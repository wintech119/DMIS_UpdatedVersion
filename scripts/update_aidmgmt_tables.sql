--
-- Migration script to update 5 AIDMGMT-3 tables to match aidmgmt-3.1.sql schema
-- Tables: transfer, agency, reliefrqst, reliefrqst_item, reliefpkg
-- DO NOT modify any other tables
--

BEGIN;

--
-- 1. UPDATE TRANSFER TABLE
--
-- Add new columns
ALTER TABLE transfer ADD COLUMN IF NOT EXISTS event_id INTEGER REFERENCES event(event_id);
ALTER TABLE transfer ADD COLUMN IF NOT EXISTS reason_text VARCHAR(255);

-- Drop old columns that don't exist in aidmgmt-3.1
ALTER TABLE transfer DROP COLUMN IF EXISTS transport_mode CASCADE;
ALTER TABLE transfer DROP COLUMN IF EXISTS comments_text CASCADE;

-- Update status_code check constraint to match aidmgmt-3.1 (D, C, V only)
ALTER TABLE transfer DROP CONSTRAINT IF EXISTS transfer_status_code_check;
ALTER TABLE transfer ADD CONSTRAINT c_transfer_2 CHECK (status_code IN ('D','C','V'));

-- Set default for transfer_date
ALTER TABLE transfer ALTER COLUMN transfer_date SET DEFAULT CURRENT_DATE;

--
-- 2. UPDATE AGENCY TABLE
--
-- Add new columns that are in aidmgmt-3.1
ALTER TABLE agency ADD COLUMN IF NOT EXISTS agency_type VARCHAR(16);
ALTER TABLE agency ADD COLUMN IF NOT EXISTS ineligible_event_id INTEGER REFERENCES event(event_id);
ALTER TABLE agency ADD COLUMN IF NOT EXISTS status_code CHAR(1);

-- Set defaults for existing rows before adding NOT NULL constraints
UPDATE agency SET agency_type = 'DISTRIBUTOR' WHERE agency_type IS NULL;
UPDATE agency SET status_code = 'A' WHERE status_code IS NULL;

-- Make columns NOT NULL as per aidmgmt-3.1
ALTER TABLE agency ALTER COLUMN agency_type SET NOT NULL;
ALTER TABLE agency ALTER COLUMN status_code SET NOT NULL;

-- Add check constraints
ALTER TABLE agency DROP CONSTRAINT IF EXISTS agency_agency_type_check;
ALTER TABLE agency ADD CONSTRAINT c_agency_3 CHECK (agency_type IN ('DISTRIBUTOR','SHELTER'));

ALTER TABLE agency DROP CONSTRAINT IF EXISTS agency_status_code_check;
ALTER TABLE agency ADD CONSTRAINT c_agency_5 CHECK (status_code IN ('A','I'));

--
-- 3. UPDATE RELIEFRQST TABLE  
--
-- Add new columns from aidmgmt-3.1
ALTER TABLE reliefrqst ADD COLUMN IF NOT EXISTS eligible_event_id INTEGER REFERENCES event(event_id);
ALTER TABLE reliefrqst ADD COLUMN IF NOT EXISTS rqst_notes_text TEXT;
ALTER TABLE reliefrqst ADD COLUMN IF NOT EXISTS review_notes_text TEXT;

-- Migrate status_code: Change 0 (Draft) to 1 (Awaiting approval) to match new schema
UPDATE reliefrqst SET status_code = 1 WHERE status_code = 0;

-- Update status_code check constraint to match aidmgmt-3.1 (1 to 7, not 0 to 7)
ALTER TABLE reliefrqst DROP CONSTRAINT IF EXISTS reliefrqst_status_code_check;
ALTER TABLE reliefrqst ADD CONSTRAINT c_reliefrqst_3 CHECK (status_code BETWEEN 1 AND 7);

-- Rename constraints to match aidmgmt-3.1 naming
ALTER TABLE reliefrqst DROP CONSTRAINT IF EXISTS reliefrqst_check;
ALTER TABLE reliefrqst ADD CONSTRAINT c_reliefrqst_4a 
  CHECK ((review_by_id IS NULL AND status_code < 2) OR (review_by_id IS NOT NULL AND status_code >= 2));

ALTER TABLE reliefrqst DROP CONSTRAINT IF EXISTS reliefrqst_check1;
ALTER TABLE reliefrqst ADD CONSTRAINT c_reliefrqst_4b
  CHECK ((review_by_id IS NULL AND review_dtime IS NULL) OR (review_by_id IS NOT NULL AND review_dtime IS NOT NULL));

ALTER TABLE reliefrqst DROP CONSTRAINT IF EXISTS reliefrqst_check2;
ALTER TABLE reliefrqst ADD CONSTRAINT c_reliefrqst_5a
  CHECK ((action_by_id IS NULL AND status_code < 4) OR (action_by_id IS NOT NULL AND status_code >= 4));

