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


def get_warehouse_names(warehouse_ids: List[int]) -> Tuple[Dict[int, str], List[str]]:
    """
    Fetch warehouse names for many warehouse IDs in one query.
    Returns a dict mapping warehouse_id -> warehouse_name and any warnings.
    """
    if not warehouse_ids:
        return {}, []

    unique_ids = sorted({int(warehouse_id) for warehouse_id in warehouse_ids if warehouse_id is not None})
    if not unique_ids:
        return {}, []

    if _is_sqlite():
        return {warehouse_id: f"Warehouse {warehouse_id}" for warehouse_id in unique_ids}, []

    schema = _schema_name()
    warehouse_names: Dict[int, str] = {}
    warnings: List[str] = []
    try:
        placeholders = ",".join(["%s"] * len(unique_ids))
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT warehouse_id, warehouse_name
                FROM {schema}.warehouse
                WHERE warehouse_id IN ({placeholders})
                """,
                unique_ids,
            )
            for warehouse_id, warehouse_name in cursor.fetchall():
                warehouse_names[int(warehouse_id)] = (
                    str(warehouse_name) if warehouse_name else f"Warehouse {warehouse_id}"
                )
    except DatabaseError as exc:
        logger.warning("Warehouse names query failed for warehouse_ids=%s: %s", unique_ids, exc)
        try:
            connection.rollback()
        except Exception as rollback_exc:
            logger.warning("DB rollback failed after warehouse names query error: %s", rollback_exc)
        warnings.append("db_unavailable_warehouse_names")

    for warehouse_id in unique_ids:
        warehouse_names.setdefault(warehouse_id, f"Warehouse {warehouse_id}")
    return warehouse_names, warnings


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


def get_warehouses_with_stock(
    item_ids: List[int], exclude_warehouse_id: int
) -> Tuple[Dict[int, List[Dict]], List[str]]:
    """
    Find source warehouses with available stock per item.
    Returns {item_id: [{warehouse_id, warehouse_name, available_qty}, ...]} and warnings.
    """
    if _is_sqlite():
        return {}, ["db_unavailable_preview_stub"]
    if not item_ids:
        return {}, []

    schema = _schema_name()
    result: Dict[int, List[Dict]] = {}
    warnings: List[str] = []
    status = getattr(settings, "NEEDS_INVENTORY_ACTIVE_STATUS", "A")

    try:
        placeholders = ",".join(["%s"] * len(item_ids))
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT ib.item_id,
                       w.warehouse_id,
                       w.warehouse_name,
                       SUM(ib.usable_qty - ib.reserved_qty) AS available_qty
                FROM {schema}.itembatch ib
                JOIN {schema}.inventory i
                    ON i.inventory_id = ib.inventory_id AND i.item_id = ib.item_id
                JOIN {schema}.warehouse w
                    ON w.warehouse_id = ib.inventory_id
                WHERE ib.item_id IN ({placeholders})
                  AND ib.inventory_id != %s
                  AND ib.status_code = %s
                  AND i.status_code = %s
                  AND w.status_code = 'A'
                GROUP BY ib.item_id, w.warehouse_id, w.warehouse_name
                HAVING SUM(ib.usable_qty - ib.reserved_qty) > 0
                ORDER BY ib.item_id, available_qty DESC
                """,
                [*item_ids, exclude_warehouse_id, status, status],
            )
            for item_id, wh_id, wh_name, qty in cursor.fetchall():
                item_id = int(item_id)
                result.setdefault(item_id, []).append({
                    "warehouse_id": int(wh_id),
                    "warehouse_name": str(wh_name) if wh_name else f"Warehouse {wh_id}",
                    "available_qty": _to_float(qty),
                })
    except DatabaseError as exc:
        logger.warning("Warehouses with stock query failed: %s", exc)
        try:
            connection.rollback()
        except Exception as rollback_exc:
            logger.warning("DB rollback failed: %s", rollback_exc)
        warnings.append("db_unavailable_preview_stub")
        return {}, warnings

    return result, warnings


