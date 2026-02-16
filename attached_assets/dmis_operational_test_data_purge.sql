-- ============================================================================
-- DMIS Operational Test Data PURGE Script
-- ============================================================================
-- Version: 2.0  (matches dmis_operational_test_data.sql v2.0)
-- Date: 2026-02-13
-- Purpose: Removes operational test data seeded by dmis_operational_test_data.sql
--          Preserves schema structure, existing warehouses/items/roles, and
--          baseline tenant/EP-02 schema records (tenant tables, event phases, etc.).
--
-- SAFE TO RUN: Only deletes records created by TEST_SCRIPT or test users,
--              using the 9000+ ID range where applicable.
--
-- TEST ID RANGES:
--   Users:            9001 – 9005
--   Agency:           9001
--   Batch IDs:        9001 – 9045
--   Relief Requests:  9001 – 9003
--   Relief Packages:  9001 – 9006, 9011 – 9013, 9021 – 9022
--   Transfers:        9001 – 9002
--   Needs Lists:      tracked by create_by_id
--
-- USAGE:
--   psql -d dmis -f dmis_operational_test_data_purge.sql
-- ============================================================================

BEGIN;

-- ============================================================================
-- Phase 1: Delete child/dependent records first (FK dependencies)
-- ============================================================================

-- Needs list audit (depends on needs_list)
DELETE FROM public.needs_list_audit
WHERE actor_user_id IN ('kemar_logistics', 'andrea_executive', 'marcus_dg', 'TEST_SCRIPT');

-- Needs list items (depends on needs_list)
DELETE FROM public.needs_list_item WHERE create_by_id = 'TEST_SCRIPT';

-- Needs lists created by test users
DELETE FROM public.needs_list
WHERE create_by_id IN ('kemar_logistics', 'TEST_SCRIPT');

-- Burn rate snapshots (Marcus Garvey test data)
DELETE FROM public.burn_rate_snapshot
WHERE warehouse_id = 2 AND event_id = 8;

-- Warehouse sync logs (test warehouses)
DELETE FROM public.warehouse_sync_log
WHERE warehouse_id IN (1, 2, 3)
  AND sync_dtime > NOW() - INTERVAL '96 hours';

-- Transfer items (child of transfer)
DELETE FROM public.transfer_item WHERE transfer_id IN (9001, 9002);

-- Transfers
DELETE FROM public.transfer WHERE transfer_id IN (9001, 9002);

-- Relief package items (child of reliefpkg)
DELETE FROM public.reliefpkg_item
WHERE reliefpkg_id IN (9001, 9002, 9003, 9004, 9005, 9006, 9011, 9012, 9013, 9021, 9022);

-- Relief packages
DELETE FROM public.reliefpkg
WHERE reliefpkg_id IN (9001, 9002, 9003, 9004, 9005, 9006, 9011, 9012, 9013, 9021, 9022);

-- Relief requests
DELETE FROM public.reliefrqst WHERE reliefrqst_id IN (9001, 9002, 9003);

-- Item batches (test batches only — preserves existing batches)
DELETE FROM public.itembatch WHERE batch_id BETWEEN 9001 AND 9045;

-- Inventory records created by test script
-- (only deletes rows tagged TEST_SCRIPT, preserves existing inventory)
DELETE FROM public.inventory WHERE create_by_id = 'TEST_SCRIPT';

-- Lead time config
DELETE FROM public.lead_time_config WHERE create_by_id = 'TEST_SCRIPT';

-- Supplier test data
DELETE FROM public.supplier WHERE create_by_id = 'TEST_SCRIPT';

-- ============================================================================
-- Phase 2: Delete mapping/junction records
-- ============================================================================

-- Tenant-user mappings (if tenant tables exist)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='tenant_user') THEN
        DELETE FROM public.tenant_user WHERE create_by_id = 'TEST_SCRIPT';
        RAISE NOTICE 'Tenant-user mappings purged';
    END IF;
END $$;

