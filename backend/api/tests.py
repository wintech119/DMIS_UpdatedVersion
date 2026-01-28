from django.test import TestCase, override_settings
from rest_framework.test import APIClient


class HealthEndpointTests(TestCase):
    def test_health(self) -> None:
        client = APIClient()
        response = client.get("/api/v1/health/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})


class AuthWhoAmITests(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()

    @override_settings(AUTH_ENABLED=True, DEV_AUTH_ENABLED=False)
    def test_whoami_requires_auth(self) -> None:
        response = self.client.get("/api/v1/auth/whoami/")

        self.assertEqual(response.status_code, 401)

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="dev-user",
        DEV_AUTH_ROLES=["VIEWER"],
        AUTH_USE_DB_RBAC=False,
    )
    def test_whoami_forbidden_without_permission(self) -> None:
        response = self.client.get("/api/v1/auth/whoami/")

        self.assertEqual(response.status_code, 403)

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="dev-user",
        DEV_AUTH_ROLES=["LOGISTICS"],
        AUTH_USE_DB_RBAC=False,
    )
    def test_whoami_allows_with_permission(self) -> None:
        response = self.client.get("/api/v1/auth/whoami/")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["user_id"], "dev-user")
        self.assertIn("replenishment.needs_list.preview", body["permissions"])
