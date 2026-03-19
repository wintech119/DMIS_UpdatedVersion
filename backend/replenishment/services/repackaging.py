from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any

from django.db import DatabaseError, connection, transaction

from replenishment.services.data_access import _is_sqlite, _schema_name

logger = logging.getLogger(__name__)

_QTY_SCALE = Decimal("0.000001")


class RepackagingError(ValueError):
    def __init__(
        self,
        code: str,
        detail: str,
        *,
        status_code: int = 400,
        diagnostic: str = "",
        warnings: list[str] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status_code = status_code
        self.diagnostic = diagnostic
        self.warnings = warnings or []
        self.payload = payload or {"code": code}


@dataclass(frozen=True)
class RepackagingComputation:
    source_qty: Decimal
    target_qty: Decimal
    equivalent_default_qty: Decimal
    source_conversion_factor: Decimal
    target_conversion_factor: Decimal


def create_repackaging_transaction(
    *,
    warehouse_id: int,
    item_id: int,
    source_uom_code: str,
    source_qty: Decimal,
    target_uom_code: str,
    reason_code: str,
    actor_id: str,
    note_text: str = "",
    batch_id: int | None = None,
    batch_or_lot: str = "",
    client_target_qty: Decimal | None = None,
    client_equivalent_default_qty: Decimal | None = None,
) -> tuple[dict[str, Any], list[str]]:
    if _is_sqlite():
        raise RepackagingError(
            "db_unavailable",
            "UOM repackaging requires PostgreSQL and is unavailable in SQLite mode.",
            status_code=503,
        )

    normalized_source_uom = str(source_uom_code or "").strip().upper()
    normalized_target_uom = str(target_uom_code or "").strip().upper()
    normalized_reason = str(reason_code or "").strip().upper()
    normalized_note = str(note_text or "").strip()
    normalized_batch_or_lot = str(batch_or_lot or "").strip()

    if not normalized_source_uom:
        raise RepackagingError("source_uom_required", "source_uom_code is required.")
    if not normalized_target_uom:
        raise RepackagingError("target_uom_required", "target_uom_code is required.")
    if normalized_source_uom == normalized_target_uom:
        raise RepackagingError(
            "same_uom_not_allowed",
            "Source and target UOMs must be different for repackaging.",
            status_code=409,
        )
    if not normalized_reason:
        raise RepackagingError("reason_code_required", "reason_code is required.")

    normalized_source_qty = _normalize_positive_decimal(source_qty, field_name="source_qty")
    schema = _schema_name()
    warnings: list[str] = []

    try:
        with transaction.atomic():
            context = _load_repackaging_context(
                schema=schema,
                warehouse_id=warehouse_id,
                item_id=item_id,
                source_uom_code=normalized_source_uom,
                target_uom_code=normalized_target_uom,
                batch_id=batch_id,
                batch_or_lot=normalized_batch_or_lot,
            )
            computation = _compute_repackaging_quantities(
                source_qty=normalized_source_qty,
                source_conversion_factor=context["source_conversion_factor"],
                target_conversion_factor=context["target_conversion_factor"],
            )
            available_default_qty = _quantize_qty(context["available_default_qty"])
            if available_default_qty < computation.equivalent_default_qty:
                raise RepackagingError(
                    "insufficient_stock",
                    "Source stock is insufficient for the requested repackaging quantity.",
                    status_code=409,
                    payload={
                        "code": "insufficient_stock",
                        "warehouse_id": warehouse_id,
                        "item_id": item_id,
                        "available_default_qty": str(available_default_qty),
                        "required_default_qty": str(computation.equivalent_default_qty),
                    },
                )

            if client_target_qty is not None:
                try:
                    normalized_client_target = _quantize_qty(client_target_qty)
                except (InvalidOperation, TypeError, ValueError):
                    warnings.append("client_target_qty_ignored")
                else:
                    if normalized_client_target != computation.target_qty:
                        warnings.append("client_target_qty_ignored")
            if client_equivalent_default_qty is not None:
                try:
                    normalized_client_equivalent = _quantize_qty(
                        client_equivalent_default_qty
                    )
                except (InvalidOperation, TypeError, ValueError):
                    warnings.append("client_equivalent_qty_ignored")
                else:
                    if normalized_client_equivalent != computation.equivalent_default_qty:
                        warnings.append("client_equivalent_qty_ignored")

            repackaging_id = _insert_repackaging_txn(
                schema=schema,
                warehouse_id=warehouse_id,
                item_id=item_id,
                batch_id=context["batch_id"],
                batch_no_snapshot=context["batch_no_snapshot"],
                expiry_date_snapshot=context["expiry_date_snapshot"],
                source_uom_code=normalized_source_uom,
                target_uom_code=normalized_target_uom,
                reason_code=normalized_reason,
                note_text=normalized_note,
                computation=computation,
                actor_id=actor_id,
            )

            after_state = {
                "warehouse_id": warehouse_id,
                "warehouse_name": context["warehouse_name"],
                "item_id": item_id,
                "item_code": context["item_code"],
                "item_name": context["item_name"],
                "batch_id": context["batch_id"],
                "batch_or_lot": context["batch_no_snapshot"] or context["batch_id"],
                "expiry_date": context["expiry_date_snapshot"],
                "source_uom_code": normalized_source_uom,
                "source_qty": computation.source_qty,
                "target_uom_code": normalized_target_uom,
                "target_qty": computation.target_qty,
                "equivalent_default_qty": computation.equivalent_default_qty,
                "source_conversion_factor": computation.source_conversion_factor,
                "target_conversion_factor": computation.target_conversion_factor,
                "reason_code": normalized_reason,
                "note_text": normalized_note,
                "available_default_qty": available_default_qty,
            }
            _insert_repackaging_audit(
                schema=schema,
                repackaging_id=repackaging_id,
                action_type="CREATE",
                before_state=None,
                after_state=after_state,
                reason_code=normalized_reason,
                note_text=normalized_note,
                actor_id=actor_id,
            )

            record, read_warnings = get_repackaging_transaction(
                repackaging_id,
                raise_on_error=True,
            )
            warnings.extend(read_warnings)
            if record is None:
                raise RepackagingError(
                    "repackaging_readback_failed",
                    "Failed to load the created repackaging transaction.",
                    status_code=500,
                )
            return record, warnings
    except RepackagingError:
        raise
    except DatabaseError as exc:
        logger.warning("create_repackaging_transaction failed: %s", exc)
        _safe_rollback()
        raise RepackagingError(
            "repackaging_storage_error",
            "Unable to persist repackaging because of a storage error.",
            status_code=500,
        ) from exc


def list_repackaging_transactions(
    *,
    warehouse_id: Any | None = None,
    item_id: Any | None = None,
    batch_id: Any | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int, list[str]]:
    if _is_sqlite():
        return [], 0, ["db_unavailable"]

    schema = _schema_name()
    where_clauses: list[str] = []
    params: list[Any] = []
    warnings: list[str] = []

    parsed_warehouse_id = _parse_optional_int(warehouse_id)
    if warehouse_id not in (None, ""):
        if parsed_warehouse_id is None:
            warnings.append("invalid_warehouse_id_filter")
        else:
            where_clauses.append("t.warehouse_id = %s")
            params.append(parsed_warehouse_id)

    parsed_item_id = _parse_optional_int(item_id)
    if item_id not in (None, ""):
        if parsed_item_id is None:
            warnings.append("invalid_item_id_filter")
        else:
            where_clauses.append("t.item_id = %s")
            params.append(parsed_item_id)

    parsed_batch_id = _parse_optional_int(batch_id)
    if batch_id not in (None, ""):
        if parsed_batch_id is None:
            warnings.append("invalid_batch_id_filter")
        else:
            where_clauses.append("t.batch_id = %s")
            params.append(parsed_batch_id)

    where_sql = ""
    if where_clauses:
        where_sql = "WHERE " + " AND ".join(where_clauses)

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT COUNT(*) FROM {schema}.uom_repackaging_txn t {where_sql}",
                params,
            )
            total = int(cursor.fetchone()[0] or 0)
            cursor.execute(
                f"""
                SELECT
                    t.repackaging_id,
                    t.warehouse_id,
                    w.warehouse_name,
                    t.item_id,
                    i.item_code,
                    i.item_name,
                    t.batch_id,
                    t.batch_no_snapshot,
                    t.expiry_date_snapshot,
                    t.source_uom_code,
                    t.source_qty,
                    t.target_uom_code,
                    t.target_qty,
                    t.equivalent_default_qty,
                    t.reason_code,
                    t.note_text,
                    t.create_by_id,
                    t.create_dtime
                FROM {schema}.uom_repackaging_txn t
                JOIN {schema}.warehouse w
                  ON w.warehouse_id = t.warehouse_id
                JOIN {schema}.item i
                  ON i.item_id = t.item_id
                {where_sql}
                ORDER BY t.create_dtime DESC, t.repackaging_id DESC
                LIMIT %s OFFSET %s
                """,
                params + [limit, offset],
            )
            rows = [_row_to_repackaging_list_dict(row) for row in cursor.fetchall()]
        return rows, total, warnings
    except DatabaseError as exc:
        logger.warning("list_repackaging_transactions failed: %s", exc)
        _safe_rollback()
        return [], 0, ["db_error"]


