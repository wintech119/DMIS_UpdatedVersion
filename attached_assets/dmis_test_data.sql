-- ============================================================================
-- DMIS Test Data Script: Multi-Tenancy Foundation + Supply Replenishment (EP-02)
-- ============================================================================
-- Version: 2.0
-- Date: 2026-02-13
-- Purpose: Creates multi-tenancy schema with graceful custodian migration
--          and comprehensive test data for EP-02 Supply Replenishment testing
-- 
-- MIGRATION STRATEGY:
--   - tenant table becomes the canonical organizational registry
--   - custodian table gains tenant_id FK for graceful migration
--   - warehouse gains optional tenant_id for direct lookup (custodian_id remains)
--   - All existing custodian dependencies continue to work unchanged
--
-- USAGE:
--   psql -d dmis -f dmis_test_data.sql
--
-- ROLLBACK:
--   psql -d dmis -f dmis_test_data_purge.sql
-- ============================================================================

-- Begin transaction for atomic execution
BEGIN;

-- ============================================================================
-- SECTION 1: TENANT TABLE (Canonical Organization Registry)
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.tenant (
    tenant_id SERIAL PRIMARY KEY,
    tenant_code VARCHAR(20) NOT NULL,
    tenant_name VARCHAR(120) NOT NULL,
    tenant_type VARCHAR(20) NOT NULL CHECK (tenant_type IN (
        'NATIONAL', 'MILITARY', 'PARISH', 'MINISTRY', 'EXTERNAL', 'INFRASTRUCTURE', 'PUBLIC'
    )),
    parent_tenant_id INTEGER REFERENCES public.tenant(tenant_id),
    -- Contact/Address (mirrors custodian for migration)
    address1_text VARCHAR(255),
    address2_text VARCHAR(255),
    parish_code CHAR(2) REFERENCES public.parish(parish_code),
    contact_name VARCHAR(50),
    phone_no VARCHAR(20),
    email_text VARCHAR(100),
    -- Multi-tenancy attributes (from Stakeholder Analysis v1.6)
    data_scope VARCHAR(50) DEFAULT 'OWN_DATA' CHECK (data_scope IN (
        'OWN_DATA', 'PARISH_DATA', 'REGIONAL_DATA', 'NATIONAL_DATA'
    )),
    pii_access VARCHAR(20) DEFAULT 'NONE' CHECK (pii_access IN (
        'NONE', 'AGGREGATED', 'LIMITED', 'MASKED', 'FULL'
    )),
    offline_required BOOLEAN DEFAULT FALSE,
    mobile_priority VARCHAR(10) DEFAULT 'LOW' CHECK (mobile_priority IN (
        'CRITICAL', 'HIGH', 'MEDIUM', 'LOW'
    )),
    -- Status and audit
    status_code CHAR(1) NOT NULL DEFAULT 'A' CHECK (status_code IN ('A', 'I')),
    create_by_id VARCHAR(20) NOT NULL DEFAULT 'SYSTEM',
    create_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_by_id VARCHAR(20) NOT NULL DEFAULT 'SYSTEM',
    update_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    version_nbr INTEGER NOT NULL DEFAULT 1,
    CONSTRAINT tenant_code_upper CHECK (tenant_code = UPPER(tenant_code)),
    CONSTRAINT tenant_name_upper CHECK (tenant_name = UPPER(tenant_name))
);

-- Unique constraint on tenant_code
CREATE UNIQUE INDEX IF NOT EXISTS idx_tenant_code_unique ON public.tenant(tenant_code);

COMMENT ON TABLE public.tenant IS 'Canonical organization registry for multi-tenancy. Supersedes custodian for organizational identity.';
COMMENT ON COLUMN public.tenant.tenant_type IS 'NATIONAL=ODPEM/NDRMC, MILITARY=JDF/JCF, PARISH=Municipal Corps, MINISTRY=Govt ministries, EXTERNAL=NGOs, INFRASTRUCTURE=Utilities, PUBLIC=Dashboard access';
COMMENT ON COLUMN public.tenant.data_scope IS 'Data visibility scope: OWN_DATA (own org only), PARISH_DATA (parish-wide), NATIONAL_DATA (all parishes)';

-- ============================================================================
-- SECTION 2: ADD tenant_id TO CUSTODIAN (Graceful Migration Bridge)
-- ============================================================================

-- Add tenant_id column to custodian if not exists
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public' 
        AND table_name = 'custodian' 
        AND column_name = 'tenant_id'
    ) THEN
        ALTER TABLE public.custodian ADD COLUMN tenant_id INTEGER REFERENCES public.tenant(tenant_id);
        COMMENT ON COLUMN public.custodian.tenant_id IS 'FK to tenant for multi-tenancy migration. Custodian records will be migrated to tenant table.';
    END IF;
END $$;

-- ============================================================================
-- SECTION 3: ADD tenant_id TO WAREHOUSE (Optional Direct Lookup)
-- ============================================================================

-- Add tenant_id column to warehouse if not exists (custodian_id remains as FK)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public' 
        AND table_name = 'warehouse' 
        AND column_name = 'tenant_id'
    ) THEN
        ALTER TABLE public.warehouse ADD COLUMN tenant_id INTEGER REFERENCES public.tenant(tenant_id);
        COMMENT ON COLUMN public.warehouse.tenant_id IS 'Direct FK to tenant for multi-tenancy queries. Derived from custodian.tenant_id during migration.';
    END IF;
