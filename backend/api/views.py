import logging
from typing import Any

from django.conf import settings
from django.core.cache import caches
from django.db import DatabaseError, connection
from django.http import HttpResponse
from django.utils import timezone
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from api.apps import build_log_extra, get_request_id
from api.authentication import LegacyCompatAuthentication, local_auth_harness_enabled
from api.models import AsyncJob
from api.permissions import user_has_required_permission
from api.rbac import resolve_roles_and_permissions
from api.tenancy import resolve_tenant_context, tenant_context_to_dict
from operations import policy as operations_policy

readiness_logger = logging.getLogger("dmis.readiness")


@api_view(["GET"])
def health(request):
    return Response(_liveness_payload(request))


def _liveness_payload(request=None) -> dict[str, str]:
    runtime_env = str(getattr(settings, "DMIS_RUNTIME_ENV", "")).strip() or "unknown"
    payload = {
        "status": "live",
        "runtime_env": runtime_env,
    }
    request_id = get_request_id(request)
    if request_id and request_id != "-":
        payload["request_id"] = request_id
    return payload


def _database_readiness_check() -> tuple[str, str | None]:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError as exc:
        return "failed", f"Database connectivity check failed ({exc.__class__.__name__})."
    return "ok", None


def _redis_readiness_check() -> tuple[str, str | None]:
    redis_required = bool(getattr(settings, "DMIS_REDIS_REQUIRED", False))
    redis_configured = bool(getattr(settings, "DMIS_REDIS_CONFIGURED", False))
    cache_backend = str(getattr(settings, "DMIS_DEFAULT_CACHE_BACKEND", "")).strip()

    if not redis_configured:
        if redis_required:
            return "failed", "Redis is required for this runtime but REDIS_URL is not configured."
        return "skipped", "Redis is optional in local-harness when REDIS_URL is not set."

    if cache_backend != "django_redis.cache.RedisCache":
        return "failed", "The default cache backend is not Redis-backed."

    try:
        default_cache = caches["default"]
        redis_client = default_cache.client.get_client(write=True)
        redis_client.ping()
    except Exception as exc:  # noqa: BLE001 - readiness should fail on any backend/protocol error.
        return "failed", f"Redis connectivity check failed ({exc.__class__.__name__})."

    return "ok", None


def _queue_readiness_check() -> tuple[str, str | None]:
    if bool(getattr(settings, "DMIS_ASYNC_EAGER", False)):
        return "skipped", "Async jobs run eagerly in this runtime."

    if not bool(getattr(settings, "DMIS_WORKER_REQUIRED", False)):
        return "skipped", "Background worker is optional in this runtime."

    if not bool(getattr(settings, "DMIS_REDIS_CONFIGURED", False)):
        return "failed", "Redis-backed queueing is required but REDIS_URL is not configured."

    cache_backend = str(getattr(settings, "DMIS_DEFAULT_CACHE_BACKEND", "")).strip()
    if cache_backend != "django_redis.cache.RedisCache":
        return "failed", "The default cache backend is not Redis-backed."

    try:
        heartbeat = caches["default"].get(getattr(settings, "DMIS_WORKER_HEARTBEAT_KEY", "dmis:worker:heartbeat"))
    except Exception as exc:  # noqa: BLE001 - readiness should fail on any backend/protocol error.
        return "failed", f"Worker heartbeat check failed ({exc.__class__.__name__})."

    if not heartbeat:
        return "failed", "No active worker heartbeat detected."

    return "ok", None


def _readiness_payload(request=None) -> tuple[dict[str, Any], int]:
    database_status, database_reason = _database_readiness_check()
    redis_status, redis_reason = _redis_readiness_check()
    queue_status, queue_reason = _queue_readiness_check()
    redis_required = bool(getattr(settings, "DMIS_REDIS_REQUIRED", False))
    queue_required = bool(getattr(settings, "DMIS_WORKER_REQUIRED", False))

    checks: dict[str, dict[str, Any]] = {
        "database": {
            "required": True,
            "status": database_status,
        },
        "redis": {
            "required": redis_required,
            "status": redis_status,
        },
        "queue": {
            "required": queue_required,
            "status": queue_status,
        },
    }
    if database_reason:
        checks["database"]["reason"] = database_reason
    if redis_reason:
        checks["redis"]["reason"] = redis_reason
    if queue_reason:
        checks["queue"]["reason"] = queue_reason

    runtime_env = str(getattr(settings, "DMIS_RUNTIME_ENV", "")).strip() or "unknown"
    statuses = {check["status"] for check in checks.values()}
    is_ready = "failed" not in statuses
    payload = {
        "status": "ready" if is_ready else "not_ready",
        "runtime_env": runtime_env,
        "checks": checks,
    }
    request_id = get_request_id(request)
    if request_id and request_id != "-":
        payload["request_id"] = request_id
    if not is_ready:
        failing_checks = ",".join(
            sorted(name for name, check in checks.items() if check["status"] == "failed")
        )
        readiness_logger.warning(
            "readiness.not_ready",
            extra=build_log_extra(
                request,
                event="readiness.not_ready",
                status_code=503,
                dependency=failing_checks or "unknown",
            ),
        )
    return payload, 200 if is_ready else 503


