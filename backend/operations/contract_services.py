from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping, Sequence

from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.utils.dateparse import parse_datetime
from django.utils import timezone

from api.rbac import (
    PERM_OPERATIONS_FULFILLMENT_MODE_SET,
    PERM_OPERATIONS_PACKAGE_ALLOCATE,
    PERM_OPERATIONS_STAGING_WAREHOUSE_OVERRIDE,
)
from api.tenancy import TenantContext, can_access_tenant
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
    ROLE_LOGISTICS_MANAGER,
    ROLE_SYSTEM_ADMINISTRATOR,
    STAGING_SELECTION_BASIS_MANUAL_OVERRIDE,
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
from operations import services as legacy_service
from operations.staging_selection import (
    beneficiary_parish_code_for_request,
    get_staging_hub_details,
    recommend_staging_hub,
)
from replenishment.legacy_models import (
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


def _mask_sensitive_value(value: str | None) -> str | None:
    if not value:
        return value
    trimmed = str(value).strip()
    if len(trimmed) <= 4:
        return trimmed
    return f"{'*' * (len(trimmed) - 4)}{trimmed[-4:]}"


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
        )
    elif status_code and status_code != original_status:
        record_status_transition(
            entity_type=ENTITY_PACKAGE,
            entity_id=int(package.reliefpkg_id),
            from_status=original_status,
            to_status=status_code,
            actor_id=actor_id,
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
    tenant_id = operations_policy.resolve_odpem_fulfillment_tenant_id()
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
    should_resolve_recommendation = bool(
        _is_staged_fulfillment_mode(fulfillment_mode)
        or existing_staging_id not in (None, "")
        or requested_staging_id is not _UNSET
        or payload.get("staging_override_reason")
    )
    if should_resolve_recommendation:
        parish_code = beneficiary_parish_code_for_request(int(reliefrqst_id))
        recommendation = recommend_staging_hub(beneficiary_parish_code=parish_code)
        recommended_id = recommendation.recommended_staging_warehouse_id
        recommendation_basis = recommendation.staging_selection_basis
    else:
        recommended_id = None
        recommendation_basis = None
    staging_override_reason = str(
        payload.get("staging_override_reason")
        or (existing_package_record.staging_override_reason if existing_package_record is not None else "")
        or ""
    ).strip() or None
    staging_warehouse_id = existing_staging_id
    if requested_staging_id is not _UNSET:
        staging_warehouse_id = requested_staging_id
    elif staging_warehouse_id in (None, ""):
        staging_warehouse_id = recommended_id

    staging_selection_basis = (
        recommendation_basis
        or (
            existing_package_record.staging_selection_basis
            if existing_package_record is not None
            else None
        )
    )

    if _is_staged_fulfillment_mode(fulfillment_mode):
        if staging_warehouse_id is None:
            raise OperationValidationError(
                {"staging_warehouse_id": "A staging warehouse is required for staged fulfillment."}
            )
        staging_hub = get_staging_hub_details(int(staging_warehouse_id))
        if staging_hub is None:
            raise OperationValidationError(
                {
                    "staging_warehouse_id": (
                        "Selected staging warehouse must be an active ODPEM-owned SUB-HUB."
                    )
                }
            )
        if recommended_id is not None and int(staging_warehouse_id) != int(recommended_id):
            _require_permission(
                permissions,
                PERM_OPERATIONS_STAGING_WAREHOUSE_OVERRIDE,
                field_name="staging_warehouse_id",
                message=(
                    "Selecting a non-recommended staging warehouse requires "
                    "operations.staging_warehouse.override."
                ),
            )
            if not staging_override_reason:
                raise OperationValidationError(
                    {
                        "staging_override_reason": (
                            "A manual override reason is required when the selected staging "
                            "warehouse differs from the recommendation."
                        )
                    }
                )
            staging_selection_basis = STAGING_SELECTION_BASIS_MANUAL_OVERRIDE
    else:
        staging_warehouse_id = None
        staging_selection_basis = None
        staging_override_reason = None

    return {
        "fulfillment_mode": fulfillment_mode,
        "recommended_staging_warehouse_id": recommended_id,
        "staging_warehouse_id": staging_warehouse_id,
        "staging_selection_basis": staging_selection_basis,
        "staging_override_reason": staging_override_reason,
        "recommendation": {
            "recommended_staging_warehouse_id": recommended_id,
            "staging_selection_basis": recommendation_basis,
        },
    }


def _request_summary_payload(request: ReliefRqst, request_record: OperationsReliefRequest) -> dict[str, Any]:
    payload = legacy_service._request_summary(request)
    payload["legacy_status_code"] = payload.pop("status_code")
    payload["status_code"] = request_record.status_code
    payload["status_label"] = STATUS_LABELS.get(request_record.status_code, request_record.status_code.title())
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
            "driver_license_no": _mask_sensitive_value(transport.driver_license_no),
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
        "driver_license_no": _mask_sensitive_value(leg.driver_license_no),
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
        OperationsConsolidationLegItem.objects.filter(
            leg_id__in=[int(leg.leg_id) for leg in existing_legs]
        ).delete()
        OperationsConsolidationLeg.objects.filter(
            leg_id__in=[int(leg.leg_id) for leg in existing_legs]
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
        inventory.usable_qty = legacy_service._quantize_qty(inventory.usable_qty) + item.quantity
        inventory.update_by_id = actor_id
        inventory.update_dtime = now
        inventory.version_nbr = int(inventory.version_nbr or 0) + 1
        inventory.save(update_fields=["usable_qty", "update_by_id", "update_dtime", "version_nbr"])

        staging_batch_id = int(legacy_service._next_int_id("itembatch", "batch_id"))
        ItemBatch.objects.create(
            batch_id=staging_batch_id,
            inventory_id=int(leg.staging_warehouse_id),
            item_id=int(item.item_id),
            batch_no=source_batch.batch_no,
            batch_date=source_batch.batch_date,
            expiry_date=source_batch.expiry_date,
            usable_qty=item.quantity,
            reserved_qty=legacy_service._quantize_qty(0),
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
    request = legacy_service._load_request(reliefrqst_id)
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
    request = legacy_service._load_request(int(result["reliefrqst_id"]))
    _sync_operations_request(
        request,
        actor_id=actor_id,
        decision=decision,
        status_code=REQUEST_STATUS_DRAFT,
        source_needs_list_id=source_needs_list_id,
        requesting_agency_id=requesting_agency_id,
    )
    return get_request(int(result["reliefrqst_id"]), actor_id=actor_id, tenant_context=tenant_context, actor_roles=())


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
    current_request = legacy_service._load_request(reliefrqst_id)
    effective_agency_raw = mutable_payload.get("agency_id", current_request.agency_id)
    agency_id = _parse_int_or_raise(effective_agency_raw, "agency_id")
    if agency_id is None:
        raise OperationValidationError({"agency_id": "agency_id is required."})
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
    request = legacy_service._load_request(reliefrqst_id)
    _sync_operations_request(
        request,
        actor_id=actor_id,
        decision=decision,
        source_needs_list_id=source_needs_list_id,
        requesting_agency_id=requesting_agency_id,
    )
    return get_request(int(result["reliefrqst_id"]), actor_id=actor_id, tenant_context=tenant_context, actor_roles=())


@transaction.atomic
def submit_request(reliefrqst_id: int, *, actor_id: str, tenant_context: TenantContext) -> dict[str, Any]:
    legacy_service.submit_request(reliefrqst_id, actor_id=actor_id, tenant_context=tenant_context)
    request = legacy_service._load_request(reliefrqst_id)
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
    return get_request(reliefrqst_id, actor_id=actor_id, tenant_context=tenant_context, actor_roles=())


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
) -> dict[str, Any]:
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
    package, request, request_record, package_record = _package_context_by_package_id(
        reliefpkg_id,
        actor_id=actor_id,
        actor_roles=actor_roles,
        tenant_context=tenant_context,
    )
    del package, request, request_record
    return {
        "package": _package_summary_payload(
            legacy_service._load_package(reliefpkg_id),
            package_record,
        ),
        "results": [
            _consolidation_leg_payload(leg)
            for leg in package_record.consolidation_legs.order_by("leg_sequence").prefetch_related("items")
        ],
    }


def get_package_allocation_options(reliefrqst_id: int, *, source_warehouse_id: int | None = None, actor_id: str | None = None, actor_roles: Iterable[str] | None = None, tenant_context: TenantContext) -> dict[str, Any]:
    actor_id = _require_actor_id(actor_id)
    request = legacy_service._load_request(reliefrqst_id)
    request_probe = _request_access_probe_from_legacy(request)
    _ensure_fulfillment_request_access(request_probe, actor_id=actor_id, actor_roles=actor_roles or (), tenant_context=tenant_context)
    return legacy_service.get_package_allocation_options(reliefrqst_id, source_warehouse_id=source_warehouse_id)


def get_item_allocation_options(
    reliefrqst_id: int,
    item_id: int,
    *,
    source_warehouse_id: int,
    draft_allocations: Sequence[Mapping[str, Any]] | None = None,
    actor_id: str | None = None,
    actor_roles: Iterable[str] | None = None,
    tenant_context: TenantContext,
) -> dict[str, Any]:
    """Return allocation candidates for a single item from a single warehouse."""
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
    payload: Mapping[str, Any],
    actor_id: str | None = None,
    actor_roles: Iterable[str] | None = None,
    tenant_context: TenantContext,
) -> dict[str, Any]:
    actor_id = _require_actor_id(actor_id)
    requested_source_warehouse_id = _optional_positive_int_payload_value(payload, "source_warehouse_id")
    if requested_source_warehouse_id in (_UNSET, None):
        raise OperationValidationError({"source_warehouse_id": "source_warehouse_id is required."})

    draft_allocations = payload.get("draft_allocations", [])
    if draft_allocations is None:
        draft_allocations = []
    if not isinstance(draft_allocations, list):
        raise OperationValidationError({"draft_allocations": "draft_allocations must be provided as an array."})

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
        source_warehouse_id=int(requested_source_warehouse_id),
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
) -> dict[str, Any]:
    _require_roles(actor_roles, FULFILLMENT_ROLE_CODES, message="Only fulfillment roles may modify packages.")
    requested_source_warehouse_id = _optional_positive_int_payload_value(payload, "source_warehouse_id")
    validated_allocations = _validate_allocation_rows(payload["allocations"]) if "allocations" in payload else None
    request = legacy_service._load_request(reliefrqst_id, for_update=True)
    request_probe = _request_access_probe_from_legacy(request)
    _ensure_fulfillment_request_access(request_probe, actor_id=actor_id, actor_roles=actor_roles or (), tenant_context=tenant_context, write=True)
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
    )
    result = legacy_service.save_package(reliefrqst_id, payload=payload, actor_id=actor_id)
    # Re-sync request after legacy save to keep the operations status at
    # APPROVED_FOR_FULFILLMENT (the legacy save sets status_code=2 which
    # the mapping interprets as CANCELLED).
    request = legacy_service._load_request(reliefrqst_id)
    request_record = _sync_operations_request(request, actor_id=actor_id, status_code=REQUEST_STATUS_APPROVED_FOR_FULFILLMENT)
    package = legacy_service._current_package_for_request(reliefrqst_id)
    if not package_locked_before_save and package is not None:
        _acquire_package_lock(int(package.reliefpkg_id), actor_id=actor_id, actor_roles=actor_roles or ())
    if package is None:
        return result
    first_inventory_id: int | None | object = _UNSET
    if validated_allocations:
        first_inventory_id = validated_allocations[0]["source_warehouse_id"]
    if requested_source_warehouse_id is not _UNSET:
        first_inventory_id = requested_source_warehouse_id
    status_code = PACKAGE_STATUS_DRAFT
    override_status = None
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
        source_warehouse_id=first_inventory_id,
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
        OperationsAllocationLine.objects.filter(package=package_record).delete()
        lines_to_create = []
        now = timezone.now()
        for allocation in validated_allocations:
            lines_to_create.append(
                OperationsAllocationLine(
                    package=package_record,
                    item_id=allocation["item_id"],
                    source_warehouse_id=allocation["source_warehouse_id"],
                    batch_id=allocation["batch_id"],
                    quantity=allocation["quantity"],
                    source_type=allocation["source_type"],
                    source_record_id=allocation["source_record_id"],
                    uom_code=allocation["uom_code"],
                    create_by_id=actor_id,
                    create_dtime=now,
                    update_by_id=actor_id,
                    update_dtime=now,
                )
            )
        if lines_to_create:
            OperationsAllocationLine.objects.bulk_create(lines_to_create)
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
                source_warehouse_id=first_inventory_id,
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
        return get_package(reliefrqst_id, actor_id=actor_id, actor_roles=actor_roles, tenant_context=tenant_context)
    return {
        **result,
        "package_status_code": package_record.status_code,
        "package_status_label": STATUS_LABELS.get(package_record.status_code, package_record.status_code.title()),
        "lock": _package_lock_payload(int(package.reliefpkg_id)),
    }


