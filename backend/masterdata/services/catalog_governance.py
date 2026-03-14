from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from django.db import DatabaseError, connection, transaction

from masterdata.ifrc_catalogue_loader import get_taxonomy
from masterdata.ifrc_code_agent import (
    IFRCAgent,
    _encode_generated_spec,
    _extract_form_metadata,
    _extract_material_metadata,
    _extract_size_weight_metadata,
)
from masterdata.services.data_access import (
    _is_sqlite,
    _normalize_field_value,
    _safe_rollback,
    _schema_name,
    activate_record,
    check_dependencies,
    create_record,
    get_record,
    get_table_config,
    inactivate_record,
    update_record,
)
from masterdata.services.item_master import _fetch_ifrc_family

logger = logging.getLogger(__name__)

GOVERNED_CATALOG_TABLE_KEYS = frozenset({
    "item_categories",
    "ifrc_families",
    "ifrc_item_references",
})

CATALOG_LOCKED_FIELDS: dict[str, tuple[str, ...]] = {
    "ifrc_families": ("group_code", "family_code"),
    "ifrc_item_references": (
        "ifrc_family_id",
        "ifrc_code",
        "category_code",
        "spec_segment",
    ),
}

CATALOG_EDIT_WARNINGS: dict[str, str] = {
    "ifrc_families": (
        "You are editing governed IFRC Family data. Canonical code-bearing fields stay locked; "
        "use replacement flow for code corrections or hierarchy realignment."
    ),
    "ifrc_item_references": (
        "You are editing governed IFRC Item Reference data. Canonical code-bearing fields stay locked; "
        "use replacement flow for code corrections or family realignment."
    ),
}

CATALOG_AUDIT_FIELDS: dict[str, tuple[str, ...]] = {
    "item_categories": (
        "category_type",
        "category_code",
        "category_desc",
        "comments_text",
        "status_code",
    ),
    "ifrc_families": (
        "category_id",
        "group_code",
        "group_label",
        "family_code",
        "family_label",
        "source_version",
        "status_code",
    ),
    "ifrc_item_references": (
        "ifrc_family_id",
        "ifrc_code",
        "reference_desc",
        "category_code",
        "category_label",
        "spec_segment",
        "size_weight",
        "form",
        "material",
        "source_version",
        "status_code",
    ),
}

_WORD_RE = re.compile(r"[A-Z0-9]+")


def is_governed_catalog_table(table_key: str) -> bool:
    return table_key in GOVERNED_CATALOG_TABLE_KEYS


def catalog_detail_metadata(table_key: str) -> dict[str, Any]:
    if table_key not in CATALOG_EDIT_WARNINGS:
        return {}
    return {
        "edit_guidance": {
            "warning_required": True,
            "warning_text": CATALOG_EDIT_WARNINGS[table_key],
            "locked_fields": list(CATALOG_LOCKED_FIELDS.get(table_key, ())),
            "replacement_supported": True,
        }
    }


def validate_catalog_update(
    table_key: str,
    data: dict[str, Any],
    existing_record: dict[str, Any],
) -> tuple[dict[str, str], list[str]]:
    errors: dict[str, str] = {}
    warnings: list[str] = []
    if table_key not in CATALOG_LOCKED_FIELDS:
        return errors, warnings

    cfg = get_table_config(table_key)
    if cfg is None:
        return {"detail": "Unknown governed catalog table."}, warnings

    field_map = {field.name: field for field in cfg.fields}
    for field_name in CATALOG_LOCKED_FIELDS[table_key]:
        if field_name not in data:
            continue
        field_def = field_map.get(field_name)
        if field_def is None:
            continue
        proposed = _normalize_field_value(field_def, data.get(field_name))
        existing = _normalize_field_value(field_def, existing_record.get(field_name))
        if proposed != existing:
            label = field_def.label or field_name.replace("_", " ").title()
            errors[field_name] = (
                f"{label} is locked for existing governed records. Use replacement flow instead."
            )
    return errors, warnings


