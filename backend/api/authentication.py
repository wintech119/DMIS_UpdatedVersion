import logging
from dataclasses import dataclass, field
from typing import Optional, Tuple

import jwt
from jwt import InvalidTokenError, PyJWKClient, PyJWKClientError
from django.conf import settings
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

logger = logging.getLogger(__name__)

@dataclass
class Principal:
    user_id: Optional[str]
    username: Optional[str]
    roles: list[str]
    permissions: list[str] = field(default_factory=list)
    is_authenticated: bool = True


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
        logger.warning("JWT verification failed: %s", exc)
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


class LegacyCompatAuthentication(BaseAuthentication):
    """
    Minimal auth that mirrors legacy patterns. JWT validation is structural only.
    """

    def authenticate(self, request) -> Optional[Tuple[Principal, None]]:
        if settings.DEV_AUTH_ENABLED and settings.AUTH_ENABLED:
            raise AuthenticationFailed(
                "Invalid auth configuration: DEV_AUTH_ENABLED cannot be true when AUTH_ENABLED is true."
            )

        if settings.DEV_AUTH_ENABLED:
            if not settings.DEBUG:
                raise AuthenticationFailed(
                    "DEV_AUTH_ENABLED requires DEBUG=1 to prevent unsafe production use."
                )
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
