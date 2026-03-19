from __future__ import annotations

from contextlib import nullcontext
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import ANY, MagicMock, patch

from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.response import Response
from rest_framework.test import APIClient

from replenishment.services import repackaging


class RepackagingComputationTests(SimpleTestCase):
    def test_compute_quantities_preserves_exact_equivalence(self) -> None:
        result = repackaging._compute_repackaging_quantities(
            source_qty=Decimal("2"),
            source_conversion_factor=Decimal("12"),
            target_conversion_factor=Decimal("1"),
        )

        self.assertEqual(result.source_qty, Decimal("2.000000"))
        self.assertEqual(result.target_qty, Decimal("24.000000"))
        self.assertEqual(result.equivalent_default_qty, Decimal("24.000000"))

    def test_compute_quantities_rejects_non_exact_conservation(self) -> None:
        with self.assertRaises(repackaging.RepackagingError) as raised:
            repackaging._compute_repackaging_quantities(
                source_qty=Decimal("1"),
                source_conversion_factor=Decimal("1"),
                target_conversion_factor=Decimal("3"),
            )

        self.assertEqual(raised.exception.code, "quantity_conservation_violation")

    def test_normalize_positive_decimal_rejects_non_finite_values(self) -> None:
        with self.assertRaises(repackaging.RepackagingError) as raised:
            repackaging._normalize_positive_decimal("NaN", field_name="source_qty")

        self.assertEqual(raised.exception.code, "source_qty_invalid")

    def test_quantize_qty_rejects_values_below_minimum_quantization_unit(self) -> None:
        with self.assertRaises(repackaging.RepackagingError) as raised:
            repackaging._quantize_qty(Decimal("0.0000004"))

        self.assertEqual(raised.exception.code, "quantity_invalid")

    @patch("replenishment.services.repackaging.logger")
    @patch("replenishment.services.repackaging.connection.rollback", side_effect=RuntimeError("no tx"))
    def test_safe_rollback_logs_debug_when_rollback_fails(
        self,
        _mock_rollback,
        mock_logger,
    ) -> None:
        repackaging._safe_rollback()

        mock_logger.debug.assert_called_once()


