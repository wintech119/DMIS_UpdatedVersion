from __future__ import annotations

import json

from django.db import migrations


PERMISSION_RESOURCE = "masterdata.advanced"
PERMISSION_ACTIONS = ("view", "create", "edit", "inactivate")
AUTHORIZED_ROLE_CODES = ("SYSTEM_ADMINISTRATOR",)
MIGRATION_ACTOR = "mig_0004_md_adv"
SCOPE_MARKER = {"seeded_by": MIGRATION_ACTOR}
REQUIRED_TABLES = {"permission", "role", "role_permission"}


def _required_tables_exist(schema_editor, cursor) -> bool:
    existing_tables = set(schema_editor.connection.introspection.table_names(cursor))
    return REQUIRED_TABLES.issubset(existing_tables)


def _permission_id(cursor, action: str) -> int | None:
    cursor.execute(
        "SELECT perm_id FROM permission WHERE resource = %s AND action = %s LIMIT 1",
        [PERMISSION_RESOURCE, action],
    )
    row = cursor.fetchone()
    return int(row[0]) if row else None


def seed_masterdata_advanced_permissions(apps, schema_editor) -> None:
    cursor = schema_editor.connection.cursor()
    if not _required_tables_exist(schema_editor, cursor):
        return

    scope_json = json.dumps(SCOPE_MARKER)
    for action in PERMISSION_ACTIONS:
        perm_id = _permission_id(cursor, action)
        if perm_id is None:
            cursor.execute("LOCK TABLE permission IN EXCLUSIVE MODE")
            cursor.execute("SELECT COALESCE(MAX(perm_id), 0) + 1 FROM permission")
            perm_id = int(cursor.fetchone()[0])
            cursor.execute(
                """
                INSERT INTO permission (
                    perm_id,
                    resource,
                    action,
                    create_by_id,
                    create_dtime,
                    update_by_id,
                    update_dtime,
                    version_nbr
                )
                VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP, %s, CURRENT_TIMESTAMP, 1)
                ON CONFLICT (resource, action) DO NOTHING
                """,
                [perm_id, PERMISSION_RESOURCE, action, MIGRATION_ACTOR, MIGRATION_ACTOR],
            )
            perm_id = _permission_id(cursor, action)
            if perm_id is None:
                continue

        for role_code in AUTHORIZED_ROLE_CODES:
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
                SELECT r.id, p.perm_id, %s::jsonb, %s, CURRENT_TIMESTAMP, %s, CURRENT_TIMESTAMP, 1
                FROM role r
                JOIN permission p ON p.resource = %s AND p.action = %s
                WHERE UPPER(r.code) = %s
                ON CONFLICT (role_id, perm_id) DO NOTHING
                """,
                [
                    scope_json,
                    MIGRATION_ACTOR,
                    MIGRATION_ACTOR,
                    PERMISSION_RESOURCE,
                    action,
                    role_code,
                ],
            )


def reverse_masterdata_advanced_permissions(apps, schema_editor) -> None:
    cursor = schema_editor.connection.cursor()
    if not _required_tables_exist(schema_editor, cursor):
        return

    scope_json = json.dumps(SCOPE_MARKER)
    for action in PERMISSION_ACTIONS:
        cursor.execute(
            """
            DELETE FROM role_permission rp
            USING role r, permission p
            WHERE rp.role_id = r.id
              AND rp.perm_id = p.perm_id
              AND UPPER(r.code) IN %s
              AND p.resource = %s
              AND p.action = %s
              AND rp.scope_json @> %s::jsonb
            """,
            [tuple(AUTHORIZED_ROLE_CODES), PERMISSION_RESOURCE, action, scope_json],
        )
        cursor.execute(
            """
            DELETE FROM permission p
            WHERE p.resource = %s
              AND p.action = %s
              AND p.create_by_id = %s
              AND NOT EXISTS (
                  SELECT 1
                  FROM role_permission rp
                  WHERE rp.perm_id = p.perm_id
              )
            """,
            [PERMISSION_RESOURCE, action, MIGRATION_ACTOR],
        )


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0003_seed_operations_request_cancel_permission"),
    ]

    operations = [
        migrations.RunPython(
            seed_masterdata_advanced_permissions,
            reverse_masterdata_advanced_permissions,
        ),
    ]
