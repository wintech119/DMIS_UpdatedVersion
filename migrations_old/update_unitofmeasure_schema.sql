-- ============================================================================
-- DRIMS - Unit of Measure Table Schema Migration
-- ============================================================================
-- Purpose: Update unitofmeasure table to match the standardized DRIMS schema
-- Date: 2025-11-17
-- 
-- This script safely migrates the unitofmeasure table structure while:
-- - Preserving all existing data
-- - Maintaining all foreign key references (10 referencing tables)
-- - Using ALTER TABLE operations to avoid breaking dependencies
-- - Ensuring all constraint names match DRIMS naming conventions
-- ============================================================================

BEGIN;

-- ============================================================================
-- SECTION 1: ANALYSIS - Current State
-- ============================================================================
-- Current structure verified:
--   - uom_code varchar(25) NOT NULL (PK with uppercase check)
--   - uom_desc varchar(60) NOT NULL
--   - comments_text text
--   - Audit fields: create_by_id, create_dtime, update_by_id, update_dtime
--   - version_nbr integer NOT NULL
--
-- Current constraints:
--   - unitofmeasure_pkey (PRIMARY KEY) → needs rename to pk_unitofmeasure
--   - unitofmeasure_uom_code_check (uppercase) → needs rename to c_unitofmeasure_1
--
-- Missing:
--   - status_code char(1) NOT NULL with CHECK constraint c_unitofmeasure_2
--
-- Foreign Keys Referencing unitofmeasure.uom_code (10 tables):
--   1. dbintake_item.uom_code
--   2. dnintake_item.uom_code
--   3. donation_item.uom_code
--   4. inventory.uom_code
--   5. item.default_uom_code
--   6. reliefpkg_item.uom_code
--   7. rtintake_item.uom_code
--   8. transfer_item.uom_code
--   9. xfintake_item.uom_code
--  10. xfreturn_item.uom_code
-- ============================================================================

-- ============================================================================
-- SECTION 2: ADD MISSING COLUMN
-- ============================================================================
-- Add status_code column if it doesn't exist
-- Default to 'A' (Active) for all existing records
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public' 
          AND table_name = 'unitofmeasure' 
          AND column_name = 'status_code'
    ) THEN
        ALTER TABLE unitofmeasure 
        ADD COLUMN status_code char(1) NOT NULL DEFAULT 'A';
        
        RAISE NOTICE 'Added status_code column with default value A';
    ELSE
        RAISE NOTICE 'Column status_code already exists, skipping';
    END IF;
END $$;

-- ============================================================================
-- SECTION 3: RENAME CONSTRAINTS TO MATCH DRIMS NAMING CONVENTIONS
-- ============================================================================

-- Step 3.1: Rename PRIMARY KEY constraint
-- From: unitofmeasure_pkey → To: pk_unitofmeasure
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'unitofmeasure_pkey' 
          AND conrelid = 'public.unitofmeasure'::regclass
    ) THEN
        ALTER TABLE unitofmeasure 
        RENAME CONSTRAINT unitofmeasure_pkey TO pk_unitofmeasure;
        
        RAISE NOTICE 'Renamed PRIMARY KEY constraint to pk_unitofmeasure';
    ELSE
        RAISE NOTICE 'PRIMARY KEY constraint already named pk_unitofmeasure';
    END IF;
END $$;

-- Step 3.2: Rename uppercase CHECK constraint
-- From: unitofmeasure_uom_code_check → To: c_unitofmeasure_1
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'unitofmeasure_uom_code_check' 
          AND conrelid = 'public.unitofmeasure'::regclass
    ) THEN
        ALTER TABLE unitofmeasure 
        RENAME CONSTRAINT unitofmeasure_uom_code_check TO c_unitofmeasure_1;
        
        RAISE NOTICE 'Renamed uppercase CHECK constraint to c_unitofmeasure_1';
    ELSE
        RAISE NOTICE 'Uppercase CHECK constraint already named c_unitofmeasure_1';
    END IF;
END $$;

