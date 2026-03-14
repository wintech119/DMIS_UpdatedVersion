import importlib
from io import StringIO
from unittest.mock import MagicMock, patch
from types import SimpleNamespace

from django.core.management import call_command
from django.db import DatabaseError
from django.test import RequestFactory, SimpleTestCase
from django.test import override_settings
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory, force_authenticate

from masterdata import views

from masterdata.services.data_access import (
    INACTIVE_ITEM_FORWARD_WRITE_CODE,
    TABLE_REGISTRY,
    _guard_inactive_item_forward_write,
    _is_forward_write_guarded_state,
    _schema_name,
    _resolve_order_by,
    check_dependencies,
    check_uniqueness,
    create_record,
    inspect_auto_pk_sequence,
    resync_auto_pk_sequence,
    update_record,
)
from masterdata.services.validation import _cross_field_validation
from masterdata.ifrc_code_agent import (
    IFRCAgent,
    IFRCCodeSuggestion,
    _encode_generated_spec,
    _encode_spec,
    _next_sequence,
)


class OrderByValidationTests(SimpleTestCase):
    def test_accepts_known_column_default_direction(self):
        cfg = TABLE_REGISTRY["items"]
        sort_sql, invalid = _resolve_order_by(cfg, "item_name")
        self.assertEqual(sort_sql, "item_name ASC")
        self.assertFalse(invalid)

    def test_accepts_explicit_desc_direction(self):
        cfg = TABLE_REGISTRY["items"]
        sort_sql, invalid = _resolve_order_by(cfg, "item_name desc")
        self.assertEqual(sort_sql, "item_name DESC")
        self.assertFalse(invalid)

    def test_accepts_dash_prefix_desc(self):
        cfg = TABLE_REGISTRY["items"]
        sort_sql, invalid = _resolve_order_by(cfg, "-item_name")
        self.assertEqual(sort_sql, "item_name DESC")
        self.assertFalse(invalid)

    def test_rejects_sql_fragment_and_falls_back_to_default(self):
        cfg = TABLE_REGISTRY["items"]
        sort_sql, invalid = _resolve_order_by(cfg, "item_name; DROP TABLE item; --")
        self.assertEqual(sort_sql, "item_name ASC")
        self.assertTrue(invalid)

    def test_rejects_unknown_column_and_falls_back_to_default(self):
        cfg = TABLE_REGISTRY["items"]
        sort_sql, invalid = _resolve_order_by(cfg, "does_not_exist DESC")
        self.assertEqual(sort_sql, "item_name ASC")
        self.assertTrue(invalid)

    def test_preserves_valid_default_direction(self):
        cfg = TABLE_REGISTRY["events"]
        sort_sql, invalid = _resolve_order_by(cfg, None)
        self.assertEqual(sort_sql, "start_date DESC")
        self.assertFalse(invalid)


class PaginationLimitClampTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.cfg = TABLE_REGISTRY["items"]

    @patch("masterdata.views.list_item_records", return_value=([], 0, []))
    def test_negative_limit_is_clamped_to_minimum(self, mock_list_records):
        request = Request(self.factory.get(
            "/api/v1/masterdata/items/",
            {"limit": "-1", "offset": "0"},
        ))
        response = views._handle_list(request, self.cfg)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["limit"], 1)
        kwargs = mock_list_records.call_args.kwargs
        self.assertEqual(kwargs["limit"], 1)

    @patch("masterdata.views.list_item_records", return_value=([], 0, []))
    def test_excessive_limit_is_clamped_to_maximum(self, mock_list_records):
        request = Request(self.factory.get(
            "/api/v1/masterdata/items/",
            {"limit": "999999", "offset": "0"},
        ))
        response = views._handle_list(request, self.cfg)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["limit"], 500)
        kwargs = mock_list_records.call_args.kwargs
        self.assertEqual(kwargs["limit"], 500)


class UniquenessFieldValidationTests(SimpleTestCase):
    @patch("masterdata.services.data_access._is_sqlite", return_value=False)
    def test_invalid_field_returns_warning_and_skips_query(self, _mock_sqlite):
        is_unique, warnings = check_uniqueness(
            "items",
            "item_name; DROP TABLE item; --",
            "MRE",
        )

        self.assertTrue(is_unique)
        self.assertEqual(warnings, ["invalid_field"])

    @patch("masterdata.services.data_access.connection")
    @patch("masterdata.services.data_access._is_sqlite", return_value=False)
    def test_valid_field_uses_canonical_column_name(self, _mock_sqlite, mock_connection):
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (0,)

        is_unique, warnings = check_uniqueness("items", "item_name", "MRE")

        self.assertTrue(is_unique)
        self.assertEqual(warnings, [])
        executed_sql = cursor.execute.call_args.args[0]
        self.assertIn("UPPER(item_name) = UPPER(%s)", executed_sql)


class ItemCrossFieldValidationTests(SimpleTestCase):
    def test_low_criticality_is_allowed_choice(self):
        cfg = TABLE_REGISTRY["items"]
        criticality_field = next(fd for fd in cfg.fields if fd.name == "criticality_level")
        self.assertIn("LOW", criticality_field.choices or [])

    def test_fefo_requires_expiry(self):
        cfg = TABLE_REGISTRY["items"]
        errors = _cross_field_validation(
            cfg,
            {
                "issuance_order": "FEFO",
                "can_expire_flag": False,
            },
        )
        self.assertEqual(
            errors.get("can_expire_flag"),
            "Can Expire must be enabled when Issuance Order is FEFO.",
        )

    def test_can_expire_requires_fefo(self):
        cfg = TABLE_REGISTRY["items"]
        errors = _cross_field_validation(
            cfg,
            {
                "issuance_order": "FIFO",
                "can_expire_flag": True,
            },
        )
        self.assertEqual(
            errors.get("issuance_order"),
            "Issuance Order must be FEFO when Can Expire is enabled.",
        )

    def test_can_expire_without_issuance_does_not_override_required_message(self):
        cfg = TABLE_REGISTRY["items"]
        errors = _cross_field_validation(
            cfg,
            {
                "can_expire_flag": True,
            },
        )
        self.assertNotIn("issuance_order", errors)

    def test_fefo_patch_allows_existing_expiry_enabled(self):
        cfg = TABLE_REGISTRY["items"]
        errors = _cross_field_validation(
            cfg,
            {"issuance_order": "FEFO"},
            is_update=True,
            existing_record={"can_expire_flag": True},
        )
        self.assertEqual(errors, {})

    def test_fefo_patch_blocks_disabling_expiry_when_existing_order_is_fefo(self):
        cfg = TABLE_REGISTRY["items"]
        errors = _cross_field_validation(
            cfg,
            {"can_expire_flag": False},
            is_update=True,
            existing_record={"issuance_order": "FEFO"},
        )
        self.assertEqual(
            errors.get("can_expire_flag"),
            "Can Expire must be enabled when Issuance Order is FEFO.",
        )

    def test_can_expire_patch_blocks_non_fefo_when_existing_can_expire_true(self):
        cfg = TABLE_REGISTRY["items"]
        errors = _cross_field_validation(
            cfg,
            {"issuance_order": "FIFO"},
            is_update=True,
            existing_record={"can_expire_flag": True},
        )
        self.assertEqual(
            errors.get("issuance_order"),
            "Issuance Order must be FEFO when Can Expire is enabled.",
        )


class ItemSkuNormalizationTests(SimpleTestCase):
    @patch("masterdata.services.data_access.connection")
    @patch("masterdata.services.data_access.transaction.atomic")
    @patch("masterdata.services.data_access._is_sqlite", return_value=False)
    def test_create_blank_sku_is_saved_as_null(
        self,
        _mock_sqlite,
        _mock_atomic,
        mock_connection,
    ):
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (123,)

        pk_val, warnings = create_record("items", {"sku_code": "   "}, "tester")

        self.assertEqual(pk_val, 123)
        self.assertEqual(warnings, [])
        _, params = cursor.execute.call_args.args
        self.assertIn(None, params)

    @patch("masterdata.services.data_access.connection")
    @patch("masterdata.services.data_access.transaction.atomic")
    @patch("masterdata.services.data_access._is_sqlite", return_value=False)
    def test_update_blank_sku_is_saved_as_null(
        self,
        _mock_sqlite,
        _mock_atomic,
        mock_connection,
    ):
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        cursor.rowcount = 1

        success, warnings = update_record(
            "items",
            99,
            {"sku_code": "   "},
            "tester",
        )

        self.assertTrue(success)
        self.assertEqual(warnings, [])
        _, params = cursor.execute.call_args.args
        self.assertIsNone(params[0])


