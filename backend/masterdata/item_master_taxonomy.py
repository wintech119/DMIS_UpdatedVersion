from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from masterdata.ifrc_catalogue_loader import IFRCTaxonomy, get_taxonomy
from masterdata.ifrc_code_agent import _encode_spec

SCHEMA_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
SOURCE_VERSION_RE = re.compile(r"^#\s+Version:\s*(.+)$")

SYSTEM_ACTOR_ID = "system"

APPROVED_LEVEL1_CATEGORIES: list[dict[str, Any]] = [
    {"category_id": 101, "category_code": "FOOD_NUTRITION", "category_desc": "Food & Nutrition"},
    {"category_id": 102, "category_code": "WASH", "category_desc": "WASH"},
    {"category_id": 103, "category_code": "MEDICAL_HEALTH", "category_desc": "Medical & Health"},
    {"category_id": 104, "category_code": "HEALTH_KITS_SETS", "category_desc": "Health Kits & Sets"},
    {"category_id": 105, "category_code": "SHELTER_CONSTRUCTION", "category_desc": "Shelter & Construction"},
    {"category_id": 106, "category_code": "HOUSEHOLD_NFIS", "category_desc": "Household / NFIs"},
    {"category_id": 107, "category_code": "POWER_LIGHTING", "category_desc": "Power & Lighting"},
    {"category_id": 108, "category_code": "TOOLS_HARDWARE_ENGINEERING", "category_desc": "Tools, Hardware & Engineering"},
    {"category_id": 109, "category_code": "LOGISTICS_WAREHOUSING_PKG", "category_desc": "Logistics, Warehousing & Packaging"},
    {"category_id": 110, "category_code": "TELECOM_IT", "category_desc": "Telecom & IT"},
    {"category_id": 111, "category_code": "VEHICLES_TRANSPORT_FUEL", "category_desc": "Vehicles, Transport & Fuel"},
    {"category_id": 112, "category_code": "SAFETY_PPE_PERSONNEL_SUPPORT", "category_desc": "Safety / PPE / Personnel Support"},
    {"category_id": 113, "category_code": "LIVELIHOOD_RECOVERY", "category_desc": "Livelihood & Recovery"},
    {"category_id": 114, "category_code": "ADMIN_OPERATIONAL_SUPPORT", "category_desc": "Administration & Operational Support"},
]

IFRC_FAMILY_CATEGORY_CODE_MAP: dict[tuple[str, str], str] = {
    ("A", "OFC"): "ADMIN_OPERATIONAL_SUPPORT",
    ("C", "COM"): "TELECOM_IT",
    ("C", "RAD"): "TELECOM_IT",
    ("D", "ANB"): "MEDICAL_HEALTH",
    ("D", "ANL"): "MEDICAL_HEALTH",
    ("D", "ANT"): "MEDICAL_HEALTH",
    ("D", "ORS"): "MEDICAL_HEALTH",
    ("D", "VIT"): "MEDICAL_HEALTH",
    ("E", "BAT"): "POWER_LIGHTING",
    ("E", "FUE"): "VEHICLES_TRANSPORT_FUEL",
    ("E", "GEN"): "POWER_LIGHTING",
    ("E", "LGT"): "POWER_LIGHTING",
    ("F", "CAN"): "FOOD_NUTRITION",
    ("F", "CER"): "FOOD_NUTRITION",
    ("F", "NUT"): "FOOD_NUTRITION",
    ("F", "OIL"): "FOOD_NUTRITION",
    ("F", "PLS"): "FOOD_NUTRITION",
    ("F", "SAL"): "FOOD_NUTRITION",
    ("F", "SUG"): "FOOD_NUTRITION",
    ("H", "BED"): "HOUSEHOLD_NFIS",
    ("H", "KIT"): "HOUSEHOLD_NFIS",
    ("H", "SHE"): "SHELTER_CONSTRUCTION",
    ("K", "FAK"): "HEALTH_KITS_SETS",
    ("K", "HYK"): "WASH",
    ("K", "MED"): "HEALTH_KITS_SETS",
    ("M", "COL"): "MEDICAL_HEALTH",
    ("M", "DRE"): "MEDICAL_HEALTH",
    ("M", "GLV"): "SAFETY_PPE_PERSONNEL_SUPPORT",
    ("M", "MAS"): "SAFETY_PPE_PERSONNEL_SUPPORT",
    ("M", "SYR"): "MEDICAL_HEALTH",
    ("T", "VEH"): "VEHICLES_TRANSPORT_FUEL",
    ("W", "HYG"): "WASH",
    ("W", "SAN"): "WASH",
    ("W", "WTR"): "WASH",
}


