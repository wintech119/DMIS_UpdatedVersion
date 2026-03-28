from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.db import IntegrityError, connection
from django.test import TestCase
from django.utils import timezone

from api.tenancy import TenantContext, TenantMembership
from operations import contract_services
from operations import policy as operations_policy
from operations.constants import (
    DISPATCH_STATUS_IN_TRANSIT,
    ELIGIBILITY_ROLE_CODES,
    ORIGIN_MODE_FOR_SUBORDINATE,
    ORIGIN_MODE_SELF,
    PACKAGE_STATUS_COMMITTED,
    PACKAGE_STATUS_DISPATCHED,
    PACKAGE_STATUS_PENDING_OVERRIDE_APPROVAL,
    QUEUE_CODE_DISPATCH,
    QUEUE_CODE_ELIGIBILITY,
    QUEUE_CODE_RECEIPT,
    ROLE_SYSTEM_ADMINISTRATOR,
    REQUEST_STATUS_APPROVED_FOR_FULFILLMENT,
    REQUEST_STATUS_UNDER_ELIGIBILITY_REVIEW,
)
from operations.exceptions import OperationValidationError
from operations.models import (
    OperationsDispatch,
    OperationsDispatchTransport,
    OperationsNotification,
    OperationsPackage,
    OperationsPackageLock,
    OperationsQueueAssignment,
    OperationsReceipt,
    OperationsReliefRequest,
    OperationsWaybill,
    TenantControlScope,
    TenantRequestPolicy,
)
from api.rbac import PERM_OPERATIONS_REQUEST_CREATE_SELF
from replenishment.legacy_models import ReliefRqst


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


