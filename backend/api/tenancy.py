from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable

from django.conf import settings
from django.db import DatabaseError, connection

from api.authentication import Principal
from api.rbac import (
    PERM_NATIONAL_ACT_CROSS_TENANT,
    PERM_NATIONAL_READ_ALL_TENANTS,
)


_NEOC_TENANT_TYPES = {"NEOC", "NATIONAL_LEVEL"}
_NEOC_TENANT_CODES = {"NEOC", "ODPEM_NEOC"}
_CROSS_TENANT_POLICY_KEY = "approval.cross_tenant_actions"


@dataclass(frozen=True)
class TenantMembership:
    tenant_id: int
    tenant_code: str
    tenant_name: str
    tenant_type: str
    is_primary: bool
    access_level: str | None


@dataclass(frozen=True)
class TenantContext:
    requested_tenant_id: int | None
    active_tenant_id: int | None
    active_tenant_code: str | None
    active_tenant_type: str | None
    memberships: tuple[TenantMembership, ...]
    can_read_all_tenants: bool
    can_act_cross_tenant: bool

    @property
    def is_neoc(self) -> bool:
        code = _normalize_tenant_code(self.active_tenant_code)
        if code in _NEOC_TENANT_CODES:
            return True
        return _normalize_tenant_type(self.active_tenant_type) in _NEOC_TENANT_TYPES

    @property
    def membership_tenant_ids(self) -> set[int]:
        return {membership.tenant_id for membership in self.memberships}


def _normalize_tenant_type(value: object) -> str:
    text = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
    while "__" in text:
        text = text.replace("__", "_")
    return text


def _normalize_tenant_code(value: object) -> str:
    return _normalize_tenant_type(value)


def _parse_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _permission_set(permissions: Iterable[str]) -> set[str]:
    return {str(permission or "").strip().lower() for permission in permissions if str(permission or "").strip()}


def _parse_json_object(value: object) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        if isinstance(parsed, dict):
            return parsed
    return None


def _resolve_user_id(principal: Principal) -> int | None:
    if principal.user_id:
        parsed = _parse_int(principal.user_id)
        if parsed is not None:
            return parsed

    if not principal.username:
        return None

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT user_id FROM "user" WHERE username = %s OR email = %s LIMIT 1',
                [principal.username, principal.username],
            )
            row = cursor.fetchone()
    except DatabaseError:
        return None
    return _parse_int(row[0] if row else None)


def _tenant_by_id(tenant_id: int) -> TenantMembership | None:
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT tenant_id, tenant_code, tenant_name, tenant_type
                FROM tenant
                WHERE tenant_id = %s AND COALESCE(status_code, 'A') = 'A'
                LIMIT 1
                """,
                [tenant_id],
            )
            row = cursor.fetchone()
    except DatabaseError:
        return None
    if not row:
        return None
    return TenantMembership(
        tenant_id=int(row[0]),
        tenant_code=str(row[1] or ""),
        tenant_name=str(row[2] or ""),
        tenant_type=str(row[3] or ""),
        is_primary=False,
        access_level=None,
    )


def list_user_tenant_memberships(principal: Principal) -> tuple[TenantMembership, ...]:
    user_id = _resolve_user_id(principal)
    if user_id is None:
        return tuple()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    t.tenant_id,
                    t.tenant_code,
                    t.tenant_name,
                    t.tenant_type,
                    COALESCE(tu.is_primary_tenant, FALSE) AS is_primary_tenant,
                    tu.access_level
                FROM tenant_user tu
                JOIN tenant t ON t.tenant_id = tu.tenant_id
                WHERE
                    tu.user_id = %s
                    AND COALESCE(tu.status_code, 'A') = 'A'
                    AND COALESCE(t.status_code, 'A') = 'A'
                ORDER BY
                    COALESCE(tu.is_primary_tenant, FALSE) DESC,
                    t.tenant_id ASC
                """,
                [user_id],
            )
            rows = cursor.fetchall()
    except DatabaseError:
        return tuple()

    memberships: list[TenantMembership] = []
    for row in rows:
        memberships.append(
            TenantMembership(
                tenant_id=int(row[0]),
                tenant_code=str(row[1] or ""),
                tenant_name=str(row[2] or ""),
                tenant_type=str(row[3] or ""),
                is_primary=bool(row[4]),
                access_level=str(row[5] or "").strip() or None,
            )
        )
    return tuple(memberships)


def resolve_tenant_context(
    request,
    principal: Principal,
    permissions: Iterable[str],
) -> TenantContext:
    permission_set = _permission_set(permissions)
    can_read_all = PERM_NATIONAL_READ_ALL_TENANTS.lower() in permission_set
    can_act_cross_tenant = PERM_NATIONAL_ACT_CROSS_TENANT.lower() in permission_set

    memberships = list_user_tenant_memberships(principal)
    membership_by_id = {membership.tenant_id: membership for membership in memberships}

    query_params = getattr(request, "query_params", None)
    query_tenant_value = query_params.get("tenant_id") if hasattr(query_params, "get") else None
    requested_tenant_id = _parse_int(
        request.META.get("HTTP_X_TENANT_ID")
        or query_tenant_value
    )

    active_membership: TenantMembership | None = None
    if requested_tenant_id is not None and requested_tenant_id in membership_by_id:
        active_membership = membership_by_id[requested_tenant_id]
    elif memberships:
        active_membership = next(
            (membership for membership in memberships if membership.is_primary),
            memberships[0],
        )

    if (
        requested_tenant_id is not None
        and active_membership is None
        and can_read_all
    ):
        provisional_context = TenantContext(
            requested_tenant_id=requested_tenant_id,
            active_tenant_id=None,
            active_tenant_code=None,
            active_tenant_type=None,
            memberships=memberships,
            can_read_all_tenants=can_read_all,
            can_act_cross_tenant=can_act_cross_tenant,
        )
        if can_access_tenant(provisional_context, requested_tenant_id, write=False):
            active_membership = _tenant_by_id(requested_tenant_id)

    return TenantContext(
        requested_tenant_id=requested_tenant_id,
        active_tenant_id=active_membership.tenant_id if active_membership else None,
        active_tenant_code=active_membership.tenant_code if active_membership else None,
        active_tenant_type=active_membership.tenant_type if active_membership else None,
        memberships=memberships,
        can_read_all_tenants=can_read_all,
        can_act_cross_tenant=can_act_cross_tenant,
    )


