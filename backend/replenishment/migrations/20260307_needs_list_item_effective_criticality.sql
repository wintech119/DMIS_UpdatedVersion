-- Add effective criticality traceability fields to needs_list_item.
-- Template SQL: render with a schema value before execution
-- via the apply_replenishment_sql_migration management command.
-- Source of truth: docs/requirements/items-source-of-truth.md (AC-1, AC-3, AC-10).

ALTER TABLE {schema}.needs_list_item
    ADD COLUMN IF NOT EXISTS effective_criticality_level VARCHAR(10) NOT NULL DEFAULT 'NORMAL',
    ADD COLUMN IF NOT EXISTS effective_criticality_source VARCHAR(30) NOT NULL DEFAULT 'ITEM_DEFAULT';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'c_needs_list_item_effective_criticality_level'
    ) THEN
        ALTER TABLE {schema}.needs_list_item
            ADD CONSTRAINT c_needs_list_item_effective_criticality_level
            CHECK (effective_criticality_level IN ('CRITICAL', 'HIGH', 'NORMAL', 'LOW'));
    END IF;
END$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'c_needs_list_item_effective_criticality_source'
    ) THEN
        ALTER TABLE {schema}.needs_list_item
            ADD CONSTRAINT c_needs_list_item_effective_criticality_source
            CHECK (effective_criticality_source IN ('EVENT_OVERRIDE', 'HAZARD_TYPE_DEFAULT', 'ITEM_DEFAULT'));
    END IF;
END$$;

UPDATE {schema}.needs_list_item nli
SET
    effective_criticality_level = COALESCE(i.criticality_level, 'NORMAL'),
    effective_criticality_source = 'ITEM_DEFAULT'
FROM {schema}.item i
WHERE nli.item_id = i.item_id
  AND (
      nli.effective_criticality_level IS NULL
      OR nli.effective_criticality_source IS NULL
  );
