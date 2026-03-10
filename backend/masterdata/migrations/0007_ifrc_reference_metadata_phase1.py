from __future__ import annotations

import os
import re

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


def _relation_exists(schema_editor, relation_name: str) -> bool:
    relation = f"{_schema_name(schema_editor)}.{relation_name}"
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass(%s)", [relation])
        row = cursor.fetchone()
    return bool(row and row[0])


def _forwards(apps, schema_editor):
    if not _is_postgres(schema_editor):
        return
    if not _relation_exists(schema_editor, "ifrc_item_reference"):
        return

    schema = _schema_name(schema_editor)
    schema_editor.execute(_FORWARD_SQL_TEMPLATE.format(schema=schema))

    from masterdata.item_master_taxonomy import sync_item_master_taxonomy

    sync_item_master_taxonomy(schema_editor.connection, schema=schema)


def _backwards(apps, schema_editor):
    if not _is_postgres(schema_editor):
        return
    if not _relation_exists(schema_editor, "ifrc_item_reference"):
        return

    schema = _schema_name(schema_editor)
    schema_editor.execute(_REVERSE_SQL_TEMPLATE.format(schema=schema))


class Migration(migrations.Migration):
    atomic = True

    dependencies = [
        ("masterdata", "0006_canonical_item_code_phase1"),
    ]

    operations = [
        migrations.RunPython(_forwards, _backwards),
    ]
