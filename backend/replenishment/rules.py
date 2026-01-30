import os
from typing import Dict, List, Tuple

SAFETY_STOCK_FACTOR = 1.25


def _get_int_env(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _get_str_env(name: str, default: str) -> str:
    raw = os.getenv(name)
    if raw is None:
        return default
    stripped = raw.strip()
    return stripped or default

PHASES = ("SURGE", "STABILIZED", "BASELINE")

WINDOWS_V40_LEGACY: Dict[str, Dict[str, int]] = {
    "SURGE": {"demand_hours": 6, "planning_hours": 24},
    "STABILIZED": {"demand_hours": 24, "planning_hours": 72},
    "BASELINE": {"demand_hours": 72, "planning_hours": 168},
}

WINDOWS_DEFAULT: Dict[str, Dict[str, int]] = {
    "SURGE": {"demand_hours": 6, "planning_hours": 72},
    "STABILIZED": {"demand_hours": 72, "planning_hours": 168},
    "BASELINE": {"demand_hours": 720, "planning_hours": 720},
}

WINDOWS_BY_VERSION: Dict[str, Dict[str, Dict[str, int]]] = {
    "v41": WINDOWS_DEFAULT,
    "v40": WINDOWS_V40_LEGACY,
}

FRESHNESS_THRESHOLDS: Dict[str, Dict[str, int]] = {
    "SURGE": {"fresh_max_hours": 2, "warn_max_hours": 4},
    "STABILIZED": {"fresh_max_hours": 6, "warn_max_hours": 12},
    "BASELINE": {"fresh_max_hours": 24, "warn_max_hours": 48},
}

DONATION_LEAD_TIME_HOURS = _get_int_env("NEEDS_DONATION_LEAD_TIME_HOURS", 24)
PROCUREMENT_LEAD_TIME_HOURS = _get_int_env("NEEDS_PROCUREMENT_LEAD_TIME_HOURS", 336)

SAFETY_BUFFER_MULTIPLIERS: Dict[str, float] = {
    "SURGE": 0.5,
    "STABILIZED": 0.25,
    "BASELINE": 0.1,
}

GOJEP_NOTE_LABEL = "Proceed in GOJEP; update status here"
GOJEP_URL = _get_str_env("NEEDS_GOJEP_URL", "https://gojep.gov.jm")

PROCUREMENT_INBOUND_ELIGIBLE_STATUSES = {
    "SHIPPED",
    "IN_TRANSIT",
    "PARTIALLY_RECEIVED",
}

PROCUREMENT_APPROVAL_RULES: Dict[str, List[Dict[str, object]]] = {
    "goods_services": [
        {
            "max_jmd": 3_000_000,
            "tier": "Below Tier 1",
            "approver_baseline": "Logistics Manager (Kemar)",
            "approver_surge": "Logistics Manager (Kemar)",
            "methods": ["Single-Source", "Request for Quotations"],
        },
        {
            "max_jmd": 15_000_000,
            "tier": "Below Tier 1",
            "approver_baseline": "Senior Director (Andrea)",
            "approver_surge": "Logistics Manager (Kemar)",
            "methods": ["Restricted Bidding (min. 3 suppliers)"],
        },
        {
            "max_jmd": 40_000_000,
            "tier": "Below Tier 1",
            "approver_baseline": "Director General (Marcus)",
            "approver_surge": "Senior Director (Andrea)",
            "methods": ["Open National Competitive Bidding"],
        },
        {
            "max_jmd": 60_000_000,
            "tier": "Tier 1",
            "approver_baseline": "Director General (Marcus)",
            "approver_surge": "Director General (Marcus)",
            "methods": ["Open International or National Competitive Bidding"],
        },
        {
            "max_jmd": 100_000_000,
            "tier": "Tier 2",
            "approver_baseline": "DG + PPC Endorsement",
            "approver_surge": "DG + PPC Endorsement",
            "methods": ["Open International Competitive Bidding"],
        },
        {
            "max_jmd": None,
            "tier": "Tier 3",
            "approver_baseline": "DG + PPC + Cabinet",
            "approver_surge": "DG + PPC + Cabinet",
            "methods": ["Open International Competitive Bidding"],
        },
    ],
    "works": [
        {
            "max_jmd": 5_000_000,
            "tier": "Below Tier 1",
            "approver_baseline": "Logistics Manager (Kemar)",
            "approver_surge": "Logistics Manager (Kemar)",
            "methods": ["Single-Source", "Request for Quotations"],
        },
        {
            "max_jmd": 15_000_000,
            "tier": "Below Tier 1",
            "approver_baseline": "Senior Director (Andrea)",
            "approver_surge": "Logistics Manager (Kemar)",
            "methods": ["Restricted Bidding (min. 3 suppliers)"],
        },
        {
            "max_jmd": 40_000_000,
            "tier": "Below Tier 1",
            "approver_baseline": "Director General (Marcus)",
            "approver_surge": "Senior Director (Andrea)",
            "methods": ["Open National Competitive Bidding"],
        },
        {
            "max_jmd": 60_000_000,
            "tier": "Tier 1",
            "approver_baseline": "Director General (Marcus)",
            "approver_surge": "Director General (Marcus)",
            "methods": ["Open International or National Competitive Bidding"],
        },
        {
            "max_jmd": 100_000_000,
            "tier": "Tier 2",
            "approver_baseline": "DG + PPC Endorsement",
            "approver_surge": "DG + PPC Endorsement",
            "methods": ["Open International Competitive Bidding"],
        },
        {
            "max_jmd": None,
            "tier": "Tier 3",
            "approver_baseline": "DG + PPC + Cabinet",
            "approver_surge": "DG + PPC + Cabinet",
            "methods": ["Open International Competitive Bidding"],
        },
    ],
}

DEFAULT_PROCUREMENT_CATEGORY = "goods_services"

DEFAULT_WINDOWS_VERSION = "v41"

STRICT_INBOUND_TRANSFER_RULE = "INBOUND_WHEN_DISPATCHED_OR_LATER"
STRICT_INBOUND_DONATION_RULE = "CONFIRMED_AND_IN_TRANSIT_OR_SHIPPED"
STRICT_INBOUND_PROCUREMENT_RULE = "APPROVED_AND_SHIPMENT_SHIPPED_OR_IN_TRANSIT"


def get_windows_version() -> str:
    return os.getenv("NEEDS_WINDOWS_VERSION", DEFAULT_WINDOWS_VERSION).lower()


def get_phase_windows(phase: str) -> Dict[str, int]:
    version = get_windows_version()
    windows = WINDOWS_BY_VERSION.get(version, WINDOWS_DEFAULT)
    if phase not in windows:
        raise ValueError(f"invalid phase, expected one of: {list(windows.keys())}")
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
    # Prefer NEEDS_* config as the documented primary, but allow explicit override.
    strict_default = _parse_codes_env("NEEDS_STRICT_INBOUND_DONATION_STATUSES", ["V", "P"])
    confirmed = _parse_codes_env("DONATION_CONFIRMED_CODES", strict_default)
    in_transit = _parse_codes_env("DONATION_IN_TRANSIT_CODES", strict_default)

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


def get_procurement_approval(
    est_total_cost_jmd: float | None,
    phase: str,
    category: str | None = None,
) -> Tuple[Dict[str, object], List[str]]:
    warnings: List[str] = []
    phase_upper = str(phase).upper()

    if est_total_cost_jmd is None:
        warnings.append("procurement_cost_unavailable")
        cost = 0.0
    else:
        try:
            cost = float(est_total_cost_jmd)
        except (TypeError, ValueError):
            warnings.append("procurement_cost_invalid")
            cost = 0.0

    category_key = (category or DEFAULT_PROCUREMENT_CATEGORY).lower()
    if category is None:
        warnings.append("procurement_category_unavailable")
    if category_key not in PROCUREMENT_APPROVAL_RULES:
        warnings.append("procurement_category_invalid")
        category_key = DEFAULT_PROCUREMENT_CATEGORY

    ruleset = PROCUREMENT_APPROVAL_RULES[category_key]
    selected = ruleset[-1]
    for rule in ruleset:
        max_jmd = rule.get("max_jmd")
        if max_jmd is None or cost <= float(max_jmd):
            selected = rule
            break

    approver = (
        selected["approver_surge"]
        if phase_upper == "SURGE"
        else selected["approver_baseline"]
    )

    approval = {
        "tier": selected["tier"],
        "approver_role": approver,
        "methods_allowed": list(selected["methods"]),
    }
    return approval, warnings
