from __future__ import annotations

from datetime import date
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connection
from django.db.migrations.recorder import MigrationRecorder
from django.db.models import Q
from django.utils import timezone

from api import rbac
from operations.constants import (
    DISPATCH_ROLE_CODES,
    ELIGIBILITY_ROLE_CODES,
    FULFILLMENT_ROLE_CODES,
    normalize_role_codes,
)
from operations.models import TenantControlScope, TenantHierarchy, TenantRequestPolicy

OPERATIONS_MIGRATION = ("operations", "0001_relief_management_backend_first")
REQUIRED_OPERATIONS_TABLES = {
    "tenant_hierarchy",
    "tenant_request_policy",
    "tenant_control_scope",
    "operations_relief_request",
    "operations_eligibility_decision",
    "operations_package",
    "operations_package_lock",
    "operations_dispatch",
    "operations_dispatch_transport",
    "operations_waybill",
    "operations_receipt",
    "operations_notification",
    "operations_queue_assignment",
    "operations_status_history",
}
REQUIRED_OPERATIONS_PERMISSIONS = {
    rbac.PERM_OPERATIONS_REQUEST_CREATE_SELF,
    rbac.PERM_OPERATIONS_REQUEST_CREATE_FOR_SUBORDINATE,
    rbac.PERM_OPERATIONS_REQUEST_CREATE_ON_BEHALF_BRIDGE,
    rbac.PERM_OPERATIONS_REQUEST_EDIT_DRAFT,
    rbac.PERM_OPERATIONS_REQUEST_SUBMIT,
    rbac.PERM_OPERATIONS_ELIGIBILITY_REVIEW,
    rbac.PERM_OPERATIONS_ELIGIBILITY_APPROVE,
    rbac.PERM_OPERATIONS_ELIGIBILITY_REJECT,
    rbac.PERM_OPERATIONS_PACKAGE_CREATE,
    rbac.PERM_OPERATIONS_PACKAGE_LOCK,
    rbac.PERM_OPERATIONS_PACKAGE_ALLOCATE,
    rbac.PERM_OPERATIONS_PACKAGE_OVERRIDE_REQUEST,
    rbac.PERM_OPERATIONS_PACKAGE_OVERRIDE_APPROVE,
    rbac.PERM_OPERATIONS_DISPATCH_PREPARE,
    rbac.PERM_OPERATIONS_DISPATCH_EXECUTE,
    rbac.PERM_OPERATIONS_RECEIPT_CONFIRM,
    rbac.PERM_OPERATIONS_WAYBILL_VIEW,
    rbac.PERM_OPERATIONS_NOTIFICATION_RECEIVE,
    rbac.PERM_OPERATIONS_QUEUE_VIEW,
}


