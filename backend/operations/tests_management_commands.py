from __future__ import annotations

from contextlib import nullcontext
import json
import os
import tempfile
from datetime import date, timedelta
from decimal import Decimal
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.core.management import CommandError, call_command
from django.db import connection
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from operations.constants import (
    QUEUE_CODE_DISPATCH,
    QUEUE_CODE_FULFILLMENT,
    QUEUE_CODE_OVERRIDE,
    REQUEST_STATUS_APPROVED_FOR_FULFILLMENT,
    ROLE_LOGISTICS_MANAGER,
    ROLE_LOGISTICS_OFFICER,
)
from operations.models import (
    OperationsAllocationLine,
    OperationsNotification,
    OperationsPackage,
    OperationsPackageLock,
    OperationsQueueAssignment,
    OperationsReliefRequest,
    TenantControlScope,
    TenantHierarchy,
    TenantRequestPolicy,
)
from replenishment.legacy_models import Inventory, ItemBatch
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
    def test_inventory_clerk_seed_permissions_exclude_staging_receipt_and_pickup_release(self) -> None:
        from api import rbac
        from operations.management.commands.seed_operations_rbac_permissions import (
            OPERATIONS_ROLE_PERMISSION_MAP,
        )

        permissions = OPERATIONS_ROLE_PERMISSION_MAP["INVENTORY_CLERK"]

        self.assertNotIn(rbac.PERM_OPERATIONS_CONSOLIDATION_RECEIVE, permissions)
        self.assertNotIn(rbac.PERM_OPERATIONS_PICKUP_RELEASE, permissions)

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


