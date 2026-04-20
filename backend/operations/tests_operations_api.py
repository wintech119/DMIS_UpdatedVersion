from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from django.core.cache import cache
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from rest_framework.response import Response
from rest_framework.test import APIClient

from api.authentication import Principal
from api.rbac import (
    PERM_OPERATIONS_PACKAGE_OVERRIDE_APPROVE,
    PERM_OPERATIONS_REQUEST_CREATE_SELF,
    PERM_OPERATIONS_REQUEST_EDIT_DRAFT,
)
from api.tenancy import TenantContext, TenantMembership
from operations.exceptions import OperationValidationError
from operations.models import OperationsReliefRequest
from operations import views as operations_views
from replenishment.services.allocation_dispatch import InventoryDriftError


@override_settings(
    AUTH_ENABLED=False,
    DEV_AUTH_ENABLED=True,
    TEST_DEV_AUTH_ENABLED=True,
    DEV_AUTH_USER_ID="ops-dev",
    DEV_AUTH_ROLES=["SYSTEM_ADMINISTRATOR"],
    DEV_AUTH_PERMISSIONS=[],
    DEBUG=True,
    AUTH_USE_DB_RBAC=False,
)
class OperationsApiTests(SimpleTestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        cache.clear()
        active_event_patcher = patch("operations.views.data_access.get_active_event", return_value={})
        active_event_patcher.start()
        self.addCleanup(active_event_patcher.stop)

    def tearDown(self) -> None:
        cache.clear()

    @patch(
        "operations.views.resolve_roles_and_permissions",
        return_value=(
            ["SYSTEM_ADMINISTRATOR"],
            [PERM_OPERATIONS_REQUEST_CREATE_SELF, PERM_OPERATIONS_REQUEST_EDIT_DRAFT],
        ),
    )
    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch(
        "operations.views.operations_service.get_request_reference_data",
        return_value={"agencies": [{"value": 5, "label": "FFP Shelter"}], "events": [], "items": []},
    )
    @patch("operations.views.operations_service.submit_request", return_value={"reliefrqst_id": 70, "status_label": "Awaiting Approval"})
    @patch("operations.views.operations_service.update_request", return_value={"reliefrqst_id": 70, "status_label": "Draft"})
    @patch("operations.views.operations_service.create_request", return_value={"reliefrqst_id": 70, "tracking_no": "RQ00070"})
    @patch("operations.views.operations_service.get_request", return_value={"reliefrqst_id": 70, "tracking_no": "RQ00070"})
    @patch("operations.views.operations_service.list_requests", return_value={"results": [{"reliefrqst_id": 70, "tracking_no": "RQ00070"}]})
    def test_request_contracts_forward_request_id_actor_and_payload(
        self,
        mock_list,
        mock_get,
        mock_create,
        mock_update,
        mock_submit,
        mock_reference_data,
        _mock_permission,
        mock_tenant_context,
        _mock_roles,
    ) -> None:
        list_response = self.client.get("/api/v1/operations/requests")
        detail_response = self.client.get("/api/v1/operations/requests/70")
        references_response = self.client.get("/api/v1/operations/requests/reference-data")
        create_response = self.client.post(
            "/api/v1/operations/requests",
            {"agency_id": 5, "urgency_ind": "H", "items": [{"item_id": 101, "request_qty": "3"}]},
            format="json",
        )
        update_response = self.client.patch(
            "/api/v1/operations/requests/70",
            {"rqst_notes_text": "Updated note"},
            format="json",
        )
        submit_response = self.client.post(
            "/api/v1/operations/requests/70/submit",
            {},
            format="json",
            HTTP_IDEMPOTENCY_KEY="submit-70",
        )

        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(references_response.status_code, 200)
        self.assertEqual(create_response.status_code, 201)
        self.assertEqual(update_response.status_code, 200)
        self.assertEqual(submit_response.status_code, 200)
        self.assertEqual(mock_list.call_args.kwargs["filter_key"], None)
        self.assertEqual(mock_list.call_args.kwargs["actor_id"], "ops-dev")
        self.assertEqual(mock_list.call_args.kwargs["tenant_context"].active_tenant_id, 20)
        self.assertEqual(mock_list.call_args.kwargs["actor_roles"], ["SYSTEM_ADMINISTRATOR"])
        self.assertEqual(mock_get.call_args.kwargs["actor_id"], "ops-dev")
        self.assertEqual(mock_get.call_args.kwargs["tenant_context"].active_tenant_id, 20)
        self.assertEqual(mock_get.call_args.kwargs["actor_roles"], ["SYSTEM_ADMINISTRATOR"])
        self.assertEqual(mock_reference_data.call_args.kwargs["tenant_context"].active_tenant_id, 20)
        self.assertEqual(
            mock_reference_data.call_args.kwargs["permissions"],
            [PERM_OPERATIONS_REQUEST_CREATE_SELF, PERM_OPERATIONS_REQUEST_EDIT_DRAFT],
        )
        self.assertEqual(mock_create.call_args.kwargs["actor_id"], "ops-dev")
        self.assertEqual(mock_create.call_args.kwargs["payload"]["agency_id"], 5)
        self.assertEqual(mock_create.call_args.kwargs["tenant_context"].active_tenant_id, 20)
        self.assertEqual(mock_create.call_args.kwargs["permissions"], [PERM_OPERATIONS_REQUEST_CREATE_SELF, PERM_OPERATIONS_REQUEST_EDIT_DRAFT])
        self.assertEqual(mock_update.call_args.kwargs["actor_id"], "ops-dev")
        self.assertEqual(mock_update.call_args.kwargs["payload"]["rqst_notes_text"], "Updated note")
        self.assertEqual(mock_update.call_args.kwargs["tenant_context"].active_tenant_id, 20)
        self.assertEqual(mock_update.call_args.kwargs["permissions"], [PERM_OPERATIONS_REQUEST_CREATE_SELF, PERM_OPERATIONS_REQUEST_EDIT_DRAFT])
        self.assertEqual(mock_submit.call_args.kwargs["tenant_context"].active_tenant_id, 20)
        self.assertEqual(mock_submit.call_args.kwargs["idempotency_key"], "submit-70")

    @patch("operations.views.resolve_roles_and_permissions", return_value=(["ODPEM_DG"], []))
    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=1))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.operations_service.submit_eligibility_decision", return_value={"reliefrqst_id": 80, "status_label": "Submitted"})
    @patch("operations.views.operations_service.get_eligibility_request", return_value={"reliefrqst_id": 80, "decision_made": False})
    @patch("operations.views.operations_service.list_eligibility_queue", return_value={"results": [{"reliefrqst_id": 80}]})
    def test_eligibility_contracts_forward_decision_payload(
        self,
        mock_list,
        mock_get,
        mock_decide,
        _mock_permission,
        mock_tenant_context,
        _mock_roles,
    ) -> None:
        queue_response = self.client.get("/api/v1/operations/eligibility/queue")
        detail_response = self.client.get("/api/v1/operations/eligibility/80")
        decide_response = self.client.post(
            "/api/v1/operations/eligibility/80/decision",
            {"decision": "Y", "reason": "Eligible"},
            format="json",
            HTTP_IDEMPOTENCY_KEY="eligibility-80",
        )

        self.assertEqual(queue_response.status_code, 200)
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(decide_response.status_code, 200)
        self.assertEqual(mock_list.call_args.kwargs["actor_id"], "ops-dev")
        self.assertIs(mock_list.call_args.kwargs["tenant_context"], mock_tenant_context.return_value)
        self.assertEqual(mock_list.call_args.kwargs["actor_roles"], ["ODPEM_DG"])
        self.assertEqual(mock_get.call_args.kwargs["actor_id"], "ops-dev")
        self.assertIs(mock_get.call_args.kwargs["tenant_context"], mock_tenant_context.return_value)
        self.assertEqual(mock_get.call_args.kwargs["actor_roles"], ["ODPEM_DG"])
        self.assertEqual(mock_decide.call_args.kwargs["payload"]["decision"], "Y")
        self.assertEqual(mock_decide.call_args.kwargs["actor_id"], "ops-dev")
        self.assertEqual(mock_decide.call_args.kwargs["actor_roles"], ["ODPEM_DG"])
        self.assertIs(mock_decide.call_args.kwargs["tenant_context"], mock_tenant_context.return_value)
        self.assertEqual(mock_decide.call_args.kwargs["idempotency_key"], "eligibility-80")

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["LOGISTICS_MANAGER"], []))
    @patch("operations.views.operations_service.cancel_package", return_value={"status": "CANCELLED"})
    @patch("operations.views.operations_service.list_tasks", return_value={"queue_assignments": [], "notifications": []})
    @patch("operations.views.operations_service.confirm_receipt", return_value={"status": "RECEIVED", "reliefpkg_id": 90})
    @patch("operations.views.operations_service.get_waybill", return_value={"waybill_no": "WB-PK00090"})
    @patch("operations.views.operations_service.submit_dispatch", return_value={"reliefpkg_id": 90, "waybill_no": "WB-PK00090"})
    @patch("operations.views.operations_service.get_dispatch_package", return_value={"reliefpkg_id": 90, "status_label": "Dispatched"})
    @patch("operations.views.operations_service.list_dispatch_queue", return_value={"results": [{"reliefpkg_id": 90}]})
    @patch("operations.views.operations_service.approve_override", return_value={"reliefrqst_id": 70, "status": "COMMITTED"})
    @patch("operations.views.operations_service.save_package", return_value={"reliefrqst_id": 70, "status": "COMMITTED"})
    @patch("operations.views.operations_service.get_package_allocation_options", return_value={"items": [{"item_id": 101}]})
    @patch("operations.views.operations_service.get_package", return_value={"request": {"reliefrqst_id": 70}, "package": {"reliefpkg_id": 90}})
    @patch("operations.views.operations_service.list_packages", return_value={"results": [{"reliefrqst_id": 70}]})
    def test_package_and_dispatch_contracts_forward_real_ids(
        self,
        mock_list_packages,
        mock_get_package,
        mock_options,
        mock_save,
        mock_override,
        mock_dispatch_queue,
        mock_dispatch_detail,
        mock_submit_dispatch,
        mock_waybill,
        mock_receipt,
        mock_tasks,
        mock_cancel_package,
        _mock_roles,
        _mock_permission,
        mock_tenant_context,
    ) -> None:
        packages_response = self.client.get("/api/v1/operations/packages/queue")
        package_detail_response = self.client.get("/api/v1/operations/packages/70")
        options_response = self.client.get("/api/v1/operations/packages/70/allocation-options?source_warehouse_id=1")
        draft_response = self.client.post("/api/v1/operations/packages/70/draft", {"comments_text": "Prep"}, format="json")
        commit_response = self.client.post(
            "/api/v1/operations/packages/70/allocations/commit",
            {"allocations": [{"item_id": 101, "inventory_id": 1, "batch_id": 1001, "quantity": "2"}]},
            format="json",
            HTTP_IDEMPOTENCY_KEY="commit-70",
        )
        override_response = self.client.post(
            "/api/v1/operations/packages/70/allocations/override-approve",
            {"allocations": [{"item_id": 101, "inventory_id": 1, "batch_id": 1001, "quantity": "2"}], "override_reason_code": "FEFO_BYPASS", "override_note": "Approved"},
            format="json",
            HTTP_IDEMPOTENCY_KEY="override-70",
        )
        dispatch_queue_response = self.client.get("/api/v1/operations/dispatch/queue")
        dispatch_detail_response = self.client.get("/api/v1/operations/dispatch/90")
        dispatch_submit_response = self.client.post(
            "/api/v1/operations/dispatch/90/handoff",
            {
                "transport_mode": "TRUCK",
                "driver_name": "Jane Driver",
                "vehicle_registration": "1234AB",
                "departure_dtime": "2026-03-26T10:00:00Z",
                "estimated_arrival_dtime": "2026-03-26T13:00:00Z",
            },
            format="json",
            HTTP_IDEMPOTENCY_KEY="dispatch-90",
        )
        waybill_response = self.client.get("/api/v1/operations/dispatch/90/waybill")
        receipt_response = self.client.post(
            "/api/v1/operations/receipt-confirmation/90",
            {"received_by_name": "Receiver"},
            format="json",
            HTTP_IDEMPOTENCY_KEY="receipt-90",
        )
        cancel_response = self.client.post(
            "/api/v1/operations/packages/90/cancel",
            {},
            format="json",
            HTTP_IDEMPOTENCY_KEY="cancel-90",
        )
        tasks_response = self.client.get("/api/v1/operations/tasks")

        self.assertEqual(packages_response.status_code, 200)
        self.assertEqual(package_detail_response.status_code, 200)
        self.assertEqual(options_response.status_code, 200)
        self.assertEqual(draft_response.status_code, 200)
        self.assertEqual(commit_response.status_code, 200)
        self.assertEqual(override_response.status_code, 200)
        self.assertEqual(dispatch_queue_response.status_code, 200)
        self.assertEqual(dispatch_detail_response.status_code, 200)
        self.assertEqual(dispatch_submit_response.status_code, 200)
        self.assertEqual(waybill_response.status_code, 200)
        self.assertEqual(receipt_response.status_code, 200)
        self.assertEqual(cancel_response.status_code, 200)
        self.assertEqual(tasks_response.status_code, 200)
        self.assertEqual(mock_list_packages.call_args.kwargs["actor_id"], "ops-dev")
        self.assertEqual(mock_list_packages.call_args.kwargs["actor_roles"], ["LOGISTICS_MANAGER"])
        self.assertEqual(mock_list_packages.call_args.kwargs["tenant_context"].active_tenant_id, 20)
        self.assertEqual(mock_get_package.call_args.kwargs["actor_id"], "ops-dev")
        self.assertEqual(mock_get_package.call_args.kwargs["actor_roles"], ["LOGISTICS_MANAGER"])
        self.assertEqual(mock_get_package.call_args.kwargs["tenant_context"].active_tenant_id, 20)
        self.assertEqual(mock_options.call_args.kwargs["source_warehouse_id"], 1)
        self.assertEqual(mock_save.call_count, 2)
        self.assertEqual(mock_save.call_args_list[0].kwargs["payload"]["comments_text"], "Prep")
        self.assertIs(mock_save.call_args_list[0].kwargs["payload"]["draft_save"], True)
        self.assertEqual(mock_save.call_args_list[1].kwargs["payload"]["allocations"][0]["item_id"], 101)
        self.assertFalse(mock_save.call_args_list[1].kwargs["payload"].get("draft_save", False))
        self.assertEqual(mock_save.call_args_list[0].kwargs["tenant_context"].active_tenant_id, 20)
        self.assertEqual(mock_save.call_args_list[0].kwargs["permissions"], [])
        self.assertEqual(mock_save.call_args_list[1].kwargs["permissions"], [])
        self.assertEqual(mock_save.call_args_list[1].kwargs["idempotency_key"], "commit-70")
        self.assertEqual(mock_override.call_args.kwargs["actor_roles"], ["LOGISTICS_MANAGER"])
        self.assertEqual(mock_override.call_args.kwargs["tenant_context"].active_tenant_id, 20)
        self.assertEqual(mock_override.call_args.kwargs["idempotency_key"], "override-70")
        self.assertEqual(mock_dispatch_queue.call_args.kwargs["actor_id"], "ops-dev")
        self.assertEqual(mock_dispatch_queue.call_args.kwargs["actor_roles"], ["LOGISTICS_MANAGER"])
        self.assertEqual(mock_dispatch_queue.call_args.kwargs["tenant_context"].active_tenant_id, 20)
        self.assertEqual(mock_dispatch_detail.call_args.kwargs["actor_id"], "ops-dev")
        self.assertEqual(mock_dispatch_detail.call_args.kwargs["actor_roles"], ["LOGISTICS_MANAGER"])
        self.assertEqual(mock_dispatch_detail.call_args.kwargs["tenant_context"].active_tenant_id, 20)
        self.assertEqual(mock_submit_dispatch.call_args.kwargs["payload"]["transport_mode"], "TRUCK")
        self.assertEqual(mock_submit_dispatch.call_args.kwargs["payload"]["driver_name"], "Jane Driver")
        self.assertEqual(mock_submit_dispatch.call_args.kwargs["tenant_context"].active_tenant_id, 20)
        self.assertEqual(mock_submit_dispatch.call_args.kwargs["idempotency_key"], "dispatch-90")
        self.assertEqual(mock_waybill.call_args.kwargs["actor_id"], "ops-dev")
        self.assertEqual(mock_waybill.call_args.kwargs["tenant_context"].active_tenant_id, 20)
        self.assertEqual(mock_receipt.call_args.kwargs["payload"]["received_by_name"], "Receiver")
        self.assertEqual(mock_receipt.call_args.kwargs["tenant_context"].active_tenant_id, 20)
        self.assertEqual(mock_receipt.call_args.kwargs["idempotency_key"], "receipt-90")
        self.assertEqual(mock_cancel_package.call_args.args[0], 90)
        self.assertEqual(mock_cancel_package.call_args.kwargs["actor_roles"], ["LOGISTICS_MANAGER"])
        self.assertEqual(mock_cancel_package.call_args.kwargs["tenant_context"].active_tenant_id, 20)
        self.assertEqual(mock_cancel_package.call_args.kwargs["idempotency_key"], "cancel-90")
        self.assertEqual(mock_tasks.call_args.kwargs["actor_roles"], ["LOGISTICS_MANAGER"])

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["LOGISTICS_MANAGER"], []))
    @patch("operations.views.operations_service.abandon_package_draft", return_value={"status": "DRAFT", "abandoned": True})
    def test_package_abandon_draft_forwards_idempotency_key(
        self,
        mock_abandon_package_draft,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        response = self.client.post(
            "/api/v1/operations/packages/90/abandon-draft",
            {"reason": "Release draft lock"},
            format="json",
            HTTP_IDEMPOTENCY_KEY="abandon-90",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_abandon_package_draft.call_args.args[0], 90)
        self.assertEqual(mock_abandon_package_draft.call_args.kwargs["payload"]["reason"], "Release draft lock")
        self.assertEqual(mock_abandon_package_draft.call_args.kwargs["actor_roles"], ["LOGISTICS_MANAGER"])
        self.assertEqual(mock_abandon_package_draft.call_args.kwargs["tenant_context"].active_tenant_id, 20)
        self.assertEqual(mock_abandon_package_draft.call_args.kwargs["idempotency_key"], "abandon-90")

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["LOGISTICS_MANAGER"], []))
    @patch("operations.views.data_access.get_active_event", return_value=None)
    @patch(
        "operations.views.operations_service.return_override",
        return_value={
            "reliefrqst_id": 70,
            "status": "DRAFT",
            "override_status_code": "RETURNED_FOR_ADJUSTMENT",
        },
    )
    def test_package_override_return_forwards_payload_actor_tenant_and_idempotency_key(
        self,
        mock_return_override,
        _mock_active_event,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        response = self.client.post(
            "/api/v1/operations/packages/70/allocations/override-return",
            {"reason": "Adjust allocations to follow compliant stock order."},
            format="json",
            HTTP_IDEMPOTENCY_KEY="override-return-70",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_return_override.call_args.args[0], 70)
        self.assertEqual(
            mock_return_override.call_args.kwargs["payload"]["reason"],
            "Adjust allocations to follow compliant stock order.",
        )
        self.assertEqual(mock_return_override.call_args.kwargs["actor_id"], "ops-dev")
        self.assertEqual(mock_return_override.call_args.kwargs["actor_roles"], ["LOGISTICS_MANAGER"])
        self.assertEqual(mock_return_override.call_args.kwargs["tenant_context"].active_tenant_id, 20)
        self.assertEqual(mock_return_override.call_args.kwargs["idempotency_key"], "override-return-70")

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["LOGISTICS_MANAGER"], []))
    @patch(
        "operations.views.operations_service.save_package",
        side_effect=InventoryDriftError(
            "Inventory aggregate for item 195 at inventory 1 is out of sync with batch stock. Batch 95015 can cover 2.0000, but the warehouse aggregate shows only 0.0000. Reconcile the inventory row before committing the reservation."
        ),
    )
    def test_commit_allocation_returns_conflict_for_inventory_drift_errors(
        self,
        _mock_save_package,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        response = self.client.post(
            "/api/v1/operations/packages/70/allocations/commit",
            {"allocations": [{"item_id": 101, "inventory_id": 1, "batch_id": 1001, "quantity": "2"}]},
            format="json",
            HTTP_IDEMPOTENCY_KEY="11f91359-d448-4b5a-b4fd-f2345a5d040b",
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json(),
            {
                "errors": {
                    "allocations": (
                        "Inventory aggregate for item 195 at inventory 1 is out of sync with batch stock. "
                        "Batch 95015 can cover 2.0000, but the warehouse aggregate shows only 0.0000. "
                        "Reconcile the inventory row before committing the reservation."
                    )
                }
            },
        )

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch(
        "operations.views.resolve_roles_and_permissions",
        return_value=(["LOGISTICS_MANAGER"], [PERM_OPERATIONS_PACKAGE_OVERRIDE_APPROVE]),
    )
    @patch(
        "operations.views.operations_service.release_package_lock",
        return_value={
            "released": True,
            "package_id": 90,
            "package_no": "PK00090",
            "previous_lock_owner_user_id": "kemar_tst",
            "previous_lock_owner_role_code": "LOGISTICS_OFFICER",
            "released_by_user_id": "ops-dev",
            "released_at": "2026-04-07T15:11:00Z",
            "lock_status": "RELEASED",
            "lock_expires_at": "2026-04-07T15:11:00Z",
            "message": "Package lock released.",
        },
    )
    def test_package_unlock_contract_forwards_force_flag_and_returns_payload(
        self,
        mock_unlock,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        response = self.client.post("/api/v1/operations/packages/70/unlock", {"force": True}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["released"])
        self.assertEqual(response.json()["package_no"], "PK00090")
        self.assertEqual(mock_unlock.call_args.args[0], 70)
        self.assertEqual(mock_unlock.call_args.kwargs["actor_id"], "ops-dev")
        self.assertEqual(mock_unlock.call_args.kwargs["actor_roles"], ["LOGISTICS_MANAGER"])
        self.assertEqual(mock_unlock.call_args.kwargs["tenant_context"].active_tenant_id, 20)
        self.assertTrue(mock_unlock.call_args.kwargs["force"])

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["LOGISTICS_MANAGER"], []))
    @patch("operations.views.operations_service.release_package_lock")
    def test_package_unlock_rejects_non_object_payloads(
        self,
        mock_unlock,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        response = self.client.post("/api/v1/operations/packages/70/unlock", ["force"], format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["errors"]["body"], "Request body must be a JSON object.")
        mock_unlock.assert_not_called()

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["LOGISTICS_MANAGER"], []))
    @patch("operations.views.operations_service.release_package_lock")
    def test_package_unlock_rejects_force_without_override_permission(
        self,
        mock_unlock,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        response = self.client.post("/api/v1/operations/packages/70/unlock", {"force": True}, format="json")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json(),
            {"errors": {"force": "Override approval permission is required to force-release a package lock."}},
        )
        mock_unlock.assert_not_called()

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["LOGISTICS_MANAGER"], []))
    @patch("operations.views.operations_service.save_package")
    def test_package_draft_rejects_non_object_payloads(
        self,
        mock_save_package,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        response = self.client.post("/api/v1/operations/packages/70/draft", ["not-an-object"], format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["errors"]["body"], "Request body must be a JSON object.")
        mock_save_package.assert_not_called()

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["LOGISTICS_MANAGER"], []))
    @patch(
        "operations.views.operations_service.get_item_allocation_options",
        return_value={
            "item_id": 101,
            "source_warehouse_id": 7,
            "selected_warehouse_ids": [7, 5],
            "recommended_warehouse_id": 7,
            "remaining_shortfall_qty": "6.0000",
            "continuation_recommended": True,
            "alternate_warehouses": [
                {
                    "warehouse_id": 1,
                    "warehouse_name": "Warehouse 1",
                    "available_qty": "4.0000",
                    "suggested_qty": "4.0000",
                    "can_fully_cover": False,
                }
            ],
        },
    )
    def test_item_allocation_options_forwards_optional_source_and_continuation_ids(
        self,
        mock_item_options,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        response = self.client.get(
            "/api/v1/operations/packages/70/allocation-options/101"
            "?source_warehouse_id=7&additional_warehouse_ids=5"
            "&additional_warehouse_ids=2&additional_warehouse_ids=5"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["remaining_shortfall_qty"], "6.0000")
        self.assertTrue(response.json()["continuation_recommended"])
        self.assertEqual(response.json()["selected_warehouse_ids"], [7, 5])
        self.assertEqual(response.json()["recommended_warehouse_id"], 7)
        self.assertEqual(response.json()["alternate_warehouses"][0]["warehouse_id"], 1)
        self.assertEqual(mock_item_options.call_args.args[:2], (70, 101))
        self.assertEqual(mock_item_options.call_args.kwargs["source_warehouse_id"], 7)
        self.assertIsNone(mock_item_options.call_args.kwargs["draft_allocations"])
        self.assertEqual(mock_item_options.call_args.kwargs["additional_warehouse_ids"], [5, 2])
        self.assertEqual(mock_item_options.call_args.kwargs["actor_id"], "ops-dev")
        self.assertEqual(mock_item_options.call_args.kwargs["actor_roles"], ["LOGISTICS_MANAGER"])
        self.assertEqual(mock_item_options.call_args.kwargs["tenant_context"].active_tenant_id, 20)

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["LOGISTICS_MANAGER"], []))
    @patch("operations.views.operations_service.pickup_release", return_value={"status": "RECEIVED"})
    @patch("operations.views.operations_service.approve_partial_release", return_value={"status": "APPROVED"})
    @patch("operations.views.operations_service.request_partial_release", return_value={"status": "PARTIAL_RELEASE_REQUESTED"})
    @patch("operations.views.operations_service.get_consolidation_leg_waybill", return_value={"waybill_no": "PK00090-L01"})
    @patch("operations.views.operations_service.receive_consolidation_leg", return_value={"status": "RECEIVED_AT_STAGING"})
    @patch("operations.views.operations_service.dispatch_consolidation_leg", return_value={"status": "IN_TRANSIT"})
    @patch("operations.views.operations_service.list_consolidation_legs", return_value={"results": [{"leg_id": 301}]})
    @patch("operations.views.operations_service.get_staging_recommendation", return_value={"recommended_staging_warehouse_id": 55})
    def test_staged_fulfillment_contracts_forward_ids_and_payloads(
        self,
        mock_staging_recommendation,
        mock_list_legs,
        mock_dispatch_leg,
        mock_receive_leg,
        mock_leg_waybill,
        mock_partial_request,
        mock_partial_approve,
        mock_pickup_release,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        recommendation_response = self.client.get("/api/v1/operations/packages/70/staging-recommendation")
        legs_response = self.client.get("/api/v1/operations/packages/90/consolidation-legs")
        dispatch_leg_response = self.client.post(
            "/api/v1/operations/packages/90/consolidation-legs/301/dispatch",
            {"driver_name": "Jane Driver", "vehicle_registration": "1234AB"},
            format="json",
            HTTP_IDEMPOTENCY_KEY="dispatch-leg-301",
        )
        receive_leg_response = self.client.post(
            "/api/v1/operations/packages/90/consolidation-legs/301/receive",
            {"received_by_name": "Receiver"},
            format="json",
            HTTP_IDEMPOTENCY_KEY="receive-leg-301",
        )
        leg_waybill_response = self.client.get("/api/v1/operations/packages/90/consolidation-legs/301/waybill")
        partial_request_response = self.client.post(
            "/api/v1/operations/packages/90/partial-release/request",
            {"reason": "Release received legs now"},
            format="json",
            HTTP_IDEMPOTENCY_KEY="partial-request-90",
        )
        partial_approve_response = self.client.post(
            "/api/v1/operations/packages/90/partial-release/approve",
            {"approval_reason": "Approved"},
            format="json",
            HTTP_IDEMPOTENCY_KEY="partial-approve-90",
        )
        pickup_release_response = self.client.post(
            "/api/v1/operations/packages/90/pickup-release",
            {
                "collected_by_name": "Community Driver",
                "collected_by_id_ref": "NID-7788",
                "released_by_name": "Receiver",
                "release_notes": "Pickup at gate",
            },
            format="json",
            HTTP_IDEMPOTENCY_KEY="pickup-90",
        )

        self.assertEqual(recommendation_response.status_code, 200)
        self.assertEqual(legs_response.status_code, 200)
        self.assertEqual(dispatch_leg_response.status_code, 200)
        self.assertEqual(receive_leg_response.status_code, 200)
        self.assertEqual(leg_waybill_response.status_code, 200)
        self.assertEqual(partial_request_response.status_code, 200)
        self.assertEqual(partial_approve_response.status_code, 200)
        self.assertEqual(pickup_release_response.status_code, 200)

        self.assertEqual(mock_staging_recommendation.call_args.args[0], 70)
        self.assertEqual(mock_list_legs.call_args.args[0], 90)
        self.assertEqual(mock_dispatch_leg.call_args.args[:2], (90, 301))
        self.assertEqual(mock_dispatch_leg.call_args.kwargs["payload"]["driver_name"], "Jane Driver")
        self.assertEqual(mock_dispatch_leg.call_args.kwargs["idempotency_key"], "dispatch-leg-301")
        self.assertEqual(mock_receive_leg.call_args.args[:2], (90, 301))
        self.assertEqual(mock_receive_leg.call_args.kwargs["payload"]["received_by_name"], "Receiver")
        self.assertEqual(mock_receive_leg.call_args.kwargs["idempotency_key"], "receive-leg-301")
        self.assertEqual(mock_leg_waybill.call_args.args[:2], (90, 301))
        self.assertEqual(mock_partial_request.call_args.args[0], 90)
        self.assertEqual(mock_partial_request.call_args.kwargs["payload"]["reason"], "Release received legs now")
        self.assertEqual(mock_partial_request.call_args.kwargs["idempotency_key"], "partial-request-90")
        self.assertEqual(mock_partial_approve.call_args.args[0], 90)
        self.assertEqual(mock_partial_approve.call_args.kwargs["idempotency_key"], "partial-approve-90")
        self.assertEqual(mock_pickup_release.call_args.args[0], 90)
        self.assertEqual(mock_pickup_release.call_args.kwargs["payload"]["collected_by_name"], "Community Driver")
        self.assertEqual(mock_pickup_release.call_args.kwargs["payload"]["collected_by_id_ref"], "NID-7788")
        self.assertEqual(mock_pickup_release.call_args.kwargs["payload"]["released_by_name"], "Receiver")
        self.assertEqual(mock_pickup_release.call_args.kwargs["payload"]["release_notes"], "Pickup at gate")
        self.assertEqual(mock_pickup_release.call_args.kwargs["idempotency_key"], "pickup-90")

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["LOGISTICS_MANAGER"], []))
    @patch("operations.views.operations_service.get_package_allocation_options", return_value={"items": [{"item_id": 101}]})
    def test_package_allocation_options_allow_missing_source_warehouse_id(
        self,
        mock_options,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        response = self.client.get("/api/v1/operations/packages/70/allocation-options")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"items": [{"item_id": 101}]})
        mock_options.assert_called_once_with(
            70,
            source_warehouse_id=None,
            actor_id="ops-dev",
            actor_roles=["LOGISTICS_MANAGER"],
            tenant_context=SimpleNamespace(active_tenant_id=20),
        )

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["LOGISTICS_MANAGER"], []))
    @patch("operations.views.operations_service.get_package_allocation_options", return_value={"items": [{"item_id": 101}]})
    def test_package_allocation_options_reject_invalid_source_warehouse_id(
        self,
        mock_options,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        response = self.client.get("/api/v1/operations/packages/70/allocation-options?source_warehouse_id=abc")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"errors": {"source_warehouse_id": "Must be a positive integer."}})
        mock_options.assert_not_called()

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["LOGISTICS_MANAGER"], []))
    @patch(
        "operations.views.operations_service.get_item_allocation_options",
        return_value={"item_id": 101, "selected_warehouse_ids": [7], "recommended_warehouse_id": 7},
    )
    def test_item_allocation_options_allow_missing_source_warehouse_id(
        self,
        mock_item_options,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        response = self.client.get("/api/v1/operations/packages/70/allocation-options/101")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["recommended_warehouse_id"], 7)
        self.assertIsNone(mock_item_options.call_args.kwargs["source_warehouse_id"])
        self.assertEqual(mock_item_options.call_args.kwargs["additional_warehouse_ids"], [])

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["LOGISTICS_MANAGER"], []))
    @patch("operations.views.operations_service.get_item_allocation_options")
    def test_item_allocation_options_reject_invalid_source_warehouse_id(
        self,
        mock_item_options,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        response = self.client.get("/api/v1/operations/packages/70/allocation-options/101?source_warehouse_id=abc")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"errors": {"source_warehouse_id": "Must be a positive integer."}})
        mock_item_options.assert_not_called()

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["LOGISTICS_MANAGER"], []))
    @patch("operations.views.operations_service.get_item_allocation_options")
    def test_item_allocation_options_reject_invalid_additional_warehouse_ids(
        self,
        mock_item_options,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        response = self.client.get(
            "/api/v1/operations/packages/70/allocation-options/101"
            "?additional_warehouse_ids=5&additional_warehouse_ids=abc"
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {"errors": {"additional_warehouse_ids[1]": "Must be a positive integer."}},
        )
        mock_item_options.assert_not_called()

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["LOGISTICS_MANAGER"], []))
    @patch("operations.views.operations_service.get_item_allocation_options")
    def test_item_allocation_options_rejects_draft_allocations_query_param(
        self,
        mock_item_options,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        response = self.client.get(
            "/api/v1/operations/packages/70/allocation-options/101",
            {"source_warehouse_id": 1, "draft_allocations": "[]"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {"errors": {"draft_allocations": "Use the preview endpoint for draft-aware allocation guidance."}},
        )
        mock_item_options.assert_not_called()

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["LOGISTICS_MANAGER"], []))
    @patch(
        "operations.views.operations_service.get_item_allocation_preview",
        return_value={
            "item_id": 101,
            "item_code": "MASK001",
            "item_name": "Face Mask",
            "request_qty": "12.0000",
            "issue_qty": "2.0000",
            "remaining_qty": "10.0000",
            "draft_selected_qty": "5.0000",
            "effective_remaining_qty": "5.0000",
            "urgency_ind": "H",
            "candidates": [],
            "suggested_allocations": [],
            "remaining_after_suggestion": "2.0000",
            "source_warehouse_id": 7,
            "selected_warehouse_ids": [7, 5],
            "recommended_warehouse_id": 7,
            "remaining_shortfall_qty": "2.0000",
            "continuation_recommended": True,
            "alternate_warehouses": [
                {
                    "warehouse_id": 5,
                    "warehouse_name": "Warehouse 5",
                    "available_qty": "4.0000",
                    "suggested_qty": "2.0000",
                    "can_fully_cover": True,
                }
            ],
        },
    )
    def test_item_allocation_preview_forwards_ids_and_payload(
        self,
        mock_preview,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        payload = {
            "source_warehouse_id": 7,
            "additional_warehouse_ids": [5, 2, 5],
            "draft_allocations": [
                {
                    "item_id": 101,
                    "inventory_id": 7,
                    "batch_id": 1001,
                    "quantity": "2.0000",
                    "source_type": "ON_HAND",
                    "source_record_id": None,
                }
            ],
        }

        response = self.client.post(
            "/api/v1/operations/packages/70/allocation-options/101/preview",
            payload,
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["remaining_qty"], "10.0000")
        self.assertEqual(response.json()["draft_selected_qty"], "5.0000")
        self.assertEqual(response.json()["effective_remaining_qty"], "5.0000")
        self.assertEqual(response.json()["selected_warehouse_ids"], [7, 5])
        self.assertEqual(mock_preview.call_args.args[:2], (70, 101))
        self.assertEqual(
            mock_preview.call_args.kwargs["payload"],
            {
                **payload,
                "additional_warehouse_ids": [5, 2],
            },
        )
        self.assertEqual(
            mock_preview.call_args.kwargs["source_warehouse_id"],
            payload["source_warehouse_id"],
        )
        self.assertEqual(
            mock_preview.call_args.kwargs["draft_allocations"],
            payload["draft_allocations"],
        )
        self.assertEqual(mock_preview.call_args.kwargs["additional_warehouse_ids"], [5, 2])
        self.assertEqual(mock_preview.call_args.kwargs["actor_id"], "ops-dev")
        self.assertEqual(mock_preview.call_args.kwargs["actor_roles"], ["LOGISTICS_MANAGER"])
        self.assertEqual(mock_preview.call_args.kwargs["tenant_context"].active_tenant_id, 20)

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["LOGISTICS_MANAGER"], []))
    @patch(
        "operations.views.operations_service.get_item_allocation_preview",
        return_value={"item_id": 101, "recommended_warehouse_id": 7, "selected_warehouse_ids": [7]},
    )
    def test_item_allocation_preview_allows_missing_source_warehouse_id(
        self,
        mock_preview,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        response = self.client.post(
            "/api/v1/operations/packages/70/allocation-options/101/preview",
            {"draft_allocations": [], "additional_warehouse_ids": [5, 5]},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["recommended_warehouse_id"], 7)
        self.assertIsNone(mock_preview.call_args.kwargs["source_warehouse_id"])
        self.assertEqual(mock_preview.call_args.kwargs["additional_warehouse_ids"], [5])

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["LOGISTICS_MANAGER"], []))
    def test_item_allocation_preview_rejects_invalid_source_warehouse_id(
        self,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        response = self.client.post(
            "/api/v1/operations/packages/70/allocation-options/101/preview",
            {"source_warehouse_id": "abc", "draft_allocations": []},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"errors": {"source_warehouse_id": "Must be a positive integer."}})

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["LOGISTICS_MANAGER"], []))
    def test_item_allocation_preview_rejects_invalid_additional_warehouse_ids(
        self,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        response = self.client.post(
            "/api/v1/operations/packages/70/allocation-options/101/preview",
            {"additional_warehouse_ids": ["5", "abc"], "draft_allocations": []},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {"errors": {"additional_warehouse_ids[1]": "Must be a positive integer."}},
        )

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["LOGISTICS_MANAGER"], []))
    def test_item_allocation_preview_rejects_invalid_draft_allocations(
        self,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        response = self.client.post(
            "/api/v1/operations/packages/70/allocation-options/101/preview",
            {"source_warehouse_id": 1, "draft_allocations": {"not": "a-list"}},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {"errors": {"draft_allocations": "draft_allocations must be provided as an array."}},
        )

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["LOGISTICS_MANAGER"], []))
    def test_item_allocation_preview_rejects_invalid_draft_allocation_row_shape(
        self,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        response = self.client.post(
            "/api/v1/operations/packages/70/allocation-options/101/preview",
            {
                "source_warehouse_id": 1,
                "draft_allocations": [
                    {
                        "item_id": 101,
                        "inventory_id": 1,
                        "quantity": "2.0000",
                    }
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {"errors": {"draft_allocations[0]": "Missing required field(s): batch_id."}},
        )

    @patch("operations.views.operations_service.list_requests")
    @patch(
        "operations.views.LegacyCompatAuthentication.authenticate",
        return_value=(SimpleNamespace(user_id=None, username=None, is_authenticated=True), None),
    )
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    def test_requests_reject_authenticated_actor_without_stable_identifier(
        self,
        _mock_permission,
        _mock_authenticate,
        mock_list_requests,
    ) -> None:
        response = self.client.get("/api/v1/operations/requests")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json()["detail"],
            "Authenticated operations requests require a stable actor identifier.",
        )
        mock_list_requests.assert_not_called()

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["LOGISTICS_MANAGER"], []))
    @patch("operations.views.operations_service.submit_request")
    def test_request_submit_requires_idempotency_key(
        self,
        mock_submit_request,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        response = self.client.post(
            "/api/v1/operations/requests/70/submit",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"errors": {"idempotency_key": "Idempotency-Key header is required."}})
        mock_submit_request.assert_not_called()

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["ODPEM_DG"], []))
    @patch("operations.views.operations_service.submit_eligibility_decision")
    def test_eligibility_decision_requires_idempotency_key(
        self,
        mock_submit_eligibility_decision,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        response = self.client.post(
            "/api/v1/operations/eligibility/80/decision",
            {"decision": "APPROVED"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"errors": {"idempotency_key": "Idempotency-Key header is required."}})
        mock_submit_eligibility_decision.assert_not_called()

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["SYSTEM_ADMINISTRATOR"], [PERM_OPERATIONS_REQUEST_CREATE_SELF]))
    @patch("operations.views.operations_service.create_request")
    def test_request_create_returns_429_when_rate_limited(
        self,
        mock_create_request,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        with patch(
            "operations.views._rate_limit_response",
            return_value=Response(
                {"detail": "Rate limit exceeded."},
                status=429,
                headers={"Retry-After": "17"},
            ),
        ):
            response = self.client.post(
                "/api/v1/operations/requests",
                {"agency_id": 5, "urgency_ind": "H", "items": [{"item_id": 101, "request_qty": "3"}]},
                format="json",
            )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response["Retry-After"], "17")
        self.assertEqual(response.json(), {"detail": "Rate limit exceeded."})
        mock_create_request.assert_not_called()

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["SYSTEM_ADMINISTRATOR"], [PERM_OPERATIONS_REQUEST_EDIT_DRAFT]))
    @patch("operations.views.operations_service.update_request")
    def test_request_update_returns_429_when_rate_limited(
        self,
        mock_update_request,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        with patch(
            "operations.views._rate_limit_response",
            return_value=Response(
                {"detail": "Rate limit exceeded."},
                status=429,
                headers={"Retry-After": "17"},
            ),
        ):
            response = self.client.patch(
                "/api/v1/operations/requests/70",
                {"rqst_notes_text": "Updated note"},
                format="json",
            )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response["Retry-After"], "17")
        self.assertEqual(response.json(), {"detail": "Rate limit exceeded."})
        mock_update_request.assert_not_called()

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["SYSTEM_ADMINISTRATOR"], []))
    @patch("operations.views.operations_service.submit_request")
    @patch("operations.views.operations_service.peek_idempotent_response", return_value=None)
    def test_request_submit_returns_429_when_rate_limited(
        self,
        mock_peek_response,
        mock_submit_request,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        with patch(
            "operations.views._rate_limit_response",
            return_value=Response(
                {"detail": "Rate limit exceeded."},
                status=429,
                headers={"Retry-After": "17"},
            ),
        ):
            response = self.client.post(
                "/api/v1/operations/requests/70/submit",
                {},
                format="json",
                HTTP_IDEMPOTENCY_KEY="submit-70",
            )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response["Retry-After"], "17")
        self.assertEqual(response.json(), {"detail": "Rate limit exceeded."})
        mock_submit_request.assert_not_called()
        self.assertEqual(mock_peek_response.call_args.kwargs["endpoint"], "request_submit")
        self.assertEqual(mock_peek_response.call_args.kwargs["resource_id"], 70)
        self.assertEqual(mock_peek_response.call_args.kwargs["actor_id"], "ops-dev")
        self.assertEqual(mock_peek_response.call_args.kwargs["tenant_context"].active_tenant_id, 20)
        self.assertEqual(mock_peek_response.call_args.kwargs["idempotency_key"], "submit-70")

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["SYSTEM_ADMINISTRATOR"], []))
    @patch("operations.views.operations_service.submit_request")
    @patch(
        "operations.views.operations_service.peek_idempotent_response",
        return_value={"reliefrqst_id": 70, "status_label": "Awaiting Approval"},
    )
    def test_request_submit_returns_cached_idempotent_response_before_rate_limit(
        self,
        mock_peek_response,
        mock_submit_request,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        with patch(
            "operations.views._rate_limit_response",
            return_value=Response(
                {"detail": "Rate limit exceeded."},
                status=429,
                headers={"Retry-After": "17"},
            ),
        ) as mock_rate_limit_response:
            response = self.client.post(
                "/api/v1/operations/requests/70/submit",
                {},
                format="json",
                HTTP_IDEMPOTENCY_KEY="submit-70",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"reliefrqst_id": 70, "status_label": "Awaiting Approval"})
        mock_rate_limit_response.assert_not_called()
        mock_submit_request.assert_not_called()
        self.assertEqual(mock_peek_response.call_args.kwargs["endpoint"], "request_submit")
        self.assertEqual(mock_peek_response.call_args.kwargs["resource_id"], 70)
        self.assertEqual(mock_peek_response.call_args.kwargs["actor_id"], "ops-dev")
        self.assertEqual(mock_peek_response.call_args.kwargs["tenant_context"].active_tenant_id, 20)
        self.assertEqual(mock_peek_response.call_args.kwargs["idempotency_key"], "submit-70")

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["ODPEM_DG"], []))
    @patch("operations.views.operations_service.submit_eligibility_decision")
    def test_eligibility_decision_returns_429_when_rate_limited(
        self,
        mock_submit_eligibility_decision,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        with patch(
            "operations.views._rate_limit_response",
            return_value=Response(
                {"detail": "Rate limit exceeded."},
                status=429,
                headers={"Retry-After": "17"},
            ),
        ):
            response = self.client.post(
                "/api/v1/operations/eligibility/80/decision",
                {"decision": "APPROVED"},
                format="json",
                HTTP_IDEMPOTENCY_KEY="eligibility-80",
            )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response["Retry-After"], "17")
        self.assertEqual(response.json(), {"detail": "Rate limit exceeded."})
        mock_submit_eligibility_decision.assert_not_called()

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["ODPEM_DG"], []))
    @patch("operations.views.operations_service.submit_eligibility_decision")
    @patch(
        "operations.views.operations_service.peek_idempotent_response",
        return_value={"reliefrqst_id": 80, "status_label": "Submitted"},
    )
    def test_eligibility_decision_returns_cached_idempotent_response_before_rate_limit(
        self,
        mock_peek_response,
        mock_submit_eligibility_decision,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        with patch(
            "operations.views._rate_limit_response",
            return_value=Response(
                {"detail": "Rate limit exceeded."},
                status=429,
                headers={"Retry-After": "17"},
            ),
        ) as mock_rate_limit_response:
            response = self.client.post(
                "/api/v1/operations/eligibility/80/decision",
                {"decision": "APPROVED"},
                format="json",
                HTTP_IDEMPOTENCY_KEY="eligibility-80",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"reliefrqst_id": 80, "status_label": "Submitted"})
        mock_rate_limit_response.assert_not_called()
        mock_submit_eligibility_decision.assert_not_called()
        self.assertEqual(mock_peek_response.call_args.kwargs["endpoint"], "eligibility_decision")
        self.assertEqual(mock_peek_response.call_args.kwargs["resource_id"], 80)
        self.assertEqual(mock_peek_response.call_args.kwargs["actor_id"], "ops-dev")
        self.assertEqual(mock_peek_response.call_args.kwargs["tenant_context"].active_tenant_id, 20)
        self.assertEqual(mock_peek_response.call_args.kwargs["idempotency_key"], "eligibility-80")

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["LOGISTICS_MANAGER"], []))
    @patch("operations.views.operations_service.save_package")
    def test_package_commit_requires_idempotency_key(
        self,
        mock_save_package,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        response = self.client.post(
            "/api/v1/operations/packages/70/allocations/commit",
            {"allocations": [{"item_id": 101, "inventory_id": 1, "batch_id": 1001, "quantity": "2"}]},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"errors": {"idempotency_key": "Idempotency-Key header is required."}})
        mock_save_package.assert_not_called()

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["LOGISTICS_MANAGER"], []))
    @patch("operations.views.operations_service.save_package")
    @patch(
        "operations.views.operations_service.peek_idempotent_response",
        return_value={"status": "COMMITTED", "reliefpkg_id": 70},
    )
    def test_package_commit_returns_cached_idempotent_response_before_rate_limit(
        self,
        mock_peek_response,
        mock_save_package,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        with patch(
            "operations.views._rate_limit_response",
            return_value=Response(
                {"detail": "Rate limit exceeded."},
                status=429,
                headers={"Retry-After": "17"},
            ),
        ) as mock_rate_limit_response:
            response = self.client.post(
                "/api/v1/operations/packages/70/allocations/commit",
                {"allocations": [{"item_id": 101, "inventory_id": 1, "batch_id": 1001, "quantity": "2"}]},
                format="json",
                HTTP_IDEMPOTENCY_KEY="package-70",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "COMMITTED", "reliefpkg_id": 70})
        mock_rate_limit_response.assert_not_called()
        mock_save_package.assert_not_called()
        self.assertEqual(mock_peek_response.call_args.kwargs["endpoint"], "package_commit_allocation")
        self.assertEqual(mock_peek_response.call_args.kwargs["resource_id"], 70)
        self.assertEqual(mock_peek_response.call_args.kwargs["actor_id"], "ops-dev")
        self.assertEqual(mock_peek_response.call_args.kwargs["tenant_context"].active_tenant_id, 20)
        self.assertEqual(mock_peek_response.call_args.kwargs["idempotency_key"], "package-70")

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["LOGISTICS_MANAGER"], []))
    @patch("operations.views.operations_service.submit_dispatch")
    def test_dispatch_handoff_requires_idempotency_key(
        self,
        mock_submit_dispatch,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        response = self.client.post(
            "/api/v1/operations/dispatch/90/handoff",
            {
                "transport_mode": "TRUCK",
                "driver_name": "Jane Driver",
                "vehicle_registration": "1234AB",
                "departure_dtime": "2026-03-26T10:00:00Z",
                "estimated_arrival_dtime": "2026-03-26T13:00:00Z",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"errors": {"idempotency_key": "Idempotency-Key header is required."}})
        mock_submit_dispatch.assert_not_called()

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["LOGISTICS_MANAGER"], []))
    @patch("operations.views.operations_service.submit_dispatch")
    @patch(
        "operations.views.operations_service.peek_idempotent_response",
        return_value={"status": "IN_TRANSIT", "reliefpkg_id": 90},
    )
    def test_dispatch_handoff_returns_cached_idempotent_response_before_rate_limit(
        self,
        mock_peek_response,
        mock_submit_dispatch,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        with patch(
            "operations.views._rate_limit_response",
            return_value=Response(
                {"detail": "Rate limit exceeded."},
                status=429,
                headers={"Retry-After": "17"},
            ),
        ) as mock_rate_limit_response:
            response = self.client.post(
                "/api/v1/operations/dispatch/90/handoff",
                {
                    "transport_mode": "TRUCK",
                    "driver_name": "Jane Driver",
                    "vehicle_registration": "1234AB",
                    "departure_dtime": "2026-03-26T10:00:00Z",
                    "estimated_arrival_dtime": "2026-03-26T13:00:00Z",
                },
                format="json",
                HTTP_IDEMPOTENCY_KEY="dispatch-90",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "IN_TRANSIT", "reliefpkg_id": 90})
        mock_rate_limit_response.assert_not_called()
        mock_submit_dispatch.assert_not_called()
        self.assertEqual(mock_peek_response.call_args.kwargs["endpoint"], "dispatch_handoff")
        self.assertEqual(mock_peek_response.call_args.kwargs["resource_id"], 90)
        self.assertEqual(mock_peek_response.call_args.kwargs["actor_id"], "ops-dev")
        self.assertEqual(mock_peek_response.call_args.kwargs["tenant_context"].active_tenant_id, 20)
        self.assertEqual(mock_peek_response.call_args.kwargs["idempotency_key"], "dispatch-90")

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["LOGISTICS_MANAGER"], []))
    @patch("operations.views.operations_service.dispatch_consolidation_leg")
    def test_consolidation_leg_dispatch_requires_idempotency_key(
        self,
        mock_dispatch_leg,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        response = self.client.post(
            "/api/v1/operations/packages/90/consolidation-legs/301/dispatch",
            {"dispatched_by_name": "Dispatcher"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"errors": {"idempotency_key": "Idempotency-Key header is required."}})
        mock_dispatch_leg.assert_not_called()

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["LOGISTICS_MANAGER"], []))
    @patch("operations.views.operations_service.receive_consolidation_leg")
    def test_consolidation_leg_receive_requires_idempotency_key(
        self,
        mock_receive_leg,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        response = self.client.post(
            "/api/v1/operations/packages/90/consolidation-legs/301/receive",
            {"received_by_name": "Receiver"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"errors": {"idempotency_key": "Idempotency-Key header is required."}})
        mock_receive_leg.assert_not_called()

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["LOGISTICS_MANAGER"], []))
    @patch("operations.views.operations_service.request_partial_release")
    def test_partial_release_request_requires_idempotency_key(
        self,
        mock_request_partial_release,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        response = self.client.post(
            "/api/v1/operations/packages/90/partial-release/request",
            {"reason": "Release received legs now"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"errors": {"idempotency_key": "Idempotency-Key header is required."}})
        mock_request_partial_release.assert_not_called()

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["LOGISTICS_MANAGER"], []))
    @patch("operations.views.operations_service.approve_partial_release")
    def test_partial_release_approve_requires_idempotency_key(
        self,
        mock_approve_partial_release,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        response = self.client.post(
            "/api/v1/operations/packages/90/partial-release/approve",
            {"decision": "APPROVE"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"errors": {"idempotency_key": "Idempotency-Key header is required."}})
        mock_approve_partial_release.assert_not_called()

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["LOGISTICS_MANAGER"], []))
    @patch("operations.views.data_access.get_active_event", return_value=None)
    @patch(
        "operations.views.operations_service.reject_override",
        return_value={"reliefrqst_id": 70, "status": "REJECTED", "override_status_code": "REJECTED"},
    )
    def test_package_override_reject_forwards_payload_actor_tenant_and_idempotency_key(
        self,
        mock_reject_override,
        _mock_active_event,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        response = self.client.post(
            "/api/v1/operations/packages/70/allocations/override-reject",
            {"reason": "Rebuild with compliant stock order."},
            format="json",
            HTTP_IDEMPOTENCY_KEY="override-reject-70",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_reject_override.call_args.kwargs["actor_id"], "ops-dev")
        self.assertEqual(mock_reject_override.call_args.kwargs["actor_roles"], ["LOGISTICS_MANAGER"])
        self.assertEqual(mock_reject_override.call_args.kwargs["tenant_context"].active_tenant_id, 20)
        self.assertEqual(mock_reject_override.call_args.kwargs["payload"]["reason"], "Rebuild with compliant stock order.")
        self.assertEqual(mock_reject_override.call_args.kwargs["idempotency_key"], "override-reject-70")

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["LOGISTICS_MANAGER"], []))
    @patch("operations.views.operations_service.return_override")
    def test_package_override_return_requires_idempotency_key(
        self,
        mock_return_override,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        response = self.client.post(
            "/api/v1/operations/packages/70/allocations/override-return",
            {"reason": "Adjust allocations to follow compliant stock order."},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"errors": {"idempotency_key": "Idempotency-Key header is required."}})
        mock_return_override.assert_not_called()

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["LOGISTICS_MANAGER"], []))
    @patch("operations.views.operations_service.approve_override")
    def test_package_override_approve_requires_idempotency_key(
        self,
        mock_approve_override,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        response = self.client.post(
            "/api/v1/operations/packages/70/allocations/override-approve",
            {"override_reason_code": "FEFO_BYPASS", "override_note": "Approved"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"errors": {"idempotency_key": "Idempotency-Key header is required."}})
        mock_approve_override.assert_not_called()

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["LOGISTICS_MANAGER"], []))
    @patch("operations.views.operations_service.reject_override")
    def test_package_override_reject_requires_idempotency_key(
        self,
        mock_reject_override,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        response = self.client.post(
            "/api/v1/operations/packages/70/allocations/override-reject",
            {"reason": "Rebuild with compliant stock order."},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"errors": {"idempotency_key": "Idempotency-Key header is required."}})
        mock_reject_override.assert_not_called()

    @patch("operations.views.operations_service.return_override")
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=False)
    def test_package_override_return_permission_guard_blocks_service_call(
        self,
        _mock_permission,
        mock_return_override,
    ) -> None:
        response = self.client.post(
            "/api/v1/operations/packages/70/allocations/override-return",
            {"reason": "Adjust allocations to follow compliant stock order."},
            format="json",
            HTTP_IDEMPOTENCY_KEY="override-return-guard-70",
        )

        self.assertEqual(response.status_code, 403)
        mock_return_override.assert_not_called()

    @patch("operations.views.operations_service.reject_override")
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=False)
    def test_package_override_reject_permission_guard_blocks_service_call(
        self,
        _mock_permission,
        mock_reject_override,
    ) -> None:
        response = self.client.post(
            "/api/v1/operations/packages/70/allocations/override-reject",
            {"reason": "Rebuild with compliant stock order."},
            format="json",
            HTTP_IDEMPOTENCY_KEY="override-reject-guard-70",
        )

        self.assertEqual(response.status_code, 403)
        mock_reject_override.assert_not_called()

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["LOGISTICS_MANAGER"], []))
    @patch("operations.views.operations_service.pickup_release")
    def test_pickup_release_requires_idempotency_key(
        self,
        mock_pickup_release,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        response = self.client.post(
            "/api/v1/operations/packages/90/pickup-release",
            {"released_by_name": "Receiver"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"errors": {"idempotency_key": "Idempotency-Key header is required."}})
        mock_pickup_release.assert_not_called()

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["LOGISTICS_MANAGER"], []))
    @patch("operations.views.operations_service.cancel_package")
    def test_package_cancel_requires_idempotency_key(
        self,
        mock_cancel_package,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        response = self.client.post(
            "/api/v1/operations/packages/90/cancel",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"errors": {"idempotency_key": "Idempotency-Key header is required."}})
        mock_cancel_package.assert_not_called()

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["LOGISTICS_MANAGER"], []))
    @patch("operations.views.operations_service.abandon_package_draft")
    def test_package_abandon_draft_requires_idempotency_key(
        self,
        mock_abandon_package_draft,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        response = self.client.post(
            "/api/v1/operations/packages/90/abandon-draft",
            {"reason": "Release draft lock"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"errors": {"idempotency_key": "Idempotency-Key header is required."}})
        mock_abandon_package_draft.assert_not_called()

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["LOGISTICS_MANAGER"], []))
    @patch("operations.views.operations_service.request_partial_release")
    def test_partial_release_request_returns_429_when_rate_limited(
        self,
        mock_request_partial_release,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        with patch(
            "operations.views._rate_limit_response",
            return_value=Response(
                {"detail": "Rate limit exceeded."},
                status=429,
                headers={"Retry-After": "17"},
            ),
        ):
            response = self.client.post(
                "/api/v1/operations/packages/90/partial-release/request",
                {"reason": "Release received legs now"},
                format="json",
                HTTP_IDEMPOTENCY_KEY="partial-request-90",
            )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response["Retry-After"], "17")
        self.assertEqual(response.json(), {"detail": "Rate limit exceeded."})
        mock_request_partial_release.assert_not_called()

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["LOGISTICS_MANAGER"], []))
    @patch("operations.views.operations_service.return_override")
    def test_package_override_return_returns_429_when_rate_limited(
        self,
        mock_return_override,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        with patch(
            "operations.views._rate_limit_response",
            return_value=Response(
                {"detail": "Rate limit exceeded."},
                status=429,
                headers={"Retry-After": "17"},
            ),
        ):
            response = self.client.post(
                "/api/v1/operations/packages/70/allocations/override-return",
                {"reason": "Adjust allocations to follow compliant stock order."},
                format="json",
                HTTP_IDEMPOTENCY_KEY="override-return-70",
            )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response["Retry-After"], "17")
        self.assertEqual(response.json(), {"detail": "Rate limit exceeded."})
        mock_return_override.assert_not_called()

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["LOGISTICS_MANAGER"], []))
    @patch("operations.views.operations_service.reject_override")
    def test_package_override_reject_returns_429_when_rate_limited(
        self,
        mock_reject_override,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        with patch(
            "operations.views._rate_limit_response",
            return_value=Response(
                {"detail": "Rate limit exceeded."},
                status=429,
                headers={"Retry-After": "17"},
            ),
        ):
            response = self.client.post(
                "/api/v1/operations/packages/70/allocations/override-reject",
                {"reason": "Rebuild with compliant stock order."},
                format="json",
                HTTP_IDEMPOTENCY_KEY="override-reject-70",
            )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response["Retry-After"], "17")
        self.assertEqual(response.json(), {"detail": "Rate limit exceeded."})
        mock_reject_override.assert_not_called()

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["LOGISTICS_MANAGER"], []))
    @patch("operations.views.operations_service.approve_override")
    def test_package_override_approve_returns_429_when_rate_limited(
        self,
        mock_approve_override,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        with patch(
            "operations.views._rate_limit_response",
            return_value=Response(
                {"detail": "Rate limit exceeded."},
                status=429,
                headers={"Retry-After": "17"},
            ),
        ):
            response = self.client.post(
                "/api/v1/operations/packages/70/allocations/override-approve",
                {"override_reason_code": "FEFO_BYPASS", "override_note": "Approved"},
                format="json",
                HTTP_IDEMPOTENCY_KEY="override-70",
            )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response["Retry-After"], "17")
        self.assertEqual(response.json(), {"detail": "Rate limit exceeded."})
        mock_approve_override.assert_not_called()

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["LOGISTICS_MANAGER"], []))
    @patch("operations.views.operations_service.save_package")
    def test_package_commit_allocation_returns_429_when_rate_limited(
        self,
        mock_save_package,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        with patch(
            "operations.views._rate_limit_response",
            return_value=Response(
                {"detail": "Rate limit exceeded."},
                status=429,
                headers={"Retry-After": "17"},
            ),
        ):
            response = self.client.post(
                "/api/v1/operations/packages/70/allocations/commit",
                {"allocations": [{"item_id": 101, "inventory_id": 1, "batch_id": 1001, "quantity": "2"}]},
                format="json",
                HTTP_IDEMPOTENCY_KEY="package-70",
            )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response["Retry-After"], "17")
        self.assertEqual(response.json(), {"detail": "Rate limit exceeded."})
        mock_save_package.assert_not_called()

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["LOGISTICS_MANAGER"], []))
    @patch("operations.views.operations_service.cancel_package")
    def test_package_cancel_returns_429_when_rate_limited(
        self,
        mock_cancel_package,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        with patch(
            "operations.views._rate_limit_response",
            return_value=Response(
                {"detail": "Rate limit exceeded."},
                status=429,
                headers={"Retry-After": "17"},
            ),
        ):
            response = self.client.post(
                "/api/v1/operations/packages/90/cancel",
                {},
                format="json",
                HTTP_IDEMPOTENCY_KEY="cancel-90",
            )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response["Retry-After"], "17")
        self.assertEqual(response.json(), {"detail": "Rate limit exceeded."})
        mock_cancel_package.assert_not_called()

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["LOGISTICS_MANAGER"], []))
    @patch("operations.views.operations_service.abandon_package_draft")
    def test_package_abandon_draft_returns_429_when_rate_limited(
        self,
        mock_abandon_package_draft,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        with patch(
            "operations.views._rate_limit_response",
            return_value=Response(
                {"detail": "Rate limit exceeded."},
                status=429,
                headers={"Retry-After": "17"},
            ),
        ):
            response = self.client.post(
                "/api/v1/operations/packages/90/abandon-draft",
                {"reason": "Release draft lock"},
                format="json",
                HTTP_IDEMPOTENCY_KEY="abandon-90",
            )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response["Retry-After"], "17")
        self.assertEqual(response.json(), {"detail": "Rate limit exceeded."})
        mock_abandon_package_draft.assert_not_called()

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["LOGISTICS_MANAGER"], []))
    @patch("operations.views.operations_service.receive_consolidation_leg")
    def test_consolidation_leg_receive_returns_429_when_rate_limited(
        self,
        mock_receive_leg,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        with patch(
            "operations.views._rate_limit_response",
            return_value=Response(
                {"detail": "Rate limit exceeded."},
                status=429,
                headers={"Retry-After": "17"},
            ),
        ):
            response = self.client.post(
                "/api/v1/operations/packages/90/consolidation-legs/301/receive",
                {"received_by_name": "Receiver"},
                format="json",
                HTTP_IDEMPOTENCY_KEY="receive-leg-301",
            )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response["Retry-After"], "17")
        self.assertEqual(response.json(), {"detail": "Rate limit exceeded."})
        mock_receive_leg.assert_not_called()


