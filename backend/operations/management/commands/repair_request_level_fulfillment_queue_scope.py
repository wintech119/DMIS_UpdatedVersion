from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from operations import policy as operations_policy
from operations.constants import (
    QUEUE_CODE_FULFILLMENT,
    QUEUE_CODE_OVERRIDE,
    REQUEST_STATUS_APPROVED_FOR_FULFILLMENT,
    REQUEST_STATUS_FULFILLED,
    REQUEST_STATUS_PARTIALLY_FULFILLED,
)
from operations.models import (
    OperationsNotification,
    OperationsQueueAssignment,
    OperationsReliefRequest,
)

ENTITY_REQUEST = "RELIEF_REQUEST"
REPAIRABLE_REQUEST_STATUSES = frozenset(
    {
        REQUEST_STATUS_APPROVED_FOR_FULFILLMENT,
        REQUEST_STATUS_PARTIALLY_FULFILLED,
        REQUEST_STATUS_FULFILLED,
    }
)


@dataclass(frozen=True)
class PlannedTenantRepair:
    row_kind: str
    row_id: int
    request_id: int
    request_no: str
    queue_code: str
    role_or_user: str | None
    current_tenant_id: int | None
    target_tenant_id: int
    status_code: str | None = None

    def render(self) -> str:
        role_fragment = self.role_or_user or "-"
        status_fragment = f" status={self.status_code}" if self.status_code else ""
        return (
            f"{self.row_kind} id={self.row_id} request_no={self.request_no} "
            f"request_id={self.request_id} queue_code={self.queue_code} "
            f"owner={role_fragment} tenant={self.current_tenant_id!r} -> {self.target_tenant_id}"
            f"{status_fragment}"
        )


