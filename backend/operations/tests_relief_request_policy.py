from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from api.rbac import (
    PERM_OPERATIONS_REQUEST_CREATE_FOR_SUBORDINATE,
    PERM_OPERATIONS_REQUEST_CREATE_ON_BEHALF_BRIDGE,
    PERM_OPERATIONS_REQUEST_CREATE_SELF,
)
from api.tenancy import TenantContext, TenantMembership
from operations.constants import ORIGIN_MODE_FOR_SUBORDINATE, ORIGIN_MODE_ODPEM_BRIDGE
from operations import policy as operations_policy
from operations import services as operations_service
from operations.exceptions import OperationValidationError


def _tenant_context(
    *,
    tenant_id: int,
    tenant_code: str,
    tenant_type: str,
    access_level: str = "ADMIN",
    can_act_cross_tenant: bool = False,
) -> TenantContext:
    membership = TenantMembership(
        tenant_id=tenant_id,
        tenant_code=tenant_code,
        tenant_name=f"Tenant {tenant_id}",
        tenant_type=tenant_type,
        is_primary=True,
        access_level=access_level,
    )
    return TenantContext(
        requested_tenant_id=tenant_id,
        active_tenant_id=tenant_id,
        active_tenant_code=tenant_code,
        active_tenant_type=tenant_type,
        memberships=(membership,),
        can_read_all_tenants=can_act_cross_tenant,
        can_act_cross_tenant=can_act_cross_tenant,
    )


class ReliefRequestCapabilityTests(SimpleTestCase):
    def test_non_odpem_self_service_capabilities_are_explicit(self) -> None:
        capabilities = operations_policy.get_relief_request_capabilities(
            tenant_context=_tenant_context(tenant_id=20, tenant_code="FFP", tenant_type="EXTERNAL"),
            permissions=[PERM_OPERATIONS_REQUEST_CREATE_SELF],
        )

        self.assertTrue(capabilities["can_create_relief_request"])
        self.assertFalse(capabilities["can_create_relief_request_on_behalf"])
        self.assertEqual(capabilities["relief_request_submission_mode"], "self")
        self.assertEqual(capabilities["default_requesting_tenant_id"], 20)
        self.assertEqual(capabilities["allowed_origin_modes"], ["self"])

    def test_odpem_on_behalf_capabilities_are_explicit(self) -> None:
        capabilities = operations_policy.get_relief_request_capabilities(
            tenant_context=_tenant_context(
                tenant_id=27,
                tenant_code="OFFICE-OF-DISASTER-P",
                tenant_type="NATIONAL",
                can_act_cross_tenant=True,
            ),
            permissions=[PERM_OPERATIONS_REQUEST_CREATE_ON_BEHALF_BRIDGE],
        )

        self.assertTrue(capabilities["can_create_relief_request"])
        self.assertTrue(capabilities["can_create_relief_request_on_behalf"])
        self.assertEqual(capabilities["relief_request_submission_mode"], "on_behalf_bridge")
        self.assertEqual(capabilities["default_requesting_tenant_id"], 27)
        self.assertEqual(capabilities["allowed_origin_modes"], ["on_behalf_bridge"])

    def test_subordinate_request_capability_is_explicit(self) -> None:
        capabilities = operations_policy.get_relief_request_capabilities(
            tenant_context=_tenant_context(tenant_id=14, tenant_code="PARISH-KN", tenant_type="PARISH"),
            permissions=[PERM_OPERATIONS_REQUEST_CREATE_FOR_SUBORDINATE],
        )

        self.assertTrue(capabilities["can_create_relief_request"])
        self.assertTrue(capabilities["can_create_relief_request_on_behalf"])
        self.assertEqual(capabilities["relief_request_submission_mode"], "for_subordinate")
        self.assertEqual(capabilities["allowed_origin_modes"], ["for_subordinate"])


