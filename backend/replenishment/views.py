import csv
import io
import hashlib
import ipaddress
import logging
import time
import re
import math
import json
import os
import uuid
from decimal import Decimal, InvalidOperation
from datetime import timedelta
from importlib import import_module
from pathlib import Path
from contextlib import contextmanager
from typing import Any, Dict, Mapping

from django.conf import settings
from django.core.cache import cache
from django.db import DatabaseError, IntegrityError, OperationalError, ProgrammingError, connection, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.urls import reverse
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from api.apps import build_log_extra, get_request_id
from api.authentication import LegacyCompatAuthentication
from api.checks import get_replenishment_export_audit_schema_status
from api.models import AsyncJob
from api.permissions import NeedsListPermission, NeedsListPreviewPermission, ProcurementPermission
from api.rbac import (
    PERM_MASTERDATA_EDIT,
    PERM_MASTERDATA_VIEW,
    PERM_CRITICALITY_OVERRIDE_VIEW,
    PERM_CRITICALITY_OVERRIDE_MANAGE,
    PERM_CRITICALITY_HAZARD_VIEW,
    PERM_CRITICALITY_HAZARD_MANAGE,
    PERM_CRITICALITY_HAZARD_APPROVE,
    PERM_NEEDS_LIST_CREATE_DRAFT,
    PERM_NEEDS_LIST_EDIT_LINES,
    PERM_NEEDS_LIST_ESCALATE,
    PERM_NEEDS_LIST_APPROVE,
    PERM_NEEDS_LIST_EXECUTE,
    PERM_NEEDS_LIST_CANCEL,
    PERM_NEEDS_LIST_REVIEW_COMMENTS,
    PERM_NEEDS_LIST_REJECT,
    PERM_NEEDS_LIST_RETURN,
    PERM_NEEDS_LIST_SUBMIT,
    PERM_PROCUREMENT_CREATE,
    PERM_PROCUREMENT_VIEW,
    PERM_PROCUREMENT_EDIT,
    PERM_PROCUREMENT_SUBMIT,
    PERM_PROCUREMENT_APPROVE,
    PERM_PROCUREMENT_REJECT,
    PERM_PROCUREMENT_ORDER,
    PERM_PROCUREMENT_RECEIVE,
    PERM_PROCUREMENT_CANCEL,
    resolve_roles_and_permissions,
)
from api.tenancy import (
    can_access_record,
    can_access_warehouse,
    resolve_tenant_context,
    resolve_warehouse_tenant_id,
    tenant_context_to_dict,
)
from api.task_engine import TaskRule, resolve_available_tasks
from replenishment import rules, workflow_store_db
from replenishment.models import (
    NeedsList,
    NeedsListAllocationLine,
    NeedsListExecutionLink,
    Procurement,
)
from replenishment.services import allocation_dispatch
from replenishment.services import approval as approval_service
from replenishment.services import criticality_governance
from replenishment.services import data_access, needs_list, phase_window_policy
from replenishment.services import location_storage
from replenishment.services import procurement as procurement_service
from replenishment.services import repackaging as repackaging_service
from replenishment.services.procurement import ProcurementError
from replenishment.services.repackaging import RepackagingError

logger = logging.getLogger("dmis.audit")

try:  # POSIX
    import fcntl  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover - not available on Windows
    fcntl = None  # type: ignore[assignment]

try:  # Windows fallback
    import msvcrt  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover - not available on POSIX
    msvcrt = None  # type: ignore[assignment]

PENDING_APPROVAL_STATUSES = {"SUBMITTED", "PENDING_APPROVAL", "PENDING", "UNDER_REVIEW"}
_DB_STATUS_TRANSITIONS = {
    "PENDING": "SUBMITTED",
    "PENDING_APPROVAL": "SUBMITTED",
    "UNDER_REVIEW": "SUBMITTED",
    "RETURNED": "MODIFIED",
    "ESCALATED": "SUBMITTED",
    "CANCELLED": "REJECTED",
    "IN_PREPARATION": "IN_PROGRESS",
    "DISPATCHED": "IN_PROGRESS",
    "RECEIVED": "IN_PROGRESS",
    "COMPLETED": "FULFILLED",
}
REQUEST_CHANGE_REASON_CODES = {
    "QTY_ADJUSTMENT",
    "DATA_QUALITY",
    "MISSING_JUSTIFICATION",
    "SCOPE_MISMATCH",
    "POLICY_COMPLIANCE",
    "OTHER",
}
_CLOSED_NEEDS_LIST_STATUSES = {"FULFILLED", "COMPLETED", "CANCELLED", "SUPERSEDED", "REJECTED"}
_OWNER_ONLY_SUBMISSION_STATUSES = {"DRAFT", "MODIFIED", "RETURNED"}
_DUPLICATE_GUARD_ACTIVE_STATUSES = {
    "SUBMITTED",
    "PENDING_APPROVAL",
    "PENDING",
    "UNDER_REVIEW",
    "APPROVED",
    "IN_PROGRESS",
    "IN_PREPARATION",
    "DISPATCHED",
    "RECEIVED",
}
_NEEDS_LIST_EXECUTION_STATUSES = {
    "APPROVED",
    "IN_PREPARATION",
    "DISPATCHED",
    "RECEIVED",
    "IN_PROGRESS",
}
INACTIVE_ITEM_FORWARD_WRITE_CODE = "inactive_item_forward_write_blocked"
STRICT_INBOUND_VIEW_MISSING_CODE = "strict_inbound_workflow_view_missing"


def _record_for_task_context(context: Mapping[str, Any]) -> Dict[str, Any]:
    record = context.get("record")
    return record if isinstance(record, dict) else {}


def _record_status_for_task(record: Dict[str, Any]) -> str:
    return str(record.get("status") or "").strip().upper()


def _can_mark_dispatched(context: Mapping[str, Any]) -> bool:
    record = _record_for_task_context(context)
    status = _record_status_for_task(record)
    if status == "IN_PREPARATION":
        return True
    if status != "IN_PROGRESS":
        return False
    return bool(record.get("prep_started_at")) and not bool(record.get("dispatched_at"))


def _can_mark_received(context: Mapping[str, Any]) -> bool:
    record = _record_for_task_context(context)
    status = _record_status_for_task(record)
    if status == "DISPATCHED":
        return True
    if status != "IN_PROGRESS":
        return False
    return bool(record.get("dispatched_at")) and not bool(record.get("received_at"))


def _can_mark_completed(context: Mapping[str, Any]) -> bool:
    record = _record_for_task_context(context)
    status = _record_status_for_task(record)
    if status == "RECEIVED":
        return True
    if status != "IN_PROGRESS":
        return False
    return bool(record.get("received_at")) and not bool(record.get("completed_at"))


def _can_cancel_execution(context: Mapping[str, Any]) -> bool:
    record = _record_for_task_context(context)
    status = _record_status_for_task(record)
    if status not in {"APPROVED", "IN_PREPARATION", "IN_PROGRESS"}:
        return False
    return not any(record.get(field) for field in ("dispatched_at", "received_at", "completed_at"))


_NEEDS_LIST_TASK_RULES = (
    TaskRule(
        task_code="edit_lines",
        required_permissions=(PERM_NEEDS_LIST_EDIT_LINES,),
        statuses=frozenset({"DRAFT", "MODIFIED", "RETURNED"}),
    ),
    TaskRule(
        task_code="submit",
        required_permissions=(PERM_NEEDS_LIST_SUBMIT,),
        statuses=frozenset({"DRAFT", "MODIFIED", "RETURNED"}),
    ),
    TaskRule(
        task_code="cancel",
        required_permissions=(PERM_NEEDS_LIST_CANCEL,),
        statuses=frozenset({"DRAFT", "MODIFIED", "RETURNED"}),
    ),
    TaskRule(
        task_code="review_comments",
        required_permissions=(PERM_NEEDS_LIST_REVIEW_COMMENTS,),
        statuses=frozenset(PENDING_APPROVAL_STATUSES),
    ),
    TaskRule(
        task_code="return",
        required_permissions=(PERM_NEEDS_LIST_RETURN,),
        statuses=frozenset(PENDING_APPROVAL_STATUSES),
    ),
    TaskRule(
        task_code="reject",
        required_permissions=(PERM_NEEDS_LIST_REJECT,),
        statuses=frozenset(PENDING_APPROVAL_STATUSES),
    ),
    TaskRule(
        task_code="approve",
        required_permissions=(PERM_NEEDS_LIST_APPROVE,),
        statuses=frozenset(PENDING_APPROVAL_STATUSES),
    ),
    TaskRule(
        task_code="escalate",
        required_permissions=(PERM_NEEDS_LIST_ESCALATE,),
        statuses=frozenset(PENDING_APPROVAL_STATUSES),
    ),
    TaskRule(
        task_code="start_preparation",
        required_permissions=(PERM_NEEDS_LIST_EXECUTE,),
        statuses=frozenset({"APPROVED"}),
    ),
    TaskRule(
        task_code="mark_dispatched",
        required_permissions=(PERM_NEEDS_LIST_EXECUTE,),
        statuses=frozenset({"IN_PREPARATION", "IN_PROGRESS"}),
        predicate=_can_mark_dispatched,
    ),
    TaskRule(
        task_code="mark_received",
        required_permissions=(PERM_NEEDS_LIST_EXECUTE,),
        statuses=frozenset({"DISPATCHED", "IN_PROGRESS"}),
        predicate=_can_mark_received,
    ),
    TaskRule(
        task_code="mark_completed",
        required_permissions=(PERM_NEEDS_LIST_EXECUTE,),
        statuses=frozenset({"RECEIVED", "IN_PROGRESS"}),
        predicate=_can_mark_completed,
    ),
    TaskRule(
        task_code="generate_transfers",
        required_permissions=(PERM_NEEDS_LIST_EXECUTE,),
        statuses=frozenset(_NEEDS_LIST_EXECUTION_STATUSES),
    ),
    TaskRule(
        task_code="manage_donations",
        required_permissions=(PERM_NEEDS_LIST_EXECUTE,),
        statuses=frozenset(_NEEDS_LIST_EXECUTION_STATUSES),
    ),
    TaskRule(
        task_code="export_procurement",
        required_permissions=(PERM_NEEDS_LIST_EXECUTE,),
        statuses=frozenset(_NEEDS_LIST_EXECUTION_STATUSES),
    ),
    TaskRule(
        task_code="cancel",
        required_permissions=(PERM_NEEDS_LIST_CANCEL,),
        statuses=frozenset({"APPROVED", "IN_PREPARATION", "IN_PROGRESS"}),
        predicate=_can_cancel_execution,
    ),
)


class DuplicateConflictValidationError(ValueError):
    """Raised when duplicate-conflict validation input is malformed."""


class PaginationValidationError(ValueError):
    """Raised when pagination query parameters are invalid."""

    def __init__(self, errors: Dict[str, str]):
        self.errors = errors
        super().__init__("Invalid pagination parameters.")


workflow_store = workflow_store_db


def _workflow_target_status(status: str) -> str:
    normalized = str(status or "").upper()
    return _DB_STATUS_TRANSITIONS.get(normalized, normalized)


def _status_matches(
    current_status: object,
    *expected_statuses: str,
    include_db_transitions: bool = False,
) -> bool:
    current = str(current_status or "").upper()
    accepted: set[str] = set()
    for status in expected_statuses:
        normalized = str(status or "").upper()
        if not normalized:
            continue
        accepted.add(normalized)
        if include_db_transitions:
            accepted.add(_workflow_target_status(normalized))
    return current in accepted


def _parse_positive_int(value: Any, field_name: str, errors: Dict[str, str]) -> int | None:
    if isinstance(value, float):
        errors[field_name] = "Must be an integer."
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or not re.fullmatch(r"[+-]?\d+", stripped):
            errors[field_name] = "Must be an integer."
            return None
        value = stripped
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        errors[field_name] = "Must be an integer."
        return None
    if parsed <= 0:
        errors[field_name] = "Must be a positive integer."
        return None
    return parsed


def _parse_optional_bool(value: Any, field_name: str, errors: Dict[str, str]) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
    errors[field_name] = "Must be a boolean."
    return None


def _parse_optional_datetime(
    value: Any,
    field_name: str,
    errors: Dict[str, str],
):
    if value in (None, ""):
        return None
    if isinstance(value, str):
        parsed = parse_datetime(value.strip())
        if parsed is None:
            errors[field_name] = "Must be an ISO datetime."
            return None
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
        return parsed
    errors[field_name] = "Must be an ISO datetime string."
    return None


def _parse_selected_item_keys(
    raw_keys: Any,
    errors: Dict[str, str],
    field_name: str = "selected_item_keys",
) -> set[str] | None:
    if raw_keys is None:
        return None
    if not isinstance(raw_keys, list):
        errors[field_name] = "Must be an array of item keys."
        return None

    parsed: set[str] = set()
    for idx, key in enumerate(raw_keys):
        if not isinstance(key, str):
            errors[field_name] = f"Invalid key at index {idx}."
            return None
        normalized = key.strip()
        if not re.fullmatch(r"\d+_\d+", normalized):
            errors[field_name] = f"Invalid key format at index {idx}."
            return None
        parsed.add(normalized)
    return parsed


def _actor_id(request) -> str | None:
    return getattr(request.user, "user_id", None) or getattr(request.user, "username", None)


def _parse_required_decimal(value: Any, field_name: str, errors: Dict[str, str]) -> Decimal | None:
    if value in (None, ""):
        errors[field_name] = "This field is required."
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        errors[field_name] = "Must be a decimal number."
        return None
    if parsed <= 0:
        errors[field_name] = "Must be greater than zero."
        return None
    return parsed


def _normalize_selected_method_for_execution(value: Any) -> str | None:
    normalized = str(value or "").strip().upper()
    if not normalized:
        return None
    if normalized in {"FEFO", "FIFO", "MIXED", "MANUAL"}:
        return normalized
    return None


def _parse_allocation_selections(
    raw_allocations: Any,
    errors: Dict[str, str],
) -> list[dict[str, Any]]:
    if not isinstance(raw_allocations, list) or not raw_allocations:
        errors["allocations"] = "Must provide a non-empty array of allocations."
        return []

    selections: list[dict[str, Any]] = []
    for idx, raw_line in enumerate(raw_allocations):
        if not isinstance(raw_line, dict):
            errors[f"allocations[{idx}]"] = "Each allocation must be an object."
            continue

        line_errors: Dict[str, str] = {}
        item_id = _parse_positive_int(raw_line.get("item_id"), f"allocations[{idx}].item_id", line_errors)
        quantity = _parse_required_decimal(
            raw_line.get("quantity", raw_line.get("allocated_qty")),
            f"allocations[{idx}].quantity",
            line_errors,
        )
        inventory_id = _parse_positive_int(
            raw_line.get("inventory_id"),
            f"allocations[{idx}].inventory_id",
            line_errors,
        )
        batch_id = _parse_positive_int(
            raw_line.get("batch_id"),
            f"allocations[{idx}].batch_id",
            line_errors,
        )
        source_type = str(raw_line.get("source_type") or "ON_HAND").strip().upper() or "ON_HAND"
        if source_type not in {"ON_HAND", "TRANSFER", "DONATION", "PROCUREMENT"}:
            line_errors[f"allocations[{idx}].source_type"] = "Invalid source type."
        needs_list_item_id = None
        if raw_line.get("needs_list_item_id") not in (None, ""):
            needs_list_item_id = _parse_positive_int(
                raw_line.get("needs_list_item_id"),
                f"allocations[{idx}].needs_list_item_id",
                line_errors,
            )
        source_record_id = None
        if raw_line.get("source_record_id") not in (None, ""):
            source_record_id = _parse_positive_int(
                raw_line.get("source_record_id"),
                f"allocations[{idx}].source_record_id",
                line_errors,
            )
        if source_type != "PROCUREMENT":
            if inventory_id is None:
                line_errors[f"allocations[{idx}].inventory_id"] = "This field is required."
            if batch_id is None:
                line_errors[f"allocations[{idx}].batch_id"] = "This field is required."

        if line_errors:
            errors.update(line_errors)
            continue

        selections.append(
            {
                "item_id": item_id,
                "quantity": quantity,
                "inventory_id": inventory_id,
                "batch_id": batch_id,
                "source_type": source_type,
                "source_record_id": source_record_id,
                "uom_code": str(raw_line.get("uom_code") or "").strip() or None,
                "needs_list_item_id": needs_list_item_id,
                "override_reason_code": (
                    str(raw_line.get("override_reason_code") or "").strip() or None
                ),
                "override_note": str(raw_line.get("override_note") or "").strip() or None,
            }
        )
    return selections


def _upsert_execution_link(
    *,
    needs_list_id: int,
    actor_user_id: str,
    reliefrqst_id: int | None = None,
    reliefpkg_id: int | None = None,
    selected_method: str | None = None,
    execution_status: str,
    waybill_no: str | None = None,
    waybill_payload: Any = None,
    prepared: bool = False,
    committed: bool = False,
    override_requested: bool = False,
    override_approved: bool = False,
    dispatched: bool = False,
    received: bool = False,
    cancelled: bool = False,
) -> NeedsListExecutionLink | None:
    if (
        execution_status == NeedsListExecutionLink.ExecutionStatus.DISPATCHED
        and (reliefrqst_id is None or reliefpkg_id is None)
    ):
        raise ValueError(
            "Execution links cannot transition to DISPATCHED without both reliefrqst_id and reliefpkg_id."
        )
    now = timezone.now()
    try:
        defaults: Dict[str, Any] = {
            "update_by_id": actor_user_id,
            "execution_status": execution_status,
        }
        if reliefrqst_id is not None:
            defaults["reliefrqst_id"] = reliefrqst_id
        if reliefpkg_id is not None:
            defaults["reliefpkg_id"] = reliefpkg_id
        if selected_method is not None:
            defaults["selected_method"] = selected_method
        if waybill_no is not None:
            defaults["waybill_no"] = waybill_no
        if waybill_payload is not None:
            defaults["waybill_payload_json"] = waybill_payload
        if prepared:
            defaults["prepared_at"] = now
            defaults["prepared_by"] = actor_user_id
        if committed:
            defaults["committed_at"] = now
            defaults["committed_by"] = actor_user_id
        if override_requested:
            defaults["override_requested_at"] = now
            defaults["override_requested_by"] = actor_user_id
        if override_approved:
            defaults["override_approved_at"] = now
            defaults["override_approved_by"] = actor_user_id
        if dispatched:
            defaults["dispatched_at"] = now
            defaults["dispatched_by"] = actor_user_id
        if received:
            defaults["received_at"] = now
            defaults["received_by"] = actor_user_id
        if cancelled:
            defaults["cancelled_at"] = now
            defaults["cancelled_by"] = actor_user_id

        link, created = NeedsListExecutionLink.objects.get_or_create(
            needs_list_id=needs_list_id,
            defaults={
                "create_by_id": actor_user_id,
                "reliefrqst_id": reliefrqst_id,
                **defaults,
            },
        )
        if created:
            return link
        for field, value in defaults.items():
            setattr(link, field, value)
        link.save()
        return link
    except (DatabaseError, OperationalError, ProgrammingError):
        return None


def _replace_execution_allocation_lines(
    *,
    needs_list: NeedsList,
    selections: list[dict[str, Any]],
    actor_user_id: str,
    rule_bypass_flag: bool,
    override_reason_code: str | None = None,
    override_note: str | None = None,
    supervisor_user_id: str | None = None,
) -> None:
    try:
        NeedsListAllocationLine.objects.filter(needs_list=needs_list).delete()
        item_map = {item.item_id: item for item in needs_list.items.all()}
        now = timezone.now()
        rows: list[NeedsListAllocationLine] = []
        for index, selection in enumerate(selections, start=1):
            needs_item = item_map.get(selection["item_id"])
            rows.append(
                NeedsListAllocationLine(
                    needs_list=needs_list,
                    needs_list_item=needs_item,
                    item_id=selection["item_id"],
                    inventory_id=selection.get("inventory_id") or 0,
                    batch_id=selection.get("batch_id") or 0,
                    uom_code=selection.get("uom_code") or getattr(needs_item, "uom_code", None) or "EA",
                    source_type=selection.get("source_type") or "ON_HAND",
                    source_record_id=selection.get("source_record_id"),
                    allocated_qty=selection["quantity"],
                    allocation_rank=index,
                    rule_bypass_flag=rule_bypass_flag,
                    override_reason_code=override_reason_code,
                    override_note=override_note,
                    supervisor_approved_by=supervisor_user_id,
                    supervisor_approved_at=now if supervisor_user_id else None,
                    create_by_id=actor_user_id,
                    update_by_id=actor_user_id,
                )
            )
        NeedsListAllocationLine.objects.bulk_create(rows)
    except (DatabaseError, OperationalError, ProgrammingError):
        return


def _stored_execution_allocation_lines(needs_list_id: int) -> list[dict[str, Any]]:
    try:
        rows = list(
            NeedsListAllocationLine.objects.filter(needs_list_id=needs_list_id)
            .order_by("allocation_rank", "allocation_line_id")
            .values(
                "needs_list_item_id",
                "item_id",
                "inventory_id",
                "batch_id",
                "uom_code",
                "source_type",
                "source_record_id",
                "allocated_qty",
                "allocation_rank",
                "rule_bypass_flag",
                "override_reason_code",
                "override_note",
                "supervisor_approved_by",
                "supervisor_approved_at",
            )
        )
    except (DatabaseError, OperationalError, ProgrammingError):
        return []

    allocations: list[dict[str, Any]] = []
    for row in rows:
        allocations.append(
            {
                "needs_list_item_id": row.get("needs_list_item_id"),
                "item_id": row.get("item_id"),
                "inventory_id": row.get("inventory_id"),
                "batch_id": row.get("batch_id"),
                "uom_code": row.get("uom_code"),
                "source_type": row.get("source_type"),
                "source_record_id": row.get("source_record_id"),
                "quantity": str(allocation_dispatch._quantize_qty(row.get("allocated_qty") or 0)),
                "allocation_rank": row.get("allocation_rank"),
                "rule_bypass_flag": bool(row.get("rule_bypass_flag")),
                "override_reason_code": row.get("override_reason_code"),
                "override_note": row.get("override_note"),
                "supervisor_approved_by": row.get("supervisor_approved_by"),
                "supervisor_approved_at": (
                    row.get("supervisor_approved_at").isoformat()
                    if row.get("supervisor_approved_at")
                    else None
                ),
            }
        )
    return allocations


