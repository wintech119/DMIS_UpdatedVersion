import logging
from typing import Any, Dict

from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from api.authentication import LegacyCompatAuthentication
from api.permissions import NeedsListPreviewPermission
from replenishment.services import data_access, needs_list

logger = logging.getLogger("dmis.audit")


def _parse_positive_int(value: Any, field_name: str, errors: Dict[str, str]) -> int | None:
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
    as_of_raw = payload.get("as_of_datetime")
    as_of_dt = timezone.now()
    if as_of_raw:
        parsed = parse_datetime(as_of_raw)
        if parsed is None:
            errors["as_of_datetime"] = "Must be an ISO-8601 datetime string."
        else:
            as_of_dt = parsed

    if errors:
        return Response({"errors": errors}, status=400)

    horizon_a_days = int(getattr(settings, "NEEDS_HORIZON_A_DAYS", 7))
    horizon_b_days_setting = getattr(settings, "NEEDS_HORIZON_B_DAYS", None)
    if horizon_b_days_setting is None and planning_window_days is not None:
        horizon_b_days = max(planning_window_days - horizon_a_days, 0)
    else:
        horizon_b_days = int(horizon_b_days_setting or 0)

    available_by_item, warnings_available = data_access.get_available_by_item(
        warehouse_id, as_of_dt
    )
    donations_by_item, warnings_donations = data_access.get_inbound_donations_by_item(
        warehouse_id, as_of_dt
    )
    transfers_by_item, warnings_transfers = data_access.get_inbound_transfers_by_item(
        warehouse_id, as_of_dt
    )
    burn_by_item, warnings_burn, burn_source = data_access.get_burn_by_item(
        event_id, warehouse_id, planning_window_days, as_of_dt
    )

    base_warnings = (
        warnings_available + warnings_donations + warnings_transfers + warnings_burn
    )

    item_ids = needs_list.collect_item_ids(
        available_by_item, donations_by_item, transfers_by_item, burn_by_item
    )

    items, item_warnings = needs_list.build_preview_items(
        item_ids=item_ids,
        available_by_item=available_by_item,
        inbound_donations_by_item=donations_by_item,
        inbound_transfers_by_item=transfers_by_item,
        burn_by_item=burn_by_item,
        planning_window_days=planning_window_days,
        safety_factor=float(getattr(settings, "NEEDS_SAFETY_FACTOR", 1.0)),
        horizon_a_days=horizon_a_days,
        horizon_b_days=horizon_b_days,
        burn_source=burn_source,
        as_of_dt=as_of_dt,
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