def get_repackaging_transaction(
    repackaging_id: Any,
    *,
    raise_on_error: bool = False,
) -> tuple[dict[str, Any] | None, list[str]]:
    if _is_sqlite():
        return None, ["db_unavailable"]

    schema = _schema_name()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT
                    t.repackaging_id,
                    t.warehouse_id,
                    w.warehouse_name,
                    t.item_id,
                    i.item_code,
                    i.item_name,
                    t.batch_id,
                    t.batch_no_snapshot,
                    t.expiry_date_snapshot,
                    t.source_uom_code,
                    t.source_qty,
                    t.target_uom_code,
                    t.target_qty,
                    t.equivalent_default_qty,
                    t.source_conversion_factor,
                    t.target_conversion_factor,
                    t.reason_code,
                    t.note_text,
                    t.create_by_id,
                    t.create_dtime
                FROM {schema}.uom_repackaging_txn t
                JOIN {schema}.warehouse w
                  ON w.warehouse_id = t.warehouse_id
                JOIN {schema}.item i
                  ON i.item_id = t.item_id
                WHERE t.repackaging_id = %s
                LIMIT 1
                """,
                [repackaging_id],
            )
            row = cursor.fetchone()
            if not row:
                return None, []

            record = {
                "repackaging_id": row[0],
                "warehouse_id": row[1],
                "warehouse_name": row[2],
                "item_id": row[3],
                "item_code": row[4],
                "item_name": row[5],
                "batch_id": row[6],
                "batch_or_lot": row[7] or row[6],
                "expiry_date": row[8],
                "source_uom_code": row[9],
                "source_qty": row[10],
                "target_uom_code": row[11],
                "target_qty": row[12],
                "equivalent_default_qty": row[13],
                "source_conversion_factor": row[14],
                "target_conversion_factor": row[15],
                "reason_code": row[16],
                "note_text": row[17],
                "audit_metadata": {
                    "created_by_id": row[18],
                    "created_at": row[19],
                },
            }
            record["audit_rows"] = _load_repackaging_audit_rows(cursor, schema, repackaging_id)
            record["audit_metadata"]["audit_row_count"] = len(record["audit_rows"])
        return record, []
    except DatabaseError as exc:
        _safe_rollback()
        if raise_on_error:
            raise
        logger.warning("get_repackaging_transaction(%s) failed: %s", repackaging_id, exc)
        return None, ["db_error"]


def _load_repackaging_context(
    *,
    schema: str,
    warehouse_id: int,
    item_id: int,
    source_uom_code: str,
    target_uom_code: str,
    batch_id: int | None,
    batch_or_lot: str,
) -> dict[str, Any]:
    warehouse_row = _fetch_warehouse(schema, warehouse_id)
    if warehouse_row is None:
        raise RepackagingError("warehouse_not_found", f"Warehouse {warehouse_id} was not found.", status_code=404)
    if str(warehouse_row.get("status_code") or "").upper() != "A":
        raise RepackagingError("warehouse_inactive", f"Warehouse {warehouse_id} is inactive.", status_code=409)

    item_row = _fetch_item(schema, item_id)
    if item_row is None:
        raise RepackagingError("item_not_found", f"Item {item_id} was not found.", status_code=404)
    if str(item_row.get("status_code") or "").upper() != "A":
        raise RepackagingError("item_inactive", f"Item {item_id} is inactive.", status_code=409)

    source_conversion_factor, target_conversion_factor = _fetch_uom_conversion_pair(
        schema=schema,
        item_row=item_row,
        item_id=item_id,
        source_uom_code=source_uom_code,
        target_uom_code=target_uom_code,
    )

    requires_batch_context = bool(item_row["is_batched_flag"] or item_row["can_expire_flag"])
    if requires_batch_context and batch_id is None and not batch_or_lot:
        raise RepackagingError(
            "batch_context_required",
            "batch_id or batch_or_lot is required for batched or expiring items.",
            status_code=400,
        )
    if not requires_batch_context and (batch_id is not None or batch_or_lot):
        raise RepackagingError(
            "batch_context_not_allowed",
            "batch_id or batch_or_lot is not allowed for non-batched items.",
            status_code=400,
        )

    batch_context: dict[str, Any] | None = None
    if requires_batch_context:
        batch_context = _fetch_batch_context(
            schema=schema,
            warehouse_id=warehouse_id,
            item_id=item_id,
            batch_id=batch_id,
            batch_or_lot=batch_or_lot,
            default_uom_code=item_row["default_uom_code"],
        )
        if batch_context is None:
            raise RepackagingError(
                "batch_not_found",
                "The requested batch or lot context was not found for this warehouse and item.",
                status_code=404,
            )
        available_default_qty = batch_context["available_default_qty"]
    else:
        inventory_context = _fetch_inventory_context(schema, warehouse_id=warehouse_id, item_id=item_id)
        if inventory_context is None:
            raise RepackagingError(
                "inventory_not_found",
                "No inventory record exists for this warehouse and item.",
                status_code=404,
            )
        available_default_qty = inventory_context["available_default_qty"]

    return {
        "warehouse_name": warehouse_row["warehouse_name"],
        "item_code": item_row["item_code"],
        "item_name": item_row["item_name"],
        "batch_id": batch_context["batch_id"] if batch_context else None,
        "batch_no_snapshot": batch_context["batch_no_snapshot"] if batch_context else "",
        "expiry_date_snapshot": batch_context["expiry_date_snapshot"] if batch_context else None,
        "source_conversion_factor": source_conversion_factor,
        "target_conversion_factor": target_conversion_factor,
        "available_default_qty": available_default_qty,
    }


def _compute_repackaging_quantities(
    *,
    source_qty: Decimal,
    source_conversion_factor: Decimal,
    target_conversion_factor: Decimal,
) -> RepackagingComputation:
    equivalent_default_qty = _quantize_qty(source_qty * source_conversion_factor)
    with localcontext() as ctx:
        ctx.prec = 28
        target_qty = _quantize_qty(equivalent_default_qty / target_conversion_factor)

    if _quantize_qty(target_qty * target_conversion_factor) != equivalent_default_qty:
        raise RepackagingError(
            "quantity_conservation_violation",
            "The requested UOM conversion does not preserve quantity exactly.",
            status_code=409,
        )

    return RepackagingComputation(
        source_qty=_quantize_qty(source_qty),
        target_qty=target_qty,
        equivalent_default_qty=equivalent_default_qty,
        source_conversion_factor=_quantize_qty(source_conversion_factor),
        target_conversion_factor=_quantize_qty(target_conversion_factor),
    )


def _fetch_warehouse(schema: str, warehouse_id: int) -> dict[str, Any] | None:
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT warehouse_id, warehouse_name, status_code
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
        "status_code": str(row[2] or ""),
    }


def _fetch_item(schema: str, item_id: int) -> dict[str, Any] | None:
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT
                item_id,
                item_code,
                item_name,
                default_uom_code,
                is_batched_flag,
                can_expire_flag,
                status_code
            FROM {schema}.item
            WHERE item_id = %s
            LIMIT 1
            """,
            [item_id],
        )
        row = cursor.fetchone()
    if not row:
        return None
    return {
        "item_id": int(row[0]),
        "item_code": str(row[1] or ""),
        "item_name": str(row[2] or ""),
        "default_uom_code": str(row[3] or "").upper(),
        "is_batched_flag": bool(row[4]),
        "can_expire_flag": bool(row[5]),
        "status_code": str(row[6] or ""),
    }