@transaction.atomic
def approve_override(
    reliefrqst_id: int,
    *,
    payload: Mapping[str, Any],
    actor_id: str,
    actor_roles: Iterable[str] | None,
    tenant_context: TenantContext,
) -> dict[str, Any]:
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
) -> dict[str, Any]:
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
    leg.driver_license_no = transport_payload["driver_license_no"]
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
    return {
        "status": CONSOLIDATION_LEG_STATUS_IN_TRANSIT,
        "package": _package_summary_payload(package, package_record),
        "leg": _consolidation_leg_payload(leg),
    }


@transaction.atomic
def receive_consolidation_leg(
    reliefpkg_id: int,
    leg_id: int,
    *,
    payload: Mapping[str, Any],
    actor_id: str,
    actor_roles: Iterable[str] | None,
    tenant_context: TenantContext,
) -> dict[str, Any]:
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
    return {
        "status": leg.status_code,
        "package": _package_summary_payload(package, package_record),
        "leg": _consolidation_leg_payload(leg),
    }


def get_consolidation_leg_waybill(
    reliefpkg_id: int,
    leg_id: int,
    *,
    actor_id: str | None = None,
    actor_roles: Iterable[str] | None = None,
    tenant_context: TenantContext,
) -> dict[str, Any]:
    actor_id = _require_actor_id(actor_id)
    _, _, _, package_record = _package_context_by_package_id(
        reliefpkg_id,
        actor_id=actor_id,
        actor_roles=actor_roles,
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
) -> dict[str, Any]:
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
    collected_by_id_ref = str(payload.get("collected_by_id_ref") or "").strip() or None
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
        collected_by_id_ref=collected_by_id_ref,
        released_by_user_id=actor_id,
        released_by_name=released_by_name,
        released_at=now,
        release_notes=release_notes,
        release_artifact_json={
            "staging_warehouse_id": package_record.staging_warehouse_id,
            "tenant_id": pickup_tenant_id,
            "collected_by_name": collected_by_name,
            "collected_by_id_ref": collected_by_id_ref,
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
    return {
        "status": "RECEIVED",
        "package": _package_summary_payload(package, package_record),
    }


def request_partial_release(
    reliefpkg_id: int,
    *,
    payload: Mapping[str, Any],
    actor_id: str,
    actor_roles: Iterable[str] | None,
    tenant_context: TenantContext,
) -> dict[str, Any]:
    _require_roles(actor_roles, FULFILLMENT_ROLE_CODES, message="Only fulfillment roles may request partial release.")
    package, request, request_record, package_record = _package_context_by_package_id(
        reliefpkg_id,
        actor_id=actor_id,
        actor_roles=actor_roles,
        tenant_context=tenant_context,
        write=True,
    )
    del package
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
    return {
        "status": "PARTIAL_RELEASE_REQUESTED",
        "package": _package_summary_payload(
            legacy_service._load_package(reliefpkg_id),
            package_record,
        ),
    }


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
) -> dict[str, Any]:
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
    return split_result


