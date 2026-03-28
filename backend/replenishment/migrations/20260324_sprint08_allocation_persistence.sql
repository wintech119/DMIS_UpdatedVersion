-- Sprint 08 allocation and dispatch persistence layer.
-- Template SQL: render with a schema value before execution
-- via the apply_replenishment_sql_migration management command.

CREATE TABLE IF NOT EXISTS {schema}.needs_list_execution_link (
    needs_list_id INTEGER PRIMARY KEY
        REFERENCES {schema}.needs_list(needs_list_id)
        ON DELETE CASCADE,
    reliefrqst_id INTEGER UNIQUE,
    reliefpkg_id INTEGER UNIQUE,
    selected_method VARCHAR(20),
    execution_status VARCHAR(35) NOT NULL DEFAULT 'PREPARING',
    prepared_at TIMESTAMPTZ,
    prepared_by VARCHAR(20),
    committed_at TIMESTAMPTZ,
    committed_by VARCHAR(20),
    override_requested_at TIMESTAMPTZ,
    override_requested_by VARCHAR(20),
    override_approved_at TIMESTAMPTZ,
    override_approved_by VARCHAR(20),
    dispatched_at TIMESTAMPTZ,
    dispatched_by VARCHAR(20),
    received_at TIMESTAMPTZ,
    received_by VARCHAR(20),
    cancelled_at TIMESTAMPTZ,
    cancelled_by VARCHAR(20),
    waybill_no VARCHAR(50) UNIQUE,
    waybill_payload_json JSONB,
    create_by_id VARCHAR(20) NOT NULL,
    create_dtime TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    update_by_id VARCHAR(20) NOT NULL,
    update_dtime TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    version_nbr INTEGER NOT NULL DEFAULT 1,
    CONSTRAINT c_needs_list_execution_link_selected_method
        CHECK (selected_method IS NULL OR selected_method IN ('FEFO', 'FIFO', 'MIXED', 'MANUAL')),
    CONSTRAINT c_needs_list_execution_link_status
        CHECK (
            execution_status IN (
                'PREPARING',
                'PENDING_OVERRIDE_APPROVAL',
                'COMMITTED',
                'DISPATCHED',
                'RECEIVED',
                'CANCELLED'
            )
        )
);

CREATE INDEX IF NOT EXISTS idx_needs_list_execution_link_status
    ON {schema}.needs_list_execution_link(execution_status);


CREATE TABLE IF NOT EXISTS {schema}.needs_list_allocation_line (
    allocation_line_id BIGSERIAL PRIMARY KEY,
    needs_list_id INTEGER NOT NULL
        REFERENCES {schema}.needs_list(needs_list_id)
        ON DELETE CASCADE,
    needs_list_item_id INTEGER
        REFERENCES {schema}.needs_list_item(needs_list_item_id)
        ON DELETE SET NULL,
    item_id INTEGER NOT NULL,
    inventory_id INTEGER NOT NULL,
    batch_id INTEGER NOT NULL,
    uom_code VARCHAR(25) NOT NULL,
    source_type VARCHAR(20) NOT NULL,
    source_record_id INTEGER,
    allocated_qty NUMERIC(15, 4) NOT NULL DEFAULT 0.0000,
    allocation_rank INTEGER NOT NULL DEFAULT 1,
    rule_bypass_flag BOOLEAN NOT NULL DEFAULT FALSE,
    override_reason_code VARCHAR(50),
    override_note VARCHAR(500),
    supervisor_approved_by VARCHAR(20),
    supervisor_approved_at TIMESTAMPTZ,
    create_by_id VARCHAR(20) NOT NULL,
    create_dtime TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    update_by_id VARCHAR(20) NOT NULL,
    update_dtime TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    version_nbr INTEGER NOT NULL DEFAULT 1,
    CONSTRAINT uq_needs_list_allocation_line_identity
        UNIQUE (needs_list_id, item_id, inventory_id, batch_id),
    CONSTRAINT c_needs_list_allocation_line_source_type
        CHECK (source_type IN ('ON_HAND', 'TRANSFER', 'DONATION', 'PROCUREMENT')),
    CONSTRAINT c_needs_list_allocation_line_qty_nonnegative
        CHECK (allocated_qty >= 0),
    CONSTRAINT c_needs_list_allocation_line_rank_positive
        CHECK (allocation_rank >= 1)
);

CREATE INDEX IF NOT EXISTS idx_needs_list_allocation_line_needs_list_rank
    ON {schema}.needs_list_allocation_line(needs_list_id, allocation_rank);

CREATE INDEX IF NOT EXISTS idx_needs_list_allocation_line_needs_list_item
    ON {schema}.needs_list_allocation_line(needs_list_id, item_id);

CREATE INDEX IF NOT EXISTS idx_needs_list_allocation_line_needs_list_item_id
    ON {schema}.needs_list_allocation_line(needs_list_item_id);

CREATE INDEX IF NOT EXISTS idx_needs_list_allocation_line_inventory_batch
    ON {schema}.needs_list_allocation_line(inventory_id, batch_id);

CREATE INDEX IF NOT EXISTS idx_needs_list_allocation_line_source
    ON {schema}.needs_list_allocation_line(source_type, source_record_id);

CREATE INDEX IF NOT EXISTS idx_needs_list_allocation_line_rule_bypass
    ON {schema}.needs_list_allocation_line(rule_bypass_flag);
