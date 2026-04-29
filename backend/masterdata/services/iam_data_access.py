from __future__ import annotations

import json
from typing import Any

from django.db import connection


def _fetchall_dicts(cursor) -> list[dict[str, Any]]:
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _actor_label(actor_id: Any) -> str:
    return str(actor_id or "system")[:20]


def _assigned_by_value(actor_id: Any) -> int | None:
    try:
        return int(actor_id)
    except (TypeError, ValueError):
        return None


def _jsonb_param(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value)


def list_user_roles(user_id: int) -> list[dict[str, Any]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                ur.role_id,
                r.code,
                r.name,
                ur.assigned_at
            FROM user_role ur
            JOIN role r ON r.id = ur.role_id
            WHERE ur.user_id = %s
            ORDER BY r.code
            """,
            [user_id],
        )
        return _fetchall_dicts(cursor)


def assign_user_role(user_id: int, role_id: int, assigned_by: Any) -> bool:
    actor_label = _actor_label(assigned_by)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO user_role (
                user_id,
                role_id,
                assigned_by,
                create_by_id,
                create_dtime,
                update_by_id,
                update_dtime,
                version_nbr
            )
            VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP, %s, CURRENT_TIMESTAMP, 1)
            ON CONFLICT (user_id, role_id) DO NOTHING
            """,
            [user_id, role_id, _assigned_by_value(assigned_by), actor_label, actor_label],
        )
        return cursor.rowcount > 0


def revoke_user_role(user_id: int, role_id: int) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            DELETE FROM user_role
            WHERE user_id = %s
              AND role_id = %s
            """,
            [user_id, role_id],
        )
        return cursor.rowcount > 0


def list_role_permissions(role_id: int) -> list[dict[str, Any]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                rp.perm_id,
                p.resource,
                p.action,
                rp.scope_json
            FROM role_permission rp
            JOIN permission p ON p.perm_id = rp.perm_id
            WHERE rp.role_id = %s
            ORDER BY p.resource, p.action
            """,
            [role_id],
        )
        return _fetchall_dicts(cursor)


def assign_role_permission(
    role_id: int,
    perm_id: int,
    actor_id: Any,
    scope_json: Any = None,
) -> bool:
    actor_label = _actor_label(actor_id)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO role_permission (
                role_id,
                perm_id,
                scope_json,
                create_by_id,
                create_dtime,
                update_by_id,
                update_dtime,
                version_nbr
            )
            VALUES (%s, %s, %s::jsonb, %s, CURRENT_TIMESTAMP, %s, CURRENT_TIMESTAMP, 1)
            ON CONFLICT (role_id, perm_id) DO NOTHING
            """,
            [role_id, perm_id, _jsonb_param(scope_json), actor_label, actor_label],
        )
        return cursor.rowcount > 0


def revoke_role_permission(role_id: int, perm_id: int) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            DELETE FROM role_permission
            WHERE role_id = %s
              AND perm_id = %s
            """,
            [role_id, perm_id],
        )
        return cursor.rowcount > 0


def list_tenant_users(tenant_id: int) -> list[dict[str, Any]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                tu.user_id,
                u.username,
                u.email,
                tu.access_level,
                tu.is_primary_tenant,
                u.last_login_at
            FROM tenant_user tu
            JOIN "user" u ON u.user_id = tu.user_id
            WHERE tu.tenant_id = %s
              AND tu.status_code = 'A'
            ORDER BY u.username NULLS LAST, u.email
            """,
            [tenant_id],
        )
        return _fetchall_dicts(cursor)


def list_user_active_tenant_ids(user_id: int) -> list[int]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT tu.tenant_id
            FROM tenant_user tu
            JOIN tenant t ON t.tenant_id = tu.tenant_id
            WHERE tu.user_id = %s
              AND COALESCE(tu.status_code, 'A') = 'A'
              AND COALESCE(t.status_code, 'A') = 'A'
            ORDER BY tu.tenant_id
            """,
            [user_id],
        )
        return [int(row[0]) for row in cursor.fetchall()]