@transaction.atomic
def cancel_package(
    reliefpkg_id: int,
    *,
    payload: Mapping[str, Any] | None = None,
    actor_id: str,
    actor_roles: Iterable[str] | None,
    tenant_context: TenantContext,
) -> dict[str, Any]:
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
    return {
        "status": PACKAGE_STATUS_CANCELLED,
        "package": _package_summary_payload(package, package_record),
        "request": _request_summary_payload(request, request_record),
    }


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
    dispatch = _ensure_dispatch_record(package=package, package_record=package_record, actor_id=actor_id)
    payload = get_package(int(package.reliefrqst_id), actor_id=actor_id, actor_roles=actor_roles, tenant_context=tenant_context)
    payload["dispatch"] = _dispatch_payload(package, dispatch)
    payload["request"] = _request_summary_payload(request, request_record)
    payload["waybill"] = get_waybill(reliefpkg_id, actor_id=actor_id, actor_roles=actor_roles, tenant_context=tenant_context) if package.dispatch_dtime else None
    return payload


def _validated_transport_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    driver_name = str(payload.get("driver_name") or "").strip()
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
        "driver_license_no": str(payload.get("driver_license_no") or "").strip() or None,
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
    actor_roles: Iterable[str] | None,
    tenant_context: TenantContext,
) -> dict[str, Any]:
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
    dispatch.source_warehouse_id = package_record.source_warehouse_id
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
    return {
        **legacy_result,
        "dispatch": _dispatch_payload(package, dispatch),
        "waybill": get_waybill(reliefpkg_id, actor_id=actor_id, actor_roles=actor_roles, tenant_context=tenant_context),
    }


def get_waybill(reliefpkg_id: int, *, actor_id: str | None = None, actor_roles: Iterable[str] | None = None, tenant_context: TenantContext) -> dict[str, Any]:
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
) -> dict[str, Any]:
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
    return {
        "status": "RECEIVED",
        "reliefpkg_id": reliefpkg_id,
        "package_tracking_no": package.tracking_no,
        "receipt": receipt_artifact,
    }


def list_tasks(*, actor_id: str, actor_roles: Iterable[str] | None, tenant_context: TenantContext) -> dict[str, Any]:
    return {
        "queue_assignments": _serialize_queue_assignments(actor_id=actor_id, actor_roles=actor_roles or (), tenant_context=tenant_context),
        "notifications": _serialize_notifications(actor_id=actor_id, actor_roles=actor_roles or (), tenant_context=tenant_context),
    }
