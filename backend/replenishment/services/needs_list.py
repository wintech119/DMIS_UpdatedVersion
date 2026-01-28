from __future__ import annotations

from typing import Dict, Iterable, List, Tuple


def collect_item_ids(*sources: Dict[int, float]) -> List[int]:
    item_ids = set()
    for source in sources:
        item_ids.update(source.keys())
    return sorted(item_ids)


def compute_inbound_strict(
    item_id: int,
    inbound_donations_by_item: Dict[int, float],
    inbound_transfers_by_item: Dict[int, float],
) -> float:
    return float(inbound_donations_by_item.get(item_id, 0.0)) + float(
        inbound_transfers_by_item.get(item_id, 0.0)
    )


def compute_gap(
    burn_rate_per_day: float,
    planning_window_days: int,
    safety_factor: float,
    available: float,
    inbound_strict: float,
) -> float:
    demand = burn_rate_per_day * planning_window_days * safety_factor
    gap = demand - (available + inbound_strict)
    return max(0.0, float(gap))


def allocate_horizons(
    gap_qty: float, horizon_a_days: int, horizon_b_days: int, procurement_available: bool
) -> Tuple[Dict[str, Dict[str, float | None]], List[str]]:
    warnings: List[str] = []
    total_days = max(horizon_a_days + horizon_b_days, 1)

    if gap_qty <= 0:
        a_qty = 0.0
        b_qty = 0.0
    else:
        a_qty = gap_qty * (horizon_a_days / total_days) if horizon_a_days > 0 else 0.0
        b_qty = gap_qty - a_qty

    c_qty: float | None = 0.0 if procurement_available else None
    if not procurement_available:
        warnings.append("procurement_unavailable")

    return (
        {
            "A": {"recommended_qty": round(a_qty, 2)},
            "B": {"recommended_qty": round(b_qty, 2)},
            "C": {"recommended_qty": c_qty},
        },
        warnings,
    )


def compute_confidence_and_warnings(
    burn_source: str,
    warnings: Iterable[str],
    procurement_available: bool,
    transfer_semantics_tbd: bool,
) -> Tuple[str, List[str], List[str]]:
    warnings_out = list(dict.fromkeys(warnings))
    reasons: List[str] = []

    if transfer_semantics_tbd and "transfer_status_semantics_tbd" not in warnings_out:
        warnings_out.append("transfer_status_semantics_tbd")

    if not procurement_available and "procurement_unavailable" not in warnings_out:
        warnings_out.append("procurement_unavailable")

    level = "high"
    if "db_unavailable_preview_stub" in warnings_out:
        level = "low"
        reasons.append("db_unavailable_preview_stub")
    elif burn_source == "none":
        level = "low"
        reasons.append("burn_data_missing")
    elif burn_source == "reliefrqst":
        level = "medium"
        reasons.append("burn_proxy_reliefrqst")
    else:
        reasons.append("burn_proxy_reliefpkg")

    return level, reasons, warnings_out


def merge_warnings(base: Iterable[str], extra: Iterable[str]) -> List[str]:
    return list(dict.fromkeys(list(base) + list(extra)))


def build_preview_items(
    item_ids: List[int],
    available_by_item: Dict[int, float],
    inbound_donations_by_item: Dict[int, float],
    inbound_transfers_by_item: Dict[int, float],
    burn_by_item: Dict[int, float],
    planning_window_days: int,
    safety_factor: float,
    horizon_a_days: int,
    horizon_b_days: int,
    burn_source: str,
    as_of_dt,
    base_warnings: Iterable[str] | None = None,
) -> Tuple[List[Dict[str, object]], List[str]]:
    items: List[Dict[str, object]] = []
    warnings: List[str] = []
    base_warnings = list(base_warnings or [])

    for item_id in item_ids:
        available = float(available_by_item.get(item_id, 0.0))
        inbound_strict = compute_inbound_strict(
            item_id, inbound_donations_by_item, inbound_transfers_by_item
        )
        burn_total = float(burn_by_item.get(item_id, 0.0))
        burn_rate = burn_total / planning_window_days if planning_window_days else 0.0
        gap = compute_gap(
            burn_rate, planning_window_days, safety_factor, available, inbound_strict
        )

        horizon, horizon_warnings = allocate_horizons(
            gap, horizon_a_days, horizon_b_days, procurement_available=False
        )
        confidence_level, reasons, item_warnings = compute_confidence_and_warnings(
            burn_source=burn_source,
            warnings=base_warnings + horizon_warnings,
            procurement_available=False,
            transfer_semantics_tbd=True,
        )
        warnings = merge_warnings(warnings, item_warnings)

        items.append(
            {
                "item_id": item_id,
                "available_qty": round(available, 2),
                "inbound_strict_qty": round(inbound_strict, 2),
                "burn_rate_per_day": round(burn_rate, 4),
                "gap_qty": round(gap, 2),
                "horizon": horizon,
                "confidence": {"level": confidence_level, "reasons": reasons},
                "warnings": item_warnings,
                "freshness": {
                    "inventory_as_of": as_of_dt.isoformat(),
                    "burn_window_days": planning_window_days,
                },
            }
        )

    return items, warnings
