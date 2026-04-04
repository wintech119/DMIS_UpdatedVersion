from __future__ import annotations

from typing import Iterable, Tuple

from django.conf import settings
from django.db import DatabaseError, connection
import logging

from api.authentication import Principal

logger = logging.getLogger(__name__)

REQUIRED_PERMISSION = "replenishment.needs_list.preview"
PERM_NEEDS_LIST_CREATE_DRAFT = "replenishment.needs_list.create_draft"
PERM_NEEDS_LIST_EDIT_LINES = "replenishment.needs_list.edit_lines"
PERM_NEEDS_LIST_SUBMIT = "replenishment.needs_list.submit"
PERM_NEEDS_LIST_RETURN = "replenishment.needs_list.return"
PERM_NEEDS_LIST_REJECT = "replenishment.needs_list.reject"
PERM_NEEDS_LIST_APPROVE = "replenishment.needs_list.approve"
PERM_NEEDS_LIST_ESCALATE = "replenishment.needs_list.escalate"
PERM_NEEDS_LIST_EXECUTE = "replenishment.needs_list.execute"
PERM_NEEDS_LIST_CANCEL = "replenishment.needs_list.cancel"
PERM_NEEDS_LIST_REVIEW_COMMENTS = "replenishment.needs_list.review_comments"

# Operations permissions
PERM_OPERATIONS_REQUEST_CREATE_SELF = "operations.request.create.self"
PERM_OPERATIONS_REQUEST_CREATE_FOR_SUBORDINATE = "operations.request.create.for_subordinate"
PERM_OPERATIONS_REQUEST_CREATE_ON_BEHALF_BRIDGE = "operations.request.create.on_behalf_bridge"
PERM_OPERATIONS_REQUEST_EDIT_DRAFT = "operations.request.edit.draft"
PERM_OPERATIONS_REQUEST_SUBMIT = "operations.request.submit"
PERM_OPERATIONS_ELIGIBILITY_REVIEW = "operations.eligibility.review"
PERM_OPERATIONS_ELIGIBILITY_APPROVE = "operations.eligibility.approve"
PERM_OPERATIONS_ELIGIBILITY_REJECT = "operations.eligibility.reject"
PERM_OPERATIONS_PACKAGE_CREATE = "operations.package.create"
PERM_OPERATIONS_PACKAGE_LOCK = "operations.package.lock"
PERM_OPERATIONS_PACKAGE_ALLOCATE = "operations.package.allocate"
PERM_OPERATIONS_PACKAGE_OVERRIDE_REQUEST = "operations.package.override.request"
PERM_OPERATIONS_PACKAGE_OVERRIDE_APPROVE = "operations.package.override.approve"
PERM_OPERATIONS_DISPATCH_PREPARE = "operations.dispatch.prepare"
PERM_OPERATIONS_DISPATCH_EXECUTE = "operations.dispatch.execute"
PERM_OPERATIONS_RECEIPT_CONFIRM = "operations.receipt.confirm"
PERM_OPERATIONS_CONSOLIDATION_DISPATCH = "operations.consolidation.dispatch"
PERM_OPERATIONS_CONSOLIDATION_RECEIVE = "operations.consolidation.receive"
PERM_OPERATIONS_PICKUP_RELEASE = "operations.pickup.release"
PERM_OPERATIONS_STAGING_WAREHOUSE_OVERRIDE = "operations.staging_warehouse.override"
PERM_OPERATIONS_FULFILLMENT_MODE_SET = "operations.fulfillment_mode.set"
PERM_OPERATIONS_PARTIAL_RELEASE_REQUEST = "operations.partial_release.request"
PERM_OPERATIONS_PARTIAL_RELEASE_APPROVE = "operations.partial_release.approve"
PERM_OPERATIONS_WAYBILL_VIEW = "operations.waybill.view"
PERM_OPERATIONS_NOTIFICATION_RECEIVE = "operations.notification.receive"
PERM_OPERATIONS_QUEUE_VIEW = "operations.queue.view"

# Tenant administration permissions
PERM_TENANT_APPROVAL_POLICY_VIEW = "tenant.approval_policy.view"
PERM_TENANT_APPROVAL_POLICY_MANAGE = "tenant.approval_policy.manage"
PERM_TENANT_FEATURE_VIEW = "tenant.feature.view"
PERM_TENANT_FEATURE_MANAGE = "tenant.feature.manage"
PERM_EVENT_PHASE_WINDOW_VIEW = "replenishment.phase_window.view"
PERM_EVENT_PHASE_WINDOW_MANAGE = "replenishment.phase_window.manage"

# National (NEOC) cross-tenant scope permissions
PERM_NATIONAL_READ_ALL_TENANTS = "national.read_all_tenants"
PERM_NATIONAL_ACT_CROSS_TENANT = "national.act_cross_tenant"

