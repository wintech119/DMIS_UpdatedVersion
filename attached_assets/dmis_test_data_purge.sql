-- ============================================================================
-- DMIS Test Data PURGE Script
-- ============================================================================
-- Version: 2.0
-- Date: 2026-02-13
-- Purpose: Removes test data and optionally drops multi-tenancy schema
-- 
-- SAFETY: This script preserves production data by:
--   - Only removing records created by TEST_SCRIPT or CUSTODIAN_MIGRATION
--   - Keeping custodian table intact (only removes tenant_id links)
--   - Keeping warehouse table intact (only removes tenant_id links)
--
-- USAGE:
--   psql -d dmis -f dmis_test_data_purge.sql
-- ============================================================================

BEGIN;

-- ============================================================================
-- SECTION 1: REMOVE EP-02 TEST DATA (in dependency order)
-- ============================================================================

-- 1.1 Remove needs list items
DELETE FROM public.needs_list_item 
WHERE needs_list_id IN (
    SELECT needs_list_id FROM public.needs_list WHERE create_by_id = 'TEST_SCRIPT'
);

-- 1.2 Remove needs lists
DELETE FROM public.needs_list WHERE create_by_id = 'TEST_SCRIPT';

-- 1.3 Remove event phases
DELETE FROM public.event_phase WHERE create_by_id = 'TEST_SCRIPT';

-- 1.4 Remove warehouse sync status for test warehouses
DELETE FROM public.warehouse_sync_status 
WHERE warehouse_id IN (
    SELECT warehouse_id FROM public.warehouse WHERE create_by_id = 'TEST_SCRIPT'
);

-- ============================================================================
-- SECTION 2: REMOVE MULTI-TENANCY TEST DATA (in dependency order)
-- ============================================================================

-- 2.1 Remove data sharing agreements
DELETE FROM public.data_sharing_agreement WHERE create_by_id = 'TEST_SCRIPT';

-- 2.2 Remove tenant-warehouse mappings
DELETE FROM public.tenant_warehouse WHERE create_by_id = 'TEST_SCRIPT';

-- 2.3 Remove tenant-user mappings
DELETE FROM public.tenant_user WHERE create_by_id = 'TEST_SCRIPT';

-- 2.4 Remove tenant configurations
DELETE FROM public.tenant_config WHERE create_by_id = 'TEST_SCRIPT';

-- 2.5 Clear tenant_id from warehouses (only test/migration tenants; keep warehouse records)
UPDATE public.warehouse
SET tenant_id = NULL
WHERE tenant_id IN (
    SELECT id
    FROM public.tenant
    WHERE create_by_id IN ('TEST_SCRIPT', 'CUSTODIAN_MIGRATION')
);

-- 2.6 Clear tenant_id from custodians (only test/migration tenants; keep custodian records)
UPDATE public.custodian
SET tenant_id = NULL
WHERE tenant_id IN (
    SELECT id
    FROM public.tenant
    WHERE create_by_id IN ('TEST_SCRIPT', 'CUSTODIAN_MIGRATION')
);

-- 2.7 Remove tenant hierarchy links before deleting tenants
UPDATE public.tenant SET parent_tenant_id = NULL WHERE create_by_id IN ('TEST_SCRIPT', 'CUSTODIAN_MIGRATION');

-- 2.8 Remove tenant records
DELETE FROM public.tenant WHERE create_by_id IN ('TEST_SCRIPT', 'CUSTODIAN_MIGRATION');

-- ============================================================================
-- SECTION 3: REMOVE TEST EVENTS
-- ============================================================================

DELETE FROM public.event WHERE create_by_id = 'TEST_SCRIPT';

-- ============================================================================
-- SECTION 4: DROP MULTI-TENANCY SCHEMA (OPTIONAL)
-- ============================================================================
-- WARNING: Uncomment this section ONLY if you want to completely remove
-- the multi-tenancy schema. This removes the tenant_id columns from
-- custodian and warehouse tables.