class AutoPkSequenceRepairTests(SimpleTestCase):
    @patch("masterdata.services.data_access._is_sqlite", return_value=False)
    @patch("masterdata.services.data_access.connection")
    def test_inspect_auto_pk_sequence_uses_runtime_schema(self, mock_connection, _mock_sqlite):
        mock_connection.vendor = "postgresql"
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.side_effect = [
            ("public.item_item_id_seq",),
            (457,),
            (401, True),
        ]

        info, warnings = inspect_auto_pk_sequence("items")

        self.assertEqual(warnings, [])
        self.assertEqual(info["sequence_name"], "public.item_item_id_seq")
        self.assertEqual(info["max_pk"], 457)
        self.assertEqual(info["last_value"], 401)
        self.assertTrue(info["is_called"])
        self.assertEqual(info["next_value"], 402)
        self.assertEqual(
            cursor.execute.call_args_list[0].args[1],
            [f"{_schema_name()}.item", "item_id"],
        )

    @patch("masterdata.services.data_access.inspect_auto_pk_sequence")
    @patch("masterdata.services.data_access.transaction.atomic")
    @patch("masterdata.services.data_access.connection")
    def test_resync_auto_pk_sequence_sets_next_free_value(
        self,
        mock_connection,
        _mock_atomic,
        mock_inspect,
    ):
        mock_connection.vendor = "postgresql"
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (458,)
        mock_inspect.return_value = ({
            "table_key": "items",
            "schema": "public",
            "table_name": "item",
            "pk_field": "item_id",
            "sequence_name": "public.item_item_id_seq",
            "max_pk": 457,
            "last_value": 401,
            "is_called": True,
            "next_value": 402,
        }, [])

        success, info, warnings = resync_auto_pk_sequence("items")

        self.assertTrue(success)
        self.assertEqual(info["target_value"], 458)
        self.assertEqual(info["next_value"], 458)
        self.assertIn("pk_sequence_resynced", warnings)
        self.assertEqual(
            cursor.execute.call_args.args[1],
            ["public.item_item_id_seq", 458],
        )

    @patch("masterdata.services.data_access._is_sqlite", return_value=False)
    @patch("masterdata.services.data_access.resync_auto_pk_sequence")
    @patch("masterdata.services.data_access._is_auto_pk_duplicate_violation", return_value=True)
    @patch("masterdata.services.data_access._execute_create_insert")
    def test_create_record_retries_once_after_sequence_resync(
        self,
        mock_execute_insert,
        _mock_duplicate,
        mock_resync,
        _mock_sqlite,
    ):
        duplicate_exc = DatabaseError(
            'duplicate key value violates unique constraint "pk_item" DETAIL: Key (item_id)=(457) already exists.'
        )
        mock_execute_insert.side_effect = [duplicate_exc, 458]
        mock_resync.return_value = (True, {"target_value": 458}, ["pk_sequence_resynced"])

        pk_val, warnings = create_record("items", {"item_name": "WATER TABS"}, "tester")

        self.assertEqual(pk_val, 458)
        self.assertIn("pk_sequence_resynced", warnings)
        self.assertEqual(mock_execute_insert.call_count, 2)
        mock_resync.assert_called_once_with("items")

    @patch("masterdata.services.data_access._is_sqlite", return_value=False)
    @patch("masterdata.services.data_access.resync_auto_pk_sequence")
    @patch("masterdata.services.data_access._execute_create_insert", return_value=123)
    def test_create_record_normal_insert_does_not_resync(
        self,
        _mock_execute_insert,
        mock_resync,
        _mock_sqlite,
    ):
        pk_val, warnings = create_record("items", {"item_name": "BLANKET"}, "tester")

        self.assertEqual(pk_val, 123)
        self.assertEqual(warnings, [])
        mock_resync.assert_not_called()


class AutoPkSequenceRepairCommandTests(SimpleTestCase):
    @patch("masterdata.management.commands.repair_auto_pk_sequence.inspect_auto_pk_sequence")
    def test_command_inspects_default_item_table(self, mock_inspect):
        mock_inspect.return_value = ({
            "schema": "public",
            "table_name": "item",
            "pk_field": "item_id",
            "sequence_name": "public.item_item_id_seq",
            "max_pk": 457,
            "last_value": 401,
            "is_called": True,
            "next_value": 402,
        }, [])
        stdout = StringIO()

        call_command("repair_auto_pk_sequence", stdout=stdout)

        output = stdout.getvalue()
        self.assertIn("Table key: items", output)
        self.assertIn("Sequence: public.item_item_id_seq", output)
        self.assertIn("Next sequence value: 402", output)

    @patch("masterdata.management.commands.repair_auto_pk_sequence.resync_auto_pk_sequence")
    @patch("masterdata.management.commands.repair_auto_pk_sequence.inspect_auto_pk_sequence")
    def test_command_repairs_sequence_when_apply_requested(self, mock_inspect, mock_resync):
        mock_inspect.return_value = ({
            "schema": "public",
            "table_name": "item",
            "pk_field": "item_id",
            "sequence_name": "public.item_item_id_seq",
            "max_pk": 457,
            "last_value": 401,
            "is_called": True,
            "next_value": 402,
        }, [])
        mock_resync.return_value = (
            True,
            {
                "last_value": 458,
                "next_value": 458,
            },
            ["pk_sequence_resynced"],
        )
        stdout = StringIO()

        call_command("repair_auto_pk_sequence", "items", "--apply", stdout=stdout)

        output = stdout.getvalue()
        self.assertIn("Sequence repaired.", output)
        self.assertIn("Applied value: 458", output)
        self.assertIn("Next insert value: 458", output)
        mock_resync.assert_called_once_with("items")


class ItemUpdateValidationContextTests(SimpleTestCase):
    def setUp(self):
        self.cfg = TABLE_REGISTRY["items"]

    @patch("masterdata.views.update_item_record", return_value=(True, []))
    @patch("masterdata.views.validate_record", return_value={})
    @patch("masterdata.views.get_item_record")
    def test_item_update_passes_existing_record_to_validation(
        self,
        mock_get_record,
        mock_validate,
        _mock_update,
    ):
        existing_record = {
            "item_id": 1,
            "issuance_order": "FIFO",
            "can_expire_flag": True,
        }
        mock_get_record.side_effect = [(existing_record, []), (existing_record, [])]

        request = SimpleNamespace(
            data={"issuance_order": "FEFO"},
            user=SimpleNamespace(user_id="tester"),
        )
        response = views._handle_update(request, self.cfg, 1)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            mock_validate.call_args.kwargs.get("existing_record"),
            existing_record,
        )


class ItemDetailReadFailureTests(SimpleTestCase):
    def setUp(self):
        self.cfg = TABLE_REGISTRY["items"]

    @patch("masterdata.views.get_item_record", return_value=(None, ["db_error"]))
    def test_item_detail_returns_500_when_item_read_fails(self, _mock_get_item_record):
        response = views._handle_detail(self.cfg, 42)

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.data["detail"], "Failed to load item detail.")
        self.assertEqual(response.data["warnings"], ["db_error"])
        self.assertIn("db_error", response.data["diagnostic"])

    @patch("masterdata.views.get_item_record", return_value=(None, ["db_unavailable"]))
    def test_item_detail_returns_503_when_item_read_is_transient(self, _mock_get_item_record):
        response = views._handle_detail(self.cfg, 42)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.data["detail"],
            "Item detail lookup is temporarily unavailable.",
        )
        self.assertEqual(response.data["warnings"], ["db_unavailable"])
        self.assertIn("db_unavailable", response.data["diagnostic"])

    @patch("masterdata.views.get_item_record", return_value=(None, []))
    def test_item_detail_keeps_404_for_true_miss(self, _mock_get_item_record):
        response = views._handle_detail(self.cfg, 42)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data, {"detail": "Not found."})


