from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand
from django.db import connection, transaction


class Command(BaseCommand):
    help = (
        "Enforce single-writer storage policy between item_location and batchlocation. "
        "Batched items must use batchlocation; non-batched items must use item_location."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Apply trigger/view DDL. Without this flag command runs in dry-run mode.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        apply_changes = bool(options.get("apply"))

        self.stdout.write("Location storage policy enforcement:")
        self.stdout.write("- item_location writes will be blocked for batched items")
        self.stdout.write("- batchlocation writes will be blocked for non-batched items")
        self.stdout.write("- derived view v_item_location_batched will be created/updated")
        self.stdout.write(f"- apply mode: {apply_changes}")

        if not apply_changes:
            self.stdout.write(
                self.style.WARNING("Dry-run only. Re-run with --apply to persist trigger policy.")
            )
            return

        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
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
                    """
                )

                cursor.execute("DROP TRIGGER IF EXISTS trg_enforce_item_location_policy ON item_location;")
                cursor.execute(
                    """
                    CREATE TRIGGER trg_enforce_item_location_policy
                    BEFORE INSERT OR UPDATE ON item_location
                    FOR EACH ROW
                    EXECUTE FUNCTION enforce_item_location_write_policy();
                    """
                )

                cursor.execute(
                    """
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
                    """
                )

                cursor.execute("DROP TRIGGER IF EXISTS trg_enforce_batchlocation_policy ON batchlocation;")
                cursor.execute(
                    """
                    CREATE TRIGGER trg_enforce_batchlocation_policy
                    BEFORE INSERT OR UPDATE ON batchlocation
                    FOR EACH ROW
                    EXECUTE FUNCTION enforce_batchlocation_write_policy();
                    """
                )

                cursor.execute(
                    """
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
                    """
                )

        self.stdout.write(self.style.SUCCESS("Storage policy triggers and view applied."))

