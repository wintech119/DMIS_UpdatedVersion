from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connection, transaction
from django.utils import timezone

from operations.models import TenantControlScope, TenantHierarchy, TenantRequestPolicy


@dataclass(frozen=True)
class PolicyRow:
    tenant_id: int
    can_self_request_flag: bool
    request_authority_tenant_id: int | None
    can_create_needs_list_flag: bool
    can_apply_needs_list_to_relief_request_flag: bool
    can_export_needs_list_for_donation_flag: bool
    can_broadcast_needs_list_for_donation_flag: bool
    allow_odpem_bridge_flag: bool
    effective_date: date
    expiry_date: date | None
    status_code: str


@dataclass(frozen=True)
class ControlScopeRow:
    controller_tenant_id: int
    controlled_tenant_id: int
    control_type: str
    effective_date: date
    expiry_date: date | None
    status_code: str


@dataclass(frozen=True)
class HierarchyRow:
    parent_tenant_id: int
    child_tenant_id: int
    relationship_type: str
    can_parent_request_on_behalf_flag: bool
    effective_date: date
    expiry_date: date | None
    status_code: str


class Command(BaseCommand):
    help = (
        "Import frozen Relief Management tenant authority policy, control-scope, and "
        "hierarchy data from JSON. Dry-run by default."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("source", type=str, help="Path to the JSON seed file.")
        parser.add_argument("--actor", type=str, default="SYSTEM", help="Actor user ID for audit columns.")
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Persist changes. Without this flag, the command only validates and previews.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        source_path = Path(str(options["source"])).expanduser().resolve()
        actor_id = str(options.get("actor") or "SYSTEM").strip() or "SYSTEM"
        apply_changes = bool(options.get("apply"))

        if not source_path.exists():
            raise CommandError(f"Source file does not exist: {source_path}")

        payload = self._load_payload(source_path)
        policies, control_scopes, hierarchies = self._build_rows(payload)

        self.stdout.write("Relief Management authority import:")
        self.stdout.write(f"- source: {source_path}")
        self.stdout.write(f"- policies: {len(policies)}")
        self.stdout.write(f"- control scopes: {len(control_scopes)}")
        self.stdout.write(f"- hierarchies: {len(hierarchies)}")

        if not apply_changes:
            self.stdout.write(self.style.WARNING("Dry-run only. Re-run with --apply to persist changes."))
            return

        now = timezone.now()
        created_counts = {"policies": 0, "control_scopes": 0, "hierarchies": 0}
        updated_counts = {"policies": 0, "control_scopes": 0, "hierarchies": 0}

        with transaction.atomic():
            for row in policies:
                _record, created = TenantRequestPolicy.objects.update_or_create(
                    tenant_id=row.tenant_id,
                    effective_date=row.effective_date,
                    defaults={
                        "can_self_request_flag": row.can_self_request_flag,
                        "request_authority_tenant_id": row.request_authority_tenant_id,
                        "can_create_needs_list_flag": row.can_create_needs_list_flag,
                        "can_apply_needs_list_to_relief_request_flag": row.can_apply_needs_list_to_relief_request_flag,
                        "can_export_needs_list_for_donation_flag": row.can_export_needs_list_for_donation_flag,
                        "can_broadcast_needs_list_for_donation_flag": row.can_broadcast_needs_list_for_donation_flag,
                        "allow_odpem_bridge_flag": row.allow_odpem_bridge_flag,
                        "expiry_date": row.expiry_date,
                        "status_code": row.status_code,
                        "create_by_id": actor_id,
                        "update_by_id": actor_id,
                        "update_dtime": now,
                    },
                )
                if created:
                    created_counts["policies"] += 1
                else:
                    updated_counts["policies"] += 1

            for row in control_scopes:
                _record, created = TenantControlScope.objects.update_or_create(
                    controller_tenant_id=row.controller_tenant_id,
                    controlled_tenant_id=row.controlled_tenant_id,
                    control_type=row.control_type,
                    effective_date=row.effective_date,
                    defaults={
                        "expiry_date": row.expiry_date,
                        "status_code": row.status_code,
                        "create_by_id": actor_id,
                        "update_by_id": actor_id,
                        "update_dtime": now,
                    },
                )
                if created:
                    created_counts["control_scopes"] += 1
                else:
                    updated_counts["control_scopes"] += 1

            for row in hierarchies:
                _record, created = TenantHierarchy.objects.update_or_create(
                    parent_tenant_id=row.parent_tenant_id,
                    child_tenant_id=row.child_tenant_id,
                    relationship_type=row.relationship_type,
                    effective_date=row.effective_date,
                    defaults={
                        "can_parent_request_on_behalf_flag": row.can_parent_request_on_behalf_flag,
                        "expiry_date": row.expiry_date,
                        "status_code": row.status_code,
                        "create_by_id": actor_id,
                        "update_by_id": actor_id,
                        "update_dtime": now,
                    },
                )
                if created:
                    created_counts["hierarchies"] += 1
                else:
                    updated_counts["hierarchies"] += 1

        self.stdout.write(self.style.SUCCESS("Relief Management authority data imported."))
        self.stdout.write(
            json.dumps(
                {
                    "created": created_counts,
                    "updated": updated_counts,
                },
                indent=2,
                sort_keys=True,
            )
        )

    def _load_payload(self, source_path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(source_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CommandError(f"Invalid JSON in {source_path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise CommandError("Seed file must contain a JSON object at the top level.")
        return payload

    def _build_rows(
        self,
        payload: dict[str, Any],
    ) -> tuple[list[PolicyRow], list[ControlScopeRow], list[HierarchyRow]]:
        policies_payload = payload.get("policies") or []
        control_scopes_payload = payload.get("control_scopes") or []
        hierarchies_payload = payload.get("hierarchies") or []

        if not isinstance(policies_payload, list):
            raise CommandError("'policies' must be a list.")
        if not isinstance(control_scopes_payload, list):
            raise CommandError("'control_scopes' must be a list.")
        if not isinstance(hierarchies_payload, list):
            raise CommandError("'hierarchies' must be a list.")

        policies = [self._build_policy_row(index, record) for index, record in enumerate(policies_payload, start=1)]
        control_scopes = [
            self._build_control_scope_row(index, record)
            for index, record in enumerate(control_scopes_payload, start=1)
        ]
        hierarchies = [
            self._build_hierarchy_row(index, record)
            for index, record in enumerate(hierarchies_payload, start=1)
        ]
        return policies, control_scopes, hierarchies

    def _build_policy_row(self, index: int, record: Any) -> PolicyRow:
        record = self._require_mapping(record, section="policies", index=index)
        return PolicyRow(
            tenant_id=self._resolve_tenant_reference(
                record.get("tenant_id"),
                record.get("tenant_code"),
                section="policies",
                index=index,
                field_name="tenant",
                allow_null=False,
            ),
            can_self_request_flag=self._parse_bool(record.get("can_self_request_flag"), default=True),
            request_authority_tenant_id=self._resolve_tenant_reference(
                record.get("request_authority_tenant_id"),
                record.get("request_authority_tenant_code"),
                section="policies",
                index=index,
                field_name="request_authority_tenant",
                allow_null=True,
            ),
            can_create_needs_list_flag=self._parse_bool(record.get("can_create_needs_list_flag"), default=True),
            can_apply_needs_list_to_relief_request_flag=self._parse_bool(
                record.get("can_apply_needs_list_to_relief_request_flag"),
                default=True,
            ),
            can_export_needs_list_for_donation_flag=self._parse_bool(
                record.get("can_export_needs_list_for_donation_flag"),
                default=True,
            ),
            can_broadcast_needs_list_for_donation_flag=self._parse_bool(
                record.get("can_broadcast_needs_list_for_donation_flag"),
                default=True,
            ),
            allow_odpem_bridge_flag=self._parse_bool(record.get("allow_odpem_bridge_flag"), default=False),
            effective_date=self._parse_date(record.get("effective_date"), section="policies", index=index),
            expiry_date=self._parse_optional_date(record.get("expiry_date"), section="policies", index=index),
            status_code=self._parse_status(record.get("status_code")),
        )

    def _build_control_scope_row(self, index: int, record: Any) -> ControlScopeRow:
        record = self._require_mapping(record, section="control_scopes", index=index)
        control_type = str(record.get("control_type") or "").strip().upper()
        if not control_type:
            raise CommandError(f"control_scopes[{index}] must provide control_type.")
        return ControlScopeRow(
            controller_tenant_id=self._resolve_tenant_reference(
                record.get("controller_tenant_id"),
                record.get("controller_tenant_code"),
                section="control_scopes",
                index=index,
                field_name="controller_tenant",
                allow_null=False,
            ),
            controlled_tenant_id=self._resolve_tenant_reference(
                record.get("controlled_tenant_id"),
                record.get("controlled_tenant_code"),
                section="control_scopes",
                index=index,
                field_name="controlled_tenant",
                allow_null=False,
            ),
            control_type=control_type,
            effective_date=self._parse_date(record.get("effective_date"), section="control_scopes", index=index),
            expiry_date=self._parse_optional_date(record.get("expiry_date"), section="control_scopes", index=index),
            status_code=self._parse_status(record.get("status_code")),
        )

    def _build_hierarchy_row(self, index: int, record: Any) -> HierarchyRow:
        record = self._require_mapping(record, section="hierarchies", index=index)
        relationship_type = str(record.get("relationship_type") or "").strip().upper()
        if not relationship_type:
            raise CommandError(f"hierarchies[{index}] must provide relationship_type.")
        return HierarchyRow(
            parent_tenant_id=self._resolve_tenant_reference(
                record.get("parent_tenant_id"),
                record.get("parent_tenant_code"),
                section="hierarchies",
                index=index,
                field_name="parent_tenant",
                allow_null=False,
            ),
            child_tenant_id=self._resolve_tenant_reference(
                record.get("child_tenant_id"),
                record.get("child_tenant_code"),
                section="hierarchies",
                index=index,
                field_name="child_tenant",
                allow_null=False,
            ),
            relationship_type=relationship_type,
            can_parent_request_on_behalf_flag=self._parse_bool(
                record.get("can_parent_request_on_behalf_flag"),
                default=False,
            ),
            effective_date=self._parse_date(record.get("effective_date"), section="hierarchies", index=index),
            expiry_date=self._parse_optional_date(record.get("expiry_date"), section="hierarchies", index=index),
            status_code=self._parse_status(record.get("status_code")),
        )

    def _resolve_tenant_reference(
        self,
        tenant_id: Any,
        tenant_code: Any,
        *,
        section: str,
        index: int,
        field_name: str,
        allow_null: bool,
    ) -> int | None:
        parsed_id = self._parse_positive_int(tenant_id)
        normalized_code = str(tenant_code or "").strip().upper()
        if parsed_id is None and not normalized_code:
            if allow_null:
                return None
            raise CommandError(f"{section}[{index}] must provide {field_name}_id or {field_name}_code.")

        try:
            with connection.cursor() as cursor:
                if parsed_id is not None:
                    cursor.execute(
                        """
                        SELECT tenant_id
                        FROM tenant
                        WHERE tenant_id = %s
                        LIMIT 1
                        """,
                        [parsed_id],
                    )
                    row = cursor.fetchone()
                    if row:
                        return int(row[0])
                if normalized_code:
                    cursor.execute(
                        """
                        SELECT tenant_id
                        FROM tenant
                        WHERE UPPER(COALESCE(tenant_code, '')) = %s
                        LIMIT 1
                        """,
                        [normalized_code],
                    )
                    row = cursor.fetchone()
                    if row:
                        return int(row[0])
        except DatabaseError as exc:
            raise CommandError("Unable to validate tenant references against the tenant table.") from exc

        if allow_null:
            return None
        raise CommandError(
            f"{section}[{index}] references unknown {field_name}: id={tenant_id!r}, code={tenant_code!r}."
        )

    def _parse_status(self, value: Any) -> str:
        normalized = str(value or "ACTIVE").strip().upper()
        return normalized or "ACTIVE"

    def _parse_bool(self, value: Any, *, default: bool) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        normalized = str(value).strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        raise CommandError(f"Expected boolean-compatible value, got {value!r}.")

    def _parse_date(self, value: Any, *, section: str, index: int) -> date:
        if not value:
            raise CommandError(f"{section}[{index}] must provide effective_date.")
        try:
            return date.fromisoformat(str(value))
        except ValueError as exc:
            raise CommandError(f"{section}[{index}] has invalid ISO date {value!r}.") from exc

    def _parse_optional_date(self, value: Any, *, section: str, index: int) -> date | None:
        if value in (None, ""):
            return None
        try:
            return date.fromisoformat(str(value))
        except ValueError as exc:
            raise CommandError(f"{section}[{index}] has invalid ISO date {value!r}.") from exc

    def _parse_positive_int(self, value: Any) -> int | None:
        if value in (None, ""):
            return None
        try:
            parsed = int(str(value))
        except ValueError:
            return None
        return parsed if parsed > 0 else None

    def _require_mapping(self, record: Any, *, section: str, index: int) -> dict[str, Any]:
        if not isinstance(record, dict):
            raise CommandError(f"{section}[{index}] must be a JSON object.")
        return record