class OperationsWorkflowContractTests(TestCase):
    def setUp(self) -> None:
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
            override_status_code=PACKAGE_STATUS_PENDING_OVERRIDE_APPROVAL,
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
        self.assertEqual(record.override_status_code, PACKAGE_STATUS_PENDING_OVERRIDE_APPROVAL)
        self.assertEqual(record.version_nbr, 5)
        self.assertEqual(record.update_by_id, "seed-user")
        self.assertEqual(record.update_dtime, original_updated_at)

    def test_package_sync_clears_override_status_when_override_is_approved(self) -> None:
        self._create_operations_request_record()
        OperationsPackage.objects.create(
            package_id=90,
            package_no="PK00090",
            relief_request_id=70,
            destination_tenant_id=20,
            destination_agency_id=501,
            status_code=PACKAGE_STATUS_PENDING_OVERRIDE_APPROVAL,
            override_status_code=PACKAGE_STATUS_PENDING_OVERRIDE_APPROVAL,
            create_by_id="seed-user",
            update_by_id="seed-user",
            version_nbr=5,
        )

        record = contract_services._sync_operations_package(
            self._package_stub(reliefpkg_id=90, reliefrqst_id=70, agency_id=501, status_code="P"),
            request_record=SimpleNamespace(beneficiary_tenant_id=20, beneficiary_agency_id=501),
            actor_id="sync-1",
            status_code=PACKAGE_STATUS_COMMITTED,
            override_status_code=None,
        )
        record.refresh_from_db()

        self.assertEqual(record.status_code, PACKAGE_STATUS_COMMITTED)
        self.assertIsNone(record.override_status_code)

    def test_approve_override_requires_package_pending_override_status(self) -> None:
        with (
            patch("operations.contract_services.legacy_service._load_request", return_value=self.request),
            patch(
                "operations.contract_services._sync_operations_request",
                return_value=SimpleNamespace(beneficiary_tenant_id=20, beneficiary_agency_id=501),
            ),
            patch("operations.contract_services._ensure_request_access"),
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
                )

        self.assertEqual(
            raised.exception.errors["override"],
            "Package is not awaiting override approval.",
        )
        approve_override_mock.assert_not_called()

    def test_ensure_dispatch_record_updates_existing_route_fields(self) -> None:
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
        dispatch = OperationsDispatch.objects.create(
            package_id=90,
            dispatch_no="DP00090",
            status_code="READY",
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
                source_warehouse_id=9,
                destination_tenant_id=30,
                destination_agency_id=777,
            ),
            actor_id="sync-1",
        )
        dispatch.refresh_from_db()

        self.assertEqual(updated_dispatch.dispatch_id, dispatch.dispatch_id)
        self.assertEqual(dispatch.source_warehouse_id, 9)
        self.assertEqual(dispatch.destination_tenant_id, 30)
        self.assertEqual(dispatch.destination_agency_id, 777)
        self.assertEqual(dispatch.update_by_id, "sync-1")
        self.assertEqual(dispatch.version_nbr, 2)

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
        load_request_mock.return_value = self.request
        current_package_mock.return_value = self.package
        save_package_mock.return_value = {"status": "COMMITTED", "reliefpkg_id": 90}
        get_agency_scope_mock.return_value = self.agency_scope

        contract_services.save_package(
            70,
            payload={"allocations": [{"item_id": 101, "inventory_id": 4, "batch_id": 1001, "quantity": "2"}]},
            actor_id="logistics-manager-1",
            actor_roles=self.dispatch_roles,
            tenant_context=self.dispatch_ready_context,
        )

        package_record = OperationsPackage.objects.get(package_id=90)
        self.assertEqual(package_record.status_code, "COMMITTED")
        self.assertTrue(OperationsPackageLock.objects.filter(package_id=90).exists())
        self.assertTrue(OperationsDispatch.objects.filter(package_id=90).exists())
        self.assertTrue(
            OperationsQueueAssignment.objects.filter(queue_code=QUEUE_CODE_DISPATCH, entity_id=90).exists()
        )
        load_request_mock.assert_called_once_with(70, for_update=True)

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
        load_request_mock.return_value = self.request
        current_package_mock.return_value = self.package
        save_package_mock.return_value = {"status": "COMMITTED", "reliefpkg_id": 90}
        get_agency_scope_mock.return_value = self.agency_scope

        contract_services.save_package(
            70,
            payload={"allocations": [{"item_id": 101, "batch_id": 1001, "quantity": "2"}]},
            actor_id="logistics-manager-1",
            actor_roles=self.dispatch_roles,
            tenant_context=self.dispatch_ready_context,
        )

        package_record = OperationsPackage.objects.get(package_id=90)
        dispatch = OperationsDispatch.objects.get(package_id=90)
        self.assertIsNone(package_record.source_warehouse_id)
        self.assertIsNone(dispatch.source_warehouse_id)

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
        load_request_mock.return_value = self.request
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
    def test_package_save_rejects_conflicting_lock_before_legacy_write(
        self,
        save_package_mock,
        load_request_mock,
        current_package_mock,
        get_agency_scope_mock,
    ) -> None:
        load_request_mock.return_value = self.request
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

        result = contract_services.submit_dispatch(
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
        )

        self.assertEqual(result["dispatch"]["status_code"], DISPATCH_STATUS_IN_TRANSIT)
        self.assertTrue(OperationsDispatchTransport.objects.filter(dispatch_id=result["dispatch"]["dispatch_id"]).exists())
        self.assertTrue(OperationsWaybill.objects.filter(waybill_no="WB-PK00090").exists())
        self.assertTrue(OperationsQueueAssignment.objects.filter(queue_code=QUEUE_CODE_RECEIPT, entity_id=90).exists())

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

    def test_dispatch_payload_masks_driver_license_number(self) -> None:
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
            driver_license_no="DL123456789",
            vehicle_registration="1234AB",
            transport_mode="TRUCK",
        )

        payload = contract_services._dispatch_payload(package, dispatch)

        self.assertEqual(payload["transport"]["driver_license_no"], "*******6789")
        self.assertNotEqual(payload["transport"]["driver_license_no"], "DL123456789")

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
    @patch("operations.contract_services.operations_policy.get_agency_scope")
    def test_eligibility_queue_fallback_excludes_out_of_scope_requests(
        self,
        get_agency_scope_mock,
        _request_summary_mock,
    ) -> None:
        self._insert_legacy_agency(501)
        self._insert_legacy_agency(503)
        ReliefRqst.objects.create(
            reliefrqst_id=80,
            agency_id=501,
            request_date=date(2026, 3, 26),
            tracking_no="RQ00080",
            eligible_event_id=1,
            urgency_ind="H",
            rqst_notes_text="Need shelter kits",
            status_code=contract_services.legacy_service.STATUS_AWAITING_APPROVAL,
            create_by_id="requester-1",
            create_dtime=datetime(2026, 3, 26, 9, 0, 0),
            version_nbr=1,
        )
        ReliefRqst.objects.create(
            reliefrqst_id=81,
            agency_id=503,
            request_date=date(2026, 3, 26),
            tracking_no="RQ00081",
            eligible_event_id=1,
            urgency_ind="H",
            rqst_notes_text="Need shelter kits",
            status_code=contract_services.legacy_service.STATUS_AWAITING_APPROVAL,
            create_by_id="requester-1",
            create_dtime=datetime(2026, 3, 26, 9, 15, 0),
            version_nbr=1,
        )
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

    @patch("operations.contract_services._request_summary_payload", side_effect=lambda request, request_record: {"reliefrqst_id": int(request.reliefrqst_id), "requesting_tenant_id": request_record.requesting_tenant_id})
    @patch("operations.contract_services.operations_policy.get_agency_scope")
    @patch("operations.contract_services.legacy_service._current_package_for_request", return_value=None)
    @patch("operations.contract_services.legacy_service._load_request")
    def test_fulfillment_queue_fallback_respects_scope(
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
            70: self._request_stub(reliefrqst_id=70, agency_id=501, status_code=3),
            71: self._request_stub(reliefrqst_id=71, agency_id=502, status_code=3),
        }
        load_request_mock.side_effect = lambda reliefrqst_id: requests[int(reliefrqst_id)]
        get_agency_scope_mock.side_effect = lambda agency_id: {
            501: self._agency_scope_for(501, 20, "FFP"),
            502: self._agency_scope_for(502, 30, "OUT-30"),
        }[int(agency_id)]

        result = contract_services.list_packages(
            actor_id="logistics-1",
            actor_roles=["LOGISTICS_MANAGER"],
            tenant_context=self.dispatch_ready_context,
        )

        self.assertEqual([row["reliefrqst_id"] for row in result["results"]], [70])

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
            )

        self.assertEqual(raised.exception.errors, {"receipt": "Dispatch record is missing for this package."})
