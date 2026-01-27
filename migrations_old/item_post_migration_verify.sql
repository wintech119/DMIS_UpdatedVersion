-- ============================================================================
-- ITEM TABLE POST-MIGRATION VERIFICATION SCRIPT
-- Purpose: Verify migration completed successfully
-- Date: 2025-11-17
-- ============================================================================

\echo '========================================='
\echo 'ITEM TABLE MIGRATION VERIFICATION'
\echo '========================================='
\echo ''

-- ============================================================================
-- Test 1: Verify all required columns exist with correct types
-- ============================================================================
\echo 'Test 1: Column Structure'
SELECT 
    column_name,
    data_type,
    COALESCE(character_maximum_length::text, 
             numeric_precision::text || ',' || numeric_scale::text) as max_length,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_name = 'item'
ORDER BY ordinal_position;

\echo ''
\echo '========================================='

-- ============================================================================
-- Test 2: Verify all constraints exist
-- ============================================================================
\echo 'Test 2: Constraints'
SELECT
    constraint_name,
    constraint_type
FROM information_schema.table_constraints
WHERE table_name = 'item'
ORDER BY constraint_type, constraint_name;

\echo ''
\echo '========================================='

-- ============================================================================
-- Test 3: Verify all indexes exist
-- ============================================================================
\echo 'Test 3: Indexes'
SELECT 
    indexname,
    indexdef
FROM pg_indexes
WHERE tablename = 'item'
ORDER BY indexname;

\echo ''
\echo '========================================='

-- ============================================================================
-- Test 4: Verify specific required constraints by name
-- ============================================================================
\echo 'Test 4: Required Constraints Check'
SELECT 
    CASE 
        WHEN EXISTS (SELECT 1 FROM information_schema.table_constraints 
                     WHERE table_name = 'item' AND constraint_name = 'pk_item') 
        THEN 'PASS' ELSE 'FAIL' 
    END as pk_item_exists,
    CASE 
        WHEN EXISTS (SELECT 1 FROM information_schema.table_constraints 
                     WHERE table_name = 'item' AND constraint_name = 'uk_item_1') 
        THEN 'PASS' ELSE 'FAIL' 
    END as uk_item_1_exists,
    CASE 
        WHEN EXISTS (SELECT 1 FROM information_schema.table_constraints 
                     WHERE table_name = 'item' AND constraint_name = 'uk_item_2') 
        THEN 'PASS' ELSE 'FAIL' 
    END as uk_item_2_exists,
    CASE 
        WHEN EXISTS (SELECT 1 FROM information_schema.table_constraints 
                     WHERE table_name = 'item' AND constraint_name = 'uk_item_3') 
        THEN 'PASS' ELSE 'FAIL' 
    END as uk_item_3_exists,
    CASE 
        WHEN EXISTS (SELECT 1 FROM information_schema.table_constraints 
                     WHERE table_name = 'item' AND constraint_name = 'fk_item_itemcatg') 
        THEN 'PASS' ELSE 'FAIL' 
    END as fk_item_itemcatg_exists,
    CASE 
        WHEN EXISTS (SELECT 1 FROM information_schema.table_constraints 
                     WHERE table_name = 'item' AND constraint_name = 'fk_item_unitofmeasure') 
        THEN 'PASS' ELSE 'FAIL' 
    END as fk_item_unitofmeasure_exists;

\echo ''
\echo '========================================='

-- ============================================================================
-- Test 5: Verify required indexes exist
-- ============================================================================
\echo 'Test 5: Required Indexes Check'
SELECT 
    CASE 
        WHEN EXISTS (SELECT 1 FROM pg_indexes 
                     WHERE tablename = 'item' AND indexname = 'dk_item_1') 
        THEN 'PASS' ELSE 'FAIL' 
    END as dk_item_1_exists,
    CASE 
        WHEN EXISTS (SELECT 1 FROM pg_indexes 
                     WHERE tablename = 'item' AND indexname = 'dk_item_2') 
        THEN 'PASS' ELSE 'FAIL' 
    END as dk_item_2_exists,
    CASE 
        WHEN EXISTS (SELECT 1 FROM pg_indexes 
                     WHERE tablename = 'item' AND indexname = 'dk_item_3') 
        THEN 'PASS' ELSE 'FAIL' 
    END as dk_item_3_exists;

\echo ''
\echo '========================================='

-- ============================================================================
-- Test 6: Verify data integrity
-- ============================================================================
\echo 'Test 6: Data Integrity'
SELECT 
    COUNT(*) as total_rows,
    COUNT(DISTINCT item_id) as unique_ids,
    COUNT(DISTINCT item_code) as unique_item_codes,
    COUNT(DISTINCT item_name) as unique_item_names,
    COUNT(DISTINCT sku_code) as unique_sku_codes,
    COUNT(CASE WHEN item_code = UPPER(item_code) THEN 1 END) as uppercase_item_codes,
    COUNT(CASE WHEN item_name = UPPER(item_name) THEN 1 END) as uppercase_item_names,
    COUNT(CASE WHEN sku_code = UPPER(sku_code) THEN 1 END) as uppercase_sku_codes,
    COUNT(CASE WHEN reorder_qty > 0 THEN 1 END) as valid_reorder_qty,
    COUNT(CASE WHEN status_code IN ('A', 'I') THEN 1 END) as valid_status_codes
FROM item;

\echo ''
\echo '========================================='

-- ============================================================================
-- Test 7: Verify new columns have been populated correctly
-- ============================================================================
\echo 'Test 7: New Columns Population'
SELECT 
    COUNT(*) as total_rows,
    COUNT(item_code) as item_code_populated,
    COUNT(CASE WHEN units_size_vary_flag IS NOT NULL THEN 1 END) as units_size_vary_flag_populated,
    COUNT(CASE WHEN is_batched_flag IS NOT NULL THEN 1 END) as is_batched_flag_populated,
    COUNT(CASE WHEN can_expire_flag IS NOT NULL THEN 1 END) as can_expire_flag_populated,
    COUNT(issuance_order) as issuance_order_populated
FROM item;

\echo ''
\echo '========================================='

-- ============================================================================
-- Test 8: Sample data verification
-- ============================================================================
\echo 'Test 8: Sample Data (First 5 rows)'
SELECT 
    item_id,
    item_code,
    item_name,
    sku_code,
    category_id,
    status_code,
    is_batched_flag,
    can_expire_flag,
    issuance_order
FROM item
ORDER BY item_id
LIMIT 5;

\echo ''
\echo '========================================='
\echo 'VERIFICATION COMPLETE'
\echo '========================================='

-- ============================================================================
-- Expected Results Summary
-- ============================================================================
-- All tests should show:
-- - pk_item, uk_item_1, uk_item_2, uk_item_3 constraints exist
-- - fk_item_itemcatg, fk_item_unitofmeasure foreign keys exist  
-- - dk_item_1, dk_item_2, dk_item_3 indexes exist
-- - All uppercase checks pass (item_code, item_name, sku_code)
-- - All reorder_qty > 0
-- - All status_code in ('A', 'I')
-- - No NULL values in NOT NULL columns
-- ============================================================================
