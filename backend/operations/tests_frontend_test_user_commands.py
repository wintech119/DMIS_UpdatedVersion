from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase

from operations.management.commands.seed_relief_management_frontend_test_users import Command


class SeedReliefManagementFrontendTestUsersCommandTests(SimpleTestCase):
    def test_ensure_user_annotation_uses_frontend_user_spec(self) -> None:
        self.assertEqual(
            Command._ensure_user.__annotations__["profile"],
            "TemporaryFrontendUserSpec",
        )

    @patch(
        "operations.management.commands.seed_relief_management_frontend_test_users.timezone.now",
        return_value=datetime(2026, 3, 28, 9, 30, 0),
    )
    @patch("operations.management.commands.seed_relief_management_frontend_test_users.connection")
    def test_ensure_user_prefers_username_match_before_email_match(
        self,
        mock_connection,
        _now_mock,
    ) -> None:
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.side_effect = [(95101,), (95202,)]

        user_id, created = Command()._ensure_user(
            profile=SimpleNamespace(
                username="relief_jrc_requester_tst",
                email="requester@agency.example.org",
                user_name="Requester",
                first_name="Alicia",
                last_name="Bennett",
                full_name="Alicia Bennett",
                job_title="Distribution Coordinator",
            ),
            tenant_name="JAMAICA RED CROSS",
            agency_id=3,
            warehouse_id=14,
        )

        self.assertEqual(user_id, 95101)
        self.assertFalse(created)
        self.assertEqual(len(cursor.execute.call_args_list), 2)
        username_sql, username_params = cursor.execute.call_args_list[0].args
        self.assertIn("WHERE username = %s", username_sql)
        self.assertEqual(username_params, ["relief_jrc_requester_tst"])
        update_sql, update_params = cursor.execute.call_args_list[1].args
        self.assertIn('UPDATE "user"', update_sql)
        self.assertEqual(update_params[-1], 95101)

    @patch(
        "operations.management.commands.seed_relief_management_frontend_test_users.timezone.now",
        return_value=datetime(2026, 3, 28, 9, 30, 0),
    )
    @patch("operations.management.commands.seed_relief_management_frontend_test_users.connection")
    def test_ensure_user_falls_back_to_email_match_when_username_missing(
        self,
        mock_connection,
        _now_mock,
    ) -> None:
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.side_effect = [None, (95202,)]

        user_id, created = Command()._ensure_user(
            profile=SimpleNamespace(
                username="relief_jrc_requester_tst",
                email="requester@agency.example.org",
                user_name="Requester",
                first_name="Alicia",
                last_name="Bennett",
                full_name="Alicia Bennett",
                job_title="Distribution Coordinator",
            ),
            tenant_name="JAMAICA RED CROSS",
            agency_id=3,
            warehouse_id=14,
        )

        self.assertEqual(user_id, 95202)
        self.assertFalse(created)
        self.assertEqual(len(cursor.execute.call_args_list), 3)
        username_sql, username_params = cursor.execute.call_args_list[0].args
        email_sql, email_params = cursor.execute.call_args_list[1].args
        self.assertIn("WHERE username = %s", username_sql)
        self.assertEqual(username_params, ["relief_jrc_requester_tst"])
        self.assertIn("WHERE email = %s", email_sql)
        self.assertEqual(email_params, ["requester@agency.example.org"])

    @patch("operations.management.commands.seed_relief_management_frontend_test_users.connection")
    def test_resolve_agency_name_lookup_filters_to_active_rows(self, mock_connection) -> None:
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (3, "S07 TEST DISTRIBUTOR AGENCY - JRC", 14, "DISTRIBUTOR", "A")

        agency = Command()._resolve_agency(None, agency_name="S07 TEST DISTRIBUTOR AGENCY - JRC")

        self.assertEqual(agency["agency_id"], 3)
        sql, params = cursor.execute.call_args.args
        self.assertIn("UPPER(COALESCE(agency_name, '')) = %s", sql)
        self.assertIn("UPPER(COALESCE(status_code, '')) = 'A'", sql)
        self.assertEqual(params, ["S07 TEST DISTRIBUTOR AGENCY - JRC"])

    @patch("operations.management.commands.seed_relief_management_frontend_test_users.connection")
    def test_resolve_warehouse_name_lookup_filters_to_active_rows(self, mock_connection) -> None:
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (14, "S07 TEST MAIN HUB - JRC", 19, "A")

        warehouse = Command()._resolve_warehouse(None, warehouse_name="S07 TEST MAIN HUB - JRC")

        self.assertEqual(warehouse["warehouse_id"], 14)
        sql, params = cursor.execute.call_args.args
        self.assertIn("UPPER(COALESCE(warehouse_name, '')) = %s", sql)
        self.assertIn("UPPER(COALESCE(status_code, '')) = 'A'", sql)
        self.assertEqual(params, ["S07 TEST MAIN HUB - JRC"])

    def test_profile_builder_uses_real_non_odpem_personas(self) -> None:
        profiles = Command()._build_profiles("FFP", "Food For The Poor")

        self.assertEqual([profile.username for profile in profiles], [
            "local_system_admin_tst",
            "local_odpem_deputy_director_tst",
            "local_odpem_logistics_manager_tst",
            "local_odpem_logistics_officer_tst",
            "relief_ffp_requester_tst",
        ])
        self.assertEqual(profiles[0].role_code, "SYSTEM_ADMINISTRATOR")
        self.assertEqual(profiles[0].tenant_scope, "national")
        self.assertFalse(profiles[0].bind_to_agency)
        self.assertFalse(profiles[0].bind_to_warehouse)
        self.assertEqual(profiles[1].full_name, "Natalie Williams")
        self.assertEqual(profiles[1].job_title, "ODPEM Deputy Director")
        self.assertEqual(profiles[1].role_code, "ODPEM_DDG")
        self.assertEqual(profiles[1].tenant_scope, "national")
        self.assertFalse(profiles[1].bind_to_agency)
        self.assertFalse(profiles[1].bind_to_warehouse)
        self.assertEqual(profiles[2].full_name, "Kemar Campbell")
        self.assertEqual(profiles[2].job_title, "ODPEM Logistics Manager")
        self.assertEqual(profiles[2].role_code, "ODPEM_LOGISTICS_MANAGER")
        self.assertEqual(profiles[2].tenant_scope, "national")
        self.assertFalse(profiles[2].bind_to_agency)
        self.assertFalse(profiles[2].bind_to_warehouse)
        self.assertEqual(profiles[3].full_name, "Chantal Ellis")
        self.assertEqual(profiles[3].job_title, "ODPEM Logistics Officer")
        self.assertEqual(profiles[3].tenant_scope, "national")
        self.assertFalse(profiles[3].bind_to_agency)
        self.assertFalse(profiles[3].bind_to_warehouse)
        self.assertEqual(profiles[4].full_name, "Alicia Bennett")
        self.assertEqual(profiles[4].job_title, "Distribution Coordinator")
        self.assertEqual(profiles[0].email, "system.admin+local@dmis.example.org")
        self.assertTrue(profiles[1].email.endswith("@odpem.gov.jm"))
        self.assertTrue(profiles[2].email.endswith("@odpem.gov.jm"))
        self.assertTrue(profiles[3].email.endswith("@odpem.gov.jm"))
        self.assertTrue(profiles[4].email.endswith("@agency.example.org"))
        self.assertTrue(all(len(profile.user_name) <= 20 for profile in profiles))

    @patch(
        "operations.management.commands.seed_relief_management_frontend_test_users.Command._resolve_role",
        side_effect=lambda role_code: {"id": 20, "code": role_code},
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
        "operations.management.commands.seed_relief_management_frontend_test_users.Command._resolve_national_tenant",
        return_value={"tenant_id": 27, "tenant_code": "ODPEM-NEOC", "tenant_name": "ODPEM NEOC"},
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
        _resolve_national_tenant,
        _resolve_tenant,
        _resolve_agency,
        _resolve_warehouse,
        _resolve_role,
    ) -> None:
        output = StringIO()

        call_command("seed_relief_management_frontend_test_users", stdout=output)

        text = output.getvalue()
        self.assertIn("Relief Management frontend test-user seed:", text)
        self.assertIn("local_system_admin_tst", text)
        self.assertIn("local_odpem_deputy_director_tst", text)
        self.assertIn("local_odpem_logistics_manager_tst", text)
        self.assertIn("local_odpem_logistics_officer_tst", text)
        self.assertIn("relief_jrc_requester_tst", text)
        self.assertIn("recommended DEV_AUTH_USER_ID: local_system_admin_tst", text)
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
        side_effect=lambda role_code: {"id": 20, "code": role_code},
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
        "operations.management.commands.seed_relief_management_frontend_test_users.Command._resolve_national_tenant",
        return_value={"tenant_id": 27, "tenant_code": "ODPEM-NEOC", "tenant_name": "ODPEM NEOC"},
    )
    @patch(
        "operations.management.commands.seed_relief_management_frontend_test_users.Command._ensure_user",
        side_effect=[(95101, True), (95102, False), (95103, True), (95104, False), (95105, True)],
    )
    @patch(
        "operations.management.commands.seed_relief_management_frontend_test_users.Command._ensure_tenant_membership",
        side_effect=[True, True, True, True, True],
    )
    @patch(
        "operations.management.commands.seed_relief_management_frontend_test_users.Command._ensure_user_role",
        side_effect=[True, False, True, False, True],
    )
    def test_apply_creates_memberships_and_roles(
        self,
        ensure_user_role,
        ensure_tenant_membership,
        ensure_user,
        _resolve_national_tenant,
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
        self.assertIn("users created: 3", text)
        self.assertIn("users reused: 2", text)
        self.assertEqual(ensure_user.call_count, 5)
        self.assertEqual(ensure_tenant_membership.call_count, 5)
        self.assertEqual(ensure_user_role.call_count, 5)
        self.assertEqual(ensure_tenant_membership.call_args_list[0].kwargs["tenant_id"], 27)
        self.assertEqual(ensure_tenant_membership.call_args_list[1].kwargs["tenant_id"], 27)
        self.assertEqual(ensure_tenant_membership.call_args_list[2].kwargs["tenant_id"], 27)
        self.assertEqual(ensure_tenant_membership.call_args_list[3].kwargs["tenant_id"], 27)
        self.assertEqual(ensure_tenant_membership.call_args_list[4].kwargs["tenant_id"], 19)

    @patch(
        "operations.management.commands.seed_relief_management_frontend_test_users.Command._resolve_role",
        side_effect=lambda role_code: {"id": 20, "code": role_code},
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
    @patch(
        "operations.management.commands.seed_relief_management_frontend_test_users.Command._resolve_national_tenant",
        return_value={"tenant_id": 27, "tenant_code": "ODPEM-NEOC", "tenant_name": "ODPEM NEOC"},
    )
    def test_dry_run_normalizes_default_names_for_hyphenated_tenant_codes(
        self,
        _resolve_national_tenant,
        _resolve_tenant,
        resolve_agency,
        resolve_warehouse,
        _resolve_role,
    ) -> None:
        output = StringIO()

        call_command("seed_relief_management_frontend_test_users", tenant_code="PARISH-KN", stdout=output)

        resolve_agency.assert_called_once_with(None, agency_name="S07 TEST DISTRIBUTOR AGENCY - PARISH_KN")
        resolve_warehouse.assert_called_once_with(None, warehouse_name="S07 TEST MAIN HUB - PARISH_KN")
        self.assertIn("local_odpem_deputy_director_tst", output.getvalue())
        self.assertIn("local_odpem_logistics_manager_tst", output.getvalue())
        self.assertIn("relief_parish_kn_requester_tst", output.getvalue())

    @patch(
        "operations.management.commands.seed_relief_management_frontend_test_users.timezone.now",
        return_value=datetime(2026, 3, 28, 9, 30, 0),
    )
    @patch(
        "operations.management.commands.seed_relief_management_frontend_test_users.lock_primary_tenant_membership",
    )
    @patch("operations.management.commands.seed_relief_management_frontend_test_users.connection")
    def test_existing_tenant_membership_update_preserves_creation_audit(
        self,
        mock_connection,
        lock_primary_tenant_membership_mock,
        now_mock,
    ) -> None:
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (1,)

        result = Command()._ensure_tenant_membership(
            user_id=95101,
            tenant_id=19,
            access_level="WRITE",
            actor_id="SYSTEM",
            actor_user_id=95200,
        )

        self.assertTrue(result)
        lock_primary_tenant_membership_mock.assert_called_once_with(cursor, user_id=95101)
        update_sql, update_params = cursor.execute.call_args_list[2].args
        self.assertNotIn("create_by_id", update_sql)
        self.assertNotIn("create_dtime", update_sql)
        self.assertEqual(
            update_params,
            ["WRITE", now_mock.return_value, 95200, 19, 95101],
        )


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
        return_value=[{"user_id": 95103, "username": "relief_jrc_requester_tst"}],
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
