from __future__ import annotations

import logging
import os
import re
from typing import Dict, List, Tuple

from django.conf import settings
from django.db import DatabaseError, connection
from django.utils import timezone

logger = logging.getLogger(__name__)

CRITICALITY_LEVELS = {"CRITICAL", "HIGH", "NORMAL", "LOW"}

SOURCE_EVENT_OVERRIDE = "EVENT_OVERRIDE"
SOURCE_HAZARD_DEFAULT = "HAZARD_TYPE_DEFAULT"
SOURCE_ITEM_DEFAULT = "ITEM_DEFAULT"

_TABLE_EVENT_OVERRIDE = "event_item_criticality_override"
_TABLE_HAZARD_DEFAULT = "hazard_item_criticality"

_EVENT_TYPE_COLUMNS = ("event_type", "event_type_code", "hazard_type")
_EVENT_ID_COLUMNS = ("event_id", "eligible_event_id")
_ACTIVE_FLAG_COLUMNS = ("is_active", "active_flag", "enabled_flag")
_ACTIVE_STATUS_COLUMNS = ("status_code", "state_code")
_APPROVAL_STATUS_COLUMNS = ("approval_status", "review_status")
_START_COLUMNS = ("effective_from", "effective_start", "effective_start_dtime", "start_dtime")
_END_COLUMNS = ("effective_to", "effective_end", "effective_end_dtime", "end_dtime", "expires_at")
_ORDER_COLUMNS = (
    "effective_from",
    "effective_start",
    "effective_start_dtime",
    "start_dtime",
    "update_dtime",
    "updated_at",
    "update_at",
    "create_dtime",
    "created_at",
    "hazard_item_criticality_id",
    "override_id",
)


def _is_sqlite() -> bool:
    if os.getenv("DJANGO_USE_SQLITE", "0") == "1":
        return True
    return settings.DATABASES["default"]["ENGINE"].endswith("sqlite3")


def _schema_name() -> str:
    schema = os.getenv("DMIS_DB_SCHEMA", "public")
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema):
        return schema
    logger.warning("Invalid DMIS_DB_SCHEMA %r, defaulting to public", schema)
    return "public"


def _normalize_level(value: object) -> str | None:
    normalized = str(value or "").strip().upper()
    if normalized in CRITICALITY_LEVELS:
        return normalized
    return None


def _first_column(columns: set[str], candidates: Tuple[str, ...]) -> str | None:
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None


def _order_by_desc(columns: set[str]) -> str:
    ordered = [column for column in _ORDER_COLUMNS if column in columns]
    if not ordered:
        return "item_id DESC"
    return ", ".join(f"{column} DESC" for column in ordered)


def _table_exists(schema: str, table_name: str) -> bool:
    if _is_sqlite():
        return False
    try:
        with connection.cursor() as cursor:
            if connection.vendor == "postgresql":
                cursor.execute("SELECT to_regclass(%s)", [f"{schema}.{table_name}"])
                row = cursor.fetchone()
                return bool(row and row[0])
            cursor.execute(
                """
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = %s AND table_name = %s
                LIMIT 1
                """,
                [schema, table_name],
            )
            return cursor.fetchone() is not None
    except DatabaseError as exc:
        logger.warning("Criticality table existence lookup failed for %s.%s: %s", schema, table_name, exc)
        try:
            connection.rollback()
        except Exception:
            pass
        return False


def _table_columns(schema: str, table_name: str) -> set[str]:
    if _is_sqlite():
        return set()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                """,
                [schema, table_name],
            )
            return {str(row[0]) for row in cursor.fetchall() if row and row[0]}
    except DatabaseError as exc:
        logger.warning("Criticality column lookup failed for %s.%s: %s", schema, table_name, exc)
        try:
            connection.rollback()
        except Exception:
            pass
        return set()


def _load_item_defaults(schema: str, item_ids: List[int]) -> Tuple[Dict[int, str], List[str]]:
    defaults: Dict[int, str] = {item_id: "NORMAL" for item_id in item_ids}
    warnings: List[str] = []
    if not item_ids:
        return defaults, warnings
    if _is_sqlite():
        return defaults, ["db_unavailable_preview_stub"]

    placeholders = ",".join(["%s"] * len(item_ids))
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT item_id, criticality_level
                FROM {schema}.item
                WHERE item_id IN ({placeholders})
                """,
                [*item_ids],
            )
            for raw_item_id, raw_level in cursor.fetchall():
                item_id = int(raw_item_id)
                level = _normalize_level(raw_level)
                if level is None:
                    warnings.append("criticality_item_default_invalid")
                    continue
                defaults[item_id] = level
    except DatabaseError as exc:
        logger.warning("Item criticality defaults lookup failed: %s", exc)
        try:
            connection.rollback()
        except Exception:
            pass
        warnings.append("criticality_item_default_lookup_failed")

    return defaults, warnings


