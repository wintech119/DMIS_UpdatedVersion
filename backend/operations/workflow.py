from __future__ import annotations

from collections.abc import Iterable

from django.db.models import Q
from django.utils import timezone

from api.tenancy import TenantContext
from operations.constants import normalize_role_codes
from operations.models import (
    OperationsActionAudit,
    OperationsNotification,
    OperationsQueueAssignment,
    OperationsStatusHistory,
)


def record_status_transition(
    *,
    entity_type: str,
    entity_id: int,
    from_status: str | None,
    to_status: str,
    actor_id: str,
    reason_text: str | None = None,
) -> None:
    if from_status == to_status:
        return
    OperationsStatusHistory.objects.create(
        entity_type=entity_type,
        entity_id=int(entity_id),
        from_status_code=from_status,
        to_status_code=to_status,
        changed_by_id=actor_id,
        reason_text=reason_text,
    )


def record_action_audit(
    *,
    entity_type: str,
    entity_id: int,
    action_code: str,
    actor_id: str,
    actor_role_code: str,
    package_id: int | None = None,
    consolidation_leg_id: int | None = None,
    tenant_id: int | None = None,
    warehouse_id: int | None = None,
    action_reason: str | None = None,
    artifact_reference: str | None = None,
) -> None:
    OperationsActionAudit.objects.create(
        entity_type=entity_type,
        entity_id=int(entity_id),
        package_id=package_id,
        consolidation_leg_id=consolidation_leg_id,
        tenant_id=tenant_id,
        warehouse_id=warehouse_id,
        action_code=action_code,
        action_reason=action_reason,
        artifact_reference=artifact_reference,
        acted_by_user_id=actor_id,
        acted_by_role_code=actor_role_code,
    )


def create_role_notifications(
    *,
    event_code: str,
    entity_type: str,
    entity_id: int,
    message_text: str,
    role_codes: Iterable[str],
    tenant_id: int | None = None,
    queue_code: str | None = None,
) -> None:
    for role_code in normalize_role_codes(role_codes):
        OperationsNotification.objects.create(
            event_code=event_code,
            entity_type=entity_type,
            entity_id=int(entity_id),
            recipient_role_code=role_code,
            recipient_tenant_id=tenant_id,
            message_text=message_text,
            queue_code=queue_code,
        )


def create_user_notification(
    *,
    event_code: str,
    entity_type: str,
    entity_id: int,
    recipient_user_id: str,
    message_text: str,
    tenant_id: int | None = None,
    queue_code: str | None = None,
) -> None:
    OperationsNotification.objects.create(
        event_code=event_code,
        entity_type=entity_type,
        entity_id=int(entity_id),
        recipient_user_id=recipient_user_id,
        recipient_tenant_id=tenant_id,
        message_text=message_text,
        queue_code=queue_code,
    )


def assign_roles_to_queue(
    *,
    queue_code: str,
    entity_type: str,
    entity_id: int,
    role_codes: Iterable[str],
    tenant_id: int | None = None,
) -> None:
    for role_code in normalize_role_codes(role_codes):
        OperationsQueueAssignment.objects.update_or_create(
            queue_code=queue_code,
            entity_type=entity_type,
            entity_id=int(entity_id),
            assigned_role_code=role_code,
            defaults={
                "assigned_tenant_id": tenant_id,
                "assignment_status": "OPEN",
                "assigned_at": timezone.now(),
                "completed_at": None,
            },
        )


def assign_user_to_queue(
    *,
    queue_code: str,
    entity_type: str,
    entity_id: int,
    user_id: str,
    tenant_id: int | None = None,
) -> None:
    OperationsQueueAssignment.objects.update_or_create(
        queue_code=queue_code,
        entity_type=entity_type,
        entity_id=int(entity_id),
        assigned_user_id=user_id,
        defaults={
            "assigned_tenant_id": tenant_id,
            "assignment_status": "OPEN",
            "assigned_at": timezone.now(),
            "completed_at": None,
        },
    )


def complete_queue_assignments(
    *,
    entity_type: str,
    entity_id: int,
    queue_code: str | None = None,
    actor_id: str,
    completion_status: str = "COMPLETED",
) -> int:
    del actor_id  # kept to keep the service call explicit and future-safe
    queryset = OperationsQueueAssignment.objects.filter(
        entity_type=entity_type,
        entity_id=int(entity_id),
        assignment_status="OPEN",
    )
    if queue_code:
        queryset = queryset.filter(queue_code=queue_code)
    return queryset.update(
        assignment_status=completion_status,
        completed_at=timezone.now(),
    )


def actor_queue_queryset(
    *,
    actor_id: str,
    actor_roles: Iterable[str],
    tenant_context: TenantContext,
):
    normalized_roles = normalize_role_codes(actor_roles)
    filters = Q(assigned_user_id=actor_id)
    if normalized_roles:
        filters |= Q(assigned_role_code__in=normalized_roles)

    queryset = OperationsQueueAssignment.objects.filter(filters, assignment_status="OPEN")
    if tenant_context.active_tenant_id is not None:
        queryset = queryset.filter(
            Q(assigned_tenant_id__isnull=True) | Q(assigned_tenant_id=tenant_context.active_tenant_id)
        )
    return queryset.order_by("-assigned_at", "-queue_assignment_id")


def actor_notification_queryset(
    *,
    actor_id: str,
    actor_roles: Iterable[str],
    tenant_context: TenantContext,
):
    normalized_roles = normalize_role_codes(actor_roles)
    filters = Q(recipient_user_id=actor_id)
    if normalized_roles:
        filters |= Q(recipient_role_code__in=normalized_roles)

    queryset = OperationsNotification.objects.filter(filters)
    if tenant_context.active_tenant_id is not None:
        queryset = queryset.filter(
            Q(recipient_tenant_id__isnull=True) | Q(recipient_tenant_id=tenant_context.active_tenant_id)
        )
    return queryset.order_by("-created_at", "-notification_id")