def _selection_signature(lines: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    return [
        (
            int(line.get("item_id") or 0),
            int(line.get("inventory_id") or 0),
            int(line.get("batch_id") or 0),
            str(allocation_dispatch._quantize_qty(line.get("quantity", line.get("allocated_qty")) or 0)),
            str(line.get("source_type") or "ON_HAND").strip().upper(),
            int(line.get("source_record_id") or 0),
            str(line.get("uom_code") or "").strip().upper(),
        )
        for line in lines
    ]


_DIRECTOR_PEOD_ROLE_CODES = {
    "DIR_PEOD",
    "ODPEM_DIR_PEOD",
    "TST_DIR_PEOD",
    "DIRECTOR_GENERAL",
    "ODPEM_DG",
    "TST_DG",
    "DG",
}


def _has_director_peod_authority(request) -> bool:
    roles, _ = resolve_roles_and_permissions(request, request.user)
    normalized_roles = {str(role).strip().upper() for role in roles}
    return bool(normalized_roles & _DIRECTOR_PEOD_ROLE_CODES)


def _tenant_context(request):
    cached = getattr(request, "_tenant_context_cache", None)
    if cached is not None:
        return cached
    _, permissions = resolve_roles_and_permissions(request, request.user)
    context = resolve_tenant_context(request, request.user, permissions)
    request._tenant_context_cache = context
    return context


def _should_enforce_tenant_scope(request) -> bool:
    """
    Rollout gate for strict tenant scope enforcement.
    When enabled, all tenant-scoped read/write paths are enforced.
    """
    return bool(getattr(settings, "TENANT_SCOPE_ENFORCEMENT", False))


def _accessible_read_warehouse_ids(request) -> set[int] | None:
    if not _should_enforce_tenant_scope(request):
        return None

    context = _tenant_context(request)
    # Read-all national/NEOC users should keep their cross-tenant visibility; a
    # requested tenant can influence the active context without becoming a hard
    # pre-hydration warehouse filter on list endpoints.
    if context.can_read_all_tenants:
        return None

    if context.requested_tenant_id is not None and context.active_tenant_id is not None:
        tenant_ids = {context.active_tenant_id}
    else:
        tenant_ids = set(context.membership_tenant_ids)
        if not tenant_ids and context.active_tenant_id is not None:
            tenant_ids.add(context.active_tenant_id)

    if not tenant_ids:
        return set()

    return data_access.get_warehouse_ids_for_tenants(tenant_ids)


def _tenant_scope_denied_response(
    request,
    *,
    warehouse_id: int | None = None,
    record: Dict[str, Any] | None = None,
    write: bool = False,
) -> Response:
    context = _tenant_context(request)
    details: Dict[str, Any] = {
        "message": "Access denied for tenant scope.",
        "write": bool(write),
        "tenant_context": tenant_context_to_dict(context),
    }
    if warehouse_id is not None:
        details["warehouse_id"] = warehouse_id
        details["target_tenant_id"] = resolve_warehouse_tenant_id(warehouse_id)
    if isinstance(record, dict):
        details["needs_list_id"] = record.get("needs_list_id")
        details["record_warehouse_id"] = record.get("warehouse_id")
    return Response({"errors": {"tenant_scope": details}}, status=403)


def _require_warehouse_scope(
    request,
    warehouse_id: object,
    *,
    write: bool = False,
) -> Response | None:
    if not _should_enforce_tenant_scope(request):
        return None
    parsed_warehouse_id = _to_int_or_none(warehouse_id)
    if parsed_warehouse_id is None:
        return None
    context = _tenant_context(request)
    if can_access_warehouse(context, parsed_warehouse_id, write=write):
        return None
    return _tenant_scope_denied_response(
        request,
        warehouse_id=parsed_warehouse_id,
        write=write,
    )


def _require_record_scope(
    request,
    record: Dict[str, Any],
    *,
    write: bool = False,
) -> Response | None:
    if not _should_enforce_tenant_scope(request):
        return None
    context = _tenant_context(request)
    if can_access_record(context, record, write=write):
        return None
    return _tenant_scope_denied_response(
        request,
        record=record,
        write=write,
    )


def _record_tenant_id(record: Dict[str, Any], snapshot: Dict[str, Any] | None = None) -> int | None:
    record_tenant = _to_int_or_none(record.get("tenant_id"))
    if record_tenant is not None:
        return record_tenant
    warehouse_id = _to_int_or_none(record.get("warehouse_id"))
    if warehouse_id is None and isinstance(snapshot, dict):
        warehouse_id = _to_int_or_none(snapshot.get("warehouse_id"))
    if warehouse_id is None:
        return None
    return resolve_warehouse_tenant_id(warehouse_id)


def _audit_username(request) -> str | None:
    return getattr(request.user, "username", None)


def _log_audit_event(
    event_name: str,
    request,
    *,
    event_type: str,
    action: str,
    procurement_id: int | None = None,
    supplier_id: int | None = None,
    from_status: str | None = None,
    to_status: str | None = None,
    **context: object,
) -> None:
    # Merge caller context first so core audit fields cannot be overwritten.
    extra = {
        **context,
        "event_type": event_type,
        "user_id": _actor_id(request),
        "username": _audit_username(request),
        "action": action,
        "procurement_id": procurement_id,
        "supplier_id": supplier_id,
        "from_status": from_status,
        "to_status": to_status,
    }
    logger.info(event_name, extra=extra)


def _normalize_actor(value: object) -> str:
    return str(value or "").strip().lower()


def _query_param_truthy(value: object, *, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if not normalized:
        return default
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _safe_content_disposition_ref(value: object, fallback: object) -> str:
    def _clean(raw: object) -> str:
        cleaned = (
            str(raw or "")
            .replace("\r", "")
            .replace("\n", "")
            .replace('"', "")
            .strip()
        )
        return cleaned

    cleaned = _clean(value)
    if cleaned:
        return cleaned
    fallback_cleaned = _clean(fallback)
    return fallback_cleaned or "needs_list"


_ASYNC_EXPORT_JOB_TYPES = {
    "donation": AsyncJob.JobType.NEEDS_LIST_DONATION_EXPORT,
    "procurement": AsyncJob.JobType.NEEDS_LIST_PROCUREMENT_EXPORT,
}
_NEEDS_LIST_EXPORT_RATE_LIMIT_PER_MINUTE = 5
_NEEDS_LIST_EXPORT_RATE_LIMIT_WINDOW_SECONDS = 60
_NEEDS_LIST_EXPORT_RATE_LIMIT_CACHE_TIMEOUT_SECONDS = (
    _NEEDS_LIST_EXPORT_RATE_LIMIT_WINDOW_SECONDS + 5
)
_NEEDS_LIST_EXPORT_RATE_LIMIT_LOCK_TIMEOUT_SECONDS = 5
_NEEDS_LIST_EXPORT_RATE_LIMIT_LOCK_WAIT_SECONDS = 0.01
_NEEDS_LIST_EXPORT_RATE_LIMIT_LOCK_ATTEMPTS = 20


def _needs_list_snapshot_version(record: Dict[str, Any], needs_list_id: str) -> str:
    serialized = _serialize_workflow_record(record, include_overrides=False)
    normalized_status = _normalize_status_for_ui(serialized.get("status"))
    updated_at = (
        serialized.get("updated_at")
        or serialized.get("approved_at")
        or serialized.get("submitted_at")
        or serialized.get("created_at")
    )
    return f"{serialized.get('needs_list_id') or needs_list_id}|{updated_at or ''}|{normalized_status}"


def _async_job_status_url(job: AsyncJob) -> str:
    return reverse("async_job_status", kwargs={"job_id": job.job_id})


def _async_job_download_url(job: AsyncJob) -> str:
    return reverse("async_job_download", kwargs={"job_id": job.job_id})


def _serialize_export_job(job: AsyncJob) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "job_id": job.job_id,
        "job_type": job.job_type,
        "status": job.status,
        "queued_at": job.queued_at.isoformat() if job.queued_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "expires_at": job.expires_at.isoformat() if job.expires_at else None,
        "retry_count": job.retry_count,
        "max_retries": job.max_retries,
        "error_message": job.error_message,
        "artifact_ready": job.artifact_ready,
        "status_url": _async_job_status_url(job),
    }
    if job.artifact_ready:
        payload["download_url"] = _async_job_download_url(job)
    return payload


def _async_export_dedupe_key(
    *,
    job_type: str,
    needs_list_id: str,
    actor_user_id: str | None,
    snapshot_version: str,
) -> str:
    base = "|".join(
        [
            job_type,
            str(needs_list_id or "").strip(),
            str(actor_user_id or "").strip(),
            str(snapshot_version or "").strip(),
        ]
    )
    return f"async-export:{hashlib.sha256(base.encode('utf-8')).hexdigest()}"


def _request_client_ip(request) -> str:
    remote_addr = _normalize_ip_address(request.META.get("REMOTE_ADDR"))
    if not remote_addr:
        return "-"

    trusted_proxies = _trusted_proxy_ip_set()
    if remote_addr not in trusted_proxies:
        return remote_addr

    forwarded_for = str(request.META.get("HTTP_X_FORWARDED_FOR", "") or "").strip()
    if not forwarded_for:
        return remote_addr

    for raw_candidate in forwarded_for.split(","):
        candidate = _normalize_ip_address(raw_candidate)
        if candidate and candidate not in trusted_proxies:
            return candidate
    return remote_addr


def _normalize_ip_address(value: object) -> str | None:
    candidate = str(value or "").strip()
    if not candidate or len(candidate) > 64:
        return None
    try:
        return ipaddress.ip_address(candidate).compressed
    except ValueError:
        return None


def _trusted_proxy_ip_set() -> set[str]:
    trusted = set()
    for raw_proxy in getattr(settings, "TRUSTED_PROXIES", ()) or ():
        normalized_proxy = _normalize_ip_address(raw_proxy)
        if normalized_proxy:
            trusted.add(normalized_proxy)
    return trusted


def _needs_list_export_rate_limit_key(
    *,
    user_key: str,
    client_ip: str,
    tenant_id: int | None,
) -> str:
    return ":".join(
        [
            "needs-list-export-rate-limit",
            str(tenant_id if tenant_id is not None else "global"),
            user_key,
            client_ip or "-",
        ]
    )


def _acquire_needs_list_export_rate_limit_lock(lock_key: str) -> str | None:
    for _ in range(_NEEDS_LIST_EXPORT_RATE_LIMIT_LOCK_ATTEMPTS):
        owner_token = str(uuid.uuid4())
        if cache.add(
            lock_key,
            owner_token,
            timeout=_NEEDS_LIST_EXPORT_RATE_LIMIT_LOCK_TIMEOUT_SECONDS,
        ):
            return owner_token
        time.sleep(_NEEDS_LIST_EXPORT_RATE_LIMIT_LOCK_WAIT_SECONDS)
    return None


def _release_needs_list_export_rate_limit_lock(
    lock_key: str,
    owner_token: str | None,
) -> None:
    if not owner_token:
        return
    if cache.get(lock_key) == owner_token:
        cache.delete(lock_key)


def _claim_needs_list_export_slot(
    request,
    *,
    user_key: str,
    client_ip: str,
    tenant_id: int | None,
    endpoint_tier: str,
    active_event_phase: str | None,
    actor_user_id: str | None,
) -> tuple[bool, int]:
    now = timezone.now().timestamp()
    capacity = float(_NEEDS_LIST_EXPORT_RATE_LIMIT_PER_MINUTE)
    refill_window = float(_NEEDS_LIST_EXPORT_RATE_LIMIT_WINDOW_SECONDS)
    refill_rate = capacity / refill_window
    cache_key = _needs_list_export_rate_limit_key(
        user_key=user_key,
        client_ip=client_ip,
        tenant_id=tenant_id,
    )
    lock_key = f"{cache_key}:lock"
    cache_timeout = _NEEDS_LIST_EXPORT_RATE_LIMIT_CACHE_TIMEOUT_SECONDS
    lock_owner_token = _acquire_needs_list_export_rate_limit_lock(lock_key)
    if not lock_owner_token:
        logger.warning(
            "request.throttled",
            extra=build_log_extra(
                request,
                event="request.throttled",
                status_code=429,
                endpoint_tier=endpoint_tier,
                active_event_phase=active_event_phase,
                enforcement_key=cache_key,
                actor_user_id=actor_user_id,
                tenant_id=tenant_id,
                client_ip=client_ip,
                token_count=0.0,
                retry_after=1,
                throttle_reason="lock_timeout",
            ),
        )
        return False, 1

    try:
        state = cache.get(cache_key) or {}
        tokens = float(state.get("tokens", capacity))
        last_refill = float(state.get("last_refill", now))
        elapsed = max(now - last_refill, 0.0)
        tokens = min(capacity, tokens + (elapsed * refill_rate))

        if tokens < 1.0:
            retry_after = max(int(math.ceil((1.0 - tokens) / refill_rate)), 1)
            cache.set(
                cache_key,
                {"tokens": tokens, "last_refill": now},
                timeout=cache_timeout,
            )
            logger.warning(
                "request.throttled",
                extra=build_log_extra(
                    request,
                    event="request.throttled",
                    status_code=429,
                    endpoint_tier=endpoint_tier,
                    active_event_phase=active_event_phase,
                    enforcement_key=cache_key,
                    actor_user_id=actor_user_id,
                    tenant_id=tenant_id,
                    client_ip=client_ip,
                    token_count=round(tokens, 3),
                    retry_after=retry_after,
                    throttle_reason="token_bucket_exhausted",
                ),
            )
            return False, retry_after

        cache.set(
            cache_key,
            {"tokens": tokens - 1.0, "last_refill": now},
            timeout=cache_timeout,
        )
        return True, 1
    finally:
        _release_needs_list_export_rate_limit_lock(lock_key, lock_owner_token)


def _needs_list_export_rate_limited_response(
    request,
    *,
    needs_list_id: str,
    job_type: str,
    tenant_id: int | None,
    tenant_code: str | None,
    actor_user_id: str | None,
    actor_username: str | None,
    retry_after: int,
) -> Response:
    response = Response(
        {
            "errors": {
                "async": (
                    "Too many queued export requests. Wait before requesting another export."
                )
            }
        },
        status=429,
    )
    response["Retry-After"] = str(retry_after)
    return response


def _queue_export_job_log_extra(
    request,
    *,
    job: AsyncJob,
    needs_list_id: str,
    tenant_id: int | None,
    tenant_code: str | None,
    data_version: str,
) -> dict[str, object]:
    return build_log_extra(
        request,
        event="job.queued",
        job_id=job.job_id,
        job_type=job.job_type,
        needs_list_id=needs_list_id,
        tenant_id=tenant_id,
        tenant_code=tenant_code,
        actor_user_id=job.actor_user_id,
        actor_username=job.actor_username,
        source_resource_type=job.source_resource_type,
        source_resource_id=job.source_resource_id,
        source_snapshot_version=data_version,
        retry_count=job.retry_count,
    )


def _enqueue_needs_list_export_job(
    request,
    *,
    needs_list_id: str,
    record: Dict[str, Any],
    export_kind: str,
) -> Response:
    export_kind_normalized = str(export_kind or "").strip().lower()
    job_type = _ASYNC_EXPORT_JOB_TYPES.get(export_kind_normalized)
    if job_type is None:
        return Response({"errors": {"export": "Unsupported export kind."}}, status=400)

    payload_data = request.data if isinstance(request.data, dict) else {}
    requested_format = str(
        payload_data.get("format")
        or request.query_params.get("format")
        or "csv"
    ).strip().lower()
    if requested_format != "csv":
        return Response(
            {
                "errors": {
                    "format": "Only CSV export is supported for queued needs-list exports."
                }
            },
            status=400,
        )

    audit_schema_status, audit_schema_reason = get_replenishment_export_audit_schema_status()
    if audit_schema_status == "failed":
        logger.error(
            "job.queue_blocked",
            extra=build_log_extra(
                request,
                event="job.queue_blocked",
                needs_list_id=needs_list_id,
                job_type=job_type,
                dependency="export_audit_schema",
                error_message=audit_schema_reason,
            ),
        )
        return Response(
            {
                "errors": {
                    "async": (
                        "Queued export is unavailable until the replenishment export audit "
                        "schema update is applied."
                    )
                },
                "detail": audit_schema_reason,
            },
            status=503,
        )

    tenant_context = _tenant_context(request)
    tenant_id = _record_tenant_id(record)
    tenant_code = tenant_context.active_tenant_code
    actor_user_id = _actor_id(request)
    actor_username = _audit_username(request)
    request_id = get_request_id(request)
    data_version = _needs_list_snapshot_version(record, needs_list_id)
    rate_limit_actor_key = str(actor_user_id or actor_username or "unknown").strip()
    client_ip = _request_client_ip(request)
    active_event_phase = str(
        record.get("event_phase") or record.get("phase") or ""
    ).strip().upper() or None
    dedupe_key = _async_export_dedupe_key(
        job_type=job_type,
        needs_list_id=needs_list_id,
        actor_user_id=actor_user_id,
        snapshot_version=data_version,
    )
    existing_job = AsyncJob.objects.filter(active_dedupe_key=dedupe_key).first()
    if existing_job is not None:
        payload = {
            "needs_list_id": needs_list_id,
            "format": requested_format,
            "data_version": data_version,
            **_serialize_export_job(existing_job),
            "deduplicated": True,
        }
        return Response(payload, status=202)

    allowed, retry_after = _claim_needs_list_export_slot(
        request,
        user_key=rate_limit_actor_key,
        client_ip=client_ip,
        tenant_id=tenant_id,
        endpoint_tier="file_export",
        active_event_phase=active_event_phase,
        actor_user_id=actor_user_id,
    )
    if not allowed:
        return _needs_list_export_rate_limited_response(
            request,
            needs_list_id=needs_list_id,
            job_type=job_type,
            tenant_id=tenant_id,
            tenant_code=tenant_code,
            actor_user_id=actor_user_id,
            actor_username=actor_username,
            retry_after=retry_after,
        )

    created = False
    try:
        with transaction.atomic():
            job = (
                AsyncJob.objects.select_for_update()
                .filter(active_dedupe_key=dedupe_key)
                .first()
            )
            if job is None:
                job = AsyncJob.objects.create(
                    job_id=str(uuid.uuid4()),
                    job_type=job_type,
                    status=AsyncJob.Status.QUEUED,
                    actor_user_id=actor_user_id,
                    actor_username=actor_username,
                    tenant_id=tenant_id,
                    tenant_code=tenant_code,
                    request_id=request_id if request_id != "-" else None,
                    source_resource_type=AsyncJob.SourceType.NEEDS_LIST,
                    source_resource_id=needs_list_id,
                    source_snapshot_version=data_version,
                    active_dedupe_key=dedupe_key,
                )
                created = True
    except IntegrityError:
        job = AsyncJob.objects.get(active_dedupe_key=dedupe_key)

    if created:
        logger.info(
            "job.queued",
            extra=_queue_export_job_log_extra(
                request,
                job=job,
                needs_list_id=needs_list_id,
                tenant_id=tenant_id,
                tenant_code=tenant_code,
                data_version=data_version,
            ),
        )
        try:
            async_tasks = import_module("api.tasks")
            async_tasks.run_async_job.delay(job.job_id)
            job.refresh_from_db()
        except ModuleNotFoundError as exc:
            if exc.name == "celery":
                job.mark_failed(
                    error_message="Async worker plane is unavailable because Celery is not installed."
                )
                job.save(
                    update_fields=[
                        "status",
                        "error_message",
                        "finished_at",
                        "active_dedupe_key",
                        "artifact_filename",
                        "artifact_content_type",
                        "artifact_sha256",
                        "artifact_payload",
                        "expires_at",
                    ]
                )
                logger.error(
                    "job.failed",
                    extra=build_log_extra(
                        request,
                        event="job.failed",
                        job_id=job.job_id,
                        job_type=job.job_type,
                        needs_list_id=needs_list_id,
                        tenant_id=tenant_id,
                        tenant_code=tenant_code,
                        actor_user_id=job.actor_user_id,
                        actor_username=job.actor_username,
                        source_resource_type=job.source_resource_type,
                        source_resource_id=job.source_resource_id,
                        source_snapshot_version=data_version,
                        error_message=job.error_message,
                    ),
                )
                return Response(
                    {
                        "errors": {
                            "async": "Queued export is unavailable because the worker plane dependency is not installed."
                        }
                    },
                    status=503,
                )
            raise

    payload = {
        "needs_list_id": needs_list_id,
        "format": requested_format,
        "data_version": data_version,
        **_serialize_export_job(job),
    }
    if not created:
        payload["deduplicated"] = True
    return Response(payload, status=202)


def _needs_list_export_preview_response(
    *,
    needs_list_id: str,
    record: Dict[str, Any],
    export_kind: str,
) -> Response:
    snapshot = workflow_store.apply_overrides(record)
    return Response(
        needs_list.build_needs_list_export_preview(
            snapshot=snapshot,
            export_kind=export_kind,
            needs_list_id=needs_list_id,
            export_format="json",
        )
    )


def _reviewer_must_differ_from_submitter(record: Dict[str, Any], actor: str | None) -> Response | None:
    submitted_by = record.get("submitted_by")
    if not submitted_by or submitted_by == actor:
        return Response(
            {"errors": {"review": "Reviewer must be different from submitter."}},
            status=409,
        )
    return None


def _to_float_or_none(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int_or_none(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _record_sort_timestamp(record: Dict[str, Any]) -> float:
    for field in (
        "updated_at",
        "approved_at",
        "reviewed_at",
        "submitted_at",
        "created_at",
        "as_of_datetime",
    ):
        raw_value = record.get(field)
        if not raw_value:
            continue
        value = str(raw_value)
        parsed = parse_datetime(value)
        if parsed is None:
            continue
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed, timezone.get_default_timezone())
        return parsed.timestamp()
    return 0.0


def _items_have_actionable_state(items: list[Dict[str, Any]]) -> bool:
    for item in items:
        burn = _to_float_or_none(item.get("burn_rate_per_hour")) or 0.0
        gap = _to_float_or_none(item.get("gap_qty")) or 0.0
        severity = str(item.get("severity") or "OK").upper()
        if burn > 0 or gap > 0 or severity in {"CRITICAL", "WARNING", "WATCH"}:
            return True
    return False


def _stock_state_scope_key(event_id: int, warehouse_id: int, phase: str) -> str:
    return f"{event_id}:{warehouse_id}:{str(phase or '').strip().upper()}"


def _stock_state_store_path() -> Path:
    configured_path = getattr(settings, "NEEDS_STOCK_STATE_STORE_PATH", None)
    if configured_path:
        return Path(str(configured_path))
    base_dir = Path(getattr(settings, "BASE_DIR", Path.cwd()))
    return base_dir / "runtime" / "stock_state_cache.json"


def _stock_state_lock_path(store_path: Path) -> Path:
    return store_path.with_suffix(store_path.suffix + ".lock")


def _acquire_stock_state_file_lock(file_handle, *, exclusive: bool) -> None:
    if fcntl is not None:
        lock_type = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        fcntl.flock(file_handle.fileno(), lock_type)
        return
    if msvcrt is not None:
        lock_type = msvcrt.LK_LOCK if exclusive else getattr(msvcrt, "LK_RLCK", msvcrt.LK_LOCK)
        file_handle.seek(0)
        try:
            msvcrt.locking(file_handle.fileno(), lock_type, 1)
        except OSError as exc:
            logger.warning(
                "Failed acquiring stock-state lock for %s (exclusive=%s): %s",
                getattr(file_handle, "name", "<unknown>"),
                exclusive,
                exc,
            )
            raise


def _release_stock_state_file_lock(file_handle) -> None:
    if fcntl is not None:
        fcntl.flock(file_handle.fileno(), fcntl.LOCK_UN)
        return
    if msvcrt is not None:
        file_handle.seek(0)
        try:
            msvcrt.locking(file_handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError as exc:
            logger.warning(
                "Stock-state unlock failed for %s; continuing: %s",
                getattr(file_handle, "name", "<unknown>"),
                exc,
            )


@contextmanager
def _fallback_stock_state_file(store_path: Path, *, exclusive: bool):
    """
    Best-effort fallback when sidecar lock file acquisition is unavailable.
    """
    with store_path.open("a+", encoding="utf-8") as file_handle:
        _acquire_stock_state_file_lock(file_handle, exclusive=exclusive)
        try:
            file_handle.seek(0)
            yield file_handle
        finally:
            _release_stock_state_file_lock(file_handle)


@contextmanager
def _locked_stock_state_file(*, exclusive: bool):
    store_path = _stock_state_store_path()
    store_path.parent.mkdir(parents=True, exist_ok=True)

    # On POSIX, lock the data file directly with flock.
    if fcntl is not None:
        with store_path.open("a+", encoding="utf-8") as file_handle:
            _acquire_stock_state_file_lock(file_handle, exclusive=exclusive)
            try:
                file_handle.seek(0)
                yield file_handle
            finally:
                _release_stock_state_file_lock(file_handle)
        return

    # On Windows, prefer a sidecar lock file for cross-process coordination.
    lock_path = _stock_state_lock_path(store_path)
    yielded = False
    attempted_sidecar_lock = False
    try:
        with lock_path.open("a+b") as lock_handle:
            lock_handle.seek(0, os.SEEK_END)
            if lock_handle.tell() == 0:
                lock_handle.write(b"0")
                lock_handle.flush()
                try:
                    os.fsync(lock_handle.fileno())
                except OSError as exc:
                    logger.warning(
                        "Stock-state lock fsync unavailable for %s; continuing: %s",
                        lock_path,
                        exc,
                    )
            attempted_sidecar_lock = True
            _acquire_stock_state_file_lock(lock_handle, exclusive=exclusive)
            try:
                with store_path.open("a+", encoding="utf-8") as file_handle:
                    file_handle.seek(0)
                    yielded = True
                    yield file_handle
            finally:
                _release_stock_state_file_lock(lock_handle)
        return
    except OSError as exc:
        if yielded or attempted_sidecar_lock:
            raise
        logger.warning("Failed acquiring stock-state file lock for %s: %s", store_path, exc)
        with _fallback_stock_state_file(store_path, exclusive=exclusive) as file_handle:
            yield file_handle


def _load_stock_state_store_from_file(file_handle) -> Dict[str, Any]:
    file_handle.seek(0)
    raw = file_handle.read()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("Failed parsing stock-state cache file content: %s", exc)
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _write_stock_state_store_to_file(file_handle, store: Dict[str, Any]) -> None:
    file_handle.seek(0)
    file_handle.truncate()
    json.dump(store, file_handle)
    file_handle.flush()
    try:
        os.fsync(file_handle.fileno())
    except OSError as exc:
        logger.warning(
            "Stock-state fsync unavailable for %s; continuing: %s",
            getattr(file_handle, "name", "<unknown>"),
            exc,
        )


def _read_stock_state_store() -> Dict[str, Any]:
    store_path = _stock_state_store_path()
    try:
        with _locked_stock_state_file(exclusive=False) as file_handle:
            return _load_stock_state_store_from_file(file_handle)
    except OSError as exc:
        logger.warning("Failed reading stock-state cache file %s: %s", store_path, exc)
        return {}


def _write_stock_state_store(store: Dict[str, Any]) -> None:
    store_path = _stock_state_store_path()
    try:
        with _locked_stock_state_file(exclusive=True) as file_handle:
            _write_stock_state_store_to_file(file_handle, store)
    except OSError as exc:
        logger.warning("Failed writing stock-state cache file %s: %s", store_path, exc)


def _persist_stock_state_snapshot(
    event_id: int,
    warehouse_id: int,
    phase: str,
    as_of_datetime: str,
    items: list[Dict[str, Any]],
    warnings: list[str],
) -> None:
    if not _items_have_actionable_state(items):
        return
    payload = {
        "event_id": event_id,
        "warehouse_id": warehouse_id,
        "phase": str(phase or "").strip().upper(),
        "as_of_datetime": as_of_datetime,
        "items": [dict(item) for item in items if isinstance(item, dict)],
        "warnings": [str(warning) for warning in warnings],
        "saved_at": timezone.now().isoformat(),
    }
    scope_key = _stock_state_scope_key(event_id, warehouse_id, phase)
    store_path = _stock_state_store_path()
    try:
        with _locked_stock_state_file(exclusive=True) as file_handle:
            store = _load_stock_state_store_from_file(file_handle)
            store[scope_key] = payload
            _write_stock_state_store_to_file(file_handle, store)
    except OSError as exc:
        logger.warning("Failed persisting stock-state snapshot to %s: %s", store_path, exc)


def _load_stock_state_snapshot(
    event_id: int,
    warehouse_id: int,
    phase: str,
) -> Dict[str, Any] | None:
    scope_key = _stock_state_scope_key(event_id, warehouse_id, phase)
    store = _read_stock_state_store()
    raw_snapshot = store.get(scope_key)
    if not isinstance(raw_snapshot, dict):
        return None
    snapshot_items = raw_snapshot.get("items")
    if not isinstance(snapshot_items, list) or not snapshot_items:
        return None
    normalized_items = [dict(item) for item in snapshot_items if isinstance(item, dict)]
    if not normalized_items:
        return None
    if not _items_have_actionable_state(normalized_items):
        return None
    restored = dict(raw_snapshot)
    restored["items"] = normalized_items
    restored["restored_from_needs_list_id"] = "stock_state_cache"
    return restored


def _should_restore_persisted_state(
    items: list[Dict[str, Any]], warnings: list[str]
) -> bool:
    if _items_have_actionable_state(items):
        return False
    warning_set = {str(warning or "").strip().lower() for warning in warnings}
    return bool({"burn_data_missing", "burn_no_rows_in_window"}.intersection(warning_set))


def _load_persisted_snapshot_for_scope(
    event_id: int,
    warehouse_id: int,
    phase: str,
) -> Dict[str, Any] | None:
    cached = _load_stock_state_snapshot(event_id, warehouse_id, phase)
    if cached:
        return cached

    try:
        records = workflow_store.list_records(allowed_warehouse_ids=[warehouse_id])
    except RuntimeError:
        return None
    except Exception as exc:
        logger.warning("Failed loading workflow records for stock-state restore: %s", exc)
        return None

    if not records:
        return None

    normalized_phase = str(phase or "").strip().upper()
    sorted_records = sorted(records, key=_record_sort_timestamp, reverse=True)

    for record in sorted_records:
        if _to_int_or_none(record.get("event_id")) != event_id:
            continue
        if _to_int_or_none(record.get("warehouse_id")) != warehouse_id:
            continue
        if str(record.get("phase") or "").strip().upper() != normalized_phase:
            continue

        snapshot = None
        try:
            snapshot = workflow_store.apply_overrides(record)
        except Exception:
            snapshot = dict(record.get("snapshot") or {})

        if not isinstance(snapshot, dict):
            continue

        snapshot_items = snapshot.get("items")
        if not isinstance(snapshot_items, list) or not snapshot_items:
            continue

        normalized_items = [dict(item) for item in snapshot_items if isinstance(item, dict)]
        if not normalized_items:
            continue
        if not _items_have_actionable_state(normalized_items):
            continue

        restored = dict(snapshot)
        restored["items"] = normalized_items
        restored["restored_from_needs_list_id"] = record.get("needs_list_id")
        return restored

    return None


def _compute_approval_summary(
    record: Dict[str, Any],
    snapshot: Dict[str, Any],
) -> Dict[str, Any]:
    tenant_id = _record_tenant_id(record, snapshot)
    selected_method = _normalize_horizon_key(
        record.get("selected_method") or snapshot.get("selected_method")
    )
    total_required_qty, total_estimated_cost, approval_warnings = (
        approval_service.compute_needs_list_totals(snapshot.get("items") or [])
    )
    if selected_method in {"A", "B"}:
        # Transfer and donation approvals are not procurement-cost driven.
        approval_warnings = []
    approval, approval_warnings_extra, approval_rationale = (
        approval_service.determine_approval_tier(
            str(record.get("phase") or "BASELINE"),
            total_estimated_cost,
            bool(approval_warnings),
            selected_method=selected_method,
            tenant_id=tenant_id,
        )
    )
    authority_warnings, escalation_required = (
        approval_service.evaluate_appendix_c_authority(snapshot.get("items") or [])
    )
    warnings = needs_list.merge_warnings(
        approval_warnings, approval_warnings_extra + authority_warnings
    )
    parsed_cost = _to_float_or_none(total_estimated_cost)
    return {
        "total_required_qty": round(float(total_required_qty or 0.0), 2),
        "total_estimated_cost": None if parsed_cost is None else round(parsed_cost, 2),
        "approval": approval,
        "warnings": warnings,
        "rationale": approval_rationale,
        "escalation_required": escalation_required,
        "tenant_id": tenant_id,
        "policy_version": approval.get("policy_version"),
    }


def _normalize_submitted_approval_summary(summary: object) -> Dict[str, Any] | None:
    if not isinstance(summary, dict):
        return None
    approval = summary.get("approval")
    if not isinstance(approval, dict):
        approval = {}
    warnings_raw = summary.get("warnings")
    warnings = (
        [str(warning).strip() for warning in warnings_raw if str(warning).strip()]
        if isinstance(warnings_raw, list)
        else []
    )
    total_required_qty = _to_float_or_none(summary.get("total_required_qty")) or 0.0
    total_estimated_cost = summary.get("total_estimated_cost")
    parsed_cost = None
    if total_estimated_cost is not None:
        parsed_cost = _to_float_or_none(total_estimated_cost)
    tenant_id = _to_int_or_none(summary.get("tenant_id"))
    policy_version = summary.get("policy_version")
    if policy_version is None and isinstance(approval, dict):
        policy_version = approval.get("policy_version")
    return {
        "total_required_qty": round(total_required_qty, 2),
        "total_estimated_cost": None if parsed_cost is None else round(parsed_cost, 2),
        "approval": approval,
        "warnings": warnings,
        "rationale": str(summary.get("rationale") or ""),
        "escalation_required": bool(summary.get("escalation_required")),
        "tenant_id": tenant_id,
        "policy_version": policy_version,
    }


def _approval_summary_for_record(
    record: Dict[str, Any],
    snapshot: Dict[str, Any],
) -> Dict[str, Any]:
    status = _normalize_status_for_ui(record.get("status"))
    persisted_summary = _normalize_submitted_approval_summary(
        record.get("submitted_approval_summary")
    )
    if status not in {"DRAFT", "MODIFIED"} and persisted_summary:
        return persisted_summary
    return _compute_approval_summary(record, snapshot)


def _build_preview_response(payload: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, str]]:
    errors: Dict[str, str] = {}

    event_id = _parse_positive_int(payload.get("event_id"), "event_id", errors)
    warehouse_id = _parse_positive_int(payload.get("warehouse_id"), "warehouse_id", errors)

    phase = payload.get("phase")
    warnings_phase: list[str] = []
    as_of_raw = payload.get("as_of_datetime")
    as_of_dt = timezone.now()
    if as_of_raw:
        parsed = parse_datetime(as_of_raw)
        if parsed is None:
            errors["as_of_datetime"] = "Must be an ISO-8601 datetime string."
        else:
            if timezone.is_naive(parsed):
                parsed = timezone.make_aware(parsed, timezone.get_default_timezone())
            as_of_dt = parsed

    if errors:
        return {}, errors

    if not phase:
        phase = "BASELINE"
        warnings_phase.append("phase_defaulted_to_baseline")
    phase = str(phase).upper()
    if phase not in rules.PHASES:
        return {}, {"phase": "Must be SURGE, STABILIZED, or BASELINE."}

    windows = phase_window_policy.get_effective_phase_windows(int(event_id), phase)
    demand_window_hours = int(windows["demand_hours"])
    planning_window_hours = int(windows["planning_hours"])
    planning_window_days = planning_window_hours / 24

    horizon_lead_times = phase_window_policy.get_default_horizon_lead_times()
    horizon_a_hours = int(horizon_lead_times["A"]["lead_time_hours"])
    horizon_b_hours = int(horizon_lead_times["B"]["lead_time_hours"])
    horizon_c_hours = int(horizon_lead_times["C"]["lead_time_hours"])

    (
        available_by_item,
        warnings_available,
        inventory_as_of,
    ) = data_access.get_available_by_item(warehouse_id, as_of_dt)
    donations_by_item, warnings_donations = data_access.get_inbound_donations_by_item(
        warehouse_id, as_of_dt
    )
    transfers_by_item, warnings_transfers = data_access.get_inbound_transfers_by_item(
        warehouse_id, as_of_dt
    )
    if (
        STRICT_INBOUND_VIEW_MISSING_CODE in warnings_donations
        or STRICT_INBOUND_VIEW_MISSING_CODE in warnings_transfers
    ):
        return {}, {
            STRICT_INBOUND_VIEW_MISSING_CODE: (
                "Strict inbound requires database view public.v_inbound_stock. "
                "Run replenishment SQL migrations before preview/draft."
            )
        }
    burn_by_item, warnings_burn, burn_source, burn_debug = data_access.get_burn_by_item(
        event_id, warehouse_id, demand_window_hours, as_of_dt
    )
    category_burn_rates, warnings_burn_fallback, burn_fallback_debug = (
        data_access.get_category_burn_fallback_rates(event_id, warehouse_id, 30, as_of_dt)
    )

    base_warnings = (
        warnings_phase
        + warnings_available
        + warnings_donations
        + warnings_transfers
        + warnings_burn
        + warnings_burn_fallback
    )

    item_ids = needs_list.collect_item_ids(
        available_by_item, donations_by_item, transfers_by_item, burn_by_item
    )
    item_categories, warnings_categories = data_access.get_item_categories(item_ids)
    base_warnings = needs_list.merge_warnings(base_warnings, warnings_categories)

    # Fetch item names for display
    item_names, warnings_names = data_access.get_item_names(item_ids)
    base_warnings = needs_list.merge_warnings(base_warnings, warnings_names)
    effective_criticality_by_item, warnings_criticality = data_access.get_effective_criticality_by_item(
        event_id,
        item_ids,
        as_of_dt,
    )
    base_warnings = needs_list.merge_warnings(base_warnings, warnings_criticality)

    safety_factor = rules.SAFETY_STOCK_FACTOR
    items, item_warnings, fallback_counts = needs_list.build_preview_items(
        item_ids=item_ids,
        available_by_item=available_by_item,
        inbound_donations_by_item=donations_by_item,
        inbound_transfers_by_item=transfers_by_item,
        burn_by_item=burn_by_item,
        item_categories=item_categories,
        category_burn_rates=category_burn_rates,
        demand_window_hours=demand_window_hours,
        planning_window_hours=planning_window_hours,
        safety_factor=safety_factor,
        horizon_a_hours=horizon_a_hours,
        horizon_b_hours=horizon_b_hours,
        horizon_c_hours=horizon_c_hours,
        burn_source=burn_source,
        as_of_dt=as_of_dt,
        phase=phase,
        inventory_as_of=inventory_as_of,
        base_warnings=base_warnings,
        item_names=item_names,
        effective_criticality_by_item=effective_criticality_by_item,
    )

    warnings = needs_list.merge_warnings(base_warnings, item_warnings)
    _persist_stock_state_snapshot(
        event_id=event_id,
        warehouse_id=warehouse_id,
        phase=phase,
        as_of_datetime=as_of_dt.isoformat(),
        items=items,
        warnings=warnings,
    )

    restored_snapshot: Dict[str, Any] | None = None
    if _should_restore_persisted_state(items, warnings):
        restored_snapshot = _load_persisted_snapshot_for_scope(event_id, warehouse_id, phase)
        if restored_snapshot:
            restored_items = restored_snapshot.get("items")
            if isinstance(restored_items, list) and restored_items:
                items = restored_items
                warnings = needs_list.merge_warnings(
                    warnings,
                    ["stock_state_restored_from_snapshot"],
                )
                logger.info(
                    "stock_state_restored_from_snapshot",
                    extra={
                        "event_type": "READ",
                        "event_id": event_id,
                        "warehouse_id": warehouse_id,
                        "phase": phase,
                        "needs_list_id": restored_snapshot.get("restored_from_needs_list_id"),
                    },
                )

    response = {
        "as_of_datetime": (
            restored_snapshot.get("as_of_datetime", as_of_dt.isoformat())
            if restored_snapshot
            else as_of_dt.isoformat()
        ),
        "planning_window_days": planning_window_days,
        "event_id": event_id,
        "warehouse_id": warehouse_id,
        "phase": phase,
        "phase_window": windows,
        "horizon_lead_times_hours": {
            key: int(value["lead_time_hours"])
            for key, value in horizon_lead_times.items()
        },
        "freshness_summary": {
            "HIGH": sum(
                1
                for item in items
                if str((item.get("freshness") or {}).get("state") or "").strip().upper() == "HIGH"
            ),
            "MEDIUM": sum(
                1
                for item in items
                if str((item.get("freshness") or {}).get("state") or "").strip().upper() == "MEDIUM"
            ),
            "LOW": sum(
                1
                for item in items
                if str((item.get("freshness") or {}).get("state") or "").strip().upper() == "LOW"
            ),
        },
        "items": items,
        "warnings": warnings,
    }
    if settings.DEBUG:
        response["debug_summary"] = {
            "burn": burn_debug,
            "burn_fallback": {
                "category": burn_fallback_debug,
                "counts": fallback_counts,
            },
        }
    return response, {}


def _available_actions_for_record(request, record: Dict[str, Any]) -> list[str]:
    status = str(record.get("status") or "").strip().upper()
    _, permissions = resolve_roles_and_permissions(request, request.user)
    enforce_scope = _should_enforce_tenant_scope(request)
    can_write_scope = True
    if enforce_scope:
        tenant_context = _tenant_context(request)
        can_write_scope = can_access_record(tenant_context, record, write=True)
    return resolve_available_tasks(
        _NEEDS_LIST_TASK_RULES,
        status=status,
        permissions=permissions,
        can_write_scope=can_write_scope,
        context={"record": record},
    )


def _execution_needs_list_pk(record: Mapping[str, Any]) -> int | None:
    needs_list_pk = _to_int_or_none(record.get("needs_list_id"))
    if needs_list_pk is not None:
        return needs_list_pk
    needs_list_no = str(record.get("needs_list_no") or "").strip()
    if not needs_list_no:
        return None
    try:
        return int(
            NeedsList.objects.only("needs_list_id").get(needs_list_no=needs_list_no).needs_list_id
        )
    except (
        NeedsList.DoesNotExist,
        DatabaseError,
        OperationalError,
        ProgrammingError,
        ValueError,
        TypeError,
    ):
        return None


def _execution_link_for_record(record: Mapping[str, Any]) -> NeedsListExecutionLink | None:
    needs_list_pk = _execution_needs_list_pk(record)
    if needs_list_pk is None:
        return None
    try:
        return (
            NeedsListExecutionLink.objects.select_related("needs_list")
            .get(needs_list_id=needs_list_pk)
        )
    except (
        NeedsListExecutionLink.DoesNotExist,
        DatabaseError,
        OperationalError,
        ProgrammingError,
    ):
        return None


def _summarize_execution_lines(lines: list[dict[str, Any]]) -> dict[str, Any]:
    by_item_batch: dict[tuple[int, int | None], float] = {}
    total_qty = 0.0
    for line in lines:
        item_id = _to_int_or_none(line.get("item_id")) or 0
        batch_id = _to_int_or_none(line.get("batch_id"))
        qty = _to_float_or_none(line.get("quantity") or line.get("allocated_qty")) or 0.0
        total_qty += qty
        key = (item_id, batch_id)
        by_item_batch[key] = round(by_item_batch.get(key, 0.0) + qty, 4)
    return {
        "line_count": len(lines),
        "total_qty": round(total_qty, 4),
        "by_item_batch": [
            {
                "item_id": item_id,
                "batch_id": batch_id,
                "reserved_qty": qty,
            }
            for (item_id, batch_id), qty in sorted(by_item_batch.items())
        ],
    }


def _execution_payload_for_record(record: Mapping[str, Any]) -> Dict[str, Any]:
    link = _execution_link_for_record(record)
    if link is None:
        return {}

    waybill_payload = link.waybill_payload_json if isinstance(link.waybill_payload_json, dict) else {}
    payload: Dict[str, Any] = {
        "execution_status": link.execution_status,
        "reliefrqst_id": link.reliefrqst_id,
        "reliefpkg_id": link.reliefpkg_id,
        "selected_method": link.selected_method,
        "waybill_no": link.waybill_no,
        "waybill_payload": link.waybill_payload_json,
        "request_tracking_no": waybill_payload.get("request_tracking_no"),
        "package_tracking_no": waybill_payload.get("package_tracking_no"),
    }

    allocation_lines: list[dict[str, Any]] = []
    if link.reliefrqst_id and link.reliefpkg_id:
        try:
            current = allocation_dispatch.get_current_allocation(
                {
                    "needs_list_id": link.needs_list_id,
                    "reliefrqst_id": link.reliefrqst_id,
                    "reliefpkg_id": link.reliefpkg_id,
                }
            )
            payload.update(
                {
                    "request_tracking_no": current.get("request_tracking_no"),
                    "package_tracking_no": current.get("package_tracking_no"),
                    "waybill_no": payload.get("waybill_no") or current.get("waybill_no"),
                    "package_status": current.get("package_status"),
                    "dispatch_dtime": current.get("dispatch_dtime"),
                }
            )
            allocation_lines = list(current.get("allocation_lines") or [])
            payload["reserved_stock_summary"] = current.get("reserved_stock_summary") or {}
        except (
            allocation_dispatch.AllocationDispatchError,
            DatabaseError,
            OperationalError,
            ProgrammingError,
        ):
            allocation_lines = []

    if not allocation_lines:
        try:
            allocation_lines = _stored_execution_allocation_lines(link.needs_list_id)
            payload["reserved_stock_summary"] = _summarize_execution_lines(allocation_lines)
        except (DatabaseError, OperationalError, ProgrammingError):
            allocation_lines = []

    payload["allocation_lines"] = allocation_lines
    payload["linked_sources"] = [
        {
            "source_type": str(line.get("source_type") or ""),
            "source_record_id": line.get("source_record_id"),
        }
        for line in allocation_lines
        if line.get("source_type") and line.get("source_record_id") is not None
    ]
    return payload


def _allocation_context_from_record(
    record: Mapping[str, Any],
    payload: Mapping[str, Any] | None = None,
    *,
    link: NeedsListExecutionLink | None = None,
) -> Dict[str, Any]:
    data = dict(payload or {})
    needs_list_pk = _execution_needs_list_pk(record)
    return {
        "needs_list_id": needs_list_pk,
        "reliefrqst_id": getattr(link, "reliefrqst_id", None),
        "reliefpkg_id": getattr(link, "reliefpkg_id", None),
        "agency_id": data.get("agency_id"),
        "destination_warehouse_id": _to_int_or_none(record.get("warehouse_id")),
        "event_id": _to_int_or_none(record.get("event_id")),
        "submitted_by": getattr(link, "override_requested_by", None) or record.get("submitted_by"),
        "needs_list_no": record.get("needs_list_no"),
        "transport_mode": data.get("transport_mode"),
        "urgency_ind": data.get("urgency_ind"),
        "request_notes": data.get("request_notes") or data.get("rqst_notes_text"),
        "package_comments": data.get("package_comments") or data.get("comments_text"),
    }


def _release_execution_reservations(
    record: Mapping[str, Any],
    *,
    actor_user_id: str,
    reason_code: str,
    cancel: bool = False,
) -> None:
    link = _execution_link_for_record(record)
    if (
        link is None
        or link.reliefrqst_id is None
        or link.reliefpkg_id is None
        or link.execution_status not in {
            NeedsListExecutionLink.ExecutionStatus.COMMITTED,
            NeedsListExecutionLink.ExecutionStatus.PENDING_OVERRIDE_APPROVAL,
        }
    ):
        return

    allocation_dispatch.release_allocation(
        {
            "needs_list_id": link.needs_list_id,
            "reliefrqst_id": link.reliefrqst_id,
            "reliefpkg_id": link.reliefpkg_id,
        },
        actor_user_id=actor_user_id,
        reason_code=reason_code,
    )
    _upsert_execution_link(
        needs_list_id=link.needs_list_id,
        actor_user_id=actor_user_id,
        reliefrqst_id=link.reliefrqst_id,
        reliefpkg_id=link.reliefpkg_id,
        selected_method=link.selected_method,
        execution_status=(
            NeedsListExecutionLink.ExecutionStatus.CANCELLED
            if cancel
            else NeedsListExecutionLink.ExecutionStatus.PREPARING
        ),
        cancelled=cancel,
    )


def _serialize_workflow_record(
    record: Dict[str, Any],
    include_overrides: bool = True,
    *,
    include_execution_payload: bool = True,
) -> Dict[str, Any]:
    snapshot = (
        workflow_store.apply_overrides(record)
        if include_overrides
        else dict(record.get("snapshot") or {})
    )
    approval_summary = _approval_summary_for_record(record, snapshot)
    selected_method = _normalize_horizon_key(
        record.get("selected_method") or snapshot.get("selected_method")
    )
    response = dict(snapshot)
    response.update(
        {
            "needs_list_id": record.get("needs_list_id"),
            "needs_list_no": record.get("needs_list_no") or snapshot.get("needs_list_no"),
            "status": _normalize_status_for_ui(record.get("status")),
            "event_id": record.get("event_id"),
            "event_name": record.get("event_name"),
            "warehouse_id": record.get("warehouse_id"),
            "warehouse_ids": record.get("warehouse_ids"),
            "warehouses": record.get("warehouses"),
            "phase": record.get("phase"),
            "planning_window_days": record.get("planning_window_days"),
            "as_of_datetime": record.get("as_of_datetime"),
            "created_by": record.get("created_by"),
            "created_at": record.get("created_at"),
            "updated_by": record.get("updated_by"),
            "updated_at": record.get("updated_at"),
            "submitted_by": record.get("submitted_by"),
            "submitted_at": record.get("submitted_at"),
            "reviewed_by": record.get("reviewed_by"),
            "reviewed_at": record.get("reviewed_at"),
            "approved_by": record.get("approved_by"),
            "approved_at": record.get("approved_at"),
            "approval_tier": record.get("approval_tier"),
            "approval_rationale": record.get("approval_rationale"),
            "selected_method": selected_method,
            "prep_started_by": record.get("prep_started_by"),
            "prep_started_at": record.get("prep_started_at"),
            "dispatched_by": record.get("dispatched_by"),
            "dispatched_at": record.get("dispatched_at"),
            "received_by": record.get("received_by"),
            "received_at": record.get("received_at"),
            "completed_by": record.get("completed_by"),
            "completed_at": record.get("completed_at"),
            "cancelled_by": record.get("cancelled_by"),
            "cancelled_at": record.get("cancelled_at"),
            "cancel_reason": record.get("cancel_reason"),
            "escalated_by": record.get("escalated_by"),
            "escalated_at": record.get("escalated_at"),
            "escalation_reason": record.get("escalation_reason"),
            "superseded_by": record.get("superseded_by"),
            "superseded_at": record.get("superseded_at"),
            "superseded_by_actor": record.get("superseded_by_actor"),
            "superseded_by_needs_list_id": record.get("superseded_by_needs_list_id"),
            "supersedes_needs_list_ids": record.get("supersedes_needs_list_ids"),
            "supersede_reason": record.get("supersede_reason"),
            "return_reason": record.get("return_reason"),
            "return_reason_code": record.get("return_reason_code"),
            "reject_reason": record.get("reject_reason"),
            "approval_summary": approval_summary,
            "tenant_id": _record_tenant_id(record, snapshot),
        }
    )
    if include_execution_payload:
        response.update(_execution_payload_for_record(record))
    return response


def _normalize_status_for_ui(status: object) -> str:
    normalized = str(status or "").strip().upper()
    if normalized in {"PENDING", "PENDING_APPROVAL", "UNDER_REVIEW"}:
        return "SUBMITTED"
    if normalized == "RETURNED":
        return "MODIFIED"
    if normalized == "CANCELLED":
        return "REJECTED"
    if normalized in {"IN_PREPARATION", "DISPATCHED", "RECEIVED"}:
        return "IN_PROGRESS"
    if normalized == "COMPLETED":
        return "FULFILLED"
    return normalized


def _record_owned_by_actor(record: Dict[str, Any], actor: str) -> bool:
    if not actor:
        return False
    owner = _normalize_actor(record.get("created_by"))
    return bool(owner) and owner == actor


def _submission_status_requires_actor_scope(status: object) -> bool:
    return _normalize_status_for_ui(status) in _OWNER_ONLY_SUBMISSION_STATUSES


def _expand_submission_status_filters(
    statuses: list[str] | None,
) -> tuple[list[str] | None, set[str] | None]:
    if not statuses:
        return None, None

    store_filters: set[str] = set()
    ui_filters: set[str] = set()
    for status in statuses:
        raw = str(status or "").strip().upper()
        if not raw:
            continue

        ui = _normalize_status_for_ui(raw)
        ui_filters.add(ui)

        if ui == "SUBMITTED":
            store_filters.update({"PENDING_APPROVAL", "SUBMITTED", "PENDING", "UNDER_REVIEW"})
        elif ui == "IN_PROGRESS":
            store_filters.update({"IN_PROGRESS", "IN_PREPARATION", "DISPATCHED", "RECEIVED"})
        elif ui == "FULFILLED":
            store_filters.update({"FULFILLED", "COMPLETED"})
        elif ui == "MODIFIED":
            store_filters.update({"MODIFIED", "RETURNED"})
        elif ui == "REJECTED":
            store_filters.update({"REJECTED", "CANCELLED"})
        else:
            store_filters.add(raw)
            store_filters.add(ui)

    return (sorted(store_filters) if store_filters else None), (ui_filters or None)


def _item_is_fulfilled(item: Dict[str, Any], list_status: str) -> bool:
    if list_status in {"FULFILLED", "COMPLETED"}:
        return True

    fulfillment_status = str(item.get("fulfillment_status") or "").strip().upper()
    if fulfillment_status in {"FULFILLED", "RECEIVED"}:
        return True

    target_qty = _effective_line_target_qty(item)
    if target_qty <= 0:
        return True

    fulfilled_qty = max(_to_float_or_none(item.get("fulfilled_qty")) or 0.0, 0.0)
    return fulfilled_qty >= target_qty


def _effective_line_target_qty(item: Dict[str, Any]) -> float:
    """
    Return the effective requested quantity for fulfillment math.

    When overrides are applied, required_qty is updated while gap_qty remains
    the original computed shortage. Prefer required_qty so tracker/history math
    reflects what was actually submitted.
    """
    required_qty = _to_float_or_none(item.get("required_qty"))
    if required_qty is not None:
        return max(required_qty, 0.0)

    # Fallback to historical behavior for records without required_qty.
    gap_qty = max(_to_float_or_none(item.get("gap_qty")) or 0.0, 0.0)
    fulfilled_qty = max(_to_float_or_none(item.get("fulfilled_qty")) or 0.0, 0.0)
    return max(gap_qty + fulfilled_qty, 0.0)


def _line_item_ids_with_positive_target(items: object) -> set[int]:
    if not isinstance(items, list):
        return set()

    item_ids: set[int] = set()
    for raw_item in items:
        if not isinstance(raw_item, dict):
            continue
        item_id = _to_int_or_none(raw_item.get("item_id"))
        if item_id is None or item_id <= 0:
            continue
        if _effective_line_target_qty(raw_item) <= 0:
            continue
        item_ids.add(item_id)
    return item_ids


def _line_item_warehouse_pairs_with_positive_target(
    record: Dict[str, Any],
    items: object,
) -> set[tuple[int, int]]:
    if not isinstance(items, list):
        return set()

    record_warehouse_ids = _warehouse_ids_for_record(record)
    item_warehouse_ids: set[int] = set()
    for raw_item in items:
        if not isinstance(raw_item, dict):
            continue
        item_warehouse_id = _to_int_or_none(raw_item.get("warehouse_id"))
        if item_warehouse_id is not None and item_warehouse_id > 0:
            item_warehouse_ids.add(item_warehouse_id)

    warehouse_scope_ids = set(record_warehouse_ids)
    warehouse_scope_ids.update(item_warehouse_ids)

    pairs: set[tuple[int, int]] = set()
    for raw_item in items:
        if not isinstance(raw_item, dict):
            continue
        item_id = _to_int_or_none(raw_item.get("item_id"))
        if item_id is None or item_id <= 0:
            continue
        if _effective_line_target_qty(raw_item) <= 0:
            continue

        item_warehouse_id = _to_int_or_none(raw_item.get("warehouse_id"))
        if item_warehouse_id is not None and item_warehouse_id > 0:
            candidate_warehouse_ids = {item_warehouse_id}
        else:
            candidate_warehouse_ids = warehouse_scope_ids

        for warehouse_id in candidate_warehouse_ids:
            pairs.add((warehouse_id, item_id))

    return pairs


def _warehouse_ids_for_record(record: Dict[str, Any]) -> set[int]:
    warehouse_ids: set[int] = set()
    primary_warehouse_id = _to_int_or_none(record.get("warehouse_id"))
    if primary_warehouse_id is not None and primary_warehouse_id > 0:
        warehouse_ids.add(primary_warehouse_id)

    for raw_id in record.get("warehouse_ids") or []:
        parsed = _to_int_or_none(raw_id)
        if parsed is not None and parsed > 0:
            warehouse_ids.add(parsed)

    return warehouse_ids


def _find_submitted_or_approved_overlap_conflicts(
    record: Dict[str, Any],
    *,
    exclude_needs_list_id: str | None = None,
) -> list[Dict[str, Any]]:
    if not isinstance(record, dict):
        raise DuplicateConflictValidationError("Invalid needs list record payload.")

    current_snapshot = workflow_store.apply_overrides(record)
    if not isinstance(current_snapshot, dict):
        raise DuplicateConflictValidationError("Invalid current needs list snapshot payload.")
    current_pairs = _line_item_warehouse_pairs_with_positive_target(
        record,
        current_snapshot.get("items"),
    )
    if not current_pairs:
        return []

    existing_records = workflow_store.list_records(
        sorted(_DUPLICATE_GUARD_ACTIVE_STATUSES),
        allowed_warehouse_ids=sorted({warehouse_id for warehouse_id, _ in current_pairs}),
    )
    if not isinstance(existing_records, list):
        raise DuplicateConflictValidationError("Invalid existing needs list payload.")
    normalized_excluded_id = str(exclude_needs_list_id or "").strip()
    conflicts: list[Dict[str, Any]] = []
    for existing in existing_records:
        if not isinstance(existing, dict):
            raise DuplicateConflictValidationError("Invalid existing needs list record payload.")
        existing_id = str(existing.get("needs_list_id") or "").strip()
        if not existing_id:
            continue
        if normalized_excluded_id and existing_id == normalized_excluded_id:
            continue

        existing_status = str(existing.get("status") or "").strip().upper()
        if existing_status not in _DUPLICATE_GUARD_ACTIVE_STATUSES:
            continue

        existing_snapshot = workflow_store.apply_overrides(existing)
        if not isinstance(existing_snapshot, dict):
            raise DuplicateConflictValidationError("Invalid existing needs list snapshot payload.")
        existing_pairs = _line_item_warehouse_pairs_with_positive_target(
            existing,
            existing_snapshot.get("items"),
        )
        overlap_pairs = current_pairs.intersection(existing_pairs)
        if not overlap_pairs:
            continue
        overlap_item_ids = sorted({item_id for _, item_id in overlap_pairs})

        conflicts.append(
            {
                "needs_list_id": existing_id,
                "needs_list_no": existing.get("needs_list_no"),
                "status": existing_status,
                "warehouse_id": _to_int_or_none(existing.get("warehouse_id")),
                "warehouse_name": (
                    (existing.get("warehouses") or [{}])[0].get("warehouse_name")
                    if isinstance(existing.get("warehouses"), list)
                    and existing.get("warehouses")
                    and isinstance((existing.get("warehouses") or [{}])[0], dict)
                    else None
                ),
                "overlap_item_ids": overlap_item_ids,
                "overlap_count": len(overlap_item_ids),
            }
        )

    return conflicts


def _horizon_item_qty(item: Dict[str, Any], horizon_key: str) -> float:
    horizon = item.get("horizon")
    if isinstance(horizon, dict):
        bucket = horizon.get(horizon_key)
        if isinstance(bucket, dict):
            return max(_to_float_or_none(bucket.get("recommended_qty")) or 0.0, 0.0)
    return 0.0


def _normalize_horizon_key(value: object) -> str | None:
    normalized = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
    if normalized in {"A", "TRANSFER", "INTER_WAREHOUSE", "HORIZON_A"}:
        return "A"
    if normalized in {"B", "DONATION", "DONATIONS", "HORIZON_B"}:
        return "B"
    if normalized in {"C", "PROCUREMENT", "PURCHASE", "HORIZON_C"}:
        return "C"
    return None


def _resolve_item_horizon(item: Dict[str, Any], fallback_horizon: object = None) -> str:
    forced_horizon = _normalize_horizon_key(fallback_horizon)
    if forced_horizon is not None:
        return forced_horizon

    for key in ("A", "B", "C"):
        if _horizon_item_qty(item, key) > 0:
            return key
    return "A"


def _compute_horizon_summary(
    items: list[Dict[str, Any]],
    *,
    fallback_horizon: object = None,
) -> Dict[str, Dict[str, float | int]]:
    summary = {
        "horizon_a": {"count": 0, "estimated_value": 0.0},
        "horizon_b": {"count": 0, "estimated_value": 0.0},
        "horizon_c": {"count": 0, "estimated_value": 0.0},
    }
    fallback_key = _normalize_horizon_key(fallback_horizon)
    horizon_bucket_by_key = {
        "A": "horizon_a",
        "B": "horizon_b",
        "C": "horizon_c",
    }

    for item in items:
        procurement = item.get("procurement")
        procurement_data = procurement if isinstance(procurement, dict) else {}
        unit_cost = max(_to_float_or_none(procurement_data.get("est_unit_cost")) or 0.0, 0.0)
        total_cost = max(_to_float_or_none(procurement_data.get("est_total_cost")) or 0.0, 0.0)

        if fallback_key is not None:
            forced_bucket = horizon_bucket_by_key[fallback_key]
            forced_qty = _horizon_item_qty(item, fallback_key)
            if forced_qty <= 0:
                forced_qty = _effective_line_target_qty(item)
            if forced_qty <= 0:
                continue

            summary[forced_bucket]["count"] = int(summary[forced_bucket]["count"]) + 1
            if unit_cost > 0:
                summary[forced_bucket]["estimated_value"] = (
                    float(summary[forced_bucket]["estimated_value"]) + (forced_qty * unit_cost)
                )
            elif fallback_key == "C" and total_cost > 0:
                summary[forced_bucket]["estimated_value"] = (
                    float(summary[forced_bucket]["estimated_value"]) + total_cost
                )
            continue

        matched_horizon = False

        for key, bucket in (
            ("A", "horizon_a"),
            ("B", "horizon_b"),
            ("C", "horizon_c"),
        ):
            qty = _horizon_item_qty(item, key)
            if qty <= 0:
                continue

            matched_horizon = True
            summary[bucket]["count"] = int(summary[bucket]["count"]) + 1
            if unit_cost > 0:
                summary[bucket]["estimated_value"] = float(summary[bucket]["estimated_value"]) + (qty * unit_cost)
            elif key == "C" and total_cost > 0:
                # Procurement fallback is intentionally scoped to Horizon C:
                # est_total_cost comes from procurement metadata and is used only
                # when unit cost is unavailable for the C recommendation.
                summary[bucket]["estimated_value"] = float(summary[bucket]["estimated_value"]) + total_cost
        if matched_horizon or fallback_key is None:
            continue

        fallback_bucket = horizon_bucket_by_key[fallback_key]
        summary[fallback_bucket]["count"] = int(summary[fallback_bucket]["count"]) + 1
        fallback_qty = _effective_line_target_qty(item)
        if unit_cost > 0 and fallback_qty > 0:
            summary[fallback_bucket]["estimated_value"] = (
                float(summary[fallback_bucket]["estimated_value"]) + (fallback_qty * unit_cost)
            )
        elif fallback_key == "C" and total_cost > 0:
            summary[fallback_bucket]["estimated_value"] = (
                float(summary[fallback_bucket]["estimated_value"]) + total_cost
            )

    return summary


def _infer_external_source(item: Dict[str, Any]) -> tuple[str, str]:
    donation_qty = max(_to_float_or_none(item.get("inbound_donation_qty")) or 0.0, 0.0)
    transfer_qty = max(_to_float_or_none(item.get("inbound_transfer_qty")) or 0.0, 0.0)
    procurement_qty = max(_to_float_or_none(item.get("inbound_procurement_qty")) or 0.0, 0.0)

    if donation_qty > 0:
        return ("DONATION", "Inbound Donation")
    if transfer_qty > 0:
        return ("TRANSFER", "Inbound Transfer")
    if procurement_qty > 0:
        return ("PROCUREMENT", "Procurement Pipeline")
    return ("TRANSFER", "External Supply")


def _build_external_update_summary(
    items: list[Dict[str, Any]],
    updated_at: str | None,
) -> list[Dict[str, Any]]:
    updates: list[Dict[str, Any]] = []
    for item in items:
        fulfilled_qty = max(_to_float_or_none(item.get("fulfilled_qty")) or 0.0, 0.0)
        if fulfilled_qty <= 0:
            continue

        original_qty = _effective_line_target_qty(item)
        if original_qty <= 0:
            continue

        source_type, source_reference = _infer_external_source(item)
        updates.append(
            {
                "item_name": item.get("item_name") or f"Item {item.get('item_id')}",
                "original_qty": round(original_qty, 2),
                "covered_qty": round(fulfilled_qty, 2),
                "remaining_qty": round(max(original_qty - fulfilled_qty, 0.0), 2),
                "source_type": source_type,
                "source_reference": source_reference,
                "updated_at": updated_at,
            }
        )
    return updates


def _serialize_submission_summary(record: Dict[str, Any]) -> Dict[str, Any]:
    items_raw = record.get("items")
    items = [item for item in items_raw if isinstance(item, dict)] if isinstance(items_raw, list) else []
    snapshot = record.get("snapshot") if isinstance(record.get("snapshot"), dict) else {}

    list_status_raw = str(record.get("status") or "").strip().upper()
    list_status = _normalize_status_for_ui(list_status_raw)

    total_items = len(items)
    fulfilled_items = sum(1 for item in items if _item_is_fulfilled(item, list_status_raw))
    remaining_items = max(total_items - fulfilled_items, 0)

    updated_at = (
        str(record.get("updated_at") or "").strip()
        or str(record.get("approved_at") or "").strip()
        or str(record.get("submitted_at") or "").strip()
        or str(record.get("created_at") or "").strip()
        or None
    )

    warehouses = record.get("warehouses")
    warehouse_obj = warehouses[0] if isinstance(warehouses, list) and warehouses else {}
    warehouse_name = (
        str(warehouse_obj.get("warehouse_name") or "").strip()
        if isinstance(warehouse_obj, dict)
        else ""
    )
    warehouse_id = (
        _to_int_or_none(warehouse_obj.get("warehouse_id")) if isinstance(warehouse_obj, dict) else None
    )
    if warehouse_id is None:
        warehouse_id = _to_int_or_none(record.get("warehouse_id"))

    event_name = str(record.get("event_name") or "").strip()
    event_id = _to_int_or_none(record.get("event_id"))
    phase = str(record.get("phase") or "").strip().upper() or "BASELINE"
    selected_method = _normalize_horizon_key(record.get("selected_method") or snapshot.get("selected_method"))

    external_update_summary = _build_external_update_summary(items, updated_at)

    return {
        "id": str(record.get("needs_list_id") or ""),
        "reference_number": str(record.get("needs_list_no") or "N/A"),
        "warehouse": {
            "id": warehouse_id,
            "name": warehouse_name or (f"Warehouse {warehouse_id}" if warehouse_id is not None else "Unknown"),
            "code": str(warehouse_id) if warehouse_id is not None else "",
        },
        "event": {
            "id": event_id,
            "name": event_name or (f"Event {event_id}" if event_id is not None else "Unknown"),
            "phase": phase,
        },
        "selected_method": selected_method,
        "status": list_status,
        "total_items": total_items,
        "fulfilled_items": fulfilled_items,
        "remaining_items": remaining_items,
        "horizon_summary": _compute_horizon_summary(items, fallback_horizon=selected_method),
        "submitted_at": record.get("submitted_at"),
        "approved_at": record.get("approved_at"),
        "last_updated_at": updated_at,
        "superseded_by_id": (
            record.get("superseded_by_needs_list_id")
            or record.get("superseded_by")
        ),
        "supersedes_id": (
            (record.get("supersedes_needs_list_ids") or [None])[0]
            if isinstance(record.get("supersedes_needs_list_ids"), list)
            else None
        ),
        "has_external_updates": len(external_update_summary) > 0,
        "external_update_summary": external_update_summary,
        "data_version": f"{record.get('needs_list_id')}|{updated_at or ''}|{list_status}",
        "created_by": {
            "id": None,
            "name": str(record.get("created_by") or ""),
        },
    }


def _parse_iso_datetime(value: object) -> Any | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None

    default_tz = timezone.get_default_timezone()
    parsed = parse_datetime(normalized)
    if parsed is None:
        # Accept date-only values by appending midnight in default timezone context.
        parsed = parse_datetime(f"{normalized}T00:00:00")
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, default_tz)
    else:
        parsed = timezone.localtime(parsed, default_tz)
    return parsed


def _paginate_results(request, items: list[Dict[str, Any]], *, default_page_size: int = 10, max_page_size: int = 100) -> Dict[str, Any]:
    page, page_size = _parse_pagination_params(
        request,
        default_page_size=default_page_size,
        max_page_size=max_page_size,
    )
    total_count = len(items)
    start = (page - 1) * page_size
    end = start + page_size
    page_items = items[start:end] if start < total_count else []

    return _build_paginated_payload(
        request,
        items=page_items,
        total_count=total_count,
        page=page,
        page_size=page_size,
    )


def _parse_pagination_params(
    request,
    *,
    default_page_size: int = 10,
    max_page_size: int = 100,
) -> tuple[int, int]:
    errors: Dict[str, str] = {}
    raw_page = request.query_params.get("page")
    raw_page_size = request.query_params.get("page_size")
    page = (
        _parse_positive_int(raw_page, "page", errors)
        if raw_page not in (None, "")
        else 1
    )
    page_size = (
        _parse_positive_int(raw_page_size, "page_size", errors)
        if raw_page_size not in (None, "")
        else default_page_size
    )
    if errors:
        raise PaginationValidationError(errors)
    page_size = max(1, min(page_size, max_page_size))
    return page or 1, page_size


def _build_paginated_payload(
    request,
    *,
    items: list[Dict[str, Any]],
    total_count: int,
    page: int,
    page_size: int,
    result_key: str = "results",
) -> Dict[str, Any]:

    next_url = None
    prev_url = None
    query = request.query_params.copy()
    query["page_size"] = str(page_size)

    if page * page_size < total_count:
        query["page"] = str(page + 1)
        next_url = request.build_absolute_uri(
            f"{request.path}?{query.urlencode()}"
        )
    if page > 1 and total_count > 0:
        query["page"] = str(page - 1)
        prev_url = request.build_absolute_uri(
            f"{request.path}?{query.urlencode()}"
        )

    return {
        "count": total_count,
        "next": next_url,
        "previous": prev_url,
        result_key: items,
    }


def _workflow_disabled_response() -> Response:
    return Response(
        {"errors": {"workflow": "DB-backed needs-list workflow is unavailable."}},
        status=501,
    )


@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPreviewPermission])
def needs_list_list(request):
    """
    List needs lists, optionally filtered by query params.
    Query params:
        status - comma-separated list of statuses (e.g. DRAFT,SUBMITTED,APPROVED)
        mine - when true, only records created by current actor
        include_closed - when false, excludes terminal statuses
        event_id - optional positive integer event scope
        warehouse_id - optional positive integer warehouse scope
        phase - optional phase filter (SURGE, STABILIZED, BASELINE)
    """
    try:
        workflow_store.store_enabled_or_raise()
    except RuntimeError:
        return _workflow_disabled_response()

    status_param = request.query_params.get("status")
    statuses = [s.strip() for s in status_param.split(",") if s.strip()] if status_param else None
    mine_only = _query_param_truthy(request.query_params.get("mine"), default=False)
    include_closed = _query_param_truthy(
        request.query_params.get("include_closed"), default=True
    )

    errors: Dict[str, str] = {}
    event_id_filter = _parse_positive_int(
        request.query_params.get("event_id"), "event_id", errors
    ) if request.query_params.get("event_id") is not None else None
    warehouse_id_filter = _parse_positive_int(
        request.query_params.get("warehouse_id"), "warehouse_id", errors
    ) if request.query_params.get("warehouse_id") is not None else None
    phase_raw = request.query_params.get("phase")
    phase_filter = str(phase_raw or "").strip().upper() or None
    if phase_filter and phase_filter not in rules.PHASES:
        errors["phase"] = "Must be SURGE, STABILIZED, or BASELINE."
    if errors:
        return Response({"errors": errors}, status=400)

    actor = _normalize_actor(_actor_id(request))
    if mine_only and not actor:
        return Response({"needs_lists": [], "count": 0})
    scoped_warehouse_ids = _accessible_read_warehouse_ids(request)
    record_ids = [
        row.get("needs_list_id")
        for row in workflow_store.list_record_headers(
            statuses,
            mine_actor=actor if mine_only else None,
            event_id=event_id_filter,
            warehouse_id=warehouse_id_filter,
            phase=phase_filter,
            exclude_statuses=_CLOSED_NEEDS_LIST_STATUSES if not include_closed else None,
            allowed_warehouse_ids=scoped_warehouse_ids,
        )
    ]
    scoped_base_queryset = (
        NeedsList.objects.filter(warehouse_id__in=sorted(set(scoped_warehouse_ids)))
        if scoped_warehouse_ids is not None
        else NeedsList.objects.all()
    )
    records = workflow_store.get_records_by_ids(
        record_ids,
        base_queryset=scoped_base_queryset,
        include_audit_logs=False,
    )
    tenant_context = _tenant_context(request)
    enforce_tenant_scope = _should_enforce_tenant_scope(request)
    filtered_records: list[Dict[str, Any]] = []
    for record in records:
        if enforce_tenant_scope and not can_access_record(tenant_context, record, write=False):
            continue
        filtered_records.append(record)

    serialized = []
    for record in filtered_records:
        row = _serialize_workflow_record(record, include_execution_payload=False)
        row["allowed_actions"] = _available_actions_for_record(request, record)
        serialized.append(row)
    if mine_only:
        serialized.sort(key=_record_sort_timestamp, reverse=True)
    else:
        # Sort by submitted_at ascending (oldest first), nulls last.
        serialized.sort(key=lambda r: r.get("submitted_at") or "9999")

    return Response({"needs_lists": serialized, "count": len(serialized)})


