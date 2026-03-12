from __future__ import annotations

import json
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from django.db import DatabaseError, connection, transaction

from masterdata.services.data_access import (
    TABLE_REGISTRY,
    _is_sqlite,
    _parse_sort_expression,
    _safe_rollback,
    _schema_name,
    create_record,
    update_record,
)

logger = logging.getLogger(__name__)

ITEM_LIST_SELECT = """
    i.item_id,
    i.item_code,
    i.legacy_item_code,
    i.item_name,
    i.sku_code,
    i.category_id,
    i.item_desc,
    i.reorder_qty,
    i.default_uom_code,
    u.uom_desc AS default_uom_desc,
    i.units_size_vary_flag,
    i.usage_desc,
    i.storage_desc,
    i.is_batched_flag,
    i.can_expire_flag,
    i.issuance_order,
    i.baseline_burn_rate,
    i.min_stock_threshold,
    i.criticality_level,
    i.comments_text,
    i.status_code,
    i.ifrc_family_id,
    i.ifrc_item_ref_id,
    c.category_code,
    c.category_desc,
    f.group_code AS ifrc_group_code,
    f.group_label AS ifrc_group_label,
    f.family_code AS ifrc_family_code,
    f.family_label AS ifrc_family_label,
    r.ifrc_code AS ifrc_reference_code,
    r.reference_desc AS ifrc_reference_desc,
    r.category_code AS ifrc_reference_category_code,
    r.category_label AS ifrc_reference_category_label,
    r.spec_segment AS ifrc_reference_spec_segment,
    r.size_weight AS ifrc_reference_size_weight,
    r.form AS ifrc_reference_form,
    r.material AS ifrc_reference_material,
    i.create_by_id,
    i.create_dtime,
    i.update_by_id,
    i.update_dtime,
    i.version_nbr
"""

ITEM_LIST_COLUMN_NAMES = [
    "item_id",
    "item_code",
    "legacy_item_code",
    "item_name",
    "sku_code",
    "category_id",
    "item_desc",
    "reorder_qty",
    "default_uom_code",
    "default_uom_desc",
    "units_size_vary_flag",
    "usage_desc",
    "storage_desc",
    "is_batched_flag",
    "can_expire_flag",
    "issuance_order",
    "baseline_burn_rate",
    "min_stock_threshold",
    "criticality_level",
    "comments_text",
    "status_code",
    "ifrc_family_id",
    "ifrc_item_ref_id",
    "category_code",
    "category_desc",
    "ifrc_group_code",
    "ifrc_group_label",
    "ifrc_family_code",
    "ifrc_family_label",
    "ifrc_reference_code",
    "ifrc_reference_desc",
    "ifrc_reference_category_code",
    "ifrc_reference_category_label",
    "ifrc_reference_spec_segment",
    "ifrc_reference_size_weight",
    "ifrc_reference_form",
    "ifrc_reference_material",
    "create_by_id",
    "create_dtime",
    "update_by_id",
    "update_dtime",
    "version_nbr",
]

ITEM_CANONICAL_CONFLICT_CODE = "duplicate_canonical_item_code"

ITEM_AUDIT_STATE_FIELDS = [
    "identity",
    "category",
    "ifrc_family",
    "ifrc_item_reference",
    "uom_options",
    "batch_expiry",
    "status_code",
]


