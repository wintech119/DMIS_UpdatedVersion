from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from django.db import DatabaseError
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from api.rbac import (
    PERM_OPERATIONS_PACKAGE_OVERRIDE_APPROVE,
    PERM_OPERATIONS_PACKAGE_OVERRIDE_REQUEST,
    PERM_OPERATIONS_REQUEST_CREATE_FOR_SUBORDINATE,
    PERM_OPERATIONS_REQUEST_CREATE_ON_BEHALF_BRIDGE,
    PERM_OPERATIONS_REQUEST_CREATE_SELF,
)
from api.tenancy import TenantContext, TenantMembership
from operations.constants import ORIGIN_MODE_FOR_SUBORDINATE, ORIGIN_MODE_ODPEM_BRIDGE, ORIGIN_MODE_SELF
from operations import policy as operations_policy
from operations import services as operations_service
from operations.exceptions import OperationValidationError
from replenishment.models import NeedsList


def _tenant_context(
    *,
    tenant_id: int,
    tenant_code: str,
    tenant_type: str,
    access_level: str = "ADMIN",
    can_read_all_tenants: bool = False,
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
        can_read_all_tenants=can_read_all_tenants,
        can_act_cross_tenant=can_act_cross_tenant,
    )


class _DeterministicOdpemTenantResolutionMixin:
    """Keep policy-only tests deterministic without live tenant table access."""

    odpem_tenant_id = 27

    def setUp(self) -> None:
        super().setUp()
        self._resolve_odpem_tenant_id_patcher = patch(
            "operations.policy.resolve_odpem_tenant_id",
            return_value=self.odpem_tenant_id,
        )
        self._resolve_odpem_tenant_id_patcher.start()
        self.addCleanup(self._resolve_odpem_tenant_id_patcher.stop)


class ReliefRequestCapabilityTests(_DeterministicOdpemTenantResolutionMixin, SimpleTestCase):
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


class ReliefRequestAuthorityPreviewTests(_DeterministicOdpemTenantResolutionMixin, TestCase):
    def _create_needs_list(self, needs_list_id: int = 40) -> NeedsList:
        return NeedsList.objects.create(
            needs_list_id=needs_list_id,
            needs_list_no=f"NL{needs_list_id:05d}",
            event_id=12,
            warehouse_id=11,
            event_phase="SURGE",
            calculation_dtime=timezone.now(),
            demand_window_hours=6,
            planning_window_hours=72,
            safety_factor=Decimal("1.25"),
            status_code="APPROVED",
            total_gap_qty=Decimal("1.00"),
            create_by_id="tester",
            update_by_id="tester",
        )

    @staticmethod
    def _decision(
        *,
        origin_mode: str = ORIGIN_MODE_SELF,
        requesting_tenant_id: int = 20,
        beneficiary_tenant_id: int = 20,
        agency_id: int = 501,
    ) -> operations_policy.ReliefRequestWriteDecision:
        return operations_policy.ReliefRequestWriteDecision(
            agency_scope=operations_policy.AgencyScope(
                agency_id=agency_id,
                agency_name=f"Agency {agency_id}",
                agency_type="SHELTER",
                warehouse_id=11,
                tenant_id=beneficiary_tenant_id,
                tenant_code="ODPEM" if beneficiary_tenant_id == 27 else f"TENANT-{beneficiary_tenant_id}",
                tenant_name=f"Tenant {beneficiary_tenant_id}",
                tenant_type="NATIONAL" if beneficiary_tenant_id == 27 else "EXTERNAL",
            ),
            origin_mode=origin_mode,
            requesting_tenant_id=requesting_tenant_id,
            beneficiary_tenant_id=beneficiary_tenant_id,
            requesting_agency_id=agency_id if origin_mode == ORIGIN_MODE_SELF else None,
            beneficiary_agency_id=agency_id,
        )

    @staticmethod
    def _policy_error(code: str) -> OperationValidationError:
        return OperationValidationError({"agency_id": {"code": code, "message": "Authority preview blocked."}})

    def test_authority_preview_allows_requester_owned_needs_list(self) -> None:
        needs_list = self._create_needs_list()
        decision = self._decision()

        with (
            patch("operations.services._needs_list_owner_tenant_id", return_value=20),
            patch("operations.services._agency_id_for_needs_list_owner", return_value=501),
            patch("operations.services._active_request_authority_tenant_id", return_value=None),
            patch(
                "operations.services.operations_policy.validate_relief_request_agency_selection",
                return_value=decision,
            ),
        ):
            payload = operations_service.get_request_authority_preview(
                source_needs_list_id=needs_list.needs_list_id,
                tenant_context=_tenant_context(tenant_id=20, tenant_code="FFP", tenant_type="EXTERNAL"),
                permissions=[PERM_OPERATIONS_REQUEST_CREATE_SELF],
            )

        self.assertEqual(
            payload,
            {
                "can_create": True,
                "allowed_origin_modes": [ORIGIN_MODE_SELF],
                "required_authority_tenant_id": None,
                "beneficiary_tenant_id": 20,
                "beneficiary_agency_id": 501,
                "suggested_event_id": 12,
                "blocked_reason_code": None,
            },
        )

    def test_authority_preview_blocks_odpem_hq_replenishment_needs_list(self) -> None:
        needs_list = self._create_needs_list(41)

        with (
            patch("operations.services._needs_list_owner_tenant_id", return_value=27),
            patch("operations.services._agency_id_for_needs_list_owner", return_value=901),
            patch("operations.services._active_request_authority_tenant_id", return_value=None),
            patch("operations.services.operations_policy.validate_relief_request_agency_selection") as mock_validate,
        ):
            payload = operations_service.get_request_authority_preview(
                source_needs_list_id=needs_list.needs_list_id,
                tenant_context=_tenant_context(tenant_id=27, tenant_code="ODPEM", tenant_type="NATIONAL"),
                permissions=[PERM_OPERATIONS_REQUEST_CREATE_ON_BEHALF_BRIDGE],
            )

        self.assertFalse(payload["can_create"])
        self.assertEqual(payload["blocked_reason_code"], "odpem_replenishment_only_needs_list")
        self.assertEqual(payload["beneficiary_tenant_id"], 27)
        mock_validate.assert_not_called()

    def test_authority_preview_reports_escalation_required(self) -> None:
        needs_list = self._create_needs_list(42)

        with (
            patch("operations.services._needs_list_owner_tenant_id", return_value=20),
            patch("operations.services._agency_id_for_needs_list_owner", return_value=501),
            patch("operations.services._active_request_authority_tenant_id", return_value=400),
            patch(
                "operations.services.operations_policy.validate_relief_request_agency_selection",
                side_effect=self._policy_error("request_authority_escalation_required"),
            ),
        ):
            payload = operations_service.get_request_authority_preview(
                source_needs_list_id=needs_list.needs_list_id,
                tenant_context=_tenant_context(tenant_id=20, tenant_code="FFP", tenant_type="EXTERNAL"),
                permissions=[PERM_OPERATIONS_REQUEST_CREATE_SELF],
            )

        self.assertFalse(payload["can_create"])
        self.assertEqual(payload["blocked_reason_code"], "escalation_required")
        self.assertEqual(payload["required_authority_tenant_id"], 400)

    def test_authority_preview_reports_agency_out_of_scope(self) -> None:
        needs_list = self._create_needs_list(43)

        with (
            patch("operations.services._needs_list_owner_tenant_id", return_value=20),
            patch("operations.services._agency_id_for_needs_list_owner", return_value=501),
            patch("operations.services._active_request_authority_tenant_id", return_value=None),
            patch(
                "operations.services.operations_policy.validate_relief_request_agency_selection",
                side_effect=self._policy_error("agency_out_of_scope"),
            ),
        ):
            payload = operations_service.get_request_authority_preview(
                source_needs_list_id=needs_list.needs_list_id,
                tenant_context=_tenant_context(tenant_id=21, tenant_code="OTHER", tenant_type="EXTERNAL"),
                permissions=[PERM_OPERATIONS_REQUEST_CREATE_SELF],
            )

        self.assertFalse(payload["can_create"])
        self.assertEqual(payload["blocked_reason_code"], "agency_out_of_scope")

    def test_authority_preview_maps_cross_tenant_source_mismatch_to_scope_block(self) -> None:
        needs_list = self._create_needs_list(44)
        mismatched_decision = self._decision(beneficiary_tenant_id=21)

        with (
            patch("operations.services._needs_list_owner_tenant_id", return_value=20),
            patch("operations.services._agency_id_for_needs_list_owner", return_value=501),
            patch("operations.services._active_request_authority_tenant_id", return_value=None),
            patch(
                "operations.services.operations_policy.validate_relief_request_agency_selection",
                return_value=mismatched_decision,
            ),
        ):
            payload = operations_service.get_request_authority_preview(
                source_needs_list_id=needs_list.needs_list_id,
                tenant_context=_tenant_context(tenant_id=21, tenant_code="OTHER", tenant_type="EXTERNAL"),
                permissions=[PERM_OPERATIONS_REQUEST_CREATE_SELF],
            )

        self.assertFalse(payload["can_create"])
        self.assertEqual(payload["blocked_reason_code"], "agency_out_of_scope")

    def test_authority_preview_reports_self_request_disabled(self) -> None:
        needs_list = self._create_needs_list(45)

        with (
            patch("operations.services._needs_list_owner_tenant_id", return_value=20),
            patch("operations.services._agency_id_for_needs_list_owner", return_value=501),
            patch("operations.services._active_request_authority_tenant_id", return_value=None),
            patch(
                "operations.services.operations_policy.validate_relief_request_agency_selection",
                side_effect=self._policy_error("self_request_disabled"),
            ),
        ):
            payload = operations_service.get_request_authority_preview(
                source_needs_list_id=needs_list.needs_list_id,
                tenant_context=_tenant_context(tenant_id=20, tenant_code="FFP", tenant_type="EXTERNAL"),
                permissions=[PERM_OPERATIONS_REQUEST_CREATE_SELF],
            )

        self.assertFalse(payload["can_create"])
        self.assertEqual(payload["blocked_reason_code"], "self_request_disabled")

    def test_authority_preview_missing_needs_list_raises_stable_error(self) -> None:
        with self.assertRaises(OperationValidationError) as raised:
            operations_service.get_request_authority_preview(
                source_needs_list_id=404,
                tenant_context=_tenant_context(tenant_id=20, tenant_code="FFP", tenant_type="EXTERNAL"),
                permissions=[PERM_OPERATIONS_REQUEST_CREATE_SELF],
            )

        self.assertEqual(raised.exception.errors["source_needs_list_id"]["code"], "source_needs_list_not_found")


