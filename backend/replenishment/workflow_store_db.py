"""
Database-backed workflow store for needs list management.

All needs lists, line items, workflow metadata, and audit trails are stored in the
database so the live request path has one authoritative persistence mechanism.
"""

from __future__ import annotations

import logging
import json
from datetime import datetime, timezone
from functools import lru_cache
from typing import Dict, Iterable, Sequence, Tuple
from django.db import IntegrityError, connection, connections, transaction
from django.db.models import CharField, DateTimeField, OuterRef, Q, QuerySet, Subquery, Sum, Value
from django.db.models.expressions import RawSQL
from django.db.models.functions import Cast, Coalesce
from django.core.exceptions import ObjectDoesNotExist
from django.utils.dateparse import parse_datetime
from decimal import Decimal, InvalidOperation

from .legacy_models import Warehouse
from .models import (
    NeedsList,
    NeedsListAllocationLine,
    NeedsListItem,
    NeedsListAudit,
)
from .services import data_access, phase_window_policy

logger = logging.getLogger("dmis.audit")

_STATUS_ALIASES = {
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

_NEEDS_LIST_NO_MAX_RETRIES = 5
_SUPERSEDE_CANDIDATE_STATUSES = {
    "DRAFT",
    "MODIFIED",
    "SUBMITTED",
    # Legacy values remain here so older rows are handled safely until migrated.
    "RETURNED",
    "PENDING",
    "PENDING_APPROVAL",
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


@lru_cache(maxsize=1)
def _have_warehouse_table() -> bool:
    return "warehouse" in connection.introspection.table_names()


def _normalize_actor(value: object) -> str:
    return str(value or "").strip().lower()


def _canonical_status(value: object) -> str:
    normalized = str(value or "").strip().upper()
    if not normalized:
        return ""
    return _STATUS_ALIASES.get(normalized, normalized)


def _status_filter_values(statuses: Iterable[object] | None) -> list[str]:
    values: set[str] = set()
    for status in statuses or []:
        raw = str(status or "").strip().upper()
        if not raw:
            continue
        canonical = _canonical_status(raw)
        if canonical:
            values.add(canonical)
        values.add(raw)
        values.update(
            alias
            for alias, target in _STATUS_ALIASES.items()
            if target == canonical
        )
    return sorted(values)


def _record_owned_by_actor(needs_list: NeedsList, actor: str | None) -> bool:
    normalized_actor = _normalize_actor(actor)
    if not normalized_actor:
        return False

    owner = _normalize_actor(getattr(needs_list, "create_by_id", None))
    return bool(owner) and owner == normalized_actor


def _iso_or_none(value: object) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()  # type: ignore[union-attr]
    return str(value).strip() or None


def _normalize_status_filters(statuses: Iterable[object] | None) -> list[str]:
    return _status_filter_values(statuses)


_FRESHNESS_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


def _normalize_freshness_level(value: object) -> str | None:
    normalized = str(value or "").strip().upper()
    return normalized if normalized in _FRESHNESS_ORDER else None


def _item_freshness_level(item_data: Dict[str, object]) -> str | None:
    freshness = item_data.get("freshness")
    if isinstance(freshness, dict):
        level = _normalize_freshness_level(freshness.get("state"))
        if level:
            return level
    return _normalize_freshness_level(
        item_data.get("freshness_state") or item_data.get("data_freshness_level")
    )


def _overall_freshness_level(items: Iterable[Dict[str, object]]) -> str:
    levels = [
        level
        for item in items
        if (level := _item_freshness_level(item)) is not None
    ]
    if not levels:
        return "HIGH"
    return min(levels, key=lambda level: _FRESHNESS_ORDER[level])


def _stockout_hours_value(item_data: Dict[str, object]) -> float | None:
    raw_value = item_data.get("time_to_stockout_hours", item_data.get("time_to_stockout"))
    parsed = _coerce_optional_decimal(raw_value)
    return float(parsed) if parsed is not None else None


def _severity_from_stockout_hours(stockout_hours: float | None) -> str:
    if stockout_hours is None:
        return "OK"
    if stockout_hours < 8:
        return "CRITICAL"
    if stockout_hours < 24:
        return "WARNING"
    if stockout_hours < 72:
        return "WATCH"
    return "OK"


def _normalize_severity(item_data: Dict[str, object]) -> str:
    normalized = str(
        item_data.get("severity") or item_data.get("severity_level") or ""
    ).strip().upper()
    if normalized in {"CRITICAL", "WARNING", "WATCH", "OK"}:
        return normalized
    return _severity_from_stockout_hours(_stockout_hours_value(item_data))


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


def _workflow_metadata_table_name(*, db_connection=None) -> str:
    active_connection = db_connection or connection
    quoted_table_name = active_connection.ops.quote_name(_WORKFLOW_METADATA_TABLE_NAME)
    if active_connection.vendor == "postgresql":
        quoted_schema_name = active_connection.ops.quote_name("public")
        return f"{quoted_schema_name}.{quoted_table_name}"
    return quoted_table_name


def _workflow_needs_list_table_name(*, db_connection=None) -> str:
    active_connection = db_connection or connection
    metadata_table_name = _workflow_metadata_table_name(db_connection=active_connection)
    if "." in metadata_table_name:
        schema_name, _ = metadata_table_name.split(".", 1)
        return f"{schema_name}.{active_connection.ops.quote_name('needs_list')}"
    return active_connection.ops.quote_name("needs_list")


def _have_workflow_metadata_table() -> bool:
    return _WORKFLOW_METADATA_TABLE_NAME in connection.introspection.table_names()


def _workflow_legacy_selected_method_sql() -> str:
    needs_list_table_name = connection.ops.quote_name(NeedsList._meta.db_table)
    if connection.vendor == "postgresql":
        legacy_expr = (
            "UPPER(COALESCE("
            "NULLIF("
            f"SUBSTRING(COALESCE({needs_list_table_name}.notes_text, '') "
            "FROM '\"selected_method\"\\s*:\\s*\"([^\"]+)\"'),"
            "''"
            "), "
            "''))"
        )
    else:
        legacy_expr = (
            "UPPER(COALESCE("
            f"CASE WHEN json_valid(COALESCE({needs_list_table_name}.notes_text, '')) "
            f"THEN json_extract({needs_list_table_name}.notes_text, '$.selected_method') "
            "ELSE NULL END, ''))"
        )
    return legacy_expr


def _workflow_selected_method_sql(*, include_metadata: bool = True) -> str:
    if not include_metadata:
        return _workflow_legacy_selected_method_sql()

    metadata_table_name = _workflow_metadata_table_name()
    metadata_expr = (
        f"SELECT UPPER(COALESCE(metadata_json ->> 'selected_method', '')) "
        f"FROM {metadata_table_name} "
        f"WHERE {metadata_table_name}.needs_list_id = {connection.ops.quote_name(NeedsList._meta.db_table)}.needs_list_id"
    ) if connection.vendor == "postgresql" else (
        f"SELECT UPPER(COALESCE(json_extract(metadata_json, '$.selected_method'), '')) "
        f"FROM {metadata_table_name} "
        f"WHERE {metadata_table_name}.needs_list_id = {connection.ops.quote_name(NeedsList._meta.db_table)}.needs_list_id"
    )
    return f"COALESCE(NULLIF(({metadata_expr}), ''), {_workflow_legacy_selected_method_sql()})"


def _ensure_workflow_metadata_table(*, using: str | None = None) -> None:
    db_connection = connections[using or "default"]
    table_name = _workflow_metadata_table_name(db_connection=db_connection)
    needs_list_table_name = _workflow_needs_list_table_name(db_connection=db_connection)
    with db_connection.cursor() as cursor:
        if db_connection.vendor == "postgresql":
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
    if _have_workflow_metadata_table():
        try:
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
    return _parse_workflow_metadata(needs_list.notes_text)


def _load_workflow_metadata_map(needs_lists: Iterable[NeedsList]) -> Dict[int, Dict[str, object]]:
    needs_list_rows = list(needs_lists)
    metadata_by_id: Dict[int, Dict[str, object]] = {}
    needs_list_ids = [int(needs_list.needs_list_id) for needs_list in needs_list_rows]

    if needs_list_ids and _have_workflow_metadata_table():
        try:
            table_name = _workflow_metadata_table_name()
            placeholders = ",".join(["%s"] * len(needs_list_ids))
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT needs_list_id, metadata_json
                    FROM {table_name}
                    WHERE needs_list_id IN ({placeholders})
                    """,
                    needs_list_ids,
                )
                for raw_needs_list_id, raw_metadata in cursor.fetchall():
                    parsed = _parse_workflow_metadata(raw_metadata)
                    if parsed:
                        metadata_by_id[int(raw_needs_list_id)] = parsed
        except Exception as exc:  # pragma: no cover - defensive fallback path
            logger.warning(
                "Workflow metadata bulk lookup failed for needs_list_ids=%s: %s",
                needs_list_ids,
                exc,
            )

    for needs_list in needs_list_rows:
        needs_list_id = int(needs_list.needs_list_id)
        if needs_list_id in metadata_by_id:
            continue
        legacy = _parse_workflow_metadata(needs_list.notes_text)
        if legacy:
            metadata_by_id[needs_list_id] = legacy

    return metadata_by_id


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


def _line_target_qty(item: NeedsListItem) -> Decimal:
    return item.adjusted_qty if item.adjusted_qty is not None else item.required_qty


def _fulfillment_status_for_quantities(fulfilled_qty: Decimal, target_qty: Decimal) -> str:
    if target_qty <= 0 or fulfilled_qty >= target_qty:
        return "FULFILLED"
    if fulfilled_qty > 0:
        return "PARTIAL"
    return "PENDING"


def _record_line_fulfillment_change(
    *,
    needs_list: NeedsList,
    item: NeedsListItem,
    old_status: str,
    new_status: str,
    actor: str,
    notes: str,
) -> None:
    if old_status == new_status:
        return
    NeedsListAudit.objects.create(
        needs_list=needs_list,
        needs_list_item=item,
        action_type="FULFILLED" if new_status == "FULFILLED" else "STATUS_CHANGED",
        field_name="fulfillment_status",
        old_value=old_status,
        new_value=new_status,
        notes_text=notes,
        actor_user_id=actor,
    )


def _apply_received_allocations_to_lines(needs_list: NeedsList, actor: str) -> None:
    allocation_totals = {
        int(row["item_id"]): Decimal(str(row["allocated_qty"] or "0"))
        for row in NeedsListAllocationLine.objects.filter(needs_list=needs_list)
        .values("item_id")
        .annotate(allocated_qty=Sum("allocated_qty"))
    }
    if not allocation_totals:
        return

    for item in needs_list.items.select_for_update():
        received_qty = allocation_totals.get(int(item.item_id))
        if received_qty is None or received_qty <= 0:
            continue

        old_status = item.fulfillment_status
        target_qty = _line_target_qty(item)
        item.fulfilled_qty = min(item.fulfilled_qty + received_qty, target_qty)
        item.coverage_qty = max(item.coverage_qty, min(target_qty, item.fulfilled_qty))
        item.fulfillment_status = _fulfillment_status_for_quantities(
            item.fulfilled_qty,
            target_qty,
        )
        item.update_by_id = actor
        item.save(
            update_fields=[
                "fulfilled_qty",
                "coverage_qty",
                "fulfillment_status",
                "update_by_id",
                "update_dtime",
            ]
        )
        _record_line_fulfillment_change(
            needs_list=needs_list,
            item=item,
            old_status=old_status,
            new_status=item.fulfillment_status,
            actor=actor,
            notes="Fulfillment updated from received allocation quantities.",
        )


def _mark_all_lines_fulfilled(needs_list: NeedsList, actor: str) -> None:
    for item in needs_list.items.select_for_update():
        old_status = item.fulfillment_status
        target_qty = _line_target_qty(item)
        item.fulfilled_qty = target_qty
        item.coverage_qty = max(item.coverage_qty, target_qty)
        item.fulfillment_status = "FULFILLED"
        item.update_by_id = actor
        item.save(
            update_fields=[
                "fulfilled_qty",
                "coverage_qty",
                "fulfillment_status",
                "update_by_id",
                "update_dtime",
            ]
        )
        _record_line_fulfillment_change(
            needs_list=needs_list,
            item=item,
            old_status=old_status,
            new_status=item.fulfillment_status,
            actor=actor,
            notes="Needs list completion marked remaining line quantity fulfilled.",
        )


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
    effective_criticality_level = str(
        item_data.get("effective_criticality_level")
        or item_data.get("criticality_level")
        or "NORMAL"
    ).strip().upper()
    if effective_criticality_level not in {"CRITICAL", "HIGH", "NORMAL", "LOW"}:
        effective_criticality_level = "NORMAL"
    effective_criticality_source = str(
        item_data.get("effective_criticality_source")
        or item_data.get("criticality_source")
        or "ITEM_DEFAULT"
    ).strip().upper()
    if effective_criticality_source not in {
        "EVENT_OVERRIDE",
        "HAZARD_TYPE_DEFAULT",
        "ITEM_DEFAULT",
    }:
        effective_criticality_source = "ITEM_DEFAULT"

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
        "effective_criticality_level": effective_criticality_level,
        "effective_criticality_source": effective_criticality_source,
        "criticality_level": effective_criticality_level,
        "criticality_source": effective_criticality_source,
        "warehouse_id": item_data.get("warehouse_id") or warehouse_id,
        "warehouse_name": item_data.get("warehouse_name") or warehouse_name,
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
        "severity": _normalize_severity(item_data),
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
    normalized_snapshot_items = [
        _normalize_snapshot_item(
            dict(item),
            warehouse_id=_coerce_int(warehouse_id, 0) or None,
            warehouse_name=None,
            item_lookup={},
        )
        for item in items
        if isinstance(item, dict)
    ]
    data_freshness_level = _overall_freshness_level(normalized_snapshot_items)

    windows = phase_window_policy.get_effective_phase_windows(int(event_id), str(phase or "BASELINE"))
    demand_window_hours = int(windows["demand_hours"])
    planning_window_hours = int(windows["planning_hours"])
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
                    data_freshness_level=data_freshness_level,
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
                        "data_freshness_level": data_freshness_level,
                        "snapshot_items": normalized_snapshot_items,
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
    created_line_items: list[tuple[NeedsListItem, str, str]] = []
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
        effective_criticality_level = str(
            item_data.get("effective_criticality_level")
            or item_data.get("criticality_level")
            or "NORMAL"
        ).strip().upper()
        if effective_criticality_level not in {"CRITICAL", "HIGH", "NORMAL", "LOW"}:
            effective_criticality_level = "NORMAL"
        effective_criticality_source = str(
            item_data.get("effective_criticality_source")
            or item_data.get("criticality_source")
            or "ITEM_DEFAULT"
        ).strip().upper()
        if effective_criticality_source not in {
            "EVENT_OVERRIDE",
            "HAZARD_TYPE_DEFAULT",
            "ITEM_DEFAULT",
        }:
            effective_criticality_source = "ITEM_DEFAULT"

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
            "severity_level": _normalize_severity(item_data),
            "effective_criticality_level": effective_criticality_level,
            "effective_criticality_source": effective_criticality_source,
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

        created_item = NeedsListItem.objects.create(
            **create_kwargs,
        )
        created_line_items.append(
            (
                created_item,
                effective_criticality_level,
                effective_criticality_source,
            )
        )

    # Create audit log entry
    NeedsListAudit.objects.create(
        needs_list=needs_list,
        action_type='CREATED',
        notes_text=f"Created with {len(items)} items. Warnings: {', '.join(warnings_list) if warnings_list else 'None'}",
        actor_user_id=actor,
    )
    for created_item, criticality_level, criticality_source in created_line_items:
        NeedsListAudit.objects.create(
            needs_list=needs_list,
            needs_list_item=created_item,
            action_type="CREATED",
            field_name="criticality_level",
            old_value=None,
            new_value=criticality_level,
            reason_code=criticality_source,
            notes_text="Effective criticality captured for draft generation.",
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


def _record_queryset(
    statuses: Iterable[object] | None = None,
    *,
    mine_actor: str | None = None,
    owner_visibility_actor: str | None = None,
    owner_visibility_statuses: Iterable[object] | None = None,
    event_id: int | None = None,
    warehouse_id: int | None = None,
    phase: str | None = None,
    exclude_statuses: Iterable[object] | None = None,
    allowed_warehouse_ids: Iterable[int] | None = None,
):
    queryset = NeedsList.objects.all()

    normalized_statuses = _normalize_status_filters(statuses)
    if normalized_statuses:
        queryset = queryset.filter(status_code__in=normalized_statuses)

    normalized_excluded_statuses = _normalize_status_filters(exclude_statuses)
    if normalized_excluded_statuses:
        queryset = queryset.exclude(status_code__in=normalized_excluded_statuses)

    normalized_mine_actor = _normalize_actor(mine_actor)
    normalized_owner_actor = _normalize_actor(owner_visibility_actor)
    normalized_owner_statuses = _normalize_status_filters(owner_visibility_statuses)
    if normalized_mine_actor:
        queryset = queryset.filter(create_by_id__iexact=normalized_mine_actor)
    elif normalized_owner_statuses:
        if normalized_owner_actor:
            queryset = queryset.exclude(
                ~Q(create_by_id__iexact=normalized_owner_actor)
                & Q(status_code__in=normalized_owner_statuses)
            )
        else:
            queryset = queryset.exclude(status_code__in=normalized_owner_statuses)

    if event_id is not None:
        queryset = queryset.filter(event_id=event_id)
    if warehouse_id is not None:
        queryset = queryset.filter(warehouse_id=warehouse_id)
    if phase:
        queryset = queryset.filter(event_phase=str(phase or "").strip().upper())

    if allowed_warehouse_ids is not None:
        scoped_warehouse_ids = sorted(
            {
                int(candidate)
                for candidate in allowed_warehouse_ids
                if candidate is not None
            }
        )
        if not scoped_warehouse_ids:
            return NeedsList.objects.none()
        queryset = queryset.filter(warehouse_id__in=scoped_warehouse_ids)

    return queryset


def _header_queryset(
    statuses: Iterable[object] | None = None,
    *,
    mine_actor: str | None = None,
    owner_visibility_actor: str | None = None,
    owner_visibility_statuses: Iterable[object] | None = None,
    event_id: int | None = None,
    warehouse_id: int | None = None,
    phase: str | None = None,
    exclude_statuses: Iterable[object] | None = None,
    allowed_warehouse_ids: Iterable[int] | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    sort_by: str = "date",
    sort_order: str = "desc",
) -> QuerySet[NeedsList]:
    if _have_warehouse_table():
        warehouse_name_annotation = Coalesce(
            Subquery(
                Warehouse.objects.filter(
                    warehouse_id=OuterRef("warehouse_id")
                ).values("warehouse_name")[:1]
            ),
            Value(""),
        )
    else:
        warehouse_name_annotation = Cast("warehouse_id", output_field=CharField())
    queryset = _record_queryset(
        statuses,
        mine_actor=mine_actor,
        owner_visibility_actor=owner_visibility_actor,
        owner_visibility_statuses=owner_visibility_statuses,
        event_id=event_id,
        warehouse_id=warehouse_id,
        phase=phase,
        exclude_statuses=exclude_statuses,
        allowed_warehouse_ids=allowed_warehouse_ids,
    ).annotate(
        submission_sort_at=Coalesce(
            "update_dtime",
            "approved_at",
            "submitted_at",
            "create_dtime",
            output_field=DateTimeField(),
        ),
        warehouse_name_sort=warehouse_name_annotation,
    )

    if date_from is not None:
        queryset = queryset.filter(submission_sort_at__gte=date_from)
    if date_to is not None:
        queryset = queryset.filter(submission_sort_at__lte=date_to)

    descending = str(sort_order or "desc").strip().lower() != "asc"
    if sort_by == "status":
        primary_field = "status_code"
    elif sort_by == "warehouse":
        primary_field = "warehouse_name_sort"
    else:
        primary_field = "submission_sort_at"

    primary_order = f"-{primary_field}" if descending else primary_field
    secondary_order = "-needs_list_id" if descending else "needs_list_id"
    return queryset.order_by(primary_order, secondary_order)


def _serialize_record_headers(needs_lists: Sequence[NeedsList]) -> list[Dict[str, object]]:
    needs_list_rows = list(needs_lists)
    if not needs_list_rows:
        return []

    warehouse_names, _ = data_access.get_warehouse_names(
        [needs_list.warehouse_id for needs_list in needs_list_rows]
    )
    event_names, _ = data_access.get_event_names(
        [needs_list.event_id for needs_list in needs_list_rows]
    )
    metadata_by_id = _load_workflow_metadata_map(needs_list_rows)

    headers: list[Dict[str, object]] = []
    for needs_list in needs_list_rows:
        needs_list_id = int(needs_list.needs_list_id)
        metadata = metadata_by_id.get(needs_list_id, {})
        selected_method = metadata.get("selected_method")
        warehouse_name = warehouse_names.get(
            needs_list.warehouse_id,
            f"Warehouse {needs_list.warehouse_id}",
        )
        event_name = event_names.get(
            needs_list.event_id,
            f"Event {needs_list.event_id}",
        )
        headers.append(
            {
                "needs_list_id": str(needs_list_id),
                "needs_list_no": needs_list.needs_list_no,
                "status": _canonical_status(needs_list.status_code),
                "event_id": needs_list.event_id,
                "event_name": event_name,
                "warehouse_id": needs_list.warehouse_id,
                "warehouse_name": warehouse_name,
                "phase": needs_list.event_phase,
                "data_freshness_level": needs_list.data_freshness_level,
                "selected_method": selected_method,
                "created_by": needs_list.create_by_id,
                "created_at": _iso_or_none(needs_list.create_dtime),
                "updated_at": _iso_or_none(needs_list.update_dtime),
                "submitted_at": _iso_or_none(needs_list.submitted_at),
                "approved_at": _iso_or_none(needs_list.approved_at),
            }
        )

    return headers


def list_record_headers(
    statuses: Iterable[object] | None = None,
    *,
    mine_actor: str | None = None,
    owner_visibility_actor: str | None = None,
    owner_visibility_statuses: Iterable[object] | None = None,
    event_id: int | None = None,
    warehouse_id: int | None = None,
    phase: str | None = None,
    exclude_statuses: Iterable[object] | None = None,
    allowed_warehouse_ids: Iterable[int] | None = None,
) -> list[Dict[str, object]]:
    queryset = (
        _record_queryset(
            statuses,
            mine_actor=mine_actor,
            owner_visibility_actor=owner_visibility_actor,
            owner_visibility_statuses=owner_visibility_statuses,
            event_id=event_id,
            warehouse_id=warehouse_id,
            phase=phase,
            exclude_statuses=exclude_statuses,
            allowed_warehouse_ids=allowed_warehouse_ids,
        )
        .only(
            "needs_list_id",
            "needs_list_no",
            "event_id",
            "warehouse_id",
            "event_phase",
            "data_freshness_level",
            "status_code",
            "create_by_id",
            "create_dtime",
            "update_dtime",
            "submitted_at",
            "approved_at",
            "notes_text",
        )
        .order_by("-calculation_dtime", "-needs_list_id")
    )
    needs_lists = list(queryset)
    return _serialize_record_headers(needs_lists)


def list_record_headers_page(
    statuses: Iterable[object] | None = None,
    *,
    mine_actor: str | None = None,
    owner_visibility_actor: str | None = None,
    owner_visibility_statuses: Iterable[object] | None = None,
    event_id: int | None = None,
    warehouse_id: int | None = None,
    phase: str | None = None,
    exclude_statuses: Iterable[object] | None = None,
    allowed_warehouse_ids: Iterable[int] | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    sort_by: str = "date",
    sort_order: str = "desc",
    method_filter: str | None = None,
    offset: int = 0,
    limit: int = 10,
) -> tuple[list[Dict[str, object]], int]:
    offset = max(int(offset), 0)
    limit = max(int(limit), 1)
    queryset = (
        _header_queryset(
            statuses,
            mine_actor=mine_actor,
            owner_visibility_actor=owner_visibility_actor,
            owner_visibility_statuses=owner_visibility_statuses,
            event_id=event_id,
            warehouse_id=warehouse_id,
            phase=phase,
            exclude_statuses=exclude_statuses,
            allowed_warehouse_ids=allowed_warehouse_ids,
            date_from=date_from,
            date_to=date_to,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        .only(
            "needs_list_id",
            "needs_list_no",
            "event_id",
            "warehouse_id",
            "event_phase",
            "data_freshness_level",
            "status_code",
            "create_by_id",
            "create_dtime",
            "update_dtime",
            "submitted_at",
            "approved_at",
            "notes_text",
        )
    )

    normalized_method = str(method_filter or "").strip().upper()
    if not normalized_method:
        total_count = queryset.count()
        needs_lists = list(queryset[offset: offset + limit])
        return _serialize_record_headers(needs_lists), total_count

    selected_method_sql = _workflow_selected_method_sql(
        include_metadata=_have_workflow_metadata_table()
    )
    filtered_queryset = queryset.annotate(
        selected_method_filter=RawSQL(f"({selected_method_sql})", [])
    ).filter(selected_method_filter=normalized_method)
    total_count = filtered_queryset.count()
    needs_lists = list(filtered_queryset[offset: offset + limit])
    return _serialize_record_headers(needs_lists), total_count


def get_records_by_ids(
    needs_list_ids: Iterable[object],
    *,
    base_queryset: QuerySet[NeedsList],
    include_audit_logs: bool = True,
) -> list[Dict[str, object]]:
    ordered_ids: list[int] = []
    seen_ids: set[int] = set()
    for raw_needs_list_id in needs_list_ids:
        try:
            parsed_needs_list_id = int(str(raw_needs_list_id).strip())
        except (TypeError, ValueError):
            continue
        if parsed_needs_list_id in seen_ids:
            continue
        seen_ids.add(parsed_needs_list_id)
        ordered_ids.append(parsed_needs_list_id)

    if not ordered_ids:
        return []

    prefetch_paths = ["items"]
    if include_audit_logs:
        prefetch_paths.extend(["audit_logs", "audit_logs__needs_list_item"])

    needs_lists = list(
        base_queryset.filter(needs_list_id__in=ordered_ids)
        .prefetch_related(*prefetch_paths)
    )
    if not needs_lists:
        return []

    needs_list_by_id = {
        int(needs_list.needs_list_id): needs_list for needs_list in needs_lists
    }
    ordered_needs_lists = [
        needs_list_by_id[needs_list_id]
        for needs_list_id in ordered_ids
        if needs_list_id in needs_list_by_id
    ]
    if not ordered_needs_lists:
        return []

    warehouse_names, _ = data_access.get_warehouse_names(
        sorted(
            {
                needs_list.warehouse_id
                for needs_list in ordered_needs_lists
                if needs_list.warehouse_id is not None
            }
        )
    )
    event_names, _ = data_access.get_event_names(
        sorted(
            {
                needs_list.event_id
                for needs_list in ordered_needs_lists
                if needs_list.event_id is not None
            }
        )
    )
    all_item_ids = sorted(
        {
            item.item_id
            for needs_list in ordered_needs_lists
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
            audit_logs=needs_list.audit_logs.all() if include_audit_logs else None,
        )
        for needs_list in ordered_needs_lists
    ]


def list_records(
    statuses: list[str] | None = None,
    *,
    allowed_warehouse_ids: Iterable[int] | None = None,
    include_audit_logs: bool = True,
) -> list[Dict[str, object]]:
    """
    List needs list records, optionally filtered by status.

    Accepts legacy API status aliases and maps them to database status values.
    """
    base_queryset = _record_queryset(
        statuses,
        allowed_warehouse_ids=allowed_warehouse_ids,
    )
    needs_list_ids = list(
        base_queryset
        .order_by("-calculation_dtime", "-needs_list_id")
        .values_list("needs_list_id", flat=True)
    )
    return get_records_by_ids(
        needs_list_ids,
        base_queryset=base_queryset,
        include_audit_logs=include_audit_logs,
    )


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
            needs_list.status_code = _canonical_status(record['status'])
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

    requested_status = str(to_status or "").strip().upper()
    target_status = _canonical_status(requested_status)
    requested_stage = _normalize_in_progress_stage(stage)
    if requested_status in _IN_PROGRESS_STAGE_BY_STATUS:
        target_status = "IN_PROGRESS"
        if requested_stage is None:
            requested_stage = _normalize_in_progress_stage(requested_status)

    metadata = _load_workflow_metadata(needs_list)
    metadata_changed = False
    old_status = _canonical_status(needs_list.status_code)
    needs_list.status_code = target_status
    needs_list.update_by_id = actor or 'SYSTEM'
    actor_value = actor or "SYSTEM"

    # Update workflow timestamps based on new status
    now = _utc_now()
    now_iso = now.isoformat()
    if target_status == 'SUBMITTED':
        if requested_status == "ESCALATED":
            needs_list.under_review_at = now
            needs_list.under_review_by = actor
        elif old_status != "SUBMITTED" or not needs_list.submitted_at:
            needs_list.submitted_at = now
            needs_list.submitted_by = actor
        if requested_status == "ESCALATED" and reason and str(reason).strip():
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
        if requested_status == 'CANCELLED':
            needs_list.cancelled_at = now
            needs_list.cancelled_by = actor
    elif target_status == 'MODIFIED':
        needs_list.reviewed_at = now
        needs_list.reviewed_by = actor
        needs_list.returned_at = now
        needs_list.returned_by = actor
        needs_list.returned_reason = reason
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
            _apply_received_allocations_to_lines(needs_list, actor_value)
        else:
            raise ValueError(f"Unsupported IN_PROGRESS stage: {requested_stage}")
    elif target_status == "FULFILLED":
        if not metadata.get("completed_at"):
            metadata["completed_at"] = now_iso
            metadata_changed = True
        if not metadata.get("completed_by"):
            metadata["completed_by"] = actor_value
            metadata_changed = True
        _mark_all_lines_fulfilled(needs_list, actor_value)

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
    # Database store is always enabled.
    return None


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
    snapshot_items_by_id: dict[int, Dict[str, object]] = {}
    raw_snapshot_items = metadata.get("snapshot_items")
    if isinstance(raw_snapshot_items, list):
        for raw_item in raw_snapshot_items:
            if not isinstance(raw_item, dict):
                continue
            item_id = _coerce_int(raw_item.get("item_id"), 0)
            if item_id > 0:
                snapshot_items_by_id[item_id] = dict(raw_item)
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
            snapshot_item = snapshot_items_by_id.get(item.item_id, {})
            time_to_stockout_value = (
                float(item.time_to_stockout_hours)
                if item.time_to_stockout_hours is not None
                else snapshot_item.get(
                    "time_to_stockout",
                    snapshot_item.get("time_to_stockout_hours"),
                )
            )
            raw_item = {
                **snapshot_item,
                "item_id": item.item_id,
                "uom_code": item.uom_code,
                "burn_rate": float(item.burn_rate),
                "burn_rate_source": item.burn_rate_source,
                "effective_criticality_level": item.effective_criticality_level,
                "effective_criticality_source": item.effective_criticality_source,
                "available_qty": float(item.available_stock),
                "reserved_qty": float(item.reserved_qty),
                "inbound_transfer_qty": float(item.inbound_transfer_qty),
                "inbound_donation_qty": float(item.inbound_donation_qty),
                "inbound_procurement_qty": float(item.inbound_procurement_qty),
                "required_qty": float(item.required_qty),
                "coverage_qty": float(item.coverage_qty),
                "gap_qty": float(item.gap_qty),
                "time_to_stockout": time_to_stockout_value,
                "time_to_stockout_hours": time_to_stockout_value,
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
        'data_freshness_level': needs_list.data_freshness_level,
        'planning_window_days': needs_list.planning_window_hours / 24,  # Convert back to days
        'filters': filters,
        'status': _canonical_status(needs_list.status_code),
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
        'cancelled_by': needs_list.cancelled_by,
        'cancelled_at': needs_list.cancelled_at.isoformat() if needs_list.cancelled_at else None,
        'cancel_reason': needs_list.rejection_reason if needs_list.cancelled_at else None,
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
        'return_reason': needs_list.returned_reason,
        'rejected_by': needs_list.rejected_by,
        'rejected_at': needs_list.rejected_at.isoformat() if needs_list.rejected_at else None,
        'reject_reason': needs_list.rejection_reason if _canonical_status(needs_list.status_code) == 'REJECTED' else None,
        'line_overrides': line_overrides,
        'line_review_notes': line_review_notes,
        'selected_method': selected_method,
        'selected_item_keys': selected_item_keys,
        'snapshot': {
            'items': items,
            'warnings': list(warnings),
            'data_freshness_level': needs_list.data_freshness_level,
            'planning_window_days': needs_list.planning_window_hours / 24,
            'as_of_datetime': calculation_as_of,
            'event_name': event_name,
            'warehouse_ids': warehouse_ids,
            'warehouses': warehouses,
            'selected_method': selected_method,
        },
    }
