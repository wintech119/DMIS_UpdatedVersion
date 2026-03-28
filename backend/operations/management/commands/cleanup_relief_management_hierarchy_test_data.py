from __future__ import annotations

from datetime import date
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, transaction
from django.utils import timezone

from operations.models import TenantControlScope, TenantHierarchy, TenantRequestPolicy


class Command(BaseCommand):
    help = (
        "Revert temporary parish-to-subordinate request-authority data for Relief Management QA. "
        "Dry-run by default."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--parish-tenant-id", type=int, default=None)
        parser.add_argument("--parish-tenant-code", type=str, default="PARISH-KN")
        parser.add_argument("--subordinate-tenant-id", type=int, default=None)
        parser.add_argument("--subordinate-tenant-code", type=str, default="FFP")
        parser.add_argument("--actor", type=str, default="SYSTEM")
        parser.add_argument("--effective-date", type=str, default=None)
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Persist changes. Without this flag, the command only previews the plan.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        actor_id = str(options.get("actor") or "SYSTEM").strip() or "SYSTEM"
        apply_changes = bool(options.get("apply"))
        effective_date = self._resolve_effective_date(options.get("effective_date"))

        parish = self._resolve_tenant(
            tenant_id=options.get("parish_tenant_id"),
            tenant_code=options.get("parish_tenant_code"),
        )
        subordinate = self._resolve_tenant(
            tenant_id=options.get("subordinate_tenant_id"),
            tenant_code=options.get("subordinate_tenant_code"),
        )

        if parish["tenant_id"] == subordinate["tenant_id"]:
            raise CommandError("Parish and subordinate tenants must differ.")
        if str(parish["tenant_type"]).upper() != "PARISH":
            raise CommandError("The parish tenant must have tenant_type=PARISH.")
        if self._is_odpem_tenant_code(subordinate["tenant_code"]):
            raise CommandError("The subordinate tenant must be non-ODPEM.")

        self.stdout.write("Relief Management hierarchy test-data cleanup:")
        self.stdout.write(f"- parish tenant: {parish['tenant_id']} ({parish['tenant_code']})")
        self.stdout.write(f"- subordinate tenant: {subordinate['tenant_id']} ({subordinate['tenant_code']})")
        self.stdout.write(f"- effective date: {effective_date.isoformat()}")

        if not apply_changes:
            self.stdout.write(self.style.WARNING("Dry-run only. Re-run with --apply to persist changes."))
            return

        now = timezone.now()
        with transaction.atomic():
            TenantRequestPolicy.objects.update_or_create(
                tenant_id=subordinate["tenant_id"],
                effective_date=effective_date,
                defaults={
                    "can_self_request_flag": True,
                    "request_authority_tenant_id": None,
                    "can_create_needs_list_flag": True,
                    "can_apply_needs_list_to_relief_request_flag": True,
                    "can_export_needs_list_for_donation_flag": True,
                    "can_broadcast_needs_list_for_donation_flag": True,
                    "allow_odpem_bridge_flag": False,
                    "expiry_date": None,
                    "status_code": "ACTIVE",
                    "create_by_id": actor_id,
                    "update_by_id": actor_id,
                    "update_dtime": now,
                },
            )
            TenantControlScope.objects.filter(
                controller_tenant_id=parish["tenant_id"],
                controlled_tenant_id=subordinate["tenant_id"],
                control_type="REQUEST_AUTHORITY",
                status_code="ACTIVE",
            ).update(
                status_code="INACTIVE",
                expiry_date=effective_date,
                update_by_id=actor_id,
                update_dtime=now,
            )
            TenantHierarchy.objects.filter(
                parent_tenant_id=parish["tenant_id"],
                child_tenant_id=subordinate["tenant_id"],
                relationship_type="REQUEST_AUTHORITY",
                status_code="ACTIVE",
            ).update(
                status_code="INACTIVE",
                expiry_date=effective_date,
                update_by_id=actor_id,
                update_dtime=now,
            )

        self.stdout.write(self.style.SUCCESS("Temporary Relief Management hierarchy data has been reverted."))

    def _resolve_effective_date(self, value: Any) -> date:
        if value in (None, ""):
            return timezone.localdate()
        try:
            return date.fromisoformat(str(value))
        except ValueError as exc:
            raise CommandError(f"Invalid --effective-date {value!r}.") from exc

    def _resolve_tenant(self, *, tenant_id: Any, tenant_code: Any) -> dict[str, Any]:
        parsed_tenant_id = self._safe_int(tenant_id)
        normalized_code = str(tenant_code or "").strip().upper()
        from django.db import connection

        try:
            with connection.cursor() as cursor:
                if parsed_tenant_id is not None:
                    cursor.execute(
                        """
                        SELECT tenant_id, tenant_code, tenant_name, tenant_type
                        FROM tenant
                        WHERE tenant_id = %s AND COALESCE(status_code, 'A') = 'A'
                        LIMIT 1
                        """,
                        [parsed_tenant_id],
                    )
                else:
                    cursor.execute(
                        """
                        SELECT tenant_id, tenant_code, tenant_name, tenant_type
                        FROM tenant
                        WHERE UPPER(COALESCE(tenant_code, '')) = %s AND COALESCE(status_code, 'A') = 'A'
                        LIMIT 1
                        """,
                        [normalized_code],
                    )
                row = cursor.fetchone()
        except DatabaseError as exc:
            raise CommandError("Unable to resolve tenant.") from exc
        if not row:
            raise CommandError("Target tenant does not exist or is inactive.")
        return {
            "tenant_id": int(row[0]),
            "tenant_code": str(row[1] or "").strip(),
            "tenant_name": str(row[2] or "").strip(),
            "tenant_type": str(row[3] or "").strip(),
        }

    def _safe_int(self, value: Any) -> int | None:
        try:
            parsed = int(str(value).strip())
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    def _is_odpem_tenant_code(self, value: object) -> bool:
        normalized = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
        while "__" in normalized:
            normalized = normalized.replace("__", "_")
        return bool(normalized) and (normalized.startswith("ODPEM") or normalized == "OFFICE_OF_DISASTER_P")