def insert_draft_transfer(
    from_warehouse_id: int,
    to_warehouse_id: int,
    event_id: int,
    needs_list_id: str,
    reason: str,
    actor_id: str,
) -> Tuple[int | None, List[str]]:
    """
    Insert a draft transfer row into the legacy transfer table.
    Returns (transfer_id, warnings).
    """
    if _is_sqlite():
        return None, ["db_unavailable_preview_stub"]

    schema = _schema_name()
    warnings: List[str] = []
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                INSERT INTO {schema}.transfer
                    (fr_inventory_id, to_inventory_id, eligible_event_id,
                     transfer_date, reason_text, status_code,
                     needs_list_id, create_user, create_dtime)
                VALUES (%s, %s, %s, CURRENT_DATE, %s, 'P', %s, %s, NOW())
                RETURNING transfer_id
                """,
                [from_warehouse_id, to_warehouse_id, event_id,
                 reason, needs_list_id, actor_id],
            )
            row = cursor.fetchone()
            return int(row[0]) if row else None, warnings
    except DatabaseError as exc:
        logger.warning("Insert draft transfer failed: %s", exc)
        try:
            connection.rollback()
        except Exception as rollback_exc:
            logger.warning("DB rollback failed: %s", rollback_exc)
        warnings.append("db_error_insert_transfer")
        return None, warnings


def insert_transfer_items(
    transfer_id: int, items: List[Dict]
) -> List[str]:
    """
    Insert items into transfer_item table for a given transfer.
    Each item dict must have: item_id, item_qty, uom_code.
    inventory_id defaults to the transfer's source inventory when omitted.
    """
    if _is_sqlite():
        return ["db_unavailable_preview_stub"]
    if not items:
        return []

    schema = _schema_name()
    warnings: List[str] = []
    try:
        with connection.cursor() as cursor:
            default_inventory_id = None
            if any(item.get("inventory_id") is None for item in items):
                cursor.execute(
                    f"SELECT fr_inventory_id FROM {schema}.transfer WHERE transfer_id = %s",
                    [transfer_id],
                )
                row = cursor.fetchone()
                if not row:
                    warnings.append("transfer_not_found")
                    return warnings
                default_inventory_id = int(row[0]) if row[0] is not None else None

            for item in items:
                inventory_id = item.get("inventory_id", default_inventory_id)
                if inventory_id is None:
                    warnings.append(f"transfer_source_inventory_missing_item_{item['item_id']}")
                    continue
                cursor.execute(
                    f"""
                    INSERT INTO {schema}.transfer_item
                        (transfer_id, item_id, item_qty, uom_code, inventory_id)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    [transfer_id, item["item_id"], item["item_qty"],
                     item.get("uom_code", "EA"), inventory_id],
                )
    except DatabaseError as exc:
        logger.warning("Insert transfer items failed: %s", exc)
        try:
            connection.rollback()
        except Exception as rollback_exc:
            logger.warning("DB rollback failed: %s", rollback_exc)
        warnings.append("db_error_insert_transfer_items")
    return warnings


def get_transfers_for_needs_list(
    needs_list_id: str,
) -> Tuple[List[Dict], List[str]]:
    """
    Return transfers + items linked to this needs list.
    """
    if _is_sqlite():
        return [], ["db_unavailable_preview_stub"]

    schema = _schema_name()
    transfers: Dict[int, Dict] = {}
    warnings: List[str] = []
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT t.transfer_id, t.fr_inventory_id, t.to_inventory_id,
                       t.status_code, t.transfer_date, t.reason_text,
                       fw.warehouse_name AS from_name,
                       tw.warehouse_name AS to_name,
                       t.create_user, t.create_dtime
                FROM {schema}.transfer t
                LEFT JOIN {schema}.warehouse fw ON fw.warehouse_id = t.fr_inventory_id
                LEFT JOIN {schema}.warehouse tw ON tw.warehouse_id = t.to_inventory_id
                WHERE t.needs_list_id = %s
                ORDER BY t.transfer_id
                """,
                [needs_list_id],
            )
            for row in cursor.fetchall():
                tid = int(row[0])
                transfers[tid] = {
                    "transfer_id": tid,
                    "from_warehouse": {
                        "id": int(row[1]),
                        "name": str(row[6]) if row[6] else f"Warehouse {row[1]}",
                    },
                    "to_warehouse": {
                        "id": int(row[2]),
                        "name": str(row[7]) if row[7] else f"Warehouse {row[2]}",
                    },
                    "status": str(row[3]),
                    "transfer_date": row[4].isoformat() if row[4] else None,
                    "reason": str(row[5]) if row[5] else None,
                    "created_by": str(row[8]) if row[8] else None,
                    "created_at": row[9].isoformat() if row[9] else None,
                    "items": [],
                }

        if transfers:
            tids = list(transfers.keys())
            placeholders = ",".join(["%s"] * len(tids))
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT ti.transfer_id, ti.item_id, ti.item_qty, ti.uom_code,
                           it.item_name
                    FROM {schema}.transfer_item ti
                    LEFT JOIN {schema}.item it ON it.item_id = ti.item_id
                    WHERE ti.transfer_id IN ({placeholders})
                    ORDER BY ti.transfer_id, ti.item_id
                    """,
                    tids,
                )
                for row in cursor.fetchall():
                    tid = int(row[0])
                    if tid in transfers:
                        transfers[tid]["items"].append({
                            "item_id": int(row[1]),
                            "item_qty": _to_float(row[2]),
                            "uom_code": str(row[3]) if row[3] else "EA",
                            "item_name": str(row[4]) if row[4] else f"Item {row[1]}",
                        })
    except DatabaseError as exc:
        logger.warning("Get transfers for needs list failed: %s", exc)
        try:
            connection.rollback()
        except Exception as rollback_exc:
            logger.warning("DB rollback failed: %s", rollback_exc)
        warnings.append("db_unavailable_preview_stub")
        return [], warnings

    return list(transfers.values()), warnings