def _fetch_inventory_context(
    schema: str,
    *,
    warehouse_id: int,
    item_id: int,
) -> dict[str, Any] | None:
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT usable_qty, reserved_qty
            FROM {schema}.inventory
            WHERE inventory_id = %s
              AND item_id = %s
              AND status_code = 'A'
            LIMIT 1
            """,
            [warehouse_id, item_id],
        )
        row = cursor.fetchone()
    if not row:
        return None
    usable_qty = Decimal(str(row[0] or 0))
    reserved_qty = Decimal(str(row[1] or 0))
    return {"available_default_qty": usable_qty - reserved_qty}


def _fetch_batch_context(
    *,
    schema: str,
    warehouse_id: int,
    item_id: int,
    batch_id: int | None,
    batch_or_lot: str,
    default_uom_code: str,
) -> dict[str, Any] | None:
    where_clauses = [
        "inventory_id = %s",
        "item_id = %s",
        "status_code = 'A'",
    ]
    params: list[Any] = [warehouse_id, item_id]
    if batch_id is not None:
        where_clauses.append("batch_id = %s")
        params.append(batch_id)
    else:
        where_clauses.append("UPPER(COALESCE(batch_no, '')) = %s")
        params.append(str(batch_or_lot or "").strip().upper())

    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT batch_id, batch_no, expiry_date, usable_qty, reserved_qty, uom_code
            FROM {schema}.itembatch
            WHERE {" AND ".join(where_clauses)}
            LIMIT 1
            """,
            params,
        )
        row = cursor.fetchone()
    if not row:
        return None
    usable_qty = Decimal(str(row[3] or 0))
    reserved_qty = Decimal(str(row[4] or 0))
    batch_uom_code = str(row[5] or "").strip().upper()
    batch_conversion_factor = _fetch_single_uom_conversion_factor(
        schema=schema,
        item_id=item_id,
        uom_code=batch_uom_code,
        default_uom_code=default_uom_code,
    )
    return {
        "batch_id": int(row[0]),
        "batch_no_snapshot": str(row[1] or ""),
        "expiry_date_snapshot": row[2],
        "available_default_qty": _quantize_qty(
            (usable_qty - reserved_qty) * batch_conversion_factor
        ),
    }


