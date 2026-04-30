from __future__ import annotations

from django.conf import settings
from django.core.checks import Error, Tags, Warning as DjangoWarning, register
from django.db import DatabaseError, connection
from dmis_api import settings as dmis_settings


@register(Tags.security)
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


@register(deploy=True)
def check_dmis_replenishment_export_audit_schema(app_configs, **kwargs):
    if not _replenishment_export_audit_schema_required():
        return []

    status, reason = get_replenishment_export_audit_schema_status()
    if status != "failed":
        return []

    return [
        Error(
            reason or (
                "Queued export durability requires the replenishment export audit "
                "schema update to be applied."
            ),
            id="api.E006",
        )
    ]


@register()
def check_dmis_rbac_boundary(app_configs, **kwargs):
    messages = []

    if not getattr(settings, "AUTH_USE_DB_RBAC", False):
        messages.append(
            DjangoWarning(
                "AUTH_USE_DB_RBAC is disabled; DMIS RBAC is expected as the canonical auth source.",
                id="api.W001",
            )
        )
        return messages

    if getattr(settings, "TESTING", False):
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

    # Phase 3 of the Django auth adapter intentionally mirrors custom RBAC
    # into auth_group/auth_permission and the custom-user group M2M. Only
    # auth_user rows indicate drift away from the legacy "user" table.
    django_auth_tables = ["auth_user"]
    populated = []
    for table_name in django_auth_tables:
        count = _count_rows(table_name)
        if count is not None and count > 0:
            populated.append((table_name, count))

    if populated:
        details = ", ".join(f"{name}={count}" for name, count in populated)
        messages.append(
            DjangoWarning(
                "Django auth_user contains rows. "
                "The legacy DMIS user table remains canonical; validate these are not "
                f"business authorization dependencies ({details}).",
                id="api.W002",
            )
        )

    return messages


def _replenishment_export_audit_schema_required() -> bool:
    if bool(getattr(settings, "TESTING", False)):
        return False
    return bool(getattr(settings, "DMIS_WORKER_REQUIRED", False)) or not bool(
        getattr(settings, "DMIS_ASYNC_EAGER", False)
    )


def get_replenishment_export_audit_schema_status() -> tuple[str, str | None]:
    table_name = "needs_list_audit"
    if not _table_exists(table_name):
        return "failed", "Required replenishment audit table needs_list_audit is missing."

    if not _column_exists(table_name, "request_id"):
        return (
            "failed",
            "Queued export durability requires needs_list_audit.request_id to exist; "
            "apply the replenishment export audit schema update.",
        )

    if connection.vendor == "postgresql":
        constraint_sql = _constraint_definition(
            table_name=table_name,
            constraint_name="c_nla_action",
        )
        if constraint_sql is None:
            return (
                "failed",
                "Queued export durability requires the needs_list_audit c_nla_action "
                "constraint to be present and allow EXPORT_GENERATED.",
            )
        if "EXPORT_GENERATED" not in constraint_sql:
            return (
                "failed",
                "Queued export durability requires needs_list_audit.c_nla_action "
                "to allow EXPORT_GENERATED; apply the replenishment export audit schema update.",
            )

    return "ok", None


def _table_exists(table_name: str) -> bool:
    try:
        return table_name in set(connection.introspection.table_names())
    except DatabaseError:
        return False


def _column_exists(table_name: str, column_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    try:
        with connection.cursor() as cursor:
            description = connection.introspection.get_table_description(cursor, table_name)
    except DatabaseError:
        return False

    for column in description:
        if str(getattr(column, "name", "")).strip().lower() == str(column_name).strip().lower():
            return True
    return False


def _constraint_definition(*, table_name: str, constraint_name: str) -> str | None:
    if connection.vendor != "postgresql":
        return None
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT pg_get_constraintdef(c.oid)
                FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                JOIN pg_namespace n ON n.oid = t.relnamespace
                WHERE n.nspname = current_schema()
                  AND t.relname = %s
                  AND c.conname = %s
                """,
                [table_name, constraint_name],
            )
            row = cursor.fetchone()
    except DatabaseError:
        return None

    if not row or not row[0]:
        return None
    return str(row[0])


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

