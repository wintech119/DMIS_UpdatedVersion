from __future__ import annotations

import hashlib
import logging
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import BaseBackend, ModelBackend
from django.core.cache import cache
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.db import DatabaseError
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed

from api.authentication import (
    _fetch_dev_override_roles_and_permissions,
    _legacy_user_name,
    _log_auth_warning,
    _parse_roles,
    _verify_jwt_with_jwks,
)

logger = logging.getLogger("dmis.security")

LOCAL_HARNESS_BACKEND_PATH = "accounts.backends.LocalHarnessBackend"
LOGIN_THROTTLE_LIMIT = 5
LOGIN_THROTTLE_WINDOW_SECONDS = 15 * 60


def _client_ip(request) -> str:
    if request is None:
        return "-"
    return str(request.META.get("REMOTE_ADDR", "") or "-").strip() or "-"


def _normalise_claim(value: object, fallback: str = "") -> str:
    return str(value or "").strip() or fallback


def _principal_shape_user(user, *, request=None, roles=None, permissions=None):
    if getattr(user, "user_id", None) is not None:
        user.user_id = str(user.user_id)
    if hasattr(user, "bind_auth_context"):
        user.bind_auth_context(request=request, roles=roles or [], permissions=permissions or [])
    return user


class KeycloakOidcBackend(BaseBackend):
    """Validates Keycloak/OIDC JWTs and returns the matching DMIS user."""

    def authenticate(self, request, jwt: str | None = None, **kwargs):
        if jwt is None and self._has_password_credentials(kwargs):
            return None

        token = jwt or self._bearer_token_from_request(request)
        if not token:
            return None

        try:
            payload = _verify_jwt_with_jwks(token, settings.AUTH_JWKS_URL)
        except AuthenticationFailed:
            return None

        user_id = payload.get(settings.AUTH_USER_ID_CLAIM) if settings.AUTH_USER_ID_CLAIM else None
        username = payload.get(settings.AUTH_USERNAME_CLAIM) if settings.AUTH_USERNAME_CLAIM else None
        roles = _parse_roles(payload.get(settings.AUTH_ROLES_CLAIM)) if settings.AUTH_ROLES_CLAIM else []
        email = payload.get("email")
        full_name = self._full_name_from_payload(payload, username)
        user = self.sync_user_from_claims(
            user_id=user_id,
            username=username,
            email=email,
            full_name=full_name,
        )
        return _principal_shape_user(user, request=request, roles=roles, permissions=[])

    def get_user(self, user_id):
        UserModel = get_user_model()
        return UserModel.objects.filter(pk=user_id).first()

    def _has_password_credentials(self, credentials: dict[str, Any]) -> bool:
        UserModel = get_user_model()
        username_field = getattr(UserModel, "USERNAME_FIELD", "username")
        return any(key in credentials for key in ("username", username_field, "password"))

    def sync_user_from_claims(self, *, user_id: Any, username: Any, email: Any, full_name: Any):
        UserModel = get_user_model()
        normalized_user_id = _normalise_claim(user_id)
        normalized_username = _normalise_claim(username, normalized_user_id)
        normalized_email = _normalise_claim(email, f"{normalized_user_id}@keycloak.dmis.local")
        normalized_full_name = _normalise_claim(full_name, normalized_username)

        if not normalized_user_id or not getattr(settings, "AUTH_USE_DB_RBAC", False):
            return self._unsaved_claim_user(
                normalized_user_id=normalized_user_id,
                normalized_username=normalized_username,
                normalized_email=normalized_email,
                normalized_full_name=normalized_full_name,
            )

        now = timezone.now()
        defaults: dict[str, Any] = {
            "username": normalized_username,
            "email": normalized_email,
            "full_name": normalized_full_name,
            "update_dtime": now,
        }
        try:
            existing = UserModel.objects.filter(pk=normalized_user_id).first()
            if existing is None:
                defaults.update(
                    {
                        "password": "",
                        "user_name": _legacy_user_name(normalized_username),
                        "password_algo": "argon2id",
                        "mfa_enabled": False,
                        "failed_login_count": 0,
                        "status_code": "A",
                        "version_nbr": 1,
                        "login_count": 0,
                        "is_active": True,
                        "timezone": "America/Jamaica",
                        "language": "en",
                        "create_dtime": now,
                    }
                )
            user, created = UserModel.objects.update_or_create(
                user_id=normalized_user_id,
                defaults=defaults,
            )
            if created:
                logger.info(
                    "Auto-provisioned DMIS user row for user_id=%s username=%s",
                    normalized_user_id,
                    normalized_username,
                )
            return user
        except (DatabaseError, TypeError, ValueError):
            logger.exception(
                "Failed to auto-provision DMIS user row for user_id=%s username=%s",
                normalized_user_id,
                normalized_username,
            )
            return self._unsaved_claim_user(
                normalized_user_id=normalized_user_id,
                normalized_username=normalized_username,
                normalized_email=normalized_email,
                normalized_full_name=normalized_full_name,
            )

    def _unsaved_claim_user(
        self,
        *,
        normalized_user_id: str,
        normalized_username: str,
        normalized_email: str,
        normalized_full_name: str,
    ):
        UserModel = get_user_model()
        now = timezone.now()
        return UserModel(
            user_id=normalized_user_id or None,
            username=normalized_username or None,
            email=normalized_email,
            full_name=normalized_full_name,
            password="",
            user_name=_legacy_user_name(normalized_username),
            password_algo="argon2id",
            is_active=True,
            create_dtime=now,
            update_dtime=now,
        )

    def _full_name_from_payload(self, payload: dict[str, Any], username: Any) -> str:
        full_name = _normalise_claim(payload.get("name"))
        if full_name:
            return full_name
        given_name = _normalise_claim(payload.get("given_name"))
        family_name = _normalise_claim(payload.get("family_name"))
        return " ".join(part for part in (given_name, family_name) if part) or _normalise_claim(username)

    def _bearer_token_from_request(self, request) -> str | None:
        if request is None:
            return None
        auth_header = str(request.META.get("HTTP_AUTHORIZATION", "") or "")
        if not auth_header.startswith("Bearer "):
            return None
        token = auth_header.replace("Bearer ", "", 1).strip()
        return token or None