@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPreviewPermission])
def needs_list_my_submissions(request):
    """
    Paginated, filterable summaries of needs list submissions.

    Visibility rules:
    - DRAFT/MODIFIED records remain owner-only.
    - Submitted-and-beyond records are visible to all authorized users.
    - mine=true forces owner-only filtering for all statuses.
    """
    try:
        workflow_store.store_enabled_or_raise()
    except RuntimeError:
        return _workflow_disabled_response()

    actor = _normalize_actor(_actor_id(request))
    mine_only = _query_param_truthy(request.query_params.get("mine"), default=False)
    if mine_only and not actor:
        return Response({"count": 0, "next": None, "previous": None, "results": []})

    status_param = request.query_params.get("status")
    requested_statuses = [s.strip() for s in str(status_param or "").split(",") if s.strip()] or None
    store_status_filters, ui_status_filters = _expand_submission_status_filters(
        requested_statuses
    )
    event_id_filter = _to_int_or_none(request.query_params.get("event_id"))
    warehouse_id_filter = _to_int_or_none(request.query_params.get("warehouse_id"))
    method_filter_raw = str(request.query_params.get("method") or "").strip().upper()
    method_filter = _normalize_horizon_key(method_filter_raw) if method_filter_raw else None
    if method_filter_raw and method_filter is None:
        return Response({"errors": {"method": "Must be one of: A, B, C."}}, status=400)
    date_from_raw = request.query_params.get("date_from")
    date_to_raw = request.query_params.get("date_to")
    date_from = _parse_iso_datetime(date_from_raw)
    date_to = _parse_iso_datetime(date_to_raw)
    if (
        date_to is not None
        and isinstance(date_to_raw, str)
        and re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_to_raw.strip())
    ):
        # Treat day-only end filters as inclusive through end-of-day.
        date_to = date_to + timedelta(days=1) - timedelta(microseconds=1)

    sort_by = str(request.query_params.get("sort_by") or "date").strip().lower()
    sort_order = str(request.query_params.get("sort_order") or "desc").strip().lower()
    if sort_by not in {"date", "status", "warehouse"}:
        return Response({"errors": {"sort_by": "Must be one of: date, status, warehouse."}}, status=400)
    if sort_order not in {"asc", "desc"}:
        return Response({"errors": {"sort_order": "Must be asc or desc."}}, status=400)

    # Terminal statuses hidden by default unless explicitly requested via filter.
    _DEFAULT_EXCLUDED_STATUSES = _CLOSED_NEEDS_LIST_STATUSES
    try:
        page, page_size = _parse_pagination_params(request)
    except PaginationValidationError as exc:
        return Response({"errors": exc.errors}, status=400)
    scoped_warehouse_ids = _accessible_read_warehouse_ids(request)
    headers, total_count = workflow_store.list_record_headers_page(
        store_status_filters,
        mine_actor=actor if mine_only else None,
        owner_visibility_actor=None if mine_only else actor,
        owner_visibility_statuses=_OWNER_ONLY_SUBMISSION_STATUSES,
        event_id=event_id_filter,
        warehouse_id=warehouse_id_filter,
        exclude_statuses=None if ui_status_filters else _DEFAULT_EXCLUDED_STATUSES,
        allowed_warehouse_ids=scoped_warehouse_ids,
        date_from=date_from,
        date_to=date_to,
        sort_by=sort_by,
        sort_order=sort_order,
        method_filter=method_filter,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    page_ids = [row.get("needs_list_id") for row in headers]
    scoped_base_queryset = (
        NeedsList.objects.filter(warehouse_id__in=sorted(set(scoped_warehouse_ids)))
        if scoped_warehouse_ids is not None
        else NeedsList.objects.all()
    )
    page_records = workflow_store.get_records_by_ids(
        page_ids,
        base_queryset=scoped_base_queryset,
        include_audit_logs=False,
    )
    tenant_context = _tenant_context(request)
    enforce_tenant_scope = _should_enforce_tenant_scope(request)
    records_by_id = {
        str(record.get("needs_list_id")): record
        for record in page_records
    }
    summaries: list[Dict[str, Any]] = []
    for header in headers:
        record = records_by_id.get(str(header.get("needs_list_id")))
        if not record:
            continue
        if enforce_tenant_scope and not can_access_record(tenant_context, record, write=False):
            continue
        serialized = _serialize_workflow_record(
            record,
            include_overrides=True,
            include_execution_payload=False,
        )
        summary = _serialize_submission_summary(serialized)
        summary["allowed_actions"] = _available_actions_for_record(request, record)
        summaries.append(summary)

    return Response(
        _build_paginated_payload(
            request,
            items=summaries,
            total_count=total_count,
            page=page,
            page_size=page_size,
        )
    )


@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPreviewPermission])
def needs_list_summary_version(_request, needs_list_id: str):
    try:
        workflow_store.store_enabled_or_raise()
    except RuntimeError:
        return _workflow_disabled_response()

    record = workflow_store.get_record(needs_list_id)
    if not record:
        return Response({"errors": {"needs_list_id": "Not found."}}, status=404)
    scope_error = _require_record_scope(_request, record, write=False)
    if scope_error:
        return scope_error

    serialized = _serialize_workflow_record(record, include_overrides=False)
    normalized_status = _normalize_status_for_ui(serialized.get("status"))
    updated_at = (
        serialized.get("updated_at")
        or serialized.get("approved_at")
        or serialized.get("submitted_at")
        or serialized.get("created_at")
    )
    return Response(
        {
            "needs_list_id": str(serialized.get("needs_list_id") or needs_list_id),
            "status": normalized_status,
            "last_updated_at": updated_at,
            "data_version": f"{serialized.get('needs_list_id')}|{updated_at or ''}|{normalized_status}",
        }
    )