class ResolveOdpemTenantIdTests(TestCase):
    def tearDown(self) -> None:
        super().tearDown()
        operations_policy.resolve_odpem_tenant_id.cache_clear()

    @override_settings(ODPEM_TENANT_ID="not-an-int")
    def test_invalid_configured_tenant_id_returns_none(self) -> None:
        self.assertIsNone(operations_policy.resolve_odpem_tenant_id())

    @patch("operations.policy.connection")
    def test_query_only_searches_for_odpem_like_tenants(self, connection_mock) -> None:
        cursor = MagicMock()
        cursor.__enter__.return_value = cursor
        cursor.fetchone.return_value = None
        connection_mock.cursor.return_value = cursor

        resolved = operations_policy.resolve_odpem_tenant_id()

        self.assertIsNone(resolved)
        sql = cursor.execute.call_args.args[0]
        self.assertIn("OFFICE_OF_DISASTER_P", sql)
        self.assertIn("LIKE 'ODPEM%%'", sql)
        self.assertNotIn("ELSE 2", sql)


class EventLookupTests(SimpleTestCase):
    @patch("operations.services._qualified_table", return_value="legacy_schema.event")
    @patch("operations.services.connection")
    def test_event_exists_queries_qualified_event_table(self, connection_mock, qualified_table_mock) -> None:
        cursor = MagicMock()
        cursor.__enter__.return_value = cursor
        cursor.fetchone.return_value = (1,)
        connection_mock.cursor.return_value = cursor

        exists = operations_service._event_exists(77)

        self.assertTrue(exists)
        qualified_table_mock.assert_called_once_with("event")
        cursor.execute.assert_called_once_with(
            "SELECT 1 FROM legacy_schema.event WHERE event_id = %s LIMIT 1",
            [77],
        )

    @patch("operations.services.connection")
    def test_event_exists_returns_false_for_invalid_event_id(self, connection_mock) -> None:
        exists = operations_service._event_exists("not-an-int")

        self.assertFalse(exists)
        connection_mock.cursor.assert_not_called()

    @patch("operations.services._qualified_table", return_value="legacy_schema.event")
    @patch("operations.services.connection")
    def test_event_exists_propagates_database_errors(self, connection_mock, _qualified_table_mock) -> None:
        cursor = MagicMock()
        cursor.__enter__.return_value = cursor
        cursor.execute.side_effect = DatabaseError("event lookup failed")
        connection_mock.cursor.return_value = cursor

        with self.assertRaises(DatabaseError):
            operations_service._event_exists(77)


