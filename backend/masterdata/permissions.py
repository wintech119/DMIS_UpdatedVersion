from rest_framework.permissions import BasePermission

from api.rbac import resolve_roles_and_permissions


# Permission constants
PERM_MASTERDATA_VIEW = "masterdata.view"
PERM_MASTERDATA_CREATE = "masterdata.create"
PERM_MASTERDATA_EDIT = "masterdata.edit"
PERM_MASTERDATA_INACTIVATE = "masterdata.inactivate"


class MasterDataPermission(BasePermission):
    """
    Permission class for master data endpoints.

    Reads ``required_permission`` from the view function.  Supports
    method-specific mappings:
    ``required_permission = {"GET": "masterdata.view", "POST": "masterdata.create"}``
    """

    message = "Forbidden."

    def has_permission(self, request, view) -> bool:
        required = getattr(view, "required_permission", None)
        if required is None:
            view_cls = getattr(view, "view_class", None) or getattr(view, "cls", None)
            if view_cls is not None:
                required = getattr(view_cls, "required_permission", None)
        if not required:
            return False

        if isinstance(required, dict):
            required = required.get(request.method) or required.get("*")
            if not required:
                return False

        user = request.user
        if not getattr(user, "is_authenticated", False):
            return False

        _, permissions = resolve_roles_and_permissions(request, user)
        if isinstance(required, (list, set, tuple)):
            return any(perm in permissions for perm in required)
        return required in permissions