def _fetch_single_uom_conversion_factor(
    *,
    schema: str,
    item_id: int,
    uom_code: str,
    default_uom_code: str,
) -> Decimal:
    normalized_uom_code = str(uom_code or "").strip().upper()
    normalized_default_uom = str(default_uom_code or "").strip().upper()
    if normalized_uom_code and normalized_uom_code == normalized_default_uom:
        return Decimal("1")

    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT conversion_factor
            FROM {schema}.item_uom_option
            WHERE item_id = %s
              AND status_code = 'A'
              AND uom_code = %s
            LIMIT 1
            """,
            [item_id, normalized_uom_code],
        )
        row = cursor.fetchone()

    if row and row[0] is not None:
        return Decimal(str(row[0]))

    raise RepackagingError(
        "invalid_uom_mapping",
        "Source and target UOMs must both be active for the selected item.",
        status_code=409,
        payload={"code": "invalid_uom_mapping", "missing_uom_codes": [normalized_uom_code]},
    )


def _fetch_uom_conversion_pair(
    *,
    schema: str,
    item_row: dict[str, Any],
    item_id: int,
    source_uom_code: str,
    target_uom_code: str,
) -> tuple[Decimal, Decimal]:
    requested_uoms = sorted({source_uom_code, target_uom_code})
    placeholders = ", ".join(["%s"] * len(requested_uoms))
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT uom_code, conversion_factor
            FROM {schema}.item_uom_option
            WHERE item_id = %s
              AND status_code = 'A'
              AND uom_code IN ({placeholders})
            """,
            [item_id] + requested_uoms,
        )
        rows = cursor.fetchall()

    conversion_by_uom = {
        str(uom_code or "").upper(): Decimal(str(conversion_factor))
        for uom_code, conversion_factor in rows
    }
    default_uom_code = str(item_row.get("default_uom_code") or "").upper()
    if default_uom_code and default_uom_code not in conversion_by_uom:
        conversion_by_uom[default_uom_code] = Decimal("1")

    missing = [
        uom_code
        for uom_code in (source_uom_code, target_uom_code)
        if uom_code not in conversion_by_uom
    ]
    if missing:
        raise RepackagingError(
            "invalid_uom_mapping",
            "Source and target UOMs must both be active for the selected item.",
            status_code=409,
            payload={"code": "invalid_uom_mapping", "missing_uom_codes": missing},
        )

    return conversion_by_uom[source_uom_code], conversion_by_uom[target_uom_code]


