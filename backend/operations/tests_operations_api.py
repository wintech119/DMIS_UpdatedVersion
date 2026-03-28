from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from rest_framework.test import APIClient

from api.authentication import Principal
from api.rbac import PERM_OPERATIONS_REQUEST_CREATE_SELF, PERM_OPERATIONS_REQUEST_EDIT_DRAFT


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
        self.assertEqual(mock_tasks.call_args.kwargs["actor_roles"], ["LOGISTICS_MANAGER"])

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
