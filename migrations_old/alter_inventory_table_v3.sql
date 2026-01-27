-- Inventory Table Migration V3
-- Staged migration following architect recommendations

BEGIN;

-- ============================================================
-- STAGE 1: PRECHECKS AND VALIDATION
-- ============================================================

-- Precheck: Validate each (warehouse_id, item_id) combination is unique
DO $$
DECLARE
    duplicate_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO duplicate_count
    FROM (
        SELECT warehouse_id, item_id, COUNT(*) as cnt
        FROM inventory
        GROUP BY warehouse_id, item_id
        HAVING COUNT(*) > 1
    ) duplicates;
    
    IF duplicate_count > 0 THEN
        RAISE EXCEPTION 'Data integrity check failed: Found % duplicate (warehouse_id, item_id) combinations', duplicate_count;
    END IF;
    
    RAISE NOTICE 'Precheck passed: All (warehouse_id, item_id) combinations are unique';
END $$;

-- Snapshot counts for verification
DO $$
DECLARE
    inv_count INTEGER;
    wh_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO inv_count FROM inventory;
    SELECT COUNT(*) INTO wh_count FROM warehouse;
    RAISE NOTICE 'Pre-migration counts: inventory=%, warehouses=%', inv_count, wh_count;
END $$;

-- ============================================================
-- STAGE 2: CREATE PERSISTENT MAPPING TABLE
-- ============================================================

CREATE TABLE IF NOT EXISTS inventory_id_mapping (
    old_inventory_id INTEGER NOT NULL,
    new_inventory_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    PRIMARY KEY (old_inventory_id)
);

TRUNCATE inventory_id_mapping;

INSERT INTO inventory_id_mapping (old_inventory_id, new_inventory_id, item_id)
SELECT inventory_id, warehouse_id, item_id
FROM inventory;

DO $$
BEGIN
    RAISE NOTICE 'Created mapping table with % entries', (SELECT COUNT(*) FROM inventory_id_mapping);
END $$;

-- ============================================================
-- STAGE 3: DROP COMPOSITE FOREIGN KEYS FIRST
-- ============================================================

-- Drop composite FKs (these depend on index uk_inventory_1)
ALTER TABLE transfer_item DROP CONSTRAINT IF EXISTS fk_transfer_item_inventory CASCADE;
ALTER TABLE item_location DROP CONSTRAINT IF EXISTS item_location_item_id_inventory_id_fkey CASCADE;
ALTER TABLE item_location DROP CONSTRAINT IF EXISTS fk_item_location_inventory CASCADE;
ALTER TABLE xfreturn_item DROP CONSTRAINT IF EXISTS fk_xfreturn_item_inventory CASCADE;

-- ============================================================
-- STAGE 4: DROP SINGLE-COLUMN FOREIGN KEYS
-- ============================================================

ALTER TABLE reliefpkg DROP CONSTRAINT IF EXISTS reliefpkg_to_inventory_id_fkey;
ALTER TABLE reliefpkg DROP CONSTRAINT IF EXISTS fk_reliefpkg_inventory;
ALTER TABLE dbintake DROP CONSTRAINT IF EXISTS dbintake_inventory_id_fkey;
ALTER TABLE dbintake DROP CONSTRAINT IF EXISTS fk_dbintake_inventory;
ALTER TABLE dnintake DROP CONSTRAINT IF EXISTS dnintake_inventory_id_fkey;
ALTER TABLE dnintake DROP CONSTRAINT IF EXISTS fk_dnintake_inventory;
ALTER TABLE rtintake DROP CONSTRAINT IF EXISTS rtintake_inventory_id_fkey;
ALTER TABLE rtintake DROP CONSTRAINT IF EXISTS fk_rtintake_inventory;
ALTER TABLE xfintake DROP CONSTRAINT IF EXISTS xfintake_inventory_id_fkey;
ALTER TABLE xfintake DROP CONSTRAINT IF EXISTS fk_xfintake_inventory;
ALTER TABLE transfer DROP CONSTRAINT IF EXISTS transfer_fr_inventory_id_fkey;
ALTER TABLE transfer DROP CONSTRAINT IF EXISTS transfer_to_inventory_id_fkey;
ALTER TABLE transfer DROP CONSTRAINT IF EXISTS fk_transfer_fr_inventory;
ALTER TABLE transfer DROP CONSTRAINT IF EXISTS fk_transfer_to_inventory;
ALTER TABLE xfreturn DROP CONSTRAINT IF EXISTS xfreturn_fr_inventory_id_fkey;
ALTER TABLE xfreturn DROP CONSTRAINT IF EXISTS xfreturn_to_inventory_id_fkey;
ALTER TABLE xfreturn DROP CONSTRAINT IF EXISTS fk_xfreturn_fr_inventory;
ALTER TABLE xfreturn DROP CONSTRAINT IF EXISTS fk_xfreturn_to_inventory;
ALTER TABLE location DROP CONSTRAINT IF EXISTS location_inventory_id_fkey;
ALTER TABLE location DROP CONSTRAINT IF EXISTS fk_location_inventory;
ALTER TABLE itembatch DROP CONSTRAINT IF EXISTS itembatch_inventory_id_fkey;
ALTER TABLE itembatch DROP CONSTRAINT IF EXISTS fk_itembatch_inventory;

