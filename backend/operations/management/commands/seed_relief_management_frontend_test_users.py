from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connection, transaction
from django.utils import timezone

from api.tenant_membership_locks import lock_primary_tenant_membership
from operations.relief_test_data import (
    TemporaryFrontendUserSpec,
    default_frontend_test_agency_name,
    default_frontend_test_warehouse_name,
    local_auth_harness_usernames,
    temporary_frontend_user_specs,
    temporary_local_harness_default_user,
)

_ODPEM_NATIONAL_TENANT_TYPES = {"NEOC", "NATIONAL", "NATIONAL_LEVEL"}


class Command(BaseCommand):
    help = (
        "Seed temporary local-harness frontend test users, including ODPEM national logistics personas "
        "and a target-tenant requester profile for Relief Management. Dry-run by default."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--tenant-id", type=int, default=None, help="Existing target tenant ID.")
        parser.add_argument("--tenant-code", type=str, default="JRC", help="Existing target tenant code. Defaults to JRC.")
        parser.add_argument("--national-tenant-id", type=int, default=None, help="Existing ODPEM national tenant ID for the local system-admin and ODPEM logistics profiles.")
        parser.add_argument(
            "--national-tenant-code",
            type=str,
            default=None,
            help="Existing ODPEM national tenant code for the local system-admin and ODPEM logistics profiles. Auto-resolves from ODPEM_TENANT_ID when omitted.",
        )
        parser.add_argument("--agency-id", type=int, default=None, help="Existing beneficiary agency ID.")
        parser.add_argument(
            "--agency-name",
            type=str,
            default=None,
            help="Existing beneficiary agency name. Defaults to 'S07 TEST DISTRIBUTOR AGENCY - <TENANT_CODE>'.",
        )
        parser.add_argument("--warehouse-id", type=int, default=None, help="Existing warehouse ID.")
        parser.add_argument(
            "--warehouse-name",
            type=str,
            default=None,
            help="Existing warehouse name. Defaults to 'S07 TEST MAIN HUB - <TENANT_CODE>'.",
        )
        parser.add_argument("--actor", type=str, default="SYSTEM", help="Actor user ID for audit columns.")
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Persist changes. Without this flag, the command only previews the plan.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        actor_id = str(options.get("actor") or "SYSTEM").strip() or "SYSTEM"
        actor_user_id = self._safe_int(actor_id)
        apply_changes = bool(options.get("apply"))

        tenant = self._resolve_tenant(options.get("tenant_id"), options.get("tenant_code"))
        national_tenant = self._resolve_national_tenant(
            options.get("national_tenant_id"),
            options.get("national_tenant_code"),
        )
        agency_name = str(options.get("agency_name") or "").strip() or default_frontend_test_agency_name(
            tenant["tenant_code"]
        )
        warehouse_name = str(options.get("warehouse_name") or "").strip() or default_frontend_test_warehouse_name(
            tenant["tenant_code"]
        )
        agency = self._resolve_agency(options.get("agency_id"), agency_name=agency_name)
        warehouse = self._resolve_warehouse(options.get("warehouse_id"), warehouse_name=warehouse_name)

        if agency["warehouse_id"] != warehouse["warehouse_id"]:
            raise CommandError(
                f"Agency {agency['agency_name']!r} is linked to warehouse {agency['warehouse_id']}, not {warehouse['warehouse_id']}."
            )
        if warehouse["tenant_id"] != tenant["tenant_id"]:
            raise CommandError(
                f"Warehouse {warehouse['warehouse_name']!r} belongs to tenant {warehouse['tenant_id']}, not {tenant['tenant_id']}."
            )

        profiles = self._build_profiles(tenant["tenant_code"], tenant["tenant_name"])
        resolved_roles = {profile.role_code: self._resolve_role(profile.role_code) for profile in profiles}
        recommended_usernames = local_auth_harness_usernames(tenant["tenant_code"])

        self.stdout.write("Relief Management frontend test-user seed:")
        self.stdout.write(f"- target tenant: {tenant['tenant_id']} ({tenant['tenant_code']}) {tenant['tenant_name']}")
        self.stdout.write(
            f"- national tenant: {national_tenant['tenant_id']} ({national_tenant['tenant_code']}) {national_tenant['tenant_name']}"
        )
        self.stdout.write(f"- warehouse: {warehouse['warehouse_id']} {warehouse['warehouse_name']}")
        self.stdout.write(f"- agency: {agency['agency_id']} {agency['agency_name']}")
        self.stdout.write(f"- users planned: {len(profiles)}")
        for profile in profiles:
            profile_tenant = national_tenant if profile.tenant_scope == "national" else tenant
            self.stdout.write(
                f"  - {profile.username} role={profile.role_code} access={profile.access_level} tenant={profile_tenant['tenant_code']}"
            )
        self.stdout.write(f"- recommended DEV_AUTH_USER_ID: {temporary_local_harness_default_user().username}")
        self.stdout.write(f"- recommended LOCAL_AUTH_HARNESS_USERNAMES: {','.join(recommended_usernames)}")

        if not apply_changes:
            self.stdout.write(self.style.WARNING("Dry-run only. Re-run with --apply to persist changes."))
            return

        created_users = 0
        reused_users = 0
        membership_changes = 0
        role_changes = 0
        with transaction.atomic():
            for profile in profiles:
                profile_tenant = national_tenant if profile.tenant_scope == "national" else tenant
                user_id, created = self._ensure_user(
                    profile=profile,
                    tenant_name=profile_tenant["tenant_name"],
                    agency_id=agency["agency_id"] if profile.bind_to_agency else None,
                    warehouse_id=warehouse["warehouse_id"] if profile.bind_to_warehouse else None,
                )
                created_users += int(created)
                reused_users += int(not created)
                membership_changes += int(
                    self._ensure_tenant_membership(
                        user_id=user_id,
                        tenant_id=profile_tenant["tenant_id"],
                        access_level=profile.access_level,
                        actor_id=actor_id,
                        actor_user_id=actor_user_id,
                    )
                )
                role_changes += int(
                    self._ensure_user_role(
                        user_id=user_id,
                        role_id=resolved_roles[profile.role_code]["id"],
                        actor_id=actor_id,
                        actor_user_id=actor_user_id,
                    )
                )

        self.stdout.write(self.style.SUCCESS("Temporary Relief Management frontend users are ready."))
        self.stdout.write(f"- users created: {created_users}")
        self.stdout.write(f"- users reused: {reused_users}")
        self.stdout.write(f"- tenant memberships inserted/updated: {membership_changes}")
        self.stdout.write(f"- role assignments inserted: {role_changes}")

    def _build_profiles(self, tenant_code: str, _tenant_name: str) -> list[TemporaryFrontendUserSpec]:
        return [
            temporary_local_harness_default_user(),
            *list(temporary_frontend_user_specs(tenant_code)),
        ]

    def _resolve_tenant(self, tenant_id: Any, tenant_code: Any) -> dict[str, Any]:
        parsed_tenant_id = self._safe_int(tenant_id)
        normalized_code = str(tenant_code or "").strip().upper()
        try:
            with connection.cursor() as cursor:
                if parsed_tenant_id is not None:
                    cursor.execute(
                        """
                        SELECT tenant_id, tenant_code, tenant_name
                        FROM tenant
                        WHERE tenant_id = %s AND COALESCE(status_code, 'A') = 'A'
                        LIMIT 1
                        """,
                        [parsed_tenant_id],
                    )
                else:
                    cursor.execute(
                        """
                        SELECT tenant_id, tenant_code, tenant_name
                        FROM tenant
                        WHERE UPPER(COALESCE(tenant_code, '')) = %s AND COALESCE(status_code, 'A') = 'A'
                        LIMIT 1
                        """,
                        [normalized_code],
                    )
                row = cursor.fetchone()
        except DatabaseError as exc:
            raise CommandError("Unable to resolve target tenant.") from exc
        if not row:
            raise CommandError("Target tenant does not exist or is inactive.")
        if self._is_odpem_tenant_code(row[1]):
            raise CommandError("Temporary frontend users must target a non-ODPEM tenant.")
        return {"tenant_id": int(row[0]), "tenant_code": str(row[1] or "").strip(), "tenant_name": str(row[2] or "").strip()}

    def _resolve_national_tenant(self, tenant_id: Any, tenant_code: Any) -> dict[str, Any]:
        parsed_tenant_id = self._safe_int(tenant_id)
        normalized_code = str(tenant_code or "").strip().upper()
        configured_tenant_id = self._safe_int(getattr(settings, "ODPEM_TENANT_ID", None))
        if parsed_tenant_id is None and not normalized_code and configured_tenant_id is not None:
            parsed_tenant_id = configured_tenant_id
        try:
            with connection.cursor() as cursor:
                if parsed_tenant_id is not None:
                    cursor.execute(
                        """
                        SELECT tenant_id, tenant_code, tenant_name, tenant_type
                        FROM tenant
                        WHERE tenant_id = %s AND COALESCE(status_code, 'A') = 'A'
                        LIMIT 1
                        """,
                        [parsed_tenant_id],
                    )
                elif normalized_code:
                    cursor.execute(
                        """
                        SELECT tenant_id, tenant_code, tenant_name, tenant_type
                        FROM tenant
                        WHERE UPPER(COALESCE(tenant_code, '')) = %s AND COALESCE(status_code, 'A') = 'A'
                        LIMIT 1
                        """,
                        [normalized_code],
                    )
                else:
                    cursor.execute(
                        """
                        SELECT tenant_id, tenant_code, tenant_name, tenant_type
                        FROM tenant
                        WHERE
                            COALESCE(status_code, 'A') = 'A'
                            AND UPPER(REPLACE(REPLACE(COALESCE(tenant_code, ''), '-', '_'), ' ', '_')) IN ('ODPEM_NEOC', 'OFFICE_OF_DISASTER_P')
                        ORDER BY
                            CASE
                                WHEN UPPER(REPLACE(REPLACE(COALESCE(tenant_code, ''), '-', '_'), ' ', '_')) = 'ODPEM_NEOC' THEN 0
                                WHEN UPPER(REPLACE(REPLACE(COALESCE(tenant_code, ''), '-', '_'), ' ', '_')) = 'OFFICE_OF_DISASTER_P' THEN 1
                                ELSE 2
                            END,
                            tenant_id
                        LIMIT 2
                        """
                    )
                    rows = cursor.fetchall()
                    if len(rows) > 1:
                        raise CommandError(
                            "Unable to resolve the national/local system-admin tenant due to ambiguous matches."
                        )
                    row = rows[0] if rows else None
                if parsed_tenant_id is not None or normalized_code:
                    row = cursor.fetchone()
        except DatabaseError as exc:
            raise CommandError("Unable to resolve the national/local system-admin tenant.") from exc

        if not row:
            raise CommandError("National/local system-admin tenant does not exist or is inactive.")
        tenant_type = str(row[3] or "").strip().upper()
        if not self._is_odpem_tenant_code(row[1]) or tenant_type not in _ODPEM_NATIONAL_TENANT_TYPES:
            raise CommandError(
                "The national/local system-admin tenant must resolve to an ODPEM national or NEOC tenant."
            )
        return {
            "tenant_id": int(row[0]),
            "tenant_code": str(row[1] or "").strip(),
            "tenant_name": str(row[2] or "").strip(),
        }

    def _resolve_agency(self, agency_id: Any, *, agency_name: str) -> dict[str, Any]:
        parsed_agency_id = self._safe_int(agency_id)
        try:
            with connection.cursor() as cursor:
                if parsed_agency_id is not None:
                    cursor.execute(
                        """
                        SELECT agency_id, agency_name, warehouse_id, agency_type, status_code
                        FROM agency
                        WHERE agency_id = %s
                        LIMIT 1
                        """,
                        [parsed_agency_id],
                    )
                else:
                    cursor.execute(
                        """
                        SELECT agency_id, agency_name, warehouse_id, agency_type, status_code
                        FROM agency
                        WHERE UPPER(COALESCE(agency_name, '')) = %s
                          AND UPPER(COALESCE(status_code, '')) = 'A'
                        LIMIT 1
                        """,
                        [agency_name.upper()],
                    )
                row = cursor.fetchone()
        except DatabaseError as exc:
            raise CommandError("Unable to resolve target agency.") from exc
        if not row:
            raise CommandError("Target agency does not exist.")
        if str(row[4] or "").upper() != "A":
            raise CommandError("Target agency is not active.")
        return {
            "agency_id": int(row[0]),
            "agency_name": str(row[1] or "").strip(),
            "warehouse_id": int(row[2]) if row[2] is not None else None,
            "agency_type": str(row[3] or "").strip(),
        }

    def _resolve_warehouse(self, warehouse_id: Any, *, warehouse_name: str) -> dict[str, Any]:
        parsed_warehouse_id = self._safe_int(warehouse_id)
        try:
            with connection.cursor() as cursor:
                if parsed_warehouse_id is not None:
                    cursor.execute(
                        """
                        SELECT warehouse_id, warehouse_name, tenant_id, status_code
                        FROM warehouse
                        WHERE warehouse_id = %s
                        LIMIT 1
                        """,
                        [parsed_warehouse_id],
                    )
                else:
                    cursor.execute(
                        """
                        SELECT warehouse_id, warehouse_name, tenant_id, status_code
                        FROM warehouse
                        WHERE UPPER(COALESCE(warehouse_name, '')) = %s
                          AND UPPER(COALESCE(status_code, '')) = 'A'
                        LIMIT 1
                        """,
                        [warehouse_name.upper()],
                    )
                row = cursor.fetchone()
        except DatabaseError as exc:
            raise CommandError("Unable to resolve target warehouse.") from exc
        if not row:
            raise CommandError("Target warehouse does not exist.")
        if str(row[3] or "").upper() != "A":
            raise CommandError("Target warehouse is not active.")
        return {
            "warehouse_id": int(row[0]),
            "warehouse_name": str(row[1] or "").strip(),
            "tenant_id": int(row[2]) if row[2] is not None else None,
        }

    def _resolve_role(self, role_code: str) -> dict[str, Any]:
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id, code FROM role WHERE UPPER(code) = %s LIMIT 1",
                    [str(role_code).strip().upper()],
                )
                row = cursor.fetchone()
        except DatabaseError as exc:
            raise CommandError(f"Unable to resolve role {role_code}.") from exc
        if not row:
            raise CommandError(f"Role {role_code} does not exist.")
        return {"id": int(row[0]), "code": str(row[1] or "").strip()}

    def _ensure_user(
        self,
        *,
        profile: TemporaryFrontendUserSpec,
        tenant_name: str,
        agency_id: int | None,
        warehouse_id: int | None,
    ) -> tuple[int, bool]:
        now = timezone.now()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT user_id
                    FROM "user"
                    WHERE username = %s
                    LIMIT 1
                    """,
                    [profile.username],
                )
                row = cursor.fetchone()
                if row is None:
                    cursor.execute(
                        """
                        SELECT user_id
                        FROM "user"
                        WHERE email = %s
                        LIMIT 1
                        """,
                        [profile.email],
                    )
                    row = cursor.fetchone()
                if row:
                    user_id = int(row[0])
                    cursor.execute(
                        """
                        UPDATE "user"
                        SET
                            email = %s,
                            username = %s,
                            user_name = %s,
                            first_name = %s,
                            last_name = %s,
                            full_name = %s,
                            organization = %s,
                            job_title = %s,
                            assigned_warehouse_id = %s,
                            agency_id = %s,
                            is_active = TRUE,
                            status_code = 'A',
                            update_dtime = %s,
                            version_nbr = version_nbr + 1
                        WHERE user_id = %s
                        """,
                        [
                            profile.email,
                            profile.username,
                            profile.user_name,
                            profile.first_name,
                            profile.last_name,
                            profile.full_name,
                            tenant_name,
                            profile.job_title,
                            warehouse_id,
                            agency_id,
                            now,
                            user_id,
                        ],
                    )
                    return user_id, False

                cursor.execute(
                    """
                    INSERT INTO "user" (
                        email,
                        password_hash,
                        first_name,
                        last_name,
                        full_name,
                        is_active,
                        organization,
                        job_title,
                        phone,
                        timezone,
                        language,
                        assigned_warehouse_id,
                        create_dtime,
                        update_dtime,
                        username,
                        password_algo,
                        mfa_enabled,
                        failed_login_count,
                        agency_id,
                        status_code,
                        version_nbr,
                        user_name,
                        login_count
                    )
                    VALUES (%s, %s, %s, %s, %s, TRUE, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE, 0, %s, 'A', 1, %s, 0)
                    RETURNING user_id
                    """,
                    [
                        profile.email,
                        "KEYCLOAK_MANAGED",
                        profile.first_name,
                        profile.last_name,
                        profile.full_name,
                        tenant_name,
                        profile.job_title,
                        None,
                        "America/Jamaica",
                        "en",
                        warehouse_id,
                        now,
                        now,
                        profile.username,
                        "argon2id",
                        agency_id,
                        profile.user_name,
                    ],
                )
                created_row = cursor.fetchone()
        except DatabaseError as exc:
            raise CommandError(f"Unable to create or update user {profile.username}.") from exc
        return int(created_row[0]), True

    def _ensure_tenant_membership(
        self,
        *,
        user_id: int,
        tenant_id: int,
        access_level: str,
        actor_id: str,
        actor_user_id: int | None,
    ) -> bool:
        now = timezone.now()
        try:
            with connection.cursor() as cursor:
                lock_primary_tenant_membership(cursor, user_id=user_id)
                cursor.execute(
                    """
                    UPDATE tenant_user
                    SET is_primary_tenant = FALSE
                    WHERE user_id = %s AND tenant_id <> %s AND COALESCE(status_code, 'A') = 'A'
                    """,
                    [user_id, tenant_id],
                )
                cursor.execute(
                    """
                    SELECT 1
                    FROM tenant_user
                    WHERE tenant_id = %s AND user_id = %s
                    LIMIT 1
                    """,
                    [tenant_id, user_id],
                )
                exists = cursor.fetchone() is not None
                if exists:
                    cursor.execute(
                        """
                        UPDATE tenant_user
                        SET
                            is_primary_tenant = TRUE,
                            access_level = %s,
                            assigned_at = %s,
                            assigned_by = %s,
                            status_code = 'A'
                        WHERE tenant_id = %s AND user_id = %s
                        """,
                        [access_level, now, actor_user_id, tenant_id, user_id],
                    )
                    return True
                cursor.execute(
                    """
                    INSERT INTO tenant_user (
                        tenant_id,
                        user_id,
                        is_primary_tenant,
                        access_level,
                        assigned_at,
                        assigned_by,
                        status_code,
                        create_by_id,
                        create_dtime
                    )
                    VALUES (%s, %s, TRUE, %s, %s, %s, 'A', %s, %s)
                    """,
                    [tenant_id, user_id, access_level, now, actor_user_id, actor_id, now],
                )
        except DatabaseError as exc:
            raise CommandError(f"Unable to upsert tenant membership for user {user_id}.") from exc
        return True

    def _ensure_user_role(
        self,
        *,
        user_id: int,
        role_id: int,
        actor_id: str,
        actor_user_id: int | None,
    ) -> bool:
        now = timezone.now()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT 1
                    FROM user_role
                    WHERE user_id = %s AND role_id = %s
                    LIMIT 1
                    """,
                    [user_id, role_id],
                )
                exists = cursor.fetchone() is not None
                if exists:
                    return False
                cursor.execute(
                    """
                    INSERT INTO user_role (
                        user_id,
                        role_id,
                        assigned_at,
                        assigned_by,
                        create_by_id,
                        create_dtime,
                        update_by_id,
                        update_dtime,
                        version_nbr
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 1)
                    """,
                    [user_id, role_id, now, actor_user_id, actor_id, now, actor_id, now],
                )
        except DatabaseError as exc:
            raise CommandError(f"Unable to assign role {role_id} to user {user_id}.") from exc
        return True

    def _safe_int(self, value: Any) -> int | None:
        try:
            parsed = int(str(value).strip())
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    def _is_odpem_tenant_code(self, value: object) -> bool:
        normalized = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
        while "__" in normalized:
            normalized = normalized.replace("__", "_")
        return bool(normalized) and (normalized.startswith("ODPEM") or normalized == "OFFICE_OF_DISASTER_P")
