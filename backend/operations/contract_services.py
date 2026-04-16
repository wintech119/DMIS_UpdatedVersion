from __future__ import annotations

import uuid
import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping, Sequence

from django.conf import settings
from django.core.cache import cache
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.db.models import Count, F, Q, Sum
from django.utils.dateparse import parse_datetime
from django.utils import timezone

from api.rbac import (
    PERM_OPERATIONS_FULFILLMENT_MODE_SET,
    PERM_OPERATIONS_PACKAGE_ALLOCATE,
)
from api.tenancy import TenantContext, can_access_tenant, can_access_warehouse
from masterdata.services.data_access import get_lookup
from operations import policy as operations_policy
from operations.constants import (
    CONSOLIDATION_LEG_STATUS_CANCELLED,
    CONSOLIDATION_LEG_STATUS_IN_TRANSIT,
    CONSOLIDATION_LEG_STATUS_PLANNED,
    CONSOLIDATION_LEG_STATUS_RECEIVED_AT_STAGING,
    CONSOLIDATION_STATUS_ALL_RECEIVED,
    CONSOLIDATION_STATUS_AWAITING_LEGS,
    CONSOLIDATION_STATUS_LEGS_IN_TRANSIT,
    CONSOLIDATION_STATUS_PARTIAL_RELEASE_REQUESTED,
    CONSOLIDATION_STATUS_PARTIALLY_RECEIVED,
    DISPATCH_ROLE_CODES,
    DISPATCH_STATUS_IN_TRANSIT,
    DISPATCH_STATUS_READY,
    DISPATCH_STATUS_RECEIVED,
    ELIGIBILITY_ROLE_CODES,
    EVENT_CONSOLIDATION_DISPATCHED,
    EVENT_CONSOLIDATION_PLANNED,
    EVENT_DISPATCH_COMPLETED,
    EVENT_OVERRIDE_APPROVED,
    EVENT_OVERRIDE_REQUESTED,
    EVENT_PACKAGE_CANCELLED,
    EVENT_PACKAGE_COMMITTED,
    EVENT_PACKAGE_LOCKED,
    EVENT_PACKAGE_SPLIT,
    EVENT_PARTIAL_RELEASE_APPROVED,
    EVENT_PARTIAL_RELEASE_REQUESTED,
    EVENT_PICKUP_RELEASED,
    EVENT_RECEIPT_CONFIRMED,
    EVENT_REQUEST_APPROVED,
    EVENT_REQUEST_INELIGIBLE,
    EVENT_REQUEST_REJECTED,
    EVENT_REQUEST_SUBMITTED,
    EVENT_STAGED_DELIVERY_READY,
    EVENT_PACKAGE_UNLOCKED,
    EVENT_STAGING_RECEIPT_RECORDED,
    FULFILLMENT_MODE_DELIVER_FROM_STAGING,
    FULFILLMENT_MODE_DIRECT,
    FULFILLMENT_MODE_PICKUP_AT_STAGING,
    FULFILLMENT_ROLE_CODES,
    ORIGIN_MODE_SELF,
    PACKAGE_STATUS_COMMITTED,
    PACKAGE_STATUS_CONSOLIDATING,
    PACKAGE_STATUS_CANCELLED,
    PACKAGE_STATUS_DRAFT,
    PACKAGE_STATUS_DISPATCHED,
    PACKAGE_STATUS_PENDING_OVERRIDE_APPROVAL,
    PACKAGE_STATUS_READY_FOR_DISPATCH,
    PACKAGE_STATUS_READY_FOR_PICKUP,
    PACKAGE_STATUS_RECEIVED,
    PACKAGE_STATUS_SPLIT,
    QUEUE_CODE_DISPATCH,
    QUEUE_CODE_CONSOLIDATION_DISPATCH,
    QUEUE_CODE_ELIGIBILITY,
    QUEUE_CODE_FULFILLMENT,
    QUEUE_CODE_OVERRIDE,
    QUEUE_CODE_PARTIAL_RELEASE_APPROVAL,
    QUEUE_CODE_PICKUP_RELEASE,
    QUEUE_CODE_RECEIPT,
    QUEUE_CODE_STAGING_RECEIPT,
    REQUEST_STATUS_APPROVED_FOR_FULFILLMENT,
    REQUEST_STATUS_CANCELLED,
    REQUEST_STATUS_DRAFT,
    REQUEST_STATUS_FULFILLED,
    REQUEST_STATUS_INELIGIBLE,
    REQUEST_STATUS_PARTIALLY_FULFILLED,
    REQUEST_STATUS_REJECTED,
    REQUEST_STATUS_SUBMITTED,
    REQUEST_STATUS_UNDER_ELIGIBILITY_REVIEW,
    ROLE_LOGISTICS_OFFICER,
    ROLE_LOGISTICS_MANAGER,
    ROLE_SYSTEM_ADMINISTRATOR,
    STATUS_LABELS,
    normalize_role_codes,
)
from operations.exceptions import OperationValidationError
from operations.models import (
    OperationsAllocationLine,
    OperationsConsolidationLeg,
    OperationsConsolidationLegItem,
    OperationsConsolidationReceipt,
    OperationsConsolidationWaybill,
    OperationsDispatch,
    OperationsDispatchTransport,
    OperationsEligibilityDecision,
    OperationsPackage,
    OperationsPackageLock,
    OperationsPickupRelease,
    OperationsQueueAssignment,
    OperationsReceipt,
    OperationsReliefRequest,
    OperationsWaybill,
)
from operations.workflow import (
    actor_notification_queryset,
    actor_queue_queryset,
    assign_roles_to_queue,
    assign_user_to_queue,
    complete_queue_assignments,
    create_role_notifications,
    create_user_notification,
    record_status_transition,
)
from operations.staging_selection import (
    beneficiary_parish_code_for_request,
    get_staging_hub_details,
    recommend_staging_hub,
)
from replenishment.models import NeedsListExecutionLink
from replenishment.services import data_access
from replenishment.services.allocation_dispatch import (
    DispatchError,
    LegacyWorkflowContext,
    OptimisticLockError,
    OverrideApprovalError,
    _advance_transfer_rows,
    _apply_package_header_updates,
    _apply_stock_delta_for_rows,
    _as_iso,
    _current_package_status,
    _fetch_batch_candidates,
    _group_plan_rows,
    _inventory_batch_drift_message,
    _inventory_batch_stock_totals,
    _load_package_plan_with_source_info,
    _next_int_id,
    _package_plan_map,
    _qualified_table,
    _quantize_qty,
    _request_completion_status,
    _selected_plan_for_package,
    _upsert_package_rows,
    approve_override as compat_approve_override,
    build_greedy_allocation_plan,
    commit_allocation as compat_commit_allocation,
    dispatch_package as compat_dispatch_package,
    get_allocation_options as compat_get_allocation_options,
    get_current_allocation as compat_get_current_allocation,
    sort_batch_candidates,
    validate_override_approval,
)
from replenishment.legacy_models import (
    Agency,
    Item,
    Inventory,
    ItemBatch,
    ReliefPkg,
    ReliefPkgItem,
    ReliefRqst,
    Transfer,
    TransferItem,
)

_UNSET = object()

ENTITY_REQUEST = "RELIEF_REQUEST"
ENTITY_PACKAGE = "PACKAGE"
ENTITY_DISPATCH = "DISPATCH"
ENTITY_CONSOLIDATION_LEG = "CONSOLIDATION_LEG"
ENTITY_PICKUP_RELEASE = "PICKUP_RELEASE"
_VALID_ALLOCATION_SOURCE_TYPES = {"ON_HAND", "TRANSFER", "DONATION", "PROCUREMENT"}
_OPERATIONS_NATIVE_PACKAGE_STATUSES = frozenset(
    {
        PACKAGE_STATUS_PENDING_OVERRIDE_APPROVAL,
        PACKAGE_STATUS_CONSOLIDATING,
        PACKAGE_STATUS_READY_FOR_DISPATCH,
        PACKAGE_STATUS_READY_FOR_PICKUP,
        PACKAGE_STATUS_SPLIT,
        PACKAGE_STATUS_CANCELLED,
    }
)
_REQUEST_URGENCY_VALUES = {"C", "H", "M", "L"}
_REQUEST_ITEM_REASON_MAX_LENGTH = 255

STATUS_DRAFT = 0
STATUS_AWAITING_APPROVAL = 1
STATUS_CANCELLED = 2
STATUS_SUBMITTED = 3
STATUS_DENIED = 4
STATUS_PART_FILLED = 5
STATUS_CLOSED = 6
STATUS_FILLED = 7
STATUS_INELIGIBLE = 8

PKG_STATUS_DRAFT = "A"
PKG_STATUS_PENDING = "P"
PKG_STATUS_DISPATCHED = "D"
PKG_STATUS_COMPLETED = "C"

REQUEST_STATUS_LABELS = {
    STATUS_DRAFT: "Draft",
    STATUS_AWAITING_APPROVAL: "Awaiting Approval",
    STATUS_CANCELLED: "Cancelled",
    STATUS_SUBMITTED: "Submitted",
    STATUS_DENIED: "Denied",
    STATUS_PART_FILLED: "Part Filled",
    STATUS_CLOSED: "Closed",
    STATUS_FILLED: "Filled",
    STATUS_INELIGIBLE: "Ineligible",
}

PKG_STATUS_LABELS = {
    PKG_STATUS_DRAFT: "Draft",
    PKG_STATUS_PENDING: "Pending",
    PKG_STATUS_DISPATCHED: "Dispatched",
    PKG_STATUS_COMPLETED: "Completed",
}

REQUEST_LIST_FILTERS = {
    "draft": {STATUS_DRAFT},
    "awaiting": {STATUS_AWAITING_APPROVAL},
    "submitted": {STATUS_SUBMITTED, STATUS_PART_FILLED},
    "processing": {STATUS_AWAITING_APPROVAL, STATUS_PART_FILLED},
    "completed": {STATUS_FILLED},
    "dispatched": {STATUS_CLOSED},
}

FULFILLMENT_REQUEST_STATUSES = frozenset({STATUS_SUBMITTED, STATUS_PART_FILLED})
_IDEMPOTENCY_TTL_SECONDS = 15 * 60
# Keep failed reservations short-lived so retries recover quickly if a write aborts
# before the success payload is published to the replay cache.
_IDEMPOTENCY_IN_PROGRESS_TTL_SECONDS = 60


def _fetch_rows(sql: str, params: Sequence[Any] | None = None) -> list[dict[str, Any]]:
    with connection.cursor() as cursor:
        cursor.execute(sql, list(params or []))
        columns = [col[0] for col in cursor.description or []]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _execute(sql: str, params: Sequence[Any] | None = None) -> int:
    with connection.cursor() as cursor:
        cursor.execute(sql, list(params or []))
        return cursor.rowcount


def _tenant_cache_key_value(tenant_context: TenantContext | None) -> str:
    if tenant_context is None:
        return "legacy"
    tenant_id = getattr(tenant_context, "active_tenant_id", None) or getattr(tenant_context, "requested_tenant_id", None)
    return str(tenant_id or "unknown")


def _validated_idempotency_key(idempotency_key: str | None) -> str:
    normalized = str(idempotency_key or "").strip()
    if not normalized:
        raise OperationValidationError({"idempotency_key": "Idempotency-Key header is required."})
    return normalized


def _idempotency_cache_key(
    *,
    endpoint: str,
    actor_id: str,
    tenant_context: TenantContext | None,
    reliefpkg_id: int,
    idempotency_key: str,
) -> str:
    digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
    return (
        f"operations:idempotency:{endpoint}:{actor_id}:{_tenant_cache_key_value(tenant_context)}:"
        f"{int(reliefpkg_id)}:{digest}"
    )


@dataclass(frozen=True)
class _IdempotencyWriteLease:
    cache_key: str | None = None
    cached_result: dict[str, Any] | None = None
    reservation_key: str | None = None
    reservation_token: str | None = None


def _cached_idempotent_response(cache_key: str | None) -> dict[str, Any] | None:
    if not cache_key:
        return None
    cached_result = cache.get(cache_key)
    if not isinstance(cached_result, dict):
        return None
    return cached_result


def _idempotency_reservation_key(cache_key: str) -> str:
    return f"{cache_key}:in_progress"


def _release_idempotency_reservation(*, reservation_key: str | None, reservation_token: str | None) -> None:
    if not reservation_key or not reservation_token:
        return
    current_token = cache.get(reservation_key)
    if current_token == reservation_token:
        cache.delete(reservation_key)


def _idempotency_cache_state(
    *,
    endpoint: str,
    actor_id: str,
    tenant_context: TenantContext | None,
    resource_id: int,
    idempotency_key: str | None,
) -> tuple[str, str, dict[str, Any] | None]:
    normalized_idempotency_key = _validated_idempotency_key(idempotency_key)
    cache_key = _idempotency_cache_key(
        endpoint=endpoint,
        actor_id=actor_id,
        tenant_context=tenant_context,
        reliefpkg_id=resource_id,
        idempotency_key=normalized_idempotency_key,
    )
    cached_result = _cached_idempotent_response(cache_key)
    return normalized_idempotency_key, cache_key, cached_result


def _begin_idempotent_write(
    *,
    endpoint: str,
    actor_id: str,
    tenant_context: TenantContext | None,
    resource_id: int,
    idempotency_key: str | None,
    required: bool = True,
) -> _IdempotencyWriteLease:
    if not required and idempotency_key is None:
        return _IdempotencyWriteLease()

    _, cache_key, cached_result = _idempotency_cache_state(
        endpoint=endpoint,
        actor_id=actor_id,
        tenant_context=tenant_context,
        resource_id=resource_id,
        idempotency_key=idempotency_key,
    )
    if cached_result is not None:
        return _IdempotencyWriteLease(cache_key=cache_key, cached_result=cached_result)

    reservation_key = _idempotency_reservation_key(cache_key)
    reservation_token = uuid.uuid4().hex
    reserved = cache.add(
        reservation_key,
        reservation_token,
        timeout=_IDEMPOTENCY_IN_PROGRESS_TTL_SECONDS,
    )
    if not reserved:
        cached_result = _cached_idempotent_response(cache_key)
        if cached_result is not None:
            return _IdempotencyWriteLease(cache_key=cache_key, cached_result=cached_result)
        raise OperationValidationError(
            {"idempotency_key": "A request with this Idempotency-Key is already in progress."}
        )

    cached_result = _cached_idempotent_response(cache_key)
    if cached_result is not None:
        _release_idempotency_reservation(
            reservation_key=reservation_key,
            reservation_token=reservation_token,
        )
        return _IdempotencyWriteLease(cache_key=cache_key, cached_result=cached_result)

    return _IdempotencyWriteLease(
        cache_key=cache_key,
        reservation_key=reservation_key,
        reservation_token=reservation_token,
    )


def peek_idempotent_response(
    *,
    endpoint: str,
    actor_id: str,
    tenant_context: TenantContext | None,
    resource_id: int,
    idempotency_key: str,
) -> dict[str, Any] | None:
    _, _, cached_result = _idempotency_cache_state(
        endpoint=endpoint,
        actor_id=actor_id,
        tenant_context=tenant_context,
        resource_id=resource_id,
        idempotency_key=idempotency_key,
    )
    return cached_result


def _cache_idempotent_response_after_commit(
    cache_key: str | None,
    payload: dict[str, Any],
    *,
    reservation_key: str | None = None,
    reservation_token: str | None = None,
) -> None:
    if not cache_key:
        return

    def _store() -> None:
        cache.set(cache_key, payload, timeout=_IDEMPOTENCY_TTL_SECONDS)
        _release_idempotency_reservation(
            reservation_key=reservation_key,
            reservation_token=reservation_token,
        )

    transaction.on_commit(_store)


def _tracking_no(prefix: str, numeric_id: int) -> str:
    return f"{prefix}{int(numeric_id):05d}"


def _decimal_or_zero(value: Any) -> Decimal:
    try:
        return value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _positive_int(value: Any, field_name: str, errors: dict[str, str]) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        errors[field_name] = "Must be a positive integer."
        return None
    if parsed <= 0:
        errors[field_name] = "Must be a positive integer."
        return None
    return parsed


def _optional_positive_int(value: Any, field_name: str) -> int | None:
    if value in (None, ""):
        return None
    errors: dict[str, str] = {}
    parsed = _positive_int(value, field_name, errors)
    if errors:
        raise OperationValidationError(errors)
    return parsed


def _optional_date(value: Any, field_name: str, errors: dict[str, str]) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        errors[field_name] = "Invalid date"
        return None


def _event_exists(event_id: int) -> bool:
    try:
        normalized_event_id = int(event_id)
    except (TypeError, ValueError):
        return False
    table_name = _qualified_table("event")
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT 1 FROM {table_name} WHERE event_id = %s LIMIT 1", [normalized_event_id])
        return cursor.fetchone() is not None


def _load_request(reliefrqst_id: int, *, for_update: bool = False) -> ReliefRqst:
    queryset = ReliefRqst.objects.select_for_update() if for_update else ReliefRqst.objects
    return queryset.get(reliefrqst_id=reliefrqst_id)


def _load_package(reliefpkg_id: int, *, for_update: bool = False) -> ReliefPkg:
    queryset = ReliefPkg.objects.select_for_update() if for_update else ReliefPkg.objects
    return queryset.get(reliefpkg_id=reliefpkg_id)


def _current_package_for_request(reliefrqst_id: int, *, for_update: bool = False) -> ReliefPkg | None:
    queryset = ReliefPkg.objects.select_for_update() if for_update else ReliefPkg.objects
    return queryset.filter(reliefrqst_id=reliefrqst_id).order_by("-reliefpkg_id").first()


def _execution_link_for_request(reliefrqst_id: int) -> NeedsListExecutionLink | None:
    return NeedsListExecutionLink.objects.select_related("needs_list").filter(reliefrqst_id=reliefrqst_id).first()


def _execution_link_for_package(reliefpkg_id: int) -> NeedsListExecutionLink | None:
    return NeedsListExecutionLink.objects.select_related("needs_list").filter(reliefpkg_id=reliefpkg_id).first()


def _request_items(reliefrqst_id: int) -> list[dict[str, Any]]:
    rows = _fetch_rows(
        f"""
        SELECT item_id, request_qty, issue_qty, urgency_ind, rqst_reason_desc, required_by_date, status_code
        FROM {_qualified_table("reliefrqst_item")}
        WHERE reliefrqst_id = %s
        ORDER BY item_id
        """,
        [reliefrqst_id],
    )
    item_ids = [int(row["item_id"]) for row in rows]
    item_names, _ = data_access.get_item_names(item_ids)
    result: list[dict[str, Any]] = []
    for row in rows:
        lookup = item_names.get(int(row["item_id"]), {})
        result.append(
            {
                "item_id": int(row["item_id"]),
                "item_code": lookup.get("item_code") or lookup.get("code"),
                "item_name": lookup.get("item_name") or lookup.get("name"),
                "request_qty": str(_quantize_qty(row.get("request_qty"))),
                "issue_qty": str(_quantize_qty(row.get("issue_qty"))),
                "urgency_ind": row.get("urgency_ind"),
                "rqst_reason_desc": row.get("rqst_reason_desc"),
                "required_by_date": _as_iso(row.get("required_by_date")),
                "status_code": row.get("status_code"),
            }
        )
    return result


def _ensure_request_in_fulfillment_state(request: ReliefRqst) -> None:
    if int(request.status_code or STATUS_DRAFT) not in FULFILLMENT_REQUEST_STATUSES:
        raise OperationValidationError(
            {
                "request": (
                    "Packages can only be managed for requests that are submitted for fulfillment "
                    "or already part filled."
                )
            }
        )


def _request_item_rows_for_allocation(reliefrqst_id: int) -> list[dict[str, Any]]:
    return _fetch_rows(
        f"""
        SELECT item_id, request_qty, issue_qty, urgency_ind, rqst_reason_desc, required_by_date
        FROM {_qualified_table("reliefrqst_item")}
        WHERE reliefrqst_id = %s
        ORDER BY item_id
        """,
        [reliefrqst_id],
    )


def _request_summary(request: ReliefRqst) -> dict[str, Any]:
    items = _request_items(int(request.reliefrqst_id))
    package = _current_package_for_request(int(request.reliefrqst_id))
    execution_link = _execution_link_for_request(int(request.reliefrqst_id))
    agency = Agency.objects.filter(agency_id=request.agency_id).first()
    total_requested = sum((_decimal_or_zero(item["request_qty"]) for item in items), Decimal("0"))
    total_issued = sum((_decimal_or_zero(item["issue_qty"]) for item in items), Decimal("0"))
    return {
        "reliefrqst_id": int(request.reliefrqst_id),
        "tracking_no": request.tracking_no,
        "agency_id": request.agency_id,
        "agency_name": agency.agency_name if agency is not None else None,
        "eligible_event_id": request.eligible_event_id,
        "event_name": data_access.get_event_name(int(request.eligible_event_id))
        if request.eligible_event_id is not None
        else None,
        "urgency_ind": request.urgency_ind,
        "status_code": request.status_code,
        "status_label": REQUEST_STATUS_LABELS.get(int(request.status_code or -1), "Unknown"),
        "request_date": _as_iso(request.request_date),
        "create_dtime": _as_iso(request.create_dtime),
        "review_dtime": _as_iso(request.review_dtime),
        "action_dtime": _as_iso(request.action_dtime),
        "rqst_notes_text": request.rqst_notes_text,
        "review_notes_text": request.review_notes_text,
        "status_reason_desc": request.status_reason_desc,
        "version_nbr": request.version_nbr,
        "item_count": len(items),
        "total_requested_qty": str(total_requested.quantize(Decimal("0.0001"))),
        "total_issued_qty": str(total_issued.quantize(Decimal("0.0001"))),
        "reliefpkg_id": int(package.reliefpkg_id) if package is not None else None,
        "package_tracking_no": package.tracking_no if package is not None else None,
        "package_status": _current_package_status(package) if package is not None else None,
        "execution_status": execution_link.execution_status if execution_link is not None else None,
        "needs_list_id": execution_link.needs_list_id if execution_link is not None else None,
        "compatibility_bridge": execution_link is not None,
    }


def _package_summary(package: ReliefPkg) -> dict[str, Any]:
    execution_link = _execution_link_for_package(int(package.reliefpkg_id))
    return {
        "reliefpkg_id": int(package.reliefpkg_id),
        "tracking_no": package.tracking_no,
        "reliefrqst_id": int(package.reliefrqst_id),
        "agency_id": package.agency_id,
        "eligible_event_id": package.eligible_event_id,
        "to_inventory_id": package.to_inventory_id,
        "destination_warehouse_name": data_access.get_warehouse_name(int(package.to_inventory_id))
        if package.to_inventory_id is not None
        else None,
        "status_code": package.status_code,
        "status_label": PKG_STATUS_LABELS.get(_current_package_status(package), "Unknown"),
        "dispatch_dtime": _as_iso(package.dispatch_dtime),
        "received_dtime": _as_iso(package.received_dtime),
        "transport_mode": package.transport_mode,
        "comments_text": package.comments_text,
        "version_nbr": package.version_nbr,
        "execution_status": execution_link.execution_status if execution_link is not None else None,
        "needs_list_id": execution_link.needs_list_id if execution_link is not None else None,
        "compatibility_bridge": execution_link is not None,
    }


def _request_detail(request: ReliefRqst) -> dict[str, Any]:
    payload = _request_summary(request)
    payload["items"] = _request_items(int(request.reliefrqst_id))
    payload["packages"] = [
        _package_summary(package)
        for package in ReliefPkg.objects.filter(reliefrqst_id=request.reliefrqst_id).order_by("-reliefpkg_id")
    ]
    return payload


def _package_detail(package: ReliefPkg) -> dict[str, Any]:
    payload = _package_summary(package)
    execution_link = _execution_link_for_package(int(package.reliefpkg_id))
    if execution_link is not None:
        payload["allocation"] = compat_get_current_allocation(
            {
                "needs_list_id": int(execution_link.needs_list_id),
                "reliefrqst_id": int(package.reliefrqst_id),
                "reliefpkg_id": int(package.reliefpkg_id),
            }
        )
    else:
        rows = _load_package_plan_with_source_info(int(package.reliefpkg_id))
        payload["allocation"] = {
            "allocation_lines": [
                {**row, "quantity": str(_quantize_qty(row["quantity"]))}
                for row in rows
            ],
            "reserved_stock_summary": {
                "line_count": len(rows),
                "total_qty": str(
                    sum((_quantize_qty(row["quantity"]) for row in rows), Decimal("0")).quantize(Decimal("0.0001"))
                ),
            },
            "waybill_no": f"WB-{package.tracking_no}" if package.dispatch_dtime else None,
        }
    return payload