def resolve_schema_name(configured: str | None = None) -> str:
    schema = configured or os.getenv("DMIS_DB_SCHEMA", "public")
    if not SCHEMA_RE.fullmatch(schema):
        raise RuntimeError(f"Invalid DMIS_DB_SCHEMA: {schema!r}")
    return schema


def taxonomy_source_version(path: Path | None = None) -> str:
    md_path = path or _taxonomy_path()
    try:
        with md_path.open(encoding="utf-8") as handle:
            for _ in range(8):
                line = handle.readline()
                if not line:
                    break
                match = SOURCE_VERSION_RE.match(line.strip())
                if match:
                    return match.group(1).strip()
    except OSError:
        pass
    return "2024"


def build_ifrc_taxonomy_seed_payload(
    taxonomy: IFRCTaxonomy | None = None,
) -> dict[str, list[dict[str, Any]]]:
    taxonomy = taxonomy or get_taxonomy()
    source_version = taxonomy_source_version()

    families: list[dict[str, Any]] = []
    references: list[dict[str, Any]] = []
    prefix_sequence: dict[str, int] = {}

    for group_code, group in taxonomy.groups.items():
        for family_code, family in group.families.items():
            category_code = IFRC_FAMILY_CATEGORY_CODE_MAP.get((group_code, family_code))
            if not category_code:
                raise RuntimeError(
                    f"Missing DMIS Level 1 category mapping for IFRC family {group_code}/{family_code}."
                )

            families.append(
                {
                    "group_code": group_code,
                    "group_label": group.label,
                    "family_code": family_code,
                    "family_label": family.label,
                    "category_code": category_code,
                    "source_version": source_version,
                }
            )

            for reference_category_code, reference_category in family.categories.items():
                for reference_desc in reference_category.items:
                    spec_segment = _encode_spec(reference_desc)
                    prefix = f"{group_code}{family_code}{reference_category_code}{spec_segment}".upper()
                    next_seq = prefix_sequence.get(prefix, 0) + 1
                    prefix_sequence[prefix] = next_seq
                    references.append(
                        {
                            "group_code": group_code,
                            "family_code": family_code,
                            "ifrc_code": f"{prefix}{next_seq:02d}",
                            "reference_desc": reference_desc.strip(),
                            "category_code": reference_category_code,
                            "category_label": reference_category.label,
                            "spec_segment": spec_segment,
                            "source_version": source_version,
                        }
                    )

    return {
        "categories": list(APPROVED_LEVEL1_CATEGORIES),
        "families": families,
        "references": references,
    }


def sync_item_master_taxonomy(
    connection_obj,
    *,
    schema: str | None = None,
    actor_id: str = SYSTEM_ACTOR_ID,
    taxonomy: IFRCTaxonomy | None = None,
) -> dict[str, int]:
    schema_name = resolve_schema_name(schema)
    payload = build_ifrc_taxonomy_seed_payload(taxonomy)

    with connection_obj.cursor() as cursor:
        _sync_categories(cursor, schema_name, payload["categories"], actor_id)
        category_id_by_code = _load_category_ids(cursor, schema_name)
        _sync_families(
            cursor,
            schema_name,
            payload["families"],
            category_id_by_code,
            actor_id,
        )
        family_id_by_key = _load_family_ids(cursor, schema_name)
        _sync_references(
            cursor,
            schema_name,
            payload["references"],
            family_id_by_key,
            actor_id,
        )
        _backfill_default_item_uom_options(cursor, schema_name, actor_id)

    return {
        "categories": len(payload["categories"]),
        "families": len(payload["families"]),
        "references": len(payload["references"]),
    }


def _taxonomy_path() -> Path:
    return Path(__file__).resolve().parent / "data" / "ifrc_catalogue_taxonomy.md"


def _load_category_ids(cursor, schema: str) -> dict[str, int]:
    cursor.execute(
        f"SELECT category_code, category_id FROM {schema}.itemcatg"
    )
    return {str(code): int(category_id) for code, category_id in cursor.fetchall()}


