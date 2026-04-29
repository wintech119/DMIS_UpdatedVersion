from __future__ import annotations

import json
import logging
from typing import Any

from django.conf import settings
from django.db import DatabaseError, IntegrityError
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
    throttle_classes,
)
from rest_framework.response import Response

from api.authentication import LegacyCompatAuthentication
from api.rbac import (
    PERM_MASTERDATA_ADVANCED_EDIT,
    PERM_MASTERDATA_ADVANCED_VIEW,
    resolve_roles_and_permissions,
)
from api.tenancy import (
    can_access_tenant,
    resolve_tenant_context,
    tenant_context_to_dict,
)
from masterdata.permissions import MasterDataPermission
from masterdata.services import iam_data_access
from masterdata.throttling import MasterDataWriteThrottle


logger = logging.getLogger(__name__)

TENANT_USER_ACCESS_LEVELS = {"ADMIN", "FULL", "STANDARD", "LIMITED", "READ_ONLY"}


def _principal(request):
    return getattr(request, "principal", None) or getattr(request, "user", None)


def _actor_identity(request) -> str | None:
    principal = _principal(request)
    for attr in ("user_id", "username"):
        value = str(getattr(principal, attr, "") or "").strip()
        if value:
            return value
    return None


def _actor_id(request) -> str:
    return _actor_identity(request) or "system"


def _actor_assignment_audit_id(request) -> int | str | None:
    actor_id = _actor_identity(request)
    if actor_id is None:
        return None
    try:
        return int(actor_id)
    except (TypeError, ValueError):
        return actor_id


def _actor_assignment_audit_id_or_error(request) -> tuple[int | str | None, Response | None]:
    actor_id = _actor_assignment_audit_id(request)
    if actor_id is None:
        return None, Response(
            {"detail": "Authenticated actor identity is required for assignment audit."},
            status=401,
        )
    return actor_id, None


def _should_enforce_tenant_scope() -> bool:
    return bool(getattr(settings, "TENANT_SCOPE_ENFORCEMENT", False))


def _tenant_context(request):
    cached = getattr(request, "_tenant_context_cache", None)
    if cached is not None:
        return cached
    _, permissions = resolve_roles_and_permissions(request, request.user)
    context = resolve_tenant_context(request, request.user, permissions)
    request._tenant_context_cache = context
    return context


def _tenant_scope_denied_response(
    request,
    *,
    write: bool,
    tenant_id: int | None = None,
    user_id: int | None = None,
    role_id: int | None = None,
) -> Response:
    details: dict[str, Any] = {
        "message": "Access denied for tenant scope.",
        "write": bool(write),
        "tenant_context": tenant_context_to_dict(_tenant_context(request)),
    }
    if tenant_id is not None:
        details["tenant_id"] = tenant_id
    if user_id is not None:
        details["user_id"] = user_id
    if role_id is not None:
        details["role_id"] = role_id
    return Response({"errors": {"tenant_scope": details}}, status=403)


def _require_tenant_scope(request, tenant_id: int, *, write: bool) -> Response | None:
    if not _should_enforce_tenant_scope():
        return None
    context = _tenant_context(request)
    if can_access_tenant(context, tenant_id, write=write):
        return None
    return _tenant_scope_denied_response(request, tenant_id=tenant_id, write=write)


def _require_active_tenant_scope(
    request,
    *,
    write: bool,
    role_id: int | None = None,
) -> Response | None:
    if not _should_enforce_tenant_scope():
        return None
    context = _tenant_context(request)
    if context.active_tenant_id is not None and can_access_tenant(
        context,
        context.active_tenant_id,
        write=write,
    ):
        return None
    return _tenant_scope_denied_response(request, role_id=role_id, write=write)


def _require_user_scope(request, user_id: int, *, write: bool) -> Response | None:
    if not _should_enforce_tenant_scope():
        return None
    target_tenant_ids = iam_data_access.list_user_active_tenant_ids(user_id)
    if not target_tenant_ids:
        return _tenant_scope_denied_response(request, user_id=user_id, write=write)
    context = _tenant_context(request)
    if all(can_access_tenant(context, tenant_id, write=write) for tenant_id in target_tenant_ids):
        return None
    return _tenant_scope_denied_response(request, user_id=user_id, write=write)


def _positive_int(value: Any, field_name: str) -> tuple[int | None, Response | None]:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None, _field_error(field_name, f"{field_name} must be a positive integer.")
    if parsed <= 0:
        return None, _field_error(field_name, f"{field_name} must be a positive integer.")
    return parsed, None


def _payload_positive_int(data: dict[str, Any], field_name: str) -> tuple[int | None, Response | None]:
    if field_name not in data:
        return None, _field_error(field_name, f"{field_name} is required.")
    return _positive_int(data.get(field_name), field_name)


def _query_positive_int(request, field_name: str) -> tuple[int | None, Response | None]:
    value = request.query_params.get(field_name)
    if value is None:
        return None, _field_error(field_name, f"{field_name} is required.")
    return _positive_int(value, field_name)


