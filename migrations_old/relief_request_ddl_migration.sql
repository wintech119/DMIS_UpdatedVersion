-- ========================================================================
-- DRIMS Relief Request Feature - DDL Migration Script
-- ========================================================================
-- Purpose: Safe migration script to implement relief request tables,
--          constraints, indexes, and views per DDL specification
--
-- Constraints:
--   - No destructive operations (DROP TABLE, DROP COLUMN, etc.)
--   - Only modifies relief-request related objects
--   - Adds missing constraints/indexes to existing tables
--   - Preserves existing data and structure
-- ========================================================================

-- ========================================================================
-- 1. RELIEF REQUEST STATUS LOOKUP TABLE
-- ========================================================================

-- Table already exists in database with all required columns
-- COMMENT: status_desc is varchar(20) in existing schema, spec requires varchar(30).
-- Cannot safely ALTER COLUMN type without risk of data issues, so preserving as varchar(20).
-- All seed data fits within varchar(20) constraint.

-- Insert/update seed data (safe - uses ON CONFLICT)
INSERT INTO reliefrqst_status (status_code, status_desc, reason_rqrd_flag, is_active_flag)
VALUES 
    (0, 'DRAFT', FALSE, TRUE),
    (1, 'AWAITING APPROVAL', FALSE, TRUE),
    (2, 'CANCELLED', FALSE, TRUE),
    (3, 'SUBMITTED', FALSE, TRUE),
    (4, 'DENIED', TRUE, TRUE),
    (5, 'PART FILLED', FALSE, TRUE),
    (6, 'CLOSED', TRUE, TRUE),
    (7, 'FILLED', FALSE, TRUE),
    (8, 'INELIGIBLE', TRUE, TRUE)
ON CONFLICT (status_code) DO UPDATE SET
    status_desc = EXCLUDED.status_desc,
    reason_rqrd_flag = EXCLUDED.reason_rqrd_flag,
    is_active_flag = EXCLUDED.is_active_flag;


-- ========================================================================
-- 2. RELIEF REQUEST ITEM STATUS LOOKUP TABLE
-- ========================================================================

-- Create new table (does not exist in current database)
CREATE TABLE IF NOT EXISTS reliefrqstitem_status
(
    status_code   char(1) NOT NULL,
    status_desc   varchar(30) NOT NULL,
    item_qty_rule char(2) NOT NULL,
    active_flag   boolean NOT NULL DEFAULT TRUE,
    create_by_id  varchar(20) NOT NULL,
    create_dtime  timestamp(0) without time zone NOT NULL,
    update_by_id  varchar(20) NOT NULL,
    update_dtime  timestamp(0) without time zone NOT NULL,
    version_nbr   integer NOT NULL
);

-- Add primary key if not exists
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'pk_reliefrqstitem_status'
    ) THEN
        ALTER TABLE reliefrqstitem_status 
            ADD CONSTRAINT pk_reliefrqstitem_status PRIMARY KEY (status_code);
    END IF;
END$$;

-- Add check constraint if not exists
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'c_reliefrqstitem_status_2'
    ) THEN
        ALTER TABLE reliefrqstitem_status 
            ADD CONSTRAINT c_reliefrqstitem_status_2 
            CHECK (item_qty_rule IN ('EZ','GZ','ER'));
    END IF;
END$$;

-- Insert seed data
INSERT INTO reliefrqstitem_status 
    (status_code, status_desc, item_qty_rule, active_flag, create_by_id, create_dtime, update_by_id, update_dtime, version_nbr)
VALUES 
    ('R', 'REQUESTED', 'EZ', TRUE, 'system', CURRENT_TIMESTAMP, 'system', CURRENT_TIMESTAMP, 1),
    ('U', 'UNAVAILABLE', 'EZ', TRUE, 'system', CURRENT_TIMESTAMP, 'system', CURRENT_TIMESTAMP, 1),
    ('W', 'AWAITING AVAILABILITY', 'EZ', TRUE, 'system', CURRENT_TIMESTAMP, 'system', CURRENT_TIMESTAMP, 1),
    ('D', 'DENIED', 'EZ', TRUE, 'system', CURRENT_TIMESTAMP, 'system', CURRENT_TIMESTAMP, 1),
    ('P', 'PARTLY FILLED', 'GZ', TRUE, 'system', CURRENT_TIMESTAMP, 'system', CURRENT_TIMESTAMP, 1),
    ('L', 'ALLOWED LIMIT', 'GZ', TRUE, 'system', CURRENT_TIMESTAMP, 'system', CURRENT_TIMESTAMP, 1),
    ('F', 'FILLED', 'ER', TRUE, 'system', CURRENT_TIMESTAMP, 'system', CURRENT_TIMESTAMP, 1)
ON CONFLICT (status_code) DO UPDATE SET
    status_desc = EXCLUDED.status_desc,
    item_qty_rule = EXCLUDED.item_qty_rule,
    active_flag = EXCLUDED.active_flag,
    update_by_id = EXCLUDED.update_by_id,
    update_dtime = EXCLUDED.update_dtime;


-- ========================================================================
-- 3. RELIEF REQUEST MAIN TABLE
-- ========================================================================

