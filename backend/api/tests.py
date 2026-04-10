from types import SimpleNamespace
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient
from unittest.mock import patch

from api import rbac
from api.authentication import Principal
from api.permissions import NeedsListPermission


class HealthEndpointTests(TestCase):
    def test_health(self) -> None:
        client = APIClient()
        response = client.get("/api/v1/health/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})


class AuthWhoAmITests(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()

    @override_settings(
        AUTH_ENABLED=True,
        DEV_AUTH_ENABLED=False,
        AUTH_ISSUER="https://issuer.example",
        AUTH_AUDIENCE="dmis-api",
        AUTH_JWKS_URL="https://issuer.example/.well-known/jwks.json",
        AUTH_USER_ID_CLAIM="sub",
        AUTH_ROLES_CLAIM="roles",
        AUTH_USE_DB_RBAC=False,
    )
    def test_whoami_requires_auth(self) -> None:
        response = self.client.get("/api/v1/auth/whoami/")

        self.assertEqual(response.status_code, 401)

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="dev-user",
        DEV_AUTH_ROLES=["VIEWER"],
        DEV_AUTH_PERMISSIONS=[],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    def test_whoami_allows_without_needs_list_permission(self) -> None:
        response = self.client.get("/api/v1/auth/whoami/")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["user_id"], "dev-user")
        self.assertEqual(body["roles"], ["VIEWER"])
        self.assertEqual(body["permissions"], [])

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="dev-user",
        DEV_AUTH_ROLES=["LOGISTICS"],
        DEV_AUTH_PERMISSIONS=[],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    def test_whoami_allows_with_permission(self) -> None:
        response = self.client.get("/api/v1/auth/whoami/")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["user_id"], "dev-user")
        self.assertIn("replenishment.needs_list.preview", body["permissions"])

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="dev-user",
        DEV_AUTH_ROLES=["LOGISTICS"],
        DEV_AUTH_PERMISSIONS=[],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch(
        "api.views.operations_policy.get_relief_request_capabilities",
        return_value={
            "can_create_relief_request": True,
            "can_create_relief_request_on_behalf": False,
            "relief_request_submission_mode": "self",
            "default_requesting_tenant_id": 20,
        },
    )
    def test_whoami_includes_operations_capabilities(self, _mock_capabilities) -> None:
        response = self.client.get("/api/v1/auth/whoami/")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            body["operations_capabilities"],
            {
                "can_create_relief_request": True,
                "can_create_relief_request_on_behalf": False,
                "relief_request_submission_mode": "self",
                "default_requesting_tenant_id": 20,
            },
        )

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        LOCAL_AUTH_HARNESS_ENABLED=True,
        LOCAL_AUTH_HARNESS_USERNAMES=["relief_ffp_requester_tst"],
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="dev-user",
        DEV_AUTH_ROLES=[],
        DEV_AUTH_PERMISSIONS=[],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch(
        "api.authentication._resolve_dev_override_principal",
        return_value=Principal(
            user_id="13",
            username="relief_ffp_requester_tst",
            roles=["AGENCY_DISTRIBUTOR"],
            permissions=["operations.request.create.self"],
        ),
    )
    def test_whoami_dev_override_includes_db_roles_and_permissions(
        self,
        _mock_override_principal,
    ) -> None:
        response = self.client.get(
            "/api/v1/auth/whoami/",
            HTTP_X_DMIS_LOCAL_USER="relief_ffp_requester_tst",
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["user_id"], "13")
        self.assertEqual(body["username"], "relief_ffp_requester_tst")
        self.assertIn("AGENCY_DISTRIBUTOR", body["roles"])
        self.assertIn("operations.request.create.self", body["permissions"])

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    def test_local_auth_harness_route_is_hidden_when_not_explicitly_enabled(self) -> None:
        response = self.client.get("/api/v1/auth/local-harness/")

        self.assertEqual(response.status_code, 404)

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        LOCAL_AUTH_HARNESS_ENABLED=True,
        LOCAL_AUTH_HARNESS_USERNAMES=[
            "local_system_admin_tst",
            "local_odpem_deputy_director_tst",
            "local_odpem_logistics_manager_tst",
            "local_odpem_logistics_officer_tst",
            "relief_jrc_requester_tst",
        ],
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="local_system_admin_tst",
        DEV_AUTH_ROLES=["SYSTEM_ADMINISTRATOR"],
        DEV_AUTH_PERMISSIONS=[],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch(
        "api.views._load_local_auth_harness_users",
        return_value=(
            [
                {
                    "user_id": "27",
                    "username": "local_system_admin_tst",
                    "email": "system.admin+local@dmis.example.org",
                    "roles": ["SYSTEM_ADMINISTRATOR"],
                    "permissions": ["masterdata.view"],
                    "memberships": [
                        {
                            "tenant_id": 1,
                            "tenant_code": "ODPEM-NEOC",
                            "tenant_name": "ODPEM NEOC",
                            "tenant_type": "NEOC",
                            "is_primary": True,
                            "access_level": "FULL",
                        }
                    ],
                }
            ],
            [
                "local_odpem_deputy_director_tst",
                "local_odpem_logistics_manager_tst",
                "local_odpem_logistics_officer_tst",
                "relief_jrc_requester_tst",
            ],
        ),
    )
    def test_local_auth_harness_route_returns_curated_users_and_missing_entries(
        self,
        _mock_load_users,
    ) -> None:
        response = self.client.get("/api/v1/auth/local-harness/")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["enabled"])
        self.assertEqual(body["mode"], "local_dev_only")
        self.assertEqual(body["default_user"], "local_system_admin_tst")
        self.assertEqual(body["header_name"], "X-DMIS-Local-User")
        self.assertEqual(
            body["missing_usernames"],
            [
                "local_odpem_deputy_director_tst",
                "local_odpem_logistics_manager_tst",
                "local_odpem_logistics_officer_tst",
                "relief_jrc_requester_tst",
            ],
        )
        self.assertEqual(len(body["users"]), 1)
        self.assertEqual(body["users"][0]["username"], "local_system_admin_tst")