def _load_family_ids(cursor, schema: str) -> dict[tuple[str, str], int]:
    cursor.execute(
        f"SELECT group_code, family_code, ifrc_family_id FROM {schema}.ifrc_family"
    )
    return {
        (str(group_code), str(family_code)): int(ifrc_family_id)
        for group_code, family_code, ifrc_family_id in cursor.fetchall()
    }


def _sync_categories(
    cursor,
    schema: str,
    categories: list[dict[str, Any]],
    actor_id: str,
) -> None:
    values_sql = ", ".join(["(%s, %s, %s, %s)"] * len(categories))
    params: list[Any] = []
    for category in categories:
        params.extend(
            [
                category["category_id"],
                category["category_code"],
                category["category_desc"],
                "GOODS",
            ]
        )

    cursor.execute(
        f"""
        WITH source_rows(category_id, category_code, category_desc, category_type) AS (
            VALUES {values_sql}
        )
        INSERT INTO {schema}.itemcatg (
            category_id,
            category_code,
            category_desc,
            category_type,
            comments_text,
            status_code,
            create_by_id,
            create_dtime,
            update_by_id,
            update_dtime,
            version_nbr
        )
        SELECT
            category_id,
            category_code,
            category_desc,
            category_type,
            'Phase 1 governed Level 1 business category',
            'A',
            %s,
            NOW(),
            %s,
            NOW(),
            1
        FROM source_rows
        ON CONFLICT (category_code) DO UPDATE
        SET
            category_desc = EXCLUDED.category_desc,
            category_type = EXCLUDED.category_type,
            status_code = 'A',
            update_by_id = EXCLUDED.update_by_id,
            update_dtime = NOW(),
            version_nbr = itemcatg.version_nbr + 1
        """,
        params + [actor_id, actor_id],
    )

    deactivate_params = [category["category_code"] for category in categories]
    deactivate_values = ", ".join(["(%s)"] * len(categories))
    cursor.execute(
        f"""
        WITH source_rows(category_code) AS (
            VALUES {deactivate_values}
        )
        UPDATE {schema}.itemcatg AS itemcatg
        SET
            status_code = 'I',
            update_by_id = %s,
            update_dtime = NOW(),
            version_nbr = itemcatg.version_nbr + 1
        WHERE NOT EXISTS (
            SELECT 1
            FROM source_rows
            WHERE source_rows.category_code = itemcatg.category_code
        )
          AND itemcatg.status_code <> 'I'
        """,
        deactivate_params + [actor_id],
    )


def _sync_families(
    cursor,
    schema: str,
    families: list[dict[str, Any]],
    category_id_by_code: dict[str, int],
    actor_id: str,
) -> None:
    values_sql = ", ".join(["(%s, %s, %s, %s, %s, %s)"] * len(families))
    params: list[Any] = []
    for family in families:
        category_id = category_id_by_code[family["category_code"]]
        params.extend(
            [
                category_id,
                family["group_code"],
                family["group_label"],
                family["family_code"],
                family["family_label"],
                family["source_version"],
            ]
        )

    cursor.execute(
        f"""
        WITH source_rows(
            category_id,
            group_code,
            group_label,
            family_code,
            family_label,
            source_version
        ) AS (
            VALUES {values_sql}
        )
        INSERT INTO {schema}.ifrc_family (
            category_id,
            group_code,
            group_label,
            family_code,
            family_label,
            source_version,
            status_code,
            create_by_id,
            create_dtime,
            update_by_id,
            update_dtime,
            version_nbr
        )
        SELECT
            category_id,
            group_code,
            group_label,
            family_code,
            family_label,
            source_version,
            'A',
            %s,
            NOW(),
            %s,
            NOW(),
            1
        FROM source_rows
        ON CONFLICT (group_code, family_code) DO UPDATE
        SET
            category_id = EXCLUDED.category_id,
            group_label = EXCLUDED.group_label,
            family_label = EXCLUDED.family_label,
            source_version = EXCLUDED.source_version,
            status_code = 'A',
            update_by_id = EXCLUDED.update_by_id,
            update_dtime = NOW(),
            version_nbr = ifrc_family.version_nbr + 1
        """,
        params + [actor_id, actor_id],
    )

    deactivate_params: list[Any] = []
    deactivate_values = ", ".join(["(%s, %s)"] * len(families))
    for family in families:
        deactivate_params.extend([family["group_code"], family["family_code"]])

    cursor.execute(
        f"""
        WITH source_rows(group_code, family_code) AS (
            VALUES {deactivate_values}
        )
        UPDATE {schema}.ifrc_family AS ifrc_family
        SET
            status_code = 'I',
            update_by_id = %s,
            update_dtime = NOW(),
            version_nbr = ifrc_family.version_nbr + 1
        WHERE NOT EXISTS (
            SELECT 1
            FROM source_rows
            WHERE source_rows.group_code = ifrc_family.group_code
              AND source_rows.family_code = ifrc_family.family_code
        )
          AND ifrc_family.status_code <> 'I'
        """,
        deactivate_params + [actor_id],
    )


