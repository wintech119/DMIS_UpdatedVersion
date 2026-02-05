-- ============================================================================
-- Supply Replenishment Migration Verification Script (pgAdmin4 Compatible)
-- ============================================================================
-- Run this script in pgAdmin4 Query Tool to verify migration success
-- ============================================================================

-- 1. CHECK ALTERED COLUMNS ON EXISTING TABLES
SELECT 'CHECKING ALTERED COLUMNS' AS status;

SELECT 'event table columns:' AS check_type;
SELECT
    column_name,
    data_type,
    column_default
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'event'
  AND column_name IN ('current_phase', 'phase_changed_at', 'phase_changed_by')
ORDER BY column_name;

SELECT 'warehouse table columns:' AS check_type;
SELECT
    column_name,
    data_type,
    column_default
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'warehouse'
  AND column_name IN ('min_stock_threshold', 'last_sync_dtime', 'sync_status')
ORDER BY column_name;

SELECT 'item table columns:' AS check_type;
SELECT
    column_name,
    data_type,
    column_default
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'item'
  AND column_name IN ('baseline_burn_rate', 'min_stock_threshold', 'criticality_level')
ORDER BY column_name;

-- 2. CHECK NEW TABLES
SELECT 'CHECKING NEW TABLES' AS status;

SELECT
    expected.table_name,
    CASE WHEN t.table_name IS NOT NULL THEN '✓ EXISTS' ELSE '✗ MISSING' END AS status
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

-- 3. CHECK VIEWS
SELECT 'CHECKING VIEWS' AS status;

SELECT
    expected.table_name AS view_name,
    CASE WHEN v.table_name IS NOT NULL THEN '✓ EXISTS' ELSE '✗ MISSING' END AS status
FROM (VALUES
    ('v_stock_status'),
    ('v_inbound_stock')
) AS expected(table_name)
LEFT JOIN information_schema.views v
    ON v.table_schema = 'public'
    AND v.table_name = expected.table_name
ORDER BY expected.table_name;

-- 4. CHECK DEFAULT DATA
SELECT 'CHECKING DEFAULT DATA' AS status;

SELECT 'Lead time configurations:' AS check_type;
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

-- 5. CHECK ACTIVE EVENTS
SELECT 'CHECKING ACTIVE EVENTS' AS status;

SELECT
    event_id,
    event_name,
    status_code,
    current_phase,
    CASE
        WHEN current_phase IS NULL THEN '⚠ WARNING: current_phase is NULL'
        WHEN UPPER(status_code) = 'ACTIVE' THEN '✓ Active event with phase'
        ELSE 'Not active'
    END AS status
FROM public.event
ORDER BY event_id DESC
LIMIT 5;

-- 6. SUMMARY CHECK
SELECT 'MIGRATION SUMMARY' AS status;

WITH checks AS (
    SELECT
        (SELECT COUNT(*) FROM (
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
        WHERE EXISTS (
            SELECT 1
            FROM information_schema.columns c
            WHERE c.table_schema = 'public'
              AND c.table_name = expected.tbl
              AND c.column_name = expected.col
        )) AS columns_present,

        (SELECT COUNT(*) FROM (VALUES
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
        WHERE EXISTS (
            SELECT 1
            FROM information_schema.tables t
            WHERE t.table_schema = 'public'
              AND t.table_name = expected.tbl
        )) AS tables_present,

        (SELECT COUNT(*) FROM (VALUES
            ('v_stock_status'),
            ('v_inbound_stock')
        ) AS expected(vw)
        WHERE EXISTS (
            SELECT 1
            FROM information_schema.views v
            WHERE v.table_schema = 'public'
              AND v.table_name = expected.vw
        )) AS views_present,

        (SELECT COUNT(*) FROM public.lead_time_config WHERE is_default = TRUE) AS defaults_present,

        (SELECT COUNT(*) FROM public.event WHERE current_phase IS NULL) AS events_without_phase
)
SELECT
    CASE
        WHEN columns_present = 10 THEN '✓ All 10 required columns present'
        ELSE '✗ Missing ' || (10 - columns_present)::text || ' column(s)'
    END AS columns_check,
    CASE
        WHEN tables_present = 11 THEN '✓ All 11 new tables created'
        ELSE '✗ Missing ' || (11 - tables_present)::text || ' table(s)'
    END AS tables_check,
    CASE
        WHEN views_present = 2 THEN '✓ All 2 views created'
        ELSE '✗ Missing ' || (2 - views_present)::text || ' view(s)'
    END AS views_check,
    CASE
        WHEN defaults_present >= 2 THEN '✓ Default lead time configurations present'
        ELSE '✗ Missing ' || (2 - defaults_present)::text || ' default lead time(s)'
    END AS defaults_check,
    CASE
        WHEN events_without_phase = 0 THEN '✓ All events have current_phase set'
        ELSE '⚠ ' || events_without_phase::text || ' event(s) without current_phase - UPDATE needed'
    END AS events_check,
    CASE
        WHEN columns_present = 10 AND tables_present = 11 AND views_present = 2 AND defaults_present >= 2
        THEN '✓✓✓ MIGRATION SUCCESSFUL ✓✓✓'
        ELSE '✗✗✗ MIGRATION INCOMPLETE ✗✗✗'
    END AS overall_status
FROM checks;
