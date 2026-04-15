import sys
import types
from datetime import datetime, timedelta
from decimal import Decimal
from io import StringIO
from importlib import import_module
from types import SimpleNamespace
from django.apps import apps as django_apps
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import path
from django.db import DatabaseError
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.response import Response
from rest_framework.test import APIClient
from unittest.mock import patch

from api import authentication, checks as api_checks
from api import rbac
from api.authentication import Principal
from api.models import AsyncJob, AsyncJobArtifact
from api.permissions import NeedsListPermission
from api.tenancy import TenantContext, TenantMembership
from dmis_api import settings as dmis_settings
from replenishment.models import NeedsList, NeedsListAudit
from replenishment import views as replenishment_views


@api_view(["GET"])
def observability_boom(_request):
    raise RuntimeError("boom")


urlpatterns = [
    path("boom/", observability_boom, name="observability_boom"),
]


class _CursorResultContext:
    def __init__(self, row):
        self._row = row

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, *_args, **_kwargs) -> None:
        return None

    def fetchone(self):
        return self._row


class HealthEndpointTests(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()

    def _assert_correlated_response(self, response, expected_request_id: str | None = None) -> str:
        body = response.json()
        self.assertIn("request_id", body)
        self.assertIn("X-Request-ID", response)
        self.assertEqual(response["X-Request-ID"], body["request_id"])
        if expected_request_id is not None:
            self.assertEqual(body["request_id"], expected_request_id)
        else:
            self.assertRegex(body["request_id"], r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
        return str(body["request_id"])

    def test_health_alias_returns_liveness_payload(self) -> None:
        response = self.client.get("/api/v1/health/")
        body = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["status"], "live")
        self.assertEqual(body["runtime_env"], "test")
        self._assert_correlated_response(response)

    def test_live_endpoint_returns_liveness_payload(self) -> None:
        response = self.client.get("/api/v1/health/live/")
        body = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["status"], "live")
        self.assertEqual(body["runtime_env"], "test")
        self._assert_correlated_response(response)

    def test_live_endpoint_reuses_valid_request_id_header(self) -> None:
        response = self.client.get("/api/v1/health/live/", HTTP_X_REQUEST_ID="edge-health-123")

        self.assertEqual(response.status_code, 200)
        self._assert_correlated_response(response, "edge-health-123")

    def test_live_endpoint_replaces_invalid_request_id_header(self) -> None:
        response = self.client.get("/api/v1/health/live/", HTTP_X_REQUEST_ID="bad header/value")

        request_id = self._assert_correlated_response(response)
        self.assertNotEqual(request_id, "bad header/value")

    @override_settings(
        DMIS_RUNTIME_ENV="shared-dev",
        DMIS_REDIS_REQUIRED=True,
        DMIS_WORKER_REQUIRED=True,
    )
    @patch("api.views._export_audit_schema_readiness_check", return_value=("ok", None))
    @patch("api.views._queue_readiness_check", return_value=("ok", None))
    @patch("api.views._redis_readiness_check", return_value=("ok", None))
    @patch("api.views._database_readiness_check", return_value=("ok", None))
    def test_readiness_returns_ready_when_required_dependencies_are_available(
        self,
        _mock_database_check,
        _mock_redis_check,
        _mock_queue_check,
        _mock_export_audit_schema_check,
    ) -> None:
        response = self.client.get("/api/v1/health/ready/")
        body = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["status"], "ready")
        self.assertEqual(
            body["checks"],
            {
                "database": {"required": True, "status": "ok"},
                "redis": {"required": True, "status": "ok"},
                "queue": {"required": True, "status": "ok"},
                "export_audit_schema": {"required": True, "status": "ok"},
            },
        )
        self._assert_correlated_response(response)

    @override_settings(
        DMIS_RUNTIME_ENV="local-harness",
        DMIS_REDIS_REQUIRED=False,
        DMIS_WORKER_REQUIRED=False,
        DMIS_ASYNC_EAGER=True,
    )
    @patch(
        "api.views._export_audit_schema_readiness_check",
        return_value=("skipped", "Queued export audit schema is optional while async jobs run eagerly."),
    )
    @patch(
        "api.views._queue_readiness_check",
        return_value=("skipped", "Async jobs run inline in local-harness when eager execution is enabled."),
    )
    @patch(
        "api.views._redis_readiness_check",
        return_value=("skipped", "Redis is optional in local-harness when REDIS_URL is not set."),
    )
    @patch("api.views._database_readiness_check", return_value=("ok", None))
    def test_readiness_reports_local_harness_redis_skip(
        self,
        _mock_database_check,
        _mock_redis_check,
        _mock_queue_check,
        _mock_export_audit_schema_check,
    ) -> None:
        response = self.client.get("/api/v1/health/ready/")
        body = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["status"], "ready")
        self.assertEqual(body["runtime_env"], "local-harness")
        self.assertEqual(
            body["checks"],
            {
                "database": {"required": True, "status": "ok"},
                "redis": {
                    "required": False,
                    "status": "skipped",
                    "reason": "Redis is optional in local-harness when REDIS_URL is not set.",
                },
                "queue": {
                    "required": False,
                    "status": "skipped",
                    "reason": "Async jobs run inline in local-harness when eager execution is enabled.",
                },
                "export_audit_schema": {
                    "required": False,
                    "status": "skipped",
                    "reason": "Queued export audit schema is optional while async jobs run eagerly.",
                },
            },
        )
        self._assert_correlated_response(response)

    @override_settings(
        DMIS_RUNTIME_ENV="shared-dev",
        DMIS_REDIS_REQUIRED=True,
        DMIS_WORKER_REQUIRED=True,
    )
    @patch("api.views.readiness_logger.warning")
    @patch("api.views._export_audit_schema_readiness_check", return_value=("ok", None))
    @patch("api.views._queue_readiness_check", return_value=("ok", None))
    @patch("api.views._redis_readiness_check", return_value=("ok", None))
    @patch(
        "api.views._database_readiness_check",
        return_value=("failed", "Database connectivity check failed (DatabaseError)."),
    )
    def test_readiness_failure_logs_request_correlation(
        self,
        _mock_database_check,
        _mock_redis_check,
        _mock_queue_check,
        _mock_export_audit_schema_check,
        mock_warning,
    ) -> None:
        response = self.client.get(
            "/api/v1/health/ready/",
            HTTP_X_REQUEST_ID="edge-ready-503",
        )

        self.assertEqual(response.status_code, 503)
        self._assert_correlated_response(response, "edge-ready-503")
        mock_warning.assert_called_once()
        self.assertEqual(mock_warning.call_args.args[0], "readiness.not_ready")
        self.assertEqual(mock_warning.call_args.kwargs["extra"]["request_id"], "edge-ready-503")
        self.assertEqual(mock_warning.call_args.kwargs["extra"]["dependency"], "database")

    @override_settings(
        DMIS_RUNTIME_ENV="shared-dev",
        DMIS_REDIS_REQUIRED=True,
        DMIS_WORKER_REQUIRED=True,
    )
    @patch("api.views._export_audit_schema_readiness_check", return_value=("ok", None))
    @patch("api.views._queue_readiness_check", return_value=("ok", None))
    @patch("api.views._redis_readiness_check", return_value=("ok", None))
    @patch(
        "api.views._database_readiness_check",
        return_value=("failed", "Database connectivity check failed (DatabaseError)."),
    )
    def test_readiness_fails_when_database_is_unavailable(
        self,
        _mock_database_check,
        _mock_redis_check,
        _mock_queue_check,
        _mock_export_audit_schema_check,
    ) -> None:
        response = self.client.get("/api/v1/health/ready/")
        body = response.json()

        self.assertEqual(response.status_code, 503)
        self.assertEqual(body["status"], "not_ready")
        self.assertEqual(body["checks"]["database"]["status"], "failed")
        self.assertEqual(body["checks"]["redis"]["status"], "ok")
        self.assertEqual(body["checks"]["queue"]["status"], "ok")
        self.assertEqual(body["checks"]["export_audit_schema"]["status"], "ok")
        self._assert_correlated_response(response)

    @override_settings(
        DMIS_RUNTIME_ENV="shared-dev",
        DMIS_REDIS_REQUIRED=True,
        DMIS_WORKER_REQUIRED=True,
    )
    @patch("api.views._export_audit_schema_readiness_check", return_value=("ok", None))
    @patch("api.views._queue_readiness_check", return_value=("ok", None))
    @patch(
        "api.views._redis_readiness_check",
        return_value=("failed", "Redis is required for this runtime but REDIS_URL is not configured."),
    )
    @patch("api.views._database_readiness_check", return_value=("ok", None))
    def test_readiness_fails_when_required_redis_is_missing(
        self,
        _mock_database_check,
        _mock_redis_check,
        _mock_queue_check,
        _mock_export_audit_schema_check,
    ) -> None:
        response = self.client.get("/api/v1/health/ready/")
        body = response.json()

        self.assertEqual(response.status_code, 503)
        self.assertEqual(body["status"], "not_ready")
        self.assertEqual(body["checks"]["redis"]["status"], "failed")
        self.assertIn("REDIS_URL", body["checks"]["redis"]["reason"])
        self.assertEqual(body["checks"]["queue"]["status"], "ok")
        self.assertEqual(body["checks"]["export_audit_schema"]["status"], "ok")
        self._assert_correlated_response(response)

    @override_settings(
        DMIS_RUNTIME_ENV="shared-dev",
        DMIS_REDIS_REQUIRED=True,
        DMIS_WORKER_REQUIRED=True,
    )
    @patch("api.views._export_audit_schema_readiness_check", return_value=("ok", None))
    @patch("api.views._queue_readiness_check", return_value=("ok", None))
    @patch(
        "api.views._redis_readiness_check",
        return_value=("failed", "Redis connectivity check failed (ConnectionError)."),
    )
    @patch("api.views._database_readiness_check", return_value=("ok", None))
    def test_readiness_fails_when_required_redis_is_unreachable(
        self,
        _mock_database_check,
        _mock_redis_check,
        _mock_queue_check,
        _mock_export_audit_schema_check,
    ) -> None:
        response = self.client.get("/api/v1/health/ready/")
        body = response.json()

        self.assertEqual(response.status_code, 503)
        self.assertEqual(body["status"], "not_ready")
        self.assertEqual(body["checks"]["redis"]["status"], "failed")
        self.assertEqual(body["checks"]["queue"]["status"], "ok")
        self.assertEqual(body["checks"]["export_audit_schema"]["status"], "ok")
        self._assert_correlated_response(response)

    @override_settings(
        DMIS_RUNTIME_ENV="shared-dev",
        DMIS_REDIS_REQUIRED=True,
        DMIS_WORKER_REQUIRED=True,
    )
    @patch("api.views._export_audit_schema_readiness_check", return_value=("ok", None))
    @patch(
        "api.views._queue_readiness_check",
        return_value=("failed", "No active worker heartbeat detected."),
    )
    @patch("api.views._redis_readiness_check", return_value=("ok", None))
    @patch("api.views._database_readiness_check", return_value=("ok", None))
    def test_readiness_fails_when_worker_heartbeat_is_missing(
        self,
        _mock_database_check,
        _mock_redis_check,
        _mock_queue_check,
        _mock_export_audit_schema_check,
    ) -> None:
        response = self.client.get("/api/v1/health/ready/")
        body = response.json()

        self.assertEqual(response.status_code, 503)
        self.assertEqual(body["status"], "not_ready")
        self.assertEqual(body["checks"]["queue"]["status"], "failed")
        self.assertEqual(body["checks"]["queue"]["reason"], "No active worker heartbeat detected.")
        self.assertEqual(body["checks"]["export_audit_schema"]["status"], "ok")
        self._assert_correlated_response(response)

    @override_settings(
        DMIS_RUNTIME_ENV="shared-dev",
        DMIS_REDIS_REQUIRED=True,
        DMIS_WORKER_REQUIRED=True,
    )
    @patch(
        "api.views._export_audit_schema_readiness_check",
        return_value=(
            "failed",
            "Queued export durability requires needs_list_audit.request_id to exist; apply the replenishment export audit schema update.",
        ),
    )
    @patch("api.views._queue_readiness_check", return_value=("ok", None))
    @patch("api.views._redis_readiness_check", return_value=("ok", None))
    @patch("api.views._database_readiness_check", return_value=("ok", None))
    def test_readiness_fails_when_export_audit_schema_is_missing(
        self,
        _mock_database_check,
        _mock_redis_check,
        _mock_queue_check,
        _mock_export_audit_schema_check,
    ) -> None:
        response = self.client.get("/api/v1/health/ready/")
        body = response.json()

        self.assertEqual(response.status_code, 503)
        self.assertEqual(body["checks"]["export_audit_schema"]["status"], "failed")
        self.assertIn("request_id", body["checks"]["export_audit_schema"]["reason"])
        self._assert_correlated_response(response)


