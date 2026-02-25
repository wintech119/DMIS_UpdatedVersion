import csv
import io
import logging
import re
import math
import json
import os
from datetime import timedelta
from pathlib import Path
from contextlib import contextmanager
from typing import Any, Dict

from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from api.authentication import LegacyCompatAuthentication
from api.permissions import NeedsListPermission, NeedsListPreviewPermission, ProcurementPermission
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
from replenishment import rules, workflow_store as workflow_store_file, workflow_store_db
from replenishment.models import Procurement
from replenishment.services import approval as approval_service
from replenishment.services import data_access, needs_list
from replenishment.services import procurement as procurement_service
from replenishment.services.procurement import ProcurementError

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
_CLOSED_NEEDS_LIST_STATUSES = {"FULFILLED", "COMPLETED", "CANCELLED", "SUPERSEDED", "REJECTED"}

def _use_db_workflow_store() -> bool:
    if not getattr(settings, "AUTH_USE_DB_RBAC", False):
        return False
    engine = str(settings.DATABASES.get("default", {}).get("ENGINE", "")).lower()
    return "postgresql" in engine


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
        }
    )
    return response


def _normalize_status_for_ui(status: object) -> str:
    normalized = str(status or "").strip().upper()
    if normalized in {"SUBMITTED", "PENDING", "UNDER_REVIEW"}:
        return "PENDING_APPROVAL"
    if normalized in {"IN_PREPARATION", "DISPATCHED", "RECEIVED"}:
        return "IN_PROGRESS"
    if normalized == "COMPLETED":
        return "FULFILLED"
    return normalized


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

        if ui == "PENDING_APPROVAL":
            store_filters.update({"PENDING_APPROVAL", "SUBMITTED", "PENDING", "UNDER_REVIEW"})
        elif ui == "IN_PROGRESS":
            store_filters.update({"IN_PROGRESS", "IN_PREPARATION", "DISPATCHED", "RECEIVED"})
        elif ui == "FULFILLED":
            store_filters.update({"FULFILLED", "COMPLETED"})
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


def _horizon_item_qty(item: Dict[str, Any], horizon_key: str) -> float:
    horizon = item.get("horizon")
    if isinstance(horizon, dict):
        bucket = horizon.get(horizon_key)
        if isinstance(bucket, dict):
            return max(_to_float_or_none(bucket.get("recommended_qty")) or 0.0, 0.0)
    return 0.0


