from rest_framework.permissions import BasePermission

from api.rbac import resolve_roles_and_permissions


class OperationsPermission(BasePermission):
    message = "Forbidden."

    def has_permission(self, request, view) -> bool:
        required = getattr(view, "required_permission", None)
        if required is None:
            view_cls = (
                getattr(view, "view_class", None)
                or getattr(view, "cls", None)
                or getattr(view, "__class__", None)
            )
            if view_cls is not None:
                required = getattr(view_cls, "required_permission", None)
        if required is None:
            resolver_func = getattr(getattr(request, "resolver_match", None), "func", None)
            if resolver_func is not None:
                required = getattr(resolver_func, "required_permission", None)
                if required is None:
                    resolver_cls = (
                        getattr(resolver_func, "view_class", None)
                        or getattr(resolver_func, "cls", None)
                    )
                    if resolver_cls is not None:
                        required = getattr(resolver_cls, "required_permission", None)
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
        if isinstance(required, (list, tuple, set)):
            return any(perm in permissions for perm in required)
        return required in permissions

