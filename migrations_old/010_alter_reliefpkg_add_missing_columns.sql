-- Migration 010: Add missing columns to reliefpkg table
-- Date: 2025-11-18
-- Purpose: Add agency_id, tracking_no, and eligible_event_id columns to reliefpkg table
--          while maintaining referential integrity

BEGIN;

-- Step 1: Add agency_id column (required)
ALTER TABLE reliefpkg
ADD COLUMN agency_id INTEGER;

-- Step 2: Set default agency_id from related relief request
-- (This ensures data integrity for existing records)
UPDATE reliefpkg
SET agency_id = rr.agency_id
FROM reliefrqst rr
WHERE reliefpkg.reliefrqst_id = rr.reliefrqst_id
AND reliefpkg.agency_id IS NULL;

-- Step 3: Make agency_id NOT NULL after populating
ALTER TABLE reliefpkg
ALTER COLUMN agency_id SET NOT NULL;

-- Step 4: Add foreign key constraint for agency_id
ALTER TABLE reliefpkg
ADD CONSTRAINT fk_reliefpkg_agency 
FOREIGN KEY (agency_id) REFERENCES agency(agency_id);

-- Step 5: Add tracking_no column (required)
ALTER TABLE reliefpkg
ADD COLUMN tracking_no CHAR(7);

-- Step 6: Generate tracking numbers for existing records
-- Format: 7 characters - using reliefpkg_id padded with zeros
UPDATE reliefpkg
SET tracking_no = LPAD(reliefpkg_id::TEXT, 7, '0')
WHERE tracking_no IS NULL;

-- Step 7: Make tracking_no NOT NULL after populating
ALTER TABLE reliefpkg
ALTER COLUMN tracking_no SET NOT NULL;

-- Step 8: Add eligible_event_id column (nullable)
ALTER TABLE reliefpkg
ADD COLUMN eligible_event_id INTEGER;

-- Step 9: Populate eligible_event_id from related relief request
UPDATE reliefpkg
SET eligible_event_id = rr.eligible_event_id
FROM reliefrqst rr
WHERE reliefpkg.reliefrqst_id = rr.reliefrqst_id
AND reliefpkg.eligible_event_id IS NULL;

-- Step 10: Add foreign key constraint for eligible_event_id
ALTER TABLE reliefpkg
ADD CONSTRAINT fk_reliefpkg_event 
FOREIGN KEY (eligible_event_id) REFERENCES event(event_id);

-- Step 11: Update constraint c_reliefpkg_3 to ensure status_code includes all valid values
-- and confirm 'A' = Draft
ALTER TABLE reliefpkg
DROP CONSTRAINT IF EXISTS c_reliefpkg_3;

ALTER TABLE reliefpkg
ADD CONSTRAINT c_reliefpkg_3 
CHECK (status_code IN ('A','P','C','V','D','R'));

COMMIT;

-- Migration Notes:
-- 1. agency_id populated from reliefrqst.agency_id for data consistency
-- 2. tracking_no generated as zero-padded reliefpkg_id (can be customized later)
-- 3. eligible_event_id populated from reliefrqst.eligible_event_id
-- 4. Status codes: A=Draft, P=Processing, C=Completed, V=Verified, D=Dispatched, R=Received
-- 5. All foreign keys added with proper referential integrity