@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPreviewPermission])
def needs_list_fulfillment_sources(_request, needs_list_id: str):
    try:
        workflow_store.store_enabled_or_raise()
    except RuntimeError:
        return _workflow_disabled_response()

    record = workflow_store.get_record(needs_list_id)
    if not record:
        return Response({"errors": {"needs_list_id": "Not found."}}, status=404)
    scope_error = _require_record_scope(_request, record, write=False)
    if scope_error:
        return scope_error

    serialized = _serialize_workflow_record(record, include_overrides=True)
    list_status = str(serialized.get("status") or "").strip().upper()
    selected_method = _normalize_horizon_key(serialized.get("selected_method"))
    updated_at = serialized.get("updated_at")
    lines: list[Dict[str, Any]] = []

    for raw_item in serialized.get("items") or []:
        if not isinstance(raw_item, dict):
            continue

        item_id = _to_int_or_none(raw_item.get("item_id"))
        target_qty = _effective_line_target_qty(raw_item)
        fulfilled_qty = max(_to_float_or_none(raw_item.get("fulfilled_qty")) or 0.0, 0.0)
        original_qty = round(target_qty, 2)
        remaining_qty = 0.0 if _item_is_fulfilled(raw_item, list_status) else round(max(original_qty - fulfilled_qty, 0.0), 2)

        donation_qty = max(_to_float_or_none(raw_item.get("inbound_donation_qty")) or 0.0, 0.0)
        transfer_qty = max(_to_float_or_none(raw_item.get("inbound_transfer_qty")) or 0.0, 0.0)
        procurement_qty = max(_to_float_or_none(raw_item.get("inbound_procurement_qty")) or 0.0, 0.0)

        sources: list[Dict[str, Any]] = []
        if donation_qty > 0:
            sources.append(
                {
                    "source_type": "DONATION",
                    "source_id": None,
                    "source_reference": "Inbound Donation",
                    "quantity": round(donation_qty, 2),
                    "status": "RECEIVED",
                    "date": updated_at,
                }
            )
        if transfer_qty > 0:
            sources.append(
                {
                    "source_type": "TRANSFER",
                    "source_id": None,
                    "source_reference": "Inbound Transfer",
                    "quantity": round(transfer_qty, 2),
                    "status": "DISPATCHED",
                    "date": updated_at,
                }
            )
        if procurement_qty > 0:
            sources.append(
                {
                    "source_type": "PROCUREMENT",
                    "source_id": None,
                    "source_reference": "Procurement Pipeline",
                    "quantity": round(procurement_qty, 2),
                    "status": "DRAFT",
                    "date": None,
                }
            )

        if remaining_qty > 0:
            sources.append(
                {
                    "source_type": "NEEDS_LIST_LINE",
                    "source_id": item_id,
                    "source_reference": f"{serialized.get('needs_list_no') or 'N/A'} (This needs list)",
                    "quantity": round(remaining_qty, 2),
                    "status": _normalize_status_for_ui(serialized.get("status")),
                    "date": None,
                }
            )

        total_coverage = round(sum(_to_float_or_none(source.get("quantity")) or 0.0 for source in sources), 2)
        lines.append(
            {
                "id": item_id,
                "item": {
                    "id": item_id,
                    "name": raw_item.get("item_name") or (f"Item {item_id}" if item_id is not None else "Item"),
                    "uom": raw_item.get("uom_code") or "EA",
                },
                "original_qty": original_qty,
                "covered_qty": round(fulfilled_qty, 2),
                "remaining_qty": round(max(remaining_qty, 0.0), 2),
                "horizon": _resolve_item_horizon(raw_item, selected_method),
                "fulfillment_sources": sources,
                "total_coverage": total_coverage,
                "is_fully_covered": remaining_qty <= 0,
            }
        )

    return Response({"needs_list_id": str(serialized.get("needs_list_id") or needs_list_id), "lines": lines})


