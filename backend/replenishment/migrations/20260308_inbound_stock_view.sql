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
    t.transfer_id AS source_id
FROM {schema}.transfer t
JOIN {schema}.transfer_item ti ON t.transfer_id = ti.transfer_id
WHERE t.status_code = 'D'
  AND t.received_at IS NULL
GROUP BY t.to_inventory_id, ti.item_id, t.expected_arrival, t.transfer_id

UNION ALL

-- Donations VERIFIED with intake still in transit
SELECT
    dni.inventory_id AS warehouse_id,
    di.item_id,
    'DONATION' AS source_type,
    SUM(di.item_qty) AS inbound_qty,
    NULL AS expected_arrival,
    d.donation_id AS source_id
FROM {schema}.donation d
JOIN {schema}.donation_item di ON d.donation_id = di.donation_id
JOIN {schema}.dnintake dni ON d.donation_id = dni.donation_id
WHERE d.status_code = 'V'
  AND dni.status_code != 'V'
GROUP BY dni.inventory_id, di.item_id, d.donation_id

UNION ALL

-- Procurement SHIPPED and not fully received
SELECT
    p.target_warehouse_id AS warehouse_id,
    pi.item_id,
    'PROCUREMENT' AS source_type,
    SUM(pi.ordered_qty - pi.received_qty) AS inbound_qty,
    p.expected_arrival,
    p.procurement_id AS source_id
FROM {schema}.procurement p
JOIN {schema}.procurement_item pi ON p.procurement_id = pi.procurement_id
WHERE p.status_code = 'SHIPPED'
  AND pi.status_code != 'RECEIVED'
GROUP BY p.target_warehouse_id, pi.item_id, p.expected_arrival, p.procurement_id;

COMMENT ON VIEW {schema}.v_inbound_stock IS
    'Confirmed inbound stock meeting strict definition: DISPATCHED transfers, VERIFIED donations, SHIPPED procurement';
