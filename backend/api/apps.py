from __future__ import annotations

import contextvars
import logging
import re
import uuid

from django.apps import AppConfig
from django.conf import settings
from django.utils.deprecation import MiddlewareMixin
from rest_framework.exceptions import AuthenticationFailed, NotAuthenticated, Throttled
from rest_framework.views import exception_handler as drf_exception_handler

runtime_logger = logging.getLogger("dmis.runtime")
request_logger = logging.getLogger("dmis.request")
security_logger = logging.getLogger("dmis.security")

_request_log_context: contextvars.ContextVar[dict[str, str]] = contextvars.ContextVar(
    "dmis_request_log_context",
    default={},
)
_request_id_pattern = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_runtime_posture_logged = False


def _sanitize_request_id(raw_value: object) -> str | None:
    candidate = str(raw_value or "").strip()
    if not candidate:
        return None
    if not _request_id_pattern.fullmatch(candidate):
        return None
    return candidate


def set_request_log_context(*, request_id: str, request_method: str, request_path: str) -> None:
    _request_log_context.set(
        {
            "request_id": request_id,
            "request_method": request_method or "-",
            "request_path": request_path or "-",
        }
    )


def clear_request_log_context() -> None:
    _request_log_context.set({})


def get_request_id(request=None) -> str:
    if request is not None:
        request_id = str(getattr(request, "dmis_request_id", "") or "").strip()
        if request_id:
            return request_id
    return _request_log_context.get({}).get("request_id", "-")


def build_log_extra(request=None, **extra) -> dict[str, object]:
    context = dict(_request_log_context.get({}))
    payload: dict[str, object] = {
        "request_id": context.get("request_id", "-"),
        "request_method": context.get("request_method", "-"),
        "request_path": context.get("request_path", "-"),
    }
    if request is not None:
        payload.update(
            {
                "request_id": get_request_id(request),
                "request_method": str(getattr(request, "method", "") or "-"),
                "request_path": str(getattr(request, "path", "") or "-"),
            }
        )
    for key, value in extra.items():
        if value is None:
            continue
        payload[key] = value
    return payload


class RequestContextLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        context = _request_log_context.get({})
        record.request_id = getattr(record, "request_id", context.get("request_id", "-")) or "-"
        record.request_method = (
            getattr(record, "request_method", context.get("request_method", "-")) or "-"
        )
        record.request_path = (
            getattr(record, "request_path", context.get("request_path", "-")) or "-"
        )
        record.status_code = getattr(record, "status_code", "-") or "-"
        record.event = getattr(record, "event", "-") or "-"
        record.runtime_env = (
            getattr(record, "runtime_env", None)
            or str(getattr(settings, "DMIS_RUNTIME_ENV", "")).strip()
            or "unknown"
        )
        record.dependency = getattr(record, "dependency", "-") or "-"
        record.auth_mode = getattr(record, "auth_mode", "-") or "-"
        record.exception_class = getattr(record, "exception_class", "-") or "-"
        return True


class DmisRequestContextMiddleware(MiddlewareMixin):
    response_header_name = "X-Request-ID"

    def process_request(self, request) -> None:
        request_id = _sanitize_request_id(request.META.get("HTTP_X_REQUEST_ID")) or uuid.uuid4().hex
        request.dmis_request_id = request_id
        set_request_log_context(
            request_id=request_id,
            request_method=str(getattr(request, "method", "") or "-"),
            request_path=str(getattr(request, "path", "") or "-"),
        )

    def process_exception(self, request, exception):
        request._dmis_exception_logged = True
        request_logger.exception(
            "request.unhandled_exception",
            extra=build_log_extra(
                request,
                event="request.unhandled_exception",
                status_code=500,
                exception_class=exception.__class__.__name__,
            ),
        )
        return None

    def process_response(self, request, response):
        request_id = get_request_id(request)
        if request_id and request_id != "-":
            response[self.response_header_name] = request_id
        if (
            response.status_code >= 500
            and not getattr(request, "_dmis_exception_logged", False)
            and not getattr(request, "_dmis_skip_response_error_logging", False)
        ):
            request_logger.error(
                "request.server_error_response",
                extra=build_log_extra(
                    request,
                    event="request.server_error_response",
                    status_code=response.status_code,
                ),
            )
        clear_request_log_context()
        return response


def _auth_mode_from_request(request) -> str:
    if request is None:
        return "unknown"
    authorization = str(request.META.get("HTTP_AUTHORIZATION", "") or "")
    if authorization.startswith("Bearer "):
        return "bearer"
    if request.META.get("HTTP_X_DMIS_LOCAL_USER"):
        return "local-harness-header"
    if request.META.get("HTTP_X_DEV_USER"):
        return "legacy-dev-header"
    return "missing"


def dmis_exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    if response is None:
        return None

    request = context.get("request")
    request_id = get_request_id(request)
    if request_id and request_id != "-":
        response["X-Request-ID"] = request_id

    if isinstance(response.data, dict):
        response.data.setdefault("request_id", request_id)
    else:
        response.data = {
            "detail": response.data,
            "request_id": request_id,
        }

    if isinstance(exc, (AuthenticationFailed, NotAuthenticated)):
        security_logger.warning(
            "auth.request_rejected",
            extra=build_log_extra(
                request,
                event="auth.request_rejected",
                status_code=response.status_code,
                auth_mode=_auth_mode_from_request(request),
                exception_class=exc.__class__.__name__,
            ),
        )
    elif isinstance(exc, Throttled):
        request_logger.warning(
            "request.throttled",
            extra=build_log_extra(
                request,
                event="request.throttled",
                status_code=response.status_code,
                exception_class=exc.__class__.__name__,
            ),
        )

    return response


class ApiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "api"

    def ready(self) -> None:
        # Register Django system checks for auth-boundary guardrails.
        from . import checks  # noqa: F401

        global _runtime_posture_logged
        if _runtime_posture_logged or bool(getattr(settings, "TESTING", False)):
            return

        _runtime_posture_logged = True
        runtime_logger.info(
            (
                "runtime.posture.initialized auth_enabled=%s redis_required=%s "
                "redis_configured=%s cache_backend=%s async_eager=%s "
                "worker_required=%s secure_ssl_redirect=%s "
                "session_cookie_secure=%s csrf_cookie_secure=%s"
            ),
            bool(getattr(settings, "AUTH_ENABLED", False)),
            bool(getattr(settings, "DMIS_REDIS_REQUIRED", False)),
            bool(getattr(settings, "DMIS_REDIS_CONFIGURED", False)),
            str(getattr(settings, "DMIS_DEFAULT_CACHE_BACKEND", "")),
            bool(getattr(settings, "DMIS_ASYNC_EAGER", False)),
            bool(getattr(settings, "DMIS_WORKER_REQUIRED", False)),
            bool(getattr(settings, "SECURE_SSL_REDIRECT", False)),
            bool(getattr(settings, "SESSION_COOKIE_SECURE", False)),
            bool(getattr(settings, "CSRF_COOKIE_SECURE", False)),
            extra={"event": "runtime.posture.initialized"},
        )
