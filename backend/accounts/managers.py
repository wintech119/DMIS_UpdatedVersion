from __future__ import annotations

from typing import Any

from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.hashers import make_password
from django.core.exceptions import ImproperlyConfigured
from django.db import DatabaseError, IntegrityError, connection, transaction

from masterdata.services.data_access import check_warehouse_managed_by_tenant
from masterdata.services.iam_data_access import (
    UserCreateRecordError,
    UserPrimaryTenantMembershipError,
    create_user_with_primary_tenant,
)


def _actor_label(actor_id: Any) -> str:
    return str(actor_id or "system")[:20]


def _assigned_by_value(actor_id: Any) -> int | None:
    try:
        return int(actor_id)
    except (TypeError, ValueError):
        return None


def _password_algorithm_label(password_hash: str) -> str:
    algorithm = str(password_hash or "").split("$", 1)[0].strip()
    return (algorithm or "django")[:20]


class DmisUserManager(BaseUserManager):
    use_in_migrations = True

    def _resolve_tenant_id(self, extra_fields: dict[str, Any]) -> int:
        raw_tenant_id = extra_fields.pop("tenant_id", None)
        raw_tenant_code = extra_fields.pop("tenant_code", None)

        if raw_tenant_id not in (None, ""):
            try:
                tenant_id = int(raw_tenant_id)
            except (TypeError, ValueError) as exc:
                raise ImproperlyConfigured("tenant_id must be a positive integer.") from exc
            if tenant_id <= 0:
                raise ImproperlyConfigured("tenant_id must be a positive integer.")
            if not self._active_tenant_exists(tenant_id):
                raise ImproperlyConfigured(
                    "tenant_id does not resolve to an active tenant."
                )
            return tenant_id

        tenant_code = str(raw_tenant_code or "").strip().upper()
        if not tenant_code:
            raise ImproperlyConfigured("DmisUser creation requires tenant_id or tenant_code.")

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT tenant_id
                FROM tenant
                WHERE UPPER(COALESCE(tenant_code, '')) = %s
                  AND COALESCE(status_code, 'A') = 'A'
                LIMIT 1
                """,
                [tenant_code],
            )
            row = cursor.fetchone()

        if not row:
            raise ImproperlyConfigured("tenant_code does not resolve to an active tenant.")
        return int(row[0])

    def _active_tenant_exists(self, tenant_id: int) -> bool:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT 1
                FROM tenant
                WHERE tenant_id = %s
                  AND COALESCE(status_code, 'A') = 'A'
                LIMIT 1
                """,
                [tenant_id],
            )
            return cursor.fetchone() is not None

    def _validate_assigned_warehouse_tenant(
        self,
        tenant_id: int,
        raw_warehouse_id: Any,
    ) -> int | None:
        if raw_warehouse_id in (None, ""):
            return None
        try:
            warehouse_id = int(raw_warehouse_id)
        except (TypeError, ValueError) as exc:
            raise ImproperlyConfigured(
                "assigned_warehouse_id must be a positive integer."
            ) from exc
        if warehouse_id <= 0:
            raise ImproperlyConfigured(
                "assigned_warehouse_id must be a positive integer."
            )

        is_managed_by_tenant, warnings = check_warehouse_managed_by_tenant(
            warehouse_id,
            tenant_id,
        )
        if warnings:
            is_managed_by_tenant = self._warehouse_managed_by_tenant_direct(
                warehouse_id,
                tenant_id,
            )
        if not is_managed_by_tenant:
            raise ImproperlyConfigured(
                "assigned_warehouse_id does not resolve to an active warehouse "
                "managed by the selected tenant."
            )
        return warehouse_id

    def _warehouse_managed_by_tenant_direct(
        self,
        warehouse_id: int,
        tenant_id: int,
    ) -> bool:
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT 1
                    FROM warehouse
                    WHERE warehouse_id = %s
                      AND tenant_id = %s
                      AND status_code = %s
                    LIMIT 1
                    """,
                    [warehouse_id, tenant_id, "A"],
                )
                return cursor.fetchone() is not None
        except DatabaseError as exc:
            raise ImproperlyConfigured(
                "assigned_warehouse_id could not be validated."
            ) from exc

    def _record_data(
        self,
        *,
        username: str,
        email: str,
        password_hash: str,
        tenant_id: int,
        extra_fields: dict[str, Any],
    ) -> dict[str, Any]:
        first_name = str(extra_fields.pop("first_name", "") or "").strip()
        last_name = str(extra_fields.pop("last_name", "") or "").strip()
        full_name = str(extra_fields.pop("full_name", "") or "").strip()
        user_name = str(extra_fields.pop("user_name", username) or username).strip()
        if not user_name:
            user_name = username
        if not full_name:
            full_name = " ".join(part for part in (first_name, last_name) if part) or username

        record_data: dict[str, Any] = {
            "username": username,
            "user_name": user_name[:20],
            "email": email,
            "password_hash": password_hash,
            "first_name": first_name,
            "last_name": last_name,
            "full_name": full_name,
            "is_active": bool(extra_fields.pop("is_active", True)),
            "status_code": str(extra_fields.pop("status_code", "A") or "A").strip().upper(),
            "timezone": str(extra_fields.pop("timezone", "America/Jamaica") or "America/Jamaica").strip(),
            "language": str(extra_fields.pop("language", "en") or "en").strip(),
        }

        if "assigned_warehouse_id" in extra_fields:
            assigned_warehouse_id = self._validate_assigned_warehouse_tenant(
                tenant_id,
                extra_fields.pop("assigned_warehouse_id"),
            )
            record_data["assigned_warehouse_id"] = assigned_warehouse_id

        optional_fields = ("agency_id", "phone")
        for field_name in optional_fields:
            if field_name in extra_fields:
                record_data[field_name] = extra_fields.pop(field_name)

        return record_data

    def create_user(self, username, email, password=None, **extra_fields):
        username = str(username or "").strip()
        if not username:
            raise ValueError("The username must be set.")

        email = self.normalize_email(email or "")
        if not email:
            raise ValueError("The email must be set.")

        working_fields = dict(extra_fields)
        tenant_id = self._resolve_tenant_id(working_fields)
        actor_id = working_fields.pop("actor_id", "system")
        password_hash = make_password(password)
        record_data = self._record_data(
            username=username,
            email=email,
            password_hash=password_hash,
            tenant_id=tenant_id,
            extra_fields=working_fields,
        )

        try:
            with transaction.atomic():
                user_id, _warnings = create_user_with_primary_tenant(
                    tenant_id=tenant_id,
                    record_data=record_data,
                    actor_id=actor_id,
                )
                user = self.get(pk=user_id)
                user.password = password_hash
                user.password_algo = _password_algorithm_label(password_hash)
                user.save(update_fields=["password", "password_algo"])
        except UserCreateRecordError as exc:
            raise IntegrityError("Failed to create DMIS user row.") from exc
        except UserPrimaryTenantMembershipError as exc:
            raise IntegrityError("Failed to create primary tenant membership.") from exc

        return user

    def create_superuser(self, username, email, password=None, **extra_fields):
        working_fields = dict(extra_fields)
        working_fields["is_active"] = True
        actor_id = working_fields.get("actor_id", "system")

        with transaction.atomic():
            user = self.create_user(username, email, password, **working_fields)
            if not bool(user.is_active):
                user.is_active = True
                user.save(update_fields=["is_active"])
            self._assign_system_administrator_role(user.user_id, actor_id)
            user.__dict__.pop("is_staff", None)
            return user

    def _assign_system_administrator_role(self, user_id: int, actor_id: Any) -> None:
        actor_label = _actor_label(actor_id)
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id
                FROM role
                WHERE UPPER(code) = %s
                LIMIT 1
                """,
                ["SYSTEM_ADMINISTRATOR"],
            )
            row = cursor.fetchone()
            if not row:
                raise IntegrityError("SYSTEM_ADMINISTRATOR role does not exist.")

            cursor.execute(
                """
                INSERT INTO user_role (
                    user_id,
                    role_id,
                    assigned_by,
                    create_by_id,
                    create_dtime,
                    update_by_id,
                    update_dtime,
                    version_nbr
                )
                VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP, %s, CURRENT_TIMESTAMP, 1)
                ON CONFLICT (user_id, role_id) DO NOTHING
                """,
                [
                    int(user_id),
                    int(row[0]),
                    _assigned_by_value(actor_id),
                    actor_label,
                    actor_label,
                ],
            )