def list_item_records(
    *,
    status_filter: str | None = None,
    search: str | None = None,
    order_by: str | None = None,
    category_id: Any | None = None,
    ifrc_family_id: Any | None = None,
    ifrc_item_ref_id: Any | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int, list[str]]:
    if _is_sqlite():
        return [], 0, ["db_unavailable"]

    schema = _schema_name()
    warnings: list[str] = []
    where_clauses: list[str] = []
    params: list[Any] = []

    if status_filter:
        where_clauses.append("i.status_code = %s")
        params.append(status_filter)
    if category_id not in (None, ""):
        where_clauses.append("i.category_id = %s")
        params.append(category_id)
    if ifrc_family_id not in (None, ""):
        where_clauses.append("i.ifrc_family_id = %s")
        params.append(ifrc_family_id)
    if ifrc_item_ref_id not in (None, ""):
        where_clauses.append("i.ifrc_item_ref_id = %s")
        params.append(ifrc_item_ref_id)

    if search:
        token = f"%{str(search).upper()}%"
        where_clauses.append(
            "("
            "UPPER(i.item_code) LIKE %s OR "
            "UPPER(COALESCE(i.legacy_item_code, '')) LIKE %s OR "
            "UPPER(i.item_name) LIKE %s OR "
            "UPPER(COALESCE(i.sku_code, '')) LIKE %s OR "
            "UPPER(CAST(i.item_desc AS TEXT)) LIKE %s OR "
            "UPPER(COALESCE(c.category_desc, '')) LIKE %s OR "
            "UPPER(COALESCE(f.family_label, '')) LIKE %s OR "
            "UPPER(COALESCE(r.reference_desc, '')) LIKE %s OR "
            "UPPER(COALESCE(r.ifrc_code, '')) LIKE %s"
            ")"
        )
        params.extend([token] * 9)

    where_sql = ""
    if where_clauses:
        where_sql = "WHERE " + " AND ".join(where_clauses)

    order_sql = _resolve_item_order_by(order_by, warnings)

    sql_from = f"""
        FROM {schema}.item i
        LEFT JOIN {schema}.itemcatg c
            ON c.category_id = i.category_id
        LEFT JOIN {schema}.ifrc_family f
            ON f.ifrc_family_id = i.ifrc_family_id
        LEFT JOIN {schema}.ifrc_item_reference r
            ON r.ifrc_item_ref_id = i.ifrc_item_ref_id
        LEFT JOIN {schema}.unitofmeasure u
            ON u.uom_code = i.default_uom_code
    """

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT COUNT(*) {sql_from} {where_sql}",
                list(params),
            )
            total = int(cursor.fetchone()[0] or 0)
            cursor.execute(
                f"""
                SELECT {ITEM_LIST_SELECT}
                {sql_from}
                {where_sql}
                ORDER BY {order_sql}
                LIMIT %s OFFSET %s
                """,
                params + [limit, offset],
            )
            rows = [
                dict(zip(ITEM_LIST_COLUMN_NAMES, row))
                for row in cursor.fetchall()
            ]
        return rows, total, warnings
    except DatabaseError as exc:
        logger.warning("list_item_records failed: %s", exc)
        _safe_rollback()
        return [], 0, ["db_error"]


def get_item_record(item_id: Any) -> tuple[dict[str, Any] | None, list[str]]:
    if _is_sqlite():
        return None, ["db_unavailable"]

    schema = _schema_name()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {ITEM_LIST_SELECT}
                FROM {schema}.item i
                LEFT JOIN {schema}.itemcatg c
                    ON c.category_id = i.category_id
                LEFT JOIN {schema}.ifrc_family f
                    ON f.ifrc_family_id = i.ifrc_family_id
                LEFT JOIN {schema}.ifrc_item_reference r
                    ON r.ifrc_item_ref_id = i.ifrc_item_ref_id
                LEFT JOIN {schema}.unitofmeasure u
                    ON u.uom_code = i.default_uom_code
                WHERE i.item_id = %s
                """,
                [item_id],
            )
            row = cursor.fetchone()
            if not row:
                return None, []
            record = dict(zip(ITEM_LIST_COLUMN_NAMES, row))
            record["uom_options"] = _load_item_uom_options(cursor, schema, item_id)
            return record, []
    except DatabaseError as exc:
        logger.warning("get_item_record(%s) failed: %s", item_id, exc)
        _safe_rollback()
        return None, ["db_error"]


def list_item_category_lookup(
    *,
    active_only: bool = True,
    include_value: Any | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    if _is_sqlite():
        return [], ["db_unavailable"]

    schema = _schema_name()
    where_sql = ""
    params: list[Any] = []
    if active_only:
        if include_value not in (None, ""):
            where_sql = "WHERE c.status_code = 'A' OR c.category_id = %s"
            params.append(include_value)
        else:
            where_sql = "WHERE c.status_code = 'A'"

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT c.category_id, c.category_desc, c.category_code, c.status_code
                FROM {schema}.itemcatg c
                {where_sql}
                ORDER BY
                    CASE WHEN c.status_code = 'A' THEN 0 ELSE 1 END,
                    c.category_desc
                """,
                params,
            )
            return [
                {
                    "value": row[0],
                    "label": row[1],
                    "category_code": row[2],
                    "status_code": row[3],
                }
                for row in cursor.fetchall()
            ], []
    except DatabaseError as exc:
        logger.warning("list_item_category_lookup failed: %s", exc)
        _safe_rollback()
        return [], ["db_error"]


