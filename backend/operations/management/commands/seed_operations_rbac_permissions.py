from __future__ import annotations

import json
from typing import Any

from django.core.management.base import BaseCommand
from django.db import DatabaseError, connection, transaction

from api import rbac

OPERATIONS_ROLE_PERMISSION_MAP: dict[str, set[str]] = {
    "AGENCY_DISTRIBUTOR": {
        rbac.PERM_OPERATIONS_REQUEST_CREATE_SELF,
        rbac.PERM_OPERATIONS_REQUEST_CREATE_FOR_SUBORDINATE,
        rbac.PERM_OPERATIONS_REQUEST_EDIT_DRAFT,
        rbac.PERM_OPERATIONS_REQUEST_SUBMIT,
        rbac.PERM_OPERATIONS_REQUEST_CANCEL,
        rbac.PERM_OPERATIONS_WAYBILL_VIEW,
        rbac.PERM_OPERATIONS_RECEIPT_CONFIRM,
        rbac.PERM_OPERATIONS_NOTIFICATION_RECEIVE,
        rbac.PERM_OPERATIONS_QUEUE_VIEW,
    },
    "AGENCY_SHELTER": {
        rbac.PERM_OPERATIONS_REQUEST_CREATE_SELF,
        rbac.PERM_OPERATIONS_REQUEST_CREATE_FOR_SUBORDINATE,
        rbac.PERM_OPERATIONS_REQUEST_EDIT_DRAFT,
        rbac.PERM_OPERATIONS_REQUEST_SUBMIT,
        rbac.PERM_OPERATIONS_REQUEST_CANCEL,
        rbac.PERM_OPERATIONS_WAYBILL_VIEW,
        rbac.PERM_OPERATIONS_RECEIPT_CONFIRM,
        rbac.PERM_OPERATIONS_NOTIFICATION_RECEIVE,
        rbac.PERM_OPERATIONS_QUEUE_VIEW,
    },
    "CUSTODIAN": {
        rbac.PERM_OPERATIONS_REQUEST_CREATE_SELF,
        rbac.PERM_OPERATIONS_REQUEST_CREATE_FOR_SUBORDINATE,
        rbac.PERM_OPERATIONS_REQUEST_EDIT_DRAFT,
        rbac.PERM_OPERATIONS_REQUEST_SUBMIT,
        rbac.PERM_OPERATIONS_REQUEST_CANCEL,
        rbac.PERM_OPERATIONS_WAYBILL_VIEW,
        rbac.PERM_OPERATIONS_RECEIPT_CONFIRM,
        rbac.PERM_OPERATIONS_NOTIFICATION_RECEIVE,
        rbac.PERM_OPERATIONS_QUEUE_VIEW,
    },
    "LOGISTICS_OFFICER": {
        rbac.PERM_OPERATIONS_PACKAGE_CREATE,
        rbac.PERM_OPERATIONS_PACKAGE_LOCK,
        rbac.PERM_OPERATIONS_PACKAGE_ALLOCATE,
        rbac.PERM_OPERATIONS_PACKAGE_OVERRIDE_REQUEST,
        rbac.PERM_OPERATIONS_FULFILLMENT_MODE_SET,
        rbac.PERM_OPERATIONS_STAGING_WAREHOUSE_OVERRIDE,
        rbac.PERM_OPERATIONS_PARTIAL_RELEASE_REQUEST,
        rbac.PERM_OPERATIONS_DISPATCH_PREPARE,
        rbac.PERM_OPERATIONS_DISPATCH_EXECUTE,
        rbac.PERM_OPERATIONS_CONSOLIDATION_DISPATCH,
        rbac.PERM_OPERATIONS_CONSOLIDATION_RECEIVE,
        rbac.PERM_OPERATIONS_PICKUP_RELEASE,
        rbac.PERM_OPERATIONS_WAYBILL_VIEW,
        rbac.PERM_OPERATIONS_NOTIFICATION_RECEIVE,
        rbac.PERM_OPERATIONS_QUEUE_VIEW,
    },
    "TST_LOGISTICS_OFFICER": {
        rbac.PERM_OPERATIONS_PACKAGE_CREATE,
        rbac.PERM_OPERATIONS_PACKAGE_LOCK,
        rbac.PERM_OPERATIONS_PACKAGE_ALLOCATE,
        rbac.PERM_OPERATIONS_PACKAGE_OVERRIDE_REQUEST,
        rbac.PERM_OPERATIONS_FULFILLMENT_MODE_SET,
        rbac.PERM_OPERATIONS_STAGING_WAREHOUSE_OVERRIDE,
        rbac.PERM_OPERATIONS_PARTIAL_RELEASE_REQUEST,
        rbac.PERM_OPERATIONS_DISPATCH_PREPARE,
        rbac.PERM_OPERATIONS_DISPATCH_EXECUTE,
        rbac.PERM_OPERATIONS_CONSOLIDATION_DISPATCH,
        rbac.PERM_OPERATIONS_CONSOLIDATION_RECEIVE,
        rbac.PERM_OPERATIONS_PICKUP_RELEASE,
        rbac.PERM_OPERATIONS_WAYBILL_VIEW,
        rbac.PERM_OPERATIONS_NOTIFICATION_RECEIVE,
        rbac.PERM_OPERATIONS_QUEUE_VIEW,
    },
    "LOGISTICS_MANAGER": {
        rbac.PERM_OPERATIONS_PACKAGE_CREATE,
        rbac.PERM_OPERATIONS_PACKAGE_LOCK,
        rbac.PERM_OPERATIONS_PACKAGE_ALLOCATE,
        rbac.PERM_OPERATIONS_PACKAGE_OVERRIDE_REQUEST,
        rbac.PERM_OPERATIONS_PACKAGE_OVERRIDE_APPROVE,
        rbac.PERM_OPERATIONS_FULFILLMENT_MODE_SET,
        rbac.PERM_OPERATIONS_STAGING_WAREHOUSE_OVERRIDE,
        rbac.PERM_OPERATIONS_PARTIAL_RELEASE_REQUEST,
        rbac.PERM_OPERATIONS_PARTIAL_RELEASE_APPROVE,
        rbac.PERM_OPERATIONS_DISPATCH_PREPARE,
        rbac.PERM_OPERATIONS_DISPATCH_EXECUTE,
        rbac.PERM_OPERATIONS_CONSOLIDATION_DISPATCH,
        rbac.PERM_OPERATIONS_CONSOLIDATION_RECEIVE,
        rbac.PERM_OPERATIONS_PICKUP_RELEASE,
        rbac.PERM_OPERATIONS_WAYBILL_VIEW,
        rbac.PERM_OPERATIONS_NOTIFICATION_RECEIVE,
        rbac.PERM_OPERATIONS_QUEUE_VIEW,
    },
    "ODPEM_LOGISTICS_MANAGER": {
        rbac.PERM_OPERATIONS_PACKAGE_CREATE,
        rbac.PERM_OPERATIONS_PACKAGE_LOCK,
        rbac.PERM_OPERATIONS_PACKAGE_ALLOCATE,
        rbac.PERM_OPERATIONS_PACKAGE_OVERRIDE_REQUEST,
        rbac.PERM_OPERATIONS_PACKAGE_OVERRIDE_APPROVE,
        rbac.PERM_OPERATIONS_FULFILLMENT_MODE_SET,
        rbac.PERM_OPERATIONS_STAGING_WAREHOUSE_OVERRIDE,
        rbac.PERM_OPERATIONS_PARTIAL_RELEASE_REQUEST,
        rbac.PERM_OPERATIONS_PARTIAL_RELEASE_APPROVE,
        rbac.PERM_OPERATIONS_DISPATCH_PREPARE,
        rbac.PERM_OPERATIONS_DISPATCH_EXECUTE,
        rbac.PERM_OPERATIONS_CONSOLIDATION_DISPATCH,
        rbac.PERM_OPERATIONS_CONSOLIDATION_RECEIVE,
        rbac.PERM_OPERATIONS_PICKUP_RELEASE,
        rbac.PERM_OPERATIONS_WAYBILL_VIEW,
        rbac.PERM_OPERATIONS_NOTIFICATION_RECEIVE,
        rbac.PERM_OPERATIONS_QUEUE_VIEW,
    },
    "TST_LOGISTICS_MANAGER": {
        rbac.PERM_OPERATIONS_PACKAGE_CREATE,
        rbac.PERM_OPERATIONS_PACKAGE_LOCK,
        rbac.PERM_OPERATIONS_PACKAGE_ALLOCATE,
        rbac.PERM_OPERATIONS_PACKAGE_OVERRIDE_REQUEST,
        rbac.PERM_OPERATIONS_PACKAGE_OVERRIDE_APPROVE,
        rbac.PERM_OPERATIONS_FULFILLMENT_MODE_SET,
        rbac.PERM_OPERATIONS_STAGING_WAREHOUSE_OVERRIDE,
        rbac.PERM_OPERATIONS_PARTIAL_RELEASE_REQUEST,
        rbac.PERM_OPERATIONS_PARTIAL_RELEASE_APPROVE,
        rbac.PERM_OPERATIONS_DISPATCH_PREPARE,
        rbac.PERM_OPERATIONS_DISPATCH_EXECUTE,
        rbac.PERM_OPERATIONS_CONSOLIDATION_DISPATCH,
        rbac.PERM_OPERATIONS_CONSOLIDATION_RECEIVE,
        rbac.PERM_OPERATIONS_PICKUP_RELEASE,
        rbac.PERM_OPERATIONS_WAYBILL_VIEW,
        rbac.PERM_OPERATIONS_NOTIFICATION_RECEIVE,
        rbac.PERM_OPERATIONS_QUEUE_VIEW,
    },
    "INVENTORY_CLERK": {
        rbac.PERM_OPERATIONS_DISPATCH_PREPARE,
        rbac.PERM_OPERATIONS_DISPATCH_EXECUTE,
        rbac.PERM_OPERATIONS_CONSOLIDATION_DISPATCH,
        rbac.PERM_OPERATIONS_WAYBILL_VIEW,
        rbac.PERM_OPERATIONS_NOTIFICATION_RECEIVE,
        rbac.PERM_OPERATIONS_QUEUE_VIEW,
    },
    "ODPEM_DDG": {
        rbac.PERM_OPERATIONS_ELIGIBILITY_REVIEW,
        rbac.PERM_OPERATIONS_ELIGIBILITY_APPROVE,
        rbac.PERM_OPERATIONS_ELIGIBILITY_REJECT,
        rbac.PERM_OPERATIONS_NOTIFICATION_RECEIVE,
        rbac.PERM_OPERATIONS_QUEUE_VIEW,
    },
    "ODPEM_DIR_PEOD": {
        rbac.PERM_OPERATIONS_ELIGIBILITY_REVIEW,
        rbac.PERM_OPERATIONS_ELIGIBILITY_APPROVE,
        rbac.PERM_OPERATIONS_ELIGIBILITY_REJECT,
        rbac.PERM_OPERATIONS_NOTIFICATION_RECEIVE,
        rbac.PERM_OPERATIONS_QUEUE_VIEW,
    },
    "ODPEM_DG": {
        rbac.PERM_OPERATIONS_ELIGIBILITY_REVIEW,
        rbac.PERM_OPERATIONS_ELIGIBILITY_APPROVE,
        rbac.PERM_OPERATIONS_ELIGIBILITY_REJECT,
        rbac.PERM_OPERATIONS_NOTIFICATION_RECEIVE,
        rbac.PERM_OPERATIONS_QUEUE_VIEW,
    },
    "TST_DG": {
        rbac.PERM_OPERATIONS_ELIGIBILITY_REVIEW,
        rbac.PERM_OPERATIONS_ELIGIBILITY_APPROVE,
        rbac.PERM_OPERATIONS_ELIGIBILITY_REJECT,
        rbac.PERM_OPERATIONS_NOTIFICATION_RECEIVE,
        rbac.PERM_OPERATIONS_QUEUE_VIEW,
    },
    "TST_DIR_PEOD": {
        rbac.PERM_OPERATIONS_ELIGIBILITY_REVIEW,
        rbac.PERM_OPERATIONS_ELIGIBILITY_APPROVE,
        rbac.PERM_OPERATIONS_ELIGIBILITY_REJECT,
        rbac.PERM_OPERATIONS_NOTIFICATION_RECEIVE,
        rbac.PERM_OPERATIONS_QUEUE_VIEW,
    },
    "SYSTEM_ADMINISTRATOR": {
        rbac.PERM_OPERATIONS_REQUEST_CREATE_SELF,
        rbac.PERM_OPERATIONS_REQUEST_CREATE_FOR_SUBORDINATE,
        rbac.PERM_OPERATIONS_REQUEST_CREATE_ON_BEHALF_BRIDGE,
        rbac.PERM_OPERATIONS_REQUEST_EDIT_DRAFT,
        rbac.PERM_OPERATIONS_REQUEST_SUBMIT,
        rbac.PERM_OPERATIONS_REQUEST_CANCEL,
        rbac.PERM_OPERATIONS_ELIGIBILITY_REVIEW,
        rbac.PERM_OPERATIONS_ELIGIBILITY_APPROVE,
        rbac.PERM_OPERATIONS_ELIGIBILITY_REJECT,
        rbac.PERM_OPERATIONS_PACKAGE_CREATE,
        rbac.PERM_OPERATIONS_PACKAGE_LOCK,
        rbac.PERM_OPERATIONS_PACKAGE_ALLOCATE,
        rbac.PERM_OPERATIONS_PACKAGE_OVERRIDE_REQUEST,
        rbac.PERM_OPERATIONS_PACKAGE_OVERRIDE_APPROVE,
        rbac.PERM_OPERATIONS_FULFILLMENT_MODE_SET,
        rbac.PERM_OPERATIONS_STAGING_WAREHOUSE_OVERRIDE,
        rbac.PERM_OPERATIONS_PARTIAL_RELEASE_REQUEST,
        rbac.PERM_OPERATIONS_PARTIAL_RELEASE_APPROVE,
        rbac.PERM_OPERATIONS_DISPATCH_PREPARE,
        rbac.PERM_OPERATIONS_DISPATCH_EXECUTE,
        rbac.PERM_OPERATIONS_CONSOLIDATION_DISPATCH,
        rbac.PERM_OPERATIONS_CONSOLIDATION_RECEIVE,
        rbac.PERM_OPERATIONS_PICKUP_RELEASE,
        rbac.PERM_OPERATIONS_RECEIPT_CONFIRM,
        rbac.PERM_OPERATIONS_WAYBILL_VIEW,
        rbac.PERM_OPERATIONS_NOTIFICATION_RECEIVE,
        rbac.PERM_OPERATIONS_QUEUE_VIEW,
    },
}

