from rest_framework.permissions import BasePermission

from api.rbac import REQUIRED_PERMISSION, resolve_roles_and_permissions


def resolve_view_required_permission(request, view):
    required = getattr(view, "required_permission", None)
    if required is None:
        view_cls = getattr(view, "view_class", None) or getattr(view, "cls", None)
        if view_cls is not None:
            required = getattr(view_cls, "required_permission", None)
    if isinstance(required, dict):
        return required.get(request.method) or required.get("*")
    return required


def user_has_required_permission(request, user, required) -> bool:
    if not required:
        return False
    if not getattr(user, "is_authenticated", False):
        return False

    _, permissions = resolve_roles_and_permissions(request, user)
    if isinstance(required, (list, set, tuple)):
        return any(perm in permissions for perm in required)
    return required in permissions


class NeedsListPreviewPermission(BasePermission):
    message = "Forbidden."

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not getattr(user, "is_authenticated", False):
            return False
        return user_has_required_permission(request, user, REQUIRED_PERMISSION)


class NeedsListPermission(BasePermission):
    message = "Forbidden."

    def has_permission(self, request, view) -> bool:
        required = resolve_view_required_permission(request, view)
        return user_has_required_permission(request, request.user, required)


class ProcurementPermission(BasePermission):
    """Permission class for procurement endpoints.

    Works identically to NeedsListPermission - checks ``required_permission``
    attribute on the view function against the resolved RBAC permissions.
    Supports method-specific mappings via:
    ``required_permission = {"GET": "...view", "POST": "...create"}``
    """

    message = "Forbidden."

    def has_permission(self, request, view) -> bool:
        required = resolve_view_required_permission(request, view)
        return user_has_required_permission(request, request.user, required)
