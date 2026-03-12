from __future__ import annotations

import base64
import json
import os
import re
import zlib

from django.db import migrations


_SYSTEM_ACTOR_ID = "system"

_FROZEN_ITEM_MASTER_SEED_PAYLOAD = json.loads(
    zlib.decompress(
        base64.b64decode(
            """
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
"""
        )
    ).decode("utf-8")
)


_FORWARD_SQL_TEMPLATE = """
CREATE TABLE IF NOT EXISTS "{schema}".ifrc_family (
    ifrc_family_id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    category_id INTEGER NOT NULL REFERENCES "{schema}".itemcatg(category_id),
    group_code VARCHAR(4) NOT NULL,
    group_label VARCHAR(120) NOT NULL,
    family_code VARCHAR(6) NOT NULL,
    family_label VARCHAR(160) NOT NULL,
    source_version VARCHAR(80) NOT NULL,
    status_code CHAR(1) NOT NULL DEFAULT 'A',
    create_by_id VARCHAR(50) NOT NULL,
    create_dtime TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    update_by_id VARCHAR(50) NOT NULL,
    update_dtime TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    version_nbr INTEGER NOT NULL DEFAULT 1,
    CONSTRAINT uq_ifrc_family_group_family UNIQUE (group_code, family_code),
    CONSTRAINT c_ifrc_family_status CHECK (status_code IN ('A', 'I'))
);

CREATE INDEX IF NOT EXISTS idx_ifrc_family_category_status
    ON "{schema}".ifrc_family (category_id, status_code);

CREATE TABLE IF NOT EXISTS "{schema}".ifrc_item_reference (
    ifrc_item_ref_id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    ifrc_family_id BIGINT NOT NULL REFERENCES "{schema}".ifrc_family(ifrc_family_id),
    ifrc_code VARCHAR(30) NOT NULL,
    reference_desc VARCHAR(255) NOT NULL,
    category_code VARCHAR(6) NOT NULL,
    category_label VARCHAR(160) NOT NULL,
    spec_segment VARCHAR(7) NOT NULL DEFAULT '',
    source_version VARCHAR(80) NOT NULL,
    status_code CHAR(1) NOT NULL DEFAULT 'A',
    create_by_id VARCHAR(50) NOT NULL,
    create_dtime TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    update_by_id VARCHAR(50) NOT NULL,
    update_dtime TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    version_nbr INTEGER NOT NULL DEFAULT 1,
    CONSTRAINT uq_ifrc_item_reference_code UNIQUE (ifrc_code),
    CONSTRAINT uq_ifrc_item_reference_id_family UNIQUE (ifrc_item_ref_id, ifrc_family_id),
    CONSTRAINT c_ifrc_item_reference_status CHECK (status_code IN ('A', 'I'))
);

CREATE INDEX IF NOT EXISTS idx_ifrc_item_reference_family_status
    ON "{schema}".ifrc_item_reference (ifrc_family_id, status_code);

CREATE INDEX IF NOT EXISTS idx_ifrc_item_reference_code
    ON "{schema}".ifrc_item_reference (ifrc_code);

CREATE TABLE IF NOT EXISTS "{schema}".item_uom_option (
    item_uom_option_id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    item_id INTEGER NOT NULL REFERENCES "{schema}".item(item_id) ON DELETE CASCADE,
    uom_code VARCHAR(25) NOT NULL REFERENCES "{schema}".unitofmeasure(uom_code),
    conversion_factor NUMERIC(18, 6) NOT NULL DEFAULT 1.0,
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    sort_order INTEGER NOT NULL DEFAULT 0,
    status_code CHAR(1) NOT NULL DEFAULT 'A',
    create_by_id VARCHAR(50) NOT NULL,
    create_dtime TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    update_by_id VARCHAR(50) NOT NULL,
    update_dtime TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    version_nbr INTEGER NOT NULL DEFAULT 1,
    CONSTRAINT uq_item_uom_option_item_uom UNIQUE (item_id, uom_code),
    CONSTRAINT c_item_uom_option_factor_positive CHECK (conversion_factor > 0),
    CONSTRAINT c_item_uom_option_status CHECK (status_code IN ('A', 'I')),
    CONSTRAINT c_item_uom_option_default_factor CHECK (
        (NOT is_default) OR conversion_factor = 1.0
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_item_uom_option_one_default
    ON "{schema}".item_uom_option (item_id)
    WHERE is_default = TRUE AND status_code = 'A';

CREATE TABLE IF NOT EXISTS "{schema}".item_classification_audit (
    item_classification_audit_id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    item_id INTEGER NOT NULL REFERENCES "{schema}".item(item_id) ON DELETE CASCADE,
    change_action VARCHAR(32) NOT NULL,
    changed_fields_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    before_state_json JSONB,
    after_state_json JSONB NOT NULL,
    changed_by_id VARCHAR(50) NOT NULL,
    changed_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_item_classification_audit_item_changed_at
    ON "{schema}".item_classification_audit (item_id, changed_at DESC);

CREATE OR REPLACE FUNCTION "{schema}".fn_prevent_item_classification_audit_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'item_classification_audit is append-only';
END;
$$;

DROP TRIGGER IF EXISTS trg_item_classification_audit_no_mutation
    ON "{schema}".item_classification_audit;

CREATE TRIGGER trg_item_classification_audit_no_mutation
BEFORE UPDATE OR DELETE ON "{schema}".item_classification_audit
FOR EACH ROW
EXECUTE FUNCTION "{schema}".fn_prevent_item_classification_audit_mutation();

ALTER TABLE "{schema}".item
    ADD COLUMN IF NOT EXISTS ifrc_family_id BIGINT,
    ADD COLUMN IF NOT EXISTS ifrc_item_ref_id BIGINT;

CREATE INDEX IF NOT EXISTS idx_item_ifrc_family_id
    ON "{schema}".item (ifrc_family_id);

CREATE INDEX IF NOT EXISTS idx_item_ifrc_item_ref_id
    ON "{schema}".item (ifrc_item_ref_id);

ALTER TABLE "{schema}".item
    DROP CONSTRAINT IF EXISTS fk_item_ifrc_family;

ALTER TABLE "{schema}".item
    ADD CONSTRAINT fk_item_ifrc_family
    FOREIGN KEY (ifrc_family_id)
    REFERENCES "{schema}".ifrc_family(ifrc_family_id);

ALTER TABLE "{schema}".item
    DROP CONSTRAINT IF EXISTS fk_item_ifrc_item_ref;

ALTER TABLE "{schema}".item
    ADD CONSTRAINT fk_item_ifrc_item_ref
    FOREIGN KEY (ifrc_item_ref_id)
    REFERENCES "{schema}".ifrc_item_reference(ifrc_item_ref_id);

ALTER TABLE "{schema}".item
    DROP CONSTRAINT IF EXISTS c_item_ifrc_ref_requires_family;

ALTER TABLE "{schema}".item
    ADD CONSTRAINT c_item_ifrc_ref_requires_family
    CHECK (ifrc_item_ref_id IS NULL OR ifrc_family_id IS NOT NULL);

ALTER TABLE "{schema}".item
    DROP CONSTRAINT IF EXISTS fk_item_ifrc_ref_family_match;

ALTER TABLE "{schema}".item
    ADD CONSTRAINT fk_item_ifrc_ref_family_match
    FOREIGN KEY (ifrc_item_ref_id, ifrc_family_id)
    REFERENCES "{schema}".ifrc_item_reference(ifrc_item_ref_id, ifrc_family_id)
    DEFERRABLE INITIALLY IMMEDIATE;
"""


