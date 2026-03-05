import os
import re

from django.db import migrations


_FORWARD_SQL_TEMPLATE = """
    -- Drop dependent view before altering referenced column type.
    DROP VIEW IF EXISTS {schema}.v_stock_status;

    -- Step 1: Drop the existing uppercase check constraint
    ALTER TABLE {schema}.item DROP CONSTRAINT IF EXISTS c_item_1a;

    -- Step 2: Widen the column (safe: widening VARCHAR never truncates)
    ALTER TABLE {schema}.item ALTER COLUMN item_code TYPE VARCHAR(30);

    -- Step 3: Recreate uppercase check constraint
    ALTER TABLE {schema}.item ADD CONSTRAINT c_item_1a
        CHECK (item_code = UPPER(item_code));

    -- Recreate dependent view.
    CREATE VIEW {schema}.v_stock_status AS
    SELECT
        w.warehouse_id,
        w.warehouse_name,
        w.warehouse_type,
        i.item_id,
        i.item_code,
        i.item_name,
        i.criticality_level,
        COALESCE(inv.usable_qty, 0::numeric) AS available_stock,
        COALESCE(inv.reserved_qty, 0::numeric) AS reserved_qty,
        COALESCE(i.min_stock_threshold, w.min_stock_threshold, 0::numeric) AS min_threshold,
        COALESCE(inv.usable_qty, 0::numeric) - COALESCE(i.min_stock_threshold, w.min_stock_threshold, 0::numeric) AS surplus_qty,
        w.last_sync_dtime,
        w.sync_status,
        CASE
            WHEN w.last_sync_dtime IS NULL THEN 'UNKNOWN'::text
            WHEN w.last_sync_dtime > (NOW() - INTERVAL '2 hours') THEN 'HIGH'::text
            WHEN w.last_sync_dtime > (NOW() - INTERVAL '6 hours') THEN 'MEDIUM'::text
            ELSE 'LOW'::text
        END AS data_freshness
    FROM {schema}.warehouse w
    CROSS JOIN {schema}.item i
    LEFT JOIN {schema}.inventory inv
        ON inv.item_id = i.item_id
        AND inv.inventory_id = w.warehouse_id
    WHERE w.status_code = 'A'::bpchar
      AND i.status_code = 'A'::bpchar;
"""


_REVERSE_SQL_TEMPLATE = """
    DROP VIEW IF EXISTS {schema}.v_stock_status;

    -- Rollback: narrow back to 16 only when safe
    ALTER TABLE {schema}.item DROP CONSTRAINT IF EXISTS c_item_1a;

    -- Refuse rollback if data would be truncated
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM {schema}.item WHERE LENGTH(item_code) > 16) THEN
            RAISE EXCEPTION
                'Cannot reverse migration: item_code values exist that exceed 16 characters.';
        END IF;
    END $$;

    ALTER TABLE {schema}.item ALTER COLUMN item_code TYPE VARCHAR(16);
    ALTER TABLE {schema}.item ADD CONSTRAINT c_item_1a
        CHECK (item_code = UPPER(item_code));

    CREATE VIEW {schema}.v_stock_status AS
    SELECT
        w.warehouse_id,
        w.warehouse_name,
        w.warehouse_type,
        i.item_id,
        i.item_code,
        i.item_name,
        i.criticality_level,
        COALESCE(inv.usable_qty, 0::numeric) AS available_stock,
        COALESCE(inv.reserved_qty, 0::numeric) AS reserved_qty,
        COALESCE(i.min_stock_threshold, w.min_stock_threshold, 0::numeric) AS min_threshold,
        COALESCE(inv.usable_qty, 0::numeric) - COALESCE(i.min_stock_threshold, w.min_stock_threshold, 0::numeric) AS surplus_qty,
        w.last_sync_dtime,
        w.sync_status,
        CASE
            WHEN w.last_sync_dtime IS NULL THEN 'UNKNOWN'::text
            WHEN w.last_sync_dtime > (NOW() - INTERVAL '2 hours') THEN 'HIGH'::text
            WHEN w.last_sync_dtime > (NOW() - INTERVAL '6 hours') THEN 'MEDIUM'::text
            ELSE 'LOW'::text
        END AS data_freshness
    FROM {schema}.warehouse w
    CROSS JOIN {schema}.item i
    LEFT JOIN {schema}.inventory inv
        ON inv.item_id = i.item_id
        AND inv.inventory_id = w.warehouse_id
    WHERE w.status_code = 'A'::bpchar
      AND i.status_code = 'A'::bpchar;
"""


def _is_postgres(schema_editor) -> bool:
    return schema_editor.connection.vendor == "postgresql"


def _schema_name() -> str:
    schema = os.getenv("DMIS_DB_SCHEMA", "public")
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema):
        return schema
    return "public"


def _legacy_item_table_exists(schema_editor) -> bool:
    relation = f"{_schema_name()}.item"
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass(%s)", [relation])
        row = cursor.fetchone()
    return bool(row and row[0])


def _forwards(apps, schema_editor):
    # Local/test sqlite runs and fresh DBs may not have the legacy table/view.
    if not _is_postgres(schema_editor):
        return
    if not _legacy_item_table_exists(schema_editor):
        return
    schema = _schema_name()
    schema_editor.execute(_FORWARD_SQL_TEMPLATE.format(schema=schema))


def _backwards(apps, schema_editor):
    if not _is_postgres(schema_editor):
        return
    if not _legacy_item_table_exists(schema_editor):
        return
    schema = _schema_name()
    schema_editor.execute(_REVERSE_SQL_TEMPLATE.format(schema=schema))


class Migration(migrations.Migration):
    atomic = True

    dependencies = []

    operations = [
        migrations.RunPython(_forwards, _backwards),
    ]