def tenant_context_to_dict(context: TenantContext) -> dict[str, Any]:
    return {
        "requested_tenant_id": context.requested_tenant_id,
        "active_tenant_id": context.active_tenant_id,
        "active_tenant_code": context.active_tenant_code,
        "active_tenant_type": context.active_tenant_type,
        "is_neoc": context.is_neoc,
        "can_read_all_tenants": context.can_read_all_tenants,
        "can_act_cross_tenant": context.can_act_cross_tenant,
        "memberships": [
            {
                "tenant_id": membership.tenant_id,
                "tenant_code": membership.tenant_code,
                "tenant_name": membership.tenant_name,
                "tenant_type": membership.tenant_type,
                "is_primary": membership.is_primary,
                "access_level": membership.access_level,
            }
            for membership in context.memberships
        ],
    }


def resolve_warehouse_tenant_id(warehouse_id: int | None) -> int | None:
    if warehouse_id is None:
        return None

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT tenant_id
                FROM tenant_warehouse
                WHERE
                    warehouse_id = %s
                    AND effective_date <= CURRENT_DATE
                    AND (expiry_date IS NULL OR expiry_date >= CURRENT_DATE)
                ORDER BY effective_date DESC
                LIMIT 1
                """,
                [warehouse_id],
            )
            row = cursor.fetchone()
    except DatabaseError:
        row = None
    parsed = _parse_int(row[0] if row else None)
    if parsed is not None:
        return parsed

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT tenant_id FROM warehouse WHERE warehouse_id = %s LIMIT 1",
                [warehouse_id],
            )
            fallback_row = cursor.fetchone()
    except DatabaseError:
        fallback_row = None
    return _parse_int(fallback_row[0] if fallback_row else None)


def _target_tenant_allows_neoc_actions(target_tenant_id: int | None) -> bool:
    if target_tenant_id is None:
        return False
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT config_value
                FROM tenant_config
                WHERE
                    tenant_id = %s
                    AND config_key = %s
                    AND effective_date <= CURRENT_DATE
                    AND (expiry_date IS NULL OR expiry_date >= CURRENT_DATE)
                ORDER BY effective_date DESC, update_dtime DESC, config_id DESC
                LIMIT 1
                """,
                [target_tenant_id, _CROSS_TENANT_POLICY_KEY],
            )
            row = cursor.fetchone()
    except DatabaseError:
        return False
    if not row:
        return False
    config = _parse_json_object(row[0])
    if not config:
        return False
    return bool(config.get("allow_neoc_actions", False))


def can_access_tenant(
    context: TenantContext,
    target_tenant_id: int | None,
    *,
    write: bool = False,
) -> bool:
    if target_tenant_id is None:
        return False

    if target_tenant_id in context.membership_tenant_ids:
        return True

    if not context.is_neoc:
        return False

    if write:
        if not context.can_act_cross_tenant:
            return False
        return _target_tenant_allows_neoc_actions(target_tenant_id)

    return context.can_read_all_tenants


def can_manage_phase_window_config(context: TenantContext) -> bool:
    """
    Event phase demand/planning windows are centrally managed and must only be
    configurable by ODPEM national and ODPEM-NEOC tenants.
    """
    active_type = _normalize_tenant_type(context.active_tenant_type)
    if active_type not in {"NATIONAL", "NEOC", "NATIONAL_LEVEL"}:
        return False

    configured_codes = getattr(settings, "NATIONAL_PHASE_WINDOW_ADMIN_CODES", [])
    allowed_codes = {
        _normalize_tenant_code(value)
        for value in configured_codes
        if str(value or "").strip()
    }
    if not allowed_codes:
        allowed_codes = {"OFFICE_OF_DISASTER_P", "ODPEM_NEOC"}

    active_code = _normalize_tenant_code(context.active_tenant_code)
    return active_code in allowed_codes


def can_access_warehouse(
    context: TenantContext,
    warehouse_id: int | None,
    *,
    write: bool = False,
) -> bool:
    target_tenant_id = resolve_warehouse_tenant_id(warehouse_id)
    return can_access_tenant(context, target_tenant_id, write=write)


def can_access_record(
    context: TenantContext,
    record: dict[str, Any],
    *,
    write: bool = False,
) -> bool:
    warehouse_id = _parse_int(record.get("warehouse_id"))
    if warehouse_id is not None:
        return can_access_warehouse(context, warehouse_id, write=write)

    warehouse_ids = record.get("warehouse_ids")
    if isinstance(warehouse_ids, (list, tuple, set)):
        for value in warehouse_ids:
            candidate_id = _parse_int(value)
            if candidate_id is None:
                continue
            if can_access_warehouse(context, candidate_id, write=write):
                return True
    return False
    return False