class PostWriteReadbackFailureViewTests(SimpleTestCase):
    def setUp(self):
        self.cfg = TABLE_REGISTRY["uom"]

    @patch("masterdata.views.get_record", return_value=(None, ["db_unavailable"]))
    @patch("masterdata.views.create_record", return_value=("EA", []))
    @patch("masterdata.views.validate_record", return_value={})
    def test_generic_create_returns_503_when_readback_is_transient(
        self,
        _mock_validate,
        _mock_create,
        _mock_get_record,
    ):
        request = SimpleNamespace(
            data={"uom_code": "EA", "uom_desc": "Each"},
            user=SimpleNamespace(user_id="tester"),
        )

        response = views._handle_create(request, self.cfg)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.data["detail"],
            "Loading the created record is temporarily unavailable.",
        )
        self.assertEqual(response.data["warnings"], ["db_unavailable"])
        self.assertIn("db_unavailable", response.data["diagnostic"])

    @patch(
        "masterdata.views.get_record",
        return_value=(
            None,
            [
                "db_error",
                "db_exception:OperationalError",
                "db_message:failed to reload updated record",
            ],
        ),
    )
    @patch("masterdata.views.update_record", return_value=(True, []))
    @patch("masterdata.views.validate_record", return_value={})
    def test_generic_update_returns_500_when_readback_fails(
        self,
        _mock_validate,
        _mock_update,
        _mock_get_record,
    ):
        request = SimpleNamespace(
            data={"uom_desc": "Each"},
            user=SimpleNamespace(user_id="tester"),
        )

        response = views._handle_update(request, self.cfg, "EA")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.data["detail"], "Failed to load updated record.")
        self.assertEqual(
            response.data["warnings"],
            [
                "db_error",
                "db_exception:OperationalError",
                "db_message:failed to reload updated record",
            ],
        )
        self.assertIn("OperationalError", response.data["diagnostic"])


class InactiveItemForwardWriteTests(SimpleTestCase):
    def setUp(self):
        self.cfg = TABLE_REGISTRY["inventory"]

    @patch("masterdata.views.validate_record", return_value={})
    @patch(
        "masterdata.views.create_record",
        return_value=(
            None,
            [
                INACTIVE_ITEM_FORWARD_WRITE_CODE,
                "inactive_item_id_7",
                "forward_write_table_inventory",
                "forward_write_workflow_ALWAYS",
            ],
        ),
    )
    def test_create_returns_machine_readable_inactive_guard(
        self,
        _mock_create,
        _mock_validate,
    ):
        request = SimpleNamespace(
            data={"item_id": 7},
            user=SimpleNamespace(user_id="tester"),
        )

        response = views._handle_create(request, self.cfg)

        self.assertEqual(response.status_code, 409)
        guard = response.data["errors"][INACTIVE_ITEM_FORWARD_WRITE_CODE]
        self.assertEqual(guard["code"], INACTIVE_ITEM_FORWARD_WRITE_CODE)
        self.assertEqual(guard["table"], "inventory")
        self.assertEqual(guard["workflow_state"], "ALWAYS")
        self.assertEqual(guard["item_ids"], [7])

    @patch(
        "masterdata.views.update_record",
        return_value=(
            False,
            [
                INACTIVE_ITEM_FORWARD_WRITE_CODE,
                "inactive_item_id_9",
                "forward_write_table_inventory",
                "forward_write_workflow_ALWAYS",
            ],
        ),
    )
    @patch("masterdata.views.validate_record", return_value={})
    @patch("masterdata.views.get_record", return_value=({"item_id": 9}, []))
    def test_update_returns_machine_readable_inactive_guard(
        self,
        _mock_get_record,
        _mock_validate,
        _mock_update,
    ):
        request = SimpleNamespace(
            data={"item_id": 9},
            user=SimpleNamespace(user_id="tester"),
        )

        response = views._handle_update(request, self.cfg, 1)

        self.assertEqual(response.status_code, 409)
        guard = response.data["errors"][INACTIVE_ITEM_FORWARD_WRITE_CODE]
        self.assertEqual(guard["item_ids"], [9])


class InactivationDependencyFailureViewTests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.user = SimpleNamespace(
            is_authenticated=True,
            user_id="tester",
            roles=[],
            permissions=[views.PERM_MASTERDATA_INACTIVATE],
        )

    @patch("masterdata.permissions.MasterDataPermission.has_permission", return_value=True)
    @patch("masterdata.views.inactivate_record")
    @patch(
        "masterdata.views.check_dependencies",
        return_value=([], ["dependency_check_failed_inventory"]),
    )
    def test_master_inactivate_returns_500_when_dependency_check_fails(
        self,
        _mock_check_dependencies,
        mock_inactivate_record,
        _mock_permission,
    ):
        request = self.factory.post("/api/v1/masterdata/items/15/inactivate", {})
        force_authenticate(request, user=self.user)

        response = views.master_inactivate(request, "items", "15")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.data["detail"],
            "Failed to validate dependencies before inactivation.",
        )
        self.assertEqual(
            response.data["warnings"],
            ["dependency_check_failed_inventory"],
        )
        mock_inactivate_record.assert_not_called()


class StatusChangeNotFoundViewTests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.user = SimpleNamespace(
            is_authenticated=True,
            user_id="tester",
            roles=[],
            permissions=[views.PERM_MASTERDATA_INACTIVATE, views.PERM_MASTERDATA_EDIT],
        )

    @patch("masterdata.permissions.MasterDataPermission.has_permission", return_value=True)
    @patch("masterdata.views.update_item_record", return_value=(False, ["not_found"]))
    @patch("masterdata.views.check_dependencies", return_value=([], []))
    def test_master_inactivate_returns_404_when_item_status_change_reports_not_found(
        self,
        _mock_check_dependencies,
        _mock_update_item_record,
        _mock_permission,
    ):
        request = self.factory.post("/api/v1/masterdata/items/15/inactivate", {})
        force_authenticate(request, user=self.user)

        response = views.master_inactivate(request, "items", "15")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data["detail"], "Record not found.")
        self.assertEqual(response.data["warnings"], ["not_found"])

    @patch("masterdata.permissions.MasterDataPermission.has_permission", return_value=True)
    @patch("masterdata.views.inactivate_record", return_value=(False, ["not_found"]))
    @patch("masterdata.views.check_dependencies", return_value=([], []))
    def test_master_inactivate_returns_404_when_generic_status_change_reports_not_found(
        self,
        _mock_check_dependencies,
        _mock_inactivate_record,
        _mock_permission,
    ):
        request = self.factory.post("/api/v1/masterdata/uom/EA/inactivate", {})
        force_authenticate(request, user=self.user)

        response = views.master_inactivate(request, "uom", "EA")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data["detail"], "Record not found.")
        self.assertEqual(response.data["warnings"], ["not_found"])

    @patch("masterdata.permissions.MasterDataPermission.has_permission", return_value=True)
    @patch("masterdata.views.update_item_record", return_value=(False, ["not_found"]))
    def test_master_activate_returns_404_when_item_status_change_reports_not_found(
        self,
        _mock_update_item_record,
        _mock_permission,
    ):
        request = self.factory.post("/api/v1/masterdata/items/15/activate", {})
        force_authenticate(request, user=self.user)

        response = views.master_activate(request, "items", "15")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data["detail"], "Record not found.")
        self.assertEqual(response.data["warnings"], ["not_found"])

    @patch("masterdata.permissions.MasterDataPermission.has_permission", return_value=True)
    @patch("masterdata.views.activate_record", return_value=(False, ["not_found"]))
    def test_master_activate_returns_404_when_generic_status_change_reports_not_found(
        self,
        _mock_activate_record,
        _mock_permission,
    ):
        request = self.factory.post("/api/v1/masterdata/uom/EA/activate", {})
        force_authenticate(request, user=self.user)

        response = views.master_activate(request, "uom", "EA")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data["detail"], "Record not found.")
        self.assertEqual(response.data["warnings"], ["not_found"])


