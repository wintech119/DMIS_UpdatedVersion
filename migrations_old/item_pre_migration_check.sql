-- ============================================================================
-- ITEM TABLE PRE-MIGRATION VALIDATION SCRIPT
-- Purpose: Check data integrity before running migration
-- Date: 2025-11-17
-- ============================================================================

-- Check 1: Verify all category_id values are populated
SELECT 
    'Category ID Check' as check_name,
    COUNT(*) as total_rows,
    COUNT(category_id) as populated_category_ids,
    COUNT(*) - COUNT(category_id) as null_category_ids
FROM item;

-- If null_category_ids > 0, you need to populate them before migration
-- Example fix (customize as needed):
-- UPDATE item SET category_id = 1 WHERE category_id IS NULL;

-- Check 2: Verify all items have unique names and SKUs
SELECT 
    'Uniqueness Check' as check_name,
    COUNT(*) as total_rows,
    COUNT(DISTINCT item_name) as unique_names,
    COUNT(DISTINCT sku_code) as unique_skus,
    CASE 
        WHEN COUNT(*) = COUNT(DISTINCT item_name) THEN 'PASS' 
        ELSE 'FAIL - Duplicate item_name exists' 
    END as name_uniqueness,
    CASE 
        WHEN COUNT(*) = COUNT(DISTINCT sku_code) THEN 'PASS' 
        ELSE 'FAIL - Duplicate sku_code exists' 
    END as sku_uniqueness
FROM item;

-- Check 3: Find any duplicate item names
SELECT 
    item_name,
    COUNT(*) as duplicate_count
FROM item
GROUP BY item_name
HAVING COUNT(*) > 1;

-- Check 4: Find any duplicate SKU codes
SELECT 
    sku_code,
    COUNT(*) as duplicate_count
FROM item
GROUP BY sku_code
HAVING COUNT(*) > 1;

-- Check 5: Verify reorder_qty is always > 0
SELECT 
    'Reorder Qty Check' as check_name,
    COUNT(*) as total_rows,
    COUNT(*) FILTER (WHERE reorder_qty > 0) as valid_reorder_qty,
    COUNT(*) FILTER (WHERE reorder_qty <= 0) as invalid_reorder_qty
FROM item;

-- Check 6: Verify status_code values
SELECT 
    'Status Code Check' as check_name,
    status_code,
    COUNT(*) as count
FROM item
GROUP BY status_code
ORDER BY status_code;

-- Check 7: Current item data that needs item_code values
SELECT 
    item_id,
    item_name,
    sku_code,
    category_id
FROM item
ORDER BY item_id
LIMIT 10;

-- ============================================================================
-- CRITICAL: ITEM_CODE POPULATION REQUIRED
-- ============================================================================
-- You MUST populate the item_code column with your business values BEFORE running
-- the migration. The migration will fail if item_code values are not provided.
--
-- Requirements:
-- - Max length: 16 characters
-- - Must be UPPERCASE
-- - Must be UNIQUE across all items
-- - Cannot be NULL
--
-- Example population strategies:
--
-- 1. Use existing SKU code (if it meets requirements):
--    UPDATE item SET item_code = sku_code;
--
-- 2. Create codes from item name abbreviation + ID:
--    UPDATE item SET item_code = UPPER(SUBSTRING(item_name, 1, 8) || '-' || item_id);
--
-- 3. Custom business logic (e.g., category prefix + sequence):
--    UPDATE item SET item_code = 'CAT' || category_id || '-' || LPAD(item_id::text, 6, '0');
--
-- 4. Manual entry for each item (for smaller datasets):
--    UPDATE item SET item_code = 'BLANKET-001' WHERE item_id = 1;
--    UPDATE item SET item_code = 'WATER-500ML' WHERE item_id = 2;
--
-- After populating, verify with:
--    SELECT COUNT(*), COUNT(DISTINCT item_code) FROM item;
--    -- Both counts should match (all unique)
--
--    SELECT item_code, COUNT(*) FROM item GROUP BY item_code HAVING COUNT(*) > 1;
--    -- Should return no rows (no duplicates)
-- ============================================================================
