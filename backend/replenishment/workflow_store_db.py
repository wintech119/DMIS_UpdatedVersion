"""
Database-backed workflow store for needs list management.

This module replaces the JSON file-based workflow_store.py with database persistence
using the Django ORM models defined in models.py.

All needs lists, line items, and audit trails are now stored in PostgreSQL tables,
making the system production-ready and enabling proper transactional integrity.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Dict, Iterable, Tuple
from django.db import transaction
from django.core.exceptions import ObjectDoesNotExist
from django.utils.dateparse import parse_datetime
from decimal import Decimal, InvalidOperation

from .models import (
    NeedsList,
    NeedsListItem,
    NeedsListAudit,
)
from .services import data_access

_STATUS_ALIASES = {
    "SUBMITTED": "PENDING_APPROVAL",
    "PENDING": "PENDING_APPROVAL",
    "MODIFIED": "RETURNED",
    "ESCALATED": "UNDER_REVIEW",
    "IN_PREPARATION": "IN_PROGRESS",
    "DISPATCHED": "IN_PROGRESS",
    "RECEIVED": "IN_PROGRESS",
    "COMPLETED": "FULFILLED",
}


def _utc_now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


def _utc_now_str() -> str:
    """Return current UTC datetime as ISO string."""
    return _utc_now().isoformat()


def _generate_needs_list_no(event_id: int, warehouse_id: int) -> str:
    """
    Generate unique needs list number.
    Format: NL-{EVENT_ID}-{WAREHOUSE_ID}-{YYYYMMDD}-{SEQ}
    """
    today = datetime.now().strftime('%Y%m%d')
    prefix = f"NL-{event_id}-{warehouse_id}-{today}"

    # Find next sequence number for today
    existing = NeedsList.objects.filter(
        needs_list_no__startswith=prefix
    ).count()

    seq = existing + 1
    return f"{prefix}-{seq:03d}"


def _coerce_optional_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _coerce_decimal(value: object, default: str = "0") -> Decimal:
    parsed = _coerce_optional_decimal(value)
    if parsed is None:
        return Decimal(default)
    return parsed


def _coerce_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _extract_horizon_qty(item_data: Dict[str, object], horizon_key: str) -> float:
    direct_key = f"horizon_{horizon_key.lower()}_qty"
    direct_value = item_data.get(direct_key)
    if direct_value is not None:
        return _coerce_float(direct_value, 0.0)
    horizon = item_data.get("horizon")
    if isinstance(horizon, dict):
        section = horizon.get(horizon_key)
        if isinstance(section, dict):
            return _coerce_float(section.get("recommended_qty"), 0.0)
    return 0.0


def _load_workflow_metadata(needs_list: NeedsList) -> Dict[str, object]:
    raw = needs_list.notes_text
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _normalize_snapshot_item(
    item_data: Dict[str, object],
    *,
    warehouse_id: int | None,
    warehouse_name: str | None,
    item_lookup: Dict[int, Dict[str, str | None]],
) -> Dict[str, object]:
    item_id = _coerce_float(item_data.get("item_id"), 0.0)
    item_id_int = int(item_id) if item_id else 0
    item_meta = item_lookup.get(item_id_int, {}) if item_id_int else {}
    item_name = item_data.get("item_name") or item_meta.get("name")
    item_code = item_data.get("item_code") or item_meta.get("code")

    burn_rate_per_hour = item_data.get("burn_rate_per_hour")
    if burn_rate_per_hour is None:
        burn_rate_per_hour = item_data.get("burn_rate")
    burn_rate_per_hour_value = _coerce_float(burn_rate_per_hour, 0.0)

    available_qty = _coerce_float(item_data.get("available_qty"), 0.0)
    inbound_transfer_qty = _coerce_float(item_data.get("inbound_transfer_qty"), 0.0)
    inbound_donation_qty = _coerce_float(item_data.get("inbound_donation_qty"), 0.0)
    inbound_procurement_qty = _coerce_float(item_data.get("inbound_procurement_qty"), 0.0)

    inbound_strict_qty = item_data.get("inbound_strict_qty")
    if inbound_strict_qty is None:
        inbound_strict_qty = inbound_transfer_qty + inbound_donation_qty
    inbound_strict_qty_value = _coerce_float(inbound_strict_qty, 0.0)

    required_qty = _coerce_float(item_data.get("required_qty"), 0.0)
    computed_required_qty = _coerce_float(
        item_data.get("computed_required_qty", required_qty),
        required_qty,
    )
    coverage_qty = _coerce_float(
        item_data.get("coverage_qty", available_qty + inbound_strict_qty_value),
        available_qty + inbound_strict_qty_value,
    )
    gap_qty = _coerce_float(item_data.get("gap_qty"), 0.0)

    time_to_stockout = item_data.get("time_to_stockout")
    if time_to_stockout is None:
        time_to_stockout = item_data.get("time_to_stockout_hours")
    time_to_stockout_hours: float | None
    if isinstance(time_to_stockout, str):
        parsed = _coerce_optional_decimal(time_to_stockout)
        if parsed is None:
            time_to_stockout_hours = None
        else:
            time_to_stockout_hours = float(parsed)
    elif time_to_stockout is None:
        time_to_stockout_hours = None
    else:
        time_to_stockout_hours = _coerce_float(time_to_stockout, 0.0)

    horizon_a_qty = _extract_horizon_qty(item_data, "A")
    horizon_b_qty = _extract_horizon_qty(item_data, "B")
    horizon_c_qty = _extract_horizon_qty(item_data, "C")

    warnings = item_data.get("warnings")
    normalized_warnings = (
        [str(w).strip() for w in warnings if str(w).strip()]
        if isinstance(warnings, list)
        else []
    )

    normalized = {
        "item_id": item_id_int,
        "item_name": item_name,
        "item_code": item_code,
        "warehouse_id": item_data.get("warehouse_id", warehouse_id),
        "warehouse_name": item_data.get("warehouse_name", warehouse_name),
        "uom_code": item_data.get("uom_code", "EA"),
        "burn_rate_per_hour": round(burn_rate_per_hour_value, 4),
        "burn_rate": round(burn_rate_per_hour_value, 4),
        "burn_rate_source": item_data.get("burn_rate_source", "CALCULATED"),
        "available_qty": round(available_qty, 2),
        "reserved_qty": round(_coerce_float(item_data.get("reserved_qty"), 0.0), 2),
        "inbound_transfer_qty": round(inbound_transfer_qty, 2),
        "inbound_donation_qty": round(inbound_donation_qty, 2),
        "inbound_procurement_qty": round(inbound_procurement_qty, 2),
        "inbound_strict_qty": round(inbound_strict_qty_value, 2),
        "required_qty": round(required_qty, 2),
        "computed_required_qty": round(computed_required_qty, 2),
        "coverage_qty": round(coverage_qty, 2),
        "gap_qty": round(gap_qty, 2),
        "time_to_stockout": time_to_stockout_hours,
        "time_to_stockout_hours": time_to_stockout_hours,
        "severity": item_data.get("severity", "OK"),
        "horizon": {
            "A": {"recommended_qty": round(horizon_a_qty, 2)},
            "B": {"recommended_qty": round(horizon_b_qty, 2)},
            "C": {"recommended_qty": round(horizon_c_qty, 2)},
        },
        "horizon_a_qty": round(horizon_a_qty, 2),
        "horizon_b_qty": round(horizon_b_qty, 2),
        "horizon_c_qty": round(horizon_c_qty, 2),
        "warnings": normalized_warnings,
        "override_reason": item_data.get("override_reason"),
        "override_updated_by": item_data.get("override_updated_by"),
        "override_updated_at": item_data.get("override_updated_at"),
        "review_comment": item_data.get("review_comment"),
        "review_updated_by": item_data.get("review_updated_by"),
        "review_updated_at": item_data.get("review_updated_at"),
    }

    if isinstance(item_data.get("procurement"), dict):
        normalized["procurement"] = item_data.get("procurement")
    if item_data.get("procurement_status") is not None:
        normalized["procurement_status"] = item_data.get("procurement_status")
    if isinstance(item_data.get("triggers"), dict):
        normalized["triggers"] = item_data.get("triggers")
    if isinstance(item_data.get("confidence"), dict):
        normalized["confidence"] = item_data.get("confidence")
    if isinstance(item_data.get("freshness"), dict):
        normalized["freshness"] = item_data.get("freshness")
    if item_data.get("freshness_state") is not None:
        normalized["freshness_state"] = item_data.get("freshness_state")

    return normalized


@transaction.atomic
def create_draft(
    payload: Dict[str, object],
    items: Iterable[Dict[str, object]],
    warnings: Iterable[str],
    actor: str | None,
) -> Dict[str, object]:
    """
    Create a new needs list in DRAFT status with calculated line items.

    Args:
        payload: Needs list header data (event_id, warehouse_id, phase, etc.)
        items: List of calculated line items with burn rates, gaps, horizons
        warnings: List of warning messages from calculation
        actor: Username of the user creating the draft

    Returns:
        Dict representation of the created needs list record
    """
    if actor is None:
        actor = 'SYSTEM'

    items = list(items)
    warnings_list = list(warnings)

    # Extract header data
    event_id = payload.get('event_id')
    warehouse_id = payload.get('warehouse_id')
    phase = payload.get('phase')
    as_of_datetime = payload.get('as_of_datetime')
    planning_window_days = payload.get('planning_window_days')
    selected_method = payload.get("selected_method")
    selected_item_keys = payload.get("selected_item_keys")
    filters = payload.get("filters")

    # Convert planning window to hours (assumes demand/planning windows are in API payload)
    # For now, use default values based on phase
    phase_windows = {
        'SURGE': {'demand': 6, 'planning': 72},
        'STABILIZED': {'demand': 72, 'planning': 168},
        'BASELINE': {'demand': 720, 'planning': 720},
    }
    windows = phase_windows.get(phase, phase_windows['BASELINE'])
    demand_window_hours = windows['demand']
    planning_window_hours = windows['planning']
    if planning_window_days is not None:
        try:
            planning_window_hours = int(float(planning_window_days) * 24)
        except (TypeError, ValueError):
            pass

    calculation_dtime = as_of_datetime
    if isinstance(calculation_dtime, str):
        parsed_as_of = parse_datetime(calculation_dtime)
        calculation_dtime = parsed_as_of if parsed_as_of is not None else None
    if calculation_dtime is None:
        calculation_dtime = _utc_now()

    # Generate unique needs list number
    needs_list_no = _generate_needs_list_no(event_id, warehouse_id)

    # Calculate totals
    total_gap_qty = sum(
        Decimal(str(item.get('gap_qty', 0)))
        for item in items
    )

    # Create needs list header
    needs_list = NeedsList.objects.create(
        needs_list_no=needs_list_no,
        event_id=event_id,
        warehouse_id=warehouse_id,
        event_phase=phase,
        calculation_dtime=calculation_dtime,
        demand_window_hours=demand_window_hours,
        planning_window_hours=planning_window_hours,
        safety_factor=Decimal('1.25'),  # Default safety factor
        data_freshness_level='HIGH',  # TODO: Calculate from actual data freshness
        status_code='DRAFT',
        total_gap_qty=total_gap_qty,
        notes_text=json.dumps(
            {
                "selected_method": selected_method,
                "selected_item_keys": selected_item_keys,
                "filters": filters,
                "warnings": warnings_list,
            }
        ),
        create_by_id=actor,
        update_by_id=actor,
    )

    # Create line items
    for item_data in items:
        inbound_strict_qty = _coerce_float(item_data.get("inbound_strict_qty"), 0.0)
        inbound_transfer_qty = item_data.get("inbound_transfer_qty")
        if inbound_transfer_qty is None:
            inbound_transfer_qty = inbound_strict_qty
        inbound_donation_qty = item_data.get("inbound_donation_qty")
        if inbound_donation_qty is None:
            inbound_donation_qty = 0.0

        available_qty = _coerce_float(item_data.get("available_qty"), 0.0)
        coverage_qty = item_data.get("coverage_qty")
        if coverage_qty is None:
            coverage_qty = available_qty + _coerce_float(inbound_transfer_qty, 0.0) + _coerce_float(inbound_donation_qty, 0.0)

        time_to_stockout = _coerce_optional_decimal(
            item_data.get("time_to_stockout_hours", item_data.get("time_to_stockout"))
        )

        burn_rate = item_data.get("burn_rate_per_hour")
        if burn_rate is None:
            burn_rate = item_data.get("burn_rate")

        horizon_a_qty = _extract_horizon_qty(item_data, "A")
        horizon_b_qty = _extract_horizon_qty(item_data, "B")
        horizon_c_qty = _extract_horizon_qty(item_data, "C")

        NeedsListItem.objects.create(
            needs_list=needs_list,
            item_id=item_data.get('item_id'),
            uom_code=item_data.get('uom_code', 'EA'),
            burn_rate=_coerce_decimal(burn_rate),
            burn_rate_source=item_data.get('burn_rate_source', 'CALCULATED'),
            available_stock=_coerce_decimal(available_qty),
            reserved_qty=_coerce_decimal(item_data.get('reserved_qty')),
            inbound_transfer_qty=_coerce_decimal(inbound_transfer_qty),
            inbound_donation_qty=_coerce_decimal(inbound_donation_qty),
            inbound_procurement_qty=_coerce_decimal(item_data.get('inbound_procurement_qty')),
            required_qty=_coerce_decimal(item_data.get('required_qty')),
            coverage_qty=_coerce_decimal(coverage_qty),
            gap_qty=_coerce_decimal(item_data.get('gap_qty')),
            time_to_stockout_hours=time_to_stockout,
            severity_level=item_data.get('severity', 'OK'),
            horizon_a_qty=_coerce_decimal(horizon_a_qty),
            horizon_b_qty=_coerce_decimal(horizon_b_qty),
            horizon_c_qty=_coerce_decimal(horizon_c_qty),
            create_by_id=actor,
            update_by_id=actor,
        )

    # Create audit log entry
    NeedsListAudit.objects.create(
        needs_list=needs_list,
        action_type='CREATED',
        notes_text=f"Created with {len(items)} items. Warnings: {', '.join(warnings_list) if warnings_list else 'None'}",
        actor_user_id=actor,
    )

    # Return dict representation matching the old JSON format
    return _needs_list_to_dict(needs_list, items, warnings_list)


def get_record(needs_list_id: str) -> Dict[str, object] | None:
    """
    Retrieve a needs list record by ID.

    Args:
        needs_list_id: Primary key of the needs list (can be string or int)

    Returns:
        Dict representation of the needs list, or None if not found
    """
    try:
        # Handle both integer IDs and string IDs (for backward compatibility)
        if isinstance(needs_list_id, str) and not needs_list_id.isdigit():
            # Try to find by needs_list_no
            needs_list = NeedsList.objects.get(needs_list_no=needs_list_id)
        else:
            needs_list = NeedsList.objects.get(needs_list_id=int(needs_list_id))

        return _needs_list_to_dict(needs_list)
    except (ObjectDoesNotExist, ValueError):
        return None


def list_records(statuses: list[str] | None = None) -> list[Dict[str, object]]:
    """
    List needs list records, optionally filtered by status.

    Accepts legacy API status aliases and maps them to database status values.
    """
    queryset = NeedsList.objects.all()

    if statuses:
        normalized: set[str] = set()
        for status in statuses:
            value = str(status or "").strip().upper()
            if not value:
                continue
            normalized.add(_STATUS_ALIASES.get(value, value))
        if normalized:
            queryset = queryset.filter(status_code__in=list(normalized))

    queryset = queryset.order_by("-calculation_dtime", "-needs_list_id")
    return [_needs_list_to_dict(needs_list) for needs_list in queryset]


@transaction.atomic
def update_record(needs_list_id: str, record: Dict[str, object]) -> None:
    """
    Update a needs list record.

    Args:
        needs_list_id: Primary key of the needs list
        record: Updated record data
    """
    try:
        needs_list = NeedsList.objects.get(needs_list_id=int(needs_list_id))

        # Update fields from record
        if 'status' in record:
            needs_list.status_code = record['status']
        if 'updated_by' in record:
            needs_list.update_by_id = record['updated_by']

        # Update workflow timestamps
        if 'submitted_at' in record and record['submitted_at']:
            needs_list.submitted_at = record['submitted_at']
            needs_list.submitted_by = record.get('submitted_by')
        if 'review_started_at' in record and record['review_started_at']:
            needs_list.under_review_at = record['review_started_at']
            needs_list.under_review_by = record.get('review_started_by')
        elif 'reviewed_at' in record and record['reviewed_at']:
            needs_list.under_review_at = record['reviewed_at']
            needs_list.under_review_by = record.get('reviewed_by')
        if 'reviewed_at' in record and record['reviewed_at']:
            needs_list.reviewed_at = record['reviewed_at']
            needs_list.reviewed_by = record.get('reviewed_by')
        if 'approved_at' in record and record['approved_at']:
            needs_list.approved_at = record['approved_at']
            needs_list.approved_by = record.get('approved_by')
        if 'rejected_at' in record and record['rejected_at']:
            needs_list.rejected_at = record['rejected_at']
            needs_list.rejected_by = record.get('rejected_by')
            needs_list.rejection_reason = record.get('reject_reason')
        if 'returned_at' in record and record['returned_at']:
            needs_list.returned_at = record['returned_at']
            needs_list.returned_by = record.get('returned_by')
        if 'return_reason' in record and record['return_reason']:
            needs_list.returned_reason = record.get('return_reason')
        if 'cancelled_at' in record and record['cancelled_at']:
            needs_list.cancelled_at = record['cancelled_at']
            needs_list.cancelled_by = record.get('cancelled_by')
            needs_list.rejection_reason = record.get('cancel_reason')

        needs_list.save()

        # Update line item overrides if present
        line_overrides = record.get('line_overrides', {})
        for item_id_str, override_data in line_overrides.items():
            try:
                item = needs_list.items.get(item_id=int(item_id_str))
                item.adjusted_qty = Decimal(str(override_data.get('overridden_qty', 0)))
                item.adjustment_reason = 'OTHER'  # Map from override reason
                item.adjustment_notes = override_data.get('reason', '')
                item.adjusted_by = override_data.get('updated_by')
                item.adjusted_at = override_data.get('updated_at')
                item.update_by_id = override_data.get('updated_by', needs_list.update_by_id)
                item.save()
            except ObjectDoesNotExist:
                pass  # Item not found, skip

    except ObjectDoesNotExist:
        raise ValueError(f"Needs list {needs_list_id} not found")


def apply_overrides(record: Dict[str, object]) -> Dict[str, object]:
    """
    Apply line item overrides to the snapshot.

    This function merges adjusted quantities and review notes into the snapshot items.
    Used when retrieving a needs list to show current state with user modifications.

    Args:
        record: Needs list record dict

    Returns:
        Updated snapshot dict with overrides applied
    """
    snapshot = dict(record.get('snapshot') or {})
    items = [dict(item) for item in snapshot.get('items') or []]
    overrides = record.get('line_overrides') or {}
    review_notes = record.get('line_review_notes') or {}

    for item in items:
        item_id = str(item.get('item_id'))

        # Apply quantity override
        if item_id in overrides:
            override = overrides[item_id]
            if 'computed_required_qty' not in item:
                item['computed_required_qty'] = item.get('required_qty')
            item['required_qty'] = override.get('overridden_qty')
            item['override_reason'] = override.get('reason')
            item['override_updated_by'] = override.get('updated_by')
            item['override_updated_at'] = override.get('updated_at')

        # Apply review notes
        if item_id in review_notes:
            note = review_notes[item_id]
            item['review_comment'] = note.get('comment')
            item['review_updated_by'] = note.get('updated_by')
            item['review_updated_at'] = note.get('updated_at')

    snapshot['items'] = items
    return snapshot


@transaction.atomic
def add_line_overrides(
    record: Dict[str, object],
    overrides: Iterable[Dict[str, object]],
    actor: str | None,
) -> Tuple[Dict[str, object], list[str]]:
    """
    Add or update quantity overrides for line items.

    Args:
        record: Needs list record dict
        overrides: List of override dicts with item_id, overridden_qty, reason
        actor: Username of the user making the override

    Returns:
        Tuple of (updated record, list of error messages)
    """
    errors: list[str] = []
    now = _utc_now()
    needs_list_id = record.get('needs_list_id')
    if not needs_list_id:
        return record, ['needs_list_id missing']

    try:
        needs_list = NeedsList.objects.get(needs_list_id=int(needs_list_id))
    except ObjectDoesNotExist:
        return record, [f'needs_list_id {needs_list_id} not found']

    # Get valid item IDs
    valid_item_ids = set(
        str(item_id) for item_id in
        needs_list.items.values_list('item_id', flat=True)
    )

    # Process each override
    for override in overrides:
        item_id = str(override.get('item_id', ''))
        reason = override.get('reason')
        overridden_qty = override.get('overridden_qty')

        if not item_id or item_id not in valid_item_ids:
            errors.append(f"item_id {item_id} not found in needs list")
            continue

        if not reason:
            errors.append(f"reason required for item_id {item_id}")
            continue

        try:
            overridden_qty_decimal = Decimal(str(overridden_qty))
        except (InvalidOperation, ValueError, TypeError):
            errors.append(f"invalid overridden_qty for item_id {item_id}")
            continue

        try:
            item = needs_list.items.get(item_id=int(item_id))
            item.adjusted_qty = overridden_qty_decimal
            item.adjustment_reason = 'OTHER'
            item.adjustment_notes = reason
            item.adjusted_by = actor
            item.adjusted_at = now
            item.update_by_id = actor or 'SYSTEM'
            item.save()

            # Create audit log
            NeedsListAudit.objects.create(
                needs_list=needs_list,
                needs_list_item=item,
                action_type='QUANTITY_ADJUSTED',
                field_name='adjusted_qty',
                old_value=str(item.required_qty),
                new_value=str(overridden_qty),
                reason_code='OTHER',
                notes_text=reason,
                actor_user_id=actor or 'SYSTEM',
            )
        except (ObjectDoesNotExist, ValueError) as e:
            errors.append(f"Error updating item {item_id}: {str(e)}")

    needs_list.update_by_id = actor or 'SYSTEM'
    needs_list.save()

    # Reload and return updated record
    updated_record = _needs_list_to_dict(needs_list)
    return updated_record, errors


@transaction.atomic
def add_line_review_notes(
    record: Dict[str, object],
    notes: Iterable[Dict[str, object]],
    actor: str | None,
) -> Tuple[Dict[str, object], list[str]]:
    """
    Add reviewer comments to line items.

    Args:
        record: Needs list record dict
        notes: List of note dicts with item_id and comment
        actor: Username of the reviewer

    Returns:
        Tuple of (updated record, list of error messages)
    """
    errors: list[str] = []
    now = _utc_now()

    needs_list_id = record.get('needs_list_id')
    if not needs_list_id:
        return record, ['needs_list_id missing']

    try:
        needs_list = NeedsList.objects.get(needs_list_id=int(needs_list_id))
    except ObjectDoesNotExist:
        return record, [f'needs_list_id {needs_list_id} not found']

    # Get valid item IDs
    valid_item_ids = set(
        str(item_id) for item_id in
        needs_list.items.values_list('item_id', flat=True)
    )

    # Process each note
    for note in notes:
        item_id = str(note.get('item_id', ''))
        comment = note.get('comment', '').strip()

        if not item_id or item_id not in valid_item_ids:
            errors.append(f"item_id {item_id} not found in needs list")
            continue

        if not comment:
            errors.append(f"comment required for item_id {item_id}")
            continue

        try:
            item = needs_list.items.get(item_id=int(item_id))

            # Create audit log for review comment
            NeedsListAudit.objects.create(
                needs_list=needs_list,
                needs_list_item=item,
                action_type='COMMENT_ADDED',
                notes_text=comment,
                actor_user_id=actor or 'SYSTEM',
            )
        except ObjectDoesNotExist as e:
            errors.append(f"Error adding note for item {item_id}: {str(e)}")

    needs_list.update_by_id = actor or 'SYSTEM'
    needs_list.save()

    # Reload and return updated record
    updated_record = _needs_list_to_dict(needs_list)
    return updated_record, errors


@transaction.atomic
def transition_status(
    record: Dict[str, object],
    to_status: str,
    actor: str | None,
    reason: str | None = None,
) -> Dict[str, object]:
    """
    Transition needs list to a new status.

    Args:
        record: Needs list record dict
        to_status: New status code
        actor: Username of the user performing the transition
        reason: Optional reason for the transition (for rejections, cancellations)

    Returns:
        Updated record dict
    """
    needs_list_id = record.get('needs_list_id')
    if not needs_list_id:
        raise ValueError('needs_list_id missing')

    try:
        needs_list = NeedsList.objects.get(needs_list_id=int(needs_list_id))
    except ObjectDoesNotExist:
        raise ValueError(f'needs_list_id {needs_list_id} not found')

    old_status = needs_list.status_code
    needs_list.status_code = to_status
    needs_list.update_by_id = actor or 'SYSTEM'

    # Update workflow timestamps based on new status
    now = _utc_now()
    if to_status == 'PENDING_APPROVAL':
        needs_list.submitted_at = now
        needs_list.submitted_by = actor
    elif to_status == 'UNDER_REVIEW':
        needs_list.under_review_at = now
        needs_list.under_review_by = actor
    elif to_status == 'APPROVED':
        needs_list.reviewed_at = now
        needs_list.reviewed_by = actor
        needs_list.approved_at = now
        needs_list.approved_by = actor
    elif to_status == 'REJECTED':
        needs_list.reviewed_at = now
        needs_list.reviewed_by = actor
        needs_list.rejected_at = now
        needs_list.rejected_by = actor
        needs_list.rejection_reason = reason
    elif to_status == 'RETURNED':
        needs_list.reviewed_at = now
        needs_list.reviewed_by = actor
        needs_list.returned_at = now
        needs_list.returned_by = actor
        needs_list.returned_reason = reason
    elif to_status == 'CANCELLED':
        needs_list.cancelled_at = now
        needs_list.cancelled_by = actor
        needs_list.rejection_reason = reason  # Reuse rejection_reason field

    needs_list.save()

    # Create audit log for status change
    NeedsListAudit.objects.create(
        needs_list=needs_list,
        action_type='STATUS_CHANGED',
        field_name='status_code',
        old_value=old_status,
        new_value=to_status,
        reason_code=reason if reason else None,
        notes_text=f"Status changed from {old_status} to {to_status}",
        actor_user_id=actor or 'SYSTEM',
    )

    # Return updated record
    return _needs_list_to_dict(needs_list)


def store_enabled_or_raise() -> None:
    """
    Check if database-backed workflow store is enabled.

    In the database version, this always succeeds since we're using Django ORM.
    Kept for backward compatibility with the JSON file version.
    """
    # Database store is always enabled
    pass


# =============================================================================
# Helper Functions
# =============================================================================

def _needs_list_to_dict(
    needs_list: NeedsList,
    items: Iterable[Dict[str, object]] = None,
    warnings: Iterable[str] = None
) -> Dict[str, object]:
    """
    Convert a NeedsList model instance to dict format matching the old JSON structure.

    Args:
        needs_list: NeedsList model instance
        items: Optional list of item dicts (for newly created records)
        warnings: Optional list of warnings (for newly created records)

    Returns:
        Dict representation of the needs list
    """
    metadata = _load_workflow_metadata(needs_list)
    selected_method = metadata.get("selected_method")
    selected_item_keys = metadata.get("selected_item_keys")
    filters = metadata.get("filters")
    if warnings is None:
        raw_warnings = metadata.get("warnings")
        if isinstance(raw_warnings, list):
            warnings = [str(w).strip() for w in raw_warnings if str(w).strip()]
        else:
            warnings = []

    warehouse_name = data_access.get_warehouse_name(needs_list.warehouse_id)
    event_name = data_access.get_event_name(needs_list.event_id)
    warehouses = [
        {
            "warehouse_id": needs_list.warehouse_id,
            "warehouse_name": warehouse_name,
        }
    ]
    warehouse_ids = [needs_list.warehouse_id]

    # If items not provided, load from database.
    if items is None:
        db_items = list(needs_list.items.all())
        item_ids = [item.item_id for item in db_items]
        item_lookup, _ = data_access.get_item_names(item_ids)

        items = []
        for item in db_items:
            raw_item = {
                "item_id": item.item_id,
                "uom_code": item.uom_code,
                "burn_rate": float(item.burn_rate),
                "burn_rate_source": item.burn_rate_source,
                "available_qty": float(item.available_stock),
                "reserved_qty": float(item.reserved_qty),
                "inbound_transfer_qty": float(item.inbound_transfer_qty),
                "inbound_donation_qty": float(item.inbound_donation_qty),
                "inbound_procurement_qty": float(item.inbound_procurement_qty),
                "required_qty": float(item.required_qty),
                "coverage_qty": float(item.coverage_qty),
                "gap_qty": float(item.gap_qty),
                "time_to_stockout": float(item.time_to_stockout_hours)
                if item.time_to_stockout_hours is not None
                else None,
                "severity": item.severity_level,
                "horizon_a_qty": float(item.horizon_a_qty),
                "horizon_b_qty": float(item.horizon_b_qty),
                "horizon_c_qty": float(item.horizon_c_qty),
                "computed_required_qty": float(item.required_qty),
                "override_reason": item.adjustment_notes if item.adjusted_qty is not None else None,
                "override_updated_by": item.adjusted_by if item.adjusted_qty is not None else None,
                "override_updated_at": item.adjusted_at.isoformat() if item.adjusted_at else None,
            }
            items.append(
                _normalize_snapshot_item(
                    raw_item,
                    warehouse_id=needs_list.warehouse_id,
                    warehouse_name=warehouse_name,
                    item_lookup=item_lookup,
                )
            )
    else:
        items = list(items)
        item_ids = [
            int(_coerce_float(item.get("item_id"), 0.0))
            for item in items
            if _coerce_float(item.get("item_id"), 0.0) > 0
        ]
        item_lookup, _ = data_access.get_item_names(item_ids)
        items = [
            _normalize_snapshot_item(
                dict(item),
                warehouse_id=needs_list.warehouse_id,
                warehouse_name=warehouse_name,
                item_lookup=item_lookup,
            )
            for item in items
        ]

    # Build line overrides dict
    line_overrides = {}
    for item in needs_list.items.filter(adjusted_qty__isnull=False):
        line_overrides[str(item.item_id)] = {
            'overridden_qty': float(item.adjusted_qty),
            'reason': item.adjustment_notes or '',
            'updated_by': item.adjusted_by,
            'updated_at': item.adjusted_at.isoformat() if item.adjusted_at else None,
        }

    # Build line review notes dict from audit logs
    line_review_notes = {}
    for audit in needs_list.audit_logs.filter(action_type='COMMENT_ADDED').order_by('-action_dtime'):
        if audit.needs_list_item:
            item_id = str(audit.needs_list_item.item_id)
            if item_id not in line_review_notes:
                line_review_notes[item_id] = {
                    'comment': audit.notes_text,
                    'updated_by': audit.actor_user_id,
                    'updated_at': audit.action_dtime.isoformat(),
                }

    calculation_as_of = (
        needs_list.calculation_dtime.isoformat()
        if hasattr(needs_list.calculation_dtime, "isoformat")
        else str(needs_list.calculation_dtime)
    )

    return {
        'needs_list_id': str(needs_list.needs_list_id),  # String for backward compatibility
        'needs_list_no': needs_list.needs_list_no,
        'event_id': needs_list.event_id,
        'event_name': event_name,
        'warehouse_id': needs_list.warehouse_id,
        'warehouse_ids': warehouse_ids,
        'warehouses': warehouses,
        'phase': needs_list.event_phase,
        'as_of_datetime': calculation_as_of,
        'planning_window_days': needs_list.planning_window_hours / 24,  # Convert back to days
        'filters': filters,
        'status': needs_list.status_code,
        'created_by': needs_list.create_by_id,
        'created_at': needs_list.create_dtime.isoformat(),
        'updated_by': needs_list.update_by_id,
        'updated_at': needs_list.update_dtime.isoformat(),
        'submitted_by': needs_list.submitted_by,
        'submitted_at': needs_list.submitted_at.isoformat() if needs_list.submitted_at else None,
        'reviewed_by': needs_list.reviewed_by,
        'reviewed_at': needs_list.reviewed_at.isoformat() if needs_list.reviewed_at else None,
        'review_started_by': needs_list.under_review_by,
        'review_started_at': needs_list.under_review_at.isoformat() if needs_list.under_review_at else None,
        'approved_by': needs_list.approved_by,
        'approved_at': needs_list.approved_at.isoformat() if needs_list.approved_at else None,
        'approval_tier': None,  # TODO: Add to model if needed
        'approval_rationale': None,
        'prep_started_by': None,  # TODO: Add workflow stages to model
        'prep_started_at': None,
        'dispatched_by': None,
        'dispatched_at': None,
        'received_by': None,
        'received_at': None,
        'completed_by': None,
        'completed_at': None,
        'cancelled_by': needs_list.cancelled_by if needs_list.status_code == 'CANCELLED' else None,
        'cancelled_at': needs_list.cancelled_at.isoformat() if needs_list.status_code == 'CANCELLED' and needs_list.cancelled_at else None,
        'cancel_reason': needs_list.rejection_reason if needs_list.status_code == 'CANCELLED' else None,
        'escalated_by': None,  # TODO: Add escalation tracking
        'escalated_at': None,
        'escalation_reason': None,
        'returned_by': needs_list.returned_by,
        'returned_at': needs_list.returned_at.isoformat() if needs_list.returned_at else None,
        'return_reason': needs_list.returned_reason if needs_list.status_code == 'RETURNED' else None,
        'rejected_by': needs_list.rejected_by,
        'rejected_at': needs_list.rejected_at.isoformat() if needs_list.rejected_at else None,
        'reject_reason': needs_list.rejection_reason if needs_list.status_code == 'REJECTED' else None,
        'line_overrides': line_overrides,
        'line_review_notes': line_review_notes,
        'selected_method': selected_method,
        'selected_item_keys': selected_item_keys,
        'snapshot': {
            'items': items,
            'warnings': list(warnings),
            'planning_window_days': needs_list.planning_window_hours / 24,
            'as_of_datetime': calculation_as_of,
            'event_name': event_name,
            'warehouse_ids': warehouse_ids,
            'warehouses': warehouses,
            'selected_method': selected_method,
        },
    }
