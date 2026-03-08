from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from typing import Dict, List, Tuple

from django.conf import settings
from django.db import DatabaseError, connection, transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

CRITICALITY_LEVELS = {"CRITICAL", "HIGH", "NORMAL", "LOW"}
HAZARD_APPROVAL_STATUSES = {"DRAFT", "PENDING_APPROVAL", "APPROVED", "REJECTED"}
EVENT_TYPES = {
    "STORM",
    "HURRICANE",
    "TORNADO",
    "FLOOD",
    "TSUNAMI",
    "FIRE",
    "EARTHQUAKE",
    "WAR",
    "EPIDEMIC",
    "ADHOC",
}


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


def _normalize_event_type(value: object) -> str | None:
    normalized = str(value or "").strip().upper()
    if normalized in EVENT_TYPES:
        return normalized
    return None


def _normalize_approval_status(value: object) -> str | None:
    normalized = str(value or "").strip().upper()
    if normalized in HAZARD_APPROVAL_STATUSES:
        return normalized
    return None


def _to_iso(value: object) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return None if value is None else str(value)


def _serialize_event_override_row(row: tuple) -> Dict[str, object]:
    return {
        "override_id": int(row[0]),
        "event_id": int(row[1]),
        "item_id": int(row[2]),
        "criticality_level": str(row[3]),
        "reason_text": row[4],
        "effective_from": _to_iso(row[5]),
        "effective_to": _to_iso(row[6]),
        "is_active": bool(row[7]),
        "status_code": str(row[8]),
        "create_by_id": row[9],
        "create_dtime": _to_iso(row[10]),
        "update_by_id": row[11],
        "update_dtime": _to_iso(row[12]),
        "version_nbr": int(row[13]),
    }


def _serialize_hazard_default_row(row: tuple) -> Dict[str, object]:
    return {
        "hazard_item_criticality_id": int(row[0]),
        "event_type": str(row[1]),
        "item_id": int(row[2]),
        "criticality_level": str(row[3]),
        "reason_text": row[4],
        "effective_from": _to_iso(row[5]),
        "effective_to": _to_iso(row[6]),
        "is_active": bool(row[7]),
        "status_code": str(row[8]),
        "approval_status": str(row[9]),
        "submitted_by_id": row[10],
        "submitted_dtime": _to_iso(row[11]),
        "approved_by_id": row[12],
        "approved_dtime": _to_iso(row[13]),
        "rejected_by_id": row[14],
        "rejected_dtime": _to_iso(row[15]),
        "rejected_reason": row[16],
        "create_by_id": row[17],
        "create_dtime": _to_iso(row[18]),
        "update_by_id": row[19],
        "update_dtime": _to_iso(row[20]),
        "version_nbr": int(row[21]),
    }


def _fetch_event_status(schema: str, event_id: int) -> str | None:
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT status_code
            FROM {schema}.event
            WHERE event_id = %s
            LIMIT 1
            """,
            [event_id],
        )
        row = cursor.fetchone()
        return str(row[0]).strip().upper() if row and row[0] else None


def list_event_overrides(
    *,
    event_id: int | None = None,
    item_id: int | None = None,
    active_only: bool = False,
    limit: int = 200,
) -> Tuple[List[Dict[str, object]], List[str]]:
    if _is_sqlite():
        return [], ["db_unavailable_preview_stub"]

    schema = _schema_name()
    warnings: List[str] = []
    rows_out: List[Dict[str, object]] = []
    where: List[str] = []
    params: List[object] = []

    if event_id is not None:
        where.append("event_id = %s")
        params.append(int(event_id))
    if item_id is not None:
        where.append("item_id = %s")
        params.append(int(item_id))
    if active_only:
        where.append("is_active = TRUE")
        where.append("(effective_to IS NULL OR effective_to > NOW())")

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    safe_limit = max(1, min(int(limit or 200), 500))

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT
                    override_id,
                    event_id,
                    item_id,
                    criticality_level,
                    reason_text,
                    effective_from,
                    effective_to,
                    is_active,
                    status_code,
                    create_by_id,
                    create_dtime,
                    update_by_id,
                    update_dtime,
                    version_nbr
                FROM {schema}.event_item_criticality_override
                {where_sql}
                ORDER BY
                    is_active DESC,
                    COALESCE(effective_from, create_dtime) DESC,
                    override_id DESC
                LIMIT %s
                """,
                [*params, safe_limit],
            )
            rows_out = [_serialize_event_override_row(row) for row in cursor.fetchall()]
    except DatabaseError as exc:
        logger.warning("List event criticality overrides failed: %s", exc)
        try:
            connection.rollback()
        except Exception:
            pass
        return [], ["criticality_event_override_list_failed"]

    return rows_out, warnings


