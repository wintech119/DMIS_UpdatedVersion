from __future__ import annotations

from datetime import date
from io import StringIO
from unittest.mock import patch

from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, TestCase

from operations.models import TenantControlScope, TenantHierarchy, TenantRequestPolicy

TEST_PARISH_TENANT = {
    "tenant_id": 14,
    "tenant_code": "PARISH-KN",
    "tenant_name": "Kingston and St. Andrew Municipal Corporation",
    "tenant_type": "PARISH",
}

TEST_FFP_TENANT = {
    "tenant_id": 20,
    "tenant_code": "FFP",
    "tenant_name": "Food For The Poor",
    "tenant_type": "EXTERNAL",
}

TEST_ODPEM_TENANT = {
    "tenant_id": 27,
    "tenant_code": "OFFICE-OF-DISASTER-P",
    "tenant_name": "ODPEM",
    "tenant_type": "EXTERNAL",
}


def tenant_sequence(*tenants: dict[str, object]) -> list[dict[str, object]]:
    return [dict(tenant) for tenant in tenants]


class SeedReliefManagementHierarchyTestDataCommandTests(SimpleTestCase):
    @patch(
        "operations.management.commands.seed_relief_management_hierarchy_test_data.Command._resolve_tenant",
        side_effect=tenant_sequence(TEST_PARISH_TENANT, TEST_FFP_TENANT),
    )
    def test_dry_run_reports_planned_hierarchy_seed(
        self,
        _resolve_tenant,
    ) -> None:
        output = StringIO()

        call_command("seed_relief_management_hierarchy_test_data", stdout=output)

        text = output.getvalue()
        self.assertIn("Relief Management hierarchy test-data seed:", text)
        self.assertIn("PARISH-KN", text)
        self.assertIn("FFP", text)
        self.assertIn("Dry-run only", text)

    @patch(
        "operations.management.commands.seed_relief_management_hierarchy_test_data.Command._resolve_tenant",
        side_effect=tenant_sequence(TEST_ODPEM_TENANT, TEST_FFP_TENANT),
    )
    def test_dry_run_rejects_non_parish_controller(
        self,
        _resolve_tenant,
    ) -> None:
        with self.assertRaisesMessage(CommandError, "parish tenant must have tenant_type=PARISH"):
            call_command("seed_relief_management_hierarchy_test_data")

    @patch(
        "operations.management.commands.cleanup_relief_management_hierarchy_test_data.Command._resolve_tenant",
        side_effect=tenant_sequence(TEST_PARISH_TENANT, TEST_FFP_TENANT),
    )
    def test_cleanup_dry_run_reports_planned_revert(
        self,
        _resolve_tenant,
    ) -> None:
        output = StringIO()

        call_command("cleanup_relief_management_hierarchy_test_data", stdout=output)

        text = output.getvalue()
        self.assertIn("Relief Management hierarchy test-data cleanup:", text)
        self.assertIn("PARISH-KN", text)
        self.assertIn("FFP", text)
        self.assertIn("Dry-run only", text)