# Procurement permissions
PERM_PROCUREMENT_CREATE = "replenishment.procurement.create"
PERM_PROCUREMENT_VIEW = "replenishment.procurement.view"
PERM_PROCUREMENT_EDIT = "replenishment.procurement.edit"
PERM_PROCUREMENT_SUBMIT = "replenishment.procurement.submit"
PERM_PROCUREMENT_APPROVE = "replenishment.procurement.approve"
PERM_PROCUREMENT_REJECT = "replenishment.procurement.reject"
PERM_PROCUREMENT_ORDER = "replenishment.procurement.order"
PERM_PROCUREMENT_RECEIVE = "replenishment.procurement.receive"
PERM_PROCUREMENT_CANCEL = "replenishment.procurement.cancel"
PERM_CRITICALITY_OVERRIDE_VIEW = "replenishment.criticality_override.view"
PERM_CRITICALITY_OVERRIDE_MANAGE = "replenishment.criticality_override.manage"
PERM_CRITICALITY_HAZARD_VIEW = "replenishment.criticality_hazard.view"
PERM_CRITICALITY_HAZARD_MANAGE = "replenishment.criticality_hazard.manage"
PERM_CRITICALITY_HAZARD_APPROVE = "replenishment.criticality_hazard.approve"

# Master data permissions
PERM_MASTERDATA_VIEW = "masterdata.view"
PERM_MASTERDATA_CREATE = "masterdata.create"
PERM_MASTERDATA_EDIT = "masterdata.edit"
PERM_MASTERDATA_INACTIVATE = "masterdata.inactivate"

_DEV_ROLE_PERMISSION_MAP = {
    "LOGISTICS": {
        REQUIRED_PERMISSION,
        PERM_NEEDS_LIST_CREATE_DRAFT,
        PERM_NEEDS_LIST_EDIT_LINES,
        PERM_NEEDS_LIST_SUBMIT,
        PERM_NEEDS_LIST_APPROVE,
        PERM_NEEDS_LIST_EXECUTE,
        PERM_NEEDS_LIST_CANCEL,
        PERM_PROCUREMENT_CREATE,
        PERM_PROCUREMENT_VIEW,
        PERM_PROCUREMENT_EDIT,
        PERM_PROCUREMENT_SUBMIT,
        PERM_PROCUREMENT_ORDER,
        PERM_PROCUREMENT_RECEIVE,
        PERM_PROCUREMENT_CANCEL,
        PERM_CRITICALITY_OVERRIDE_VIEW,
        PERM_CRITICALITY_OVERRIDE_MANAGE,
        PERM_CRITICALITY_HAZARD_VIEW,
        PERM_CRITICALITY_HAZARD_MANAGE,
        PERM_TENANT_FEATURE_VIEW,
        PERM_EVENT_PHASE_WINDOW_VIEW,
        PERM_MASTERDATA_VIEW,
        PERM_OPERATIONS_FULFILLMENT_MODE_SET,
        PERM_OPERATIONS_STAGING_WAREHOUSE_OVERRIDE,
        PERM_OPERATIONS_CONSOLIDATION_DISPATCH,
        PERM_OPERATIONS_CONSOLIDATION_RECEIVE,
        PERM_OPERATIONS_PICKUP_RELEASE,
        PERM_OPERATIONS_PARTIAL_RELEASE_REQUEST,
    },
    "EXECUTIVE": {
        REQUIRED_PERMISSION,
        PERM_NEEDS_LIST_RETURN,
        PERM_NEEDS_LIST_REJECT,
        PERM_NEEDS_LIST_APPROVE,
        PERM_NEEDS_LIST_ESCALATE,
        PERM_NEEDS_LIST_REVIEW_COMMENTS,
        PERM_PROCUREMENT_VIEW,
        PERM_PROCUREMENT_APPROVE,
        PERM_PROCUREMENT_REJECT,
        PERM_CRITICALITY_OVERRIDE_VIEW,
        PERM_CRITICALITY_HAZARD_VIEW,
        PERM_TENANT_FEATURE_VIEW,
        PERM_TENANT_APPROVAL_POLICY_VIEW,
        PERM_NATIONAL_READ_ALL_TENANTS,
        PERM_EVENT_PHASE_WINDOW_VIEW,
        PERM_EVENT_PHASE_WINDOW_MANAGE,
        PERM_MASTERDATA_VIEW,
    },
    "SYSTEM_ADMINISTRATOR": {
        REQUIRED_PERMISSION,
        PERM_NEEDS_LIST_CREATE_DRAFT,
        PERM_NEEDS_LIST_EDIT_LINES,
        PERM_NEEDS_LIST_SUBMIT,
        PERM_NEEDS_LIST_RETURN,
        PERM_NEEDS_LIST_REJECT,
        PERM_NEEDS_LIST_APPROVE,
        PERM_NEEDS_LIST_ESCALATE,
        PERM_NEEDS_LIST_EXECUTE,
        PERM_NEEDS_LIST_CANCEL,
        PERM_NEEDS_LIST_REVIEW_COMMENTS,
        PERM_PROCUREMENT_CREATE,
        PERM_PROCUREMENT_VIEW,
        PERM_PROCUREMENT_EDIT,
        PERM_PROCUREMENT_SUBMIT,
        PERM_PROCUREMENT_APPROVE,
        PERM_PROCUREMENT_REJECT,
        PERM_PROCUREMENT_ORDER,
        PERM_PROCUREMENT_RECEIVE,
        PERM_PROCUREMENT_CANCEL,
        PERM_CRITICALITY_OVERRIDE_VIEW,
        PERM_CRITICALITY_OVERRIDE_MANAGE,
        PERM_CRITICALITY_HAZARD_VIEW,
        PERM_CRITICALITY_HAZARD_MANAGE,
        PERM_TENANT_APPROVAL_POLICY_VIEW,
        PERM_TENANT_APPROVAL_POLICY_MANAGE,
        PERM_TENANT_FEATURE_VIEW,
        PERM_TENANT_FEATURE_MANAGE,
        PERM_NATIONAL_READ_ALL_TENANTS,
        PERM_NATIONAL_ACT_CROSS_TENANT,
        PERM_EVENT_PHASE_WINDOW_VIEW,
        PERM_EVENT_PHASE_WINDOW_MANAGE,
        PERM_MASTERDATA_VIEW,
        PERM_MASTERDATA_CREATE,
        PERM_MASTERDATA_EDIT,
        PERM_MASTERDATA_INACTIVATE,
        PERM_OPERATIONS_CONSOLIDATION_DISPATCH,
        PERM_OPERATIONS_CONSOLIDATION_RECEIVE,
        PERM_OPERATIONS_PICKUP_RELEASE,
        PERM_OPERATIONS_STAGING_WAREHOUSE_OVERRIDE,
        PERM_OPERATIONS_FULFILLMENT_MODE_SET,
        PERM_OPERATIONS_PARTIAL_RELEASE_REQUEST,
        PERM_OPERATIONS_PARTIAL_RELEASE_APPROVE,
    },
}