@api_view(["GET"])
def health_live(request):
    return Response(_liveness_payload(request))


@api_view(["GET"])
def health_ready(request):
    payload, status_code = _readiness_payload(request)
    if status_code >= 500:
        raw_request = getattr(request, "_request", request)
        raw_request._dmis_skip_response_error_logging = True
    return Response(payload, status=status_code)


def _async_job_status_url(job: AsyncJob) -> str:
    return f"/api/v1/jobs/{job.job_id}"


def _async_job_download_url(job: AsyncJob) -> str:
    return f"/api/v1/jobs/{job.job_id}/download"


def _serialize_async_job(job: AsyncJob) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "job_id": job.job_id,
        "job_type": job.job_type,
        "status": job.status,
        "queued_at": job.queued_at.isoformat() if job.queued_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "expires_at": job.expires_at.isoformat() if job.expires_at else None,
        "retry_count": job.retry_count,
        "max_retries": job.max_retries,
        "error_message": job.error_message,
        "artifact_ready": job.artifact_ready,
        "status_url": _async_job_status_url(job),
    }
    if job.artifact_ready:
        payload["download_url"] = _async_job_download_url(job)
    return payload


def _authorize_async_job(request, job: AsyncJob):
    if job.source_resource_type != AsyncJob.SourceType.NEEDS_LIST:
        return None, Response({"detail": "Not found."}, status=404)

    from replenishment import workflow_store_db
    from replenishment.views import (
        _require_record_scope,
        needs_list_donations_export,
        needs_list_procurement_export,
    )

    if job.job_type == AsyncJob.JobType.NEEDS_LIST_DONATION_EXPORT:
        required_permission = getattr(needs_list_donations_export, "required_permission", None)
    elif job.job_type == AsyncJob.JobType.NEEDS_LIST_PROCUREMENT_EXPORT:
        required_permission = getattr(needs_list_procurement_export, "required_permission", None)
    else:
        return None, Response({"detail": "Not found."}, status=404)

    if not user_has_required_permission(request, request.user, required_permission):
        return None, Response({"detail": "Forbidden."}, status=403)

    record = workflow_store_db.get_record(job.source_resource_id)
    if not record:
        return None, Response({"detail": "Not found."}, status=404)

    scope_error = _require_record_scope(request, record, write=False)
    if scope_error:
        return None, scope_error

    return record, None


@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([IsAuthenticated])
def async_job_status(request, job_id: str):
    try:
        job = AsyncJob.objects.get(job_id=job_id)
    except AsyncJob.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)

    _, auth_error = _authorize_async_job(request, job)
    if auth_error:
        return auth_error

    return Response(_serialize_async_job(job))


@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([IsAuthenticated])
def async_job_download(request, job_id: str):
    try:
        job = AsyncJob.objects.get(job_id=job_id)
    except AsyncJob.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)

    _, auth_error = _authorize_async_job(request, job)
    if auth_error:
        return auth_error

    if job.expires_at and timezone.now() > job.expires_at:
        return Response(
            {
                "job_id": job.job_id,
                "status": job.status,
                "detail": "The job artifact has expired.",
            },
            status=410,
        )

    if not job.artifact_ready:
        return Response(
            {
                "job_id": job.job_id,
                "status": job.status,
                "detail": "The job artifact is not ready.",
            },
            status=409,
        )

    response = HttpResponse(
        job.artifact_payload,
        content_type=job.artifact_content_type or "text/plain",
    )
    filename = str(job.artifact_filename or f"{job.job_id}.txt").replace('"', "")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    if job.artifact_sha256:
        response["ETag"] = job.artifact_sha256
    return response


@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([IsAuthenticated])
def whoami(request):
    roles, permissions = resolve_roles_and_permissions(request, request.user)
    tenant_context = resolve_tenant_context(request, request.user, permissions)
    return Response(
        {
            "user_id": request.user.user_id,
            "username": request.user.username,
            "roles": roles,
            "permissions": sorted(permissions),
            "tenant_context": tenant_context_to_dict(tenant_context),
            "operations_capabilities": operations_policy.get_relief_request_capabilities(
                tenant_context=tenant_context,
                permissions=permissions,
            ),
        }
    )


def _configured_local_auth_harness_usernames() -> list[str]:
    seen: set[str] = set()
    usernames: list[str] = []
    for raw_value in getattr(settings, "LOCAL_AUTH_HARNESS_USERNAMES", []):
        normalized = str(raw_value or "").strip()
        key = normalized.lower()
        if not normalized or key in seen:
            continue
        seen.add(key)
        usernames.append(normalized)
    return usernames


