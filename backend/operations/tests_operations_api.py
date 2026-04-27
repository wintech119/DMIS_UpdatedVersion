from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import patch

from django.core.cache import cache
from django.db import DatabaseError, connection
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.test import APIClient

from api.authentication import Principal
from api.rbac import (
    PERM_OPERATIONS_PACKAGE_OVERRIDE_APPROVE,
    PERM_OPERATIONS_QUEUE_VIEW,
    PERM_OPERATIONS_REQUEST_CANCEL,
    PERM_OPERATIONS_REQUEST_CREATE_SELF,
    PERM_OPERATIONS_REQUEST_EDIT_DRAFT,
    PERM_OPERATIONS_REQUEST_SUBMIT,
)
from api.tenancy import TenantContext, TenantMembership
from operations.constants import (
    ACTION_REQUEST_BRIDGE_CREATED,
    ACTION_REQUEST_CANCELLED,
    EVENT_REQUEST_CANCELLED,
    ORIGIN_MODE_SELF,
    QUEUE_CODE_ELIGIBILITY,
    REQUEST_STATUS_APPROVED_FOR_FULFILLMENT,
    REQUEST_STATUS_CANCELLED,
    REQUEST_STATUS_DRAFT,
    REQUEST_STATUS_SUBMITTED,
    REQUEST_STATUS_UNDER_ELIGIBILITY_REVIEW,
)
from operations.exceptions import OperationValidationError
from operations.models import (
    OperationsActionAudit,
    OperationsNotification,
    OperationsQueueAssignment,
    OperationsReliefRequest,
    OperationsStatusHistory,
)
from operations import contract_services as operations_service, views as operations_views
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
        self.active_event_patcher = patch("operations.views.data_access.get_active_event", return_value=None)
        self.active_event_patcher.start()
        self.addCleanup(self.active_event_patcher.stop)
        cache.clear()

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

    @patch("operations.views.resolve_roles_and_permissions", return_value=(["AGENCY_DISTRIBUTOR"], [PERM_OPERATIONS_REQUEST_CANCEL]))
    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.operations_service.cancel_request", return_value={"reliefrqst_id": 70, "status_code": "CANCELLED"})
    def test_request_cancel_forwards_payload_actor_roles_permissions_tenant_and_idempotency_key(
        self,
        mock_cancel,
        _mock_permission,
        mock_tenant_context,
        _mock_roles,
    ) -> None:
        response = self.client.post(
            "/api/v1/operations/requests/70/cancel",
            {"cancellation_reason": "Duplicate intake"},
            format="json",
            HTTP_IDEMPOTENCY_KEY="cancel-70",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_cancel.call_args.args[0], 70)
        self.assertEqual(mock_cancel.call_args.kwargs["payload"]["cancellation_reason"], "Duplicate intake")
        self.assertEqual(mock_cancel.call_args.kwargs["actor_id"], "ops-dev")
        self.assertEqual(mock_cancel.call_args.kwargs["actor_roles"], ["AGENCY_DISTRIBUTOR"])
        self.assertIs(mock_cancel.call_args.kwargs["tenant_context"], mock_tenant_context.return_value)
        self.assertEqual(mock_cancel.call_args.kwargs["permissions"], [PERM_OPERATIONS_REQUEST_CANCEL])
        self.assertEqual(mock_cancel.call_args.kwargs["idempotency_key"], "cancel-70")

    @patch("operations.views.resolve_roles_and_permissions", return_value=(["AGENCY_DISTRIBUTOR"], [PERM_OPERATIONS_REQUEST_CANCEL]))
    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.operations_service.cancel_request")
    def test_request_cancel_requires_idempotency_key(
        self,
        mock_cancel,
        _mock_permission,
        _mock_tenant_context,
        _mock_roles,
    ) -> None:
        response = self.client.post(
            "/api/v1/operations/requests/70/cancel",
            {"cancellation_reason": "Duplicate intake"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"errors": {"idempotency_key": "Idempotency-Key header is required."}})
        mock_cancel.assert_not_called()

    @patch("operations.views.resolve_roles_and_permissions", return_value=(["AGENCY_DISTRIBUTOR"], [PERM_OPERATIONS_QUEUE_VIEW]))
    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch(
        "operations.views.operations_service.get_request_authority_preview",
        return_value={
            "can_create": True,
            "allowed_origin_modes": ["SELF"],
            "required_authority_tenant_id": None,
            "beneficiary_tenant_id": 20,
            "beneficiary_agency_id": 501,
            "suggested_event_id": 12,
            "blocked_reason_code": None,
        },
    )
    def test_request_authority_preview_forwards_source_needs_list_tenant_and_permissions(
        self,
        mock_preview,
        _mock_permission,
        mock_tenant_context,
        _mock_roles,
    ) -> None:
        response = self.client.get("/api/v1/operations/requests/authority-preview?source_needs_list_id=40")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_preview.call_args.kwargs["source_needs_list_id"], 40)
        self.assertIs(mock_preview.call_args.kwargs["tenant_context"], mock_tenant_context.return_value)
        self.assertEqual(mock_preview.call_args.kwargs["permissions"], [PERM_OPERATIONS_QUEUE_VIEW])
        self.assertTrue(response.json()["can_create"])

    @patch("operations.views.resolve_roles_and_permissions", return_value=(["AGENCY_DISTRIBUTOR"], [PERM_OPERATIONS_QUEUE_VIEW]))
    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch(
        "operations.views.operations_service.get_request_authority_preview",
        side_effect=OperationValidationError(
            {
                "source_needs_list_id": {
                    "code": "source_needs_list_not_found",
                    "message": "The source needs list does not exist.",
                }
            }
        ),
    )
    def test_request_authority_preview_missing_needs_list_returns_not_found(
        self,
        _mock_preview,
        _mock_permission,
        _mock_tenant_context,
        _mock_roles,
    ) -> None:
        response = self.client.get("/api/v1/operations/requests/authority-preview?source_needs_list_id=404")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "Not found."})

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
            {
                "received_by_name": "Receiver",
                "receipt_lines": [
                    {
                        "leg_item_id": 8001,
                        "received_qty": "1.0000",
                        "damaged_qty": "0.0000",
                    }
                ],
            },
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
        self.assertEqual(mock_receive_leg.call_args.kwargs["payload"]["receipt_lines"][0]["leg_item_id"], 8001)
        self.assertEqual(mock_receive_leg.call_args.kwargs["payload"]["receipt_lines"][0]["received_qty"], "1.0000")
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
            {"errors": {"additional_warehouse_ids[1]": "Must be an integer."}},
        )
        mock_item_options.assert_not_called()

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["LOGISTICS_MANAGER"], []))
    @patch("operations.views.operations_service.get_item_allocation_options")
    def test_item_allocation_options_rejects_too_many_additional_warehouse_ids(
        self,
        mock_item_options,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        response = self.client.get(
            "/api/v1/operations/packages/70/allocation-options/101",
            {"additional_warehouse_ids": [str(index) for index in range(1, 102)]},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {"errors": {"additional_warehouse_ids": "additional_warehouse_ids must not contain more than 100 items."}},
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
            {"errors": {"additional_warehouse_ids[1]": "Must be an integer."}},
        )

    @patch("operations.views.resolve_tenant_context", return_value=SimpleNamespace(active_tenant_id=20))
    @patch("operations.permissions.OperationsPermission.has_permission", return_value=True)
    @patch("operations.views.resolve_roles_and_permissions", return_value=(["LOGISTICS_MANAGER"], []))
    def test_item_allocation_preview_rejects_too_many_additional_warehouse_ids(
        self,
        _mock_roles,
        _mock_permission,
        _mock_tenant_context,
    ) -> None:
        response = self.client.post(
            "/api/v1/operations/packages/70/allocation-options/101/preview",
            {
                "additional_warehouse_ids": list(range(1, 102)),
                "draft_allocations": [],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {"errors": {"additional_warehouse_ids": "additional_warehouse_ids must not contain more than 100 items."}},
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
        self.active_event_patcher = patch("operations.views.data_access.get_active_event", return_value=None)
        self.active_event_patcher.start()
        self.addCleanup(self.active_event_patcher.stop)
        cache.clear()

    def tearDown(self) -> None:
        cache.clear()

    @staticmethod
    def _tenant_context(
        tenant_id: int,
        tenant_code: str,
        *,
        can_read_all_tenants: bool = False,
        can_act_cross_tenant: bool = False,
    ) -> TenantContext:
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
            can_read_all_tenants=can_read_all_tenants,
            can_act_cross_tenant=can_act_cross_tenant,
        )

    @staticmethod
    def _principal(user_id: str, permissions: list[str], roles: list[str] | None = None) -> Principal:
        return Principal(
            user_id=user_id,
            username=user_id,
            roles=roles or ["AGENCY_DISTRIBUTOR"],
            permissions=permissions,
        )

    @staticmethod
    def _legacy_request(reliefrqst_id: int, *, request_date: date, agency_id: int = 501) -> SimpleNamespace:
        return SimpleNamespace(
            reliefrqst_id=reliefrqst_id,
            agency_id=agency_id,
            request_date=request_date,
            tracking_no=f"RQ{reliefrqst_id:05d}",
            eligible_event_id=12,
            urgency_ind="H",
            rqst_notes_text=None,
            review_by_id=None,
            review_dtime=None,
            create_by_id="user-a",
            create_dtime=timezone.now(),
            status_code=0,
        )

    @staticmethod
    def _create_native_request(
        reliefrqst_id: int,
        *,
        status_code: str = REQUEST_STATUS_DRAFT,
        tenant_id: int = 10,
        owner_id: str = "user-a",
        origin_mode: str = ORIGIN_MODE_SELF,
    ) -> OperationsReliefRequest:
        return OperationsReliefRequest.objects.create(
            relief_request_id=reliefrqst_id,
            request_no=f"RQ{reliefrqst_id:05d}",
            requesting_tenant_id=tenant_id,
            requesting_agency_id=501,
            beneficiary_tenant_id=tenant_id,
            beneficiary_agency_id=501,
            origin_mode=origin_mode,
            event_id=12,
            request_date=date(2026, 4, 7),
            urgency_code="H",
            status_code=status_code,
            create_by_id=owner_id,
            update_by_id=owner_id,
        )

    @staticmethod
    def _ensure_rbac_tables_for_tests() -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS permission (
                    perm_id integer PRIMARY KEY,
                    resource varchar(100) NOT NULL,
                    action varchar(100) NOT NULL,
                    create_by_id varchar(20),
                    create_dtime timestamp with time zone,
                    update_by_id varchar(20),
                    update_dtime timestamp with time zone,
                    version_nbr integer,
                    UNIQUE (resource, action)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS role (
                    id integer GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    code varchar(80) NOT NULL UNIQUE,
                    name varchar(150),
                    description text,
                    created_at timestamp with time zone
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS "user" (
                    user_id integer GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    email varchar(255),
                    password_hash varchar(255),
                    first_name varchar(150),
                    last_name varchar(150),
                    full_name varchar(255),
                    username varchar(150),
                    user_name varchar(150),
                    is_active boolean DEFAULT TRUE
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS user_role (
                    user_id integer NOT NULL,
                    role_id integer NOT NULL,
                    assigned_at timestamp with time zone,
                    assigned_by varchar(20),
                    create_by_id varchar(20),
                    create_dtime timestamp with time zone,
                    update_by_id varchar(20),
                    update_dtime timestamp with time zone,
                    version_nbr integer,
                    PRIMARY KEY (user_id, role_id)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS role_permission (
                    role_id integer NOT NULL,
                    perm_id integer NOT NULL,
                    scope_json jsonb,
                    create_by_id varchar(20),
                    create_dtime timestamp with time zone,
                    update_by_id varchar(20),
                    update_dtime timestamp with time zone,
                    version_nbr integer,
                    PRIMARY KEY (role_id, perm_id)
                )
                """
            )

    @staticmethod
    def _ensure_permission(permission_key: str) -> int:
        OperationsApiTenantIsolationTests._ensure_rbac_tables_for_tests()
        resource, action = permission_key.rsplit(".", 1)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT perm_id FROM permission WHERE resource = %s AND action = %s LIMIT 1",
                [resource, action],
            )
            row = cursor.fetchone()
            if row:
                return int(row[0])
            cursor.execute("LOCK TABLE permission IN EXCLUSIVE MODE")
            cursor.execute("SELECT COALESCE(MAX(perm_id), 0) + 1 FROM permission")
            perm_id = int(cursor.fetchone()[0])
            cursor.execute(
                """
                INSERT INTO permission (
                    perm_id,
                    resource,
                    action,
                    create_by_id,
                    create_dtime,
                    update_by_id,
                    update_dtime,
                    version_nbr
                )
                VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP, %s, CURRENT_TIMESTAMP, 1)
                """,
                [perm_id, resource, action, "test-db-rbac", "test-db-rbac"],
            )
            return perm_id

    @staticmethod
    def _ensure_role(role_code: str) -> int:
        OperationsApiTenantIsolationTests._ensure_rbac_tables_for_tests()
        normalized_role = role_code.strip().upper()
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM role WHERE UPPER(code) = %s LIMIT 1", [normalized_role])
            row = cursor.fetchone()
            if row:
                return int(row[0])
            cursor.execute(
                """
                INSERT INTO role (code, name, description, created_at)
                VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                RETURNING id
                """,
                [normalized_role, normalized_role.replace("_", " ").title(), "Test role"],
            )
            return int(cursor.fetchone()[0])

    def _create_db_rbac_actor(
        self,
        *,
        username: str,
        role_code: str,
        permissions: list[str] | None = None,
    ) -> Principal:
        self._ensure_rbac_tables_for_tests()
        role_id = self._ensure_role(role_code)
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO "user" (
                    email,
                    password_hash,
                    first_name,
                    last_name,
                    full_name,
                    username,
                    user_name,
                    is_active
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE)
                RETURNING user_id
                """,
                [
                    f"{username}@example.test",
                    "not-used",
                    username,
                    "Actor",
                    f"{username} Actor",
                    username,
                    username,
                ],
            )
            user_id = int(cursor.fetchone()[0])
            cursor.execute(
                """
                INSERT INTO user_role (
                    user_id,
                    role_id,
                    assigned_at,
                    assigned_by,
                    create_by_id,
                    create_dtime,
                    update_by_id,
                    update_dtime,
                    version_nbr
                )
                VALUES (%s, %s, CURRENT_TIMESTAMP, %s, %s, CURRENT_TIMESTAMP, %s, CURRENT_TIMESTAMP, 1)
                """,
                [user_id, role_id, "test-db-rbac", "test-db-rbac", "test-db-rbac"],
            )
            for permission in permissions or []:
                perm_id = self._ensure_permission(permission)
                cursor.execute(
                    """
                    INSERT INTO role_permission (
                        role_id,
                        perm_id,
                        scope_json,
                        create_by_id,
                        create_dtime,
                        update_by_id,
                        update_dtime,
                        version_nbr
                    )
                    VALUES (%s, %s, %s::jsonb, %s, CURRENT_TIMESTAMP, %s, CURRENT_TIMESTAMP, 1)
                    ON CONFLICT (role_id, perm_id) DO NOTHING
                    """,
                    [role_id, perm_id, "{}", "test-db-rbac", "test-db-rbac"],
                )
        return Principal(user_id=str(user_id), username=username, roles=[], permissions=[])

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

    def _cancel_request(
        self,
        request_record: OperationsReliefRequest,
        *,
        actor: Principal,
        tenant_context: TenantContext,
        reason: str = "Duplicate intake",
        idempotency_key: str = "cancel-70",
    ):
        self.client.force_authenticate(user=actor)
        with (
            patch("operations.views.resolve_tenant_context", return_value=tenant_context),
            patch("operations.contract_services._load_request_record_for_workflow", return_value=(request_record, None)),
            patch(
                "operations.contract_services._compat_request_response",
                return_value={
                    "reliefrqst_id": request_record.relief_request_id,
                    "status_code": REQUEST_STATUS_CANCELLED,
                },
            ),
        ):
            with self.captureOnCommitCallbacks(execute=True):
                return self.client.post(
                    f"/api/v1/operations/requests/{request_record.relief_request_id}/cancel",
                    {"cancellation_reason": reason},
                    format="json",
                    HTTP_IDEMPOTENCY_KEY=idempotency_key,
                )

    def test_request_cancel_happy_path_from_each_allowed_state(self) -> None:
        for index, starting_status in enumerate(
            [REQUEST_STATUS_DRAFT, REQUEST_STATUS_SUBMITTED, REQUEST_STATUS_UNDER_ELIGIBILITY_REVIEW],
            start=1,
        ):
            with self.subTest(starting_status=starting_status):
                reliefrqst_id = 700 + index
                request_record = self._create_native_request(reliefrqst_id, status_code=starting_status)
                OperationsQueueAssignment.objects.create(
                    queue_code=QUEUE_CODE_ELIGIBILITY,
                    entity_type="RELIEF_REQUEST",
                    entity_id=reliefrqst_id,
                    assigned_role_code="DG",
                    assigned_tenant_id=10,
                )
                response = self._cancel_request(
                    request_record,
                    actor=self._principal("user-a", [PERM_OPERATIONS_REQUEST_CANCEL]),
                    tenant_context=self._tenant_context(10, "TENANT_A"),
                    reason="Duplicate request",
                    idempotency_key=f"cancel-{reliefrqst_id}",
                )

                self.assertEqual(response.status_code, 200)
                request_record.refresh_from_db()
                self.assertEqual(request_record.status_code, REQUEST_STATUS_CANCELLED)
                self.assertIsNotNone(request_record.cancelled_at)
                status_history = OperationsStatusHistory.objects.get(
                    entity_type="RELIEF_REQUEST",
                    entity_id=reliefrqst_id,
                    to_status_code=REQUEST_STATUS_CANCELLED,
                )
                self.assertEqual(status_history.from_status_code, starting_status)
                self.assertEqual(status_history.reason_text, "Duplicate request")
                action_audit = OperationsActionAudit.objects.get(
                    entity_type="RELIEF_REQUEST",
                    entity_id=reliefrqst_id,
                    action_code=ACTION_REQUEST_CANCELLED,
                )
                self.assertEqual(action_audit.acted_by_user_id, "user-a")
                self.assertEqual(action_audit.acted_by_role_code, "AGENCY_DISTRIBUTOR")
                self.assertEqual(action_audit.action_reason, "Duplicate request")
                queue_assignment = OperationsQueueAssignment.objects.get(
                    queue_code=QUEUE_CODE_ELIGIBILITY,
                    entity_type="RELIEF_REQUEST",
                    entity_id=reliefrqst_id,
                )
                self.assertEqual(queue_assignment.assignment_status, "CANCELLED")
                self.assertIsNotNone(queue_assignment.completed_at)
                self.assertTrue(
                    OperationsNotification.objects.filter(
                        event_code=EVENT_REQUEST_CANCELLED,
                        entity_type="RELIEF_REQUEST",
                        entity_id=reliefrqst_id,
                        message_text="Relief Request cancelled",
                    ).exists()
                )

    def test_request_cancel_blocks_non_cancellable_state(self) -> None:
        request_record = self._create_native_request(
            720,
            status_code=REQUEST_STATUS_APPROVED_FOR_FULFILLMENT,
        )

        response = self._cancel_request(
            request_record,
            actor=self._principal("user-a", [PERM_OPERATIONS_REQUEST_CANCEL]),
            tenant_context=self._tenant_context(10, "TENANT_A"),
            idempotency_key="cancel-state-720",
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["errors"]["status"]["code"], "request_not_cancellable")
        request_record.refresh_from_db()
        self.assertEqual(request_record.status_code, REQUEST_STATUS_APPROVED_FOR_FULFILLMENT)
        self.assertFalse(
            OperationsActionAudit.objects.filter(
                entity_type="RELIEF_REQUEST",
                entity_id=720,
                action_code=ACTION_REQUEST_CANCELLED,
            ).exists()
        )

    def test_request_cancel_denies_cross_tenant_probe_as_not_found(self) -> None:
        request_record = self._create_native_request(721, status_code=REQUEST_STATUS_DRAFT)

        response = self._cancel_request(
            request_record,
            actor=self._principal("user-b", [PERM_OPERATIONS_REQUEST_CANCEL]),
            tenant_context=self._tenant_context(20, "TENANT_B"),
            idempotency_key="cancel-cross-721",
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "Not found."})
        request_record.refresh_from_db()
        self.assertEqual(request_record.status_code, REQUEST_STATUS_DRAFT)

    def test_request_cancel_requires_cancel_permission(self) -> None:
        request_record = self._create_native_request(722, status_code=REQUEST_STATUS_DRAFT)
        self.client.force_authenticate(user=self._principal("user-a", [], roles=["DG"]))

        with (
            patch("operations.views.resolve_tenant_context", return_value=self._tenant_context(10, "TENANT_A")),
            patch("operations.views.operations_service.cancel_request") as mock_cancel_request,
        ):
            response = self.client.post(
                "/api/v1/operations/requests/722/cancel",
                {"cancellation_reason": "Duplicate intake"},
                format="json",
                HTTP_IDEMPOTENCY_KEY="cancel-perm-722",
            )

        self.assertEqual(response.status_code, 403)
        mock_cancel_request.assert_not_called()
        request_record.refresh_from_db()
        self.assertEqual(request_record.status_code, REQUEST_STATUS_DRAFT)

    @override_settings(AUTH_USE_DB_RBAC=True, TESTING=False, DEV_AUTH_ENABLED=False, AUTH_ENABLED=False)
    def test_request_cancel_allows_db_rbac_seeded_parish_requester(self) -> None:
        request_record = self._create_native_request(728, status_code=REQUEST_STATUS_DRAFT)
        actor = self._create_db_rbac_actor(
            username="db-rbac-cancel-requester",
            role_code="AGENCY_DISTRIBUTOR",
            permissions=[PERM_OPERATIONS_REQUEST_CANCEL],
        )
        self.client.force_authenticate(user=actor)

        with (
            patch("operations.views.resolve_tenant_context", return_value=self._tenant_context(10, "TENANT_A")),
            patch("operations.contract_services._load_request_record_for_workflow", return_value=(request_record, None)),
            patch(
                "operations.contract_services._compat_request_response",
                return_value={"reliefrqst_id": 728, "status_code": REQUEST_STATUS_CANCELLED},
            ),
        ):
            response = self.client.post(
                "/api/v1/operations/requests/728/cancel",
                {"cancellation_reason": "Duplicate intake"},
                format="json",
                HTTP_IDEMPOTENCY_KEY="cancel-db-rbac-728",
            )

        self.assertEqual(response.status_code, 200)
        request_record.refresh_from_db()
        self.assertEqual(request_record.status_code, REQUEST_STATUS_CANCELLED)

    @override_settings(AUTH_USE_DB_RBAC=True, TESTING=False, DEV_AUTH_ENABLED=False, AUTH_ENABLED=False)
    def test_request_cancel_denies_db_rbac_logistics_officer(self) -> None:
        request_record = self._create_native_request(729, status_code=REQUEST_STATUS_DRAFT)
        actor = self._create_db_rbac_actor(
            username="db-rbac-logistics-officer",
            role_code="LOGISTICS_OFFICER",
            permissions=["replenishment.needs_list.submit"],
        )
        self.client.force_authenticate(user=actor)

        with (
            patch("operations.views.resolve_tenant_context", return_value=self._tenant_context(10, "TENANT_A")),
            patch("operations.contract_services.cancel_request") as mock_cancel_request,
        ):
            response = self.client.post(
                "/api/v1/operations/requests/729/cancel",
                {"cancellation_reason": "Duplicate intake"},
                format="json",
                HTTP_IDEMPOTENCY_KEY="cancel-db-rbac-denied-729",
            )

        self.assertEqual(response.status_code, 403)
        mock_cancel_request.assert_not_called()
        request_record.refresh_from_db()
        self.assertEqual(request_record.status_code, REQUEST_STATUS_DRAFT)

    def test_request_cancel_validates_reason(self) -> None:
        request_record = self._create_native_request(723, status_code=REQUEST_STATUS_DRAFT)
        actor = self._principal("user-a", [PERM_OPERATIONS_REQUEST_CANCEL])
        tenant_context = self._tenant_context(10, "TENANT_A")

        empty_response = self._cancel_request(
            request_record,
            actor=actor,
            tenant_context=tenant_context,
            reason="   ",
            idempotency_key="cancel-empty-723",
        )
        long_response = self._cancel_request(
            request_record,
            actor=actor,
            tenant_context=tenant_context,
            reason="x" * 501,
            idempotency_key="cancel-long-723",
        )

        self.assertEqual(empty_response.status_code, 400)
        self.assertEqual(empty_response.json()["errors"]["cancellation_reason"], "Cancellation reason is required.")
        self.assertEqual(long_response.status_code, 400)
        self.assertEqual(
            long_response.json()["errors"]["cancellation_reason"],
            "Cancellation reason must be 500 characters or fewer.",
        )
        request_record.refresh_from_db()
        self.assertEqual(request_record.status_code, REQUEST_STATUS_DRAFT)

    def test_request_cancel_idempotency_replay_does_not_duplicate_side_effects(self) -> None:
        request_record = self._create_native_request(724, status_code=REQUEST_STATUS_DRAFT)
        actor = self._principal("user-a", [PERM_OPERATIONS_REQUEST_CANCEL])
        tenant_context = self._tenant_context(10, "TENANT_A")

        first_response = self._cancel_request(
            request_record,
            actor=actor,
            tenant_context=tenant_context,
            reason="Duplicate intake",
            idempotency_key="cancel-replay-724",
        )
        second_response = self._cancel_request(
            request_record,
            actor=actor,
            tenant_context=tenant_context,
            reason="Duplicate intake",
            idempotency_key="cancel-replay-724",
        )

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(second_response.json(), first_response.json())
        self.assertEqual(
            OperationsStatusHistory.objects.filter(
                entity_type="RELIEF_REQUEST",
                entity_id=724,
                to_status_code=REQUEST_STATUS_CANCELLED,
            ).count(),
            1,
        )
        self.assertEqual(
            OperationsActionAudit.objects.filter(
                entity_type="RELIEF_REQUEST",
                entity_id=724,
                action_code=ACTION_REQUEST_CANCELLED,
            ).count(),
            1,
        )

    def test_request_cancel_legacy_database_error_rolls_back_native_and_audit(self) -> None:
        request_record = self._create_native_request(730, status_code=REQUEST_STATUS_DRAFT)

        class LegacyRequest:
            status_code = 0
            version_nbr = 0

            def save(self, **_kwargs):
                raise DatabaseError("legacy cancel write failed")

        with patch(
            "operations.contract_services._load_request_record_for_workflow",
            return_value=(request_record, LegacyRequest()),
        ):
            with self.assertRaises(DatabaseError):
                operations_service.cancel_request(
                    730,
                    payload={"cancellation_reason": "Duplicate intake"},
                    actor_id="user-a",
                    actor_roles=["AGENCY_DISTRIBUTOR"],
                    tenant_context=self._tenant_context(10, "TENANT_A"),
                    permissions=[PERM_OPERATIONS_REQUEST_CANCEL],
                    idempotency_key="cancel-db-error-730",
                )

        request_record.refresh_from_db()
        self.assertEqual(request_record.status_code, REQUEST_STATUS_DRAFT)
        self.assertFalse(
            OperationsStatusHistory.objects.filter(
                entity_type="RELIEF_REQUEST",
                entity_id=730,
                to_status_code=REQUEST_STATUS_CANCELLED,
            ).exists()
        )
        self.assertFalse(
            OperationsActionAudit.objects.filter(
                entity_type="RELIEF_REQUEST",
                entity_id=730,
                action_code=ACTION_REQUEST_CANCELLED,
            ).exists()
        )

    @patch("operations.contract_services.legacy_service.update_request", return_value={"reliefrqst_id": 725})
    @patch("operations.contract_services.operations_policy.validate_relief_request_agency_selection")
    @patch("operations.contract_services._legacy_helper")
    @patch("operations.views.resolve_tenant_context")
    def test_request_patch_denies_cross_tenant_probe_as_not_found(
        self,
        mock_resolve_tenant_context,
        mock_legacy_helper,
        _mock_validate_agency_selection,
        mock_update_request,
    ) -> None:
        request_date = date(2026, 4, 7)
        self._create_native_request(725, status_code=REQUEST_STATUS_DRAFT)
        mock_legacy_helper.return_value = lambda *_args, **_kwargs: self._legacy_request(725, request_date=request_date)
        tenant_contexts = {
            "user-b": self._tenant_context(20, "TENANT_B"),
        }
        mock_resolve_tenant_context.side_effect = (
            lambda request, user, permissions: tenant_contexts[str(user.user_id)]
        )

        self.client.force_authenticate(
            user=self._principal("user-b", [PERM_OPERATIONS_REQUEST_EDIT_DRAFT])
        )
        response = self.client.patch(
            "/api/v1/operations/requests/725",
            {"rqst_notes_text": "Cross-tenant edit attempt"},
            format="json",
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "Not found."})
        mock_update_request.assert_not_called()

    @patch("operations.contract_services.legacy_service.submit_request")
    @patch("operations.contract_services._legacy_helper")
    @patch("operations.views.resolve_tenant_context")
    def test_request_submit_denies_cross_tenant_probe_as_not_found(
        self,
        mock_resolve_tenant_context,
        mock_legacy_helper,
        mock_submit_request,
    ) -> None:
        request_date = date(2026, 4, 7)
        self._create_native_request(726, status_code=REQUEST_STATUS_DRAFT)
        mock_legacy_helper.return_value = lambda *_args, **_kwargs: self._legacy_request(726, request_date=request_date)
        tenant_contexts = {
            "user-b": self._tenant_context(20, "TENANT_B"),
        }
        mock_resolve_tenant_context.side_effect = (
            lambda request, user, permissions: tenant_contexts[str(user.user_id)]
        )

        self.client.force_authenticate(
            user=self._principal("user-b", [PERM_OPERATIONS_REQUEST_SUBMIT])
        )
        response = self.client.post(
            "/api/v1/operations/requests/726/submit",
            {},
            format="json",
            HTTP_IDEMPOTENCY_KEY="submit-cross-726",
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "Not found."})
        mock_submit_request.assert_not_called()

    def _seed_audit_timeline_request(self) -> OperationsReliefRequest:
        request_record = self._create_native_request(727, status_code=REQUEST_STATUS_DRAFT, origin_mode="ODPEM_BRIDGE")
        OperationsStatusHistory.objects.create(
            entity_type="RELIEF_REQUEST",
            entity_id=727,
            from_status_code=None,
            to_status_code=REQUEST_STATUS_DRAFT,
            changed_by_id="user-a",
            changed_at=timezone.make_aware(datetime(2026, 4, 7, 9, 0, 0)),
        )
        OperationsActionAudit.objects.create(
            entity_type="RELIEF_REQUEST",
            entity_id=727,
            tenant_id=10,
            action_code=ACTION_REQUEST_BRIDGE_CREATED,
            action_reason="ODPEM created bridge request",
            acted_by_user_id="odpem-bridge",
            acted_by_role_code="ODPEM_BRIDGE_REQUESTER",
            acted_at=timezone.make_aware(datetime(2026, 4, 7, 9, 5, 0)),
        )
        OperationsActionAudit.objects.create(
            entity_type="RELIEF_REQUEST",
            entity_id=727,
            tenant_id=10,
            action_code=ACTION_REQUEST_CANCELLED,
            action_reason="Duplicate bridge request",
            acted_by_user_id="user-a",
            acted_by_role_code="AGENCY_DISTRIBUTOR",
            acted_at=timezone.make_aware(datetime(2026, 4, 7, 9, 10, 0)),
        )
        OperationsStatusHistory.objects.create(
            entity_type="RELIEF_REQUEST",
            entity_id=727,
            from_status_code=REQUEST_STATUS_DRAFT,
            to_status_code=REQUEST_STATUS_CANCELLED,
            changed_by_id="user-a",
            changed_at=timezone.make_aware(datetime(2026, 4, 7, 9, 15, 0)),
            reason_text="Duplicate bridge request",
        )
        return request_record

    def _get_detail_with_audit_timeline(
        self,
        *,
        actor: Principal,
        tenant_context: TenantContext,
    ):
        request_date = date(2026, 4, 7)
        legacy_request = self._legacy_request(727, request_date=request_date)
        self.client.force_authenticate(user=actor)
        with (
            patch("operations.contract_services.legacy_service._request_summary", return_value={"status_code": "DRAFT"}),
            patch(
                "operations.contract_services.legacy_service.get_request",
                return_value={"reliefrqst_id": 727, "tracking_no": "RQ00727"},
            ),
            patch("operations.contract_services.ReliefPkg.objects.filter") as mock_reliefpkg_filter,
            patch("operations.contract_services._legacy_helper", return_value=lambda *_args, **_kwargs: legacy_request),
            patch("operations.views.resolve_tenant_context", return_value=tenant_context),
        ):
            mock_reliefpkg_filter.return_value.order_by.return_value = []
            return self.client.get("/api/v1/operations/requests/727")

    def test_request_detail_includes_same_tenant_audit_timeline(self) -> None:
        self._seed_audit_timeline_request()

        response = self._get_detail_with_audit_timeline(
            actor=self._principal("user-a", [PERM_OPERATIONS_REQUEST_EDIT_DRAFT]),
            tenant_context=self._tenant_context(10, "TENANT_A"),
        )

        self.assertEqual(response.status_code, 200)
        timeline = response.json()["audit_timeline"]
        self.assertEqual([event["event_kind"] for event in timeline], ["STATUS_TRANSITION", "ACTION_AUDIT", "ACTION_AUDIT", "STATUS_TRANSITION"])
        self.assertEqual(timeline[0]["actor_user_label"], "User ...er-a")
        self.assertTrue(all("user-a" not in str(event["actor_user_label"] or "") for event in timeline))
        self.assertEqual(timeline[1]["action_code"], ACTION_REQUEST_BRIDGE_CREATED)
        self.assertEqual(timeline[1]["actor_role_code"], "ODPEM_BRIDGE_REQUESTER")
        self.assertEqual(timeline[2]["action_code"], ACTION_REQUEST_CANCELLED)
        self.assertEqual(timeline[2]["action_reason"], "Duplicate bridge request")
        self.assertEqual(timeline[3]["to_status_code"], REQUEST_STATUS_CANCELLED)

    def test_request_detail_masks_uuid_audit_actor_user_label(self) -> None:
        self._seed_audit_timeline_request()
        raw_actor_id = "550e8400-e29b-41d4-a716-446655440000"
        OperationsActionAudit.objects.filter(
            entity_type="RELIEF_REQUEST",
            entity_id=727,
            action_code=ACTION_REQUEST_CANCELLED,
        ).update(acted_by_user_id=raw_actor_id)

        response = self._get_detail_with_audit_timeline(
            actor=self._principal("user-a", [PERM_OPERATIONS_REQUEST_EDIT_DRAFT]),
            tenant_context=self._tenant_context(10, "TENANT_A"),
        )

        self.assertEqual(response.status_code, 200)
        timeline = response.json()["audit_timeline"]
        self.assertEqual(timeline[2]["actor_user_label"], "User ...0000")
        self.assertTrue(all(raw_actor_id not in str(event["actor_user_label"] or "") for event in timeline))

    def test_request_detail_redacts_cross_tenant_audit_actor_fields(self) -> None:
        self._seed_audit_timeline_request()
        OperationsQueueAssignment.objects.create(
            queue_code=QUEUE_CODE_ELIGIBILITY,
            entity_type="RELIEF_REQUEST",
            entity_id=727,
            assigned_user_id="user-b",
            assigned_tenant_id=20,
        )

        response = self._get_detail_with_audit_timeline(
            actor=self._principal("user-b", [PERM_OPERATIONS_QUEUE_VIEW]),
            tenant_context=self._tenant_context(20, "TENANT_B"),
        )

        self.assertEqual(response.status_code, 200)
        timeline = response.json()["audit_timeline"]
        self.assertEqual([event["occurred_at"] for event in timeline], sorted(event["occurred_at"] for event in timeline))
        self.assertTrue(all(event["actor_role_code"] is None for event in timeline))
        self.assertTrue(all(event["actor_user_label"] is None for event in timeline))
        self.assertEqual(timeline[1]["action_code"], ACTION_REQUEST_BRIDGE_CREATED)
        self.assertEqual(timeline[2]["action_code"], ACTION_REQUEST_CANCELLED)

    def test_request_detail_keeps_audit_actor_fields_for_national_override(self) -> None:
        self._seed_audit_timeline_request()

        response = self._get_detail_with_audit_timeline(
            actor=self._principal("national-user", [PERM_OPERATIONS_QUEUE_VIEW], roles=["ODPEM_DG"]),
            tenant_context=self._tenant_context(
                27,
                "ODPEM",
                can_read_all_tenants=True,
                can_act_cross_tenant=True,
            ),
        )

        self.assertEqual(response.status_code, 200)
        timeline = response.json()["audit_timeline"]
        self.assertEqual(timeline[1]["actor_role_code"], "ODPEM_BRIDGE_REQUESTER")
        self.assertEqual(timeline[1]["actor_user_label"], "User ...idge")
        self.assertEqual(timeline[2]["actor_role_code"], "AGENCY_DISTRIBUTOR")
        self.assertEqual(timeline[2]["actor_user_label"], "User ...er-a")


class OperationsViewHelperTests(SimpleTestCase):
    def setUp(self) -> None:
        self.factory = RequestFactory()
        self.client = APIClient()
        self.active_event_patcher = patch("operations.views.data_access.get_active_event", return_value=None)
        self.active_event_patcher.start()
        self.addCleanup(self.active_event_patcher.stop)
        cache.clear()

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
