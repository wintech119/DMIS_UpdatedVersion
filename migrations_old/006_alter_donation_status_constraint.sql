-- Migration 006: Update donation table status_code constraint
-- Add 'P' (Processed) status to existing E=Entered, V=Verified statuses
-- Maintains referential integrity and existing data

BEGIN;

-- Drop existing check constraint
ALTER TABLE donation DROP CONSTRAINT IF EXISTS c_donation_2;

-- Add updated check constraint with P status
ALTER TABLE donation ADD CONSTRAINT c_donation_2 
    CHECK (status_code IN ('E', 'V', 'P'));

-- Verify constraint was updated
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 
        FROM pg_constraint 
        WHERE conname = 'c_donation_2' 
        AND conrelid = 'donation'::regclass
    ) THEN
        RAISE EXCEPTION 'Failed to create constraint c_donation_2';
    END IF;
END $$;

COMMIT;

-- Status codes:
-- E = Entered (initial entry)
-- V = Verified (verified by custodian)
-- P = Processed (donation processed/completed)
