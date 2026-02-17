import logging
import re
import math
import json
from pathlib import Path
from threading import Lock
from typing import Any, Dict

from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from api.authentication import LegacyCompatAuthentication
from api.permissions import NeedsListPermission, NeedsListPreviewPermission
from api.rbac import (
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
)
from replenishment import rules, workflow_store as workflow_store_file, workflow_store_db
from replenishment.services import approval as approval_service
from replenishment.services import data_access, needs_list

logger = logging.getLogger("dmis.audit")
_STOCK_STATE_LOCK = Lock()

PENDING_APPROVAL_STATUSES = {"SUBMITTED", "PENDING_APPROVAL", "PENDING", "UNDER_REVIEW"}
_DB_STATUS_TRANSITIONS = {
    "SUBMITTED": "PENDING_APPROVAL",
    "MODIFIED": "RETURNED",
    "ESCALATED": "UNDER_REVIEW",
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


def _use_db_workflow_store() -> bool:
    if not getattr(settings, "AUTH_USE_DB_RBAC", False):
        return False
    engine = str(settings.DATABASES.get("default", {}).get("ENGINE", ""))
    return engine.endswith("postgresql")


class _WorkflowStoreProxy:
    def __getattr__(self, name: str):
        module = workflow_store_db if _use_db_workflow_store() else workflow_store_file
        return getattr(module, name)


workflow_store = _WorkflowStoreProxy()


def _workflow_target_status(status: str) -> str:
    normalized = str(status or "").upper()
    if _use_db_workflow_store():
        return _DB_STATUS_TRANSITIONS.get(normalized, normalized)
    return normalized


def _status_matches(current_status: object, *expected_statuses: str) -> bool:
    current = str(current_status or "").upper()
    accepted: set[str] = set()
    for status in expected_statuses:
        normalized = str(status or "").upper()
        if not normalized:
            continue
        accepted.add(normalized)
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


def _read_stock_state_store() -> Dict[str, Any]:
    store_path = _stock_state_store_path()
    if not store_path.exists():
        return {}
    try:
        raw = store_path.read_text(encoding="utf-8")
        parsed = json.loads(raw)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("Failed reading stock-state cache file %s: %s", store_path, exc)
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _write_stock_state_store(store: Dict[str, Any]) -> None:
    store_path = _stock_state_store_path()
    try:
        store_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = store_path.with_suffix(store_path.suffix + ".tmp")
        temp_path.write_text(json.dumps(store), encoding="utf-8")
        temp_path.replace(store_path)
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
    with _STOCK_STATE_LOCK:
        store = _read_stock_state_store()
        store[scope_key] = payload
        _write_stock_state_store(store)


def _load_stock_state_snapshot(
    event_id: int,
    warehouse_id: int,
    phase: str,
) -> Dict[str, Any] | None:
    scope_key = _stock_state_scope_key(event_id, warehouse_id, phase)
    with _STOCK_STATE_LOCK:
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
        records = workflow_store.list_records()
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
    selected_method = (
        str(record.get("selected_method") or snapshot.get("selected_method") or "")
        .strip()
        .upper()
        or None
    )
    total_required_qty, total_estimated_cost, approval_warnings = (
        approval_service.compute_needs_list_totals(snapshot.get("items") or [])
    )
    if selected_method == "A":
        approval_warnings = []
    approval, approval_warnings_extra, approval_rationale = (
        approval_service.determine_approval_tier(
            str(record.get("phase") or "BASELINE"),
            total_estimated_cost,
            bool(approval_warnings),
            selected_method=selected_method,
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
    return {
        "total_required_qty": round(total_required_qty, 2),
        "total_estimated_cost": None if parsed_cost is None else round(parsed_cost, 2),
        "approval": approval,
        "warnings": warnings,
        "rationale": str(summary.get("rationale") or ""),
        "escalation_required": bool(summary.get("escalation_required")),
    }


def _approval_summary_for_record(
    record: Dict[str, Any],
    snapshot: Dict[str, Any],
) -> Dict[str, Any]:
    status = str(record.get("status") or "").upper()
    persisted_summary = _normalize_submitted_approval_summary(
        record.get("submitted_approval_summary")
    )
    if status not in {"DRAFT", "MODIFIED", "RETURNED"} and persisted_summary:
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

    windows = rules.get_phase_windows(phase)
    demand_window_hours = int(windows["demand_hours"])
    planning_window_hours = int(windows["planning_hours"])
    planning_window_days = planning_window_hours / 24

    horizon_a_setting = getattr(settings, "NEEDS_HORIZON_A_DAYS", 7)
    try:
        horizon_a_hours = int(horizon_a_setting) * 24
    except (TypeError, ValueError):
        logger.warning(
            "Invalid NEEDS_HORIZON_A_DAYS setting %r, defaulting to 7",
            horizon_a_setting,
        )
        horizon_a_hours = 7 * 24
    horizon_b_days_setting = getattr(settings, "NEEDS_HORIZON_B_DAYS", None)
    if horizon_b_days_setting is None:
        horizon_b_hours = max(planning_window_hours - horizon_a_hours, 0)
    else:
        try:
            horizon_b_hours = int(horizon_b_days_setting or 0) * 24
        except (TypeError, ValueError):
            logger.warning(
                "Invalid NEEDS_HORIZON_B_DAYS setting %r, defaulting to 0",
                horizon_b_days_setting,
            )
            horizon_b_hours = 0

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
        burn_source=burn_source,
        as_of_dt=as_of_dt,
        phase=phase,
        inventory_as_of=inventory_as_of,
        base_warnings=base_warnings,
        item_names=item_names,
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


def _serialize_workflow_record(record: Dict[str, Any], include_overrides: bool = True) -> Dict[str, Any]:
    snapshot = (
        workflow_store.apply_overrides(record)
        if include_overrides
        else dict(record.get("snapshot") or {})
    )
    approval_summary = _approval_summary_for_record(record, snapshot)
    selected_method = (
        str(record.get("selected_method") or snapshot.get("selected_method") or "")
        .strip()
        .upper()
        or None
    )
    response = dict(snapshot)
    response.update(
        {
            "needs_list_id": record.get("needs_list_id"),
            "status": record.get("status"),
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
            "selected_method": record.get("selected_method"),
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
            "return_reason": record.get("return_reason"),
            "return_reason_code": record.get("return_reason_code"),
            "reject_reason": record.get("reject_reason"),
            "approval_summary": approval_summary,
        }
    )
    return response


def _workflow_disabled_response() -> Response:
    return Response(
        {"errors": {"workflow": "Workflow dev store is disabled."}},
        status=501,
    )


@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPreviewPermission])
def needs_list_list(request):
    """
    List needs lists, optionally filtered by status.
    Query params:
        status - comma-separated list of statuses (e.g. SUBMITTED,PENDING_APPROVAL,UNDER_REVIEW)
    """
    try:
        workflow_store.store_enabled_or_raise()
    except RuntimeError:
        return _workflow_disabled_response()

    status_param = request.query_params.get("status")
    statuses = [s.strip() for s in status_param.split(",") if s.strip()] if status_param else None

    records = workflow_store.list_records(statuses)
    serialized = [_serialize_workflow_record(r) for r in records]
    # Sort by submitted_at ascending (oldest first), nulls last
    serialized.sort(key=lambda r: r.get("submitted_at") or "9999")

    return Response({"needs_lists": serialized, "count": len(serialized)})


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


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPreviewPermission])
def needs_list_preview(request):
    payload = request.data or {}
    response, errors = _build_preview_response(payload)
    if errors:
        return Response({"errors": errors}, status=400)

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
    selected_item_keys = _parse_selected_item_keys(payload.get("selected_item_keys"), errors)
    selected_method_raw = payload.get("selected_method")
    selected_method = None
    if selected_method_raw is not None:
        selected_method = str(selected_method_raw).strip().upper()
        if selected_method not in {"A", "B", "C"}:
            errors["selected_method"] = "Must be one of: A, B, C."

    if errors:
        return Response({"errors": errors}, status=400)

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

    response = _serialize_workflow_record(record, include_overrides=True)
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

    status = str(record.get("status") or "").upper()
    if not _status_matches(status, "DRAFT", "MODIFIED"):
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

    previous_status = str(record.get("status") or "").upper()
    if not _status_matches(previous_status, "DRAFT", "MODIFIED"):
        return Response({"errors": {"status": "Only draft or modified needs lists can be submitted."}}, status=409)

    submit_empty_allowed = bool((request.data or {}).get("submit_empty_allowed", False))
    item_count = len(record.get("snapshot", {}).get("items") or [])
    if item_count == 0 and not submit_empty_allowed:
        return Response({"errors": {"items": "Cannot submit an empty needs list."}}, status=409)

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
    required_roles = approval_service.required_roles_for_approval(approval)

    from api.rbac import resolve_roles_and_permissions

    roles, _ = resolve_roles_and_permissions(request, request.user)
    role_set = {role.upper() for role in roles}
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

    target_status = _workflow_target_status("ESCALATED")
    record = workflow_store.transition_status(record, target_status, actor, reason=reason)
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
    try:
        workflow_store.store_enabled_or_raise()
    except RuntimeError:
        return _workflow_disabled_response()

    record = workflow_store.get_record(needs_list_id)
    if not record:
        return Response({"errors": {"needs_list_id": "Not found."}}, status=404)

    if record.get("status") != "APPROVED":
        return Response({"errors": {"status": "Needs list must be approved."}}, status=409)

    target_status = _workflow_target_status("IN_PREPARATION")
    record = workflow_store.transition_status(record, target_status, _actor_id(request))
    workflow_store.update_record(needs_list_id, record)

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
    try:
        workflow_store.store_enabled_or_raise()
    except RuntimeError:
        return _workflow_disabled_response()

    record = workflow_store.get_record(needs_list_id)
    if not record:
        return Response({"errors": {"needs_list_id": "Not found."}}, status=404)

    if not _status_matches(record.get("status"), "IN_PREPARATION"):
        return Response({"errors": {"status": "Needs list must be in preparation."}}, status=409)
    if not record.get("prep_started_at"):
        return Response({"errors": {"status": "Needs list preparation must be started."}}, status=409)
    if record.get("dispatched_at"):
        return Response({"errors": {"status": "Needs list already dispatched."}}, status=409)

    from_status = str(record.get("status") or "").upper()
    target_status = _workflow_target_status("DISPATCHED")
    record = workflow_store.transition_status(record, target_status, _actor_id(request))
    workflow_store.update_record(needs_list_id, record)

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
    try:
        workflow_store.store_enabled_or_raise()
    except RuntimeError:
        return _workflow_disabled_response()

    record = workflow_store.get_record(needs_list_id)
    if not record:
        return Response({"errors": {"needs_list_id": "Not found."}}, status=404)

    if not _status_matches(record.get("status"), "DISPATCHED"):
        return Response({"errors": {"status": "Needs list must be dispatched."}}, status=409)
    if not record.get("dispatched_at"):
        return Response({"errors": {"status": "Needs list must be dispatched."}}, status=409)
    if record.get("received_at"):
        return Response({"errors": {"status": "Needs list already received."}}, status=409)

    from_status = str(record.get("status") or "").upper()
    target_status = _workflow_target_status("RECEIVED")
    record = workflow_store.transition_status(record, target_status, _actor_id(request))
    workflow_store.update_record(needs_list_id, record)

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
    try:
        workflow_store.store_enabled_or_raise()
    except RuntimeError:
        return _workflow_disabled_response()

    record = workflow_store.get_record(needs_list_id)
    if not record:
        return Response({"errors": {"needs_list_id": "Not found."}}, status=404)

    if not _status_matches(record.get("status"), "RECEIVED"):
        return Response({"errors": {"status": "Needs list must be received."}}, status=409)
    if not record.get("received_at"):
        return Response({"errors": {"status": "Needs list must be received."}}, status=409)
    if record.get("completed_at"):
        return Response({"errors": {"status": "Needs list already completed."}}, status=409)

    from_status = str(record.get("status") or "").upper()
    target_status = _workflow_target_status("COMPLETED")
    record = workflow_store.transition_status(record, target_status, _actor_id(request))
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

    return Response(_serialize_workflow_record(record, include_overrides=True))


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPermission])
def needs_list_cancel(request, needs_list_id: str):
    try:
        workflow_store.store_enabled_or_raise()
    except RuntimeError:
        return _workflow_disabled_response()

    record = workflow_store.get_record(needs_list_id)
    if not record:
        return Response({"errors": {"needs_list_id": "Not found."}}, status=404)

    if not _status_matches(record.get("status"), "APPROVED", "IN_PREPARATION"):
        return Response({"errors": {"status": "Cancel not allowed in current state."}}, status=409)

    reason = (request.data or {}).get("reason")
    if not reason:
        return Response({"errors": {"reason": "Reason is required."}}, status=400)

    from_status = record.get("status")
    record = workflow_store.transition_status(
        record, "CANCELLED", _actor_id(request), reason=reason
    )
    workflow_store.update_record(needs_list_id, record)

    logger.info(
        "needs_list_cancelled",
        extra={
            "event_type": "STATE_CHANGE",
            "user_id": getattr(request.user, "user_id", None),
            "username": getattr(request.user, "username", None),
            "needs_list_id": needs_list_id,
            "from_status": from_status,
            "to_status": "CANCELLED",
            "reason": reason,
        },
    )

    return Response(_serialize_workflow_record(record, include_overrides=True))


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
needs_list_start_preparation.required_permission = PERM_NEEDS_LIST_EXECUTE
needs_list_mark_dispatched.required_permission = PERM_NEEDS_LIST_EXECUTE
needs_list_mark_received.required_permission = PERM_NEEDS_LIST_EXECUTE
needs_list_mark_completed.required_permission = PERM_NEEDS_LIST_EXECUTE
needs_list_cancel.required_permission = PERM_NEEDS_LIST_CANCEL

for view_func in (
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
    needs_list_start_preparation,
    needs_list_mark_dispatched,
    needs_list_mark_received,
    needs_list_mark_completed,
    needs_list_cancel,
):
    if hasattr(view_func, "cls"):
        view_func.cls.required_permission = view_func.required_permission
