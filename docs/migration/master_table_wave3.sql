-- DMIS Master Table Wave 3 (Boundary Hardening + MVP Scaffolding)
-- Generated: 2026-03-03
-- Notes:
--   1) This SQL mirrors the changes applied via management commands.
--   2) Run in a controlled window with backup/snapshot.

BEGIN;

-- ---------------------------------------------------------------------------
-- A) Single-writer policy enforcement
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION enforce_item_location_write_policy()
RETURNS TRIGGER AS $$
DECLARE
    v_is_batched BOOLEAN;
BEGIN
    SELECT i.is_batched_flag
    INTO v_is_batched
    FROM item i
    WHERE i.item_id = NEW.item_id
    LIMIT 1;

    IF v_is_batched IS NULL THEN
        RAISE EXCEPTION
            'item_location policy: unable to resolve item_id %.',
            NEW.item_id;
    END IF;

    IF v_is_batched THEN
        RAISE EXCEPTION
            'item_location policy violation: item_id % is batch-tracked; use batchlocation.',
            NEW.item_id;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_enforce_item_location_policy ON item_location;
CREATE TRIGGER trg_enforce_item_location_policy
BEFORE INSERT OR UPDATE ON item_location
FOR EACH ROW
EXECUTE FUNCTION enforce_item_location_write_policy();

CREATE OR REPLACE FUNCTION enforce_batchlocation_write_policy()
RETURNS TRIGGER AS $$
DECLARE
    v_item_id INTEGER;
    v_is_batched BOOLEAN;
BEGIN
    SELECT ib.item_id
    INTO v_item_id
    FROM itembatch ib
    WHERE ib.batch_id = NEW.batch_id
      AND ib.inventory_id = NEW.inventory_id
    LIMIT 1;

    IF v_item_id IS NULL THEN
        RAISE EXCEPTION
            'batchlocation policy: unable to resolve itembatch for inventory_id %, batch_id %.',
            NEW.inventory_id, NEW.batch_id;
    END IF;

    SELECT i.is_batched_flag
    INTO v_is_batched
    FROM item i
    WHERE i.item_id = v_item_id
    LIMIT 1;

    IF v_is_batched IS NULL THEN
        RAISE EXCEPTION
            'batchlocation policy: unable to resolve item for batch_id %.',
            NEW.batch_id;
    END IF;

    IF NOT v_is_batched THEN
        RAISE EXCEPTION
            'batchlocation policy violation: item_id % is not batch-tracked; use item_location.',
            v_item_id;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_enforce_batchlocation_policy ON batchlocation;
CREATE TRIGGER trg_enforce_batchlocation_policy
BEFORE INSERT OR UPDATE ON batchlocation
FOR EACH ROW
EXECUTE FUNCTION enforce_batchlocation_write_policy();

CREATE OR REPLACE VIEW v_item_location_batched AS
SELECT
    ib.inventory_id,
    ib.item_id,
    bl.location_id,
    COUNT(*) AS batch_count,
    SUM(COALESCE(ib.usable_qty, 0)) AS usable_qty,
    SUM(COALESCE(ib.reserved_qty, 0)) AS reserved_qty,
    SUM(COALESCE(ib.defective_qty, 0)) AS defective_qty,
    SUM(COALESCE(ib.expired_qty, 0)) AS expired_qty
FROM batchlocation bl
JOIN itembatch ib
    ON ib.batch_id = bl.batch_id
   AND ib.inventory_id = bl.inventory_id
GROUP BY ib.inventory_id, ib.item_id, bl.location_id;