class RbacResolutionTests(TestCase):
    @patch(
        "api.rbac._fetch_permissions_for_role_codes",
        return_value={"replenishment.needs_list.approve"},
    )
    @patch("api.rbac._resolve_user_id", return_value=None)
    @patch("api.rbac._db_rbac_enabled", return_value=True)
    def test_db_rbac_resolves_permissions_from_claim_roles(
        self,
        _mock_db_enabled,
        _mock_user_id,
        mock_permissions_for_roles,
    ) -> None:
        request = type("Request", (), {})()
        principal = Principal(
            user_id=None,
            username="keycloak-user",
            roles=["ODPEM_DIR_PEOD"],
            permissions=[],
        )

        roles, permissions = rbac.resolve_roles_and_permissions(request, principal)

        self.assertIn("ODPEM_DIR_PEOD", roles)
        self.assertIn("replenishment.needs_list.approve", permissions)
        self.assertEqual(mock_permissions_for_roles.call_count, 1)

    @patch(
        "api.rbac._fetch_permissions_for_role_codes",
        return_value={
            "replenishment.needs_list.preview",
            "replenishment.needs_list.create_draft",
            "replenishment.needs_list.edit_lines",
        },
    )
    @patch("api.rbac._resolve_user_id", return_value=None)
    @patch("api.rbac._db_rbac_enabled", return_value=True)
    def test_db_rbac_applies_submit_compat_override_for_logistics_officer(
        self,
        _mock_db_enabled,
        _mock_user_id,
        _mock_permissions_for_roles,
    ) -> None:
        request = type("Request", (), {})()
        principal = Principal(
            user_id=None,
            username="logistics-officer",
            roles=["TST_LOGISTICS_OFFICER"],
            permissions=[],
        )

        _roles, permissions = rbac.resolve_roles_and_permissions(request, principal)
        self.assertIn("replenishment.needs_list.submit", permissions)

    @patch(
        "api.rbac._fetch_permissions_for_role_codes",
        return_value=set(),
    )
    @patch("api.rbac._resolve_user_id", return_value=None)
    @patch("api.rbac._db_rbac_enabled", return_value=True)
    def test_db_rbac_applies_masterdata_view_compat_for_tst_logistics_manager(
        self,
        _mock_db_enabled,
        _mock_user_id,
        _mock_permissions_for_roles,
    ) -> None:
        request = type("Request", (), {})()
        principal = Principal(
            user_id=None,
            username="kemar_tst",
            roles=["TST_LOGISTICS_MANAGER"],
            permissions=[],
        )

        _roles, permissions = rbac.resolve_roles_and_permissions(request, principal)
        self.assertIn("masterdata.view", permissions)
        self.assertNotIn("operations.eligibility.review", permissions)

    @patch(
        "api.rbac._fetch_permissions_for_role_codes",
        return_value={"replenishment.needs_list.approve"},
    )
    @patch("api.rbac._resolve_user_id", return_value=None)
    @patch("api.rbac._db_rbac_enabled", return_value=True)
    def test_db_rbac_does_not_grant_eligibility_permissions_from_needs_list_approval(
        self,
        _mock_db_enabled,
        _mock_user_id,
        _mock_permissions_for_roles,
    ) -> None:
        request = type("Request", (), {})()
        principal = Principal(
            user_id=None,
            username="logistics-manager",
            roles=["LOGISTICS_MANAGER"],
            permissions=[],
        )

        _roles, permissions = rbac.resolve_roles_and_permissions(request, principal)

        self.assertIn("replenishment.needs_list.approve", permissions)
        self.assertNotIn("operations.eligibility.review", permissions)
        self.assertNotIn("operations.eligibility.approve", permissions)
        self.assertNotIn("operations.eligibility.reject", permissions)

    @patch(
        "api.rbac._fetch_permissions_for_role_codes",
        return_value=set(),
    )
    @patch("api.rbac._resolve_user_id", return_value=None)
    @patch("api.rbac._db_rbac_enabled", return_value=True)
    def test_db_rbac_applies_masterdata_view_compat_for_tst_readonly(
        self,
        _mock_db_enabled,
        _mock_user_id,
        _mock_permissions_for_roles,
    ) -> None:
        request = type("Request", (), {})()
        principal = Principal(
            user_id=None,
            username="sarah_tst",
            roles=["TST_READONLY"],
            permissions=[],
        )

        _roles, permissions = rbac.resolve_roles_and_permissions(request, principal)
        self.assertIn("masterdata.view", permissions)

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEBUG=True,
        AUTH_USE_DB_RBAC=True,
    )
    @patch(
        "api.rbac._fetch_permissions_for_role_codes",
        return_value=set(),
    )
    @patch("api.rbac._resolve_user_id", return_value=None)
    @patch("api.rbac._db_rbac_enabled", return_value=True)
    def test_dev_auth_applies_executive_bundle_for_odpem_ddg(
        self,
        _mock_db_enabled,
        _mock_user_id,
        _mock_permissions_for_roles,
    ) -> None:
        request = type("Request", (), {})()
        principal = Principal(
            user_id="15",
            username="local_odpem_deputy_director_tst",
            roles=["ODPEM_DDG"],
            permissions=[],
        )

        _roles, permissions = rbac.resolve_roles_and_permissions(request, principal)

        self.assertIn("replenishment.needs_list.approve", permissions)
        self.assertIn("masterdata.view", permissions)
        self.assertIn("operations.eligibility.review", permissions)

    def test_governed_catalog_access_is_limited_to_global_governance_roles(self) -> None:
        self.assertFalse(rbac.has_governed_catalog_access(["AGENCY_DISTRIBUTOR"]))
        self.assertFalse(rbac.has_governed_catalog_access(["ODPEM_LOGISTICS_MANAGER"]))
        self.assertTrue(rbac.has_governed_catalog_access(["SYSTEM_ADMINISTRATOR"]))
        self.assertTrue(rbac.has_governed_catalog_access(["ODPEM_DG"]))
        self.assertTrue(rbac.has_governed_catalog_access(["TST_READONLY"]))

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEBUG=True,
        AUTH_USE_DB_RBAC=True,
    )
    @patch(
        "api.rbac._fetch_permissions_for_role_codes",
        return_value={"replenishment.needs_list.preview", "db_only.sentinel"},
    )
    @patch("api.rbac._resolve_user_id", return_value=None)
    @patch("api.rbac._db_rbac_enabled", return_value=True)
    def test_dev_auth_preserves_role_bundle_when_db_rbac_returns_partial_permissions(
        self,
        _mock_db_enabled,
        _mock_user_id,
        _mock_permissions_for_roles,
    ) -> None:
        request = type("Request", (), {})()
        principal = Principal(
            user_id="dev-user",
            username="sysadmin.odpem+tst@odpem.gov.jm",
            roles=["SYSTEM_ADMINISTRATOR"],
            permissions=[],
        )

        _roles, permissions = rbac.resolve_roles_and_permissions(request, principal)

        self.assertIn("replenishment.needs_list.preview", permissions)
        self.assertIn("db_only.sentinel", permissions)
        self.assertIn("masterdata.create", permissions)
        self.assertIn("masterdata.edit", permissions)


class NeedsListPermissionTests(SimpleTestCase):
    def _build_request(self, method: str, *, authenticated: bool = True) -> SimpleNamespace:
        return SimpleNamespace(
            method=method,
            user=SimpleNamespace(is_authenticated=authenticated),
        )

    @patch(
        "api.permissions.resolve_roles_and_permissions",
        return_value=([], {"tenant.approval_policy.view"}),
    )
    def test_supports_method_specific_permission_mapping(self, _mock_permissions) -> None:
        permission = NeedsListPermission()
        view = SimpleNamespace(
            required_permission={
                "GET": "tenant.approval_policy.view",
                "PUT": "tenant.approval_policy.manage",
            }
        )

        self.assertTrue(permission.has_permission(self._build_request("GET"), view))
        self.assertFalse(permission.has_permission(self._build_request("PUT"), view))
