from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from replenishment.services.needs_list import (
    allocate_horizons,
    compute_confidence_and_warnings,
    compute_gap,
    compute_inbound_strict,
)


class NeedsListServiceTests(SimpleTestCase):
    def test_strict_inbound_sums(self) -> None:
        donations = {1: 5.0}
        transfers = {1: 7.5}
        self.assertEqual(compute_inbound_strict(1, donations, transfers), 12.5)

    def test_gap_uses_safety_factor(self) -> None:
        gap = compute_gap(
            burn_rate_per_day=2.0,
            planning_window_days=10,
            safety_factor=1.5,
            available=5.0,
            inbound_strict=0.0,
        )
        self.assertEqual(gap, 25.0)

    def test_negative_gap_floors_to_zero(self) -> None:
        gap = compute_gap(
            burn_rate_per_day=1.0,
            planning_window_days=10,
            safety_factor=1.0,
            available=50.0,
            inbound_strict=0.0,
        )
        self.assertEqual(gap, 0.0)

    def test_procurement_unavailable_sets_horizon_c_null(self) -> None:
        horizons, warnings = allocate_horizons(
            gap_qty=10, horizon_a_days=7, horizon_b_days=7, procurement_available=False
        )
        self.assertIsNone(horizons["C"]["recommended_qty"])
        self.assertIn("procurement_unavailable", warnings)

    def test_confidence_changes_with_burn_source(self) -> None:
        level_missing, _, _ = compute_confidence_and_warnings(
            burn_source="none",
            warnings=[],
            procurement_available=False,
            transfer_semantics_tbd=True,
        )
        level_present, _, _ = compute_confidence_and_warnings(
            burn_source="reliefpkg",
            warnings=[],
            procurement_available=False,
            transfer_semantics_tbd=True,
        )
        self.assertEqual(level_missing, "low")
        self.assertEqual(level_present, "high")


class NeedsListPreviewApiTests(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="dev-user",
        DEV_AUTH_ROLES=["LOGISTICS"],
        AUTH_USE_DB_RBAC=False,
    )
    def test_preview_endpoint_returns_stubbed_response(self) -> None:
        response = self.client.post(
            "/api/v1/replenishment/needs-list/preview",
            {
                "event_id": 1,
                "warehouse_id": 1,
                "planning_window_days": 14,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("items", body)
        self.assertIn("warnings", body)
        self.assertIn("db_unavailable_preview_stub", body["warnings"])
