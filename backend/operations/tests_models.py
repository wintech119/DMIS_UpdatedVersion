from __future__ import annotations

from datetime import date
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from operations import staging_selection
from operations.constants import (
    PARTIAL_RELEASE_STATUS_APPROVED,
    PARTIAL_RELEASE_STATUS_PENDING,
    STAGING_SELECTION_BASIS_ALPHABETICAL_FALLBACK,
)
from operations.models import (
    OperationsDispatch,
    OperationsPackage,
    OperationsPartialReleaseRequest,
    OperationsReceipt,
    OperationsReliefRequest,
)


class _OperationsRequestFactoryMixin:
    request_no_prefix = "RQ"
    requesting_tenant_id = 20
    beneficiary_tenant_id = 20
    request_date = date(2026, 4, 2)
    urgency_code = "H"

    def _create_request(self, request_id: int) -> OperationsReliefRequest:
        return OperationsReliefRequest.objects.create(
            relief_request_id=request_id,
            request_no=f"{self.request_no_prefix}{request_id:05d}",
            requesting_tenant_id=self.requesting_tenant_id,
            beneficiary_tenant_id=self.beneficiary_tenant_id,
            beneficiary_agency_id=501,
            origin_mode="SELF",
            request_date=self.request_date,
            urgency_code=self.urgency_code,
            status_code="APPROVED_FOR_FULFILLMENT",
            create_by_id="tester",
            update_by_id="tester",
        )


class OperationsReceiptModelTests(_OperationsRequestFactoryMixin, TestCase):
    request_no_prefix = "RR"
    requesting_tenant_id = 10
    beneficiary_tenant_id = 20
    request_date = date(2026, 3, 27)
    urgency_code = "HIGH"

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


class OperationsPackageModelTests(_OperationsRequestFactoryMixin, TestCase):
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


class OperationsPartialReleaseRequestModelTests(_OperationsRequestFactoryMixin, TestCase):
    def test_partial_release_request_records_pending_workflow_evidence(self) -> None:
        request = self._create_request(90)
        package = OperationsPackage.objects.create(
            package_id=190,
            package_no="PK00190",
            relief_request=request,
            fulfillment_mode="DELIVER_FROM_STAGING",
            status_code="CONSOLIDATING",
            create_by_id="tester",
            update_by_id="tester",
        )

        partial_request = OperationsPartialReleaseRequest.objects.create(
            package=package,
            request_reason="Release received legs now",
            approval_status_code=PARTIAL_RELEASE_STATUS_PENDING,
            requested_by_user_id="logistics-1",
        )

        self.assertEqual(partial_request.package, package)
        self.assertEqual(package.partial_release_requests.get(), partial_request)
        self.assertEqual(partial_request.approval_status_code, PARTIAL_RELEASE_STATUS_PENDING)
        self.assertIsNone(partial_request.approved_by_user_id)

    def test_partial_release_request_can_reference_split_children_for_audit_convenience(self) -> None:
        request = self._create_request(91)
        parent = OperationsPackage.objects.create(
            package_id=191,
            package_no="PK00191",
            relief_request=request,
            fulfillment_mode="DELIVER_FROM_STAGING",
            status_code="SPLIT",
            create_by_id="tester",
            update_by_id="tester",
        )
        released_child = OperationsPackage.objects.create(
            package_id=192,
            package_no="PK00191-R1",
            relief_request=request,
            fulfillment_mode="DELIVER_FROM_STAGING",
            status_code="READY_FOR_DISPATCH",
            split_from_package=parent,
            create_by_id="tester",
            update_by_id="tester",
        )
        residual_child = OperationsPackage.objects.create(
            package_id=193,
            package_no="PK00191-R2",
            relief_request=request,
            fulfillment_mode="DELIVER_FROM_STAGING",
            status_code="CONSOLIDATING",
            split_from_package=parent,
            create_by_id="tester",
            update_by_id="tester",
        )

        partial_request = OperationsPartialReleaseRequest.objects.create(
            package=parent,
            request_reason="Release received legs now",
            approval_status_code=PARTIAL_RELEASE_STATUS_APPROVED,
            requested_by_user_id="logistics-1",
            approved_by_user_id="manager-1",
            approved_at=timezone.now(),
            released_child_package=released_child,
            residual_child_package=residual_child,
        )

        self.assertEqual(partial_request.released_child_package, released_child)
        self.assertEqual(partial_request.residual_child_package, residual_child)
        self.assertEqual(released_child.released_by_partial_release_requests.get(), partial_request)
        self.assertEqual(residual_child.residual_by_partial_release_requests.get(), partial_request)