def update_transfer_draft(
    transfer_id: int, needs_list_id: str, updates: Dict
) -> List[str]:
    """
    Update a draft transfer's items (qty, source warehouse).
    updates should contain: items: [{item_id, item_qty}], reason: str
    """
    if _is_sqlite():
        return ["db_unavailable_preview_stub"]

    schema = _schema_name()
    warnings: List[str] = []
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT status_code
                FROM {schema}.transfer
                WHERE transfer_id = %s
                  AND needs_list_id = %s
                """,
                [transfer_id, needs_list_id],
            )
            row = cursor.fetchone()
            if not row:
                warnings.append("transfer_not_found_for_needs_list")
                return warnings
            if str(row[0]) != "P":
                warnings.append("transfer_not_found_or_not_draft")
                return warnings

            if updates.get("reason"):
                cursor.execute(
                    f"""
                    UPDATE {schema}.transfer
                    SET reason_text = %s
                    WHERE transfer_id = %s
                      AND needs_list_id = %s
                      AND status_code = 'P'
                    """,
                    [updates["reason"], transfer_id, needs_list_id],
                )
            for item in updates.get("items", []):
                cursor.execute(
                    f"""
                    UPDATE {schema}.transfer_item ti
                    SET item_qty = %s
                    FROM {schema}.transfer t
                    WHERE ti.transfer_id = %s
                      AND ti.item_id = %s
                      AND t.transfer_id = ti.transfer_id
                      AND t.needs_list_id = %s
                      AND t.status_code = 'P'
                    """,
                    [item["item_qty"], transfer_id, item["item_id"], needs_list_id],
                )
    except DatabaseError as exc:
        logger.warning("Update transfer draft failed: %s", exc)
        try:
            connection.rollback()
        except Exception as rollback_exc:
            logger.warning("DB rollback failed: %s", rollback_exc)
        warnings.append("db_error_update_transfer")
    return warnings


def confirm_transfer_draft(
    transfer_id: int, needs_list_id: str, actor_id: str
) -> Tuple[bool, List[str]]:
    """
    Confirm draft transfer → dispatched (status P → D).
    Returns (success, warnings).
    """
    if _is_sqlite():
        return False, ["db_unavailable_preview_stub"]

    schema = _schema_name()
    warnings: List[str] = []
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT status_code
                FROM {schema}.transfer
                WHERE transfer_id = %s
                  AND needs_list_id = %s
                """,
                [transfer_id, needs_list_id],
            )
            row = cursor.fetchone()
            if not row:
                warnings.append("transfer_not_found_for_needs_list")
                return False, warnings
            if str(row[0]) != "P":
                warnings.append("transfer_not_found_or_not_draft")
                return False, warnings

            cursor.execute(
                f"""
                UPDATE {schema}.transfer
                SET status_code = 'D',
                    update_user = %s,
                    update_dtime = NOW()
                WHERE transfer_id = %s
                  AND needs_list_id = %s
                  AND status_code = 'P'
                """,
                [actor_id, transfer_id, needs_list_id],
            )
            if cursor.rowcount == 0:
                warnings.append("transfer_not_found_or_not_draft")
                return False, warnings
            return True, warnings
    except DatabaseError as exc:
        logger.warning("Confirm transfer draft failed: %s", exc)
        try:
            connection.rollback()
        except Exception as rollback_exc:
            logger.warning("DB rollback failed: %s", rollback_exc)
        warnings.append("db_error_confirm_transfer")
        return False, warnings


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
    Returns a dict mapping item_id -> {"name": str, "code": str | None}, and any warnings.
    """
    if _is_sqlite():
        return {}, ["db_unavailable_preview_stub"]
    if not item_ids:
        return {}, []

    schema = _schema_name()
    item_data: Dict[int, Dict[str, str | None]] = {}
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
    Fetch the active event context for replenishment workflows.

    Selection priority:
    1) Most recently worked active event from needs_list activity.
    2) Fallback to the most recent active event by start date.

    Returns a dict with keys:
    - event_id
    - event_name
    - status
    - phase
    - declaration_date

    Returns None when no active event is available.
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
            # Query for all active events (status_code 'A' or 'ACTIVE' = Active)
            cursor.execute(
                f"""
                SELECT event_id, event_name, status_code, current_phase, start_date
                FROM {schema}.event
                WHERE UPPER(status_code) IN (%s, %s)
                ORDER BY start_date DESC
                """,
                ["A", "ACTIVE"],
            )
            rows = cursor.fetchall()
            if not rows:
                return None

            events = [
                {
                    "event_id": int(row[0]),
                    "event_name": str(row[1]) if row[1] else f"Event {row[0]}",
                    "status": str(row[2]) if row[2] else "A",
                    "phase": str(row[3]).upper() if row[3] else "BASELINE",
                    "declaration_date": row[4].isoformat() if row[4] else None,
                }
                for row in rows
            ]

            # Prefer the most recently worked active event from needs-list workflow activity.
            selected = events[0]
            active_event_ids = [event["event_id"] for event in events]

            try:
                cursor.execute(
                    f"""
                    SELECT event_id, event_phase
                    FROM {schema}.needs_list
                    WHERE event_id = ANY(%s)
                    ORDER BY COALESCE(
                        approved_at,
                        reviewed_at,
                        submitted_at,
                        update_dtime,
                        create_dtime
                    ) DESC
                    LIMIT 1
                    """,
                    [active_event_ids],
                )
                latest_activity = cursor.fetchone()
            except DatabaseError as exc:
                logger.warning("Active event workflow preference query failed: %s", exc)
                try:
                    connection.rollback()
                except Exception as rb_exc:
                    logger.exception(
                        "Rollback failed after DatabaseError in active event workflow preference query: "
                        "rollback_error=%s, original_error=%s",
                        rb_exc,
                        exc,
                    )
                latest_activity = None

            if latest_activity:
                latest_event_id = int(latest_activity[0])
                latest_phase = str(latest_activity[1]).upper() if latest_activity[1] else None
                for event in events:
                    if event["event_id"] == latest_event_id:
                        selected = dict(event)
                        if latest_phase:
                            selected["phase"] = latest_phase
                        break

            return selected
    except DatabaseError as exc:
        logger.warning("Active event query failed: %s", exc)
        try:
            connection.rollback()
        except Exception as rollback_exc:
            logger.warning("DB rollback failed after active event query error: %s", rollback_exc)

    return None


def get_event_name(event_id: int) -> str:
    """
    Fetch event name by event ID.
    Returns a fallback format "Event {id}" when not found.
    """
    if _is_sqlite():
        if int(event_id) == 1:
            return "Development Test Event"
        return f"Event {event_id}"

    schema = _schema_name()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT event_name
                FROM {schema}.event
                WHERE event_id = %s
                LIMIT 1
                """,
                [event_id],
            )
            row = cursor.fetchone()
            if row and row[0]:
                return str(row[0])
    except DatabaseError as exc:
        logger.warning("Event name query failed for event_id=%s: %s", event_id, exc)
        try:
            connection.rollback()
        except Exception as rollback_exc:
            logger.warning("DB rollback failed after event query error: %s", rollback_exc)

    return f"Event {event_id}"