@override_settings(
    AUTH_ENABLED=False,
    DEV_AUTH_ENABLED=False,
    DEBUG=True,
)
class OperationsPermissionRuntimeTests(SimpleTestCase):
    databases = {"default"}

    def setUp(self) -> None:
        self.client = APIClient()

    @patch(
        "api.authentication.LegacyCompatAuthentication.authenticate",
        return_value=(
            Principal(
                user_id="13",
                username="relief_ffp_requester_tst",
                roles=["AGENCY_DISTRIBUTOR"],
                permissions=[PERM_OPERATIONS_REQUEST_CREATE_SELF],
            ),
            None,
        ),
    )
    @patch("operations.views.operations_service.get_request_reference_data", return_value={"agencies": [], "events": [], "items": []})
    def test_reference_data_view_honors_function_view_required_permission(
        self,
        mock_reference_data,
        _mock_authenticate,
    ) -> None:
        response = self.client.get("/api/v1/operations/requests/reference-data", HTTP_HOST="localhost")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"agencies": [], "events": [], "items": []})
        mock_reference_data.assert_called_once()


@override_settings(
    AUTH_ENABLED=False,
    DEV_AUTH_ENABLED=False,
    DEBUG=True,
    AUTH_USE_DB_RBAC=False,
)
class OperationsApiTenantIsolationTests(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        cache.clear()

    def tearDown(self) -> None:
        cache.clear()

    @staticmethod
    def _tenant_context(tenant_id: int, tenant_code: str) -> TenantContext:
        membership = TenantMembership(
            tenant_id=tenant_id,
            tenant_code=tenant_code,
            tenant_name=tenant_code,
            tenant_type="TENANT",
            is_primary=True,
            access_level="FULL",
        )
        return TenantContext(
            requested_tenant_id=tenant_id,
            active_tenant_id=tenant_id,
            active_tenant_code=tenant_code,
            active_tenant_type="TENANT",
            memberships=(membership,),
            can_read_all_tenants=False,
            can_act_cross_tenant=False,
        )

    @patch("operations.contract_services.legacy_service._request_summary", return_value={"status_code": "DRAFT"})
    @patch("operations.contract_services.legacy_service.get_request", return_value={"reliefrqst_id": 70, "tracking_no": "RQ00070"})
    @patch("operations.contract_services.ReliefPkg.objects.filter")
    @patch("operations.contract_services.operations_policy.get_agency_scope", return_value=SimpleNamespace(tenant_id=10))
    @patch("operations.contract_services._legacy_helper")
    @patch("operations.views.resolve_tenant_context")
    def test_request_detail_denies_cross_tenant_reader(
        self,
        mock_resolve_tenant_context,
        mock_legacy_helper,
        _mock_get_agency_scope,
        mock_reliefpkg_filter,
        mock_legacy_get_request,
        _mock_request_summary,
    ) -> None:
        request_date = date(2026, 4, 7)
        OperationsReliefRequest.objects.create(
            relief_request_id=70,
            request_no="RQ00070",
            requesting_tenant_id=10,
            requesting_agency_id=501,
            beneficiary_tenant_id=10,
            beneficiary_agency_id=501,
            origin_mode="SELF",
            event_id=12,
            request_date=request_date,
            urgency_code="H",
            status_code="DRAFT",
            create_by_id="user-a",
            update_by_id="user-a",
        )

        legacy_request = SimpleNamespace(
            reliefrqst_id=70,
            agency_id=501,
            request_date=request_date,
            tracking_no="RQ00070",
            eligible_event_id=12,
            urgency_ind="H",
            rqst_notes_text=None,
            review_by_id=None,
            review_dtime=None,
            create_by_id="user-a",
            create_dtime=None,
            status_code=0,
        )
        mock_legacy_helper.return_value = lambda *_args, **_kwargs: legacy_request
        mock_reliefpkg_filter.return_value.order_by.return_value = []

        tenant_contexts = {
            "user-a": self._tenant_context(10, "TENANT_A"),
            "user-b": self._tenant_context(20, "TENANT_B"),
        }
        mock_resolve_tenant_context.side_effect = (
            lambda request, user, permissions: tenant_contexts[str(user.user_id)]
        )

        user_a = Principal(
            user_id="user-a",
            username="user-a",
            roles=["AGENCY_DISTRIBUTOR"],
            permissions=[PERM_OPERATIONS_REQUEST_EDIT_DRAFT],
        )
        user_b = Principal(
            user_id="user-b",
            username="user-b",
            roles=["AGENCY_DISTRIBUTOR"],
            permissions=[PERM_OPERATIONS_REQUEST_EDIT_DRAFT],
        )

        self.client.force_authenticate(user=user_a)
        allowed_response = self.client.get("/api/v1/operations/requests/70")

        self.client.force_authenticate(user=user_b)
        denied_response = self.client.get("/api/v1/operations/requests/70")

        self.assertEqual(allowed_response.status_code, 200)
        self.assertEqual(denied_response.status_code, 404)
        self.assertEqual(denied_response.json(), {"detail": "Not found."})
        self.assertEqual(mock_legacy_get_request.call_count, 1)


class OperationsViewHelperTests(SimpleTestCase):
    def setUp(self) -> None:
        self.factory = RequestFactory()
        cache.clear()
        active_event_patcher = patch("operations.views.data_access.get_active_event", return_value={})
        active_event_patcher.start()
        self.addCleanup(active_event_patcher.stop)

    def tearDown(self) -> None:
        cache.clear()

    def test_request_ip_ignores_untrusted_forwarded_for_headers(self) -> None:
        request = self.factory.get(
            "/api/v1/operations/dispatch/90/handoff",
            REMOTE_ADDR="10.0.0.25",
            HTTP_X_FORWARDED_FOR="198.51.100.77, 203.0.113.9",
        )

        self.assertEqual(operations_views._request_ip(request), "10.0.0.25")

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["LOGISTICS_MANAGER"], []))
    def test_rate_limit_keys_use_actor_tenant_primary_key_and_ip_secondary_key(
        self,
        _mock_roles,
        _mock_tenant_context,
    ) -> None:
        request = self.factory.post(
            "/api/v1/operations/packages/90/consolidation-legs/301/dispatch",
            REMOTE_ADDR="10.0.0.25",
        )
        request.user = SimpleNamespace(user_id="13", username="relief_ffp_requester_tst", is_authenticated=True)

        cache_key, secondary_key, actor_id, tenant_id = operations_views._rate_limit_keys(
            request,
            "consolidation_leg_dispatch",
        )

        self.assertEqual(cache_key, "ops:rate:consolidation_leg_dispatch:13:20")
        self.assertEqual(secondary_key, "ops:rate:consolidation_leg_dispatch:13:20:ip:10.0.0.25")
        self.assertEqual(actor_id, "13")
        self.assertEqual(tenant_id, "20")

    @patch("operations.views.data_access.get_active_event", return_value={"phase": "SURGE"})
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["LOGISTICS_MANAGER"], []))
    def test_scaled_rate_limit_doubles_for_field_roles_during_surge(
        self,
        _mock_roles,
        _mock_active_event,
    ) -> None:
        request = self.factory.post("/api/v1/operations/packages/90/consolidation-legs/301/dispatch")
        request.user = SimpleNamespace(user_id="13", username="relief_ffp_requester_tst", is_authenticated=True)

        self.assertEqual(operations_views._scaled_rate_limit(request, 10), 20)

    def test_service_error_response_hides_scope_errors_as_not_found(self) -> None:
        response = operations_views._service_error_response(
            OperationValidationError({"scope": "Request is outside the active tenant or workflow assignment scope."})
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data, {"detail": "Not found."})

    def test_service_error_response_preserves_non_scope_validation_errors(self) -> None:
        response = operations_views._service_error_response(
            OperationValidationError({"reason": "A partial release reason is required."})
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data, {"errors": {"reason": "A partial release reason is required."}})

    def test_required_positive_int_payload_value_rejects_non_integer_values(self) -> None:
        for raw_value in (True, False, 1.5, "1.5", "abc"):
            with self.subTest(raw_value=raw_value):
                with self.assertRaises(OperationValidationError) as captured:
                    operations_views._required_positive_int_payload_value(raw_value, "source_warehouse_id")

                self.assertEqual(
                    captured.exception.errors,
                    {"source_warehouse_id": "Must be a positive integer."},
                )

    def test_acquire_rate_limit_lock_stores_owner_token(self) -> None:
        owner_token = operations_views._acquire_rate_limit_lock("ops:test:lock")

        self.assertTrue(owner_token)
        self.assertEqual(cache.get("ops:test:lock"), owner_token)

    def test_release_rate_limit_lock_preserves_newer_owner(self) -> None:
        cache.set("ops:test:lock", "owner-2", timeout=30)

        operations_views._release_rate_limit_lock("ops:test:lock", "owner-1")
        self.assertEqual(cache.get("ops:test:lock"), "owner-2")

        operations_views._release_rate_limit_lock("ops:test:lock", "owner-2")
        self.assertIsNone(cache.get("ops:test:lock"))

    @patch(
        "api.authentication.LegacyCompatAuthentication.authenticate",
        return_value=(
            Principal(
                user_id="13",
                username="relief_ffp_requester_tst",
                roles=["AGENCY_DISTRIBUTOR"],
                permissions=[PERM_OPERATIONS_REQUEST_CREATE_SELF],
            ),
            None,
        ),
    )
    @patch("operations.views.operations_service.create_request", return_value={"reliefrqst_id": 70, "tracking_no": "RQ00070"})
    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch(
        "operations.views.resolve_roles_and_permissions",
        return_value=(["AGENCY_DISTRIBUTOR"], [PERM_OPERATIONS_REQUEST_CREATE_SELF]),
    )
    def test_request_create_view_honors_method_scoped_required_permission(
        self,
        _mock_roles,
        _mock_tenant_context,
        mock_create_request,
        _mock_authenticate,
    ) -> None:
        response = self.client.post(
            "/api/v1/operations/requests",
            {"agency_id": 5, "urgency_ind": "H", "items": [{"item_id": 101, "request_qty": "3"}]},
            format="json",
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json(), {"reliefrqst_id": 70, "tracking_no": "RQ00070"})
        mock_create_request.assert_called_once()
