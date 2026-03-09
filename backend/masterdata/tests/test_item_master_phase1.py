import importlib
from io import StringIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.test import SimpleTestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from masterdata import views
from masterdata.item_master_taxonomy import build_ifrc_taxonomy_seed_payload
from masterdata.services.data_access import TABLE_REGISTRY
from masterdata.services.item_master import list_item_records, validate_item_payload


class ItemMasterRegistryTests(SimpleTestCase):
    def test_items_registry_includes_ifrc_fields(self):
        field_names = {field.name for field in TABLE_REGISTRY["items"].fields}
        self.assertIn("ifrc_family_id", field_names)
        self.assertIn("ifrc_item_ref_id", field_names)


class ItemMasterSearchSqlTests(SimpleTestCase):
    @patch("masterdata.services.item_master._is_sqlite", return_value=False)
    @patch("masterdata.services.item_master.connection")
    def test_list_item_records_searches_joined_taxonomy_fields(
        self,
        mock_connection,
        _mock_sqlite,
    ):
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (0,)
        cursor.fetchall.return_value = []

        rows, total, warnings = list_item_records(search="blanket", order_by="ifrc_family_label")

        self.assertEqual(rows, [])
        self.assertEqual(total, 0)
        self.assertEqual(warnings, [])
        executed_sql = cursor.execute.call_args_list[1].args[0]
        self.assertIn("LEFT JOIN public.ifrc_family f", executed_sql)
        self.assertIn("LEFT JOIN public.ifrc_item_reference r", executed_sql)
        self.assertIn("UPPER(COALESCE(f.family_label, '')) LIKE %s", executed_sql)
        self.assertIn("UPPER(COALESCE(r.reference_desc, '')) LIKE %s", executed_sql)
        self.assertIn("ORDER BY ifrc_family_label ASC", executed_sql)


class ItemMasterValidationTests(SimpleTestCase):
    @patch("masterdata.services.item_master._is_sqlite", return_value=False)
    @patch("masterdata.services.item_master._missing_uom_codes", return_value=[])
    @patch("masterdata.services.item_master._category_has_active_families", return_value=True)
    @patch("masterdata.services.item_master._fetch_ifrc_reference", return_value=None)
    @patch("masterdata.services.item_master._fetch_ifrc_family", return_value=None)
    def test_validate_item_payload_requires_family_when_category_has_seeded_families(
        self,
        _mock_family,
        _mock_reference,
        _mock_category_has_families,
        _mock_missing_uoms,
        _mock_sqlite,
    ):
        errors, warnings = validate_item_payload(
            {"category_id": 102, "default_uom_code": "EA"},
            is_update=False,
        )

        self.assertEqual(warnings, [])
        self.assertEqual(
            errors["ifrc_family_id"],
            "IFRC Family is required for categories with governed Level 2 classifications.",
        )

    @patch("masterdata.services.item_master._is_sqlite", return_value=False)
    @patch("masterdata.services.item_master._missing_uom_codes", return_value=[])
    @patch("masterdata.services.item_master._category_has_active_families", return_value=True)
    @patch("masterdata.services.item_master._fetch_ifrc_reference", return_value=None)
    @patch("masterdata.services.item_master._fetch_ifrc_family", return_value=None)
    def test_validate_item_payload_allows_legacy_update_with_null_ifrc_fields(
        self,
        _mock_family,
        _mock_reference,
        _mock_category_has_families,
        _mock_missing_uoms,
        _mock_sqlite,
    ):
        errors, warnings = validate_item_payload(
            {"item_name": "LEGACY WATER"},
            is_update=True,
            existing_record={
                "category_id": 102,
                "ifrc_family_id": None,
                "ifrc_item_ref_id": None,
                "default_uom_code": "EA",
            },
        )

        self.assertEqual(warnings, [])
        self.assertEqual(errors, {})

    @patch("masterdata.services.item_master._is_sqlite", return_value=False)
    @patch("masterdata.services.item_master._missing_uom_codes", return_value=[])
    @patch("masterdata.services.item_master._category_has_active_families", return_value=True)
    @patch(
        "masterdata.services.item_master._fetch_ifrc_reference",
        return_value={"ifrc_item_ref_id": 51, "ifrc_family_id": 22, "ifrc_code": "WWTRTABL01", "reference_desc": "Water purification tablet", "status_code": "A"},
    )
    @patch(
        "masterdata.services.item_master._fetch_ifrc_family",
        return_value={"ifrc_family_id": 11, "category_id": 102, "group_code": "W", "family_code": "WTR", "family_label": "Water Treatment", "status_code": "A"},
    )
    def test_validate_item_payload_rejects_reference_outside_selected_family(
        self,
        _mock_family,
        _mock_reference,
        _mock_category_has_families,
        _mock_missing_uoms,
        _mock_sqlite,
    ):
        errors, warnings = validate_item_payload(
            {
                "category_id": 102,
                "ifrc_family_id": 11,
                "ifrc_item_ref_id": 51,
                "default_uom_code": "EA",
            },
            is_update=False,
        )

        self.assertEqual(warnings, [])
        self.assertEqual(
            errors["ifrc_item_ref_id"],
            "Selected IFRC Item Reference does not belong to the chosen IFRC Family.",
        )


