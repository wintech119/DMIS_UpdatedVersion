-- ============================================================================
-- DMIS Operational Test Data SAFE Script
-- ============================================================================
-- Version: 3.0-safe
-- Date: 2026-02-16
-- Depends on: backend/EP02_SUPPLY_REPLENISHMENT_SCHEMA.sql already applied
-- Purpose: Populates isolated replenishment test fixtures without mutating
--          existing role-to-permission mappings or deleting non-test data.
--
-- SAFETY PRINCIPLES:
--   - Uses isolated test roles (code prefix TST_*)
--   - Uses dedicated test ID ranges (95001+)
--   - Uses create_by_id tag = 'TST_OP_SAFE'
--   - Avoids global updates to existing role mappings and event phases
--
-- STRATEGY:
--   - USES existing warehouses (1=Kingston, 2=Marcus Garvey, 3=Montego Bay)
--   - USES existing items (15 representative items)
--   - USES existing event (id=8)
--   - CREATES itembatch records (batch_id 95001-95045)
--   - CREATES 11 replenishment permissions (no review_start)
--   - CREATES test users (user_id 95001-95005)
--   - CREATES agency, relief requests, relief packages, transfers, needs lists
--
-- USAGE:
--   psql -d dmis -f dmis_operational_test_data_safe.sql
--
-- ROLLBACK:
--   psql -d dmis -f dmis_operational_test_data_safe_purge.sql
-- ============================================================================

BEGIN;

-- ============================================================================
-- SECTION 1: ADD current_phase TO EVENT TABLE (if not present)
-- ============================================================================
-- data_access.py queries event.current_phase; ensure the column exists.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name   = 'event'
          AND column_name  = 'current_phase'
    ) THEN
        ALTER TABLE public.event
            ADD COLUMN current_phase VARCHAR(20) DEFAULT 'BASELINE';
    END IF;
END $$;

-- ============================================================================
-- SECTION 2: PRE-FLIGHT CHECKS
-- ============================================================================
-- Fail fast if required baseline data is missing.

DO $$
DECLARE
    v_missing INTEGER;
BEGIN
    SELECT COUNT(*) INTO v_missing
    FROM (VALUES (1), (2), (3)) AS expected(warehouse_id)
    WHERE NOT EXISTS (
        SELECT 1 FROM public.warehouse w WHERE w.warehouse_id = expected.warehouse_id
    );
    IF v_missing > 0 THEN
        RAISE EXCEPTION 'Missing required warehouses (1,2,3). Seed aborted.';
    END IF;

    SELECT COUNT(*) INTO v_missing
    FROM (VALUES (1),(2),(7),(9),(16),(17),(19),(21),(58),(62),(85),(86),(89),(192),(195)) AS expected(item_id)
    WHERE NOT EXISTS (
        SELECT 1 FROM public.item i WHERE i.item_id = expected.item_id
    );
    IF v_missing > 0 THEN
        RAISE EXCEPTION 'Missing one or more required test items. Seed aborted.';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM public.event WHERE event_id = 8) THEN
        RAISE EXCEPTION 'Event id=8 not found. Create/select an event before running this seed.';
    END IF;

    IF EXISTS (SELECT 1 FROM public.agency WHERE agency_id = 95001 AND create_by_id <> 'TST_OP_SAFE') THEN
        RAISE EXCEPTION 'agency_id=95001 already used by non-test data. Seed aborted.';
    END IF;

    IF EXISTS (SELECT 1 FROM public.reliefrqst WHERE reliefrqst_id BETWEEN 95001 AND 95003 AND create_by_id <> 'TST_OP_SAFE') THEN
        RAISE EXCEPTION 'reliefrqst_id range 95001-95003 already used by non-test data. Seed aborted.';
    END IF;

    IF EXISTS (
        SELECT 1 FROM public.reliefpkg
        WHERE reliefpkg_id IN (95001,95002,95003,95004,95005,95006,95011,95012,95013,95021,95022)
          AND create_by_id <> 'TST_OP_SAFE'
    ) THEN
        RAISE EXCEPTION 'reliefpkg test IDs already used by non-test data. Seed aborted.';
    END IF;

    IF EXISTS (SELECT 1 FROM public.transfer WHERE transfer_id IN (95001, 95002) AND create_by_id <> 'TST_OP_SAFE') THEN
        RAISE EXCEPTION 'transfer IDs 95001/95002 already used by non-test data. Seed aborted.';
    END IF;

    IF EXISTS (SELECT 1 FROM public.itembatch WHERE batch_id BETWEEN 95001 AND 95045 AND create_by_id <> 'TST_OP_SAFE') THEN
        RAISE EXCEPTION 'itembatch range 95001-95045 already used by non-test data. Seed aborted.';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM public."user"
        WHERE user_id BETWEEN 95001 AND 95005
          AND create_by_id <> 'TST_OP_SAFE'
    ) THEN
        RAISE EXCEPTION 'user_id range 95001-95005 already used by non-test users. Seed aborted.';
    END IF;
END $$;

-- ============================================================================
-- SECTION 3: UNIT OF MEASURE REFERENCE DATA
-- ============================================================================

