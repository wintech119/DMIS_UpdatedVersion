-- Migration 008: Drop and recreate dnintake_item table with corrected schema
-- Changes:
-- 1. Fix quantity precision from DECIMAL(15,4) to DECIMAL(12,2) as per spec
-- 2. Fix avg_unit_value constraint from >= to > (must be positive)
-- 3. Fix c_dnintake_item_4 constraint bug (was checking defective_qty instead of expired_qty)
-- 4. Add missing expiry_date constraint (c_dnintake_item_1c)

BEGIN;

-- Step 1: Drop existing table (no dependencies, 0 rows)
DROP TABLE IF EXISTS dnintake_item CASCADE;

-- Step 2: Create dnintake_item table with correct schema
CREATE TABLE dnintake_item
(
    donation_id INTEGER NOT NULL,
    inventory_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,

    -- Batch number assigned by manufacturer or by ODPEM (where there is no batch number).
    -- If no batch number is assigned, set value of field to item code.
    -- If batch does not exist, create it with a batch id and zero quantities (i.e. empty).
    -- Update batch amounts with the amounts being taken in.
    
    batch_no VARCHAR(20) NOT NULL
        CONSTRAINT c_dnintake_item_1a CHECK (batch_no = UPPER(batch_no)),
    batch_date DATE NOT NULL
        CONSTRAINT c_dnintake_item_1b CHECK (batch_date <= CURRENT_DATE),
    expiry_date DATE 
        CONSTRAINT c_dnintake_item_1c CHECK (expiry_date >= CURRENT_DATE OR expiry_date IS NULL),

    -- Units in which quantity of item is measured
    uom_code VARCHAR(25) NOT NULL
        CONSTRAINT fk_dnintake_item_unitofmeasure REFERENCES unitofmeasure(uom_code),

    avg_unit_value DECIMAL(10,2) NOT NULL
        CONSTRAINT c_dnintake_item_1d CHECK (avg_unit_value > 0.00),
    
    -- Quantity/amount of usable/good item in inventory
    usable_qty DECIMAL(12,2) NOT NULL
        CONSTRAINT c_dnintake_item_2 CHECK (usable_qty >= 0.00),
    
    -- Quantity/amount of defective item in inventory
    defective_qty DECIMAL(12,2) NOT NULL
        CONSTRAINT c_dnintake_item_3 CHECK (defective_qty >= 0.00),
    
    -- Quantity/amount of expired item in inventory
    expired_qty DECIMAL(12,2) NOT NULL
        CONSTRAINT c_dnintake_item_4 CHECK (expired_qty >= 0.00),

    status_code CHAR(1) NOT NULL
        -- P=Processed, V=Verified
        CONSTRAINT c_dnintake_item_5 CHECK (status_code IN ('P','V')),
    comments_text VARCHAR(255),

    create_by_id VARCHAR(20) NOT NULL,
    create_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    update_by_id VARCHAR(20) NOT NULL,
    update_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    version_nbr INTEGER NOT NULL,

    CONSTRAINT fk_dnintake_item_intake FOREIGN KEY (donation_id, inventory_id) 
        REFERENCES dnintake(donation_id, inventory_id),
    CONSTRAINT fk_dnintake_item_donation_item FOREIGN KEY(donation_id, item_id)
        REFERENCES donation_item(donation_id, item_id),
    CONSTRAINT pk_dnintake_item PRIMARY KEY(donation_id, inventory_id, item_id, batch_no)
);

-- Step 3: Create indexes
CREATE INDEX dk_dnintake_item_1 ON dnintake_item(inventory_id, item_id);
CREATE INDEX dk_dnintake_item_2 ON dnintake_item(item_id);

-- Step 4: Verify table was created
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 
        FROM pg_tables 
        WHERE tablename = 'dnintake_item' 
        AND schemaname = 'public'
    ) THEN
        RAISE EXCEPTION 'Failed to create dnintake_item table';
    END IF;
END $$;

COMMIT;

-- Notes:
-- 1. Key fixes: quantity precision changed to DECIMAL(12,2), avg_unit_value must be > 0.00
-- 2. Fixed constraint c_dnintake_item_4 to check expired_qty instead of defective_qty
-- 3. Added missing expiry_date constraint (c_dnintake_item_1c)
-- 4. Status codes: P=Processed, V=Verified
