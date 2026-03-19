import importlib
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings
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

    @patch("masterdata.services.operational_masters._is_sqlite", return_value=False)
    @patch(
        "masterdata.services.operational_masters._fetch_warehouse_minimal",
        return_value={
            "warehouse_id": 9,
            "warehouse_name": "Cross Tenant Hub",
            "warehouse_type": "MAIN-HUB",
            "status_code": "A",
            "tenant_id": 2,
        },
    )
    def test_validate_warehouse_payload_rejects_cross_tenant_parent(
        self,
        _mock_parent,
        _mock_sqlite,
    ):
        errors, warnings = validate_warehouse_payload(
            {
                "warehouse_type": "SUB-HUB",
                "parent_warehouse_id": 9,
                "tenant_id": 1,
            },
            is_update=False,
        )

        self.assertEqual(warnings, [])
        self.assertEqual(
            errors["parent_warehouse_id"],
            "Parent warehouse must belong to the same tenant.",
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

    @patch(
        "masterdata.views.get_warehouse_record",
        return_value=(
            {
                "warehouse_id": 5,
                "warehouse_name": "Kingston Hub",
                "warehouse_type": "MAIN-HUB",
                "child_warehouse_count": 2,
            },
            [],
        ),
    )
    @patch("masterdata.views.create_record", return_value=(5, []))
    @patch("masterdata.views.validate_operational_master_payload", return_value=({}, []))
    @patch("masterdata.views.validate_record", return_value={})
    @patch("masterdata.views._prepare_warehouse_write_payload", return_value=({"warehouse_name": "Kingston Hub"}, {}))
    def test_handle_create_uses_dedicated_warehouse_readback(
        self,
        _mock_prepare_payload,
        _mock_validate_record,
        _mock_validate_operational,
        _mock_create_record,
        mock_get_warehouse_record,
    ):
        request = self.factory.post("/api/v1/masterdata/warehouses/", {"warehouse_name": "Kingston Hub"}, format="json")
        force_authenticate(request, user=self.user)
        request.data = {"warehouse_name": "Kingston Hub"}
        request.user = self.user

        response = views._handle_create(request, TABLE_REGISTRY["warehouses"])

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["record"]["child_warehouse_count"], 2)
        mock_get_warehouse_record.assert_called_once_with(5)

    @patch(
        "masterdata.views.get_warehouse_record",
        return_value=(
            {
                "warehouse_id": 5,
                "warehouse_name": "Kingston Hub",
                "warehouse_type": "MAIN-HUB",
                "child_warehouse_count": 3,
            },
            [],
        ),
    )
    @patch("masterdata.views.update_record", return_value=(True, []))
    @patch("masterdata.views.validate_operational_master_payload", return_value=({}, []))
    @patch("masterdata.views.validate_record", return_value={})
    @patch("masterdata.views._prepare_warehouse_write_payload", return_value=({"warehouse_name": "Kingston Hub"}, {}))
    @patch(
        "masterdata.views.get_record",
        return_value=(
            {
                "warehouse_id": 5,
                "warehouse_name": "Kingston Hub",
                "tenant_id": 1,
            },
            [],
        ),
    )
    def test_handle_update_uses_dedicated_warehouse_readback(
        self,
        mock_get_record,
        _mock_prepare_payload,
        _mock_validate_record,
        _mock_validate_operational,
        _mock_update_record,
        mock_get_warehouse_record,
    ):
        request = self.factory.patch("/api/v1/masterdata/warehouses/5", {"warehouse_name": "Kingston Hub"}, format="json")
        force_authenticate(request, user=self.user)
        request.data = {"warehouse_name": "Kingston Hub"}
        request.user = self.user

        response = views._handle_update(request, TABLE_REGISTRY["warehouses"], 5)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["record"]["child_warehouse_count"], 3)
        self.assertEqual(mock_get_record.call_count, 1)
        mock_get_warehouse_record.assert_called_once_with(5)

    @override_settings(TENANT_SCOPE_ENFORCEMENT=True)
    @patch("masterdata.permissions.MasterDataPermission.has_permission", return_value=True)
    @patch("masterdata.views.list_stock_health_records")
    def test_warehouse_stock_health_requires_filter_when_scope_enabled(
        self,
        mock_list_stock_health,
        _mock_permission,
    ):
        request = self.factory.get("/api/v1/masterdata/warehouses/stock-health")
        force_authenticate(request, user=self.user)

        response = views.warehouse_stock_health(request)

        self.assertEqual(response.status_code, 400)
        self.assertIn("warehouse_id", response.data["errors"])
        mock_list_stock_health.assert_not_called()

    @override_settings(TENANT_SCOPE_ENFORCEMENT=True)
    @patch("masterdata.permissions.MasterDataPermission.has_permission", return_value=True)
    @patch("masterdata.views.list_stock_health_records")
    def test_warehouse_stock_health_rejects_invalid_filter_when_scope_enabled(
        self,
        mock_list_stock_health,
        _mock_permission,
    ):
        request = self.factory.get("/api/v1/masterdata/warehouses/stock-health", {"warehouse_id": "abc"})
        force_authenticate(request, user=self.user)

        response = views.warehouse_stock_health(request)

        self.assertEqual(response.status_code, 400)
        self.assertIn("warehouse_id", response.data["errors"])
        mock_list_stock_health.assert_not_called()

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

    @override_settings(TENANT_SCOPE_ENFORCEMENT=True)
    @patch("masterdata.permissions.MasterDataPermission.has_permission", return_value=True)
    @patch(
        "masterdata.views._require_warehouse_scope",
        return_value=views.Response({"errors": {"tenant_scope": "denied"}}, status=403),
    )
    @patch("masterdata.views.list_stock_health_records")
    def test_warehouse_stock_health_detail_enforces_scope(
        self,
        mock_list_stock_health,
        _mock_scope,
        _mock_permission,
    ):
        request = self.factory.get("/api/v1/masterdata/warehouses/5/stock-health")
        force_authenticate(request, user=self.user)

        response = views.warehouse_stock_health_detail(request, "5")

        self.assertEqual(response.status_code, 403)
        mock_list_stock_health.assert_not_called()

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
    def test_warehouse_stock_health_detail_supports_pagination(
        self,
        mock_list_stock_health,
        _mock_permission,
    ):
        request = self.factory.get(
            "/api/v1/masterdata/warehouses/5/stock-health",
            {"limit": "25", "offset": "50"},
        )
        force_authenticate(request, user=self.user)

        response = views.warehouse_stock_health_detail(request, "5")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["limit"], 25)
        self.assertEqual(response.data["offset"], 50)
        mock_list_stock_health.assert_called_once_with(
            warehouse_id="5",
            item_id=None,
            health_status=None,
            order_by=None,
            limit=25,
            offset=50,
        )

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

    @override_settings(TENANT_SCOPE_ENFORCEMENT=True)
    @patch("masterdata.views._tenant_context", return_value=SimpleNamespace())
    @patch("masterdata.views.can_access_warehouse", return_value=False)
    def test_prepare_warehouse_write_payload_rejects_cross_tenant_update(
        self,
        _mock_can_access,
        _mock_tenant_context,
    ):
        request = self.factory.patch("/api/v1/masterdata/warehouses/5", {"warehouse_name": "Renamed"}, format="json")
        force_authenticate(request, user=self.user)

        payload, errors = views._prepare_warehouse_write_payload(
            request,
            {"warehouse_name": "Renamed"},
            existing_record={"warehouse_id": 5, "tenant_id": 2},
        )

        self.assertEqual(payload, {"warehouse_name": "Renamed"})
        self.assertEqual(
            errors["tenant_scope"],
            "You do not have access to modify this warehouse.",
        )


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

    def test_forward_sql_skips_when_required_relations_are_missing(self):
        schema_editor = SimpleNamespace(
            connection=SimpleNamespace(vendor="postgresql"),
            execute=MagicMock(),
        )

        def relation_exists(_schema_editor, relation):
            return relation != "inventory"

        with patch.object(self.migration, "_relation_exists", side_effect=relation_exists):
            with patch.dict("os.environ", {"DMIS_DB_SCHEMA": "tenant_a"}):
                self.migration._forwards(None, schema_editor)

        schema_editor.execute.assert_not_called()