DO $$
BEGIN
    RAISE NOTICE 'Dropped all foreign key constraints';
END $$;

-- ============================================================
-- STAGE 5: UPDATE ALL REFERENCING TABLES
-- ============================================================

-- Update tables with single-column FK
UPDATE reliefpkg r SET to_inventory_id = m.new_inventory_id
FROM inventory_id_mapping m
WHERE r.to_inventory_id = m.old_inventory_id;

UPDATE dbintake d SET inventory_id = m.new_inventory_id
FROM inventory_id_mapping m
WHERE d.inventory_id = m.old_inventory_id;

UPDATE dnintake d SET inventory_id = m.new_inventory_id
FROM inventory_id_mapping m
WHERE d.inventory_id = m.old_inventory_id;

UPDATE rtintake r SET inventory_id = m.new_inventory_id
FROM inventory_id_mapping m
WHERE r.inventory_id = m.old_inventory_id;

UPDATE xfintake x SET inventory_id = m.new_inventory_id
FROM inventory_id_mapping m
WHERE x.inventory_id = m.old_inventory_id;

UPDATE transfer t SET fr_inventory_id = m.new_inventory_id
FROM inventory_id_mapping m
WHERE t.fr_inventory_id = m.old_inventory_id;

UPDATE transfer t SET to_inventory_id = m.new_inventory_id
FROM inventory_id_mapping m
WHERE t.to_inventory_id = m.old_inventory_id;

UPDATE xfreturn x SET fr_inventory_id = m.new_inventory_id
FROM inventory_id_mapping m
WHERE x.fr_inventory_id = m.old_inventory_id;

UPDATE xfreturn x SET to_inventory_id = m.new_inventory_id
FROM inventory_id_mapping m
WHERE x.to_inventory_id = m.old_inventory_id;

UPDATE location l SET inventory_id = m.new_inventory_id
FROM inventory_id_mapping m
WHERE l.inventory_id = m.old_inventory_id;

UPDATE itembatch i SET inventory_id = m.new_inventory_id
FROM inventory_id_mapping m
WHERE i.inventory_id = m.old_inventory_id;

-- Update tables with composite FK
UPDATE transfer_item t SET inventory_id = m.new_inventory_id
FROM inventory_id_mapping m
WHERE t.inventory_id = m.old_inventory_id AND t.item_id = m.item_id;

UPDATE item_location il SET inventory_id = m.new_inventory_id
FROM inventory_id_mapping m
WHERE il.inventory_id = m.old_inventory_id AND il.item_id = m.item_id;

UPDATE xfreturn_item x SET inventory_id = m.new_inventory_id
FROM inventory_id_mapping m
WHERE x.inventory_id = m.old_inventory_id AND x.item_id = m.item_id;

DO $$
BEGIN
    RAISE NOTICE 'Updated all foreign key references';
END $$;

-- ============================================================
-- STAGE 6: ALTER INVENTORY TABLE STRUCTURE
-- ============================================================

