from __future__ import annotations

import logging
import os
import re
from datetime import date

from django.conf import settings
from django.db import DatabaseError, connection, transaction

logger = logging.getLogger(__name__)


class LocationAssignmentError(ValueError):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


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


def _normalize_actor(actor_id: str | None) -> str:
    normalized = str(actor_id or "").strip()
    if not normalized:
        return "SYSTEM"
    return normalized[:20]


def _fetch_item_batched_flag(item_id: int) -> bool:
    schema = _schema_name()
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT is_batched_flag
            FROM {schema}.item
            WHERE item_id = %s
            LIMIT 1
            """,
            [item_id],
        )
        row = cursor.fetchone()
        if not row:
            raise LocationAssignmentError(
                "item_not_found",
                f"Item {item_id} was not found.",
                status_code=404,
            )
        return bool(row[0])


def _ensure_location_exists(location_id: int) -> None:
    schema = _schema_name()
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT 1
            FROM {schema}.location
            WHERE location_id = %s
            LIMIT 1
            """,
            [location_id],
        )
        if cursor.fetchone() is None:
            raise LocationAssignmentError(
                "location_not_found",
                f"Location {location_id} was not found.",
                status_code=404,
            )


def _ensure_inventory_item_exists(inventory_id: int, item_id: int) -> None:
    schema = _schema_name()
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT 1
            FROM {schema}.inventory
            WHERE inventory_id = %s
              AND item_id = %s
            LIMIT 1
            """,
            [inventory_id, item_id],
        )
        if cursor.fetchone() is None:
            raise LocationAssignmentError(
                "inventory_item_not_found",
                (
                    "Inventory item mapping was not found for "
                    f"inventory_id={inventory_id}, item_id={item_id}."
                ),
                status_code=404,
            )


def _ensure_itembatch_exists(inventory_id: int, item_id: int, batch_id: int) -> None:
    schema = _schema_name()
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT 1
            FROM {schema}.itembatch
            WHERE inventory_id = %s
              AND item_id = %s
              AND batch_id = %s
            LIMIT 1
            """,
            [inventory_id, item_id, batch_id],
        )
        if cursor.fetchone() is None:
            raise LocationAssignmentError(
                "itembatch_not_found",
                (
                    "Item batch mapping was not found for "
                    f"inventory_id={inventory_id}, item_id={item_id}, batch_id={batch_id}."
                ),
                status_code=404,
            )


def _format_inventory_option_label(warehouse_name: object, inventory_id: int) -> str:
    name = str(warehouse_name or "").strip()
    return name or f"Warehouse {inventory_id}"


def _format_location_option_label(location_desc: object, location_id: int) -> str:
    description = str(location_desc or "").strip()
    return description or f"Location {location_id}"


def _format_batch_option_label(
    *,
    batch_id: int,
    batch_no: object,
    expiry_date: date | None,
) -> str:
    batch_label = str(batch_no or "").strip() or f"Batch {batch_id}"
    if expiry_date is None:
        return batch_label
    return f"{batch_label} · Expires {expiry_date.isoformat()}"


def _fetch_inventory_assignment_options(item_id: int) -> list[dict[str, object]]:
    schema = _schema_name()
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            WITH inventory_ids AS (
                SELECT DISTINCT inventory_id
                FROM {schema}.inventory
                WHERE item_id = %s
                UNION
                SELECT DISTINCT inventory_id
                FROM {schema}.itembatch
                WHERE item_id = %s
            )
            SELECT inventory_ids.inventory_id, w.warehouse_name
            FROM inventory_ids
            LEFT JOIN {schema}.warehouse w
              ON w.warehouse_id = inventory_ids.inventory_id
            ORDER BY COALESCE(w.warehouse_name, ''), inventory_ids.inventory_id
            """,
            [item_id, item_id],
        )
        return [
            {
                "value": int(inventory_id),
                "label": _format_inventory_option_label(warehouse_name, int(inventory_id)),
                "detail": f"Internal inventory ID {int(inventory_id)}",
            }
            for inventory_id, warehouse_name in cursor.fetchall()
        ]


def _fetch_location_assignment_options(item_id: int) -> list[dict[str, object]]:
    schema = _schema_name()
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            WITH inventory_ids AS (
                SELECT DISTINCT inventory_id
                FROM {schema}.inventory
                WHERE item_id = %s
                UNION
                SELECT DISTINCT inventory_id
                FROM {schema}.itembatch
                WHERE item_id = %s
            )
            SELECT l.location_id, l.inventory_id, l.location_desc
            FROM {schema}.location l
            INNER JOIN inventory_ids
              ON inventory_ids.inventory_id = l.inventory_id
            ORDER BY l.inventory_id, COALESCE(l.location_desc, ''), l.location_id
            """,
            [item_id, item_id],
        )
        return [
            {
                "value": int(location_id),
                "inventory_id": int(inventory_id),
                "label": _format_location_option_label(location_desc, int(location_id)),
                "detail": f"Internal location ID {int(location_id)}",
            }
            for location_id, inventory_id, location_desc in cursor.fetchall()
        ]