class ItemMasterSeedPayloadTests(SimpleTestCase):
    def test_seed_payload_is_deterministic(self):
        first = build_ifrc_taxonomy_seed_payload()
        second = build_ifrc_taxonomy_seed_payload()

        self.assertEqual(first, second)
        self.assertEqual(len(first["categories"]), 14)
        self.assertGreater(len(first["families"]), 0)
        self.assertGreater(len(first["references"]), len(first["families"]))


class ItemMasterViewDispatchTests(SimpleTestCase):
    @patch("masterdata.views.get_item_record", return_value=({"item_id": 501, "item_code": "LOC-001"}, []))
    @patch("masterdata.views.create_item_record", return_value=(501, []))
    @patch("masterdata.views.validate_item_payload", return_value=({}, []))
    @patch("masterdata.views.validate_record", return_value={})
    def test_handle_item_create_uses_dedicated_service(
        self,
        _mock_validate_record,
        _mock_validate_item_payload,
        mock_create_item_record,
        _mock_get_item_record,
    ):
        request = SimpleNamespace(
            data={"item_code": "LOC-001", "item_name": "WATER TABS", "category_id": 102},
            user=SimpleNamespace(user_id="tester"),
        )

        response = views._handle_create(request, TABLE_REGISTRY["items"])

        self.assertEqual(response.status_code, 201)
        mock_create_item_record.assert_called_once()
        self.assertEqual(response.data["record"]["item_id"], 501)


class ItemMasterLookupViewTests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.user = SimpleNamespace(
            is_authenticated=True,
            user_id="tester",
            roles=[],
            permissions=[views.PERM_MASTERDATA_VIEW],
        )

    @patch("masterdata.permissions.MasterDataPermission.has_permission", return_value=True)
    @patch("masterdata.views.list_ifrc_family_lookup", return_value=([{"value": 11, "label": "Water Treatment"}], []))
    def test_family_lookup_endpoint_returns_items(self, _mock_lookup, _mock_permission):
        request = self.factory.get("/api/v1/masterdata/items/ifrc-families/lookup", {"category_id": "102", "active_only": "true"})
        force_authenticate(request, user=self.user)
        response = views.item_ifrc_family_lookup(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["items"][0]["label"], "Water Treatment")

    @patch("masterdata.permissions.MasterDataPermission.has_permission", return_value=True)
    @patch("masterdata.views.list_item_category_lookup", return_value=([{"value": 1, "label": "Food and Water Supplies", "status_code": "I"}], []))
    def test_category_lookup_can_include_legacy_inactive_value(self, _mock_lookup, _mock_permission):
        request = self.factory.get(
            "/api/v1/masterdata/items/categories/lookup",
            {"include_value": "1", "active_only": "true"},
        )
        force_authenticate(request, user=self.user)

        response = views.item_level1_category_lookup(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["items"][0]["status_code"], "I")


class UnifiedItemMasterMigrationSchemaTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.migration = importlib.import_module(
            "masterdata.migrations.0005_unified_item_master_phase1"
        )

    @patch("masterdata.item_master_taxonomy.sync_item_master_taxonomy")
    def test_forwards_sql_uses_configured_schema(self, mock_sync):
        schema_editor = SimpleNamespace(
            connection=SimpleNamespace(vendor="postgresql"),
            execute=MagicMock(),
        )
        with patch.object(self.migration, "_legacy_item_table_exists", return_value=True):
            with patch.dict("os.environ", {"DMIS_DB_SCHEMA": "tenant_a"}):
                self.migration._forwards(None, schema_editor)

        executed_sql = schema_editor.execute.call_args.args[0]
        self.assertIn("CREATE TABLE IF NOT EXISTS tenant_a.ifrc_family", executed_sql)
        self.assertIn("ALTER TABLE tenant_a.item", executed_sql)
        mock_sync.assert_called_once_with(schema_editor.connection, schema="tenant_a")


class SyncItemMasterTaxonomyCommandTests(SimpleTestCase):
    def test_dry_run_reports_seed_counts(self):
        stdout = StringIO()

        call_command("sync_item_master_taxonomy", "--dry-run", stdout=stdout)

        output = stdout.getvalue()
        self.assertIn("Item master taxonomy sync dry-run:", output)
        self.assertIn("Level 1 categories: 14", output)
        self.assertIn("IFRC families:", output)
        self.assertIn("IFRC item references:", output)
