-- ============================================================================
-- STEP 1: Add item_code column (nullable initially)
-- Purpose: Add the column so you can populate it with your business values
-- ============================================================================

BEGIN;

-- Add item_code column as nullable
ALTER TABLE item ADD COLUMN IF NOT EXISTS item_code varchar(16);

-- Show current data to help you decide on item_code values
SELECT 
    item_id,
    item_name,
    sku_code,
    item_code,
    CASE 
        WHEN item_code IS NULL THEN 'NEEDS VALUE'
        ELSE 'POPULATED'
    END as status
FROM item
ORDER BY item_id;

COMMIT;

-- ============================================================================
-- NEXT STEP: Populate item_code values
-- ============================================================================
-- After running this script, you need to populate item_code with your values.
-- See step2_populate_item_code_examples.sql for examples.
-- ============================================================================
