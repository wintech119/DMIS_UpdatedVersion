ALTER TABLE {schema}.needs_list_allocation_line
    ALTER COLUMN allocated_qty TYPE NUMERIC(15, 4)
    USING allocated_qty::NUMERIC(15, 4);

ALTER TABLE {schema}.needs_list_allocation_line
    ALTER COLUMN allocated_qty SET DEFAULT 0.0000;
