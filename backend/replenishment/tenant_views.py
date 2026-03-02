from __future__ import annotations

from typing import Any

from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from api.authentication import LegacyCompatAuthentication
from api.permissions import NeedsListPermission
from api.rbac import (
    PERM_TENANT_APPROVAL_POLICY_MANAGE,
    PERM_TENANT_APPROVAL_POLICY_VIEW,
    PERM_TENANT_FEATURE_MANAGE,
    PERM_TENANT_FEATURE_VIEW,
    resolve_roles_and_permissions,
)
from api.tenancy import can_access_tenant, resolve_tenant_context, tenant_context_to_dict
from replenishment.services import tenant_policy
from replenishment.services.tenant_policy import TenantPolicyError


def _actor_id(request) -> str | None:
    return getattr(request.user, "user_id", None) or getattr(request.user, "username", None)


def _tenant_scope_error(request, tenant_id: int, *, write: bool) -> Response | None:
    _, permissions = resolve_roles_and_permissions(request, request.user)
    context = resolve_tenant_context(request, request.user, permissions)
    if can_access_tenant(context, tenant_id, write=write):
        return None
    return Response(
        {
            "errors": {"tenant_scope": "Access denied for tenant scope."},
            "tenant_context": tenant_context_to_dict(context),
            "target_tenant_id": tenant_id,
        },
        status=403,
    )


@api_view(["GET", "PUT"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPermission])
def tenant_approval_policy_detail(request, tenant_id: int, workflow_type: str):
    scope_error = _tenant_scope_error(
        request,
        tenant_id,
        write=request.method == "PUT",
    )
    if scope_error:
        return scope_error

    if request.method == "GET":
        try:
            active = tenant_policy.get_active_approval_policy(tenant_id, workflow_type)
            draft = tenant_policy.get_draft_approval_policy(tenant_id, workflow_type)
        except TenantPolicyError as exc:
            return Response({"errors": {"workflow_type": str(exc)}}, status=400)
        workflow = str(workflow_type or "").strip().upper()
        return Response(
            {
                "tenant_id": tenant_id,
                "workflow_type": workflow,
                "active_policy": active,
                "draft_policy": draft,
            }
        )

    payload = (request.data or {}).get("policy")
    if payload is None:
        payload = request.data or {}
    try:
        result = tenant_policy.save_approval_policy_draft(
            tenant_id=tenant_id,
            workflow_type=workflow_type,
            payload=payload,
            actor=_actor_id(request),
        )
    except TenantPolicyError as exc:
        return Response({"errors": {"policy": str(exc)}}, status=400)

    return Response({"tenant_id": tenant_id, "workflow_type": workflow_type, "draft_policy": result})


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPermission])
def tenant_approval_policy_publish(request, tenant_id: int, workflow_type: str):
    scope_error = _tenant_scope_error(request, tenant_id, write=True)
    if scope_error:
        return scope_error

    try:
        result = tenant_policy.publish_approval_policy(
            tenant_id=tenant_id,
            workflow_type=workflow_type,
            actor=_actor_id(request),
        )
    except TenantPolicyError as exc:
        return Response({"errors": {"policy": str(exc)}}, status=400)

    return Response(
        {
            "tenant_id": tenant_id,
            "workflow_type": workflow_type,
            "active_policy": result,
            "published": True,
        }
    )


@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPermission])
def tenant_feature_list(request, tenant_id: int):
    scope_error = _tenant_scope_error(request, tenant_id, write=False)
    if scope_error:
        return scope_error

    features = tenant_policy.list_tenant_features(tenant_id)
    return Response({"tenant_id": tenant_id, "features": features, "count": len(features)})


@api_view(["GET", "PUT"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPermission])
def tenant_feature_detail(request, tenant_id: int, feature_key: str):
    scope_error = _tenant_scope_error(
        request,
        tenant_id,
        write=request.method == "PUT",
    )
    if scope_error:
        return scope_error

    normalized_feature_key = str(feature_key or "").strip().lower().replace(" ", "_")
    if not normalized_feature_key:
        return Response({"errors": {"feature_key": "feature_key is required."}}, status=400)

    if request.method == "GET":
        features = tenant_policy.list_tenant_features(tenant_id)
        match = next(
            (feature for feature in features if feature.get("feature_key") == normalized_feature_key),
            None,
        )
        if match is None:
            return Response(
                {
                    "tenant_id": tenant_id,
                    "feature": {
                        "feature_key": normalized_feature_key,
                        "enabled": False,
                        "settings": {},
                    },
                }
            )
        return Response({"tenant_id": tenant_id, "feature": match})

    body: dict[str, Any] = request.data if isinstance(request.data, dict) else {}
    if "enabled" not in body:
        return Response({"errors": {"enabled": "enabled is required."}}, status=400)
    enabled = bool(body.get("enabled"))
    settings = body.get("settings")
    if settings is not None and not isinstance(settings, dict):
        return Response({"errors": {"settings": "settings must be an object when provided."}}, status=400)

    result = tenant_policy.set_tenant_feature(
        tenant_id=tenant_id,
        feature_key=normalized_feature_key,
        enabled=enabled,
        settings=settings if isinstance(settings, dict) else None,
        actor=_actor_id(request),
    )
    return Response({"tenant_id": tenant_id, "feature": result})


tenant_approval_policy_detail.required_permission = {
    "GET": PERM_TENANT_APPROVAL_POLICY_VIEW,
    "PUT": PERM_TENANT_APPROVAL_POLICY_MANAGE,
}
tenant_approval_policy_publish.required_permission = PERM_TENANT_APPROVAL_POLICY_MANAGE
tenant_feature_list.required_permission = PERM_TENANT_FEATURE_VIEW
tenant_feature_detail.required_permission = {
    "GET": PERM_TENANT_FEATURE_VIEW,
    "PUT": PERM_TENANT_FEATURE_MANAGE,
}

for _tenant_view in (
    tenant_approval_policy_detail,
    tenant_approval_policy_publish,
    tenant_feature_list,
    tenant_feature_detail,
):
    if hasattr(_tenant_view, "cls"):
        _tenant_view.cls.required_permission = _tenant_view.required_permission
