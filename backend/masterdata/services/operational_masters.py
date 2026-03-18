from __future__ import annotations

import logging
from typing import Any

from masterdata.services.data_access import (
    _is_sqlite,
    _parse_sort_expression,
    _safe_rollback,
    _schema_name,
    get_record,
    list_records,
)

from django.db import DatabaseError, connection

logger = logging.getLogger(__name__)

_WAREHOUSE_STOCK_HEALTH_STATUSES = {"GREEN", "AMBER", "RED", "UNKNOWN"}


def list_warehouse_records(
    *,
    status_filter: str | None = None,
    search: str | None = None,
    order_by: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int, list[str]]:
    rows, total, warnings = list_records(
        "warehouses",
        status_filter=status_filter,
        search=search,
        order_by=order_by,
        limit=limit,
        offset=offset,
    )
    if rows:
        _attach_warehouse_hierarchy_metadata(rows, warnings)
        _attach_stock_health_summary(rows, warnings)
    return rows, total, warnings


def get_warehouse_record(warehouse_id: Any) -> tuple[dict[str, Any] | None, list[str]]:
    record, warnings = get_record("warehouses", warehouse_id)
    if record is None:
        return None, warnings

    rows = [record]
    _attach_warehouse_hierarchy_metadata(rows, warnings)
    _attach_stock_health_summary(rows, warnings)
    return record, warnings


def validate_operational_master_payload(
    table_key: str,
    data: dict[str, Any],
    *,
    is_update: bool,
    existing_record: dict[str, Any] | None = None,
    current_pk: Any | None = None,
) -> tuple[dict[str, str], list[str]]:
    if _is_sqlite():
        return {}, []

    if table_key == "warehouses":
        return validate_warehouse_payload(
            data,
            is_update=is_update,
            existing_record=existing_record,
            current_pk=current_pk,
        )
    if table_key == "agencies":
        return validate_agency_payload(
            data,
            is_update=is_update,
            existing_record=existing_record,
        )
    return {}, []


def validate_warehouse_payload(
    data: dict[str, Any],
    *,
    is_update: bool,
    existing_record: dict[str, Any] | None = None,
    current_pk: Any | None = None,
) -> tuple[dict[str, str], list[str]]:
    errors: dict[str, str] = {}
    warnings: list[str] = []

    warehouse_type = str(
        _merged_value(data, existing_record, "warehouse_type") or ""
    ).strip().upper()
    parent_warehouse_id = _parse_optional_int(
        _merged_value(data, existing_record, "parent_warehouse_id")
    )

    if warehouse_type == "SUB-HUB" and parent_warehouse_id is None:
        errors["parent_warehouse_id"] = "Parent warehouse is required for SUB-HUB warehouses."
        return errors, warnings

    if warehouse_type == "MAIN-HUB" and parent_warehouse_id is not None:
        errors["parent_warehouse_id"] = "MAIN-HUB warehouses cannot have a parent warehouse."
        return errors, warnings

    current_warehouse_id = _parse_optional_int(current_pk)
    if current_warehouse_id is not None and parent_warehouse_id == current_warehouse_id:
        errors["parent_warehouse_id"] = "A warehouse cannot be its own parent."
        return errors, warnings

    if parent_warehouse_id is None:
        return errors, warnings

    schema = _schema_name()
    try:
        parent_record = _fetch_warehouse_minimal(schema, parent_warehouse_id)
    except DatabaseError as exc:
        logger.warning("validate_warehouse_payload failed to load parent warehouse %s: %s", parent_warehouse_id, exc)
        _safe_rollback()
        return errors, ["warehouse_parent_lookup_failed"]

    if parent_record is None:
        errors["parent_warehouse_id"] = "Selected parent warehouse does not exist."
        return errors, warnings

    if str(parent_record.get("status_code") or "").upper() != "A":
        errors["parent_warehouse_id"] = "Selected parent warehouse must be active."
    elif str(parent_record.get("warehouse_type") or "").upper() != "MAIN-HUB":
        errors["parent_warehouse_id"] = "SUB-HUB warehouses must belong to an active MAIN-HUB warehouse."
    return errors, warnings


def validate_agency_payload(
    data: dict[str, Any],
    *,
    is_update: bool,
    existing_record: dict[str, Any] | None = None,
) -> tuple[dict[str, str], list[str]]:
    errors: dict[str, str] = {}
    warnings: list[str] = []

    warehouse_id = _parse_optional_int(_merged_value(data, existing_record, "warehouse_id"))
    if warehouse_id is None:
        return errors, warnings

    schema = _schema_name()
    try:
        warehouse_record = _fetch_warehouse_minimal(schema, warehouse_id)
    except DatabaseError as exc:
        logger.warning("validate_agency_payload failed to load warehouse %s: %s", warehouse_id, exc)
        _safe_rollback()
        return errors, ["agency_warehouse_lookup_failed"]

    if warehouse_record is None:
        errors["warehouse_id"] = "Selected Warehouse does not exist."
    elif str(warehouse_record.get("status_code") or "").upper() != "A":
        errors["warehouse_id"] = "Selected Warehouse must be active."
    return errors, warnings