def get_event_names(event_ids: List[int]) -> Tuple[Dict[int, str], List[str]]:
    """
    Fetch event names for many event IDs in one query.
    Returns a dict mapping event_id -> event_name and any warnings.
    """
    if not event_ids:
        return {}, []

    unique_ids = sorted({int(event_id) for event_id in event_ids if event_id is not None})
    if not unique_ids:
        return {}, []

    if _is_sqlite():
        return {
            event_id: "Development Test Event" if event_id == 1 else f"Event {event_id}"
            for event_id in unique_ids
        }, []

    schema = _schema_name()
    event_names: Dict[int, str] = {}
    warnings: List[str] = []
    try:
        placeholders = ",".join(["%s"] * len(unique_ids))
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT event_id, event_name
                FROM {schema}.event
                WHERE event_id IN ({placeholders})
                """,
                unique_ids,
            )
            for event_id, event_name in cursor.fetchall():
                event_names[int(event_id)] = (
                    str(event_name) if event_name else f"Event {event_id}"
                )
    except DatabaseError as exc:
        logger.warning("Event names query failed for event_ids=%s: %s", unique_ids, exc)
        try:
            connection.rollback()
        except Exception as rollback_exc:
            logger.warning("DB rollback failed after event names query error: %s", rollback_exc)
        warnings.append("db_unavailable_event_names")

    for event_id in unique_ids:
        event_names.setdefault(event_id, f"Event {event_id}")
    return event_names, warnings


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