def _sync_references(
    cursor,
    schema: str,
    references: list[dict[str, Any]],
    family_id_by_key: dict[tuple[str, str], int],
    actor_id: str,
) -> None:
    values_sql = ", ".join(["(%s, %s, %s, %s, %s, %s)"] * len(references))
    params: list[Any] = []
    for reference in references:
        family_id = family_id_by_key[(reference["group_code"], reference["family_code"])]
        params.extend(
            [
                family_id,
                reference["ifrc_code"],
                reference["reference_desc"],
                reference["category_code"],
                reference["category_label"],
                reference["spec_segment"],
            ]
        )

    source_version = references[0]["source_version"] if references else taxonomy_source_version()
    cursor.execute(
        f"""
        WITH source_rows(
            ifrc_family_id,
            ifrc_code,
            reference_desc,
            category_code,
            category_label,
            spec_segment
        ) AS (
            VALUES {values_sql}
        )
        INSERT INTO {schema}.ifrc_item_reference (
            ifrc_family_id,
            ifrc_code,
            reference_desc,
            category_code,
            category_label,
            spec_segment,
            source_version,
            status_code,
            create_by_id,
            create_dtime,
            update_by_id,
            update_dtime,
            version_nbr
        )
        SELECT
            ifrc_family_id,
            ifrc_code,
            reference_desc,
            category_code,
            category_label,
            spec_segment,
            %s,
            'A',
            %s,
            NOW(),
            %s,
            NOW(),
            1
        FROM source_rows
        ON CONFLICT (ifrc_code) DO UPDATE
        SET
            ifrc_family_id = EXCLUDED.ifrc_family_id,
            reference_desc = EXCLUDED.reference_desc,
            category_code = EXCLUDED.category_code,
            category_label = EXCLUDED.category_label,
            spec_segment = EXCLUDED.spec_segment,
            source_version = EXCLUDED.source_version,
            status_code = 'A',
            update_by_id = EXCLUDED.update_by_id,
            update_dtime = NOW(),
            version_nbr = ifrc_item_reference.version_nbr + 1
        """,
        params + [source_version, actor_id, actor_id],
    )

    deactivate_values = ", ".join(["(%s)"] * len(references))
    deactivate_params = [reference["ifrc_code"] for reference in references]
    cursor.execute(
        f"""
        WITH source_rows(ifrc_code) AS (
            VALUES {deactivate_values}
        )
        UPDATE {schema}.ifrc_item_reference AS ifrc_item_reference
        SET
            status_code = 'I',
            update_by_id = %s,
            update_dtime = NOW(),
            version_nbr = ifrc_item_reference.version_nbr + 1
        WHERE NOT EXISTS (
            SELECT 1
            FROM source_rows
            WHERE source_rows.ifrc_code = ifrc_item_reference.ifrc_code
        )
          AND ifrc_item_reference.status_code <> 'I'
        """,
        deactivate_params + [actor_id],
    )


def _backfill_default_item_uom_options(cursor, schema: str, actor_id: str) -> None:
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
        SELECT
            item_id,
            default_uom_code,
            1.0,
            TRUE,
            0,
            'A',
            %s,
            NOW(),
            %s,
            NOW(),
            1
        FROM {schema}.item AS item
        WHERE item.default_uom_code IS NOT NULL
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
        [actor_id, actor_id],
    )

    cursor.execute(
        f"""
        UPDATE {schema}.item_uom_option AS item_uom_option
        SET
            is_default = FALSE,
            update_by_id = %s,
            update_dtime = NOW(),
            version_nbr = item_uom_option.version_nbr + 1
        FROM {schema}.item AS item
        WHERE item.item_id = item_uom_option.item_id
          AND item_uom_option.uom_code <> item.default_uom_code
          AND item_uom_option.is_default = TRUE
        """,
        [actor_id],
    )
