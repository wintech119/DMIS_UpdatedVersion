import logging
import re
import math
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
    PERM_NEEDS_LIST_REVIEW_START,
    PERM_NEEDS_LIST_SUBMIT,
)
from replenishment import rules, workflow_store
from replenishment.services import approval as approval_service
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
    approval_warnings = needs_list.merge_warnings(
        approval_warnings, approval_warnings_extra + authority_warnings
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
            "reject_reason": record.get("reject_reason"),
            "approval_summary": {
                "total_required_qty": round(total_required_qty, 2),
                "total_estimated_cost": None
                if total_estimated_cost is None
                else round(float(total_estimated_cost), 2),
                "approval": approval,
                "warnings": approval_warnings,
                "rationale": approval_rationale,
                "escalation_required": escalation_required,
            },
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
        status - comma-separated list of statuses (e.g. SUBMITTED,UNDER_REVIEW)
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
                f"{item.get('item_id')}_{item.get('warehouse_id') or warehouse_id}"
                in selected_item_keys
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

    if record.get("status") != "UNDER_REVIEW":
        return Response({"errors": {"status": "Needs list must be under review."}}, status=409)

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

    if record.get("status") != "UNDER_REVIEW":
        return Response({"errors": {"status": "Needs list must be under review."}}, status=409)

    actor = _actor_id(request)
    if not record.get("submitted_by") or record.get("submitted_by") == actor:
        return Response(
            {"errors": {"approval": "Approver must be different from submitter."}},
            status=409,
        )

    comment = (request.data or {}).get("comment")
    snapshot = workflow_store.apply_overrides(record)
    total_required_qty, total_estimated_cost, total_warnings = (
        approval_service.compute_needs_list_totals(snapshot.get("items") or [])
    )
    selected_method = (
        str(record.get("selected_method") or snapshot.get("selected_method") or "")
        .strip()
        .upper()
        or None
    )
    if selected_method == "A":
        total_warnings = []
    approval, approval_warnings, approval_rationale = (
        approval_service.determine_approval_tier(
            str(record.get("phase") or "BASELINE"),
            total_estimated_cost,
            bool(total_warnings),
            selected_method=selected_method,
        )
    )
    authority_warnings, escalation_required = (
        approval_service.evaluate_appendix_c_authority(snapshot.get("items") or [])
    )
    warnings = needs_list.merge_warnings(
        total_warnings, approval_warnings + authority_warnings
    )
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
    workflow_store.update_record(needs_list_id, record)

    logger.info(
        "needs_list_approved",
        extra={
            "event_type": "STATE_CHANGE",
            "user_id": getattr(request.user, "user_id", None),
            "username": getattr(request.user, "username", None),
            "needs_list_id": needs_list_id,
            "from_status": "UNDER_REVIEW",
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

    if record.get("status") != "UNDER_REVIEW":
        return Response({"errors": {"status": "Needs list must be under review."}}, status=409)

    reason = (request.data or {}).get("reason")
    if not reason:
        return Response({"errors": {"reason": "Reason is required."}}, status=400)

    record = workflow_store.transition_status(
        record, "ESCALATED", _actor_id(request), reason=reason
    )
    workflow_store.update_record(needs_list_id, record)

    logger.info(
        "needs_list_escalated",
        extra={
            "event_type": "STATE_CHANGE",
            "user_id": getattr(request.user, "user_id", None),
            "username": getattr(request.user, "username", None),
            "needs_list_id": needs_list_id,
            "from_status": "UNDER_REVIEW",
            "to_status": "ESCALATED",
            "reason": reason,
        },
    )

    return Response(_serialize_workflow_record(record, include_overrides=True))


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

    record = workflow_store.transition_status(record, "IN_PREPARATION", _actor_id(request))
    workflow_store.update_record(needs_list_id, record)

    logger.info(
        "needs_list_preparation_started",
        extra={
            "event_type": "STATE_CHANGE",
            "user_id": getattr(request.user, "user_id", None),
            "username": getattr(request.user, "username", None),
            "needs_list_id": needs_list_id,
            "from_status": "APPROVED",
            "to_status": "IN_PREPARATION",
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

    if record.get("status") != "IN_PREPARATION":
        return Response({"errors": {"status": "Needs list must be in preparation."}}, status=409)

    record = workflow_store.transition_status(record, "DISPATCHED", _actor_id(request))
    workflow_store.update_record(needs_list_id, record)

    logger.info(
        "needs_list_dispatched",
        extra={
            "event_type": "STATE_CHANGE",
            "user_id": getattr(request.user, "user_id", None),
            "username": getattr(request.user, "username", None),
            "needs_list_id": needs_list_id,
            "from_status": "IN_PREPARATION",
            "to_status": "DISPATCHED",
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

    if record.get("status") != "DISPATCHED":
        return Response({"errors": {"status": "Needs list must be dispatched."}}, status=409)

    record = workflow_store.transition_status(record, "RECEIVED", _actor_id(request))
    workflow_store.update_record(needs_list_id, record)

    logger.info(
        "needs_list_received",
        extra={
            "event_type": "STATE_CHANGE",
            "user_id": getattr(request.user, "user_id", None),
            "username": getattr(request.user, "username", None),
            "needs_list_id": needs_list_id,
            "from_status": "DISPATCHED",
            "to_status": "RECEIVED",
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

    if record.get("status") != "RECEIVED":
        return Response({"errors": {"status": "Needs list must be received."}}, status=409)

    record = workflow_store.transition_status(record, "COMPLETED", _actor_id(request))
    workflow_store.update_record(needs_list_id, record)

    logger.info(
        "needs_list_completed",
        extra={
            "event_type": "STATE_CHANGE",
            "user_id": getattr(request.user, "user_id", None),
            "username": getattr(request.user, "username", None),
            "needs_list_id": needs_list_id,
            "from_status": "RECEIVED",
            "to_status": "COMPLETED",
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

    if record.get("status") not in {"APPROVED", "IN_PREPARATION"}:
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
    PERM_NEEDS_LIST_REVIEW_START,
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
needs_list_review_start.required_permission = PERM_NEEDS_LIST_REVIEW_START
needs_list_return.required_permission = PERM_NEEDS_LIST_RETURN
needs_list_reject.required_permission = PERM_NEEDS_LIST_REJECT
needs_list_approve.required_permission = PERM_NEEDS_LIST_APPROVE
needs_list_escalate.required_permission = PERM_NEEDS_LIST_ESCALATE
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
    needs_list_review_start,
    needs_list_return,
    needs_list_reject,
    needs_list_approve,
    needs_list_escalate,
    needs_list_start_preparation,
    needs_list_mark_dispatched,
    needs_list_mark_received,
    needs_list_mark_completed,
    needs_list_cancel,
):
    if hasattr(view_func, "cls"):
        view_func.cls.required_permission = view_func.required_permission
