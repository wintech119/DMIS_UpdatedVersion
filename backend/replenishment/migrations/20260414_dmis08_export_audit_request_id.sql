ALTER TABLE {schema}.needs_list_audit
    ADD COLUMN IF NOT EXISTS request_id VARCHAR(128);

CREATE INDEX IF NOT EXISTS ix_needs_list_audit_request_id
    ON {schema}.needs_list_audit(request_id);

ALTER TABLE {schema}.needs_list_audit
    DROP CONSTRAINT IF EXISTS c_nla_action;

ALTER TABLE {schema}.needs_list_audit
    ADD CONSTRAINT c_nla_action
    CHECK (
        action_type IN (
            'CREATED',
            'SUBMITTED',
            'APPROVED',
            'REJECTED',
            'RETURNED',
            'QUANTITY_ADJUSTED',
            'STATUS_CHANGED',
            'HORIZON_CHANGED',
            'SUPERSEDED',
            'CANCELLED',
            'FULFILLED',
            'ALLOCATION_COMMITTED',
            'ALLOCATION_OVERRIDE_SUBMITTED',
            'ALLOCATION_OVERRIDE_APPROVED',
            'ALLOCATION_RELEASED',
            'DISPATCHED',
            'COMMENT_ADDED',
            'EXPORT_GENERATED'
        )
    );