class ReliefRequestAgencyPolicyTests(SimpleTestCase):
    @patch("operations.policy.get_agency_scope")
    def test_non_odpem_tenant_can_create_for_allowed_agency_scope(self, get_agency_scope_mock) -> None:
        get_agency_scope_mock.return_value = operations_policy.AgencyScope(
            agency_id=501,
            agency_name="Food For The Poor Shelter",
            agency_type="SHELTER",
            warehouse_id=11,
            tenant_id=20,
            tenant_code="FFP",
            tenant_name="Food For The Poor",
            tenant_type="EXTERNAL",
        )

        decision = operations_policy.validate_relief_request_agency_selection(
            agency_id=501,
            tenant_context=_tenant_context(tenant_id=20, tenant_code="FFP", tenant_type="EXTERNAL"),
        )

        self.assertEqual(decision.submission_mode, "self")
        self.assertEqual(decision.agency_scope.tenant_id, 20)

    @patch("operations.policy.get_agency_scope")
    def test_non_odpem_tenant_cannot_create_for_out_of_scope_agency(self, get_agency_scope_mock) -> None:
        get_agency_scope_mock.return_value = operations_policy.AgencyScope(
            agency_id=777,
            agency_name="Parish Shelter",
            agency_type="SHELTER",
            warehouse_id=12,
            tenant_id=21,
            tenant_code="UNOPS",
            tenant_name="UNOPS",
            tenant_type="EXTERNAL",
        )

        with self.assertRaises(OperationValidationError) as raised:
            operations_policy.validate_relief_request_agency_selection(
                agency_id=777,
                tenant_context=_tenant_context(tenant_id=20, tenant_code="FFP", tenant_type="EXTERNAL"),
            )

        self.assertEqual(raised.exception.errors["agency_id"]["code"], "agency_out_of_scope")

    @patch("operations.policy._tenant_allows_relief_request_on_behalf", return_value=True)
    @patch("operations.policy.get_agency_scope")
    def test_odpem_can_create_on_behalf_for_non_odpem_agency(
        self,
        get_agency_scope_mock,
        _allow_on_behalf_mock,
    ) -> None:
        get_agency_scope_mock.return_value = operations_policy.AgencyScope(
            agency_id=888,
            agency_name="Community Distributor",
            agency_type="DISTRIBUTOR",
            warehouse_id=14,
            tenant_id=19,
            tenant_code="JRC",
            tenant_name="Jamaica Red Cross",
            tenant_type="EXTERNAL",
        )

        decision = operations_policy.validate_relief_request_agency_selection(
            agency_id=888,
            tenant_context=_tenant_context(
                tenant_id=27,
                tenant_code="OFFICE-OF-DISASTER-P",
                tenant_type="NATIONAL",
                can_act_cross_tenant=True,
            ),
        )

        self.assertEqual(decision.submission_mode, "on_behalf_bridge")
        self.assertEqual(decision.agency_scope.tenant_code, "JRC")

    @patch("operations.policy.get_agency_scope")
    def test_odpem_cannot_select_odpem_owned_agency_for_on_behalf_flow(self, get_agency_scope_mock) -> None:
        get_agency_scope_mock.return_value = operations_policy.AgencyScope(
            agency_id=95001,
            agency_name="ODPEM Logistics Test Agency",
            agency_type="DISTRIBUTOR",
            warehouse_id=1,
            tenant_id=27,
            tenant_code="OFFICE-OF-DISASTER-P",
            tenant_name="ODPEM",
            tenant_type="NATIONAL",
        )

        with self.assertRaises(OperationValidationError) as raised:
            operations_policy.validate_relief_request_agency_selection(
                agency_id=95001,
                tenant_context=_tenant_context(
                    tenant_id=27,
                    tenant_code="OFFICE-OF-DISASTER-P",
                    tenant_type="NATIONAL",
                    can_act_cross_tenant=True,
                ),
            )

        self.assertEqual(raised.exception.errors["agency_id"]["code"], "odpem_on_behalf_external_only")

    @patch("operations.policy.get_agency_scope")
    def test_odpem_without_cross_tenant_authority_cannot_create_on_behalf(self, get_agency_scope_mock) -> None:
        get_agency_scope_mock.return_value = operations_policy.AgencyScope(
            agency_id=889,
            agency_name="Community Shelter",
            agency_type="SHELTER",
            warehouse_id=15,
            tenant_id=19,
            tenant_code="JRC",
            tenant_name="Jamaica Red Cross",
            tenant_type="EXTERNAL",
        )

        with self.assertRaises(OperationValidationError) as raised:
            operations_policy.validate_relief_request_agency_selection(
                agency_id=889,
                tenant_context=_tenant_context(
                    tenant_id=27,
                    tenant_code="OFFICE-OF-DISASTER-P",
                    tenant_type="NATIONAL",
                    can_act_cross_tenant=False,
                ),
            )

        self.assertEqual(raised.exception.errors["agency_id"]["code"], "on_behalf_not_allowed")


