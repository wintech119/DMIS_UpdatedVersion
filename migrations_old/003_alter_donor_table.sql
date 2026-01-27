-- Migration: Alter donor table while retaining referential integrity
-- Date: 2025-11-17
-- Status: COMPLETED SUCCESSFULLY
-- Purpose: 
--   1. Add donor_code column (varchar(16), NOT NULL, uppercase)
--   2. Remove donor_type column
--   3. Add check constraints for uppercase validation on donor_code and donor_name
-- 
-- Note: donor_id was already configured as identity column, no modification needed

BEGIN;

-- Step 1: Add donor_code column (nullable initially for migration)
ALTER TABLE donor 
ADD COLUMN IF NOT EXISTS donor_code VARCHAR(16);

-- Step 2: Populate donor_code from existing data
-- Strategy: Generate codes from existing donor_type and donor_id
-- Individual donors: IND-00001, IND-00002, etc.
-- Organization donors: ORG-00001, ORG-00002, etc.
UPDATE donor 
SET donor_code = UPPER(
    CASE 
        WHEN donor_type = 'I' THEN 'IND-' || LPAD(donor_id::TEXT, 5, '0')
        WHEN donor_type = 'O' THEN 'ORG-' || LPAD(donor_id::TEXT, 5, '0')
        ELSE 'DNR-' || LPAD(donor_id::TEXT, 5, '0')
    END
)
WHERE donor_code IS NULL;

-- Step 3: Make donor_code NOT NULL
ALTER TABLE donor 
ALTER COLUMN donor_code SET NOT NULL;

-- Step 4: Add uppercase constraint on donor_code
ALTER TABLE donor 
ADD CONSTRAINT c_donor_1 CHECK (donor_code = UPPER(donor_code));

-- Step 5: Ensure all existing donor_name values are uppercase
UPDATE donor 
SET donor_name = UPPER(donor_name)
WHERE donor_name != UPPER(donor_name);

-- Step 6: Add uppercase constraint to donor_name
ALTER TABLE donor 
ADD CONSTRAINT c_donor_2 CHECK (donor_name = UPPER(donor_name));

-- Step 7: Remove donor_type column
ALTER TABLE donor 
DROP COLUMN donor_type;

COMMIT;

-- Post-migration verification queries
-- Verify the new structure:
-- SELECT column_name, data_type, is_nullable, column_default, is_identity
-- FROM information_schema.columns
-- WHERE table_name = 'donor'
-- ORDER BY ordinal_position;

-- Verify constraints:
-- SELECT con.conname, pg_get_constraintdef(con.oid) 
-- FROM pg_constraint con
-- WHERE con.conrelid = 'donor'::regclass;

-- Verify referential integrity:
-- SELECT COUNT(*) FROM donation d
-- WHERE NOT EXISTS (SELECT 1 FROM donor WHERE donor_id = d.donor_id);
-- 
-- SELECT COUNT(*) FROM transaction t
-- WHERE t.donor_id IS NOT NULL 
--   AND NOT EXISTS (SELECT 1 FROM donor WHERE donor_id = t.donor_id);
