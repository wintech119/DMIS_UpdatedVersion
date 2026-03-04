from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = (
        "Verify parity between warehouse.sync_status (trigger-driven current state) "
        "and warehouse_sync_status rows."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--show-matches",
            action="store_true",
            help="Print rows where warehouse_sync_status matches expected status.",
        )
        parser.add_argument(
            "--repair-shadow",
            action="store_true",
            help="Update warehouse_sync_status rows to expected status for detected mismatches.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        show_matches = bool(options.get("show_matches"))
        repair_shadow = bool(options.get("repair_shadow"))
        rows = self._load_rows()

        matched = 0
        mismatched = 0
        missing_shadow = 0
        extra_shadow = 0

        self.stdout.write("Warehouse sync parity report:")
        self.stdout.write(f"- warehouse rows evaluated: {len(rows)}")
        self.stdout.write(f"- repair mode: {repair_shadow}")

        for row in rows:
            warehouse_id = int(row["warehouse_id"])
            warehouse_name = row["warehouse_name"]
            current_status = row["current_status"]
            expected_status = row["expected_status"]
            shadow_status = row["shadow_status"]

            if shadow_status is None:
                missing_shadow += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"[MISSING] W{warehouse_id} {warehouse_name}: "
                        f"expected={expected_status}, shadow_row=missing"
                    )
                )
                continue

            if shadow_status == expected_status and current_status == expected_status:
                matched += 1
                if show_matches:
                    self.stdout.write(
                        f"[OK] W{warehouse_id} {warehouse_name}: status={expected_status}"
                    )
                continue

            mismatched += 1
            self.stdout.write(
                self.style.WARNING(
                    f"[MISMATCH] W{warehouse_id} {warehouse_name}: "
                    f"warehouse.sync_status={current_status}, "
                    f"expected={expected_status}, shadow={shadow_status}"
                )
            )

            if repair_shadow:
                self._repair_shadow_status(
                    warehouse_id=warehouse_id,
                    expected_status=expected_status,
                )

        # Shadow rows without matching warehouse are also drift.
        extra_shadow = self._count_orphan_shadow_rows()
        if extra_shadow:
            self.stdout.write(
                self.style.WARNING(
                    f"[ORPHAN] warehouse_sync_status rows without warehouse parent: {extra_shadow}"
                )
            )

        self.stdout.write("Summary:")
        self.stdout.write(f"- matched: {matched}")
        self.stdout.write(f"- mismatched: {mismatched}")
        self.stdout.write(f"- missing_shadow_rows: {missing_shadow}")
        self.stdout.write(f"- orphan_shadow_rows: {extra_shadow}")
        if repair_shadow:
            self.stdout.write(
                self.style.SUCCESS(
                    "Applied repairs to warehouse_sync_status mismatches where shadow rows existed."
                )
            )

    def _load_rows(self) -> list[dict[str, Any]]:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    w.warehouse_id,
                    w.warehouse_name,
                    w.sync_status AS current_status,
                    CASE
                        WHEN w.last_sync_dtime IS NULL THEN 'UNKNOWN'
                        WHEN w.last_sync_dtime > NOW() - INTERVAL '2 hours' THEN 'ONLINE'
                        WHEN w.last_sync_dtime > NOW() - INTERVAL '6 hours' THEN 'STALE'
                        ELSE 'OFFLINE'
                    END AS expected_status,
                    ws.sync_status AS shadow_status
                FROM warehouse w
                LEFT JOIN warehouse_sync_status ws
                    ON ws.warehouse_id = w.warehouse_id
                ORDER BY w.warehouse_id
                """
            )
            fetched = cursor.fetchall()

        rows: list[dict[str, Any]] = []
        for row in fetched:
            rows.append(
                {
                    "warehouse_id": int(row[0]),
                    "warehouse_name": str(row[1] or "").strip(),
                    "current_status": str(row[2] or "").strip() or None,
                    "expected_status": str(row[3] or "").strip() or None,
                    "shadow_status": str(row[4] or "").strip() or None,
                }
            )
        return rows

    def _count_orphan_shadow_rows(self) -> int:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM warehouse_sync_status ws
                LEFT JOIN warehouse w ON w.warehouse_id = ws.warehouse_id
                WHERE w.warehouse_id IS NULL
                """
            )
            return int(cursor.fetchone()[0])

    def _repair_shadow_status(self, *, warehouse_id: int, expected_status: str | None) -> None:
        if expected_status is None:
            return
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE warehouse_sync_status
                SET sync_status = %s
                WHERE warehouse_id = %s
                """,
                [expected_status, warehouse_id],
            )
