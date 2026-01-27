-- Migration: Alter donation table constraint names while retaining referential integrity
-- Date: 2025-11-17
-- Purpose: 
--   Rename constraints to match naming standards:
--   1. pk_donation (primary key)
--   2. fk_donation_donor, fk_donation_event, fk_donation_custodian (foreign keys)
--   3. c_donation_1 (received_date check)
--   4. c_donation_2 (status_code check)
-- 
-- Note: donation_id is already configured as identity column
-- Note: All columns and data types are already correct

BEGIN;

-- Step 1: Rename PRIMARY KEY constraint
ALTER TABLE donation 
RENAME CONSTRAINT donation_pkey TO pk_donation;

-- Step 2: Rename FOREIGN KEY constraints
ALTER TABLE donation 
RENAME CONSTRAINT donation_donor_id_fkey TO fk_donation_donor;

ALTER TABLE donation 
RENAME CONSTRAINT donation_event_id_fkey TO fk_donation_event;

ALTER TABLE donation 
RENAME CONSTRAINT donation_custodian_id_fkey TO fk_donation_custodian;

-- Step 3: Rename CHECK constraints
ALTER TABLE donation 
RENAME CONSTRAINT donation_received_date_check TO c_donation_1;

ALTER TABLE donation 
RENAME CONSTRAINT donation_status_code_check TO c_donation_2;

-- Step 4: Verify referential integrity is intact
DO $$ 
DECLARE
    orphaned_dnintake INTEGER;
    orphaned_donation_items INTEGER;
    invalid_donors INTEGER;
    invalid_events INTEGER;
    invalid_custodians INTEGER;
BEGIN
    -- Check for orphaned dnintake records
    SELECT COUNT(*) INTO orphaned_dnintake
    FROM dnintake d
    WHERE NOT EXISTS (SELECT 1 FROM donation WHERE donation_id = d.donation_id);
    
    -- Check for orphaned donation_item records
    SELECT COUNT(*) INTO orphaned_donation_items
    FROM donation_item di
    WHERE NOT EXISTS (SELECT 1 FROM donation WHERE donation_id = di.donation_id);
    
    -- Check for invalid donor references
    SELECT COUNT(*) INTO invalid_donors
    FROM donation d
    WHERE NOT EXISTS (SELECT 1 FROM donor WHERE donor_id = d.donor_id);
    
    -- Check for invalid event references
    SELECT COUNT(*) INTO invalid_events
    FROM donation d
    WHERE NOT EXISTS (SELECT 1 FROM event WHERE event_id = d.event_id);
    
    -- Check for invalid custodian references
    SELECT COUNT(*) INTO invalid_custodians
    FROM donation d
    WHERE NOT EXISTS (SELECT 1 FROM custodian WHERE custodian_id = d.custodian_id);
    
    IF orphaned_dnintake > 0 OR orphaned_donation_items > 0 OR 
       invalid_donors > 0 OR invalid_events > 0 OR invalid_custodians > 0 THEN
        RAISE EXCEPTION 'Referential integrity violation detected! Found orphaned or invalid records.';
    END IF;
    
    RAISE NOTICE 'Referential integrity check passed. All foreign keys are valid.';
END $$;

COMMIT;

-- Post-migration verification queries
-- Verify the new constraint names:
-- SELECT con.conname, pg_get_constraintdef(con.oid) 
-- FROM pg_constraint con
-- WHERE con.conrelid = 'donation'::regclass
-- ORDER BY con.contype, con.conname;