def list_ifrc_family_lookup(
    *,
    category_id: Any | None = None,
    search: str | None = None,
    active_only: bool = True,
) -> tuple[list[dict[str, Any]], list[str]]:
    if _is_sqlite():
        return [], ["db_unavailable"]

    schema = _schema_name()
    where_clauses: list[str] = []
    params: list[Any] = []
    if category_id not in (None, ""):
        where_clauses.append("f.category_id = %s")
        params.append(category_id)
    if active_only:
        where_clauses.append("f.status_code = 'A'")
    if search:
        where_clauses.append(
            "(UPPER(f.family_label) LIKE %s OR UPPER(f.family_code) LIKE %s OR UPPER(f.group_label) LIKE %s)"
        )
        token = f"%{str(search).upper()}%"
        params.extend([token, token, token])

    where_sql = ""
    if where_clauses:
        where_sql = "WHERE " + " AND ".join(where_clauses)

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT
                    f.ifrc_family_id,
                    f.family_label,
                    f.family_code,
                    f.group_code,
                    f.group_label,
                    f.category_id,
                    c.category_code,
                    c.category_desc
                FROM {schema}.ifrc_family f
                JOIN {schema}.itemcatg c
                    ON c.category_id = f.category_id
                {where_sql}
                ORDER BY c.category_desc, f.family_label
                """,
                params,
            )
            return [
                {
                    "value": row[0],
                    "label": row[1],
                    "family_code": row[2],
                    "group_code": row[3],
                    "group_label": row[4],
                    "category_id": row[5],
                    "category_code": row[6],
                    "category_desc": row[7],
                }
                for row in cursor.fetchall()
            ], []
    except DatabaseError as exc:
        logger.warning("list_ifrc_family_lookup failed: %s", exc)
        _safe_rollback()
        return [], ["db_error"]


def list_ifrc_reference_lookup(
    *,
    ifrc_family_id: Any | None = None,
    search: str | None = None,
    active_only: bool = True,
    limit: int = 100,
) -> tuple[list[dict[str, Any]], list[str]]:
    if _is_sqlite():
        return [], ["db_unavailable"]

    schema = _schema_name()
    where_clauses: list[str] = []
    params: list[Any] = []
    if ifrc_family_id not in (None, ""):
        where_clauses.append("r.ifrc_family_id = %s")
        params.append(ifrc_family_id)
    if active_only:
        where_clauses.append("r.status_code = 'A'")
    if search:
        where_clauses.append(
            "(" 
            "UPPER(r.reference_desc) LIKE %s OR "
            "UPPER(r.ifrc_code) LIKE %s OR "
            "UPPER(r.category_label) LIKE %s OR "
            "UPPER(COALESCE(r.size_weight, '')) LIKE %s OR "
            "UPPER(COALESCE(r.form, '')) LIKE %s OR "
            "UPPER(COALESCE(r.material, '')) LIKE %s"
            ")"
        )
        token = f"%{str(search).upper()}%"
        params.extend([token, token, token, token, token, token])

    where_sql = ""
    if where_clauses:
        where_sql = "WHERE " + " AND ".join(where_clauses)

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT
                    r.ifrc_item_ref_id,
                    r.reference_desc,
                    r.ifrc_code,
                    r.ifrc_family_id,
                    f.family_code,
                    f.family_label,
                    r.category_code,
                    r.category_label,
                    r.spec_segment,
                    r.size_weight,
                    r.form,
                    r.material
                FROM {schema}.ifrc_item_reference r
                JOIN {schema}.ifrc_family f
                    ON f.ifrc_family_id = r.ifrc_family_id
                {where_sql}
                ORDER BY r.reference_desc, r.ifrc_code
                LIMIT %s
                """,
                params + [limit],
            )
            return [
                {
                    "value": row[0],
                    "label": row[1],
                    "ifrc_code": row[2],
                    "ifrc_family_id": row[3],
                    "family_code": row[4],
                    "family_label": row[5],
                    "category_code": row[6],
                    "category_label": row[7],
                    "spec_segment": row[8],
                    "size_weight": row[9],
                    "form": row[10],
                    "material": row[11],
                }
                for row in cursor.fetchall()
            ], []
    except DatabaseError as exc:
        logger.warning("list_ifrc_reference_lookup failed: %s", exc)
        _safe_rollback()
        return [], ["db_error"]


