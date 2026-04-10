from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from rest_framework.test import APIClient

from api.authentication import Principal
from api.rbac import PERM_OPERATIONS_REQUEST_CREATE_SELF, PERM_OPERATIONS_REQUEST_EDIT_DRAFT
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
        submit_response = self.client.post("/api/v1/operations/requests/70/submit", {}, format="json")

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
        )
        override_response = self.client.post(
            "/api/v1/operations/packages/70/allocations/override-approve",
            {"allocations": [{"item_id": 101, "inventory_id": 1, "batch_id": 1001, "quantity": "2"}], "override_reason_code": "FEFO_BYPASS", "override_note": "Approved"},
            format="json",
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
        )
        waybill_response = self.client.get("/api/v1/operations/dispatch/90/waybill")
        receipt_response = self.client.post("/api/v1/operations/receipt-confirmation/90", {"received_by_name": "Receiver"}, format="json")
        cancel_response = self.client.post("/api/v1/operations/packages/90/cancel", {}, format="json")
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
        self.assertEqual(mock_save.call_args_list[1].kwargs["payload"]["allocations"][0]["item_id"], 101)
        self.assertEqual(mock_save.call_args_list[0].kwargs["tenant_context"].active_tenant_id, 20)
        self.assertEqual(mock_save.call_args_list[0].kwargs["permissions"], [])
        self.assertEqual(mock_save.call_args_list[1].kwargs["permissions"], [])
        self.assertEqual(mock_override.call_args.kwargs["actor_roles"], ["LOGISTICS_MANAGER"])
        self.assertEqual(mock_override.call_args.kwargs["tenant_context"].active_tenant_id, 20)
        self.assertEqual(mock_dispatch_queue.call_args.kwargs["actor_id"], "ops-dev")
        self.assertEqual(mock_dispatch_queue.call_args.kwargs["actor_roles"], ["LOGISTICS_MANAGER"])
        self.assertEqual(mock_dispatch_queue.call_args.kwargs["tenant_context"].active_tenant_id, 20)
        self.assertEqual(mock_dispatch_detail.call_args.kwargs["actor_id"], "ops-dev")
        self.assertEqual(mock_dispatch_detail.call_args.kwargs["actor_roles"], ["LOGISTICS_MANAGER"])
        self.assertEqual(mock_dispatch_detail.call_args.kwargs["tenant_context"].active_tenant_id, 20)
        self.assertEqual(mock_submit_dispatch.call_args.kwargs["payload"]["transport_mode"], "TRUCK")
        self.assertEqual(mock_submit_dispatch.call_args.kwargs["payload"]["driver_name"], "Jane Driver")
        self.assertEqual(mock_submit_dispatch.call_args.kwargs["tenant_context"].active_tenant_id, 20)
        self.assertEqual(mock_waybill.call_args.kwargs["actor_id"], "ops-dev")
        self.assertEqual(mock_waybill.call_args.kwargs["tenant_context"].active_tenant_id, 20)
        self.assertEqual(mock_receipt.call_args.kwargs["payload"]["received_by_name"], "Receiver")
        self.assertEqual(mock_receipt.call_args.kwargs["tenant_context"].active_tenant_id, 20)
        self.assertEqual(mock_cancel_package.call_args.args[0], 90)
        self.assertEqual(mock_cancel_package.call_args.kwargs["actor_roles"], ["LOGISTICS_MANAGER"])
        self.assertEqual(mock_cancel_package.call_args.kwargs["tenant_context"].active_tenant_id, 20)
        self.assertEqual(mock_tasks.call_args.kwargs["actor_roles"], ["LOGISTICS_MANAGER"])

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
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["LOGISTICS_MANAGER"], []))
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
    @patch(
        "operations.views.operations_service.get_item_allocation_options",
        return_value={
            "item_id": 101,
            "source_warehouse_id": 1,
            "remaining_shortfall_qty": "6.0000",
            "continuation_recommended": True,
            "alternate_warehouses": [
                {
                    "warehouse_id": 2,
                    "warehouse_name": "Warehouse 2",
                    "available_qty": "6.0000",
                    "suggested_qty": "6.0000",
                    "can_fully_cover": True,
                }
            ],
        },
    )
    def test_item_allocation_options_forwards_ids_and_returns_continuation_fields(
        self,
        mock_item_options,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        response = self.client.get("/api/v1/operations/packages/70/allocation-options/101?source_warehouse_id=1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["remaining_shortfall_qty"], "6.0000")
        self.assertTrue(response.json()["continuation_recommended"])
        self.assertEqual(response.json()["alternate_warehouses"][0]["warehouse_id"], 2)
        self.assertEqual(mock_item_options.call_args.args[:2], (70, 101))
        self.assertEqual(mock_item_options.call_args.kwargs["source_warehouse_id"], 1)
        self.assertIsNone(mock_item_options.call_args.kwargs["draft_allocations"])
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
        )
        receive_leg_response = self.client.post(
            "/api/v1/operations/packages/90/consolidation-legs/301/receive",
            {"received_by_name": "Receiver"},
            format="json",
        )
        leg_waybill_response = self.client.get("/api/v1/operations/packages/90/consolidation-legs/301/waybill")
        partial_request_response = self.client.post(
            "/api/v1/operations/packages/90/partial-release/request",
            {"reason": "Release received legs now"},
            format="json",
        )
        partial_approve_response = self.client.post(
            "/api/v1/operations/packages/90/partial-release/approve",
            {"approval_reason": "Approved"},
            format="json",
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
        self.assertEqual(mock_receive_leg.call_args.args[:2], (90, 301))
        self.assertEqual(mock_receive_leg.call_args.kwargs["payload"]["received_by_name"], "Receiver")
        self.assertEqual(mock_leg_waybill.call_args.args[:2], (90, 301))
        self.assertEqual(mock_partial_request.call_args.args[0], 90)
        self.assertEqual(mock_partial_request.call_args.kwargs["payload"]["reason"], "Release received legs now")
        self.assertEqual(mock_partial_approve.call_args.args[0], 90)
        self.assertEqual(mock_pickup_release.call_args.args[0], 90)
        self.assertEqual(mock_pickup_release.call_args.kwargs["payload"]["collected_by_name"], "Community Driver")
        self.assertEqual(mock_pickup_release.call_args.kwargs["payload"]["collected_by_id_ref"], "NID-7788")
        self.assertEqual(mock_pickup_release.call_args.kwargs["payload"]["released_by_name"], "Receiver")
        self.assertEqual(mock_pickup_release.call_args.kwargs["payload"]["release_notes"], "Pickup at gate")

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
    @patch("operations.views.operations_service.get_item_allocation_options")
    def test_item_allocation_options_require_source_warehouse_id(
        self,
        mock_item_options,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        response = self.client.get("/api/v1/operations/packages/70/allocation-options/101")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"errors": {"source_warehouse_id": "source_warehouse_id is required."}})
        mock_item_options.assert_not_called()

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
            "source_warehouse_id": 1,
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
            "source_warehouse_id": 1,
            "draft_allocations": [
                {
                    "item_id": 101,
                    "inventory_id": 1,
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
        self.assertEqual(mock_preview.call_args.args[:2], (70, 101))
        self.assertEqual(mock_preview.call_args.kwargs["payload"], payload)
        self.assertEqual(mock_preview.call_args.kwargs["actor_id"], "ops-dev")
        self.assertEqual(mock_preview.call_args.kwargs["actor_roles"], ["LOGISTICS_MANAGER"])
        self.assertEqual(mock_preview.call_args.kwargs["tenant_context"].active_tenant_id, 20)

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["LOGISTICS_MANAGER"], []))
    def test_item_allocation_preview_rejects_missing_source_warehouse_id(
        self,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        response = self.client.post(
            "/api/v1/operations/packages/70/allocation-options/101/preview",
            {"draft_allocations": []},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"errors": {"source_warehouse_id": "source_warehouse_id is required."}})

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
            response.json(),
            {"detail": "Authenticated operations requests require a stable actor identifier."},
        )
        mock_list_requests.assert_not_called()


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
