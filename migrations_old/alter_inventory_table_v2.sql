-- Inventory Table Migration V2
-- Changes inventory_id to warehouse_id and creates composite PK

BEGIN;

-- Step 1: Create a temporary mapping table for old to new inventory_id
CREATE TEMP TABLE inventory_id_mapping AS
SELECT 
    inventory_id as old_inventory_id,
    warehouse_id as new_inventory_id,
    item_id
FROM inventory;

-- Step 2: Drop all dependent foreign key constraints
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

-- Step 3: Update all foreign key references in dependent tables
UPDATE reliefpkg SET to_inventory_id = m.new_inventory_id
FROM inventory_id_mapping m
WHERE reliefpkg.to_inventory_id = m.old_inventory_id;

UPDATE dbintake SET inventory_id = m.new_inventory_id
FROM inventory_id_mapping m  
WHERE dbintake.inventory_id = m.old_inventory_id;

UPDATE dnintake SET inventory_id = m.new_inventory_id
FROM inventory_id_mapping m
WHERE dnintake.inventory_id = m.old_inventory_id;

UPDATE rtintake SET inventory_id = m.new_inventory_id
FROM inventory_id_mapping m
WHERE rtintake.inventory_id = m.old_inventory_id;

UPDATE xfintake SET inventory_id = m.new_inventory_id
FROM inventory_id_mapping m
WHERE xfintake.inventory_id = m.old_inventory_id;

UPDATE transfer SET fr_inventory_id = m.new_inventory_id
FROM inventory_id_mapping m
WHERE transfer.fr_inventory_id = m.old_inventory_id;

UPDATE transfer SET to_inventory_id = m.new_inventory_id
FROM inventory_id_mapping m
WHERE transfer.to_inventory_id = m.old_inventory_id;

UPDATE xfreturn SET fr_inventory_id = m.new_inventory_id
FROM inventory_id_mapping m
WHERE xfreturn.fr_inventory_id = m.old_inventory_id;

UPDATE xfreturn SET to_inventory_id = m.new_inventory_id
FROM inventory_id_mapping m
WHERE xfreturn.to_inventory_id = m.old_inventory_id;

UPDATE location SET inventory_id = m.new_inventory_id
FROM inventory_id_mapping m
WHERE location.inventory_id = m.old_inventory_id;

UPDATE itembatch SET inventory_id = m.new_inventory_id
FROM inventory_id_mapping m
WHERE itembatch.inventory_id = m.old_inventory_id;

UPDATE transfer_item SET inventory_id = m.new_inventory_id
FROM inventory_id_mapping m
WHERE transfer_item.inventory_id = m.old_inventory_id;

UPDATE item_location SET inventory_id = m.new_inventory_id
FROM inventory_id_mapping m
WHERE item_location.inventory_id = m.old_inventory_id;

UPDATE xfreturn_item SET inventory_id = m.new_inventory_id
FROM inventory_id_mapping m
WHERE xfreturn_item.inventory_id = m.old_inventory_id;

-- Step 4: Drop existing indexes
DROP INDEX IF EXISTS dk_inventory_1;
DROP INDEX IF EXISTS uk_inventory_1;

-- Step 5: Drop current primary key constraint
ALTER TABLE inventory DROP CONSTRAINT IF EXISTS inventory_pkey;

-- Step 6: Update inventory_id to warehouse_id
UPDATE inventory SET inventory_id = warehouse_id;

-- Step 7: Drop warehouse_id column and its foreign key
ALTER TABLE inventory DROP CONSTRAINT IF EXISTS inventory_warehouse_id_fkey;
ALTER TABLE inventory DROP COLUMN IF EXISTS warehouse_id;

-- Step 8: Add reorder_qty column
ALTER TABLE inventory ADD COLUMN IF NOT EXISTS reorder_qty decimal(12,2) NOT NULL DEFAULT 0.00;

-- Step 9: Drop existing check constraints
ALTER TABLE inventory DROP CONSTRAINT IF EXISTS inventory_check;
ALTER TABLE inventory DROP CONSTRAINT IF EXISTS inventory_check1;
ALTER TABLE inventory DROP CONSTRAINT IF EXISTS inventory_defective_qty_check;
ALTER TABLE inventory DROP CONSTRAINT IF EXISTS inventory_expired_qty_check;
ALTER TABLE inventory DROP CONSTRAINT IF EXISTS inventory_status_code_check;
ALTER TABLE inventory DROP CONSTRAINT IF EXISTS inventory_usable_qty_check;

-- Step 10: Drop existing foreign keys on inventory table
ALTER TABLE inventory DROP CONSTRAINT IF EXISTS inventory_item_id_fkey;
ALTER TABLE inventory DROP CONSTRAINT IF EXISTS inventory_uom_code_fkey;

-- Step 11: Create new composite primary key
ALTER TABLE inventory ADD CONSTRAINT pk_inventory PRIMARY KEY (inventory_id, item_id);

-- Step 12: Add foreign key from inventory_id to warehouse
ALTER TABLE inventory ADD CONSTRAINT fk_inventory_warehouse 
    FOREIGN KEY (inventory_id) REFERENCES warehouse(warehouse_id);

-- Step 13: Add foreign key from item_id to item
ALTER TABLE inventory ADD CONSTRAINT fk_inventory_item 
    FOREIGN KEY (item_id) REFERENCES item(item_id);

-- Step 14: Add foreign key from uom_code to unitofmeasure
ALTER TABLE inventory ADD CONSTRAINT fk_inventory_unitofmeasure 
    FOREIGN KEY (uom_code) REFERENCES unitofmeasure(uom_code);

-- Step 15: Add all named check constraints
ALTER TABLE inventory ADD CONSTRAINT c_inventory_1 CHECK (usable_qty >= 0.00);
ALTER TABLE inventory ADD CONSTRAINT c_inventory_2 CHECK (reserved_qty <= usable_qty);
ALTER TABLE inventory ADD CONSTRAINT c_inventory_3 CHECK (defective_qty >= 0.00);
ALTER TABLE inventory ADD CONSTRAINT c_inventory_4 CHECK (expired_qty >= 0.00);
ALTER TABLE inventory ADD CONSTRAINT c_inventory_5 CHECK (reorder_qty >= 0.00);
ALTER TABLE inventory ADD CONSTRAINT c_inventory_6 
    CHECK ((last_verified_by IS NULL AND last_verified_date IS NULL) 
        OR (last_verified_by IS NOT NULL AND last_verified_date IS NOT NULL));
ALTER TABLE inventory ADD CONSTRAINT c_inventory_7 CHECK (status_code IN ('A','U'));

-- Step 16: Create indexes
CREATE UNIQUE INDEX uk_inventory_1 ON inventory(item_id, inventory_id) WHERE usable_qty > 0.00;
CREATE INDEX dk_inventory_1 ON inventory(item_id);

-- Step 17: Recreate foreign key constraints on dependent tables
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

COMMIT;

-- Success message
DO $$
BEGIN
    RAISE NOTICE 'Inventory table migration completed successfully';
    RAISE NOTICE 'inventory_id is now the warehouse_id with composite PK (inventory_id, item_id)';
END $$;