class RuntimeRedisConfigurationValidationTests(SimpleTestCase):
    def test_local_harness_allows_locmem_without_redis(self) -> None:
        dmis_settings.validate_runtime_redis_configuration(
            runtime_env="local-harness",
            redis_url="",
            cache_backend="django.core.cache.backends.locmem.LocMemCache",
            testing=False,
        )

    @patch("dmis_api.settings.import_module", return_value=object())
    def test_local_harness_accepts_configured_redis(self, _mock_import_module) -> None:
        dmis_settings.validate_runtime_redis_configuration(
            runtime_env="local-harness",
            redis_url="redis://localhost:6379/1",
            cache_backend="django_redis.cache.RedisCache",
            testing=False,
        )

    def test_non_local_runtimes_require_redis_url(self) -> None:
        for runtime_env in ("prod-like-local", "shared-dev", "staging", "production"):
            with self.subTest(runtime_env=runtime_env):
                with self.assertRaisesMessage(
                    RuntimeError,
                    f"DMIS_RUNTIME_ENV={runtime_env} requires REDIS_URL because Redis is a mandatory runtime dependency.",
                ):
                    dmis_settings.validate_runtime_redis_configuration(
                        runtime_env=runtime_env,
                        redis_url="",
                        cache_backend="django.core.cache.backends.locmem.LocMemCache",
                        testing=False,
                    )

    def test_prod_like_local_rejects_invalid_redis_url(self) -> None:
        with self.assertRaisesMessage(
            RuntimeError,
            "DMIS_RUNTIME_ENV=prod-like-local requires REDIS_URL to use one of the supported schemes",
        ):
            dmis_settings.validate_runtime_redis_configuration(
                runtime_env="prod-like-local",
                redis_url="http://localhost:6379/1",
                cache_backend="django_redis.cache.RedisCache",
                testing=False,
            )

    def test_shared_dev_requires_redis_backed_cache_backend(self) -> None:
        with self.assertRaisesMessage(
            RuntimeError,
            "DMIS_RUNTIME_ENV=shared-dev with REDIS_URL configured requires the default cache backend to be django_redis.cache.RedisCache.",
        ):
            dmis_settings.validate_runtime_redis_configuration(
                runtime_env="shared-dev",
                redis_url="redis://shared-dev-redis:6379/1",
                cache_backend="django.core.cache.backends.locmem.LocMemCache",
                testing=False,
            )

    @patch(
        "dmis_api.settings.import_module",
        side_effect=ModuleNotFoundError("No module named 'django_redis'"),
    )
    def test_shared_dev_requires_django_redis_dependency(self, _mock_import_module) -> None:
        with self.assertRaisesMessage(
            RuntimeError,
            "DMIS_RUNTIME_ENV=shared-dev with REDIS_URL configured requires the django-redis package to be installed.",
        ):
            dmis_settings.validate_runtime_redis_configuration(
                runtime_env="shared-dev",
                redis_url="redis://shared-dev-redis:6379/1",
                cache_backend="django_redis.cache.RedisCache",
                testing=False,
            )