def _load_event_context(schema: str, event_id: int) -> Tuple[str | None, str | None, List[str]]:
    if _is_sqlite():
        return None, None, ["db_unavailable_preview_stub"]

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT event_type, status_code
                FROM {schema}.event
                WHERE event_id = %s
                LIMIT 1
                """,
                [event_id],
            )
            row = cursor.fetchone()
    except DatabaseError as exc:
        logger.warning("Event context lookup failed for event_id=%s: %s", event_id, exc)
        try:
            connection.rollback()
        except Exception:
            pass
        return None, None, ["criticality_event_lookup_failed"]

    if not row:
        return None, None, ["criticality_event_not_found"]

    event_type = str(row[0]).strip().upper() if row[0] else None
    status_code = str(row[1]).strip().upper() if row[1] else None
    return event_type, status_code, []


def _load_hazard_defaults(
    schema: str,
    event_type: str,
    item_ids: List[int],
    as_of_dt,
) -> Tuple[Dict[int, str], List[str]]:
    warnings: List[str] = []
    if not event_type or not item_ids:
        return {}, warnings
    if not _table_exists(schema, _TABLE_HAZARD_DEFAULT):
        return {}, warnings

    columns = _table_columns(schema, _TABLE_HAZARD_DEFAULT)
    event_type_col = _first_column(columns, _EVENT_TYPE_COLUMNS)
    if not {"item_id", "criticality_level"}.issubset(columns) or not event_type_col:
        return {}, ["criticality_hazard_default_schema_invalid"]

    where_clauses = [f"{event_type_col} = %s"]
    params: List[object] = [event_type]
    placeholders = ",".join(["%s"] * len(item_ids))
    where_clauses.append(f"item_id IN ({placeholders})")
    params.extend(item_ids)

    active_flag_col = _first_column(columns, _ACTIVE_FLAG_COLUMNS)
    if active_flag_col:
        where_clauses.append(f"{active_flag_col} = TRUE")

    status_col = _first_column(columns, _ACTIVE_STATUS_COLUMNS)
    if status_col:
        where_clauses.append(f"UPPER({status_col}) IN ('A', 'ACTIVE')")

    approval_col = _first_column(columns, _APPROVAL_STATUS_COLUMNS)
    if approval_col:
        where_clauses.append(f"UPPER({approval_col}) IN ('APPROVED', 'A')")

    start_col = _first_column(columns, _START_COLUMNS)
    if start_col:
        where_clauses.append(f"({start_col} IS NULL OR {start_col} <= %s)")
        params.append(as_of_dt)

    end_col = _first_column(columns, _END_COLUMNS)
    if end_col:
        where_clauses.append(f"({end_col} IS NULL OR {end_col} > %s)")
        params.append(as_of_dt)

    order_by = _order_by_desc(columns)
    resolved: Dict[int, str] = {}
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT item_id, criticality_level
                FROM {schema}.{_TABLE_HAZARD_DEFAULT}
                WHERE {" AND ".join(where_clauses)}
                ORDER BY item_id, {order_by}
                """,
                params,
            )
            for raw_item_id, raw_level in cursor.fetchall():
                item_id = int(raw_item_id)
                if item_id in resolved:
                    continue
                level = _normalize_level(raw_level)
                if level is None:
                    warnings.append("criticality_hazard_default_invalid")
                    continue
                resolved[item_id] = level
    except DatabaseError as exc:
        logger.warning("Hazard default criticality lookup failed: %s", exc)
        try:
            connection.rollback()
        except Exception:
            pass
        warnings.append("criticality_hazard_default_lookup_failed")
        return {}, warnings

    return resolved, warnings


