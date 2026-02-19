"""
Database-backed workflow store for needs list management.

This module replaces the JSON file-based workflow_store.py with database persistence
using the Django ORM models defined in models.py.

All needs lists, line items, and audit trails are now stored in PostgreSQL tables,
making the system production-ready and enabling proper transactional integrity.
"""

from __future__ import annotations

import logging
import json
from datetime import datetime, timezone
from typing import Dict, Iterable, Tuple
from django.db import IntegrityError, connection, transaction
from django.core.exceptions import ObjectDoesNotExist
from django.utils.dateparse import parse_datetime
from decimal import Decimal, InvalidOperation

from .models import (
    NeedsList,
    NeedsListItem,
    NeedsListAudit,
)
from .services import data_access

logger = logging.getLogger("dmis.audit")

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

_NEEDS_LIST_NO_MAX_RETRIES = 5
_SUPERSEDE_CANDIDATE_STATUSES = {
    "DRAFT",
    "RETURNED",
    "SUBMITTED",
    "PENDING",
    "PENDING_APPROVAL",
    "UNDER_REVIEW",
}
_WORKFLOW_METADATA_TABLE_NAME = "needs_list_workflow_metadata"
_IN_PROGRESS_STAGE_BY_STATUS = {
    status: status
    for status, mapped_status in _STATUS_ALIASES.items()
    if mapped_status == "IN_PROGRESS"
}
_IN_PROGRESS_STAGE_ALIASES = {
    "IN_PREPARATION": "IN_PREPARATION",
    "PREPARATION": "IN_PREPARATION",
    "PREP": "IN_PREPARATION",
    "DISPATCHED": "DISPATCHED",
    "DISPATCH": "DISPATCHED",
    "RECEIVED": "RECEIVED",
    "RECEIVE": "RECEIVED",
}


def _normalize_actor(value: object) -> str:
    return str(value or "").strip().lower()


def _record_owned_by_actor(needs_list: NeedsList, actor: str | None) -> bool:
    normalized_actor = _normalize_actor(actor)
    if not normalized_actor:
        return False

    return any(
        _normalize_actor(candidate) == normalized_actor
        for candidate in (
            needs_list.create_by_id,
            needs_list.submitted_by,
            needs_list.update_by_id,
        )
        if candidate
    )


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
    today = _utc_now().strftime("%Y%m%d")
    prefix = f"NL-{event_id}-{warehouse_id}-{today}"

    latest_no = (
        NeedsList.objects.select_for_update()
        .filter(needs_list_no__startswith=prefix)
        .order_by("-needs_list_no")
        .values_list("needs_list_no", flat=True)
        .first()
    )

    seq = 1
    if latest_no:
        try:
            seq = int(str(latest_no).rsplit("-", 1)[-1]) + 1
        except (TypeError, ValueError):
            seq = 1
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


def _coerce_int(value: object, default: int = 0) -> int:
    if value is None or isinstance(value, bool):
        return default
    try:
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return default
            return int(stripped)
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_in_progress_stage(stage: object) -> str | None:
    normalized = str(stage or "").strip().upper()
    if not normalized:
        return None
    return _IN_PROGRESS_STAGE_ALIASES.get(normalized)


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


def _workflow_metadata_table_name() -> str:
    quoted_table_name = connection.ops.quote_name(_WORKFLOW_METADATA_TABLE_NAME)
    if connection.vendor == "postgresql":
        quoted_schema_name = connection.ops.quote_name("public")
        return f"{quoted_schema_name}.{quoted_table_name}"
    return quoted_table_name


def _workflow_needs_list_table_name() -> str:
    metadata_table_name = _workflow_metadata_table_name()
    if "." in metadata_table_name:
        schema_name, _ = metadata_table_name.split(".", 1)
        return f"{schema_name}.{connection.ops.quote_name('needs_list')}"
    return connection.ops.quote_name("needs_list")