class RuntimeAsyncConfigurationValidationTests(SimpleTestCase):
    def test_local_harness_defaults_async_eager(self) -> None:
        self.assertTrue(
            dmis_settings.default_async_eager_for_runtime_env(
                runtime_env="local-harness",
                testing=False,
            )
        )

    def test_non_local_runtime_rejects_async_eager_mode(self) -> None:
        with self.assertRaisesMessage(
            RuntimeError,
            "DMIS_RUNTIME_ENV=shared-dev requires DMIS_ASYNC_EAGER=0 so a real worker plane is active.",
        ):
            dmis_settings.validate_runtime_async_configuration(
                runtime_env="shared-dev",
                testing=False,
                redis_url="redis://shared-dev-redis:6379/1",
                async_eager=True,
                worker_required=True,
                broker_url="redis://shared-dev-redis:6379/1",
                result_backend="redis://shared-dev-redis:6379/1",
            )

    def test_non_local_runtime_requires_redis_backed_worker_plane(self) -> None:
        with self.assertRaisesMessage(
            RuntimeError,
            "DMIS_RUNTIME_ENV=staging requires REDIS_URL because Redis-backed async queueing is mandatory.",
        ):
            dmis_settings.validate_runtime_async_configuration(
                runtime_env="staging",
                testing=False,
                redis_url="",
                async_eager=False,
                worker_required=True,
                broker_url="",
                result_backend="",
            )

    @patch("dmis_api.settings.import_module", return_value=object())
    def test_local_harness_accepts_eager_async_mode_without_queue_dependency(
        self,
        _mock_import_module,
    ) -> None:
        dmis_settings.validate_runtime_async_configuration(
            runtime_env="local-harness",
            testing=False,
            redis_url="",
            async_eager=True,
            worker_required=False,
            broker_url="",
            result_backend="",
        )

    def test_worker_loss_recovery_settings_are_hardened(self) -> None:
        self.assertEqual(
            dmis_settings.CELERY_TASK_ACKS_LATE,
            not dmis_settings.DMIS_ASYNC_EAGER,
        )
        self.assertEqual(
            dmis_settings.CELERY_TASK_REJECT_ON_WORKER_LOST,
            not dmis_settings.DMIS_ASYNC_EAGER,
        )
        self.assertEqual(dmis_settings.CELERY_WORKER_PREFETCH_MULTIPLIER, 1)
        self.assertGreaterEqual(
            dmis_settings.DMIS_ASYNC_VISIBILITY_TIMEOUT_SECONDS,
            dmis_settings.CELERY_TASK_TIME_LIMIT,
        )
        self.assertEqual(
            dmis_settings.CELERY_BROKER_TRANSPORT_OPTIONS["visibility_timeout"],
            dmis_settings.DMIS_ASYNC_VISIBILITY_TIMEOUT_SECONDS,
        )


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

    def test_detect_testing_recognizes_pytest_invocation(self) -> None:
        self.assertTrue(dmis_settings._detect_testing(["pytest", "backend/api/tests.py"]))

    def test_detect_testing_recognizes_running_tests_environment_flag(self) -> None:
        self.assertTrue(dmis_settings._detect_testing(["runserver"], {"RUNNING_TESTS": "1"}))

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


class RuntimeDependencyCheckTests(SimpleTestCase):
    @override_settings(
        TESTING=False,
        DMIS_RUNTIME_ENV="shared-dev",
        DMIS_REDIS_URL="",
        DMIS_DEFAULT_CACHE_BACKEND="django.core.cache.backends.locmem.LocMemCache",
        DMIS_ASYNC_EAGER=False,
        DMIS_WORKER_REQUIRED=True,
        CELERY_BROKER_URL="",
        CELERY_RESULT_BACKEND="",
    )
    def test_runtime_dependency_check_reports_errors_when_redis_and_worker_plane_are_missing(self) -> None:
        messages = api_checks.check_dmis_runtime_dependency_posture(None)

        self.assertEqual([message.id for message in messages], ["api.E004", "api.E005"])
        self.assertIn("REDIS_URL", messages[0].msg)
        self.assertIn("Redis-backed async queueing is mandatory", messages[1].msg)


class ExportAuditSchemaCheckTests(SimpleTestCase):
    @override_settings(
        TESTING=False,
        DMIS_RUNTIME_ENV="shared-dev",
        DMIS_ASYNC_EAGER=False,
        DMIS_WORKER_REQUIRED=True,
    )
    @patch(
        "api.checks.get_replenishment_export_audit_schema_status",
        return_value=(
            "failed",
            "Queued export durability requires needs_list_audit.request_id to exist; apply the replenishment export audit schema update.",
        ),
    )
    def test_export_audit_schema_check_reports_missing_schema(self, _mock_schema_status) -> None:
        messages = api_checks.check_dmis_replenishment_export_audit_schema(None)

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].id, "api.E006")
        self.assertIn("request_id", messages[0].msg)