def _load_event_overrides(
    schema: str,
    event_id: int,
    item_ids: List[int],
    as_of_dt,
) -> Tuple[Dict[int, str], List[str]]:
    warnings: List[str] = []
    if not item_ids:
        return {}, warnings
    if not _table_exists(schema, _TABLE_EVENT_OVERRIDE):
        return {}, warnings

    columns = _table_columns(schema, _TABLE_EVENT_OVERRIDE)
    event_id_col = _first_column(columns, _EVENT_ID_COLUMNS)
    if not {"item_id", "criticality_level"}.issubset(columns) or not event_id_col:
        return {}, ["criticality_event_override_schema_invalid"]

    where_clauses = [f"{event_id_col} = %s"]
    params: List[object] = [event_id]
    placeholders = ",".join(["%s"] * len(item_ids))
    where_clauses.append(f"item_id IN ({placeholders})")
    params.extend(item_ids)

    active_flag_col = _first_column(columns, _ACTIVE_FLAG_COLUMNS)
    if active_flag_col:
        where_clauses.append(f"{active_flag_col} = TRUE")

    status_col = _first_column(columns, _ACTIVE_STATUS_COLUMNS)
    if status_col:
        where_clauses.append(f"UPPER({status_col}) IN ('A', 'ACTIVE')")

    start_col = _first_column(columns, _START_COLUMNS)
    if start_col:
        where_clauses.append(f"({start_col} IS NULL OR {start_col} <= %s)")
        params.append(as_of_dt)

    end_col = _first_column(columns, _END_COLUMNS)
    if end_col:
        where_clauses.append(f"({end_col} IS NULL OR {end_col} > %s)")
        params.append(as_of_dt)

    order_by = _order_by_desc(columns)
    resolved: Dict[int, str] = {}
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT item_id, criticality_level
                FROM {schema}.{_TABLE_EVENT_OVERRIDE}
                WHERE {" AND ".join(where_clauses)}
                ORDER BY item_id, {order_by}
                """,
                params,
            )
            for raw_item_id, raw_level in cursor.fetchall():
                item_id = int(raw_item_id)
                if item_id in resolved:
                    continue
                level = _normalize_level(raw_level)
                if level is None:
                    warnings.append("criticality_event_override_invalid")
                    continue
                resolved[item_id] = level
    except DatabaseError as exc:
        logger.warning("Event override criticality lookup failed: %s", exc)
        try:
            connection.rollback()
        except Exception:
            pass
        warnings.append("criticality_event_override_lookup_failed")
        return {}, warnings

    return resolved, warnings


def resolve_effective_criticality_by_item(
    event_id: int | None,
    item_ids: List[int],
    as_of_dt=None,
) -> Tuple[Dict[int, Dict[str, str]], List[str]]:
    unique_item_ids = sorted({int(item_id) for item_id in item_ids if item_id is not None})
    if not unique_item_ids:
        return {}, []

    if as_of_dt is None:
        as_of_dt = timezone.now()

    schema = _schema_name()
    warnings: List[str] = []

    item_defaults, default_warnings = _load_item_defaults(schema, unique_item_ids)
    warnings.extend(default_warnings)
    resolved: Dict[int, Dict[str, str]] = {
        item_id: {
            "effective_criticality_level": item_defaults.get(item_id, "NORMAL"),
            "effective_criticality_source": SOURCE_ITEM_DEFAULT,
        }
        for item_id in unique_item_ids
    }

    if event_id is None:
        return resolved, list(dict.fromkeys(warnings))

    event_type, event_status, event_warnings = _load_event_context(schema, int(event_id))
    warnings.extend(event_warnings)

    if event_type:
        hazard_defaults, hazard_warnings = _load_hazard_defaults(
            schema, event_type, unique_item_ids, as_of_dt
        )
        warnings.extend(hazard_warnings)
        for item_id, level in hazard_defaults.items():
            resolved[item_id] = {
                "effective_criticality_level": level,
                "effective_criticality_source": SOURCE_HAZARD_DEFAULT,
            }

    is_closed_event = event_status in {"C", "CLOSED"}
    if is_closed_event:
        warnings.append("criticality_event_closed_override_ignored")
    else:
        overrides, override_warnings = _load_event_overrides(
            schema, int(event_id), unique_item_ids, as_of_dt
        )
        warnings.extend(override_warnings)
        for item_id, level in overrides.items():
            resolved[item_id] = {
                "effective_criticality_level": level,
                "effective_criticality_source": SOURCE_EVENT_OVERRIDE,
            }

    return resolved, list(dict.fromkeys(warnings))
