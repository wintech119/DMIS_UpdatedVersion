from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Iterable

from django.conf import settings
from django.db import DatabaseError, connection, models, transaction
from django.utils import timezone

from api.rbac import (
    PERM_OPERATIONS_REQUEST_CREATE_FOR_SUBORDINATE,
    PERM_OPERATIONS_REQUEST_CREATE_ON_BEHALF_BRIDGE,
    PERM_OPERATIONS_REQUEST_CREATE_SELF,
)
from api.tenancy import TenantContext, TenantMembership
from operations.constants import (
    ORIGIN_MODE_FOR_SUBORDINATE,
    ORIGIN_MODE_ODPEM_BRIDGE,
    ORIGIN_MODE_SELF,
)
from operations.exceptions import OperationValidationError
from operations.models import TenantControlScope, TenantHierarchy, TenantRequestPolicy

_ODPEM_TENANT_CODES = {"OFFICE_OF_DISASTER_P"}
_RELIEF_REQUEST_ON_BEHALF_POLICY_KEY = "approval.cross_tenant_actions"
_READ_ONLY_ACCESS_LEVELS = {"READ_ONLY", "READONLY", "VIEW", "VIEW_ONLY"}
_REQUEST_CREATE_PERMISSION_BY_ORIGIN_MODE = {
    ORIGIN_MODE_SELF: PERM_OPERATIONS_REQUEST_CREATE_SELF,
    ORIGIN_MODE_FOR_SUBORDINATE: PERM_OPERATIONS_REQUEST_CREATE_FOR_SUBORDINATE,
    ORIGIN_MODE_ODPEM_BRIDGE: PERM_OPERATIONS_REQUEST_CREATE_ON_BEHALF_BRIDGE,
}


@dataclass(frozen=True)
class AgencyScope:
    agency_id: int
    agency_name: str | None
    agency_type: str | None
    warehouse_id: int | None
    tenant_id: int | None
    tenant_code: str | None
    tenant_name: str | None
    tenant_type: str | None

    @property
    def is_odpem_tenant(self) -> bool:
        return _is_odpem_tenant(self.tenant_id, self.tenant_code)


@dataclass(frozen=True)
class ReliefRequestWriteDecision:
    agency_scope: AgencyScope
    origin_mode: str
    requesting_tenant_id: int
    beneficiary_tenant_id: int
    requesting_agency_id: int | None = None
    beneficiary_agency_id: int | None = None

    @property
    def submission_mode(self) -> str:
        if self.origin_mode == ORIGIN_MODE_FOR_SUBORDINATE:
            return "for_subordinate"
        if self.origin_mode == ORIGIN_MODE_ODPEM_BRIDGE:
            return "on_behalf_bridge"
        return "self"


def _normalize_token(value: object) -> str:
    text = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
    while "__" in text:
        text = text.replace("__", "_")
    return text


def _is_odpem_tenant_code(value: object) -> bool:
    code = _normalize_token(value)
    return bool(code) and (code in _ODPEM_TENANT_CODES or code.startswith("ODPEM"))


@lru_cache(maxsize=1)
def resolve_odpem_tenant_id() -> int | None:
    configured = getattr(settings, "ODPEM_TENANT_ID", None)
    if configured:
        try:
            return int(configured)
        except (TypeError, ValueError):
            return None
    row = _safe_fetchone(
        """
        SELECT tenant_id
        FROM tenant
        WHERE tenant_code IS NOT NULL
          AND (
            UPPER(REPLACE(REPLACE(tenant_code, '-', '_'), ' ', '_')) = 'OFFICE_OF_DISASTER_P'
            OR UPPER(tenant_code) LIKE 'ODPEM%%'
          )
        ORDER BY tenant_id
        LIMIT 1
        """
    )

    if not row or row[0] in (None, ""):
        return None
    return int(row[0])


def resolve_odpem_fulfillment_tenant_id() -> int | None:
    """Return the operational tenant that owns ODPEM-managed fulfillment work."""
    return resolve_odpem_tenant_id()


def _is_odpem_tenant(tenant_id: object, tenant_code: object) -> bool:
    parsed_tenant_id = _parse_int(tenant_id)
    resolved_tenant_id = resolve_odpem_tenant_id()
    if parsed_tenant_id is not None and resolved_tenant_id is not None:
        return parsed_tenant_id == resolved_tenant_id
    return _is_odpem_tenant_code(tenant_code)


def _permission_set(permissions: Iterable[str]) -> set[str]:
    return {str(permission or "").strip().lower() for permission in permissions if str(permission or "").strip()}


def _active_membership(context: TenantContext) -> TenantMembership | None:
    return next(
        (membership for membership in context.memberships if membership.tenant_id == context.active_tenant_id),
        None,
    )


