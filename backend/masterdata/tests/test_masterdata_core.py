import importlib
from unittest.mock import MagicMock, patch
from types import SimpleNamespace

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
    _resolve_order_by,
    check_dependencies,
    check_uniqueness,
    create_record,
    update_record,
)
from masterdata.services.validation import _cross_field_validation
from masterdata.ifrc_code_agent import IFRCAgent, IFRCCodeSuggestion, _encode_spec, _next_sequence


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

    @patch("masterdata.views.list_records", return_value=([], 0, []))
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

    @patch("masterdata.views.list_records", return_value=([], 0, []))
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


class ItemUpdateValidationContextTests(SimpleTestCase):
    def setUp(self):
        self.cfg = TABLE_REGISTRY["items"]

    @patch("masterdata.views.update_record", return_value=(True, []))
    @patch("masterdata.views.validate_record", return_value={})
    @patch("masterdata.views.get_record")
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

        executed = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertEqual(len(executed), 9)
        self.assertTrue(any("JOIN public.transfer t" in sql for sql in executed))
        self.assertTrue(all("UPPER(COALESCE(" in sql for sql in executed))

        transfer_call = next(
            call for call in cursor.execute.call_args_list
            if "JOIN public.transfer t" in call.args[0]
        )
        transfer_params = transfer_call.args[1]
        self.assertIn(15, transfer_params)
        self.assertIn("DRAFT", transfer_params)
        self.assertIn("PENDING", transfer_params)

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

        executed = [call.args[0] for call in cursor.execute.call_args_list]
        expected_fragments = [
            "FROM public.inventory inv",
            "FROM public.itembatch ib",
            "FROM public.item_location il",
            "FROM public.transfer_item ti",
            "FROM public.needs_list_item nli",
            "FROM public.donation_item di",
            "FROM public.procurement_item pi",
            "FROM public.reliefpkg_item rpi",
            "FROM public.reliefrqst_item rri",
        ]
        for fragment in expected_fragments:
            self.assertTrue(any(fragment in sql for sql in executed), fragment)


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
    @patch("masterdata.ifrc_code_agent._next_sequence", return_value=(1, "SEQ=1 selected."))
    def test_suggest_generates_v3_code_when_llm_disabled(self, _mock_seq):
        agent = IFRCAgent()
        result = agent.suggest("water tabs")

        self.assertEqual(result.match_type, "fallback")
        self.assertIsNotNone(result.ifrc_code)
        self.assertRegex(result.ifrc_code, r"^[A-Z]{8}[A-Z0-9]{0,5}\d{2}$")
        self.assertEqual(result.group_code, "W")
        self.assertEqual(result.family_code, "WTR")
        self.assertEqual(result.category_code, "TABL")
        self.assertEqual(result.sequence, 1)

    def test_spec_encoding_prefers_form_then_size(self):
        self.assertEqual(_encode_spec("200 g", "tablet", "plastic"), "TB200")

    def test_spec_encoding_uses_material_when_form_absent(self):
        self.assertEqual(_encode_spec("20 l", "", "plastic"), "PL20L")

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

    @patch("masterdata.permissions.MasterDataPermission.has_permission", return_value=True)
    @patch("masterdata.views._allow_ifrc_request", return_value=True)
    @patch("masterdata.views._write_ifrc_audit_log", return_value=123)
    @patch("masterdata.views._ifrc_agent")
    def test_ifrc_suggest_success(
        self,
        mock_ifrc_agent,
        _mock_write_log,
        _mock_rate_limit,
        _mock_permission,
    ):
        suggestion = IFRCCodeSuggestion(
            item_code="WWTRTABLTB01",
            standardised_name="WATER PURIFICATION TABLET",
            confidence=0.88,
            match_type="generated",
            construction_rationale="Group=W Family=WTR Category=TABL Spec=TB SEQ=01",
            llm_used=False,
            grp="W",
            fam="WTR",
            cat="TABL",
            spec_seg="TB",
            seq=1,
        )
        mock_ifrc_agent.return_value.generate.return_value = suggestion
        mock_ifrc_agent.return_value.suggest.return_value = suggestion

        request = self.factory.get("/api/v1/masterdata/items/ifrc-suggest", {"name": "water tabs"})
        force_authenticate(request, user=self.user)
        response = views.ifrc_suggest(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["ifrc_code"], "WWTRTABLTB01")
        self.assertEqual(response.data["suggestion_id"], "123")
        self.assertEqual(response.data["match_type"], "generated")

    @patch("masterdata.permissions.MasterDataPermission.has_permission", return_value=True)
    @patch("masterdata.views._allow_ifrc_request", return_value=False)
    def test_ifrc_suggest_rate_limited(self, _mock_rate_limit, _mock_permission):
        request = self.factory.get("/api/v1/masterdata/items/ifrc-suggest", {"name": "water"})
        force_authenticate(request, user=self.user)
        response = views.ifrc_suggest(request)

        self.assertEqual(response.status_code, 429)