class AsyncJobApiTests(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="dev-user",
        DEV_AUTH_ROLES=["LOGISTICS"],
        DEV_AUTH_PERMISSIONS=[rbac.PERM_NEEDS_LIST_EXECUTE],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch("replenishment.views._require_record_scope", return_value=None)
    @patch(
        "replenishment.workflow_store_db.get_record",
        return_value={"needs_list_id": "NL-ASYNC-1", "warehouse_id": 10},
    )
    def test_async_job_status_returns_authorized_job_metadata(
        self,
        _mock_get_record,
        _mock_scope,
    ) -> None:
        job = AsyncJob.objects.create(
            job_id="job-status-1",
            job_type=AsyncJob.JobType.NEEDS_LIST_DONATION_EXPORT,
            status=AsyncJob.Status.QUEUED,
            source_resource_type=AsyncJob.SourceType.NEEDS_LIST,
            source_resource_id="NL-ASYNC-1",
            request_id="req-123",
        )

        response = self.client.get("/api/v1/jobs/job-status-1")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["job_id"], job.job_id)
        self.assertEqual(body["status"], AsyncJob.Status.QUEUED)
        self.assertEqual(body["status_url"], f"/api/v1/jobs/{job.job_id}")
        self.assertFalse(body["artifact_ready"])

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="dev-user",
        DEV_AUTH_ROLES=["LOGISTICS"],
        DEV_AUTH_PERMISSIONS=[rbac.PERM_NEEDS_LIST_EXECUTE],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch("replenishment.views._require_record_scope", return_value=None)
    @patch(
        "replenishment.workflow_store_db.get_record",
        return_value={"needs_list_id": "NL-ASYNC-1B", "warehouse_id": 10},
    )
    def test_async_job_status_omits_download_for_expired_artifact(
        self,
        _mock_get_record,
        _mock_scope,
    ) -> None:
        expired_at = timezone.now() - timedelta(minutes=1)
        job = AsyncJob.objects.create(
            job_id="job-status-expired",
            job_type=AsyncJob.JobType.NEEDS_LIST_DONATION_EXPORT,
            status=AsyncJob.Status.SUCCEEDED,
            source_resource_type=AsyncJob.SourceType.NEEDS_LIST,
            source_resource_id="NL-ASYNC-1B",
            artifact_filename="donation_needs_NL-ASYNC-1B.csv",
            artifact_content_type="text/csv",
            artifact_sha256="expiredstatus123",
            expires_at=expired_at,
        )
        AsyncJobArtifact.objects.create(
            job=job,
            payload_text="item_id,item_name\n1,Water\n",
            size_bytes=len("item_id,item_name\n1,Water\n".encode("utf-8")),
            retention_expires_at=expired_at,
        )

        response = self.client.get("/api/v1/jobs/job-status-expired")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["artifact_ready"])
        self.assertNotIn("download_url", body)

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="dev-user",
        DEV_AUTH_ROLES=["LOGISTICS"],
        DEV_AUTH_PERMISSIONS=[rbac.PERM_NEEDS_LIST_EXECUTE],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch(
        "replenishment.views._require_record_scope",
        return_value=Response({"errors": {"tenant_scope": "denied"}}, status=403),
    )
    @patch(
        "replenishment.workflow_store_db.get_record",
        return_value={"needs_list_id": "NL-ASYNC-2", "warehouse_id": 10},
    )
    def test_async_job_status_reuses_needs_list_scope_authorization(
        self,
        _mock_get_record,
        _mock_scope,
    ) -> None:
        AsyncJob.objects.create(
            job_id="job-status-2",
            job_type=AsyncJob.JobType.NEEDS_LIST_DONATION_EXPORT,
            status=AsyncJob.Status.QUEUED,
            source_resource_type=AsyncJob.SourceType.NEEDS_LIST,
            source_resource_id="NL-ASYNC-2",
        )

        response = self.client.get("/api/v1/jobs/job-status-2")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"errors": {"tenant_scope": "denied"}})

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="viewer-user",
        DEV_AUTH_ROLES=[],
        DEV_AUTH_PERMISSIONS=[],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch("replenishment.views._require_record_scope", return_value=None)
    @patch(
        "replenishment.workflow_store_db.get_record",
        return_value={"needs_list_id": "NL-ASYNC-2A", "warehouse_id": 10},
    )
    def test_async_job_status_requires_source_export_permission(
        self,
        _mock_get_record,
        _mock_scope,
    ) -> None:
        AsyncJob.objects.create(
            job_id="job-status-2a",
            job_type=AsyncJob.JobType.NEEDS_LIST_DONATION_EXPORT,
            status=AsyncJob.Status.QUEUED,
            source_resource_type=AsyncJob.SourceType.NEEDS_LIST,
            source_resource_id="NL-ASYNC-2A",
        )

        response = self.client.get("/api/v1/jobs/job-status-2a")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"detail": "Forbidden."})

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="dev-user",
        DEV_AUTH_ROLES=["LOGISTICS"],
        DEV_AUTH_PERMISSIONS=[rbac.PERM_NEEDS_LIST_EXECUTE],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch("api.views.api_logger.warning")
    def test_async_job_status_reports_missing_source_permission_configuration(
        self,
        mock_warning,
    ) -> None:
        AsyncJob.objects.create(
            job_id="job-status-misconfigured",
            job_type=AsyncJob.JobType.NEEDS_LIST_DONATION_EXPORT,
            status=AsyncJob.Status.QUEUED,
            source_resource_type=AsyncJob.SourceType.NEEDS_LIST,
            source_resource_id="NL-ASYNC-MISCONFIGURED",
        )

        with patch.object(replenishment_views.needs_list_donations_export, "required_permission", None):
            response = self.client.get("/api/v1/jobs/job-status-misconfigured")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json(), {"detail": "Async job authorization is misconfigured."})
        mock_warning.assert_called_once()

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="dev-user",
        DEV_AUTH_ROLES=["LOGISTICS"],
        DEV_AUTH_PERMISSIONS=[rbac.PERM_NEEDS_LIST_EXECUTE],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch("replenishment.views._require_record_scope", return_value=None)
    @patch(
        "replenishment.workflow_store_db.get_record",
        return_value={"needs_list_id": "NL-ASYNC-3", "warehouse_id": 10},
    )
    def test_async_job_download_returns_attachment_for_ready_artifact(
        self,
        _mock_get_record,
        _mock_scope,
    ) -> None:
        job = AsyncJob.objects.create(
            job_id="job-download-1",
            job_type=AsyncJob.JobType.NEEDS_LIST_PROCUREMENT_EXPORT,
            status=AsyncJob.Status.SUCCEEDED,
            source_resource_type=AsyncJob.SourceType.NEEDS_LIST,
            source_resource_id="NL-ASYNC-3",
            artifact_filename="procurement_needs_NL-ASYNC-3.csv",
            artifact_content_type="text/csv",
            artifact_sha256="abc123",
            expires_at=timezone.now() + timedelta(hours=1),
        )
        AsyncJobArtifact.objects.create(
            job=job,
            payload_text="item_id,item_name\n1,Generator\n",
            size_bytes=len("item_id,item_name\n1,Generator\n".encode("utf-8")),
            retention_expires_at=job.expires_at,
        )

        response = self.client.get("/api/v1/jobs/job-download-1/download")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Disposition"], 'attachment; filename="procurement_needs_NL-ASYNC-3.csv"')
        self.assertEqual(response["ETag"], "abc123")
        self.assertEqual(response.content.decode("utf-8"), "item_id,item_name\n1,Generator\n")

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="dev-user",
        DEV_AUTH_ROLES=["LOGISTICS"],
        DEV_AUTH_PERMISSIONS=[rbac.PERM_NEEDS_LIST_EXECUTE],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch("replenishment.views._require_record_scope", return_value=None)
    @patch(
        "replenishment.workflow_store_db.get_record",
        return_value={"needs_list_id": "NL-ASYNC-4", "warehouse_id": 10},
    )
    def test_async_job_download_rejects_not_ready_artifact(
        self,
        _mock_get_record,
        _mock_scope,
    ) -> None:
        AsyncJob.objects.create(
            job_id="job-download-2",
            job_type=AsyncJob.JobType.NEEDS_LIST_PROCUREMENT_EXPORT,
            status=AsyncJob.Status.RUNNING,
            source_resource_type=AsyncJob.SourceType.NEEDS_LIST,
            source_resource_id="NL-ASYNC-4",
        )

        response = self.client.get("/api/v1/jobs/job-download-2/download")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json(),
            {
                "job_id": "job-download-2",
                "status": AsyncJob.Status.RUNNING,
                "detail": "The job artifact is not ready.",
            },
        )

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="viewer-user",
        DEV_AUTH_ROLES=[],
        DEV_AUTH_PERMISSIONS=[],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch("replenishment.views._require_record_scope", return_value=None)
    @patch(
        "replenishment.workflow_store_db.get_record",
        return_value={"needs_list_id": "NL-ASYNC-4A", "warehouse_id": 10},
    )
    def test_async_job_download_requires_source_export_permission(
        self,
        _mock_get_record,
        _mock_scope,
    ) -> None:
        AsyncJob.objects.create(
            job_id="job-download-2a",
            job_type=AsyncJob.JobType.NEEDS_LIST_PROCUREMENT_EXPORT,
            status=AsyncJob.Status.SUCCEEDED,
            source_resource_type=AsyncJob.SourceType.NEEDS_LIST,
            source_resource_id="NL-ASYNC-4A",
            artifact_filename="procurement_needs_NL-ASYNC-4A.csv",
            artifact_content_type="text/csv",
            artifact_sha256="abc123",
            artifact_payload="item_id,item_name\n1,Generator\n",
            expires_at=timezone.now() + timedelta(hours=1),
        )

        response = self.client.get("/api/v1/jobs/job-download-2a/download")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"detail": "Forbidden."})

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="dev-user",
        DEV_AUTH_ROLES=["LOGISTICS"],
        DEV_AUTH_PERMISSIONS=[rbac.PERM_NEEDS_LIST_EXECUTE],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch("replenishment.views._require_record_scope", return_value=None)
    @patch(
        "replenishment.workflow_store_db.get_record",
        return_value={"needs_list_id": "NL-ASYNC-4B", "warehouse_id": 10},
    )
    def test_async_job_download_returns_gone_for_expired_durable_artifact(
        self,
        _mock_get_record,
        _mock_scope,
    ) -> None:
        expired_at = timezone.now() - timedelta(minutes=5)
        job = AsyncJob.objects.create(
            job_id="job-download-expired",
            job_type=AsyncJob.JobType.NEEDS_LIST_PROCUREMENT_EXPORT,
            status=AsyncJob.Status.SUCCEEDED,
            source_resource_type=AsyncJob.SourceType.NEEDS_LIST,
            source_resource_id="NL-ASYNC-4B",
            artifact_filename="procurement_needs_NL-ASYNC-4B.csv",
            artifact_content_type="text/csv",
            artifact_sha256="expired123",
            expires_at=expired_at,
        )
        AsyncJobArtifact.objects.create(
            job=job,
            payload_text="item_id,item_name\n2,Tent\n",
            size_bytes=len("item_id,item_name\n2,Tent\n".encode("utf-8")),
            retention_expires_at=expired_at,
        )

        response = self.client.get("/api/v1/jobs/job-download-expired/download")

        self.assertEqual(response.status_code, 410)
        self.assertEqual(
            response.json(),
            {
                "job_id": "job-download-expired",
                "status": AsyncJob.Status.SUCCEEDED,
                "detail": "The job artifact has expired.",
            },
        )

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="dev-user",
        DEV_AUTH_ROLES=["LOGISTICS"],
        DEV_AUTH_PERMISSIONS=[rbac.PERM_NEEDS_LIST_EXECUTE],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch("replenishment.views._require_record_scope", return_value=None)
    @patch(
        "replenishment.workflow_store_db.get_record",
        return_value={"needs_list_id": "NL-ASYNC-4B-EQ", "warehouse_id": 10},
    )
    def test_async_job_download_returns_gone_when_expiry_equals_now(
        self,
        _mock_get_record,
        _mock_scope,
    ) -> None:
        expires_at = timezone.now()
        job = AsyncJob.objects.create(
            job_id="job-download-expired-eq",
            job_type=AsyncJob.JobType.NEEDS_LIST_PROCUREMENT_EXPORT,
            status=AsyncJob.Status.SUCCEEDED,
            source_resource_type=AsyncJob.SourceType.NEEDS_LIST,
            source_resource_id="NL-ASYNC-4B-EQ",
            artifact_filename="procurement_needs_NL-ASYNC-4B-EQ.csv",
            artifact_content_type="text/csv",
            artifact_sha256="expired-eq-123",
            expires_at=expires_at,
        )
        AsyncJobArtifact.objects.create(
            job=job,
            payload_text="item_id,item_name\n2,Tent\n",
            size_bytes=len("item_id,item_name\n2,Tent\n".encode("utf-8")),
            retention_expires_at=expires_at,
        )

        with patch("api.views.timezone.now", return_value=expires_at):
            response = self.client.get("/api/v1/jobs/job-download-expired-eq/download")

        self.assertEqual(response.status_code, 410)
        self.assertEqual(
            response.json(),
            {
                "job_id": "job-download-expired-eq",
                "status": AsyncJob.Status.SUCCEEDED,
                "detail": "The job artifact has expired.",
            },
        )

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="dev-user",
        DEV_AUTH_ROLES=["LOGISTICS"],
        DEV_AUTH_PERMISSIONS=[rbac.PERM_NEEDS_LIST_EXECUTE],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch("api.views.api_logger.error")
    @patch("replenishment.views._require_record_scope", return_value=None)
    @patch(
        "replenishment.workflow_store_db.get_record",
        return_value={"needs_list_id": "NL-ASYNC-4C", "warehouse_id": 10},
    )
    def test_async_job_download_reports_storage_inconsistency_for_missing_payload(
        self,
        _mock_get_record,
        _mock_scope,
        mock_error,
    ) -> None:
        AsyncJob.objects.create(
            job_id="job-download-missing",
            job_type=AsyncJob.JobType.NEEDS_LIST_PROCUREMENT_EXPORT,
            status=AsyncJob.Status.SUCCEEDED,
            source_resource_type=AsyncJob.SourceType.NEEDS_LIST,
            source_resource_id="NL-ASYNC-4C",
            artifact_filename="procurement_needs_NL-ASYNC-4C.csv",
            artifact_content_type="text/csv",
            artifact_sha256="missing123",
            expires_at=timezone.now() + timedelta(hours=1),
        )

        response = self.client.get("/api/v1/jobs/job-download-missing/download")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.json(),
            {
                "job_id": "job-download-missing",
                "status": AsyncJob.Status.SUCCEEDED,
                "detail": "The job artifact is unavailable due to a storage inconsistency.",
            },
        )
        mock_error.assert_called_once()

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="dev-user",
        DEV_AUTH_ROLES=["LOGISTICS"],
        DEV_AUTH_PERMISSIONS=[rbac.PERM_NEEDS_LIST_EXECUTE],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
        TENANT_SCOPE_ENFORCEMENT=True,
    )
    @patch(
        "replenishment.workflow_store_db.get_record",
        return_value={"needs_list_id": "NL-ASYNC-4D", "warehouse_id": 10},
    )
    def test_async_job_download_denies_cross_tenant_access(
        self,
        _mock_get_record,
    ) -> None:
        job = AsyncJob.objects.create(
            job_id="job-download-idor",
            job_type=AsyncJob.JobType.NEEDS_LIST_PROCUREMENT_EXPORT,
            status=AsyncJob.Status.SUCCEEDED,
            source_resource_type=AsyncJob.SourceType.NEEDS_LIST,
            source_resource_id="NL-ASYNC-4D",
            artifact_filename="procurement_needs_NL-ASYNC-4D.csv",
            artifact_content_type="text/csv",
            artifact_sha256="idor123",
            artifact_payload="item_id,item_name\n1,Generator\n",
            expires_at=timezone.now() + timedelta(hours=1),
        )

        context = TenantContext(
            requested_tenant_id=2,
            active_tenant_id=2,
            active_tenant_code="AGENCY_B",
            active_tenant_type="AGENCY",
            memberships=(
                TenantMembership(
                    tenant_id=2,
                    tenant_code="AGENCY_B",
                    tenant_name="Agency B",
                    tenant_type="AGENCY",
                    is_primary=True,
                    access_level="WRITE",
                ),
            ),
            can_read_all_tenants=False,
            can_act_cross_tenant=False,
        )

        with patch("replenishment.views._tenant_context", return_value=context), patch(
            "api.tenancy.resolve_warehouse_tenant_id",
            return_value=1,
        ):
            response = self.client.get(f"/api/v1/jobs/{job.job_id}/download")

        self.assertEqual(response.status_code, 403)
        self.assertIn("tenant_scope", response.json().get("errors", {}))