class Command(BaseCommand):
    help = (
        "Check whether the Relief Management backend is ready for live frontend integration. "
        "Reports blockers for migration state, authority seed data, and required role coverage."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--tenant-id",
            action="append",
            type=int,
            dest="tenant_ids",
            default=[],
            help="Optional tenant IDs that must already have an active tenant_request_policy row.",
        )
        parser.add_argument(
            "--strict-permissions",
            action="store_true",
            help="Treat missing canonical Operations permission rows in DB RBAC as a blocker.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        tenant_ids = sorted({int(value) for value in options.get("tenant_ids") or [] if int(value) > 0})
        strict_permissions = bool(options.get("strict_permissions"))

        blockers: list[str] = []
        warnings: list[str] = []
        summaries: list[str] = []

        migration_applied = self._migration_applied(*OPERATIONS_MIGRATION)
        summaries.append(f"operations migration applied: {migration_applied}")
        if not migration_applied:
            blockers.append(
                "Apply Django migration operations.0001_relief_management_backend_first before frontend uses live APIs."
            )

        existing_tables = self._existing_tables()
        missing_tables = sorted(REQUIRED_OPERATIONS_TABLES - existing_tables)
        summaries.append(
            f"operations tables present: {len(REQUIRED_OPERATIONS_TABLES) - len(missing_tables)}/{len(REQUIRED_OPERATIONS_TABLES)}"
        )
        if migration_applied and missing_tables:
            blockers.append(
                "Operations migration is recorded but required tables are missing: "
                + ", ".join(missing_tables)
            )

        if "tenant_request_policy" in existing_tables:
            active_policies = self._active_rows(TenantRequestPolicy, timezone.localdate())
            policy_count = active_policies.count()
            summaries.append(f"active tenant request policies: {policy_count}")
            if policy_count == 0:
                blockers.append(
                    "No active tenant_request_policy rows exist. Seed explicit request-authority data before frontend integration."
                )
            if tenant_ids:
                seeded_ids = set(active_policies.filter(tenant_id__in=tenant_ids).values_list("tenant_id", flat=True))
                missing_seed = [str(tenant_id) for tenant_id in tenant_ids if tenant_id not in seeded_ids]
                if missing_seed:
                    blockers.append(
                        "Missing active tenant_request_policy rows for required tenant IDs: "
                        + ", ".join(missing_seed)
                    )
        else:
            summaries.append("active tenant request policies: unavailable")

        hierarchy_count = self._safe_count_active(TenantHierarchy, existing_tables, "tenant_hierarchy")
        control_scope_count = self._safe_count_active(TenantControlScope, existing_tables, "tenant_control_scope")
        summaries.append(
            f"active tenant hierarchy rows: {hierarchy_count if hierarchy_count is not None else 'unavailable'}"
        )
        summaries.append(
            f"active tenant control-scope rows: {control_scope_count if control_scope_count is not None else 'unavailable'}"
        )
        if hierarchy_count == 0 and control_scope_count == 0:
            warnings.append(
                "No active tenant_hierarchy or tenant_control_scope rows exist. Subordinate request flows will stay unavailable until explicit control data is loaded."
            )

        role_codes = self._fetch_role_codes(existing_tables)
        if role_codes is None:
            blockers.append("Unable to read role table. Verify DB RBAC schema is available in the target environment.")
        else:
            required_canonical_roles = set(ELIGIBILITY_ROLE_CODES + FULFILLMENT_ROLE_CODES + DISPATCH_ROLE_CODES)
            available_canonical_roles = set(normalize_role_codes(role_codes))
            missing_roles = sorted(required_canonical_roles - available_canonical_roles)
            summaries.append(
                f"required operations role groups present: {len(required_canonical_roles) - len(missing_roles)}/{len(required_canonical_roles)}"
            )
            if missing_roles:
                blockers.append(
                    "Missing required role coverage for Operations personas: "
                    + ", ".join(missing_roles)
                )

        permission_codes = self._fetch_permission_codes(existing_tables)
        if permission_codes is None:
            warnings.append("Permission table was not readable. Canonical Operations permission rows could not be verified.")
        else:
            missing_permissions = sorted(REQUIRED_OPERATIONS_PERMISSIONS - permission_codes)
            summaries.append(
                "canonical operations permissions present in DB RBAC: "
                f"{len(REQUIRED_OPERATIONS_PERMISSIONS) - len(missing_permissions)}/{len(REQUIRED_OPERATIONS_PERMISSIONS)}"
            )
            if missing_permissions:
                message = (
                    "DB RBAC is missing canonical Operations permission rows: "
                    + ", ".join(missing_permissions)
                    + ". api.rbac compatibility mapping currently bridges this, but canonical seeding is still recommended."
                )
                if strict_permissions:
                    blockers.append(message)
                else:
                    warnings.append(message)

        if not getattr(settings, "AUTH_USE_DB_RBAC", False):
            warnings.append("AUTH_USE_DB_RBAC is disabled; live readiness assumes DB RBAC remains the canonical authorization source.")

        agency_summary = self._fetch_active_agency_summary(existing_tables)
        if agency_summary is None:
            warnings.append("Agency coverage could not be verified.")
        else:
            summaries.append(f"active agencies: {agency_summary['active_agencies']}")
            summaries.append(f"agency scopes resolved to tenants: {agency_summary['resolved_agencies']}")
            summaries.append(f"non-ODPEM agency scopes resolved to tenants: {agency_summary['non_odpem_resolved_agencies']}")
            if agency_summary["active_agencies"] == 0:
                blockers.append("No active agencies exist. Frontend request creation cannot target beneficiary agencies.")
            elif agency_summary["non_odpem_resolved_agencies"] == 0:
                blockers.append(
                    "No active non-ODPEM agencies resolve to a tenant via agency->warehouse->tenant. "
                    "Frontend request creation cannot target real operational beneficiary agencies yet. "
                    "Run `python manage.py audit_relief_management_agency_scope --json-out backend/operations/examples/agency_scope_audit.json` "
                    "to generate the remediation inventory."
                )

        self.stdout.write("Relief Management frontend readiness check:")
        for line in summaries:
            self.stdout.write(f"- {line}")

        if warnings:
            self.stdout.write(self.style.WARNING("Warnings:"))
            for warning in warnings:
                self.stdout.write(f"  - {warning}")

        if blockers:
            self.stdout.write(self.style.ERROR("Blockers:"))
            for blocker in blockers:
                self.stdout.write(f"  - {blocker}")
            raise CommandError("Relief Management backend is not ready for live frontend integration.")

        self.stdout.write(self.style.SUCCESS("No live-frontend blockers detected."))

    def _migration_applied(self, app_label: str, migration_name: str) -> bool:
        try:
            return MigrationRecorder.Migration.objects.filter(app=app_label, name=migration_name).exists()
        except DatabaseError:
            return False

    def _existing_tables(self) -> set[str]:
        try:
            return set(connection.introspection.table_names())
        except DatabaseError:
            return set()

    def _active_rows(self, model, today: date):
        return model.objects.filter(
            status_code="ACTIVE",
            effective_date__lte=today,
        ).filter(Q(expiry_date__isnull=True) | Q(expiry_date__gte=today))

    def _safe_count_active(self, model, existing_tables: set[str], table_name: str) -> int | None:
        if table_name not in existing_tables:
            return None
        try:
            return self._active_rows(model, timezone.localdate()).count()
        except DatabaseError:
            return None

    def _fetch_role_codes(self, existing_tables: set[str]) -> set[str] | None:
        if "role" not in existing_tables:
            return None
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT DISTINCT UPPER(code) FROM role WHERE code IS NOT NULL")
                return {str(row[0]).strip().upper() for row in cursor.fetchall() if str(row[0]).strip()}
        except DatabaseError:
            return None

    def _fetch_permission_codes(self, existing_tables: set[str]) -> set[str] | None:
        if "permission" not in existing_tables:
            return None
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT DISTINCT LOWER(resource), LOWER(action)
                    FROM permission
                    WHERE resource IS NOT NULL AND action IS NOT NULL
                    """
                )
                return {f"{row[0]}.{row[1]}" for row in cursor.fetchall() if row[0] and row[1]}
        except DatabaseError:
            return None

    def _fetch_active_agency_summary(self, existing_tables: set[str]) -> dict[str, int] | None:
        if "agency" not in existing_tables or "warehouse" not in existing_tables or "tenant" not in existing_tables:
            return None
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        COUNT(*) AS active_agencies,
                        COUNT(t.tenant_id) AS resolved_agencies,
                        COUNT(
                            CASE
                                WHEN t.tenant_id IS NOT NULL
                                 AND UPPER(REPLACE(REPLACE(COALESCE(t.tenant_code, ''), '-', '_'), ' ', '_')) NOT LIKE 'ODPEM%%'
                                 AND UPPER(REPLACE(REPLACE(COALESCE(t.tenant_code, ''), '-', '_'), ' ', '_')) <> 'OFFICE_OF_DISASTER_P'
                                THEN 1
                                ELSE NULL
                            END
                        ) AS non_odpem_resolved_agencies
                    FROM agency a
                    LEFT JOIN warehouse w ON w.warehouse_id = a.warehouse_id
                    LEFT JOIN tenant t ON t.tenant_id = w.tenant_id
                    WHERE COALESCE(a.status_code, 'A') = 'A'
                    """
                )
                row = cursor.fetchone()
        except DatabaseError:
            return None
        return {
            "active_agencies": int(row[0] or 0),
            "resolved_agencies": int(row[1] or 0),
            "non_odpem_resolved_agencies": int(row[2] or 0),
        }
