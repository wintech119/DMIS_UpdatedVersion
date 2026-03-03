from __future__ import annotations

from collections.abc import Mapping

from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from api.authentication import LegacyCompatAuthentication
from api.permissions import NeedsListPermission
from api.rbac import (
    PERM_EVENT_PHASE_WINDOW_MANAGE,
    PERM_EVENT_PHASE_WINDOW_VIEW,
    resolve_roles_and_permissions,
)
from api.tenancy import (
    can_manage_phase_window_config,
    resolve_tenant_context,
    tenant_context_to_dict,
)
from replenishment.services import phase_window_policy
from replenishment.services.phase_window_policy import PhaseWindowPolicyError


def _actor_id(request) -> str | None:
    return getattr(request.user, "user_id", None) or getattr(request.user, "username", None)


def _tenant_context(request):
    _, permissions = resolve_roles_and_permissions(request, request.user)
    return resolve_tenant_context(request, request.user, permissions)


def _manage_scope_error(request) -> Response | None:
    context = _tenant_context(request)
    if can_manage_phase_window_config(context):
        return None
    return Response(
        {
            "errors": {
                "tenant_scope": (
                    "Only ODPEM national tenant and ODPEM-NEOC may configure "
                    "event phase windows."
                )
            },
            "tenant_context": tenant_context_to_dict(context),
        },
        status=403,
    )


def _phase_window_error_status(exc: Exception) -> int:
    message = str(exc or "").lower()
    backend_markers = ("database", "db", "storage", "connection", "timeout", "backend")
    return 500 if any(marker in message for marker in backend_markers) else 400


@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPermission])
def event_phase_window_list(request, event_id: int):
    try:
        windows = phase_window_policy.list_effective_phase_windows(int(event_id))
    except PhaseWindowPolicyError as exc:
        return Response(
            {"errors": {"event_phase_windows": str(exc)}},
            status=_phase_window_error_status(exc),
        )
    context = _tenant_context(request)
    return Response(
        {
            "event_id": int(event_id),
            "phase_windows": windows,
            "manageable_by_active_tenant": can_manage_phase_window_config(context),
        }
    )


@api_view(["PUT"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPermission])
def event_phase_window_detail(request, event_id: int, phase: str):
    scope_error = _manage_scope_error(request)
    if scope_error:
        return scope_error

    body = request.data if isinstance(request.data, Mapping) else {}
    demand_hours = body.get("demand_hours", body.get("demand_window_hours"))
    planning_hours = body.get("planning_hours", body.get("planning_window_hours"))

    if demand_hours is None or planning_hours is None:
        return Response(
            {
                "errors": {
                    "payload": "demand_hours and planning_hours are required."
                }
            },
            status=400,
        )

    try:
        updated = phase_window_policy.set_event_phase_windows(
            event_id=int(event_id),
            phase=phase,
            demand_hours=demand_hours,
            planning_hours=planning_hours,
            actor=_actor_id(request),
        )
    except PhaseWindowPolicyError as exc:
        return Response(
            {"errors": {"event_phase_windows": str(exc)}},
            status=_phase_window_error_status(exc),
        )

    return Response(
        {
            "event_id": int(event_id),
            "phase": updated.get("phase"),
            "windows": updated,
            "updated": True,
        }
    )


event_phase_window_list.required_permission = PERM_EVENT_PHASE_WINDOW_VIEW
event_phase_window_detail.required_permission = PERM_EVENT_PHASE_WINDOW_MANAGE

for _view in (event_phase_window_list, event_phase_window_detail):
    if hasattr(_view, "cls"):
        _view.cls.required_permission = _view.required_permission
