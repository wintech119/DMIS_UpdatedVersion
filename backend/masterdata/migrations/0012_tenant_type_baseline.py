from __future__ import annotations

import os
import re

from django.db import migrations


_SYSTEM_ACTOR_ID = "system"
_SCHEMA_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

_BASELINE_TENANT_TYPES = (
    (
        "NATIONAL",
        "National Coordination",
        "ODPEM and NEOC national coordination functions.",
        10,
    ),
    (
        "MILITARY",
        "Military",
        "Jamaica Defence Force and other approved military coordination tenants.",
        20,
    ),
    ("SOCIAL_SERVICES", "Social Services", "MLSS and social-services coordination entities.", 30),
    ("PARISH", "Parish", "Parish Councils and parish disaster offices.", 40),
    (
        "COMMUNITY",
        "Community",
        "Community-level entities or distribution points under a parent tenant.",
        50,
    ),
    ("NGO", "NGO", "Aid organizations and humanitarian NGOs.", 60),
    ("UTILITY", "Utility", "JPS, NWC, NWA, telecoms, and similar lifeline operators.", 70),
    ("SHELTER_OPERATOR", "Shelter Operator", "Organizations directly managing shelters.", 80),
    ("PARTNER", "Partner", "Other approved platform agencies and entities.", 90),
)
_BASELINE_CODES = tuple(row[0] for row in _BASELINE_TENANT_TYPES)
_RETIRED_CODES = (
    "NEOC",
    "NATIONAL_LEVEL",
    "AGENCY",
    "OTHER",
    "PUBLIC",
    "MINISTRY",
    "EXTERNAL",
    "INFRASTRUCTURE",
    "SHELTER",
)


def _is_postgres(schema_editor) -> bool:
    return schema_editor.connection.vendor == "postgresql"


def _schema_name(schema_editor) -> str:
    configured = os.getenv("DMIS_DB_SCHEMA")
    if configured is not None:
        if not _SCHEMA_RE.fullmatch(configured):
            raise RuntimeError(f"Invalid DMIS_DB_SCHEMA: {configured!r}")
        return configured

    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT current_schema()")
        row = cursor.fetchone()
    schema = row[0] or "public"
    if not _SCHEMA_RE.fullmatch(schema):
        raise RuntimeError(f"Invalid database schema name: {schema!r}")
    return schema


def _quoted_schema(schema_editor, schema: str) -> str:
    return schema_editor.connection.ops.quote_name(schema)


