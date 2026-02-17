from __future__ import annotations

from typing import Dict, Iterable, List, Tuple

from replenishment import rules


LOGISTICS_MANAGER_APPROVER_ROLES = {
    "LOGISTICS",
    "LOGISTICS_MANAGER",
    "ODPEM_LOGISTICS_MANAGER",
    "TST_LOGISTICS_MANAGER",
    "SYSTEM_ADMINISTRATOR",
}

SENIOR_DIRECTOR_APPROVER_ROLES = {
    "EXECUTIVE",
    "ODPEM_DIR_PEOD",
    "SENIOR_DIRECTOR",
    "TST_DIR_PEOD",
    "SYSTEM_ADMINISTRATOR",
}

DG_APPROVER_ROLES = {
    "EXECUTIVE",
    "ODPEM_DG",
    "ODPEM_DDG",
    "DIRECTOR_GENERAL",
    "TST_DG",
    "SYSTEM_ADMINISTRATOR",
}

APPROVAL_ROLE_MAP = {
    "Logistics Manager (Kemar)": LOGISTICS_MANAGER_APPROVER_ROLES,
    "Senior Director (Andrea)": SENIOR_DIRECTOR_APPROVER_ROLES,
    "Director General (Marcus)": DG_APPROVER_ROLES,
    "DG + PPC Endorsement": DG_APPROVER_ROLES,
    "DG + PPC + Cabinet": DG_APPROVER_ROLES,
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
        if required_qty <= 0:
            # Do not force conservative approval when there is no quantity to cost.
            continue
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
    phase: str,
    total_cost: float | None,
    cost_missing: bool,
    selected_method: str | None = None,
) -> Tuple[Dict[str, object], List[str], str]:
    method = str(selected_method or "").upper()
    if method == "A":
        # Transfer approvals are not procurement-cost driven.
        return (
            {
                "tier": "Below Tier 1",
                "approver_role": "Logistics Manager (Kemar)",
                "methods_allowed": ["Transfer"],
            },
            [],
            "Transfer workflow selected; transfer approval path applied.",
        )

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
    return APPROVAL_ROLE_MAP.get(approver_role, DG_APPROVER_ROLES)


def evaluate_appendix_c_authority(
    items: Iterable[Dict[str, object]],
) -> Tuple[List[str], bool]:
    warnings: List[str] = []
    escalation_required = False

    def _safe_float(value: object) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    for item in items:
        horizon = item.get("horizon") or {}
        horizon_a = _safe_float((horizon.get("A") or {}).get("recommended_qty"))
        horizon_b = _safe_float((horizon.get("B") or {}).get("recommended_qty"))

        if horizon_a > 0:
            transfer_scope = item.get("transfer_scope")
            transfer_qty = _safe_float(item.get("transfer_qty") or horizon_a)
            if not transfer_scope:
                warnings.append("transfer_scope_unavailable")
            else:
                scope = str(transfer_scope).lower()
                if scope == "cross_parish":
                    if transfer_qty > 500:
                        warnings.append("transfer_cross_parish_over_500")
                        escalation_required = True
                elif scope != "same_parish":
                    warnings.append("transfer_scope_unrecognized")

        if horizon_b > 0:
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
