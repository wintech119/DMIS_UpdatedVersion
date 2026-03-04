-- DMIS Master Table Wave 1 (Safe/Additive) SQL
-- Generated: 2026-03-03
-- Notes:
--   1) Run in a controlled maintenance window.
--   2) Take a backup/snapshot first.
--   3) Keep statements idempotent where possible.

BEGIN;

-- ---------------------------------------------------------------------------
-- 1) Document event_phase snapshot semantics
-- ---------------------------------------------------------------------------
COMMENT ON COLUMN event_phase.demand_window_hours IS
'Snapshot copied from event_phase_config at phase activation. Do not update after activation.';

COMMENT ON COLUMN event_phase.planning_window_hours IS
'Snapshot copied from event_phase_config at phase activation. Do not update after activation.';

COMMENT ON COLUMN event_phase.buffer_multiplier IS
'Snapshot copied from event_phase_config-derived safety policy at phase activation.';

-- ---------------------------------------------------------------------------
-- 2) Candidate cleanup: itemcostdef (guarded)
-- ---------------------------------------------------------------------------
-- Precondition checks:
--   - table exists
--   - no FK dependencies
--   - no data rows
DO $$
DECLARE
    v_exists boolean;
    v_count bigint;
    v_fk_count bigint;
BEGIN
    SELECT EXISTS(
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = current_schema()
          AND table_name = 'itemcostdef'
    ) INTO v_exists;

    IF NOT v_exists THEN
        RAISE NOTICE 'itemcostdef does not exist; skipping drop.';
        RETURN;
    END IF;

    EXECUTE 'SELECT COUNT(*) FROM itemcostdef' INTO v_count;

    SELECT COUNT(*)
    INTO v_fk_count
    FROM information_schema.table_constraints tc
    JOIN information_schema.constraint_column_usage ccu
      ON ccu.constraint_name = tc.constraint_name
     AND ccu.table_schema = tc.table_schema
    WHERE tc.constraint_type = 'FOREIGN KEY'
      AND tc.table_schema = current_schema()
      AND ccu.table_name = 'itemcostdef';

    IF v_count = 0 AND v_fk_count = 0 THEN
        EXECUTE 'DROP TABLE itemcostdef';
        RAISE NOTICE 'Dropped itemcostdef (empty and unreferenced).';
    ELSE
        RAISE NOTICE 'Skipped dropping itemcostdef: rows=%, fk_refs=%', v_count, v_fk_count;
    END IF;
END $$;

COMMIT;

