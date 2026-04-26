from __future__ import annotations

import json

from django.db import migrations


PERMISSION_RESOURCE = "operations.request"
PERMISSION_ACTION = "cancel"
AUTHORIZED_ROLE_CODES = (
    "AGENCY_DISTRIBUTOR",
    "AGENCY_SHELTER",
    "CUSTODIAN",
    "SYSTEM_ADMINISTRATOR",
)
MIGRATION_ACTOR = "mig_0003_cancel"
SCOPE_MARKER = {"seeded_by": MIGRATION_ACTOR}
REQUIRED_TABLES = {"permission", "role", "role_permission"}


def _required_tables_exist(schema_editor, cursor) -> bool:
    existing_tables = set(schema_editor.connection.introspection.table_names(cursor))
    return REQUIRED_TABLES.issubset(existing_tables)


def _permission_id(cursor) -> int | None:
    cursor.execute(
        "SELECT perm_id FROM permission WHERE resource = %s AND action = %s LIMIT 1",
        [PERMISSION_RESOURCE, PERMISSION_ACTION],
    )
    row = cursor.fetchone()
    return int(row[0]) if row else None


def seed_cancel_permission(apps, schema_editor) -> None:
    cursor = schema_editor.connection.cursor()
    if not _required_tables_exist(schema_editor, cursor):
        return

    perm_id = _permission_id(cursor)
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
            """,
            [perm_id, PERMISSION_RESOURCE, PERMISSION_ACTION, MIGRATION_ACTOR, MIGRATION_ACTOR],
        )

    cursor.execute(
        "SELECT id, UPPER(code) FROM role WHERE UPPER(code) IN %s",
        [tuple(AUTHORIZED_ROLE_CODES)],
    )
    roles = [(int(role_id), str(role_code)) for role_id, role_code in cursor.fetchall()]
    scope_json = json.dumps(SCOPE_MARKER)
    for role_id, _role_code in roles:
        cursor.execute(
            "SELECT 1 FROM role_permission WHERE role_id = %s AND perm_id = %s LIMIT 1",
            [role_id, perm_id],
        )
        if cursor.fetchone():
            continue
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
            """,
            [role_id, perm_id, scope_json, MIGRATION_ACTOR, MIGRATION_ACTOR],
        )


def reverse_cancel_permission_seed(apps, schema_editor) -> None:
    cursor = schema_editor.connection.cursor()
    if not _required_tables_exist(schema_editor, cursor):
        return

    perm_id = _permission_id(cursor)
    if perm_id is None:
        return

    cursor.execute(
        """
        DELETE FROM role_permission
        WHERE perm_id = %s
          AND scope_json @> %s::jsonb
        """,
        [perm_id, json.dumps(SCOPE_MARKER)],
    )
    cursor.execute(
        """
        DELETE FROM permission p
        WHERE p.perm_id = %s
          AND p.resource = %s
          AND p.action = %s
          AND p.create_by_id = %s
          AND NOT EXISTS (
              SELECT 1
              FROM role_permission rp
              WHERE rp.perm_id = p.perm_id
          )
        """,
        [perm_id, PERMISSION_RESOURCE, PERMISSION_ACTION, MIGRATION_ACTOR],
    )


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0002_async_job_artifact"),
    ]

    operations = [
        migrations.RunPython(seed_cancel_permission, reverse_cancel_permission_seed),
    ]
