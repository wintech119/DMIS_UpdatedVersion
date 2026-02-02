import os
from datetime import timedelta
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from replenishment import rules, workflow_store
from replenishment.services import needs_list
from replenishment.services.needs_list import (
    allocate_horizons,
    compute_confidence_and_warnings,
    compute_gap,
    compute_inbound_strict,
    compute_time_to_stockout_hours,
)


class NeedsListServiceTests(SimpleTestCase):
    def test_strict_inbound_sums(self) -> None:
        donations = {1: 5.0}
        transfers = {1: 7.5}
        self.assertEqual(compute_inbound_strict(1, donations, transfers), 12.5)

    def test_gap_uses_safety_factor(self) -> None:
        gap = compute_gap(
            burn_rate_per_hour=10.0,
            planning_window_hours=10,
            safety_factor=rules.SAFETY_STOCK_FACTOR,
            available=5.0,
            inbound_strict=0.0,
        )
        self.assertEqual(gap, 120.0)

    def test_negative_gap_floors_to_zero(self) -> None:
        gap = compute_gap(
            burn_rate_per_hour=1.0,
            planning_window_hours=10,
            safety_factor=1.0,
            available=50.0,
            inbound_strict=0.0,
        )
        self.assertEqual(gap, 0.0)

    def test_procurement_unavailable_sets_horizon_c_null(self) -> None:
        horizons, warnings = allocate_horizons(
            gap_qty=10,
            horizon_a_hours=24,
            horizon_b_hours=24,
            procurement_available=False,
        )
        self.assertIsNone(horizons["C"]["recommended_qty"])
        self.assertIn("procurement_unavailable_in_schema", warnings)

    def test_confidence_changes_with_burn_source(self) -> None:
        level_missing, _, _ = compute_confidence_and_warnings(
            burn_source="none",
            warnings=[],
            procurement_available=False,
            mapping_best_effort=False,
        )
        level_present, _, _ = compute_confidence_and_warnings(
            burn_source="reliefpkg",
            warnings=[],
            procurement_available=True,
            mapping_best_effort=False,
        )
        self.assertEqual(level_missing, "low")
        self.assertEqual(level_present, "high")

    def test_time_to_stockout_handles_zero_burn(self) -> None:
        self.assertEqual(
            compute_time_to_stockout_hours(0.0, 10.0, 0.0), "N/A - No current demand"
        )

    def test_burn_rate_fallback_sets_low_confidence(self) -> None:
        as_of_dt = timezone.now()
        inventory_as_of = as_of_dt - timedelta(hours=72)
        items, _, fallback_counts = needs_list.build_preview_items(
            item_ids=[1, 2],
            available_by_item={1: 0.0, 2: 0.0},
            inbound_donations_by_item={},
            inbound_transfers_by_item={},
            burn_by_item={},
            item_categories={1: 10, 2: 10},
            category_burn_rates={10: 2.0},
            demand_window_hours=2,
            planning_window_hours=2,
            safety_factor=1.0,
            horizon_a_hours=0,
            horizon_b_hours=0,
            burn_source="none",
            as_of_dt=as_of_dt,
            phase="BASELINE",
            inventory_as_of=inventory_as_of,
            base_warnings=["burn_data_missing"],
        )
        item_one = items[0]
        self.assertEqual(item_one["confidence"]["level"], "low")
        self.assertIn("burn_rate_estimated", item_one["warnings"])
        self.assertEqual(fallback_counts["category_avg"], 2)

    def test_freshness_unknown_without_timestamp(self) -> None:
        state, warnings, _ = needs_list.compute_freshness_state(
            "BASELINE", None, timezone.now()
        )
        self.assertEqual(state, "unknown")
        self.assertIn("inventory_timestamp_unavailable", warnings)

    def test_horizon_b_recommended_with_zero_inbound(self) -> None:
        items, _, _ = needs_list.build_preview_items(
            item_ids=[1],
            available_by_item={1: 0.0},
            inbound_donations_by_item={},
            inbound_transfers_by_item={},
            burn_by_item={1: 24.0},
            item_categories={1: 10},
            category_burn_rates={},
            demand_window_hours=24,
            planning_window_hours=48,
            safety_factor=1.0,
            horizon_a_hours=24,
            horizon_b_hours=24,
            burn_source="reliefpkg",
            as_of_dt=timezone.now(),
            phase="BASELINE",
            inventory_as_of=timezone.now(),
            base_warnings=["donation_in_transit_unmodeled"],
        )
        horizon_b = items[0]["horizon"]["B"]["recommended_qty"]
        self.assertIsNotNone(horizon_b)
        self.assertGreater(horizon_b or 0.0, 0.0)

    def test_activate_b_when_gap_remains_after_a(self) -> None:
        as_of_dt = timezone.now()
        inventory_as_of = as_of_dt - timedelta(hours=1)
        items, _, _ = needs_list.build_preview_items(
            item_ids=[1],
            available_by_item={1: 0.0},
            inbound_donations_by_item={},
            inbound_transfers_by_item={},
            burn_by_item={1: 24.0},
            item_categories={1: 10},
            category_burn_rates={},
            demand_window_hours=24,
            planning_window_hours=48,
            safety_factor=1.0,
            horizon_a_hours=48,
            horizon_b_hours=24,
            burn_source="reliefpkg",
            as_of_dt=as_of_dt,
            phase="STABILIZED",
            inventory_as_of=inventory_as_of,
            base_warnings=[],
        )
        triggers = items[0]["triggers"]
        self.assertTrue(triggers["activate_B"])

    def test_activate_c_when_time_to_stockout_below_lead_time(self) -> None:
        as_of_dt = timezone.now()
        inventory_as_of = as_of_dt - timedelta(hours=1)
        items, _, _ = needs_list.build_preview_items(
            item_ids=[1],
            available_by_item={1: 10.0},
            inbound_donations_by_item={},
            inbound_transfers_by_item={},
            burn_by_item={1: 24.0},
            item_categories={1: 10},
            category_burn_rates={},
            demand_window_hours=24,
            planning_window_hours=72,
            safety_factor=1.0,
            horizon_a_hours=24,
            horizon_b_hours=24,
            burn_source="reliefpkg",
            as_of_dt=as_of_dt,
            phase="SURGE",
            inventory_as_of=inventory_as_of,
            base_warnings=[],
        )
        item = items[0]
        self.assertTrue(item["triggers"]["activate_C"])
        self.assertIn("procurement_recommendation_qty", item)
        self.assertEqual(item.get("procurement_status"), "RECOMMENDED")
        self.assertIn("procurement", item)
        procurement = item["procurement"]
        self.assertEqual(procurement.get("lead_time_hours_default"), 336)
        self.assertIn("approval", procurement)
        self.assertIn("gojep_note", procurement)
        self.assertEqual(item.get("external_procurement_system"), "GOJEP")
        self.assertIsNone(item.get("external_reference"))
        self.assertNotIn("procurement_method", item)
        self.assertNotIn("procurement_id", item)
        self.assertIn("procurement_cost_unavailable", item.get("warnings", []))
        self.assertIn("procurement_category_unavailable", item.get("warnings", []))

    def test_surge_critical_activates_all(self) -> None:
        as_of_dt = timezone.now()
        inventory_as_of = as_of_dt - timedelta(hours=1)
        with patch.dict(os.environ, {"NEEDS_CRITICAL_ITEM_IDS": "1"}):
            items, _, _ = needs_list.build_preview_items(
                item_ids=[1],
                available_by_item={1: 0.0},
                inbound_donations_by_item={},
                inbound_transfers_by_item={},
                burn_by_item={1: 60.0},
                item_categories={1: 10},
                category_burn_rates={},
                demand_window_hours=6,
                planning_window_hours=72,
                safety_factor=1.0,
                horizon_a_hours=24,
                horizon_b_hours=24,
                burn_source="reliefpkg",
                as_of_dt=as_of_dt,
                phase="SURGE",
                inventory_as_of=inventory_as_of,
                base_warnings=[],
            )
        triggers = items[0]["triggers"]
        self.assertTrue(triggers["activate_all"])
        self.assertTrue(triggers["activate_B"])
        self.assertTrue(triggers["activate_C"])
        self.assertNotIn("critical_flag_unavailable", items[0]["warnings"])

    def test_surge_critical_category_activates_all(self) -> None:
        as_of_dt = timezone.now()
        inventory_as_of = as_of_dt - timedelta(hours=1)
        with patch.dict(os.environ, {"NEEDS_CRITICAL_CATEGORY_IDS": "10"}):
            items, _, _ = needs_list.build_preview_items(
                item_ids=[1],
                available_by_item={1: 0.0},
                inbound_donations_by_item={},
                inbound_transfers_by_item={},
                burn_by_item={1: 60.0},
                item_categories={1: 10},
                category_burn_rates={},
                demand_window_hours=6,
                planning_window_hours=72,
                safety_factor=1.0,
                horizon_a_hours=24,
                horizon_b_hours=24,
                burn_source="reliefpkg",
                as_of_dt=as_of_dt,
                phase="SURGE",
                inventory_as_of=inventory_as_of,
                base_warnings=[],
            )
        triggers = items[0]["triggers"]
        self.assertTrue(triggers["activate_all"])
        self.assertTrue(triggers["activate_B"])
        self.assertTrue(triggers["activate_C"])
        self.assertNotIn("critical_flag_unavailable", items[0]["warnings"])

    def test_surge_missing_critical_warns(self) -> None:
        as_of_dt = timezone.now()
        inventory_as_of = as_of_dt - timedelta(hours=1)
        items, _, _ = needs_list.build_preview_items(
            item_ids=[1],
            available_by_item={1: 0.0},
            inbound_donations_by_item={},
            inbound_transfers_by_item={},
            burn_by_item={1: 60.0},
            item_categories={1: 10},
            category_burn_rates={},
            demand_window_hours=6,
            planning_window_hours=72,
            safety_factor=1.0,
            horizon_a_hours=24,
            horizon_b_hours=24,
            burn_source="reliefpkg",
            as_of_dt=as_of_dt,
            phase="SURGE",
            inventory_as_of=inventory_as_of,
            base_warnings=[],
        )
        self.assertIn("critical_flag_unavailable", items[0]["warnings"])

    def test_burn_zero_freshness_high_no_estimate(self) -> None:
        as_of_dt = timezone.now()
        inventory_as_of = as_of_dt - timedelta(hours=1)
        items, _, _ = needs_list.build_preview_items(
            item_ids=[1],
            available_by_item={1: 5.0},
            inbound_donations_by_item={},
            inbound_transfers_by_item={},
            burn_by_item={},
            item_categories={1: 10},
            category_burn_rates={10: 2.0},
            demand_window_hours=24,
            planning_window_hours=24,
            safety_factor=1.0,
            horizon_a_hours=0,
            horizon_b_hours=0,
            burn_source="reliefpkg",
            as_of_dt=as_of_dt,
            phase="BASELINE",
            inventory_as_of=inventory_as_of,
            base_warnings=[],
        )
        item = items[0]
        self.assertEqual(item["burn_rate_per_hour"], 0.0)
        self.assertEqual(item["time_to_stockout"], "N/A - No current demand")
        self.assertIn("burn_no_rows_in_window", item["warnings"])
        self.assertNotIn("burn_rate_estimated", item["warnings"])

    def test_burn_zero_freshness_stale_estimated_low_confidence(self) -> None:
        as_of_dt = timezone.now()
        inventory_as_of = as_of_dt - timedelta(hours=72)
        items, _, _ = needs_list.build_preview_items(
            item_ids=[1],
            available_by_item={1: 5.0},
            inbound_donations_by_item={},
            inbound_transfers_by_item={},
            burn_by_item={},
            item_categories={1: 10},
            category_burn_rates={10: 1.5},
            demand_window_hours=24,
            planning_window_hours=24,
            safety_factor=1.0,
            horizon_a_hours=0,
            horizon_b_hours=0,
            burn_source="reliefpkg",
            as_of_dt=as_of_dt,
            phase="BASELINE",
            inventory_as_of=inventory_as_of,
            base_warnings=[],
        )
        item = items[0]
        self.assertEqual(item["burn_rate_per_hour"], 1.5)
        self.assertIn("burn_rate_estimated", item["warnings"])
        self.assertEqual(item["confidence"]["level"], "low")
        self.assertNotIn("burn_no_rows_in_window", item["warnings"])

    def test_burn_zero_freshness_unknown_no_estimate(self) -> None:
        as_of_dt = timezone.now()
        items, _, _ = needs_list.build_preview_items(
            item_ids=[1],
            available_by_item={1: 5.0},
            inbound_donations_by_item={},
            inbound_transfers_by_item={},
            burn_by_item={},
            item_categories={1: 10},
            category_burn_rates={10: 1.5},
            demand_window_hours=24,
            planning_window_hours=24,
            safety_factor=1.0,
            horizon_a_hours=0,
            horizon_b_hours=0,
            burn_source="reliefpkg",
            as_of_dt=as_of_dt,
            phase="BASELINE",
            inventory_as_of=None,
            base_warnings=[],
        )
        item = items[0]
        self.assertEqual(item["burn_rate_per_hour"], 0.0)
        self.assertEqual(item["time_to_stockout"], "N/A - No current demand")
        self.assertIn("burn_no_rows_in_window", item["warnings"])
        self.assertIn("inventory_timestamp_unavailable", item["warnings"])
        self.assertNotIn("burn_rate_estimated", item["warnings"])

    def test_procurement_approval_band_low_baseline(self) -> None:
        approval, warnings = rules.get_procurement_approval(2_000_000, "BASELINE")
        self.assertEqual(approval["tier"], "Below Tier 1")
        self.assertEqual(approval["approver_role"], "Logistics Manager (Kemar)")
        self.assertIn("Single-Source", approval["methods_allowed"])
        self.assertIn("procurement_category_unavailable", warnings)

    def test_procurement_approval_band_mid_surge(self) -> None:
        approval, warnings = rules.get_procurement_approval(20_000_000, "SURGE")
        self.assertEqual(approval["tier"], "Below Tier 1")
        self.assertEqual(approval["approver_role"], "Senior Director (Andrea)")
        self.assertIn("Open National Competitive Bidding", approval["methods_allowed"])
        self.assertIn("procurement_category_unavailable", warnings)

    def test_procurement_approval_band_high_baseline(self) -> None:
        approval, warnings = rules.get_procurement_approval(80_000_000, "BASELINE")
        self.assertEqual(approval["tier"], "Tier 2")
        self.assertEqual(approval["approver_role"], "DG + PPC Endorsement")
        self.assertIn("Open International Competitive Bidding", approval["methods_allowed"])
        self.assertIn("procurement_category_unavailable", warnings)
    def test_default_windows_are_v41(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(rules.get_windows_version(), "v41")
            self.assertEqual(
                rules.get_phase_windows("SURGE"),
                {"demand_hours": 6, "planning_hours": 72},
            )
            self.assertEqual(
                rules.get_phase_windows("STABILIZED"),
                {"demand_hours": 72, "planning_hours": 168},
            )
            self.assertEqual(
                rules.get_phase_windows("BASELINE"),
                {"demand_hours": 720, "planning_hours": 720},
            )

    def test_windows_version_override_v40(self) -> None:
        with patch.dict(os.environ, {"NEEDS_WINDOWS_VERSION": "v40"}):
            windows = rules.get_phase_windows("SURGE")
            self.assertEqual(windows["planning_hours"], 24)
            self.assertEqual(windows["demand_hours"], 6)

    def test_freshness_thresholds_matrix(self) -> None:
        self.assertEqual(
            rules.FRESHNESS_THRESHOLDS,
            {
                "SURGE": {"fresh_max_hours": 2, "warn_max_hours": 4},
                "STABILIZED": {"fresh_max_hours": 6, "warn_max_hours": 12},
                "BASELINE": {"fresh_max_hours": 24, "warn_max_hours": 48},
            },
        )

    def test_donation_mapping_avoids_apc(self) -> None:
        with patch.dict(
            os.environ,
            {"DONATION_CONFIRMED_CODES": "A,V,C", "DONATION_IN_TRANSIT_CODES": "V"},
        ):
            codes, warnings = rules.resolve_strict_inbound_donation_codes()
            self.assertTrue(set(codes).issubset({"E", "V", "P"}))
            self.assertNotIn("A", codes)
            self.assertNotIn("C", codes)
            self.assertIn("donation_status_code_invalid_filtered", warnings)

    def test_transfer_mapping_defaults_to_d(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            codes, warnings = rules.resolve_strict_inbound_transfer_codes()
            self.assertEqual(codes, ["D"])
            self.assertNotIn("strict_inbound_mapping_best_effort", warnings)


class NeedsListPreviewApiTests(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="dev-user",
        DEV_AUTH_ROLES=["LOGISTICS"],
        DEV_AUTH_PERMISSIONS=[],
        DEBUG=True,
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
        self.assertIn("debug_summary", body)
        self.assertEqual(
            body["debug_summary"]["burn"].get("filter"),
            "reliefpkg.status_code IN ('D','R') and dispatch_dtime window",
        )

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="dev-user",
        DEV_AUTH_ROLES=["LOGISTICS"],
        DEV_AUTH_PERMISSIONS=[],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch("replenishment.views.data_access.get_item_categories")
    @patch("replenishment.views.data_access.get_category_burn_fallback_rates")
    @patch("replenishment.views.data_access.get_burn_by_item")
    @patch("replenishment.views.data_access.get_inbound_transfers_by_item")
    @patch("replenishment.views.data_access.get_inbound_donations_by_item")
    @patch("replenishment.views.data_access.get_available_by_item")
    def test_preview_endpoint_includes_required_fields(
        self,
        mock_available,
        mock_donations,
        mock_transfers,
        mock_burn,
        mock_fallback,
        mock_categories,
    ) -> None:
        mock_available.return_value = ({1: 10.0}, [], None)
        mock_donations.return_value = ({}, ["donation_in_transit_unmodeled"])
        mock_transfers.return_value = ({}, [])
        mock_burn.return_value = (
            {1: 24.0},
            [],
            "reliefpkg",
            {"filter": "reliefpkg.status_code IN ('D','R') and dispatch_dtime window"},
        )
        mock_fallback.return_value = ({}, [], {})
        mock_categories.return_value = ({1: 10}, [])

        response = self.client.post(
            "/api/v1/replenishment/needs-list/preview",
            {"event_id": 1, "warehouse_id": 1, "phase": "BASELINE"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("warnings", body)
        self.assertIn("donation_in_transit_unmodeled", body["warnings"])
        self.assertEqual(len(body["items"]), 1)
        item = body["items"][0]
        self.assertIn("required_qty", item)
        self.assertIn("time_to_stockout", item)
        self.assertEqual(item.get("freshness_state"), "Unknown")
        self.assertIn("donation_in_transit_unmodeled", item.get("warnings", []))


class NeedsListWorkflowApiTests(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        store_path = workflow_store._store_path()
        if store_path.exists():
            store_path.unlink()

    def tearDown(self) -> None:
        store_path = workflow_store._store_path()
        if store_path.exists():
            store_path.unlink()

    def _draft_payload(self) -> dict:
        return {"event_id": 1, "warehouse_id": 1, "phase": "BASELINE"}

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="dev-user",
        DEV_AUTH_ROLES=["LOGISTICS"],
        DEV_AUTH_PERMISSIONS=[],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch("replenishment.views.data_access.get_item_categories")
    @patch("replenishment.views.data_access.get_category_burn_fallback_rates")
    @patch("replenishment.views.data_access.get_burn_by_item")
    @patch("replenishment.views.data_access.get_inbound_transfers_by_item")
    @patch("replenishment.views.data_access.get_inbound_donations_by_item")
    @patch("replenishment.views.data_access.get_available_by_item")
    def test_draft_creation_creates_store_entry(
        self,
        mock_available,
        mock_donations,
        mock_transfers,
        mock_burn,
        mock_fallback,
        mock_categories,
    ) -> None:
        mock_available.return_value = ({1: 10.0}, [], None)
        mock_donations.return_value = ({}, [])
        mock_transfers.return_value = ({}, [])
        mock_burn.return_value = ({1: 24.0}, [], "reliefpkg", {"filter": "test"})
        mock_fallback.return_value = ({}, [], {})
        mock_categories.return_value = ({1: 10}, [])

        with patch.dict(os.environ, {"NEEDS_WORKFLOW_DEV_STORE": "1"}):
            response = self.client.post(
                "/api/v1/replenishment/needs-list/draft",
                self._draft_payload(),
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body.get("status"), "DRAFT")
        self.assertIsNotNone(body.get("needs_list_id"))
        store_path = workflow_store._store_path()
        self.assertTrue(store_path.exists())

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="dev-user",
        DEV_AUTH_ROLES=["LOGISTICS"],
        DEV_AUTH_PERMISSIONS=[],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch("replenishment.views.data_access.get_item_categories")
    @patch("replenishment.views.data_access.get_category_burn_fallback_rates")
    @patch("replenishment.views.data_access.get_burn_by_item")
    @patch("replenishment.views.data_access.get_inbound_transfers_by_item")
    @patch("replenishment.views.data_access.get_inbound_donations_by_item")
    @patch("replenishment.views.data_access.get_available_by_item")
    def test_line_edit_requires_reason_and_draft_only(
        self,
        mock_available,
        mock_donations,
        mock_transfers,
        mock_burn,
        mock_fallback,
        mock_categories,
    ) -> None:
        mock_available.return_value = ({1: 10.0}, [], None)
        mock_donations.return_value = ({}, [])
        mock_transfers.return_value = ({}, [])
        mock_burn.return_value = ({1: 24.0}, [], "reliefpkg", {"filter": "test"})
        mock_fallback.return_value = ({}, [], {})
        mock_categories.return_value = ({1: 10}, [])

        with patch.dict(os.environ, {"NEEDS_WORKFLOW_DEV_STORE": "1"}):
            draft = self.client.post(
                "/api/v1/replenishment/needs-list/draft",
                self._draft_payload(),
                format="json",
            ).json()
            needs_list_id = draft["needs_list_id"]

            response = self.client.patch(
                f"/api/v1/replenishment/needs-list/{needs_list_id}/lines",
                [{"item_id": 1, "overridden_qty": 5}],
                format="json",
            )
            self.assertEqual(response.status_code, 400)

            invalid_negative = self.client.patch(
                f"/api/v1/replenishment/needs-list/{needs_list_id}/lines",
                [{"item_id": 1, "overridden_qty": -5, "reason": "Adjust"}],
                format="json",
            )
            self.assertEqual(invalid_negative.status_code, 400)

            invalid_nan = self.client.patch(
                f"/api/v1/replenishment/needs-list/{needs_list_id}/lines",
                [{"item_id": 1, "overridden_qty": "NaN", "reason": "Adjust"}],
                format="json",
            )
            self.assertEqual(invalid_nan.status_code, 400)

            response = self.client.patch(
                f"/api/v1/replenishment/needs-list/{needs_list_id}/lines",
                [{"item_id": 1, "overridden_qty": 5, "reason": "Adjust"}],
                format="json",
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.json()["items"][0].get("required_qty"),
                5.0,
            )

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="submitter",
        DEV_AUTH_ROLES=["LOGISTICS"],
        DEV_AUTH_PERMISSIONS=[],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch("replenishment.views.data_access.get_item_categories")
    @patch("replenishment.views.data_access.get_category_burn_fallback_rates")
    @patch("replenishment.views.data_access.get_burn_by_item")
    @patch("replenishment.views.data_access.get_inbound_transfers_by_item")
    @patch("replenishment.views.data_access.get_inbound_donations_by_item")
    @patch("replenishment.views.data_access.get_available_by_item")
    def test_submit_and_review_separation(
        self,
        mock_available,
        mock_donations,
        mock_transfers,
        mock_burn,
        mock_fallback,
        mock_categories,
    ) -> None:
        mock_available.return_value = ({1: 10.0}, [], None)
        mock_donations.return_value = ({}, [])
        mock_transfers.return_value = ({}, [])
        mock_burn.return_value = ({1: 24.0}, [], "reliefpkg", {"filter": "test"})
        mock_fallback.return_value = ({}, [], {})
        mock_categories.return_value = ({1: 10}, [])

        with patch.dict(os.environ, {"NEEDS_WORKFLOW_DEV_STORE": "1"}):
            draft = self.client.post(
                "/api/v1/replenishment/needs-list/draft",
                self._draft_payload(),
                format="json",
            ).json()
            needs_list_id = draft["needs_list_id"]
            submit = self.client.post(
                f"/api/v1/replenishment/needs-list/{needs_list_id}/submit",
                {},
                format="json",
            )
            self.assertEqual(submit.status_code, 200)
            submit_again = self.client.post(
                f"/api/v1/replenishment/needs-list/{needs_list_id}/submit",
                {},
                format="json",
            )
            self.assertEqual(submit_again.status_code, 409)

            with self.settings(DEV_AUTH_ROLES=["EXECUTIVE"]):
                review_same_user = self.client.post(
                    f"/api/v1/replenishment/needs-list/{needs_list_id}/review/start",
                    {},
                    format="json",
                )
                self.assertEqual(review_same_user.status_code, 409)

            with self.settings(
                DEV_AUTH_USER_ID="reviewer",
                DEV_AUTH_ROLES=["EXECUTIVE"],
            ):
                review = self.client.post(
                    f"/api/v1/replenishment/needs-list/{needs_list_id}/review/start",
                    {},
                    format="json",
                )
                self.assertEqual(review.status_code, 200)
                self.assertEqual(review.json().get("status"), "UNDER_REVIEW")

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="reviewer",
        DEV_AUTH_ROLES=["EXECUTIVE"],
        DEV_AUTH_PERMISSIONS=[],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch("replenishment.views.data_access.get_item_categories")
    @patch("replenishment.views.data_access.get_category_burn_fallback_rates")
    @patch("replenishment.views.data_access.get_burn_by_item")
    @patch("replenishment.views.data_access.get_inbound_transfers_by_item")
    @patch("replenishment.views.data_access.get_inbound_donations_by_item")
    @patch("replenishment.views.data_access.get_available_by_item")
    def test_return_and_reject_require_reason(
        self,
        mock_available,
        mock_donations,
        mock_transfers,
        mock_burn,
        mock_fallback,
        mock_categories,
    ) -> None:
        mock_available.return_value = ({1: 10.0}, [], None)
        mock_donations.return_value = ({}, [])
        mock_transfers.return_value = ({}, [])
        mock_burn.return_value = ({1: 24.0}, [], "reliefpkg", {"filter": "test"})
        mock_fallback.return_value = ({}, [], {})
        mock_categories.return_value = ({1: 10}, [])

        with patch.dict(os.environ, {"NEEDS_WORKFLOW_DEV_STORE": "1"}):
            with self.settings(DEV_AUTH_ROLES=["LOGISTICS"], DEV_AUTH_USER_ID="submitter"):
                draft = self.client.post(
                    "/api/v1/replenishment/needs-list/draft",
                    self._draft_payload(),
                    format="json",
                ).json()
                needs_list_id = draft["needs_list_id"]
                self.client.post(
                    f"/api/v1/replenishment/needs-list/{needs_list_id}/submit",
                    {},
                    format="json",
                )

            review = self.client.post(
                f"/api/v1/replenishment/needs-list/{needs_list_id}/review/start",
                {},
                format="json",
            )
            self.assertEqual(review.status_code, 200)

            returned = self.client.post(
                f"/api/v1/replenishment/needs-list/{needs_list_id}/return",
                {},
                format="json",
            )
            self.assertEqual(returned.status_code, 400)

            rejected = self.client.post(
                f"/api/v1/replenishment/needs-list/{needs_list_id}/reject",
                {},
                format="json",
            )
            self.assertEqual(rejected.status_code, 400)

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="submitter",
        DEV_AUTH_ROLES=["LOGISTICS"],
        DEV_AUTH_PERMISSIONS=[],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch("replenishment.views.data_access.get_item_categories")
    @patch("replenishment.views.data_access.get_category_burn_fallback_rates")
    @patch("replenishment.views.data_access.get_burn_by_item")
    @patch("replenishment.views.data_access.get_inbound_transfers_by_item")
    @patch("replenishment.views.data_access.get_inbound_donations_by_item")
    @patch("replenishment.views.data_access.get_available_by_item")
    def test_rbac_denies_unauthorized_review(
        self,
        mock_available,
        mock_donations,
        mock_transfers,
        mock_burn,
        mock_fallback,
        mock_categories,
    ) -> None:
        mock_available.return_value = ({1: 10.0}, [], None)
        mock_donations.return_value = ({}, [])
        mock_transfers.return_value = ({}, [])
        mock_burn.return_value = ({1: 24.0}, [], "reliefpkg", {"filter": "test"})
        mock_fallback.return_value = ({}, [], {})
        mock_categories.return_value = ({1: 10}, [])

        with patch.dict(os.environ, {"NEEDS_WORKFLOW_DEV_STORE": "1"}):
            draft = self.client.post(
                "/api/v1/replenishment/needs-list/draft",
                self._draft_payload(),
                format="json",
            ).json()
            needs_list_id = draft["needs_list_id"]
            self.client.post(
                f"/api/v1/replenishment/needs-list/{needs_list_id}/submit",
                {},
                format="json",
            )

            review = self.client.post(
                f"/api/v1/replenishment/needs-list/{needs_list_id}/review/start",
                {},
                format="json",
            )
            self.assertEqual(review.status_code, 403)

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="submitter",
        DEV_AUTH_ROLES=["LOGISTICS"],
        DEV_AUTH_PERMISSIONS=[],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch("replenishment.views.data_access.get_item_categories")
    @patch("replenishment.views.data_access.get_category_burn_fallback_rates")
    @patch("replenishment.views.data_access.get_burn_by_item")
    @patch("replenishment.views.data_access.get_inbound_transfers_by_item")
    @patch("replenishment.views.data_access.get_inbound_donations_by_item")
    @patch("replenishment.views.data_access.get_available_by_item")
    def test_approve_requires_authorized_role(
        self,
        mock_available,
        mock_donations,
        mock_transfers,
        mock_burn,
        mock_fallback,
        mock_categories,
    ) -> None:
        mock_available.return_value = ({1: 10.0}, [], None)
        mock_donations.return_value = ({}, [])
        mock_transfers.return_value = ({}, [])
        mock_burn.return_value = ({1: 24.0}, [], "reliefpkg", {"filter": "test"})
        mock_fallback.return_value = ({}, [], {})
        mock_categories.return_value = ({1: 10}, [])

        with patch.dict(os.environ, {"NEEDS_WORKFLOW_DEV_STORE": "1"}):
            draft = self.client.post(
                "/api/v1/replenishment/needs-list/draft",
                self._draft_payload(),
                format="json",
            ).json()
            needs_list_id = draft["needs_list_id"]
            self.client.post(
                f"/api/v1/replenishment/needs-list/{needs_list_id}/submit",
                {},
                format="json",
            )

            with self.settings(DEV_AUTH_ROLES=["EXECUTIVE"], DEV_AUTH_USER_ID="reviewer"):
                self.client.post(
                    f"/api/v1/replenishment/needs-list/{needs_list_id}/review/start",
                    {},
                    format="json",
                )
                approve = self.client.post(
                    f"/api/v1/replenishment/needs-list/{needs_list_id}/approve",
                    {},
                    format="json",
                )
                self.assertEqual(approve.status_code, 200)
                body = approve.json()
                self.assertEqual(body.get("status"), "APPROVED")
                self.assertEqual(body.get("approval_tier"), "Tier 3")
                self.assertIn(
                    "approval_tier_conservative",
                    body.get("approval_summary", {}).get("warnings", []),
                )

            with self.settings(DEV_AUTH_ROLES=["LOGISTICS"], DEV_AUTH_USER_ID="approver"):
                approve_denied = self.client.post(
                    f"/api/v1/replenishment/needs-list/{needs_list_id}/approve",
                    {},
                    format="json",
                )
                self.assertEqual(approve_denied.status_code, 403)

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="submitter",
        DEV_AUTH_ROLES=["LOGISTICS"],
        DEV_AUTH_PERMISSIONS=[],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch("replenishment.views.data_access.get_item_categories")
    @patch("replenishment.views.data_access.get_category_burn_fallback_rates")
    @patch("replenishment.views.data_access.get_burn_by_item")
    @patch("replenishment.views.data_access.get_inbound_transfers_by_item")
    @patch("replenishment.views.data_access.get_inbound_donations_by_item")
    @patch("replenishment.views.data_access.get_available_by_item")
    def test_approve_blocked_for_submitter(
        self,
        mock_available,
        mock_donations,
        mock_transfers,
        mock_burn,
        mock_fallback,
        mock_categories,
    ) -> None:
        mock_available.return_value = ({1: 10.0}, [], None)
        mock_donations.return_value = ({}, [])
        mock_transfers.return_value = ({}, [])
        mock_burn.return_value = ({1: 24.0}, [], "reliefpkg", {"filter": "test"})
        mock_fallback.return_value = ({}, [], {})
        mock_categories.return_value = ({1: 10}, [])

        with patch.dict(os.environ, {"NEEDS_WORKFLOW_DEV_STORE": "1"}):
            draft = self.client.post(
                "/api/v1/replenishment/needs-list/draft",
                self._draft_payload(),
                format="json",
            ).json()
            needs_list_id = draft["needs_list_id"]
            self.client.post(
                f"/api/v1/replenishment/needs-list/{needs_list_id}/submit",
                {},
                format="json",
            )

            with self.settings(DEV_AUTH_ROLES=["EXECUTIVE"]):
                self.client.post(
                    f"/api/v1/replenishment/needs-list/{needs_list_id}/review/start",
                    {},
                    format="json",
                )

            with self.settings(DEV_AUTH_ROLES=["EXECUTIVE"], DEV_AUTH_USER_ID="submitter"):
                approve = self.client.post(
                    f"/api/v1/replenishment/needs-list/{needs_list_id}/approve",
                    {},
                    format="json",
                )
                self.assertEqual(approve.status_code, 409)

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="reviewer",
        DEV_AUTH_ROLES=["EXECUTIVE"],
        DEV_AUTH_PERMISSIONS=[],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch("replenishment.views.data_access.get_item_categories")
    @patch("replenishment.views.data_access.get_category_burn_fallback_rates")
    @patch("replenishment.views.data_access.get_burn_by_item")
    @patch("replenishment.views.data_access.get_inbound_transfers_by_item")
    @patch("replenishment.views.data_access.get_inbound_donations_by_item")
    @patch("replenishment.views.data_access.get_available_by_item")
    def test_escalate_requires_reason(
        self,
        mock_available,
        mock_donations,
        mock_transfers,
        mock_burn,
        mock_fallback,
        mock_categories,
    ) -> None:
        mock_available.return_value = ({1: 10.0}, [], None)
        mock_donations.return_value = ({}, [])
        mock_transfers.return_value = ({}, [])
        mock_burn.return_value = ({1: 24.0}, [], "reliefpkg", {"filter": "test"})
        mock_fallback.return_value = ({}, [], {})
        mock_categories.return_value = ({1: 10}, [])

        with patch.dict(os.environ, {"NEEDS_WORKFLOW_DEV_STORE": "1"}):
            with self.settings(DEV_AUTH_ROLES=["LOGISTICS"], DEV_AUTH_USER_ID="submitter"):
                draft = self.client.post(
                    "/api/v1/replenishment/needs-list/draft",
                    self._draft_payload(),
                    format="json",
                ).json()
                needs_list_id = draft["needs_list_id"]
                self.client.post(
                    f"/api/v1/replenishment/needs-list/{needs_list_id}/submit",
                    {},
                    format="json",
                )

            self.client.post(
                f"/api/v1/replenishment/needs-list/{needs_list_id}/review/start",
                {},
                format="json",
            )
            missing = self.client.post(
                f"/api/v1/replenishment/needs-list/{needs_list_id}/escalate",
                {},
                format="json",
            )
            self.assertEqual(missing.status_code, 400)

            escalated = self.client.post(
                f"/api/v1/replenishment/needs-list/{needs_list_id}/escalate",
                {"reason": "Higher authority needed"},
                format="json",
            )
            self.assertEqual(escalated.status_code, 200)
            self.assertEqual(escalated.json().get("status"), "ESCALATED")
