import importlib
import json
from contextlib import nullcontext
from decimal import Decimal
from io import StringIO
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from django.core.management import call_command
from django.db import DatabaseError
from django.test import SimpleTestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from masterdata import views
from masterdata.ifrc_catalogue_loader import CategoryDef, FamilyDef, GroupDef, IFRCTaxonomy
from masterdata.item_master_taxonomy import (
    _backfill_default_item_uom_options,
    _sync_categories,
    _sync_references,
    build_ifrc_taxonomy_seed_payload,
    sync_item_master_taxonomy,
)
from masterdata.services.catalog_governance import (
    _write_catalog_audit,
    _match_reference_category,
    catalog_detail_metadata,
    suggest_ifrc_family_authoring,
    suggest_ifrc_reference_authoring,
    validate_catalog_update,
)
from masterdata.services.data_access import TABLE_REGISTRY
from masterdata.services.data_access import get_lookup
from masterdata.services.item_master import (
    ITEM_CANONICAL_CONFLICT_CODE,
    _build_item_write_payload,
    _ensure_default_item_uom_option,
    _normalize_item_uom_options,
    _replace_item_uom_options,
    create_item_record,
    find_item_canonical_conflict,
    get_item_record,
    list_ifrc_family_lookup,
    list_ifrc_reference_lookup,
    list_item_records,
    update_item_record,
    validate_item_payload,
)
from masterdata.services.validation import validate_record


class ItemMasterRegistryTests(SimpleTestCase):
    def test_items_registry_includes_taxonomy_and_legacy_code_fields(self):
        field_map = {field.name: field for field in TABLE_REGISTRY["items"].fields}
        self.assertIn("ifrc_family_id", field_map)
        self.assertIn("ifrc_item_ref_id", field_map)
        self.assertIn("legacy_item_code", field_map)
        self.assertFalse(field_map["item_code"].required)

    def test_catalog_registry_includes_governed_family_and_reference_tables(self):
        self.assertIn("ifrc_families", TABLE_REGISTRY)
        self.assertIn("ifrc_item_references", TABLE_REGISTRY)
        family_fields = {field.name for field in TABLE_REGISTRY["ifrc_families"].fields}
        reference_fields = {field.name for field in TABLE_REGISTRY["ifrc_item_references"].fields}

        self.assertIn("group_code", family_fields)
        self.assertIn("family_code", family_fields)
        self.assertIn("size_weight", reference_fields)
        self.assertIn("form", reference_fields)
        self.assertIn("material", reference_fields)

    @patch("masterdata.services.data_access._is_sqlite", return_value=False)
    @patch("masterdata.services.data_access.connection")
    def test_ifrc_family_lookup_uses_family_label_for_dropdown_labels(
        self,
        mock_connection,
        _mock_sqlite,
    ):
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [(11, "Water Treatment")]

        rows, warnings = get_lookup("ifrc_families")

        self.assertEqual(rows, [{"value": 11, "label": "Water Treatment"}])
        self.assertEqual(warnings, [])
        executed_sql = cursor.execute.call_args.args[0]
        self.assertIn("SELECT ifrc_family_id, family_label", executed_sql)
        self.assertIn("ORDER BY family_label", executed_sql)