def validate_item_payload(
    data: dict[str, Any],
    *,
    is_update: bool,
    existing_record: dict[str, Any] | None = None,
) -> tuple[dict[str, str], list[str]]:
    def parse_numeric_identifier(value: Any, field_name: str) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            errors[field_name] = "Invalid numeric ID."
            return None

    errors: dict[str, str] = {}
    warnings: list[str] = []

    if _is_sqlite():
        return errors, warnings

    schema = _schema_name()
    category_id = _merged_value(data, existing_record, "category_id")
    family_id = _merged_value(data, existing_record, "ifrc_family_id")
    reference_id = _merged_value(data, existing_record, "ifrc_item_ref_id")
    parsed_category_id = parse_numeric_identifier(category_id, "category_id")
    parsed_family_id = parse_numeric_identifier(family_id, "ifrc_family_id")
    default_uom_code = str(
        _merged_value(data, existing_record, "default_uom_code") or ""
    ).strip().upper()

    normalized_uom_options, option_errors = _normalize_item_uom_options(
        data.get("uom_options"),
        default_uom_code=default_uom_code,
    )
    errors.update(option_errors)
    if option_errors:
        return errors, warnings

    try:
        family_row = (
            _fetch_ifrc_family(schema, parsed_family_id)
            if parsed_family_id is not None
            else None
        )
        reference_row = (
            _fetch_ifrc_reference(schema, reference_id)
            if reference_id not in (None, "")
            else None
        )
        if normalized_uom_options is not None:
            missing_uoms = _missing_uom_codes(
                schema,
                [row["uom_code"] for row in normalized_uom_options],
            )
            if missing_uoms:
                errors["uom_options"] = (
                    "Unknown unit(s) of measure: " + ", ".join(sorted(missing_uoms))
                )
    except DatabaseError as exc:
        logger.warning("validate_item_payload failed: %s", exc)
        _safe_rollback()
        warnings.append("item_taxonomy_validation_failed")
        return errors, warnings

    existing_family_id = existing_record.get("ifrc_family_id") if existing_record else None
    existing_reference_id = existing_record.get("ifrc_item_ref_id") if existing_record else None
    family_selection_changed = not _same_identifier(existing_family_id, family_id)
    reference_selection_changed = not _same_identifier(existing_reference_id, reference_id)

    if not is_update:
        if family_id in (None, ""):
            errors["ifrc_family_id"] = "IFRC Family is required for new items."
        if reference_id in (None, ""):
            errors["ifrc_item_ref_id"] = "IFRC Item Reference is required for new items."
    elif existing_reference_id not in (None, ""):
        if family_id in (None, ""):
            errors["ifrc_family_id"] = "Mapped items must retain an IFRC Family."
        if reference_id in (None, ""):
            errors["ifrc_item_ref_id"] = "Mapped items must retain an IFRC Item Reference."
    elif family_id not in (None, "") and reference_id in (None, "") and (
        "ifrc_family_id" in data or "ifrc_item_ref_id" in data
    ):
        errors["ifrc_item_ref_id"] = "IFRC Item Reference is required when selecting an IFRC Family."

    if family_id not in (None, "") and parsed_family_id is not None and family_row is None:
        errors["ifrc_family_id"] = "Selected IFRC Family does not exist."
    if reference_id not in (None, "") and reference_row is None:
        errors["ifrc_item_ref_id"] = "Selected IFRC Item Reference does not exist."

    if family_row and str(family_row.get("status_code") or "").upper() != "A":
        if not is_update or family_selection_changed or existing_family_id in (None, ""):
            errors["ifrc_family_id"] = "Selected IFRC Family is inactive."

    if reference_row and str(reference_row.get("status_code") or "").upper() != "A":
        if not is_update or reference_selection_changed or existing_reference_id in (None, ""):
            errors["ifrc_item_ref_id"] = "Selected IFRC Item Reference is inactive."

    if family_row and parsed_category_id is not None:
        if int(family_row["category_id"]) != parsed_category_id:
            errors["ifrc_family_id"] = (
                "Selected IFRC Family does not belong to the chosen Level 1 category."
            )

    if reference_row:
        if family_id in (None, ""):
            errors["ifrc_family_id"] = (
                "IFRC Family is required when selecting an IFRC Item Reference."
            )
        elif parsed_family_id is not None and int(reference_row["ifrc_family_id"]) != parsed_family_id:
            errors["ifrc_item_ref_id"] = (
                "Selected IFRC Item Reference does not belong to the chosen IFRC Family."
            )

    return errors, warnings


def create_item_record(
    data: dict[str, Any],
    actor_id: str,
) -> tuple[Any | None, list[str]]:
    if _is_sqlite():
        return None, ["db_unavailable"]

    schema = _schema_name()
    base_data, _ = _build_item_write_payload(data, is_update=False)
    default_uom_code = str(base_data.get("default_uom_code") or "").strip().upper()
    normalized_uom_options, _ = _normalize_item_uom_options(
        data.get("uom_options"),
        default_uom_code=default_uom_code,
    )

    try:
        with transaction.atomic():
            item_id, warnings = create_record("items", base_data, actor_id)
            if item_id is None:
                return None, warnings

            if normalized_uom_options is not None:
                _replace_item_uom_options(
                    schema,
                    item_id,
                    normalized_uom_options,
                    actor_id,
                )
            else:
                _ensure_default_item_uom_option(
                    schema,
                    item_id,
                    default_uom_code,
                    actor_id,
                )

            record, record_warnings = get_item_record(item_id)
            warnings.extend(record_warnings)
            if record is None:
                return None, warnings or ["db_error"]

            _write_item_classification_audit(
                schema,
                item_id=item_id,
                change_action="CREATE",
                before_state=None,
                after_state=_tracked_item_state(record),
                changed_by_id=actor_id,
            )
            return item_id, warnings
    except DatabaseError as exc:
        logger.warning("create_item_record failed: %s", exc)
        _safe_rollback()
        return None, ["db_error"]