class StatusChangeReadbackFailureViewTests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.user = SimpleNamespace(
            is_authenticated=True,
            user_id="tester",
            roles=[],
            permissions=[views.PERM_MASTERDATA_INACTIVATE, views.PERM_MASTERDATA_EDIT],
        )

    @patch("masterdata.permissions.MasterDataPermission.has_permission", return_value=True)
    @patch("masterdata.views.get_item_record", return_value=(None, ["db_unavailable"]))
    @patch("masterdata.views.update_item_record", return_value=(True, []))
    @patch("masterdata.views.check_dependencies", return_value=([], []))
    def test_master_inactivate_returns_503_when_item_readback_is_transient(
        self,
        _mock_check_dependencies,
        _mock_update_item_record,
        _mock_get_item_record,
        _mock_permission,
    ):
        request = self.factory.post("/api/v1/masterdata/items/15/inactivate", {})
        force_authenticate(request, user=self.user)

        response = views.master_inactivate(request, "items", "15")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.data["detail"],
            "Loading the inactivated item is temporarily unavailable.",
        )
        self.assertEqual(response.data["warnings"], ["db_unavailable"])
        self.assertIn("db_unavailable", response.data["diagnostic"])

    @patch("masterdata.permissions.MasterDataPermission.has_permission", return_value=True)
    @patch(
        "masterdata.views.get_record",
        return_value=(
            None,
            [
                "db_error",
                "db_exception:OperationalError",
                "db_message:failed to reload activated record",
            ],
        ),
    )
    @patch("masterdata.views.activate_record", return_value=(True, []))
    def test_master_activate_returns_500_when_generic_readback_fails(
        self,
        _mock_activate_record,
        _mock_get_record,
        _mock_permission,
    ):
        request = self.factory.post("/api/v1/masterdata/uom/EA/activate", {})
        force_authenticate(request, user=self.user)

        response = views.master_activate(request, "uom", "EA")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.data["detail"], "Failed to load activated record.")
        self.assertEqual(
            response.data["warnings"],
            [
                "db_error",
                "db_exception:OperationalError",
                "db_message:failed to reload activated record",
            ],
        )
        self.assertIn("OperationalError", response.data["diagnostic"])


class InventoryGuardLookupTests(SimpleTestCase):
    @patch(
        "masterdata.services.data_access._guard_inactive_item_forward_write",
        return_value=(False, [INACTIVE_ITEM_FORWARD_WRITE_CODE]),
    )
    @patch("masterdata.services.data_access._is_sqlite", return_value=False)
    @patch("masterdata.services.data_access.connection")
    def test_inventory_update_without_item_id_uses_existing_item_for_guard(
        self,
        mock_connection,
        _mock_sqlite,
        mock_guard,
    ):
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (42,)

        success, warnings = update_record(
            "inventory",
            11,
            {"usable_qty": 5},
            "tester",
        )

        self.assertFalse(success)
        self.assertIn(INACTIVE_ITEM_FORWARD_WRITE_CODE, warnings)
        self.assertEqual(mock_guard.call_args.kwargs["item_id"], 42)

    @patch("masterdata.services.data_access._guard_inactive_item_forward_write")
    @patch(
        "masterdata.services.data_access._lookup_inventory_item_id",
        return_value=(None, ["inventory_item_lookup_failed"]),
    )
    @patch("masterdata.services.data_access._is_sqlite", return_value=False)
    def test_inventory_update_blocks_when_item_lookup_fails(
        self,
        _mock_sqlite,
        _mock_lookup,
        mock_guard,
    ):
        success, warnings = update_record(
            "inventory",
            11,
            {"usable_qty": 5},
            "tester",
        )

        self.assertFalse(success)
        self.assertEqual(warnings, ["inventory_item_lookup_failed"])
        mock_guard.assert_not_called()


class InactiveForwardWriteMatrixTests(SimpleTestCase):
    def test_state_matrix_guards_transfer_item_pending(self):
        guarded, workflow_state = _is_forward_write_guarded_state(
            "transfer_item",
            "P",
        )
        self.assertTrue(guarded)
        self.assertEqual(workflow_state, "PENDING")

    def test_state_matrix_skips_transfer_item_dispatched(self):
        guarded, workflow_state = _is_forward_write_guarded_state(
            "transfer_item",
            "DISPATCHED",
        )
        self.assertFalse(guarded)
        self.assertEqual(workflow_state, "DISPATCHED")

    def test_state_matrix_guards_needs_list_item_draft_generation(self):
        guarded, workflow_state = _is_forward_write_guarded_state(
            "needs_list_item",
            "DRAFT_GENERATION",
        )
        self.assertTrue(guarded)
        self.assertEqual(workflow_state, "DRAFT_GENERATION")

    def test_state_matrix_guards_donation_item_entered(self):
        guarded, workflow_state = _is_forward_write_guarded_state(
            "donation_item",
            "ENTERED",
        )
        self.assertTrue(guarded)
        self.assertEqual(workflow_state, "ENTERED")

    def test_state_matrix_guards_procurement_item_draft(self):
        guarded, workflow_state = _is_forward_write_guarded_state(
            "procurement_item",
            "DRAFT",
        )
        self.assertTrue(guarded)
        self.assertEqual(workflow_state, "DRAFT")

    def test_state_matrix_guards_reliefpkg_item_draft(self):
        guarded, workflow_state = _is_forward_write_guarded_state(
            "reliefpkg_item",
            "DRAFT",
        )
        self.assertTrue(guarded)
        self.assertEqual(workflow_state, "DRAFT")

    def test_state_matrix_guards_reliefrqst_item_draft(self):
        guarded, workflow_state = _is_forward_write_guarded_state(
            "reliefrqst_item",
            "DRAFT",
        )
        self.assertTrue(guarded)
        self.assertEqual(workflow_state, "DRAFT")

    @patch("masterdata.services.data_access._is_sqlite", return_value=False)
    @patch("masterdata.services.data_access.connection")
    def test_guard_blocks_pending_transfer_item_for_inactive_item(
        self,
        mock_connection,
        _mock_sqlite,
    ):
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = ("I",)

        allowed, warnings = _guard_inactive_item_forward_write(
            table_key="transfer_item",
            item_id=15,
            workflow_state="PENDING",
        )

        self.assertFalse(allowed)
        self.assertIn(INACTIVE_ITEM_FORWARD_WRITE_CODE, warnings)
        self.assertIn("forward_write_table_transfer_item", warnings)
        self.assertIn("forward_write_workflow_PENDING", warnings)

    @patch("masterdata.services.data_access._is_sqlite", return_value=False)
    @patch("masterdata.services.data_access.connection")
    def test_guard_allows_non_guarded_transfer_state(
        self,
        mock_connection,
        _mock_sqlite,
    ):
        allowed, warnings = _guard_inactive_item_forward_write(
            table_key="transfer_item",
            item_id=15,
            workflow_state="DISPATCHED",
        )

        self.assertTrue(allowed)
        self.assertEqual(warnings, [])
        mock_connection.cursor.assert_not_called()