INSERT INTO public.unitofmeasure (uom_code, uom_desc, create_by_id, create_dtime, update_by_id, update_dtime, version_nbr)
VALUES
    ('PK',  'Pack',     'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW(), 1),
    ('BX',  'Box',      'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW(), 1),
    ('CS',  'Case',     'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW(), 1),
    ('KG',  'Kilogram', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW(), 1),
    ('L',   'Litre',    'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW(), 1),
    ('BG',  'Bag',      'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW(), 1),
    ('RL',  'Roll',     'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW(), 1),
    ('BT',  'Bottle',   'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW(), 1)
ON CONFLICT (uom_code) DO NOTHING;

-- ============================================================================
-- SECTION 4: RBAC PERMISSIONS (11 replenishment permissions)
-- ============================================================================
-- permission table: perm_id (auto), resource VARCHAR(40), action VARCHAR(32)

INSERT INTO public.permission (resource, action, create_by_id, update_by_id) VALUES
    ('replenishment.needs_list', 'preview',         'TST_OP_SAFE', 'TST_OP_SAFE'),
    ('replenishment.needs_list', 'create_draft',    'TST_OP_SAFE', 'TST_OP_SAFE'),
    ('replenishment.needs_list', 'edit_lines',      'TST_OP_SAFE', 'TST_OP_SAFE'),
    ('replenishment.needs_list', 'submit',          'TST_OP_SAFE', 'TST_OP_SAFE'),
    ('replenishment.needs_list', 'return',          'TST_OP_SAFE', 'TST_OP_SAFE'),
    ('replenishment.needs_list', 'reject',          'TST_OP_SAFE', 'TST_OP_SAFE'),
    ('replenishment.needs_list', 'approve',         'TST_OP_SAFE', 'TST_OP_SAFE'),
    ('replenishment.needs_list', 'escalate',        'TST_OP_SAFE', 'TST_OP_SAFE'),
    ('replenishment.needs_list', 'execute',         'TST_OP_SAFE', 'TST_OP_SAFE'),
    ('replenishment.needs_list', 'cancel',          'TST_OP_SAFE', 'TST_OP_SAFE'),
    ('replenishment.needs_list', 'review_comments', 'TST_OP_SAFE', 'TST_OP_SAFE')
ON CONFLICT (resource, action) DO NOTHING;

-- ============================================================================
-- SECTION 5: ISOLATED TEST ROLE -> PERMISSION MAPPINGS
-- ============================================================================
-- Uses TST_* roles to avoid mutating existing production-like roles.

DO $$
DECLARE
    v_role_logistics_mgr INTEGER;
    v_role_logistics_officer INTEGER;
    v_role_dir_peod INTEGER;
    v_role_dg INTEGER;
    v_role_readonly INTEGER;
    v_preview       INTEGER;
    v_create_draft  INTEGER;
    v_edit_lines    INTEGER;
    v_submit        INTEGER;
    v_return        INTEGER;
    v_reject        INTEGER;
    v_approve       INTEGER;
    v_escalate      INTEGER;
    v_execute       INTEGER;
    v_cancel        INTEGER;
    v_review_comms  INTEGER;
BEGIN
    INSERT INTO public.role (code, name, description)
    VALUES
        ('TST_LOGISTICS_MANAGER', 'Test Logistics Manager', 'Isolated test role for replenishment authoring/execution'),
        ('TST_LOGISTICS_OFFICER', 'Test Logistics Officer', 'Isolated test role for draft creation/edit'),
        ('TST_DIR_PEOD', 'Test Director PEOD', 'Isolated test approver role'),
        ('TST_DG', 'Test Director General', 'Isolated higher-tier approver role'),
        ('TST_READONLY', 'Test Readonly', 'Isolated preview-only role')
    ON CONFLICT (code) DO NOTHING;

    SELECT id INTO v_role_logistics_mgr FROM public.role WHERE code = 'TST_LOGISTICS_MANAGER';
    SELECT id INTO v_role_logistics_officer FROM public.role WHERE code = 'TST_LOGISTICS_OFFICER';
    SELECT id INTO v_role_dir_peod FROM public.role WHERE code = 'TST_DIR_PEOD';
    SELECT id INTO v_role_dg FROM public.role WHERE code = 'TST_DG';
    SELECT id INTO v_role_readonly FROM public.role WHERE code = 'TST_READONLY';

    SELECT perm_id INTO v_preview      FROM public.permission WHERE resource='replenishment.needs_list' AND action='preview';
    SELECT perm_id INTO v_create_draft FROM public.permission WHERE resource='replenishment.needs_list' AND action='create_draft';
    SELECT perm_id INTO v_edit_lines   FROM public.permission WHERE resource='replenishment.needs_list' AND action='edit_lines';
    SELECT perm_id INTO v_submit       FROM public.permission WHERE resource='replenishment.needs_list' AND action='submit';
    SELECT perm_id INTO v_return       FROM public.permission WHERE resource='replenishment.needs_list' AND action='return';
    SELECT perm_id INTO v_reject       FROM public.permission WHERE resource='replenishment.needs_list' AND action='reject';
    SELECT perm_id INTO v_approve      FROM public.permission WHERE resource='replenishment.needs_list' AND action='approve';
    SELECT perm_id INTO v_escalate     FROM public.permission WHERE resource='replenishment.needs_list' AND action='escalate';
    SELECT perm_id INTO v_execute      FROM public.permission WHERE resource='replenishment.needs_list' AND action='execute';
    SELECT perm_id INTO v_cancel       FROM public.permission WHERE resource='replenishment.needs_list' AND action='cancel';
    SELECT perm_id INTO v_review_comms FROM public.permission WHERE resource='replenishment.needs_list' AND action='review_comments';

    IF v_preview IS NULL
       OR v_create_draft IS NULL
       OR v_edit_lines IS NULL
       OR v_submit IS NULL
       OR v_return IS NULL
       OR v_reject IS NULL
       OR v_approve IS NULL
       OR v_escalate IS NULL
       OR v_execute IS NULL
       OR v_cancel IS NULL
       OR v_review_comms IS NULL
       OR v_role_logistics_mgr IS NULL
       OR v_role_logistics_officer IS NULL
       OR v_role_dir_peod IS NULL
       OR v_role_dg IS NULL
       OR v_role_readonly IS NULL THEN
        RAISE EXCEPTION 'Required permissions/roles missing. Seed aborted.';
    END IF;

    INSERT INTO public.role_permission (role_id, perm_id) VALUES
        (v_role_logistics_mgr, v_preview), (v_role_logistics_mgr, v_create_draft),
        (v_role_logistics_mgr, v_edit_lines), (v_role_logistics_mgr, v_submit),
        (v_role_logistics_mgr, v_execute), (v_role_logistics_mgr, v_cancel)
    ON CONFLICT (role_id, perm_id) DO NOTHING;

    INSERT INTO public.role_permission (role_id, perm_id) VALUES
        (v_role_logistics_officer, v_preview), (v_role_logistics_officer, v_create_draft),
        (v_role_logistics_officer, v_edit_lines)
    ON CONFLICT (role_id, perm_id) DO NOTHING;

    INSERT INTO public.role_permission (role_id, perm_id) VALUES
        (v_role_dir_peod, v_preview), (v_role_dir_peod, v_return), (v_role_dir_peod, v_reject),
        (v_role_dir_peod, v_approve), (v_role_dir_peod, v_escalate), (v_role_dir_peod, v_review_comms),
        (v_role_dg, v_preview), (v_role_dg, v_return), (v_role_dg, v_reject),
        (v_role_dg, v_approve), (v_role_dg, v_escalate), (v_role_dg, v_review_comms),
        (v_role_readonly, v_preview)
    ON CONFLICT (role_id, perm_id) DO NOTHING;
END $$;

-- ============================================================================
-- SECTION 6: TEST USERS (Five EP-02 Personas)
-- ============================================================================

DO $$
DECLARE
    v_collisions INTEGER;
BEGIN
    SELECT COUNT(*) INTO v_collisions
    FROM public."user"
    WHERE user_id BETWEEN 95001 AND 95005
      AND username NOT IN ('kemar_tst', 'andrea_tst', 'marcus_tst', 'sarah_tst', 'devon_tst');
    IF v_collisions > 0 THEN
        RAISE EXCEPTION 'User ID range 95001-95005 is already in use by non-test users. Abort.';
    END IF;

    SELECT COUNT(*) INTO v_collisions
    FROM public."user"
    WHERE username IN ('kemar_tst', 'andrea_tst', 'marcus_tst', 'sarah_tst', 'devon_tst')
      AND user_id NOT BETWEEN 95001 AND 95005;
    IF v_collisions > 0 THEN
        RAISE EXCEPTION 'Test usernames already exist outside the safe ID range. Abort.';
    END IF;

    INSERT INTO public."user" (
        user_id, email, password_hash, user_name, username,
        first_name, last_name, full_name, organization, job_title,
        status_code, assigned_warehouse_id,
        create_by_id, create_dtime, update_dtime
    ) VALUES
        (95001, 'kemar.brown+tst@odpem.gov.jm', 'KEYCLOAK_MANAGED', 'KEMAR',  'kemar_tst',  'Kemar',  'Brown',   'Kemar Brown',   'ODPEM', 'Logistics Manager',   'A', 1,    'TST_OP_SAFE', NOW(), NOW()),
        (95002, 'andrea.campbell+tst@odpem.gov.jm', 'KEYCLOAK_MANAGED', 'ANDREA', 'andrea_tst', 'Andrea', 'Campbell', 'Andrea Campbell', 'ODPEM', 'Senior Director PEOD', 'A', NULL, 'TST_OP_SAFE', NOW(), NOW()),
        (95003, 'marcus.reid+tst@odpem.gov.jm', 'KEYCLOAK_MANAGED', 'MARCUS', 'marcus_tst', 'Marcus', 'Reid',    'Marcus Reid',    'ODPEM', 'Director General',    'A', NULL, 'TST_OP_SAFE', NOW(), NOW()),
        (95004, 'sarah.johnson+tst@odpem.gov.jm', 'KEYCLOAK_MANAGED', 'SARAH',  'sarah_tst',  'Sarah',  'Johnson', 'Sarah Johnson',   'ODPEM', 'Dashboard Analyst',    'A', NULL, 'TST_OP_SAFE', NOW(), NOW()),
        (95005, 'devon.scott+tst@odpem.gov.jm', 'KEYCLOAK_MANAGED', 'DEVON',  'devon_tst',  'Devon',  'Scott',   'Devon Scott',     'ODPEM', 'Field Worker',         'A', 2,    'TST_OP_SAFE', NOW(), NOW())
    ON CONFLICT (user_id) DO UPDATE SET
        email = EXCLUDED.email,
        password_hash = EXCLUDED.password_hash,
        user_name = EXCLUDED.user_name,
        username = EXCLUDED.username,
        first_name = EXCLUDED.first_name,
        last_name = EXCLUDED.last_name,
        full_name = EXCLUDED.full_name,
        organization = EXCLUDED.organization,
        job_title = EXCLUDED.job_title,
        status_code = EXCLUDED.status_code,
        assigned_warehouse_id = EXCLUDED.assigned_warehouse_id,
        create_by_id = EXCLUDED.create_by_id,
        update_dtime = NOW();
END $$;

-- ============================================================================
-- SECTION 7: USER -> ROLE MAPPINGS
-- ============================================================================

DO $$
DECLARE
    v_role_logistics_mgr INTEGER;
    v_role_logistics_officer INTEGER;
    v_role_dir_peod INTEGER;
    v_role_dg INTEGER;
    v_role_readonly INTEGER;
BEGIN
    SELECT id INTO v_role_logistics_mgr FROM public.role WHERE code = 'TST_LOGISTICS_MANAGER';
    SELECT id INTO v_role_logistics_officer FROM public.role WHERE code = 'TST_LOGISTICS_OFFICER';
    SELECT id INTO v_role_dir_peod FROM public.role WHERE code = 'TST_DIR_PEOD';
    SELECT id INTO v_role_dg FROM public.role WHERE code = 'TST_DG';
    SELECT id INTO v_role_readonly FROM public.role WHERE code = 'TST_READONLY';

    IF v_role_logistics_mgr IS NULL OR v_role_logistics_officer IS NULL
       OR v_role_dir_peod IS NULL OR v_role_dg IS NULL
       OR v_role_readonly IS NULL THEN
        RAISE EXCEPTION 'One or more TST_* roles not found. Run Section 5 first. Seed aborted.';
    END IF;

    INSERT INTO public.user_role (user_id, role_id) VALUES
        (95001, v_role_logistics_mgr),
        (95002, v_role_dir_peod),
        (95003, v_role_dg),
        (95004, v_role_readonly),
        (95005, v_role_logistics_officer)
    ON CONFLICT (user_id, role_id) DO NOTHING;
END $$;

-- ============================================================================
-- SECTION 8: TEST AGENCY (required FK for relief packages)
-- ============================================================================
-- agency constraints: agency_name UPPERCASE, contact_name UPPERCASE,
-- agency_type IN ('DISTRIBUTOR','SHELTER'),
-- DISTRIBUTOR requires warehouse_id NOT NULL, SHELTER requires warehouse_id NULL

INSERT INTO public.agency (
    agency_id, agency_name, address1_text, parish_code,
    contact_name, phone_no, email_text,
    agency_type, warehouse_id, status_code,
    create_by_id, create_dtime, update_by_id, update_dtime, version_nbr
) VALUES (
    95001, 'ODPEM LOGISTICS TEST AGENCY', '2-4 HAINING ROAD', '01',
    'KEMAR BROWN', '876-555-0101', 'logistics@odpem.gov.jm',
    'DISTRIBUTOR', 1, 'A',
    'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW(), 1
)
ON CONFLICT (agency_id) DO NOTHING;

-- ============================================================================
-- SECTION 9: INVENTORY RECORDS (ensure exist for 15 test items × 3 warehouses)
-- ============================================================================
-- inventory PK: (inventory_id, item_id)
-- inventory_id = warehouse_id in the legacy DMIS 1:1 mapping

INSERT INTO public.inventory (
    inventory_id, item_id, usable_qty, reserved_qty, defective_qty, expired_qty,
    uom_code, status_code, reorder_qty,
    create_by_id, create_dtime, update_by_id, update_dtime, version_nbr
)
SELECT wh.id, itm.id, 0, 0, 0, 0, 'EA', 'A', 10,
       'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW(), 1
FROM (VALUES (1),(2),(3)) AS wh(id),
     (VALUES (1),(2),(7),(9),(16),(17),(19),(21),(58),(62),(85),(86),(89),(192),(195)) AS itm(id)
ON CONFLICT (inventory_id, item_id) DO NOTHING;

-- ============================================================================
-- SECTION 10: ITEM BATCHES (Test Stock Quantities)
-- ============================================================================
-- These quantities determine available stock at each warehouse.
-- Combined with burn rates from relief packages, they produce target severities.
--
-- KINGSTON (WH1):  Well-stocked main hub → mostly OK
-- MARCUS GARVEY (WH2): Heavily impacted, stocks depleting → CRITICAL/WARNING
-- MONTEGO BAY (WH3): Moderate stock → WATCH/OK

INSERT INTO public.itembatch (
    batch_id, inventory_id, item_id, batch_no, usable_qty, reserved_qty,
    defective_qty, expired_qty, uom_code, avg_unit_value, status_code,
    create_by_id, create_dtime, update_by_id, update_dtime
) VALUES
    -- ===================== KINGSTON (WH1, inventory_id=1) =====================
    -- High stock → OK severity with low burn rates
    (95001, 1,   1, 'TST-K-001', 5000.0, 0, 0, 0, 'EA', 50.00,  'A', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95002, 1,   2, 'TST-K-002', 1000.0, 0, 0, 0, 'EA', 200.00, 'A', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95003, 1,   7, 'TST-K-007', 3000.0, 0, 0, 0, 'EA', 150.00, 'A', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95004, 1,   9, 'TST-K-009', 2000.0, 0, 0, 0, 'EA', 300.00, 'A', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95005, 1,  16, 'TST-K-016',  800.0, 0, 0, 0, 'EA', 25.00,  'A', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95006, 1,  17, 'TST-K-017',  500.0, 0, 0, 0, 'EA', 10.00,  'A', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95007, 1,  19, 'TST-K-019',  400.0, 0, 0, 0, 'EA', 8.00,   'A', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95008, 1,  21, 'TST-K-021',  300.0, 0, 0, 0, 'EA', 15.00,  'A', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95009, 1,  58, 'TST-K-058', 1000.0, 0, 0, 0, 'EA', 5.00,   'A', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95010, 1,  62, 'TST-K-062',   15.0, 0, 0, 0, 'EA', 45000.00,'A', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95011, 1,  85, 'TST-K-085',   20.0, 0, 0, 0, 'EA', 85000.00,'A', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95012, 1,  86, 'TST-K-086',  200.0, 0, 0, 0, 'EA', 30.00,  'A', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95013, 1,  89, 'TST-K-089',  150.0, 0, 0, 0, 'EA', 50.00,  'A', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95014, 1, 192, 'TST-K-192',  500.0, 0, 0, 0, 'EA', 1200.00,'A', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95015, 1, 195, 'TST-K-195',  300.0, 0, 0, 0, 'EA', 1500.00,'A', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),

    -- ===================== MARCUS GARVEY (WH2, inventory_id=2) =====================
    -- Low stock with high burn rates → CRITICAL / WARNING
    (95016, 2,   1, 'TST-M-001',  200.0, 0, 0, 0, 'EA', 50.00,  'A', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95017, 2,   2, 'TST-M-002',   50.0, 0, 0, 0, 'EA', 200.00, 'A', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95018, 2,   7, 'TST-M-007',  100.0, 0, 0, 0, 'EA', 150.00, 'A', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95019, 2,   9, 'TST-M-009',  100.0, 0, 0, 0, 'EA', 300.00, 'A', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95020, 2,  16, 'TST-M-016',   30.0, 0, 0, 0, 'EA', 25.00,  'A', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95021, 2,  17, 'TST-M-017',   80.0, 0, 0, 0, 'EA', 10.00,  'A', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95022, 2,  19, 'TST-M-019',   60.0, 0, 0, 0, 'EA', 8.00,   'A', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95023, 2,  21, 'TST-M-021',   40.0, 0, 0, 0, 'EA', 15.00,  'A', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95024, 2,  58, 'TST-M-058',  100.0, 0, 0, 0, 'EA', 5.00,   'A', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95025, 2,  62, 'TST-M-062',    3.0, 0, 0, 0, 'EA', 45000.00,'A', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95026, 2,  85, 'TST-M-085',    5.0, 0, 0, 0, 'EA', 85000.00,'A', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95027, 2,  86, 'TST-M-086',   50.0, 0, 0, 0, 'EA', 30.00,  'A', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95028, 2,  89, 'TST-M-089',   30.0, 0, 0, 0, 'EA', 50.00,  'A', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95029, 2, 192, 'TST-M-192',   20.0, 0, 0, 0, 'EA', 1200.00,'A', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95030, 2, 195, 'TST-M-195',   15.0, 0, 0, 0, 'EA', 1500.00,'A', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),

    -- ===================== MONTEGO BAY (WH3, inventory_id=3) =====================
    -- Moderate stock → WATCH / OK
    (95031, 3,   1, 'TST-B-001', 1500.0, 0, 0, 0, 'EA', 50.00,  'A', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95032, 3,   2, 'TST-B-002',  300.0, 0, 0, 0, 'EA', 200.00, 'A', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95033, 3,   7, 'TST-B-007',  500.0, 0, 0, 0, 'EA', 150.00, 'A', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95034, 3,   9, 'TST-B-009',  400.0, 0, 0, 0, 'EA', 300.00, 'A', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95035, 3,  16, 'TST-B-016',  200.0, 0, 0, 0, 'EA', 25.00,  'A', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95036, 3,  17, 'TST-B-017',  150.0, 0, 0, 0, 'EA', 10.00,  'A', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95037, 3,  19, 'TST-B-019',  100.0, 0, 0, 0, 'EA', 8.00,   'A', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95038, 3,  21, 'TST-B-021',  200.0, 0, 0, 0, 'EA', 15.00,  'A', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95039, 3,  58, 'TST-B-058',  500.0, 0, 0, 0, 'EA', 5.00,   'A', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95040, 3,  62, 'TST-B-062',    8.0, 0, 0, 0, 'EA', 45000.00,'A', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95041, 3,  85, 'TST-B-085',   10.0, 0, 0, 0, 'EA', 85000.00,'A', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95042, 3,  86, 'TST-B-086',  100.0, 0, 0, 0, 'EA', 30.00,  'A', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95043, 3,  89, 'TST-B-089',   60.0, 0, 0, 0, 'EA', 50.00,  'A', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95044, 3, 192, 'TST-B-192',  300.0, 0, 0, 0, 'EA', 1200.00,'A', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95045, 3, 195, 'TST-B-195',  200.0, 0, 0, 0, 'EA', 1500.00,'A', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW())
ON CONFLICT (batch_id) DO NOTHING;

-- ============================================================================
-- SECTION 11: RELIEF REQUESTS (Burn Rate Source Data - prerequisite for packages)
-- ============================================================================
-- reliefrqst: status_code SMALLINT, urgency_ind IN ('L','M','H','C')
-- status_code = 0 is simplest (no review/action fields required)

INSERT INTO public.reliefrqst (
    reliefrqst_id, agency_id, request_date, urgency_ind, status_code,
    eligible_event_id, rqst_notes_text,
    create_by_id, create_dtime, version_nbr
) VALUES
    (95001, 95001, CURRENT_DATE, 'H', 0, 8, 'Test relief request for Marcus Garvey warehouse — high urgency',
     'TST_OP_SAFE', NOW(), 1),
    (95002, 95001, CURRENT_DATE, 'M', 0, 8, 'Test relief request for Montego Bay warehouse — moderate urgency',
     'TST_OP_SAFE', NOW(), 1),
    (95003, 95001, CURRENT_DATE, 'L', 0, 8, 'Test relief request for Kingston warehouse — routine resupply',
     'TST_OP_SAFE', NOW(), 1)
ON CONFLICT (reliefrqst_id) DO NOTHING;

-- ============================================================================
-- SECTION 12: RELIEF PACKAGES (Burn Rate Source — Dispatched Packages)
-- ============================================================================
-- Only status 'D' (Dispatched) has dispatch_dtime (enforced by CHECK constraint)
-- Packages spread across the 72-hour STABILIZED demand window
--
-- TO WH2 (Marcus Garvey): 6 packages → high burn rate
-- TO WH3 (Montego Bay):   3 packages → moderate burn rate
-- TO WH1 (Kingston):      2 packages → low burn rate

INSERT INTO public.reliefpkg (
    reliefpkg_id, to_inventory_id, reliefrqst_id, start_date,
    dispatch_dtime, status_code, agency_id, tracking_no,
    eligible_event_id,
    create_by_id, create_dtime, update_by_id, update_dtime, version_nbr
) VALUES
    -- TO MARCUS GARVEY (WH2) — 6 packages over 72h, high demand area
    (95001, 2, 95001, CURRENT_DATE, NOW() - INTERVAL '66 hours', 'D', 95001, 'TS00001', 8, 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW(), 1),
    (95002, 2, 95001, CURRENT_DATE, NOW() - INTERVAL '54 hours', 'D', 95001, 'TS00002', 8, 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW(), 1),
    (95003, 2, 95001, CURRENT_DATE, NOW() - INTERVAL '42 hours', 'D', 95001, 'TS00003', 8, 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW(), 1),
    (95004, 2, 95001, CURRENT_DATE, NOW() - INTERVAL '30 hours', 'D', 95001, 'TS00004', 8, 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW(), 1),
    (95005, 2, 95001, CURRENT_DATE, NOW() - INTERVAL '18 hours', 'D', 95001, 'TS00005', 8, 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW(), 1),
    (95006, 2, 95001, CURRENT_DATE, NOW() - INTERVAL '4 hours',  'D', 95001, 'TS00006', 8, 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW(), 1),
    -- TO MONTEGO BAY (WH3) — 3 packages, moderate demand
    (95011, 3, 95002, CURRENT_DATE, NOW() - INTERVAL '60 hours', 'D', 95001, 'TS00011', 8, 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW(), 1),
    (95012, 3, 95002, CURRENT_DATE, NOW() - INTERVAL '36 hours', 'D', 95001, 'TS00012', 8, 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW(), 1),
    (95013, 3, 95002, CURRENT_DATE, NOW() - INTERVAL '8 hours',  'D', 95001, 'TS00013', 8, 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW(), 1),
    -- TO KINGSTON (WH1) — 2 packages, low demand
    (95021, 1, 95003, CURRENT_DATE, NOW() - INTERVAL '48 hours', 'D', 95001, 'TS00021', 8, 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW(), 1),
    (95022, 1, 95003, CURRENT_DATE, NOW() - INTERVAL '12 hours', 'D', 95001, 'TS00022', 8, 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW(), 1)
ON CONFLICT (reliefpkg_id) DO NOTHING;

-- ============================================================================
-- SECTION 13: RELIEF PACKAGE ITEMS (Quantities That Produce Burn Rates)
-- ============================================================================
-- Burn Rate = SUM(dispatched item_qty) / demand_window_hours (72h for STABILIZED)
-- fr_inventory_id = source warehouse, batch_id + item_id must match itembatch at source
--
-- TO WH2 targets (burn/hr): water=50, water5g=5, food=15, MRE=15, purif=5,
--   wipes=2, babywipes=1, gloves=1, AED=0.5, tape=2, alben=1, tarp10=3, tarp12=1
-- TO WH3 targets: water=10, food=5, MRE=5, wipes=1, babywipes=1, AED=0.2, tarp10=1
-- TO WH1 targets: water=3, MRE=2, wipes=0.5, tarp10=0.5

INSERT INTO public.reliefpkg_item (
    reliefpkg_id, fr_inventory_id, batch_id, item_id,
    item_qty, uom_code,
    create_by_id, create_dtime, update_by_id, update_dtime
) VALUES
    -- ===================== TO MARCUS GARVEY (Packages 95001-95006) =====================
    -- Source: Kingston (WH1, fr_inventory_id=1), using WH1 batches
    -- Per package: total/6 to achieve target burn rates over 72h

    -- Package 95001 (dispatched 66h ago)
    (95001, 1, 95001,   1, 600, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),  -- water 12pk
    (95001, 1, 95002,   2,  60, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),  -- water 5gal
    (95001, 1, 95003,   7, 180, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),  -- food pkg
    (95001, 1, 95004,   9, 180, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),  -- MRE
    (95001, 1, 95005,  16,  60, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),  -- purif tablets
    (95001, 1, 95006,  17,  24, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),  -- wipes
    (95001, 1, 95007,  19,  12, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),  -- baby wipes
    (95001, 1, 95008,  21,  12, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),  -- gloves
    (95001, 1, 95011,  85,   6, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),  -- AED
    (95001, 1, 95012,  86,  24, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),  -- tape
    (95001, 1, 95013,  89,  12, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),  -- albendazole
    (95001, 1, 95014, 192,  36, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),  -- tarp 10x12
    (95001, 1, 95015, 195,  12, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),  -- tarp 12x16

    -- Package 95002 (dispatched 54h ago)
    (95002, 1, 95001,   1, 600, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95002, 1, 95002,   2,  60, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95002, 1, 95003,   7, 180, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95002, 1, 95004,   9, 180, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95002, 1, 95005,  16,  60, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95002, 1, 95006,  17,  24, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95002, 1, 95007,  19,  12, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95002, 1, 95008,  21,  12, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95002, 1, 95011,  85,   6, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95002, 1, 95012,  86,  24, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95002, 1, 95013,  89,  12, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95002, 1, 95014, 192,  36, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95002, 1, 95015, 195,  12, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),

    -- Package 95003 (dispatched 42h ago)
    (95003, 1, 95001,   1, 600, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95003, 1, 95002,   2,  60, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95003, 1, 95003,   7, 180, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95003, 1, 95004,   9, 180, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95003, 1, 95005,  16,  60, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95003, 1, 95006,  17,  24, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95003, 1, 95007,  19,  12, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95003, 1, 95008,  21,  12, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95003, 1, 95011,  85,   6, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95003, 1, 95012,  86,  24, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95003, 1, 95013,  89,  12, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95003, 1, 95014, 192,  36, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95003, 1, 95015, 195,  12, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),

    -- Package 95004 (dispatched 30h ago)
    (95004, 1, 95001,   1, 600, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95004, 1, 95002,   2,  60, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95004, 1, 95003,   7, 180, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95004, 1, 95004,   9, 180, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95004, 1, 95005,  16,  60, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95004, 1, 95006,  17,  24, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95004, 1, 95007,  19,  12, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95004, 1, 95008,  21,  12, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95004, 1, 95011,  85,   6, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95004, 1, 95012,  86,  24, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95004, 1, 95013,  89,  12, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95004, 1, 95014, 192,  36, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95004, 1, 95015, 195,  12, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),

    -- Package 95005 (dispatched 18h ago)
    (95005, 1, 95001,   1, 600, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95005, 1, 95002,   2,  60, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95005, 1, 95003,   7, 180, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95005, 1, 95004,   9, 180, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95005, 1, 95005,  16,  60, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95005, 1, 95006,  17,  24, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95005, 1, 95007,  19,  12, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95005, 1, 95008,  21,  12, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95005, 1, 95011,  85,   6, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95005, 1, 95012,  86,  24, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95005, 1, 95013,  89,  12, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95005, 1, 95014, 192,  36, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95005, 1, 95015, 195,  12, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),

    -- Package 95006 (dispatched 4h ago)
    (95006, 1, 95001,   1, 600, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95006, 1, 95002,   2,  60, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95006, 1, 95003,   7, 180, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95006, 1, 95004,   9, 180, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95006, 1, 95005,  16,  60, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95006, 1, 95006,  17,  24, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95006, 1, 95007,  19,  12, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95006, 1, 95008,  21,  12, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95006, 1, 95011,  85,   6, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95006, 1, 95012,  86,  24, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95006, 1, 95013,  89,  12, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95006, 1, 95014, 192,  36, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95006, 1, 95015, 195,  12, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),

    -- ===================== TO MONTEGO BAY (Packages 95011-95013) =====================
    -- Source: Kingston (WH1), fewer items per package

    -- Package 95011
    (95011, 1, 95001,   1, 240, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95011, 1, 95003,   7, 120, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95011, 1, 95004,   9, 120, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95011, 1, 95006,  17,  24, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95011, 1, 95007,  19,  24, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95011, 1, 95011,  85,   5, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95011, 1, 95014, 192,  24, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),

    -- Package 95012
    (95012, 1, 95001,   1, 240, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95012, 1, 95003,   7, 120, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95012, 1, 95004,   9, 120, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95012, 1, 95006,  17,  24, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95012, 1, 95007,  19,  24, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95012, 1, 95011,  85,   5, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95012, 1, 95014, 192,  24, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),

    -- Package 95013
    (95013, 1, 95001,   1, 240, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95013, 1, 95003,   7, 120, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95013, 1, 95004,   9, 120, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95013, 1, 95006,  17,  24, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95013, 1, 95007,  19,  24, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95013, 1, 95011,  85,   5, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95013, 1, 95014, 192,  24, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),

    -- ===================== TO KINGSTON (Packages 95021-95022) =====================
    -- Source: Marcus Garvey (WH2), using WH2 batches

    -- Package 95021
    (95021, 2, 95016,   1, 108, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95021, 2, 95019,   9,  72, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95021, 2, 95021,  17,  18, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95021, 2, 95029, 192,  18, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),

    -- Package 95022
    (95022, 2, 95016,   1, 108, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95022, 2, 95019,   9,  72, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95022, 2, 95021,  17,  18, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
    (95022, 2, 95029, 192,  18, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW())
ON CONFLICT (reliefpkg_id, fr_inventory_id, batch_id, item_id) DO NOTHING;

-- ============================================================================
-- SECTION 14: INBOUND TRANSFERS (Horizon A — Dispatched)
-- ============================================================================
-- Only transfers with status 'D' count as strict inbound per data_access.py.
-- transfer requires: fr_inventory_id, to_inventory_id, verify_by_id (NOT NULL)

INSERT INTO public.transfer (
    transfer_id, fr_inventory_id, to_inventory_id, eligible_event_id,
    transfer_date, status_code, verify_by_id,
    dispatched_at, dispatched_by, expected_arrival,
    create_by_id, create_dtime, update_by_id, update_dtime, version_nbr
) VALUES
    -- Transfer 95001: Kingston (WH1) → Marcus Garvey (WH2) — emergency water resupply
    (95001, 1, 2, 8, CURRENT_DATE, 'D', 'SYSADMIN',
     NOW() - INTERVAL '2 hours', 'kemar_tst', NOW() + INTERVAL '6 hours',
     'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW(), 1),
    -- Transfer 95002: Montego Bay (WH3) → Marcus Garvey (WH2) — shelter supplies
    (95002, 3, 2, 8, CURRENT_DATE, 'D', 'SYSADMIN',
     NOW() - INTERVAL '1 hour', 'kemar_tst', NOW() + INTERVAL '8 hours',
     'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW(), 1)
ON CONFLICT (transfer_id) DO NOTHING;

-- Transfer items (batch_id + inventory_id reference itembatch at SOURCE warehouse)
INSERT INTO public.transfer_item (
    transfer_id, item_id, batch_id, inventory_id, item_qty, uom_code,
    create_by_id, create_dtime, update_by_id, update_dtime
) VALUES
    -- Transfer 95001: Kingston → Marcus Garvey
    (95001,   1, 95001, 1, 500, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),   -- 500 water bottles
    (95001,   9, 95004, 1, 200, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),   -- 200 MREs
    (95001, 192, 95014, 1,  50, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),   -- 50 tarps
    (95001,  85, 95011, 1,   3, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),   -- 3 AED sets
    -- Transfer 95002: Montego Bay → Marcus Garvey
    (95002,   1, 95031, 3, 300, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),   -- 300 water bottles
    (95002,  19, 95037, 3,  50, 'EA', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW())    -- 50 baby wipes
ON CONFLICT (transfer_id, item_id, batch_id) DO NOTHING;

-- ============================================================================
-- SECTION 15: EVENT PHASE NOTE (NO GLOBAL UPDATE)
-- ============================================================================
-- Safe seed does not force-update event.current_phase.
-- Needs lists are seeded with event_phase='STABILIZED' values directly.

-- ============================================================================
-- SECTION 16: NEEDS LISTS IN VARIOUS WORKFLOW STATES
-- ============================================================================
-- Uses correct column names for the Django-managed needs_list table:
--   needs_list_no, event_phase, calculation_dtime, demand_window_hours,
--   planning_window_hours, safety_factor, data_freshness_level, status_code,
--   total_gap_qty, submitted_at, submitted_by, etc.

DO $$
DECLARE
    v_nl_draft     INTEGER;
    v_nl_submitted INTEGER;
    v_nl_review    INTEGER;
    v_nl_approved  INTEGER;
    v_nl_rejected  INTEGER;
    v_nl_executing INTEGER;
BEGIN
    -- Deterministic rerun cleanup (needs-list workflow fixtures).
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

    -- NL #1: DRAFT at Marcus Garvey (generated by Kemar, not yet submitted)
    INSERT INTO public.needs_list (
        needs_list_no, event_id, warehouse_id, event_phase,
        calculation_dtime, demand_window_hours, planning_window_hours, safety_factor,
        data_freshness_level, status_code, total_gap_qty, total_estimated_value,
        create_by_id, create_dtime, update_by_id, update_dtime
    ) VALUES (
        'NL-TST-MG-2026-001', 8, 2, 'STABILIZED',
        NOW() - INTERVAL '2 hours', 72, 168, 1.25,
        'MEDIUM', 'DRAFT', 12200.00, 2500000.00,
        'kemar_tst', NOW() - INTERVAL '2 hours', 'kemar_tst', NOW() - INTERVAL '2 hours'
    ) ON CONFLICT (needs_list_no) DO UPDATE SET update_dtime = EXCLUDED.update_dtime, update_by_id = EXCLUDED.update_by_id RETURNING needs_list_id INTO v_nl_draft;

    -- NL #2: PENDING_APPROVAL at Kingston (submitted by Kemar)
    INSERT INTO public.needs_list (
        needs_list_no, event_id, warehouse_id, event_phase,
        calculation_dtime, demand_window_hours, planning_window_hours, safety_factor,
        data_freshness_level, status_code, total_gap_qty, total_estimated_value,
        submitted_at, submitted_by,
        create_by_id, create_dtime, update_by_id, update_dtime
    ) VALUES (
        'NL-TST-KW-2026-001', 8, 1, 'STABILIZED',
        NOW() - INTERVAL '6 hours', 72, 168, 1.25,
        'HIGH', 'PENDING_APPROVAL', 4430.00, 900000.00,
        NOW() - INTERVAL '5 hours', 'kemar_tst',
        'kemar_tst', NOW() - INTERVAL '6 hours', 'kemar_tst', NOW() - INTERVAL '5 hours'
    ) ON CONFLICT (needs_list_no) DO UPDATE SET update_dtime = EXCLUDED.update_dtime, update_by_id = EXCLUDED.update_by_id RETURNING needs_list_id INTO v_nl_submitted;

    -- NL #3: UNDER_REVIEW at Marcus Garvey (Andrea reviewing)
    INSERT INTO public.needs_list (
        needs_list_no, event_id, warehouse_id, event_phase,
        calculation_dtime, demand_window_hours, planning_window_hours, safety_factor,
        data_freshness_level, status_code, total_gap_qty,
        submitted_at, submitted_by, under_review_at, under_review_by,
        create_by_id, create_dtime, update_by_id, update_dtime
    ) VALUES (
        'NL-TST-MG-2026-002', 8, 2, 'STABILIZED',
        NOW() - INTERVAL '12 hours', 72, 168, 1.25,
        'MEDIUM', 'UNDER_REVIEW', 15800.00,
        NOW() - INTERVAL '10 hours', 'kemar_tst',
        NOW() - INTERVAL '8 hours', 'andrea_tst',
        'kemar_tst', NOW() - INTERVAL '12 hours', 'andrea_tst', NOW() - INTERVAL '8 hours'
    ) ON CONFLICT (needs_list_no) DO UPDATE SET update_dtime = EXCLUDED.update_dtime, update_by_id = EXCLUDED.update_by_id RETURNING needs_list_id INTO v_nl_review;

    -- NL #4: APPROVED at Marcus Garvey (approved by Andrea)
    INSERT INTO public.needs_list (
        needs_list_no, event_id, warehouse_id, event_phase,
        calculation_dtime, demand_window_hours, planning_window_hours, safety_factor,
        data_freshness_level, status_code, total_gap_qty,
        submitted_at, submitted_by,
        under_review_at, under_review_by,
        approved_at, approved_by,
        notes_text,
        create_by_id, create_dtime, update_by_id, update_dtime
    ) VALUES (
        'NL-TST-MG-2026-003', 8, 2, 'STABILIZED',
        NOW() - INTERVAL '24 hours', 72, 168, 1.25,
        'HIGH', 'APPROVED', 11900.00,
        NOW() - INTERVAL '22 hours', 'kemar_tst',
        NOW() - INTERVAL '20 hours', 'andrea_tst',
        NOW() - INTERVAL '18 hours', 'andrea_tst',
        'Approved — critical items confirmed. Prioritize water and medical.',
        'kemar_tst', NOW() - INTERVAL '24 hours', 'andrea_tst', NOW() - INTERVAL '18 hours'
    ) ON CONFLICT (needs_list_no) DO UPDATE SET update_dtime = EXCLUDED.update_dtime, update_by_id = EXCLUDED.update_by_id RETURNING needs_list_id INTO v_nl_approved;

    -- NL #5: REJECTED at Montego Bay (rejected by Andrea)
    INSERT INTO public.needs_list (
        needs_list_no, event_id, warehouse_id, event_phase,
        calculation_dtime, demand_window_hours, planning_window_hours, safety_factor,
        data_freshness_level, status_code, total_gap_qty,
        submitted_at, submitted_by,
        rejected_at, rejected_by, rejection_reason,
        create_by_id, create_dtime, update_by_id, update_dtime
    ) VALUES (
        'NL-TST-MB-2026-001', 8, 3, 'STABILIZED',
        NOW() - INTERVAL '36 hours', 72, 168, 1.25,
        'LOW', 'REJECTED', 2800.00,
        NOW() - INTERVAL '34 hours', 'kemar_tst',
        NOW() - INTERVAL '30 hours', 'andrea_tst',
        'Quantities exceed projected need for Montego Bay. Reduce and resubmit.',
        'kemar_tst', NOW() - INTERVAL '36 hours', 'andrea_tst', NOW() - INTERVAL '30 hours'
    ) ON CONFLICT (needs_list_no) DO UPDATE SET update_dtime = EXCLUDED.update_dtime, update_by_id = EXCLUDED.update_by_id RETURNING needs_list_id INTO v_nl_rejected;

    -- NL #6: IN_PROGRESS at Marcus Garvey (being fulfilled)
    INSERT INTO public.needs_list (
        needs_list_no, event_id, warehouse_id, event_phase,
        calculation_dtime, demand_window_hours, planning_window_hours, safety_factor,
        data_freshness_level, status_code, total_gap_qty,
        submitted_at, submitted_by,
        approved_at, approved_by,
        notes_text,
        create_by_id, create_dtime, update_by_id, update_dtime
    ) VALUES (
        'NL-TST-MG-2026-004', 8, 2, 'STABILIZED',
        NOW() - INTERVAL '48 hours', 72, 168, 1.25,
        'HIGH', 'IN_PROGRESS', 10200.00,
        NOW() - INTERVAL '46 hours', 'kemar_tst',
        NOW() - INTERVAL '42 hours', 'andrea_tst',
        'Emergency approval — Marcus Garvey critical. Fast-track transfers.',
        'kemar_tst', NOW() - INTERVAL '48 hours', 'kemar_tst', NOW() - INTERVAL '40 hours'
    ) ON CONFLICT (needs_list_no) DO UPDATE SET update_dtime = EXCLUDED.update_dtime, update_by_id = EXCLUDED.update_by_id RETURNING needs_list_id INTO v_nl_executing;

    -- ===================== NEEDS LIST ITEMS =====================
    -- Uses correct columns: horizon_a_qty, horizon_b_qty, horizon_c_qty,
    -- available_stock, inbound_transfer_qty, inbound_donation_qty, inbound_procurement_qty,
    -- severity_level, coverage_qty, fulfillment_status

    -- NL #1 (DRAFT) — Marcus Garvey items, Kemar hasn't submitted yet
    INSERT INTO public.needs_list_item (
        needs_list_id, item_id, uom_code,
        burn_rate, burn_rate_source, available_stock, reserved_qty,
        inbound_transfer_qty, inbound_donation_qty, inbound_procurement_qty,
        required_qty, coverage_qty, gap_qty, time_to_stockout_hours,
        severity_level, horizon_a_qty, horizon_b_qty, horizon_c_qty,
        fulfilled_qty, fulfillment_status,
        create_by_id, create_dtime, update_by_id, update_dtime
    ) VALUES
        (v_nl_draft, 1,   'EA', 50.0, 'CALCULATED', 200, 0, 0, 0, 0, 9000, 200, 8800, 4.0,   'CRITICAL', 8800, 0, 0, 0, 'PENDING', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
        (v_nl_draft, 9,   'EA', 15.0, 'CALCULATED', 100, 0, 0, 0, 0, 2700, 100, 2600, 6.7,   'CRITICAL', 2600, 0, 0, 0, 'PENDING', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
        (v_nl_draft, 85,  'EA', 0.5,  'CALCULATED',   5, 0, 0, 0, 0,   90,   5,   85, 10.0,  'WARNING',    85, 0, 0, 0, 'PENDING', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
        (v_nl_draft, 192, 'EA', 3.0,  'CALCULATED',  20, 0, 0, 0, 0,  648,  20,  628, 6.7,   'CRITICAL',  628, 0, 0, 0, 'PENDING', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
        (v_nl_draft, 86,  'EA', 2.0,  'BASELINE',    50, 0, 0, 0, 0,  420,  50,  370, 25.0,  'WATCH',       0, 370, 0, 0, 'PENDING', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW());

    -- NL #2 (PENDING_APPROVAL) — Kingston items
    INSERT INTO public.needs_list_item (
        needs_list_id, item_id, uom_code,
        burn_rate, burn_rate_source, available_stock, reserved_qty,
        inbound_transfer_qty, inbound_donation_qty, inbound_procurement_qty,
        required_qty, coverage_qty, gap_qty, time_to_stockout_hours,
        severity_level, horizon_a_qty, horizon_b_qty, horizon_c_qty,
        fulfilled_qty, fulfillment_status,
        create_by_id, create_dtime, update_by_id, update_dtime
    ) VALUES
        (v_nl_submitted, 85,  'EA', 0.1, 'BASELINE',   20, 0, 0, 0, 0,  21,  20, 1, 200.0,  'OK',    0, 0, 1, 0, 'PENDING', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
        (v_nl_submitted, 17,  'EA', 0.5, 'CALCULATED', 500, 0, 0, 0, 0, 630, 500, 130, 1000.0,'OK',    0, 130, 0, 0, 'PENDING', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
        (v_nl_submitted, 9,   'EA', 2.0, 'CALCULATED', 2000,0, 0, 0, 0, 5250,2000,3250, 1000.0,'OK', 0, 0, 3250, 0, 'PENDING', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW());

    -- NL #3 (UNDER_REVIEW) — Marcus Garvey critical items
    INSERT INTO public.needs_list_item (
        needs_list_id, item_id, uom_code,
        burn_rate, burn_rate_source, available_stock, reserved_qty,
        inbound_transfer_qty, inbound_donation_qty, inbound_procurement_qty,
        required_qty, coverage_qty, gap_qty, time_to_stockout_hours,
        severity_level, horizon_a_qty, horizon_a_source_warehouse_id,
        horizon_b_qty, horizon_c_qty,
        fulfilled_qty, fulfillment_status,
        create_by_id, create_dtime, update_by_id, update_dtime
    ) VALUES
        (v_nl_review, 1,   'EA', 50.0, 'CALCULATED', 200, 0, 500, 0, 0, 9000, 700, 8300, 4.0,  'CRITICAL', 8300, 1, 0, 0, 0, 'PENDING', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
        (v_nl_review, 16,  'EA', 5.0,  'CALCULATED',  30, 0, 0,   0, 0,  900,  30,  870, 6.0,  'CRITICAL',  870, NULL, 0, 0, 0, 'PENDING', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
        (v_nl_review, 85,  'EA', 0.5,  'CALCULATED',   5, 0, 3,   0, 0,   90,   8,   82, 10.0, 'WARNING',    82, 1, 0, 0, 0, 'PENDING', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
        (v_nl_review, 192, 'EA', 3.0,  'CALCULATED',  20, 0, 50,  0, 0,  648,  70,  578, 6.7,  'CRITICAL',  578, 1, 0, 0, 0, 'PENDING', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
        (v_nl_review, 9,   'EA', 15.0, 'CALCULATED', 100, 0, 200, 0, 0, 2700, 300, 2400, 6.7,  'CRITICAL', 2400, 1, 0, 0, 0, 'PENDING', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
        (v_nl_review, 86,  'EA', 2.0,  'BASELINE',    50, 0, 0,   0, 0,  420,  50,  370, 25.0, 'WATCH',       0, NULL, 370, 0, 0, 'PENDING', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW());

    -- NL #4 (APPROVED) — Marcus Garvey, approved with adjustments
    INSERT INTO public.needs_list_item (
        needs_list_id, item_id, uom_code,
        burn_rate, burn_rate_source, available_stock, reserved_qty,
        inbound_transfer_qty, inbound_donation_qty, inbound_procurement_qty,
        required_qty, coverage_qty, gap_qty, time_to_stockout_hours,
        severity_level, horizon_a_qty, horizon_a_source_warehouse_id,
        horizon_b_qty, horizon_c_qty,
        adjusted_qty, adjustment_reason, adjusted_by, adjusted_at,
        fulfilled_qty, fulfillment_status,
        create_by_id, create_dtime, update_by_id, update_dtime
    ) VALUES
        (v_nl_approved, 1,   'EA', 50.0, 'CALCULATED', 200, 0, 500, 0, 0, 9000, 700, 8300, 4.0, 'CRITICAL', 8000, 1, 0, 300, 8000, 'PARTIAL_COVERAGE', 'andrea_tst', NOW() - INTERVAL '20 hours', 0, 'PENDING', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
        (v_nl_approved, 9,   'EA', 15.0, 'CALCULATED', 100, 0, 200, 0, 0, 2700, 300, 2400, 6.7, 'CRITICAL', 2400, 1, 0, 0, NULL, NULL, NULL, NULL, 0, 'PENDING', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
        (v_nl_approved, 192, 'EA', 3.0,  'CALCULATED',  20, 0, 50,  0, 0,  648,  70,  578, 6.7, 'CRITICAL',  578, 1, 0, 0, NULL, NULL, NULL, NULL, 0, 'PENDING', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
        (v_nl_approved, 85,  'EA', 0.5,  'CALCULATED',   5, 0, 3,   0, 0,   90,   8,   82, 10.0,'WARNING',    82, 1, 0, 0, NULL, NULL, NULL, NULL, 0, 'PENDING', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW());

    -- NL #5 (REJECTED) — Montego Bay items
    INSERT INTO public.needs_list_item (
        needs_list_id, item_id, uom_code,
        burn_rate, burn_rate_source, available_stock, reserved_qty,
        inbound_transfer_qty, inbound_donation_qty, inbound_procurement_qty,
        required_qty, coverage_qty, gap_qty, time_to_stockout_hours,
        severity_level, horizon_a_qty, horizon_b_qty, horizon_c_qty,
        fulfilled_qty, fulfillment_status,
        create_by_id, create_dtime, update_by_id, update_dtime
    ) VALUES
        (v_nl_rejected, 1,   'EA', 10.0, 'CALCULATED', 1500, 0, 0, 0, 0, 2100, 1500, 600, 150.0, 'OK', 0, 600, 0, 0, 'CANCELLED', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
        (v_nl_rejected, 9,   'EA', 5.0,  'CALCULATED',  400, 0, 0, 0, 0, 1050,  400, 650, 80.0,  'OK', 0, 650, 0, 0, 'CANCELLED', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
        (v_nl_rejected, 17,  'EA', 1.0,  'CALCULATED',  150, 0, 0, 0, 0,  210,  150,  60, 150.0, 'OK', 0, 60,  0, 0, 'CANCELLED', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW());

    -- NL #6 (IN_PROGRESS) — Marcus Garvey, being fulfilled
    INSERT INTO public.needs_list_item (
        needs_list_id, item_id, uom_code,
        burn_rate, burn_rate_source, available_stock, reserved_qty,
        inbound_transfer_qty, inbound_donation_qty, inbound_procurement_qty,
        required_qty, coverage_qty, gap_qty, time_to_stockout_hours,
        severity_level, horizon_a_qty, horizon_a_source_warehouse_id,
        horizon_b_qty, horizon_c_qty,
        fulfilled_qty, fulfillment_status,
        create_by_id, create_dtime, update_by_id, update_dtime
    ) VALUES
        (v_nl_executing, 1,   'EA', 50.0, 'CALCULATED', 200, 0, 500, 0, 0, 8000, 700, 7300, 4.0,  'CRITICAL', 7300, 1, 0, 0, 3000, 'PARTIAL',   'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
        (v_nl_executing, 85,  'EA', 0.5,  'CALCULATED',   5, 0, 3,   0, 0,   90,   8,   82, 10.0, 'WARNING',    82, 1, 0, 0,   82, 'FULFILLED', 'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
        (v_nl_executing, 192, 'EA', 3.0,  'CALCULATED',  20, 0, 50,  0, 0,  600,  70,  530, 6.7,  'CRITICAL',  530, 1, 0, 0,  200, 'PARTIAL',   'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW()),
        (v_nl_executing, 9,   'EA', 15.0, 'CALCULATED', 100, 0, 200, 0, 0, 2500, 300, 2200, 6.7,  'CRITICAL',    0, NULL, 0, 2200,   0, 'PENDING',   'TST_OP_SAFE', NOW(), 'TST_OP_SAFE', NOW());

    -- ===================== AUDIT TRAIL =====================
    -- needs_list_audit: NO create_by_id column. Uses actor_user_id (varchar 20).

    INSERT INTO public.needs_list_audit (
        needs_list_id, action_type, field_name, old_value, new_value,
        reason_code, notes_text, actor_user_id, action_dtime
    ) VALUES
        -- NL#2: Created → Submitted
        (v_nl_submitted, 'CREATED',   'status_code', NULL,    'DRAFT',            'SYSTEM', 'Needs list generated from stock status dashboard', 'kemar_tst', NOW() - INTERVAL '6 hours'),
        (v_nl_submitted, 'SUBMITTED', 'status_code', 'DRAFT', 'PENDING_APPROVAL', 'USER',   'Submitted for approval — Kingston items for review', 'kemar_tst', NOW() - INTERVAL '5 hours'),
        -- NL#3: Created → Submitted → Under Review
        (v_nl_review,    'CREATED',        'status_code', NULL,               'DRAFT',              'SYSTEM', 'Needs list generated', 'kemar_tst',   NOW() - INTERVAL '12 hours'),
        (v_nl_review,    'SUBMITTED',      'status_code', 'DRAFT',            'PENDING_APPROVAL',   'USER',   'Submitted',            'kemar_tst',   NOW() - INTERVAL '10 hours'),
        (v_nl_review,    'STATUS_CHANGED', 'status_code', 'PENDING_APPROVAL', 'UNDER_REVIEW',       'USER',   'Andrea started review', 'andrea_tst', NOW() - INTERVAL '8 hours'),
        -- NL#4: Full lifecycle → Approved
        (v_nl_approved,  'CREATED',   'status_code', NULL,               'DRAFT',            'SYSTEM', 'Needs list generated',                  'kemar_tst',   NOW() - INTERVAL '24 hours'),
        (v_nl_approved,  'SUBMITTED', 'status_code', 'DRAFT',            'PENDING_APPROVAL', 'USER',   'Submitted — urgent Marcus Garvey needs','kemar_tst',   NOW() - INTERVAL '22 hours'),
        (v_nl_approved,  'APPROVED',  'status_code', 'PENDING_APPROVAL', 'APPROVED',         'USER',   'Approved — critical items confirmed',   'andrea_tst',  NOW() - INTERVAL '18 hours'),
        (v_nl_approved,  'QUANTITY_ADJUSTED', 'adjusted_qty', '9000', '8000', 'PARTIAL_COVERAGE', 'Water adjusted per transfer capacity', 'andrea_tst', NOW() - INTERVAL '20 hours'),
        -- NL#5: Rejected
        (v_nl_rejected,  'CREATED',   'status_code', NULL,               'DRAFT',            'SYSTEM', 'Needs list generated', 'kemar_tst', NOW() - INTERVAL '36 hours'),
        (v_nl_rejected,  'SUBMITTED', 'status_code', 'DRAFT',            'PENDING_APPROVAL', 'USER',   'Submitted — Montego Bay resupply', 'kemar_tst', NOW() - INTERVAL '34 hours'),
        (v_nl_rejected,  'REJECTED',  'status_code', 'PENDING_APPROVAL', 'REJECTED',         'USER',   'Quantities exceed projected need',  'andrea_tst', NOW() - INTERVAL '30 hours'),
        -- NL#6: Full lifecycle → In Progress
        (v_nl_executing, 'CREATED',        'status_code', NULL,               'DRAFT',            'SYSTEM', 'Emergency needs list',   'kemar_tst',  NOW() - INTERVAL '48 hours'),
        (v_nl_executing, 'SUBMITTED',      'status_code', 'DRAFT',            'PENDING_APPROVAL', 'USER',   'Emergency submission',   'kemar_tst',  NOW() - INTERVAL '46 hours'),
        (v_nl_executing, 'APPROVED',       'status_code', 'PENDING_APPROVAL', 'APPROVED',         'USER',   'Emergency approval',     'andrea_tst', NOW() - INTERVAL '42 hours'),
        (v_nl_executing, 'STATUS_CHANGED', 'status_code', 'APPROVED',         'IN_PROGRESS',      'USER',   'Preparation started',    'kemar_tst',  NOW() - INTERVAL '40 hours');

    RAISE NOTICE 'Needs lists created: draft=%, submitted=%, review=%, approved=%, rejected=%, executing=%',
        v_nl_draft, v_nl_submitted, v_nl_review, v_nl_approved, v_nl_rejected, v_nl_executing;
END $$;

-- ============================================================================
-- SECTION 17: BURN RATE SNAPSHOTS (Historical Trending Data)
-- ============================================================================
-- 24 deterministic snapshots in a fixed date window for safe purge.

DO $$
DECLARE
    v_snap_time TIMESTAMP;
    v_i INTEGER;
BEGIN
    DELETE FROM public.burn_rate_snapshot
    WHERE warehouse_id = 2
      AND event_id = 8
      AND item_id IN (1, 9)
      AND snapshot_dtime >= TIMESTAMP '2000-01-01 00:00:00'
      AND snapshot_dtime <  TIMESTAMP '2000-01-04 00:00:00';

    FOR v_i IN 0..11 LOOP
        v_snap_time := TIMESTAMP '2000-01-01 00:00:00' + (v_i * INTERVAL '6 hours');

        INSERT INTO public.burn_rate_snapshot (
            warehouse_id, item_id, event_id, event_phase, snapshot_dtime,
            demand_window_hours, fulfillment_count, total_fulfilled_qty,
            burn_rate, burn_rate_source, data_freshness_level,
            time_to_stockout_hours, available_stock_at_calc
        ) VALUES
            -- Water at Marcus Garvey - burn rate trending up
            (2, 1, 8, 'STABILIZED', v_snap_time, 72,
             6, 3600 + (v_i * 50),
             50.0 + (v_i * 0.7),
             'CALCULATED', 'MEDIUM',
             GREATEST(1.0, 4.0 - (v_i * 0.3)),
             GREATEST(50, 1200 - (v_i * 100))),
            -- MRE at Marcus Garvey - burn rate stable
            (2, 9, 8, 'STABILIZED', v_snap_time, 72,
             6, 1080,
             15.0,
             'CALCULATED', 'MEDIUM',
             GREATEST(2.0, (GREATEST(50.0, 600.0 - (v_i * 50.0))) / 15.0),
             GREATEST(50, 600 - (v_i * 50)));
    END LOOP;
END $$;

-- ============================================================================
-- SECTION 18: WAREHOUSE SYNC LOGS (Data Freshness History)
-- ============================================================================

DO $$
BEGIN
    -- Purge deterministic sync rows from prior safe runs.
    DELETE FROM public.warehouse_sync_log
    WHERE sync_dtime >= TIMESTAMP '2000-01-01 00:00:00'
      AND sync_dtime <  TIMESTAMP '2000-01-04 00:00:00'
      AND triggered_by IN ('SYNC_TST', 'kemar_tst', 'devon_tst');

    INSERT INTO public.warehouse_sync_log (warehouse_id, sync_dtime, sync_type, sync_status, items_synced, error_message, triggered_by) VALUES
        -- Kingston: frequent successful syncs
        (1, TIMESTAMP '2000-01-03 00:00:00', 'SCHEDULED', 'SUCCESS', 15, NULL, 'SYNC_TST'),
        (1, TIMESTAMP '2000-01-03 00:30:00', 'SCHEDULED', 'SUCCESS', 15, NULL, 'SYNC_TST'),
        (1, TIMESTAMP '2000-01-03 01:00:00', 'SCHEDULED', 'SUCCESS', 15, NULL, 'SYNC_TST'),
        (1, TIMESTAMP '2000-01-03 01:30:00', 'SCHEDULED', 'SUCCESS', 15, NULL, 'SYNC_TST'),
        (1, TIMESTAMP '2000-01-03 02:00:00', 'SCHEDULED', 'SUCCESS', 15, NULL, 'SYNC_TST'),
        (1, TIMESTAMP '2000-01-03 02:30:00', 'SCHEDULED', 'SUCCESS', 15, NULL, 'SYNC_TST'),
        -- Marcus Garvey: mixed quality sync history
        (2, TIMESTAMP '2000-01-02 19:00:00', 'MANUAL',    'SUCCESS', 15, NULL, 'kemar_tst'),
        (2, TIMESTAMP '2000-01-02 16:00:00', 'SCHEDULED', 'FAILED',  0,  'Connection timeout - cellular network down', 'SYNC_TST'),
        (2, TIMESTAMP '2000-01-02 12:00:00', 'MANUAL',    'PARTIAL', 10, 'Partial sync - 5 items failed checksum', 'devon_tst'),
        (2, TIMESTAMP '2000-01-02 06:00:00', 'SCHEDULED', 'SUCCESS', 15, NULL, 'SYNC_TST'),
        -- Montego Bay: infrequent syncs
        (3, TIMESTAMP '2000-01-02 10:00:00', 'SCHEDULED', 'SUCCESS', 15, NULL, 'SYNC_TST'),
        (3, TIMESTAMP '2000-01-02 04:00:00', 'SCHEDULED', 'FAILED',  0,  'Database connection pool exhausted', 'SYNC_TST');
END $$;

-- ============================================================================
-- SECTION 19: SUPPLIER TEST DATA (Horizon C — Procurement)
-- ============================================================================

INSERT INTO public.supplier (
    supplier_code, supplier_name, contact_name, phone_no, email_text,
    address_text, parish_code, default_lead_time_days,
    is_framework_supplier, framework_contract_no, framework_expiry_date,
    status_code, create_by_id, update_by_id
) VALUES
    ('SUP-GBS', 'GRACE BIOSYSTEMS LTD',      'Michael Chen',   '876-555-0201', 'sales@gracebio.com.jm',
     '12 Marcus Garvey Dr, Kingston', '01', 7,  TRUE,  'GOJ-FW-2026-001', '2027-03-31',
     'A', 'TST_OP_SAFE', 'TST_OP_SAFE'),
    ('SUP-JAM', 'JAMAICA MEDICAL SUPPLIES',   'Donna Wright',   '876-555-0202', 'orders@jammedsup.com.jm',
     '45 Half Way Tree Rd, Kingston', '01', 5,  TRUE,  'GOJ-FW-2026-002', '2027-06-30',
     'A', 'TST_OP_SAFE', 'TST_OP_SAFE'),
    ('SUP-CAR', 'CARIBBEAN PROVISIONS CO',    'Andre Thompson', '876-555-0203', 'supply@caribprov.com',
     '8 Port Royal St, Kingston',     '01', 14, FALSE, NULL, NULL,
     'A', 'TST_OP_SAFE', 'TST_OP_SAFE'),
    ('SUP-INT', 'INTERNATIONAL RELIEF SUPPLY','Sarah Palmer',   '1-305-555-0300','orders@intrelief.org',
     '100 NW 12th Ave, Miami FL',     NULL, 21, FALSE, NULL, NULL,
     'A', 'TST_OP_SAFE', 'TST_OP_SAFE')
ON CONFLICT (supplier_code) DO NOTHING;

-- ============================================================================
-- SECTION 20: LEAD TIME CONFIGURATION
-- ============================================================================

INSERT INTO public.lead_time_config (
    horizon, from_warehouse_id, to_warehouse_id, lead_time_hours,
    is_default, effective_from,
    create_by_id, update_by_id
) VALUES
    -- Horizon A: Transfer lead times (specific routes)
    -- NOTE: c_ltc_a_warehouses requires from/to warehouse_id NOT NULL for horizon A
    ('A', 1, 2, 6,  FALSE, CURRENT_DATE, 'TST_OP_SAFE', 'TST_OP_SAFE'),   -- Kingston → Marcus Garvey: 6h
    ('A', 1, 3, 8,  FALSE, CURRENT_DATE, 'TST_OP_SAFE', 'TST_OP_SAFE'),   -- Kingston → Montego Bay: 8h
    ('A', 3, 2, 10, FALSE, CURRENT_DATE, 'TST_OP_SAFE', 'TST_OP_SAFE'),   -- Montego Bay → Marcus Garvey: 10h
    ('A', 2, 1, 8,  FALSE, CURRENT_DATE, 'TST_OP_SAFE', 'TST_OP_SAFE'),   -- Marcus Garvey → Kingston: 8h (reverse)
    -- Horizon B: Donation lead times
    ('B', NULL, NULL, 48, TRUE,  CURRENT_DATE, 'TST_OP_SAFE', 'TST_OP_SAFE'),
    -- Horizon C: Procurement lead times
    ('C', NULL, NULL, 336,TRUE,  CURRENT_DATE, 'TST_OP_SAFE', 'TST_OP_SAFE')
ON CONFLICT (config_id) DO NOTHING;

-- ============================================================================
-- SECTION 21: TENANT-USER MAPPINGS (if tenant tables exist)
-- ============================================================================

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='tenant_user') THEN
        INSERT INTO public.tenant_user (tenant_id, user_id, is_primary_tenant, access_level, assigned_by, create_by_id)
        SELECT t.tenant_id, u.user_id, TRUE,
               CASE u.user_id
                   WHEN 95001 THEN 'FULL'
                   WHEN 95002 THEN 'FULL'
                   WHEN 95003 THEN 'ADMIN'
                   WHEN 95004 THEN 'READ_ONLY'
                   WHEN 95005 THEN 'LIMITED'
               END,
               95003,
               'TST_OP_SAFE'
        FROM public.tenant t, (VALUES (95001),(95002),(95003),(95004),(95005)) AS u(user_id)
        WHERE t.tenant_code = 'ODPEM-LOGISTICS'
        ON CONFLICT (tenant_id, user_id) DO NOTHING;

        RAISE NOTICE 'Tenant-user mappings created';
    ELSE
        RAISE NOTICE 'tenant_user table not found - skipping (apply baseline tenant schema first)';
    END IF;
END $$;

-- ============================================================================
-- SECTION 22: DATA SHARING AGREEMENTS (if tenant tables exist)
-- ============================================================================

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='data_sharing_agreement') THEN
        INSERT INTO public.data_sharing_agreement (from_tenant_id, to_tenant_id, data_category, permission_level, agreement_notes, status_code, approved_by, approved_at, create_by_id, update_by_id)
        SELECT f.tenant_id, t.tenant_id, 'INVENTORY', 'READ',
            'JRC can view ODPEM inventory levels for donation coordination',
            'A', 95003, NOW() - INTERVAL '30 days', 'TST_OP_SAFE', 'TST_OP_SAFE'
        FROM public.tenant f, public.tenant t
        WHERE f.tenant_code = 'ODPEM-LOGISTICS' AND t.tenant_code = 'JRC'
        ON CONFLICT DO NOTHING;

        RAISE NOTICE 'Data sharing agreements created';
    ELSE
        RAISE NOTICE 'data_sharing_agreement table not found — skipping';
    END IF;
END $$;

-- ============================================================================
-- SECTION 23: INDEXES FOR TEST DATA PERFORMANCE
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_itembatch_tst_safe_wh ON public.itembatch(inventory_id)
    WHERE inventory_id IN (1, 2, 3) AND create_by_id = 'TST_OP_SAFE';

-- ============================================================================
-- COMMIT
-- ============================================================================

COMMIT;

-- ============================================================================
-- SECTION 24: POST-EXECUTION SUMMARY & VERIFICATION
-- ============================================================================

DO $$
DECLARE
    v_user_count     INTEGER;
    v_perm_count     INTEGER;
    v_rp_count       INTEGER;
    v_batch_count    INTEGER;
    v_pkg_count      INTEGER;
    v_nl_count       INTEGER;
    v_nli_count      INTEGER;
    v_audit_count    INTEGER;
    v_snapshot_count INTEGER;
    v_transfer_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO v_user_count     FROM public."user"          WHERE user_id BETWEEN 95001 AND 95005;
    SELECT COUNT(*) INTO v_perm_count     FROM public.permission      WHERE create_by_id = 'TST_OP_SAFE';
    SELECT COUNT(*) INTO v_rp_count       FROM public.role_permission rp
                                          JOIN public.permission p ON rp.perm_id = p.perm_id
                                          WHERE p.create_by_id = 'TST_OP_SAFE';
    SELECT COUNT(*) INTO v_batch_count    FROM public.itembatch       WHERE batch_id BETWEEN 95001 AND 95045;
    SELECT COUNT(*) INTO v_pkg_count      FROM public.reliefpkg       WHERE create_by_id = 'TST_OP_SAFE';
    SELECT COUNT(*) INTO v_transfer_count FROM public.transfer        WHERE create_by_id = 'TST_OP_SAFE';
    SELECT COUNT(*) INTO v_nl_count       FROM public.needs_list      WHERE needs_list_no LIKE 'NL-TST-%';
    SELECT COUNT(*) INTO v_nli_count      FROM public.needs_list_item WHERE create_by_id = 'TST_OP_SAFE';
    SELECT COUNT(*) INTO v_audit_count
    FROM public.needs_list_audit
    WHERE needs_list_id IN (SELECT needs_list_id FROM public.needs_list WHERE needs_list_no LIKE 'NL-TST-%');
    SELECT COUNT(*) INTO v_snapshot_count
    FROM public.burn_rate_snapshot
    WHERE warehouse_id = 2
      AND event_id = 8
      AND snapshot_dtime >= TIMESTAMP '2000-01-01 00:00:00'
      AND snapshot_dtime <  TIMESTAMP '2000-01-04 00:00:00';

    RAISE NOTICE '============================================================';
    RAISE NOTICE 'DMIS OPERATIONAL TEST DATA CREATION COMPLETE';
    RAISE NOTICE '============================================================';
    RAISE NOTICE '';
    RAISE NOTICE 'RBAC FIXTURES:';
    RAISE NOTICE '  Test users:         % (kemar, andrea, marcus, sarah, devon)', v_user_count;
    RAISE NOTICE '  Permissions:        % (11 replenishment permissions)', v_perm_count;
    RAISE NOTICE '  Role-perm mappings: % (isolated TST_* roles)', v_rp_count;
    RAISE NOTICE '';
    RAISE NOTICE 'INVENTORY DATA (using existing warehouses 1, 2, 3):';
    RAISE NOTICE '  Item batches:       % (test stock at Kingston, Marcus Garvey, Montego Bay)', v_batch_count;
    RAISE NOTICE '';
    RAISE NOTICE 'BURN RATE DATA:';
    RAISE NOTICE '  Relief packages:    % (dispatched within demand window)', v_pkg_count;
    RAISE NOTICE '  Transfers:          % (inbound dispatched)', v_transfer_count;
    RAISE NOTICE '  Rate snapshots:     % (historical trending for Marcus Garvey)', v_snapshot_count;
    RAISE NOTICE '';
    RAISE NOTICE 'NEEDS LIST WORKFLOW:';
    RAISE NOTICE '  Needs lists:        % (DRAFT, PENDING, REVIEW, APPROVED, REJECTED, IN_PROGRESS)', v_nl_count;
    RAISE NOTICE '  Line items:         %', v_nli_count;
    RAISE NOTICE '  Audit records:      %', v_audit_count;
    RAISE NOTICE '';
    RAISE NOTICE 'EXPECTED SEVERITY DISTRIBUTION:';
    RAISE NOTICE '  KINGSTON (WH1):      All OK (well-stocked main hub, low burn rate)';
    RAISE NOTICE '  MARCUS GARVEY (WH2): 5 CRITICAL, 3 WARNING, 5 WATCH (heavily impacted)';
    RAISE NOTICE '  MONTEGO BAY (WH3):   1 WATCH, rest OK (moderate stock)';
    RAISE NOTICE '';
    RAISE NOTICE 'RBAC TEST SCENARIOS:';
    RAISE NOTICE '  kemar_tst  (95001): TST_LOGISTICS_MANAGER - create, edit, submit, execute, cancel';
    RAISE NOTICE '  andrea_tst (95002): TST_DIR_PEOD         - approve/reject/return/escalate';
    RAISE NOTICE '  marcus_tst (95003): TST_DG               - higher-tier approvals';
    RAISE NOTICE '  sarah_tst  (95004): TST_READONLY         - preview/dashboard only';
    RAISE NOTICE '  devon_tst  (95005): TST_LOGISTICS_OFFICER- preview/create_draft/edit_lines';
    RAISE NOTICE '';
    RAISE NOTICE 'To purge: psql -d dmis -f dmis_operational_test_data_safe_purge.sql';
    RAISE NOTICE '============================================================';
END $$;




