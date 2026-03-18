import importlib
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from masterdata import views
from masterdata.services.data_access import TABLE_REGISTRY
from masterdata.services.operational_masters import (
    validate_agency_payload,
    validate_warehouse_payload,
)


class WarehouseOperationalValidationTests(SimpleTestCase):
    def test_validate_warehouse_payload_requires_parent_for_sub_hub(self):
        errors, warnings = validate_warehouse_payload(
            {"warehouse_type": "SUB-HUB"},
            is_update=False,
        )

        self.assertEqual(warnings, [])
        self.assertEqual(
            errors["parent_warehouse_id"],
            "Parent warehouse is required for SUB-HUB warehouses.",
        )

    @patch("masterdata.services.operational_masters._is_sqlite", return_value=False)
    @patch(
        "masterdata.services.operational_masters._fetch_warehouse_minimal",
        return_value={
            "warehouse_id": 7,
            "warehouse_name": "North Spur",
            "warehouse_type": "SUB-HUB",
            "status_code": "A",
            "tenant_id": 1,
        },
    )
    def test_validate_warehouse_payload_rejects_sub_hub_parent(
        self,
        _mock_parent,
        _mock_sqlite,
    ):
        errors, warnings = validate_warehouse_payload(
            {"warehouse_type": "SUB-HUB", "parent_warehouse_id": 7},
            is_update=False,
        )

        self.assertEqual(warnings, [])
        self.assertEqual(
            errors["parent_warehouse_id"],
            "SUB-HUB warehouses must belong to an active MAIN-HUB warehouse.",
        )

    @patch("masterdata.services.operational_masters._is_sqlite", return_value=False)
    @patch(
        "masterdata.services.operational_masters._fetch_warehouse_minimal",
        return_value={
            "warehouse_id": 3,
            "warehouse_name": "Dormant Hub",
            "warehouse_type": "MAIN-HUB",
            "status_code": "I",
            "tenant_id": 1,
        },
    )
    def test_validate_agency_payload_rejects_inactive_warehouse(
        self,
        _mock_parent,
        _mock_sqlite,
    ):
        errors, warnings = validate_agency_payload(
            {"agency_type": "DISTRIBUTOR", "warehouse_id": 3},
            is_update=False,
        )

        self.assertEqual(warnings, [])
        self.assertEqual(
            errors["warehouse_id"],
            "Selected Warehouse must be active.",
        )