def create_catalog_record(table_key: str, data: dict[str, Any], actor_id: str) -> tuple[Any | None, list[str]]:
    if _is_sqlite():
        return None, ["db_unavailable"]

    schema = _schema_name()
    try:
        with transaction.atomic():
            pk_value, warnings = create_record(table_key, data, actor_id)
            if pk_value is None:
                return None, warnings
            record, read_warnings = get_record(table_key, pk_value)
            warnings.extend(read_warnings)
            if record is None:
                return None, warnings or ["db_error"]
            _write_catalog_audit(
                schema,
                table_key=table_key,
                record_pk=pk_value,
                change_action="CREATE",
                before_state=None,
                after_state=_catalog_state(table_key, record),
                changed_by_id=actor_id,
                context={"source": "catalog_create"},
            )
            return pk_value, warnings
    except DatabaseError as exc:
        logger.warning("create_catalog_record(%s) failed: %s", table_key, exc)
        _safe_rollback()
        return None, ["db_error"]


def update_catalog_record(
    table_key: str,
    pk_value: Any,
    data: dict[str, Any],
    actor_id: str,
    expected_version: int | None = None,
    *,
    existing_record: dict[str, Any] | None = None,
) -> tuple[bool, list[str]]:
    if _is_sqlite():
        return False, ["db_unavailable"]

    schema = _schema_name()
    try:
        with transaction.atomic():
            before_record = existing_record
            before_warnings: list[str] = []
            if before_record is None:
                before_record, before_warnings = get_record(table_key, pk_value)
            if before_record is None:
                return False, before_warnings or ["not_found"]

            before_state = _catalog_state(table_key, before_record)
            success, warnings = update_record(table_key, pk_value, data, actor_id, expected_version)
            if not success:
                return False, warnings

            after_record, after_warnings = get_record(table_key, pk_value)
            warnings.extend(before_warnings)
            warnings.extend(after_warnings)
            if after_record is None:
                return False, warnings or ["db_error"]

            after_state = _catalog_state(table_key, after_record)
            if before_state != after_state:
                _write_catalog_audit(
                    schema,
                    table_key=table_key,
                    record_pk=pk_value,
                    change_action=_status_change_action(before_record, after_record),
                    before_state=before_state,
                    after_state=after_state,
                    changed_by_id=actor_id,
                    context={"source": "catalog_update"},
                )
            return True, warnings
    except DatabaseError as exc:
        logger.warning("update_catalog_record(%s, %s) failed: %s", table_key, pk_value, exc)
        _safe_rollback()
        return False, ["db_error"]

def inactivate_catalog_record(
    table_key: str,
    pk_value: Any,
    actor_id: str,
    expected_version: int | None = None,
) -> tuple[bool, list[str]]:
    return _status_catalog_record(table_key, pk_value, actor_id, expected_version, active=False)


def activate_catalog_record(
    table_key: str,
    pk_value: Any,
    actor_id: str,
    expected_version: int | None = None,
) -> tuple[bool, list[str]]:
    return _status_catalog_record(table_key, pk_value, actor_id, expected_version, active=True)


