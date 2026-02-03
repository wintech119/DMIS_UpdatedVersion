-- ============================================================================
-- DMIS Supply Replenishment Module (EP-02) - Database Schema
-- ============================================================================
-- Version: 1.0
-- Date: February 2026
-- Description: New tables and alterations for Supply Replenishment functionality
-- ============================================================================

-- ============================================================================
-- PART 1: ALTERATIONS TO EXISTING TABLES
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1.1 ALTER: event - Add phase tracking
-- ----------------------------------------------------------------------------
-- The event table needs to track the current operational phase (SURGE/STABILIZED/BASELINE)

ALTER TABLE public.event
ADD COLUMN IF NOT EXISTS current_phase VARCHAR(15) DEFAULT 'BASELINE' NOT NULL,
ADD COLUMN IF NOT EXISTS phase_changed_at TIMESTAMP(0) WITHOUT TIME ZONE,
ADD COLUMN IF NOT EXISTS phase_changed_by VARCHAR(20);

-- Add constraint for valid phases
ALTER TABLE public.event
ADD CONSTRAINT c_event_phase CHECK (
    current_phase IN ('SURGE', 'STABILIZED', 'BASELINE')
);

COMMENT ON COLUMN public.event.current_phase IS 'Current operational phase: SURGE (0-72h), STABILIZED (post-surge), BASELINE (normal)';
COMMENT ON COLUMN public.event.phase_changed_at IS 'Timestamp when phase was last changed';
COMMENT ON COLUMN public.event.phase_changed_by IS 'User who changed the phase';


-- ----------------------------------------------------------------------------
-- 1.2 ALTER: warehouse - Add minimum threshold and sync tracking
-- ----------------------------------------------------------------------------

ALTER TABLE public.warehouse
ADD COLUMN IF NOT EXISTS min_stock_threshold NUMERIC(12,2) DEFAULT 0.00 NOT NULL,
ADD COLUMN IF NOT EXISTS last_sync_dtime TIMESTAMP(0) WITHOUT TIME ZONE,
ADD COLUMN IF NOT EXISTS sync_status VARCHAR(10) DEFAULT 'UNKNOWN';

ALTER TABLE public.warehouse
ADD CONSTRAINT c_warehouse_min_threshold CHECK (min_stock_threshold >= 0.00),
ADD CONSTRAINT c_warehouse_sync_status CHECK (sync_status IN ('ONLINE', 'STALE', 'OFFLINE', 'UNKNOWN'));

COMMENT ON COLUMN public.warehouse.min_stock_threshold IS 'Default minimum stock threshold for this warehouse; surplus = available - threshold';
COMMENT ON COLUMN public.warehouse.last_sync_dtime IS 'Last time inventory data was synchronized from this warehouse';
COMMENT ON COLUMN public.warehouse.sync_status IS 'Data freshness status: ONLINE (<2h), STALE (2-6h), OFFLINE (>6h), UNKNOWN';


-- ----------------------------------------------------------------------------
-- 1.3 ALTER: item - Add baseline burn rate and category-level thresholds
-- ----------------------------------------------------------------------------

ALTER TABLE public.item
ADD COLUMN IF NOT EXISTS baseline_burn_rate NUMERIC(10,4) DEFAULT 0.0000,
ADD COLUMN IF NOT EXISTS min_stock_threshold NUMERIC(12,2) DEFAULT 0.00,
ADD COLUMN IF NOT EXISTS criticality_level VARCHAR(10) DEFAULT 'NORMAL';

ALTER TABLE public.item
ADD CONSTRAINT c_item_baseline_burn CHECK (baseline_burn_rate >= 0.0000),
ADD CONSTRAINT c_item_min_threshold CHECK (min_stock_threshold >= 0.00),
ADD CONSTRAINT c_item_criticality CHECK (criticality_level IN ('CRITICAL', 'HIGH', 'NORMAL', 'LOW'));

COMMENT ON COLUMN public.item.baseline_burn_rate IS 'Default burn rate (units/hour) used when no recent fulfillment data exists';
COMMENT ON COLUMN public.item.min_stock_threshold IS 'Item-level minimum threshold; overrides warehouse default if set';
COMMENT ON COLUMN public.item.criticality_level IS 'Item criticality for prioritization: CRITICAL, HIGH, NORMAL, LOW';


-- ----------------------------------------------------------------------------
-- 1.4 ALTER: transfer - Add dispatch tracking for inbound calculation
-- ----------------------------------------------------------------------------