/*
-- Drop triggers first
DROP TRIGGER IF EXISTS trg_tenant_update_dtime ON public.tenant;
DROP TRIGGER IF EXISTS trg_tenant_config_update_dtime ON public.tenant_config;
DROP TRIGGER IF EXISTS trg_needs_list_update_dtime ON public.needs_list;
DROP TRIGGER IF EXISTS trg_needs_list_item_update_dtime ON public.needs_list_item;

-- Drop indexes
DROP INDEX IF EXISTS public.idx_tenant_code_unique;
DROP INDEX IF EXISTS public.idx_tenant_type;
DROP INDEX IF EXISTS public.idx_tenant_status;
DROP INDEX IF EXISTS public.idx_tenant_user_user;
DROP INDEX IF EXISTS public.idx_tenant_warehouse_warehouse;
DROP INDEX IF EXISTS public.idx_data_sharing_from;
DROP INDEX IF EXISTS public.idx_data_sharing_to;
DROP INDEX IF EXISTS public.idx_needs_list_event;
DROP INDEX IF EXISTS public.idx_needs_list_warehouse;
DROP INDEX IF EXISTS public.idx_needs_list_status;
DROP INDEX IF EXISTS public.idx_needs_list_item_needs_list;
DROP INDEX IF EXISTS public.idx_needs_list_item_item;
DROP INDEX IF EXISTS public.idx_needs_list_item_horizon;
DROP INDEX IF EXISTS public.idx_event_phase_event;
DROP INDEX IF EXISTS public.idx_event_phase_current;
DROP INDEX IF EXISTS public.idx_custodian_tenant;
DROP INDEX IF EXISTS public.idx_warehouse_tenant;

-- Remove tenant_id columns from existing tables
ALTER TABLE public.warehouse DROP COLUMN IF EXISTS tenant_id;
ALTER TABLE public.custodian DROP COLUMN IF EXISTS tenant_id;

-- Drop tables in reverse dependency order
DROP TABLE IF EXISTS public.needs_list_item CASCADE;
DROP TABLE IF EXISTS public.needs_list CASCADE;
DROP TABLE IF EXISTS public.event_phase CASCADE;
DROP TABLE IF EXISTS public.warehouse_sync_status CASCADE;
DROP TABLE IF EXISTS public.data_sharing_agreement CASCADE;
DROP TABLE IF EXISTS public.tenant_warehouse CASCADE;
DROP TABLE IF EXISTS public.tenant_user CASCADE;
DROP TABLE IF EXISTS public.tenant_config CASCADE;
DROP TABLE IF EXISTS public.tenant CASCADE;
*/

-- ============================================================================
-- COMMIT TRANSACTION
-- ============================================================================

COMMIT;

-- ============================================================================
-- POST-PURGE VERIFICATION
-- ============================================================================

DO $$
DECLARE
    v_tenant_count INTEGER;
    v_needs_list_count INTEGER;
    v_event_phase_count INTEGER;
    v_custodian_linked INTEGER;
    v_warehouse_linked INTEGER;
BEGIN
    -- Check remaining counts
    SELECT COUNT(*) INTO v_tenant_count FROM public.tenant WHERE create_by_id IN ('TEST_SCRIPT', 'CUSTODIAN_MIGRATION');
    SELECT COUNT(*) INTO v_custodian_linked FROM public.custodian WHERE tenant_id IS NOT NULL;
    SELECT COUNT(*) INTO v_warehouse_linked FROM public.warehouse WHERE tenant_id IS NOT NULL;
    
    -- Check EP-02 tables if they exist
    BEGIN
        SELECT COUNT(*) INTO v_needs_list_count FROM public.needs_list WHERE create_by_id = 'TEST_SCRIPT';
    EXCEPTION WHEN undefined_table THEN
        v_needs_list_count := 0;
    END;
    
    BEGIN
        SELECT COUNT(*) INTO v_event_phase_count FROM public.event_phase WHERE create_by_id = 'TEST_SCRIPT';
    EXCEPTION WHEN undefined_table THEN
        v_event_phase_count := 0;
    END;
    
    RAISE NOTICE '============================================================';
    RAISE NOTICE 'DMIS TEST DATA PURGE COMPLETE';
    RAISE NOTICE '============================================================';
    RAISE NOTICE '';
    RAISE NOTICE 'VERIFICATION:';
    RAISE NOTICE '  - Test tenants remaining: %', v_tenant_count;
    RAISE NOTICE '  - Custodians with tenant_id: %', v_custodian_linked;
    RAISE NOTICE '  - Warehouses with tenant_id: %', v_warehouse_linked;
    RAISE NOTICE '  - Test needs lists remaining: %', v_needs_list_count;
    RAISE NOTICE '  - Test event phases remaining: %', v_event_phase_count;
    RAISE NOTICE '';
    
    IF v_tenant_count > 0 OR v_needs_list_count > 0 THEN
        RAISE WARNING 'Some test data may remain. Check for foreign key dependencies.';
    ELSE
        RAISE NOTICE 'All test data successfully removed.';
    END IF;
    
    RAISE NOTICE '';
    RAISE NOTICE 'SCHEMA STATUS:';
    RAISE NOTICE '  - Multi-tenancy tables preserved (empty)';
    RAISE NOTICE '  - custodian.tenant_id column preserved (cleared)';
    RAISE NOTICE '  - warehouse.tenant_id column preserved (cleared)';
    RAISE NOTICE '';
    RAISE NOTICE 'To completely remove schema, uncomment Section 4 in purge script.';
    RAISE NOTICE 'To recreate test data: psql -d dmis -f dmis_test_data.sql';
    RAISE NOTICE '============================================================';
END $$;
