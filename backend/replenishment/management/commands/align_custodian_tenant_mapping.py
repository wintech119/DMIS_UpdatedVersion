from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from django.core.management.base import BaseCommand
from django.db import connection, transaction


def _norm(value: object) -> str:
    text = str(value or "").upper()
    text = re.sub(r"[^A-Z0-9]+", "", text)
    return text.strip()


@dataclass
class CustodianRow:
    custodian_id: int
    custodian_name: str
    tenant_id: int | None
    suggested_tenant_id: int | None
    suggested_source: str | None
    warehouse_count: int
    donation_count: int


class Command(BaseCommand):
    help = (
        "Assess and optionally backfill custodian.tenant_id alignment. "
        "Only NULL tenant_id rows are updated when a deterministic mapping exists."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--actor",
            type=str,
            default="SYSTEM",
            help="Actor used for audit fields when applying updates.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Apply safe backfills (NULL -> deterministic tenant_id).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        actor = str(options.get("actor") or "SYSTEM").strip()[:20] or "SYSTEM"
        apply_changes = bool(options.get("apply"))

        rows = self._build_alignment_rows()
        to_backfill = [row for row in rows if row.tenant_id is None and row.suggested_tenant_id is not None]
        mismatches = [
            row
            for row in rows
            if row.tenant_id is not None
            and row.suggested_tenant_id is not None
            and row.tenant_id != row.suggested_tenant_id
        ]

        self.stdout.write("Custodian -> tenant alignment report:")
        self.stdout.write(f"- custodians: {len(rows)}")
        self.stdout.write(f"- safe backfill candidates (NULL tenant_id): {len(to_backfill)}")
        self.stdout.write(f"- mismatches (manual review): {len(mismatches)}")
        self.stdout.write(f"- apply mode: {apply_changes}")

        for row in rows:
            self.stdout.write(
                f"- custodian_id={row.custodian_id} "
                f"name={row.custodian_name!r} "
                f"tenant_id={row.tenant_id} "
                f"suggested={row.suggested_tenant_id} "
                f"source={row.suggested_source} "
                f"warehouses={row.warehouse_count} donations={row.donation_count}"
            )

        if not apply_changes:
            self.stdout.write(
                self.style.WARNING("Dry-run only. Re-run with --apply to persist safe backfills.")
            )
            return

        if not to_backfill:
            self.stdout.write(self.style.SUCCESS("No safe custodian tenant backfills required."))
            return

        updated = 0
        with transaction.atomic():
            with connection.cursor() as cursor:
                for row in to_backfill:
                    cursor.execute(
                        """
                        UPDATE custodian
                        SET
                            tenant_id = %s,
                            update_by_id = %s,
                            update_dtime = CURRENT_TIMESTAMP,
                            version_nbr = COALESCE(version_nbr, 0) + 1
                        WHERE custodian_id = %s
                          AND tenant_id IS NULL
                        """,
                        [row.suggested_tenant_id, actor, row.custodian_id],
                    )
                    updated += int(cursor.rowcount or 0)

        self.stdout.write(self.style.SUCCESS(f"Backfill complete. Rows updated: {updated}"))

    def _build_alignment_rows(self) -> list[CustodianRow]:
        tenants = self._load_active_tenants()
        tenant_by_norm_name = {_norm(row["tenant_name"]): row["tenant_id"] for row in tenants}
        by_warehouse = self._warehouse_inferred_mapping()
        donation_counts = self._donation_counts()
        warehouse_counts = self._warehouse_counts()

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT custodian_id, custodian_name, tenant_id
                FROM custodian
                ORDER BY custodian_id
                """
            )
            raw = cursor.fetchall()

        rows: list[CustodianRow] = []
        for entry in raw:
            custodian_id = int(entry[0])
            custodian_name = str(entry[1] or "").strip()
            tenant_id = int(entry[2]) if entry[2] is not None else None

            suggested_tenant_id = None
            suggested_source = None

            inferred = by_warehouse.get(custodian_id)
            if inferred is not None:
                suggested_tenant_id = inferred
                suggested_source = "warehouse_majority"
            else:
                matched = tenant_by_norm_name.get(_norm(custodian_name))
                if matched is not None:
                    suggested_tenant_id = matched
                    suggested_source = "tenant_name_match"

            rows.append(
                CustodianRow(
                    custodian_id=custodian_id,
                    custodian_name=custodian_name,
                    tenant_id=tenant_id,
                    suggested_tenant_id=suggested_tenant_id,
                    suggested_source=suggested_source,
                    warehouse_count=warehouse_counts.get(custodian_id, 0),
                    donation_count=donation_counts.get(custodian_id, 0),
                )
            )
        return rows

    def _load_active_tenants(self) -> list[dict[str, Any]]:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT tenant_id, tenant_name
                FROM tenant
                WHERE COALESCE(status_code, 'A') = 'A'
                ORDER BY tenant_id
                """
            )
            rows = cursor.fetchall()
        return [{"tenant_id": int(row[0]), "tenant_name": str(row[1] or "")} for row in rows]

    def _warehouse_inferred_mapping(self) -> dict[int, int]:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    custodian_id,
                    tenant_id,
                    COUNT(*) AS row_count
                FROM warehouse
                WHERE custodian_id IS NOT NULL
                  AND tenant_id IS NOT NULL
                GROUP BY custodian_id, tenant_id
                ORDER BY custodian_id, row_count DESC, tenant_id
                """
            )
            rows = cursor.fetchall()

        grouped: dict[int, list[tuple[int, int]]] = {}
        for row in rows:
            custodian_id = int(row[0])
            tenant_id = int(row[1])
            row_count = int(row[2])
            grouped.setdefault(custodian_id, []).append((tenant_id, row_count))

        inferred: dict[int, int] = {}
        for custodian_id, tenant_rows in grouped.items():
            distinct_tenants = {tenant_id for tenant_id, _ in tenant_rows}
            if len(distinct_tenants) == 1:
                inferred[custodian_id] = tenant_rows[0][0]
        return inferred

    def _donation_counts(self) -> dict[int, int]:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT custodian_id, COUNT(*)
                FROM donation
                WHERE custodian_id IS NOT NULL
                GROUP BY custodian_id
                """
            )
            rows = cursor.fetchall()
        return {int(row[0]): int(row[1]) for row in rows}

    def _warehouse_counts(self) -> dict[int, int]:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT custodian_id, COUNT(*)
                FROM warehouse
                WHERE custodian_id IS NOT NULL
                GROUP BY custodian_id
                """
            )
            rows = cursor.fetchall()
        return {int(row[0]): int(row[1]) for row in rows}

