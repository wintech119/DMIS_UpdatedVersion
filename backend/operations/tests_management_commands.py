from __future__ import annotations

from contextlib import nullcontext
import json
import os
import tempfile
from datetime import date
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, TestCase, override_settings

from operations.models import TenantControlScope, TenantHierarchy, TenantRequestPolicy


class ImportReliefManagementAuthorityCommandTests(TestCase):
    def _write_payload(self, payload: dict[str, object]) -> str:
        fd, raw_path = tempfile.mkstemp(
            suffix=".json",
            prefix="authority_",
            dir=str(Path.cwd()),
        )
        self.addCleanup(lambda: Path(raw_path).unlink(missing_ok=True))
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload))
        path = Path(raw_path)
        return str(path)

    def test_dry_run_validates_payload_without_writing(self) -> None:
        payload_path = self._write_payload(
            {
                "policies": [
                    {
                        "tenant_code": "PARISH_001",
                        "can_self_request_flag": True,
                        "effective_date": "2026-03-26",
                    }
                ],
                "control_scopes": [
                    {
                        "controller_tenant_code": "PARISH_001",
                        "controlled_tenant_code": "COMMUNITY_001",
                        "control_type": "REQUEST_AUTHORITY",
                        "effective_date": "2026-03-26",
                    }
                ],
                "hierarchies": [
                    {
                        "parent_tenant_code": "PARISH_001",
                        "child_tenant_code": "COMMUNITY_001",
                        "relationship_type": "REQUEST_AUTHORITY",
                        "can_parent_request_on_behalf_flag": True,
                        "effective_date": "2026-03-26",
                    }
                ],
            }
        )
        output = StringIO()

        with patch(
            "operations.management.commands.import_relief_management_authority.Command._resolve_tenant_reference",
            side_effect=[400, None, 400, 300, 400, 300],
        ):
            call_command("import_relief_management_authority", payload_path, stdout=output)

        text = output.getvalue()
        self.assertIn("Relief Management authority import:", text)
        self.assertIn("Dry-run only", text)
        self.assertEqual(TenantRequestPolicy.objects.count(), 0)
        self.assertEqual(TenantControlScope.objects.count(), 0)
        self.assertEqual(TenantHierarchy.objects.count(), 0)

    def test_apply_creates_and_updates_authority_rows(self) -> None:
        TenantRequestPolicy.objects.create(
            tenant_id=300,
            can_self_request_flag=True,
            request_authority_tenant_id=None,
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

        payload_path = self._write_payload(
            {
                "policies": [
                    {
                        "tenant_id": 300,
                        "can_self_request_flag": False,
                        "request_authority_tenant_id": 400,
                        "effective_date": "2026-03-26",
                        "status_code": "ACTIVE",
                    }
                ],
                "control_scopes": [
                    {
                        "controller_tenant_id": 400,
                        "controlled_tenant_id": 300,
                        "control_type": "REQUEST_AUTHORITY",
                        "effective_date": "2026-03-26",
                    }
                ],
                "hierarchies": [
                    {
                        "parent_tenant_id": 400,
                        "child_tenant_id": 300,
                        "relationship_type": "REQUEST_AUTHORITY",
                        "can_parent_request_on_behalf_flag": True,
                        "effective_date": "2026-03-26",
                    }
                ],
            }
        )
        output = StringIO()

        with patch(
            "operations.management.commands.import_relief_management_authority.Command._resolve_tenant_reference",
            side_effect=[300, 400, 400, 300, 400, 300],
        ):
            call_command(
                "import_relief_management_authority",
                payload_path,
                actor="importer",
                apply=True,
                stdout=output,
            )

        policy = TenantRequestPolicy.objects.get(tenant_id=300, effective_date=date(2026, 3, 26))
        self.assertFalse(policy.can_self_request_flag)
        self.assertEqual(policy.request_authority_tenant_id, 400)
        self.assertTrue(
            TenantControlScope.objects.filter(
                controller_tenant_id=400,
                controlled_tenant_id=300,
                control_type="REQUEST_AUTHORITY",
            ).exists()
        )
        self.assertTrue(
            TenantHierarchy.objects.filter(
                parent_tenant_id=400,
                child_tenant_id=300,
                relationship_type="REQUEST_AUTHORITY",
            ).exists()
        )


class CheckReliefManagementReadinessCommandTests(SimpleTestCase):
    @override_settings(AUTH_USE_DB_RBAC=True)
    @patch(
        "operations.management.commands.check_relief_management_readiness.Command._fetch_permission_codes",
        return_value=set(),
    )
    @patch(
        "operations.management.commands.check_relief_management_readiness.Command._fetch_active_agency_summary",
        return_value={
            "active_agencies": 2,
            "resolved_agencies": 2,
            "non_odpem_resolved_agencies": 1,
        },
    )
    @patch(
        "operations.management.commands.check_relief_management_readiness.Command._fetch_role_codes",
        return_value={
            "ODPEM_DDG",
            "ODPEM_DIR_PEOD",
            "ODPEM_DG",
            "LOGISTICS_OFFICER",
            "LOGISTICS_MANAGER",
            "INVENTORY_CLERK",
        },
    )
    @patch(
        "operations.management.commands.check_relief_management_readiness.Command._safe_count_active",
        side_effect=[1, 1],
    )
    @patch(
        "operations.management.commands.check_relief_management_readiness.Command._active_rows",
    )
    @patch(
        "operations.management.commands.check_relief_management_readiness.Command._existing_tables",
        return_value={
            "tenant_hierarchy",
            "tenant_request_policy",
            "tenant_control_scope",
            "operations_relief_request",
            "operations_eligibility_decision",
            "operations_package",
            "operations_package_lock",
            "operations_dispatch",
            "operations_dispatch_transport",
            "operations_waybill",
            "operations_receipt",
            "operations_notification",
            "operations_queue_assignment",
            "operations_status_history",
            "role",
            "permission",
        },
    )
    @patch(
        "operations.management.commands.check_relief_management_readiness.Command._migration_applied",
        return_value=True,
    )
    def test_readiness_passes_when_migration_and_seed_data_exist(
        self,
        _migration_applied,
        _existing_tables,
        active_rows_mock,
        _safe_count_active,
        _fetch_active_agency_summary,
        _fetch_role_codes,
        _fetch_permission_codes,
    ) -> None:
        queryset = active_rows_mock.return_value
        queryset.count.return_value = 2
        queryset.filter.return_value.values_list.return_value = [300, 400]
        output = StringIO()

        call_command("check_relief_management_readiness", stdout=output)

        text = output.getvalue()
        self.assertIn("Relief Management frontend readiness check:", text)
        self.assertIn("No live-frontend blockers detected.", text)
        self.assertIn("Warnings:", text)

    @override_settings(AUTH_USE_DB_RBAC=True)
    @patch(
        "operations.management.commands.check_relief_management_readiness.Command._fetch_active_agency_summary",
        return_value={
            "active_agencies": 1,
            "resolved_agencies": 1,
            "non_odpem_resolved_agencies": 0,
        },
    )
    @patch(
        "operations.management.commands.check_relief_management_readiness.Command._fetch_permission_codes",
        return_value=set(),
    )
    @patch(
        "operations.management.commands.check_relief_management_readiness.Command._fetch_role_codes",
        return_value={
            "ODPEM_DDG",
            "ODPEM_DIR_PEOD",
            "ODPEM_DG",
            "LOGISTICS_OFFICER",
            "LOGISTICS_MANAGER",
            "INVENTORY_CLERK",
        },
    )
    @patch(
        "operations.management.commands.check_relief_management_readiness.Command._safe_count_active",
        side_effect=[0, 0],
    )
    @patch(
        "operations.management.commands.check_relief_management_readiness.Command._active_rows",
    )
    @patch(
        "operations.management.commands.check_relief_management_readiness.Command._existing_tables",
        return_value={
            "tenant_hierarchy",
            "tenant_request_policy",
            "tenant_control_scope",
            "operations_relief_request",
            "operations_eligibility_decision",
            "operations_package",
            "operations_package_lock",
            "operations_dispatch",
            "operations_dispatch_transport",
            "operations_waybill",
            "operations_receipt",
            "operations_notification",
            "operations_queue_assignment",
            "operations_status_history",
            "role",
            "permission",
            "agency",
            "warehouse",
            "tenant",
        },
    )
    @patch(
        "operations.management.commands.check_relief_management_readiness.Command._migration_applied",
        return_value=True,
    )
    def test_readiness_blocks_when_only_odpem_agencies_are_resolved(
        self,
        _migration_applied,
        _existing_tables,
        active_rows_mock,
        _safe_count_active,
        _fetch_role_codes,
        _fetch_permission_codes,
        _fetch_active_agency_summary,
    ) -> None:
        queryset = active_rows_mock.return_value
        queryset.count.return_value = 2
        queryset.filter.return_value.values_list.return_value = [27, 20]
        with self.assertRaises(CommandError):
            call_command("check_relief_management_readiness")

    @override_settings(AUTH_USE_DB_RBAC=True)
    @patch(
        "operations.management.commands.check_relief_management_readiness.Command._existing_tables",
        return_value=set(),
    )
    @patch(
        "operations.management.commands.check_relief_management_readiness.Command._migration_applied",
        return_value=False,
    )
    def test_readiness_blocks_when_operations_migration_is_missing(
        self,
        _migration_applied,
        _existing_tables,
    ) -> None:
        with self.assertRaises(CommandError):
            call_command("check_relief_management_readiness")


class BootstrapReliefManagementAuthorityBaselineCommandTests(SimpleTestCase):
    @patch(
        "operations.management.commands.bootstrap_relief_management_authority_baseline.Command._load_active_tenants",
        return_value=[
            object(),
        ],
    )
    @patch(
        "operations.management.commands.bootstrap_relief_management_authority_baseline.Command._build_rows",
        return_value=(
            [{"tenant_id": 20}],
            [],
            [],
            {
                "bridge_only_tenants": 1,
                "direct_self_service_tenants": 0,
                "public_read_only_tenants": 0,
                "parish_subordinate_tenants": 0,
                "unclassified_parent_links": 0,
            },
        ),
    )
    def test_dry_run_reports_baseline_summary(
        self,
        _build_rows,
        _load_active_tenants,
    ) -> None:
        output = StringIO()
        call_command("bootstrap_relief_management_authority_baseline", stdout=output)
        text = output.getvalue()
        self.assertIn("Relief Management authority baseline bootstrap:", text)
        self.assertIn("Dry-run only", text)

    def test_build_rows_classifies_odpem_public_and_flat_direct_tenants(self) -> None:
        from operations.management.commands.bootstrap_relief_management_authority_baseline import (
            Command,
            TenantSnapshot,
        )

        command = Command()
        policy_rows, control_rows, hierarchy_rows, summary = command._build_rows(
            [
                TenantSnapshot(tenant_id=27, tenant_code="OFFICE-OF-DISASTER-P", tenant_name="ODPEM", tenant_type="NATIONAL", parent_tenant_id=None),
                TenantSnapshot(tenant_id=14, tenant_code="PARISH-KN", tenant_name="Parish", tenant_type="PARISH", parent_tenant_id=None),
                TenantSnapshot(tenant_id=20, tenant_code="FFP", tenant_name="Food For The Poor", tenant_type="EXTERNAL", parent_tenant_id=None),
                TenantSnapshot(tenant_id=25, tenant_code="PUBLIC", tenant_name="Public", tenant_type="PUBLIC", parent_tenant_id=None),
            ],
            date(2026, 3, 26),
        )

        policy_by_tenant = {row["tenant_id"]: row for row in policy_rows}
        self.assertFalse(policy_by_tenant[27]["can_self_request_flag"])
        self.assertTrue(policy_by_tenant[27]["allow_odpem_bridge_flag"])
        self.assertTrue(policy_by_tenant[20]["can_self_request_flag"])
        self.assertFalse(policy_by_tenant[25]["can_create_needs_list_flag"])
        self.assertEqual(control_rows, [])
        self.assertEqual(hierarchy_rows, [])
        self.assertEqual(summary["bridge_only_tenants"], 1)
        self.assertEqual(summary["direct_self_service_tenants"], 2)
        self.assertEqual(summary["public_read_only_tenants"], 1)


class AgencyScopeAuditCommandTests(SimpleTestCase):
    def _row(
        self,
        *,
        agency_id: int,
        agency_name: str,
        warehouse_id: int | None,
        warehouse_status_code: str | None,
        tenant_id: int | None,
        tenant_code: str | None,
    ):
        from operations.management.commands.audit_relief_management_agency_scope import AgencyScopeAuditRow

        resolution_status = "READY_NON_ODPEM"
        resolution_reason = "Agency resolves to a non-ODPEM tenant and is ready."
        if warehouse_id is None:
            resolution_status = "UNRESOLVED_NO_WAREHOUSE"
            resolution_reason = "Agency is not linked to a warehouse."
        elif warehouse_status_code not in (None, "", "A"):
            resolution_status = "UNRESOLVED_INACTIVE_WAREHOUSE"
            resolution_reason = "Agency points to an inactive warehouse."
        elif tenant_id is None:
            resolution_status = "UNRESOLVED_NO_TENANT"
            resolution_reason = "Agency warehouse does not resolve to a tenant owner."
        elif tenant_code == "OFFICE-OF-DISASTER-P":
            resolution_status = "ODPEM_ONLY"
            resolution_reason = "Agency resolves only to an ODPEM-owned tenant."

        return AgencyScopeAuditRow(
            agency_id=agency_id,
            agency_name=agency_name,
            agency_type="SHELTER",
            agency_status_code="A",
            warehouse_id=warehouse_id,
            warehouse_name="Warehouse A" if warehouse_id else None,
            warehouse_status_code=warehouse_status_code,
            tenant_id=tenant_id,
            tenant_code=tenant_code,
            tenant_name="Tenant Name" if tenant_id else None,
            tenant_type="PARISH" if tenant_id else None,
            resolution_status=resolution_status,
            resolution_reason=resolution_reason,
        )

    @patch("operations.management.commands.audit_relief_management_agency_scope.Command._fetch_rows")
    def test_audit_writes_json_and_reports_non_ready_agencies(self, fetch_rows) -> None:
        fetch_rows.return_value = [
            self._row(
                agency_id=5,
                agency_name="Ready Agency",
                warehouse_id=10,
                warehouse_status_code="A",
                tenant_id=20,
                tenant_code="JRC",
            ),
            self._row(
                agency_id=6,
                agency_name="ODPEM Agency",
                warehouse_id=11,
                warehouse_status_code="A",
                tenant_id=27,
                tenant_code="OFFICE-OF-DISASTER-P",
            ),
        ]
        output = StringIO()
        fd, raw_path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        json_path = Path(raw_path)
        self.addCleanup(lambda: json_path.unlink(missing_ok=True))
        call_command(
            "audit_relief_management_agency_scope",
            json_out=str(json_path),
            stdout=output,
        )
        payload = json.loads(json_path.read_text(encoding="utf-8"))

        text = output.getvalue()
        self.assertIn("Relief Management agency scope audit:", text)
        self.assertIn("ready non-ODPEM agencies: 1", text)
        self.assertEqual(payload["summary"]["odpem_owned_agencies"], 1)
        self.assertEqual(payload["summary"]["ready_non_odpem_agencies"], 1)
        self.assertEqual(len(payload["agencies"]), 2)

    @patch("operations.management.commands.audit_relief_management_agency_scope.Command._fetch_rows")
    def test_audit_blocks_when_no_non_odpem_agencies_are_ready(self, fetch_rows) -> None:
        fetch_rows.return_value = [
            self._row(
                agency_id=6,
                agency_name="ODPEM Agency",
                warehouse_id=11,
                warehouse_status_code="A",
                tenant_id=27,
                tenant_code="OFFICE-OF-DISASTER-P",
            ),
            self._row(
                agency_id=7,
                agency_name="Missing Warehouse",
                warehouse_id=None,
                warehouse_status_code=None,
                tenant_id=None,
                tenant_code=None,
            ),
        ]

        with self.assertRaises(CommandError):
            call_command("audit_relief_management_agency_scope")


class SeedReliefManagementFrontendTestDataCommandTests(SimpleTestCase):
    @patch(
        "operations.management.commands.seed_relief_management_frontend_test_data.Command._resolve_custodian",
    )
    @patch(
        "operations.management.commands.seed_relief_management_frontend_test_data.Command._resolve_tenant",
        return_value={
            "tenant_id": 19,
            "tenant_code": "JRC",
            "tenant_name": "JAMAICA RED CROSS",
            "tenant_type": "EXTERNAL",
        },
    )
    @patch(
        "operations.management.commands.seed_relief_management_frontend_test_data.Command._fetch_warehouse_by_name",
        return_value=None,
    )
    @patch(
        "operations.management.commands.seed_relief_management_frontend_test_data.Command._fetch_agency_by_name",
        return_value=None,
    )
    @patch(
        "operations.management.commands.seed_relief_management_frontend_test_data.Command._validate_create_payload",
    )
    @patch(
        "operations.management.commands.seed_relief_management_frontend_test_data.create_record",
    )
    def test_dry_run_reports_planned_seed_without_writing(
        self,
        create_record,
        _validate_create_payload,
        _fetch_agency_by_name,
        _fetch_warehouse_by_name,
        _resolve_tenant,
        _resolve_custodian,
    ) -> None:
        output = StringIO()

        call_command("seed_relief_management_frontend_test_data", stdout=output)

        text = output.getvalue()
        self.assertIn("Relief Management frontend test-data seed:", text)
        self.assertIn("target tenant: 19 (JRC)", text)
        self.assertIn("Dry-run only", text)
        create_record.assert_not_called()

    @patch(
        "operations.management.commands.seed_relief_management_frontend_test_data.Command._resolve_custodian",
    )
    @patch(
        "operations.management.commands.seed_relief_management_frontend_test_data.Command._resolve_tenant",
        return_value={
            "tenant_id": 19,
            "tenant_code": "JRC",
            "tenant_name": "JAMAICA RED CROSS",
            "tenant_type": "EXTERNAL",
        },
    )
    @patch(
        "operations.management.commands.seed_relief_management_frontend_test_data.Command._fetch_warehouse_by_name",
        return_value=None,
    )
    @patch(
        "operations.management.commands.seed_relief_management_frontend_test_data.Command._fetch_agency_by_name",
        return_value=None,
    )
    @patch(
        "operations.management.commands.seed_relief_management_frontend_test_data.Command._validate_create_payload",
    )
    @patch(
        "operations.management.commands.seed_relief_management_frontend_test_data.create_record",
        side_effect=[(101, []), (501, [])],
    )
    def test_apply_creates_warehouse_then_agency(
        self,
        create_record,
        _validate_create_payload,
        _fetch_agency_by_name,
        _fetch_warehouse_by_name,
        _resolve_tenant,
        _resolve_custodian,
    ) -> None:
        output = StringIO()

        call_command("seed_relief_management_frontend_test_data", actor="seed-user", apply=True, stdout=output)

        text = output.getvalue()
        self.assertIn("Created warehouse 101", text)
        self.assertIn("Created agency 501", text)
        self.assertEqual(create_record.call_count, 2)
        warehouse_call = create_record.call_args_list[0]
        agency_call = create_record.call_args_list[1]
        self.assertEqual(warehouse_call.args[0], "warehouses")
        self.assertEqual(warehouse_call.args[1]["tenant_id"], 19)
        self.assertEqual(agency_call.args[0], "agencies")
        self.assertEqual(agency_call.args[1]["warehouse_id"], 101)

    @patch(
        "operations.management.commands.seed_relief_management_frontend_test_data.Command._resolve_custodian",
    )
    @patch(
        "operations.management.commands.seed_relief_management_frontend_test_data.Command._resolve_tenant",
        return_value={
            "tenant_id": 19,
            "tenant_code": "JRC",
            "tenant_name": "JAMAICA RED CROSS",
            "tenant_type": "EXTERNAL",
        },
    )
    @patch(
        "operations.management.commands.seed_relief_management_frontend_test_data.Command._fetch_warehouse_by_name",
        return_value={
            "warehouse_id": 101,
            "warehouse_name": "S07 TEST MAIN HUB - JRC",
            "tenant_id": 19,
            "status_code": "A",
            "warehouse_type": "MAIN-HUB",
        },
    )
    @patch(
        "operations.management.commands.seed_relief_management_frontend_test_data.Command._fetch_agency_by_name",
        return_value={
            "agency_id": 501,
            "agency_name": "S07 TEST DISTRIBUTOR AGENCY - JRC",
            "warehouse_id": 101,
            "status_code": "A",
            "agency_type": "DISTRIBUTOR",
        },
    )
    @patch(
        "operations.management.commands.seed_relief_management_frontend_test_data.create_record",
    )
    def test_apply_reuses_existing_seed_records(
        self,
        create_record,
        _fetch_agency_by_name,
        _fetch_warehouse_by_name,
        _resolve_tenant,
        _resolve_custodian,
    ) -> None:
        output = StringIO()

        call_command("seed_relief_management_frontend_test_data", apply=True, stdout=output)

        text = output.getvalue()
        self.assertIn("Reused warehouse 101", text)
        self.assertIn("Reused agency 501", text)
        create_record.assert_not_called()


class SeedOperationsRbacPermissionsCommandTests(SimpleTestCase):
    @patch(
        "operations.management.commands.seed_operations_rbac_permissions.Command._fetch_role_permission_keys",
        return_value=set(),
    )
    @patch(
        "operations.management.commands.seed_operations_rbac_permissions.Command._fetch_role_ids",
        return_value={"LOGISTICS_MANAGER": 5, "SYSTEM_ADMINISTRATOR": 9},
    )
    @patch(
        "operations.management.commands.seed_operations_rbac_permissions.Command._fetch_permission_ids",
        return_value={},
    )
    def test_dry_run_reports_missing_permissions_without_writing(
        self,
        _fetch_permission_ids,
        _fetch_role_ids,
        _fetch_role_permission_keys,
    ) -> None:
        output = StringIO()

        call_command("seed_operations_rbac_permissions", stdout=output)

        text = output.getvalue()
        self.assertIn("Operations RBAC seed:", text)
        self.assertIn("Dry-run only", text)

    @patch(
        "operations.management.commands.seed_operations_rbac_permissions.Command._insert_role_permissions",
    )
    @patch(
        "operations.management.commands.seed_operations_rbac_permissions.Command._insert_permissions",
    )
    @patch(
        "operations.management.commands.seed_operations_rbac_permissions.Command._next_perm_id",
        return_value=101,
    )
    def test_apply_inserts_permissions_and_links(
        self,
        _next_perm_id,
        insert_permissions,
        insert_role_permissions,
    ) -> None:
        from operations.management.commands.seed_operations_rbac_permissions import (
            ALL_OPERATIONS_PERMISSIONS,
        )

        role_ids = {"LOGISTICS_MANAGER": 5, "SYSTEM_ADMINISTRATOR": 9}
        permission_ids_after_insert = {
            permission: index + 101 for index, permission in enumerate(ALL_OPERATIONS_PERMISSIONS)
        }
        output = StringIO()

        with patch(
            "operations.management.commands.seed_operations_rbac_permissions.transaction.atomic",
            return_value=nullcontext(),
        ), patch(
            "operations.management.commands.seed_operations_rbac_permissions.Command._fetch_permission_ids",
            side_effect=[{}, permission_ids_after_insert],
        ), patch(
            "operations.management.commands.seed_operations_rbac_permissions.Command._fetch_role_ids",
            return_value=role_ids,
        ), patch(
            "operations.management.commands.seed_operations_rbac_permissions.Command._fetch_role_permission_keys",
            return_value=set(),
        ):
            call_command("seed_operations_rbac_permissions", actor="seed-user", apply=True, stdout=output)

        text = output.getvalue()
        self.assertIn("Operations RBAC seed applied.", text)
        insert_permissions.assert_called_once()
        insert_role_permissions.assert_called_once()