class ApplyReliefManagementHierarchyTestDataCommandTests(TestCase):
    @patch(
        "operations.management.commands.seed_relief_management_hierarchy_test_data.Command._resolve_tenant",
        side_effect=tenant_sequence(TEST_PARISH_TENANT, TEST_FFP_TENANT),
    )
    def test_apply_upserts_policy_scope_and_hierarchy(
        self,
        _resolve_tenant,
    ) -> None:
        output = StringIO()

        call_command(
            "seed_relief_management_hierarchy_test_data",
            actor="seed-user",
            effective_date="2026-03-26",
            apply=True,
            stdout=output,
        )

        policy = TenantRequestPolicy.objects.get(tenant_id=20, effective_date=date(2026, 3, 26))
        self.assertFalse(policy.can_self_request_flag)
        self.assertEqual(policy.request_authority_tenant_id, 14)
        self.assertEqual(policy.update_by_id, "seed-user")
        self.assertTrue(
            TenantControlScope.objects.filter(
                controller_tenant_id=14,
                controlled_tenant_id=20,
                control_type="REQUEST_AUTHORITY",
                effective_date=date(2026, 3, 26),
                status_code="ACTIVE",
            ).exists()
        )
        self.assertTrue(
            TenantHierarchy.objects.filter(
                parent_tenant_id=14,
                child_tenant_id=20,
                relationship_type="REQUEST_AUTHORITY",
                effective_date=date(2026, 3, 26),
                status_code="ACTIVE",
                can_parent_request_on_behalf_flag=True,
            ).exists()
        )
        self.assertIn("Temporary Relief Management hierarchy data is ready.", output.getvalue())

    @patch(
        "operations.management.commands.seed_relief_management_hierarchy_test_data.Command._resolve_tenant",
        side_effect=tenant_sequence(TEST_PARISH_TENANT, TEST_FFP_TENANT),
    )
    def test_apply_preserves_unrelated_policy_rows_and_inactive_history(
        self,
        _resolve_tenant,
    ) -> None:
        TenantRequestPolicy.objects.create(
            tenant_id=20,
            can_self_request_flag=True,
            request_authority_tenant_id=None,
            can_create_needs_list_flag=True,
            can_apply_needs_list_to_relief_request_flag=True,
            can_export_needs_list_for_donation_flag=True,
            can_broadcast_needs_list_for_donation_flag=True,
            allow_odpem_bridge_flag=False,
            effective_date=date(2026, 3, 20),
            status_code="ACTIVE",
            create_by_id="baseline",
            update_by_id="baseline",
        )
        TenantControlScope.objects.create(
            controller_tenant_id=14,
            controlled_tenant_id=20,
            control_type="REQUEST_AUTHORITY",
            effective_date=date(2026, 3, 20),
            expiry_date=date(2026, 3, 25),
            status_code="INACTIVE",
            create_by_id="baseline",
            update_by_id="baseline",
        )
        TenantHierarchy.objects.create(
            parent_tenant_id=14,
            child_tenant_id=20,
            relationship_type="REQUEST_AUTHORITY",
            can_parent_request_on_behalf_flag=False,
            effective_date=date(2026, 3, 20),
            expiry_date=date(2026, 3, 25),
            status_code="INACTIVE",
            create_by_id="baseline",
            update_by_id="baseline",
        )

        call_command(
            "seed_relief_management_hierarchy_test_data",
            actor="seed-user",
            effective_date="2026-03-26",
            apply=True,
        )

        baseline_policy = TenantRequestPolicy.objects.get(tenant_id=20, effective_date=date(2026, 3, 20))
        self.assertTrue(baseline_policy.can_self_request_flag)
        self.assertIsNone(baseline_policy.request_authority_tenant_id)
        self.assertEqual(baseline_policy.status_code, "ACTIVE")

        historical_scope = TenantControlScope.objects.get(
            controller_tenant_id=14,
            controlled_tenant_id=20,
            control_type="REQUEST_AUTHORITY",
            effective_date=date(2026, 3, 20),
        )
        historical_hierarchy = TenantHierarchy.objects.get(
            parent_tenant_id=14,
            child_tenant_id=20,
            relationship_type="REQUEST_AUTHORITY",
            effective_date=date(2026, 3, 20),
        )
        self.assertEqual(historical_scope.status_code, "INACTIVE")
        self.assertEqual(historical_scope.expiry_date, date(2026, 3, 25))
        self.assertEqual(historical_hierarchy.status_code, "INACTIVE")
        self.assertEqual(historical_hierarchy.expiry_date, date(2026, 3, 25))

    @patch(
        "operations.management.commands.cleanup_relief_management_hierarchy_test_data.Command._resolve_tenant",
        side_effect=tenant_sequence(TEST_PARISH_TENANT, TEST_FFP_TENANT),
    )
    def test_cleanup_resets_policy_and_inactivates_scope_and_hierarchy(
        self,
        _resolve_tenant,
    ) -> None:
        TenantRequestPolicy.objects.create(
            tenant_id=20,
            can_self_request_flag=False,
            request_authority_tenant_id=14,
            can_create_needs_list_flag=True,
            can_apply_needs_list_to_relief_request_flag=True,
            can_export_needs_list_for_donation_flag=True,
            can_broadcast_needs_list_for_donation_flag=True,
            allow_odpem_bridge_flag=False,
            effective_date=date(2026, 3, 26),
            status_code="ACTIVE",
            create_by_id="seed",
            update_by_id="seed",
        )
        TenantControlScope.objects.create(
            controller_tenant_id=14,
            controlled_tenant_id=20,
            control_type="REQUEST_AUTHORITY",
            effective_date=date(2026, 3, 26),
            status_code="ACTIVE",
            create_by_id="seed",
            update_by_id="seed",
        )
        TenantHierarchy.objects.create(
            parent_tenant_id=14,
            child_tenant_id=20,
            relationship_type="REQUEST_AUTHORITY",
            can_parent_request_on_behalf_flag=True,
            effective_date=date(2026, 3, 26),
            status_code="ACTIVE",
            create_by_id="seed",
            update_by_id="seed",
        )

        output = StringIO()
        call_command(
            "cleanup_relief_management_hierarchy_test_data",
            actor="cleanup-user",
            effective_date="2026-03-26",
            apply=True,
            stdout=output,
        )

        policy = TenantRequestPolicy.objects.get(tenant_id=20, effective_date=date(2026, 3, 26))
        self.assertTrue(policy.can_self_request_flag)
        self.assertIsNone(policy.request_authority_tenant_id)
        self.assertEqual(policy.update_by_id, "cleanup-user")

        control_scope = TenantControlScope.objects.get(
            controller_tenant_id=14,
            controlled_tenant_id=20,
            control_type="REQUEST_AUTHORITY",
            effective_date=date(2026, 3, 26),
        )
        hierarchy = TenantHierarchy.objects.get(
            parent_tenant_id=14,
            child_tenant_id=20,
            relationship_type="REQUEST_AUTHORITY",
            effective_date=date(2026, 3, 26),
        )
        self.assertEqual(control_scope.status_code, "INACTIVE")
        self.assertEqual(control_scope.expiry_date, date(2026, 3, 26))
        self.assertEqual(hierarchy.status_code, "INACTIVE")
        self.assertEqual(hierarchy.expiry_date, date(2026, 3, 26))
        self.assertIn("Temporary Relief Management hierarchy data has been reverted.", output.getvalue())