-- ---------------------------------------------------------------------------
-- B) Missing MVP master tables scaffolding
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS role_scope_policy (
    policy_id SERIAL PRIMARY KEY,
    role_id INTEGER NOT NULL REFERENCES role(id),
    scope_type VARCHAR(20) NOT NULL
        CHECK (scope_type IN ('TENANT', 'WAREHOUSE', 'NATIONAL', 'SYSTEM')),
    tenant_id INTEGER NULL REFERENCES tenant(tenant_id),
    warehouse_id INTEGER NULL REFERENCES warehouse(warehouse_id),
    can_read_all_tenants BOOLEAN NOT NULL DEFAULT FALSE,
    can_act_cross_tenant BOOLEAN NOT NULL DEFAULT FALSE,
    status_code CHAR(1) NOT NULL DEFAULT 'A' CHECK (status_code IN ('A', 'I')),
    create_by_id VARCHAR(20) NOT NULL DEFAULT 'SYSTEM',
    create_dtime TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_by_id VARCHAR(20) NOT NULL DEFAULT 'SYSTEM',
    update_dtime TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    version_nbr INTEGER NOT NULL DEFAULT 1
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_role_scope_policy_scope
ON role_scope_policy (role_id, scope_type, tenant_id, warehouse_id);

CREATE TABLE IF NOT EXISTS approval_reason_code (
    reason_code VARCHAR(40) PRIMARY KEY,
    reason_label VARCHAR(120) NOT NULL,
    workflow_stage VARCHAR(30) NOT NULL,
    outcome_type VARCHAR(20) NOT NULL,
    requires_comment BOOLEAN NOT NULL DEFAULT TRUE,
    status_code CHAR(1) NOT NULL DEFAULT 'A' CHECK (status_code IN ('A', 'I')),
    create_by_id VARCHAR(20) NOT NULL DEFAULT 'SYSTEM',
    create_dtime TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_by_id VARCHAR(20) NOT NULL DEFAULT 'SYSTEM',
    update_dtime TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    version_nbr INTEGER NOT NULL DEFAULT 1
);
INSERT INTO approval_reason_code (
    reason_code, reason_label, workflow_stage, outcome_type, requires_comment
) VALUES
    ('NEEDS_CLARIFICATION', 'Needs Clarification', 'REVIEW', 'RETURN', TRUE),
    ('POLICY_NONCOMPLIANT', 'Policy Noncompliant', 'REVIEW', 'REJECT', TRUE),
    ('INSUFFICIENT_BUDGET', 'Insufficient Budget', 'REVIEW', 'REJECT', TRUE),
    ('HIGH_IMPACT_ESCALATION', 'High Impact Escalation', 'REVIEW', 'ESCALATE', TRUE),
    ('DUPLICATE_SUBMISSION', 'Duplicate Submission', 'SUBMISSION', 'CANCEL', TRUE)
ON CONFLICT (reason_code) DO NOTHING;

CREATE TABLE IF NOT EXISTS event_severity_profile (
    profile_id SERIAL PRIMARY KEY,
    event_id INTEGER NOT NULL REFERENCES event(event_id),
    severity_level VARCHAR(20) NOT NULL
        CHECK (severity_level IN ('LOW', 'MODERATE', 'HIGH', 'SEVERE', 'EXTREME')),
    impact_score NUMERIC(5, 2) NULL,
    response_mode VARCHAR(30) NULL,
    notes_text TEXT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    create_by_id VARCHAR(20) NOT NULL DEFAULT 'SYSTEM',
    create_dtime TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_by_id VARCHAR(20) NOT NULL DEFAULT 'SYSTEM',
    update_dtime TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    version_nbr INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_event_severity_profile_event
ON event_severity_profile (event_id, is_active);

CREATE TABLE IF NOT EXISTS resource_capability_ref (
    capability_code VARCHAR(40) PRIMARY KEY,
    capability_name VARCHAR(120) NOT NULL,
    capability_type VARCHAR(40) NOT NULL,
    description_text TEXT NULL,
    status_code CHAR(1) NOT NULL DEFAULT 'A' CHECK (status_code IN ('A', 'I')),
    create_by_id VARCHAR(20) NOT NULL DEFAULT 'SYSTEM',
    create_dtime TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_by_id VARCHAR(20) NOT NULL DEFAULT 'SYSTEM',
    update_dtime TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    version_nbr INTEGER NOT NULL DEFAULT 1
);
INSERT INTO resource_capability_ref (
    capability_code, capability_name, capability_type, description_text
) VALUES
    ('WAREHOUSING', 'Warehousing Capacity', 'LOGISTICS', 'Storage and handling capacity'),
    ('TRANSPORT', 'Transport Capacity', 'LOGISTICS', 'Vehicle and routing capacity'),
    ('PROCUREMENT', 'Procurement Capacity', 'SUPPLY', 'Procurement process throughput'),
    ('DISTRIBUTION', 'Distribution Capacity', 'OPERATIONS', 'Last-mile distribution capability')
ON CONFLICT (capability_code) DO NOTHING;

CREATE TABLE IF NOT EXISTS allocation_priority_rule (
    priority_rule_id SERIAL PRIMARY KEY,
    rule_name VARCHAR(120) NOT NULL,
    event_phase_code VARCHAR(20) NOT NULL REFERENCES ref_event_phase(phase_code),
    criticality_weight NUMERIC(5, 2) NOT NULL DEFAULT 0,
    urgency_weight NUMERIC(5, 2) NOT NULL DEFAULT 0,
    population_weight NUMERIC(5, 2) NOT NULL DEFAULT 0,
    chronology_weight NUMERIC(5, 2) NOT NULL DEFAULT 0,
    tenant_id INTEGER NULL REFERENCES tenant(tenant_id),
    effective_date DATE NOT NULL DEFAULT CURRENT_DATE,
    expiry_date DATE NULL,
    status_code CHAR(1) NOT NULL DEFAULT 'A' CHECK (status_code IN ('A', 'I')),
    create_by_id VARCHAR(20) NOT NULL DEFAULT 'SYSTEM',
    create_dtime TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_by_id VARCHAR(20) NOT NULL DEFAULT 'SYSTEM',
    update_dtime TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    version_nbr INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_allocation_priority_rule_tenant_phase
ON allocation_priority_rule (tenant_id, event_phase_code, effective_date);

CREATE TABLE IF NOT EXISTS tenant_access_policy (
    policy_id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenant(tenant_id),
    allow_neoc_actions BOOLEAN NOT NULL DEFAULT FALSE,
    allow_cross_tenant_read BOOLEAN NOT NULL DEFAULT FALSE,
    allow_cross_tenant_write BOOLEAN NOT NULL DEFAULT FALSE,
    policy_source VARCHAR(40) NULL,
    effective_date DATE NOT NULL DEFAULT CURRENT_DATE,
    expiry_date DATE NULL,
    status_code CHAR(1) NOT NULL DEFAULT 'A' CHECK (status_code IN ('A', 'I')),
    create_by_id VARCHAR(20) NOT NULL DEFAULT 'SYSTEM',
    create_dtime TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_by_id VARCHAR(20) NOT NULL DEFAULT 'SYSTEM',
    update_dtime TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    version_nbr INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_tenant_access_policy_active
ON tenant_access_policy (tenant_id, effective_date, expiry_date, status_code);

COMMIT;

