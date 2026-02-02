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

    # Category is not modeled at needs-list level; default category fallback is expected here.
    approval, approval_warnings = rules.get_procurement_approval(total_cost, phase)
    warnings.extend(approval_warnings)
    rationale = "Tier computed from estimated total cost."
    return approval, warnings, rationale


def required_roles_for_approval(approval: Dict[str, object]) -> set[str]:
    approver_role = str(approval.get("approver_role") or "")
    return APPROVAL_ROLE_MAP.get(approver_role, {"EXECUTIVE"})


def evaluate_appendix_c_authority(
    items: Iterable[Dict[str, object]],
) -> Tuple[List[str], bool]:
    warnings: List[str] = []
    escalation_required = False

    for item in items:
        horizon = item.get("horizon") or {}
        horizon_a = (horizon.get("A") or {}).get("recommended_qty") or 0.0
        horizon_b = (horizon.get("B") or {}).get("recommended_qty") or 0.0

        if horizon_a and float(horizon_a) > 0:
            transfer_scope = item.get("transfer_scope")
            transfer_qty = item.get("transfer_qty") or horizon_a
            if not transfer_scope:
                warnings.append("transfer_scope_unavailable")
            else:
                scope = str(transfer_scope).lower()
                if scope == "cross_parish":
                    if float(transfer_qty) > 500:
                        warnings.append("transfer_cross_parish_over_500")
                        escalation_required = True
                elif scope != "same_parish":
                    warnings.append("transfer_scope_unrecognized")

        if horizon_b and float(horizon_b) > 0:
            donation_restriction = item.get("donation_restriction")
            if not donation_restriction:
                warnings.append("donation_restriction_unavailable")
            else:
                restriction = str(donation_restriction).lower()
                if restriction in {"restricted", "earmarked"}:
                    warnings.append("donation_restriction_escalation_required")
                    escalation_required = True
                elif restriction != "verified":
                    warnings.append("donation_restriction_unrecognized")

    return list(dict.fromkeys(warnings)), escalation_required
