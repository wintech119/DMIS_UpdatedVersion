from __future__ import annotations

from datetime import date

from django.core.exceptions import ValidationError
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

    def test_receipt_save_rejects_package_that_does_not_match_dispatch(self) -> None:
        request = self._create_request(70)
        package = self._create_package(90, request)
        other_package = self._create_package(91, request)
        dispatch = OperationsDispatch.objects.create(
            package=package,
            dispatch_no="DP00090",
            status_code="RECEIVED",
            create_by_id="tester",
            update_by_id="tester",
        )

        with self.assertRaises(ValidationError) as raised:
            OperationsReceipt.objects.create(
                dispatch=dispatch,
                package=other_package,
                receipt_status_code="RECEIVED",
                received_by_user_id="receiver-1",
            )

        self.assertEqual(
            raised.exception.message_dict,
            {"package": ["Receipt package must match the dispatch package."]},
        )

    def test_receipt_model_declares_unique_constraint_on_package(self) -> None:
        constraint_names = {constraint.name for constraint in OperationsReceipt._meta.constraints}

        self.assertIn("operations_receipt_unique_package", constraint_names)
