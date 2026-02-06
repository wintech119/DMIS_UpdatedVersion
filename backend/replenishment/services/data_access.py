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


def get_warehouse_name(warehouse_id: int) -> str:
    """
    Fetch warehouse name from warehouse table.
    Returns the warehouse name string or the fallback format "Warehouse {id}" when not found.
    """
    if _is_sqlite():
        return f"Warehouse {warehouse_id}"

    schema = _schema_name()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT warehouse_name
                FROM {schema}.warehouse
                WHERE warehouse_id = %s
                LIMIT 1
                """,
                [warehouse_id],
            )
            row = cursor.fetchone()
            if row and row[0]:
                return str(row[0])
    except DatabaseError as exc:
        logger.warning("Warehouse name query failed for warehouse_id=%s: %s", warehouse_id, exc)

    # Fallback to ID if name not found
    return f"Warehouse {warehouse_id}"


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
                FROM {schema}.itembatch
                WHERE inventory_id = %s
                  AND update_dtime <= %s
                """,
                [warehouse_id, as_of_dt],
            )
            row = cursor.fetchone()
            inventory_as_of = row[0] if row else None
        if inventory_as_of is None:
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
    _ = (warehouse_id, as_of_dt)
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


def get_item_categories(item_ids: List[int]) -> Tuple[Dict[int, int], List[str]]:
    if _is_sqlite():
        return {}, ["db_unavailable_preview_stub"]
    if not item_ids:
        return {}, []

    schema = _schema_name()
    categories: Dict[int, int] = {}
    warnings: List[str] = []
    try:
        placeholders = ",".join(["%s"] * len(item_ids))
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT item_id, category_id
                FROM {schema}.item
                WHERE item_id IN ({placeholders})
                """,
                [*item_ids],
            )
            for item_id, category_id in cursor.fetchall():
                categories[int(item_id)] = int(category_id)
    except DatabaseError as exc:
        logger.warning("Item category lookup failed: %s", exc)
        try:
            connection.rollback()
        except Exception as rollback_exc:
            logger.warning("DB rollback failed after item category error: %s", rollback_exc)
        warnings.append("db_unavailable_preview_stub")
        return {}, warnings

    return categories, warnings


def get_item_names(item_ids: List[int]) -> Tuple[Dict[int, Dict[str, str | None]], List[str]]:
    """
    Fetch item names and codes for given item IDs.
    Returns a dict mapping item_id -> {"name": str, "code": str}, and any warnings.
    """
    if _is_sqlite():
        return {}, ["db_unavailable_preview_stub"]
    if not item_ids:
        return {}, []

    schema = _schema_name()
    item_data: Dict[int, Dict[str, str]] = {}
    warnings: List[str] = []
    try:
        placeholders = ",".join(["%s"] * len(item_ids))
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT item_id, item_name, item_code
                FROM {schema}.item
                WHERE item_id IN ({placeholders})
                """,
                [*item_ids],
            )
            for item_id, item_name, item_code in cursor.fetchall():
                if item_name:
                    item_data[int(item_id)] = {
                        "name": str(item_name),
                        "code": str(item_code) if item_code else None
                    }
    except DatabaseError as exc:
        logger.warning("Item data lookup failed: %s", exc)
        try:
            connection.rollback()
        except Exception as rollback_exc:
            logger.warning("DB rollback failed after item data error: %s", rollback_exc)
        warnings.append("db_unavailable_item_names")
        return {}, warnings

    return item_data, warnings


