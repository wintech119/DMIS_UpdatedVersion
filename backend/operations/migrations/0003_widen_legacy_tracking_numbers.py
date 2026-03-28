import os
import re

from django.db import migrations


_FORWARD_SQL_TEMPLATE = """
    ALTER TABLE {schema}.reliefrqst
    ALTER COLUMN tracking_no TYPE VARCHAR(30);

    ALTER TABLE {schema}.reliefpkg
    ALTER COLUMN tracking_no TYPE VARCHAR(30)
    USING BTRIM(tracking_no)::VARCHAR(30);
"""


_REVERSE_SQL_TEMPLATE = """
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1
            FROM {schema}.reliefrqst
            WHERE LENGTH(tracking_no) > 7
        ) THEN
            RAISE EXCEPTION
                'Cannot reverse migration: reliefrqst.tracking_no contains values longer than 7 characters.';
        END IF;

        IF EXISTS (
            SELECT 1
            FROM {schema}.reliefpkg
            WHERE LENGTH(BTRIM(tracking_no)) > 7
        ) THEN
            RAISE EXCEPTION
                'Cannot reverse migration: reliefpkg.tracking_no contains values longer than 7 characters.';
        END IF;
    END $$;

    ALTER TABLE {schema}.reliefrqst
    ALTER COLUMN tracking_no TYPE VARCHAR(7);

    ALTER TABLE {schema}.reliefpkg
    ALTER COLUMN tracking_no TYPE CHAR(7)
    USING RPAD(BTRIM(tracking_no), 7, ' ');
"""


def _is_postgres(schema_editor) -> bool:
    return schema_editor.connection.vendor == "postgresql"


def _search_path_schema_name(schema_editor) -> str:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SHOW search_path")
        row = cursor.fetchone()

    search_path = str((row or [None])[0] or "").strip()
    if not search_path:
        return "public"

    first_schema = search_path.split(",", 1)[0].strip()
    if first_schema.startswith('"') and first_schema.endswith('"') and len(first_schema) >= 2:
        first_schema = first_schema[1:-1].replace('""', '"')

    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", first_schema):
        return "public"
    return first_schema


def _schema_name(schema_editor) -> str:
    configured = os.getenv("DMIS_DB_SCHEMA")
    if configured is not None:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", configured):
            raise RuntimeError(f"Invalid DMIS_DB_SCHEMA: {configured!r}")
        return configured

    return _search_path_schema_name(schema_editor)


def _legacy_tracking_tables_exist(schema_editor) -> bool:
    schema = _schema_name(schema_editor)
    relations = [f"{schema}.reliefrqst", f"{schema}.reliefpkg"]
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass(%s), to_regclass(%s)", relations)
        row = cursor.fetchone()
    return bool(row and row[0] and row[1])


def _forwards(apps, schema_editor):
    if not _is_postgres(schema_editor):
        return
    if not _legacy_tracking_tables_exist(schema_editor):
        return
    schema_editor.execute(_FORWARD_SQL_TEMPLATE.format(schema=_schema_name(schema_editor)))


def _backwards(apps, schema_editor):
    if not _is_postgres(schema_editor):
        return
    if not _legacy_tracking_tables_exist(schema_editor):
        return
    schema_editor.execute(_REVERSE_SQL_TEMPLATE.format(schema=_schema_name(schema_editor)))


class Migration(migrations.Migration):
    atomic = True

    dependencies = [
        ("operations", "0002_convert_core_id_fields_to_relations"),
    ]

    operations = [
        migrations.RunPython(_forwards, _backwards),
    ]
