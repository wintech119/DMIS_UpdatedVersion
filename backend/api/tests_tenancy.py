from __future__ import annotations

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from api.tenancy import (
    TenantContext,
    TenantMembership,
    can_access_tenant,
    can_manage_phase_window_config,
    resolve_tenant_context,
)
from api.authentication import Principal
from api.rbac import PERM_NATIONAL_READ_ALL_TENANTS


class TenancyAccessTests(SimpleTestCase):
    def test_member_can_access_own_tenant(self) -> None:
        context = TenantContext(
            requested_tenant_id=None,
            active_tenant_id=20,
            active_tenant_code="PAR20",
            active_tenant_type="PARISH",
            memberships=(
                TenantMembership(
                    tenant_id=20,
                    tenant_code="PAR20",
                    tenant_name="Parish 20",
                    tenant_type="PARISH",
                    is_primary=True,
                    access_level="admin",
                ),
            ),
            can_read_all_tenants=False,
            can_act_cross_tenant=False,
        )

        self.assertTrue(can_access_tenant(context, 20, write=False))
        self.assertTrue(can_access_tenant(context, 20, write=True))

    def test_read_only_member_cannot_write_own_tenant(self) -> None:
        context = TenantContext(
            requested_tenant_id=None,
            active_tenant_id=20,
            active_tenant_code="PAR20",
            active_tenant_type="PARISH",
            memberships=(
                TenantMembership(
                    tenant_id=20,
                    tenant_code="PAR20",
                    tenant_name="Parish 20",
                    tenant_type="PARISH",
                    is_primary=True,
                    access_level="READ_ONLY",
                ),
            ),
            can_read_all_tenants=False,
            can_act_cross_tenant=False,
        )

        self.assertTrue(can_access_tenant(context, 20, write=False))
        self.assertFalse(can_access_tenant(context, 20, write=True))

    def test_non_neoc_cannot_access_other_tenant(self) -> None:
        context = TenantContext(
            requested_tenant_id=None,
            active_tenant_id=20,
            active_tenant_code="PAR20",
            active_tenant_type="PARISH",
            memberships=(),
            can_read_all_tenants=False,
            can_act_cross_tenant=False,
        )

        self.assertFalse(can_access_tenant(context, 99, write=False))
        self.assertFalse(can_access_tenant(context, 99, write=True))

    @patch("api.tenancy._tenant_by_id")
    def test_neoc_can_read_all_tenants_with_permission(self, tenant_by_id_mock) -> None:
        context = TenantContext(
            requested_tenant_id=1,
            active_tenant_id=1,
            active_tenant_code="ODPEM-NEOC",
            active_tenant_type="NATIONAL",
            memberships=(),
            can_read_all_tenants=True,
            can_act_cross_tenant=False,
        )

        tenant_by_id_mock.return_value = TenantMembership(
            tenant_id=42,
            tenant_code="PAR42",
            tenant_name="Parish 42",
            tenant_type="PARISH",
            is_primary=False,
            access_level=None,
        )
        self.assertTrue(can_access_tenant(context, 42, write=False))
        self.assertFalse(can_access_tenant(context, 42, write=True))

    @patch("api.tenancy._tenant_by_id", return_value=None)
    def test_neoc_cannot_read_inactive_target_tenant(self, _tenant_by_id_mock) -> None:
        context = TenantContext(
            requested_tenant_id=1,
            active_tenant_id=1,
            active_tenant_code="ODPEM-NEOC",
            active_tenant_type="NATIONAL",
            memberships=(),
            can_read_all_tenants=True,
            can_act_cross_tenant=False,
        )

        self.assertFalse(can_access_tenant(context, 42, write=False))

    def test_non_neoc_national_tenant_cannot_read_all(self) -> None:
        context = TenantContext(
            requested_tenant_id=3,
            active_tenant_id=3,
            active_tenant_code="ODPEM-LOGISTICS",
            active_tenant_type="NATIONAL",
            memberships=(),
            can_read_all_tenants=True,
            can_act_cross_tenant=False,
        )

        self.assertFalse(can_access_tenant(context, 42, write=False))

    @patch("api.tenancy._tenant_by_id")
    @patch("api.tenancy._target_tenant_allows_neoc_actions")
    def test_neoc_write_requires_target_opt_in(self, target_opt_in, tenant_by_id_mock) -> None:
        context = TenantContext(
            requested_tenant_id=1,
            active_tenant_id=1,
            active_tenant_code="ODPEM-NEOC",
            active_tenant_type="NEOC",
            memberships=(),
            can_read_all_tenants=True,
            can_act_cross_tenant=True,
        )

        tenant_by_id_mock.return_value = TenantMembership(
            tenant_id=42,
            tenant_code="PAR42",
            tenant_name="Parish 42",
            tenant_type="PARISH",
            is_primary=False,
            access_level=None,
        )
        target_opt_in.return_value = False
        self.assertFalse(can_access_tenant(context, 42, write=True))

        target_opt_in.return_value = True
        self.assertTrue(can_access_tenant(context, 42, write=True))

    @patch("api.tenancy._tenant_by_id", return_value=None)
    @patch("api.tenancy._target_tenant_allows_neoc_actions")
    def test_neoc_write_rejects_inactive_target_tenant(self, target_opt_in, _tenant_by_id_mock) -> None:
        context = TenantContext(
            requested_tenant_id=1,
            active_tenant_id=1,
            active_tenant_code="ODPEM-NEOC",
            active_tenant_type="NEOC",
            memberships=(),
            can_read_all_tenants=True,
            can_act_cross_tenant=True,
        )

        target_opt_in.return_value = True
        self.assertFalse(can_access_tenant(context, 42, write=True))

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        NATIONAL_PHASE_WINDOW_ADMIN_CODES=[
            "OFFICE-OF-DISASTER-P",
            "ODPEM-NEOC",
        ]
    )
    def test_phase_window_config_requires_direct_odpem_national_membership(self) -> None:
        odpem_context = TenantContext(
            requested_tenant_id=27,
            active_tenant_id=27,
            active_tenant_code="OFFICE-OF-DISASTER-P",
            active_tenant_type="NATIONAL",
            memberships=(
                TenantMembership(
                    tenant_id=27,
                    tenant_code="OFFICE-OF-DISASTER-P",
                    tenant_name="ODPEM National",
                    tenant_type="NATIONAL",
                    is_primary=True,
                    access_level="admin",
                ),
            ),
            can_read_all_tenants=False,
            can_act_cross_tenant=False,
        )
        neoc_context = TenantContext(
            requested_tenant_id=2,
            active_tenant_id=27,
            active_tenant_code="OFFICE-OF-DISASTER-P",
            active_tenant_type="NATIONAL",
            memberships=(
                TenantMembership(
                    tenant_id=2,
                    tenant_code="ODPEM-NEOC",
                    tenant_name="ODPEM NEOC",
                    tenant_type="NEOC",
                    is_primary=True,
                    access_level="admin",
                ),
            ),
            can_read_all_tenants=True,
            can_act_cross_tenant=True,
        )
        other_context = TenantContext(
            requested_tenant_id=3,
            active_tenant_id=3,
            active_tenant_code="ODPEM-LOGISTICS",
            active_tenant_type="NATIONAL",
            memberships=(
                TenantMembership(
                    tenant_id=3,
                    tenant_code="ODPEM-LOGISTICS",
                    tenant_name="ODPEM Logistics",
                    tenant_type="NATIONAL",
                    is_primary=True,
                    access_level="admin",
                ),
            ),
            can_read_all_tenants=False,
            can_act_cross_tenant=False,
        )
        stale_env_neoc_context = TenantContext(
            requested_tenant_id=2,
            active_tenant_id=2,
            active_tenant_code="ODPEM-NEOC",
            active_tenant_type="NATIONAL_LEVEL",
            memberships=(
                TenantMembership(
                    tenant_id=2,
                    tenant_code="ODPEM-NEOC",
                    tenant_name="ODPEM NEOC",
                    tenant_type="NATIONAL_LEVEL",
                    is_primary=True,
                    access_level="admin",
                ),
            ),
            can_read_all_tenants=True,
            can_act_cross_tenant=True,
        )

        self.assertTrue(can_manage_phase_window_config(odpem_context))
        self.assertFalse(can_manage_phase_window_config(neoc_context))
        self.assertFalse(can_manage_phase_window_config(other_context))
        self.assertFalse(can_manage_phase_window_config(stale_env_neoc_context))

    @patch("api.tenancy._tenant_by_id")
    @patch("api.tenancy.list_user_tenant_memberships")
    def test_resolve_context_does_not_activate_requested_tenant_without_neoc_access(
        self,
        memberships_mock,
        tenant_by_id_mock,
    ) -> None:
        memberships_mock.return_value = tuple()
        tenant_by_id_mock.return_value = TenantMembership(
            tenant_id=42,
            tenant_code="PAR42",
            tenant_name="Parish 42",
            tenant_type="PARISH",
            is_primary=False,
            access_level=None,
        )
        request = type("Req", (), {"META": {"HTTP_X_TENANT_ID": "42"}, "query_params": {}})()
        principal = Principal(user_id="1", username="user", roles=[])

        context = resolve_tenant_context(
            request,
            principal,
            [PERM_NATIONAL_READ_ALL_TENANTS],
        )

        tenant_by_id_mock.assert_not_called()
        self.assertEqual(context.requested_tenant_id, 42)
        self.assertIsNone(context.active_tenant_id)
