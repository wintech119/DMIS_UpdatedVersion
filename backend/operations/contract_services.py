from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any, Iterable, Mapping

from django.db import transaction
from django.utils import timezone

from api.tenancy import TenantContext, can_access_tenant
from operations import policy as operations_policy
from operations.constants import (
    DISPATCH_ROLE_CODES,
    DISPATCH_STATUS_IN_TRANSIT,
    DISPATCH_STATUS_READY,
    DISPATCH_STATUS_RECEIVED,
    ELIGIBILITY_ROLE_CODES,
    EVENT_DISPATCH_COMPLETED,
    EVENT_OVERRIDE_APPROVED,
    EVENT_OVERRIDE_REQUESTED,
    EVENT_PACKAGE_COMMITTED,
    EVENT_PACKAGE_LOCKED,
    EVENT_RECEIPT_CONFIRMED,
    EVENT_REQUEST_APPROVED,
    EVENT_REQUEST_INELIGIBLE,
    EVENT_REQUEST_REJECTED,
    EVENT_REQUEST_SUBMITTED,
    FULFILLMENT_ROLE_CODES,
    ORIGIN_MODE_SELF,
    PACKAGE_STATUS_COMMITTED,
    PACKAGE_STATUS_DRAFT,
    PACKAGE_STATUS_PENDING_OVERRIDE_APPROVAL,
    PACKAGE_STATUS_RECEIVED,
    PACKAGE_STATUS_DISPATCHED,
    QUEUE_CODE_DISPATCH,
    QUEUE_CODE_ELIGIBILITY,
    QUEUE_CODE_FULFILLMENT,
    QUEUE_CODE_OVERRIDE,
    QUEUE_CODE_RECEIPT,
    REQUEST_STATUS_APPROVED_FOR_FULFILLMENT,
    REQUEST_STATUS_DRAFT,
    REQUEST_STATUS_FULFILLED,
    REQUEST_STATUS_INELIGIBLE,
    REQUEST_STATUS_PARTIALLY_FULFILLED,
    REQUEST_STATUS_REJECTED,
    REQUEST_STATUS_SUBMITTED,
    REQUEST_STATUS_UNDER_ELIGIBILITY_REVIEW,
    ROLE_LOGISTICS_MANAGER,
    ROLE_SYSTEM_ADMINISTRATOR,
    STATUS_LABELS,
    normalize_role_codes,
)
from operations.exceptions import OperationValidationError
from operations.models import (
    OperationsDispatch,
    OperationsDispatchTransport,
    OperationsEligibilityDecision,
    OperationsPackage,
    OperationsPackageLock,
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
from replenishment.legacy_models import ReliefPkg, ReliefRqst

ENTITY_REQUEST = "RELIEF_REQUEST"
ENTITY_PACKAGE = "PACKAGE"
ENTITY_DISPATCH = "DISPATCH"

REQUEST_FILTERS = {
    "draft": {REQUEST_STATUS_DRAFT},
    "awaiting": {REQUEST_STATUS_SUBMITTED, REQUEST_STATUS_UNDER_ELIGIBILITY_REVIEW},
    "submitted": {REQUEST_STATUS_APPROVED_FOR_FULFILLMENT, REQUEST_STATUS_PARTIALLY_FULFILLED},
    "processing": {REQUEST_STATUS_UNDER_ELIGIBILITY_REVIEW, REQUEST_STATUS_APPROVED_FOR_FULFILLMENT, REQUEST_STATUS_PARTIALLY_FULFILLED},
    "completed": {REQUEST_STATUS_FULFILLED},
    "dispatched": {REQUEST_STATUS_PARTIALLY_FULFILLED, REQUEST_STATUS_FULFILLED},
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
        legacy_service.STATUS_CANCELLED: "CANCELLED",
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


def _assign_if_changed(record: Any, field_name: str, value: Any, changed_fields: list[str]) -> None:
    if getattr(record, field_name) != value:
        setattr(record, field_name, value)
        changed_fields.append(field_name)


def _sync_operations_request(
    request: ReliefRqst,
    *,
    actor_id: str,
    decision: operations_policy.ReliefRequestWriteDecision | None = None,
    status_code: str | None = None,
    source_needs_list_id: int | None = None,
    requesting_agency_id: int | None = None,
) -> OperationsReliefRequest:
    record = _ops_request_from_legacy(request, actor_id=actor_id)
    original_status = record.status_code
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
        if requesting_agency_id is not None:
            _assign_if_changed(record, "requesting_agency_id", int(requesting_agency_id), changed_fields)
        elif decision.origin_mode == ORIGIN_MODE_SELF:
            _assign_if_changed(record, "requesting_agency_id", int(request.agency_id), changed_fields)
    _assign_if_changed(record, "request_no", request.tracking_no, changed_fields)
    _assign_if_changed(record, "event_id", request.eligible_event_id, changed_fields)
    _assign_if_changed(record, "request_date", request.request_date, changed_fields)
    _assign_if_changed(record, "urgency_code", request.urgency_ind, changed_fields)
    _assign_if_changed(record, "notes_text", request.rqst_notes_text, changed_fields)
    if source_needs_list_id is not None:
        _assign_if_changed(record, "source_needs_list_id", source_needs_list_id, changed_fields)
    _assign_if_changed(record, "reviewed_by_id", request.review_by_id, changed_fields)
    _assign_if_changed(record, "reviewed_at", request.review_dtime, changed_fields)
    if status_code:
        _assign_if_changed(record, "status_code", status_code, changed_fields)
    if changed_fields:
        record.update_by_id = actor_id
        record.update_dtime = timezone.now()
        record.version_nbr = int(record.version_nbr or 0) + 1
        changed_fields.extend(["update_by_id", "update_dtime", "version_nbr"])
        record.save(update_fields=changed_fields)
    if status_code and status_code != original_status:
        record_status_transition(
            entity_type=ENTITY_REQUEST,
            entity_id=int(request.reliefrqst_id),
            from_status=original_status,
            to_status=status_code,
            actor_id=actor_id,
        )
    return record


def _sync_operations_package(
    package: ReliefPkg,
    *,
    request_record: OperationsReliefRequest,
    actor_id: str,
    status_code: str | None = None,
    override_status_code: str | None = None,
    source_warehouse_id: int | None = None,
) -> OperationsPackage:
    record, created = OperationsPackage.objects.get_or_create(
        package_id=int(package.reliefpkg_id),
        defaults={
            "package_no": package.tracking_no,
            "relief_request_id": int(package.reliefrqst_id),
            "source_warehouse_id": source_warehouse_id,
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
    if source_warehouse_id is not None:
        _assign_if_changed(record, "source_warehouse_id", int(source_warehouse_id), changed_fields)
    if status_code:
        _assign_if_changed(record, "status_code", status_code, changed_fields)
    if override_status_code is not None:
        _assign_if_changed(record, "override_status_code", override_status_code, changed_fields)
    if record.status_code == PACKAGE_STATUS_COMMITTED and record.committed_at is None:
        record.committed_at = timezone.now()
        changed_fields.append("committed_at")
    if record.status_code == PACKAGE_STATUS_DISPATCHED and record.dispatched_at is None:
        record.dispatched_at = timezone.now()
        changed_fields.append("dispatched_at")
    if record.status_code == PACKAGE_STATUS_RECEIVED and record.received_at is None:
        record.received_at = timezone.now()
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
    dispatch, created = OperationsDispatch.objects.get_or_create(
        package_id=int(package.reliefpkg_id),
        defaults={
            "dispatch_no": legacy_service._tracking_no("DP", int(package.reliefpkg_id)),
            "status_code": DISPATCH_STATUS_READY,
            "source_warehouse_id": package_record.source_warehouse_id,
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
    return dispatch


def _require_roles(actor_roles: Iterable[str] | None, allowed_roles: Iterable[str], *, message: str) -> tuple[str, ...]:
    normalized_roles = normalize_role_codes(actor_roles)
    if ROLE_SYSTEM_ADMINISTRATOR in normalized_roles:
        return normalized_roles
    allowed = set(allowed_roles)
    if not any(role in allowed for role in normalized_roles):
        raise OperationValidationError({"roles": message})
    return normalized_roles


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
        if (
            existing
            and existing.lock_status == "ACTIVE"
            and existing.lock_owner_user_id != actor_id
            and (existing.lock_expires_at is None or existing.lock_expires_at > now)
        ):
            raise OperationValidationError({"lock": "Package is locked by another fulfillment actor."})
        if existing is None:
            lock = OperationsPackageLock.objects.create(
                package_id=int(package_id),
                lock_owner_user_id=actor_id,
                lock_owner_role_code=owner_role,
                lock_started_at=now,
                lock_expires_at=expires_at,
                lock_status="ACTIVE",
            )
            created = True
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


def _ensure_request_access(
    request_record: OperationsReliefRequest,
    *,
    actor_id: str,
    actor_roles: Iterable[str],
    tenant_context: TenantContext,
) -> None:
    relevant_tenants = [request_record.requesting_tenant_id, request_record.beneficiary_tenant_id]
    for tenant_id in relevant_tenants:
        if tenant_id and can_access_tenant(tenant_context, int(tenant_id), write=False):
            return
    if actor_queue_queryset(actor_id=actor_id, actor_roles=actor_roles, tenant_context=tenant_context).filter(
        entity_type=ENTITY_REQUEST,
        entity_id=int(request_record.relief_request_id),
    ).exists():
        return
    raise OperationValidationError({"scope": "Request is outside the active tenant or workflow assignment scope."})


def _ensure_package_access(
    package_record: OperationsPackage,
    *,
    actor_id: str,
    actor_roles: Iterable[str],
    tenant_context: TenantContext,
) -> None:
    request_record = OperationsReliefRequest.objects.get(relief_request_id=int(package_record.relief_request_id))
    _ensure_request_access(request_record, actor_id=actor_id, actor_roles=actor_roles, tenant_context=tenant_context)


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
    payload["destination_tenant_id"] = package_record.destination_tenant_id if package_record else None
    payload["destination_agency_id"] = package_record.destination_agency_id if package_record else None
    payload["lock"] = _package_lock_payload(int(package.reliefpkg_id))
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
            "driver_license_no": transport.driver_license_no,
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
    actor_id = actor_id or "system"
    requested_statuses = REQUEST_FILTERS.get(str(filter_key or "").lower())
    results: list[dict[str, Any]] = []
    for request in ReliefRqst.objects.order_by("-create_dtime", "-reliefrqst_id")[:200]:
        request_record = _sync_operations_request(request, actor_id=actor_id)
        if requested_statuses and request_record.status_code not in requested_statuses:
            continue
        try:
            _ensure_request_access(request_record, actor_id=actor_id, actor_roles=actor_roles or (), tenant_context=tenant_context)
        except OperationValidationError:
            continue
        results.append(_request_summary_payload(request, request_record))
    return {"results": results}


def get_request(reliefrqst_id: int, *, actor_id: str | None = None, tenant_context: TenantContext, actor_roles: Iterable[str] | None = None) -> dict[str, Any]:
    actor_id = actor_id or "system"
    request = legacy_service._load_request(reliefrqst_id)
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
    if mutable_payload.get("agency_id") in (None, ""):
        raise OperationValidationError({"agency_id": "agency_id or beneficiary_agency_id is required."})
    decision = operations_policy.validate_relief_request_agency_selection(
        agency_id=int(mutable_payload.get("agency_id")),
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
        source_needs_list_id=int(mutable_payload["source_needs_list_id"]) if mutable_payload.get("source_needs_list_id") not in (None, "") else None,
        requesting_agency_id=int(mutable_payload["requesting_agency_id"]) if mutable_payload.get("requesting_agency_id") not in (None, "") else None,
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
    result = legacy_service.update_request(
        reliefrqst_id,
        payload=mutable_payload,
        actor_id=actor_id,
        tenant_context=tenant_context,
        permissions=permissions,
    )
    request = legacy_service._load_request(reliefrqst_id)
    decision = operations_policy.validate_relief_request_agency_selection(
        agency_id=int(request.agency_id),
        tenant_context=tenant_context,
    )
    _sync_operations_request(
        request,
        actor_id=actor_id,
        decision=decision,
        source_needs_list_id=int(mutable_payload["source_needs_list_id"]) if mutable_payload.get("source_needs_list_id") not in (None, "") else None,
        requesting_agency_id=int(mutable_payload["requesting_agency_id"]) if mutable_payload.get("requesting_agency_id") not in (None, "") else None,
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
    actor_id = actor_id or "system"
    _require_roles(actor_roles, ELIGIBILITY_ROLE_CODES, message="Only eligibility approvers may view this queue.")
    entity_ids = list(
        actor_queue_queryset(actor_id=actor_id, actor_roles=actor_roles or (), tenant_context=tenant_context)
        .filter(queue_code=QUEUE_CODE_ELIGIBILITY, entity_type=ENTITY_REQUEST)
        .values_list("entity_id", flat=True)
    )
    results: list[dict[str, Any]] = []
    queryset = ReliefRqst.objects.filter(reliefrqst_id__in=entity_ids) if entity_ids else ReliefRqst.objects.filter(status_code=legacy_service.STATUS_AWAITING_APPROVAL)
    for request in queryset.order_by("-request_date", "-reliefrqst_id")[:200]:
        request_record = _ops_request_from_legacy(request, actor_id=actor_id)
        try:
            _ensure_request_access(
                request_record,
                actor_id=actor_id,
                actor_roles=actor_roles or (),
                tenant_context=tenant_context,
            )
        except OperationValidationError:
            continue
        request_record = _sync_operations_request(request, actor_id=actor_id, status_code=REQUEST_STATUS_UNDER_ELIGIBILITY_REVIEW)
        results.append(_request_summary_payload(request, request_record))
    return {"results": results}


def get_eligibility_request(reliefrqst_id: int, *, actor_id: str | None = None, actor_roles: Iterable[str] | None = None, tenant_context: TenantContext) -> dict[str, Any]:
    actor_id = actor_id or "system"
    _require_roles(actor_roles, ELIGIBILITY_ROLE_CODES, message="Only eligibility approvers may review requests.")
    request = legacy_service._load_request(reliefrqst_id)
    request_record = _sync_operations_request(request, actor_id=actor_id, status_code=REQUEST_STATUS_UNDER_ELIGIBILITY_REVIEW)
    payload = get_request(reliefrqst_id, actor_id=actor_id, tenant_context=tenant_context, actor_roles=actor_roles)
    decision = OperationsEligibilityDecision.objects.filter(relief_request_id=reliefrqst_id).first()
    payload["decision_made"] = decision is not None
    payload["can_edit"] = request_record.status_code == REQUEST_STATUS_UNDER_ELIGIBILITY_REVIEW and decision is None
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
    _ensure_request_access(request_record, actor_id=actor_id, actor_roles=actor_roles or (), tenant_context=tenant_context)
    if OperationsEligibilityDecision.objects.filter(relief_request_id=reliefrqst_id).exists():
        raise OperationValidationError({"status": "Eligibility decision already recorded."})
    decision = str(payload.get("decision") or "").strip().upper()
    decision_code = {"Y": "APPROVED", "N": "INELIGIBLE"}.get(decision, decision)
    if decision_code not in {"APPROVED", "INELIGIBLE", "REJECTED"}:
        raise OperationValidationError({"decision": "Decision must be APPROVED, REJECTED, INELIGIBLE, Y, or N."})
    decision_reason = str(payload.get("reason") or payload.get("decision_reason") or "").strip() or None
    if decision_code in {"INELIGIBLE", "REJECTED"} and not decision_reason:
        raise OperationValidationError({"reason": "Reason is required for non-approval decisions."})
    now = timezone.now()
    request.review_by_id = actor_id
    request.review_dtime = now
    request.action_by_id = actor_id
    request.action_dtime = now
    request.version_nbr = int(request.version_nbr or 0) + 1
    if decision_code == "APPROVED":
        request.status_code = legacy_service.STATUS_SUBMITTED
        request.status_reason_desc = None
        next_status = REQUEST_STATUS_APPROVED_FOR_FULFILLMENT
    elif decision_code == "REJECTED":
        request.status_code = legacy_service.STATUS_DENIED
        request.status_reason_desc = decision_reason
        next_status = REQUEST_STATUS_REJECTED
    else:
        request.status_code = legacy_service.STATUS_INELIGIBLE
        request.status_reason_desc = decision_reason
        next_status = REQUEST_STATUS_INELIGIBLE
    request.save(
        update_fields=[
            "review_by_id",
            "review_dtime",
            "action_by_id",
            "action_dtime",
            "status_code",
            "status_reason_desc",
            "version_nbr",
        ]
    )
    OperationsEligibilityDecision.objects.create(
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
    request_record = _sync_operations_request(request, actor_id=actor_id, status_code=next_status)
    request_record.reviewed_by_id = actor_id
    request_record.reviewed_at = now
    request_record.save(update_fields=["reviewed_by_id", "reviewed_at"])
    complete_queue_assignments(entity_type=ENTITY_REQUEST, entity_id=reliefrqst_id, queue_code=QUEUE_CODE_ELIGIBILITY, actor_id=actor_id)
    if decision_code == "APPROVED":
        assign_roles_to_queue(
            queue_code=QUEUE_CODE_FULFILLMENT,
            entity_type=ENTITY_REQUEST,
            entity_id=reliefrqst_id,
            role_codes=FULFILLMENT_ROLE_CODES,
            tenant_id=request_record.beneficiary_tenant_id,
        )
        create_role_notifications(
            event_code=EVENT_REQUEST_APPROVED,
            entity_type=ENTITY_REQUEST,
            entity_id=reliefrqst_id,
            message_text=f"Relief request {request.tracking_no} is approved for fulfillment.",
            role_codes=FULFILLMENT_ROLE_CODES,
            tenant_id=request_record.beneficiary_tenant_id,
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
    return get_eligibility_request(reliefrqst_id, actor_id=actor_id, actor_roles=actor_roles, tenant_context=tenant_context)


def list_packages(*, actor_id: str | None = None, actor_roles: Iterable[str] | None = None, tenant_context: TenantContext) -> dict[str, Any]:
    actor_id = actor_id or "system"
    _require_roles(actor_roles, FULFILLMENT_ROLE_CODES, message="Only fulfillment roles may view this queue.")
    entity_ids = list(
        actor_queue_queryset(actor_id=actor_id, actor_roles=actor_roles or (), tenant_context=tenant_context)
        .filter(queue_code__in=[QUEUE_CODE_FULFILLMENT, QUEUE_CODE_OVERRIDE], entity_type=ENTITY_REQUEST)
        .values_list("entity_id", flat=True)
    )
    results: list[dict[str, Any]] = []
    if entity_ids:
        request_ids = entity_ids[:200]
    else:
        request_ids = list(
            OperationsReliefRequest.objects.filter(
                status_code__in=[REQUEST_STATUS_APPROVED_FOR_FULFILLMENT, REQUEST_STATUS_PARTIALLY_FULFILLED]
            )
            .order_by("-request_date", "-relief_request_id")
            .values_list("relief_request_id", flat=True)[:200]
        )
    for reliefrqst_id in request_ids:
        request = legacy_service._load_request(int(reliefrqst_id))
        request_record = _sync_operations_request(request, actor_id=actor_id)
        if request_record.status_code not in {REQUEST_STATUS_APPROVED_FOR_FULFILLMENT, REQUEST_STATUS_PARTIALLY_FULFILLED}:
            continue
        try:
            _ensure_request_access(
                request_record,
                actor_id=actor_id,
                actor_roles=actor_roles or (),
                tenant_context=tenant_context,
            )
        except OperationValidationError:
            continue
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
    actor_id = actor_id or "system"
    request = legacy_service._load_request(reliefrqst_id)
    request_record = _sync_operations_request(request, actor_id=actor_id)
    _ensure_request_access(request_record, actor_id=actor_id, actor_roles=actor_roles or (), tenant_context=tenant_context)
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


def get_package_allocation_options(reliefrqst_id: int, *, source_warehouse_id: int | None = None, actor_id: str | None = None, actor_roles: Iterable[str] | None = None, tenant_context: TenantContext) -> dict[str, Any]:
    del actor_roles
    actor_id = actor_id or "system"
    request = legacy_service._load_request(reliefrqst_id)
    request_record = _sync_operations_request(request, actor_id=actor_id)
    _ensure_request_access(request_record, actor_id=actor_id, actor_roles=(), tenant_context=tenant_context)
    return legacy_service.get_package_allocation_options(reliefrqst_id, source_warehouse_id=source_warehouse_id)


@transaction.atomic
def save_package(
    reliefrqst_id: int,
    *,
    payload: Mapping[str, Any],
    actor_id: str,
    actor_roles: Iterable[str] | None,
    tenant_context: TenantContext,
) -> dict[str, Any]:
    _require_roles(actor_roles, FULFILLMENT_ROLE_CODES, message="Only fulfillment roles may modify packages.")
    request = legacy_service._load_request(reliefrqst_id)
    request_record = _sync_operations_request(request, actor_id=actor_id)
    _ensure_request_access(request_record, actor_id=actor_id, actor_roles=actor_roles or (), tenant_context=tenant_context)
    package = legacy_service._current_package_for_request(reliefrqst_id)
    package_locked_before_save = package is not None
    if package_locked_before_save:
        _sync_operations_package(package, request_record=request_record, actor_id=actor_id)
        _acquire_package_lock(int(package.reliefpkg_id), actor_id=actor_id, actor_roles=actor_roles or ())
    result = legacy_service.save_package(reliefrqst_id, payload=payload, actor_id=actor_id)
    package = legacy_service._current_package_for_request(reliefrqst_id)
    if package is None:
        return result
    first_inventory_id = None
    allocations = payload.get("allocations")
    if isinstance(allocations, list) and allocations:
        first_inventory_id = int(allocations[0].get("inventory_id"))
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
    if not package_locked_before_save:
        _acquire_package_lock(int(package.reliefpkg_id), actor_id=actor_id, actor_roles=actor_roles or ())
    if status_code == PACKAGE_STATUS_PENDING_OVERRIDE_APPROVAL:
        assign_roles_to_queue(
            queue_code=QUEUE_CODE_OVERRIDE,
            entity_type=ENTITY_REQUEST,
            entity_id=reliefrqst_id,
            role_codes=[ROLE_LOGISTICS_MANAGER],
            tenant_id=request_record.beneficiary_tenant_id,
        )
        create_role_notifications(
            event_code=EVENT_OVERRIDE_REQUESTED,
            entity_type=ENTITY_REQUEST,
            entity_id=reliefrqst_id,
            message_text=f"Override approval is required for package {package.tracking_no}.",
            role_codes=[ROLE_LOGISTICS_MANAGER],
            tenant_id=request_record.beneficiary_tenant_id,
            queue_code=QUEUE_CODE_OVERRIDE,
        )
    elif status_code == PACKAGE_STATUS_COMMITTED:
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
    request_record = _sync_operations_request(request, actor_id=actor_id)
    _ensure_request_access(request_record, actor_id=actor_id, actor_roles=normalized_roles, tenant_context=tenant_context)
    result = legacy_service.approve_override(reliefrqst_id, payload=payload, actor_id=actor_id, actor_roles=normalized_roles)
    package = legacy_service._current_package_for_request(reliefrqst_id)
    if package is not None:
        package_record = _sync_operations_package(package, request_record=request_record, actor_id=actor_id, status_code=PACKAGE_STATUS_COMMITTED, override_status_code=None)
        _ensure_dispatch_record(package=package, package_record=package_record, actor_id=actor_id)
        complete_queue_assignments(entity_type=ENTITY_REQUEST, entity_id=reliefrqst_id, queue_code=QUEUE_CODE_OVERRIDE, actor_id=actor_id)
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


def list_dispatch_queue(*, actor_id: str | None = None, actor_roles: Iterable[str] | None = None, tenant_context: TenantContext) -> dict[str, Any]:
    actor_id = actor_id or "system"
    _require_roles(actor_roles, DISPATCH_ROLE_CODES, message="Only dispatch roles may view this queue.")
    package_ids = list(
        actor_queue_queryset(actor_id=actor_id, actor_roles=actor_roles or (), tenant_context=tenant_context)
        .filter(queue_code=QUEUE_CODE_DISPATCH, entity_type=ENTITY_PACKAGE)
        .values_list("entity_id", flat=True)
    )
    results = []
    if not package_ids:
        package_ids = list(
            OperationsPackage.objects.filter(status_code=PACKAGE_STATUS_COMMITTED)
            .order_by("-committed_at", "-package_id")
            .values_list("package_id", flat=True)[:200]
        )
    for reliefpkg_id in package_ids[:200]:
        package = legacy_service._load_package(int(reliefpkg_id))
        request = legacy_service._load_request(int(package.reliefrqst_id))
        request_record = _sync_operations_request(request, actor_id=actor_id)
        package_record = _sync_operations_package(package, request_record=request_record, actor_id=actor_id)
        if package_record.status_code != PACKAGE_STATUS_COMMITTED:
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
    actor_id = actor_id or "system"
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
    departure_dtime = payload.get("departure_dtime")
    estimated_arrival_dtime = payload.get("estimated_arrival_dtime")
    if not driver_name:
        raise OperationValidationError({"driver_name": "driver_name is required for dispatch."})
    if not any([vehicle_id, vehicle_registration, vehicle_type]):
        raise OperationValidationError({"vehicle": "vehicle_id, vehicle_registration, or vehicle_type is required for dispatch."})
    if departure_dtime in (None, ""):
        raise OperationValidationError({"departure_dtime": "departure_dtime is required for dispatch."})
    if estimated_arrival_dtime in (None, ""):
        raise OperationValidationError({"estimated_arrival_dtime": "estimated_arrival_dtime is required for dispatch."})
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
    actor_id = actor_id or "system"
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
    _ensure_package_access(package_record, actor_id=actor_id, actor_roles=actor_roles or (), tenant_context=tenant_context)
    if package.dispatch_dtime is None:
        raise OperationValidationError({"receipt": "Package has not been dispatched."})
    if package.received_dtime is not None:
        raise OperationValidationError({"receipt": "Receipt has already been confirmed."})
    now = timezone.now()
    package.received_by_id = actor_id
    package.received_dtime = now
    package.status_code = legacy_service.PKG_STATUS_COMPLETED
    package.update_by_id = actor_id
    package.update_dtime = now
    package.version_nbr = int(package.version_nbr or 0) + 1
    package.save()
    _sync_operations_package(package, request_record=request_record, actor_id=actor_id, status_code=PACKAGE_STATUS_RECEIVED)
    dispatch = OperationsDispatch.objects.filter(package_id=reliefpkg_id).first()
    if dispatch is None:
        raise OperationValidationError({"receipt": "Dispatch record is missing for this package."})
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
            "package_id": reliefpkg_id,
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