class ItemInactivationDependencyMatrixTests(SimpleTestCase):
    @patch.dict("os.environ", {"DMIS_DB_SCHEMA": "tenant_a"})
    @patch("masterdata.services.data_access._is_sqlite", return_value=False)
    @patch("masterdata.services.data_access.connection")
    def test_items_dependency_check_uses_status_scoped_matrix(
        self,
        mock_connection,
        _mock_sqlite,
    ):
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.side_effect = [
            (0,),  # inventory
            (0,),  # itembatch
            (0,),  # item_location
            (2,),  # transfer_item (blocking)
            (0,),  # needs_list_item
            (0,),  # donation_item
            (0,),  # procurement_item
            (0,),  # reliefpkg_item
            (0,),  # reliefrqst_item
        ]

        blocking, warnings = check_dependencies("items", 15)

        self.assertEqual(blocking, ["Draft/Pending Transfers (2 records)"])
        self.assertEqual(warnings, [])

        schema = _schema_name()
        executed = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertEqual(len(executed), 9)
        self.assertTrue(any(f"JOIN {schema}.transfer t" in sql for sql in executed))
        self.assertTrue(all("UPPER(COALESCE(" in sql for sql in executed))

        transfer_call = next(
            call for call in cursor.execute.call_args_list
            if f"JOIN {schema}.transfer t" in call.args[0]
        )
        transfer_params = transfer_call.args[1]
        self.assertIn(15, transfer_params)
        self.assertIn("DRAFT", transfer_params)
        self.assertIn("PENDING", transfer_params)

    @patch.dict("os.environ", {"DMIS_DB_SCHEMA": "tenant_a"})
    @patch("masterdata.services.data_access._is_sqlite", return_value=False)
    @patch("masterdata.services.data_access.connection")
    def test_items_dependency_check_covers_all_approved_tables(
        self,
        mock_connection,
        _mock_sqlite,
    ):
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.side_effect = [(0,)] * 9

        blocking, warnings = check_dependencies("items", 42)

        self.assertEqual(blocking, [])
        self.assertEqual(warnings, [])

        schema = _schema_name()
        executed = [call.args[0] for call in cursor.execute.call_args_list]
        expected_fragments = [
            f"FROM {schema}.inventory inv",
            f"FROM {schema}.itembatch ib",
            f"FROM {schema}.item_location il",
            f"FROM {schema}.transfer_item ti",
            f"FROM {schema}.needs_list_item nli",
            f"FROM {schema}.donation_item di",
            f"FROM {schema}.procurement_item pi",
            f"FROM {schema}.reliefpkg_item rpi",
            f"FROM {schema}.reliefrqst_item rri",
        ]
        for fragment in expected_fragments:
            self.assertTrue(any(fragment in sql for sql in executed), fragment)

    @patch("masterdata.services.data_access._is_sqlite", return_value=False)
    @patch("masterdata.services.data_access.connection")
    def test_items_dependency_check_rolls_back_and_returns_warning_on_db_error(
        self,
        mock_connection,
        _mock_sqlite,
    ):
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        cursor.execute.side_effect = DatabaseError("lookup failed")
        mock_connection.rollback.side_effect = RuntimeError("rollback failed")

        blocking, warnings = check_dependencies("items", 42)

        self.assertEqual(blocking, [])
        self.assertEqual(len(warnings), 9)
        self.assertIn("dependency_check_failed_inventory", warnings)
        self.assertEqual(mock_connection.rollback.call_count, 9)


class InactiveItemLookupFailureTests(SimpleTestCase):
    @patch("masterdata.services.data_access._is_sqlite", return_value=False)
    @patch("masterdata.services.data_access.connection")
    def test_guard_blocks_write_when_item_status_lookup_fails(
        self,
        mock_connection,
        _mock_sqlite,
    ):
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        cursor.execute.side_effect = DatabaseError("lookup failed")
        mock_connection.rollback.side_effect = RuntimeError("rollback failed")

        allowed, warnings = _guard_inactive_item_forward_write(
            table_key="inventory",
            item_id=15,
            workflow_state="ALWAYS",
        )

        self.assertFalse(allowed)
        self.assertEqual(warnings, ["item_status_lookup_failed"])
        mock_connection.rollback.assert_called_once()


class ItemCodeMigrationSchemaTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.migration = importlib.import_module(
            "masterdata.migrations.0001_item_code_varchar_30"
        )

    def test_legacy_table_lookup_uses_configured_schema(self):
        schema_editor = SimpleNamespace(connection=MagicMock())
        cursor = schema_editor.connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = ("tenant_a.item",)

        with patch.dict("os.environ", {"DMIS_DB_SCHEMA": "tenant_a"}):
            exists = self.migration._legacy_item_table_exists(schema_editor)

        self.assertTrue(exists)
        self.assertEqual(cursor.execute.call_args.args[0], "SELECT to_regclass(%s)")
        self.assertEqual(cursor.execute.call_args.args[1], ["tenant_a.item"])

    def test_forwards_sql_uses_configured_schema(self):
        schema_editor = SimpleNamespace(
            connection=SimpleNamespace(vendor="postgresql"),
            execute=MagicMock(),
        )
        with patch.object(self.migration, "_legacy_item_table_exists", return_value=True):
            with patch.dict("os.environ", {"DMIS_DB_SCHEMA": "tenant_a"}):
                self.migration._forwards(None, schema_editor)

        executed_sql = schema_editor.execute.call_args.args[0]
        self.assertIn("ALTER TABLE tenant_a.item", executed_sql)
        self.assertIn("CREATE VIEW tenant_a.v_stock_status AS", executed_sql)


@override_settings(
    IFRC_AGENT={
        "LLM_ENABLED": False,
        "CB_REDIS_KEY": "ifrc:test:cb",
        "CB_FAILURE_THRESHOLD": 5,
        "CB_RESET_TIMEOUT_SECONDS": 120,
        "OLLAMA_MODEL_ID": "qwen3.5:0.8b",
        "OLLAMA_BASE_URL": "http://localhost:11434",
        "OLLAMA_TIMEOUT_SECONDS": 10,
    }
)
class IFRCAgentTests(SimpleTestCase):
    def test_suggest_generates_ifrc_style_12_char_code_when_llm_disabled(self):
        agent = IFRCAgent()
        result = agent.suggest("water tabs")

        self.assertEqual(result.match_type, "fallback")
        self.assertIsNotNone(result.ifrc_code)
        self.assertRegex(result.ifrc_code, r"^[A-Z0-9]{12}$")
        self.assertEqual(result.group_code, "W")
        self.assertEqual(result.family_code, "WTR")
        self.assertEqual(result.category_code, "TABL")
        self.assertEqual(result.spec_seg, "TB00")
        self.assertIsNone(result.sequence)

    def test_spec_encoding_prefers_form_then_size(self):
        self.assertEqual(_encode_spec("200 g", "tablet", "plastic"), "TB200")

    def test_spec_encoding_uses_material_when_form_absent(self):
        self.assertEqual(_encode_spec("20 l", "", "plastic"), "PL20L")

    def test_generated_spec_encoding_uses_compact_ifrc_style_suffix(self):
        self.assertEqual(
            _encode_generated_spec(
                "Corned beef, canned, 200 g",
                size_weight="200 g",
                form="canned",
                category_code="MEAT",
            ),
            "BK02",
        )
        self.assertEqual(
            _encode_generated_spec(
                "Air conditioner, window, 18000 BTU",
                size_weight="18000 BTU",
                category_code="ACON",
            ),
            "CW18",
        )

    def test_empty_input_returns_none(self):
        agent = IFRCAgent()
        result = agent.suggest("   ")
        self.assertEqual(result.match_type, "none")
        self.assertIsNone(result.ifrc_code)


class IFRCSequenceLookupTests(SimpleTestCase):
    @patch("masterdata.ifrc_code_agent.connection")
    def test_sequence_lookup_uses_configured_schema(self, mock_connection):
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = []

        with patch.dict("os.environ", {"DMIS_DB_SCHEMA": "tenant_a"}):
            seq, _ = _next_sequence("WWTRTABL")

        self.assertEqual(seq, 1)
        executed_sql = cursor.execute.call_args.args[0]
        self.assertIn("FROM tenant_a.item", executed_sql)


