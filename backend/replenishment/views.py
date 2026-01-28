import logging
import re
from typing import Any, Dict

from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from api.authentication import LegacyCompatAuthentication
from api.permissions import NeedsListPreviewPermission
from replenishment import rules
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


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPreviewPermission])
def needs_list_preview(request):
    payload = request.data or {}
    errors: Dict[str, str] = {}

    event_id = _parse_positive_int(payload.get("event_id"), "event_id", errors)
    warehouse_id = _parse_positive_int(payload.get("warehouse_id"), "warehouse_id", errors)
    planning_window_days = _parse_positive_int(
        payload.get("planning_window_days"), "planning_window_days", errors
    )

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
        return Response({"errors": errors}, status=400)

    if not phase:
        phase = "BASELINE"
        warnings_phase.append("phase_defaulted_to_baseline")
    phase = str(phase).upper()
    if phase not in rules.WINDOWS_V40:
        return Response({"errors": {"phase": "Must be SURGE, STABILIZED, or BASELINE."}}, status=400)

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
    burn_by_item, warnings_burn, burn_source = data_access.get_burn_by_item(
        event_id, warehouse_id, demand_window_hours, as_of_dt
    )

    base_warnings = (
        warnings_phase
        + warnings_available
        + warnings_donations
        + warnings_transfers
        + warnings_burn
    )

    item_ids = needs_list.collect_item_ids(
        available_by_item, donations_by_item, transfers_by_item, burn_by_item
    )

    safety_factor = rules.SAFETY_STOCK_FACTOR

    items, item_warnings = needs_list.build_preview_items(
        item_ids=item_ids,
        available_by_item=available_by_item,
        inbound_donations_by_item=donations_by_item,
        inbound_transfers_by_item=transfers_by_item,
        burn_by_item=burn_by_item,
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

    logger.info(
        "needs_list_preview",
        extra={
            "event_type": "READ",
            "user_id": getattr(request.user, "user_id", None),
            "username": getattr(request.user, "username", None),
            "event_id": event_id,
            "warehouse_id": warehouse_id,
            "as_of_datetime": as_of_dt.isoformat(),
            "planning_window_days": planning_window_days,
            "item_count": len(items),
            "warnings": warnings,
        },
    )

    response = {
        "as_of_datetime": as_of_dt.isoformat(),
        "planning_window_days": planning_window_days,
        "event_id": event_id,
        "warehouse_id": warehouse_id,
        "phase": phase,
        "items": items,
        "warnings": warnings,
    }
    return Response(response)
