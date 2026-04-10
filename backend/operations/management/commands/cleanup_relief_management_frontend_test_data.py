from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connection, transaction
from django.utils import timezone


class Command(BaseCommand):
    help = (
        "Deactivate temporary Relief Management frontend test users and inactivate the associated "
        "temporary warehouse and agency. Dry-run by default."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--tenant-code", type=str, default="JRC", help="Tenant code used when seeding the temporary data.")
        parser.add_argument("--actor", type=str, default="SYSTEM", help="Actor user ID for audit columns.")
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Persist changes. Without this flag, the command only previews the plan.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        actor_id = str(options.get("actor") or "SYSTEM").strip() or "SYSTEM"
        apply_changes = bool(options.get("apply"))
        tenant_code = str(options.get("tenant_code") or "JRC").strip().upper()
        normalized = tenant_code.lower().replace("-", "_").replace(" ", "_")

        usernames = [
            f"relief_{normalized}_requester_tst",
        ]
        warehouse_name = f"S07 TEST MAIN HUB - {tenant_code}"
        agency_name = f"S07 TEST DISTRIBUTOR AGENCY - {tenant_code}"

        user_rows = self._fetch_users(usernames)
        warehouse = self._fetch_warehouse(warehouse_name)
        agency = self._fetch_agency(agency_name)

        self.stdout.write("Relief Management frontend test-data cleanup:")
        self.stdout.write(f"- tenant code: {tenant_code}")
        self.stdout.write(f"- users matched: {len(user_rows)}")
        self.stdout.write(f"- warehouse matched: {'yes' if warehouse else 'no'}")
        self.stdout.write(f"- agency matched: {'yes' if agency else 'no'}")

        if not apply_changes:
            self.stdout.write(self.style.WARNING("Dry-run only. Re-run with --apply to persist changes."))
            return

        now = timezone.now()
        with transaction.atomic():
            if user_rows:
                user_ids = [row["user_id"] for row in user_rows]
                self._deactivate_tenant_memberships(user_ids=user_ids, actor_id=actor_id, now=now)
                self._delete_user_roles(user_ids=user_ids)
                self._deactivate_users(user_ids=user_ids, now=now)
            if agency is not None:
                self._inactivate_agency(agency_id=agency["agency_id"])
            if warehouse is not None:
                self._inactivate_warehouse(warehouse_id=warehouse["warehouse_id"], actor_id=actor_id, now=now)

        self.stdout.write(self.style.SUCCESS("Temporary Relief Management frontend test data has been deactivated."))

    def _fetch_users(self, usernames: list[str]) -> list[dict[str, Any]]:
        if not usernames:
            return []
        placeholders = ", ".join(["%s"] * len(usernames))
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT user_id, username
                    FROM "user"
                    WHERE username IN ({placeholders})
                    ORDER BY user_id
                    """,
                    usernames,
                )
                rows = cursor.fetchall()
        except DatabaseError as exc:
            raise CommandError("Unable to inspect frontend test users.") from exc
        return [{"user_id": int(row[0]), "username": str(row[1] or "").strip()} for row in rows]

    def _fetch_warehouse(self, warehouse_name: str) -> dict[str, Any] | None:
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT warehouse_id, warehouse_name
                    FROM warehouse
                    WHERE UPPER(COALESCE(warehouse_name, '')) = %s
                    LIMIT 1
                    """,
                    [warehouse_name.upper()],
                )
                row = cursor.fetchone()
        except DatabaseError as exc:
            raise CommandError("Unable to inspect frontend test warehouse.") from exc
        if not row:
            return None
        return {"warehouse_id": int(row[0]), "warehouse_name": str(row[1] or "").strip()}

    def _fetch_agency(self, agency_name: str) -> dict[str, Any] | None:
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT agency_id, agency_name
                    FROM agency
                    WHERE UPPER(COALESCE(agency_name, '')) = %s
                    LIMIT 1
                    """,
                    [agency_name.upper()],
                )
                row = cursor.fetchone()
        except DatabaseError as exc:
            raise CommandError("Unable to inspect frontend test agency.") from exc
        if not row:
            return None
        return {"agency_id": int(row[0]), "agency_name": str(row[1] or "").strip()}

    def _deactivate_tenant_memberships(self, *, user_ids: list[int], actor_id: str, now) -> None:
        placeholders = ", ".join(["%s"] * len(user_ids))
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE tenant_user
                SET
                    status_code = 'I',
                    is_primary_tenant = FALSE,
                    create_by_id = %s,
                    create_dtime = %s
                WHERE user_id IN ({placeholders}) AND COALESCE(status_code, 'A') = 'A'
                """,
                [actor_id, now, *user_ids],
            )

    def _delete_user_roles(self, *, user_ids: list[int]) -> None:
        placeholders = ", ".join(["%s"] * len(user_ids))
        with connection.cursor() as cursor:
            cursor.execute(
                f"DELETE FROM user_role WHERE user_id IN ({placeholders})",
                user_ids,
            )

    def _deactivate_users(self, *, user_ids: list[int], now) -> None:
        placeholders = ", ".join(["%s"] * len(user_ids))
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE "user"
                SET
                    is_active = FALSE,
                    status_code = 'I',
                    update_dtime = %s,
                    version_nbr = version_nbr + 1
                WHERE user_id IN ({placeholders})
                """,
                [now, *user_ids],
            )

    def _inactivate_agency(self, *, agency_id: int) -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE agency
                SET status_code = 'I'
                WHERE agency_id = %s
                """,
                [agency_id],
            )

    def _inactivate_warehouse(self, *, warehouse_id: int, actor_id: str, now) -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE warehouse
                SET
                    status_code = 'I',
                    reason_desc = 'TEMP RELIEF TEST DATA CLEANUP',
                    update_by_id = %s,
                    update_dtime = %s,
                    version_nbr = version_nbr + 1
                WHERE warehouse_id = %s
                """,
                [actor_id, now, warehouse_id],
            )
