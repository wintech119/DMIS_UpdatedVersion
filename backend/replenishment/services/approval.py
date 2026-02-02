from __future__ import annotations

from typing import Dict, Iterable, List, Tuple

from replenishment import rules


APPROVAL_ROLE_MAP = {
    "Logistics Manager (Kemar)": {"LOGISTICS"},
    "Senior Director (Andrea)": {"EXECUTIVE"},
    "Director General (Marcus)": {"EXECUTIVE"},
    "DG + PPC Endorsement": {"EXECUTIVE"},
    "DG + PPC + Cabinet": {"EXECUTIVE"},
}


def compute_needs_list_totals(
    items: Iterable[Dict[str, object]],
) -> Tuple[float, float | None, List[str]]:
    total_required_qty = 0.0
    total_estimated_cost = 0.0
    cost_missing = False

    for item in items:
        required_qty = float(item.get("required_qty") or 0.0)
        total_required_qty += required_qty
        unit_cost = None
        if "est_unit_cost" in item:
            unit_cost = item.get("est_unit_cost")
        elif "procurement" in item and isinstance(item["procurement"], dict):
            unit_cost = item["procurement"].get("est_unit_cost")

        if unit_cost is None:
            cost_missing = True
            continue

        try:
            total_estimated_cost += required_qty * float(unit_cost)
        except (TypeError, ValueError):
            cost_missing = True

    warnings: List[str] = []
    if cost_missing:
        warnings.append("cost_missing_for_approval")
        total_estimated_cost = None

    return total_required_qty, total_estimated_cost, warnings


def determine_approval_tier(
    phase: str, total_cost: float | None, cost_missing: bool
) -> Tuple[Dict[str, object], List[str], str]:
    warnings: List[str] = []
    if cost_missing or total_cost is None:
        ruleset = rules.PROCUREMENT_APPROVAL_RULES[rules.DEFAULT_PROCUREMENT_CATEGORY]
        approval = {
            "tier": ruleset[-1]["tier"],
            "approver_role": ruleset[-1][
                "approver_surge" if phase == "SURGE" else "approver_baseline"
            ],
            "methods_allowed": list(ruleset[-1]["methods"]),
        }
        warnings.append("approval_tier_conservative")
        rationale = "Costs missing; highest tier required."
        return approval, warnings, rationale

    approval, approval_warnings = rules.get_procurement_approval(total_cost, phase)
    warnings.extend(approval_warnings)
    rationale = "Tier computed from estimated total cost."
    return approval, warnings, rationale


def required_roles_for_approval(approval: Dict[str, object]) -> set[str]:
    approver_role = str(approval.get("approver_role") or "")
    return APPROVAL_ROLE_MAP.get(approver_role, {"EXECUTIVE"})
