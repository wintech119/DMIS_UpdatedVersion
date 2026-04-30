import logging
import warnings
from dataclasses import dataclass, field
from typing import Optional, Tuple

import jwt
from jwt import InvalidTokenError, PyJWKClient, PyJWKClientError
from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.db import DatabaseError, connection
from django.utils import timezone
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied

from api.apps import build_log_extra

logger = logging.getLogger("dmis.security")

LOCAL_AUTH_HARNESS_HEADER = "HTTP_X_DMIS_LOCAL_USER"
LEGACY_DEV_AUTH_HEADER = "HTTP_X_DEV_USER"


@dataclass
class Principal:
    user_id: Optional[str]
    username: Optional[str]
    roles: list[str]
    permissions: list[str] = field(default_factory=list)
    is_authenticated: bool = True

    def __post_init__(self) -> None:
        warnings.warn(
            "api.authentication.Principal is deprecated; use accounts.DmisUser instead.",
            DeprecationWarning,
            stacklevel=2,
        )


def _log_auth_warning(
    event: str,
    *,
    request=None,
    exception: Exception | None = None,
    **extra,
) -> None:
    payload = build_log_extra(request, event=event, **extra)
    if exception is not None:
        payload["exception_class"] = exception.__class__.__name__
    logger.warning(event, extra=payload)


def _verify_jwt_with_jwks(token: str, jwks_url: str) -> dict:
    if not jwks_url:
        raise AuthenticationFailed("JWKS URL is not configured.")
    try:
        header = jwt.get_unverified_header(token)
        allowed_algs = getattr(settings, "AUTH_ALGORITHMS", None) or ["RS256"]
        alg = header.get("alg")
        if not alg:
            raise AuthenticationFailed("JWT alg is missing.")
        if alg not in allowed_algs:
            raise AuthenticationFailed("JWT alg is not allowed.")

        jwk_client = PyJWKClient(jwks_url)
        signing_key = jwk_client.get_signing_key_from_jwt(token)

        options = {
            "verify_aud": bool(settings.AUTH_AUDIENCE),
            "verify_iss": bool(settings.AUTH_ISSUER),
        }
        kwargs = {
            "algorithms": allowed_algs,
            "options": options,
        }
        if settings.AUTH_ISSUER:
            kwargs["issuer"] = settings.AUTH_ISSUER
        if settings.AUTH_AUDIENCE:
            kwargs["audience"] = settings.AUTH_AUDIENCE

        payload = jwt.decode(token, signing_key.key, **kwargs)
        if not isinstance(payload, dict):
            raise AuthenticationFailed("Invalid JWT payload.")
        return payload
    except (PyJWKClientError, InvalidTokenError, AuthenticationFailed, ValueError) as exc:
        _log_auth_warning("auth.jwt_verification_failed", exception=exc)
        if isinstance(exc, AuthenticationFailed):
            raise
        raise AuthenticationFailed("Invalid bearer token.") from exc


def _parse_roles(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(role) for role in value]
    if isinstance(value, str):
        if "," in value:
            return [role.strip() for role in value.split(",") if role.strip()]
        return [value]
    return [str(value)]


def _legacy_user_name(value: object) -> str:
    text = str(value or "").strip() or "KEYCLOAK_USER"
    return text[:20]


def _ensure_user_row(user_id, username, email, full_name) -> None:
    from accounts.backends import KeycloakOidcBackend

    KeycloakOidcBackend().sync_user_from_claims(
        user_id=user_id,
        username=username,
        email=email,
        full_name=full_name,
    )


def local_auth_harness_enabled() -> bool:
    return bool(
        settings.LOCAL_AUTH_HARNESS_ENABLED
        and settings.DEV_AUTH_ENABLED
        and settings.DEBUG
        and not settings.AUTH_ENABLED
    )


def _configured_local_auth_harness_users() -> set[str]:
    return {
        str(value or "").strip().lower()
        for value in getattr(settings, "LOCAL_AUTH_HARNESS_USERNAMES", [])
        if str(value or "").strip()
    }


def _requested_local_auth_harness_user(request) -> str:
    return str(request.META.get(LOCAL_AUTH_HARNESS_HEADER, "")).strip()


def _enforce_dev_override_header_policy(request) -> None:
    legacy_header_value = str(request.META.get(LEGACY_DEV_AUTH_HEADER, "")).strip()
    if legacy_header_value:
        _log_auth_warning("auth.rejected_legacy_dev_header", request=request)
        raise AuthenticationFailed(
            "X-Dev-User is no longer supported. Use the local auth harness flow only in explicit local-harness mode."
        )

    local_harness_header_value = _requested_local_auth_harness_user(request)
    if local_harness_header_value and not local_auth_harness_enabled():
        _log_auth_warning(
            "auth.rejected_local_harness_header_outside_local_mode",
            request=request,
        )
        raise AuthenticationFailed(
            "X-DMIS-Local-User is disabled outside DMIS local-harness mode."
        )


