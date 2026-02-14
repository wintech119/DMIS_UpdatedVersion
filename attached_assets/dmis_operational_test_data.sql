-- ============================================================================
-- DMIS Operational Test Data Script
-- ============================================================================
-- Version: 2.0  (complete rewrite for actual DB schema)
-- Date: 2026-02-13
-- Depends on: dmis_test_data.sql (run that script FIRST for tenant tables)
-- Purpose: Populates RBAC fixtures, inventory, burn-rate source data,
--          and needs-list workflow records for thorough EP-02 testing.
--
-- STRATEGY:
--   - USES existing warehouses (1=Kingston, 2=Marcus Garvey, 3=Montego Bay)
--   - USES existing items (HADR-xxxx series, 15 representative items)
--   - USES existing roles (13-22) and existing event (id=8)
--   - CREATES new itembatch records (batch_id 9001-9045)
--   - CREATES new permissions (12 replenishment perms)
--   - CREATES test users (user_id 9001-9005) for RBAC testing
--   - CREATES agency, relief requests, relief packages, transfers, needs lists
--   - All test records tagged with create_by_id = 'TEST_SCRIPT'
--
-- TEST ID RANGES:
--   Users:            9001 – 9005
--   Agency:           9001
--   Batch IDs:        9001 – 9045  (15 items × 3 warehouses)
--   Relief Requests:  9001 – 9003
--   Relief Packages:  9001 – 9006, 9011 – 9013, 9021 – 9022
--   Transfers:        9001 – 9002
--   Needs Lists:      (auto via SERIAL, tracked by create_by_id)
--
-- TEST ITEMS (15 existing items across 5 categories):
--   Cat 1 FOOD_WATER:  1, 2, 7, 9, 16
--   Cat 2 MEDICAL:     85, 86, 89
--   Cat 3 SHELTER:     192, 195
--   Cat 4 HYGIENE:     17, 19, 21
--   Cat 5 LOGS_ENGR:   58, 62
--
-- USAGE:
--   psql -d dmis -f dmis_operational_test_data.sql
--
-- ROLLBACK:
--   psql -d dmis -f dmis_operational_test_data_purge.sql
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
-- SECTION 2: UNIT OF MEASURE REFERENCE DATA
-- ============================================================================