class ItemMasterSearchSqlTests(SimpleTestCase):
    @patch("masterdata.services.item_master._is_sqlite", return_value=False)
    @patch("masterdata.services.item_master.connection")
    def test_list_item_records_searches_legacy_and_joined_taxonomy_fields(
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
        self.assertIn(".ifrc_family f", executed_sql)
        self.assertIn(".ifrc_item_reference r", executed_sql)
        self.assertIn("UPPER(COALESCE(i.legacy_item_code, '')) LIKE %s", executed_sql)
        self.assertIn("UPPER(COALESCE(f.family_label, '')) LIKE %s", executed_sql)
        self.assertIn("UPPER(COALESCE(r.reference_desc, '')) LIKE %s", executed_sql)
        self.assertIn("ORDER BY ifrc_family_label ASC", executed_sql)

    @patch("masterdata.services.item_master._is_sqlite", return_value=False)
    @patch("masterdata.services.item_master.connection")
    def test_list_item_records_ignores_malformed_numeric_filters(
        self,
        mock_connection,
        _mock_sqlite,
    ):
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (0,)
        cursor.fetchall.return_value = []

        rows, total, warnings = list_item_records(
            category_id="abc",
            ifrc_family_id="bad",
            ifrc_item_ref_id="oops",
        )

        self.assertEqual(rows, [])
        self.assertEqual(total, 0)
        self.assertEqual(
            warnings,
            [
                "invalid_category_id_filter",
                "invalid_ifrc_family_id_filter",
                "invalid_ifrc_item_ref_id_filter",
            ],
        )
        executed_sql = cursor.execute.call_args_list[1].args[0]
        query_params = cursor.execute.call_args_list[1].args[1]
        self.assertNotIn("i.category_id = %s", executed_sql)
        self.assertNotIn("i.ifrc_family_id = %s", executed_sql)
        self.assertNotIn("i.ifrc_item_ref_id = %s", executed_sql)
        self.assertEqual(query_params, [100, 0])

    @patch("masterdata.services.item_master._is_sqlite", return_value=False)
    @patch("masterdata.services.item_master.connection")
    def test_list_ifrc_family_lookup_ignores_malformed_category_filter(
        self,
        mock_connection,
        _mock_sqlite,
    ):
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = []

        rows, warnings = list_ifrc_family_lookup(category_id="abc", active_only=False)

        self.assertEqual(rows, [])
        self.assertEqual(warnings, [])
        executed_sql = cursor.execute.call_args.args[0]
        self.assertNotIn("f.category_id = %s", executed_sql)
        self.assertEqual(cursor.execute.call_args.args[1], [])

    @patch("masterdata.services.item_master._is_sqlite", return_value=False)
    @patch("masterdata.services.item_master.connection")
    def test_list_ifrc_family_lookup_can_include_requested_inactive_value(
        self,
        mock_connection,
        _mock_sqlite,
    ):
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [
            (11, "Water Treatment", "WTR", "W", "Water", 102, "WASH", "Water and Sanitation")
        ]

        rows, warnings = list_ifrc_family_lookup(
            category_id=102,
            active_only=True,
            include_value=11,
        )

        self.assertEqual(warnings, [])
        self.assertEqual(rows[0]["value"], 11)
        executed_sql = cursor.execute.call_args.args[0]
        query_params = cursor.execute.call_args.args[1]
        self.assertIn("(f.status_code = 'A' OR f.ifrc_family_id = %s)", executed_sql)
        self.assertEqual(query_params[:2], [102, 11])

    @patch("masterdata.services.item_master._is_sqlite", return_value=False)
    @patch("masterdata.services.item_master.connection")
    def test_list_ifrc_reference_lookup_ignores_malformed_family_filter(
        self,
        mock_connection,
        _mock_sqlite,
    ):
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = []

        rows, warnings = list_ifrc_reference_lookup(ifrc_family_id="abc", active_only=False)

        self.assertEqual(rows, [])
        self.assertEqual(warnings, [])
        executed_sql = cursor.execute.call_args.args[0]
        query_params = cursor.execute.call_args.args[1]
        self.assertNotIn("r.ifrc_family_id = %s", executed_sql)
        self.assertEqual(query_params, [100])

    @patch("masterdata.services.item_master._is_sqlite", return_value=False)
    @patch("masterdata.services.item_master.connection")
    def test_list_ifrc_reference_lookup_can_include_requested_inactive_value(
        self,
        mock_connection,
        _mock_sqlite,
    ):
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [
            (
                77,
                "Water purification tablet",
                "WWTRTABLTB01",
                11,
                "WTR",
                "Water Treatment",
                "TABL",
                "Tablet",
                "TB",
                "500 G",
                "TABLET",
                "CHLORINE",
            )
        ]

        rows, warnings = list_ifrc_reference_lookup(
            ifrc_family_id=11,
            active_only=True,
            include_value=77,
        )

        self.assertEqual(warnings, [])
        self.assertEqual(rows[0]["value"], 77)
        executed_sql = cursor.execute.call_args.args[0]
        query_params = cursor.execute.call_args.args[1]
        self.assertIn("(r.status_code = 'A' OR r.ifrc_item_ref_id = %s)", executed_sql)
        self.assertEqual(query_params[:2], [11, 77])


class ItemMasterValidationTests(SimpleTestCase):
    @patch("masterdata.services.item_master._is_sqlite", return_value=False)
    @patch("masterdata.services.item_master._missing_uom_codes", return_value=[])
    @patch("masterdata.services.item_master._fetch_ifrc_reference", return_value=None)
    @patch("masterdata.services.item_master._fetch_ifrc_family", return_value=None)
    def test_validate_item_payload_requires_family_and_reference_for_new_items(
        self,
        _mock_family,
        _mock_reference,
        _mock_missing_uoms,
        _mock_sqlite,
    ):
        errors, warnings = validate_item_payload(
            {"category_id": 102, "default_uom_code": "EA"},
            is_update=False,
        )

        self.assertEqual(warnings, [])
        self.assertEqual(errors["ifrc_family_id"], "IFRC Family is required for new items.")
        self.assertEqual(errors["ifrc_item_ref_id"], "IFRC Item Reference is required for new items.")

    @patch("masterdata.services.item_master._is_sqlite", return_value=False)
    @patch("masterdata.services.item_master._missing_uom_codes", return_value=[])
    @patch("masterdata.services.item_master._fetch_ifrc_reference", return_value=None)
    @patch("masterdata.services.item_master._fetch_ifrc_family", return_value=None)
    def test_validate_item_payload_allows_legacy_update_with_null_ifrc_fields(
        self,
        _mock_family,
        _mock_reference,
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
    @patch("masterdata.services.item_master._fetch_ifrc_reference", return_value=None)
    @patch(
        "masterdata.services.item_master._fetch_ifrc_family",
        return_value={"ifrc_family_id": 11, "category_id": 102, "group_code": "W", "family_code": "WTR", "family_label": "Water Treatment", "status_code": "A"},
    )
    def test_validate_item_payload_requires_reference_when_family_selected(
        self,
        _mock_family,
        _mock_reference,
        _mock_missing_uoms,
        _mock_sqlite,
    ):
        errors, warnings = validate_item_payload(
            {
                "category_id": 102,
                "ifrc_family_id": 11,
                "default_uom_code": "EA",
            },
            is_update=True,
            existing_record={
                "category_id": 102,
                "ifrc_family_id": None,
                "ifrc_item_ref_id": None,
                "default_uom_code": "EA",
            },
        )

        self.assertEqual(warnings, [])
        self.assertEqual(
            errors["ifrc_item_ref_id"],
            "IFRC Item Reference is required when selecting an IFRC Family.",
        )

    @patch("masterdata.services.item_master._is_sqlite", return_value=False)
    @patch("masterdata.services.item_master._missing_uom_codes", return_value=[])
    @patch(
        "masterdata.services.item_master._fetch_ifrc_reference",
        return_value={"ifrc_item_ref_id": 51, "ifrc_family_id": 11, "ifrc_code": "WWTRTABL01", "reference_desc": "Water purification tablet", "status_code": "A"},
    )
    @patch(
        "masterdata.services.item_master._fetch_ifrc_family",
        return_value={"ifrc_family_id": 11, "category_id": 102, "group_code": "W", "family_code": "WTR", "family_label": "Water Treatment", "status_code": "A"},
    )
    def test_validate_item_payload_rejects_mapped_item_unmapping_attempt(
        self,
        _mock_family,
        _mock_reference,
        _mock_missing_uoms,
        _mock_sqlite,
    ):
        errors, warnings = validate_item_payload(
            {"ifrc_item_ref_id": None},
            is_update=True,
            existing_record={
                "category_id": 102,
                "ifrc_family_id": 11,
                "ifrc_item_ref_id": 51,
                "default_uom_code": "EA",
            },
        )

        self.assertEqual(warnings, [])
        self.assertEqual(errors["ifrc_item_ref_id"], "Mapped items must retain an IFRC Item Reference.")

    @patch("masterdata.services.item_master._is_sqlite", return_value=False)
    @patch("masterdata.services.item_master._missing_uom_codes", return_value=[])
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

    @patch("masterdata.services.item_master._is_sqlite", return_value=False)
    @patch("masterdata.services.item_master._missing_uom_codes", return_value=[])
    @patch(
        "masterdata.services.item_master._fetch_ifrc_reference",
        return_value={"ifrc_item_ref_id": 51, "ifrc_family_id": 11, "ifrc_code": "WWTRTABL01", "reference_desc": "Water purification tablet", "status_code": "A"},
    )
    @patch(
        "masterdata.services.item_master._fetch_ifrc_family",
        return_value={"ifrc_family_id": 11, "category_id": 102, "group_code": "W", "family_code": "WTR", "family_label": "Water Treatment", "status_code": "A"},
    )
    def test_validate_item_payload_rejects_non_numeric_category_id(
        self,
        _mock_family,
        _mock_reference,
        _mock_missing_uoms,
        _mock_sqlite,
    ):
        errors, warnings = validate_item_payload(
            {
                "category_id": "abc",
                "ifrc_family_id": 11,
                "ifrc_item_ref_id": 51,
                "default_uom_code": "EA",
            },
            is_update=False,
        )

        self.assertEqual(warnings, [])
        self.assertEqual(errors["category_id"], "Invalid numeric ID.")

    @patch("masterdata.services.item_master._is_sqlite", return_value=False)
    @patch("masterdata.services.item_master._missing_uom_codes", return_value=[])
    @patch(
        "masterdata.services.item_master._fetch_ifrc_reference",
        return_value={"ifrc_item_ref_id": 51, "ifrc_family_id": 11, "ifrc_code": "WWTRTABL01", "reference_desc": "Water purification tablet", "status_code": "A"},
    )
    @patch("masterdata.services.item_master._fetch_ifrc_family")
    def test_validate_item_payload_rejects_non_numeric_family_id(
        self,
        mock_family,
        _mock_reference,
        _mock_missing_uoms,
        _mock_sqlite,
    ):
        errors, warnings = validate_item_payload(
            {
                "category_id": 102,
                "ifrc_family_id": "abc",
                "ifrc_item_ref_id": 51,
                "default_uom_code": "EA",
            },
            is_update=False,
        )

        self.assertEqual(warnings, [])
        self.assertEqual(errors["ifrc_family_id"], "Invalid numeric ID.")
        mock_family.assert_not_called()

    @patch("masterdata.services.item_master._is_sqlite", return_value=False)
    @patch("masterdata.services.item_master._missing_uom_codes", return_value=[])
    @patch("masterdata.services.item_master._fetch_ifrc_reference")
    @patch(
        "masterdata.services.item_master._fetch_ifrc_family",
        return_value={"ifrc_family_id": 11, "category_id": 102, "group_code": "W", "family_code": "WTR", "family_label": "Water Treatment", "status_code": "A"},
    )
    def test_validate_item_payload_rejects_non_numeric_reference_id(
        self,
        _mock_family,
        mock_reference,
        _mock_missing_uoms,
        _mock_sqlite,
    ):
        errors, warnings = validate_item_payload(
            {
                "category_id": 102,
                "ifrc_family_id": 11,
                "ifrc_item_ref_id": "abc",
                "default_uom_code": "EA",
            },
            is_update=False,
        )

        self.assertEqual(warnings, [])
        self.assertEqual(errors["ifrc_item_ref_id"], "Invalid numeric ID.")
        mock_reference.assert_not_called()

    @patch("masterdata.services.item_master._is_sqlite", return_value=False)
    @patch("masterdata.services.item_master._missing_uom_codes", return_value=[])
    @patch(
        "masterdata.services.item_master._fetch_ifrc_reference",
        return_value={"ifrc_item_ref_id": 51, "ifrc_family_id": 11, "ifrc_code": "WWTRTABL01", "reference_desc": "Water purification tablet", "status_code": "A"},
    )
    @patch(
        "masterdata.services.item_master._fetch_ifrc_family",
        return_value={"ifrc_family_id": 11, "category_id": 102, "group_code": "W", "family_code": "WTR", "family_label": "Water Treatment", "status_code": "I"},
    )
    def test_validate_item_payload_rejects_inactive_family_for_new_mapping(
        self,
        _mock_family,
        _mock_reference,
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
        self.assertEqual(errors["ifrc_family_id"], "Selected IFRC Family is inactive.")

    @patch("masterdata.services.item_master._is_sqlite", return_value=False)
    @patch("masterdata.services.item_master._missing_uom_codes", return_value=[])
    @patch(
        "masterdata.services.item_master._fetch_ifrc_reference",
        return_value={"ifrc_item_ref_id": 51, "ifrc_family_id": 11, "ifrc_code": "WWTRTABL01", "reference_desc": "Water purification tablet", "status_code": "I"},
    )
    @patch(
        "masterdata.services.item_master._fetch_ifrc_family",
        return_value={"ifrc_family_id": 11, "category_id": 102, "group_code": "W", "family_code": "WTR", "family_label": "Water Treatment", "status_code": "A"},
    )
    def test_validate_item_payload_rejects_inactive_reference_for_new_mapping(
        self,
        _mock_family,
        _mock_reference,
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
        self.assertEqual(errors["ifrc_item_ref_id"], "Selected IFRC Item Reference is inactive.")

    @patch("masterdata.services.item_master._is_sqlite", return_value=False)
    @patch("masterdata.services.item_master._missing_uom_codes", return_value=[])
    @patch(
        "masterdata.services.item_master._fetch_ifrc_reference",
        return_value={"ifrc_item_ref_id": 51, "ifrc_family_id": 11, "ifrc_code": "WWTRTABL01", "reference_desc": "Water purification tablet", "status_code": "I"},
    )
    @patch(
        "masterdata.services.item_master._fetch_ifrc_family",
        return_value={"ifrc_family_id": 11, "category_id": 102, "group_code": "W", "family_code": "WTR", "family_label": "Water Treatment", "status_code": "I"},
    )
    def test_validate_item_payload_allows_unchanged_inactive_mapping_on_existing_item_update(
        self,
        _mock_family,
        _mock_reference,
        _mock_missing_uoms,
        _mock_sqlite,
    ):
        errors, warnings = validate_item_payload(
            {"item_name": "UPDATED WATER TABS"},
            is_update=True,
            existing_record={
                "category_id": 102,
                "ifrc_family_id": 11,
                "ifrc_item_ref_id": 51,
                "default_uom_code": "EA",
            },
        )

        self.assertEqual(warnings, [])
        self.assertEqual(errors, {})


class ItemMasterWritePayloadTests(SimpleTestCase):
    @patch(
        "masterdata.services.item_master._fetch_ifrc_reference",
        return_value={"ifrc_item_ref_id": 51, "ifrc_family_id": 11, "ifrc_code": "WWTRTABL01", "reference_desc": "Water purification tablet", "status_code": "A"},
    )
    def test_create_payload_derives_canonical_item_code_and_preserves_client_code_as_legacy(
        self,
        _mock_reference,
    ):
        payload, reference_row = _build_item_write_payload(
            {
                "item_code": "HADR-WATER-TABS",
                "item_name": "WATER TABS",
                "category_id": 102,
                "ifrc_family_id": 11,
                "ifrc_item_ref_id": 51,
                "default_uom_code": "EA",
            },
            is_update=False,
        )

        self.assertEqual(reference_row["ifrc_item_ref_id"], 51)
        self.assertEqual(payload["item_code"], "WWTRTABL01")
        self.assertEqual(payload["legacy_item_code"], "HADR-WATER-TABS")

    @patch(
        "masterdata.services.item_master._fetch_ifrc_reference",
        return_value={"ifrc_item_ref_id": 51, "ifrc_family_id": 11, "ifrc_code": "WWTRTABL01", "reference_desc": "Water purification tablet", "status_code": "A"},
    )
    def test_update_payload_maps_legacy_item_to_canonical_and_preserves_existing_local_code(
        self,
        _mock_reference,
    ):
        payload, reference_row = _build_item_write_payload(
            {
                "ifrc_family_id": 11,
                "ifrc_item_ref_id": 51,
            },
            is_update=True,
            existing_record={
                "item_id": 77,
                "item_code": "HADR-WATER-TABS",
                "legacy_item_code": None,
                "ifrc_item_ref_id": None,
            },
        )

        self.assertEqual(reference_row["ifrc_item_ref_id"], 51)
        self.assertEqual(payload["item_code"], "WWTRTABL01")
        self.assertEqual(payload["legacy_item_code"], "HADR-WATER-TABS")


class ItemMasterReadErrorTests(SimpleTestCase):
    @patch("masterdata.services.item_master._is_sqlite", return_value=False)
    @patch("masterdata.services.item_master._schema_name", return_value="tenant_a")
    @patch("masterdata.services.item_master._safe_rollback")
    @patch("masterdata.services.item_master.connection")
    def test_get_item_record_returns_db_error_by_default(
        self,
        mock_connection,
        mock_safe_rollback,
        _mock_schema_name,
        _mock_sqlite,
    ):
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        cursor.execute.side_effect = DatabaseError("read failed")

        record, warnings = get_item_record(501)

        self.assertIsNone(record)
        self.assertEqual(warnings, ["db_error"])
        mock_safe_rollback.assert_called_once()

    @patch("masterdata.services.item_master._is_sqlite", return_value=False)
    @patch("masterdata.services.item_master._schema_name", return_value="tenant_a")
    @patch("masterdata.services.item_master._safe_rollback")
    @patch("masterdata.services.item_master.connection")
    def test_get_item_record_reraises_db_error_when_requested(
        self,
        mock_connection,
        mock_safe_rollback,
        _mock_schema_name,
        _mock_sqlite,
    ):
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        cursor.execute.side_effect = DatabaseError("read failed")

        with self.assertRaises(DatabaseError):
            get_item_record(501, raise_on_error=True)

        mock_safe_rollback.assert_called_once()


class ItemMasterTransactionalWriteTests(SimpleTestCase):
    @patch("masterdata.services.item_master._is_sqlite", return_value=False)
    @patch("masterdata.services.item_master._schema_name", return_value="tenant_a")
    @patch("masterdata.services.item_master._build_item_write_payload", return_value=({"default_uom_code": "EA"}, None))
    @patch("masterdata.services.item_master._normalize_item_uom_options", return_value=(None, {}))
    @patch("masterdata.services.item_master.create_record", return_value=(501, []))
    @patch("masterdata.services.item_master.get_item_record", side_effect=DatabaseError("reload failed"))
    @patch("masterdata.services.item_master._ensure_default_item_uom_option")
    @patch("masterdata.services.item_master._safe_rollback")
    @patch("masterdata.services.item_master.transaction.atomic", return_value=nullcontext())
    def test_create_item_record_uses_raise_on_error_for_post_write_reload(
        self,
        _mock_atomic,
        mock_safe_rollback,
        _mock_ensure_default,
        mock_get_item_record,
        _mock_create_record,
        _mock_normalize_uoms,
        _mock_build_payload,
        _mock_schema_name,
        _mock_sqlite,
    ):
        item_id, warnings = create_item_record({"item_name": "WATER TABS"}, "tester")

        self.assertIsNone(item_id)
        self.assertEqual(warnings, ["db_error"])
        mock_get_item_record.assert_called_once_with(501, raise_on_error=True)
        mock_safe_rollback.assert_called_once()

    @patch("masterdata.services.item_master._is_sqlite", return_value=False)
    @patch("masterdata.services.item_master._schema_name", return_value="tenant_a")
    @patch("masterdata.services.item_master._build_item_write_payload", return_value=({"default_uom_code": "EA"}, None))
    @patch("masterdata.services.item_master.update_record", return_value=(True, []))
    @patch("masterdata.services.item_master._normalize_item_uom_options", return_value=(None, {}))
    @patch("masterdata.services.item_master._ensure_default_item_uom_option")
    @patch("masterdata.services.item_master._tracked_item_state", return_value={"identity": {"item_code": "OLD"}})
    @patch(
        "masterdata.services.item_master.get_item_record",
        side_effect=[
            ({"item_id": 501, "default_uom_code": "EA"}, []),
            DatabaseError("reload failed"),
        ],
    )
    @patch("masterdata.services.item_master._safe_rollback")
    @patch("masterdata.services.item_master.transaction.atomic", return_value=nullcontext())
    def test_update_item_record_uses_raise_on_error_for_transactional_reads(
        self,
        _mock_atomic,
        mock_safe_rollback,
        mock_get_item_record,
        _mock_tracked_state,
        _mock_ensure_default,
        _mock_normalize_uoms,
        _mock_update_record,
        _mock_build_payload,
        _mock_schema_name,
        _mock_sqlite,
    ):
        success, warnings = update_item_record(501, {"item_name": "WATER TABS"}, "tester")

        self.assertFalse(success)
        self.assertEqual(warnings, ["db_error"])
        self.assertEqual(
            mock_get_item_record.call_args_list,
            [
                call(501, raise_on_error=True),
                call(501, raise_on_error=True),
            ],
        )
        mock_safe_rollback.assert_called_once()


class ItemMasterConflictTests(SimpleTestCase):
    @patch("masterdata.services.item_master._is_sqlite", return_value=False)
    @patch("masterdata.services.item_master.get_item_record", return_value=({"item_id": 91, "item_code": "WWTRTABL01"}, []))
    @patch("masterdata.services.item_master._find_duplicate_item_id", return_value=91)
    @patch(
        "masterdata.services.item_master._fetch_ifrc_reference",
        return_value={"ifrc_item_ref_id": 51, "ifrc_family_id": 11, "ifrc_code": "WWTRTABL01", "reference_desc": "Water purification tablet", "status_code": "A"},
    )
    def test_find_item_canonical_conflict_returns_existing_item_payload(
        self,
        _mock_reference,
        _mock_duplicate,
        _mock_get_item_record,
        _mock_sqlite,
    ):
        conflict = find_item_canonical_conflict({"ifrc_item_ref_id": 51})

        self.assertIsNotNone(conflict)
        self.assertEqual(conflict["code"], ITEM_CANONICAL_CONFLICT_CODE)
        self.assertEqual(conflict["item_code"], "WWTRTABL01")
        self.assertEqual(conflict["existing_item"]["item_id"], 91)

    @patch("masterdata.services.item_master._is_sqlite", return_value=False)
    @patch("masterdata.services.item_master._fetch_ifrc_reference")
    def test_find_item_canonical_conflict_returns_none_for_non_numeric_reference_id(
        self,
        mock_reference,
        _mock_sqlite,
    ):
        conflict = find_item_canonical_conflict({"ifrc_item_ref_id": "abc"})

        self.assertIsNone(conflict)
        mock_reference.assert_not_called()


class CatalogGovernanceServiceTests(SimpleTestCase):
    @patch("masterdata.services.catalog_governance.connection")
    def test_write_catalog_audit_uses_sql_null_for_missing_before_state(
        self,
        mock_connection,
    ):
        cursor = mock_connection.cursor.return_value.__enter__.return_value

        _write_catalog_audit(
            "tenant_a",
            table_key="ifrc_families",
            record_pk=11,
            change_action="CREATE",
            before_state=None,
            after_state={"status_code": "A"},
            changed_by_id="system",
            context={"source": "test"},
        )

        params = cursor.execute.call_args.args[1]
        self.assertIsNone(params[4])
        self.assertEqual(json.loads(params[5]), {"status_code": "A"})
        self.assertEqual(json.loads(params[6]), {"source": "test"})

    def test_validate_catalog_update_rejects_locked_reference_fields(self):
        errors, warnings = validate_catalog_update(
            "ifrc_item_references",
            {"ifrc_code": "WWTRTABLPW99"},
            {
                "ifrc_item_ref_id": 77,
                "ifrc_family_id": 11,
                "ifrc_code": "WWTRTABLTB01",
                "category_code": "TABL",
                "spec_segment": "TB",
            },
        )

        self.assertEqual(warnings, [])
        self.assertIn("ifrc_code", errors)
        self.assertIn("locked", errors["ifrc_code"])

    def test_catalog_detail_metadata_exposes_edit_guidance(self):
        guidance = catalog_detail_metadata("ifrc_families")

        self.assertTrue(guidance["edit_guidance"]["warning_required"])
        self.assertIn("replacement", guidance["edit_guidance"]["warning_text"])
        self.assertIn("family_code", guidance["edit_guidance"]["locked_fields"])

    def test_match_reference_category_returns_general_when_no_category_scores_above_zero(self):
        taxonomy = IFRCTaxonomy(
            groups={
                "W": GroupDef(
                    code="W",
                    label="WASH",
                    families={
                        "WTR": FamilyDef(
                            code="WTR",
                            label="Water Treatment",
                            categories={
                                "GENR": CategoryDef(code="GENR", label="General", items=["Miscellaneous supply"]),
                                "TABL": CategoryDef(code="TABL", label="Tablet", items=["Water purification tablet"]),
                            },
                        )
                    },
                )
            }
        )

        match = _match_reference_category(
            taxonomy=taxonomy,
            group_code="W",
            family_code="WTR",
            reference_desc="Unrelated fallback description",
        )

        self.assertEqual(match, {"category_code": "GENR", "category_label": "General"})

    @patch(
        "masterdata.services.catalog_governance._family_conflicts",
        return_value=({"exact_code_match": None, "exact_label_match": None, "near_matches": []}, []),
    )
    @patch("masterdata.services.catalog_governance._family_ai_candidate", return_value=None)
    def test_family_authoring_suggestion_is_deterministic_without_ai(
        self,
        _mock_ai_candidate,
        _mock_conflicts,
    ):
        payload, errors, warnings = suggest_ifrc_family_authoring({"family_label": "Water Treatment"})

        self.assertEqual(errors, {})
        self.assertEqual(warnings, [])
        self.assertEqual(payload["source"], "deterministic")
        self.assertEqual(payload["normalized"]["group_code"], "W")
        self.assertEqual(payload["normalized"]["family_code"], "WTR")

    @patch(
        "masterdata.services.catalog_governance._family_conflicts",
        return_value=({"exact_code_match": None, "exact_label_match": None, "near_matches": []}, []),
    )
    @patch("masterdata.services.catalog_governance._family_ai_candidate", return_value=None)
    def test_family_authoring_with_explicit_group_uses_three_character_family_code(
        self,
        _mock_ai_candidate,
        _mock_conflicts,
    ):
        payload, errors, warnings = suggest_ifrc_family_authoring(
            {
                "family_label": "Emergency Communications Support",
                "group_code": "W",
            }
        )

        self.assertEqual(errors, {})
        self.assertEqual(warnings, [])
        self.assertEqual(payload["normalized"]["group_code"], "W")
        self.assertEqual(payload["normalized"]["family_code"], "ECS")

    @patch("masterdata.services.validation.check_fk_exists", return_value=(True, []))
    @patch("masterdata.services.validation.check_uniqueness", return_value=(True, []))
    def test_ifrc_family_validation_rejects_non_canonical_family_code_length(
        self,
        _mock_check_uniqueness,
        _mock_check_fk_exists,
    ):
        errors = validate_record(
            TABLE_REGISTRY["ifrc_families"],
            {
                "category_id": 102,
                "group_code": "W",
                "group_label": "WASH",
                "family_code": "WT",
                "family_label": "Water Treatment",
                "status_code": "A",
            },
        )

        self.assertEqual(
            errors["family_code"],
            "Family Code must be exactly 3 uppercase letters or digits.",
        )

    @patch("masterdata.services.catalog_governance._is_sqlite", return_value=False)
    @patch(
        "masterdata.services.catalog_governance._reference_conflicts",
        return_value=({"exact_code_match": None, "exact_desc_match": None, "near_matches": []}, []),
    )
    @patch("masterdata.services.catalog_governance._reference_ai_candidate", return_value=None)
    @patch(
        "masterdata.services.catalog_governance._fetch_ifrc_family",
        return_value={
            "ifrc_family_id": 11,
            "group_code": "W",
            "family_code": "WTR",
            "family_label": "Water Treatment",
        },
    )
    def test_reference_authoring_suggestion_falls_back_to_deterministic_logic(
        self,
        _mock_family,
        _mock_ai_candidate,
        _mock_conflicts,
        _mock_sqlite,
    ):
        payload, errors, warnings = suggest_ifrc_reference_authoring(
            {
                "ifrc_family_id": 11,
                "reference_desc": "Water purification tablet",
                "form": "tablet",
            }
        )

        self.assertEqual(errors, {})
        self.assertEqual(warnings, [])
        self.assertEqual(payload["source"], "deterministic")
        self.assertEqual(payload["normalized"]["form"], "TABLET")
        self.assertEqual(payload["normalized"]["spec_segment"], "TB00")
        self.assertEqual(payload["normalized"]["ifrc_code"], "WWTRTABLTB00")


class ItemMasterSeedPayloadTests(SimpleTestCase):
    def test_seed_payload_is_deterministic(self):
        first = build_ifrc_taxonomy_seed_payload()
        second = build_ifrc_taxonomy_seed_payload()

        self.assertEqual(first, second)
        self.assertEqual(len(first["categories"]), 14)
        self.assertGreater(len(first["families"]), 0)
        self.assertGreater(len(first["references"]), len(first["families"]))
        self.assertIn("size_weight", first["references"][0])
        self.assertIn("form", first["references"][0])
        self.assertIn("material", first["references"][0])

    def test_seed_payload_includes_governed_corned_beef_variants(self):
        payload = build_ifrc_taxonomy_seed_payload()
        references_by_desc = {
            reference["reference_desc"]: reference
            for reference in payload["references"]
            if reference["reference_desc"].startswith("Corned beef, canned")
        }

        self.assertEqual(references_by_desc["Corned beef, canned, 200 g"]["ifrc_code"], "FCANMEATCB200G")
        self.assertEqual(references_by_desc["Corned beef, canned, 200 g"]["size_weight"], "200 G")
        self.assertEqual(references_by_desc["Corned beef, canned, 500 g"]["ifrc_code"], "FCANMEATCB500G")
        self.assertEqual(references_by_desc["Corned beef, canned, 500 g"]["size_weight"], "500 G")

    def test_seed_payload_preserves_catalogue_item_metadata(self):
        payload = build_ifrc_taxonomy_seed_payload()
        references_by_desc = {
            reference["reference_desc"]: reference
            for reference in payload["references"]
        }

        self.assertEqual(
            references_by_desc["Water purification tablet, aquatab"]["material"],
            "CHLORINE",
        )
        self.assertEqual(
            references_by_desc["Water purification tablet, aquatab"]["form"],
            "TABLET",
        )

    def test_seed_payload_uses_item_metadata_for_governed_codes_generically(self):
        taxonomy = IFRCTaxonomy(
            groups={
                "W": GroupDef(
                    code="W",
                    label="WASH",
                    families={
                        "WTR": FamilyDef(
                            code="WTR",
                            label="Water Treatment",
                            categories={
                                "PURI": CategoryDef(
                                    code="PURI",
                                    label="Water Purification",
                                    items=["Water purification tablet, 500 mg"],
                                    item_metadata={
                                        "WATER PURIFICATION TABLET, 500 MG": {
                                            "IFRC_CODE": "WWTRPURIAQ500MG",
                                            "SIZE_WEIGHT": "500 MG",
                                            "FORM": "TABLET",
                                            "MATERIAL": "CHLORINE",
                                            "SPEC_SEGMENT": "TB500",
                                        }
                                    },
                                )
                            },
                        )
                    },
                )
            }
        )

        payload = build_ifrc_taxonomy_seed_payload(taxonomy)

        self.assertEqual(
            payload["references"],
            [
                {
                    "group_code": "W",
                    "family_code": "WTR",
                    "ifrc_code": "WWTRPURIAQ500MG",
                    "reference_desc": "Water purification tablet, 500 mg",
                    "category_code": "PURI",
                    "category_label": "Water Purification",
                    "spec_segment": "TB500",
                    "size_weight": "500 MG",
                    "form": "TABLET",
                    "material": "CHLORINE",
                    "source_version": payload["references"][0]["source_version"],
                }
            ],
        )

    def test_reference_codes_are_stable_across_item_reordering(self):
        taxonomy_a = IFRCTaxonomy(
            groups={
                "W": GroupDef(
                    code="W",
                    label="WASH",
                    families={
                        "WTR": FamilyDef(
                            code="WTR",
                            label="Water Treatment",
                            categories={
                                "TEST": CategoryDef(
                                    code="TEST",
                                    label="Test",
                                    items=["Alpha supply", "Beta supply"],
                                )
                            },
                        )
                    },
                )
            }
        )
        taxonomy_b = IFRCTaxonomy(
            groups={
                "W": GroupDef(
                    code="W",
                    label="WASH",
                    families={
                        "WTR": FamilyDef(
                            code="WTR",
                            label="Water Treatment",
                            categories={
                                "TEST": CategoryDef(
                                    code="TEST",
                                    label="Test",
                                    items=["Beta supply", "Alpha supply"],
                                )
                            },
                        )
                    },
                )
            }
        )

        payload_a = build_ifrc_taxonomy_seed_payload(taxonomy_a)
        payload_b = build_ifrc_taxonomy_seed_payload(taxonomy_b)

        codes_a = {reference["reference_desc"]: reference["ifrc_code"] for reference in payload_a["references"]}
        codes_b = {reference["reference_desc"]: reference["ifrc_code"] for reference in payload_b["references"]}

        self.assertEqual(codes_a, codes_b)
        self.assertNotEqual(codes_a["Alpha supply"], codes_a["Beta supply"])


class ItemMasterReferenceSyncTests(SimpleTestCase):
    def test_sync_categories_only_deactivates_rows_owned_by_sync_actor(self):
        cursor = MagicMock()
        categories = [
            {
                "category_id": 101,
                "category_code": "FOOD_NUTRITION",
                "category_desc": "Food & Nutrition",
            },
            {
                "category_id": 102,
                "category_code": "WASH",
                "category_desc": "WASH",
            },
        ]

        _sync_categories(cursor, "tenant_a", categories, "system")

        self.assertEqual(cursor.execute.call_count, 2)
        deactivate_sql = cursor.execute.call_args_list[1].args[0]
        deactivate_params = cursor.execute.call_args_list[1].args[1]
        self.assertIn("AND itemcatg.update_by_id = %s", deactivate_sql)
        self.assertEqual(
            deactivate_params,
            ["FOOD_NUTRITION", "WASH", "system", "system"],
        )

    def test_sync_references_reuses_existing_code_for_same_reference(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = [
            ("W", "WTR", "TABL", "Water purification tablet", "TB", "WWTRTABLTB01"),
        ]
        references = [
            {
                "group_code": "W",
                "family_code": "WTR",
                "ifrc_code": "WWTRTABLTBDEADBEEF",
                "reference_desc": "Water purification tablet",
                "category_code": "TABL",
                "category_label": "Tablet",
                "spec_segment": "TB",
                "size_weight": "",
                "form": "TABLET",
                "material": "",
                "source_version": "2024",
            }
        ]

        _sync_references(cursor, "tenant_a", references, {("W", "WTR"): 11}, "system")

        self.assertEqual(cursor.execute.call_count, 3)
        insert_params = cursor.execute.call_args_list[1].args[1]
        deactivate_params = cursor.execute.call_args_list[2].args[1]
        self.assertEqual(insert_params[1], "WWTRTABLTB01")
        self.assertEqual(deactivate_params[0], "WWTRTABLTB01")


class ItemMasterViewDispatchTests(SimpleTestCase):
    @patch("masterdata.views.get_item_record", return_value=({"item_id": 501, "item_code": "WWTRTABL01"}, []))
    @patch("masterdata.views.create_item_record", return_value=(501, []))
    @patch("masterdata.views.find_item_canonical_conflict", return_value=None)
    @patch("masterdata.views.validate_item_payload", return_value=({}, []))
    @patch("masterdata.views.validate_record", return_value={})
    def test_handle_item_create_uses_dedicated_service(
        self,
        _mock_validate_record,
        _mock_validate_item_payload,
        _mock_find_conflict,
        mock_create_item_record,
        _mock_get_item_record,
    ):
        request = SimpleNamespace(
            data={"item_name": "WATER TABS", "category_id": 102, "ifrc_family_id": 11, "ifrc_item_ref_id": 51},
            user=SimpleNamespace(user_id="tester"),
        )

        response = views._handle_create(request, TABLE_REGISTRY["items"])

        self.assertEqual(response.status_code, 201)
        mock_create_item_record.assert_called_once()
        self.assertEqual(response.data["record"]["item_id"], 501)

    @patch("masterdata.views.find_item_canonical_conflict", return_value={
        "code": ITEM_CANONICAL_CONFLICT_CODE,
        "ifrc_item_ref_id": 51,
        "item_code": "WWTRTABL01",
        "existing_item": {"item_id": 99, "item_code": "WWTRTABL01"},
    })
    @patch("masterdata.views.validate_item_payload", return_value=({}, []))
    @patch("masterdata.views.validate_record", return_value={})
    def test_handle_item_create_returns_conflict_response_for_duplicate_canonical_code(
        self,
        _mock_validate_record,
        _mock_validate_item_payload,
        _mock_find_conflict,
    ):
        request = SimpleNamespace(
            data={"item_name": "WATER TABS", "category_id": 102, "ifrc_family_id": 11, "ifrc_item_ref_id": 51},
            user=SimpleNamespace(user_id="tester"),
        )

        response = views._handle_create(request, TABLE_REGISTRY["items"])

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["errors"][ITEM_CANONICAL_CONFLICT_CODE]["existing_item"]["item_id"], 99)

    @patch(
        "masterdata.views.create_item_record",
        return_value=(
            None,
            [
                "db_error",
                "db_constraint",
                "db_unique_violation",
            ],
        ),
    )
    @patch("masterdata.views.find_item_canonical_conflict", return_value=None)
    @patch("masterdata.views.validate_item_payload", return_value=({}, []))
    @patch("masterdata.views.validate_record", return_value={})
    def test_handle_item_create_surfaces_db_failure_diagnostic(
        self,
        _mock_validate_record,
        _mock_validate_item_payload,
        _mock_find_conflict,
        _mock_create_item_record,
    ):
        request = SimpleNamespace(
            data={"item_name": "WATER TABS", "category_id": 102, "ifrc_family_id": 11, "ifrc_item_ref_id": 51},
            user=SimpleNamespace(user_id="tester"),
        )

        response = views._handle_create(request, TABLE_REGISTRY["items"])

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.data["detail"], "Failed to create item.")
        self.assertEqual(
            response.data["warnings"],
            [
                "db_error",
                "db_constraint",
                "db_unique_violation",
            ],
        )
        self.assertIn("unique database constraint", response.data["diagnostic"])

    @patch("masterdata.views.create_item_record", return_value=(None, ["db_unavailable"]))
    @patch("masterdata.views.find_item_canonical_conflict", return_value=None)
    @patch("masterdata.views.validate_item_payload", return_value=({}, []))
    @patch("masterdata.views.validate_record", return_value={})
    def test_handle_item_create_returns_service_unavailable_for_transient_failure(
        self,
        _mock_validate_record,
        _mock_validate_item_payload,
        _mock_find_conflict,
        _mock_create_item_record,
    ):
        request = SimpleNamespace(
            data={"item_name": "WATER TABS", "category_id": 102, "ifrc_family_id": 11, "ifrc_item_ref_id": 51},
            user=SimpleNamespace(user_id="tester"),
        )

        response = views._handle_create(request, TABLE_REGISTRY["items"])

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data["detail"], "Item creation is temporarily unavailable.")
        self.assertEqual(response.data["warnings"], ["db_unavailable"])
        self.assertIn("temporarily unavailable", response.data["diagnostic"])
        self.assertIn("db_unavailable", response.data["diagnostic"])

    @patch(
        "masterdata.views.get_item_record",
        return_value=(
            None,
            ["db_error"],
        ),
    )
    @patch("masterdata.views.create_item_record", return_value=(501, []))
    @patch("masterdata.views.find_item_canonical_conflict", return_value=None)
    @patch("masterdata.views.validate_item_payload", return_value=({}, []))
    @patch("masterdata.views.validate_record", return_value={})
    def test_handle_item_create_surfaces_created_item_reload_diagnostic(
        self,
        _mock_validate_record,
        _mock_validate_item_payload,
        _mock_find_conflict,
        _mock_create_item_record,
        _mock_get_item_record,
    ):
        request = SimpleNamespace(
            data={"item_name": "WATER TABS", "category_id": 102, "ifrc_family_id": 11, "ifrc_item_ref_id": 51},
            user=SimpleNamespace(user_id="tester"),
        )

        response = views._handle_create(request, TABLE_REGISTRY["items"])

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.data["detail"], "Failed to load created item.")
        self.assertIn("database error", response.data["diagnostic"])
        self.assertEqual(
            response.data["warnings"],
            ["db_error"],
        )

    @patch(
        "masterdata.views.get_item_record",
        side_effect=[
            (
                {
                    "item_id": 501,
                    "item_code": "WWTRTABL01",
                    "version_nbr": 1,
                },
                [],
            ),
            (None, ["db_unavailable"]),
        ],
    )
    @patch("masterdata.views.update_item_record", return_value=(True, []))
    @patch("masterdata.views.find_item_canonical_conflict", return_value=None)
    @patch("masterdata.views.validate_item_payload", return_value=({}, []))
    @patch("masterdata.views.validate_record", return_value={})
    def test_handle_item_update_returns_503_when_updated_item_reload_is_transient(
        self,
        _mock_validate_record,
        _mock_validate_item_payload,
        _mock_find_conflict,
        _mock_update_item_record,
        _mock_get_item_record,
    ):
        request = SimpleNamespace(
            data={"item_name": "WATER TABS", "version_nbr": 1},
            user=SimpleNamespace(user_id="tester"),
        )

        response = views._handle_update(request, TABLE_REGISTRY["items"], 501)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.data["detail"],
            "Loading the updated item is temporarily unavailable.",
        )
        self.assertEqual(response.data["warnings"], ["db_unavailable"])
        self.assertIn("db_unavailable", response.data["diagnostic"])


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
    @patch("masterdata.views.list_ifrc_family_lookup", return_value=([], []))
    def test_family_lookup_passes_include_current_value_for_inactive_saved_selection(
        self,
        mock_lookup,
        _mock_permission,
    ):
        request = self.factory.get(
            "/api/v1/masterdata/items/ifrc-families/lookup",
            {"category_id": "102", "include_current_value": "11", "active_only": "true"},
        )
        force_authenticate(request, user=self.user)

        response = views.item_ifrc_family_lookup(request)

        self.assertEqual(response.status_code, 200)
        mock_lookup.assert_called_once_with(
            category_id="102",
            search=None,
            active_only=True,
            include_value="11",
        )

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


    @patch("masterdata.permissions.MasterDataPermission.has_permission", return_value=True)
    @patch(
        "masterdata.views.list_ifrc_reference_lookup",
        return_value=(
            [
                {
                    "value": 77,
                    "label": "Water purification tablet",
                    "ifrc_code": "WWTRTABLTB01",
                    "ifrc_family_id": 11,
                    "family_code": "WTR",
                    "family_label": "Water Treatment",
                    "category_code": "TABL",
                    "category_label": "Tablet",
                    "spec_segment": "TB",
                    "size_weight": "500 G",
                    "form": "TABLET",
                    "material": "CHLORINE",
                }
            ],
            [],
        ),
    )
    def test_reference_lookup_returns_level3_metadata(self, _mock_lookup, _mock_permission):
        request = self.factory.get(
            "/api/v1/masterdata/items/ifrc-references/lookup",
            {"ifrc_family_id": "11", "search": "tablet"},
        )
        force_authenticate(request, user=self.user)

        response = views.item_ifrc_reference_lookup(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["items"][0]["size_weight"], "500 G")
        self.assertEqual(response.data["items"][0]["form"], "TABLET")
        self.assertEqual(response.data["items"][0]["material"], "CHLORINE")

    @patch("masterdata.permissions.MasterDataPermission.has_permission", return_value=True)
    @patch("masterdata.views.list_ifrc_reference_lookup", return_value=([], []))
    def test_reference_lookup_passes_include_value_for_inactive_saved_selection(
        self,
        mock_lookup,
        _mock_permission,
    ):
        request = self.factory.get(
            "/api/v1/masterdata/items/ifrc-references/lookup",
            {"ifrc_family_id": "11", "include_value": "77", "active_only": "true"},
        )
        force_authenticate(request, user=self.user)

        response = views.item_ifrc_reference_lookup(request)

        self.assertEqual(response.status_code, 200)
        mock_lookup.assert_called_once_with(
            ifrc_family_id="11",
            search=None,
            active_only=True,
            include_value="77",
            limit=views.DEFAULT_PAGE_LIMIT,
        )

    @patch("masterdata.permissions.MasterDataPermission.has_permission", return_value=True)
    @patch("masterdata.views.list_ifrc_reference_lookup", return_value=([], []))
    def test_reference_lookup_passes_include_current_value_for_inactive_saved_selection(
        self,
        mock_lookup,
        _mock_permission,
    ):
        request = self.factory.get(
            "/api/v1/masterdata/items/ifrc-references/lookup",
            {"ifrc_family_id": "11", "include_current_value": "77", "active_only": "true"},
        )
        force_authenticate(request, user=self.user)

        response = views.item_ifrc_reference_lookup(request)

        self.assertEqual(response.status_code, 200)
        mock_lookup.assert_called_once_with(
            ifrc_family_id="11",
            search=None,
            active_only=True,
            include_value="77",
            limit=views.DEFAULT_PAGE_LIMIT,
        )


