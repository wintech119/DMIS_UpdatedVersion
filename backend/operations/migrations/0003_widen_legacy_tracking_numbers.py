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
