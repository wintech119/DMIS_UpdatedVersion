from __future__ import annotations

from types import SimpleNamespace

from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.models import (
    Group,
    Permission,
    _user_get_permissions,
    _user_has_module_perms,
    _user_has_perm,
)
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.db import DatabaseError, models, connection, transaction
from django.utils.functional import cached_property
from django.utils.itercompat import is_iterable
from django.utils.translation import gettext_lazy as _

from accounts.managers import DmisUserManager


class DmisUser(AbstractBaseUser):
    username_validator = UnicodeUsernameValidator()

    user_id = models.IntegerField(primary_key=True)
    email = models.EmailField(max_length=200, unique=True)
    password = models.CharField(_("password"), max_length=256, db_column="password_hash")
    first_name = models.CharField(max_length=100, blank=True, null=True)
    last_name = models.CharField(max_length=100, blank=True, null=True)
    full_name = models.CharField(max_length=200, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    organization = models.CharField(max_length=200, blank=True, null=True)
    job_title = models.CharField(max_length=200, blank=True, null=True)
    phone = models.CharField(max_length=50, blank=True, null=True)
    timezone = models.CharField(max_length=50, default="America/Jamaica")
    language = models.CharField(max_length=10, default="en")
    notification_preferences = models.TextField(blank=True, null=True)
    assigned_warehouse_id = models.IntegerField(blank=True, null=True)
    last_login = models.DateTimeField(_("last login"), db_column="last_login_at", blank=True, null=True)
    create_dtime = models.DateTimeField()
    update_dtime = models.DateTimeField()
    username = models.CharField(
        max_length=60,
        unique=True,
        validators=[username_validator],
        blank=True,
        null=True,
    )
    user_name = models.CharField(max_length=20)
    password_algo = models.CharField(max_length=20, default="argon2id", editable=False)
    mfa_enabled = models.BooleanField(default=False)
    mfa_secret = models.CharField(max_length=64, blank=True, null=True, editable=False)
    failed_login_count = models.SmallIntegerField(default=0, editable=False)
    lock_until_at = models.DateTimeField(blank=True, null=True, editable=False)
    password_changed_at = models.DateTimeField(blank=True, null=True, editable=False)
    agency_id = models.IntegerField(blank=True, null=True)
    status_code = models.CharField(max_length=1, default="A")
    version_nbr = models.IntegerField(default=1)
    login_count = models.IntegerField(default=0)

    groups = models.ManyToManyField(
        Group,
        verbose_name=_("groups"),
        blank=True,
        help_text=_(
            "The groups this user belongs to. A user will get all permissions "
            "granted to each of their groups."
        ),
        related_name="user_set",
        related_query_name="user",
    )
    user_permissions = models.ManyToManyField(
        Permission,
        verbose_name=_("user permissions"),
        blank=True,
        help_text=_("Specific permissions for this user."),
        related_name="user_set",
        related_query_name="user",
    )

    objects = DmisUserManager()

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = ["email"]
    EMAIL_FIELD = "email"

    class Meta:
        db_table = '"user"'
        managed = False
        verbose_name = "DMIS user"
        verbose_name_plural = "DMIS users"

    @property
    def is_superuser(self) -> bool:
        return False

    def bind_auth_context(self, *, request=None, roles=None, permissions=None):
        self._dmis_request = request
        self._rbac_seed_roles = list(roles or [])
        self._rbac_seed_permissions = list(permissions or [])
        self._rbac_roles = list(self._rbac_seed_roles)
        self._rbac_permissions = list(self._rbac_seed_permissions)
        self._rbac_resolved = False
        return self

    @property
    def roles(self) -> list[str]:
        if getattr(self, "_rbac_resolving", False):
            return list(getattr(self, "_rbac_seed_roles", []))
        self._ensure_rbac_resolved()
        return list(getattr(self, "_rbac_roles", []))

    @property
    def permissions(self) -> list[str]:
        if getattr(self, "_rbac_resolving", False):
            return list(getattr(self, "_rbac_seed_permissions", []))
        self._ensure_rbac_resolved()
        return list(getattr(self, "_rbac_permissions", []))

    def _ensure_rbac_resolved(self) -> None:
        if getattr(self, "_rbac_resolved", False):
            return
        request = getattr(self, "_dmis_request", None) or SimpleNamespace()
        from api.rbac import resolve_roles_and_permissions

        self._rbac_resolving = True
        try:
            roles, permissions = resolve_roles_and_permissions(request, self)
        finally:
            self._rbac_resolving = False

        self._rbac_roles = list(roles)
        self._rbac_permissions = list(permissions)
        self._rbac_resolved = True

    @cached_property
    def is_staff(self) -> bool:
        if self.user_id in (None, ""):
            return False
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT 1
                    FROM user_role ur
                    JOIN role r ON r.id = ur.role_id
                    WHERE ur.user_id = %s
                      AND UPPER(r.code) = %s
                    LIMIT 1
                    """,
                    [int(self.user_id), "SYSTEM_ADMINISTRATOR"],
                )
                return cursor.fetchone() is not None
        except (DatabaseError, TypeError, ValueError):
            return False

    def _safe_permissions(self, permission_type: str, obj=None):
        try:
            with transaction.atomic():
                return _user_get_permissions(self, obj, permission_type)
        except DatabaseError:
            return set()

    def get_user_permissions(self, obj=None):
        return self._safe_permissions("user", obj)

    def get_group_permissions(self, obj=None):
        return self._safe_permissions("group", obj)

    def get_all_permissions(self, obj=None):
        return self._safe_permissions("all", obj)

    def has_perm(self, perm, obj=None):
        if not self.is_active:
            return False
        try:
            with transaction.atomic():
                if _user_has_perm(self, perm, obj):
                    return True
                if (
                    isinstance(perm, str)
                    and "__" in perm
                    and not perm.startswith("dmis.")
                ):
                    return _user_has_perm(self, f"dmis.{perm}", obj)
                return False
        except DatabaseError:
            return False

    def has_perms(self, perm_list, obj=None):
        if not is_iterable(perm_list) or isinstance(perm_list, str):
            raise ValueError("perm_list must be an iterable of permissions.")
        return all(self.has_perm(perm, obj) for perm in perm_list)

    def has_module_perms(self, app_label):
        if not self.is_active:
            return False
        try:
            with transaction.atomic():
                return _user_has_module_perms(self, app_label)
        except DatabaseError:
            return False

    def __str__(self) -> str:
        return str(self.username or self.email or self.user_id)


class RbacBridgeGroup(models.Model):
    group = models.OneToOneField(
        Group,
        on_delete=models.CASCADE,
        related_name="dmis_rbac_bridge_marker",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "accounts_rbac_bridge_group"
        verbose_name = "DMIS RBAC bridge group marker"
        verbose_name_plural = "DMIS RBAC bridge group markers"