-- ============================================================================
-- SECTION 4: ADD STATUS CODE CHECK CONSTRAINT
-- ============================================================================

-- Add CHECK constraint for status_code (must be 'A' or 'I')
-- Constraint name: c_unitofmeasure_2
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'c_unitofmeasure_2' 
          AND conrelid = 'public.unitofmeasure'::regclass
    ) THEN
        ALTER TABLE unitofmeasure 
        ADD CONSTRAINT c_unitofmeasure_2 
        CHECK (status_code IN ('A', 'I'));
        
        RAISE NOTICE 'Added status_code CHECK constraint c_unitofmeasure_2';
    ELSE
        RAISE NOTICE 'CHECK constraint c_unitofmeasure_2 already exists';
    END IF;
END $$;

-- ============================================================================
-- SECTION 5: VERIFICATION
-- ============================================================================

-- Verify final table structure
DO $$
DECLARE
    v_column_count INTEGER;
    v_constraint_count INTEGER;
BEGIN
    -- Count columns (should be 9)
    SELECT COUNT(*) INTO v_column_count
    FROM information_schema.columns
    WHERE table_schema = 'public' 
      AND table_name = 'unitofmeasure';
    
    -- Count constraints (should be 3: PK + 2 CHECKs)
    SELECT COUNT(*) INTO v_constraint_count
    FROM pg_constraint
    WHERE conrelid = 'public.unitofmeasure'::regclass;
    
    RAISE NOTICE '=================================================';
    RAISE NOTICE 'MIGRATION VERIFICATION RESULTS';
    RAISE NOTICE '=================================================';
    RAISE NOTICE 'Total columns: % (expected: 9)', v_column_count;
    RAISE NOTICE 'Total constraints: % (expected: 3)', v_constraint_count;
    
    -- Verify required columns exist
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public' 
          AND table_name = 'unitofmeasure' 
          AND column_name = 'status_code'
    ) THEN
        RAISE NOTICE '✓ Column status_code exists';
    ELSE
        RAISE EXCEPTION '✗ Column status_code is missing!';
    END IF;
    
    -- Verify constraints
    IF EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'pk_unitofmeasure' 
          AND conrelid = 'public.unitofmeasure'::regclass
    ) THEN
        RAISE NOTICE '✓ Constraint pk_unitofmeasure exists';
    ELSE
        RAISE EXCEPTION '✗ Constraint pk_unitofmeasure is missing!';
    END IF;
    
    IF EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'c_unitofmeasure_1' 
          AND conrelid = 'public.unitofmeasure'::regclass
    ) THEN
        RAISE NOTICE '✓ Constraint c_unitofmeasure_1 exists';
    ELSE
        RAISE EXCEPTION '✗ Constraint c_unitofmeasure_1 is missing!';
    END IF;
    
    IF EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'c_unitofmeasure_2' 
          AND conrelid = 'public.unitofmeasure'::regclass
    ) THEN
        RAISE NOTICE '✓ Constraint c_unitofmeasure_2 exists';
    ELSE
        RAISE EXCEPTION '✗ Constraint c_unitofmeasure_2 is missing!';
    END IF;
    
    RAISE NOTICE '=================================================';
    RAISE NOTICE 'Migration completed successfully!';
    RAISE NOTICE '=================================================';
END $$;

-- Display final table structure
SELECT 
    column_name,
    data_type,
    character_maximum_length,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_schema = 'public' 
  AND table_name = 'unitofmeasure'
ORDER BY ordinal_position;

-- Display final constraints
SELECT
    conname as constraint_name,
    contype as constraint_type,
    pg_get_constraintdef(oid) as constraint_definition
FROM pg_constraint
WHERE conrelid = 'public.unitofmeasure'::regclass
ORDER BY conname;

COMMIT;

-- ============================================================================
-- END OF MIGRATION SCRIPT
-- ============================================================================
-- Notes:
-- - All foreign key references remain intact (no FKs were dropped)
-- - All existing data preserved
-- - All indexes maintained
-- - Table now matches target schema exactly
-- - Safe to execute multiple times (idempotent)
-- ============================================================================
