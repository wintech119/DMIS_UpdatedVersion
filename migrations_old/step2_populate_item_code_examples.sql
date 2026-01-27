-- ============================================================================
-- STEP 2: Populate item_code values (CHOOSE YOUR STRATEGY)
-- ============================================================================
-- You MUST populate item_code before running step 3.
-- 
-- Requirements:
-- - Max 16 characters
-- - UPPERCASE only
-- - Unique across all items
-- - Cannot be NULL
-- ============================================================================

-- STRATEGY 1: Use existing SKU code (if it meets requirements)
-- ============================================================================
-- Uncomment if SKU codes are suitable:
-- UPDATE item SET item_code = sku_code WHERE item_code IS NULL;


-- STRATEGY 2: Generate from item ID with prefix
-- ============================================================================
-- Uncomment to use:
-- UPDATE item SET item_code = 'ITM-' || LPAD(item_id::text, 6, '0') WHERE item_code IS NULL;
-- Example: ITM-000001, ITM-000002, etc.


-- STRATEGY 3: Manually set each item code
-- ============================================================================
-- Uncomment and customize:
-- UPDATE item SET item_code = 'WATER-500ML' WHERE item_id = 1;
-- UPDATE item SET item_code = 'BLANKET-STD' WHERE item_id = 2;
-- UPDATE item SET item_code = 'TARP-10X12' WHERE item_id = 3;
-- ... continue for each item


-- STRATEGY 4: Generate from item name
-- ============================================================================
-- Uncomment to use first 12 chars of item name + ID:
-- UPDATE item 
-- SET item_code = UPPER(SUBSTRING(REPLACE(item_name, ' ', ''), 1, 12) || item_id)
-- WHERE item_code IS NULL;


-- ============================================================================
-- VERIFICATION: Run these after populating
-- ============================================================================

-- Check all are populated (should return 0)
SELECT COUNT(*) as null_count FROM item WHERE item_code IS NULL;

-- Check uniqueness (should return no rows)
SELECT item_code, COUNT(*) as duplicate_count
FROM item 
WHERE item_code IS NOT NULL
GROUP BY item_code 
HAVING COUNT(*) > 1;

-- Check uppercase (should return no rows)
SELECT item_id, item_code
FROM item 
WHERE item_code IS NOT NULL AND item_code != UPPER(item_code);

-- Check length (should return no rows)
SELECT item_id, item_code, LENGTH(item_code) as length
FROM item 
WHERE item_code IS NOT NULL AND LENGTH(item_code) > 16;

-- Preview all item codes
SELECT item_id, item_code, item_name, sku_code
FROM item
ORDER BY item_id;
