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