INSERT INTO public.unitofmeasure (uom_code, uom_desc, create_by_id, create_dtime, update_by_id, update_dtime, version_nbr)
VALUES
    ('PK',  'Pack',     'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW(), 1),
    ('BX',  'Box',      'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW(), 1),
    ('CS',  'Case',     'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW(), 1),
    ('KG',  'Kilogram', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW(), 1),
    ('L',   'Litre',    'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW(), 1),
    ('BG',  'Bag',      'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW(), 1),
    ('RL',  'Roll',     'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW(), 1),
    ('BT',  'Bottle',   'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW(), 1)
ON CONFLICT (uom_code) DO NOTHING;

-- ============================================================================
-- SECTION 3: RBAC PERMISSIONS (12 replenishment permissions)
-- ============================================================================
-- permission table: perm_id (auto), resource VARCHAR(40), action VARCHAR(32)
-- These are queried by backend/api/rbac.py as f"{resource}.{action}"

INSERT INTO public.permission (resource, action, create_by_id, update_by_id) VALUES
    ('replenishment.needs_list', 'preview',         'TEST_SCRIPT', 'TEST_SCRIPT'),
    ('replenishment.needs_list', 'create_draft',    'TEST_SCRIPT', 'TEST_SCRIPT'),
    ('replenishment.needs_list', 'edit_lines',      'TEST_SCRIPT', 'TEST_SCRIPT'),
    ('replenishment.needs_list', 'submit',          'TEST_SCRIPT', 'TEST_SCRIPT'),
    ('replenishment.needs_list', 'review_start',    'TEST_SCRIPT', 'TEST_SCRIPT'),
    ('replenishment.needs_list', 'return',          'TEST_SCRIPT', 'TEST_SCRIPT'),
    ('replenishment.needs_list', 'reject',          'TEST_SCRIPT', 'TEST_SCRIPT'),
    ('replenishment.needs_list', 'approve',         'TEST_SCRIPT', 'TEST_SCRIPT'),
    ('replenishment.needs_list', 'escalate',        'TEST_SCRIPT', 'TEST_SCRIPT'),
    ('replenishment.needs_list', 'execute',         'TEST_SCRIPT', 'TEST_SCRIPT'),
    ('replenishment.needs_list', 'cancel',          'TEST_SCRIPT', 'TEST_SCRIPT'),
    ('replenishment.needs_list', 'review_comments', 'TEST_SCRIPT', 'TEST_SCRIPT')
ON CONFLICT (resource, action) DO NOTHING;

-- ============================================================================
-- SECTION 4: ROLE → PERMISSION MAPPINGS
-- ============================================================================
-- Maps existing roles to the new permissions.
-- Mirrors _DEV_ROLE_PERMISSION_MAP in rbac.py:
--   LOGISTICS (role 17): preview, create_draft, edit_lines, submit, execute, cancel
--   EXECUTIVE (roles 14, 16): preview, review_start, return, reject, approve, escalate, review_comments
--   ADMIN (role 13): all permissions

DO $$
DECLARE
    v_preview       INTEGER;
    v_create_draft  INTEGER;
    v_edit_lines    INTEGER;
    v_submit        INTEGER;
    v_review_start  INTEGER;
    v_return        INTEGER;
    v_reject        INTEGER;
    v_approve       INTEGER;
    v_escalate      INTEGER;
    v_execute       INTEGER;
    v_cancel        INTEGER;
    v_review_comms  INTEGER;
BEGIN
    SELECT perm_id INTO v_preview      FROM public.permission WHERE resource='replenishment.needs_list' AND action='preview';
    SELECT perm_id INTO v_create_draft FROM public.permission WHERE resource='replenishment.needs_list' AND action='create_draft';
    SELECT perm_id INTO v_edit_lines   FROM public.permission WHERE resource='replenishment.needs_list' AND action='edit_lines';
    SELECT perm_id INTO v_submit       FROM public.permission WHERE resource='replenishment.needs_list' AND action='submit';
    SELECT perm_id INTO v_review_start FROM public.permission WHERE resource='replenishment.needs_list' AND action='review_start';
    SELECT perm_id INTO v_return       FROM public.permission WHERE resource='replenishment.needs_list' AND action='return';
    SELECT perm_id INTO v_reject       FROM public.permission WHERE resource='replenishment.needs_list' AND action='reject';
    SELECT perm_id INTO v_approve      FROM public.permission WHERE resource='replenishment.needs_list' AND action='approve';
    SELECT perm_id INTO v_escalate     FROM public.permission WHERE resource='replenishment.needs_list' AND action='escalate';
    SELECT perm_id INTO v_execute      FROM public.permission WHERE resource='replenishment.needs_list' AND action='execute';
    SELECT perm_id INTO v_cancel       FROM public.permission WHERE resource='replenishment.needs_list' AND action='cancel';
    SELECT perm_id INTO v_review_comms FROM public.permission WHERE resource='replenishment.needs_list' AND action='review_comments';

    IF v_preview IS NULL THEN
        RAISE NOTICE 'Permissions not found — skipping role-permission mappings';
        RETURN;
    END IF;

    -- LOGISTICS_MANAGER (role 17): preview, create_draft, edit_lines, submit, execute, cancel
    INSERT INTO public.role_permission (role_id, perm_id) VALUES
        (17, v_preview), (17, v_create_draft), (17, v_edit_lines),
        (17, v_submit), (17, v_execute), (17, v_cancel)
    ON CONFLICT (role_id, perm_id) DO NOTHING;

    -- LOGISTICS_OFFICER (role 18): preview, create_draft, edit_lines
    INSERT INTO public.role_permission (role_id, perm_id) VALUES
        (18, v_preview), (18, v_create_draft), (18, v_edit_lines)
    ON CONFLICT (role_id, perm_id) DO NOTHING;

    -- ODPEM_DG (role 14): all review/approval permissions
    INSERT INTO public.role_permission (role_id, perm_id) VALUES
        (14, v_preview), (14, v_review_start), (14, v_return), (14, v_reject),
        (14, v_approve), (14, v_escalate), (14, v_review_comms)
    ON CONFLICT (role_id, perm_id) DO NOTHING;

    -- ODPEM_DIR_PEOD (role 16): review/approval (Senior Director level)
    INSERT INTO public.role_permission (role_id, perm_id) VALUES
        (16, v_preview), (16, v_review_start), (16, v_return), (16, v_reject),
        (16, v_approve), (16, v_escalate), (16, v_review_comms)
    ON CONFLICT (role_id, perm_id) DO NOTHING;

    -- ODPEM_DDG (role 15): review/approval
    INSERT INTO public.role_permission (role_id, perm_id) VALUES
        (15, v_preview), (15, v_review_start), (15, v_return), (15, v_reject),
        (15, v_approve), (15, v_escalate), (15, v_review_comms)
    ON CONFLICT (role_id, perm_id) DO NOTHING;

    -- SYSTEM_ADMINISTRATOR (role 13): all permissions
    INSERT INTO public.role_permission (role_id, perm_id) VALUES
        (13, v_preview), (13, v_create_draft), (13, v_edit_lines), (13, v_submit),
        (13, v_review_start), (13, v_return), (13, v_reject), (13, v_approve),
        (13, v_escalate), (13, v_execute), (13, v_cancel), (13, v_review_comms)
    ON CONFLICT (role_id, perm_id) DO NOTHING;

    -- INVENTORY_CLERK (role 19): preview only
    INSERT INTO public.role_permission (role_id, perm_id) VALUES
        (19, v_preview)
    ON CONFLICT (role_id, perm_id) DO NOTHING;

    RAISE NOTICE 'Role-permission mappings created for roles 13-19';
END $$;

-- ============================================================================
-- SECTION 5: TEST USERS (Five EP-02 Personas)
-- ============================================================================
-- user table NOT NULL columns: user_id, email, password_hash, user_name,
--   status_code, timezone, language, password_algo, mfa_enabled,
--   failed_login_count, login_count, version_nbr
--
-- PERSONAS:
--   9001 Kemar   – Logistics Manager (field-first, creates/submits needs lists)
--   9002 Andrea  – Senior Director PEOD (reviews/approves needs lists)
--   9003 Marcus  – Director General (higher-tier approvals)
--   9004 Sarah   – Dashboard Analyst (read-only access)
--   9005 Devon   – Field Worker (mobile, limited access)

DO $$
BEGIN
    INSERT INTO public."user" (
        user_id, email, password_hash, user_name, username,
        first_name, last_name, full_name, organization, job_title,
        status_code, assigned_warehouse_id,
        create_dtime, update_dtime
    ) VALUES
        (9001, 'kemar.brown@odpem.gov.jm',     'KEYCLOAK_MANAGED', 'KEMAR',   'kemar_logistics',
         'Kemar',  'Brown',    'Kemar Brown',    'ODPEM', 'Logistics Manager',
         'A', 1, NOW(), NOW()),
        (9002, 'andrea.campbell@odpem.gov.jm',  'KEYCLOAK_MANAGED', 'ANDREA',  'andrea_executive',
         'Andrea', 'Campbell', 'Andrea Campbell', 'ODPEM', 'Senior Director PEOD',
         'A', NULL, NOW(), NOW()),
        (9003, 'marcus.reid@odpem.gov.jm',      'KEYCLOAK_MANAGED', 'MARCUS',  'marcus_dg',
         'Marcus', 'Reid',     'Marcus Reid',     'ODPEM', 'Director General',
         'A', NULL, NOW(), NOW()),
        (9004, 'sarah.johnson@odpem.gov.jm',    'KEYCLOAK_MANAGED', 'SARAH',   'sarah_readonly',
         'Sarah',  'Johnson',  'Sarah Johnson',   'ODPEM', 'Dashboard Analyst',
         'A', NULL, NOW(), NOW()),
        (9005, 'devon.scott@odpem.gov.jm',      'KEYCLOAK_MANAGED', 'DEVON',   'devon_field',
         'Devon',  'Scott',    'Devon Scott',      'ODPEM', 'Field Worker',
         'A', 2, NOW(), NOW());
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'Test user insert error (may already exist): %', SQLERRM;
END $$;

-- ============================================================================
-- SECTION 6: USER → ROLE MAPPINGS
-- ============================================================================
-- Map test users to existing roles (13-22)

INSERT INTO public.user_role (user_id, role_id) VALUES
    (9001, 17),   -- Kemar  → LOGISTICS_MANAGER
    (9002, 16),   -- Andrea → ODPEM_DIR_PEOD (Senior Director)
    (9003, 14),   -- Marcus → ODPEM_DG (Director General)
    (9004, 19),   -- Sarah  → INVENTORY_CLERK (read-only equivalent)
    (9005, 18)    -- Devon  → LOGISTICS_OFFICER (field worker)
ON CONFLICT (user_id, role_id) DO NOTHING;

-- ============================================================================
-- SECTION 7: TEST AGENCY (required FK for relief packages)
-- ============================================================================
-- agency constraints: agency_name UPPERCASE, contact_name UPPERCASE,
-- agency_type IN ('DISTRIBUTOR','SHELTER'),
-- DISTRIBUTOR requires warehouse_id NOT NULL, SHELTER requires warehouse_id NULL

DO $$
BEGIN
    INSERT INTO public.agency (
        agency_id, agency_name, address1_text, parish_code,
        contact_name, phone_no, email_text,
        agency_type, warehouse_id, status_code,
        create_by_id, create_dtime, update_by_id, update_dtime, version_nbr
    ) VALUES (
        9001, 'ODPEM LOGISTICS TEST AGENCY', '2-4 HAINING ROAD', '01',
        'KEMAR BROWN', '876-555-0101', 'logistics@odpem.gov.jm',
        'DISTRIBUTOR', 1, 'A',
        'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW(), 1
    );
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'Agency 9001 insert skipped: %', SQLERRM;
END $$;

-- ============================================================================
-- SECTION 8: INVENTORY RECORDS (ensure exist for 15 test items × 3 warehouses)
-- ============================================================================
-- inventory PK: (inventory_id, item_id)
-- inventory_id = warehouse_id in the legacy DMIS 1:1 mapping

INSERT INTO public.inventory (
    inventory_id, item_id, usable_qty, reserved_qty, defective_qty, expired_qty,
    uom_code, status_code, reorder_qty,
    create_by_id, create_dtime, update_by_id, update_dtime, version_nbr
)
SELECT wh.id, itm.id, 0, 0, 0, 0, 'EA', 'A', 10,
       'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW(), 1
FROM (VALUES (1),(2),(3)) AS wh(id),
     (VALUES (1),(2),(7),(9),(16),(17),(19),(21),(58),(62),(85),(86),(89),(192),(195)) AS itm(id)
ON CONFLICT (inventory_id, item_id) DO NOTHING;

-- ============================================================================
-- SECTION 9: ITEM BATCHES (Test Stock Quantities)
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
    (9001, 1,   1, 'TST-K-001', 5000.0, 0, 0, 0, 'EA', 50.00,  'A', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9002, 1,   2, 'TST-K-002', 1000.0, 0, 0, 0, 'EA', 200.00, 'A', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9003, 1,   7, 'TST-K-007', 3000.0, 0, 0, 0, 'EA', 150.00, 'A', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9004, 1,   9, 'TST-K-009', 2000.0, 0, 0, 0, 'EA', 300.00, 'A', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9005, 1,  16, 'TST-K-016',  800.0, 0, 0, 0, 'EA', 25.00,  'A', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9006, 1,  17, 'TST-K-017',  500.0, 0, 0, 0, 'EA', 10.00,  'A', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9007, 1,  19, 'TST-K-019',  400.0, 0, 0, 0, 'EA', 8.00,   'A', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9008, 1,  21, 'TST-K-021',  300.0, 0, 0, 0, 'EA', 15.00,  'A', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9009, 1,  58, 'TST-K-058', 1000.0, 0, 0, 0, 'EA', 5.00,   'A', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9010, 1,  62, 'TST-K-062',   15.0, 0, 0, 0, 'EA', 45000.00,'A', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9011, 1,  85, 'TST-K-085',   20.0, 0, 0, 0, 'EA', 85000.00,'A', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9012, 1,  86, 'TST-K-086',  200.0, 0, 0, 0, 'EA', 30.00,  'A', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9013, 1,  89, 'TST-K-089',  150.0, 0, 0, 0, 'EA', 50.00,  'A', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9014, 1, 192, 'TST-K-192',  500.0, 0, 0, 0, 'EA', 1200.00,'A', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9015, 1, 195, 'TST-K-195',  300.0, 0, 0, 0, 'EA', 1500.00,'A', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),

    -- ===================== MARCUS GARVEY (WH2, inventory_id=2) =====================
    -- Low stock with high burn rates → CRITICAL / WARNING
    (9016, 2,   1, 'TST-M-001',  200.0, 0, 0, 0, 'EA', 50.00,  'A', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9017, 2,   2, 'TST-M-002',   50.0, 0, 0, 0, 'EA', 200.00, 'A', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9018, 2,   7, 'TST-M-007',  100.0, 0, 0, 0, 'EA', 150.00, 'A', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9019, 2,   9, 'TST-M-009',  100.0, 0, 0, 0, 'EA', 300.00, 'A', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9020, 2,  16, 'TST-M-016',   30.0, 0, 0, 0, 'EA', 25.00,  'A', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9021, 2,  17, 'TST-M-017',   80.0, 0, 0, 0, 'EA', 10.00,  'A', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9022, 2,  19, 'TST-M-019',   60.0, 0, 0, 0, 'EA', 8.00,   'A', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9023, 2,  21, 'TST-M-021',   40.0, 0, 0, 0, 'EA', 15.00,  'A', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9024, 2,  58, 'TST-M-058',  100.0, 0, 0, 0, 'EA', 5.00,   'A', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9025, 2,  62, 'TST-M-062',    3.0, 0, 0, 0, 'EA', 45000.00,'A', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9026, 2,  85, 'TST-M-085',    5.0, 0, 0, 0, 'EA', 85000.00,'A', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9027, 2,  86, 'TST-M-086',   50.0, 0, 0, 0, 'EA', 30.00,  'A', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9028, 2,  89, 'TST-M-089',   30.0, 0, 0, 0, 'EA', 50.00,  'A', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9029, 2, 192, 'TST-M-192',   20.0, 0, 0, 0, 'EA', 1200.00,'A', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9030, 2, 195, 'TST-M-195',   15.0, 0, 0, 0, 'EA', 1500.00,'A', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),

    -- ===================== MONTEGO BAY (WH3, inventory_id=3) =====================
    -- Moderate stock → WATCH / OK
    (9031, 3,   1, 'TST-B-001', 1500.0, 0, 0, 0, 'EA', 50.00,  'A', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9032, 3,   2, 'TST-B-002',  300.0, 0, 0, 0, 'EA', 200.00, 'A', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9033, 3,   7, 'TST-B-007',  500.0, 0, 0, 0, 'EA', 150.00, 'A', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9034, 3,   9, 'TST-B-009',  400.0, 0, 0, 0, 'EA', 300.00, 'A', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9035, 3,  16, 'TST-B-016',  200.0, 0, 0, 0, 'EA', 25.00,  'A', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9036, 3,  17, 'TST-B-017',  150.0, 0, 0, 0, 'EA', 10.00,  'A', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9037, 3,  19, 'TST-B-019',  100.0, 0, 0, 0, 'EA', 8.00,   'A', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9038, 3,  21, 'TST-B-021',  200.0, 0, 0, 0, 'EA', 15.00,  'A', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9039, 3,  58, 'TST-B-058',  500.0, 0, 0, 0, 'EA', 5.00,   'A', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9040, 3,  62, 'TST-B-062',    8.0, 0, 0, 0, 'EA', 45000.00,'A', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9041, 3,  85, 'TST-B-085',   10.0, 0, 0, 0, 'EA', 85000.00,'A', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9042, 3,  86, 'TST-B-086',  100.0, 0, 0, 0, 'EA', 30.00,  'A', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9043, 3,  89, 'TST-B-089',   60.0, 0, 0, 0, 'EA', 50.00,  'A', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9044, 3, 192, 'TST-B-192',  300.0, 0, 0, 0, 'EA', 1200.00,'A', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9045, 3, 195, 'TST-B-195',  200.0, 0, 0, 0, 'EA', 1500.00,'A', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW())
ON CONFLICT (batch_id) DO NOTHING;

-- ============================================================================
-- SECTION 10: RELIEF REQUESTS (Burn Rate Source Data - prerequisite for packages)
-- ============================================================================
-- reliefrqst: status_code SMALLINT, urgency_ind IN ('L','M','H','C')
-- status_code = 0 is simplest (no review/action fields required)

INSERT INTO public.reliefrqst (
    reliefrqst_id, agency_id, request_date, urgency_ind, status_code,
    eligible_event_id, rqst_notes_text,
    create_by_id, create_dtime, version_nbr
) VALUES
    (9001, 9001, CURRENT_DATE, 'H', 0, 8, 'Test relief request for Marcus Garvey warehouse — high urgency',
     'TEST_SCRIPT', NOW(), 1),
    (9002, 9001, CURRENT_DATE, 'M', 0, 8, 'Test relief request for Montego Bay warehouse — moderate urgency',
     'TEST_SCRIPT', NOW(), 1),
    (9003, 9001, CURRENT_DATE, 'L', 0, 8, 'Test relief request for Kingston warehouse — routine resupply',
     'TEST_SCRIPT', NOW(), 1)
ON CONFLICT DO NOTHING;

-- ============================================================================
-- SECTION 11: RELIEF PACKAGES (Burn Rate Source — Dispatched Packages)
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
    (9001, 2, 9001, CURRENT_DATE, NOW() - INTERVAL '66 hours', 'D', 9001, 'TS00001', 8, 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW(), 1),
    (9002, 2, 9001, CURRENT_DATE, NOW() - INTERVAL '54 hours', 'D', 9001, 'TS00002', 8, 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW(), 1),
    (9003, 2, 9001, CURRENT_DATE, NOW() - INTERVAL '42 hours', 'D', 9001, 'TS00003', 8, 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW(), 1),
    (9004, 2, 9001, CURRENT_DATE, NOW() - INTERVAL '30 hours', 'D', 9001, 'TS00004', 8, 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW(), 1),
    (9005, 2, 9001, CURRENT_DATE, NOW() - INTERVAL '18 hours', 'D', 9001, 'TS00005', 8, 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW(), 1),
    (9006, 2, 9001, CURRENT_DATE, NOW() - INTERVAL '4 hours',  'D', 9001, 'TS00006', 8, 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW(), 1),
    -- TO MONTEGO BAY (WH3) — 3 packages, moderate demand
    (9011, 3, 9002, CURRENT_DATE, NOW() - INTERVAL '60 hours', 'D', 9001, 'TS00011', 8, 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW(), 1),
    (9012, 3, 9002, CURRENT_DATE, NOW() - INTERVAL '36 hours', 'D', 9001, 'TS00012', 8, 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW(), 1),
    (9013, 3, 9002, CURRENT_DATE, NOW() - INTERVAL '8 hours',  'D', 9001, 'TS00013', 8, 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW(), 1),
    -- TO KINGSTON (WH1) — 2 packages, low demand
    (9021, 1, 9003, CURRENT_DATE, NOW() - INTERVAL '48 hours', 'D', 9001, 'TS00021', 8, 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW(), 1),
    (9022, 1, 9003, CURRENT_DATE, NOW() - INTERVAL '12 hours', 'D', 9001, 'TS00022', 8, 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW(), 1)
ON CONFLICT DO NOTHING;

-- ============================================================================
-- SECTION 12: RELIEF PACKAGE ITEMS (Quantities That Produce Burn Rates)
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
    -- ===================== TO MARCUS GARVEY (Packages 9001-9006) =====================
    -- Source: Kingston (WH1, fr_inventory_id=1), using WH1 batches
    -- Per package: total/6 to achieve target burn rates over 72h

    -- Package 9001 (dispatched 66h ago)
    (9001, 1, 9001,   1, 600, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),  -- water 12pk
    (9001, 1, 9002,   2,  60, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),  -- water 5gal
    (9001, 1, 9003,   7, 180, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),  -- food pkg
    (9001, 1, 9004,   9, 180, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),  -- MRE
    (9001, 1, 9005,  16,  60, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),  -- purif tablets
    (9001, 1, 9006,  17,  24, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),  -- wipes
    (9001, 1, 9007,  19,  12, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),  -- baby wipes
    (9001, 1, 9008,  21,  12, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),  -- gloves
    (9001, 1, 9011,  85,   6, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),  -- AED
    (9001, 1, 9012,  86,  24, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),  -- tape
    (9001, 1, 9013,  89,  12, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),  -- albendazole
    (9001, 1, 9014, 192,  36, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),  -- tarp 10x12
    (9001, 1, 9015, 195,  12, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),  -- tarp 12x16

    -- Package 9002 (dispatched 54h ago)
    (9002, 1, 9001,   1, 600, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9002, 1, 9002,   2,  60, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9002, 1, 9003,   7, 180, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9002, 1, 9004,   9, 180, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9002, 1, 9005,  16,  60, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9002, 1, 9006,  17,  24, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9002, 1, 9007,  19,  12, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9002, 1, 9008,  21,  12, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9002, 1, 9011,  85,   6, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9002, 1, 9012,  86,  24, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9002, 1, 9013,  89,  12, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9002, 1, 9014, 192,  36, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9002, 1, 9015, 195,  12, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),

    -- Package 9003 (dispatched 42h ago)
    (9003, 1, 9001,   1, 600, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9003, 1, 9002,   2,  60, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9003, 1, 9003,   7, 180, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9003, 1, 9004,   9, 180, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9003, 1, 9005,  16,  60, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9003, 1, 9006,  17,  24, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9003, 1, 9007,  19,  12, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9003, 1, 9008,  21,  12, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9003, 1, 9011,  85,   6, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9003, 1, 9012,  86,  24, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9003, 1, 9013,  89,  12, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9003, 1, 9014, 192,  36, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9003, 1, 9015, 195,  12, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),

    -- Package 9004 (dispatched 30h ago)
    (9004, 1, 9001,   1, 600, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9004, 1, 9002,   2,  60, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9004, 1, 9003,   7, 180, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9004, 1, 9004,   9, 180, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9004, 1, 9005,  16,  60, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9004, 1, 9006,  17,  24, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9004, 1, 9007,  19,  12, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9004, 1, 9008,  21,  12, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9004, 1, 9011,  85,   6, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9004, 1, 9012,  86,  24, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9004, 1, 9013,  89,  12, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9004, 1, 9014, 192,  36, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9004, 1, 9015, 195,  12, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),

    -- Package 9005 (dispatched 18h ago)
    (9005, 1, 9001,   1, 600, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9005, 1, 9002,   2,  60, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9005, 1, 9003,   7, 180, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9005, 1, 9004,   9, 180, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9005, 1, 9005,  16,  60, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9005, 1, 9006,  17,  24, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9005, 1, 9007,  19,  12, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9005, 1, 9008,  21,  12, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9005, 1, 9011,  85,   6, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9005, 1, 9012,  86,  24, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9005, 1, 9013,  89,  12, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9005, 1, 9014, 192,  36, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9005, 1, 9015, 195,  12, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),

    -- Package 9006 (dispatched 4h ago)
    (9006, 1, 9001,   1, 600, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9006, 1, 9002,   2,  60, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9006, 1, 9003,   7, 180, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9006, 1, 9004,   9, 180, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9006, 1, 9005,  16,  60, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9006, 1, 9006,  17,  24, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9006, 1, 9007,  19,  12, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9006, 1, 9008,  21,  12, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9006, 1, 9011,  85,   6, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9006, 1, 9012,  86,  24, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9006, 1, 9013,  89,  12, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9006, 1, 9014, 192,  36, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9006, 1, 9015, 195,  12, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),

    -- ===================== TO MONTEGO BAY (Packages 9011-9013) =====================
    -- Source: Kingston (WH1), fewer items per package

    -- Package 9011
    (9011, 1, 9001,   1, 240, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9011, 1, 9003,   7, 120, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9011, 1, 9004,   9, 120, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9011, 1, 9006,  17,  24, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9011, 1, 9007,  19,  24, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9011, 1, 9011,  85,   5, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9011, 1, 9014, 192,  24, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),

    -- Package 9012
    (9012, 1, 9001,   1, 240, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9012, 1, 9003,   7, 120, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9012, 1, 9004,   9, 120, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9012, 1, 9006,  17,  24, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9012, 1, 9007,  19,  24, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9012, 1, 9011,  85,   5, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9012, 1, 9014, 192,  24, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),

    -- Package 9013
    (9013, 1, 9001,   1, 240, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9013, 1, 9003,   7, 120, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9013, 1, 9004,   9, 120, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9013, 1, 9006,  17,  24, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9013, 1, 9007,  19,  24, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9013, 1, 9011,  85,   5, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9013, 1, 9014, 192,  24, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),

    -- ===================== TO KINGSTON (Packages 9021-9022) =====================
    -- Source: Marcus Garvey (WH2), using WH2 batches

    -- Package 9021
    (9021, 2, 9016,   1, 108, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9021, 2, 9019,   9,  72, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9021, 2, 9021,  17,  18, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9021, 2, 9029, 192,  18, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),

    -- Package 9022
    (9022, 2, 9016,   1, 108, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9022, 2, 9019,   9,  72, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9022, 2, 9021,  17,  18, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
    (9022, 2, 9029, 192,  18, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW())
ON CONFLICT DO NOTHING;

-- ============================================================================
-- SECTION 13: INBOUND TRANSFERS (Horizon A — Dispatched)
-- ============================================================================
-- Only transfers with status 'D' count as strict inbound per data_access.py.
-- transfer requires: fr_inventory_id, to_inventory_id, verify_by_id (NOT NULL)

INSERT INTO public.transfer (
    transfer_id, fr_inventory_id, to_inventory_id, eligible_event_id,
    transfer_date, status_code, verify_by_id,
    dispatched_at, dispatched_by, expected_arrival,
    create_by_id, create_dtime, update_by_id, update_dtime, version_nbr
) VALUES
    -- Transfer 9001: Kingston (WH1) → Marcus Garvey (WH2) — emergency water resupply
    (9001, 1, 2, 8, CURRENT_DATE, 'D', 'SYSADMIN',
     NOW() - INTERVAL '2 hours', 'kemar_logistics', NOW() + INTERVAL '6 hours',
     'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW(), 1),
    -- Transfer 9002: Montego Bay (WH3) → Marcus Garvey (WH2) — shelter supplies
    (9002, 3, 2, 8, CURRENT_DATE, 'D', 'SYSADMIN',
     NOW() - INTERVAL '1 hour', 'kemar_logistics', NOW() + INTERVAL '8 hours',
     'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW(), 1)
ON CONFLICT DO NOTHING;

-- Transfer items (batch_id + inventory_id reference itembatch at SOURCE warehouse)
INSERT INTO public.transfer_item (
    transfer_id, item_id, batch_id, inventory_id, item_qty, uom_code,
    create_by_id, create_dtime, update_by_id, update_dtime
) VALUES
    -- Transfer 9001: Kingston → Marcus Garvey
    (9001,   1, 9001, 1, 500, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),   -- 500 water bottles
    (9001,   9, 9004, 1, 200, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),   -- 200 MREs
    (9001, 192, 9014, 1,  50, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),   -- 50 tarps
    (9001,  85, 9011, 1,   3, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),   -- 3 AED sets
    -- Transfer 9002: Montego Bay → Marcus Garvey
    (9002,   1, 9031, 3, 300, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),   -- 300 water bottles
    (9002,  19, 9037, 3,  50, 'EA', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW())    -- 50 baby wipes
ON CONFLICT DO NOTHING;

-- ============================================================================
-- SECTION 14: UPDATE EVENT WITH CURRENT PHASE
-- ============================================================================

UPDATE public.event
SET current_phase = 'STABILIZED'
WHERE event_id = 8;

-- ============================================================================
-- SECTION 15: NEEDS LISTS IN VARIOUS WORKFLOW STATES
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
    -- NL #1: DRAFT at Marcus Garvey (generated by Kemar, not yet submitted)
    INSERT INTO public.needs_list (
        needs_list_no, event_id, warehouse_id, event_phase,
        calculation_dtime, demand_window_hours, planning_window_hours, safety_factor,
        data_freshness_level, status_code, total_gap_qty, total_estimated_value,
        create_by_id, create_dtime, update_by_id, update_dtime
    ) VALUES (
        'NL-MG-2026-001', 8, 2, 'STABILIZED',
        NOW() - INTERVAL '2 hours', 72, 168, 1.25,
        'MEDIUM', 'DRAFT', 12200.00, 2500000.00,
        'kemar_logistics', NOW() - INTERVAL '2 hours', 'kemar_logistics', NOW() - INTERVAL '2 hours'
    ) RETURNING needs_list_id INTO v_nl_draft;

    -- NL #2: PENDING_APPROVAL at Kingston (submitted by Kemar)
    INSERT INTO public.needs_list (
        needs_list_no, event_id, warehouse_id, event_phase,
        calculation_dtime, demand_window_hours, planning_window_hours, safety_factor,
        data_freshness_level, status_code, total_gap_qty, total_estimated_value,
        submitted_at, submitted_by,
        create_by_id, create_dtime, update_by_id, update_dtime
    ) VALUES (
        'NL-KW-2026-001', 8, 1, 'STABILIZED',
        NOW() - INTERVAL '6 hours', 72, 168, 1.25,
        'HIGH', 'PENDING_APPROVAL', 4430.00, 900000.00,
        NOW() - INTERVAL '5 hours', 'kemar_logistics',
        'kemar_logistics', NOW() - INTERVAL '6 hours', 'kemar_logistics', NOW() - INTERVAL '5 hours'
    ) RETURNING needs_list_id INTO v_nl_submitted;

    -- NL #3: UNDER_REVIEW at Marcus Garvey (Andrea reviewing)
    INSERT INTO public.needs_list (
        needs_list_no, event_id, warehouse_id, event_phase,
        calculation_dtime, demand_window_hours, planning_window_hours, safety_factor,
        data_freshness_level, status_code, total_gap_qty,
        submitted_at, submitted_by, under_review_at, under_review_by,
        create_by_id, create_dtime, update_by_id, update_dtime
    ) VALUES (
        'NL-MG-2026-002', 8, 2, 'STABILIZED',
        NOW() - INTERVAL '12 hours', 72, 168, 1.25,
        'MEDIUM', 'UNDER_REVIEW', 15800.00,
        NOW() - INTERVAL '10 hours', 'kemar_logistics',
        NOW() - INTERVAL '8 hours', 'andrea_executive',
        'kemar_logistics', NOW() - INTERVAL '12 hours', 'andrea_executive', NOW() - INTERVAL '8 hours'
    ) RETURNING needs_list_id INTO v_nl_review;

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
        'NL-MG-2026-003', 8, 2, 'STABILIZED',
        NOW() - INTERVAL '24 hours', 72, 168, 1.25,
        'HIGH', 'APPROVED', 11900.00,
        NOW() - INTERVAL '22 hours', 'kemar_logistics',
        NOW() - INTERVAL '20 hours', 'andrea_executive',
        NOW() - INTERVAL '18 hours', 'andrea_executive',
        'Approved — critical items confirmed. Prioritize water and medical.',
        'kemar_logistics', NOW() - INTERVAL '24 hours', 'andrea_executive', NOW() - INTERVAL '18 hours'
    ) RETURNING needs_list_id INTO v_nl_approved;

    -- NL #5: REJECTED at Montego Bay (rejected by Andrea)
    INSERT INTO public.needs_list (
        needs_list_no, event_id, warehouse_id, event_phase,
        calculation_dtime, demand_window_hours, planning_window_hours, safety_factor,
        data_freshness_level, status_code, total_gap_qty,
        submitted_at, submitted_by,
        rejected_at, rejected_by, rejection_reason,
        create_by_id, create_dtime, update_by_id, update_dtime
    ) VALUES (
        'NL-MB-2026-001', 8, 3, 'STABILIZED',
        NOW() - INTERVAL '36 hours', 72, 168, 1.25,
        'LOW', 'REJECTED', 2800.00,
        NOW() - INTERVAL '34 hours', 'kemar_logistics',
        NOW() - INTERVAL '30 hours', 'andrea_executive',
        'Quantities exceed projected need for Montego Bay. Reduce and resubmit.',
        'kemar_logistics', NOW() - INTERVAL '36 hours', 'andrea_executive', NOW() - INTERVAL '30 hours'
    ) RETURNING needs_list_id INTO v_nl_rejected;

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
        'NL-MG-2026-004', 8, 2, 'STABILIZED',
        NOW() - INTERVAL '48 hours', 72, 168, 1.25,
        'HIGH', 'IN_PROGRESS', 10200.00,
        NOW() - INTERVAL '46 hours', 'kemar_logistics',
        NOW() - INTERVAL '42 hours', 'andrea_executive',
        'Emergency approval — Marcus Garvey critical. Fast-track transfers.',
        'kemar_logistics', NOW() - INTERVAL '48 hours', 'kemar_logistics', NOW() - INTERVAL '40 hours'
    ) RETURNING needs_list_id INTO v_nl_executing;

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
        (v_nl_draft, 1,   'EA', 50.0, 'CALCULATED', 200, 0, 0, 0, 0, 9000, 200, 8800, 4.0,   'CRITICAL', 8800, 0, 0, 0, 'PENDING', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
        (v_nl_draft, 9,   'EA', 15.0, 'CALCULATED', 100, 0, 0, 0, 0, 2700, 100, 2600, 6.7,   'CRITICAL', 2600, 0, 0, 0, 'PENDING', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
        (v_nl_draft, 85,  'EA', 0.5,  'CALCULATED',   5, 0, 0, 0, 0,   90,   5,   85, 10.0,  'WARNING',    85, 0, 0, 0, 'PENDING', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
        (v_nl_draft, 192, 'EA', 3.0,  'CALCULATED',  20, 0, 0, 0, 0,  648,  20,  628, 6.7,   'CRITICAL',  628, 0, 0, 0, 'PENDING', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
        (v_nl_draft, 86,  'EA', 2.0,  'BASELINE',    50, 0, 0, 0, 0,  420,  50,  370, 25.0,  'WATCH',       0, 370, 0, 0, 'PENDING', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW());

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
        (v_nl_submitted, 85,  'EA', 0.1, 'BASELINE',   20, 0, 0, 0, 0,  21,  20, 1, 200.0,  'OK',    0, 0, 1, 0, 'PENDING', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
        (v_nl_submitted, 17,  'EA', 0.5, 'CALCULATED', 500, 0, 0, 0, 0, 630, 500, 130, 1000.0,'OK',    0, 130, 0, 0, 'PENDING', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
        (v_nl_submitted, 9,   'EA', 2.0, 'CALCULATED', 2000,0, 0, 0, 0, 5250,2000,3250, 1000.0,'OK', 0, 0, 3250, 0, 'PENDING', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW());

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
        (v_nl_review, 1,   'EA', 50.0, 'CALCULATED', 200, 0, 500, 0, 0, 9000, 700, 8300, 4.0,  'CRITICAL', 8300, 1, 0, 0, 0, 'PENDING', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
        (v_nl_review, 16,  'EA', 5.0,  'CALCULATED',  30, 0, 0,   0, 0,  900,  30,  870, 6.0,  'CRITICAL',  870, NULL, 0, 0, 0, 'PENDING', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
        (v_nl_review, 85,  'EA', 0.5,  'CALCULATED',   5, 0, 3,   0, 0,   90,   8,   82, 10.0, 'WARNING',    82, 1, 0, 0, 0, 'PENDING', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
        (v_nl_review, 192, 'EA', 3.0,  'CALCULATED',  20, 0, 50,  0, 0,  648,  70,  578, 6.7,  'CRITICAL',  578, 1, 0, 0, 0, 'PENDING', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
        (v_nl_review, 9,   'EA', 15.0, 'CALCULATED', 100, 0, 200, 0, 0, 2700, 300, 2400, 6.7,  'CRITICAL', 2400, 1, 0, 0, 0, 'PENDING', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
        (v_nl_review, 86,  'EA', 2.0,  'BASELINE',    50, 0, 0,   0, 0,  420,  50,  370, 25.0, 'WATCH',       0, NULL, 370, 0, 0, 'PENDING', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW());

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
        (v_nl_approved, 1,   'EA', 50.0, 'CALCULATED', 200, 0, 500, 0, 0, 9000, 700, 8300, 4.0, 'CRITICAL', 8000, 1, 0, 300, 8000, 'PARTIAL_COVERAGE', 'andrea_executive', NOW() - INTERVAL '20 hours', 0, 'PENDING', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
        (v_nl_approved, 9,   'EA', 15.0, 'CALCULATED', 100, 0, 200, 0, 0, 2700, 300, 2400, 6.7, 'CRITICAL', 2400, 1, 0, 0, NULL, NULL, NULL, NULL, 0, 'PENDING', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
        (v_nl_approved, 192, 'EA', 3.0,  'CALCULATED',  20, 0, 50,  0, 0,  648,  70,  578, 6.7, 'CRITICAL',  578, 1, 0, 0, NULL, NULL, NULL, NULL, 0, 'PENDING', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
        (v_nl_approved, 85,  'EA', 0.5,  'CALCULATED',   5, 0, 3,   0, 0,   90,   8,   82, 10.0,'WARNING',    82, 1, 0, 0, NULL, NULL, NULL, NULL, 0, 'PENDING', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW());

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
        (v_nl_rejected, 1,   'EA', 10.0, 'CALCULATED', 1500, 0, 0, 0, 0, 2100, 1500, 600, 150.0, 'OK', 0, 600, 0, 0, 'CANCELLED', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
        (v_nl_rejected, 9,   'EA', 5.0,  'CALCULATED',  400, 0, 0, 0, 0, 1050,  400, 650, 80.0,  'OK', 0, 650, 0, 0, 'CANCELLED', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
        (v_nl_rejected, 17,  'EA', 1.0,  'CALCULATED',  150, 0, 0, 0, 0,  210,  150,  60, 150.0, 'OK', 0, 60,  0, 0, 'CANCELLED', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW());

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
        (v_nl_executing, 1,   'EA', 50.0, 'CALCULATED', 200, 0, 500, 0, 0, 8000, 700, 7300, 4.0,  'CRITICAL', 7300, 1, 0, 0, 3000, 'PARTIAL',   'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
        (v_nl_executing, 85,  'EA', 0.5,  'CALCULATED',   5, 0, 3,   0, 0,   90,   8,   82, 10.0, 'WARNING',    82, 1, 0, 0,   82, 'FULFILLED', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
        (v_nl_executing, 192, 'EA', 3.0,  'CALCULATED',  20, 0, 50,  0, 0,  600,  70,  530, 6.7,  'CRITICAL',  530, 1, 0, 0,  200, 'PARTIAL',   'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW()),
        (v_nl_executing, 9,   'EA', 15.0, 'CALCULATED', 100, 0, 200, 0, 0, 2500, 300, 2200, 6.7,  'CRITICAL',    0, NULL, 0, 2200,   0, 'PENDING',   'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW());

    -- ===================== AUDIT TRAIL =====================
    -- needs_list_audit: NO create_by_id column. Uses actor_user_id (varchar 20).

    INSERT INTO public.needs_list_audit (
        needs_list_id, action_type, field_name, old_value, new_value,
        reason_code, notes_text, actor_user_id, action_dtime
    ) VALUES
        -- NL#2: Created → Submitted
        (v_nl_submitted, 'CREATED',   'status_code', NULL,    'DRAFT',            'SYSTEM', 'Needs list generated from stock status dashboard', 'kemar_logistics', NOW() - INTERVAL '6 hours'),
        (v_nl_submitted, 'SUBMITTED', 'status_code', 'DRAFT', 'PENDING_APPROVAL', 'USER',   'Submitted for approval — Kingston items for review', 'kemar_logistics', NOW() - INTERVAL '5 hours'),
        -- NL#3: Created → Submitted → Under Review
        (v_nl_review,    'CREATED',        'status_code', NULL,               'DRAFT',              'SYSTEM', 'Needs list generated', 'kemar_logistics',   NOW() - INTERVAL '12 hours'),
        (v_nl_review,    'SUBMITTED',      'status_code', 'DRAFT',            'PENDING_APPROVAL',   'USER',   'Submitted',            'kemar_logistics',   NOW() - INTERVAL '10 hours'),
        (v_nl_review,    'STATUS_CHANGED', 'status_code', 'PENDING_APPROVAL', 'UNDER_REVIEW',       'USER',   'Andrea started review', 'andrea_executive', NOW() - INTERVAL '8 hours'),
        -- NL#4: Full lifecycle → Approved
        (v_nl_approved,  'CREATED',   'status_code', NULL,               'DRAFT',            'SYSTEM', 'Needs list generated',                  'kemar_logistics',   NOW() - INTERVAL '24 hours'),
        (v_nl_approved,  'SUBMITTED', 'status_code', 'DRAFT',            'PENDING_APPROVAL', 'USER',   'Submitted — urgent Marcus Garvey needs','kemar_logistics',   NOW() - INTERVAL '22 hours'),
        (v_nl_approved,  'APPROVED',  'status_code', 'PENDING_APPROVAL', 'APPROVED',         'USER',   'Approved — critical items confirmed',   'andrea_executive',  NOW() - INTERVAL '18 hours'),
        (v_nl_approved,  'QUANTITY_ADJUSTED', 'adjusted_qty', '9000', '8000', 'PARTIAL_COVERAGE', 'Water adjusted per transfer capacity', 'andrea_executive', NOW() - INTERVAL '20 hours'),
        -- NL#5: Rejected
        (v_nl_rejected,  'CREATED',   'status_code', NULL,               'DRAFT',            'SYSTEM', 'Needs list generated', 'kemar_logistics', NOW() - INTERVAL '36 hours'),
        (v_nl_rejected,  'SUBMITTED', 'status_code', 'DRAFT',            'PENDING_APPROVAL', 'USER',   'Submitted — Montego Bay resupply', 'kemar_logistics', NOW() - INTERVAL '34 hours'),
        (v_nl_rejected,  'REJECTED',  'status_code', 'PENDING_APPROVAL', 'REJECTED',         'USER',   'Quantities exceed projected need',  'andrea_executive', NOW() - INTERVAL '30 hours'),
        -- NL#6: Full lifecycle → In Progress
        (v_nl_executing, 'CREATED',        'status_code', NULL,               'DRAFT',            'SYSTEM', 'Emergency needs list',   'kemar_logistics',  NOW() - INTERVAL '48 hours'),
        (v_nl_executing, 'SUBMITTED',      'status_code', 'DRAFT',            'PENDING_APPROVAL', 'USER',   'Emergency submission',   'kemar_logistics',  NOW() - INTERVAL '46 hours'),
        (v_nl_executing, 'APPROVED',       'status_code', 'PENDING_APPROVAL', 'APPROVED',         'USER',   'Emergency approval',     'andrea_executive', NOW() - INTERVAL '42 hours'),
        (v_nl_executing, 'STATUS_CHANGED', 'status_code', 'APPROVED',         'IN_PROGRESS',      'USER',   'Preparation started',    'kemar_logistics',  NOW() - INTERVAL '40 hours');

    RAISE NOTICE 'Needs lists created: draft=%, submitted=%, review=%, approved=%, rejected=%, executing=%',
        v_nl_draft, v_nl_submitted, v_nl_review, v_nl_approved, v_nl_rejected, v_nl_executing;
END $$;

-- ============================================================================
-- SECTION 16: BURN RATE SNAPSHOTS (Historical Trending Data)
-- ============================================================================
-- 12 snapshots over 72 hours (every 6 hours) for Marcus Garvey (most active)

DO $$
DECLARE
    v_snap_time TIMESTAMP;
    v_i INTEGER;
BEGIN
    FOR v_i IN 0..11 LOOP
        v_snap_time := NOW() - (v_i * INTERVAL '6 hours');

        INSERT INTO public.burn_rate_snapshot (
            warehouse_id, item_id, event_id, event_phase, snapshot_dtime,
            demand_window_hours, fulfillment_count, total_fulfilled_qty,
            burn_rate, burn_rate_source, data_freshness_level,
            time_to_stockout_hours, available_stock_at_calc
        ) VALUES
            -- Water at Marcus Garvey — burn rate trending UP (worsening)
            (2, 1, 8, 'STABILIZED', v_snap_time, 72,
             6, 3600 + (v_i * 50),
             50.0 + (v_i * 0.7),
             'CALCULATED', 'MEDIUM',
             GREATEST(1.0, 4.0 - (v_i * 0.3)),
             GREATEST(50, 200 + (v_i * 100))),
            -- MRE at Marcus Garvey — burn rate STABLE
            (2, 9, 8, 'STABILIZED', v_snap_time, 72,
             6, 1080,
             15.0,
             'CALCULATED', 'MEDIUM',
             GREATEST(2.0, 6.7 + (v_i * 0.5)),
             GREATEST(50, 100 + (v_i * 50)));
    END LOOP;
END $$;

-- ============================================================================
-- SECTION 17: WAREHOUSE SYNC LOGS (Data Freshness History)
-- ============================================================================

DO $$
DECLARE
    v_i INTEGER;
BEGIN
    -- Kingston: regular syncs (every 30 min, all successful)
    FOR v_i IN 0..5 LOOP
        INSERT INTO public.warehouse_sync_log (
            warehouse_id, sync_dtime, sync_type, sync_status,
            items_synced, triggered_by
        ) VALUES (
            1, NOW() - (v_i * INTERVAL '30 minutes'), 'SCHEDULED', 'SUCCESS',
            15, 'SYSTEM'
        );
    END LOOP;

    -- Marcus Garvey: sporadic syncs (connectivity issues in field)
    INSERT INTO public.warehouse_sync_log (warehouse_id, sync_dtime, sync_type, sync_status, items_synced, error_message, triggered_by) VALUES
        (2, NOW() - INTERVAL '5 hours',  'MANUAL',    'SUCCESS', 15, NULL, 'kemar_logistics'),
        (2, NOW() - INTERVAL '8 hours',  'SCHEDULED', 'FAILED',  0,  'Connection timeout — cellular network down', 'SYSTEM'),
        (2, NOW() - INTERVAL '12 hours', 'MANUAL',    'PARTIAL', 10, 'Partial sync — 5 items failed checksum', 'devon_field'),
        (2, NOW() - INTERVAL '18 hours', 'SCHEDULED', 'SUCCESS', 15, NULL, 'SYSTEM');

    -- Montego Bay: infrequent syncs (low priority area)
    INSERT INTO public.warehouse_sync_log (warehouse_id, sync_dtime, sync_type, sync_status, items_synced, error_message, triggered_by) VALUES
        (3, NOW() - INTERVAL '14 hours', 'SCHEDULED', 'SUCCESS', 15, NULL, 'SYSTEM'),
        (3, NOW() - INTERVAL '20 hours', 'SCHEDULED', 'FAILED',  0,  'Database connection pool exhausted', 'SYSTEM');
END $$;

-- ============================================================================
-- SECTION 18: SUPPLIER TEST DATA (Horizon C — Procurement)
-- ============================================================================

INSERT INTO public.supplier (
    supplier_code, supplier_name, contact_name, phone_no, email_text,
    address_text, parish_code, default_lead_time_days,
    is_framework_supplier, framework_contract_no, framework_expiry_date,
    status_code, create_by_id, update_by_id
) VALUES
    ('SUP-GBS', 'GRACE BIOSYSTEMS LTD',      'Michael Chen',   '876-555-0201', 'sales@gracebio.com.jm',
     '12 Marcus Garvey Dr, Kingston', '01', 7,  TRUE,  'GOJ-FW-2026-001', '2027-03-31',
     'A', 'TEST_SCRIPT', 'TEST_SCRIPT'),
    ('SUP-JAM', 'JAMAICA MEDICAL SUPPLIES',   'Donna Wright',   '876-555-0202', 'orders@jammedsup.com.jm',
     '45 Half Way Tree Rd, Kingston', '01', 5,  TRUE,  'GOJ-FW-2026-002', '2027-06-30',
     'A', 'TEST_SCRIPT', 'TEST_SCRIPT'),
    ('SUP-CAR', 'CARIBBEAN PROVISIONS CO',    'Andre Thompson', '876-555-0203', 'supply@caribprov.com',
     '8 Port Royal St, Kingston',     '01', 14, FALSE, NULL, NULL,
     'A', 'TEST_SCRIPT', 'TEST_SCRIPT'),
    ('SUP-INT', 'INTERNATIONAL RELIEF SUPPLY','Sarah Palmer',   '1-305-555-0300','orders@intrelief.org',
     '100 NW 12th Ave, Miami FL',     NULL, 21, FALSE, NULL, NULL,
     'A', 'TEST_SCRIPT', 'TEST_SCRIPT')
ON CONFLICT DO NOTHING;

-- ============================================================================
-- SECTION 19: LEAD TIME CONFIGURATION
-- ============================================================================

INSERT INTO public.lead_time_config (
    horizon, from_warehouse_id, to_warehouse_id, lead_time_hours,
    is_default, effective_from,
    create_by_id, update_by_id
) VALUES
    -- Horizon A: Transfer lead times (specific routes)
    -- NOTE: c_ltc_a_warehouses requires from/to warehouse_id NOT NULL for horizon A
    ('A', 1, 2, 6,  FALSE, CURRENT_DATE, 'TEST_SCRIPT', 'TEST_SCRIPT'),   -- Kingston → Marcus Garvey: 6h
    ('A', 1, 3, 8,  FALSE, CURRENT_DATE, 'TEST_SCRIPT', 'TEST_SCRIPT'),   -- Kingston → Montego Bay: 8h
    ('A', 3, 2, 10, FALSE, CURRENT_DATE, 'TEST_SCRIPT', 'TEST_SCRIPT'),   -- Montego Bay → Marcus Garvey: 10h
    ('A', 2, 1, 8,  FALSE, CURRENT_DATE, 'TEST_SCRIPT', 'TEST_SCRIPT'),   -- Marcus Garvey → Kingston: 8h (reverse)
    -- Horizon B: Donation lead times
    ('B', NULL, NULL, 48, TRUE,  CURRENT_DATE, 'TEST_SCRIPT', 'TEST_SCRIPT'),
    -- Horizon C: Procurement lead times
    ('C', NULL, NULL, 336,TRUE,  CURRENT_DATE, 'TEST_SCRIPT', 'TEST_SCRIPT')
ON CONFLICT DO NOTHING;

-- ============================================================================
-- SECTION 20: TENANT-USER MAPPINGS (if tenant tables exist)
-- ============================================================================

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='tenant_user') THEN
        INSERT INTO public.tenant_user (tenant_id, user_id, is_primary_tenant, access_level, assigned_by, create_by_id)
        SELECT t.tenant_id, u.user_id, TRUE,
               CASE u.user_id
                   WHEN 9001 THEN 'FULL'
                   WHEN 9002 THEN 'FULL'
                   WHEN 9003 THEN 'ADMIN'
                   WHEN 9004 THEN 'READ_ONLY'
                   WHEN 9005 THEN 'LIMITED'
               END,
               9003,
               'TEST_SCRIPT'
        FROM public.tenant t, (VALUES (9001),(9002),(9003),(9004),(9005)) AS u(user_id)
        WHERE t.tenant_code = 'ODPEM-LOGISTICS'
        ON CONFLICT (tenant_id, user_id) DO NOTHING;

        RAISE NOTICE 'Tenant-user mappings created';
    ELSE
        RAISE NOTICE 'tenant_user table not found — skipping (run dmis_test_data.sql first)';
    END IF;
END $$;

-- ============================================================================
-- SECTION 21: DATA SHARING AGREEMENTS (if tenant tables exist)
-- ============================================================================

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='data_sharing_agreement') THEN
        INSERT INTO public.data_sharing_agreement (from_tenant_id, to_tenant_id, data_category, permission_level, agreement_notes, status_code, approved_by, approved_at, create_by_id, update_by_id)
        SELECT f.tenant_id, t.tenant_id, 'INVENTORY', 'READ',
            'JRC can view ODPEM inventory levels for donation coordination',
            'A', 9003, NOW() - INTERVAL '30 days', 'TEST_SCRIPT', 'TEST_SCRIPT'
        FROM public.tenant f, public.tenant t
        WHERE f.tenant_code = 'ODPEM-LOGISTICS' AND t.tenant_code = 'JRC'
        ON CONFLICT DO NOTHING;

        RAISE NOTICE 'Data sharing agreements created';
    ELSE
        RAISE NOTICE 'data_sharing_agreement table not found — skipping';
    END IF;
END $$;

-- ============================================================================
-- SECTION 22: INDEXES FOR TEST DATA PERFORMANCE
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_itembatch_test_wh ON public.itembatch(inventory_id)
    WHERE inventory_id IN (1, 2, 3) AND create_by_id = 'TEST_SCRIPT';

-- ============================================================================
-- COMMIT
-- ============================================================================

COMMIT;

-- ============================================================================
-- SECTION 23: POST-EXECUTION SUMMARY & VERIFICATION
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
    SELECT COUNT(*) INTO v_user_count     FROM public."user"          WHERE user_id BETWEEN 9001 AND 9005;
    SELECT COUNT(*) INTO v_perm_count     FROM public.permission      WHERE create_by_id = 'TEST_SCRIPT';
    SELECT COUNT(*) INTO v_rp_count       FROM public.role_permission rp
                                          JOIN public.permission p ON rp.perm_id = p.perm_id
                                          WHERE p.create_by_id = 'TEST_SCRIPT';
    SELECT COUNT(*) INTO v_batch_count    FROM public.itembatch       WHERE batch_id BETWEEN 9001 AND 9045;
    SELECT COUNT(*) INTO v_pkg_count      FROM public.reliefpkg       WHERE create_by_id = 'TEST_SCRIPT';
    SELECT COUNT(*) INTO v_transfer_count FROM public.transfer        WHERE create_by_id = 'TEST_SCRIPT';
    SELECT COUNT(*) INTO v_nl_count       FROM public.needs_list      WHERE create_by_id IN ('kemar_logistics', 'TEST_SCRIPT');
    SELECT COUNT(*) INTO v_nli_count      FROM public.needs_list_item WHERE create_by_id = 'TEST_SCRIPT';
    SELECT COUNT(*) INTO v_audit_count    FROM public.needs_list_audit WHERE actor_user_id IN ('kemar_logistics', 'andrea_executive', 'TEST_SCRIPT');
    SELECT COUNT(*) INTO v_snapshot_count FROM public.burn_rate_snapshot WHERE warehouse_id = 2 AND event_id = 8;

    RAISE NOTICE '============================================================';
    RAISE NOTICE 'DMIS OPERATIONAL TEST DATA CREATION COMPLETE';
    RAISE NOTICE '============================================================';
    RAISE NOTICE '';
    RAISE NOTICE 'RBAC FIXTURES:';
    RAISE NOTICE '  Test users:         % (kemar, andrea, marcus, sarah, devon)', v_user_count;
    RAISE NOTICE '  Permissions:        % (12 replenishment permissions)', v_perm_count;
    RAISE NOTICE '  Role-perm mappings: % (roles 13-19 mapped)', v_rp_count;
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
    RAISE NOTICE '  kemar_logistics  (9001): LOGISTICS_MANAGER — create, edit, submit, execute, cancel';
    RAISE NOTICE '  andrea_executive (9002): ODPEM_DIR_PEOD   — review, approve, reject, return, escalate';
    RAISE NOTICE '  marcus_dg        (9003): ODPEM_DG         — higher-tier approvals';
    RAISE NOTICE '  sarah_readonly   (9004): INVENTORY_CLERK  — preview/dashboard only';
    RAISE NOTICE '  devon_field      (9005): LOGISTICS_OFFICER— preview, create draft from field';
    RAISE NOTICE '';
    RAISE NOTICE 'To purge: psql -d dmis -f dmis_operational_test_data_purge.sql';
    RAISE NOTICE '============================================================';
END $$;
