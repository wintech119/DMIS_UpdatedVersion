from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from api.rbac import (
    PERM_MASTERDATA_ADVANCED_CREATE,
    PERM_MASTERDATA_ADVANCED_VIEW,
)
from masterdata import views
from masterdata.services import data_access as data_access_service
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

    def _principal(self, permissions):
        return SimpleNamespace(
            is_authenticated=True,
            user_id="tester",
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
