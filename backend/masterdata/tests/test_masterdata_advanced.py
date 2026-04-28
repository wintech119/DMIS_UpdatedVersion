import importlib
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from api.rbac import (
    PERM_MASTERDATA_ADVANCED_CREATE,
    PERM_MASTERDATA_ADVANCED_EDIT,
    PERM_MASTERDATA_ADVANCED_INACTIVATE,
    PERM_MASTERDATA_ADVANCED_VIEW,
    PERM_MASTERDATA_TENANT_TYPE_MANAGE,
)
from masterdata import views, views_advanced
from masterdata.services import data_access as data_access_service
from masterdata.services import iam_data_access
from masterdata.services.data_access import TABLE_REGISTRY


SENSITIVE_USER_FIELDS = {
    "password_hash",
    "password_algo",
    "mfa_enabled",
    "mfa_secret",
    "failed_login_count",
    "lock_until_at",
    "last_login_at",
    "login_count",
    "password_changed_at",
}


class AdvancedMasterDataPermissionTests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()

    def _principal(self, permissions, user_id="tester"):
        return SimpleNamespace(
            is_authenticated=True,
            user_id=user_id,
            roles=[],
            permissions=list(permissions),
        )

    @patch("masterdata.views.list_records", return_value=([], 0, []))
    def test_user_list_requires_advanced_view(self, mock_list_records):
        standard_request = self.factory.get("/api/v1/masterdata/user/")
        force_authenticate(
            standard_request,
            user=self._principal([views.PERM_MASTERDATA_VIEW]),
        )

        standard_response = views.master_list_create(standard_request, "user")

        self.assertEqual(standard_response.status_code, 403)
        mock_list_records.assert_not_called()

        sysadmin_request = self.factory.get("/api/v1/masterdata/user/")
        force_authenticate(
            sysadmin_request,
            user=self._principal([PERM_MASTERDATA_ADVANCED_VIEW]),
        )

        sysadmin_response = views.master_list_create(sysadmin_request, "user")

        self.assertEqual(sysadmin_response.status_code, 200)
        mock_list_records.assert_called_once_with(
            "user",
            status_filter=None,
            search=None,
            order_by=None,
            limit=views.DEFAULT_PAGE_LIMIT,
            offset=0,
        )

    @patch("masterdata.views.list_records", return_value=([], 0, []))
    def test_role_list_requires_advanced_view(self, mock_list_records):
        standard_request = self.factory.get("/api/v1/masterdata/role/")
        force_authenticate(
            standard_request,
            user=self._principal([views.PERM_MASTERDATA_VIEW]),
        )

        standard_response = views.master_list_create(standard_request, "role")

        self.assertEqual(standard_response.status_code, 403)
        mock_list_records.assert_not_called()

        sysadmin_request = self.factory.get("/api/v1/masterdata/role/")
        force_authenticate(
            sysadmin_request,
            user=self._principal([PERM_MASTERDATA_ADVANCED_VIEW]),
        )

        sysadmin_response = views.master_list_create(sysadmin_request, "role")

        self.assertEqual(sysadmin_response.status_code, 200)
        mock_list_records.assert_called_once_with(
            "role",
            status_filter=None,
            search=None,
            order_by=None,
            limit=views.DEFAULT_PAGE_LIMIT,
            offset=0,
        )

    @patch("masterdata.views.list_records", return_value=([], 0, []))
    def test_tenant_type_list_requires_advanced_view(self, mock_list_records):
        standard_request = self.factory.get("/api/v1/masterdata/tenant_types/")
        force_authenticate(
            standard_request,
            user=self._principal([views.PERM_MASTERDATA_VIEW]),
        )

        standard_response = views.master_list_create(standard_request, "tenant_types")

        self.assertEqual(standard_response.status_code, 403)
        mock_list_records.assert_not_called()

        sysadmin_request = self.factory.get("/api/v1/masterdata/tenant_types/")
        force_authenticate(
            sysadmin_request,
            user=self._principal([PERM_MASTERDATA_ADVANCED_VIEW]),
        )

        sysadmin_response = views.master_list_create(sysadmin_request, "tenant_types")

        self.assertEqual(sysadmin_response.status_code, 200)
        mock_list_records.assert_called_once_with(
            "tenant_types",
            status_filter=None,
            search=None,
            order_by=None,
            limit=views.DEFAULT_PAGE_LIMIT,
            offset=0,
        )

    def test_tenant_type_registry_uses_ref_table_as_canonical_lookup(self):
        self.assertIn("tenant_types", TABLE_REGISTRY)
        tenant_type_field = TABLE_REGISTRY["tenant"].field("tenant_type")

        self.assertIsNotNone(tenant_type_field)
        self.assertEqual(tenant_type_field.fk_table, "ref_tenant_type")
        self.assertEqual(tenant_type_field.fk_pk, "tenant_type_code")
        self.assertIsNone(tenant_type_field.choices)

    def test_tenant_type_baseline_migration_adds_legacy_columns_before_seed(self):
        migration = importlib.import_module("masterdata.migrations.0012_tenant_type_baseline")
        events = []

        class FakeSchemaEditor:
            connection = SimpleNamespace(
                vendor="postgresql",
                ops=SimpleNamespace(quote_name=lambda value: f'"{value}"'),
            )

            def execute(self, sql, params=None):
                events.append(("execute", " ".join(str(sql).split())))

        def relation_exists(_schema_editor, _schema, relation):
            return relation in {"ref_tenant_type", "tenant"}

        def record_seed(_schema_editor, _schema_sql):
            events.append(("seed", None))

        with (
            patch.object(migration, "_schema_name", return_value="public"),
            patch.object(migration, "_relation_exists", side_effect=relation_exists),
            patch.object(migration, "_seed_baseline_tenant_types", side_effect=record_seed),
            patch.object(migration, "_migrate_tenant_rows"),
            patch.object(migration, "_retire_legacy_tenant_types"),
        ):
            migration._forwards(None, FakeSchemaEditor())

        description_column_index = next(
            index
            for index, event in enumerate(events)
            if event[0] == "execute"
            and "ALTER TABLE \"public\".ref_tenant_type ADD COLUMN IF NOT EXISTS description text"
            in event[1]
        )
        seed_index = next(index for index, event in enumerate(events) if event[0] == "seed")
        self.assertLess(description_column_index, seed_index)

    @patch("masterdata.views.get_record", return_value=({"id": 7, "code": "TEST_ROLE", "name": "Test Role"}, []))
    @patch("masterdata.views.create_record", return_value=(7, []))
    @patch("masterdata.services.validation.check_uniqueness", return_value=(True, []))
    def test_role_create_requires_advanced_create(
        self,
        _mock_check_uniqueness,
        mock_create_record,
        _mock_get_record,
    ):
        standard_request = self.factory.post(
            "/api/v1/masterdata/role/",
            {"code": "TEST_ROLE", "name": "Test Role"},
            format="json",
        )
        force_authenticate(
            standard_request,
            user=self._principal([views.PERM_MASTERDATA_CREATE]),
        )

        standard_response = views.master_list_create(standard_request, "role")

        self.assertEqual(standard_response.status_code, 403)
        mock_create_record.assert_not_called()

        sysadmin_request = self.factory.post(
            "/api/v1/masterdata/role/",
            {"code": "TEST_ROLE", "name": "Test Role"},
            format="json",
        )
        force_authenticate(
            sysadmin_request,
            user=self._principal([PERM_MASTERDATA_ADVANCED_CREATE]),
        )

        sysadmin_response = views.master_list_create(sysadmin_request, "role")

        self.assertEqual(sysadmin_response.status_code, 201)
        mock_create_record.assert_called_once()

    @patch(
        "masterdata.views.get_record",
        return_value=(
            {
                "user_id": 42,
                "username": "field-admin",
                "email": "field-admin@example.test",
                "status_code": "A",
            },
            [],
        ),
    )
    def test_user_password_hash_not_returned(self, _mock_get_record):
        user_fields = {field.name for field in TABLE_REGISTRY["user"].fields}
        self.assertFalse(SENSITIVE_USER_FIELDS.intersection(user_fields))

        request = self.factory.get("/api/v1/masterdata/user/42")
        force_authenticate(
            request,
            user=self._principal([PERM_MASTERDATA_ADVANCED_VIEW]),
        )

        response = views.master_detail_update(request, "user", "42")

        self.assertEqual(response.status_code, 200)
        record = response.data["record"]
        self.assertFalse(SENSITIVE_USER_FIELDS.intersection(record))

    @patch("masterdata.services.data_access._execute_create_insert", return_value=42)
    @patch("masterdata.services.data_access._is_sqlite", return_value=False)
    def test_user_create_uses_hidden_identity_defaults(self, _mock_is_sqlite, mock_insert):
        pk_value, warnings = data_access_service.create_record(
            "user",
            {"username": "field.admin", "email": "field.admin@example.test"},
            "tester",
        )

        self.assertEqual(pk_value, 42)
        self.assertEqual(warnings, [])

        _cfg, _schema, col_sql, ph_sql, final_values, _data = mock_insert.call_args.args
        columns = [column.strip() for column in col_sql.split(",")]
        placeholders = [placeholder.strip() for placeholder in ph_sql.split(",")]
        remaining_values = list(final_values)
        values_by_column = {}
        for column, placeholder in zip(columns, placeholders):
            if placeholder == "%s":
                values_by_column[column] = remaining_values.pop(0)

        self.assertEqual(values_by_column["password_hash"], "")
        self.assertEqual(values_by_column["password_algo"], "argon2id")
        self.assertEqual(values_by_column["user_name"], "field.admin")
        self.assertIs(values_by_column["mfa_enabled"], False)
        self.assertEqual(values_by_column["failed_login_count"], 0)
        self.assertEqual(values_by_column["login_count"], 0)

    def test_check_fk_exists_can_require_active_status(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = (1,)
        cursor_context = MagicMock()
        cursor_context.__enter__.return_value = cursor
        cursor_context.__exit__.return_value = False
        connection = SimpleNamespace(cursor=lambda: cursor_context)

        with (
            patch("masterdata.services.data_access._is_sqlite", return_value=False),
            patch("masterdata.services.data_access._schema_name", return_value="public"),
            patch("masterdata.services.data_access.connection", connection),
        ):
            exists, warnings = data_access_service.check_fk_exists(
                "tenant",
                "tenant_id",
                2,
                active_only=True,
            )

        self.assertTrue(exists)
        self.assertEqual(warnings, [])
        sql, params = cursor.execute.call_args.args
        self.assertIn('FROM "public"."tenant"', sql)
        self.assertIn('"tenant_id" = %s', sql)
        self.assertIn('"status_code" = %s', sql)
        self.assertEqual(params, [2, "A"])

    @patch("masterdata.views.transaction.atomic", side_effect=lambda: nullcontext())
    @patch(
        "masterdata.views.get_record",
        return_value=(
            {
                "user_id": 42,
                "username": "field.admin",
                "email": "field.admin@example.test",
                "primary_tenant_id": 2,
                "primary_tenant_code": "ODPEM",
                "primary_tenant_name": "ODPEM National Coordination",
                "primary_tenant_label": "ODPEM - ODPEM National Coordination",
            },
            [],
        ),
    )
    @patch("masterdata.views.iam_data_access.count_active_primary_tenant_memberships", return_value=1)
    @patch("masterdata.views.iam_data_access.has_active_primary_tenant_membership", return_value=True)
    @patch("masterdata.views.iam_data_access.assign_tenant_user", return_value=True)
    @patch("masterdata.views.create_record", return_value=(42, []))
    @patch("masterdata.views.check_fk_exists", return_value=(True, []))
    @patch("masterdata.services.validation.check_uniqueness", return_value=(True, []))
    def test_user_create_requires_tenant_and_creates_primary_membership(
        self,
        _mock_check_uniqueness,
        _mock_tenant_fk,
        mock_create_record,
        mock_assign_tenant_user,
        mock_has_primary,
        mock_count_primary,
        _mock_get_record,
        _mock_atomic,
    ):
        request = self.factory.post(
            "/api/v1/masterdata/user/",
            {
                "tenant_id": 2,
                "username": "field.admin",
                "email": "field.admin@example.test",
            },
            format="json",
        )
        force_authenticate(
            request,
            user=self._principal([PERM_MASTERDATA_ADVANCED_CREATE], user_id="99"),
        )

        response = views.master_list_create(request, "user")

        self.assertEqual(response.status_code, 201)
        created_payload = mock_create_record.call_args.args[1]
        self.assertNotIn("tenant_id", created_payload)
        self.assertNotIn("agency_id", created_payload)
        mock_assign_tenant_user.assert_called_once_with(
            2,
            42,
            "STANDARD",
            "99",
            is_primary_tenant=True,
        )
        mock_has_primary.assert_called_once_with(2, 42)
        mock_count_primary.assert_called_once_with(42)
        self.assertEqual(response.data["record"]["primary_tenant_id"], 2)

    @patch("masterdata.views.create_record")
    @patch("masterdata.views.iam_data_access.assign_tenant_user")
    def test_user_create_rejects_missing_tenant(self, mock_assign_tenant_user, mock_create_record):
        request = self.factory.post(
            "/api/v1/masterdata/user/",
            {
                "username": "field.admin",
                "email": "field.admin@example.test",
            },
            format="json",
        )
        force_authenticate(
            request,
            user=self._principal([PERM_MASTERDATA_ADVANCED_CREATE]),
        )

        response = views.master_list_create(request, "user")

        self.assertEqual(response.status_code, 400)
        self.assertIn("tenant_id", response.data["errors"])
        mock_create_record.assert_not_called()
        mock_assign_tenant_user.assert_not_called()

    @patch("masterdata.views.create_record")
    @patch("masterdata.views.check_fk_exists", return_value=(False, []))
    def test_user_create_rejects_invalid_tenant(self, _mock_tenant_fk, mock_create_record):
        request = self.factory.post(
            "/api/v1/masterdata/user/",
            {
                "tenant_id": 999,
                "username": "field.admin",
                "email": "field.admin@example.test",
            },
            format="json",
        )
        force_authenticate(
            request,
            user=self._principal([PERM_MASTERDATA_ADVANCED_CREATE]),
        )

        response = views.master_list_create(request, "user")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["errors"]["tenant_id"], "Selected Tenant does not exist.")
        mock_create_record.assert_not_called()

    @patch("masterdata.views.iam_data_access.assign_tenant_user")
    @patch("masterdata.views.create_record")
    @patch("masterdata.views.check_fk_exists", side_effect=[(True, []), (False, [])])
    def test_user_create_rejects_inactive_tenant(
        self,
        _mock_tenant_fk,
        mock_create_record,
        mock_assign_tenant_user,
    ):
        request = self.factory.post(
            "/api/v1/masterdata/user/",
            {
                "tenant_id": 2,
                "username": "field.admin",
                "email": "field.admin@example.test",
            },
            format="json",
        )
        force_authenticate(
            request,
            user=self._principal([PERM_MASTERDATA_ADVANCED_CREATE]),
        )

        response = views.master_list_create(request, "user")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["errors"]["tenant_id"], "Selected Tenant is inactive.")
        mock_create_record.assert_not_called()
        mock_assign_tenant_user.assert_not_called()

    @patch("masterdata.views.create_record")
    @patch("masterdata.views.check_fk_exists", return_value=(True, []))
    @patch("masterdata.services.validation.check_fk_exists", return_value=(False, []))
    @patch("masterdata.services.validation.check_uniqueness", return_value=(True, []))
    def test_user_create_validates_supplied_agency_fk(
        self,
        _mock_check_uniqueness,
        _mock_agency_fk,
        _mock_tenant_fk,
        mock_create_record,
    ):
        request = self.factory.post(
            "/api/v1/masterdata/user/",
            {
                "tenant_id": 2,
                "agency_id": 999,
                "username": "field.admin",
                "email": "field.admin@example.test",
            },
            format="json",
        )
        force_authenticate(
            request,
            user=self._principal([PERM_MASTERDATA_ADVANCED_CREATE]),
        )

        response = views.master_list_create(request, "user")

        self.assertEqual(response.status_code, 400)
        self.assertIn("agency_id", response.data["errors"])
        mock_create_record.assert_not_called()

    @patch("masterdata.views.transaction.atomic", side_effect=lambda: nullcontext())
    @patch("masterdata.views.get_record")
    @patch("masterdata.views.iam_data_access.count_active_primary_tenant_memberships")
    @patch("masterdata.views.iam_data_access.has_active_primary_tenant_membership", return_value=True)
    @patch("masterdata.views.iam_data_access.assign_tenant_user", return_value=False)
    @patch("masterdata.views.create_record", return_value=(42, []))
    @patch("masterdata.views.check_fk_exists", return_value=(True, []))
    @patch("masterdata.services.validation.check_uniqueness", return_value=(True, []))
    def test_user_create_rolls_back_when_membership_insert_returns_false(
        self,
        _mock_check_uniqueness,
        _mock_tenant_fk,
        _mock_create_record,
        _mock_assign_tenant_user,
        _mock_has_primary,
        mock_count_primary,
        mock_get_record,
        _mock_atomic,
    ):
        request = self.factory.post(
            "/api/v1/masterdata/user/",
            {
                "tenant_id": 2,
                "username": "field.admin",
                "email": "field.admin@example.test",
            },
            format="json",
        )
        force_authenticate(
            request,
            user=self._principal([PERM_MASTERDATA_ADVANCED_CREATE]),
        )

        response = views.master_list_create(request, "user")

        self.assertEqual(response.status_code, 500)
        self.assertIn("primary_tenant_membership_create_failed", response.data["warnings"])
        mock_count_primary.assert_not_called()
        mock_get_record.assert_not_called()

    @patch("masterdata.views.transaction.atomic", side_effect=lambda: nullcontext())
    @patch("masterdata.views.get_record")
    @patch("masterdata.views.iam_data_access.count_active_primary_tenant_memberships")
    @patch("masterdata.views.iam_data_access.has_active_primary_tenant_membership", return_value=False)
    @patch("masterdata.views.iam_data_access.assign_tenant_user", return_value=True)
    @patch("masterdata.views.create_record", return_value=(42, []))
    @patch("masterdata.views.check_fk_exists", return_value=(True, []))
    @patch("masterdata.services.validation.check_uniqueness", return_value=(True, []))
    def test_user_create_rolls_back_when_membership_verification_finds_no_row(
        self,
        _mock_check_uniqueness,
        _mock_tenant_fk,
        _mock_create_record,
        _mock_assign_tenant_user,
        _mock_has_primary,
        mock_count_primary,
        mock_get_record,
        _mock_atomic,
    ):
        request = self.factory.post(
            "/api/v1/masterdata/user/",
            {
                "tenant_id": 2,
                "username": "field.admin",
                "email": "field.admin@example.test",
            },
            format="json",
        )
        force_authenticate(
            request,
            user=self._principal([PERM_MASTERDATA_ADVANCED_CREATE]),
        )

        response = views.master_list_create(request, "user")

        self.assertEqual(response.status_code, 500)
        self.assertIn("primary_tenant_membership_create_failed", response.data["warnings"])
        mock_count_primary.assert_not_called()
        mock_get_record.assert_not_called()

    @patch("masterdata.views.transaction.atomic", side_effect=lambda: nullcontext())
    @patch("masterdata.views.get_record")
    @patch("masterdata.views.iam_data_access.count_active_primary_tenant_memberships")
    @patch("masterdata.views.iam_data_access.has_active_primary_tenant_membership")
    @patch("masterdata.views.iam_data_access.assign_tenant_user", side_effect=RuntimeError("insert failed"))
    @patch("masterdata.views.create_record", return_value=(42, []))
    @patch("masterdata.views.check_fk_exists", return_value=(True, []))
    @patch("masterdata.services.validation.check_uniqueness", return_value=(True, []))
    def test_user_create_rolls_back_when_membership_insert_raises(
        self,
        _mock_check_uniqueness,
        _mock_tenant_fk,
        _mock_create_record,
        _mock_assign_tenant_user,
        mock_has_primary,
        mock_count_primary,
        mock_get_record,
        _mock_atomic,
    ):
        request = self.factory.post(
            "/api/v1/masterdata/user/",
            {
                "tenant_id": 2,
                "username": "field.admin",
                "email": "field.admin@example.test",
            },
            format="json",
        )
        force_authenticate(
            request,
            user=self._principal([PERM_MASTERDATA_ADVANCED_CREATE]),
        )

        response = views.master_list_create(request, "user")

        self.assertEqual(response.status_code, 500)
        self.assertIn("primary_tenant_membership_create_failed", response.data["warnings"])
        mock_has_primary.assert_not_called()
        mock_count_primary.assert_not_called()
        mock_get_record.assert_not_called()

    @patch("masterdata.views.transaction.atomic", side_effect=lambda: nullcontext())
    @patch("masterdata.views.get_record")
    @patch("masterdata.views.iam_data_access.count_active_primary_tenant_memberships", return_value=0)
    @patch("masterdata.views.iam_data_access.has_active_primary_tenant_membership", return_value=True)
    @patch("masterdata.views.iam_data_access.assign_tenant_user", return_value=True)
    @patch("masterdata.views.create_record", return_value=(42, []))
    @patch("masterdata.views.check_fk_exists", return_value=(True, []))
    @patch("masterdata.services.validation.check_uniqueness", return_value=(True, []))
    def test_user_create_rolls_back_when_primary_count_is_not_exactly_one(
        self,
        _mock_check_uniqueness,
        _mock_tenant_fk,
        _mock_create_record,
        _mock_assign_tenant_user,
        _mock_has_primary,
        _mock_count_primary,
        mock_get_record,
        _mock_atomic,
    ):
        request = self.factory.post(
            "/api/v1/masterdata/user/",
            {
                "tenant_id": 2,
                "username": "field.admin",
                "email": "field.admin@example.test",
            },
            format="json",
        )
        force_authenticate(
            request,
            user=self._principal([PERM_MASTERDATA_ADVANCED_CREATE]),
        )

        response = views.master_list_create(request, "user")

        self.assertEqual(response.status_code, 500)
        self.assertIn("primary_tenant_membership_create_failed", response.data["warnings"])
        mock_get_record.assert_not_called()

    @patch("masterdata.views.update_record")
    def test_user_edit_rejects_flat_tenant_change(self, mock_update_record):
        request = self.factory.patch(
            "/api/v1/masterdata/user/42",
            {"tenant_id": 3, "first_name": "Kemar"},
            format="json",
        )
        force_authenticate(
            request,
            user=self._principal([PERM_MASTERDATA_ADVANCED_EDIT]),
        )

        response = views.master_detail_update(request, "user", "42")

        self.assertEqual(response.status_code, 400)
        self.assertIn("tenant_id", response.data["errors"])
        mock_update_record.assert_not_called()

    def test_user_list_returns_primary_tenant_from_membership(self):
        user_row = (
            42,
            "field.admin",
            "field.admin@example.test",
            "Field",
            "Admin",
            "Field Admin",
            True,
            None,
            None,
            None,
            "America/Jamaica",
            "en",
            "A",
        )
        membership_row = (
            42,
            2,
            "ODPEM",
            "ODPEM National Coordination",
            True,
            None,
        )
        cursor = MagicMock()
        cursor.fetchone.return_value = (1,)
        cursor.fetchall.side_effect = [[user_row], [membership_row]]
        cursor_context = MagicMock()
        cursor_context.__enter__.return_value = cursor
        cursor_context.__exit__.return_value = False
        connection = SimpleNamespace(cursor=lambda: cursor_context)

        with (
            patch("masterdata.services.data_access._is_sqlite", return_value=False),
            patch("masterdata.services.data_access._schema_name", return_value="public"),
            patch("masterdata.services.data_access.connection", connection),
        ):
            rows, total, warnings = data_access_service.list_records("user")

        self.assertEqual(total, 1)
        self.assertEqual(warnings, [])
        self.assertEqual(rows[0]["primary_tenant_id"], 2)
        self.assertEqual(rows[0]["primary_tenant_label"], "ODPEM - ODPEM National Coordination")

    def test_user_detail_returns_primary_tenant_from_membership(self):
        cfg = TABLE_REGISTRY["user"]
        user_values = [
            42,
            "field.admin",
            "field.admin@example.test",
            "Field",
            "Admin",
            "Field Admin",
            True,
            None,
            None,
            None,
            "America/Jamaica",
            "en",
            "A",
            None,
            None,
            1,
        ]
        self.assertEqual(len(user_values), len(cfg.fields) + 3)
        membership_row = (
            42,
            2,
            "ODPEM",
            "ODPEM National Coordination",
            True,
            None,
        )
        cursor = MagicMock()
        cursor.fetchone.return_value = tuple(user_values)
        cursor.fetchall.return_value = [membership_row]
        cursor_context = MagicMock()
        cursor_context.__enter__.return_value = cursor
        cursor_context.__exit__.return_value = False
        connection = SimpleNamespace(cursor=lambda: cursor_context)

        with (
            patch("masterdata.services.data_access._is_sqlite", return_value=False),
            patch("masterdata.services.data_access._schema_name", return_value="public"),
            patch("masterdata.services.data_access.connection", connection),
        ):
            record, warnings = data_access_service.get_record("user", 42)

        self.assertEqual(warnings, [])
        self.assertIsNotNone(record)
        self.assertEqual(record["primary_tenant_id"], 2)
        self.assertEqual(record["primary_tenant_label"], "ODPEM - ODPEM National Coordination")

    def test_user_primary_tenant_display_warns_for_multiple_primary_and_fallback(self):
        rows = [
            {"user_id": 42},
            {"user_id": 43},
            {"user_id": 44},
        ]
        cursor = MagicMock()
        cursor.fetchall.return_value = [
            (42, 2, "ODPEM", "ODPEM National Coordination", True, "2026-01-01T00:00:00Z"),
            (42, 3, "NEOC", "NEOC", True, "2026-01-02T00:00:00Z"),
            (43, 5, "MLSS", "Ministry of Labour and Social Security", False, "2026-01-01T00:00:00Z"),
        ]
        cursor_context = MagicMock()
        cursor_context.__enter__.return_value = cursor
        cursor_context.__exit__.return_value = False
        connection = SimpleNamespace(cursor=lambda: cursor_context)

        with (
            patch("masterdata.services.data_access._schema_name", return_value="public"),
            patch("masterdata.services.data_access.connection", connection),
            self.assertLogs("masterdata.services.data_access", level="WARNING") as log_context,
        ):
            data_access_service._attach_primary_tenant_display(rows)

        self.assertEqual(rows[0]["primary_tenant_id"], 2)
        self.assertEqual(rows[1]["primary_tenant_id"], 5)
        self.assertIsNone(rows[2]["primary_tenant_id"])
        self.assertTrue(
            any("multiple active primary tenant memberships" in message for message in log_context.output)
        )
        self.assertTrue(
            any("active tenant memberships but no primary" in message for message in log_context.output)
        )
        self.assertTrue(
            any("no active tenant membership" in message for message in log_context.output)
        )

    def test_role_code_pattern_enforced(self):
        request = self.factory.post(
            "/api/v1/masterdata/role/",
            {"code": "lower-case", "name": "Invalid Role"},
            format="json",
        )
        force_authenticate(
            request,
            user=self._principal([PERM_MASTERDATA_ADVANCED_CREATE]),
        )

        response = views.master_list_create(request, "role")

        self.assertEqual(response.status_code, 400)
        self.assertIn("code", response.data["errors"])

    @patch("masterdata.views.create_record")
    @patch("masterdata.views.can_manage_tenant_types", return_value=False)
    @patch("masterdata.views.resolve_tenant_context")
    def test_tenant_type_create_requires_context_guard(
        self,
        _mock_context,
        _mock_can_manage,
        mock_create_record,
    ):
        request = self.factory.post(
            "/api/v1/masterdata/tenant_types/",
            {
                "tenant_type_code": "UTILITY",
                "tenant_type_name": "Utility",
                "description": "Lifeline operators.",
                "display_order": 70,
                "status_code": "A",
            },
            format="json",
        )
        force_authenticate(
            request,
            user=self._principal(
                [PERM_MASTERDATA_ADVANCED_CREATE, PERM_MASTERDATA_TENANT_TYPE_MANAGE]
            ),
        )

        response = views.master_list_create(request, "tenant_types")

        self.assertEqual(response.status_code, 403)
        mock_create_record.assert_not_called()

    @patch("masterdata.views.create_record")
    @patch("masterdata.views.can_manage_tenant_types", return_value=True)
    @patch("masterdata.views.resolve_tenant_context")
    def test_tenant_type_create_rejects_non_baseline_code(
        self,
        _mock_context,
        _mock_can_manage,
        mock_create_record,
    ):
        request = self.factory.post(
            "/api/v1/masterdata/tenant_types/",
            {
                "tenant_type_code": "PRIVATE_SECTOR",
                "tenant_type_name": "Private Sector",
                "status_code": "A",
            },
            format="json",
        )
        force_authenticate(
            request,
            user=self._principal(
                [PERM_MASTERDATA_ADVANCED_CREATE, PERM_MASTERDATA_TENANT_TYPE_MANAGE]
            ),
        )

        response = views.master_list_create(request, "tenant_types")

        self.assertEqual(response.status_code, 400)
        self.assertIn("tenant_type_code", response.data["errors"])
        mock_create_record.assert_not_called()

    @patch("masterdata.views.get_record", return_value=({"tenant_type_code": "UTILITY"}, []))
    @patch("masterdata.views.create_record", return_value=("UTILITY", []))
    @patch("masterdata.services.validation.check_uniqueness", return_value=(True, []))
    @patch("masterdata.views.can_manage_tenant_types", return_value=True)
    @patch("masterdata.views.resolve_tenant_context")
    def test_tenant_type_create_allows_missing_baseline_code(
        self,
        _mock_context,
        _mock_can_manage,
        _mock_check_uniqueness,
        mock_create_record,
        _mock_get_record,
    ):
        request = self.factory.post(
            "/api/v1/masterdata/tenant_types/",
            {
                "tenant_type_code": "utility",
                "tenant_type_name": "Utility",
                "description": "Lifeline operators.",
                "display_order": 70,
                "status_code": "A",
            },
            format="json",
        )
        force_authenticate(
            request,
            user=self._principal(
                [PERM_MASTERDATA_ADVANCED_CREATE, PERM_MASTERDATA_TENANT_TYPE_MANAGE]
            ),
        )

        response = views.master_list_create(request, "tenant_types")

        self.assertEqual(response.status_code, 201)
        created_payload = mock_create_record.call_args.args[1]
        self.assertEqual(created_payload["tenant_type_code"], "UTILITY")

    @patch("masterdata.views.inactivate_record")
    @patch("masterdata.views.check_dependencies", return_value=(["Tenants (2 records)"], []))
    @patch("masterdata.views.can_manage_tenant_types", return_value=True)
    @patch("masterdata.views.resolve_tenant_context")
    def test_tenant_type_inactivate_blocks_when_in_use(
        self,
        _mock_context,
        _mock_can_manage,
        _mock_check_dependencies,
        mock_inactivate_record,
    ):
        request = self.factory.post("/api/v1/masterdata/tenant_types/UTILITY/inactivate", {}, format="json")
        force_authenticate(
            request,
            user=self._principal(
                [
                    PERM_MASTERDATA_ADVANCED_EDIT,
                    PERM_MASTERDATA_ADVANCED_INACTIVATE,
                    PERM_MASTERDATA_TENANT_TYPE_MANAGE,
                ]
            ),
        )

        response = views.master_inactivate(request, "tenant_types", "UTILITY")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["blocking"], ["Tenants (2 records)"])
        mock_inactivate_record.assert_not_called()

    @patch("masterdata.views.update_record")
    @patch("masterdata.views.check_dependencies", return_value=(["Tenants (2 records)"], []))
    @patch("masterdata.views.can_manage_tenant_types", return_value=True)
    @patch("masterdata.views.resolve_tenant_context")
    def test_tenant_type_patch_inactivate_blocks_when_in_use(
        self,
        _mock_context,
        _mock_can_manage,
        _mock_check_dependencies,
        mock_update_record,
    ):
        request = self.factory.patch(
            "/api/v1/masterdata/tenant_types/UTILITY",
            {"status_code": "I"},
            format="json",
        )
        force_authenticate(
            request,
            user=self._principal(
                [PERM_MASTERDATA_ADVANCED_EDIT, PERM_MASTERDATA_TENANT_TYPE_MANAGE]
            ),
        )

        response = views.master_detail_update(request, "tenant_types", "UTILITY")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["blocking"], ["Tenants (2 records)"])
        mock_update_record.assert_not_called()

    @patch("masterdata.services.validation.check_composite_uniqueness", return_value=(False, []))
    def test_permission_uniqueness(self, _mock_check_composite_uniqueness):
        request = self.factory.post(
            "/api/v1/masterdata/permission/",
            {"resource": "masterdata.advanced", "action": "view"},
            format="json",
        )
        force_authenticate(
            request,
            user=self._principal([PERM_MASTERDATA_ADVANCED_CREATE]),
        )

        response = views.master_list_create(request, "permission")

        self.assertEqual(response.status_code, 400)
        self.assertIn("resource", response.data["errors"])

    def test_user_roles_endpoint_get_post_delete_and_403(self):
        with (
            patch("masterdata.views_advanced.iam_data_access.list_user_roles") as mock_list,
            patch("masterdata.views_advanced.iam_data_access.assign_user_role") as mock_assign,
            patch("masterdata.views_advanced.iam_data_access.revoke_user_role") as mock_revoke,
        ):
            mock_list.return_value = [
                {"role_id": 3, "code": "LOGISTICS", "name": "Logistics", "assigned_at": "now"}
            ]
            mock_assign.side_effect = [True, False]
            mock_revoke.side_effect = [True, False]

            denied = self.factory.get("/api/v1/masterdata/user/7/roles")
            force_authenticate(denied, user=self._principal([views.PERM_MASTERDATA_VIEW]))
            denied_response = views_advanced.user_roles(denied, 7)
            self.assertEqual(denied_response.status_code, 403)
            mock_list.assert_not_called()

            get_request = self.factory.get("/api/v1/masterdata/user/7/roles")
            force_authenticate(
                get_request,
                user=self._principal([PERM_MASTERDATA_ADVANCED_VIEW]),
            )
            get_response = views_advanced.user_roles(get_request, 7)
            self.assertEqual(get_response.status_code, 200)
            self.assertEqual(get_response.data["results"][0]["role_id"], 3)

            post_request = self.factory.post(
                "/api/v1/masterdata/user/7/roles",
                {"role_id": 3},
                format="json",
            )
            force_authenticate(
                post_request,
                user=self._principal([PERM_MASTERDATA_ADVANCED_EDIT], user_id="99"),
            )
            post_response = views_advanced.user_roles(post_request, 7)
            self.assertEqual(post_response.status_code, 201)
            mock_assign.assert_called_with(7, 3, 99)

            idem_request = self.factory.post(
                "/api/v1/masterdata/user/7/roles",
                {"role_id": 3},
                format="json",
            )
            force_authenticate(
                idem_request,
                user=self._principal([PERM_MASTERDATA_ADVANCED_EDIT], user_id="99"),
            )
            idem_response = views_advanced.user_roles(idem_request, 7)
            self.assertEqual(idem_response.status_code, 200)

            delete_request = self.factory.delete("/api/v1/masterdata/user/7/roles?role_id=3")
            force_authenticate(
                delete_request,
                user=self._principal([PERM_MASTERDATA_ADVANCED_EDIT], user_id="99"),
            )
            delete_response = views_advanced.user_roles(delete_request, 7)
            self.assertEqual(delete_response.status_code, 204)

            missing_delete = self.factory.delete("/api/v1/masterdata/user/7/roles?role_id=4")
            force_authenticate(
                missing_delete,
                user=self._principal([PERM_MASTERDATA_ADVANCED_EDIT], user_id="99"),
            )
            missing_response = views_advanced.user_roles(missing_delete, 7)
            self.assertEqual(missing_response.status_code, 404)

    def test_role_permissions_endpoint_get_post_delete_and_403(self):
        with (
            patch("masterdata.views_advanced.iam_data_access.list_role_permissions") as mock_list,
            patch("masterdata.views_advanced.iam_data_access.assign_role_permission") as mock_assign,
            patch("masterdata.views_advanced.iam_data_access.revoke_role_permission") as mock_revoke,
        ):
            mock_list.return_value = [
                {
                    "perm_id": 8,
                    "resource": "masterdata.advanced",
                    "action": "view",
                    "scope_json": {"tenant_id": 1},
                }
            ]
            mock_assign.side_effect = [True, False]
            mock_revoke.side_effect = [True, False]

            denied = self.factory.get("/api/v1/masterdata/role/3/permissions")
            force_authenticate(denied, user=self._principal([views.PERM_MASTERDATA_VIEW]))
            denied_response = views_advanced.role_permissions(denied, 3)
            self.assertEqual(denied_response.status_code, 403)
            mock_list.assert_not_called()

            get_request = self.factory.get("/api/v1/masterdata/role/3/permissions")
            force_authenticate(
                get_request,
                user=self._principal([PERM_MASTERDATA_ADVANCED_VIEW]),
            )
            get_response = views_advanced.role_permissions(get_request, 3)
            self.assertEqual(get_response.status_code, 200)
            self.assertEqual(get_response.data["results"][0]["perm_id"], 8)

            post_request = self.factory.post(
                "/api/v1/masterdata/role/3/permissions",
                {"perm_id": 8, "scope_json": {"tenant_id": 1}},
                format="json",
            )
            force_authenticate(
                post_request,
                user=self._principal([PERM_MASTERDATA_ADVANCED_EDIT], user_id="99"),
            )
            post_response = views_advanced.role_permissions(post_request, 3)
            self.assertEqual(post_response.status_code, 201)
            mock_assign.assert_called_with(3, 8, "99", {"tenant_id": 1})

            idem_request = self.factory.post(
                "/api/v1/masterdata/role/3/permissions",
                {"perm_id": 8},
                format="json",
            )
            force_authenticate(
                idem_request,
                user=self._principal([PERM_MASTERDATA_ADVANCED_EDIT], user_id="99"),
            )
            idem_response = views_advanced.role_permissions(idem_request, 3)
            self.assertEqual(idem_response.status_code, 200)

            delete_request = self.factory.delete("/api/v1/masterdata/role/3/permissions?perm_id=8")
            force_authenticate(
                delete_request,
                user=self._principal([PERM_MASTERDATA_ADVANCED_EDIT], user_id="99"),
            )
            delete_response = views_advanced.role_permissions(delete_request, 3)
            self.assertEqual(delete_response.status_code, 204)

            missing_delete = self.factory.delete("/api/v1/masterdata/role/3/permissions?perm_id=9")
            force_authenticate(
                missing_delete,
                user=self._principal([PERM_MASTERDATA_ADVANCED_EDIT], user_id="99"),
            )
            missing_response = views_advanced.role_permissions(missing_delete, 3)
            self.assertEqual(missing_response.status_code, 404)

    def test_tenant_users_endpoint_get_post_delete_and_403(self):
        with (
            patch("masterdata.views_advanced.iam_data_access.list_tenant_users") as mock_list,
            patch("masterdata.views_advanced.iam_data_access.assign_tenant_user") as mock_assign,
            patch("masterdata.views_advanced.iam_data_access.revoke_tenant_user") as mock_revoke,
        ):
            mock_list.return_value = [
                {
                    "user_id": 7,
                    "username": "field-admin",
                    "email": "field-admin@example.test",
                    "access_level": "ADMIN",
                    "is_primary_tenant": True,
                    "last_login_at": None,
                }
            ]
            mock_assign.side_effect = [True, False]
            mock_revoke.side_effect = [True, False]

            denied = self.factory.get("/api/v1/masterdata/tenant/2/users")
            force_authenticate(denied, user=self._principal([views.PERM_MASTERDATA_VIEW]))
            denied_response = views_advanced.tenant_users(denied, 2)
            self.assertEqual(denied_response.status_code, 403)
            mock_list.assert_not_called()

            get_request = self.factory.get("/api/v1/masterdata/tenant/2/users")
            force_authenticate(
                get_request,
                user=self._principal([PERM_MASTERDATA_ADVANCED_VIEW]),
            )
            get_response = views_advanced.tenant_users(get_request, 2)
            self.assertEqual(get_response.status_code, 200)
            self.assertEqual(get_response.data["results"][0]["access_level"], "ADMIN")

            post_request = self.factory.post(
                "/api/v1/masterdata/tenant/2/users",
                {"user_id": 7, "access_level": "admin"},
                format="json",
            )
            force_authenticate(
                post_request,
                user=self._principal([PERM_MASTERDATA_ADVANCED_EDIT], user_id="99"),
            )
            post_response = views_advanced.tenant_users(post_request, 2)
            self.assertEqual(post_response.status_code, 201)
            mock_assign.assert_called_with(2, 7, "ADMIN", 99)

            idem_request = self.factory.post(
                "/api/v1/masterdata/tenant/2/users",
                {"user_id": 7, "access_level": "ADMIN"},
                format="json",
            )
            force_authenticate(
                idem_request,
                user=self._principal([PERM_MASTERDATA_ADVANCED_EDIT], user_id="99"),
            )
            idem_response = views_advanced.tenant_users(idem_request, 2)
            self.assertEqual(idem_response.status_code, 200)

            delete_request = self.factory.delete("/api/v1/masterdata/tenant/2/users?user_id=7")
            force_authenticate(
                delete_request,
                user=self._principal([PERM_MASTERDATA_ADVANCED_EDIT], user_id="99"),
            )
            delete_response = views_advanced.tenant_users(delete_request, 2)
            self.assertEqual(delete_response.status_code, 204)

            missing_delete = self.factory.delete("/api/v1/masterdata/tenant/2/users?user_id=8")
            force_authenticate(
                missing_delete,
                user=self._principal([PERM_MASTERDATA_ADVANCED_EDIT], user_id="99"),
            )
            missing_response = views_advanced.tenant_users(missing_delete, 2)
            self.assertEqual(missing_response.status_code, 404)

    def test_tenant_user_roles_endpoint_get_post_delete_and_403(self):
        with (
            patch("masterdata.views_advanced.iam_data_access.list_user_tenant_roles") as mock_list,
            patch("masterdata.views_advanced.iam_data_access.assign_user_tenant_role") as mock_assign,
            patch("masterdata.views_advanced.iam_data_access.revoke_user_tenant_role") as mock_revoke,
        ):
            mock_list.return_value = [
                {"role_id": 3, "code": "LOGISTICS", "name": "Logistics"}
            ]
            mock_assign.side_effect = [True, False]
            mock_revoke.side_effect = [True, False]

            denied = self.factory.get("/api/v1/masterdata/tenant/2/users/7/roles")
            force_authenticate(denied, user=self._principal([views.PERM_MASTERDATA_VIEW]))
            denied_response = views_advanced.tenant_user_roles(denied, 2, 7)
            self.assertEqual(denied_response.status_code, 403)
            mock_list.assert_not_called()

            get_request = self.factory.get("/api/v1/masterdata/tenant/2/users/7/roles")
            force_authenticate(
                get_request,
                user=self._principal([PERM_MASTERDATA_ADVANCED_VIEW]),
            )
            get_response = views_advanced.tenant_user_roles(get_request, 2, 7)
            self.assertEqual(get_response.status_code, 200)
            self.assertEqual(get_response.data["results"][0]["role_id"], 3)

            post_request = self.factory.post(
                "/api/v1/masterdata/tenant/2/users/7/roles",
                {"role_id": 3},
                format="json",
            )
            force_authenticate(
                post_request,
                user=self._principal([PERM_MASTERDATA_ADVANCED_EDIT], user_id="99"),
            )
            post_response = views_advanced.tenant_user_roles(post_request, 2, 7)
            self.assertEqual(post_response.status_code, 201)
            mock_assign.assert_called_with(2, 7, 3, 99)

            idem_request = self.factory.post(
                "/api/v1/masterdata/tenant/2/users/7/roles",
                {"role_id": 3},
                format="json",
            )
            force_authenticate(
                idem_request,
                user=self._principal([PERM_MASTERDATA_ADVANCED_EDIT], user_id="99"),
            )
            idem_response = views_advanced.tenant_user_roles(idem_request, 2, 7)
            self.assertEqual(idem_response.status_code, 200)

            delete_request = self.factory.delete("/api/v1/masterdata/tenant/2/users/7/roles?role_id=3")
            force_authenticate(
                delete_request,
                user=self._principal([PERM_MASTERDATA_ADVANCED_EDIT], user_id="99"),
            )
            delete_response = views_advanced.tenant_user_roles(delete_request, 2, 7)
            self.assertEqual(delete_response.status_code, 204)

            missing_delete = self.factory.delete("/api/v1/masterdata/tenant/2/users/7/roles?role_id=4")
            force_authenticate(
                missing_delete,
                user=self._principal([PERM_MASTERDATA_ADVANCED_EDIT], user_id="99"),
            )
            missing_response = views_advanced.tenant_user_roles(missing_delete, 2, 7)
            self.assertEqual(missing_response.status_code, 404)

    def test_assign_user_role_sql_uses_on_conflict_and_assigned_by(self):
        cursor = MagicMock()
        cursor.rowcount = 1
        cursor_context = MagicMock()
        cursor_context.__enter__.return_value = cursor
        cursor_context.__exit__.return_value = False

        connection = SimpleNamespace(cursor=lambda: cursor_context)
        with patch("masterdata.services.iam_data_access.connection", connection):
            created = iam_data_access.assign_user_role(7, 3, 99)

        self.assertTrue(created)
        sql, params = cursor.execute.call_args.args
        self.assertIn("ON CONFLICT (user_id, role_id) DO NOTHING", sql)
        self.assertEqual(params[:3], [7, 3, 99])

    def test_assign_tenant_user_sql_populates_assigned_by(self):
        cursor = MagicMock()
        cursor.rowcount = 1
        cursor_context = MagicMock()
        cursor_context.__enter__.return_value = cursor
        cursor_context.__exit__.return_value = False

        connection = SimpleNamespace(cursor=lambda: cursor_context)
        with patch("masterdata.services.iam_data_access.connection", connection):
            created = iam_data_access.assign_tenant_user(2, 7, "ADMIN", 99)

        self.assertTrue(created)
        sql, params = cursor.execute.call_args.args
        self.assertIn("ON CONFLICT (tenant_id, user_id) DO NOTHING", sql)
        self.assertIn("is_primary_tenant", sql)
        self.assertEqual(params[:5], [2, 7, False, "ADMIN", 99])