class RepairRequestLevelFulfillmentQueueScopeCommandTests(TestCase):
    resolver_path = (
        "operations.management.commands.repair_request_level_fulfillment_queue_scope."
        "operations_policy.resolve_odpem_fulfillment_tenant_id"
    )

    def setUp(self) -> None:
        super().setUp()
        self.resolver_patch = patch(self.resolver_path, return_value=27)
        self.resolver_patch.start()
        self.addCleanup(self.resolver_patch.stop)

    def _create_request(
        self,
        *,
        relief_request_id: int,
        request_no: str,
        requesting_tenant_id: int = 19,
        beneficiary_tenant_id: int = 19,
        status_code: str = REQUEST_STATUS_APPROVED_FOR_FULFILLMENT,
    ) -> OperationsReliefRequest:
        return OperationsReliefRequest.objects.create(
            relief_request_id=relief_request_id,
            request_no=request_no,
            requesting_tenant_id=requesting_tenant_id,
            requesting_agency_id=401,
            beneficiary_tenant_id=beneficiary_tenant_id,
            beneficiary_agency_id=501,
            origin_mode="SELF",
            event_id=12,
            request_date=date(2026, 3, 26),
            urgency_code="H",
            status_code=status_code,
            submitted_by_id="relief_jrc_requester_tst",
            create_by_id="tester",
            update_by_id="tester",
        )

    def _create_assignment(
        self,
        *,
        entity_id: int,
        queue_code: str = QUEUE_CODE_FULFILLMENT,
        tenant_id: int | None = 19,
        role_code: str = ROLE_LOGISTICS_OFFICER,
        assignment_status: str = "OPEN",
    ) -> OperationsQueueAssignment:
        return OperationsQueueAssignment.objects.create(
            queue_code=queue_code,
            entity_type="RELIEF_REQUEST",
            entity_id=entity_id,
            assigned_role_code=role_code,
            assigned_tenant_id=tenant_id,
            assignment_status=assignment_status,
        )

    def _create_notification(
        self,
        *,
        entity_id: int,
        queue_code: str = QUEUE_CODE_FULFILLMENT,
        tenant_id: int | None = 19,
        role_code: str = ROLE_LOGISTICS_OFFICER,
    ) -> OperationsNotification:
        return OperationsNotification.objects.create(
            event_code="REQUEST_APPROVED",
            entity_type="RELIEF_REQUEST",
            entity_id=entity_id,
            recipient_role_code=role_code,
            recipient_tenant_id=tenant_id,
            message_text="Repair candidate",
            queue_code=queue_code,
        )

    def test_dry_run_reports_affected_rows_and_does_not_persist_changes(self) -> None:
        self._create_request(relief_request_id=95009, request_no="RQ95009")
        assignment = self._create_assignment(entity_id=95009, role_code=ROLE_LOGISTICS_OFFICER)
        notification = self._create_notification(entity_id=95009, role_code=ROLE_LOGISTICS_OFFICER)
        output = StringIO()

        call_command("repair_request_level_fulfillment_queue_scope", stdout=output)

        text = output.getvalue()
        self.assertIn("Request-level fulfillment queue scope repair:", text)
        self.assertIn("RQ95009", text)
        self.assertIn("QUEUE_ASSIGNMENT", text)
        self.assertIn("NOTIFICATION", text)
        self.assertIn("tenant=19 -> 27", text)
        self.assertIn("Dry-run only", text)
        assignment.refresh_from_db()
        notification.refresh_from_db()
        self.assertEqual(assignment.assigned_tenant_id, 19)
        self.assertEqual(notification.recipient_tenant_id, 19)


    def test_apply_updates_fulfillment_queue_assignments_to_odpem_tenant(self) -> None:
        self._create_request(relief_request_id=95009, request_no="RQ95009")
        officer_assignment = self._create_assignment(entity_id=95009, role_code=ROLE_LOGISTICS_OFFICER)
        manager_assignment = self._create_assignment(entity_id=95009, role_code=ROLE_LOGISTICS_MANAGER)
        output = StringIO()

        call_command("repair_request_level_fulfillment_queue_scope", apply=True, stdout=output)

        officer_assignment.refresh_from_db()
        manager_assignment.refresh_from_db()
        self.assertEqual(officer_assignment.assigned_tenant_id, 27)
        self.assertEqual(manager_assignment.assigned_tenant_id, 27)
        self.assertIn("queue assignments updated: 2", output.getvalue())

    def test_apply_updates_corresponding_notifications_to_odpem_tenant(self) -> None:
        self._create_request(relief_request_id=95009, request_no="RQ95009")
        officer_notification = self._create_notification(entity_id=95009, role_code=ROLE_LOGISTICS_OFFICER)
        manager_notification = self._create_notification(entity_id=95009, role_code=ROLE_LOGISTICS_MANAGER)
        output = StringIO()

        call_command("repair_request_level_fulfillment_queue_scope", apply=True, stdout=output)

        officer_notification.refresh_from_db()
        manager_notification.refresh_from_db()
        self.assertEqual(officer_notification.recipient_tenant_id, 27)
        self.assertEqual(manager_notification.recipient_tenant_id, 27)
        self.assertIn("notifications updated: 2", output.getvalue())

    def test_apply_rolls_back_assignment_updates_when_notification_repair_fails(self) -> None:
        self._create_request(relief_request_id=95009, request_no="RQ95009")
        assignment = self._create_assignment(entity_id=95009)
        self._create_notification(entity_id=95009)
        output = StringIO()

        with patch(
            "operations.management.commands.repair_request_level_fulfillment_queue_scope."
            "Command._apply_notification_repairs",
            side_effect=RuntimeError("notification repair failed"),
        ):
            with self.assertRaisesRegex(RuntimeError, "notification repair failed"):
                call_command("repair_request_level_fulfillment_queue_scope", apply=True, stdout=output)

        assignment.refresh_from_db()
        self.assertEqual(assignment.assigned_tenant_id, 19)

    def test_request_no_filter_limits_repair_to_targeted_request(self) -> None:
        self._create_request(relief_request_id=95009, request_no="RQ95009")
        self._create_request(relief_request_id=95010, request_no="RQ95010")
        targeted_assignment = self._create_assignment(entity_id=95009)
        other_assignment = self._create_assignment(entity_id=95010)
        output = StringIO()

        call_command(
            "repair_request_level_fulfillment_queue_scope",
            request_no="RQ95009",
            apply=True,
            stdout=output,
        )

        targeted_assignment.refresh_from_db()
        other_assignment.refresh_from_db()
        self.assertEqual(targeted_assignment.assigned_tenant_id, 27)
        self.assertEqual(other_assignment.assigned_tenant_id, 19)
        self.assertIn("candidate requests: 1", output.getvalue())

    def test_second_apply_is_noop_after_initial_repair(self) -> None:
        self._create_request(relief_request_id=95009, request_no="RQ95009")
        self._create_assignment(entity_id=95009)
        first_output = StringIO()
        second_output = StringIO()

        call_command("repair_request_level_fulfillment_queue_scope", apply=True, stdout=first_output)
        call_command("repair_request_level_fulfillment_queue_scope", apply=True, stdout=second_output)

        self.assertIn("total rows repaired: 1", first_output.getvalue())
        self.assertIn("No repairs needed.", second_output.getvalue())
        self.assertIn("total rows repaired: 0", second_output.getvalue())

    def test_include_override_repairs_request_level_override_rows(self) -> None:
        self._create_request(relief_request_id=95009, request_no="RQ95009")
        override_assignment = self._create_assignment(
            entity_id=95009,
            queue_code=QUEUE_CODE_OVERRIDE,
            role_code=ROLE_LOGISTICS_MANAGER,
        )
        override_notification = self._create_notification(
            entity_id=95009,
            queue_code=QUEUE_CODE_OVERRIDE,
            role_code=ROLE_LOGISTICS_MANAGER,
        )
        output = StringIO()

        call_command(
            "repair_request_level_fulfillment_queue_scope",
            include_override=True,
            apply=True,
            stdout=output,
        )

        override_assignment.refresh_from_db()
        override_notification.refresh_from_db()
        self.assertEqual(override_assignment.assigned_tenant_id, 27)
        self.assertEqual(override_notification.recipient_tenant_id, 27)

    def test_override_rows_are_skipped_without_include_override(self) -> None:
        self._create_request(relief_request_id=95009, request_no="RQ95009")
        override_assignment = self._create_assignment(
            entity_id=95009,
            queue_code=QUEUE_CODE_OVERRIDE,
            role_code=ROLE_LOGISTICS_MANAGER,
        )
        override_notification = self._create_notification(
            entity_id=95009,
            queue_code=QUEUE_CODE_OVERRIDE,
            role_code=ROLE_LOGISTICS_MANAGER,
        )
        output = StringIO()

        call_command("repair_request_level_fulfillment_queue_scope", apply=True, stdout=output)

        override_assignment.refresh_from_db()
        override_notification.refresh_from_db()
        self.assertEqual(override_assignment.assigned_tenant_id, 19)
        self.assertEqual(override_notification.recipient_tenant_id, 19)
        self.assertIn("planned queue assignment repairs: 0", output.getvalue())

    def test_rows_already_in_odpem_scope_are_left_untouched(self) -> None:
        self._create_request(relief_request_id=95009, request_no="RQ95009")
        assignment = self._create_assignment(entity_id=95009, tenant_id=27)
        notification = self._create_notification(entity_id=95009, tenant_id=27)
        output = StringIO()

        call_command("repair_request_level_fulfillment_queue_scope", apply=True, stdout=output)

        assignment.refresh_from_db()
        notification.refresh_from_db()
        self.assertEqual(assignment.assigned_tenant_id, 27)
        self.assertEqual(notification.recipient_tenant_id, 27)
        self.assertIn("total rows repaired: 0", output.getvalue())

    def test_unrelated_queue_codes_are_untouched(self) -> None:
        self._create_request(relief_request_id=95009, request_no="RQ95009")
        assignment = self._create_assignment(
            entity_id=95009,
            queue_code=QUEUE_CODE_DISPATCH,
            tenant_id=19,
            role_code=ROLE_LOGISTICS_OFFICER,
        )
        notification = self._create_notification(
            entity_id=95009,
            queue_code=QUEUE_CODE_DISPATCH,
            tenant_id=19,
            role_code=ROLE_LOGISTICS_OFFICER,
        )
        output = StringIO()

        call_command(
            "repair_request_level_fulfillment_queue_scope",
            include_override=True,
            apply=True,
            stdout=output,
        )

        assignment.refresh_from_db()
        notification.refresh_from_db()
        self.assertEqual(assignment.assigned_tenant_id, 19)
        self.assertEqual(notification.recipient_tenant_id, 19)


