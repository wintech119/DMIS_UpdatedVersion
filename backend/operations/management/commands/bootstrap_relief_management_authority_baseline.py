from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connection, transaction
from django.utils import timezone

from operations.models import TenantControlScope, TenantHierarchy, TenantRequestPolicy


@dataclass(frozen=True)
class TenantSnapshot:
    tenant_id: int
    tenant_code: str
    tenant_name: str
    tenant_type: str
    parent_tenant_id: int | None


def _normalize_token(value: object) -> str:
    text = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
    while "__" in text:
        text = text.replace("__", "_")
    return text


def _is_odpem_tenant_code(value: object) -> bool:
    code = _normalize_token(value)
    return bool(code) and (code.startswith("ODPEM") or code == "OFFICE_OF_DISASTER_P")


def _is_public_access_tenant(tenant: TenantSnapshot) -> bool:
    token = f"{_normalize_token(tenant.tenant_code)} {_normalize_token(tenant.tenant_name)}"
    return "PUBLIC" in token or "DASHBOARD" in token


class Command(BaseCommand):
    help = (
        "Bootstrap a conservative Relief Management authority baseline from current tenants. "
        "Assumes flat/direct tenants unless an explicit PARISH parent_tenant_id exists. Dry-run by default."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--actor", type=str, default="SYSTEM", help="Actor user ID for audit columns.")
        parser.add_argument(
            "--effective-date",
            type=str,
            default=None,
            help="Override effective date in YYYY-MM-DD format. Defaults to today.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Persist changes. Without this flag, the command only previews the plan.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        actor_id = str(options.get("actor") or "SYSTEM").strip() or "SYSTEM"
        effective_date = self._resolve_effective_date(options.get("effective_date"))
        apply_changes = bool(options.get("apply"))

        tenants = self._load_active_tenants()
        if not tenants:
            raise CommandError("No active tenants found.")

        policy_rows, control_scope_rows, hierarchy_rows, summary = self._build_rows(tenants, effective_date)

        self.stdout.write("Relief Management authority baseline bootstrap:")
        self.stdout.write(f"- active tenants: {len(tenants)}")
        self.stdout.write(f"- policy rows: {len(policy_rows)}")
        self.stdout.write(f"- control-scope rows: {len(control_scope_rows)}")
        self.stdout.write(f"- hierarchy rows: {len(hierarchy_rows)}")
        for key in sorted(summary):
            self.stdout.write(f"- {key}: {summary[key]}")

        if not apply_changes:
            self.stdout.write(
                self.style.WARNING(
                    "Dry-run only. This baseline only covers flat/direct tenants and explicit PARISH parent links."
                )
            )
            return

        now = timezone.now()
        created_counts = {"policies": 0, "control_scopes": 0, "hierarchies": 0}
        updated_counts = {"policies": 0, "control_scopes": 0, "hierarchies": 0}

        with transaction.atomic():
            for row in policy_rows:
                _record, created = TenantRequestPolicy.objects.update_or_create(
                    tenant_id=row["tenant_id"],
                    effective_date=row["effective_date"],
                    defaults={
                        "can_self_request_flag": row["can_self_request_flag"],
                        "request_authority_tenant_id": row["request_authority_tenant_id"],
                        "can_create_needs_list_flag": row["can_create_needs_list_flag"],
                        "can_apply_needs_list_to_relief_request_flag": row["can_apply_needs_list_to_relief_request_flag"],
                        "can_export_needs_list_for_donation_flag": row["can_export_needs_list_for_donation_flag"],
                        "can_broadcast_needs_list_for_donation_flag": row["can_broadcast_needs_list_for_donation_flag"],
                        "allow_odpem_bridge_flag": row["allow_odpem_bridge_flag"],
                        "expiry_date": row["expiry_date"],
                        "status_code": row["status_code"],
                        "create_by_id": actor_id,
                        "update_by_id": actor_id,
                        "update_dtime": now,
                    },
                )
                if created:
                    created_counts["policies"] += 1
                else:
                    updated_counts["policies"] += 1

            for row in control_scope_rows:
                _record, created = TenantControlScope.objects.update_or_create(
                    controller_tenant_id=row["controller_tenant_id"],
                    controlled_tenant_id=row["controlled_tenant_id"],
                    control_type=row["control_type"],
                    effective_date=row["effective_date"],
                    defaults={
                        "expiry_date": row["expiry_date"],
                        "status_code": row["status_code"],
                        "create_by_id": actor_id,
                        "update_by_id": actor_id,
                        "update_dtime": now,
                    },
                )
                if created:
                    created_counts["control_scopes"] += 1
                else:
                    updated_counts["control_scopes"] += 1

            for row in hierarchy_rows:
                _record, created = TenantHierarchy.objects.update_or_create(
                    parent_tenant_id=row["parent_tenant_id"],
                    child_tenant_id=row["child_tenant_id"],
                    relationship_type=row["relationship_type"],
                    effective_date=row["effective_date"],
                    defaults={
                        "can_parent_request_on_behalf_flag": row["can_parent_request_on_behalf_flag"],
                        "expiry_date": row["expiry_date"],
                        "status_code": row["status_code"],
                        "create_by_id": actor_id,
                        "update_by_id": actor_id,
                        "update_dtime": now,
                    },
                )
                if created:
                    created_counts["hierarchies"] += 1
                else:
                    updated_counts["hierarchies"] += 1

        self.stdout.write(self.style.SUCCESS("Relief Management authority baseline applied."))
        self.stdout.write(
            json.dumps(
                {
                    "created": created_counts,
                    "updated": updated_counts,
                    "summary": summary,
                },
                indent=2,
                sort_keys=True,
            )
        )

    def _resolve_effective_date(self, value: Any) -> date:
        if value in (None, ""):
            return timezone.localdate()
        try:
            return date.fromisoformat(str(value))
        except ValueError as exc:
            raise CommandError(f"Invalid --effective-date {value!r}.") from exc

    def _load_active_tenants(self) -> list[TenantSnapshot]:
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT tenant_id, tenant_code, tenant_name, tenant_type, parent_tenant_id
                    FROM tenant
                    WHERE COALESCE(status_code, 'A') = 'A'
                    ORDER BY tenant_id
                    """
                )
                rows = cursor.fetchall()
        except DatabaseError as exc:
            raise CommandError("Unable to load active tenants from the tenant table.") from exc

        return [
            TenantSnapshot(
                tenant_id=int(row[0]),
                tenant_code=str(row[1] or "").strip(),
                tenant_name=str(row[2] or "").strip(),
                tenant_type=str(row[3] or "").strip().upper(),
                parent_tenant_id=int(row[4]) if row[4] is not None else None,
            )
            for row in rows
        ]

    def _build_rows(
        self,
        tenants: list[TenantSnapshot],
        effective_date: date,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
        tenants_by_id = {tenant.tenant_id: tenant for tenant in tenants}
        policy_rows: list[dict[str, Any]] = []
        control_scope_rows: list[dict[str, Any]] = []
        hierarchy_rows: list[dict[str, Any]] = []
        summary = {
            "bridge_only_tenants": 0,
            "direct_self_service_tenants": 0,
            "public_read_only_tenants": 0,
            "parish_subordinate_tenants": 0,
            "unclassified_parent_links": 0,
        }

        for tenant in tenants:
            parent = tenants_by_id.get(tenant.parent_tenant_id) if tenant.parent_tenant_id else None
            policy_row = {
                "tenant_id": tenant.tenant_id,
                "can_self_request_flag": True,
                "request_authority_tenant_id": None,
                "can_create_needs_list_flag": True,
                "can_apply_needs_list_to_relief_request_flag": True,
                "can_export_needs_list_for_donation_flag": True,
                "can_broadcast_needs_list_for_donation_flag": True,
                "allow_odpem_bridge_flag": False,
                "effective_date": effective_date,
                "expiry_date": None,
                "status_code": "ACTIVE",
            }

            if _is_public_access_tenant(tenant):
                policy_row.update(
                    {
                        "can_self_request_flag": False,
                        "can_create_needs_list_flag": False,
                        "can_apply_needs_list_to_relief_request_flag": False,
                        "can_export_needs_list_for_donation_flag": False,
                        "can_broadcast_needs_list_for_donation_flag": False,
                    }
                )
                summary["public_read_only_tenants"] += 1
            elif _is_odpem_tenant_code(tenant.tenant_code):
                policy_row.update(
                    {
                        "can_self_request_flag": False,
                        "allow_odpem_bridge_flag": True,
                    }
                )
                summary["bridge_only_tenants"] += 1
            elif parent is not None and parent.tenant_type == "PARISH":
                policy_row.update(
                    {
                        "can_self_request_flag": False,
                        "request_authority_tenant_id": parent.tenant_id,
                    }
                )
                control_scope_rows.append(
                    {
                        "controller_tenant_id": parent.tenant_id,
                        "controlled_tenant_id": tenant.tenant_id,
                        "control_type": "REQUEST_AUTHORITY",
                        "effective_date": effective_date,
                        "expiry_date": None,
                        "status_code": "ACTIVE",
                    }
                )
                hierarchy_rows.append(
                    {
                        "parent_tenant_id": parent.tenant_id,
                        "child_tenant_id": tenant.tenant_id,
                        "relationship_type": "REQUEST_AUTHORITY",
                        "can_parent_request_on_behalf_flag": True,
                        "effective_date": effective_date,
                        "expiry_date": None,
                        "status_code": "ACTIVE",
                    }
                )
                summary["parish_subordinate_tenants"] += 1
            else:
                if parent is not None:
                    summary["unclassified_parent_links"] += 1
                summary["direct_self_service_tenants"] += 1

            policy_rows.append(policy_row)

        return policy_rows, control_scope_rows, hierarchy_rows, summary
