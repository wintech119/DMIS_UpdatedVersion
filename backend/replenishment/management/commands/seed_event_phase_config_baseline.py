from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.core.management.base import BaseCommand
from django.db import connection, transaction

from replenishment import rules
from replenishment.models import EventPhaseConfig


class Command(BaseCommand):
    help = (
        "Seed/backfill event_phase_config rows from event_phase snapshots "
        "and rules defaults, and document snapshot semantics on event_phase columns."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--actor",
            type=str,
            default="SYSTEM",
            help="Actor stamp for create_by_id/update_by_id (default: SYSTEM).",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Apply changes. Without this flag the command runs in dry-run mode.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        actor = str(options.get("actor") or "SYSTEM").strip()[:20] or "SYSTEM"
        apply_changes = bool(options.get("apply"))

        phase_rows = self._load_event_phase_rows()
        fallback_rows = self._load_event_current_phase_rows()

        self.stdout.write("Event phase config baseline plan:")
        self.stdout.write(f"- event_phase rows discovered: {len(phase_rows)}")
        self.stdout.write(f"- event current_phase fallback rows: {len(fallback_rows)}")
        self.stdout.write(f"- apply mode: {apply_changes}")

        if not apply_changes:
            self.stdout.write(
                self.style.WARNING("Dry-run only. Re-run with --apply to persist changes.")
            )
            return

        created = 0
        updated = 0
        untouched = 0

        with transaction.atomic():
            for row in phase_rows:
                changed = self._upsert_phase_config(
                    event_id=row["event_id"],
                    phase=row["phase"],
                    demand_hours=row["demand_hours"],
                    planning_hours=row["planning_hours"],
                    actor=actor,
                )
                if changed == "created":
                    created += 1
                elif changed == "updated":
                    updated += 1
                else:
                    untouched += 1

            for row in fallback_rows:
                changed = self._upsert_phase_config(
                    event_id=row["event_id"],
                    phase=row["phase"],
                    demand_hours=row["demand_hours"],
                    planning_hours=row["planning_hours"],
                    actor=actor,
                )
                if changed == "created":
                    created += 1
                elif changed == "updated":
                    updated += 1
                else:
                    untouched += 1

            self._apply_snapshot_comments()

        self.stdout.write(self.style.SUCCESS("event_phase_config baseline completed."))
        self.stdout.write(f"- created: {created}")
        self.stdout.write(f"- updated: {updated}")
        self.stdout.write(f"- unchanged: {untouched}")

    def _load_event_phase_rows(self) -> list[dict[str, Any]]:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    event_id,
                    UPPER(TRIM(phase_code)) AS phase_code,
                    demand_window_hours,
                    planning_window_hours
                FROM event_phase
                WHERE phase_code IS NOT NULL
                ORDER BY event_id, phase_code
                """
            )
            rows = cursor.fetchall()

        out: list[dict[str, Any]] = []
        for row in rows:
            phase = str(row[1] or "").strip().upper()
            if phase not in rules.PHASES:
                continue
            out.append(
                {
                    "event_id": int(row[0]),
                    "phase": phase,
                    "demand_hours": int(row[2]) if row[2] is not None else int(rules.get_phase_windows(phase)["demand_hours"]),
                    "planning_hours": int(row[3]) if row[3] is not None else int(rules.get_phase_windows(phase)["planning_hours"]),
                }
            )
        return out

    def _load_event_current_phase_rows(self) -> list[dict[str, Any]]:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT event_id, UPPER(TRIM(current_phase)) AS current_phase
                FROM event
                WHERE
                    current_phase IS NOT NULL
                    AND COALESCE(status_code, 'A') = 'A'
                ORDER BY event_id
                """
            )
            rows = cursor.fetchall()

        out: list[dict[str, Any]] = []
        for row in rows:
            phase = str(row[1] or "").strip().upper()
            if phase not in rules.PHASES:
                continue
            windows = rules.get_phase_windows(phase)
            out.append(
                {
                    "event_id": int(row[0]),
                    "phase": phase,
                    "demand_hours": int(windows["demand_hours"]),
                    "planning_hours": int(windows["planning_hours"]),
                }
            )
        return out

    def _upsert_phase_config(
        self,
        *,
        event_id: int,
        phase: str,
        demand_hours: int,
        planning_hours: int,
        actor: str,
    ) -> str:
        fresh_threshold = int(
            rules.FRESHNESS_THRESHOLDS.get(phase, {}).get("fresh_max_hours", 2)
        )
        stale_threshold = int(
            rules.FRESHNESS_THRESHOLDS.get(phase, {}).get("warn_max_hours", 6)
        )

        existing = (
            EventPhaseConfig.objects
            .select_for_update()
            .filter(event_id=event_id, phase=phase)
            .first()
        )

        if existing is None:
            EventPhaseConfig.objects.create(
                event_id=event_id,
                phase=phase,
                demand_window_hours=int(demand_hours),
                planning_window_hours=int(planning_hours),
                safety_buffer_pct=Decimal("25.00"),
                safety_factor=Decimal("1.25"),
                freshness_threshold_hours=fresh_threshold,
                stale_threshold_hours=stale_threshold,
                is_active=True,
                create_by_id=actor,
                update_by_id=actor,
                version_nbr=1,
            )
            return "created"

        changed = False
        if int(existing.demand_window_hours) != int(demand_hours):
            existing.demand_window_hours = int(demand_hours)
            changed = True
        if int(existing.planning_window_hours) != int(planning_hours):
            existing.planning_window_hours = int(planning_hours)
            changed = True
        if int(existing.freshness_threshold_hours) != int(fresh_threshold):
            existing.freshness_threshold_hours = int(fresh_threshold)
            changed = True
        if int(existing.stale_threshold_hours) != int(stale_threshold):
            existing.stale_threshold_hours = int(stale_threshold)
            changed = True
        if existing.is_active is not True:
            existing.is_active = True
            changed = True

        if not changed:
            return "unchanged"

        existing.update_by_id = actor
        existing.version_nbr = int(existing.version_nbr or 1) + 1
        existing.save(
            update_fields=[
                "demand_window_hours",
                "planning_window_hours",
                "freshness_threshold_hours",
                "stale_threshold_hours",
                "is_active",
                "update_by_id",
                "update_dtime",
                "version_nbr",
            ]
        )
        return "updated"

    def _apply_snapshot_comments(self) -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                COMMENT ON COLUMN event_phase.demand_window_hours IS
                'Snapshot copied from event_phase_config at phase activation. Do not update after activation.';
                """
            )
            cursor.execute(
                """
                COMMENT ON COLUMN event_phase.planning_window_hours IS
                'Snapshot copied from event_phase_config at phase activation. Do not update after activation.';
                """
            )
            cursor.execute(
                """
                COMMENT ON COLUMN event_phase.buffer_multiplier IS
                'Snapshot copied from event_phase_config-derived safety policy at phase activation.';
                """
            )

