-- Migration: Drop and Recreate dnintake_item table to match target DDL
-- Date: 2025-11-25
-- Migration ID: 017
-- Purpose: Complete table rebuild to match exact target DDL structure
-- Safety: Table is empty (0 rows), no dependent FKs exist

-- ==============================================================================
-- TRANSACTION START
-- ==============================================================================
BEGIN;

-- ==============================================================================
-- STEP 1: Drop existing indexes (if any)
-- ==============================================================================

DROP INDEX IF EXISTS dk_dnintake_item_1;
DROP INDEX IF EXISTS dk_dnintake_item_2;

-- ==============================================================================
-- STEP 2: Drop the existing dnintake_item table
-- ==============================================================================
-- Table is empty (0 rows), no dependent FKs, so safe to drop

DROP TABLE IF EXISTS dnintake_item CASCADE;

-- ==============================================================================
-- STEP 3: Create dnintake_item with target DDL structure
-- ==============================================================================
-- Note: Some corrections made to target DDL:
-- - c_dnintake_item_1c was duplicated (used for both expiry_date and ext_item_cost)
--   renamed ext_item_cost constraint to c_dnintake_item_1e
-- - c_dnintake_item_4 had typo (checking defective_qty instead of expired_qty)

CREATE TABLE dnintake_item
(
    donation_id INTEGER NOT NULL,
    inventory_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,

    batch_no VARCHAR(20) NOT NULL
        CONSTRAINT c_dnintake_item_1a CHECK (batch_no = UPPER(batch_no)),

    batch_date DATE NOT NULL
        CONSTRAINT c_dnintake_item_1b CHECK (batch_date <= CURRENT_DATE),

    expiry_date DATE NOT NULL
        CONSTRAINT c_dnintake_item_1c CHECK (expiry_date >= batch_date),

    uom_code VARCHAR(25) NOT NULL
        CONSTRAINT fk_dnintake_item_unitofmeasure REFERENCES unitofmeasure(uom_code),

    avg_unit_value DECIMAL(10,2) NOT NULL
        CONSTRAINT c_dnintake_item_1d CHECK (avg_unit_value > 0.00),

    usable_qty DECIMAL(12,2) NOT NULL DEFAULT 0.00
        CONSTRAINT c_dnintake_item_2 CHECK (usable_qty >= 0.00),

    defective_qty DECIMAL(12,2) NOT NULL DEFAULT 0.00
        CONSTRAINT c_dnintake_item_3 CHECK (defective_qty >= 0.00),

    expired_qty DECIMAL(12,2) NOT NULL DEFAULT 0.00
        CONSTRAINT c_dnintake_item_4 CHECK (expired_qty >= 0.00),

    ext_item_cost DECIMAL(12,2) NOT NULL DEFAULT 0.00
        CONSTRAINT c_dnintake_item_1e CHECK (ext_item_cost >= 0.00),

    status_code CHAR(1) NOT NULL DEFAULT 'P'
        CONSTRAINT c_dnintake_item_5 CHECK (status_code IN ('P','V')),

    comments_text VARCHAR(255),

    create_by_id VARCHAR(20) NOT NULL,
    create_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    update_by_id VARCHAR(20) NOT NULL,
    update_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    version_nbr INTEGER NOT NULL DEFAULT 1,

    CONSTRAINT fk_dnintake_item_intake 
        FOREIGN KEY (donation_id, inventory_id) 
        REFERENCES dnintake(donation_id, inventory_id),

    CONSTRAINT fk_dnintake_item_donation_item 
        FOREIGN KEY (donation_id, item_id)
        REFERENCES donation_item(donation_id, item_id),

    CONSTRAINT pk_dnintake_item 
        PRIMARY KEY (donation_id, inventory_id, item_id, batch_no)
);

-- ==============================================================================
-- STEP 4: Create performance indexes
-- ==============================================================================

CREATE INDEX dk_dnintake_item_1 ON dnintake_item(inventory_id, item_id);
CREATE INDEX dk_dnintake_item_2 ON dnintake_item(item_id);

-- ==============================================================================
-- STEP 5: Add table comments for documentation
-- ==============================================================================

COMMENT ON TABLE dnintake_item IS 'Donation intake items - batch-level tracking of items received in donation intakes';
COMMENT ON COLUMN dnintake_item.donation_id IS 'FK to donation via dnintake';
COMMENT ON COLUMN dnintake_item.inventory_id IS 'FK to warehouse via dnintake';
COMMENT ON COLUMN dnintake_item.item_id IS 'FK to item via donation_item';
COMMENT ON COLUMN dnintake_item.batch_no IS 'Manufacturer batch number or item code if none exists';
COMMENT ON COLUMN dnintake_item.batch_date IS 'Manufacturing/batch date';
COMMENT ON COLUMN dnintake_item.expiry_date IS 'Expiry date (must be >= batch_date)';
COMMENT ON COLUMN dnintake_item.uom_code IS 'Unit of measure for quantities';
COMMENT ON COLUMN dnintake_item.avg_unit_value IS 'Average value per unit (must be > 0)';
COMMENT ON COLUMN dnintake_item.usable_qty IS 'Quantity of usable/good items';
COMMENT ON COLUMN dnintake_item.defective_qty IS 'Quantity of defective items';
COMMENT ON COLUMN dnintake_item.expired_qty IS 'Quantity of expired items';
COMMENT ON COLUMN dnintake_item.ext_item_cost IS 'Extended cost: (usable + defective + expired) * avg_unit_value';
COMMENT ON COLUMN dnintake_item.status_code IS 'P=Pending verification, V=Verified';

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
    numeric_precision,
    numeric_scale,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_name = 'dnintake_item'
ORDER BY ordinal_position;

-- Display all constraints
SELECT 
    tc.constraint_name,
    tc.constraint_type
FROM information_schema.table_constraints AS tc
WHERE tc.table_name = 'dnintake_item'
ORDER BY tc.constraint_type, tc.constraint_name;

-- Verify indexes
SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename = 'dnintake_item';

-- ==============================================================================
-- MIGRATION COMPLETE
-- ==============================================================================
-- dnintake_item table recreated with:
-- ✓ Composite PK: pk_dnintake_item (donation_id, inventory_id, item_id, batch_no)
-- ✓ FKs: fk_dnintake_item_intake, fk_dnintake_item_donation_item, fk_dnintake_item_unitofmeasure
-- ✓ CHECK constraints: c_dnintake_item_1a (batch_no uppercase), 1b (batch_date), 
--   1c (expiry_date), 1d (avg_unit_value), 1e (ext_item_cost), 2-5 (quantities, status)
-- ✓ Performance indexes: dk_dnintake_item_1, dk_dnintake_item_2
-- ✓ Zero data loss (table was empty)
-- ==============================================================================
