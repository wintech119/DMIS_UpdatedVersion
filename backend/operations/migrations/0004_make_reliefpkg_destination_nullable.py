import os
import re

from django.db import migrations


_FORWARD_SQL_TEMPLATE = """
    ALTER TABLE {schema}.reliefpkg
    ALTER COLUMN to_inventory_id DROP NOT NULL;
"""


_REVERSE_SQL_TEMPLATE = """
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1
            FROM {schema}.reliefpkg
            WHERE to_inventory_id IS NULL
        ) THEN
            RAISE EXCEPTION
                'Cannot reverse migration: reliefpkg.to_inventory_id contains NULL values.';
        END IF;
    END $$;

    ALTER TABLE {schema}.reliefpkg
    ALTER COLUMN to_inventory_id SET NOT NULL;
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


def _legacy_reliefpkg_exists(schema_editor) -> bool:
    relation = f"{_schema_name(schema_editor)}.reliefpkg"
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass(%s)", [relation])
        row = cursor.fetchone()
    return bool(row and row[0])


def _forwards(apps, schema_editor):
    if not _is_postgres(schema_editor):
        return
    if not _legacy_reliefpkg_exists(schema_editor):
        return
    schema_editor.execute(_FORWARD_SQL_TEMPLATE.format(schema=_schema_name(schema_editor)))


def _backwards(apps, schema_editor):
    if not _is_postgres(schema_editor):
        return
    if not _legacy_reliefpkg_exists(schema_editor):
        return
    schema_editor.execute(_REVERSE_SQL_TEMPLATE.format(schema=_schema_name(schema_editor)))


class Migration(migrations.Migration):
    atomic = True

    dependencies = [
        ("operations", "0003_widen_legacy_tracking_numbers"),
    ]

    operations = [
        migrations.RunPython(_forwards, _backwards),
    ]
