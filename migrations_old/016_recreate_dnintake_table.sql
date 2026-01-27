-- Migration: Drop and Recreate dnintake table to match target DDL
-- Date: 2025-11-25
-- Migration ID: 016
-- Purpose: Complete table rebuild to match exact target DDL structure
-- Safety: Table is empty (0 rows), dependent FK from dnintake_item properly handled

-- ==============================================================================
-- TRANSACTION START
-- ==============================================================================
BEGIN;

-- ==============================================================================
-- STEP 1: Drop FK from dnintake_item referencing dnintake
-- ==============================================================================
-- dnintake_item has composite FK: (donation_id, inventory_id) → dnintake(donation_id, inventory_id)

ALTER TABLE dnintake_item 
DROP CONSTRAINT IF EXISTS fk_dnintake_item_intake;

-- ==============================================================================
-- STEP 2: Drop the existing dnintake table
-- ==============================================================================
-- Table is empty (0 rows), so no data loss

DROP TABLE IF EXISTS dnintake CASCADE;

-- ==============================================================================
-- STEP 3: Create dnintake with target DDL structure
-- ==============================================================================

CREATE TABLE dnintake
(
    donation_id INTEGER NOT NULL
        CONSTRAINT fk_dnintake_donation REFERENCES donation(donation_id),

    inventory_id INTEGER NOT NULL
        CONSTRAINT fk_dnintake_warehouse REFERENCES warehouse(warehouse_id),

    intake_date DATE NOT NULL
        CONSTRAINT c_dnintake_1 CHECK (intake_date <= CURRENT_DATE),

    comments_text VARCHAR(255),

    status_code CHAR(1) NOT NULL DEFAULT 'I'
        CONSTRAINT c_dnintake_2 CHECK (status_code IN ('I','C','V')),

    create_by_id VARCHAR(20) NOT NULL,
    create_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    update_by_id VARCHAR(20) NOT NULL,
    update_dtime TIMESTAMP(0) WITHOUT TIME ZONE,
    verify_by_id VARCHAR(20) NOT NULL,
    verify_dtime TIMESTAMP(0) WITHOUT TIME ZONE,
    version_nbr INTEGER NOT NULL DEFAULT 1,

    CONSTRAINT pk_dnintake PRIMARY KEY (donation_id, inventory_id)
);

-- ==============================================================================
-- STEP 4: Re-add FK from dnintake_item to dnintake
-- ==============================================================================

ALTER TABLE dnintake_item
ADD CONSTRAINT fk_dnintake_item_intake 
    FOREIGN KEY (donation_id, inventory_id) 
    REFERENCES dnintake(donation_id, inventory_id);

-- ==============================================================================
-- STEP 5: Add table comments for documentation
-- ==============================================================================

COMMENT ON TABLE dnintake IS 'Donation intake records - tracks when donations are received at warehouses';
COMMENT ON COLUMN dnintake.donation_id IS 'FK to donation being received';
COMMENT ON COLUMN dnintake.inventory_id IS 'FK to warehouse where donation is received (warehouse_id)';
COMMENT ON COLUMN dnintake.intake_date IS 'Date donation was received at warehouse';
COMMENT ON COLUMN dnintake.comments_text IS 'Optional comments about the intake';
COMMENT ON COLUMN dnintake.status_code IS 'I=Incomplete, C=Completed, V=Verified';

-- ==============================================================================
-- TRANSACTION COMMIT
-- ==============================================================================
COMMIT;

-- ==============================================================================
-- VERIFICATION QUERIES
-- ==============================================================================

-- Verify new table structure
SELECT 
    column_name,
    data_type,
    character_maximum_length,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_name = 'dnintake'
ORDER BY ordinal_position;

-- Display all constraints
SELECT 
    tc.constraint_name,
    tc.constraint_type
FROM information_schema.table_constraints AS tc
WHERE tc.table_name = 'dnintake'
ORDER BY tc.constraint_type, tc.constraint_name;

-- Verify FK from dnintake_item is restored
SELECT 
    tc.table_name AS referencing_table,
    tc.constraint_name,
    ccu.table_name AS references_table
FROM information_schema.table_constraints AS tc
JOIN information_schema.constraint_column_usage AS ccu
    ON ccu.constraint_name = tc.constraint_name
WHERE tc.constraint_type = 'FOREIGN KEY'
    AND ccu.table_name = 'dnintake';

-- ==============================================================================
-- MIGRATION COMPLETE
-- ==============================================================================
-- dnintake table recreated with:
-- ✓ Composite PK (donation_id, inventory_id) named pk_dnintake
-- ✓ FK fk_dnintake_donation → donation(donation_id)
-- ✓ FK fk_dnintake_warehouse → warehouse(warehouse_id)
-- ✓ CHECK constraints: c_dnintake_1 (intake_date), c_dnintake_2 (status_code)
-- ✓ Status codes: I=Incomplete, C=Completed, V=Verified
-- ✓ Dependent FK restored: fk_dnintake_item_intake from dnintake_item
-- ✓ Zero data loss (table was empty)
-- ==============================================================================