# Compatibility overrides for known DB role-permission gaps.
# These are merged in addition to DB-resolved permissions.
_ROLE_PERMISSION_COMPAT_OVERRIDES = {
    "AGENCY_DISTRIBUTOR": {
        PERM_OPERATIONS_REQUEST_CREATE_SELF,
        PERM_OPERATIONS_REQUEST_CREATE_FOR_SUBORDINATE,
        PERM_OPERATIONS_REQUEST_EDIT_DRAFT,
        PERM_OPERATIONS_REQUEST_SUBMIT,
        PERM_OPERATIONS_WAYBILL_VIEW,
        PERM_OPERATIONS_RECEIPT_CONFIRM,
        PERM_OPERATIONS_NOTIFICATION_RECEIVE,
        PERM_OPERATIONS_QUEUE_VIEW,
    },
    "AGENCY_SHELTER": {
        PERM_OPERATIONS_REQUEST_CREATE_SELF,
        PERM_OPERATIONS_REQUEST_CREATE_FOR_SUBORDINATE,
        PERM_OPERATIONS_REQUEST_EDIT_DRAFT,
        PERM_OPERATIONS_REQUEST_SUBMIT,
        PERM_OPERATIONS_WAYBILL_VIEW,
        PERM_OPERATIONS_RECEIPT_CONFIRM,
        PERM_OPERATIONS_NOTIFICATION_RECEIVE,
        PERM_OPERATIONS_QUEUE_VIEW,
    },
    "CUSTODIAN": {
        PERM_OPERATIONS_REQUEST_CREATE_SELF,
        PERM_OPERATIONS_REQUEST_CREATE_FOR_SUBORDINATE,
        PERM_OPERATIONS_REQUEST_EDIT_DRAFT,
        PERM_OPERATIONS_REQUEST_SUBMIT,
        PERM_OPERATIONS_WAYBILL_VIEW,
        PERM_OPERATIONS_RECEIPT_CONFIRM,
        PERM_OPERATIONS_NOTIFICATION_RECEIVE,
        PERM_OPERATIONS_QUEUE_VIEW,
    },
    "LOGISTICS_OFFICER": {
        PERM_NEEDS_LIST_SUBMIT,
        PERM_MASTERDATA_VIEW,
        PERM_OPERATIONS_PACKAGE_CREATE,
        PERM_OPERATIONS_PACKAGE_LOCK,
        PERM_OPERATIONS_PACKAGE_ALLOCATE,
        PERM_OPERATIONS_PACKAGE_OVERRIDE_REQUEST,
        PERM_OPERATIONS_FULFILLMENT_MODE_SET,
        PERM_OPERATIONS_STAGING_WAREHOUSE_OVERRIDE,
        PERM_OPERATIONS_PARTIAL_RELEASE_REQUEST,
        PERM_OPERATIONS_DISPATCH_PREPARE,
        PERM_OPERATIONS_DISPATCH_EXECUTE,
        PERM_OPERATIONS_CONSOLIDATION_DISPATCH,
        PERM_OPERATIONS_CONSOLIDATION_RECEIVE,
        PERM_OPERATIONS_PICKUP_RELEASE,
        PERM_OPERATIONS_WAYBILL_VIEW,
        PERM_OPERATIONS_NOTIFICATION_RECEIVE,
        PERM_OPERATIONS_QUEUE_VIEW,
    },
    "TST_LOGISTICS_OFFICER": {
        PERM_NEEDS_LIST_SUBMIT,
        PERM_MASTERDATA_VIEW,
        PERM_OPERATIONS_PACKAGE_CREATE,
        PERM_OPERATIONS_PACKAGE_LOCK,
        PERM_OPERATIONS_PACKAGE_ALLOCATE,
        PERM_OPERATIONS_PACKAGE_OVERRIDE_REQUEST,
        PERM_OPERATIONS_FULFILLMENT_MODE_SET,
        PERM_OPERATIONS_STAGING_WAREHOUSE_OVERRIDE,
        PERM_OPERATIONS_PARTIAL_RELEASE_REQUEST,
        PERM_OPERATIONS_DISPATCH_PREPARE,
        PERM_OPERATIONS_DISPATCH_EXECUTE,
        PERM_OPERATIONS_CONSOLIDATION_DISPATCH,
        PERM_OPERATIONS_CONSOLIDATION_RECEIVE,
        PERM_OPERATIONS_PICKUP_RELEASE,
        PERM_OPERATIONS_WAYBILL_VIEW,
        PERM_OPERATIONS_NOTIFICATION_RECEIVE,
        PERM_OPERATIONS_QUEUE_VIEW,
    },
    "INVENTORY_CLERK": {
        PERM_OPERATIONS_DISPATCH_PREPARE,
        PERM_OPERATIONS_DISPATCH_EXECUTE,
        PERM_OPERATIONS_CONSOLIDATION_DISPATCH,
        PERM_OPERATIONS_WAYBILL_VIEW,
        PERM_OPERATIONS_NOTIFICATION_RECEIVE,
        PERM_OPERATIONS_QUEUE_VIEW,
    },
    # Approval workflow expects Logistics Manager roles to be able to review
    # and decide pending needs lists for lower approval tiers.
    "LOGISTICS_MANAGER": {
        PERM_NEEDS_LIST_RETURN,
        PERM_NEEDS_LIST_REJECT,
        PERM_NEEDS_LIST_APPROVE,
        PERM_NEEDS_LIST_ESCALATE,
        PERM_NEEDS_LIST_REVIEW_COMMENTS,
        PERM_CRITICALITY_OVERRIDE_VIEW,
        PERM_CRITICALITY_OVERRIDE_MANAGE,
        PERM_CRITICALITY_HAZARD_VIEW,
        PERM_MASTERDATA_VIEW,
        PERM_OPERATIONS_PACKAGE_CREATE,
        PERM_OPERATIONS_PACKAGE_LOCK,
        PERM_OPERATIONS_PACKAGE_ALLOCATE,
        PERM_OPERATIONS_PACKAGE_OVERRIDE_REQUEST,
        PERM_OPERATIONS_PACKAGE_OVERRIDE_APPROVE,
        PERM_OPERATIONS_FULFILLMENT_MODE_SET,
        PERM_OPERATIONS_STAGING_WAREHOUSE_OVERRIDE,
        PERM_OPERATIONS_PARTIAL_RELEASE_REQUEST,
        PERM_OPERATIONS_PARTIAL_RELEASE_APPROVE,
        PERM_OPERATIONS_DISPATCH_PREPARE,
        PERM_OPERATIONS_DISPATCH_EXECUTE,
        PERM_OPERATIONS_CONSOLIDATION_DISPATCH,
        PERM_OPERATIONS_CONSOLIDATION_RECEIVE,
        PERM_OPERATIONS_PICKUP_RELEASE,
        PERM_OPERATIONS_WAYBILL_VIEW,
        PERM_OPERATIONS_NOTIFICATION_RECEIVE,
        PERM_OPERATIONS_QUEUE_VIEW,
    },
    "ODPEM_LOGISTICS_MANAGER": {
        PERM_NEEDS_LIST_RETURN,
        PERM_NEEDS_LIST_REJECT,
        PERM_NEEDS_LIST_APPROVE,
        PERM_NEEDS_LIST_ESCALATE,
        PERM_NEEDS_LIST_REVIEW_COMMENTS,
        PERM_CRITICALITY_OVERRIDE_VIEW,
        PERM_CRITICALITY_OVERRIDE_MANAGE,
        PERM_CRITICALITY_HAZARD_VIEW,
        PERM_MASTERDATA_VIEW,
        PERM_OPERATIONS_PACKAGE_CREATE,
        PERM_OPERATIONS_PACKAGE_LOCK,
        PERM_OPERATIONS_PACKAGE_ALLOCATE,
        PERM_OPERATIONS_PACKAGE_OVERRIDE_REQUEST,
        PERM_OPERATIONS_PACKAGE_OVERRIDE_APPROVE,
        PERM_OPERATIONS_FULFILLMENT_MODE_SET,
        PERM_OPERATIONS_STAGING_WAREHOUSE_OVERRIDE,
        PERM_OPERATIONS_PARTIAL_RELEASE_REQUEST,
        PERM_OPERATIONS_PARTIAL_RELEASE_APPROVE,
        PERM_OPERATIONS_DISPATCH_PREPARE,
        PERM_OPERATIONS_DISPATCH_EXECUTE,
        PERM_OPERATIONS_CONSOLIDATION_DISPATCH,
        PERM_OPERATIONS_CONSOLIDATION_RECEIVE,
        PERM_OPERATIONS_PICKUP_RELEASE,
        PERM_OPERATIONS_WAYBILL_VIEW,
        PERM_OPERATIONS_NOTIFICATION_RECEIVE,
        PERM_OPERATIONS_QUEUE_VIEW,
    },
    "TST_LOGISTICS_MANAGER": {
        PERM_NEEDS_LIST_RETURN,
        PERM_NEEDS_LIST_REJECT,
        PERM_NEEDS_LIST_APPROVE,
        PERM_NEEDS_LIST_ESCALATE,
        PERM_NEEDS_LIST_REVIEW_COMMENTS,
        PERM_CRITICALITY_OVERRIDE_VIEW,
        PERM_CRITICALITY_OVERRIDE_MANAGE,
        PERM_CRITICALITY_HAZARD_VIEW,
        PERM_MASTERDATA_VIEW,
        PERM_OPERATIONS_PACKAGE_CREATE,
        PERM_OPERATIONS_PACKAGE_LOCK,
        PERM_OPERATIONS_PACKAGE_ALLOCATE,
        PERM_OPERATIONS_PACKAGE_OVERRIDE_REQUEST,
        PERM_OPERATIONS_PACKAGE_OVERRIDE_APPROVE,
        PERM_OPERATIONS_FULFILLMENT_MODE_SET,
        PERM_OPERATIONS_STAGING_WAREHOUSE_OVERRIDE,
        PERM_OPERATIONS_PARTIAL_RELEASE_REQUEST,
        PERM_OPERATIONS_PARTIAL_RELEASE_APPROVE,
        PERM_OPERATIONS_DISPATCH_PREPARE,
        PERM_OPERATIONS_DISPATCH_EXECUTE,
        PERM_OPERATIONS_CONSOLIDATION_DISPATCH,
        PERM_OPERATIONS_CONSOLIDATION_RECEIVE,
        PERM_OPERATIONS_PICKUP_RELEASE,
        PERM_OPERATIONS_WAYBILL_VIEW,
        PERM_OPERATIONS_NOTIFICATION_RECEIVE,
        PERM_OPERATIONS_QUEUE_VIEW,
    },
    "ODPEM_DDG": {
        PERM_OPERATIONS_ELIGIBILITY_REVIEW,
        PERM_OPERATIONS_ELIGIBILITY_APPROVE,
        PERM_OPERATIONS_ELIGIBILITY_REJECT,
        PERM_OPERATIONS_NOTIFICATION_RECEIVE,
        PERM_OPERATIONS_QUEUE_VIEW,
    },
    # National command role compatibility for phase-window administration.
    "TST_DG": {
        PERM_EVENT_PHASE_WINDOW_VIEW,
        PERM_EVENT_PHASE_WINDOW_MANAGE,
        PERM_CRITICALITY_HAZARD_VIEW,
        PERM_CRITICALITY_HAZARD_MANAGE,
        PERM_CRITICALITY_HAZARD_APPROVE,
        PERM_MASTERDATA_VIEW,
        PERM_OPERATIONS_ELIGIBILITY_REVIEW,
        PERM_OPERATIONS_ELIGIBILITY_APPROVE,
        PERM_OPERATIONS_ELIGIBILITY_REJECT,
        PERM_OPERATIONS_NOTIFICATION_RECEIVE,
        PERM_OPERATIONS_QUEUE_VIEW,
    },
    "TST_DIR_PEOD": {
        PERM_EVENT_PHASE_WINDOW_VIEW,
        PERM_EVENT_PHASE_WINDOW_MANAGE,
        PERM_CRITICALITY_HAZARD_VIEW,
        PERM_CRITICALITY_HAZARD_MANAGE,
        PERM_CRITICALITY_HAZARD_APPROVE,
        PERM_MASTERDATA_VIEW,
        PERM_OPERATIONS_ELIGIBILITY_REVIEW,
        PERM_OPERATIONS_ELIGIBILITY_APPROVE,
        PERM_OPERATIONS_ELIGIBILITY_REJECT,
        PERM_OPERATIONS_NOTIFICATION_RECEIVE,
        PERM_OPERATIONS_QUEUE_VIEW,
    },
    "DG": {
        PERM_EVENT_PHASE_WINDOW_VIEW,
        PERM_EVENT_PHASE_WINDOW_MANAGE,
        PERM_CRITICALITY_HAZARD_VIEW,
        PERM_CRITICALITY_HAZARD_MANAGE,
        PERM_CRITICALITY_HAZARD_APPROVE,
        PERM_MASTERDATA_VIEW,
        PERM_OPERATIONS_ELIGIBILITY_REVIEW,
        PERM_OPERATIONS_ELIGIBILITY_APPROVE,
        PERM_OPERATIONS_ELIGIBILITY_REJECT,
        PERM_OPERATIONS_NOTIFICATION_RECEIVE,
        PERM_OPERATIONS_QUEUE_VIEW,
    },
    "DIRECTOR_GENERAL": {
        PERM_EVENT_PHASE_WINDOW_VIEW,
        PERM_EVENT_PHASE_WINDOW_MANAGE,
        PERM_CRITICALITY_HAZARD_VIEW,
        PERM_CRITICALITY_HAZARD_MANAGE,
        PERM_CRITICALITY_HAZARD_APPROVE,
        PERM_MASTERDATA_VIEW,
        PERM_OPERATIONS_ELIGIBILITY_REVIEW,
        PERM_OPERATIONS_ELIGIBILITY_APPROVE,
        PERM_OPERATIONS_ELIGIBILITY_REJECT,
        PERM_OPERATIONS_NOTIFICATION_RECEIVE,
        PERM_OPERATIONS_QUEUE_VIEW,
    },
    "DIR_PEOD": {
        PERM_EVENT_PHASE_WINDOW_VIEW,
        PERM_EVENT_PHASE_WINDOW_MANAGE,
        PERM_CRITICALITY_HAZARD_VIEW,
        PERM_CRITICALITY_HAZARD_MANAGE,
        PERM_CRITICALITY_HAZARD_APPROVE,
        PERM_MASTERDATA_VIEW,
        PERM_OPERATIONS_ELIGIBILITY_REVIEW,
        PERM_OPERATIONS_ELIGIBILITY_APPROVE,
        PERM_OPERATIONS_ELIGIBILITY_REJECT,
        PERM_OPERATIONS_NOTIFICATION_RECEIVE,
        PERM_OPERATIONS_QUEUE_VIEW,
    },
    "ODPEM_DG": {
        PERM_EVENT_PHASE_WINDOW_VIEW,
        PERM_EVENT_PHASE_WINDOW_MANAGE,
        PERM_CRITICALITY_HAZARD_VIEW,
        PERM_CRITICALITY_HAZARD_MANAGE,
        PERM_CRITICALITY_HAZARD_APPROVE,
        PERM_MASTERDATA_VIEW,
        PERM_OPERATIONS_ELIGIBILITY_REVIEW,
        PERM_OPERATIONS_ELIGIBILITY_APPROVE,
        PERM_OPERATIONS_ELIGIBILITY_REJECT,
        PERM_OPERATIONS_NOTIFICATION_RECEIVE,
        PERM_OPERATIONS_QUEUE_VIEW,
    },
    "ODPEM_DIR_PEOD": {
        PERM_EVENT_PHASE_WINDOW_VIEW,
        PERM_EVENT_PHASE_WINDOW_MANAGE,
        PERM_CRITICALITY_HAZARD_VIEW,
        PERM_CRITICALITY_HAZARD_MANAGE,
        PERM_CRITICALITY_HAZARD_APPROVE,
        PERM_MASTERDATA_VIEW,
        PERM_OPERATIONS_ELIGIBILITY_REVIEW,
        PERM_OPERATIONS_ELIGIBILITY_APPROVE,
        PERM_OPERATIONS_ELIGIBILITY_REJECT,
        PERM_OPERATIONS_NOTIFICATION_RECEIVE,
        PERM_OPERATIONS_QUEUE_VIEW,
    },
    "TST_READONLY": {
        PERM_MASTERDATA_VIEW,
        PERM_OPERATIONS_WAYBILL_VIEW,
        PERM_OPERATIONS_QUEUE_VIEW,
    },
    "SYSTEM_ADMINISTRATOR": {
        PERM_OPERATIONS_REQUEST_CREATE_SELF,
        PERM_OPERATIONS_REQUEST_CREATE_FOR_SUBORDINATE,
        PERM_OPERATIONS_REQUEST_CREATE_ON_BEHALF_BRIDGE,
        PERM_OPERATIONS_REQUEST_EDIT_DRAFT,
        PERM_OPERATIONS_REQUEST_SUBMIT,
        PERM_OPERATIONS_ELIGIBILITY_REVIEW,
        PERM_OPERATIONS_ELIGIBILITY_APPROVE,
        PERM_OPERATIONS_ELIGIBILITY_REJECT,
        PERM_OPERATIONS_PACKAGE_CREATE,
        PERM_OPERATIONS_PACKAGE_LOCK,
        PERM_OPERATIONS_PACKAGE_ALLOCATE,
        PERM_OPERATIONS_PACKAGE_OVERRIDE_REQUEST,
        PERM_OPERATIONS_PACKAGE_OVERRIDE_APPROVE,
        PERM_OPERATIONS_FULFILLMENT_MODE_SET,
        PERM_OPERATIONS_STAGING_WAREHOUSE_OVERRIDE,
        PERM_OPERATIONS_PARTIAL_RELEASE_REQUEST,
        PERM_OPERATIONS_PARTIAL_RELEASE_APPROVE,
        PERM_OPERATIONS_DISPATCH_PREPARE,
        PERM_OPERATIONS_DISPATCH_EXECUTE,
        PERM_OPERATIONS_CONSOLIDATION_DISPATCH,
        PERM_OPERATIONS_CONSOLIDATION_RECEIVE,
        PERM_OPERATIONS_PICKUP_RELEASE,
        PERM_OPERATIONS_RECEIPT_CONFIRM,
        PERM_OPERATIONS_WAYBILL_VIEW,
        PERM_OPERATIONS_NOTIFICATION_RECEIVE,
        PERM_OPERATIONS_QUEUE_VIEW,
    },
}

