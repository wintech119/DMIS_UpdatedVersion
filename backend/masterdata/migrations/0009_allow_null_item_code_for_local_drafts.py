from __future__ import annotations

import os
import re

from django.db import migrations


_FORWARD_SQL_TEMPLATE = """
ALTER TABLE {schema}.item
    ALTER COLUMN item_code DROP NOT NULL;
"""


_REVERSE_SQL_TEMPLATE = """
UPDATE {schema}.item
SET item_code = legacy_item_code,
    update_by_id = 'system',
    update_dtime = NOW(),
    version_nbr = version_nbr + 1
WHERE item_code IS NULL
  AND legacy_item_code IS NOT NULL
  AND legacy_item_code <> '';

ALTER TABLE {schema}.item
    ALTER COLUMN item_code SET NOT NULL;
"""


_SCHEMA_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


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


def _legacy_item_table_exists(schema_editor) -> bool:
    relation = _qualified_relation_name(
        schema_editor,
        schema=_schema_name(schema_editor),
        relation_name="item",
    )
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass(%s)", [relation])
        row = cursor.fetchone()
    return bool(row and row[0])


def _forwards(apps, schema_editor):
    if not _is_postgres(schema_editor):
        return
    if not _legacy_item_table_exists(schema_editor):
        return

    schema = _schema_name(schema_editor)
    quoted_schema = _quoted_schema(schema_editor, schema)
    schema_editor.execute(_FORWARD_SQL_TEMPLATE.format(schema=quoted_schema))


def _backwards(apps, schema_editor):
    if not _is_postgres(schema_editor):
        return
    if not _legacy_item_table_exists(schema_editor):
        return

    schema = _schema_name(schema_editor)
    quoted_schema = _quoted_schema(schema_editor, schema)
    schema_editor.execute(_REVERSE_SQL_TEMPLATE.format(schema=quoted_schema))


class Migration(migrations.Migration):
    atomic = True

    dependencies = [
        ("masterdata", "0008_catalog_governance_audit"),
    ]

    operations = [
        migrations.RunPython(_forwards, _backwards),
    ]
