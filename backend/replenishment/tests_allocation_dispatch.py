from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.db import ProgrammingError
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from replenishment import views
from replenishment.services.allocation_dispatch import (
    LegacyWorkflowContext,
    _ensure_legacy_request_package,
    _request_header_update_values,
    _tracking_no,
    _apply_stock_delta_for_rows,
    _upsert_request_items,
    build_greedy_allocation_plan,
    build_waybill_payload,
    detect_override_requirement,
    get_current_allocation,
    OverrideApprovalError,
    sort_batch_candidates,
    sort_needs_list_items_for_allocation,
    validate_override_approval,
)


class AllocationDispatchHelperTests(SimpleTestCase):
    def test_tracking_number_preserves_prefix_for_large_ids(self) -> None:
        self.assertEqual(_tracking_no("PK", 100000), "PK100000")

    def test_tracking_number_keeps_zero_padding_for_small_ids(self) -> None:
        self.assertEqual(_tracking_no("RQ", 7), "RQ00007")

    def test_request_header_updates_mark_committed_allocations_as_approved_without_action_fields(self) -> None:
        values = _request_header_update_values(
            request=SimpleNamespace(
                status_code=0,
                review_by_id=None,
                review_dtime=None,
                action_by_id=None,
                action_dtime=None,
            ),
            package_status="P",
            needs_list=None,
            actor_user_id="planner",
            event_time=datetime(2026, 3, 24, 10, 0, 0),
        )

        self.assertEqual(values["status_code"], 2)
        self.assertEqual(values["review_by_id"], "planner")
        self.assertEqual(values["action_by_id"], None)
        self.assertEqual(values["action_dtime"], None)

    def test_request_header_updates_mark_dispatch_as_fulfilled_and_stamp_action_fields(self) -> None:
        values = _request_header_update_values(
            request=SimpleNamespace(
                status_code=2,
                review_by_id="reviewer",
                review_dtime=datetime(2026, 3, 24, 10, 0, 0),
                action_by_id=None,
                action_dtime=None,
            ),
            package_status="D",
            needs_list=None,
            actor_user_id="dispatcher",
            event_time=datetime(2026, 3, 25, 11, 0, 0),
        )

        self.assertEqual(values["status_code"], 5)
        self.assertEqual(values["review_by_id"], "reviewer")
        self.assertEqual(values["action_by_id"], "dispatcher")
        self.assertEqual(values["action_dtime"], datetime(2026, 3, 25, 11, 0, 0))

    def test_request_header_updates_keep_pending_override_request_in_approved_state(self) -> None:
        values = _request_header_update_values(
            request=SimpleNamespace(
                status_code=2,
                review_by_id="reviewer",
                review_dtime=datetime(2026, 3, 24, 10, 0, 0),
                action_by_id=None,
                action_dtime=None,
            ),
            package_status="A",
            needs_list=None,
            actor_user_id="planner",
            event_time=datetime(2026, 3, 25, 11, 0, 0),
        )

        self.assertEqual(values["status_code"], 2)
        self.assertEqual(values["review_by_id"], "reviewer")
        self.assertEqual(values["review_dtime"], datetime(2026, 3, 24, 10, 0, 0))
        self.assertEqual(values["action_by_id"], None)
        self.assertEqual(values["action_dtime"], None)

    @patch("replenishment.services.allocation_dispatch._load_package_plan_with_source_info", return_value=[])
    @patch("replenishment.services.allocation_dispatch._ensure_request_package_context")
    @patch("replenishment.services.allocation_dispatch._load_needs_list")
    def test_get_current_allocation_uses_nonlocking_request_package_lookup(
        self,
        mock_load_needs_list,
        mock_ensure_context,
        _mock_load_package_plan,
    ) -> None:
        mock_load_needs_list.return_value = SimpleNamespace(needs_list_id=11)
        mock_ensure_context.return_value = (
            SimpleNamespace(reliefrqst_id=70, tracking_no="RQ00070"),
            SimpleNamespace(
                reliefpkg_id=90,
                tracking_no="PK00090",
                status_code="P",
                dispatch_dtime=None,
            ),
        )

        result = get_current_allocation(
            {"needs_list_id": 11, "reliefrqst_id": 70, "reliefpkg_id": 90}
        )

        self.assertEqual(result["request_tracking_no"], "RQ00070")
        self.assertEqual(result["package_tracking_no"], "PK00090")
        self.assertEqual(mock_ensure_context.call_args.kwargs["for_update"], False)

    @patch("replenishment.views.NeedsListAllocationLine.objects.filter", side_effect=ProgrammingError("skip"))
    @patch(
        "replenishment.views.allocation_dispatch.get_current_allocation",
        side_effect=OverrideApprovalError("skip"),
    )
    @patch("replenishment.views._execution_link_for_record")
    def test_execution_payload_falls_back_to_execution_waybill_tracking_and_selected_method(
        self,
        mock_execution_link,
        _mock_current_allocation,
        _mock_allocation_line_filter,
    ) -> None:
        mock_execution_link.return_value = SimpleNamespace(
            needs_list_id=11,
            execution_status="DISPATCHED",
            reliefrqst_id=70,
            reliefpkg_id=90,
            selected_method="FIFO",
            waybill_no="WB-PK00090",
            waybill_payload_json={
                "request_tracking_no": "RQ00070",
                "package_tracking_no": "PK00090",
            },
        )

        payload = views._execution_payload_for_record({"needs_list_id": "11"})

        self.assertEqual(payload["selected_method"], "FIFO")
        self.assertEqual(payload["request_tracking_no"], "RQ00070")
        self.assertEqual(payload["package_tracking_no"], "PK00090")

    @patch("replenishment.services.allocation_dispatch._log_audit")
    @patch("replenishment.legacy_models.Inventory.objects")
    @patch("replenishment.legacy_models.ItemBatch.objects")
    @patch("replenishment.services.allocation_dispatch.NeedsListItem.objects")
    def test_apply_stock_delta_updates_same_needs_list_item_across_multiple_batches(
        self,
        mock_needs_list_item_objects,
        mock_itembatch_objects,
        mock_inventory_objects,
        _mock_log_audit,
    ) -> None:
        needs_item = SimpleNamespace(
            item_id=62,
            needs_list_item_id=64,
            reserved_qty=Decimal("0"),
            version_nbr=1,
        )
        mock_needs_list_item_objects.select_for_update.return_value.filter.return_value = [needs_item]

        expected_versions = [1, 2]

        def needs_item_filter_side_effect(**kwargs):
            version = kwargs["version_nbr"]
            expected = expected_versions.pop(0)
            update_result = 1 if version == expected else 0
            return SimpleNamespace(update=lambda **_update_kwargs: update_result)

        mock_needs_list_item_objects.filter.side_effect = needs_item_filter_side_effect

        batch_first = SimpleNamespace(
            batch_id=95025,
            inventory_id=2,
            item_id=62,
            reserved_qty=Decimal("0"),
            usable_qty=Decimal("3"),
            version_nbr=1,
            available_qty=Decimal("3"),
        )
        batch_second = SimpleNamespace(
            batch_id=109,
            inventory_id=2,
            item_id=62,
            reserved_qty=Decimal("0"),
            usable_qty=Decimal("91"),
            version_nbr=1,
            available_qty=Decimal("91"),
        )
        mock_itembatch_objects.select_for_update.return_value.get.side_effect = [batch_first, batch_second]
        mock_itembatch_objects.filter.return_value.update.return_value = 1

        inventory_first = SimpleNamespace(
            inventory_id=2,
            item_id=62,
            reserved_qty=Decimal("0"),
            usable_qty=Decimal("91"),
            version_nbr=1,
            available_qty=Decimal("91"),
        )
        inventory_second = SimpleNamespace(
            inventory_id=2,
            item_id=62,
            reserved_qty=Decimal("3"),
            usable_qty=Decimal("91"),
            version_nbr=2,
            available_qty=Decimal("88"),
        )
        mock_inventory_objects.select_for_update.return_value.get.side_effect = [
            inventory_first,
            inventory_second,
        ]
        mock_inventory_objects.filter.return_value.update.return_value = 1

        _apply_stock_delta_for_rows(
            [
                {"item_id": 62, "inventory_id": 2, "batch_id": 95025, "quantity": "3", "source_type": "ON_HAND"},
                {"item_id": 62, "inventory_id": 2, "batch_id": 109, "quantity": "2", "source_type": "ON_HAND"},
            ],
            actor_user_id="tester",
            delta_sign=1,
            update_needs_list=True,
            needs_list_id=11,
            consume_stock=False,
        )

        self.assertEqual(needs_item.reserved_qty, Decimal("5.0000"))
        self.assertEqual(
            [call.kwargs["version_nbr"] for call in mock_needs_list_item_objects.filter.call_args_list],
            [1, 2],
        )

    def test_sort_needs_list_items_orders_critical_before_high_before_normal(self) -> None:
        needs_list = SimpleNamespace(submitted_at=None, create_dtime=None)
        items = [
            SimpleNamespace(item_id=3, effective_criticality_level="NORMAL"),
            SimpleNamespace(item_id=1, effective_criticality_level="CRITICAL"),
            SimpleNamespace(item_id=2, effective_criticality_level="HIGH"),
        ]

        ordered = sort_needs_list_items_for_allocation(needs_list, items)

        self.assertEqual([item.item_id for item in ordered], [1, 2, 3])

    def test_sort_batch_candidates_fefo_excludes_expired_and_orders_by_expiry_then_batch_date(self) -> None:
        item = SimpleNamespace(can_expire_flag=True, issuance_order="FEFO")
        candidates = [
            {
                "batch_id": 1,
                "inventory_id": 10,
                "item_id": 99,
                "batch_date": date(2026, 1, 5),
                "expiry_date": date(2026, 1, 8),
                "available_qty": "4",
            },
            {
                "batch_id": 2,
                "inventory_id": 10,
                "item_id": 99,
                "batch_date": date(2026, 1, 1),
                "expiry_date": date(2026, 1, 6),
                "available_qty": "5",
            },
            {
                "batch_id": 3,
                "inventory_id": 10,
                "item_id": 99,
                "batch_date": date(2026, 1, 2),
                "expiry_date": date(2026, 1, 1),
                "available_qty": "2",
            },
        ]

        ordered = sort_batch_candidates(item, candidates, as_of_date=date(2026, 1, 3))

        self.assertEqual([row["batch_id"] for row in ordered], [2, 1])

    def test_sort_batch_candidates_fifo_uses_batch_date_for_non_expirable_items(self) -> None:
        item = SimpleNamespace(can_expire_flag=False, issuance_order="FEFO")
        candidates = [
            {
                "batch_id": 10,
                "inventory_id": 10,
                "item_id": 99,
                "batch_date": date(2026, 1, 5),
                "expiry_date": date(2026, 1, 8),
                "available_qty": "4",
            },
            {
                "batch_id": 11,
                "inventory_id": 10,
                "item_id": 99,
                "batch_date": date(2026, 1, 1),
                "expiry_date": date(2026, 1, 6),
                "available_qty": "5",
            },
        ]

        ordered = sort_batch_candidates(item, candidates)

        self.assertEqual([row["batch_id"] for row in ordered], [11, 10])

    def test_build_greedy_plan_consumes_batches_in_order(self) -> None:
        candidates = [
            {"item_id": 1, "inventory_id": 10, "batch_id": 100, "available_qty": "2", "uom_code": "EA"},
            {"item_id": 1, "inventory_id": 10, "batch_id": 101, "available_qty": "3", "uom_code": "EA"},
        ]

        plan, remaining = build_greedy_allocation_plan(candidates, "4")

        self.assertEqual(remaining, 0)
        self.assertEqual([(row["batch_id"], str(row["quantity"])) for row in plan], [(100, "2.0000"), (101, "2.0000")])

    def test_detect_override_requirement_flags_late_batch_selection(self) -> None:
        item = SimpleNamespace(can_expire_flag=False, issuance_order="FIFO")
        candidates = [
            {"item_id": 1, "inventory_id": 10, "batch_id": 100, "available_qty": "2", "uom_code": "EA"},
            {"item_id": 1, "inventory_id": 10, "batch_id": 101, "available_qty": "3", "uom_code": "EA"},
        ]
        selected = [
            {
                "item_id": 1,
                "inventory_id": 10,
                "batch_id": 101,
                "quantity": "2",
                "uom_code": "EA",
            }
        ]

        override_required, recommended, markers = detect_override_requirement(item, selected, candidates)

        self.assertTrue(override_required)
        self.assertEqual([row["batch_id"] for row in recommended], [100])
        self.assertIn("allocation_order_override", markers)

    def test_validate_override_approval_rejects_self_approval_and_bad_roles(self) -> None:
        with self.assertRaises(OverrideApprovalError):
            validate_override_approval(
                approver_user_id="alice",
                approver_role_codes=["LOGISTICS_MANAGER"],
                submitter_user_id="alice",
                needs_list_submitted_by="planner",
            )

        with self.assertRaises(OverrideApprovalError):
            validate_override_approval(
                approver_user_id="bob",
                approver_role_codes=["UNRELATED_ROLE"],
                submitter_user_id="alice",
                needs_list_submitted_by="planner",
            )

    @patch(
        "replenishment.services.allocation_dispatch.data_access.get_warehouse_names",
        return_value=({10: "Warehouse 10"}, []),
    )
    @patch("replenishment.services.allocation_dispatch.data_access.get_warehouse_name", return_value="Warehouse 2")
    @patch("replenishment.services.allocation_dispatch.data_access.get_event_name", return_value="Storm 7")
    def test_build_waybill_payload_includes_minimal_tracking_and_line_detail(
        self,
        _mock_event_name,
        _mock_warehouse_name,
        _mock_warehouse_names,
    ) -> None:
        needs_list = SimpleNamespace(needs_list_id=11, needs_list_no="NL-11", event_id=7)
        request = SimpleNamespace(tracking_no="RQ123", agency_id=5)
        package = SimpleNamespace(tracking_no="PK456", to_inventory_id=2, transport_mode="TRUCK")
        payload = build_waybill_payload(
            needs_list=needs_list,
            request=request,
            package=package,
            dispatched_rows=[
                {
                    "item_id": 1,
                    "inventory_id": 10,
                    "batch_id": 100,
                    "batch_no": "B100",
                    "quantity": "3",
                    "uom_code": "EA",
                    "source_type": "DONATION",
                    "source_record_id": 77,
                }
            ],
            actor_user_id="dispatcher",
            dispatch_dtime=None,
            transport_mode="TRUCK",
        )

        self.assertEqual(payload["waybill_no"], "WB-PK456")
        self.assertEqual(payload["request_tracking_no"], "RQ123")
        self.assertEqual(payload["package_tracking_no"], "PK456")
        self.assertEqual(payload["line_items"][0]["batch_id"], 100)
        self.assertEqual(payload["line_items"][0]["source_type"], "DONATION")

    @patch("replenishment.services.allocation_dispatch._upsert_request_items")
    @patch("replenishment.services.allocation_dispatch._next_int_id", side_effect=[501, 601])
    @patch("replenishment.legacy_models.ReliefPkg.objects.create")
    @patch("replenishment.legacy_models.ReliefRqst.objects.create")
    def test_first_legacy_request_creation_sets_approved_request_status(
        self,
        mock_request_create,
        mock_package_create,
        _mock_next_id,
        _mock_upsert_request_items,
    ) -> None:
        mock_request_create.return_value = SimpleNamespace(reliefrqst_id=501)
        mock_package_create.return_value = SimpleNamespace(reliefpkg_id=601)

        context = LegacyWorkflowContext(
            needs_list_id=11,
            agency_id=95001,
            destination_warehouse_id=1,
            event_id=1,
            urgency_ind="H",
            request_notes="notes",
            package_comments="comments",
        )
        needs_list = SimpleNamespace(event_id=1, warehouse_id=1)
        needs_list_items = [SimpleNamespace(item_id=1, required_qty="3", fulfilled_qty="0")]

        _ensure_legacy_request_package(
            context,
            needs_list=needs_list,
            needs_list_items=needs_list_items,
            actor_user_id="tester",
        )

        self.assertEqual(mock_request_create.call_args.kwargs["status_code"], 2)
        self.assertEqual(mock_request_create.call_args.kwargs["review_by_id"], "tester")
        self.assertIsNotNone(mock_request_create.call_args.kwargs["review_dtime"])
        self.assertNotIn("action_by_id", mock_request_create.call_args.kwargs)
        self.assertNotIn("action_dtime", mock_request_create.call_args.kwargs)
        self.assertEqual(mock_package_create.call_args.kwargs["status_code"], "A")

    @patch("replenishment.services.allocation_dispatch._execute", side_effect=[0, 1])
    def test_upsert_request_items_inserts_requested_status_without_action_fields_for_high_urgency(
        self,
        mock_execute,
    ) -> None:
        _upsert_request_items(
            reliefrqst_id=501,
            needs_list_items=[SimpleNamespace(item_id=1, required_qty="12", fulfilled_qty="0")],
            actor_user_id="tester",
            urgency_ind="H",
        )

        insert_params = mock_execute.call_args_list[1].args[1]
        self.assertEqual(insert_params[0], 501)
        self.assertEqual(insert_params[1], 1)
        self.assertEqual(insert_params[4], "H")
        self.assertEqual(insert_params[5], "AUTO-GENERATED HIGH URGENCY NEEDS LIST REQUEST")
        self.assertIsNotNone(insert_params[6])
        self.assertEqual(insert_params[7], "R")


