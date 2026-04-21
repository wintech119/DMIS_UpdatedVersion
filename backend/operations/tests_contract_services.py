from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from django.db import DatabaseError, IntegrityError, connection
from django.core.cache import cache
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from api.tenancy import TenantContext, TenantMembership
from operations import contract_services
from operations import policy as operations_policy
from operations import services as operations_service
from operations.constants import (
    CONSOLIDATION_LEG_STATUS_CANCELLED,
    CONSOLIDATION_LEG_STATUS_IN_TRANSIT,
    CONSOLIDATION_LEG_STATUS_PLANNED,
    CONSOLIDATION_STATUS_ALL_RECEIVED,
    CONSOLIDATION_STATUS_AWAITING_LEGS,
    CONSOLIDATION_STATUS_PARTIAL_RELEASE_REQUESTED,
    DISPATCH_STATUS_IN_TRANSIT,
    FULFILLMENT_MODE_PICKUP_AT_STAGING,
    ELIGIBILITY_ROLE_CODES,
    FULFILLMENT_MODE_DELIVER_FROM_STAGING,
    ORIGIN_MODE_FOR_SUBORDINATE,
    ORIGIN_MODE_SELF,
    PACKAGE_STATUS_CANCELLED,
    PACKAGE_STATUS_COMMITTED,
    PACKAGE_STATUS_CONSOLIDATING,
    PACKAGE_STATUS_DISPATCHED,
    PACKAGE_STATUS_DRAFT,
    PACKAGE_STATUS_PENDING_OVERRIDE_APPROVAL,
    PACKAGE_STATUS_REJECTED,
    PACKAGE_STATUS_READY_FOR_DISPATCH,
    PACKAGE_STATUS_READY_FOR_PICKUP,
    PACKAGE_STATUS_RECEIVED,
    PACKAGE_STATUS_SPLIT,
    QUEUE_CODE_CONSOLIDATION_DISPATCH,
    QUEUE_CODE_DISPATCH,
    QUEUE_CODE_ELIGIBILITY,
    QUEUE_CODE_FULFILLMENT,
    QUEUE_CODE_OVERRIDE,
    QUEUE_CODE_PICKUP_RELEASE,
    QUEUE_CODE_RECEIPT,
    QUEUE_CODE_STAGING_RECEIPT,
    ROLE_INVENTORY_CLERK,
    ROLE_LOGISTICS_MANAGER,
    ROLE_LOGISTICS_OFFICER,
    ROLE_SYSTEM_ADMINISTRATOR,
    REQUEST_STATUS_APPROVED_FOR_FULFILLMENT,
    REQUEST_STATUS_FULFILLED,
    REQUEST_STATUS_INELIGIBLE,
    REQUEST_STATUS_PARTIALLY_FULFILLED,
    REQUEST_STATUS_REJECTED,
    REQUEST_STATUS_UNDER_ELIGIBILITY_REVIEW,
)
from operations.exceptions import OperationValidationError
from operations.models import (
    OperationsAllocationLine,
    OperationsActionAudit,
    OperationsConsolidationLeg,
    OperationsConsolidationLegItem,
    OperationsDispatch,
    OperationsDispatchTransport,
    OperationsEligibilityDecision,
    OperationsNotification,
    OperationsPackage,
    OperationsPackageLock,
    OperationsPickupRelease,
    OperationsQueueAssignment,
    OperationsReceipt,
    OperationsReliefRequest,
    OperationsStatusHistory,
    OperationsWaybill,
    TenantControlScope,
    TenantRequestPolicy,
)
from api.rbac import (
    PERM_OPERATIONS_FULFILLMENT_MODE_SET,
    PERM_OPERATIONS_PACKAGE_OVERRIDE_REQUEST,
    PERM_OPERATIONS_REQUEST_CREATE_SELF,
    PERM_OPERATIONS_STAGING_WAREHOUSE_OVERRIDE,
)
from replenishment.legacy_models import Inventory, ItemBatch, ReliefRqst


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


def _policy_kwargs(actor: str) -> dict[str, object]:
    return {
        "create_by_id": actor,
        "update_by_id": actor,
        "effective_date": date(2026, 1, 1),
    }


class RequestAuthorityHierarchyTests(TestCase):
    @patch("operations.policy.get_agency_scope")
    def test_child_tenant_cannot_self_request_when_parent_is_request_authority(self, get_agency_scope_mock) -> None:
        TenantRequestPolicy.objects.create(
            tenant_id=300,
            can_self_request_flag=True,
            request_authority_tenant_id=400,
            **_policy_kwargs("tester"),
        )
        get_agency_scope_mock.return_value = operations_policy.AgencyScope(
            agency_id=501,
            agency_name="Community Agency",
            agency_type="COMMUNITY",
            warehouse_id=11,
            tenant_id=300,
            tenant_code="COMM-300",
            tenant_name="Community 300",
            tenant_type="COMMUNITY",
        )

        with self.assertRaises(OperationValidationError) as raised:
            operations_policy.validate_relief_request_agency_selection(
                agency_id=501,
                tenant_context=_tenant_context(tenant_id=300, tenant_code="COMM-300", tenant_type="COMMUNITY"),
            )

        self.assertEqual(raised.exception.errors["agency_id"]["code"], "request_authority_escalation_required")

    @patch("operations.policy.get_agency_scope")
    def test_parent_tenant_can_request_for_controlled_subordinate(self, get_agency_scope_mock) -> None:
        TenantRequestPolicy.objects.create(
            tenant_id=300,
            can_self_request_flag=False,
            request_authority_tenant_id=400,
            **_policy_kwargs("tester"),
        )
        TenantControlScope.objects.create(
            controller_tenant_id=400,
            controlled_tenant_id=300,
            control_type="REQUEST_AUTHORITY",
            **_policy_kwargs("tester"),
        )
        get_agency_scope_mock.return_value = operations_policy.AgencyScope(
            agency_id=777,
            agency_name="Shelter Agency",
            agency_type="SHELTER",
            warehouse_id=22,
            tenant_id=300,
            tenant_code="COMM-300",
            tenant_name="Community 300",
            tenant_type="COMMUNITY",
        )

        decision = operations_policy.validate_relief_request_agency_selection(
            agency_id=777,
            tenant_context=_tenant_context(tenant_id=400, tenant_code="PARISH-400", tenant_type="PARISH"),
        )

        self.assertEqual(decision.origin_mode, ORIGIN_MODE_FOR_SUBORDINATE)
        self.assertEqual(decision.beneficiary_tenant_id, 300)


@override_settings(AUTH_ENABLED=False, DEV_AUTH_ENABLED=True, TEST_DEV_AUTH_ENABLED=True)
class OperationsWorkflowContractTests(TestCase):
    def setUp(self) -> None:
        cache.clear()
        self.request = SimpleNamespace(
            reliefrqst_id=70,
            agency_id=501,
            tracking_no="RQ00070",
            eligible_event_id=12,
            request_date=date(2026, 3, 26),
            urgency_ind="H",
            rqst_notes_text="Need shelter kits",
            create_by_id="requester-1",
            create_dtime=datetime(2026, 3, 26, 9, 0, 0),
            review_by_id=None,
            review_dtime=None,
            status_code=1,
        )
        self.fulfillment_request = self._request_stub(
            reliefrqst_id=70,
            agency_id=501,
            status_code=contract_services.legacy_service.STATUS_SUBMITTED,
        )
        self.package = SimpleNamespace(
            reliefpkg_id=90,
            tracking_no="PK00090",
            reliefrqst_id=70,
            dispatch_dtime=None,
            to_inventory_id=8,
            status_code="P",
            received_dtime=None,
            received_by_id=None,
            update_by_id="locker-1",
            update_dtime=datetime(2026, 3, 26, 10, 0, 0),
            version_nbr=1,
            save=lambda **kwargs: None,
        )
        self.dispatch_ready_context = _tenant_context(tenant_id=20, tenant_code="FFP", tenant_type="EXTERNAL")
        self.odpem_context = _tenant_context(
            tenant_id=27,
            tenant_code="OFFICE-OF-DISASTER-P",
            tenant_type="NATIONAL",
        )
        self.dispatch_roles = ["LOGISTICS_MANAGER"]
        self.agency_scope = operations_policy.AgencyScope(
            agency_id=501,
            agency_name="FFP Shelter",
            agency_type="SHELTER",
            warehouse_id=11,
            tenant_id=20,
            tenant_code="FFP",
            tenant_name="Food For The Poor",
            tenant_type="EXTERNAL",
        )
        fully_dispatched_patcher = patch(
            "operations.contract_services._request_fully_dispatched",
            return_value=False,
        )
        fully_dispatched_patcher.start()
        self.addCleanup(fully_dispatched_patcher.stop)

    def tearDown(self) -> None:
        cache.clear()

    def _request_stub(self, *, reliefrqst_id: int, agency_id: int, status_code: int = 3) -> SimpleNamespace:
        return SimpleNamespace(
            reliefrqst_id=reliefrqst_id,
            agency_id=agency_id,
            tracking_no=f"RQ{reliefrqst_id:05d}",
            eligible_event_id=12,
            request_date=date(2026, 3, 26),
            urgency_ind="H",
            rqst_notes_text="Need shelter kits",
            create_by_id="requester-1",
            create_dtime=datetime(2026, 3, 26, 9, 0, 0),
            review_by_id=None,
            review_dtime=None,
            status_code=status_code,
        )

    def _package_stub(
        self,
        *,
        reliefpkg_id: int,
        reliefrqst_id: int,
        agency_id: int,
        status_code: str = "P",
        dispatch_dtime: datetime | None = None,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            reliefpkg_id=reliefpkg_id,
            tracking_no=f"PK{reliefpkg_id:05d}",
            reliefrqst_id=reliefrqst_id,
            agency_id=agency_id,
            eligible_event_id=12,
            dispatch_dtime=dispatch_dtime,
            to_inventory_id=8,
            transport_mode=None,
            comments_text=None,
            status_code=status_code,
            received_dtime=None,
            received_by_id=None,
            update_by_id="locker-1",
            update_dtime=datetime(2026, 3, 26, 10, 0, 0),
            version_nbr=1,
            save=lambda **kwargs: None,
        )

    def _agency_scope_for(self, agency_id: int, tenant_id: int, tenant_code: str) -> operations_policy.AgencyScope:
        return operations_policy.AgencyScope(
            agency_id=agency_id,
            agency_name=f"Agency {agency_id}",
            agency_type="SHELTER",
            warehouse_id=11,
            tenant_id=tenant_id,
            tenant_code=tenant_code,
            tenant_name=f"Tenant {tenant_id}",
            tenant_type="EXTERNAL",
        )

    @patch("operations.contract_services.get_lookup")
    @patch("operations.contract_services.operations_policy.validate_relief_request_agency_selection")
    def test_request_reference_data_filters_agencies_to_allowed_scope(
        self,
        validate_agency_mock,
        get_lookup_mock,
    ) -> None:
        get_lookup_mock.side_effect = [
            (
                [
                    {"value": 501, "label": "FFP Shelter"},
                    {"value": 777, "label": "Other Agency"},
                ],
                [],
            ),
            ([{"value": 12, "label": "Spring Flood 2026"}], []),
            ([{"value": 101, "label": "Water purification tablet"}], []),
        ]

        def validate_side_effect(*, agency_id: int, tenant_context: TenantContext):
            if agency_id == 501:
                return operations_policy.ReliefRequestWriteDecision(
                    agency_scope=self.agency_scope,
                    origin_mode=ORIGIN_MODE_SELF,
                    requesting_tenant_id=20,
                    beneficiary_tenant_id=20,
                    requesting_agency_id=501,
                    beneficiary_agency_id=501,
                )
            raise OperationValidationError({"agency_id": {"code": "agency_out_of_scope"}})

        validate_agency_mock.side_effect = validate_side_effect

        payload = contract_services.get_request_reference_data(
            tenant_context=self.dispatch_ready_context,
            permissions=[PERM_OPERATIONS_REQUEST_CREATE_SELF],
        )

        self.assertEqual(payload["agencies"], [{"value": 501, "label": "FFP Shelter"}])
        self.assertEqual(payload["events"], [{"value": 12, "label": "Spring Flood 2026"}])
        self.assertEqual(payload["items"], [{"value": 101, "label": "Water purification tablet"}])

    def _insert_legacy_agency(self, agency_id: int) -> None:
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO agency (
                        agency_id,
                        agency_name,
                        address1_text,
                        parish_code,
                        contact_name,
                        phone_no,
                        create_by_id,
                        create_dtime,
                        update_by_id,
                        update_dtime,
                        version_nbr,
                        agency_type,
                        status_code
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (agency_id) DO NOTHING
                    """,
                    [
                        agency_id,
                        f"AGENCY {agency_id}",
                        f"{agency_id} Test Street",
                        "01",
                        "TEST CONTACT",
                        "555-0100",
                        "tester",
                        datetime(2026, 3, 26, 9, 0, 0),
                        "tester",
                        datetime(2026, 3, 26, 9, 0, 0),
                        1,
                        "SHELTER",
                        "A",
                    ],
                )
        except DatabaseError:
            return

    def _create_operations_request_record(self, relief_request_id: int = 70, agency_id: int = 501) -> OperationsReliefRequest:
        return OperationsReliefRequest.objects.create(
            relief_request_id=relief_request_id,
            request_no=f"RQ{relief_request_id:05d}",
            requesting_tenant_id=20,
            requesting_agency_id=agency_id,
            beneficiary_tenant_id=20,
            beneficiary_agency_id=agency_id,
            origin_mode="SELF",
            event_id=12,
            request_date=date(2026, 3, 26),
            urgency_code="H",
            status_code=REQUEST_STATUS_APPROVED_FOR_FULFILLMENT,
            create_by_id="tester",
            update_by_id="tester",
        )

    @patch("operations.contract_services.operations_policy.get_agency_scope")
    def test_request_sync_skips_version_bump_when_record_matches_legacy(self, get_agency_scope_mock) -> None:
        get_agency_scope_mock.return_value = self.agency_scope
        original_updated_at = timezone.make_aware(datetime(2026, 3, 26, 8, 30, 0))
        OperationsReliefRequest.objects.create(
            relief_request_id=70,
            request_no="RQ00070",
            requesting_tenant_id=20,
            requesting_agency_id=501,
            beneficiary_tenant_id=20,
            beneficiary_agency_id=501,
            origin_mode="SELF",
            event_id=12,
            request_date=date(2026, 3, 26),
            urgency_code="H",
            notes_text="Need shelter kits",
            status_code=REQUEST_STATUS_UNDER_ELIGIBILITY_REVIEW,
            create_by_id="seed-user",
            update_by_id="seed-user",
            update_dtime=original_updated_at,
            version_nbr=7,
        )

        record = contract_services._sync_operations_request(self.request, actor_id="sync-1")
        record.refresh_from_db()

        self.assertEqual(record.version_nbr, 7)
        self.assertEqual(record.update_by_id, "seed-user")
        self.assertEqual(record.update_dtime, original_updated_at)

    @patch("operations.contract_services.operations_policy.get_agency_scope")
    def test_request_sync_preserves_fulfilled_status_when_legacy_maps_back_to_approved(
        self,
        get_agency_scope_mock,
    ) -> None:
        get_agency_scope_mock.return_value = self.agency_scope
        original_updated_at = timezone.make_aware(datetime(2026, 3, 26, 8, 30, 0))
        legacy_request = self._request_stub(
            reliefrqst_id=70,
            agency_id=501,
            status_code=contract_services.legacy_service.STATUS_CANCELLED,
        )
        OperationsReliefRequest.objects.create(
            relief_request_id=70,
            request_no="RQ00070",
            requesting_tenant_id=20,
            requesting_agency_id=501,
            beneficiary_tenant_id=20,
            beneficiary_agency_id=501,
            origin_mode="SELF",
            event_id=12,
            request_date=date(2026, 3, 26),
            urgency_code="H",
            notes_text="Need shelter kits",
            status_code=REQUEST_STATUS_FULFILLED,
            create_by_id="seed-user",
            update_by_id="seed-user",
            update_dtime=original_updated_at,
            version_nbr=4,
        )

        record = contract_services._sync_operations_request(legacy_request, actor_id="sync-1")
        record.refresh_from_db()

        self.assertEqual(record.status_code, REQUEST_STATUS_FULFILLED)
        self.assertEqual(record.version_nbr, 4)

    @patch("operations.contract_services.operations_policy.get_agency_scope")
    def test_request_sync_uses_decision_requesting_agency_when_payload_omitted(self, get_agency_scope_mock) -> None:
        get_agency_scope_mock.return_value = self.agency_scope

        record = contract_services._sync_operations_request(
            self.request,
            actor_id="sync-1",
            decision=operations_policy.ReliefRequestWriteDecision(
                agency_scope=self.agency_scope,
                origin_mode=ORIGIN_MODE_FOR_SUBORDINATE,
                requesting_tenant_id=30,
                beneficiary_tenant_id=20,
                requesting_agency_id=777,
                beneficiary_agency_id=501,
            ),
        )

        self.assertEqual(record.requesting_tenant_id, 30)
        self.assertEqual(record.requesting_agency_id, 777)
        self.assertEqual(record.beneficiary_agency_id, 501)

    @patch("operations.contract_services.get_request", return_value={"reliefrqst_id": 70})
    @patch("operations.contract_services._sync_operations_request")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service.create_request", return_value={"reliefrqst_id": 70})
    @patch("operations.contract_services.operations_policy.validate_relief_request_agency_selection")
    def test_create_request_coerces_integer_payload_fields_before_sync(
        self,
        validate_selection_mock,
        _create_request_mock,
        load_request_mock,
        sync_request_mock,
        get_request_mock,
    ) -> None:
        validate_selection_mock.return_value = operations_policy.ReliefRequestWriteDecision(
            agency_scope=self.agency_scope,
            origin_mode=ORIGIN_MODE_SELF,
            requesting_tenant_id=20,
            beneficiary_tenant_id=20,
            requesting_agency_id=501,
            beneficiary_agency_id=501,
        )
        load_request_mock.return_value = self.request

        result = contract_services.create_request(
            payload={
                "agency_id": "501",
                "source_needs_list_id": "17",
                "requesting_agency_id": "777",
            },
            actor_id="requester-1",
            tenant_context=self.dispatch_ready_context,
            permissions=[PERM_OPERATIONS_REQUEST_CREATE_SELF],
        )

        self.assertEqual(result, {"reliefrqst_id": 70})
        validate_selection_mock.assert_called_once_with(
            agency_id=501,
            tenant_context=self.dispatch_ready_context,
        )
        self.assertEqual(sync_request_mock.call_args.kwargs["source_needs_list_id"], 17)
        self.assertEqual(sync_request_mock.call_args.kwargs["requesting_agency_id"], 777)
        get_request_mock.assert_called_once_with(
            70,
            actor_id="requester-1",
            tenant_context=self.dispatch_ready_context,
            actor_roles=(),
        )

    @patch("operations.contract_services.operations_policy.validate_relief_request_agency_selection")
    def test_create_request_rejects_invalid_agency_id_before_policy_validation(
        self,
        validate_selection_mock,
    ) -> None:
        with self.assertRaises(OperationValidationError) as raised:
            contract_services.create_request(
                payload={"agency_id": "bad-id"},
                actor_id="requester-1",
                tenant_context=self.dispatch_ready_context,
                permissions=[PERM_OPERATIONS_REQUEST_CREATE_SELF],
            )

        self.assertEqual(
            raised.exception.errors,
            {"agency_id": "agency_id must be a valid integer value."},
        )
        validate_selection_mock.assert_not_called()

    @patch("operations.contract_services.operations_policy.validate_relief_request_agency_selection")
    def test_create_request_requires_request_notes_for_high_urgency(
        self,
        validate_selection_mock,
    ) -> None:
        with self.assertRaises(OperationValidationError) as raised:
            contract_services.create_request(
                payload={
                    "agency_id": 501,
                    "urgency_ind": "H",
                    "rqst_notes_text": "   ",
                },
                actor_id="requester-1",
                tenant_context=self.dispatch_ready_context,
                permissions=[PERM_OPERATIONS_REQUEST_CREATE_SELF],
            )

        self.assertEqual(
            raised.exception.errors,
            {"rqst_notes_text": "Justification is required for high-urgency requests."},
        )
        validate_selection_mock.assert_not_called()

    @patch("operations.contract_services.legacy_service.update_request")
    def test_update_request_rejects_invalid_requesting_agency_id_before_legacy_write(
        self,
        update_request_mock,
    ) -> None:
        with self.assertRaises(OperationValidationError) as raised:
            contract_services.update_request(
                70,
                payload={"requesting_agency_id": "bad-id"},
                actor_id="requester-1",
                tenant_context=self.dispatch_ready_context,
                permissions=[PERM_OPERATIONS_REQUEST_CREATE_SELF],
            )

        self.assertEqual(
            raised.exception.errors,
            {"requesting_agency_id": "requesting_agency_id must be a valid integer value."},
        )
        update_request_mock.assert_not_called()

    @patch("operations.contract_services.operations_policy.validate_relief_request_agency_selection")
    @patch("operations.contract_services.legacy_service._load_request")
    def test_update_request_requires_request_notes_when_draft_becomes_high_urgency(
        self,
        load_request_mock,
        validate_selection_mock,
    ) -> None:
        draft_request = self._request_stub(
            reliefrqst_id=70,
            agency_id=501,
            status_code=contract_services.STATUS_DRAFT,
        )
        draft_request.urgency_ind = "M"
        draft_request.rqst_notes_text = None
        load_request_mock.side_effect = [draft_request, draft_request]

        with self.assertRaises(OperationValidationError) as raised:
            contract_services.update_request(
                70,
                payload={"urgency_ind": "H"},
                actor_id="requester-1",
                tenant_context=self.dispatch_ready_context,
                permissions=[PERM_OPERATIONS_REQUEST_CREATE_SELF],
            )

        self.assertEqual(
            raised.exception.errors,
            {"rqst_notes_text": "Justification is required for high-urgency requests."},
        )
        validate_selection_mock.assert_not_called()

    @patch("operations.contract_services.get_request", return_value={"reliefrqst_id": 70})
    @patch("operations.contract_services.operations_policy.validate_relief_request_agency_selection")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service.update_request")
    def test_update_request_validates_current_request_agency_before_legacy_write(
        self,
        update_request_mock,
        load_request_mock,
        validate_selection_mock,
        _get_request_mock,
    ) -> None:
        validate_selection_mock.return_value = operations_policy.ReliefRequestWriteDecision(
            agency_scope=self.agency_scope,
            origin_mode=ORIGIN_MODE_SELF,
            requesting_tenant_id=20,
            beneficiary_tenant_id=20,
            requesting_agency_id=501,
            beneficiary_agency_id=501,
        )
        load_request_mock.side_effect = [self.request, self.request]

        def _update_side_effect(*args, **kwargs):
            self.assertTrue(validate_selection_mock.called)
            return {"reliefrqst_id": 70}

        update_request_mock.side_effect = _update_side_effect

        contract_services.update_request(
            70,
            payload={"rqst_notes_text": "Updated note"},
            actor_id="requester-1",
            tenant_context=self.dispatch_ready_context,
            permissions=[PERM_OPERATIONS_REQUEST_CREATE_SELF],
        )

        validate_selection_mock.assert_called_once_with(
            agency_id=501,
            tenant_context=self.dispatch_ready_context,
        )
        update_request_mock.assert_called_once()

    @patch("operations.contract_services.legacy_service.update_request")
    @patch("operations.contract_services.legacy_service._load_request")
    def test_update_request_rejects_invalid_beneficiary_agency_before_legacy_write(
        self,
        load_request_mock,
        update_request_mock,
    ) -> None:
        load_request_mock.return_value = self.request

        with self.assertRaises(OperationValidationError) as raised:
            contract_services.update_request(
                70,
                payload={"beneficiary_agency_id": "bad-id"},
                actor_id="requester-1",
                tenant_context=self.dispatch_ready_context,
                permissions=[PERM_OPERATIONS_REQUEST_CREATE_SELF],
            )

        self.assertEqual(
            raised.exception.errors,
            {"agency_id": "agency_id must be a valid integer value."},
        )
        update_request_mock.assert_not_called()

    @patch("operations.contract_services.operations_policy.validate_relief_request_agency_selection")
    def test_create_request_rejects_item_reason_longer_than_255_characters(
        self,
        validate_selection_mock,
    ) -> None:
        with self.assertRaises(OperationValidationError) as raised:
            contract_services.create_request(
                payload={
                    "agency_id": 501,
                    "urgency_ind": "M",
                    "items": [
                        {
                            "item_id": 101,
                            "request_qty": "3",
                            "urgency_ind": "H",
                            "rqst_reason_desc": "x" * 256,
                        }
                    ],
                },
                actor_id="requester-1",
                tenant_context=self.dispatch_ready_context,
                permissions=[PERM_OPERATIONS_REQUEST_CREATE_SELF],
            )

        self.assertEqual(
            raised.exception.errors,
            {"items[0].rqst_reason_desc": "Reason must be 255 characters or fewer."},
        )
        validate_selection_mock.assert_not_called()

    @patch("operations.contract_services.operations_policy.validate_relief_request_agency_selection")
    def test_create_request_still_requires_reason_for_critical_items(
        self,
        validate_selection_mock,
    ) -> None:
        with self.assertRaises(OperationValidationError) as raised:
            contract_services.create_request(
                payload={
                    "agency_id": 501,
                    "urgency_ind": "M",
                    "items": [
                        {
                            "item_id": 101,
                            "request_qty": "3",
                            "urgency_ind": "C",
                        }
                    ],
                },
                actor_id="requester-1",
                tenant_context=self.dispatch_ready_context,
                permissions=[PERM_OPERATIONS_REQUEST_CREATE_SELF],
            )

        self.assertEqual(
            raised.exception.errors,
            {"items[0].rqst_reason_desc": "Reason is required for high-priority items."},
        )
        validate_selection_mock.assert_not_called()

    @patch("operations.contract_services.get_request", return_value={"reliefrqst_id": 70})
    @patch("operations.contract_services.operations_policy.validate_relief_request_agency_selection")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service.update_request", return_value={"reliefrqst_id": 70})
    def test_update_request_allows_clearing_source_needs_list_id(
        self,
        _update_request_mock,
        load_request_mock,
        validate_selection_mock,
        _get_request_mock,
    ) -> None:
        record = self._create_operations_request_record()
        record.source_needs_list_id = 17
        record.save(update_fields=["source_needs_list_id"])
        load_request_mock.return_value = self.request
        validate_selection_mock.return_value = operations_policy.ReliefRequestWriteDecision(
            agency_scope=self.agency_scope,
            origin_mode=ORIGIN_MODE_SELF,
            requesting_tenant_id=20,
            beneficiary_tenant_id=20,
            requesting_agency_id=501,
            beneficiary_agency_id=501,
        )

        contract_services.update_request(
            70,
            payload={"source_needs_list_id": None},
            actor_id="requester-1",
            tenant_context=self.dispatch_ready_context,
            permissions=[PERM_OPERATIONS_REQUEST_CREATE_SELF],
        )

        record.refresh_from_db()
        self.assertIsNone(record.source_needs_list_id)

    @patch(
        "operations.contract_services._request_summary_payload",
        side_effect=lambda request, request_record: {
            "requesting_tenant_id": request_record.requesting_tenant_id,
            "request_mode": request_record.origin_mode,
            "origin_mode": request_record.origin_mode,
            "requesting_agency_id": request_record.requesting_agency_id,
            "beneficiary_tenant_id": request_record.beneficiary_tenant_id,
            "beneficiary_agency_id": request_record.beneficiary_agency_id,
        },
    )
    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.ReliefPkg.objects.filter")
    @patch("operations.contract_services.legacy_service.get_request", return_value={"reliefrqst_id": 70})
    @patch("operations.contract_services.legacy_service._load_request")
    def test_get_request_probe_uses_persisted_requesting_tenant_for_controller_scope(
        self,
        load_request_mock,
        _legacy_get_request_mock,
        reliefpkg_filter_mock,
        get_agency_scope_mock,
        _request_summary_mock,
    ) -> None:
        OperationsReliefRequest.objects.create(
            relief_request_id=70,
            request_no="RQ00070",
            requesting_tenant_id=30,
            requesting_agency_id=777,
            beneficiary_tenant_id=20,
            beneficiary_agency_id=501,
            origin_mode=ORIGIN_MODE_FOR_SUBORDINATE,
            event_id=12,
            request_date=date(2026, 3, 26),
            urgency_code="H",
            status_code=REQUEST_STATUS_APPROVED_FOR_FULFILLMENT,
            create_by_id="tester",
            update_by_id="tester",
        )
        load_request_mock.return_value = self._request_stub(reliefrqst_id=70, agency_id=501, status_code=3)
        get_agency_scope_mock.return_value = self.agency_scope
        reliefpkg_filter_mock.return_value.order_by.return_value = []

        result = contract_services.get_request(
            70,
            actor_id="controller-1",
            actor_roles=[],
            tenant_context=_tenant_context(tenant_id=30, tenant_code="CTRL-30", tenant_type="PARISH"),
        )

        self.assertEqual(result["requesting_tenant_id"], 30)
        self.assertEqual(result["request_mode"], ORIGIN_MODE_FOR_SUBORDINATE)
        self.assertEqual(result["origin_mode"], ORIGIN_MODE_FOR_SUBORDINATE)
        self.assertEqual(result["requesting_agency_id"], 777)
        self.assertEqual(result["beneficiary_tenant_id"], 20)
        self.assertEqual(result["beneficiary_agency_id"], 501)

    def test_package_sync_skips_version_bump_when_record_matches_legacy(self) -> None:
        original_updated_at = timezone.make_aware(datetime(2026, 3, 26, 8, 45, 0))
        committed_at = timezone.make_aware(datetime(2026, 3, 26, 8, 0, 0))
        self._create_operations_request_record()
        OperationsPackage.objects.create(
            package_id=90,
            package_no="PK00090",
            relief_request_id=70,
            source_warehouse_id=4,
            destination_tenant_id=20,
            destination_agency_id=501,
            status_code=PACKAGE_STATUS_COMMITTED,
            committed_at=committed_at,
            create_by_id="seed-user",
            update_by_id="seed-user",
            update_dtime=original_updated_at,
            version_nbr=9,
        )

        record = contract_services._sync_operations_package(
            self._package_stub(reliefpkg_id=90, reliefrqst_id=70, agency_id=501, status_code="P"),
            request_record=SimpleNamespace(beneficiary_tenant_id=20, beneficiary_agency_id=501),
            actor_id="sync-1",
            status_code=PACKAGE_STATUS_COMMITTED,
            source_warehouse_id=4,
        )
        record.refresh_from_db()

        self.assertEqual(record.version_nbr, 9)
        self.assertEqual(record.update_by_id, "seed-user")
        self.assertEqual(record.update_dtime, original_updated_at)

    def test_package_sync_preserves_pending_override_status_when_legacy_package_is_still_draft(self) -> None:
        original_updated_at = timezone.make_aware(datetime(2026, 3, 26, 8, 45, 0))
        self._create_operations_request_record()
        OperationsPackage.objects.create(
            package_id=90,
            package_no="PK00090",
            relief_request_id=70,
            destination_tenant_id=20,
            destination_agency_id=501,
            status_code=PACKAGE_STATUS_PENDING_OVERRIDE_APPROVAL,
            override_status_code=contract_services.OVERRIDE_STATUS_PENDING_APPROVAL,
            create_by_id="seed-user",
            update_by_id="seed-user",
            update_dtime=original_updated_at,
            version_nbr=5,
        )

        record = contract_services._sync_operations_package(
            self._package_stub(reliefpkg_id=90, reliefrqst_id=70, agency_id=501, status_code="A"),
            request_record=SimpleNamespace(beneficiary_tenant_id=20, beneficiary_agency_id=501),
            actor_id="sync-1",
        )
        record.refresh_from_db()

        self.assertEqual(record.status_code, PACKAGE_STATUS_PENDING_OVERRIDE_APPROVAL)
        self.assertEqual(record.override_status_code, contract_services.OVERRIDE_STATUS_PENDING_APPROVAL)
        self.assertEqual(record.version_nbr, 5)
        self.assertEqual(record.update_by_id, "seed-user")
        self.assertEqual(record.update_dtime, original_updated_at)

    def test_package_sync_records_frozen_override_status_when_override_is_approved(self) -> None:
        self._create_operations_request_record()
        OperationsPackage.objects.create(
            package_id=90,
            package_no="PK00090",
            relief_request_id=70,
            destination_tenant_id=20,
            destination_agency_id=501,
            status_code=PACKAGE_STATUS_PENDING_OVERRIDE_APPROVAL,
            override_status_code=contract_services.OVERRIDE_STATUS_PENDING_APPROVAL,
            create_by_id="seed-user",
            update_by_id="seed-user",
            version_nbr=5,
        )

        record = contract_services._sync_operations_package(
            self._package_stub(reliefpkg_id=90, reliefrqst_id=70, agency_id=501, status_code="P"),
            request_record=SimpleNamespace(beneficiary_tenant_id=20, beneficiary_agency_id=501),
            actor_id="sync-1",
            status_code=PACKAGE_STATUS_COMMITTED,
            override_status_code=contract_services.OVERRIDE_STATUS_APPROVED,
        )
        record.refresh_from_db()

        self.assertEqual(record.status_code, PACKAGE_STATUS_COMMITTED)
        self.assertEqual(record.override_status_code, contract_services.OVERRIDE_STATUS_APPROVED)

    def test_package_sync_uses_legacy_package_timestamps_when_present(self) -> None:
        self._create_operations_request_record()
        cases = [
            (
                90,
                SimpleNamespace(
                    reliefpkg_id=90,
                    tracking_no="PK00090",
                    reliefrqst_id=70,
                    agency_id=501,
                    eligible_event_id=12,
                    to_inventory_id=8,
                    transport_mode=None,
                    comments_text=None,
                    status_code="P",
                    committed_dtime=datetime(2026, 3, 26, 11, 0, 0),
                    dispatch_dtime=None,
                    received_dtime=None,
                    received_by_id=None,
                    update_by_id="locker-1",
                    update_dtime=datetime(2026, 3, 26, 10, 0, 0),
                    version_nbr=1,
                    save=lambda **kwargs: None,
                ),
                PACKAGE_STATUS_COMMITTED,
                "committed_at",
                timezone.make_aware(datetime(2026, 3, 26, 11, 0, 0)),
            ),
            (
                91,
                SimpleNamespace(
                    reliefpkg_id=91,
                    tracking_no="PK00091",
                    reliefrqst_id=70,
                    agency_id=501,
                    eligible_event_id=12,
                    to_inventory_id=8,
                    transport_mode=None,
                    comments_text=None,
                    status_code="D",
                    committed_dtime=None,
                    dispatch_dtime=datetime(2026, 3, 26, 12, 0, 0),
                    received_dtime=None,
                    received_by_id=None,
                    update_by_id="locker-1",
                    update_dtime=datetime(2026, 3, 26, 10, 0, 0),
                    version_nbr=1,
                    save=lambda **kwargs: None,
                ),
                PACKAGE_STATUS_DISPATCHED,
                "dispatched_at",
                timezone.make_aware(datetime(2026, 3, 26, 12, 0, 0)),
            ),
            (
                92,
                SimpleNamespace(
                    reliefpkg_id=92,
                    tracking_no="PK00092",
                    reliefrqst_id=70,
                    agency_id=501,
                    eligible_event_id=12,
                    to_inventory_id=8,
                    transport_mode=None,
                    comments_text=None,
                    status_code="C",
                    committed_dtime=None,
                    dispatch_dtime=None,
                    received_dtime=datetime(2026, 3, 26, 13, 0, 0),
                    received_by_id="receiver-1",
                    update_by_id="locker-1",
                    update_dtime=datetime(2026, 3, 26, 10, 0, 0),
                    version_nbr=1,
                    save=lambda **kwargs: None,
                ),
                PACKAGE_STATUS_RECEIVED,
                "received_at",
                timezone.make_aware(datetime(2026, 3, 26, 13, 0, 0)),
            ),
        ]

        for package_id, package, status_code, timestamp_field, expected in cases:
            OperationsPackage.objects.create(
                package_id=package_id,
                package_no=f"PK{package_id:05d}",
                relief_request_id=70,
                destination_tenant_id=20,
                destination_agency_id=501,
                status_code=status_code,
                create_by_id="seed-user",
                update_by_id="seed-user",
            )

            record = contract_services._sync_operations_package(
                package,
                request_record=SimpleNamespace(beneficiary_tenant_id=20, beneficiary_agency_id=501),
                actor_id="sync-1",
                status_code=status_code,
            )
            record.refresh_from_db()

            self.assertEqual(getattr(record, timestamp_field), expected)

    def test_approve_override_requires_package_pending_override_status(self) -> None:
        with (
            patch("operations.contract_services.legacy_service._load_request", return_value=self.request),
            patch(
                "operations.contract_services._sync_operations_request",
                return_value=SimpleNamespace(beneficiary_tenant_id=20, beneficiary_agency_id=501),
            ),
            patch("operations.contract_services._ensure_fulfillment_request_access"),
            patch(
                "operations.contract_services.legacy_service._current_package_for_request",
                return_value=self.package,
            ),
            patch(
                "operations.contract_services._sync_operations_package",
                return_value=SimpleNamespace(status_code=PACKAGE_STATUS_COMMITTED),
            ),
            patch("operations.contract_services.legacy_service.approve_override") as approve_override_mock,
        ):
            with self.assertRaises(OperationValidationError) as raised:
                contract_services.approve_override(
                    70,
                    payload={"allocations": [{"item_id": 101, "quantity": "1"}]},
                    actor_id="manager-1",
                    actor_roles=["LOGISTICS_MANAGER"],
                    tenant_context=self.dispatch_ready_context,
                    idempotency_key="override-70",
                )

        self.assertEqual(
            raised.exception.errors["override"],
            "Package is not awaiting override approval.",
        )
        approve_override_mock.assert_not_called()

    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._current_package_for_request")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service.approve_override")
    def test_approve_override_preserves_no_self_approval_for_actual_override_submitter(
        self,
        approve_override_mock,
        load_request_mock,
        current_package_mock,
        get_agency_scope_mock,
    ) -> None:
        request_record = self._create_operations_request_record()
        request_record.create_by_id = "requester-1"
        request_record.save(update_fields=["create_by_id"])
        OperationsPackage.objects.create(
            package_id=90,
            package_no="PK00090",
            relief_request=request_record,
            source_warehouse_id=4,
            destination_tenant_id=20,
            destination_agency_id=501,
            status_code=PACKAGE_STATUS_PENDING_OVERRIDE_APPROVAL,
            override_status_code=contract_services.OVERRIDE_STATUS_PENDING_APPROVAL,
            create_by_id="manager-1",
            update_by_id="manager-1",
        )
        OperationsStatusHistory.objects.create(
            entity_type="PACKAGE",
            entity_id=90,
            from_status_code=PACKAGE_STATUS_DRAFT,
            to_status_code=PACKAGE_STATUS_PENDING_OVERRIDE_APPROVAL,
            changed_by_id="manager-1",
        )
        request = self._request_stub(
            reliefrqst_id=70,
            agency_id=501,
            status_code=contract_services.legacy_service.STATUS_SUBMITTED,
        )
        request.create_by_id = "requester-1"
        load_request_mock.return_value = request
        current_package_mock.return_value = self._package_stub(
            reliefpkg_id=90,
            reliefrqst_id=70,
            agency_id=501,
            status_code="P",
        )
        get_agency_scope_mock.return_value = self.agency_scope

        with self.assertRaises(contract_services.OverrideApprovalError):
            contract_services.approve_override(
                70,
                payload={
                    "allocations": [{"item_id": 101, "inventory_id": 4, "batch_id": 1001, "quantity": "2"}],
                    "override_reason_code": "FEFO_BYPASS",
                    "override_note": "Supervisor approved.",
                },
                actor_id="manager-1",
                actor_roles=[ROLE_LOGISTICS_MANAGER],
                tenant_context=self.dispatch_ready_context,
                idempotency_key="override-approve-70",
            )

        approve_override_mock.assert_not_called()

    @patch("operations.contract_services._resolve_request_level_fulfillment_tenant_id", return_value=27)
    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._current_package_for_request")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service.approve_override")
    def test_approve_override_completes_override_queue_and_routes_direct_package_to_dispatch(
        self,
        approve_override_mock,
        load_request_mock,
        current_package_mock,
        get_agency_scope_mock,
        _mock_request_level_tenant,
    ) -> None:
        request_record = self._create_operations_request_record()
        package_record = OperationsPackage.objects.create(
            package_id=90,
            package_no="PK00090",
            relief_request=request_record,
            source_warehouse_id=4,
            destination_tenant_id=20,
            destination_agency_id=501,
            status_code=PACKAGE_STATUS_PENDING_OVERRIDE_APPROVAL,
            override_status_code=contract_services.OVERRIDE_STATUS_PENDING_APPROVAL,
            create_by_id="fulfiller-1",
            update_by_id="fulfiller-1",
        )
        OperationsStatusHistory.objects.create(
            entity_type="PACKAGE",
            entity_id=90,
            from_status_code=PACKAGE_STATUS_DRAFT,
            to_status_code=PACKAGE_STATUS_PENDING_OVERRIDE_APPROVAL,
            changed_by_id="fulfiller-1",
        )
        OperationsQueueAssignment.objects.create(
            queue_code=QUEUE_CODE_OVERRIDE,
            entity_type="RELIEF_REQUEST",
            entity_id=70,
            assigned_role_code=ROLE_LOGISTICS_MANAGER,
            assigned_tenant_id=20,
            assignment_status="OPEN",
        )
        load_request_mock.return_value = self.fulfillment_request
        current_package_mock.return_value = self._package_stub(
            reliefpkg_id=90,
            reliefrqst_id=70,
            agency_id=501,
            status_code="P",
        )
        get_agency_scope_mock.return_value = self.agency_scope
        approve_override_mock.return_value = {"reliefrqst_id": 70, "status": "COMMITTED"}

        result = contract_services.approve_override(
            70,
            payload={
                "allocations": [{"item_id": 101, "inventory_id": 4, "batch_id": 1001, "quantity": "2"}],
                "override_reason_code": "FEFO_BYPASS",
                "override_note": "Supervisor approved.",
            },
            actor_id="manager-1",
            actor_roles=[ROLE_LOGISTICS_MANAGER],
            tenant_context=self.dispatch_ready_context,
            idempotency_key="override-70",
        )

        package_record.refresh_from_db()
        request_record.refresh_from_db()
        override_assignment = OperationsQueueAssignment.objects.get(
            queue_code=QUEUE_CODE_OVERRIDE,
            entity_type="RELIEF_REQUEST",
            entity_id=70,
            assigned_role_code=ROLE_LOGISTICS_MANAGER,
        )
        self.assertEqual(result["status"], PACKAGE_STATUS_COMMITTED)
        self.assertEqual(result["request_status"], REQUEST_STATUS_APPROVED_FOR_FULFILLMENT)
        self.assertEqual(result["package"]["status_code"], PACKAGE_STATUS_COMMITTED)
        self.assertEqual(package_record.status_code, PACKAGE_STATUS_COMMITTED)
        self.assertEqual(package_record.override_status_code, contract_services.OVERRIDE_STATUS_APPROVED)
        self.assertEqual(request_record.status_code, REQUEST_STATUS_APPROVED_FOR_FULFILLMENT)
        self.assertEqual(override_assignment.assignment_status, "COMPLETED")
        self.assertTrue(
            OperationsQueueAssignment.objects.filter(
                queue_code=QUEUE_CODE_DISPATCH,
                entity_type="PACKAGE",
                entity_id=90,
                assigned_role_code=ROLE_LOGISTICS_MANAGER,
                assigned_tenant_id=20,
                assignment_status="OPEN",
            ).exists()
        )
        self.assertTrue(
            OperationsNotification.objects.filter(
                event_code=contract_services.EVENT_OVERRIDE_APPROVED,
                entity_type="PACKAGE",
                entity_id=90,
                queue_code=QUEUE_CODE_DISPATCH,
            ).exists()
        )
        self.assertTrue(
            OperationsNotification.objects.filter(
                event_code=contract_services.EVENT_OVERRIDE_APPROVED,
                entity_type="PACKAGE",
                entity_id=90,
                recipient_user_id="fulfiller-1",
            ).exists()
        )
        self.assertTrue(
            OperationsStatusHistory.objects.filter(
                entity_type="PACKAGE",
                entity_id=90,
                from_status_code=PACKAGE_STATUS_PENDING_OVERRIDE_APPROVAL,
                to_status_code=PACKAGE_STATUS_COMMITTED,
                changed_by_id="manager-1",
            ).exists()
        )
        self.assertTrue(
            OperationsActionAudit.objects.filter(
                package_id=90,
                action_code=contract_services.ACTION_OVERRIDE_APPROVED,
                action_reason="Supervisor approved.",
                acted_by_user_id="manager-1",
            ).exists()
        )

    @patch("operations.contract_services._resolve_request_level_fulfillment_tenant_id", return_value=27)
    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._current_package_for_request")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service.approve_override")
    def test_approve_override_routes_staged_off_hub_package_to_consolidation(
        self,
        approve_override_mock,
        load_request_mock,
        current_package_mock,
        get_agency_scope_mock,
        _mock_request_level_tenant,
    ) -> None:
        request_record = self._create_operations_request_record()
        package_record = OperationsPackage.objects.create(
            package_id=90,
            package_no="PK00090",
            relief_request=request_record,
            source_warehouse_id=4,
            destination_tenant_id=20,
            destination_agency_id=501,
            status_code=PACKAGE_STATUS_PENDING_OVERRIDE_APPROVAL,
            override_status_code=contract_services.OVERRIDE_STATUS_PENDING_APPROVAL,
            fulfillment_mode=FULFILLMENT_MODE_DELIVER_FROM_STAGING,
            staging_warehouse_id=8,
            create_by_id="fulfiller-1",
            update_by_id="fulfiller-1",
        )
        OperationsAllocationLine.objects.create(
            package=package_record,
            item_id=101,
            source_warehouse_id=4,
            batch_id=1001,
            quantity=Decimal("2.0000"),
            source_type="ON_HAND",
            create_by_id="fulfiller-1",
            update_by_id="fulfiller-1",
        )
        OperationsStatusHistory.objects.create(
            entity_type="PACKAGE",
            entity_id=90,
            from_status_code=PACKAGE_STATUS_DRAFT,
            to_status_code=PACKAGE_STATUS_PENDING_OVERRIDE_APPROVAL,
            changed_by_id="fulfiller-1",
        )
        OperationsQueueAssignment.objects.create(
            queue_code=QUEUE_CODE_OVERRIDE,
            entity_type="RELIEF_REQUEST",
            entity_id=70,
            assigned_role_code=ROLE_LOGISTICS_MANAGER,
            assigned_tenant_id=20,
            assignment_status="OPEN",
        )
        load_request_mock.return_value = self.fulfillment_request
        current_package_mock.return_value = self._package_stub(
            reliefpkg_id=90,
            reliefrqst_id=70,
            agency_id=501,
            status_code="P",
        )
        get_agency_scope_mock.return_value = self.agency_scope
        approve_override_mock.return_value = {"reliefrqst_id": 70, "status": "COMMITTED"}

        result = contract_services.approve_override(
            70,
            payload={
                "allocations": [{"item_id": 101, "inventory_id": 4, "batch_id": 1001, "quantity": "2"}],
                "override_reason_code": "FEFO_BYPASS",
                "override_note": "Approved for staging flow.",
            },
            actor_id="manager-1",
            actor_roles=[ROLE_LOGISTICS_MANAGER],
            tenant_context=self.dispatch_ready_context,
            idempotency_key="override-stage-70",
        )

        package_record.refresh_from_db()
        request_record.refresh_from_db()
        self.assertEqual(result["status"], PACKAGE_STATUS_CONSOLIDATING)
        self.assertEqual(result["request_status"], REQUEST_STATUS_APPROVED_FOR_FULFILLMENT)
        self.assertEqual(result["package"]["status_code"], PACKAGE_STATUS_CONSOLIDATING)
        self.assertEqual(package_record.status_code, PACKAGE_STATUS_CONSOLIDATING)
        self.assertEqual(package_record.override_status_code, contract_services.OVERRIDE_STATUS_APPROVED)
        self.assertEqual(request_record.status_code, REQUEST_STATUS_APPROVED_FOR_FULFILLMENT)
        self.assertEqual(package_record.consolidation_status, CONSOLIDATION_STATUS_AWAITING_LEGS)
        self.assertEqual(package_record.consolidation_legs.count(), 1)
        leg = package_record.consolidation_legs.get()
        self.assertEqual(leg.source_warehouse_id, 4)
        self.assertEqual(leg.staging_warehouse_id, 8)
        self.assertTrue(
            OperationsQueueAssignment.objects.filter(
                queue_code=QUEUE_CODE_CONSOLIDATION_DISPATCH,
                entity_type="CONSOLIDATION_LEG",
                entity_id=leg.leg_id,
                assigned_tenant_id=20,
                assignment_status="OPEN",
            ).exists()
        )
        self.assertTrue(
            OperationsActionAudit.objects.filter(
                package_id=90,
                action_code=contract_services.ACTION_OVERRIDE_APPROVED,
            ).exists()
        )

    @patch("operations.contract_services._resolve_request_level_fulfillment_tenant_id", return_value=27)
    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._current_package_for_request")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service.approve_override")
    def test_approve_override_routes_staged_at_hub_package_to_pickup_release(
        self,
        approve_override_mock,
        load_request_mock,
        current_package_mock,
        get_agency_scope_mock,
        _mock_request_level_tenant,
    ) -> None:
        request_record = self._create_operations_request_record()
        package_record = OperationsPackage.objects.create(
            package_id=90,
            package_no="PK00090",
            relief_request=request_record,
            source_warehouse_id=8,
            destination_tenant_id=20,
            destination_agency_id=501,
            status_code=PACKAGE_STATUS_PENDING_OVERRIDE_APPROVAL,
            override_status_code=contract_services.OVERRIDE_STATUS_PENDING_APPROVAL,
            fulfillment_mode=FULFILLMENT_MODE_PICKUP_AT_STAGING,
            staging_warehouse_id=8,
            create_by_id="fulfiller-1",
            update_by_id="fulfiller-1",
        )
        OperationsAllocationLine.objects.create(
            package=package_record,
            item_id=101,
            source_warehouse_id=8,
            batch_id=1001,
            quantity=Decimal("2.0000"),
            source_type="ON_HAND",
            create_by_id="fulfiller-1",
            update_by_id="fulfiller-1",
        )
        OperationsStatusHistory.objects.create(
            entity_type="PACKAGE",
            entity_id=90,
            from_status_code=PACKAGE_STATUS_DRAFT,
            to_status_code=PACKAGE_STATUS_PENDING_OVERRIDE_APPROVAL,
            changed_by_id="fulfiller-1",
        )
        OperationsQueueAssignment.objects.create(
            queue_code=QUEUE_CODE_OVERRIDE,
            entity_type="RELIEF_REQUEST",
            entity_id=70,
            assigned_role_code=ROLE_LOGISTICS_MANAGER,
            assigned_tenant_id=20,
            assignment_status="OPEN",
        )
        load_request_mock.return_value = self.fulfillment_request
        current_package_mock.return_value = self._package_stub(
            reliefpkg_id=90,
            reliefrqst_id=70,
            agency_id=501,
            status_code="P",
        )
        get_agency_scope_mock.return_value = self.agency_scope
        approve_override_mock.return_value = {"reliefrqst_id": 70, "status": "COMMITTED"}

        result = contract_services.approve_override(
            70,
            payload={
                "allocations": [{"item_id": 101, "inventory_id": 8, "batch_id": 1001, "quantity": "2"}],
                "override_reason_code": "FEFO_BYPASS",
                "override_note": "Approved for pickup.",
            },
            actor_id="manager-1",
            actor_roles=[ROLE_LOGISTICS_MANAGER],
            tenant_context=self.dispatch_ready_context,
            idempotency_key="override-pickup-70",
        )

        package_record.refresh_from_db()
        request_record.refresh_from_db()
        self.assertEqual(result["status"], PACKAGE_STATUS_READY_FOR_PICKUP)
        self.assertEqual(result["request_status"], REQUEST_STATUS_APPROVED_FOR_FULFILLMENT)
        self.assertEqual(result["package"]["status_code"], PACKAGE_STATUS_READY_FOR_PICKUP)
        self.assertEqual(package_record.status_code, PACKAGE_STATUS_READY_FOR_PICKUP)
        self.assertEqual(package_record.override_status_code, contract_services.OVERRIDE_STATUS_APPROVED)
        self.assertEqual(request_record.status_code, REQUEST_STATUS_APPROVED_FOR_FULFILLMENT)
        self.assertTrue(
            OperationsQueueAssignment.objects.filter(
                queue_code=QUEUE_CODE_PICKUP_RELEASE,
                entity_type="PACKAGE",
                entity_id=90,
                assignment_status="OPEN",
            ).exists()
        )
        self.assertFalse(package_record.consolidation_legs.exists())

    @patch("operations.contract_services._save_package_allocation")
    @patch("operations.contract_services._current_package_for_request")
    @patch("operations.contract_services._load_request")
    def test_legacy_override_approve_uses_pending_override_transition_actor_as_submitter(
        self,
        load_request_mock,
        current_package_mock,
        save_package_allocation_mock,
    ) -> None:
        request = self._request_stub(
            reliefrqst_id=70,
            agency_id=501,
            status_code=contract_services.legacy_service.STATUS_SUBMITTED,
        )
        request.create_by_id = "requester-1"
        package = self._package_stub(
            reliefpkg_id=90,
            reliefrqst_id=70,
            agency_id=501,
            status_code="A",
        )
        package.create_by_id = "allocator-1"
        load_request_mock.return_value = request
        current_package_mock.return_value = package
        OperationsStatusHistory.objects.create(
            entity_type="PACKAGE",
            entity_id=90,
            from_status_code=PACKAGE_STATUS_DRAFT,
            to_status_code=PACKAGE_STATUS_PENDING_OVERRIDE_APPROVAL,
            changed_by_id="override-requester-1",
        )
        save_package_allocation_mock.return_value = {"status": "COMMITTED"}

        result = contract_services.legacy_service.approve_override(
            70,
            payload={
                "allocations": [{"item_id": 101, "inventory_id": 4, "batch_id": 1001, "quantity": "2"}],
                "override_reason_code": "FEFO_BYPASS",
                "override_note": "Supervisor approved.",
            },
            actor_id="manager-1",
            actor_roles=[ROLE_LOGISTICS_MANAGER],
        )

        self.assertEqual(result, {"status": "COMMITTED"})
        self.assertEqual(
            save_package_allocation_mock.call_args.kwargs["override_submitter_user_id"],
            "override-requester-1",
        )

    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._current_package_for_request")
    @patch("operations.contract_services.legacy_service._load_request")
    def test_reject_override_preserves_no_self_approval_for_actual_override_submitter(
        self,
        load_request_mock,
        current_package_mock,
        get_agency_scope_mock,
    ) -> None:
        request_record = self._create_operations_request_record()
        request_record.create_by_id = "requester-1"
        request_record.save(update_fields=["create_by_id"])
        OperationsPackage.objects.create(
            package_id=90,
            package_no="PK00090",
            relief_request=request_record,
            source_warehouse_id=4,
            destination_tenant_id=20,
            destination_agency_id=501,
            status_code=PACKAGE_STATUS_PENDING_OVERRIDE_APPROVAL,
            override_status_code=contract_services.OVERRIDE_STATUS_PENDING_APPROVAL,
            create_by_id="manager-1",
            update_by_id="manager-1",
        )
        OperationsQueueAssignment.objects.create(
            queue_code=QUEUE_CODE_OVERRIDE,
            entity_type="RELIEF_REQUEST",
            entity_id=70,
            assigned_role_code=ROLE_LOGISTICS_MANAGER,
            assigned_tenant_id=20,
            assignment_status="OPEN",
        )
        OperationsStatusHistory.objects.create(
            entity_type="PACKAGE",
            entity_id=90,
            from_status_code=PACKAGE_STATUS_DRAFT,
            to_status_code=PACKAGE_STATUS_PENDING_OVERRIDE_APPROVAL,
            changed_by_id="manager-1",
        )
        request = self._request_stub(
            reliefrqst_id=70,
            agency_id=501,
            status_code=contract_services.legacy_service.STATUS_SUBMITTED,
        )
        request.create_by_id = "requester-1"
        load_request_mock.return_value = request
        package = self._package_stub(
            reliefpkg_id=90,
            reliefrqst_id=70,
            agency_id=501,
            status_code="A",
        )
        package.create_by_id = "fulfiller-1"
        current_package_mock.return_value = package
        get_agency_scope_mock.return_value = self.agency_scope

        with self.assertRaises(contract_services.OverrideApprovalError):
            contract_services.reject_override(
                70,
                payload={"reason": "Rejecting my own override."},
                actor_id="manager-1",
                actor_roles=[ROLE_LOGISTICS_MANAGER],
                tenant_context=self.dispatch_ready_context,
                idempotency_key="override-reject-70",
            )

    def test_return_override_requires_reason(self) -> None:
        with self.assertRaises(OperationValidationError) as raised:
            contract_services.return_override(
                70,
                payload={"reason": "   "},
                actor_id="manager-1",
                actor_roles=[ROLE_LOGISTICS_MANAGER],
                tenant_context=self.dispatch_ready_context,
                idempotency_key="override-return-70",
            )

        self.assertEqual(
            raised.exception.errors,
            {"reason": "Reason is required when returning an override for adjustments."},
        )

    @patch("operations.contract_services._resolve_request_level_fulfillment_tenant_id", return_value=27)
    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._current_package_for_request")
    @patch("operations.contract_services.legacy_service._load_request")
    def test_return_override_returns_same_package_to_draft_and_reopens_fulfillment_work(
        self,
        load_request_mock,
        current_package_mock,
        get_agency_scope_mock,
        _mock_request_level_tenant,
    ) -> None:
        request_record = self._create_operations_request_record()
        package_record = OperationsPackage.objects.create(
            package_id=90,
            package_no="PK00090",
            relief_request=request_record,
            source_warehouse_id=4,
            destination_tenant_id=20,
            destination_agency_id=501,
            status_code=PACKAGE_STATUS_PENDING_OVERRIDE_APPROVAL,
            override_status_code=contract_services.OVERRIDE_STATUS_PENDING_APPROVAL,
            create_by_id="fulfiller-1",
            update_by_id="fulfiller-1",
        )
        OperationsAllocationLine.objects.create(
            package=package_record,
            item_id=101,
            source_warehouse_id=4,
            batch_id=1001,
            quantity=Decimal("2.0000"),
            source_type="ON_HAND",
            reason_text="FEFO_BYPASS",
            create_by_id="fulfiller-1",
            update_by_id="fulfiller-1",
        )
        OperationsQueueAssignment.objects.create(
            queue_code=QUEUE_CODE_OVERRIDE,
            entity_type="RELIEF_REQUEST",
            entity_id=70,
            assigned_role_code=ROLE_LOGISTICS_MANAGER,
            assigned_tenant_id=20,
            assignment_status="OPEN",
        )
        OperationsStatusHistory.objects.create(
            entity_type="PACKAGE",
            entity_id=90,
            from_status_code=PACKAGE_STATUS_DRAFT,
            to_status_code=PACKAGE_STATUS_PENDING_OVERRIDE_APPROVAL,
            changed_by_id="fulfiller-1",
        )
        load_request_mock.return_value = self.fulfillment_request
        current_package_mock.return_value = self._package_stub(
            reliefpkg_id=90,
            reliefrqst_id=70,
            agency_id=501,
            status_code="A",
        )
        get_agency_scope_mock.return_value = self.agency_scope

        result = contract_services.return_override(
            70,
            payload={"reason": "Adjust allocations to match compliant stock order."},
            actor_id="manager-1",
            actor_roles=[ROLE_LOGISTICS_MANAGER],
            tenant_context=self.dispatch_ready_context,
            idempotency_key="override-return-70",
        )

        package_record.refresh_from_db()
        request_record.refresh_from_db()
        override_assignment = OperationsQueueAssignment.objects.get(
            queue_code=QUEUE_CODE_OVERRIDE,
            entity_type="RELIEF_REQUEST",
            entity_id=70,
            assigned_role_code=ROLE_LOGISTICS_MANAGER,
        )
        self.assertEqual(result["status"], PACKAGE_STATUS_DRAFT)
        self.assertEqual(result["override_status_code"], contract_services.OVERRIDE_STATUS_RETURNED_FOR_ADJUSTMENT)
        self.assertEqual(package_record.status_code, PACKAGE_STATUS_DRAFT)
        self.assertEqual(
            package_record.override_status_code,
            contract_services.OVERRIDE_STATUS_RETURNED_FOR_ADJUSTMENT,
        )
        self.assertTrue(OperationsAllocationLine.objects.filter(package_id=90).exists())
        self.assertEqual(request_record.status_code, REQUEST_STATUS_APPROVED_FOR_FULFILLMENT)
        self.assertEqual(override_assignment.assignment_status, "COMPLETED")
        self.assertTrue(
            OperationsQueueAssignment.objects.filter(
                queue_code=QUEUE_CODE_FULFILLMENT,
                entity_type="RELIEF_REQUEST",
                entity_id=70,
                assigned_role_code=ROLE_LOGISTICS_OFFICER,
                assignment_status="OPEN",
            ).exists()
        )
        self.assertFalse(
            OperationsQueueAssignment.objects.filter(
                queue_code__in=[
                    QUEUE_CODE_DISPATCH,
                    QUEUE_CODE_CONSOLIDATION_DISPATCH,
                    QUEUE_CODE_PICKUP_RELEASE,
                ],
                entity_id=90,
                assignment_status="OPEN",
            ).exists()
        )
        self.assertTrue(
            OperationsNotification.objects.filter(
                event_code=contract_services.EVENT_OVERRIDE_RETURNED_FOR_ADJUSTMENT,
                entity_type="PACKAGE",
                entity_id=90,
                recipient_user_id="fulfiller-1",
            ).exists()
        )
        self.assertTrue(
            OperationsStatusHistory.objects.filter(
                entity_type="PACKAGE",
                entity_id=90,
                from_status_code=PACKAGE_STATUS_PENDING_OVERRIDE_APPROVAL,
                to_status_code=PACKAGE_STATUS_DRAFT,
                changed_by_id="manager-1",
            ).exists()
        )
        self.assertTrue(
            OperationsActionAudit.objects.filter(
                package_id=90,
                action_code=contract_services.ACTION_OVERRIDE_RETURNED_FOR_ADJUSTMENT,
                action_reason="Adjust allocations to match compliant stock order.",
                acted_by_user_id="manager-1",
            ).exists()
        )

    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._current_package_for_request")
    @patch("operations.contract_services.legacy_service._load_request")
    def test_return_override_preserves_no_self_approval_for_actual_override_submitter(
        self,
        load_request_mock,
        current_package_mock,
        get_agency_scope_mock,
    ) -> None:
        request_record = self._create_operations_request_record()
        request_record.create_by_id = "requester-1"
        request_record.save(update_fields=["create_by_id"])
        OperationsPackage.objects.create(
            package_id=90,
            package_no="PK00090",
            relief_request=request_record,
            source_warehouse_id=4,
            destination_tenant_id=20,
            destination_agency_id=501,
            status_code=PACKAGE_STATUS_PENDING_OVERRIDE_APPROVAL,
            override_status_code=contract_services.OVERRIDE_STATUS_PENDING_APPROVAL,
            create_by_id="manager-1",
            update_by_id="manager-1",
        )
        OperationsStatusHistory.objects.create(
            entity_type="PACKAGE",
            entity_id=90,
            from_status_code=PACKAGE_STATUS_DRAFT,
            to_status_code=PACKAGE_STATUS_PENDING_OVERRIDE_APPROVAL,
            changed_by_id="manager-1",
        )
        request = self._request_stub(
            reliefrqst_id=70,
            agency_id=501,
            status_code=contract_services.legacy_service.STATUS_SUBMITTED,
        )
        request.create_by_id = "requester-1"
        load_request_mock.return_value = request
        current_package_mock.return_value = self._package_stub(
            reliefpkg_id=90,
            reliefrqst_id=70,
            agency_id=501,
            status_code="A",
        )
        get_agency_scope_mock.return_value = self.agency_scope

        with self.assertRaises(contract_services.OverrideApprovalError):
            contract_services.return_override(
                70,
                payload={"reason": "Sending my own override back."},
                actor_id="manager-1",
                actor_roles=[ROLE_LOGISTICS_MANAGER],
                tenant_context=self.dispatch_ready_context,
                idempotency_key="override-return-self-70",
            )

    def test_reject_override_requires_reason(self) -> None:
        with self.assertRaises(OperationValidationError) as raised:
            contract_services.reject_override(
                70,
                payload={"reason": "   "},
                actor_id="manager-1",
                actor_roles=[ROLE_LOGISTICS_MANAGER],
                tenant_context=self.dispatch_ready_context,
                idempotency_key="override-reject-70",
            )

        self.assertEqual(
            raised.exception.errors,
            {"reason": "Reason is required when rejecting an override."},
        )

    @patch("operations.contract_services._resolve_request_level_fulfillment_tenant_id", return_value=27)
    @patch("operations.contract_services.reset_package_allocations")
    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._current_package_for_request")
    @patch("operations.contract_services.legacy_service._load_request")
    def test_reject_override_marks_package_rejected_and_preserves_evidence(
        self,
        load_request_mock,
        current_package_mock,
        get_agency_scope_mock,
        reset_package_allocations_mock,
        _mock_request_level_tenant,
    ) -> None:
        request_record = self._create_operations_request_record()
        package_record = OperationsPackage.objects.create(
            package_id=90,
            package_no="PK00090",
            relief_request=request_record,
            source_warehouse_id=4,
            destination_tenant_id=20,
            destination_agency_id=501,
            status_code=PACKAGE_STATUS_PENDING_OVERRIDE_APPROVAL,
            override_status_code=contract_services.OVERRIDE_STATUS_PENDING_APPROVAL,
            create_by_id="fulfiller-1",
            update_by_id="fulfiller-1",
        )
        OperationsAllocationLine.objects.create(
            package=package_record,
            item_id=101,
            source_warehouse_id=4,
            batch_id=1001,
            quantity=Decimal("2.0000"),
            source_type="ON_HAND",
            create_by_id="fulfiller-1",
            update_by_id="fulfiller-1",
        )
        OperationsQueueAssignment.objects.create(
            queue_code=QUEUE_CODE_OVERRIDE,
            entity_type="RELIEF_REQUEST",
            entity_id=70,
            assigned_role_code=ROLE_LOGISTICS_MANAGER,
            assigned_tenant_id=20,
            assignment_status="OPEN",
        )
        OperationsStatusHistory.objects.create(
            entity_type="PACKAGE",
            entity_id=90,
            from_status_code=PACKAGE_STATUS_DRAFT,
            to_status_code=PACKAGE_STATUS_PENDING_OVERRIDE_APPROVAL,
            changed_by_id="fulfiller-1",
        )
        OperationsPackageLock.objects.create(
            package=package_record,
            lock_owner_user_id="fulfiller-1",
            lock_owner_role_code=ROLE_LOGISTICS_OFFICER,
            lock_status="ACTIVE",
        )
        package = self._package_stub(
            reliefpkg_id=90,
            reliefrqst_id=70,
            agency_id=501,
            status_code="A",
        )
        load_request_mock.return_value = self.fulfillment_request
        current_package_mock.return_value = package
        get_agency_scope_mock.return_value = self.agency_scope

        result = contract_services.reject_override(
            70,
            payload={"reason": "Rebuild with compliant stock order."},
            actor_id="manager-1",
            actor_roles=[ROLE_LOGISTICS_MANAGER],
            tenant_context=self.dispatch_ready_context,
            idempotency_key="override-reject-70",
        )

        package_record.refresh_from_db()
        request_record.refresh_from_db()
        override_assignment = OperationsQueueAssignment.objects.get(
            queue_code=QUEUE_CODE_OVERRIDE,
            entity_type="RELIEF_REQUEST",
            entity_id=70,
            assigned_role_code=ROLE_LOGISTICS_MANAGER,
        )
        package_lock = OperationsPackageLock.objects.get(package_id=90)
        self.assertEqual(result["status"], PACKAGE_STATUS_REJECTED)
        self.assertEqual(result["override_status_code"], contract_services.OVERRIDE_STATUS_REJECTED)
        reset_package_allocations_mock.assert_not_called()
        self.assertEqual(package_record.status_code, PACKAGE_STATUS_REJECTED)
        self.assertEqual(package_record.override_status_code, contract_services.OVERRIDE_STATUS_REJECTED)
        self.assertTrue(OperationsAllocationLine.objects.filter(package_id=90).exists())
        self.assertEqual(request_record.status_code, REQUEST_STATUS_APPROVED_FOR_FULFILLMENT)
        self.assertEqual(override_assignment.assignment_status, "COMPLETED")
        self.assertEqual(package_lock.lock_status, "RELEASED")
        self.assertFalse(
            OperationsQueueAssignment.objects.filter(
                queue_code__in=[
                    QUEUE_CODE_FULFILLMENT,
                    QUEUE_CODE_DISPATCH,
                    QUEUE_CODE_CONSOLIDATION_DISPATCH,
                    QUEUE_CODE_PICKUP_RELEASE,
                ],
                entity_id__in=[70, 90],
                assignment_status="OPEN",
            ).exists()
        )
        self.assertTrue(
            OperationsNotification.objects.filter(
                event_code=contract_services.EVENT_OVERRIDE_REJECTED,
                entity_type="PACKAGE",
                entity_id=90,
                recipient_user_id="fulfiller-1",
            ).exists()
        )
        self.assertTrue(
            OperationsStatusHistory.objects.filter(
                entity_type="PACKAGE",
                entity_id=90,
                from_status_code=PACKAGE_STATUS_PENDING_OVERRIDE_APPROVAL,
                to_status_code=PACKAGE_STATUS_REJECTED,
                changed_by_id="manager-1",
            ).exists()
        )
        self.assertTrue(
            OperationsActionAudit.objects.filter(
                package_id=90,
                action_code=contract_services.ACTION_OVERRIDE_REJECTED,
                action_reason="Rebuild with compliant stock order.",
                acted_by_user_id="manager-1",
            ).exists()
        )

    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._current_package_for_request")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service.save_package")
    def test_save_package_creates_fresh_package_after_rejected_current_package(
        self,
        save_package_mock,
        load_request_mock,
        current_package_mock,
        get_agency_scope_mock,
    ) -> None:
        request_record = self._create_operations_request_record(relief_request_id=81, agency_id=501)
        rejected_package_record = OperationsPackage.objects.create(
            package_id=90,
            package_no="PK00090",
            relief_request=request_record,
            source_warehouse_id=4,
            destination_tenant_id=20,
            destination_agency_id=501,
            status_code=PACKAGE_STATUS_REJECTED,
            override_status_code=contract_services.OVERRIDE_STATUS_REJECTED,
            create_by_id="fulfiller-1",
            update_by_id="manager-1",
        )
        OperationsAllocationLine.objects.create(
            package=rejected_package_record,
            item_id=101,
            source_warehouse_id=4,
            batch_id=1001,
            quantity=Decimal("2.0000"),
            source_type="ON_HAND",
            reason_text="FEFO_BYPASS",
            create_by_id="fulfiller-1",
            update_by_id="manager-1",
        )
        request = self._request_stub(
            reliefrqst_id=81,
            agency_id=501,
            status_code=contract_services.legacy_service.STATUS_SUBMITTED,
        )
        old_package = self._package_stub(
            reliefpkg_id=90,
            reliefrqst_id=81,
            agency_id=501,
            status_code="A",
        )
        new_package = self._package_stub(
            reliefpkg_id=91,
            reliefrqst_id=81,
            agency_id=501,
            status_code="P",
        )
        load_request_mock.return_value = request
        current_package_mock.side_effect = [old_package, new_package, new_package]
        get_agency_scope_mock.return_value = self.agency_scope
        save_package_mock.return_value = {
            "status": "COMMITTED",
            "reliefpkg_id": 91,
            "allocation_lines": [
                {"item_id": 101, "inventory_id": 4, "batch_id": 1001, "quantity": "2.0000"},
            ],
        }

        contract_services.save_package(
            81,
            payload={
                "allocations": [
                    {"item_id": 101, "inventory_id": 4, "batch_id": 1001, "quantity": "2.0000"},
                ],
            },
            actor_id="fulfiller-2",
            actor_roles=[ROLE_LOGISTICS_OFFICER],
            tenant_context=self.dispatch_ready_context,
        )

        rejected_package_record.refresh_from_db()
        new_package_record = OperationsPackage.objects.get(package_id=91)
        self.assertEqual(rejected_package_record.status_code, PACKAGE_STATUS_REJECTED)
        self.assertEqual(
            list(
                OperationsAllocationLine.objects.filter(package_id=90).values_list("item_id", flat=True)
            ),
            [101],
        )
        self.assertEqual(new_package_record.status_code, PACKAGE_STATUS_COMMITTED)
        self.assertEqual(
            list(
                OperationsAllocationLine.objects.filter(package_id=91).values_list("item_id", flat=True)
            ),
            [101],
        )

    def test_ensure_dispatch_record_updates_existing_route_fields(self) -> None:
        self._create_operations_request_record()
        dispatched_at = timezone.make_aware(datetime(2026, 3, 26, 12, 0, 0))
        package_record = OperationsPackage.objects.create(
            package_id=90,
            package_no="PK00090",
            relief_request_id=70,
            source_warehouse_id=4,
            destination_tenant_id=20,
            destination_agency_id=501,
            status_code=PACKAGE_STATUS_DISPATCHED,
            dispatched_at=dispatched_at,
            create_by_id="seed-user",
            update_by_id="seed-user",
        )
        dispatch = OperationsDispatch.objects.create(
            package_id=90,
            dispatch_no="DP00090",
            status_code="READY",
            dispatch_at=None,
            source_warehouse_id=4,
            destination_tenant_id=20,
            destination_agency_id=501,
            create_by_id="seed-user",
            update_by_id="seed-user",
        )

        updated_dispatch = contract_services._ensure_dispatch_record(
            package=self._package_stub(reliefpkg_id=90, reliefrqst_id=70, agency_id=501, status_code="P"),
            package_record=SimpleNamespace(
                package_id=package_record.package_id,
                status_code=PACKAGE_STATUS_DISPATCHED,
                dispatched_at=dispatched_at,
                source_warehouse_id=9,
                destination_tenant_id=30,
                destination_agency_id=777,
            ),
            actor_id="sync-1",
        )
        dispatch.refresh_from_db()

        self.assertEqual(updated_dispatch.dispatch_id, dispatch.dispatch_id)
        self.assertEqual(dispatch.status_code, DISPATCH_STATUS_IN_TRANSIT)
        self.assertEqual(dispatch.dispatch_at, dispatched_at)
        self.assertEqual(dispatch.source_warehouse_id, 9)
        self.assertEqual(dispatch.destination_tenant_id, 30)
        self.assertEqual(dispatch.destination_agency_id, 777)
        self.assertEqual(dispatch.update_by_id, "sync-1")
        self.assertEqual(dispatch.version_nbr, 2)

    def test_get_dispatch_package_does_not_create_dispatch_for_uncommitted_package(self) -> None:
        """Viewing the dispatch page for a DRAFT package must not side-effect a dispatch row."""
        self._create_operations_request_record()
        package_record = OperationsPackage.objects.create(
            package_id=90,
            package_no="PK00090",
            relief_request_id=70,
            source_warehouse_id=4,
            destination_tenant_id=20,
            destination_agency_id=501,
            status_code=PACKAGE_STATUS_DRAFT,
            create_by_id="seed-user",
            update_by_id="seed-user",
        )

        self.assertEqual(OperationsDispatch.objects.filter(package_id=90).count(), 0)

        with (
            patch(
                "operations.contract_services.legacy_service._load_package",
                return_value=self._package_stub(reliefpkg_id=90, reliefrqst_id=70, agency_id=501, status_code="X"),
            ),
            patch(
                "operations.contract_services.legacy_service._load_request",
                return_value=self.request,
            ),
            patch(
                "operations.contract_services._sync_operations_request",
                return_value=SimpleNamespace(beneficiary_tenant_id=20, beneficiary_agency_id=501),
            ),
            patch(
                "operations.contract_services._sync_operations_package",
                return_value=package_record,
            ),
            patch("operations.contract_services._ensure_package_access"),
            patch("operations.contract_services.get_package", return_value={"reliefpkg_id": 90}),
            patch("operations.contract_services._request_summary_payload", return_value={"reliefrqst_id": 70}),
        ):
            payload = contract_services.get_dispatch_package(
                90,
                actor_id="manager-1",
                actor_roles=["LOGISTICS_MANAGER"],
                tenant_context=self.dispatch_ready_context,
            )

        self.assertIsNone(payload["dispatch"])
        self.assertIsNone(payload["waybill"])
        self.assertEqual(OperationsDispatch.objects.filter(package_id=90).count(), 0)

    def test_get_dispatch_package_materializes_dispatch_when_committed(self) -> None:
        """A COMMITTED package returns a populated dispatch and reuses the existing row."""
        self._create_operations_request_record()
        package_record = OperationsPackage.objects.create(
            package_id=90,
            package_no="PK00090",
            relief_request_id=70,
            source_warehouse_id=4,
            destination_tenant_id=20,
            destination_agency_id=501,
            status_code=PACKAGE_STATUS_COMMITTED,
            create_by_id="seed-user",
            update_by_id="seed-user",
        )

        self.assertEqual(OperationsDispatch.objects.filter(package_id=90).count(), 0)

        with (
            patch(
                "operations.contract_services.legacy_service._load_package",
                return_value=self._package_stub(reliefpkg_id=90, reliefrqst_id=70, agency_id=501, status_code="P"),
            ),
            patch(
                "operations.contract_services.legacy_service._load_request",
                return_value=self.request,
            ),
            patch(
                "operations.contract_services._sync_operations_request",
                return_value=SimpleNamespace(beneficiary_tenant_id=20, beneficiary_agency_id=501),
            ),
            patch(
                "operations.contract_services._sync_operations_package",
                return_value=package_record,
            ),
            patch("operations.contract_services._ensure_package_access"),
            patch("operations.contract_services.get_package", return_value={"reliefpkg_id": 90}),
            patch("operations.contract_services._request_summary_payload", return_value={"reliefrqst_id": 70}),
        ):
            first_payload = contract_services.get_dispatch_package(
                90,
                actor_id="manager-1",
                actor_roles=["LOGISTICS_MANAGER"],
                tenant_context=self.dispatch_ready_context,
            )

            self.assertIsNotNone(first_payload["dispatch"])
            self.assertEqual(first_payload["dispatch"]["dispatch_no"], OperationsDispatch.objects.get(package_id=90).dispatch_no)
            self.assertEqual(OperationsDispatch.objects.filter(package_id=90).count(), 1)

            second_payload = contract_services.get_dispatch_package(
                90,
                actor_id="manager-1",
                actor_roles=["LOGISTICS_MANAGER"],
                tenant_context=self.dispatch_ready_context,
            )

            self.assertIsNotNone(second_payload["dispatch"])
            self.assertEqual(
                second_payload["dispatch"]["dispatch_id"],
                first_payload["dispatch"]["dispatch_id"],
            )
            self.assertEqual(OperationsDispatch.objects.filter(package_id=90).count(), 1)

    @patch("operations.contract_services.get_request", return_value={"reliefrqst_id": 70})
    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service.submit_request")
    def test_submit_request_creates_eligibility_queue_and_notifications(
        self,
        _submit_request_mock,
        load_request_mock,
        get_agency_scope_mock,
        _get_request_mock,
    ) -> None:
        load_request_mock.return_value = self.request
        get_agency_scope_mock.return_value = self.agency_scope

        contract_services.submit_request(
            70,
            actor_id="requester-1",
            tenant_context=self.dispatch_ready_context,
            idempotency_key="submit-70",
        )

        request_record = OperationsReliefRequest.objects.get(relief_request_id=70)
        self.assertEqual(request_record.status_code, REQUEST_STATUS_UNDER_ELIGIBILITY_REVIEW)
        self.assertEqual(
            OperationsQueueAssignment.objects.filter(queue_code=QUEUE_CODE_ELIGIBILITY, entity_id=70).count(),
            len(ELIGIBILITY_ROLE_CODES),
        )
        self.assertEqual(
            OperationsNotification.objects.filter(queue_code=QUEUE_CODE_ELIGIBILITY, entity_id=70).count(),
            len(ELIGIBILITY_ROLE_CODES),
        )

    @patch("operations.contract_services.get_request", return_value={"reliefrqst_id": 70})
    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service.submit_request")
    def test_submit_request_reuses_cached_response_for_same_idempotency_key(
        self,
        submit_request_mock,
        load_request_mock,
        get_agency_scope_mock,
        _get_request_mock,
    ) -> None:
        load_request_mock.return_value = self.request
        get_agency_scope_mock.return_value = self.agency_scope

        with self.captureOnCommitCallbacks(execute=True):
            first = contract_services.submit_request(
                70,
                actor_id="requester-1",
                tenant_context=self.dispatch_ready_context,
                idempotency_key="submit-70",
            )
        queue_count = OperationsQueueAssignment.objects.filter(queue_code=QUEUE_CODE_ELIGIBILITY, entity_id=70).count()
        notification_count = OperationsNotification.objects.filter(queue_code=QUEUE_CODE_ELIGIBILITY, entity_id=70).count()
        second = contract_services.submit_request(
            70,
            actor_id="requester-1",
            tenant_context=self.dispatch_ready_context,
            idempotency_key="submit-70",
        )

        self.assertEqual(first, second)
        self.assertEqual(submit_request_mock.call_count, 1)
        self.assertEqual(load_request_mock.call_count, 1)
        self.assertEqual(
            OperationsQueueAssignment.objects.filter(queue_code=QUEUE_CODE_ELIGIBILITY, entity_id=70).count(),
            queue_count,
        )
        self.assertEqual(
            OperationsNotification.objects.filter(queue_code=QUEUE_CODE_ELIGIBILITY, entity_id=70).count(),
            notification_count,
        )

    @patch("operations.contract_services.get_request", return_value={"reliefrqst_id": 70})
    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service.submit_request")
    def test_submit_request_idempotency_cache_is_tenant_scoped(
        self,
        submit_request_mock,
        load_request_mock,
        get_agency_scope_mock,
        _get_request_mock,
    ) -> None:
        load_request_mock.return_value = self.request
        get_agency_scope_mock.return_value = self.agency_scope
        foreign_tenant_context = _tenant_context(
            tenant_id=999,
            tenant_code="OTHER-TENANT",
            tenant_type="EXTERNAL",
        )

        def _submit_side_effect(reliefrqst_id: int, *, actor_id: str, tenant_context) -> None:
            if tenant_context is foreign_tenant_context:
                raise OperationValidationError(
                    {"scope": "Request is outside the active tenant or workflow assignment scope."}
                )

        submit_request_mock.side_effect = _submit_side_effect

        with self.captureOnCommitCallbacks(execute=True):
            contract_services.submit_request(
                70,
                actor_id="requester-1",
                tenant_context=self.dispatch_ready_context,
                idempotency_key="submit-70",
            )

        with self.assertRaises(OperationValidationError) as raised:
            contract_services.submit_request(
                70,
                actor_id="requester-1",
                tenant_context=foreign_tenant_context,
                idempotency_key="submit-70",
            )

        self.assertIn("scope", raised.exception.errors)
        self.assertEqual(submit_request_mock.call_count, 2)

    @patch("operations.contract_services.cache.set")
    @patch("operations.contract_services.get_request", return_value={"reliefrqst_id": 70})
    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service.submit_request")
    def test_submit_request_defers_idempotency_cache_until_commit(
        self,
        _submit_request_mock,
        load_request_mock,
        get_agency_scope_mock,
        _get_request_mock,
        cache_set_mock,
    ) -> None:
        load_request_mock.return_value = self.request
        get_agency_scope_mock.return_value = self.agency_scope

        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            result = contract_services.submit_request(
                70,
                actor_id="requester-1",
                tenant_context=self.dispatch_ready_context,
                idempotency_key="submit-70",
            )

        cache_set_mock.assert_not_called()
        self.assertEqual(len(callbacks), 1)
        callbacks[0]()
        cache_set_mock.assert_called_once()
        args, kwargs = cache_set_mock.call_args
        self.assertTrue(args[0].startswith("operations:idempotency:request_submit:requester-1:"))
        self.assertEqual(args[1], result)
        self.assertEqual(kwargs["timeout"], contract_services._IDEMPOTENCY_TTL_SECONDS)

    @patch("operations.contract_services.get_request", return_value={"reliefrqst_id": 70})
    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service.submit_request")
    def test_submit_request_releases_idempotency_reservation_after_failure(
        self,
        submit_request_mock,
        load_request_mock,
        get_agency_scope_mock,
        _get_request_mock,
    ) -> None:
        load_request_mock.return_value = self.request
        get_agency_scope_mock.return_value = self.agency_scope
        submit_request_mock.side_effect = [
            RuntimeError("transient submit failure"),
            None,
        ]

        with self.assertRaises(RuntimeError):
            contract_services.submit_request(
                70,
                actor_id="requester-1",
                tenant_context=self.dispatch_ready_context,
                idempotency_key="submit-70-failure",
            )

        cache_key = contract_services._idempotency_cache_key(
            endpoint="request_submit",
            actor_id="requester-1",
            tenant_context=self.dispatch_ready_context,
            reliefpkg_id=70,
            idempotency_key="submit-70-failure",
        )
        reservation_key = contract_services._idempotency_reservation_key(cache_key)
        self.assertIsNone(cache.get(cache_key))
        self.assertIsNone(cache.get(reservation_key))

        with self.captureOnCommitCallbacks(execute=True):
            second = contract_services.submit_request(
                70,
                actor_id="requester-1",
                tenant_context=self.dispatch_ready_context,
                idempotency_key="submit-70-failure",
            )

        self.assertEqual(submit_request_mock.call_count, 2)
        self.assertEqual(cache.get(cache_key), second)
        self.assertIsNone(cache.get(reservation_key))

    @patch("operations.contract_services.legacy_service.submit_request")
    def test_submit_request_requires_idempotency_key(self, submit_request_mock) -> None:
        with self.assertRaises(OperationValidationError) as raised:
            contract_services.submit_request(
                70,
                actor_id="requester-1",
                tenant_context=self.dispatch_ready_context,
            )

        self.assertEqual(
            raised.exception.errors,
            {"idempotency_key": "Idempotency-Key header is required."},
        )
        submit_request_mock.assert_not_called()

    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._current_package_for_request")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service.save_package")
    def test_package_commit_creates_lock_dispatch_queue_and_dispatch_record(
        self,
        save_package_mock,
        load_request_mock,
        current_package_mock,
        get_agency_scope_mock,
    ) -> None:
        load_request_mock.return_value = self.fulfillment_request
        current_package_mock.return_value = self.package
        save_package_mock.return_value = {"status": "COMMITTED", "reliefpkg_id": 90}
        get_agency_scope_mock.return_value = self.agency_scope

        contract_services.save_package(
            70,
            payload={"allocations": [{"item_id": 101, "inventory_id": 4, "batch_id": 1001, "quantity": "2"}]},
            actor_id="logistics-manager-1",
            actor_roles=self.dispatch_roles,
            permissions=None,
            tenant_context=self.dispatch_ready_context,
        )

        package_record = OperationsPackage.objects.get(package_id=90)
        self.assertEqual(package_record.status_code, "COMMITTED")
        self.assertTrue(OperationsPackageLock.objects.filter(package_id=90).exists())
        self.assertTrue(OperationsDispatch.objects.filter(package_id=90).exists())
        self.assertTrue(
            OperationsQueueAssignment.objects.filter(queue_code=QUEUE_CODE_DISPATCH, entity_id=90).exists()
        )
        self.assertEqual(
            set(
                OperationsQueueAssignment.objects.filter(queue_code=QUEUE_CODE_DISPATCH, entity_id=90)
                .values_list("assigned_tenant_id", flat=True)
            ),
            {20},
        )
        # First call loads for update, second re-syncs request status after legacy save
        self.assertEqual(load_request_mock.call_count, 2)
        load_request_mock.assert_any_call(70, for_update=True)
        load_request_mock.assert_any_call(70)

    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._current_package_for_request")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service.save_package")
    def test_intentional_partial_commit_remains_compliant_when_legacy_commit_succeeds(
        self,
        save_package_mock,
        load_request_mock,
        current_package_mock,
        get_agency_scope_mock,
    ) -> None:
        load_request_mock.return_value = self.fulfillment_request
        current_package_mock.return_value = self.package
        save_package_mock.return_value = {"status": "COMMITTED", "reliefpkg_id": 90}
        get_agency_scope_mock.return_value = self.agency_scope

        contract_services.save_package(
            70,
            payload={
                "allocations": [
                    {"item_id": 101, "inventory_id": 4, "batch_id": 1001, "quantity": "1.0000"}
                ]
            },
            actor_id="logistics-manager-1",
            actor_roles=self.dispatch_roles,
            tenant_context=self.dispatch_ready_context,
        )

        package_record = OperationsPackage.objects.get(package_id=90)
        self.assertEqual(package_record.status_code, PACKAGE_STATUS_COMMITTED)
        self.assertIsNone(package_record.override_status_code)
        self.assertFalse(
            OperationsQueueAssignment.objects.filter(
                queue_code=QUEUE_CODE_OVERRIDE,
                entity_type="RELIEF_REQUEST",
                entity_id=70,
            ).exists()
        )
        self.assertTrue(
            OperationsQueueAssignment.objects.filter(
                queue_code=QUEUE_CODE_DISPATCH,
                entity_type="PACKAGE",
                entity_id=90,
            ).exists()
        )

    @patch("operations.contract_services._apply_package_header_updates")
    @patch("operations.contract_services._apply_stock_delta_for_rows")
    @patch("operations.contract_services._upsert_package_rows")
    @patch("operations.contract_services.data_access.get_warehouses_with_stock")
    @patch("operations.contract_services._fetch_batch_candidates")
    @patch("operations.contract_services.Item.objects.filter")
    @patch(
        "operations.contract_services._request_item_rows_for_allocation",
        return_value=[
            {"item_id": 101, "request_qty": "5.0000", "issue_qty": "0.0000", "urgency_ind": "H"}
        ],
    )
    @patch("operations.contract_services._current_package_status", return_value="A")
    @patch("operations.contract_services._ensure_package")
    @patch("operations.contract_services._load_request")
    @patch("operations.contract_services._execution_link_for_request", return_value=None)
    def test_save_package_flags_override_when_better_ranked_warehouse_is_omitted(
        self,
        _execution_link_mock,
        load_request_mock,
        ensure_package_mock,
        _current_status_mock,
        _request_rows_mock,
        item_filter_mock,
        fetch_candidates_mock,
        get_warehouses_with_stock_mock,
        upsert_rows_mock,
        stock_delta_mock,
        header_updates_mock,
    ) -> None:
        load_request_mock.return_value = self._request_stub(
            reliefrqst_id=70,
            agency_id=501,
            status_code=contract_services.legacy_service.STATUS_SUBMITTED,
        )
        ensure_package_mock.return_value = self._package_stub(
            reliefpkg_id=90,
            reliefrqst_id=70,
            agency_id=501,
            status_code="A",
        )
        item_filter_mock.return_value = [SimpleNamespace(item_id=101, issuance_order="FIFO")]
        get_warehouses_with_stock_mock.return_value = (
            {
                101: [
                    {"warehouse_id": 1, "warehouse_name": "Warehouse 1", "available_qty": 3.0},
                    {"warehouse_id": 9, "warehouse_name": "Warehouse 9", "available_qty": 3.0},
                ]
            },
            [],
        )
        warehouse_candidates = {
            1: [
                {
                    "batch_id": 1001,
                    "inventory_id": 1,
                    "item_id": 101,
                    "batch_no": "B-1001",
                    "batch_date": date(2026, 3, 20),
                    "expiry_date": None,
                    "usable_qty": Decimal("3.0000"),
                    "reserved_qty": Decimal("0.0000"),
                    "available_qty": Decimal("3.0000"),
                    "uom_code": "EA",
                    "source_type": "ON_HAND",
                    "source_record_id": None,
                    "warehouse_name": "Warehouse 1",
                }
            ],
            9: [
                {
                    "batch_id": 9001,
                    "inventory_id": 9,
                    "item_id": 101,
                    "batch_no": "B-9001",
                    "batch_date": date(2026, 3, 25),
                    "expiry_date": None,
                    "usable_qty": Decimal("3.0000"),
                    "reserved_qty": Decimal("0.0000"),
                    "available_qty": Decimal("3.0000"),
                    "uom_code": "EA",
                    "source_type": "ON_HAND",
                    "source_record_id": None,
                    "warehouse_name": "Warehouse 9",
                }
            ],
        }
        fetch_candidates_mock.side_effect = (
            lambda warehouse_id, _item_id, as_of_date=None: list(
                warehouse_candidates.get(warehouse_id, [])
            )
        )

        result = contract_services._save_package_allocation(
            70,
            payload={
                "allocations": [
                    {
                        "item_id": 101,
                        "inventory_id": 9,
                        "batch_id": 9001,
                        "quantity": "2.0000",
                    }
                ],
                "override_reason_code": "FEFO_BYPASS",
                "override_note": "Need to allocate from the downstream warehouse first.",
            },
            actor_id="officer-1",
            actor_roles=[ROLE_LOGISTICS_OFFICER],
            actor_permissions=[PERM_OPERATIONS_PACKAGE_OVERRIDE_REQUEST],
            tenant_context=None,
            allow_pending_override=True,
        )

        self.assertEqual(result["status"], "PENDING_OVERRIDE_APPROVAL")
        self.assertTrue(result["override_required"])
        self.assertEqual(result["override_markers"], ["allocation_order_override"])
        self.assertEqual(upsert_rows_mock.call_args.kwargs["notes"], "FEFO_BYPASS")
        stock_delta_mock.assert_not_called()
        self.assertEqual(
            header_updates_mock.call_args.kwargs["status_code"],
            contract_services.PKG_STATUS_DRAFT,
        )
        self.assertEqual(
            sorted({call.args[0] for call in fetch_candidates_mock.call_args_list}),
            [1, 9],
        )

    @patch("operations.contract_services._apply_package_header_updates")
    @patch("operations.contract_services._apply_stock_delta_for_rows")
    @patch("operations.contract_services._upsert_package_rows")
    @patch("operations.contract_services.data_access.get_warehouses_with_stock")
    @patch("operations.contract_services._fetch_batch_candidates")
    @patch("operations.contract_services.Item.objects.filter")
    @patch(
        "operations.contract_services._request_item_rows_for_allocation",
        return_value=[
            {"item_id": 101, "request_qty": "5.0000", "issue_qty": "0.0000", "urgency_ind": "H"}
        ],
    )
    @patch("operations.contract_services._current_package_status", return_value="A")
    @patch("operations.contract_services._ensure_package")
    @patch("operations.contract_services._load_request")
    @patch("operations.contract_services._execution_link_for_request", return_value=None)
    def test_save_package_allows_ranked_continuation_without_override(
        self,
        _execution_link_mock,
        load_request_mock,
        ensure_package_mock,
        _current_status_mock,
        _request_rows_mock,
        item_filter_mock,
        fetch_candidates_mock,
        get_warehouses_with_stock_mock,
        upsert_rows_mock,
        stock_delta_mock,
        header_updates_mock,
    ) -> None:
        load_request_mock.return_value = self._request_stub(
            reliefrqst_id=70,
            agency_id=501,
            status_code=contract_services.legacy_service.STATUS_SUBMITTED,
        )
        ensure_package_mock.return_value = self._package_stub(
            reliefpkg_id=90,
            reliefrqst_id=70,
            agency_id=501,
            status_code="A",
        )
        item_filter_mock.return_value = [SimpleNamespace(item_id=101, issuance_order="FIFO")]
        get_warehouses_with_stock_mock.return_value = (
            {
                101: [
                    {"warehouse_id": 1, "warehouse_name": "Warehouse 1", "available_qty": 2.0},
                    {"warehouse_id": 9, "warehouse_name": "Warehouse 9", "available_qty": 4.0},
                ]
            },
            [],
        )
        warehouse_candidates = {
            1: [
                {
                    "batch_id": 1001,
                    "inventory_id": 1,
                    "item_id": 101,
                    "batch_no": "B-1001",
                    "batch_date": date(2026, 3, 20),
                    "expiry_date": None,
                    "usable_qty": Decimal("2.0000"),
                    "reserved_qty": Decimal("0.0000"),
                    "available_qty": Decimal("2.0000"),
                    "uom_code": "EA",
                    "source_type": "ON_HAND",
                    "source_record_id": None,
                    "warehouse_name": "Warehouse 1",
                }
            ],
            9: [
                {
                    "batch_id": 9001,
                    "inventory_id": 9,
                    "item_id": 101,
                    "batch_no": "B-9001",
                    "batch_date": date(2026, 3, 25),
                    "expiry_date": None,
                    "usable_qty": Decimal("4.0000"),
                    "reserved_qty": Decimal("0.0000"),
                    "available_qty": Decimal("4.0000"),
                    "uom_code": "EA",
                    "source_type": "ON_HAND",
                    "source_record_id": None,
                    "warehouse_name": "Warehouse 9",
                }
            ],
        }
        fetch_candidates_mock.side_effect = (
            lambda warehouse_id, _item_id, as_of_date=None: list(
                warehouse_candidates.get(warehouse_id, [])
            )
        )

        result = contract_services._save_package_allocation(
            70,
            payload={
                "allocations": [
                    {
                        "item_id": 101,
                        "inventory_id": 1,
                        "batch_id": 1001,
                        "quantity": "2.0000",
                        "uom_code": "EA",
                    },
                    {
                        "item_id": 101,
                        "inventory_id": 9,
                        "batch_id": 9001,
                        "quantity": "2.0000",
                        "uom_code": "EA",
                    },
                ]
            },
            actor_id="officer-1",
            actor_roles=[ROLE_LOGISTICS_OFFICER],
            actor_permissions=[PERM_OPERATIONS_PACKAGE_OVERRIDE_REQUEST],
            tenant_context=None,
            allow_pending_override=True,
        )

        self.assertEqual(result["status"], "COMMITTED")
        self.assertFalse(result["override_required"])
        self.assertEqual(result["override_markers"], [])
        self.assertEqual(upsert_rows_mock.call_args.kwargs["notes"], "RR:70")
        stock_delta_mock.assert_called_once()
        self.assertEqual(
            header_updates_mock.call_args.kwargs["status_code"],
            contract_services.PKG_STATUS_PENDING,
        )
        self.assertEqual(
            sorted({call.args[0] for call in fetch_candidates_mock.call_args_list}),
            [1, 9],
        )

    @patch("operations.contract_services._apply_package_header_updates")
    @patch("operations.contract_services._apply_stock_delta_for_rows")
    @patch("operations.contract_services._upsert_package_rows")
    @patch("operations.contract_services.data_access.get_warehouses_with_stock")
    @patch("operations.contract_services._fetch_batch_candidates")
    @patch("operations.contract_services.Item.objects.filter")
    @patch(
        "operations.contract_services._request_item_rows_for_allocation",
        return_value=[
            {"item_id": 101, "request_qty": "5.0000", "issue_qty": "0.0000", "urgency_ind": "H"}
        ],
    )
    @patch("operations.contract_services._current_package_status", return_value="A")
    @patch("operations.contract_services._ensure_package")
    @patch("operations.contract_services._load_request")
    @patch("operations.contract_services._execution_link_for_request", return_value=None)
    def test_save_package_allows_intentional_partial_commit_without_override(
        self,
        _execution_link_mock,
        load_request_mock,
        ensure_package_mock,
        _current_status_mock,
        _request_rows_mock,
        item_filter_mock,
        fetch_candidates_mock,
        get_warehouses_with_stock_mock,
        upsert_rows_mock,
        stock_delta_mock,
        header_updates_mock,
    ) -> None:
        load_request_mock.return_value = self._request_stub(
            reliefrqst_id=70,
            agency_id=501,
            status_code=contract_services.legacy_service.STATUS_SUBMITTED,
        )
        ensure_package_mock.return_value = self._package_stub(
            reliefpkg_id=90,
            reliefrqst_id=70,
            agency_id=501,
            status_code="A",
        )
        item_filter_mock.return_value = [SimpleNamespace(item_id=101, issuance_order="FIFO")]
        get_warehouses_with_stock_mock.return_value = (
            {
                101: [
                    {"warehouse_id": 1, "warehouse_name": "Warehouse 1", "available_qty": 2.0},
                    {"warehouse_id": 9, "warehouse_name": "Warehouse 9", "available_qty": 4.0},
                ]
            },
            [],
        )
        warehouse_candidates = {
            1: [
                {
                    "batch_id": 1001,
                    "inventory_id": 1,
                    "item_id": 101,
                    "batch_no": "B-1001",
                    "batch_date": date(2026, 3, 20),
                    "expiry_date": None,
                    "usable_qty": Decimal("2.0000"),
                    "reserved_qty": Decimal("0.0000"),
                    "available_qty": Decimal("2.0000"),
                    "uom_code": "EA",
                    "source_type": "ON_HAND",
                    "source_record_id": None,
                    "warehouse_name": "Warehouse 1",
                }
            ],
            9: [
                {
                    "batch_id": 9001,
                    "inventory_id": 9,
                    "item_id": 101,
                    "batch_no": "B-9001",
                    "batch_date": date(2026, 3, 25),
                    "expiry_date": None,
                    "usable_qty": Decimal("4.0000"),
                    "reserved_qty": Decimal("0.0000"),
                    "available_qty": Decimal("4.0000"),
                    "uom_code": "EA",
                    "source_type": "ON_HAND",
                    "source_record_id": None,
                    "warehouse_name": "Warehouse 9",
                }
            ],
        }
        fetch_candidates_mock.side_effect = (
            lambda warehouse_id, _item_id, as_of_date=None: list(
                warehouse_candidates.get(warehouse_id, [])
            )
        )

        result = contract_services._save_package_allocation(
            70,
            payload={
                "allocations": [
                    {
                        "item_id": 101,
                        "inventory_id": 1,
                        "batch_id": 1001,
                        "quantity": "2.0000",
                        "uom_code": "EA",
                    }
                ]
            },
            actor_id="officer-1",
            actor_roles=[ROLE_LOGISTICS_OFFICER],
            actor_permissions=[PERM_OPERATIONS_PACKAGE_OVERRIDE_REQUEST],
            tenant_context=None,
            allow_pending_override=True,
        )

        self.assertEqual(result["status"], "COMMITTED")
        self.assertFalse(result["override_required"])
        self.assertEqual(result["override_markers"], [])
        self.assertEqual(upsert_rows_mock.call_args.kwargs["notes"], "RR:70")
        stock_delta_mock.assert_called_once()
        self.assertEqual(
            header_updates_mock.call_args.kwargs["status_code"],
            contract_services.PKG_STATUS_PENDING,
        )
        self.assertEqual(
            sorted({call.args[0] for call in fetch_candidates_mock.call_args_list}),
            [1, 9],
        )

    @patch("operations.contract_services.compat_commit_allocation")
    @patch("operations.contract_services._current_package_for_request")
    @patch("operations.contract_services.data_access.get_warehouses_with_stock")
    @patch("operations.contract_services._fetch_batch_candidates")
    @patch("operations.contract_services.Item.objects.filter")
    @patch(
        "operations.contract_services._request_item_rows_for_allocation",
        return_value=[
            {"item_id": 101, "request_qty": "5.0000", "issue_qty": "0.0000", "urgency_ind": "H"}
        ],
    )
    @patch("operations.contract_services._load_request")
    @patch("operations.contract_services._execution_link_for_request")
    def test_execution_linked_save_package_passes_ranked_override_markers_to_compat_commit(
        self,
        execution_link_mock,
        load_request_mock,
        _request_rows_mock,
        item_filter_mock,
        fetch_candidates_mock,
        get_warehouses_with_stock_mock,
        current_package_mock,
        compat_commit_mock,
    ) -> None:
        execution_link_mock.return_value = SimpleNamespace(
            needs_list_id=11,
            reliefrqst_id=70,
            reliefpkg_id=90,
            override_requested_by="planner-1",
            needs_list=SimpleNamespace(
                warehouse_id=9,
                event_id=12,
                submitted_by="planner-1",
            ),
        )
        load_request_mock.return_value = self._request_stub(
            reliefrqst_id=70,
            agency_id=501,
            status_code=contract_services.legacy_service.STATUS_SUBMITTED,
        )
        current_package_mock.return_value = self._package_stub(
            reliefpkg_id=90,
            reliefrqst_id=70,
            agency_id=501,
            status_code="A",
        )
        compat_commit_mock.return_value = {"status": "PENDING_OVERRIDE_APPROVAL"}
        item_filter_mock.return_value = [SimpleNamespace(item_id=101, issuance_order="FIFO")]
        get_warehouses_with_stock_mock.return_value = (
            {
                101: [
                    {"warehouse_id": 1, "warehouse_name": "Warehouse 1", "available_qty": 3.0},
                    {"warehouse_id": 9, "warehouse_name": "Warehouse 9", "available_qty": 3.0},
                ]
            },
            [],
        )
        warehouse_candidates = {
            1: [
                {
                    "batch_id": 1001,
                    "inventory_id": 1,
                    "item_id": 101,
                    "batch_no": "B-1001",
                    "batch_date": date(2026, 3, 20),
                    "expiry_date": None,
                    "usable_qty": Decimal("3.0000"),
                    "reserved_qty": Decimal("0.0000"),
                    "available_qty": Decimal("3.0000"),
                    "uom_code": "EA",
                    "source_type": "ON_HAND",
                    "source_record_id": None,
                    "warehouse_name": "Warehouse 1",
                }
            ],
            9: [
                {
                    "batch_id": 9001,
                    "inventory_id": 9,
                    "item_id": 101,
                    "batch_no": "B-9001",
                    "batch_date": date(2026, 3, 25),
                    "expiry_date": None,
                    "usable_qty": Decimal("3.0000"),
                    "reserved_qty": Decimal("0.0000"),
                    "available_qty": Decimal("3.0000"),
                    "uom_code": "EA",
                    "source_type": "ON_HAND",
                    "source_record_id": None,
                    "warehouse_name": "Warehouse 9",
                }
            ],
        }
        fetch_candidates_mock.side_effect = (
            lambda warehouse_id, _item_id, as_of_date=None: list(
                warehouse_candidates.get(warehouse_id, [])
            )
        )

        contract_services._save_package_allocation(
            70,
            payload={
                "allocations": [
                    {
                        "item_id": 101,
                        "inventory_id": 9,
                        "batch_id": 9001,
                        "quantity": "2.0000",
                        "uom_code": "EA",
                    }
                ],
                "override_reason_code": "FEFO_BYPASS",
                "override_note": "Need to allocate from the downstream warehouse first.",
            },
            actor_id="officer-1",
            actor_roles=[ROLE_LOGISTICS_OFFICER],
            actor_permissions=[PERM_OPERATIONS_PACKAGE_OVERRIDE_REQUEST],
            tenant_context=None,
            allow_pending_override=True,
        )

        self.assertEqual(
            compat_commit_mock.call_args.kwargs["override_markers"],
            ["allocation_order_override"],
        )
        self.assertFalse(compat_commit_mock.call_args.kwargs["manager_direct_commit"])

    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._current_package_for_request")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service.save_package")
    def test_package_commit_reuses_cached_response_for_same_idempotency_key(
        self,
        save_package_mock,
        load_request_mock,
        current_package_mock,
        get_agency_scope_mock,
    ) -> None:
        load_request_mock.return_value = self.fulfillment_request
        current_package_mock.return_value = self.package
        save_package_mock.return_value = {"status": "COMMITTED", "reliefpkg_id": 90}
        get_agency_scope_mock.return_value = self.agency_scope

        with self.captureOnCommitCallbacks(execute=True):
            first = contract_services.save_package(
                70,
                payload={"allocations": [{"item_id": 101, "inventory_id": 4, "batch_id": 1001, "quantity": "2"}]},
                actor_id="logistics-manager-1",
                actor_roles=self.dispatch_roles,
                tenant_context=self.dispatch_ready_context,
                idempotency_key="commit-70",
            )
        queue_assignment_count = OperationsQueueAssignment.objects.filter(
            queue_code=QUEUE_CODE_DISPATCH,
            entity_id=90,
        ).count()
        second = contract_services.save_package(
            70,
            payload={"allocations": [{"item_id": 101, "inventory_id": 4, "batch_id": 1001, "quantity": "2"}]},
            actor_id="logistics-manager-1",
            actor_roles=self.dispatch_roles,
            tenant_context=self.dispatch_ready_context,
            idempotency_key="commit-70",
        )

        self.assertEqual(first, second)
        self.assertEqual(save_package_mock.call_count, 1)
        self.assertEqual(load_request_mock.call_count, 2)
        self.assertGreater(queue_assignment_count, 0)
        self.assertEqual(
            OperationsQueueAssignment.objects.filter(queue_code=QUEUE_CODE_DISPATCH, entity_id=90).count(),
            queue_assignment_count,
        )

    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._current_package_for_request")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service.save_package")
    @override_settings(ODPEM_TENANT_ID=27)
    def test_save_package_routes_override_requests_into_odpem_fulfillment_scope(
        self,
        save_package_mock,
        load_request_mock,
        current_package_mock,
        get_agency_scope_mock,
    ) -> None:
        request = self._request_stub(
            reliefrqst_id=95009,
            agency_id=501,
            status_code=contract_services.legacy_service.STATUS_SUBMITTED,
        )
        package = self._package_stub(reliefpkg_id=91, reliefrqst_id=95009, agency_id=501)
        load_request_mock.return_value = request
        current_package_mock.return_value = package
        save_package_mock.return_value = {"status": "PENDING_OVERRIDE_APPROVAL", "reliefpkg_id": 91}
        get_agency_scope_mock.return_value = self._agency_scope_for(501, 19, "JRC")
        OperationsReliefRequest.objects.create(
            relief_request_id=95009,
            request_no="RQ95009",
            requesting_tenant_id=19,
            requesting_agency_id=401,
            beneficiary_tenant_id=19,
            beneficiary_agency_id=501,
            origin_mode="SELF",
            event_id=12,
            request_date=date(2026, 3, 26),
            urgency_code="H",
            status_code=REQUEST_STATUS_APPROVED_FOR_FULFILLMENT,
            create_by_id="tester",
            update_by_id="tester",
        )
        OperationsQueueAssignment.objects.create(
            queue_code=QUEUE_CODE_FULFILLMENT,
            entity_type="RELIEF_REQUEST",
            entity_id=95009,
            assigned_role_code=ROLE_LOGISTICS_OFFICER,
            assigned_tenant_id=27,
            assignment_status="OPEN",
        )

        contract_services.save_package(
            95009,
            payload={"allocations": [{"item_id": 101, "inventory_id": 4, "batch_id": 1001, "quantity": "2"}]},
            actor_id="devon_tst",
            actor_roles=[ROLE_LOGISTICS_OFFICER],
            tenant_context=self.odpem_context,
            permissions=[PERM_OPERATIONS_PACKAGE_OVERRIDE_REQUEST],
        )

        override_assignment = OperationsQueueAssignment.objects.get(
            queue_code=QUEUE_CODE_OVERRIDE,
            entity_type="RELIEF_REQUEST",
            entity_id=95009,
            assigned_role_code=ROLE_LOGISTICS_MANAGER,
        )
        self.assertEqual(override_assignment.assigned_tenant_id, 27)
        override_notification = OperationsNotification.objects.get(
            queue_code=QUEUE_CODE_OVERRIDE,
            entity_type="RELIEF_REQUEST",
            entity_id=95009,
            recipient_role_code=ROLE_LOGISTICS_MANAGER,
        )
        self.assertEqual(override_notification.recipient_tenant_id, 27)

    def _create_operations_package_record(
        self,
        *,
        request_record: OperationsReliefRequest,
        package_id: int = 90,
        status_code: str = PACKAGE_STATUS_COMMITTED,
    ) -> OperationsPackage:
        return OperationsPackage.objects.create(
            package_id=package_id,
            package_no=f"PK{package_id:05d}",
            relief_request=request_record,
            source_warehouse_id=4,
            destination_tenant_id=request_record.beneficiary_tenant_id,
            destination_agency_id=request_record.beneficiary_agency_id,
            status_code=status_code,
            create_by_id="tester",
            update_by_id="tester",
        )

    @patch("operations.contract_services.beneficiary_parish_code_for_request", return_value="01")
    @patch("operations.contract_services.recommend_staging_hub")
    @patch("operations.contract_services._sync_operations_request")
    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.get_staging_hub_details")
    @patch("operations.contract_services.legacy_service._current_package_for_request")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service.save_package")
    def test_staged_package_commit_creates_consolidation_legs_and_skips_final_dispatch(
        self,
        save_package_mock,
        load_request_mock,
        current_package_mock,
        get_staging_hub_details_mock,
        get_agency_scope_mock,
        sync_operations_request_mock,
        recommend_staging_hub_mock,
        _beneficiary_parish_code_mock,
    ) -> None:
        request_record = self._create_operations_request_record()
        load_request_mock.return_value = self.fulfillment_request
        current_package_mock.return_value = self.package
        save_package_mock.return_value = {"status": "COMMITTED", "reliefpkg_id": 90}
        get_agency_scope_mock.return_value = self.agency_scope
        sync_operations_request_mock.return_value = request_record
        recommend_staging_hub_mock.return_value = SimpleNamespace(
            recommended_staging_warehouse_id=55,
            staging_selection_basis="SAME_PARISH",
            recommended_staging_warehouse_name="ODPEM Hub 55",
            recommended_staging_parish_code="01",
        )
        get_staging_hub_details_mock.return_value = {
            "warehouse_id": 55,
            "warehouse_name": "ODPEM Hub 55",
            "parish_code": "01",
        }

        contract_services.save_package(
            70,
            payload={
                "fulfillment_mode": FULFILLMENT_MODE_DELIVER_FROM_STAGING,
                "staging_warehouse_id": 55,
                "allocations": [
                    {"item_id": 101, "inventory_id": 4, "batch_id": 1001, "quantity": "2"},
                    {"item_id": 102, "inventory_id": 9, "batch_id": 1002, "quantity": "1"},
                ],
            },
            actor_id="logistics-manager-1",
            actor_roles=self.dispatch_roles,
            tenant_context=self.dispatch_ready_context,
            permissions=[PERM_OPERATIONS_FULFILLMENT_MODE_SET],
        )

        package_record = OperationsPackage.objects.get(package_id=90)
        self.assertEqual(package_record.status_code, PACKAGE_STATUS_CONSOLIDATING)
        self.assertEqual(package_record.fulfillment_mode, FULFILLMENT_MODE_DELIVER_FROM_STAGING)
        self.assertEqual(package_record.staging_warehouse_id, 55)
        self.assertEqual(package_record.consolidation_status, CONSOLIDATION_STATUS_AWAITING_LEGS)
        self.assertFalse(OperationsDispatch.objects.filter(package_id=90).exists())
        self.assertEqual(OperationsConsolidationLeg.objects.filter(package_id=90).count(), 2)
        self.assertEqual(
            OperationsQueueAssignment.objects.filter(
                queue_code=QUEUE_CODE_CONSOLIDATION_DISPATCH,
            entity_type="CONSOLIDATION_LEG",
        ).count(),
        6,
        )
        self.assertEqual(
            set(
                OperationsQueueAssignment.objects.filter(
                    queue_code=QUEUE_CODE_CONSOLIDATION_DISPATCH,
                    entity_type="CONSOLIDATION_LEG",
                ).values_list("assigned_tenant_id", flat=True)
            ),
            {20},
        )

    @patch("operations.contract_services.beneficiary_parish_code_for_request", return_value="01")
    @patch("operations.contract_services.recommend_staging_hub")
    @patch("operations.contract_services._sync_operations_request")
    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.get_staging_hub_details")
    @patch("operations.contract_services.legacy_service._current_package_for_request")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service.save_package")
    def test_staged_package_commit_skips_same_warehouse_consolidation_leg(
        self,
        save_package_mock,
        load_request_mock,
        current_package_mock,
        get_staging_hub_details_mock,
        get_agency_scope_mock,
        sync_operations_request_mock,
        recommend_staging_hub_mock,
        _beneficiary_parish_code_mock,
    ) -> None:
        request_record = self._create_operations_request_record()
        load_request_mock.return_value = self.fulfillment_request
        current_package_mock.return_value = self.package
        save_package_mock.return_value = {"status": "COMMITTED", "reliefpkg_id": 90}
        get_agency_scope_mock.return_value = self.agency_scope
        sync_operations_request_mock.return_value = request_record
        recommend_staging_hub_mock.return_value = SimpleNamespace(
            recommended_staging_warehouse_id=55,
            staging_selection_basis="SAME_PARISH",
            recommended_staging_warehouse_name="ODPEM Hub 55",
            recommended_staging_parish_code="01",
        )
        get_staging_hub_details_mock.return_value = {
            "warehouse_id": 55,
            "warehouse_name": "ODPEM Hub 55",
            "parish_code": "01",
        }

        contract_services.save_package(
            70,
            payload={
                "fulfillment_mode": FULFILLMENT_MODE_DELIVER_FROM_STAGING,
                "staging_warehouse_id": 55,
                "allocations": [
                    {"item_id": 101, "inventory_id": 55, "batch_id": 1001, "quantity": "2"},
                    {"item_id": 102, "inventory_id": 9, "batch_id": 1002, "quantity": "1"},
                ],
            },
            actor_id="logistics-manager-1",
            actor_roles=self.dispatch_roles,
            tenant_context=self.dispatch_ready_context,
            permissions=[PERM_OPERATIONS_FULFILLMENT_MODE_SET],
        )

        package_record = OperationsPackage.objects.get(package_id=90)
        self.assertEqual(package_record.status_code, PACKAGE_STATUS_CONSOLIDATING)
        self.assertEqual(
            list(
                OperationsConsolidationLeg.objects.filter(package_id=90)
                .order_by("leg_sequence")
                .values_list("source_warehouse_id", flat=True)
            ),
            [9],
        )
        self.assertFalse(
            OperationsConsolidationLeg.objects.filter(package_id=90, source_warehouse_id=55).exists()
        )
        self.assertEqual(
            OperationsQueueAssignment.objects.filter(
                queue_code=QUEUE_CODE_CONSOLIDATION_DISPATCH,
                entity_type="CONSOLIDATION_LEG",
            ).count(),
            3,
        )

    def test_create_consolidation_legs_retires_open_queue_assignments_before_rebuild(self) -> None:
        request_record = self._create_operations_request_record()
        package_record = OperationsPackage.objects.create(
            package_id=190,
            package_no="PK00190",
            relief_request=request_record,
            source_warehouse_id=4,
            staging_warehouse_id=55,
            fulfillment_mode=FULFILLMENT_MODE_DELIVER_FROM_STAGING,
            status_code=PACKAGE_STATUS_CONSOLIDATING,
            consolidation_status=CONSOLIDATION_STATUS_AWAITING_LEGS,
            create_by_id="tester",
            update_by_id="tester",
        )
        OperationsAllocationLine.objects.create(
            package=package_record,
            item_id=101,
            source_warehouse_id=4,
            batch_id=1001,
            quantity=Decimal("2.0000"),
            source_type="ON_HAND",
            create_by_id="tester",
            update_by_id="tester",
        )
        OperationsAllocationLine.objects.create(
            package=package_record,
            item_id=102,
            source_warehouse_id=9,
            batch_id=1002,
            quantity=Decimal("1.0000"),
            source_type="ON_HAND",
            create_by_id="tester",
            update_by_id="tester",
        )
        existing_leg = OperationsConsolidationLeg.objects.create(
            package=package_record,
            leg_sequence=1,
            source_warehouse_id=4,
            staging_warehouse_id=55,
            status_code=CONSOLIDATION_LEG_STATUS_PLANNED,
            create_by_id="tester",
            update_by_id="tester",
        )
        OperationsConsolidationLegItem.objects.create(
            leg=existing_leg,
            item_id=101,
            batch_id=1001,
            quantity="2",
            source_type="ON_HAND",
            create_by_id="tester",
            update_by_id="tester",
        )
        dispatch_assignment = OperationsQueueAssignment.objects.create(
            queue_code=QUEUE_CODE_CONSOLIDATION_DISPATCH,
            entity_type="CONSOLIDATION_LEG",
            entity_id=int(existing_leg.leg_id),
            assigned_role_code=ROLE_LOGISTICS_MANAGER,
            assigned_tenant_id=20,
            assignment_status="OPEN",
        )
        receipt_assignment = OperationsQueueAssignment.objects.create(
            queue_code=QUEUE_CODE_STAGING_RECEIPT,
            entity_type="CONSOLIDATION_LEG",
            entity_id=int(existing_leg.leg_id),
            assigned_role_code=ROLE_LOGISTICS_OFFICER,
            assigned_tenant_id=20,
            assignment_status="OPEN",
        )

        created_legs = contract_services._create_consolidation_legs(
            package_record=package_record,
            actor_id="tester",
        )

        self.assertEqual([leg.source_warehouse_id for leg in created_legs], [4, 9])
        self.assertFalse(
            OperationsConsolidationLeg.objects.filter(leg_id=int(existing_leg.leg_id)).exists()
        )
        dispatch_assignment.refresh_from_db()
        receipt_assignment.refresh_from_db()
        self.assertEqual(dispatch_assignment.assignment_status, "CANCELLED")
        self.assertEqual(receipt_assignment.assignment_status, "CANCELLED")

    @patch("operations.contract_services.beneficiary_parish_code_for_request", return_value="01")
    @patch("operations.contract_services.recommend_staging_hub")
    @patch("operations.contract_services._sync_operations_request")
    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.get_staging_hub_details")
    @patch("operations.contract_services.legacy_service._current_package_for_request")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service.save_package")
    def test_staged_package_commit_routes_directly_when_all_allocations_are_already_at_staging(
        self,
        save_package_mock,
        load_request_mock,
        current_package_mock,
        get_staging_hub_details_mock,
        get_agency_scope_mock,
        sync_operations_request_mock,
        recommend_staging_hub_mock,
        _beneficiary_parish_code_mock,
    ) -> None:
        request_record = self._create_operations_request_record()
        load_request_mock.return_value = self.fulfillment_request
        current_package_mock.return_value = self.package
        save_package_mock.return_value = {"status": "COMMITTED", "reliefpkg_id": 90}
        get_agency_scope_mock.return_value = self.agency_scope
        sync_operations_request_mock.return_value = request_record
        recommend_staging_hub_mock.return_value = SimpleNamespace(
            recommended_staging_warehouse_id=55,
            staging_selection_basis="SAME_PARISH",
            recommended_staging_warehouse_name="ODPEM Hub 55",
            recommended_staging_parish_code="01",
        )
        get_staging_hub_details_mock.return_value = {
            "warehouse_id": 55,
            "warehouse_name": "ODPEM Hub 55",
            "parish_code": "01",
        }

        contract_services.save_package(
            70,
            payload={
                "fulfillment_mode": FULFILLMENT_MODE_DELIVER_FROM_STAGING,
                "staging_warehouse_id": 55,
                "allocations": [
                    {"item_id": 101, "inventory_id": 55, "batch_id": 1001, "quantity": "2"},
                    {"item_id": 102, "inventory_id": 55, "batch_id": 1002, "quantity": "1"},
                ],
            },
            actor_id="logistics-manager-1",
            actor_roles=self.dispatch_roles,
            tenant_context=self.dispatch_ready_context,
            permissions=[PERM_OPERATIONS_FULFILLMENT_MODE_SET],
        )

        package_record = OperationsPackage.objects.get(package_id=90)
        self.assertEqual(package_record.status_code, "READY_FOR_DISPATCH")
        self.assertEqual(package_record.source_warehouse_id, 55)
        self.assertEqual(package_record.consolidation_status, CONSOLIDATION_STATUS_ALL_RECEIVED)
        self.assertFalse(OperationsConsolidationLeg.objects.filter(package_id=90).exists())
        self.assertTrue(OperationsDispatch.objects.filter(package_id=90).exists())
        self.assertEqual(
            OperationsQueueAssignment.objects.filter(
                queue_code=QUEUE_CODE_DISPATCH,
                entity_type="PACKAGE",
                entity_id=90,
            ).count(),
            3,
        )
        self.assertFalse(
            OperationsQueueAssignment.objects.filter(
                queue_code=QUEUE_CODE_CONSOLIDATION_DISPATCH,
                entity_type="CONSOLIDATION_LEG",
            ).exists()
        )

    def test_update_package_consolidation_status_preserves_partial_release_requested(self) -> None:
        request_record = self._create_operations_request_record(relief_request_id=82)
        package_record = OperationsPackage.objects.create(
            package_id=182,
            package_no="PK00182",
            relief_request=request_record,
            source_warehouse_id=4,
            staging_warehouse_id=55,
            fulfillment_mode=FULFILLMENT_MODE_DELIVER_FROM_STAGING,
            status_code=PACKAGE_STATUS_CONSOLIDATING,
            consolidation_status=CONSOLIDATION_STATUS_PARTIAL_RELEASE_REQUESTED,
            create_by_id="tester",
            update_by_id="tester",
        )
        OperationsConsolidationLeg.objects.create(
            package=package_record,
            leg_sequence=1,
            source_warehouse_id=4,
            staging_warehouse_id=55,
            status_code=CONSOLIDATION_LEG_STATUS_IN_TRANSIT,
            create_by_id="tester",
            update_by_id="tester",
        )
        OperationsConsolidationLeg.objects.create(
            package=package_record,
            leg_sequence=2,
            source_warehouse_id=9,
            staging_warehouse_id=55,
            status_code=contract_services.CONSOLIDATION_LEG_STATUS_RECEIVED_AT_STAGING,
            create_by_id="tester",
            update_by_id="tester",
        )

        result = contract_services._update_package_consolidation_status(
            package_record=package_record,
            actor_id="tester",
        )

        package_record.refresh_from_db()
        self.assertEqual(result, CONSOLIDATION_STATUS_PARTIAL_RELEASE_REQUESTED)
        self.assertEqual(
            package_record.consolidation_status,
            CONSOLIDATION_STATUS_PARTIAL_RELEASE_REQUESTED,
        )

    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.get_package", return_value={"package": {"reliefpkg_id": 90}})
    @patch("operations.contract_services.legacy_service._current_package_for_request")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service.save_package")
    def test_staged_package_draft_save_allows_blank_staging_hub(
        self,
        save_package_mock,
        load_request_mock,
        current_package_mock,
        _get_package_mock,
        get_agency_scope_mock,
    ) -> None:
        request_record = self._create_operations_request_record()
        load_request_mock.return_value = self.fulfillment_request
        current_package_mock.return_value = self.package
        save_package_mock.return_value = {"status": "DRAFT", "reliefpkg_id": 90}
        get_agency_scope_mock.return_value = self.agency_scope

        with patch("operations.contract_services._sync_operations_request", return_value=request_record):
            contract_services.save_package(
                70,
                payload={
                    "draft_save": True,
                    "fulfillment_mode": FULFILLMENT_MODE_DELIVER_FROM_STAGING,
                    "staging_warehouse_id": None,
                },
                actor_id="logistics-manager-1",
                actor_roles=self.dispatch_roles,
                tenant_context=self.dispatch_ready_context,
                permissions=[PERM_OPERATIONS_FULFILLMENT_MODE_SET],
            )

        package_record = OperationsPackage.objects.get(package_id=90)
        self.assertEqual(package_record.fulfillment_mode, FULFILLMENT_MODE_DELIVER_FROM_STAGING)
        self.assertIsNone(package_record.staging_warehouse_id)
        save_package_mock.assert_called_once()

    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._current_package_for_request")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service.save_package")
    def test_staged_package_commit_requires_selected_staging_hub(
        self,
        save_package_mock,
        load_request_mock,
        current_package_mock,
        get_agency_scope_mock,
    ) -> None:
        load_request_mock.return_value = self.fulfillment_request
        current_package_mock.return_value = self.package
        get_agency_scope_mock.return_value = self.agency_scope

        with self.assertRaises(OperationValidationError) as raised:
            contract_services.save_package(
                70,
                payload={
                    "fulfillment_mode": FULFILLMENT_MODE_DELIVER_FROM_STAGING,
                    "staging_warehouse_id": None,
                    "allocations": [
                        {"item_id": 101, "inventory_id": 4, "batch_id": 1001, "quantity": "2"},
                    ],
                },
                actor_id="logistics-manager-1",
                actor_roles=self.dispatch_roles,
                tenant_context=self.dispatch_ready_context,
                permissions=[PERM_OPERATIONS_FULFILLMENT_MODE_SET],
            )

        self.assertEqual(
            raised.exception.errors["staging_warehouse_id"],
            "A staging warehouse is required before staged fulfillment can be committed.",
        )
        save_package_mock.assert_not_called()

    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._current_package_for_request")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service.save_package")
    def test_staged_package_commit_rejects_invalid_staging_hub_before_legacy_save(
        self,
        save_package_mock,
        load_request_mock,
        current_package_mock,
        get_agency_scope_mock,
    ) -> None:
        load_request_mock.return_value = self.fulfillment_request
        current_package_mock.return_value = self.package
        get_agency_scope_mock.return_value = self.agency_scope

        with patch("operations.contract_services.get_staging_hub_details", return_value=None):
            with self.assertRaises(OperationValidationError) as raised:
                contract_services.save_package(
                    70,
                    payload={
                        "fulfillment_mode": FULFILLMENT_MODE_DELIVER_FROM_STAGING,
                        "staging_warehouse_id": 999,
                        "staging_override_reason": "Closer road access",
                        "allocations": [
                            {"item_id": 101, "inventory_id": 4, "batch_id": 1001, "quantity": "2"},
                        ],
                    },
                    actor_id="logistics-manager-1",
                    actor_roles=self.dispatch_roles,
                    tenant_context=self.dispatch_ready_context,
                    permissions=[
                        PERM_OPERATIONS_FULFILLMENT_MODE_SET,
                        PERM_OPERATIONS_STAGING_WAREHOUSE_OVERRIDE,
                    ],
                )

        self.assertIn("staging_warehouse_id", raised.exception.errors)
        save_package_mock.assert_not_called()

    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._current_package_for_request")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service.save_package")
    def test_staged_package_commit_requires_fulfillment_mode_permission(
        self,
        save_package_mock,
        load_request_mock,
        current_package_mock,
        get_agency_scope_mock,
    ) -> None:
        load_request_mock.return_value = self.fulfillment_request
        current_package_mock.return_value = self.package
        get_agency_scope_mock.return_value = self.agency_scope

        with patch(
            "operations.contract_services.get_staging_hub_details",
            return_value={"warehouse_id": 55, "warehouse_name": "ODPEM Hub 55", "parish_code": "01"},
        ):
            with self.assertRaises(OperationValidationError) as raised:
                contract_services.save_package(
                    70,
                    payload={
                        "fulfillment_mode": FULFILLMENT_MODE_DELIVER_FROM_STAGING,
                        "staging_warehouse_id": 55,
                        "allocations": [
                            {"item_id": 101, "inventory_id": 4, "batch_id": 1001, "quantity": "2"},
                        ],
                    },
                    actor_id="logistics-manager-1",
                    actor_roles=self.dispatch_roles,
                    tenant_context=self.dispatch_ready_context,
                    permissions=[PERM_OPERATIONS_REQUEST_CREATE_SELF],
                )

        self.assertEqual(raised.exception.errors["fulfillment_mode"]["required_permission"], PERM_OPERATIONS_FULFILLMENT_MODE_SET)
        save_package_mock.assert_not_called()

    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._current_package_for_request")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service.save_package")
    def test_staged_package_commit_accepts_operator_selected_hub_without_recommendation_override(
        self,
        save_package_mock,
        load_request_mock,
        current_package_mock,
        get_agency_scope_mock,
    ) -> None:
        request_record = self._create_operations_request_record()
        load_request_mock.return_value = self.fulfillment_request
        current_package_mock.return_value = self.package
        save_package_mock.return_value = {"status": "COMMITTED", "reliefpkg_id": 90}
        get_agency_scope_mock.return_value = self.agency_scope

        with patch("operations.contract_services._sync_operations_request", return_value=request_record):
            with patch(
                "operations.contract_services.get_staging_hub_details",
                return_value={"warehouse_id": 77, "warehouse_name": "ODPEM Hub 77", "parish_code": "02"},
            ):
                contract_services.save_package(
                    70,
                    payload={
                        "fulfillment_mode": FULFILLMENT_MODE_DELIVER_FROM_STAGING,
                        "staging_warehouse_id": 77,
                        "allocations": [
                            {"item_id": 101, "inventory_id": 4, "batch_id": 1001, "quantity": "2"},
                        ],
                    },
                    actor_id="logistics-manager-1",
                    actor_roles=self.dispatch_roles,
                    tenant_context=self.dispatch_ready_context,
                    permissions=[PERM_OPERATIONS_FULFILLMENT_MODE_SET],
                )

        package_record = OperationsPackage.objects.get(package_id=90)
        self.assertEqual(package_record.staging_warehouse_id, 77)
        save_package_mock.assert_called_once()

    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services._request_fully_dispatched", return_value=True)
    @patch("operations.contract_services.legacy_service._current_package_for_request")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service.save_package")
    def test_save_package_rejects_when_all_items_already_fully_issued(
        self,
        save_package_mock,
        load_request_mock,
        current_package_mock,
        _request_fully_dispatched_mock,
        get_agency_scope_mock,
    ) -> None:
        """Regression guard for PK95025-style empty drafts.

        Even when legacy ``reliefrqst.status_code`` has drifted to PART_FILLED
        (because an upstream write path failed to flip it to FILLED after the
        prior package dispatched every item), the contract service must refuse
        to create or mutate another package: there is nothing left to allocate.
        """
        load_request_mock.return_value = self.fulfillment_request
        current_package_mock.return_value = self._package_stub(
            reliefpkg_id=90,
            reliefrqst_id=70,
            agency_id=501,
            status_code="D",
            dispatch_dtime=datetime(2026, 3, 24, 16, 28, 14),
        )
        get_agency_scope_mock.return_value = self.agency_scope

        with self.assertRaises(OperationValidationError) as raised:
            contract_services.save_package(
                70,
                payload={
                    "allocations": [
                        {"item_id": 101, "inventory_id": 4, "batch_id": 1001, "quantity": "2"},
                    ],
                },
                actor_id="logistics-manager-1",
                actor_roles=self.dispatch_roles,
                tenant_context=self.dispatch_ready_context,
            )

        self.assertIn("request", raised.exception.errors)
        self.assertIn("already fully issued", raised.exception.errors["request"])
        save_package_mock.assert_not_called()

    def test_sync_package_preserves_operations_only_statuses_when_legacy_is_still_pending(self) -> None:
        request_record = self._create_operations_request_record()
        for index, status_code in enumerate(
            (
                PACKAGE_STATUS_CONSOLIDATING,
                PACKAGE_STATUS_READY_FOR_PICKUP,
                PACKAGE_STATUS_SPLIT,
                PACKAGE_STATUS_CANCELLED,
            ),
            start=1,
        ):
            with self.subTest(status_code=status_code):
                package_record = OperationsPackage.objects.create(
                    package_id=900 + index,
                    package_no=f"PK{900 + index:05d}",
                    relief_request=request_record,
                    source_warehouse_id=4,
                    staging_warehouse_id=55,
                    fulfillment_mode=FULFILLMENT_MODE_PICKUP_AT_STAGING,
                    status_code=status_code,
                    create_by_id="tester",
                    update_by_id="tester",
                )
                synced = contract_services._sync_operations_package(
                    self._package_stub(
                        reliefpkg_id=900 + index,
                        reliefrqst_id=70,
                        agency_id=501,
                        status_code="P",
                    ),
                    request_record=request_record,
                    actor_id="tester",
                )
                self.assertEqual(synced.status_code, status_code)
                package_record.delete()

    @patch("operations.contract_services._receive_leg_stock_into_staging")
    @patch("operations.contract_services._package_context_by_package_id")
    def test_receive_consolidation_leg_assigns_pickup_release_to_role_queue(
        self,
        package_context_mock,
        _receive_stock_mock,
    ) -> None:
        request_record = self._create_operations_request_record()
        request_record.submitted_by_id = "requester-1"
        request_record.save(update_fields=["submitted_by_id"])
        package_record = OperationsPackage.objects.create(
            package_id=190,
            package_no="PK00190",
            relief_request=request_record,
            source_warehouse_id=4,
            staging_warehouse_id=55,
            fulfillment_mode=FULFILLMENT_MODE_PICKUP_AT_STAGING,
            status_code=PACKAGE_STATUS_CONSOLIDATING,
            create_by_id="tester",
            update_by_id="tester",
        )
        leg = OperationsConsolidationLeg.objects.create(
            package=package_record,
            leg_sequence=1,
            source_warehouse_id=4,
            staging_warehouse_id=55,
            status_code=CONSOLIDATION_LEG_STATUS_IN_TRANSIT,
            create_by_id="tester",
            update_by_id="tester",
        )
        OperationsQueueAssignment.objects.create(
            queue_code=QUEUE_CODE_STAGING_RECEIPT,
            entity_type="CONSOLIDATION_LEG",
            entity_id=int(leg.leg_id),
            assigned_role_code="LOGISTICS_MANAGER",
            assigned_tenant_id=20,
            assignment_status="OPEN",
        )
        package = self._package_stub(reliefpkg_id=190, reliefrqst_id=70, agency_id=501, status_code="P")
        request = self._request_stub(reliefrqst_id=70, agency_id=501, status_code=contract_services.legacy_service.STATUS_SUBMITTED)
        package_context_mock.return_value = (package, request, request_record, package_record)

        def _sync_side_effect(*args, **kwargs):
            if "status_code" in kwargs and kwargs["status_code"]:
                package_record.status_code = kwargs["status_code"]
                package_record.save(update_fields=["status_code"])
            return package_record

        with patch("operations.contract_services._sync_operations_package", side_effect=_sync_side_effect):
            result = contract_services.receive_consolidation_leg(
                190,
                int(leg.leg_id),
                payload={"received_by_name": "Receiver"},
                actor_id="logistics-manager-1",
                actor_roles=self.dispatch_roles,
                tenant_context=self.dispatch_ready_context,
                idempotency_key="receive-leg-190",
            )

        self.assertEqual(result["package"]["status_code"], PACKAGE_STATUS_READY_FOR_PICKUP)
        self.assertEqual(
            set(
                OperationsQueueAssignment.objects.filter(
                    queue_code=QUEUE_CODE_PICKUP_RELEASE,
                    entity_type="PACKAGE",
                    entity_id=int(package_record.package_id),
                ).values_list("assigned_role_code", flat=True)
            ),
            {ROLE_LOGISTICS_OFFICER, ROLE_LOGISTICS_MANAGER},
        )
        self.assertFalse(
            OperationsQueueAssignment.objects.filter(
                queue_code=QUEUE_CODE_PICKUP_RELEASE,
                entity_type="PACKAGE",
                entity_id=int(package_record.package_id),
                assigned_role_code=ROLE_INVENTORY_CLERK,
            ).exists()
        )

    @patch("operations.contract_services._create_consolidation_waybill")
    @patch("operations.contract_services.legacy_service._apply_stock_delta_for_rows")
    @patch("operations.contract_services._create_leg_shadow_transfer", return_value=701)
    @patch("operations.contract_services._package_context_by_package_id")
    def test_dispatch_consolidation_leg_assigns_staging_receipt_to_logistics_roles_only(
        self,
        package_context_mock,
        _create_shadow_transfer_mock,
        _apply_stock_delta_mock,
        _create_waybill_mock,
    ) -> None:
        request_record = self._create_operations_request_record()
        package_record = OperationsPackage.objects.create(
            package_id=191,
            package_no="PK00191",
            relief_request=request_record,
            source_warehouse_id=4,
            staging_warehouse_id=55,
            fulfillment_mode=FULFILLMENT_MODE_DELIVER_FROM_STAGING,
            status_code=PACKAGE_STATUS_CONSOLIDATING,
            create_by_id="tester",
            update_by_id="tester",
        )
        leg = OperationsConsolidationLeg.objects.create(
            package=package_record,
            leg_sequence=1,
            source_warehouse_id=4,
            staging_warehouse_id=55,
            status_code=CONSOLIDATION_LEG_STATUS_PLANNED,
            create_by_id="tester",
            update_by_id="tester",
        )
        OperationsConsolidationLegItem.objects.create(
            leg=leg,
            item_id=101,
            batch_id=1001,
            quantity="2",
            source_type="ON_HAND",
            uom_code="EA",
            create_by_id="tester",
            update_by_id="tester",
        )
        OperationsQueueAssignment.objects.create(
            queue_code=QUEUE_CODE_CONSOLIDATION_DISPATCH,
            entity_type="CONSOLIDATION_LEG",
            entity_id=int(leg.leg_id),
            assigned_role_code=ROLE_LOGISTICS_MANAGER,
            assigned_tenant_id=20,
            assignment_status="OPEN",
        )
        package_context_mock.return_value = (
            self._package_stub(reliefpkg_id=191, reliefrqst_id=70, agency_id=501, status_code="P"),
            self._request_stub(
                reliefrqst_id=70,
                agency_id=501,
                status_code=contract_services.legacy_service.STATUS_SUBMITTED,
            ),
            request_record,
            package_record,
        )

        result = contract_services.dispatch_consolidation_leg(
            191,
            int(leg.leg_id),
            payload={
                "driver_name": "Jane Driver",
                "driver_license_no": "DL123456789",
                "vehicle_registration": "1234AB",
                "departure_dtime": "2026-03-26T09:00:00Z",
                "estimated_arrival_dtime": "2026-03-26T10:00:00Z",
            },
            actor_id="logistics-manager-1",
            actor_roles=self.dispatch_roles,
            tenant_context=self.dispatch_ready_context,
            idempotency_key="dispatch-leg-191",
        )

        self.assertEqual(result["status"], CONSOLIDATION_LEG_STATUS_IN_TRANSIT)
        leg.refresh_from_db()
        self.assertEqual(leg.driver_license_last4, "6789")
        self.assertEqual(result["leg"]["driver_license_last4"], "6789")
        self.assertEqual(
            set(
                OperationsQueueAssignment.objects.filter(
                    queue_code=QUEUE_CODE_STAGING_RECEIPT,
                    entity_type="CONSOLIDATION_LEG",
                    entity_id=int(leg.leg_id),
                ).values_list("assigned_role_code", flat=True)
            ),
            {ROLE_LOGISTICS_OFFICER, ROLE_LOGISTICS_MANAGER},
        )
        self.assertFalse(
            OperationsQueueAssignment.objects.filter(
                queue_code=QUEUE_CODE_STAGING_RECEIPT,
                entity_type="CONSOLIDATION_LEG",
                entity_id=int(leg.leg_id),
                assigned_role_code=ROLE_INVENTORY_CLERK,
            ).exists()
        )

    @patch("operations.contract_services._consolidation_leg_payload", return_value={"leg_id": 1})
    @patch("operations.contract_services._package_summary_payload", return_value={"reliefpkg_id": 192})
    @patch("operations.contract_services._ensure_fulfillment_request_access")
    @patch("operations.contract_services._package_context_by_package_id")
    def test_list_consolidation_legs_enforces_fulfillment_request_access(
        self,
        package_context_mock,
        ensure_fulfillment_access_mock,
        _package_summary_mock,
        _leg_payload_mock,
    ) -> None:
        request_record = self._create_operations_request_record(relief_request_id=92)
        package_record = OperationsPackage.objects.create(
            package_id=192,
            package_no="PK00192",
            relief_request=request_record,
            source_warehouse_id=4,
            staging_warehouse_id=55,
            fulfillment_mode=FULFILLMENT_MODE_DELIVER_FROM_STAGING,
            status_code=PACKAGE_STATUS_CONSOLIDATING,
            create_by_id="tester",
            update_by_id="tester",
        )
        package_context_mock.return_value = (
            self._package_stub(reliefpkg_id=192, reliefrqst_id=92, agency_id=501, status_code="P"),
            self._request_stub(reliefrqst_id=92, agency_id=501),
            request_record,
            package_record,
        )

        contract_services.list_consolidation_legs(
            192,
            actor_id="logistics-manager-1",
            actor_roles=self.dispatch_roles,
            tenant_context=self.dispatch_ready_context,
        )

        ensure_fulfillment_access_mock.assert_called_once_with(
            request_record,
            actor_id="logistics-manager-1",
            actor_roles=self.dispatch_roles,
            tenant_context=self.dispatch_ready_context,
        )

    @patch("operations.contract_services._ensure_fulfillment_request_access")
    @patch("operations.contract_services._package_context_by_package_id")
    def test_get_consolidation_leg_waybill_enforces_fulfillment_request_access(
        self,
        package_context_mock,
        ensure_fulfillment_access_mock,
    ) -> None:
        request_record = self._create_operations_request_record(relief_request_id=93)
        package_record = OperationsPackage.objects.create(
            package_id=193,
            package_no="PK00193",
            relief_request=request_record,
            source_warehouse_id=4,
            staging_warehouse_id=55,
            fulfillment_mode=FULFILLMENT_MODE_DELIVER_FROM_STAGING,
            status_code=PACKAGE_STATUS_CONSOLIDATING,
            create_by_id="tester",
            update_by_id="tester",
        )
        leg = OperationsConsolidationLeg.objects.create(
            package=package_record,
            leg_sequence=1,
            source_warehouse_id=4,
            staging_warehouse_id=55,
            status_code=CONSOLIDATION_LEG_STATUS_IN_TRANSIT,
            create_by_id="tester",
            update_by_id="tester",
        )
        contract_services.OperationsConsolidationWaybill.objects.create(
            leg=leg,
            waybill_no="LEG-WB-193",
            artifact_payload_json={"leg_id": int(leg.leg_id)},
            generated_by_id="tester",
        )
        package_context_mock.return_value = (
            self._package_stub(reliefpkg_id=193, reliefrqst_id=93, agency_id=501, status_code="P"),
            self._request_stub(reliefrqst_id=93, agency_id=501),
            request_record,
            package_record,
        )

        contract_services.get_consolidation_leg_waybill(
            193,
            int(leg.leg_id),
            actor_id="logistics-manager-1",
            actor_roles=self.dispatch_roles,
            tenant_context=self.dispatch_ready_context,
        )

        ensure_fulfillment_access_mock.assert_called_once_with(
            request_record,
            actor_id="logistics-manager-1",
            actor_roles=self.dispatch_roles,
            tenant_context=self.dispatch_ready_context,
        )

    @patch("operations.contract_services._sync_operations_request")
    @patch("operations.contract_services._request_fully_dispatched", return_value=True)
    @patch("operations.contract_services.legacy_service._apply_stock_delta_for_rows")
    @patch("operations.contract_services._package_context_by_package_id")
    def test_pickup_release_persists_enriched_contract_and_staged_allocations_when_no_legs_exist(
        self,
        package_context_mock,
        apply_stock_delta_mock,
        _request_fully_dispatched_mock,
        sync_operations_request_mock,
    ) -> None:
        request_record = self._create_operations_request_record()
        sync_operations_request_mock.return_value = request_record
        package_record = OperationsPackage.objects.create(
            package_id=192,
            package_no="PK00192",
            relief_request=request_record,
            source_warehouse_id=55,
            staging_warehouse_id=55,
            fulfillment_mode=FULFILLMENT_MODE_PICKUP_AT_STAGING,
            status_code=PACKAGE_STATUS_READY_FOR_PICKUP,
            create_by_id="tester",
            update_by_id="tester",
        )
        OperationsAllocationLine.objects.create(
            package=package_record,
            item_id=101,
            source_warehouse_id=55,
            batch_id=1001,
            quantity="2",
            source_type="ON_HAND",
            uom_code="EA",
            create_by_id="tester",
            update_by_id="tester",
        )
        OperationsQueueAssignment.objects.create(
            queue_code=QUEUE_CODE_PICKUP_RELEASE,
            entity_type="PACKAGE",
            entity_id=int(package_record.package_id),
            assigned_role_code=ROLE_LOGISTICS_MANAGER,
            assigned_tenant_id=20,
            assignment_status="OPEN",
        )
        package = self._package_stub(reliefpkg_id=192, reliefrqst_id=70, agency_id=501, status_code="P")
        request = self._request_stub(
            reliefrqst_id=70,
            agency_id=501,
            status_code=contract_services.legacy_service.STATUS_SUBMITTED,
        )
        package_context_mock.return_value = (package, request, request_record, package_record)

        result = contract_services.pickup_release(
            192,
            payload={
                "collected_by_name": "Community Driver",
                "collected_by_id_ref": "NID-7788",
                "released_by_name": "Receiver",
                "release_notes": "Pickup at gate",
                "driver_name": "Ignored",
            },
            actor_id="logistics-manager-1",
            actor_roles=self.dispatch_roles,
            tenant_context=self.dispatch_ready_context,
            idempotency_key="pickup-192",
        )

        package_record.refresh_from_db()
        pickup_release_record = OperationsPickupRelease.objects.get(package_id=192)
        self.assertEqual(result["status"], "RECEIVED")
        self.assertEqual(set(result.keys()), {"status", "package"})
        self.assertEqual(package_record.status_code, PACKAGE_STATUS_RECEIVED)
        self.assertEqual(pickup_release_record.staging_warehouse_id, 55)
        self.assertEqual(pickup_release_record.tenant_id, 20)
        self.assertEqual(pickup_release_record.collected_by_name, "Community Driver")
        self.assertEqual(pickup_release_record.collected_by_id_last4, "7788")
        self.assertEqual(pickup_release_record.released_by_name, "Receiver")
        self.assertEqual(pickup_release_record.release_notes, "Pickup at gate")
        self.assertEqual(
            pickup_release_record.release_artifact_json,
            {
                "staging_warehouse_id": 55,
                "tenant_id": 20,
                "collected_by_name": "Community Driver",
                "collected_by_id_last4": "7788",
                "released_by_user_id": "logistics-manager-1",
                "released_by_name": "Receiver",
                "released_at": pickup_release_record.released_at.isoformat(),
                "release_notes": "Pickup at gate",
            },
        )
        apply_stock_delta_mock.assert_called_once()
        self.assertEqual(
            apply_stock_delta_mock.call_args.args[0],
            [
                {
                    "item_id": 101,
                    "quantity": package_record.allocation_lines.get().quantity,
                    "inventory_id": 55,
                    "batch_id": 1001,
                    "source_type": "ON_HAND",
                }
            ],
        )

    @patch("operations.contract_services._sync_operations_request")
    @patch("operations.contract_services._request_fully_dispatched", return_value=True)
    @patch("operations.contract_services.legacy_service._apply_stock_delta_for_rows")
    @patch("operations.contract_services._package_context_by_package_id")
    def test_pickup_release_accepts_legacy_payload_without_collector_fields(
        self,
        package_context_mock,
        apply_stock_delta_mock,
        _request_fully_dispatched_mock,
        sync_operations_request_mock,
    ) -> None:
        request_record = self._create_operations_request_record(relief_request_id=71, agency_id=502)
        sync_operations_request_mock.return_value = request_record
        package_record = OperationsPackage.objects.create(
            package_id=193,
            package_no="PK00193",
            relief_request=request_record,
            source_warehouse_id=56,
            staging_warehouse_id=56,
            fulfillment_mode=FULFILLMENT_MODE_PICKUP_AT_STAGING,
            status_code=PACKAGE_STATUS_READY_FOR_PICKUP,
            create_by_id="tester",
            update_by_id="tester",
        )
        OperationsAllocationLine.objects.create(
            package=package_record,
            item_id=102,
            source_warehouse_id=56,
            batch_id=1002,
            quantity="1",
            source_type="ON_HAND",
            uom_code="EA",
            create_by_id="tester",
            update_by_id="tester",
        )
        OperationsQueueAssignment.objects.create(
            queue_code=QUEUE_CODE_PICKUP_RELEASE,
            entity_type="PACKAGE",
            entity_id=int(package_record.package_id),
            assigned_role_code=ROLE_LOGISTICS_MANAGER,
            assigned_tenant_id=20,
            assignment_status="OPEN",
        )
        package = self._package_stub(reliefpkg_id=193, reliefrqst_id=71, agency_id=502, status_code="P")
        request = self._request_stub(
            reliefrqst_id=71,
            agency_id=502,
            status_code=contract_services.legacy_service.STATUS_SUBMITTED,
        )
        package_context_mock.return_value = (package, request, request_record, package_record)

        result = contract_services.pickup_release(
            193,
            payload={
                "released_by_name": "Receiver Two",
                "release_notes": "Legacy client payload",
            },
            actor_id="logistics-manager-1",
            actor_roles=self.dispatch_roles,
            tenant_context=self.dispatch_ready_context,
            idempotency_key="pickup-193",
        )

        package_record.refresh_from_db()
        pickup_release_record = OperationsPickupRelease.objects.get(package_id=193)
        self.assertEqual(result["status"], "RECEIVED")
        self.assertEqual(package_record.status_code, PACKAGE_STATUS_RECEIVED)
        self.assertIsNone(pickup_release_record.collected_by_name)
        self.assertIsNone(pickup_release_record.collected_by_id_last4)
        self.assertEqual(pickup_release_record.staging_warehouse_id, 56)
        self.assertEqual(pickup_release_record.tenant_id, 20)
        self.assertEqual(
            pickup_release_record.release_artifact_json["collected_by_name"],
            None,
        )
        self.assertEqual(
            pickup_release_record.release_artifact_json["collected_by_id_last4"],
            None,
        )
        apply_stock_delta_mock.assert_called_once()

    @patch("operations.contract_services._package_context_by_package_id")
    def test_cancel_package_blocks_in_transit_consolidation_legs(
        self,
        package_context_mock,
    ) -> None:
        request_record = self._create_operations_request_record()
        package_record = OperationsPackage.objects.create(
            package_id=290,
            package_no="PK00290",
            relief_request=request_record,
            source_warehouse_id=4,
            staging_warehouse_id=55,
            fulfillment_mode=FULFILLMENT_MODE_DELIVER_FROM_STAGING,
            status_code=PACKAGE_STATUS_CONSOLIDATING,
            create_by_id="tester",
            update_by_id="tester",
        )
        OperationsConsolidationLeg.objects.create(
            package=package_record,
            leg_sequence=1,
            source_warehouse_id=4,
            staging_warehouse_id=55,
            status_code=CONSOLIDATION_LEG_STATUS_IN_TRANSIT,
            create_by_id="tester",
            update_by_id="tester",
        )
        package_context_mock.return_value = (
            self._package_stub(reliefpkg_id=290, reliefrqst_id=70, agency_id=501, status_code="P"),
            self._request_stub(reliefrqst_id=70, agency_id=501, status_code=contract_services.legacy_service.STATUS_SUBMITTED),
            request_record,
            package_record,
        )

        with self.assertRaises(OperationValidationError) as raised:
            contract_services.cancel_package(
                290,
                payload=None,
                actor_id="logistics-manager-1",
                actor_roles=self.dispatch_roles,
                tenant_context=self.dispatch_ready_context,
                idempotency_key="cancel-290",
            )

        self.assertEqual(
            raised.exception.errors["cancel"],
            "Packages with in-transit consolidation legs cannot be cancelled.",
        )

    @patch("operations.contract_services._package_context_by_package_id")
    @patch("operations.contract_services.legacy_service._apply_stock_delta_for_rows")
    @patch("operations.contract_services.legacy_service._selected_plan_for_package")
    @patch("operations.contract_services._request_summary_payload", return_value={"reliefrqst_id": 70})
    @patch("operations.contract_services._package_summary_payload", return_value={"reliefpkg_id": 291})
    def test_cancel_package_releases_reserved_stock_and_cancels_planned_legs(
        self,
        _package_summary_mock,
        _request_summary_mock,
        selected_plan_mock,
        apply_stock_delta_mock,
        package_context_mock,
    ) -> None:
        request_record = self._create_operations_request_record()
        package_record = OperationsPackage.objects.create(
            package_id=291,
            package_no="PK00291",
            relief_request=request_record,
            source_warehouse_id=4,
            staging_warehouse_id=55,
            fulfillment_mode=FULFILLMENT_MODE_DELIVER_FROM_STAGING,
            status_code=PACKAGE_STATUS_CONSOLIDATING,
            create_by_id="tester",
            update_by_id="tester",
        )
        leg = OperationsConsolidationLeg.objects.create(
            package=package_record,
            leg_sequence=1,
            source_warehouse_id=4,
            staging_warehouse_id=55,
            status_code=CONSOLIDATION_LEG_STATUS_PLANNED,
            create_by_id="tester",
            update_by_id="tester",
        )
        OperationsQueueAssignment.objects.create(
            queue_code=QUEUE_CODE_CONSOLIDATION_DISPATCH,
            entity_type="CONSOLIDATION_LEG",
            entity_id=int(leg.leg_id),
            assigned_role_code="LOGISTICS_MANAGER",
            assigned_tenant_id=20,
            assignment_status="OPEN",
        )
        OperationsPackageLock.objects.create(
            package=package_record,
            lock_owner_user_id="logistics-manager-1",
            lock_owner_role_code="LOGISTICS_MANAGER",
            lock_status="ACTIVE",
        )
        package = self._package_stub(reliefpkg_id=291, reliefrqst_id=70, agency_id=501, status_code="P")
        package.save = Mock()
        package_context_mock.return_value = (
            package,
            self._request_stub(reliefrqst_id=70, agency_id=501, status_code=contract_services.legacy_service.STATUS_SUBMITTED),
            request_record,
            package_record,
        )
        selected_plan_mock.return_value = [
            {"inventory_id": 4, "batch_id": 1001, "item_id": 101, "quantity": "2", "uom_code": "EA"}
        ]

        result = contract_services.cancel_package(
            291,
            payload=None,
            actor_id="logistics-manager-1",
            actor_roles=self.dispatch_roles,
            tenant_context=self.dispatch_ready_context,
            idempotency_key="cancel-291",
        )

        package_record.refresh_from_db()
        leg.refresh_from_db()
        self.assertEqual(result["status"], PACKAGE_STATUS_CANCELLED)
        self.assertEqual(package_record.status_code, PACKAGE_STATUS_CANCELLED)
        self.assertEqual(leg.status_code, CONSOLIDATION_LEG_STATUS_CANCELLED)
        apply_stock_delta_mock.assert_called_once()
        self.assertEqual(apply_stock_delta_mock.call_args.kwargs["delta_sign"], -1)
        self.assertFalse(
            OperationsQueueAssignment.objects.filter(
                queue_code=QUEUE_CODE_CONSOLIDATION_DISPATCH,
                entity_type="CONSOLIDATION_LEG",
                entity_id=int(leg.leg_id),
                assignment_status="OPEN",
            ).exists()
        )
        self.assertEqual(
            OperationsPackageLock.objects.get(package_id=int(package_record.package_id)).lock_status,
            "RELEASED",
        )

    @patch("operations.contract_services.record_status_transition")
    @patch("operations.contract_services.reset_package_allocations")
    @patch("operations.contract_services._package_context_by_package_id")
    def test_abandon_package_draft_cancels_planned_legs_and_delegates_to_reset(
        self,
        package_context_mock,
        reset_mock,
        record_transition_mock,
    ) -> None:
        """Happy-path abandon cancels planned legs for still-revertible staged packages, then delegates the reset."""
        request_record = self._create_operations_request_record(relief_request_id=92)
        package_record = OperationsPackage.objects.create(
            package_id=392,
            package_no="PK00392",
            relief_request=request_record,
            source_warehouse_id=4,
            staging_warehouse_id=55,
            fulfillment_mode=FULFILLMENT_MODE_DELIVER_FROM_STAGING,
            status_code=PACKAGE_STATUS_CONSOLIDATING,
            create_by_id="tester",
            update_by_id="tester",
        )
        planned_leg = OperationsConsolidationLeg.objects.create(
            package=package_record,
            leg_sequence=1,
            source_warehouse_id=4,
            staging_warehouse_id=55,
            status_code=CONSOLIDATION_LEG_STATUS_PLANNED,
            create_by_id="tester",
            update_by_id="tester",
        )

        package_stub = self._package_stub(
            reliefpkg_id=392,
            reliefrqst_id=92,
            agency_id=501,
            status_code="P",
        )
        request_stub = self._request_stub(
            reliefrqst_id=92,
            agency_id=501,
            status_code=contract_services.legacy_service.STATUS_SUBMITTED,
        )
        package_context_mock.return_value = (
            package_stub,
            request_stub,
            request_record,
            package_record,
        )
        reset_mock.return_value = {
            "status": PACKAGE_STATUS_DRAFT,
            "reliefrqst_id": 92,
            "reliefpkg_id": 392,
            "request_no": "RQ00092",
            "package_no": "PK00392",
            "operations_allocation_lines_deleted": 1,
            "legacy_allocation_lines_deleted": 1,
            "released_stock_summary": {"line_count": 1, "total_qty": "2.0000"},
        }

        result = contract_services.abandon_package_draft(
            392,
            payload={"reason": "  Wrong warehouse pre-selection  "},
            actor_id="logistics-manager-1",
            actor_roles=self.dispatch_roles,
            tenant_context=self.dispatch_ready_context,
            idempotency_key="abandon-392",
        )

        planned_leg.refresh_from_db()
        self.assertTrue(result["abandoned"])
        # Reason is trimmed and stored
        self.assertEqual(result["reason"], "Wrong warehouse pre-selection")
        self.assertEqual(result["previous_status_code"], PACKAGE_STATUS_CONSOLIDATING)
        self.assertEqual(result["status"], PACKAGE_STATUS_DRAFT)
        self.assertEqual(result["request_status"], REQUEST_STATUS_APPROVED_FOR_FULFILLMENT)
        # The planned leg is cancelled up-front, before reset_package_allocations runs,
        # because reset refuses to touch packages with active legs.
        self.assertEqual(planned_leg.status_code, CONSOLIDATION_LEG_STATUS_CANCELLED)
        # The actual revert (stock release, lock release, DRAFT transition) is delegated.
        reset_mock.assert_called_once_with(
            392,
            actor_id="logistics-manager-1",
            status_transition_reason="Wrong warehouse pre-selection",
        )
        # Abandon should not write a second package DRAFT transition on top of the
        # delegated reset; only the planned-leg cancellation is recorded here.
        record_transition_mock.assert_called_once_with(
            entity_type=contract_services.ENTITY_CONSOLIDATION_LEG,
            entity_id=int(planned_leg.leg_id),
            from_status=CONSOLIDATION_LEG_STATUS_PLANNED,
            to_status=CONSOLIDATION_LEG_STATUS_CANCELLED,
            actor_id="logistics-manager-1",
        )

    @patch("operations.contract_services._package_context_by_package_id")
    @patch("operations.contract_services.reset_package_allocations")
    @patch("operations.contract_services.record_status_transition")
    def test_abandon_package_draft_reuses_cached_response_for_same_idempotency_key(
        self,
        record_transition_mock,
        reset_mock,
        package_context_mock,
    ) -> None:
        request_record = self._create_operations_request_record(relief_request_id=932)
        package_record = OperationsPackage.objects.create(
            package_id=3932,
            package_no="PK03932",
            relief_request=request_record,
            source_warehouse_id=4,
            staging_warehouse_id=55,
            fulfillment_mode=FULFILLMENT_MODE_DELIVER_FROM_STAGING,
            status_code=PACKAGE_STATUS_CONSOLIDATING,
            create_by_id="tester",
            update_by_id="tester",
        )
        planned_leg = OperationsConsolidationLeg.objects.create(
            package=package_record,
            leg_sequence=1,
            source_warehouse_id=4,
            staging_warehouse_id=55,
            status_code=CONSOLIDATION_LEG_STATUS_PLANNED,
            create_by_id="tester",
            update_by_id="tester",
        )
        package_context_mock.return_value = (
            self._package_stub(reliefpkg_id=3932, reliefrqst_id=932, agency_id=501, status_code="P"),
            self._request_stub(
                reliefrqst_id=932,
                agency_id=501,
                status_code=contract_services.legacy_service.STATUS_SUBMITTED,
            ),
            request_record,
            package_record,
        )
        reset_mock.return_value = {
            "status": PACKAGE_STATUS_DRAFT,
            "reliefrqst_id": 932,
            "reliefpkg_id": 3932,
            "request_no": "RQ00932",
            "package_no": "PK03932",
            "operations_allocation_lines_deleted": 1,
            "legacy_allocation_lines_deleted": 1,
            "released_stock_summary": {"line_count": 1, "total_qty": "2.0000"},
        }

        with self.captureOnCommitCallbacks(execute=True):
            first = contract_services.abandon_package_draft(
                3932,
                payload={"reason": "Retry-safe abandon"},
                actor_id="logistics-manager-1",
                actor_roles=self.dispatch_roles,
                tenant_context=self.dispatch_ready_context,
                idempotency_key="abandon-3932",
            )
        second = contract_services.abandon_package_draft(
            3932,
            payload={"reason": "Retry-safe abandon"},
            actor_id="logistics-manager-1",
            actor_roles=self.dispatch_roles,
            tenant_context=self.dispatch_ready_context,
            idempotency_key="abandon-3932",
        )

        planned_leg.refresh_from_db()
        self.assertEqual(first, second)
        self.assertEqual(package_context_mock.call_count, 1)
        self.assertEqual(reset_mock.call_count, 1)
        record_transition_mock.assert_called_once_with(
            entity_type=contract_services.ENTITY_CONSOLIDATION_LEG,
            entity_id=int(planned_leg.leg_id),
            from_status=CONSOLIDATION_LEG_STATUS_PLANNED,
            to_status=CONSOLIDATION_LEG_STATUS_CANCELLED,
            actor_id="logistics-manager-1",
        )
        self.assertEqual(planned_leg.status_code, CONSOLIDATION_LEG_STATUS_CANCELLED)

    @patch("operations.contract_services._package_context_by_package_id")
    def test_abandon_package_draft_rejects_committed_package(
        self,
        package_context_mock,
    ) -> None:
        """Committed packages are already approved for dispatch and cannot be abandoned."""
        request_record = self._create_operations_request_record(relief_request_id=931)
        package_record = OperationsPackage.objects.create(
            package_id=3931,
            package_no="PK03931",
            relief_request=request_record,
            source_warehouse_id=4,
            staging_warehouse_id=55,
            fulfillment_mode=FULFILLMENT_MODE_DELIVER_FROM_STAGING,
            status_code=PACKAGE_STATUS_COMMITTED,
            create_by_id="tester",
            update_by_id="tester",
        )
        package_context_mock.return_value = (
            self._package_stub(reliefpkg_id=3931, reliefrqst_id=931, agency_id=501, status_code="P"),
            self._request_stub(reliefrqst_id=931, agency_id=501, status_code=contract_services.legacy_service.STATUS_SUBMITTED),
            request_record,
            package_record,
        )

        with self.assertRaises(OperationValidationError) as raised:
            contract_services.abandon_package_draft(
                3931,
                payload=None,
                actor_id="logistics-manager-1",
                actor_roles=self.dispatch_roles,
                tenant_context=self.dispatch_ready_context,
                idempotency_key="abandon-3931",
            )

        self.assertEqual(
            raised.exception.errors["abandon"],
            "This fulfillment can no longer be abandoned.",
        )

        package_record.refresh_from_db()
        self.assertEqual(package_record.status_code, PACKAGE_STATUS_COMMITTED)

    @patch("operations.contract_services._package_context_by_package_id")
    def test_abandon_package_draft_rejects_dispatched_package(
        self,
        package_context_mock,
    ) -> None:
        """Packages that have already been dispatched cannot be abandoned."""
        request_record = self._create_operations_request_record(relief_request_id=93)
        package_record = OperationsPackage.objects.create(
            package_id=393,
            package_no="PK00393",
            relief_request=request_record,
            source_warehouse_id=4,
            staging_warehouse_id=55,
            fulfillment_mode=FULFILLMENT_MODE_DELIVER_FROM_STAGING,
            status_code=PACKAGE_STATUS_DISPATCHED,
            create_by_id="tester",
            update_by_id="tester",
        )
        package_context_mock.return_value = (
            self._package_stub(reliefpkg_id=393, reliefrqst_id=93, agency_id=501, status_code="D"),
            self._request_stub(reliefrqst_id=93, agency_id=501, status_code=contract_services.legacy_service.STATUS_SUBMITTED),
            request_record,
            package_record,
        )

        with self.assertRaises(OperationValidationError) as raised:
            contract_services.abandon_package_draft(
                393,
                payload=None,
                actor_id="logistics-manager-1",
                actor_roles=self.dispatch_roles,
                tenant_context=self.dispatch_ready_context,
                idempotency_key="abandon-393",
            )

        self.assertEqual(
            raised.exception.errors["abandon"],
            "This fulfillment can no longer be abandoned.",
        )

        package_record.refresh_from_db()
        self.assertEqual(package_record.status_code, PACKAGE_STATUS_DISPATCHED)

    @patch("operations.contract_services._package_context_by_package_id")
    def test_abandon_package_draft_rejects_in_transit_consolidation_leg(
        self,
        package_context_mock,
    ) -> None:
        """In-transit legs block the abandon so we never lose shipment state."""
        request_record = self._create_operations_request_record(relief_request_id=94)
        package_record = OperationsPackage.objects.create(
            package_id=394,
            package_no="PK00394",
            relief_request=request_record,
            source_warehouse_id=4,
            staging_warehouse_id=55,
            fulfillment_mode=FULFILLMENT_MODE_DELIVER_FROM_STAGING,
            status_code=PACKAGE_STATUS_CONSOLIDATING,
            create_by_id="tester",
            update_by_id="tester",
        )
        OperationsConsolidationLeg.objects.create(
            package=package_record,
            leg_sequence=1,
            source_warehouse_id=4,
            staging_warehouse_id=55,
            status_code=CONSOLIDATION_LEG_STATUS_IN_TRANSIT,
            create_by_id="tester",
            update_by_id="tester",
        )
        package_context_mock.return_value = (
            self._package_stub(reliefpkg_id=394, reliefrqst_id=94, agency_id=501, status_code="P"),
            self._request_stub(reliefrqst_id=94, agency_id=501, status_code=contract_services.legacy_service.STATUS_SUBMITTED),
            request_record,
            package_record,
        )

        with self.assertRaises(OperationValidationError) as raised:
            contract_services.abandon_package_draft(
                394,
                payload={},
                actor_id="logistics-manager-1",
                actor_roles=self.dispatch_roles,
                tenant_context=self.dispatch_ready_context,
                idempotency_key="abandon-394",
            )

        self.assertIn("in-transit", raised.exception.errors["abandon"].lower())

    @patch("operations.contract_services._package_context_by_package_id")
    def test_abandon_package_draft_idor_cross_tenant_returns_validation_error(
        self,
        package_context_mock,
    ) -> None:
        """Officer from a different tenant cannot abandon another tenant's draft.

        The real ``_package_context_by_package_id`` raises
        ``OperationValidationError({"scope": ...})`` from ``_ensure_package_access``
        when a caller's tenant context does not cover the package's tenants. We
        mock it here to avoid exercising the legacy-table lookup chain (``agency``,
        ``reliefpkg``, ``reliefrqst``) that is not provisioned in the test DB.
        """
        package_context_mock.side_effect = OperationValidationError(
            {"scope": "Request is outside the active tenant or workflow assignment scope."}
        )
        foreign_tenant_context = _tenant_context(
            tenant_id=999,
            tenant_code="OTHER-TENANT",
            tenant_type="EXTERNAL",
        )

        with self.assertRaises(OperationValidationError) as raised:
            contract_services.abandon_package_draft(
                395,
                payload={"reason": "attempting cross-tenant abandon"},
                actor_id="rogue-officer-1",
                actor_roles=self.dispatch_roles,
                tenant_context=foreign_tenant_context,
                idempotency_key="abandon-395",
            )

        self.assertIn("scope", raised.exception.errors)
        package_context_mock.assert_called_once()
        call_kwargs = package_context_mock.call_args.kwargs
        self.assertEqual(call_kwargs["actor_id"], "rogue-officer-1")
        self.assertIs(call_kwargs["tenant_context"], foreign_tenant_context)
        self.assertTrue(call_kwargs["write"])

    def test_abandon_package_draft_rejects_oversized_reason(self) -> None:
        """Reason strings longer than 500 characters are rejected up front."""
        with self.assertRaises(OperationValidationError) as raised:
            contract_services.abandon_package_draft(
                396,
                payload={"reason": "x" * 501},
                actor_id="logistics-manager-1",
                actor_roles=self.dispatch_roles,
                tenant_context=self.dispatch_ready_context,
                idempotency_key="abandon-396",
            )

        self.assertEqual(
            raised.exception.errors["reason"],
            "Reason must be 500 characters or fewer.",
        )

    def test_abandon_package_draft_requires_idempotency_key(self) -> None:
        with self.assertRaises(OperationValidationError) as raised:
            contract_services.abandon_package_draft(
                396,
                payload={},
                actor_id="logistics-manager-1",
                actor_roles=self.dispatch_roles,
                tenant_context=self.dispatch_ready_context,
            )

        self.assertEqual(
            raised.exception.errors,
            {"idempotency_key": "Idempotency-Key header is required."},
        )

    @patch("operations.contract_services._delete_legacy_allocation_lines")
    @patch("operations.contract_services._legacy_allocation_line_count", return_value=1)
    @patch("operations.contract_services.legacy_service._apply_stock_delta_for_rows")
    @patch("operations.contract_services.legacy_service._selected_plan_for_package")
    @patch("operations.contract_services.legacy_service._current_package_status", return_value="P")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service._load_package")
    def test_reset_package_allocations_deletes_cancelled_legs_and_closes_open_queue_work(
        self,
        load_package_mock,
        load_request_mock,
        _current_status_mock,
        selected_plan_mock,
        apply_stock_delta_mock,
        _legacy_line_count_mock,
        delete_legacy_lines_mock,
    ) -> None:
        request_record = self._create_operations_request_record(relief_request_id=91)
        package_record = OperationsPackage.objects.create(
            package_id=391,
            package_no="PK00391",
            relief_request=request_record,
            source_warehouse_id=4,
            staging_warehouse_id=55,
            fulfillment_mode=FULFILLMENT_MODE_DELIVER_FROM_STAGING,
            status_code=PACKAGE_STATUS_COMMITTED,
            create_by_id="tester",
            update_by_id="tester",
        )
        OperationsAllocationLine.objects.create(
            package=package_record,
            item_id=101,
            source_warehouse_id=4,
            batch_id=1001,
            quantity=Decimal("2.0000"),
            source_type="ON_HAND",
            create_by_id="tester",
            update_by_id="tester",
        )
        leg = OperationsConsolidationLeg.objects.create(
            package=package_record,
            leg_sequence=1,
            source_warehouse_id=4,
            staging_warehouse_id=55,
            status_code=CONSOLIDATION_LEG_STATUS_CANCELLED,
            create_by_id="tester",
            update_by_id="tester",
        )
        OperationsConsolidationLegItem.objects.create(
            leg=leg,
            item_id=101,
            batch_id=1001,
            quantity=Decimal("2.0000"),
            source_type="ON_HAND",
            create_by_id="tester",
            update_by_id="tester",
        )
        dispatch_assignment = OperationsQueueAssignment.objects.create(
            queue_code=QUEUE_CODE_DISPATCH,
            entity_type="PACKAGE",
            entity_id=int(package_record.package_id),
            assigned_role_code=ROLE_LOGISTICS_MANAGER,
            assigned_tenant_id=20,
            assignment_status="OPEN",
        )
        override_assignment = OperationsQueueAssignment.objects.create(
            queue_code=QUEUE_CODE_OVERRIDE,
            entity_type="RELIEF_REQUEST",
            entity_id=int(request_record.relief_request_id),
            assigned_role_code=ROLE_LOGISTICS_MANAGER,
            assigned_tenant_id=20,
            assignment_status="OPEN",
        )
        leg_assignment = OperationsQueueAssignment.objects.create(
            queue_code=QUEUE_CODE_CONSOLIDATION_DISPATCH,
            entity_type="CONSOLIDATION_LEG",
            entity_id=int(leg.leg_id),
            assigned_role_code=ROLE_LOGISTICS_MANAGER,
            assigned_tenant_id=20,
            assignment_status="OPEN",
        )
        OperationsPackageLock.objects.create(
            package=package_record,
            lock_owner_user_id="logistics-manager-1",
            lock_owner_role_code="LOGISTICS_MANAGER",
            lock_status="ACTIVE",
        )

        package = self._package_stub(reliefpkg_id=391, reliefrqst_id=91, agency_id=501, status_code="P")
        package.save = Mock()
        request = self._request_stub(
            reliefrqst_id=91,
            agency_id=501,
            status_code=contract_services.legacy_service.STATUS_SUBMITTED,
        )
        load_package_mock.return_value = package
        load_request_mock.return_value = request
        selected_plan_mock.return_value = [
            {"inventory_id": 4, "batch_id": 1001, "item_id": 101, "quantity": "2", "uom_code": "EA"}
        ]

        result = contract_services.reset_package_allocations(
            391,
            actor_id="logistics-manager-1",
        )

        package_record.refresh_from_db()
        dispatch_assignment.refresh_from_db()
        override_assignment.refresh_from_db()
        leg_assignment.refresh_from_db()
        self.assertEqual(result["status"], "DRAFT")
        self.assertEqual(package_record.status_code, "DRAFT")
        self.assertFalse(OperationsConsolidationLeg.objects.filter(package_id=391).exists())
        self.assertFalse(OperationsConsolidationLegItem.objects.filter(leg_id=int(leg.leg_id)).exists())
        self.assertEqual(dispatch_assignment.assignment_status, "CANCELLED")
        self.assertEqual(override_assignment.assignment_status, "CANCELLED")
        self.assertEqual(leg_assignment.assignment_status, "CANCELLED")
        self.assertEqual(
            OperationsPackageLock.objects.get(package_id=int(package_record.package_id)).lock_status,
            "RELEASED",
        )
        apply_stock_delta_mock.assert_called_once()
        delete_legacy_lines_mock.assert_called_once_with(int(package_record.package_id))

    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._current_package_for_request")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service.save_package")
    def test_save_package_preserves_completed_request_status_when_legacy_reloads_as_approved(
        self,
        save_package_mock,
        load_request_mock,
        current_package_mock,
        get_agency_scope_mock,
    ) -> None:
        preserved_request = self._request_stub(
            reliefrqst_id=70,
            agency_id=501,
            status_code=contract_services.legacy_service.STATUS_CANCELLED,
        )
        load_request_mock.side_effect = [preserved_request, preserved_request]
        current_package_mock.return_value = self.package
        save_package_mock.return_value = {"status": "COMMITTED", "reliefpkg_id": 90}
        get_agency_scope_mock.return_value = self.agency_scope

        request_record = OperationsReliefRequest.objects.create(
            relief_request_id=70,
            request_no="RQ00070",
            requesting_tenant_id=20,
            requesting_agency_id=501,
            beneficiary_tenant_id=20,
            beneficiary_agency_id=501,
            origin_mode="SELF",
            event_id=12,
            request_date=date(2026, 3, 26),
            urgency_code="H",
            notes_text="Need shelter kits",
            status_code=REQUEST_STATUS_PARTIALLY_FULFILLED,
            create_by_id="seed-user",
            update_by_id="seed-user",
        )

        contract_services.save_package(
            70,
            payload={"allocations": [{"item_id": 101, "inventory_id": 4, "batch_id": 1001, "quantity": "2"}]},
            actor_id="logistics-manager-1",
            actor_roles=self.dispatch_roles,
            tenant_context=self.dispatch_ready_context,
        )

        request_record.refresh_from_db()
        self.assertEqual(request_record.status_code, REQUEST_STATUS_PARTIALLY_FULFILLED)

    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._current_package_for_request")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service.save_package")
    def test_package_commit_tolerates_missing_first_inventory_id(
        self,
        save_package_mock,
        load_request_mock,
        current_package_mock,
        get_agency_scope_mock,
    ) -> None:
        load_request_mock.return_value = self.fulfillment_request
        current_package_mock.return_value = self.package
        save_package_mock.return_value = {"status": "COMMITTED", "reliefpkg_id": 90}
        get_agency_scope_mock.return_value = self.agency_scope

        with self.assertRaises(OperationValidationError) as raised:
            contract_services.save_package(
                70,
                payload={"allocations": [{"item_id": 101, "batch_id": 1001, "quantity": "2"}]},
                actor_id="logistics-manager-1",
                actor_roles=self.dispatch_roles,
                tenant_context=self.dispatch_ready_context,
            )

        self.assertIn("allocations[0].inventory_id", raised.exception.errors)
        save_package_mock.assert_not_called()

    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._current_package_for_request")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service.save_package")
    def test_package_commit_preserves_existing_source_warehouse_when_inventory_is_missing(
        self,
        save_package_mock,
        load_request_mock,
        current_package_mock,
        get_agency_scope_mock,
    ) -> None:
        load_request_mock.return_value = self.fulfillment_request
        current_package_mock.return_value = self.package
        save_package_mock.return_value = {"status": "COMMITTED", "reliefpkg_id": 90}
        get_agency_scope_mock.return_value = self.agency_scope
        ops_request = self._create_operations_request_record()
        OperationsPackage.objects.create(
            package_id=90,
            package_no="PK00090",
            relief_request_id=ops_request.relief_request_id,
            source_warehouse_id=4,
            destination_tenant_id=20,
            destination_agency_id=501,
            status_code=PACKAGE_STATUS_COMMITTED,
            create_by_id="tester",
            update_by_id="tester",
        )

        with self.assertRaises(OperationValidationError) as raised:
            contract_services.save_package(
                70,
                payload={"allocations": [{"item_id": 101, "batch_id": 1001, "quantity": "2"}]},
                actor_id="logistics-manager-1",
                actor_roles=self.dispatch_roles,
                tenant_context=self.dispatch_ready_context,
            )

        self.assertIn("allocations[0].inventory_id", raised.exception.errors)
        save_package_mock.assert_not_called()

    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._current_package_for_request")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service.save_package")
    def test_package_commit_clears_existing_source_warehouse_when_inventory_is_null(
        self,
        save_package_mock,
        load_request_mock,
        current_package_mock,
        get_agency_scope_mock,
    ) -> None:
        load_request_mock.return_value = self.fulfillment_request
        current_package_mock.return_value = self.package
        save_package_mock.return_value = {"status": "COMMITTED", "reliefpkg_id": 90}
        get_agency_scope_mock.return_value = self.agency_scope
        ops_request = self._create_operations_request_record()
        OperationsPackage.objects.create(
            package_id=90,
            package_no="PK00090",
            relief_request_id=ops_request.relief_request_id,
            source_warehouse_id=4,
            destination_tenant_id=20,
            destination_agency_id=501,
            status_code=PACKAGE_STATUS_COMMITTED,
            create_by_id="tester",
            update_by_id="tester",
        )

        with self.assertRaises(OperationValidationError) as raised:
            contract_services.save_package(
                70,
                payload={"allocations": [{"item_id": 101, "inventory_id": None, "batch_id": 1001, "quantity": "2"}]},
                actor_id="logistics-manager-1",
                actor_roles=self.dispatch_roles,
                tenant_context=self.dispatch_ready_context,
            )

        self.assertIn("allocations[0].inventory_id", raised.exception.errors)
        save_package_mock.assert_not_called()

    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._current_package_for_request")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service.save_package")
    def test_system_administrator_can_commit_package_and_own_lock(
        self,
        save_package_mock,
        load_request_mock,
        current_package_mock,
        get_agency_scope_mock,
    ) -> None:
        load_request_mock.return_value = self.request
        current_package_mock.return_value = self.package
        save_package_mock.return_value = {"status": "COMMITTED", "reliefpkg_id": 90}
        get_agency_scope_mock.return_value = self.agency_scope

        contract_services.save_package(
            70,
            payload={"allocations": [{"item_id": 101, "inventory_id": 4, "batch_id": 1001, "quantity": "2"}]},
            actor_id="system-admin-1",
            actor_roles=[ROLE_SYSTEM_ADMINISTRATOR],
            tenant_context=self.dispatch_ready_context,
        )

        lock = OperationsPackageLock.objects.get(package_id=90)
        self.assertEqual(lock.lock_owner_role_code, ROLE_SYSTEM_ADMINISTRATOR)
        self.assertTrue(OperationsDispatch.objects.filter(package_id=90).exists())

    def test_acquire_package_lock_returns_lock_context_for_active_conflict(self) -> None:
        self._create_operations_request_record()
        OperationsPackage.objects.create(
            package_id=90,
            package_no="PK00090",
            relief_request_id=70,
            destination_tenant_id=20,
            destination_agency_id=501,
            status_code=PACKAGE_STATUS_COMMITTED,
            create_by_id="tester",
            update_by_id="tester",
        )
        lock = OperationsPackageLock.objects.create(
            package_id=90,
            lock_owner_user_id="kemar_tst",
            lock_owner_role_code=ROLE_LOGISTICS_MANAGER,
            lock_started_at=timezone.now(),
            lock_expires_at=timezone.now() + timedelta(minutes=30),
            lock_status="ACTIVE",
        )

        with self.assertRaises(OperationValidationError) as raised:
            contract_services._acquire_package_lock(
                90,
                actor_id="devon_tst",
                actor_roles=[ROLE_LOGISTICS_OFFICER],
            )

        self.assertEqual(
            raised.exception.errors["lock"],
            "Package is locked by another fulfillment actor.",
        )
        self.assertEqual(raised.exception.errors["lock_owner_user_id"], "kemar_tst")
        self.assertEqual(raised.exception.errors["lock_owner_role_code"], ROLE_LOGISTICS_MANAGER)
        self.assertEqual(
            raised.exception.errors["lock_expires_at"],
            contract_services.legacy_service._as_iso(lock.lock_expires_at),
        )

    def test_acquire_package_lock_recovers_from_concurrent_insert_race(self) -> None:
        self._create_operations_request_record()
        OperationsPackage.objects.create(
            package_id=90,
            package_no="PK00090",
            relief_request_id=70,
            destination_tenant_id=20,
            destination_agency_id=501,
            status_code=PACKAGE_STATUS_COMMITTED,
            create_by_id="tester",
            update_by_id="tester",
        )
        existing_lock = OperationsPackageLock.objects.create(
            package_id=90,
            lock_owner_user_id="logistics-manager-1",
            lock_owner_role_code="LOGISTICS_MANAGER",
            lock_started_at=timezone.now(),
            lock_expires_at=timezone.now() + timedelta(minutes=30),
            lock_status="ACTIVE",
        )
        select_for_update_mock = patch(
            "operations.contract_services.OperationsPackageLock.objects.select_for_update"
        )

        with patch(
            "operations.contract_services.OperationsPackageLock.objects.create",
            side_effect=IntegrityError("duplicate package lock"),
        ), select_for_update_mock as select_for_update:
            select_for_update.return_value.filter.return_value.first.side_effect = [None, existing_lock]
            lock = contract_services._acquire_package_lock(
                90,
                actor_id="logistics-manager-1",
                actor_roles=self.dispatch_roles,
            )

        self.assertEqual(lock.package_id, 90)
        self.assertEqual(lock.lock_owner_user_id, "logistics-manager-1")
        self.assertEqual(lock.lock_status, "ACTIVE")
        self.assertEqual(OperationsPackageLock.objects.filter(package_id=90).count(), 1)

    @patch("operations.contract_services.legacy_service._current_package_for_request")
    @patch("operations.contract_services.legacy_service._load_request")
    def test_lock_owner_can_release_their_own_package_lock(
        self,
        load_request_mock,
        current_package_mock,
    ) -> None:
        request_record = OperationsReliefRequest.objects.create(
            relief_request_id=70,
            request_no="RQ00070",
            requesting_tenant_id=19,
            requesting_agency_id=401,
            beneficiary_tenant_id=19,
            beneficiary_agency_id=501,
            origin_mode="SELF",
            event_id=12,
            request_date=date(2026, 3, 26),
            urgency_code="H",
            status_code=REQUEST_STATUS_APPROVED_FOR_FULFILLMENT,
            create_by_id="tester",
            update_by_id="tester",
        )
        package_record = self._create_operations_package_record(request_record=request_record)
        lock = OperationsPackageLock.objects.create(
            package=package_record,
            lock_owner_user_id="devon_tst",
            lock_owner_role_code=ROLE_LOGISTICS_OFFICER,
            lock_started_at=timezone.now() - timedelta(minutes=1),
            lock_expires_at=timezone.now() + timedelta(minutes=30),
            lock_status="ACTIVE",
        )
        load_request_mock.return_value = self.fulfillment_request
        current_package_mock.return_value = self.package
        OperationsQueueAssignment.objects.create(
            queue_code=QUEUE_CODE_FULFILLMENT,
            entity_type="RELIEF_REQUEST",
            entity_id=70,
            assigned_role_code=ROLE_LOGISTICS_OFFICER,
            assigned_tenant_id=27,
            assignment_status="OPEN",
        )
        with patch("operations.contract_services._resolve_request_level_fulfillment_tenant_id", return_value=27):
            result = contract_services.release_package_lock(
                70,
                actor_id="devon_tst",
                actor_roles=[ROLE_LOGISTICS_OFFICER],
                tenant_context=self.odpem_context,
            )

        lock.refresh_from_db()
        unlock_notification = OperationsNotification.objects.get(
            queue_code=QUEUE_CODE_FULFILLMENT,
            entity_type="PACKAGE",
            entity_id=90,
            recipient_user_id="devon_tst",
        )
        self.assertTrue(result["released"])
        self.assertEqual(result["package_id"], 90)
        self.assertEqual(result["package_no"], "PK00090")
        self.assertEqual(result["previous_lock_owner_user_id"], "devon_tst")
        self.assertEqual(result["previous_lock_owner_role_code"], ROLE_LOGISTICS_OFFICER)
        self.assertEqual(result["released_by_user_id"], "devon_tst")
        self.assertEqual(result["lock_status"], "RELEASED")
        self.assertEqual(lock.lock_status, "RELEASED")
        self.assertLessEqual(lock.lock_expires_at, timezone.now())
        self.assertEqual(unlock_notification.recipient_tenant_id, 27)
        self.assertNotEqual(unlock_notification.recipient_tenant_id, request_record.beneficiary_tenant_id)

    @patch("operations.contract_services.legacy_service._current_package_for_request")
    @patch("operations.contract_services.legacy_service._load_request")
    def test_other_fulfillment_user_cannot_release_someone_elses_lock_without_elevated_role(
        self,
        load_request_mock,
        current_package_mock,
    ) -> None:
        request_record = self._create_operations_request_record()
        package_record = self._create_operations_package_record(request_record=request_record)
        lock = OperationsPackageLock.objects.create(
            package=package_record,
            lock_owner_user_id="kemar_tst",
            lock_owner_role_code=ROLE_LOGISTICS_MANAGER,
            lock_started_at=timezone.now() - timedelta(minutes=1),
            lock_expires_at=timezone.now() + timedelta(minutes=30),
            lock_status="ACTIVE",
        )
        load_request_mock.return_value = self.fulfillment_request
        current_package_mock.return_value = self.package

        with self.assertRaises(OperationValidationError) as raised:
            contract_services.release_package_lock(
                70,
                actor_id="devon_tst",
                actor_roles=[ROLE_LOGISTICS_OFFICER],
                tenant_context=self.dispatch_ready_context,
                force=True,
            )

        lock.refresh_from_db()
        self.assertEqual(
            raised.exception.errors["lock"],
            "Only the current lock owner, a Logistics Manager, or a System Administrator may release this package lock.",
        )
        self.assertEqual(lock.lock_status, "ACTIVE")

    @patch("operations.contract_services.legacy_service._current_package_for_request")
    @patch("operations.contract_services.legacy_service._load_request")
    def test_logistics_manager_can_force_release_another_users_lock(
        self,
        load_request_mock,
        current_package_mock,
    ) -> None:
        request_record = OperationsReliefRequest.objects.create(
            relief_request_id=70,
            request_no="RQ00070",
            requesting_tenant_id=19,
            requesting_agency_id=401,
            beneficiary_tenant_id=19,
            beneficiary_agency_id=501,
            origin_mode="SELF",
            event_id=12,
            request_date=date(2026, 3, 26),
            urgency_code="H",
            status_code=REQUEST_STATUS_APPROVED_FOR_FULFILLMENT,
            create_by_id="tester",
            update_by_id="tester",
        )
        package_record = self._create_operations_package_record(request_record=request_record)
        lock = OperationsPackageLock.objects.create(
            package=package_record,
            lock_owner_user_id="kemar_tst",
            lock_owner_role_code=ROLE_LOGISTICS_OFFICER,
            lock_started_at=timezone.now() - timedelta(minutes=1),
            lock_expires_at=timezone.now() + timedelta(minutes=30),
            lock_status="ACTIVE",
        )
        load_request_mock.return_value = self.fulfillment_request
        current_package_mock.return_value = self.package
        OperationsQueueAssignment.objects.create(
            queue_code=QUEUE_CODE_FULFILLMENT,
            entity_type="RELIEF_REQUEST",
            entity_id=70,
            assigned_role_code=ROLE_LOGISTICS_MANAGER,
            assigned_tenant_id=27,
            assignment_status="OPEN",
        )
        with patch("operations.contract_services._resolve_request_level_fulfillment_tenant_id", return_value=27):
            result = contract_services.release_package_lock(
                70,
                actor_id="manager_tst",
                actor_roles=[ROLE_LOGISTICS_MANAGER],
                tenant_context=self.odpem_context,
                force=True,
            )

        lock.refresh_from_db()
        actor_notification = OperationsNotification.objects.get(
            queue_code=QUEUE_CODE_FULFILLMENT,
            entity_type="PACKAGE",
            entity_id=90,
            recipient_user_id="manager_tst",
        )
        previous_owner_notification = OperationsNotification.objects.get(
            queue_code=QUEUE_CODE_FULFILLMENT,
            entity_type="PACKAGE",
            entity_id=90,
            recipient_user_id="kemar_tst",
        )
        self.assertTrue(result["released"])
        self.assertEqual(result["previous_lock_owner_user_id"], "kemar_tst")
        self.assertEqual(result["previous_lock_owner_role_code"], ROLE_LOGISTICS_OFFICER)
        self.assertEqual(result["released_by_user_id"], "manager_tst")
        self.assertEqual(lock.lock_status, "RELEASED")
        self.assertLessEqual(lock.lock_expires_at, timezone.now())
        self.assertEqual(actor_notification.recipient_tenant_id, 27)
        self.assertEqual(previous_owner_notification.recipient_tenant_id, 27)
        self.assertNotEqual(previous_owner_notification.recipient_tenant_id, request_record.beneficiary_tenant_id)

    @patch("operations.contract_services.legacy_service._current_package_for_request")
    @patch("operations.contract_services.legacy_service._load_request")
    def test_release_package_lock_returns_safe_success_when_no_active_lock_exists(
        self,
        load_request_mock,
        current_package_mock,
    ) -> None:
        request_record = self._create_operations_request_record()
        self._create_operations_package_record(request_record=request_record)
        load_request_mock.return_value = self.fulfillment_request
        current_package_mock.return_value = self.package

        result = contract_services.release_package_lock(
            70,
            actor_id="devon_tst",
            actor_roles=[ROLE_LOGISTICS_OFFICER],
            tenant_context=self.dispatch_ready_context,
        )

        self.assertFalse(result["released"])
        self.assertEqual(result["package_id"], 90)
        self.assertEqual(result["package_no"], "PK00090")
        self.assertEqual(result["lock_status"], None)
        self.assertEqual(result["message"], "No active package lock found for this package.")

    @patch("operations.contract_services.legacy_service._current_package_for_request")
    @patch("operations.contract_services.legacy_service._load_request")
    def test_release_package_lock_enforces_request_scope(
        self,
        load_request_mock,
        current_package_mock,
    ) -> None:
        request_record = self._create_operations_request_record()
        package_record = self._create_operations_package_record(request_record=request_record)
        OperationsPackageLock.objects.create(
            package=package_record,
            lock_owner_user_id="kemar_tst",
            lock_owner_role_code=ROLE_LOGISTICS_MANAGER,
            lock_started_at=timezone.now() - timedelta(minutes=1),
            lock_expires_at=timezone.now() + timedelta(minutes=30),
            lock_status="ACTIVE",
        )
        load_request_mock.return_value = self.fulfillment_request
        current_package_mock.return_value = self.package
        unrelated_context = _tenant_context(tenant_id=31, tenant_code="EXT-31", tenant_type="EXTERNAL")

        with self.assertRaises(OperationValidationError) as raised:
            contract_services.release_package_lock(
                70,
                actor_id="manager_tst",
                actor_roles=[ROLE_LOGISTICS_MANAGER],
                tenant_context=unrelated_context,
                force=True,
            )

        self.assertEqual(
            raised.exception.errors["scope"],
            "Request is outside the active tenant or workflow assignment scope.",
        )

    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._current_package_for_request")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service.save_package")
    def test_package_commit_updates_existing_dispatch_route_fields_after_edit(
        self,
        save_package_mock,
        load_request_mock,
        current_package_mock,
        get_agency_scope_mock,
    ) -> None:
        load_request_mock.return_value = self.fulfillment_request
        current_package_mock.return_value = self.package
        save_package_mock.return_value = {"status": "COMMITTED", "reliefpkg_id": 90}
        get_agency_scope_mock.return_value = self.agency_scope
        self._create_operations_request_record()
        OperationsPackage.objects.create(
            package_id=90,
            package_no="PK00090",
            relief_request_id=70,
            source_warehouse_id=4,
            destination_tenant_id=20,
            destination_agency_id=501,
            status_code=PACKAGE_STATUS_COMMITTED,
            create_by_id="tester",
            update_by_id="tester",
        )
        OperationsDispatch.objects.create(
            package_id=90,
            dispatch_no="DP00090",
            status_code="READY",
            source_warehouse_id=4,
            destination_tenant_id=20,
            destination_agency_id=501,
            create_by_id="tester",
            update_by_id="tester",
        )

        contract_services.save_package(
            70,
            payload={"allocations": [{"item_id": 101, "inventory_id": 9, "batch_id": 1001, "quantity": "2"}]},
            actor_id="logistics-manager-1",
            actor_roles=self.dispatch_roles,
            tenant_context=self.dispatch_ready_context,
        )

        dispatch = OperationsDispatch.objects.get(package_id=90)
        self.assertEqual(dispatch.source_warehouse_id, 9)
        self.assertEqual(dispatch.destination_tenant_id, 20)
        self.assertEqual(dispatch.destination_agency_id, 501)

    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._current_package_for_request")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service.save_package")
    @patch("operations.contract_services.get_package")
    def test_package_draft_save_persists_requested_source_warehouse_without_allocations(
        self,
        get_package_mock,
        save_package_mock,
        load_request_mock,
        current_package_mock,
        get_agency_scope_mock,
    ) -> None:
        load_request_mock.return_value = self.fulfillment_request
        current_package_mock.return_value = self.package
        save_package_mock.return_value = {"status": "DRAFT", "reliefpkg_id": 90}
        get_agency_scope_mock.return_value = self.agency_scope
        get_package_mock.return_value = {"package": {"source_warehouse_id": 3}}

        contract_services.save_package(
            70,
            payload={"source_warehouse_id": 3, "comments_text": "Seeded for warehouse testing."},
            actor_id="logistics-manager-1",
            actor_roles=self.dispatch_roles,
            tenant_context=self.dispatch_ready_context,
        )

        package_record = OperationsPackage.objects.get(package_id=90)
        self.assertEqual(package_record.source_warehouse_id, 3)
        self.assertEqual(package_record.status_code, "DRAFT")

    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._current_package_for_request")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service.save_package")
    def test_package_draft_save_persists_exact_allocation_lines_without_forwarding_commit_payload(
        self,
        save_package_mock,
        load_request_mock,
        current_package_mock,
        get_agency_scope_mock,
    ) -> None:
        load_request_mock.return_value = self.fulfillment_request
        current_package_mock.return_value = self.package
        save_package_mock.return_value = {"status": "DRAFT", "reliefpkg_id": 90}
        get_agency_scope_mock.return_value = self.agency_scope
        request_record = self._create_operations_request_record()
        self._create_operations_package_record(
            request_record=request_record,
            status_code="DRAFT",
        )
        OperationsAllocationLine.objects.create(
            package_id=90,
            item_id=101,
            source_warehouse_id=4,
            batch_id=999,
            quantity=Decimal("9.0000"),
            source_type="ON_HAND",
            create_by_id="tester",
            update_by_id="tester",
        )

        contract_services.save_package(
            70,
            payload={
                "draft_save": True,
                "source_warehouse_id": 3,
                "allocations": [
                    {"item_id": 101, "inventory_id": 3, "batch_id": 1001, "quantity": "2.0000"},
                    {"item_id": 101, "inventory_id": 5, "batch_id": 1002, "quantity": "1.0000"},
                ],
            },
            actor_id="logistics-manager-1",
            actor_roles=self.dispatch_roles,
            tenant_context=self.dispatch_ready_context,
        )

        save_package_mock.assert_called_once_with(
            70,
            payload={"source_warehouse_id": 3},
            actor_id="logistics-manager-1",
            actor_roles=self.dispatch_roles,
            tenant_context=self.dispatch_ready_context,
        )
        package_record = OperationsPackage.objects.get(package_id=90)
        self.assertEqual(package_record.status_code, "DRAFT")
        self.assertEqual(package_record.source_warehouse_id, 3)
        self.assertQuerySetEqual(
            OperationsAllocationLine.objects.filter(package_id=90).order_by("source_warehouse_id", "batch_id"),
            [
                (101, 3, 1001, Decimal("2.0000")),
                (101, 5, 1002, Decimal("1.0000")),
            ],
            transform=lambda line: (
                int(line.item_id),
                int(line.source_warehouse_id),
                int(line.batch_id),
                line.quantity,
            ),
        )

    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._current_package_for_request")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service.save_package")
    def test_package_draft_save_does_not_fabricate_default_warehouse_from_per_item_allocations(
        self,
        save_package_mock,
        load_request_mock,
        current_package_mock,
        get_agency_scope_mock,
    ) -> None:
        """When the client does per-item warehouse selection without sending an
        explicit package-level default, the backend must NOT derive one from
        the first allocation row. Otherwise the picker resurfaces a fabricated
        "default" the user never selected on reload."""
        load_request_mock.return_value = self.fulfillment_request
        current_package_mock.return_value = self.package
        save_package_mock.return_value = {"status": "DRAFT", "reliefpkg_id": 90}
        get_agency_scope_mock.return_value = self.agency_scope
        request_record = self._create_operations_request_record()
        OperationsPackage.objects.create(
            package_id=90,
            package_no="PK00090",
            relief_request=request_record,
            source_warehouse_id=None,
            destination_tenant_id=request_record.beneficiary_tenant_id,
            destination_agency_id=request_record.beneficiary_agency_id,
            status_code="DRAFT",
            create_by_id="tester",
            update_by_id="tester",
        )

        contract_services.save_package(
            70,
            payload={
                "draft_save": True,
                "allocations": [
                    {"item_id": 101, "inventory_id": 3, "batch_id": 1001, "quantity": "2.0000"},
                    {"item_id": 101, "inventory_id": 5, "batch_id": 1002, "quantity": "1.0000"},
                ],
            },
            actor_id="logistics-manager-1",
            actor_roles=self.dispatch_roles,
            tenant_context=self.dispatch_ready_context,
        )

        package_record = OperationsPackage.objects.get(package_id=90)
        self.assertEqual(package_record.status_code, "DRAFT")
        self.assertIsNone(package_record.source_warehouse_id)
        self.assertEqual(
            OperationsAllocationLine.objects.filter(package_id=90).count(),
            2,
        )

    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._current_package_for_request")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service._request_items", return_value=[])
    @patch("operations.contract_services.legacy_service._package_detail")
    def test_get_package_uses_saved_draft_allocation_lines_for_draft_packages(
        self,
        package_detail_mock,
        _request_items_mock,
        load_request_mock,
        current_package_mock,
        get_agency_scope_mock,
    ) -> None:
        draft_package = self._package_stub(
            reliefpkg_id=90,
            reliefrqst_id=70,
            agency_id=501,
            status_code="A",
        )
        load_request_mock.return_value = self.fulfillment_request
        current_package_mock.return_value = draft_package
        get_agency_scope_mock.return_value = self.agency_scope
        request_record = self._create_operations_request_record()
        self._create_operations_package_record(
            request_record=request_record,
            status_code="DRAFT",
        )
        OperationsAllocationLine.objects.create(
            package_id=90,
            item_id=101,
            source_warehouse_id=3,
            batch_id=1001,
            quantity=Decimal("2.0000"),
            source_type="ON_HAND",
            create_by_id="tester",
            update_by_id="tester",
        )
        OperationsAllocationLine.objects.create(
            package_id=90,
            item_id=101,
            source_warehouse_id=5,
            batch_id=1002,
            quantity=Decimal("1.0000"),
            source_type="ON_HAND",
            create_by_id="tester",
            update_by_id="tester",
        )

        with patch(
            "operations.contract_services._request_summary_payload",
            return_value={"reliefrqst_id": 70, "status_code": "APPROVED_FOR_FULFILLMENT"},
        ), patch(
            "operations.contract_services._package_summary_payload",
            return_value={"reliefpkg_id": 90, "source_warehouse_id": 3},
        ):
            result = contract_services.get_package(
                70,
                actor_id="kemar_tst",
                actor_roles=[ROLE_LOGISTICS_MANAGER],
                tenant_context=self.dispatch_ready_context,
            )

        package_detail_mock.assert_not_called()
        self.assertEqual(result["package"]["source_warehouse_id"], 3)
        self.assertEqual(
            result["package"]["allocation"]["reserved_stock_summary"],
            {"line_count": 2, "total_qty": "3.0000"},
        )
        self.assertEqual(
            [
                (
                    line["item_id"],
                    line["inventory_id"],
                    line["batch_id"],
                    line["quantity"],
                )
                for line in result["package"]["allocation"]["allocation_lines"]
            ],
            [
                (101, 3, 1001, "2.0000"),
                (101, 5, 1002, "1.0000"),
            ],
        )

    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._current_package_for_request")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service.save_package")
    def test_package_save_rejects_conflicting_lock_before_legacy_write(
        self,
        save_package_mock,
        load_request_mock,
        current_package_mock,
        get_agency_scope_mock,
    ) -> None:
        load_request_mock.return_value = self.fulfillment_request
        current_package_mock.return_value = self.package
        get_agency_scope_mock.return_value = self.agency_scope
        self._create_operations_request_record()
        OperationsPackage.objects.create(
            package_id=90,
            package_no="PK00090",
            relief_request_id=70,
            source_warehouse_id=4,
            destination_tenant_id=20,
            destination_agency_id=501,
            status_code=PACKAGE_STATUS_COMMITTED,
            create_by_id="tester",
            update_by_id="tester",
        )
        OperationsPackageLock.objects.create(
            package_id=90,
            lock_owner_user_id="other-actor",
            lock_owner_role_code="LOGISTICS_MANAGER",
            lock_started_at=timezone.now(),
            lock_expires_at=timezone.now() + timedelta(minutes=30),
            lock_status="ACTIVE",
        )

        with self.assertRaises(OperationValidationError):
            contract_services.save_package(
                70,
                payload={"allocations": [{"item_id": 101, "inventory_id": 4, "batch_id": 1001, "quantity": "2"}]},
                actor_id="logistics-manager-1",
                actor_roles=self.dispatch_roles,
                tenant_context=self.dispatch_ready_context,
            )

        save_package_mock.assert_not_called()

    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._request_item_rows_for_allocation", return_value=[{"request_qty": "2", "issue_qty": "2"}])
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service._load_package")
    @patch("operations.contract_services.legacy_service.submit_dispatch")
    def test_dispatch_handoff_persists_transport_waybill_and_receipt_queue(
        self,
        submit_dispatch_mock,
        load_package_mock,
        load_request_mock,
        _request_items_mock,
        get_agency_scope_mock,
    ) -> None:
        dispatched_package = SimpleNamespace(**{**self.package.__dict__, "dispatch_dtime": datetime(2026, 3, 26, 12, 0, 0), "status_code": "D"})
        load_package_mock.return_value = dispatched_package
        load_request_mock.return_value = self.request
        submit_dispatch_mock.return_value = {
            "status": "DISPATCHED",
            "waybill_no": "WB-PK00090",
            "waybill_payload": {"line_items": [{"item_id": 101}]},
        }
        get_agency_scope_mock.return_value = self.agency_scope
        request_record = self._create_operations_request_record()
        package_record = OperationsPackage.objects.create(
            package_id=90,
            package_no="PK00090",
            relief_request=request_record,
            source_warehouse_id=4,
            staging_warehouse_id=55,
            fulfillment_mode=FULFILLMENT_MODE_DELIVER_FROM_STAGING,
            destination_tenant_id=20,
            destination_agency_id=501,
            status_code=PACKAGE_STATUS_READY_FOR_DISPATCH,
            create_by_id="seed-user",
            update_by_id="seed-user",
        )

        result = contract_services.submit_dispatch(
            90,
            payload={
                "transport_mode": "TRUCK",
                "driver_name": "Jane Driver",
                "driver_license_no": "DL123456789",
                "vehicle_registration": "1234AB",
                "departure_dtime": "2026-03-26T10:00:00Z",
                "estimated_arrival_dtime": "2026-03-26T13:00:00Z",
            },
            actor_id="dispatch-1",
            actor_roles=["LOGISTICS_OFFICER"],
            tenant_context=self.dispatch_ready_context,
            idempotency_key="dispatch-90",
        )

        self.assertEqual(result["dispatch"]["status_code"], DISPATCH_STATUS_IN_TRANSIT)
        self.assertTrue(OperationsDispatchTransport.objects.filter(dispatch_id=result["dispatch"]["dispatch_id"]).exists())
        transport_record = OperationsDispatchTransport.objects.get(dispatch_id=result["dispatch"]["dispatch_id"])
        self.assertEqual(transport_record.driver_license_last4, "6789")
        self.assertTrue(OperationsWaybill.objects.filter(waybill_no="WB-PK00090").exists())
        self.assertTrue(OperationsQueueAssignment.objects.filter(queue_code=QUEUE_CODE_RECEIPT, entity_id=90).exists())
        dispatch_record = OperationsDispatch.objects.get(dispatch_id=result["dispatch"]["dispatch_id"])
        self.assertEqual(
            dispatch_record.source_warehouse_id,
            package_record.effective_dispatch_source_warehouse_id,
        )

    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service._load_package")
    @patch("operations.contract_services.legacy_service.submit_dispatch")
    def test_dispatch_out_of_scope_rejected_before_side_effects(
        self,
        submit_dispatch_mock,
        load_package_mock,
        load_request_mock,
        get_agency_scope_mock,
    ) -> None:
        load_package_mock.return_value = self.package
        load_request_mock.return_value = self.request
        get_agency_scope_mock.return_value = self.agency_scope

        with self.assertRaises(OperationValidationError):
            contract_services.submit_dispatch(
                90,
                payload={
                    "transport_mode": "TRUCK",
                    "driver_name": "Jane Driver",
                    "vehicle_registration": "1234AB",
                    "departure_dtime": "2026-03-26T10:00:00Z",
                    "estimated_arrival_dtime": "2026-03-26T13:00:00Z",
                },
                actor_id="dispatch-1",
                actor_roles=["LOGISTICS_OFFICER"],
                tenant_context=_tenant_context(tenant_id=999, tenant_code="OTHER", tenant_type="EXTERNAL"),
                idempotency_key="dispatch-other",
            )

        submit_dispatch_mock.assert_not_called()
        self.assertFalse(OperationsWaybill.objects.exists())
        self.assertFalse(OperationsDispatchTransport.objects.exists())

    def test_validated_transport_payload_rejects_unparseable_datetimes(self) -> None:
        with self.assertRaises(OperationValidationError) as raised:
            contract_services._validated_transport_payload(
                {
                    "driver_name": "Jane Driver",
                    "vehicle_registration": "1234AB",
                    "departure_dtime": "not-a-datetime",
                    "estimated_arrival_dtime": "2026-03-26T13:00:00Z",
                }
            )

        self.assertEqual(
            raised.exception.errors["departure_dtime"],
            "departure_dtime must be a valid ISO 8601 datetime.",
        )

    def test_validated_transport_payload_rejects_eta_before_departure(self) -> None:
        with self.assertRaises(OperationValidationError) as raised:
            contract_services._validated_transport_payload(
                {
                    "driver_name": "Jane Driver",
                    "vehicle_registration": "1234AB",
                    "departure_dtime": "2026-03-26T14:00:00Z",
                    "estimated_arrival_dtime": "2026-03-26T13:00:00Z",
                }
            )

        self.assertEqual(
            raised.exception.errors["estimated_arrival_dtime"],
            "estimated_arrival_dtime cannot be earlier than departure_dtime.",
        )

    def test_dispatch_payload_returns_driver_license_last4_only(self) -> None:
        self._create_operations_request_record()
        package = OperationsPackage.objects.create(
            package_id=90,
            package_no="PK00090",
            relief_request_id=70,
            source_warehouse_id=4,
            destination_tenant_id=20,
            destination_agency_id=501,
            status_code=PACKAGE_STATUS_DISPATCHED,
            dispatched_at=datetime(2026, 3, 26, 12, 0, 0),
            create_by_id="tester",
            update_by_id="tester",
        )
        dispatch = OperationsDispatch.objects.create(
            package_id=90,
            dispatch_no="DP00090",
            status_code=DISPATCH_STATUS_IN_TRANSIT,
            source_warehouse_id=4,
            destination_tenant_id=20,
            destination_agency_id=501,
            create_by_id="tester",
            update_by_id="tester",
        )
        OperationsDispatchTransport.objects.create(
            dispatch_id=dispatch.dispatch_id,
            driver_name="Jane Driver",
            driver_license_last4="6789",
            vehicle_registration="1234AB",
            transport_mode="TRUCK",
        )

        payload = contract_services._dispatch_payload(package, dispatch)

        self.assertEqual(payload["transport"]["driver_license_last4"], "6789")
        self.assertNotIn("driver_license_no", payload["transport"])

    @patch("operations.contract_services._dispatch_payload", side_effect=lambda package, dispatch: {"dispatch_id": int(dispatch.dispatch_id), "status_code": dispatch.status_code})
    @patch("operations.contract_services._request_summary_payload", side_effect=lambda request, request_record: {"reliefrqst_id": int(request.reliefrqst_id)})
    @patch("operations.contract_services._package_summary_payload", side_effect=lambda package, package_record=None: {"reliefpkg_id": int(package.reliefpkg_id), "status_code": package_record.status_code if package_record else None})
    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service._load_package")
    def test_dispatch_queue_fallback_excludes_already_dispatched_rows(
        self,
        load_package_mock,
        load_request_mock,
        get_agency_scope_mock,
        _package_summary_mock,
        _request_summary_mock,
        _dispatch_payload_mock,
    ) -> None:
        OperationsReliefRequest.objects.create(
            relief_request_id=70,
            request_no="RQ00070",
            requesting_tenant_id=20,
            requesting_agency_id=501,
            beneficiary_tenant_id=20,
            beneficiary_agency_id=501,
            origin_mode="SELF",
            event_id=12,
            request_date=date(2026, 3, 26),
            urgency_code="H",
            status_code=REQUEST_STATUS_APPROVED_FOR_FULFILLMENT,
            create_by_id="tester",
            update_by_id="tester",
        )
        OperationsReliefRequest.objects.create(
            relief_request_id=71,
            request_no="RQ00071",
            requesting_tenant_id=20,
            requesting_agency_id=502,
            beneficiary_tenant_id=20,
            beneficiary_agency_id=502,
            origin_mode="SELF",
            event_id=12,
            request_date=date(2026, 3, 26),
            urgency_code="H",
            status_code=REQUEST_STATUS_APPROVED_FOR_FULFILLMENT,
            create_by_id="tester",
            update_by_id="tester",
        )
        OperationsPackage.objects.create(
            package_id=90,
            package_no="PK00090",
            relief_request_id=70,
            destination_tenant_id=20,
            destination_agency_id=501,
            status_code=PACKAGE_STATUS_COMMITTED,
            create_by_id="tester",
            update_by_id="tester",
        )
        OperationsPackage.objects.create(
            package_id=91,
            package_no="PK00091",
            relief_request_id=71,
            destination_tenant_id=20,
            destination_agency_id=502,
            status_code=PACKAGE_STATUS_DISPATCHED,
            dispatched_at=datetime(2026, 3, 26, 12, 0, 0),
            create_by_id="tester",
            update_by_id="tester",
        )
        packages = {
            90: self._package_stub(reliefpkg_id=90, reliefrqst_id=70, agency_id=501, status_code="P"),
            91: self._package_stub(reliefpkg_id=91, reliefrqst_id=71, agency_id=502, status_code="D", dispatch_dtime=datetime(2026, 3, 26, 12, 0, 0)),
        }
        requests = {
            70: self._request_stub(reliefrqst_id=70, agency_id=501, status_code=3),
            71: self._request_stub(reliefrqst_id=71, agency_id=502, status_code=3),
        }
        load_package_mock.side_effect = lambda reliefpkg_id: packages[int(reliefpkg_id)]
        load_request_mock.side_effect = lambda reliefrqst_id: requests[int(reliefrqst_id)]
        get_agency_scope_mock.side_effect = lambda agency_id: self._agency_scope_for(int(agency_id), 20, "FFP")

        result = contract_services.list_dispatch_queue(
            actor_id="dispatch-1",
            actor_roles=["LOGISTICS_OFFICER"],
            tenant_context=self.dispatch_ready_context,
        )

        self.assertEqual([row["reliefpkg_id"] for row in result["results"]], [90])
        load_package_mock.assert_called_once_with(90)

    @patch("operations.contract_services._dispatch_payload", side_effect=lambda package, dispatch: {"dispatch_id": int(dispatch.dispatch_id), "status_code": dispatch.status_code})
    @patch("operations.contract_services._request_summary_payload", side_effect=lambda request, request_record: {"reliefrqst_id": int(request.reliefrqst_id)})
    @patch("operations.contract_services._package_summary_payload", side_effect=lambda package, package_record=None: {"reliefpkg_id": int(package.reliefpkg_id), "status_code": package_record.status_code if package_record else None})
    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service._load_package")
    def test_dispatch_queue_fallback_respects_scope(
        self,
        load_package_mock,
        load_request_mock,
        get_agency_scope_mock,
        _package_summary_mock,
        _request_summary_mock,
        _dispatch_payload_mock,
    ) -> None:
        OperationsReliefRequest.objects.create(
            relief_request_id=70,
            request_no="RQ00070",
            requesting_tenant_id=20,
            requesting_agency_id=501,
            beneficiary_tenant_id=20,
            beneficiary_agency_id=501,
            origin_mode="SELF",
            event_id=12,
            request_date=date(2026, 3, 26),
            urgency_code="H",
            status_code=REQUEST_STATUS_APPROVED_FOR_FULFILLMENT,
            create_by_id="tester",
            update_by_id="tester",
        )
        OperationsReliefRequest.objects.create(
            relief_request_id=72,
            request_no="RQ00072",
            requesting_tenant_id=30,
            requesting_agency_id=503,
            beneficiary_tenant_id=30,
            beneficiary_agency_id=503,
            origin_mode="SELF",
            event_id=12,
            request_date=date(2026, 3, 26),
            urgency_code="H",
            status_code=REQUEST_STATUS_APPROVED_FOR_FULFILLMENT,
            create_by_id="tester",
            update_by_id="tester",
        )
        OperationsPackage.objects.create(
            package_id=90,
            package_no="PK00090",
            relief_request_id=70,
            destination_tenant_id=20,
            destination_agency_id=501,
            status_code=PACKAGE_STATUS_COMMITTED,
            create_by_id="tester",
            update_by_id="tester",
        )
        OperationsPackage.objects.create(
            package_id=92,
            package_no="PK00092",
            relief_request_id=72,
            destination_tenant_id=30,
            destination_agency_id=503,
            status_code=PACKAGE_STATUS_COMMITTED,
            create_by_id="tester",
            update_by_id="tester",
        )
        packages = {
            90: self._package_stub(reliefpkg_id=90, reliefrqst_id=70, agency_id=501, status_code="P"),
            92: self._package_stub(reliefpkg_id=92, reliefrqst_id=72, agency_id=503, status_code="P"),
        }
        requests = {
            70: self._request_stub(reliefrqst_id=70, agency_id=501, status_code=3),
            72: self._request_stub(reliefrqst_id=72, agency_id=503, status_code=3),
        }
        load_package_mock.side_effect = lambda reliefpkg_id: packages[int(reliefpkg_id)]
        load_request_mock.side_effect = lambda reliefrqst_id: requests[int(reliefrqst_id)]
        get_agency_scope_mock.side_effect = lambda agency_id: {
            501: self._agency_scope_for(501, 20, "FFP"),
            503: self._agency_scope_for(503, 30, "OUT-30"),
        }[int(agency_id)]

        result = contract_services.list_dispatch_queue(
            actor_id="dispatch-1",
            actor_roles=["LOGISTICS_OFFICER"],
            tenant_context=self.dispatch_ready_context,
        )

        self.assertEqual([row["reliefpkg_id"] for row in result["results"]], [90])

    @patch("operations.contract_services._request_summary_payload", side_effect=lambda request, request_record: {"reliefrqst_id": int(request.reliefrqst_id)})
    @patch("operations.contract_services.ReliefRqst.objects.filter")
    @patch("operations.contract_services.operations_policy.get_agency_scope")
    def test_eligibility_queue_fallback_excludes_out_of_scope_requests(
        self,
        get_agency_scope_mock,
        legacy_request_filter_mock,
        _request_summary_mock,
    ) -> None:
        request_in_scope = self._request_stub(
            reliefrqst_id=80,
            agency_id=501,
            status_code=contract_services.legacy_service.STATUS_AWAITING_APPROVAL,
        )
        request_out_of_scope = self._request_stub(
            reliefrqst_id=81,
            agency_id=503,
            status_code=contract_services.legacy_service.STATUS_AWAITING_APPROVAL,
        )
        legacy_request_filter_mock.return_value.order_by.return_value.iterator.return_value = [
            request_in_scope,
            request_out_of_scope,
        ]
        get_agency_scope_mock.side_effect = lambda agency_id: {
            501: self._agency_scope_for(501, 20, "FFP"),
            503: self._agency_scope_for(503, 30, "OUT-30"),
        }[int(agency_id)]

        result = contract_services.list_eligibility_queue(
            actor_id="eligibility-1",
            actor_roles=[ELIGIBILITY_ROLE_CODES[0]],
            tenant_context=self.dispatch_ready_context,
        )

        self.assertEqual([row["reliefrqst_id"] for row in result["results"]], [80])
        self.assertTrue(OperationsReliefRequest.objects.filter(relief_request_id=80).exists())
        self.assertFalse(OperationsReliefRequest.objects.filter(relief_request_id=81).exists())

    @patch(
        "operations.contract_services._request_summary_payload",
        side_effect=lambda request, request_record: {
            "reliefrqst_id": int(request.reliefrqst_id),
            "status_code": request_record.status_code,
            "request_mode": request_record.origin_mode,
            "origin_mode": request_record.origin_mode,
            "requesting_tenant_id": request_record.requesting_tenant_id,
            "requesting_agency_id": request_record.requesting_agency_id,
            "beneficiary_tenant_id": request_record.beneficiary_tenant_id,
            "beneficiary_agency_id": request_record.beneficiary_agency_id,
        },
    )
    @patch("operations.contract_services.ReliefPkg.objects.filter")
    @patch("operations.contract_services.legacy_service.get_request")
    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._load_request")
    def test_get_eligibility_request_preserves_approved_status_on_read(
        self,
        load_request_mock,
        get_agency_scope_mock,
        get_request_mock,
        filter_packages_mock,
        _request_summary_payload_mock,
    ) -> None:
        request = self._request_stub(
            reliefrqst_id=70,
            agency_id=501,
            status_code=contract_services.legacy_service.STATUS_SUBMITTED,
        )
        load_request_mock.return_value = request
        get_agency_scope_mock.return_value = self._agency_scope_for(501, 20, "FFP")
        get_request_mock.return_value = {"reliefrqst_id": 70, "items": [], "packages": []}
        filter_packages_mock.return_value.order_by.return_value = []
        OperationsReliefRequest.objects.create(
            relief_request_id=70,
            request_no="RQ00070",
            requesting_tenant_id=30,
            requesting_agency_id=777,
            beneficiary_tenant_id=20,
            beneficiary_agency_id=501,
            origin_mode=ORIGIN_MODE_FOR_SUBORDINATE,
            event_id=12,
            request_date=date(2026, 3, 26),
            urgency_code="H",
            status_code=REQUEST_STATUS_APPROVED_FOR_FULFILLMENT,
            create_by_id="tester",
            update_by_id="tester",
        )
        OperationsEligibilityDecision.objects.create(
            relief_request_id=70,
            decision_code="APPROVED",
            decision_reason=None,
            decided_by_user_id="eligibility-1",
            decided_by_role_code=ELIGIBILITY_ROLE_CODES[0],
            decided_at=timezone.now(),
        )

        payload = contract_services.get_eligibility_request(
            70,
            actor_id="eligibility-1",
            actor_roles=[ELIGIBILITY_ROLE_CODES[0]],
            tenant_context=self.dispatch_ready_context,
        )

        self.assertEqual(payload["status_code"], REQUEST_STATUS_APPROVED_FOR_FULFILLMENT)
        self.assertTrue(payload["decision_made"])
        self.assertFalse(payload["can_edit"])
        self.assertEqual(payload["request_mode"], ORIGIN_MODE_FOR_SUBORDINATE)
        self.assertEqual(payload["origin_mode"], ORIGIN_MODE_FOR_SUBORDINATE)
        self.assertEqual(payload["requesting_tenant_id"], 30)
        self.assertEqual(payload["requesting_agency_id"], 777)
        self.assertEqual(payload["beneficiary_tenant_id"], 20)
        self.assertEqual(payload["beneficiary_agency_id"], 501)

    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services._sync_operations_request")
    @patch("operations.contract_services.legacy_service.get_request")
    @patch("operations.contract_services.legacy_service._load_request")
    def test_get_eligibility_request_rejects_same_tenant_request_outside_visibility_statuses(
        self,
        load_request_mock,
        get_request_mock,
        sync_request_mock,
        get_agency_scope_mock,
    ) -> None:
        load_request_mock.return_value = self._request_stub(
            reliefrqst_id=74,
            agency_id=501,
            status_code=contract_services.legacy_service.STATUS_DRAFT,
        )
        get_agency_scope_mock.return_value = self._agency_scope_for(501, 20, "FFP")

        with self.assertRaises(OperationValidationError):
            contract_services.get_eligibility_request(
                74,
                actor_id="eligibility-1",
                actor_roles=[ELIGIBILITY_ROLE_CODES[0]],
                tenant_context=self.dispatch_ready_context,
            )

        get_request_mock.assert_not_called()
        sync_request_mock.assert_not_called()

    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service.get_request")
    @patch("operations.contract_services.legacy_service._load_request")
    def test_get_eligibility_request_rejects_unrelated_assignment_outside_review_scope(
        self,
        load_request_mock,
        get_request_mock,
        get_agency_scope_mock,
    ) -> None:
        request = self._request_stub(
            reliefrqst_id=72,
            agency_id=503,
            status_code=contract_services.legacy_service.STATUS_SUBMITTED,
        )
        load_request_mock.return_value = request
        get_agency_scope_mock.return_value = self._agency_scope_for(503, 30, "OUT-30")
        OperationsReliefRequest.objects.create(
            relief_request_id=72,
            request_no="RQ00072",
            requesting_tenant_id=30,
            requesting_agency_id=503,
            beneficiary_tenant_id=30,
            beneficiary_agency_id=503,
            origin_mode="SELF",
            event_id=12,
            request_date=date(2026, 3, 26),
            urgency_code="H",
            status_code=REQUEST_STATUS_UNDER_ELIGIBILITY_REVIEW,
            create_by_id="tester",
            update_by_id="tester",
        )
        OperationsQueueAssignment.objects.create(
            queue_code=QUEUE_CODE_FULFILLMENT,
            entity_type="RELIEF_REQUEST",
            entity_id=72,
            assigned_user_id="eligibility-1",
            assigned_tenant_id=20,
            assignment_status="OPEN",
        )

        with self.assertRaises(OperationValidationError):
            contract_services.get_eligibility_request(
                72,
                actor_id="eligibility-1",
                actor_roles=[ELIGIBILITY_ROLE_CODES[0]],
                tenant_context=self.dispatch_ready_context,
            )

        get_request_mock.assert_not_called()

    @patch(
        "operations.contract_services._request_summary_payload",
        side_effect=lambda request, request_record: {
            "reliefrqst_id": int(request.reliefrqst_id),
            "status_code": request_record.status_code,
        },
    )
    @patch("operations.contract_services.ReliefRqst.objects.filter")
    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._load_request")
    def test_eligibility_queue_excludes_decided_requests_without_actor_review_scope(
        self,
        load_request_mock,
        get_agency_scope_mock,
        _relief_request_filter_mock,
        _request_summary_payload_mock,
    ) -> None:
        decided_request = self._request_stub(
            reliefrqst_id=73,
            agency_id=503,
            status_code=contract_services.legacy_service.STATUS_SUBMITTED,
        )
        load_request_mock.return_value = decided_request
        get_agency_scope_mock.return_value = self._agency_scope_for(503, 30, "OUT-30")
        _relief_request_filter_mock.return_value.order_by.return_value.iterator.return_value = []

        OperationsReliefRequest.objects.create(
            relief_request_id=73,
            request_no="RQ00073",
            requesting_tenant_id=30,
            requesting_agency_id=503,
            beneficiary_tenant_id=30,
            beneficiary_agency_id=503,
            origin_mode="SELF",
            event_id=12,
            request_date=date(2026, 3, 26),
            urgency_code="H",
            status_code=REQUEST_STATUS_APPROVED_FOR_FULFILLMENT,
            create_by_id="tester",
            update_by_id="tester",
        )
        OperationsEligibilityDecision.objects.create(
            relief_request_id=73,
            decision_code="APPROVED",
            decided_by_user_id="other-reviewer",
            decided_by_role_code=ELIGIBILITY_ROLE_CODES[0],
            decided_at=timezone.now(),
        )

        result = contract_services.list_eligibility_queue(
            actor_id="eligibility-1",
            actor_roles=[ELIGIBILITY_ROLE_CODES[0]],
            tenant_context=self.dispatch_ready_context,
        )

        self.assertEqual(result["results"], [])

    def test_eligibility_queue_rejects_non_eligibility_roles(self) -> None:
        with self.assertRaises(OperationValidationError) as raised:
            contract_services.list_eligibility_queue(
                actor_id="logistics-1",
                actor_roles=[ROLE_LOGISTICS_OFFICER],
                tenant_context=self.dispatch_ready_context,
            )

        self.assertEqual(
            raised.exception.errors,
            {"roles": "Only eligibility approvers may view this queue."},
        )

    @patch(
        "operations.contract_services._request_summary_payload",
        side_effect=lambda request, request_record: {
            "reliefrqst_id": int(request.reliefrqst_id),
            "status_code": request_record.status_code,
        },
    )
    @patch("operations.contract_services.ReliefRqst.objects.filter")
    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._load_request")
    def test_eligibility_queue_returns_only_requests_awaiting_action(
        self,
        load_request_mock,
        get_agency_scope_mock,
        relief_request_filter_mock,
        _request_summary_payload_mock,
    ) -> None:
        awaiting_request = self._request_stub(
            reliefrqst_id=70,
            agency_id=501,
            status_code=contract_services.legacy_service.STATUS_AWAITING_APPROVAL,
        )
        approved_request = self._request_stub(
            reliefrqst_id=71,
            agency_id=502,
            status_code=contract_services.legacy_service.STATUS_SUBMITTED,
        )
        rejected_request = self._request_stub(
            reliefrqst_id=72,
            agency_id=503,
            status_code=contract_services.legacy_service.STATUS_DENIED,
        )
        ineligible_request = self._request_stub(
            reliefrqst_id=73,
            agency_id=504,
            status_code=contract_services.legacy_service.STATUS_INELIGIBLE,
        )
        load_request_mock.side_effect = lambda reliefrqst_id, **kwargs: {
            70: awaiting_request,
            71: approved_request,
            72: rejected_request,
            73: ineligible_request,
        }[int(reliefrqst_id)]
        get_agency_scope_mock.side_effect = lambda agency_id: {
            501: self._agency_scope_for(501, 20, "FFP"),
            502: self._agency_scope_for(502, 30, "OUT-30"),
            503: self._agency_scope_for(503, 30, "OUT-30"),
            504: self._agency_scope_for(504, 30, "OUT-30"),
        }[int(agency_id)]
        relief_request_filter_mock.return_value.order_by.return_value.iterator.return_value = []

        OperationsReliefRequest.objects.create(
            relief_request_id=70,
            request_no="RQ00070",
            requesting_tenant_id=20,
            requesting_agency_id=501,
            beneficiary_tenant_id=20,
            beneficiary_agency_id=501,
            origin_mode="SELF",
            event_id=12,
            request_date=date(2026, 3, 26),
            urgency_code="H",
            status_code=REQUEST_STATUS_UNDER_ELIGIBILITY_REVIEW,
            create_by_id="tester",
            update_by_id="tester",
        )
        OperationsQueueAssignment.objects.create(
            queue_code=QUEUE_CODE_ELIGIBILITY,
            entity_type="RELIEF_REQUEST",
            entity_id=70,
            assigned_role_code=ELIGIBILITY_ROLE_CODES[0],
            assignment_status="OPEN",
        )

        OperationsReliefRequest.objects.create(
            relief_request_id=71,
            request_no="RQ00071",
            requesting_tenant_id=30,
            requesting_agency_id=502,
            beneficiary_tenant_id=30,
            beneficiary_agency_id=502,
            origin_mode="SELF",
            event_id=12,
            request_date=date(2026, 3, 26),
            urgency_code="H",
            status_code=REQUEST_STATUS_APPROVED_FOR_FULFILLMENT,
            create_by_id="tester",
            update_by_id="tester",
        )
        OperationsEligibilityDecision.objects.create(
            relief_request_id=71,
            decision_code="APPROVED",
            decided_by_user_id="eligibility-1",
            decided_by_role_code=ELIGIBILITY_ROLE_CODES[0],
            decided_at=timezone.now(),
        )
        OperationsQueueAssignment.objects.create(
            queue_code=QUEUE_CODE_ELIGIBILITY,
            entity_type="RELIEF_REQUEST",
            entity_id=71,
            assigned_role_code=ELIGIBILITY_ROLE_CODES[0],
            assignment_status="COMPLETED",
        )

        OperationsReliefRequest.objects.create(
            relief_request_id=72,
            request_no="RQ00072",
            requesting_tenant_id=30,
            requesting_agency_id=503,
            beneficiary_tenant_id=30,
            beneficiary_agency_id=503,
            origin_mode="SELF",
            event_id=12,
            request_date=date(2026, 3, 26),
            urgency_code="H",
            status_code=REQUEST_STATUS_REJECTED,
            create_by_id="tester",
            update_by_id="tester",
        )
        OperationsEligibilityDecision.objects.create(
            relief_request_id=72,
            decision_code="REJECTED",
            decision_reason="Outside current scope",
            decided_by_user_id="eligibility-1",
            decided_by_role_code=ELIGIBILITY_ROLE_CODES[0],
            decided_at=timezone.now(),
        )
        OperationsQueueAssignment.objects.create(
            queue_code=QUEUE_CODE_ELIGIBILITY,
            entity_type="RELIEF_REQUEST",
            entity_id=72,
            assigned_role_code=ELIGIBILITY_ROLE_CODES[0],
            assignment_status="COMPLETED",
        )

        OperationsReliefRequest.objects.create(
            relief_request_id=73,
            request_no="RQ00073",
            requesting_tenant_id=30,
            requesting_agency_id=504,
            beneficiary_tenant_id=30,
            beneficiary_agency_id=504,
            origin_mode="SELF",
            event_id=12,
            request_date=date(2026, 3, 26),
            urgency_code="H",
            status_code=REQUEST_STATUS_INELIGIBLE,
            create_by_id="tester",
            update_by_id="tester",
        )
        OperationsEligibilityDecision.objects.create(
            relief_request_id=73,
            decision_code="INELIGIBLE",
            decision_reason="Insufficient justification",
            decided_by_user_id="eligibility-1",
            decided_by_role_code=ELIGIBILITY_ROLE_CODES[0],
            decided_at=timezone.now(),
        )
        OperationsQueueAssignment.objects.create(
            queue_code=QUEUE_CODE_ELIGIBILITY,
            entity_type="RELIEF_REQUEST",
            entity_id=73,
            assigned_role_code=ELIGIBILITY_ROLE_CODES[0],
            assignment_status="COMPLETED",
        )

        result = contract_services.list_eligibility_queue(
            actor_id="eligibility-1",
            actor_roles=[ELIGIBILITY_ROLE_CODES[0]],
            tenant_context=self.dispatch_ready_context,
        )

        self.assertEqual([row["reliefrqst_id"] for row in result["results"]], [70])

    @patch("operations.contract_services._ensure_request_access")
    @patch("operations.contract_services._sync_operations_request")
    @patch("operations.contract_services.legacy_service._load_request")
    def test_submit_eligibility_decision_rejects_invalid_requesting_agency_id(
        self,
        load_request_mock,
        sync_request_mock,
        _ensure_request_access_mock,
    ) -> None:
        request = self._request_stub(reliefrqst_id=70, agency_id=501, status_code=1)
        request.review_by_id = None
        request.review_dtime = None
        request.action_by_id = None
        request.action_dtime = None
        request.status_reason_desc = None
        request.version_nbr = 1
        request.save = Mock()
        load_request_mock.return_value = request
        sync_request_mock.return_value = SimpleNamespace(
            relief_request_id=70,
            beneficiary_tenant_id=20,
            reviewed_by_id=None,
            reviewed_at=None,
            save=Mock(),
        )

        with self.assertRaises(OperationValidationError) as raised:
            contract_services.submit_eligibility_decision(
                70,
                payload={"decision": "APPROVED", "requesting_agency_id": "bad-id"},
                actor_id="eligibility-1",
                actor_roles=[ELIGIBILITY_ROLE_CODES[0]],
                tenant_context=self.dispatch_ready_context,
                idempotency_key="eligibility-70-invalid",
            )

        self.assertEqual(
            raised.exception.errors,
            {"requesting_agency_id": "invalid requesting_agency_id: 'bad-id'"},
        )
        request.save.assert_not_called()
        self.assertFalse(OperationsEligibilityDecision.objects.filter(relief_request_id=70).exists())

    @patch(
        "operations.contract_services._request_summary_payload",
        side_effect=lambda request, request_record: {
            "reliefrqst_id": int(request.reliefrqst_id),
            "status_code": request_record.status_code,
        },
    )
    @patch("operations.contract_services.ReliefPkg.objects.filter")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service.get_request")
    @override_settings(ODPEM_TENANT_ID=27)
    def test_submit_eligibility_decision_returns_payload_for_cross_tenant_queue_assignee(
        self,
        get_request_mock,
        load_request_mock,
        filter_packages_mock,
        _request_summary_payload_mock,
    ) -> None:
        get_request_mock.return_value = {
            "reliefrqst_id": 95009,
            "items": [],
            "packages": [],
        }
        filter_packages_mock.return_value.order_by.return_value = []
        request = self._request_stub(
            reliefrqst_id=95009,
            agency_id=501,
            status_code=contract_services.legacy_service.STATUS_AWAITING_APPROVAL,
        )
        request.review_by_id = None
        request.review_dtime = None
        request.action_by_id = None
        request.action_dtime = None
        request.status_reason_desc = None
        request.version_nbr = 1
        request.save = Mock()
        load_request_mock.return_value = request
        OperationsReliefRequest.objects.create(
            relief_request_id=95009,
            request_no="RQ95009",
            requesting_tenant_id=19,
            requesting_agency_id=401,
            beneficiary_tenant_id=19,
            beneficiary_agency_id=501,
            origin_mode="SELF",
            event_id=12,
            request_date=date(2026, 3, 26),
            urgency_code="H",
            status_code=REQUEST_STATUS_UNDER_ELIGIBILITY_REVIEW,
            submitted_by_id="relief_jrc_requester_tst",
            submitted_at=timezone.now(),
            create_by_id="tester",
            update_by_id="tester",
        )
        OperationsQueueAssignment.objects.create(
            queue_code=QUEUE_CODE_ELIGIBILITY,
            entity_type="RELIEF_REQUEST",
            entity_id=95009,
            assigned_role_code=ELIGIBILITY_ROLE_CODES[0],
            assignment_status="OPEN",
        )

        result = contract_services.submit_eligibility_decision(
            95009,
            payload={"decision": "APPROVED"},
            actor_id="andrea_tst",
            actor_roles=[ELIGIBILITY_ROLE_CODES[0]],
            tenant_context=self.odpem_context,
            idempotency_key="eligibility-95009",
        )

        self.assertEqual(result["status_code"], REQUEST_STATUS_APPROVED_FOR_FULFILLMENT)
        self.assertTrue(result["decision_made"])
        self.assertFalse(result["can_edit"])
        self.assertEqual(result["eligibility_decision"]["decision_code"], "APPROVED")
        self.assertEqual(
            request.status_code,
            contract_services.legacy_service.STATUS_SUBMITTED,
        )
        self.assertEqual(request.review_by_id, "andrea_tst")
        self.assertIsNotNone(request.review_dtime)
        self.assertIsNone(request.action_by_id)
        self.assertIsNone(request.action_dtime)
        request.save.assert_called_once()
        self.assertEqual(
            set(request.save.call_args.kwargs["update_fields"]),
            {
                "review_by_id",
                "review_dtime",
                "action_by_id",
                "action_dtime",
                "status_code",
                "status_reason_desc",
                "version_nbr",
            },
        )
        self.assertEqual(
            OperationsEligibilityDecision.objects.get(relief_request_id=95009).decision_code,
            "APPROVED",
        )
        self.assertEqual(
            OperationsQueueAssignment.objects.get(
                queue_code=QUEUE_CODE_ELIGIBILITY,
                entity_type="RELIEF_REQUEST",
                entity_id=95009,
            ).assignment_status,
            "COMPLETED",
        )
        fulfillment_assignment = OperationsQueueAssignment.objects.get(
            queue_code=contract_services.QUEUE_CODE_FULFILLMENT,
            entity_type="RELIEF_REQUEST",
            entity_id=95009,
            assigned_role_code=contract_services.FULFILLMENT_ROLE_CODES[0],
        )
        self.assertEqual(fulfillment_assignment.assigned_tenant_id, 27)
        self.assertEqual(
            OperationsNotification.objects.get(
                queue_code=contract_services.QUEUE_CODE_FULFILLMENT,
                entity_type="RELIEF_REQUEST",
                entity_id=95009,
                recipient_role_code=contract_services.FULFILLMENT_ROLE_CODES[0],
            ).recipient_tenant_id,
            27,
        )

    @patch(
        "operations.contract_services._request_summary_payload",
        side_effect=lambda request, request_record: {
            "reliefrqst_id": int(request.reliefrqst_id),
            "status_code": request_record.status_code,
        },
    )
    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.ReliefPkg.objects.filter")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service.get_request")
    @override_settings(ODPEM_TENANT_ID=27)
    def test_submit_eligibility_decision_reuses_cached_response_for_same_idempotency_key(
        self,
        get_request_mock,
        load_request_mock,
        filter_packages_mock,
        get_agency_scope_mock,
        _request_summary_payload_mock,
    ) -> None:
        get_request_mock.return_value = {
            "reliefrqst_id": 95009,
            "items": [],
            "packages": [],
        }
        get_agency_scope_mock.return_value = self.agency_scope
        filter_packages_mock.return_value.order_by.return_value = []
        request = self._request_stub(
            reliefrqst_id=95009,
            agency_id=501,
            status_code=contract_services.legacy_service.STATUS_AWAITING_APPROVAL,
        )
        request.review_by_id = None
        request.review_dtime = None
        request.action_by_id = None
        request.action_dtime = None
        request.status_reason_desc = None
        request.version_nbr = 1
        request.save = Mock()
        load_request_mock.return_value = request
        OperationsReliefRequest.objects.create(
            relief_request_id=95009,
            request_no="RQ95009",
            requesting_tenant_id=19,
            requesting_agency_id=401,
            beneficiary_tenant_id=19,
            beneficiary_agency_id=501,
            origin_mode="SELF",
            event_id=12,
            request_date=date(2026, 3, 26),
            urgency_code="H",
            status_code=REQUEST_STATUS_UNDER_ELIGIBILITY_REVIEW,
            submitted_by_id="relief_jrc_requester_tst",
            submitted_at=timezone.now(),
            create_by_id="tester",
            update_by_id="tester",
        )
        OperationsQueueAssignment.objects.create(
            queue_code=QUEUE_CODE_ELIGIBILITY,
            entity_type="RELIEF_REQUEST",
            entity_id=95009,
            assigned_role_code=ELIGIBILITY_ROLE_CODES[0],
            assignment_status="OPEN",
        )

        with self.captureOnCommitCallbacks(execute=True):
            first = contract_services.submit_eligibility_decision(
                95009,
                payload={"decision": "APPROVED"},
                actor_id="andrea_tst",
                actor_roles=[ELIGIBILITY_ROLE_CODES[0]],
                tenant_context=self.odpem_context,
                idempotency_key="eligibility-95009",
            )
        decision_count = OperationsEligibilityDecision.objects.filter(relief_request_id=95009).count()
        second = contract_services.submit_eligibility_decision(
            95009,
            payload={"decision": "APPROVED"},
            actor_id="andrea_tst",
            actor_roles=[ELIGIBILITY_ROLE_CODES[0]],
            tenant_context=self.odpem_context,
            idempotency_key="eligibility-95009",
        )

        self.assertEqual(first, second)
        self.assertEqual(load_request_mock.call_count, 1)
        self.assertEqual(
            OperationsEligibilityDecision.objects.filter(relief_request_id=95009).count(),
            decision_count,
        )

    @patch(
        "operations.contract_services._request_summary_payload",
        side_effect=lambda request, request_record: {
            "reliefrqst_id": int(request.reliefrqst_id),
            "status_code": request_record.status_code,
        },
    )
    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.ReliefPkg.objects.filter")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service.get_request")
    @override_settings(ODPEM_TENANT_ID=27)
    def test_submit_eligibility_decision_idempotency_cache_is_tenant_scoped(
        self,
        get_request_mock,
        load_request_mock,
        filter_packages_mock,
        get_agency_scope_mock,
        _request_summary_payload_mock,
    ) -> None:
        get_request_mock.return_value = {
            "reliefrqst_id": 95009,
            "items": [],
            "packages": [],
        }
        get_agency_scope_mock.return_value = self.agency_scope
        filter_packages_mock.return_value.order_by.return_value = []
        request = self._request_stub(
            reliefrqst_id=95009,
            agency_id=501,
            status_code=contract_services.legacy_service.STATUS_AWAITING_APPROVAL,
        )
        request.review_by_id = None
        request.review_dtime = None
        request.action_by_id = None
        request.action_dtime = None
        request.status_reason_desc = None
        request.version_nbr = 1
        request.save = Mock()
        load_request_mock.return_value = request
        OperationsReliefRequest.objects.create(
            relief_request_id=95009,
            request_no="RQ95009",
            requesting_tenant_id=19,
            requesting_agency_id=401,
            beneficiary_tenant_id=19,
            beneficiary_agency_id=501,
            origin_mode="SELF",
            event_id=12,
            request_date=date(2026, 3, 26),
            urgency_code="H",
            status_code=REQUEST_STATUS_UNDER_ELIGIBILITY_REVIEW,
            submitted_by_id="relief_jrc_requester_tst",
            submitted_at=timezone.now(),
            create_by_id="tester",
            update_by_id="tester",
        )
        OperationsQueueAssignment.objects.create(
            queue_code=QUEUE_CODE_ELIGIBILITY,
            entity_type="RELIEF_REQUEST",
            entity_id=95009,
            assigned_role_code=ELIGIBILITY_ROLE_CODES[0],
            assignment_status="OPEN",
        )
        foreign_tenant_context = _tenant_context(
            tenant_id=999,
            tenant_code="OTHER-TENANT",
            tenant_type="EXTERNAL",
        )

        with self.captureOnCommitCallbacks(execute=True):
            first = contract_services.submit_eligibility_decision(
                95009,
                payload={"decision": "APPROVED"},
                actor_id="andrea_tst",
                actor_roles=[ELIGIBILITY_ROLE_CODES[0]],
                tenant_context=self.odpem_context,
                idempotency_key="eligibility-95009",
            )

        with self.assertRaises(OperationValidationError) as raised:
            contract_services.submit_eligibility_decision(
                95009,
                payload={"decision": "APPROVED"},
                actor_id="andrea_tst",
                actor_roles=[ELIGIBILITY_ROLE_CODES[0]],
                tenant_context=foreign_tenant_context,
                idempotency_key="eligibility-95009",
            )

        self.assertEqual(
            raised.exception.errors,
            {"scope": "Request is outside the active tenant or workflow assignment scope."},
        )
        self.assertEqual(first["reliefrqst_id"], 95009)
        self.assertEqual(load_request_mock.call_count, 2)
        self.assertEqual(
            OperationsEligibilityDecision.objects.filter(relief_request_id=95009).count(),
            1,
        )

    @patch("operations.contract_services.cache.set")
    @patch(
        "operations.contract_services._request_summary_payload",
        side_effect=lambda request, request_record: {
            "reliefrqst_id": int(request.reliefrqst_id),
            "status_code": request_record.status_code,
        },
    )
    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.ReliefPkg.objects.filter")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service.get_request")
    @override_settings(ODPEM_TENANT_ID=27)
    def test_submit_eligibility_decision_defers_idempotency_cache_until_commit(
        self,
        get_request_mock,
        load_request_mock,
        filter_packages_mock,
        get_agency_scope_mock,
        _request_summary_payload_mock,
        cache_set_mock,
    ) -> None:
        get_request_mock.return_value = {
            "reliefrqst_id": 95009,
            "items": [],
            "packages": [],
        }
        get_agency_scope_mock.return_value = self.agency_scope
        filter_packages_mock.return_value.order_by.return_value = []
        request = self._request_stub(
            reliefrqst_id=95009,
            agency_id=501,
            status_code=contract_services.legacy_service.STATUS_AWAITING_APPROVAL,
        )
        request.review_by_id = None
        request.review_dtime = None
        request.action_by_id = None
        request.action_dtime = None
        request.status_reason_desc = None
        request.version_nbr = 1
        request.save = Mock()
        load_request_mock.return_value = request
        OperationsReliefRequest.objects.create(
            relief_request_id=95009,
            request_no="RQ95009",
            requesting_tenant_id=19,
            requesting_agency_id=401,
            beneficiary_tenant_id=19,
            beneficiary_agency_id=501,
            origin_mode="SELF",
            event_id=12,
            request_date=date(2026, 3, 26),
            urgency_code="H",
            status_code=REQUEST_STATUS_UNDER_ELIGIBILITY_REVIEW,
            submitted_by_id="relief_jrc_requester_tst",
            submitted_at=timezone.now(),
            create_by_id="tester",
            update_by_id="tester",
        )
        OperationsQueueAssignment.objects.create(
            queue_code=QUEUE_CODE_ELIGIBILITY,
            entity_type="RELIEF_REQUEST",
            entity_id=95009,
            assigned_role_code=ELIGIBILITY_ROLE_CODES[0],
            assignment_status="OPEN",
        )

        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            result = contract_services.submit_eligibility_decision(
                95009,
                payload={"decision": "APPROVED"},
                actor_id="andrea_tst",
                actor_roles=[ELIGIBILITY_ROLE_CODES[0]],
                tenant_context=self.odpem_context,
                idempotency_key="eligibility-95009",
            )

        cache_set_mock.assert_not_called()
        self.assertEqual(len(callbacks), 1)
        callbacks[0]()
        cache_set_mock.assert_called_once()
        args, kwargs = cache_set_mock.call_args
        self.assertTrue(args[0].startswith("operations:idempotency:eligibility_decision:andrea_tst:"))
        self.assertEqual(args[1], result)
        self.assertEqual(kwargs["timeout"], contract_services._IDEMPOTENCY_TTL_SECONDS)

    @patch(
        "operations.contract_services._request_summary_payload",
        side_effect=lambda request, request_record: {
            "reliefrqst_id": int(request.reliefrqst_id),
            "status_code": request_record.status_code,
        },
    )
    @patch("operations.contract_services.ReliefPkg.objects.filter")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service.get_request")
    def test_submit_eligibility_decision_rejected_sets_legacy_action_fields(
        self,
        get_request_mock,
        load_request_mock,
        filter_packages_mock,
        _request_summary_payload_mock,
    ) -> None:
        get_request_mock.return_value = {
            "reliefrqst_id": 70,
            "items": [],
            "packages": [],
        }
        filter_packages_mock.return_value.order_by.return_value = []
        request = self._request_stub(
            reliefrqst_id=70,
            agency_id=501,
            status_code=contract_services.legacy_service.STATUS_AWAITING_APPROVAL,
        )
        request.review_by_id = None
        request.review_dtime = None
        request.action_by_id = None
        request.action_dtime = None
        request.status_reason_desc = None
        request.version_nbr = 1
        request.save = Mock()
        load_request_mock.return_value = request
        OperationsReliefRequest.objects.create(
            relief_request_id=70,
            request_no="RQ00070",
            requesting_tenant_id=14,
            requesting_agency_id=401,
            beneficiary_tenant_id=20,
            beneficiary_agency_id=501,
            origin_mode="SELF",
            event_id=12,
            request_date=date(2026, 3, 26),
            urgency_code="H",
            status_code=REQUEST_STATUS_UNDER_ELIGIBILITY_REVIEW,
            submitted_by_id="requester-1",
            submitted_at=timezone.now(),
            create_by_id="tester",
            update_by_id="tester",
        )
        OperationsQueueAssignment.objects.create(
            queue_code=QUEUE_CODE_ELIGIBILITY,
            entity_type="RELIEF_REQUEST",
            entity_id=70,
            assigned_role_code=ELIGIBILITY_ROLE_CODES[0],
            assignment_status="OPEN",
        )

        result = contract_services.submit_eligibility_decision(
            70,
            payload={"decision": "REJECTED", "reason": "Outside current scope"},
            actor_id="eligibility-1",
            actor_roles=[ELIGIBILITY_ROLE_CODES[0]],
            tenant_context=_tenant_context(
                tenant_id=27,
                tenant_code="OFFICE-OF-DISASTER-P",
                tenant_type="NATIONAL",
                access_level="ADMIN",
            ),
            idempotency_key="eligibility-70-rejected",
        )

        self.assertEqual(result["status_code"], REQUEST_STATUS_REJECTED)
        self.assertEqual(request.status_code, contract_services.legacy_service.STATUS_DENIED)
        self.assertEqual(request.status_reason_desc, "Outside current scope")
        self.assertEqual(request.review_by_id, "eligibility-1")
        self.assertIsNotNone(request.review_dtime)
        self.assertEqual(request.action_by_id, "eligibility-1")
        self.assertIsNotNone(request.action_dtime)
        self.assertEqual(
            OperationsEligibilityDecision.objects.get(relief_request_id=70).decision_code,
            "REJECTED",
        )
        self.assertEqual(
            OperationsEligibilityDecision.objects.get(relief_request_id=70).decision_reason,
            "Outside current scope",
        )
        self.assertEqual(
            OperationsQueueAssignment.objects.get(
                queue_code=QUEUE_CODE_ELIGIBILITY,
                entity_type="RELIEF_REQUEST",
                entity_id=70,
            ).assignment_status,
            "COMPLETED",
        )

    @patch("operations.contract_services.legacy_service._load_request")
    def test_submit_eligibility_decision_requires_idempotency_key(self, load_request_mock) -> None:
        with self.assertRaises(OperationValidationError) as raised:
            contract_services.submit_eligibility_decision(
                70,
                payload={"decision": "APPROVED"},
                actor_id="eligibility-1",
                actor_roles=[ELIGIBILITY_ROLE_CODES[0]],
                tenant_context=self.dispatch_ready_context,
            )

        self.assertEqual(
            raised.exception.errors,
            {"idempotency_key": "Idempotency-Key header is required."},
        )
        load_request_mock.assert_not_called()

    @patch("operations.contract_services.ReliefRqst.objects.order_by")
    @patch("operations.contract_services._request_summary_payload", side_effect=lambda request, request_record: {"reliefrqst_id": int(request.reliefrqst_id)})
    @patch("operations.contract_services.operations_policy.get_agency_scope")
    def test_request_list_skips_out_of_scope_rows_without_syncing(
        self,
        get_agency_scope_mock,
        _request_summary_mock,
        order_by_mock,
    ) -> None:
        request_in_scope = self._request_stub(reliefrqst_id=82, agency_id=501, status_code=contract_services.legacy_service.STATUS_SUBMITTED)
        request_out_of_scope = self._request_stub(reliefrqst_id=83, agency_id=503, status_code=contract_services.legacy_service.STATUS_SUBMITTED)
        order_by_mock.return_value.iterator.return_value = [request_in_scope, request_out_of_scope]
        get_agency_scope_mock.side_effect = lambda agency_id: {
            501: self._agency_scope_for(501, 20, "FFP"),
            503: self._agency_scope_for(503, 30, "OUT-30"),
        }[int(agency_id)]

        result = contract_services.list_requests(
            actor_id="requester-1",
            actor_roles=["LOGISTICS_OFFICER"],
            tenant_context=self.dispatch_ready_context,
        )

        self.assertEqual([row["reliefrqst_id"] for row in result["results"]], [82])
        self.assertTrue(OperationsReliefRequest.objects.filter(relief_request_id=82).exists())
        self.assertFalse(OperationsReliefRequest.objects.filter(relief_request_id=83).exists())

    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch(
        "operations.contract_services.legacy_service._request_summary",
        return_value={"reliefrqst_id": 82, "status_code": "SUBMITTED"},
    )
    @patch("operations.contract_services.ReliefRqst.objects.order_by")
    def test_request_list_exposes_canonical_request_mode_and_tenant_context(
        self,
        order_by_mock,
        _request_summary_mock,
        get_agency_scope_mock,
    ) -> None:
        OperationsReliefRequest.objects.create(
            relief_request_id=82,
            request_no="RQ00082",
            requesting_tenant_id=30,
            requesting_agency_id=777,
            beneficiary_tenant_id=20,
            beneficiary_agency_id=501,
            origin_mode=ORIGIN_MODE_FOR_SUBORDINATE,
            event_id=12,
            request_date=date(2026, 3, 26),
            urgency_code="H",
            status_code=REQUEST_STATUS_UNDER_ELIGIBILITY_REVIEW,
            create_by_id="tester",
            update_by_id="tester",
        )
        order_by_mock.return_value.iterator.return_value = [
            self._request_stub(
                reliefrqst_id=82,
                agency_id=501,
                status_code=contract_services.legacy_service.STATUS_SUBMITTED,
            )
        ]
        get_agency_scope_mock.return_value = self.agency_scope

        result = contract_services.list_requests(
            actor_id="controller-1",
            actor_roles=[],
            tenant_context=_tenant_context(tenant_id=30, tenant_code="CTRL-30", tenant_type="PARISH"),
        )

        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["results"][0]["request_mode"], ORIGIN_MODE_FOR_SUBORDINATE)
        self.assertEqual(result["results"][0]["origin_mode"], ORIGIN_MODE_FOR_SUBORDINATE)
        self.assertEqual(result["results"][0]["requesting_tenant_id"], 30)
        self.assertEqual(result["results"][0]["requesting_agency_id"], 777)
        self.assertEqual(result["results"][0]["beneficiary_tenant_id"], 20)
        self.assertEqual(result["results"][0]["beneficiary_agency_id"], 501)

    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service.get_request")
    @patch("operations.contract_services.legacy_service._load_request")
    def test_get_request_rejects_out_of_scope_without_syncing(
        self,
        load_request_mock,
        get_request_mock,
        get_agency_scope_mock,
    ) -> None:
        load_request_mock.return_value = self._request_stub(reliefrqst_id=84, agency_id=503, status_code=contract_services.legacy_service.STATUS_SUBMITTED)
        get_agency_scope_mock.return_value = self._agency_scope_for(503, 30, "OUT-30")

        with self.assertRaises(OperationValidationError):
            contract_services.get_request(
                84,
                actor_id="requester-1",
                actor_roles=["LOGISTICS_OFFICER"],
                tenant_context=self.dispatch_ready_context,
            )

        get_request_mock.assert_not_called()
        self.assertFalse(OperationsReliefRequest.objects.filter(relief_request_id=84).exists())

    @patch("operations.contract_services._request_summary_payload", side_effect=lambda request, request_record: {"reliefrqst_id": int(request.reliefrqst_id), "requesting_tenant_id": request_record.requesting_tenant_id})
    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._current_package_for_request", return_value=None)
    @patch("operations.contract_services.legacy_service._load_request")
    def test_fulfillment_queue_includes_external_request_routed_to_odpem_scope(
        self,
        load_request_mock,
        _current_package_mock,
        get_agency_scope_mock,
        _request_summary_mock,
    ) -> None:
        OperationsReliefRequest.objects.create(
            relief_request_id=95009,
            request_no="RQ95009",
            requesting_tenant_id=19,
            requesting_agency_id=401,
            beneficiary_tenant_id=19,
            beneficiary_agency_id=501,
            origin_mode="SELF",
            event_id=12,
            request_date=date(2026, 3, 26),
            urgency_code="H",
            status_code=REQUEST_STATUS_APPROVED_FOR_FULFILLMENT,
            create_by_id="tester",
            update_by_id="tester",
        )
        OperationsQueueAssignment.objects.create(
            queue_code=QUEUE_CODE_FULFILLMENT,
            entity_type="RELIEF_REQUEST",
            entity_id=95009,
            assigned_role_code=ROLE_LOGISTICS_MANAGER,
            assigned_tenant_id=27,
            assignment_status="OPEN",
        )
        OperationsReliefRequest.objects.create(
            relief_request_id=71,
            request_no="RQ00071",
            requesting_tenant_id=30,
            requesting_agency_id=502,
            beneficiary_tenant_id=30,
            beneficiary_agency_id=502,
            origin_mode="SELF",
            event_id=12,
            request_date=date(2026, 3, 26),
            urgency_code="H",
            status_code=REQUEST_STATUS_APPROVED_FOR_FULFILLMENT,
            create_by_id="tester",
            update_by_id="tester",
        )
        requests = {
            95009: self._request_stub(reliefrqst_id=95009, agency_id=501, status_code=3),
            71: self._request_stub(reliefrqst_id=71, agency_id=502, status_code=3),
        }
        load_request_mock.side_effect = lambda reliefrqst_id: requests[int(reliefrqst_id)]
        get_agency_scope_mock.side_effect = lambda agency_id: {
            501: self._agency_scope_for(501, 19, "JRC"),
            502: self._agency_scope_for(502, 30, "OUT-30"),
        }[int(agency_id)]

        result = contract_services.list_packages(
            actor_id="kemar_tst",
            actor_roles=[ROLE_LOGISTICS_MANAGER],
            tenant_context=self.odpem_context,
        )

        self.assertEqual([row["reliefrqst_id"] for row in result["results"]], [95009])

    @patch("operations.contract_services._request_summary_payload", side_effect=lambda request, request_record: {"reliefrqst_id": int(request.reliefrqst_id)})
    @patch(
        "operations.contract_services._sync_operations_request",
        side_effect=lambda request, actor_id: SimpleNamespace(
            relief_request_id=int(request.reliefrqst_id),
            status_code=REQUEST_STATUS_APPROVED_FOR_FULFILLMENT,
            requesting_tenant_id=20,
            beneficiary_tenant_id=20,
            beneficiary_agency_id=501,
        ),
    )
    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.actor_queue_queryset")
    @patch("operations.contract_services.OperationsReliefRequest.objects.filter")
    @patch("operations.contract_services.legacy_service._current_package_for_request", return_value=None)
    @patch("operations.contract_services.legacy_service._load_request")
    def test_fulfillment_queue_prioritizes_actor_assigned_requests_before_status_fallback(
        self,
        load_request_mock,
        _current_package_mock,
        operations_request_filter_mock,
        actor_queue_queryset_mock,
        get_agency_scope_mock,
        _sync_request_mock,
        _request_summary_mock,
    ) -> None:
        actor_queue_queryset_mock.return_value.filter.return_value.values_list.return_value = [999]
        operations_request_filter_mock.return_value.order_by.return_value.values_list.return_value = list(range(1, 205))
        load_request_mock.side_effect = lambda reliefrqst_id: self._request_stub(
            reliefrqst_id=int(reliefrqst_id),
            agency_id=501,
            status_code=contract_services.legacy_service.STATUS_SUBMITTED,
        )
        get_agency_scope_mock.return_value = self._agency_scope_for(501, 20, "FFP")

        result = contract_services.list_packages(
            actor_id="logistics-1",
            actor_roles=["LOGISTICS_MANAGER"],
            tenant_context=self.dispatch_ready_context,
        )

        request_ids = [row["reliefrqst_id"] for row in result["results"]]
        self.assertEqual(request_ids[0], 999)
        self.assertEqual(len(request_ids), 200)
        self.assertIn(999, request_ids)
        self.assertNotIn(204, request_ids)

    @patch("operations.contract_services._request_summary_payload", side_effect=lambda request, request_record: {"reliefrqst_id": int(request.reliefrqst_id), "requesting_tenant_id": request_record.requesting_tenant_id})
    @patch(
        "operations.contract_services._sync_operations_request",
        side_effect=lambda request, actor_id: SimpleNamespace(
            relief_request_id=int(request.reliefrqst_id),
            status_code=REQUEST_STATUS_APPROVED_FOR_FULFILLMENT,
            requesting_tenant_id=20,
            beneficiary_tenant_id=20,
            beneficiary_agency_id=501,
        ),
    )
    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.actor_queue_queryset")
    @patch("operations.contract_services.OperationsReliefRequest.objects.filter")
    @patch("operations.contract_services.legacy_service._current_package_for_request", return_value=None)
    @patch("operations.contract_services.legacy_service._load_request")
    def test_fulfillment_queue_skips_missing_legacy_requests(
        self,
        load_request_mock,
        _current_package_mock,
        operations_request_filter_mock,
        actor_queue_queryset_mock,
        get_agency_scope_mock,
        _sync_request_mock,
        _request_summary_mock,
    ) -> None:
        actor_queue_queryset_mock.return_value.filter.return_value.values_list.return_value = []
        operations_request_filter_mock.return_value.order_by.return_value.values_list.return_value = [70, 71]

        def load_request_side_effect(reliefrqst_id: int):
            if int(reliefrqst_id) == 70:
                raise ReliefRqst.DoesNotExist
            return self._request_stub(
                reliefrqst_id=71,
                agency_id=501,
                status_code=contract_services.legacy_service.STATUS_SUBMITTED,
            )

        load_request_mock.side_effect = load_request_side_effect
        get_agency_scope_mock.return_value = self._agency_scope_for(501, 20, "FFP")

        result = contract_services.list_packages(
            actor_id="logistics-1",
            actor_roles=["LOGISTICS_MANAGER"],
            tenant_context=self.dispatch_ready_context,
        )

        self.assertEqual([row["reliefrqst_id"] for row in result["results"]], [71])
        self.assertIsNone(result["results"][0]["current_package"])

    def test_ensure_fulfillment_request_access_allows_odpem_assignment_for_external_request(self) -> None:
        request_record = OperationsReliefRequest.objects.create(
            relief_request_id=95009,
            request_no="RQ95009",
            requesting_tenant_id=19,
            requesting_agency_id=401,
            beneficiary_tenant_id=19,
            beneficiary_agency_id=501,
            origin_mode="SELF",
            event_id=12,
            request_date=date(2026, 3, 26),
            urgency_code="H",
            status_code=REQUEST_STATUS_APPROVED_FOR_FULFILLMENT,
            create_by_id="tester",
            update_by_id="tester",
        )
        OperationsQueueAssignment.objects.create(
            queue_code=QUEUE_CODE_FULFILLMENT,
            entity_type="RELIEF_REQUEST",
            entity_id=95009,
            assigned_role_code=ROLE_LOGISTICS_OFFICER,
            assigned_tenant_id=27,
            assignment_status="OPEN",
        )

        contract_services._ensure_fulfillment_request_access(
            request_record,
            actor_id="devon_tst",
            actor_roles=[ROLE_LOGISTICS_OFFICER],
            tenant_context=self.odpem_context,
        )

    def test_ensure_request_access_allows_system_administrator_cross_tenant(self) -> None:
        request_record = OperationsReliefRequest.objects.create(
            relief_request_id=95011,
            request_no="RQ95011",
            requesting_tenant_id=19,
            requesting_agency_id=401,
            beneficiary_tenant_id=19,
            beneficiary_agency_id=501,
            origin_mode="SELF",
            event_id=12,
            request_date=date(2026, 3, 26),
            urgency_code="H",
            status_code=REQUEST_STATUS_UNDER_ELIGIBILITY_REVIEW,
            create_by_id="tester",
            update_by_id="tester",
        )

        contract_services._ensure_request_access(
            request_record,
            actor_id="local_system_admin_tst",
            actor_roles=[ROLE_SYSTEM_ADMINISTRATOR],
            tenant_context=self.odpem_context,
            write=True,
        )

    @patch("operations.contract_services._request_summary_payload", side_effect=lambda request, request_record: {"reliefrqst_id": int(request.reliefrqst_id), "requesting_tenant_id": request_record.requesting_tenant_id})
    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._current_package_for_request", return_value=None)
    @patch("operations.contract_services.legacy_service._load_request")
    def test_fulfillment_queue_excludes_unrelated_role_assignment_outside_tenant_scope(
        self,
        load_request_mock,
        _current_package_mock,
        get_agency_scope_mock,
        _request_summary_mock,
    ) -> None:
        OperationsReliefRequest.objects.create(
            relief_request_id=70,
            request_no="RQ00070",
            requesting_tenant_id=14,
            requesting_agency_id=401,
            beneficiary_tenant_id=20,
            beneficiary_agency_id=501,
            origin_mode="SELF",
            event_id=12,
            request_date=date(2026, 3, 26),
            urgency_code="H",
            status_code=REQUEST_STATUS_APPROVED_FOR_FULFILLMENT,
            create_by_id="tester",
            update_by_id="tester",
        )
        OperationsQueueAssignment.objects.create(
            queue_code=QUEUE_CODE_FULFILLMENT,
            entity_type="RELIEF_REQUEST",
            entity_id=70,
            assigned_role_code="LOGISTICS_OFFICER",
            assigned_tenant_id=27,
            assignment_status="OPEN",
        )
        load_request_mock.return_value = self._request_stub(reliefrqst_id=70, agency_id=501, status_code=3)
        get_agency_scope_mock.return_value = self._agency_scope_for(501, 20, "FFP")

        result = contract_services.list_packages(
            actor_id="logistics-1",
            actor_roles=["LOGISTICS_MANAGER"],
            tenant_context=_tenant_context(
                tenant_id=27,
                tenant_code="OFFICE-OF-DISASTER-P",
                tenant_type="NATIONAL",
                access_level="ADMIN",
            ),
        )

        self.assertEqual(result["results"], [])

    @patch("operations.contract_services.legacy_service._current_package_for_request", return_value=None)
    @patch("operations.contract_services.legacy_service._request_items", return_value=[])
    @patch("operations.contract_services._request_summary_payload", side_effect=lambda request, request_record: {"reliefrqst_id": int(request.reliefrqst_id), "status_code": request_record.status_code})
    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services._sync_operations_request")
    @patch("operations.contract_services.legacy_service._load_request")
    def test_get_package_rejects_unrelated_role_assignment_outside_tenant_scope(
        self,
        load_request_mock,
        sync_request_mock,
        get_agency_scope_mock,
        _request_summary_mock,
        _request_items_mock,
        _current_package_mock,
    ) -> None:
        OperationsReliefRequest.objects.create(
            relief_request_id=70,
            request_no="RQ00070",
            requesting_tenant_id=14,
            requesting_agency_id=401,
            beneficiary_tenant_id=20,
            beneficiary_agency_id=501,
            origin_mode="SELF",
            event_id=12,
            request_date=date(2026, 3, 26),
            urgency_code="H",
            status_code=REQUEST_STATUS_APPROVED_FOR_FULFILLMENT,
            create_by_id="tester",
            update_by_id="tester",
        )
        OperationsQueueAssignment.objects.create(
            queue_code=QUEUE_CODE_FULFILLMENT,
            entity_type="RELIEF_REQUEST",
            entity_id=70,
            assigned_role_code="LOGISTICS_OFFICER",
            assigned_tenant_id=27,
            assignment_status="OPEN",
        )
        load_request_mock.return_value = self._request_stub(reliefrqst_id=70, agency_id=501, status_code=3)
        get_agency_scope_mock.return_value = self._agency_scope_for(501, 20, "FFP")

        with self.assertRaises(OperationValidationError):
            contract_services.get_package(
                70,
                actor_id="logistics-1",
                actor_roles=["LOGISTICS_MANAGER"],
                tenant_context=_tenant_context(
                    tenant_id=27,
                    tenant_code="OFFICE-OF-DISASTER-P",
                    tenant_type="NATIONAL",
                    access_level="ADMIN",
                ),
            )
        sync_request_mock.assert_not_called()

    @patch("operations.contract_services.legacy_service._current_package_for_request", return_value=None)
    @patch("operations.contract_services.legacy_service._request_items", return_value=[])
    @patch("operations.contract_services._request_summary_payload", side_effect=lambda request, request_record: {"reliefrqst_id": int(request.reliefrqst_id), "status_code": request_record.status_code})
    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._load_request")
    def test_get_package_rejects_same_tenant_non_fulfillment_roles(
        self,
        load_request_mock,
        get_agency_scope_mock,
        _request_summary_mock,
        _request_items_mock,
        _current_package_mock,
    ) -> None:
        OperationsReliefRequest.objects.create(
            relief_request_id=95009,
            request_no="RQ95009",
            requesting_tenant_id=19,
            requesting_agency_id=401,
            beneficiary_tenant_id=19,
            beneficiary_agency_id=501,
            origin_mode="SELF",
            event_id=12,
            request_date=date(2026, 3, 26),
            urgency_code="H",
            status_code=REQUEST_STATUS_APPROVED_FOR_FULFILLMENT,
            create_by_id="tester",
            update_by_id="tester",
        )
        OperationsQueueAssignment.objects.create(
            queue_code=QUEUE_CODE_FULFILLMENT,
            entity_type="RELIEF_REQUEST",
            entity_id=95009,
            assigned_role_code=ROLE_LOGISTICS_MANAGER,
            assigned_tenant_id=27,
            assignment_status="OPEN",
        )
        load_request_mock.return_value = self._request_stub(reliefrqst_id=95009, agency_id=501, status_code=3)
        get_agency_scope_mock.return_value = self._agency_scope_for(501, 19, "JRC")

        with self.assertRaises(OperationValidationError):
            contract_services.get_package(
                95009,
                actor_id="relief_jrc_requester_tst",
                actor_roles=[ELIGIBILITY_ROLE_CODES[0]],
                tenant_context=_tenant_context(tenant_id=19, tenant_code="JRC", tenant_type="EXTERNAL"),
            )

    @patch("operations.contract_services._request_summary_payload", side_effect=lambda request, request_record: {"reliefrqst_id": int(request.reliefrqst_id), "requesting_tenant_id": request_record.requesting_tenant_id})
    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._current_package_for_request", return_value=None)
    @patch("operations.contract_services.legacy_service._load_request")
    def test_system_administrator_can_view_package_queue_for_accessible_tenant_scope(
        self,
        load_request_mock,
        _current_package_mock,
        get_agency_scope_mock,
        _request_summary_mock,
    ) -> None:
        OperationsReliefRequest.objects.create(
            relief_request_id=70,
            request_no="RQ00070",
            requesting_tenant_id=20,
            requesting_agency_id=501,
            beneficiary_tenant_id=20,
            beneficiary_agency_id=501,
            origin_mode="SELF",
            event_id=12,
            request_date=date(2026, 3, 26),
            urgency_code="H",
            status_code=REQUEST_STATUS_APPROVED_FOR_FULFILLMENT,
            create_by_id="tester",
            update_by_id="tester",
        )
        load_request_mock.return_value = self._request_stub(reliefrqst_id=70, agency_id=501, status_code=3)
        get_agency_scope_mock.return_value = self._agency_scope_for(501, 20, "FFP")

        result = contract_services.list_packages(
            actor_id="system-admin-1",
            actor_roles=[ROLE_SYSTEM_ADMINISTRATOR],
            tenant_context=self.dispatch_ready_context,
        )

        self.assertEqual([row["reliefrqst_id"] for row in result["results"]], [70])

    @patch(
        "operations.contract_services._request_summary_payload",
        side_effect=lambda request, request_record: {
            "reliefrqst_id": int(request.reliefrqst_id),
            "status_code": request_record.status_code,
        },
    )
    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._current_package_for_request", return_value=None)
    @patch("operations.contract_services.legacy_service._load_request")
    def test_fulfillment_queue_excludes_fulfilled_requests_from_active_work_queue(
        self,
        load_request_mock,
        _current_package_mock,
        get_agency_scope_mock,
        _request_summary_mock,
    ) -> None:
        OperationsReliefRequest.objects.create(
            relief_request_id=70,
            request_no="RQ00070",
            requesting_tenant_id=20,
            requesting_agency_id=501,
            beneficiary_tenant_id=20,
            beneficiary_agency_id=501,
            origin_mode="SELF",
            event_id=12,
            request_date=date(2026, 3, 26),
            urgency_code="H",
            status_code=REQUEST_STATUS_FULFILLED,
            create_by_id="tester",
            update_by_id="tester",
        )
        load_request_mock.return_value = self._request_stub(
            reliefrqst_id=70,
            agency_id=501,
            status_code=contract_services.legacy_service.STATUS_FILLED,
        )
        get_agency_scope_mock.return_value = self._agency_scope_for(501, 20, "FFP")

        result = contract_services.list_packages(
            actor_id="logistics-1",
            actor_roles=["LOGISTICS_OFFICER"],
            tenant_context=self.dispatch_ready_context,
        )

        self.assertEqual(result["results"], [])

    @patch(
        "operations.contract_services._request_summary_payload",
        side_effect=lambda request, request_record: {
            "reliefrqst_id": int(request.reliefrqst_id),
            "status_code": request_record.status_code,
        },
    )
    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._current_package_for_request", return_value=None)
    @patch("operations.contract_services.legacy_service._load_request")
    def test_fulfillment_queue_includes_active_approved_requests(
        self,
        load_request_mock,
        _current_package_mock,
        get_agency_scope_mock,
        _request_summary_mock,
    ) -> None:
        OperationsReliefRequest.objects.create(
            relief_request_id=70,
            request_no="RQ00070",
            requesting_tenant_id=20,
            requesting_agency_id=501,
            beneficiary_tenant_id=20,
            beneficiary_agency_id=501,
            origin_mode="SELF",
            event_id=12,
            request_date=date(2026, 3, 26),
            urgency_code="H",
            status_code=REQUEST_STATUS_APPROVED_FOR_FULFILLMENT,
            create_by_id="tester",
            update_by_id="tester",
        )
        load_request_mock.return_value = self._request_stub(
            reliefrqst_id=70,
            agency_id=501,
            status_code=contract_services.legacy_service.STATUS_SUBMITTED,
        )
        get_agency_scope_mock.return_value = self.agency_scope

        result = contract_services.list_packages(
            actor_id="logistics-1",
            actor_roles=["LOGISTICS_OFFICER"],
            tenant_context=self.dispatch_ready_context,
        )

        self.assertEqual(
            result["results"],
            [{"reliefrqst_id": 70, "status_code": REQUEST_STATUS_APPROVED_FOR_FULFILLMENT, "current_package": None}],
        )

    @patch(
        "operations.contract_services._request_summary_payload",
        side_effect=lambda request, request_record: {
            "reliefrqst_id": int(request.reliefrqst_id),
            "status_code": request_record.status_code,
        },
    )
    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._current_package_for_request", return_value=None)
    @patch("operations.contract_services.legacy_service._load_request")
    def test_fulfillment_queue_backfills_active_rows_after_stale_fulfilled_assignments(
        self,
        load_request_mock,
        _current_package_mock,
        get_agency_scope_mock,
        _request_summary_mock,
    ) -> None:
        request_map: dict[int, SimpleNamespace] = {}
        active_request_id = 70
        OperationsReliefRequest.objects.create(
            relief_request_id=active_request_id,
            request_no="RQ00070",
            requesting_tenant_id=20,
            requesting_agency_id=501,
            beneficiary_tenant_id=20,
            beneficiary_agency_id=501,
            origin_mode="SELF",
            event_id=12,
            request_date=date(2026, 1, 1),
            urgency_code="H",
            status_code=REQUEST_STATUS_APPROVED_FOR_FULFILLMENT,
            create_by_id="tester",
            update_by_id="tester",
        )
        OperationsQueueAssignment.objects.create(
            queue_code=QUEUE_CODE_FULFILLMENT,
            entity_type="RELIEF_REQUEST",
            entity_id=active_request_id,
            assigned_role_code=ROLE_LOGISTICS_OFFICER,
            assigned_tenant_id=20,
            assignment_status="OPEN",
        )
        request_map[active_request_id] = self._request_stub(
            reliefrqst_id=active_request_id,
            agency_id=501,
            status_code=contract_services.legacy_service.STATUS_SUBMITTED,
        )

        for offset in range(205):
            reliefrqst_id = 1000 + offset
            OperationsReliefRequest.objects.create(
                relief_request_id=reliefrqst_id,
                request_no=f"RQ{reliefrqst_id:05d}",
                requesting_tenant_id=20,
                requesting_agency_id=501,
                beneficiary_tenant_id=20,
                beneficiary_agency_id=501,
                origin_mode="SELF",
                event_id=12,
                request_date=date(2026, 3, 1),
                urgency_code="H",
                status_code=REQUEST_STATUS_FULFILLED,
                create_by_id="tester",
                update_by_id="tester",
            )
            OperationsQueueAssignment.objects.create(
                queue_code=QUEUE_CODE_FULFILLMENT,
                entity_type="RELIEF_REQUEST",
                entity_id=reliefrqst_id,
                assigned_role_code=ROLE_LOGISTICS_OFFICER,
                assigned_tenant_id=20,
                assignment_status="OPEN",
            )
            request_map[reliefrqst_id] = self._request_stub(
                reliefrqst_id=reliefrqst_id,
                agency_id=501,
                status_code=contract_services.legacy_service.STATUS_FILLED,
            )

        load_request_mock.side_effect = lambda reliefrqst_id: request_map[int(reliefrqst_id)]
        get_agency_scope_mock.return_value = self.agency_scope

        result = contract_services.list_packages(
            actor_id="logistics-1",
            actor_roles=["LOGISTICS_OFFICER"],
            tenant_context=self.dispatch_ready_context,
        )

        self.assertEqual(
            result["results"],
            [
                {
                    "reliefrqst_id": active_request_id,
                    "status_code": REQUEST_STATUS_APPROVED_FOR_FULFILLMENT,
                    "current_package": None,
                }
            ],
        )

    @patch("operations.contract_services.legacy_service._current_package_for_request", return_value=None)
    @patch("operations.contract_services.legacy_service._request_items", return_value=[])
    @patch(
        "operations.contract_services._request_summary_payload",
        side_effect=lambda request, request_record: {
            "reliefrqst_id": int(request.reliefrqst_id),
            "status_code": request_record.status_code,
        },
    )
    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._load_request")
    def test_get_package_allows_fulfilled_requests_in_fulfillment_workspace(
        self,
        load_request_mock,
        get_agency_scope_mock,
        _request_summary_mock,
        _request_items_mock,
        _current_package_mock,
    ) -> None:
        OperationsReliefRequest.objects.create(
            relief_request_id=70,
            request_no="RQ00070",
            requesting_tenant_id=20,
            requesting_agency_id=501,
            beneficiary_tenant_id=20,
            beneficiary_agency_id=501,
            origin_mode="SELF",
            event_id=12,
            request_date=date(2026, 3, 26),
            urgency_code="H",
            status_code=REQUEST_STATUS_FULFILLED,
            create_by_id="tester",
            update_by_id="tester",
        )
        load_request_mock.return_value = self._request_stub(
            reliefrqst_id=70,
            agency_id=501,
            status_code=contract_services.legacy_service.STATUS_FILLED,
        )
        get_agency_scope_mock.return_value = self._agency_scope_for(501, 20, "FFP")

        result = contract_services.get_package(
            70,
            actor_id="logistics-1",
            actor_roles=["LOGISTICS_MANAGER"],
            tenant_context=self.dispatch_ready_context,
        )

        self.assertEqual(result["request"], {"reliefrqst_id": 70, "status_code": REQUEST_STATUS_FULFILLED})
        self.assertEqual(result["package"], None)

    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service._load_package")
    def test_receipt_confirmation_persists_receipt_artifact(
        self,
        load_package_mock,
        load_request_mock,
        get_agency_scope_mock,
    ) -> None:
        dispatched_package = SimpleNamespace(**{**self.package.__dict__, "dispatch_dtime": datetime(2026, 3, 26, 12, 0, 0), "status_code": "D"})
        load_package_mock.return_value = dispatched_package
        load_request_mock.return_value = self.request
        get_agency_scope_mock.return_value = self.agency_scope
        ops_request = OperationsReliefRequest.objects.create(
            relief_request_id=70,
            request_no="RQ00070",
            requesting_tenant_id=20,
            origin_mode="SELF",
            event_id=12,
            request_date=date(2026, 3, 26),
            urgency_code="H",
            status_code="SUBMITTED",
            create_by_id="requester-1",
            update_by_id="requester-1",
        )
        OperationsPackage.objects.create(
            package_id=90,
            package_no="PK00090",
            relief_request=ops_request,
            status_code="DISPATCHED",
            create_by_id="locker-1",
            update_by_id="locker-1",
        )
        dispatch = OperationsDispatch.objects.create(
            package_id=90,
            dispatch_no="DP00090",
            status_code=DISPATCH_STATUS_IN_TRANSIT,
            source_warehouse_id=4,
            destination_tenant_id=20,
            destination_agency_id=501,
            create_by_id="dispatch-1",
            update_by_id="dispatch-1",
        )
        OperationsQueueAssignment.objects.create(
            queue_code="RECEIPT_CONFIRMATION",
            entity_type="PACKAGE",
            entity_id=90,
            assigned_user_id="receiver-1",
            assigned_role_code="LOGISTICS_MANAGER",
            assignment_status="OPEN",
        )

        result = contract_services.confirm_receipt(
            90,
            payload={"received_by_name": "Receiver One", "receipt_notes": "Received intact"},
            actor_id="receiver-1",
            actor_roles=["LOGISTICS_MANAGER"],
            tenant_context=self.dispatch_ready_context,
            idempotency_key="receipt-90",
        )

        self.assertEqual(result["status"], "RECEIVED")
        receipt = OperationsReceipt.objects.get(dispatch_id=dispatch.dispatch_id)
        self.assertEqual(receipt.received_by_name, "Receiver One")
        self.assertEqual(receipt.receipt_status_code, "RECEIVED")
        self.assertEqual(receipt.package_id, dispatch.package_id)

    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service._load_package")
    def test_receipt_confirmation_allows_controller_flow_with_direct_receipt_assignment(
        self,
        load_package_mock,
        load_request_mock,
        get_agency_scope_mock,
    ) -> None:
        dispatched_package = SimpleNamespace(
            **{**self.package.__dict__, "dispatch_dtime": datetime(2026, 3, 26, 12, 0, 0), "status_code": "D"}
        )
        load_package_mock.return_value = dispatched_package
        load_request_mock.return_value = self.request
        get_agency_scope_mock.return_value = self.agency_scope
        ops_request = OperationsReliefRequest.objects.create(
            relief_request_id=70,
            request_no="RQ00070",
            requesting_tenant_id=20,
            requesting_agency_id=501,
            beneficiary_tenant_id=30,
            beneficiary_agency_id=777,
            origin_mode=ORIGIN_MODE_FOR_SUBORDINATE,
            event_id=12,
            request_date=date(2026, 3, 26),
            urgency_code="H",
            status_code="SUBMITTED",
            create_by_id="requester-1",
            update_by_id="requester-1",
        )
        OperationsPackage.objects.create(
            package_id=90,
            package_no="PK00090",
            relief_request=ops_request,
            destination_tenant_id=30,
            destination_agency_id=777,
            status_code="DISPATCHED",
            create_by_id="locker-1",
            update_by_id="locker-1",
        )
        dispatch = OperationsDispatch.objects.create(
            package_id=90,
            dispatch_no="DP00090",
            status_code=DISPATCH_STATUS_IN_TRANSIT,
            source_warehouse_id=4,
            destination_tenant_id=30,
            destination_agency_id=777,
            create_by_id="dispatch-1",
            update_by_id="dispatch-1",
        )
        OperationsQueueAssignment.objects.create(
            queue_code=QUEUE_CODE_RECEIPT,
            entity_type="PACKAGE",
            entity_id=90,
            assigned_user_id="controller-1",
            assigned_tenant_id=30,
            assignment_status="OPEN",
        )

        result = contract_services.confirm_receipt(
            90,
            payload={"received_by_name": "Receiver One", "receipt_notes": "Received intact"},
            actor_id="controller-1",
            actor_roles=["LOGISTICS_MANAGER"],
            tenant_context=self.dispatch_ready_context,
            idempotency_key="receipt-90-controller",
        )

        self.assertEqual(result["status"], "RECEIVED")
        receipt = OperationsReceipt.objects.get(dispatch_id=dispatch.dispatch_id)
        self.assertEqual(receipt.received_by_name, "Receiver One")
        self.assertEqual(receipt.receipt_status_code, "RECEIVED")
        self.assertEqual(receipt.package_id, dispatch.package_id)

    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service._load_package")
    def test_receipt_confirmation_requires_receipt_queue_assignment(
        self,
        load_package_mock,
        load_request_mock,
        get_agency_scope_mock,
    ) -> None:
        dispatched_package = SimpleNamespace(
            **{**self.package.__dict__, "dispatch_dtime": datetime(2026, 3, 26, 12, 0, 0), "status_code": "D"}
        )
        load_package_mock.return_value = dispatched_package
        load_request_mock.return_value = self.request
        get_agency_scope_mock.return_value = self.agency_scope
        ops_request = OperationsReliefRequest.objects.create(
            relief_request_id=70,
            request_no="RQ00070",
            requesting_tenant_id=20,
            origin_mode="SELF",
            event_id=12,
            request_date=date(2026, 3, 26),
            urgency_code="H",
            status_code="SUBMITTED",
            create_by_id="requester-1",
            update_by_id="requester-1",
        )
        OperationsPackage.objects.create(
            package_id=90,
            package_no="PK00090",
            relief_request=ops_request,
            status_code="DISPATCHED",
            create_by_id="locker-1",
            update_by_id="locker-1",
        )
        OperationsDispatch.objects.create(
            package_id=90,
            dispatch_no="DP00090",
            status_code=DISPATCH_STATUS_IN_TRANSIT,
            source_warehouse_id=4,
            destination_tenant_id=20,
            destination_agency_id=501,
            create_by_id="dispatch-1",
            update_by_id="dispatch-1",
        )

        with self.assertRaises(OperationValidationError) as raised:
            contract_services.confirm_receipt(
                90,
                payload={"received_by_name": "Receiver One"},
                actor_id="receiver-1",
                actor_roles=["LOGISTICS_MANAGER"],
                tenant_context=self.dispatch_ready_context,
                idempotency_key="receipt-90-missing-assignment",
            )

        self.assertEqual(
            raised.exception.errors,
            {"authorization": "You are not assigned to the receipt queue for this package."},
        )

    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service._load_package")
    def test_receipt_confirmation_requires_dispatch_record(
        self,
        load_package_mock,
        load_request_mock,
        get_agency_scope_mock,
    ) -> None:
        dispatched_package = SimpleNamespace(
            **{**self.package.__dict__, "dispatch_dtime": datetime(2026, 3, 26, 12, 0, 0), "status_code": "D"}
        )
        load_package_mock.return_value = dispatched_package
        load_request_mock.return_value = self.request
        get_agency_scope_mock.return_value = self.agency_scope

        with self.assertRaises(OperationValidationError) as raised:
            contract_services.confirm_receipt(
                90,
                payload={"received_by_name": "Receiver One"},
                actor_id="receiver-1",
                actor_roles=["LOGISTICS_MANAGER"],
                tenant_context=self.dispatch_ready_context,
                idempotency_key="receipt-90-missing-dispatch",
            )

        self.assertEqual(raised.exception.errors, {"receipt": "Dispatch record is missing for this package."})

    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service._load_package")
    @patch("operations.contract_services.legacy_service.submit_dispatch")
    def test_submit_dispatch_reuses_cached_response_for_same_idempotency_key(
        self,
        legacy_submit_dispatch_mock,
        load_package_mock,
        load_request_mock,
        get_agency_scope_mock,
    ) -> None:
        load_package_mock.return_value = self.package
        load_request_mock.return_value = self.request
        get_agency_scope_mock.return_value = self.agency_scope
        legacy_submit_dispatch_mock.return_value = {
            "reliefpkg_id": 90,
            "waybill_no": "WB-PK00090",
            "waybill_payload": {"tracking_no": "WB-PK00090"},
        }
        ops_request = OperationsReliefRequest.objects.create(
            relief_request_id=70,
            request_no="RQ00070",
            requesting_tenant_id=20,
            origin_mode="SELF",
            event_id=12,
            request_date=date(2026, 3, 26),
            urgency_code="H",
            status_code="SUBMITTED",
            create_by_id="requester-1",
            update_by_id="requester-1",
            submitted_by_id="requester-1",
            beneficiary_tenant_id=20,
            beneficiary_agency_id=501,
        )
        OperationsPackage.objects.create(
            package_id=90,
            package_no="PK00090",
            relief_request=ops_request,
            status_code="READY_FOR_DISPATCH",
            source_warehouse_id=4,
            destination_tenant_id=20,
            destination_agency_id=501,
            create_by_id="locker-1",
            update_by_id="locker-1",
        )
        with self.captureOnCommitCallbacks(execute=True):
            first = contract_services.submit_dispatch(
                90,
                payload={
                    "transport_mode": "TRUCK",
                    "driver_name": "Jane Driver",
                    "vehicle_registration": "1234AB",
                    "departure_dtime": "2026-03-26T10:00:00Z",
                    "estimated_arrival_dtime": "2026-03-26T13:00:00Z",
                },
                actor_id="dispatch-1",
                actor_roles=["LOGISTICS_OFFICER"],
                tenant_context=self.dispatch_ready_context,
                idempotency_key="dispatch-repeat",
            )

        second = contract_services.submit_dispatch(
            90,
            payload={
                "transport_mode": "TRUCK",
                "driver_name": "Different Driver",
                "vehicle_registration": "9876CD",
                "departure_dtime": "2026-03-26T10:05:00Z",
                "estimated_arrival_dtime": "2026-03-26T13:05:00Z",
            },
            actor_id="dispatch-1",
            actor_roles=["LOGISTICS_OFFICER"],
            tenant_context=self.dispatch_ready_context,
            idempotency_key="dispatch-repeat",
        )

        self.assertEqual(first, second)
        legacy_submit_dispatch_mock.assert_called_once()

    @patch("operations.contract_services._legacy_submit_dispatch")
    def test_submit_dispatch_reuses_cached_response_for_same_idempotency_key_without_tenant_context(
        self,
        legacy_submit_dispatch_mock,
    ) -> None:
        legacy_submit_dispatch_mock.return_value = {
            "reliefpkg_id": 90,
            "waybill_no": "WB-PK00090",
            "waybill_payload": {"tracking_no": "WB-PK00090"},
        }

        with self.captureOnCommitCallbacks(execute=True):
            first = contract_services.submit_dispatch(
                90,
                payload={"transport_mode": "TRUCK"},
                actor_id="dispatch-1",
                tenant_context=None,
                idempotency_key="dispatch-legacy-repeat",
            )

        second = contract_services.submit_dispatch(
            90,
            payload={"transport_mode": "AIR"},
            actor_id="dispatch-1",
            tenant_context=None,
            idempotency_key="dispatch-legacy-repeat",
        )

        self.assertEqual(first, second)
        legacy_submit_dispatch_mock.assert_called_once()

    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service._load_package")
    @patch("operations.contract_services.legacy_service.submit_dispatch")
    @patch("operations.contract_services.get_waybill")
    def test_submit_dispatch_scopes_idempotency_cache_to_relief_package(
        self,
        get_waybill_mock,
        legacy_submit_dispatch_mock,
        load_package_mock,
        load_request_mock,
        get_agency_scope_mock,
    ) -> None:
        package_90 = self._package_stub(reliefpkg_id=90, reliefrqst_id=70, agency_id=501)
        package_91 = self._package_stub(reliefpkg_id=91, reliefrqst_id=71, agency_id=501)
        request_70 = self._request_stub(reliefrqst_id=70, agency_id=501, status_code=contract_services.legacy_service.STATUS_SUBMITTED)
        request_71 = self._request_stub(reliefrqst_id=71, agency_id=501, status_code=contract_services.legacy_service.STATUS_SUBMITTED)
        load_package_mock.side_effect = [package_90, package_90, package_91, package_91]
        load_request_mock.side_effect = [request_70, request_70, request_71, request_71]
        get_agency_scope_mock.return_value = self.agency_scope
        legacy_submit_dispatch_mock.side_effect = [
            {
                "reliefpkg_id": 90,
                "waybill_no": "WB-PK00090",
                "waybill_payload": {"tracking_no": "WB-PK00090"},
            },
            {
                "reliefpkg_id": 91,
                "waybill_no": "WB-PK00091",
                "waybill_payload": {"tracking_no": "WB-PK00091"},
            },
        ]
        get_waybill_mock.side_effect = [
            {"waybill_no": "WB-PK00090", "waybill_payload": {"tracking_no": "WB-PK00090"}, "persisted": True},
            {"waybill_no": "WB-PK00091", "waybill_payload": {"tracking_no": "WB-PK00091"}, "persisted": True},
        ]
        ops_request_70 = OperationsReliefRequest.objects.create(
            relief_request_id=70,
            request_no="RQ00070",
            requesting_tenant_id=20,
            origin_mode="SELF",
            event_id=12,
            request_date=date(2026, 3, 26),
            urgency_code="H",
            status_code="SUBMITTED",
            create_by_id="requester-1",
            update_by_id="requester-1",
            submitted_by_id="requester-1",
            beneficiary_tenant_id=20,
            beneficiary_agency_id=501,
        )
        OperationsPackage.objects.create(
            package_id=90,
            package_no="PK00090",
            relief_request=ops_request_70,
            status_code="READY_FOR_DISPATCH",
            source_warehouse_id=4,
            destination_tenant_id=20,
            destination_agency_id=501,
            create_by_id="locker-1",
            update_by_id="locker-1",
        )
        ops_request_71 = OperationsReliefRequest.objects.create(
            relief_request_id=71,
            request_no="RQ00071",
            requesting_tenant_id=20,
            origin_mode="SELF",
            event_id=12,
            request_date=date(2026, 3, 26),
            urgency_code="H",
            status_code="SUBMITTED",
            create_by_id="requester-1",
            update_by_id="requester-1",
            submitted_by_id="requester-1",
            beneficiary_tenant_id=20,
            beneficiary_agency_id=501,
        )
        OperationsPackage.objects.create(
            package_id=91,
            package_no="PK00091",
            relief_request=ops_request_71,
            status_code="READY_FOR_DISPATCH",
            source_warehouse_id=4,
            destination_tenant_id=20,
            destination_agency_id=501,
            create_by_id="locker-1",
            update_by_id="locker-1",
        )

        first = contract_services.submit_dispatch(
            90,
            payload={
                "transport_mode": "TRUCK",
                "driver_name": "Jane Driver",
                "vehicle_registration": "1234AB",
                "departure_dtime": "2026-03-26T10:00:00Z",
                "estimated_arrival_dtime": "2026-03-26T13:00:00Z",
            },
            actor_id="dispatch-1",
            actor_roles=["LOGISTICS_OFFICER"],
            tenant_context=self.dispatch_ready_context,
            idempotency_key="dispatch-repeat",
        )

        second = contract_services.submit_dispatch(
            91,
            payload={
                "transport_mode": "TRUCK",
                "driver_name": "Other Driver",
                "vehicle_registration": "9876CD",
                "departure_dtime": "2026-03-26T11:00:00Z",
                "estimated_arrival_dtime": "2026-03-26T14:00:00Z",
            },
            actor_id="dispatch-1",
            actor_roles=["LOGISTICS_OFFICER"],
            tenant_context=self.dispatch_ready_context,
            idempotency_key="dispatch-repeat",
        )

        self.assertEqual(first["reliefpkg_id"], 90)
        self.assertEqual(second["reliefpkg_id"], 91)
        self.assertEqual(legacy_submit_dispatch_mock.call_count, 2)

    def test_confirm_receipt_requires_idempotency_key(self) -> None:
        with self.assertRaises(OperationValidationError) as raised:
            contract_services.confirm_receipt(
                90,
                payload={"received_by_name": "Receiver One"},
                actor_id="receiver-1",
                actor_roles=["LOGISTICS_MANAGER"],
                tenant_context=self.dispatch_ready_context,
            )

        self.assertEqual(
            raised.exception.errors,
            {"idempotency_key": "Idempotency-Key header is required."},
        )

    def test_pickup_release_requires_idempotency_key(self) -> None:
        with self.assertRaises(OperationValidationError) as raised:
            contract_services.pickup_release(
                90,
                payload={"released_by_name": "Receiver One"},
                actor_id="receiver-1",
                actor_roles=["LOGISTICS_MANAGER"],
                tenant_context=self.dispatch_ready_context,
            )

        self.assertEqual(
            raised.exception.errors,
            {"idempotency_key": "Idempotency-Key header is required."},
        )

    def test_cancel_package_requires_idempotency_key(self) -> None:
        with self.assertRaises(OperationValidationError) as raised:
            contract_services.cancel_package(
                90,
                payload=None,
                actor_id="dispatcher-1",
                actor_roles=["LOGISTICS_MANAGER"],
                tenant_context=self.dispatch_ready_context,
            )

        self.assertEqual(
            raised.exception.errors,
            {"idempotency_key": "Idempotency-Key header is required."},
        )

    def test_request_partial_release_requires_idempotency_key(self) -> None:
        with self.assertRaises(OperationValidationError) as raised:
            contract_services.request_partial_release(
                90,
                payload={"reason": "Release received legs now"},
                actor_id="dispatcher-1",
                actor_roles=["LOGISTICS_MANAGER"],
                tenant_context=self.dispatch_ready_context,
            )

        self.assertEqual(
            raised.exception.errors,
            {"idempotency_key": "Idempotency-Key header is required."},
        )

    @patch("operations.contract_services._package_summary_payload", return_value={"reliefpkg_id": 90})
    @patch("operations.contract_services.legacy_service._load_package")
    @patch("operations.contract_services.create_role_notifications")
    @patch("operations.contract_services.assign_roles_to_queue")
    @patch("operations.contract_services._update_package_workflow_fields")
    @patch("operations.contract_services._package_leg_summary", return_value={"received_legs": 1, "total_legs": 2})
    @patch("operations.contract_services._package_context_by_package_id")
    def test_request_partial_release_reuses_cached_response_for_same_idempotency_key(
        self,
        package_context_mock,
        _package_leg_summary_mock,
        update_package_workflow_fields_mock,
        assign_roles_mock,
        create_notifications_mock,
        load_package_mock,
        package_summary_payload_mock,
    ) -> None:
        request_record = SimpleNamespace(beneficiary_tenant_id=20)
        package_record = SimpleNamespace(
            package_id=90,
            package_no="PK00090",
            fulfillment_mode=FULFILLMENT_MODE_DELIVER_FROM_STAGING,
            status_code=PACKAGE_STATUS_CONSOLIDATING,
        )
        package_context_mock.return_value = (
            self._package_stub(reliefpkg_id=90, reliefrqst_id=70, agency_id=501),
            self._request_stub(reliefrqst_id=70, agency_id=501),
            request_record,
            package_record,
        )
        load_package_mock.return_value = self._package_stub(reliefpkg_id=90, reliefrqst_id=70, agency_id=501)

        with self.captureOnCommitCallbacks(execute=True):
            first = contract_services.request_partial_release(
                90,
                payload={"reason": "Release received legs now"},
                actor_id="dispatcher-1",
                actor_roles=["LOGISTICS_MANAGER"],
                tenant_context=self.dispatch_ready_context,
                idempotency_key="partial-request-90",
            )
        second = contract_services.request_partial_release(
            90,
            payload={"reason": "Changed reason ignored by idempotency"},
            actor_id="dispatcher-1",
            actor_roles=["LOGISTICS_MANAGER"],
            tenant_context=self.dispatch_ready_context,
            idempotency_key="partial-request-90",
        )

        self.assertEqual(first, second)
        self.assertEqual(first["status"], "PARTIAL_RELEASE_REQUESTED")
        package_context_mock.assert_called_once()
        update_package_workflow_fields_mock.assert_called_once()
        assign_roles_mock.assert_called_once()
        create_notifications_mock.assert_called_once()
        load_package_mock.assert_called_once_with(90)
        package_summary_payload_mock.assert_called_once()


class StagingReservationContractTests(TransactionTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls._created_legacy_tables: list[type] = []
        existing_tables = set(connection.introspection.table_names())
        with connection.schema_editor() as schema_editor:
            for model in (Inventory, ItemBatch):
                if model._meta.db_table in existing_tables:
                    continue
                schema_editor.create_model(model)
                cls._created_legacy_tables.append(model)

    @classmethod
    def tearDownClass(cls) -> None:
        with connection.schema_editor() as schema_editor:
            for model in reversed(cls._created_legacy_tables):
                schema_editor.delete_model(model)
        super().tearDownClass()

    def _create_operations_request_record(self, relief_request_id: int = 70, agency_id: int = 501) -> OperationsReliefRequest:
        return OperationsReliefRequest.objects.create(
            relief_request_id=relief_request_id,
            request_no=f"RQ{relief_request_id:05d}",
            requesting_tenant_id=20,
            requesting_agency_id=agency_id,
            beneficiary_tenant_id=20,
            beneficiary_agency_id=agency_id,
            origin_mode="SELF",
            event_id=12,
            request_date=date(2026, 3, 26),
            urgency_code="H",
            status_code=REQUEST_STATUS_APPROVED_FOR_FULFILLMENT,
            create_by_id="tester",
            update_by_id="tester",
        )

    def test_receive_leg_stock_into_staging_reserves_the_new_staging_batch_for_final_dispatch(self) -> None:
        request_record = self._create_operations_request_record(relief_request_id=191)
        package_record = OperationsPackage.objects.create(
            package_id=191,
            package_no="PK00191",
            relief_request=request_record,
            source_warehouse_id=4,
            staging_warehouse_id=55,
            fulfillment_mode=FULFILLMENT_MODE_DELIVER_FROM_STAGING,
            status_code=PACKAGE_STATUS_CONSOLIDATING,
            create_by_id="tester",
            update_by_id="tester",
        )
        leg = OperationsConsolidationLeg.objects.create(
            package=package_record,
            leg_sequence=1,
            source_warehouse_id=4,
            staging_warehouse_id=55,
            status_code=CONSOLIDATION_LEG_STATUS_IN_TRANSIT,
            create_by_id="tester",
            update_by_id="tester",
        )
        source_batch = ItemBatch.objects.create(
            batch_id=4001,
            inventory_id=4,
            item_id=101,
            batch_no="SRC-4001",
            batch_date=date(2026, 3, 20),
            expiry_date=date(2026, 12, 31),
            usable_qty=Decimal("5.0000"),
            reserved_qty=Decimal("0.0000"),
            defective_qty=Decimal("0.0000"),
            expired_qty=Decimal("0.0000"),
            uom_code="EA",
            status_code="A",
            update_by_id="tester",
            update_dtime=timezone.now(),
            version_nbr=1,
        )
        leg_item = OperationsConsolidationLegItem.objects.create(
            leg=leg,
            item_id=101,
            batch_id=source_batch.batch_id,
            quantity=Decimal("2.0000"),
            source_type="ON_HAND",
            source_record_id=None,
            uom_code="EA",
            create_by_id="tester",
            update_by_id="tester",
        )

        with patch("operations.contract_services.legacy_service._next_int_id", return_value=95501):
            contract_services._receive_leg_stock_into_staging(leg=leg, actor_id="receiver-1")

        leg_item.refresh_from_db()
        staging_batch = ItemBatch.objects.get(batch_id=95501)
        staging_inventory = Inventory.objects.get(inventory_id=55, item_id=101)

        self.assertEqual(leg_item.staging_batch_id, 95501)
        self.assertEqual(staging_batch.inventory_id, 55)
        self.assertEqual(staging_batch.usable_qty, Decimal("2.0000"))
        self.assertEqual(staging_batch.reserved_qty, Decimal("2.0000"))
        self.assertEqual(staging_batch.available_qty, Decimal("0.0000"))
        self.assertEqual(staging_inventory.usable_qty, Decimal("2.00"))
        self.assertEqual(staging_inventory.reserved_qty, Decimal("2.00"))
        self.assertEqual(staging_inventory.available_qty, Decimal("0.00"))


@override_settings(AUTH_ENABLED=False, DEV_AUTH_ENABLED=True, TEST_DEV_AUTH_ENABLED=True)
class ItemAllocationOptionsTests(TestCase):
    """Tests for the per-item allocation options endpoint."""

    def setUp(self) -> None:
        self.tenant_ctx = _tenant_context(tenant_id=20, tenant_code="FFP", tenant_type="EXTERNAL")
        self.agency_scope = operations_policy.AgencyScope(
            agency_id=501,
            agency_name="FFP Shelter",
            agency_type="SHELTER",
            warehouse_id=11,
            tenant_id=20,
            tenant_code="FFP",
            tenant_name="Food For The Poor",
            tenant_type="EXTERNAL",
        )
        self.request_stub = SimpleNamespace(
            reliefrqst_id=80,
            agency_id=501,
            tracking_no="RQ00080",
            eligible_event_id=12,
            request_date=date(2026, 3, 26),
            urgency_ind="H",
            rqst_notes_text="Multi-warehouse test",
            create_by_id="requester-1",
            create_dtime=datetime(2026, 3, 26, 9, 0, 0),
            review_by_id=None,
            review_dtime=None,
            status_code=3,
        )
        fully_dispatched_patcher = patch(
            "operations.contract_services._request_fully_dispatched",
            return_value=False,
        )
        fully_dispatched_patcher.start()
        self.addCleanup(fully_dispatched_patcher.stop)

    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service.get_item_allocation_options")
    def test_returns_single_item_options_with_optional_source_and_continuation_ids(
        self,
        get_item_options_mock,
        load_request_mock,
        get_agency_scope_mock,
    ) -> None:
        load_request_mock.return_value = self.request_stub
        get_agency_scope_mock.return_value = self.agency_scope
        get_item_options_mock.return_value = {
            "item_id": 101,
            "item_code": "MASK001",
            "item_name": "Face Mask",
            "request_qty": "20.0000",
            "issue_qty": "0.0000",
            "remaining_qty": "20.0000",
            "urgency_ind": "H",
            "candidates": [],
            "suggested_allocations": [],
            "remaining_after_suggestion": "20.0000",
            "source_warehouse_id": 7,
            "selected_warehouse_ids": [7, 5],
            "recommended_warehouse_id": 7,
            "remaining_shortfall_qty": "20.0000",
            "continuation_recommended": False,
            "alternate_warehouses": [],
        }

        result = contract_services.get_item_allocation_options(
            80,
            101,
            source_warehouse_id=None,
            additional_warehouse_ids=[7, 5, 5],
            actor_id="fulfiller-1",
            actor_roles=["LOGISTICS_OFFICER"],
            tenant_context=self.tenant_ctx,
        )

        self.assertEqual(result["item_id"], 101)
        self.assertEqual(result["source_warehouse_id"], 7)
        self.assertEqual(result["selected_warehouse_ids"], [7, 5])
        self.assertEqual(result["recommended_warehouse_id"], 7)
        self.assertEqual(result["remaining_shortfall_qty"], "20.0000")
        self.assertFalse(result["continuation_recommended"])
        get_item_options_mock.assert_called_once_with(
            80,
            101,
            source_warehouse_id=None,
            tenant_context=self.tenant_ctx,
            draft_allocations=None,
            additional_warehouse_ids=[7, 5, 5],
        )

    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service.get_item_allocation_preview")
    def test_preview_forwards_draft_and_continuation_payload(
        self,
        get_item_preview_mock,
        load_request_mock,
        get_agency_scope_mock,
    ) -> None:
        load_request_mock.return_value = self.request_stub
        get_agency_scope_mock.return_value = self.agency_scope
        get_item_preview_mock.return_value = {
            "item_id": 101,
            "remaining_qty": "20.0000",
            "draft_selected_qty": "2.0000",
            "effective_remaining_qty": "18.0000",
            "remaining_after_suggestion": "12.0000",
            "remaining_shortfall_qty": "12.0000",
            "continuation_recommended": True,
            "alternate_warehouses": [],
        }

        result = contract_services.get_item_allocation_preview(
            80,
            101,
            payload={
                "additional_warehouse_ids": [5, 2, 5],
                "draft_allocations": [
                    {
                        "item_id": 101,
                        "inventory_id": 5,
                        "batch_id": 1001,
                        "quantity": "2.0000",
                    }
                ],
            },
            actor_id="fulfiller-1",
            actor_roles=["LOGISTICS_OFFICER"],
            tenant_context=self.tenant_ctx,
        )

        self.assertEqual(result["draft_selected_qty"], "2.0000")
        self.assertEqual(result["effective_remaining_qty"], "18.0000")
        get_item_preview_mock.assert_called_once_with(
            80,
            101,
            source_warehouse_id=None,
            tenant_context=self.tenant_ctx,
            draft_allocations=[
                {
                    "item_id": 101,
                    "inventory_id": 5,
                    "batch_id": 1001,
                    "quantity": "2.0000",
                }
            ],
            additional_warehouse_ids=[5, 2],
        )

    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service.get_package_allocation_options")
    def test_package_options_forward_tenant_context(
        self,
        get_package_options_mock,
        load_request_mock,
        get_agency_scope_mock,
    ) -> None:
        load_request_mock.return_value = self.request_stub
        get_agency_scope_mock.return_value = self.agency_scope
        get_package_options_mock.return_value = {"request": {"reliefrqst_id": 80}, "items": []}

        result = contract_services.get_package_allocation_options(
            80,
            source_warehouse_id=None,
            actor_id="fulfiller-1",
            actor_roles=["LOGISTICS_OFFICER"],
            tenant_context=self.tenant_ctx,
        )

        self.assertEqual(result["request"]["reliefrqst_id"], 80)
        get_package_options_mock.assert_called_once_with(
            80,
            source_warehouse_id=None,
            tenant_context=self.tenant_ctx,
        )

    @patch("operations.services.data_access.get_warehouses_with_stock")
    @patch("operations.services.can_access_warehouse")
    @patch("operations.services._fetch_batch_candidates")
    @patch("operations.services.Item.objects.filter")
    @patch(
        "operations.services._request_item_rows_for_allocation",
        return_value=[
            {"item_id": 101, "request_qty": "10.0000", "issue_qty": "2.0000", "urgency_ind": "H"}
        ],
    )
    def test_service_omits_continuation_when_selected_warehouse_fully_covers(
        self,
        _request_rows_mock,
        item_filter_mock,
        fetch_candidates_mock,
        can_access_warehouse_mock,
        get_warehouses_with_stock_mock,
    ) -> None:
        item = SimpleNamespace(
            item_id=101,
            item_code="MASK001",
            item_name="Face Mask",
            issuance_order="FIFO",
            can_expire_flag=False,
        )
        item_queryset = Mock()
        item_queryset.first.return_value = item
        item_filter_mock.return_value = item_queryset
        get_warehouses_with_stock_mock.return_value = ({}, [])
        fetch_candidates_mock.return_value = [
            {
                "batch_id": 1001,
                "inventory_id": 1,
                "item_id": 101,
                "batch_no": "B-1001",
                "batch_date": date(2026, 3, 25),
                "expiry_date": None,
                "usable_qty": Decimal("8.0000"),
                "reserved_qty": Decimal("0.0000"),
                "available_qty": Decimal("8.0000"),
                "uom_code": "EA",
                "source_type": "ON_HAND",
                "source_record_id": None,
                "warehouse_name": "Warehouse 1",
                "can_expire_flag": False,
                "issuance_order": "FIFO",
                "item_code": "MASK001",
                "item_name": "Face Mask",
            }
        ]

        result = operations_service.get_item_allocation_options(
            80,
            101,
            source_warehouse_id=1,
            tenant_context=self.tenant_ctx,
        )

        self.assertEqual(result["source_warehouse_id"], 1)
        self.assertEqual(result["remaining_after_suggestion"], "0.0000")
        self.assertEqual(result["remaining_shortfall_qty"], "0.0000")
        self.assertFalse(result["continuation_recommended"])
        self.assertEqual(result["alternate_warehouses"], [])
        get_warehouses_with_stock_mock.assert_called_once_with([101], 0)
        can_access_warehouse_mock.assert_called_once_with(self.tenant_ctx, 1, write=True)

    @patch("operations.services.data_access.get_warehouses_with_stock")
    @patch("operations.services.can_access_warehouse")
    @patch(
        "operations.services._active_source_stock_integrity_issue",
        return_value=(
            "Warehouse stock totals are out of sync for item 101 at inventory 1. "
            "Aggregate available stock is 0.0000 but batch-level available stock totals 8.0000. "
            "Reconcile warehouse inventory before committing this reservation."
        ),
    )
    @patch("operations.services._fetch_batch_candidates")
    @patch("operations.services.Item.objects.filter")
    @patch(
        "operations.services._request_item_rows_for_allocation",
        return_value=[
            {"item_id": 101, "request_qty": "10.0000", "issue_qty": "2.0000", "urgency_ind": "H"}
        ],
    )
    def test_preview_without_draft_allocations_surfaces_stock_integrity_issue_and_clears_suggestions(
        self,
        _request_rows_mock,
        item_filter_mock,
        fetch_candidates_mock,
        _stock_integrity_issue_mock,
        can_access_warehouse_mock,
        get_warehouses_with_stock_mock,
    ) -> None:
        item = SimpleNamespace(
            item_id=101,
            item_code="MASK001",
            item_name="Face Mask",
            issuance_order="FIFO",
            can_expire_flag=False,
        )
        item_queryset = Mock()
        item_queryset.first.return_value = item
        item_filter_mock.return_value = item_queryset
        get_warehouses_with_stock_mock.return_value = ({}, [])
        fetch_candidates_mock.return_value = [
            {
                "batch_id": 1001,
                "inventory_id": 1,
                "item_id": 101,
                "batch_no": "B-1001",
                "batch_date": date(2026, 3, 25),
                "expiry_date": None,
                "usable_qty": Decimal("8.0000"),
                "reserved_qty": Decimal("0.0000"),
                "available_qty": Decimal("8.0000"),
                "uom_code": "EA",
                "source_type": "ON_HAND",
                "source_record_id": None,
                "warehouse_name": "Warehouse 1",
                "can_expire_flag": False,
                "issuance_order": "FIFO",
                "item_code": "MASK001",
                "item_name": "Face Mask",
            }
        ]

        result = operations_service.get_item_allocation_preview(
            80,
            101,
            source_warehouse_id=1,
            tenant_context=self.tenant_ctx,
        )

        self.assertEqual(result["remaining_qty"], "8.0000")
        self.assertEqual(result["draft_selected_qty"], "0.0000")
        self.assertEqual(result["effective_remaining_qty"], "8.0000")
        self.assertEqual(result["remaining_after_suggestion"], "8.0000")
        self.assertEqual(result["remaining_shortfall_qty"], "8.0000")
        self.assertIn("out of sync", result["stock_integrity_issue"])
        self.assertEqual(result["suggested_allocations"], [])
        self.assertFalse(result["continuation_recommended"])
        self.assertEqual(result["alternate_warehouses"], [])
        self.assertFalse(result["fully_issued"])
        self.assertEqual(get_warehouses_with_stock_mock.call_count, 1)
        get_warehouses_with_stock_mock.assert_called_once_with([101], 0)
        can_access_warehouse_mock.assert_called_once_with(self.tenant_ctx, 1, write=True)

    @patch("operations.services.data_access.get_warehouses_with_stock")
    @patch("operations.services.can_access_warehouse", return_value=True)
    @patch(
        "operations.services._inventory_batch_drift_message",
        return_value=(
            "Warehouse stock totals are out of sync for item 101 at inventory 5. "
            "Aggregate available stock is 0.0000 but batch-level available stock totals 4.0000. "
            "Reconcile warehouse inventory before committing this reservation."
        ),
    )
    @patch("operations.services._inventory_batch_stock_totals")
    @patch("operations.services._fetch_batch_candidates")
    @patch("operations.services.Item.objects.filter")
    @patch(
        "operations.services._request_item_rows_for_allocation",
        return_value=[
            {"item_id": 101, "request_qty": "10.0000", "issue_qty": "2.0000", "urgency_ind": "H"}
        ],
    )
    def test_preview_surfaces_stock_integrity_issue_for_loaded_secondary_warehouse_drift(
        self,
        _request_rows_mock,
        item_filter_mock,
        fetch_candidates_mock,
        inventory_batch_totals_mock,
        _inventory_batch_drift_message_mock,
        _can_access_warehouse_mock,
        get_warehouses_with_stock_mock,
    ) -> None:
        item = SimpleNamespace(
            item_id=101,
            item_code="MASK001",
            item_name="Face Mask",
            issuance_order="FIFO",
            can_expire_flag=False,
        )
        item_queryset = Mock()
        item_queryset.first.return_value = item
        item_filter_mock.return_value = item_queryset
        get_warehouses_with_stock_mock.return_value = ({}, [])
        fetch_candidates_mock.side_effect = lambda warehouse_id, _item_id, as_of_date=None: [
            {
                "batch_id": 1000 + int(warehouse_id),
                "inventory_id": warehouse_id,
                "item_id": 101,
                "batch_no": f"B-{warehouse_id}",
                "batch_date": date(2026, 3, 25),
                "expiry_date": None,
                "usable_qty": Decimal("4.0000"),
                "reserved_qty": Decimal("0.0000"),
                "available_qty": Decimal("4.0000"),
                "uom_code": "EA",
                "source_type": "ON_HAND",
                "source_record_id": None,
                "warehouse_name": (
                    "ODPEM Continuation Depot"
                    if int(warehouse_id) == 5
                    else f"Warehouse {warehouse_id}"
                ),
                "can_expire_flag": False,
                "issuance_order": "FIFO",
                "item_code": "MASK001",
                "item_name": "Face Mask",
            }
        ]

        def totals_side_effect(inventory_id, _item_id, as_of_date=None):
            if int(inventory_id) == 1:
                return {
                    "inventory_id": 1,
                    "item_id": 101,
                    "inventory_usable_qty": Decimal("4.0000"),
                    "inventory_reserved_qty": Decimal("0.0000"),
                    "inventory_available_qty": Decimal("4.0000"),
                    "batch_usable_qty": Decimal("4.0000"),
                    "batch_reserved_qty": Decimal("0.0000"),
                    "batch_available_qty": Decimal("4.0000"),
                    "has_drift": False,
                }
            return {
                "inventory_id": 5,
                "item_id": 101,
                "inventory_usable_qty": Decimal("0.0000"),
                "inventory_reserved_qty": Decimal("0.0000"),
                "inventory_available_qty": Decimal("0.0000"),
                "batch_usable_qty": Decimal("4.0000"),
                "batch_reserved_qty": Decimal("0.0000"),
                "batch_available_qty": Decimal("4.0000"),
                "has_drift": True,
            }

        inventory_batch_totals_mock.side_effect = totals_side_effect

        result = operations_service._build_item_allocation_response(
            80,
            101,
            source_warehouse_id=1,
            tenant_context=self.tenant_ctx,
            draft_allocations=[],
            include_draft_metrics=True,
            additional_warehouse_ids=[5],
        )

        self.assertEqual(
            [candidate["inventory_id"] for candidate in result["candidates"]],
            [1, 5],
        )
        self.assertEqual(result["selected_warehouse_ids"], [1, 5])
        self.assertEqual(result["recommended_warehouse_id"], 1)
        self.assertEqual(result["suggested_allocations"], [])
        self.assertFalse(result["continuation_recommended"])
        self.assertIn("inventory 5", result["stock_integrity_issue"])
        warehouse_cards_by_id = {
            int(card["warehouse_id"]): card for card in result["warehouse_cards"]
        }
        self.assertEqual(
            warehouse_cards_by_id[5]["warehouse_name"],
            "ODPEM Continuation Depot",
        )
        self.assertEqual(
            [call.args[0] for call in inventory_batch_totals_mock.call_args_list],
            [1, 5],
        )

    @patch("operations.services.data_access.get_warehouses_with_stock")
    @patch(
        "operations.services._inventory_batch_drift_message",
        return_value=(
            "Warehouse stock totals are out of sync for item 101 at inventory 1. "
            "Reconcile warehouse inventory before committing this reservation."
        ),
    )
    @patch(
        "operations.services._active_batch_stock_totals",
        return_value={
            "inventory_id": 1,
            "item_id": 101,
            "batch_usable_qty": Decimal("8.0000"),
            "batch_reserved_qty": Decimal("0.0000"),
            "batch_available_qty": Decimal("8.0000"),
            "batch_row_count": 1,
        },
    )
    @patch("operations.services._inventory_batch_stock_totals", return_value=None)
    @patch("operations.services.can_access_warehouse", return_value=True)
    @patch("operations.services._fetch_batch_candidates")
    @patch("operations.services.Item.objects.filter")
    @patch(
        "operations.services._request_item_rows_for_allocation",
        return_value=[
            {"item_id": 101, "request_qty": "10.0000", "issue_qty": "2.0000", "urgency_ind": "H"}
        ],
    )
    def test_preview_surfaces_stock_integrity_issue_when_inventory_aggregate_is_missing_but_batches_exist(
        self,
        _request_rows_mock,
        item_filter_mock,
        fetch_candidates_mock,
        _can_access_warehouse_mock,
        _inventory_batch_totals_mock,
        _active_batch_stock_totals_mock,
        _inventory_batch_drift_message_mock,
        get_warehouses_with_stock_mock,
    ) -> None:
        item = SimpleNamespace(
            item_id=101,
            item_code="MASK001",
            item_name="Face Mask",
            issuance_order="FIFO",
            can_expire_flag=False,
        )
        item_queryset = Mock()
        item_queryset.first.return_value = item
        item_filter_mock.return_value = item_queryset
        get_warehouses_with_stock_mock.return_value = ({}, [])
        fetch_candidates_mock.return_value = [
            {
                "batch_id": 1001,
                "inventory_id": 1,
                "item_id": 101,
                "batch_no": "B-1001",
                "batch_date": date(2026, 3, 25),
                "expiry_date": None,
                "usable_qty": Decimal("8.0000"),
                "reserved_qty": Decimal("0.0000"),
                "available_qty": Decimal("8.0000"),
                "uom_code": "EA",
                "source_type": "ON_HAND",
                "source_record_id": None,
                "warehouse_name": "Warehouse 1",
                "can_expire_flag": False,
                "issuance_order": "FIFO",
                "item_code": "MASK001",
                "item_name": "Face Mask",
            }
        ]

        result = operations_service.get_item_allocation_preview(
            80,
            101,
            source_warehouse_id=1,
            tenant_context=self.tenant_ctx,
        )

        self.assertEqual(result["suggested_allocations"], [])
        self.assertFalse(result["continuation_recommended"])
        self.assertIn("out of sync", result["stock_integrity_issue"])
        self.assertIn("Reconcile warehouse inventory", result["stock_integrity_issue"])

    @patch("operations.services.data_access.get_warehouses_with_stock")
    @patch("operations.services.can_access_warehouse")
    @patch("operations.services._fetch_batch_candidates")
    @patch("operations.services.Item.objects.filter")
    @patch(
        "operations.services._request_item_rows_for_allocation",
        return_value=[
            {"item_id": 101, "request_qty": "40.0000", "issue_qty": "40.0000", "urgency_ind": "H"}
        ],
    )
    def test_preview_flags_fully_issued_item_when_issue_qty_matches_request_qty(
        self,
        _request_rows_mock,
        item_filter_mock,
        fetch_candidates_mock,
        can_access_warehouse_mock,
        get_warehouses_with_stock_mock,
    ) -> None:
        """Regression: previously-dispatched items (issue_qty == request_qty) must
        surface a ``fully_issued`` flag so the UI can show an "Already Issued" state
        instead of the misleading "Over-Allocated" label when the operator tries to
        add any reservation from another batch."""
        item = SimpleNamespace(
            item_id=101,
            item_code="HADR-0058",
            item_name="Battery AA",
            issuance_order="FIFO",
            can_expire_flag=False,
        )
        item_queryset = Mock()
        item_queryset.first.return_value = item
        item_filter_mock.return_value = item_queryset
        fetch_candidates_mock.return_value = [
            {
                "batch_id": 2058,
                "inventory_id": 1,
                "item_id": 101,
                "batch_no": "HADR-2-58",
                "batch_date": date(2025, 11, 28),
                "expiry_date": None,
                "usable_qty": Decimal("1000.0000"),
                "reserved_qty": Decimal("0.0000"),
                "available_qty": Decimal("1000.0000"),
                "uom_code": "EA",
                "source_type": "ON_HAND",
                "source_record_id": None,
                "warehouse_name": "ODPEM Marcus Garvey Warehouse",
                "can_expire_flag": False,
                "issuance_order": "FIFO",
                "item_code": "HADR-0058",
                "item_name": "Battery AA",
            }
        ]
        # ``build_item_warehouse_cards`` unconditionally calls
        # ``data_access.get_warehouses_with_stock`` at the top of its body, so
        # the mock must return a real (dict, list) tuple instead of the default
        # MagicMock that cannot be unpacked.
        get_warehouses_with_stock_mock.return_value = ({}, [])

        result = operations_service.get_item_allocation_preview(
            80,
            101,
            source_warehouse_id=1,
            tenant_context=self.tenant_ctx,
        )

        self.assertEqual(result["request_qty"], "40.0000")
        self.assertEqual(result["issue_qty"], "40.0000")
        self.assertEqual(result["remaining_qty"], "0.0000")
        self.assertTrue(result["fully_issued"])
        self.assertEqual(result["effective_remaining_qty"], "0.0000")

    @patch("operations.services.data_access.get_warehouses_with_stock")
    @patch("operations.services.can_access_warehouse")
    @patch("operations.services._fetch_batch_candidates")
    @patch("operations.services.Item.objects.filter")
    @patch(
        "operations.services._request_item_rows_for_allocation",
        return_value=[
            {"item_id": 101, "request_qty": "12.0000", "issue_qty": "2.0000", "urgency_ind": "H"}
        ],
    )
    def test_service_includes_sorted_authorized_alternates_for_shortfall(
        self,
        _request_rows_mock,
        item_filter_mock,
        fetch_candidates_mock,
        can_access_warehouse_mock,
        get_warehouses_with_stock_mock,
    ) -> None:
        item = SimpleNamespace(
            item_id=101,
            item_code="MASK001",
            item_name="Face Mask",
            issuance_order="FIFO",
            can_expire_flag=False,
        )
        item_queryset = Mock()
        item_queryset.first.return_value = item
        item_filter_mock.return_value = item_queryset

        get_warehouses_with_stock_mock.return_value = (
            {
                101: [
                    {"warehouse_id": 1, "warehouse_name": "Warehouse 1", "available_qty": 99.0},
                    {"warehouse_id": 9, "warehouse_name": "Warehouse 9", "available_qty": 12.0},
                    {"warehouse_id": 7, "warehouse_name": "Warehouse 7", "available_qty": 4.0},
                    {"warehouse_id": 5, "warehouse_name": "Warehouse 5", "available_qty": 6.0},
                    {"warehouse_id": 2, "warehouse_name": "Warehouse 2", "available_qty": 6.0},
                ]
            },
            [],
        )
        can_access_warehouse_mock.side_effect = lambda _tenant_context, warehouse_id, write=False: write and warehouse_id != 9

        warehouse_candidates = {
            1: [
                {
                    "batch_id": 1001,
                    "inventory_id": 1,
                    "item_id": 101,
                    "batch_no": "B-1001",
                    "batch_date": date(2026, 3, 25),
                    "expiry_date": None,
                    "usable_qty": Decimal("4.0000"),
                    "reserved_qty": Decimal("0.0000"),
                    "available_qty": Decimal("4.0000"),
                    "uom_code": "EA",
                    "source_type": "ON_HAND",
                    "source_record_id": None,
                    "warehouse_name": "Warehouse 1",
                    "can_expire_flag": False,
                    "issuance_order": "FIFO",
                    "item_code": "MASK001",
                    "item_name": "Face Mask",
                }
            ],
            2: [
                {
                    "batch_id": 2001,
                    "inventory_id": 2,
                    "item_id": 101,
                    "batch_no": "B-2001",
                    "batch_date": date(2026, 3, 24),
                    "expiry_date": None,
                    "usable_qty": Decimal("6.0000"),
                    "reserved_qty": Decimal("0.0000"),
                    "available_qty": Decimal("6.0000"),
                    "uom_code": "EA",
                    "source_type": "ON_HAND",
                    "source_record_id": None,
                    "warehouse_name": "Warehouse 2",
                    "can_expire_flag": False,
                    "issuance_order": "FIFO",
                    "item_code": "MASK001",
                    "item_name": "Face Mask",
                }
            ],
            5: [
                {
                    "batch_id": 5001,
                    "inventory_id": 5,
                    "item_id": 101,
                    "batch_no": "B-5001",
                    "batch_date": date(2026, 3, 23),
                    "expiry_date": None,
                    "usable_qty": Decimal("6.0000"),
                    "reserved_qty": Decimal("0.0000"),
                    "available_qty": Decimal("6.0000"),
                    "uom_code": "EA",
                    "source_type": "ON_HAND",
                    "source_record_id": None,
                    "warehouse_name": "Warehouse 5",
                    "can_expire_flag": False,
                    "issuance_order": "FIFO",
                    "item_code": "MASK001",
                    "item_name": "Face Mask",
                }
            ],
            7: [
                {
                    "batch_id": 7001,
                    "inventory_id": 7,
                    "item_id": 101,
                    "batch_no": "B-7001",
                    "batch_date": date(2026, 3, 22),
                    "expiry_date": None,
                    "usable_qty": Decimal("4.0000"),
                    "reserved_qty": Decimal("0.0000"),
                    "available_qty": Decimal("4.0000"),
                    "uom_code": "EA",
                    "source_type": "ON_HAND",
                    "source_record_id": None,
                    "warehouse_name": "Warehouse 7",
                    "can_expire_flag": False,
                    "issuance_order": "FIFO",
                    "item_code": "MASK001",
                    "item_name": "Face Mask",
                }
            ],
            9: [
                {
                    "batch_id": 9001,
                    "inventory_id": 9,
                    "item_id": 101,
                    "batch_no": "B-9001",
                    "batch_date": date(2026, 3, 21),
                    "expiry_date": None,
                    "usable_qty": Decimal("12.0000"),
                    "reserved_qty": Decimal("0.0000"),
                    "available_qty": Decimal("12.0000"),
                    "uom_code": "EA",
                    "source_type": "ON_HAND",
                    "source_record_id": None,
                    "warehouse_name": "Warehouse 9",
                    "can_expire_flag": False,
                    "issuance_order": "FIFO",
                    "item_code": "MASK001",
                    "item_name": "Face Mask",
                }
            ],
        }
        fetch_candidates_mock.side_effect = (
            lambda warehouse_id, _item_id, as_of_date=None: warehouse_candidates.get(warehouse_id, [])
        )

        result = operations_service.get_item_allocation_options(
            80,
            101,
            source_warehouse_id=1,
            tenant_context=self.tenant_ctx,
        )

        self.assertEqual(result["remaining_after_suggestion"], "6.0000")
        self.assertEqual(result["remaining_shortfall_qty"], "6.0000")
        self.assertTrue(result["continuation_recommended"])
        self.assertEqual(result["selected_warehouse_ids"], [1])
        self.assertEqual(result["recommended_warehouse_id"], 7)
        self.assertEqual(
            [card["warehouse_id"] for card in result["warehouse_cards"]],
            [7, 5, 2, 1],
        )
        self.assertEqual(
            [row["warehouse_id"] for row in result["alternate_warehouses"]],
            [7, 5, 2],
        )
        self.assertEqual(
            result["alternate_warehouses"],
            [
                {
                    "warehouse_id": 7,
                    "warehouse_name": "Warehouse 7",
                    "available_qty": "4.0000",
                    "suggested_qty": "4.0000",
                    "can_fully_cover": False,
                },
                {
                    "warehouse_id": 5,
                    "warehouse_name": "Warehouse 5",
                    "available_qty": "6.0000",
                    "suggested_qty": "6.0000",
                    "can_fully_cover": True,
                },
                {
                    "warehouse_id": 2,
                    "warehouse_name": "Warehouse 2",
                    "available_qty": "6.0000",
                    "suggested_qty": "6.0000",
                    "can_fully_cover": True,
                },
            ],
        )

    @patch("operations.services.data_access.get_warehouses_with_stock")
    @patch("operations.services.can_access_warehouse", return_value=True)
    @patch("operations.services._fetch_batch_candidates")
    @patch("operations.services.Item.objects.filter")
    @patch("operations.services._load_request")
    @patch("operations.services._request_summary", return_value={"reliefrqst_id": 80})
    @patch(
        "operations.services._request_item_rows_for_allocation",
        return_value=[
            {"item_id": 101, "request_qty": "4.0000", "issue_qty": "0.0000", "urgency_ind": "H"},
            {"item_id": 202, "request_qty": "2.0000", "issue_qty": "0.0000", "urgency_ind": "H"},
        ],
    )
    def test_package_options_recommend_per_item_rank_zero_warehouse_not_shared_source_seed(
        self,
        _request_rows_mock,
        _request_summary_mock,
        load_request_mock,
        item_filter_mock,
        fetch_candidates_mock,
        _can_access_warehouse_mock,
        get_warehouses_with_stock_mock,
    ) -> None:
        load_request_mock.return_value = self.request_stub
        fifo_item = SimpleNamespace(
            item_id=101,
            item_code="TARP001",
            item_name="Tarpaulin",
            issuance_order="FIFO",
            can_expire_flag=False,
        )
        fefo_item = SimpleNamespace(
            item_id=202,
            item_code="MEDS001",
            item_name="Medical Kit",
            issuance_order="FEFO",
            can_expire_flag=True,
        )

        def item_filter_side_effect(*args, **kwargs):
            item_id = int(kwargs.get("item_id"))
            queryset = Mock()
            queryset.first.return_value = fifo_item if item_id == 101 else fefo_item
            return queryset

        item_filter_mock.side_effect = item_filter_side_effect
        get_warehouses_with_stock_mock.return_value = (
            {
                101: [
                    {"warehouse_id": 3, "warehouse_name": "Warehouse 3", "available_qty": 4.0},
                    {"warehouse_id": 5, "warehouse_name": "Warehouse 5", "available_qty": 6.0},
                ],
                202: [
                    {"warehouse_id": 3, "warehouse_name": "Warehouse 3", "available_qty": 3.0},
                    {"warehouse_id": 7, "warehouse_name": "Warehouse 7", "available_qty": 5.0},
                ],
            },
            [],
        )
        warehouse_candidates = {
            (3, 101): [
                {
                    "batch_id": 3001,
                    "inventory_id": 3,
                    "item_id": 101,
                    "batch_no": "B-3001",
                    "batch_date": date(2026, 3, 15),
                    "expiry_date": None,
                    "usable_qty": Decimal("4.0000"),
                    "reserved_qty": Decimal("0.0000"),
                    "available_qty": Decimal("4.0000"),
                    "uom_code": "EA",
                    "source_type": "ON_HAND",
                    "source_record_id": None,
                    "warehouse_name": "Warehouse 3",
                    "can_expire_flag": False,
                    "issuance_order": "FIFO",
                    "item_code": "TARP001",
                    "item_name": "Tarpaulin",
                }
            ],
            (5, 101): [
                {
                    "batch_id": 5001,
                    "inventory_id": 5,
                    "item_id": 101,
                    "batch_no": "B-5001",
                    "batch_date": date(2026, 3, 10),
                    "expiry_date": None,
                    "usable_qty": Decimal("6.0000"),
                    "reserved_qty": Decimal("0.0000"),
                    "available_qty": Decimal("6.0000"),
                    "uom_code": "EA",
                    "source_type": "ON_HAND",
                    "source_record_id": None,
                    "warehouse_name": "Warehouse 5",
                    "can_expire_flag": False,
                    "issuance_order": "FIFO",
                    "item_code": "TARP001",
                    "item_name": "Tarpaulin",
                }
            ],
            (3, 202): [
                {
                    "batch_id": 3201,
                    "inventory_id": 3,
                    "item_id": 202,
                    "batch_no": "M-3201",
                    "batch_date": date(2026, 3, 1),
                    "expiry_date": date(2026, 7, 1),
                    "usable_qty": Decimal("3.0000"),
                    "reserved_qty": Decimal("0.0000"),
                    "available_qty": Decimal("3.0000"),
                    "uom_code": "EA",
                    "source_type": "ON_HAND",
                    "source_record_id": None,
                    "warehouse_name": "Warehouse 3",
                    "can_expire_flag": True,
                    "issuance_order": "FEFO",
                    "item_code": "MEDS001",
                    "item_name": "Medical Kit",
                }
            ],
            (7, 202): [
                {
                    "batch_id": 7201,
                    "inventory_id": 7,
                    "item_id": 202,
                    "batch_no": "M-7201",
                    "batch_date": date(2026, 3, 1),
                    "expiry_date": date(2026, 5, 1),
                    "usable_qty": Decimal("5.0000"),
                    "reserved_qty": Decimal("0.0000"),
                    "available_qty": Decimal("5.0000"),
                    "uom_code": "EA",
                    "source_type": "ON_HAND",
                    "source_record_id": None,
                    "warehouse_name": "Warehouse 7",
                    "can_expire_flag": True,
                    "issuance_order": "FEFO",
                    "item_code": "MEDS001",
                    "item_name": "Medical Kit",
                }
            ],
        }
        fetch_candidates_mock.side_effect = (
            lambda warehouse_id, item_id, as_of_date=None: list(
                warehouse_candidates.get((int(warehouse_id), int(item_id)), [])
            )
        )

        result = operations_service.get_package_allocation_options(
            80,
            source_warehouse_id=3,
            tenant_context=self.tenant_ctx,
        )

        groups_by_item = {group["item_id"]: group for group in result["items"]}
        self.assertEqual(groups_by_item[101]["recommended_warehouse_id"], 5)
        self.assertEqual(groups_by_item[101]["selected_warehouse_ids"], [3])
        self.assertEqual(groups_by_item[101]["source_warehouse_id"], 3)
        self.assertEqual(groups_by_item[202]["recommended_warehouse_id"], 7)
        self.assertEqual(groups_by_item[202]["selected_warehouse_ids"], [3])
        self.assertEqual(groups_by_item[202]["source_warehouse_id"], 3)

    @patch("operations.services.data_access.get_warehouses_with_stock")
    @patch("operations.services.can_access_warehouse", return_value=True)
    @patch("operations.services._fetch_batch_candidates")
    @patch("operations.services.Item.objects.filter")
    @patch("operations.services._load_request")
    @patch(
        "operations.services._request_summary",
        return_value={"reliefrqst_id": 80, "compatibility_bridge": True, "needs_list_id": 11},
    )
    @patch(
        "operations.services._request_item_rows_for_allocation",
        return_value=[
            {"item_id": 101, "request_qty": "4.0000", "issue_qty": "0.0000", "urgency_ind": "H"}
        ],
    )
    @patch("operations.services._execution_link_for_request")
    def test_execution_linked_package_options_return_ranked_item_contract(
        self,
        execution_link_mock,
        _request_rows_mock,
        _request_summary_mock,
        load_request_mock,
        item_filter_mock,
        fetch_candidates_mock,
        _can_access_warehouse_mock,
        get_warehouses_with_stock_mock,
    ) -> None:
        execution_link_mock.return_value = SimpleNamespace(
            needs_list_id=11,
            reliefrqst_id=80,
            reliefpkg_id=90,
            execution_status="PREPARING",
            needs_list=SimpleNamespace(warehouse_id=3),
        )
        load_request_mock.return_value = self.request_stub
        item_queryset = Mock()
        item_queryset.first.return_value = SimpleNamespace(
            item_id=101,
            item_code="TARP001",
            item_name="Tarpaulin",
            issuance_order="FIFO",
            can_expire_flag=False,
        )
        item_filter_mock.return_value = item_queryset
        get_warehouses_with_stock_mock.return_value = (
            {
                101: [
                    {"warehouse_id": 3, "warehouse_name": "Warehouse 3", "available_qty": 4.0},
                    {"warehouse_id": 5, "warehouse_name": "Warehouse 5", "available_qty": 6.0},
                ]
            },
            [],
        )
        warehouse_candidates = {
            3: [
                {
                    "batch_id": 3001,
                    "inventory_id": 3,
                    "item_id": 101,
                    "batch_no": "B-3001",
                    "batch_date": date(2026, 3, 24),
                    "expiry_date": None,
                    "usable_qty": Decimal("4.0000"),
                    "reserved_qty": Decimal("0.0000"),
                    "available_qty": Decimal("4.0000"),
                    "uom_code": "EA",
                    "source_type": "ON_HAND",
                    "source_record_id": None,
                    "warehouse_name": "Warehouse 3",
                    "can_expire_flag": False,
                    "issuance_order": "FIFO",
                    "item_code": "TARP001",
                    "item_name": "Tarpaulin",
                }
            ],
            5: [
                {
                    "batch_id": 5001,
                    "inventory_id": 5,
                    "item_id": 101,
                    "batch_no": "B-5001",
                    "batch_date": date(2026, 3, 20),
                    "expiry_date": None,
                    "usable_qty": Decimal("6.0000"),
                    "reserved_qty": Decimal("0.0000"),
                    "available_qty": Decimal("6.0000"),
                    "uom_code": "EA",
                    "source_type": "ON_HAND",
                    "source_record_id": None,
                    "warehouse_name": "Warehouse 5",
                    "can_expire_flag": False,
                    "issuance_order": "FIFO",
                    "item_code": "TARP001",
                    "item_name": "Tarpaulin",
                }
            ],
        }
        fetch_candidates_mock.side_effect = (
            lambda warehouse_id, _item_id, as_of_date=None: list(
                warehouse_candidates.get(warehouse_id, [])
            )
        )

        result = operations_service.get_package_allocation_options(
            80,
            source_warehouse_id=3,
            tenant_context=self.tenant_ctx,
        )

        self.assertTrue(result["request"]["compatibility_bridge"])
        item_group = result["items"][0]
        self.assertEqual(item_group["recommended_warehouse_id"], 5)
        self.assertEqual(item_group["source_warehouse_id"], 3)
        self.assertEqual(item_group["selected_warehouse_ids"], [3])
        self.assertIn("warehouse_cards", item_group)
        self.assertIn("remaining_shortfall_qty", item_group)
        self.assertIn("continuation_recommended", item_group)
        self.assertIn("alternate_warehouses", item_group)
        self.assertGreater(len(item_group["warehouse_cards"]), 0)
        self.assertEqual(item_group["warehouse_cards"][0]["warehouse_id"], 5)
        self.assertEqual(item_group["warehouse_cards"][0]["rank"], 0)
        self.assertEqual(item_group["warehouse_cards"][0]["ranking_context"]["basis"], "FIFO")

    @patch("operations.services.data_access.get_warehouses_with_stock")
    @patch("operations.services.can_access_warehouse", return_value=True)
    @patch("operations.services._fetch_batch_candidates")
    @patch("operations.services.Item.objects.filter")
    @patch(
        "operations.services._request_item_rows_for_allocation",
        return_value=[
            {"item_id": 101, "request_qty": "10.0000", "issue_qty": "0.0000", "urgency_ind": "H"}
        ],
    )
    def test_service_uses_allocatable_qty_for_alternate_warehouse_surplus(
        self,
        _request_rows_mock,
        item_filter_mock,
        fetch_candidates_mock,
        _can_access_warehouse_mock,
        get_warehouses_with_stock_mock,
    ) -> None:
        item = SimpleNamespace(
            item_id=101,
            item_code="MASK001",
            item_name="Face Mask",
            issuance_order="FIFO",
            can_expire_flag=False,
        )
        item_queryset = Mock()
        item_queryset.first.return_value = item
        item_filter_mock.return_value = item_queryset

        get_warehouses_with_stock_mock.return_value = (
            {
                101: [
                    {"warehouse_id": 1, "warehouse_name": "Warehouse 1", "available_qty": 0.0},
                    {"warehouse_id": 2, "warehouse_name": "Warehouse 2", "available_qty": 9.0},
                ]
            },
            [],
        )

        fetch_candidates_mock.side_effect = lambda warehouse_id, _item_id, as_of_date=None: {
            1: [],
            2: [
                {
                    "batch_id": 2001,
                    "inventory_id": 2,
                    "item_id": 101,
                    "batch_no": "B-2001",
                    "batch_date": date(2026, 3, 24),
                    "expiry_date": None,
                    "usable_qty": Decimal("4.0000"),
                    "reserved_qty": Decimal("0.0000"),
                    "available_qty": Decimal("9.0000"),
                    "uom_code": "EA",
                    "source_type": "ON_HAND",
                    "source_record_id": None,
                    "warehouse_name": "Warehouse 2",
                    "can_expire_flag": False,
                    "issuance_order": "FIFO",
                    "item_code": "MASK001",
                    "item_name": "Face Mask",
                }
            ],
        }.get(warehouse_id, [])

        result = operations_service.get_item_allocation_options(
            80,
            101,
            source_warehouse_id=1,
            tenant_context=self.tenant_ctx,
        )

        self.assertEqual(result["recommended_warehouse_id"], 2)
        self.assertEqual(result["selected_warehouse_ids"], [2])
        self.assertEqual(result["source_warehouse_id"], 2)
        self.assertEqual(result["alternate_warehouses"], [])

    def _create_draft_package_record(
        self,
        *,
        relief_request_id: int = 80,
        package_id: int = 90,
        source_warehouse_id: int = 3,
    ) -> OperationsPackage:
        """Seed a DRAFT ``OperationsPackage`` (and its parent request) for hydration tests."""
        request_record = OperationsReliefRequest.objects.create(
            relief_request_id=relief_request_id,
            request_no=f"RQ{relief_request_id:05d}",
            requesting_tenant_id=20,
            requesting_agency_id=501,
            beneficiary_tenant_id=20,
            beneficiary_agency_id=501,
            origin_mode="SELF",
            event_id=12,
            request_date=date(2026, 3, 26),
            urgency_code="H",
            status_code=REQUEST_STATUS_APPROVED_FOR_FULFILLMENT,
            create_by_id="tester",
            update_by_id="tester",
        )
        return OperationsPackage.objects.create(
            package_id=package_id,
            package_no=f"PK{package_id:05d}",
            relief_request=request_record,
            source_warehouse_id=source_warehouse_id,
            destination_tenant_id=request_record.beneficiary_tenant_id,
            destination_agency_id=request_record.beneficiary_agency_id,
            status_code="DRAFT",
            create_by_id="tester",
            update_by_id="tester",
        )

    @patch("operations.services.data_access.get_warehouses_with_stock")
    @patch("operations.services.can_access_warehouse", return_value=True)
    @patch("operations.services._fetch_batch_candidates")
    @patch("operations.services.Item.objects.filter")
    @patch("operations.services._load_request")
    @patch("operations.services._request_summary", return_value={"reliefrqst_id": 80})
    @patch(
        "operations.services._request_item_rows_for_allocation",
        return_value=[
            {"item_id": 101, "request_qty": "12.0000", "issue_qty": "2.0000", "urgency_ind": "H"}
        ],
    )
    def test_package_options_includes_committed_draft_warehouses(
        self,
        _request_rows_mock,
        _request_summary_mock,
        load_request_mock,
        item_filter_mock,
        fetch_candidates_mock,
        _can_access_warehouse_mock,
        get_warehouses_with_stock_mock,
    ) -> None:
        """Reload fetches candidates from every warehouse the draft already committed."""
        load_request_mock.return_value = self.request_stub
        item = SimpleNamespace(
            item_id=101,
            item_code="TARP001",
            item_name="Tarpaulin",
            issuance_order="FIFO",
            can_expire_flag=False,
        )
        item_queryset = MagicMock()
        item_queryset.__iter__.return_value = iter([item])
        item_queryset.first.return_value = item
        item_filter_mock.return_value = item_queryset
        get_warehouses_with_stock_mock.return_value = (
            {
                101: [
                    {"warehouse_id": 3, "warehouse_name": "Warehouse 3", "available_qty": 4.0}
                ]
            },
            [],
        )

        self._create_draft_package_record(
            relief_request_id=80,
            package_id=90,
            source_warehouse_id=3,
        )
        OperationsAllocationLine.objects.create(
            package_id=90,
            item_id=101,
            source_warehouse_id=3,
            batch_id=3001,
            quantity=Decimal("2.0000"),
            source_type="ON_HAND",
            create_by_id="tester",
            update_by_id="tester",
        )
        OperationsAllocationLine.objects.create(
            package_id=90,
            item_id=101,
            source_warehouse_id=5,
            batch_id=5001,
            quantity=Decimal("1.0000"),
            source_type="ON_HAND",
            create_by_id="tester",
            update_by_id="tester",
        )

        warehouse_candidates = {
            3: [
                {
                    "batch_id": 3001,
                    "inventory_id": 3,
                    "item_id": 101,
                    "batch_no": "B-3001",
                    "batch_date": date(2026, 3, 24),
                    "expiry_date": None,
                    "usable_qty": Decimal("4.0000"),
                    "reserved_qty": Decimal("0.0000"),
                    "available_qty": Decimal("4.0000"),
                    "uom_code": "EA",
                    "source_type": "ON_HAND",
                    "source_record_id": None,
                    "warehouse_name": "Warehouse 3",
                    "can_expire_flag": False,
                    "issuance_order": "FIFO",
                    "item_code": "TARP001",
                    "item_name": "Tarpaulin",
                }
            ],
            5: [
                {
                    "batch_id": 5001,
                    "inventory_id": 5,
                    "item_id": 101,
                    "batch_no": "B-5001",
                    "batch_date": date(2026, 3, 23),
                    "expiry_date": None,
                    "usable_qty": Decimal("6.0000"),
                    "reserved_qty": Decimal("0.0000"),
                    "available_qty": Decimal("6.0000"),
                    "uom_code": "EA",
                    "source_type": "ON_HAND",
                    "source_record_id": None,
                    "warehouse_name": "Warehouse 5",
                    "can_expire_flag": False,
                    "issuance_order": "FIFO",
                    "item_code": "TARP001",
                    "item_name": "Tarpaulin",
                }
            ],
        }
        fetch_candidates_mock.side_effect = (
            lambda warehouse_id, _item_id, as_of_date=None: list(
                warehouse_candidates.get(warehouse_id, [])
            )
        )

        result = operations_service.get_package_allocation_options(
            80,
            source_warehouse_id=3,
            tenant_context=self.tenant_ctx,
        )

        self.assertEqual(len(result["items"]), 1)
        item_group = result["items"][0]
        self.assertEqual(item_group["source_warehouse_id"], 5)
        self.assertEqual(item_group["selected_warehouse_ids"], [5, 3])
        self.assertEqual(item_group["draft_selected_qty"], "3.0000")
        self.assertEqual(item_group["effective_remaining_qty"], "7.0000")
        self.assertEqual(item_group["remaining_shortfall_qty"], "0.0000")
        self.assertFalse(item_group["continuation_recommended"])
        self.assertEqual(
            sorted(candidate["inventory_id"] for candidate in item_group["candidates"]),
            [3, 5],
        )
        self.assertEqual(
            sorted(
                (candidate["inventory_id"], candidate["batch_id"])
                for candidate in item_group["candidates"]
            ),
            [(3, 3001), (5, 5001)],
        )
        # Merged warehouses should never appear in the alternates list.
        alternate_ids = {
            warehouse["warehouse_id"] for warehouse in item_group["alternate_warehouses"]
        }
        self.assertNotIn(3, alternate_ids)
        self.assertNotIn(5, alternate_ids)
        fetched_warehouses = sorted(
            {call.args[0] for call in fetch_candidates_mock.call_args_list}
        )
        self.assertEqual(fetched_warehouses, [3, 5])

    @patch("operations.services.data_access.get_warehouses_with_stock")
    @patch("operations.services.can_access_warehouse", return_value=True)
    @patch("operations.services._fetch_batch_candidates")
    @patch("operations.services.Item.objects.filter")
    @patch("operations.services._load_request")
    @patch("operations.services._request_summary", return_value={"reliefrqst_id": 80})
    @patch(
        "operations.services._request_item_rows_for_allocation",
        return_value=[
            {"item_id": 101, "request_qty": "12.0000", "issue_qty": "2.0000", "urgency_ind": "H"}
        ],
    )
    def test_package_options_preserve_candidates_fully_consumed_by_draft(
        self,
        _request_rows_mock,
        _request_summary_mock,
        load_request_mock,
        item_filter_mock,
        fetch_candidates_mock,
        _can_access_warehouse_mock,
        get_warehouses_with_stock_mock,
    ) -> None:
        """Reload must still expose both warehouse candidates even when the draft
        allocation fully consumes every batch at both warehouses.

        Regression: a draft that reserved the entire available quantity of a batch
        used to have that candidate silently dropped on reload, which made the
        corresponding warehouse card disappear in the fulfillment workspace and
        triggered false OVERRIDDEN / Rule Bypass badges (RQ95009 tarpaulin bug).
        """
        load_request_mock.return_value = self.request_stub
        item = SimpleNamespace(
            item_id=101,
            item_code="TARP001",
            item_name="Tarpaulin",
            issuance_order="FIFO",
            can_expire_flag=False,
        )
        item_queryset = MagicMock()
        item_queryset.__iter__.return_value = iter([item])
        item_queryset.first.return_value = item
        item_filter_mock.return_value = item_queryset
        get_warehouses_with_stock_mock.return_value = (
            {
                101: [
                    {"warehouse_id": 3, "warehouse_name": "Warehouse 3", "available_qty": 4.0}
                ]
            },
            [],
        )

        self._create_draft_package_record(
            relief_request_id=80,
            package_id=92,
            source_warehouse_id=3,
        )
        OperationsAllocationLine.objects.create(
            package_id=92,
            item_id=101,
            source_warehouse_id=3,
            batch_id=3001,
            quantity=Decimal("4.0000"),
            source_type="ON_HAND",
            create_by_id="tester",
            update_by_id="tester",
        )
        OperationsAllocationLine.objects.create(
            package_id=92,
            item_id=101,
            source_warehouse_id=5,
            batch_id=5001,
            quantity=Decimal("6.0000"),
            source_type="ON_HAND",
            create_by_id="tester",
            update_by_id="tester",
        )

        warehouse_candidates = {
            3: [
                {
                    "batch_id": 3001,
                    "inventory_id": 3,
                    "item_id": 101,
                    "batch_no": "B-3001",
                    "batch_date": date(2026, 3, 24),
                    "expiry_date": None,
                    "usable_qty": Decimal("4.0000"),
                    "reserved_qty": Decimal("0.0000"),
                    "available_qty": Decimal("4.0000"),
                    "uom_code": "EA",
                    "source_type": "ON_HAND",
                    "source_record_id": None,
                    "warehouse_name": "Warehouse 3",
                    "can_expire_flag": False,
                    "issuance_order": "FIFO",
                    "item_code": "TARP001",
                    "item_name": "Tarpaulin",
                }
            ],
            5: [
                {
                    "batch_id": 5001,
                    "inventory_id": 5,
                    "item_id": 101,
                    "batch_no": "B-5001",
                    "batch_date": date(2026, 3, 23),
                    "expiry_date": None,
                    "usable_qty": Decimal("6.0000"),
                    "reserved_qty": Decimal("0.0000"),
                    "available_qty": Decimal("6.0000"),
                    "uom_code": "EA",
                    "source_type": "ON_HAND",
                    "source_record_id": None,
                    "warehouse_name": "Warehouse 5",
                    "can_expire_flag": False,
                    "issuance_order": "FIFO",
                    "item_code": "TARP001",
                    "item_name": "Tarpaulin",
                }
            ],
        }
        fetch_candidates_mock.side_effect = (
            lambda warehouse_id, _item_id, as_of_date=None: list(
                warehouse_candidates.get(warehouse_id, [])
            )
        )

        result = operations_service.get_package_allocation_options(
            80,
            source_warehouse_id=3,
            tenant_context=self.tenant_ctx,
        )

        self.assertEqual(len(result["items"]), 1)
        item_group = result["items"][0]
        self.assertEqual(item_group["source_warehouse_id"], 5)
        self.assertEqual(item_group["selected_warehouse_ids"], [5, 3])
        self.assertEqual(item_group["draft_selected_qty"], "10.0000")
        self.assertEqual(item_group["effective_remaining_qty"], "0.0000")
        self.assertEqual(item_group["remaining_shortfall_qty"], "0.0000")
        self.assertFalse(item_group["continuation_recommended"])
        self.assertEqual(item_group["suggested_allocations"], [])
        self.assertEqual(
            sorted(
                (candidate["inventory_id"], candidate["batch_id"])
                for candidate in item_group["candidates"]
            ),
            [(3, 3001), (5, 5001)],
        )
        candidates_by_warehouse = {
            candidate["inventory_id"]: candidate for candidate in item_group["candidates"]
        }
        # The response must advertise the pre-draft physical availability so the
        # frontend can render every warehouse card and replay the greedy plan.
        self.assertEqual(candidates_by_warehouse[3]["available_qty"], "4.0000")
        self.assertEqual(candidates_by_warehouse[3]["usable_qty"], "4.0000")
        self.assertEqual(candidates_by_warehouse[5]["available_qty"], "6.0000")
        self.assertEqual(candidates_by_warehouse[5]["usable_qty"], "6.0000")

    @patch("operations.services.data_access.get_warehouses_with_stock")
    @patch("operations.services.can_access_warehouse")
    @patch("operations.services._fetch_batch_candidates")
    @patch("operations.services.Item.objects.filter")
    @patch("operations.services._load_request")
    @patch("operations.services._request_summary", return_value={"reliefrqst_id": 80})
    @patch(
        "operations.services._request_item_rows_for_allocation",
        return_value=[
            {"item_id": 101, "request_qty": "12.0000", "issue_qty": "2.0000", "urgency_ind": "H"}
        ],
    )
    def test_package_options_filter_rehydrated_draft_warehouses_by_tenant_access(
        self,
        _request_rows_mock,
        _request_summary_mock,
        load_request_mock,
        item_filter_mock,
        fetch_candidates_mock,
        can_access_warehouse_mock,
        get_warehouses_with_stock_mock,
    ) -> None:
        load_request_mock.return_value = self.request_stub
        item = SimpleNamespace(
            item_id=101,
            item_code="TARP001",
            item_name="Tarpaulin",
            issuance_order="FIFO",
            can_expire_flag=False,
        )
        item_queryset = MagicMock()
        item_queryset.__iter__.return_value = iter([item])
        item_queryset.first.return_value = item
        item_filter_mock.return_value = item_queryset
        get_warehouses_with_stock_mock.return_value = (
            {
                101: [
                    {"warehouse_id": 3, "warehouse_name": "Warehouse 3", "available_qty": 4.0}
                ]
            },
            [],
        )
        can_access_warehouse_mock.side_effect = (
            lambda tenant_context, warehouse_id, write=True: warehouse_id != 5
        )

        self._create_draft_package_record(
            relief_request_id=80,
            package_id=91,
            source_warehouse_id=3,
        )
        OperationsAllocationLine.objects.create(
            package_id=91,
            item_id=101,
            source_warehouse_id=3,
            batch_id=3001,
            quantity=Decimal("2.0000"),
            source_type="ON_HAND",
            create_by_id="tester",
            update_by_id="tester",
        )
        OperationsAllocationLine.objects.create(
            package_id=91,
            item_id=101,
            source_warehouse_id=5,
            batch_id=5001,
            quantity=Decimal("1.0000"),
            source_type="ON_HAND",
            create_by_id="tester",
            update_by_id="tester",
        )

        warehouse_candidates = {
            3: [
                {
                    "batch_id": 3001,
                    "inventory_id": 3,
                    "item_id": 101,
                    "batch_no": "B-3001",
                    "batch_date": date(2026, 3, 24),
                    "expiry_date": None,
                    "usable_qty": Decimal("4.0000"),
                    "reserved_qty": Decimal("0.0000"),
                    "available_qty": Decimal("4.0000"),
                    "uom_code": "EA",
                    "source_type": "ON_HAND",
                    "source_record_id": None,
                    "warehouse_name": "Warehouse 3",
                    "can_expire_flag": False,
                    "issuance_order": "FIFO",
                    "item_code": "TARP001",
                    "item_name": "Tarpaulin",
                }
            ],
            5: [
                {
                    "batch_id": 5001,
                    "inventory_id": 5,
                    "item_id": 101,
                    "batch_no": "B-5001",
                    "batch_date": date(2026, 3, 23),
                    "expiry_date": None,
                    "usable_qty": Decimal("6.0000"),
                    "reserved_qty": Decimal("0.0000"),
                    "available_qty": Decimal("6.0000"),
                    "uom_code": "EA",
                    "source_type": "ON_HAND",
                    "source_record_id": None,
                    "warehouse_name": "Warehouse 5",
                    "can_expire_flag": False,
                    "issuance_order": "FIFO",
                    "item_code": "TARP001",
                    "item_name": "Tarpaulin",
                }
            ],
        }
        fetch_candidates_mock.side_effect = (
            lambda warehouse_id, _item_id, as_of_date=None: list(
                warehouse_candidates.get(warehouse_id, [])
            )
        )

        result = operations_service.get_package_allocation_options(
            80,
            source_warehouse_id=3,
            tenant_context=self.tenant_ctx,
        )

        item_group = result["items"][0]
        self.assertEqual(
            [candidate["inventory_id"] for candidate in item_group["candidates"]],
            [3],
        )
        fetched_warehouses = sorted(
            {call.args[0] for call in fetch_candidates_mock.call_args_list}
        )
        self.assertEqual(fetched_warehouses, [3])

    @patch("operations.services.data_access.get_warehouses_with_stock")
    @patch("operations.services.can_access_warehouse", return_value=True)
    @patch("operations.services._fetch_batch_candidates")
    @patch("operations.services.Item.objects.filter")
    @patch("operations.services._load_request")
    @patch("operations.services._request_summary", return_value={"reliefrqst_id": 80})
    @patch(
        "operations.services._request_item_rows_for_allocation",
        return_value=[
            {"item_id": 101, "request_qty": "12.0000", "issue_qty": "2.0000", "urgency_ind": "H"}
        ],
    )
    def test_package_options_without_draft_lines_unchanged(
        self,
        _request_rows_mock,
        _request_summary_mock,
        load_request_mock,
        item_filter_mock,
        fetch_candidates_mock,
        _can_access_warehouse_mock,
        get_warehouses_with_stock_mock,
    ) -> None:
        """Regression guard: the merge path stays inert when no draft lines exist."""
        load_request_mock.return_value = self.request_stub
        item = SimpleNamespace(
            item_id=101,
            item_code="TARP001",
            item_name="Tarpaulin",
            issuance_order="FIFO",
            can_expire_flag=False,
        )
        item_queryset = MagicMock()
        item_queryset.__iter__.return_value = iter([item])
        item_queryset.first.return_value = item
        item_filter_mock.return_value = item_queryset
        get_warehouses_with_stock_mock.return_value = (
            {
                101: [
                    {"warehouse_id": 3, "warehouse_name": "Warehouse 3", "available_qty": 4.0}
                ]
            },
            [],
        )
        fetch_candidates_mock.side_effect = lambda warehouse_id, _item_id, as_of_date=None: (
            [
                {
                    "batch_id": 3001,
                    "inventory_id": 3,
                    "item_id": 101,
                    "batch_no": "B-3001",
                    "batch_date": date(2026, 3, 24),
                    "expiry_date": None,
                    "usable_qty": Decimal("4.0000"),
                    "reserved_qty": Decimal("0.0000"),
                    "available_qty": Decimal("4.0000"),
                    "uom_code": "EA",
                    "source_type": "ON_HAND",
                    "source_record_id": None,
                    "warehouse_name": "Warehouse 3",
                    "can_expire_flag": False,
                    "issuance_order": "FIFO",
                    "item_code": "TARP001",
                    "item_name": "Tarpaulin",
                }
            ]
            if warehouse_id == 3
            else []
        )

        result = operations_service.get_package_allocation_options(
            80,
            source_warehouse_id=3,
        )

        self.assertEqual(len(result["items"]), 1)
        item_group = result["items"][0]
        self.assertEqual(
            [candidate["inventory_id"] for candidate in item_group["candidates"]],
            [3],
        )
        fetched_warehouses = sorted(
            {call.args[0] for call in fetch_candidates_mock.call_args_list}
        )
        self.assertEqual(fetched_warehouses, [3])

    @patch("operations.services._fetch_batch_candidates")
    def test_warehouse_usable_surplus_uses_allocatable_available_qty_after_draft_adjustments(
        self,
        fetch_candidates_mock,
    ) -> None:
        item = SimpleNamespace(
            item_id=101,
            item_code="TARP001",
            item_name="Tarpaulin",
            issuance_order="FIFO",
            can_expire_flag=False,
        )
        fetch_candidates_mock.return_value = [
            {
                "batch_id": 3001,
                "inventory_id": 3,
                "item_id": 101,
                "batch_no": "B-3001",
                "batch_date": date(2026, 3, 24),
                "expiry_date": None,
                "usable_qty": Decimal("10.0000"),
                "reserved_qty": Decimal("4.0000"),
                "available_qty": Decimal("6.0000"),
                "uom_code": "EA",
                "source_type": "ON_HAND",
                "source_record_id": None,
                "warehouse_name": "Warehouse 3",
                "can_expire_flag": False,
                "issuance_order": "FIFO",
                "item_code": "TARP001",
                "item_name": "Tarpaulin",
            },
            {
                "batch_id": 3002,
                "inventory_id": 3,
                "item_id": 101,
                "batch_no": "B-3002",
                "batch_date": date(2026, 3, 25),
                "expiry_date": None,
                "usable_qty": Decimal("3.0000"),
                "reserved_qty": Decimal("0.0000"),
                "available_qty": Decimal("3.0000"),
                "uom_code": "EA",
                "source_type": "ON_HAND",
                "source_record_id": None,
                "warehouse_name": "Warehouse 3",
                "can_expire_flag": False,
                "issuance_order": "FIFO",
                "item_code": "TARP001",
                "item_name": "Tarpaulin",
            },
        ]

        result = operations_service._warehouse_usable_surplus_for_item(
            3,
            101,
            item=item,
            as_of_date=date(2026, 3, 27),
            draft_allocations=[
                {
                    "item_id": 101,
                    "inventory_id": 3,
                    "batch_id": 3001,
                    "quantity": "2.0000",
                    "source_type": "ON_HAND",
                    "source_record_id": None,
                }
            ],
        )

        self.assertEqual(result, Decimal("7.0000"))

    @patch("operations.services.data_access.get_warehouses_with_stock")
    @patch("operations.services.can_access_warehouse")
    @patch("operations.services._fetch_batch_candidates")
    @patch("operations.services.Item.objects.filter")
    @patch("operations.services._load_request")
    @patch("operations.services._request_summary", return_value={"reliefrqst_id": 80})
    @patch(
        "operations.services._request_item_rows_for_allocation",
        return_value=[
            {"item_id": 101, "request_qty": "12.0000", "issue_qty": "2.0000", "urgency_ind": "H"}
        ],
    )
    def test_package_options_skip_inaccessible_primary_warehouse_and_merge_authorized_draft_warehouses(
        self,
        _request_rows_mock,
        _request_summary_mock,
        load_request_mock,
        item_filter_mock,
        fetch_candidates_mock,
        can_access_warehouse_mock,
        get_warehouses_with_stock_mock,
    ) -> None:
        load_request_mock.return_value = self.request_stub
        item = SimpleNamespace(
            item_id=101,
            item_code="TARP001",
            item_name="Tarpaulin",
            issuance_order="FIFO",
            can_expire_flag=False,
        )
        item_queryset = MagicMock()
        item_queryset.__iter__.return_value = iter([item])
        item_queryset.first.return_value = item
        item_filter_mock.return_value = item_queryset
        get_warehouses_with_stock_mock.return_value = ({101: []}, [])
        can_access_warehouse_mock.side_effect = (
            lambda tenant_context, warehouse_id, write=True: warehouse_id == 5
        )

        self._create_draft_package_record(
            relief_request_id=80,
            package_id=91,
            source_warehouse_id=3,
        )
        OperationsAllocationLine.objects.create(
            package_id=91,
            item_id=101,
            source_warehouse_id=5,
            batch_id=5001,
            quantity=Decimal("1.0000"),
            source_type="ON_HAND",
            create_by_id="tester",
            update_by_id="tester",
        )

        warehouse_candidates = {
            5: [
                {
                    "batch_id": 5001,
                    "inventory_id": 5,
                    "item_id": 101,
                    "batch_no": "B-5001",
                    "batch_date": date(2026, 3, 23),
                    "expiry_date": None,
                    "usable_qty": Decimal("6.0000"),
                    "reserved_qty": Decimal("0.0000"),
                    "available_qty": Decimal("6.0000"),
                    "uom_code": "EA",
                    "source_type": "ON_HAND",
                    "source_record_id": None,
                    "warehouse_name": "Warehouse 5",
                    "can_expire_flag": False,
                    "issuance_order": "FIFO",
                    "item_code": "TARP001",
                    "item_name": "Tarpaulin",
                }
            ],
        }
        fetch_candidates_mock.side_effect = (
            lambda warehouse_id, _item_id, as_of_date=None: list(
                warehouse_candidates.get(warehouse_id, [])
            )
        )

        result = operations_service.get_package_allocation_options(
            80,
            source_warehouse_id=3,
            tenant_context=self.tenant_ctx,
        )

        item_group = result["items"][0]
        self.assertEqual(
            [candidate["inventory_id"] for candidate in item_group["candidates"]],
            [5],
        )
        fetched_warehouses = sorted(
            {call.args[0] for call in fetch_candidates_mock.call_args_list}
        )
        self.assertEqual(fetched_warehouses, [5])

    @patch("operations.services.data_access.get_warehouses_with_stock")
    @patch("operations.services.can_access_warehouse", return_value=True)
    @patch("operations.services._fetch_batch_candidates")
    @patch("operations.services.Item.objects.filter")
    @patch(
        "operations.services._request_item_rows_for_allocation",
        return_value=[
            {"item_id": 101, "request_qty": "12.0000", "issue_qty": "2.0000", "urgency_ind": "H"}
        ],
    )
    def test_preview_adjusts_candidates_and_alternates_for_draft_allocations(
        self,
        _request_rows_mock,
        item_filter_mock,
        fetch_candidates_mock,
        _can_access_warehouse_mock,
        get_warehouses_with_stock_mock,
    ) -> None:
        item = SimpleNamespace(
            item_id=101,
            item_code="MASK001",
            item_name="Face Mask",
            issuance_order="FIFO",
            can_expire_flag=False,
        )
        item_queryset = Mock()
        item_queryset.first.return_value = item
        item_filter_mock.return_value = item_queryset

        get_warehouses_with_stock_mock.return_value = (
            {
                101: [
                    {"warehouse_id": 1, "warehouse_name": "Warehouse 1", "available_qty": 99.0},
                    {"warehouse_id": 5, "warehouse_name": "Warehouse 5", "available_qty": 6.0},
                    {"warehouse_id": 7, "warehouse_name": "Warehouse 7", "available_qty": 3.0},
                ]
            },
            [],
        )

        warehouse_candidates = {
            1: [
                {
                    "batch_id": 1001,
                    "inventory_id": 1,
                    "item_id": 101,
                    "batch_no": "B-1001",
                    "batch_date": date(2026, 3, 25),
                    "expiry_date": None,
                    "usable_qty": Decimal("4.0000"),
                    "reserved_qty": Decimal("0.0000"),
                    "available_qty": Decimal("4.0000"),
                    "uom_code": "EA",
                    "source_type": "ON_HAND",
                    "source_record_id": None,
                    "warehouse_name": "Warehouse 1",
                    "can_expire_flag": False,
                    "issuance_order": "FIFO",
                    "item_code": "MASK001",
                    "item_name": "Face Mask",
                },
                {
                    "batch_id": 1002,
                    "inventory_id": 1,
                    "item_id": 101,
                    "batch_no": "B-1002",
                    "batch_date": date(2026, 3, 26),
                    "expiry_date": None,
                    "usable_qty": Decimal("2.0000"),
                    "reserved_qty": Decimal("0.0000"),
                    "available_qty": Decimal("2.0000"),
                    "uom_code": "EA",
                    "source_type": "ON_HAND",
                    "source_record_id": None,
                    "warehouse_name": "Warehouse 1",
                    "can_expire_flag": False,
                    "issuance_order": "FIFO",
                    "item_code": "MASK001",
                    "item_name": "Face Mask",
                },
            ],
            5: [
                {
                    "batch_id": 5001,
                    "inventory_id": 5,
                    "item_id": 101,
                    "batch_no": "B-5001",
                    "batch_date": date(2026, 3, 23),
                    "expiry_date": None,
                    "usable_qty": Decimal("6.0000"),
                    "reserved_qty": Decimal("0.0000"),
                    "available_qty": Decimal("6.0000"),
                    "uom_code": "EA",
                    "source_type": "ON_HAND",
                    "source_record_id": None,
                    "warehouse_name": "Warehouse 5",
                    "can_expire_flag": False,
                    "issuance_order": "FIFO",
                    "item_code": "MASK001",
                    "item_name": "Face Mask",
                }
            ],
            7: [
                {
                    "batch_id": 7001,
                    "inventory_id": 7,
                    "item_id": 101,
                    "batch_no": "B-7001",
                    "batch_date": date(2026, 3, 22),
                    "expiry_date": None,
                    "usable_qty": Decimal("3.0000"),
                    "reserved_qty": Decimal("0.0000"),
                    "available_qty": Decimal("3.0000"),
                    "uom_code": "EA",
                    "source_type": "ON_HAND",
                    "source_record_id": None,
                    "warehouse_name": "Warehouse 7",
                    "can_expire_flag": False,
                    "issuance_order": "FIFO",
                    "item_code": "MASK001",
                    "item_name": "Face Mask",
                }
            ],
        }
        fetch_candidates_mock.side_effect = (
            lambda warehouse_id, _item_id, as_of_date=None: warehouse_candidates.get(warehouse_id, [])
        )

        result = operations_service.get_item_allocation_preview(
            80,
            101,
            source_warehouse_id=1,
            tenant_context=self.tenant_ctx,
            draft_allocations=[
                {
                    "item_id": 101,
                    "inventory_id": 1,
                    "batch_id": 1001,
                    "quantity": "1.0000",
                    "source_type": "ON_HAND",
                    "source_record_id": None,
                },
                {
                    "item_id": 101,
                    "inventory_id": 1,
                    "batch_id": 1002,
                    "quantity": "2.0000",
                    "source_type": "ON_HAND",
                    "source_record_id": None,
                },
                {
                    "item_id": 101,
                    "inventory_id": 5,
                    "batch_id": 5001,
                    "quantity": "2.0000",
                    "source_type": "ON_HAND",
                    "source_record_id": None,
                },
            ],
        )

        self.assertEqual(result["remaining_qty"], "10.0000")
        self.assertEqual(result["draft_selected_qty"], "5.0000")
        self.assertEqual(result["effective_remaining_qty"], "5.0000")
        self.assertEqual(result["remaining_after_suggestion"], "0.0000")
        self.assertEqual(result["remaining_shortfall_qty"], "0.0000")
        self.assertFalse(result["continuation_recommended"])
        self.assertEqual(result["selected_warehouse_ids"], [5, 1])
        # Candidates reflect the pre-draft physical state so the UI can still
        # render every warehouse card, including batches the draft fully
        # consumed (batch 1002 has usable_qty=2 and draft qty=2 but must not
        # disappear from the response). The greedy suggestion below still
        # uses the adjusted quantities.
        self.assertEqual(len(result["candidates"]), 3)
        candidates_by_batch = {
            candidate["batch_id"]: candidate for candidate in result["candidates"]
        }
        self.assertEqual(candidates_by_batch[5001]["available_qty"], "6.0000")
        self.assertEqual(candidates_by_batch[5001]["usable_qty"], "6.0000")
        self.assertEqual(candidates_by_batch[1001]["available_qty"], "4.0000")
        self.assertEqual(candidates_by_batch[1001]["usable_qty"], "4.0000")
        self.assertEqual(candidates_by_batch[1002]["available_qty"], "2.0000")
        self.assertEqual(candidates_by_batch[1002]["usable_qty"], "2.0000")
        self.assertEqual(len(result["suggested_allocations"]), 2)
        self.assertEqual(
            [(row["inventory_id"], row["batch_id"], row["quantity"]) for row in result["suggested_allocations"]],
            [(5, 5001, "4.0000"), (1, 1001, "1.0000")],
        )
        self.assertEqual(result["alternate_warehouses"], [])

    @patch("operations.services.data_access.get_warehouses_with_stock")
    @patch("operations.services.can_access_warehouse", return_value=True)
    @patch("operations.services._fetch_batch_candidates")
    @patch("operations.services.Item.objects.filter")
    @patch(
        "operations.services._request_item_rows_for_allocation",
        return_value=[
            {"item_id": 101, "request_qty": "12.0000", "issue_qty": "2.0000", "urgency_ind": "H"}
        ],
    )
    def test_service_applies_item_draft_allocations_to_shortfall_and_alternates(
        self,
        _request_rows_mock,
        item_filter_mock,
        fetch_candidates_mock,
        _can_access_warehouse_mock,
        get_warehouses_with_stock_mock,
    ) -> None:
        item = SimpleNamespace(
            item_id=101,
            item_code="MASK001",
            item_name="Face Mask",
            issuance_order="FIFO",
            can_expire_flag=False,
        )
        item_queryset = Mock()
        item_queryset.first.return_value = item
        item_filter_mock.return_value = item_queryset

        get_warehouses_with_stock_mock.return_value = (
            {
                101: [
                    {"warehouse_id": 1, "warehouse_name": "Warehouse 1", "available_qty": 99.0},
                    {"warehouse_id": 5, "warehouse_name": "Warehouse 5", "available_qty": 6.0},
                    {"warehouse_id": 7, "warehouse_name": "Warehouse 7", "available_qty": 3.0},
                ]
            },
            [],
        )

        warehouse_candidates = {
            1: [
                {
                    "batch_id": 1001,
                    "inventory_id": 1,
                    "item_id": 101,
                    "batch_no": "B-1001",
                    "batch_date": date(2026, 3, 25),
                    "expiry_date": None,
                    "usable_qty": Decimal("4.0000"),
                    "reserved_qty": Decimal("0.0000"),
                    "available_qty": Decimal("4.0000"),
                    "uom_code": "EA",
                    "source_type": "ON_HAND",
                    "source_record_id": None,
                    "warehouse_name": "Warehouse 1",
                    "can_expire_flag": False,
                    "issuance_order": "FIFO",
                    "item_code": "MASK001",
                    "item_name": "Face Mask",
                },
                {
                    "batch_id": 1002,
                    "inventory_id": 1,
                    "item_id": 101,
                    "batch_no": "B-1002",
                    "batch_date": date(2026, 3, 26),
                    "expiry_date": None,
                    "usable_qty": Decimal("2.0000"),
                    "reserved_qty": Decimal("0.0000"),
                    "available_qty": Decimal("2.0000"),
                    "uom_code": "EA",
                    "source_type": "ON_HAND",
                    "source_record_id": None,
                    "warehouse_name": "Warehouse 1",
                    "can_expire_flag": False,
                    "issuance_order": "FIFO",
                    "item_code": "MASK001",
                    "item_name": "Face Mask",
                },
            ],
            5: [
                {
                    "batch_id": 5001,
                    "inventory_id": 5,
                    "item_id": 101,
                    "batch_no": "B-5001",
                    "batch_date": date(2026, 3, 23),
                    "expiry_date": None,
                    "usable_qty": Decimal("6.0000"),
                    "reserved_qty": Decimal("0.0000"),
                    "available_qty": Decimal("6.0000"),
                    "uom_code": "EA",
                    "source_type": "ON_HAND",
                    "source_record_id": None,
                    "warehouse_name": "Warehouse 5",
                    "can_expire_flag": False,
                    "issuance_order": "FIFO",
                    "item_code": "MASK001",
                    "item_name": "Face Mask",
                }
            ],
            7: [
                {
                    "batch_id": 7001,
                    "inventory_id": 7,
                    "item_id": 101,
                    "batch_no": "B-7001",
                    "batch_date": date(2026, 3, 22),
                    "expiry_date": None,
                    "usable_qty": Decimal("3.0000"),
                    "reserved_qty": Decimal("0.0000"),
                    "available_qty": Decimal("3.0000"),
                    "uom_code": "EA",
                    "source_type": "ON_HAND",
                    "source_record_id": None,
                    "warehouse_name": "Warehouse 7",
                    "can_expire_flag": False,
                    "issuance_order": "FIFO",
                    "item_code": "MASK001",
                    "item_name": "Face Mask",
                }
            ],
        }
        fetch_candidates_mock.side_effect = (
            lambda warehouse_id, _item_id, as_of_date=None: warehouse_candidates.get(warehouse_id, [])
        )

        result = operations_service.get_item_allocation_options(
            80,
            101,
            source_warehouse_id=1,
            tenant_context=self.tenant_ctx,
            draft_allocations=[
                {
                    "item_id": 101,
                    "inventory_id": 1,
                    "batch_id": 1001,
                    "quantity": "1.0000",
                    "source_type": "ON_HAND",
                    "source_record_id": None,
                },
                {
                    "item_id": 101,
                    "inventory_id": 1,
                    "batch_id": 1002,
                    "quantity": "2.0000",
                    "source_type": "ON_HAND",
                    "source_record_id": None,
                },
                {
                    "item_id": 101,
                    "inventory_id": 5,
                    "batch_id": 5001,
                    "quantity": "2.0000",
                    "source_type": "ON_HAND",
                    "source_record_id": None,
                },
            ],
        )

        self.assertEqual(result["remaining_qty"], "10.0000")
        self.assertEqual(result["remaining_after_suggestion"], "0.0000")
        self.assertEqual(result["remaining_shortfall_qty"], "0.0000")
        self.assertFalse(result["continuation_recommended"])
        self.assertEqual(result["selected_warehouse_ids"], [5, 1])
        # Candidates reflect the pre-draft physical state so the UI can still
        # render every warehouse card, including batches the draft fully
        # consumed. Batch 1002 has usable_qty=2 and draft qty=2 but must not
        # disappear from the response.
        self.assertEqual(len(result["candidates"]), 3)
        candidates_by_batch = {
            candidate["batch_id"]: candidate for candidate in result["candidates"]
        }
        self.assertEqual(
            candidates_by_batch[5001],
            {
                "batch_id": 5001,
                "inventory_id": 5,
                "item_id": 101,
                "batch_no": "B-5001",
                "batch_date": "2026-03-23",
                "expiry_date": None,
                "usable_qty": "6.0000",
                "reserved_qty": "0.0000",
                "available_qty": "6.0000",
                "uom_code": "EA",
                "source_type": "ON_HAND",
                "source_record_id": None,
                "warehouse_name": "Warehouse 5",
                "can_expire_flag": False,
                "issuance_order": "FIFO",
                "item_code": "MASK001",
                "item_name": "Face Mask",
            },
        )
        self.assertEqual(
            candidates_by_batch[1001],
            {
                "batch_id": 1001,
                "inventory_id": 1,
                "item_id": 101,
                "batch_no": "B-1001",
                "batch_date": "2026-03-25",
                "expiry_date": None,
                "usable_qty": "4.0000",
                "reserved_qty": "0.0000",
                "available_qty": "4.0000",
                "uom_code": "EA",
                "source_type": "ON_HAND",
                "source_record_id": None,
                "warehouse_name": "Warehouse 1",
                "can_expire_flag": False,
                "issuance_order": "FIFO",
                "item_code": "MASK001",
                "item_name": "Face Mask",
            },
        )
        self.assertEqual(
            candidates_by_batch[1002],
            {
                "batch_id": 1002,
                "inventory_id": 1,
                "item_id": 101,
                "batch_no": "B-1002",
                "batch_date": "2026-03-26",
                "expiry_date": None,
                "usable_qty": "2.0000",
                "reserved_qty": "0.0000",
                "available_qty": "2.0000",
                "uom_code": "EA",
                "source_type": "ON_HAND",
                "source_record_id": None,
                "warehouse_name": "Warehouse 1",
                "can_expire_flag": False,
                "issuance_order": "FIFO",
                "item_code": "MASK001",
                "item_name": "Face Mask",
            },
        )
        self.assertEqual(len(result["suggested_allocations"]), 2)
        self.assertEqual(
            [(row["inventory_id"], row["batch_id"], row["quantity"]) for row in result["suggested_allocations"]],
            [(5, 5001, "4.0000"), (1, 1001, "1.0000")],
        )
        self.assertEqual(result["alternate_warehouses"], [])

    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service.get_item_allocation_options")
    def test_item_not_in_request_raises_validation_error(
        self,
        get_item_options_mock,
        load_request_mock,
        get_agency_scope_mock,
    ) -> None:
        load_request_mock.return_value = self.request_stub
        get_agency_scope_mock.return_value = self.agency_scope
        get_item_options_mock.side_effect = OperationValidationError(
            {"item_id": "Item 999 is not part of request 80."}
        )

        with self.assertRaises(OperationValidationError):
            contract_services.get_item_allocation_options(
                80,
                999,
                source_warehouse_id=1,
                actor_id="fulfiller-1",
                actor_roles=["LOGISTICS_OFFICER"],
                tenant_context=self.tenant_ctx,
            )

    @patch("operations.contract_services._fetch_batch_candidates")
    @patch("operations.contract_services.can_access_warehouse", return_value=True)
    @patch("operations.contract_services.data_access.get_warehouses_with_stock")
    def test_build_item_warehouse_cards_ranks_fefo(
        self,
        get_warehouses_with_stock_mock,
        _can_access_warehouse_mock,
        fetch_candidates_mock,
    ) -> None:
        """FEFO items order warehouses by earliest-expiring batch, not alphabetically."""
        item = SimpleNamespace(
            item_id=202,
            item_code="MEDS001",
            item_name="Medical kit",
            issuance_order="FEFO",
            can_expire_flag=True,
        )
        get_warehouses_with_stock_mock.return_value = (
            {
                202: [
                    {"warehouse_id": 1, "warehouse_name": "Warehouse 1", "available_qty": 50.0},
                    {"warehouse_id": 2, "warehouse_name": "Warehouse 2", "available_qty": 50.0},
                    {"warehouse_id": 3, "warehouse_name": "Warehouse 3", "available_qty": 50.0},
                ]
            },
            [],
        )

        warehouse_candidates = {
            1: [
                {
                    "batch_id": 1101,
                    "inventory_id": 1,
                    "item_id": 202,
                    "batch_no": "B-1101",
                    "batch_date": date(2026, 3, 1),
                    "expiry_date": date(2026, 12, 31),  # latest expiry
                    "usable_qty": Decimal("50.0000"),
                    "reserved_qty": Decimal("0.0000"),
                    "available_qty": Decimal("50.0000"),
                    "uom_code": "EA",
                    "source_type": "ON_HAND",
                    "source_record_id": None,
                    "warehouse_name": "Warehouse 1",
                    "can_expire_flag": True,
                    "issuance_order": "FEFO",
                    "item_code": "MEDS001",
                    "item_name": "Medical kit",
                }
            ],
            2: [
                {
                    "batch_id": 2201,
                    "inventory_id": 2,
                    "item_id": 202,
                    "batch_no": "B-2201",
                    "batch_date": date(2026, 3, 1),
                    "expiry_date": date(2026, 5, 15),  # earliest expiry
                    "usable_qty": Decimal("50.0000"),
                    "reserved_qty": Decimal("0.0000"),
                    "available_qty": Decimal("50.0000"),
                    "uom_code": "EA",
                    "source_type": "ON_HAND",
                    "source_record_id": None,
                    "warehouse_name": "Warehouse 2",
                    "can_expire_flag": True,
                    "issuance_order": "FEFO",
                    "item_code": "MEDS001",
                    "item_name": "Medical kit",
                }
            ],
            3: [
                {
                    "batch_id": 3301,
                    "inventory_id": 3,
                    "item_id": 202,
                    "batch_no": "B-3301",
                    "batch_date": date(2026, 3, 1),
                    "expiry_date": date(2026, 8, 10),  # middle expiry
                    "usable_qty": Decimal("50.0000"),
                    "reserved_qty": Decimal("0.0000"),
                    "available_qty": Decimal("50.0000"),
                    "uom_code": "EA",
                    "source_type": "ON_HAND",
                    "source_record_id": None,
                    "warehouse_name": "Warehouse 3",
                    "can_expire_flag": True,
                    "issuance_order": "FEFO",
                    "item_code": "MEDS001",
                    "item_name": "Medical kit",
                }
            ],
        }
        fetch_candidates_mock.side_effect = (
            lambda warehouse_id, _item_id, as_of_date=None: list(
                warehouse_candidates.get(warehouse_id, [])
            )
        )

        cards = contract_services.build_item_warehouse_cards(
            item_id=202,
            remaining_qty=Decimal("60"),
            item=item,
            tenant_context=self.tenant_ctx,
        )

        self.assertEqual(len(cards), 3)
        # FEFO ranks warehouses by earliest expiry date: warehouse 2 → 3 → 1
        self.assertEqual([c["warehouse_id"] for c in cards], [2, 3, 1])
        self.assertEqual([c["rank"] for c in cards], [0, 1, 2])
        self.assertTrue(all(c["issuance_order"] == "FEFO" for c in cards))
        self.assertEqual([c["recommended"] for c in cards], [True, False, False])
        self.assertEqual(cards[0]["allocatable_available_qty"], "50.0000")
        self.assertEqual(
            cards[0]["ranking_context"],
            {
                "basis": "FEFO",
                "top_batch_id": 2201,
                "top_batch_no": "B-2201",
                "top_batch_date": "2026-03-01",
                "top_expiry_date": "2026-05-15",
            },
        )
        self.assertEqual(
            cards[0]["batches"][0],
            {
                "batch_id": 2201,
                "inventory_id": 2,
                "batch_no": "B-2201",
                "batch_date": "2026-03-01",
                "expiry_date": "2026-05-15",
                "available_qty": "50.0000",
                "usable_qty": "50.0000",
                "reserved_qty": "0.0000",
                "uom_code": "EA",
                "source_type": "ON_HAND",
                "source_record_id": None,
            },
        )

    @patch("operations.contract_services._fetch_batch_candidates")
    @patch("operations.contract_services.can_access_warehouse", return_value=True)
    @patch("operations.contract_services.data_access.get_warehouses_with_stock")
    def test_build_item_warehouse_cards_greedy_suggested_qty(
        self,
        get_warehouses_with_stock_mock,
        _can_access_warehouse_mock,
        fetch_candidates_mock,
    ) -> None:
        """The top-ranked warehouse is greedily filled first; subsequent cards take the remainder."""
        item = SimpleNamespace(
            item_id=303,
            item_code="TARP001",
            item_name="Tarpaulin",
            issuance_order="FIFO",
            can_expire_flag=False,
        )
        get_warehouses_with_stock_mock.return_value = (
            {
                303: [
                    {"warehouse_id": 1, "warehouse_name": "Warehouse 1", "available_qty": 30.0},
                    {"warehouse_id": 2, "warehouse_name": "Warehouse 2", "available_qty": 80.0},
                    {"warehouse_id": 3, "warehouse_name": "Warehouse 3", "available_qty": 200.0},
                ]
            },
            [],
        )

        warehouse_candidates = {
            1: [
                {
                    "batch_id": 1301,
                    "inventory_id": 1,
                    "item_id": 303,
                    "batch_no": "B-1301",
                    "batch_date": date(2026, 1, 10),  # earliest batch → ranks first FIFO
                    "expiry_date": None,
                    "usable_qty": Decimal("30.0000"),
                    "reserved_qty": Decimal("0.0000"),
                    "available_qty": Decimal("30.0000"),
                    "uom_code": "EA",
                    "source_type": "ON_HAND",
                    "source_record_id": None,
                    "warehouse_name": "Warehouse 1",
                    "can_expire_flag": False,
                    "issuance_order": "FIFO",
                    "item_code": "TARP001",
                    "item_name": "Tarpaulin",
                }
            ],
            2: [
                {
                    "batch_id": 2301,
                    "inventory_id": 2,
                    "item_id": 303,
                    "batch_no": "B-2301",
                    "batch_date": date(2026, 2, 15),
                    "expiry_date": None,
                    "usable_qty": Decimal("80.0000"),
                    "reserved_qty": Decimal("0.0000"),
                    "available_qty": Decimal("80.0000"),
                    "uom_code": "EA",
                    "source_type": "ON_HAND",
                    "source_record_id": None,
                    "warehouse_name": "Warehouse 2",
                    "can_expire_flag": False,
                    "issuance_order": "FIFO",
                    "item_code": "TARP001",
                    "item_name": "Tarpaulin",
                }
            ],
            3: [
                {
                    "batch_id": 3301,
                    "inventory_id": 3,
                    "item_id": 303,
                    "batch_no": "B-3301",
                    "batch_date": date(2026, 3, 20),  # most recent batch → last FIFO
                    "expiry_date": None,
                    "usable_qty": Decimal("200.0000"),
                    "reserved_qty": Decimal("0.0000"),
                    "available_qty": Decimal("200.0000"),
                    "uom_code": "EA",
                    "source_type": "ON_HAND",
                    "source_record_id": None,
                    "warehouse_name": "Warehouse 3",
                    "can_expire_flag": False,
                    "issuance_order": "FIFO",
                    "item_code": "TARP001",
                    "item_name": "Tarpaulin",
                }
            ],
        }
        fetch_candidates_mock.side_effect = (
            lambda warehouse_id, _item_id, as_of_date=None: list(
                warehouse_candidates.get(warehouse_id, [])
            )
        )

        cards = contract_services.build_item_warehouse_cards(
            item_id=303,
            remaining_qty=Decimal("150"),
            item=item,
            tenant_context=self.tenant_ctx,
        )

        self.assertEqual(len(cards), 3)
        self.assertEqual([c["warehouse_id"] for c in cards], [1, 2, 3])
        # Greedy fill: 30 (all of WH1) + 80 (all of WH2) + 40 (remainder from WH3) = 150
        self.assertEqual(cards[0]["suggested_qty"], "30.0000")
        self.assertEqual(cards[1]["suggested_qty"], "80.0000")
        self.assertEqual(cards[2]["suggested_qty"], "40.0000")
        self.assertEqual(cards[0]["total_available"], "30.0000")
        self.assertEqual(cards[1]["total_available"], "80.0000")
        self.assertEqual(cards[2]["total_available"], "200.0000")
        self.assertTrue(all(c["issuance_order"] == "FIFO" for c in cards))
        # Greedy should have stopped at the requested qty, never over-allocating
        total_suggested = sum(Decimal(c["suggested_qty"]) for c in cards)
        self.assertEqual(total_suggested, Decimal("150.0000"))

    @patch("operations.contract_services._fetch_batch_candidates")
    @patch("operations.contract_services.can_access_warehouse")
    @patch("operations.contract_services.data_access.get_warehouses_with_stock")
    def test_build_item_warehouse_cards_excludes_unauthorized_warehouses(
        self,
        get_warehouses_with_stock_mock,
        can_access_warehouse_mock,
        fetch_candidates_mock,
    ) -> None:
        """Warehouses outside the caller's tenant scope never reach the card list."""
        item = SimpleNamespace(
            item_id=404,
            item_code="WATER001",
            item_name="Water purification tablet",
            issuance_order="FIFO",
            can_expire_flag=False,
        )
        get_warehouses_with_stock_mock.return_value = (
            {
                404: [
                    {"warehouse_id": 1, "warehouse_name": "Warehouse 1", "available_qty": 20.0},
                    {"warehouse_id": 9, "warehouse_name": "Warehouse 9", "available_qty": 40.0},
                ]
            },
            [],
        )
        # Warehouse 9 is the forbidden one (different tenant)
        can_access_warehouse_mock.side_effect = (
            lambda _ctx, warehouse_id, write=False: warehouse_id != 9
        )
        fetch_candidates_mock.return_value = [
            {
                "batch_id": 1401,
                "inventory_id": 1,
                "item_id": 404,
                "batch_no": "B-1401",
                "batch_date": date(2026, 3, 1),
                "expiry_date": None,
                "usable_qty": Decimal("20.0000"),
                "reserved_qty": Decimal("0.0000"),
                "available_qty": Decimal("20.0000"),
                "uom_code": "EA",
                "source_type": "ON_HAND",
                "source_record_id": None,
                "warehouse_name": "Warehouse 1",
                "can_expire_flag": False,
                "issuance_order": "FIFO",
                "item_code": "WATER001",
                "item_name": "Water purification tablet",
            }
        ]

        cards = contract_services.build_item_warehouse_cards(
            item_id=404,
            remaining_qty=Decimal("30"),
            item=item,
            tenant_context=self.tenant_ctx,
        )

        card_ids = [c["warehouse_id"] for c in cards]
        self.assertIn(1, card_ids)
        self.assertNotIn(9, card_ids)
        # Remaining (30) exceeds available (20) → suggested is capped at total_available
        self.assertEqual(cards[0]["suggested_qty"], "20.0000")


class MultiWarehouseDualWriteTests(TestCase):
    """Tests that dual-write populates OperationsAllocationLine on commit."""

    def setUp(self) -> None:
        from operations.models import OperationsAllocationLine

        self.OperationsAllocationLine = OperationsAllocationLine
        self.tenant_ctx = _tenant_context(tenant_id=20, tenant_code="FFP", tenant_type="EXTERNAL")
        self.agency_scope = operations_policy.AgencyScope(
            agency_id=501,
            agency_name="FFP Shelter",
            agency_type="SHELTER",
            warehouse_id=11,
            tenant_id=20,
            tenant_code="FFP",
            tenant_name="Food For The Poor",
            tenant_type="EXTERNAL",
        )
        self.request_stub = SimpleNamespace(
            reliefrqst_id=81,
            agency_id=501,
            tracking_no="RQ00081",
            eligible_event_id=12,
            request_date=date(2026, 3, 26),
            urgency_ind="H",
            rqst_notes_text="Dual write test",
            create_by_id="requester-1",
            create_dtime=datetime(2026, 3, 26, 9, 0, 0),
            review_by_id=None,
            review_dtime=None,
            status_code=3,
        )
        self.package_stub = SimpleNamespace(
            reliefpkg_id=91,
            tracking_no="PK00091",
            reliefrqst_id=81,
            agency_id=501,
            eligible_event_id=12,
            dispatch_dtime=None,
            to_inventory_id=8,
            transport_mode=None,
            comments_text=None,
            status_code="P",
            received_dtime=None,
            received_by_id=None,
            update_by_id="locker-1",
            update_dtime=datetime(2026, 3, 26, 10, 0, 0),
            version_nbr=1,
            save=lambda **kwargs: None,
        )
        fully_dispatched_patcher = patch(
            "operations.contract_services._request_fully_dispatched",
            return_value=False,
        )
        fully_dispatched_patcher.start()
        self.addCleanup(fully_dispatched_patcher.stop)

    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service._current_package_for_request")
    @patch("operations.contract_services.legacy_service.save_package")
    def test_dual_write_creates_allocation_lines(
        self,
        save_package_mock,
        current_package_mock,
        load_request_mock,
        get_agency_scope_mock,
    ) -> None:
        load_request_mock.return_value = self.request_stub
        current_package_mock.return_value = self.package_stub
        get_agency_scope_mock.return_value = self.agency_scope
        save_package_mock.return_value = {
            "status": "COMMITTED",
            "reliefpkg_id": 91,
            "allocation_lines": [
                {"item_id": 101, "inventory_id": 1, "batch_id": 10, "quantity": "20.0000"},
                {"item_id": 102, "inventory_id": 2, "batch_id": 20, "quantity": "10.0000"},
            ],
        }

        payload = {
            "source_warehouse_id": 1,
            "allocations": [
                {"item_id": 101, "inventory_id": 1, "batch_id": 10, "quantity": "20.0000", "source_type": "ON_HAND"},
                {"item_id": 102, "inventory_id": 2, "batch_id": 20, "quantity": "10.0000", "source_type": "ON_HAND"},
            ],
        }

        contract_services.save_package(
            81,
            payload=payload,
            actor_id="fulfiller-1",
            actor_roles=["LOGISTICS_OFFICER"],
            tenant_context=self.tenant_ctx,
        )

        lines = list(
            self.OperationsAllocationLine.objects.filter(
                package__package_id=91
            ).order_by("item_id")
        )
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0].item_id, 101)
        self.assertEqual(lines[0].source_warehouse_id, 1)
        self.assertEqual(lines[0].batch_id, 10)
        self.assertEqual(lines[1].item_id, 102)
        self.assertEqual(lines[1].source_warehouse_id, 2)
        self.assertEqual(lines[1].batch_id, 20)

    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service._current_package_for_request")
    @patch("operations.contract_services.legacy_service.save_package")
    def test_dual_write_replaces_old_lines_on_update(
        self,
        save_package_mock,
        current_package_mock,
        load_request_mock,
        get_agency_scope_mock,
    ) -> None:
        load_request_mock.return_value = self.request_stub
        current_package_mock.return_value = self.package_stub
        get_agency_scope_mock.return_value = self.agency_scope

        # Create a package record to host allocation lines.
        request_record = OperationsReliefRequest.objects.create(
            relief_request_id=81,
            request_no="RQ00081",
            requesting_tenant_id=20,
            beneficiary_tenant_id=20,
            beneficiary_agency_id=501,
            origin_mode="SELF",
            request_date=date(2026, 3, 26),
            urgency_code="H",
            status_code="APPROVED_FOR_FULFILLMENT",
            create_by_id="tester",
            update_by_id="tester",
        )
        pkg_record = OperationsPackage.objects.create(
            package_id=91,
            package_no="PK00091",
            relief_request=request_record,
            status_code="COMMITTED",
            create_by_id="tester",
            update_by_id="tester",
        )
        # Seed an old line that should be replaced.
        self.OperationsAllocationLine.objects.create(
            package=pkg_record,
            item_id=999,
            source_warehouse_id=99,
            batch_id=99,
            quantity=5,
            create_by_id="old",
            update_by_id="old",
        )

        save_package_mock.return_value = {"status": "COMMITTED", "reliefpkg_id": 91, "allocation_lines": []}

        payload = {
            "allocations": [
                {"item_id": 101, "inventory_id": 1, "batch_id": 10, "quantity": "15.0000"},
            ],
        }

        contract_services.save_package(
            81,
            payload=payload,
            actor_id="fulfiller-1",
            actor_roles=["LOGISTICS_OFFICER"],
            tenant_context=self.tenant_ctx,
        )

        lines = list(self.OperationsAllocationLine.objects.filter(package=pkg_record))
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0].item_id, 101)
        # Old line (item 999) should be gone.
        self.assertFalse(self.OperationsAllocationLine.objects.filter(item_id=999).exists())

    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service._current_package_for_request")
    @patch("operations.contract_services.legacy_service.save_package")
    def test_dual_write_rejects_invalid_allocation_rows_before_legacy_write(
        self,
        save_package_mock,
        current_package_mock,
        load_request_mock,
        get_agency_scope_mock,
    ) -> None:
        load_request_mock.return_value = self.request_stub
        current_package_mock.return_value = self.package_stub
        get_agency_scope_mock.return_value = self.agency_scope

        with self.assertRaises(OperationValidationError) as raised:
            contract_services.save_package(
                81,
                payload={
                    "allocations": [
                        {"item_id": 101, "inventory_id": 1, "batch_id": 10, "quantity": "bad-qty"},
                    ],
                },
                actor_id="fulfiller-1",
                actor_roles=["LOGISTICS_OFFICER"],
                tenant_context=self.tenant_ctx,
            )

        self.assertIn("allocations[0].quantity", raised.exception.errors)
        save_package_mock.assert_not_called()

    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service._current_package_for_request")
    @patch("operations.contract_services.legacy_service.save_package")
    def test_dual_write_rejects_duplicate_allocation_rows_before_legacy_write(
        self,
        save_package_mock,
        current_package_mock,
        load_request_mock,
        get_agency_scope_mock,
    ) -> None:
        load_request_mock.return_value = self.request_stub
        current_package_mock.return_value = self.package_stub
        get_agency_scope_mock.return_value = self.agency_scope

        with self.assertRaises(OperationValidationError) as raised:
            contract_services.save_package(
                81,
                payload={
                    "allocations": [
                        {"item_id": 101, "inventory_id": 1, "batch_id": 10, "quantity": "5.0000"},
                        {"item_id": 101, "inventory_id": 1, "batch_id": 10, "quantity": "2.0000"},
                    ],
                },
                actor_id="fulfiller-1",
                actor_roles=["LOGISTICS_OFFICER"],
                tenant_context=self.tenant_ctx,
            )

        self.assertIn("allocations[1]", raised.exception.errors)
        save_package_mock.assert_not_called()

    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._load_request")
    @patch("operations.contract_services.legacy_service._current_package_for_request")
    @patch("operations.contract_services.legacy_service.save_package")
    def test_dual_write_rejects_override_assignment_for_non_manager_outside_tenant_scope(
        self,
        save_package_mock,
        current_package_mock,
        load_request_mock,
        get_agency_scope_mock,
    ) -> None:
        load_request_mock.return_value = self.request_stub
        current_package_mock.return_value = self.package_stub
        get_agency_scope_mock.return_value = self.agency_scope

        OperationsReliefRequest.objects.create(
            relief_request_id=81,
            request_no="RQ00081",
            requesting_tenant_id=30,
            beneficiary_tenant_id=30,
            beneficiary_agency_id=501,
            origin_mode="SELF",
            request_date=date(2026, 3, 26),
            urgency_code="H",
            status_code=REQUEST_STATUS_APPROVED_FOR_FULFILLMENT,
            create_by_id="tester",
            update_by_id="tester",
        )
        OperationsQueueAssignment.objects.create(
            queue_code=QUEUE_CODE_OVERRIDE,
            entity_type="RELIEF_REQUEST",
            entity_id=81,
            assigned_role_code="LOGISTICS_MANAGER",
            assigned_tenant_id=20,
            assignment_status="OPEN",
        )

        with self.assertRaises(OperationValidationError):
            contract_services.save_package(
                81,
                payload={
                    "allocations": [
                        {"item_id": 101, "inventory_id": 1, "batch_id": 10, "quantity": "5.0000"},
                    ],
                },
                actor_id="fulfiller-1",
                actor_roles=["LOGISTICS_OFFICER"],
                tenant_context=self.tenant_ctx,
            )

        save_package_mock.assert_not_called()