def update_item_record(
    item_id: Any,
    data: dict[str, Any],
    actor_id: str,
    expected_version: int | None = None,
) -> tuple[bool, list[str]]:
    if _is_sqlite():
        return False, ["db_unavailable"]

    schema = _schema_name()
    try:
        with transaction.atomic():
            before_record, before_warnings = get_item_record(item_id)
            if before_record is None:
                return False, before_warnings or ["not_found"]

            before_state = _tracked_item_state(before_record)
            base_data, _ = _build_item_write_payload(
                data,
                is_update=True,
                existing_record=before_record,
            )
            success, warnings = update_record(
                "items",
                item_id,
                base_data,
                actor_id,
                expected_version,
            )
            if not success:
                return False, warnings

            default_uom_code = str(
                base_data.get("default_uom_code")
                or before_record.get("default_uom_code")
                or ""
            ).strip().upper()
            normalized_uom_options, _ = _normalize_item_uom_options(
                data.get("uom_options"),
                default_uom_code=default_uom_code,
            )
            if data.get("uom_options") is not None:
                _replace_item_uom_options(
                    schema,
                    item_id,
                    normalized_uom_options or [],
                    actor_id,
                )
            elif default_uom_code:
                _ensure_default_item_uom_option(
                    schema,
                    item_id,
                    default_uom_code,
                    actor_id,
                )

            after_record, after_warnings = get_item_record(item_id)
            warnings.extend(before_warnings)
            warnings.extend(after_warnings)
            if after_record is None:
                return False, warnings or ["db_error"]

            after_state = _tracked_item_state(after_record)
            if before_state != after_state:
                action = _audit_action_from_status_change(before_record, after_record)
                _write_item_classification_audit(
                    schema,
                    item_id=item_id,
                    change_action=action,
                    before_state=before_state,
                    after_state=after_state,
                    changed_by_id=actor_id,
                )

            return True, warnings
    except DatabaseError as exc:
        logger.warning("update_item_record(%s) failed: %s", item_id, exc)
        _safe_rollback()
        return False, ["db_error"]