@override_settings(
    AUTH_ENABLED=False,
    DEV_AUTH_ENABLED=True,
    TEST_DEV_AUTH_ENABLED=True,
    DEV_AUTH_USER_ID="dev-user",
    DEV_AUTH_ROLES=["LOGISTICS"],
    DEV_AUTH_PERMISSIONS=[],
    DEBUG=True,
    AUTH_USE_DB_RBAC=False,
)
class AllocationDispatchApiTests(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()

    @patch("replenishment.views._execution_needs_list_pk", return_value=11)
    @patch("replenishment.views._use_db_workflow_store", return_value=True)
    @patch("replenishment.views.workflow_store.get_record")
    @patch("replenishment.views.workflow_store.store_enabled_or_raise")
    def test_commit_requires_agency_and_urgency_for_first_formal_allocation(
        self,
        _mock_store_enabled,
        mock_get_record,
        _mock_use_db,
        _mock_needs_list_pk,
    ) -> None:
        mock_get_record.return_value = {
            "needs_list_id": "11",
            "needs_list_no": "NL-11",
            "status": "APPROVED",
            "warehouse_id": 1,
            "event_id": 7,
        }

        response = self.client.post(
            "/api/v1/replenishment/needs-list/11/allocations/commit",
            {
                "allocations": [
                    {
                        "item_id": 101,
                        "inventory_id": 1,
                        "batch_id": 1001,
                        "quantity": "3",
                    }
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("agency_id", response.json().get("errors", {}))
        self.assertIn("urgency_ind", response.json().get("errors", {}))

    @patch("replenishment.views._serialize_workflow_record", return_value={"needs_list_id": "11"})
    @patch("replenishment.views._upsert_execution_link")
    @patch("replenishment.views._replace_execution_allocation_lines")
    @patch("replenishment.views._stored_execution_allocation_lines")
    @patch("replenishment.views.resolve_roles_and_permissions", return_value=(["LOGISTICS_MANAGER"], []))
    @patch("replenishment.views.allocation_dispatch.approve_override")
    @patch("replenishment.views._execution_link_for_record")
    @patch("replenishment.views._execution_needs_list_pk", return_value=11)
    @patch("replenishment.views._use_db_workflow_store", return_value=True)
    @patch("replenishment.views.NeedsList.objects.select_for_update")
    @patch("replenishment.views.workflow_store.get_record")
    @patch("replenishment.views.workflow_store.store_enabled_or_raise")
    def test_override_approve_uses_override_submitter_for_no_self_approval(
        self,
        _mock_store_enabled,
        mock_get_record,
        mock_select_for_update,
        _mock_use_db,
        _mock_needs_list_pk,
        mock_execution_link,
        mock_approve_override,
        _mock_roles,
        mock_stored_lines,
        _mock_replace_lines,
        _mock_upsert_link,
        _mock_serialize,
    ) -> None:
        mock_get_record.return_value = {
            "needs_list_id": "11",
            "needs_list_no": "NL-11",
            "status": "IN_PREPARATION",
            "warehouse_id": 1,
            "event_id": 7,
            "submitted_by": "requester",
        }
        mock_execution_link.return_value = SimpleNamespace(
            needs_list_id=11,
            reliefrqst_id=70,
            reliefpkg_id=90,
            selected_method="FIFO",
            override_requested_by="planner-1",
            execution_status="PENDING_OVERRIDE_APPROVAL",
        )
        mock_stored_lines.return_value = [
            {
                "item_id": 101,
                "inventory_id": 1,
                "batch_id": 1001,
                "quantity": "3.0000",
                "source_type": "ON_HAND",
                "source_record_id": None,
                "uom_code": None,
                "needs_list_item_id": None,
                "allocation_rank": 1,
                "override_reason_code": "FEFO_BYPASS",
                "override_note": "Supervisor approved.",
            }
        ]
        mock_select_for_update.return_value.get.return_value = SimpleNamespace(needs_list_id=11)
        mock_approve_override.return_value = {
            "status": "COMMITTED",
            "reliefrqst_id": 70,
            "reliefpkg_id": 90,
            "override_required": True,
            "override_markers": ["allocation_order_override"],
        }

        response = self.client.post(
            "/api/v1/replenishment/needs-list/11/allocations/override-approve",
            {
                "override_reason_code": "FEFO_BYPASS",
                "override_note": "Supervisor approved.",
                "allocations": [
                    {
                        "item_id": 101,
                        "inventory_id": 1,
                        "batch_id": 1001,
                        "quantity": "3",
                        "source_type": "ON_HAND",
                    }
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_approve_override.call_args.kwargs["submitter_user_id"], "planner-1")
        self.assertEqual(mock_approve_override.call_args.kwargs["supervisor_user_id"], "dev-user")
        self.assertEqual(mock_approve_override.call_args.args[1][0]["quantity"], "3.0000")

    @patch("replenishment.views._execution_link_for_record")
    @patch("replenishment.views._execution_needs_list_pk", return_value=11)
    @patch("replenishment.views._use_db_workflow_store", return_value=True)
    @patch("replenishment.views.workflow_store.get_record")
    @patch("replenishment.views.workflow_store.store_enabled_or_raise")
    def test_override_approve_requires_pending_override_execution_status(
        self,
        _mock_store_enabled,
        mock_get_record,
        _mock_use_db,
        _mock_needs_list_pk,
        mock_execution_link,
    ) -> None:
        mock_get_record.return_value = {
            "needs_list_id": "11",
            "needs_list_no": "NL-11",
            "status": "IN_PREPARATION",
            "warehouse_id": 1,
            "event_id": 7,
            "submitted_by": "requester",
        }
        mock_execution_link.return_value = SimpleNamespace(
            needs_list_id=11,
            reliefrqst_id=70,
            reliefpkg_id=90,
            selected_method="FIFO",
            override_requested_by="planner-1",
            execution_status="PREPARING",
        )

        response = self.client.post(
            "/api/v1/replenishment/needs-list/11/allocations/override-approve",
            {"override_reason_code": "FEFO_BYPASS", "override_note": "Supervisor approved."},
            format="json",
        )

        self.assertEqual(response.status_code, 409)
        self.assertIn("status", response.json().get("errors", {}))

    @patch("replenishment.views._serialize_workflow_record", return_value={"needs_list_id": "11", "waybill_no": "WB-PK00090"})
    @patch("replenishment.views._use_db_workflow_store", return_value=True)
    @patch("replenishment.views._upsert_execution_link")
    @patch("replenishment.views.allocation_dispatch.dispatch_package")
    @patch("replenishment.views._execution_link_for_record")
    @patch("replenishment.views.workflow_store.update_record")
    @patch("replenishment.views.workflow_store.transition_status")
    @patch("replenishment.views.workflow_store.get_record")
    @patch("replenishment.views.workflow_store.store_enabled_or_raise")
    def test_mark_dispatched_uses_allocation_dispatch_service_when_execution_link_exists(
        self,
        _mock_store_enabled,
        mock_get_record,
        mock_transition_status,
        _mock_update_record,
        mock_execution_link,
        mock_dispatch_package,
        _mock_upsert_link,
        _mock_use_db,
        _mock_serialize,
    ) -> None:
        record = {
            "needs_list_id": "11",
            "needs_list_no": "NL-11",
            "status": "IN_PREPARATION",
            "warehouse_id": 1,
            "event_id": 7,
            "prep_started_at": "2026-03-24T10:00:00Z",
        }
        mock_get_record.return_value = record
        mock_transition_status.return_value = {**record, "status": "IN_PROGRESS", "dispatched_at": "2026-03-24T11:00:00Z"}
        mock_execution_link.return_value = SimpleNamespace(
            needs_list_id=11,
            reliefrqst_id=70,
            reliefpkg_id=90,
            selected_method="FIFO",
        )
        mock_dispatch_package.return_value = {
            "status": "DISPATCHED",
            "reliefrqst_id": 70,
            "reliefpkg_id": 90,
            "waybill_no": "WB-PK00090",
            "waybill_payload": {"waybill_no": "WB-PK00090"},
        }

        response = self.client.post(
            "/api/v1/replenishment/needs-list/11/mark-dispatched",
            {"transport_mode": "TRUCK"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(mock_dispatch_package.called)
        self.assertEqual(response.json().get("waybill_no"), "WB-PK00090")