def list_stock_health_records(
    *,
    warehouse_id: Any | None = None,
    item_id: Any | None = None,
    health_status: str | None = None,
    order_by: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int, list[str]]:
    if _is_sqlite():
        return [], 0, ["db_unavailable"]

    schema = _schema_name()
    warnings: list[str] = []
    where_clauses: list[str] = []
    params: list[Any] = []

    parsed_warehouse_id = _parse_optional_int(warehouse_id)
    if warehouse_id not in (None, ""):
        if parsed_warehouse_id is None:
            warnings.append("invalid_warehouse_id_filter")
        else:
            where_clauses.append("warehouse_id = %s")
            params.append(parsed_warehouse_id)

    parsed_item_id = _parse_optional_int(item_id)
    if item_id not in (None, ""):
        if parsed_item_id is None:
            warnings.append("invalid_item_id_filter")
        else:
            where_clauses.append("item_id = %s")
            params.append(parsed_item_id)

    normalized_health_status = str(health_status or "").strip().upper()
    if normalized_health_status:
        if normalized_health_status not in _WAREHOUSE_STOCK_HEALTH_STATUSES:
            warnings.append("invalid_stock_health_filter")
        else:
            where_clauses.append("stock_health_status = %s")
            params.append(normalized_health_status)

    where_sql = ""
    if where_clauses:
        where_sql = "WHERE " + " AND ".join(where_clauses)

    allowed_columns = {
        "warehouse_name": "warehouse_name",
        "item_name": "item_name",
        "item_code": "item_code",
        "available_stock": "available_stock",
        "reorder_level_qty": "reorder_level_qty",
        "stock_health_status": "stock_health_status",
        "surplus_qty": "surplus_qty",
        "data_freshness": "data_freshness",
    }
    resolved_order = _parse_sort_expression(order_by, allowed_columns=allowed_columns)
    if resolved_order is None:
        if order_by and str(order_by).strip():
            warnings.append("invalid_order_by")
        resolved_order = "warehouse_name ASC, item_name ASC"

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT COUNT(*) FROM {schema}.v_stock_status {where_sql}",
                params,
            )
            total = int(cursor.fetchone()[0] or 0)
            cursor.execute(
                f"""
                SELECT
                    warehouse_id,
                    warehouse_name,
                    warehouse_type,
                    parent_warehouse_id,
                    item_id,
                    item_code,
                    item_name,
                    criticality_level,
                    available_stock,
                    reserved_qty,
                    reorder_level_qty,
                    reorder_level_source,
                    min_threshold,
                    surplus_qty,
                    stock_health_status,
                    last_sync_dtime,
                    sync_status,
                    data_freshness
                FROM {schema}.v_stock_status
                {where_sql}
                ORDER BY {resolved_order}
                LIMIT %s OFFSET %s
                """,
                params + [limit, offset],
            )
            rows = [
                {
                    "warehouse_id": row[0],
                    "warehouse_name": row[1],
                    "warehouse_type": row[2],
                    "parent_warehouse_id": row[3],
                    "item_id": row[4],
                    "item_code": row[5],
                    "item_name": row[6],
                    "criticality_level": row[7],
                    "available_stock": row[8],
                    "reserved_qty": row[9],
                    "reorder_level_qty": row[10],
                    "reorder_level_source": row[11],
                    "min_threshold": row[12],
                    "surplus_qty": row[13],
                    "stock_health_status": row[14],
                    "last_sync_dtime": row[15],
                    "sync_status": row[16],
                    "data_freshness": row[17],
                }
                for row in cursor.fetchall()
            ]
        return rows, total, warnings
    except DatabaseError as exc:
        logger.warning("list_stock_health_records failed: %s", exc)
        _safe_rollback()
        return [], 0, ["db_error"]