END $$;

-- ============================================================================
-- SECTION 4: TENANT CONFIGURATION TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.tenant_config (
    config_id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES public.tenant(tenant_id) ON DELETE CASCADE,
    config_key VARCHAR(50) NOT NULL,
    config_value TEXT NOT NULL,
    config_type VARCHAR(20) DEFAULT 'STRING' CHECK (config_type IN (
        'STRING', 'INTEGER', 'DECIMAL', 'BOOLEAN', 'JSON'
    )),
    effective_date DATE NOT NULL DEFAULT CURRENT_DATE,
    expiry_date DATE,
    description TEXT,
    create_by_id VARCHAR(20) NOT NULL DEFAULT 'SYSTEM',
    create_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_by_id VARCHAR(20) NOT NULL DEFAULT 'SYSTEM',
    update_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    version_nbr INTEGER NOT NULL DEFAULT 1,
    CONSTRAINT tenant_config_unique UNIQUE (tenant_id, config_key, effective_date)
);

COMMENT ON TABLE public.tenant_config IS 'Tenant-specific configuration overrides (approval thresholds, phase parameters, etc.)';

-- ============================================================================
-- SECTION 5: TENANT-USER MAPPING TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.tenant_user (
    tenant_id INTEGER NOT NULL REFERENCES public.tenant(tenant_id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES public."user"(user_id) ON DELETE CASCADE,
    is_primary_tenant BOOLEAN DEFAULT TRUE,
    access_level VARCHAR(20) DEFAULT 'STANDARD' CHECK (access_level IN (
        'ADMIN', 'FULL', 'STANDARD', 'LIMITED', 'READ_ONLY'
    )),
    assigned_at TIMESTAMP(0) WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    assigned_by INTEGER REFERENCES public."user"(user_id),
    status_code CHAR(1) NOT NULL DEFAULT 'A' CHECK (status_code IN ('A', 'I')),
    create_by_id VARCHAR(20) NOT NULL DEFAULT 'SYSTEM',
    create_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, user_id)
);

COMMENT ON TABLE public.tenant_user IS 'Maps users to tenants with access levels. Users may belong to multiple tenants.';
COMMENT ON COLUMN public.tenant_user.access_level IS 'From DMIS Access Matrix: ADMIN, FULL, STANDARD, LIMITED, READ_ONLY';

-- ============================================================================
-- SECTION 6: TENANT-WAREHOUSE MAPPING TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.tenant_warehouse (
    tenant_id INTEGER NOT NULL REFERENCES public.tenant(tenant_id) ON DELETE CASCADE,
    warehouse_id INTEGER NOT NULL REFERENCES public.warehouse(warehouse_id) ON DELETE CASCADE,
    ownership_type VARCHAR(20) DEFAULT 'OWNED' CHECK (ownership_type IN (
        'OWNED', 'SHARED', 'ALLOCATED', 'PARTNER'
    )),
    access_level VARCHAR(20) DEFAULT 'FULL' CHECK (access_level IN (
        'FULL', 'STANDARD', 'LIMITED', 'READ_ONLY'
    )),
    effective_date DATE NOT NULL DEFAULT CURRENT_DATE,
    expiry_date DATE,
    create_by_id VARCHAR(20) NOT NULL DEFAULT 'SYSTEM',
    create_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, warehouse_id)
);

COMMENT ON TABLE public.tenant_warehouse IS 'Maps warehouses to tenants. Supports shared warehouse model.';

-- ============================================================================
-- SECTION 7: DATA SHARING AGREEMENT TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.data_sharing_agreement (
    agreement_id SERIAL PRIMARY KEY,
    from_tenant_id INTEGER NOT NULL REFERENCES public.tenant(tenant_id),
    to_tenant_id INTEGER NOT NULL REFERENCES public.tenant(tenant_id),
    data_category VARCHAR(50) NOT NULL CHECK (data_category IN (
        'INVENTORY', 'RELIEF_REQUESTS', 'ALLOCATIONS', 'BENEFICIARY',
        'DONATIONS', 'FINANCIAL', '3W_REPORTS', 'DASHBOARD'
    )),
    permission_level VARCHAR(20) DEFAULT 'READ' CHECK (permission_level IN (
        'READ', 'CONTRIBUTE', 'FULL'
    )),
    effective_date DATE NOT NULL DEFAULT CURRENT_DATE,
    expiry_date DATE,
    agreement_notes TEXT,
    status_code CHAR(1) NOT NULL DEFAULT 'A' CHECK (status_code IN ('A', 'I', 'E')),
    approved_by INTEGER REFERENCES public."user"(user_id),
    approved_at TIMESTAMP(0) WITHOUT TIME ZONE,
    create_by_id VARCHAR(20) NOT NULL DEFAULT 'SYSTEM',
    create_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_by_id VARCHAR(20) NOT NULL DEFAULT 'SYSTEM',
    update_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    version_nbr INTEGER NOT NULL DEFAULT 1
);

COMMENT ON TABLE public.data_sharing_agreement IS 'Cross-tenant data sharing permissions for multi-agency coordination';

