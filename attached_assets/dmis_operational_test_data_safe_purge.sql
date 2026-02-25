-- ============================================================================
-- DMIS Operational Test Data SAFE PURGE Script
-- ============================================================================
-- Version: 3.0-safe
-- Date: 2026-02-16
-- Purpose: Removes data seeded by dmis_operational_test_data_safe.sql only.
--          Preserves baseline schema and non-test operational data.
--
-- SAFETY PRINCIPLES:
--   - Deletes only TST_OP_SAFE-tagged rows, fixed test ID ranges, and
--     deterministic test keys (e.g., needs_list_no LIKE 'NL-TST-%').
--   - Does NOT reset event.current_phase.
--   - Does NOT delete recent real sync/snapshot data.
--
-- USAGE:
--   psql -d dmis -f dmis_operational_test_data_safe_purge.sql
-- ============================================================================

BEGIN;

-- ============================================================================
-- Phase 1: Delete dependent records first (FK order)
-- ============================================================================

DELETE FROM public.needs_list_audit
WHERE needs_list_id IN (
    SELECT needs_list_id FROM public.needs_list WHERE needs_list_no LIKE 'NL-TST-%'
);

DELETE FROM public.needs_list_item
WHERE needs_list_id IN (
    SELECT needs_list_id FROM public.needs_list WHERE needs_list_no LIKE 'NL-TST-%'
);

DELETE FROM public.needs_list
WHERE needs_list_no LIKE 'NL-TST-%';

-- Deterministic snapshot window seeded by safe script
DELETE FROM public.burn_rate_snapshot
WHERE warehouse_id = 2
  AND event_id = 8
  AND item_id IN (1, 9)
  AND snapshot_dtime >= TIMESTAMP '2000-01-01 00:00:00'
  AND snapshot_dtime <  TIMESTAMP '2000-01-04 00:00:00';

-- Deterministic sync logs seeded by safe script
DELETE FROM public.warehouse_sync_log
WHERE sync_dtime >= TIMESTAMP '2000-01-01 00:00:00'
  AND sync_dtime <  TIMESTAMP '2000-01-04 00:00:00'
  AND triggered_by IN ('SYNC_TST', 'kemar_tst', 'devon_tst');

DELETE FROM public.transfer_item WHERE transfer_id IN (95001, 95002);
DELETE FROM public.transfer      WHERE transfer_id IN (95001, 95002);

DELETE FROM public.reliefpkg_item
WHERE reliefpkg_id IN (95001,95002,95003,95004,95005,95006,95011,95012,95013,95021,95022)
  AND create_by_id = 'TST_OP_SAFE';

DELETE FROM public.reliefpkg
WHERE reliefpkg_id IN (95001,95002,95003,95004,95005,95006,95011,95012,95013,95021,95022)
  AND create_by_id = 'TST_OP_SAFE';

DELETE FROM public.reliefrqst
WHERE reliefrqst_id IN (95001, 95002, 95003)
  AND create_by_id = 'TST_OP_SAFE';

DELETE FROM public.itembatch
WHERE batch_id BETWEEN 95001 AND 95045
  AND create_by_id = 'TST_OP_SAFE';

DELETE FROM public.inventory WHERE create_by_id = 'TST_OP_SAFE';
DELETE FROM public.lead_time_config WHERE create_by_id = 'TST_OP_SAFE';
DELETE FROM public.supplier WHERE create_by_id = 'TST_OP_SAFE';

-- ============================================================================
-- Phase 2: Mapping/junction records
-- ============================================================================

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='tenant_user') THEN
        DELETE FROM public.tenant_user WHERE create_by_id = 'TST_OP_SAFE';
        RAISE NOTICE 'Tenant-user mappings purged';
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='data_sharing_agreement') THEN
        DELETE FROM public.data_sharing_agreement WHERE create_by_id = 'TST_OP_SAFE';
        RAISE NOTICE 'Data sharing agreements purged';
    END IF;
END $$;

DELETE FROM public.user_role WHERE user_id BETWEEN 95001 AND 95005;