def _fetch_batch_assignment_options(item_id: int) -> list[dict[str, object]]:
    schema = _schema_name()
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT batch_id, inventory_id, batch_no, expiry_date
            FROM {schema}.itembatch
            WHERE item_id = %s
            ORDER BY inventory_id, COALESCE(batch_no, ''), expiry_date NULLS LAST, batch_id
            """,
            [item_id],
        )
        return [
            {
                "value": int(batch_id),
                "inventory_id": int(inventory_id),
                "label": _format_batch_option_label(
                    batch_id=int(batch_id),
                    batch_no=batch_no,
                    expiry_date=expiry_date,
                ),
                "detail": f"Internal batch ID {int(batch_id)}",
            }
            for batch_id, inventory_id, batch_no, expiry_date in cursor.fetchall()
        ]


def get_storage_assignment_options(*, item_id: int) -> dict[str, object]:
    if _is_sqlite():
        raise LocationAssignmentError(
            "db_unavailable",
            "Storage assignment lookups require PostgreSQL and are unavailable in SQLite mode.",
            status_code=503,
        )

    if item_id <= 0:
        raise LocationAssignmentError(
            "validation",
            "item_id must be a positive integer.",
            status_code=400,
        )

    is_batched = _fetch_item_batched_flag(item_id)

    try:
        return {
            "item_id": item_id,
            "is_batched": is_batched,
            "inventories": _fetch_inventory_assignment_options(item_id),
            "locations": _fetch_location_assignment_options(item_id),
            "batches": _fetch_batch_assignment_options(item_id),
        }
    except DatabaseError as exc:
        logger.warning(
            "Storage assignment options lookup failed for item_id=%s: %s",
            item_id,
            exc,
        )
        raise LocationAssignmentError(
            "location_storage_error",
            "Unable to load storage assignment options because of a storage error.",
            status_code=500,
        ) from exc


def _assign_item_location(
    *,
    inventory_id: int,
    item_id: int,
    location_id: int,
    actor_id: str,
) -> bool:
    schema = _schema_name()
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            INSERT INTO {schema}.item_location (
                inventory_id,
                item_id,
                location_id,
                create_by_id,
                create_dtime
            )
            VALUES (%s, %s, %s, %s, NOW())
            ON CONFLICT (item_id, location_id) DO NOTHING
            RETURNING inventory_id
            """,
            [inventory_id, item_id, location_id, actor_id],
        )
        inserted = cursor.fetchone() is not None
        if inserted:
            return True

        cursor.execute(
            f"""
            SELECT inventory_id
            FROM {schema}.item_location
            WHERE item_id = %s
              AND location_id = %s
            LIMIT 1
            """,
            [item_id, location_id],
        )
        existing = cursor.fetchone()
        if not existing:
            return False

        existing_inventory_id = int(existing[0])
        if existing_inventory_id != inventory_id:
            raise LocationAssignmentError(
                "item_location_conflict",
                (
                    "Location assignment conflict for non-batched item: "
                    f"item_id={item_id}, location_id={location_id} is already tied to "
                    f"inventory_id={existing_inventory_id}."
                ),
                status_code=409,
            )
        return False


def _assign_batch_location(
    *,
    inventory_id: int,
    location_id: int,
    batch_id: int,
    actor_id: str,
) -> bool:
    schema = _schema_name()
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            INSERT INTO {schema}.batchlocation (
                inventory_id,
                location_id,
                batch_id,
                create_by_id,
                create_dtime
            )
            VALUES (%s, %s, %s, %s, NOW())
            ON CONFLICT (inventory_id, location_id, batch_id) DO NOTHING
            RETURNING batch_id
            """,
            [inventory_id, location_id, batch_id, actor_id],
        )
        return cursor.fetchone() is not None


def assign_storage_location(
    *,
    item_id: int,
    inventory_id: int,
    location_id: int,
    batch_id: int | None,
    actor_id: str | None,
) -> dict[str, object]:
    if _is_sqlite():
        raise LocationAssignmentError(
            "db_unavailable",
            "Location assignment requires PostgreSQL and is unavailable in SQLite mode.",
            status_code=503,
        )

    if item_id <= 0 or inventory_id <= 0 or location_id <= 0:
        raise LocationAssignmentError(
            "validation",
            "item_id, inventory_id, and location_id must all be positive integers.",
            status_code=400,
        )

    normalized_actor = _normalize_actor(actor_id)

    try:
        with transaction.atomic():
            is_batched = _fetch_item_batched_flag(item_id)
            _ensure_location_exists(location_id)

            if is_batched:
                if batch_id is None:
                    raise LocationAssignmentError(
                        "batch_id_required",
                        "batch_id is required for batched items.",
                        status_code=400,
                    )
                _ensure_itembatch_exists(inventory_id, item_id, batch_id)
                created = _assign_batch_location(
                    inventory_id=inventory_id,
                    location_id=location_id,
                    batch_id=batch_id,
                    actor_id=normalized_actor,
                )
                return {
                    "storage_table": "batchlocation",
                    "created": created,
                    "item_id": item_id,
                    "inventory_id": inventory_id,
                    "location_id": location_id,
                    "batch_id": batch_id,
                }

            if batch_id is not None:
                raise LocationAssignmentError(
                    "batch_id_not_allowed",
                    "batch_id is not allowed for non-batched items.",
                    status_code=400,
                )

            _ensure_inventory_item_exists(inventory_id, item_id)
            created = _assign_item_location(
                inventory_id=inventory_id,
                item_id=item_id,
                location_id=location_id,
                actor_id=normalized_actor,
            )
            return {
                "storage_table": "item_location",
                "created": created,
                "item_id": item_id,
                "inventory_id": inventory_id,
                "location_id": location_id,
                "batch_id": None,
            }
    except LocationAssignmentError:
        raise
    except DatabaseError as exc:
        message = str(exc)
        lowered = message.lower()
        if "policy violation" in lowered:
            raise LocationAssignmentError(
                "location_policy_violation",
                message,
                status_code=409,
            ) from exc
        logger.warning(
            "Location assignment DB failure for item_id=%s inventory_id=%s location_id=%s batch_id=%s: %s",
            item_id,
            inventory_id,
            location_id,
            batch_id,
            exc,
        )
        raise LocationAssignmentError(
            "location_storage_error",
            "Unable to persist location assignment because of a storage error.",
            status_code=500,
        ) from exc