def create_catalog_replacement(
    table_key: str,
    pk_value: Any,
    data: dict[str, Any],
    actor_id: str,
    *,
    retire_original: bool = False,
) -> tuple[dict[str, Any] | None, list[str]]:
    if table_key not in {"ifrc_families", "ifrc_item_references"}:
        return None, ["replacement_not_supported"]
    if _is_sqlite():
        return None, ["db_unavailable"]

    schema = _schema_name()
    try:
        with transaction.atomic():
            original_record, original_warnings = get_record(table_key, pk_value)
            if original_record is None:
                return None, original_warnings or ["not_found"]

            base_payload = _replacement_payload(table_key, original_record)
            base_payload.update({key: value for key, value in (data or {}).items() if key != "retire_original"})
            base_payload["status_code"] = str(base_payload.get("status_code") or "A").strip().upper() or "A"

            new_pk, warnings = create_record(table_key, base_payload, actor_id)
            warnings.extend(original_warnings)
            if new_pk is None:
                return None, warnings

            new_record, read_warnings = get_record(table_key, new_pk)
            warnings.extend(read_warnings)
            if new_record is None:
                return None, warnings or ["db_error"]

            _write_catalog_audit(
                schema,
                table_key=table_key,
                record_pk=new_pk,
                change_action="REPLACEMENT_CREATE",
                before_state=None,
                after_state=_catalog_state(table_key, new_record),
                changed_by_id=actor_id,
                context={"replacement_for_pk": pk_value},
            )

            retired_original = False
            if retire_original:
                blocking, dep_warnings = check_dependencies(table_key, pk_value)
                warnings.extend(dep_warnings)
                if blocking:
                    warnings.append("replacement_original_retire_blocked")
                else:
                    before_state = _catalog_state(table_key, original_record)
                    success, retire_warnings = inactivate_record(table_key, pk_value, actor_id)
                    warnings.extend(retire_warnings)
                    if success:
                        retired_original = True
                        retired_record, _ = get_record(table_key, pk_value)
                        if retired_record is not None:
                            _write_catalog_audit(
                                schema,
                                table_key=table_key,
                                record_pk=pk_value,
                                change_action="SUPERSEDE",
                                before_state=before_state,
                                after_state=_catalog_state(table_key, retired_record),
                                changed_by_id=actor_id,
                                context={"replacement_record_pk": new_pk},
                            )

            return {
                "record": new_record,
                "replacement_for_pk": pk_value,
                "retire_original_requested": bool(retire_original),
                "retired_original": retired_original,
            }, warnings
    except DatabaseError as exc:
        logger.warning("create_catalog_replacement(%s, %s) failed: %s", table_key, pk_value, exc)
        _safe_rollback()
        return None, ["db_error"]


def suggest_ifrc_family_authoring(data: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, str], list[str]]:
    family_label_input = str(data.get("family_label") or data.get("label") or "").strip()
    if not family_label_input:
        return None, {"family_label": "Family label is required."}, []

    category_id = data.get("category_id")
    explicit_group_code = str(data.get("group_code") or "").strip().upper()
    explicit_group_label = _normalize_label(data.get("group_label") or "")
    normalized_family_label = _normalize_label(family_label_input)
    taxonomy = get_taxonomy()
    warnings: list[str] = []
    source = "deterministic"

    group_code = ""
    group_label = ""
    family_code = ""

    exact_taxonomy_family = _match_taxonomy_family(normalized_family_label, taxonomy)
    if exact_taxonomy_family is not None:
        group_code = exact_taxonomy_family["group_code"]
        group_label = exact_taxonomy_family["group_label"]
        family_code = exact_taxonomy_family["family_code"]
        normalized_family_label = exact_taxonomy_family["family_label"]
    elif explicit_group_code and explicit_group_code in taxonomy.groups:
        group_code = explicit_group_code
        group_label = taxonomy.group_label(group_code)
        family_code = _derive_code_from_label(normalized_family_label, 3)
    elif explicit_group_label:
        matched_group = _match_taxonomy_group(explicit_group_label, taxonomy)
        if matched_group is not None:
            group_code = matched_group["group_code"]
            group_label = matched_group["group_label"]
        family_code = _derive_code_from_label(normalized_family_label, 3)
    else:
        ai_candidate = _family_ai_candidate(normalized_family_label)
        if ai_candidate is not None:
            group_code = ai_candidate["group_code"]
            group_label = ai_candidate["group_label"]
            family_code = ai_candidate["family_code"]
            source = ai_candidate["source"]
        else:
            family_code = _derive_code_from_label(normalized_family_label, 3)

    conflicts, conflict_warnings = _family_conflicts(
        group_code=group_code,
        family_code=family_code,
        family_label=normalized_family_label,
    )
    warnings.extend(conflict_warnings)

    payload = {
        "source": source,
        "normalized": {
            "category_id": category_id,
            "group_code": group_code,
            "group_label": group_label,
            "family_code": family_code,
            "family_label": normalized_family_label,
        },
        "conflicts": conflicts,
        "edit_guidance": catalog_detail_metadata("ifrc_families").get("edit_guidance", {}),
    }
    return payload, {}, warnings


