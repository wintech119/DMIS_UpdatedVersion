-- Migration 009: Alter reliefrqst_status table
-- Changes:
-- 1. Expand status_desc from VARCHAR(20) to VARCHAR(30)
-- 2. Update reason_rqrd_flag for statuses 4, 6, 8 to TRUE
-- 3. Insert missing status 9 (PROCESSED)
-- 4. Create missing view v_status4reliefrqst_processed
-- Referential integrity maintained: reliefrqst table references this table

BEGIN;

-- Step 1: Alter column to increase size
ALTER TABLE reliefrqst_status 
    ALTER COLUMN status_desc TYPE VARCHAR(30);

-- Step 2: Update reason_rqrd_flag for statuses that require reasons
-- Status 4 (DENIED), 6 (CLOSED), 8 (INELIGIBLE) should require reasons
UPDATE reliefrqst_status SET reason_rqrd_flag = TRUE WHERE status_code = 4; -- DENIED
UPDATE reliefrqst_status SET reason_rqrd_flag = TRUE WHERE status_code = 6; -- CLOSED
UPDATE reliefrqst_status SET reason_rqrd_flag = TRUE WHERE status_code = 8; -- INELIGIBLE

-- Step 3: Insert missing status 9 (PROCESSED)
INSERT INTO reliefrqst_status (status_code, status_desc, reason_rqrd_flag, is_active_flag)
VALUES (9, 'PROCESSED', FALSE, TRUE)
ON CONFLICT (status_code) DO NOTHING;

-- Step 4: Drop existing views if they exist (will be recreated)
DROP VIEW IF EXISTS v_status4reliefrqst_create CASCADE;
DROP VIEW IF EXISTS v_status4reliefrqst_action CASCADE;
DROP VIEW IF EXISTS v_status4reliefrqst_processed CASCADE;

-- Step 5: Create view for request creation statuses (0,1,2,3)
CREATE VIEW v_status4reliefrqst_create AS
    SELECT status_code, status_desc, reason_rqrd_flag
    FROM reliefrqst_status
    WHERE status_code IN (0,1,2,3) AND is_active_flag = TRUE;

-- Step 6: Create view for request action statuses (4,5,6,7,8)
CREATE VIEW v_status4reliefrqst_action AS
    SELECT status_code, status_desc, reason_rqrd_flag
    FROM reliefrqst_status
    WHERE status_code IN (4,5,6,7,8) AND is_active_flag = TRUE;

-- Step 7: Create view for processed requests (9)
CREATE VIEW v_status4reliefrqst_processed AS
    SELECT status_code, status_desc, reason_rqrd_flag
    FROM reliefrqst_status
    WHERE status_code IN (9) AND is_active_flag = TRUE;

-- Step 8: Verify all changes
DO $$
BEGIN
    -- Verify status_desc is VARCHAR(30)
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'reliefrqst_status' 
        AND column_name = 'status_desc' 
        AND character_maximum_length = 30
    ) THEN
        RAISE EXCEPTION 'status_desc column not updated to VARCHAR(30)';
    END IF;
    
    -- Verify status 9 exists
    IF NOT EXISTS (
        SELECT 1 FROM reliefrqst_status WHERE status_code = 9
    ) THEN
        RAISE EXCEPTION 'Status 9 (PROCESSED) not inserted';
    END IF;
    
    -- Verify all views exist
    IF NOT EXISTS (
        SELECT 1 FROM pg_views WHERE viewname = 'v_status4reliefrqst_create'
    ) THEN
        RAISE EXCEPTION 'View v_status4reliefrqst_create not created';
    END IF;
    
    IF NOT EXISTS (
        SELECT 1 FROM pg_views WHERE viewname = 'v_status4reliefrqst_action'
    ) THEN
        RAISE EXCEPTION 'View v_status4reliefrqst_action not created';
    END IF;
    
    IF NOT EXISTS (
        SELECT 1 FROM pg_views WHERE viewname = 'v_status4reliefrqst_processed'
    ) THEN
        RAISE EXCEPTION 'View v_status4reliefrqst_processed not created';
    END IF;
END $$;

COMMIT;

-- Status Code Meanings:
-- 0 = DRAFT (creation workflow)
-- 1 = AWAITING APPROVAL (creation workflow)
-- 2 = CANCELLED (creation workflow)
-- 3 = SUBMITTED (creation workflow)
-- 4 = DENIED (action workflow, requires reason)
-- 5 = PART FILLED (action workflow)
-- 6 = CLOSED (action workflow, requires reason)
-- 7 = FILLED (action workflow)
-- 8 = INELIGIBLE (action workflow, requires reason)
-- 9 = PROCESSED (processed workflow)