class AsyncJobTaskTests(TestCase):
    @staticmethod
    def _fake_celery_modules() -> dict[str, object]:
        class FakeSignal:
            def connect(self, receiver=None, **_kwargs):
                if receiver is None:
                    def decorator(func):
                        return func

                    return decorator
                return receiver

        class FakeSharedTask:
            def __init__(self, func):
                self._func = func
                self.request = SimpleNamespace(retries=0, id=None)

            def run(self, *args, **kwargs):
                return self._func(self, *args, **kwargs)

            def delay(self, *args, **kwargs):
                return self.run(*args, **kwargs)

            def retry(self, *args, **kwargs):
                raise RuntimeError("retry called")

        def shared_task(*_args, **_kwargs):
            def decorator(func):
                return FakeSharedTask(func)

            return decorator

        celery_module = types.ModuleType("celery")
        celery_module.shared_task = shared_task

        celery_signals_module = types.ModuleType("celery.signals")
        celery_signals_module.heartbeat_sent = FakeSignal()
        celery_signals_module.worker_ready = FakeSignal()

        return {
            "celery": celery_module,
            "celery.signals": celery_signals_module,
        }

    def _load_api_tasks(self):
        sys.modules.pop("api.tasks", None)
        with patch.dict(sys.modules, self._fake_celery_modules()):
            return import_module("api.tasks")

    def _create_needs_list(self, *, needs_list_no: str = "NL-TASK-1") -> NeedsList:
        return NeedsList.objects.create(
            needs_list_no=needs_list_no,
            event_id=1,
            warehouse_id=1,
            event_phase="BASELINE",
            calculation_dtime=timezone.now(),
            demand_window_hours=24,
            planning_window_hours=72,
            safety_factor=Decimal("1.25"),
            data_freshness_level="HIGH",
            status_code="APPROVED",
            total_gap_qty=Decimal("5.00"),
            create_by_id="tester",
            update_by_id="tester",
        )

    def _create_job(self, *, job_id: str) -> AsyncJob:
        needs_list = self._create_needs_list()
        return AsyncJob.objects.create(
            job_id=job_id,
            job_type=AsyncJob.JobType.NEEDS_LIST_DONATION_EXPORT,
            status=AsyncJob.Status.QUEUED,
            source_resource_type=AsyncJob.SourceType.NEEDS_LIST,
            source_resource_id=str(needs_list.needs_list_id),
            active_dedupe_key=f"dedupe-{job_id}",
            max_retries=3,
            actor_user_id="task-user",
            actor_username="task.user",
            request_id="req-task-1",
        )

    def test_run_async_job_marks_job_succeeded_and_persists_artifact(self) -> None:
        api_tasks = self._load_api_tasks()

        job = self._create_job(job_id="task-success-1")
        request_context = SimpleNamespace(retries=0, id="celery-task-1")

        with patch("api.tasks._touch_worker_heartbeat"), patch.object(
            api_tasks,
            "_build_needs_list_export_artifact",
            return_value=(
                "donation_needs_NL-TASK-1.csv",
                "text/csv",
                "sha-123",
                "item_id,item_name\n1,Water\n",
            ),
        ), patch.object(api_tasks.run_async_job, "request", request_context), patch(
            "api.tasks.job_logger.info"
        ) as mock_info:
            status = api_tasks.run_async_job.run(job.job_id)

        job.refresh_from_db()
        artifact = AsyncJobArtifact.objects.get(job=job)
        audit = NeedsListAudit.objects.get(
            needs_list_id=int(job.source_resource_id),
            action_type="EXPORT_GENERATED",
        )
        success_logs = [
            call.kwargs.get("extra", {})
            for call in mock_info.call_args_list
            if call.args and call.args[0] == "job.succeeded"
        ]

        self.assertEqual(status, AsyncJob.Status.SUCCEEDED)
        self.assertEqual(job.status, AsyncJob.Status.SUCCEEDED)
        self.assertEqual(job.artifact_filename, "donation_needs_NL-TASK-1.csv")
        self.assertEqual(job.artifact_content_type, "text/csv")
        self.assertEqual(job.artifact_sha256, "sha-123")
        self.assertIsNone(job.artifact_payload)
        self.assertEqual(artifact.payload_text, "item_id,item_name\n1,Water\n")
        self.assertEqual(artifact.size_bytes, len("item_id,item_name\n1,Water\n".encode("utf-8")))
        self.assertEqual(audit.field_name, "artifact_sha256")
        self.assertEqual(audit.new_value, "sha-123")
        self.assertEqual(audit.reason_code, "DONATION_EXPORT")
        self.assertEqual(audit.actor_user_id, "task-user")
        self.assertEqual(audit.request_id, "req-task-1")
        self.assertEqual(
            audit.notes_text,
            f"artifact_id={artifact.artifact_id} file=donation_needs_NL-TASK-1.csv",
        )
        self.assertEqual(len(success_logs), 1)
        self.assertEqual(success_logs[0].get("artifact_id"), artifact.artifact_id)
        self.assertIsNone(job.active_dedupe_key)

    def test_run_async_job_marks_job_failed_for_permanent_errors(self) -> None:
        api_tasks = self._load_api_tasks()

        job = self._create_job(job_id="task-failed-1")
        request_context = SimpleNamespace(retries=0, id="celery-task-2")

        with patch("api.tasks._touch_worker_heartbeat"), patch.object(
            api_tasks,
            "_build_needs_list_export_artifact",
            side_effect=api_tasks.AsyncJobPermanentError("source needs list missing"),
        ), patch.object(api_tasks.run_async_job, "request", request_context):
            status = api_tasks.run_async_job.run(job.job_id)

        job.refresh_from_db()
        self.assertEqual(status, AsyncJob.Status.FAILED)
        self.assertEqual(job.status, AsyncJob.Status.FAILED)
        self.assertEqual(job.error_message, "source needs list missing")
        self.assertIsNone(job.active_dedupe_key)
        self.assertFalse(job.artifact_ready)

    def test_run_async_job_fails_when_export_audit_schema_is_missing(self) -> None:
        api_tasks = self._load_api_tasks()

        job = self._create_job(job_id="task-schema-missing-1")
        request_context = SimpleNamespace(retries=0, id="celery-task-schema-missing")

        with patch("api.tasks._touch_worker_heartbeat"), patch.object(
            api_tasks,
            "get_replenishment_export_audit_schema_status",
            return_value=(
                "failed",
                "Queued export durability requires needs_list_audit.request_id to exist; apply the replenishment export audit schema update.",
            ),
        ), patch.object(api_tasks.run_async_job, "request", request_context):
            status = api_tasks.run_async_job.run(job.job_id)

        job.refresh_from_db()
        self.assertEqual(status, AsyncJob.Status.FAILED)
        self.assertEqual(job.status, AsyncJob.Status.FAILED)
        self.assertIn("request_id", job.error_message)
        self.assertFalse(AsyncJobArtifact.objects.filter(job=job).exists())

    def test_run_async_job_marks_retrying_before_requesting_retry(self) -> None:
        api_tasks = self._load_api_tasks()

        job = self._create_job(job_id="task-retry-1")
        request_context = SimpleNamespace(retries=0, id="celery-task-3")

        with patch("api.tasks._touch_worker_heartbeat"), patch.object(
            api_tasks,
            "_build_needs_list_export_artifact",
            side_effect=RuntimeError("database temporarily unavailable"),
        ), patch.object(api_tasks.run_async_job, "request", request_context), patch.object(
            api_tasks.run_async_job,
            "retry",
            side_effect=RuntimeError("retry called"),
        ) as mock_retry:
            with self.assertRaisesMessage(RuntimeError, "retry called"):
                api_tasks.run_async_job.run(job.job_id)

        job.refresh_from_db()
        self.assertEqual(job.status, AsyncJob.Status.RETRYING)
        self.assertEqual(job.retry_count, 1)
        self.assertEqual(
            job.error_message,
            "RuntimeError: database temporarily unavailable",
        )
        mock_retry.assert_called_once()

    def test_run_async_job_logs_recovery_when_redelivered_after_running_state(self) -> None:
        api_tasks = self._load_api_tasks()

        job = self._create_job(job_id="task-recovered-1")
        job.status = AsyncJob.Status.RUNNING
        job.celery_task_id = "celery-task-old"
        job.started_at = timezone.now() - timedelta(minutes=10)
        job.save(update_fields=["status", "celery_task_id", "started_at"])
        request_context = SimpleNamespace(retries=0, id="celery-task-new")

        with patch("api.tasks._touch_worker_heartbeat"), patch.object(
            api_tasks,
            "_build_needs_list_export_artifact",
            return_value=(
                "donation_needs_NL-TASK-1.csv",
                "text/csv",
                "sha-123",
                "item_id,item_name\n1,Water\n",
            ),
        ), patch.object(api_tasks.run_async_job, "request", request_context), patch(
            "api.tasks.job_logger.warning"
        ) as mock_warning:
            status = api_tasks.run_async_job.run(job.job_id)

        job.refresh_from_db()
        self.assertEqual(status, AsyncJob.Status.SUCCEEDED)
        mock_warning.assert_called_once()
        self.assertEqual(mock_warning.call_args.args[0], "job.recovered")
        self.assertEqual(mock_warning.call_args.kwargs["extra"]["event"], "job.recovered")
        self.assertEqual(
            mock_warning.call_args.kwargs["extra"]["previous_celery_task_id"],
            "celery-task-old",
        )


