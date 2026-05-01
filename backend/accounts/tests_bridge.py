from __future__ import annotations

from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase, override_settings

from accounts.models import DmisUser, RbacBridgeGroup
from accounts.management.commands.sync_rbac_to_django_auth import (
    BRIDGE_COMBO_GROUP_PREFIX,
    Command as SyncRbacCommand,
)
from accounts.permissions import bridge_codename
from accounts.tests import DmisUserTestMixin
from api import checks as api_checks
from api import rbac
from api.rbac import resolve_roles_and_permissions


BRIDGE_AUTH_BACKENDS = ["django.contrib.auth.backends.ModelBackend"]


@override_settings(
    AUTH_ENABLED=False,
    DEV_AUTH_ENABLED=True,
    TEST_DEV_AUTH_ENABLED=True,
    AUTHENTICATION_BACKENDS=BRIDGE_AUTH_BACKENDS,
    AUTH_USE_DB_RBAC=True,
)
class RbacBridgeSyncTests(DmisUserTestMixin, TestCase):
    role_codes = {
        501: "BRIDGE_LOGISTICS",
        502: "BRIDGE_VIEWER",
        503: "BRIDGE_NATIONAL",
    }
    permission_codes = {
        701: rbac.PERM_MASTERDATA_VIEW,
        702: rbac.PERM_NEEDS_LIST_SUBMIT,
        703: rbac.PERM_TENANT_FEATURE_VIEW,
        704: rbac.PERM_NATIONAL_ACT_CROSS_TENANT,
        705: rbac.PERM_OPERATIONS_REQUEST_CREATE_SELF,
    }
    permission_row_parts = {
        rbac.PERM_OPERATIONS_REQUEST_CREATE_SELF: (
            "operations.request",
            "create.self",
        ),
    }
    role_permissions = {
        "BRIDGE_LOGISTICS": {
            rbac.PERM_MASTERDATA_VIEW,
            rbac.PERM_NEEDS_LIST_SUBMIT,
        },
        "BRIDGE_VIEWER": {rbac.PERM_MASTERDATA_VIEW},
        "BRIDGE_NATIONAL": {rbac.PERM_NATIONAL_ACT_CROSS_TENANT},
    }
    user_roles = {
        881001: {"BRIDGE_LOGISTICS"},
        881002: {"BRIDGE_VIEWER"},
        881003: {"BRIDGE_LOGISTICS", "BRIDGE_NATIONAL"},
    }

    def setUp(self) -> None:
        super().setUp()
        self._ensure_bridge_tables()
        self._ensure_auth_m2m_tables()
        self._clear_bridge_state()
        self._insert_bridge_fixture()

    def tearDown(self) -> None:
        self._clear_bridge_state()
        super().tearDown()

    def _fixture_teardown(self) -> None:
        self._clear_bridge_state()
        super()._fixture_teardown()

    def test_sync_creates_groups_and_permissions(self) -> None:
        self._run_sync()

        group_names = set(Group.objects.values_list("name", flat=True))
        combo_groups = {
            group_name
            for group_name in group_names
            if group_name.startswith(BRIDGE_COMBO_GROUP_PREFIX)
        }
        self.assertTrue(set(self.role_codes.values()).issubset(group_names))
        self.assertEqual(len(combo_groups), 1)
        for code in self.permission_codes.values():
            resource, action = self._permission_parts_for_code(code)
            self.assertTrue(
                Permission.objects.filter(
                    content_type__app_label="dmis",
                    content_type__model=resource,
                    codename=bridge_codename(resource, action),
                ).exists()
            )
        self.assertEqual(
            Permission.objects.filter(content_type__app_label="dmis").count(),
            len(self._expected_all_permission_codes()),
        )

    def test_sync_preserves_dotted_permission_row_actions(self) -> None:
        self._run_sync()

        expected_codename = bridge_codename("operations.request", "create.self")
        old_split_codename = bridge_codename("operations.request.create", "self")

        self.assertTrue(
            Permission.objects.filter(
                content_type__app_label="dmis",
                content_type__model="operations.request",
                codename=expected_codename,
            ).exists()
        )
        self.assertFalse(
            Permission.objects.filter(
                content_type__app_label="dmis",
                content_type__model="operations.request.create",
                codename=old_split_codename,
            ).exists()
        )
        self.assertTrue(DmisUser.objects.get(pk=881001).has_perm(expected_codename))

    def test_sync_assigns_user_groups(self) -> None:
        self._run_sync()

        for user_id, expected_roles in self.user_roles.items():
            user = DmisUser.objects.get(pk=user_id)
            group_names = set(user.groups.values_list("name", flat=True))
            combo_groups = {
                group_name
                for group_name in group_names
                if group_name.startswith(BRIDGE_COMBO_GROUP_PREFIX)
            }

            self.assertTrue(expected_roles.issubset(group_names))
            if user_id == 881003:
                self.assertEqual(len(combo_groups), 1)
            else:
                self.assertEqual(combo_groups, set())

    def test_has_perm_via_bridge_matches_resolve_roles_and_permissions(self) -> None:
        self._run_sync()

        for user_id, roles in self.user_roles.items():
            expected_codes = self._expected_permission_codes_for_roles(roles)
            expected_bridge_permissions = {
                self._bridge_permission_string(code) for code in expected_codes
            }
            user = DmisUser.objects.get(pk=user_id)

            self.assertEqual(user.get_all_permissions(), expected_bridge_permissions)
            for code in expected_codes:
                resource, action = self._permission_parts_for_code(code)
                codename = bridge_codename(resource, action)
                self.assertTrue(user.has_perm(f"dmis.{codename}"))
                self.assertTrue(user.has_perm(codename))

    def test_sync_clears_direct_dmis_user_permissions(self) -> None:
        self._run_sync()
        viewer = DmisUser.objects.get(pk=881002)
        external_permission = self._create_external_permission()
        resource, action = self._permission_parts_for_code(rbac.PERM_TENANT_FEATURE_VIEW)
        stale_permission = Permission.objects.get(
            content_type__app_label="dmis",
            content_type__model=resource,
            codename=bridge_codename(resource, action),
        )

        viewer.user_permissions.add(stale_permission)
        viewer.user_permissions.add(external_permission)
        self.assertTrue(viewer.has_perm(bridge_codename(resource, action)))
        self.assertTrue(viewer.has_perm("external_app.external_manage"))

        self._run_sync()
        viewer = DmisUser.objects.get(pk=881002)

        self.assertFalse(
            viewer.user_permissions.filter(pk=stale_permission.pk).exists()
        )
        self.assertTrue(
            viewer.user_permissions.filter(pk=external_permission.pk).exists()
        )
        self.assertFalse(viewer.has_perm(bridge_codename(resource, action)))
        self.assertTrue(viewer.has_perm("external_app.external_manage"))

    def test_sync_is_idempotent(self) -> None:
        self._run_sync()
        first_state = self._bridge_state()

        output = self._run_sync()
        self.assertIn("Permissions: 0 created, 0 updated", output)
        self.assertIn("Groups: 0 created, 0 updated", output)
        self.assertEqual(self._bridge_state(), first_state)

    def test_sync_bootstraps_unmarked_matching_legacy_bridge_group(self) -> None:
        self._run_sync()
        bridge_group = Group.objects.get(name="BRIDGE_VIEWER")
        RbacBridgeGroup.objects.filter(group=bridge_group).delete()
        dmis_permission_ids = set(bridge_group.permissions.values_list("id", flat=True))

        self._run_sync()

        bridge_group = Group.objects.get(name="BRIDGE_VIEWER")
        self.assertEqual(
            set(bridge_group.permissions.values_list("id", flat=True)),
            dmis_permission_ids,
        )
        self.assertTrue(RbacBridgeGroup.objects.filter(group=bridge_group).exists())

    def test_sync_rejects_empty_unmarked_group_name_collision(self) -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO role (id, code, name) VALUES (%s, %s, %s)",
                [504, "BRIDGE_EMPTY", "Bridge Empty"],
            )
        external_group = Group.objects.create(name="BRIDGE_EMPTY")

        with self.assertRaises(CommandError):
            self._run_sync()

        self.assertFalse(RbacBridgeGroup.objects.filter(group=external_group).exists())

    def test_sync_deletes_bridge_orphans(self) -> None:
        orphan_content_type = ContentType.objects.create(
            app_label="dmis",
            model="removed.resource",
        )
        Permission.objects.create(
            content_type=orphan_content_type,
            codename="removed.resource__view",
            name="DMIS removed.resource.view",
        )
        orphan_group = Group.objects.create(name=f"{BRIDGE_COMBO_GROUP_PREFIX}removed")
        RbacBridgeGroup.objects.create(group=orphan_group)

        self._run_sync()

        self.assertFalse(
            Group.objects.filter(name=f"{BRIDGE_COMBO_GROUP_PREFIX}removed").exists()
        )
        self.assertFalse(
            Permission.objects.filter(codename="removed.resource__view").exists()
        )

    def test_sync_removes_stale_bridge_role_memberships(self) -> None:
        stale_content_type = ContentType.objects.create(
            app_label="dmis",
            model="removed.role",
        )
        stale_permission = Permission.objects.create(
            content_type=stale_content_type,
            codename="removed.role__view",
            name="DMIS removed.role.view",
        )
        stale_group = Group.objects.create(name="REMOVED_ROLE")
        stale_group.permissions.add(stale_permission)
        RbacBridgeGroup.objects.create(group=stale_group)
        user = DmisUser.objects.get(pk=881001)
        user.groups.add(stale_group)

        self._run_sync()

        user = DmisUser.objects.get(pk=881001)
        self.assertFalse(Group.objects.filter(name="REMOVED_ROLE").exists())
        self.assertFalse(user.groups.filter(name="REMOVED_ROLE").exists())
        self.assertFalse(
            Permission.objects.filter(pk=stale_permission.pk).exists()
        )

    def test_sync_preserves_external_groups_and_memberships(self) -> None:
        external_permission = self._create_external_permission()
        external_group = Group.objects.create(name="EXTERNAL_OPS")
        external_group.permissions.add(external_permission)
        user = DmisUser.objects.get(pk=881001)
        user.groups.add(external_group)

        self._run_sync()

        user = DmisUser.objects.get(pk=881001)
        self.assertTrue(Group.objects.filter(name="EXTERNAL_OPS").exists())
        self.assertTrue(user.groups.filter(name="EXTERNAL_OPS").exists())
        self.assertTrue(user.groups.filter(name="BRIDGE_LOGISTICS").exists())
        self.assertTrue(user.has_perm("external_app.external_manage"))

    def test_sync_rejects_unmarked_group_name_collision(self) -> None:
        external_permission = self._create_external_permission()
        bridge_group = Group.objects.create(name="BRIDGE_VIEWER")
        bridge_group.permissions.add(external_permission)
        viewer = DmisUser.objects.get(pk=881002)
        viewer.groups.add(bridge_group)
        self.assertTrue(viewer.has_perm("external_app.external_manage"))

        with self.assertRaises(CommandError):
            self._run_sync()

        viewer = DmisUser.objects.get(pk=881002)
        bridge_group = Group.objects.get(name="BRIDGE_VIEWER")
        self.assertTrue(
            bridge_group.permissions.filter(pk=external_permission.pk).exists()
        )
        self.assertTrue(viewer.groups.filter(name="BRIDGE_VIEWER").exists())
        self.assertTrue(viewer.has_perm("external_app.external_manage"))
        self.assertFalse(RbacBridgeGroup.objects.filter(group=bridge_group).exists())

    def test_sync_preserves_unmarked_manual_combo_prefix_group(self) -> None:
        external_permission = self._create_external_permission()
        external_group = Group.objects.create(name=f"{BRIDGE_COMBO_GROUP_PREFIX}manual")
        external_group.permissions.add(external_permission)
        user = DmisUser.objects.get(pk=881001)
        user.groups.add(external_group)

        self._run_sync()

        user = DmisUser.objects.get(pk=881001)
        external_group = Group.objects.get(name=f"{BRIDGE_COMBO_GROUP_PREFIX}manual")
        self.assertTrue(user.groups.filter(pk=external_group.pk).exists())
        self.assertTrue(
            external_group.permissions.filter(pk=external_permission.pk).exists()
        )
        self.assertFalse(RbacBridgeGroup.objects.filter(group=external_group).exists())

    def test_sync_rejects_unmarked_combo_group_name_collision(self) -> None:
        external_permission = self._create_external_permission()
        combo_name = SyncRbacCommand()._combo_group_name(self.user_roles[881003])
        combo_group = Group.objects.create(name=combo_name)
        combo_group.permissions.add(external_permission)
        combo_user = DmisUser.objects.get(pk=881003)
        combo_user.groups.add(combo_group)

        with self.assertRaises(CommandError):
            self._run_sync()

        combo_user = DmisUser.objects.get(pk=881003)
        combo_group = Group.objects.get(name=combo_name)
        self.assertTrue(combo_user.groups.filter(pk=combo_group.pk).exists())
        self.assertTrue(
            combo_group.permissions.filter(pk=external_permission.pk).exists()
        )
        self.assertFalse(RbacBridgeGroup.objects.filter(group=combo_group).exists())

    def test_sync_resets_marked_bridge_group_permissions_to_derived_set(self) -> None:
        self._run_sync()
        external_permission = self._create_external_permission()
        bridge_group = Group.objects.get(name="BRIDGE_VIEWER")
        bridge_group.permissions.add(external_permission)
        viewer = DmisUser.objects.get(pk=881002)
        self.assertTrue(viewer.has_perm("external_app.external_manage"))

        self._run_sync()

        viewer = DmisUser.objects.get(pk=881002)
        bridge_group = Group.objects.get(name="BRIDGE_VIEWER")
        self.assertFalse(
            bridge_group.permissions.filter(pk=external_permission.pk).exists()
        )
        self.assertFalse(viewer.has_perm("external_app.external_manage"))
        self.assertTrue(
            bridge_group.permissions.filter(
                content_type__app_label="dmis",
            ).exists()
        )

    def test_sync_strips_stale_dmis_permissions_from_external_groups(self) -> None:
        stale_content_type = ContentType.objects.create(
            app_label="dmis",
            model="stale.resource",
        )
        stale_permission = Permission.objects.create(
            content_type=stale_content_type,
            codename="stale.resource__view",
            name="DMIS stale.resource.view",
        )
        external_permission = self._create_external_permission()
        external_group = Group.objects.create(name="EXTERNAL_WITH_STALE_DMIS")
        external_group.permissions.add(stale_permission, external_permission)

        self._run_sync()

        external_group = Group.objects.get(name="EXTERNAL_WITH_STALE_DMIS")
        self.assertFalse(
            external_group.permissions.filter(pk=stale_permission.pk).exists()
        )
        self.assertTrue(
            external_group.permissions.filter(pk=external_permission.pk).exists()
        )

    def test_sync_preserves_external_membership_with_stale_dmis_permission(self) -> None:
        stale_content_type = ContentType.objects.create(
            app_label="dmis",
            model="mixed.external",
        )
        stale_permission = Permission.objects.create(
            content_type=stale_content_type,
            codename="mixed.external__view",
            name="DMIS mixed.external.view",
        )
        external_permission = self._create_external_permission()
        external_group = Group.objects.create(name="EXTERNAL_MIXED")
        external_group.permissions.add(stale_permission, external_permission)
        user = DmisUser.objects.get(pk=881001)
        user.groups.add(external_group)

        self._run_sync()

        user = DmisUser.objects.get(pk=881001)
        external_group = Group.objects.get(name="EXTERNAL_MIXED")
        self.assertTrue(user.groups.filter(name="EXTERNAL_MIXED").exists())
        self.assertFalse(
            external_group.permissions.filter(pk=stale_permission.pk).exists()
        )
        self.assertTrue(
            external_group.permissions.filter(pk=external_permission.pk).exists()
        )
        self.assertTrue(user.has_perm("external_app.external_manage"))

    def _run_sync(self) -> str:
        output = StringIO()
        call_command("sync_rbac_to_django_auth", stdout=output)
        return output.getvalue()

    def _ensure_bridge_tables(self) -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS permission (
                    perm_id integer PRIMARY KEY,
                    resource varchar(40) NOT NULL,
                    action varchar(32) NOT NULL
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

    def _ensure_auth_m2m_tables(self) -> None:
        existing_tables = set(connection.introspection.table_names())
        with connection.schema_editor() as schema_editor:
            for through_model in (
                DmisUser.groups.through,
                DmisUser.user_permissions.through,
            ):
                if through_model._meta.db_table not in existing_tables:
                    schema_editor.create_model(through_model)

    def _clear_bridge_state(self) -> None:
        RbacBridgeGroup.objects.all().delete()
        DmisUser.groups.through.objects.all().delete()
        DmisUser.user_permissions.through.objects.all().delete()
        Group.objects.all().delete()
        Permission.objects.filter(content_type__app_label="dmis").delete()
        ContentType.objects.filter(app_label="dmis").delete()
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM role_permission")
            cursor.execute("DELETE FROM user_role")
            cursor.execute("DELETE FROM role")
            cursor.execute("DELETE FROM permission")
            cursor.execute(
                """
                DELETE FROM "user"
                WHERE email LIKE %s
                """,
                ["accounts-bridge-%@example.test"],
            )

    def _insert_bridge_fixture(self) -> None:
        self._insert_user(
            user_id=881001,
            username="accounts_bridge_logistics_tst",
            email="accounts-bridge-logistics@example.test",
        )
        self._insert_user(
            user_id=881002,
            username="accounts_bridge_viewer_tst",
            email="accounts-bridge-viewer@example.test",
        )
        self._insert_user(
            user_id=881003,
            username="accounts_bridge_combo_tst",
            email="accounts-bridge-combo@example.test",
        )
        with connection.cursor() as cursor:
            for role_id, role_code in self.role_codes.items():
                cursor.execute(
                    "INSERT INTO role (id, code, name) VALUES (%s, %s, %s)",
                    [role_id, role_code, role_code.replace("_", " ").title()],
                )
            for perm_id, code in self.permission_codes.items():
                resource, action = self._permission_row_parts(code)
                cursor.execute(
                    "INSERT INTO permission (perm_id, resource, action) VALUES (%s, %s, %s)",
                    [perm_id, resource, action],
                )
            permission_ids_by_code = {
                code: perm_id for perm_id, code in self.permission_codes.items()
            }
            role_ids_by_code = {
                role_code: role_id for role_id, role_code in self.role_codes.items()
            }
            for role_code, permission_codes in self.role_permissions.items():
                for code in permission_codes:
                    cursor.execute(
                        "INSERT INTO role_permission (role_id, perm_id) VALUES (%s, %s)",
                        [role_ids_by_code[role_code], permission_ids_by_code[code]],
                    )
            for user_id, role_codes in self.user_roles.items():
                for role_code in role_codes:
                    cursor.execute(
                        "INSERT INTO user_role (user_id, role_id) VALUES (%s, %s)",
                        [user_id, role_ids_by_code[role_code]],
                    )

    def _expected_all_permission_codes(self) -> set[str]:
        expected = set(self.permission_codes.values())
        for role_codes in self.user_roles.values():
            expected.update(self._expected_permission_codes_for_roles(role_codes))
        return expected

    def _expected_permission_codes_for_roles(self, roles: set[str]) -> set[str]:
        seed_permissions = set()
        for role_code in roles:
            seed_permissions.update(self.role_permissions.get(role_code, set()))
        _resolved_roles, permissions = resolve_roles_and_permissions(
            SimpleNamespace(),
            SimpleNamespace(
                user_id=None,
                username=None,
                roles=sorted(roles),
                permissions=sorted(seed_permissions),
            ),
        )
        return set(permissions)

    def test_combined_role_compat_permissions_do_not_under_or_over_grant(self) -> None:
        self._run_sync()

        combo_user = DmisUser.objects.get(pk=881003)
        logistics_user = DmisUser.objects.get(pk=881001)
        resource, action = self._permission_parts_for_code(
            rbac.PERM_OPERATIONS_REQUEST_CREATE_ON_BEHALF_BRIDGE
        )
        codename = bridge_codename(resource, action)

        self.assertTrue(combo_user.has_perm(codename))
        self.assertFalse(logistics_user.has_perm(codename))

    def _bridge_permission_string(self, code: str) -> str:
        resource, action = self._permission_parts_for_code(code)
        return f"dmis.{bridge_codename(resource, action)}"

    def _create_external_permission(self) -> Permission:
        content_type, _created = ContentType.objects.get_or_create(
            app_label="external_app",
            model="external_model",
        )
        permission, _created = Permission.objects.get_or_create(
            content_type=content_type,
            codename="external_manage",
            defaults={"name": "External manage"},
        )
        return permission

    def _bridge_state(self):
        group_names = tuple(sorted(Group.objects.values_list("name", flat=True)))
        permission_codes = tuple(
            sorted(
                Permission.objects.filter(content_type__app_label="dmis")
                .values_list("content_type__model", "codename")
            )
        )
        user_groups = tuple(
            sorted(
                (user.user_id, group.name)
                for user in DmisUser.objects.filter(user_id__in=self.user_roles)
                for group in user.groups.all()
            )
        )
        return group_names, permission_codes, user_groups

    def _split_code(self, code: str) -> tuple[str, str]:
        return code.rsplit(".", 1)

    def _permission_row_parts(self, code: str) -> tuple[str, str]:
        return self.permission_row_parts.get(code, self._split_code(code))

    def _permission_parts_for_code(self, code: str) -> tuple[str, str]:
        permission_parts_by_code = {
            permission_code: self._permission_row_parts(permission_code)
            for permission_code in self.permission_codes.values()
        }
        if code in permission_parts_by_code:
            return permission_parts_by_code[code]

        known_resources = sorted(
            {resource for resource, _action in permission_parts_by_code.values()},
            key=len,
            reverse=True,
        )
        for resource in known_resources:
            prefix = f"{resource}."
            if code.startswith(prefix):
                action = code[len(prefix):]
                if action:
                    return resource, action

        return self._split_code(code)


class RbacBoundaryBridgeCheckTests(TestCase):
    @override_settings(TESTING=False, AUTH_USE_DB_RBAC=True)
    @patch("api.checks._count_rows", return_value=0)
    @patch("api.checks._table_exists", return_value=True)
    def test_w002_ignores_bridge_auth_tables(self, table_exists, count_rows) -> None:
        messages = api_checks.check_dmis_rbac_boundary(None)

        self.assertEqual(messages, [])
        table_exists.assert_any_call("role")
        count_rows.assert_called_once_with("auth_user")

    @override_settings(TESTING=False, AUTH_USE_DB_RBAC=True)
    @patch("api.checks._count_rows", return_value=1)
    @patch("api.checks._table_exists", return_value=True)
    def test_w002_still_warns_on_auth_user_rows(self, _table_exists, _count_rows) -> None:
        messages = api_checks.check_dmis_rbac_boundary(None)

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].id, "api.W002")
        self.assertIn("auth_user=1", messages[0].msg)