def _parse_bulk_ids(raw_ids: Any) -> tuple[list[str], Dict[str, str] | None]:
    if not isinstance(raw_ids, list):
        return ([], {"ids": "Expected an array of needs list IDs."})

    parsed_ids: list[str] = []
    seen: set[str] = set()
    if not raw_ids:
        return ([], {"ids": "At least one ID is required."})
    for raw_id in raw_ids:
        value = str(raw_id or "").strip()
        if not value:
            return ([], {"ids": "Each ID must be a non-empty string or number."})
        if value in seen:
            continue
        seen.add(value)
        parsed_ids.append(value)
    return (parsed_ids, None)


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPermission])
def needs_list_bulk_submit(request):
    try:
        workflow_store.store_enabled_or_raise()
    except RuntimeError:
        return _workflow_disabled_response()

    ids, parse_error = _parse_bulk_ids((request.data or {}).get("ids"))
    if parse_error:
        return Response({"errors": parse_error}, status=400)

    submitted_ids: list[str] = []
    errors: list[Dict[str, str]] = []
    actor = _actor_id(request)
    target_status = _workflow_target_status("SUBMITTED")
    for needs_list_id in ids:
        record = workflow_store.get_record(needs_list_id)
        if not record:
            errors.append({"id": needs_list_id, "error": "Not found."})
            continue
        if _require_record_scope(request, record, write=True):
            errors.append({"id": needs_list_id, "error": "Access denied for tenant scope."})
            continue

        previous_status = str(record.get("status") or "").upper()
        if not _status_matches(previous_status, "DRAFT", "MODIFIED", include_db_transitions=True):
            errors.append({"id": needs_list_id, "error": "Only draft or modified needs lists can be submitted."})
            continue

        item_count = len(record.get("snapshot", {}).get("items") or [])
        if item_count == 0:
            errors.append({"id": needs_list_id, "error": "Cannot submit an empty needs list."})
            continue

        try:
            duplicate_conflicts = _find_submitted_or_approved_overlap_conflicts(
                record,
                exclude_needs_list_id=needs_list_id,
            )
        except DuplicateConflictValidationError:
            logger.warning(
                "needs_list_duplicate_validation_failed",
                extra={
                    "event_type": "VALIDATION_ERROR",
                    "needs_list_id": needs_list_id,
                    "actor": actor,
                    "status": record.get("status") if isinstance(record, dict) else None,
                    "event_id": record.get("event_id") if isinstance(record, dict) else None,
                    "phase": record.get("phase") if isinstance(record, dict) else None,
                    "warehouse_id": record.get("warehouse_id") if isinstance(record, dict) else None,
                },
            )
            errors.append(
                {
                    "id": needs_list_id,
                    "error": "Failed to validate duplicate needs lists. Please retry.",
                }
            )
            continue
        if duplicate_conflicts:
            errors.append(
                {
                    "id": needs_list_id,
                    "error": (
                        "A submitted or approved needs list already exists for one or more "
                        "of these items in the same warehouse."
                    ),
                }
            )
            continue

        updated_record = workflow_store.transition_status(
            record,
            target_status,
            actor,
        )
        updated_record["submitted_approval_summary"] = _compute_approval_summary(
            updated_record,
            workflow_store.apply_overrides(updated_record),
        )
        workflow_store.update_record(needs_list_id, updated_record)
        logger.info(
            "needs_list_submitted",
            extra={
                "event_type": "STATE_CHANGE",
                "user_id": getattr(request.user, "user_id", None),
                "username": getattr(request.user, "username", None),
                "needs_list_id": needs_list_id,
                "from_status": previous_status,
                "to_status": target_status,
                "item_count": item_count,
            },
        )
        submitted_ids.append(needs_list_id)

    return Response({"submitted_ids": submitted_ids, "errors": errors, "count": len(submitted_ids)})


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPermission])
def needs_list_bulk_delete(request):
    try:
        workflow_store.store_enabled_or_raise()
    except RuntimeError:
        return _workflow_disabled_response()

    ids, parse_error = _parse_bulk_ids((request.data or {}).get("ids"))
    if parse_error:
        return Response({"errors": parse_error}, status=400)

    cancelled_ids: list[str] = []
    errors: list[Dict[str, str]] = []
    actor = _actor_id(request)
    reason = str((request.data or {}).get("reason") or "Removed from My Submissions.").strip()
    for needs_list_id in ids:
        record = workflow_store.get_record(needs_list_id)
        if not record:
            errors.append({"id": needs_list_id, "error": "Not found."})
            continue
        if _require_record_scope(request, record, write=True):
            errors.append({"id": needs_list_id, "error": "Access denied for tenant scope."})
            continue

        status = str(record.get("status") or "").upper()
        if not _status_matches(status, "DRAFT", "MODIFIED", include_db_transitions=True):
            errors.append({"id": needs_list_id, "error": "Only draft or modified needs lists can be removed."})
            continue

        updated_record = workflow_store.transition_status(
            record,
            "CANCELLED",
            actor,
            reason=reason,
        )
        target_status = _workflow_target_status("CANCELLED")
        workflow_store.update_record(needs_list_id, updated_record)
        logger.info(
            "needs_list_cancelled",
            extra={
                "event_type": "STATE_CHANGE",
                "user_id": getattr(request.user, "user_id", None),
                "username": getattr(request.user, "username", None),
                "needs_list_id": needs_list_id,
                "from_status": status,
                "to_status": target_status,
                "reason": reason,
            },
        )
        cancelled_ids.append(needs_list_id)

    return Response({"cancelled_ids": cancelled_ids, "errors": errors, "count": len(cancelled_ids)})


@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPreviewPermission])
def get_active_event(request):
    """
    Get the most recent active event.
    Returns event details including event_id, event_name, status, phase, and declaration_date.
    Returns null if no active event found (200 status, not 404).
    """
    event = data_access.get_active_event()

    if not event:
        # Return 200 with null instead of 404, so frontend can show empty state
        logger.info(
            "get_active_event_none",
            extra={
                "event_type": "READ",
                "user_id": getattr(request.user, "user_id", None),
                "username": getattr(request.user, "username", None),
                "message": "No active event found",
            },
        )
        return Response(None, status=200)

    logger.info(
        "get_active_event",
        extra={
            "event_type": "READ",
            "user_id": getattr(request.user, "user_id", None),
            "username": getattr(request.user, "username", None),
            "event_id": event.get("event_id"),
        },
    )

    return Response(event)


@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPreviewPermission])
def get_all_warehouses(request):
    """
    Get all active warehouses.
    Returns list of warehouses with warehouse_id and warehouse_name.
    """
    warehouses = data_access.get_all_warehouses()
    tenant_context = _tenant_context(request)
    if _should_enforce_tenant_scope(request):
        warehouses = [
            warehouse
            for warehouse in warehouses
            if can_access_warehouse(
                tenant_context,
                _to_int_or_none(warehouse.get("warehouse_id") if isinstance(warehouse, dict) else None),
                write=False,
            )
        ]

    logger.info(
        "get_all_warehouses",
        extra={
            "event_type": "READ",
            "user_id": getattr(request.user, "user_id", None),
            "username": getattr(request.user, "username", None),
            "warehouse_count": len(warehouses),
        },
    )

    return Response({"warehouses": warehouses, "count": len(warehouses)})


@api_view(["GET", "POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPermission])
def criticality_event_overrides(request):
    if request.method == "GET":
        errors: Dict[str, str] = {}
        event_id = _parse_positive_int(request.query_params.get("event_id"), "event_id", errors) if request.query_params.get("event_id") else None
        item_id = _parse_positive_int(request.query_params.get("item_id"), "item_id", errors) if request.query_params.get("item_id") else None
        active_only = _parse_optional_bool(request.query_params.get("active_only"), "active_only", errors)
        if active_only is None:
            active_only = False
        limit = _parse_positive_int(request.query_params.get("limit"), "limit", errors) if request.query_params.get("limit") else 200
        if errors:
            return Response({"errors": errors}, status=400)

        rows, warnings = criticality_governance.list_event_overrides(
            event_id=event_id,
            item_id=item_id,
            active_only=active_only,
            limit=limit or 200,
        )
        return Response({"results": rows, "count": len(rows), "warnings": warnings})

    payload = request.data if isinstance(request.data, Mapping) else {}
    errors: Dict[str, str] = {}
    event_id = _parse_positive_int(payload.get("event_id"), "event_id", errors)
    item_id = _parse_positive_int(payload.get("item_id"), "item_id", errors)
    level = str(payload.get("criticality_level") or "").strip().upper()
    if level not in {"CRITICAL", "HIGH", "NORMAL", "LOW"}:
        errors["criticality_level"] = "Must be one of: CRITICAL, HIGH, NORMAL, LOW."
    is_active = _parse_optional_bool(payload.get("is_active"), "is_active", errors)
    if is_active is None:
        is_active = True
    effective_from = _parse_optional_datetime(payload.get("effective_from"), "effective_from", errors)
    effective_to = _parse_optional_datetime(payload.get("effective_to"), "effective_to", errors)
    if errors:
        return Response({"errors": errors}, status=400)

    assert event_id is not None
    assert item_id is not None
    actor_id = _actor_id(request) or "SYSTEM"
    created, warnings = criticality_governance.create_event_override(
        event_id=event_id,
        item_id=item_id,
        criticality_level=level,
        actor_id=actor_id,
        reason_text=payload.get("reason_text"),
        effective_from=effective_from,
        effective_to=effective_to,
        is_active=is_active,
    )
    if created is None:
        status_code = 409 if "event_closed_override_not_allowed" in warnings else 400
        return Response({"errors": {"criticality": warnings or ["criticality_event_override_create_failed"]}}, status=status_code)

    _log_audit_event(
        "criticality_event_override_create",
        request,
        event_type="CREATE",
        action="CRITICALITY_EVENT_OVERRIDE_CREATE",
        event_id=event_id,
        item_id=item_id,
        override_id=created.get("override_id"),
        criticality_level=created.get("criticality_level"),
    )
    return Response({"override": created, "warnings": warnings}, status=201)


@api_view(["PATCH", "DELETE"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPermission])
def criticality_event_override_detail(request, override_id: int):
    if request.method == "DELETE":
        updated, warnings = criticality_governance.update_event_override(
            override_id=override_id,
            updates={"is_active": False, "effective_to": timezone.now()},
            actor_id=_actor_id(request) or "SYSTEM",
        )
        if updated is None:
            status_code = 404 if "criticality_event_override_not_found" in warnings else 400
            return Response({"errors": {"criticality": warnings}}, status=status_code)
        _log_audit_event(
            "criticality_event_override_deactivate",
            request,
            event_type="UPDATE",
            action="CRITICALITY_EVENT_OVERRIDE_DEACTIVATE",
            override_id=override_id,
        )
        return Response({"override": updated, "warnings": warnings})

    payload = request.data if isinstance(request.data, Mapping) else {}
    errors: Dict[str, str] = {}
    updates: Dict[str, object] = {}

    if "criticality_level" in payload:
        level = str(payload.get("criticality_level") or "").strip().upper()
        if level not in {"CRITICAL", "HIGH", "NORMAL", "LOW"}:
            errors["criticality_level"] = "Must be one of: CRITICAL, HIGH, NORMAL, LOW."
        else:
            updates["criticality_level"] = level
    if "reason_text" in payload:
        updates["reason_text"] = payload.get("reason_text")
    if "effective_from" in payload:
        updates["effective_from"] = _parse_optional_datetime(payload.get("effective_from"), "effective_from", errors)
    if "effective_to" in payload:
        updates["effective_to"] = _parse_optional_datetime(payload.get("effective_to"), "effective_to", errors)
    if "is_active" in payload:
        parsed_active = _parse_optional_bool(payload.get("is_active"), "is_active", errors)
        if parsed_active is not None:
            updates["is_active"] = parsed_active

    if not updates and not errors:
        errors["updates"] = "At least one field is required."
    if errors:
        return Response({"errors": errors}, status=400)

    updated, warnings = criticality_governance.update_event_override(
        override_id=override_id,
        updates=updates,
        actor_id=_actor_id(request) or "SYSTEM",
    )
    if updated is None:
        status_code = 404 if "criticality_event_override_not_found" in warnings else 409 if "event_closed_override_not_allowed" in warnings else 400
        return Response({"errors": {"criticality": warnings}}, status=status_code)

    _log_audit_event(
        "criticality_event_override_update",
        request,
        event_type="UPDATE",
        action="CRITICALITY_EVENT_OVERRIDE_UPDATE",
        override_id=override_id,
    )
    return Response({"override": updated, "warnings": warnings})


@api_view(["GET", "POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPermission])
def criticality_hazard_defaults(request):
    if request.method == "GET":
        errors: Dict[str, str] = {}
        item_id = _parse_positive_int(request.query_params.get("item_id"), "item_id", errors) if request.query_params.get("item_id") else None
        active_only = _parse_optional_bool(request.query_params.get("active_only"), "active_only", errors)
        if active_only is None:
            active_only = False
        limit = _parse_positive_int(request.query_params.get("limit"), "limit", errors) if request.query_params.get("limit") else 200
        event_type = request.query_params.get("event_type")
        approval_status = request.query_params.get("approval_status")
        if errors:
            return Response({"errors": errors}, status=400)

        rows, warnings = criticality_governance.list_hazard_defaults(
            event_type=event_type,
            item_id=item_id,
            approval_status=approval_status,
            active_only=active_only,
            limit=limit or 200,
        )
        return Response({"results": rows, "count": len(rows), "warnings": warnings})

    payload = request.data if isinstance(request.data, Mapping) else {}
    errors: Dict[str, str] = {}
    item_id = _parse_positive_int(payload.get("item_id"), "item_id", errors)
    event_type = str(payload.get("event_type") or "").strip().upper()
    if not event_type:
        errors["event_type"] = "This field is required."
    level = str(payload.get("criticality_level") or "").strip().upper()
    if level not in {"CRITICAL", "HIGH", "NORMAL", "LOW"}:
        errors["criticality_level"] = "Must be one of: CRITICAL, HIGH, NORMAL, LOW."
    is_active = _parse_optional_bool(payload.get("is_active"), "is_active", errors)
    if is_active is None:
        is_active = True
    submit_for_approval = _parse_optional_bool(payload.get("submit_for_approval"), "submit_for_approval", errors)
    if submit_for_approval is None:
        submit_for_approval = False
    effective_from = _parse_optional_datetime(payload.get("effective_from"), "effective_from", errors)
    effective_to = _parse_optional_datetime(payload.get("effective_to"), "effective_to", errors)
    if errors:
        return Response({"errors": errors}, status=400)

    assert item_id is not None
    created, warnings = criticality_governance.create_hazard_default(
        event_type=event_type,
        item_id=item_id,
        criticality_level=level,
        actor_id=_actor_id(request) or "SYSTEM",
        reason_text=payload.get("reason_text"),
        effective_from=effective_from,
        effective_to=effective_to,
        is_active=is_active,
        approval_status="PENDING_APPROVAL" if submit_for_approval else "DRAFT",
    )
    if created is None:
        return Response({"errors": {"criticality": warnings or ["criticality_hazard_default_create_failed"]}}, status=400)

    _log_audit_event(
        "criticality_hazard_default_create",
        request,
        event_type="CREATE",
        action="CRITICALITY_HAZARD_DEFAULT_CREATE",
        hazard_event_type=event_type,
        item_id=item_id,
        hazard_item_criticality_id=created.get("hazard_item_criticality_id"),
        approval_status=created.get("approval_status"),
    )
    return Response({"hazard_default": created, "warnings": warnings}, status=201)


@api_view(["PATCH"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPermission])
def criticality_hazard_default_detail(request, hazard_item_criticality_id: int):
    payload = request.data if isinstance(request.data, Mapping) else {}
    errors: Dict[str, str] = {}
    updates: Dict[str, object] = {}

    if "event_type" in payload:
        updates["event_type"] = payload.get("event_type")
    if "item_id" in payload:
        parsed_item_id = _parse_positive_int(payload.get("item_id"), "item_id", errors)
        if parsed_item_id is not None:
            updates["item_id"] = parsed_item_id
    if "criticality_level" in payload:
        level = str(payload.get("criticality_level") or "").strip().upper()
        if level not in {"CRITICAL", "HIGH", "NORMAL", "LOW"}:
            errors["criticality_level"] = "Must be one of: CRITICAL, HIGH, NORMAL, LOW."
        else:
            updates["criticality_level"] = level
    if "reason_text" in payload:
        updates["reason_text"] = payload.get("reason_text")
    if "effective_from" in payload:
        updates["effective_from"] = _parse_optional_datetime(payload.get("effective_from"), "effective_from", errors)
    if "effective_to" in payload:
        updates["effective_to"] = _parse_optional_datetime(payload.get("effective_to"), "effective_to", errors)
    if "is_active" in payload:
        parsed_active = _parse_optional_bool(payload.get("is_active"), "is_active", errors)
        if parsed_active is not None:
            updates["is_active"] = parsed_active

    if not updates and not errors:
        errors["updates"] = "At least one field is required."
    if errors:
        return Response({"errors": errors}, status=400)

    updated, warnings = criticality_governance.update_hazard_default(
        hazard_item_criticality_id=hazard_item_criticality_id,
        updates=updates,
        actor_id=_actor_id(request) or "SYSTEM",
    )
    if updated is None:
        status_code = 404 if "criticality_hazard_default_not_found" in warnings else 400
        return Response({"errors": {"criticality": warnings}}, status=status_code)

    _log_audit_event(
        "criticality_hazard_default_update",
        request,
        event_type="UPDATE",
        action="CRITICALITY_HAZARD_DEFAULT_UPDATE",
        hazard_item_criticality_id=hazard_item_criticality_id,
        approval_status=updated.get("approval_status"),
    )
    return Response({"hazard_default": updated, "warnings": warnings})


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPermission])
def criticality_hazard_default_submit(request, hazard_item_criticality_id: int):
    submitted, warnings = criticality_governance.submit_hazard_default(
        hazard_item_criticality_id=hazard_item_criticality_id,
        actor_id=_actor_id(request) or "SYSTEM",
    )
    if submitted is None:
        status_code = 404 if any("missing" in warning for warning in warnings) else 409
        return Response({"errors": {"criticality": warnings}}, status=status_code)

    _log_audit_event(
        "criticality_hazard_default_submit",
        request,
        event_type="STATE_CHANGE",
        action="CRITICALITY_HAZARD_DEFAULT_SUBMIT",
        hazard_item_criticality_id=hazard_item_criticality_id,
    )
    return Response({"hazard_default": submitted, "warnings": warnings})


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPermission])
def criticality_hazard_default_approve(request, hazard_item_criticality_id: int):
    if not _has_director_peod_authority(request):
        return Response({"errors": {"approval": "Director PEOD approval is required."}}, status=403)

    approved, warnings = criticality_governance.approve_hazard_default(
        hazard_item_criticality_id=hazard_item_criticality_id,
        actor_id=_actor_id(request) or "SYSTEM",
    )
    if approved is None:
        status_code = 404 if any("missing" in warning for warning in warnings) else 409
        return Response({"errors": {"criticality": warnings}}, status=status_code)

    _log_audit_event(
        "criticality_hazard_default_approve",
        request,
        event_type="STATE_CHANGE",
        action="CRITICALITY_HAZARD_DEFAULT_APPROVE",
        hazard_item_criticality_id=hazard_item_criticality_id,
    )
    return Response({"hazard_default": approved, "warnings": warnings})


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPermission])
def criticality_hazard_default_reject(request, hazard_item_criticality_id: int):
    if not _has_director_peod_authority(request):
        return Response({"errors": {"approval": "Director PEOD approval is required."}}, status=403)

    payload = request.data if isinstance(request.data, Mapping) else {}
    reason_text = payload.get("reason_text")
    rejected, warnings = criticality_governance.reject_hazard_default(
        hazard_item_criticality_id=hazard_item_criticality_id,
        actor_id=_actor_id(request) or "SYSTEM",
        reason_text=reason_text,
    )
    if rejected is None:
        if "criticality_hazard_default_reject_reason_required" in warnings:
            return Response({"errors": {"reason_text": "Rejection reason is required."}}, status=400)
        status_code = 404 if any("missing" in warning for warning in warnings) else 409
        return Response({"errors": {"criticality": warnings}}, status=status_code)

    _log_audit_event(
        "criticality_hazard_default_reject",
        request,
        event_type="STATE_CHANGE",
        action="CRITICALITY_HAZARD_DEFAULT_REJECT",
        hazard_item_criticality_id=hazard_item_criticality_id,
    )
    return Response({"hazard_default": rejected, "warnings": warnings})


@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPermission])
def storage_assignment_options(request):
    errors: Dict[str, str] = {}
    item_id = _parse_positive_int(request.query_params.get("item_id"), "item_id", errors)
    if errors:
        return Response({"errors": errors}, status=400)

    assert item_id is not None

    try:
        result = location_storage.get_storage_assignment_options(item_id=item_id)
    except location_storage.LocationAssignmentError as exc:
        return Response(
            {"detail": exc.message, "errors": {exc.code: exc.message}},
            status=exc.status_code,
        )

    if _should_enforce_tenant_scope(request):
        tenant_context = _tenant_context(request)
        inventories = list(result.get("inventories") or [])
        allowed_inventory_ids = {
            parsed_inventory_id
            for option in inventories
            for parsed_inventory_id in [_to_int_or_none(option.get("value"))]
            if parsed_inventory_id is not None
            and can_access_warehouse(tenant_context, parsed_inventory_id, write=False)
        }
        if inventories and not allowed_inventory_ids:
            return _tenant_scope_denied_response(request, write=False)

        def _belongs_to_allowed_inventory(option: Mapping[str, Any]) -> bool:
            inventory_id = _to_int_or_none(option.get("inventory_id"))
            return inventory_id is not None and inventory_id in allowed_inventory_ids

        result = {
            **result,
            "inventories": [
                option
                for option in inventories
                if _to_int_or_none(option.get("value")) in allowed_inventory_ids
            ],
            "locations": [
                option
                for option in list(result.get("locations") or [])
                if _belongs_to_allowed_inventory(option)
            ],
            "batches": [
                option
                for option in list(result.get("batches") or [])
                if _belongs_to_allowed_inventory(option)
            ],
        }

    return Response(result)


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPermission])
def assign_storage_location(request):
    body = request.data if isinstance(request.data, Mapping) else {}
    errors: Dict[str, str] = {}

    item_id = _parse_positive_int(body.get("item_id"), "item_id", errors)
    inventory_id = _parse_positive_int(body.get("inventory_id"), "inventory_id", errors)
    location_id = _parse_positive_int(body.get("location_id"), "location_id", errors)

    batch_id: int | None = None
    raw_batch_id = body.get("batch_id")
    if raw_batch_id not in (None, ""):
        batch_id = _parse_positive_int(raw_batch_id, "batch_id", errors)

    if errors:
        return Response({"errors": errors}, status=400)

    assert item_id is not None
    assert inventory_id is not None
    assert location_id is not None

    try:
        result = location_storage.assign_storage_location(
            item_id=item_id,
            inventory_id=inventory_id,
            location_id=location_id,
            batch_id=batch_id,
            actor_id=_actor_id(request),
        )
    except location_storage.LocationAssignmentError as exc:
        return Response({"errors": {exc.code: exc.message}}, status=exc.status_code)

    logger.info(
        "location_assignment_saved",
        extra={
            "event_type": "UPDATE",
            "user_id": getattr(request.user, "user_id", None),
            "username": getattr(request.user, "username", None),
            "item_id": result.get("item_id"),
            "inventory_id": result.get("inventory_id"),
            "location_id": result.get("location_id"),
            "batch_id": result.get("batch_id"),
            "storage_table": result.get("storage_table"),
            "created": bool(result.get("created")),
        },
    )

    status_code = 201 if result.get("created") else 200
    return Response(result, status=status_code)