class Command(BaseCommand):
    help = (
        "Repair request-level fulfillment queue assignments and notifications that were scoped to an external "
        "beneficiary tenant instead of the operational ODPEM fulfillment tenant. Dry-run by default."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--request-no",
            type=str,
            default=None,
            help="Optional request number filter, for example RQ95009.",
        )
        parser.add_argument(
            "--reliefrqst-id",
            type=int,
            default=None,
            help="Optional relief request ID filter, for example 95009.",
        )
        parser.add_argument(
            "--queue-code",
            type=str,
            choices=[QUEUE_CODE_FULFILLMENT, QUEUE_CODE_OVERRIDE],
            default=None,
            help="Optional queue-code filter. Defaults to PACKAGE_FULFILLMENT, or both repairable request-level queues when --include-override is passed.",
        )
        parser.add_argument(
            "--include-override",
            action="store_true",
            help="Also repair request-level OVERRIDE_APPROVAL rows.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Persist changes. Without this flag, the command only previews the repairs.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        apply_changes = bool(options.get("apply"))
        queue_codes = self._resolve_queue_codes(
            queue_code=options.get("queue_code"),
            include_override=bool(options.get("include_override")),
        )
        target_tenant_id = operations_policy.resolve_odpem_fulfillment_tenant_id()
        if target_tenant_id is None:
            raise CommandError("ODPEM fulfillment tenant could not be resolved.")
        target_tenant_id = int(target_tenant_id)

        request_rows = self._load_candidate_requests(
            request_no=options.get("request_no"),
            reliefrqst_id=options.get("reliefrqst_id"),
            target_tenant_id=target_tenant_id,
        )
        if (options.get("request_no") or options.get("reliefrqst_id")) and not request_rows:
            raise CommandError("No matching request was found for the supplied filters.")

        assignment_repairs = self._build_assignment_repairs(
            request_rows=request_rows,
            queue_codes=queue_codes,
            target_tenant_id=target_tenant_id,
        )
        notification_repairs = self._build_notification_repairs(
            request_rows=request_rows,
            queue_codes=queue_codes,
            target_tenant_id=target_tenant_id,
        )

        self.stdout.write("Request-level fulfillment queue scope repair:")
        self.stdout.write(f"- target fulfillment tenant: {target_tenant_id}")
        self.stdout.write(f"- queue codes: {', '.join(queue_codes)}")
        self.stdout.write(f"- candidate requests: {len(request_rows)}")
        self.stdout.write(f"- planned queue assignment repairs: {len(assignment_repairs)}")
        self.stdout.write(f"- planned notification repairs: {len(notification_repairs)}")

        for repair in assignment_repairs + notification_repairs:
            self.stdout.write(f"  - {repair.render()}")

        if not apply_changes:
            self.stdout.write(self.style.WARNING("Dry-run only. Re-run with --apply to persist changes."))
            return

        with transaction.atomic():
            assignment_updates = self._apply_assignment_repairs(
                assignment_repairs,
                target_tenant_id=target_tenant_id,
            )
            notification_updates = self._apply_notification_repairs(
                notification_repairs,
                target_tenant_id=target_tenant_id,
            )

        total_updates = assignment_updates + notification_updates
        if total_updates == 0:
            self.stdout.write(self.style.SUCCESS("No repairs needed."))
        else:
            self.stdout.write(self.style.SUCCESS("Request-level fulfillment queue scope repair applied."))
        self.stdout.write(f"- queue assignments updated: {assignment_updates}")
        self.stdout.write(f"- notifications updated: {notification_updates}")
        self.stdout.write(f"- total rows repaired: {total_updates}")

    def _resolve_queue_codes(self, *, queue_code: str | None, include_override: bool) -> list[str]:
        if queue_code:
            if queue_code == QUEUE_CODE_OVERRIDE and not include_override:
                raise CommandError("--queue-code OVERRIDE_APPROVAL requires --include-override.")
            return [queue_code]
        queue_codes = [QUEUE_CODE_FULFILLMENT]
        if include_override:
            queue_codes.append(QUEUE_CODE_OVERRIDE)
        return queue_codes

    def _load_candidate_requests(
        self,
        *,
        request_no: str | None,
        reliefrqst_id: int | None,
        target_tenant_id: int,
    ) -> dict[int, OperationsReliefRequest]:
        queryset = OperationsReliefRequest.objects.filter(status_code__in=REPAIRABLE_REQUEST_STATUSES)
        if request_no:
            queryset = queryset.filter(request_no=str(request_no).strip())
        if reliefrqst_id:
            queryset = queryset.filter(relief_request_id=int(reliefrqst_id))

        queryset = queryset.filter(
            ~Q(requesting_tenant_id=target_tenant_id)
            | (Q(beneficiary_tenant_id__isnull=False) & ~Q(beneficiary_tenant_id=target_tenant_id))
        )
        return {
            int(record.relief_request_id): record
            for record in queryset.order_by("relief_request_id")
        }

    def _build_assignment_repairs(
        self,
        *,
        request_rows: dict[int, OperationsReliefRequest],
        queue_codes: list[str],
        target_tenant_id: int,
    ) -> list[PlannedTenantRepair]:
        if not request_rows:
            return []
        repairs: list[PlannedTenantRepair] = []
        queryset = (
            OperationsQueueAssignment.objects.filter(
                entity_type=ENTITY_REQUEST,
                queue_code__in=queue_codes,
                entity_id__in=list(request_rows),
            )
            .exclude(assigned_tenant_id=target_tenant_id)
            .order_by("entity_id", "queue_code", "queue_assignment_id")
        )
        for row in queryset:
            request_record = request_rows.get(int(row.entity_id))
            if request_record is None:
                continue
            repairs.append(
                PlannedTenantRepair(
                    row_kind="QUEUE_ASSIGNMENT",
                    row_id=int(row.queue_assignment_id),
                    request_id=int(request_record.relief_request_id),
                    request_no=request_record.request_no,
                    queue_code=row.queue_code,
                    role_or_user=row.assigned_role_code or row.assigned_user_id,
                    current_tenant_id=row.assigned_tenant_id,
                    target_tenant_id=target_tenant_id,
                    status_code=row.assignment_status,
                )
            )
        return repairs

    def _build_notification_repairs(
        self,
        *,
        request_rows: dict[int, OperationsReliefRequest],
        queue_codes: list[str],
        target_tenant_id: int,
    ) -> list[PlannedTenantRepair]:
        if not request_rows:
            return []
        repairs: list[PlannedTenantRepair] = []
        queryset = (
            OperationsNotification.objects.filter(
                entity_type=ENTITY_REQUEST,
                queue_code__in=queue_codes,
                entity_id__in=list(request_rows),
            )
            .exclude(recipient_tenant_id=target_tenant_id)
            .order_by("entity_id", "queue_code", "notification_id")
        )
        for row in queryset:
            request_record = request_rows.get(int(row.entity_id))
            if request_record is None:
                continue
            repairs.append(
                PlannedTenantRepair(
                    row_kind="NOTIFICATION",
                    row_id=int(row.notification_id),
                    request_id=int(request_record.relief_request_id),
                    request_no=request_record.request_no,
                    queue_code=str(row.queue_code or ""),
                    role_or_user=row.recipient_role_code or row.recipient_user_id,
                    current_tenant_id=row.recipient_tenant_id,
                    target_tenant_id=target_tenant_id,
                )
            )
        return repairs

    def _apply_assignment_repairs(
        self,
        repairs: list[PlannedTenantRepair],
        *,
        target_tenant_id: int,
    ) -> int:
        if not repairs:
            return 0
        updated = 0
        row_ids = [repair.row_id for repair in repairs]
        for row in OperationsQueueAssignment.objects.filter(queue_assignment_id__in=row_ids):
            if row.assigned_tenant_id == target_tenant_id:
                continue
            row.assigned_tenant_id = target_tenant_id
            row.save(update_fields=["assigned_tenant_id"])
            updated += 1
        return updated

    def _apply_notification_repairs(
        self,
        repairs: list[PlannedTenantRepair],
        *,
        target_tenant_id: int,
    ) -> int:
        if not repairs:
            return 0
        updated = 0
        row_ids = [repair.row_id for repair in repairs]
        for row in OperationsNotification.objects.filter(notification_id__in=row_ids):
            if row.recipient_tenant_id == target_tenant_id:
                continue
            row.recipient_tenant_id = target_tenant_id
            row.save(update_fields=["recipient_tenant_id"])
            updated += 1
        return updated