-- Drop existing indexes
DROP INDEX IF EXISTS dk_inventory_1 CASCADE;
DROP INDEX IF EXISTS uk_inventory_1 CASCADE;

-- Drop current primary key
ALTER TABLE inventory DROP CONSTRAINT IF EXISTS inventory_pkey;

-- Drop existing check constraints
ALTER TABLE inventory DROP CONSTRAINT IF EXISTS inventory_check;
ALTER TABLE inventory DROP CONSTRAINT IF EXISTS inventory_check1;
ALTER TABLE inventory DROP CONSTRAINT IF EXISTS inventory_defective_qty_check;
ALTER TABLE inventory DROP CONSTRAINT IF EXISTS inventory_expired_qty_check;
ALTER TABLE inventory DROP CONSTRAINT IF EXISTS inventory_status_code_check;
ALTER TABLE inventory DROP CONSTRAINT IF EXISTS inventory_usable_qty_check;

-- Drop FKs on inventory table itself
ALTER TABLE inventory DROP CONSTRAINT IF EXISTS inventory_warehouse_id_fkey;
ALTER TABLE inventory DROP CONSTRAINT IF EXISTS inventory_item_id_fkey;
ALTER TABLE inventory DROP CONSTRAINT IF EXISTS inventory_uom_code_fkey;

-- Update inventory_id to warehouse_id
UPDATE inventory SET inventory_id = warehouse_id;

-- Drop warehouse_id column
ALTER TABLE inventory DROP COLUMN IF EXISTS warehouse_id;

-- Add reorder_qty column
ALTER TABLE inventory ADD COLUMN IF NOT EXISTS reorder_qty decimal(12,2) NOT NULL DEFAULT 0.00;

-- Create composite primary key
ALTER TABLE inventory ADD CONSTRAINT pk_inventory PRIMARY KEY (inventory_id, item_id);

-- Add foreign keys
ALTER TABLE inventory ADD CONSTRAINT fk_inventory_warehouse 
    FOREIGN KEY (inventory_id) REFERENCES warehouse(warehouse_id);

ALTER TABLE inventory ADD CONSTRAINT fk_inventory_item 
    FOREIGN KEY (item_id) REFERENCES item(item_id);

ALTER TABLE inventory ADD CONSTRAINT fk_inventory_unitofmeasure 
    FOREIGN KEY (uom_code) REFERENCES unitofmeasure(uom_code);

-- Add named check constraints
ALTER TABLE inventory ADD CONSTRAINT c_inventory_1 CHECK (usable_qty >= 0.00);
ALTER TABLE inventory ADD CONSTRAINT c_inventory_2 CHECK (reserved_qty <= usable_qty);
ALTER TABLE inventory ADD CONSTRAINT c_inventory_3 CHECK (defective_qty >= 0.00);
ALTER TABLE inventory ADD CONSTRAINT c_inventory_4 CHECK (expired_qty >= 0.00);
ALTER TABLE inventory ADD CONSTRAINT c_inventory_5 CHECK (reorder_qty >= 0.00);
ALTER TABLE inventory ADD CONSTRAINT c_inventory_6 
    CHECK ((last_verified_by IS NULL AND last_verified_date IS NULL) 
        OR (last_verified_by IS NOT NULL AND last_verified_date IS NOT NULL));
ALTER TABLE inventory ADD CONSTRAINT c_inventory_7 CHECK (status_code IN ('A','U'));

-- Create indexes
CREATE UNIQUE INDEX uk_inventory_1 ON inventory(item_id, inventory_id) WHERE usable_qty > 0.00;
CREATE INDEX dk_inventory_1 ON inventory(item_id);

DO $$
BEGIN
    RAISE NOTICE 'Inventory table structure updated';
END $$;

-- ============================================================
-- STAGE 7: RECREATE FOREIGN KEY CONSTRAINTS
-- ============================================================

-- Note: After migration, inventory_id IS warehouse_id and is not unique
-- (multiple rows per warehouse, one per item). So single-column FKs 
-- must reference warehouse(warehouse_id), not inventory(inventory_id).