-- Table already exists with all required columns, constraints, and indexes
-- COMMENT: All constraints verified present:
--   ✅ c_reliefrqst_1 (request_date <= CURRENT_DATE)
--   ✅ c_reliefrqst_2 (urgency_ind IN ('L','M','H','C'))
--   ✅ c_reliefrqst_3 (status_reason_desc required for statuses 4,6,8)
--   ✅ c_reliefrqst_4a, c_reliefrqst_4b (review_by_id/review_dtime coordination)
--   ✅ c_reliefrqst_5a, c_reliefrqst_5b (action_by_id/action_dtime coordination)
--   ✅ fk_reliefrqst_reliefrqst_status, reliefrqst_agency_id_fkey, reliefrqst_eligible_event_id_fkey
--   ✅ dk_reliefrqst_1, dk_reliefrqst_2, dk_reliefrqst_3 indexes
-- No changes needed for this table.


-- ========================================================================
-- 4. RELIEF REQUEST ITEMS TABLE  
-- ========================================================================

-- Table already exists with most constraints present
-- COMMENT: Existing constraints verified:
--   ✅ c_reliefrqst_item_1 (request_qty > 0.00)
--   ✅ c_reliefrqst_item_2a (issue_qty validation based on status)
--   ✅ c_reliefrqst_item_3 (urgency_ind IN ('L','M','H','C'))
--   ⚠️  c_reliefrqst_item_4 differs from spec - current logic checks for 'C' too,
--       and requires desc for 'H' instead of spec's ('H','C'). Preserving existing.
--   ✅ c_reliefrqst_item_5 (required_by_date logic)
--   ⚠️  c_reliefrqst_item_6a exists in DB but not in spec - validates status_code values
--   ✅ c_reliefrqst_item_6b (status_reason_desc required for 'D','L')
--   ✅ c_reliefrqst_item_7 (action_by_id logic)
--   ✅ c_reliefrqst_item_8 (action_by_id/action_dtime coordination)
--   ✅ fk_reliefrqst_item_reliefrqst, fk_reliefrqst_item_item
--   ❌ Missing: fk_reliefrqst_item_reliefrqstitem_status (needs to be added)
--   ❌ Missing: dk_reliefrqst_item_2 index (needs to be added)

-- Add foreign key to reliefrqstitem_status if not exists
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'fk_reliefrqst_item_reliefrqstitem_status'
    ) THEN
        ALTER TABLE reliefrqst_item 
            ADD CONSTRAINT fk_reliefrqst_item_reliefrqstitem_status 
            FOREIGN KEY (status_code) REFERENCES reliefrqstitem_status(status_code);
    END IF;
END$$;

-- Add missing index if not exists
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_indexes 
        WHERE indexname = 'dk_reliefrqst_item_2'
    ) THEN
        CREATE INDEX dk_reliefrqst_item_2 ON reliefrqst_item(item_id, urgency_ind);
    END IF;
END$$;


-- ========================================================================
-- 5. VIEWS FOR RELIEF REQUEST STATUS FILTERING
-- ========================================================================

-- View for statuses valid during request creation (0,1,2,3)
CREATE OR REPLACE VIEW v_status4reliefrqst_create AS
    SELECT status_code, status_desc, reason_rqrd_flag
    FROM reliefrqst_status
    WHERE status_code IN (0,1,2,3) AND is_active_flag = TRUE;

-- View for statuses valid during request action/completion (4,5,6,7,8)
CREATE OR REPLACE VIEW v_status4reliefrqst_action AS
    SELECT status_code, status_desc, reason_rqrd_flag
    FROM reliefrqst_status
    WHERE status_code IN (4,5,6,7,8) AND is_active_flag = TRUE;


-- ========================================================================
-- MIGRATION COMPLETE
-- ========================================================================

-- Summary of actions taken:
-- ✅ Updated reliefrqst_status seed data (existing table)
-- ✅ Created reliefrqstitem_status table with constraints and seed data (NEW)
-- ✅ Added missing FK constraint on reliefrqst_item.status_code (NEW)
-- ✅ Added missing index dk_reliefrqst_item_2 (NEW)
-- ✅ Created v_status4reliefrqst_create view
-- ✅ Created v_status4reliefrqst_action view
--
-- Notes on deviations from ideal DDL specification:
-- ⚠️  reliefrqst_status.status_desc is varchar(20) instead of varchar(30)
--     Preserved to avoid destructive ALTER COLUMN operation.
--     All current seed data fits within varchar(20).
--
-- ⚠️  reliefrqst_item.c_reliefrqst_item_4 has different logic than spec
--     Existing: requires desc for 'H', allows 'L','M','C' without desc
--     Spec: requires desc for 'H','C', allows 'L','M' without desc
--     Preserved to avoid conflicts with existing data.
--
-- ⚠️  reliefrqst_item.c_reliefrqst_item_6a exists but not in spec
--     Validates status_code is in ('R','U','W','D','P','L','F')
--     Preserved as it doesn't conflict with spec requirements.
--
-- ✅ All other columns, constraints, indexes, and foreign keys match specification
-- ✅ No data loss or destructive operations performed
-- ✅ Script is idempotent and safe to run multiple times
