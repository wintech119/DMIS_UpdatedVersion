SET search_path TO {schema}, public;

CREATE OR REPLACE FUNCTION enforce_item_location_write_policy()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_is_batched boolean;
BEGIN
    SELECT COALESCE(i.is_batched_flag, false)
      INTO v_is_batched
      FROM item i
     WHERE i.item_id = NEW.item_id
     LIMIT 1;

    IF COALESCE(v_is_batched, false) THEN
        RAISE EXCEPTION
            'item_location policy violation: item_id % is batch-tracked; use batchlocation.',
            NEW.item_id;
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_enforce_item_location_policy ON item_location;
CREATE TRIGGER trg_enforce_item_location_policy
BEFORE INSERT OR UPDATE ON item_location
FOR EACH ROW
EXECUTE FUNCTION enforce_item_location_write_policy();

CREATE OR REPLACE FUNCTION enforce_batchlocation_write_policy()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_is_batched boolean;
BEGIN
    SELECT COALESCE(i.is_batched_flag, false)
      INTO v_is_batched
      FROM itembatch ib
      JOIN item i
        ON i.item_id = ib.item_id
     WHERE ib.inventory_id = NEW.inventory_id
       AND ib.batch_id = NEW.batch_id
     LIMIT 1;

    IF NOT COALESCE(v_is_batched, false) THEN
        RAISE EXCEPTION
            'batchlocation policy violation: batch_id % is not batch-tracked; use item_location.',
            NEW.batch_id;
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_enforce_batchlocation_policy ON batchlocation;
CREATE TRIGGER trg_enforce_batchlocation_policy
BEFORE INSERT OR UPDATE ON batchlocation
FOR EACH ROW
EXECUTE FUNCTION enforce_batchlocation_write_policy();

DROP VIEW IF EXISTS v_item_location_batched;
CREATE VIEW v_item_location_batched AS
SELECT
    il.inventory_id,
    il.item_id,
    il.location_id,
    NULL::integer AS batch_id,
    FALSE AS is_batched_flag
FROM item_location il
UNION ALL
SELECT
    bl.inventory_id,
    ib.item_id,
    bl.location_id,
    bl.batch_id,
    TRUE AS is_batched_flag
FROM batchlocation bl
JOIN itembatch ib
  ON ib.inventory_id = bl.inventory_id
 AND ib.batch_id = bl.batch_id;