class RepackagingServiceTests(SimpleTestCase):
    @patch(
        "replenishment.services.repackaging._fetch_single_uom_conversion_factor",
        return_value=Decimal("12"),
    )
    def test_fetch_batch_context_converts_batch_qty_to_default_uom(
        self,
        mock_factor,
    ) -> None:
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (
            18,
            "LOT-18",
            None,
            Decimal("2"),
            Decimal("0.5"),
            "BOX",
        )
        cursor_cm = MagicMock()
        cursor_cm.__enter__.return_value = mock_cursor
        cursor_cm.__exit__.return_value = None
        mock_connection = MagicMock(cursor=MagicMock(return_value=cursor_cm))

        with patch("replenishment.services.repackaging.connection", new=mock_connection):
            context = repackaging._fetch_batch_context(
                schema="tenant_a",
                warehouse_id=2,
                item_id=11,
                batch_id=18,
                batch_or_lot="",
                default_uom_code="EA",
            )

        assert context is not None
        self.assertEqual(context["batch_id"], 18)
        self.assertEqual(context["available_default_qty"], Decimal("18.000000"))
        mock_factor.assert_called_once_with(
            schema="tenant_a",
            item_id=11,
            uom_code="BOX",
            default_uom_code="EA",
        )

    @patch("replenishment.services.repackaging._is_sqlite", return_value=False)
    @patch(
        "replenishment.services.repackaging.get_repackaging_transaction",
        return_value=({"repackaging_id": 33, "audit_rows": [{"action_type": "CREATE"}]}, []),
    )
    @patch("replenishment.services.repackaging._insert_repackaging_audit")
    @patch("replenishment.services.repackaging._insert_repackaging_txn", return_value=33)
    @patch(
        "replenishment.services.repackaging._load_repackaging_context",
        return_value={
            "warehouse_name": "Kingston Hub",
            "item_code": "WWTRTABLTB01",
            "item_name": "Water purification tablet",
            "batch_id": 18,
            "batch_no_snapshot": "LOT-18",
            "expiry_date_snapshot": None,
            "source_conversion_factor": Decimal("12"),
            "target_conversion_factor": Decimal("1"),
            "available_default_qty": Decimal("120"),
        },
    )
    def test_create_repackaging_ignores_client_derived_values_and_reads_back_record(
        self,
        _mock_context,
        _mock_insert_txn,
        mock_insert_audit,
        _mock_get_record,
        _mock_sqlite,
    ) -> None:
        with patch(
            "replenishment.services.repackaging.transaction.atomic",
            return_value=nullcontext(),
        ):
            record, warnings = repackaging.create_repackaging_transaction(
                warehouse_id=2,
                item_id=11,
                source_uom_code="BOX",
                source_qty=Decimal("2"),
                target_uom_code="EA",
                reason_code="DAMAGED_OUTER_PACK",
                note_text="Broken carton",
                batch_id=18,
                actor_id="ops-user",
                client_target_qty=Decimal("25"),
                client_equivalent_default_qty=Decimal("25"),
            )

        self.assertEqual(record["repackaging_id"], 33)
        self.assertIn("client_target_qty_ignored", warnings)
        self.assertIn("client_equivalent_qty_ignored", warnings)
        mock_insert_audit.assert_called_once()

    @patch("replenishment.services.repackaging._is_sqlite", return_value=False)
    @patch(
        "replenishment.services.repackaging.get_repackaging_transaction",
        return_value=({"repackaging_id": 33, "audit_rows": [{"action_type": "CREATE"}]}, []),
    )
    @patch("replenishment.services.repackaging._insert_repackaging_audit")
    @patch("replenishment.services.repackaging._insert_repackaging_txn", return_value=33)
    @patch(
        "replenishment.services.repackaging._load_repackaging_context",
        return_value={
            "warehouse_name": "Kingston Hub",
            "item_code": "WWTRTABLTB01",
            "item_name": "Water purification tablet",
            "batch_id": None,
            "batch_no_snapshot": "",
            "expiry_date_snapshot": None,
            "source_conversion_factor": Decimal("12"),
            "target_conversion_factor": Decimal("1"),
            "available_default_qty": Decimal("120"),
        },
    )
    def test_create_repackaging_ignores_invalid_client_derived_values(
        self,
        _mock_context,
        _mock_insert_txn,
        _mock_insert_audit,
        _mock_get_record,
        _mock_sqlite,
    ) -> None:
        with patch(
            "replenishment.services.repackaging.transaction.atomic",
            return_value=nullcontext(),
        ):
            record, warnings = repackaging.create_repackaging_transaction(
                warehouse_id=2,
                item_id=11,
                source_uom_code="BOX",
                source_qty=Decimal("2"),
                target_uom_code="EA",
                reason_code="DAMAGED_OUTER_PACK",
                actor_id="ops-user",
                client_target_qty="foo",
                client_equivalent_default_qty="NaN",
            )

        self.assertEqual(record["repackaging_id"], 33)
        self.assertIn("client_target_qty_ignored", warnings)
        self.assertIn("client_equivalent_qty_ignored", warnings)

    @patch("replenishment.services.repackaging._is_sqlite", return_value=False)
    @patch(
        "replenishment.services.repackaging._load_repackaging_context",
        return_value={
            "warehouse_name": "Kingston Hub",
            "item_code": "WWTRTABLTB01",
            "item_name": "Water purification tablet",
            "batch_id": None,
            "batch_no_snapshot": "",
            "expiry_date_snapshot": None,
            "source_conversion_factor": Decimal("12"),
            "target_conversion_factor": Decimal("1"),
            "available_default_qty": Decimal("6"),
        },
    )
    def test_create_repackaging_rejects_insufficient_stock(
        self,
        _mock_context,
        _mock_sqlite,
    ) -> None:
        with patch(
            "replenishment.services.repackaging.transaction.atomic",
            return_value=nullcontext(),
        ):
            with self.assertRaises(repackaging.RepackagingError) as raised:
                repackaging.create_repackaging_transaction(
                    warehouse_id=2,
                    item_id=11,
                    source_uom_code="BOX",
                    source_qty=Decimal("1"),
                    target_uom_code="EA",
                    reason_code="DAMAGED_OUTER_PACK",
                    actor_id="ops-user",
                )

        self.assertEqual(raised.exception.code, "insufficient_stock")
        self.assertEqual(raised.exception.status_code, 409)