@api_view(["GET", "POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPermission])
def inventory_repackaging(request):
    if request.method == "GET":
        warehouse_id_filter = request.query_params.get("warehouse_id")
        errors: Dict[str, str] = {}
        parsed_warehouse_id = (
            _parse_positive_int(warehouse_id_filter, "warehouse_id", errors)
            if warehouse_id_filter not in (None, "")
            else None
        )
        if errors:
            return Response({"errors": errors}, status=400)
        if _should_enforce_tenant_scope(request) and parsed_warehouse_id is None:
            return Response(
                {
                    "errors": {
                        "warehouse_id": (
                            "warehouse_id is required when tenant scope enforcement is enabled."
                        )
                    }
                },
                status=400,
            )
        scope_error = _require_warehouse_scope(
            request,
            parsed_warehouse_id,
            write=False,
        )
        if scope_error:
            return scope_error

        try:
            limit = int(request.query_params.get("limit", 100))
            limit = max(1, min(limit, 500))
            offset = max(int(request.query_params.get("offset", 0)), 0)
        except (TypeError, ValueError):
            limit, offset = 100, 0

        rows, total, warnings = repackaging_service.list_repackaging_transactions(
            warehouse_id=parsed_warehouse_id,
            item_id=request.query_params.get("item_id"),
            batch_id=request.query_params.get("batch_id"),
            limit=limit,
            offset=offset,
        )
        if "db_unavailable" in warnings:
            return Response(
                {
                    "detail": "Repackaging is unavailable in this environment.",
                    "warnings": warnings,
                },
                status=503,
            )
        if "db_error" in warnings:
            return Response(
                {
                    "detail": "Failed to load repackaging transactions.",
                    "warnings": warnings,
                },
                status=500,
            )
        return Response(
            {
                "results": rows,
                "count": total,
                "limit": limit,
                "offset": offset,
                "warnings": warnings,
            }
        )

    body = request.data if isinstance(request.data, Mapping) else {}
    errors: Dict[str, str] = {}

    warehouse_id = _parse_positive_int(body.get("warehouse_id"), "warehouse_id", errors)
    item_id = _parse_positive_int(body.get("item_id"), "item_id", errors)

    source_uom_code = str(body.get("source_uom_code") or "").strip()
    if not source_uom_code:
        errors["source_uom_code"] = "source_uom_code is required."

    target_uom_code = str(body.get("target_uom_code") or "").strip()
    if not target_uom_code:
        errors["target_uom_code"] = "target_uom_code is required."

    if body.get("source_qty") in (None, ""):
        errors["source_qty"] = "source_qty is required."

    reason_code = str(body.get("reason_code") or "").strip()
    if not reason_code:
        errors["reason_code"] = "reason_code is required."

    batch_id: int | None = None
    raw_batch_id = body.get("batch_id")
    if raw_batch_id not in (None, ""):
        batch_id = _parse_positive_int(raw_batch_id, "batch_id", errors)

    if errors:
        return Response({"errors": errors}, status=400)

    assert warehouse_id is not None
    assert item_id is not None

    scope_error = _require_warehouse_scope(
        request,
        warehouse_id,
        write=True,
    )
    if scope_error:
        return scope_error

    try:
        record, warnings = repackaging_service.create_repackaging_transaction(
            warehouse_id=warehouse_id,
            item_id=item_id,
            source_uom_code=source_uom_code,
            source_qty=body.get("source_qty"),
            target_uom_code=target_uom_code,
            reason_code=reason_code,
            note_text=str(body.get("note_text") or body.get("note") or "").strip(),
            batch_id=batch_id,
            batch_or_lot=str(body.get("batch_or_lot") or "").strip(),
            client_target_qty=body.get("target_qty"),
            client_equivalent_default_qty=body.get("equivalent_default_qty"),
            actor_id=_actor_id(request),
        )
    except RepackagingError as exc:
        response_payload: Dict[str, Any] = {
            "detail": exc.detail,
            "errors": {exc.code: exc.payload},
            "warnings": exc.warnings,
        }
        if exc.diagnostic:
            response_payload["diagnostic"] = exc.diagnostic
        return Response(response_payload, status=exc.status_code)

    return Response({"record": record, "warnings": warnings}, status=201)


@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPermission])
def inventory_repackaging_detail(request, repackaging_id: int):
    record, warnings = repackaging_service.get_repackaging_transaction(repackaging_id)
    if record is None:
        if "db_unavailable" in warnings:
            return Response(
                {
                    "detail": "Repackaging is unavailable in this environment.",
                    "warnings": warnings,
                },
                status=503,
            )
        if "db_error" in warnings:
            return Response(
                {"detail": "Failed to load repackaging detail.", "warnings": warnings},
                status=500,
            )
        return Response({"detail": "Not found."}, status=404)
    scope_error = _require_warehouse_scope(
        request,
        record.get("warehouse_id"),
        write=False,
    )
    if scope_error:
        return Response({"detail": "Not found."}, status=404)
    return Response({"record": record, "warnings": warnings})


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPreviewPermission])
def needs_list_preview(request):
    payload = request.data or {}
    response, errors = _build_preview_response(payload)
    if errors:
        status_code = 503 if STRICT_INBOUND_VIEW_MISSING_CODE in errors else 400
        return Response({"errors": errors}, status=status_code)
    scope_error = _require_warehouse_scope(
        request,
        response.get("warehouse_id"),
        write=False,
    )
    if scope_error:
        return scope_error

    logger.info(
        "needs_list_preview",
        extra={
            "event_type": "READ",
            "user_id": getattr(request.user, "user_id", None),
            "username": getattr(request.user, "username", None),
            "event_id": response.get("event_id"),
            "warehouse_id": response.get("warehouse_id"),
            "as_of_datetime": response.get("as_of_datetime"),
            "planning_window_days": response.get("planning_window_days"),
            "item_count": len(response.get("items", [])),
            "warnings": response.get("warnings", []),
        },
    )

    return Response(response)


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPreviewPermission])
def needs_list_preview_multi(request):
    """
    Generate needs list preview for multiple warehouses.
    Aggregates results across selected warehouses.
    """
    payload = request.data or {}
    warehouse_ids = payload.get("warehouse_ids", [])

    if not warehouse_ids or not isinstance(warehouse_ids, list):
        return Response({"errors": {"warehouse_ids": "warehouse_ids array required"}}, status=400)

    errors: Dict[str, str] = {}

    # Validate event_id
    event_id = _parse_positive_int(payload.get("event_id"), "event_id", errors)
    if errors:
        return Response({"errors": errors}, status=400)

    # Validate warehouse_ids are positive integers
    validated_warehouse_ids = []
    for wh_id in warehouse_ids:
        wh_id_parsed = _parse_positive_int(wh_id, "warehouse_id", errors)
        if wh_id_parsed:
            validated_warehouse_ids.append(wh_id_parsed)

    if errors:
        return Response({"errors": errors}, status=400)

    if not validated_warehouse_ids:
        return Response({"errors": {"warehouse_ids": "At least one valid warehouse ID required"}}, status=400)

    # Get phase from payload
    phase = payload.get("phase")
    if not phase:
        phase = "BASELINE"
    phase = str(phase).upper()
    if phase not in rules.PHASES:
        return Response({"errors": {"phase": "Must be SURGE, STABILIZED, or BASELINE."}}, status=400)

    # Enforce tenant warehouse scope before doing warehouse-specific preview work.
    unauthorized_warehouses = [
        warehouse_id
        for warehouse_id in validated_warehouse_ids
        if _require_warehouse_scope(request, warehouse_id, write=False)
    ]
    if unauthorized_warehouses:
        return Response(
            {
                "errors": {
                    "tenant_scope": (
                        "Access denied for one or more requested warehouses."
                    )
                },
                "unauthorized_warehouse_ids": unauthorized_warehouses,
            },
            status=403,
        )

    # Aggregate results from all warehouses
    all_items = []
    warehouse_metadata = []
    base_warnings = []

    for warehouse_id in validated_warehouse_ids:
        # Build preview for this warehouse
        wh_payload = dict(payload)
        wh_payload["warehouse_id"] = warehouse_id
        response, wh_errors = _build_preview_response(wh_payload)

        if wh_errors:
            if STRICT_INBOUND_VIEW_MISSING_CODE in wh_errors:
                return Response(
                    {
                        "errors": wh_errors,
                        "warehouse_id": warehouse_id,
                    },
                    status=503,
                )
            # Log error but continue with other warehouses
            logger.warning(
                "Preview failed for warehouse_id=%s: %s",
                warehouse_id,
                wh_errors
            )
            base_warnings.append(f"preview_failed_warehouse_{warehouse_id}")
            continue

        # Get warehouse name
        warehouse_name = data_access.get_warehouse_name(warehouse_id)

        # Add warehouse info to each item
        for item in response.get("items", []):
            item["warehouse_id"] = warehouse_id
            item["warehouse_name"] = warehouse_name

        all_items.extend(response.get("items", []))
        warehouse_metadata.append({
            "warehouse_id": warehouse_id,
            "warehouse_name": warehouse_name
        })

        # Merge warnings
        base_warnings.extend(response.get("warnings", []))

    # Build aggregated response
    aggregated_response = {
        "event_id": event_id,
        "phase": phase,
        "warehouse_ids": validated_warehouse_ids,
        "warehouses": warehouse_metadata,
        "items": all_items,
        "as_of_datetime": timezone.now().isoformat(),
        "warnings": list(set(base_warnings)),  # Deduplicate warnings
    }

    logger.info(
        "needs_list_preview_multi",
        extra={
            "event_type": "READ",
            "user_id": getattr(request.user, "user_id", None),
            "username": getattr(request.user, "username", None),
            "event_id": event_id,
            "warehouse_ids": validated_warehouse_ids,
            "warehouse_count": len(validated_warehouse_ids),
            "item_count": len(all_items),
            "warnings": aggregated_response.get("warnings", []),
        },
    )

    return Response(aggregated_response)


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPermission])
def needs_list_draft(request):
    payload = request.data or {}
    response, errors = _build_preview_response(payload)
    if errors and STRICT_INBOUND_VIEW_MISSING_CODE in errors:
        return Response({"errors": errors}, status=503)
    selected_item_keys = _parse_selected_item_keys(payload.get("selected_item_keys"), errors)
    selected_method_raw = payload.get("selected_method")
    selected_method = None
    if selected_method_raw is not None:
        selected_method = str(selected_method_raw).strip().upper()
        if selected_method not in {"A", "B", "C"}:
            errors["selected_method"] = "Must be one of: A, B, C."

    if errors:
        return Response({"errors": errors}, status=400)
    scope_error = _require_warehouse_scope(
        request,
        response.get("warehouse_id"),
        write=True,
    )
    if scope_error:
        return scope_error

    try:
        workflow_store.store_enabled_or_raise()
    except RuntimeError:
        return _workflow_disabled_response()

    event_id = response.get("event_id")
    warehouse_id = response.get("warehouse_id")
    all_items = response.get("items", []) or []
    if selected_item_keys is not None:
        filtered_items = [
            item
            for item in all_items
            if (
                f"{item.get('item_id')}_{item.get('warehouse_id') or 0}" in selected_item_keys
                or (
                    warehouse_id is not None
                    and f"{item.get('item_id')}_{warehouse_id}" in selected_item_keys
                )
            )
        ]
    else:
        filtered_items = all_items

    if not filtered_items:
        return Response(
            {"errors": {"items": "At least one selected item is required."}},
            status=400,
        )

    filtered_item_ids = [
        item_id
        for item in filtered_items
        if (item_id := _to_int_or_none(item.get("item_id"))) is not None
    ]
    inactive_item_ids, inactive_item_warnings = data_access.get_inactive_item_ids(filtered_item_ids)
    if inactive_item_ids:
        error_payload = {
            "code": INACTIVE_ITEM_FORWARD_WRITE_CODE,
            "table": "needs_list_item",
            "workflow_state": "DRAFT_GENERATION",
            "item_ids": inactive_item_ids,
        }
        return Response(
            {
                "detail": "Cannot write forward-looking data for inactive item(s).",
                "errors": {INACTIVE_ITEM_FORWARD_WRITE_CODE: error_payload},
                "warnings": inactive_item_warnings,
            },
            status=409,
        )
    if inactive_item_warnings:
        response["warnings"] = needs_list.merge_warnings(
            response.get("warnings", []),
            inactive_item_warnings,
        )

    event_name = (
        data_access.get_event_name(int(event_id))
        if event_id is not None
        else None
    )
    warehouse_name = (
        data_access.get_warehouse_name(int(warehouse_id))
        if warehouse_id is not None
        else None
    )

    record_payload = {
        "event_id": event_id,
        "event_name": event_name,
        "warehouse_id": warehouse_id,
        "tenant_id": resolve_warehouse_tenant_id(_to_int_or_none(warehouse_id)),
        "warehouse_ids": [warehouse_id] if warehouse_id is not None else [],
        "warehouses": (
            [{"warehouse_id": warehouse_id, "warehouse_name": warehouse_name}]
            if warehouse_id is not None
            else []
        ),
        "phase": response.get("phase"),
        "as_of_datetime": response.get("as_of_datetime"),
        "planning_window_days": response.get("planning_window_days"),
        "filters": payload.get("filters"),
        "selected_method": selected_method,
        "selected_item_keys": sorted(selected_item_keys) if selected_item_keys is not None else None,
    }
    record = workflow_store.create_draft(
        record_payload,
        filtered_items,
        response.get("warnings", []),
        _actor_id(request),
    )

    logger.info(
        "needs_list_draft_created",
        extra={
            "event_type": "CREATE",
            "user_id": getattr(request.user, "user_id", None),
            "username": getattr(request.user, "username", None),
            "needs_list_id": record.get("needs_list_id"),
            "event_id": event_id,
            "warehouse_id": warehouse_id,
            "item_count": len(filtered_items),
            "selected_method": selected_method,
        },
    )

    return Response(_serialize_workflow_record(record, include_overrides=False))


@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPermission])
def needs_list_get(request, needs_list_id: str):
    try:
        workflow_store.store_enabled_or_raise()
    except RuntimeError:
        return _workflow_disabled_response()

    record = workflow_store.get_record(needs_list_id)
    if not record:
        return Response({"errors": {"needs_list_id": "Not found."}}, status=404)
    scope_error = _require_record_scope(request, record, write=False)
    if scope_error:
        return scope_error

    response = _serialize_workflow_record(record, include_overrides=True)
    response["allowed_actions"] = _available_actions_for_record(request, record)
    logger.info(
        "needs_list_get",
        extra={
            "event_type": "READ",
            "user_id": getattr(request.user, "user_id", None),
            "username": getattr(request.user, "username", None),
            "needs_list_id": needs_list_id,
            "item_count": len(response.get("items", [])),
        },
    )
    return Response(response)


@api_view(["PATCH"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPermission])
def needs_list_edit_lines(request, needs_list_id: str):
    try:
        workflow_store.store_enabled_or_raise()
    except RuntimeError:
        return _workflow_disabled_response()

    record = workflow_store.get_record(needs_list_id)
    if not record:
        return Response({"errors": {"needs_list_id": "Not found."}}, status=404)
    scope_error = _require_record_scope(request, record, write=True)
    if scope_error:
        return scope_error

    status = str(record.get("status") or "").upper()
    if not _status_matches(status, "DRAFT", "MODIFIED", include_db_transitions=True):
        return Response({"errors": {"status": "Only draft or modified needs lists can be edited."}}, status=409)

    overrides_raw = request.data
    if not isinstance(overrides_raw, list):
        return Response({"errors": {"lines": "Expected a list of overrides."}}, status=400)

    overrides: list[Dict[str, object]] = []
    parse_errors: list[str] = []
    for entry in overrides_raw:
        if not isinstance(entry, dict):
            parse_errors.append("Each override must be an object.")
            continue
        item_id = entry.get("item_id")
        reason = entry.get("reason")
        overridden_qty = entry.get("overridden_qty")
        if item_id is None:
            parse_errors.append("item_id is required.")
            continue
        if overridden_qty is None:
            parse_errors.append(f"overridden_qty is required for item_id {item_id}.")
            continue
        try:
            overridden_qty = float(overridden_qty)
            if not math.isfinite(overridden_qty) or overridden_qty < 0:
                raise ValueError("overridden_qty must be a finite, non-negative number")
        except (TypeError, ValueError):
            parse_errors.append(f"overridden_qty must be numeric for item_id {item_id}.")
            continue
        overrides.append(
            {
                "item_id": item_id,
                "overridden_qty": overridden_qty,
                "reason": reason,
            }
        )

    if parse_errors:
        return Response({"errors": {"lines": parse_errors}}, status=400)

    record, errors = workflow_store.add_line_overrides(record, overrides, _actor_id(request))
    if errors:
        return Response({"errors": {"lines": errors}}, status=400)
    workflow_store.update_record(needs_list_id, record)

    response = _serialize_workflow_record(record, include_overrides=True)
    logger.info(
        "needs_list_lines_updated",
        extra={
            "event_type": "UPDATE",
            "user_id": getattr(request.user, "user_id", None),
            "username": getattr(request.user, "username", None),
            "needs_list_id": needs_list_id,
            "line_count": len(overrides),
        },
    )
    return Response(response)


@api_view(["PATCH"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPermission])
def needs_list_review_comments(request, needs_list_id: str):
    try:
        workflow_store.store_enabled_or_raise()
    except RuntimeError:
        return _workflow_disabled_response()

    record = workflow_store.get_record(needs_list_id)
    if not record:
        return Response({"errors": {"needs_list_id": "Not found."}}, status=404)
    scope_error = _require_record_scope(request, record, write=True)
    if scope_error:
        return scope_error

    status = str(record.get("status") or "").upper()
    if status not in PENDING_APPROVAL_STATUSES:
        return Response({"errors": {"status": "Needs list must be pending approval."}}, status=409)

    notes_raw = request.data
    if not isinstance(notes_raw, list):
        return Response({"errors": {"lines": "Expected a list of comments."}}, status=400)

    notes: list[Dict[str, object]] = []
    parse_errors: list[str] = []
    for entry in notes_raw:
        if not isinstance(entry, dict):
            parse_errors.append("Each comment must be an object.")
            continue
        item_id = entry.get("item_id")
        comment = entry.get("comment")
        if item_id is None:
            parse_errors.append("item_id is required.")
            continue
        if not comment or not str(comment).strip():
            parse_errors.append(f"comment is required for item_id {item_id}.")
            continue
        notes.append(
            {
                "item_id": item_id,
                "comment": str(comment).strip(),
            }
        )

    if parse_errors:
        return Response({"errors": {"lines": parse_errors}}, status=400)

    record, errors = workflow_store.add_line_review_notes(record, notes, _actor_id(request))
    if errors:
        return Response({"errors": {"lines": errors}}, status=400)
    workflow_store.update_record(needs_list_id, record)

    response = _serialize_workflow_record(record, include_overrides=True)
    logger.info(
        "needs_list_review_comments_updated",
        extra={
            "event_type": "UPDATE",
            "user_id": getattr(request.user, "user_id", None),
            "username": getattr(request.user, "username", None),
            "needs_list_id": needs_list_id,
            "line_count": len(notes),
        },
    )
    return Response(response)


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPermission])
def needs_list_submit(request, needs_list_id: str):
    try:
        workflow_store.store_enabled_or_raise()
    except RuntimeError:
        return _workflow_disabled_response()

    record = workflow_store.get_record(needs_list_id)
    if not record:
        return Response({"errors": {"needs_list_id": "Not found."}}, status=404)
    scope_error = _require_record_scope(request, record, write=True)
    if scope_error:
        return scope_error

    previous_status = str(record.get("status") or "").upper()
    if not _status_matches(previous_status, "DRAFT", "MODIFIED", include_db_transitions=True):
        return Response({"errors": {"status": "Only draft or modified needs lists can be submitted."}}, status=409)

    submit_empty_allowed = bool((request.data or {}).get("submit_empty_allowed", False))
    item_count = len(record.get("snapshot", {}).get("items") or [])
    if item_count == 0 and not submit_empty_allowed:
        return Response({"errors": {"items": "Cannot submit an empty needs list."}}, status=409)

    try:
        duplicate_conflicts = _find_submitted_or_approved_overlap_conflicts(
            record,
            exclude_needs_list_id=needs_list_id,
        )
    except DuplicateConflictValidationError:
        logger.warning(
            "needs_list_duplicate_validation_failed",
            extra={
                "event_type": "VALIDATION_ERROR",
                "needs_list_id": needs_list_id,
                "actor": _actor_id(request),
                "status": record.get("status") if isinstance(record, dict) else None,
                "event_id": record.get("event_id") if isinstance(record, dict) else None,
                "phase": record.get("phase") if isinstance(record, dict) else None,
                "warehouse_id": record.get("warehouse_id") if isinstance(record, dict) else None,
            },
        )
        return Response(
            {
                "errors": {
                    "duplicate": "Failed to validate duplicate needs lists. Please retry."
                }
            },
            status=503,
        )
    if duplicate_conflicts:
        return Response(
            {
                "errors": {
                    "duplicate": (
                        "A submitted or approved needs list already exists for one or more "
                        "of these items in the same warehouse."
                    )
                },
                "conflicts": duplicate_conflicts,
            },
            status=409,
        )

    target_status = _workflow_target_status("SUBMITTED")
    record = workflow_store.transition_status(record, target_status, _actor_id(request))
    record["submitted_approval_summary"] = _compute_approval_summary(
        record,
        workflow_store.apply_overrides(record),
    )
    workflow_store.update_record(needs_list_id, record)

    logger.info(
        "needs_list_submitted",
        extra={
            "event_type": "STATE_CHANGE",
            "user_id": getattr(request.user, "user_id", None),
            "username": getattr(request.user, "username", None),
            "needs_list_id": needs_list_id,
            "from_status": previous_status,
            "to_status": target_status,
            "item_count": item_count,
        },
    )

    return Response(_serialize_workflow_record(record, include_overrides=True))


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPermission])
def needs_list_return(request, needs_list_id: str):
    try:
        workflow_store.store_enabled_or_raise()
    except RuntimeError:
        return _workflow_disabled_response()

    record = workflow_store.get_record(needs_list_id)
    if not record:
        return Response({"errors": {"needs_list_id": "Not found."}}, status=404)
    scope_error = _require_record_scope(request, record, write=True)
    if scope_error:
        return scope_error

    current_status = str(record.get("status") or "").upper()
    if current_status not in PENDING_APPROVAL_STATUSES:
        return Response({"errors": {"status": "Needs list must be pending approval."}}, status=409)

    actor = _actor_id(request)
    reviewer_error = _reviewer_must_differ_from_submitter(record, actor)
    if reviewer_error:
        return reviewer_error

    reason_code = str((request.data or {}).get("reason_code") or "").strip().upper()
    if not reason_code:
        return Response({"errors": {"reason_code": "Reason code is required."}}, status=400)
    if reason_code not in REQUEST_CHANGE_REASON_CODES:
        return Response(
            {
                "errors": {
                    "reason_code": (
                        "Invalid reason code. Must be one of: "
                        + ", ".join(sorted(REQUEST_CHANGE_REASON_CODES))
                    )
                }
            },
            status=400,
        )

    reason = str((request.data or {}).get("reason") or "").strip()
    if not reason:
        reason = "Changes requested by approver."

    with transaction.atomic():
        _release_execution_reservations(
            record,
            actor_user_id=actor or "SYSTEM",
            reason_code=f"return:{reason_code}",
        )
        target_status = _workflow_target_status("MODIFIED")
        record = workflow_store.transition_status(record, target_status, actor, reason=reason)
        record["return_reason"] = reason
        record["return_reason_code"] = reason_code
        workflow_store.update_record(needs_list_id, record)

    logger.info(
        "needs_list_changes_requested",
        extra={
            "event_type": "STATE_CHANGE",
            "user_id": getattr(request.user, "user_id", None),
            "username": getattr(request.user, "username", None),
            "needs_list_id": needs_list_id,
            "from_status": current_status,
            "to_status": target_status,
            "reason_code": reason_code,
            "reason": reason,
        },
    )

    return Response(_serialize_workflow_record(record, include_overrides=True))


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPermission])
def needs_list_reject(request, needs_list_id: str):
    try:
        workflow_store.store_enabled_or_raise()
    except RuntimeError:
        return _workflow_disabled_response()

    record = workflow_store.get_record(needs_list_id)
    if not record:
        return Response({"errors": {"needs_list_id": "Not found."}}, status=404)
    scope_error = _require_record_scope(request, record, write=True)
    if scope_error:
        return scope_error

    current_status = str(record.get("status") or "").upper()
    if current_status not in PENDING_APPROVAL_STATUSES:
        return Response({"errors": {"status": "Needs list must be pending approval."}}, status=409)

    actor = _actor_id(request)
    reviewer_error = _reviewer_must_differ_from_submitter(record, actor)
    if reviewer_error:
        return reviewer_error

    snapshot = workflow_store.apply_overrides(record)
    approval_summary = _approval_summary_for_record(record, snapshot)
    approval = approval_summary.get("approval") or {}
    submitter_roles = approval_service.resolve_submitter_roles(record)
    required_roles = approval_service.required_roles_for_approval(
        approval,
        record=record,
        submitter_roles=submitter_roles,
    )
    roles, _ = resolve_roles_and_permissions(request, request.user)
    role_set: set[str] = set()
    for role in roles:
        normalized_role = str(role).strip().upper().replace("-", "_").replace(" ", "_")
        while "__" in normalized_role:
            normalized_role = normalized_role.replace("__", "_")
        if normalized_role:
            role_set.add(normalized_role)
    if not role_set.intersection(required_roles):
        return Response({"errors": {"approval": "Approver role not authorized."}}, status=403)

    reason = (request.data or {}).get("reason")
    if not reason:
        return Response({"errors": {"reason": "Reason is required."}}, status=400)

    with transaction.atomic():
        _release_execution_reservations(
            record,
            actor_user_id=actor or "SYSTEM",
            reason_code="reject",
        )
        record = workflow_store.transition_status(record, "REJECTED", actor, reason=reason)
        workflow_store.update_record(needs_list_id, record)

    logger.info(
        "needs_list_rejected",
        extra={
            "event_type": "STATE_CHANGE",
            "user_id": getattr(request.user, "user_id", None),
            "username": getattr(request.user, "username", None),
            "needs_list_id": needs_list_id,
            "from_status": current_status,
            "to_status": "REJECTED",
            "reason": reason,
        },
    )

    return Response(_serialize_workflow_record(record, include_overrides=True))


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPermission])
def needs_list_approve(request, needs_list_id: str):
    try:
        workflow_store.store_enabled_or_raise()
    except RuntimeError:
        return _workflow_disabled_response()

    record = workflow_store.get_record(needs_list_id)
    if not record:
        return Response({"errors": {"needs_list_id": "Not found."}}, status=404)
    scope_error = _require_record_scope(request, record, write=True)
    if scope_error:
        return scope_error

    current_status = str(record.get("status") or "").upper()
    if current_status not in PENDING_APPROVAL_STATUSES:
        return Response({"errors": {"status": "Needs list must be pending approval."}}, status=409)

    actor = _actor_id(request)
    if not record.get("submitted_by") or record.get("submitted_by") == actor:
        return Response(
            {"errors": {"approval": "Approver must be different from submitter."}},
            status=409,
        )

    comment = (request.data or {}).get("comment")
    snapshot = workflow_store.apply_overrides(record)
    approval_summary = _approval_summary_for_record(record, snapshot)
    total_required_qty = float(approval_summary.get("total_required_qty") or 0.0)
    total_estimated_cost = approval_summary.get("total_estimated_cost")
    approval = approval_summary.get("approval") or {}
    approval_rationale = str(approval_summary.get("rationale") or "")
    warnings = approval_summary.get("warnings") or []
    escalation_required = bool(approval_summary.get("escalation_required"))
    if escalation_required:
        return Response(
            {
                "errors": {"approval": "Escalation required by Appendix C rules."},
                "warnings": warnings,
            },
            status=409,
        )
    submitter_roles = approval_service.resolve_submitter_roles(record)
    required_roles = approval_service.required_roles_for_approval(
        approval,
        record=record,
        submitter_roles=submitter_roles,
    )

    roles, _ = resolve_roles_and_permissions(request, request.user)
    role_set: set[str] = set()
    for role in roles:
        normalized_role = str(role).strip().upper().replace("-", "_").replace(" ", "_")
        while "__" in normalized_role:
            normalized_role = normalized_role.replace("__", "_")
        if normalized_role:
            role_set.add(normalized_role)
    if not role_set.intersection(required_roles):
        return Response({"errors": {"approval": "Approver role not authorized."}}, status=403)

    record = workflow_store.transition_status(record, "APPROVED", actor)
    record["approval_tier"] = approval.get("tier")
    record["approval_rationale"] = approval_rationale
    record["submitted_approval_summary"] = approval_summary
    workflow_store.update_record(needs_list_id, record)

    logger.info(
        "needs_list_approved",
        extra={
            "event_type": "STATE_CHANGE",
            "user_id": getattr(request.user, "user_id", None),
            "username": getattr(request.user, "username", None),
            "needs_list_id": needs_list_id,
            "from_status": current_status,
            "to_status": "APPROVED",
            "approval_tier": approval.get("tier"),
            "approval_rationale": approval_rationale,
            "comment": comment,
            "warnings": warnings,
            "total_required_qty": round(total_required_qty, 2),
            "total_estimated_cost": total_estimated_cost,
        },
    )

    return Response(_serialize_workflow_record(record, include_overrides=True))


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPermission])
def needs_list_escalate(request, needs_list_id: str):
    try:
        workflow_store.store_enabled_or_raise()
    except RuntimeError:
        return _workflow_disabled_response()

    record = workflow_store.get_record(needs_list_id)
    if not record:
        return Response({"errors": {"needs_list_id": "Not found."}}, status=404)
    scope_error = _require_record_scope(request, record, write=True)
    if scope_error:
        return scope_error

    current_status = str(record.get("status") or "").upper()
    if current_status not in PENDING_APPROVAL_STATUSES:
        return Response({"errors": {"status": "Needs list must be pending approval."}}, status=409)

    actor = _actor_id(request)
    reviewer_error = _reviewer_must_differ_from_submitter(record, actor)
    if reviewer_error:
        return reviewer_error

    reason = (request.data or {}).get("reason")
    if not reason:
        return Response({"errors": {"reason": "Reason is required."}}, status=400)

    record = workflow_store.transition_status(record, "ESCALATED", actor, reason=reason)
    target_status = _workflow_target_status("ESCALATED")
    workflow_store.update_record(needs_list_id, record)

    logger.info(
        "needs_list_escalated",
        extra={
            "event_type": "STATE_CHANGE",
            "user_id": getattr(request.user, "user_id", None),
            "username": getattr(request.user, "username", None),
            "needs_list_id": needs_list_id,
            "from_status": current_status,
            "to_status": target_status,
            "reason": reason,
        },
    )

    return Response(_serialize_workflow_record(record, include_overrides=True))


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPermission])
def needs_list_review_reminder(request, needs_list_id: str):
    try:
        workflow_store.store_enabled_or_raise()
    except RuntimeError:
        return _workflow_disabled_response()

    record = workflow_store.get_record(needs_list_id)
    if not record:
        return Response({"errors": {"needs_list_id": "Not found."}}, status=404)
    scope_error = _require_record_scope(request, record, write=True)
    if scope_error:
        return scope_error

    status = str(record.get("status") or "").upper()
    if status not in PENDING_APPROVAL_STATUSES:
        return Response(
            {"errors": {"status": "Needs list must be pending approval."}},
            status=409,
        )

    submitted_at_raw = record.get("submitted_at")
    if not submitted_at_raw:
        return Response(
            {"errors": {"submitted_at": "Needs list has not been submitted."}},
            status=409,
        )

    submitted_at = parse_datetime(str(submitted_at_raw))
    if submitted_at is None:
        return Response(
            {"errors": {"submitted_at": "Needs list has invalid submitted timestamp."}},
            status=409,
        )
    if timezone.is_naive(submitted_at):
        submitted_at = timezone.make_aware(
            submitted_at,
            timezone.get_default_timezone(),
        )

    pending_hours = max((timezone.now() - submitted_at).total_seconds() / 3600.0, 0.0)
    if pending_hours < 4:
        return Response(
            {
                "errors": {
                    "reminder": "Reminder is available after 4 hours pending approval."
                },
                "pending_hours": round(pending_hours, 2),
            },
            status=409,
        )

    escalation_recommended = pending_hours >= 8
    reminder_sent_at = timezone.now().isoformat()

    logger.info(
        "needs_list_review_reminder_sent",
        extra={
            "event_type": "NOTIFICATION",
            "user_id": getattr(request.user, "user_id", None),
            "username": getattr(request.user, "username", None),
            "needs_list_id": needs_list_id,
            "status": status,
            "pending_hours": round(pending_hours, 2),
            "escalation_recommended": escalation_recommended,
        },
    )

    response = _serialize_workflow_record(record, include_overrides=True)
    response["review_reminder"] = {
        "pending_hours": round(pending_hours, 2),
        "reminder_sent_at": reminder_sent_at,
        "escalation_recommended": escalation_recommended,
    }
    return Response(response)


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPermission])
def needs_list_start_preparation(request, needs_list_id: str):
    """
    Transitional compatibility endpoint frozen pending retirement during the Operations cutover.
    """
    try:
        workflow_store.store_enabled_or_raise()
    except RuntimeError:
        return _workflow_disabled_response()

    record = workflow_store.get_record(needs_list_id)
    if not record:
        return Response({"errors": {"needs_list_id": "Not found."}}, status=404)
    scope_error = _require_record_scope(request, record, write=True)
    if scope_error:
        return scope_error

    if record.get("status") != "APPROVED":
        return Response({"errors": {"status": "Needs list must be approved."}}, status=409)

    actor_user_id = _actor_id(request) or "SYSTEM"
    target_status = _workflow_target_status("IN_PREPARATION")
    with transaction.atomic():
        record = workflow_store.transition_status(
            record,
            target_status,
            actor_user_id,
            stage="IN_PREPARATION",
        )
        workflow_store.update_record(needs_list_id, record)
        needs_list_pk = _execution_needs_list_pk(record)
        if needs_list_pk is not None:
            _upsert_execution_link(
                needs_list_id=needs_list_pk,
                actor_user_id=actor_user_id,
                selected_method=_normalize_selected_method_for_execution(
                    (request.data or {}).get("selected_method") or record.get("selected_method")
                ),
                execution_status=NeedsListExecutionLink.ExecutionStatus.PREPARING,
                prepared=True,
            )

    logger.info(
        "needs_list_preparation_started",
        extra={
            "event_type": "STATE_CHANGE",
            "user_id": getattr(request.user, "user_id", None),
            "username": getattr(request.user, "username", None),
            "needs_list_id": needs_list_id,
            "from_status": "APPROVED",
            "to_status": target_status,
        },
    )

    return Response(_serialize_workflow_record(record, include_overrides=True))


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPermission])
def needs_list_mark_dispatched(request, needs_list_id: str):
    """
    Transitional compatibility endpoint frozen pending retirement during the Operations cutover.
    """
    try:
        workflow_store.store_enabled_or_raise()
    except RuntimeError:
        return _workflow_disabled_response()

    record = workflow_store.get_record(needs_list_id)
    if not record:
        return Response({"errors": {"needs_list_id": "Not found."}}, status=404)
    scope_error = _require_record_scope(request, record, write=True)
    if scope_error:
        return scope_error

    if not _status_matches(record.get("status"), "IN_PREPARATION", include_db_transitions=True):
        return Response({"errors": {"status": "Needs list must be in preparation."}}, status=409)
    if not record.get("prep_started_at"):
        return Response({"errors": {"status": "Needs list preparation must be started."}}, status=409)
    if record.get("dispatched_at"):
        return Response({"errors": {"status": "Needs list already dispatched."}}, status=409)

    actor_user_id = _actor_id(request) or "SYSTEM"
    from_status = str(record.get("status") or "").upper()
    target_status = _workflow_target_status("DISPATCHED")
    link = _execution_link_for_record(record)
    try:
        with transaction.atomic():
            dispatch_result = allocation_dispatch.dispatch_package(
                _allocation_context_from_record(record, request.data or {}, link=link),
                actor_user_id=actor_user_id,
                transport_mode=str((request.data or {}).get("transport_mode") or "").strip() or None,
            )
            reliefrqst_id = dispatch_result.get("reliefrqst_id")
            reliefpkg_id = dispatch_result.get("reliefpkg_id")
            if reliefrqst_id is None or reliefpkg_id is None:
                raise allocation_dispatch.AllocationDispatchError(
                    "Dispatch did not return committed request/package identifiers.",
                    code="legacy_context_missing",
                )
            execution_needs_list_id = getattr(link, "needs_list_id", None) or _execution_needs_list_pk(
                record
            )
            if execution_needs_list_id is None:
                raise allocation_dispatch.AllocationDispatchError(
                    "Dispatch requires a persisted needs list execution context.",
                    code="legacy_context_missing",
                )
            record = workflow_store.transition_status(
                record,
                target_status,
                actor_user_id,
                stage="DISPATCHED",
            )
            workflow_store.update_record(needs_list_id, record)
            _upsert_execution_link(
                needs_list_id=execution_needs_list_id,
                actor_user_id=actor_user_id,
                reliefrqst_id=reliefrqst_id,
                reliefpkg_id=reliefpkg_id,
                execution_status=NeedsListExecutionLink.ExecutionStatus.DISPATCHED,
                waybill_no=dispatch_result.get("waybill_no"),
                waybill_payload=dispatch_result.get("waybill_payload"),
                dispatched=True,
            )
    except allocation_dispatch.AllocationDispatchError as exc:
        return Response({"errors": {exc.code: exc.message}}, status=409)

    logger.info(
        "needs_list_dispatched",
        extra={
            "event_type": "STATE_CHANGE",
            "user_id": getattr(request.user, "user_id", None),
            "username": getattr(request.user, "username", None),
            "needs_list_id": needs_list_id,
            "from_status": from_status,
            "to_status": target_status,
        },
    )

    return Response(_serialize_workflow_record(record, include_overrides=True))


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPermission])
def needs_list_mark_received(request, needs_list_id: str):
    """
    Transitional compatibility endpoint frozen pending retirement during the Operations cutover.
    """
    try:
        workflow_store.store_enabled_or_raise()
    except RuntimeError:
        return _workflow_disabled_response()

    record = workflow_store.get_record(needs_list_id)
    if not record:
        return Response({"errors": {"needs_list_id": "Not found."}}, status=404)
    scope_error = _require_record_scope(request, record, write=True)
    if scope_error:
        return scope_error

    if not _status_matches(record.get("status"), "DISPATCHED", include_db_transitions=True):
        return Response({"errors": {"status": "Needs list must be dispatched."}}, status=409)
    if not record.get("dispatched_at"):
        return Response({"errors": {"status": "Needs list must be dispatched."}}, status=409)
    if record.get("received_at"):
        return Response({"errors": {"status": "Needs list already received."}}, status=409)

    actor_user_id = _actor_id(request) or "SYSTEM"
    from_status = str(record.get("status") or "").upper()
    target_status = _workflow_target_status("RECEIVED")
    with transaction.atomic():
        record = workflow_store.transition_status(
            record,
            target_status,
            actor_user_id,
            stage="RECEIVED",
        )
        workflow_store.update_record(needs_list_id, record)
        link = _execution_link_for_record(record)
        if link is not None:
            _upsert_execution_link(
                needs_list_id=link.needs_list_id,
                actor_user_id=actor_user_id,
                reliefrqst_id=link.reliefrqst_id,
                reliefpkg_id=link.reliefpkg_id,
                selected_method=link.selected_method,
                execution_status=NeedsListExecutionLink.ExecutionStatus.RECEIVED,
                received=True,
            )

    logger.info(
        "needs_list_received",
        extra={
            "event_type": "STATE_CHANGE",
            "user_id": getattr(request.user, "user_id", None),
            "username": getattr(request.user, "username", None),
            "needs_list_id": needs_list_id,
            "from_status": from_status,
            "to_status": target_status,
        },
    )

    return Response(_serialize_workflow_record(record, include_overrides=True))


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPermission])
def needs_list_mark_completed(request, needs_list_id: str):
    """
    Transitional compatibility endpoint frozen pending retirement during the Operations cutover.
    """
    try:
        workflow_store.store_enabled_or_raise()
    except RuntimeError:
        return _workflow_disabled_response()

    record = workflow_store.get_record(needs_list_id)
    if not record:
        return Response({"errors": {"needs_list_id": "Not found."}}, status=404)
    scope_error = _require_record_scope(request, record, write=True)
    if scope_error:
        return scope_error

    if not _status_matches(record.get("status"), "RECEIVED", include_db_transitions=True):
        return Response({"errors": {"status": "Needs list must be received."}}, status=409)
    if not record.get("received_at"):
        return Response({"errors": {"status": "Needs list must be received."}}, status=409)
    if record.get("completed_at"):
        return Response({"errors": {"status": "Needs list already completed."}}, status=409)

    actor_user_id = _actor_id(request) or "SYSTEM"
    from_status = str(record.get("status") or "").upper()
    target_status = _workflow_target_status("COMPLETED")
    with transaction.atomic():
        record = workflow_store.transition_status(record, target_status, actor_user_id)
        workflow_store.update_record(needs_list_id, record)

    logger.info(
        "needs_list_completed",
        extra={
            "event_type": "STATE_CHANGE",
            "user_id": getattr(request.user, "user_id", None),
            "username": getattr(request.user, "username", None),
            "needs_list_id": needs_list_id,
            "from_status": from_status,
            "to_status": target_status,
        },
    )

    response_payload = _serialize_workflow_record(record, include_overrides=True)
    if str(response_payload.get("status") or "").strip().upper() == "FULFILLED":
        response_payload["execution_stage"] = "COMPLETED"
    return Response(response_payload)


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPermission])
def needs_list_cancel(request, needs_list_id: str):
    """
    Transitional compatibility endpoint frozen pending retirement during the Operations cutover.
    """
    try:
        workflow_store.store_enabled_or_raise()
    except RuntimeError:
        return _workflow_disabled_response()

    record = workflow_store.get_record(needs_list_id)
    if not record:
        return Response({"errors": {"needs_list_id": "Not found."}}, status=404)
    scope_error = _require_record_scope(request, record, write=True)
    if scope_error:
        return scope_error

    if not _status_matches(record.get("status"), "APPROVED", "IN_PREPARATION", include_db_transitions=True):
        return Response({"errors": {"status": "Cancel not allowed in current state."}}, status=409)

    if any(record.get(field) for field in ("dispatched_at", "received_at", "completed_at")):
        return Response(
            {"errors": {"status": "Cancel not allowed after dispatch/receipt/completion."}},
            status=409,
        )

    reason = (request.data or {}).get("reason")
    if not reason:
        return Response({"errors": {"reason": "Reason is required."}}, status=400)

    actor_user_id = _actor_id(request) or "SYSTEM"
    from_status = record.get("status")
    with transaction.atomic():
        _release_execution_reservations(
            record,
            actor_user_id=actor_user_id,
            reason_code="cancel",
            cancel=True,
        )
        record = workflow_store.transition_status(
            record, "CANCELLED", actor_user_id, reason=reason
        )
        target_status = _workflow_target_status("CANCELLED")
        workflow_store.update_record(needs_list_id, record)

    logger.info(
        "needs_list_cancelled",
        extra={
            "event_type": "STATE_CHANGE",
            "user_id": getattr(request.user, "user_id", None),
            "username": getattr(request.user, "username", None),
            "needs_list_id": needs_list_id,
            "from_status": from_status,
            "to_status": target_status,
            "reason": reason,
        },
    )

    return Response(_serialize_workflow_record(record, include_overrides=True))


