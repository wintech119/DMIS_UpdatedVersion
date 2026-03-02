from __future__ import annotations

import json
from datetime import datetime, timezone

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from replenishment import workflow_store_db
from replenishment.services import data_access


class Command(BaseCommand):
    help = "Seed one workflow-ready needs-list draft with CRITICAL/WARNING/WATCH line items for testing."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--actor", type=str, default="test-user", help="Actor user ID for created records.")
        parser.add_argument(
            "--event-id",
            type=int,
            default=None,
            help="Override event_id. Defaults to active event.",
        )
        parser.add_argument(
            "--warehouse-id",
            type=int,
            default=None,
            help="Override warehouse_id. Defaults to first active warehouse.",
        )

    def handle(self, *args, **options) -> None:
        self._assert_db_backed_workflow()

        actor = str(options.get("actor") or "test-user").strip() or "test-user"
        event_id = options.get("event_id")
        warehouse_id = options.get("warehouse_id")

        active_event = data_access.get_active_event()
        if event_id is None:
            if not active_event:
                raise CommandError("No active event found. Pass --event-id explicitly.")
            event_id = int(active_event["event_id"])

        warehouses = data_access.get_all_warehouses()
        if warehouse_id is None:
            if not warehouses:
                raise CommandError("No active warehouses found. Pass --warehouse-id explicitly.")
            warehouse_id = int(warehouses[0]["warehouse_id"])

        phase = "STABILIZED"
        if active_event and int(active_event.get("event_id", 0)) == int(event_id):
            phase = str(active_event.get("phase") or "STABILIZED").upper()

        seed_items = self._get_seed_items()
        if len(seed_items) < 3:
            raise CommandError("Need at least 3 items in item master table to seed CRITICAL/WARNING/WATCH test data.")

        timestamp = datetime.now(timezone.utc).isoformat()

        payload = {
            "event_id": int(event_id),
            "event_name": (active_event or {}).get("event_name") or f"Event {event_id}",
            "warehouse_id": int(warehouse_id),
            "warehouse_ids": [int(warehouse_id)],
            "warehouses": [int(warehouse_id)],
            "phase": phase,
            "as_of_datetime": timestamp,
            "planning_window_days": 7,
            "filters": {"seed": "workflow_test"},
            "selected_method": "A",
            "selected_item_keys": [
                f"{warehouse_id}_{seed_items[0]['item_id']}",
                f"{warehouse_id}_{seed_items[1]['item_id']}",
                f"{warehouse_id}_{seed_items[2]['item_id']}",
            ],
        }

        items = [
            {
                "item_id": seed_items[0]["item_id"],
                "item_name": seed_items[0]["item_name"],
                "uom_code": "EA",
                "available_qty": 5,
                "inbound_transfer_qty": 0,
                "inbound_donation_qty": 0,
                "inbound_procurement_qty": 0,
                "required_qty": 125,
                "coverage_qty": 5,
                "gap_qty": 120,
                "burn_rate_per_hour": 10,
                "time_to_stockout_hours": 4,
                "severity": "CRITICAL",
                "horizon": {
                    "A": {"recommended_qty": 40},
                    "B": {"recommended_qty": 30},
                    "C": {"recommended_qty": 50},
                },
            },
            {
                "item_id": seed_items[1]["item_id"],
                "item_name": seed_items[1]["item_name"],
                "uom_code": "EA",
                "available_qty": 18,
                "inbound_transfer_qty": 0,
                "inbound_donation_qty": 0,
                "inbound_procurement_qty": 0,
                "required_qty": 90,
                "coverage_qty": 18,
                "gap_qty": 72,
                "burn_rate_per_hour": 2,
                "time_to_stockout_hours": 16,
                "severity": "WARNING",
                "horizon": {
                    "A": {"recommended_qty": 25},
                    "B": {"recommended_qty": 20},
                    "C": {"recommended_qty": 27},
                },
            },
            {
                "item_id": seed_items[2]["item_id"],
                "item_name": seed_items[2]["item_name"],
                "uom_code": "EA",
                "available_qty": 30,
                "inbound_transfer_qty": 0,
                "inbound_donation_qty": 0,
                "inbound_procurement_qty": 0,
                "required_qty": 80,
                "coverage_qty": 30,
                "gap_qty": 50,
                "burn_rate_per_hour": 1,
                "time_to_stockout_hours": 48,
                "severity": "WATCH",
                "horizon": {
                    "A": {"recommended_qty": 20},
                    "B": {"recommended_qty": 10},
                    "C": {"recommended_qty": 20},
                },
            },
        ]

        warnings = ["seeded_test_data"]

        record = workflow_store_db.create_draft(payload, items, warnings, actor)

        summary = {
            "needs_list_id": record.get("needs_list_id"),
            "needs_list_no": record.get("needs_list_no"),
            "status": record.get("status"),
            "event_id": record.get("event_id"),
            "warehouse_id": record.get("warehouse_id"),
            "item_count": len(record.get("snapshot", {}).get("items", [])),
        }
        self.stdout.write(self.style.SUCCESS("Seeded needs-list workflow test draft."))
        self.stdout.write(json.dumps(summary, indent=2, sort_keys=True))

    def _assert_db_backed_workflow(self) -> None:
        engine = str(settings.DATABASES.get("default", {}).get("ENGINE", "")).lower()
        use_db = bool(getattr(settings, "AUTH_USE_DB_RBAC", False)) and "postgresql" in engine
        if not use_db:
            raise CommandError(
                "Refusing seed: DB-backed workflow store is not active (requires AUTH_USE_DB_RBAC + PostgreSQL)."
            )

    def _get_seed_items(self) -> list[dict[str, object]]:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT item_id, item_name
                FROM item
                ORDER BY item_id
                LIMIT 3
                """
            )
            rows = cursor.fetchall()

        return [
            {
                "item_id": int(row[0]),
                "item_name": str(row[1]) if row[1] else f"Item {row[0]}",
            }
            for row in rows
        ]
