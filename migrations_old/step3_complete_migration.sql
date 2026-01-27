-- ============================================================================
-- STEP 3: Complete Migration to Target Schema
-- Purpose: Add all remaining columns, constraints, and indexes
-- Prerequisites: item_code must be populated (run steps 1 & 2 first)
-- ============================================================================

BEGIN;

-- ============================================================================
-- VALIDATION: Ensure item_code is ready
-- ============================================================================

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM item WHERE item_code IS NULL) THEN
        RAISE EXCEPTION 'MIGRATION FAILED: item_code has NULL values. Run step 2 to populate all item_code values first.';
    END IF;
    
    IF EXISTS (SELECT item_code FROM item WHERE item_code IS NOT NULL GROUP BY item_code HAVING COUNT(*) > 1) THEN
        RAISE EXCEPTION 'MIGRATION FAILED: Duplicate item_code values found. Each item_code must be unique.';
    END IF;
    
    IF EXISTS (SELECT 1 FROM item WHERE item_code IS NOT NULL AND item_code != UPPER(item_code)) THEN
        RAISE EXCEPTION 'MIGRATION FAILED: Some item_code values are not uppercase.';
    END IF;
    
    IF EXISTS (SELECT 1 FROM item WHERE LENGTH(item_code) > 16) THEN
        RAISE EXCEPTION 'MIGRATION FAILED: Some item_code values exceed 16 characters.';
    END IF;
END $$;

-- ============================================================================
-- ADD NEW COLUMNS
-- ============================================================================

-- Add units_size_vary_flag
ALTER TABLE item ADD COLUMN IF NOT EXISTS units_size_vary_flag boolean NOT NULL DEFAULT FALSE;

-- Add is_batched_flag
ALTER TABLE item ADD COLUMN IF NOT EXISTS is_batched_flag boolean NOT NULL DEFAULT TRUE;

-- Add can_expire_flag
ALTER TABLE item ADD COLUMN IF NOT EXISTS can_expire_flag boolean NOT NULL DEFAULT FALSE;

-- Migrate data from old expiration_apply_flag to new can_expire_flag (if old column exists)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'item' AND column_name = 'expiration_apply_flag') THEN
        UPDATE item SET can_expire_flag = expiration_apply_flag;
    END IF;
END $$;

-- Add issuance_order
ALTER TABLE item ADD COLUMN IF NOT EXISTS issuance_order varchar(20) NOT NULL DEFAULT 'FIFO';

-- ============================================================================
-- UPDATE EXISTING COLUMNS
-- ============================================================================

-- Ensure category_id is NOT NULL (validate first)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM item WHERE category_id IS NULL) THEN
        RAISE EXCEPTION 'MIGRATION FAILED: category_id has NULL values. All items must have a valid category_id.';
    END IF;
END $$;

ALTER TABLE item ALTER COLUMN category_id SET NOT NULL;

-- Make item_code NOT NULL
ALTER TABLE item ALTER COLUMN item_code SET NOT NULL;

-- Ensure timestamp precision is (0)
ALTER TABLE item ALTER COLUMN create_dtime TYPE timestamp(0) without time zone;
ALTER TABLE item ALTER COLUMN update_dtime TYPE timestamp(0) without time zone;

-- ============================================================================
-- DROP OLD CONSTRAINTS (to rebuild with correct names)
-- ============================================================================

-- Drop existing constraints that need renaming
ALTER TABLE item DROP CONSTRAINT IF EXISTS item_pkey;
ALTER TABLE item DROP CONSTRAINT IF EXISTS uk_item_1;
ALTER TABLE item DROP CONSTRAINT IF EXISTS uk_item_2;
ALTER TABLE item DROP CONSTRAINT IF EXISTS item_item_name_check;
ALTER TABLE item DROP CONSTRAINT IF EXISTS item_sku_code_check;
ALTER TABLE item DROP CONSTRAINT IF EXISTS item_reorder_qty_check;
ALTER TABLE item DROP CONSTRAINT IF EXISTS item_status_code_check;
ALTER TABLE item DROP CONSTRAINT IF EXISTS item_category_id_fkey;
ALTER TABLE item DROP CONSTRAINT IF EXISTS item_default_uom_code_fkey;

-- ============================================================================
-- ADD CONSTRAINTS WITH CORRECT NAMES
-- ============================================================================

-- Primary key
ALTER TABLE item ADD CONSTRAINT pk_item PRIMARY KEY (item_id);

-- Unique constraints
ALTER TABLE item ADD CONSTRAINT uk_item_1 UNIQUE (item_code);
ALTER TABLE item ADD CONSTRAINT uk_item_2 UNIQUE (item_name);
ALTER TABLE item ADD CONSTRAINT uk_item_3 UNIQUE (sku_code);

-- Check constraints
ALTER TABLE item ADD CONSTRAINT c_item_1a CHECK (item_code = upper(item_code));
ALTER TABLE item ADD CONSTRAINT c_item_1b CHECK (item_name = upper(item_name));
ALTER TABLE item ADD CONSTRAINT c_item_1c CHECK (sku_code = upper(sku_code));
ALTER TABLE item ADD CONSTRAINT c_item_1d CHECK (reorder_qty > 0.00);
ALTER TABLE item ADD CONSTRAINT c_item_3 CHECK (status_code IN ('A', 'I'));

-- Foreign keys
ALTER TABLE item ADD CONSTRAINT fk_item_itemcatg FOREIGN KEY (category_id) REFERENCES itemcatg(category_id);
ALTER TABLE item ADD CONSTRAINT fk_item_unitofmeasure FOREIGN KEY (default_uom_code) REFERENCES unitofmeasure(uom_code);

-- ============================================================================
-- CREATE INDEXES
-- ============================================================================

CREATE INDEX IF NOT EXISTS dk_item_1 ON item(item_desc);
CREATE INDEX IF NOT EXISTS dk_item_2 ON item(category_id);
CREATE INDEX IF NOT EXISTS dk_item_3 ON item(sku_code);

-- ============================================================================
-- DROP OBSOLETE COLUMNS
-- ============================================================================

ALTER TABLE item DROP COLUMN IF EXISTS category_code;
ALTER TABLE item DROP COLUMN IF EXISTS expiration_apply_flag;

COMMIT;

-- ============================================================================
-- VERIFICATION
-- ============================================================================

SELECT 'Migration completed successfully!' as status;

-- Show final structure
SELECT column_name, data_type, character_maximum_length, is_nullable, column_default
FROM information_schema.columns
WHERE table_name = 'item'
ORDER BY ordinal_position;
