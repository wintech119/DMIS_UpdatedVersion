from __future__ import annotations

from contextlib import nullcontext
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase


class SeedReliefManagementFrontendTestUsersCommandTests(SimpleTestCase):
    @patch(
        "operations.management.commands.seed_relief_management_frontend_test_users.Command._resolve_role",
        return_value={"id": 20, "code": "AGENCY_DISTRIBUTOR"},
    )
    @patch(
        "operations.management.commands.seed_relief_management_frontend_test_users.Command._resolve_warehouse",
        return_value={"warehouse_id": 14, "warehouse_name": "S07 TEST MAIN HUB - JRC", "tenant_id": 19},
    )
    @patch(
        "operations.management.commands.seed_relief_management_frontend_test_users.Command._resolve_agency",
        return_value={"agency_id": 3, "agency_name": "S07 TEST DISTRIBUTOR AGENCY - JRC", "warehouse_id": 14, "agency_type": "DISTRIBUTOR"},
    )
    @patch(
        "operations.management.commands.seed_relief_management_frontend_test_users.Command._resolve_tenant",
        return_value={"tenant_id": 19, "tenant_code": "JRC", "tenant_name": "JAMAICA RED CROSS"},
    )
    @patch(
        "operations.management.commands.seed_relief_management_frontend_test_users.Command._ensure_user",
    )
    @patch(
        "operations.management.commands.seed_relief_management_frontend_test_users.Command._ensure_tenant_membership",
    )
    @patch(
        "operations.management.commands.seed_relief_management_frontend_test_users.Command._ensure_user_role",
    )
    def test_dry_run_reports_planned_users_without_writing(
        self,
        ensure_user_role,
        ensure_tenant_membership,
        ensure_user,
        _resolve_tenant,
        _resolve_agency,
        _resolve_warehouse,
        _resolve_role,
    ) -> None:
        output = StringIO()

        call_command("seed_relief_management_frontend_test_users", stdout=output)

        text = output.getvalue()
        self.assertIn("Relief Management frontend test-user seed:", text)
        self.assertIn("relief_jrc_requester_tst", text)
        self.assertIn("Dry-run only", text)
        ensure_user.assert_not_called()
        ensure_tenant_membership.assert_not_called()
        ensure_user_role.assert_not_called()

    @patch(
        "operations.management.commands.seed_relief_management_frontend_test_users.transaction.atomic",
        return_value=nullcontext(),
    )
    @patch(
        "operations.management.commands.seed_relief_management_frontend_test_users.Command._resolve_role",
        return_value={"id": 20, "code": "AGENCY_DISTRIBUTOR"},
    )
    @patch(
        "operations.management.commands.seed_relief_management_frontend_test_users.Command._resolve_warehouse",
        return_value={"warehouse_id": 14, "warehouse_name": "S07 TEST MAIN HUB - JRC", "tenant_id": 19},
    )
    @patch(
        "operations.management.commands.seed_relief_management_frontend_test_users.Command._resolve_agency",
        return_value={"agency_id": 3, "agency_name": "S07 TEST DISTRIBUTOR AGENCY - JRC", "warehouse_id": 14, "agency_type": "DISTRIBUTOR"},
    )
    @patch(
        "operations.management.commands.seed_relief_management_frontend_test_users.Command._resolve_tenant",
        return_value={"tenant_id": 19, "tenant_code": "JRC", "tenant_name": "JAMAICA RED CROSS"},
    )
    @patch(
        "operations.management.commands.seed_relief_management_frontend_test_users.Command._ensure_user",
        side_effect=[(95101, True), (95102, False)],
    )
    @patch(
        "operations.management.commands.seed_relief_management_frontend_test_users.Command._ensure_tenant_membership",
        side_effect=[True, True],
    )
    @patch(
        "operations.management.commands.seed_relief_management_frontend_test_users.Command._ensure_user_role",
        side_effect=[True, False],
    )
    def test_apply_creates_memberships_and_roles(
        self,
        ensure_user_role,
        ensure_tenant_membership,
        ensure_user,
        _resolve_tenant,
        _resolve_agency,
        _resolve_warehouse,
        _resolve_role,
        _atomic,
    ) -> None:
        output = StringIO()

        call_command("seed_relief_management_frontend_test_users", apply=True, stdout=output)

        text = output.getvalue()
        self.assertIn("Temporary Relief Management frontend users are ready.", text)
        self.assertIn("users created: 1", text)
        self.assertIn("users reused: 1", text)
        self.assertEqual(ensure_user.call_count, 2)
        self.assertEqual(ensure_tenant_membership.call_count, 2)
        self.assertEqual(ensure_user_role.call_count, 2)

    @patch(
        "operations.management.commands.seed_relief_management_frontend_test_users.Command._resolve_role",
        return_value={"id": 20, "code": "AGENCY_DISTRIBUTOR"},
    )
    @patch(
        "operations.management.commands.seed_relief_management_frontend_test_users.Command._resolve_warehouse",
        return_value={"warehouse_id": 16, "warehouse_name": "S07 TEST MAIN HUB - PARISH_KN", "tenant_id": 14},
    )
    @patch(
        "operations.management.commands.seed_relief_management_frontend_test_users.Command._resolve_agency",
        return_value={
            "agency_id": 5,
            "agency_name": "S07 TEST DISTRIBUTOR AGENCY - PARISH_KN",
            "warehouse_id": 16,
            "agency_type": "DISTRIBUTOR",
        },
    )
    @patch(
        "operations.management.commands.seed_relief_management_frontend_test_users.Command._resolve_tenant",
        return_value={"tenant_id": 14, "tenant_code": "PARISH-KN", "tenant_name": "Kingston and St. Andrew"},
    )
    def test_dry_run_normalizes_default_names_for_hyphenated_tenant_codes(
        self,
        _resolve_tenant,
        resolve_agency,
        resolve_warehouse,
        _resolve_role,
    ) -> None:
        output = StringIO()

        call_command("seed_relief_management_frontend_test_users", tenant_code="PARISH-KN", stdout=output)

        resolve_agency.assert_called_once_with(None, agency_name="S07 TEST DISTRIBUTOR AGENCY - PARISH_KN")
        resolve_warehouse.assert_called_once_with(None, warehouse_name="S07 TEST MAIN HUB - PARISH_KN")
        self.assertIn("relief_parish_kn_requester_tst", output.getvalue())


