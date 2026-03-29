from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping, Sequence

from django.db import connection, transaction
from django.db.models import F
from django.utils import timezone

from api.tenancy import TenantContext
from operations import policy as operations_policy
from operations.exceptions import OperationValidationError
from replenishment.legacy_models import Agency, Item, ReliefPkg, ReliefRqst
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


def _fetch_rows(sql: str, params: Sequence[Any] | None = None) -> list[dict[str, Any]]:
    with connection.cursor() as cursor:
        cursor.execute(sql, list(params or []))
        columns = [col[0] for col in cursor.description or []]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _execute(sql: str, params: Sequence[Any] | None = None) -> int:
    with connection.cursor() as cursor:
        cursor.execute(sql, list(params or []))
        return cursor.rowcount


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
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise OperationValidationError({field_name: "Must be a positive integer."}) from exc
    if parsed <= 0:
        raise OperationValidationError({field_name: "Must be a positive integer."})
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
    manager = ReliefRqst.objects.select_for_update() if for_update else ReliefRqst.objects
    return manager.get(reliefrqst_id=reliefrqst_id)


def _load_package(reliefpkg_id: int, *, for_update: bool = False) -> ReliefPkg:
    manager = ReliefPkg.objects.select_for_update() if for_update else ReliefPkg.objects
    return manager.get(reliefpkg_id=reliefpkg_id)


def _current_package_for_request(reliefrqst_id: int, *, for_update: bool = False) -> ReliefPkg | None:
    manager = ReliefPkg.objects.select_for_update() if for_update else ReliefPkg.objects
    return manager.filter(reliefrqst_id=reliefrqst_id).order_by("-reliefpkg_id").first()


def _execution_link_for_request(reliefrqst_id: int) -> NeedsListExecutionLink | None:
    return NeedsListExecutionLink.objects.filter(reliefrqst_id=reliefrqst_id).first()


def _execution_link_for_package(reliefpkg_id: int) -> NeedsListExecutionLink | None:
    return NeedsListExecutionLink.objects.filter(reliefpkg_id=reliefpkg_id).first()


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
    return [
        {
            "item_id": int(row["item_id"]),
            "item_code": item_names.get(int(row["item_id"]), {}).get("item_code"),
            "item_name": item_names.get(int(row["item_id"]), {}).get("item_name"),
            "request_qty": str(_quantize_qty(row.get("request_qty"))),
            "issue_qty": str(_quantize_qty(row.get("issue_qty"))),
            "urgency_ind": row.get("urgency_ind"),
            "rqst_reason_desc": row.get("rqst_reason_desc"),
            "required_by_date": _as_iso(row.get("required_by_date")),
            "status_code": row.get("status_code"),
        }
        for row in rows
    ]