def create_event_override(
    *,
    event_id: int,
    item_id: int,
    criticality_level: object,
    actor_id: str,
    reason_text: str | None = None,
    effective_from=None,
    effective_to=None,
    is_active: bool = True,
) -> Tuple[Dict[str, object] | None, List[str]]:
    if _is_sqlite():
        return None, ["db_unavailable_preview_stub"]

    level = _normalize_level(criticality_level)
    if level is None:
        return None, ["criticality_level_invalid"]

    schema = _schema_name()
    warnings: List[str] = []
    actor = str(actor_id or "SYSTEM")

    try:
        with transaction.atomic():
            event_status = _fetch_event_status(schema, int(event_id))
            if event_status in {"C", "CLOSED"} and is_active:
                return None, ["event_closed_override_not_allowed"]

            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    INSERT INTO {schema}.event_item_criticality_override (
                        event_id,
                        item_id,
                        criticality_level,
                        reason_text,
                        effective_from,
                        effective_to,
                        is_active,
                        status_code,
                        create_by_id,
                        create_dtime,
                        update_by_id,
                        update_dtime
                    )
                    VALUES (
                        %s,
                        %s,
                        %s,
                        %s,
                        COALESCE(%s, NOW()),
                        %s,
                        %s,
                        %s,
                        %s,
                        NOW(),
                        %s,
                        NOW()
                    )
                    RETURNING
                        override_id,
                        event_id,
                        item_id,
                        criticality_level,
                        reason_text,
                        effective_from,
                        effective_to,
                        is_active,
                        status_code,
                        create_by_id,
                        create_dtime,
                        update_by_id,
                        update_dtime,
                        version_nbr
                    """,
                    [
                        int(event_id),
                        int(item_id),
                        level,
                        (reason_text or "").strip() or None,
                        effective_from,
                        effective_to,
                        bool(is_active),
                        "A" if bool(is_active) else "I",
                        actor,
                        actor,
                    ],
                )
                row = cursor.fetchone()
                return _serialize_event_override_row(row) if row else None, warnings
    except DatabaseError as exc:
        logger.warning("Create event criticality override failed: %s", exc)
        try:
            connection.rollback()
        except Exception:
            pass
        return None, ["criticality_event_override_create_failed"]


def update_event_override(
    *,
    override_id: int,
    updates: Dict[str, object],
    actor_id: str,
) -> Tuple[Dict[str, object] | None, List[str]]:
    if _is_sqlite():
        return None, ["db_unavailable_preview_stub"]

    schema = _schema_name()
    warnings: List[str] = []
    actor = str(actor_id or "SYSTEM")
    set_parts: List[str] = []
    params: List[object] = []

    if "criticality_level" in updates:
        level = _normalize_level(updates.get("criticality_level"))
        if level is None:
            return None, ["criticality_level_invalid"]
        set_parts.append("criticality_level = %s")
        params.append(level)
    if "reason_text" in updates:
        set_parts.append("reason_text = %s")
        params.append((str(updates.get("reason_text") or "").strip() or None))
    if "effective_from" in updates:
        set_parts.append("effective_from = %s")
        params.append(updates.get("effective_from"))
    if "effective_to" in updates:
        set_parts.append("effective_to = %s")
        params.append(updates.get("effective_to"))
    if "is_active" in updates:
        is_active = bool(updates.get("is_active"))
        set_parts.append("is_active = %s")
        params.append(is_active)
        set_parts.append("status_code = %s")
        params.append("A" if is_active else "I")
        if not is_active and "effective_to" not in updates:
            set_parts.append("effective_to = COALESCE(effective_to, NOW())")

    if not set_parts:
        return None, ["no_updates_provided"]

    set_parts.extend(
        [
            "update_by_id = %s",
            "update_dtime = NOW()",
            "version_nbr = version_nbr + 1",
        ]
    )
    params.append(actor)

    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    UPDATE {schema}.event_item_criticality_override
                    SET {", ".join(set_parts)}
                    WHERE override_id = %s
                    RETURNING
                        override_id,
                        event_id,
                        item_id,
                        criticality_level,
                        reason_text,
                        effective_from,
                        effective_to,
                        is_active,
                        status_code,
                        create_by_id,
                        create_dtime,
                        update_by_id,
                        update_dtime,
                        version_nbr
                    """,
                    [*params, int(override_id)],
                )
                row = cursor.fetchone()
                if not row:
                    return None, ["criticality_event_override_not_found"]
                return _serialize_event_override_row(row), warnings
    except DatabaseError as exc:
        logger.warning("Update event criticality override failed: %s", exc)
        try:
            connection.rollback()
        except Exception:
            pass
        return None, ["criticality_event_override_update_failed"]


