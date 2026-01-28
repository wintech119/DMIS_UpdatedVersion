import logging
import os
from datetime import timedelta
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
        return timezone.make_naive(dt, timezone.utc)
    return dt


def get_available_by_item(
    warehouse_id: int, as_of_dt
) -> Tuple[Dict[int, float], List[str], object | None]:
    if _is_sqlite():
        return {}, ["db_unavailable_preview_stub"], None

    warnings: List[str] = []
    available: Dict[int, float] = {}
    status = getattr(settings, "NEEDS_INVENTORY_ACTIVE_STATUS", "A")
    inventory_as_of = None
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT ib.item_id, SUM(ib.usable_qty - ib.reserved_qty) AS qty
                FROM itembatch ib
                JOIN inventory i
                    ON i.inventory_id = ib.inventory_id AND i.item_id = ib.item_id
                WHERE ib.inventory_id = %s
                  AND ib.status_code = %s
                  AND i.status_code = %s
                GROUP BY ib.item_id
                """,
                [warehouse_id, status, status],
            )
            for item_id, qty in cursor.fetchall():
                available[int(item_id)] = _to_float(qty)

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT item_id, SUM(usable_qty - reserved_qty) AS qty
                FROM inventory
                WHERE inventory_id = %s
                  AND status_code = %s
                GROUP BY item_id
                """,
                [warehouse_id, status],
            )
            for item_id, qty in cursor.fetchall():
                item_id = int(item_id)
                if item_id not in available:
                    available[item_id] = _to_float(qty)
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT MAX(update_dtime)
                FROM inventory
                WHERE inventory_id = %s
                """,
                [warehouse_id],
            )
            row = cursor.fetchone()
            inventory_as_of = row[0] if row else None
    except DatabaseError as exc:
        logger.warning("Available inventory query failed: %s", exc)
        warnings.append("db_unavailable_preview_stub")
        return {}, warnings, None

    return available, warnings, inventory_as_of


def get_inbound_donations_by_item(
    warehouse_id: int, as_of_dt
) -> Tuple[Dict[int, float], List[str]]:
    statuses, warnings = rules.resolve_strict_inbound_donation_codes()
    if _is_sqlite():
        warnings.append("db_unavailable_preview_stub")
        return {}, warnings
    if not statuses:
        return {}, warnings

    as_of_date = _normalize_datetime(as_of_dt).date()
    inbound: Dict[int, float] = {}
    try:
        placeholders = ",".join(["%s"] * len(statuses))
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT di.item_id, SUM(di.usable_qty) AS qty
                FROM dnintake_item di
                JOIN dnintake d
                  ON d.donation_id = di.donation_id
                 AND d.inventory_id = di.inventory_id
                JOIN donation dn
                  ON dn.donation_id = di.donation_id
                WHERE di.inventory_id = %s
                  AND dn.status_code IN ({placeholders})
                  AND di.status_code IN ('P', 'V')
                  AND d.intake_date <= %s
                GROUP BY di.item_id
                """,
                [warehouse_id, *statuses, as_of_date],
            )
            for item_id, qty in cursor.fetchall():
                inbound[int(item_id)] = _to_float(qty)
    except DatabaseError as exc:
        logger.warning("Inbound donations query failed: %s", exc)
        warnings.append("db_unavailable_preview_stub")
        return {}, warnings

    return inbound, warnings


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
    inbound: Dict[int, float] = {}
    try:
        placeholders = ",".join(["%s"] * len(statuses))
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT ti.item_id, SUM(ti.item_qty) AS qty
                FROM transfer_item ti
                JOIN transfer t ON t.transfer_id = ti.transfer_id
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
    start_date = start_dt.date()
    end_date = end_dt.date()
    burn: Dict[int, float] = {}

    primary = getattr(settings, "NEEDS_BURN_SOURCE", "reliefpkg")
    fallback = getattr(settings, "NEEDS_BURN_FALLBACK", "reliefrqst")

    if primary == "reliefpkg":
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT rpi.item_id, SUM(rpi.item_qty) AS qty
                    FROM reliefpkg_item rpi
                    JOIN reliefpkg rp ON rp.reliefpkg_id = rpi.reliefpkg_id
                    WHERE rp.to_inventory_id = %s
                      AND rp.eligible_event_id = %s
                      AND COALESCE(rp.dispatch_dtime, rp.start_date)
                          BETWEEN %s AND %s
                    GROUP BY rpi.item_id
                    """,
                    [warehouse_id, event_id, start_date, end_date],
                )
                for item_id, qty in cursor.fetchall():
                    burn[int(item_id)] = _to_float(qty)
        except DatabaseError as exc:
            logger.warning("Burn query (reliefpkg) failed: %s", exc)
            warnings.append("db_unavailable_preview_stub")
            return {}, warnings, "none"

        if burn:
            return burn, warnings, "reliefpkg"

    if fallback == "reliefrqst":
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT rri.item_id, SUM(rri.issue_qty) AS qty
                    FROM reliefrqst_item rri
                    JOIN reliefrqst rr ON rr.reliefrqst_id = rri.reliefrqst_id
                    JOIN agency a ON a.agency_id = rr.agency_id
                    WHERE rr.eligible_event_id = %s
                      AND a.warehouse_id = %s
                      AND rr.request_date BETWEEN %s AND %s
                    GROUP BY rri.item_id
                    """,
                    [event_id, warehouse_id, start_date, end_date],
                )
                for item_id, qty in cursor.fetchall():
                    burn[int(item_id)] = _to_float(qty)
        except DatabaseError as exc:
            logger.warning("Burn query (reliefrqst) failed: %s", exc)
            warnings.append("db_unavailable_preview_stub")
            return {}, warnings, "none"

        if burn:
            warnings.append("burn_source_fallback_reliefrqst")
            return burn, warnings, "reliefrqst"

    warnings.append("burn_data_missing")
    return {}, warnings, "none"