class AsyncJobArtifactMigrationTests(TestCase):
    def test_backfill_migration_copies_non_expired_inline_artifacts(self) -> None:
        migration_module = import_module("api.migrations.0002_async_job_artifact")
        retained_job = AsyncJob.objects.create(
            job_id="migration-inline-retained",
            job_type=AsyncJob.JobType.NEEDS_LIST_DONATION_EXPORT,
            status=AsyncJob.Status.SUCCEEDED,
            source_resource_type=AsyncJob.SourceType.NEEDS_LIST,
            source_resource_id="1",
            artifact_filename="donation.csv",
            artifact_content_type="text/csv",
            artifact_sha256="retain123",
            artifact_payload="item_id,item_name\n1,Water\n",
            expires_at=timezone.now() + timedelta(hours=2),
        )
        expired_job = AsyncJob.objects.create(
            job_id="migration-inline-expired",
            job_type=AsyncJob.JobType.NEEDS_LIST_DONATION_EXPORT,
            status=AsyncJob.Status.SUCCEEDED,
            source_resource_type=AsyncJob.SourceType.NEEDS_LIST,
            source_resource_id="2",
            artifact_filename="donation-expired.csv",
            artifact_content_type="text/csv",
            artifact_sha256="expired123",
            artifact_payload="item_id,item_name\n2,Tent\n",
            expires_at=timezone.now() - timedelta(hours=2),
        )

        migration_module.backfill_durable_async_job_artifacts(django_apps, None)

        retained_artifact = AsyncJobArtifact.objects.get(job=retained_job)
        self.assertEqual(retained_artifact.payload_text, "item_id,item_name\n1,Water\n")
        self.assertEqual(retained_artifact.retention_expires_at, retained_job.expires_at)
        retained_job.refresh_from_db()
        self.assertEqual(retained_job.artifact_payload, "item_id,item_name\n1,Water\n")
        self.assertFalse(AsyncJobArtifact.objects.filter(job=expired_job).exists())

    def test_backfill_migration_fails_for_jobs_without_retention_expiry(self) -> None:
        migration_module = import_module("api.migrations.0002_async_job_artifact")
        retained_job = AsyncJob.objects.create(
            job_id="migration-inline-no-expiry",
            job_type=AsyncJob.JobType.NEEDS_LIST_DONATION_EXPORT,
            status=AsyncJob.Status.SUCCEEDED,
            source_resource_type=AsyncJob.SourceType.NEEDS_LIST,
            source_resource_id="3",
            artifact_filename="donation-null-expiry.csv",
            artifact_content_type="text/csv",
            artifact_sha256="retain-null-expiry",
            artifact_payload="item_id,item_name\n5,Water Purification Tablet\n",
            expires_at=None,
        )

        with self.assertRaisesMessage(RuntimeError, "explicit retention policy"):
            migration_module.backfill_durable_async_job_artifacts(django_apps, None)

        self.assertFalse(AsyncJobArtifact.objects.filter(job=retained_job).exists())