ALTER TABLE public.transfer
ADD COLUMN IF NOT EXISTS dispatched_at TIMESTAMP(0) WITHOUT TIME ZONE,
ADD COLUMN IF NOT EXISTS dispatched_by VARCHAR(20),
ADD COLUMN IF NOT EXISTS expected_arrival TIMESTAMP(0) WITHOUT TIME ZONE,
ADD COLUMN IF NOT EXISTS received_at TIMESTAMP(0) WITHOUT TIME ZONE,
ADD COLUMN IF NOT EXISTS received_by VARCHAR(20),
ADD COLUMN IF NOT EXISTS needs_list_id INTEGER;

COMMENT ON COLUMN public.transfer.dispatched_at IS 'Timestamp when transfer was physically dispatched';
COMMENT ON COLUMN public.transfer.expected_arrival IS 'Estimated arrival time at destination warehouse';
COMMENT ON COLUMN public.transfer.received_at IS 'Timestamp when transfer was received at destination';
COMMENT ON COLUMN public.transfer.needs_list_id IS 'FK to needs_list if this transfer was generated from a needs list';


-- ============================================================================
-- PART 2: NEW TABLES
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 2.1 NEW: event_phase_config - Phase-specific parameters
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.event_phase_config (
    config_id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    event_id INTEGER NOT NULL REFERENCES public.event(event_id),
    phase VARCHAR(15) NOT NULL,
    demand_window_hours INTEGER NOT NULL,
    planning_window_hours INTEGER NOT NULL,
    safety_buffer_pct NUMERIC(5,2) NOT NULL DEFAULT 25.00,
    safety_factor NUMERIC(4,2) NOT NULL DEFAULT 1.25,
    freshness_threshold_hours INTEGER NOT NULL DEFAULT 2,
    stale_threshold_hours INTEGER NOT NULL DEFAULT 6,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    create_by_id VARCHAR(20) NOT NULL,
    create_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_by_id VARCHAR(20) NOT NULL,
    update_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    version_nbr INTEGER NOT NULL DEFAULT 1,

    CONSTRAINT c_phase_config_phase CHECK (phase IN ('SURGE', 'STABILIZED', 'BASELINE')),
    CONSTRAINT c_phase_config_demand CHECK (demand_window_hours > 0),
    CONSTRAINT c_phase_config_planning CHECK (planning_window_hours > 0),
    CONSTRAINT c_phase_config_safety_buffer CHECK (safety_buffer_pct >= 0 AND safety_buffer_pct <= 100),
    CONSTRAINT c_phase_config_safety_factor CHECK (safety_factor >= 1.00),
    CONSTRAINT uq_event_phase UNIQUE (event_id, phase)
);

COMMENT ON TABLE public.event_phase_config IS 'Phase-specific configuration parameters for each disaster event';
COMMENT ON COLUMN public.event_phase_config.demand_window_hours IS 'Lookback period for burn rate calculation (SURGE=6, STABILIZED=72, BASELINE=720)';
COMMENT ON COLUMN public.event_phase_config.planning_window_hours IS 'Time horizon for stock requirements (SURGE=72, STABILIZED=168, BASELINE=720)';
COMMENT ON COLUMN public.event_phase_config.safety_buffer_pct IS 'Percentage buffer added to lead time trigger (SURGE=50, STABILIZED=25, BASELINE=10)';

-- Insert default configuration for ADHOC event (or create trigger)
-- INSERT INTO event_phase_config (event_id, phase, demand_window_hours, planning_window_hours, ...)


-- ----------------------------------------------------------------------------
-- 2.2 NEW: event_phase_history - Audit trail for phase transitions
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.event_phase_history (
    history_id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    event_id INTEGER NOT NULL REFERENCES public.event(event_id),
    from_phase VARCHAR(15),
    to_phase VARCHAR(15) NOT NULL,
    changed_at TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    changed_by VARCHAR(20) NOT NULL,
    reason_text VARCHAR(255),

    CONSTRAINT c_phase_history_from CHECK (from_phase IS NULL OR from_phase IN ('SURGE', 'STABILIZED', 'BASELINE')),
    CONSTRAINT c_phase_history_to CHECK (to_phase IN ('SURGE', 'STABILIZED', 'BASELINE'))
);

COMMENT ON TABLE public.event_phase_history IS 'Audit trail of event phase transitions';