ALTER TABLE reliefrqst DROP CONSTRAINT IF EXISTS reliefrqst_check3;
ALTER TABLE reliefrqst ADD CONSTRAINT c_reliefrqst_5b
  CHECK ((action_by_id IS NULL AND action_dtime IS NULL) OR (action_by_id IS NOT NULL AND action_dtime IS NOT NULL));

--
-- 4. UPDATE RELIEFRQST_ITEM TABLE
--
-- Remove defaults that shouldn't be there per aidmgmt-3.1
ALTER TABLE reliefrqst_item ALTER COLUMN issue_qty DROP DEFAULT;
ALTER TABLE reliefrqst_item ALTER COLUMN status_code DROP DEFAULT;

-- Update check constraint names to match aidmgmt-3.1
ALTER TABLE reliefrqst_item DROP CONSTRAINT IF EXISTS reliefrqst_item_check;
ALTER TABLE reliefrqst_item ADD CONSTRAINT c_reliefrqst_item_2 
  CHECK (issue_qty <= request_qty);

ALTER TABLE reliefrqst_item DROP CONSTRAINT IF EXISTS reliefrqst_item_check1;
ALTER TABLE reliefrqst_item ADD CONSTRAINT c_reliefrqst_item_4
  CHECK ((rqst_reason_desc IS NOT NULL) OR (rqst_reason_desc IS NULL AND urgency_ind IN ('L','M')));

ALTER TABLE reliefrqst_item DROP CONSTRAINT IF EXISTS reliefrqst_item_check2;
ALTER TABLE reliefrqst_item ADD CONSTRAINT c_reliefrqst_item_5
  CHECK ((required_by_date IS NOT NULL) OR (required_by_date IS NULL AND urgency_ind IN ('L','M')));

ALTER TABLE reliefrqst_item DROP CONSTRAINT IF EXISTS reliefrqst_item_check3;
ALTER TABLE reliefrqst_item ADD CONSTRAINT c_reliefrqst_item_7
  CHECK ((action_by_id IS NULL AND status_code = 'R') OR (action_by_id IS NOT NULL AND status_code != 'R'));

ALTER TABLE reliefrqst_item DROP CONSTRAINT IF EXISTS reliefrqst_item_check4;
ALTER TABLE reliefrqst_item ADD CONSTRAINT c_reliefrqst_item_8
  CHECK ((action_by_id IS NULL AND action_dtime IS NULL) OR (action_by_id IS NOT NULL AND action_dtime IS NOT NULL));

-- Add missing index from aidmgmt-3.1
CREATE INDEX IF NOT EXISTS dk_reliefrqst_item_2 ON reliefrqst_item(item_id, urgency_ind);

--
-- 5. UPDATE RELIEFPKG TABLE
--
-- Add new columns for 'Received' status tracking
ALTER TABLE reliefpkg ADD COLUMN IF NOT EXISTS received_by_id VARCHAR(20);
ALTER TABLE reliefpkg ADD COLUMN IF NOT EXISTS received_dtime TIMESTAMP(0) WITHOUT TIME ZONE;

-- Set default to empty string for existing rows before making NOT NULL
UPDATE reliefpkg SET received_by_id = '' WHERE received_by_id IS NULL;

-- Make received_by_id NOT NULL as per aidmgmt-3.1
ALTER TABLE reliefpkg ALTER COLUMN received_by_id SET NOT NULL;

-- Update status_code check constraint to include 'R' for Received
ALTER TABLE reliefpkg DROP CONSTRAINT IF EXISTS reliefpkg_status_code_check;
ALTER TABLE reliefpkg ADD CONSTRAINT c_reliefpkg_3 CHECK (status_code IN ('P','C','V','D','R'));

-- Update dispatch_dtime check constraint to match aidmgmt-3.1 logic
ALTER TABLE reliefpkg DROP CONSTRAINT IF EXISTS reliefpkg_check;
ALTER TABLE reliefpkg ADD CONSTRAINT c_reliefpkg_2
  CHECK ((dispatch_dtime IS NULL AND status_code != 'D') OR (dispatch_dtime IS NOT NULL AND status_code = 'D'));

COMMIT;

-- Validation: Show updated table structures
\echo ''
\echo '======================================================================='
\echo 'MIGRATION COMPLETED SUCCESSFULLY'
\echo '======================================================================='
\echo ''
\echo '=== TRANSFER TABLE ==='
\d transfer

\echo ''
\echo '=== AGENCY TABLE ==='
\d agency

\echo ''
\echo '=== RELIEFRQST TABLE ==='
\d reliefrqst

\echo ''
\echo '=== RELIEFRQST_ITEM TABLE ==='
\d reliefrqst_item

\echo ''
\echo '=== RELIEFPKG TABLE ==='
\d reliefpkg