ALL_OPERATIONS_PERMISSIONS = sorted(
    {
        permission
        for permissions in OPERATIONS_ROLE_PERMISSION_MAP.values()
        for permission in permissions
    }
)


class Command(BaseCommand):
    help = (
        "Seed canonical operations.* permission rows and role_permission mappings into "
        "DMIS DB RBAC. Dry-run by default."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--actor", type=str, default="SYSTEM", help="Actor user ID for audit columns.")
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Persist changes. Without this flag, the command only previews the plan.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        actor_id = str(options.get("actor") or "SYSTEM").strip() or "SYSTEM"
        apply_changes = bool(options.get("apply"))

        existing_permission_ids = self._fetch_permission_ids()
        role_ids = self._fetch_role_ids()
        existing_role_permission_keys = self._fetch_role_permission_keys()

        missing_permissions = [permission for permission in ALL_OPERATIONS_PERMISSIONS if permission not in existing_permission_ids]
        missing_roles = [role_code for role_code in sorted(OPERATIONS_ROLE_PERMISSION_MAP) if role_code not in role_ids]

        planned_role_permission_links = []
        for role_code, permissions in OPERATIONS_ROLE_PERMISSION_MAP.items():
            if role_code not in role_ids:
                continue
            for permission in sorted(permissions):
                if f"{role_code}:{permission}" not in existing_role_permission_keys:
                    planned_role_permission_links.append((role_code, permission))

        self.stdout.write("Operations RBAC seed:")
        self.stdout.write(f"- missing permission rows: {len(missing_permissions)}")
        self.stdout.write(f"- missing role_permission links: {len(planned_role_permission_links)}")
        self.stdout.write(f"- missing roles in DB: {len(missing_roles)}")
        if missing_roles:
            self.stdout.write("  - " + ", ".join(missing_roles))

        if not apply_changes:
            self.stdout.write(self.style.WARNING("Dry-run only. Re-run with --apply to persist changes."))
            return

        created_permission_count = 0
        created_link_count = 0

        with transaction.atomic():
            next_perm_id = self._next_perm_id()
            permission_rows = []
            for permission in missing_permissions:
                resource, action = permission.rsplit(".", 1)
                permission_rows.append((next_perm_id, resource, action, actor_id, actor_id))
                next_perm_id += 1

            if permission_rows:
                self._insert_permissions(permission_rows)
                created_permission_count = len(permission_rows)

            permission_ids = self._fetch_permission_ids()
            link_rows = []
            for role_code, permission in planned_role_permission_links:
                role_id = role_ids.get(role_code)
                perm_id = permission_ids.get(permission)
                if role_id is None or perm_id is None:
                    continue
                link_rows.append((role_id, perm_id, json.dumps({"source": "operations_rbac_seed"}), actor_id, actor_id))

            if link_rows:
                self._insert_role_permissions(link_rows)
                created_link_count = len(link_rows)

        self.stdout.write(self.style.SUCCESS("Operations RBAC seed applied."))
        self.stdout.write(
            json.dumps(
                {
                    "created_permissions": created_permission_count,
                    "created_role_permission_links": created_link_count,
                    "missing_roles": missing_roles,
                },
                indent=2,
                sort_keys=True,
            )
        )

    def _fetch_permission_ids(self) -> dict[str, int]:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT resource, action, perm_id
                FROM permission
                WHERE resource LIKE 'operations.%'
                """
            )
            return {f"{row[0]}.{row[1]}": int(row[2]) for row in cursor.fetchall()}

    def _fetch_role_ids(self) -> dict[str, int]:
        with connection.cursor() as cursor:
            cursor.execute("SELECT code, id FROM role")
            return {str(row[0]).strip().upper(): int(row[1]) for row in cursor.fetchall() if str(row[0]).strip()}

    def _fetch_role_permission_keys(self) -> set[str]:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT r.code, p.resource, p.action
                FROM role_permission rp
                JOIN role r ON r.id = rp.role_id
                JOIN permission p ON p.perm_id = rp.perm_id
                WHERE p.resource LIKE 'operations.%'
                """
            )
            return {
                f"{str(row[0]).strip().upper()}:{row[1]}.{row[2]}"
                for row in cursor.fetchall()
                if str(row[0]).strip()
            }

    def _next_perm_id(self) -> int:
        with connection.cursor() as cursor:
            cursor.execute("LOCK TABLE permission IN EXCLUSIVE MODE")
            cursor.execute("SELECT COALESCE(MAX(perm_id), 0) + 1 FROM permission")
            row = cursor.fetchone()
        return int(row[0] or 1)

    def _insert_permissions(self, rows: list[tuple[int, str, str, str, str]]) -> None:
        try:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO permission (
                        perm_id,
                        resource,
                        action,
                        create_by_id,
                        update_by_id
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    rows,
                )
        except DatabaseError as exc:
            raise RuntimeError("Unable to insert canonical Operations permission rows.") from exc

    def _insert_role_permissions(self, rows: list[tuple[int, int, str, str, str]]) -> None:
        try:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO role_permission (
                        role_id,
                        perm_id,
                        scope_json,
                        create_by_id,
                        update_by_id
                    )
                    VALUES (%s, %s, %s::jsonb, %s, %s)
                    ON CONFLICT (role_id, perm_id) DO NOTHING
                    """,
                    rows,
                )
        except DatabaseError as exc:
            raise RuntimeError("Unable to insert Operations role_permission rows.") from exc
