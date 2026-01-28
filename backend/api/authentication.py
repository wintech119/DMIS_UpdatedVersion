import base64
import binascii
import json
import logging
from dataclasses import dataclass
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
    is_authenticated: bool = True


def _decode_base64url(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(value + padding)
    except binascii.Error as exc:
        raise ValueError(f"Invalid JWT payload: {exc}") from exc


def _decode_jwt_unverified(token: str) -> dict:
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Token is not a JWT")
    try:
        payload_text = _decode_base64url(parts[1]).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"Invalid JWT payload: {exc}") from exc
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JWT payload: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Invalid token payload")
    return payload


def _verify_jwt_with_jwks(token: str, jwks_url: str) -> dict:
    if not jwks_url:
        raise AuthenticationFailed("JWKS URL is not configured.")
    try:
        header = jwt.get_unverified_header(token)
        alg = header.get("alg")
        if not alg:
            raise AuthenticationFailed("JWT alg is missing.")

        jwk_client = PyJWKClient(jwks_url)
        signing_key = jwk_client.get_signing_key_from_jwt(token)

        options = {
            "verify_aud": bool(settings.AUTH_AUDIENCE),
            "verify_iss": bool(settings.AUTH_ISSUER),
        }
        kwargs = {
            "algorithms": [alg],
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
        if settings.DEV_AUTH_ENABLED:
            roles = [role for role in settings.DEV_AUTH_ROLES]
            principal = Principal(
                user_id=str(settings.DEV_AUTH_USER_ID),
                username=str(settings.DEV_AUTH_USER_ID),
                roles=roles,
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
