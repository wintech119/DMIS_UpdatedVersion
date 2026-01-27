-- ============================================================================
-- HADR Inventory & ItemBatch Seeding Script
-- ============================================================================
-- Purpose: Safely populate inventory and itembatch tables from existing
--          transaction data imported from HADR Excel
-- 
-- Constraints:
--   - Does NOT modify database schema
--   - Does NOT delete or update existing data
--   - Only INSERTs new rows where none exist
--   - All seeded rows are marked with 'Seeded from HADR import' for rollback
--
-- Tables affected: inventory, itembatch (INSERT only)
-- ============================================================================

BEGIN;

-- ============================================================================
-- Step 1: Create temporary aggregate table with net stock per (warehouse, item)
-- ============================================================================
CREATE TEMP TABLE hadr_net_stock AS
SELECT 
    t.warehouse_id,
    t.item_id,
    i.default_uom_code,
    COALESCE(SUM(CASE WHEN t.ttype = 'IN' THEN t.qty ELSE 0 END), 0) AS total_in,
    COALESCE(SUM(CASE WHEN t.ttype = 'OUT' THEN t.qty ELSE 0 END), 0) AS total_out,
    COALESCE(SUM(CASE WHEN t.ttype = 'IN' THEN t.qty ELSE 0 END), 0) - 
    COALESCE(SUM(CASE WHEN t.ttype = 'OUT' THEN t.qty ELSE 0 END), 0) AS net_qty
FROM "transaction" t
JOIN item i ON t.item_id = i.item_id
WHERE t.warehouse_id IS NOT NULL
  AND t.item_id IS NOT NULL
GROUP BY t.warehouse_id, t.item_id, i.default_uom_code
HAVING (
    COALESCE(SUM(CASE WHEN t.ttype = 'IN' THEN t.qty ELSE 0 END), 0) - 
    COALESCE(SUM(CASE WHEN t.ttype = 'OUT' THEN t.qty ELSE 0 END), 0)
) > 0;

-- Verify aggregate data (for debugging - can be removed in production)
-- SELECT COUNT(*) AS items_with_positive_stock FROM hadr_net_stock;

-- ============================================================================
-- Step 2: Insert into inventory table
-- ============================================================================
-- Primary key is composite: (inventory_id, item_id)
-- inventory_id = warehouse_id (per the model design)
-- Only insert where no matching row exists
-- ============================================================================
INSERT INTO inventory (
    inventory_id,
    item_id,
    usable_qty,
    reserved_qty,
    defective_qty,
    expired_qty,
    uom_code,
    reorder_qty,
    last_verified_by,
    last_verified_date,
    status_code,
    comments_text,
    create_by_id,
    create_dtime,
    update_by_id,
    update_dtime,
    version_nbr
)
SELECT 
    ns.warehouse_id AS inventory_id,
    ns.item_id,
    ns.net_qty AS usable_qty,
    0.00 AS reserved_qty,
    0.00 AS defective_qty,
    0.00 AS expired_qty,
    ns.default_uom_code AS uom_code,
    0.00 AS reorder_qty,
    NULL AS last_verified_by,
    NULL AS last_verified_date,
    'A' AS status_code,
    'Seeded from HADR import' AS comments_text,
    'SYSTEM' AS create_by_id,
    NOW() AS create_dtime,
    'SYSTEM' AS update_by_id,
    NOW() AS update_dtime,
    1 AS version_nbr
FROM hadr_net_stock ns
WHERE NOT EXISTS (
    SELECT 1 
    FROM inventory inv 
    WHERE inv.inventory_id = ns.warehouse_id 
      AND inv.item_id = ns.item_id
);

-- ============================================================================
-- Step 3: Insert into itembatch table
-- ============================================================================
-- Primary key is batch_id (serial/sequence)
-- One synthetic batch per (warehouse_id, item_id) where inventory was created
-- Only insert where no matching batch exists for that inventory_id + item_id
-- ============================================================================
INSERT INTO itembatch (
    batch_id,
    inventory_id,
    item_id,
    batch_no,
    batch_date,
    expiry_date,
    usable_qty,
    reserved_qty,
    defective_qty,
    expired_qty,
    uom_code,
    size_spec,
    avg_unit_value,
    last_verified_by,
    last_verified_date,
    status_code,
    comments_text,
    create_by_id,
    create_dtime,
    update_by_id,
    update_dtime,
    version_nbr
)
SELECT 
    nextval('itembatch_batch_id_seq') AS batch_id,
    ns.warehouse_id AS inventory_id,
    ns.item_id,
    'HADR-' || ns.warehouse_id || '-' || ns.item_id AS batch_no,
    CURRENT_DATE AS batch_date,
    NULL AS expiry_date,
    ns.net_qty AS usable_qty,
    0.00 AS reserved_qty,
    0.00 AS defective_qty,
    0.00 AS expired_qty,
    ns.default_uom_code AS uom_code,
    NULL AS size_spec,
    0.00 AS avg_unit_value,
    NULL AS last_verified_by,
    NULL AS last_verified_date,
    'A' AS status_code,
    'Seeded from HADR import' AS comments_text,
    'SYSTEM' AS create_by_id,
    NOW() AS create_dtime,
    'SYSTEM' AS update_by_id,
    NOW() AS update_dtime,
    1 AS version_nbr
FROM hadr_net_stock ns
WHERE NOT EXISTS (
    SELECT 1 
    FROM itembatch ib 
    WHERE ib.inventory_id = ns.warehouse_id 
      AND ib.item_id = ns.item_id
);

-- ============================================================================
-- Step 4: Cleanup temporary table
-- ============================================================================
DROP TABLE IF EXISTS hadr_net_stock;

-- ============================================================================
-- Step 5: Verification queries (optional - comment out for production)
-- ============================================================================
-- SELECT 'Inventory rows created:' AS metric, COUNT(*) AS count 
-- FROM inventory WHERE comments_text = 'Seeded from HADR import';
-- 
-- SELECT 'ItemBatch rows created:' AS metric, COUNT(*) AS count 
-- FROM itembatch WHERE comments_text = 'Seeded from HADR import';

COMMIT;

-- ============================================================================
-- ROLLBACK SNIPPET (run manually if you need to undo this seeding)
-- ============================================================================
-- WARNING: Only run this if you need to completely remove HADR seeded data
-- 
-- BEGIN;
-- DELETE FROM itembatch WHERE comments_text = 'Seeded from HADR import';
-- DELETE FROM inventory WHERE comments_text = 'Seeded from HADR import';
-- COMMIT;
-- ============================================================================
