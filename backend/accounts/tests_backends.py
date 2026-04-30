from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.contrib.auth import authenticate
from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings
from rest_framework.exceptions import AuthenticationFailed

from accounts.backends import KeycloakOidcBackend, LocalHarnessBackend
from api.authentication import _legacy_user_name
from accounts.models import DmisUser
from accounts.tests import DmisUserTestMixin
from api import authentication


class KeycloakOidcBackendTests(DmisUserTestMixin, TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.factory = RequestFactory()

    @override_settings(
        AUTH_ENABLED=True,
        DEV_AUTH_ENABLED=False,
        AUTH_JWKS_URL="https://issuer.example/.well-known/jwks.json",
        AUTH_USER_ID_CLAIM="sub",
        AUTH_USERNAME_CLAIM="preferred_username",
        AUTH_ROLES_CLAIM="roles",
        AUTH_USE_DB_RBAC=True,
    )
    @patch(
        "accounts.backends._verify_jwt_with_jwks",
        return_value={
            "sub": "880101",
            "preferred_username": "accounts_keycloak_tst",
            "email": "accounts-keycloak@example.test",
            "name": "Accounts Keycloak",
            "roles": ["SYSTEM_ADMINISTRATOR"],
        },
    )
    def test_valid_jwt_returns_dmis_user_and_populates_claim_fields(self, _mock_verify) -> None:
        request = self.factory.get("/api/v1/auth/whoami/")

        user = KeycloakOidcBackend().authenticate(request, jwt="valid-token")

        self.assertIsInstance(user, DmisUser)
        self.assertEqual(user.user_id, "880101")
        self.assertEqual(user.username, "accounts_keycloak_tst")
        self.assertEqual(user.roles, ["SYSTEM_ADMINISTRATOR"])
        loaded = DmisUser.objects.get(pk=880101)
        self.assertEqual(loaded.email, "accounts-keycloak@example.test")
        self.assertEqual(loaded.full_name, "Accounts Keycloak")
        self.assertEqual(loaded.user_name, _legacy_user_name("accounts_keycloak_tst"))
        self.assertEqual(loaded.password, "")

    @override_settings(
        AUTH_ENABLED=True,
        DEV_AUTH_ENABLED=False,
        AUTH_JWKS_URL="https://issuer.example/.well-known/jwks.json",
        AUTH_USER_ID_CLAIM="sub",
        AUTH_USERNAME_CLAIM="preferred_username",
        AUTH_ROLES_CLAIM="roles",
        AUTH_USE_DB_RBAC=True,
    )
    @patch(
        "accounts.backends._verify_jwt_with_jwks",
        return_value={
            "sub": "880102",
            "preferred_username": "accounts_existing_tst",
            "email": "accounts-existing-updated@example.test",
            "given_name": "Existing",
            "family_name": "Updated",
            "roles": [],
        },
    )
    def test_valid_jwt_updates_existing_claim_fields_without_resetting_password(self, _mock_verify) -> None:
        self._insert_user(
            user_id=880102,
            username="accounts_existing_tst",
            email="accounts-existing@example.test",
            full_name="Existing Before",
        )
        request = self.factory.get("/api/v1/auth/whoami/")

        user = KeycloakOidcBackend().authenticate(request, jwt="valid-token")

        self.assertEqual(user.user_id, "880102")
        loaded = DmisUser.objects.get(pk=880102)
        self.assertEqual(loaded.email, "accounts-existing-updated@example.test")
        self.assertEqual(loaded.full_name, "Existing Updated")
        self.assertTrue(loaded.check_password("phase1-pass"))

    @override_settings(
        AUTH_ENABLED=True,
        DEV_AUTH_ENABLED=False,
        AUTH_JWKS_URL="https://issuer.example/.well-known/jwks.json",
        AUTH_USER_ID_CLAIM="sub",
        AUTH_USERNAME_CLAIM="preferred_username",
        AUTH_ROLES_CLAIM="roles",
        AUTH_USE_DB_RBAC=True,
        AUTH_ALGORITHMS=["RS256"],
    )
    @patch(
        "api.authentication.jwt.get_unverified_header",
        side_effect=authentication.InvalidTokenError("bad token"),
    )
    @patch("api.authentication.logger.warning")
    def test_invalid_jwt_returns_none_and_emits_auth_warning(
        self,
        mock_warning,
        _mock_get_unverified_header,
    ) -> None:
        request = self.factory.get("/api/v1/auth/whoami/")

        user = KeycloakOidcBackend().authenticate(request, jwt="invalid-token")

        self.assertIsNone(user)
        mock_warning.assert_called_once()
        self.assertEqual(mock_warning.call_args.args[0], "auth.jwt_verification_failed")
        self.assertEqual(mock_warning.call_args.kwargs["extra"]["event"], "auth.jwt_verification_failed")

    @override_settings(
        AUTHENTICATION_BACKENDS=[
            "accounts.backends.KeycloakOidcBackend",
            "accounts.backends.LocalHarnessBackend",
        ],
        AUTH_ENABLED=True,
        DEV_AUTH_ENABLED=False,
        AUTH_JWKS_URL="https://issuer.example/.well-known/jwks.json",
        AUTH_USER_ID_CLAIM="sub",
        AUTH_USERNAME_CLAIM="preferred_username",
        AUTH_ROLES_CLAIM="roles",
        AUTH_USE_DB_RBAC=True,
    )
    @patch(
        "accounts.backends._verify_jwt_with_jwks",
        return_value={
            "sub": "880104",
            "preferred_username": "accounts_bearer_tst",
            "email": "accounts-bearer@example.test",
            "roles": [],
        },
    )
    def test_django_password_auth_ignores_request_bearer_header(self, mock_verify) -> None:
        self._insert_user(
            user_id=880105,
            username="accounts_password_tst",
            email="accounts-password@example.test",
        )
        request = self.factory.post(
            "/admin/login/",
            HTTP_AUTHORIZATION="Bearer valid-token",
            REMOTE_ADDR="10.0.0.16",
        )

        self.assertIsNone(
            authenticate(request, username="accounts_password_tst", password="wrong-pass")
        )
        user = authenticate(request, username="accounts_password_tst", password="phase1-pass")

        self.assertEqual(user.user_id, "880105")
        mock_verify.assert_not_called()


class LocalHarnessBackendTests(DmisUserTestMixin, TestCase):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        self.factory = RequestFactory()

    def tearDown(self) -> None:
        cache.clear()
        super().tearDown()

    def test_valid_username_password_returns_dmis_user(self) -> None:
        self._insert_user(
            user_id=880201,
            username="accounts_local_tst",
            email="accounts-local@example.test",
        )
        request = self.factory.post("/admin/login/", REMOTE_ADDR="10.0.0.10")

        user = LocalHarnessBackend().authenticate(
            request,
            username="accounts_local_tst",
            password="phase1-pass",
        )

        self.assertIsInstance(user, DmisUser)
        self.assertEqual(user.user_id, "880201")

    def test_invalid_username_password_returns_none(self) -> None:
        self._insert_user(
            user_id=880202,
            username="accounts_invalid_tst",
            email="accounts-invalid@example.test",
        )
        request = self.factory.post("/admin/login/", REMOTE_ADDR="10.0.0.11")

        user = LocalHarnessBackend().authenticate(
            request,
            username="accounts_invalid_tst",
            password="wrong-pass",
        )

        self.assertIsNone(user)

    @patch("accounts.backends._log_auth_warning")
    def test_django_authenticate_throttle_returns_none(self, mock_warning) -> None:
        self._insert_user(
            user_id=880203,
            username="accounts_throttled_tst",
            email="accounts-throttled@example.test",
        )
        request = self.factory.post("/admin/login/", REMOTE_ADDR="10.0.0.15")

        for _index in range(5):
            self.assertIsNone(
                authenticate(request, username="accounts_throttled_tst", password="wrong-pass")
            )

        self.assertIsNone(
            authenticate(request, username="accounts_throttled_tst", password="wrong-pass")
        )
        self.assertEqual(mock_warning.call_args.args[0], "auth.login_throttled")

    @patch("accounts.backends._log_auth_warning")
    def test_harness_header_lookup_is_covered_by_login_throttle(self, mock_warning) -> None:
        backend = LocalHarnessBackend()
        request = self.factory.get("/api/v1/auth/whoami/", REMOTE_ADDR="10.0.0.12")

        for _index in range(5):
            with self.assertRaisesMessage(AuthenticationFailed, "did not match"):
                backend.get_user_by_harness_header(request, "missing_harness_tst")

        with self.assertRaisesMessage(AuthenticationFailed, "Too many login attempts"):
            backend.get_user_by_harness_header(request, "missing_harness_tst")

        self.assertEqual(mock_warning.call_args.args[0], "auth.login_throttled")

    @patch("accounts.backends._log_auth_warning")
    def test_harness_header_missing_user_emits_user_not_found_warning(self, mock_warning) -> None:
        request = self.factory.get("/api/v1/auth/whoami/", REMOTE_ADDR="10.0.0.13")

        with self.assertRaisesMessage(AuthenticationFailed, "did not match"):
            LocalHarnessBackend().get_user_by_harness_header(request, "missing_user_tst")

        self.assertEqual(mock_warning.call_args.args[0], "auth.dev_override_user_not_found")

    @patch("accounts.backends.get_user_model")
    @patch("accounts.backends._log_auth_warning")
    def test_harness_header_lookup_failure_emits_lookup_failed_warning(
        self,
        mock_warning,
        mock_get_user_model,
    ) -> None:
        manager = MagicMock()
        manager.objects.filter.side_effect = authentication.DatabaseError("boom")
        mock_get_user_model.return_value = manager
        request = self.factory.get("/api/v1/auth/whoami/", REMOTE_ADDR="10.0.0.14")

        with self.assertRaisesMessage(AuthenticationFailed, "could not be resolved safely"):
            LocalHarnessBackend().get_user_by_harness_header(request, "lookup_failure_tst")

        self.assertEqual(mock_warning.call_args.args[0], "auth.dev_override_lookup_failed")