class IFRCSuggestViewTests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.user = SimpleNamespace(
            is_authenticated=True,
            user_id="test-user",
            roles=[],
            permissions=[views.PERM_MASTERDATA_VIEW],
        )

    def _build_suggestion(self):
        return IFRCCodeSuggestion(
            item_code="WWTRTABLTB00",
            standardised_name="WATER PURIFICATION TABLET",
            confidence=0.88,
            match_type="generated",
            construction_rationale="Group=W Family=WTR Category=TABL Compact specification TB00",
            llm_used=False,
            grp="W",
            fam="WTR",
            cat="TABL",
            spec_seg="TB00",
            seq=None,
        )

    def _official_corned_beef_candidates(self):
        return [
            {
                "ifrc_item_ref_id": 501,
                "ifrc_family_id": 41,
                "ifrc_code": "FCANMEATCB200G",
                "reference_desc": "Corned beef, canned, 200 g",
                "category_code": "MEAT",
                "category_label": "Canned Meat",
                "spec_segment": "CN200",
                "size_weight": "200 G",
                "form": "CANNED",
                "material": "",
                "group_code": "F",
                "group_label": "Food",
                "family_code": "CAN",
                "family_label": "Canned Food",
            },
            {
                "ifrc_item_ref_id": 502,
                "ifrc_family_id": 41,
                "ifrc_code": "FCANMEATCB500G",
                "reference_desc": "Corned beef, canned, 500 g",
                "category_code": "MEAT",
                "category_label": "Canned Meat",
                "spec_segment": "CN500",
                "size_weight": "500 G",
                "form": "CANNED",
                "material": "",
                "group_code": "F",
                "group_label": "Food",
                "family_code": "CAN",
                "family_label": "Canned Food",
            },
        ]

    def _official_amoxicillin_candidates(self):
        return [
            {
                "ifrc_item_ref_id": 611,
                "ifrc_family_id": 22,
                "ifrc_code": "DANBAMOXAMX250MG",
                "reference_desc": "Amoxicillin tablet, 250 mg",
                "category_code": "AMOX",
                "category_label": "Amoxicillin and Penicillins",
                "spec_segment": "TB250",
                "size_weight": "250 MG",
                "form": "TABLET",
                "material": "",
                "group_code": "D",
                "group_label": "Drugs",
                "family_code": "ANB",
                "family_label": "Antibiotics",
            },
            {
                "ifrc_item_ref_id": 612,
                "ifrc_family_id": 22,
                "ifrc_code": "DANBAMOXAMX500MG",
                "reference_desc": "Amoxicillin tablet, 500 mg",
                "category_code": "AMOX",
                "category_label": "Amoxicillin and Penicillins",
                "spec_segment": "TB500",
                "size_weight": "500 MG",
                "form": "TABLET",
                "material": "",
                "group_code": "D",
                "group_label": "Drugs",
                "family_code": "ANB",
                "family_label": "Antibiotics",
            },
        ]

    @patch("masterdata.permissions.MasterDataPermission.has_permission", return_value=True)
    @patch("masterdata.views._allow_ifrc_request", return_value=True)
    @patch("masterdata.views._write_ifrc_audit_log", return_value=123)
    @patch(
        "masterdata.views._resolve_ifrc_suggestion",
        return_value={
            "resolution_status": "resolved",
            "resolution_explanation": "Generated suggestion resolved to exactly one active governed IFRC reference.",
            "ifrc_family_id": 11,
            "resolved_ifrc_item_ref_id": 77,
            "candidate_count": 1,
            "auto_highlight_candidate_id": 77,
            "direct_accept_allowed": True,
            "candidates": [
                {
                    "ifrc_item_ref_id": 77,
                    "ifrc_family_id": 11,
                    "ifrc_code": "WWTRTABLTB01",
                    "reference_desc": "WATER PURIFICATION TABLET",
                    "group_code": "W",
                    "group_label": "WASH",
                    "family_code": "WTR",
                    "family_label": "Water Treatment",
                    "category_code": "TABL",
                    "category_label": "Tablet",
                    "spec_segment": "TB",
                    "rank": 1,
                    "score": 1.0,
                    "auto_highlight": True,
                    "match_reasons": ["exact_generated_code_match"],
                }
            ],
        },
    )
    @patch("masterdata.views._ifrc_agent")
    def test_ifrc_suggest_success_returns_resolved_payload_and_passes_hints(
        self,
        mock_ifrc_agent,
        _mock_resolve,
        _mock_write_log,
        _mock_rate_limit,
        _mock_permission,
    ):
        mock_ifrc_agent.return_value.generate.return_value = self._build_suggestion()

        request = self.factory.get(
            "/api/v1/masterdata/items/ifrc-suggest",
            {
                "name": "water tabs",
                "size_weight": "500g",
                "form": "tablet",
                "material": "chlorine",
            },
        )
        force_authenticate(request, user=self.user)
        response = views.ifrc_suggest(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["ifrc_code"], "WWTRTABLTB01")
        self.assertEqual(response.data["suggestion_id"], "123")
        self.assertEqual(response.data["match_type"], "generated")
        self.assertEqual(response.data["resolution_status"], "resolved")
        self.assertEqual(response.data["resolved_ifrc_item_ref_id"], 77)
        self.assertEqual(response.data["candidate_count"], 1)
        self.assertTrue(response.data["direct_accept_allowed"])
        self.assertEqual(response.data["auto_fill_threshold"], 0.85)
        mock_ifrc_agent.return_value.generate.assert_called_once_with(
            "water tabs",
            size_weight="500g",
            form="tablet",
            material="chlorine",
        )

    @patch("masterdata.permissions.MasterDataPermission.has_permission", return_value=True)
    @patch("masterdata.views._allow_ifrc_request", return_value=True)
    @patch("masterdata.views._write_ifrc_audit_log", return_value=123)
    @patch(
        "masterdata.views._resolve_ifrc_suggestion",
        return_value={
            "resolution_status": "ambiguous",
            "resolution_explanation": "Multiple active governed IFRC references are plausible; explicit user selection is required.",
            "ifrc_family_id": 11,
            "resolved_ifrc_item_ref_id": None,
            "candidate_count": 2,
            "auto_highlight_candidate_id": 88,
            "direct_accept_allowed": False,
            "candidates": [
                {
                    "ifrc_item_ref_id": 88,
                    "ifrc_family_id": 11,
                    "ifrc_code": "WWTRTABLTB01",
                    "reference_desc": "WATER PURIFICATION TABLET",
                    "group_code": "W",
                    "group_label": "WASH",
                    "family_code": "WTR",
                    "family_label": "Water Treatment",
                    "category_code": "TABL",
                    "category_label": "Tablet",
                    "spec_segment": "TB",
                    "rank": 1,
                    "score": 0.91,
                    "auto_highlight": True,
                    "match_reasons": ["exact_spec_match"],
                },
                {
                    "ifrc_item_ref_id": 89,
                    "ifrc_family_id": 11,
                    "ifrc_code": "WWTRTABLPW01",
                    "reference_desc": "WATER PURIFICATION POWDER",
                    "group_code": "W",
                    "group_label": "WASH",
                    "family_code": "WTR",
                    "family_label": "Water Treatment",
                    "category_code": "TABL",
                    "category_label": "Tablet",
                    "spec_segment": "PW",
                    "rank": 2,
                    "score": 0.74,
                    "auto_highlight": False,
                    "match_reasons": ["desc_overlap:WATER,PURIFICATION"],
                },
            ],
        },
    )
    @patch("masterdata.views._ifrc_agent")
    def test_ifrc_suggest_returns_ambiguous_candidate_payload(
        self,
        mock_ifrc_agent,
        _mock_resolve,
        _mock_write_log,
        _mock_rate_limit,
        _mock_permission,
    ):
        mock_ifrc_agent.return_value.generate.return_value = self._build_suggestion()

        request = self.factory.get("/api/v1/masterdata/items/ifrc-suggest", {"name": "water tabs"})
        force_authenticate(request, user=self.user)
        response = views.ifrc_suggest(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["resolution_status"], "ambiguous")
        self.assertEqual(response.data["candidate_count"], 2)
        self.assertIsNone(response.data["resolved_ifrc_item_ref_id"])
        self.assertEqual(response.data["auto_highlight_candidate_id"], 88)
        self.assertFalse(response.data["direct_accept_allowed"])
        self.assertEqual(len(response.data["candidates"]), 2)

    @patch("masterdata.permissions.MasterDataPermission.has_permission", return_value=True)
    @patch("masterdata.views._allow_ifrc_request", return_value=True)
    @patch("masterdata.views._write_ifrc_audit_log", return_value=123)
    @patch(
        "masterdata.views._load_ifrc_reference_candidates",
        return_value=[
            {
                "ifrc_item_ref_id": 88,
                "ifrc_family_id": 11,
                "ifrc_code": "WWTRTABLTB01",
                "reference_desc": "WATER KIT",
                "category_code": "TABL",
                "category_label": "Tablet",
                "spec_segment": "TB",
                "size_weight": "",
                "form": "",
                "material": "",
                "group_code": "W",
                "group_label": "WASH",
                "family_code": "WTR",
                "family_label": "Treatment",
            },
            {
                "ifrc_item_ref_id": 89,
                "ifrc_family_id": 11,
                "ifrc_code": "WWTRTABLTB02",
                "reference_desc": "WATER FILTER",
                "category_code": "TABL",
                "category_label": "Tablet",
                "spec_segment": "TB",
                "size_weight": "",
                "form": "",
                "material": "",
                "group_code": "W",
                "group_label": "WASH",
                "family_code": "WTR",
                "family_label": "Treatment",
            },
        ],
    )
    @patch("masterdata.views._fetch_ifrc_reference_by_code", return_value=None)
    @patch("masterdata.views._fetch_ifrc_family_id", return_value=11)
    @patch("masterdata.views._ifrc_agent")
    def test_auto_highlight_threshold_just_below_default(
        self,
        mock_ifrc_agent,
        _mock_family_lookup,
        _mock_reference_lookup,
        _mock_load_candidates,
        _mock_write_log,
        _mock_rate_limit,
        _mock_permission,
    ):
        mock_ifrc_agent.return_value.generate.return_value = IFRCCodeSuggestion(
            item_code="WWTRTABLTB00",
            standardised_name="WATER KIT",
            confidence=0.84,
            match_type="generated",
            construction_rationale="Group=W Family=WTR Category=TABL Compact specification TB00",
            llm_used=False,
            grp="W",
            fam="WTR",
            cat="TABL",
            spec_seg="TB00",
            seq=None,
        )

        request = self.factory.get("/api/v1/masterdata/items/ifrc-suggest", {"name": "water kit"})
        force_authenticate(request, user=self.user)
        response = views.ifrc_suggest(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["confidence"], 0.84)
        self.assertEqual(response.data["auto_fill_threshold"], 0.85)
        self.assertEqual(response.data["resolution_status"], "ambiguous")
        self.assertEqual(response.data["candidate_count"], 2)
        self.assertIsNone(response.data["resolved_ifrc_item_ref_id"])
        self.assertIsNone(response.data["auto_highlight_candidate_id"])
        self.assertFalse(response.data["direct_accept_allowed"])
        self.assertLess(response.data["candidates"][0]["score"], 0.85)
        self.assertFalse(response.data["candidates"][0]["auto_highlight"])

    @patch("masterdata.permissions.MasterDataPermission.has_permission", return_value=True)
    @patch("masterdata.views._allow_ifrc_request", return_value=True)
    @patch("masterdata.views._write_ifrc_audit_log", return_value=123)
    @patch(
        "masterdata.views._resolve_ifrc_suggestion",
        return_value={
            "resolution_status": "unresolved",
            "resolution_explanation": "Generated suggestion did not resolve to an active governed IFRC reference.",
            "ifrc_family_id": None,
            "resolved_ifrc_item_ref_id": None,
            "candidate_count": 0,
            "auto_highlight_candidate_id": None,
            "direct_accept_allowed": False,
            "candidates": [],
        },
    )
    @patch("masterdata.views._ifrc_agent")
    def test_ifrc_suggest_returns_unresolved_payload(
        self,
        mock_ifrc_agent,
        _mock_resolve,
        _mock_write_log,
        _mock_rate_limit,
        _mock_permission,
    ):
        mock_ifrc_agent.return_value.generate.return_value = self._build_suggestion()

        request = self.factory.get("/api/v1/masterdata/items/ifrc-suggest", {"name": "water tabs"})
        force_authenticate(request, user=self.user)
        response = views.ifrc_suggest(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["resolution_status"], "unresolved")
        self.assertEqual(response.data["candidate_count"], 0)
        self.assertEqual(response.data["candidates"], [])
        self.assertFalse(response.data["direct_accept_allowed"])

    @patch("masterdata.permissions.MasterDataPermission.has_permission", return_value=True)
    @patch("masterdata.views._allow_ifrc_request", return_value=True)
    @patch("masterdata.views._write_ifrc_audit_log", return_value=123)
    @patch("masterdata.views._load_ifrc_reference_candidates")
    @patch("masterdata.views._fetch_ifrc_reference_by_code", return_value=None)
    @patch("masterdata.views._fetch_ifrc_family_id", return_value=41)
    @patch("masterdata.views._ifrc_agent")
    def test_ifrc_suggest_resolves_official_corned_beef_200g_reference(
        self,
        mock_ifrc_agent,
        _mock_family_lookup,
        _mock_reference_lookup,
        mock_load_candidates,
        _mock_write_log,
        _mock_rate_limit,
        _mock_permission,
    ):
        mock_load_candidates.return_value = self._official_corned_beef_candidates()
        mock_ifrc_agent.return_value.generate.return_value = IFRCCodeSuggestion(
            item_code="FCANMEATBK02",
            standardised_name="CORNED BEEF CANNED 200 G",
            confidence=0.88,
            match_type="generated",
            construction_rationale="Group=F Family=CAN Category=MEAT Compact specification BK02",
            llm_used=False,
            grp="F",
            fam="CAN",
            cat="MEAT",
            spec_seg="BK02",
            seq=None,
        )

        request = self.factory.get(
            "/api/v1/masterdata/items/ifrc-suggest",
            {"name": "CORNED BEEF, CANNED, 200g"},
        )
        force_authenticate(request, user=self.user)
        response = views.ifrc_suggest(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["resolution_status"], "resolved")
        self.assertEqual(response.data["resolved_ifrc_item_ref_id"], 501)
        self.assertEqual(response.data["ifrc_code"], "FCANMEATCB200G")
        self.assertEqual(response.data["ifrc_description"], "Corned beef, canned, 200 g")
        self.assertNotEqual(response.data["ifrc_code"], "FCANMEATBK02")
        self.assertEqual(response.data["candidates"][0]["size_weight"], "200 G")
        self.assertIn("exact_size_weight_match", response.data["candidates"][0]["match_reasons"])
        self.assertTrue(response.data["direct_accept_allowed"])

    @patch("masterdata.permissions.MasterDataPermission.has_permission", return_value=True)
    @patch("masterdata.views._allow_ifrc_request", return_value=True)
    @patch("masterdata.views._write_ifrc_audit_log", return_value=123)
    @patch("masterdata.views._load_ifrc_reference_candidates")
    @patch("masterdata.views._fetch_ifrc_reference_by_code", return_value=None)
    @patch("masterdata.views._fetch_ifrc_family_id", return_value=41)
    @patch("masterdata.views._ifrc_agent")
    def test_ifrc_suggest_resolves_official_corned_beef_500g_reference(
        self,
        mock_ifrc_agent,
        _mock_family_lookup,
        _mock_reference_lookup,
        mock_load_candidates,
        _mock_write_log,
        _mock_rate_limit,
        _mock_permission,
    ):
        mock_load_candidates.return_value = self._official_corned_beef_candidates()
        mock_ifrc_agent.return_value.generate.return_value = IFRCCodeSuggestion(
            item_code="FCANMEATBK05",
            standardised_name="CORNED BEEF CANNED 500 G",
            confidence=0.88,
            match_type="generated",
            construction_rationale="Group=F Family=CAN Category=MEAT Compact specification BK05",
            llm_used=False,
            grp="F",
            fam="CAN",
            cat="MEAT",
            spec_seg="BK05",
            seq=None,
        )

        request = self.factory.get(
            "/api/v1/masterdata/items/ifrc-suggest",
            {"name": "CORNED BEEF, CANNED, 500g"},
        )
        force_authenticate(request, user=self.user)
        response = views.ifrc_suggest(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["resolution_status"], "resolved")
        self.assertEqual(response.data["resolved_ifrc_item_ref_id"], 502)
        self.assertEqual(response.data["ifrc_code"], "FCANMEATCB500G")
        self.assertEqual(response.data["ifrc_description"], "Corned beef, canned, 500 g")
        self.assertNotEqual(response.data["ifrc_code"], "FCANMEATBK05")
        self.assertEqual(response.data["candidates"][0]["size_weight"], "500 G")
        self.assertIn("exact_size_weight_match", response.data["candidates"][0]["match_reasons"])
        self.assertTrue(response.data["direct_accept_allowed"])

    @patch("masterdata.permissions.MasterDataPermission.has_permission", return_value=True)
    @patch("masterdata.views._allow_ifrc_request", return_value=True)
    @patch("masterdata.views._write_ifrc_audit_log", return_value=123)
    @patch("masterdata.views._load_ifrc_reference_candidates")
    @patch("masterdata.views._fetch_ifrc_reference_by_code", return_value=None)
    @patch("masterdata.views._fetch_ifrc_family_id", return_value=41)
    @patch("masterdata.views._ifrc_agent")
    def test_ifrc_suggest_200kg_does_not_return_pseudo_code_when_only_governed_variants_exist(
        self,
        mock_ifrc_agent,
        _mock_family_lookup,
        _mock_reference_lookup,
        mock_load_candidates,
        _mock_write_log,
        _mock_rate_limit,
        _mock_permission,
    ):
        mock_load_candidates.return_value = self._official_corned_beef_candidates()
        mock_ifrc_agent.return_value.generate.return_value = IFRCCodeSuggestion(
            item_code="FCANMEATBK20",
            standardised_name="CORNED BEEF CANNED 200 KG",
            confidence=0.88,
            match_type="generated",
            construction_rationale="Group=F Family=CAN Category=MEAT Compact specification BK20",
            llm_used=False,
            grp="F",
            fam="CAN",
            cat="MEAT",
            spec_seg="BK20",
            seq=None,
        )

        request = self.factory.get(
            "/api/v1/masterdata/items/ifrc-suggest",
            {"name": "CORNED BEEF, CANNED, 200kg"},
        )
        force_authenticate(request, user=self.user)
        response = views.ifrc_suggest(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["resolution_status"], "unresolved")
        self.assertIsNone(response.data["resolved_ifrc_item_ref_id"])
        self.assertIsNone(response.data["ifrc_code"])
        self.assertEqual(response.data["candidate_count"], 0)
        self.assertEqual(response.data["candidates"], [])
        self.assertFalse(response.data["direct_accept_allowed"])

    @patch("masterdata.permissions.MasterDataPermission.has_permission", return_value=True)
    @patch("masterdata.views._allow_ifrc_request", return_value=False)
    def test_ifrc_suggest_rate_limited(self, _mock_rate_limit, _mock_permission):
        request = self.factory.get("/api/v1/masterdata/items/ifrc-suggest", {"name": "water"})
        force_authenticate(request, user=self.user)
        response = views.ifrc_suggest(request)

        self.assertEqual(response.status_code, 429)

    @patch("masterdata.permissions.MasterDataPermission.has_permission", return_value=True)
    @patch("masterdata.views._allow_ifrc_request", return_value=True)
    @patch("masterdata.views._write_ifrc_audit_log", return_value=123)
    @patch("masterdata.views._load_ifrc_reference_candidates")
    @patch(
        "masterdata.views._fetch_ifrc_reference_by_code",
        return_value={
            "ifrc_item_ref_id": 699,
            "ifrc_family_id": 22,
            "ifrc_code": "DANBAMOXTB50",
            "reference_desc": "Amoxicillin tablet",
            "category_code": "AMOX",
            "category_label": "Amoxicillin and Penicillins",
            "spec_segment": "TB50",
            "size_weight": "",
            "form": "TABLET",
            "material": "",
            "group_code": "D",
            "group_label": "Drugs",
            "family_code": "ANB",
            "family_label": "Antibiotics",
        },
    )
    @patch("masterdata.views._fetch_ifrc_family_id", return_value=22)
    @patch("masterdata.views._ifrc_agent")
    def test_ifrc_suggest_prefers_official_medical_variant_over_generated_code_match(
        self,
        mock_ifrc_agent,
        _mock_family_lookup,
        _mock_reference_lookup,
        mock_load_candidates,
        _mock_write_log,
        _mock_rate_limit,
        _mock_permission,
    ):
        mock_load_candidates.return_value = self._official_amoxicillin_candidates()
        mock_ifrc_agent.return_value.generate.return_value = IFRCCodeSuggestion(
            item_code="DANBAMOXTB50",
            standardised_name="AMOXICILLIN TABLET 500 MG",
            confidence=0.88,
            match_type="generated",
            construction_rationale="Group=D Family=ANB Category=AMOX Compact specification TB50",
            llm_used=False,
            grp="D",
            fam="ANB",
            cat="AMOX",
            spec_seg="TB50",
            seq=None,
        )

        request = self.factory.get(
            "/api/v1/masterdata/items/ifrc-suggest",
            {"name": "AMOXICILLIN TABLET, 500mg"},
        )
        force_authenticate(request, user=self.user)
        response = views.ifrc_suggest(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["resolution_status"], "resolved")
        self.assertEqual(response.data["resolved_ifrc_item_ref_id"], 612)
        self.assertEqual(response.data["ifrc_code"], "DANBAMOXAMX500MG")
        self.assertNotEqual(response.data["ifrc_code"], "DANBAMOXTB50")
        self.assertEqual(response.data["candidates"][0]["size_weight"], "500 MG")
        self.assertIn("exact_size_weight_match", response.data["candidates"][0]["match_reasons"])
        self.assertTrue(response.data["direct_accept_allowed"])

    @patch("masterdata.permissions.MasterDataPermission.has_permission", return_value=True)
    @patch("masterdata.views._allow_ifrc_request", return_value=True)
    @patch("masterdata.views._write_ifrc_audit_log", return_value=123)
    @patch("masterdata.views._load_ifrc_reference_candidates")
    @patch("masterdata.views._fetch_ifrc_reference_by_code", return_value=None)
    @patch("masterdata.views._fetch_ifrc_family_id", return_value=22)
    @patch("masterdata.views._ifrc_agent")
    def test_ifrc_suggest_returns_official_medical_candidates_for_ambiguous_spec(
        self,
        mock_ifrc_agent,
        _mock_family_lookup,
        _mock_reference_lookup,
        mock_load_candidates,
        _mock_write_log,
        _mock_rate_limit,
        _mock_permission,
    ):
        mock_load_candidates.return_value = self._official_amoxicillin_candidates()
        mock_ifrc_agent.return_value.generate.return_value = IFRCCodeSuggestion(
            item_code="DANBAMOXTB00",
            standardised_name="AMOXICILLIN TABLET",
            confidence=0.88,
            match_type="generated",
            construction_rationale="Group=D Family=ANB Category=AMOX Compact specification TB00",
            llm_used=False,
            grp="D",
            fam="ANB",
            cat="AMOX",
            spec_seg="TB00",
            seq=None,
        )

        request = self.factory.get(
            "/api/v1/masterdata/items/ifrc-suggest",
            {"name": "AMOXICILLIN TABLET"},
        )
        force_authenticate(request, user=self.user)
        response = views.ifrc_suggest(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["resolution_status"], "ambiguous")
        self.assertIsNone(response.data["resolved_ifrc_item_ref_id"])
        self.assertIsNone(response.data["ifrc_code"])
        self.assertEqual(response.data["candidate_count"], 2)
        self.assertFalse(response.data["direct_accept_allowed"])
        self.assertEqual(
            {candidate["ifrc_code"] for candidate in response.data["candidates"]},
            {"DANBAMOXAMX250MG", "DANBAMOXAMX500MG"},
        )