-- Data sharing agreements (if tenant tables exist)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='data_sharing_agreement') THEN
        DELETE FROM public.data_sharing_agreement WHERE create_by_id = 'TEST_SCRIPT';
        RAISE NOTICE 'Data sharing agreements purged';
    END IF;
END $$;

-- User-role mappings (test users only)
DELETE FROM public.user_role WHERE user_id BETWEEN 9001 AND 9005;

-- Role-permission mappings (for permissions created by TEST_SCRIPT)
DELETE FROM public.role_permission
WHERE perm_id IN (
    SELECT perm_id FROM public.permission WHERE create_by_id = 'TEST_SCRIPT'
);

-- ============================================================================
-- Phase 3: Delete master records
-- ============================================================================

-- Agency
DO $$
BEGIN
    DELETE FROM public.agency WHERE agency_id = 9001;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'Agency 9001 delete skipped (may have remaining FKs): %', SQLERRM;
END $$;

-- Permissions (replenishment perms created by test script)
DELETE FROM public.permission WHERE create_by_id = 'TEST_SCRIPT';

-- Test users
DO $$
BEGIN
    DELETE FROM public."user" WHERE user_id BETWEEN 9001 AND 9005;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'User delete skipped (may have remaining FKs): %', SQLERRM;
END $$;

-- ============================================================================
-- Phase 4: Reset event current_phase
-- ============================================================================

UPDATE public.event SET current_phase = 'BASELINE'
WHERE event_id = 8
  AND current_phase = 'STABILIZED';

-- ============================================================================
-- Phase 5: Clean up test indexes
-- ============================================================================

DROP INDEX IF EXISTS idx_itembatch_test_wh;

COMMIT;

-- ============================================================================
-- Verification
-- ============================================================================

DO $$
DECLARE
    v_remaining INTEGER;
BEGIN
    SELECT COUNT(*) INTO v_remaining FROM public."user" WHERE user_id BETWEEN 9001 AND 9005;
    IF v_remaining > 0 THEN RAISE NOTICE 'WARNING: % test users remain (FK dependencies)', v_remaining; END IF;

    SELECT COUNT(*) INTO v_remaining FROM public.itembatch WHERE batch_id BETWEEN 9001 AND 9045;
    IF v_remaining > 0 THEN RAISE NOTICE 'WARNING: % test batches remain (FK dependencies)', v_remaining; END IF;

    SELECT COUNT(*) INTO v_remaining FROM public.permission WHERE create_by_id = 'TEST_SCRIPT';
    IF v_remaining > 0 THEN RAISE NOTICE 'WARNING: % test permissions remain', v_remaining; END IF;

    SELECT COUNT(*) INTO v_remaining FROM public.needs_list WHERE create_by_id IN ('kemar_logistics', 'TEST_SCRIPT');
    IF v_remaining > 0 THEN RAISE NOTICE 'WARNING: % test needs lists remain', v_remaining; END IF;

    SELECT COUNT(*) INTO v_remaining FROM public.reliefpkg WHERE reliefpkg_id IN (9001,9002,9003,9004,9005,9006,9011,9012,9013,9021,9022);
    IF v_remaining > 0 THEN RAISE NOTICE 'WARNING: % test relief packages remain', v_remaining; END IF;

    SELECT COUNT(*) INTO v_remaining FROM public.agency WHERE agency_id = 9001;
    IF v_remaining > 0 THEN RAISE NOTICE 'WARNING: % test agencies remain', v_remaining; END IF;

    RAISE NOTICE '============================================================';
    RAISE NOTICE 'DMIS OPERATIONAL TEST DATA PURGE COMPLETE';
    RAISE NOTICE '============================================================';
    RAISE NOTICE 'Schema structure preserved. Existing warehouses, items, roles';
    RAISE NOTICE 'and event records are untouched.';
    RAISE NOTICE '';
    RAISE NOTICE 'Baseline tenant/EP-02 schema is preserved by this purge.';
    RAISE NOTICE 'Use your environment rollback/migration tooling for full schema teardown.';
    RAISE NOTICE '============================================================';
END $$;