def _field_error(field_name: str, message: str, status: int = 400) -> Response:
    return Response({"errors": {field_name: message}}, status=status)


def _integrity_error_response() -> Response:
    return Response(
        {"detail": "Assignment references an unknown or invalid record."},
        status=400,
    )


def _db_error_response() -> Response:
    return Response({"detail": "Failed to process assignment."}, status=500)


def _post_response(created: bool) -> Response:
    return Response({"created": created}, status=201 if created else 200)


def _log_success(action: str, table: str, request, payload: dict[str, Any]) -> None:
    logger.info(
        "masterdata.advanced.%s: %s by user_id=%s payload=%s",
        action,
        table,
        _actor_id(request),
        payload,
    )


def _validated_scope_json(data: dict[str, Any]) -> tuple[Any, Response | None]:
    if "scope_json" not in data or data.get("scope_json") is None:
        return None, None
    scope_json = data.get("scope_json")
    try:
        json.dumps(scope_json)
    except (TypeError, ValueError):
        return None, _field_error("scope_json", "scope_json must be JSON serializable.")
    return scope_json, None


def _validated_access_level(data: dict[str, Any]) -> tuple[str | None, Response | None]:
    raw_value = str(data.get("access_level") or "").strip().upper()
    if not raw_value:
        return None, _field_error("access_level", "access_level is required.")
    if raw_value not in TENANT_USER_ACCESS_LEVELS:
        return None, _field_error(
            "access_level",
            "access_level must be one of: ADMIN, FULL, STANDARD, LIMITED, READ_ONLY.",
        )
    return raw_value, None