def _membership_can_write(access_level: object) -> bool:
    normalized = _normalize_token(access_level)
    if not normalized:
        return True
    return normalized not in _READ_ONLY_ACCESS_LEVELS


def _parse_int(value: object) -> int | None:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


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


def _parse_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    normalized = str(value or "").strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off", ""}:
        return False
    return False


def _safe_fetchone(sql: str, params: Iterable[object] | None = None) -> tuple[Any, ...] | None:
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(sql, list(params or []))
                return cursor.fetchone()
    except DatabaseError:
        return None


def _active_policy(tenant_id: int | None) -> TenantRequestPolicy | None:
    if tenant_id is None:
        return None
    today = timezone.localdate()
    try:
        return (
            TenantRequestPolicy.objects.filter(
                tenant_id=int(tenant_id),
                status_code="ACTIVE",
                effective_date__lte=today,
            )
            .filter(models.Q(expiry_date__isnull=True) | models.Q(expiry_date__gte=today))
            .order_by("-effective_date", "-policy_id")
            .first()
        )
    except Exception:
        return None


def _tenant_controls_target(controller_tenant_id: int | None, target_tenant_id: int | None) -> bool:
    if controller_tenant_id is None or target_tenant_id is None or controller_tenant_id == target_tenant_id:
        return False
    today = timezone.localdate()
    try:
        direct_scope_exists = TenantControlScope.objects.filter(
            controller_tenant_id=int(controller_tenant_id),
            controlled_tenant_id=int(target_tenant_id),
            status_code="ACTIVE",
            effective_date__lte=today,
        ).filter(models.Q(expiry_date__isnull=True) | models.Q(expiry_date__gte=today)).exists()
        if direct_scope_exists:
            return True
        return TenantHierarchy.objects.filter(
            parent_tenant_id=int(controller_tenant_id),
            child_tenant_id=int(target_tenant_id),
            status_code="ACTIVE",
            can_parent_request_on_behalf_flag=True,
            effective_date__lte=today,
        ).filter(models.Q(expiry_date__isnull=True) | models.Q(expiry_date__gte=today)).exists()
    except Exception:
        return False


def _tenant_allows_relief_request_on_behalf(
    target_tenant_id: int | None,
    *,
    target_policy: TenantRequestPolicy | None = None,
) -> bool:
    if target_tenant_id is None:
        return False

    if target_policy is not None:
        return bool(target_policy.allow_odpem_bridge_flag)

    row = _safe_fetchone(
        """
        SELECT allow_neoc_actions, allow_cross_tenant_write
        FROM tenant_access_policy
        WHERE
            tenant_id = %s
            AND COALESCE(status_code, 'A') = 'A'
            AND effective_date <= CURRENT_DATE
            AND (expiry_date IS NULL OR expiry_date >= CURRENT_DATE)
        ORDER BY effective_date DESC, update_dtime DESC, policy_id DESC
        LIMIT 1
        """,
        [int(target_tenant_id)],
    )

    if row:
        return bool(row[0]) or bool(row[1])

    row = _safe_fetchone(
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
        [int(target_tenant_id), _RELIEF_REQUEST_ON_BEHALF_POLICY_KEY],
    )

    if not row:
        return False

    config = _parse_json_object(row[0])
    if not config:
        return False

    for key in ("allow_odpem_on_behalf_requests", "allow_cross_tenant_write", "allow_neoc_actions"):
        if key in config:
            return _parse_bool(config.get(key))
    return False


def _agency_scope_error(
    *,
    code: str,
    message: str,
    tenant_context: TenantContext,
    agency_id: int | None = None,
    agency_scope: AgencyScope | None = None,
) -> OperationValidationError:
    details: dict[str, Any] = {
        "code": code,
        "message": message,
        "active_tenant_id": tenant_context.active_tenant_id,
        "active_tenant_code": tenant_context.active_tenant_code,
        "active_tenant_type": tenant_context.active_tenant_type,
    }
    if agency_id is not None:
        details["agency_id"] = int(agency_id)
    if agency_scope is not None:
        details["agency_name"] = agency_scope.agency_name
        details["agency_tenant_id"] = agency_scope.tenant_id
        details["agency_tenant_code"] = agency_scope.tenant_code
        details["agency_tenant_type"] = agency_scope.tenant_type
    return OperationValidationError({"agency_id": details})