class StagingSelectionRecommendationTests(TestCase):
    @patch("operations.staging_selection.operations_policy.resolve_odpem_tenant_id", return_value=27)
    @patch(
        "operations.staging_selection._staging_hub_rows",
        return_value=[
            {"warehouse_id": 12, "warehouse_name": "Alpha Hub", "parish_code": "03"},
            {"warehouse_id": 18, "warehouse_name": "Bravo Hub", "parish_code": "05"},
        ],
    )
    def test_recommend_staging_hub_uses_alphabetical_fallback_without_target_parish(
        self,
        _staging_hub_rows_mock,
        _resolve_odpem_tenant_id_mock,
    ) -> None:
        recommendation = staging_selection.recommend_staging_hub(beneficiary_parish_code=None)

        self.assertEqual(recommendation.recommended_staging_warehouse_id, 12)
        self.assertEqual(
            recommendation.staging_selection_basis,
            STAGING_SELECTION_BASIS_ALPHABETICAL_FALLBACK,
        )
        self.assertEqual(recommendation.recommended_staging_warehouse_name, "Alpha Hub")

    @patch("operations.staging_selection.operations_policy.resolve_odpem_tenant_id", return_value=27)
    @patch(
        "operations.staging_selection._staging_hub_rows",
        return_value=[
            {"warehouse_id": 12, "warehouse_name": "Alpha Hub", "parish_code": "03"},
            {"warehouse_id": 18, "warehouse_name": "Bravo Hub", "parish_code": "05"},
        ],
    )
    @patch("operations.staging_selection._fetch_rows", return_value=[])
    def test_recommend_staging_hub_uses_alphabetical_fallback_without_proximity_ranking(
        self,
        fetch_rows_mock,
        _staging_hub_rows_mock,
        _resolve_odpem_tenant_id_mock,
    ) -> None:
        recommendation = staging_selection.recommend_staging_hub(beneficiary_parish_code="09")

        self.assertEqual(recommendation.recommended_staging_warehouse_id, 12)
        self.assertEqual(
            recommendation.staging_selection_basis,
            STAGING_SELECTION_BASIS_ALPHABETICAL_FALLBACK,
        )
        fetch_rows_mock.assert_called_once()

    @patch("operations.staging_selection.operations_policy.resolve_odpem_tenant_id", return_value=27)
    @patch(
        "operations.staging_selection._staging_hub_rows",
        return_value=[
            {"warehouse_id": 12, "warehouse_name": "Alpha Hub", "parish_code": "03"},
            {"warehouse_id": 18, "warehouse_name": "Bravo Hub", "parish_code": "05"},
        ],
    )
    @patch(
        "operations.staging_selection._fetch_rows",
        return_value=[{"candidate_parish_code": "09", "proximity_rank": 1}],
    )
    def test_recommend_staging_hub_uses_alphabetical_fallback_when_ranked_parishes_do_not_match_candidates(
        self,
        _fetch_rows_mock,
        _staging_hub_rows_mock,
        _resolve_odpem_tenant_id_mock,
    ) -> None:
        recommendation = staging_selection.recommend_staging_hub(beneficiary_parish_code="08")

        self.assertEqual(recommendation.recommended_staging_warehouse_id, 12)
        self.assertEqual(
            recommendation.staging_selection_basis,
            STAGING_SELECTION_BASIS_ALPHABETICAL_FALLBACK,
        )
