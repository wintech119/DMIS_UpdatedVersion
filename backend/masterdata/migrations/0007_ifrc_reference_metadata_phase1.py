from __future__ import annotations

import os
import re
from decimal import Decimal, InvalidOperation

from django.db import migrations


_FORWARD_SQL_TEMPLATE = """
ALTER TABLE {schema}.ifrc_item_reference
    ADD COLUMN IF NOT EXISTS size_weight VARCHAR(40),
    ADD COLUMN IF NOT EXISTS form VARCHAR(40),
    ADD COLUMN IF NOT EXISTS material VARCHAR(40);
"""


_REVERSE_SQL_TEMPLATE = """
ALTER TABLE {schema}.ifrc_item_reference
    DROP COLUMN IF EXISTS material,
    DROP COLUMN IF EXISTS form,
    DROP COLUMN IF EXISTS size_weight;
"""


_SCHEMA_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_SYSTEM_ACTOR_ID = "system"

_SIZE_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(kg|mg|g|l|lt|liter|litre|ml|kva|kw|cm|mm)\b",
    re.IGNORECASE,
)
_DIMENSION_RE = re.compile(
    r"(\d+(?:\.\d+)?\s*x\s*\d+(?:\.\d+)?)\s*(m\^2|m2|sqm|sq\s*m|m)\b",
    re.IGNORECASE,
)
_AREA_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(m\^2|m2|sqm|sq\s*m)\b",
    re.IGNORECASE,
)

_FORM_CODES: dict[str, str] = {
    "tablet": "TB", "tablets": "TB",
    "tab": "TB", "tabs": "TB",
    "liquid": "LQ",
    "solution": "SL",
    "powder": "PW", "powdered": "PW",
    "canned": "CN", "can": "CN",
    "bar": "BR", "bars": "BR",
    "sachet": "SC", "sachets": "SC",
    "capsule": "CP", "capsules": "CP",
    "cream": "CR",
    "roll": "RL", "rolls": "RL",
    "sheet": "SH", "sheets": "SH",
    "kit": "KT",
    "pack": "PK", "packet": "PK",
    "bottle": "BT",
    "bag": "BG",
    "box": "BX",
    "tube": "TU",
    "gel": "GL",
    "spray": "SP",
    "syrup": "SY",
    "injection": "IN",
    "infusion": "IF",
    "lotion": "LO",
}

_FORM_LABELS: dict[str, str] = {
    "TB": "TABLET",
    "LQ": "LIQUID",
    "SL": "SOLUTION",
    "PW": "POWDER",
    "CN": "CAN",
    "BR": "BAR",
    "SC": "SACHET",
    "CP": "CAPSULE",
    "CR": "CREAM",
    "RL": "ROLL",
    "SH": "SHEET",
    "KT": "KIT",
    "PK": "PACK",
    "BT": "BOTTLE",
    "BG": "BAG",
    "BX": "BOX",
    "TU": "TUBE",
    "GL": "GEL",
    "SP": "SPRAY",
    "SY": "SYRUP",
    "IN": "INJECTION",
    "IF": "INFUSION",
    "LO": "LOTION",
}

_MATERIAL_CODES: dict[str, str] = {
    "aluminized": "AL", "aluminium": "AL", "aluminum": "AL",
    "cotton": "CT",
    "polyethylene": "PE",
    "polypropylene": "PP",
    "plastic": "PL",
    "rubber": "RB",
    "nylon": "NY",
    "synthetic": "SY",
    "stainless": "SS",
    "latex": "LX",
    "wool": "WO",
    "fleece": "FL",
    "nitrile": "NI",
}

_MATERIAL_LABELS: dict[str, str] = {
    "AL": "ALUMINIZED",
    "CT": "COTTON",
    "PE": "POLYETHYLENE",
    "PP": "POLYPROPYLENE",
    "PL": "PLASTIC",
    "RB": "RUBBER",
    "NY": "NYLON",
    "SY": "SYNTHETIC",
    "SS": "STAINLESS",
    "LX": "LATEX",
    "WO": "WOOL",
    "FL": "FLEECE",
    "NI": "NITRILE",
}


def _is_postgres(schema_editor) -> bool:
    return schema_editor.connection.vendor == "postgresql"


def _validated_schema(schema: object, *, source: str) -> str:
    if not isinstance(schema, str) or not _SCHEMA_RE.fullmatch(schema):
        raise RuntimeError(f"Invalid {source}: {schema!r}")
    return schema


def _quoted_schema(schema_editor, schema: str) -> str:
    validated_schema = _validated_schema(schema, source="database schema name")
    return schema_editor.connection.ops.quote_name(validated_schema)


def _qualified_relation_name(schema_editor, *, schema: str, relation_name: str) -> str:
    return (
        f"{_quoted_schema(schema_editor, schema)}."
        f"{schema_editor.connection.ops.quote_name(relation_name)}"
    )


def _schema_name(schema_editor) -> str:
    configured = os.getenv("DMIS_DB_SCHEMA")
    if configured is not None:
        return _validated_schema(configured, source="DMIS_DB_SCHEMA")

    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT current_schema()")
        row = cursor.fetchone()
    schema = row[0] or "public"
    return _validated_schema(schema, source="database schema name")


