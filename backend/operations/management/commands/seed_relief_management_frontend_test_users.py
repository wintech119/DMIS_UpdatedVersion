from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connection, transaction
from django.utils import timezone

from operations.relief_test_data import (
    default_frontend_test_agency_name,
    default_frontend_test_warehouse_name,
)


@dataclass(frozen=True)
class UserSeedProfile:
    username: str
    email: str
    user_name: str
    first_name: str
    last_name: str
    full_name: str
    job_title: str
    role_code: str
    access_level: str


class Command(BaseCommand):
    help = (
        "Seed temporary non-ODPEM frontend test users, tenant memberships, and DB RBAC role assignments "
        "for Relief Management. Dry-run by default."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--tenant-id", type=int, default=None, help="Existing target tenant ID.")
        parser.add_argument("--tenant-code", type=str, default="JRC", help="Existing target tenant code. Defaults to JRC.")
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

        self.stdout.write("Relief Management frontend test-user seed:")
        self.stdout.write(f"- target tenant: {tenant['tenant_id']} ({tenant['tenant_code']}) {tenant['tenant_name']}")
        self.stdout.write(f"- warehouse: {warehouse['warehouse_id']} {warehouse['warehouse_name']}")
        self.stdout.write(f"- agency: {agency['agency_id']} {agency['agency_name']}")
        self.stdout.write(f"- users planned: {len(profiles)}")
        for profile in profiles:
            self.stdout.write(f"  - {profile.username} role={profile.role_code} access={profile.access_level}")

        if not apply_changes:
            self.stdout.write(self.style.WARNING("Dry-run only. Re-run with --apply to persist changes."))
            return

        created_users = 0
        reused_users = 0
        membership_changes = 0
        role_changes = 0
        with transaction.atomic():
            for profile in profiles:
                user_id, created = self._ensure_user(
                    profile=profile,
                    tenant_name=tenant["tenant_name"],
                    agency_id=agency["agency_id"],
                    warehouse_id=warehouse["warehouse_id"],
                )
                created_users += int(created)
                reused_users += int(not created)
                membership_changes += int(
                    self._ensure_tenant_membership(
                        user_id=user_id,
                        tenant_id=tenant["tenant_id"],
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

    def _build_profiles(self, tenant_code: str, tenant_name: str) -> list[UserSeedProfile]:
        normalized = tenant_code.lower().replace("-", "_").replace(" ", "_")
        display_prefix = tenant_code.upper().replace("-", " ")
        return [
            UserSeedProfile(
                username=f"relief_{normalized}_requester_tst",
                email=f"relief.{normalized}.requester+tst@odpem.gov.jm",
                user_name=f"{display_prefix}_REQUESTER",
                first_name=tenant_code.upper(),
                last_name="Requester",
                full_name=f"{tenant_name} Requester Test",
                job_title="Relief Requester Test",
                role_code="AGENCY_DISTRIBUTOR",
                access_level="FULL",
            ),
            UserSeedProfile(
                username=f"relief_{normalized}_receiver_tst",
                email=f"relief.{normalized}.receiver+tst@odpem.gov.jm",
                user_name=f"{display_prefix}_RECEIVER",
                first_name=tenant_code.upper(),
                last_name="Receiver",
                full_name=f"{tenant_name} Receiver Test",
                job_title="Relief Receiver Test",
                role_code="AGENCY_DISTRIBUTOR",
                access_level="FULL",
            ),
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
        profile: UserSeedProfile,
        tenant_name: str,
        agency_id: int,
        warehouse_id: int,
    ) -> tuple[int, bool]:
        now = timezone.now()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT user_id
                    FROM "user"
                    WHERE username = %s OR email = %s
                    LIMIT 1
                    """,
                    [profile.username, profile.email],
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
                            status_code = 'A',
                            create_by_id = %s,
                            create_dtime = %s
                        WHERE tenant_id = %s AND user_id = %s
                        """,
                        [access_level, now, actor_user_id, actor_id, now, tenant_id, user_id],
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