class CleanupReliefManagementFrontendTestDataCommandTests(SimpleTestCase):
    @patch(
        "operations.management.commands.cleanup_relief_management_frontend_test_data.Command._fetch_agency",
        return_value={"agency_id": 3, "agency_name": "S07 TEST DISTRIBUTOR AGENCY - JRC"},
    )
    @patch(
        "operations.management.commands.cleanup_relief_management_frontend_test_data.Command._fetch_warehouse",
        return_value={"warehouse_id": 14, "warehouse_name": "S07 TEST MAIN HUB - JRC"},
    )
    @patch(
        "operations.management.commands.cleanup_relief_management_frontend_test_data.Command._fetch_users",
        return_value=[{"user_id": 95101, "username": "relief_jrc_requester_tst"}],
    )
    @patch(
        "operations.management.commands.cleanup_relief_management_frontend_test_data.Command._deactivate_tenant_memberships",
    )
    @patch(
        "operations.management.commands.cleanup_relief_management_frontend_test_data.Command._delete_user_roles",
    )
    @patch(
        "operations.management.commands.cleanup_relief_management_frontend_test_data.Command._deactivate_users",
    )
    @patch(
        "operations.management.commands.cleanup_relief_management_frontend_test_data.Command._inactivate_agency",
    )
    @patch(
        "operations.management.commands.cleanup_relief_management_frontend_test_data.Command._inactivate_warehouse",
    )
    def test_dry_run_reports_cleanup_without_writing(
        self,
        inactivate_warehouse,
        inactivate_agency,
        deactivate_users,
        delete_user_roles,
        deactivate_tenant_memberships,
        _fetch_users,
        _fetch_warehouse,
        _fetch_agency,
    ) -> None:
        output = StringIO()

        call_command("cleanup_relief_management_frontend_test_data", stdout=output)

        text = output.getvalue()
        self.assertIn("Relief Management frontend test-data cleanup:", text)
        self.assertIn("users matched: 1", text)
        self.assertIn("Dry-run only", text)
        deactivate_tenant_memberships.assert_not_called()
        delete_user_roles.assert_not_called()
        deactivate_users.assert_not_called()
        inactivate_agency.assert_not_called()
        inactivate_warehouse.assert_not_called()

    @patch(
        "operations.management.commands.cleanup_relief_management_frontend_test_data.transaction.atomic",
        return_value=nullcontext(),
    )
    @patch(
        "operations.management.commands.cleanup_relief_management_frontend_test_data.Command._fetch_agency",
        return_value={"agency_id": 3, "agency_name": "S07 TEST DISTRIBUTOR AGENCY - JRC"},
    )
    @patch(
        "operations.management.commands.cleanup_relief_management_frontend_test_data.Command._fetch_warehouse",
        return_value={"warehouse_id": 14, "warehouse_name": "S07 TEST MAIN HUB - JRC"},
    )
    @patch(
        "operations.management.commands.cleanup_relief_management_frontend_test_data.Command._fetch_users",
        return_value=[
            {"user_id": 95101, "username": "relief_jrc_requester_tst"},
            {"user_id": 95102, "username": "relief_jrc_receiver_tst"},
        ],
    )
    @patch(
        "operations.management.commands.cleanup_relief_management_frontend_test_data.Command._deactivate_tenant_memberships",
    )
    @patch(
        "operations.management.commands.cleanup_relief_management_frontend_test_data.Command._delete_user_roles",
    )
    @patch(
        "operations.management.commands.cleanup_relief_management_frontend_test_data.Command._deactivate_users",
    )
    @patch(
        "operations.management.commands.cleanup_relief_management_frontend_test_data.Command._inactivate_agency",
    )
    @patch(
        "operations.management.commands.cleanup_relief_management_frontend_test_data.Command._inactivate_warehouse",
    )
    def test_apply_deactivates_users_and_master_data(
        self,
        inactivate_warehouse,
        inactivate_agency,
        deactivate_users,
        delete_user_roles,
        deactivate_tenant_memberships,
        _fetch_users,
        _fetch_warehouse,
        _fetch_agency,
        _atomic,
    ) -> None:
        output = StringIO()

        call_command("cleanup_relief_management_frontend_test_data", apply=True, stdout=output)

        text = output.getvalue()
        self.assertIn("deactivated.", text)
        deactivate_tenant_memberships.assert_called_once()
        delete_user_roles.assert_called_once()
        deactivate_users.assert_called_once()
        inactivate_agency.assert_called_once_with(agency_id=3)
        inactivate_warehouse.assert_called_once()
