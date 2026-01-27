-- Inventory Table Migration
-- Changes: 
-- 1. Add reorder_qty column
-- 2. Change primary key from (inventory_id) to (inventory_id, item_id)
-- 3. Remove warehouse_id column
-- 4. Rename constraints to DRIMS naming standards
-- 5. Update indexes

-- Safety check: Ensure inventory_id = warehouse_id
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM inventory WHERE inventory_id != warehouse_id) THEN
        RAISE EXCEPTION 'Data integrity check failed: inventory_id must equal warehouse_id';
    END IF;
END $$;

-- Step 1: Drop all dependent foreign key constraints
ALTER TABLE reliefpkg DROP CONSTRAINT IF EXISTS reliefpkg_to_inventory_id_fkey;
ALTER TABLE dbintake DROP CONSTRAINT IF EXISTS dbintake_inventory_id_fkey;
ALTER TABLE dnintake DROP CONSTRAINT IF EXISTS dnintake_inventory_id_fkey;
ALTER TABLE rtintake DROP CONSTRAINT IF EXISTS rtintake_inventory_id_fkey;
ALTER TABLE xfintake DROP CONSTRAINT IF EXISTS xfintake_inventory_id_fkey;
ALTER TABLE transfer DROP CONSTRAINT IF EXISTS transfer_fr_inventory_id_fkey;
ALTER TABLE transfer DROP CONSTRAINT IF EXISTS transfer_to_inventory_id_fkey;
ALTER TABLE xfreturn DROP CONSTRAINT IF EXISTS xfreturn_fr_inventory_id_fkey;
ALTER TABLE xfreturn DROP CONSTRAINT IF EXISTS xfreturn_to_inventory_id_fkey;
ALTER TABLE location DROP CONSTRAINT IF EXISTS location_inventory_id_fkey;
ALTER TABLE itembatch DROP CONSTRAINT IF EXISTS itembatch_inventory_id_fkey;
ALTER TABLE transfer_item DROP CONSTRAINT IF EXISTS transfer_item_inventory_id_item_id_fkey;
ALTER TABLE transfer_item DROP CONSTRAINT IF EXISTS transfer_item_inventory_id_fkey;
ALTER TABLE item_location DROP CONSTRAINT IF EXISTS item_location_inventory_id_item_id_fkey;
ALTER TABLE item_location DROP CONSTRAINT IF EXISTS item_location_inventory_id_fkey;
ALTER TABLE xfreturn_item DROP CONSTRAINT IF EXISTS xfreturn_item_inventory_id_fkey;

-- Step 2: Drop existing indexes
DROP INDEX IF EXISTS dk_inventory_1;
DROP INDEX IF EXISTS uk_inventory_1;

-- Step 3: Drop current primary key constraint
ALTER TABLE inventory DROP CONSTRAINT IF EXISTS inventory_pkey;

-- Step 4: Drop warehouse_id column and its foreign key
ALTER TABLE inventory DROP CONSTRAINT IF EXISTS inventory_warehouse_id_fkey;
ALTER TABLE inventory DROP COLUMN IF EXISTS warehouse_id;

-- Step 5: Add reorder_qty column
ALTER TABLE inventory ADD COLUMN IF NOT EXISTS reorder_qty decimal(12,2) NOT NULL DEFAULT 0.00;

-- Step 6: Drop existing check constraints
ALTER TABLE inventory DROP CONSTRAINT IF EXISTS inventory_check;
ALTER TABLE inventory DROP CONSTRAINT IF EXISTS inventory_check1;
ALTER TABLE inventory DROP CONSTRAINT IF EXISTS inventory_defective_qty_check;
ALTER TABLE inventory DROP CONSTRAINT IF EXISTS inventory_expired_qty_check;
ALTER TABLE inventory DROP CONSTRAINT IF EXISTS inventory_status_code_check;
ALTER TABLE inventory DROP CONSTRAINT IF EXISTS inventory_usable_qty_check;

-- Step 7: Drop existing foreign keys on inventory table
ALTER TABLE inventory DROP CONSTRAINT IF EXISTS inventory_item_id_fkey;
ALTER TABLE inventory DROP CONSTRAINT IF EXISTS inventory_uom_code_fkey;

-- Step 8: Create new primary key (composite)
ALTER TABLE inventory ADD CONSTRAINT pk_inventory PRIMARY KEY (inventory_id, item_id);

-- Step 9: Add foreign key from inventory_id to warehouse (inventory_id IS the warehouse_id)
ALTER TABLE inventory ADD CONSTRAINT fk_inventory_warehouse 
    FOREIGN KEY (inventory_id) REFERENCES warehouse(warehouse_id);

