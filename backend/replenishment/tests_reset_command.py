from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

from django.core.management.base import CommandError
from django.test import SimpleTestCase

from replenishment.management.commands.reset_needs_lists import Command


class ResetNeedsListsCommandTests(SimpleTestCase):
    def test_execute_requires_backup_dir(self) -> None:
        command = Command()

        with self.assertRaises(CommandError):
            command.handle(execute=True, allow_prod=False, backup_dir="")

    def test_dry_run_does_not_mutate(self) -> None:
        command = Command()

        with patch.object(command, "_assert_db_backed_workflow"), patch.object(
            command, "_assert_non_prod_or_allowed"
        ), patch.object(command, "_collect_counts", return_value={"needs": {}, "queue": {}, "linked": {}}), patch.object(
            command, "_write_backups"
        ) as write_backups, patch.object(command, "_detach_links") as detach_links, patch.object(
            command, "_delete_needs_data"
        ) as delete_data, patch.object(command, "_reset_identities") as reset_ids:
            command.handle(execute=False, allow_prod=False, backup_dir="")

        write_backups.assert_not_called()
        detach_links.assert_not_called()
        delete_data.assert_not_called()
        reset_ids.assert_not_called()

    def test_execute_writes_backup_and_runs_reset_steps(self) -> None:
        command = Command()

        with patch.object(command, "_assert_db_backed_workflow"), patch.object(
            command, "_assert_non_prod_or_allowed"
        ), patch.object(
            command,
            "_collect_counts",
            side_effect=[
                {"needs": {"total_needs_lists": 3}, "queue": {"queue_visible_total": 2}, "linked": {}},
                {"needs": {"total_needs_lists": 0}, "queue": {"queue_visible_total": 0}, "linked": {}},
            ],
        ), patch.object(command, "_write_backups") as write_backups, patch.object(
            command, "_lock_tables"
        ) as lock_tables, patch.object(
            command, "_detach_links", return_value={"transfer": 0, "procurement": 0, "procurement_item": 0}
        ) as detach_links, patch.object(
            command,
            "_delete_needs_data",
            return_value={
                "needs_list_workflow_metadata": 0,
                "needs_list_audit": 0,
                "needs_list_item": 0,
                "needs_list": 3,
            },
        ) as delete_data, patch.object(command, "_reset_identities") as reset_ids, patch.object(
            command, "_db_name", return_value="dmis_dev"
        ), patch(
            "replenishment.management.commands.reset_needs_lists.transaction.atomic",
            return_value=nullcontext(),
        ):
from tempfile import TemporaryDirectory

            with TemporaryDirectory() as tmpdir:
                backup_dir = Path(tmpdir).resolve()
                command.handle(execute=True, allow_prod=False, backup_dir=str(backup_dir))
        write_backups.assert_called_once()
        lock_tables.assert_called_once()
        detach_links.assert_called_once()
        delete_data.assert_called_once()
        reset_ids.assert_called_once()
