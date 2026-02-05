-- ============================================================================
-- Supply Replenishment Migration Verification Script
-- ============================================================================
-- Run this script after applying EP02_SUPPLY_REPLENISHMENT_SCHEMA.sql
-- to verify that all changes were applied successfully.
-- ============================================================================

\echo '========================================='
\echo 'Supply Replenishment Migration Verification'
\echo '========================================='
\echo ''

-- ============================================================================
-- 1. CHECK ALTERED COLUMNS ON EXISTING TABLES
-- ============================================================================

\echo '1. Checking altered columns on existing tables...'
\echo ''

\echo '  event table columns:'
SELECT
    column_name,
    data_type,
    column_default
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'event'
  AND column_name IN ('current_phase', 'phase_changed_at', 'phase_changed_by')
ORDER BY column_name;

\echo ''
\echo '  warehouse table columns:'
SELECT
    column_name,
    data_type,
    column_default
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'warehouse'
  AND column_name IN ('min_stock_threshold', 'last_sync_dtime', 'sync_status')
ORDER BY column_name;

\echo ''
\echo '  item table columns:'
SELECT
    column_name,
    data_type,
    column_default
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'item'
  AND column_name IN ('baseline_burn_rate', 'min_stock_threshold', 'criticality_level')
ORDER BY column_name;

\echo ''
\echo '  transfer table columns:'
SELECT
    column_name,
    data_type
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'transfer'
  AND column_name IN ('dispatched_at', 'dispatched_by', 'expected_arrival', 'received_at', 'received_by', 'needs_list_id')
ORDER BY column_name;

\echo ''

-- ============================================================================
-- 2. CHECK NEW TABLES
-- ============================================================================

\echo '2. Checking new tables...'
\echo ''

SELECT
    table_name,
    CASE WHEN table_name IS NOT NULL THEN '✓ EXISTS' ELSE '✗ MISSING' END AS status
FROM (VALUES
    ('event_phase_config'),
    ('event_phase_history'),
    ('needs_list'),
    ('needs_list_item'),
    ('needs_list_audit'),
    ('burn_rate_snapshot'),
    ('warehouse_sync_log'),
    ('procurement'),
    ('procurement_item'),
    ('supplier'),
    ('lead_time_config')
) AS expected(table_name)
LEFT JOIN information_schema.tables t
    ON t.table_schema = 'public'
    AND t.table_name = expected.table_name
ORDER BY expected.table_name;

\echo ''

-- ============================================================================
-- 3. CHECK VIEWS
-- ============================================================================

\echo '3. Checking views...'
\echo ''

SELECT
    table_name AS view_name,
    CASE WHEN table_name IS NOT NULL THEN '✓ EXISTS' ELSE '✗ MISSING' END AS status
FROM (VALUES
    ('v_stock_status'),
    ('v_inbound_stock')
) AS expected(table_name)
LEFT JOIN information_schema.views v
    ON v.table_schema = 'public'
    AND v.table_name = expected.table_name
ORDER BY expected.table_name;

\echo ''

-- ============================================================================
-- 4. CHECK CONSTRAINTS
-- ============================================================================

\echo '4. Checking key constraints...'
\echo ''

SELECT
    conname AS constraint_name,
    conrelid::regclass AS table_name,
    CASE contype
        WHEN 'c' THEN 'CHECK'
        WHEN 'f' THEN 'FOREIGN KEY'
        WHEN 'p' THEN 'PRIMARY KEY'
        WHEN 'u' THEN 'UNIQUE'
    END AS constraint_type
FROM pg_constraint
WHERE connamespace = 'public'::regnamespace
  AND (
    conrelid::regclass::text IN (
      'event', 'warehouse', 'item', 'transfer',
      'event_phase_config', 'event_phase_history',
      'needs_list', 'needs_list_item', 'needs_list_audit',
      'burn_rate_snapshot', 'warehouse_sync_log',
      'procurement', 'procurement_item', 'supplier', 'lead_time_config'
    )
    AND conname LIKE 'c_%'  -- Check constraints
  )
ORDER BY table_name, constraint_type, constraint_name
LIMIT 20;

\echo ''

-- ============================================================================
-- 5. CHECK DEFAULT DATA
-- ============================================================================

\echo '5. Checking default data...'
\echo ''

\echo '  Lead time configurations:'
SELECT
    horizon,
    lead_time_hours,
    is_default,
    CASE horizon
        WHEN 'A' THEN 'Transfers'
        WHEN 'B' THEN 'Donations'
        WHEN 'C' THEN 'Procurement'
    END AS description
FROM public.lead_time_config
WHERE is_default = TRUE
ORDER BY horizon;

\echo ''

-- ============================================================================
-- 6. CHECK TRIGGERS
-- ============================================================================

\echo '6. Checking triggers...'
\echo ''

SELECT
    trigger_name,
    event_object_table AS table_name,
    action_timing || ' ' || string_agg(event_manipulation, ', ') AS trigger_event
FROM information_schema.triggers
WHERE trigger_schema = 'public'
  AND trigger_name IN ('trg_warehouse_sync_status', 'trg_event_phase_change')
GROUP BY trigger_name, event_object_table, action_timing
ORDER BY trigger_name;

\echo ''

-- ============================================================================
-- 7. CHECK ACTIVE EVENTS
-- ============================================================================

\echo '7. Checking active events (should have data for dashboard)...'
\echo ''