GOVERNED_CATALOG_ROLE_CODES = frozenset({
    "SYSTEM_ADMINISTRATOR",
    "ODPEM_DDG",
    "ODPEM_DG",
    "ODPEM_DIR_PEOD",
    "DG",
    "DIR_PEOD",
    "DIRECTOR_GENERAL",
    "TST_DG",
    "TST_DIR_PEOD",
    "TST_READONLY",
})


def _dedupe_preserve_order(items: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(items))


def has_governed_catalog_access(roles: Iterable[str]) -> bool:
    normalized_roles = {
        str(role or "").strip().upper()
        for role in roles
        if str(role or "").strip()
    }
    return bool(normalized_roles.intersection(GOVERNED_CATALOG_ROLE_CODES))


def resolve_roles_and_permissions(
    request, principal: Principal
) -> Tuple[list[str], list[str]]:
    if hasattr(request, "_rbac_cache"):
        cached = request._rbac_cache
        return cached["roles"], cached["permissions"]

    roles: list[str] = list(principal.roles or [])
    permissions: list[str] = list(getattr(principal, "permissions", []) or [])
    db_error = False

    if _db_rbac_enabled():
        try:
            user_id = _resolve_user_id(principal)
            if user_id is not None:
                roles = _dedupe_preserve_order(list(roles) + _fetch_roles(user_id))
                permissions = _dedupe_preserve_order(
                    list(permissions) + list(_fetch_permissions(user_id))
                )
            if roles:
                permissions = _dedupe_preserve_order(
                    list(permissions) + list(_fetch_permissions_for_role_codes(roles))
                )
        except DatabaseError as exc:
            db_error = True
            logger.warning("RBAC DB lookup failed: %s", exc)

    if settings.DEV_AUTH_ENABLED:
        permissions = _dedupe_preserve_order(
            list(permissions) + list(_permissions_for_roles(roles))
        )
    elif not permissions and not db_error:
        permissions = _dedupe_preserve_order(
            list(permissions) + list(_permissions_for_roles(roles))
        )

    permissions = _dedupe_preserve_order(
        list(permissions) + list(_compat_permissions_for_roles(roles))
    )
    permissions = _dedupe_preserve_order(
        list(permissions) + list(_compat_operations_permissions_for_permissions(permissions))
    )

    request._rbac_cache = {"roles": roles, "permissions": permissions}
    return roles, permissions


