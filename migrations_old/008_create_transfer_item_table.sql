-- Migration 008: Create transfer_item table
-- This table was dropped in migration 007 but never recreated
-- It's required for the Item model relationships to work

BEGIN;

-- Create transfer_item table
CREATE TABLE IF NOT EXISTS transfer_item
(
    transfer_id INTEGER NOT NULL
        CONSTRAINT fk_transfer_item_transfer REFERENCES transfer(transfer_id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL
        CONSTRAINT fk_transfer_item_item REFERENCES item(item_id),
    batch_id INTEGER,
    inventory_id INTEGER NOT NULL,
    item_qty NUMERIC(10,2) NOT NULL
        CONSTRAINT c_transfer_item_1 CHECK (item_qty > 0),
    uom_code VARCHAR(10) NOT NULL
        CONSTRAINT fk_transfer_item_uom REFERENCES unitofmeasure(uom_code),
    reason_text VARCHAR(255),
    
    -- Audit fields
    create_by_id VARCHAR(20) NOT NULL,
    create_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    update_by_id VARCHAR(20) NOT NULL,
    update_dtime TIMESTAMP(0) WITHOUT TIME ZONE,
    version_nbr INTEGER NOT NULL DEFAULT 1,
    
    -- Composite primary key
    CONSTRAINT pk_transfer_item PRIMARY KEY (transfer_id, item_id, batch_id),
    
    -- Foreign key to inventory (composite)
    CONSTRAINT fk_transfer_item_inventory 
        FOREIGN KEY (inventory_id, item_id) 
        REFERENCES inventory(inventory_id, item_id),
    
    -- Foreign key to itembatch (composite) - nullable batch_id
    CONSTRAINT fk_transfer_item_batch
        FOREIGN KEY (inventory_id, batch_id)
        REFERENCES itembatch(inventory_id, batch_id)
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_transfer_item_item ON transfer_item(item_id);
CREATE INDEX IF NOT EXISTS idx_transfer_item_batch ON transfer_item(inventory_id, batch_id);

-- Verify table was created
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 
        FROM pg_tables 
        WHERE tablename = 'transfer_item' 
        AND schemaname = 'public'
    ) THEN
        RAISE EXCEPTION 'Failed to create transfer_item table';
    END IF;
END $$;

COMMIT;

-- Notes:
-- 1. This table tracks items in warehouse-to-warehouse transfers
-- 2. Batch-level tracking for traceability
-- 3. Composite foreign keys ensure referential integrity
-- 4. Optimistic locking via version_nbr
