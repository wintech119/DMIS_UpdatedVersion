import logging
import re
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
    PERM_NEEDS_LIST_REJECT,
    PERM_NEEDS_LIST_RETURN,
    PERM_NEEDS_LIST_REVIEW_START,
    PERM_NEEDS_LIST_SUBMIT,
)
from replenishment import rules, workflow_store
from replenishment.services import data_access, needs_list

logger = logging.getLogger("dmis.audit")


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


def _actor_id(request) -> str | None:
    return getattr(request.user, "user_id", None) or getattr(request.user, "username", None)


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
    )

    warnings = needs_list.merge_warnings(base_warnings, item_warnings)

    response = {
        "as_of_datetime": as_of_dt.isoformat(),
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
    response = dict(snapshot)
    response.update(
        {
            "needs_list_id": record.get("needs_list_id"),
            "status": record.get("status"),
            "event_id": record.get("event_id"),
            "warehouse_id": record.get("warehouse_id"),
            "phase": record.get("phase"),
            "planning_window_days": record.get("planning_window_days"),
            "as_of_datetime": record.get("as_of_datetime"),
            "created_by": record.get("created_by"),
            "created_at": record.get("created_at"),
            "updated_by": record.get("updated_by"),
            "updated_at": record.get("updated_at"),
            "submitted_by": record.get("submitted_by"),
            "submitted_at": record.get("submitted_at"),
            "reviewer_by": record.get("reviewer_by"),
            "review_started_at": record.get("review_started_at"),
            "return_reason": record.get("return_reason"),
            "reject_reason": record.get("reject_reason"),
        }
    )
    return response


def _workflow_disabled_response() -> Response:
    return Response(
        {"errors": {"workflow": "Workflow dev store is disabled."}},
        status=501,
    )


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
@permission_classes([NeedsListPermission])
def needs_list_draft(request):
    payload = request.data or {}
    response, errors = _build_preview_response(payload)
    if errors:
        return Response({"errors": errors}, status=400)

    try:
        workflow_store.store_enabled_or_raise()
    except RuntimeError:
        return _workflow_disabled_response()

    record_payload = {
        "event_id": response.get("event_id"),
        "warehouse_id": response.get("warehouse_id"),
        "phase": response.get("phase"),
        "as_of_datetime": response.get("as_of_datetime"),
        "planning_window_days": response.get("planning_window_days"),
        "filters": payload.get("filters"),
    }
    record = workflow_store.create_draft(
        record_payload,
        response.get("items", []),
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
            "event_id": response.get("event_id"),
            "warehouse_id": response.get("warehouse_id"),
            "item_count": len(response.get("items", [])),
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

    if record.get("status") != "DRAFT":
        return Response({"errors": {"status": "Drafts only."}}, status=409)

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

    if record.get("status") != "DRAFT":
        return Response({"errors": {"status": "Only drafts can be submitted."}}, status=409)

    submit_empty_allowed = bool((request.data or {}).get("submit_empty_allowed", False))
    item_count = len(record.get("snapshot", {}).get("items") or [])
    if item_count == 0 and not submit_empty_allowed:
        return Response({"errors": {"items": "Cannot submit an empty needs list."}}, status=409)

    record = workflow_store.transition_status(record, "SUBMITTED", _actor_id(request))
    workflow_store.update_record(needs_list_id, record)

    logger.info(
        "needs_list_submitted",
        extra={
            "event_type": "STATE_CHANGE",
            "user_id": getattr(request.user, "user_id", None),
            "username": getattr(request.user, "username", None),
            "needs_list_id": needs_list_id,
            "from_status": "DRAFT",
            "to_status": "SUBMITTED",
            "item_count": item_count,
        },
    )

    return Response(_serialize_workflow_record(record, include_overrides=True))


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPermission])
def needs_list_review_start(request, needs_list_id: str):
    try:
        workflow_store.store_enabled_or_raise()
    except RuntimeError:
        return _workflow_disabled_response()

    record = workflow_store.get_record(needs_list_id)
    if not record:
        return Response({"errors": {"needs_list_id": "Not found."}}, status=404)

    if record.get("status") != "SUBMITTED":
        return Response({"errors": {"status": "Needs list must be submitted first."}}, status=409)

    actor = _actor_id(request)
    if not record.get("submitted_by") or record.get("submitted_by") == actor:
        return Response(
            {"errors": {"review": "Reviewer must be different from submitter."}},
            status=409,
        )

    record = workflow_store.transition_status(record, "UNDER_REVIEW", actor)
    workflow_store.update_record(needs_list_id, record)

    logger.info(
        "needs_list_review_started",
        extra={
            "event_type": "STATE_CHANGE",
            "user_id": getattr(request.user, "user_id", None),
            "username": getattr(request.user, "username", None),
            "needs_list_id": needs_list_id,
            "from_status": "SUBMITTED",
            "to_status": "UNDER_REVIEW",
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

    if record.get("status") != "UNDER_REVIEW":
        return Response({"errors": {"status": "Needs list must be under review."}}, status=409)

    reason = (request.data or {}).get("reason")
    if not reason:
        return Response({"errors": {"reason": "Reason is required."}}, status=400)

    record = workflow_store.transition_status(record, "DRAFT", _actor_id(request))
    record["return_reason"] = reason
    workflow_store.update_record(needs_list_id, record)

    logger.info(
        "needs_list_returned",
        extra={
            "event_type": "STATE_CHANGE",
            "user_id": getattr(request.user, "user_id", None),
            "username": getattr(request.user, "username", None),
            "needs_list_id": needs_list_id,
            "from_status": "UNDER_REVIEW",
            "to_status": "DRAFT",
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

    if record.get("status") != "UNDER_REVIEW":
        return Response({"errors": {"status": "Needs list must be under review."}}, status=409)

    reason = (request.data or {}).get("reason")
    if not reason:
        return Response({"errors": {"reason": "Reason is required."}}, status=400)

    record = workflow_store.transition_status(record, "REJECTED", _actor_id(request), reason=reason)
    workflow_store.update_record(needs_list_id, record)

    logger.info(
        "needs_list_rejected",
        extra={
            "event_type": "STATE_CHANGE",
            "user_id": getattr(request.user, "user_id", None),
            "username": getattr(request.user, "username", None),
            "needs_list_id": needs_list_id,
            "from_status": "UNDER_REVIEW",
            "to_status": "REJECTED",
            "reason": reason,
        },
    )

    return Response(_serialize_workflow_record(record, include_overrides=True))


needs_list_draft.required_permission = PERM_NEEDS_LIST_CREATE_DRAFT
needs_list_get.required_permission = [
    PERM_NEEDS_LIST_CREATE_DRAFT,
    PERM_NEEDS_LIST_SUBMIT,
    PERM_NEEDS_LIST_REVIEW_START,
    PERM_NEEDS_LIST_RETURN,
    PERM_NEEDS_LIST_REJECT,
]
needs_list_edit_lines.required_permission = PERM_NEEDS_LIST_EDIT_LINES
needs_list_submit.required_permission = PERM_NEEDS_LIST_SUBMIT
needs_list_review_start.required_permission = PERM_NEEDS_LIST_REVIEW_START
needs_list_return.required_permission = PERM_NEEDS_LIST_RETURN
needs_list_reject.required_permission = PERM_NEEDS_LIST_REJECT

for view_func in (
    needs_list_draft,
    needs_list_get,
    needs_list_edit_lines,
    needs_list_submit,
    needs_list_review_start,
    needs_list_return,
    needs_list_reject,
):
    if hasattr(view_func, "cls"):
        view_func.cls.required_permission = view_func.required_permission
