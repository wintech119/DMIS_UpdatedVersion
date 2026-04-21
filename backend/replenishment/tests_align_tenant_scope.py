from __future__ import annotations

from datetime import datetime
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from replenishment.management.commands.align_tenant_scope import Command


@override_settings(AUTH_ENABLED=False, DEV_AUTH_ENABLED=True, TEST_DEV_AUTH_ENABLED=True)
class AlignTenantScopeCommandTests(SimpleTestCase):
    @patch("replenishment.management.commands.align_tenant_scope.lock_primary_tenant_membership")
    @patch("replenishment.management.commands.align_tenant_scope.connection")
    def test_set_primary_tenant_for_users_locks_each_user_before_updates(
        self,
        mock_connection,
        lock_primary_tenant_membership_mock,
    ) -> None:
        cursor = mock_connection.cursor.return_value.__enter__.return_value

        Command()._set_primary_tenant_for_users(user_ids=[101, 102], target_tenant_id=19)

        self.assertEqual(
            lock_primary_tenant_membership_mock.call_args_list,
            [
                ((cursor,), {"user_id": 101}),
                ((cursor,), {"user_id": 102}),
            ],
        )
        self.assertEqual(len(cursor.execute.call_args_list), 4)
        first_reset_sql, first_reset_params = cursor.execute.call_args_list[0].args
        first_set_sql, first_set_params = cursor.execute.call_args_list[1].args
        self.assertIn("SET is_primary_tenant = FALSE", first_reset_sql)
        self.assertEqual(first_reset_params, [101])
        self.assertIn("SET is_primary_tenant = TRUE", first_set_sql)
        self.assertEqual(first_set_params, [101, 19])

    @patch("replenishment.management.commands.align_tenant_scope.Command._validate_tenant_exists")
    @patch("replenishment.management.commands.align_tenant_scope.Command._active_memberships", return_value=[])
    @patch("replenishment.management.commands.align_tenant_scope.Command._owned_warehouse_ids", return_value=[1, 2])
    def test_handle_supports_warehouse_reassignment_without_source_memberships(
        self,
        _owned_warehouse_ids_mock,
        _active_memberships_mock,
        _validate_tenant_exists_mock,
    ) -> None:
        output = StringIO()

        call_command(
            "align_tenant_scope",
            from_tenant_id=27,
            to_tenant_id=1,
            reassign_owned_warehouses=True,
            warehouse_ids="[1, 2]",
            stdout=output,
        )

        text = output.getvalue()
        self.assertIn("owned warehouses to reassign: 2", text)
        self.assertIn("warehouse scope: 1, 2", text)
        self.assertIn("Dry-run only", text)

    @patch("replenishment.management.commands.align_tenant_scope.Command._validate_tenant_exists")
    @patch(
        "replenishment.management.commands.align_tenant_scope.Command._active_memberships",
        return_value=[object(), object()],
    )
    @patch("replenishment.management.commands.align_tenant_scope.Command._owned_warehouse_ids", return_value=[1, 2])
    def test_handle_can_skip_membership_copy_for_warehouse_only_repairs(
        self,
        _owned_warehouse_ids_mock,
        _active_memberships_mock,
        _validate_tenant_exists_mock,
    ) -> None:
        output = StringIO()

        call_command(
            "align_tenant_scope",
            from_tenant_id=27,
            to_tenant_id=1,
            skip_membership_copy=True,
            reassign_owned_warehouses=True,
            warehouse_ids="[1, 2]",
            stdout=output,
        )

        text = output.getvalue()
        self.assertIn("copy source memberships: False", text)
        self.assertIn("source active memberships: 0", text)
        self.assertIn("new memberships to create: 0", text)
        self.assertIn("Dry-run only", text)

    @patch("replenishment.management.commands.align_tenant_scope.connection")
    def test_owned_warehouse_ids_rejects_requested_ids_outside_source_tenant(self, mock_connection) -> None:
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [(1,), (2,)]

        with self.assertRaisesMessage(
            CommandError,
            "Warehouses 3 are not currently owned by tenant 27.",
        ):
            Command()._owned_warehouse_ids(27, warehouse_ids=[1, 2, 3])

    @patch("replenishment.management.commands.align_tenant_scope.timezone.localdate", return_value=datetime(2026, 4, 18).date())
    @patch("replenishment.management.commands.align_tenant_scope.connection")
    def test_reassign_owned_warehouses_replaces_source_scope_and_updates_owner(
        self,
        mock_connection,
        _localdate_mock,
    ) -> None:
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [(1,), (2,)]
        now = datetime(2026, 4, 18, 9, 30, 0)

        Command()._reassign_owned_warehouses(
            from_tenant_id=27,
            to_tenant_id=1,
            warehouse_ids=[1, 2],
            actor_ref="SYSTEM",
            now=now,
        )

        delete_sql, delete_params = cursor.execute.call_args_list[0].args
        update_sql, update_params = cursor.execute.call_args_list[1].args
        upsert_sql = cursor.executemany.call_args.args[0]
        upsert_rows = cursor.executemany.call_args.args[1]

        self.assertIn("DELETE FROM tenant_warehouse", delete_sql)
        self.assertEqual(delete_params, [27, 1, 2])
        self.assertIn("UPDATE warehouse", update_sql)
        self.assertEqual(update_params, [1, "SYSTEM", now, 27, 1, 2])
        self.assertIn("ON CONFLICT (tenant_id, warehouse_id) DO UPDATE", upsert_sql)
        self.assertEqual(
            upsert_rows,
            [
                [1, 1, "OWNED", "FULL", datetime(2026, 4, 18).date(), None, "SYSTEM", now],
                [1, 2, "OWNED", "FULL", datetime(2026, 4, 18).date(), None, "SYSTEM", now],
            ],
        )

    @patch("replenishment.management.commands.align_tenant_scope.timezone.localdate", return_value=datetime(2026, 4, 18).date())
    @patch("replenishment.management.commands.align_tenant_scope.connection")
    def test_reassign_owned_warehouses_upserts_only_updated_warehouses(
        self,
        mock_connection,
        _localdate_mock,
    ) -> None:
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [(2,)]
        now = datetime(2026, 4, 18, 9, 30, 0)

        Command()._reassign_owned_warehouses(
            from_tenant_id=27,
            to_tenant_id=1,
            warehouse_ids=[1, 2],
            actor_ref="SYSTEM",
            now=now,
        )

        upsert_rows = cursor.executemany.call_args.args[1]
        self.assertEqual(
            upsert_rows,
            [[1, 2, "OWNED", "FULL", datetime(2026, 4, 18).date(), None, "SYSTEM", now]],
        )

    def test_parse_positive_int_list_requires_json_array(self) -> None:
        with self.assertRaisesMessage(
            CommandError,
            "--warehouse-ids must be a JSON array of positive integers.",
        ):
            Command()._parse_positive_int_list("1,2")

    def test_parse_positive_int_list_enforces_max_length(self) -> None:
        with self.assertRaisesMessage(
            CommandError,
            "--warehouse-ids must not contain more than 100 items.",
        ):
            Command()._parse_positive_int_list(list(range(1, 102)))

    def test_handle_rejects_actor_values_that_exceed_audit_column_width(self) -> None:
        with self.assertRaisesMessage(CommandError, "actor value too long"):
            call_command(
                "align_tenant_scope",
                from_tenant_id=27,
                to_tenant_id=1,
                actor="THIS-ACTOR-VALUE-IS-TOO-LONG",
                stdout=StringIO(),
            )