def _allocation_contracts_unavailable_response() -> Response:
    return Response(
        {
            "errors": {
                "allocation": "Allocation and dispatch contracts require the DB-backed replenishment workflow."
            }
        },
        status=409,
    )


def _allocation_record_or_response(
    request,
    needs_list_id: str,
    *,
    write: bool,
) -> tuple[dict[str, Any] | None, Response | None]:
    try:
        workflow_store.store_enabled_or_raise()
    except RuntimeError:
        return None, _workflow_disabled_response()

    record = workflow_store.get_record(needs_list_id)
    if not record:
        return None, Response({"errors": {"needs_list_id": "Not found."}}, status=404)
    scope_error = _require_record_scope(request, record, write=write)
    if scope_error:
        return None, scope_error
    if _execution_needs_list_pk(record) is None:
        return None, Response({"errors": {"needs_list_id": "Needs list is not DB-backed."}}, status=409)
    return record, None


def _allocation_commit_response(
    request,
    needs_list_id: str,
    *,
    approval_required: bool,
    payload_override: Mapping[str, Any] | None = None,
) -> Response:
    record, error_response = _allocation_record_or_response(request, needs_list_id, write=True)
    if error_response is not None:
        return error_response
    assert record is not None

    payload = dict(payload_override or request.data or {})
    actor_user_id = _actor_id(request) or "SYSTEM"
    link = _execution_link_for_record(record)
    needs_list_pk = _execution_needs_list_pk(record)
    if not _status_matches(
        record.get("status"),
        "APPROVED",
        "IN_PREPARATION",
        "IN_PROGRESS",
        include_db_transitions=True,
    ):
        return Response(
            {"errors": {"status": "Allocations can only be committed from approved or active preparation states."}},
            status=409,
        )
    parse_errors: Dict[str, str] = {}
    stored_selections: list[dict[str, Any]] = []
    if approval_required:
        if (
            link is None
            or link.execution_status != NeedsListExecutionLink.ExecutionStatus.PENDING_OVERRIDE_APPROVAL
        ):
            return Response(
                {"errors": {"status": "Override approval requires a pending override allocation."}},
                status=409,
            )
        stored_selections = _stored_execution_allocation_lines(int(needs_list_pk))
        if not stored_selections:
            return Response(
                {"errors": {"allocations": "No pending override allocation is available to approve."}},
                status=409,
            )
        if payload.get("allocations") not in (None, ""):
            provided_selections = _parse_allocation_selections(payload.get("allocations"), parse_errors)
            if parse_errors:
                return Response({"errors": parse_errors}, status=400)
            if _selection_signature(provided_selections) != _selection_signature(stored_selections):
                return Response(
                    {
                        "errors": {
                            "allocations": (
                                "Override approval must use the same pending allocation plan that was submitted."
                            )
                        }
                    },
                    status=409,
                )
        selections = stored_selections
    else:
        selections = _parse_allocation_selections(payload.get("allocations"), parse_errors)
    selected_method = _normalize_selected_method_for_execution(
        payload.get("selected_method") or getattr(link, "selected_method", None)
    )
    if payload.get("selected_method") is not None and selected_method is None:
        parse_errors["selected_method"] = "Must be one of FEFO, FIFO, MIXED, or MANUAL."
    if approval_required and payload.get("selected_method") not in (None, ""):
        stored_method = str(getattr(link, "selected_method", "") or "").strip().upper()
        if stored_method and selected_method and selected_method != stored_method:
            return Response(
                {"errors": {"selected_method": "Override approval must use the originally submitted method."}},
                status=409,
            )
    if not approval_required and link is None and payload.get("agency_id") in (None, ""):
        parse_errors["agency_id"] = "agency_id is required for the first formal allocation commit."
    if not approval_required and link is None and not str(payload.get("urgency_ind") or "").strip():
        parse_errors["urgency_ind"] = "urgency_ind is required for the first formal allocation commit."
    if parse_errors:
        return Response({"errors": parse_errors}, status=400)

    stored_override_reason_code = next(
        (
            str(line.get("override_reason_code") or "").strip()
            for line in stored_selections
            if str(line.get("override_reason_code") or "").strip()
        ),
        "",
    )
    stored_override_note = next(
        (
            str(line.get("override_note") or "").strip()
            for line in stored_selections
            if str(line.get("override_note") or "").strip()
        ),
        "",
    )
    override_reason_code = str(payload.get("override_reason_code") or stored_override_reason_code or "").strip()
    override_note = str(payload.get("override_note") or stored_override_note or "").strip()

    roles, _ = resolve_roles_and_permissions(request, request.user)
    context = _allocation_context_from_record(record, payload, link=link)
    if selected_method is not None:
        context["selected_method"] = selected_method

    try:
        with transaction.atomic():
            if approval_required:
                result = allocation_dispatch.approve_override(
                    context,
                    selections,
                    actor_user_id=actor_user_id,
                    supervisor_user_id=actor_user_id,
                    supervisor_role_codes=roles,
                    submitter_user_id=getattr(link, "override_requested_by", None),
                    override_reason_code=override_reason_code,
                    override_note=override_note,
                )
            else:
                result = allocation_dispatch.commit_allocation(
                    context,
                    selections,
                    actor_user_id=actor_user_id,
                    override_reason_code=override_reason_code or None,
                    override_note=override_note or None,
                )

            needs_list_obj = NeedsList.objects.select_for_update().get(needs_list_id=needs_list_pk)
            _replace_execution_allocation_lines(
                needs_list=needs_list_obj,
                selections=selections,
                actor_user_id=actor_user_id,
                rule_bypass_flag=bool(result.get("override_required")),
                override_reason_code=override_reason_code or None,
                override_note=override_note or None,
                supervisor_user_id=actor_user_id if approval_required else None,
            )
            _upsert_execution_link(
                needs_list_id=needs_list_pk,
                actor_user_id=actor_user_id,
                reliefrqst_id=result.get("reliefrqst_id"),
                reliefpkg_id=result.get("reliefpkg_id"),
                selected_method=selected_method,
                execution_status=(
                    NeedsListExecutionLink.ExecutionStatus.COMMITTED
                    if result.get("status") == "COMMITTED"
                    else NeedsListExecutionLink.ExecutionStatus.PENDING_OVERRIDE_APPROVAL
                ),
                committed=result.get("status") == "COMMITTED",
                override_requested=result.get("status") == "PENDING_OVERRIDE_APPROVAL",
                override_approved=approval_required,
            )
    except allocation_dispatch.AllocationDispatchError as exc:
        return Response({"errors": {exc.code: exc.message}}, status=409)
    except NeedsList.DoesNotExist:
        return Response({"errors": {"needs_list_id": "Not found."}}, status=404)

    refreshed = workflow_store.get_record(needs_list_id) or record
    response_payload = _serialize_workflow_record(refreshed, include_overrides=True)
    response_payload["override_required"] = bool(result.get("override_required"))
    response_payload["override_markers"] = result.get("override_markers") or []
    return Response(response_payload)


@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPermission])
def needs_list_allocation_options(request, needs_list_id: str):
    record, error_response = _allocation_record_or_response(request, needs_list_id, write=False)
    if error_response is not None:
        return error_response
    assert record is not None

    try:
        options = allocation_dispatch.get_allocation_options(_execution_needs_list_pk(record))
    except allocation_dispatch.AllocationDispatchError as exc:
        status = 409 if exc.code in {"needs_list_closed", "overlapping_open_needs_list"} else 400
        return Response({"errors": {exc.code: exc.message}}, status=status)
    return Response(options)


@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPermission])
def needs_list_allocations_current(request, needs_list_id: str):
    record, error_response = _allocation_record_or_response(request, needs_list_id, write=False)
    if error_response is not None:
        return error_response
    assert record is not None
    response_payload = _serialize_workflow_record(record, include_overrides=True)
    return Response(response_payload)


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPermission])
def needs_list_allocations_commit(request, needs_list_id: str):
    """
    Transitional compatibility endpoint frozen pending retirement during the Operations cutover.
    """
    return _allocation_commit_response(request, needs_list_id, approval_required=False)


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPermission])
def needs_list_allocations_override_approve(request, needs_list_id: str):
    """
    Transitional compatibility endpoint frozen pending retirement during the Operations cutover.
    """
    return _allocation_commit_response(request, needs_list_id, approval_required=True)


@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPermission])
def needs_list_waybill(request, needs_list_id: str):
    """
    Transitional compatibility endpoint frozen pending retirement during the Operations cutover.
    """
    record, error_response = _allocation_record_or_response(request, needs_list_id, write=False)
    if error_response is not None:
        return error_response
    assert record is not None
    payload = _execution_payload_for_record(record)
    if not payload.get("waybill_no"):
        return Response({"errors": {"waybill": "Waybill not available."}}, status=404)
    return Response(
        {
            "needs_list_id": needs_list_id,
            "waybill_no": payload.get("waybill_no"),
            "waybill_payload": payload.get("waybill_payload"),
            "request_tracking_no": payload.get("request_tracking_no"),
            "package_tracking_no": payload.get("package_tracking_no"),
        }
    )


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPermission])
def needs_list_generate_transfers(request, needs_list_id: str):
    try:
        workflow_store.store_enabled_or_raise()
    except RuntimeError:
        return _workflow_disabled_response()

    record = workflow_store.get_record(needs_list_id)
    if not record:
        return Response({"errors": {"needs_list_id": "Not found."}}, status=404)
    scope_error = _require_record_scope(request, record, write=True)
    if scope_error:
        return scope_error

    if not _status_matches(
        record.get("status"), "APPROVED", "IN_PREPARATION", "IN_PROGRESS",
        include_db_transitions=True,
    ):
        return Response(
            {"errors": {"status": "Needs list must be approved or in progress."}},
            status=409,
        )

    snapshot = workflow_store.apply_overrides(record)
    items = snapshot.get("items", [])
    warehouse_id = record.get("warehouse_id")
    event_id = record.get("event_id")
    actor = _actor_id(request)

    horizon_a_items = [
        item for item in items
        if (item.get("horizon") or {}).get("A", {}).get("recommended_qty") and
           (item["horizon"]["A"]["recommended_qty"] or 0) > 0
    ]

    if not horizon_a_items:
        return Response(
            {"errors": {"items": "No Horizon A (transfer) items found."}},
            status=400,
        )

    item_ids = [item["item_id"] for item in horizon_a_items]
    source_stock, stock_warnings = data_access.get_warehouses_with_stock(item_ids, warehouse_id)

    all_warnings = list(stock_warnings)

    sources_used: dict = {}
    for item in horizon_a_items:
        iid = item["item_id"]
        needed = item["horizon"]["A"]["recommended_qty"]
        available_sources = source_stock.get(iid, [])
        remaining = needed

        for source in available_sources:
            if remaining <= 0:
                break
            alloc_qty = min(remaining, source["available_qty"])
            src_wh = source["warehouse_id"]

            key = src_wh
            if key not in sources_used:
                sources_used[key] = {"from_warehouse_id": src_wh, "items": []}
            sources_used[key]["items"].append({
                "item_id": iid,
                "item_qty": alloc_qty,
                "uom_code": item.get("uom_code", "EA"),
                "inventory_id": src_wh,
                "item_name": item.get("item_name", f"Item {iid}"),
            })
            remaining -= alloc_qty

        if remaining > 0:
            all_warnings.append(f"insufficient_source_stock_item_{iid}")

    transfer_specs = [
        {
            "from_warehouse_id": src_wh,
            "to_warehouse_id": warehouse_id,
            "event_id": event_id,
            "reason": f"Auto-generated from needs list {record.get('needs_list_no', needs_list_id)}",
            "actor_id": str(actor) if actor is not None else None,
            "items": transfer_data["items"],
        }
        for src_wh, transfer_data in sources_used.items()
    ]

    transfers, created_count, already_exists, transfer_warnings = (
        data_access.create_draft_transfers_if_absent(
            needs_list_id=needs_list_id,
            transfer_specs=transfer_specs,
        )
    )
    all_warnings.extend(transfer_warnings)

    if already_exists:
        return Response(
            {
                "errors": {"transfers": "Draft transfers already exist for this needs list."},
                "transfers": transfers,
                "warnings": all_warnings,
            },
            status=409,
        )

    logger.info(
        "needs_list_transfers_generated",
        extra={
            "event_type": "EXECUTION",
            "user_id": getattr(request.user, "user_id", None),
            "username": getattr(request.user, "username", None),
            "needs_list_id": needs_list_id,
            "transfers_created": created_count,
        },
    )

    return Response({
        "needs_list_id": needs_list_id,
        "transfers": transfers,
        "warnings": all_warnings,
    }, status=201)


@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPermission])
def needs_list_transfers(request, needs_list_id: str):
    try:
        workflow_store.store_enabled_or_raise()
    except RuntimeError:
        return _workflow_disabled_response()

    record = workflow_store.get_record(needs_list_id)
    if not record:
        return Response({"errors": {"needs_list_id": "Not found."}}, status=404)
    scope_error = _require_record_scope(request, record, write=False)
    if scope_error:
        return scope_error

    transfers, warnings = data_access.get_transfers_for_needs_list(needs_list_id)
    logger.info(
        "needs_list_transfers_get",
        extra={
            "event_type": "READ",
            "user_id": getattr(request.user, "keycloak_id", None),
            "username": getattr(request.user, "username", None),
            "needs_list_id": needs_list_id,
            "transfer_count": len(transfers),
        },
    )
    return Response({
        "needs_list_id": needs_list_id,
        "transfers": transfers,
        "warnings": warnings,
    })


@api_view(["PATCH"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPermission])
def needs_list_transfer_update(request, needs_list_id: str, transfer_id: int):
    try:
        workflow_store.store_enabled_or_raise()
    except RuntimeError:
        return _workflow_disabled_response()

    record = workflow_store.get_record(needs_list_id)
    if not record:
        return Response({"errors": {"needs_list_id": "Not found."}}, status=404)
    scope_error = _require_record_scope(request, record, write=True)
    if scope_error:
        return scope_error

    body = request.data or {}
    reason = str(body.get("reason") or "").strip()
    items = body.get("items", [])

    if items and not reason:
        return Response(
            {"errors": {"reason": "Reason is required when modifying quantities."}},
            status=400,
        )

    warnings = data_access.update_transfer_draft(transfer_id, needs_list_id, {
        "reason": reason,
        "items": items,
    })
    if "transfer_not_found_for_needs_list" in warnings:
        return Response(
            {"errors": {"transfer_id": "Not found for this needs list."}, "warnings": warnings},
            status=404,
        )
    if "transfer_not_found_or_not_draft" in warnings:
        return Response(
            {"errors": {"status": "Only draft transfers can be updated."}, "warnings": warnings},
            status=409,
        )

    logger.info(
        "needs_list_transfer_updated",
        extra={
            "event_type": "EXECUTION",
            "user_id": getattr(request.user, "user_id", None),
            "username": getattr(request.user, "username", None),
            "needs_list_id": needs_list_id,
            "transfer_id": transfer_id,
            "reason": reason,
        },
    )

    transfers, tw = data_access.get_transfers_for_needs_list(needs_list_id)
    warnings.extend(tw)
    updated = next((t for t in transfers if t["transfer_id"] == transfer_id), None)
    return Response({
        "transfer": updated,
        "warnings": warnings,
    })


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPermission])
def needs_list_transfer_confirm(request, needs_list_id: str, transfer_id: int):
    try:
        workflow_store.store_enabled_or_raise()
    except RuntimeError:
        return _workflow_disabled_response()

    record = workflow_store.get_record(needs_list_id)
    if not record:
        return Response({"errors": {"needs_list_id": "Not found."}}, status=404)
    scope_error = _require_record_scope(request, record, write=True)
    if scope_error:
        return scope_error

    actor = _actor_id(request)
    success, warnings = data_access.confirm_transfer_draft(transfer_id, needs_list_id, str(actor))

    if not success:
        if "transfer_not_found_for_needs_list" in warnings:
            return Response(
                {"errors": {"transfer_id": "Not found for this needs list."}, "warnings": warnings},
                status=404,
            )
        return Response(
            {"errors": {"transfer": "Transfer not found or not in draft status."},
             "warnings": warnings},
            status=409,
        )

    logger.info(
        "needs_list_transfer_confirmed",
        extra={
            "event_type": "EXECUTION",
            "user_id": getattr(request.user, "user_id", None),
            "username": getattr(request.user, "username", None),
            "needs_list_id": needs_list_id,
            "transfer_id": transfer_id,
        },
    )

    transfers, tw = data_access.get_transfers_for_needs_list(needs_list_id)
    warnings.extend(tw)
    confirmed = next((t for t in transfers if t["transfer_id"] == transfer_id), None)
    return Response({
        "transfer": confirmed,
        "warnings": warnings,
    })