def _relation_exists(schema_editor, schema: str, relation_name: str) -> bool:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT 1
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = %s AND c.relname = %s
            LIMIT 1
            """,
            [schema, relation_name],
        )
        row = cursor.fetchone()
    return bool(row and row[0])


def _seed_baseline_tenant_types(schema_editor, schema_sql: str) -> None:
    with schema_editor.connection.cursor() as cursor:
        for code, name, description, display_order in _BASELINE_TENANT_TYPES:
            cursor.execute(
                f"""
                INSERT INTO {schema_sql}.ref_tenant_type (
                    tenant_type_code,
                    tenant_type_name,
                    description,
                    display_order,
                    status_code,
                    create_by_id,
                    update_by_id
                )
                VALUES (%s, %s, %s, %s, 'A', %s, %s)
                ON CONFLICT (tenant_type_code) DO UPDATE
                SET tenant_type_name = EXCLUDED.tenant_type_name,
                    description = EXCLUDED.description,
                    display_order = EXCLUDED.display_order,
                    status_code = 'A',
                    update_by_id = EXCLUDED.update_by_id,
                    update_dtime = CURRENT_TIMESTAMP,
                    version_nbr = {schema_sql}.ref_tenant_type.version_nbr + 1
                """,
                [code, name, description, display_order, _SYSTEM_ACTOR_ID, _SYSTEM_ACTOR_ID],
            )


def _migrate_tenant_rows(schema_editor, schema_sql: str) -> None:
    baseline_sql = ", ".join(f"'{code}'" for code in _BASELINE_CODES)
    schema_editor.execute(
        f"""
        UPDATE {schema_sql}.tenant
        SET tenant_type = CASE
                WHEN UPPER(REPLACE(REPLACE(COALESCE(tenant_type, ''), '-', '_'), ' ', '_'))
                    IN ('NEOC', 'NATIONAL_LEVEL') THEN 'NATIONAL'
                WHEN UPPER(REPLACE(REPLACE(COALESCE(tenant_type, ''), '-', '_'), ' ', '_'))
                    = 'INFRASTRUCTURE' THEN 'UTILITY'
                WHEN UPPER(REPLACE(REPLACE(COALESCE(tenant_type, ''), '-', '_'), ' ', '_'))
                    = 'SHELTER' THEN 'SHELTER_OPERATOR'
                WHEN UPPER(REPLACE(REPLACE(COALESCE(tenant_type, ''), '-', '_'), ' ', '_'))
                    IN ('AGENCY', 'OTHER', 'PUBLIC') THEN 'PARTNER'
                WHEN UPPER(REPLACE(REPLACE(COALESCE(tenant_type, ''), '-', '_'), ' ', '_'))
                    = 'MINISTRY'
                    AND (
                        UPPER(REPLACE(REPLACE(COALESCE(tenant_code, ''), '-', '_'), ' ', '_')) LIKE '%%MLSS%%'
                        OR UPPER(REPLACE(REPLACE(COALESCE(tenant_name, ''), '-', '_'), ' ', '_')) LIKE '%%MLSS%%'
                        OR UPPER(REPLACE(REPLACE(COALESCE(tenant_name, ''), '-', '_'), ' ', '_')) LIKE '%%MINISTRY_OF_LABOUR%%'
                        OR UPPER(REPLACE(REPLACE(COALESCE(tenant_name, ''), '-', '_'), ' ', '_')) LIKE '%%LABOUR_AND_SOCIAL_SECURITY%%'
                    ) THEN 'SOCIAL_SERVICES'
                WHEN UPPER(REPLACE(REPLACE(COALESCE(tenant_type, ''), '-', '_'), ' ', '_'))
                    = 'MINISTRY' THEN 'PARTNER'
                WHEN UPPER(REPLACE(REPLACE(COALESCE(tenant_type, ''), '-', '_'), ' ', '_'))
                    = 'EXTERNAL'
                    AND (
                        UPPER(REPLACE(REPLACE(COALESCE(tenant_code, ''), '-', '_'), ' ', '_')) LIKE '%%NGO%%'
                        OR UPPER(REPLACE(REPLACE(COALESCE(tenant_name, ''), '-', '_'), ' ', '_')) LIKE '%%NGO%%'
                        OR UPPER(REPLACE(REPLACE(COALESCE(tenant_name, ''), '-', '_'), ' ', '_')) LIKE '%%RED_CROSS%%'
                        OR UPPER(REPLACE(REPLACE(COALESCE(tenant_name, ''), '-', '_'), ' ', '_')) LIKE '%%JRC%%'
                        OR UPPER(REPLACE(REPLACE(COALESCE(tenant_name, ''), '-', '_'), ' ', '_')) LIKE '%%SALVATION%%'
                        OR UPPER(REPLACE(REPLACE(COALESCE(tenant_name, ''), '-', '_'), ' ', '_')) LIKE '%%HUMANITARIAN%%'
                    ) THEN 'NGO'
                WHEN UPPER(REPLACE(REPLACE(COALESCE(tenant_type, ''), '-', '_'), ' ', '_'))
                    = 'EXTERNAL' THEN 'PARTNER'
                WHEN UPPER(REPLACE(REPLACE(COALESCE(tenant_type, ''), '-', '_'), ' ', '_'))
                    NOT IN ({baseline_sql}) THEN 'PARTNER'
                ELSE UPPER(REPLACE(REPLACE(COALESCE(tenant_type, ''), '-', '_'), ' ', '_'))
            END,
            update_by_id = %s,
            update_dtime = CURRENT_TIMESTAMP,
            version_nbr = version_nbr + 1
        WHERE UPPER(REPLACE(REPLACE(COALESCE(tenant_type, ''), '-', '_'), ' ', '_'))
            NOT IN ({baseline_sql})
        """,
        [_SYSTEM_ACTOR_ID],
    )
    schema_editor.execute(
        f"""
        UPDATE {schema_sql}.tenant
        SET tenant_type = UPPER(REPLACE(REPLACE(COALESCE(tenant_type, ''), '-', '_'), ' ', '_')),
            update_by_id = %s,
            update_dtime = CURRENT_TIMESTAMP,
            version_nbr = version_nbr + 1
        WHERE UPPER(REPLACE(REPLACE(COALESCE(tenant_type, ''), '-', '_'), ' ', '_'))
            IN ({baseline_sql})
          AND tenant_type <> UPPER(REPLACE(REPLACE(COALESCE(tenant_type, ''), '-', '_'), ' ', '_'))
        """,
        [_SYSTEM_ACTOR_ID],
    )


def _retire_legacy_tenant_types(schema_editor, schema_sql: str) -> None:
    retired_sql = ", ".join(f"'{code}'" for code in _RETIRED_CODES)
    schema_editor.execute(
        f"""
        UPDATE {schema_sql}.ref_tenant_type
        SET status_code = 'I',
            update_by_id = %s,
            update_dtime = CURRENT_TIMESTAMP,
            version_nbr = version_nbr + 1
        WHERE tenant_type_code IN ({retired_sql})
        """,
        [_SYSTEM_ACTOR_ID],
    )


def _resync_permission_sequence(schema_editor, schema: str, schema_sql: str) -> None:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_get_serial_sequence(%s, %s)",
            [f"{schema}.permission", "perm_id"],
        )
        row = cursor.fetchone()
        sequence_name = row[0] if row else None
        if not sequence_name:
            return
        cursor.execute(f"SELECT COALESCE(MAX(perm_id), 0) + 1 FROM {schema_sql}.permission")
        next_value_row = cursor.fetchone()
        next_value = int(next_value_row[0] or 1) if next_value_row else 1
        cursor.execute("SELECT setval(%s::regclass, %s, false)", [sequence_name, next_value])


def _seed_tenant_type_permission(schema_editor, schema_sql: str) -> None:
    schema_editor.execute(
        f"""
        WITH tenant_type_permission AS (
            INSERT INTO {schema_sql}.permission (
                resource,
                action,
                create_by_id,
                update_by_id
            )
            VALUES ('masterdata.tenant_type', 'manage', %s, %s)
            ON CONFLICT (resource, action) DO UPDATE
            SET update_by_id = EXCLUDED.update_by_id,
                update_dtime = CURRENT_TIMESTAMP,
                version_nbr = {schema_sql}.permission.version_nbr + 1
            RETURNING perm_id
        )
        INSERT INTO {schema_sql}.role_permission (
            role_id,
            perm_id,
            create_by_id,
            update_by_id
        )
        SELECT r.id, p.perm_id, %s, %s
        FROM {schema_sql}.role r
        CROSS JOIN tenant_type_permission p
        WHERE UPPER(r.code) = 'SYSTEM_ADMINISTRATOR'
        ON CONFLICT (role_id, perm_id) DO NOTHING
        """,
        [_SYSTEM_ACTOR_ID, _SYSTEM_ACTOR_ID, _SYSTEM_ACTOR_ID, _SYSTEM_ACTOR_ID],
    )


def _forwards(apps, schema_editor) -> None:
    if not _is_postgres(schema_editor):
        return

    schema = _schema_name(schema_editor)
    required_relations = ("ref_tenant_type", "tenant")
    if not all(_relation_exists(schema_editor, schema, relation) for relation in required_relations):
        return

    schema_sql = _quoted_schema(schema_editor, schema)
    schema_editor.execute(
        f"ALTER TABLE {schema_sql}.ref_tenant_type ADD COLUMN IF NOT EXISTS description text"
    )
    schema_editor.execute(
        f"ALTER TABLE {schema_sql}.ref_tenant_type ADD COLUMN IF NOT EXISTS display_order integer DEFAULT 90"
    )
    schema_editor.execute(
        f"""
        UPDATE {schema_sql}.ref_tenant_type
        SET display_order = 90
        WHERE display_order IS NULL
        """
    )
    schema_editor.execute(
        f"ALTER TABLE {schema_sql}.ref_tenant_type ALTER COLUMN display_order SET DEFAULT 90"
    )
    schema_editor.execute(
        f"ALTER TABLE {schema_sql}.ref_tenant_type ALTER COLUMN display_order SET NOT NULL"
    )
    schema_editor.execute(
        f"ALTER TABLE {schema_sql}.tenant DROP CONSTRAINT IF EXISTS tenant_tenant_type_check"
    )
    _seed_baseline_tenant_types(schema_editor, schema_sql)
    _migrate_tenant_rows(schema_editor, schema_sql)
    _retire_legacy_tenant_types(schema_editor, schema_sql)

    if all(
        _relation_exists(schema_editor, schema, relation)
        for relation in ("permission", "role", "role_permission")
    ):
        _resync_permission_sequence(schema_editor, schema, schema_sql)
        _seed_tenant_type_permission(schema_editor, schema_sql)


def _backwards(apps, schema_editor) -> None:
    if not _is_postgres(schema_editor):
        return

    schema = _schema_name(schema_editor)
    if not _relation_exists(schema_editor, schema, "ref_tenant_type"):
        return

    schema_sql = _quoted_schema(schema_editor, schema)
    schema_editor.execute(
        f"""
        UPDATE {schema_sql}.ref_tenant_type
        SET status_code = 'I',
            update_by_id = %s,
            update_dtime = CURRENT_TIMESTAMP,
            version_nbr = version_nbr + 1
        WHERE tenant_type_code IN ({", ".join(f"'{code}'" for code in _BASELINE_CODES)})
        """,
        [_SYSTEM_ACTOR_ID],
    )


class Migration(migrations.Migration):
    atomic = True

    dependencies = [
        ("masterdata", "0011_parish_proximity_matrix"),
    ]

    operations = [
        migrations.RunPython(_forwards, _backwards),
    ]
