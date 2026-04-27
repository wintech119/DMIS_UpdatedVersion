from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from api.rbac import (
    PERM_MASTERDATA_ADVANCED_CREATE,
    PERM_MASTERDATA_ADVANCED_EDIT,
    PERM_MASTERDATA_ADVANCED_VIEW,
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
        self.assertEqual(params[:4], [2, 7, "ADMIN", 99])