def _insert_repackaging_txn(
    *,
    schema: str,
    warehouse_id: int,
    item_id: int,
    batch_id: int | None,
    batch_no_snapshot: str,
    expiry_date_snapshot: date | None,
    source_uom_code: str,
    target_uom_code: str,
    reason_code: str,
    note_text: str,
    computation: RepackagingComputation,
    actor_id: str,
) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            INSERT INTO {schema}.uom_repackaging_txn (
                warehouse_id,
                item_id,
                batch_id,
                batch_no_snapshot,
                expiry_date_snapshot,
                source_uom_code,
                target_uom_code,
                source_qty,
                target_qty,
                equivalent_default_qty,
                source_conversion_factor,
                target_conversion_factor,
                reason_code,
                note_text,
                create_by_id,
                create_dtime,
                update_by_id,
                update_dtime,
                version_nbr
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s, NOW(), 1
            )
            RETURNING repackaging_id
            """,
            [
                warehouse_id,
                item_id,
                batch_id,
                batch_no_snapshot or None,
                expiry_date_snapshot,
                source_uom_code,
                target_uom_code,
                computation.source_qty,
                computation.target_qty,
                computation.equivalent_default_qty,
                computation.source_conversion_factor,
                computation.target_conversion_factor,
                reason_code,
                note_text or None,
                actor_id,
                actor_id,
            ],
        )
        row = cursor.fetchone()
    if not row or row[0] is None:
        raise RepackagingError(
            "repackaging_insert_failed",
            "Failed to create the repackaging transaction.",
            status_code=500,
        )
    return int(row[0])


def _insert_repackaging_audit(
    *,
    schema: str,
    repackaging_id: int,
    action_type: str,
    before_state: dict[str, Any] | None,
    after_state: dict[str, Any],
    reason_code: str,
    note_text: str,
    actor_id: str,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            INSERT INTO {schema}.uom_repackaging_audit (
                repackaging_id,
                action_type,
                before_state_json,
                after_state_json,
                reason_code,
                note_text,
                actor_id,
                action_dtime
            )
            VALUES (%s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, NOW())
            """,
            [
                repackaging_id,
                action_type,
                None if before_state is None else json.dumps(_to_jsonable(before_state)),
                json.dumps(_to_jsonable(after_state)),
                reason_code,
                note_text or None,
                actor_id,
            ],
        )