_REVERSE_SQL_TEMPLATE = """
ALTER TABLE "{schema}".item
    DROP CONSTRAINT IF EXISTS fk_item_ifrc_ref_family_match;

ALTER TABLE "{schema}".item
    DROP CONSTRAINT IF EXISTS c_item_ifrc_ref_requires_family;

ALTER TABLE "{schema}".item
    DROP CONSTRAINT IF EXISTS fk_item_ifrc_item_ref;

ALTER TABLE "{schema}".item
    DROP CONSTRAINT IF EXISTS fk_item_ifrc_family;

DROP INDEX IF EXISTS "{schema}".idx_item_ifrc_item_ref_id;
DROP INDEX IF EXISTS "{schema}".idx_item_ifrc_family_id;

ALTER TABLE "{schema}".item
    DROP COLUMN IF EXISTS ifrc_item_ref_id,
    DROP COLUMN IF EXISTS ifrc_family_id;

DROP TRIGGER IF EXISTS trg_item_classification_audit_no_mutation
    ON "{schema}".item_classification_audit;

DROP FUNCTION IF EXISTS "{schema}".fn_prevent_item_classification_audit_mutation();

DROP TABLE IF EXISTS "{schema}".item_classification_audit;
DROP INDEX IF EXISTS "{schema}".ux_item_uom_option_one_default;
DROP TABLE IF EXISTS "{schema}".item_uom_option;
DROP TABLE IF EXISTS "{schema}".ifrc_item_reference;
DROP TABLE IF EXISTS "{schema}".ifrc_family;
"""


def _is_postgres(schema_editor) -> bool:
    return schema_editor.connection.vendor == "postgresql"


def _schema_name(schema_editor) -> str:
    configured = os.getenv("DMIS_DB_SCHEMA")
    if configured is not None:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", configured):
            raise RuntimeError(f"Invalid DMIS_DB_SCHEMA: {configured!r}")
        return configured

    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT current_schema()")
        row = cursor.fetchone()
    return row[0] or "public"


def _quoted_schema_name(schema_editor) -> str:
    return f'"{_schema_name(schema_editor)}"'


def _quoted_schema(schema: str) -> str:
    return f'"{schema}"'


def _legacy_item_table_exists(schema_editor) -> bool:
    relation = f"{_quoted_schema_name(schema_editor)}.item"
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass(%s)", [relation])
        row = cursor.fetchone()
    return bool(row and row[0])


