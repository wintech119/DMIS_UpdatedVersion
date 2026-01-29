import os
from typing import Dict, List, Tuple

SAFETY_STOCK_FACTOR = 1.25

WINDOWS_V40: Dict[str, Dict[str, int]] = {
    "SURGE": {"demand_hours": 6, "planning_hours": 24},
    "STABILIZED": {"demand_hours": 24, "planning_hours": 72},
    "BASELINE": {"demand_hours": 72, "planning_hours": 168},
}

WINDOWS_V41: Dict[str, Dict[str, int]] = {
    "SURGE": {"demand_hours": 6, "planning_hours": 72},
    "STABILIZED": {"demand_hours": 72, "planning_hours": 168},
    "BASELINE": {"demand_hours": 720, "planning_hours": 720},
}

FRESHNESS_THRESHOLDS: Dict[str, Dict[str, int]] = {
    "SURGE": {"fresh_max_hours": 2, "warn_max_hours": 4},
    "STABILIZED": {"fresh_max_hours": 6, "warn_max_hours": 12},
    "BASELINE": {"fresh_max_hours": 24, "warn_max_hours": 48},
}

DEFAULT_WINDOWS_VERSION = os.getenv("NEEDS_WINDOWS_VERSION", "v40").lower()

STRICT_INBOUND_TRANSFER_RULE = "INBOUND_WHEN_DISPATCHED_OR_LATER"
STRICT_INBOUND_DONATION_RULE = "CONFIRMED_AND_IN_TRANSIT_OR_SHIPPED"
STRICT_INBOUND_PROCUREMENT_RULE = "APPROVED_AND_SHIPMENT_SHIPPED_OR_IN_TRANSIT"


def get_windows_version() -> str:
    return os.getenv("NEEDS_WINDOWS_VERSION", "v40").lower()


def get_phase_windows(phase: str) -> Dict[str, int]:
    version = get_windows_version()
    windows = WINDOWS_V41 if version == "v41" else WINDOWS_V40
    return windows[phase]


def _parse_codes_env(name: str, default: List[str]) -> List[str]:
    raw = os.getenv(name)
    if raw is None:
        return list(default)
    codes = [code.strip().upper() for code in raw.split(",") if code.strip()]
    return codes or list(default)


def resolve_strict_inbound_transfer_codes() -> Tuple[List[str], List[str]]:
    codes = _parse_codes_env("TRANSFER_DISPATCHED_CODES", ["D"])
    warnings: List[str] = []
    if codes != ["D"]:
        warnings.append("strict_inbound_mapping_best_effort")
    return codes, warnings


def resolve_strict_inbound_donation_codes() -> Tuple[List[str], List[str]]:
    warnings: List[str] = []
    confirmed = _parse_codes_env("DONATION_CONFIRMED_CODES", ["V"])
    in_transit = _parse_codes_env("DONATION_IN_TRANSIT_CODES", ["V"])

    allowed = {"E", "V", "P"}
    confirmed_filtered = [code for code in confirmed if code in allowed]
    in_transit_filtered = [code for code in in_transit if code in allowed]

    if len(confirmed_filtered) != len(confirmed) or len(in_transit_filtered) != len(
        in_transit
    ):
        warnings.append("donation_status_code_invalid_filtered")

    if not confirmed_filtered:
        confirmed_filtered = ["V"]
    if not in_transit_filtered:
        in_transit_filtered = ["V"]

    intersection = [code for code in confirmed_filtered if code in in_transit_filtered]
    if intersection:
        codes = intersection
    else:
        codes = sorted(set(confirmed_filtered + in_transit_filtered))
        warnings.append("strict_inbound_mapping_best_effort")

    return codes, warnings