-- Step 10: Add foreign key from item_id to item
ALTER TABLE inventory ADD CONSTRAINT fk_inventory_item 
    FOREIGN KEY (item_id) REFERENCES item(item_id);

-- Step 11: Add foreign key from uom_code to unitofmeasure
ALTER TABLE inventory ADD CONSTRAINT fk_inventory_unitofmeasure 
    FOREIGN KEY (uom_code) REFERENCES unitofmeasure(uom_code);

-- Step 12: Add all named check constraints
ALTER TABLE inventory ADD CONSTRAINT c_inventory_1 
    CHECK (usable_qty >= 0.00);

ALTER TABLE inventory ADD CONSTRAINT c_inventory_2 
    CHECK (reserved_qty <= usable_qty);

ALTER TABLE inventory ADD CONSTRAINT c_inventory_3 
    CHECK (defective_qty >= 0.00);

ALTER TABLE inventory ADD CONSTRAINT c_inventory_4 
    CHECK (expired_qty >= 0.00);

ALTER TABLE inventory ADD CONSTRAINT c_inventory_5 
    CHECK (reorder_qty >= 0.00);

ALTER TABLE inventory ADD CONSTRAINT c_inventory_6 
    CHECK ((last_verified_by IS NULL AND last_verified_date IS NULL) 
        OR (last_verified_by IS NOT NULL AND last_verified_date IS NOT NULL));

ALTER TABLE inventory ADD CONSTRAINT c_inventory_7 
    CHECK (status_code IN ('A','U'));

-- Step 13: Create indexes
-- Unique index for checking if there is any usable item across inventory
CREATE UNIQUE INDEX uk_inventory_1 ON inventory(item_id, inventory_id) WHERE usable_qty > 0.00;

-- Duplicate index on inventory to optimize join with item
CREATE INDEX dk_inventory_1 ON inventory(item_id);

-- Step 14: Recreate foreign key constraints on dependent tables
-- Single column FK to inventory_id only
ALTER TABLE reliefpkg ADD CONSTRAINT fk_reliefpkg_inventory 
    FOREIGN KEY (to_inventory_id) REFERENCES inventory(inventory_id);

ALTER TABLE dbintake ADD CONSTRAINT fk_dbintake_inventory 
    FOREIGN KEY (inventory_id) REFERENCES inventory(inventory_id);

ALTER TABLE dnintake ADD CONSTRAINT fk_dnintake_inventory 
    FOREIGN KEY (inventory_id) REFERENCES inventory(inventory_id);

ALTER TABLE rtintake ADD CONSTRAINT fk_rtintake_inventory 
    FOREIGN KEY (inventory_id) REFERENCES inventory(inventory_id);

ALTER TABLE xfintake ADD CONSTRAINT fk_xfintake_inventory 
    FOREIGN KEY (inventory_id) REFERENCES inventory(inventory_id);

ALTER TABLE transfer ADD CONSTRAINT fk_transfer_fr_inventory 
    FOREIGN KEY (fr_inventory_id) REFERENCES inventory(inventory_id);

ALTER TABLE transfer ADD CONSTRAINT fk_transfer_to_inventory 
    FOREIGN KEY (to_inventory_id) REFERENCES inventory(inventory_id);

ALTER TABLE xfreturn ADD CONSTRAINT fk_xfreturn_fr_inventory 
    FOREIGN KEY (fr_inventory_id) REFERENCES inventory(inventory_id);

ALTER TABLE xfreturn ADD CONSTRAINT fk_xfreturn_to_inventory 
    FOREIGN KEY (to_inventory_id) REFERENCES inventory(inventory_id);

ALTER TABLE location ADD CONSTRAINT fk_location_inventory 
    FOREIGN KEY (inventory_id) REFERENCES inventory(inventory_id);

ALTER TABLE itembatch ADD CONSTRAINT fk_itembatch_inventory 
    FOREIGN KEY (inventory_id) REFERENCES inventory(inventory_id);

-- Composite FK to inventory(inventory_id, item_id)
ALTER TABLE transfer_item ADD CONSTRAINT fk_transfer_item_inventory 
    FOREIGN KEY (inventory_id, item_id) REFERENCES inventory(inventory_id, item_id);

ALTER TABLE item_location ADD CONSTRAINT fk_item_location_inventory 
    FOREIGN KEY (inventory_id, item_id) REFERENCES inventory(inventory_id, item_id);

ALTER TABLE xfreturn_item ADD CONSTRAINT fk_xfreturn_item_inventory 
    FOREIGN KEY (inventory_id, item_id) REFERENCES inventory(inventory_id, item_id);

-- Success message
DO $$
BEGIN
    RAISE NOTICE 'Inventory table migration completed successfully';
END $$;
