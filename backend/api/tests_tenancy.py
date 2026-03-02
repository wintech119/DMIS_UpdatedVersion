from __future__ import annotations

from unittest.mock import patch

from django.test import SimpleTestCase

from api.tenancy import TenantContext, TenantMembership, can_access_tenant


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

    def test_neoc_can_read_all_tenants_with_permission(self) -> None:
        context = TenantContext(
            requested_tenant_id=1,
            active_tenant_id=1,
            active_tenant_code="ODPEM-NEOC",
            active_tenant_type="NATIONAL",
            memberships=(),
            can_read_all_tenants=True,
            can_act_cross_tenant=False,
        )

        self.assertTrue(can_access_tenant(context, 42, write=False))
        self.assertFalse(can_access_tenant(context, 42, write=True))

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

    @patch("api.tenancy._target_tenant_allows_neoc_actions")
    def test_neoc_write_requires_target_opt_in(self, target_opt_in) -> None:
        context = TenantContext(
            requested_tenant_id=1,
            active_tenant_id=1,
            active_tenant_code="ODPEM-NEOC",
            active_tenant_type="NEOC",
            memberships=(),
            can_read_all_tenants=True,
            can_act_cross_tenant=True,
        )

        target_opt_in.return_value = False
        self.assertFalse(can_access_tenant(context, 42, write=True))

        target_opt_in.return_value = True
        self.assertTrue(can_access_tenant(context, 42, write=True))
