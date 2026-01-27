-- Migration: Update donation_item table to match target DDL
-- Date: 2025-11-24
-- Purpose: Align donation_item table structure with requirements while preserving
--          referential integrity, all existing data, and all workflows
-- Safety: Table is currently empty (0 rows), making this migration completely safe

-- ==============================================================================
-- CURRENT STATE ANALYSIS
-- ==============================================================================
-- The table already has most required columns and constraints:
-- ✓ donation_id, item_id (PK composite)
-- ✓ donation_type CHAR(5) with CHECK constraint
-- ✓ item_qty DECIMAL(12,2) (needs precision change to 9,2)
-- ✓ item_cost DECIMAL(10,2) with CHECK >= 0.00
-- ✓ addon_cost DECIMAL(10,2) with CHECK >= 0.00
-- ✓ uom_code VARCHAR(25) with FK to unitofmeasure
-- ✓ location_name TEXT
-- ✓ status_code CHAR(1) with CHECK IN ('P','V')
-- ✓ All audit fields present
--
-- CHANGES NEEDED:
-- 1. Alter item_qty precision from DECIMAL(12,2) to DECIMAL(9,2)
-- 2. Add default 1.00 to item_qty
-- 3. Make verify_by_id NOT NULL
-- 4. Make verify_dtime NOT NULL
-- 5. Add constraint c_donation_item_10: item_cost + addon_cost > 0.00
--
-- ==============================================================================

-- ==============================================================================
-- STEP 1: Modify item_qty precision and add default
-- ==============================================================================
-- Safe because: Table is empty, no data to migrate
-- Target: DECIMAL(9,2) NOT NULL DEFAULT 1.00

ALTER TABLE donation_item 
ALTER COLUMN item_qty TYPE DECIMAL(9,2);

ALTER TABLE donation_item 
ALTER COLUMN item_qty SET DEFAULT 1.00;

-- ==============================================================================
-- STEP 2: Make verify_by_id NOT NULL
-- ==============================================================================
-- Safe because: Table is empty
-- For future rows: Application already sets this field via add_audit_fields()

-- Update any existing NULL values (shouldn't exist as table is empty)
UPDATE donation_item 
SET verify_by_id = create_by_id 
WHERE verify_by_id IS NULL;

ALTER TABLE donation_item 
ALTER COLUMN verify_by_id SET NOT NULL;

-- ==============================================================================
-- STEP 3: Make verify_dtime NOT NULL
-- ==============================================================================
-- Safe because: Table is empty
-- For future rows: Application already sets this field via add_audit_fields()

-- Update any existing NULL values (shouldn't exist as table is empty)
UPDATE donation_item 
SET verify_dtime = create_dtime 
WHERE verify_dtime IS NULL;

ALTER TABLE donation_item 
ALTER COLUMN verify_dtime SET NOT NULL;

-- ==============================================================================
-- STEP 4: Add constraint c_donation_item_10
-- ==============================================================================
-- This constraint ensures that the combined cost (item_cost + addon_cost) is > 0.00
-- Safe because: Table is empty, and application logic already ensures costs are valid

-- Drop if exists (idempotent)
ALTER TABLE donation_item DROP CONSTRAINT IF EXISTS c_donation_item_10;

-- Add the constraint
ALTER TABLE donation_item 
ADD CONSTRAINT c_donation_item_10 
CHECK (item_cost + addon_cost > 0.00);

-- ==============================================================================
-- STEP 5: Verify all constraints are in place
-- ==============================================================================

-- Verify constraint c_donation_item_0 exists (donation_type)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.check_constraints 
        WHERE constraint_name = 'c_donation_item_0'
        AND constraint_schema = 'public'
    ) THEN
        ALTER TABLE donation_item 
        ADD CONSTRAINT c_donation_item_0 
        CHECK (donation_type IN ('GOODS','FUNDS'));
    END IF;
END $$;

-- Verify constraint c_donation_item_1a exists (item_qty >= 0.00)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.check_constraints 
        WHERE constraint_name = 'c_donation_item_1a'
        AND constraint_schema = 'public'
    ) THEN
        ALTER TABLE donation_item 
        ADD CONSTRAINT c_donation_item_1a 
        CHECK (item_qty >= 0.00);
    END IF;
END $$;

-- Verify constraint c_donation_item_1b exists (item_cost >= 0.00)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.check_constraints 
        WHERE constraint_name = 'c_donation_item_1b'
        AND constraint_schema = 'public'
    ) THEN
        ALTER TABLE donation_item 
        ADD CONSTRAINT c_donation_item_1b 
        CHECK (item_cost >= 0.00);
    END IF;
END $$;

-- Verify constraint c_donation_item_2 exists (status_code IN ('P','V'))
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.check_constraints 
        WHERE constraint_name = 'c_donation_item_2'
        AND constraint_schema = 'public'
    ) THEN
        ALTER TABLE donation_item 
        ADD CONSTRAINT c_donation_item_2 
        CHECK (status_code IN ('P','V'));
    END IF;
END $$;

-- ==============================================================================
-- STEP 6: Verify foreign keys remain intact
-- ==============================================================================
-- These should not need recreation, but verify they exist

DO $$
BEGIN
    -- fk_donation_item_donation
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints 
        WHERE constraint_name = 'fk_donation_item_donation' 
        AND table_name = 'donation_item'
    ) THEN
        ALTER TABLE donation_item 
        ADD CONSTRAINT fk_donation_item_donation 
        FOREIGN KEY (donation_id) REFERENCES donation(donation_id);
    END IF;
    
    -- fk_donation_item_item
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints 
        WHERE constraint_name = 'fk_donation_item_item' 
        AND table_name = 'donation_item'
    ) THEN
        ALTER TABLE donation_item 
        ADD CONSTRAINT fk_donation_item_item 
        FOREIGN KEY (item_id) REFERENCES item(item_id);
    END IF;
    
    -- fk_donation_item_unitofmeasure
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints 
        WHERE constraint_name = 'fk_donation_item_unitofmeasure' 
        AND table_name = 'donation_item'
    ) THEN
        ALTER TABLE donation_item 
        ADD CONSTRAINT fk_donation_item_unitofmeasure 
        FOREIGN KEY (uom_code) REFERENCES unitofmeasure(uom_code);
    END IF;
END $$;

-- ==============================================================================
-- STEP 7: Display final table structure for verification
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
    tc.constraint_type,
    kcu.column_name,
    ccu.table_name AS references_table,
    ccu.column_name AS references_column
FROM information_schema.table_constraints AS tc
LEFT JOIN information_schema.key_column_usage AS kcu
    ON tc.constraint_name = kcu.constraint_name
LEFT JOIN information_schema.constraint_column_usage AS ccu
    ON ccu.constraint_name = tc.constraint_name
WHERE tc.table_name = 'donation_item'
ORDER BY tc.constraint_type, tc.constraint_name;

-- ==============================================================================
-- MIGRATION COMPLETE
-- ==============================================================================
-- The donation_item table now matches the target DDL with:
-- ✓ item_qty DECIMAL(9,2) DEFAULT 1.00
-- ✓ verify_by_id NOT NULL
-- ✓ verify_dtime NOT NULL
-- ✓ All CHECK constraints enforced including c_donation_item_10
-- ✓ All foreign keys intact
-- ✓ Referential integrity preserved for downstream tables:
--   * dnintake_item
-- ✓ Composite primary key (donation_id, item_id) preserved
-- ✓ All audit fields properly configured
-- ==============================================================================