def _ensure_workflow_metadata_table() -> None:
    table_name = _workflow_metadata_table_name()
    needs_list_table_name = _workflow_needs_list_table_name()
    with connection.cursor() as cursor:
        if connection.vendor == "postgresql":
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
                    needs_list_id INTEGER PRIMARY KEY
                        REFERENCES {needs_list_table_name}(needs_list_id) ON DELETE CASCADE,
                    metadata_json JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        else:
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
                    needs_list_id INTEGER PRIMARY KEY,
                    metadata_json TEXT NOT NULL DEFAULT '{{}}',
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )


def _parse_workflow_metadata(raw: object) -> Dict[str, object]:
    if isinstance(raw, dict):
        return raw
    if raw is None:
        return {}
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _load_workflow_metadata(needs_list: NeedsList) -> Dict[str, object]:
    try:
        _ensure_workflow_metadata_table()
        table_name = _workflow_metadata_table_name()
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT metadata_json FROM {table_name} WHERE needs_list_id = %s",
                [int(needs_list.needs_list_id)],
            )
            row = cursor.fetchone()
        if row:
            parsed = _parse_workflow_metadata(row[0])
            if parsed:
                return parsed
    except Exception as exc:  # pragma: no cover - defensive fallback path
        logger.warning(
            "Workflow metadata lookup failed for needs_list_id=%s: %s",
            getattr(needs_list, "needs_list_id", None),
            exc,
        )

    # Legacy fallback for rows created before metadata table support.
    legacy = _parse_workflow_metadata(needs_list.notes_text)
    if legacy:
        try:
            _save_workflow_metadata(needs_list, legacy)
        except Exception as exc:  # pragma: no cover - best effort migration only
            logger.warning(
                "Failed saving legacy workflow metadata for needs_list_id=%s legacy=%s: %s",
                getattr(needs_list, "needs_list_id", None),
                legacy,
                exc,
                exc_info=True,
            )
    return legacy