def suggest_ifrc_reference_authoring(data: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, str], list[str]]:
    family_id = data.get("ifrc_family_id") or data.get("family_id")
    reference_desc_input = str(data.get("reference_desc") or data.get("label") or "").strip()
    if family_id in (None, ""):
        return None, {"ifrc_family_id": "IFRC Family is required."}, []
    if not reference_desc_input:
        return None, {"reference_desc": "Reference description is required."}, []
    if _is_sqlite():
        return None, {}, ["db_unavailable"]

    schema = _schema_name()
    warnings: list[str] = []
    try:
        family_row = _fetch_ifrc_family(schema, family_id)
    except DatabaseError as exc:
        logger.warning("suggest_ifrc_reference_authoring failed to load family %s: %s", family_id, exc)
        _safe_rollback()
        return None, {}, ["db_error"]

    if family_row is None:
        return None, {"ifrc_family_id": "Selected IFRC Family does not exist."}, []

    reference_desc = _normalize_label(reference_desc_input)
    size_weight = _extract_size_weight_metadata(reference_desc_input, size_weight=str(data.get("size_weight") or ""))
    form = _extract_form_metadata(reference_desc_input, form=str(data.get("form") or ""))
    material = _extract_material_metadata(reference_desc_input, material=str(data.get("material") or ""))
    taxonomy = get_taxonomy()
    group_code = str(family_row.get("group_code") or "").upper()
    family_code = str(family_row.get("family_code") or "").upper()

    category_match = _match_reference_category(
        taxonomy=taxonomy,
        group_code=group_code,
        family_code=family_code,
        reference_desc=reference_desc,
    )
    category_code = category_match["category_code"]
    category_label = category_match["category_label"]
    spec_segment = _encode_generated_spec(
        reference_desc,
        size_weight=size_weight,
        form=form,
        material=material,
        category_code=category_code,
    )
    source = "deterministic"

    ai_candidate = _reference_ai_candidate(
        reference_desc=reference_desc_input,
        group_code=group_code,
        family_code=family_code,
        size_weight=size_weight,
        form=form,
        material=material,
        taxonomy=taxonomy,
    )
    if ai_candidate is not None:
        category_code = ai_candidate["category_code"]
        category_label = ai_candidate["category_label"]
        spec_segment = ai_candidate["spec_segment"]
        source = ai_candidate["source"]

    ifrc_code = f"{group_code}{family_code}{category_code}{spec_segment}".upper() if category_code else ""

    conflicts, conflict_warnings = _reference_conflicts(
        family_id=int(family_row["ifrc_family_id"]),
        ifrc_code=ifrc_code,
        reference_desc=reference_desc,
    )
    warnings.extend(conflict_warnings)

    payload = {
        "source": source,
        "normalized": {
            "ifrc_family_id": int(family_row["ifrc_family_id"]),
            "ifrc_code": ifrc_code,
            "reference_desc": reference_desc,
            "category_code": category_code,
            "category_label": category_label,
            "spec_segment": spec_segment,
            "size_weight": size_weight,
            "form": form,
            "material": material,
        },
        "conflicts": conflicts,
        "edit_guidance": catalog_detail_metadata("ifrc_item_references").get("edit_guidance", {}),
    }
    return payload, {}, warnings

def _status_catalog_record(
    table_key: str,
    pk_value: Any,
    actor_id: str,
    expected_version: int | None,
    *,
    active: bool,
) -> tuple[bool, list[str]]:
    if _is_sqlite():
        return False, ["db_unavailable"]

    schema = _schema_name()
    try:
        with transaction.atomic():
            before_record, before_warnings = get_record(table_key, pk_value)
            if before_record is None:
                return False, before_warnings or ["not_found"]
            before_state = _catalog_state(table_key, before_record)
            if active:
                success, warnings = activate_record(table_key, pk_value, actor_id, expected_version)
                action = "ACTIVATE"
            else:
                success, warnings = inactivate_record(table_key, pk_value, actor_id, expected_version)
                action = "INACTIVATE"
            if not success:
                return False, warnings
            after_record, after_warnings = get_record(table_key, pk_value)
            warnings.extend(before_warnings)
            warnings.extend(after_warnings)
            if after_record is None:
                return False, warnings or ["db_error"]
            _write_catalog_audit(
                schema,
                table_key=table_key,
                record_pk=pk_value,
                change_action=action,
                before_state=before_state,
                after_state=_catalog_state(table_key, after_record),
                changed_by_id=actor_id,
                context={"source": "catalog_status_change"},
            )
            return True, warnings
    except DatabaseError as exc:
        logger.warning("_status_catalog_record(%s, %s) failed: %s", table_key, pk_value, exc)
        _safe_rollback()
        return False, ["db_error"]


