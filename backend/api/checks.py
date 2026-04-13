from __future__ import annotations

from django.conf import settings
from django.core.checks import Error, Warning, register
from django.db import DatabaseError, connection
from dmis_api import settings as dmis_settings


@register()
def check_dmis_auth_runtime_posture(app_configs, **kwargs):
    messages = []

    try:
        dmis_settings.validate_runtime_auth_configuration(
            runtime_env=str(getattr(settings, "DMIS_RUNTIME_ENV", "")).strip(),
            debug=bool(getattr(settings, "DEBUG", False)),
            auth_enabled=bool(getattr(settings, "AUTH_ENABLED", False)),
            dev_auth_enabled=bool(getattr(settings, "DEV_AUTH_ENABLED", False)),
            local_auth_harness_enabled=bool(getattr(settings, "LOCAL_AUTH_HARNESS_ENABLED", False)),
            testing=bool(getattr(settings, "TESTING", False)),
        )
    except RuntimeError as exc:
        messages.append(
            Error(
                str(exc),
                id="api.E002",
            )
        )

    return messages


@register(deploy=True)
def check_dmis_secure_runtime_posture(app_configs, **kwargs):
    messages = []

    try:
        dmis_settings.validate_runtime_security_configuration(
            runtime_env=str(getattr(settings, "DMIS_RUNTIME_ENV", "")).strip(),
            debug=bool(getattr(settings, "DEBUG", False)),
            secret_key=str(getattr(settings, "SECRET_KEY", "")),
            secret_key_explicit=bool(getattr(settings, "DMIS_SECRET_KEY_EXPLICIT", False)),
            allowed_hosts=list(getattr(settings, "ALLOWED_HOSTS", [])),
            allowed_hosts_explicit=bool(getattr(settings, "DMIS_ALLOWED_HOSTS_EXPLICIT", False)),
            secure_ssl_redirect=bool(getattr(settings, "SECURE_SSL_REDIRECT", False)),
            session_cookie_secure=bool(getattr(settings, "SESSION_COOKIE_SECURE", False)),
            csrf_cookie_secure=bool(getattr(settings, "CSRF_COOKIE_SECURE", False)),
            secure_hsts_seconds=int(getattr(settings, "SECURE_HSTS_SECONDS", 0)),
            secure_hsts_include_subdomains=bool(
                getattr(settings, "SECURE_HSTS_INCLUDE_SUBDOMAINS", False)
            ),
            secure_hsts_preload=bool(getattr(settings, "SECURE_HSTS_PRELOAD", False)),
            x_frame_options=str(getattr(settings, "X_FRAME_OPTIONS", "")).strip().upper(),
            secure_referrer_policy=str(
                getattr(settings, "SECURE_REFERRER_POLICY", "")
            ).strip().lower(),
            csrf_trusted_origins=list(getattr(settings, "CSRF_TRUSTED_ORIGINS", [])),
            secure_proxy_ssl_header=getattr(settings, "SECURE_PROXY_SSL_HEADER", None),
            use_x_forwarded_host=bool(getattr(settings, "USE_X_FORWARDED_HOST", False)),
            testing=bool(getattr(settings, "TESTING", False)),
        )
    except RuntimeError as exc:
        messages.append(
            Error(
                str(exc),
                id="api.E003",
            )
        )

    return messages


@register(deploy=True)
def check_dmis_runtime_dependency_posture(app_configs, **kwargs):
    messages = []

    try:
        dmis_settings.validate_runtime_redis_configuration(
            runtime_env=str(getattr(settings, "DMIS_RUNTIME_ENV", "")).strip(),
            redis_url=str(getattr(settings, "DMIS_REDIS_URL", "")).strip(),
            cache_backend=str(getattr(settings, "DMIS_DEFAULT_CACHE_BACKEND", "")).strip(),
            testing=bool(getattr(settings, "TESTING", False)),
        )
    except RuntimeError as exc:
        messages.append(
            Error(
                str(exc),
                id="api.E004",
            )
        )

    try:
        dmis_settings.validate_runtime_async_configuration(
            runtime_env=str(getattr(settings, "DMIS_RUNTIME_ENV", "")).strip(),
            async_eager=bool(getattr(settings, "DMIS_ASYNC_EAGER", False)),
            worker_required=bool(getattr(settings, "DMIS_WORKER_REQUIRED", False)),
            redis_url=str(getattr(settings, "DMIS_REDIS_URL", "")).strip(),
            broker_url=str(getattr(settings, "CELERY_BROKER_URL", "")).strip(),
            result_backend=str(getattr(settings, "CELERY_RESULT_BACKEND", "")).strip(),
            testing=bool(getattr(settings, "TESTING", False)),
        )
    except RuntimeError as exc:
        messages.append(
            Error(
                str(exc),
                id="api.E005",
            )
        )

    return messages


@register()
def check_dmis_rbac_boundary(app_configs, **kwargs):
    messages = []

    if not getattr(settings, "AUTH_USE_DB_RBAC", False):
        messages.append(
            Warning(
                "AUTH_USE_DB_RBAC is disabled; DMIS RBAC is expected as the canonical auth source.",
                id="api.W001",
            )
        )
        return messages

    required_tables = ["user", "role", "permission", "role_permission", "user_role"]
    missing = [table_name for table_name in required_tables if not _table_exists(table_name)]
    if missing:
        messages.append(
            Error(
                f"Required DMIS RBAC table(s) missing: {', '.join(sorted(missing))}.",
                id="api.E001",
            )
        )
        return messages

    django_auth_tables = [
        "auth_user",
        "auth_group",
        "auth_group_permissions",
        "auth_user_groups",
        "auth_user_user_permissions",
    ]
    populated = []
    for table_name in django_auth_tables:
        count = _count_rows(table_name)
        if count is not None and count > 0:
            populated.append((table_name, count))

    if populated:
        details = ", ".join(f"{name}={count}" for name, count in populated)
        messages.append(
            Warning(
                "Django auth membership tables contain rows. "
                "DMIS RBAC remains canonical; validate these are framework-only artifacts "
                f"and not business authorization dependencies ({details}).",
                id="api.W002",
            )
        )

    return messages


def _table_exists(table_name: str) -> bool:
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT EXISTS(
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = current_schema() AND table_name = %s
                )
                """,
                [table_name],
            )
            return bool(cursor.fetchone()[0])
    except DatabaseError:
        return False


def _count_rows(table_name: str) -> int | None:
    if not _table_exists(table_name):
        return None
    try:
        with connection.cursor() as cursor:
            quoted = connection.ops.quote_name(table_name)
            cursor.execute(f"SELECT COUNT(*) FROM {quoted}")
            return int(cursor.fetchone()[0])
    except DatabaseError:
        return None