class ReliefRequestServiceTests(TestCase):
    @patch("operations.services.get_request", return_value={"reliefrqst_id": 77, "tracking_no": "RQ00077"})
    @patch("operations.services._upsert_request_items")
    @patch("operations.services.ReliefRqst.objects.create")
    @patch("operations.services._next_int_id", return_value=77)
    @patch("operations.services.operations_policy.validate_relief_request_agency_selection")
    @patch("operations.services.timezone.now", return_value=datetime(2026, 3, 25, 9, 30, 0))
    def test_request_date_remains_system_generated_on_create(
        self,
        _now_mock,
        validate_scope_mock,
        _next_int_id_mock,
        create_request_mock,
        _upsert_request_items_mock,
        _get_request_mock,
    ) -> None:
        tenant_context = _tenant_context(tenant_id=20, tenant_code="FFP", tenant_type="EXTERNAL")
        validate_scope_mock.return_value = operations_policy.ReliefRequestWriteDecision(
            agency_scope=operations_policy.AgencyScope(
                agency_id=501,
                agency_name="Food For The Poor Shelter",
                agency_type="SHELTER",
                warehouse_id=11,
                tenant_id=20,
                tenant_code="FFP",
                tenant_name="Food For The Poor",
                tenant_type="EXTERNAL",
            ),
            origin_mode=operations_policy.ORIGIN_MODE_SELF,
            requesting_tenant_id=20,
            beneficiary_tenant_id=20,
            requesting_agency_id=501,
            beneficiary_agency_id=501,
        )

        operations_service.create_request(
            payload={
                "agency_id": 501,
                "urgency_ind": "M",
                "request_date": "2026-01-01",
                "items": [{"item_id": 101, "request_qty": "3"}],
            },
            actor_id="user-1",
            tenant_context=tenant_context,
            permissions=[PERM_OPERATIONS_REQUEST_CREATE_SELF],
        )

        validate_scope_mock.assert_called_once_with(agency_id=501, tenant_context=tenant_context)
        self.assertEqual(create_request_mock.call_args.kwargs["request_date"].isoformat(), "2026-03-25")

    @patch("operations.services.ReliefRqst.objects.create")
    @patch("operations.services.operations_policy.validate_relief_request_agency_selection")
    def test_self_only_requester_cannot_create_for_subordinate_requests(
        self,
        validate_scope_mock,
        create_request_mock,
    ) -> None:
        validate_scope_mock.return_value = operations_policy.ReliefRequestWriteDecision(
            agency_scope=operations_policy.AgencyScope(
                agency_id=501,
                agency_name="Shelter A",
                agency_type="SHELTER",
                warehouse_id=11,
                tenant_id=30,
                tenant_code="PARISH-30",
                tenant_name="Parish 30",
                tenant_type="PARISH",
            ),
            origin_mode=ORIGIN_MODE_FOR_SUBORDINATE,
            requesting_tenant_id=20,
            beneficiary_tenant_id=30,
            beneficiary_agency_id=501,
        )
        tenant_context = _tenant_context(tenant_id=20, tenant_code="FFP", tenant_type="EXTERNAL")

        with self.assertRaises(OperationValidationError) as raised:
            operations_service.create_request(
                payload={
                    "agency_id": 501,
                    "urgency_ind": "M",
                    "items": [{"item_id": 101, "request_qty": "3"}],
                },
                actor_id="user-1",
                tenant_context=tenant_context,
                permissions=[PERM_OPERATIONS_REQUEST_CREATE_SELF],
            )

        self.assertEqual(
            raised.exception.errors["origin_mode"]["required_permission"],
            PERM_OPERATIONS_REQUEST_CREATE_FOR_SUBORDINATE,
        )
        create_request_mock.assert_not_called()

    @patch("operations.services.ReliefRqst.objects.create")
    @patch("operations.services.operations_policy.validate_relief_request_agency_selection")
    def test_self_only_requester_cannot_create_odpem_bridge_requests(
        self,
        validate_scope_mock,
        create_request_mock,
    ) -> None:
        validate_scope_mock.return_value = operations_policy.ReliefRequestWriteDecision(
            agency_scope=operations_policy.AgencyScope(
                agency_id=777,
                agency_name="Community A",
                agency_type="COMMUNITY",
                warehouse_id=14,
                tenant_id=88,
                tenant_code="COMM-88",
                tenant_name="Community 88",
                tenant_type="COMMUNITY",
            ),
            origin_mode=ORIGIN_MODE_ODPEM_BRIDGE,
            requesting_tenant_id=27,
            beneficiary_tenant_id=88,
            beneficiary_agency_id=777,
        )
        tenant_context = _tenant_context(
            tenant_id=27,
            tenant_code="OFFICE-OF-DISASTER-P",
            tenant_type="NATIONAL",
            can_act_cross_tenant=True,
        )

        with self.assertRaises(OperationValidationError) as raised:
            operations_service.create_request(
                payload={
                    "agency_id": 777,
                    "urgency_ind": "M",
                    "items": [{"item_id": 101, "request_qty": "2"}],
                },
                actor_id="user-1",
                tenant_context=tenant_context,
                permissions=[PERM_OPERATIONS_REQUEST_CREATE_SELF],
            )

        self.assertEqual(
            raised.exception.errors["origin_mode"]["required_permission"],
            PERM_OPERATIONS_REQUEST_CREATE_ON_BEHALF_BRIDGE,
        )
        create_request_mock.assert_not_called()

    @patch("operations.services.get_request", return_value={"reliefrqst_id": 88, "status_label": "Awaiting Approval"})
    @patch("operations.services._request_item_rows_for_allocation", return_value=[{"item_id": 101, "request_qty": "1", "issue_qty": "0"}])
    @patch("operations.services._load_request")
    @patch("operations.services.operations_policy.validate_relief_request_agency_selection")
    def test_submit_request_revalidates_existing_agency_scope(
        self,
        validate_scope_mock,
        load_request_mock,
        _request_items_mock,
        _get_request_mock,
    ) -> None:
        request_record = SimpleNamespace(agency_id=501, status_code=operations_service.STATUS_DRAFT, version_nbr=1)
        request_record.save = lambda **kwargs: None
        load_request_mock.return_value = request_record
        tenant_context = _tenant_context(tenant_id=20, tenant_code="FFP", tenant_type="EXTERNAL")

        operations_service.submit_request(88, actor_id="user-1", tenant_context=tenant_context)

        validate_scope_mock.assert_called_once_with(agency_id=501, tenant_context=tenant_context)

    @patch("operations.services.validate_override_approval")
    @patch("operations.services._apply_package_header_updates")
    @patch("operations.services._apply_stock_delta_for_rows")
    @patch("operations.services._upsert_package_rows")
    @patch(
        "operations.services.build_greedy_allocation_plan",
        return_value=(
            [
                {
                    "item_id": 101,
                    "inventory_id": 1,
                    "batch_id": 1002,
                    "quantity": Decimal("2.0000"),
                    "source_type": "ON_HAND",
                    "source_record_id": None,
                    "uom_code": None,
                }
            ],
            Decimal("0"),
        ),
    )
    @patch("operations.services.sort_batch_candidates", return_value=[])
    @patch("operations.services._fetch_batch_candidates", return_value=[])
    @patch("operations.services.Item.objects.filter")
    @patch("operations.services._request_item_rows_for_allocation", return_value=[{"item_id": 101}])
    @patch("operations.services._resolve_candidate_warehouse_ids", return_value=[1])
    @patch("operations.services._current_package_status", return_value="A")
    @patch("operations.services._ensure_package")
    @patch("operations.services._load_request")
    @patch("operations.services._execution_link_for_request", return_value=None)
    def test_approved_override_uses_request_creator_and_commits_stock(
        self,
        _execution_link_mock,
        load_request_mock,
        ensure_package_mock,
        _current_status_mock,
        _warehouse_ids_mock,
        _request_rows_mock,
        item_filter_mock,
        _batch_candidates_mock,
        _sort_candidates_mock,
        _allocation_plan_mock,
        upsert_rows_mock,
        stock_delta_mock,
        header_updates_mock,
        validate_override_mock,
    ) -> None:
        load_request_mock.return_value = SimpleNamespace(create_by_id="planner-1", tracking_no="RQ00088")
        ensure_package_mock.return_value = SimpleNamespace(reliefpkg_id=90, tracking_no="PK00090")
        item_filter_mock.return_value = [SimpleNamespace(item_id=101)]

        result = operations_service._save_package_allocation(
            88,
            payload={
                "allocations": [
                    {
                        "item_id": 101,
                        "inventory_id": 1,
                        "batch_id": 1001,
                        "quantity": "2",
                    }
                ],
                "override_reason_code": "FEFO_BYPASS",
                "override_note": "Approved by supervisor",
            },
            actor_id="manager-1",
            allow_pending_override=False,
            supervisor_user_id="manager-1",
            supervisor_role_codes=["LOGISTICS_MANAGER"],
        )

        self.assertEqual(result["status"], "COMMITTED")
        validate_override_mock.assert_called_once_with(
            approver_user_id="manager-1",
            approver_role_codes=["LOGISTICS_MANAGER"],
            submitter_user_id="planner-1",
            needs_list_submitted_by="planner-1",
        )
        upsert_rows_mock.assert_called_once()
        stock_delta_mock.assert_called_once()
        self.assertEqual(header_updates_mock.call_args.kwargs["status_code"], operations_service.PKG_STATUS_PENDING)

    @patch("operations.services.get_request", return_value={"reliefrqst_id": 70, "status_label": "Draft"})
    @patch("operations.services.operations_policy.validate_relief_request_agency_selection")
    def test_partial_update_preserves_existing_notes_when_omitted(
        self,
        validate_scope_mock,
        _get_request_mock,
    ) -> None:
        tenant_context = _tenant_context(tenant_id=20, tenant_code="FFP", tenant_type="EXTERNAL")
        validate_scope_mock.return_value = operations_policy.ReliefRequestWriteDecision(
            agency_scope=operations_policy.AgencyScope(
                agency_id=501,
                agency_name="Food For The Poor Shelter",
                agency_type="SHELTER",
                warehouse_id=11,
                tenant_id=20,
                tenant_code="FFP",
                tenant_name="Food For The Poor",
                tenant_type="EXTERNAL",
            ),
            origin_mode=operations_policy.ORIGIN_MODE_SELF,
            requesting_tenant_id=20,
            beneficiary_tenant_id=20,
            requesting_agency_id=501,
            beneficiary_agency_id=501,
        )
        saved: dict[str, object] = {}
        request_record = SimpleNamespace(
            reliefrqst_id=70,
            agency_id=501,
            status_code=operations_service.STATUS_DRAFT,
            urgency_ind="M",
            eligible_event_id=None,
            rqst_notes_text="Keep this note",
            version_nbr=4,
            save=lambda **kwargs: saved.update(kwargs),
        )

        with patch("operations.services._load_request", return_value=request_record):
            operations_service.update_request(
                70,
                payload={"urgency_ind": "H"},
                actor_id="user-1",
                tenant_context=tenant_context,
                permissions=[PERM_OPERATIONS_REQUEST_CREATE_SELF],
            )

        self.assertEqual(request_record.rqst_notes_text, "Keep this note")
        self.assertNotIn("rqst_notes_text", list(saved.get("update_fields", [])))

    def test_existing_package_destination_can_be_updated_after_initial_draft_save(self) -> None:
        saved: dict[str, object] = {}
        package = SimpleNamespace(
            reliefpkg_id=90,
            to_inventory_id=0,
            transport_mode=None,
            comments_text=None,
            version_nbr=1,
            save=lambda **kwargs: saved.update(kwargs),
        )

        with patch("operations.services._current_package_for_request", return_value=package):
            result = operations_service._ensure_package(
                70,
                actor_id="planner-1",
                payload={"to_inventory_id": "9"},
            )

        self.assertIs(result, package)
        self.assertEqual(package.to_inventory_id, 9)
        self.assertIn("to_inventory_id", list(saved.get("update_fields", [])))

    @patch("operations.services.data_access.get_warehouse_name", return_value="Destination Warehouse")
    @patch("operations.services.data_access.get_event_name", return_value="Flood 2026")
    @patch("operations.services.data_access.get_warehouse_names", return_value=({4: "Source Warehouse"}, None))
    def test_waybill_payload_uses_package_dispatch_timestamp(
        self,
        _warehouse_names_mock,
        _event_name_mock,
        _warehouse_name_mock,
    ) -> None:
        dispatch_time = datetime(2026, 3, 26, 12, 30, 0)
        payload = operations_service._operations_waybill_payload(
            request=SimpleNamespace(
                tracking_no="RQ00070",
                agency_id=501,
                eligible_event_id=12,
            ),
            package=SimpleNamespace(
                tracking_no="PK00090",
                to_inventory_id=8,
                dispatch_dtime=dispatch_time,
                transport_mode="TRUCK",
            ),
            dispatched_rows=[
                {
                    "item_id": 101,
                    "inventory_id": 4,
                    "batch_id": 1001,
                    "batch_no": "BATCH-1001",
                    "quantity": Decimal("2"),
                    "uom_code": "EA",
                    "source_type": "ON_HAND",
                    "source_record_id": None,
                }
            ],
            actor_id="dispatch-1",
        )

        self.assertEqual(payload["dispatch_dtime"], operations_service._as_iso(dispatch_time))
