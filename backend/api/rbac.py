from __future__ import annotations

from typing import Iterable, Tuple

from django.conf import settings
from django.db import DatabaseError, connection
import logging

from api.authentication import Principal

logger = logging.getLogger(__name__)

REQUIRED_PERMISSION = "replenishment.needs_list.preview"
PERM_NEEDS_LIST_CREATE_DRAFT = "replenishment.needs_list.create_draft"
PERM_NEEDS_LIST_EDIT_LINES = "replenishment.needs_list.edit_lines"
PERM_NEEDS_LIST_SUBMIT = "replenishment.needs_list.submit"
PERM_NEEDS_LIST_REVIEW_START = "replenishment.needs_list.review_start"
PERM_NEEDS_LIST_RETURN = "replenishment.needs_list.return"
PERM_NEEDS_LIST_REJECT = "replenishment.needs_list.reject"
PERM_NEEDS_LIST_APPROVE = "replenishment.needs_list.approve"
PERM_NEEDS_LIST_ESCALATE = "replenishment.needs_list.escalate"
PERM_NEEDS_LIST_EXECUTE = "replenishment.needs_list.execute"
PERM_NEEDS_LIST_CANCEL = "replenishment.needs_list.cancel"
PERM_NEEDS_LIST_REVIEW_COMMENTS = "replenishment.needs_list.review_comments"

_DEV_ROLE_PERMISSION_MAP = {
    "LOGISTICS": {
        REQUIRED_PERMISSION,
        PERM_NEEDS_LIST_CREATE_DRAFT,
        PERM_NEEDS_LIST_EDIT_LINES,
        PERM_NEEDS_LIST_SUBMIT,
        PERM_NEEDS_LIST_EXECUTE,
        PERM_NEEDS_LIST_CANCEL,
    },
    "EXECUTIVE": {
        REQUIRED_PERMISSION,
        PERM_NEEDS_LIST_REVIEW_START,
        PERM_NEEDS_LIST_RETURN,
        PERM_NEEDS_LIST_REJECT,
        PERM_NEEDS_LIST_APPROVE,
        PERM_NEEDS_LIST_ESCALATE,
        PERM_NEEDS_LIST_REVIEW_COMMENTS,
    },
}


def _dedupe_preserve_order(items: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(items))


def resolve_roles_and_permissions(
    request, principal: Principal
) -> Tuple[list[str], list[str]]:
    if hasattr(request, "_rbac_cache"):
        cached = request._rbac_cache
        return cached["roles"], cached["permissions"]

    roles: list[str] = list(principal.roles or [])
    permissions: list[str] = list(getattr(principal, "permissions", []) or [])
    db_error = False

    if _db_rbac_enabled():
        try:
            user_id = _resolve_user_id(principal)
            if user_id is not None:
                roles = _dedupe_preserve_order(list(roles) + _fetch_roles(user_id))
                permissions = _dedupe_preserve_order(
                    list(permissions) + list(_fetch_permissions(user_id))
                )
        except DatabaseError as exc:
            db_error = True
            logger.warning("RBAC DB lookup failed: %s", exc)

    if not permissions and not db_error:
        permissions = _dedupe_preserve_order(
            list(permissions) + list(_permissions_for_roles(roles))
        )

    request._rbac_cache = {"roles": roles, "permissions": permissions}
    return roles, permissions


def _db_rbac_enabled() -> bool:
    if not settings.AUTH_USE_DB_RBAC:
        return False
    return settings.DATABASES["default"]["ENGINE"].endswith("postgresql")


def _resolve_user_id(principal: Principal) -> int | None:
    if principal.user_id:
        try:
            return int(principal.user_id)
        except ValueError:
            pass

    if not principal.username:
        return None

    with connection.cursor() as cursor:
        cursor.execute(
            'SELECT user_id FROM "user" WHERE username = %s OR email = %s LIMIT 1',
            [principal.username, principal.username],
        )
        row = cursor.fetchone()
        return int(row[0]) if row else None


def _fetch_roles(user_id: int) -> list[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT DISTINCT r.code
            FROM user_role ur
            JOIN role r ON r.id = ur.role_id
            WHERE ur.user_id = %s
            """,
            [user_id],
        )
        return [row[0] for row in cursor.fetchall()]


def _fetch_permissions(user_id: int) -> set[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT DISTINCT p.resource, p.action
            FROM user_role ur
            JOIN role_permission rp ON rp.role_id = ur.role_id
            JOIN permission p ON p.perm_id = rp.perm_id
            WHERE ur.user_id = %s
            """,
            [user_id],
        )
        return {f"{row[0]}.{row[1]}" for row in cursor.fetchall()}


def _permissions_for_roles(roles: Iterable[str]) -> set[str]:
    permissions: set[str] = set()
    for role in roles:
        permissions |= _DEV_ROLE_PERMISSION_MAP.get(role.upper(), set())
    return permissions
