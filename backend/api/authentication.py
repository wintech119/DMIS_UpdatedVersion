import logging
from dataclasses import dataclass, field
from typing import Optional, Tuple

import jwt
from jwt import InvalidTokenError, PyJWKClient, PyJWKClientError
from django.conf import settings
from django.db import DatabaseError, connection
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

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


def _resolve_dev_override_principal(request) -> Principal | None:
    if not local_auth_harness_enabled():
        return None

    requested = _requested_local_auth_harness_user(request)
    if not requested:
        return None

    allowed_users = _configured_local_auth_harness_users()
    if not allowed_users:
        _log_auth_warning("auth.local_harness_enabled_without_allowlist", request=request)
        return None
    if requested.lower() not in allowed_users:
        _log_auth_warning("auth.local_harness_rejected_non_allowlisted_user", request=request)
        return None

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT user_id, username
                FROM "user"
                WHERE CAST(user_id AS TEXT) = %s OR username = %s OR email = %s
                LIMIT 1
                """,
                [requested, requested, requested],
            )
            row = cursor.fetchone()
    except DatabaseError as exc:
        _log_auth_warning("auth.dev_override_lookup_failed", request=request, exception=exc)
        return None

    if not row:
        _log_auth_warning("auth.dev_override_user_not_found", request=request)
        return None

    user_id = int(row[0])
    roles, permissions = _fetch_dev_override_roles_and_permissions(user_id)

    return Principal(
        user_id=str(user_id),
        username=str(row[1]),
        roles=roles,
        permissions=permissions,
    )


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
        return [], []

    return roles, permissions


class LegacyCompatAuthentication(BaseAuthentication):
    """
    Minimal auth that mirrors legacy patterns. JWT validation is structural only.
    """

    def authenticate(self, request) -> Optional[Tuple[Principal, None]]:
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
            override_principal = _resolve_dev_override_principal(request)
            if override_principal is not None:
                return override_principal, None
            roles = [role for role in settings.DEV_AUTH_ROLES]
            permissions = [perm for perm in settings.DEV_AUTH_PERMISSIONS]
            principal = Principal(
                user_id=str(settings.DEV_AUTH_USER_ID),
                username=str(settings.DEV_AUTH_USER_ID),
                roles=roles,
                permissions=permissions,
            )
            return principal, None

        if not settings.AUTH_ENABLED:
            return None

        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header.startswith("Bearer "):
            raise AuthenticationFailed("Missing bearer token.")

        token = auth_header.replace("Bearer ", "", 1).strip()
        if not token:
            raise AuthenticationFailed("Missing bearer token.")

        payload = _verify_jwt_with_jwks(token, settings.AUTH_JWKS_URL)

        user_id = None
        username = None
        if settings.AUTH_USER_ID_CLAIM:
            user_id = payload.get(settings.AUTH_USER_ID_CLAIM)
        if settings.AUTH_USERNAME_CLAIM:
            username = payload.get(settings.AUTH_USERNAME_CLAIM)

        roles = []
        if settings.AUTH_ROLES_CLAIM:
            roles = _parse_roles(payload.get(settings.AUTH_ROLES_CLAIM))

        principal = Principal(
            user_id=str(user_id) if user_id is not None else None,
            username=str(username) if username is not None else None,
            roles=roles,
        )
        return principal, None

    def authenticate_header(self, request) -> str:
        return "Bearer"