class RepairInventoryAggregatesCommandTests(TransactionTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls._created_tables: list[type] = []
        existing_tables = set(connection.introspection.table_names())
        with connection.schema_editor() as schema_editor:
            for model in (Inventory, ItemBatch):
                if model._meta.db_table in existing_tables:
                    continue
                schema_editor.create_model(model)
                cls._created_tables.append(model)

    @classmethod
    def tearDownClass(cls) -> None:
        with connection.schema_editor() as schema_editor:
            for model in reversed(cls._created_tables):
                schema_editor.delete_model(model)
        super().tearDownClass()

    def _create_inventory(
        self,
        *,
        inventory_id: int = 9903,
        item_id: int = 9195,
        usable_qty: Decimal = Decimal("0.0000"),
        reserved_qty: Decimal = Decimal("0.0000"),
        defective_qty: Decimal = Decimal("0.0000"),
        expired_qty: Decimal = Decimal("0.0000"),
        version_nbr: int = 1,
    ) -> Inventory:
        Inventory.objects.filter(inventory_id=inventory_id).delete()
        return Inventory.objects.create(
            inventory_id=inventory_id,
            item_id=item_id,
            usable_qty=usable_qty,
            reserved_qty=reserved_qty,
            defective_qty=defective_qty,
            expired_qty=expired_qty,
            uom_code="EA",
            status_code="A",
            update_by_id="seed",
            update_dtime=timezone.now(),
            version_nbr=version_nbr,
        )

    def _create_batch(
        self,
        *,
        batch_id: int = 995045,
        inventory_id: int = 9903,
        item_id: int = 9195,
        usable_qty: Decimal = Decimal("200.0000"),
        reserved_qty: Decimal = Decimal("0.0000"),
        defective_qty: Decimal = Decimal("0.0000"),
        expired_qty: Decimal = Decimal("0.0000"),
        status_code: str = "A",
    ) -> ItemBatch:
        ItemBatch.objects.filter(batch_id=batch_id).delete()
        return ItemBatch.objects.create(
            batch_id=batch_id,
            inventory_id=inventory_id,
            item_id=item_id,
            batch_no=f"B-{batch_id}",
            batch_date=date(2026, 4, 8),
            expiry_date=None,
            usable_qty=usable_qty,
            reserved_qty=reserved_qty,
            defective_qty=defective_qty,
            expired_qty=expired_qty,
            uom_code="EA",
            status_code=status_code,
            update_by_id="seed",
            update_dtime=timezone.now(),
            version_nbr=1,
        )

    def test_dry_run_reports_current_and_batch_totals_without_persisting(self) -> None:
        inventory = self._create_inventory()
        self._create_batch(
            usable_qty=Decimal("200.0000"),
            defective_qty=Decimal("5.0000"),
            expired_qty=Decimal("1.0000"),
        )
        output = StringIO()

        call_command(
            "repair_inventory_aggregates",
            inventory_id=9903,
            item_id=9195,
            batch_id=995045,
            stdout=output,
        )

        text = output.getvalue()
        self.assertIn("Inventory aggregate repair:", text)
        self.assertIn("batch_id verification: 995045", text)
        self.assertIn("current aggregate totals: usable=0.0000 reserved=0.0000", text)
        self.assertIn("active batch totals: rows=1 usable=200.0000 reserved=0.0000", text)
        self.assertIn("planned action: update", text)
        self.assertIn("Dry-run only", text)
        inventory.refresh_from_db()
        self.assertEqual(inventory.usable_qty, Decimal("0.00"))
        self.assertEqual(inventory.version_nbr, 1)

    def test_apply_updates_stale_inventory_aggregate_from_active_batch_totals(self) -> None:
        inventory = self._create_inventory()
        self._create_batch(
            usable_qty=Decimal("200.0000"),
            defective_qty=Decimal("5.0000"),
            expired_qty=Decimal("1.0000"),
        )
        output = StringIO()

        call_command(
            "repair_inventory_aggregates",
            inventory_id=9903,
            item_id=9195,
            actor="SYSTEM",
            apply=True,
            stdout=output,
        )

        inventory.refresh_from_db()
        self.assertEqual(inventory.usable_qty, Decimal("200.00"))
        self.assertEqual(inventory.reserved_qty, Decimal("0.00"))
        self.assertEqual(inventory.defective_qty, Decimal("5.00"))
        self.assertEqual(inventory.expired_qty, Decimal("1.00"))
        self.assertEqual(inventory.update_by_id, "SYSTEM")
        self.assertEqual(inventory.version_nbr, 2)
        self.assertIn("Inventory aggregate repair applied.", output.getvalue())
        self.assertIn("applied action: update", output.getvalue())

    def test_apply_creates_missing_inventory_row_from_active_batch_totals(self) -> None:
        self._create_batch(
            inventory_id=9911,
            item_id=9222,
            batch_id=995111,
            usable_qty=Decimal("75.5000"),
            reserved_qty=Decimal("10.2500"),
            defective_qty=Decimal("1.2500"),
            expired_qty=Decimal("0.5000"),
        )
        output = StringIO()

        call_command(
            "repair_inventory_aggregates",
            inventory_id=9911,
            item_id=9222,
            actor="SYNC_REPAIR",
            apply=True,
            stdout=output,
        )

        inventory = Inventory.objects.get(inventory_id=9911, item_id=9222)
        self.assertEqual(inventory.usable_qty, Decimal("75.50"))
        self.assertEqual(inventory.reserved_qty, Decimal("10.25"))
        self.assertEqual(inventory.defective_qty, Decimal("1.25"))
        self.assertEqual(inventory.expired_qty, Decimal("0.50"))
        self.assertEqual(inventory.update_by_id, "SYNC_REPAIR")
        self.assertEqual(inventory.version_nbr, 1)
        self.assertIn("applied action: create", output.getvalue())

    def test_apply_is_noop_when_inventory_aggregate_is_already_reconciled(self) -> None:
        self._create_inventory(
            inventory_id=9922,
            item_id=9333,
            usable_qty=Decimal("15.5000"),
            reserved_qty=Decimal("2.2500"),
            defective_qty=Decimal("1.0000"),
            expired_qty=Decimal("0.5000"),
        )
        self._create_batch(
            inventory_id=9922,
            item_id=9333,
            batch_id=995222,
            usable_qty=Decimal("15.5000"),
            reserved_qty=Decimal("2.2500"),
            defective_qty=Decimal("1.0000"),
            expired_qty=Decimal("0.5000"),
        )
        output = StringIO()

        call_command(
            "repair_inventory_aggregates",
            inventory_id=9922,
            item_id=9333,
            apply=True,
            stdout=output,
        )

        inventory = Inventory.objects.get(inventory_id=9922, item_id=9333)
        self.assertEqual(inventory.version_nbr, 1)
        self.assertIn("planned action: noop", output.getvalue())
        self.assertIn("No repairs needed.", output.getvalue())
        self.assertIn("applied action: noop", output.getvalue())


class ReleasePackageLockCommandTests(TestCase):
    resolver_path = "operations.contract_services._resolve_request_level_fulfillment_tenant_id"

    def setUp(self) -> None:
        super().setUp()
        self.resolver_patch = patch(self.resolver_path, return_value=27)
        self.resolver_patch.start()
        self.addCleanup(self.resolver_patch.stop)

    def _create_request(self, *, relief_request_id: int = 95009, request_no: str = "RQ95009") -> OperationsReliefRequest:
        return OperationsReliefRequest.objects.create(
            relief_request_id=relief_request_id,
            request_no=request_no,
            requesting_tenant_id=19,
            requesting_agency_id=401,
            beneficiary_tenant_id=19,
            beneficiary_agency_id=501,
            origin_mode="SELF",
            event_id=12,
            request_date=date(2026, 4, 7),
            urgency_code="H",
            status_code=REQUEST_STATUS_APPROVED_FOR_FULFILLMENT,
            create_by_id="tester",
            update_by_id="tester",
        )

    def _create_package(
        self,
        *,
        request_record: OperationsReliefRequest,
        package_id: int = 95027,
    ) -> OperationsPackage:
        return OperationsPackage.objects.create(
            package_id=package_id,
            package_no=f"PK{package_id}",
            relief_request=request_record,
            source_warehouse_id=4,
            destination_tenant_id=request_record.beneficiary_tenant_id,
            destination_agency_id=request_record.beneficiary_agency_id,
            status_code="COMMITTED",
            create_by_id="tester",
            update_by_id="tester",
        )

    def _create_lock(self, *, package_record: OperationsPackage) -> OperationsPackageLock:
        return OperationsPackageLock.objects.create(
            package=package_record,
            lock_owner_user_id="kemar_tst",
            lock_owner_role_code=ROLE_LOGISTICS_MANAGER,
            lock_started_at=timezone.now() - timedelta(minutes=2),
            lock_expires_at=timezone.now() + timedelta(minutes=30),
            lock_status="ACTIVE",
        )

    def test_dry_run_shows_lock_details_and_does_not_persist(self) -> None:
        request_record = self._create_request()
        package_record = self._create_package(request_record=request_record)
        lock = self._create_lock(package_record=package_record)
        output = StringIO()

        call_command("release_package_lock", request_no="RQ95009", stdout=output)

        lock.refresh_from_db()
        text = output.getvalue()
        self.assertIn("Package lock release:", text)
        self.assertIn("RQ95009", text)
        self.assertIn("PK95027", text)
        self.assertIn("active_lock: yes", text)
        self.assertIn("Dry-run only", text)
        self.assertEqual(lock.lock_status, "ACTIVE")

    def test_apply_releases_active_lock(self) -> None:
        request_record = self._create_request()
        package_record = self._create_package(request_record=request_record)
        lock = self._create_lock(package_record=package_record)
        output = StringIO()

        call_command("release_package_lock", package_id=95027, actor="SYSTEM", apply=True, stdout=output)

        lock.refresh_from_db()
        self.assertEqual(lock.lock_status, "RELEASED")
        self.assertLessEqual(lock.lock_expires_at, timezone.now())
        self.assertEqual(
            OperationsNotification.objects.get(
                queue_code=QUEUE_CODE_FULFILLMENT,
                entity_type="PACKAGE",
                entity_id=95027,
                recipient_user_id="kemar_tst",
            ).recipient_tenant_id,
            27,
        )
        text = output.getvalue()
        self.assertIn("Package lock released.", text)
        self.assertIn("released: True", text)

    def test_apply_is_noop_when_no_active_lock_exists(self) -> None:
        request_record = self._create_request()
        self._create_package(request_record=request_record)
        output = StringIO()

        call_command("release_package_lock", request_no="RQ95009", apply=True, stdout=output)

        text = output.getvalue()
        self.assertIn("No active package lock found for this package.", text)
        self.assertIn("released: False", text)

    def test_request_no_without_package_raises_command_error(self) -> None:
        self._create_request()

        with self.assertRaisesRegex(CommandError, "No package found for request_no=RQ95009."):
            call_command("release_package_lock", request_no="RQ95009")

    def test_request_no_with_multiple_packages_requires_package_id(self) -> None:
        request_record = self._create_request()
        self._create_package(request_record=request_record, package_id=95027)
        self._create_package(request_record=request_record, package_id=95028)

        with self.assertRaisesRegex(
            CommandError,
            "Multiple packages found for request_no=RQ95009. Specify --package-id.",
        ):
            call_command("release_package_lock", request_no="RQ95009")


class ResetPackageAllocationsCommandTests(TestCase):
    def _create_request(self, *, relief_request_id: int = 95009, request_no: str = "RQ95009") -> OperationsReliefRequest:
        return OperationsReliefRequest.objects.create(
            relief_request_id=relief_request_id,
            request_no=request_no,
            requesting_tenant_id=19,
            requesting_agency_id=401,
            beneficiary_tenant_id=19,
            beneficiary_agency_id=501,
            origin_mode="SELF",
            event_id=12,
            request_date=date(2026, 4, 7),
            urgency_code="H",
            status_code=REQUEST_STATUS_APPROVED_FOR_FULFILLMENT,
            create_by_id="tester",
            update_by_id="tester",
        )

    def _create_package(self, *, request_record: OperationsReliefRequest) -> OperationsPackage:
        return OperationsPackage.objects.create(
            package_id=95027,
            package_no="PK95027",
            relief_request=request_record,
            source_warehouse_id=4,
            destination_tenant_id=request_record.beneficiary_tenant_id,
            destination_agency_id=request_record.beneficiary_agency_id,
            status_code="DRAFT",
            create_by_id="tester",
            update_by_id="tester",
        )

    @patch(
        "operations.management.commands.reset_package_allocations.Command._legacy_allocation_line_count",
        return_value=1,
    )
    def test_dry_run_shows_current_allocation_counts(self, _legacy_count_mock) -> None:
        request_record = self._create_request()
        package_record = self._create_package(request_record=request_record)
        OperationsPackageLock.objects.create(
            package=package_record,
            lock_owner_user_id="kemar_tst",
            lock_owner_role_code=ROLE_LOGISTICS_MANAGER,
            lock_status="ACTIVE",
        )
        OperationsAllocationLine.objects.create(
            package=package_record,
            item_id=101,
            source_warehouse_id=1,
            batch_id=1001,
            quantity="2.0000",
            source_type="ON_HAND",
            create_by_id="tester",
            update_by_id="tester",
        )
        output = StringIO()

        call_command("reset_package_allocations", request_no="RQ95009", stdout=output)

        text = output.getvalue()
        self.assertIn("Package allocation reset:", text)
        self.assertIn("operations_allocation_lines: 1", text)
        self.assertIn("legacy_allocation_lines: 1", text)
        self.assertIn("Dry-run only", text)

    @patch("operations.management.commands.reset_package_allocations.contract_services.reset_package_allocations")
    def test_apply_delegates_to_cleanup_service(self, reset_mock) -> None:
        request_record = self._create_request()
        self._create_package(request_record=request_record)
        reset_mock.return_value = {
            "status": "DRAFT",
            "operations_allocation_lines_deleted": 3,
            "legacy_allocation_lines_deleted": 2,
            "released_stock_summary": {"line_count": 3, "total_qty": "450.0000"},
        }
        output = StringIO()

        call_command("reset_package_allocations", request_no="RQ95009", apply=True, stdout=output)

        reset_mock.assert_called_once_with(95027, actor_id="SYSTEM")
        text = output.getvalue()
        self.assertIn("Package allocations reset.", text)
        self.assertIn("operations_allocation_lines_deleted: 3", text)
        self.assertIn("released_stock_total_qty: 450.0000", text)
