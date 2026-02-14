from django.conf import settings
from django.db import DatabaseError, connection
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from api.authentication import LegacyCompatAuthentication
from api.rbac import resolve_roles_and_permissions


@api_view(["GET"])
def health(request):
    return Response({"status": "ok"})


@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([IsAuthenticated])
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


@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([IsAuthenticated])
def dev_users(request):
    if not (settings.DEBUG and settings.DEV_AUTH_ENABLED):
        return Response({"detail": "Not found."}, status=404)

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    u.user_id,
                    u.username,
                    u.email,
                    r.code,
                    p.resource,
                    p.action
                FROM "user" u
                JOIN user_role ur ON ur.user_id = u.user_id
                JOIN role r ON r.id = ur.role_id
                JOIN role_permission rp ON rp.role_id = r.id
                JOIN permission p ON p.perm_id = rp.perm_id
                WHERE p.resource = 'replenishment.needs_list'
                ORDER BY u.username, u.user_id
                """
            )
            rows = cursor.fetchall()
    except DatabaseError:
        return Response({"users": []})

    users_by_id: dict[str, dict[str, object]] = {}
    for row in rows:
        user_id = str(row[0])
        username = str(row[1] or "").strip()
        if not username:
            continue
        email = row[2]
        role = str(row[3] or "").strip()
        resource = str(row[4] or "").strip()
        action = str(row[5] or "").strip()
        permission = f"{resource}.{action}" if resource and action else ""

        if user_id not in users_by_id:
            users_by_id[user_id] = {
                "user_id": user_id,
                "username": username,
                "email": email,
                "roles": set(),
                "permissions": set(),
            }
        if role:
            users_by_id[user_id]["roles"].add(role)
        if permission:
            users_by_id[user_id]["permissions"].add(permission)

    users = [
        {
            "user_id": user["user_id"],
            "username": user["username"],
            "email": user["email"],
            "roles": sorted(list(user["roles"])),
            "permissions": sorted(list(user["permissions"])),
        }
        for user in sorted(
            users_by_id.values(),
            key=lambda item: str(item["username"]).lower(),
        )
    ]

    return Response({"users": users})