def _normalize_horizon_key(value: object) -> str | None:
    normalized = str(value or "").strip().upper()
    if normalized in {"A", "B", "C"}:
        return normalized
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
        "reference_number": str(record.get("needs_list_no") or record.get("needs_list_id") or ""),
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
    page = _parse_positive_int(request.query_params.get("page"), "page", {}) or 1
    page_size = _parse_positive_int(request.query_params.get("page_size"), "page_size", {}) or default_page_size
    page_size = max(1, min(page_size, max_page_size))

    total_count = len(items)
    start = (page - 1) * page_size
    end = start + page_size
    page_items = items[start:end] if start < total_count else []

    next_url = None
    prev_url = None
    query = request.query_params.copy()
    query["page_size"] = str(page_size)

    if end < total_count:
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
        "results": page_items,
    }


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
    List needs lists, optionally filtered by query params.
    Query params:
        status - comma-separated list of statuses (e.g. SUBMITTED,PENDING_APPROVAL,UNDER_REVIEW)
        mine - when true, only records authored/submitted/updated by current actor
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

    records = workflow_store.list_records(statuses)
    actor = _normalize_actor(_actor_id(request))
    filtered_records: list[Dict[str, Any]] = []
    for record in records:
        status_value = str(record.get("status") or "").upper()
        if not include_closed and status_value in _CLOSED_NEEDS_LIST_STATUSES:
            continue

        if mine_only:
            if not actor:
                continue
            if not any(
                _normalize_actor(candidate) == actor
                for candidate in (
                    record.get("created_by"),
                    record.get("submitted_by"),
                    record.get("updated_by"),
                )
                if candidate
            ):
                continue

        if event_id_filter is not None:
            record_event_id = _to_int_or_none(record.get("event_id"))
            if record_event_id != event_id_filter:
                continue

        if warehouse_id_filter is not None:
            record_warehouse_id = _to_int_or_none(record.get("warehouse_id"))
            record_warehouse_ids = {
                _to_int_or_none(value)
                for value in (record.get("warehouse_ids") or [])
            }
            if (
                record_warehouse_id != warehouse_id_filter
                and warehouse_id_filter not in record_warehouse_ids
            ):
                continue

        if phase_filter and str(record.get("phase") or "").strip().upper() != phase_filter:
            continue

        filtered_records.append(record)

    serialized = [_serialize_workflow_record(r) for r in filtered_records]
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
    Paginated, filterable summaries for the current actor's submissions.
    """
    try:
        workflow_store.store_enabled_or_raise()
    except RuntimeError:
        return _workflow_disabled_response()

    actor = _normalize_actor(_actor_id(request))
    if not actor:
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

    records = workflow_store.list_records(store_status_filters)
    summaries: list[Dict[str, Any]] = []
    for record in records:
        if not any(
            _normalize_actor(candidate) == actor
            for candidate in (
                record.get("created_by"),
                record.get("submitted_by"),
                record.get("updated_by"),
            )
            if candidate
        ):
            continue

        serialized = _serialize_workflow_record(record, include_overrides=True)
        summary = _serialize_submission_summary(serialized)
        summary_status = str(summary.get("status") or "").strip().upper()
        if ui_status_filters and summary_status not in ui_status_filters:
            continue

        if event_id_filter is not None and summary.get("event", {}).get("id") != event_id_filter:
            continue
        if warehouse_id_filter is not None and summary.get("warehouse", {}).get("id") != warehouse_id_filter:
            continue
        if method_filter is not None:
            row_method = _normalize_horizon_key(summary.get("selected_method"))
            if row_method != method_filter:
                continue

        summary_ts = _parse_iso_datetime(summary.get("last_updated_at"))
        if date_from and (summary_ts is None or summary_ts < date_from):
            continue
        if date_to and (summary_ts is None or summary_ts > date_to):
            continue

        summaries.append(summary)

    reverse = sort_order == "desc"
    if sort_by == "status":
        summaries.sort(key=lambda row: str(row.get("status") or ""), reverse=reverse)
    elif sort_by == "warehouse":
        summaries.sort(
            key=lambda row: str((row.get("warehouse") or {}).get("name") or ""),
            reverse=reverse,
        )
    else:
        summaries.sort(key=lambda row: _record_sort_timestamp({"updated_at": row.get("last_updated_at")}), reverse=reverse)

    return Response(_paginate_results(request, summaries))


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
                    "source_reference": f"{serialized.get('needs_list_no') or serialized.get('needs_list_id')} (This needs list)",
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

        previous_status = str(record.get("status") or "").upper()
        if not _status_matches(previous_status, "DRAFT", "MODIFIED", include_db_transitions=True):
            errors.append({"id": needs_list_id, "error": "Only draft or modified needs lists can be submitted."})
            continue

        item_count = len(record.get("snapshot", {}).get("items") or [])
        if item_count == 0:
            errors.append({"id": needs_list_id, "error": "Cannot submit an empty needs list."})
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
        workflow_store.update_record(needs_list_id, updated_record)
        logger.info(
            "needs_list_cancelled",
            extra={
                "event_type": "STATE_CHANGE",
                "user_id": getattr(request.user, "user_id", None),
                "username": getattr(request.user, "username", None),
                "needs_list_id": needs_list_id,
                "from_status": status,
                "to_status": "CANCELLED",
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
    if not _status_matches(previous_status, "DRAFT", "MODIFIED", include_db_transitions=True):
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
    record = workflow_store.transition_status(
        record,
        target_status,
        _actor_id(request),
        stage="IN_PREPARATION",
    )
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

    if not _status_matches(record.get("status"), "IN_PREPARATION", include_db_transitions=True):
        return Response({"errors": {"status": "Needs list must be in preparation."}}, status=409)
    if not record.get("prep_started_at"):
        return Response({"errors": {"status": "Needs list preparation must be started."}}, status=409)
    if record.get("dispatched_at"):
        return Response({"errors": {"status": "Needs list already dispatched."}}, status=409)

    from_status = str(record.get("status") or "").upper()
    target_status = _workflow_target_status("DISPATCHED")
    record = workflow_store.transition_status(
        record,
        target_status,
        _actor_id(request),
        stage="DISPATCHED",
    )
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

    if not _status_matches(record.get("status"), "DISPATCHED", include_db_transitions=True):
        return Response({"errors": {"status": "Needs list must be dispatched."}}, status=409)
    if not record.get("dispatched_at"):
        return Response({"errors": {"status": "Needs list must be dispatched."}}, status=409)
    if record.get("received_at"):
        return Response({"errors": {"status": "Needs list already received."}}, status=409)

    from_status = str(record.get("status") or "").upper()
    target_status = _workflow_target_status("RECEIVED")
    record = workflow_store.transition_status(
        record,
        target_status,
        _actor_id(request),
        stage="RECEIVED",
    )
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

    if not _status_matches(record.get("status"), "RECEIVED", include_db_transitions=True):
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

    snapshot = workflow_store.apply_overrides(record)
    items = snapshot.get("items", [])

    horizon_b_lines = []
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
        "warnings": ["donation_in_transit_unmodeled"],
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

    allocations = request.data if isinstance(request.data, list) else []
    if not allocations:
        return Response(
            {"errors": {"allocations": "Must provide a list of allocations."}},
            status=400,
        )

    logger.info(
        "needs_list_donations_allocate_not_implemented",
        extra={
            "event_type": "EXECUTION",
            "user_id": getattr(request.user, "user_id", None),
            "username": getattr(request.user, "username", None),
            "needs_list_id": needs_list_id,
            "allocation_count": len(allocations),
        },
    )

    return Response(
        {"errors": {"donations": "donation_allocation_not_implemented"}},
        status=501,
    )


@api_view(["GET"])
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

    fmt = request.query_params.get("format", "csv").lower()
    snapshot = workflow_store.apply_overrides(record)
    items = snapshot.get("items", [])
    horizon_b_items = [
        item for item in items
        if ((item.get("horizon") or {}).get("B") or {}).get("recommended_qty", 0) > 0
    ]

    if fmt == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Item ID", "Item Name", "UOM", "Required Qty"])
        for item in horizon_b_items:
            writer.writerow([
                item["item_id"],
                item.get("item_name", ""),
                item.get("uom_code", "EA"),
                item["horizon"]["B"]["recommended_qty"],
            ])
        response = HttpResponse(output.getvalue(), content_type="text/csv")
        ref = _safe_content_disposition_ref(
            record.get("needs_list_no"),
            needs_list_id,
        )
        response["Content-Disposition"] = f'attachment; filename="donation_needs_{ref}.csv"'
        return response

    return Response({
        "needs_list_id": needs_list_id,
        "format": fmt,
        "items": [
            {
                "item_id": item["item_id"],
                "item_name": item.get("item_name", ""),
                "uom": item.get("uom_code", "EA"),
                "required_qty": item["horizon"]["B"]["recommended_qty"],
            }
            for item in horizon_b_items
        ],
    })


@api_view(["GET"])
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

    fmt = request.query_params.get("format", "csv").lower()
    snapshot = workflow_store.apply_overrides(record)
    items = snapshot.get("items", [])
    horizon_c_items = [
        item for item in items
        if ((item.get("horizon") or {}).get("C") or {}).get("recommended_qty", 0) > 0
    ]

    if fmt == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Item ID", "Item Name", "UOM", "Required Qty", "Est Unit Cost", "Est Total Cost"])
        for item in horizon_c_items:
            proc = item.get("procurement") or {}
            qty = item["horizon"]["C"]["recommended_qty"]
            unit_cost = proc.get("est_unit_cost") or 0
            writer.writerow([
                item["item_id"],
                item.get("item_name", ""),
                item.get("uom_code", "EA"),
                qty,
                unit_cost,
                unit_cost * qty if unit_cost else "",
            ])
        response = HttpResponse(output.getvalue(), content_type="text/csv")
        ref = _safe_content_disposition_ref(
            record.get("needs_list_no"),
            needs_list_id,
        )
        response["Content-Disposition"] = f'attachment; filename="procurement_needs_{ref}.csv"'
        return response

    return Response({
        "needs_list_id": needs_list_id,
        "format": fmt,
        "items": [
            {
                "item_id": item["item_id"],
                "item_name": item.get("item_name", ""),
                "uom": item.get("uom_code", "EA"),
                "required_qty": item["horizon"]["C"]["recommended_qty"],
                "est_unit_cost": (item.get("procurement") or {}).get("est_unit_cost"),
                "est_total_cost": (item.get("procurement") or {}).get("est_total_cost"),
            }
            for item in horizon_c_items
        ],
    })


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
needs_list_procurement_export.required_permission = PERM_NEEDS_LIST_EXECUTE

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
    needs_list_bulk_submit,
    needs_list_bulk_delete,
    needs_list_start_preparation,
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
        filters = {}
        for key in ("status", "warehouse_id", "event_id", "needs_list_id", "supplier_id"):
            val = request.query_params.get(key)
            if val:
                filters[key] = val
        procurements, count = procurement_service.list_procurements(filters or None)
        return Response({"procurements": procurements, "count": count})

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


# ── Supplier Views ───────────────────────────────────────────────────────────


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


# ── Procurement Permission Assignments ──────────────────────────────────────

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