def _load_category_ids(cursor, schema: str) -> dict[str, int]:
    schema_sql = _quoted_schema(schema)
    cursor.execute(f"SELECT category_code, category_id FROM {schema_sql}.itemcatg")
    return {str(code): int(category_id) for code, category_id in cursor.fetchall()}


def _load_family_ids(cursor, schema: str) -> dict[tuple[str, str], int]:
    schema_sql = _quoted_schema(schema)
    cursor.execute(
        f"SELECT group_code, family_code, ifrc_family_id FROM {schema_sql}.ifrc_family"
    )
    return {
        (str(group_code), str(family_code)): int(ifrc_family_id)
        for group_code, family_code, ifrc_family_id in cursor.fetchall()
    }


def _sync_categories(cursor, schema: str, categories: list[dict[str, object]], actor_id: str) -> None:
    schema_sql = _quoted_schema(schema)
    values_sql = ", ".join(["(%s, %s, %s, %s)"] * len(categories))
    params: list[object] = []
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
        INSERT INTO {schema_sql}.itemcatg (
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

    deactivate_values = ", ".join(["(%s)"] * len(categories))
    deactivate_params = [category["category_code"] for category in categories]
    cursor.execute(
        f"""
        WITH source_rows(category_code) AS (
            VALUES {deactivate_values}
        )
        UPDATE {schema_sql}.itemcatg AS itemcatg
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
    families: list[dict[str, object]],
    category_id_by_code: dict[str, int],
    actor_id: str,
) -> None:
    schema_sql = _quoted_schema(schema)
    values_sql = ", ".join(["(%s, %s, %s, %s, %s, %s)"] * len(families))
    params: list[object] = []
    for family in families:
        category_id = category_id_by_code[str(family["category_code"])]
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
        INSERT INTO {schema_sql}.ifrc_family (
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

    deactivate_values = ", ".join(["(%s, %s)"] * len(families))
    deactivate_params: list[object] = []
    for family in families:
        deactivate_params.extend([family["group_code"], family["family_code"]])

    cursor.execute(
        f"""
        WITH source_rows(group_code, family_code) AS (
            VALUES {deactivate_values}
        )
        UPDATE {schema_sql}.ifrc_family AS ifrc_family
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
    references: list[dict[str, object]],
    family_id_by_key: dict[tuple[str, str], int],
    actor_id: str,
) -> None:
    schema_sql = _quoted_schema(schema)
    values_sql = ", ".join(["(%s, %s, %s, %s, %s, %s)"] * len(references))
    params: list[object] = []
    for reference in references:
        family_id = family_id_by_key[(str(reference["group_code"]), str(reference["family_code"]))]
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

    source_version = str(references[0]["source_version"])
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
        INSERT INTO {schema_sql}.ifrc_item_reference (
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
        UPDATE {schema_sql}.ifrc_item_reference AS ifrc_item_reference
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
    schema_sql = _quoted_schema(schema)
    cursor.execute(
        f"""
        UPDATE {schema_sql}.item_uom_option AS item_uom_option
        SET
            is_default = FALSE,
            update_by_id = %s,
            update_dtime = NOW(),
            version_nbr = item_uom_option.version_nbr + 1
        FROM {schema_sql}.item AS item
        WHERE item.item_id = item_uom_option.item_id
          AND item_uom_option.uom_code <> item.default_uom_code
          AND item_uom_option.is_default = TRUE
        """,
        [actor_id],
    )

    cursor.execute(
        f"""
        INSERT INTO {schema_sql}.item_uom_option (
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
        FROM {schema_sql}.item AS item
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


def _seed_item_master_taxonomy(connection_obj, *, schema: str, actor_id: str = _SYSTEM_ACTOR_ID) -> None:
    payload = _FROZEN_ITEM_MASTER_SEED_PAYLOAD
    with connection_obj.cursor() as cursor:
        _sync_categories(cursor, schema, payload["categories"], actor_id)
        category_id_by_code = _load_category_ids(cursor, schema)
        _sync_families(cursor, schema, payload["families"], category_id_by_code, actor_id)
        family_id_by_key = _load_family_ids(cursor, schema)
        _sync_references(cursor, schema, payload["references"], family_id_by_key, actor_id)
        _backfill_default_item_uom_options(cursor, schema, actor_id)


def _forwards(apps, schema_editor):
    if not _is_postgres(schema_editor):
        return
    if not _legacy_item_table_exists(schema_editor):
        return

    schema = _schema_name(schema_editor)
    schema_editor.execute(_FORWARD_SQL_TEMPLATE.format(schema=schema))
    _seed_item_master_taxonomy(schema_editor.connection, schema=schema)


def _backwards(apps, schema_editor):
    if not _is_postgres(schema_editor):
        return
    if not _legacy_item_table_exists(schema_editor):
        return

    schema = _schema_name(schema_editor)
    schema_editor.execute(_REVERSE_SQL_TEMPLATE.format(schema=schema))


class Migration(migrations.Migration):
    atomic = True

    dependencies = [
        ("masterdata", "0004_alter_itemifrcsuggestlog_options"),
    ]

    operations = [
        migrations.RunPython(_forwards, _backwards),
    ]