def find_item_canonical_conflict(
    data: dict[str, Any],
    *,
    existing_record: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if _is_sqlite():
        return None

    schema = _schema_name()
    merged_reference_id = _merged_value(data, existing_record, "ifrc_item_ref_id")
    if merged_reference_id in (None, ""):
        return None

    reference_row = _fetch_ifrc_reference(schema, merged_reference_id)
    if reference_row is None:
        return None

    exclude_item_id = existing_record.get("item_id") if existing_record else None
    canonical_code = _normalize_item_code(reference_row.get("ifrc_code"))
    duplicate_item_id = _find_duplicate_item_id(
        schema,
        ifrc_item_ref_id=reference_row["ifrc_item_ref_id"],
        item_code=canonical_code,
        exclude_item_id=exclude_item_id,
    )
    if duplicate_item_id is None:
        return None

    conflict_record, _ = get_item_record(duplicate_item_id)
    return {
        "code": ITEM_CANONICAL_CONFLICT_CODE,
        "ifrc_item_ref_id": reference_row["ifrc_item_ref_id"],
        "item_code": canonical_code,
        "existing_item": conflict_record,
    }


def _find_duplicate_item_id(
    schema: str,
    *,
    ifrc_item_ref_id: Any,
    item_code: str | None,
    exclude_item_id: Any | None = None,
) -> Any | None:
    where_clauses: list[str] = []
    params: list[Any] = []

    if ifrc_item_ref_id not in (None, ""):
        where_clauses.append("ifrc_item_ref_id = %s")
        params.append(ifrc_item_ref_id)
    if item_code:
        where_clauses.append("UPPER(item_code) = UPPER(%s)")
        params.append(item_code)
    if not where_clauses:
        return None

    sql = [
        f"SELECT item_id FROM {schema}.item",
        "WHERE (" + " OR ".join(where_clauses) + ")",
    ]
    if exclude_item_id not in (None, ""):
        sql.append("AND item_id <> %s")
        params.append(exclude_item_id)
    sql.append("ORDER BY item_id ASC LIMIT 1")

    with connection.cursor() as cursor:
        cursor.execute("\n".join(sql), params)
        row = cursor.fetchone()
    return row[0] if row else None


def _build_item_write_payload(
    data: dict[str, Any],
    *,
    is_update: bool,
    existing_record: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    schema = _schema_name()
    base_data = _item_column_payload(data)
    base_data.pop("item_code", None)
    base_data.pop("legacy_item_code", None)

    merged_reference_id = _merged_value(data, existing_record, "ifrc_item_ref_id")
    reference_row = (
        _fetch_ifrc_reference(schema, merged_reference_id)
        if merged_reference_id not in (None, "")
        else None
    )
    if reference_row is None:
        return base_data, None

    canonical_code = _normalize_item_code(reference_row.get("ifrc_code"))
    base_data["item_code"] = canonical_code

    existing_item_code = _normalize_item_code(
        existing_record.get("item_code") if existing_record else None
    )
    existing_legacy_code = _normalize_item_code(
        existing_record.get("legacy_item_code") if existing_record else None
    )
    provided_item_code = _normalize_item_code(data.get("item_code"))

    if existing_legacy_code:
        base_data["legacy_item_code"] = existing_legacy_code
    elif is_update and existing_item_code and existing_item_code != canonical_code:
        base_data["legacy_item_code"] = existing_item_code
    elif (not is_update) and provided_item_code and provided_item_code != canonical_code:
        base_data["legacy_item_code"] = provided_item_code

    return base_data, reference_row


def _resolve_item_order_by(requested_order_by: str | None, warnings: list[str]) -> str:
    allowed_columns = {
        "item_code": "i.item_code",
        "legacy_item_code": "i.legacy_item_code",
        "item_name": "i.item_name",
        "sku_code": "i.sku_code",
        "category_desc": "category_desc",
        "ifrc_family_label": "ifrc_family_label",
        "ifrc_reference_code": "ifrc_reference_code",
        "status_code": "i.status_code",
        "update_dtime": "i.update_dtime",
        "create_dtime": "i.create_dtime",
    }
    resolved = _parse_sort_expression(requested_order_by, allowed_columns=allowed_columns)
    if resolved:
        return resolved
    if requested_order_by and str(requested_order_by).strip():
        warnings.append("invalid_order_by")
    return "i.item_name ASC"


def _load_item_uom_options(cursor, schema: str, item_id: Any) -> list[dict[str, Any]]:
    cursor.execute(
        f"""
        SELECT
            item_uom_option_id,
            uom_code,
            conversion_factor,
            is_default,
            sort_order,
            status_code
        FROM {schema}.item_uom_option
        WHERE item_id = %s
          AND status_code = 'A'
        ORDER BY is_default DESC, sort_order ASC, uom_code ASC
        """,
        [item_id],
    )
    return [
        {
            "item_uom_option_id": row[0],
            "uom_code": row[1],
            "conversion_factor": row[2],
            "is_default": row[3],
            "sort_order": row[4],
            "status_code": row[5],
        }
        for row in cursor.fetchall()
    ]


def _fetch_ifrc_family(schema: str, family_id: Any) -> dict[str, Any] | None:
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT
                ifrc_family_id,
                category_id,
                group_code,
                family_code,
                family_label,
                status_code
            FROM {schema}.ifrc_family
            WHERE ifrc_family_id = %s
            LIMIT 1
            """,
            [family_id],
        )
        row = cursor.fetchone()
    if not row:
        return None
    return {
        "ifrc_family_id": row[0],
        "category_id": row[1],
        "group_code": row[2],
        "family_code": row[3],
        "family_label": row[4],
        "status_code": row[5],
    }


def _fetch_ifrc_reference(schema: str, reference_id: Any) -> dict[str, Any] | None:
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT
                ifrc_item_ref_id,
                ifrc_family_id,
                ifrc_code,
                reference_desc,
                size_weight,
                form,
                material,
                status_code
            FROM {schema}.ifrc_item_reference
            WHERE ifrc_item_ref_id = %s
            LIMIT 1
            """,
            [reference_id],
        )
        row = cursor.fetchone()
    if not row:
        return None
    return {
        "ifrc_item_ref_id": row[0],
        "ifrc_family_id": row[1],
        "ifrc_code": row[2],
        "reference_desc": row[3],
        "size_weight": row[4],
        "form": row[5],
        "material": row[6],
        "status_code": row[7],
    }


def _category_has_active_families(schema: str, category_id: Any) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT COUNT(*)
            FROM {schema}.ifrc_family
            WHERE category_id = %s
              AND status_code = 'A'
            """,
            [category_id],
        )
        row = cursor.fetchone()
    return bool(row and int(row[0] or 0) > 0)


def _normalize_item_code(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().upper()
    return normalized or None


def _same_identifier(left: Any, right: Any) -> bool:
    if left in (None, '') and right in (None, ''):
        return True
    return str(left).strip() == str(right).strip()


def _missing_uom_codes(schema: str, uom_codes: list[str]) -> list[str]:
    if not uom_codes:
        return []

    placeholders = ", ".join(["%s"] * len(uom_codes))
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT uom_code
            FROM {schema}.unitofmeasure
            WHERE uom_code IN ({placeholders})
            """,
            uom_codes,
        )
        existing = {str(row[0]).upper() for row in cursor.fetchall()}
    return [code for code in uom_codes if code not in existing]