def get_agency_scope(agency_id: int) -> AgencyScope | None:
    row = _safe_fetchone(
        """
        SELECT
            a.agency_id,
            a.agency_name,
            a.agency_type,
            a.warehouse_id,
            t.tenant_id,
            t.tenant_code,
            t.tenant_name,
            t.tenant_type
        FROM agency a
        LEFT JOIN warehouse w ON w.warehouse_id = a.warehouse_id
        LEFT JOIN tenant t ON t.tenant_id = w.tenant_id
        WHERE
            a.agency_id = %s
            AND COALESCE(a.status_code, 'A') = 'A'
        LIMIT 1
        """,
        [int(agency_id)],
    )

    if not row:
        return None

    return AgencyScope(
        agency_id=int(row[0]),
        agency_name=str(row[1]).strip() if row[1] else None,
        agency_type=str(row[2]).strip() if row[2] else None,
        warehouse_id=_parse_int(row[3]),
        tenant_id=_parse_int(row[4]),
        tenant_code=str(row[5]).strip() if row[5] else None,
        tenant_name=str(row[6]).strip() if row[6] else None,
        tenant_type=str(row[7]).strip() if row[7] else None,
    )


def is_odpem_tenant_context(context: TenantContext) -> bool:
    return _is_odpem_tenant(context.active_tenant_id, context.active_tenant_code)


def get_relief_request_capabilities(
    *,
    tenant_context: TenantContext,
    permissions: Iterable[str],
) -> dict[str, Any]:
    permission_set = _permission_set(permissions)
    active_membership = _active_membership(tenant_context)
    active_policy = _active_policy(tenant_context.active_tenant_id)
    active_is_odpem = is_odpem_tenant_context(tenant_context)

    has_self_permission = PERM_OPERATIONS_REQUEST_CREATE_SELF.lower() in permission_set
    has_subordinate_permission = PERM_OPERATIONS_REQUEST_CREATE_FOR_SUBORDINATE.lower() in permission_set
    has_bridge_permission = PERM_OPERATIONS_REQUEST_CREATE_ON_BEHALF_BRIDGE.lower() in permission_set
    active_membership_can_write = active_membership is not None and _membership_can_write(active_membership.access_level)
    can_self_request = bool(
        has_self_permission
        and active_membership_can_write
        and not active_is_odpem
        and (active_policy.can_self_request_flag if active_policy is not None else True)
        and not (
            active_policy is not None
            and active_policy.request_authority_tenant_id
            and active_policy.request_authority_tenant_id != tenant_context.active_tenant_id
        )
    )
    can_subordinate_request = bool(
        has_subordinate_permission
        and active_membership_can_write
        and not active_is_odpem
        and not (
            active_policy is not None
            and active_policy.request_authority_tenant_id
            and active_policy.request_authority_tenant_id != tenant_context.active_tenant_id
        )
    )
    can_bridge_request = bool(has_bridge_permission and active_membership_can_write and active_is_odpem and tenant_context.can_act_cross_tenant)

    submission_mode: str | None = None
    if can_self_request:
        submission_mode = "self"
    elif can_subordinate_request:
        submission_mode = "for_subordinate"
    elif can_bridge_request:
        submission_mode = "on_behalf_bridge"

    return {
        "can_create_relief_request": can_self_request or can_subordinate_request or can_bridge_request,
        "can_create_relief_request_on_behalf": can_bridge_request or can_subordinate_request,
        "relief_request_submission_mode": submission_mode,
        "default_requesting_tenant_id": tenant_context.active_tenant_id if tenant_context.active_tenant_id else None,
        "allowed_origin_modes": [
            mode
            for mode, allowed in (
                ("self", can_self_request),
                ("for_subordinate", can_subordinate_request),
                ("on_behalf_bridge", can_bridge_request),
            )
            if allowed
        ],
    }


def required_permission_for_origin_mode(origin_mode: str) -> str | None:
    return _REQUEST_CREATE_PERMISSION_BY_ORIGIN_MODE.get(str(origin_mode or "").strip())


def enforce_relief_request_origin_mode_permission(
    *,
    decision: ReliefRequestWriteDecision,
    permissions: Iterable[str],
) -> None:
    required_permission = required_permission_for_origin_mode(decision.origin_mode)
    if required_permission is None:
        raise OperationValidationError({"origin_mode": "Unsupported relief request origin mode."})

    permission_set = _permission_set(permissions)
    if required_permission.lower() in permission_set:
        return

    raise OperationValidationError(
        {
            "origin_mode": {
                "code": "origin_mode_permission_denied",
                "message": f"Creating a {decision.submission_mode} relief request requires {required_permission}.",
                "origin_mode": decision.origin_mode,
                "required_permission": required_permission,
            }
        }
    )


