-- Migration: Drop and Recreate donation_item table to match target DDL
-- Date: 2025-11-25
-- Migration ID: 014
-- Purpose: Complete table rebuild to match exact target DDL structure
-- Safety: Table is empty (0 rows), FK from dnintake_item properly handled

-- ==============================================================================
-- TRANSACTION START
-- ==============================================================================
BEGIN;

-- ==============================================================================
-- STEP 1: Drop FK from dnintake_item referencing donation_item
-- ==============================================================================
-- The dnintake_item table has: fk_dnintake_item_donation_item (donation_id, item_id)
-- This must be dropped before we can drop donation_item

ALTER TABLE dnintake_item 
DROP CONSTRAINT IF EXISTS fk_dnintake_item_donation_item;

-- ==============================================================================
-- STEP 2: Drop the existing donation_item table
-- ==============================================================================
-- Table is empty, so no data loss

DROP TABLE IF EXISTS donation_item CASCADE;

-- ==============================================================================
-- STEP 3: Create donation_item with target DDL structure
-- ==============================================================================
-- Note: addon_cost is included because constraint c_donation_item_10 requires it
-- The provided DDL omits addon_cost as a column but references it in the constraint

CREATE TABLE donation_item
(
    donation_id INTEGER NOT NULL
        CONSTRAINT fk_donation_item_donation REFERENCES donation(donation_id),
    
    item_id INTEGER NOT NULL
        CONSTRAINT fk_donation_item_item REFERENCES item(item_id),
    
    donation_type CHAR(5) NOT NULL DEFAULT 'GOODS'
        CONSTRAINT c_donation_item_0 CHECK (donation_type IN ('GOODS','FUNDS')),
    
    item_qty DECIMAL(9,2) NOT NULL DEFAULT 1.00
        CONSTRAINT c_donation_item_1a CHECK (item_qty >= 0.00),
    
    item_cost DECIMAL(10,2) NOT NULL DEFAULT 0.00
        CONSTRAINT c_donation_item_1b CHECK (item_cost >= 0.00),
    
    addon_cost DECIMAL(10,2) NOT NULL DEFAULT 0.00
        CONSTRAINT c_donation_item_1c CHECK (addon_cost >= 0.00),
    
    uom_code VARCHAR(25) NOT NULL
        CONSTRAINT fk_donation_item_unitofmeasure REFERENCES unitofmeasure(uom_code),
    
    location_name TEXT NOT NULL,
    
    status_code CHAR(1) NOT NULL DEFAULT 'V'
        CONSTRAINT c_donation_item_2 CHECK (status_code IN ('P','V')),
    
    comments_text TEXT,
    
    create_by_id VARCHAR(20) NOT NULL,
    create_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    update_by_id VARCHAR(20) NOT NULL,
    update_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    verify_by_id VARCHAR(20) NOT NULL,
    verify_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    version_nbr INTEGER NOT NULL DEFAULT 1,
    
    CONSTRAINT c_donation_item_10 CHECK (item_cost + addon_cost > 0.00),
    
    CONSTRAINT pk_donation_item PRIMARY KEY (donation_id, item_id)
);

-- ==============================================================================
-- STEP 4: Re-add FK from dnintake_item to donation_item
-- ==============================================================================

ALTER TABLE dnintake_item
ADD CONSTRAINT fk_dnintake_item_donation_item 
    FOREIGN KEY (donation_id, item_id) 
    REFERENCES donation_item(donation_id, item_id);

-- ==============================================================================
-- STEP 5: Add table comments for documentation
-- ==============================================================================

COMMENT ON TABLE donation_item IS 'Donation items - individual items/funds donated as part of a donation';
COMMENT ON COLUMN donation_item.donation_type IS 'Type of donation: GOODS (physical items) or FUNDS (monetary)';
COMMENT ON COLUMN donation_item.item_qty IS 'Quantity (goods) or number of instances (funds)';
COMMENT ON COLUMN donation_item.item_cost IS 'Purchase cost (goods) or donated value (funds)';
COMMENT ON COLUMN donation_item.addon_cost IS 'Additional costs (shipping, handling, etc.)';
COMMENT ON COLUMN donation_item.uom_code IS 'Unit of measure (goods) or currency code (funds)';
COMMENT ON COLUMN donation_item.location_name IS 'Pickup location (goods) or bank/account info (funds)';
COMMENT ON COLUMN donation_item.status_code IS 'P=Pending verification, V=Verified';

-- ==============================================================================
-- TRANSACTION COMMIT
-- ==============================================================================
COMMIT;

-- ==============================================================================
-- STEP 6: Verify the new table structure
-- ==============================================================================

SELECT 
    column_name,
    data_type,
    character_maximum_length,
    numeric_precision,
    numeric_scale,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_name = 'donation_item'
ORDER BY ordinal_position;

-- Display all constraints
SELECT 
    tc.constraint_name,
    tc.constraint_type
FROM information_schema.table_constraints AS tc
WHERE tc.table_name = 'donation_item'
ORDER BY tc.constraint_type, tc.constraint_name;

-- Verify FK from dnintake_item is restored
SELECT 
    tc.table_name,
    tc.constraint_name,
    ccu.table_name AS references_table
FROM information_schema.table_constraints AS tc
JOIN information_schema.constraint_column_usage AS ccu
    ON ccu.constraint_name = tc.constraint_name
WHERE tc.constraint_type = 'FOREIGN KEY'
    AND ccu.table_name = 'donation_item';

-- ==============================================================================
-- MIGRATION COMPLETE
-- ==============================================================================
-- donation_item table recreated with:
-- ✓ All columns matching target DDL (including addon_cost for constraint)
-- ✓ All CHECK constraints properly defined
-- ✓ All foreign keys intact
-- ✓ Composite PK (donation_id, item_id)
-- ✓ FK from dnintake_item restored
-- ✓ Zero data loss (table was empty)
-- ==============================================================================