def list_hazard_defaults(
    *,
    event_type: str | None = None,
    item_id: int | None = None,
    approval_status: str | None = None,
    active_only: bool = False,
    limit: int = 200,
) -> Tuple[List[Dict[str, object]], List[str]]:
    if _is_sqlite():
        return [], ["db_unavailable_preview_stub"]

    schema = _schema_name()
    warnings: List[str] = []
    rows_out: List[Dict[str, object]] = []
    where: List[str] = []
    params: List[object] = []

    if event_type:
        normalized_event_type = _normalize_event_type(event_type)
        if normalized_event_type is None:
            return [], ["event_type_invalid"]
        where.append("UPPER(event_type) = %s")
        params.append(normalized_event_type)
    if item_id is not None:
        where.append("item_id = %s")
        params.append(int(item_id))
    if approval_status:
        normalized_status = _normalize_approval_status(approval_status)
        if normalized_status is None:
            return [], ["approval_status_invalid"]
        where.append("approval_status = %s")
        params.append(normalized_status)
    if active_only:
        where.append("is_active = TRUE")
        where.append("(effective_to IS NULL OR effective_to > NOW())")

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    safe_limit = max(1, min(int(limit or 200), 500))

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT
                    hazard_item_criticality_id,
                    event_type,
                    item_id,
                    criticality_level,
                    reason_text,
                    effective_from,
                    effective_to,
                    is_active,
                    status_code,
                    approval_status,
                    submitted_by_id,
                    submitted_dtime,
                    approved_by_id,
                    approved_dtime,
                    rejected_by_id,
                    rejected_dtime,
                    rejected_reason,
                    create_by_id,
                    create_dtime,
                    update_by_id,
                    update_dtime,
                    version_nbr
                FROM {schema}.hazard_item_criticality
                {where_sql}
                ORDER BY
                    COALESCE(effective_from, create_dtime) DESC,
                    hazard_item_criticality_id DESC
                LIMIT %s
                """,
                [*params, safe_limit],
            )
            rows_out = [_serialize_hazard_default_row(row) for row in cursor.fetchall()]
    except DatabaseError as exc:
        logger.warning("List hazard criticality defaults failed: %s", exc)
        try:
            connection.rollback()
        except Exception:
            pass
        return [], ["criticality_hazard_default_list_failed"]

    return rows_out, warnings


def create_hazard_default(
    *,
    event_type: object,
    item_id: int,
    criticality_level: object,
    actor_id: str,
    reason_text: str | None = None,
    effective_from=None,
    effective_to=None,
    is_active: bool = True,
    approval_status: str = "DRAFT",
) -> Tuple[Dict[str, object] | None, List[str]]:
    if _is_sqlite():
        return None, ["db_unavailable_preview_stub"]

    normalized_event_type = _normalize_event_type(event_type)
    if normalized_event_type is None:
        return None, ["event_type_invalid"]
    level = _normalize_level(criticality_level)
    if level is None:
        return None, ["criticality_level_invalid"]
    normalized_approval_status = _normalize_approval_status(approval_status)
    if normalized_approval_status is None:
        return None, ["approval_status_invalid"]

    schema = _schema_name()
    actor = str(actor_id or "SYSTEM")
    submitted_by = actor if normalized_approval_status == "PENDING_APPROVAL" else None
    submitted_dtime = timezone.now() if normalized_approval_status == "PENDING_APPROVAL" else None

    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    INSERT INTO {schema}.hazard_item_criticality (
                        event_type,
                        item_id,
                        criticality_level,
                        reason_text,
                        effective_from,
                        effective_to,
                        is_active,
                        status_code,
                        approval_status,
                        submitted_by_id,
                        submitted_dtime,
                        create_by_id,
                        create_dtime,
                        update_by_id,
                        update_dtime
                    )
                    VALUES (
                        %s,
                        %s,
                        %s,
                        %s,
                        COALESCE(%s, NOW()),
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        NOW(),
                        %s,
                        NOW()
                    )
                    RETURNING
                        hazard_item_criticality_id,
                        event_type,
                        item_id,
                        criticality_level,
                        reason_text,
                        effective_from,
                        effective_to,
                        is_active,
                        status_code,
                        approval_status,
                        submitted_by_id,
                        submitted_dtime,
                        approved_by_id,
                        approved_dtime,
                        rejected_by_id,
                        rejected_dtime,
                        rejected_reason,
                        create_by_id,
                        create_dtime,
                        update_by_id,
                        update_dtime,
                        version_nbr
                    """,
                    [
                        normalized_event_type,
                        int(item_id),
                        level,
                        (reason_text or "").strip() or None,
                        effective_from,
                        effective_to,
                        bool(is_active),
                        "A" if bool(is_active) else "I",
                        normalized_approval_status,
                        submitted_by,
                        submitted_dtime,
                        actor,
                        actor,
                    ],
                )
                row = cursor.fetchone()
                return _serialize_hazard_default_row(row) if row else None, []
    except DatabaseError as exc:
        logger.warning("Create hazard criticality default failed: %s", exc)
        try:
            connection.rollback()
        except Exception:
            pass
        return None, ["criticality_hazard_default_create_failed"]