class LocalHarnessBackend(ModelBackend):
    """Username/password and local-harness lookup against the existing user table."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        UserModel = get_user_model()
        username = username or kwargs.get(UserModel.USERNAME_FIELD)
        username = str(username or "").strip()
        if not username:
            return None

        self._check_login_throttle(request, username, django_auth=True)
        user = super().authenticate(request, username=username, password=password, **kwargs)
        if user is None:
            self._record_login_failure(request, username)
            return None

        self._reset_login_throttle(request, username)
        return _principal_shape_user(user, request=request, roles=[], permissions=[])

    def get_user_by_harness_header(self, request, username: str):
        requested = str(username or "").strip()
        if not requested:
            return None

        self._check_login_throttle(request, requested)
        UserModel = get_user_model()
        try:
            query = Q(username=requested) | Q(email=requested)
            if requested.isdigit():
                query |= Q(pk=int(requested))
            user = UserModel.objects.filter(query).first()
        except DatabaseError as exc:
            self._record_login_failure(request, requested)
            _log_auth_warning("auth.dev_override_lookup_failed", request=request, exception=exc)
            raise AuthenticationFailed("X-DMIS-Local-User could not be resolved safely.") from exc

        if user is None:
            self._record_login_failure(request, requested)
            _log_auth_warning("auth.dev_override_user_not_found", request=request)
            raise AuthenticationFailed("X-DMIS-Local-User did not match a configured local harness user.")

        try:
            roles, permissions = _fetch_dev_override_roles_and_permissions(int(user.user_id))
        except AuthenticationFailed:
            self._record_login_failure(request, requested)
            raise

        self._reset_login_throttle(request, requested)
        return _principal_shape_user(user, request=request, roles=roles, permissions=permissions)

    def _cache_key(self, request, username: str) -> str:
        account = str(username or "").strip().lower() or "unknown"
        raw_key = f"{account}|{_client_ip(request)}"
        digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        return f"dmis:auth:login-attempts:{digest}"

    def _check_login_throttle(self, request, username: str, *, django_auth: bool = False) -> None:
        key = self._cache_key(request, username)
        attempts = int(cache.get(key, 0) or 0)
        if attempts < LOGIN_THROTTLE_LIMIT:
            return
        _log_auth_warning(
            "auth.login_throttled",
            request=request,
            auth_mode="local-harness",
        )
        if django_auth:
            raise DjangoPermissionDenied("Too many login attempts. Try again later.")
        raise AuthenticationFailed("Too many login attempts. Try again later.")

    def _record_login_failure(self, request, username: str) -> None:
        key = self._cache_key(request, username)
        attempts = int(cache.get(key, 0) or 0) + 1
        cache.set(key, attempts, timeout=LOGIN_THROTTLE_WINDOW_SECONDS)

    def _reset_login_throttle(self, request, username: str) -> None:
        cache.delete(self._cache_key(request, username))