class WarehouseViewDispatchTests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.user = SimpleNamespace(
            is_authenticated=True,
            user_id="ops-admin",
            roles=[],
            permissions=[
                views.PERM_MASTERDATA_VIEW,
                views.PERM_MASTERDATA_CREATE,
                views.PERM_MASTERDATA_EDIT,
            ],
        )

    @patch("masterdata.permissions.MasterDataPermission.has_permission", return_value=True)
    @patch(
        "masterdata.views.list_warehouse_records",
        return_value=(
            [
                {
                    "warehouse_id": 5,
                    "warehouse_name": "Kingston Hub",
                    "warehouse_type": "MAIN-HUB",
                    "stock_health_summary": {"overall_status": "GREEN"},
                }
            ],
            1,
            [],
        ),
    )
    def test_master_list_create_uses_dedicated_warehouse_listing(
        self,
        mock_list_warehouse_records,
        _mock_permission,
    ):
        request = self.factory.get("/api/v1/masterdata/warehouses/", {"status": "A"})
        force_authenticate(request, user=self.user)

        response = views.master_list_create(request, "warehouses")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["results"][0]["stock_health_summary"]["overall_status"], "GREEN")
        mock_list_warehouse_records.assert_called_once_with(
            status_filter="A",
            search=None,
            order_by=None,
            limit=views.DEFAULT_PAGE_LIMIT,
            offset=0,
        )

    @patch("masterdata.permissions.MasterDataPermission.has_permission", return_value=True)
    @patch(
        "masterdata.views.get_warehouse_record",
        return_value=(
            {
                "warehouse_id": 5,
                "warehouse_name": "Kingston Hub",
                "warehouse_type": "MAIN-HUB",
                "child_warehouse_count": 2,
                "stock_health_summary": {"overall_status": "AMBER"},
            },
            [],
        ),
    )
    def test_master_detail_update_uses_dedicated_warehouse_detail(
        self,
        _mock_get_warehouse_record,
        _mock_permission,
    ):
        request = self.factory.get("/api/v1/masterdata/warehouses/5")
        force_authenticate(request, user=self.user)

        response = views.master_detail_update(request, "warehouses", "5")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["record"]["child_warehouse_count"], 2)
        self.assertEqual(response.data["record"]["stock_health_summary"]["overall_status"], "AMBER")

    @patch("masterdata.permissions.MasterDataPermission.has_permission", return_value=True)
    @patch(
        "masterdata.views.list_stock_health_records",
        return_value=(
            [
                {
                    "warehouse_id": 5,
                    "item_id": 11,
                    "item_name": "Water Tabs",
                    "stock_health_status": "RED",
                }
            ],
            1,
            [],
        ),
    )
    def test_warehouse_stock_health_endpoint_returns_rows(
        self,
        mock_list_stock_health,
        _mock_permission,
    ):
        request = self.factory.get(
            "/api/v1/masterdata/warehouses/stock-health",
            {"warehouse_id": "5", "health_status": "RED"},
        )
        force_authenticate(request, user=self.user)

        response = views.warehouse_stock_health(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["results"][0]["stock_health_status"], "RED")
        mock_list_stock_health.assert_called_once_with(
            warehouse_id="5",
            item_id=None,
            health_status="RED",
            order_by=None,
            limit=views.DEFAULT_PAGE_LIMIT,
            offset=0,
        )

    @patch("masterdata.permissions.MasterDataPermission.has_permission", return_value=True)
    @patch(
        "masterdata.views.list_stock_health_records",
        return_value=([], 0, ["db_unavailable"]),
    )
    def test_warehouse_stock_health_endpoint_returns_503_when_unavailable(
        self,
        _mock_list_stock_health,
        _mock_permission,
    ):
        request = self.factory.get("/api/v1/masterdata/warehouses/stock-health")
        force_authenticate(request, user=self.user)

        response = views.warehouse_stock_health(request)

        self.assertEqual(response.status_code, 503)
        self.assertIn("db_unavailable", response.data["warnings"])

    @patch("masterdata.permissions.MasterDataPermission.has_permission", return_value=True)
    @patch(
        "masterdata.views.list_stock_health_records",
        return_value=([], 0, ["db_error"]),
    )
    def test_warehouse_stock_health_detail_returns_500_on_storage_error(
        self,
        _mock_list_stock_health,
        _mock_permission,
    ):
        request = self.factory.get("/api/v1/masterdata/warehouses/5/stock-health")
        force_authenticate(request, user=self.user)

        response = views.warehouse_stock_health_detail(request, "5")

        self.assertEqual(response.status_code, 500)
        self.assertIn("db_error", response.data["warnings"])


class Sprint07MigrationTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.migration = importlib.import_module(
            "masterdata.migrations.0009_sprint07_logistics_foundations"
        )

    def test_forward_sql_adds_parent_hierarchy_stock_health_and_repackaging(self):
        schema_editor = SimpleNamespace(
            connection=SimpleNamespace(vendor="postgresql"),
            execute=MagicMock(),
        )

        with patch.object(self.migration, "_relation_exists", return_value=True):
            with patch.dict("os.environ", {"DMIS_DB_SCHEMA": "tenant_a"}):
                self.migration._forwards(None, schema_editor)

        executed_sql = schema_editor.execute.call_args.args[0]
        self.assertIn('ADD COLUMN IF NOT EXISTS parent_warehouse_id', executed_sql)
        self.assertIn('CREATE TABLE IF NOT EXISTS "tenant_a".uom_repackaging_txn', executed_sql)
        self.assertIn('CREATE TABLE IF NOT EXISTS "tenant_a".uom_repackaging_audit', executed_sql)
        self.assertIn('fn_prevent_uom_repackaging_txn_mutation', executed_sql)
        self.assertIn('trg_uom_repackaging_txn_no_mutation', executed_sql)
        self.assertIn('stock_health_status', executed_sql)
        self.assertIn('reorder_level_qty', executed_sql)