def _db_rbac_enabled() -> bool:
    if getattr(settings, "TESTING", False):
        return False
    if not settings.AUTH_USE_DB_RBAC:
        return False
    return settings.DATABASES["default"]["ENGINE"].endswith("postgresql")


def _resolve_user_id(principal: Principal) -> int | None:
    if principal.user_id:
        try:
            return int(principal.user_id)
        except ValueError:
            pass

    if not principal.username:
        return None

    with connection.cursor() as cursor:
        cursor.execute(
            'SELECT user_id FROM "user" WHERE username = %s OR email = %s LIMIT 1',
            [principal.username, principal.username],
        )
        row = cursor.fetchone()
        return int(row[0]) if row else None


def _fetch_roles(user_id: int) -> list[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT DISTINCT r.code
            FROM user_role ur
            JOIN role r ON r.id = ur.role_id
            WHERE ur.user_id = %s
            """,
            [user_id],
        )
        return [row[0] for row in cursor.fetchall()]


def _fetch_permissions(user_id: int) -> set[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT DISTINCT p.resource, p.action
            FROM user_role ur
            JOIN role_permission rp ON rp.role_id = ur.role_id
            JOIN permission p ON p.perm_id = rp.perm_id
            WHERE ur.user_id = %s
            """,
            [user_id],
        )
        return {f"{row[0]}.{row[1]}" for row in cursor.fetchall()}