def get_category_burn_fallback_rates(
    event_id: int, warehouse_id: int, lookback_days: int, as_of_dt
) -> Tuple[Dict[int, float], List[str], Dict[str, object]]:
    if _is_sqlite():
        return {}, ["db_unavailable_preview_stub"], {}

    warnings: List[str] = []
    start_dt = _normalize_datetime(as_of_dt) - timedelta(days=lookback_days)
    end_dt = _normalize_datetime(as_of_dt)
    schema = _schema_name()
    category_rates: Dict[int, float] = {}
    debug: Dict[str, object] = {
        "window_start": start_dt.isoformat(),
        "window_end": end_dt.isoformat(),
        "row_count": 0,
        "filter": "reliefpkg.status_code IN ('D','R') and dispatch_dtime window",
    }

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT i.category_id, SUM(rpi.item_qty) AS qty
                FROM {schema}.reliefpkg_item rpi
                JOIN {schema}.reliefpkg rp ON rp.reliefpkg_id = rpi.reliefpkg_id
                JOIN {schema}.reliefrqst rr ON rr.reliefrqst_id = rp.reliefrqst_id
                JOIN {schema}.item i ON i.item_id = rpi.item_id
                WHERE rp.to_inventory_id = %s
                  AND rp.status_code IN ('D','R')
                  AND (rp.eligible_event_id = %s OR rr.eligible_event_id = %s)
                  AND rp.dispatch_dtime BETWEEN %s AND %s
                GROUP BY i.category_id
                """,
                [warehouse_id, event_id, event_id, start_dt, end_dt],
            )
            rows = cursor.fetchall()
            debug["row_count"] = len(rows)
            hours = max(lookback_days * 24, 1)
            for category_id, qty in rows:
                category_rates[int(category_id)] = _to_float(qty) / hours
    except DatabaseError as exc:
        logger.warning("Category burn fallback query failed: %s", exc)
        try:
            connection.rollback()
        except Exception as rollback_exc:
            logger.warning("DB rollback failed after category fallback error: %s", rollback_exc)
        warnings.append("db_unavailable_preview_stub")
        return {}, warnings, debug

    return category_rates, warnings, debug


def get_burn_by_item(
    event_id: int, warehouse_id: int, demand_window_hours: int, as_of_dt
) -> Tuple[Dict[int, float], List[str], str, Dict[str, object]]:
    start_dt = _normalize_datetime(as_of_dt) - timedelta(hours=demand_window_hours)
    end_dt = _normalize_datetime(as_of_dt)
    burn: Dict[int, float] = {}
    debug: Dict[str, object] = {
        "window_start": start_dt.isoformat(),
        "window_end": end_dt.isoformat(),
        "row_count": 0,
        # Legacy analytics mapping: dispatched/received packages are status_code IN ('D','R').
        "filter": "reliefpkg.status_code IN ('D','R') and dispatch_dtime window",
    }
    if _is_sqlite():
        return {}, ["db_unavailable_preview_stub"], "none", debug

    warnings: List[str] = []

    schema = _schema_name()

    try:
        with connection.cursor() as cursor:
            # Doc concept "validated/submitted fulfillment" mapped to legacy analytics filter:
            # relief packages with status_code IN ('D','R') and dispatch_dtime in window.
            cursor.execute(
                f"""
                SELECT rpi.item_id, SUM(rpi.item_qty) AS qty
                FROM {schema}.reliefpkg_item rpi
                JOIN {schema}.reliefpkg rp ON rp.reliefpkg_id = rpi.reliefpkg_id
                JOIN {schema}.reliefrqst rr ON rr.reliefrqst_id = rp.reliefrqst_id
                WHERE rp.to_inventory_id = %s
                  AND rp.status_code IN ('D','R')
                  AND (rp.eligible_event_id = %s OR rr.eligible_event_id = %s)
                  AND rp.dispatch_dtime BETWEEN %s AND %s
                GROUP BY rpi.item_id
                """,
                [warehouse_id, event_id, event_id, start_dt, end_dt],
            )
            rows = cursor.fetchall()
            debug["row_count"] = len(rows)
            for item_id, qty in rows:
                burn[int(item_id)] = _to_float(qty)
    except DatabaseError as exc:
        logger.warning("Burn query (reliefpkg) failed: %s", exc)
        try:
            connection.rollback()
        except Exception as rollback_exc:
            logger.warning("DB rollback failed after burn query error: %s", rollback_exc)
        warnings.append("db_unavailable_preview_stub")
        return {}, warnings, "none", debug

    if burn:
        return burn, warnings, "reliefpkg", debug

    warnings.append("burn_data_missing")
    return {}, warnings, "none", debug


def get_active_event() -> Dict[str, object] | None:
    """
    Fetch the most recent active event.
    Returns event dict with keys: event_id, event_name, status, phase, declaration_date
    or None if no active event found.
    """
    if _is_sqlite():
        # Return mock data for SQLite development - Event ID 1 is always the default active event
        return {
            "event_id": 1,
            "event_name": "Development Test Event",
            "status": "ACTIVE",
            "phase": "STABILIZED",
            "declaration_date": timezone.now().isoformat(),
        }

    schema = _schema_name()

    try:
        with connection.cursor() as cursor:
            # Query for active event (status_code 'A' or 'ACTIVE' = Active)
            cursor.execute(
                f"""
                SELECT event_id, event_name, status_code, current_phase, start_date
                FROM {schema}.event
                WHERE UPPER(status_code) IN (%s, %s)
                ORDER BY start_date DESC
                LIMIT 1
                """,
                ["A", "ACTIVE"],
            )
            row = cursor.fetchone()

            if row:
                return {
                    "event_id": int(row[0]),
                    "event_name": str(row[1]) if row[1] else f"Event {row[0]}",
                    "status": str(row[2]) if row[2] else "A",
                    "phase": str(row[3]).upper() if row[3] else "BASELINE",
                    "declaration_date": row[4].isoformat() if row[4] else None,
                }
    except DatabaseError as exc:
        logger.warning("Active event query failed: %s", exc)
        try:
            connection.rollback()
        except Exception as rollback_exc:
            logger.warning("DB rollback failed after active event query error: %s", rollback_exc)

    return None


def get_all_warehouses() -> List[Dict[str, object]]:
    """
    Fetch all active warehouses from the warehouse table.
    Returns list of warehouse dicts with keys: warehouse_id, warehouse_name
    """
    if _is_sqlite():
        # Return mock data for SQLite development - Default warehouses for Event ID 1
        return [
            {"warehouse_id": 1, "warehouse_name": "Kingston Central Depot"},
            {"warehouse_id": 2, "warehouse_name": "Montego Bay Hub"},
            {"warehouse_id": 3, "warehouse_name": "Mandeville Storage"},
        ]

    schema = _schema_name()
    warehouses = []
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT warehouse_id, warehouse_name
                FROM {schema}.warehouse
                WHERE status_code = %s
                ORDER BY warehouse_name
                """,
                ["A"],
            )
            for row in cursor.fetchall():
                warehouses.append({
                    "warehouse_id": int(row[0]),
                    "warehouse_name": str(row[1]) if row[1] else f"Warehouse {row[0]}",
                })
    except DatabaseError as exc:
        logger.warning("Warehouses query failed: %s", exc)
        try:
            connection.rollback()
        except Exception as rollback_exc:
            logger.warning("DB rollback failed after warehouses query error: %s", rollback_exc)

    return warehouses