def _normalize_item_uom_options(
    raw_options: Any,
    *,
    default_uom_code: str,
) -> tuple[list[dict[str, Any]] | None, dict[str, str]]:
    if raw_options is None:
        return None, {}
    if not isinstance(raw_options, list):
        return None, {"uom_options": "UOM options must be a list of objects."}

    errors: dict[str, str] = {}
    options_by_code: dict[str, dict[str, Any]] = {}
    for index, option in enumerate(raw_options):
        if not isinstance(option, dict):
            return None, {"uom_options": "UOM options must be a list of objects."}
        uom_code = str(option.get("uom_code") or "").strip().upper()
        if not uom_code:
            errors["uom_options"] = "Each UOM option must include a uom_code."
            break
        if uom_code in options_by_code:
            errors["uom_options"] = "Duplicate UOM options are not allowed."
            break
        raw_factor = option.get("conversion_factor", option.get("conversion_to_default", 1))
        try:
            conversion_factor = Decimal(str(raw_factor))
        except Exception:
            errors["uom_options"] = "Each UOM option must include a numeric conversion_factor."
            break
        if conversion_factor <= 0:
            errors["uom_options"] = "UOM conversion_factor must be greater than zero."
            break
        options_by_code[uom_code] = {
            "uom_code": uom_code,
            "conversion_factor": conversion_factor,
            "is_default": bool(option.get("is_default", False)),
            "sort_order": index + 1,
        }

    if errors:
        return None, errors

    if default_uom_code:
        default_row = options_by_code.get(default_uom_code)
        if default_row is None:
            options_by_code[default_uom_code] = {
                "uom_code": default_uom_code,
                "conversion_factor": Decimal("1"),
                "is_default": True,
                "sort_order": 0,
            }
        else:
            default_row["is_default"] = True
            default_row["conversion_factor"] = Decimal("1")
            default_row["sort_order"] = 0

    normalized = sorted(
        options_by_code.values(),
        key=lambda row: (row["sort_order"], row["uom_code"]),
    )
    for row in normalized:
        row["is_default"] = row["uom_code"] == default_uom_code
    return normalized, {}


def _ensure_default_item_uom_option(
    schema: str,
    item_id: Any,
    default_uom_code: str,
    actor_id: str,
) -> None:
    if not default_uom_code:
        return
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            UPDATE {schema}.item_uom_option AS item_uom_option
            SET
                is_default = FALSE,
                update_by_id = %s,
                update_dtime = NOW(),
                version_nbr = item_uom_option.version_nbr + 1
            WHERE item_id = %s
              AND uom_code <> %s
              AND is_default = TRUE
            """,
            [actor_id, item_id, default_uom_code],
        )
        cursor.execute(
            f"""
            INSERT INTO {schema}.item_uom_option (
                item_id,
                uom_code,
                conversion_factor,
                is_default,
                sort_order,
                status_code,
                create_by_id,
                create_dtime,
                update_by_id,
                update_dtime,
                version_nbr
            )
            VALUES (%s, %s, 1.0, TRUE, 0, 'A', %s, NOW(), %s, NOW(), 1)
            ON CONFLICT (item_id, uom_code) DO UPDATE
            SET
                conversion_factor = 1.0,
                is_default = TRUE,
                sort_order = 0,
                status_code = 'A',
                update_by_id = EXCLUDED.update_by_id,
                update_dtime = NOW(),
                version_nbr = item_uom_option.version_nbr + 1
            """,
            [item_id, default_uom_code, actor_id, actor_id],
        )


def _replace_item_uom_options(
    schema: str,
    item_id: Any,
    options: list[dict[str, Any]],
    actor_id: str,
) -> None:
    if not options:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE {schema}.item_uom_option AS item_uom_option
                SET
                    status_code = 'I',
                    update_by_id = %s,
                    update_dtime = NOW(),
                    version_nbr = item_uom_option.version_nbr + 1
                WHERE item_id = %s
                  AND status_code <> 'I'
                """,
                [actor_id, item_id],
            )
        return

    with connection.cursor() as cursor:
        default_uom_code = next(
            (str(option["uom_code"]).upper() for option in options if option.get("is_default")),
            "",
        )
        if default_uom_code:
            cursor.execute(
                f"""
                UPDATE {schema}.item_uom_option AS item_uom_option
                SET
                    is_default = FALSE,
                    update_by_id = %s,
                    update_dtime = NOW(),
                    version_nbr = item_uom_option.version_nbr + 1
                WHERE item_id = %s
                  AND uom_code <> %s
                  AND is_default = TRUE
                """,
                [actor_id, item_id, default_uom_code],
            )
        for option in options:
            cursor.execute(
                f"""
                INSERT INTO {schema}.item_uom_option (
                    item_id,
                    uom_code,
                    conversion_factor,
                    is_default,
                    sort_order,
                    status_code,
                    create_by_id,
                    create_dtime,
                    update_by_id,
                    update_dtime,
                    version_nbr
                )
                VALUES (%s, %s, %s, %s, %s, 'A', %s, NOW(), %s, NOW(), 1)
                ON CONFLICT (item_id, uom_code) DO UPDATE
                SET
                    conversion_factor = EXCLUDED.conversion_factor,
                    is_default = EXCLUDED.is_default,
                    sort_order = EXCLUDED.sort_order,
                    status_code = 'A',
                    update_by_id = EXCLUDED.update_by_id,
                    update_dtime = NOW(),
                    version_nbr = item_uom_option.version_nbr + 1
                """,
                [
                    item_id,
                    option["uom_code"],
                    option["conversion_factor"],
                    option["is_default"],
                    option["sort_order"],
                    actor_id,
                    actor_id,
                ],
            )

        placeholders = ", ".join(["%s"] * len(options))
        cursor.execute(
            f"""
            UPDATE {schema}.item_uom_option AS item_uom_option
            SET
                status_code = 'I',
                update_by_id = %s,
                update_dtime = NOW(),
                version_nbr = item_uom_option.version_nbr + 1
            WHERE item_id = %s
              AND uom_code NOT IN ({placeholders})
              AND status_code <> 'I'
            """,
            [actor_id, item_id] + [option["uom_code"] for option in options],
        )