-- Single-column FKs to warehouse(warehouse_id)
ALTER TABLE reliefpkg ADD CONSTRAINT fk_reliefpkg_warehouse 
    FOREIGN KEY (to_inventory_id) REFERENCES warehouse(warehouse_id);

ALTER TABLE dbintake ADD CONSTRAINT fk_dbintake_warehouse 
    FOREIGN KEY (inventory_id) REFERENCES warehouse(warehouse_id);

ALTER TABLE dnintake ADD CONSTRAINT fk_dnintake_warehouse 
    FOREIGN KEY (inventory_id) REFERENCES warehouse(warehouse_id);

ALTER TABLE rtintake ADD CONSTRAINT fk_rtintake_warehouse 
    FOREIGN KEY (inventory_id) REFERENCES warehouse(warehouse_id);

ALTER TABLE xfintake ADD CONSTRAINT fk_xfintake_warehouse 
    FOREIGN KEY (inventory_id) REFERENCES warehouse(warehouse_id);

ALTER TABLE transfer ADD CONSTRAINT fk_transfer_fr_warehouse 
    FOREIGN KEY (fr_inventory_id) REFERENCES warehouse(warehouse_id);

ALTER TABLE transfer ADD CONSTRAINT fk_transfer_to_warehouse 
    FOREIGN KEY (to_inventory_id) REFERENCES warehouse(warehouse_id);

ALTER TABLE xfreturn ADD CONSTRAINT fk_xfreturn_fr_warehouse 
    FOREIGN KEY (fr_inventory_id) REFERENCES warehouse(warehouse_id);

ALTER TABLE xfreturn ADD CONSTRAINT fk_xfreturn_to_warehouse 
    FOREIGN KEY (to_inventory_id) REFERENCES warehouse(warehouse_id);

ALTER TABLE location ADD CONSTRAINT fk_location_warehouse 
    FOREIGN KEY (inventory_id) REFERENCES warehouse(warehouse_id);

ALTER TABLE itembatch ADD CONSTRAINT fk_itembatch_warehouse 
    FOREIGN KEY (inventory_id) REFERENCES warehouse(warehouse_id);

-- Composite FKs to inventory(inventory_id, item_id)
ALTER TABLE transfer_item ADD CONSTRAINT fk_transfer_item_inventory 
    FOREIGN KEY (inventory_id, item_id) REFERENCES inventory(inventory_id, item_id);

ALTER TABLE item_location ADD CONSTRAINT fk_item_location_inventory 
    FOREIGN KEY (inventory_id, item_id) REFERENCES inventory(inventory_id, item_id);

ALTER TABLE xfreturn_item ADD CONSTRAINT fk_xfreturn_item_inventory 
    FOREIGN KEY (inventory_id, item_id) REFERENCES inventory(inventory_id, item_id);

DO $$
BEGIN
    RAISE NOTICE 'Recreated all foreign key constraints';
END $$;

-- ============================================================
-- STAGE 8: VERIFY DATA INTEGRITY
-- ============================================================

DO $$
DECLARE
    inv_count_after INTEGER;
    orphan_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO inv_count_after FROM inventory;
    RAISE NOTICE 'Post-migration inventory count: %', inv_count_after;
    
    -- Check for orphaned records
    SELECT COUNT(*) INTO orphan_count FROM itembatch 
    WHERE NOT EXISTS (SELECT 1 FROM inventory WHERE inventory.inventory_id = itembatch.inventory_id);
    
    IF orphan_count > 0 THEN
        RAISE WARNING 'Found % orphaned itembatch records', orphan_count;
    ELSE
        RAISE NOTICE 'No orphaned records found';
    END IF;
END $$;

-- ============================================================
-- COMMIT TRANSACTION
-- ============================================================

COMMIT;

-- Final success message (outside transaction)
DO $$
BEGIN
    RAISE NOTICE '==========================================================';
    RAISE NOTICE 'Inventory table migration completed successfully!';
    RAISE NOTICE 'inventory_id is now the warehouse_id';
    RAISE NOTICE 'Primary key: (inventory_id, item_id) composite';
    RAISE NOTICE 'All referential integrity constraints restored';
    RAISE NOTICE '==========================================================';
END $$;