class RepackagingApiTests(TestCase):
    ENDPOINT = "/api/v1/replenishment/inventory/repackaging"

    def setUp(self) -> None:
        self.client = APIClient()

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
    @patch("replenishment.views.repackaging_service.create_repackaging_transaction")
    def test_post_repackaging_returns_created_record(self, mock_create) -> None:
        mock_create.return_value = (
            {
                "repackaging_id": 33,
                "warehouse_id": 2,
                "item_id": 11,
                "source_uom_code": "BOX",
                "target_uom_code": "EA",
                "target_qty": Decimal("24.000000"),
                "audit_rows": [{"action_type": "CREATE"}],
            },
            [],
        )

        response = self.client.post(
            self.ENDPOINT,
            {
                "warehouse_id": 2,
                "item_id": 11,
                "source_uom_code": "BOX",
                "source_qty": "2",
                "target_uom_code": "EA",
                "reason_code": "DAMAGED_OUTER_PACK",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["record"]["repackaging_id"], 33)

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="ops-user",
        DEV_AUTH_ROLES=["LOGISTICS"],
        DEV_AUTH_PERMISSIONS=["replenishment.needs_list.execute", "masterdata.edit"],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
        TENANT_SCOPE_ENFORCEMENT=True,
    )
    @patch(
        "replenishment.views._require_warehouse_scope",
        return_value=Response({"errors": {"tenant_scope": "denied"}}, status=403),
    )
    @patch("replenishment.views.repackaging_service.create_repackaging_transaction")
    def test_post_repackaging_enforces_write_scope_before_service_call(
        self,
        mock_create,
        mock_scope,
    ) -> None:
        response = self.client.post(
            self.ENDPOINT,
            {
                "warehouse_id": 2,
                "item_id": 11,
                "source_uom_code": "BOX",
                "source_qty": "2",
                "target_uom_code": "EA",
                "reason_code": "DAMAGED_OUTER_PACK",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        mock_scope.assert_called_once_with(ANY, 2, write=True)
        mock_create.assert_not_called()

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
        "replenishment.views.repackaging_service.create_repackaging_transaction",
        side_effect=repackaging.RepackagingError(
            "same_uom_not_allowed",
            "Source and target UOMs must be different for repackaging.",
            status_code=409,
        ),
    )
    def test_post_repackaging_maps_domain_errors(self, _mock_create) -> None:
        response = self.client.post(
            self.ENDPOINT,
            {
                "warehouse_id": 2,
                "item_id": 11,
                "source_uom_code": "EA",
                "source_qty": "2",
                "target_uom_code": "EA",
                "reason_code": "DAMAGED_OUTER_PACK",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 409)
        self.assertIn("same_uom_not_allowed", response.json()["errors"])

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="viewer-1",
        DEV_AUTH_ROLES=["EXECUTIVE"],
        DEV_AUTH_PERMISSIONS=["masterdata.view"],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch(
        "replenishment.views.repackaging_service.list_repackaging_transactions",
        return_value=(
            [{"repackaging_id": 33, "warehouse_id": 2, "item_id": 11}],
            1,
            [],
        ),
    )
    def test_get_repackaging_list_allows_view_permission(self, _mock_list) -> None:
        response = self.client.get(self.ENDPOINT, {"warehouse_id": 2})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="viewer-1",
        DEV_AUTH_ROLES=["EXECUTIVE"],
        DEV_AUTH_PERMISSIONS=["masterdata.view"],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch(
        "replenishment.views.repackaging_service.list_repackaging_transactions",
        return_value=([], 0, ["db_unavailable"]),
    )
    def test_get_repackaging_list_returns_503_when_backend_unavailable(
        self,
        _mock_list,
    ) -> None:
        response = self.client.get(self.ENDPOINT, {"warehouse_id": 2})

        self.assertEqual(response.status_code, 503)
        self.assertIn("db_unavailable", response.json()["warnings"])

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="viewer-1",
        DEV_AUTH_ROLES=["EXECUTIVE"],
        DEV_AUTH_PERMISSIONS=["masterdata.view", "replenishment.needs_list.execute"],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
        TENANT_SCOPE_ENFORCEMENT=True,
    )
    @patch("replenishment.views.repackaging_service.list_repackaging_transactions")
    def test_get_repackaging_list_requires_warehouse_filter_when_scope_enabled(
        self,
        mock_list,
    ) -> None:
        response = self.client.get(self.ENDPOINT)

        self.assertEqual(response.status_code, 400)
        self.assertIn("warehouse_id", response.json()["errors"])
        mock_list.assert_not_called()

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="viewer-1",
        DEV_AUTH_ROLES=["EXECUTIVE"],
        DEV_AUTH_PERMISSIONS=["masterdata.view", "replenishment.needs_list.execute"],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
        TENANT_SCOPE_ENFORCEMENT=True,
    )
    @patch("replenishment.views.repackaging_service.list_repackaging_transactions")
    def test_get_repackaging_list_rejects_invalid_warehouse_filter_when_scope_enabled(
        self,
        mock_list,
    ) -> None:
        response = self.client.get(self.ENDPOINT, {"warehouse_id": "abc"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("warehouse_id", response.json()["errors"])
        mock_list.assert_not_called()

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="viewer-1",
        DEV_AUTH_ROLES=["EXECUTIVE"],
        DEV_AUTH_PERMISSIONS=["masterdata.view", "replenishment.needs_list.execute"],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
        TENANT_SCOPE_ENFORCEMENT=True,
    )
    @patch(
        "replenishment.views._require_warehouse_scope",
        return_value=Response({"errors": {"tenant_scope": "denied"}}, status=403),
    )
    @patch(
        "replenishment.views.repackaging_service.get_repackaging_transaction",
        return_value=({"repackaging_id": 33, "warehouse_id": 2}, []),
    )
    def test_get_repackaging_detail_enforces_read_scope(
        self,
        mock_get,
        mock_scope,
    ) -> None:
        response = self.client.get(f"{self.ENDPOINT}/33")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data["detail"], "Not found.")
        mock_get.assert_called_once_with(33)
        mock_scope.assert_called_once_with(ANY, 2, write=False)

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="viewer-1",
        DEV_AUTH_ROLES=["EXECUTIVE"],
        DEV_AUTH_PERMISSIONS=["masterdata.view", "replenishment.needs_list.execute"],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch(
        "replenishment.views.repackaging_service.get_repackaging_transaction",
        return_value=(None, ["db_unavailable"]),
    )
    def test_get_repackaging_detail_returns_503_when_backend_unavailable(
        self,
        _mock_get,
    ) -> None:
        response = self.client.get(f"{self.ENDPOINT}/33")

        self.assertEqual(response.status_code, 503)
        self.assertIn("db_unavailable", response.json()["warnings"])
