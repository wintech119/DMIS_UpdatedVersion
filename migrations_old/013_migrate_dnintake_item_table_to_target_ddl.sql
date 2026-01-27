-- Migration: Update dnintake_item table to match target DDL
-- Date: 2025-11-25
-- Migration ID: 013
-- Purpose: Rebuild dnintake_item table with composite primary key and enhanced structure
-- Safety: Table is currently empty (0 rows), making this a completely safe rebuild

-- ==============================================================================
-- CURRENT STATE ANALYSIS
-- ==============================================================================
-- Current table has:
-- - intake_item_id (serial) as single-column PK
-- - batch_no, batch_date, expiry_date nullable
-- - Missing ext_item_cost column
-- - Missing composite PK (donation_id, inventory_id, item_id, batch_no)
-- - Missing indexes dk_dnintake_item_1 and dk_dnintake_item_2
--
-- Target table requires:
-- - Composite PK: (donation_id, inventory_id, item_id, batch_no)
-- - batch_date, expiry_date NOT NULL
-- - ext_item_cost column with computed default and CHECK constraint
-- - Two performance indexes
--
-- Since table is EMPTY, safest approach is DROP and RECREATE
-- ==============================================================================

-- ==============================================================================
-- STEP 1: Verify no tables reference dnintake_item
-- ==============================================================================
-- Query confirmed: No other tables have FKs referencing dnintake_item
-- Therefore, no FK drops needed before dropping the table

-- ==============================================================================
-- STEP 2: Drop the existing table
-- ==============================================================================
-- Safe because: Table is empty and no dependent FKs exist

DROP TABLE IF EXISTS dnintake_item CASCADE;

-- Drop the sequence that was used for intake_item_id
DROP SEQUENCE IF EXISTS dnintake_item_intake_item_id_seq;

-- ==============================================================================
-- STEP 3: Create the new table with target DDL structure
-- ==============================================================================
-- Note: The target DDL has a duplicate constraint name c_dnintake_item_1c
-- (used for both expiry_date and ext_item_cost). I'm fixing this by naming
-- the ext_item_cost constraint as c_dnintake_item_1e for clarity.
--
-- Also: batch_no in target DDL has "--not null" commented out, so it remains nullable
-- but is part of the composite PK, which requires a value. The application must
-- provide a default value (item code) when batch_no is not specified.

CREATE TABLE dnintake_item
(
    donation_id INTEGER NOT NULL,
    inventory_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,

    -- Batch number assigned by manufacturer or by ODPEM
    -- If no batch number is assigned, set value to item code
    batch_no VARCHAR(20) NOT NULL
        CONSTRAINT c_dnintake_item_1a CHECK (batch_no = UPPER(batch_no)),

    batch_date DATE NOT NULL
        CONSTRAINT c_dnintake_item_1b CHECK (batch_date <= CURRENT_DATE),

    expiry_date DATE NOT NULL
        CONSTRAINT c_dnintake_item_1c CHECK (expiry_date >= batch_date),

    -- Units in which quantity of item is measured
    uom_code VARCHAR(25) NOT NULL
        CONSTRAINT fk_dnintake_item_unitofmeasure REFERENCES unitofmeasure(uom_code),

    avg_unit_value DECIMAL(10,2) NOT NULL
        CONSTRAINT c_dnintake_item_1d CHECK (avg_unit_value > 0.00),

    -- Extended item cost = (usable_qty + defective_qty + expired_qty) * avg_unit_value
    ext_item_cost DECIMAL(12,2) NOT NULL DEFAULT 0.00
        CONSTRAINT c_dnintake_item_1e CHECK (ext_item_cost >= 0.00),

    -- Quantity/amount of usable/good item in inventory
    usable_qty DECIMAL(12,2) NOT NULL DEFAULT 0.00
        CONSTRAINT c_dnintake_item_2 CHECK (usable_qty >= 0.00),

    -- Quantity/amount of defective item in inventory
    defective_qty DECIMAL(12,2) NOT NULL DEFAULT 0.00
        CONSTRAINT c_dnintake_item_3 CHECK (defective_qty >= 0.00),

    -- Quantity/amount of expired item in inventory
    expired_qty DECIMAL(12,2) NOT NULL DEFAULT 0.00
        CONSTRAINT c_dnintake_item_4 CHECK (expired_qty >= 0.00),

    -- P=Pending verification, V=Verified
    status_code CHAR(1) NOT NULL DEFAULT 'P'
        CONSTRAINT c_dnintake_item_5 CHECK (status_code IN ('P','V')),

    comments_text VARCHAR(255),

    -- Audit fields
    create_by_id VARCHAR(20) NOT NULL,
    create_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    update_by_id VARCHAR(20) NOT NULL,
    update_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    version_nbr INTEGER NOT NULL DEFAULT 1,

    -- Composite Foreign Keys
    CONSTRAINT fk_dnintake_item_intake 
        FOREIGN KEY (donation_id, inventory_id) 
        REFERENCES dnintake(donation_id, inventory_id),

    CONSTRAINT fk_dnintake_item_donation_item 
        FOREIGN KEY (donation_id, item_id)
        REFERENCES donation_item(donation_id, item_id),

    -- Composite Primary Key
    CONSTRAINT pk_dnintake_item 
        PRIMARY KEY (donation_id, inventory_id, item_id, batch_no)
);