class AsyncJobArtifactCleanupCommandTests(TestCase):
    def _create_job(
        self,
        *,
        job_id: str,
        expires_at,
        artifact_payload: str | None = None,
        durable_payload: str | None = None,
    ) -> AsyncJob:
        job = AsyncJob.objects.create(
            job_id=job_id,
            job_type=AsyncJob.JobType.NEEDS_LIST_PROCUREMENT_EXPORT,
            status=AsyncJob.Status.SUCCEEDED,
            source_resource_type=AsyncJob.SourceType.NEEDS_LIST,
            source_resource_id="1",
            artifact_filename=f"{job_id}.csv",
            artifact_content_type="text/csv",
            artifact_sha256=f"sha-{job_id}",
            artifact_payload=artifact_payload,
            expires_at=expires_at,
        )
        if durable_payload is not None:
            AsyncJobArtifact.objects.create(
                job=job,
                payload_text=durable_payload,
                size_bytes=len(durable_payload.encode("utf-8")),
                retention_expires_at=expires_at,
            )
        return job

    def test_purge_expired_async_job_artifacts_dry_run_keeps_data(self) -> None:
        expired_job = self._create_job(
            job_id="expired-job",
            expires_at=timezone.now() - timedelta(hours=1),
            artifact_payload="item_id,item_name\n1,Water\n",
            durable_payload="item_id,item_name\n1,Water\n",
        )
        fresh_job = self._create_job(
            job_id="fresh-job",
            expires_at=timezone.now() + timedelta(hours=1),
            artifact_payload="item_id,item_name\n2,Tent\n",
            durable_payload="item_id,item_name\n2,Tent\n",
        )
        output = StringIO()

        call_command("purge_expired_async_job_artifacts", stdout=output)

        text = output.getvalue()
        self.assertIn("expired durable artifacts: 1", text)
        self.assertIn("expired legacy inline payloads: 1", text)
        self.assertTrue(AsyncJobArtifact.objects.filter(job=expired_job).exists())
        expired_job.refresh_from_db()
        self.assertEqual(expired_job.artifact_payload, "item_id,item_name\n1,Water\n")
        self.assertTrue(AsyncJobArtifact.objects.filter(job=fresh_job).exists())

    def test_purge_expired_async_job_artifacts_apply_removes_expired_payloads_only(self) -> None:
        expires_at = timezone.now() - timedelta(hours=1)
        expired_job = self._create_job(
            job_id="expired-job-apply",
            expires_at=expires_at,
            artifact_payload="item_id,item_name\n3,Blanket\n",
            durable_payload="item_id,item_name\n3,Blanket\n",
        )
        fresh_job = self._create_job(
            job_id="fresh-job-apply",
            expires_at=timezone.now() + timedelta(hours=1),
            artifact_payload="item_id,item_name\n4,Generator\n",
            durable_payload="item_id,item_name\n4,Generator\n",
        )
        output = StringIO()

        call_command("purge_expired_async_job_artifacts", apply=True, stdout=output)

        expired_job.refresh_from_db()
        fresh_job.refresh_from_db()
        self.assertFalse(AsyncJobArtifact.objects.filter(job=expired_job).exists())
        self.assertIsNone(expired_job.artifact_payload)
        self.assertEqual(expired_job.artifact_filename, "expired-job-apply.csv")
        self.assertEqual(expired_job.artifact_sha256, "sha-expired-job-apply")
        self.assertEqual(expired_job.expires_at, expires_at)
        self.assertTrue(AsyncJobArtifact.objects.filter(job=fresh_job).exists())
        self.assertEqual(fresh_job.artifact_payload, "item_id,item_name\n4,Generator\n")
        self.assertIn("were purged", output.getvalue())

    def test_purge_expired_async_job_artifacts_apply_batches_when_requested(self) -> None:
        expired_jobs = [
            self._create_job(
                job_id=f"expired-job-batch-{index}",
                expires_at=timezone.now() - timedelta(hours=1),
                artifact_payload=f"item_id,item_name\n{index},Water\n",
                durable_payload=f"item_id,item_name\n{index},Water\n",
            )
            for index in (1, 2)
        ]
        output = StringIO()

        call_command(
            "purge_expired_async_job_artifacts",
            apply=True,
            batch_size=1,
            stdout=output,
        )

        for job in expired_jobs:
            job.refresh_from_db()
            self.assertFalse(AsyncJobArtifact.objects.filter(job=job).exists())
            self.assertIsNone(job.artifact_payload)
        self.assertIn("were purged", output.getvalue())


class AsyncJobModelTests(SimpleTestCase):
    def test_artifact_payload_text_prefers_durable_artifact_when_present(self) -> None:
        durable_artifact = type("DurableArtifactStub", (), {"payload_text": ""})()
        job = AsyncJob(
            job_id="async-job-durable-artifact-canonical",
            job_type=AsyncJob.JobType.NEEDS_LIST_PROCUREMENT_EXPORT,
            status=AsyncJob.Status.SUCCEEDED,
            source_resource_type=AsyncJob.SourceType.NEEDS_LIST,
            source_resource_id="1",
            artifact_payload="legacy-inline-payload",
        )

        with patch.object(AsyncJob, "durable_artifact_or_none", return_value=durable_artifact):
            self.assertEqual(job.artifact_payload_text, "")

    def test_mark_succeeded_requires_timezone_aware_expiry(self) -> None:
        job = AsyncJob(
            job_id="async-job-aware-expiry",
            job_type=AsyncJob.JobType.NEEDS_LIST_PROCUREMENT_EXPORT,
            status=AsyncJob.Status.QUEUED,
            source_resource_type=AsyncJob.SourceType.NEEDS_LIST,
            source_resource_id="1",
        )

        with self.assertRaisesMessage(ValueError, "timezone-aware"):
            job.mark_succeeded(
                artifact_filename="report.csv",
                artifact_content_type="text/csv",
                artifact_sha256="sha-aware-expiry",
                artifact_expires_at=datetime.utcnow(),
            )

    def test_mark_succeeded_rejects_expired_expiry(self) -> None:
        now = timezone.now()
        job = AsyncJob(
            job_id="async-job-expired-expiry",
            job_type=AsyncJob.JobType.NEEDS_LIST_PROCUREMENT_EXPORT,
            status=AsyncJob.Status.QUEUED,
            source_resource_type=AsyncJob.SourceType.NEEDS_LIST,
            source_resource_id="1",
        )

        with patch("api.models.timezone.now", return_value=now):
            with self.assertRaisesMessage(ValueError, "must be in the future"):
                job.mark_succeeded(
                    artifact_filename="report.csv",
                    artifact_content_type="text/csv",
                    artifact_sha256="sha-expired-expiry",
                    artifact_expires_at=now,
                )

    def test_artifact_ready_false_when_expiry_equals_now(self) -> None:
        now = timezone.now()
        job = AsyncJob(
            job_id="async-job-expired-at-boundary",
            job_type=AsyncJob.JobType.NEEDS_LIST_PROCUREMENT_EXPORT,
            status=AsyncJob.Status.SUCCEEDED,
            source_resource_type=AsyncJob.SourceType.NEEDS_LIST,
            source_resource_id="1",
            artifact_payload="item_id,item_name\n1,Water\n",
            expires_at=now,
        )

        with patch("api.models.timezone.now", return_value=now):
            self.assertFalse(job.artifact_ready)