def _save_workflow_metadata(needs_list: NeedsList, metadata: Dict[str, object]) -> None:
    serialized = json.dumps(metadata or {})
    try:
        _ensure_workflow_metadata_table()
        table_name = _workflow_metadata_table_name()
        with connection.cursor() as cursor:
            if connection.vendor == "postgresql":
                cursor.execute(
                    f"""
                    INSERT INTO {table_name} (needs_list_id, metadata_json, updated_at)
                    VALUES (%s, %s::jsonb, NOW())
                    ON CONFLICT (needs_list_id) DO UPDATE
                    SET metadata_json = EXCLUDED.metadata_json,
                        updated_at = NOW()
                    """,
                    [int(needs_list.needs_list_id), serialized],
                )
            else:
                cursor.execute(
                    f"""
                    INSERT INTO {table_name} (needs_list_id, metadata_json, updated_at)
                    VALUES (%s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (needs_list_id) DO UPDATE
                    SET metadata_json = excluded.metadata_json,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    [int(needs_list.needs_list_id), serialized],
                )
    except Exception as exc:  # pragma: no cover - defensive fallback path
        logger.warning(
            "Workflow metadata write failed for needs_list_id=%s; using legacy notes_text fallback: %s",
            getattr(needs_list, "needs_list_id", None),
            exc,
        )
        needs_list.notes_text = serialized
        try:
            needs_list.save(update_fields=["notes_text"])
        except Exception as save_exc:  # pragma: no cover - defensive fallback path
            logger.warning(
                "Legacy notes_text fallback save failed for needs_list_id=%s: %s",
                getattr(needs_list, "needs_list_id", None),
                save_exc,
            )


def _supersede_open_scope_records(
    *,
    event_id: int,
    warehouse_id: int,
    phase: str,
    actor: str | None,
    superseding_needs_list: NeedsList,
) -> list[str]:
    """
    Mark existing open records for the same scope and actor as SUPERSEDED.

    This keeps only the newest draft/revision active for a scope while preserving
    older drafts/submissions as history.
    """
    normalized_phase = str(phase or "").strip().upper()
    actor_value = actor or "SYSTEM"
    superseded_at = _utc_now_str()

    existing_records = (
        NeedsList.objects.select_for_update()
        .filter(
            event_id=event_id,
            warehouse_id=warehouse_id,
            event_phase=normalized_phase,
            status_code__in=_SUPERSEDE_CANDIDATE_STATUSES,
        )
        .exclude(needs_list_id=superseding_needs_list.needs_list_id)
        .order_by("-needs_list_id")
    )

    superseded_ids: list[str] = []
    for existing in existing_records:
        if not _record_owned_by_actor(existing, actor):
            continue

        previous_status = str(existing.status_code or "").upper()
        if previous_status == "SUPERSEDED":
            continue

        metadata = _load_workflow_metadata(existing)
        metadata["superseded_at"] = superseded_at
        metadata["superseded_by"] = actor_value
        metadata["supersede_reason"] = "Replaced by newer draft calculation."
        metadata["superseded_by_needs_list_id"] = str(
            superseding_needs_list.needs_list_id
        )
        _save_workflow_metadata(existing, metadata)

        existing.status_code = "SUPERSEDED"
        existing.superseded_by = superseding_needs_list
        existing.update_by_id = actor_value
        existing.save(
            update_fields=["status_code", "superseded_by", "update_by_id", "update_dtime"]
        )

        NeedsListAudit.objects.create(
            needs_list=existing,
            action_type="SUPERSEDED",
            field_name="status_code",
            old_value=previous_status,
            new_value="SUPERSEDED",
            notes_text=(
                "Superseded by newer draft "
                f"{superseding_needs_list.needs_list_no or superseding_needs_list.needs_list_id}"
            ),
            actor_user_id=actor_value,
        )
        superseded_ids.append(str(existing.needs_list_id))

    return superseded_ids


def _safe_get_warehouse_name(warehouse_id: int) -> str:
    try:
        return data_access.get_warehouse_name(warehouse_id)
    except Exception as exc:  # pragma: no cover - defensive fallback path
        logger.warning("Warehouse lookup failed for warehouse_id=%s: %s", warehouse_id, exc)
        return f"Warehouse {warehouse_id}"


def _safe_get_event_name(event_id: int) -> str:
    try:
        return data_access.get_event_name(event_id)
    except Exception as exc:  # pragma: no cover - defensive fallback path
        logger.warning("Event lookup failed for event_id=%s: %s", event_id, exc)
        return f"Event {event_id}"


def _execution_stage_fields(
    needs_list: NeedsList,
    metadata: Dict[str, object],
    audit_logs: Iterable[NeedsListAudit] | None = None,
) -> Dict[str, object]:
    fields = {
        "prep_started_by": metadata.get("prep_started_by"),
        "prep_started_at": metadata.get("prep_started_at"),
        "dispatched_by": metadata.get("dispatched_by"),
        "dispatched_at": metadata.get("dispatched_at"),
        "received_by": metadata.get("received_by"),
        "received_at": metadata.get("received_at"),
        "completed_by": metadata.get("completed_by"),
        "completed_at": metadata.get("completed_at"),
    }

    # Backfill from audit history only for legacy rows that have no persisted
    # execution stage metadata at all.
    if any(
        fields.get(key)
        for key in ("prep_started_at", "dispatched_at", "received_at", "completed_at")
    ):
        return fields

    if audit_logs is None:
        status_audits = needs_list.audit_logs.filter(
            action_type="STATUS_CHANGED",
            field_name="status_code",
        ).order_by("action_dtime")
    else:
        status_audits = sorted(
            (
                audit
                for audit in audit_logs
                if audit.action_type == "STATUS_CHANGED"
                and audit.field_name == "status_code"
            ),
            key=lambda audit: audit.action_dtime,
        )
    for audit in status_audits:
        new_value = str(audit.new_value or "").upper()
        actor = audit.actor_user_id
        action_at = audit.action_dtime.isoformat()
        if new_value == "IN_PROGRESS":
            if not fields.get("prep_started_at"):
                fields["prep_started_at"] = action_at
                fields["prep_started_by"] = fields.get("prep_started_by") or actor
            elif not fields.get("dispatched_at"):
                fields["dispatched_at"] = action_at
                fields["dispatched_by"] = fields.get("dispatched_by") or actor
            elif not fields.get("received_at"):
                fields["received_at"] = action_at
                fields["received_by"] = fields.get("received_by") or actor
        elif new_value == "FULFILLED" and not fields.get("completed_at"):
            fields["completed_at"] = action_at
            fields["completed_by"] = fields.get("completed_by") or actor

    return fields


def _normalize_snapshot_item(
    item_data: Dict[str, object],
    *,
    warehouse_id: int | None,
    warehouse_name: str | None,
    item_lookup: Dict[int, Dict[str, str | None]],
) -> Dict[str, object]:
    item_id_int = _coerce_int(item_data.get("item_id"), 0)
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
    if item_data.get("fulfilled_qty") is not None:
        normalized["fulfilled_qty"] = round(_coerce_float(item_data.get("fulfilled_qty"), 0.0), 2)
    if item_data.get("fulfillment_status") is not None:
        normalized["fulfillment_status"] = str(item_data.get("fulfillment_status") or "").strip() or None
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
        calculation_dtime = parsed_as_of
    if calculation_dtime is None:
        calculation_dtime = _utc_now()

    # Calculate totals
    total_gap_qty = sum(
        (_coerce_decimal(item.get('gap_qty', 0)) for item in items),
        Decimal("0"),
    )

    # Create needs list header with retry in case of concurrent needs_list_no generation.
    needs_list: NeedsList | None = None
    last_integrity_error: IntegrityError | None = None
    for _ in range(_NEEDS_LIST_NO_MAX_RETRIES):
        needs_list_no = _generate_needs_list_no(event_id, warehouse_id)
        try:
            with transaction.atomic():
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
                    create_by_id=actor,
                    update_by_id=actor,
                )
                _save_workflow_metadata(
                    needs_list,
                    {
                        "selected_method": selected_method,
                        "selected_item_keys": selected_item_keys,
                        "filters": filters,
                        "warnings": warnings_list,
                    },
                )
            break
        except IntegrityError as exc:
            # Retry only for needs_list_no uniqueness collisions.
            if "needs_list_no" not in str(exc).lower():
                raise
            last_integrity_error = exc

    if needs_list is None:
        if last_integrity_error is not None:
            raise last_integrity_error
        raise RuntimeError("Unable to allocate needs_list_no for draft creation")

    superseded_ids = _supersede_open_scope_records(
        event_id=int(event_id),
        warehouse_id=int(warehouse_id),
        phase=str(phase or ""),
        actor=actor,
        superseding_needs_list=needs_list,
    )
    if superseded_ids:
        metadata = _load_workflow_metadata(needs_list)
        metadata["supersedes_needs_list_ids"] = superseded_ids
        metadata["supersede_reason"] = (
            "Superseded previous draft/submitted needs list records for this scope."
        )
        _save_workflow_metadata(needs_list, metadata)

    # Create line items
    for item_data in items:
        inbound_strict_qty = _coerce_float(item_data.get("inbound_strict_qty"), 0.0)
        inbound_transfer_qty = item_data.get("inbound_transfer_qty")
        inbound_donation_qty = item_data.get("inbound_donation_qty")
        if inbound_transfer_qty is None and inbound_donation_qty is not None:
            derived_transfer_qty = inbound_strict_qty - _coerce_float(inbound_donation_qty, 0.0)
            inbound_transfer_qty = max(derived_transfer_qty, 0.0)

        available_qty = _coerce_float(item_data.get("available_qty"), 0.0)
        coverage_qty = item_data.get("coverage_qty")
        if coverage_qty is None:
            coverage_qty = available_qty + inbound_strict_qty

        time_to_stockout = _coerce_optional_decimal(
            item_data.get("time_to_stockout_hours", item_data.get("time_to_stockout"))
        )

        burn_rate = item_data.get("burn_rate_per_hour")
        if burn_rate is None:
            burn_rate = item_data.get("burn_rate")

        horizon_a_qty = _extract_horizon_qty(item_data, "A")
        horizon_b_qty = _extract_horizon_qty(item_data, "B")
        horizon_c_qty = _extract_horizon_qty(item_data, "C")

        create_kwargs = {
            "needs_list": needs_list,
            "item_id": item_data.get('item_id'),
            "uom_code": item_data.get('uom_code', 'EA'),
            "burn_rate": _coerce_decimal(burn_rate),
            "burn_rate_source": item_data.get('burn_rate_source', 'CALCULATED'),
            "available_stock": _coerce_decimal(available_qty),
            "reserved_qty": _coerce_decimal(item_data.get('reserved_qty')),
            "inbound_procurement_qty": _coerce_decimal(item_data.get('inbound_procurement_qty')),
            "required_qty": _coerce_decimal(item_data.get('required_qty')),
            "coverage_qty": _coerce_decimal(coverage_qty),
            "gap_qty": _coerce_decimal(item_data.get('gap_qty')),
            "time_to_stockout_hours": time_to_stockout,
            "severity_level": item_data.get('severity', 'OK'),
            "horizon_a_qty": _coerce_decimal(horizon_a_qty),
            "horizon_b_qty": _coerce_decimal(horizon_b_qty),
            "horizon_c_qty": _coerce_decimal(horizon_c_qty),
            "create_by_id": actor,
            "update_by_id": actor,
        }
        if inbound_transfer_qty is not None:
            create_kwargs["inbound_transfer_qty"] = _coerce_decimal(inbound_transfer_qty)
        if inbound_donation_qty is not None:
            create_kwargs["inbound_donation_qty"] = _coerce_decimal(inbound_donation_qty)

        NeedsListItem.objects.create(
            **create_kwargs,
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

    queryset = queryset.order_by("-calculation_dtime", "-needs_list_id").prefetch_related(
        "items",
        "audit_logs",
        "audit_logs__needs_list_item",
    )
    needs_lists = list(queryset)
    if not needs_lists:
        return []

    warehouse_ids = sorted({needs_list.warehouse_id for needs_list in needs_lists})
    event_ids = sorted({needs_list.event_id for needs_list in needs_lists})
    warehouse_names, _ = data_access.get_warehouse_names(warehouse_ids)
    event_names, _ = data_access.get_event_names(event_ids)

    all_item_ids = sorted(
        {
            item.item_id
            for needs_list in needs_lists
            for item in needs_list.items.all()
        }
    )
    item_lookup, _ = data_access.get_item_names(all_item_ids)

    return [
        _needs_list_to_dict(
            needs_list,
            warehouse_name=warehouse_names.get(needs_list.warehouse_id),
            event_name=event_names.get(needs_list.event_id),
            db_items=needs_list.items.all(),
            item_lookup=item_lookup,
            audit_logs=needs_list.audit_logs.all(),
        )
        for needs_list in needs_lists
    ]


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
        metadata = _load_workflow_metadata(needs_list)
        metadata_changed = False

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

        stage_keys = (
            "prep_started_by",
            "prep_started_at",
            "dispatched_by",
            "dispatched_at",
            "received_by",
            "received_at",
            "completed_by",
            "completed_at",
        )
        for key in stage_keys:
            if key in record:
                value = record.get(key)
                if value:
                    metadata[key] = value
                    metadata_changed = True

        if metadata_changed:
            _save_workflow_metadata(needs_list, metadata)

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
    stage: str | None = None,
) -> Dict[str, object]:
    """
    Transition needs list to a new status.

    Args:
        record: Needs list record dict
        to_status: New status code
        actor: Username of the user performing the transition
        reason: Optional reason for the transition (for rejections, cancellations)
        stage: Optional execution sub-stage for IN_PROGRESS transitions.

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

    target_status = str(to_status or "").upper()
    requested_stage = _normalize_in_progress_stage(stage)
    if target_status in _IN_PROGRESS_STAGE_BY_STATUS:
        target_status = "IN_PROGRESS"
        if requested_stage is None:
            requested_stage = _normalize_in_progress_stage(to_status)

    metadata = _load_workflow_metadata(needs_list)
    metadata_changed = False
    old_status = needs_list.status_code
    needs_list.status_code = target_status
    needs_list.update_by_id = actor or 'SYSTEM'
    actor_value = actor or "SYSTEM"

    # Update workflow timestamps based on new status
    now = _utc_now()
    now_iso = now.isoformat()
    if target_status == 'PENDING_APPROVAL':
        needs_list.submitted_at = now
        needs_list.submitted_by = actor
    elif target_status == 'UNDER_REVIEW':
        needs_list.under_review_at = now
        needs_list.under_review_by = actor
        # Escalation transitions are mapped to UNDER_REVIEW in DB-backed mode.
        if reason and str(reason).strip():
            metadata["escalated_at"] = now_iso
            metadata["escalated_by"] = actor_value
            metadata["escalation_reason"] = str(reason).strip()
            metadata_changed = True
    elif target_status == 'APPROVED':
        needs_list.reviewed_at = now
        needs_list.reviewed_by = actor
        needs_list.approved_at = now
        needs_list.approved_by = actor
    elif target_status == 'REJECTED':
        needs_list.reviewed_at = now
        needs_list.reviewed_by = actor
        needs_list.rejected_at = now
        needs_list.rejected_by = actor
        needs_list.rejection_reason = reason
    elif target_status == 'RETURNED':
        needs_list.reviewed_at = now
        needs_list.reviewed_by = actor
        needs_list.returned_at = now
        needs_list.returned_by = actor
        needs_list.returned_reason = reason
    elif target_status == 'CANCELLED':
        needs_list.cancelled_at = now
        needs_list.cancelled_by = actor
        needs_list.rejection_reason = reason  # Reuse rejection_reason field

    if target_status == "IN_PROGRESS":
        if requested_stage is None:
            raise ValueError("IN_PROGRESS transitions require an explicit stage.")

        if requested_stage == "IN_PREPARATION":
            if old_status != "APPROVED":
                raise ValueError("Preparation can only start from APPROVED status.")
            if metadata.get("prep_started_at"):
                raise ValueError("Preparation already started.")
            metadata["prep_started_at"] = now_iso
            metadata["prep_started_by"] = actor_value
            metadata_changed = True
        elif requested_stage == "DISPATCHED":
            if not metadata.get("prep_started_at"):
                raise ValueError("Dispatched stage requires preparation to be started first.")
            if metadata.get("dispatched_at"):
                raise ValueError("Needs list already dispatched.")
            metadata["dispatched_at"] = now_iso
            metadata["dispatched_by"] = actor_value
            metadata_changed = True
        elif requested_stage == "RECEIVED":
            if not metadata.get("dispatched_at"):
                raise ValueError("Received stage requires dispatch to be completed first.")
            if metadata.get("received_at"):
                raise ValueError("Needs list already received.")
            metadata["received_at"] = now_iso
            metadata["received_by"] = actor_value
            metadata_changed = True
        else:
            raise ValueError(f"Unsupported IN_PROGRESS stage: {requested_stage}")
    elif target_status == "FULFILLED":
        if not metadata.get("completed_at"):
            metadata["completed_at"] = now_iso
            metadata_changed = True
        if not metadata.get("completed_by"):
            metadata["completed_by"] = actor_value
            metadata_changed = True

    if metadata_changed:
        _save_workflow_metadata(needs_list, metadata)

    needs_list.save()

    # Create audit log for status change
    NeedsListAudit.objects.create(
        needs_list=needs_list,
        action_type='STATUS_CHANGED',
        field_name='status_code',
        old_value=old_status,
        new_value=target_status,
        reason_code=reason if reason else None,
        notes_text=f"Status changed from {old_status} to {target_status}",
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
    items: Iterable[Dict[str, object]] | None = None,
    warnings: Iterable[str] | None = None,
    *,
    warehouse_name: str | None = None,
    event_name: str | None = None,
    db_items: Iterable[NeedsListItem] | None = None,
    item_lookup: Dict[int, Dict[str, str | None]] | None = None,
    audit_logs: Iterable[NeedsListAudit] | None = None,
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
    supersedes_needs_list_ids = metadata.get("supersedes_needs_list_ids")
    if isinstance(supersedes_needs_list_ids, list):
        supersedes_needs_list_ids = [
            str(needs_list_id).strip()
            for needs_list_id in supersedes_needs_list_ids
            if str(needs_list_id).strip()
        ]
    else:
        supersedes_needs_list_ids = []
    if warnings is None:
        raw_warnings = metadata.get("warnings")
        if isinstance(raw_warnings, list):
            warnings = [str(w).strip() for w in raw_warnings if str(w).strip()]
        else:
            warnings = []
    audit_logs_list = list(audit_logs) if audit_logs is not None else None
    stage_fields = _execution_stage_fields(
        needs_list,
        metadata,
        audit_logs=audit_logs_list,
    )

    if warehouse_name is None:
        warehouse_name = _safe_get_warehouse_name(needs_list.warehouse_id)
    if event_name is None:
        event_name = _safe_get_event_name(needs_list.event_id)
    warehouses = [
        {
            "warehouse_id": needs_list.warehouse_id,
            "warehouse_name": warehouse_name,
        }
    ]
    warehouse_ids = [needs_list.warehouse_id]

    # If items not provided, load from database.
    db_items_list: list[NeedsListItem] | None = None

    if items is None:
        db_items_list = list(db_items) if db_items is not None else list(needs_list.items.all())
        if item_lookup is None:
            item_ids = [item.item_id for item in db_items_list]
            item_lookup, _ = data_access.get_item_names(item_ids)
        else:
            item_lookup = dict(item_lookup)

        items = []
        for item in db_items_list:
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
                "fulfilled_qty": float(item.fulfilled_qty),
                "fulfillment_status": item.fulfillment_status,
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
        if item_lookup is None:
            item_ids = [
                item_id_int
                for item in items
                if (item_id_int := _coerce_int(item.get("item_id"), 0)) > 0
            ]
            item_lookup, _ = data_access.get_item_names(item_ids)
        else:
            item_lookup = dict(item_lookup)
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
    adjusted_items: Iterable[NeedsListItem]
    if db_items_list is None:
        adjusted_items = needs_list.items.filter(adjusted_qty__isnull=False)
    else:
        adjusted_items = [item for item in db_items_list if item.adjusted_qty is not None]

    for item in adjusted_items:
        line_overrides[str(item.item_id)] = {
            'overridden_qty': float(item.adjusted_qty),
            'reason': item.adjustment_notes or '',
            'updated_by': item.adjusted_by,
            'updated_at': item.adjusted_at.isoformat() if item.adjusted_at else None,
        }

    # Build line review notes dict from audit logs
    line_review_notes = {}
    if audit_logs_list is None:
        comment_audits = needs_list.audit_logs.filter(action_type='COMMENT_ADDED').order_by('-action_dtime')
    else:
        comment_audits = sorted(
            (audit for audit in audit_logs_list if audit.action_type == 'COMMENT_ADDED'),
            key=lambda audit: audit.action_dtime,
            reverse=True,
        )

    for audit in comment_audits:
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
        'prep_started_by': stage_fields.get("prep_started_by"),
        'prep_started_at': stage_fields.get("prep_started_at"),
        'dispatched_by': stage_fields.get("dispatched_by"),
        'dispatched_at': stage_fields.get("dispatched_at"),
        'received_by': stage_fields.get("received_by"),
        'received_at': stage_fields.get("received_at"),
        'completed_by': stage_fields.get("completed_by"),
        'completed_at': stage_fields.get("completed_at"),
        'cancelled_by': needs_list.cancelled_by if needs_list.status_code == 'CANCELLED' else None,
        'cancelled_at': needs_list.cancelled_at.isoformat() if needs_list.status_code == 'CANCELLED' and needs_list.cancelled_at else None,
        'cancel_reason': needs_list.rejection_reason if needs_list.status_code == 'CANCELLED' else None,
        'escalated_by': metadata.get("escalated_by"),
        'escalated_at': metadata.get("escalated_at"),
        'escalation_reason': metadata.get("escalation_reason"),
        'superseded_by': str(needs_list.superseded_by_id) if needs_list.superseded_by_id else None,
        'superseded_at': metadata.get("superseded_at"),
        'superseded_by_actor': metadata.get("superseded_by"),
        'superseded_by_needs_list_id': metadata.get("superseded_by_needs_list_id"),
        'supersedes_needs_list_ids': supersedes_needs_list_ids,
        'supersede_reason': metadata.get("supersede_reason") or metadata.get("superseded_reason"),
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