def update_hazard_default(
    *,
    hazard_item_criticality_id: int,
    updates: Dict[str, object],
    actor_id: str,
) -> Tuple[Dict[str, object] | None, List[str]]:
    if _is_sqlite():
        return None, ["db_unavailable_preview_stub"]

    schema = _schema_name()
    actor = str(actor_id or "SYSTEM")
    set_parts: List[str] = []
    params: List[object] = []
    state_changed = False

    if "event_type" in updates:
        normalized_event_type = _normalize_event_type(updates.get("event_type"))
        if normalized_event_type is None:
            return None, ["event_type_invalid"]
        set_parts.append("event_type = %s")
        params.append(normalized_event_type)
        state_changed = True
    if "item_id" in updates:
        set_parts.append("item_id = %s")
        params.append(int(updates.get("item_id")))
        state_changed = True
    if "criticality_level" in updates:
        level = _normalize_level(updates.get("criticality_level"))
        if level is None:
            return None, ["criticality_level_invalid"]
        set_parts.append("criticality_level = %s")
        params.append(level)
        state_changed = True
    if "reason_text" in updates:
        set_parts.append("reason_text = %s")
        params.append((str(updates.get("reason_text") or "").strip() or None))
    if "effective_from" in updates:
        set_parts.append("effective_from = %s")
        params.append(updates.get("effective_from"))
        state_changed = True
    if "effective_to" in updates:
        set_parts.append("effective_to = %s")
        params.append(updates.get("effective_to"))
        state_changed = True
    if "is_active" in updates:
        is_active = bool(updates.get("is_active"))
        set_parts.append("is_active = %s")
        params.append(is_active)
        set_parts.append("status_code = %s")
        params.append("A" if is_active else "I")

    if not set_parts:
        return None, ["no_updates_provided"]

    if state_changed:
        set_parts.append("approval_status = 'DRAFT'")
        set_parts.append("submitted_by_id = NULL")
        set_parts.append("submitted_dtime = NULL")
        set_parts.append("approved_by_id = NULL")
        set_parts.append("approved_dtime = NULL")
        set_parts.append("rejected_by_id = NULL")
        set_parts.append("rejected_dtime = NULL")
        set_parts.append("rejected_reason = NULL")

    set_parts.extend(
        [
            "update_by_id = %s",
            "update_dtime = NOW()",
            "version_nbr = version_nbr + 1",
        ]
    )
    params.append(actor)

    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    UPDATE {schema}.hazard_item_criticality
                    SET {", ".join(set_parts)}
                    WHERE hazard_item_criticality_id = %s
                    RETURNING
                        hazard_item_criticality_id,
                        event_type,
                        item_id,
                        criticality_level,
                        reason_text,
                        effective_from,
                        effective_to,
                        is_active,
                        status_code,
                        approval_status,
                        submitted_by_id,
                        submitted_dtime,
                        approved_by_id,
                        approved_dtime,
                        rejected_by_id,
                        rejected_dtime,
                        rejected_reason,
                        create_by_id,
                        create_dtime,
                        update_by_id,
                        update_dtime,
                        version_nbr
                    """,
                    [*params, int(hazard_item_criticality_id)],
                )
                row = cursor.fetchone()
                if not row:
                    return None, ["criticality_hazard_default_not_found"]
                return _serialize_hazard_default_row(row), []
    except DatabaseError as exc:
        logger.warning("Update hazard criticality default failed: %s", exc)
        try:
            connection.rollback()
        except Exception:
            pass
        return None, ["criticality_hazard_default_update_failed"]


def submit_hazard_default(
    *,
    hazard_item_criticality_id: int,
    actor_id: str,
) -> Tuple[Dict[str, object] | None, List[str]]:
    if _is_sqlite():
        return None, ["db_unavailable_preview_stub"]

    schema = _schema_name()
    actor = str(actor_id or "SYSTEM")
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    UPDATE {schema}.hazard_item_criticality
                    SET
                        approval_status = 'PENDING_APPROVAL',
                        submitted_by_id = %s,
                        submitted_dtime = NOW(),
                        update_by_id = %s,
                        update_dtime = NOW(),
                        version_nbr = version_nbr + 1
                    WHERE hazard_item_criticality_id = %s
                      AND approval_status IN ('DRAFT', 'REJECTED')
                    RETURNING
                        hazard_item_criticality_id,
                        event_type,
                        item_id,
                        criticality_level,
                        reason_text,
                        effective_from,
                        effective_to,
                        is_active,
                        status_code,
                        approval_status,
                        submitted_by_id,
                        submitted_dtime,
                        approved_by_id,
                        approved_dtime,
                        rejected_by_id,
                        rejected_dtime,
                        rejected_reason,
                        create_by_id,
                        create_dtime,
                        update_by_id,
                        update_dtime,
                        version_nbr
                    """,
                    [actor, actor, int(hazard_item_criticality_id)],
                )
                row = cursor.fetchone()
                if not row:
                    return None, ["criticality_hazard_default_submit_invalid_state_or_missing"]
                return _serialize_hazard_default_row(row), []
    except DatabaseError as exc:
        logger.warning("Submit hazard criticality default failed: %s", exc)
        try:
            connection.rollback()
        except Exception:
            pass
        return None, ["criticality_hazard_default_submit_failed"]