def _item_column_payload(data: dict[str, Any]) -> dict[str, Any]:
    allowed_fields = {field.name for field in TABLE_REGISTRY["items"].data_fields}
    return {
        key: value
        for key, value in data.items()
        if key in allowed_fields
    }


def _tracked_item_state(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "identity": {
            "item_code": record.get("item_code"),
            "legacy_item_code": record.get("legacy_item_code"),
        },
        "category": {
            "category_id": record.get("category_id"),
            "category_code": record.get("category_code"),
            "category_desc": record.get("category_desc"),
        },
        "ifrc_family": (
            None
            if record.get("ifrc_family_id") in (None, "")
            else {
                "ifrc_family_id": record.get("ifrc_family_id"),
                "group_code": record.get("ifrc_group_code"),
                "group_label": record.get("ifrc_group_label"),
                "family_code": record.get("ifrc_family_code"),
                "family_label": record.get("ifrc_family_label"),
            }
        ),
        "ifrc_item_reference": (
            None
            if record.get("ifrc_item_ref_id") in (None, "")
            else {
                "ifrc_item_ref_id": record.get("ifrc_item_ref_id"),
                "ifrc_code": record.get("ifrc_reference_code"),
                "reference_desc": record.get("ifrc_reference_desc"),
                "category_code": record.get("ifrc_reference_category_code"),
                "category_label": record.get("ifrc_reference_category_label"),
                "spec_segment": record.get("ifrc_reference_spec_segment"),
                "size_weight": record.get("ifrc_reference_size_weight"),
                "form": record.get("ifrc_reference_form"),
                "material": record.get("ifrc_reference_material"),
            }
        ),
        "uom_options": [
            {
                "uom_code": option.get("uom_code"),
                "conversion_factor": option.get("conversion_factor"),
                "is_default": option.get("is_default"),
                "sort_order": option.get("sort_order"),
            }
            for option in record.get("uom_options", [])
        ],
        "batch_expiry": {
            "default_uom_code": record.get("default_uom_code"),
            "is_batched_flag": record.get("is_batched_flag"),
            "can_expire_flag": record.get("can_expire_flag"),
            "issuance_order": record.get("issuance_order"),
        },
        "status_code": record.get("status_code"),
    }


def _audit_action_from_status_change(
    before_record: dict[str, Any],
    after_record: dict[str, Any],
) -> str:
    before_status = str(before_record.get("status_code") or "").upper()
    after_status = str(after_record.get("status_code") or "").upper()
    if before_status != after_status and after_status == "I":
        return "INACTIVATE"
    if before_status != after_status and after_status == "A":
        return "ACTIVATE"
    return "UPDATE"


def _write_item_classification_audit(
    schema: str,
    *,
    item_id: Any,
    change_action: str,
    before_state: dict[str, Any] | None,
    after_state: dict[str, Any],
    changed_by_id: str,
) -> None:
    changed_fields = ITEM_AUDIT_STATE_FIELDS
    if before_state is not None:
        changed_fields = [
            field_name
            for field_name in ITEM_AUDIT_STATE_FIELDS
            if before_state.get(field_name) != after_state.get(field_name)
        ]

    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            INSERT INTO {schema}.item_classification_audit (
                item_id,
                change_action,
                changed_fields_json,
                before_state_json,
                after_state_json,
                changed_by_id,
                changed_at
            )
            VALUES (%s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, NOW())
            """,
            [
                item_id,
                change_action,
                json.dumps(_to_jsonable(changed_fields)),
                json.dumps(_to_jsonable(before_state)),
                json.dumps(_to_jsonable(after_state)),
                changed_by_id,
            ],
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

