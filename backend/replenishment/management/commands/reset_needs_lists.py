from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

NEEDS_TABLES = (
    "needs_list",
    "needs_list_item",
    "needs_list_audit",
    "needs_list_workflow_metadata",
)

QUEUE_STATUSES = (
    "DRAFT",
    "RETURNED",
    "PENDING_APPROVAL",
    "UNDER_REVIEW",
    "APPROVED",
    "IN_PROGRESS",
)


class Command(BaseCommand):
    help = (
        "Reset needs-list workflow data safely. Dry-run by default. "
        "Use --execute to apply changes."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--execute",
            action="store_true",
            help="Apply reset changes. Without this flag, command runs as dry-run.",
        )
        parser.add_argument(
            "--allow-prod",
            action="store_true",
            help="Allow execution against a database that appears production-like.",
        )
        parser.add_argument(
            "--backup-dir",
            type=str,
            default="",
            help=(
                "Directory path to write CSV backups and summary metadata. "
                "Required when using --execute."
            ),
        )

    def handle(self, *args, **options) -> None:
        execute = bool(options["execute"])
        allow_prod = bool(options["allow_prod"])
        backup_dir = str(options.get("backup_dir") or "").strip()

        if execute and not backup_dir:
            raise CommandError("--backup-dir is required when --execute is provided.")

        self._assert_db_backed_workflow()
        self._assert_non_prod_or_allowed(allow_prod)

        pre_counts = self._collect_counts()
        self.stdout.write(self.style.WARNING("Needs-list reset preflight summary:"))
        self.stdout.write(json.dumps(pre_counts, indent=2, sort_keys=True))

        if not execute:
            self.stdout.write(self.style.SUCCESS("Dry-run complete. No data changed."))
            return

        backup_path = Path(backup_dir).resolve()
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_path = backup_path / f"needs_list_reset_{timestamp}"
        run_path.mkdir(parents=True, exist_ok=True)

        self._write_backups(run_path)

        with transaction.atomic():
            self._lock_tables()
            detached = self._detach_links()
            deleted = self._delete_needs_data()
            self._reset_identities()

        post_counts = self._collect_counts()
        outcome = {
            "detached": detached,
            "deleted": deleted,
            "pre_counts": pre_counts,
            "post_counts": post_counts,
            "executed_at_utc": timestamp,
            "database": self._db_name(),
        }
        (run_path / "reset_outcome.json").write_text(
            json.dumps(outcome, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        if post_counts["needs"]["total_needs_lists"] != 0:
            raise CommandError("Reset failed: needs_list still contains rows after execution.")

        if post_counts["queue"]["queue_visible_total"] != 0:
            raise CommandError("Reset failed: queue-visible needs lists remain after execution.")

        self.stdout.write(self.style.SUCCESS("Needs-list reset complete."))
        self.stdout.write(f"Backup and report directory: {run_path}")

    def _assert_db_backed_workflow(self) -> None:
        engine = str(settings.DATABASES.get("default", {}).get("ENGINE", "")).lower()
        use_db = bool(getattr(settings, "AUTH_USE_DB_RBAC", False)) and "postgresql" in engine
        if not use_db:
            raise CommandError(
                "Refusing reset: DB-backed workflow store is not active (requires AUTH_USE_DB_RBAC + PostgreSQL)."
            )

    def _assert_non_prod_or_allowed(self, allow_prod: bool) -> None:
        if allow_prod:
            return

        db_name = self._db_name().lower()
        env_name = str(getattr(settings, "ENVIRONMENT", "")).lower()
        suspicious = ("prod", "production", "live")
        looks_prod = any(token in db_name for token in suspicious) or env_name in suspicious

        if looks_prod:
            raise CommandError(
                "Database appears production-like. Use non-prod DB or rerun with --allow-prod after explicit approval."
            )

    def _db_name(self) -> str:
        return str(settings.DATABASES.get("default", {}).get("NAME", ""))

    def _table_exists(self, table_name: str) -> bool:
        return table_name in connection.introspection.table_names()

    def _column_exists(self, table_name: str, column_name: str) -> bool:
        if not self._table_exists(table_name):
            return False
        with connection.cursor() as cursor:
            description = connection.introspection.get_table_description(cursor, table_name)
        return any(col.name == column_name for col in description)

    def _scalar(self, sql: str) -> int:
        with connection.cursor() as cursor:
            cursor.execute(sql)
            row = cursor.fetchone()
        return int(row[0] if row else 0)

    def _collect_counts(self) -> dict[str, Any]:
        needs_counts = {
            "total_needs_lists": self._scalar("SELECT COUNT(*) FROM needs_list") if self._table_exists("needs_list") else 0,
            "total_needs_list_items": self._scalar("SELECT COUNT(*) FROM needs_list_item") if self._table_exists("needs_list_item") else 0,
            "total_needs_list_audits": self._scalar("SELECT COUNT(*) FROM needs_list_audit") if self._table_exists("needs_list_audit") else 0,
            "total_workflow_metadata": self._scalar("SELECT COUNT(*) FROM needs_list_workflow_metadata") if self._table_exists("needs_list_workflow_metadata") else 0,
        }

        queue_total = 0
        if self._table_exists("needs_list"):
            statuses = ",".join([f"'{s}'" for s in QUEUE_STATUSES])
            queue_total = self._scalar(
                f"SELECT COUNT(*) FROM needs_list WHERE UPPER(status_code) IN ({statuses})"
            )

        linked_counts = {
            "transfer_links": self._scalar("SELECT COUNT(*) FROM transfer WHERE needs_list_id IS NOT NULL")
            if self._column_exists("transfer", "needs_list_id")
            else 0,
            "procurement_links": self._scalar("SELECT COUNT(*) FROM procurement WHERE needs_list_id IS NOT NULL")
            if self._column_exists("procurement", "needs_list_id")
            else 0,
            "procurement_item_links": self._scalar("SELECT COUNT(*) FROM procurement_item WHERE needs_list_item_id IS NOT NULL")
            if self._column_exists("procurement_item", "needs_list_item_id")
            else 0,
        }

        return {
            "needs": needs_counts,
            "queue": {"queue_visible_total": queue_total},
            "linked": linked_counts,
        }

    def _write_backups(self, run_path: Path) -> None:
        summary = self._collect_counts()
        (run_path / "pre_reset_counts.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        self._export_csv("needs_list", "SELECT * FROM needs_list", run_path / "needs_list.csv")
        self._export_csv("needs_list_item", "SELECT * FROM needs_list_item", run_path / "needs_list_item.csv")
        self._export_csv("needs_list_audit", "SELECT * FROM needs_list_audit", run_path / "needs_list_audit.csv")

        if self._table_exists("needs_list_workflow_metadata"):
            self._export_csv(
                "needs_list_workflow_metadata",
                "SELECT * FROM needs_list_workflow_metadata",
                run_path / "needs_list_workflow_metadata.csv",
            )

        if self._column_exists("transfer", "needs_list_id"):
            self._export_csv(
                "transfer",
                "SELECT * FROM transfer WHERE needs_list_id IS NOT NULL",
                run_path / "transfer_linked_rows.csv",
            )

        if self._column_exists("procurement", "needs_list_id"):
            self._export_csv(
                "procurement",
                "SELECT * FROM procurement WHERE needs_list_id IS NOT NULL",
                run_path / "procurement_linked_rows.csv",
            )

        if self._column_exists("procurement_item", "needs_list_item_id"):
            self._export_csv(
                "procurement_item",
                "SELECT * FROM procurement_item WHERE needs_list_item_id IS NOT NULL",
                run_path / "procurement_item_linked_rows.csv",
            )

    def _export_csv(self, table_name: str, sql: str, path: Path) -> None:
        if not self._table_exists(table_name):
            return

        with connection.cursor() as cursor:
            cursor.execute(sql)
            columns = [col[0] for col in cursor.description]
            rows = cursor.fetchall()

        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(columns)
            writer.writerows(rows)

    def _lock_tables(self) -> None:
        if connection.vendor != "postgresql":
            return

        locks = []
        for table in ("needs_list", "needs_list_item", "needs_list_audit"):
            if self._table_exists(table):
                locks.append(table)
        if self._table_exists("needs_list_workflow_metadata"):
            locks.append("needs_list_workflow_metadata")

        if not locks:
            return

        sql = "LOCK TABLE " + ", ".join(locks) + " IN SHARE ROW EXCLUSIVE MODE"
        with connection.cursor() as cursor:
            cursor.execute(sql)

    def _detach_links(self) -> dict[str, int]:
        detached = {
            "transfer": 0,
            "procurement": 0,
            "procurement_item": 0,
        }

        with connection.cursor() as cursor:
            if self._column_exists("transfer", "needs_list_id"):
                cursor.execute("UPDATE transfer SET needs_list_id = NULL WHERE needs_list_id IS NOT NULL")
                detached["transfer"] = cursor.rowcount

            if self._column_exists("procurement", "needs_list_id"):
                cursor.execute("UPDATE procurement SET needs_list_id = NULL WHERE needs_list_id IS NOT NULL")
                detached["procurement"] = cursor.rowcount

            if self._column_exists("procurement_item", "needs_list_item_id"):
                cursor.execute(
                    "UPDATE procurement_item SET needs_list_item_id = NULL WHERE needs_list_item_id IS NOT NULL"
                )
                detached["procurement_item"] = cursor.rowcount

        return detached

    def _delete_needs_data(self) -> dict[str, int]:
        deleted = {
            "needs_list_workflow_metadata": 0,
            "needs_list_audit": 0,
            "needs_list_item": 0,
            "needs_list": 0,
        }

        with connection.cursor() as cursor:
            if self._table_exists("needs_list_workflow_metadata"):
                cursor.execute("DELETE FROM needs_list_workflow_metadata")
                deleted["needs_list_workflow_metadata"] = cursor.rowcount

            if self._table_exists("needs_list_audit"):
                cursor.execute("DELETE FROM needs_list_audit")
                deleted["needs_list_audit"] = cursor.rowcount

            if self._table_exists("needs_list_item"):
                cursor.execute("DELETE FROM needs_list_item")
                deleted["needs_list_item"] = cursor.rowcount

            if self._table_exists("needs_list"):
                cursor.execute("DELETE FROM needs_list")
                deleted["needs_list"] = cursor.rowcount

        return deleted

    def _reset_identities(self) -> None:
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                for table, pk in (
                    ("needs_list", "needs_list_id"),
                    ("needs_list_item", "needs_list_item_id"),
                    ("needs_list_audit", "audit_id"),
                ):
                    if not self._table_exists(table):
                        continue
                    cursor.execute("SELECT pg_get_serial_sequence(%s, %s)", [table, pk])
                    row = cursor.fetchone()
                    sequence_name = row[0] if row else None
                    if sequence_name:
                        cursor.execute("ALTER SEQUENCE " + sequence_name + " RESTART WITH 1")
            return

        if connection.vendor == "sqlite":
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM sqlite_sequence WHERE name IN ('needs_list','needs_list_item','needs_list_audit')"
                )
