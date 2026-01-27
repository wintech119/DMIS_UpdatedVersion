-- ============================================================================
-- DRIMS Migration: Alter custodian table to match target schema
-- ============================================================================
-- This migration transforms the existing custodian table to align with
-- DRIMS standards including:
--   - Identity column for custodian_id (if not already present)
--   - Standardized constraint naming (pk_, uk_, c_, fk_ prefixes)
--   - Uppercase enforcement on name fields
--   - Timestamp precision
--
-- SAFETY: Preserves all foreign key references from warehouse and donation
-- ============================================================================

BEGIN;

-- ============================================================================
-- PHASE 1: Normalize existing data
-- ============================================================================
-- Ensure custodian_name and contact_name are uppercase before adding constraints

UPDATE custodian
SET custodian_name = UPPER(custodian_name)
WHERE custodian_name <> UPPER(custodian_name);

UPDATE custodian
SET contact_name = UPPER(contact_name)
WHERE contact_name <> UPPER(contact_name);

-- ============================================================================
-- PHASE 2: Rename constraints to DRIMS standards
-- ============================================================================

-- 2.1 Rename Primary Key: custodian_pkey → pk_custodian (if needed)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'custodian_pkey' 
        AND conrelid = 'custodian'::regclass
    ) THEN
        ALTER TABLE custodian RENAME CONSTRAINT custodian_pkey TO pk_custodian;
        RAISE NOTICE 'Renamed custodian_pkey to pk_custodian';
    ELSE
        RAISE NOTICE 'pk_custodian already exists, skipping rename';
    END IF;
END $$;

-- 2.2 Drop and recreate check constraints with standard names

-- Drop old custodian_name check constraint if it exists
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'custodian_custodian_name_check' 
        AND conrelid = 'custodian'::regclass
    ) THEN
        ALTER TABLE custodian DROP CONSTRAINT custodian_custodian_name_check;
        RAISE NOTICE 'Dropped custodian_custodian_name_check';
    END IF;
    
    -- Add new custodian_name check constraint with standard name
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'c_custodian_1' 
        AND conrelid = 'custodian'::regclass
    ) THEN
        ALTER TABLE custodian ADD CONSTRAINT c_custodian_1 
        CHECK (custodian_name = UPPER(custodian_name));
        RAISE NOTICE 'Added c_custodian_1 constraint';
    END IF;
END $$;

-- Drop old contact_name check constraint if it exists
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'custodian_contact_name_check' 
        AND conrelid = 'custodian'::regclass
    ) THEN
        ALTER TABLE custodian DROP CONSTRAINT custodian_contact_name_check;
        RAISE NOTICE 'Dropped custodian_contact_name_check';
    END IF;
    
    -- Add new contact_name check constraint with standard name
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'c_custodian_3' 
        AND conrelid = 'custodian'::regclass
    ) THEN
        ALTER TABLE custodian ADD CONSTRAINT c_custodian_3 
        CHECK (contact_name = UPPER(contact_name));
        RAISE NOTICE 'Added c_custodian_3 constraint';
    END IF;
END $$;

-- 2.3 Rename Foreign Key: custodian_parish_code_fkey → fk_custodian_parish (if needed)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'custodian_parish_code_fkey' 
        AND conrelid = 'custodian'::regclass
    ) THEN
        ALTER TABLE custodian RENAME CONSTRAINT custodian_parish_code_fkey TO fk_custodian_parish;
        RAISE NOTICE 'Renamed custodian_parish_code_fkey to fk_custodian_parish';
    ELSE
        RAISE NOTICE 'fk_custodian_parish already exists, skipping rename';
    END IF;
END $$;

-- NOTE: uk_custodian_1 already has the correct name, no change needed

-- ============================================================================
-- PHASE 3: Convert custodian_id to IDENTITY column (if not already)
-- ============================================================================

DO $$
DECLARE
    max_id INTEGER;
    is_identity_col BOOLEAN;
BEGIN
    -- Check if custodian_id is already an identity column
    SELECT 
        CASE WHEN c.is_identity = 'YES' THEN TRUE ELSE FALSE END
    INTO is_identity_col
    FROM information_schema.columns c
    WHERE c.table_name = 'custodian' 
      AND c.table_schema = 'public'
      AND c.column_name = 'custodian_id';
    
    IF NOT is_identity_col THEN
        -- Get the maximum custodian_id to set sequence start value
        SELECT COALESCE(MAX(custodian_id), 0) + 1 INTO max_id FROM custodian;
        
        -- Add identity characteristic to existing column
        ALTER TABLE custodian 
            ALTER COLUMN custodian_id 
            ADD GENERATED BY DEFAULT AS IDENTITY;
        
        -- Set the sequence to start after the highest existing ID
        PERFORM setval(
            pg_get_serial_sequence('custodian', 'custodian_id'),
            max_id,
            false
        );
        
        RAISE NOTICE 'custodian_id converted to identity column, sequence starts at %', max_id;
    ELSE
        RAISE NOTICE 'custodian_id is already an identity column, skipping conversion';
    END IF;
