from __future__ import annotations

from contextlib import nullcontext
from io import StringIO
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from replenishment.services import location_storage


class LocationAssignmentApiTests(TestCase):
    ENDPOINT = "/api/v1/replenishment/inventory/location-assignment"

    def setUp(self) -> None:
        self.client = APIClient()

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="viewer-1",
        DEV_AUTH_ROLES=["EXECUTIVE"],
        DEV_AUTH_PERMISSIONS=["replenishment.needs_list.preview"],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    def test_assignment_requires_write_permission(self) -> None:
        response = self.client.post(
            self.ENDPOINT,
            {"item_id": 1, "inventory_id": 2, "location_id": 3},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="ops-user",
        DEV_AUTH_ROLES=["LOGISTICS"],
        DEV_AUTH_PERMISSIONS=["replenishment.needs_list.execute"],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch("replenishment.views.location_storage.assign_storage_location")
    def test_assignment_calls_service_for_execute_permission(self, mock_assign) -> None:
        mock_assign.return_value = {
            "storage_table": "item_location",
            "created": True,
            "item_id": 10,
            "inventory_id": 2,
            "location_id": 7,
            "batch_id": None,
        }

        response = self.client.post(
            self.ENDPOINT,
            {"item_id": 10, "inventory_id": 2, "location_id": 7},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        mock_assign.assert_called_once_with(
            item_id=10,
            inventory_id=2,
            location_id=7,
            batch_id=None,
            actor_id="ops-user",
        )

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="md-admin",
        DEV_AUTH_ROLES=["SYSTEM_ADMINISTRATOR"],
        DEV_AUTH_PERMISSIONS=["masterdata.edit"],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch("replenishment.views.location_storage.assign_storage_location")
    def test_assignment_allows_masterdata_edit_permission(self, mock_assign) -> None:
        mock_assign.return_value = {
            "storage_table": "item_location",
            "created": False,
            "item_id": 11,
            "inventory_id": 2,
            "location_id": 8,
            "batch_id": None,
        }

        response = self.client.post(
            self.ENDPOINT,
            {"item_id": 11, "inventory_id": 2, "location_id": 8},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get("storage_table"), "item_location")

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="ops-user",
        DEV_AUTH_ROLES=["LOGISTICS"],
        DEV_AUTH_PERMISSIONS=["replenishment.needs_list.execute"],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch("replenishment.views.location_storage.assign_storage_location")
    def test_assignment_validates_positive_integer_payload(self, mock_assign) -> None:
        response = self.client.post(
            self.ENDPOINT,
            {"item_id": "X", "inventory_id": -1, "location_id": 0},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("item_id", response.json()["errors"])
        self.assertIn("inventory_id", response.json()["errors"])
        self.assertIn("location_id", response.json()["errors"])
        mock_assign.assert_not_called()

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="ops-user",
        DEV_AUTH_ROLES=["LOGISTICS"],
        DEV_AUTH_PERMISSIONS=["replenishment.needs_list.execute"],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch(
        "replenishment.views.location_storage.assign_storage_location",
        side_effect=location_storage.LocationAssignmentError(
            "location_policy_violation",
            "item_location policy violation: item_id 1 is batch-tracked; use batchlocation.",
            status_code=409,
        ),
    )
    def test_assignment_maps_domain_errors(self, _mock_assign) -> None:
        response = self.client.post(
            self.ENDPOINT,
            {"item_id": 1, "inventory_id": 2, "location_id": 3},
            format="json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn("location_policy_violation", response.json()["errors"])


class LocationStorageRoutingTests(SimpleTestCase):
    def test_routes_non_batched_items_to_item_location(self) -> None:
        with (
            patch(
                "replenishment.services.location_storage.transaction.atomic",
                return_value=nullcontext(),
            ),
            patch("replenishment.services.location_storage._is_sqlite", return_value=False),
            patch(
                "replenishment.services.location_storage._fetch_item_batched_flag",
                return_value=False,
            ),
            patch("replenishment.services.location_storage._ensure_location_exists"),
            patch("replenishment.services.location_storage._ensure_inventory_item_exists"),
            patch("replenishment.services.location_storage._assign_batch_location") as mock_batch_assign,
            patch(
                "replenishment.services.location_storage._assign_item_location",
                return_value=True,
            ) as mock_item_assign,
        ):
            result = location_storage.assign_storage_location(
                item_id=25,
                inventory_id=2,
                location_id=9,
                batch_id=None,
                actor_id="tester",
            )

        self.assertEqual(result["storage_table"], "item_location")
        self.assertTrue(result["created"])
        mock_item_assign.assert_called_once()
        mock_batch_assign.assert_not_called()

    def test_routes_batched_items_to_batchlocation(self) -> None:
        with (
            patch(
                "replenishment.services.location_storage.transaction.atomic",
                return_value=nullcontext(),
            ),
            patch("replenishment.services.location_storage._is_sqlite", return_value=False),
            patch(
                "replenishment.services.location_storage._fetch_item_batched_flag",
                return_value=True,
            ),
            patch("replenishment.services.location_storage._ensure_location_exists"),
            patch("replenishment.services.location_storage._ensure_itembatch_exists"),
            patch("replenishment.services.location_storage._assign_item_location") as mock_item_assign,
            patch(
                "replenishment.services.location_storage._assign_batch_location",
                return_value=True,
            ) as mock_batch_assign,
        ):
            result = location_storage.assign_storage_location(
                item_id=25,
                inventory_id=2,
                location_id=9,
                batch_id=100,
                actor_id="tester",
            )

        self.assertEqual(result["storage_table"], "batchlocation")
        self.assertEqual(result["batch_id"], 100)
        mock_batch_assign.assert_called_once()
        mock_item_assign.assert_not_called()

    def test_rejects_missing_batch_id_for_batched_item(self) -> None:
        with (
            patch(
                "replenishment.services.location_storage.transaction.atomic",
                return_value=nullcontext(),
            ),
            patch("replenishment.services.location_storage._is_sqlite", return_value=False),
            patch(
                "replenishment.services.location_storage._fetch_item_batched_flag",
                return_value=True,
            ),
            patch("replenishment.services.location_storage._ensure_location_exists"),
        ):
            with self.assertRaises(location_storage.LocationAssignmentError) as raised:
                location_storage.assign_storage_location(
                    item_id=25,
                    inventory_id=2,
                    location_id=9,
                    batch_id=None,
                    actor_id="tester",
                )

        self.assertEqual(raised.exception.code, "batch_id_required")


class EnforceLocationStoragePolicyCommandTests(TestCase):
    def test_dry_run_outputs_guidance(self) -> None:
        output = StringIO()
        call_command("enforce_location_storage_policy", stdout=output)
        text = output.getvalue()
        self.assertIn("Location storage policy enforcement:", text)
        self.assertIn("Dry-run only", text)

    def test_apply_executes_trigger_and_view_sql(self) -> None:
        output = StringIO()
        mock_cursor = MagicMock()
        cursor_cm = MagicMock()
        cursor_cm.__enter__.return_value = mock_cursor
        cursor_cm.__exit__.return_value = None

        with (
            patch(
                "replenishment.management.commands.enforce_location_storage_policy.transaction.atomic",
                return_value=nullcontext(),
            ),
            patch(
                "replenishment.management.commands.enforce_location_storage_policy.connection.cursor",
                return_value=cursor_cm,
            ),
        ):
            call_command("enforce_location_storage_policy", apply=True, stdout=output)

        executed_sql = "\n".join(
            str(call.args[0]).strip()
            for call in mock_cursor.execute.call_args_list
            if call.args
        )
        self.assertIn("CREATE OR REPLACE FUNCTION enforce_item_location_write_policy()", executed_sql)
        self.assertIn("CREATE TRIGGER trg_enforce_item_location_policy", executed_sql)
        self.assertIn("CREATE OR REPLACE FUNCTION enforce_batchlocation_write_policy()", executed_sql)
        self.assertIn("CREATE TRIGGER trg_enforce_batchlocation_policy", executed_sql)
        self.assertIn("CREATE OR REPLACE VIEW v_item_location_batched", executed_sql)
