from types import SimpleNamespace
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient
from unittest.mock import patch

from api import checks as api_checks
from api import rbac
from api.authentication import Principal
from api.permissions import NeedsListPermission
from dmis_api import settings as dmis_settings


class HealthEndpointTests(TestCase):
    def test_health(self) -> None:
        client = APIClient()
        response = client.get("/api/v1/health/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})


class RuntimeAuthConfigurationValidationTests(SimpleTestCase):
    def test_shared_dev_defaults_auth_enabled(self) -> None:
        self.assertTrue(
            dmis_settings.default_auth_enabled_for_runtime_env(
                runtime_env="shared-dev",
                testing=False,
            )
        )

    def test_local_harness_defaults_auth_disabled(self) -> None:
        self.assertFalse(
            dmis_settings.default_auth_enabled_for_runtime_env(
                runtime_env="local-harness",
                testing=False,
            )
        )

    def test_tests_keep_auth_disabled_by_default(self) -> None:
        self.assertFalse(
            dmis_settings.default_auth_enabled_for_runtime_env(
                runtime_env="shared-dev",
                testing=True,
            )
        )

    def test_local_harness_mode_accepts_local_only_flags(self) -> None:
        dmis_settings.validate_runtime_auth_configuration(
            runtime_env="local-harness",
            debug=True,
            auth_enabled=False,
            dev_auth_enabled=True,
            local_auth_harness_enabled=True,
            testing=False,
        )

    def test_shared_dev_requires_auth_enabled(self) -> None:
        with self.assertRaisesMessage(
            RuntimeError,
            "DMIS_RUNTIME_ENV=shared-dev requires AUTH_ENABLED=1.",
        ):
            dmis_settings.validate_runtime_auth_configuration(
                runtime_env="shared-dev",
                debug=False,
                auth_enabled=False,
                dev_auth_enabled=False,
                local_auth_harness_enabled=False,
                testing=False,
            )

    def test_shared_dev_rejects_dev_auth(self) -> None:
        with self.assertRaisesMessage(
            RuntimeError,
            "DMIS_RUNTIME_ENV=shared-dev requires DEV_AUTH_ENABLED=0.",
        ):
            dmis_settings.validate_runtime_auth_configuration(
                runtime_env="shared-dev",
                debug=False,
                auth_enabled=True,
                dev_auth_enabled=True,
                local_auth_harness_enabled=False,
                testing=False,
            )

    def test_production_rejects_local_harness_flag(self) -> None:
        with self.assertRaisesMessage(
            RuntimeError,
            "DMIS_RUNTIME_ENV=production requires LOCAL_AUTH_HARNESS_ENABLED=0.",
        ):
            dmis_settings.validate_runtime_auth_configuration(
                runtime_env="production",
                debug=False,
                auth_enabled=True,
                dev_auth_enabled=False,
                local_auth_harness_enabled=True,
                testing=False,
            )

    def test_prod_like_local_rejects_debug_mode(self) -> None:
        with self.assertRaisesMessage(
            RuntimeError,
            "DMIS_RUNTIME_ENV=prod-like-local requires DJANGO_DEBUG=0.",
        ):
            dmis_settings.validate_runtime_auth_configuration(
                runtime_env="prod-like-local",
                debug=True,
                auth_enabled=True,
                dev_auth_enabled=False,
                local_auth_harness_enabled=False,
                testing=False,
            )


class RuntimeSecurityConfigurationValidationTests(SimpleTestCase):
    def _security_kwargs(self, runtime_env: str) -> dict[str, object]:
        secure_transport_runtime_envs = {"shared-dev", "staging", "production"}
        secure_hsts_seconds = {
            "local-harness": 0,
            "prod-like-local": 0,
            "shared-dev": 3600,
            "staging": 86400,
            "production": 31536000,
        }[runtime_env]
        secure_hsts_include_subdomains = runtime_env == "production"

        return {
            "runtime_env": runtime_env,
            "debug": runtime_env == "local-harness",
            "secret_key": "ci-secure-runtime-secret",
            "secret_key_explicit": runtime_env != "local-harness",
            "allowed_hosts": (
                ["localhost", "127.0.0.1"]
                if runtime_env in {"local-harness", "prod-like-local"}
                else [f"{runtime_env}.dmis.example.org"]
            ),
            "allowed_hosts_explicit": runtime_env != "local-harness",
            "secure_ssl_redirect": runtime_env in secure_transport_runtime_envs,
            "session_cookie_secure": runtime_env in secure_transport_runtime_envs,
            "csrf_cookie_secure": runtime_env in secure_transport_runtime_envs,
            "secure_hsts_seconds": secure_hsts_seconds,
            "secure_hsts_include_subdomains": secure_hsts_include_subdomains,
            "secure_hsts_preload": False,
            "x_frame_options": "DENY",
            "secure_referrer_policy": (
                "same-origin"
                if runtime_env in {"local-harness", "prod-like-local"}
                else "strict-origin-when-cross-origin"
            ),
            "csrf_trusted_origins": [],
            "secure_proxy_ssl_header": (
                ("HTTP_X_FORWARDED_PROTO", "https")
                if runtime_env in secure_transport_runtime_envs
                else None
            ),
            "use_x_forwarded_host": False,
            "testing": False,
        }

    def test_runtime_security_profiles_accept_expected_baselines(self) -> None:
        for runtime_env in (
            "local-harness",
            "prod-like-local",
            "shared-dev",
            "staging",
            "production",
        ):
            with self.subTest(runtime_env=runtime_env):
                dmis_settings.validate_runtime_security_configuration(
                    **self._security_kwargs(runtime_env)
                )

    def test_prod_like_local_requires_explicit_secret_key(self) -> None:
        kwargs = self._security_kwargs("prod-like-local")
        kwargs["secret_key"] = "debug-generated-secret"
        kwargs["secret_key_explicit"] = False

        with self.assertRaisesMessage(
            RuntimeError,
            "DMIS_RUNTIME_ENV=prod-like-local requires DJANGO_SECRET_KEY to be set explicitly.",
        ):
            dmis_settings.validate_runtime_security_configuration(**kwargs)

    def test_shared_dev_rejects_loopback_only_allowed_hosts(self) -> None:
        kwargs = self._security_kwargs("shared-dev")
        kwargs["allowed_hosts"] = ["localhost", "127.0.0.1"]

        with self.assertRaisesMessage(
            RuntimeError,
            "DMIS_RUNTIME_ENV=shared-dev requires DJANGO_ALLOWED_HOSTS to include at least one non-loopback host.",
        ):
            dmis_settings.validate_runtime_security_configuration(**kwargs)

    def test_shared_dev_rejects_url_shaped_allowed_hosts(self) -> None:
        kwargs = self._security_kwargs("shared-dev")
        kwargs["allowed_hosts"] = ["https://shared-dev.dmis.example.org"]

        with self.assertRaisesMessage(
            RuntimeError,
            "DMIS_RUNTIME_ENV=shared-dev requires DJANGO_ALLOWED_HOSTS entries without scheme or path.",
        ):
            dmis_settings.validate_runtime_security_configuration(**kwargs)

    def test_shared_dev_requires_https_redirect(self) -> None:
        kwargs = self._security_kwargs("shared-dev")
        kwargs["secure_ssl_redirect"] = False

        with self.assertRaisesMessage(
            RuntimeError,
            "DMIS_RUNTIME_ENV=shared-dev requires DJANGO_SECURE_SSL_REDIRECT=1.",
        ):
            dmis_settings.validate_runtime_security_configuration(**kwargs)

    def test_staging_requires_expected_hsts_seconds(self) -> None:
        kwargs = self._security_kwargs("staging")
        kwargs["secure_hsts_seconds"] = 3600

        with self.assertRaisesMessage(
            RuntimeError,
            "DMIS_RUNTIME_ENV=staging requires DJANGO_SECURE_HSTS_SECONDS=86400.",
        ):
            dmis_settings.validate_runtime_security_configuration(**kwargs)

    def test_production_rejects_non_https_csrf_trusted_origins(self) -> None:
        kwargs = self._security_kwargs("production")
        kwargs["csrf_trusted_origins"] = ["http://dmis.example.org"]

        with self.assertRaisesMessage(
            RuntimeError,
            "DMIS_RUNTIME_ENV=production requires DJANGO_CSRF_TRUSTED_ORIGINS to use https:// origins only.",
        ):
            dmis_settings.validate_runtime_security_configuration(**kwargs)

    def test_production_rejects_invalid_hsts_preload_opt_in(self) -> None:
        kwargs = self._security_kwargs("production")
        kwargs["secure_hsts_preload"] = True
        kwargs["secure_hsts_include_subdomains"] = False

        with self.assertRaisesMessage(
            RuntimeError,
            "DMIS_RUNTIME_ENV=production allows DJANGO_SECURE_HSTS_PRELOAD=1 only when DJANGO_SECURE_HSTS_SECONDS>=31536000 and DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS=1.",
        ):
            dmis_settings.validate_runtime_security_configuration(**kwargs)


class RuntimeSecurityCheckTests(SimpleTestCase):
    @override_settings(
        TESTING=False,
        DMIS_RUNTIME_ENV="shared-dev",
        DEBUG=False,
        SECRET_KEY="ci-secure-runtime-secret",
        DMIS_SECRET_KEY_EXPLICIT=True,
        ALLOWED_HOSTS=["shared-dev.dmis.example.org"],
        DMIS_ALLOWED_HOSTS_EXPLICIT=True,
        SECURE_SSL_REDIRECT=False,
        SESSION_COOKIE_SECURE=True,
        CSRF_COOKIE_SECURE=True,
        SECURE_HSTS_SECONDS=3600,
        SECURE_HSTS_INCLUDE_SUBDOMAINS=False,
        SECURE_HSTS_PRELOAD=False,
        X_FRAME_OPTIONS="DENY",
        SECURE_REFERRER_POLICY="strict-origin-when-cross-origin",
        CSRF_TRUSTED_ORIGINS=[],
        SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
        USE_X_FORWARDED_HOST=False,
    )
    def test_secure_runtime_check_reports_error_for_unsafe_non_local_settings(self) -> None:
        messages = api_checks.check_dmis_secure_runtime_posture(None)

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].id, "api.E003")
        self.assertIn("DJANGO_SECURE_SSL_REDIRECT=1", messages[0].msg)


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
        TEST_DEV_AUTH_ENABLED=True,
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    def test_whoami_rejects_local_harness_header_when_harness_disabled(self) -> None:
        response = self.client.get(
            "/api/v1/auth/whoami/",
            HTTP_X_DMIS_LOCAL_USER="local_odpem_logistics_manager_tst",
        )

        self.assertEqual(response.status_code, 401)
        self.assertIn("X-DMIS-Local-User", response.json()["detail"])

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        LOCAL_AUTH_HARNESS_ENABLED=True,
        LOCAL_AUTH_HARNESS_USERNAMES=["local_system_admin_tst"],
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="local_system_admin_tst",
        DEV_AUTH_ROLES=["SYSTEM_ADMINISTRATOR"],
        DEV_AUTH_PERMISSIONS=[],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    def test_whoami_rejects_legacy_dev_user_header(self) -> None:
        response = self.client.get(
            "/api/v1/auth/whoami/",
            HTTP_X_DEV_USER="local_system_admin_tst",
        )

        self.assertEqual(response.status_code, 401)
        self.assertIn("X-Dev-User", response.json()["detail"])

    @override_settings(
        AUTH_ENABLED=True,
        DEV_AUTH_ENABLED=False,
        LOCAL_AUTH_HARNESS_ENABLED=True,
        AUTH_ISSUER="https://issuer.example",
        AUTH_AUDIENCE="dmis-api",
        AUTH_JWKS_URL="https://issuer.example/.well-known/jwks.json",
        AUTH_USER_ID_CLAIM="sub",
        AUTH_ROLES_CLAIM="roles",
        AUTH_USE_DB_RBAC=False,
    )
    def test_local_auth_harness_route_is_hidden_when_auth_is_mandatory(self) -> None:
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

    def test_legacy_dev_users_route_is_not_exposed(self) -> None:
        response = self.client.get("/api/v1/auth/dev-users/")

        self.assertEqual(response.status_code, 404)


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
