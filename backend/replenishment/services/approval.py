from __future__ import annotations

import os
import re
from typing import Dict, Iterable, List, Tuple

from django.conf import settings
from django.db import DatabaseError, connection

from replenishment import rules

_TABLE_COLUMNS_CACHE: dict[tuple[str, str, str], set[str]] = {}

_LOGISTICS_MANAGER_APPROVER_ROLES = {
    "LOGISTICS",
    "LOGISTICS_MANAGER",
    "ODPEM_LOGISTICS_MANAGER",
    "SYSTEM_ADMINISTRATOR",
}

_SENIOR_DIRECTOR_APPROVER_ROLES = {
    "EXECUTIVE",
    "ODPEM_DIR_PEOD",
    "SENIOR_DIRECTOR",
    "SENIOR_DIRECTOR_DONATIONS",
    "SYSTEM_ADMINISTRATOR",
}

_DIRECTOR_PEOD_APPROVER_ROLES = {
    "EXECUTIVE",
    "ODPEM_DIR_PEOD",
    "DIRECTOR_PEOD",
    "SYSTEM_ADMINISTRATOR",
}

_LOGISTICS_SUBMITTER_ROLES = {
    "LOGISTICS",
    "LOGISTICS_MANAGER",
    "LOGISTICS_OFFICER",
    "ODPEM_LOGISTICS_MANAGER",
}

_TEST_APPROVER_OVERLAY = {
    "logistics_manager": {"TST_LOGISTICS_MANAGER"},
    "senior_director": {"TST_DIR_PEOD"},
    "director_peod": {"TST_DIR_PEOD"},
}

_ROLE_ALIASES = {
    "LOGISTICS": {"TST_LOGISTICS_MANAGER"},
    "LOGISTICS_MANAGER": {"TST_LOGISTICS_MANAGER"},
    "ODPEM_LOGISTICS_MANAGER": {"TST_LOGISTICS_MANAGER"},
    "LOGISTICS_OFFICER": {"TST_LOGISTICS_OFFICER"},
    "TST_LOGISTICS_MANAGER": {
        "LOGISTICS",
        "LOGISTICS_MANAGER",
        "ODPEM_LOGISTICS_MANAGER",
    },
    "TST_LOGISTICS_OFFICER": {"LOGISTICS_OFFICER"},
    "ODPEM_DIR_PEOD": {"DIRECTOR_PEOD", "TST_DIR_PEOD"},
    "DIRECTOR_PEOD": {"ODPEM_DIR_PEOD", "TST_DIR_PEOD"},
    "SENIOR_DIRECTOR": {"TST_DIR_PEOD"},
    "SENIOR_DIRECTOR_DONATIONS": {"TST_DIR_PEOD"},
    "TST_DIR_PEOD": {
        "ODPEM_DIR_PEOD",
        "DIRECTOR_PEOD",
        "SENIOR_DIRECTOR",
        "SENIOR_DIRECTOR_DONATIONS",
    },
    "ODPEM_DG": {"DIRECTOR_GENERAL", "TST_DG"},
    "DIRECTOR_GENERAL": {"ODPEM_DG", "TST_DG"},
    "ODPEM_DDG": {"TST_DG"},
    "TST_DG": {"ODPEM_DG", "DIRECTOR_GENERAL", "ODPEM_DDG"},
}


def _with_test_roles(base_roles: set[str], overlay_key: str) -> set[str]:
    roles = set(base_roles)
    if getattr(settings, "ENABLE_TEST_ROLES", False):
        roles.update(_TEST_APPROVER_OVERLAY.get(overlay_key, set()))
    return roles


LOGISTICS_MANAGER_APPROVER_ROLES = _with_test_roles(
    _LOGISTICS_MANAGER_APPROVER_ROLES,
    "logistics_manager",
)
SENIOR_DIRECTOR_APPROVER_ROLES = _with_test_roles(
    _SENIOR_DIRECTOR_APPROVER_ROLES,
    "senior_director",
)
DIRECTOR_PEOD_APPROVER_ROLES = _with_test_roles(
    _DIRECTOR_PEOD_APPROVER_ROLES,
    "director_peod",
)
LOGISTICS_SUBMITTER_ROLES = _with_test_roles(
    _LOGISTICS_SUBMITTER_ROLES,
    "logistics_manager",
)

APPROVAL_ROLE_MAP = {
    "Logistics Manager (Kemar)": LOGISTICS_MANAGER_APPROVER_ROLES,
    "Senior Director (Andrea)": SENIOR_DIRECTOR_APPROVER_ROLES,
    "Director General (Marcus)": DIRECTOR_PEOD_APPROVER_ROLES,
    "DG + PPC Endorsement": DIRECTOR_PEOD_APPROVER_ROLES,
    "DG + PPC + Cabinet": DIRECTOR_PEOD_APPROVER_ROLES,
}