class IFRCSuggestionResolutionTests(SimpleTestCase):
    def test_rank_ifrc_reference_candidates_uses_form_hint_for_disambiguation(self):
        search_keys = [
            {
                "source": "primary",
                "group_code": "W",
                "family_code": "WTR",
                "category_code": "TABL",
                "ifrc_code": "",
                "spec_segment": "",
            }
        ]
        candidate_rows = [
            {
                "ifrc_item_ref_id": 1,
                "ifrc_family_id": 11,
                "ifrc_code": "WWTRTABLTB01",
                "reference_desc": "WATER PURIFICATION TABLET",
                "category_code": "TABL",
                "category_label": "Tablet",
                "spec_segment": "TB",
                "size_weight": "",
                "form": "TABLET",
                "material": "",
                "group_code": "W",
                "group_label": "WASH",
                "family_code": "WTR",
                "family_label": "Water Treatment",
            },
            {
                "ifrc_item_ref_id": 2,
                "ifrc_family_id": 11,
                "ifrc_code": "WWTRTABLPW01",
                "reference_desc": "WATER PURIFICATION POWDER",
                "category_code": "TABL",
                "category_label": "Tablet",
                "spec_segment": "PW",
                "size_weight": "",
                "form": "POWDER",
                "material": "",
                "group_code": "W",
                "group_label": "WASH",
                "family_code": "WTR",
                "family_label": "Water Treatment",
            },
        ]

        ranked = views._rank_ifrc_reference_candidates(
            candidate_rows,
            search_keys,
            item_name="water purification",
            ifrc_description="WATER PURIFICATION",
            size_weight="",
            form="powder",
            material="",
            auto_fill_threshold=0.85,
        )

        self.assertEqual(ranked[0]["ifrc_item_ref_id"], 2)
        self.assertIn("form_match", ranked[0]["match_reasons"])
        self.assertFalse(ranked[0]["auto_highlight"])
