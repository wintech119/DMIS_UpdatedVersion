from __future__ import annotations

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from rest_framework.test import APIClient


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

    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
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
        _mock_permission,
    ) -> None:
        list_response = self.client.get("/api/v1/operations/requests")
        detail_response = self.client.get("/api/v1/operations/requests/70")
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
        self.assertEqual(create_response.status_code, 201)
        self.assertEqual(update_response.status_code, 200)
        self.assertEqual(submit_response.status_code, 200)
        mock_list.assert_called_once_with(filter_key=None, actor_id="ops-dev")
        mock_get.assert_called_once_with(70, actor_id="ops-dev")
        self.assertEqual(mock_create.call_args.kwargs["actor_id"], "ops-dev")
        self.assertEqual(mock_create.call_args.kwargs["payload"]["agency_id"], 5)
        self.assertEqual(mock_update.call_args.kwargs["actor_id"], "ops-dev")
        self.assertEqual(mock_update.call_args.kwargs["payload"]["rqst_notes_text"], "Updated note")
        mock_submit.assert_called_once_with(70, actor_id="ops-dev")

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
        mock_list.assert_called_once_with(actor_id="ops-dev")
        mock_get.assert_called_once_with(80, actor_id="ops-dev")
        self.assertEqual(mock_decide.call_args.kwargs["payload"]["decision"], "Y")
        self.assertEqual(mock_decide.call_args.kwargs["actor_id"], "ops-dev")

    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["LOGISTICS_MANAGER"], []))
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
        _mock_roles,
        _mock_permission,
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
        dispatch_submit_response = self.client.post("/api/v1/operations/dispatch/90/handoff", {"transport_mode": "TRUCK"}, format="json")
        waybill_response = self.client.get("/api/v1/operations/dispatch/90/waybill")

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
        mock_list_packages.assert_called_once_with(actor_id="ops-dev")
        mock_get_package.assert_called_once_with(70, actor_id="ops-dev")
        mock_options.assert_called_once_with(70, source_warehouse_id=1)
        self.assertEqual(mock_save.call_count, 2)
        self.assertEqual(mock_save.call_args_list[0].kwargs["payload"]["comments_text"], "Prep")
        self.assertEqual(mock_save.call_args_list[1].kwargs["payload"]["allocations"][0]["item_id"], 101)
        self.assertEqual(mock_override.call_args.kwargs["actor_roles"], ["LOGISTICS_MANAGER"])
        mock_dispatch_queue.assert_called_once_with(actor_id="ops-dev")
        mock_dispatch_detail.assert_called_once_with(90, actor_id="ops-dev")
        self.assertEqual(mock_submit_dispatch.call_args.kwargs["payload"]["transport_mode"], "TRUCK")
        mock_waybill.assert_called_once_with(90)