def _ensure_request_in_fulfillment_state(request: ReliefRqst) -> None:
    current_status = int(request.status_code or STATUS_DRAFT)
    if current_status not in FULFILLMENT_REQUEST_STATUSES:
        raise OperationValidationError(
            {
                "request": (
                    "Packages can only be managed for requests that are submitted "
                    "for fulfillment or already part filled."
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
                "total_qty": str(sum((_quantize_qty(row["quantity"]) for row in rows), Decimal("0")).quantize(Decimal("0.0001"))),
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


def _validate_request_payload(payload: Mapping[str, Any], *, partial: bool = False) -> dict[str, Any]:
    errors: dict[str, str] = {}
    normalized: dict[str, Any] = {}
    if not partial or "agency_id" in payload:
        normalized["agency_id"] = _positive_int(payload.get("agency_id"), "agency_id", errors)
    if not partial or "urgency_ind" in payload:
        urgency_ind = str(payload.get("urgency_ind") or "").strip().upper()
        if urgency_ind not in {"C", "H", "M", "L"}:
            errors["urgency_ind"] = "Must be one of C, H, M, or L."
        else:
            normalized["urgency_ind"] = urgency_ind
    if "eligible_event_id" in payload:
        if payload.get("eligible_event_id") in (None, ""):
            normalized["eligible_event_id"] = None
        else:
            normalized["eligible_event_id"] = _positive_int(payload.get("eligible_event_id"), "eligible_event_id", errors)
            if normalized["eligible_event_id"] is not None and not _event_exists(int(normalized["eligible_event_id"])):
                errors["eligible_event_id"] = "Selected event does not exist."
    if not partial or "rqst_notes_text" in payload:
        normalized["rqst_notes_text"] = str(payload.get("rqst_notes_text") or "").strip() or None
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
                if urgency_ind not in {"C", "H", "M", "L"}:
                    errors[f"items[{index}].urgency_ind"] = "Must be one of C, H, M, or L."
                reason = str(raw.get("rqst_reason_desc") or "").strip() or None
                if urgency_ind in {"C", "H"} and not reason:
                    errors[f"items[{index}].rqst_reason_desc"] = "Reason is required for high-priority items."
                required_by_date = _optional_date(raw.get("required_by_date"), f"items[{index}].required_by_date", errors)
                normalized_items.append(
                    {
                        "item_id": item_id,
                        "request_qty": _quantize_qty(request_qty),
                        "urgency_ind": urgency_ind,
                        "rqst_reason_desc": reason,
                        "required_by_date": required_by_date,
                    }
                )
    normalized["items"] = normalized_items
    if errors:
        raise OperationValidationError(errors)
    return normalized


def list_requests(*, filter_key: str | None = None, actor_id: str | None = None) -> dict[str, Any]:
    queryset = ReliefRqst.objects.order_by("-create_dtime", "-reliefrqst_id")
    if filter_key:
        statuses = REQUEST_LIST_FILTERS.get(str(filter_key).lower())
        if statuses:
            queryset = queryset.filter(status_code__in=sorted(statuses))
    return {"results": [_request_summary(request) for request in queryset[:200]]}


def get_request(reliefrqst_id: int, *, actor_id: str | None = None) -> dict[str, Any]:
    return _request_detail(_load_request(reliefrqst_id))


@transaction.atomic
def create_request(
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
    return get_request(reliefrqst_id, actor_id=actor_id)


@transaction.atomic
def update_request(
    reliefrqst_id: int,
    *,
    payload: Mapping[str, Any],
    actor_id: str,
    tenant_context: TenantContext,
    permissions: Iterable[str] | None = None,
) -> dict[str, Any]:
    request = _load_request(reliefrqst_id, for_update=True)
    if int(request.status_code) != STATUS_DRAFT:
        raise OperationValidationError({"status": "Only draft requests can be updated."})
    normalized = _validate_request_payload(payload, partial=True)
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
        "action_by_id",
        "action_dtime",
        "version_nbr",
    ]
    if "rqst_notes_text" in normalized:
        request.rqst_notes_text = normalized["rqst_notes_text"]
        update_fields.append("rqst_notes_text")
    request.action_by_id = actor_id
    request.action_dtime = timezone.now()
    request.version_nbr = int(request.version_nbr or 0) + 1
    request.save(update_fields=update_fields)
    if normalized["items"]:
        _upsert_request_items(reliefrqst_id, normalized["items"])
    return get_request(reliefrqst_id, actor_id=actor_id)


@transaction.atomic
def submit_request(reliefrqst_id: int, *, actor_id: str, tenant_context: TenantContext) -> dict[str, Any]:
    request = _load_request(reliefrqst_id, for_update=True)
    if int(request.status_code) != STATUS_DRAFT:
        raise OperationValidationError({"status": "Only draft requests can be submitted."})
    operations_policy.validate_relief_request_agency_selection(
        agency_id=int(request.agency_id),
        tenant_context=tenant_context,
    )
    if not _request_item_rows_for_allocation(reliefrqst_id):
        raise OperationValidationError({"items": "At least one item is required before submission."})
    request.status_code = STATUS_AWAITING_APPROVAL
    request.version_nbr = int(request.version_nbr or 0) + 1
    request.save(update_fields=["status_code", "version_nbr"])
    return get_request(reliefrqst_id, actor_id=actor_id)


def list_eligibility_queue(*, actor_id: str | None = None) -> dict[str, Any]:
    queryset = ReliefRqst.objects.filter(
        status_code=STATUS_AWAITING_APPROVAL,
        review_by_id__isnull=True,
    ).order_by("-request_date", "-reliefrqst_id")
    return {"results": [_request_summary(request) for request in queryset[:200]]}


def get_eligibility_request(reliefrqst_id: int, *, actor_id: str | None = None) -> dict[str, Any]:
    request = _load_request(reliefrqst_id)
    payload = _request_detail(request)
    payload["decision_made"] = bool(request.review_by_id) or int(request.status_code) in {
        STATUS_INELIGIBLE,
        STATUS_DENIED,
    }
    payload["can_edit"] = int(request.status_code) == STATUS_AWAITING_APPROVAL and not payload["decision_made"]
    return payload


@transaction.atomic
def submit_eligibility_decision(
    reliefrqst_id: int,
    *,
    payload: Mapping[str, Any],
    actor_id: str,
) -> dict[str, Any]:
    request = _load_request(reliefrqst_id, for_update=True)
    if int(request.status_code) != STATUS_AWAITING_APPROVAL:
        raise OperationValidationError({"status": "Request is not awaiting eligibility review."})
    if request.review_by_id:
        raise OperationValidationError({"status": "Eligibility decision already recorded."})
    decision = str(payload.get("decision") or "").strip().upper()
    reason = str(payload.get("reason") or "").strip()
    if decision not in {"Y", "N"}:
        raise OperationValidationError({"decision": "Decision must be Y or N."})
    if decision == "N" and not reason:
        raise OperationValidationError({"reason": "Reason is required for ineligible decisions."})
    now = timezone.now()
    request.review_by_id = actor_id
    request.review_dtime = now
    request.version_nbr = int(request.version_nbr or 0) + 1
    if decision == "Y":
        request.status_code = STATUS_SUBMITTED
        request.status_reason_desc = None
    else:
        request.status_code = STATUS_INELIGIBLE
        request.status_reason_desc = reason
        request.action_by_id = actor_id
        request.action_dtime = now
    request.save(
        update_fields=[
            "review_by_id",
            "review_dtime",
            "status_code",
            "status_reason_desc",
            "action_by_id",
            "action_dtime",
            "version_nbr",
        ]
    )
    return get_eligibility_request(reliefrqst_id, actor_id=actor_id)


def list_packages(*, actor_id: str | None = None) -> dict[str, Any]:
    requests = ReliefRqst.objects.filter(
        status_code__in=sorted({STATUS_SUBMITTED, STATUS_PART_FILLED})
    ).order_by("-request_date", "-reliefrqst_id")
    results = []
    for request in requests[:200]:
        current_package = _current_package_for_request(int(request.reliefrqst_id))
        row = _request_summary(request)
        row["current_package"] = _package_summary(current_package) if current_package is not None else None
        results.append(row)
    return {"results": results}


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


def get_package(reliefrqst_id: int, *, actor_id: str | None = None) -> dict[str, Any]:
    request = _load_request(reliefrqst_id)
    package = _current_package_for_request(reliefrqst_id)
    return {
        "request": _request_summary(request),
        "package": _package_detail(package) if package is not None else None,
        "items": _request_items(reliefrqst_id),
        "compatibility_only": False,
    }


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


def _reshape_compat_options(compat: dict[str, Any], reliefrqst_id: int) -> dict[str, Any]:
    """Reshape the needs-list allocation response to match the operations contract.

    The compat path returns ``required_qty`` / ``fulfilled_qty`` per item and wraps
    the top level under ``needs_list``.  The operations frontend expects
    ``request_qty`` / ``issue_qty`` and a ``request`` summary.
    """
    items: list[dict[str, Any]] = []
    for group in compat.get("items", []):
        item: dict[str, Any] = {**group}
        item["request_qty"] = item.pop("required_qty", "0.0000")
        item["issue_qty"] = item.pop("fulfilled_qty", "0.0000")
        item.pop("reserved_qty", None)
        item.pop("needs_list_item_id", None)
        item.pop("criticality_level", None)
        item.pop("criticality_rank", None)
        items.append(item)
    return {
        "request": _request_summary(_load_request(reliefrqst_id)),
        "items": items,
    }


def get_package_allocation_options(reliefrqst_id: int, *, source_warehouse_id: int | None = None) -> dict[str, Any]:
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
    item_lookup = {item.item_id: item for item in Item.objects.filter(item_id__in=[row["item_id"] for row in item_rows])}
    results: list[dict[str, Any]] = []
    for row in item_rows:
        item_id = int(row["item_id"])
        item = item_lookup.get(item_id)
        remaining_qty = max(Decimal("0"), _quantize_qty(row["request_qty"]) - _quantize_qty(row["issue_qty"]))
        candidates: list[dict[str, Any]] = []
        for warehouse_id in warehouse_ids:
            candidates.extend(_fetch_batch_candidates(warehouse_id, item_id, as_of_date=timezone.localdate()))
        sorted_candidates = sort_batch_candidates(item or {"issuance_order": "FIFO"}, candidates)
        suggested_allocations, remaining_after_suggestion = build_greedy_allocation_plan(sorted_candidates, remaining_qty)
        results.append(
            {
                "item_id": item_id,
                "item_code": getattr(item, "item_code", None),
                "item_name": getattr(item, "item_name", None),
                "request_qty": str(_quantize_qty(row["request_qty"])),
                "issue_qty": str(_quantize_qty(row["issue_qty"])),
                "remaining_qty": str(remaining_qty.quantize(Decimal("0.0001"))),
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
            }
        )
    return {"request": _request_summary(_load_request(reliefrqst_id)), "items": results}


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
            # Approval flow requires allocations to commit the package
            raise OperationValidationError(
                {"allocations": "Allocations are required for override approval."}
            )
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
    override_required = False
    override_markers: list[str] = []
    for item_id, rows in _package_plan_map(plan_rows).items():
        if item_id not in item_lookup:
            override_required = True
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
            override_required = True
            override_markers.append("insufficient_on_hand_stock")
        if _group_plan_rows(recommended) != rows:
            override_required = True
            override_markers.append("allocation_order_override")
    override_reason_code = str(payload.get("override_reason_code") or "").strip() or None
    override_note = str(payload.get("override_note") or "").strip() or None
    if override_required:
        if not override_reason_code or not override_note:
            raise OverrideApprovalError(
                "Override reason code and note are required for non-compliant allocations.",
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
        notes=override_note or f"RR:{reliefrqst_id}",
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


@transaction.atomic
def save_package(reliefrqst_id: int, *, payload: Mapping[str, Any], actor_id: str) -> dict[str, Any]:
    return _save_package_allocation(
        reliefrqst_id,
        payload=payload,
        actor_id=actor_id,
        allow_pending_override=True,
    )


@transaction.atomic
def approve_override(reliefrqst_id: int, *, payload: Mapping[str, Any], actor_id: str, actor_roles: Iterable[str] | None) -> dict[str, Any]:
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
    # The submitter for self-approval checks is the person who originally
    # allocated the package (triggered the override), not the current approver.
    allocator_user_id = (
        str(request.create_by_id or (package.create_by_id if package is not None else actor_id))
    )
    return _save_package_allocation(
        reliefrqst_id,
        payload=payload,
        actor_id=actor_id,
        allow_pending_override=False,
        supervisor_user_id=actor_id,
        supervisor_role_codes=actor_roles,
        override_submitter_user_id=allocator_user_id,
    )


def list_dispatch_queue(*, actor_id: str | None = None) -> dict[str, Any]:
    packages = ReliefPkg.objects.filter(status_code__in=[PKG_STATUS_PENDING, "C", "V"]).order_by("-dispatch_dtime", "-reliefpkg_id")
    return {"results": [_dispatch_detail(package) for package in packages[:200]]}


def _dispatch_detail(package: ReliefPkg) -> dict[str, Any]:
    payload = _package_detail(package)
    payload["request"] = _request_summary(_load_request(int(package.reliefrqst_id)))
    payload["waybill"] = get_waybill(int(package.reliefpkg_id)) if package.dispatch_dtime else None
    return payload


def get_dispatch_package(reliefpkg_id: int, *, actor_id: str | None = None) -> dict[str, Any]:
    return _dispatch_detail(_load_package(reliefpkg_id))


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
        "event_name": data_access.get_event_name(int(request.eligible_event_id))
        if request.eligible_event_id is not None
        else None,
        "source_warehouse_ids": source_warehouse_ids,
        "source_warehouse_names": [source_warehouse_names[warehouse_id] for warehouse_id in source_warehouse_ids if warehouse_id in source_warehouse_names],
        "destination_warehouse_id": package.to_inventory_id,
        "destination_warehouse_name": data_access.get_warehouse_name(int(package.to_inventory_id))
        if package.to_inventory_id is not None
        else None,
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


@transaction.atomic
def submit_dispatch(reliefpkg_id: int, *, payload: Mapping[str, Any], actor_id: str) -> dict[str, Any]:
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


def get_waybill(reliefpkg_id: int) -> dict[str, Any]:
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
