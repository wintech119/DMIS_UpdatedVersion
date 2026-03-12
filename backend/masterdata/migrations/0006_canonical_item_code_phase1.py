from __future__ import annotations

import os
import re

from django.db import migrations


_FORWARD_SQL_TEMPLATE = """
ALTER TABLE {schema}.item
    ADD COLUMN IF NOT EXISTS legacy_item_code VARCHAR(30);

CREATE INDEX IF NOT EXISTS idx_item_legacy_item_code
    ON {schema}.item (legacy_item_code);

CREATE UNIQUE INDEX IF NOT EXISTS ux_item_ifrc_item_ref_id_unique
    ON {schema}.item (ifrc_item_ref_id)
    WHERE ifrc_item_ref_id IS NOT NULL;

UPDATE {schema}.item AS item
SET legacy_item_code = CASE
        WHEN item.legacy_item_code IS NOT NULL THEN item.legacy_item_code
        WHEN item.item_code IS DISTINCT FROM ref.ifrc_code THEN item.item_code
        ELSE item.legacy_item_code
    END,
    item_code = ref.ifrc_code,
    update_by_id = 'system',
    update_dtime = NOW(),
    version_nbr = item.version_nbr + 1
FROM {schema}.ifrc_item_reference AS ref
WHERE item.ifrc_item_ref_id = ref.ifrc_item_ref_id
  AND item.item_code IS DISTINCT FROM ref.ifrc_code;

UPDATE {schema}.item AS item
SET legacy_item_code = item.item_code,
    update_by_id = 'system',
    update_dtime = NOW(),
    version_nbr = item.version_nbr + 1
WHERE item.ifrc_item_ref_id IS NULL
  AND item.legacy_item_code IS NULL
  AND COALESCE(item.item_code, '') <> '';
"""


_REVERSE_SQL_TEMPLATE = """
DROP INDEX IF EXISTS {schema}.ux_item_ifrc_item_ref_id_unique;
DROP INDEX IF EXISTS {schema}.idx_item_legacy_item_code;

ALTER TABLE {schema}.item
    DROP COLUMN IF EXISTS legacy_item_code;
"""


_SCHEMA_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _is_postgres(schema_editor) -> bool:
    return schema_editor.connection.vendor == "postgresql"


def _schema_name(schema_editor) -> str:
    configured = os.getenv("DMIS_DB_SCHEMA")
    if configured is not None:
        if not _SCHEMA_RE.fullmatch(configured):
            raise RuntimeError(f"Invalid DMIS_DB_SCHEMA: {configured!r}")
        return configured

    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT current_schema()")
        row = cursor.fetchone()
    return row[0] or "public"


def _legacy_item_table_exists(schema_editor) -> bool:
    relation = f"{_schema_name(schema_editor)}.item"
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass(%s)", [relation])
        row = cursor.fetchone()
    return bool(row and row[0])


def _assert_no_duplicate_ifrc_item_reference_mappings(schema_editor, schema: str) -> None:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT
                ifrc_item_ref_id,
                array_agg(item_id ORDER BY item_id)
            FROM {schema}.item
            WHERE ifrc_item_ref_id IS NOT NULL
            GROUP BY ifrc_item_ref_id
            HAVING COUNT(*) > 1
            ORDER BY ifrc_item_ref_id
            """
        )
        duplicate_rows = cursor.fetchall()

    if not duplicate_rows:
        return

    duplicate_details = ", ".join(
        f"{ifrc_item_ref_id}: {list(item_ids)}"
        for ifrc_item_ref_id, item_ids in duplicate_rows
    )
    raise RuntimeError(
        "Cannot create unique index ux_item_ifrc_item_ref_id_unique because duplicate "
        f"item.ifrc_item_ref_id mappings exist in {schema}.item. Reconcile these mappings "
        f"and rerun the migration. Offending mappings: {duplicate_details}"
    )


def _forwards(apps, schema_editor):
    if not _is_postgres(schema_editor):
        return
    if not _legacy_item_table_exists(schema_editor):
        return

    schema = _schema_name(schema_editor)
    _assert_no_duplicate_ifrc_item_reference_mappings(schema_editor, schema)
    schema_editor.execute(_FORWARD_SQL_TEMPLATE.format(schema=schema))


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
        ("masterdata", "0005_unified_item_master_phase1"),
    ]

    operations = [
        migrations.RunPython(_forwards, _backwards),
    ]
