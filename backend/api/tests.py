from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from unittest.mock import patch

from api import rbac
from api.authentication import Principal


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