def _load_repackaging_audit_rows(cursor, schema: str, repackaging_id: Any) -> list[dict[str, Any]]:
    cursor.execute(
        f"""
        SELECT
            repackaging_audit_id,
            action_type,
            before_state_json,
            after_state_json,
            reason_code,
            note_text,
            actor_id,
            action_dtime
        FROM {schema}.uom_repackaging_audit
        WHERE repackaging_id = %s
        ORDER BY action_dtime ASC, repackaging_audit_id ASC
        """,
        [repackaging_id],
    )
    return [
        {
            "repackaging_audit_id": row[0],
            "action_type": row[1],
            "before_state": row[2],
            "after_state": row[3],
            "reason_code": row[4],
            "note_text": row[5],
            "actor_id": row[6],
            "action_dtime": row[7],
        }
        for row in cursor.fetchall()
    ]


def _row_to_repackaging_list_dict(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "repackaging_id": row[0],
        "warehouse_id": row[1],
        "warehouse_name": row[2],
        "item_id": row[3],
        "item_code": row[4],
        "item_name": row[5],
        "batch_id": row[6],
        "batch_or_lot": row[7] or row[6],
        "expiry_date": row[8],
        "source_uom_code": row[9],
        "source_qty": row[10],
        "target_uom_code": row[11],
        "target_qty": row[12],
        "equivalent_default_qty": row[13],
        "reason_code": row[14],
        "note_text": row[15],
        "audit_metadata": {
            "created_by_id": row[16],
            "created_at": row[17],
        },
    }


def _normalize_positive_decimal(value: Any, *, field_name: str) -> Decimal:
    try:
        normalized = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise RepackagingError(
            f"{field_name}_invalid",
            f"{field_name} must be a numeric value.",
        ) from exc
    if not normalized.is_finite():
        raise RepackagingError(
            f"{field_name}_invalid",
            f"{field_name} must be a finite numeric value.",
        )
    if normalized <= 0:
        raise RepackagingError(
            f"{field_name}_invalid",
            f"{field_name} must be greater than zero.",
        )
    return normalized


def _quantize_qty(value: Any) -> Decimal:
    normalized = Decimal(str(value))
    if not normalized.is_finite():
        raise InvalidOperation("quantity must be finite")
    return normalized.quantize(_QTY_SCALE)


def _parse_optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_rollback() -> None:
    try:
        connection.rollback()
    except Exception:
        logger.debug(
            "Rollback failed while handling a repackaging error.",
            exc_info=True,
        )


def _to_jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _to_jsonable(item) for key, item in value.items()}
    return value
