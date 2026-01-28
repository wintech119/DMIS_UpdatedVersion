import base64
import json
from dataclasses import dataclass
from typing import Optional, Tuple

from django.conf import settings
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed


@dataclass
class Principal:
    user_id: Optional[str]
    username: Optional[str]
    roles: list[str]
    is_authenticated: bool = True


def _decode_base64url(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _decode_jwt_unverified(token: str) -> dict:
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Token is not a JWT")
    payload = json.loads(_decode_base64url(parts[1]).decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Invalid token payload")
    return payload


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

        try:
            payload = _decode_jwt_unverified(token)
        except ValueError as exc:
            raise AuthenticationFailed("Invalid bearer token.") from exc

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
