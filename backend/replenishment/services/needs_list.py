from __future__ import annotations

from typing import Dict, Iterable, List, Tuple

from django.utils import timezone

from replenishment import rules


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
    burn_rate_per_hour: float,
    planning_window_hours: int,
    safety_factor: float,
    available: float,
    inbound_strict: float,
) -> float:
    demand = burn_rate_per_hour * planning_window_hours * safety_factor
    gap = demand - (available + inbound_strict)
    return max(0.0, float(gap))


def allocate_horizons(
    gap_qty: float,
    horizon_a_hours: int,
    horizon_b_hours: int,
    procurement_available: bool,
) -> Tuple[Dict[str, Dict[str, float | None]], List[str]]:
    warnings: List[str] = []
    total_hours = max(horizon_a_hours + horizon_b_hours, 1)

    if gap_qty <= 0:
        a_qty = 0.0
        b_qty = 0.0
    else:
        a_qty = gap_qty * (horizon_a_hours / total_hours) if horizon_a_hours > 0 else 0.0
        b_qty = gap_qty - a_qty

    c_qty: float | None = 0.0 if procurement_available else None
    if not procurement_available:
        warnings.append("procurement_unavailable_in_schema")
        if gap_qty > 0:
            warnings.append("procurement_trigger_best_effort")

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
    mapping_best_effort: bool,
) -> Tuple[str, List[str], List[str]]:
    warnings_out = list(dict.fromkeys(warnings))
    reasons: List[str] = []

    if mapping_best_effort and "strict_inbound_mapping_best_effort" not in warnings_out:
        warnings_out.append("strict_inbound_mapping_best_effort")

    if not procurement_available and "procurement_unavailable_in_schema" not in warnings_out:
        warnings_out.append("procurement_unavailable_in_schema")

    level = "high"
    if "db_unavailable_preview_stub" in warnings_out:
        level = "low"
        reasons.append("db_unavailable_preview_stub")
    elif burn_source == "none":
        level = "low"
        reasons.append("burn_data_missing")
    elif mapping_best_effort:
        level = "medium"
        reasons.append("strict_inbound_mapping_best_effort")
    elif not procurement_available:
        level = "medium"
        reasons.append("procurement_unavailable_in_schema")
    elif burn_source == "reliefrqst":
        level = "medium"
        reasons.append("burn_proxy_reliefrqst")
    else:
        reasons.append("burn_proxy_reliefpkg")

    return level, reasons, warnings_out


def merge_warnings(base: Iterable[str], extra: Iterable[str]) -> List[str]:
    return list(dict.fromkeys(list(base) + list(extra)))


def compute_time_to_stockout_hours(
    burn_rate_per_hour: float, available: float, inbound_strict: float
) -> float | None:
    if burn_rate_per_hour <= 0:
        return None
    return (available + inbound_strict) / burn_rate_per_hour


def compute_freshness_state(
    phase: str, inventory_as_of, as_of_dt
) -> Tuple[str, List[str], float | None]:
    if not inventory_as_of:
        return "unknown", ["inventory_timestamp_unavailable"], None

    if hasattr(inventory_as_of, "isoformat"):
        inventory_dt = inventory_as_of
    else:
        return "unknown", ["inventory_timestamp_unavailable"], None

    if timezone.is_naive(inventory_dt):
        inventory_dt = timezone.make_aware(
            inventory_dt, timezone.get_current_timezone() or timezone.utc
        )

    age_seconds = (as_of_dt - inventory_dt).total_seconds()
    age_hours = max(age_seconds / 3600.0, 0.0)
    thresholds = rules.FRESHNESS_THRESHOLDS.get(phase, {})
    fresh_max = thresholds.get("fresh_max_hours", 0)
    warn_max = thresholds.get("warn_max_hours", 0)

    if age_hours <= fresh_max:
        return "fresh", [], age_hours
    if age_hours <= warn_max:
        return "warn", [], age_hours
    return "stale", [], age_hours


def build_preview_items(
    item_ids: List[int],
    available_by_item: Dict[int, float],
    inbound_donations_by_item: Dict[int, float],
    inbound_transfers_by_item: Dict[int, float],
    burn_by_item: Dict[int, float],
    demand_window_hours: int,
    planning_window_hours: int,
    safety_factor: float,
    horizon_a_hours: int,
    horizon_b_hours: int,
    burn_source: str,
    as_of_dt,
    phase: str,
    inventory_as_of,
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
        burn_rate_per_hour = (
            burn_total / demand_window_hours if demand_window_hours else 0.0
        )
        gap = compute_gap(
            burn_rate_per_hour,
            planning_window_hours,
            safety_factor,
            available,
            inbound_strict,
        )

        horizon, horizon_warnings = allocate_horizons(
            gap, horizon_a_hours, horizon_b_hours, procurement_available=False
        )
        mapping_best_effort = "strict_inbound_mapping_best_effort" in base_warnings
        confidence_level, reasons, item_warnings = compute_confidence_and_warnings(
            burn_source=burn_source,
            warnings=base_warnings + horizon_warnings,
            procurement_available=False,
            mapping_best_effort=mapping_best_effort,
        )
        freshness_state, freshness_warnings, age_hours = compute_freshness_state(
            phase, inventory_as_of, as_of_dt
        )
        item_warnings = merge_warnings(item_warnings, freshness_warnings)
        warnings = merge_warnings(warnings, item_warnings)

        time_to_stockout = compute_time_to_stockout_hours(
            burn_rate_per_hour, available, inbound_strict
        )

        items.append(
            {
                "item_id": item_id,
                "available_qty": round(available, 2),
                "inbound_strict_qty": round(inbound_strict, 2),
                "burn_rate_per_hour": round(burn_rate_per_hour, 4),
                "gap_qty": round(gap, 2),
                "time_to_stockout_hours": None
                if time_to_stockout is None
                else round(time_to_stockout, 2),
                "horizon": horizon,
                "confidence": {"level": confidence_level, "reasons": reasons},
                "warnings": item_warnings,
                "freshness": {
                    "state": freshness_state,
                    "inventory_as_of": inventory_as_of.isoformat()
                    if inventory_as_of
                    else None,
                    "age_hours": None if age_hours is None else round(age_hours, 2),
                    "demand_window_hours": demand_window_hours,
                    "planning_window_hours": planning_window_hours,
                },
            }
        )

    return items, warnings