END $$;

-- ============================================================================
-- PHASE 4: Adjust timestamp precision to (0)
-- ============================================================================

DO $$
BEGIN
    -- Alter create_dtime to timestamp(0)
    ALTER TABLE custodian
        ALTER COLUMN create_dtime TYPE timestamp(0) without time zone;
    
    -- Alter update_dtime to timestamp(0)
    ALTER TABLE custodian
        ALTER COLUMN update_dtime TYPE timestamp(0) without time zone;
    
    RAISE NOTICE 'Timestamp columns adjusted to precision (0)';
END $$;

-- ============================================================================
-- PHASE 5: Verify final structure
-- ============================================================================

DO $$
DECLARE
    constraint_count INTEGER;
    fk_count INTEGER;
    pk_name TEXT;
    uk_name TEXT;
    fk_name TEXT;
    c1_name TEXT;
    c3_name TEXT;
BEGIN
    -- Verify all required constraints exist with correct names
    SELECT COUNT(*) INTO constraint_count
    FROM pg_constraint con
    JOIN pg_class rel ON rel.oid = con.conrelid
    JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
    WHERE nsp.nspname = 'public'
      AND rel.relname = 'custodian'
      AND con.conname IN ('pk_custodian', 'uk_custodian_1', 'c_custodian_1', 'c_custodian_3', 'fk_custodian_parish');
    
    IF constraint_count <> 5 THEN
        RAISE EXCEPTION 'Expected 5 constraints on custodian table, found %. Missing constraints!', constraint_count;
    END IF;
    
    -- Get constraint names for display
    SELECT string_agg(conname, ', ' ORDER BY conname)
    INTO pk_name
    FROM pg_constraint
    WHERE conrelid = 'custodian'::regclass AND contype = 'p';
    
    SELECT string_agg(conname, ', ' ORDER BY conname)
    INTO uk_name
    FROM pg_constraint
    WHERE conrelid = 'custodian'::regclass AND contype = 'u';
    
    SELECT string_agg(conname, ', ' ORDER BY conname)
    INTO c1_name
    FROM pg_constraint
    WHERE conrelid = 'custodian'::regclass AND contype = 'c';
    
    SELECT string_agg(conname, ', ' ORDER BY conname)
    INTO fk_name
    FROM pg_constraint
    WHERE conrelid = 'custodian'::regclass AND contype = 'f';
    
    -- Verify foreign keys to custodian still exist
    SELECT COUNT(*) INTO fk_count
    FROM information_schema.table_constraints tc
    JOIN information_schema.constraint_column_usage ccu
        ON ccu.constraint_name = tc.constraint_name
        AND ccu.table_schema = tc.table_schema
    WHERE tc.constraint_type = 'FOREIGN KEY'
      AND ccu.table_name = 'custodian'
      AND tc.table_schema = 'public';
    
    IF fk_count < 2 THEN
        RAISE WARNING 'Expected at least 2 foreign keys referencing custodian, found %', fk_count;
    END IF;
    
    RAISE NOTICE '========================================';
    RAISE NOTICE 'custodian table migration completed successfully';
    RAISE NOTICE '========================================';
    RAISE NOTICE '✓ Primary key: %', pk_name;
    RAISE NOTICE '✓ Unique constraint: %', uk_name;
    RAISE NOTICE '✓ Check constraints: %', c1_name;
    RAISE NOTICE '✓ Foreign key: %', fk_name;
    RAISE NOTICE '✓ Foreign key references preserved: % table(s)', fk_count;
    RAISE NOTICE '========================================';
END $$;

COMMIT;

-- ============================================================================
-- Post-migration verification queries (optional - uncomment to run)
-- ============================================================================

-- View final table structure
-- SELECT column_name, data_type, character_maximum_length, is_nullable, 
--        column_default, is_identity, identity_generation
-- FROM information_schema.columns
-- WHERE table_name = 'custodian' AND table_schema = 'public'
-- ORDER BY ordinal_position;

-- View all constraints
-- SELECT conname AS constraint_name, 
--        contype AS type,
--        pg_get_constraintdef(oid) AS definition
-- FROM pg_constraint
-- WHERE conrelid = 'custodian'::regclass
-- ORDER BY contype, conname;

-- View foreign keys referencing custodian
-- SELECT tc.table_name, kcu.column_name, tc.constraint_name
-- FROM information_schema.table_constraints tc
-- JOIN information_schema.key_column_usage kcu
--     ON tc.constraint_name = kcu.constraint_name
-- JOIN information_schema.constraint_column_usage ccu
--     ON ccu.constraint_name = tc.constraint_name
-- WHERE tc.constraint_type = 'FOREIGN KEY'
--   AND ccu.table_name = 'custodian'
--   AND tc.table_schema = 'public';