def validate_relief_request_agency_selection(
    *,
    agency_id: int,
    tenant_context: TenantContext,
) -> ReliefRequestWriteDecision:
    active_membership = _active_membership(tenant_context)
    if tenant_context.active_tenant_id is None or active_membership is None:
        raise _agency_scope_error(
            code="active_tenant_required",
            message="An active tenant context is required for relief-request creation.",
            tenant_context=tenant_context,
            agency_id=agency_id,
        )

    if not _membership_can_write(active_membership.access_level):
        raise _agency_scope_error(
            code="active_tenant_read_only",
            message="The active tenant membership is read-only for relief-request writes.",
            tenant_context=tenant_context,
            agency_id=agency_id,
        )

    agency_scope = get_agency_scope(int(agency_id))
    if agency_scope is None:
        raise _agency_scope_error(
            code="agency_not_found",
            message="Selected agency does not exist or is inactive.",
            tenant_context=tenant_context,
            agency_id=agency_id,
        )

    if agency_scope.tenant_id is None:
        raise _agency_scope_error(
            code="agency_tenant_unresolved",
            message="Selected agency is not mapped to a tenant-owned warehouse and cannot be used for relief requests.",
            tenant_context=tenant_context,
            agency_id=agency_id,
            agency_scope=agency_scope,
        )

    active_policy = _active_policy(tenant_context.active_tenant_id)
    target_policy = _active_policy(agency_scope.tenant_id)

    if is_odpem_tenant_context(tenant_context):
        if not tenant_context.can_act_cross_tenant:
            raise _agency_scope_error(
                code="on_behalf_not_allowed",
                message="The active ODPEM tenant is not authorized to create relief requests on behalf of other agencies.",
                tenant_context=tenant_context,
                agency_id=agency_id,
                agency_scope=agency_scope,
            )
        if agency_scope.is_odpem_tenant:
            raise _agency_scope_error(
                code="odpem_on_behalf_external_only",
                message="ODPEM bridge request creation only supports non-ODPEM beneficiary agencies.",
                tenant_context=tenant_context,
                agency_id=agency_id,
                agency_scope=agency_scope,
            )
        if not _tenant_allows_relief_request_on_behalf(agency_scope.tenant_id, target_policy=target_policy):
            raise _agency_scope_error(
                code="on_behalf_policy_denied",
                message="The beneficiary tenant has not allowed ODPEM bridge request creation.",
                tenant_context=tenant_context,
                agency_id=agency_id,
                agency_scope=agency_scope,
            )
        return ReliefRequestWriteDecision(
            agency_scope=agency_scope,
            origin_mode=ORIGIN_MODE_ODPEM_BRIDGE,
            requesting_tenant_id=int(tenant_context.active_tenant_id),
            beneficiary_tenant_id=int(agency_scope.tenant_id),
            beneficiary_agency_id=int(agency_scope.agency_id),
        )

    target_authority_tenant_id = _parse_int(
        target_policy.request_authority_tenant_id if target_policy is not None else None
    )
    if agency_scope.tenant_id == tenant_context.active_tenant_id:
        if target_authority_tenant_id and target_authority_tenant_id != tenant_context.active_tenant_id:
            raise _agency_scope_error(
                code="request_authority_escalation_required",
                message="This tenant must escalate relief requests through its request-authority parent tenant.",
                tenant_context=tenant_context,
                agency_id=agency_id,
                agency_scope=agency_scope,
            )
        if active_policy is not None and not active_policy.can_self_request_flag:
            raise _agency_scope_error(
                code="self_request_disabled",
                message="Self-service relief request creation is disabled for the active tenant policy.",
                tenant_context=tenant_context,
                agency_id=agency_id,
                agency_scope=agency_scope,
            )
        return ReliefRequestWriteDecision(
            agency_scope=agency_scope,
            origin_mode=ORIGIN_MODE_SELF,
            requesting_tenant_id=int(tenant_context.active_tenant_id),
            beneficiary_tenant_id=int(agency_scope.tenant_id),
            requesting_agency_id=int(agency_scope.agency_id),
            beneficiary_agency_id=int(agency_scope.agency_id),
        )

    if _tenant_controls_target(tenant_context.active_tenant_id, agency_scope.tenant_id):
        if target_authority_tenant_id and target_authority_tenant_id != tenant_context.active_tenant_id:
            raise _agency_scope_error(
                code="beneficiary_authority_mismatch",
                message="The selected beneficiary agency is governed by a different request-authority tenant.",
                tenant_context=tenant_context,
                agency_id=agency_id,
                agency_scope=agency_scope,
            )
        return ReliefRequestWriteDecision(
            agency_scope=agency_scope,
            origin_mode=ORIGIN_MODE_FOR_SUBORDINATE,
            requesting_tenant_id=int(tenant_context.active_tenant_id),
            beneficiary_tenant_id=int(agency_scope.tenant_id),
            beneficiary_agency_id=int(agency_scope.agency_id),
        )

    raise _agency_scope_error(
        code="agency_out_of_scope",
        message="Selected agency is outside the active tenant request-authority scope.",
        tenant_context=tenant_context,
        agency_id=agency_id,
        agency_scope=agency_scope,
    )
