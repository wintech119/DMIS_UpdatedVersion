-- Ensure strict inbound view exists for replenishment preview/draft flows.
-- Template SQL: render with a schema value before execution
-- via the apply_replenishment_sql_migration management command.
-- Source: EP02_SUPPLY_REPLENISHMENT_SCHEMA.sql section 4.2.

CREATE OR REPLACE VIEW {schema}.v_inbound_stock AS
-- Transfers DISPATCHED and not yet received
SELECT
    t.to_inventory_id AS warehouse_id,
    ti.item_id,
    'TRANSFER' AS source_type,
    SUM(ti.item_qty) AS inbound_qty,
    t.expected_arrival,
    t.transfer_id AS source_id,
    COALESCE(t.dispatched_at, t.update_dtime, t.create_dtime) AS inbound_start_dtime,
    t.received_at AS inbound_end_dtime
FROM {schema}.transfer t
JOIN {schema}.transfer_item ti ON t.transfer_id = ti.transfer_id
WHERE COALESCE(t.dispatched_at, t.update_dtime, t.create_dtime) IS NOT NULL
GROUP BY
    t.to_inventory_id,
    ti.item_id,
    t.expected_arrival,
    t.transfer_id,
    COALESCE(t.dispatched_at, t.update_dtime, t.create_dtime),
    t.received_at

UNION ALL

-- Donations VERIFIED with intake still in transit
SELECT
    dni.inventory_id AS warehouse_id,
    di.item_id,
    'DONATION' AS source_type,
    SUM(di.item_qty) AS inbound_qty,
    NULL AS expected_arrival,
    d.donation_id AS source_id,
    COALESCE(d.verify_dtime, d.update_dtime, d.create_dtime) AS inbound_start_dtime,
    CASE
        WHEN dni.status_code = 'V' THEN COALESCE(dni.verify_dtime, dni.update_dtime, dni.create_dtime)
        ELSE NULL
    END AS inbound_end_dtime
FROM {schema}.donation d
JOIN {schema}.donation_item di ON d.donation_id = di.donation_id
JOIN {schema}.dnintake dni ON d.donation_id = dni.donation_id
WHERE d.status_code IN ('V', 'P')
GROUP BY
    dni.inventory_id,
    di.item_id,
    d.donation_id,
    COALESCE(d.verify_dtime, d.update_dtime, d.create_dtime),
    CASE
        WHEN dni.status_code = 'V' THEN COALESCE(dni.verify_dtime, dni.update_dtime, dni.create_dtime)
        ELSE NULL
    END

UNION ALL

-- Procurement SHIPPED and not fully received
SELECT
    p.target_warehouse_id AS warehouse_id,
    pi.item_id,
    'PROCUREMENT' AS source_type,
    SUM(pi.ordered_qty - pi.received_qty) AS inbound_qty,
    p.expected_arrival,
    p.procurement_id AS source_id,
    COALESCE(p.shipped_at, p.update_dtime, p.create_dtime) AS inbound_start_dtime,
    p.received_at AS inbound_end_dtime
FROM {schema}.procurement p
JOIN {schema}.procurement_item pi ON p.procurement_id = pi.procurement_id
WHERE COALESCE(p.shipped_at, p.update_dtime, p.create_dtime) IS NOT NULL
GROUP BY
    p.target_warehouse_id,
    pi.item_id,
    p.expected_arrival,
    p.procurement_id,
    COALESCE(p.shipped_at, p.update_dtime, p.create_dtime),
    p.received_at;

COMMENT ON VIEW {schema}.v_inbound_stock IS
    'Confirmed inbound stock with source-specific inbound start/end timestamps for as-of previews.';
