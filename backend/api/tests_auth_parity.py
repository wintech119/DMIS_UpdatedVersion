from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase, override_settings
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.test import APIClient

from api import authentication


FIXTURE_DIR = Path(__file__).resolve().parent / "tests_auth_parity_fixtures"


def _snapshot_paths() -> list[Path]:
    return sorted(FIXTURE_DIR.glob("whoami_*.json"))


def _username_from_snapshot_path(path: Path) -> str:
    return path.stem.replace("whoami_", "", 1)


class AuthParityFixtureMixin:
    def setUp(self) -> None:
        self.client = APIClient()
        self.snapshot_paths = {
            _username_from_snapshot_path(path): path
            for path in _snapshot_paths()
        }
        self.snapshot_bytes = {
            username: path.read_bytes()
            for username, path in self.snapshot_paths.items()
        }
        self.snapshots = {
            username: json.loads(payload.decode("utf-8"))
            for username, payload in self.snapshot_bytes.items()
        }
        self._ensure_legacy_iam_tables()
        self._delete_snapshot_rows()
        self._seed_snapshot_rows()

    def tearDown(self) -> None:
        self._delete_snapshot_rows()

    @property
    def user_ids(self) -> list[int]:
        return [int(snapshot["user_id"]) for snapshot in self.snapshots.values()]

    def _snapshot_newline(self, username: str) -> str:
        return "\r\n" if b"\r\n" in self.snapshot_bytes[username] else "\n"

    def _ensure_legacy_iam_tables(self) -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS tenant (
                    tenant_id integer PRIMARY KEY,
                    tenant_code varchar(20) NOT NULL UNIQUE,
                    tenant_name varchar(120) NOT NULL,
                    tenant_type varchar(20) NOT NULL,
                    status_code char(1) DEFAULT 'A' NOT NULL,
                    create_by_id varchar(20) DEFAULT 'SYSTEM' NOT NULL,
                    create_dtime timestamp DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    update_by_id varchar(20) DEFAULT 'SYSTEM' NOT NULL,
                    update_dtime timestamp DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    version_nbr integer DEFAULT 1 NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS "user" (
                    user_id integer PRIMARY KEY,
                    email varchar(200) NOT NULL UNIQUE,
                    password_hash varchar(256) NOT NULL,
                    first_name varchar(100),
                    last_name varchar(100),
                    full_name varchar(200),
                    is_active boolean DEFAULT TRUE NOT NULL,
                    organization varchar(200),
                    job_title varchar(200),
                    phone varchar(50),
                    timezone varchar(50) DEFAULT 'America/Jamaica' NOT NULL,
                    language varchar(10) DEFAULT 'en' NOT NULL,
                    notification_preferences text,
                    assigned_warehouse_id integer,
                    last_login_at timestamp,
                    create_dtime timestamp DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    update_dtime timestamp DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    username varchar(60) UNIQUE,
                    password_algo varchar(20) DEFAULT 'argon2id' NOT NULL,
                    mfa_enabled boolean DEFAULT FALSE NOT NULL,
                    mfa_secret varchar(64),
                    failed_login_count smallint DEFAULT 0 NOT NULL,
                    lock_until_at timestamp,
                    password_changed_at timestamp,
                    agency_id integer,
                    status_code char(1) DEFAULT 'A' NOT NULL,
                    version_nbr integer DEFAULT 1 NOT NULL,
                    user_name varchar(20) NOT NULL,
                    login_count integer DEFAULT 0 NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS role (
                    id integer PRIMARY KEY,
                    code varchar(50) NOT NULL UNIQUE,
                    name varchar(100) NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS permission (
                    perm_id integer PRIMARY KEY,
                    resource varchar(100) NOT NULL,
                    action varchar(100) NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS user_role (
                    user_id integer NOT NULL,
                    role_id integer NOT NULL,
                    assigned_at timestamp DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    assigned_by integer,
                    create_by_id varchar(20) DEFAULT 'system' NOT NULL,
                    create_dtime timestamp DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    update_by_id varchar(20) DEFAULT 'system' NOT NULL,
                    update_dtime timestamp DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    version_nbr integer DEFAULT 1 NOT NULL,
                    PRIMARY KEY (user_id, role_id)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS role_permission (
                    role_id integer NOT NULL,
                    perm_id integer NOT NULL,
                    PRIMARY KEY (role_id, perm_id)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS tenant_user (
                    tenant_id integer NOT NULL,
                    user_id integer NOT NULL,
                    is_primary_tenant boolean DEFAULT FALSE NOT NULL,
                    access_level varchar(20),
                    status_code char(1) DEFAULT 'A' NOT NULL,
                    create_by_id varchar(20) DEFAULT 'system' NOT NULL,
                    create_dtime timestamp DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    update_by_id varchar(20) DEFAULT 'system' NOT NULL,
                    update_dtime timestamp DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    version_nbr integer DEFAULT 1 NOT NULL,
                    PRIMARY KEY (tenant_id, user_id)
                )
                """
            )

    def _delete_snapshot_rows(self) -> None:
        if not self.snapshots:
            return
        user_ids = self.user_ids
        tenant_ids = sorted(
            {
                int(membership["tenant_id"])
                for snapshot in self.snapshots.values()
                for membership in snapshot["tenant_context"]["memberships"]
            }
        )
        with connection.cursor() as cursor:
            for user_id in user_ids:
                cursor.execute("DELETE FROM tenant_user WHERE user_id = %s", [user_id])
                cursor.execute("DELETE FROM user_role WHERE user_id = %s", [user_id])
                cursor.execute('DELETE FROM "user" WHERE user_id = %s', [user_id])
            for tenant_id in tenant_ids:
                cursor.execute("DELETE FROM tenant WHERE tenant_id = %s", [tenant_id])
            cursor.execute("DELETE FROM role_permission")
            cursor.execute("DELETE FROM permission")
            cursor.execute("DELETE FROM role")

    def _seed_snapshot_rows(self) -> None:
        role_ids: dict[str, int] = {}
        permission_ids: dict[str, int] = {}
        role_permissions: dict[str, set[str]] = {}
        tenants: dict[int, dict] = {}

        for snapshot in self.snapshots.values():
            for role in snapshot["roles"]:
                role_permissions.setdefault(role, set()).update(snapshot["permissions"])
            for membership in snapshot["tenant_context"]["memberships"]:
                tenants[int(membership["tenant_id"])] = membership

        with connection.cursor() as cursor:
            for tenant_id, membership in sorted(tenants.items()):
                cursor.execute(
                    """
                    INSERT INTO tenant (
                        tenant_id, tenant_code, tenant_name, tenant_type, status_code
                    )
                    VALUES (%s, %s, %s, %s, 'A')
                    """,
                    [
                        tenant_id,
                        membership["tenant_code"],
                        membership["tenant_name"],
                        membership["tenant_type"],
                    ],
                )

            for index, role in enumerate(sorted(role_permissions), start=1):
                role_ids[role] = index
                cursor.execute(
                    "INSERT INTO role (id, code, name) VALUES (%s, %s, %s)",
                    [index, role, role.replace("_", " ").title()],
                )

            for index, permission in enumerate(
                sorted({perm for perms in role_permissions.values() for perm in perms}),
                start=1,
            ):
                resource, action = permission.rsplit(".", 1)
                permission_ids[permission] = index
                cursor.execute(
                    "INSERT INTO permission (perm_id, resource, action) VALUES (%s, %s, %s)",
                    [index, resource, action],
                )

            for role, permissions in role_permissions.items():
                for permission in permissions:
                    cursor.execute(
                        "INSERT INTO role_permission (role_id, perm_id) VALUES (%s, %s)",
                        [role_ids[role], permission_ids[permission]],
                    )

            for username, snapshot in self.snapshots.items():
                user_id = int(snapshot["user_id"])
                cursor.execute(
                    """
                    INSERT INTO "user" (
                        user_id,
                        email,
                        password_hash,
                        full_name,
                        is_active,
                        username,
                        user_name,
                        password_algo,
                        mfa_enabled,
                        failed_login_count,
                        status_code,
                        version_nbr,
                        login_count
                    )
                    VALUES (%s, %s, '', %s, TRUE, %s, %s, 'django', FALSE, 0, 'A', 1, 0)
                    """,
                    [
                        user_id,
                        f"{username}@parity.example.test",
                        username,
                        username,
                        username[:20],
                    ],
                )
                for role in snapshot["roles"]:
                    cursor.execute(
                        "INSERT INTO user_role (user_id, role_id) VALUES (%s, %s)",
                        [user_id, role_ids[role]],
                    )
                for membership in snapshot["tenant_context"]["memberships"]:
                    cursor.execute(
                        """
                        INSERT INTO tenant_user (
                            tenant_id, user_id, is_primary_tenant, access_level, status_code
                        )
                        VALUES (%s, %s, %s, %s, 'A')
                        """,
                        [
                            int(membership["tenant_id"]),
                            user_id,
                            bool(membership["is_primary"]),
                            membership["access_level"],
                        ],
                    )


@override_settings(
    AUTH_ENABLED=False,
    DEV_AUTH_ENABLED=True,
    DMIS_RUNTIME_ENV="local-harness",
    LOCAL_AUTH_HARNESS_ENABLED=True,
    TEST_DEV_AUTH_ENABLED=True,
    DEBUG=True,
    AUTH_USE_DB_RBAC=True,
)
class AuthParityTests(AuthParityFixtureMixin, TestCase):
    def test_whoami_matches_all_phase1_local_harness_snapshots(self) -> None:
        with override_settings(LOCAL_AUTH_HARNESS_USERNAMES=list(self.snapshots)):
            for username in self.snapshots:
                with self.subTest(username=username):
                    response = self.client.get(
                        "/api/v1/auth/whoami/",
                        HTTP_X_DMIS_LOCAL_USER=username,
                    )

                    self.assertEqual(response.status_code, 200)
                    newline = self._snapshot_newline(username)
                    actual_text = json.dumps(response.json(), indent=2, sort_keys=True)
                    actual_bytes = (actual_text.replace("\n", newline) + newline).encode("utf-8")
                    self.assertEqual(actual_bytes, self.snapshot_bytes[username])

    def test_non_allowlisted_local_harness_user_is_rejected(self) -> None:
        with (
            override_settings(LOCAL_AUTH_HARNESS_USERNAMES=["local_system_admin_tst"]),
            patch("api.authentication.logger.warning") as mock_warning,
        ):
            response = self.client.get(
                "/api/v1/auth/whoami/",
                HTTP_X_DMIS_LOCAL_USER="not_allowlisted_tst",
            )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(mock_warning.call_args.args[0], "auth.local_harness_rejected_non_allowlisted_user")

    @override_settings(LOCAL_AUTH_HARNESS_USERNAMES=["local_system_admin_tst"])
    def test_legacy_dev_user_header_is_rejected(self) -> None:
        response = self.client.get(
            "/api/v1/auth/whoami/",
            HTTP_X_DEV_USER="local_system_admin_tst",
        )

        self.assertEqual(response.status_code, 401)
        self.assertIn("X-Dev-User", response.json()["detail"])


class AuthParitySnapshotCommandTests(TestCase):
    def test_rejects_sanitized_snapshot_filename_collisions(self) -> None:
        with TemporaryDirectory() as tmpdir:
            with self.assertRaisesMessage(CommandError, "same snapshot filename"):
                call_command(
                    "capture_auth_parity_snapshots",
                    username=["a/b", "a:b"],
                    output_dir=tmpdir,
                )


class AuthAuditCompatibilityTests(TestCase):
    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        LOCAL_AUTH_HARNESS_ENABLED=False,
        TEST_DEV_AUTH_ENABLED=True,
        DEBUG=True,
    )
    @patch("api.authentication.logger.warning")
    def test_local_harness_header_outside_local_mode_emits_same_warning(self, mock_warning) -> None:
        request = SimpleNamespace(
            META={"HTTP_X_DMIS_LOCAL_USER": "local_system_admin_tst"},
            method="GET",
            path="/api/v1/auth/whoami/",
        )

        with self.assertRaises(AuthenticationFailed):
            authentication._enforce_dev_override_header_policy(request)

        self.assertEqual(mock_warning.call_args.args[0], "auth.rejected_local_harness_header_outside_local_mode")

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=False,
        LOCAL_AUTH_HARNESS_ENABLED=False,
        TEST_DEV_AUTH_ENABLED=True,
        DEBUG=True,
    )
    @patch("api.authentication.logger.warning")
    def test_disabled_local_harness_resolver_emits_same_warning(self, mock_warning) -> None:
        request = SimpleNamespace(
            META={"HTTP_X_DMIS_LOCAL_USER": "local_system_admin_tst"},
            method="GET",
            path="/api/v1/auth/whoami/",
        )

        with self.assertRaises(AuthenticationFailed):
            authentication._resolve_dev_override_principal(request)

        self.assertEqual(mock_warning.call_args.args[0], "auth.local_harness_override_rejected_when_disabled")

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        LOCAL_AUTH_HARNESS_ENABLED=True,
        LOCAL_AUTH_HARNESS_USERNAMES=[],
        TEST_DEV_AUTH_ENABLED=True,
        DEBUG=True,
    )
    @patch("api.authentication.logger.warning")
    def test_enabled_local_harness_without_allowlist_emits_same_warning(self, mock_warning) -> None:
        request = SimpleNamespace(
            META={"HTTP_X_DMIS_LOCAL_USER": "local_system_admin_tst"},
            method="GET",
            path="/api/v1/auth/whoami/",
        )

        with self.assertRaises(AuthenticationFailed):
            authentication._resolve_dev_override_principal(request)

        self.assertEqual(mock_warning.call_args.args[0], "auth.local_harness_enabled_without_allowlist")

    @patch("api.authentication.connection.cursor", side_effect=authentication.DatabaseError("boom"))
    @patch("api.authentication.logger.warning")
    def test_role_lookup_failure_emits_same_warning(self, mock_warning, _mock_cursor) -> None:
        with self.assertRaises(AuthenticationFailed):
            authentication._fetch_dev_override_roles_and_permissions(17)

        self.assertEqual(mock_warning.call_args.args[0], "auth.dev_override_role_lookup_failed")
