from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from api.authentication import LegacyCompatAuthentication
from api.permissions import NeedsListPreviewPermission
from api.rbac import resolve_roles_and_permissions


@api_view(["GET"])
def health(request):
    return Response({"status": "ok"})


@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([NeedsListPreviewPermission])
def whoami(request):
    roles, permissions = resolve_roles_and_permissions(request, request.user)
    return Response(
        {
            "user_id": request.user.user_id,
            "username": request.user.username,
            "roles": roles,
            "permissions": sorted(permissions),
        }
    )