DELETE FROM public.role_permission
WHERE role_id IN (
    SELECT id FROM public.role WHERE code LIKE 'TST_%'
);

-- ============================================================================
-- Phase 3: Master records
-- ============================================================================

DELETE FROM public.agency
WHERE agency_id = 95001
  AND create_by_id = 'TST_OP_SAFE';

DELETE FROM public.permission WHERE create_by_id = 'TST_OP_SAFE';
DELETE FROM public.role WHERE code LIKE 'TST_%';

DELETE FROM public."user"
WHERE user_id BETWEEN 95001 AND 95005
  AND username IN ('kemar_tst', 'andrea_tst', 'marcus_tst', 'sarah_tst', 'devon_tst');

-- ============================================================================
-- Phase 4: Safe index cleanup
-- ============================================================================

DROP INDEX IF EXISTS idx_itembatch_tst_safe_wh;

-- ============================================================================
-- Verification
-- ============================================================================

DO $$
DECLARE
    v_remaining INTEGER;
    v_all_cleared BOOLEAN := TRUE;
BEGIN
    SELECT COUNT(*) INTO v_remaining FROM public."user" WHERE user_id BETWEEN 95001 AND 95005;
    IF v_remaining > 0 THEN
        RAISE NOTICE 'WARNING: % test users remain (FK dependencies)', v_remaining;
        v_all_cleared := FALSE;
    END IF;

    SELECT COUNT(*) INTO v_remaining FROM public.role WHERE code LIKE 'TST_%';
    IF v_remaining > 0 THEN
        RAISE NOTICE 'WARNING: % test roles remain', v_remaining;
        v_all_cleared := FALSE;
    END IF;

    SELECT COUNT(*) INTO v_remaining FROM public.permission WHERE create_by_id = 'TST_OP_SAFE';
    IF v_remaining > 0 THEN
        RAISE NOTICE 'WARNING: % test permissions remain', v_remaining;
        v_all_cleared := FALSE;
    END IF;

    SELECT COUNT(*) INTO v_remaining FROM public.itembatch WHERE batch_id BETWEEN 95001 AND 95045;
    IF v_remaining > 0 THEN
        RAISE NOTICE 'WARNING: % test batches remain (check create_by_id filter)', v_remaining;
        v_all_cleared := FALSE;
    END IF;

    SELECT COUNT(*) INTO v_remaining FROM public.needs_list WHERE needs_list_no LIKE 'NL-TST-%';
    IF v_remaining > 0 THEN
        RAISE NOTICE 'WARNING: % test needs lists remain', v_remaining;
        v_all_cleared := FALSE;
    END IF;

    SELECT COUNT(*) INTO v_remaining
    FROM public.burn_rate_snapshot
    WHERE warehouse_id = 2
      AND event_id = 8
      AND item_id IN (1, 9)
      AND snapshot_dtime >= TIMESTAMP '2000-01-01 00:00:00'
      AND snapshot_dtime <  TIMESTAMP '2000-01-04 00:00:00';
    IF v_remaining > 0 THEN
        RAISE NOTICE 'WARNING: % deterministic test snapshots remain', v_remaining;
        v_all_cleared := FALSE;
    END IF;

    IF v_all_cleared THEN
        RAISE NOTICE '============================================================';
        RAISE NOTICE 'DMIS OPERATIONAL TEST DATA SAFE PURGE COMPLETE';
        RAISE NOTICE '============================================================';
        RAISE NOTICE 'Only safe-seed artifacts were targeted. Baseline schema and';
        RAISE NOTICE 'non-test operational data were preserved.';
        RAISE NOTICE '============================================================';
    ELSE
        RAISE NOTICE '============================================================';
        RAISE NOTICE 'DMIS OPERATIONAL TEST DATA SAFE PURGE INCOMPLETE';
        RAISE NOTICE '============================================================';
        RAISE NOTICE 'Residual test artifacts were detected before commit.';
        RAISE NOTICE 'Review WARNING notices above before assuming success.';
        RAISE NOTICE '============================================================';
    END IF;
END $$;

COMMIT;