def assign_tenant_user(
    tenant_id: int,
    user_id: int,
    access_level: str,
    assigned_by: Any,
    *,
    is_primary_tenant: bool = False,
) -> bool:
    actor_label = _actor_label(assigned_by)
    assigned_by_value = _assigned_by_value(assigned_by)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            WITH inserted AS (
                INSERT INTO tenant_user (
                    tenant_id,
                    user_id,
                    is_primary_tenant,
                    access_level,
                    assigned_by,
                    status_code,
                    create_by_id,
                    create_dtime
                )
                VALUES (%s, %s, %s, %s, %s, 'A', %s, CURRENT_TIMESTAMP)
                ON CONFLICT (tenant_id, user_id) DO NOTHING
                RETURNING TRUE AS created
            ),
            updated AS (
                UPDATE tenant_user
                SET
                    access_level = %s,
                    assigned_by = %s,
                    assigned_at = CURRENT_TIMESTAMP,
                    status_code = 'A'
                WHERE tenant_id = %s
                  AND user_id = %s
                  AND NOT EXISTS (SELECT 1 FROM inserted)
                RETURNING FALSE AS created
            )
            SELECT created FROM inserted
            UNION ALL
            SELECT created FROM updated
            """,
            [
                tenant_id,
                user_id,
                is_primary_tenant,
                access_level,
                assigned_by_value,
                actor_label,
                access_level,
                assigned_by_value,
                tenant_id,
                user_id,
            ],
        )
        row = cursor.fetchone()
        return bool(row[0]) if row else False


def has_active_primary_tenant_membership(tenant_id: int, user_id: int) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT 1
            FROM tenant_user
            WHERE tenant_id = %s
              AND user_id = %s
              AND is_primary_tenant = true
              AND status_code = 'A'
            LIMIT 1
            """,
            [tenant_id, user_id],
        )
        return cursor.fetchone() is not None


def count_active_primary_tenant_memberships(user_id: int) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM tenant_user
            WHERE user_id = %s
              AND is_primary_tenant = true
              AND status_code = 'A'
            """,
            [user_id],
        )
        return int(cursor.fetchone()[0])


def revoke_tenant_user(tenant_id: int, user_id: int) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            DELETE FROM tenant_user
            WHERE tenant_id = %s
              AND user_id = %s
            """,
            [tenant_id, user_id],
        )
        return cursor.rowcount > 0


def list_user_tenant_roles(tenant_id: int, user_id: int) -> list[dict[str, Any]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                utr.role_id,
                r.code,
                r.name
            FROM user_tenant_role utr
            JOIN role r ON r.id = utr.role_id
            WHERE utr.tenant_id = %s
              AND utr.user_id = %s
              AND utr.status_code = 'A'
            ORDER BY r.code
            """,
            [tenant_id, user_id],
        )
        return _fetchall_dicts(cursor)


def assign_user_tenant_role(
    tenant_id: int,
    user_id: int,
    role_id: int,
    assigned_by: Any,
) -> bool:
    actor_label = _actor_label(assigned_by)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO user_tenant_role (
                tenant_id,
                user_id,
                role_id,
                assigned_by,
                status_code,
                create_by_id,
                create_dtime,
                update_by_id,
                update_dtime,
                version_nbr
            )
            VALUES (%s, %s, %s, %s, 'A', %s, CURRENT_TIMESTAMP, %s, CURRENT_TIMESTAMP, 1)
            ON CONFLICT (tenant_id, user_id, role_id) DO NOTHING
            """,
            [
                tenant_id,
                user_id,
                role_id,
                _assigned_by_value(assigned_by),
                actor_label,
                actor_label,
            ],
        )
        return cursor.rowcount > 0


def revoke_user_tenant_role(tenant_id: int, user_id: int, role_id: int) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            DELETE FROM user_tenant_role
            WHERE tenant_id = %s
              AND user_id = %s
              AND role_id = %s
            """,
            [tenant_id, user_id, role_id],
        )
        return cursor.rowcount > 0