-- ----------------------------------------------------------------------------
-- 2.3 NEW: needs_list - Main needs list header
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.needs_list (
    needs_list_id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    needs_list_no VARCHAR(30) NOT NULL UNIQUE,
    event_id INTEGER NOT NULL REFERENCES public.event(event_id),
    warehouse_id INTEGER NOT NULL REFERENCES public.warehouse(warehouse_id),
    event_phase VARCHAR(15) NOT NULL,
    calculation_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    demand_window_hours INTEGER NOT NULL,
    planning_window_hours INTEGER NOT NULL,
    safety_factor NUMERIC(4,2) NOT NULL,
    data_freshness_level VARCHAR(10) NOT NULL DEFAULT 'HIGH',
    status_code VARCHAR(20) NOT NULL DEFAULT 'DRAFT',
    total_gap_qty NUMERIC(15,2) NOT NULL DEFAULT 0.00,
    total_estimated_value NUMERIC(15,2) DEFAULT 0.00,
    submitted_at TIMESTAMP(0) WITHOUT TIME ZONE,
    submitted_by VARCHAR(20),
    approved_at TIMESTAMP(0) WITHOUT TIME ZONE,
    approved_by VARCHAR(20),
    rejected_at TIMESTAMP(0) WITHOUT TIME ZONE,
    rejected_by VARCHAR(20),
    rejection_reason VARCHAR(255),
    superseded_by_id INTEGER REFERENCES public.needs_list(needs_list_id),
    notes_text TEXT,
    create_by_id VARCHAR(20) NOT NULL,
    create_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_by_id VARCHAR(20) NOT NULL,
    update_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    version_nbr INTEGER NOT NULL DEFAULT 1,

    CONSTRAINT c_needs_list_phase CHECK (event_phase IN ('SURGE', 'STABILIZED', 'BASELINE')),
    CONSTRAINT c_needs_list_freshness CHECK (data_freshness_level IN ('HIGH', 'MEDIUM', 'LOW')),
    CONSTRAINT c_needs_list_status CHECK (status_code IN (
        'DRAFT', 'PENDING_APPROVAL', 'APPROVED', 'REJECTED',
        'RETURNED', 'IN_PROGRESS', 'FULFILLED', 'CANCELLED', 'SUPERSEDED'
    )),
    CONSTRAINT c_needs_list_gap CHECK (total_gap_qty >= 0.00)
);

CREATE INDEX idx_needs_list_event ON public.needs_list(event_id);
CREATE INDEX idx_needs_list_warehouse ON public.needs_list(warehouse_id);
CREATE INDEX idx_needs_list_status ON public.needs_list(status_code);
CREATE INDEX idx_needs_list_calc_date ON public.needs_list(calculation_dtime);

COMMENT ON TABLE public.needs_list IS 'Needs list header - system-generated replenishment recommendations';
COMMENT ON COLUMN public.needs_list.needs_list_no IS 'Unique identifier: NL-{EVENT_ID}-{WAREHOUSE_ID}-{YYYYMMDD}-{SEQ}';
COMMENT ON COLUMN public.needs_list.data_freshness_level IS 'Overall data confidence at calculation time: HIGH, MEDIUM, LOW';
COMMENT ON COLUMN public.needs_list.superseded_by_id IS 'If status=SUPERSEDED, points to the newer needs list';