def _catalog_state(table_key: str, record: dict[str, Any]) -> dict[str, Any]:
    fields = CATALOG_AUDIT_FIELDS.get(table_key, ())
    return {field_name: record.get(field_name) for field_name in fields}


def _status_change_action(before_record: dict[str, Any], after_record: dict[str, Any]) -> str:
    before_status = str(before_record.get("status_code") or "").upper()
    after_status = str(after_record.get("status_code") or "").upper()
    if before_status != after_status and after_status == "I":
        return "INACTIVATE"
    if before_status != after_status and after_status == "A":
        return "ACTIVATE"
    return "UPDATE"


def _write_catalog_audit(
    schema: str,
    *,
    table_key: str,
    record_pk: Any,
    change_action: str,
    before_state: dict[str, Any] | None,
    after_state: dict[str, Any],
    changed_by_id: str,
    context: dict[str, Any] | None = None,
) -> None:
    changed_fields = list(CATALOG_AUDIT_FIELDS.get(table_key, ()))
    if before_state is not None:
        changed_fields = [
            field_name
            for field_name in CATALOG_AUDIT_FIELDS.get(table_key, ())
            if before_state.get(field_name) != after_state.get(field_name)
        ]

    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            INSERT INTO {schema}.catalog_governance_audit (
                table_key,
                record_pk,
                change_action,
                changed_fields_json,
                before_state_json,
                after_state_json,
                context_json,
                changed_by_id,
                changed_at
            )
            VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s, NOW())
            """,
            [
                table_key,
                int(record_pk),
                change_action,
                json.dumps(_to_jsonable(changed_fields)),
                json.dumps(_to_jsonable(before_state)),
                json.dumps(_to_jsonable(after_state)),
                json.dumps(_to_jsonable(context or {})),
                changed_by_id,
            ],
        )


def _replacement_payload(table_key: str, record: dict[str, Any]) -> dict[str, Any]:
    cfg = get_table_config(table_key)
    if cfg is None:
        return {}
    payload: dict[str, Any] = {}
    for field in cfg.data_fields:
        if field.pk or field.readonly:
            continue
        if field.name in record:
            payload[field.name] = record.get(field.name)
    return payload


def _family_conflicts(
    *,
    group_code: str,
    family_code: str,
    family_label: str,
) -> tuple[dict[str, Any], list[str]]:
    if _is_sqlite():
        return {"exact_code_match": None, "exact_label_match": None, "near_matches": []}, []

    schema = _schema_name()
    warnings: list[str] = []
    try:
        with connection.cursor() as cursor:
            exact_code = None
            exact_label = None
            near_matches: list[dict[str, Any]] = []

            if group_code and family_code:
                cursor.execute(
                    f"""
                    SELECT ifrc_family_id, category_id, group_code, group_label, family_code, family_label, status_code
                    FROM {schema}.ifrc_family
                    WHERE group_code = %s AND family_code = %s
                    LIMIT 1
                    """,
                    [group_code, family_code],
                )
                row = cursor.fetchone()
                if row:
                    exact_code = _family_row_to_dict(row)

            if family_label:
                cursor.execute(
                    f"""
                    SELECT ifrc_family_id, category_id, group_code, group_label, family_code, family_label, status_code
                    FROM {schema}.ifrc_family
                    WHERE UPPER(family_label) = %s
                    LIMIT 1
                    """,
                    [family_label.upper()],
                )
                row = cursor.fetchone()
                if row:
                    exact_label = _family_row_to_dict(row)

                pattern = _like_pattern(family_label)
                cursor.execute(
                    f"""
                    SELECT ifrc_family_id, category_id, group_code, group_label, family_code, family_label, status_code
                    FROM {schema}.ifrc_family
                    WHERE UPPER(family_label) LIKE %s
                    ORDER BY family_label
                    LIMIT 5
                    """,
                    [pattern],
                )
                near_matches = [_family_row_to_dict(row) for row in cursor.fetchall()]

            return {
                "exact_code_match": exact_code,
                "exact_label_match": exact_label,
                "near_matches": near_matches,
            }, warnings
    except DatabaseError as exc:
        logger.warning("_family_conflicts failed: %s", exc)
        _safe_rollback()
        warnings.append("family_conflict_lookup_failed")
        return {"exact_code_match": None, "exact_label_match": None, "near_matches": []}, warnings

def _reference_conflicts(
    *,
    family_id: int,
    ifrc_code: str,
    reference_desc: str,
) -> tuple[dict[str, Any], list[str]]:
    if _is_sqlite():
        return {"exact_code_match": None, "exact_desc_match": None, "near_matches": []}, []

    schema = _schema_name()
    warnings: list[str] = []
    try:
        with connection.cursor() as cursor:
            exact_code = None
            exact_desc = None
            near_matches: list[dict[str, Any]] = []

            if ifrc_code:
                cursor.execute(
                    f"""
                    SELECT ifrc_item_ref_id, ifrc_family_id, ifrc_code, reference_desc, category_code, category_label, spec_segment, status_code
                    FROM {schema}.ifrc_item_reference
                    WHERE ifrc_code = %s
                    LIMIT 1
                    """,
                    [ifrc_code],
                )
                row = cursor.fetchone()
                if row:
                    exact_code = _reference_row_to_dict(row)

            if reference_desc:
                cursor.execute(
                    f"""
                    SELECT ifrc_item_ref_id, ifrc_family_id, ifrc_code, reference_desc, category_code, category_label, spec_segment, status_code
                    FROM {schema}.ifrc_item_reference
                    WHERE ifrc_family_id = %s
                      AND UPPER(reference_desc) = %s
                    LIMIT 1
                    """,
                    [family_id, reference_desc.upper()],
                )
                row = cursor.fetchone()
                if row:
                    exact_desc = _reference_row_to_dict(row)

                pattern = _like_pattern(reference_desc)
                cursor.execute(
                    f"""
                    SELECT ifrc_item_ref_id, ifrc_family_id, ifrc_code, reference_desc, category_code, category_label, spec_segment, status_code
                    FROM {schema}.ifrc_item_reference
                    WHERE ifrc_family_id = %s
                      AND UPPER(reference_desc) LIKE %s
                    ORDER BY reference_desc
                    LIMIT 5
                    """,
                    [family_id, pattern],
                )
                near_matches = [_reference_row_to_dict(row) for row in cursor.fetchall()]

            return {
                "exact_code_match": exact_code,
                "exact_desc_match": exact_desc,
                "near_matches": near_matches,
            }, warnings
    except DatabaseError as exc:
        logger.warning("_reference_conflicts failed: %s", exc)
        _safe_rollback()
        warnings.append("reference_conflict_lookup_failed")
        return {"exact_code_match": None, "exact_desc_match": None, "near_matches": []}, warnings


def _match_taxonomy_group(label: str, taxonomy) -> dict[str, str] | None:
    normalized = label.strip().upper()
    if not normalized:
        return None
    for group_code, group in taxonomy.groups.items():
        if normalized == group.label.upper() or normalized in group.label.upper():
            return {"group_code": group_code, "group_label": group.label}
    return None


def _match_taxonomy_family(label: str, taxonomy) -> dict[str, str] | None:
    normalized = label.strip().upper()
    if not normalized:
        return None
    for group_code, group in taxonomy.groups.items():
        for family_code, family in group.families.items():
            family_label = family.label.upper()
            if normalized == family_label or normalized in family_label or family_label in normalized:
                return {
                    "group_code": group_code,
                    "group_label": group.label,
                    "family_code": family_code,
                    "family_label": family.label,
                }
    return None


def _family_ai_candidate(family_label: str) -> dict[str, str] | None:
    try:
        suggestion = IFRCAgent().suggest(family_label)
    except Exception as exc:
        logger.warning("Family authoring suggestion fell back to deterministic mode: %s", exc)
        return None
    if not suggestion.grp or not suggestion.fam:
        return None
    taxonomy = get_taxonomy()
    return {
        "group_code": suggestion.grp,
        "group_label": taxonomy.group_label(suggestion.grp),
        "family_code": suggestion.fam,
        "source": "hybrid" if suggestion.llm_used else "deterministic",
    }


def _reference_ai_candidate(
    *,
    reference_desc: str,
    group_code: str,
    family_code: str,
    size_weight: str,
    form: str,
    material: str,
    taxonomy,
) -> dict[str, str] | None:
    try:
        suggestion = IFRCAgent().generate(
            reference_desc,
            size_weight=size_weight,
            form=form,
            material=material,
        )
    except Exception as exc:
        logger.warning("Reference authoring suggestion fell back to deterministic mode: %s", exc)
        return None
    if suggestion.grp != group_code or suggestion.fam != family_code:
        return None
    cat = str(suggestion.cat or "").upper()
    categories = taxonomy.categories_for_family(group_code, family_code)
    if cat not in categories:
        return None
    return {
        "category_code": cat,
        "category_label": categories[cat].label,
        "spec_segment": str(suggestion.spec_seg or "").upper(),
        "source": "hybrid" if suggestion.llm_used else "deterministic",
    }


def _match_reference_category(*, taxonomy, group_code: str, family_code: str, reference_desc: str) -> dict[str, str]:
    categories = taxonomy.categories_for_family(group_code, family_code)
    if not categories:
        return {"category_code": "GENR", "category_label": "General"}

    tokens = set(_tokenize(reference_desc))
    best_code = None
    best_label = None
    best_score = -1
    for category_code, category in categories.items():
        score = 0
        label_tokens = set(_tokenize(category.label))
        score += len(tokens & label_tokens) * 3
        item_tokens = set()
        for item_name in category.items:
            item_tokens.update(_tokenize(item_name))
        score += len(tokens & item_tokens)
        if category_code in reference_desc.upper():
            score += 2
        if score > best_score:
            best_code = category_code
            best_label = category.label
            best_score = score
    if best_score <= 0:
        general_category = categories.get("GENR")
        return {
            "category_code": "GENR",
            "category_label": general_category.label if general_category is not None else "General",
        }
    return {"category_code": best_code, "category_label": best_label}


def _normalize_label(value: Any) -> str:
    raw = re.sub(r"\s+", " ", str(value or "")).strip()
    if not raw:
        return ""
    return " ".join(word.capitalize() if not word.isupper() else word for word in raw.split(" "))


def _derive_code_from_label(label: str, max_length: int) -> str:
    tokens = [token for token in _WORD_RE.findall(str(label or "").upper()) if token]
    if not tokens:
        return ""
    initials = "".join(token[0] for token in tokens)
    code = initials[:max_length]
    merged = "".join(tokens)
    for char in merged[1:]:
        if len(code) >= max_length:
            break
        if char in "AEIOU" and len(code) >= 3:
            continue
        code += char
    return code[:max_length]


def _tokenize(value: str) -> list[str]:
    return re.findall(r"[A-Z0-9]{2,}", str(value or "").upper())


def _like_pattern(value: str) -> str:
    tokens = _tokenize(value)
    if not tokens:
        return "%"
    return "%" + "%".join(tokens[:3]) + "%"


def _family_row_to_dict(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "ifrc_family_id": int(row[0]),
        "category_id": int(row[1]),
        "group_code": str(row[2] or ""),
        "group_label": str(row[3] or ""),
        "family_code": str(row[4] or ""),
        "family_label": str(row[5] or ""),
        "status_code": str(row[6] or ""),
    }


def _reference_row_to_dict(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "ifrc_item_ref_id": int(row[0]),
        "ifrc_family_id": int(row[1]),
        "ifrc_code": str(row[2] or ""),
        "reference_desc": str(row[3] or ""),
        "category_code": str(row[4] or ""),
        "category_label": str(row[5] or ""),
        "spec_segment": str(row[6] or ""),
        "status_code": str(row[7] or ""),
    }


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