class RequestContextMiddlewareTests(SimpleTestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.client.raise_request_exception = False

    @override_settings(ROOT_URLCONF="api.tests", DEBUG=False)
    @patch("api.apps.request_logger.exception")
    def test_unhandled_server_error_logs_with_request_id(self, mock_exception) -> None:
        response = self.client.get("/boom/", HTTP_X_REQUEST_ID="edge-boom-500")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response["X-Request-ID"], "edge-boom-500")
        mock_exception.assert_called_once()
        self.assertEqual(mock_exception.call_args.args[0], "request.unhandled_exception")
        self.assertEqual(mock_exception.call_args.kwargs["extra"]["request_id"], "edge-boom-500")
        self.assertEqual(mock_exception.call_args.kwargs["extra"]["exception_class"], "RuntimeError")


class AuthLoggingTests(SimpleTestCase):
    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch("api.authentication.logger.warning")
    def test_legacy_dev_header_warning_uses_structured_event(self, mock_warning) -> None:
        request = SimpleNamespace(
            META={"HTTP_X_DEV_USER": "legacy-user"},
            method="GET",
            path="/api/v1/auth/whoami/",
        )

        with self.assertRaises(AuthenticationFailed):
            authentication._enforce_dev_override_header_policy(request)

        mock_warning.assert_called_once()
        self.assertEqual(mock_warning.call_args.args[0], "auth.rejected_legacy_dev_header")
        self.assertEqual(
            mock_warning.call_args.kwargs["extra"]["event"],
            "auth.rejected_legacy_dev_header",
        )
        self.assertEqual(
            mock_warning.call_args.kwargs["extra"]["request_path"],
            "/api/v1/auth/whoami/",
        )

    @override_settings(
        AUTH_ISSUER="https://issuer.example",
        AUTH_AUDIENCE="dmis-api",
        AUTH_ALGORITHMS=["RS256"],
    )
    @patch(
        "api.authentication.jwt.get_unverified_header",
        side_effect=authentication.InvalidTokenError("bad token"),
    )
    @patch("api.authentication.logger.warning")
    def test_jwt_verification_failure_logs_structured_event_and_exception_class(
        self,
        mock_warning,
        _mock_get_unverified_header,
    ) -> None:
        with self.assertRaises(AuthenticationFailed):
            authentication._verify_jwt_with_jwks(
                "not-a-real-token",
                "https://issuer.example/.well-known/jwks.json",
            )

        mock_warning.assert_called_once()
        self.assertEqual(mock_warning.call_args.args[0], "auth.jwt_verification_failed")
        self.assertEqual(
            mock_warning.call_args.kwargs["extra"]["event"],
            "auth.jwt_verification_failed",
        )
        self.assertEqual(
            mock_warning.call_args.kwargs["extra"]["exception_class"],
            "InvalidTokenError",
        )


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
        AUTH_ENABLED=True,
        DEV_AUTH_ENABLED=False,
        AUTH_ISSUER="https://issuer.example",
        AUTH_AUDIENCE="dmis-api",
        AUTH_JWKS_URL="https://issuer.example/.well-known/jwks.json",
        AUTH_USER_ID_CLAIM="sub",
        AUTH_ROLES_CLAIM="roles",
        AUTH_USE_DB_RBAC=False,
    )
    @patch("api.apps.security_logger.warning")
    def test_whoami_auth_failure_includes_request_id_and_logs_security_event(
        self,
        mock_warning,
    ) -> None:
        response = self.client.get(
            "/api/v1/auth/whoami/",
            HTTP_X_REQUEST_ID="edge-auth-401",
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response["X-Request-ID"], "edge-auth-401")
        self.assertEqual(response.json()["request_id"], "edge-auth-401")
        mock_warning.assert_called_once()
        self.assertEqual(mock_warning.call_args.args[0], "auth.request_rejected")
        self.assertEqual(mock_warning.call_args.kwargs["extra"]["request_id"], "edge-auth-401")
        self.assertEqual(mock_warning.call_args.kwargs["extra"]["auth_mode"], "missing")

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
        DMIS_RUNTIME_ENV="local-harness",
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
        DMIS_RUNTIME_ENV="local-harness",
        LOCAL_AUTH_HARNESS_ENABLED=True,
        LOCAL_AUTH_HARNESS_USERNAMES=["local_system_admin_tst"],
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="dev-user",
        DEV_AUTH_ROLES=["SYSTEM_ADMINISTRATOR"],
        DEV_AUTH_PERMISSIONS=[],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch("api.authentication.connection.cursor", side_effect=DatabaseError("boom"))
    def test_whoami_rejects_invalid_local_harness_override_instead_of_falling_back(
        self,
        _mock_cursor,
    ) -> None:
        response = self.client.get(
            "/api/v1/auth/whoami/",
            HTTP_X_DMIS_LOCAL_USER="local_system_admin_tst",
        )

        self.assertEqual(response.status_code, 401)
        self.assertIn("could not be resolved safely", response.json()["detail"])

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        DMIS_RUNTIME_ENV="local-harness",
        LOCAL_AUTH_HARNESS_ENABLED=True,
        LOCAL_AUTH_HARNESS_USERNAMES=["local_system_admin_tst"],
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="local_system_admin_tst",
        DEV_AUTH_ROLES=["SYSTEM_ADMINISTRATOR"],
        DEV_AUTH_PERMISSIONS=[],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch(
        "api.authentication.connection.cursor",
        side_effect=[_CursorResultContext((27, "local_system_admin_tst")), DatabaseError("boom")],
    )
    def test_whoami_rejects_local_harness_override_when_rbac_lookup_fails(
        self,
        _mock_cursor,
    ) -> None:
        response = self.client.get(
            "/api/v1/auth/whoami/",
            HTTP_X_DMIS_LOCAL_USER="local_system_admin_tst",
        )

        self.assertEqual(response.status_code, 401)
        self.assertIn("RBAC lookup failed", response.json()["detail"])

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        DMIS_RUNTIME_ENV="local-harness",
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
        DMIS_RUNTIME_ENV="local-harness",
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
        DMIS_RUNTIME_ENV="local-harness",
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

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        DMIS_RUNTIME_ENV="local-harness",
        LOCAL_AUTH_HARNESS_ENABLED=True,
        LOCAL_AUTH_HARNESS_USERNAMES=["local_system_admin_tst"],
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="local_system_admin_tst",
        DEV_AUTH_ROLES=["SYSTEM_ADMINISTRATOR"],
        DEV_AUTH_PERMISSIONS=[],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch("api.views._load_local_auth_harness_users", side_effect=DatabaseError("boom"))
    def test_local_auth_harness_route_reports_backend_failure(self, _mock_load_users) -> None:
        response = self.client.get("/api/v1/auth/local-harness/")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(),
            {"detail": "Local auth harness is temporarily unavailable."},
        )

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

    def test_needs_list_execute_compat_does_not_grant_partial_release_approval(self) -> None:
        compat = rbac._compat_operations_permissions_for_permissions([rbac.PERM_NEEDS_LIST_EXECUTE])

        self.assertIn(rbac.PERM_OPERATIONS_PARTIAL_RELEASE_REQUEST, compat)
        self.assertNotIn(rbac.PERM_OPERATIONS_PARTIAL_RELEASE_APPROVE, compat)

    def test_needs_list_approve_compat_grants_partial_release_approval(self) -> None:
        compat = rbac._compat_operations_permissions_for_permissions([rbac.PERM_NEEDS_LIST_APPROVE])

        self.assertIn(rbac.PERM_OPERATIONS_PARTIAL_RELEASE_APPROVE, compat)

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