class CatalogMaintenanceViewTests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.user = SimpleNamespace(
            is_authenticated=True,
            user_id="catalog-admin",
            roles=[],
            permissions=[
                views.PERM_MASTERDATA_VIEW,
                views.PERM_MASTERDATA_CREATE,
                views.PERM_MASTERDATA_EDIT,
            ],
        )

    @patch("masterdata.permissions.MasterDataPermission.has_permission", return_value=True)
    @patch(
        "masterdata.views.list_records",
        return_value=(
            [{"ifrc_family_id": 11, "family_label": "Water Treatment", "status_code": "A"}],
            1,
            [],
        ),
    )
    def test_ifrc_family_list_is_exposed_via_generic_masterdata_endpoint(
        self,
        mock_list_records,
        _mock_permission,
    ):
        request = self.factory.get("/api/v1/masterdata/ifrc_families/")
        force_authenticate(request, user=self.user)

        response = views.master_list_create(request, "ifrc_families")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["results"][0]["family_label"], "Water Treatment")
        mock_list_records.assert_called_once_with(
            "ifrc_families",
            status_filter=None,
            search=None,
            order_by=None,
            limit=views.DEFAULT_PAGE_LIMIT,
            offset=0,
        )

    @patch("masterdata.permissions.MasterDataPermission.has_permission", return_value=True)
    @patch(
        "masterdata.views.get_record",
        return_value=(
            {
                "ifrc_family_id": 11,
                "group_code": "W",
                "group_label": "WASH",
                "family_code": "WTR",
                "family_label": "Water Treatment",
                "status_code": "A",
            },
            [],
        ),
    )
    def test_ifrc_family_detail_exposes_edit_guidance(self, _mock_get_record, _mock_permission):
        request = self.factory.get("/api/v1/masterdata/ifrc_families/11")
        force_authenticate(request, user=self.user)

        response = views.master_detail_update(request, "ifrc_families", "11")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["edit_guidance"]["warning_required"])
        self.assertIn("family_code", response.data["edit_guidance"]["locked_fields"])

    @patch("masterdata.permissions.MasterDataPermission.has_permission", return_value=True)
    @patch(
        "masterdata.views.get_record",
        return_value=(
            {
                "ifrc_item_ref_id": 77,
                "ifrc_family_id": 11,
                "ifrc_code": "WWTRTABLTB01",
                "reference_desc": "Water purification tablet",
                "size_weight": "500 G",
                "form": "TABLET",
                "material": "CHLORINE",
                "status_code": "A",
            },
            [],
        ),
    )
    @patch("masterdata.views.create_catalog_record", return_value=(77, []))
    @patch("masterdata.views.validate_record", return_value={})
    def test_ifrc_reference_create_uses_governed_catalog_service(
        self,
        _mock_validate_record,
        mock_create_catalog_record,
        _mock_get_record,
        _mock_permission,
    ):
        request = self.factory.post(
            "/api/v1/masterdata/ifrc_item_references/",
            {
                "ifrc_family_id": 11,
                "ifrc_code": "WWTRTABLTB01",
                "reference_desc": "Water purification tablet",
                "category_code": "TABL",
                "category_label": "Tablet",
                "spec_segment": "TB",
                "size_weight": "500 g",
                "form": "tablet",
                "material": "chlorine",
                "status_code": "A",
            },
            format="json",
        )
        force_authenticate(request, user=self.user)

        response = views.master_list_create(request, "ifrc_item_references")

        self.assertEqual(response.status_code, 201)
        forwarded_payload = mock_create_catalog_record.call_args.args[1]
        self.assertEqual(forwarded_payload["size_weight"], "500 g")
        self.assertEqual(forwarded_payload["form"], "tablet")
        self.assertEqual(forwarded_payload["material"], "chlorine")
        self.assertEqual(response.data["record"]["ifrc_item_ref_id"], 77)

    @patch("masterdata.permissions.MasterDataPermission.has_permission", return_value=True)
    @patch("masterdata.views.validate_record", return_value={})
    @patch(
        "masterdata.views.get_record",
        return_value=(
            {
                "ifrc_item_ref_id": 77,
                "ifrc_family_id": 11,
                "ifrc_code": "WWTRTABLTB01",
                "category_code": "TABL",
                "spec_segment": "TB",
                "reference_desc": "Water purification tablet",
                "status_code": "A",
            },
            [],
        ),
    )
    def test_reference_update_rejects_locked_canonical_field_change(
        self,
        _mock_get_record,
        _mock_validate_record,
        _mock_permission,
    ):
        request = self.factory.patch(
            "/api/v1/masterdata/ifrc_item_references/77",
            {"ifrc_code": "WWTRTABLPW99"},
            format="json",
        )
        force_authenticate(request, user=self.user)

        response = views.master_detail_update(request, "ifrc_item_references", "77")

        self.assertEqual(response.status_code, 400)
        self.assertIn("ifrc_code", response.data["errors"])

    @patch("masterdata.permissions.MasterDataPermission.has_permission", return_value=True)
    @patch(
        "masterdata.views.suggest_ifrc_family_authoring",
        return_value=({"source": "deterministic", "normalized": {"group_code": "W", "family_code": "WTR"}}, {}, []),
    )
    def test_family_suggest_endpoint_returns_authoring_payload(self, _mock_suggest, _mock_permission):
        request = self.factory.post(
            "/api/v1/masterdata/ifrc-families/suggest",
            {"family_label": "Water Treatment"},
            format="json",
        )
        force_authenticate(request, user=self.user)

        response = views.ifrc_family_suggest(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["source"], "deterministic")
        self.assertEqual(response.data["normalized"]["family_code"], "WTR")

    @patch("masterdata.permissions.MasterDataPermission.has_permission", return_value=True)
    @patch(
        "masterdata.views.create_catalog_replacement",
        return_value=({"record": {"ifrc_item_ref_id": 91, "ifrc_code": "WWTRTABLTB02"}, "replacement_for_pk": 77, "retire_original_requested": True, "retired_original": False}, []),
    )
    def test_reference_replacement_endpoint_returns_created_record(self, _mock_replace, _mock_permission):
        request = self.factory.post(
            "/api/v1/masterdata/ifrc-item-references/77/replacement",
            {"ifrc_code": "WWTRTABLTB02", "retire_original": True},
            format="json",
        )
        force_authenticate(request, user=self.user)

        response = views.ifrc_item_reference_replacement(request, "77")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["record"]["ifrc_item_ref_id"], 91)
        self.assertEqual(response.data["replacement_for_pk"], 77)


class UnifiedItemMasterMigrationSchemaTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.migration_0005 = importlib.import_module(
            "masterdata.migrations.0005_unified_item_master_phase1"
        )
        cls.migration_0006 = importlib.import_module(
            "masterdata.migrations.0006_canonical_item_code_phase1"
        )
        cls.migration_0007 = importlib.import_module(
            "masterdata.migrations.0007_ifrc_reference_metadata_phase1"
        )
        cls.migration_0008 = importlib.import_module(
            "masterdata.migrations.0008_catalog_governance_audit"
        )

    def test_0005_forwards_sql_uses_configured_schema(self):
        cursor = MagicMock()
        connection = MagicMock(vendor="postgresql")
        connection.cursor.return_value.__enter__.return_value = cursor
        categories = self.migration_0005._FROZEN_ITEM_MASTER_SEED_PAYLOAD["categories"]
        families = self.migration_0005._FROZEN_ITEM_MASTER_SEED_PAYLOAD["families"]
        cursor.fetchall.side_effect = [
            [(row["category_code"], row["category_id"]) for row in categories],
            [
                (row["group_code"], row["family_code"], index)
                for index, row in enumerate(families, start=1)
            ],
        ]
        schema_editor = SimpleNamespace(
            connection=connection,
            execute=MagicMock(),
        )
        with patch.object(self.migration_0005, "_legacy_item_table_exists", return_value=True):
            with patch.dict("os.environ", {"DMIS_DB_SCHEMA": "tenant_a"}):
                self.migration_0005._forwards(None, schema_editor)

        executed_sql = schema_editor.execute.call_args.args[0]
        self.assertIn('CREATE TABLE IF NOT EXISTS "tenant_a".ifrc_family', executed_sql)
        self.assertIn('ALTER TABLE "tenant_a".item', executed_sql)

        seed_sql_statements = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertTrue(
            any('INSERT INTO "tenant_a".itemcatg' in sql for sql in seed_sql_statements)
        )
        self.assertTrue(
            any('INSERT INTO "tenant_a".ifrc_family' in sql for sql in seed_sql_statements)
        )
        reference_seed_sql = next(
            sql
            for sql in seed_sql_statements
            if 'INSERT INTO "tenant_a".ifrc_item_reference' in sql
        )
        self.assertNotIn("size_weight", reference_seed_sql)
        self.assertNotIn("idx_ifrc_item_reference_code", executed_sql)

    def test_0006_forwards_sql_adds_legacy_code_and_reference_uniqueness(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        connection = MagicMock(vendor="postgresql")
        connection.ops.quote_name.side_effect = lambda name: f'"{name}"'
        connection.cursor.return_value.__enter__.return_value = cursor
        schema_editor = SimpleNamespace(
            connection=connection,
            execute=MagicMock(),
        )
        with patch.object(self.migration_0006, "_legacy_item_table_exists", return_value=True):
            with patch.dict("os.environ", {"DMIS_DB_SCHEMA": "tenant_a"}):
                self.migration_0006._forwards(None, schema_editor)

        executed_sql = schema_editor.execute.call_args.args[0]
        duplicate_check_sql = cursor.execute.call_args.args[0]
        self.assertIn('FROM "tenant_a"."item"', duplicate_check_sql)
        self.assertIn("GROUP BY ifrc_item_ref_id", duplicate_check_sql)
        self.assertIn("HAVING COUNT(*) > 1", duplicate_check_sql)
        self.assertIn("ADD COLUMN IF NOT EXISTS legacy_item_code", executed_sql)
        self.assertIn("CREATE UNIQUE INDEX IF NOT EXISTS ux_item_ifrc_item_ref_id_unique", executed_sql)
        self.assertIn('UPDATE "tenant_a".item AS item', executed_sql)

    def test_0006_backwards_sql_restores_legacy_item_code_before_drop(self):
        connection = SimpleNamespace(
            vendor="postgresql",
            ops=SimpleNamespace(quote_name=lambda name: f'"{name}"'),
        )
        schema_editor = SimpleNamespace(
            connection=connection,
            execute=MagicMock(),
        )

        with patch.object(self.migration_0006, "_legacy_item_table_exists", return_value=True):
            with patch.dict("os.environ", {"DMIS_DB_SCHEMA": "tenant_a"}):
                self.migration_0006._backwards(None, schema_editor)

        executed_sql = schema_editor.execute.call_args.args[0]
        update_position = executed_sql.index('UPDATE "tenant_a".item')
        unique_index_drop_position = executed_sql.index(
            'DROP INDEX IF EXISTS "tenant_a".ux_item_ifrc_item_ref_id_unique'
        )
        legacy_index_drop_position = executed_sql.index(
            'DROP INDEX IF EXISTS "tenant_a".idx_item_legacy_item_code'
        )
        drop_column_position = executed_sql.index("DROP COLUMN IF EXISTS legacy_item_code")

        self.assertLess(update_position, unique_index_drop_position)
        self.assertLess(unique_index_drop_position, legacy_index_drop_position)
        self.assertLess(legacy_index_drop_position, drop_column_position)
        self.assertIn("SET item_code = legacy_item_code", executed_sql)

    def test_0006_legacy_item_table_exists_quotes_mixed_case_schema_in_to_regclass(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = ('"TenantA"."item"',)
        connection = MagicMock(vendor="postgresql")
        connection.ops.quote_name.side_effect = lambda name: f'"{name}"'
        connection.cursor.return_value.__enter__.return_value = cursor
        schema_editor = SimpleNamespace(connection=connection)

        with patch.dict("os.environ", {"DMIS_DB_SCHEMA": "TenantA"}):
            exists = self.migration_0006._legacy_item_table_exists(schema_editor)

        self.assertTrue(exists)
        self.assertEqual(cursor.execute.call_args.args[1], ['"TenantA"."item"'])

    def test_0006_schema_name_accepts_valid_current_schema_fallback(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = ("tenant_a",)
        connection = MagicMock(vendor="postgresql")
        connection.cursor.return_value.__enter__.return_value = cursor
        schema_editor = SimpleNamespace(connection=connection)

        with patch.dict("os.environ", {}, clear=True):
            schema = self.migration_0006._schema_name(schema_editor)

        self.assertEqual(schema, "tenant_a")

    def test_0006_schema_name_rejects_invalid_current_schema_fallback(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = ('tenant_a"; DROP SCHEMA public; --',)
        connection = MagicMock(vendor="postgresql")
        connection.cursor.return_value.__enter__.return_value = cursor
        schema_editor = SimpleNamespace(connection=connection)

        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(RuntimeError) as exc:
                self.migration_0006._schema_name(schema_editor)

        self.assertIn("Invalid database schema name", str(exc.exception))

    def test_0006_forwards_aborts_when_duplicate_reference_mappings_exist(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = [(51, [7, 9]), (77, [12, 18])]
        connection = MagicMock(vendor="postgresql")
        connection.ops.quote_name.side_effect = lambda name: f'"{name}"'
        connection.cursor.return_value.__enter__.return_value = cursor
        schema_editor = SimpleNamespace(
            connection=connection,
            execute=MagicMock(),
        )

        with patch.object(self.migration_0006, "_legacy_item_table_exists", return_value=True):
            with patch.dict("os.environ", {"DMIS_DB_SCHEMA": "tenant_a"}):
                with self.assertRaises(RuntimeError) as exc:
                    self.migration_0006._forwards(None, schema_editor)

        self.assertIn("ux_item_ifrc_item_ref_id_unique", str(exc.exception))
        self.assertIn("51: [7, 9]", str(exc.exception))
        self.assertIn("77: [12, 18]", str(exc.exception))
        schema_editor.execute.assert_not_called()

    def test_0006_duplicate_mapping_check_rejects_invalid_schema_argument(self):
        cursor = MagicMock()
        connection = MagicMock(vendor="postgresql")
        connection.ops.quote_name.side_effect = lambda name: f'"{name}"'
        connection.cursor.return_value.__enter__.return_value = cursor
        schema_editor = SimpleNamespace(connection=connection)

        with self.assertRaises(RuntimeError) as exc:
            self.migration_0006._assert_no_duplicate_ifrc_item_reference_mappings(
                schema_editor,
                'tenant_a"; DROP SCHEMA public; --',
            )

        self.assertIn("Invalid database schema name for duplicate mapping check", str(exc.exception))
        cursor.execute.assert_not_called()

    def test_0007_forwards_sql_adds_reference_metadata_columns(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = [
            (77, "Water purification tablet 500 g plastic", "", "", "")
        ]
        connection = MagicMock(vendor="postgresql")
        connection.ops.quote_name.side_effect = lambda name: f'"{name}"'
        connection.cursor.return_value.__enter__.return_value = cursor
        schema_editor = SimpleNamespace(
            connection=connection,
            execute=MagicMock(),
        )
        with patch.object(self.migration_0007, "_relation_exists", return_value=True):
            with patch.dict("os.environ", {"DMIS_DB_SCHEMA": "tenant_a"}):
                self.migration_0007._forwards(None, schema_editor)

        executed_sql = schema_editor.execute.call_args.args[0]
        self.assertIn('ALTER TABLE "tenant_a".ifrc_item_reference', executed_sql)
        self.assertIn("ADD COLUMN IF NOT EXISTS size_weight", executed_sql)
        self.assertIn("ADD COLUMN IF NOT EXISTS form", executed_sql)
        self.assertIn("ADD COLUMN IF NOT EXISTS material", executed_sql)
        cursor.executemany.assert_called_once()
        update_sql, update_params = cursor.executemany.call_args.args
        self.assertIn('UPDATE "tenant_a"."ifrc_item_reference"', update_sql)
        self.assertEqual(update_params[0][0], "500 G")
        self.assertEqual(update_params[0][1], "TABLET")
        self.assertEqual(update_params[0][2], "PLASTIC")

    def test_0008_forwards_sql_creates_append_only_catalog_audit(self):
        schema_editor = SimpleNamespace(
            connection=SimpleNamespace(vendor="postgresql"),
            execute=MagicMock(),
        )
        with patch.object(self.migration_0008, "_relation_exists", return_value=True):
            with patch.dict("os.environ", {"DMIS_DB_SCHEMA": "tenant_a"}):
                self.migration_0008._forwards(None, schema_editor)

        executed_sql = schema_editor.execute.call_args.args[0]
        self.assertIn("CREATE TABLE IF NOT EXISTS tenant_a.catalog_governance_audit", executed_sql)
        self.assertIn("changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()", executed_sql)
        self.assertIn("CREATE TRIGGER trg_catalog_governance_audit_no_mutation", executed_sql)


class ItemMasterUomOptionTests(SimpleTestCase):
    def test_normalize_ensures_default_row_when_list_provided(self):
        options, errors = _normalize_item_uom_options(
            [{"uom_code": "BOX", "conversion_factor": 12}],
            default_uom_code="EA",
        )

        self.assertEqual(errors, {})
        self.assertEqual(len(options), 2)
        default_row = next(o for o in options if o["uom_code"] == "EA")
        self.assertTrue(default_row["is_default"])
        self.assertEqual(default_row["conversion_factor"], Decimal("1"))
        box_row = next(o for o in options if o["uom_code"] == "BOX")
        self.assertFalse(box_row["is_default"])

    def test_normalize_rejects_duplicate_uom_codes(self):
        options, errors = _normalize_item_uom_options(
            [
                {"uom_code": "EA", "conversion_factor": 1},
                {"uom_code": "EA", "conversion_factor": 1},
            ],
            default_uom_code="EA",
        )

        self.assertIsNone(options)
        self.assertIn("Duplicate UOM options", errors["uom_options"])

    def test_normalize_rejects_zero_conversion_factor(self):
        options, errors = _normalize_item_uom_options(
            [{"uom_code": "BOX", "conversion_factor": 0}],
            default_uom_code="EA",
        )

        self.assertIsNone(options)
        self.assertIn("greater than zero", errors["uom_options"])

    def test_normalize_rejects_non_numeric_conversion_factor(self):
        options, errors = _normalize_item_uom_options(
            [{"uom_code": "BOX", "conversion_factor": "abc"}],
            default_uom_code="EA",
        )

        self.assertIsNone(options)
        self.assertIn("numeric conversion_factor", errors["uom_options"])

    def test_normalize_returns_none_for_null_input(self):
        options, errors = _normalize_item_uom_options(None, default_uom_code="EA")

        self.assertIsNone(options)
        self.assertEqual(errors, {})

    def test_ensure_default_demotes_existing_default_before_promoting_new_default(self):
        cursor = MagicMock()
        with patch("masterdata.services.item_master.connection") as mock_connection:
            mock_connection.cursor.return_value.__enter__.return_value = cursor

            _ensure_default_item_uom_option("public", 7, "BOX", "tester")

        self.assertEqual(cursor.execute.call_count, 2)
        first_sql = cursor.execute.call_args_list[0].args[0]
        second_sql = cursor.execute.call_args_list[1].args[0]
        self.assertIn("UPDATE public.item_uom_option AS item_uom_option", first_sql)
        self.assertIn("is_default = FALSE", first_sql)
        self.assertIn("INSERT INTO public.item_uom_option", second_sql)
        self.assertEqual(cursor.execute.call_args_list[0].args[1], ["tester", 7, "BOX"])

    def test_replace_uom_options_demotes_existing_default_before_upserts(self):
        cursor = MagicMock()
        options = [
            {
                "uom_code": "BOX",
                "conversion_factor": Decimal("12"),
                "is_default": True,
                "sort_order": 0,
            },
            {
                "uom_code": "EA",
                "conversion_factor": Decimal("1"),
                "is_default": False,
                "sort_order": 1,
            },
        ]
        with patch("masterdata.services.item_master.connection") as mock_connection:
            mock_connection.cursor.return_value.__enter__.return_value = cursor

            _replace_item_uom_options("public", 9, options, "tester")

        self.assertGreaterEqual(cursor.execute.call_count, 3)
        first_sql = cursor.execute.call_args_list[0].args[0]
        second_sql = cursor.execute.call_args_list[1].args[0]
        self.assertIn("UPDATE public.item_uom_option AS item_uom_option", first_sql)
        self.assertIn("is_default = FALSE", first_sql)
        self.assertIn("INSERT INTO public.item_uom_option", second_sql)
        self.assertEqual(cursor.execute.call_args_list[0].args[1], ["tester", 9, "BOX"])

    def test_replace_uom_options_inactivates_existing_rows_when_options_empty(self):
        cursor = MagicMock()
        with patch("masterdata.services.item_master.connection") as mock_connection:
            mock_connection.cursor.return_value.__enter__.return_value = cursor

            _replace_item_uom_options("public", 9, [], "tester")

        self.assertEqual(cursor.execute.call_count, 1)
        sql = cursor.execute.call_args.args[0]
        params = cursor.execute.call_args.args[1]
        self.assertIn("UPDATE public.item_uom_option AS item_uom_option", sql)
        self.assertIn("status_code = 'I'", sql)
        self.assertIn("AND status_code <> 'I'", sql)
        self.assertEqual(params, ["tester", 9])

    def test_backfill_demotes_existing_default_before_promoting_item_default(self):
        cursor = MagicMock()

        _backfill_default_item_uom_options(cursor, "tenant_a", "system")

        self.assertEqual(cursor.execute.call_count, 2)
        first_sql = cursor.execute.call_args_list[0].args[0]
        second_sql = cursor.execute.call_args_list[1].args[0]
        self.assertIn("UPDATE tenant_a.item_uom_option AS item_uom_option", first_sql)
        self.assertIn("is_default = FALSE", first_sql)
        self.assertIn("INSERT INTO tenant_a.item_uom_option", second_sql)


class SyncItemMasterTaxonomyCommandTests(SimpleTestCase):
    @patch("masterdata.item_master_taxonomy._backfill_default_item_uom_options")
    @patch("masterdata.item_master_taxonomy._sync_references")
    @patch("masterdata.item_master_taxonomy._load_family_ids", return_value={("W", "WTR"): 11})
    @patch("masterdata.item_master_taxonomy._sync_families")
    @patch("masterdata.item_master_taxonomy._load_category_ids", return_value={"WASH": 102})
    @patch("masterdata.item_master_taxonomy._sync_categories")
    @patch(
        "masterdata.item_master_taxonomy.build_ifrc_taxonomy_seed_payload",
        return_value={"categories": [{"category_code": "WASH"}], "families": [{"family_code": "WTR"}], "references": [{"ifrc_code": "WWTRTABLTB01"}]},
    )
    def test_sync_function_does_not_run_item_uom_backfill_during_operational_sync(
        self,
        _mock_payload,
        _mock_sync_categories,
        _mock_load_category_ids,
        _mock_sync_families,
        _mock_load_family_ids,
        _mock_sync_references,
        mock_backfill,
    ):
        connection_obj = MagicMock()

        summary = sync_item_master_taxonomy(connection_obj, schema="tenant_a")

        self.assertEqual(summary, {"categories": 1, "families": 1, "references": 1})
        mock_backfill.assert_not_called()

    def test_dry_run_reports_seed_counts(self):
        stdout = StringIO()

        call_command("sync_item_master_taxonomy", "--dry-run", stdout=stdout)

        output = stdout.getvalue()
        self.assertIn("Item master taxonomy sync dry-run:", output)
        self.assertIn("Level 1 categories: 14", output)
        self.assertIn("IFRC families:", output)
        self.assertIn("IFRC item references:", output)