SELECT
    event_id,
    event_name,
    status_code,
    current_phase,
    declaration_date,
    CASE
        WHEN current_phase IS NULL THEN '⚠ WARNING: current_phase is NULL'
        WHEN UPPER(status_code) = 'ACTIVE' THEN '✓ Active event with phase'
        ELSE 'Not active'
    END AS status
FROM public.event
ORDER BY declaration_date DESC
LIMIT 5;

\echo ''

-- ============================================================================
-- 8. SUMMARY
-- ============================================================================

\echo '========================================='
\echo 'MIGRATION VERIFICATION SUMMARY'
\echo '========================================='
\echo ''

DO $$
DECLARE
    missing_columns INTEGER;
    missing_tables INTEGER;
    missing_views INTEGER;
    events_without_phase INTEGER;
    missing_defaults INTEGER;
BEGIN
    -- Count missing columns
    SELECT COUNT(*) INTO missing_columns
    FROM (
        SELECT 'event' AS tbl, 'current_phase' AS col
        UNION ALL SELECT 'event', 'phase_changed_at'
        UNION ALL SELECT 'event', 'phase_changed_by'
        UNION ALL SELECT 'warehouse', 'min_stock_threshold'
        UNION ALL SELECT 'warehouse', 'last_sync_dtime'
        UNION ALL SELECT 'warehouse', 'sync_status'
        UNION ALL SELECT 'item', 'baseline_burn_rate'
        UNION ALL SELECT 'item', 'min_stock_threshold'
        UNION ALL SELECT 'item', 'criticality_level'
        UNION ALL SELECT 'transfer', 'needs_list_id'
    ) AS expected
    WHERE NOT EXISTS (
        SELECT 1
        FROM information_schema.columns c
        WHERE c.table_schema = 'public'
          AND c.table_name = expected.tbl
          AND c.column_name = expected.col
    );

    -- Count missing tables
    SELECT COUNT(*) INTO missing_tables
    FROM (VALUES
        ('event_phase_config'),
        ('event_phase_history'),
        ('needs_list'),
        ('needs_list_item'),
        ('needs_list_audit'),
        ('burn_rate_snapshot'),
        ('warehouse_sync_log'),
        ('procurement'),
        ('procurement_item'),
        ('supplier'),
        ('lead_time_config')
    ) AS expected(tbl)
    WHERE NOT EXISTS (
        SELECT 1
        FROM information_schema.tables t
        WHERE t.table_schema = 'public'
          AND t.table_name = expected.tbl
    );

    -- Count missing views
    SELECT COUNT(*) INTO missing_views
    FROM (VALUES
        ('v_stock_status'),
        ('v_inbound_stock')
    ) AS expected(vw)
    WHERE NOT EXISTS (
        SELECT 1
        FROM information_schema.views v
        WHERE v.table_schema = 'public'
          AND v.table_name = expected.vw
    );

    -- Count events without phase
    SELECT COUNT(*) INTO events_without_phase
    FROM public.event
    WHERE current_phase IS NULL;

    -- Count missing default lead times
    SELECT GREATEST(0, 2 - COUNT(*)) INTO missing_defaults
    FROM public.lead_time_config
    WHERE is_default = TRUE;

    -- Output summary
    RAISE NOTICE '';
    RAISE NOTICE 'Results:';
    RAISE NOTICE '--------';

    IF missing_columns = 0 THEN
        RAISE NOTICE '✓ All required columns present (10 columns checked)';
    ELSE
        RAISE NOTICE '✗ Missing % column(s)', missing_columns;
    END IF;

    IF missing_tables = 0 THEN
        RAISE NOTICE '✓ All new tables created (11 tables checked)';
    ELSE
        RAISE NOTICE '✗ Missing % table(s)', missing_tables;
    END IF;

    IF missing_views = 0 THEN
        RAISE NOTICE '✓ All views created (2 views checked)';
    ELSE
        RAISE NOTICE '✗ Missing % view(s)', missing_views;
    END IF;

    IF missing_defaults = 0 THEN
        RAISE NOTICE '✓ Default lead time configurations present';
    ELSE
        RAISE NOTICE '✗ Missing % default lead time(s)', missing_defaults;
    END IF;

    IF events_without_phase = 0 THEN
        RAISE NOTICE '✓ All events have current_phase set';
    ELSE
        RAISE NOTICE '⚠ % event(s) without current_phase - run UPDATE statement', events_without_phase;
    END IF;

    RAISE NOTICE '';

    IF missing_columns = 0 AND missing_tables = 0 AND missing_views = 0 AND missing_defaults = 0 THEN
        RAISE NOTICE '✓✓✓ MIGRATION SUCCESSFUL ✓✓✓';
        IF events_without_phase > 0 THEN
            RAISE NOTICE '';
            RAISE NOTICE 'ACTION REQUIRED: Update existing events to set current_phase:';
            RAISE NOTICE 'UPDATE public.event SET current_phase = ''STABILIZED'', phase_changed_at = CURRENT_TIMESTAMP WHERE current_phase IS NULL;';
        END IF;
    ELSE
        RAISE NOTICE '✗✗✗ MIGRATION INCOMPLETE ✗✗✗';
        RAISE NOTICE 'Please review the results above and re-run the migration script.';
    END IF;
END;
$$;

\echo ''
\echo '========================================='