def _normalize_role_code(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.upper().replace("-", "_").replace(" ", "_")
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    return normalized


def _expand_role_aliases(roles: set[str]) -> set[str]:
    expanded = set(roles)
    for role in list(roles):
        expanded.update(_ROLE_ALIASES.get(role, set()))
    return expanded


def _normalized_role_set(values: object) -> set[str]:
    if values is None:
        return set()

    if isinstance(values, str):
        candidates: list[object]
        if "," in values:
            candidates = [part.strip() for part in values.split(",")]
        else:
            candidates = [values]
    elif isinstance(values, (list, tuple, set)):
        candidates = list(values)
    else:
        candidates = [values]

    roles: set[str] = set()
    for candidate in candidates:
        normalized = _normalize_role_code(candidate)
        if normalized:
            roles.add(normalized)
    return _expand_role_aliases(roles)


def _schema_name() -> str:
    configured = str(os.getenv("DMIS_DB_SCHEMA", "")).strip()
    if configured and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", configured):
        return configured

    if connection.vendor == "postgresql":
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_schema()")
                row = cursor.fetchone()
            detected = str((row[0] if row else "") or "").strip()
            if detected and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", detected):
                return detected
        except DatabaseError:
            pass

    return "public"


def _table_columns(table_name: str) -> set[str]:
    schema = _schema_name()
    cache_key = (connection.vendor, schema, table_name)
    if cache_key in _TABLE_COLUMNS_CACHE:
        return _TABLE_COLUMNS_CACHE[cache_key]

    columns: set[str] = set()
    try:
        with connection.cursor() as cursor:
            if connection.vendor == "postgresql":
                cursor.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = %s AND table_name = %s
                    """,
                    [schema, table_name],
                )
                columns = {str(row[0]) for row in cursor.fetchall()}
            elif connection.vendor == "sqlite":
                cursor.execute(f"PRAGMA table_info({table_name})")
                columns = {str(row[1]) for row in cursor.fetchall()}
    except DatabaseError:
        columns = set()

    _TABLE_COLUMNS_CACHE[cache_key] = columns
    return columns


def _to_int_or_none(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _selected_method(record: Dict[str, object] | None) -> str:
    if not isinstance(record, dict):
        return ""
    raw_method = record.get("selected_method")
    if raw_method is None:
        snapshot = record.get("snapshot")
        if isinstance(snapshot, dict):
            raw_method = snapshot.get("selected_method")
    return str(raw_method or "").strip().upper()


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


def resolve_submitter_roles(record: Dict[str, object] | None) -> set[str]:
    if not isinstance(record, dict):
        return set()

    submitter = str(record.get("submitted_by") or record.get("created_by") or "").strip()
    if not submitter:
        return set()

    user_columns = _table_columns("user")
    if "user_id" not in user_columns:
        return set()

    user_table = connection.ops.quote_name("user")
    where_parts: list[str] = []
    params: list[object] = []
    submitter_user_id = _to_int_or_none(submitter)
    if submitter_user_id is not None:
        where_parts.append("user_id = %s")
        params.append(submitter_user_id)
    if "username" in user_columns:
        where_parts.append("username = %s")
        params.append(submitter)
    if "email" in user_columns:
        where_parts.append("email = %s")
        params.append(submitter)
    if not where_parts:
        return set()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT user_id FROM {user_table} WHERE {' OR '.join(where_parts)} LIMIT 1",
                params,
            )
            user_row = cursor.fetchone()
        user_id = _to_int_or_none(user_row[0] if user_row else None)
    except DatabaseError:
        return set()

    if user_id is None:
        return set()

    if not _table_columns("user_role") or not _table_columns("role"):
        return set()

    if connection.vendor == "postgresql":
        schema = _schema_name()
        quoted_schema = connection.ops.quote_name(schema)
        user_role_table = f"{quoted_schema}.{connection.ops.quote_name('user_role')}"
        role_table = f"{quoted_schema}.{connection.ops.quote_name('role')}"
    else:
        user_role_table = connection.ops.quote_name("user_role")
        role_table = connection.ops.quote_name("role")

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT DISTINCT r.code
                FROM {user_role_table} ur
                JOIN {role_table} r ON r.id = ur.role_id
                WHERE ur.user_id = %s
                """,
                [user_id],
            )
            rows = cursor.fetchall()
    except DatabaseError:
        return set()

    return {str(row[0]).upper() for row in rows if row and row[0]}


def required_roles_for_approval(
    approval: Dict[str, object],
    *,
    record: Dict[str, object] | None = None,
    submitter_roles: Iterable[str] | None = None,
) -> set[str]:
    method = _selected_method(record)
    normalized_submitter_roles = _normalized_role_set(submitter_roles)

    if method == "A":
        # Transfer: Logistics Manager; Director PEOD can approve on behalf
        # when the requester is a logistics role.
        roles = set(LOGISTICS_MANAGER_APPROVER_ROLES)
        if normalized_submitter_roles.intersection(LOGISTICS_SUBMITTER_ROLES):
            roles.update(DIRECTOR_PEOD_APPROVER_ROLES)
        return _expand_role_aliases(roles)

    if method == "B":
        # Donation: Senior Director (donations) with PEOD-capable fallback.
        return _expand_role_aliases(set(SENIOR_DIRECTOR_APPROVER_ROLES))

    if method == "C":
        # Procurement: in-system approval handled by Director PEOD.
        # DG confirmation is a manual step outside the system.
        return _expand_role_aliases(set(DIRECTOR_PEOD_APPROVER_ROLES))

    approver_role = str(approval.get("approver_role") or "")
    return _expand_role_aliases(
        set(APPROVAL_ROLE_MAP.get(approver_role, DIRECTOR_PEOD_APPROVER_ROLES))
    )


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
