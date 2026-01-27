-- Migration: Update donation table to match target DDL
-- Date: 2025-11-24
-- Purpose: Align donation table structure with new requirements while preserving
--          referential integrity and all existing data
-- Safety: Table is currently empty (0 rows), making this migration safe

-- ==============================================================================
-- STEP 1: Add new required columns with defaults
-- ==============================================================================

-- Add cost breakdown columns (all NOT NULL with CHECK > 0.00)
-- Default to 0.01 as minimum valid value to satisfy CHECK constraints
ALTER TABLE donation 
ADD COLUMN IF NOT EXISTS storage_cost DECIMAL(12,2) NOT NULL DEFAULT 0.01;

ALTER TABLE donation 
ADD COLUMN IF NOT EXISTS haulage_cost DECIMAL(12,2) NOT NULL DEFAULT 0.01;

ALTER TABLE donation 
ADD COLUMN IF NOT EXISTS other_cost DECIMAL(12,2) NOT NULL DEFAULT 0.01;

-- Add optional description for other costs
ALTER TABLE donation 
ADD COLUMN IF NOT EXISTS other_cost_desc VARCHAR(255);

-- ==============================================================================
-- STEP 2: Rename and modify existing columns
-- ==============================================================================

-- Rename tot_donated_value to tot_item_cost (if column exists)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'donation' 
        AND column_name = 'tot_donated_value'
    ) THEN
        ALTER TABLE donation RENAME COLUMN tot_donated_value TO tot_item_cost;
    END IF;
END $$;

-- Ensure tot_item_cost has correct type and constraints
-- First, add the column if it doesn't exist (in case rename didn't happen)
ALTER TABLE donation 
ADD COLUMN IF NOT EXISTS tot_item_cost DECIMAL(12,2);

-- Update NULL values to 0.01 before making NOT NULL (table is empty, but just in case)
UPDATE donation SET tot_item_cost = 0.01 WHERE tot_item_cost IS NULL;

-- Make tot_item_cost NOT NULL
ALTER TABLE donation 
ALTER COLUMN tot_item_cost SET NOT NULL;

-- Set default for tot_item_cost
ALTER TABLE donation 
ALTER COLUMN tot_item_cost SET DEFAULT 0.01;

-- ==============================================================================
-- STEP 3: Update origin_country_id to NOT NULL
-- ==============================================================================

-- For any existing rows without country (shouldn't happen as table is empty),
-- set to a default country (Jamaica, country_id=1, or first active country)
DO $$
DECLARE
    default_country_id SMALLINT;
BEGIN
    -- Get Jamaica's country_id or first active country
    SELECT country_id INTO default_country_id 
    FROM country 
    WHERE status_code = 'A' 
    ORDER BY CASE WHEN country_name = 'JAMAICA' THEN 0 ELSE 1 END, country_id 
    LIMIT 1;
    
    -- Update NULL values (if any)
    IF default_country_id IS NOT NULL THEN
        UPDATE donation 
        SET origin_country_id = default_country_id 
        WHERE origin_country_id IS NULL;
    END IF;
END $$;

-- Make origin_country_id NOT NULL
ALTER TABLE donation 
ALTER COLUMN origin_country_id SET NOT NULL;

-- ==============================================================================
-- STEP 4: Add CHECK constraints
-- ==============================================================================

-- Drop existing constraints if they exist (idempotent)
ALTER TABLE donation DROP CONSTRAINT IF EXISTS c_donation_1;
ALTER TABLE donation DROP CONSTRAINT IF EXISTS c_donation_2;
ALTER TABLE donation DROP CONSTRAINT IF EXISTS c_donation_2a;
ALTER TABLE donation DROP CONSTRAINT IF EXISTS c_donation_2b;
ALTER TABLE donation DROP CONSTRAINT IF EXISTS c_donation_2c;
ALTER TABLE donation DROP CONSTRAINT IF EXISTS c_donation_3;

-- Add CHECK constraints as per target DDL
ALTER TABLE donation 
ADD CONSTRAINT c_donation_1 
CHECK (received_date <= CURRENT_DATE);

ALTER TABLE donation 
ADD CONSTRAINT c_donation_2 
CHECK (tot_item_cost > 0.00);

ALTER TABLE donation 
ADD CONSTRAINT c_donation_2a 
CHECK (storage_cost > 0.00);

ALTER TABLE donation 
ADD CONSTRAINT c_donation_2b 
CHECK (haulage_cost > 0.00);

ALTER TABLE donation 
ADD CONSTRAINT c_donation_2c 
CHECK (other_cost > 0.00);

ALTER TABLE donation 
ADD CONSTRAINT c_donation_3 
CHECK (status_code IN ('E','V','P'));

-- ==============================================================================
-- STEP 5: Verify foreign keys are intact
-- ==============================================================================

-- These should already exist, but verify/recreate if missing
-- (Should not be necessary as we haven't touched the table structure)

DO $$
BEGIN
    -- fk_donation_donor
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints 
        WHERE constraint_name = 'fk_donation_donor' 
        AND table_name = 'donation'
    ) THEN
        ALTER TABLE donation 
        ADD CONSTRAINT fk_donation_donor 
        FOREIGN KEY (donor_id) REFERENCES donor(donor_id);
    END IF;
    
    -- fk_donation_country
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints 
        WHERE constraint_name = 'fk_donation_country' 
        AND table_name = 'donation'
    ) THEN
        ALTER TABLE donation 
        ADD CONSTRAINT fk_donation_country 
        FOREIGN KEY (origin_country_id) REFERENCES country(country_id);
    END IF;
    
    -- fk_donation_event
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints 
        WHERE constraint_name = 'fk_donation_event' 
        AND table_name = 'donation'
    ) THEN
        ALTER TABLE donation 
        ADD CONSTRAINT fk_donation_event 
        FOREIGN KEY (event_id) REFERENCES event(event_id);
    END IF;
    
    -- fk_donation_custodian
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints 
        WHERE constraint_name = 'fk_donation_custodian' 
        AND table_name = 'donation'
    ) THEN
        ALTER TABLE donation 
        ADD CONSTRAINT fk_donation_custodian 
        FOREIGN KEY (custodian_id) REFERENCES custodian(custodian_id);
    END IF;
END $$;

-- ==============================================================================
-- STEP 6: Verify migration success
-- ==============================================================================

-- Display final table structure
SELECT 
    column_name,
    data_type,
    character_maximum_length,
    numeric_precision,
    numeric_scale,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_name = 'donation'
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
WHERE tc.table_name = 'donation'
ORDER BY tc.constraint_type, tc.constraint_name;

-- ==============================================================================
-- MIGRATION COMPLETE
-- ==============================================================================
-- The donation table now matches the target DDL with:
-- - All required cost columns (tot_item_cost, storage_cost, haulage_cost, other_cost)
-- - origin_country_id as NOT NULL
-- - All CHECK constraints enforced
-- - All foreign keys intact
-- - Referential integrity preserved for downstream tables:
--   * donation_item
--   * dnintake
--   * donation_doc
-- ==============================================================================