def _attach_warehouse_hierarchy_metadata(
    rows: list[dict[str, Any]],
    warnings: list[str],
) -> None:
    if _is_sqlite() or not rows:
        return

    schema = _schema_name()
    warehouse_ids = [int(row["warehouse_id"]) for row in rows if row.get("warehouse_id") is not None]
    parent_ids = sorted(
        {
            int(row["parent_warehouse_id"])
            for row in rows
            if row.get("parent_warehouse_id") not in (None, "")
        }
    )
    if not warehouse_ids and not parent_ids:
        return

    parent_name_map: dict[int, str] = {}
    child_count_map: dict[int, int] = {}

    try:
        with connection.cursor() as cursor:
            if parent_ids:
                placeholders = ", ".join(["%s"] * len(parent_ids))
                cursor.execute(
                    f"""
                    SELECT warehouse_id, warehouse_name
                    FROM {schema}.warehouse
                    WHERE warehouse_id IN ({placeholders})
                    """,
                    parent_ids,
                )
                parent_name_map = {
                    int(warehouse_id): str(warehouse_name or f"Warehouse {warehouse_id}")
                    for warehouse_id, warehouse_name in cursor.fetchall()
                }

            if warehouse_ids:
                placeholders = ", ".join(["%s"] * len(warehouse_ids))
                cursor.execute(
                    f"""
                    SELECT parent_warehouse_id, COUNT(*)
                    FROM {schema}.warehouse
                    WHERE parent_warehouse_id IN ({placeholders})
                      AND status_code = 'A'
                    GROUP BY parent_warehouse_id
                    """,
                    warehouse_ids,
                )
                child_count_map = {
                    int(parent_warehouse_id): int(child_count)
                    for parent_warehouse_id, child_count in cursor.fetchall()
                    if parent_warehouse_id is not None
                }
    except DatabaseError as exc:
        logger.warning("Warehouse hierarchy enrichment failed: %s", exc)
        _safe_rollback()
        warnings.append("warehouse_hierarchy_lookup_failed")
        return

    for row in rows:
        parent_id = _parse_optional_int(row.get("parent_warehouse_id"))
        row["hub_parent"] = (
            {
                "warehouse_id": parent_id,
                "warehouse_name": parent_name_map.get(parent_id, f"Warehouse {parent_id}"),
            }
            if parent_id is not None
            else None
        )
        row["child_warehouse_count"] = child_count_map.get(
            _parse_optional_int(row.get("warehouse_id")) or -1,
            0,
        )


def _attach_stock_health_summary(
    rows: list[dict[str, Any]],
    warnings: list[str],
) -> None:
    if _is_sqlite() or not rows:
        return

    schema = _schema_name()
    warehouse_ids = sorted(
        {
            int(row["warehouse_id"])
            for row in rows
            if row.get("warehouse_id") is not None
        }
    )
    if not warehouse_ids:
        return

    summary_by_warehouse: dict[int, dict[str, Any]] = {}
    try:
        placeholders = ", ".join(["%s"] * len(warehouse_ids))
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT
                    warehouse_id,
                    COUNT(*) FILTER (WHERE stock_health_status = 'GREEN') AS green_count,
                    COUNT(*) FILTER (WHERE stock_health_status = 'AMBER') AS amber_count,
                    COUNT(*) FILTER (WHERE stock_health_status = 'RED') AS red_count,
                    COUNT(*) FILTER (WHERE stock_health_status = 'UNKNOWN') AS unknown_count
                FROM {schema}.v_stock_status
                WHERE warehouse_id IN ({placeholders})
                GROUP BY warehouse_id
                """,
                warehouse_ids,
            )
            for warehouse_id, green_count, amber_count, red_count, unknown_count in cursor.fetchall():
                summary_by_warehouse[int(warehouse_id)] = {
                    "green_count": int(green_count or 0),
                    "amber_count": int(amber_count or 0),
                    "red_count": int(red_count or 0),
                    "unknown_count": int(unknown_count or 0),
                }
    except DatabaseError as exc:
        logger.warning("Warehouse stock health summary enrichment failed: %s", exc)
        _safe_rollback()
        warnings.append("warehouse_stock_health_lookup_failed")
        return

    for row in rows:
        warehouse_id = _parse_optional_int(row.get("warehouse_id"))
        summary = summary_by_warehouse.get(
            warehouse_id or -1,
            {
                "green_count": 0,
                "amber_count": 0,
                "red_count": 0,
                "unknown_count": 0,
            },
        )
        summary = dict(summary)
        summary["overall_status"] = _overall_stock_health_status(summary)
        row["stock_health_summary"] = summary


def _overall_stock_health_status(summary: dict[str, Any]) -> str:
    if int(summary.get("red_count") or 0) > 0:
        return "RED"
    if int(summary.get("amber_count") or 0) > 0:
        return "AMBER"
    if int(summary.get("green_count") or 0) > 0:
        return "GREEN"
    return "UNKNOWN"


def _fetch_warehouse_minimal(schema: str, warehouse_id: int) -> dict[str, Any] | None:
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT warehouse_id, warehouse_name, warehouse_type, status_code, tenant_id
            FROM {schema}.warehouse
            WHERE warehouse_id = %s
            LIMIT 1
            """,
            [warehouse_id],
        )
        row = cursor.fetchone()
    if not row:
        return None
    return {
        "warehouse_id": int(row[0]),
        "warehouse_name": str(row[1] or f"Warehouse {warehouse_id}"),
        "warehouse_type": str(row[2] or ""),
        "status_code": str(row[3] or ""),
        "tenant_id": row[4],
    }


def _merged_value(
    data: dict[str, Any],
    existing_record: dict[str, Any] | None,
    field_name: str,
) -> Any:
    if field_name in data:
        return data.get(field_name)
    if existing_record is not None:
        return existing_record.get(field_name)
    return None


def _parse_optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