@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPermission])
def needs_list_donations(request, needs_list_id: str):
    try:
        workflow_store.store_enabled_or_raise()
    except RuntimeError:
        return _workflow_disabled_response()

    record = workflow_store.get_record(needs_list_id)
    if not record:
        return Response({"errors": {"needs_list_id": "Not found."}}, status=404)
    scope_error = _require_record_scope(request, record, write=False)
    if scope_error:
        return scope_error

    snapshot = workflow_store.apply_overrides(record)
    items = snapshot.get("items", [])

    horizon_b_lines = []
    if _execution_needs_list_pk(record) is not None:
        try:
            options = allocation_dispatch.get_allocation_options(_execution_needs_list_pk(record))
            candidates_by_item: dict[int, list[dict[str, Any]]] = {}
            for group in options.get("items", []):
                donation_candidates = [
                    candidate
                    for candidate in group.get("candidates", [])
                    if str(candidate.get("source_type") or "").upper() == "DONATION"
                ]
                if donation_candidates:
                    candidates_by_item[int(group["item_id"])] = donation_candidates
            for item in items:
                horizon = item.get("horizon") or {}
                b_qty = (horizon.get("B") or {}).get("recommended_qty") or 0
                if b_qty > 0:
                    item_id = int(item["item_id"])
                    available_donations = candidates_by_item.get(item_id, [])
                    horizon_b_lines.append(
                        {
                            "item_id": item_id,
                            "item_name": item.get("item_name", f"Item {item_id}"),
                            "uom": item.get("uom_code", "EA"),
                            "required_qty": b_qty,
                            "allocated_qty": 0,
                            "available_donations": available_donations,
                        }
                    )
        except allocation_dispatch.AllocationDispatchError:
            horizon_b_lines = []

    if not horizon_b_lines:
        for item in items:
            horizon = item.get("horizon") or {}
            b_qty = (horizon.get("B") or {}).get("recommended_qty") or 0
            if b_qty > 0:
                horizon_b_lines.append({
                    "item_id": item["item_id"],
                    "item_name": item.get("item_name", f"Item {item['item_id']}"),
                    "uom": item.get("uom_code", "EA"),
                    "required_qty": b_qty,
                    "allocated_qty": 0,
                    "available_donations": [],
                })

    auth_payload = getattr(request, "auth", None)
    auth_sub = auth_payload.get("sub") if isinstance(auth_payload, dict) else None
    auth_username = auth_payload.get("preferred_username") if isinstance(auth_payload, dict) else None
    logger.info(
        "needs_list_donations",
        extra={
            "event_type": "READ",
            "timestamp": timezone.now().isoformat(),
            "user_id": (
                getattr(request.user, "keycloak_id", None)
                or getattr(request.user, "user_id", None)
                or auth_sub
            ),
            "username": getattr(request.user, "username", None) or auth_username,
            "action": "READ_DONATIONS_LIST",
            "needs_list_id": needs_list_id,
            "line_count": len(horizon_b_lines),
        },
    )

    return Response({
        "needs_list_id": needs_list_id,
        "lines": horizon_b_lines,
        "warnings": [],
    })


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPermission])
def needs_list_donations_allocate(request, needs_list_id: str):
    try:
        workflow_store.store_enabled_or_raise()
    except RuntimeError:
        return _workflow_disabled_response()

    record = workflow_store.get_record(needs_list_id)
    if not record:
        return Response({"errors": {"needs_list_id": "Not found."}}, status=404)
    scope_error = _require_record_scope(request, record, write=True)
    if scope_error:
        return scope_error

    raw_payload = request.data or {}
    metadata = raw_payload if isinstance(raw_payload, dict) else {}
    allocations = raw_payload if isinstance(raw_payload, list) else list(metadata.get("allocations") or [])
    if not allocations:
        return Response(
            {"errors": {"allocations": "Must provide a list of allocations."}},
            status=400,
        )

    commit_payload = {
        "agency_id": metadata.get("agency_id"),
        "urgency_ind": metadata.get("urgency_ind"),
        "allocations": [
            {
                **allocation,
                "quantity": allocation.get("quantity", allocation.get("allocated_qty")),
                "source_type": "DONATION",
                "source_record_id": allocation.get("donation_id") or allocation.get("source_record_id"),
            }
            for allocation in allocations
        ],
        "override_reason_code": metadata.get("override_reason_code"),
        "override_note": metadata.get("override_note"),
        "transport_mode": metadata.get("transport_mode"),
    }
    return _allocation_commit_response(
        request,
        needs_list_id,
        approval_required=False,
        payload_override=commit_payload,
    )


@api_view(["GET", "POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPermission])
def needs_list_donations_export(request, needs_list_id: str):
    try:
        workflow_store.store_enabled_or_raise()
    except RuntimeError:
        return _workflow_disabled_response()

    record = workflow_store.get_record(needs_list_id)
    if not record:
        return Response({"errors": {"needs_list_id": "Not found."}}, status=404)
    scope_error = _require_record_scope(request, record, write=False)
    if scope_error:
        return scope_error

    if request.method == "POST":
        return _enqueue_needs_list_export_job(
            request,
            needs_list_id=needs_list_id,
            record=record,
            export_kind="donation",
        )

    fmt = str(request.query_params.get("format") or "json").strip().lower()
    if fmt == "csv":
        return Response(
            {
                "errors": {
                    "format": "Synchronous CSV export has been retired. Queue this export with POST on the same endpoint."
                }
            },
            status=409,
        )
    if fmt != "json":
        return Response(
            {"errors": {"format": "Only JSON preview is available with GET."}},
            status=400,
        )
    return _needs_list_export_preview_response(
        needs_list_id=needs_list_id,
        record=record,
        export_kind="donation",
    )


@api_view(["GET", "POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPermission])
def needs_list_procurement_export(request, needs_list_id: str):
    try:
        workflow_store.store_enabled_or_raise()
    except RuntimeError:
        return _workflow_disabled_response()

    record = workflow_store.get_record(needs_list_id)
    if not record:
        return Response({"errors": {"needs_list_id": "Not found."}}, status=404)
    scope_error = _require_record_scope(request, record, write=False)
    if scope_error:
        return scope_error

    if request.method == "POST":
        return _enqueue_needs_list_export_job(
            request,
            needs_list_id=needs_list_id,
            record=record,
            export_kind="procurement",
        )

    fmt = str(request.query_params.get("format") or "json").strip().lower()
    if fmt == "csv":
        return Response(
            {
                "errors": {
                    "format": "Synchronous CSV export has been retired. Queue this export with POST on the same endpoint."
                }
            },
            status=409,
        )
    if fmt != "json":
        return Response(
            {"errors": {"format": "Only JSON preview is available with GET."}},
            status=400,
        )
    return _needs_list_export_preview_response(
        needs_list_id=needs_list_id,
        record=record,
        export_kind="procurement",
    )


needs_list_draft.required_permission = PERM_NEEDS_LIST_CREATE_DRAFT
needs_list_get.required_permission = [
    PERM_NEEDS_LIST_CREATE_DRAFT,
    PERM_NEEDS_LIST_SUBMIT,
    PERM_NEEDS_LIST_RETURN,
    PERM_NEEDS_LIST_REJECT,
    PERM_NEEDS_LIST_APPROVE,
    PERM_NEEDS_LIST_ESCALATE,
    PERM_NEEDS_LIST_EXECUTE,
    PERM_NEEDS_LIST_CANCEL,
    PERM_NEEDS_LIST_REVIEW_COMMENTS,
]
needs_list_edit_lines.required_permission = PERM_NEEDS_LIST_EDIT_LINES
needs_list_review_comments.required_permission = PERM_NEEDS_LIST_REVIEW_COMMENTS
needs_list_submit.required_permission = PERM_NEEDS_LIST_SUBMIT
needs_list_return.required_permission = PERM_NEEDS_LIST_RETURN
needs_list_reject.required_permission = PERM_NEEDS_LIST_REJECT
needs_list_approve.required_permission = PERM_NEEDS_LIST_APPROVE
needs_list_escalate.required_permission = PERM_NEEDS_LIST_ESCALATE
needs_list_review_reminder.required_permission = [
    PERM_NEEDS_LIST_APPROVE,
    PERM_NEEDS_LIST_REJECT,
    PERM_NEEDS_LIST_RETURN,
    PERM_NEEDS_LIST_ESCALATE,
]
needs_list_bulk_submit.required_permission = PERM_NEEDS_LIST_SUBMIT
needs_list_bulk_delete.required_permission = PERM_NEEDS_LIST_CANCEL
needs_list_start_preparation.required_permission = PERM_NEEDS_LIST_EXECUTE
needs_list_allocation_options.required_permission = PERM_NEEDS_LIST_EXECUTE
needs_list_allocations_current.required_permission = PERM_NEEDS_LIST_EXECUTE
needs_list_allocations_commit.required_permission = PERM_NEEDS_LIST_EXECUTE
needs_list_allocations_override_approve.required_permission = PERM_NEEDS_LIST_EXECUTE
needs_list_mark_dispatched.required_permission = PERM_NEEDS_LIST_EXECUTE
needs_list_mark_received.required_permission = PERM_NEEDS_LIST_EXECUTE
needs_list_mark_completed.required_permission = PERM_NEEDS_LIST_EXECUTE
needs_list_cancel.required_permission = PERM_NEEDS_LIST_CANCEL
needs_list_generate_transfers.required_permission = PERM_NEEDS_LIST_EXECUTE
needs_list_transfers.required_permission = PERM_NEEDS_LIST_EXECUTE
needs_list_transfer_update.required_permission = PERM_NEEDS_LIST_EXECUTE
needs_list_transfer_confirm.required_permission = PERM_NEEDS_LIST_EXECUTE
needs_list_donations.required_permission = PERM_NEEDS_LIST_EXECUTE
needs_list_donations_allocate.required_permission = PERM_NEEDS_LIST_EXECUTE
needs_list_donations_export.required_permission = PERM_NEEDS_LIST_EXECUTE
needs_list_waybill.required_permission = PERM_NEEDS_LIST_EXECUTE
needs_list_procurement_export.required_permission = PERM_NEEDS_LIST_EXECUTE
criticality_event_overrides.required_permission = {
    "GET": [PERM_CRITICALITY_OVERRIDE_VIEW, PERM_CRITICALITY_OVERRIDE_MANAGE],
    "POST": PERM_CRITICALITY_OVERRIDE_MANAGE,
}
criticality_event_override_detail.required_permission = PERM_CRITICALITY_OVERRIDE_MANAGE
criticality_hazard_defaults.required_permission = {
    "GET": [PERM_CRITICALITY_HAZARD_VIEW, PERM_CRITICALITY_HAZARD_MANAGE, PERM_CRITICALITY_HAZARD_APPROVE],
    "POST": PERM_CRITICALITY_HAZARD_MANAGE,
}
criticality_hazard_default_detail.required_permission = PERM_CRITICALITY_HAZARD_MANAGE
criticality_hazard_default_submit.required_permission = PERM_CRITICALITY_HAZARD_MANAGE
criticality_hazard_default_approve.required_permission = PERM_CRITICALITY_HAZARD_APPROVE
criticality_hazard_default_reject.required_permission = PERM_CRITICALITY_HAZARD_APPROVE
storage_assignment_options.required_permission = [
    PERM_MASTERDATA_VIEW,
    PERM_MASTERDATA_EDIT,
]
assign_storage_location.required_permission = [PERM_NEEDS_LIST_EXECUTE, PERM_MASTERDATA_EDIT]
inventory_repackaging.required_permission = {
    "GET": [PERM_MASTERDATA_VIEW, PERM_NEEDS_LIST_EXECUTE],
    "POST": [PERM_NEEDS_LIST_EXECUTE, PERM_MASTERDATA_EDIT],
}
inventory_repackaging_detail.required_permission = [PERM_MASTERDATA_VIEW, PERM_NEEDS_LIST_EXECUTE]

for view_func in (
    storage_assignment_options,
    assign_storage_location,
    inventory_repackaging,
    inventory_repackaging_detail,
    criticality_event_overrides,
    criticality_event_override_detail,
    criticality_hazard_defaults,
    criticality_hazard_default_detail,
    criticality_hazard_default_submit,
    criticality_hazard_default_approve,
    criticality_hazard_default_reject,
    needs_list_draft,
    needs_list_get,
    needs_list_edit_lines,
    needs_list_review_comments,
    needs_list_submit,
    needs_list_return,
    needs_list_reject,
    needs_list_approve,
    needs_list_escalate,
    needs_list_review_reminder,
    needs_list_bulk_submit,
    needs_list_bulk_delete,
    needs_list_start_preparation,
    needs_list_allocation_options,
    needs_list_allocations_current,
    needs_list_allocations_commit,
    needs_list_allocations_override_approve,
    needs_list_mark_dispatched,
    needs_list_mark_received,
    needs_list_mark_completed,
    needs_list_cancel,
    needs_list_generate_transfers,
    needs_list_transfers,
    needs_list_transfer_update,
    needs_list_transfer_confirm,
    needs_list_donations,
    needs_list_donations_allocate,
    needs_list_donations_export,
    needs_list_waybill,
    needs_list_procurement_export,
):
    if hasattr(view_func, "cls"):
        view_func.cls.required_permission = view_func.required_permission


# =============================================================================
# Procurement Views (Horizon C)
# =============================================================================

@api_view(["POST", "GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([ProcurementPermission])
def procurement_list_create(request):
    """List procurement orders (GET) or create a new one (POST)."""
    if request.method == "GET":
        errors: Dict[str, str] = {}
        filters: Dict[str, Any] = {}
        allowed_statuses = {
            str(status_code).strip().upper()
            for status_code, _label in Procurement.STATUS_CHOICES
        }
        status_filter = str(request.query_params.get("status") or "").strip().upper()
        if status_filter:
            if status_filter not in allowed_statuses:
                errors["status"] = (
                    "Must be one of: " + ", ".join(sorted(allowed_statuses)) + "."
                )
            else:
                filters["status"] = status_filter
        for field_name in ("warehouse_id", "event_id", "supplier_id"):
            raw_value = request.query_params.get(field_name)
            if raw_value is None:
                continue
            parsed_value = _parse_positive_int(raw_value, field_name, errors)
            if parsed_value is not None:
                filters[field_name] = parsed_value
        needs_list_id = str(request.query_params.get("needs_list_id") or "").strip()
        if needs_list_id:
            filters["needs_list_id"] = needs_list_id
        include_items = _parse_optional_bool(
            request.query_params.get("include_items"),
            "include_items",
            errors,
        )
        if errors:
            return Response({"errors": errors}, status=400)
        include_items = bool(include_items)
        try:
            page, page_size = _parse_pagination_params(
                request,
                default_page_size=100,
                max_page_size=200,
            )
        except PaginationValidationError as exc:
            return Response({"errors": exc.errors}, status=400)
        scoped_warehouse_ids = _accessible_read_warehouse_ids(request)
        procurements, count = procurement_service.list_procurements(
            filters or None,
            allowed_warehouse_ids=scoped_warehouse_ids,
            include_items=include_items,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
        return Response(
            _build_paginated_payload(
                request,
                items=procurements,
                total_count=count,
                page=page,
                page_size=page_size,
                result_key="procurements",
            )
        )

    # POST - create
    data = request.data
    actor = _actor_id(request)
    try:
        needs_list_id = data.get("needs_list_id")
        if needs_list_id:
            result = procurement_service.create_procurement_from_needs_list(
                needs_list_id, actor
            )
            _log_audit_event(
                "procurement_created_from_needs_list",
                request,
                event_type="CREATE",
                action="CREATE_PROCUREMENT_FROM_NEEDS_LIST",
                procurement_id=result.get("procurement_id"),
                from_status=None,
                to_status=result.get("status_code"),
                needs_list_id=needs_list_id,
                procurement_method=result.get("procurement_method"),
            )
        else:
            result = procurement_service.create_procurement_standalone(
                event_id=int(data["event_id"]),
                target_warehouse_id=int(data["target_warehouse_id"]),
                items=data.get("items", []),
                actor_id=actor,
                procurement_method=data.get("procurement_method", "SINGLE_SOURCE"),
                supplier_id=data.get("supplier_id"),
                notes=data.get("notes", ""),
            )
            _log_audit_event(
                "procurement_created_standalone",
                request,
                event_type="CREATE",
                action="CREATE_PROCUREMENT_STANDALONE",
                procurement_id=result.get("procurement_id"),
                from_status=None,
                to_status=result.get("status_code"),
                event_id=result.get("event_id"),
                target_warehouse_id=result.get("target_warehouse_id"),
                supplier_id=(result.get("supplier") or {}).get("supplier_id"),
                procurement_method=result.get("procurement_method"),
                notes=data.get("notes", ""),
            )
        return Response(result, status=201)
    except ProcurementError as exc:
        status_code = 404 if exc.code == "not_found" else 400
        return Response({"errors": {exc.code: exc.message}}, status=status_code)
    except (KeyError, ValueError, TypeError) as exc:
        return Response(
            {"errors": {"validation": f"Invalid request data: {exc}"}}, status=400
        )


@api_view(["GET", "PATCH"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([ProcurementPermission])
def procurement_detail(request, procurement_id: int):
    """Get (GET) or update (PATCH) a procurement order."""
    try:
        if request.method == "GET":
            result = procurement_service.get_procurement(procurement_id)
            return Response(result)
        else:
            result = procurement_service.update_procurement_draft(
                procurement_id, request.data, _actor_id(request)
            )
            return Response(result)
    except ProcurementError as exc:
        status_code = 404 if exc.code == "not_found" else 400
        return Response({"errors": {exc.code: exc.message}}, status=status_code)


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([ProcurementPermission])
def procurement_submit(request, procurement_id: int):
    """Submit procurement for approval."""
    try:
        current = procurement_service.get_procurement(procurement_id)
        result = procurement_service.submit_procurement(
            procurement_id, _actor_id(request)
        )
        _log_audit_event(
            "procurement_submitted",
            request,
            event_type="STATE_CHANGE",
            action="SUBMIT_PROCUREMENT",
            procurement_id=procurement_id,
            from_status=current.get("status_code"),
            to_status=result.get("status_code"),
            item_count=len(result.get("items", [])),
            total_value=result.get("total_value"),
        )
        return Response(result)
    except ProcurementError as exc:
        status_code = 404 if exc.code == "not_found" else 400
        return Response({"errors": {exc.code: exc.message}}, status=status_code)


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([ProcurementPermission])
def procurement_approve(request, procurement_id: int):
    """Approve a procurement order."""
    try:
        actor = _actor_id(request)
        proc = Procurement.objects.get(procurement_id=procurement_id)
        submitter_id = (
            proc.update_by_id if proc.status_code == "PENDING_APPROVAL" else None
        ) or proc.create_by_id
        normalized_submitter = _normalize_actor(submitter_id)
        normalized_actor = _normalize_actor(actor)
        if not normalized_submitter or normalized_submitter == normalized_actor:
            return Response(
                {"errors": {"approval": "Approver must be different from submitter."}},
                status=409,
            )
        notes = request.data.get("notes", "")
        result = procurement_service.approve_procurement(
            procurement_id,
            actor,
            notes=notes,
        )
        _log_audit_event(
            "procurement_approved",
            request,
            event_type="STATE_CHANGE",
            action="APPROVE_PROCUREMENT",
            procurement_id=procurement_id,
            from_status=proc.status_code,
            to_status=result.get("status_code"),
            notes=notes,
        )
        return Response(result)
    except Procurement.DoesNotExist:
        return Response({"errors": {"not_found": "Procurement not found."}}, status=404)
    except ProcurementError as exc:
        status_code = 404 if exc.code == "not_found" else 400
        return Response({"errors": {exc.code: exc.message}}, status=status_code)


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([ProcurementPermission])
def procurement_reject(request, procurement_id: int):
    """Reject a procurement order."""
    try:
        reason = str((request.data or {}).get("reason") or "").strip()
        if not reason:
            return Response({"errors": {"reason": "Reason is required."}}, status=400)

        current = procurement_service.get_procurement(procurement_id)
        result = procurement_service.reject_procurement(
            procurement_id, _actor_id(request), reason
        )
        _log_audit_event(
            "procurement_rejected",
            request,
            event_type="STATE_CHANGE",
            action="REJECT_PROCUREMENT",
            procurement_id=procurement_id,
            from_status=current.get("status_code"),
            to_status=result.get("status_code"),
            reason=reason,
        )
        return Response(result)
    except ProcurementError as exc:
        status_code = 404 if exc.code == "not_found" else 400
        return Response({"errors": {exc.code: exc.message}}, status=status_code)


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([ProcurementPermission])
def procurement_mark_ordered(request, procurement_id: int):
    """Mark procurement as ordered with a PO number."""
    try:
        current = procurement_service.get_procurement(procurement_id)
        po_number = request.data.get("po_number", "")
        result = procurement_service.mark_ordered(
            procurement_id, po_number, _actor_id(request)
        )
        _log_audit_event(
            "procurement_marked_ordered",
            request,
            event_type="STATE_CHANGE",
            action="MARK_PROCUREMENT_ORDERED",
            procurement_id=procurement_id,
            from_status=current.get("status_code"),
            to_status=result.get("status_code"),
            po_number=result.get("po_number") or po_number,
        )
        return Response(result)
    except ProcurementError as exc:
        status_code = 404 if exc.code == "not_found" else 400
        return Response({"errors": {exc.code: exc.message}}, status=status_code)


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([ProcurementPermission])
def procurement_mark_shipped(request, procurement_id: int):
    """Mark procurement as shipped."""
    try:
        current = procurement_service.get_procurement(procurement_id)
        shipped_at = request.data.get("shipped_at")
        expected_arrival = request.data.get("expected_arrival")
        result = procurement_service.mark_shipped(
            procurement_id,
            shipped_at=shipped_at,
            expected_arrival=expected_arrival,
            actor_id=_actor_id(request),
        )
        _log_audit_event(
            "procurement_marked_shipped",
            request,
            event_type="STATE_CHANGE",
            action="MARK_PROCUREMENT_SHIPPED",
            procurement_id=procurement_id,
            from_status=current.get("status_code"),
            to_status=result.get("status_code"),
            shipped_at=result.get("shipped_at") or shipped_at,
            expected_arrival=result.get("expected_arrival") or expected_arrival,
        )
        return Response(result)
    except ProcurementError as exc:
        status_code = 404 if exc.code == "not_found" else 400
        return Response({"errors": {exc.code: exc.message}}, status=status_code)


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([ProcurementPermission])
def procurement_receive(request, procurement_id: int):
    """Record received quantities for procurement items."""
    try:
        current = procurement_service.get_procurement(procurement_id)
        receipts = request.data.get("receipts", [])
        received_qty_total = 0.0
        for receipt in receipts:
            try:
                received_qty_total += float(receipt.get("received_qty") or 0)
            except (TypeError, ValueError):
                continue
        result = procurement_service.receive_items(
            procurement_id, receipts, _actor_id(request)
        )
        _log_audit_event(
            "procurement_received",
            request,
            event_type="STATE_CHANGE",
            action="RECEIVE_PROCUREMENT_ITEMS",
            procurement_id=procurement_id,
            from_status=current.get("status_code"),
            to_status=result.get("status_code"),
            receipt_count=len(receipts),
            received_qty_total=round(received_qty_total, 2),
        )
        return Response(result)
    except ProcurementError as exc:
        status_code = 404 if exc.code == "not_found" else 400
        return Response({"errors": {exc.code: exc.message}}, status=status_code)


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([ProcurementPermission])
def procurement_cancel(request, procurement_id: int):
    """Cancel a procurement order."""
    try:
        reason = str((request.data or {}).get("reason") or "").strip()
        if not reason:
            return Response({"errors": {"reason": "Reason is required."}}, status=400)

        current = procurement_service.get_procurement(procurement_id)
        result = procurement_service.cancel_procurement(
            procurement_id, reason, _actor_id(request)
        )
        _log_audit_event(
            "procurement_cancelled",
            request,
            event_type="STATE_CHANGE",
            action="CANCEL_PROCUREMENT",
            procurement_id=procurement_id,
            from_status=current.get("status_code"),
            to_status=result.get("status_code"),
            reason=reason,
        )
        return Response(result)
    except ProcurementError as exc:
        status_code = 404 if exc.code == "not_found" else 400
        return Response({"errors": {exc.code: exc.message}}, status=status_code)


# Supplier Views


@api_view(["GET", "POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([ProcurementPermission])
def supplier_list_create(request):
    """List suppliers (GET) or create a new one (POST)."""
    if request.method == "GET":
        suppliers = procurement_service.list_suppliers()
        return Response({"suppliers": suppliers, "count": len(suppliers)})

    try:
        result = procurement_service.create_supplier(request.data, _actor_id(request))
        _log_audit_event(
            "supplier_created",
            request,
            event_type="CREATE",
            action="CREATE_SUPPLIER",
            supplier_id=result.get("supplier_id"),
            from_status=None,
            to_status=result.get("status_code"),
            supplier_code=result.get("supplier_code"),
        )
        return Response(result, status=201)
    except ProcurementError as exc:
        return Response({"errors": {exc.code: exc.message}}, status=400)


@api_view(["GET", "PATCH"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([ProcurementPermission])
def supplier_detail(request, supplier_id: int):
    """Get (GET) or update (PATCH) a supplier."""
    try:
        if request.method == "GET":
            result = procurement_service.get_supplier(supplier_id)
            return Response(result)
        else:
            current = procurement_service.get_supplier(supplier_id)
            result = procurement_service.update_supplier(
                supplier_id, request.data, _actor_id(request)
            )
            _log_audit_event(
                "supplier_updated",
                request,
                event_type="UPDATE",
                action="UPDATE_SUPPLIER",
                supplier_id=supplier_id,
                from_status=current.get("status_code"),
                to_status=result.get("status_code"),
                supplier_code=result.get("supplier_code"),
            )
            return Response(result)
    except ProcurementError as exc:
        status_code = 404 if exc.code == "not_found" else 400
        return Response({"errors": {exc.code: exc.message}}, status=status_code)


# Procurement Permission Assignments

# Combined-method views use method-specific permission mappings.
procurement_list_create.required_permission = {
    "GET": PERM_PROCUREMENT_VIEW,
    "POST": PERM_PROCUREMENT_CREATE,
}
procurement_detail.required_permission = {
    "GET": PERM_PROCUREMENT_VIEW,
    "PATCH": PERM_PROCUREMENT_EDIT,
}
procurement_submit.required_permission = PERM_PROCUREMENT_SUBMIT
procurement_approve.required_permission = PERM_PROCUREMENT_APPROVE
procurement_reject.required_permission = PERM_PROCUREMENT_REJECT
procurement_mark_ordered.required_permission = PERM_PROCUREMENT_ORDER
procurement_mark_shipped.required_permission = PERM_PROCUREMENT_ORDER
procurement_receive.required_permission = PERM_PROCUREMENT_RECEIVE
procurement_cancel.required_permission = PERM_PROCUREMENT_CANCEL

supplier_list_create.required_permission = {
    "GET": PERM_PROCUREMENT_VIEW,
    "POST": PERM_PROCUREMENT_CREATE,
}
supplier_detail.required_permission = {
    "GET": PERM_PROCUREMENT_VIEW,
    "PATCH": PERM_PROCUREMENT_EDIT,
}

for _pview in (
    procurement_list_create,
    procurement_detail,
    procurement_submit,
    procurement_approve,
    procurement_reject,
    procurement_mark_ordered,
    procurement_mark_shipped,
    procurement_receive,
    procurement_cancel,
    supplier_list_create,
    supplier_detail,
):
    if hasattr(_pview, "cls"):
        _pview.cls.required_permission = _pview.required_permission


