-- Migration: Drop and replace donation_item table while retaining referential integrity
-- Date: 2025-11-17
-- Purpose: 
--   1. Drop existing donation_item table
--   2. Create new donation_item table with standardized constraint names
--   3. Re-establish foreign key from dnintake_item
--   4. Ensure all referential integrity is maintained

BEGIN;

-- Step 1: Drop foreign key constraint from dnintake_item that references donation_item
-- This prevents cascade issues and allows us to control the recreation
ALTER TABLE dnintake_item 
DROP CONSTRAINT IF EXISTS fk_dnintake_item_donation_item;

-- Step 2: Drop the existing donation_item table
-- This will remove all data (currently 0 records)
DROP TABLE IF EXISTS donation_item CASCADE;

-- Step 3: Create new donation_item table with standardized constraint names
CREATE TABLE donation_item
(
    donation_id INTEGER NOT NULL
        CONSTRAINT fk_donation_item_donation REFERENCES donation(donation_id),
    item_id INTEGER NOT NULL
        CONSTRAINT fk_donation_item_item REFERENCES item(item_id),
    
    -- Quantity/amount of items received
    item_qty DECIMAL(12,2) NOT NULL
        CONSTRAINT c_donation_item_1 CHECK (item_qty >= 0.00),

    -- Actual units in which quantity of item received is measured
    uom_code VARCHAR(25) NOT NULL
        CONSTRAINT fk_donation_item_unitofmeasure REFERENCES unitofmeasure(uom_code),

    -- Place at which consignment is located (bank, address, name of entity)
    location_name TEXT NOT NULL,

    status_code CHAR(1) NOT NULL
        -- P=Pending verification, V=Verified
        CONSTRAINT c_donation_item_2 CHECK (status_code IN ('P','V')),

    -- Any comments on item donated
    comments_text TEXT,
        
    create_by_id VARCHAR(20) NOT NULL,
    create_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    verify_by_id VARCHAR(20) NOT NULL,
    verify_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    version_nbr INTEGER NOT NULL,

    CONSTRAINT pk_donation_item PRIMARY KEY(donation_id, item_id)
);

-- Step 4: Re-establish foreign key from dnintake_item to donation_item
ALTER TABLE dnintake_item 
ADD CONSTRAINT fk_dnintake_item_donation_item 
FOREIGN KEY (donation_id, item_id) 
REFERENCES donation_item(donation_id, item_id);

-- Step 5: Verify referential integrity
DO $$ 
DECLARE
    invalid_donations INTEGER;
    invalid_items INTEGER;
    invalid_uoms INTEGER;
    orphaned_dnintake_items INTEGER;
BEGIN
    -- Check for invalid donation references in donation_item (should be 0)
    SELECT COUNT(*) INTO invalid_donations
    FROM donation_item di
    WHERE NOT EXISTS (SELECT 1 FROM donation WHERE donation_id = di.donation_id);
    
    -- Check for invalid item references in donation_item (should be 0)
    SELECT COUNT(*) INTO invalid_items
    FROM donation_item di
    WHERE NOT EXISTS (SELECT 1 FROM item WHERE item_id = di.item_id);
    
    -- Check for invalid UOM references in donation_item (should be 0)
    SELECT COUNT(*) INTO invalid_uoms
    FROM donation_item di
    WHERE NOT EXISTS (SELECT 1 FROM unitofmeasure WHERE uom_code = di.uom_code);
    
    -- Check for orphaned dnintake_item records (should be 0)
    SELECT COUNT(*) INTO orphaned_dnintake_items
    FROM dnintake_item dii
    WHERE NOT EXISTS (
        SELECT 1 FROM donation_item 
        WHERE donation_id = dii.donation_id 
        AND item_id = dii.item_id
    );
    
    IF invalid_donations > 0 OR invalid_items > 0 OR invalid_uoms > 0 OR orphaned_dnintake_items > 0 THEN
        RAISE EXCEPTION 'Referential integrity violation detected! Found invalid or orphaned records.';
    END IF;
    
    RAISE NOTICE 'Referential integrity check passed. All foreign keys are valid.';
    RAISE NOTICE 'donation_item table successfully recreated with standardized constraints.';
END $$;

COMMIT;

-- Post-migration verification queries
-- Verify the new structure:
-- SELECT column_name, data_type, numeric_precision, numeric_scale, is_nullable
-- FROM information_schema.columns
-- WHERE table_name = 'donation_item'
-- ORDER BY ordinal_position;

-- Verify constraints:
-- SELECT con.conname, pg_get_constraintdef(con.oid) 
-- FROM pg_constraint con
-- WHERE con.conrelid = 'donation_item'::regclass
-- ORDER BY con.contype, con.conname;