-- ============================================================================
-- SECTION 8: EVENT PHASE TABLE (EP-02 Supply Replenishment)
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.event_phase (
    phase_id SERIAL PRIMARY KEY,
    event_id INTEGER NOT NULL REFERENCES public.event(event_id),
    phase_code VARCHAR(20) NOT NULL CHECK (phase_code IN (
        'SURGE', 'STABILIZED', 'BASELINE'
    )),
    demand_window_hours INTEGER NOT NULL,
    planning_window_hours INTEGER NOT NULL,
    buffer_multiplier NUMERIC(3,2) DEFAULT 1.25,
    auto_transition_hours INTEGER,
    started_at TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_by INTEGER REFERENCES public."user"(user_id),
    ended_at TIMESTAMP(0) WITHOUT TIME ZONE,
    ended_by INTEGER REFERENCES public."user"(user_id),
    transition_reason TEXT,
    is_current BOOLEAN DEFAULT TRUE,
    create_by_id VARCHAR(20) NOT NULL DEFAULT 'SYSTEM',
    create_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_by_id VARCHAR(20) NOT NULL DEFAULT 'SYSTEM',
    update_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    version_nbr INTEGER NOT NULL DEFAULT 1
);

COMMENT ON TABLE public.event_phase IS 'Event phase tracking for Supply Replenishment burn rate calculations';
COMMENT ON COLUMN public.event_phase.phase_code IS 'SURGE (0-72h), STABILIZED (72h-7d), BASELINE (ongoing)';
COMMENT ON COLUMN public.event_phase.demand_window_hours IS 'Lookback window for burn rate calculation';
COMMENT ON COLUMN public.event_phase.planning_window_hours IS 'Forward planning horizon';

-- ============================================================================
-- SECTION 9: NEEDS LIST TABLE (EP-02 Supply Replenishment)
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.needs_list (
    needs_list_id SERIAL PRIMARY KEY,
    event_id INTEGER NOT NULL REFERENCES public.event(event_id),
    warehouse_id INTEGER NOT NULL REFERENCES public.warehouse(warehouse_id),
    phase_id INTEGER REFERENCES public.event_phase(phase_id),
    generated_at TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    generated_by INTEGER NOT NULL REFERENCES public."user"(user_id),
    status_code VARCHAR(20) NOT NULL DEFAULT 'DRAFT' CHECK (status_code IN (
        'DRAFT', 'PENDING_APPROVAL', 'APPROVED', 'REJECTED',
        'MODIFIED', 'IN_PROGRESS', 'FULFILLED', 'SUPERSEDED', 'CANCELLED'
    )),
    data_freshness VARCHAR(10) DEFAULT 'HIGH' CHECK (data_freshness IN (
        'HIGH', 'MEDIUM', 'LOW', 'STALE'
    )),
    freshness_timestamp TIMESTAMP(0) WITHOUT TIME ZONE,
    approved_by INTEGER REFERENCES public."user"(user_id),
    approved_at TIMESTAMP(0) WITHOUT TIME ZONE,
    approval_comments TEXT,
    modified_by INTEGER REFERENCES public."user"(user_id),
    modified_at TIMESTAMP(0) WITHOUT TIME ZONE,
    modification_reason TEXT,
    rejected_by INTEGER REFERENCES public."user"(user_id),
    rejected_at TIMESTAMP(0) WITHOUT TIME ZONE,
    rejection_reason TEXT,
    superseded_by INTEGER REFERENCES public.needs_list(needs_list_id),
    create_by_id VARCHAR(20) NOT NULL DEFAULT 'SYSTEM',
    create_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_by_id VARCHAR(20) NOT NULL DEFAULT 'SYSTEM',
    update_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    version_nbr INTEGER NOT NULL DEFAULT 1
);

COMMENT ON TABLE public.needs_list IS 'Supply Replenishment needs list header - EP-02';

