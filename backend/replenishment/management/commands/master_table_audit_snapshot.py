from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import connection


_SAFE_TABLE_RE = re.compile(r"^[a-z_][a-z0-9_]*$")


@dataclass(frozen=True)
class TableStatus:
    table_name: str
    exists: bool
    row_count: int | None


class Command(BaseCommand):
    help = (
        "Generate a live schema snapshot for the DMIS master-table audit "
        "(table existence, row counts, and FK dependency edges)."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--format",
            choices=["text", "json", "markdown"],
            default="text",
            help="Output format (default: text).",
        )
        parser.add_argument(
            "--output",
            type=str,
            help="Optional path to write the snapshot.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        output_format = str(options["format"]).strip().lower()
        output_path = str(options.get("output") or "").strip()

        snapshot = self._collect_snapshot()
        rendered = self._render(snapshot, output_format)

        if output_path:
            target = Path(output_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(rendered, encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"Wrote snapshot to {target}"))
            return

        self.stdout.write(rendered)

    def _collect_snapshot(self) -> dict[str, Any]:
        obsolete_or_redundant = [
            "auth_user",
            "auth_group",
            "auth_group_permissions",
            "auth_permission",
            "auth_user_groups",
            "auth_user_user_permissions",
            "warehouse_sync_status",
            "custodian",
            "itemcostdef",
            "hadr_aid_movement_staging",
            "event_phase",
            "event_phase_config",
        ]
        questionable = [
            "country",
            "batchlocation",
            "item_location",
            "distribution_package",
        ]
        necessary_master_tables = [
            "agency",
            "allocation_limit",
            "allocation_rule",
            "approval_authority_matrix",
            "approval_threshold_policy",
            "country",
            "currency",
            "event",
            "event_phase_config",
            "item",
            "itemcatg",
            "lead_time_config",
            "location",
            "parish",
            "permission",
            "ref_approval_tier",
            "ref_event_phase",
            "ref_procurement_method",
            "ref_tenant_type",
            "role",
            "supplier",
            "tenant",
        ]
        missing_mvp = [
            "role_scope_policy",
            "approval_reason_code",
            "event_severity_profile",
            "resource_capability_ref",
            "allocation_priority_rule",
            "tenant_access_policy",
        ]

        tracked_tables = sorted(
            set(
                obsolete_or_redundant
                + questionable
                + necessary_master_tables
                + missing_mvp
            )
        )

        table_status = [self._table_status(table_name) for table_name in tracked_tables]
        status_by_name = {item.table_name: item for item in table_status}

        contradictions: list[str] = []
        auth_permission_count = status_by_name.get("auth_permission", TableStatus("auth_permission", False, None)).row_count
        if auth_permission_count and auth_permission_count > 0:
            contradictions.append(
                f"auth_permission contains {auth_permission_count} rows (framework metadata is populated)."
            )

        event_phase_count = status_by_name.get("event_phase", TableStatus("event_phase", False, None)).row_count or 0
        event_phase_config_count = status_by_name.get(
            "event_phase_config", TableStatus("event_phase_config", False, None)
        ).row_count or 0
        if event_phase_count > 0 and event_phase_config_count == 0:
            contradictions.append(
                "event_phase is populated while event_phase_config is empty (requires seed/backfill)."
            )

        sync_status_count = status_by_name.get(
            "warehouse_sync_status", TableStatus("warehouse_sync_status", False, None)
        ).row_count or 0
        if sync_status_count > 0:
            contradictions.append(
                f"warehouse_sync_status contains {sync_status_count} rows (drop must be staged)."
            )

        fk_edges_to_flagged = self._fk_edges_to_tables(obsolete_or_redundant + questionable)
        fk_edges_from_flagged = self._fk_edges_from_tables(obsolete_or_redundant + questionable)

        return {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "groups": {
                "obsolete_or_redundant": obsolete_or_redundant,
                "questionable": questionable,
                "necessary_master_tables": necessary_master_tables,
                "missing_mvp_candidates": missing_mvp,
            },
            "table_status": [
                {
                    "table_name": row.table_name,
                    "exists": row.exists,
                    "row_count": row.row_count,
                }
                for row in table_status
            ],
            "fk_referencing_flagged_tables": fk_edges_to_flagged,
            "fk_from_flagged_tables": fk_edges_from_flagged,
            "contradictions": contradictions,
        }

    def _table_status(self, table_name: str) -> TableStatus:
        if not _SAFE_TABLE_RE.fullmatch(table_name):
            raise CommandError(f"Unsafe table name in audit list: {table_name!r}")
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT EXISTS(
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = current_schema() AND table_name = %s
                )
                """,
                [table_name],
            )
            exists = bool(cursor.fetchone()[0])
            if not exists:
                return TableStatus(table_name=table_name, exists=False, row_count=None)

            quoted = connection.ops.quote_name(table_name)
            cursor.execute(f"SELECT COUNT(*) FROM {quoted}")
            row_count = int(cursor.fetchone()[0])
            return TableStatus(table_name=table_name, exists=True, row_count=row_count)

    def _fk_edges_to_tables(self, table_names: list[str]) -> list[dict[str, str]]:
        table_name_set = {name for name in table_names if _SAFE_TABLE_RE.fullmatch(name)}
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    tc.table_name AS referencing_table,
                    kcu.column_name AS referencing_column,
                    ccu.table_name AS referenced_table,
                    ccu.column_name AS referenced_column,
                    tc.constraint_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                JOIN information_schema.constraint_column_usage ccu
                    ON ccu.constraint_name = tc.constraint_name
                    AND ccu.table_schema = tc.table_schema
                WHERE tc.constraint_type = 'FOREIGN KEY'
                  AND tc.table_schema = current_schema()
                ORDER BY referenced_table, referencing_table, referencing_column
                """
            )
            rows = cursor.fetchall()

        edges: list[dict[str, str]] = []
        for row in rows:
            referenced_table = str(row[2])
            if referenced_table not in table_name_set:
                continue
            edges.append(
                {
                    "referencing_table": str(row[0]),
                    "referencing_column": str(row[1]),
                    "referenced_table": referenced_table,
                    "referenced_column": str(row[3]),
                    "constraint_name": str(row[4]),
                }
            )
        return edges

    def _fk_edges_from_tables(self, table_names: list[str]) -> list[dict[str, str]]:
        table_name_set = {name for name in table_names if _SAFE_TABLE_RE.fullmatch(name)}
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    tc.table_name AS referencing_table,
                    kcu.column_name AS referencing_column,
                    ccu.table_name AS referenced_table,
                    ccu.column_name AS referenced_column,
                    tc.constraint_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                JOIN information_schema.constraint_column_usage ccu
                    ON ccu.constraint_name = tc.constraint_name
                    AND ccu.table_schema = tc.table_schema
                WHERE tc.constraint_type = 'FOREIGN KEY'
                  AND tc.table_schema = current_schema()
                ORDER BY referencing_table, referencing_column
                """
            )
            rows = cursor.fetchall()

        edges: list[dict[str, str]] = []
        for row in rows:
            referencing_table = str(row[0])
            if referencing_table not in table_name_set:
                continue
            edges.append(
                {
                    "referencing_table": referencing_table,
                    "referencing_column": str(row[1]),
                    "referenced_table": str(row[2]),
                    "referenced_column": str(row[3]),
                    "constraint_name": str(row[4]),
                }
            )
        return edges

    def _render(self, snapshot: dict[str, Any], output_format: str) -> str:
        if output_format == "json":
            return json.dumps(snapshot, indent=2, sort_keys=True)
        if output_format == "markdown":
            return self._render_markdown(snapshot)
        return self._render_text(snapshot)

    def _render_text(self, snapshot: dict[str, Any]) -> str:
        lines: list[str] = []
        lines.append(f"DMIS Master Table Audit Snapshot @ {snapshot['generated_at_utc']}")
        lines.append("")
        lines.append("Table status:")
        for row in snapshot["table_status"]:
            lines.append(
                f"- {row['table_name']}: exists={row['exists']} row_count={row['row_count']}"
            )
        lines.append("")
        lines.append("Contradictions:")
        contradictions = snapshot.get("contradictions") or []
        if contradictions:
            for item in contradictions:
                lines.append(f"- {item}")
        else:
            lines.append("- none")
        lines.append("")
        lines.append("FK references to flagged tables:")
        for edge in snapshot["fk_referencing_flagged_tables"]:
            lines.append(
                f"- {edge['referencing_table']}.{edge['referencing_column']} -> "
                f"{edge['referenced_table']}.{edge['referenced_column']} "
                f"({edge['constraint_name']})"
            )
        return "\n".join(lines)

    def _render_markdown(self, snapshot: dict[str, Any]) -> str:
        lines: list[str] = []
        lines.append(f"# DMIS Master Table Audit Snapshot")
        lines.append("")
        lines.append(f"- Generated at (UTC): `{snapshot['generated_at_utc']}`")
        lines.append("")
        lines.append("## Table Status")
        lines.append("")
        lines.append("| Table | Exists | Row Count |")
        lines.append("|---|---:|---:|")
        for row in snapshot["table_status"]:
            lines.append(
                f"| `{row['table_name']}` | `{row['exists']}` | `{row['row_count']}` |"
            )
        lines.append("")
        lines.append("## Contradictions")
        lines.append("")
        contradictions = snapshot.get("contradictions") or []
        if contradictions:
            for item in contradictions:
                lines.append(f"- {item}")
        else:
            lines.append("- none")
        lines.append("")
        lines.append("## FK References To Flagged Tables")
        lines.append("")
        for edge in snapshot["fk_referencing_flagged_tables"]:
            lines.append(
                f"- `{edge['referencing_table']}.{edge['referencing_column']}` -> "
                f"`{edge['referenced_table']}.{edge['referenced_column']}` "
                f"(`{edge['constraint_name']}`)"
            )
        lines.append("")
        lines.append("## FK References From Flagged Tables")
        lines.append("")
        for edge in snapshot["fk_from_flagged_tables"]:
            lines.append(
                f"- `{edge['referencing_table']}.{edge['referencing_column']}` -> "
                f"`{edge['referenced_table']}.{edge['referenced_column']}` "
                f"(`{edge['constraint_name']}`)"
            )
        return "\n".join(lines)