def _resolve_dev_override_principal(request):
    requested = _requested_local_auth_harness_user(request)
    if not requested:
        return None

    if not local_auth_harness_enabled():
        _log_auth_warning("auth.local_harness_override_rejected_when_disabled", request=request)
        raise AuthenticationFailed("X-DMIS-Local-User is only allowed in DMIS local-harness mode.")

    allowed_users = _configured_local_auth_harness_users()
    if not allowed_users:
        _log_auth_warning("auth.local_harness_enabled_without_allowlist", request=request)
        raise AuthenticationFailed("X-DMIS-Local-User is enabled, but no local harness users are configured.")
    if requested.lower() not in allowed_users:
        _log_auth_warning("auth.local_harness_rejected_non_allowlisted_user", request=request)
        raise PermissionDenied("X-DMIS-Local-User is not allowlisted for DMIS local-harness mode.")

    from accounts.backends import LocalHarnessBackend

    return LocalHarnessBackend().get_user_by_harness_header(request, requested)


def _build_dev_auth_user(request):
    UserModel = get_user_model()
    user_id = str(settings.DEV_AUTH_USER_ID)
    username = user_id
    now = timezone.now()
    user = UserModel(
        user_id=user_id,
        username=username,
        email=f"{user_id}@dev-auth.dmis.local",
        full_name=username,
        password="",
        user_name=_legacy_user_name(username),
        password_algo="dev",
        is_active=True,
        create_dtime=now,
        update_dtime=now,
    )
    user.bind_auth_context(
        request=request,
        roles=list(settings.DEV_AUTH_ROLES),
        permissions=list(settings.DEV_AUTH_PERMISSIONS),
    )
    return user


def _fetch_dev_override_roles_and_permissions(user_id: int) -> tuple[list[str], list[str]]:
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT DISTINCT r.code
                FROM user_role ur
                JOIN role r ON r.id = ur.role_id
                WHERE ur.user_id = %s
                ORDER BY r.code
                """,
                [int(user_id)],
            )
            roles = [str(row[0]).strip() for row in cursor.fetchall() if str(row[0]).strip()]
            cursor.execute(
                """
                SELECT DISTINCT p.resource, p.action
                FROM user_role ur
                JOIN role_permission rp ON rp.role_id = ur.role_id
                JOIN permission p ON p.perm_id = rp.perm_id
                WHERE ur.user_id = %s
                ORDER BY p.resource, p.action
                """,
                [int(user_id)],
            )
            permissions = [
                f"{row[0]}.{row[1]}"
                for row in cursor.fetchall()
                if str(row[0]).strip() and str(row[1]).strip()
            ]
    except DatabaseError as exc:
        _log_auth_warning("auth.dev_override_role_lookup_failed", exception=exc)
        raise AuthenticationFailed("X-DMIS-Local-User RBAC lookup failed.") from exc

    return roles, permissions


class LegacyCompatAuthentication(BaseAuthentication):
    """
    Minimal auth that mirrors legacy patterns. JWT validation is structural only.
    """

    def authenticate(self, request) -> Optional[Tuple[object, None]]:
        _enforce_dev_override_header_policy(request)

        if settings.DEV_AUTH_ENABLED and settings.AUTH_ENABLED:
            raise AuthenticationFailed(
                "Invalid auth configuration: DEV_AUTH_ENABLED cannot be true when AUTH_ENABLED is true."
            )

        if settings.DEV_AUTH_ENABLED:
            is_testing = getattr(settings, "TESTING", False)
            if is_testing and not getattr(settings, "TEST_DEV_AUTH_ENABLED", False):
                raise AuthenticationFailed(
                    "DEV_AUTH_ENABLED requires TEST_DEV_AUTH_ENABLED=1 during tests to prevent accidental auth bypass."
                )
            if not is_testing and not settings.DEBUG:
                raise AuthenticationFailed(
                    "DEV_AUTH_ENABLED requires DEBUG=1 outside tests to prevent unsafe production use."
                )
            override_user = _resolve_dev_override_principal(request)
            if override_user is not None:
                from accounts.backends import LOCAL_HARNESS_BACKEND_PATH

                django_request = getattr(request, "_request", request)
                login(django_request, override_user, backend=LOCAL_HARNESS_BACKEND_PATH)
                return override_user, None
            return _build_dev_auth_user(request), None

        if not settings.AUTH_ENABLED:
            return None

        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header.startswith("Bearer "):
            raise AuthenticationFailed("Missing bearer token.")

        token = auth_header.replace("Bearer ", "", 1).strip()
        if not token:
            raise AuthenticationFailed("Missing bearer token.")

        from accounts.backends import KeycloakOidcBackend

        user = KeycloakOidcBackend().authenticate(request, jwt=token)
        if user is None:
            raise AuthenticationFailed("Invalid bearer token.")
        return user, None

    def authenticate_header(self, request) -> str:
        return "Bearer"
