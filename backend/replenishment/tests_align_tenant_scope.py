from __future__ import annotations

from unittest.mock import patch

from django.test import SimpleTestCase

from replenishment.management.commands.align_tenant_scope import Command


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