-- ----------------------------------------------------------------------------
-- 2.4 NEW: needs_list_item - Individual item lines in needs list
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.needs_list_item (
    needs_list_item_id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    needs_list_id INTEGER NOT NULL REFERENCES public.needs_list(needs_list_id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES public.item(item_id),
    uom_code VARCHAR(25) NOT NULL,

    -- Calculation inputs (snapshot at calculation time)
    burn_rate NUMERIC(10,4) NOT NULL DEFAULT 0.0000,
    burn_rate_source VARCHAR(20) NOT NULL DEFAULT 'CALCULATED',
    available_stock NUMERIC(15,2) NOT NULL DEFAULT 0.00,
    reserved_qty NUMERIC(15,2) NOT NULL DEFAULT 0.00,
    inbound_transfer_qty NUMERIC(15,2) NOT NULL DEFAULT 0.00,
    inbound_donation_qty NUMERIC(15,2) NOT NULL DEFAULT 0.00,
    inbound_procurement_qty NUMERIC(15,2) NOT NULL DEFAULT 0.00,

    -- Calculation outputs
    required_qty NUMERIC(15,2) NOT NULL,
    coverage_qty NUMERIC(15,2) NOT NULL,
    gap_qty NUMERIC(15,2) NOT NULL,
    time_to_stockout_hours NUMERIC(10,2),
    severity_level VARCHAR(10) NOT NULL DEFAULT 'OK',

    -- Three Horizons allocation
    horizon_a_qty NUMERIC(15,2) NOT NULL DEFAULT 0.00,
    horizon_a_source_warehouse_id INTEGER REFERENCES public.warehouse(warehouse_id),
    horizon_b_qty NUMERIC(15,2) NOT NULL DEFAULT 0.00,
    horizon_c_qty NUMERIC(15,2) NOT NULL DEFAULT 0.00,

    -- Adjustments
    adjusted_qty NUMERIC(15,2),
    adjustment_reason VARCHAR(50),
    adjustment_notes VARCHAR(255),
    adjusted_by VARCHAR(20),
    adjusted_at TIMESTAMP(0) WITHOUT TIME ZONE,

    -- Fulfillment tracking
    fulfilled_qty NUMERIC(15,2) NOT NULL DEFAULT 0.00,
    fulfillment_status VARCHAR(20) NOT NULL DEFAULT 'PENDING',

    create_by_id VARCHAR(20) NOT NULL,
    create_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_by_id VARCHAR(20) NOT NULL,
    update_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    version_nbr INTEGER NOT NULL DEFAULT 1,

    CONSTRAINT c_nli_burn_rate CHECK (burn_rate >= 0.0000),
    CONSTRAINT c_nli_burn_source CHECK (burn_rate_source IN ('CALCULATED', 'BASELINE', 'MANUAL', 'ESTIMATED')),
    CONSTRAINT c_nli_quantities CHECK (
        available_stock >= 0.00 AND
        reserved_qty >= 0.00 AND
        inbound_transfer_qty >= 0.00 AND
        inbound_donation_qty >= 0.00 AND
        inbound_procurement_qty >= 0.00
    ),
    CONSTRAINT c_nli_severity CHECK (severity_level IN ('CRITICAL', 'WARNING', 'WATCH', 'OK')),
    CONSTRAINT c_nli_horizons CHECK (
        horizon_a_qty >= 0.00 AND
        horizon_b_qty >= 0.00 AND
        horizon_c_qty >= 0.00
    ),
    CONSTRAINT c_nli_adjustment_reason CHECK (
        adjustment_reason IS NULL OR adjustment_reason IN (
            'DEMAND_ADJUSTED', 'PARTIAL_COVERAGE', 'PRIORITY_CHANGE',
            'BUDGET_CONSTRAINT', 'SUPPLIER_LIMIT', 'OTHER'
        )
    ),
    CONSTRAINT c_nli_fulfillment_status CHECK (fulfillment_status IN (
        'PENDING', 'PARTIAL', 'FULFILLED', 'CANCELLED'
    )),
    CONSTRAINT uq_needs_list_item UNIQUE (needs_list_id, item_id)
);

CREATE INDEX idx_nli_needs_list ON public.needs_list_item(needs_list_id);
CREATE INDEX idx_nli_item ON public.needs_list_item(item_id);
CREATE INDEX idx_nli_severity ON public.needs_list_item(severity_level);

COMMENT ON TABLE public.needs_list_item IS 'Individual item lines within a needs list with calculation details';
COMMENT ON COLUMN public.needs_list_item.burn_rate_source IS 'How burn rate was determined: CALCULATED (from fulfillments), BASELINE (item default), MANUAL, ESTIMATED (stale data)';
COMMENT ON COLUMN public.needs_list_item.severity_level IS 'CRITICAL (<8h), WARNING (8-24h), WATCH (24-72h), OK (>72h)';


-- ----------------------------------------------------------------------------
-- 2.5 NEW: needs_list_audit - Audit trail for needs list changes
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.needs_list_audit (
    audit_id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    needs_list_id INTEGER NOT NULL REFERENCES public.needs_list(needs_list_id),
    needs_list_item_id INTEGER REFERENCES public.needs_list_item(needs_list_item_id),
    action_type VARCHAR(30) NOT NULL,
    field_name VARCHAR(50),
    old_value TEXT,
    new_value TEXT,
    reason_code VARCHAR(50),
    notes_text VARCHAR(500),
    actor_user_id VARCHAR(20) NOT NULL,
    action_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT c_nla_action CHECK (action_type IN (
        'CREATED', 'SUBMITTED', 'APPROVED', 'REJECTED', 'RETURNED',
        'QUANTITY_ADJUSTED', 'STATUS_CHANGED', 'HORIZON_CHANGED',
        'SUPERSEDED', 'CANCELLED', 'FULFILLED', 'COMMENT_ADDED'
    ))
);

CREATE INDEX idx_nla_needs_list ON public.needs_list_audit(needs_list_id);
CREATE INDEX idx_nla_action_date ON public.needs_list_audit(action_dtime);

COMMENT ON TABLE public.needs_list_audit IS 'Immutable audit trail for all needs list actions';


-- ----------------------------------------------------------------------------
-- 2.6 NEW: burn_rate_snapshot - Historical burn rate calculations
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.burn_rate_snapshot (
    snapshot_id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    warehouse_id INTEGER NOT NULL REFERENCES public.warehouse(warehouse_id),
    item_id INTEGER NOT NULL REFERENCES public.item(item_id),
    event_id INTEGER NOT NULL REFERENCES public.event(event_id),
    event_phase VARCHAR(15) NOT NULL,
    snapshot_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    demand_window_hours INTEGER NOT NULL,
    fulfillment_count INTEGER NOT NULL DEFAULT 0,
    total_fulfilled_qty NUMERIC(15,2) NOT NULL DEFAULT 0.00,
    burn_rate NUMERIC(10,4) NOT NULL,
    burn_rate_source VARCHAR(20) NOT NULL,
    data_freshness_level VARCHAR(10) NOT NULL,
    time_to_stockout_hours NUMERIC(10,2),
    available_stock_at_calc NUMERIC(15,2) NOT NULL,

    CONSTRAINT c_brs_phase CHECK (event_phase IN ('SURGE', 'STABILIZED', 'BASELINE')),
    CONSTRAINT c_brs_source CHECK (burn_rate_source IN ('CALCULATED', 'BASELINE', 'ESTIMATED')),
    CONSTRAINT c_brs_freshness CHECK (data_freshness_level IN ('HIGH', 'MEDIUM', 'LOW'))
);

CREATE INDEX idx_brs_warehouse_item ON public.burn_rate_snapshot(warehouse_id, item_id);
CREATE INDEX idx_brs_event ON public.burn_rate_snapshot(event_id);
CREATE INDEX idx_brs_snapshot_date ON public.burn_rate_snapshot(snapshot_dtime);

COMMENT ON TABLE public.burn_rate_snapshot IS 'Historical record of burn rate calculations for trending and analysis';


-- ----------------------------------------------------------------------------
-- 2.7 NEW: warehouse_sync_log - Track data freshness per warehouse
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.warehouse_sync_log (
    sync_id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    warehouse_id INTEGER NOT NULL REFERENCES public.warehouse(warehouse_id),
    sync_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sync_type VARCHAR(20) NOT NULL DEFAULT 'AUTO',
    sync_status VARCHAR(10) NOT NULL,
    items_synced INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    triggered_by VARCHAR(20),

    CONSTRAINT c_wsl_type CHECK (sync_type IN ('AUTO', 'MANUAL', 'SCHEDULED')),
    CONSTRAINT c_wsl_status CHECK (sync_status IN ('SUCCESS', 'PARTIAL', 'FAILED'))
);

CREATE INDEX idx_wsl_warehouse ON public.warehouse_sync_log(warehouse_id);
CREATE INDEX idx_wsl_sync_date ON public.warehouse_sync_log(sync_dtime);

COMMENT ON TABLE public.warehouse_sync_log IS 'Log of warehouse data synchronization events for freshness tracking';


-- ----------------------------------------------------------------------------
-- 2.8 NEW: procurement - Horizon C procurement orders
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.procurement (
    procurement_id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    procurement_no VARCHAR(30) NOT NULL UNIQUE,
    needs_list_id INTEGER REFERENCES public.needs_list(needs_list_id),
    event_id INTEGER NOT NULL REFERENCES public.event(event_id),
    target_warehouse_id INTEGER NOT NULL REFERENCES public.warehouse(warehouse_id),
    supplier_id INTEGER,  -- FK to supplier table if exists
    procurement_method VARCHAR(25) NOT NULL,
    po_number VARCHAR(50),
    total_value NUMERIC(15,2) NOT NULL DEFAULT 0.00,
    currency_code VARCHAR(10) NOT NULL DEFAULT 'JMD',
    status_code VARCHAR(20) NOT NULL DEFAULT 'DRAFT',
    approved_at TIMESTAMP(0) WITHOUT TIME ZONE,
    approved_by VARCHAR(20),
    approval_threshold_tier VARCHAR(10),
    shipped_at TIMESTAMP(0) WITHOUT TIME ZONE,
    expected_arrival TIMESTAMP(0) WITHOUT TIME ZONE,
    received_at TIMESTAMP(0) WITHOUT TIME ZONE,
    received_by VARCHAR(20),
    notes_text TEXT,
    create_by_id VARCHAR(20) NOT NULL,
    create_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_by_id VARCHAR(20) NOT NULL,
    update_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    version_nbr INTEGER NOT NULL DEFAULT 1,

    CONSTRAINT c_proc_method CHECK (procurement_method IN (
        'EMERGENCY_DIRECT', 'SINGLE_SOURCE', 'RFQ',
        'RESTRICTED_BIDDING', 'OPEN_TENDER', 'FRAMEWORK'
    )),
    CONSTRAINT c_proc_status CHECK (status_code IN (
        'DRAFT', 'PENDING_APPROVAL', 'APPROVED', 'REJECTED',
        'ORDERED', 'SHIPPED', 'PARTIAL_RECEIVED', 'RECEIVED', 'CANCELLED'
    )),
    CONSTRAINT c_proc_tier CHECK (approval_threshold_tier IS NULL OR
        approval_threshold_tier IN ('TIER_1', 'TIER_2', 'TIER_3', 'EMERGENCY'))
);

CREATE INDEX idx_proc_event ON public.procurement(event_id);
CREATE INDEX idx_proc_warehouse ON public.procurement(target_warehouse_id);
CREATE INDEX idx_proc_status ON public.procurement(status_code);
CREATE INDEX idx_proc_needs_list ON public.procurement(needs_list_id);

COMMENT ON TABLE public.procurement IS 'Procurement orders generated from Horizon C needs list items';
COMMENT ON COLUMN public.procurement.approval_threshold_tier IS 'GOJ procurement tier based on value thresholds';


-- ----------------------------------------------------------------------------
-- 2.9 NEW: procurement_item - Line items for procurement orders
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.procurement_item (
    procurement_item_id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    procurement_id INTEGER NOT NULL REFERENCES public.procurement(procurement_id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES public.item(item_id),
    needs_list_item_id INTEGER REFERENCES public.needs_list_item(needs_list_item_id),
    ordered_qty NUMERIC(15,2) NOT NULL,
    unit_price NUMERIC(12,2),
    line_total NUMERIC(15,2),
    uom_code VARCHAR(25) NOT NULL,
    received_qty NUMERIC(15,2) NOT NULL DEFAULT 0.00,
    status_code VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    create_by_id VARCHAR(20) NOT NULL,
    create_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_by_id VARCHAR(20) NOT NULL,
    update_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    version_nbr INTEGER NOT NULL DEFAULT 1,

    CONSTRAINT c_pi_qty CHECK (ordered_qty > 0.00),
    CONSTRAINT c_pi_received CHECK (received_qty >= 0.00 AND received_qty <= ordered_qty),
    CONSTRAINT c_pi_status CHECK (status_code IN ('PENDING', 'PARTIAL', 'RECEIVED', 'CANCELLED'))
);

CREATE INDEX idx_pi_procurement ON public.procurement_item(procurement_id);
CREATE INDEX idx_pi_item ON public.procurement_item(item_id);

COMMENT ON TABLE public.procurement_item IS 'Line items within a procurement order';


-- ----------------------------------------------------------------------------
-- 2.10 NEW: supplier - Supplier/vendor master (if not exists)
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.supplier (
    supplier_id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    supplier_code VARCHAR(20) NOT NULL UNIQUE,
    supplier_name VARCHAR(120) NOT NULL,
    contact_name VARCHAR(80),
    phone_no VARCHAR(20),
    email_text VARCHAR(100),
    address_text VARCHAR(255),
    parish_code CHAR(2),
    country_id INTEGER REFERENCES public.country(country_id),
    default_lead_time_days INTEGER DEFAULT 14,
    is_framework_supplier BOOLEAN DEFAULT FALSE,
    framework_contract_no VARCHAR(50),
    framework_expiry_date DATE,
    status_code CHAR(1) NOT NULL DEFAULT 'A',
    create_by_id VARCHAR(20) NOT NULL,
    create_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_by_id VARCHAR(20) NOT NULL,
    update_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    version_nbr INTEGER NOT NULL DEFAULT 1,

    CONSTRAINT c_supplier_status CHECK (status_code IN ('A', 'I')),
    CONSTRAINT c_supplier_code_upper CHECK (supplier_code = UPPER(supplier_code))
);

COMMENT ON TABLE public.supplier IS 'Supplier/vendor master for Horizon C procurement';
COMMENT ON COLUMN public.supplier.is_framework_supplier IS 'TRUE if supplier has a pre-negotiated framework agreement';


-- ----------------------------------------------------------------------------
-- 2.11 NEW: lead_time_config - Configurable lead times by route/supplier
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.lead_time_config (
    config_id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    horizon VARCHAR(1) NOT NULL,
    from_warehouse_id INTEGER REFERENCES public.warehouse(warehouse_id),
    to_warehouse_id INTEGER REFERENCES public.warehouse(warehouse_id),
    supplier_id INTEGER REFERENCES public.supplier(supplier_id),
    lead_time_hours INTEGER NOT NULL,
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    effective_from DATE NOT NULL DEFAULT CURRENT_DATE,
    effective_to DATE,
    create_by_id VARCHAR(20) NOT NULL,
    create_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_by_id VARCHAR(20) NOT NULL,
    update_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    version_nbr INTEGER NOT NULL DEFAULT 1,

    CONSTRAINT c_ltc_horizon CHECK (horizon IN ('A', 'B', 'C')),
    CONSTRAINT c_ltc_lead_time CHECK (lead_time_hours > 0),
    CONSTRAINT c_ltc_a_warehouses CHECK (
        (horizon = 'A' AND from_warehouse_id IS NOT NULL AND to_warehouse_id IS NOT NULL) OR
        (horizon != 'A')
    ),
    CONSTRAINT c_ltc_c_supplier CHECK (
        (horizon = 'C' AND supplier_id IS NOT NULL) OR
        (horizon != 'C')
    )
);

COMMENT ON TABLE public.lead_time_config IS 'Configurable lead times for Three Horizons: A (warehouse routes), B (donations), C (suppliers)';

-- ============================================================================
-- PART 3: FOREIGN KEY ADDITIONS
-- ============================================================================

-- Add FK from transfer to needs_list
ALTER TABLE public.transfer
ADD CONSTRAINT fk_transfer_needs_list
FOREIGN KEY (needs_list_id) REFERENCES public.needs_list(needs_list_id);

-- Add FK from procurement to supplier
ALTER TABLE public.procurement
ADD CONSTRAINT fk_procurement_supplier
FOREIGN KEY (supplier_id) REFERENCES public.supplier(supplier_id);


-- ============================================================================
-- PART 4: VIEWS FOR REPORTING
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 4.1 VIEW: v_stock_status - Current stock status with calculations
-- ----------------------------------------------------------------------------

CREATE OR REPLACE VIEW public.v_stock_status AS
SELECT
    w.warehouse_id,
    w.warehouse_name,
    w.warehouse_type,
    i.item_id,
    i.item_code,
    i.item_name,
    i.criticality_level,
    inv.usable_qty AS available_stock,
    inv.reserved_qty,
    COALESCE(i.min_stock_threshold, w.min_stock_threshold, 0) AS min_threshold,
    inv.usable_qty - COALESCE(i.min_stock_threshold, w.min_stock_threshold, 0) AS surplus_qty,
    w.last_sync_dtime,
    w.sync_status,
    CASE
        WHEN w.last_sync_dtime IS NULL THEN 'UNKNOWN'
        WHEN w.last_sync_dtime > NOW() - INTERVAL '2 hours' THEN 'HIGH'
        WHEN w.last_sync_dtime > NOW() - INTERVAL '6 hours' THEN 'MEDIUM'
        ELSE 'LOW'
    END AS data_freshness
FROM public.warehouse w
CROSS JOIN public.item i
LEFT JOIN public.inventory inv
    ON inv.item_id = i.item_id
    AND inv.inventory_id = w.warehouse_id
    -- inventory_id corresponds to warehouse_id for per-warehouse stock
WHERE w.status_code = 'A'
  AND i.status_code = 'A';

COMMENT ON VIEW public.v_stock_status IS 'Real-time stock status by warehouse and item with freshness indicators';


-- ----------------------------------------------------------------------------
-- 4.2 VIEW: v_inbound_stock - Confirmed inbound by source
-- ----------------------------------------------------------------------------

CREATE OR REPLACE VIEW public.v_inbound_stock AS
-- Transfers DISPATCHED
SELECT
    t.to_inventory_id AS warehouse_id,
    ti.item_id,
    'TRANSFER' AS source_type,
    SUM(ti.item_qty) AS inbound_qty,
    t.expected_arrival,
    t.transfer_id AS source_id
FROM public.transfer t
JOIN public.transfer_item ti ON t.transfer_id = ti.transfer_id
WHERE t.status_code = 'D'  -- DISPATCHED
  AND t.received_at IS NULL
GROUP BY t.to_inventory_id, ti.item_id, t.expected_arrival, t.transfer_id

UNION ALL

-- Donations CONFIRMED + IN-TRANSIT (need to add status tracking to donation)
SELECT
    dni.inventory_id AS warehouse_id,
    di.item_id,
    'DONATION' AS source_type,
    SUM(di.item_qty) AS inbound_qty,
    NULL AS expected_arrival,  -- Add expected_arrival to donation table
    d.donation_id AS source_id
FROM public.donation d
JOIN public.donation_item di ON d.donation_id = di.donation_id
JOIN public.dnintake dni ON d.donation_id = dni.donation_id
WHERE d.status_code = 'V'  -- VERIFIED but not yet fully received
  AND dni.status_code != 'V'  -- Intake not yet verified
GROUP BY dni.inventory_id, di.item_id, d.donation_id

UNION ALL

-- Procurement SHIPPED
SELECT
    p.target_warehouse_id AS warehouse_id,
    pi.item_id,
    'PROCUREMENT' AS source_type,
    SUM(pi.ordered_qty - pi.received_qty) AS inbound_qty,
    p.expected_arrival,
    p.procurement_id AS source_id
FROM public.procurement p
JOIN public.procurement_item pi ON p.procurement_id = pi.procurement_id
WHERE p.status_code = 'SHIPPED'
  AND pi.status_code != 'RECEIVED'
GROUP BY p.target_warehouse_id, pi.item_id, p.expected_arrival, p.procurement_id;

COMMENT ON VIEW public.v_inbound_stock IS 'Confirmed inbound stock meeting strict definition: DISPATCHED transfers, VERIFIED donations, SHIPPED procurement';


-- ============================================================================
-- PART 5: INDEXES FOR PERFORMANCE
-- ============================================================================

-- Composite indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_inventory_item_warehouse ON public.inventory(item_id);
CREATE INDEX IF NOT EXISTS idx_transfer_status_dest ON public.transfer(status_code, to_inventory_id);
CREATE INDEX IF NOT EXISTS idx_donation_status_event ON public.donation(status_code, event_id);


-- ============================================================================
-- PART 6: TRIGGERS (Optional - for audit automation)
-- ============================================================================

-- Trigger to auto-update warehouse sync_status based on last_sync_dtime
CREATE OR REPLACE FUNCTION public.update_warehouse_sync_status()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.last_sync_dtime IS NULL THEN
        NEW.sync_status := 'UNKNOWN';
    ELSIF NEW.last_sync_dtime > NOW() - INTERVAL '2 hours' THEN
        NEW.sync_status := 'ONLINE';
    ELSIF NEW.last_sync_dtime > NOW() - INTERVAL '6 hours' THEN
        NEW.sync_status := 'STALE';
    ELSE
        NEW.sync_status := 'OFFLINE';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_warehouse_sync_status
BEFORE INSERT OR UPDATE OF last_sync_dtime ON public.warehouse
FOR EACH ROW EXECUTE FUNCTION public.update_warehouse_sync_status();


-- Trigger to log phase changes to event_phase_history
CREATE OR REPLACE FUNCTION public.log_event_phase_change()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.current_phase IS DISTINCT FROM NEW.current_phase THEN
        INSERT INTO public.event_phase_history (
            event_id, from_phase, to_phase, changed_at, changed_by
        ) VALUES (
            NEW.event_id, OLD.current_phase, NEW.current_phase,
            COALESCE(NEW.phase_changed_at, NOW()),
            COALESCE(NEW.phase_changed_by, NEW.update_by_id)
        );
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_event_phase_change
AFTER UPDATE OF current_phase ON public.event
FOR EACH ROW EXECUTE FUNCTION public.log_event_phase_change();


-- ============================================================================
-- PART 7: DEFAULT DATA
-- ============================================================================

-- Insert default lead times
INSERT INTO public.lead_time_config (horizon, lead_time_hours, is_default, create_by_id)
VALUES
    ('A', 8, TRUE, 'SYSTEM'),    -- Transfers: 8 hours default
    ('B', 72, TRUE, 'SYSTEM'),   -- Donations: 72 hours (3 days) default
    ('C', 336, TRUE, 'SYSTEM')   -- Procurement: 336 hours (14 days) default
ON CONFLICT DO NOTHING;


-- ============================================================================
-- SUMMARY OF CHANGES
-- ============================================================================
/*
EXISTING TABLES ALTERED:
1. event - Added: current_phase, phase_changed_at, phase_changed_by
2. warehouse - Added: min_stock_threshold, last_sync_dtime, sync_status
3. item - Added: baseline_burn_rate, min_stock_threshold, criticality_level
4. transfer - Added: dispatched_at, dispatched_by, expected_arrival, received_at, received_by, needs_list_id

NEW TABLES CREATED:
1. event_phase_config - Phase-specific parameters per event
2. event_phase_history - Audit trail for phase transitions
3. needs_list - Main needs list header
4. needs_list_item - Individual item lines with calculations
5. needs_list_audit - Immutable audit trail
6. burn_rate_snapshot - Historical burn rate calculations
7. warehouse_sync_log - Data freshness tracking
8. procurement - Horizon C procurement orders
9. procurement_item - Procurement line items
10. supplier - Supplier/vendor master
11. lead_time_config - Configurable lead times

VIEWS CREATED:
1. v_stock_status - Real-time stock status with freshness
2. v_inbound_stock - Confirmed inbound by source type

TRIGGERS CREATED:
1. trg_warehouse_sync_status - Auto-update sync status
2. trg_event_phase_change - Log phase transitions
*/
