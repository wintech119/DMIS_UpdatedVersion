from rest_framework.permissions import BasePermission

from api.rbac import (
    PERM_MASTERDATA_ADVANCED_CREATE,
    PERM_MASTERDATA_ADVANCED_EDIT,
    PERM_MASTERDATA_ADVANCED_INACTIVATE,
    PERM_MASTERDATA_ADVANCED_VIEW,
    resolve_roles_and_permissions,
)


# Permission constants
PERM_MASTERDATA_VIEW = "masterdata.view"
PERM_MASTERDATA_CREATE = "masterdata.create"
PERM_MASTERDATA_EDIT = "masterdata.edit"
PERM_MASTERDATA_INACTIVATE = "masterdata.inactivate"

ADVANCED_TABLE_KEYS = {"user", "role", "permission", "tenant", "tenant_types"}
ADVANCED_REQUIRED_PERMISSION = {
    "GET": PERM_MASTERDATA_ADVANCED_VIEW,
    "POST": PERM_MASTERDATA_ADVANCED_CREATE,
    "PUT": PERM_MASTERDATA_ADVANCED_EDIT,
    "PATCH": PERM_MASTERDATA_ADVANCED_EDIT,
    "DELETE": PERM_MASTERDATA_ADVANCED_INACTIVATE,
}
STANDARD_TO_ADVANCED_PERMISSION = {
    PERM_MASTERDATA_VIEW: PERM_MASTERDATA_ADVANCED_VIEW,
    PERM_MASTERDATA_CREATE: PERM_MASTERDATA_ADVANCED_CREATE,
    PERM_MASTERDATA_EDIT: PERM_MASTERDATA_ADVANCED_EDIT,
    PERM_MASTERDATA_INACTIVATE: PERM_MASTERDATA_ADVANCED_INACTIVATE,
}


def _table_key_from_request(request, view) -> str:
    parser_context = getattr(request, "parser_context", None) or {}
    kwargs = parser_context.get("kwargs") or {}
    table_key = kwargs.get("table_key")
    if table_key:
        return str(table_key)
    view_kwargs = getattr(view, "kwargs", {}) or {}
    table_key = view_kwargs.get("table_key")
    if table_key:
        return str(table_key)
    args = parser_context.get("args") or getattr(view, "args", ()) or ()
    if args:
        return str(args[0])
    return ""


def _advanced_required_permission(required, method: str):
    if isinstance(required, str):
        return STANDARD_TO_ADVANCED_PERMISSION.get(required, required)
    if isinstance(required, (list, set, tuple)):
        converted = [
            STANDARD_TO_ADVANCED_PERMISSION.get(perm, perm)
            for perm in required
        ]
        return type(required)(converted)
    return ADVANCED_REQUIRED_PERMISSION.get(method, required)


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

        table_key = _table_key_from_request(request, view)
        if table_key in ADVANCED_TABLE_KEYS:
            required = _advanced_required_permission(required, request.method)

        user = request.user
        if not getattr(user, "is_authenticated", False):
            return False

        _, permissions = resolve_roles_and_permissions(request, user)
        if isinstance(required, (list, set, tuple)):
            return any(perm in permissions for perm in required)
        return required in permissions
