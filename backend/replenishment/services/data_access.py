import logging
import os
import re
from datetime import timedelta, timezone as dt_timezone
from decimal import Decimal
from typing import Dict, List, Tuple

from django.conf import settings
from django.db import DatabaseError, connection
from django.utils import timezone

from replenishment import rules

logger = logging.getLogger(__name__)


def _is_sqlite() -> bool:
    if os.getenv("DJANGO_USE_SQLITE", "0") == "1":
        return True
    return settings.DATABASES["default"]["ENGINE"].endswith("sqlite3")


def _to_float(value) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _normalize_datetime(dt):
    if timezone.is_aware(dt):
        return timezone.make_naive(dt, dt_timezone.utc)
    return dt


def _schema_name() -> str:
    schema = os.getenv("DMIS_DB_SCHEMA", "public")
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema):
        return schema
    logger.warning("Invalid DMIS_DB_SCHEMA %r, defaulting to public", schema)
    return "public"


def get_available_by_item(
    warehouse_id: int, as_of_dt
) -> Tuple[Dict[int, float], List[str], object | None]:
    if _is_sqlite():
        return {}, ["db_unavailable_preview_stub"], None

    warnings: List[str] = []
    available: Dict[int, float] = {}
    status = getattr(settings, "NEEDS_INVENTORY_ACTIVE_STATUS", "A")
    as_of_dt = _normalize_datetime(as_of_dt)
    schema = _schema_name()
    inventory_as_of = None
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT ib.item_id, SUM(ib.usable_qty - ib.reserved_qty) AS qty
                FROM {schema}.itembatch ib
                JOIN {schema}.inventory i
                    ON i.inventory_id = ib.inventory_id AND i.item_id = ib.item_id
                WHERE ib.inventory_id = %s
                  AND ib.status_code = %s
                  AND i.status_code = %s
                  AND ib.update_dtime <= %s
                  AND i.update_dtime <= %s
                GROUP BY ib.item_id
                """,
                [warehouse_id, status, status, as_of_dt, as_of_dt],
            )
            for item_id, qty in cursor.fetchall():
                available[int(item_id)] = _to_float(qty)
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT MAX(update_dtime)
                FROM {schema}.inventory
                WHERE inventory_id = %s
                  AND update_dtime <= %s
                """,
                [warehouse_id, as_of_dt],
            )
            row = cursor.fetchone()
            inventory_as_of = row[0] if row else None
    except DatabaseError as exc:
        logger.warning("Available inventory query failed: %s", exc)
        try:
            connection.rollback()
        except Exception as rollback_exc:
            logger.warning("DB rollback failed after inventory query error: %s", rollback_exc)
        warnings.append("db_unavailable_preview_stub")
        return {}, warnings, None

    return available, warnings, inventory_as_of


def get_inbound_donations_by_item(
    warehouse_id: int, as_of_dt
) -> Tuple[Dict[int, float], List[str]]:
    warnings = ["donation_in_transit_unmodeled"]
    if _is_sqlite():
        warnings.append("db_unavailable_preview_stub")
        return {}, warnings

    return {}, warnings


def get_inbound_transfers_by_item(
    warehouse_id: int, as_of_dt
) -> Tuple[Dict[int, float], List[str]]:
    statuses, warnings = rules.resolve_strict_inbound_transfer_codes()
    if _is_sqlite():
        warnings.append("db_unavailable_preview_stub")
        return {}, warnings
    if not statuses:
        return {}, warnings

    as_of_date = _normalize_datetime(as_of_dt).date()
    schema = _schema_name()
    inbound: Dict[int, float] = {}
    try:
        placeholders = ",".join(["%s"] * len(statuses))
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT ti.item_id, SUM(ti.item_qty) AS qty
                FROM {schema}.transfer_item ti
                JOIN {schema}.transfer t ON t.transfer_id = ti.transfer_id
                WHERE t.to_inventory_id = %s
                  AND t.status_code IN ({placeholders})
                  AND t.transfer_date <= %s
                GROUP BY ti.item_id
                """,
                [warehouse_id, *statuses, as_of_date],
            )
            for item_id, qty in cursor.fetchall():
                inbound[int(item_id)] = _to_float(qty)
    except DatabaseError as exc:
        logger.warning("Inbound transfers query failed: %s", exc)
        try:
            connection.rollback()
        except Exception as rollback_exc:
            logger.warning("DB rollback failed after transfers query error: %s", rollback_exc)
        warnings.append("db_unavailable_preview_stub")
        return {}, warnings

    return inbound, warnings


def get_burn_by_item(
    event_id: int, warehouse_id: int, demand_window_hours: int, as_of_dt
) -> Tuple[Dict[int, float], List[str], str]:
    if _is_sqlite():
        return {}, ["db_unavailable_preview_stub"], "none"

    warnings: List[str] = []
    start_dt = _normalize_datetime(as_of_dt) - timedelta(hours=demand_window_hours)
    end_dt = _normalize_datetime(as_of_dt)
    burn: Dict[int, float] = {}

    primary = getattr(settings, "NEEDS_BURN_SOURCE", "reliefpkg")
    schema = _schema_name()

    if primary == "reliefpkg":
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT rpi.item_id, SUM(rpi.item_qty) AS qty
                    FROM {schema}.reliefpkg_item rpi
                    JOIN {schema}.reliefpkg rp ON rp.reliefpkg_id = rpi.reliefpkg_id
                    WHERE rp.to_inventory_id = %s
                      AND rp.eligible_event_id = %s
                      AND rp.status_code = 'D'
                      AND COALESCE(rp.dispatch_dtime, rp.start_date)
                          BETWEEN %s AND %s
                    GROUP BY rpi.item_id
                    """,
                    [warehouse_id, event_id, start_dt, end_dt],
                )
                for item_id, qty in cursor.fetchall():
                    burn[int(item_id)] = _to_float(qty)
        except DatabaseError as exc:
            logger.warning("Burn query (reliefpkg) failed: %s", exc)
            try:
                connection.rollback()
            except Exception as rollback_exc:
                logger.warning("DB rollback failed after burn query error: %s", rollback_exc)
            warnings.append("db_unavailable_preview_stub")
            return {}, warnings, "none"

        if burn:
            return burn, warnings, "reliefpkg"

    warnings.append("burn_data_missing")
    return {}, warnings, "none"