class ReliefRequestAgencyPolicyTests(_DeterministicOdpemTenantResolutionMixin, SimpleTestCase):
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


class TrackingNumberHelperTests(SimpleTestCase):
    def test_tracking_number_preserves_prefix_for_large_ids(self) -> None:
        self.assertEqual(operations_service._tracking_no("RQ", 100000), "RQ100000")

    def test_tracking_number_keeps_zero_padding_for_small_ids(self) -> None:
        self.assertEqual(operations_service._tracking_no("PK", 7), "PK00007")

    @patch("operations.services._request_summary", return_value={"reliefrqst_id": 88, "tracking_no": "RQ00088"})
    @patch("operations.services._load_request", return_value=SimpleNamespace(reliefrqst_id=88, tracking_no="RQ00088"))
    def test_reshape_compat_options_normalizes_quantities_to_four_decimals(
        self,
        _load_request_mock,
        _request_summary_mock,
    ) -> None:
        payload = operations_service._reshape_compat_options(
            {
                "items": [
                    {"item_id": 101, "required_qty": "2", "fulfilled_qty": None},
                    {"item_id": 102, "required_qty": "bad", "fulfilled_qty": ""},
                ]
            },
            88,
        )

        self.assertEqual(payload["items"][0]["request_qty"], "2.0000")
        self.assertEqual(payload["items"][0]["issue_qty"], "0.0000")
        self.assertEqual(payload["items"][1]["request_qty"], "0.0000")
        self.assertEqual(payload["items"][1]["issue_qty"], "0.0000")


