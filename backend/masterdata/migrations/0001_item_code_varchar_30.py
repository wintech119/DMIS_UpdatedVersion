from django.db import migrations


class Migration(migrations.Migration):
    atomic = True

    dependencies = []

    operations = [
        migrations.RunSQL(
            sql="""
                -- Drop dependent view before altering referenced column type.
                DROP VIEW IF EXISTS public.v_stock_status;

                -- Step 1: Drop the existing uppercase check constraint
                ALTER TABLE item DROP CONSTRAINT IF EXISTS c_item_1a;

                -- Step 2: Widen the column (safe: widening VARCHAR never truncates)
                ALTER TABLE item ALTER COLUMN item_code TYPE VARCHAR(30);

                -- Step 3: Recreate uppercase check constraint
                ALTER TABLE item ADD CONSTRAINT c_item_1a
                    CHECK (item_code = UPPER(item_code));

                -- Recreate dependent view.
                CREATE VIEW public.v_stock_status AS
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
                FROM warehouse w
                CROSS JOIN item i
                LEFT JOIN inventory inv
                    ON inv.item_id = i.item_id
                    AND inv.inventory_id = w.warehouse_id
                WHERE w.status_code = 'A'::bpchar
                  AND i.status_code = 'A'::bpchar;
            """,
            reverse_sql="""
                DROP VIEW IF EXISTS public.v_stock_status;

                -- Rollback: narrow back to 16 only when safe
                ALTER TABLE item DROP CONSTRAINT IF EXISTS c_item_1a;

                -- Refuse rollback if data would be truncated
                DO $$
                BEGIN
                    IF EXISTS (SELECT 1 FROM item WHERE LENGTH(item_code) > 16) THEN
                        RAISE EXCEPTION
                            'Cannot reverse migration: item_code values exist that exceed 16 characters.';
                    END IF;
                END $$;

                ALTER TABLE item ALTER COLUMN item_code TYPE VARCHAR(16);
                ALTER TABLE item ADD CONSTRAINT c_item_1a
                    CHECK (item_code = UPPER(item_code));

                CREATE VIEW public.v_stock_status AS
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
                FROM warehouse w
                CROSS JOIN item i
                LEFT JOIN inventory inv
                    ON inv.item_id = i.item_id
                    AND inv.inventory_id = w.warehouse_id
                WHERE w.status_code = 'A'::bpchar
                  AND i.status_code = 'A'::bpchar;
            """,
        ),
    ]