@api_view(["GET", "POST", "DELETE"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([MasterDataPermission])
@throttle_classes([MasterDataWriteThrottle])
def user_roles(request, user_id: int):
    if user_id <= 0:
        return _field_error("user_id", "user_id must be a positive integer.")

    try:
        if request.method == "GET":
            scope_error = _require_user_scope(request, user_id, write=False)
            if scope_error:
                return scope_error
            return Response({"results": iam_data_access.list_user_roles(user_id)})

        if request.method == "POST":
            data = dict(request.data or {})
            role_id, error = _payload_positive_int(data, "role_id")
            if error:
                return error
            scope_error = _require_user_scope(request, user_id, write=True)
            if scope_error:
                return scope_error
            actor_audit_id, actor_error = _actor_assignment_audit_id_or_error(request)
            if actor_error:
                return actor_error
            created = iam_data_access.assign_user_role(user_id, role_id, actor_audit_id)
            _log_success(
                "assign",
                "user_role",
                request,
                {"user_id": user_id, "role_id": role_id, "created": created},
            )
            return _post_response(created)

        role_id, error = _query_positive_int(request, "role_id")
        if error:
            return error
        scope_error = _require_user_scope(request, user_id, write=True)
        if scope_error:
            return scope_error
        deleted = iam_data_access.revoke_user_role(user_id, role_id)
        if not deleted:
            return Response({"detail": "Assignment not found."}, status=404)
        _log_success("revoke", "user_role", request, {"user_id": user_id, "role_id": role_id})
        return Response(status=204)
    except IntegrityError:
        logger.warning("user_role assignment integrity failure", exc_info=True)
        return _integrity_error_response()
    except DatabaseError:
        logger.exception("user_role assignment failed")
        return _db_error_response()


user_roles.required_permission = {
    "GET": PERM_MASTERDATA_ADVANCED_VIEW,
    "POST": PERM_MASTERDATA_ADVANCED_EDIT,
    "DELETE": PERM_MASTERDATA_ADVANCED_EDIT,
}


@api_view(["GET", "POST", "DELETE"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([MasterDataPermission])
@throttle_classes([MasterDataWriteThrottle])
def role_permissions(request, role_id: int):
    if role_id <= 0:
        return _field_error("role_id", "role_id must be a positive integer.")

    try:
        if request.method == "GET":
            scope_error = _require_active_tenant_scope(request, role_id=role_id, write=False)
            if scope_error:
                return scope_error
            return Response({"results": iam_data_access.list_role_permissions(role_id)})

        if request.method == "POST":
            data = dict(request.data or {})
            perm_id, error = _payload_positive_int(data, "perm_id")
            if error:
                return error
            scope_json, scope_error = _validated_scope_json(data)
            if scope_error:
                return scope_error
            scope_error = _require_active_tenant_scope(request, role_id=role_id, write=True)
            if scope_error:
                return scope_error
            created = iam_data_access.assign_role_permission(
                role_id,
                perm_id,
                _actor_id(request),
                scope_json,
            )
            _log_success(
                "assign",
                "role_permission",
                request,
                {
                    "role_id": role_id,
                    "perm_id": perm_id,
                    "scope_json": scope_json,
                    "created": created,
                },
            )
            return _post_response(created)

        perm_id, error = _query_positive_int(request, "perm_id")
        if error:
            return error
        scope_error = _require_active_tenant_scope(request, role_id=role_id, write=True)
        if scope_error:
            return scope_error
        deleted = iam_data_access.revoke_role_permission(role_id, perm_id)
        if not deleted:
            return Response({"detail": "Assignment not found."}, status=404)
        _log_success("revoke", "role_permission", request, {"role_id": role_id, "perm_id": perm_id})
        return Response(status=204)
    except IntegrityError:
        logger.warning("role_permission assignment integrity failure", exc_info=True)
        return _integrity_error_response()
    except DatabaseError:
        logger.exception("role_permission assignment failed")
        return _db_error_response()


role_permissions.required_permission = user_roles.required_permission


@api_view(["GET", "POST", "DELETE"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([MasterDataPermission])
@throttle_classes([MasterDataWriteThrottle])
def tenant_users(request, tenant_id: int):
    if tenant_id <= 0:
        return _field_error("tenant_id", "tenant_id must be a positive integer.")

    try:
        if request.method == "GET":
            scope_error = _require_tenant_scope(request, tenant_id, write=False)
            if scope_error:
                return scope_error
            return Response({"results": iam_data_access.list_tenant_users(tenant_id)})

        if request.method == "POST":
            data = dict(request.data or {})
            user_id, error = _payload_positive_int(data, "user_id")
            if error:
                return error
            access_level, access_error = _validated_access_level(data)
            if access_error:
                return access_error
            scope_error = _require_tenant_scope(request, tenant_id, write=True)
            if scope_error:
                return scope_error
            actor_audit_id, actor_error = _actor_assignment_audit_id_or_error(request)
            if actor_error:
                return actor_error
            created = iam_data_access.assign_tenant_user(
                tenant_id,
                user_id,
                access_level,
                actor_audit_id,
            )
            _log_success(
                "assign",
                "tenant_user",
                request,
                {
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "access_level": access_level,
                    "created": created,
                },
            )
            return _post_response(created)

        user_id, error = _query_positive_int(request, "user_id")
        if error:
            return error
        scope_error = _require_tenant_scope(request, tenant_id, write=True)
        if scope_error:
            return scope_error
        deleted = iam_data_access.revoke_tenant_user(tenant_id, user_id)
        if not deleted:
            return Response({"detail": "Assignment not found."}, status=404)
        _log_success("revoke", "tenant_user", request, {"tenant_id": tenant_id, "user_id": user_id})
        return Response(status=204)
    except IntegrityError:
        logger.warning("tenant_user assignment integrity failure", exc_info=True)
        return _integrity_error_response()
    except DatabaseError:
        logger.exception("tenant_user assignment failed")
        return _db_error_response()


tenant_users.required_permission = user_roles.required_permission


@api_view(["GET", "POST", "DELETE"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([MasterDataPermission])
@throttle_classes([MasterDataWriteThrottle])
def tenant_user_roles(request, tenant_id: int, user_id: int):
    if tenant_id <= 0:
        return _field_error("tenant_id", "tenant_id must be a positive integer.")
    if user_id <= 0:
        return _field_error("user_id", "user_id must be a positive integer.")

    try:
        if request.method == "GET":
            scope_error = _require_tenant_scope(request, tenant_id, write=False)
            if scope_error:
                return scope_error
            return Response({"results": iam_data_access.list_user_tenant_roles(tenant_id, user_id)})

        if request.method == "POST":
            data = dict(request.data or {})
            role_id, error = _payload_positive_int(data, "role_id")
            if error:
                return error
            scope_error = _require_tenant_scope(request, tenant_id, write=True)
            if scope_error:
                return scope_error
            actor_audit_id, actor_error = _actor_assignment_audit_id_or_error(request)
            if actor_error:
                return actor_error
            created = iam_data_access.assign_user_tenant_role(
                tenant_id,
                user_id,
                role_id,
                actor_audit_id,
            )
            _log_success(
                "assign",
                "user_tenant_role",
                request,
                {
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "role_id": role_id,
                    "created": created,
                },
            )
            return _post_response(created)

        role_id, error = _query_positive_int(request, "role_id")
        if error:
            return error
        scope_error = _require_tenant_scope(request, tenant_id, write=True)
        if scope_error:
            return scope_error
        deleted = iam_data_access.revoke_user_tenant_role(tenant_id, user_id, role_id)
        if not deleted:
            return Response({"detail": "Assignment not found."}, status=404)
        _log_success(
            "revoke",
            "user_tenant_role",
            request,
            {"tenant_id": tenant_id, "user_id": user_id, "role_id": role_id},
        )
        return Response(status=204)
    except IntegrityError:
        logger.warning("user_tenant_role assignment integrity failure", exc_info=True)
        return _integrity_error_response()
    except DatabaseError:
        logger.exception("user_tenant_role assignment failed")
        return _db_error_response()


tenant_user_roles.required_permission = user_roles.required_permission


for _view in (
    user_roles,
    role_permissions,
    tenant_users,
    tenant_user_roles,
):
    if hasattr(_view, "cls"):
        _view.cls.required_permission = _view.required_permission