def _load_local_auth_harness_users() -> tuple[list[dict[str, object]], list[str]]:
    configured_usernames = _configured_local_auth_harness_usernames()
    if not configured_usernames:
        return [], []

    placeholders = ", ".join(["%s"] * len(configured_usernames))
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT
                u.user_id,
                u.username,
                u.email,
                r.code,
                t.tenant_id,
                t.tenant_code,
                t.tenant_name,
                t.tenant_type,
                COALESCE(tu.is_primary_tenant, FALSE) AS is_primary_tenant,
                tu.access_level,
                p.resource,
                p.action
            FROM "user" u
            LEFT JOIN user_role ur ON ur.user_id = u.user_id
            LEFT JOIN role r ON r.id = ur.role_id
            LEFT JOIN tenant_user tu
                ON tu.user_id = u.user_id
               AND COALESCE(tu.status_code, 'A') = 'A'
            LEFT JOIN tenant t
                ON t.tenant_id = tu.tenant_id
               AND COALESCE(t.status_code, 'A') = 'A'
            LEFT JOIN role_permission rp ON rp.role_id = ur.role_id
            LEFT JOIN permission p ON p.perm_id = rp.perm_id
            WHERE
                LOWER(COALESCE(u.username, '')) IN ({placeholders})
                AND COALESCE(u.is_active, TRUE) = TRUE
                AND COALESCE(u.status_code, 'A') = 'A'
            ORDER BY
                LOWER(u.username),
                COALESCE(tu.is_primary_tenant, FALSE) DESC,
                t.tenant_id ASC,
                r.code ASC,
                p.resource ASC,
                p.action ASC
            """,
            [value.lower() for value in configured_usernames],
        )
        rows = cursor.fetchall()

    users_by_username: dict[str, dict[str, object]] = {}
    for row in rows:
        username = str(row[1] or "").strip()
        if not username:
            continue
        key = username.lower()
        if key not in users_by_username:
            users_by_username[key] = {
                "user_id": str(row[0]),
                "username": username,
                "email": row[2],
                "roles": set(),
                "permissions": set(),
                "memberships": {},
            }

        role_code = str(row[3] or "").strip()
        if role_code:
            users_by_username[key]["roles"].add(role_code)

        tenant_id = row[4]
        if tenant_id is not None:
            users_by_username[key]["memberships"][int(tenant_id)] = {
                "tenant_id": int(tenant_id),
                "tenant_code": str(row[5] or "").strip() or None,
                "tenant_name": str(row[6] or "").strip() or None,
                "tenant_type": str(row[7] or "").strip() or None,
                "is_primary": bool(row[8]),
                "access_level": str(row[9] or "").strip() or None,
            }

        resource = str(row[10] or "").strip()
        action = str(row[11] or "").strip()
        if resource and action:
            users_by_username[key]["permissions"].add(f"{resource}.{action}")

    order_index = {value.lower(): index for index, value in enumerate(configured_usernames)}
    users = []
    for key, user in sorted(users_by_username.items(), key=lambda item: order_index.get(item[0], 10_000)):
        memberships = sorted(
            user["memberships"].values(),
            key=lambda membership: (
                not bool(membership["is_primary"]),
                membership["tenant_name"] or "",
                membership["tenant_id"],
            ),
        )
        users.append(
            {
                "user_id": user["user_id"],
                "username": user["username"],
                "email": user["email"],
                "roles": sorted(list(user["roles"])),
                "permissions": sorted(list(user["permissions"])),
                "memberships": memberships,
            }
        )

    missing_usernames = [
        username for username in configured_usernames if username.lower() not in users_by_username
    ]
    return users, missing_usernames


def _local_auth_harness_payload() -> dict[str, object]:
    users, missing_usernames = _load_local_auth_harness_users()
    return {
        "enabled": True,
        "mode": "local_dev_only",
        "default_user": str(getattr(settings, "DEV_AUTH_USER_ID", "") or "").strip() or None,
        "header_name": "X-DMIS-Local-User",
        "users": users,
        "missing_usernames": missing_usernames,
        "session_isolation_hint": "Use a separate browser profile or browser per selected local test user.",
    }


@api_view(["GET"])
def local_auth_harness(request):
    if not local_auth_harness_enabled():
        return Response({"detail": "Not found."}, status=404)
    authenticator = LegacyCompatAuthentication()
    auth_result = authenticator.authenticate(request)
    if auth_result is None:
        return Response({"detail": "Authentication credentials were not provided."}, status=401)
    request.user = auth_result[0]
    try:
        payload = _local_auth_harness_payload()
    except DatabaseError:
        readiness_logger.exception(
            "auth.local_harness_lookup_failed",
            extra=build_log_extra(request, event="auth.local_harness_lookup_failed"),
        )
        return Response({"detail": "Local auth harness is temporarily unavailable."}, status=503)
    return Response(payload)