def _fetch_permissions_for_role_codes(role_codes: Iterable[str]) -> set[str]:
    normalized_codes = sorted(
        {str(code).strip().upper() for code in role_codes if str(code).strip()}
    )
    if not normalized_codes:
        return set()

    placeholders = ", ".join(["%s"] * len(normalized_codes))
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT DISTINCT p.resource, p.action
            FROM role r
            JOIN role_permission rp ON rp.role_id = r.id
            JOIN permission p ON p.perm_id = rp.perm_id
            WHERE UPPER(r.code) IN ({placeholders})
            """,
            normalized_codes,
        )
        return {f"{row[0]}.{row[1]}" for row in cursor.fetchall()}


def _permissions_for_roles(roles: Iterable[str]) -> set[str]:
    permissions: set[str] = set()
    for role in roles:
        permissions |= _DEV_ROLE_PERMISSION_MAP.get(role.upper(), set())
    return permissions


def _compat_permissions_for_roles(roles: Iterable[str]) -> set[str]:
    permissions: set[str] = set()
    for role in roles:
        permissions |= _ROLE_PERMISSION_COMPAT_OVERRIDES.get(role.upper(), set())
    return permissions


def _compat_operations_permissions_for_permissions(permissions: Iterable[str]) -> set[str]:
    normalized = {str(permission or "").strip().lower() for permission in permissions if str(permission or "").strip()}
    compat: set[str] = set()
    if PERM_NEEDS_LIST_SUBMIT.lower() in normalized:
        compat |= {
            PERM_OPERATIONS_REQUEST_CREATE_SELF,
            PERM_OPERATIONS_REQUEST_CREATE_FOR_SUBORDINATE,
            PERM_OPERATIONS_REQUEST_EDIT_DRAFT,
            PERM_OPERATIONS_REQUEST_SUBMIT,
            PERM_OPERATIONS_QUEUE_VIEW,
            PERM_OPERATIONS_NOTIFICATION_RECEIVE,
        }
    if PERM_NEEDS_LIST_APPROVE.lower() in normalized:
        compat |= {
            PERM_OPERATIONS_ELIGIBILITY_REVIEW,
            PERM_OPERATIONS_ELIGIBILITY_APPROVE,
            PERM_OPERATIONS_ELIGIBILITY_REJECT,
            PERM_OPERATIONS_QUEUE_VIEW,
            PERM_OPERATIONS_NOTIFICATION_RECEIVE,
        }
    if PERM_NEEDS_LIST_EXECUTE.lower() in normalized:
        compat |= {
            PERM_OPERATIONS_PACKAGE_CREATE,
            PERM_OPERATIONS_PACKAGE_LOCK,
            PERM_OPERATIONS_PACKAGE_ALLOCATE,
            PERM_OPERATIONS_PACKAGE_OVERRIDE_REQUEST,
            PERM_OPERATIONS_DISPATCH_PREPARE,
            PERM_OPERATIONS_DISPATCH_EXECUTE,
            PERM_OPERATIONS_WAYBILL_VIEW,
            PERM_OPERATIONS_QUEUE_VIEW,
            PERM_OPERATIONS_NOTIFICATION_RECEIVE,
        }
    if PERM_NATIONAL_ACT_CROSS_TENANT.lower() in normalized and {
        PERM_OPERATIONS_REQUEST_CREATE_SELF,
        PERM_OPERATIONS_REQUEST_CREATE_FOR_SUBORDINATE,
    }.intersection(compat):
        compat.add(PERM_OPERATIONS_REQUEST_CREATE_ON_BEHALF_BRIDGE)
    return compat
