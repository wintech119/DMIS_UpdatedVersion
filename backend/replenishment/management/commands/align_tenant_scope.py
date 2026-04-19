from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone

from api.tenant_membership_locks import lock_primary_tenant_membership


@dataclass
class MembershipRow:
    tenant_id: int
    user_id: int
    is_primary_tenant: bool
    access_level: str | None
    status_code: str


class Command(BaseCommand):
    help = (
        "Align tenant scope for strict enforcement by copying active user memberships "
        "from one tenant to another, optionally reassigning owned warehouses, and "
        "optionally backfilling tenant_warehouse mappings."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--from-tenant-id", type=int, required=True)
        parser.add_argument("--to-tenant-id", type=int, required=True)
        parser.add_argument("--actor", type=str, default="SYSTEM")
        parser.add_argument(
            "--skip-membership-copy",
            action="store_true",
            help="Do not copy tenant_user memberships from the source tenant.",
        )
        parser.add_argument(
            "--set-primary",
            action="store_true",
            help="Set the target tenant as primary membership for affected users.",
        )
        parser.add_argument(
            "--backfill-tenant-warehouse",
            action="store_true",
            help="Insert tenant_warehouse mappings from warehouse.tenant_id when missing.",
        )
        parser.add_argument(
            "--reassign-owned-warehouses",
            action="store_true",
            help="Move owned warehouses from the source tenant to the target tenant.",
        )
        parser.add_argument(
            "--warehouse-ids",
            type=str,
            default=None,
            help="Optional comma-separated warehouse IDs to scope --reassign-owned-warehouses.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Apply changes. Without this flag, command runs in dry-run mode.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        from_tenant_id = int(options["from_tenant_id"])
        to_tenant_id = int(options["to_tenant_id"])
        actor = str(options["actor"] or "SYSTEM").strip() or "SYSTEM"
        skip_membership_copy = bool(options["skip_membership_copy"])
        set_primary = bool(options["set_primary"])
        backfill_tenant_warehouse = bool(options["backfill_tenant_warehouse"])
        reassign_owned_warehouses = bool(options["reassign_owned_warehouses"])
        requested_warehouse_ids = self._parse_positive_int_list(options.get("warehouse_ids"))
        apply_changes = bool(options["apply"])

        if from_tenant_id <= 0 or to_tenant_id <= 0:
            raise CommandError("Tenant IDs must be positive integers.")
        if from_tenant_id == to_tenant_id:
            raise CommandError("--from-tenant-id and --to-tenant-id must differ.")
        if skip_membership_copy and set_primary:
            raise CommandError("--set-primary cannot be used with --skip-membership-copy.")
        if requested_warehouse_ids and not reassign_owned_warehouses:
            raise CommandError("--warehouse-ids requires --reassign-owned-warehouses.")

        self._validate_tenant_exists(from_tenant_id)
        self._validate_tenant_exists(to_tenant_id)

        source_rows = self._active_memberships(from_tenant_id) if not skip_membership_copy else []
        source_membership_count = len(source_rows) if not skip_membership_copy else 0
        existing_target_user_ids = self._active_target_user_ids(to_tenant_id) if source_rows else set()
        candidate_rows = [row for row in source_rows if row.user_id not in existing_target_user_ids] if source_rows else []
        skipped_existing = source_membership_count - len(candidate_rows)

        owned_warehouse_ids: list[int] = []
        if reassign_owned_warehouses:
            owned_warehouse_ids = self._owned_warehouse_ids(
                from_tenant_id,
                warehouse_ids=requested_warehouse_ids or None,
            )

        backfill_rows = []
        if backfill_tenant_warehouse:
            scoped_tenant_ids = sorted({from_tenant_id, to_tenant_id})
            backfill_rows = self._missing_tenant_warehouse_rows(
                scoped_tenant_ids,
                warehouse_ids=owned_warehouse_ids or None,
            )

        if not source_rows and not owned_warehouse_ids and not backfill_rows:
            self.stdout.write(self.style.WARNING("No active source memberships found."))
            return

        self.stdout.write("Tenant scope alignment plan:")
        self.stdout.write(f"- from tenant: {from_tenant_id}")
        self.stdout.write(f"- to tenant: {to_tenant_id}")
        self.stdout.write(f"- copy source memberships: {not skip_membership_copy}")
        self.stdout.write(f"- source active memberships: {source_membership_count}")
        self.stdout.write(f"- new memberships to create: {len(candidate_rows)}")
        self.stdout.write(f"- memberships skipped (already mapped): {skipped_existing}")
        self.stdout.write(f"- set primary on target tenant: {set_primary}")
        self.stdout.write(f"- owned warehouses to reassign: {len(owned_warehouse_ids) if reassign_owned_warehouses else 0}")
        if owned_warehouse_ids:
            warehouse_scope = ", ".join(str(warehouse_id) for warehouse_id in owned_warehouse_ids)
            self.stdout.write(f"- warehouse scope: {warehouse_scope}")
        self.stdout.write(
            f"- tenant_warehouse rows to backfill: {len(backfill_rows) if backfill_tenant_warehouse else 0}"
        )

        if not apply_changes:
            self.stdout.write(
                self.style.WARNING("Dry-run only. Re-run with --apply to persist changes.")
            )
            return

        now = timezone.now()
        actor_ref = actor[:20]
        assigned_by = self._safe_int(actor)

        with transaction.atomic():
            if candidate_rows:
                self._insert_target_memberships(
                    candidate_rows,
                    to_tenant_id=to_tenant_id,
                    actor_ref=actor_ref,
                    assigned_by=assigned_by,
                    set_primary=set_primary,
                    now=now,
                )
            if set_primary:
                all_affected_user_ids = sorted({row.user_id for row in source_rows})
                if all_affected_user_ids:
                    self._set_primary_tenant_for_users(
                        user_ids=all_affected_user_ids,
                        target_tenant_id=to_tenant_id,
                    )
            if owned_warehouse_ids:
                self._reassign_owned_warehouses(
                    from_tenant_id=from_tenant_id,
                    to_tenant_id=to_tenant_id,
                    warehouse_ids=owned_warehouse_ids,
                    actor_ref=actor_ref,
                    now=now,
                )
            if backfill_tenant_warehouse:
                scoped_tenant_ids = sorted({from_tenant_id, to_tenant_id})
                backfill_rows = self._missing_tenant_warehouse_rows(
                    scoped_tenant_ids,
                    warehouse_ids=owned_warehouse_ids or None,
                )
                if backfill_rows:
                    self._insert_tenant_warehouse_rows(
                        backfill_rows,
                        actor_ref=actor_ref,
                        now=now,
                        tenant_ids=scoped_tenant_ids,
                    )

        self.stdout.write(self.style.SUCCESS("Tenant scope alignment applied successfully."))

    def _validate_tenant_exists(self, tenant_id: int) -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT tenant_id
                FROM tenant
                WHERE tenant_id = %s AND COALESCE(status_code, 'A') = 'A'
                LIMIT 1
                """,
                [tenant_id],
            )
            row = cursor.fetchone()
        if not row:
            raise CommandError(f"Tenant {tenant_id} does not exist or is inactive.")

    def _active_memberships(self, tenant_id: int) -> list[MembershipRow]:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT tenant_id, user_id, COALESCE(is_primary_tenant, FALSE), access_level, COALESCE(status_code, 'A')
                FROM tenant_user
                WHERE tenant_id = %s AND COALESCE(status_code, 'A') = 'A'
                ORDER BY user_id
                """,
                [tenant_id],
            )
            rows = cursor.fetchall()
        return [
            MembershipRow(
                tenant_id=int(row[0]),
                user_id=int(row[1]),
                is_primary_tenant=bool(row[2]),
                access_level=str(row[3] or "").strip() or None,
                status_code=str(row[4] or "A"),
            )
            for row in rows
        ]

    def _active_target_user_ids(self, tenant_id: int) -> set[int]:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT DISTINCT user_id
                FROM tenant_user
                WHERE tenant_id = %s AND COALESCE(status_code, 'A') = 'A'
                """,
                [tenant_id],
            )
            rows = cursor.fetchall()
        return {int(row[0]) for row in rows}

    def _insert_target_memberships(
        self,
        rows: list[MembershipRow],
        *,
        to_tenant_id: int,
        actor_ref: str,
        assigned_by: int | None,
        set_primary: bool,
        now: datetime,
    ) -> None:
        insert_rows = []
        for row in rows:
            insert_rows.append(
                [
                    to_tenant_id,
                    row.user_id,
                    bool(set_primary and row.is_primary_tenant),
                    row.access_level or "FULL",
                    now,
                    assigned_by,
                    "A",
                    actor_ref,
                    now,
                ]
            )
        with connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO tenant_user (
                    tenant_id,
                    user_id,
                    is_primary_tenant,
                    access_level,
                    assigned_at,
                    assigned_by,
                    status_code,
                    create_by_id,
                    create_dtime
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                insert_rows,
            )

    def _set_primary_tenant_for_users(self, *, user_ids: list[int], target_tenant_id: int) -> None:
        if not user_ids:
            return
        with connection.cursor() as cursor:
            for user_id in user_ids:
                lock_primary_tenant_membership(cursor, user_id=user_id)
                cursor.execute(
                    """
                    UPDATE tenant_user
                    SET is_primary_tenant = FALSE
                    WHERE user_id = %s AND COALESCE(status_code, 'A') = 'A'
                    """,
                    [user_id],
                )
                cursor.execute(
                    """
                    UPDATE tenant_user
                    SET is_primary_tenant = TRUE
                    WHERE user_id = %s
                      AND tenant_id = %s
                      AND COALESCE(status_code, 'A') = 'A'
                    """,
                    [user_id, target_tenant_id],
                )

    def _owned_warehouse_ids(
        self,
        tenant_id: int,
        *,
        warehouse_ids: list[int] | None = None,
    ) -> list[int]:
        params: list[Any] = [tenant_id]
        filters = ["w.tenant_id = %s"]
        if warehouse_ids:
            placeholders = ", ".join(["%s"] * len(warehouse_ids))
            filters.append(f"w.warehouse_id IN ({placeholders})")
            params.extend(warehouse_ids)
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT w.warehouse_id
                FROM warehouse w
                WHERE {" AND ".join(filters)}
                ORDER BY w.warehouse_id
                """,
                params,
            )
            rows = cursor.fetchall()
        resolved_ids = [int(row[0]) for row in rows]
        if warehouse_ids:
            missing_ids = sorted(set(warehouse_ids) - set(resolved_ids))
            if missing_ids:
                missing_text = ", ".join(str(warehouse_id) for warehouse_id in missing_ids)
                raise CommandError(
                    f"Warehouses {missing_text} are not currently owned by tenant {tenant_id}."
                )
        return resolved_ids

    def _reassign_owned_warehouses(
        self,
        *,
        from_tenant_id: int,
        to_tenant_id: int,
        warehouse_ids: list[int],
        actor_ref: str,
        now: datetime,
    ) -> None:
        if not warehouse_ids:
            return
        self._delete_tenant_warehouse_rows(
            tenant_id=from_tenant_id,
            warehouse_ids=warehouse_ids,
        )
        self._update_warehouse_tenants(
            from_tenant_id=from_tenant_id,
            to_tenant_id=to_tenant_id,
            warehouse_ids=warehouse_ids,
            actor_ref=actor_ref,
            now=now,
        )
        self._upsert_tenant_warehouse_rows(
            tenant_id=to_tenant_id,
            warehouse_ids=warehouse_ids,
            actor_ref=actor_ref,
            now=now,
        )

    def _delete_tenant_warehouse_rows(self, *, tenant_id: int, warehouse_ids: list[int]) -> None:
        if not warehouse_ids:
            return
        placeholders = ", ".join(["%s"] * len(warehouse_ids))
        params = [tenant_id, *warehouse_ids]
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                DELETE FROM tenant_warehouse
                WHERE tenant_id = %s
                  AND warehouse_id IN ({placeholders})
                """,
                params,
            )

    def _update_warehouse_tenants(
        self,
        *,
        from_tenant_id: int,
        to_tenant_id: int,
        warehouse_ids: list[int],
        actor_ref: str,
        now: datetime,
    ) -> None:
        if not warehouse_ids:
            return
        placeholders = ", ".join(["%s"] * len(warehouse_ids))
        params = [to_tenant_id, actor_ref, now, from_tenant_id, *warehouse_ids]
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE warehouse
                SET tenant_id = %s,
                    update_by_id = %s,
                    update_dtime = %s,
                    version_nbr = COALESCE(version_nbr, 0) + 1
                WHERE tenant_id = %s
                  AND warehouse_id IN ({placeholders})
                """,
                params,
            )

    def _upsert_tenant_warehouse_rows(
        self,
        *,
        tenant_id: int,
        warehouse_ids: list[int],
        actor_ref: str,
        now: datetime,
    ) -> None:
        if not warehouse_ids:
            return
        effective_date = timezone.localdate()
        upsert_rows = [
            [tenant_id, warehouse_id, "OWNED", "FULL", effective_date, None, actor_ref, now]
            for warehouse_id in warehouse_ids
        ]
        with connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO tenant_warehouse (
                    tenant_id,
                    warehouse_id,
                    ownership_type,
                    access_level,
                    effective_date,
                    expiry_date,
                    create_by_id,
                    create_dtime
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, warehouse_id) DO UPDATE
                SET ownership_type = EXCLUDED.ownership_type,
                    access_level = EXCLUDED.access_level,
                    effective_date = EXCLUDED.effective_date,
                    expiry_date = EXCLUDED.expiry_date,
                    create_by_id = EXCLUDED.create_by_id,
                    create_dtime = EXCLUDED.create_dtime
                """,
                upsert_rows,
            )

    def _missing_tenant_warehouse_rows(
        self,
        tenant_ids: list[int],
        *,
        warehouse_ids: list[int] | None = None,
    ) -> list[tuple[int, int]]:
        if not tenant_ids:
            return []
        placeholders = ", ".join(["%s"] * len(tenant_ids))
        params: list[Any] = [*tenant_ids]
        warehouse_filter = ""
        if warehouse_ids:
            warehouse_placeholders = ", ".join(["%s"] * len(warehouse_ids))
            warehouse_filter = f" AND w.warehouse_id IN ({warehouse_placeholders})"
            params.extend(warehouse_ids)
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT w.tenant_id, w.warehouse_id
                FROM warehouse w
                LEFT JOIN tenant_warehouse tw
                    ON tw.tenant_id = w.tenant_id
                    AND tw.warehouse_id = w.warehouse_id
                    AND tw.effective_date <= CURRENT_DATE
                    AND (tw.expiry_date IS NULL OR tw.expiry_date >= CURRENT_DATE)
                WHERE w.tenant_id IS NOT NULL
                  AND w.tenant_id IN ({placeholders})
                  {warehouse_filter}
                  AND tw.warehouse_id IS NULL
                ORDER BY w.warehouse_id
                """,
                params,
            )
            rows = cursor.fetchall()
        return [(int(row[0]), int(row[1])) for row in rows]

    def _insert_tenant_warehouse_rows(
        self,
        rows: list[tuple[int, int]],
        *,
        actor_ref: str,
        now: datetime,
        tenant_ids: list[int],
    ) -> None:
        allowed_tenant_ids = set(tenant_ids)
        filtered_rows = [(tenant_id, warehouse_id) for tenant_id, warehouse_id in rows if tenant_id in allowed_tenant_ids]
        if not filtered_rows:
            return
        insert_rows = [
            [tenant_id, warehouse_id, "OWNED", "FULL", timezone.localdate(), None, actor_ref, now]
            for tenant_id, warehouse_id in filtered_rows
        ]
        with connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO tenant_warehouse (
                    tenant_id,
                    warehouse_id,
                    ownership_type,
                    access_level,
                    effective_date,
                    expiry_date,
                    create_by_id,
                    create_dtime
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                insert_rows,
            )

    def _safe_int(self, value: str) -> int | None:
        try:
            parsed = int(str(value).strip())
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    def _parse_positive_int_list(self, value: object) -> list[int]:
        text = str(value or "").strip()
        if not text:
            return []
        parsed_ids: list[int] = []
        for token in text.split(","):
            parsed = self._safe_int(token)
            if parsed is None:
                raise CommandError("--warehouse-ids must be a comma-separated list of positive integers.")
            parsed_ids.append(parsed)
        return sorted(set(parsed_ids))