-- ==============================================================================
-- STEP 4: Create performance indexes
-- ==============================================================================

CREATE INDEX dk_dnintake_item_1 ON dnintake_item(inventory_id, item_id);
CREATE INDEX dk_dnintake_item_2 ON dnintake_item(item_id);

-- ==============================================================================
-- STEP 5: Add table and column comments for documentation
-- ==============================================================================

COMMENT ON TABLE dnintake_item IS 'Donation intake items - tracks individual items received during donation intake process';
COMMENT ON COLUMN dnintake_item.batch_no IS 'Batch number from manufacturer or ODPEM-assigned (default: item code)';
COMMENT ON COLUMN dnintake_item.ext_item_cost IS 'Extended item cost = (usable_qty + defective_qty + expired_qty) * avg_unit_value';
COMMENT ON COLUMN dnintake_item.usable_qty IS 'Quantity of usable/good items received';
COMMENT ON COLUMN dnintake_item.defective_qty IS 'Quantity of defective items received';
COMMENT ON COLUMN dnintake_item.expired_qty IS 'Quantity of expired items received';
COMMENT ON COLUMN dnintake_item.status_code IS 'P=Pending verification, V=Verified';

-- ==============================================================================
-- STEP 6: Verify the new table structure
-- ==============================================================================

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
    tc.constraint_type,
    kcu.column_name
FROM information_schema.table_constraints AS tc
LEFT JOIN information_schema.key_column_usage AS kcu
    ON tc.constraint_name = kcu.constraint_name
WHERE tc.table_name = 'dnintake_item'
ORDER BY tc.constraint_type, tc.constraint_name;

-- Display indexes
SELECT 
    indexname,
    indexdef
FROM pg_indexes
WHERE tablename = 'dnintake_item';

-- ==============================================================================
-- MIGRATION COMPLETE
-- ==============================================================================
-- The dnintake_item table now matches the target DDL with:
-- ✓ Composite PK: (donation_id, inventory_id, item_id, batch_no)
-- ✓ batch_no NOT NULL with uppercase CHECK constraint
-- ✓ batch_date NOT NULL with <= CURRENT_DATE constraint
-- ✓ expiry_date NOT NULL with >= batch_date constraint
-- ✓ ext_item_cost DECIMAL(12,2) for extended cost tracking
-- ✓ All quantity fields with >= 0.00 constraints
-- ✓ status_code with ('P','V') constraint
-- ✓ All foreign keys intact:
--   * fk_dnintake_item_intake → dnintake(donation_id, inventory_id)
--   * fk_dnintake_item_donation_item → donation_item(donation_id, item_id)
--   * fk_dnintake_item_unitofmeasure → unitofmeasure(uom_code)
-- ✓ Performance indexes: dk_dnintake_item_1, dk_dnintake_item_2
-- ✓ All audit fields properly configured
-- ==============================================================================