def approve_hazard_default(
    *,
    hazard_item_criticality_id: int,
    actor_id: str,
) -> Tuple[Dict[str, object] | None, List[str]]:
    if _is_sqlite():
        return None, ["db_unavailable_preview_stub"]

    schema = _schema_name()
    actor = str(actor_id or "SYSTEM")
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    UPDATE {schema}.hazard_item_criticality
                    SET
                        approval_status = 'APPROVED',
                        approved_by_id = %s,
                        approved_dtime = NOW(),
                        rejected_by_id = NULL,
                        rejected_dtime = NULL,
                        rejected_reason = NULL,
                        update_by_id = %s,
                        update_dtime = NOW(),
                        version_nbr = version_nbr + 1
                    WHERE hazard_item_criticality_id = %s
                      AND approval_status = 'PENDING_APPROVAL'
                    RETURNING
                        hazard_item_criticality_id,
                        event_type,
                        item_id,
                        criticality_level,
                        reason_text,
                        effective_from,
                        effective_to,
                        is_active,
                        status_code,
                        approval_status,
                        submitted_by_id,
                        submitted_dtime,
                        approved_by_id,
                        approved_dtime,
                        rejected_by_id,
                        rejected_dtime,
                        rejected_reason,
                        create_by_id,
                        create_dtime,
                        update_by_id,
                        update_dtime,
                        version_nbr
                    """,
                    [actor, actor, int(hazard_item_criticality_id)],
                )
                row = cursor.fetchone()
                if not row:
                    return None, ["criticality_hazard_default_approve_invalid_state_or_missing"]
                return _serialize_hazard_default_row(row), []
    except DatabaseError as exc:
        logger.warning("Approve hazard criticality default failed: %s", exc)
        try:
            connection.rollback()
        except Exception:
            pass
        return None, ["criticality_hazard_default_approve_failed"]


def reject_hazard_default(
    *,
    hazard_item_criticality_id: int,
    actor_id: str,
    reason_text: object,
) -> Tuple[Dict[str, object] | None, List[str]]:
    if _is_sqlite():
        return None, ["db_unavailable_preview_stub"]

    reason = str(reason_text or "").strip()
    if not reason:
        return None, ["criticality_hazard_default_reject_reason_required"]

    schema = _schema_name()
    actor = str(actor_id or "SYSTEM")
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    UPDATE {schema}.hazard_item_criticality
                    SET
                        approval_status = 'REJECTED',
                        rejected_by_id = %s,
                        rejected_dtime = NOW(),
                        rejected_reason = %s,
                        approved_by_id = NULL,
                        approved_dtime = NULL,
                        update_by_id = %s,
                        update_dtime = NOW(),
                        version_nbr = version_nbr + 1
                    WHERE hazard_item_criticality_id = %s
                      AND approval_status = 'PENDING_APPROVAL'
                    RETURNING
                        hazard_item_criticality_id,
                        event_type,
                        item_id,
                        criticality_level,
                        reason_text,
                        effective_from,
                        effective_to,
                        is_active,
                        status_code,
                        approval_status,
                        submitted_by_id,
                        submitted_dtime,
                        approved_by_id,
                        approved_dtime,
                        rejected_by_id,
                        rejected_dtime,
                        rejected_reason,
                        create_by_id,
                        create_dtime,
                        update_by_id,
                        update_dtime,
                        version_nbr
                    """,
                    [actor, reason, actor, int(hazard_item_criticality_id)],
                )
                row = cursor.fetchone()
                if not row:
                    return None, ["criticality_hazard_default_reject_invalid_state_or_missing"]
                return _serialize_hazard_default_row(row), []
    except DatabaseError as exc:
        logger.warning("Reject hazard criticality default failed: %s", exc)
        try:
            connection.rollback()
        except Exception:
            pass
        return None, ["criticality_hazard_default_reject_failed"]