-- ============================================================================
-- SECTION 10: NEEDS LIST ITEM TABLE (EP-02 Supply Replenishment)
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.needs_list_item (
    needs_list_item_id SERIAL PRIMARY KEY,
    needs_list_id INTEGER NOT NULL REFERENCES public.needs_list(needs_list_id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES public.item(item_id),
    -- Three Horizons allocation (aligned with Django model)
    horizon_a_qty NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (horizon_a_qty >= 0),
    horizon_b_qty NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (horizon_b_qty >= 0),
    horizon_c_qty NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (horizon_c_qty >= 0),
    -- Burn rate calculation
    burn_rate NUMERIC(12,4),
    burn_rate_source VARCHAR(20) CHECK (burn_rate_source IN (
        'CALCULATED', 'BASELINE', 'MANUAL'
    )),
    time_to_stockout_hours NUMERIC(10,2),
    -- Inventory position
    available_qty NUMERIC(12,2) NOT NULL,
    reserved_qty NUMERIC(12,2) DEFAULT 0,
    inbound_qty NUMERIC(12,2) DEFAULT 0,
    inbound_source VARCHAR(100),
    -- Gap and recommendation
    gap_qty NUMERIC(12,2) NOT NULL,
    recommended_qty NUMERIC(12,2) NOT NULL,
    adjusted_qty NUMERIC(12,2),
    adjustment_reason TEXT,
    adjusted_by INTEGER REFERENCES public."user"(user_id),
    adjusted_at TIMESTAMP(0) WITHOUT TIME ZONE,
    -- Fulfillment tracking
    covered_qty NUMERIC(12,2) DEFAULT 0,
    source_warehouse_id INTEGER REFERENCES public.warehouse(warehouse_id),
    estimated_lead_time_hours INTEGER,
    item_status VARCHAR(20) DEFAULT 'PENDING' CHECK (item_status IN (
        'PENDING', 'IN_PROGRESS', 'FULFILLED', 'CANCELLED', 'PARTIAL'
    )),
    uom_code VARCHAR(25) NOT NULL REFERENCES public.unitofmeasure(uom_code),
    notes TEXT,
    create_by_id VARCHAR(20) NOT NULL DEFAULT 'SYSTEM',
    create_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_by_id VARCHAR(20) NOT NULL DEFAULT 'SYSTEM',
    update_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    version_nbr INTEGER NOT NULL DEFAULT 1
);

COMMENT ON TABLE public.needs_list_item IS 'Supply Replenishment needs list line items with Three Horizons logic';
COMMENT ON COLUMN public.needs_list_item.horizon_a_qty IS 'Horizon A quantity (transfer recommendation)';
COMMENT ON COLUMN public.needs_list_item.horizon_b_qty IS 'Horizon B quantity (donation recommendation)';
COMMENT ON COLUMN public.needs_list_item.horizon_c_qty IS 'Horizon C quantity (procurement recommendation)';

-- ============================================================================
-- SECTION 11: WAREHOUSE SYNC STATUS TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.warehouse_sync_status (
    warehouse_id INTEGER PRIMARY KEY REFERENCES public.warehouse(warehouse_id),
    last_sync_at TIMESTAMP(0) WITHOUT TIME ZONE,
    sync_status VARCHAR(20) DEFAULT 'UNKNOWN' CHECK (sync_status IN (
        'ONLINE', 'SYNCING', 'STALE', 'OFFLINE', 'UNKNOWN'
    )),
    freshness_level VARCHAR(10) DEFAULT 'UNKNOWN' CHECK (freshness_level IN (
        'HIGH', 'MEDIUM', 'LOW', 'STALE', 'UNKNOWN'
    )),
    items_synced INTEGER,
    sync_errors TEXT,
    last_online_at TIMESTAMP(0) WITHOUT TIME ZONE,
    create_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE public.warehouse_sync_status IS 'Tracks warehouse data freshness for offline/mobile sync scenarios';

-- ============================================================================
-- SECTION 12: SEED TENANT DATA (From Stakeholder Analysis v1.6)
-- ============================================================================

INSERT INTO public.tenant (tenant_code, tenant_name, tenant_type, data_scope, pii_access, offline_required, mobile_priority, status_code, create_by_id, update_by_id)
VALUES
    -- NATIONAL TIER
    ('ODPEM-HQ', 'OFFICE OF DISASTER PREPAREDNESS AND EMERGENCY MANAGEMENT - HQ', 'NATIONAL', 'NATIONAL_DATA', 'AGGREGATED', FALSE, 'LOW', 'A', 'TEST_SCRIPT', 'TEST_SCRIPT'),
    ('ODPEM-NEOC', 'ODPEM - NATIONAL EMERGENCY OPERATIONS CENTRE', 'NATIONAL', 'NATIONAL_DATA', 'AGGREGATED', FALSE, 'MEDIUM', 'A', 'TEST_SCRIPT', 'TEST_SCRIPT'),
    ('ODPEM-LOGISTICS', 'ODPEM - LOGISTICS DIVISION', 'NATIONAL', 'NATIONAL_DATA', 'NONE', TRUE, 'HIGH', 'A', 'TEST_SCRIPT', 'TEST_SCRIPT'),
    ('ODPEM-FINANCE', 'ODPEM - FINANCE AND COMPLIANCE', 'NATIONAL', 'NATIONAL_DATA', 'NONE', FALSE, 'LOW', 'A', 'TEST_SCRIPT', 'TEST_SCRIPT'),
    ('NDRMC', 'NATIONAL DISASTER RISK MANAGEMENT COUNCIL', 'NATIONAL', 'NATIONAL_DATA', 'NONE', FALSE, 'LOW', 'A', 'TEST_SCRIPT', 'TEST_SCRIPT'),
    ('MLGRD', 'MINISTRY OF LOCAL GOVERNMENT AND RURAL DEVELOPMENT', 'MINISTRY', 'NATIONAL_DATA', 'NONE', FALSE, 'LOW', 'A', 'TEST_SCRIPT', 'TEST_SCRIPT'),
    ('MFPS', 'MINISTRY OF FINANCE AND PUBLIC SERVICE', 'MINISTRY', 'NATIONAL_DATA', 'NONE', FALSE, 'LOW', 'A', 'TEST_SCRIPT', 'TEST_SCRIPT'),
    ('MHW', 'MINISTRY OF HEALTH AND WELLNESS', 'MINISTRY', 'NATIONAL_DATA', 'LIMITED', FALSE, 'MEDIUM', 'A', 'TEST_SCRIPT', 'TEST_SCRIPT'),
    ('PIOJ', 'PLANNING INSTITUTE OF JAMAICA', 'NATIONAL', 'NATIONAL_DATA', 'AGGREGATED', FALSE, 'LOW', 'A', 'TEST_SCRIPT', 'TEST_SCRIPT'),
    ('OPM', 'OFFICE OF THE PRIME MINISTER', 'NATIONAL', 'NATIONAL_DATA', 'AGGREGATED', FALSE, 'LOW', 'A', 'TEST_SCRIPT', 'TEST_SCRIPT'),
    
    -- MILITARY TIER
    ('JDF', 'JAMAICA DEFENCE FORCE', 'MILITARY', 'OWN_DATA', 'NONE', TRUE, 'HIGH', 'A', 'TEST_SCRIPT', 'TEST_SCRIPT'),
    ('JCF', 'JAMAICA CONSTABULARY FORCE', 'MILITARY', 'OWN_DATA', 'NONE', FALSE, 'MEDIUM', 'A', 'TEST_SCRIPT', 'TEST_SCRIPT'),
    
    -- MINISTRY TIER
    ('MLSS', 'MINISTRY OF LABOUR AND SOCIAL SECURITY', 'MINISTRY', 'NATIONAL_DATA', 'AGGREGATED', TRUE, 'HIGH', 'A', 'TEST_SCRIPT', 'TEST_SCRIPT'),
    
    -- PARISH TIER
    ('PARISH-KN', 'KINGSTON AND ST. ANDREW MUNICIPAL CORPORATION', 'PARISH', 'PARISH_DATA', 'LIMITED', TRUE, 'CRITICAL', 'A', 'TEST_SCRIPT', 'TEST_SCRIPT'),
    ('PARISH-SC', 'ST. CATHERINE MUNICIPAL CORPORATION', 'PARISH', 'PARISH_DATA', 'LIMITED', TRUE, 'CRITICAL', 'A', 'TEST_SCRIPT', 'TEST_SCRIPT'),
    ('PARISH-PD', 'PORTLAND MUNICIPAL CORPORATION', 'PARISH', 'PARISH_DATA', 'LIMITED', TRUE, 'CRITICAL', 'A', 'TEST_SCRIPT', 'TEST_SCRIPT'),
    ('PARISH-SJ', 'ST. JAMES MUNICIPAL CORPORATION', 'PARISH', 'PARISH_DATA', 'LIMITED', TRUE, 'CRITICAL', 'A', 'TEST_SCRIPT', 'TEST_SCRIPT'),
    ('PARISH-MC', 'MANCHESTER MUNICIPAL CORPORATION', 'PARISH', 'PARISH_DATA', 'LIMITED', TRUE, 'CRITICAL', 'A', 'TEST_SCRIPT', 'TEST_SCRIPT'),
    
    -- EXTERNAL TIER (NGOs & Partners)
    ('JRC', 'JAMAICA RED CROSS', 'EXTERNAL', 'OWN_DATA', 'NONE', TRUE, 'HIGH', 'A', 'TEST_SCRIPT', 'TEST_SCRIPT'),
    ('FFP', 'FOOD FOR THE POOR', 'EXTERNAL', 'OWN_DATA', 'NONE', TRUE, 'HIGH', 'A', 'TEST_SCRIPT', 'TEST_SCRIPT'),
    ('UNOPS', 'UNITED NATIONS OFFICE FOR PROJECT SERVICES', 'EXTERNAL', 'OWN_DATA', 'NONE', FALSE, 'LOW', 'A', 'TEST_SCRIPT', 'TEST_SCRIPT'),
    ('WFP', 'WORLD FOOD PROGRAMME', 'EXTERNAL', 'OWN_DATA', 'NONE', FALSE, 'MEDIUM', 'A', 'TEST_SCRIPT', 'TEST_SCRIPT'),
    
    -- INFRASTRUCTURE TIER
    ('JPS', 'JAMAICA PUBLIC SERVICE', 'INFRASTRUCTURE', 'OWN_DATA', 'NONE', FALSE, 'MEDIUM', 'A', 'TEST_SCRIPT', 'TEST_SCRIPT'),
    ('NWC', 'NATIONAL WATER COMMISSION', 'INFRASTRUCTURE', 'OWN_DATA', 'NONE', FALSE, 'MEDIUM', 'A', 'TEST_SCRIPT', 'TEST_SCRIPT'),
    
    -- PUBLIC TIER
    ('PUBLIC', 'PUBLIC DASHBOARD ACCESS', 'PUBLIC', 'OWN_DATA', 'NONE', FALSE, 'MEDIUM', 'A', 'TEST_SCRIPT', 'TEST_SCRIPT')
ON CONFLICT (tenant_code) DO NOTHING;

-- ============================================================================
-- SECTION 13: MIGRATE EXISTING CUSTODIANS TO TENANTS
-- ============================================================================

-- Create tenant records for any existing custodians not yet linked
INSERT INTO public.tenant (tenant_code, tenant_name, tenant_type, address1_text, address2_text, parish_code, contact_name, phone_no, email_text, data_scope, status_code, create_by_id, update_by_id)
SELECT 
    UPPER(REPLACE(SUBSTRING(c.custodian_name FROM 1 FOR 20), ' ', '-')) AS tenant_code,
    UPPER(c.custodian_name) AS tenant_name,
    'NATIONAL' AS tenant_type,  -- Default; can be updated later
    c.address1_text,
    c.address2_text,
    c.parish_code,
    c.contact_name,
    c.phone_no,
    c.email_text,
    'OWN_DATA' AS data_scope,
    'A' AS status_code,
    'CUSTODIAN_MIGRATION' AS create_by_id,
    'CUSTODIAN_MIGRATION' AS update_by_id
FROM public.custodian c
WHERE c.tenant_id IS NULL
AND NOT EXISTS (
    SELECT 1 FROM public.tenant t 
    WHERE UPPER(t.tenant_name) = UPPER(c.custodian_name)
)
ON CONFLICT (tenant_code) DO NOTHING;

-- Link custodians to their tenant records
UPDATE public.custodian c
SET tenant_id = t.tenant_id
FROM public.tenant t
WHERE UPPER(c.custodian_name) = UPPER(t.tenant_name)
AND c.tenant_id IS NULL;

-- ============================================================================
-- SECTION 14: LINK WAREHOUSES TO TENANTS (via custodian)
-- ============================================================================

-- Update warehouse.tenant_id based on custodian.tenant_id
UPDATE public.warehouse w
SET tenant_id = c.tenant_id
FROM public.custodian c
WHERE w.custodian_id = c.custodian_id
AND w.tenant_id IS NULL
AND c.tenant_id IS NOT NULL;

-- ============================================================================
-- SECTION 15: TENANT CONFIGURATION (Approval Thresholds, Phase Parameters)
-- ============================================================================

-- ODPEM-LOGISTICS configuration
INSERT INTO public.tenant_config (tenant_id, config_key, config_value, config_type, description, create_by_id, update_by_id)
SELECT t.tenant_id, 'APPROVAL_THRESHOLD_JMD', '3000000', 'DECIMAL', 'Procurement approval threshold per PPA 2015', 'TEST_SCRIPT', 'TEST_SCRIPT'
FROM public.tenant t WHERE t.tenant_code = 'ODPEM-LOGISTICS'
ON CONFLICT (tenant_id, config_key, effective_date) DO NOTHING;

INSERT INTO public.tenant_config (tenant_id, config_key, config_value, config_type, description, create_by_id, update_by_id)
SELECT t.tenant_id, 'EMERGENCY_APPROVAL_LIMIT_JMD', '100000000', 'DECIMAL', 'Emergency contract limit per PPA 2015 S24', 'TEST_SCRIPT', 'TEST_SCRIPT'
FROM public.tenant t WHERE t.tenant_code = 'ODPEM-LOGISTICS'
ON CONFLICT (tenant_id, config_key, effective_date) DO NOTHING;

INSERT INTO public.tenant_config (tenant_id, config_key, config_value, config_type, description, create_by_id, update_by_id)
SELECT t.tenant_id, 'SURGE_DEMAND_WINDOW_HOURS', '6', 'INTEGER', 'Burn rate lookback for SURGE phase', 'TEST_SCRIPT', 'TEST_SCRIPT'
FROM public.tenant t WHERE t.tenant_code = 'ODPEM-LOGISTICS'
ON CONFLICT (tenant_id, config_key, effective_date) DO NOTHING;

INSERT INTO public.tenant_config (tenant_id, config_key, config_value, config_type, description, create_by_id, update_by_id)
SELECT t.tenant_id, 'STABILIZED_PLANNING_WINDOW_HOURS', '168', 'INTEGER', 'Forward planning horizon for STABILIZED phase', 'TEST_SCRIPT', 'TEST_SCRIPT'
FROM public.tenant t WHERE t.tenant_code = 'ODPEM-LOGISTICS'
ON CONFLICT (tenant_id, config_key, effective_date) DO NOTHING;

INSERT INTO public.tenant_config (tenant_id, config_key, config_value, config_type, description, create_by_id, update_by_id)
SELECT t.tenant_id, 'BUFFER_MULTIPLIER', '1.25', 'DECIMAL', 'Safety stock multiplier (25%)', 'TEST_SCRIPT', 'TEST_SCRIPT'
FROM public.tenant t WHERE t.tenant_code = 'ODPEM-LOGISTICS'
ON CONFLICT (tenant_id, config_key, effective_date) DO NOTHING;

INSERT INTO public.tenant_config (tenant_id, config_key, config_value, config_type, description, create_by_id, update_by_id)
SELECT t.tenant_id, 'DATA_FRESHNESS_WARNING_HOURS', '4', 'INTEGER', 'Hours before data freshness warning', 'TEST_SCRIPT', 'TEST_SCRIPT'
FROM public.tenant t WHERE t.tenant_code = 'ODPEM-LOGISTICS'
ON CONFLICT (tenant_id, config_key, effective_date) DO NOTHING;

INSERT INTO public.tenant_config (tenant_id, config_key, config_value, config_type, description, create_by_id, update_by_id)
SELECT t.tenant_id, 'DATA_FRESHNESS_STALE_HOURS', '24', 'INTEGER', 'Hours before data considered stale', 'TEST_SCRIPT', 'TEST_SCRIPT'
FROM public.tenant t WHERE t.tenant_code = 'ODPEM-LOGISTICS'
ON CONFLICT (tenant_id, config_key, effective_date) DO NOTHING;

-- ============================================================================
-- SECTION 16: TEST EVENT (Hurricane Melissa)
-- ============================================================================

INSERT INTO public.event (
    event_type,
    start_date,
    event_name,
    event_desc,
    impact_desc,
    status_code,
    create_by_id,
    create_dtime,
    update_by_id,
    update_dtime,
    version_nbr
)
SELECT
    v.event_type,
    v.start_date,
    v.event_name,
    v.event_desc,
    v.impact_desc,
    v.status_code,
    v.create_by_id,
    v.create_dtime,
    v.update_by_id,
    v.update_dtime,
    v.version_nbr
FROM (
    VALUES
        ('HURRICANE', '2026-01-15', 'HURRICANE MELISSA', 'Category 4 Hurricane affecting southeastern parishes', 'Major flooding in Portland, St. Thomas, St. Andrew. 50,000+ displaced.', 'A', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW(), 1),
        ('ADHOC', '2026-01-01', 'GENERAL PREPAREDNESS 2026', 'Ongoing preparedness stockpile for 2026 hurricane season', 'Pre-positioned supplies across warehouse network', 'A', 'TEST_SCRIPT', NOW(), 'TEST_SCRIPT', NOW(), 1)
) AS v(
    event_type,
    start_date,
    event_name,
    event_desc,
    impact_desc,
    status_code,
    create_by_id,
    create_dtime,
    update_by_id,
    update_dtime,
    version_nbr
)
WHERE NOT EXISTS (
    SELECT 1
    FROM public.event e
    WHERE e.event_name = v.event_name
);

-- ============================================================================
-- SECTION 17: EVENT PHASES (Hurricane Melissa)
-- ============================================================================

-- SURGE phase (completed)
INSERT INTO public.event_phase (event_id, phase_code, demand_window_hours, planning_window_hours, buffer_multiplier, auto_transition_hours, started_at, ended_at, is_current, create_by_id, update_by_id)
SELECT e.event_id, 'SURGE', 6, 72, 1.25, 72, '2026-01-15 06:00:00', '2026-01-18 06:00:00', FALSE, 'TEST_SCRIPT', 'TEST_SCRIPT'
FROM public.event e WHERE e.event_name = 'HURRICANE MELISSA'
AND NOT EXISTS (SELECT 1 FROM public.event_phase ep WHERE ep.event_id = e.event_id AND ep.phase_code = 'SURGE');

-- STABILIZED phase (current)
INSERT INTO public.event_phase (event_id, phase_code, demand_window_hours, planning_window_hours, buffer_multiplier, started_at, is_current, create_by_id, update_by_id)
SELECT e.event_id, 'STABILIZED', 72, 168, 1.25, '2026-01-18 06:00:00', TRUE, 'TEST_SCRIPT', 'TEST_SCRIPT'
FROM public.event e WHERE e.event_name = 'HURRICANE MELISSA'
AND NOT EXISTS (SELECT 1 FROM public.event_phase ep WHERE ep.event_id = e.event_id AND ep.phase_code = 'STABILIZED');

-- ============================================================================
-- SECTION 18: WAREHOUSE SYNC STATUS (Data Freshness Scenarios)
-- ============================================================================

-- Initialize sync status for existing warehouses
INSERT INTO public.warehouse_sync_status (warehouse_id, last_sync_at, sync_status, freshness_level, items_synced, last_online_at, sync_errors)
SELECT 
    w.warehouse_id,
    CASE 
        WHEN w.warehouse_type = 'MAIN-HUB' THEN NOW() - INTERVAL '30 minutes'
        ELSE NOW() - INTERVAL '6 hours'
    END AS last_sync_at,
    CASE
        WHEN w.warehouse_type = 'MAIN-HUB' THEN 'ONLINE'
        ELSE 'STALE'
    END AS sync_status,
    CASE 
        WHEN w.warehouse_type = 'MAIN-HUB' THEN 'HIGH'
        ELSE 'MEDIUM'
    END AS freshness_level,
    0 AS items_synced,
    NOW() AS last_online_at,
    NULL AS sync_errors
FROM public.warehouse w
WHERE w.status_code = 'A'
AND w.create_by_id = 'TEST_SCRIPT'
ON CONFLICT (warehouse_id) DO UPDATE SET
    last_sync_at = EXCLUDED.last_sync_at,
    sync_status = EXCLUDED.sync_status,
    freshness_level = EXCLUDED.freshness_level,
    update_dtime = NOW();

-- ============================================================================
-- SECTION 19: CREATE INDEXES FOR MULTI-TENANCY PERFORMANCE
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_tenant_type ON public.tenant(tenant_type);
CREATE INDEX IF NOT EXISTS idx_tenant_status ON public.tenant(status_code);
CREATE INDEX IF NOT EXISTS idx_tenant_user_user ON public.tenant_user(user_id);
CREATE INDEX IF NOT EXISTS idx_tenant_warehouse_warehouse ON public.tenant_warehouse(warehouse_id);
CREATE INDEX IF NOT EXISTS idx_data_sharing_from ON public.data_sharing_agreement(from_tenant_id);
CREATE INDEX IF NOT EXISTS idx_data_sharing_to ON public.data_sharing_agreement(to_tenant_id);
CREATE INDEX IF NOT EXISTS idx_needs_list_event ON public.needs_list(event_id);
CREATE INDEX IF NOT EXISTS idx_needs_list_warehouse ON public.needs_list(warehouse_id);
CREATE INDEX IF NOT EXISTS idx_needs_list_status ON public.needs_list(status_code);
CREATE INDEX IF NOT EXISTS idx_needs_list_item_needs_list ON public.needs_list_item(needs_list_id);
CREATE INDEX IF NOT EXISTS idx_needs_list_item_item ON public.needs_list_item(item_id);
-- NOTE: No single horizon code index; schema uses horizon_a_qty / horizon_b_qty / horizon_c_qty columns.
CREATE INDEX IF NOT EXISTS idx_event_phase_event ON public.event_phase(event_id);
DROP INDEX IF EXISTS public.idx_event_phase_current;
CREATE UNIQUE INDEX idx_event_phase_current ON public.event_phase(event_id) WHERE is_current = TRUE;
CREATE INDEX IF NOT EXISTS idx_custodian_tenant ON public.custodian(tenant_id) WHERE tenant_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_warehouse_tenant ON public.warehouse(tenant_id) WHERE tenant_id IS NOT NULL;

-- ============================================================================
-- SECTION 20: CREATE TRIGGERS FOR AUDIT TIMESTAMPS
-- ============================================================================

-- Drop existing triggers first (safe even if they do not exist)
DROP TRIGGER IF EXISTS trg_tenant_update_dtime ON public.tenant;
DROP TRIGGER IF EXISTS trg_tenant_config_update_dtime ON public.tenant_config;
DROP TRIGGER IF EXISTS trg_needs_list_update_dtime ON public.needs_list;
DROP TRIGGER IF EXISTS trg_needs_list_item_update_dtime ON public.needs_list_item;

-- Create triggers only if helper function public.set_updated_at() exists.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'public'
          AND p.proname = 'set_updated_at'
          AND p.pronargs = 0
    ) THEN
        EXECUTE 'CREATE TRIGGER trg_tenant_update_dtime
            BEFORE UPDATE ON public.tenant
            FOR EACH ROW
            EXECUTE FUNCTION public.set_updated_at()';

        EXECUTE 'CREATE TRIGGER trg_tenant_config_update_dtime
            BEFORE UPDATE ON public.tenant_config
            FOR EACH ROW
            EXECUTE FUNCTION public.set_updated_at()';

        EXECUTE 'CREATE TRIGGER trg_needs_list_update_dtime
            BEFORE UPDATE ON public.needs_list
            FOR EACH ROW
            EXECUTE FUNCTION public.set_updated_at()';

        EXECUTE 'CREATE TRIGGER trg_needs_list_item_update_dtime
            BEFORE UPDATE ON public.needs_list_item
            FOR EACH ROW
            EXECUTE FUNCTION public.set_updated_at()';
    ELSE
        RAISE NOTICE 'Skipping audit timestamp trigger creation: function public.set_updated_at() does not exist.';
    END IF;
END $$;

-- ============================================================================
-- COMMIT TRANSACTION
-- ============================================================================

COMMIT;

-- ============================================================================
-- POST-EXECUTION SUMMARY
-- ============================================================================

DO $$
DECLARE
    v_tenant_count INTEGER;
    v_custodian_linked INTEGER;
    v_warehouse_linked INTEGER;
    v_event_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO v_tenant_count FROM public.tenant;
    SELECT COUNT(*) INTO v_custodian_linked FROM public.custodian WHERE tenant_id IS NOT NULL;
    SELECT COUNT(*) INTO v_warehouse_linked FROM public.warehouse WHERE tenant_id IS NOT NULL;
    SELECT COUNT(*) INTO v_event_count FROM public.event WHERE create_by_id = 'TEST_SCRIPT';
    
    RAISE NOTICE '============================================================';
    RAISE NOTICE 'DMIS MULTI-TENANCY + EP-02 TEST DATA CREATION COMPLETE';
    RAISE NOTICE '============================================================';
    RAISE NOTICE '';
    RAISE NOTICE 'SCHEMA CHANGES:';
    RAISE NOTICE '  - tenant table created (canonical organization registry)';
    RAISE NOTICE '  - custodian.tenant_id added (graceful migration bridge)';
    RAISE NOTICE '  - warehouse.tenant_id added (direct tenant lookup)';
    RAISE NOTICE '  - Supporting tables: tenant_config, tenant_user, tenant_warehouse';
    RAISE NOTICE '  - EP-02 tables: event_phase, needs_list, needs_list_item';
    RAISE NOTICE '  - Sync tracking: warehouse_sync_status';
    RAISE NOTICE '';
    RAISE NOTICE 'DATA SUMMARY:';
    RAISE NOTICE '  - Total tenants: %', v_tenant_count;
    RAISE NOTICE '  - Custodians linked to tenants: %', v_custodian_linked;
    RAISE NOTICE '  - Warehouses linked to tenants: %', v_warehouse_linked;
    RAISE NOTICE '  - Test events created: %', v_event_count;
    RAISE NOTICE '';
    RAISE NOTICE 'MIGRATION STATUS:';
    RAISE NOTICE '  - Existing custodians automatically migrated to tenant table';
    RAISE NOTICE '  - custodian.tenant_id FK established for backward compatibility';
    RAISE NOTICE '  - warehouse.tenant_id derived from custodian linkage';
    RAISE NOTICE '';
    RAISE NOTICE 'NEXT STEPS:';
    RAISE NOTICE '  1. Review tenant records and update tenant_type as needed';
    RAISE NOTICE '  2. Create tenant_user mappings for existing users';
    RAISE NOTICE '  3. Configure data_sharing_agreements for cross-tenant access';
    RAISE NOTICE '';
    RAISE NOTICE 'To purge test data: psql -d dmis -f dmis_test_data_purge.sql';
    RAISE NOTICE '============================================================';
END $$;
