-- Criticality governance layer tables and event-close auto-expiry.
-- Template SQL: render with a schema value before execution
-- via the apply_replenishment_sql_migration management command
-- or the apply_items_criticality_layers convenience wrapper.
-- Source of truth: docs/requirements/items-source-of-truth.md (AC-1, AC-2, AC-3, AC-4, AC-10).

CREATE TABLE IF NOT EXISTS {schema}.event_item_criticality_override (
    override_id BIGSERIAL PRIMARY KEY,
    event_id INTEGER NOT NULL
        REFERENCES {schema}.event(event_id),
    item_id INTEGER NOT NULL
        REFERENCES {schema}.item(item_id),
    criticality_level VARCHAR(10) NOT NULL,
    reason_text VARCHAR(255),
    effective_from TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    effective_to TIMESTAMPTZ,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    status_code CHAR(1) NOT NULL DEFAULT 'A',
    create_by_id VARCHAR(20) NOT NULL,
    create_dtime TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    update_by_id VARCHAR(20) NOT NULL,
    update_dtime TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    version_nbr INTEGER NOT NULL DEFAULT 1,
    CONSTRAINT c_event_item_criticality_level
        CHECK (criticality_level IN ('CRITICAL', 'HIGH', 'NORMAL', 'LOW')),
    CONSTRAINT c_event_item_criticality_status
        CHECK (status_code IN ('A', 'I')),
    CONSTRAINT c_event_item_criticality_effective_window
        CHECK (effective_to IS NULL OR effective_to > effective_from)
);

CREATE INDEX IF NOT EXISTS idx_event_item_criticality_event_item
    ON {schema}.event_item_criticality_override(event_id, item_id);

CREATE INDEX IF NOT EXISTS idx_event_item_criticality_active
    ON {schema}.event_item_criticality_override(event_id, item_id, effective_from DESC)
    WHERE is_active = TRUE;

CREATE UNIQUE INDEX IF NOT EXISTS ux_event_item_criticality_one_open_row
    ON {schema}.event_item_criticality_override(event_id, item_id)
    WHERE is_active = TRUE AND effective_to IS NULL;


CREATE TABLE IF NOT EXISTS {schema}.hazard_item_criticality (
    hazard_item_criticality_id BIGSERIAL PRIMARY KEY,
    event_type VARCHAR(16) NOT NULL,
    item_id INTEGER NOT NULL
        REFERENCES {schema}.item(item_id),
    criticality_level VARCHAR(10) NOT NULL,
    reason_text VARCHAR(255),
    effective_from TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    effective_to TIMESTAMPTZ,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    status_code CHAR(1) NOT NULL DEFAULT 'A',
    approval_status VARCHAR(20) NOT NULL DEFAULT 'DRAFT',
    submitted_by_id VARCHAR(20),
    submitted_dtime TIMESTAMPTZ,
    approved_by_id VARCHAR(20),
    approved_dtime TIMESTAMPTZ,
    rejected_by_id VARCHAR(20),
    rejected_dtime TIMESTAMPTZ,
    rejected_reason VARCHAR(255),
    create_by_id VARCHAR(20) NOT NULL,
    create_dtime TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    update_by_id VARCHAR(20) NOT NULL,
    update_dtime TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    version_nbr INTEGER NOT NULL DEFAULT 1,
    CONSTRAINT c_hazard_item_criticality_level
        CHECK (criticality_level IN ('CRITICAL', 'HIGH', 'NORMAL', 'LOW')),
    CONSTRAINT c_hazard_item_criticality_status
        CHECK (status_code IN ('A', 'I')),
    CONSTRAINT c_hazard_item_criticality_approval_status
        CHECK (approval_status IN ('DRAFT', 'PENDING_APPROVAL', 'APPROVED', 'REJECTED')),
    CONSTRAINT c_hazard_item_criticality_effective_window
        CHECK (effective_to IS NULL OR effective_to > effective_from),
    CONSTRAINT c_hazard_item_criticality_event_type
        CHECK (
            event_type IN (
                'STORM',
                'HURRICANE',
                'TORNADO',
                'FLOOD',
                'TSUNAMI',
                'FIRE',
                'EARTHQUAKE',
                'WAR',
                'EPIDEMIC',
                'ADHOC'
            )
        )
);

CREATE INDEX IF NOT EXISTS idx_hazard_item_criticality_event_type_item
    ON {schema}.hazard_item_criticality(event_type, item_id);

CREATE INDEX IF NOT EXISTS idx_hazard_item_criticality_approved
    ON {schema}.hazard_item_criticality(event_type, item_id, effective_from DESC)
    WHERE is_active = TRUE AND approval_status = 'APPROVED';

CREATE UNIQUE INDEX IF NOT EXISTS ux_hazard_item_criticality_one_approved_row
    ON {schema}.hazard_item_criticality(event_type, item_id)
    WHERE approval_status = 'APPROVED'
      AND is_active = TRUE
      AND effective_to IS NULL;


CREATE OR REPLACE FUNCTION {schema}.fn_expire_event_item_criticality_override_on_event_close()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF UPPER(COALESCE(NEW.status_code, '')) IN ('C', 'CLOSED')
       AND UPPER(COALESCE(OLD.status_code, '')) NOT IN ('C', 'CLOSED') THEN
        UPDATE {schema}.event_item_criticality_override AS eico
        SET
            is_active = FALSE,
            status_code = 'I',
            effective_to = COALESCE(eico.effective_to, NOW()),
            update_by_id = COALESCE(NULLIF(NEW.update_by_id, ''), 'SYSTEM'),
            update_dtime = NOW(),
            version_nbr = eico.version_nbr + 1
        WHERE event_id = NEW.event_id
          AND is_active = TRUE;
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS tr_event_close_expire_item_criticality_override ON {schema}.event;

CREATE TRIGGER tr_event_close_expire_item_criticality_override
AFTER UPDATE OF status_code
ON {schema}.event
FOR EACH ROW
EXECUTE FUNCTION {schema}.fn_expire_event_item_criticality_override_on_event_close();

UPDATE {schema}.event_item_criticality_override eico
SET
    is_active = FALSE,
    status_code = 'I',
    effective_to = COALESCE(eico.effective_to, NOW()),
    update_dtime = NOW(),
    version_nbr = eico.version_nbr + 1
FROM {schema}.event e
WHERE eico.event_id = e.event_id
  AND eico.is_active = TRUE
  AND UPPER(COALESCE(e.status_code, '')) IN ('C', 'CLOSED');