def _relation_exists(schema_editor, relation_name: str) -> bool:
    relation = _qualified_relation_name(
        schema_editor,
        schema=_schema_name(schema_editor),
        relation_name=relation_name,
    )
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass(%s)", [relation])
        row = cursor.fetchone()
    return bool(row and row[0])


def _extract_form_metadata(reference_desc: str) -> str:
    normalized = str(reference_desc or "").strip().lower()
    for keyword, code in _FORM_CODES.items():
        if re.search(r"\b" + re.escape(keyword) + r"\b", normalized):
            return _FORM_LABELS.get(code, keyword.upper())
    return ""


def _extract_material_metadata(reference_desc: str) -> str:
    normalized = str(reference_desc or "").strip().lower()
    for keyword, code in _MATERIAL_CODES.items():
        if keyword in normalized:
            return _MATERIAL_LABELS.get(code, keyword.upper())
    return ""


def _extract_size_weight_metadata(reference_desc: str) -> str:
    source = str(reference_desc or "").strip().lower()
    match = _DIMENSION_RE.search(source)
    if not match:
        match = _AREA_RE.search(source)
    if not match:
        match = _SIZE_RE.search(source)
    if not match:
        return ""

    raw_value = re.sub(r"\s*x\s*", "x", str(match.group(1) or "").strip())
    raw_unit = re.sub(r"\s+", " ", str(match.group(2) or "").strip().lower())
    unit_map = {
        "kg": "KG",
        "mg": "MG",
        "g": "G",
        "l": "L",
        "lt": "L",
        "liter": "L",
        "litre": "L",
        "ml": "ML",
        "kva": "KVA",
        "kw": "KW",
        "cm": "CM",
        "mm": "MM",
        "m2": "M2",
        "m^2": "M2",
        "sqm": "M2",
        "sq m": "M2",
    }
    if raw_unit == "m" and "x" in raw_value.lower():
        unit = "M2"
    else:
        unit = unit_map.get(raw_unit, raw_unit.upper())
    try:
        value = Decimal(raw_value)
        if value == value.to_integral():
            value_text = str(value.quantize(Decimal("1")))
        else:
            value_text = format(value.normalize(), "f").rstrip("0").rstrip(".")
    except (InvalidOperation, ValueError):
        value_text = raw_value
    return f"{value_text} {unit}".strip().upper()


def _backfill_reference_metadata(schema_editor, schema: str) -> None:
    table_sql = _qualified_relation_name(
        schema_editor,
        schema=schema,
        relation_name="ifrc_item_reference",
    )
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT
                ifrc_item_ref_id,
                reference_desc,
                COALESCE(size_weight, ''),
                COALESCE(form, ''),
                COALESCE(material, '')
            FROM {table_sql}
            """
        )
        updates: list[tuple[object, ...]] = []
        for reference_id, reference_desc, existing_size_weight, existing_form, existing_material in cursor.fetchall():
            size_weight = _extract_size_weight_metadata(str(reference_desc or "")) or None
            form = _extract_form_metadata(str(reference_desc or "")) or None
            material = _extract_material_metadata(str(reference_desc or "")) or None
            if (
                (existing_size_weight or "") == (size_weight or "")
                and (existing_form or "") == (form or "")
                and (existing_material or "") == (material or "")
            ):
                continue
            updates.append(
                (
                    size_weight,
                    form,
                    material,
                    _SYSTEM_ACTOR_ID,
                    reference_id,
                    size_weight,
                    form,
                    material,
                )
            )
        if updates:
            cursor.executemany(
                f"""
                UPDATE {table_sql}
                SET
                    size_weight = %s,
                    form = %s,
                    material = %s,
                    update_by_id = %s,
                    update_dtime = NOW(),
                    version_nbr = version_nbr + 1
                WHERE ifrc_item_ref_id = %s
                  AND (
                      COALESCE(size_weight, '') IS DISTINCT FROM COALESCE(%s, '')
                      OR COALESCE(form, '') IS DISTINCT FROM COALESCE(%s, '')
                      OR COALESCE(material, '') IS DISTINCT FROM COALESCE(%s, '')
                  )
                """,
                updates,
            )


def _forwards(apps, schema_editor):
    if not _is_postgres(schema_editor):
        return
    if not _relation_exists(schema_editor, "ifrc_item_reference"):
        return

    schema = _schema_name(schema_editor)
    quoted_schema = _quoted_schema(schema_editor, schema)
    schema_editor.execute(_FORWARD_SQL_TEMPLATE.format(schema=quoted_schema))
    _backfill_reference_metadata(schema_editor, schema)


def _backwards(apps, schema_editor):
    if not _is_postgres(schema_editor):
        return
    if not _relation_exists(schema_editor, "ifrc_item_reference"):
        return

    schema = _schema_name(schema_editor)
    quoted_schema = _quoted_schema(schema_editor, schema)
    schema_editor.execute(_REVERSE_SQL_TEMPLATE.format(schema=quoted_schema))


class Migration(migrations.Migration):
    atomic = True

    dependencies = [
        ("masterdata", "0006_canonical_item_code_phase1"),
    ]

    operations = [
        migrations.RunPython(_forwards, _backwards),
    ]
