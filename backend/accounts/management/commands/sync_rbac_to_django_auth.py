from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import hashlib
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connection, transaction

from accounts.permissions import bridge_codename
from api.rbac import resolve_roles_and_permissions


DMIS_AUTH_APP_LABEL = "dmis"


@dataclass(frozen=True)
class PermissionSpec:
    resource: str
    action: str
    codename: str
    name: str


@dataclass(frozen=True)
class SyncSummary:
    permissions_created: int
    permissions_updated: int
    permissions_unchanged: int
    permissions_deleted: int
    groups_created: int
    groups_updated: int
    groups_unchanged: int
    groups_deleted: int
    group_permission_mappings: int
    user_group_assignments: int


class Command(BaseCommand):
    help = "Sync DMIS custom RBAC tables into Django auth.Group / auth.Permission. Idempotent."

    def handle(self, *args, **options):
        try:
            with transaction.atomic():
                summary = self._sync()
        except DatabaseError as exc:
            raise CommandError(f"RBAC bridge sync failed: {exc}") from exc

        self.stdout.write(
            "Permissions: "
            f"{summary.permissions_created} created, "
            f"{summary.permissions_updated} updated, "
            f"{summary.permissions_unchanged} unchanged, "
            f"{summary.permissions_deleted} deleted"
        )
        self.stdout.write(
            "Groups: "
            f"{summary.groups_created} created, "
            f"{summary.groups_updated} updated, "
            f"{summary.groups_unchanged} unchanged, "
            f"{summary.groups_deleted} deleted"
        )
        self.stdout.write(
            f"Group permissions: {summary.group_permission_mappings} mappings synced"
        )
        self.stdout.write(
            f"User groups: {summary.user_group_assignments} user-group assignments synced"
        )

    def _sync(self) -> SyncSummary:
        self._validate_required_tables()
        permission_rows, roles_by_id, role_permission_codes, user_role_codes = (
            self._load_custom_rbac()
        )
        permission_parts_by_code = self._build_permission_parts_by_code(permission_rows)

        resolved_codes_by_role = self._resolve_permission_codes_by_role(
            role_permission_codes,
            roles_by_id,
        )
        resolved_codes_by_user = self._resolve_permission_codes_by_user(
            role_permission_codes,
            user_role_codes,
        )
        combo_group_permissions, combo_groups_by_user_id = self._build_combo_groups(
            resolved_codes_by_role,
            resolved_codes_by_user,
            user_role_codes,
            set(roles_by_id.values()),
        )
        desired_specs = self._build_desired_permission_specs(
            permission_parts_by_code,
            resolved_codes_by_role,
            resolved_codes_by_user,
        )
        permission_counts, permissions_by_codename = self._sync_permissions(desired_specs)
        group_counts, groups_by_code = self._sync_groups(
            roles_by_id,
            combo_group_permissions,
        )
        group_mapping_count = self._sync_group_permissions(
            groups_by_code,
            permissions_by_codename,
            resolved_codes_by_role,
            combo_group_permissions,
            permission_parts_by_code,
        )
        self._clear_direct_user_permissions()
        user_group_assignment_count = self._sync_user_groups(
            groups_by_code,
            user_role_codes,
            combo_groups_by_user_id,
        )

        return SyncSummary(
            permissions_created=permission_counts["created"],
            permissions_updated=permission_counts["updated"],
            permissions_unchanged=permission_counts["unchanged"],
            permissions_deleted=permission_counts["deleted"],
            groups_created=group_counts["created"],
            groups_updated=group_counts["updated"],
            groups_unchanged=group_counts["unchanged"],
            groups_deleted=group_counts["deleted"],
            group_permission_mappings=group_mapping_count,
            user_group_assignments=user_group_assignment_count,
        )

    def _validate_required_tables(self) -> None:
        user_model = get_user_model()
        required_tables = {
            "user",
            "role",
            "permission",
            "role_permission",
            "user_role",
            user_model.groups.through._meta.db_table,
            user_model.user_permissions.through._meta.db_table,
        }
        existing_tables = {str(name).strip('"') for name in connection.introspection.table_names()}
        missing = sorted(
            table for table in required_tables if table.strip('"') not in existing_tables
        )
        if missing:
            raise CommandError(
                "Required DMIS RBAC/auth bridge table(s) missing: "
                + ", ".join(missing)
                + ". Apply migrations and the legacy RBAC schema before syncing."
            )

    def _load_custom_rbac(self):
        q = connection.ops.quote_name
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT perm_id, resource, action
                FROM {q("permission")}
                ORDER BY perm_id
                """
            )
            permission_rows = [
                (int(row[0]), self._clean_identifier(row[1], "permission.resource"),
                 self._clean_identifier(row[2], "permission.action"))
                for row in cursor.fetchall()
            ]

            cursor.execute(
                f"""
                SELECT id, code
                FROM {q("role")}
                ORDER BY id
                """
            )
            roles_by_id = {
                int(row[0]): self._clean_identifier(row[1], "role.code")
                for row in cursor.fetchall()
            }

            cursor.execute(
                f"""
                SELECT rp.role_id, p.resource, p.action
                FROM {q("role_permission")} rp
                JOIN {q("permission")} p ON p.perm_id = rp.perm_id
                ORDER BY rp.role_id, p.resource, p.action
                """
            )
            role_permission_codes = defaultdict(set)
            for role_id, resource, action in cursor.fetchall():
                role_code = roles_by_id.get(int(role_id))
                if role_code:
                    role_permission_codes[role_code].add(
                        self._permission_code(resource, action)
                    )

            cursor.execute(
                f"""
                SELECT ur.user_id, r.code
                FROM {q("user_role")} ur
                JOIN {q("role")} r ON r.id = ur.role_id
                ORDER BY ur.user_id, r.code
                """
            )
            user_role_codes = defaultdict(set)
            for user_id, role_code in cursor.fetchall():
                user_role_codes[int(user_id)].add(
                    self._clean_identifier(role_code, "role.code")
                )

        return permission_rows, roles_by_id, role_permission_codes, user_role_codes

    def _resolve_permission_codes_by_role(self, role_permission_codes, roles_by_id):
        resolved = {}
        for role_code in roles_by_id.values():
            request = SimpleNamespace()
            principal = SimpleNamespace(
                user_id=None,
                username=None,
                roles=[role_code],
                permissions=sorted(role_permission_codes.get(role_code, set())),
            )
            _roles, permissions = resolve_roles_and_permissions(request, principal)
            resolved[role_code] = set(permissions)
        return resolved

    def _resolve_permission_codes_by_user(self, role_permission_codes, user_role_codes):
        resolved = {}
        for user_id, role_codes in user_role_codes.items():
            seed_permissions = set()
            for role_code in role_codes:
                seed_permissions.update(role_permission_codes.get(role_code, set()))
            request = SimpleNamespace()
            principal = SimpleNamespace(
                user_id=None,
                username=None,
                roles=sorted(role_codes),
                permissions=sorted(seed_permissions),
            )
            _roles, permissions = resolve_roles_and_permissions(request, principal)
            resolved[user_id] = set(permissions)
        return resolved

    def _build_combo_groups(
        self,
        resolved_codes_by_role,
        resolved_codes_by_user,
        user_role_codes,
        role_codes,
    ):
        combo_group_permissions = {}
        combo_groups_by_user_id = defaultdict(set)
        for user_id, user_permission_codes in sorted(resolved_codes_by_user.items()):
            user_roles = sorted(user_role_codes.get(user_id, set()))
            role_permission_union = set()
            for role_code in user_roles:
                role_permission_union.update(resolved_codes_by_role.get(role_code, set()))
            extra_permissions = set(user_permission_codes) - role_permission_union
            if not extra_permissions:
                continue

            group_name = self._combo_group_name(user_roles)
            if group_name in role_codes:
                raise CommandError(
                    f"Derived bridge group {group_name!r} collides with a DMIS role code."
                )
            previous_permissions = combo_group_permissions.get(group_name)
            if previous_permissions is not None and previous_permissions != extra_permissions:
                raise CommandError(
                    f"Derived bridge group {group_name!r} has inconsistent permissions."
                )
            combo_group_permissions[group_name] = extra_permissions
            combo_groups_by_user_id[user_id].add(group_name)
        return combo_group_permissions, combo_groups_by_user_id

    def _build_desired_permission_specs(
        self,
        permission_parts_by_code,
        resolved_codes_by_role,
        resolved_codes_by_user,
    ):
        desired_codes = set(permission_parts_by_code)
        for permission_codes in resolved_codes_by_role.values():
            desired_codes.update(permission_codes)
        for permission_codes in resolved_codes_by_user.values():
            desired_codes.update(permission_codes)

        specs_by_codename = {}
        codes_by_codename = {}
        for code in sorted(desired_codes):
            resource, action = self._permission_parts_for_code(
                code,
                permission_parts_by_code,
            )
            codename = self._bridge_codename(resource, action, code)
            existing_code = codes_by_codename.get(codename)
            if existing_code and existing_code != code:
                raise CommandError(
                    "Permission codename collision after bridge translation: "
                    f"{existing_code!r} and {code!r} both map to {codename!r}."
                )
            codes_by_codename[codename] = code
            specs_by_codename[codename] = PermissionSpec(
                resource=resource,
                action=action,
                codename=codename,
                name=f"DMIS {resource}.{action}",
            )
        return specs_by_codename

    def _build_permission_parts_by_code(self, permission_rows):
        permission_parts_by_code = {}
        for _perm_id, resource, action in permission_rows:
            code = self._permission_code(resource, action)
            permission_parts = (resource, action)
            existing_parts = permission_parts_by_code.get(code)
            if existing_parts is not None and existing_parts != permission_parts:
                raise CommandError(
                    "Permission rows collapse to the same bridge code with "
                    f"different resource/action pairs: {existing_parts!r} and "
                    f"{permission_parts!r} both map to {code!r}."
                )
            permission_parts_by_code[code] = permission_parts
        return permission_parts_by_code

    def _sync_permissions(self, desired_specs):
        content_types = self._ensure_content_types(desired_specs.values())
        desired_codenames = set(desired_specs)
        existing_qs = Permission.objects.filter(
            content_type__app_label=DMIS_AUTH_APP_LABEL,
        ).select_related("content_type")
        permissions_deleted = existing_qs.exclude(codename__in=desired_codenames).count()
        existing_qs.exclude(codename__in=desired_codenames).delete()

        counts = {
            "created": 0,
            "updated": 0,
            "unchanged": 0,
            "deleted": permissions_deleted,
        }
        permissions_by_codename = {}
        for codename, spec in sorted(desired_specs.items()):
            content_type = content_types[spec.resource]
            permission = Permission.objects.filter(
                content_type__app_label=DMIS_AUTH_APP_LABEL,
                codename=codename,
            ).first()
            if permission is None:
                permission = Permission.objects.create(
                    content_type=content_type,
                    codename=codename,
                    name=spec.name,
                )
                counts["created"] += 1
            else:
                update_fields = []
                if permission.content_type_id != content_type.id:
                    permission.content_type = content_type
                    update_fields.append("content_type")
                if permission.name != spec.name:
                    permission.name = spec.name
                    update_fields.append("name")
                if update_fields:
                    permission.save(update_fields=update_fields)
                    counts["updated"] += 1
                else:
                    counts["unchanged"] += 1
            permissions_by_codename[codename] = permission

        ContentType.objects.filter(app_label=DMIS_AUTH_APP_LABEL).exclude(
            model__in={spec.resource for spec in desired_specs.values()}
        ).delete()
        return counts, permissions_by_codename

    def _sync_groups(self, roles_by_id, combo_group_permissions):
        desired_group_names = set(roles_by_id.values()) | set(combo_group_permissions)
        groups_deleted = Group.objects.exclude(name__in=desired_group_names).count()
        Group.objects.exclude(name__in=desired_group_names).delete()

        counts = {
            "created": 0,
            "updated": 0,
            "unchanged": 0,
            "deleted": groups_deleted,
        }
        groups_by_code = {}
        for group_name in sorted(desired_group_names):
            group, created = Group.objects.get_or_create(name=group_name)
            if created:
                counts["created"] += 1
            else:
                counts["unchanged"] += 1
            groups_by_code[group_name] = group
        return counts, groups_by_code

    def _sync_group_permissions(
        self,
        groups_by_code,
        permissions_by_codename,
        resolved_codes_by_role,
        combo_group_permissions,
        permission_parts_by_code,
    ) -> int:
        mapping_count = 0
        permission_codes_by_group = {
            **resolved_codes_by_role,
            **combo_group_permissions,
        }
        for group_name, group in sorted(groups_by_code.items()):
            desired_permissions = []
            for code in sorted(permission_codes_by_group.get(group_name, set())):
                resource, action = self._permission_parts_for_code(
                    code,
                    permission_parts_by_code,
                )
                codename = self._bridge_codename(resource, action, code)
                desired_permissions.append(permissions_by_codename[codename])
            group.permissions.set(desired_permissions)
            mapping_count += len(desired_permissions)
        return mapping_count

    def _clear_direct_user_permissions(self) -> None:
        user_model = get_user_model()
        user_model.user_permissions.through.objects.all().delete()

    def _sync_user_groups(self, groups_by_code, user_role_codes, combo_groups_by_user_id) -> int:
        user_model = get_user_model()
        users_with_bridge_groups = set(
            user_model.objects.filter(groups__isnull=False)
            .values_list(user_model._meta.pk.name, flat=True)
            .distinct()
        )
        target_user_ids = set(user_role_codes) | users_with_bridge_groups
        users_by_id = user_model.objects.in_bulk(target_user_ids)
        assignment_count = 0
        for user_id in sorted(target_user_ids):
            user = users_by_id.get(user_id)
            if user is None:
                continue
            desired_group_names = set(user_role_codes.get(user_id, set()))
            desired_group_names.update(combo_groups_by_user_id.get(user_id, set()))
            desired_groups = [
                groups_by_code[group_name]
                for group_name in sorted(desired_group_names)
                if group_name in groups_by_code
            ]
            user.groups.set(desired_groups)
            assignment_count += len(desired_groups)
        return assignment_count

    def _ensure_content_types(self, specs) -> dict[str, ContentType]:
        content_types = {}
        max_model_length = ContentType._meta.get_field("model").max_length
        for resource in sorted({spec.resource for spec in specs}):
            if len(resource) > max_model_length:
                raise CommandError(
                    f"DMIS permission resource {resource!r} exceeds Django's "
                    f"{max_model_length}-character ContentType.model limit."
                )
            content_type, _created = ContentType.objects.get_or_create(
                app_label=DMIS_AUTH_APP_LABEL,
                model=resource,
            )
            content_types[resource] = content_type
        return content_types

    def _bridge_codename(self, resource: str, action: str, code: str) -> str:
        codename = bridge_codename(resource, action)
        max_length = Permission._meta.get_field("codename").max_length
        if len(codename) <= max_length:
            return codename

        truncated = codename[:max_length]
        self.stderr.write(
            self.style.WARNING(
                f"Truncated DMIS permission code {code!r} to Django codename "
                f"{truncated!r} ({max_length} characters)."
            )
        )
        return truncated

    def _combo_group_name(self, role_codes) -> str:
        normalized = "\x1f".join(sorted(str(role_code) for role_code in role_codes))
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]
        return f"DMIS_BRIDGE_COMBO_{digest}"

    def _split_permission_code(self, code: str) -> tuple[str, str]:
        cleaned = str(code or "").strip()
        if "." not in cleaned:
            raise CommandError(
                f"Cannot bridge malformed DMIS permission code {cleaned!r}; "
                "expected '<resource>.<action>'."
            )
        resource, action = cleaned.rsplit(".", 1)
        return (
            self._clean_identifier(resource, "permission.resource"),
            self._clean_identifier(action, "permission.action"),
        )

    def _permission_parts_for_code(
        self,
        code: str,
        permission_parts_by_code,
    ) -> tuple[str, str]:
        cleaned = str(code or "").strip()
        permission_parts = permission_parts_by_code.get(cleaned)
        if permission_parts is not None:
            return permission_parts

        known_resources = sorted(
            {resource for resource, _action in permission_parts_by_code.values()},
            key=len,
            reverse=True,
        )
        for resource in known_resources:
            prefix = f"{resource}."
            if cleaned.startswith(prefix):
                action = cleaned[len(prefix):]
                if action:
                    return (
                        self._clean_identifier(resource, "permission.resource"),
                        self._clean_identifier(action, "permission.action"),
                    )

        return self._split_permission_code(cleaned)

    def _permission_code(self, resource, action) -> str:
        return (
            f"{self._clean_identifier(resource, 'permission.resource')}."
            f"{self._clean_identifier(action, 'permission.action')}"
        )

    def _clean_identifier(self, value, field_name: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise CommandError(f"Cannot bridge blank {field_name}.")
        return cleaned
