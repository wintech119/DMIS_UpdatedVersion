from rest_framework.permissions import BasePermission

from api.rbac import REQUIRED_PERMISSION, resolve_roles_and_permissions


class NeedsListPreviewPermission(BasePermission):
    message = "Forbidden."

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not getattr(user, "is_authenticated", False):
            return False

        _, permissions = resolve_roles_and_permissions(request, user)
        return REQUIRED_PERMISSION in permissions
