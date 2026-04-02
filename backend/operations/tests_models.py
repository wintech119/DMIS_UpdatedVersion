from __future__ import annotations

from datetime import date

from django.test import TestCase

from operations.models import (
    OperationsDispatch,
    OperationsPackage,
    OperationsReceipt,
    OperationsReliefRequest,
)


class OperationsReceiptModelTests(TestCase):
    def _create_request(self, request_id: int) -> OperationsReliefRequest:
        return OperationsReliefRequest.objects.create(
            relief_request_id=request_id,
            request_no=f"RR{request_id:05d}",
            requesting_tenant_id=10,
            beneficiary_tenant_id=20,
            beneficiary_agency_id=501,
            origin_mode="SELF",
            request_date=date(2026, 3, 27),
            urgency_code="HIGH",
            status_code="APPROVED_FOR_FULFILLMENT",
            create_by_id="tester",
            update_by_id="tester",
        )

    def _create_package(self, package_id: int, request: OperationsReliefRequest) -> OperationsPackage:
        return OperationsPackage.objects.create(
            package_id=package_id,
            package_no=f"PK{package_id:05d}",
            relief_request=request,
            destination_tenant_id=20,
            destination_agency_id=501,
            status_code="DISPATCHED",
            create_by_id="tester",
            update_by_id="tester",
        )

    def test_receipt_package_property_returns_dispatch_package(self) -> None:
        request = self._create_request(70)
        package = self._create_package(90, request)
        dispatch = OperationsDispatch.objects.create(
            package=package,
            dispatch_no="DP00090",
            status_code="RECEIVED",
            create_by_id="tester",
            update_by_id="tester",
        )

        receipt = OperationsReceipt.objects.create(
            dispatch=dispatch,
            receipt_status_code="RECEIVED",
            received_by_user_id="receiver-1",
        )
        receipt.refresh_from_db()

        self.assertEqual(receipt.package_id, package.package_id)
        self.assertEqual(receipt.package, package)

    def test_receipt_package_properties_use_assigned_unsaved_dispatch(self) -> None:
        request = self._create_request(71)
        package = self._create_package(91, request)
        dispatch = OperationsDispatch(
            package=package,
            dispatch_no="DP00091",
            status_code="PENDING",
            create_by_id="tester",
            update_by_id="tester",
        )

        receipt = OperationsReceipt(
            dispatch=dispatch,
            receipt_status_code="PENDING",
        )

        self.assertIsNone(receipt.dispatch_id)
        self.assertEqual(receipt.package_id, package.package_id)
        self.assertEqual(receipt.package, package)

    def test_receipt_package_and_id_none_without_dispatch(self) -> None:
        receipt = OperationsReceipt(
            receipt_status_code="PENDING",
        )
        self.assertIsNone(receipt.dispatch_id)
        self.assertIsNone(receipt.package_id)
        self.assertIsNone(receipt.package)


class OperationsPackageModelTests(TestCase):
    def _create_request(self, request_id: int) -> OperationsReliefRequest:
        return OperationsReliefRequest.objects.create(
            relief_request_id=request_id,
            request_no=f"RQ{request_id:05d}",
            requesting_tenant_id=20,
            beneficiary_tenant_id=20,
            beneficiary_agency_id=501,
            origin_mode="SELF",
            request_date=date(2026, 4, 2),
            urgency_code="H",
            status_code="APPROVED_FOR_FULFILLMENT",
            create_by_id="tester",
            update_by_id="tester",
        )

    def test_effective_dispatch_source_warehouse_uses_direct_source_for_direct_mode(self) -> None:
        request = self._create_request(80)
        package = OperationsPackage.objects.create(
            package_id=100,
            package_no="PK00100",
            relief_request=request,
            source_warehouse_id=4,
            fulfillment_mode="DIRECT",
            status_code="COMMITTED",
            create_by_id="tester",
            update_by_id="tester",
        )

        self.assertEqual(package.effective_dispatch_source_warehouse_id, 4)

    def test_effective_dispatch_source_warehouse_prefers_staging_for_staged_modes(self) -> None:
        request = self._create_request(81)
        package = OperationsPackage.objects.create(
            package_id=101,
            package_no="PK00101",
            relief_request=request,
            source_warehouse_id=4,
            staging_warehouse_id=55,
            fulfillment_mode="DELIVER_FROM_STAGING",
            status_code="READY_FOR_DISPATCH",
            create_by_id="tester",
            update_by_id="tester",
        )

        self.assertEqual(package.effective_dispatch_source_warehouse_id, 55)