@override_settings(AUTH_ENABLED=False, DEV_AUTH_ENABLED=True, TEST_DEV_AUTH_ENABLED=True)
class ReliefRequestServiceTests(TestCase):
    def setUp(self) -> None:
        super().setUp()
        fully_dispatched_patcher = patch(
            "operations.services._request_fully_dispatched",
            return_value=False,
        )
        fully_dispatched_patcher.start()
        self.addCleanup(fully_dispatched_patcher.stop)

    @patch("operations.services.data_access.get_item_names", return_value=({101: {"name": "Water Tabs", "code": "WT-001"}}, []))
    @patch(
        "operations.services._fetch_rows",
        return_value=[
            {
                "item_id": 101,
                "request_qty": "2",
                "issue_qty": "0",
                "urgency_ind": "H",
                "rqst_reason_desc": "Potable water",
                "required_by_date": "2026-03-30",
                "status_code": "R",
            }
        ],
    )
    def test_request_items_uses_item_name_lookup_name_and_code_keys(self, _fetch_rows_mock, _get_item_names_mock) -> None:
        items = operations_service._request_items(95007)

        self.assertEqual(items[0]["item_code"], "WT-001")
        self.assertEqual(items[0]["item_name"], "Water Tabs")

    @patch("operations.services._load_request", return_value=SimpleNamespace(reliefrqst_id=77))
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
        _load_request_mock,
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
    def test_request_item_required_by_date_must_be_iso_date(
        self,
        validate_scope_mock,
        create_request_mock,
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

        with self.assertRaises(OperationValidationError) as raised:
            operations_service.create_request(
                payload={
                    "agency_id": 501,
                    "urgency_ind": "M",
                    "items": [{"item_id": 101, "request_qty": "3", "required_by_date": "2026-02-30"}],
                },
                actor_id="user-1",
                tenant_context=tenant_context,
                permissions=[PERM_OPERATIONS_REQUEST_CREATE_SELF],
            )

        self.assertEqual(raised.exception.errors["items[0].required_by_date"], "Invalid date")
        create_request_mock.assert_not_called()

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
    @patch("operations.services.operations_policy.get_agency_scope")
    @patch("operations.services.operations_policy.validate_relief_request_agency_selection")
    def test_submit_request_revalidates_existing_agency_scope(
        self,
        validate_scope_mock,
        get_agency_scope_mock,
        load_request_mock,
        _request_items_mock,
        _get_request_mock,
    ) -> None:
        agency_scope = operations_policy.AgencyScope(
            agency_id=501,
            agency_name="Food For The Poor Shelter",
            agency_type="SHELTER",
            warehouse_id=11,
            tenant_id=20,
            tenant_code="FFP",
            tenant_name="Food For The Poor",
            tenant_type="EXTERNAL",
        )
        get_agency_scope_mock.return_value = agency_scope
        validate_scope_mock.return_value = operations_policy.ReliefRequestWriteDecision(
            agency_scope=agency_scope,
            origin_mode=operations_policy.ORIGIN_MODE_SELF,
            requesting_tenant_id=20,
            beneficiary_tenant_id=20,
            requesting_agency_id=501,
            beneficiary_agency_id=501,
        )
        request_record = SimpleNamespace(reliefrqst_id=88, agency_id=501, status_code=operations_service.STATUS_DRAFT, version_nbr=1)
        request_record.save = lambda **kwargs: None
        load_request_mock.return_value = request_record
        tenant_context = _tenant_context(tenant_id=20, tenant_code="FFP", tenant_type="EXTERNAL")

        operations_service.submit_request(
            88,
            actor_id="user-1",
            tenant_context=tenant_context,
            idempotency_key="submit-88",
        )

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
    def test_approved_override_with_order_only_bypass_commits_without_approval(
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
        load_request_mock.return_value = SimpleNamespace(
            create_by_id="planner-1",
            tracking_no="RQ00088",
            status_code=operations_service.STATUS_SUBMITTED,
        )
        ensure_package_mock.return_value = SimpleNamespace(reliefpkg_id=90, tracking_no="PK00090")
        item_filter_mock.return_value = [SimpleNamespace(item_id=101)]

        with patch("operations.services.data_access.get_warehouses_with_stock", return_value=({101: []}, [])):
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
        self.assertFalse(result["override_required"])
        self.assertEqual(result["override_markers"], ["allocation_order_override"])
        validate_override_mock.assert_called_once()
        upsert_rows_mock.assert_called_once()
        self.assertEqual(upsert_rows_mock.call_args.kwargs["notes"], "FEFO_BYPASS")
        stock_delta_mock.assert_called_once()
        self.assertEqual(header_updates_mock.call_args.kwargs["status_code"], operations_service.PKG_STATUS_PENDING)

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
    def test_save_package_requires_note_for_order_override_submission(
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
        load_request_mock.return_value = SimpleNamespace(
            create_by_id="planner-1",
            tracking_no="RQ00088",
            status_code=operations_service.STATUS_SUBMITTED,
        )
        ensure_package_mock.return_value = SimpleNamespace(reliefpkg_id=90, tracking_no="PK00090")
        item_filter_mock.return_value = [SimpleNamespace(item_id=101)]

        with patch("operations.services.data_access.get_warehouses_with_stock", return_value=({101: []}, [])):
            with self.assertRaises(operations_service.OverrideApprovalError) as raised:
                operations_service._save_package_allocation(
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
                    },
                    actor_id="manager-1",
                    actor_roles=["LOGISTICS_OFFICER"],
                    actor_permissions=[PERM_OPERATIONS_PACKAGE_OVERRIDE_REQUEST],
                    allow_pending_override=True,
                )

        self.assertEqual(raised.exception.code, "override_details_missing")
        validate_override_mock.assert_not_called()
        upsert_rows_mock.assert_not_called()
        stock_delta_mock.assert_not_called()
        header_updates_mock.assert_not_called()

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
    def test_save_package_requires_reason_code_for_order_override(
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
    ) -> None:
        load_request_mock.return_value = SimpleNamespace(
            create_by_id="planner-1",
            tracking_no="RQ00088",
            status_code=operations_service.STATUS_SUBMITTED,
        )
        ensure_package_mock.return_value = SimpleNamespace(reliefpkg_id=90, tracking_no="PK00090")
        item_filter_mock.return_value = [SimpleNamespace(item_id=101)]

        with patch("operations.services.data_access.get_warehouses_with_stock", return_value=({101: []}, [])):
            with self.assertRaises(operations_service.OverrideApprovalError) as raised:
                operations_service._save_package_allocation(
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
                    },
                    actor_id="manager-1",
                    allow_pending_override=True,
                )

        self.assertEqual(raised.exception.code, "override_details_missing")
        upsert_rows_mock.assert_not_called()
        stock_delta_mock.assert_not_called()
        header_updates_mock.assert_not_called()

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

        with (
            patch("operations.services._load_request", return_value=request_record),
            patch(
                "operations.services.operations_policy.get_agency_scope",
                return_value=validate_scope_mock.return_value.agency_scope,
            ),
        ):
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

        with (
            patch(
                "operations.services._load_request",
                return_value=SimpleNamespace(reliefrqst_id=70, agency_id=501, eligible_event_id=12, status_code=operations_service.STATUS_SUBMITTED),
            ),
            patch("operations.services._current_package_for_request", return_value=package),
        ):
            result = operations_service._ensure_package(
                70,
                actor_id="planner-1",
                payload={"to_inventory_id": "9"},
            )

        self.assertIs(result, package)
        self.assertEqual(package.to_inventory_id, 9)
        self.assertIn("to_inventory_id", list(saved.get("update_fields", [])))

    @patch("operations.services.timezone.now", return_value=datetime(2026, 3, 27, 9, 0, 0))
    @patch("operations.services._load_request")
    @patch("operations.services.ReliefPkg.objects.create")
    @patch("operations.services._next_int_id", return_value=90)
    @patch("operations.services._current_package_for_request", return_value=None)
    def test_new_package_without_destination_persists_null_instead_of_zero(
        self,
        _current_package_mock,
        _next_id_mock,
        create_package_mock,
        load_request_mock,
        _now_mock,
    ) -> None:
        load_request_mock.return_value = SimpleNamespace(
            agency_id=501,
            eligible_event_id=12,
            reliefrqst_id=70,
        )

        operations_service._ensure_package(
            70,
            actor_id="planner-1",
            payload={"comments_text": "Prep"},
        )

        self.assertIsNone(create_package_mock.call_args.kwargs["to_inventory_id"])

    @patch("operations.services.ReliefPkg.objects.create")
    @patch("operations.services._next_int_id", return_value=91)
    @patch("operations.services.timezone.now", return_value=datetime(2026, 3, 27, 9, 0, 0))
    @patch("operations.services._current_package_for_request")
    @patch("operations.services._load_request")
    def test_ensure_package_rechecks_after_request_lock_before_creating(
        self,
        load_request_mock,
        current_package_mock,
        _now_mock,
        _next_id_mock,
        create_package_mock,
    ) -> None:
        existing_package = SimpleNamespace(
            reliefpkg_id=90,
            to_inventory_id=8,
            transport_mode=None,
            comments_text=None,
            version_nbr=1,
            save=Mock(),
        )
        load_request_mock.return_value = SimpleNamespace(
            reliefrqst_id=70,
            agency_id=501,
            eligible_event_id=12,
            status_code=operations_service.STATUS_SUBMITTED,
        )
        current_package_mock.side_effect = [existing_package]

        result = operations_service._ensure_package(
            70,
            actor_id="planner-1",
            payload={"comments_text": "Prep"},
        )

        self.assertIs(result, existing_package)
        create_package_mock.assert_not_called()

    @patch("operations.services.ReliefPkg.objects.create")
    @patch("operations.services._next_int_id", return_value=91)
    @patch("operations.services.timezone.now", return_value=datetime(2026, 3, 27, 9, 0, 0))
    @patch("operations.services._current_package_status", return_value=operations_service.PKG_STATUS_DISPATCHED)
    @patch("operations.services._current_package_for_request")
    @patch("operations.services._load_request")
    def test_ensure_package_creates_follow_up_package_for_part_filled_request(
        self,
        load_request_mock,
        current_package_mock,
        _current_status_mock,
        _now_mock,
        _next_id_mock,
        create_package_mock,
    ) -> None:
        load_request_mock.return_value = SimpleNamespace(
            reliefrqst_id=70,
            agency_id=501,
            eligible_event_id=12,
            status_code=operations_service.STATUS_PART_FILLED,
        )
        current_package_mock.return_value = SimpleNamespace(
            reliefpkg_id=90,
            status_code=operations_service.PKG_STATUS_DISPATCHED,
            dispatch_dtime=datetime(2026, 3, 27, 8, 0, 0),
            to_inventory_id=8,
            transport_mode=None,
            comments_text=None,
            version_nbr=1,
            save=Mock(),
        )
        create_package_mock.return_value = SimpleNamespace(reliefpkg_id=91, tracking_no="PK00091")

        result = operations_service._ensure_package(
            70,
            actor_id="planner-1",
            payload={"to_inventory_id": "9", "comments_text": "Follow-up"},
        )

        self.assertEqual(result.reliefpkg_id, 91)
        self.assertEqual(create_package_mock.call_args.kwargs["reliefrqst_id"], 70)
        self.assertEqual(create_package_mock.call_args.kwargs["to_inventory_id"], 9)

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


class DispatchDetailTests(SimpleTestCase):
    @patch("operations.services.get_waybill")
    @patch("operations.services._request_summary", return_value={"reliefrqst_id": 70})
    @patch("operations.services._load_request", return_value=SimpleNamespace(reliefrqst_id=70))
    @patch("operations.services._package_detail", return_value={"reliefpkg_id": 90})
    def test_pending_dispatch_detail_skips_waybill_lookup(
        self,
        _package_detail_mock,
        _load_request_mock,
        _request_summary_mock,
        get_waybill_mock,
    ) -> None:
        result = operations_service._dispatch_detail(
            SimpleNamespace(
                reliefpkg_id=90,
                reliefrqst_id=70,
                dispatch_dtime=None,
            )
        )

        self.assertIsNone(result["waybill"])
        get_waybill_mock.assert_not_called()

    @patch("operations.services.get_waybill", return_value={"waybill_no": "WB-PK00090"})
    @patch("operations.services._request_summary", return_value={"reliefrqst_id": 70})
    @patch("operations.services._load_request", return_value=SimpleNamespace(reliefrqst_id=70))
    @patch("operations.services._package_detail", return_value={"reliefpkg_id": 90})
    def test_dispatched_dispatch_detail_includes_waybill(
        self,
        _package_detail_mock,
        _load_request_mock,
        _request_summary_mock,
        get_waybill_mock,
    ) -> None:
        result = operations_service._dispatch_detail(
            SimpleNamespace(
                reliefpkg_id=90,
                reliefrqst_id=70,
                dispatch_dtime=datetime(2026, 3, 27, 13, 0, 0),
            )
        )

        self.assertEqual(result["waybill"]["waybill_no"], "WB-PK00090")
        get_waybill_mock.assert_called_once_with(90)


class DispatchSubmissionStatusTests(TestCase):
    def _exercise_submit_dispatch(self, *, request_completion_status: int) -> Mock:
        request = SimpleNamespace(
            reliefrqst_id=70,
            version_nbr=4,
            review_by_id=None,
            review_dtime=None,
            tracking_no="RQ00070",
        )
        initial_package = SimpleNamespace(
            reliefpkg_id=90,
            reliefrqst_id=70,
            version_nbr=2,
            transport_mode=None,
        )
        refreshed_package = SimpleNamespace(
            reliefpkg_id=90,
            reliefrqst_id=70,
            tracking_no="PK00090",
            transport_mode="TRUCK",
            dispatch_dtime=datetime(2026, 3, 27, 14, 0, 0),
        )
        request_filter = Mock()
        request_filter.update.return_value = 1
        package_filter = Mock()
        package_filter.update.return_value = 1
        package_rows = [
            {
                "item_id": 101,
                "inventory_id": 4,
                "batch_id": 1001,
                "quantity": Decimal("2"),
                "uom_code": "EA",
                "source_type": "ON_HAND",
                "source_record_id": None,
            }
        ]

        with patch("operations.services.timezone.now", return_value=datetime(2026, 3, 27, 14, 0, 0)), patch(
            "operations.services._load_package",
            side_effect=[initial_package, refreshed_package],
        ), patch(
            "operations.services._load_request",
            return_value=request,
        ), patch(
            "operations.services._current_package_status",
            return_value=operations_service.PKG_STATUS_PENDING,
        ), patch(
            "operations.services._selected_plan_for_package",
            return_value=package_rows,
        ), patch(
            "operations.services._apply_stock_delta_for_rows",
        ), patch(
            "operations.services.ReliefRqst.objects.filter",
            return_value=request_filter,
        ), patch(
            "operations.services.ReliefPkg.objects.filter",
            return_value=package_filter,
        ), patch(
            "operations.services._advance_transfer_rows",
        ), patch(
            "operations.services._execute",
            return_value=1,
        ), patch(
            "operations.services._request_completion_status",
            return_value=request_completion_status,
        ), patch(
            "operations.services._operations_waybill_payload",
            return_value={"waybill_no": "WB-PK00090"},
        ):
            operations_service.submit_dispatch(
                90,
                payload={"transport_mode": "TRUCK"},
                actor_id="dispatch-1",
                idempotency_key=f"dispatch-status-{request_completion_status}",
            )

        return request_filter

    def test_submit_dispatch_marks_request_filled_when_all_lines_are_complete(self) -> None:
        request_filter = self._exercise_submit_dispatch(
            request_completion_status=operations_service.STATUS_FILLED,
        )

        self.assertEqual(
            request_filter.update.call_args.kwargs["status_code"],
            operations_service.STATUS_FILLED,
        )

    def test_submit_dispatch_marks_request_part_filled_when_any_line_remains_open(self) -> None:
        request_filter = self._exercise_submit_dispatch(
            request_completion_status=operations_service.STATUS_PART_FILLED,
        )

        self.assertEqual(
            request_filter.update.call_args.kwargs["status_code"],
            operations_service.STATUS_PART_FILLED,
        )


@override_settings(AUTH_ENABLED=False, DEV_AUTH_ENABLED=True, TEST_DEV_AUTH_ENABLED=True)
class PackageAllocationGuardTests(TestCase):
    @patch("operations.services._save_package_allocation")
    @patch(
        "operations.services._current_package_for_request",
        return_value=SimpleNamespace(create_by_id="allocator-1", update_by_id="editor-9"),
    )
    @patch("operations.services._load_request", return_value=SimpleNamespace(create_by_id="requester-1"))
    @patch("operations.services._execution_link_for_request", return_value=None)
    def test_approve_override_uses_request_creator_as_stable_submitter(
        self,
        _execution_link_mock,
        load_request_mock,
        current_package_mock,
        save_package_allocation_mock,
    ) -> None:
        save_package_allocation_mock.return_value = {"status": "COMMITTED"}

        result = operations_service.approve_override(
            88,
            payload={"allocations": [{"item_id": 101, "inventory_id": 1, "batch_id": 1001, "quantity": "2"}]},
            actor_id="manager-1",
            actor_roles=["LOGISTICS_MANAGER"],
            idempotency_key="override-approve-stable-submitter-88",
        )

        self.assertEqual(result, {"status": "COMMITTED"})
        load_request_mock.assert_called_once_with(88)
        current_package_mock.assert_called_once_with(88)
        self.assertEqual(
            save_package_allocation_mock.call_args.kwargs["override_submitter_user_id"],
            "requester-1",
        )

    @patch("operations.services._ensure_package")
    @patch("operations.services._load_request", return_value=SimpleNamespace(status_code=operations_service.STATUS_DRAFT))
    @patch("operations.services._execution_link_for_request", return_value=None)
    def test_save_package_rejects_non_fulfillment_request_before_package_detail(
        self,
        _execution_link_mock,
        _load_request_mock,
        ensure_package_mock,
    ) -> None:
        with self.assertRaises(OperationValidationError) as raised:
            operations_service._save_package_allocation(
                88,
                payload={},
                actor_id="manager-1",
                allow_pending_override=True,
            )

        self.assertEqual(
            raised.exception.errors["request"],
            "Packages can only be managed for requests that are submitted for fulfillment or already part filled.",
        )
        ensure_package_mock.assert_not_called()

    @patch("operations.services.compat_commit_allocation")
    @patch("operations.services._load_request", return_value=SimpleNamespace(status_code=operations_service.STATUS_DRAFT))
    @patch(
        "operations.services._execution_link_for_request",
        return_value=SimpleNamespace(
            needs_list_id=7,
            reliefrqst_id=88,
            reliefpkg_id=None,
            override_requested_by=None,
            needs_list=SimpleNamespace(warehouse_id=11, event_id=12, submitted_by="planner-1"),
        ),
    )
    def test_save_package_rejects_non_fulfillment_request_before_compat_commit(
        self,
        _execution_link_mock,
        _load_request_mock,
        compat_commit_mock,
    ) -> None:
        with self.assertRaises(OperationValidationError) as raised:
            operations_service._save_package_allocation(
                88,
                payload={
                    "allocations": [
                        {
                            "item_id": 101,
                            "inventory_id": 1,
                            "batch_id": 1001,
                            "quantity": "2",
                        }
                    ]
                },
                actor_id="manager-1",
                allow_pending_override=True,
            )

        self.assertEqual(
            raised.exception.errors["request"],
            "Packages can only be managed for requests that are submitted for fulfillment or already part filled.",
        )
        compat_commit_mock.assert_not_called()

    @patch("operations.services._apply_package_header_updates")
    @patch("operations.services._apply_stock_delta_for_rows")
    @patch("operations.services._upsert_package_rows")
    @patch(
        "operations.services.build_greedy_allocation_plan",
        return_value=([{
            "item_id": 101,
            "inventory_id": 1,
            "batch_id": 1001,
            "quantity": "2",
        }], Decimal("0")),
    )
    @patch("operations.services.sort_batch_candidates", return_value=[])
    @patch("operations.services._fetch_batch_candidates", return_value=[])
    @patch("operations.services._selected_plan_for_package", return_value=[])
    @patch("operations.services.Item.objects.filter", return_value=[SimpleNamespace(item_id=101)])
    @patch("operations.services._request_item_rows_for_allocation", return_value=[{"item_id": 101}])
    @patch("operations.services._resolve_candidate_warehouse_ids", return_value=[1])
    @patch("operations.services._current_package_status", return_value=operations_service.PKG_STATUS_DISPATCHED)
    @patch("operations.services._ensure_package")
    @patch("operations.services._load_request")
    def test_save_package_rejects_dispatched_package_before_replacing_rows(
        self,
        _load_request_mock,
        _ensure_package_mock,
        _current_status_mock,
        _warehouse_ids_mock,
        _request_rows_mock,
        _item_filter_mock,
        selected_plan_mock,
        _fetch_candidates_mock,
        _sort_candidates_mock,
        _allocation_plan_mock,
        upsert_rows_mock,
        stock_delta_mock,
        header_updates_mock,
    ) -> None:
        _load_request_mock.return_value = SimpleNamespace(
            create_by_id="planner-1",
            tracking_no="RQ00088",
            status_code=operations_service.STATUS_SUBMITTED,
        )
        _ensure_package_mock.return_value = SimpleNamespace(reliefpkg_id=90, tracking_no="PK00090")

        with self.assertRaises(operations_service.DispatchError):
            operations_service._save_package_allocation(
                88,
                payload={
                    "allocations": [
                        {
                            "item_id": 101,
                            "inventory_id": 1,
                            "batch_id": 1001,
                            "quantity": "2",
                        }
                    ]
                },
                actor_id="manager-1",
                allow_pending_override=True,
            )

        selected_plan_mock.assert_not_called()
        _fetch_candidates_mock.assert_not_called()
        _sort_candidates_mock.assert_not_called()
        _allocation_plan_mock.assert_not_called()
        upsert_rows_mock.assert_not_called()
        stock_delta_mock.assert_not_called()
        header_updates_mock.assert_not_called()

    @patch("operations.services._apply_package_header_updates")
    @patch("operations.services._apply_stock_delta_for_rows")
    @patch("operations.services._upsert_package_rows")
    @patch(
        "operations.services.build_greedy_allocation_plan",
        return_value=([{
            "item_id": 101,
            "inventory_id": 1,
            "batch_id": 1001,
            "quantity": "2",
        }], Decimal("0")),
    )
    @patch("operations.services.sort_batch_candidates", return_value=[])
    @patch("operations.services._fetch_batch_candidates", return_value=[])
    @patch("operations.services._selected_plan_for_package", return_value=[])
    @patch("operations.services.Item.objects.filter", return_value=[SimpleNamespace(item_id=101)])
    @patch("operations.services._request_item_rows_for_allocation", return_value=[{"item_id": 101}])
    @patch("operations.services._resolve_candidate_warehouse_ids", return_value=[1])
    @patch("operations.services._current_package_status", return_value=operations_service.PKG_STATUS_COMPLETED)
    @patch("operations.services._ensure_package")
    @patch("operations.services._load_request")
    def test_save_package_allows_legacy_completed_package_before_dispatch(
        self,
        _load_request_mock,
        _ensure_package_mock,
        _current_status_mock,
        _warehouse_ids_mock,
        _request_rows_mock,
        _item_filter_mock,
        selected_plan_mock,
        _fetch_candidates_mock,
        _sort_candidates_mock,
        _allocation_plan_mock,
        upsert_rows_mock,
        stock_delta_mock,
        header_updates_mock,
    ) -> None:
        _load_request_mock.return_value = SimpleNamespace(
            create_by_id="planner-1",
            tracking_no="RQ00088",
            status_code=operations_service.STATUS_SUBMITTED,
        )
        _ensure_package_mock.return_value = SimpleNamespace(reliefpkg_id=90, tracking_no="PK00090")

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
                ]
            },
            actor_id="manager-1",
            allow_pending_override=True,
        )

        self.assertEqual(result["status"], "COMMITTED")
        selected_plan_mock.assert_called_once_with(90)
        upsert_rows_mock.assert_called_once()
        header_updates_mock.assert_called_once()
        stock_delta_mock.assert_called_once_with(
            [{
                "item_id": 101,
                "inventory_id": 1,
                "batch_id": 1001,
                "source_type": "ON_HAND",
                "source_record_id": None,
                "uom_code": None,
                "quantity": Decimal("2.0000"),
            }],
            actor_user_id="manager-1",
            delta_sign=1,
            update_needs_list=False,
        )

    @patch("operations.services._apply_package_header_updates")
    @patch("operations.services._apply_stock_delta_for_rows")
    @patch("operations.services._upsert_package_rows")
    @patch("operations.services.build_greedy_allocation_plan", return_value=([], Decimal("0")))
    @patch("operations.services.sort_batch_candidates", return_value=[])
    @patch("operations.services._fetch_batch_candidates", return_value=[])
    @patch("operations.services._selected_plan_for_package", return_value=[])
    @patch("operations.services.Item.objects.filter", return_value=[SimpleNamespace(item_id=101)])
    @patch("operations.services._request_item_rows_for_allocation", return_value=[{"item_id": 101}])
    @patch("operations.services._resolve_candidate_warehouse_ids", return_value=[1])
    @patch("operations.services._current_package_status", return_value=operations_service.PKG_STATUS_PENDING)
    @patch("operations.services._ensure_package")
    @patch("operations.services._load_request")
    def test_save_package_marks_unrequested_items_as_override_and_skips_candidate_lookup(
        self,
        _load_request_mock,
        _ensure_package_mock,
        _current_status_mock,
        _warehouse_ids_mock,
        _request_rows_mock,
        _item_filter_mock,
        _selected_plan_mock,
        fetch_candidates_mock,
        sort_candidates_mock,
        allocation_plan_mock,
        upsert_rows_mock,
        stock_delta_mock,
        header_updates_mock,
    ) -> None:
        _load_request_mock.return_value = SimpleNamespace(
            create_by_id="planner-1",
            tracking_no="RQ00088",
            status_code=operations_service.STATUS_SUBMITTED,
        )
        _ensure_package_mock.return_value = SimpleNamespace(reliefpkg_id=90, tracking_no="PK00090")

        result = operations_service._save_package_allocation(
            88,
            payload={
                "allocations": [
                    {
                        "item_id": 202,
                        "inventory_id": 1,
                        "batch_id": 1001,
                        "quantity": "2",
                    }
                ],
                "override_reason_code": "FEFO_BYPASS",
                "override_note": "Supervisor approved.",
            },
            actor_id="officer-1",
            actor_roles=["LOGISTICS_OFFICER"],
            actor_permissions=[PERM_OPERATIONS_PACKAGE_OVERRIDE_REQUEST],
            allow_pending_override=True,
        )

        self.assertEqual(result["status"], "PENDING_OVERRIDE_APPROVAL")
        self.assertEqual(result["override_markers"], ["item_not_in_request"])
        fetch_candidates_mock.assert_not_called()
        sort_candidates_mock.assert_not_called()
        allocation_plan_mock.assert_not_called()
        upsert_rows_mock.assert_called_once()
        stock_delta_mock.assert_not_called()
        header_updates_mock.assert_called_once()
        self.assertEqual(
            header_updates_mock.call_args.kwargs["status_code"],
            operations_service.PKG_STATUS_DRAFT,
        )

    @patch("operations.services._apply_package_header_updates")
    @patch("operations.services._apply_stock_delta_for_rows")
    @patch("operations.services._upsert_package_rows")
    @patch("operations.services.build_greedy_allocation_plan", return_value=([], Decimal("0")))
    @patch("operations.services.sort_batch_candidates", return_value=[])
    @patch("operations.services._fetch_batch_candidates", return_value=[])
    @patch("operations.services._selected_plan_for_package", return_value=[])
    @patch("operations.services.Item.objects.filter", return_value=[SimpleNamespace(item_id=101)])
    @patch("operations.services._request_item_rows_for_allocation", return_value=[{"item_id": 101}])
    @patch("operations.services._resolve_candidate_warehouse_ids", return_value=[1])
    @patch("operations.services._current_package_status", return_value=operations_service.PKG_STATUS_PENDING)
    @patch("operations.services._ensure_package")
    @patch("operations.services._load_request")
    def test_save_package_accepts_alias_logistics_officer_for_pending_override_submission(
        self,
        _load_request_mock,
        _ensure_package_mock,
        _current_status_mock,
        _warehouse_ids_mock,
        _request_rows_mock,
        _item_filter_mock,
        _selected_plan_mock,
        fetch_candidates_mock,
        sort_candidates_mock,
        allocation_plan_mock,
        upsert_rows_mock,
        stock_delta_mock,
        header_updates_mock,
    ) -> None:
        _load_request_mock.return_value = SimpleNamespace(
            create_by_id="planner-1",
            tracking_no="RQ00088",
            status_code=operations_service.STATUS_SUBMITTED,
        )
        _ensure_package_mock.return_value = SimpleNamespace(reliefpkg_id=90, tracking_no="PK00090")

        result = operations_service._save_package_allocation(
            88,
            payload={
                "allocations": [
                    {
                        "item_id": 202,
                        "inventory_id": 1,
                        "batch_id": 1001,
                        "quantity": "2",
                    }
                ],
                "override_reason_code": "FEFO_BYPASS",
                "override_note": "Supervisor approved.",
            },
            actor_id="officer-1",
            actor_roles=["TST_LOGISTICS_OFFICER"],
            actor_permissions=[PERM_OPERATIONS_PACKAGE_OVERRIDE_REQUEST],
            allow_pending_override=True,
        )

        self.assertEqual(result["status"], "PENDING_OVERRIDE_APPROVAL")
        self.assertEqual(result["override_markers"], ["item_not_in_request"])
        fetch_candidates_mock.assert_not_called()
        sort_candidates_mock.assert_not_called()
        allocation_plan_mock.assert_not_called()
        upsert_rows_mock.assert_called_once()
        stock_delta_mock.assert_not_called()
        header_updates_mock.assert_called_once()
        self.assertEqual(
            header_updates_mock.call_args.kwargs["status_code"],
            operations_service.PKG_STATUS_DRAFT,
        )

    @patch("operations.services._apply_package_header_updates")
    @patch("operations.services._apply_stock_delta_for_rows")
    @patch("operations.services._upsert_package_rows")
    @patch("operations.services.build_greedy_allocation_plan", return_value=([], Decimal("0")))
    @patch("operations.services.sort_batch_candidates", return_value=[])
    @patch("operations.services._fetch_batch_candidates", return_value=[])
    @patch("operations.services._selected_plan_for_package", return_value=[])
    @patch("operations.services.Item.objects.filter", return_value=[SimpleNamespace(item_id=101)])
    @patch("operations.services._request_item_rows_for_allocation", return_value=[{"item_id": 101}])
    @patch("operations.services._resolve_candidate_warehouse_ids", return_value=[1])
    @patch("operations.services._current_package_status", return_value=operations_service.PKG_STATUS_PENDING)
    @patch("operations.services._ensure_package")
    @patch("operations.services._load_request")
    def test_save_package_rejects_pending_override_submission_without_override_request_permission(
        self,
        _load_request_mock,
        _ensure_package_mock,
        _current_status_mock,
        _warehouse_ids_mock,
        _request_rows_mock,
        _item_filter_mock,
        _selected_plan_mock,
        fetch_candidates_mock,
        sort_candidates_mock,
        allocation_plan_mock,
        upsert_rows_mock,
        stock_delta_mock,
        header_updates_mock,
    ) -> None:
        _load_request_mock.return_value = SimpleNamespace(
            create_by_id="planner-1",
            tracking_no="RQ00088",
            status_code=operations_service.STATUS_SUBMITTED,
        )
        _ensure_package_mock.return_value = SimpleNamespace(reliefpkg_id=90, tracking_no="PK00090")

        with self.assertRaises(OperationValidationError) as raised:
            operations_service._save_package_allocation(
                88,
                payload={
                    "allocations": [
                        {
                            "item_id": 202,
                            "inventory_id": 1,
                            "batch_id": 1001,
                            "quantity": "2",
                        }
                    ],
                    "override_reason_code": "FEFO_BYPASS",
                    "override_note": "Supervisor approved.",
                },
                actor_id="officer-1",
                actor_roles=["LOGISTICS_OFFICER"],
                actor_permissions=[],
                allow_pending_override=True,
            )

        self.assertEqual(
            raised.exception.errors["override"],
            (
                "Override request permission is required to submit override requests. "
                "Override approval permission can commit overrides directly."
            ),
        )
        fetch_candidates_mock.assert_not_called()
        sort_candidates_mock.assert_not_called()
        allocation_plan_mock.assert_not_called()
        upsert_rows_mock.assert_not_called()
        stock_delta_mock.assert_not_called()
        header_updates_mock.assert_not_called()

    @patch("operations.services._apply_package_header_updates")
    @patch("operations.services._apply_stock_delta_for_rows")
    @patch("operations.services._upsert_package_rows")
    @patch("operations.services.Item.objects.filter", return_value=[])
    @patch("operations.services._request_item_rows_for_allocation", return_value=[{"item_id": 101}])
    @patch("operations.services._resolve_candidate_warehouse_ids", return_value=[1])
    @patch("operations.services._current_package_status", return_value="A")
    @patch("operations.services._ensure_package")
    @patch("operations.services._load_request")
    @patch("operations.services._execution_link_for_request", return_value=None)
    def test_save_package_allows_manager_to_commit_approval_required_override_directly(
        self,
        _execution_link_mock,
        load_request_mock,
        ensure_package_mock,
        _current_status_mock,
        _warehouse_ids_mock,
        _request_rows_mock,
        _item_filter_mock,
        upsert_rows_mock,
        stock_delta_mock,
        header_updates_mock,
    ) -> None:
        load_request_mock.return_value = SimpleNamespace(
            create_by_id="planner-1",
            tracking_no="RQ00088",
            status_code=operations_service.STATUS_SUBMITTED,
        )
        ensure_package_mock.return_value = SimpleNamespace(reliefpkg_id=90, tracking_no="PK00090")

        result = operations_service._save_package_allocation(
            88,
            payload={
                "allocations": [
                    {
                        "item_id": 202,
                        "inventory_id": 1,
                        "batch_id": 1001,
                        "quantity": "2",
                    }
                ],
                "override_reason_code": "FEFO_BYPASS",
                "override_note": "Manager-authorized fulfillment override.",
            },
            actor_id="manager-1",
            actor_roles=["LOGISTICS_MANAGER"],
            actor_permissions=[PERM_OPERATIONS_PACKAGE_OVERRIDE_APPROVE],
            allow_pending_override=True,
        )

        self.assertEqual(result["status"], "COMMITTED")
        self.assertFalse(result["override_required"])
        self.assertEqual(result["override_markers"], ["item_not_in_request"])
        upsert_rows_mock.assert_called_once()
        stock_delta_mock.assert_called_once()
        self.assertEqual(header_updates_mock.call_args.kwargs["status_code"], operations_service.PKG_STATUS_PENDING)