def _upsert_request_items(reliefrqst_id: int, items: Sequence[Mapping[str, Any]]) -> None:
    table_name = _qualified_table("reliefrqst_item")
    for item in items:
        updated = _execute(
            f"""
            UPDATE {table_name}
            SET request_qty = %s,
                urgency_ind = %s,
                rqst_reason_desc = %s,
                required_by_date = %s,
                version_nbr = version_nbr + 1
            WHERE reliefrqst_id = %s
              AND item_id = %s
            """,
            [
                item["request_qty"],
                item["urgency_ind"],
                item["rqst_reason_desc"],
                item["required_by_date"],
                reliefrqst_id,
                item["item_id"],
            ],
        )
        if updated:
            continue
        _execute(
            f"""
            INSERT INTO {table_name}
                (reliefrqst_id, item_id, request_qty, issue_qty, urgency_ind, rqst_reason_desc, required_by_date, status_code, version_nbr)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [
                reliefrqst_id,
                item["item_id"],
                item["request_qty"],
                Decimal("0"),
                item["urgency_ind"],
                item["rqst_reason_desc"],
                item["required_by_date"],
                "R",
                1,
            ],
        )


def _validate_request_payload(
    payload: Mapping[str, Any],
    *,
    partial: bool = False,
    existing_request: Any | None = None,
) -> dict[str, Any]:
    errors: dict[str, str] = {}
    normalized: dict[str, Any] = {}
    if not partial or "agency_id" in payload:
        normalized["agency_id"] = _positive_int(payload.get("agency_id"), "agency_id", errors)
    if not partial or "urgency_ind" in payload:
        urgency_ind = str(payload.get("urgency_ind") or "").strip().upper()
        if urgency_ind not in _REQUEST_URGENCY_VALUES:
            errors["urgency_ind"] = "Must be one of C, H, M, or L."
        else:
            normalized["urgency_ind"] = urgency_ind
    if "eligible_event_id" in payload:
        if payload.get("eligible_event_id") in (None, ""):
            normalized["eligible_event_id"] = None
        else:
            normalized["eligible_event_id"] = _positive_int(
                payload.get("eligible_event_id"),
                "eligible_event_id",
                errors,
            )
            if normalized["eligible_event_id"] is not None and not _event_exists(int(normalized["eligible_event_id"])):
                errors["eligible_event_id"] = "Selected event does not exist."
    if not partial or "rqst_notes_text" in payload:
        normalized["rqst_notes_text"] = str(payload.get("rqst_notes_text") or "").strip() or None
    effective_urgency_ind = normalized.get("urgency_ind")
    if partial and effective_urgency_ind is None:
        effective_urgency_ind = str(getattr(existing_request, "urgency_ind", "") or "").strip().upper() or None
    effective_request_notes = normalized.get("rqst_notes_text")
    if partial and "rqst_notes_text" not in normalized:
        effective_request_notes = str(getattr(existing_request, "rqst_notes_text", "") or "").strip() or None
    if effective_urgency_ind == "H" and not effective_request_notes:
        errors["rqst_notes_text"] = "Justification is required for high-urgency requests."
    raw_items = payload.get("items")
    normalized_items: list[dict[str, Any]] = []
    if raw_items is not None:
        if not isinstance(raw_items, list):
            errors["items"] = "Must be an array."
        else:
            for index, raw in enumerate(raw_items):
                if not isinstance(raw, Mapping):
                    errors[f"items[{index}]"] = "Each item must be an object."
                    continue
                item_id = _positive_int(raw.get("item_id"), f"items[{index}].item_id", errors)
                try:
                    request_qty = Decimal(str(raw.get("request_qty")))
                except (InvalidOperation, ValueError, TypeError):
                    errors[f"items[{index}].request_qty"] = "Must be a decimal number."
                    continue
                if request_qty <= 0:
                    errors[f"items[{index}].request_qty"] = "Must be greater than zero."
                urgency_ind = str(raw.get("urgency_ind") or normalized.get("urgency_ind") or "M").strip().upper()
                if urgency_ind not in _REQUEST_URGENCY_VALUES:
                    errors[f"items[{index}].urgency_ind"] = "Must be one of C, H, M, or L."
                reason = str(raw.get("rqst_reason_desc") or "").strip() or None
                if reason is not None and len(reason) > _REQUEST_ITEM_REASON_MAX_LENGTH:
                    errors[f"items[{index}].rqst_reason_desc"] = "Reason must be 255 characters or fewer."
                if urgency_ind in {"C", "H"} and not reason:
                    errors[f"items[{index}].rqst_reason_desc"] = "Reason is required for high-priority items."
                required_by_date = _optional_date(
                    raw.get("required_by_date"),
                    f"items[{index}].required_by_date",
                    errors,
                )
                normalized_items.append(
                    {
                        "item_id": item_id,
                        "request_qty": _quantize_qty(request_qty),
                        "urgency_ind": urgency_ind,
                        "rqst_reason_desc": reason,
                        "required_by_date": required_by_date,
                    }
                )

    if errors:
        raise OperationValidationError(errors)

    normalized["items"] = normalized_items
    return normalized



class _LegacyServiceFacade:
    pass


legacy_service = _LegacyServiceFacade()
_LEGACY_FACADE_DEFAULTS: dict[str, Any] = {}


def _require_actor_id(actor_id: str | None) -> str:
    """Reject calls with no traceable actor identifier."""
    if not actor_id:
        raise OperationValidationError({"actor": "A traceable actor identifier is required."})
    return actor_id


def _optional_positive_int_payload_value(
    payload: Mapping[str, Any],
    field_name: str,
) -> int | None | object:
    if field_name not in payload:
        return _UNSET
    raw_value = payload.get(field_name)
    if raw_value in (None, ""):
        return None
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise OperationValidationError({field_name: "Must be a positive integer."}) from exc
    if parsed <= 0:
        raise OperationValidationError({field_name: "Must be a positive integer."})
    return parsed


def _required_positive_int_from_allocation_row(
    raw: Mapping[str, Any],
    *,
    row_index: int,
    field_name: str,
    aliases: Iterable[str] | None = None,
) -> int:
    candidate_fields = [field_name, *(aliases or ())]
    raw_value = None
    resolved_field = field_name
    for candidate in candidate_fields:
        if candidate in raw and raw.get(candidate) not in (None, ""):
            raw_value = raw.get(candidate)
            resolved_field = candidate
            break
    try:
        parsed = int(str(raw_value).strip())
    except (TypeError, ValueError) as exc:
        raise OperationValidationError(
            {f"allocations[{row_index}].{resolved_field}": f"{resolved_field} must be a positive integer."}
        ) from exc
    if parsed <= 0:
        raise OperationValidationError(
            {f"allocations[{row_index}].{resolved_field}": f"{resolved_field} must be a positive integer."}
        )
    return parsed


def _validate_allocation_rows(raw_allocations: object) -> list[dict[str, Any]]:
    if raw_allocations in (None, ""):
        return []
    if not isinstance(raw_allocations, list):
        raise OperationValidationError({"allocations": "allocations must be provided as a list."})

    validated_rows: list[dict[str, Any]] = []
    seen_keys: set[tuple[int, int, int]] = set()
    for index, raw in enumerate(raw_allocations):
        if not isinstance(raw, Mapping):
            raise OperationValidationError({f"allocations[{index}]": "Each allocation row must be an object."})

        qty_value = raw.get("quantity", raw.get("allocated_qty"))
        try:
            qty_decimal = Decimal(str(qty_value).strip())
        except (InvalidOperation, TypeError, ValueError, AttributeError) as exc:
            raise OperationValidationError(
                {f"allocations[{index}].quantity": f"Invalid quantity for allocation row {index}: {qty_value!r}."}
            ) from exc
        if qty_decimal <= 0:
            raise OperationValidationError(
                {f"allocations[{index}].quantity": "Allocation quantity must be greater than zero."}
            )

        item_id = _required_positive_int_from_allocation_row(raw, row_index=index, field_name="item_id")
        source_warehouse_id = _required_positive_int_from_allocation_row(
            raw,
            row_index=index,
            field_name="inventory_id",
            aliases=("source_warehouse_id",),
        )
        batch_id = _required_positive_int_from_allocation_row(raw, row_index=index, field_name="batch_id")
        allocation_key = (source_warehouse_id, batch_id, item_id)
        if allocation_key in seen_keys:
            raise OperationValidationError(
                {
                    f"allocations[{index}]":
                        "Duplicate allocation rows for the same item, warehouse, and batch are not allowed."
                }
            )
        seen_keys.add(allocation_key)

        source_type = str(raw.get("source_type") or "ON_HAND").strip().upper() or "ON_HAND"
        if source_type not in _VALID_ALLOCATION_SOURCE_TYPES:
            raise OperationValidationError(
                {
                    f"allocations[{index}].source_type":
                        f"Invalid source_type {source_type!r} for allocation row {index}."
                }
            )

        source_record_id: int | None = None
        if raw.get("source_record_id") not in (None, ""):
            source_record_id = _required_positive_int_from_allocation_row(
                raw,
                row_index=index,
                field_name="source_record_id",
            )

        uom_code_raw = raw.get("uom_code")
        uom_code = str(uom_code_raw).strip() if uom_code_raw not in (None, "") else None
        if uom_code is not None and len(uom_code) > 25:
            raise OperationValidationError(
                {f"allocations[{index}].uom_code": "uom_code must not exceed 25 characters."}
            )

        validated_rows.append(
            {
                "item_id": item_id,
                "source_warehouse_id": source_warehouse_id,
                "batch_id": batch_id,
                "quantity": qty_decimal,
                "source_type": source_type,
                "source_record_id": source_record_id,
                "uom_code": uom_code,
            }
        )

    return validated_rows


def _allowed_fulfillment_queue_codes(normalized_roles: set[str]) -> list[str]:
    allowed_queue_codes = [QUEUE_CODE_FULFILLMENT]
    if ROLE_LOGISTICS_MANAGER in normalized_roles:
        allowed_queue_codes.append(QUEUE_CODE_OVERRIDE)
    return allowed_queue_codes


REQUEST_FILTERS = {
    "draft": {REQUEST_STATUS_DRAFT},
    "awaiting": {REQUEST_STATUS_SUBMITTED, REQUEST_STATUS_UNDER_ELIGIBILITY_REVIEW},
    "submitted": {REQUEST_STATUS_APPROVED_FOR_FULFILLMENT, REQUEST_STATUS_PARTIALLY_FULFILLED},
    "processing": {REQUEST_STATUS_UNDER_ELIGIBILITY_REVIEW, REQUEST_STATUS_APPROVED_FOR_FULFILLMENT, REQUEST_STATUS_PARTIALLY_FULFILLED},
    "completed": {REQUEST_STATUS_FULFILLED},
    "dispatched": {REQUEST_STATUS_PARTIALLY_FULFILLED, REQUEST_STATUS_FULFILLED},
}

ELIGIBILITY_VISIBLE_REQUEST_STATUSES = frozenset(
    {
        REQUEST_STATUS_UNDER_ELIGIBILITY_REVIEW,
        REQUEST_STATUS_APPROVED_FOR_FULFILLMENT,
        REQUEST_STATUS_PARTIALLY_FULFILLED,
        REQUEST_STATUS_FULFILLED,
        REQUEST_STATUS_REJECTED,
        REQUEST_STATUS_INELIGIBLE,
    }
)

FULFILLMENT_VISIBLE_REQUEST_STATUSES = frozenset(
    {
        REQUEST_STATUS_APPROVED_FOR_FULFILLMENT,
        REQUEST_STATUS_PARTIALLY_FULFILLED,
        REQUEST_STATUS_FULFILLED,
    }
)

# Statuses that indicate an active workflow beyond initial submission.
# Used to prevent legacy re-derivation from downgrading these to CANCELLED.
_ACTIVE_REQUEST_STATUSES = frozenset(
    {
        REQUEST_STATUS_APPROVED_FOR_FULFILLMENT,
        REQUEST_STATUS_PARTIALLY_FULFILLED,
        REQUEST_STATUS_FULFILLED,
    }
)

_FULFILLMENT_COMPLETION_REQUEST_STATUSES = frozenset(
    {
        REQUEST_STATUS_PARTIALLY_FULFILLED,
        REQUEST_STATUS_FULFILLED,
    }
)


def _preserve_request_status(current_status: str, next_status: str) -> str:
    if next_status == REQUEST_STATUS_CANCELLED and current_status in _ACTIVE_REQUEST_STATUSES:
        return current_status
    if (
        next_status == REQUEST_STATUS_APPROVED_FOR_FULFILLMENT
        and current_status in _FULFILLMENT_COMPLETION_REQUEST_STATUSES
    ):
        return current_status
    return next_status


def _lookup_reference_options(table_key: str) -> list[dict[str, Any]]:
    items, _warnings = get_lookup(table_key, active_only=True)
    options: list[dict[str, Any]] = []
    for item in items:
        label = str(item.get("label") or "").strip()
        try:
            value = int(item.get("value"))
        except (TypeError, ValueError):
            continue
        if value <= 0 or not label:
            continue
        options.append({"value": value, "label": label})
    return options


def get_request_reference_data(*, tenant_context: TenantContext, permissions: Iterable[str]) -> dict[str, Any]:
    agencies: list[dict[str, Any]] = []
    for option in _lookup_reference_options("agencies"):
        try:
            decision = operations_policy.validate_relief_request_agency_selection(
                agency_id=int(option["value"]),
                tenant_context=tenant_context,
            )
            operations_policy.enforce_relief_request_origin_mode_permission(
                decision=decision,
                permissions=permissions,
            )
        except OperationValidationError:
            continue
        agencies.append(option)

    return {
        "agencies": agencies,
        "events": _lookup_reference_options("events"),
        "items": _lookup_reference_options("items"),
    }


def _request_status_from_legacy(request: ReliefRqst) -> str:
    mapping = {
        legacy_service.STATUS_DRAFT: REQUEST_STATUS_DRAFT,
        legacy_service.STATUS_AWAITING_APPROVAL: REQUEST_STATUS_UNDER_ELIGIBILITY_REVIEW,
        legacy_service.STATUS_SUBMITTED: REQUEST_STATUS_APPROVED_FOR_FULFILLMENT,
        legacy_service.STATUS_PART_FILLED: REQUEST_STATUS_PARTIALLY_FULFILLED,
        legacy_service.STATUS_FILLED: REQUEST_STATUS_FULFILLED,
        legacy_service.STATUS_CLOSED: REQUEST_STATUS_FULFILLED,
        legacy_service.STATUS_INELIGIBLE: REQUEST_STATUS_INELIGIBLE,
        legacy_service.STATUS_DENIED: REQUEST_STATUS_REJECTED,
        # Legacy status 2 is named STATUS_CANCELLED in services.py but
        # allocation_dispatch.py names it STATUS_APPROVED.  The allocation
        # commit flow (_request_header_update_values) sets requests to 2
        # while packages are being processed.  There is no cancel-request
        # endpoint, so status 2 always means "approved / in processing".
        legacy_service.STATUS_CANCELLED: REQUEST_STATUS_APPROVED_FOR_FULFILLMENT,
    }
    return mapping.get(int(request.status_code or legacy_service.STATUS_DRAFT), REQUEST_STATUS_DRAFT)


def _package_status_from_legacy(package: ReliefPkg) -> str:
    legacy_status = legacy_service._current_package_status(package)
    mapping = {
        legacy_service.PKG_STATUS_DRAFT: PACKAGE_STATUS_DRAFT,
        legacy_service.PKG_STATUS_PENDING: PACKAGE_STATUS_COMMITTED,
        legacy_service.PKG_STATUS_DISPATCHED: PACKAGE_STATUS_DISPATCHED,
        legacy_service.PKG_STATUS_COMPLETED: PACKAGE_STATUS_RECEIVED,
        "V": PACKAGE_STATUS_COMMITTED,
    }
    return mapping.get(legacy_status, PACKAGE_STATUS_DRAFT)


def _dispatch_status_from_package_status(package_status: str | None) -> str:
    if package_status == PACKAGE_STATUS_DISPATCHED:
        return DISPATCH_STATUS_IN_TRANSIT
    if package_status == PACKAGE_STATUS_RECEIVED:
        return DISPATCH_STATUS_RECEIVED
    return DISPATCH_STATUS_READY


def _ops_request_from_legacy(request: ReliefRqst, *, actor_id: str) -> OperationsReliefRequest:
    agency_scope = operations_policy.get_agency_scope(int(request.agency_id))
    beneficiary_tenant_id = agency_scope.tenant_id if agency_scope is not None else None
    record, created = OperationsReliefRequest.objects.get_or_create(
        relief_request_id=int(request.reliefrqst_id),
        defaults={
            "request_no": request.tracking_no,
            "requesting_tenant_id": int(beneficiary_tenant_id or 0),
            "requesting_agency_id": int(request.agency_id),
            "beneficiary_tenant_id": beneficiary_tenant_id,
            "beneficiary_agency_id": int(request.agency_id),
            "origin_mode": ORIGIN_MODE_SELF,
            "source_needs_list_id": None,
            "event_id": request.eligible_event_id,
            "request_date": request.request_date,
            "urgency_code": request.urgency_ind,
            "notes_text": request.rqst_notes_text,
            "status_code": _request_status_from_legacy(request),
            "submitted_by_id": request.create_by_id,
            "submitted_at": request.create_dtime,
            "reviewed_by_id": request.review_by_id,
            "reviewed_at": request.review_dtime,
            "create_by_id": actor_id,
            "update_by_id": actor_id,
        },
    )
    if created:
        record_status_transition(
            entity_type=ENTITY_REQUEST,
            entity_id=int(request.reliefrqst_id),
            from_status=None,
            to_status=record.status_code,
            actor_id=actor_id,
        )
    return record


def _request_access_probe_from_legacy(request: ReliefRqst) -> OperationsReliefRequest:
    existing = OperationsReliefRequest.objects.filter(
        relief_request_id=int(request.reliefrqst_id)
    ).only("requesting_tenant_id", "beneficiary_tenant_id").first()
    if existing is not None:
        requesting_tenant_id = existing.requesting_tenant_id
        beneficiary_tenant_id = existing.beneficiary_tenant_id
    else:
        agency_scope = operations_policy.get_agency_scope(int(request.agency_id))
        beneficiary_tenant_id = agency_scope.tenant_id if agency_scope is not None else None
        requesting_tenant_id = beneficiary_tenant_id
    return OperationsReliefRequest(
        relief_request_id=int(request.reliefrqst_id),
        requesting_tenant_id=int(requesting_tenant_id or beneficiary_tenant_id or 0),
        beneficiary_tenant_id=beneficiary_tenant_id,
        status_code=_request_status_from_legacy(request),
    )


def _assign_if_changed(record: Any, field_name: str, value: Any, changed_fields: list[str]) -> None:
    if getattr(record, field_name) != value:
        setattr(record, field_name, value)
        changed_fields.append(field_name)


def _driver_license_last4(value: Any) -> str | None:
    if value in (None, ""):
        return None
    trimmed = str(value).strip()
    return trimmed[-4:] if trimmed else None


def _collector_id_last4(value: Any) -> str | None:
    if value in (None, ""):
        return None
    trimmed = str(value).strip()
    return trimmed[-4:] if trimmed else None


def _parse_transport_datetime(value: Any, field_name: str) -> datetime | None:
    if value in (None, ""):
        return None
    parsed = parse_datetime(str(value))
    if parsed is None:
        raise OperationValidationError({field_name: f"{field_name} must be a valid ISO 8601 datetime."})
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _parse_int_or_raise(value: Any, field_name: str) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise OperationValidationError({field_name: f"{field_name} must be a valid integer value."}) from exc


def _sync_operations_request(
    request: ReliefRqst,
    *,
    actor_id: str,
    decision: operations_policy.ReliefRequestWriteDecision | None = None,
    status_code: str | None = None,
    source_needs_list_id: int | None | object = _UNSET,
    requesting_agency_id: int | None = None,
) -> OperationsReliefRequest:
    record = _ops_request_from_legacy(request, actor_id=actor_id)
    original_status = record.status_code
    resolved_status_code: str | None = None
    changed_fields: list[str] = []
    if decision is not None:
        _assign_if_changed(record, "requesting_tenant_id", int(decision.requesting_tenant_id), changed_fields)
        _assign_if_changed(record, "beneficiary_tenant_id", int(decision.beneficiary_tenant_id), changed_fields)
        _assign_if_changed(record, "origin_mode", decision.origin_mode, changed_fields)
        _assign_if_changed(
            record,
            "beneficiary_agency_id",
            int(decision.beneficiary_agency_id or request.agency_id),
            changed_fields,
        )
        resolved_requesting_agency_id = None
        if requesting_agency_id is not None:
            resolved_requesting_agency_id = int(requesting_agency_id)
        elif decision.requesting_agency_id is not None:
            resolved_requesting_agency_id = int(decision.requesting_agency_id)
        elif decision.origin_mode == ORIGIN_MODE_SELF:
            resolved_requesting_agency_id = int(request.agency_id)
        if resolved_requesting_agency_id is not None:
            _assign_if_changed(record, "requesting_agency_id", resolved_requesting_agency_id, changed_fields)
    _assign_if_changed(record, "request_no", request.tracking_no, changed_fields)
    _assign_if_changed(record, "event_id", request.eligible_event_id, changed_fields)
    _assign_if_changed(record, "request_date", request.request_date, changed_fields)
    _assign_if_changed(record, "urgency_code", request.urgency_ind, changed_fields)
    _assign_if_changed(record, "notes_text", request.rqst_notes_text, changed_fields)
    if source_needs_list_id is not _UNSET:
        _assign_if_changed(record, "source_needs_list_id", source_needs_list_id, changed_fields)
    _assign_if_changed(record, "reviewed_by_id", request.review_by_id, changed_fields)
    _assign_if_changed(record, "reviewed_at", request.review_dtime, changed_fields)
    if status_code:
        resolved_status_code = _preserve_request_status(record.status_code, status_code)
        _assign_if_changed(record, "status_code", resolved_status_code, changed_fields)
    else:
        # Issue #14: Sync status from legacy record on read paths when no explicit
        # status override is provided.
        resolved_status_code = _preserve_request_status(
            record.status_code,
            _request_status_from_legacy(request),
        )
        _assign_if_changed(record, "status_code", resolved_status_code, changed_fields)
    if changed_fields:
        record.update_by_id = actor_id
        record.update_dtime = timezone.now()
        record.version_nbr = int(record.version_nbr or 0) + 1
        changed_fields.extend(["update_by_id", "update_dtime", "version_nbr"])
        record.save(update_fields=changed_fields)
    if status_code and resolved_status_code and resolved_status_code != original_status:
        record_status_transition(
            entity_type=ENTITY_REQUEST,
            entity_id=int(request.reliefrqst_id),
            from_status=original_status,
            to_status=resolved_status_code,
            actor_id=actor_id,
        )
    return record


def _sync_operations_package(
    package: ReliefPkg,
    *,
    request_record: OperationsReliefRequest,
    actor_id: str,
    status_code: str | None = None,
    override_status_code: str | None | object = _UNSET,
    source_warehouse_id: int | None | object = _UNSET,
    status_transition_reason: str | None = None,
) -> OperationsPackage:
    record, created = OperationsPackage.objects.get_or_create(
        package_id=int(package.reliefpkg_id),
        defaults={
            "package_no": package.tracking_no,
            "relief_request_id": int(package.reliefrqst_id),
            "source_warehouse_id": None if source_warehouse_id is _UNSET else source_warehouse_id,
            "destination_tenant_id": request_record.beneficiary_tenant_id,
            "destination_agency_id": request_record.beneficiary_agency_id,
            "status_code": status_code or _package_status_from_legacy(package),
            "create_by_id": actor_id,
            "update_by_id": actor_id,
        },
    )
    original_status = record.status_code
    changed_fields: list[str] = []
    _assign_if_changed(record, "package_no", package.tracking_no, changed_fields)
    _assign_if_changed(record, "relief_request_id", int(package.reliefrqst_id), changed_fields)
    _assign_if_changed(record, "destination_tenant_id", request_record.beneficiary_tenant_id, changed_fields)
    _assign_if_changed(record, "destination_agency_id", request_record.beneficiary_agency_id, changed_fields)
    if source_warehouse_id is not _UNSET:
        _assign_if_changed(
            record,
            "source_warehouse_id",
            None if source_warehouse_id is None else int(source_warehouse_id),
            changed_fields,
        )
    if status_code:
        _assign_if_changed(record, "status_code", status_code, changed_fields)
    else:
        # Issue #14: Sync status from legacy record on read paths.
        legacy_derived_status = _package_status_from_legacy(package)
        if record.status_code in _OPERATIONS_NATIVE_PACKAGE_STATUSES and legacy_derived_status in {
            PACKAGE_STATUS_DRAFT,
            PACKAGE_STATUS_COMMITTED,
        }:
            legacy_derived_status = record.status_code
        _assign_if_changed(record, "status_code", legacy_derived_status, changed_fields)
    if override_status_code is not _UNSET:
        _assign_if_changed(record, "override_status_code", override_status_code, changed_fields)
    if record.status_code in {PACKAGE_STATUS_COMMITTED, PACKAGE_STATUS_CONSOLIDATING} and record.committed_at is None:
        record.committed_at = getattr(package, "committed_dtime", None) or timezone.now()
        changed_fields.append("committed_at")
    if record.status_code == PACKAGE_STATUS_DISPATCHED and record.dispatched_at is None:
        record.dispatched_at = getattr(package, "dispatch_dtime", None) or timezone.now()
        changed_fields.append("dispatched_at")
    if record.status_code == PACKAGE_STATUS_RECEIVED and record.received_at is None:
        record.received_at = getattr(package, "received_dtime", None) or timezone.now()
        changed_fields.append("received_at")
    if changed_fields:
        record.update_by_id = actor_id
        record.update_dtime = timezone.now()
        record.version_nbr = int(record.version_nbr or 0) + 1
        changed_fields.extend(["update_by_id", "update_dtime", "version_nbr"])
        record.save(update_fields=changed_fields)
    if created:
        record_status_transition(
            entity_type=ENTITY_PACKAGE,
            entity_id=int(package.reliefpkg_id),
            from_status=None,
            to_status=record.status_code,
            actor_id=actor_id,
            reason_text=status_transition_reason,
        )
    elif status_code and status_code != original_status:
        record_status_transition(
            entity_type=ENTITY_PACKAGE,
            entity_id=int(package.reliefpkg_id),
            from_status=original_status,
            to_status=status_code,
            actor_id=actor_id,
            reason_text=status_transition_reason,
        )
    return record


def _ensure_dispatch_record(
    *,
    package: ReliefPkg,
    package_record: OperationsPackage,
    actor_id: str,
) -> OperationsDispatch:
    fulfillment_mode = getattr(package_record, "fulfillment_mode", FULFILLMENT_MODE_DIRECT)
    effective_source_warehouse_id = getattr(
        package_record,
        "effective_dispatch_source_warehouse_id",
        getattr(package_record, "source_warehouse_id", None),
    )
    if fulfillment_mode == FULFILLMENT_MODE_PICKUP_AT_STAGING:
        raise OperationValidationError(
            {"dispatch": "Pickup-at-staging packages do not create a final dispatch record."}
        )
    if (
        fulfillment_mode == FULFILLMENT_MODE_DELIVER_FROM_STAGING
        and package_record.status_code not in {
            PACKAGE_STATUS_READY_FOR_DISPATCH,
            PACKAGE_STATUS_DISPATCHED,
            PACKAGE_STATUS_RECEIVED,
        }
    ):
        raise OperationValidationError(
            {"dispatch": "Final dispatch is not available until all consolidation legs are received."}
        )
    dispatch_status = _dispatch_status_from_package_status(package_record.status_code)
    dispatch_at = package_record.dispatched_at
    dispatch, created = OperationsDispatch.objects.get_or_create(
        package_id=int(package.reliefpkg_id),
        defaults={
            "dispatch_no": legacy_service._tracking_no("DP", int(package.reliefpkg_id)),
            "status_code": dispatch_status,
            "dispatch_at": dispatch_at,
            "source_warehouse_id": effective_source_warehouse_id,
            "destination_tenant_id": package_record.destination_tenant_id,
            "destination_agency_id": package_record.destination_agency_id,
            "create_by_id": actor_id,
            "update_by_id": actor_id,
        },
    )
    if created:
        record_status_transition(
            entity_type=ENTITY_DISPATCH,
            entity_id=int(dispatch.dispatch_id),
            from_status=None,
            to_status=dispatch.status_code,
            actor_id=actor_id,
        )
    else:
        changed_fields: list[str] = []
        _assign_if_changed(dispatch, "status_code", dispatch_status, changed_fields)
        _assign_if_changed(dispatch, "dispatch_at", dispatch_at, changed_fields)
        _assign_if_changed(
            dispatch,
            "source_warehouse_id",
            effective_source_warehouse_id,
            changed_fields,
        )
        _assign_if_changed(dispatch, "destination_tenant_id", package_record.destination_tenant_id, changed_fields)
        _assign_if_changed(dispatch, "destination_agency_id", package_record.destination_agency_id, changed_fields)
        if changed_fields:
            dispatch.update_by_id = actor_id
            dispatch.update_dtime = timezone.now()
            dispatch.version_nbr = int(dispatch.version_nbr or 0) + 1
            changed_fields.extend(["update_by_id", "update_dtime", "version_nbr"])
            dispatch.save(update_fields=changed_fields)
    return dispatch


def _require_roles(actor_roles: Iterable[str] | None, allowed_roles: Iterable[str], *, message: str) -> tuple[str, ...]:
    normalized_roles = normalize_role_codes(actor_roles)
    if ROLE_SYSTEM_ADMINISTRATOR in normalized_roles:
        return normalized_roles
    allowed = set(allowed_roles)
    if not any(role in allowed for role in normalized_roles):
        raise OperationValidationError({"roles": message})
    return normalized_roles


def _permission_set(permissions: Iterable[str] | None) -> set[str]:
    return {
        str(permission or "").strip().lower()
        for permission in permissions or ()
        if str(permission or "").strip()
    }


def _require_permission(
    permissions: Iterable[str] | None,
    required_permission: str,
    *,
    field_name: str,
    message: str,
) -> None:
    if required_permission.lower() in _permission_set(permissions):
        return
    raise OperationValidationError(
        {
            field_name: {
                "code": "permission_denied",
                "message": message,
                "required_permission": required_permission,
            }
        }
    )


def _acquire_package_lock(package_id: int, *, actor_id: str, actor_roles: Iterable[str]) -> OperationsPackageLock:
    normalized_roles = _require_roles(
        actor_roles,
        FULFILLMENT_ROLE_CODES,
        message="Only fulfillment roles may acquire package locks.",
    )
    owner_role = next(
        (role for role in normalized_roles if role in set(FULFILLMENT_ROLE_CODES)),
        ROLE_SYSTEM_ADMINISTRATOR,
    )
    now = timezone.now()
    expires_at = now + timedelta(minutes=30)
    with transaction.atomic():
        existing = (
            OperationsPackageLock.objects.select_for_update()
            .filter(package_id=int(package_id))
            .first()
        )
        if existing and existing.lock_owner_user_id != actor_id and _is_package_lock_active(existing, now=now):
            raise OperationValidationError(_package_lock_conflict_errors(existing))
        if existing is None:
            try:
                with transaction.atomic():
                    lock = OperationsPackageLock.objects.create(
                        package_id=int(package_id),
                        lock_owner_user_id=actor_id,
                        lock_owner_role_code=owner_role,
                        lock_started_at=now,
                        lock_expires_at=expires_at,
                        lock_status="ACTIVE",
                    )
                created = True
            except IntegrityError:
                # Another actor won the race; re-fetch and check ownership.
                existing = (
                    OperationsPackageLock.objects.select_for_update()
                    .filter(package_id=int(package_id))
                    .first()
                )
                if existing and existing.lock_owner_user_id != actor_id and _is_package_lock_active(existing, now=now):
                    raise OperationValidationError(_package_lock_conflict_errors(existing)) from None
                if existing is None:
                    raise  # Unexpected state; propagate original error.
                lock = existing
                lock.lock_owner_user_id = actor_id
                lock.lock_owner_role_code = owner_role
                lock.lock_started_at = now
                lock.lock_expires_at = expires_at
                lock.lock_status = "ACTIVE"
                lock.save(
                    update_fields=[
                        "lock_owner_user_id",
                        "lock_owner_role_code",
                        "lock_started_at",
                        "lock_expires_at",
                        "lock_status",
                    ]
                )
                created = False
        else:
            lock = existing
            lock.lock_owner_user_id = actor_id
            lock.lock_owner_role_code = owner_role
            lock.lock_started_at = now
            lock.lock_expires_at = expires_at
            lock.lock_status = "ACTIVE"
            lock.save(
                update_fields=[
                    "lock_owner_user_id",
                    "lock_owner_role_code",
                    "lock_started_at",
                    "lock_expires_at",
                    "lock_status",
                ]
            )
            created = False
    if created:
        create_role_notifications(
            event_code=EVENT_PACKAGE_LOCKED,
            entity_type=ENTITY_PACKAGE,
            entity_id=int(package_id),
            message_text="Package lock acquired for fulfillment.",
            role_codes=FULFILLMENT_ROLE_CODES,
            queue_code=QUEUE_CODE_FULFILLMENT,
        )
    return lock


def _is_package_lock_active(lock: OperationsPackageLock | None, *, now: datetime | None = None) -> bool:
    if lock is None or lock.lock_status != "ACTIVE":
        return False
    current_time = now or timezone.now()
    return lock.lock_expires_at is None or lock.lock_expires_at > current_time


def _package_lock_conflict_errors(lock: OperationsPackageLock) -> dict[str, Any]:
    return {
        "lock": "Package is locked by another fulfillment actor.",
        "lock_owner_user_id": lock.lock_owner_user_id,
        "lock_owner_role_code": lock.lock_owner_role_code,
        "lock_expires_at": legacy_service._as_iso(lock.lock_expires_at),
    }


def _package_lock_release_response(
    *,
    package_record: OperationsPackage | None,
    lock: OperationsPackageLock | None,
    released: bool,
    message: str,
    released_by_user_id: str | None = None,
    released_at: datetime | None = None,
) -> dict[str, Any]:
    return {
        "released": released,
        "message": message,
        "package_id": int(package_record.package_id) if package_record is not None else None,
        "package_no": package_record.package_no if package_record is not None else None,
        "previous_lock_owner_user_id": lock.lock_owner_user_id if lock is not None else None,
        "previous_lock_owner_role_code": lock.lock_owner_role_code if lock is not None else None,
        "released_by_user_id": released_by_user_id,
        "released_at": legacy_service._as_iso(released_at),
        "lock_status": lock.lock_status if lock is not None else None,
        "lock_expires_at": legacy_service._as_iso(lock.lock_expires_at) if lock is not None else None,
    }


def _persist_released_package_lock(lock: OperationsPackageLock, *, released_at: datetime) -> OperationsPackageLock:
    lock.lock_status = "RELEASED"
    lock.lock_expires_at = released_at
    lock.save(update_fields=["lock_status", "lock_expires_at"])
    return lock


def _release_package_lock_for_record(
    package_record: OperationsPackage,
    *,
    request_record: OperationsReliefRequest,
    actor_id: str,
    actor_roles: Iterable[str] | None,
    force: bool = False,
) -> dict[str, Any]:
    normalized_roles = normalize_role_codes(actor_roles)
    now = timezone.now()
    with transaction.atomic():
        lock = (
            OperationsPackageLock.objects.select_for_update()
            .filter(package_id=int(package_record.package_id))
            .first()
        )
        if not _is_package_lock_active(lock, now=now):
            return _package_lock_release_response(
                package_record=package_record,
                lock=lock,
                released=False,
                message="No active package lock found for this package.",
            )

        is_lock_owner = lock.lock_owner_user_id == actor_id
        can_force_release = ROLE_SYSTEM_ADMINISTRATOR in normalized_roles or ROLE_LOGISTICS_MANAGER in normalized_roles
        if not is_lock_owner:
            if not can_force_release:
                raise OperationValidationError(
                    {
                        "lock": (
                            "Only the current lock owner, a Logistics Manager, "
                            "or a System Administrator may release this package lock."
                        )
                    }
                )
            if not force:
                raise OperationValidationError(
                    {"force": "force=true is required to release another actor's package lock."}
                )

        previous_lock_owner_user_id = lock.lock_owner_user_id
        _persist_released_package_lock(lock, released_at=now)
        notification_tenant_id = _resolve_request_level_fulfillment_tenant_id()

        create_user_notification(
            event_code=EVENT_PACKAGE_UNLOCKED,
            entity_type=ENTITY_PACKAGE,
            entity_id=int(package_record.package_id),
            recipient_user_id=actor_id,
            tenant_id=notification_tenant_id,
            queue_code=QUEUE_CODE_FULFILLMENT,
            message_text=f"Package lock on {package_record.package_no} was released by {actor_id}.",
        )
        if previous_lock_owner_user_id != actor_id:
            create_user_notification(
                event_code=EVENT_PACKAGE_UNLOCKED,
                entity_type=ENTITY_PACKAGE,
                entity_id=int(package_record.package_id),
                recipient_user_id=previous_lock_owner_user_id,
                tenant_id=notification_tenant_id,
                queue_code=QUEUE_CODE_FULFILLMENT,
                message_text=(
                    f"Package lock on {package_record.package_no} was force-released by {actor_id}."
                ),
            )

    return _package_lock_release_response(
        package_record=package_record,
        lock=lock,
        released=True,
        message="Package lock released.",
        released_by_user_id=actor_id,
        released_at=now,
    )


def _ensure_request_access(
    request_record: OperationsReliefRequest,
    *,
    actor_id: str,
    actor_roles: Iterable[str],
    tenant_context: TenantContext,
    write: bool = False,
) -> None:
    relevant_tenants = [request_record.requesting_tenant_id, request_record.beneficiary_tenant_id]
    for tenant_id in relevant_tenants:
        if tenant_id and can_access_tenant(tenant_context, int(tenant_id), write=write):
            return
    if actor_queue_queryset(actor_id=actor_id, actor_roles=actor_roles, tenant_context=tenant_context).filter(
        entity_type=ENTITY_REQUEST,
        entity_id=int(request_record.relief_request_id),
    ).exists():
        return
    raise OperationValidationError({"scope": "Request is outside the active tenant or workflow assignment scope."})


def _can_read_eligibility_request(
    request_record: OperationsReliefRequest,
    *,
    actor_id: str,
    actor_roles: Iterable[str],
    tenant_context: TenantContext,
) -> bool:
    normalized_roles = normalize_role_codes(actor_roles)
    if ROLE_SYSTEM_ADMINISTRATOR in normalized_roles:
        return True
    if request_record.status_code not in ELIGIBILITY_VISIBLE_REQUEST_STATUSES:
        return False

    relevant_tenants = [request_record.requesting_tenant_id, request_record.beneficiary_tenant_id]
    for tenant_id in relevant_tenants:
        if tenant_id and can_access_tenant(tenant_context, int(tenant_id), write=False):
            return True

    if not any(role in set(ELIGIBILITY_ROLE_CODES) for role in normalized_roles):
        return False

    request_pk = int(request_record.relief_request_id)
    active_tenant_id = tenant_context.active_tenant_id
    assignment_filters = OperationsQueueAssignment.objects.filter(
        Q(assigned_user_id=actor_id) | Q(assigned_role_code__in=normalized_roles),
        queue_code=QUEUE_CODE_ELIGIBILITY,
        entity_type=ENTITY_REQUEST,
        entity_id=request_pk,
        assignment_status__in=["OPEN", "COMPLETED"],
    )
    if active_tenant_id is not None:
        assignment_filters = assignment_filters.filter(
            Q(assigned_tenant_id=active_tenant_id) | Q(assigned_tenant_id__isnull=True)
        )
    return assignment_filters.exists()


def _ensure_fulfillment_request_access(
    request_record: OperationsReliefRequest,
    *,
    actor_id: str,
    actor_roles: Iterable[str],
    tenant_context: TenantContext,
    write: bool = False,
) -> None:
    normalized_roles = normalize_role_codes(actor_roles)
    if ROLE_SYSTEM_ADMINISTRATOR in normalized_roles:
        return
    if not any(role in set(FULFILLMENT_ROLE_CODES) for role in normalized_roles):
        raise OperationValidationError({"scope": "Request is outside the active tenant or workflow assignment scope."})
    if request_record.status_code not in FULFILLMENT_VISIBLE_REQUEST_STATUSES:
        raise OperationValidationError({"scope": "Request is outside the active tenant or workflow assignment scope."})

    try:
        _ensure_request_access(
            request_record,
            actor_id=actor_id,
            actor_roles=actor_roles,
            tenant_context=tenant_context,
            write=write,
        )
        return
    except OperationValidationError:
        pass

    active_tenant_id = tenant_context.active_tenant_id
    if active_tenant_id is None:
        raise OperationValidationError({"scope": "Request is outside the active tenant or workflow assignment scope."})

    assignment_statuses = ["OPEN"] if write else ["OPEN", "COMPLETED"]
    allowed_queue_codes = _allowed_fulfillment_queue_codes(normalized_roles)
    has_assignment = OperationsQueueAssignment.objects.filter(
        Q(assigned_user_id=actor_id) | Q(assigned_role_code__in=normalized_roles),
        queue_code__in=allowed_queue_codes,
        entity_type=ENTITY_REQUEST,
        entity_id=int(request_record.relief_request_id),
        assignment_status__in=assignment_statuses,
    ).filter(
        Q(assigned_tenant_id=active_tenant_id) | Q(assigned_tenant_id__isnull=True)
    ).exists()
    if not has_assignment:
        raise OperationValidationError({"scope": "Request is outside the active tenant or workflow assignment scope."})


def _ensure_package_access(
    package_record: OperationsPackage,
    *,
    actor_id: str,
    actor_roles: Iterable[str],
    tenant_context: TenantContext,
    write: bool = False,
) -> None:
    try:
        request_record = OperationsReliefRequest.objects.get(relief_request_id=int(package_record.relief_request_id))
    except OperationsReliefRequest.DoesNotExist:
        raise OperationValidationError({"scope": "Associated relief request record not found for this package."}) from None
    _ensure_request_access(request_record, actor_id=actor_id, actor_roles=actor_roles, tenant_context=tenant_context, write=write)


def _ensure_actor_assigned_to_queue(
    *,
    queue_code: str,
    entity_type: str,
    entity_id: int,
    actor_id: str,
    actor_roles: Iterable[str],
    tenant_context: TenantContext,
    error_message: str,
) -> None:
    if actor_queue_queryset(
        actor_id=actor_id,
        actor_roles=actor_roles,
        tenant_context=tenant_context,
    ).filter(
        queue_code=queue_code,
        entity_type=entity_type,
        entity_id=int(entity_id),
    ).exists():
        return

    # Receipt confirmation is assigned to the original submitter but scoped to
    # the beneficiary tenant. In subordinate/on-behalf flows the assigned user
    # may not be operating in that tenant, so allow the exact direct
    # user-assignment even when it falls outside the active-tenant queue view.
    if OperationsQueueAssignment.objects.filter(
        queue_code=queue_code,
        entity_type=entity_type,
        entity_id=int(entity_id),
        assignment_status="OPEN",
        assigned_user_id=actor_id,
    ).exists():
        return

    raise OperationValidationError({"authorization": error_message})


def _assign_pickup_release_queue(
    *,
    package_record: OperationsPackage,
    tenant_id: int | None,
) -> None:
    assign_roles_to_queue(
        queue_code=QUEUE_CODE_PICKUP_RELEASE,
        entity_type=ENTITY_PACKAGE,
        entity_id=int(package_record.package_id),
        role_codes=FULFILLMENT_ROLE_CODES,
        tenant_id=tenant_id,
    )


def _resolve_request_level_fulfillment_tenant_id() -> int:
    configured_tenant_id = getattr(settings, "ODPEM_TENANT_ID", None)
    tenant_id = int(configured_tenant_id) if configured_tenant_id not in (None, "") else operations_policy.resolve_odpem_fulfillment_tenant_id()
    if tenant_id is None:
        raise OperationValidationError(
            {"tenant_scope": "ODPEM fulfillment tenant could not be resolved for request-level logistics routing."}
        )
    return int(tenant_id)


def _package_lock_payload(package_id: int) -> dict[str, Any] | None:
    lock = OperationsPackageLock.objects.filter(package_id=int(package_id)).first()
    if lock is None:
        return None
    return {
        "lock_owner_user_id": lock.lock_owner_user_id,
        "lock_owner_role_code": lock.lock_owner_role_code,
        "lock_started_at": legacy_service._as_iso(lock.lock_started_at),
        "lock_expires_at": legacy_service._as_iso(lock.lock_expires_at),
        "lock_status": lock.lock_status,
    }


def _normalized_fulfillment_mode(value: object, *, default: str = FULFILLMENT_MODE_DIRECT) -> str:
    normalized = str(value or default).strip().upper() or default
    allowed = {
        FULFILLMENT_MODE_DIRECT,
        FULFILLMENT_MODE_PICKUP_AT_STAGING,
        FULFILLMENT_MODE_DELIVER_FROM_STAGING,
    }
    if normalized not in allowed:
        raise OperationValidationError(
            {
                "fulfillment_mode": (
                    "fulfillment_mode must be DIRECT, PICKUP_AT_STAGING, "
                    "or DELIVER_FROM_STAGING."
                )
            }
        )
    return normalized


def _is_staged_fulfillment_mode(value: object) -> bool:
    return _normalized_fulfillment_mode(value) in {
        FULFILLMENT_MODE_PICKUP_AT_STAGING,
        FULFILLMENT_MODE_DELIVER_FROM_STAGING,
    }


def _package_leg_summary(package_record: OperationsPackage) -> dict[str, Any]:
    legs = list(
        OperationsConsolidationLeg.objects.filter(package_id=int(package_record.package_id)).only(
            "leg_id",
            "status_code",
        )
    )
    by_status: dict[str, int] = {}
    for leg in legs:
        by_status[leg.status_code] = by_status.get(leg.status_code, 0) + 1
    received_count = by_status.get(CONSOLIDATION_LEG_STATUS_RECEIVED_AT_STAGING, 0)
    return {
        "total_legs": len(legs),
        "planned_legs": by_status.get(CONSOLIDATION_LEG_STATUS_PLANNED, 0),
        "in_transit_legs": by_status.get(CONSOLIDATION_LEG_STATUS_IN_TRANSIT, 0),
        "received_legs": received_count,
        "cancelled_legs": by_status.get(CONSOLIDATION_LEG_STATUS_CANCELLED, 0),
        "all_received": bool(legs) and received_count == len(legs),
    }


def _package_split_references(package_record: OperationsPackage) -> dict[str, Any]:
    split_from = package_record.split_from_package
    children = list(
        package_record.split_children.order_by("package_no").values("package_id", "package_no", "status_code")
    )
    return {
        "split_from_package_id": int(split_from.package_id) if split_from is not None else None,
        "split_from_package_no": split_from.package_no if split_from is not None else None,
        "split_children": [
            {
                "package_id": int(child["package_id"]),
                "package_no": child["package_no"],
                "status_code": child["status_code"],
            }
            for child in children
        ],
    }


def _update_package_workflow_fields(
    package_record: OperationsPackage,
    *,
    actor_id: str,
    fulfillment_mode: str | object = _UNSET,
    staging_warehouse_id: int | None | object = _UNSET,
    recommended_staging_warehouse_id: int | None | object = _UNSET,
    staging_selection_basis: str | None | object = _UNSET,
    staging_override_reason: str | None | object = _UNSET,
    consolidation_status: str | None | object = _UNSET,
    partial_release_requested_by_id: str | None | object = _UNSET,
    partial_release_requested_at: datetime | None | object = _UNSET,
    partial_release_request_reason: str | None | object = _UNSET,
    partial_release_approved_by_id: str | None | object = _UNSET,
    partial_release_approved_at: datetime | None | object = _UNSET,
    partial_release_approval_reason: str | None | object = _UNSET,
    split_from_package_id: int | None | object = _UNSET,
    split_reason: str | None | object = _UNSET,
    split_at: datetime | None | object = _UNSET,
) -> OperationsPackage:
    changed_fields: list[str] = []

    if fulfillment_mode is not _UNSET:
        _assign_if_changed(package_record, "fulfillment_mode", fulfillment_mode, changed_fields)
    if staging_warehouse_id is not _UNSET:
        _assign_if_changed(package_record, "staging_warehouse_id", staging_warehouse_id, changed_fields)
    if recommended_staging_warehouse_id is not _UNSET:
        _assign_if_changed(
            package_record,
            "recommended_staging_warehouse_id",
            recommended_staging_warehouse_id,
            changed_fields,
        )
    if staging_selection_basis is not _UNSET:
        _assign_if_changed(
            package_record,
            "staging_selection_basis",
            staging_selection_basis,
            changed_fields,
        )
    if staging_override_reason is not _UNSET:
        _assign_if_changed(package_record, "staging_override_reason", staging_override_reason, changed_fields)
    if consolidation_status is not _UNSET:
        _assign_if_changed(package_record, "consolidation_status", consolidation_status, changed_fields)
    if partial_release_requested_by_id is not _UNSET:
        _assign_if_changed(
            package_record,
            "partial_release_requested_by_id",
            partial_release_requested_by_id,
            changed_fields,
        )
    if partial_release_requested_at is not _UNSET:
        _assign_if_changed(
            package_record,
            "partial_release_requested_at",
            partial_release_requested_at,
            changed_fields,
        )
    if partial_release_request_reason is not _UNSET:
        _assign_if_changed(
            package_record,
            "partial_release_request_reason",
            partial_release_request_reason,
            changed_fields,
        )
    if partial_release_approved_by_id is not _UNSET:
        _assign_if_changed(
            package_record,
            "partial_release_approved_by_id",
            partial_release_approved_by_id,
            changed_fields,
        )
    if partial_release_approved_at is not _UNSET:
        _assign_if_changed(
            package_record,
            "partial_release_approved_at",
            partial_release_approved_at,
            changed_fields,
        )
    if partial_release_approval_reason is not _UNSET:
        _assign_if_changed(
            package_record,
            "partial_release_approval_reason",
            partial_release_approval_reason,
            changed_fields,
        )
    if split_from_package_id is not _UNSET:
        _assign_if_changed(package_record, "split_from_package_id", split_from_package_id, changed_fields)
    if split_reason is not _UNSET:
        _assign_if_changed(package_record, "split_reason", split_reason, changed_fields)
    if split_at is not _UNSET:
        _assign_if_changed(package_record, "split_at", split_at, changed_fields)

    if changed_fields:
        package_record.update_by_id = actor_id
        package_record.update_dtime = timezone.now()
        package_record.version_nbr = int(package_record.version_nbr or 0) + 1
        changed_fields.extend(["update_by_id", "update_dtime", "version_nbr"])
        package_record.save(update_fields=changed_fields)
    return package_record


def _resolved_staging_configuration(
    *,
    reliefrqst_id: int,
    payload: Mapping[str, Any],
    existing_package_record: OperationsPackage | None,
    permissions: Iterable[str] | None,
    draft_save: bool,
) -> dict[str, Any]:
    existing_mode = (
        existing_package_record.fulfillment_mode
        if existing_package_record is not None
        else FULFILLMENT_MODE_DIRECT
    )
    fulfillment_mode = _normalized_fulfillment_mode(
        payload.get("fulfillment_mode"),
        default=existing_mode,
    )
    if "fulfillment_mode" in payload:
        _require_permission(
            permissions,
            PERM_OPERATIONS_FULFILLMENT_MODE_SET,
            field_name="fulfillment_mode",
            message="Setting the fulfillment mode requires operations.fulfillment_mode.set.",
        )
    existing_staging_id = (
        existing_package_record.staging_warehouse_id if existing_package_record is not None else None
    )
    requested_staging_id = _optional_positive_int_payload_value(payload, "staging_warehouse_id")
    staging_override_reason = str(
        payload.get("staging_override_reason")
        or (existing_package_record.staging_override_reason if existing_package_record is not None else "")
        or ""
    ).strip() or None
    staging_warehouse_id = existing_staging_id
    if requested_staging_id is not _UNSET:
        staging_warehouse_id = requested_staging_id
    staging_selection_basis = (
        existing_package_record.staging_selection_basis
        if existing_package_record is not None
        else None
    )

    if _is_staged_fulfillment_mode(fulfillment_mode):
        if staging_warehouse_id in (None, ""):
            if draft_save:
                staging_selection_basis = None
            else:
                raise OperationValidationError(
                    {
                        "staging_warehouse_id": (
                            "A staging warehouse is required before staged fulfillment can be committed."
                        )
                    }
                )
        if staging_warehouse_id not in (None, ""):
            staging_hub = get_staging_hub_details(int(staging_warehouse_id))
            if staging_hub is None:
                raise OperationValidationError(
                    {
                        "staging_warehouse_id": (
                            "Selected staging warehouse must be an active ODPEM-owned SUB-HUB."
                        )
                    }
                )
    else:
        staging_warehouse_id = None
        staging_selection_basis = None
        staging_override_reason = None

    if _is_staged_fulfillment_mode(fulfillment_mode) and not draft_save:
        # The staged commit path no longer auto-selects a hub. If the user has
        # not chosen one yet, fail fast before legacy save/commit work starts.
        if staging_warehouse_id in (None, ""):
            raise OperationValidationError(
                {"staging_warehouse_id": "A staging warehouse is required before staged fulfillment can be committed."}
            )

    return {
        "fulfillment_mode": fulfillment_mode,
        "recommended_staging_warehouse_id": None,
        "staging_warehouse_id": staging_warehouse_id,
        "staging_selection_basis": staging_selection_basis,
        "staging_override_reason": staging_override_reason,
        "recommendation": {
            "recommended_staging_warehouse_id": None,
            "staging_selection_basis": None,
        },
    }


def _request_summary_payload(request: ReliefRqst, request_record: OperationsReliefRequest) -> dict[str, Any]:
    payload = legacy_service._request_summary(request)
    payload["legacy_status_code"] = payload.pop("status_code")
    payload["status_code"] = request_record.status_code
    payload["status_label"] = STATUS_LABELS.get(request_record.status_code, request_record.status_code.title())
    payload["request_mode"] = request_record.origin_mode
    payload["origin_mode"] = request_record.origin_mode
    payload["requesting_tenant_id"] = request_record.requesting_tenant_id
    payload["requesting_agency_id"] = request_record.requesting_agency_id
    payload["beneficiary_tenant_id"] = request_record.beneficiary_tenant_id
    payload["beneficiary_agency_id"] = request_record.beneficiary_agency_id
    payload["source_needs_list_id"] = request_record.source_needs_list_id
    payload["submitted_at"] = legacy_service._as_iso(request_record.submitted_at)
    payload["submitted_by_id"] = request_record.submitted_by_id
    payload["reviewed_at"] = legacy_service._as_iso(request_record.reviewed_at)
    payload["reviewed_by_id"] = request_record.reviewed_by_id
    return payload


def _package_summary_payload(package: ReliefPkg, package_record: OperationsPackage | None = None) -> dict[str, Any]:
    package_record = package_record or OperationsPackage.objects.filter(package_id=int(package.reliefpkg_id)).first()
    payload = legacy_service._package_summary(package)
    payload["legacy_status_code"] = payload.pop("status_code")
    payload["status_code"] = package_record.status_code if package_record else _package_status_from_legacy(package)
    payload["status_label"] = STATUS_LABELS.get(payload["status_code"], payload["status_code"].title())
    payload["override_status_code"] = package_record.override_status_code if package_record else None
    payload["source_warehouse_id"] = package_record.source_warehouse_id if package_record else None
    payload["effective_dispatch_source_warehouse_id"] = (
        package_record.effective_dispatch_source_warehouse_id if package_record else None
    )
    payload["fulfillment_mode"] = package_record.fulfillment_mode if package_record else FULFILLMENT_MODE_DIRECT
    payload["staging_warehouse_id"] = package_record.staging_warehouse_id if package_record else None
    payload["recommended_staging_warehouse_id"] = (
        package_record.recommended_staging_warehouse_id if package_record else None
    )
    payload["staging_selection_basis"] = package_record.staging_selection_basis if package_record else None
    payload["staging_override_reason"] = package_record.staging_override_reason if package_record else None
    payload["consolidation_status"] = package_record.consolidation_status if package_record else None
    payload["destination_tenant_id"] = package_record.destination_tenant_id if package_record else None
    payload["destination_agency_id"] = package_record.destination_agency_id if package_record else None
    payload["lock"] = _package_lock_payload(int(package.reliefpkg_id))
    if package_record is not None:
        payload["leg_summary"] = _package_leg_summary(package_record)
        payload["split"] = _package_split_references(package_record)
    else:
        payload["leg_summary"] = None
        payload["split"] = None
    dispatch = OperationsDispatch.objects.filter(package_id=int(package.reliefpkg_id)).first()
    if dispatch is not None:
        payload["dispatch_status_code"] = dispatch.status_code
        payload["dispatch_status_label"] = STATUS_LABELS.get(dispatch.status_code, dispatch.status_code.title())
    return payload


def _operations_allocation_payload(
    package: ReliefPkg,
    package_record: OperationsPackage,
) -> dict[str, Any]:
    allocation_lines = list(
        package_record.allocation_lines.order_by(
            "item_id",
            "source_warehouse_id",
            "batch_id",
            "line_id",
        )
    )
    try:
        batch_lookup = {
            int(batch.batch_id): batch
            for batch in ItemBatch.objects.filter(
                batch_id__in=[int(line.batch_id) for line in allocation_lines]
            )
        }
    except DatabaseError:
        batch_lookup = {}
    dispatch = OperationsDispatch.objects.filter(package_id=int(package.reliefpkg_id)).first()
    waybill = None
    if dispatch is not None:
        waybill = (
            OperationsWaybill.objects.filter(dispatch_id=int(dispatch.dispatch_id))
            .order_by("-generated_at", "-waybill_id")
            .first()
        )
    total_qty = sum((legacy_service._quantize_qty(line.quantity) for line in allocation_lines), Decimal("0"))
    serialized_lines: list[dict[str, Any]] = []
    for line in allocation_lines:
        batch = batch_lookup.get(int(line.batch_id))
        serialized_lines.append(
            {
                "item_id": int(line.item_id),
                "inventory_id": int(line.source_warehouse_id),
                "batch_id": int(line.batch_id),
                "batch_no": batch.batch_no if batch is not None else None,
                "batch_date": legacy_service._as_iso(batch.batch_date if batch is not None else None),
                "expiry_date": legacy_service._as_iso(batch.expiry_date if batch is not None else None),
                "quantity": str(legacy_service._quantize_qty(line.quantity)),
                "uom_code": line.uom_code or (batch.uom_code if batch is not None else None),
                "source_type": line.source_type,
                "source_record_id": line.source_record_id,
                "override_reason_code": line.reason_text,
            }
        )
    return {
        "allocation_lines": serialized_lines,
        "reserved_stock_summary": {
            "line_count": len(serialized_lines),
            "total_qty": str(total_qty.quantize(Decimal("0.0001"))),
        },
        "waybill_no": waybill.waybill_no if waybill is not None else None,
    }


def _replace_operations_allocation_lines(
    package_record: OperationsPackage,
    allocations: Sequence[Mapping[str, Any]],
    *,
    actor_id: str,
    override_reason_code: str | None = None,
) -> None:
    OperationsAllocationLine.objects.filter(package=package_record).delete()
    if not allocations:
        return
    now = timezone.now()
    OperationsAllocationLine.objects.bulk_create(
        [
            OperationsAllocationLine(
                package=package_record,
                item_id=int(allocation["item_id"]),
                source_warehouse_id=int(allocation["source_warehouse_id"]),
                batch_id=int(allocation["batch_id"]),
                quantity=allocation["quantity"],
                source_type=str(allocation["source_type"]),
                source_record_id=allocation["source_record_id"],
                uom_code=allocation["uom_code"],
                reason_text=override_reason_code,
                create_by_id=actor_id,
                create_dtime=now,
                update_by_id=actor_id,
                update_dtime=now,
            )
            for allocation in allocations
        ]
    )


def _dispatch_payload(package: ReliefPkg, dispatch: OperationsDispatch) -> dict[str, Any]:
    transport = OperationsDispatchTransport.objects.filter(dispatch_id=int(dispatch.dispatch_id)).first()
    payload = {
        "dispatch_id": int(dispatch.dispatch_id),
        "dispatch_no": dispatch.dispatch_no,
        "status_code": dispatch.status_code,
        "status_label": STATUS_LABELS.get(dispatch.status_code, dispatch.status_code.title()),
        "dispatch_at": legacy_service._as_iso(dispatch.dispatch_at),
        "dispatched_by_id": dispatch.dispatched_by_id,
        "source_warehouse_id": dispatch.source_warehouse_id,
        "destination_tenant_id": dispatch.destination_tenant_id,
        "destination_agency_id": dispatch.destination_agency_id,
        "transport": None,
    }
    if transport is not None:
        payload["transport"] = {
            "driver_name": transport.driver_name,
            "driver_license_last4": transport.driver_license_last4,
            "vehicle_id": transport.vehicle_id,
            "vehicle_registration": transport.vehicle_registration,
            "vehicle_type": transport.vehicle_type,
            "transport_mode": transport.transport_mode or package.transport_mode,
            "departure_dtime": legacy_service._as_iso(transport.departure_dtime),
            "estimated_arrival_dtime": legacy_service._as_iso(transport.estimated_arrival_dtime),
            "transport_notes": transport.transport_notes,
            "route_override_reason": transport.route_override_reason,
        }
    return payload


def _consolidation_leg_payload(leg: OperationsConsolidationLeg) -> dict[str, Any]:
    waybill = (
        OperationsConsolidationWaybill.objects.filter(leg_id=int(leg.leg_id))
        .order_by("-generated_at", "-waybill_id")
        .first()
    )
    return {
        "leg_id": int(leg.leg_id),
        "package_id": int(leg.package_id),
        "leg_sequence": leg.leg_sequence,
        "source_warehouse_id": leg.source_warehouse_id,
        "staging_warehouse_id": leg.staging_warehouse_id,
        "status_code": leg.status_code,
        "status_label": STATUS_LABELS.get(leg.status_code, leg.status_code.title()),
        "shadow_transfer_id": leg.shadow_transfer_id,
        "driver_name": leg.driver_name,
        "driver_license_last4": leg.driver_license_last4,
        "vehicle_id": leg.vehicle_id,
        "vehicle_registration": leg.vehicle_registration,
        "vehicle_type": leg.vehicle_type,
        "transport_mode": leg.transport_mode,
        "transport_notes": leg.transport_notes,
        "dispatched_by_id": leg.dispatched_by_id,
        "dispatched_at": legacy_service._as_iso(leg.dispatched_at),
        "expected_arrival_at": legacy_service._as_iso(leg.expected_arrival_at),
        "received_by_user_id": leg.received_by_user_id,
        "received_at": legacy_service._as_iso(leg.received_at),
        "items": [
            {
                "leg_item_id": int(item.leg_item_id),
                "item_id": item.item_id,
                "batch_id": item.batch_id,
                "quantity": str(item.quantity),
                "source_type": item.source_type,
                "source_record_id": item.source_record_id,
                "staging_batch_id": item.staging_batch_id,
                "uom_code": item.uom_code,
            }
            for item in leg.items.order_by("item_id", "batch_id", "leg_item_id")
        ],
        "waybill_no": waybill.waybill_no if waybill is not None else None,
    }


def _leg_dispatch_rows(leg: OperationsConsolidationLeg) -> list[dict[str, Any]]:
    return [
        {
            "item_id": int(item.item_id),
            "quantity": item.quantity,
            "inventory_id": int(leg.source_warehouse_id),
            "batch_id": int(item.batch_id),
            "source_type": item.source_type,
        }
        for item in leg.items.order_by("leg_item_id")
    ]


def _pickup_release_rows(package_record: OperationsPackage) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    received_legs = list(
        package_record.consolidation_legs.filter(
            status_code=CONSOLIDATION_LEG_STATUS_RECEIVED_AT_STAGING
        ).order_by("leg_sequence")
    )
    for leg in received_legs:
        for item in leg.items.order_by("leg_item_id"):
            if item.staging_batch_id is None:
                raise OperationValidationError(
                    {
                        "pickup_release": (
                            f"Leg item {item.leg_item_id} is missing its staging batch mapping."
                        )
                    }
                )
            rows.append(
                {
                    "item_id": int(item.item_id),
                    "quantity": item.quantity,
                    "inventory_id": int(leg.staging_warehouse_id),
                    "batch_id": int(item.staging_batch_id),
                    "source_type": "ON_HAND",
                }
            )
    if rows or package_record.consolidation_legs.exists():
        return rows

    staging_warehouse_id = int(package_record.staging_warehouse_id or 0)
    if staging_warehouse_id <= 0:
        raise OperationValidationError(
            {"pickup_release": "Package is missing a valid staging warehouse for pickup release."}
        )
    for line in package_record.allocation_lines.order_by("line_id"):
        if int(line.source_warehouse_id) != staging_warehouse_id:
            raise OperationValidationError(
                {
                    "pickup_release": (
                        f"Allocation line {line.line_id} is not fully staged for pickup release."
                    )
                }
            )
        rows.append(
            {
                "item_id": int(line.item_id),
                "quantity": line.quantity,
                "inventory_id": staging_warehouse_id,
                "batch_id": int(line.batch_id),
                "source_type": "ON_HAND",
            }
        )
    return rows


def _materialized_leg_item_mapping(
    package_record: OperationsPackage,
) -> dict[tuple[int, int, int], OperationsConsolidationLegItem]:
    mapping: dict[tuple[int, int, int], OperationsConsolidationLegItem] = {}
    for leg in package_record.consolidation_legs.filter(
        status_code=CONSOLIDATION_LEG_STATUS_RECEIVED_AT_STAGING
    ).order_by("leg_sequence"):
        for item in leg.items.order_by("leg_item_id"):
            mapping[(int(leg.source_warehouse_id), int(item.batch_id), int(item.item_id))] = item
    return mapping


def _staging_delivery_ready(package_record: OperationsPackage) -> bool:
    return (
        package_record.fulfillment_mode == FULFILLMENT_MODE_DELIVER_FROM_STAGING
        and package_record.status_code == PACKAGE_STATUS_READY_FOR_DISPATCH
    )


def _create_consolidation_legs(
    *,
    package_record: OperationsPackage,
    actor_id: str,
) -> list[OperationsConsolidationLeg]:
    if package_record.staging_warehouse_id in (None, ""):
        raise OperationValidationError(
            {"staging_warehouse_id": "A staging warehouse is required before consolidation legs can be created."}
        )
    existing_legs = list(
        package_record.consolidation_legs.select_for_update().order_by("leg_sequence")
    )
    if existing_legs and any(
        leg.status_code != CONSOLIDATION_LEG_STATUS_PLANNED for leg in existing_legs
    ):
        raise OperationValidationError(
            {
                "consolidation": (
                    "Consolidation legs cannot be rebuilt after dispatch or receipt activity has started."
                )
            }
        )
    if existing_legs:
        existing_leg_ids = [int(leg.leg_id) for leg in existing_legs]
        for leg_id in existing_leg_ids:
            complete_queue_assignments(
                entity_type=ENTITY_CONSOLIDATION_LEG,
                entity_id=leg_id,
                actor_id=actor_id,
                completion_status="CANCELLED",
            )
        OperationsConsolidationLegItem.objects.filter(
            leg_id__in=existing_leg_ids
        ).delete()
        OperationsConsolidationLeg.objects.filter(
            leg_id__in=existing_leg_ids
        ).delete()

    allocation_lines = list(
        OperationsAllocationLine.objects.filter(package=package_record).order_by(
            "source_warehouse_id",
            "item_id",
            "batch_id",
        )
    )
    grouped_lines: dict[int, list[OperationsAllocationLine]] = {}
    for line in allocation_lines:
        grouped_lines.setdefault(int(line.source_warehouse_id), []).append(line)
    now = timezone.now()
    created_legs: list[OperationsConsolidationLeg] = []
    for source_warehouse_id in sorted(grouped_lines):
        if int(source_warehouse_id) == int(package_record.staging_warehouse_id):
            continue
        leg = OperationsConsolidationLeg.objects.create(
            package=package_record,
            leg_sequence=len(created_legs) + 1,
            source_warehouse_id=source_warehouse_id,
            staging_warehouse_id=int(package_record.staging_warehouse_id),
            status_code=CONSOLIDATION_LEG_STATUS_PLANNED,
            create_by_id=actor_id,
            create_dtime=now,
            update_by_id=actor_id,
            update_dtime=now,
        )
        leg_items = [
            OperationsConsolidationLegItem(
                leg=leg,
                item_id=int(line.item_id),
                batch_id=int(line.batch_id),
                quantity=line.quantity,
                source_type=line.source_type,
                source_record_id=line.source_record_id,
                uom_code=line.uom_code,
                create_by_id=actor_id,
                create_dtime=now,
                update_by_id=actor_id,
                update_dtime=now,
            )
            for line in grouped_lines[source_warehouse_id]
        ]
        OperationsConsolidationLegItem.objects.bulk_create(leg_items)
        record_status_transition(
            entity_type=ENTITY_CONSOLIDATION_LEG,
            entity_id=int(leg.leg_id),
            from_status=None,
            to_status=leg.status_code,
            actor_id=actor_id,
        )
        created_legs.append(leg)
    _update_package_workflow_fields(
        package_record,
        actor_id=actor_id,
        consolidation_status=CONSOLIDATION_STATUS_AWAITING_LEGS,
    )
    return created_legs


def _transition_staged_package_ready(
    *,
    package: ReliefPkg,
    request_record: OperationsReliefRequest,
    package_record: OperationsPackage,
    actor_id: str,
    materialize_dispatch_sources: bool,
) -> OperationsPackage:
    if package_record.fulfillment_mode == FULFILLMENT_MODE_PICKUP_AT_STAGING:
        package_record = _sync_operations_package(
            package,
            request_record=request_record,
            actor_id=actor_id,
            status_code=PACKAGE_STATUS_READY_FOR_PICKUP,
            source_warehouse_id=package_record.staging_warehouse_id,
        )
        _assign_pickup_release_queue(
            package_record=package_record,
            tenant_id=request_record.beneficiary_tenant_id,
        )
        return _update_package_workflow_fields(
            package_record,
            actor_id=actor_id,
            consolidation_status=CONSOLIDATION_STATUS_ALL_RECEIVED,
        )

    if materialize_dispatch_sources:
        _materialize_staged_dispatch_sources(package_record=package_record, actor_id=actor_id)
    package_record = _sync_operations_package(
        package,
        request_record=request_record,
        actor_id=actor_id,
        status_code=PACKAGE_STATUS_READY_FOR_DISPATCH,
        source_warehouse_id=package_record.staging_warehouse_id,
    )
    package_record = _update_package_workflow_fields(
        package_record,
        actor_id=actor_id,
        consolidation_status=CONSOLIDATION_STATUS_ALL_RECEIVED,
    )
    _ensure_dispatch_record(package=package, package_record=package_record, actor_id=actor_id)
    assign_roles_to_queue(
        queue_code=QUEUE_CODE_DISPATCH,
        entity_type=ENTITY_PACKAGE,
        entity_id=int(package_record.package_id),
        role_codes=DISPATCH_ROLE_CODES,
        tenant_id=request_record.beneficiary_tenant_id,
    )
    return package_record


def _update_package_consolidation_status(
    *,
    package_record: OperationsPackage,
    actor_id: str,
) -> str | None:
    if package_record.consolidation_status == CONSOLIDATION_STATUS_PARTIAL_RELEASE_REQUESTED:
        return CONSOLIDATION_STATUS_PARTIAL_RELEASE_REQUESTED
    summary = _package_leg_summary(package_record)
    if summary["total_legs"] == 0:
        status = None
    elif summary["received_legs"] == summary["total_legs"]:
        status = CONSOLIDATION_STATUS_ALL_RECEIVED
    elif summary["received_legs"] > 0:
        status = CONSOLIDATION_STATUS_PARTIALLY_RECEIVED
    elif summary["in_transit_legs"] > 0:
        status = CONSOLIDATION_STATUS_LEGS_IN_TRANSIT
    else:
        status = CONSOLIDATION_STATUS_AWAITING_LEGS
    _update_package_workflow_fields(
        package_record,
        actor_id=actor_id,
        consolidation_status=status,
    )
    return status


def _create_leg_shadow_transfer(
    *,
    leg: OperationsConsolidationLeg,
    package_record: OperationsPackage,
    actor_id: str,
    request: ReliefRqst,
    dispatched_at: datetime,
) -> int:
    transfer_id = int(legacy_service._next_int_id("transfer", "transfer_id"))
    reason_text = (
        f"Consolidation leg for package {package_record.package_no} "
        f"(leg {leg.leg_sequence})"
    )
    Transfer.objects.create(
        transfer_id=transfer_id,
        fr_inventory_id=int(leg.source_warehouse_id),
        to_inventory_id=int(leg.staging_warehouse_id),
        eligible_event_id=request.eligible_event_id,
        needs_list_id=None,
        transfer_date=dispatched_at.date(),
        reason_text=reason_text,
        transfer_context="CONSOLIDATION",
        status_code="D",
        create_by_id=actor_id,
        create_dtime=dispatched_at,
        update_by_id=actor_id,
        update_dtime=dispatched_at,
        verify_by_id=actor_id,
        verify_dtime=dispatched_at,
        dispatched_at=dispatched_at,
        dispatched_by=actor_id,
        expected_arrival=leg.expected_arrival_at,
        version_nbr=1,
    )
    TransferItem.objects.bulk_create(
        [
            TransferItem(
                transfer_id=transfer_id,
                item_id=int(item.item_id),
                batch_id=int(item.batch_id),
                inventory_id=int(leg.source_warehouse_id),
                item_qty=item.quantity,
                uom_code=item.uom_code,
                reason_text=reason_text,
                create_by_id=actor_id,
                create_dtime=dispatched_at,
                update_by_id=actor_id,
                update_dtime=dispatched_at,
                version_nbr=1,
            )
            for item in leg.items.order_by("leg_item_id")
        ]
    )
    leg.shadow_transfer_id = transfer_id
    leg.update_by_id = actor_id
    leg.update_dtime = dispatched_at
    leg.version_nbr = int(leg.version_nbr or 0) + 1
    leg.save(update_fields=["shadow_transfer_id", "update_by_id", "update_dtime", "version_nbr"])
    return transfer_id


def _create_consolidation_waybill(
    *,
    leg: OperationsConsolidationLeg,
    package: ReliefPkg,
    request: ReliefRqst,
    actor_id: str,
) -> OperationsConsolidationWaybill:
    artifact_payload = {
        "package_id": int(package.reliefpkg_id),
        "package_tracking_no": package.tracking_no,
        "request_id": int(request.reliefrqst_id),
        "request_tracking_no": request.tracking_no,
        "leg_id": int(leg.leg_id),
        "leg_sequence": leg.leg_sequence,
        "source_warehouse_id": leg.source_warehouse_id,
        "staging_warehouse_id": leg.staging_warehouse_id,
        "driver_name": leg.driver_name,
        "vehicle_id": leg.vehicle_id,
        "vehicle_registration": leg.vehicle_registration,
        "vehicle_type": leg.vehicle_type,
        "transport_mode": leg.transport_mode,
        "departure_dtime": legacy_service._as_iso(leg.dispatched_at),
        "expected_arrival_dtime": legacy_service._as_iso(leg.expected_arrival_at),
        "line_items": [
            {
                "item_id": int(item.item_id),
                "batch_id": int(item.batch_id),
                "quantity": str(item.quantity),
                "uom_code": item.uom_code,
            }
            for item in leg.items.order_by("item_id", "batch_id")
        ],
    }
    return OperationsConsolidationWaybill.objects.create(
        leg=leg,
        waybill_no=f"{package.tracking_no}-L{leg.leg_sequence:02d}",
        artifact_payload_json=artifact_payload,
        artifact_version=1,
        generated_by_id=actor_id,
    )


def _receive_leg_stock_into_staging(
    *,
    leg: OperationsConsolidationLeg,
    actor_id: str,
) -> None:
    now = timezone.now()
    for item in leg.items.select_for_update().order_by("leg_item_id"):
        source_batch = ItemBatch.objects.select_for_update().get(batch_id=int(item.batch_id))
        inventory = (
            Inventory.objects.select_for_update()
            .filter(inventory_id=int(leg.staging_warehouse_id), item_id=int(item.item_id))
            .first()
        )
        if inventory is None:
            inventory = Inventory.objects.create(
                inventory_id=int(leg.staging_warehouse_id),
                item_id=int(item.item_id),
                usable_qty=legacy_service._quantize_qty(0),
                reserved_qty=legacy_service._quantize_qty(0),
                defective_qty=legacy_service._quantize_qty(0),
                expired_qty=legacy_service._quantize_qty(0),
                uom_code=item.uom_code or source_batch.uom_code,
                status_code="A",
                update_by_id=actor_id,
                update_dtime=now,
                version_nbr=1,
            )
        # Keep received staging stock reserved for the package so pickup/final
        # dispatch consumes the same reservation rather than unclaimed stock.
        inventory.usable_qty = legacy_service._quantize_qty(inventory.usable_qty) + item.quantity
        inventory.reserved_qty = legacy_service._quantize_qty(inventory.reserved_qty) + item.quantity
        inventory.update_by_id = actor_id
        inventory.update_dtime = now
        inventory.version_nbr = int(inventory.version_nbr or 0) + 1
        inventory.save(
            update_fields=["usable_qty", "reserved_qty", "update_by_id", "update_dtime", "version_nbr"]
        )

        staging_batch_id = int(legacy_service._next_int_id("itembatch", "batch_id"))
        ItemBatch.objects.create(
            batch_id=staging_batch_id,
            inventory_id=int(leg.staging_warehouse_id),
            item_id=int(item.item_id),
            batch_no=source_batch.batch_no,
            batch_date=source_batch.batch_date,
            expiry_date=source_batch.expiry_date,
            usable_qty=item.quantity,
            reserved_qty=item.quantity,
            defective_qty=legacy_service._quantize_qty(0),
            expired_qty=legacy_service._quantize_qty(0),
            uom_code=item.uom_code or source_batch.uom_code,
            status_code=source_batch.status_code or "A",
            update_by_id=actor_id,
            update_dtime=now,
            version_nbr=1,
        )
        item.staging_batch_id = staging_batch_id
        item.update_by_id = actor_id
        item.update_dtime = now
        item.version_nbr = int(item.version_nbr or 0) + 1
        item.save(update_fields=["staging_batch_id", "update_by_id", "update_dtime", "version_nbr"])


def _materialize_staged_dispatch_sources(
    *,
    package_record: OperationsPackage,
    actor_id: str,
) -> None:
    mapping = _materialized_leg_item_mapping(package_record)
    if not mapping:
        raise OperationValidationError(
            {"dispatch": "No received consolidation leg stock is available at staging."}
        )
    line_items = list(
        OperationsAllocationLine.objects.select_for_update().filter(package=package_record).order_by("line_id")
    )
    for line in line_items:
        key = (int(line.source_warehouse_id), int(line.batch_id), int(line.item_id))
        leg_item = mapping.get(key)
        if leg_item is None or leg_item.staging_batch_id is None:
            raise OperationValidationError(
                {
                    "dispatch": (
                        f"Package allocation line {line.line_id} is missing a staging stock mapping."
                    )
                }
            )
        line.source_warehouse_id = int(package_record.staging_warehouse_id or 0)
        line.batch_id = int(leg_item.staging_batch_id)
        line.source_type = "ON_HAND"
        line.source_record_id = None
        line.update_by_id = actor_id
        line.update_dtime = timezone.now()
        line.version_nbr = int(line.version_nbr or 0) + 1
        line.save(
            update_fields=[
                "source_warehouse_id",
                "batch_id",
                "source_type",
                "source_record_id",
                "update_by_id",
                "update_dtime",
                "version_nbr",
            ]
        )

    ReliefPkgItem.objects.filter(reliefpkg_id=int(package_record.package_id)).delete()
    now = timezone.now()
    relief_pkg_items = [
        ReliefPkgItem(
            reliefpkg_id=int(package_record.package_id),
            fr_inventory_id=int(line.source_warehouse_id),
            batch_id=int(line.batch_id),
            item_id=int(line.item_id),
            item_qty=line.quantity,
            uom_code=line.uom_code,
            reason_text=line.reason_text,
            create_by_id=actor_id,
            create_dtime=now,
            update_by_id=actor_id,
            update_dtime=now,
            version_nbr=1,
        )
        for line in line_items
    ]
    ReliefPkgItem.objects.bulk_create(relief_pkg_items)
    _update_package_workflow_fields(
        package_record,
        actor_id=actor_id,
    )
    if package_record.source_warehouse_id != package_record.staging_warehouse_id:
        package_record.source_warehouse_id = package_record.staging_warehouse_id
        package_record.update_by_id = actor_id
        package_record.update_dtime = now
        package_record.version_nbr = int(package_record.version_nbr or 0) + 1
        package_record.save(
            update_fields=[
                "source_warehouse_id",
                "update_by_id",
                "update_dtime",
                "version_nbr",
            ]
        )


def _request_fully_dispatched(reliefrqst_id: int) -> bool:
    item_rows = legacy_service._request_item_rows_for_allocation(reliefrqst_id)
    if not item_rows:
        return False
    return all(
        Decimal(str(row.get("issue_qty") or "0")) >= Decimal(str(row.get("request_qty") or "0"))
        for row in item_rows
    )


def _serialize_notifications(*, actor_id: str, actor_roles: Iterable[str], tenant_context: TenantContext) -> list[dict[str, Any]]:
    notifications = actor_notification_queryset(
        actor_id=actor_id,
        actor_roles=actor_roles,
        tenant_context=tenant_context,
    )[:100]
    return [
        {
            "notification_id": notification.notification_id,
            "event_code": notification.event_code,
            "entity_type": notification.entity_type,
            "entity_id": notification.entity_id,
            "recipient_user_id": notification.recipient_user_id,
            "recipient_role_code": notification.recipient_role_code,
            "recipient_tenant_id": notification.recipient_tenant_id,
            "message_text": notification.message_text,
            "queue_code": notification.queue_code,
            "read_at": legacy_service._as_iso(notification.read_at),
            "created_at": legacy_service._as_iso(notification.created_at),
        }
        for notification in notifications
    ]


def _serialize_queue_assignments(*, actor_id: str, actor_roles: Iterable[str], tenant_context: TenantContext) -> list[dict[str, Any]]:
    assignments = actor_queue_queryset(
        actor_id=actor_id,
        actor_roles=actor_roles,
        tenant_context=tenant_context,
    )[:100]
    return [
        {
            "queue_assignment_id": assignment.queue_assignment_id,
            "queue_code": assignment.queue_code,
            "entity_type": assignment.entity_type,
            "entity_id": assignment.entity_id,
            "assigned_role_code": assignment.assigned_role_code,
            "assigned_tenant_id": assignment.assigned_tenant_id,
            "assigned_user_id": assignment.assigned_user_id,
            "assignment_status": assignment.assignment_status,
            "assigned_at": legacy_service._as_iso(assignment.assigned_at),
            "completed_at": legacy_service._as_iso(assignment.completed_at),
        }
        for assignment in assignments
    ]


def _update_existing_package(
    package: ReliefPkg,
    *,
    actor_id: str,
    raw_destination: int | None,
    payload: Mapping[str, Any],
) -> ReliefPkg:
    transport_mode = str(payload.get("transport_mode") or "").strip() or None
    comments_text = str(payload.get("comments_text") or "").strip() or None
    updated_fields: list[str] = []
    if raw_destination is not None and package.to_inventory_id != raw_destination:
        package.to_inventory_id = raw_destination
        updated_fields.append("to_inventory_id")
    if transport_mode is not None:
        package.transport_mode = transport_mode
        updated_fields.append("transport_mode")
    if comments_text is not None:
        package.comments_text = comments_text
        updated_fields.append("comments_text")
    if updated_fields:
        package.update_by_id = actor_id
        package.update_dtime = timezone.now()
        package.version_nbr = int(package.version_nbr or 0) + 1
        updated_fields.extend(["update_by_id", "update_dtime", "version_nbr"])
        package.save(update_fields=updated_fields)
    return package


def _create_package_for_request(
    request: ReliefRqst,
    *,
    actor_id: str,
    raw_destination: int | None,
    payload: Mapping[str, Any],
) -> ReliefPkg:
    reliefpkg_id = _next_int_id("reliefpkg", "reliefpkg_id")
    now = timezone.now()
    return ReliefPkg.objects.create(
        reliefpkg_id=reliefpkg_id,
        agency_id=request.agency_id,
        tracking_no=_tracking_no("PK", reliefpkg_id),
        eligible_event_id=request.eligible_event_id,
        to_inventory_id=raw_destination,
        reliefrqst_id=request.reliefrqst_id,
        start_date=now.date(),
        transport_mode=str(payload.get("transport_mode") or "").strip() or None,
        comments_text=str(payload.get("comments_text") or "").strip() or None,
        status_code=PKG_STATUS_DRAFT,
        create_by_id=actor_id,
        create_dtime=now,
        update_by_id=actor_id,
        update_dtime=now,
        version_nbr=1,
    )


def _ensure_package(reliefrqst_id: int, *, actor_id: str, payload: Mapping[str, Any]) -> ReliefPkg:
    raw_destination = _optional_positive_int(payload.get("to_inventory_id"), "to_inventory_id")
    request = _load_request(reliefrqst_id, for_update=True)
    package = _current_package_for_request(reliefrqst_id, for_update=True)
    if _request_fully_dispatched(int(request.reliefrqst_id)):
        raise OperationValidationError(
            {
                "request": (
                    "All items on this request are already fully issued. "
                    "Cancel a dispatched package to free quantity before creating a new one."
                )
            }
        )
    if package is not None:
        if (
            int(request.status_code or STATUS_DRAFT) == STATUS_PART_FILLED
            and _current_package_status(package) == PKG_STATUS_DISPATCHED
        ):
            return _create_package_for_request(
                request,
                actor_id=actor_id,
                raw_destination=raw_destination,
                payload=payload,
            )
        return _update_existing_package(
            package,
            actor_id=actor_id,
            raw_destination=raw_destination,
            payload=payload,
        )
    return _create_package_for_request(
        request,
        actor_id=actor_id,
        raw_destination=raw_destination,
        payload=payload,
    )


def _resolve_candidate_warehouse_ids(
    reliefrqst_id: int,
    *,
    payload: Mapping[str, Any] | None = None,
    selected_rows: Sequence[Mapping[str, Any]] | None = None,
) -> list[int]:
    warehouse_ids: set[int] = set()
    raw_source = (payload or {}).get("source_warehouse_id")
    if raw_source not in (None, ""):
        warehouse_ids.add(int(raw_source))
    for row in selected_rows or []:
        if row.get("inventory_id") not in (None, ""):
            warehouse_ids.add(int(row["inventory_id"]))
    package = _current_package_for_request(reliefrqst_id)
    if package is not None:
        for row in _load_package_plan_with_source_info(int(package.reliefpkg_id)):
            warehouse_ids.add(int(row["inventory_id"]))
    execution_link = _execution_link_for_request(reliefrqst_id)
    if execution_link is not None:
        warehouse_ids.add(int(execution_link.needs_list.warehouse_id))
    return sorted(warehouse_ids)


def _allocation_line_key(row: Mapping[str, Any]) -> tuple[int, int, str, int | None]:
    source_record_id = row.get("source_record_id")
    return (
        int(row["inventory_id"]),
        int(row["batch_id"]),
        str(row.get("source_type") or "ON_HAND").strip().upper() or "ON_HAND",
        int(source_record_id) if source_record_id not in (None, "") else None,
    )


def _committed_warehouses_by_item(package_pk: int) -> dict[int, list[int]]:
    rows = (
        OperationsAllocationLine.objects.filter(package_id=package_pk)
        .order_by("line_id")
        .values_list("item_id", "source_warehouse_id")
    )
    result: dict[int, list[int]] = {}
    for item_id, warehouse_id in rows:
        if warehouse_id is None:
            continue
        warehouse_int = int(warehouse_id)
        if warehouse_int <= 0:
            continue
        bucket = result.setdefault(int(item_id), [])
        if warehouse_int not in bucket:
            bucket.append(warehouse_int)
    return result


def _draft_committed_warehouses_by_item(reliefrqst_id: int) -> dict[int, list[int]]:
    draft_package = (
        OperationsPackage.objects.filter(
            relief_request_id=reliefrqst_id,
            status_code=PACKAGE_STATUS_DRAFT,
        )
        .order_by("-package_id")
        .first()
    )
    if draft_package is None:
        return {}
    return _committed_warehouses_by_item(int(draft_package.package_id))


def _draft_allocations_by_item(reliefrqst_id: int) -> dict[int, list[dict[str, Any]]]:
    draft_package = (
        OperationsPackage.objects.filter(
            relief_request_id=reliefrqst_id,
            status_code=PACKAGE_STATUS_DRAFT,
        )
        .order_by("-package_id")
        .first()
    )
    if draft_package is None:
        return {}

    rows = (
        OperationsAllocationLine.objects.filter(package_id=draft_package.package_id)
        .order_by("line_id")
        .values(
            "item_id",
            "source_warehouse_id",
            "batch_id",
            "quantity",
            "source_type",
            "source_record_id",
            "uom_code",
        )
    )
    result: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        item_id = int(row["item_id"])
        warehouse_id = int(row["source_warehouse_id"] or 0)
        if warehouse_id <= 0:
            continue
        result.setdefault(item_id, []).append(
            {
                "item_id": item_id,
                "inventory_id": warehouse_id,
                "batch_id": int(row["batch_id"]),
                "quantity": _quantize_qty(row["quantity"]),
                "source_type": str(row.get("source_type") or "ON_HAND").strip().upper() or "ON_HAND",
                "source_record_id": row.get("source_record_id"),
                "uom_code": row.get("uom_code"),
            }
        )
    return result


def _normalized_item_draft_allocations(
    draft_allocations: Sequence[Mapping[str, Any]] | None,
    *,
    item_id: int,
) -> list[dict[str, Any]]:
    if not draft_allocations:
        return []

    errors: dict[str, str] = {}
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(draft_allocations):
        if not isinstance(raw, Mapping):
            errors[f"draft_allocations[{index}]"] = "Each draft allocation must be an object."
            continue
        draft_item_id = _positive_int(raw.get("item_id"), f"draft_allocations[{index}].item_id", errors)
        if draft_item_id is not None and draft_item_id != item_id:
            errors[f"draft_allocations[{index}].item_id"] = f"Must match item_id {item_id}."
        inventory_id = _positive_int(raw.get("inventory_id"), f"draft_allocations[{index}].inventory_id", errors)
        batch_id = _positive_int(raw.get("batch_id"), f"draft_allocations[{index}].batch_id", errors)
        try:
            quantity = _quantize_qty(Decimal(str(raw.get("quantity"))))
        except (InvalidOperation, ValueError, TypeError):
            errors[f"draft_allocations[{index}].quantity"] = "Must be a decimal number."
            continue
        if quantity <= 0:
            errors[f"draft_allocations[{index}].quantity"] = "Must be greater than zero."
        source_record_id = raw.get("source_record_id")
        normalized_source_record_id = None
        if source_record_id not in (None, ""):
            normalized_source_record_id = _positive_int(
                source_record_id,
                f"draft_allocations[{index}].source_record_id",
                errors,
            )
        if inventory_id is None or batch_id is None or draft_item_id is None:
            continue
        normalized.append(
            {
                "item_id": draft_item_id,
                "inventory_id": inventory_id,
                "batch_id": batch_id,
                "quantity": quantity,
                "source_type": str(raw.get("source_type") or "ON_HAND").strip().upper() or "ON_HAND",
                "source_record_id": normalized_source_record_id,
            }
        )

    if errors:
        raise OperationValidationError(errors)
    return normalized


def _active_source_stock_integrity_issue(
    *,
    source_warehouse_id: int,
    item_id: int,
    as_of_date: date,
    candidate_warehouse_ids: Sequence[int] | None = None,
) -> str | None:
    warehouse_ids: list[int] = []
    seen_warehouse_ids: set[int] = set()
    for raw_warehouse_id in (source_warehouse_id, *(candidate_warehouse_ids or ())):
        warehouse_id = int(raw_warehouse_id)
        if warehouse_id <= 0 or warehouse_id in seen_warehouse_ids:
            continue
        seen_warehouse_ids.add(warehouse_id)
        warehouse_ids.append(warehouse_id)

    try:
        for warehouse_id in warehouse_ids:
            totals = _inventory_batch_stock_totals(
                warehouse_id,
                int(item_id),
                as_of_date=as_of_date,
            )
            if totals is None:
                batch_totals = _active_batch_stock_totals(
                    inventory_id=warehouse_id,
                    item_id=int(item_id),
                    as_of_date=as_of_date,
                )
                if batch_totals["batch_row_count"] > 0:
                    return _inventory_batch_drift_message(
                        warehouse_id,
                        int(item_id),
                        as_of_date=as_of_date,
                    )
                continue
            if not totals["has_drift"]:
                continue
            if _quantize_qty(totals["batch_available_qty"]) <= _quantize_qty(
                totals["inventory_available_qty"]
            ):
                continue
            return _inventory_batch_drift_message(
                warehouse_id,
                int(item_id),
                as_of_date=as_of_date,
            )
    except DatabaseError:
        # Some preview/test contexts do not materialize the legacy inventory
        # tables. Skip the drift hint there and preserve the existing preview flow.
        return None
    return None


def _active_batch_stock_totals(
    *,
    inventory_id: int,
    item_id: int,
    as_of_date: date,
) -> dict[str, Any]:
    as_of = datetime.combine(as_of_date, datetime.max.time())
    if timezone.is_naive(as_of):
        as_of = timezone.make_aware(as_of, timezone.get_current_timezone())

    active_status = str(getattr(settings, "NEEDS_INVENTORY_ACTIVE_STATUS", "A")).upper()
    batch_totals = ItemBatch.objects.filter(
        inventory_id=int(inventory_id),
        item_id=int(item_id),
        status_code__iexact=active_status,
        update_dtime__lte=as_of,
    ).aggregate(
        total_usable=Sum("usable_qty"),
        total_reserved=Sum("reserved_qty"),
        row_count=Count("batch_id"),
    )
    batch_usable = _quantize_qty(batch_totals.get("total_usable"))
    batch_reserved = _quantize_qty(batch_totals.get("total_reserved"))
    return {
        "inventory_id": int(inventory_id),
        "item_id": int(item_id),
        "batch_usable_qty": batch_usable,
        "batch_reserved_qty": batch_reserved,
        "batch_available_qty": _quantize_qty(batch_usable - batch_reserved),
        "batch_row_count": int(batch_totals.get("row_count") or 0),
    }


def _draft_allocations_by_key(
    draft_allocations: Sequence[Mapping[str, Any]],
) -> dict[tuple[int, int, str, int | None], Decimal]:
    allocation_map: dict[tuple[int, int, str, int | None], Decimal] = {}
    for row in draft_allocations:
        key = _allocation_line_key(row)
        allocation_map[key] = allocation_map.get(key, Decimal("0")) + _quantize_qty(row["quantity"])
    return allocation_map


_APPROVAL_REQUIRED_OVERRIDE_MARKERS = frozenset({"item_not_in_request", "insufficient_on_hand_stock"})


def _approval_required_override_markers(markers: Sequence[str]) -> list[str]:
    return [marker for marker in markers if marker in _APPROVAL_REQUIRED_OVERRIDE_MARKERS]


def _adjust_candidates_for_draft_allocations(
    candidates: Sequence[Mapping[str, Any]],
    draft_allocations: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if not draft_allocations:
        return [dict(candidate) for candidate in candidates]

    draft_allocations_map = _draft_allocations_by_key(draft_allocations)
    adjusted_candidates: list[dict[str, Any]] = []
    for candidate in candidates:
        draft_qty = draft_allocations_map.get(_allocation_line_key(candidate), Decimal("0"))
        available_qty = max(Decimal("0"), _quantize_qty(candidate["available_qty"]) - draft_qty)
        usable_qty = max(
            Decimal("0"),
            _quantize_qty(candidate.get("usable_qty", candidate["available_qty"])) - draft_qty,
        )
        if available_qty <= 0:
            continue
        adjusted_candidates.append(
            {
                **candidate,
                "available_qty": _quantize_qty(available_qty),
                "usable_qty": _quantize_qty(usable_qty),
            }
        )
    return adjusted_candidates


def _warehouse_usable_surplus_for_item(
    warehouse_id: int,
    item_id: int,
    *,
    item: Item | Mapping[str, Any] | None,
    as_of_date: date,
    draft_allocations: Sequence[Mapping[str, Any]] | None = None,
) -> Decimal:
    candidates = _fetch_batch_candidates(warehouse_id, item_id, as_of_date=as_of_date)
    adjusted_candidates = _adjust_candidates_for_draft_allocations(candidates, draft_allocations or ())
    sorted_candidates = sort_batch_candidates(item or {"issuance_order": "FIFO"}, adjusted_candidates, as_of_date=as_of_date)
    return sum(
        (
            _quantize_qty(candidate.get("available_qty"))
            for candidate in sorted_candidates
        ),
        Decimal("0"),
    )


def build_item_warehouse_cards(
    *,
    item_id: int,
    remaining_qty: Decimal,
    item: Item | Mapping[str, Any] | None,
    tenant_context: TenantContext | None,
    as_of_date: date | None = None,
    draft_allocations: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return every warehouse that holds stock of ``item_id``, ranked by the
    item's FEFO/FIFO rule, with a greedy ``suggested_qty`` pre-filled across
    the ranked warehouses up to ``remaining_qty``.

    The returned shape is the contract consumed by the frontend's
    ``WarehouseAllocationCardComponent`` — each entry contains everything the
    card needs to render without re-querying batches on the client.
    """

    as_of = as_of_date or timezone.localdate()
    if item is None:
        raw_issuance = "FIFO"
    elif isinstance(item, Mapping):
        raw_issuance = item.get("issuance_order") or "FIFO"
    else:
        raw_issuance = getattr(item, "issuance_order", None) or "FIFO"
    issuance_order = str(raw_issuance).upper() or "FIFO"

    # Pull every warehouse that has any stock for the item (exclude_warehouse_id=0
    # means no warehouse is excluded — 0 is never a valid warehouse id).
    warehouse_rows, _warnings = data_access.get_warehouses_with_stock([item_id], 0)
    warehouse_entries = warehouse_rows.get(item_id, [])

    cards_raw: list[dict[str, Any]] = []
    for warehouse_row in warehouse_entries:
        warehouse_id = int(warehouse_row["warehouse_id"])
        if tenant_context is not None and not can_access_warehouse(
            tenant_context, warehouse_id, write=True
        ):
            continue
        raw_candidates = _fetch_batch_candidates(warehouse_id, item_id, as_of_date=as_of)
        adjusted = _adjust_candidates_for_draft_allocations(
            raw_candidates, draft_allocations or ()
        )
        sorted_batches = sort_batch_candidates(
            item or {"issuance_order": issuance_order},
            adjusted,
            as_of_date=as_of,
        )
        total_available = sum(
            (_quantize_qty(c.get("available_qty")) for c in sorted_batches),
            Decimal("0"),
        )
        if total_available <= 0 or not sorted_batches:
            continue
        first_batch = sorted_batches[0]
        rank_key: tuple[Any, ...]
        if issuance_order == "FEFO":
            rank_key = (
                first_batch.get("expiry_date") is None,
                first_batch.get("expiry_date") or date.max,
                first_batch.get("batch_date") or date.max,
                int(first_batch.get("inventory_id") or 0),
                int(first_batch.get("batch_id") or 0),
            )
        else:
            rank_key = (
                first_batch.get("batch_date") or date.min,
                int(first_batch.get("inventory_id") or 0),
                int(first_batch.get("batch_id") or 0),
            )
        cards_raw.append(
            {
                "warehouse_id": warehouse_id,
                "warehouse_name": str(
                    warehouse_row.get("warehouse_name")
                    or first_batch.get("warehouse_name")
                    or f"Warehouse {warehouse_id}"
                ).strip(),
                "total_available": total_available,
                "batches": sorted_batches,
                "rank_key": rank_key,
            }
        )

    cards_raw.sort(key=lambda c: c["rank_key"])

    remaining = _quantize_qty(remaining_qty) if remaining_qty is not None else Decimal("0")
    if remaining < 0:
        remaining = Decimal("0")

    cards: list[dict[str, Any]] = []
    for rank_index, raw in enumerate(cards_raw):
        suggested = min(raw["total_available"], remaining)
        if suggested < 0:
            suggested = Decimal("0")
        remaining = max(Decimal("0"), remaining - suggested)
        cards.append(
            {
                "warehouse_id": raw["warehouse_id"],
                "warehouse_name": raw["warehouse_name"],
                "rank": rank_index,
                "issuance_order": issuance_order,
                "total_available": str(_quantize_qty(raw["total_available"])),
                "suggested_qty": str(_quantize_qty(suggested)),
                "batches": [
                    {
                        "batch_id": int(batch["batch_id"]),
                        "inventory_id": int(batch["inventory_id"]),
                        "batch_no": batch.get("batch_no"),
                        "batch_date": _as_iso(batch.get("batch_date")),
                        "expiry_date": _as_iso(batch.get("expiry_date")),
                        "available_qty": str(_quantize_qty(batch.get("available_qty"))),
                        "usable_qty": str(_quantize_qty(batch.get("usable_qty"))),
                        "reserved_qty": str(_quantize_qty(batch.get("reserved_qty"))),
                        "uom_code": batch.get("uom_code"),
                        "source_type": batch.get("source_type") or "ON_HAND",
                        "source_record_id": batch.get("source_record_id"),
                    }
                    for batch in raw["batches"]
                ],
            }
        )
    return cards


def _build_alternate_warehouse_options(
    *,
    item_id: int,
    item: Item | Mapping[str, Any] | None,
    source_warehouse_id: int,
    remaining_shortfall_qty: Decimal,
    tenant_context: TenantContext | None,
    as_of_date: date,
    draft_allocations: Sequence[Mapping[str, Any]] | None = None,
    excluded_warehouse_ids: Iterable[int] | None = None,
) -> list[dict[str, Any]]:
    if remaining_shortfall_qty <= 0:
        return []

    warehouse_rows, _warnings = data_access.get_warehouses_with_stock([item_id], source_warehouse_id)
    alternates: list[dict[str, Any]] = []
    seen_warehouse_ids = {int(source_warehouse_id)}
    if excluded_warehouse_ids:
        seen_warehouse_ids.update(int(wid) for wid in excluded_warehouse_ids)
    for warehouse_row in warehouse_rows.get(item_id, []):
        warehouse_id = int(warehouse_row["warehouse_id"])
        if warehouse_id in seen_warehouse_ids:
            continue
        seen_warehouse_ids.add(warehouse_id)
        if tenant_context is not None and not can_access_warehouse(tenant_context, warehouse_id, write=True):
            continue
        available_qty = _warehouse_usable_surplus_for_item(
            warehouse_id,
            item_id,
            item=item,
            as_of_date=as_of_date,
            draft_allocations=draft_allocations,
        )
        if available_qty <= 0:
            continue
        alternates.append(
            {
                "warehouse_id": warehouse_id,
                "warehouse_name": str(warehouse_row.get("warehouse_name") or "").strip() or f"Warehouse {warehouse_id}",
                "available_qty_decimal": _quantize_qty(available_qty),
            }
        )

    alternates.sort(key=lambda row: (-row["available_qty_decimal"], row["warehouse_id"]))
    return [
        {
            "warehouse_id": row["warehouse_id"],
            "warehouse_name": row["warehouse_name"],
            "available_qty": str(row["available_qty_decimal"]),
            "suggested_qty": str(min(row["available_qty_decimal"], remaining_shortfall_qty)),
            "can_fully_cover": row["available_qty_decimal"] >= remaining_shortfall_qty,
        }
        for row in alternates
    ]


def _reshape_compat_options(compat: dict[str, Any], reliefrqst_id: int) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for group in compat.get("items", []):
        item: dict[str, Any] = {**group}
        item["request_qty"] = _compat_qty_string(item.pop("required_qty", "0"))
        item["issue_qty"] = _compat_qty_string(item.pop("fulfilled_qty", "0"))
        item.pop("reserved_qty", None)
        item.pop("needs_list_item_id", None)
        item.pop("criticality_level", None)
        item.pop("criticality_rank", None)
        items.append(item)
    return {
        "request": _request_summary(_load_request(reliefrqst_id)),
        "items": items,
    }


def _compat_qty_string(value: Any) -> str:
    try:
        return str(_quantize_qty(Decimal(str(value if value not in (None, "") else "0"))))
    except (InvalidOperation, ValueError, TypeError):
        return "0.0000"


def _build_item_allocation_response(
    reliefrqst_id: int,
    item_id: int,
    *,
    source_warehouse_id: int,
    tenant_context: TenantContext | None = None,
    draft_allocations: Sequence[Mapping[str, Any]] | None = None,
    include_draft_metrics: bool = False,
    additional_warehouse_ids: Sequence[int] | None = None,
) -> dict[str, Any]:
    item_rows = _request_item_rows_for_allocation(reliefrqst_id)
    row = next((r for r in item_rows if int(r["item_id"]) == item_id), None)
    if row is None:
        raise OperationValidationError({"item_id": f"Item {item_id} is not part of request {reliefrqst_id}."})

    item = Item.objects.filter(item_id=item_id).first()
    base_remaining_qty = max(Decimal("0"), _quantize_qty(row["request_qty"]) - _quantize_qty(row["issue_qty"]))
    fully_issued = _quantize_qty(row["issue_qty"]) >= _quantize_qty(row["request_qty"]) and _quantize_qty(row["request_qty"]) > Decimal("0")
    normalized_draft_allocations = _normalized_item_draft_allocations(draft_allocations, item_id=item_id)
    draft_selected_qty = sum((_quantize_qty(allocation["quantity"]) for allocation in normalized_draft_allocations), Decimal("0"))
    effective_remaining_qty = max(Decimal("0"), _quantize_qty(base_remaining_qty) - draft_selected_qty)
    as_of_date = timezone.localdate()
    primary_warehouse_id = int(source_warehouse_id)
    primary_warehouse_accessible = tenant_context is None or can_access_warehouse(
        tenant_context, primary_warehouse_id, write=True
    )
    candidates = (
        list(_fetch_batch_candidates(primary_warehouse_id, item_id, as_of_date=as_of_date))
        if primary_warehouse_accessible
        else []
    )
    merged_warehouse_ids: list[int] = [primary_warehouse_id] if primary_warehouse_accessible else []
    seen_keys: set[tuple[int, int, str, int | None]] = {_allocation_line_key(candidate) for candidate in candidates}
    if additional_warehouse_ids:
        for extra_warehouse_id in additional_warehouse_ids:
            extra_int = int(extra_warehouse_id)
            if extra_int <= 0 or extra_int == primary_warehouse_id or extra_int in merged_warehouse_ids:
                continue
            if tenant_context is not None and not can_access_warehouse(tenant_context, extra_int, write=True):
                continue
            merged_warehouse_ids.append(extra_int)
            for extra_candidate in _fetch_batch_candidates(extra_int, item_id, as_of_date=as_of_date):
                key = _allocation_line_key(extra_candidate)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                candidates.append(extra_candidate)
    # Compute the greedy "additional capacity beyond the draft" suggestion over
    # adjusted quantities (draft commitments subtracted). The UI-facing candidates
    # list, however, must reflect the pre-draft physical state so every warehouse
    # the draft committed to still renders a card on reload — including batches the
    # draft fully consumed. See plan unified-weaving-chipmunk.md for the RQ95009
    # multi-warehouse reload regression this addresses.
    adjusted_candidates = _adjust_candidates_for_draft_allocations(candidates, normalized_draft_allocations)
    sorted_for_suggestion = sort_batch_candidates(
        item or {"issuance_order": "FIFO"}, adjusted_candidates, as_of_date=as_of_date
    )
    stock_integrity_warehouse_ids = list(merged_warehouse_ids)
    for allocation in normalized_draft_allocations:
        warehouse_id = int(allocation["inventory_id"])
        if warehouse_id not in stock_integrity_warehouse_ids:
            stock_integrity_warehouse_ids.append(warehouse_id)
    stock_integrity_issue = _active_source_stock_integrity_issue(
        source_warehouse_id=source_warehouse_id,
        item_id=item_id,
        as_of_date=as_of_date,
        candidate_warehouse_ids=stock_integrity_warehouse_ids,
    )
    suggested_allocations, remaining_after_suggestion = build_greedy_allocation_plan(
        sorted_for_suggestion, effective_remaining_qty
    )
    if stock_integrity_issue:
        suggested_allocations = []
        remaining_after_suggestion = effective_remaining_qty
    sorted_candidates = sort_batch_candidates(
        item or {"issuance_order": "FIFO"}, candidates, as_of_date=as_of_date
    )
    remaining_shortfall_qty = _quantize_qty(remaining_after_suggestion)
    alternate_warehouses = _build_alternate_warehouse_options(
        item_id=item_id,
        item=item,
        source_warehouse_id=source_warehouse_id,
        remaining_shortfall_qty=remaining_shortfall_qty,
        tenant_context=tenant_context,
        as_of_date=as_of_date,
        draft_allocations=normalized_draft_allocations,
        excluded_warehouse_ids=merged_warehouse_ids,
    )
    warehouse_cards = build_item_warehouse_cards(
        item_id=item_id,
        remaining_qty=effective_remaining_qty,
        item=item,
        tenant_context=tenant_context,
        as_of_date=as_of_date,
        draft_allocations=normalized_draft_allocations,
    )
    response = {
        "item_id": item_id,
        "item_code": getattr(item, "item_code", None),
        "item_name": getattr(item, "item_name", None),
        "request_qty": str(_quantize_qty(row["request_qty"])),
        "issue_qty": str(_quantize_qty(row["issue_qty"])),
        "remaining_qty": str(base_remaining_qty.quantize(Decimal("0.0001"))),
        "fully_issued": fully_issued,
        "urgency_ind": row.get("urgency_ind"),
        "candidates": [
            {
                **candidate,
                "available_qty": str(_quantize_qty(candidate["available_qty"])),
                "usable_qty": str(_quantize_qty(candidate["usable_qty"])),
                "reserved_qty": str(_quantize_qty(candidate["reserved_qty"])),
                "batch_date": _as_iso(candidate.get("batch_date")),
                "expiry_date": _as_iso(candidate.get("expiry_date")),
            }
            for candidate in sorted_candidates
        ],
        "suggested_allocations": [
            {**candidate, "quantity": str(_quantize_qty(candidate["quantity"]))}
            for candidate in suggested_allocations
        ],
        "remaining_after_suggestion": str(remaining_after_suggestion.quantize(Decimal("0.0001"))),
        "source_warehouse_id": source_warehouse_id,
        "stock_integrity_issue": stock_integrity_issue,
        "remaining_shortfall_qty": str(remaining_shortfall_qty),
        "continuation_recommended": (not stock_integrity_issue) and remaining_shortfall_qty > 0 and bool(alternate_warehouses),
        "alternate_warehouses": alternate_warehouses,
        "warehouse_cards": warehouse_cards,
    }
    if include_draft_metrics:
        response["draft_selected_qty"] = str(_quantize_qty(draft_selected_qty))
        response["effective_remaining_qty"] = str(_quantize_qty(effective_remaining_qty))
    return response


def _normalized_allocations(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw_allocations = payload.get("allocations")
    if not isinstance(raw_allocations, list) or not raw_allocations:
        raise OperationValidationError({"allocations": "Must provide a non-empty array of allocations."})
    errors: dict[str, str] = {}
    allocations: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_allocations):
        if not isinstance(raw, Mapping):
            errors[f"allocations[{index}]"] = "Each allocation must be an object."
            continue
        item_id = _positive_int(raw.get("item_id"), f"allocations[{index}].item_id", errors)
        inventory_id = _positive_int(raw.get("inventory_id"), f"allocations[{index}].inventory_id", errors)
        batch_id = _positive_int(raw.get("batch_id"), f"allocations[{index}].batch_id", errors)
        quantity = _quantize_qty(raw.get("quantity", raw.get("allocated_qty")))
        if quantity <= 0:
            errors[f"allocations[{index}].quantity"] = "Must be greater than zero."
        allocations.append(
            {
                "item_id": item_id,
                "inventory_id": inventory_id,
                "batch_id": batch_id,
                "quantity": quantity,
                "source_type": str(raw.get("source_type") or "ON_HAND").strip().upper() or "ON_HAND",
                "source_record_id": raw.get("source_record_id"),
                "uom_code": str(raw.get("uom_code") or "").strip() or None,
            }
        )
    if errors:
        raise OperationValidationError(errors)
    return allocations


def _save_package_allocation(
    reliefrqst_id: int,
    *,
    payload: Mapping[str, Any],
    actor_id: str,
    actor_roles: Iterable[str] | None = None,
    allow_pending_override: bool,
    supervisor_user_id: str | None = None,
    supervisor_role_codes: Iterable[str] | None = None,
    override_submitter_user_id: str | None = None,
) -> dict[str, Any]:
    execution_link = _execution_link_for_request(reliefrqst_id)
    request = _load_request(reliefrqst_id, for_update=execution_link is None)
    _ensure_request_in_fulfillment_state(request)
    if not payload.get("allocations"):
        if not allow_pending_override:
            raise OperationValidationError({"allocations": "Allocations are required for override approval."})
        return _package_detail(_ensure_package(reliefrqst_id, actor_id=actor_id, payload=payload))

    allocations = _normalized_allocations(payload)
    requested_destination_id = _optional_positive_int(payload.get("to_inventory_id"), "to_inventory_id")
    if execution_link is not None:
        existing_package = _current_package_for_request(reliefrqst_id)
        return compat_commit_allocation(
            LegacyWorkflowContext(
                needs_list_id=int(execution_link.needs_list_id),
                reliefrqst_id=int(execution_link.reliefrqst_id or reliefrqst_id),
                reliefpkg_id=(
                    int(execution_link.reliefpkg_id)
                    if execution_link.reliefpkg_id
                    else (int(existing_package.reliefpkg_id) if existing_package is not None else None)
                ),
                agency_id=int(request.agency_id),
                destination_warehouse_id=(
                    requested_destination_id
                    if requested_destination_id is not None
                    else (
                        int(existing_package.to_inventory_id)
                        if existing_package is not None and existing_package.to_inventory_id is not None
                        else int(execution_link.needs_list.warehouse_id)
                    )
                ),
                event_id=int(request.eligible_event_id or execution_link.needs_list.event_id),
                submitted_by=execution_link.override_requested_by or execution_link.needs_list.submitted_by,
                transport_mode=str(payload.get("transport_mode") or "").strip() or None,
                urgency_ind=str(request.urgency_ind or payload.get("urgency_ind") or "M").strip().upper() or None,
                request_notes=str(request.rqst_notes_text or payload.get("rqst_notes_text") or "").strip() or None,
                package_comments=str(payload.get("comments_text") or "").strip() or None,
            ),
            allocations,
            actor_user_id=actor_id,
            override_reason_code=str(payload.get("override_reason_code") or "").strip() or None,
            override_note=str(payload.get("override_note") or "").strip() or None,
            allow_pending_override=True,
        )

    package = _ensure_package(reliefrqst_id, actor_id=actor_id, payload=payload)
    current_status = _current_package_status(package)
    if current_status == PKG_STATUS_DISPATCHED:
        raise DispatchError(
            f"Package cannot be modified in status '{PKG_STATUS_LABELS.get(current_status, current_status)}'.",
            code="package_already_finalized",
        )
    old_rows = _selected_plan_for_package(int(package.reliefpkg_id)) if current_status in {"P", "C", "V"} else []
    if old_rows:
        _apply_stock_delta_for_rows(old_rows, actor_user_id=actor_id, delta_sign=-1, update_needs_list=False)
    plan_rows = _group_plan_rows(allocations)

    request_item_rows = _request_item_rows_for_allocation(reliefrqst_id)
    warehouse_ids = _resolve_candidate_warehouse_ids(reliefrqst_id, payload=payload, selected_rows=plan_rows)
    item_lookup = {item.item_id: item for item in Item.objects.filter(item_id__in=[row["item_id"] for row in request_item_rows])}
    override_markers: list[str] = []
    for item_id, rows in _package_plan_map(plan_rows).items():
        if item_id not in item_lookup:
            override_markers.append("item_not_in_request")
            continue
        candidates: list[dict[str, Any]] = []
        for warehouse_id in warehouse_ids:
            candidates.extend(_fetch_batch_candidates(warehouse_id, item_id))
        recommended, remaining = build_greedy_allocation_plan(
            sort_batch_candidates(item_lookup.get(item_id) or {"issuance_order": "FIFO"}, candidates),
            sum((_quantize_qty(row["quantity"]) for row in rows), Decimal("0")),
        )
        if remaining > 0:
            override_markers.append("insufficient_on_hand_stock")
        if _group_plan_rows(recommended) != rows:
            override_markers.append("allocation_order_override")
    override_markers = list(dict.fromkeys(override_markers))
    approval_markers = _approval_required_override_markers(override_markers)
    normalized_actor_roles = set(normalize_role_codes(actor_roles))
    manager_direct_commit = (
        bool(approval_markers)
        and allow_pending_override
        and ROLE_LOGISTICS_MANAGER in normalized_actor_roles
    )
    override_required = bool(approval_markers) and not manager_direct_commit
    override_reason_code = str(payload.get("override_reason_code") or "").strip() or None
    override_note = str(payload.get("override_note") or "").strip() or None
    if approval_markers and not override_reason_code:
        raise OverrideApprovalError(
            "Override reason code is required for allocations that require approval.",
            code="override_details_missing",
        )
    if approval_markers:
        if allow_pending_override and ROLE_LOGISTICS_OFFICER not in normalized_actor_roles:
            if not manager_direct_commit:
                raise OperationValidationError(
                    {
                        "override": (
                            "Only Logistics Officers may submit override requests. "
                            "Logistics Managers may commit their own overrides directly."
                        )
                    }
                )
        if not override_note:
            raise OverrideApprovalError(
                "Override note is required for allocations awaiting approval.",
                code="override_details_missing",
            )
        if not allow_pending_override:
            actual_submitter = override_submitter_user_id or request.create_by_id
            validate_override_approval(
                approver_user_id=supervisor_user_id,
                approver_role_codes=supervisor_role_codes,
                submitter_user_id=actual_submitter,
                needs_list_submitted_by=actual_submitter,
            )
    _upsert_package_rows(
        package_id=int(package.reliefpkg_id),
        plan_rows=plan_rows,
        actor_user_id=actor_id,
        notes=(override_reason_code or override_note) or f"RR:{reliefrqst_id}",
    )
    if not override_required or not allow_pending_override:
        _apply_stock_delta_for_rows(plan_rows, actor_user_id=actor_id, delta_sign=1, update_needs_list=False)
    _apply_package_header_updates(
        request=request,
        package=package,
        needs_list=None,
        actor_user_id=actor_id,
        status_code=PKG_STATUS_DRAFT if override_required and allow_pending_override else PKG_STATUS_PENDING,
        transport_mode=str(payload.get("transport_mode") or "").strip() or None,
    )
    return {
        "status": "PENDING_OVERRIDE_APPROVAL" if override_required and allow_pending_override else "COMMITTED",
        "reliefrqst_id": reliefrqst_id,
        "reliefpkg_id": int(package.reliefpkg_id),
        "request_tracking_no": request.tracking_no,
        "package_tracking_no": package.tracking_no,
        "override_required": override_required,
        "override_markers": override_markers,
        "allocation_lines": [{**row, "quantity": str(_quantize_qty(row["quantity"]))} for row in plan_rows],
    }


def _dispatch_detail(package: ReliefPkg) -> dict[str, Any]:
    payload = _package_detail(package)
    payload["request"] = _request_summary(_load_request(int(package.reliefrqst_id)))
    payload["waybill"] = get_waybill(int(package.reliefpkg_id)) if package.dispatch_dtime else None
    return payload


def _operations_waybill_payload(
    *,
    request: ReliefRqst,
    package: ReliefPkg,
    dispatched_rows: Sequence[Mapping[str, Any]],
    actor_id: str,
) -> dict[str, Any]:
    source_warehouse_ids = sorted({int(row["inventory_id"]) for row in dispatched_rows if row.get("inventory_id") not in (None, "")})
    source_warehouse_names, _ = data_access.get_warehouse_names(source_warehouse_ids)
    return {
        "waybill_no": f"WB-{package.tracking_no}",
        "request_tracking_no": request.tracking_no,
        "package_tracking_no": package.tracking_no,
        "agency_id": request.agency_id,
        "event_id": request.eligible_event_id,
        "event_name": data_access.get_event_name(int(request.eligible_event_id)) if request.eligible_event_id is not None else None,
        "source_warehouse_ids": source_warehouse_ids,
        "source_warehouse_names": [source_warehouse_names[warehouse_id] for warehouse_id in source_warehouse_ids if warehouse_id in source_warehouse_names],
        "destination_warehouse_id": package.to_inventory_id,
        "destination_warehouse_name": data_access.get_warehouse_name(int(package.to_inventory_id)) if package.to_inventory_id is not None else None,
        "actor_user_id": actor_id,
        "dispatch_dtime": _as_iso(package.dispatch_dtime),
        "transport_mode": package.transport_mode,
        "line_items": [
            {
                "item_id": int(row["item_id"]),
                "inventory_id": int(row["inventory_id"]),
                "batch_id": int(row["batch_id"]),
                "batch_no": row.get("batch_no"),
                "quantity": str(_quantize_qty(row["quantity"])),
                "uom_code": row.get("uom_code"),
                "source_type": row.get("source_type"),
                "source_record_id": row.get("source_record_id"),
            }
            for row in dispatched_rows
        ],
    }


def _legacy_submit_dispatch(reliefpkg_id: int, *, payload: Mapping[str, Any], actor_id: str) -> dict[str, Any]:
    package = _load_package(reliefpkg_id, for_update=True)
    execution_link = _execution_link_for_package(reliefpkg_id)
    transport_mode = str(payload.get("transport_mode") or "").strip() or None
    if execution_link is not None:
        result = compat_dispatch_package(
            LegacyWorkflowContext(
                needs_list_id=int(execution_link.needs_list_id),
                reliefrqst_id=int(execution_link.reliefrqst_id or package.reliefrqst_id),
                reliefpkg_id=int(execution_link.reliefpkg_id or reliefpkg_id),
            ),
            actor_user_id=actor_id,
            transport_mode=transport_mode,
        )
        NeedsListExecutionLink.objects.filter(needs_list_id=execution_link.needs_list_id).update(
            execution_status=NeedsListExecutionLink.ExecutionStatus.DISPATCHED,
            waybill_no=result.get("waybill_no"),
            waybill_payload_json=result.get("waybill_payload"),
            dispatched_at=timezone.now(),
            dispatched_by=actor_id,
            update_by_id=actor_id,
            update_dtime=timezone.now(),
        )
        return result

    request = _load_request(int(package.reliefrqst_id), for_update=True)
    current_status = _current_package_status(package)
    if current_status == PKG_STATUS_DISPATCHED:
        raise DispatchError("Package has already been dispatched.", code="duplicate_dispatch")
    if current_status not in {PKG_STATUS_PENDING, "C", "V"}:
        raise DispatchError(
            f"Package cannot be dispatched from status '{current_status}'.",
            code="package_not_committed",
        )
    package_rows = _selected_plan_for_package(reliefpkg_id)
    if not package_rows:
        raise DispatchError("Package contains no allocation rows to dispatch.", code="dispatch_plan_empty")
    _apply_stock_delta_for_rows(
        package_rows,
        actor_user_id=actor_id,
        delta_sign=1,
        update_needs_list=False,
        consume_stock=True,
    )
    now = timezone.now()
    package_update = ReliefPkg.objects.filter(
        reliefpkg_id=package.reliefpkg_id,
        version_nbr=package.version_nbr,
    ).update(
        status_code=PKG_STATUS_DISPATCHED,
        dispatch_dtime=now,
        transport_mode=transport_mode or package.transport_mode,
        update_by_id=actor_id,
        update_dtime=now,
        version_nbr=F("version_nbr") + 1,
    )
    if package_update != 1:
        raise OptimisticLockError("Relief package changed during dispatch.", code="package_version_mismatch")
    _advance_transfer_rows(package_rows, actor_user_id=actor_id, dispatched_at=now)
    rqst_item_table = _qualified_table("reliefrqst_item")
    for row in package_rows:
        _execute(
            f"""
            UPDATE {rqst_item_table}
            SET issue_qty = COALESCE(issue_qty, 0) + %s,
                status_code = CASE
                    WHEN COALESCE(issue_qty, 0) + %s >= request_qty THEN 'F'
                    ELSE 'P'
                END,
                action_by_id = %s,
                action_dtime = %s,
                version_nbr = version_nbr + 1
            WHERE reliefrqst_id = %s
              AND item_id = %s
            """,
            [row["quantity"], row["quantity"], actor_id, now, request.reliefrqst_id, row["item_id"]],
        )
    request_update = ReliefRqst.objects.filter(
        reliefrqst_id=request.reliefrqst_id,
        version_nbr=request.version_nbr,
    ).update(
        status_code=_request_completion_status(int(request.reliefrqst_id)),
        review_by_id=request.review_by_id or actor_id,
        review_dtime=request.review_dtime or now,
        action_by_id=actor_id,
        action_dtime=now,
        status_reason_desc=None,
        version_nbr=F("version_nbr") + 1,
    )
    if request_update != 1:
        raise OptimisticLockError("Relief request changed during dispatch.", code="request_version_mismatch")
    refreshed_package = _load_package(reliefpkg_id)
    waybill_payload = _operations_waybill_payload(
        request=request,
        package=refreshed_package,
        dispatched_rows=package_rows,
        actor_id=actor_id,
    )
    return {
        "status": "DISPATCHED",
        "reliefrqst_id": int(request.reliefrqst_id),
        "reliefpkg_id": int(refreshed_package.reliefpkg_id),
        "request_tracking_no": request.tracking_no,
        "package_tracking_no": refreshed_package.tracking_no,
        "waybill_no": waybill_payload["waybill_no"],
        "waybill_payload": waybill_payload,
        "dispatched_rows": [{**row, "quantity": str(_quantize_qty(row["quantity"]))} for row in package_rows],
    }


def _legacy_get_waybill(reliefpkg_id: int) -> dict[str, Any]:
    package = _load_package(reliefpkg_id)
    execution_link = _execution_link_for_package(reliefpkg_id)
    if execution_link is not None and execution_link.waybill_payload_json:
        return {
            "waybill_no": execution_link.waybill_no,
            "waybill_payload": execution_link.waybill_payload_json,
            "persisted": True,
            "compatibility_bridge": True,
        }
    if package.dispatch_dtime is None:
        raise OperationValidationError({"waybill": "Waybill not available."})
    request = _load_request(int(package.reliefrqst_id))
    payload = _operations_waybill_payload(
        request=request,
        package=package,
        dispatched_rows=_load_package_plan_with_source_info(int(package.reliefpkg_id)),
        actor_id=str(package.update_by_id or package.verify_by_id or "system"),
    )
    return {
        "waybill_no": payload["waybill_no"],
        "waybill_payload": payload,
        "persisted": False,
        "compatibility_bridge": False,
    }


def _legacy_get_request(reliefrqst_id: int, *, actor_id: str | None = None) -> dict[str, Any]:
    return _request_detail(_legacy_helper("_load_request")(reliefrqst_id))


@transaction.atomic
def _legacy_create_request(
    *,
    payload: Mapping[str, Any],
    actor_id: str,
    tenant_context: TenantContext,
    permissions: Iterable[str] | None = None,
) -> dict[str, Any]:
    normalized = _validate_request_payload(payload)
    decision = operations_policy.validate_relief_request_agency_selection(
        agency_id=int(normalized["agency_id"]),
        tenant_context=tenant_context,
    )
    operations_policy.enforce_relief_request_origin_mode_permission(
        decision=decision,
        permissions=permissions or (),
    )
    reliefrqst_id = _next_int_id("reliefrqst", "reliefrqst_id")
    now = timezone.now()
    ReliefRqst.objects.create(
        reliefrqst_id=reliefrqst_id,
        agency_id=normalized["agency_id"],
        request_date=now.date(),
        tracking_no=_tracking_no("RQ", reliefrqst_id),
        eligible_event_id=normalized.get("eligible_event_id"),
        urgency_ind=normalized["urgency_ind"],
        rqst_notes_text=normalized.get("rqst_notes_text"),
        status_code=STATUS_DRAFT,
        create_by_id=actor_id,
        create_dtime=now,
        version_nbr=1,
    )
    if normalized["items"]:
        _upsert_request_items(reliefrqst_id, normalized["items"])
    try:
        return get_request(reliefrqst_id, actor_id=actor_id)
    except TypeError:
        return _legacy_get_request(reliefrqst_id, actor_id=actor_id)


@transaction.atomic
def _legacy_update_request(
    reliefrqst_id: int,
    *,
    payload: Mapping[str, Any],
    actor_id: str,
    tenant_context: TenantContext,
    permissions: Iterable[str] | None = None,
) -> dict[str, Any]:
    request = _legacy_helper("_load_request")(reliefrqst_id, for_update=True)
    if int(request.status_code) != STATUS_DRAFT:
        raise OperationValidationError({"status": "Only draft requests can be updated."})
    normalized = _validate_request_payload(payload, partial=True, existing_request=request)
    target_agency_id = int(normalized["agency_id"]) if "agency_id" in normalized else int(request.agency_id)
    decision = operations_policy.validate_relief_request_agency_selection(
        agency_id=target_agency_id,
        tenant_context=tenant_context,
    )
    operations_policy.enforce_relief_request_origin_mode_permission(
        decision=decision,
        permissions=permissions or (),
    )
    if "agency_id" in normalized:
        request.agency_id = normalized["agency_id"]
    if "urgency_ind" in normalized:
        request.urgency_ind = normalized["urgency_ind"]
    if "eligible_event_id" in normalized:
        request.eligible_event_id = normalized["eligible_event_id"]
    update_fields = [
        "agency_id",
        "urgency_ind",
        "eligible_event_id",
        "version_nbr",
    ]
    if "rqst_notes_text" in normalized:
        request.rqst_notes_text = normalized["rqst_notes_text"]
        update_fields.append("rqst_notes_text")
    request.version_nbr = int(request.version_nbr or 0) + 1
    request.save(update_fields=update_fields)
    if normalized["items"]:
        _upsert_request_items(reliefrqst_id, normalized["items"])
    try:
        return get_request(reliefrqst_id, actor_id=actor_id)
    except TypeError:
        return _legacy_get_request(reliefrqst_id, actor_id=actor_id)


@transaction.atomic
def _legacy_submit_request(reliefrqst_id: int, *, actor_id: str, tenant_context: TenantContext) -> dict[str, Any]:
    request = _legacy_helper("_load_request")(reliefrqst_id, for_update=True)
    if int(request.status_code) != STATUS_DRAFT:
        raise OperationValidationError({"status": "Only draft requests can be submitted."})
    operations_policy.validate_relief_request_agency_selection(
        agency_id=int(request.agency_id),
        tenant_context=tenant_context,
    )
    if not _legacy_helper("_request_item_rows_for_allocation")(reliefrqst_id):
        raise OperationValidationError({"items": "At least one item is required before submission."})
    request.status_code = STATUS_AWAITING_APPROVAL
    request.version_nbr = int(request.version_nbr or 0) + 1
    request.save(update_fields=["status_code", "version_nbr"])
    try:
        return get_request(reliefrqst_id, actor_id=actor_id)
    except TypeError:
        return _legacy_get_request(reliefrqst_id, actor_id=actor_id)


def _legacy_get_package_allocation_options(
    reliefrqst_id: int,
    *,
    source_warehouse_id: int | None = None,
    tenant_context: TenantContext | None = None,
) -> dict[str, Any]:
    execution_link = _execution_link_for_request(reliefrqst_id)
    if execution_link is not None:
        return _reshape_compat_options(
            compat_get_allocation_options(int(execution_link.needs_list_id)),
            reliefrqst_id,
        )

    warehouse_ids = [source_warehouse_id] if source_warehouse_id is not None else _resolve_candidate_warehouse_ids(reliefrqst_id)
    warehouse_ids = [warehouse_id for warehouse_id in warehouse_ids if warehouse_id]
    if not warehouse_ids:
        raise OperationValidationError(
            {"source_warehouse_id": "source_warehouse_id is required when no needs-list compatibility bridge exists."}
        )

    item_rows = _request_item_rows_for_allocation(reliefrqst_id)
    primary_warehouse_id = int(warehouse_ids[0])
    committed_warehouses_by_item = _draft_committed_warehouses_by_item(reliefrqst_id)
    draft_allocations_by_item = _draft_allocations_by_item(reliefrqst_id)
    results: list[dict[str, Any]] = []
    for row in item_rows:
        item_id = int(row["item_id"])
        committed_for_item = committed_warehouses_by_item.get(item_id, [])
        additional_warehouse_ids = [
            warehouse_id
            for warehouse_id in committed_for_item
            if int(warehouse_id) != primary_warehouse_id
        ]
        results.append(
            _build_item_allocation_response(
                reliefrqst_id,
                item_id,
                source_warehouse_id=primary_warehouse_id,
                tenant_context=tenant_context,
                draft_allocations=draft_allocations_by_item.get(item_id),
                include_draft_metrics=True,
                additional_warehouse_ids=additional_warehouse_ids or None,
            )
        )
    try:
        request_payload = _request_summary(_legacy_helper("_load_request")(reliefrqst_id))
    except (AttributeError, DatabaseError, ReliefRqst.DoesNotExist):
        request_payload = {"reliefrqst_id": int(reliefrqst_id)}
    return {"request": request_payload, "items": results}


def _legacy_get_item_allocation_options(
    reliefrqst_id: int,
    item_id: int,
    *,
    source_warehouse_id: int,
    tenant_context: TenantContext | None = None,
    draft_allocations: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    return _build_item_allocation_response(
        reliefrqst_id,
        item_id,
        source_warehouse_id=source_warehouse_id,
        tenant_context=tenant_context,
        draft_allocations=draft_allocations,
        include_draft_metrics=False,
    )


def _legacy_get_item_allocation_preview(
    reliefrqst_id: int,
    item_id: int,
    *,
    source_warehouse_id: int,
    tenant_context: TenantContext | None = None,
    draft_allocations: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    return _build_item_allocation_response(
        reliefrqst_id,
        item_id,
        source_warehouse_id=source_warehouse_id,
        tenant_context=tenant_context,
        draft_allocations=draft_allocations,
        include_draft_metrics=True,
    )


def _legacy_save_package(
    reliefrqst_id: int,
    *,
    payload: Mapping[str, Any],
    actor_id: str,
    actor_roles: Iterable[str] | None = None,
) -> dict[str, Any]:
    return _save_package_allocation(
        reliefrqst_id,
        payload=payload,
        actor_id=actor_id,
        actor_roles=actor_roles,
        allow_pending_override=True,
    )


def _legacy_approve_override(
    reliefrqst_id: int,
    *,
    payload: Mapping[str, Any],
    actor_id: str,
    actor_roles: Iterable[str] | None,
) -> dict[str, Any]:
    execution_link = _execution_link_for_request(reliefrqst_id)
    if execution_link is not None:
        return compat_approve_override(
            LegacyWorkflowContext(
                needs_list_id=int(execution_link.needs_list_id),
                reliefrqst_id=int(execution_link.reliefrqst_id or reliefrqst_id),
                reliefpkg_id=int(execution_link.reliefpkg_id),
                submitted_by=execution_link.override_requested_by or execution_link.needs_list.submitted_by,
            ),
            _normalized_allocations(payload),
            actor_user_id=actor_id,
            supervisor_user_id=actor_id,
            supervisor_role_codes=actor_roles,
            override_reason_code=str(payload.get("override_reason_code") or "").strip(),
            override_note=str(payload.get("override_note") or "").strip(),
            submitter_user_id=execution_link.override_requested_by or execution_link.needs_list.submitted_by,
        )
    request = _load_request(reliefrqst_id)
    package = _current_package_for_request(reliefrqst_id)
    allocator_user_id = str(request.create_by_id or (package.create_by_id if package is not None else actor_id))
    return _save_package_allocation(
        reliefrqst_id,
        payload=payload,
        actor_id=actor_id,
        actor_roles=actor_roles,
        allow_pending_override=False,
        supervisor_user_id=actor_id,
        supervisor_role_codes=actor_roles,
        override_submitter_user_id=allocator_user_id,
    )


def _bind_legacy_service_facade() -> None:
    bindings = {
        "STATUS_DRAFT": STATUS_DRAFT,
        "STATUS_AWAITING_APPROVAL": STATUS_AWAITING_APPROVAL,
        "STATUS_CANCELLED": STATUS_CANCELLED,
        "STATUS_SUBMITTED": STATUS_SUBMITTED,
        "STATUS_DENIED": STATUS_DENIED,
        "STATUS_PART_FILLED": STATUS_PART_FILLED,
        "STATUS_CLOSED": STATUS_CLOSED,
        "STATUS_FILLED": STATUS_FILLED,
        "STATUS_INELIGIBLE": STATUS_INELIGIBLE,
        "PKG_STATUS_DRAFT": PKG_STATUS_DRAFT,
        "PKG_STATUS_PENDING": PKG_STATUS_PENDING,
        "PKG_STATUS_DISPATCHED": PKG_STATUS_DISPATCHED,
        "PKG_STATUS_COMPLETED": PKG_STATUS_COMPLETED,
        "_as_iso": _as_iso,
        "_tracking_no": _tracking_no,
        "_quantize_qty": _quantize_qty,
        "_next_int_id": _next_int_id,
        "_load_request": _load_request,
        "_load_package": _load_package,
        "_current_package_for_request": _current_package_for_request,
        "_current_package_status": _current_package_status,
        "_request_items": _request_items,
        "_request_item_rows_for_allocation": _request_item_rows_for_allocation,
        "_request_summary": _request_summary,
        "_package_summary": _package_summary,
        "_package_detail": _package_detail,
        "_selected_plan_for_package": _selected_plan_for_package,
        "_apply_stock_delta_for_rows": _apply_stock_delta_for_rows,
        "get_request": _legacy_get_request,
        "create_request": _legacy_create_request,
        "update_request": _legacy_update_request,
        "submit_request": _legacy_submit_request,
        "get_package_allocation_options": _legacy_get_package_allocation_options,
        "get_item_allocation_options": _legacy_get_item_allocation_options,
        "get_item_allocation_preview": _legacy_get_item_allocation_preview,
        "save_package": _legacy_save_package,
        "approve_override": _legacy_approve_override,
        "submit_dispatch": _legacy_submit_dispatch,
        "get_waybill": _legacy_get_waybill,
    }
    _LEGACY_FACADE_DEFAULTS.clear()
    _LEGACY_FACADE_DEFAULTS.update(bindings)
    for name, value in bindings.items():
        setattr(legacy_service, name, value)


def _legacy_helper(name: str):
    module_helper = globals()[name]
    facade_helper = getattr(legacy_service, name, None)
    default_helper = _LEGACY_FACADE_DEFAULTS.get(name)
    if default_helper is not None:
        if module_helper is not default_helper:
            return module_helper
        if facade_helper is not None and facade_helper is not default_helper:
            return facade_helper
        return module_helper
    if facade_helper is not None:
        return facade_helper
    return module_helper


def _legacy_request_is_syncable(request: Any) -> bool:
    required_attrs = (
        "reliefrqst_id",
        "tracking_no",
        "agency_id",
        "eligible_event_id",
        "request_date",
        "urgency_ind",
        "rqst_notes_text",
        "create_by_id",
        "create_dtime",
        "review_by_id",
        "review_dtime",
        "status_code",
    )
    return all(hasattr(request, attr) for attr in required_attrs)


def _compat_request_response(
    reliefrqst_id: int,
    *,
    actor_id: str,
    tenant_context: TenantContext,
    fallback: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        return get_request(
            int(reliefrqst_id),
            actor_id=actor_id,
            tenant_context=tenant_context,
            actor_roles=(),
        )
    except TypeError:
        try:
            return legacy_service.get_request(int(reliefrqst_id), actor_id=actor_id)
        except TypeError:
            pass
    except (AttributeError, DatabaseError, ReliefRqst.DoesNotExist):
        pass
    if fallback is not None:
        return dict(fallback)
    return {"reliefrqst_id": int(reliefrqst_id)}


_bind_legacy_service_facade()


def list_requests(
    *,
    filter_key: str | None = None,
    actor_id: str | None = None,
    tenant_context: TenantContext,
    actor_roles: Iterable[str] | None = None,
) -> dict[str, Any]:
    actor_id = _require_actor_id(actor_id)
    requested_statuses = REQUEST_FILTERS.get(str(filter_key or "").lower())
    results: list[dict[str, Any]] = []
    for request in ReliefRqst.objects.order_by("-create_dtime", "-reliefrqst_id").iterator():
        request_probe = _request_access_probe_from_legacy(request)
        request_probe.status_code = _request_status_from_legacy(request)
        try:
            _ensure_request_access(
                request_probe,
                actor_id=actor_id,
                actor_roles=actor_roles or (),
                tenant_context=tenant_context,
            )
        except OperationValidationError:
            continue
        if requested_statuses and request_probe.status_code not in requested_statuses:
            continue
        request_record = _sync_operations_request(request, actor_id=actor_id)
        _ensure_request_access(request_record, actor_id=actor_id, actor_roles=actor_roles or (), tenant_context=tenant_context)
        results.append(_request_summary_payload(request, request_record))
        if len(results) >= 200:
            break
    return {"results": results}


def get_request(reliefrqst_id: int, *, actor_id: str | None = None, tenant_context: TenantContext, actor_roles: Iterable[str] | None = None) -> dict[str, Any]:
    actor_id = _require_actor_id(actor_id)
    request = _legacy_helper("_load_request")(reliefrqst_id)
    _ensure_request_access(
        _request_access_probe_from_legacy(request),
        actor_id=actor_id,
        actor_roles=actor_roles or (),
        tenant_context=tenant_context,
    )
    request_record = _sync_operations_request(request, actor_id=actor_id)
    _ensure_request_access(request_record, actor_id=actor_id, actor_roles=actor_roles or (), tenant_context=tenant_context)
    payload = legacy_service.get_request(reliefrqst_id, actor_id=actor_id)
    payload.update(_request_summary_payload(request, request_record))
    payload["packages"] = []
    for package in ReliefPkg.objects.filter(reliefrqst_id=reliefrqst_id).order_by("-reliefpkg_id"):
        package_record = _sync_operations_package(package, request_record=request_record, actor_id=actor_id)
        payload["packages"].append(_package_summary_payload(package, package_record))
    return payload


@transaction.atomic
def create_request(
    *,
    payload: Mapping[str, Any],
    actor_id: str,
    tenant_context: TenantContext,
    permissions: Iterable[str] | None = None,
) -> dict[str, Any]:
    mutable_payload = dict(payload)
    if mutable_payload.get("beneficiary_agency_id") not in (None, "") and mutable_payload.get("agency_id") in (None, ""):
        mutable_payload["agency_id"] = mutable_payload.get("beneficiary_agency_id")
    agency_id = _parse_int_or_raise(mutable_payload.get("agency_id"), "agency_id")
    if agency_id is None:
        raise OperationValidationError({"agency_id": "agency_id or beneficiary_agency_id is required."})
    raw_source_needs_list_id = mutable_payload.get("source_needs_list_id", _UNSET)
    source_needs_list_id = (
        _parse_int_or_raise(raw_source_needs_list_id, "source_needs_list_id")
        if raw_source_needs_list_id is not _UNSET
        else _UNSET
    )
    requesting_agency_id = _parse_int_or_raise(mutable_payload.get("requesting_agency_id"), "requesting_agency_id")
    decision: operations_policy.ReliefRequestWriteDecision | None = None
    if getattr(legacy_service, "create_request", None) is not _LEGACY_FACADE_DEFAULTS.get("create_request"):
        decision = operations_policy.validate_relief_request_agency_selection(
            agency_id=agency_id,
            tenant_context=tenant_context,
        )
    result = legacy_service.create_request(
        payload=mutable_payload,
        actor_id=actor_id,
        tenant_context=tenant_context,
        permissions=permissions,
    )
    try:
        request = _legacy_helper("_load_request")(int(result["reliefrqst_id"]))
    except (DatabaseError, ReliefRqst.DoesNotExist):
        return _compat_request_response(
            int(result["reliefrqst_id"]),
            actor_id=actor_id,
            tenant_context=tenant_context,
            fallback=result,
        )
    if _legacy_request_is_syncable(request):
        if decision is None:
            decision = operations_policy.validate_relief_request_agency_selection(
                agency_id=agency_id,
                tenant_context=tenant_context,
            )
        _sync_operations_request(
            request,
            actor_id=actor_id,
            decision=decision,
            status_code=REQUEST_STATUS_DRAFT,
            source_needs_list_id=source_needs_list_id,
            requesting_agency_id=requesting_agency_id,
        )
    return _compat_request_response(
        int(result["reliefrqst_id"]),
        actor_id=actor_id,
        tenant_context=tenant_context,
        fallback=result,
    )


@transaction.atomic
def update_request(
    reliefrqst_id: int,
    *,
    payload: Mapping[str, Any],
    actor_id: str,
    tenant_context: TenantContext,
    permissions: Iterable[str] | None = None,
) -> dict[str, Any]:
    mutable_payload = dict(payload)
    if mutable_payload.get("beneficiary_agency_id") not in (None, "") and mutable_payload.get("agency_id") in (None, ""):
        mutable_payload["agency_id"] = mutable_payload.get("beneficiary_agency_id")
    raw_source_needs_list_id = mutable_payload.get("source_needs_list_id", _UNSET)
    source_needs_list_id = (
        _parse_int_or_raise(raw_source_needs_list_id, "source_needs_list_id")
        if raw_source_needs_list_id is not _UNSET
        else _UNSET
    )
    requesting_agency_id = _parse_int_or_raise(mutable_payload.get("requesting_agency_id"), "requesting_agency_id")
    current_request = _legacy_helper("_load_request")(reliefrqst_id)
    effective_agency_raw = mutable_payload.get("agency_id", current_request.agency_id)
    agency_id = _parse_int_or_raise(effective_agency_raw, "agency_id")
    if agency_id is None:
        raise OperationValidationError({"agency_id": "agency_id is required."})
    decision: operations_policy.ReliefRequestWriteDecision | None = None
    if getattr(legacy_service, "update_request", None) is not _LEGACY_FACADE_DEFAULTS.get("update_request"):
        decision = operations_policy.validate_relief_request_agency_selection(
            agency_id=agency_id,
            tenant_context=tenant_context,
        )
    result = legacy_service.update_request(
        reliefrqst_id,
        payload=mutable_payload,
        actor_id=actor_id,
        tenant_context=tenant_context,
        permissions=permissions,
    )
    request = _legacy_helper("_load_request")(reliefrqst_id)
    if _legacy_request_is_syncable(request):
        if decision is None:
            decision = operations_policy.validate_relief_request_agency_selection(
                agency_id=agency_id,
                tenant_context=tenant_context,
            )
        _sync_operations_request(
            request,
            actor_id=actor_id,
            decision=decision,
            source_needs_list_id=source_needs_list_id,
            requesting_agency_id=requesting_agency_id,
        )
    return _compat_request_response(
        int(result["reliefrqst_id"]),
        actor_id=actor_id,
        tenant_context=tenant_context,
        fallback=result,
    )


@transaction.atomic
def submit_request(
    reliefrqst_id: int,
    *,
    actor_id: str,
    tenant_context: TenantContext,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    idempotency = _begin_idempotent_write(
        endpoint="request_submit",
        actor_id=actor_id,
        tenant_context=tenant_context,
        resource_id=reliefrqst_id,
        idempotency_key=idempotency_key,
    )
    if idempotency.cached_result is not None:
        return idempotency.cached_result
    legacy_service.submit_request(reliefrqst_id, actor_id=actor_id, tenant_context=tenant_context)
    request = _legacy_helper("_load_request")(reliefrqst_id)
    if _legacy_request_is_syncable(request):
        request_record = _sync_operations_request(request, actor_id=actor_id, status_code=REQUEST_STATUS_SUBMITTED)
        request_record.submitted_by_id = actor_id
        request_record.submitted_at = timezone.now()
        request_record.status_code = REQUEST_STATUS_UNDER_ELIGIBILITY_REVIEW
        request_record.update_by_id = actor_id
        request_record.update_dtime = timezone.now()
        request_record.version_nbr = int(request_record.version_nbr or 0) + 1
        request_record.save(update_fields=["submitted_by_id", "submitted_at", "status_code", "update_by_id", "update_dtime", "version_nbr"])
        record_status_transition(
            entity_type=ENTITY_REQUEST,
            entity_id=reliefrqst_id,
            from_status=REQUEST_STATUS_SUBMITTED,
            to_status=REQUEST_STATUS_UNDER_ELIGIBILITY_REVIEW,
            actor_id=actor_id,
        )
        assign_roles_to_queue(
            queue_code=QUEUE_CODE_ELIGIBILITY,
            entity_type=ENTITY_REQUEST,
            entity_id=reliefrqst_id,
            role_codes=ELIGIBILITY_ROLE_CODES,
        )
        create_role_notifications(
            event_code=EVENT_REQUEST_SUBMITTED,
            entity_type=ENTITY_REQUEST,
            entity_id=reliefrqst_id,
            message_text=f"Relief request {request.tracking_no} is ready for eligibility review.",
            role_codes=ELIGIBILITY_ROLE_CODES,
            queue_code=QUEUE_CODE_ELIGIBILITY,
        )
    result = _compat_request_response(
        reliefrqst_id,
        actor_id=actor_id,
        tenant_context=tenant_context,
    )
    _cache_idempotent_response_after_commit(
        idempotency.cache_key,
        result,
        reservation_key=idempotency.reservation_key,
        reservation_token=idempotency.reservation_token,
    )
    return result


def list_eligibility_queue(*, actor_id: str | None = None, actor_roles: Iterable[str] | None = None, tenant_context: TenantContext) -> dict[str, Any]:
    actor_id = _require_actor_id(actor_id)
    normalized_roles = _require_roles(actor_roles, ELIGIBILITY_ROLE_CODES, message="Only eligibility approvers may view this queue.")
    results: list[dict[str, Any]] = []
    seen_request_ids: set[int] = set()

    for request_record in OperationsReliefRequest.objects.filter(
        status_code__in=ELIGIBILITY_VISIBLE_REQUEST_STATUSES,
    ).order_by("-request_date", "-relief_request_id").iterator():
        if not _can_read_eligibility_request(
            request_record,
            actor_id=actor_id,
            actor_roles=normalized_roles,
            tenant_context=tenant_context,
        ):
            continue
        try:
            request = legacy_service._load_request(int(request_record.relief_request_id))
        except ReliefRqst.DoesNotExist:
            continue
        refreshed_record = _sync_operations_request(request, actor_id=actor_id)
        if refreshed_record.status_code not in ELIGIBILITY_VISIBLE_REQUEST_STATUSES:
            continue
        results.append(_request_summary_payload(request, refreshed_record))
        seen_request_ids.add(int(request.reliefrqst_id))
        if len(results) >= 200:
            return {"results": results}

    for request in ReliefRqst.objects.filter(status_code=legacy_service.STATUS_AWAITING_APPROVAL).order_by("-request_date", "-reliefrqst_id").iterator():
        if int(request.reliefrqst_id) in seen_request_ids:
            continue
        try:
            _ensure_request_access(
                _request_access_probe_from_legacy(request),
                actor_id=actor_id,
                actor_roles=normalized_roles,
                tenant_context=tenant_context,
            )
        except OperationValidationError:
            continue
        request_record = _sync_operations_request(request, actor_id=actor_id, status_code=REQUEST_STATUS_UNDER_ELIGIBILITY_REVIEW)
        results.append(_request_summary_payload(request, request_record))
        if len(results) >= 200:
            break
    return {"results": results}


def get_eligibility_request(reliefrqst_id: int, *, actor_id: str | None = None, actor_roles: Iterable[str] | None = None, tenant_context: TenantContext) -> dict[str, Any]:
    actor_id = _require_actor_id(actor_id)
    normalized_roles = _require_roles(actor_roles, ELIGIBILITY_ROLE_CODES, message="Only eligibility approvers may review requests.")
    request = legacy_service._load_request(reliefrqst_id)
    request_probe = _request_access_probe_from_legacy(request)
    if not _can_read_eligibility_request(
        request_probe,
        actor_id=actor_id,
        actor_roles=normalized_roles,
        tenant_context=tenant_context,
    ):
        raise OperationValidationError({"scope": "Request is outside the active tenant or workflow assignment scope."})
    request_record = _sync_operations_request(request, actor_id=actor_id)

    payload = legacy_service.get_request(reliefrqst_id, actor_id=actor_id)
    payload.update(_request_summary_payload(request, request_record))
    payload["packages"] = []
    for package in ReliefPkg.objects.filter(reliefrqst_id=reliefrqst_id).order_by("-reliefpkg_id"):
        package_record = _sync_operations_package(package, request_record=request_record, actor_id=actor_id)
        payload["packages"].append(_package_summary_payload(package, package_record))
    decision = OperationsEligibilityDecision.objects.filter(relief_request_id=reliefrqst_id).first()
    payload["decision_made"] = decision is not None
    payload["can_edit"] = payload.get("status_code") == REQUEST_STATUS_UNDER_ELIGIBILITY_REVIEW and decision is None
    if decision is not None:
        payload["eligibility_decision"] = {
            "decision_code": decision.decision_code,
            "decision_reason": decision.decision_reason,
            "decided_by_user_id": decision.decided_by_user_id,
            "decided_by_role_code": decision.decided_by_role_code,
            "decided_at": legacy_service._as_iso(decision.decided_at),
        }
    return payload


@transaction.atomic
def submit_eligibility_decision(
    reliefrqst_id: int,
    *,
    payload: Mapping[str, Any],
    actor_id: str,
    actor_roles: Iterable[str] | None,
    tenant_context: TenantContext,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    idempotency = _begin_idempotent_write(
        endpoint="eligibility_decision",
        actor_id=actor_id,
        tenant_context=tenant_context,
        resource_id=reliefrqst_id,
        idempotency_key=idempotency_key,
    )
    if idempotency.cached_result is not None:
        return idempotency.cached_result
    normalized_roles = _require_roles(actor_roles, ELIGIBILITY_ROLE_CODES, message="Only eligibility approvers may decide requests.")
    request = legacy_service._load_request(reliefrqst_id, for_update=True)
    request_record = _sync_operations_request(request, actor_id=actor_id, status_code=REQUEST_STATUS_UNDER_ELIGIBILITY_REVIEW)
    _ensure_request_access(request_record, actor_id=actor_id, actor_roles=actor_roles or (), tenant_context=tenant_context, write=True)
    if OperationsEligibilityDecision.objects.filter(relief_request_id=reliefrqst_id).exists():
        raise OperationValidationError({"status": "Eligibility decision already recorded."})
    decision = str(payload.get("decision") or "").strip().upper()
    decision_code = {"Y": "APPROVED", "N": "INELIGIBLE"}.get(decision, decision)
    if decision_code not in {"APPROVED", "INELIGIBLE", "REJECTED"}:
        raise OperationValidationError({"decision": "Decision must be APPROVED, REJECTED, INELIGIBLE, Y, or N."})
    decision_reason = str(payload.get("reason") or payload.get("decision_reason") or "").strip() or None
    if decision_code in {"INELIGIBLE", "REJECTED"} and not decision_reason:
        raise OperationValidationError({"reason": "Reason is required for non-approval decisions."})
    on_behalf_agency_id = None
    raw_requesting_agency = payload.get("requesting_agency_id")
    if raw_requesting_agency not in (None, ""):
        try:
            on_behalf_agency_id = int(raw_requesting_agency)
        except (TypeError, ValueError):
            raise OperationValidationError(
                {"requesting_agency_id": f"invalid requesting_agency_id: {raw_requesting_agency!r}"}
            ) from None
    now = timezone.now()
    request.review_by_id = actor_id
    request.review_dtime = now
    request.version_nbr = int(request.version_nbr or 0) + 1
    update_fields = [
        "review_by_id",
        "review_dtime",
        "action_by_id",
        "action_dtime",
        "status_code",
        "status_reason_desc",
        "version_nbr",
    ]
    if decision_code == "APPROVED":
        # Legacy reliefrqst constraints require action_* fields to remain null
        # until the request reaches a terminal decision status.
        request.action_by_id = None
        request.action_dtime = None
        request.status_code = legacy_service.STATUS_SUBMITTED
        request.status_reason_desc = None
        next_status = REQUEST_STATUS_APPROVED_FOR_FULFILLMENT
    elif decision_code == "REJECTED":
        request.action_by_id = actor_id
        request.action_dtime = now
        request.status_code = legacy_service.STATUS_DENIED
        request.status_reason_desc = decision_reason
        next_status = REQUEST_STATUS_REJECTED
    else:
        request.action_by_id = actor_id
        request.action_dtime = now
        request.status_code = legacy_service.STATUS_INELIGIBLE
        request.status_reason_desc = decision_reason
        next_status = REQUEST_STATUS_INELIGIBLE
    request.save(update_fields=update_fields)
    eligibility_decision = OperationsEligibilityDecision.objects.create(
        relief_request_id=reliefrqst_id,
        decision_code=decision_code,
        decision_reason=decision_reason,
        decided_by_user_id=actor_id,
        decided_by_role_code=next(
            (role for role in normalized_roles if role in set(ELIGIBILITY_ROLE_CODES)),
            ROLE_SYSTEM_ADMINISTRATOR,
        ),
        decided_at=now,
    )
    request_record = _sync_operations_request(
        request,
        actor_id=actor_id,
        status_code=next_status,
        requesting_agency_id=on_behalf_agency_id,
    )
    request_record.reviewed_by_id = actor_id
    request_record.reviewed_at = now
    request_record.save(update_fields=["reviewed_by_id", "reviewed_at"])
    complete_queue_assignments(entity_type=ENTITY_REQUEST, entity_id=reliefrqst_id, queue_code=QUEUE_CODE_ELIGIBILITY, actor_id=actor_id)
    if decision_code == "APPROVED":
        fulfillment_tenant_id = _resolve_request_level_fulfillment_tenant_id()
        assign_roles_to_queue(
            queue_code=QUEUE_CODE_FULFILLMENT,
            entity_type=ENTITY_REQUEST,
            entity_id=reliefrqst_id,
            role_codes=FULFILLMENT_ROLE_CODES,
            tenant_id=fulfillment_tenant_id,
        )
        create_role_notifications(
            event_code=EVENT_REQUEST_APPROVED,
            entity_type=ENTITY_REQUEST,
            entity_id=reliefrqst_id,
            message_text=f"Relief request {request.tracking_no} is approved for fulfillment.",
            role_codes=FULFILLMENT_ROLE_CODES,
            tenant_id=fulfillment_tenant_id,
            queue_code=QUEUE_CODE_FULFILLMENT,
        )
    else:
        create_user_notification(
            event_code=EVENT_REQUEST_REJECTED if decision_code == "REJECTED" else EVENT_REQUEST_INELIGIBLE,
            entity_type=ENTITY_REQUEST,
            entity_id=reliefrqst_id,
            recipient_user_id=request.create_by_id or actor_id,
            tenant_id=request_record.requesting_tenant_id,
            message_text=f"Relief request {request.tracking_no} was marked {decision_code.lower()}.",
        )
    # Build the response from the already-authorized request state in this
    # transaction. Re-reading through get_eligibility_request() after closing
    # the eligibility queue can invalidate access for cross-tenant reviewers
    # whose authority comes from the queue assignment itself.
    payload = legacy_service.get_request(reliefrqst_id, actor_id=actor_id)
    payload.update(_request_summary_payload(request, request_record))
    payload["packages"] = []
    for package in ReliefPkg.objects.filter(reliefrqst_id=reliefrqst_id).order_by("-reliefpkg_id"):
        package_record = _sync_operations_package(package, request_record=request_record, actor_id=actor_id)
        payload["packages"].append(_package_summary_payload(package, package_record))
    payload["decision_made"] = True
    payload["can_edit"] = False
    payload["eligibility_decision"] = {
        "decision_code": eligibility_decision.decision_code,
        "decision_reason": eligibility_decision.decision_reason,
        "decided_by_user_id": eligibility_decision.decided_by_user_id,
        "decided_by_role_code": eligibility_decision.decided_by_role_code,
        "decided_at": legacy_service._as_iso(eligibility_decision.decided_at),
    }
    _cache_idempotent_response_after_commit(
        idempotency.cache_key,
        payload,
        reservation_key=idempotency.reservation_key,
        reservation_token=idempotency.reservation_token,
    )
    return payload


def list_packages(*, actor_id: str | None = None, actor_roles: Iterable[str] | None = None, tenant_context: TenantContext) -> dict[str, Any]:
    actor_id = _require_actor_id(actor_id)
    _require_roles(actor_roles, FULFILLMENT_ROLE_CODES, message="Only fulfillment roles may view this queue.")
    queue_list = list(
        actor_queue_queryset(actor_id=actor_id, actor_roles=actor_roles or (), tenant_context=tenant_context)
        .filter(queue_code__in=[QUEUE_CODE_FULFILLMENT, QUEUE_CODE_OVERRIDE], entity_type=ENTITY_REQUEST)
        .values_list("entity_id", flat=True)
    )
    status_list = list(
        OperationsReliefRequest.objects.filter(
            status_code__in=list(FULFILLMENT_VISIBLE_REQUEST_STATUSES)
        )
        .order_by("-request_date", "-relief_request_id")
        .values_list("relief_request_id", flat=True)[:200]
    )
    request_ids: list[int] = []
    seen_request_ids: set[int] = set()
    for request_id in queue_list + status_list:
        request_id = int(request_id)
        if request_id in seen_request_ids:
            continue
        request_ids.append(request_id)
        seen_request_ids.add(request_id)
        if len(request_ids) >= 200:
            break
    results: list[dict[str, Any]] = []
    for reliefrqst_id in request_ids:
        try:
            request = legacy_service._load_request(int(reliefrqst_id))
        except ReliefRqst.DoesNotExist:
            continue
        request_probe = _request_access_probe_from_legacy(request)
        try:
            _ensure_fulfillment_request_access(
                request_probe,
                actor_id=actor_id,
                actor_roles=actor_roles or (),
                tenant_context=tenant_context,
            )
        except OperationValidationError:
            continue
        request_record = _sync_operations_request(request, actor_id=actor_id)
        current_package = legacy_service._current_package_for_request(int(request.reliefrqst_id))
        row = _request_summary_payload(request, request_record)
        if current_package is not None:
            package_record = _sync_operations_package(current_package, request_record=request_record, actor_id=actor_id)
            row["current_package"] = _package_summary_payload(current_package, package_record)
        else:
            row["current_package"] = None
        results.append(row)
    return {"results": results}


def get_package(reliefrqst_id: int, *, actor_id: str | None = None, actor_roles: Iterable[str] | None = None, tenant_context: TenantContext) -> dict[str, Any]:
    actor_id = _require_actor_id(actor_id)
    request = legacy_service._load_request(reliefrqst_id)
    request_probe = _request_access_probe_from_legacy(request)
    _ensure_fulfillment_request_access(request_probe, actor_id=actor_id, actor_roles=actor_roles or (), tenant_context=tenant_context)
    request_record = _sync_operations_request(request, actor_id=actor_id)
    package = legacy_service._current_package_for_request(reliefrqst_id)
    package_record = _sync_operations_package(package, request_record=request_record, actor_id=actor_id) if package is not None else None
    payload = {
        "request": _request_summary_payload(request, request_record),
        "package": _package_summary_payload(package, package_record) if package is not None else None,
        "items": legacy_service._request_items(reliefrqst_id),
        "compatibility_only": False,
    }
    if package is not None:
        if package_record is not None and package_record.status_code == PACKAGE_STATUS_DRAFT:
            payload["package"]["allocation"] = _operations_allocation_payload(package, package_record)
        else:
            payload["package"]["allocation"] = legacy_service._package_detail(package)["allocation"]
    return payload


def release_package_lock(
    reliefrqst_id: int,
    *,
    actor_id: str,
    actor_roles: Iterable[str] | None,
    tenant_context: TenantContext,
    force: bool = False,
) -> dict[str, Any]:
    actor_id = _require_actor_id(actor_id)
    request = legacy_service._load_request(reliefrqst_id)
    request_probe = _request_access_probe_from_legacy(request)
    _ensure_fulfillment_request_access(
        request_probe,
        actor_id=actor_id,
        actor_roles=actor_roles or (),
        tenant_context=tenant_context,
        write=True,
    )
    request_record = _sync_operations_request(request, actor_id=actor_id)
    package = legacy_service._current_package_for_request(reliefrqst_id)
    if package is None:
        return _package_lock_release_response(
            package_record=None,
            lock=None,
            released=False,
            message="No current package exists for this request.",
        )
    package_record = _sync_operations_package(package, request_record=request_record, actor_id=actor_id)
    return _release_package_lock_for_record(
        package_record,
        request_record=request_record,
        actor_id=actor_id,
        actor_roles=actor_roles or (),
        force=force,
    )


def _legacy_allocation_line_count(reliefpkg_id: int) -> int:
    try:
        return ReliefPkgItem.objects.filter(reliefpkg_id=reliefpkg_id).count()
    except DatabaseError:
        return 0


def _delete_legacy_allocation_lines(reliefpkg_id: int) -> int:
    try:
        deleted, _ = ReliefPkgItem.objects.filter(reliefpkg_id=reliefpkg_id).delete()
    except DatabaseError:
        return 0
    return int(deleted)


@transaction.atomic
def reset_package_allocations(
    reliefpkg_id: int,
    *,
    actor_id: str,
    status_transition_reason: str | None = None,
) -> dict[str, Any]:
    actor_id = _require_actor_id(actor_id)
    package = legacy_service._load_package(reliefpkg_id, for_update=True)
    request = legacy_service._load_request(int(package.reliefrqst_id), for_update=True)
    request_record = _sync_operations_request(
        request,
        actor_id=actor_id,
        status_code=REQUEST_STATUS_APPROVED_FOR_FULFILLMENT,
    )
    package_record = _sync_operations_package(
        package,
        request_record=request_record,
        actor_id=actor_id,
    )

    if package_record.status_code in {
        PACKAGE_STATUS_DISPATCHED,
        PACKAGE_STATUS_RECEIVED,
        PACKAGE_STATUS_SPLIT,
        PACKAGE_STATUS_CANCELLED,
    }:
        raise OperationValidationError(
            {"reset": "This package can no longer be reset."}
        )

    cancelled_legs = list(
        package_record.consolidation_legs.select_for_update().order_by("leg_sequence")
    )
    if any(leg.status_code != CONSOLIDATION_LEG_STATUS_CANCELLED for leg in cancelled_legs):
        raise OperationValidationError(
            {"reset": "Packages with active consolidation legs cannot be reset."}
        )

    legacy_status = legacy_service._current_package_status(package)
    released_rows: list[dict[str, Any]] = []
    if legacy_status in {"P", "C", "V", "R"}:
        released_rows = legacy_service._selected_plan_for_package(int(package.reliefpkg_id))
        if released_rows:
            legacy_service._apply_stock_delta_for_rows(
                released_rows,
                actor_user_id=actor_id,
                delta_sign=-1,
                update_needs_list=False,
            )

    operations_line_count = package_record.allocation_lines.count()
    legacy_line_count = _legacy_allocation_line_count(int(package_record.package_id))
    package_record.allocation_lines.all().delete()
    _delete_legacy_allocation_lines(int(package_record.package_id))
    if cancelled_legs:
        for leg in cancelled_legs:
            complete_queue_assignments(
                entity_type=ENTITY_CONSOLIDATION_LEG,
                entity_id=int(leg.leg_id),
                actor_id=actor_id,
                completion_status="CANCELLED",
            )
        OperationsConsolidationLeg.objects.filter(
            leg_id__in=[int(leg.leg_id) for leg in cancelled_legs]
        ).delete()

    now = timezone.now()
    package.status_code = legacy_service.PKG_STATUS_DRAFT
    package.update_by_id = actor_id
    package.update_dtime = now
    package.version_nbr = int(package.version_nbr or 0) + 1
    if hasattr(package, "save"):
        package.save()

    package_record = _sync_operations_package(
        package,
        request_record=request_record,
        actor_id=actor_id,
        status_code=PACKAGE_STATUS_DRAFT,
        override_status_code=None,
        source_warehouse_id=package_record.source_warehouse_id,
        status_transition_reason=status_transition_reason,
    )
    _update_package_workflow_fields(
        package_record,
        actor_id=actor_id,
        consolidation_status=None,
    )
    complete_queue_assignments(
        entity_type=ENTITY_PACKAGE,
        entity_id=int(package_record.package_id),
        actor_id=actor_id,
        completion_status="CANCELLED",
    )
    complete_queue_assignments(
        entity_type=ENTITY_REQUEST,
        entity_id=int(request_record.relief_request_id),
        queue_code=QUEUE_CODE_OVERRIDE,
        actor_id=actor_id,
        completion_status="CANCELLED",
    )
    OperationsPackageLock.objects.filter(
        package_id=int(package_record.package_id),
        lock_status="ACTIVE",
    ).update(
        lock_status="RELEASED",
        lock_expires_at=now,
    )

    return {
        "status": PACKAGE_STATUS_DRAFT,
        "reliefrqst_id": int(request_record.relief_request_id),
        "request_no": request_record.request_no,
        "reliefpkg_id": int(package_record.package_id),
        "package_no": package_record.package_no,
        "operations_allocation_lines_deleted": int(operations_line_count),
        "legacy_allocation_lines_deleted": int(legacy_line_count),
        "released_stock_summary": (
            {
                "line_count": len(released_rows),
                "total_qty": str(
                    sum(
                        (
                            legacy_service._quantize_qty(row["quantity"])
                            for row in released_rows
                        ),
                        Decimal("0"),
                    ).quantize(Decimal("0.0001"))
                ),
            }
            if released_rows
            else {"line_count": 0, "total_qty": "0.0000"}
        ),
    }


@transaction.atomic
def abandon_package_draft(
    reliefpkg_id: int,
    *,
    payload: Mapping[str, Any] | None = None,
    actor_id: str,
    actor_roles: Iterable[str] | None,
    tenant_context: TenantContext,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """
    Abandon a work-in-progress fulfillment draft.

    Unlike ``cancel_package()`` (which moves the package to the terminal CANCELLED
    status), this is a **non-terminal** abandon: the package is reset to DRAFT,
    reserved stock is released, any planned consolidation legs are cancelled, the
    package lock is released, and the parent relief request stays in
    ``APPROVED_FOR_FULFILLMENT`` so another operator can start fresh.

    Refuses to run if the package has already advanced past a revertible state
    (dispatch-approved / dispatched / received / split / cancelled) or if any
    leg is already in transit or received.
    """
    actor_id = _require_actor_id(actor_id)
    idempotency = _begin_idempotent_write(
        endpoint="package_abandon_draft",
        actor_id=actor_id,
        tenant_context=tenant_context,
        resource_id=reliefpkg_id,
        idempotency_key=idempotency_key,
    )
    if idempotency.cached_result is not None:
        return idempotency.cached_result
    _require_roles(
        actor_roles,
        FULFILLMENT_ROLE_CODES,
        message="Only fulfillment roles may abandon a draft.",
    )

    # Validate optional reason (max 500 chars, trimmed)
    reason_text = ""
    if payload:
        raw_reason = payload.get("reason")
        if raw_reason not in (None, ""):
            reason_text = str(raw_reason).strip()
            if len(reason_text) > 500:
                raise OperationValidationError(
                    {"reason": "Reason must be 500 characters or fewer."}
                )

    # Load with tenant + access guard (write lock)
    _package, _request, request_record, package_record = _package_context_by_package_id(
        reliefpkg_id,
        actor_id=actor_id,
        actor_roles=actor_roles,
        tenant_context=tenant_context,
        write=True,
    )

    if package_record.status_code in {
        PACKAGE_STATUS_COMMITTED,
        PACKAGE_STATUS_READY_FOR_DISPATCH,
        PACKAGE_STATUS_READY_FOR_PICKUP,
        PACKAGE_STATUS_DISPATCHED,
        PACKAGE_STATUS_RECEIVED,
        PACKAGE_STATUS_SPLIT,
        PACKAGE_STATUS_CANCELLED,
    }:
        raise OperationValidationError(
            {"abandon": "This fulfillment can no longer be abandoned."}
        )

    # Any in-flight or received legs block the abandon so we don't lose shipment state
    legs = list(
        package_record.consolidation_legs.select_for_update().order_by("leg_sequence")
    )
    if any(
        leg.status_code
        in {
            CONSOLIDATION_LEG_STATUS_IN_TRANSIT,
            CONSOLIDATION_LEG_STATUS_RECEIVED_AT_STAGING,
        }
        for leg in legs
    ):
        raise OperationValidationError(
            {
                "abandon": (
                    "Packages with in-transit or received consolidation legs cannot be abandoned."
                )
            }
        )

    # Cancel any still-planned legs so reset_package_allocations is satisfied
    now = timezone.now()
    for leg in legs:
        if leg.status_code == CONSOLIDATION_LEG_STATUS_CANCELLED:
            continue
        record_status_transition(
            entity_type=ENTITY_CONSOLIDATION_LEG,
            entity_id=int(leg.leg_id),
            from_status=leg.status_code,
            to_status=CONSOLIDATION_LEG_STATUS_CANCELLED,
            actor_id=actor_id,
        )
        leg.status_code = CONSOLIDATION_LEG_STATUS_CANCELLED
        leg.update_by_id = actor_id
        leg.update_dtime = now
        leg.version_nbr = int(leg.version_nbr or 0) + 1
        leg.save(
            update_fields=["status_code", "update_by_id", "update_dtime", "version_nbr"]
        )

    previous_status_code = package_record.status_code

    # Delegate the actual revert + stock-release to the existing helper
    result = reset_package_allocations(
        int(package_record.package_id),
        actor_id=actor_id,
        status_transition_reason=reason_text or None,
    )

    result["abandoned"] = True
    result["request_status"] = REQUEST_STATUS_APPROVED_FOR_FULFILLMENT
    result["reason"] = reason_text or None
    result["previous_status_code"] = previous_status_code
    _cache_idempotent_response_after_commit(
        idempotency.cache_key,
        result,
        reservation_key=idempotency.reservation_key,
        reservation_token=idempotency.reservation_token,
    )
    return result


def get_staging_recommendation(
    reliefrqst_id: int,
    *,
    actor_id: str | None = None,
    actor_roles: Iterable[str] | None = None,
    tenant_context: TenantContext,
) -> dict[str, Any]:
    actor_id = _require_actor_id(actor_id)
    request = legacy_service._load_request(reliefrqst_id)
    request_probe = _request_access_probe_from_legacy(request)
    _ensure_fulfillment_request_access(
        request_probe,
        actor_id=actor_id,
        actor_roles=actor_roles or (),
        tenant_context=tenant_context,
    )
    recommendation = recommend_staging_hub(
        beneficiary_parish_code=beneficiary_parish_code_for_request(reliefrqst_id)
    )
    return {
        "reliefrqst_id": int(reliefrqst_id),
        "recommended_staging_warehouse_id": recommendation.recommended_staging_warehouse_id,
        "recommended_staging_warehouse_name": recommendation.recommended_staging_warehouse_name,
        "recommended_staging_parish_code": recommendation.recommended_staging_parish_code,
        "staging_selection_basis": recommendation.staging_selection_basis,
    }


def _package_context_by_package_id(
    reliefpkg_id: int,
    *,
    actor_id: str,
    actor_roles: Iterable[str] | None,
    tenant_context: TenantContext,
    write: bool = False,
):
    package = legacy_service._load_package(reliefpkg_id, for_update=write)
    request = legacy_service._load_request(int(package.reliefrqst_id), for_update=write)
    request_record = _sync_operations_request(request, actor_id=actor_id)
    package_record = _sync_operations_package(package, request_record=request_record, actor_id=actor_id)
    _ensure_package_access(
        package_record,
        actor_id=actor_id,
        actor_roles=actor_roles or (),
        tenant_context=tenant_context,
        write=write,
    )
    return package, request, request_record, package_record


def list_consolidation_legs(
    reliefpkg_id: int,
    *,
    actor_id: str | None = None,
    actor_roles: Iterable[str] | None = None,
    tenant_context: TenantContext,
) -> dict[str, Any]:
    actor_id = _require_actor_id(actor_id)
    package, _request, request_record, package_record = _package_context_by_package_id(
        reliefpkg_id,
        actor_id=actor_id,
        actor_roles=actor_roles,
        tenant_context=tenant_context,
    )
    _ensure_fulfillment_request_access(
        request_record,
        actor_id=actor_id,
        actor_roles=actor_roles or (),
        tenant_context=tenant_context,
    )
    return {
        "package": _package_summary_payload(
            package,
            package_record,
        ),
        "results": [
            _consolidation_leg_payload(leg)
            for leg in package_record.consolidation_legs.order_by("leg_sequence").prefetch_related("items")
        ],
    }


def get_package_allocation_options(
    reliefrqst_id: int,
    *,
    source_warehouse_id: int | None = None,
    actor_id: str | None = None,
    actor_roles: Iterable[str] | None = None,
    tenant_context: TenantContext | None = None,
) -> dict[str, Any]:
    if actor_id is not None and tenant_context is not None:
        actor_id = _require_actor_id(actor_id)
        request = legacy_service._load_request(reliefrqst_id)
        request_probe = _request_access_probe_from_legacy(request)
        _ensure_fulfillment_request_access(request_probe, actor_id=actor_id, actor_roles=actor_roles or (), tenant_context=tenant_context)
    return legacy_service.get_package_allocation_options(
        reliefrqst_id,
        source_warehouse_id=source_warehouse_id,
        tenant_context=tenant_context,
    )


def get_item_allocation_options(
    reliefrqst_id: int,
    item_id: int,
    *,
    source_warehouse_id: int,
    draft_allocations: Sequence[Mapping[str, Any]] | None = None,
    actor_id: str | None = None,
    actor_roles: Iterable[str] | None = None,
    tenant_context: TenantContext | None = None,
) -> dict[str, Any]:
    """Return allocation candidates for a single item from a single warehouse."""
    if actor_id is not None and tenant_context is not None:
        actor_id = _require_actor_id(actor_id)
        request = legacy_service._load_request(reliefrqst_id)
        request_probe = _request_access_probe_from_legacy(request)
        _ensure_fulfillment_request_access(
            request_probe,
            actor_id=actor_id,
            actor_roles=actor_roles or (),
            tenant_context=tenant_context,
        )
    return legacy_service.get_item_allocation_options(
        reliefrqst_id,
        item_id,
        source_warehouse_id=source_warehouse_id,
        tenant_context=tenant_context,
        draft_allocations=draft_allocations,
    )


def get_item_allocation_preview(
    reliefrqst_id: int,
    item_id: int,
    *,
    payload: Mapping[str, Any] | None = None,
    source_warehouse_id: int | None = None,
    draft_allocations: Sequence[Mapping[str, Any]] | None = None,
    actor_id: str | None = None,
    actor_roles: Iterable[str] | None = None,
    tenant_context: TenantContext | None = None,
) -> dict[str, Any]:
    if payload is not None:
        requested_source_warehouse_id = _optional_positive_int_payload_value(payload, "source_warehouse_id")
        if requested_source_warehouse_id in (_UNSET, None):
            raise OperationValidationError({"source_warehouse_id": "source_warehouse_id is required."})
        draft_allocations = payload.get("draft_allocations", [])
        if draft_allocations is None:
            draft_allocations = []
        if not isinstance(draft_allocations, list):
            raise OperationValidationError({"draft_allocations": "draft_allocations must be provided as an array."})
        source_warehouse_id = int(requested_source_warehouse_id)
    if source_warehouse_id is None:
        raise OperationValidationError({"source_warehouse_id": "source_warehouse_id is required."})
    if actor_id is not None and tenant_context is not None:
        actor_id = _require_actor_id(actor_id)
        request = legacy_service._load_request(reliefrqst_id)
        request_probe = _request_access_probe_from_legacy(request)
        _ensure_fulfillment_request_access(
            request_probe,
            actor_id=actor_id,
            actor_roles=actor_roles or (),
            tenant_context=tenant_context,
        )
    return legacy_service.get_item_allocation_preview(
        reliefrqst_id,
        item_id,
        source_warehouse_id=int(source_warehouse_id),
        tenant_context=tenant_context,
        draft_allocations=draft_allocations,
    )


@transaction.atomic
def save_package(
    reliefrqst_id: int,
    *,
    payload: Mapping[str, Any],
    actor_id: str,
    actor_roles: Iterable[str] | None,
    tenant_context: TenantContext,
    permissions: Iterable[str] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    _require_roles(actor_roles, FULFILLMENT_ROLE_CODES, message="Only fulfillment roles may modify packages.")
    draft_save = bool(payload.get("draft_save"))
    idempotency = _IdempotencyWriteLease()
    if not draft_save:
        idempotency = _begin_idempotent_write(
            endpoint="package_commit_allocation",
            actor_id=actor_id,
            tenant_context=tenant_context,
            resource_id=reliefrqst_id,
            idempotency_key=idempotency_key,
            required=False,
        )
        if idempotency.cached_result is not None:
            return idempotency.cached_result
    requested_source_warehouse_id = _optional_positive_int_payload_value(payload, "source_warehouse_id")
    validated_allocations = _validate_allocation_rows(payload["allocations"]) if "allocations" in payload else None
    request = legacy_service._load_request(reliefrqst_id, for_update=True)
    request_probe = _request_access_probe_from_legacy(request)
    _ensure_fulfillment_request_access(request_probe, actor_id=actor_id, actor_roles=actor_roles or (), tenant_context=tenant_context, write=True)
    if _request_fully_dispatched(int(request.reliefrqst_id)):
        raise OperationValidationError(
            {
                "request": (
                    "All items on this request are already fully issued. "
                    "Cancel a dispatched package to free quantity before creating a new one."
                )
            }
        )
    request_record = _sync_operations_request(request, actor_id=actor_id)
    package = legacy_service._current_package_for_request(reliefrqst_id)
    package_locked_before_save = package is not None
    if package_locked_before_save:
        package_record = _sync_operations_package(package, request_record=request_record, actor_id=actor_id)
        _acquire_package_lock(int(package.reliefpkg_id), actor_id=actor_id, actor_roles=actor_roles or ())
    else:
        package_record = None
        # No package yet - acquire lock immediately after save creates one.
        pass
    staging_config = _resolved_staging_configuration(
        reliefrqst_id=reliefrqst_id,
        payload=payload,
        existing_package_record=package_record,
        permissions=permissions,
        draft_save=draft_save,
    )
    legacy_payload = {
        key: value
        for key, value in payload.items()
        if key not in {"allocations", "draft_save"}
    }
    if not draft_save and "allocations" in payload:
        legacy_payload["allocations"] = payload["allocations"]
    result = legacy_service.save_package(
        reliefrqst_id,
        payload=legacy_payload,
        actor_id=actor_id,
        actor_roles=actor_roles,
    )
    # Re-sync request after legacy save to keep the operations status at
    # APPROVED_FOR_FULFILLMENT (the legacy save sets status_code=2 which
    # the mapping interprets as CANCELLED).
    request = legacy_service._load_request(reliefrqst_id)
    request_record = _sync_operations_request(request, actor_id=actor_id, status_code=REQUEST_STATUS_APPROVED_FOR_FULFILLMENT)
    package = legacy_service._current_package_for_request(reliefrqst_id)
    if not package_locked_before_save and package is not None:
        _acquire_package_lock(int(package.reliefpkg_id), actor_id=actor_id, actor_roles=actor_roles or ())
    if package is None:
        _cache_idempotent_response_after_commit(
            idempotency.cache_key,
            result,
            reservation_key=idempotency.reservation_key,
            reservation_token=idempotency.reservation_token,
        )
        return result
    # For draft saves, only persist an explicit user-selected default warehouse.
    # Per-item selection is first-class and must not fabricate a package-level
    # default that resurfaces on reload. For commits, keep the legacy fallback
    # (first allocation's warehouse) so the dispatch record has a source.
    package_default_warehouse_id: int | None | object
    if requested_source_warehouse_id is not _UNSET:
        package_default_warehouse_id = requested_source_warehouse_id
    elif not draft_save and validated_allocations:
        package_default_warehouse_id = validated_allocations[0]["source_warehouse_id"]
    else:
        package_default_warehouse_id = _UNSET
    status_code = PACKAGE_STATUS_DRAFT
    override_status = None
    if not draft_save:
        if result.get("status") == "PENDING_OVERRIDE_APPROVAL":
            status_code = PACKAGE_STATUS_PENDING_OVERRIDE_APPROVAL
            override_status = PACKAGE_STATUS_PENDING_OVERRIDE_APPROVAL
        elif result.get("status") == "COMMITTED":
            status_code = PACKAGE_STATUS_COMMITTED
    package_record = _sync_operations_package(
        package,
        request_record=request_record,
        actor_id=actor_id,
        status_code=status_code,
        override_status_code=override_status,
        source_warehouse_id=package_default_warehouse_id,
    )
    _update_package_workflow_fields(
        package_record,
        actor_id=actor_id,
        fulfillment_mode=staging_config["fulfillment_mode"],
        staging_warehouse_id=staging_config["staging_warehouse_id"],
        recommended_staging_warehouse_id=staging_config["recommended_staging_warehouse_id"],
        staging_selection_basis=staging_config["staging_selection_basis"],
        staging_override_reason=staging_config["staging_override_reason"],
        consolidation_status=None
        if staging_config["fulfillment_mode"] == FULFILLMENT_MODE_DIRECT
        else package_record.consolidation_status,
    )
    # ── Dual-write: sync allocation lines to new operations table ──
    if validated_allocations is not None:
        override_reason_code = None
        if (
            result.get("status") == "COMMITTED"
            and "allocation_order_override" in (result.get("override_markers") or [])
            and not result.get("override_required")
        ):
            override_reason_code = str(payload.get("override_reason_code") or "").strip() or None
        _replace_operations_allocation_lines(
            package_record,
            validated_allocations,
            actor_id=actor_id,
            override_reason_code=override_reason_code,
        )
    if status_code == PACKAGE_STATUS_PENDING_OVERRIDE_APPROVAL:
        fulfillment_tenant_id = _resolve_request_level_fulfillment_tenant_id()
        assign_roles_to_queue(
            queue_code=QUEUE_CODE_OVERRIDE,
            entity_type=ENTITY_REQUEST,
            entity_id=reliefrqst_id,
            role_codes=[ROLE_LOGISTICS_MANAGER],
            tenant_id=fulfillment_tenant_id,
        )
        create_role_notifications(
            event_code=EVENT_OVERRIDE_REQUESTED,
            entity_type=ENTITY_REQUEST,
            entity_id=reliefrqst_id,
            message_text=f"Override approval is required for package {package.tracking_no}.",
            role_codes=[ROLE_LOGISTICS_MANAGER],
            tenant_id=fulfillment_tenant_id,
            queue_code=QUEUE_CODE_OVERRIDE,
        )
    elif status_code == PACKAGE_STATUS_COMMITTED:
        if _is_staged_fulfillment_mode(staging_config["fulfillment_mode"]):
            package_record = _sync_operations_package(
                package,
                request_record=request_record,
                actor_id=actor_id,
                status_code=PACKAGE_STATUS_CONSOLIDATING,
                source_warehouse_id=package_default_warehouse_id,
            )
            _update_package_workflow_fields(
                package_record,
                actor_id=actor_id,
                fulfillment_mode=staging_config["fulfillment_mode"],
                staging_warehouse_id=staging_config["staging_warehouse_id"],
                recommended_staging_warehouse_id=staging_config["recommended_staging_warehouse_id"],
                staging_selection_basis=staging_config["staging_selection_basis"],
                staging_override_reason=staging_config["staging_override_reason"],
                consolidation_status=CONSOLIDATION_STATUS_AWAITING_LEGS,
            )
            legs = _create_consolidation_legs(package_record=package_record, actor_id=actor_id)
            if legs:
                for leg in legs:
                    assign_roles_to_queue(
                        queue_code=QUEUE_CODE_CONSOLIDATION_DISPATCH,
                        entity_type=ENTITY_CONSOLIDATION_LEG,
                        entity_id=int(leg.leg_id),
                        role_codes=DISPATCH_ROLE_CODES,
                        tenant_id=request_record.beneficiary_tenant_id,
                    )
                create_role_notifications(
                    event_code=EVENT_CONSOLIDATION_PLANNED,
                    entity_type=ENTITY_PACKAGE,
                    entity_id=int(package.reliefpkg_id),
                    message_text=(
                        f"Package {package.tracking_no} is committed for staged fulfillment "
                        "and awaiting consolidation leg dispatch."
                    ),
                    role_codes=DISPATCH_ROLE_CODES,
                    tenant_id=request_record.beneficiary_tenant_id,
                    queue_code=QUEUE_CODE_CONSOLIDATION_DISPATCH,
                )
            else:
                package_record = _transition_staged_package_ready(
                    package=package,
                    request_record=request_record,
                    package_record=package_record,
                    actor_id=actor_id,
                    materialize_dispatch_sources=False,
                )
                if package_record.status_code == PACKAGE_STATUS_READY_FOR_PICKUP:
                    create_role_notifications(
                        event_code=EVENT_PACKAGE_COMMITTED,
                        entity_type=ENTITY_PACKAGE,
                        entity_id=int(package.reliefpkg_id),
                        message_text=(
                            f"Package {package.tracking_no} is already staged and ready "
                            "for pickup release."
                        ),
                        role_codes=FULFILLMENT_ROLE_CODES,
                        tenant_id=request_record.beneficiary_tenant_id,
                        queue_code=QUEUE_CODE_PICKUP_RELEASE,
                    )
                else:
                    create_role_notifications(
                        event_code=EVENT_STAGED_DELIVERY_READY,
                        entity_type=ENTITY_PACKAGE,
                        entity_id=int(package.reliefpkg_id),
                        message_text=(
                            f"Package {package.tracking_no} is already staged and ready "
                            "for final dispatch."
                        ),
                        role_codes=DISPATCH_ROLE_CODES,
                        tenant_id=request_record.beneficiary_tenant_id,
                        queue_code=QUEUE_CODE_DISPATCH,
                    )
        else:
            dispatch = _ensure_dispatch_record(package=package, package_record=package_record, actor_id=actor_id)
            assign_roles_to_queue(
                queue_code=QUEUE_CODE_DISPATCH,
                entity_type=ENTITY_PACKAGE,
                entity_id=int(package.reliefpkg_id),
                role_codes=DISPATCH_ROLE_CODES,
                tenant_id=request_record.beneficiary_tenant_id,
            )
            create_role_notifications(
                event_code=EVENT_PACKAGE_COMMITTED,
                entity_type=ENTITY_PACKAGE,
                entity_id=int(package.reliefpkg_id),
                message_text=f"Package {package.tracking_no} is committed and ready for dispatch preparation.",
                role_codes=DISPATCH_ROLE_CODES,
                tenant_id=request_record.beneficiary_tenant_id,
                queue_code=QUEUE_CODE_DISPATCH,
            )
            if dispatch.status_code != DISPATCH_STATUS_READY:
                record_status_transition(
                    entity_type=ENTITY_DISPATCH,
                    entity_id=int(dispatch.dispatch_id),
                    from_status=dispatch.status_code,
                    to_status=DISPATCH_STATUS_READY,
                    actor_id=actor_id,
                )
                dispatch.status_code = DISPATCH_STATUS_READY
                dispatch.save(update_fields=["status_code"])
    if not payload.get("allocations"):
        final_result = get_package(reliefrqst_id, actor_id=actor_id, actor_roles=actor_roles, tenant_context=tenant_context)
    else:
        final_result = {
        **result,
        "package_status_code": package_record.status_code,
        "package_status_label": STATUS_LABELS.get(package_record.status_code, package_record.status_code.title()),
        "lock": _package_lock_payload(int(package.reliefpkg_id)),
        }
    _cache_idempotent_response_after_commit(
        idempotency.cache_key,
        final_result,
        reservation_key=idempotency.reservation_key,
        reservation_token=idempotency.reservation_token,
    )
    return final_result


@transaction.atomic
def approve_override(
    reliefrqst_id: int,
    *,
    payload: Mapping[str, Any],
    actor_id: str,
    actor_roles: Iterable[str] | None,
    tenant_context: TenantContext | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    idempotency = _begin_idempotent_write(
        endpoint="package_override_approve",
        actor_id=actor_id,
        tenant_context=tenant_context,
        resource_id=reliefrqst_id,
        idempotency_key=idempotency_key,
    )
    if idempotency.cached_result is not None:
        return idempotency.cached_result
    if tenant_context is None:
        execution_link = _execution_link_for_request(reliefrqst_id)
        if execution_link is not None:
            result = compat_approve_override(
                LegacyWorkflowContext(
                    needs_list_id=int(execution_link.needs_list_id),
                    reliefrqst_id=int(execution_link.reliefrqst_id or reliefrqst_id),
                    reliefpkg_id=int(execution_link.reliefpkg_id),
                    submitted_by=execution_link.override_requested_by or execution_link.needs_list.submitted_by,
                ),
                _normalized_allocations(payload),
                actor_user_id=actor_id,
                supervisor_user_id=actor_id,
                supervisor_role_codes=actor_roles,
                override_reason_code=str(payload.get("override_reason_code") or "").strip(),
                override_note=str(payload.get("override_note") or "").strip(),
                submitter_user_id=execution_link.override_requested_by or execution_link.needs_list.submitted_by,
            )
            _cache_idempotent_response_after_commit(
                idempotency.cache_key,
                result,
                reservation_key=idempotency.reservation_key,
                reservation_token=idempotency.reservation_token,
            )
            return result
        request = _load_request(reliefrqst_id)
        package = _current_package_for_request(reliefrqst_id)
        allocator_user_id = str(request.create_by_id or (package.create_by_id if package is not None else actor_id))
        result = _save_package_allocation(
            reliefrqst_id,
            payload=payload,
            actor_id=actor_id,
            actor_roles=actor_roles,
            allow_pending_override=False,
            supervisor_user_id=actor_id,
            supervisor_role_codes=actor_roles,
            override_submitter_user_id=allocator_user_id,
        )
        _cache_idempotent_response_after_commit(
            idempotency.cache_key,
            result,
            reservation_key=idempotency.reservation_key,
            reservation_token=idempotency.reservation_token,
        )
        return result
    normalized_roles = _require_roles(actor_roles, [ROLE_LOGISTICS_MANAGER], message="Only Logistics Managers may approve overrides.")
    request = legacy_service._load_request(reliefrqst_id)
    request_probe = _request_access_probe_from_legacy(request)
    _ensure_fulfillment_request_access(request_probe, actor_id=actor_id, actor_roles=normalized_roles, tenant_context=tenant_context, write=True)
    request_record = _sync_operations_request(request, actor_id=actor_id)
    package = legacy_service._current_package_for_request(reliefrqst_id)
    if package is None:
        raise OperationValidationError({"override": "No package exists for this request."})
    package_record = _sync_operations_package(package, request_record=request_record, actor_id=actor_id)
    if package_record.status_code != PACKAGE_STATUS_PENDING_OVERRIDE_APPROVAL:
        raise OperationValidationError({"override": "Package is not awaiting override approval."})
    result = legacy_service.approve_override(reliefrqst_id, payload=payload, actor_id=actor_id, actor_roles=normalized_roles)
    package = legacy_service._current_package_for_request(reliefrqst_id)
    if package is not None:
        package_record = _sync_operations_package(package, request_record=request_record, actor_id=actor_id, status_code=PACKAGE_STATUS_COMMITTED, override_status_code=None)
        complete_queue_assignments(entity_type=ENTITY_REQUEST, entity_id=reliefrqst_id, queue_code=QUEUE_CODE_OVERRIDE, actor_id=actor_id)
        if _is_staged_fulfillment_mode(package_record.fulfillment_mode):
            legs = _create_consolidation_legs(package_record=package_record, actor_id=actor_id)
            if legs:
                _sync_operations_package(
                    package,
                    request_record=request_record,
                    actor_id=actor_id,
                    status_code=PACKAGE_STATUS_CONSOLIDATING,
                    override_status_code=None,
                )
                _update_package_workflow_fields(
                    package_record,
                    actor_id=actor_id,
                    consolidation_status=CONSOLIDATION_STATUS_AWAITING_LEGS,
                )
                for leg in package_record.consolidation_legs.order_by("leg_sequence"):
                    assign_roles_to_queue(
                        queue_code=QUEUE_CODE_CONSOLIDATION_DISPATCH,
                        entity_type=ENTITY_CONSOLIDATION_LEG,
                        entity_id=int(leg.leg_id),
                        role_codes=DISPATCH_ROLE_CODES,
                        tenant_id=request_record.beneficiary_tenant_id,
                    )
                create_role_notifications(
                    event_code=EVENT_OVERRIDE_APPROVED,
                    entity_type=ENTITY_PACKAGE,
                    entity_id=int(package.reliefpkg_id),
                    message_text=f"Override approved for staged package {package.tracking_no}.",
                    role_codes=DISPATCH_ROLE_CODES,
                    tenant_id=request_record.beneficiary_tenant_id,
                    queue_code=QUEUE_CODE_CONSOLIDATION_DISPATCH,
                )
            else:
                package_record = _transition_staged_package_ready(
                    package=package,
                    request_record=request_record,
                    package_record=package_record,
                    actor_id=actor_id,
                    materialize_dispatch_sources=False,
                )
                if package_record.status_code == PACKAGE_STATUS_READY_FOR_PICKUP:
                    create_role_notifications(
                        event_code=EVENT_OVERRIDE_APPROVED,
                        entity_type=ENTITY_PACKAGE,
                        entity_id=int(package.reliefpkg_id),
                        message_text=(
                            f"Override approved for staged package {package.tracking_no}; "
                            "it is ready for pickup release."
                        ),
                        role_codes=FULFILLMENT_ROLE_CODES,
                        tenant_id=request_record.beneficiary_tenant_id,
                        queue_code=QUEUE_CODE_PICKUP_RELEASE,
                    )
                else:
                    create_role_notifications(
                        event_code=EVENT_OVERRIDE_APPROVED,
                        entity_type=ENTITY_PACKAGE,
                        entity_id=int(package.reliefpkg_id),
                        message_text=(
                            f"Override approved for staged package {package.tracking_no}; "
                            "it is ready for final dispatch."
                        ),
                        role_codes=DISPATCH_ROLE_CODES,
                        tenant_id=request_record.beneficiary_tenant_id,
                        queue_code=QUEUE_CODE_DISPATCH,
                    )
        else:
            _ensure_dispatch_record(package=package, package_record=package_record, actor_id=actor_id)
            assign_roles_to_queue(
                queue_code=QUEUE_CODE_DISPATCH,
                entity_type=ENTITY_PACKAGE,
                entity_id=int(package.reliefpkg_id),
                role_codes=DISPATCH_ROLE_CODES,
                tenant_id=request_record.beneficiary_tenant_id,
            )
            create_role_notifications(
                event_code=EVENT_OVERRIDE_APPROVED,
                entity_type=ENTITY_PACKAGE,
                entity_id=int(package.reliefpkg_id),
                message_text=f"Override approved for package {package.tracking_no}.",
                role_codes=DISPATCH_ROLE_CODES,
                tenant_id=request_record.beneficiary_tenant_id,
                queue_code=QUEUE_CODE_DISPATCH,
            )
    _cache_idempotent_response_after_commit(
        idempotency.cache_key,
        result,
        reservation_key=idempotency.reservation_key,
        reservation_token=idempotency.reservation_token,
    )
    return result


@transaction.atomic
def dispatch_consolidation_leg(
    reliefpkg_id: int,
    leg_id: int,
    *,
    payload: Mapping[str, Any],
    actor_id: str,
    actor_roles: Iterable[str] | None,
    tenant_context: TenantContext,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    idempotency = _begin_idempotent_write(
        endpoint="consolidation_leg_dispatch",
        actor_id=actor_id,
        tenant_context=tenant_context,
        resource_id=reliefpkg_id,
        idempotency_key=idempotency_key,
    )
    if idempotency.cached_result is not None:
        return idempotency.cached_result
    _require_roles(actor_roles, DISPATCH_ROLE_CODES, message="Only dispatch roles may hand off consolidation legs.")
    package, request, request_record, package_record = _package_context_by_package_id(
        reliefpkg_id,
        actor_id=actor_id,
        actor_roles=actor_roles,
        tenant_context=tenant_context,
        write=True,
    )
    if not _is_staged_fulfillment_mode(package_record.fulfillment_mode):
        raise OperationValidationError({"consolidation": "This package does not use staged fulfillment."})
    leg = package_record.consolidation_legs.select_for_update().filter(leg_id=int(leg_id)).first()
    if leg is None:
        raise OperationValidationError({"leg_id": "Consolidation leg not found for this package."})
    if leg.status_code != CONSOLIDATION_LEG_STATUS_PLANNED:
        raise OperationValidationError({"dispatch": "Only planned consolidation legs can be dispatched."})
    _ensure_actor_assigned_to_queue(
        queue_code=QUEUE_CODE_CONSOLIDATION_DISPATCH,
        entity_type=ENTITY_CONSOLIDATION_LEG,
        entity_id=int(leg.leg_id),
        actor_id=actor_id,
        actor_roles=actor_roles or (),
        tenant_context=tenant_context,
        error_message="You are not assigned to dispatch this consolidation leg.",
    )
    transport_payload = _validated_transport_payload(payload)
    now = timezone.now()
    leg.driver_name = transport_payload["driver_name"]
    leg.driver_license_last4 = transport_payload["driver_license_last4"]
    leg.vehicle_id = transport_payload["vehicle_id"]
    leg.vehicle_registration = transport_payload["vehicle_registration"]
    leg.vehicle_type = transport_payload["vehicle_type"]
    leg.transport_mode = transport_payload["transport_mode"]
    leg.transport_notes = transport_payload["transport_notes"]
    leg.dispatched_by_id = actor_id
    leg.dispatched_at = transport_payload["departure_dtime"] or now
    leg.expected_arrival_at = transport_payload["estimated_arrival_dtime"]
    _create_leg_shadow_transfer(
        leg=leg,
        package_record=package_record,
        actor_id=actor_id,
        request=request,
        dispatched_at=leg.dispatched_at or now,
    )
    legacy_service._apply_stock_delta_for_rows(
        _leg_dispatch_rows(leg),
        actor_user_id=actor_id,
        delta_sign=1,
        update_needs_list=False,
        consume_stock=True,
    )
    record_status_transition(
        entity_type=ENTITY_CONSOLIDATION_LEG,
        entity_id=int(leg.leg_id),
        from_status=leg.status_code,
        to_status=CONSOLIDATION_LEG_STATUS_IN_TRANSIT,
        actor_id=actor_id,
    )
    leg.status_code = CONSOLIDATION_LEG_STATUS_IN_TRANSIT
    leg.update_by_id = actor_id
    leg.update_dtime = now
    leg.version_nbr = int(leg.version_nbr or 0) + 1
    leg.save()
    _create_consolidation_waybill(leg=leg, package=package, request=request, actor_id=actor_id)
    _update_package_consolidation_status(package_record=package_record, actor_id=actor_id)
    complete_queue_assignments(
        entity_type=ENTITY_CONSOLIDATION_LEG,
        entity_id=int(leg.leg_id),
        queue_code=QUEUE_CODE_CONSOLIDATION_DISPATCH,
        actor_id=actor_id,
    )
    assign_roles_to_queue(
        queue_code=QUEUE_CODE_STAGING_RECEIPT,
        entity_type=ENTITY_CONSOLIDATION_LEG,
        entity_id=int(leg.leg_id),
        role_codes=FULFILLMENT_ROLE_CODES,
        tenant_id=request_record.beneficiary_tenant_id,
    )
    create_role_notifications(
        event_code=EVENT_CONSOLIDATION_DISPATCHED,
        entity_type=ENTITY_CONSOLIDATION_LEG,
        entity_id=int(leg.leg_id),
        message_text=(
            f"Consolidation leg {leg.leg_sequence} for package {package.tracking_no} "
            "is in transit to staging."
        ),
        role_codes=FULFILLMENT_ROLE_CODES,
        tenant_id=request_record.beneficiary_tenant_id,
        queue_code=QUEUE_CODE_STAGING_RECEIPT,
    )
    result = {
        "status": CONSOLIDATION_LEG_STATUS_IN_TRANSIT,
        "package": _package_summary_payload(package, package_record),
        "leg": _consolidation_leg_payload(leg),
    }
    _cache_idempotent_response_after_commit(
        idempotency.cache_key,
        result,
        reservation_key=idempotency.reservation_key,
        reservation_token=idempotency.reservation_token,
    )
    return result


@transaction.atomic
def receive_consolidation_leg(
    reliefpkg_id: int,
    leg_id: int,
    *,
    payload: Mapping[str, Any],
    actor_id: str,
    actor_roles: Iterable[str] | None,
    tenant_context: TenantContext,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    idempotency = _begin_idempotent_write(
        endpoint="consolidation_leg_receive",
        actor_id=actor_id,
        tenant_context=tenant_context,
        resource_id=reliefpkg_id,
        idempotency_key=idempotency_key,
    )
    if idempotency.cached_result is not None:
        return idempotency.cached_result
    _require_roles(actor_roles, FULFILLMENT_ROLE_CODES, message="Only fulfillment roles may receive consolidation legs.")
    package, request, request_record, package_record = _package_context_by_package_id(
        reliefpkg_id,
        actor_id=actor_id,
        actor_roles=actor_roles,
        tenant_context=tenant_context,
        write=True,
    )
    leg = package_record.consolidation_legs.select_for_update().filter(leg_id=int(leg_id)).first()
    if leg is None:
        raise OperationValidationError({"leg_id": "Consolidation leg not found for this package."})
    if leg.status_code != CONSOLIDATION_LEG_STATUS_IN_TRANSIT:
        raise OperationValidationError({"receive": "Only in-transit consolidation legs can be received."})
    _ensure_actor_assigned_to_queue(
        queue_code=QUEUE_CODE_STAGING_RECEIPT,
        entity_type=ENTITY_CONSOLIDATION_LEG,
        entity_id=int(leg.leg_id),
        actor_id=actor_id,
        actor_roles=actor_roles or (),
        tenant_context=tenant_context,
        error_message="You are not assigned to receive this consolidation leg.",
    )
    now = timezone.now()
    _receive_leg_stock_into_staging(leg=leg, actor_id=actor_id)
    OperationsConsolidationReceipt.objects.update_or_create(
        leg=leg,
        defaults={
            "received_by_user_id": actor_id,
            "received_by_name": str(payload.get("received_by_name") or actor_id).strip(),
            "received_at": now,
            "receipt_notes": str(payload.get("receipt_notes") or "").strip() or None,
            "receipt_artifact_json": {
                "received_by_user_id": actor_id,
                "received_by_name": str(payload.get("received_by_name") or actor_id).strip(),
                "received_at": now.isoformat(),
                "receipt_notes": str(payload.get("receipt_notes") or "").strip() or None,
            },
        },
    )
    record_status_transition(
        entity_type=ENTITY_CONSOLIDATION_LEG,
        entity_id=int(leg.leg_id),
        from_status=leg.status_code,
        to_status=CONSOLIDATION_LEG_STATUS_RECEIVED_AT_STAGING,
        actor_id=actor_id,
    )
    leg.status_code = CONSOLIDATION_LEG_STATUS_RECEIVED_AT_STAGING
    leg.received_by_user_id = actor_id
    leg.received_at = now
    leg.update_by_id = actor_id
    leg.update_dtime = now
    leg.version_nbr = int(leg.version_nbr or 0) + 1
    leg.save()
    if leg.shadow_transfer_id:
        Transfer.objects.filter(transfer_id=int(leg.shadow_transfer_id)).update(
            received_at=now,
            received_by=actor_id,
            update_by_id=actor_id,
            update_dtime=now,
            version_nbr=F("version_nbr") + 1,
        )
    complete_queue_assignments(
        entity_type=ENTITY_CONSOLIDATION_LEG,
        entity_id=int(leg.leg_id),
        queue_code=QUEUE_CODE_STAGING_RECEIPT,
        actor_id=actor_id,
    )
    consolidation_status = _update_package_consolidation_status(
        package_record=package_record,
        actor_id=actor_id,
    )
    if consolidation_status == CONSOLIDATION_STATUS_ALL_RECEIVED:
        if package_record.fulfillment_mode == FULFILLMENT_MODE_PICKUP_AT_STAGING:
            package_record = _transition_staged_package_ready(
                package=package,
                request_record=request_record,
                package_record=package_record,
                actor_id=actor_id,
                materialize_dispatch_sources=False,
            )
        else:
            package_record = _transition_staged_package_ready(
                package=package,
                request_record=request_record,
                package_record=package_record,
                actor_id=actor_id,
                materialize_dispatch_sources=True,
            )
            create_role_notifications(
                event_code=EVENT_STAGED_DELIVERY_READY,
                entity_type=ENTITY_PACKAGE,
                entity_id=int(package_record.package_id),
                message_text=(
                    f"Package {package_record.package_no} is fully consolidated and ready "
                    "for final dispatch from staging."
                ),
                role_codes=DISPATCH_ROLE_CODES,
                tenant_id=request_record.beneficiary_tenant_id,
                queue_code=QUEUE_CODE_DISPATCH,
            )
    create_role_notifications(
        event_code=EVENT_STAGING_RECEIPT_RECORDED,
        entity_type=ENTITY_CONSOLIDATION_LEG,
        entity_id=int(leg.leg_id),
        message_text=(
            f"Consolidation leg {leg.leg_sequence} for package {package.tracking_no} "
            "has been received at staging."
        ),
        role_codes=FULFILLMENT_ROLE_CODES + DISPATCH_ROLE_CODES,
        tenant_id=request_record.beneficiary_tenant_id,
    )
    result = {
        "status": leg.status_code,
        "package": _package_summary_payload(package, package_record),
        "leg": _consolidation_leg_payload(leg),
    }
    _cache_idempotent_response_after_commit(
        idempotency.cache_key,
        result,
        reservation_key=idempotency.reservation_key,
        reservation_token=idempotency.reservation_token,
    )
    return result


def get_consolidation_leg_waybill(
    reliefpkg_id: int,
    leg_id: int,
    *,
    actor_id: str | None = None,
    actor_roles: Iterable[str] | None = None,
    tenant_context: TenantContext,
) -> dict[str, Any]:
    actor_id = _require_actor_id(actor_id)
    _, _, request_record, package_record = _package_context_by_package_id(
        reliefpkg_id,
        actor_id=actor_id,
        actor_roles=actor_roles,
        tenant_context=tenant_context,
    )
    _ensure_fulfillment_request_access(
        request_record,
        actor_id=actor_id,
        actor_roles=actor_roles or (),
        tenant_context=tenant_context,
    )
    leg = package_record.consolidation_legs.filter(leg_id=int(leg_id)).first()
    if leg is None:
        raise OperationValidationError({"leg_id": "Consolidation leg not found for this package."})
    waybill = (
        OperationsConsolidationWaybill.objects.filter(leg_id=int(leg.leg_id))
        .order_by("-generated_at", "-waybill_id")
        .first()
    )
    if waybill is None:
        raise OperationValidationError({"waybill": "No leg waybill has been generated yet."})
    return {
        "waybill_no": waybill.waybill_no,
        "waybill_payload": waybill.artifact_payload_json,
        "persisted": True,
    }


@transaction.atomic
def pickup_release(
    reliefpkg_id: int,
    *,
    payload: Mapping[str, Any],
    actor_id: str,
    actor_roles: Iterable[str] | None,
    tenant_context: TenantContext,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    idempotency = _begin_idempotent_write(
        endpoint="pickup_release",
        actor_id=actor_id,
        tenant_context=tenant_context,
        resource_id=reliefpkg_id,
        idempotency_key=idempotency_key,
    )
    if idempotency.cached_result is not None:
        return idempotency.cached_result
    _require_roles(actor_roles, FULFILLMENT_ROLE_CODES, message="Only fulfillment roles may complete pickup release.")
    package, request, request_record, package_record = _package_context_by_package_id(
        reliefpkg_id,
        actor_id=actor_id,
        actor_roles=actor_roles,
        tenant_context=tenant_context,
        write=True,
    )
    if package_record.fulfillment_mode != FULFILLMENT_MODE_PICKUP_AT_STAGING:
        raise OperationValidationError({"pickup_release": "This package is not configured for pickup at staging."})
    if package_record.status_code != PACKAGE_STATUS_READY_FOR_PICKUP:
        raise OperationValidationError({"pickup_release": "Package is not ready for pickup release."})
    if OperationsPickupRelease.objects.filter(package_id=int(package_record.package_id)).exists():
        raise OperationValidationError({"pickup_release": "Pickup release has already been recorded."})
    _ensure_actor_assigned_to_queue(
        queue_code=QUEUE_CODE_PICKUP_RELEASE,
        entity_type=ENTITY_PACKAGE,
        entity_id=int(package_record.package_id),
        actor_id=actor_id,
        actor_roles=actor_roles or (),
        tenant_context=tenant_context,
        error_message="You are not assigned to complete pickup release for this package.",
    )
    legacy_service._apply_stock_delta_for_rows(
        _pickup_release_rows(package_record),
        actor_user_id=actor_id,
        delta_sign=1,
        update_needs_list=False,
        consume_stock=True,
    )
    now = timezone.now()
    released_by_name = str(payload.get("released_by_name") or actor_id).strip()
    release_notes = str(payload.get("release_notes") or "").strip() or None
    collected_by_name = str(payload.get("collected_by_name") or "").strip() or None
    collected_by_id_last4 = _collector_id_last4(
        payload.get("collected_by_id_last4") or payload.get("collected_by_id_ref")
    )
    pickup_tenant_id = (
        request_record.beneficiary_tenant_id
        or package_record.destination_tenant_id
        or tenant_context.active_tenant_id
    )
    package.received_by_id = actor_id
    package.received_dtime = now
    package.status_code = legacy_service.PKG_STATUS_COMPLETED
    package.update_by_id = actor_id
    package.update_dtime = now
    package.version_nbr = int(package.version_nbr or 0) + 1
    package.save()
    package_record = _sync_operations_package(
        package,
        request_record=request_record,
        actor_id=actor_id,
        status_code=PACKAGE_STATUS_RECEIVED,
    )
    OperationsPickupRelease.objects.create(
        package=package_record,
        staging_warehouse_id=package_record.staging_warehouse_id,
        tenant_id=pickup_tenant_id,
        collected_by_name=collected_by_name,
        collected_by_id_last4=collected_by_id_last4,
        released_by_user_id=actor_id,
        released_by_name=released_by_name,
        released_at=now,
        release_notes=release_notes,
        release_artifact_json={
            "staging_warehouse_id": package_record.staging_warehouse_id,
            "tenant_id": pickup_tenant_id,
            "collected_by_name": collected_by_name,
            "collected_by_id_last4": collected_by_id_last4,
            "released_by_user_id": actor_id,
            "released_by_name": released_by_name,
            "released_at": now.isoformat(),
            "release_notes": release_notes,
        },
    )
    complete_queue_assignments(
        entity_type=ENTITY_PACKAGE,
        entity_id=int(package_record.package_id),
        queue_code=QUEUE_CODE_PICKUP_RELEASE,
        actor_id=actor_id,
    )
    create_role_notifications(
        event_code=EVENT_PICKUP_RELEASED,
        entity_type=ENTITY_PACKAGE,
        entity_id=int(package_record.package_id),
        message_text=f"Pickup release completed for package {package_record.package_no}.",
        role_codes=FULFILLMENT_ROLE_CODES + DISPATCH_ROLE_CODES,
        tenant_id=request_record.beneficiary_tenant_id,
    )
    next_request_status = (
        REQUEST_STATUS_FULFILLED
        if _request_fully_dispatched(int(request.reliefrqst_id))
        else REQUEST_STATUS_PARTIALLY_FULFILLED
    )
    _sync_operations_request(request, actor_id=actor_id, status_code=next_request_status)
    result = {
        "status": "RECEIVED",
        "package": _package_summary_payload(package, package_record),
    }
    _cache_idempotent_response_after_commit(
        idempotency.cache_key,
        result,
        reservation_key=idempotency.reservation_key,
        reservation_token=idempotency.reservation_token,
    )
    return result


def request_partial_release(
    reliefpkg_id: int,
    *,
    payload: Mapping[str, Any],
    actor_id: str,
    actor_roles: Iterable[str] | None,
    tenant_context: TenantContext,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    idempotency = _begin_idempotent_write(
        endpoint="partial_release_request",
        actor_id=actor_id,
        tenant_context=tenant_context,
        resource_id=reliefpkg_id,
        idempotency_key=idempotency_key,
    )
    if idempotency.cached_result is not None:
        return idempotency.cached_result
    _require_roles(actor_roles, FULFILLMENT_ROLE_CODES, message="Only fulfillment roles may request partial release.")
    _package, _request, request_record, package_record = _package_context_by_package_id(
        reliefpkg_id,
        actor_id=actor_id,
        actor_roles=actor_roles,
        tenant_context=tenant_context,
        write=True,
    )
    if not _is_staged_fulfillment_mode(package_record.fulfillment_mode):
        raise OperationValidationError({"partial_release": "Partial release is only supported for staged packages."})
    if package_record.status_code != PACKAGE_STATUS_CONSOLIDATING:
        raise OperationValidationError({"partial_release": "Package is not currently consolidating."})
    summary = _package_leg_summary(package_record)
    if summary["received_legs"] <= 0 or summary["received_legs"] >= summary["total_legs"]:
        raise OperationValidationError(
            {"partial_release": "Partial release requires some, but not all, consolidation legs to be received."}
        )
    reason = str(payload.get("reason") or payload.get("partial_release_reason") or "").strip()
    if not reason:
        raise OperationValidationError({"reason": "A partial release reason is required."})
    _update_package_workflow_fields(
        package_record,
        actor_id=actor_id,
        partial_release_requested_by_id=actor_id,
        partial_release_requested_at=timezone.now(),
        partial_release_request_reason=reason,
        consolidation_status=CONSOLIDATION_STATUS_PARTIAL_RELEASE_REQUESTED,
    )
    assign_roles_to_queue(
        queue_code=QUEUE_CODE_PARTIAL_RELEASE_APPROVAL,
        entity_type=ENTITY_PACKAGE,
        entity_id=int(package_record.package_id),
        role_codes=[ROLE_LOGISTICS_MANAGER],
        tenant_id=request_record.beneficiary_tenant_id,
    )
    create_role_notifications(
        event_code=EVENT_PARTIAL_RELEASE_REQUESTED,
        entity_type=ENTITY_PACKAGE,
        entity_id=int(package_record.package_id),
        message_text=f"Partial release approval requested for package {package_record.package_no}.",
        role_codes=[ROLE_LOGISTICS_MANAGER],
        tenant_id=request_record.beneficiary_tenant_id,
        queue_code=QUEUE_CODE_PARTIAL_RELEASE_APPROVAL,
    )
    result = {
        "status": "PARTIAL_RELEASE_REQUESTED",
        "package": _package_summary_payload(
            legacy_service._load_package(reliefpkg_id),
            package_record,
        ),
    }
    _cache_idempotent_response_after_commit(
        idempotency.cache_key,
        result,
        reservation_key=idempotency.reservation_key,
        reservation_token=idempotency.reservation_token,
    )
    return result


def split_package(
    *,
    package: ReliefPkg,
    request_record: OperationsReliefRequest,
    package_record: OperationsPackage,
    actor_id: str,
) -> dict[str, Any]:
    if package_record.split_from_package_id is not None or package_record.status_code == PACKAGE_STATUS_SPLIT:
        raise OperationValidationError({"split": "This package has already been split."})
    legs = list(
        package_record.consolidation_legs.select_for_update().prefetch_related("items").order_by("leg_sequence")
    )
    received_legs = [leg for leg in legs if leg.status_code == CONSOLIDATION_LEG_STATUS_RECEIVED_AT_STAGING]
    residual_legs = [leg for leg in legs if leg.status_code != CONSOLIDATION_LEG_STATUS_RECEIVED_AT_STAGING]
    if not received_legs or not residual_legs:
        raise OperationValidationError(
            {"split": "Partial release split requires both received and outstanding consolidation legs."}
        )
    now = timezone.now()
    split_reason = package_record.partial_release_request_reason or "Partial release"
    residual_package_id = int(legacy_service._next_int_id("reliefpkg", "reliefpkg_id"))
    released_package_id = int(legacy_service._next_int_id("reliefpkg", "reliefpkg_id"))
    residual_package = ReliefPkg.objects.create(
        reliefpkg_id=residual_package_id,
        agency_id=package.agency_id,
        tracking_no=f"{package.tracking_no}-R2",
        eligible_event_id=package.eligible_event_id,
        to_inventory_id=package.to_inventory_id,
        reliefrqst_id=package.reliefrqst_id,
        start_date=package.start_date,
        dispatch_dtime=None,
        transport_mode=package.transport_mode,
        comments_text=f"{package.comments_text or ''} [Split residual]".strip(),
        status_code=legacy_service.PKG_STATUS_PENDING,
        create_by_id=actor_id,
        create_dtime=now,
        update_by_id=actor_id,
        update_dtime=now,
        version_nbr=1,
    )
    released_package = ReliefPkg.objects.create(
        reliefpkg_id=released_package_id,
        agency_id=package.agency_id,
        tracking_no=f"{package.tracking_no}-R1",
        eligible_event_id=package.eligible_event_id,
        to_inventory_id=package.to_inventory_id,
        reliefrqst_id=package.reliefrqst_id,
        start_date=package.start_date,
        dispatch_dtime=None,
        transport_mode=package.transport_mode,
        comments_text=f"{package.comments_text or ''} [Split release]".strip(),
        status_code=legacy_service.PKG_STATUS_PENDING,
        create_by_id=actor_id,
        create_dtime=now,
        update_by_id=actor_id,
        update_dtime=now,
        version_nbr=1,
    )

    mapping = _materialized_leg_item_mapping(package_record)
    parent_lines = list(
        OperationsAllocationLine.objects.select_for_update().filter(package=package_record).order_by("line_id")
    )
    released_line_specs: list[dict[str, Any]] = []
    residual_line_specs: list[dict[str, Any]] = []
    for line in parent_lines:
        key = (int(line.source_warehouse_id), int(line.batch_id), int(line.item_id))
        mapped_leg_item = mapping.get(key)
        line_payload = {
            "item_id": int(line.item_id),
            "quantity": line.quantity,
            "uom_code": line.uom_code,
            "reason_text": line.reason_text,
        }
        if mapped_leg_item is not None and mapped_leg_item.staging_batch_id is not None:
            released_line_specs.append(
                {
                    **line_payload,
                    "source_warehouse_id": int(package_record.staging_warehouse_id or 0),
                    "batch_id": int(mapped_leg_item.staging_batch_id),
                    "source_type": "ON_HAND",
                    "source_record_id": None,
                }
            )
        else:
            residual_line_specs.append(
                {
                    **line_payload,
                    "source_warehouse_id": int(line.source_warehouse_id),
                    "batch_id": int(line.batch_id),
                    "source_type": line.source_type,
                    "source_record_id": line.source_record_id,
                }
            )
    if not released_line_specs or not residual_line_specs:
        raise OperationValidationError({"split": "Split allocation partitioning failed."})

    OperationsAllocationLine.objects.filter(package=package_record).delete()
    ReliefPkgItem.objects.filter(reliefpkg_id=int(package_record.package_id)).delete()

    def _build_ops_lines(child_package_id: int, line_specs: list[dict[str, Any]]) -> list[OperationsAllocationLine]:
        return [
            OperationsAllocationLine(
                package_id=child_package_id,
                item_id=line["item_id"],
                source_warehouse_id=line["source_warehouse_id"],
                batch_id=line["batch_id"],
                quantity=line["quantity"],
                source_type=line["source_type"],
                source_record_id=line["source_record_id"],
                uom_code=line["uom_code"],
                reason_text=line["reason_text"],
                create_by_id=actor_id,
                create_dtime=now,
                update_by_id=actor_id,
                update_dtime=now,
                version_nbr=1,
            )
            for line in line_specs
        ]

    OperationsAllocationLine.objects.bulk_create(
        _build_ops_lines(residual_package_id, residual_line_specs)
        + _build_ops_lines(released_package_id, released_line_specs)
    )
    ReliefPkgItem.objects.bulk_create(
        [
            ReliefPkgItem(
                reliefpkg_id=residual_package_id,
                fr_inventory_id=line["source_warehouse_id"],
                batch_id=line["batch_id"],
                item_id=line["item_id"],
                item_qty=line["quantity"],
                uom_code=line["uom_code"],
                reason_text=line["reason_text"],
                create_by_id=actor_id,
                create_dtime=now,
                update_by_id=actor_id,
                update_dtime=now,
                version_nbr=1,
            )
            for line in residual_line_specs
        ]
        + [
            ReliefPkgItem(
                reliefpkg_id=released_package_id,
                fr_inventory_id=line["source_warehouse_id"],
                batch_id=line["batch_id"],
                item_id=line["item_id"],
                item_qty=line["quantity"],
                uom_code=line["uom_code"],
                reason_text=line["reason_text"],
                create_by_id=actor_id,
                create_dtime=now,
                update_by_id=actor_id,
                update_dtime=now,
                version_nbr=1,
            )
            for line in released_line_specs
        ]
    )

    for leg in received_legs:
        leg.package_id = released_package_id
        leg.update_by_id = actor_id
        leg.update_dtime = now
        leg.version_nbr = int(leg.version_nbr or 0) + 1
        leg.save(update_fields=["package_id", "update_by_id", "update_dtime", "version_nbr"])
    for leg in residual_legs:
        leg.package_id = residual_package_id
        leg.update_by_id = actor_id
        leg.update_dtime = now
        leg.version_nbr = int(leg.version_nbr or 0) + 1
        leg.save(update_fields=["package_id", "update_by_id", "update_dtime", "version_nbr"])

    parent_record = _sync_operations_package(
        package,
        request_record=request_record,
        actor_id=actor_id,
        status_code=PACKAGE_STATUS_SPLIT,
    )
    _update_package_workflow_fields(
        parent_record,
        actor_id=actor_id,
        split_reason=split_reason,
        split_at=now,
    )

    residual_record = _sync_operations_package(
        residual_package,
        request_record=request_record,
        actor_id=actor_id,
        status_code=PACKAGE_STATUS_CONSOLIDATING,
        source_warehouse_id=residual_line_specs[0]["source_warehouse_id"],
    )
    _update_package_workflow_fields(
        residual_record,
        actor_id=actor_id,
        fulfillment_mode=package_record.fulfillment_mode,
        staging_warehouse_id=package_record.staging_warehouse_id,
        recommended_staging_warehouse_id=package_record.recommended_staging_warehouse_id,
        staging_selection_basis=package_record.staging_selection_basis,
        staging_override_reason=package_record.staging_override_reason,
        consolidation_status=CONSOLIDATION_STATUS_AWAITING_LEGS,
        split_from_package_id=int(parent_record.package_id),
        split_reason=split_reason,
        split_at=now,
    )
    residual_status = _update_package_consolidation_status(
        package_record=residual_record,
        actor_id=actor_id,
    )

    released_status = (
        PACKAGE_STATUS_READY_FOR_PICKUP
        if package_record.fulfillment_mode == FULFILLMENT_MODE_PICKUP_AT_STAGING
        else PACKAGE_STATUS_READY_FOR_DISPATCH
    )
    released_record = _sync_operations_package(
        released_package,
        request_record=request_record,
        actor_id=actor_id,
        status_code=released_status,
        source_warehouse_id=int(package_record.staging_warehouse_id or 0),
    )
    _update_package_workflow_fields(
        released_record,
        actor_id=actor_id,
        fulfillment_mode=package_record.fulfillment_mode,
        staging_warehouse_id=package_record.staging_warehouse_id,
        recommended_staging_warehouse_id=package_record.recommended_staging_warehouse_id,
        staging_selection_basis=package_record.staging_selection_basis,
        staging_override_reason=package_record.staging_override_reason,
        consolidation_status=CONSOLIDATION_STATUS_ALL_RECEIVED,
        split_from_package_id=int(parent_record.package_id),
        split_reason=split_reason,
        split_at=now,
    )

    if released_status == PACKAGE_STATUS_READY_FOR_DISPATCH:
        _ensure_dispatch_record(package=released_package, package_record=released_record, actor_id=actor_id)
        assign_roles_to_queue(
            queue_code=QUEUE_CODE_DISPATCH,
            entity_type=ENTITY_PACKAGE,
            entity_id=int(released_record.package_id),
            role_codes=DISPATCH_ROLE_CODES,
            tenant_id=request_record.beneficiary_tenant_id,
        )
    else:
        _assign_pickup_release_queue(
            package_record=released_record,
            tenant_id=request_record.beneficiary_tenant_id,
        )

    create_role_notifications(
        event_code=EVENT_PACKAGE_SPLIT,
        entity_type=ENTITY_PACKAGE,
        entity_id=int(parent_record.package_id),
        message_text=f"Package {parent_record.package_no} was split into released and residual children.",
        role_codes=FULFILLMENT_ROLE_CODES + DISPATCH_ROLE_CODES,
        tenant_id=request_record.beneficiary_tenant_id,
    )
    return {
        "parent": _package_summary_payload(package, parent_record),
        "released_child": _package_summary_payload(released_package, released_record),
        "residual_child": _package_summary_payload(residual_package, residual_record),
        "residual_consolidation_status": residual_status,
    }


@transaction.atomic
def approve_partial_release(
    reliefpkg_id: int,
    *,
    payload: Mapping[str, Any],
    actor_id: str,
    actor_roles: Iterable[str] | None,
    tenant_context: TenantContext,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    idempotency = _begin_idempotent_write(
        endpoint="partial_release_approve",
        actor_id=actor_id,
        tenant_context=tenant_context,
        resource_id=reliefpkg_id,
        idempotency_key=idempotency_key,
    )
    if idempotency.cached_result is not None:
        return idempotency.cached_result
    normalized_roles = _require_roles(
        actor_roles,
        [ROLE_LOGISTICS_MANAGER],
        message="Only Logistics Managers may approve partial release.",
    )
    del normalized_roles
    package, _, request_record, package_record = _package_context_by_package_id(
        reliefpkg_id,
        actor_id=actor_id,
        actor_roles=actor_roles,
        tenant_context=tenant_context,
        write=True,
    )
    _ensure_actor_assigned_to_queue(
        queue_code=QUEUE_CODE_PARTIAL_RELEASE_APPROVAL,
        entity_type=ENTITY_PACKAGE,
        entity_id=int(package_record.package_id),
        actor_id=actor_id,
        actor_roles=actor_roles or (),
        tenant_context=tenant_context,
        error_message="You are not assigned to approve partial release for this package.",
    )
    if not package_record.partial_release_requested_at:
        raise OperationValidationError({"partial_release": "No partial release request is pending."})
    _update_package_workflow_fields(
        package_record,
        actor_id=actor_id,
        partial_release_approved_by_id=actor_id,
        partial_release_approved_at=timezone.now(),
        partial_release_approval_reason=str(payload.get("approval_reason") or "").strip() or None,
    )
    split_result = split_package(
        package=package,
        request_record=request_record,
        package_record=package_record,
        actor_id=actor_id,
    )
    complete_queue_assignments(
        entity_type=ENTITY_PACKAGE,
        entity_id=int(package_record.package_id),
        queue_code=QUEUE_CODE_PARTIAL_RELEASE_APPROVAL,
        actor_id=actor_id,
    )
    create_role_notifications(
        event_code=EVENT_PARTIAL_RELEASE_APPROVED,
        entity_type=ENTITY_PACKAGE,
        entity_id=int(package_record.package_id),
        message_text=f"Partial release approved for package {package_record.package_no}.",
        role_codes=FULFILLMENT_ROLE_CODES + DISPATCH_ROLE_CODES,
        tenant_id=request_record.beneficiary_tenant_id,
    )
    _cache_idempotent_response_after_commit(
        idempotency.cache_key,
        split_result,
        reservation_key=idempotency.reservation_key,
        reservation_token=idempotency.reservation_token,
    )
    return split_result


@transaction.atomic
def cancel_package(
    reliefpkg_id: int,
    *,
    payload: Mapping[str, Any] | None = None,
    actor_id: str,
    actor_roles: Iterable[str] | None,
    tenant_context: TenantContext,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    idempotency = _begin_idempotent_write(
        endpoint="package_cancel",
        actor_id=actor_id,
        tenant_context=tenant_context,
        resource_id=reliefpkg_id,
        idempotency_key=idempotency_key,
    )
    if idempotency.cached_result is not None:
        return idempotency.cached_result
    del payload
    _require_roles(actor_roles, FULFILLMENT_ROLE_CODES, message="Only fulfillment roles may cancel packages.")
    package, request, request_record, package_record = _package_context_by_package_id(
        reliefpkg_id,
        actor_id=actor_id,
        actor_roles=actor_roles,
        tenant_context=tenant_context,
        write=True,
    )
    if package_record.status_code in {
        PACKAGE_STATUS_DISPATCHED,
        PACKAGE_STATUS_RECEIVED,
        PACKAGE_STATUS_SPLIT,
        PACKAGE_STATUS_CANCELLED,
    }:
        raise OperationValidationError({"cancel": "This package can no longer be cancelled."})

    legs = list(
        package_record.consolidation_legs.select_for_update().order_by("leg_sequence")
    )
    if legs:
        if any(leg.status_code == CONSOLIDATION_LEG_STATUS_IN_TRANSIT for leg in legs):
            raise OperationValidationError(
                {"cancel": "Packages with in-transit consolidation legs cannot be cancelled."}
            )
        if any(leg.status_code != CONSOLIDATION_LEG_STATUS_PLANNED for leg in legs):
            raise OperationValidationError(
                {"cancel": "Only packages whose consolidation legs are still planned can be cancelled."}
            )

    legacy_status = legacy_service._current_package_status(package)
    if legacy_status in {legacy_service.PKG_STATUS_PENDING, "C", "V"}:
        old_rows = legacy_service._selected_plan_for_package(int(package.reliefpkg_id))
        if old_rows:
            legacy_service._apply_stock_delta_for_rows(
                old_rows,
                actor_user_id=actor_id,
                delta_sign=-1,
                update_needs_list=False,
            )

    now = timezone.now()
    for leg in legs:
        record_status_transition(
            entity_type=ENTITY_CONSOLIDATION_LEG,
            entity_id=int(leg.leg_id),
            from_status=leg.status_code,
            to_status=CONSOLIDATION_LEG_STATUS_CANCELLED,
            actor_id=actor_id,
        )
        leg.status_code = CONSOLIDATION_LEG_STATUS_CANCELLED
        leg.update_by_id = actor_id
        leg.update_dtime = now
        leg.version_nbr = int(leg.version_nbr or 0) + 1
        leg.save(update_fields=["status_code", "update_by_id", "update_dtime", "version_nbr"])
        complete_queue_assignments(
            entity_type=ENTITY_CONSOLIDATION_LEG,
            entity_id=int(leg.leg_id),
            actor_id=actor_id,
            completion_status="CANCELLED",
        )

    package.status_code = legacy_service.PKG_STATUS_DRAFT
    package.update_by_id = actor_id
    package.update_dtime = now
    package.version_nbr = int(package.version_nbr or 0) + 1
    if hasattr(package, "save"):
        package.save()

    package_record = _sync_operations_package(
        package,
        request_record=request_record,
        actor_id=actor_id,
        status_code=PACKAGE_STATUS_CANCELLED,
        source_warehouse_id=package_record.source_warehouse_id,
    )
    _update_package_workflow_fields(
        package_record,
        actor_id=actor_id,
        consolidation_status=None,
    )
    complete_queue_assignments(
        entity_type=ENTITY_PACKAGE,
        entity_id=int(package_record.package_id),
        actor_id=actor_id,
        completion_status="CANCELLED",
    )
    OperationsPackageLock.objects.filter(
        package_id=int(package_record.package_id),
        lock_status="ACTIVE",
    ).update(
        lock_status="RELEASED",
        lock_expires_at=now,
    )
    create_role_notifications(
        event_code=EVENT_PACKAGE_CANCELLED,
        entity_type=ENTITY_PACKAGE,
        entity_id=int(package_record.package_id),
        message_text=f"Package {package_record.package_no} was cancelled before dispatch.",
        role_codes=FULFILLMENT_ROLE_CODES + DISPATCH_ROLE_CODES,
        tenant_id=request_record.beneficiary_tenant_id,
    )
    result = {
        "status": PACKAGE_STATUS_CANCELLED,
        "package": _package_summary_payload(package, package_record),
        "request": _request_summary_payload(request, request_record),
    }
    _cache_idempotent_response_after_commit(
        idempotency.cache_key,
        result,
        reservation_key=idempotency.reservation_key,
        reservation_token=idempotency.reservation_token,
    )
    return result


def list_dispatch_queue(*, actor_id: str | None = None, actor_roles: Iterable[str] | None = None, tenant_context: TenantContext) -> dict[str, Any]:
    actor_id = _require_actor_id(actor_id)
    _require_roles(actor_roles, DISPATCH_ROLE_CODES, message="Only dispatch roles may view this queue.")
    package_ids = list(
        actor_queue_queryset(actor_id=actor_id, actor_roles=actor_roles or (), tenant_context=tenant_context)
        .filter(queue_code=QUEUE_CODE_DISPATCH, entity_type=ENTITY_PACKAGE)
        .values_list("entity_id", flat=True)
    )
    results = []
    if not package_ids:
        package_ids = list(
            OperationsPackage.objects.filter(
                status_code__in=[PACKAGE_STATUS_COMMITTED, PACKAGE_STATUS_READY_FOR_DISPATCH]
            )
            .order_by("-committed_at", "-package_id")
            .values_list("package_id", flat=True)[:200]
        )
    for reliefpkg_id in package_ids[:200]:
        package = legacy_service._load_package(int(reliefpkg_id))
        request = legacy_service._load_request(int(package.reliefrqst_id))
        request_record = _sync_operations_request(request, actor_id=actor_id)
        package_record = _sync_operations_package(package, request_record=request_record, actor_id=actor_id)
        if package_record.status_code not in {PACKAGE_STATUS_COMMITTED, PACKAGE_STATUS_READY_FOR_DISPATCH}:
            continue
        try:
            _ensure_package_access(
                package_record,
                actor_id=actor_id,
                actor_roles=actor_roles or (),
                tenant_context=tenant_context,
            )
        except OperationValidationError:
            continue
        dispatch = _ensure_dispatch_record(package=package, package_record=package_record, actor_id=actor_id)
        results.append(
            {
                **_package_summary_payload(package, package_record),
                "request": _request_summary_payload(request, request_record),
                "dispatch": _dispatch_payload(package, dispatch),
            }
        )
    return {"results": results}


def get_dispatch_package(reliefpkg_id: int, *, actor_id: str | None = None, actor_roles: Iterable[str] | None = None, tenant_context: TenantContext) -> dict[str, Any]:
    actor_id = _require_actor_id(actor_id)
    package = legacy_service._load_package(reliefpkg_id)
    request = legacy_service._load_request(int(package.reliefrqst_id))
    request_record = _sync_operations_request(request, actor_id=actor_id)
    package_record = _sync_operations_package(package, request_record=request_record, actor_id=actor_id)
    _ensure_package_access(package_record, actor_id=actor_id, actor_roles=actor_roles or (), tenant_context=tenant_context)
    # Only materialize a dispatch record once the package is committed. Viewing the
    # dispatch page must not side-effect a dispatch_no or status transition for a
    # package that has not yet been committed/approved for dispatch.
    dispatch = None
    if package_record.status_code in {
        PACKAGE_STATUS_COMMITTED,
        PACKAGE_STATUS_READY_FOR_DISPATCH,
        PACKAGE_STATUS_DISPATCHED,
        PACKAGE_STATUS_RECEIVED,
    }:
        dispatch = _ensure_dispatch_record(package=package, package_record=package_record, actor_id=actor_id)
    payload = get_package(int(package.reliefrqst_id), actor_id=actor_id, actor_roles=actor_roles, tenant_context=tenant_context)
    payload["dispatch"] = _dispatch_payload(package, dispatch) if dispatch else None
    payload["request"] = _request_summary_payload(request, request_record)
    payload["waybill"] = get_waybill(reliefpkg_id, actor_id=actor_id, actor_roles=actor_roles, tenant_context=tenant_context) if package.dispatch_dtime else None
    return payload


def _validated_transport_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    driver_name = str(payload.get("driver_name") or "").strip()
    driver_license_last4 = _driver_license_last4(
        payload.get("driver_license_last4") or payload.get("driver_license_no")
    )
    vehicle_id = str(payload.get("vehicle_id") or "").strip() or None
    vehicle_registration = str(payload.get("vehicle_registration") or "").strip() or None
    vehicle_type = str(payload.get("vehicle_type") or "").strip() or None
    errors: dict[str, str] = {}
    departure_dtime = _parse_transport_datetime(payload.get("departure_dtime"), "departure_dtime")
    estimated_arrival_dtime = _parse_transport_datetime(payload.get("estimated_arrival_dtime"), "estimated_arrival_dtime")
    if not driver_name:
        errors["driver_name"] = "driver_name is required for dispatch."
    if not any([vehicle_id, vehicle_registration, vehicle_type]):
        errors["vehicle"] = "vehicle_id, vehicle_registration, or vehicle_type is required for dispatch."
    if departure_dtime is None:
        errors["departure_dtime"] = "departure_dtime is required for dispatch."
    if estimated_arrival_dtime is None:
        errors["estimated_arrival_dtime"] = "estimated_arrival_dtime is required for dispatch."
    if departure_dtime is not None and estimated_arrival_dtime is not None and estimated_arrival_dtime < departure_dtime:
        errors["estimated_arrival_dtime"] = "estimated_arrival_dtime cannot be earlier than departure_dtime."
    if errors:
        raise OperationValidationError(errors)
    return {
        "driver_name": driver_name,
        "driver_license_last4": driver_license_last4,
        "vehicle_id": vehicle_id,
        "vehicle_registration": vehicle_registration,
        "vehicle_type": vehicle_type,
        "transport_mode": str(payload.get("transport_mode") or "").strip() or None,
        "departure_dtime": departure_dtime,
        "estimated_arrival_dtime": estimated_arrival_dtime,
        "transport_notes": str(payload.get("transport_notes") or "").strip() or None,
        "route_override_reason": str(payload.get("route_override_reason") or "").strip() or None,
    }


@transaction.atomic
def submit_dispatch(
    reliefpkg_id: int,
    *,
    payload: Mapping[str, Any],
    actor_id: str,
    actor_roles: Iterable[str] | None = None,
    tenant_context: TenantContext | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    if tenant_context is None:
        return _legacy_submit_dispatch(reliefpkg_id, payload=payload, actor_id=actor_id)
    idempotency = _begin_idempotent_write(
        endpoint="dispatch_handoff",
        actor_id=actor_id,
        tenant_context=tenant_context,
        resource_id=reliefpkg_id,
        idempotency_key=idempotency_key,
    )
    if idempotency.cached_result is not None:
        return idempotency.cached_result
    _require_roles(actor_roles, DISPATCH_ROLE_CODES, message="Only dispatch roles may hand off packages.")
    transport_payload = _validated_transport_payload(payload)
    package = legacy_service._load_package(reliefpkg_id)
    request = legacy_service._load_request(int(package.reliefrqst_id))
    request_record = _sync_operations_request(request, actor_id=actor_id)
    package_record = _sync_operations_package(package, request_record=request_record, actor_id=actor_id)
    _ensure_package_access(
        package_record,
        actor_id=actor_id,
        actor_roles=actor_roles or (),
        tenant_context=tenant_context,
        write=True,
    )
    legacy_result = legacy_service.submit_dispatch(
        reliefpkg_id,
        payload={"transport_mode": transport_payload.get("transport_mode")},
        actor_id=actor_id,
    )
    package = legacy_service._load_package(reliefpkg_id)
    request = legacy_service._load_request(int(package.reliefrqst_id))
    request_record = _sync_operations_request(request, actor_id=actor_id)
    package_record = _sync_operations_package(package, request_record=request_record, actor_id=actor_id, status_code=PACKAGE_STATUS_DISPATCHED)
    dispatch = _ensure_dispatch_record(package=package, package_record=package_record, actor_id=actor_id)
    if dispatch.status_code != DISPATCH_STATUS_IN_TRANSIT:
        record_status_transition(
            entity_type=ENTITY_DISPATCH,
            entity_id=int(dispatch.dispatch_id),
            from_status=dispatch.status_code,
            to_status=DISPATCH_STATUS_IN_TRANSIT,
            actor_id=actor_id,
        )
    dispatch.status_code = DISPATCH_STATUS_IN_TRANSIT
    dispatch.dispatch_at = timezone.now()
    dispatch.dispatched_by_id = actor_id
    dispatch.source_warehouse_id = package_record.effective_dispatch_source_warehouse_id
    dispatch.destination_tenant_id = package_record.destination_tenant_id
    dispatch.destination_agency_id = package_record.destination_agency_id
    dispatch.update_by_id = actor_id
    dispatch.update_dtime = timezone.now()
    dispatch.version_nbr = int(dispatch.version_nbr or 0) + 1
    dispatch.save()
    OperationsDispatchTransport.objects.update_or_create(dispatch_id=int(dispatch.dispatch_id), defaults=transport_payload)
    OperationsWaybill.objects.update_or_create(
        dispatch_id=int(dispatch.dispatch_id),
        defaults={
            "waybill_no": legacy_result["waybill_no"],
            "artifact_payload_json": legacy_result["waybill_payload"],
            "artifact_version": 1,
            "generated_by_id": actor_id,
            "generated_at": timezone.now(),
            "is_final_flag": True,
        },
    )
    complete_queue_assignments(entity_type=ENTITY_PACKAGE, entity_id=reliefpkg_id, queue_code=QUEUE_CODE_DISPATCH, actor_id=actor_id)
    assign_user_to_queue(
        queue_code=QUEUE_CODE_RECEIPT,
        entity_type=ENTITY_PACKAGE,
        entity_id=reliefpkg_id,
        user_id=request_record.submitted_by_id or request.create_by_id or actor_id,
        tenant_id=request_record.beneficiary_tenant_id,
    )
    create_role_notifications(
        event_code=EVENT_DISPATCH_COMPLETED,
        entity_type=ENTITY_PACKAGE,
        entity_id=reliefpkg_id,
        message_text=f"Package {package.tracking_no} has been dispatched and is awaiting receipt confirmation.",
        role_codes=FULFILLMENT_ROLE_CODES + DISPATCH_ROLE_CODES,
        tenant_id=request_record.beneficiary_tenant_id,
        queue_code=QUEUE_CODE_RECEIPT,
    )
    next_request_status = REQUEST_STATUS_FULFILLED if _request_fully_dispatched(int(request.reliefrqst_id)) else REQUEST_STATUS_PARTIALLY_FULFILLED
    _sync_operations_request(request, actor_id=actor_id, status_code=next_request_status)
    result = {
        **legacy_result,
        "dispatch": _dispatch_payload(package, dispatch),
        "waybill": get_waybill(reliefpkg_id, actor_id=actor_id, actor_roles=actor_roles, tenant_context=tenant_context),
    }
    _cache_idempotent_response_after_commit(
        idempotency.cache_key,
        result,
        reservation_key=idempotency.reservation_key,
        reservation_token=idempotency.reservation_token,
    )
    return result


def get_waybill(
    reliefpkg_id: int,
    *,
    actor_id: str | None = None,
    actor_roles: Iterable[str] | None = None,
    tenant_context: TenantContext | None = None,
) -> dict[str, Any]:
    if tenant_context is None:
        return _legacy_get_waybill(reliefpkg_id)
    actor_id = _require_actor_id(actor_id)
    package = legacy_service._load_package(reliefpkg_id)
    request = legacy_service._load_request(int(package.reliefrqst_id))
    request_record = _sync_operations_request(request, actor_id=actor_id)
    package_record = _sync_operations_package(package, request_record=request_record, actor_id=actor_id)
    _ensure_package_access(package_record, actor_id=actor_id, actor_roles=actor_roles or (), tenant_context=tenant_context)
    dispatch = OperationsDispatch.objects.filter(package_id=reliefpkg_id).first()
    if dispatch is not None:
        waybill = OperationsWaybill.objects.filter(dispatch_id=int(dispatch.dispatch_id)).order_by("-generated_at", "-waybill_id").first()
        if waybill is not None:
            return {
                "waybill_no": waybill.waybill_no,
                "waybill_payload": waybill.artifact_payload_json,
                "persisted": True,
                "compatibility_bridge": False,
            }
    return legacy_service.get_waybill(reliefpkg_id)


@transaction.atomic
def confirm_receipt(
    reliefpkg_id: int,
    *,
    payload: Mapping[str, Any],
    actor_id: str,
    actor_roles: Iterable[str] | None,
    tenant_context: TenantContext,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    idempotency = _begin_idempotent_write(
        endpoint="receipt_confirm",
        actor_id=actor_id,
        tenant_context=tenant_context,
        resource_id=reliefpkg_id,
        idempotency_key=idempotency_key,
    )
    if idempotency.cached_result is not None:
        return idempotency.cached_result
    package = legacy_service._load_package(reliefpkg_id, for_update=True)
    request = legacy_service._load_request(int(package.reliefrqst_id), for_update=True)
    request_record = _sync_operations_request(request, actor_id=actor_id)
    package_record = _sync_operations_package(package, request_record=request_record, actor_id=actor_id)
    _ensure_package_access(package_record, actor_id=actor_id, actor_roles=actor_roles or (), tenant_context=tenant_context, write=True)
    if package.dispatch_dtime is None:
        raise OperationValidationError({"receipt": "Package has not been dispatched."})
    if package.received_dtime is not None:
        raise OperationValidationError({"receipt": "Receipt has already been confirmed."})
    dispatch = OperationsDispatch.objects.filter(package_id=reliefpkg_id).first()
    if dispatch is None:
        raise OperationValidationError({"receipt": "Dispatch record is missing for this package."})
    _ensure_actor_assigned_to_queue(
        queue_code=QUEUE_CODE_RECEIPT,
        entity_type=ENTITY_PACKAGE,
        entity_id=reliefpkg_id,
        actor_id=actor_id,
        actor_roles=actor_roles or (),
        tenant_context=tenant_context,
        error_message="You are not assigned to the receipt queue for this package.",
    )
    now = timezone.now()
    package.received_by_id = actor_id
    package.received_dtime = now
    package.status_code = legacy_service.PKG_STATUS_COMPLETED
    package.update_by_id = actor_id
    package.update_dtime = now
    package.version_nbr = int(package.version_nbr or 0) + 1
    package.save()
    _sync_operations_package(package, request_record=request_record, actor_id=actor_id, status_code=PACKAGE_STATUS_RECEIVED)
    if dispatch.status_code != DISPATCH_STATUS_RECEIVED:
        record_status_transition(
            entity_type=ENTITY_DISPATCH,
            entity_id=int(dispatch.dispatch_id),
            from_status=dispatch.status_code,
            to_status=DISPATCH_STATUS_RECEIVED,
            actor_id=actor_id,
        )
    dispatch.status_code = DISPATCH_STATUS_RECEIVED
    dispatch.update_by_id = actor_id
    dispatch.update_dtime = now
    dispatch.version_nbr = int(dispatch.version_nbr or 0) + 1
    dispatch.save()
    receipt_artifact = {
        "receipt_status_code": DISPATCH_STATUS_RECEIVED,
        "received_by_user_id": actor_id,
        "received_by_name": str(payload.get("received_by_name") or actor_id).strip(),
        "received_at": now.isoformat(),
        "receipt_notes": str(payload.get("receipt_notes") or "").strip() or None,
        "beneficiary_delivery_ref": str(payload.get("beneficiary_delivery_ref") or "").strip() or None,
    }
    OperationsReceipt.objects.update_or_create(
        dispatch_id=int(dispatch.dispatch_id),
        defaults={
            "receipt_status_code": DISPATCH_STATUS_RECEIVED,
            "received_by_user_id": actor_id,
            "received_by_name": receipt_artifact["received_by_name"],
            "received_at": now,
            "receipt_notes": receipt_artifact["receipt_notes"],
            "receipt_artifact_json": receipt_artifact,
            "beneficiary_delivery_ref": receipt_artifact["beneficiary_delivery_ref"],
        },
    )
    complete_queue_assignments(entity_type=ENTITY_PACKAGE, entity_id=reliefpkg_id, queue_code=QUEUE_CODE_RECEIPT, actor_id=actor_id)
    create_role_notifications(
        event_code=EVENT_RECEIPT_CONFIRMED,
        entity_type=ENTITY_PACKAGE,
        entity_id=reliefpkg_id,
        message_text=f"Receipt confirmed for package {package.tracking_no}.",
        role_codes=FULFILLMENT_ROLE_CODES + DISPATCH_ROLE_CODES,
        tenant_id=request_record.beneficiary_tenant_id,
    )
    result = {
        "status": "RECEIVED",
        "reliefpkg_id": reliefpkg_id,
        "package_tracking_no": package.tracking_no,
        "receipt": receipt_artifact,
    }
    _cache_idempotent_response_after_commit(
        idempotency.cache_key,
        result,
        reservation_key=idempotency.reservation_key,
        reservation_token=idempotency.reservation_token,
    )
    return result


def list_tasks(*, actor_id: str, actor_roles: Iterable[str] | None, tenant_context: TenantContext) -> dict[str, Any]:
    return {
        "queue_assignments": _serialize_queue_assignments(actor_id=actor_id, actor_roles=actor_roles or (), tenant_context=tenant_context),
        "notifications": _serialize_notifications(actor_id=actor_id, actor_roles=actor_roles or (), tenant_context=tenant_context),
    }
