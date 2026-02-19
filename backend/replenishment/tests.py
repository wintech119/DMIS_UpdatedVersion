import os
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import timedelta
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from replenishment import rules, workflow_store, workflow_store_db
from replenishment.models import NeedsList, NeedsListItem
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


class NeedsListPreviewMultiApiTests(TestCase):
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
    @patch("replenishment.views.data_access.get_warehouse_name")
    @patch("replenishment.views.data_access.get_item_categories")
    @patch("replenishment.views.data_access.get_category_burn_fallback_rates")
    @patch("replenishment.views.data_access.get_burn_by_item")
    @patch("replenishment.views.data_access.get_inbound_transfers_by_item")
    @patch("replenishment.views.data_access.get_inbound_donations_by_item")
    @patch("replenishment.views.data_access.get_available_by_item")
    def test_preview_multi_aggregates_warehouses(
        self,
        mock_available,
        mock_donations,
        mock_transfers,
        mock_burn,
        mock_fallback,
        mock_categories,
        mock_warehouse_name,
    ) -> None:
        mock_available.return_value = ({1: 10.0}, [], None)
        mock_donations.return_value = ({}, [])
        mock_transfers.return_value = ({}, [])
        mock_burn.return_value = ({1: 24.0}, [], "reliefpkg", {"filter": "test"})
        mock_fallback.return_value = ({}, [], {})
        mock_categories.return_value = ({1: 10}, [])
        mock_warehouse_name.side_effect = lambda wh_id: f"Warehouse {wh_id}"

        response = self.client.post(
            "/api/v1/replenishment/needs-list/preview-multi",
            {
                "event_id": 1,
                "warehouse_ids": [1, 2],
                "phase": "BASELINE",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("items", body)
        self.assertIn("warehouses", body)
        self.assertIn("warehouse_ids", body)
        self.assertEqual(body["warehouse_ids"], [1, 2])
        self.assertEqual(len(body["warehouses"]), 2)
        # Should have items from both warehouses
        self.assertEqual(len(body["items"]), 2)
        # Each item should have warehouse info
        for item in body["items"]:
            self.assertIn("warehouse_id", item)
            self.assertIn("warehouse_name", item)
            self.assertIn(item["warehouse_id"], [1, 2])

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="dev-user",
        DEV_AUTH_ROLES=["LOGISTICS"],
        DEV_AUTH_PERMISSIONS=[],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    def test_preview_multi_requires_warehouse_ids_array(self) -> None:
        response = self.client.post(
            "/api/v1/replenishment/needs-list/preview-multi",
            {
                "event_id": 1,
                "phase": "BASELINE",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("warehouse_ids", response.json()["errors"])

        # Test with non-array warehouse_ids
        response = self.client.post(
            "/api/v1/replenishment/needs-list/preview-multi",
            {
                "event_id": 1,
                "warehouse_ids": 1,  # Not an array
                "phase": "BASELINE",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="dev-user",
        DEV_AUTH_ROLES=["LOGISTICS"],
        DEV_AUTH_PERMISSIONS=[],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch("replenishment.views.data_access.get_warehouse_name")
    @patch("replenishment.views.data_access.get_item_categories")
    @patch("replenishment.views.data_access.get_category_burn_fallback_rates")
    @patch("replenishment.views.data_access.get_burn_by_item")
    @patch("replenishment.views.data_access.get_inbound_transfers_by_item")
    @patch("replenishment.views.data_access.get_inbound_donations_by_item")
    @patch("replenishment.views.data_access.get_available_by_item")
    def test_preview_multi_handles_single_warehouse(
        self,
        mock_available,
        mock_donations,
        mock_transfers,
        mock_burn,
        mock_fallback,
        mock_categories,
        mock_warehouse_name,
    ) -> None:
        mock_available.return_value = ({1: 10.0}, [], None)
        mock_donations.return_value = ({}, [])
        mock_transfers.return_value = ({}, [])
        mock_burn.return_value = ({1: 24.0}, [], "reliefpkg", {"filter": "test"})
        mock_fallback.return_value = ({}, [], {})
        mock_categories.return_value = ({1: 10}, [])
        mock_warehouse_name.return_value = "Kingston Central"

        response = self.client.post(
            "/api/v1/replenishment/needs-list/preview-multi",
            {
                "event_id": 1,
                "warehouse_ids": [1],
                "phase": "BASELINE",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["warehouses"]), 1)
        self.assertEqual(body["warehouses"][0]["warehouse_name"], "Kingston Central")


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
    def test_draft_creation_respects_selected_items_and_transfer_method(
        self,
        mock_available,
        mock_donations,
        mock_transfers,
        mock_burn,
        mock_fallback,
        mock_categories,
    ) -> None:
        mock_available.return_value = ({1: 10.0, 2: 10.0}, [], None)
        mock_donations.return_value = ({}, [])
        mock_transfers.return_value = ({}, [])
        mock_burn.return_value = ({1: 24.0, 2: 24.0}, [], "reliefpkg", {"filter": "test"})
        mock_fallback.return_value = ({}, [], {})
        mock_categories.return_value = ({1: 10, 2: 10}, [])

        payload = {
            **self._draft_payload(),
            "selected_item_keys": ["1_1"],
            "selected_method": "A",
        }

        with patch.dict(os.environ, {"NEEDS_WORKFLOW_DEV_STORE": "1"}):
            response = self.client.post(
                "/api/v1/replenishment/needs-list/draft",
                payload,
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body.get("items", [])), 1)
        self.assertEqual(body["items"][0]["item_id"], 1)
        self.assertEqual(body.get("selected_method"), "A")
        self.assertIsNotNone(body.get("event_name"))

        approval = body.get("approval_summary", {}).get("approval", {})
        warnings = body.get("approval_summary", {}).get("warnings", [])
        self.assertEqual(approval.get("tier"), "Below Tier 1")
        self.assertEqual(approval.get("approver_role"), "Logistics Manager (Kemar)")
        self.assertNotIn("approval_tier_conservative", warnings)
        self.assertNotIn("cost_missing_for_approval", warnings)

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
    def test_submit_and_approve_separation(
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
                approve_same_user = self.client.post(
                    f"/api/v1/replenishment/needs-list/{needs_list_id}/approve",
                    {},
                    format="json",
                )
                self.assertEqual(approve_same_user.status_code, 409)

            with self.settings(
                DEV_AUTH_USER_ID="reviewer",
                DEV_AUTH_ROLES=["EXECUTIVE"],
            ):
                approve = self.client.post(
                    f"/api/v1/replenishment/needs-list/{needs_list_id}/approve",
                    {},
                    format="json",
                )
                self.assertEqual(approve.status_code, 200)
                self.assertEqual(approve.json().get("status"), "APPROVED")

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="submitter",
        DEV_AUTH_ROLES=[],
        DEV_AUTH_PERMISSIONS=[
            "replenishment.needs_list.preview",
            "replenishment.needs_list.create_draft",
        ],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch("replenishment.views.data_access.get_item_categories")
    @patch("replenishment.views.data_access.get_category_burn_fallback_rates")
    @patch("replenishment.views.data_access.get_burn_by_item")
    @patch("replenishment.views.data_access.get_inbound_transfers_by_item")
    @patch("replenishment.views.data_access.get_inbound_donations_by_item")
    @patch("replenishment.views.data_access.get_available_by_item")
    def test_submit_requires_submit_permission(
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

        self.assertEqual(submit.status_code, 403)

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
    def test_request_changes_requires_reason_code_and_allows_resubmit(
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
            with self.settings(
                DEV_AUTH_USER_ID="submitter",
                DEV_AUTH_ROLES=[],
                DEV_AUTH_PERMISSIONS=[
                    "replenishment.needs_list.preview",
                    "replenishment.needs_list.create_draft",
                    "replenishment.needs_list.submit",
                    "replenishment.needs_list.return",
                    "replenishment.needs_list.reject",
                ],
            ):
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
                self_review_return = self.client.post(
                    f"/api/v1/replenishment/needs-list/{needs_list_id}/return",
                    {"reason_code": "DATA_QUALITY", "reason": "Self-review attempt"},
                    format="json",
                )
                self.assertEqual(self_review_return.status_code, 409)
                self.assertIn("review", self_review_return.json().get("errors", {}))

            returned = self.client.post(
                f"/api/v1/replenishment/needs-list/{needs_list_id}/return",
                {},
                format="json",
            )
            self.assertEqual(returned.status_code, 400)
            self.assertIn("reason_code", returned.json().get("errors", {}))

            returned_invalid = self.client.post(
                f"/api/v1/replenishment/needs-list/{needs_list_id}/return",
                {"reason_code": "NOT_A_REAL_CODE", "reason": "Bad code"},
                format="json",
            )
            self.assertEqual(returned_invalid.status_code, 400)

            returned_ok = self.client.post(
                f"/api/v1/replenishment/needs-list/{needs_list_id}/return",
                {"reason_code": "DATA_QUALITY", "reason": "Data mismatch"},
                format="json",
            )
            self.assertEqual(returned_ok.status_code, 200)
            self.assertEqual(returned_ok.json().get("status"), "MODIFIED")
            self.assertEqual(returned_ok.json().get("return_reason_code"), "DATA_QUALITY")

            with self.settings(
                DEV_AUTH_USER_ID="submitter",
                DEV_AUTH_ROLES=[],
                DEV_AUTH_PERMISSIONS=[
                    "replenishment.needs_list.preview",
                    "replenishment.needs_list.create_draft",
                    "replenishment.needs_list.submit",
                    "replenishment.needs_list.return",
                    "replenishment.needs_list.reject",
                ],
            ):
                resubmit = self.client.post(
                    f"/api/v1/replenishment/needs-list/{needs_list_id}/submit",
                    {},
                    format="json",
                )
                self.assertEqual(resubmit.status_code, 200)
                self.assertEqual(resubmit.json().get("status"), "SUBMITTED")
                self_reject = self.client.post(
                    f"/api/v1/replenishment/needs-list/{needs_list_id}/reject",
                    {"reason": "Self-reject attempt"},
                    format="json",
                )
                self.assertEqual(self_reject.status_code, 409)
                self.assertIn("review", self_reject.json().get("errors", {}))

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
    def test_submitted_needs_list_appears_in_queue_filter(
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

            queue = self.client.get(
                "/api/v1/replenishment/needs-list/?status=SUBMITTED,UNDER_REVIEW"
            )

        self.assertEqual(queue.status_code, 200)
        queue_ids = [row.get("needs_list_id") for row in queue.json().get("needs_lists", [])]
        self.assertIn(needs_list_id, queue_ids)

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
    def test_needs_list_list_mine_filter_returns_only_actor_records(
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
            mine_draft = self.client.post(
                "/api/v1/replenishment/needs-list/draft",
                self._draft_payload(),
                format="json",
            ).json()

            with self.settings(
                DEV_AUTH_USER_ID="another-user",
                DEV_AUTH_ROLES=["LOGISTICS"],
                DEV_AUTH_PERMISSIONS=[],
            ):
                self.client.post(
                    "/api/v1/replenishment/needs-list/draft",
                    self._draft_payload(),
                    format="json",
                )

            mine_only = self.client.get(
                "/api/v1/replenishment/needs-list/?mine=true&include_closed=false"
            )

        self.assertEqual(mine_only.status_code, 200)
        mine_ids = [row.get("needs_list_id") for row in mine_only.json().get("needs_lists", [])]
        self.assertEqual(mine_ids, [mine_draft.get("needs_list_id")])

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
    def test_my_submissions_endpoint_returns_paginated_summary(
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
            response = self.client.get(
                "/api/v1/replenishment/needs-list/my-submissions/?page=1&page_size=10"
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertGreaterEqual(body.get("count", 0), 1)
        self.assertIn("results", body)
        result = body["results"][0]
        self.assertEqual(result.get("id"), draft.get("needs_list_id"))
        self.assertIn("horizon_summary", result)
        self.assertIn("status", result)

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
    def test_my_submissions_date_to_filter_is_inclusive_for_day_only_values(
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

            unfiltered = self.client.get(
                "/api/v1/replenishment/needs-list/my-submissions/?page=1&page_size=10"
            )
            self.assertEqual(unfiltered.status_code, 200)

            matching = next(
                (
                    row
                    for row in unfiltered.json().get("results", [])
                    if row.get("id") == draft.get("needs_list_id")
                ),
                None,
            )
            self.assertIsNotNone(matching)
            last_updated_at = str((matching or {}).get("last_updated_at") or "")
            self.assertTrue(last_updated_at)
            date_to = last_updated_at.split("T", 1)[0]

            filtered = self.client.get(
                f"/api/v1/replenishment/needs-list/my-submissions/?date_to={date_to}&page=1&page_size=10"
            )

        self.assertEqual(filtered.status_code, 200)
        filtered_ids = [row.get("id") for row in filtered.json().get("results", [])]
        self.assertIn(draft.get("needs_list_id"), filtered_ids)

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
    def test_my_submissions_status_filter_accepts_ui_aliases_in_file_store(
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
            submit = self.client.post(
                f"/api/v1/replenishment/needs-list/{draft['needs_list_id']}/submit",
                {},
                format="json",
            )
            self.assertEqual(submit.status_code, 200)

            filtered = self.client.get(
                "/api/v1/replenishment/needs-list/my-submissions/?status=PENDING_APPROVAL&page=1&page_size=10"
            )

        self.assertEqual(filtered.status_code, 200)
        filtered_ids = [row.get("id") for row in filtered.json().get("results", [])]
        self.assertIn(draft.get("needs_list_id"), filtered_ids)

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
    def test_bulk_submit_and_bulk_delete_endpoints(
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

        with patch("replenishment.views.logger.info") as mock_logger_info:
            with patch.dict(os.environ, {"NEEDS_WORKFLOW_DEV_STORE": "1"}):
                draft_one = self.client.post(
                    "/api/v1/replenishment/needs-list/draft",
                    self._draft_payload(),
                    format="json",
                ).json()

                submit_response = self.client.post(
                    "/api/v1/replenishment/needs-list/bulk-submit/",
                    {"ids": [draft_one["needs_list_id"]]},
                    format="json",
                )

                draft_two = self.client.post(
                    "/api/v1/replenishment/needs-list/draft",
                    self._draft_payload(),
                    format="json",
                ).json()

                delete_response = self.client.post(
                    "/api/v1/replenishment/needs-list/bulk-delete/",
                    {"ids": [draft_two["needs_list_id"]], "reason": "Cleanup"},
                    format="json",
                )
                version_response = self.client.get(
                    f"/api/v1/replenishment/needs-list/{draft_one['needs_list_id']}/summary-version"
                )
                sources_response = self.client.get(
                    f"/api/v1/replenishment/needs-list/{draft_one['needs_list_id']}/fulfillment-sources"
                )

        self.assertEqual(submit_response.status_code, 200)
        self.assertEqual(delete_response.status_code, 200)
        self.assertEqual(version_response.status_code, 200)
        self.assertEqual(sources_response.status_code, 200)
        self.assertEqual(submit_response.json().get("count"), 1)
        self.assertEqual(delete_response.json().get("count"), 1)
        self.assertIn("data_version", version_response.json())
        self.assertIn("lines", sources_response.json())
        submitted_logs = [
            call.kwargs.get("extra", {})
            for call in mock_logger_info.call_args_list
            if call.args and call.args[0] == "needs_list_submitted"
        ]
        cancelled_logs = [
            call.kwargs.get("extra", {})
            for call in mock_logger_info.call_args_list
            if call.args and call.args[0] == "needs_list_cancelled"
        ]
        self.assertGreaterEqual(len(submitted_logs), 1)
        self.assertGreaterEqual(len(cancelled_logs), 1)
        self.assertEqual(submitted_logs[0].get("event_type"), "STATE_CHANGE")
        self.assertEqual(cancelled_logs[0].get("event_type"), "STATE_CHANGE")
        self.assertEqual(cancelled_logs[0].get("reason"), "Cleanup")

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
    def test_fulfillment_sources_use_overridden_required_qty_for_tracker_math(
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

            override_response = self.client.patch(
                f"/api/v1/replenishment/needs-list/{needs_list_id}/lines",
                [{"item_id": 1, "overridden_qty": 5, "reason": "Adjust to approved level"}],
                format="json",
            )
            self.assertEqual(override_response.status_code, 200)

            record = workflow_store.get_record(needs_list_id)
            self.assertIsNotNone(record)
            snapshot_items = (record or {}).get("snapshot", {}).get("items", [])
            self.assertTrue(snapshot_items)
            snapshot_items[0]["fulfilled_qty"] = 3
            workflow_store.update_record(needs_list_id, record)

            partial_response = self.client.get(
                f"/api/v1/replenishment/needs-list/{needs_list_id}/fulfillment-sources"
            )
            self.assertEqual(partial_response.status_code, 200)
            partial_line = next(
                (
                    line
                    for line in partial_response.json().get("lines", [])
                    if line.get("id") == 1
                ),
                None,
            )
            self.assertIsNotNone(partial_line)
            self.assertEqual(partial_line.get("original_qty"), 5.0)
            self.assertEqual(partial_line.get("covered_qty"), 3.0)
            self.assertEqual(partial_line.get("remaining_qty"), 2.0)
            self.assertFalse(partial_line.get("is_fully_covered"))

            snapshot_items[0]["fulfilled_qty"] = 5
            workflow_store.update_record(needs_list_id, record)

            covered_response = self.client.get(
                f"/api/v1/replenishment/needs-list/{needs_list_id}/fulfillment-sources"
            )

        self.assertEqual(covered_response.status_code, 200)
        covered_line = next(
            (
                line
                for line in covered_response.json().get("lines", [])
                if line.get("id") == 1
            ),
            None,
        )
        self.assertIsNotNone(covered_line)
        self.assertEqual(covered_line.get("original_qty"), 5.0)
        self.assertEqual(covered_line.get("covered_qty"), 5.0)
        self.assertEqual(covered_line.get("remaining_qty"), 0.0)
        self.assertTrue(covered_line.get("is_fully_covered"))

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
    def test_new_draft_supersedes_existing_submitted_for_same_scope_and_actor(
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
            first_draft = self.client.post(
                "/api/v1/replenishment/needs-list/draft",
                self._draft_payload(),
                format="json",
            ).json()
            first_id = first_draft["needs_list_id"]

            submit = self.client.post(
                f"/api/v1/replenishment/needs-list/{first_id}/submit",
                {},
                format="json",
            )
            self.assertEqual(submit.status_code, 200)

            second_draft = self.client.post(
                "/api/v1/replenishment/needs-list/draft",
                self._draft_payload(),
                format="json",
            )
            self.assertEqual(second_draft.status_code, 200)
            second_body = second_draft.json()
            second_id = second_body["needs_list_id"]

            superseded = self.client.get(f"/api/v1/replenishment/needs-list/{first_id}")
            self.assertEqual(superseded.status_code, 200)

            queue = self.client.get(
                "/api/v1/replenishment/needs-list/?status=SUBMITTED,UNDER_REVIEW"
            )

        self.assertNotEqual(first_id, second_id)
        self.assertIn(first_id, second_body.get("supersedes_needs_list_ids", []))
        superseded_body = superseded.json()
        self.assertEqual(superseded_body.get("status"), "SUPERSEDED")
        self.assertEqual(superseded_body.get("superseded_by"), second_id)
        queue_ids = [row.get("needs_list_id") for row in queue.json().get("needs_lists", [])]
        self.assertNotIn(first_id, queue_ids)

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
    def test_rbac_denies_unauthorized_approve(
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

            approve = self.client.post(
                f"/api/v1/replenishment/needs-list/{needs_list_id}/approve",
                {},
                format="json",
            )
            self.assertEqual(approve.status_code, 403)

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
    def test_review_comments_requires_pending_approval(
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

            denied = self.client.patch(
                f"/api/v1/replenishment/needs-list/{needs_list_id}/review-comments",
                [{"item_id": 1, "comment": "Fix qty"}],
                format="json",
            )
            self.assertEqual(denied.status_code, 409)

            with self.settings(DEV_AUTH_ROLES=["LOGISTICS"], DEV_AUTH_USER_ID="submitter"):
                self.client.post(
                    f"/api/v1/replenishment/needs-list/{needs_list_id}/submit",
                    {},
                    format="json",
                )

            ok = self.client.patch(
                f"/api/v1/replenishment/needs-list/{needs_list_id}/review-comments",
                [{"item_id": 1, "comment": "Fix qty"}],
                format="json",
            )
            self.assertEqual(ok.status_code, 200)

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
    def test_review_reminder_requires_4_hours_and_recommends_escalation_after_8(
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

            too_early = self.client.post(
                f"/api/v1/replenishment/needs-list/{needs_list_id}/review/reminder",
                {},
                format="json",
            )
            self.assertEqual(too_early.status_code, 409)
            self.assertIn("reminder", too_early.json().get("errors", {}))

            record = workflow_store.get_record(needs_list_id)
            record["submitted_at"] = (timezone.now() - timedelta(hours=5)).isoformat()
            workflow_store.update_record(needs_list_id, record)

            reminded = self.client.post(
                f"/api/v1/replenishment/needs-list/{needs_list_id}/review/reminder",
                {},
                format="json",
            )
            self.assertEqual(reminded.status_code, 200)
            reminder = reminded.json().get("review_reminder", {})
            self.assertGreaterEqual(reminder.get("pending_hours", 0), 5)
            self.assertFalse(reminder.get("escalation_recommended"))

            record = workflow_store.get_record(needs_list_id)
            record["submitted_at"] = (timezone.now() - timedelta(hours=9)).isoformat()
            workflow_store.update_record(needs_list_id, record)

            escalated = self.client.post(
                f"/api/v1/replenishment/needs-list/{needs_list_id}/review/reminder",
                {},
                format="json",
            )
            self.assertEqual(escalated.status_code, 200)
            reminder = escalated.json().get("review_reminder", {})
            self.assertGreaterEqual(reminder.get("pending_hours", 0), 8)
            self.assertTrue(reminder.get("escalation_recommended"))

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="approver",
        DEV_AUTH_ROLES=[],
        DEV_AUTH_PERMISSIONS=[
            "replenishment.needs_list.preview",
            "replenishment.needs_list.approve",
        ],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch("replenishment.views.data_access.get_item_categories")
    @patch("replenishment.views.data_access.get_category_burn_fallback_rates")
    @patch("replenishment.views.data_access.get_burn_by_item")
    @patch("replenishment.views.data_access.get_inbound_transfers_by_item")
    @patch("replenishment.views.data_access.get_inbound_donations_by_item")
    @patch("replenishment.views.data_access.get_available_by_item")
    def test_review_reminder_allows_approve_only_permission(
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
            with self.settings(
                DEV_AUTH_USER_ID="submitter",
                DEV_AUTH_ROLES=[],
                DEV_AUTH_PERMISSIONS=[
                    "replenishment.needs_list.preview",
                    "replenishment.needs_list.create_draft",
                    "replenishment.needs_list.submit",
                ],
            ):
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

            record = workflow_store.get_record(needs_list_id)
            record["submitted_at"] = (timezone.now() - timedelta(hours=5)).isoformat()
            workflow_store.update_record(needs_list_id, record)

            reminded = self.client.post(
                f"/api/v1/replenishment/needs-list/{needs_list_id}/review/reminder",
                {},
                format="json",
            )
            self.assertEqual(reminded.status_code, 200)
            reminder = reminded.json().get("review_reminder", {})
            self.assertGreaterEqual(reminder.get("pending_hours", 0), 5)

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
            with self.settings(
                DEV_AUTH_USER_ID="submitter",
                DEV_AUTH_ROLES=[],
                DEV_AUTH_PERMISSIONS=[
                    "replenishment.needs_list.preview",
                    "replenishment.needs_list.create_draft",
                    "replenishment.needs_list.submit",
                    "replenishment.needs_list.escalate",
                ],
            ):
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
                self_escalate = self.client.post(
                    f"/api/v1/replenishment/needs-list/{needs_list_id}/escalate",
                    {"reason": "Self-escalation attempt"},
                    format="json",
                )
                self.assertEqual(self_escalate.status_code, 409)
                self.assertIn("review", self_escalate.json().get("errors", {}))

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
    def test_execution_happy_path(
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
                approve = self.client.post(
                    f"/api/v1/replenishment/needs-list/{needs_list_id}/approve",
                    {},
                    format="json",
                )
                self.assertEqual(approve.status_code, 200)

            with self.settings(DEV_AUTH_ROLES=["LOGISTICS"], DEV_AUTH_USER_ID="executor"):
                prep = self.client.post(
                    f"/api/v1/replenishment/needs-list/{needs_list_id}/start-preparation",
                    {},
                    format="json",
                )
                self.assertEqual(prep.status_code, 200)
                dispatched = self.client.post(
                    f"/api/v1/replenishment/needs-list/{needs_list_id}/mark-dispatched",
                    {},
                    format="json",
                )
                self.assertEqual(dispatched.status_code, 200)
                received = self.client.post(
                    f"/api/v1/replenishment/needs-list/{needs_list_id}/mark-received",
                    {},
                    format="json",
                )
                self.assertEqual(received.status_code, 200)
                completed = self.client.post(
                    f"/api/v1/replenishment/needs-list/{needs_list_id}/mark-completed",
                    {},
                    format="json",
                )
                self.assertEqual(completed.status_code, 200)
                self.assertEqual(completed.json().get("status"), "COMPLETED")

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
    def test_db_mode_enforces_execution_stage_sequence(
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

        with patch("replenishment.views._use_db_workflow_store", return_value=True):
            with patch(
                "replenishment.workflow_store_db.data_access.get_item_names",
                return_value=({1: {"name": "WATER BOTTLE", "code": "WB-01"}}, []),
            ), patch(
                "replenishment.workflow_store_db.data_access.get_warehouse_name",
                return_value="Kingston Central Warehouse",
            ), patch(
                "replenishment.workflow_store_db.data_access.get_event_name",
                return_value="Hurricane Test Event",
            ):
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
                    approve = self.client.post(
                        f"/api/v1/replenishment/needs-list/{needs_list_id}/approve",
                        {},
                        format="json",
                    )
                    self.assertEqual(approve.status_code, 200)

                with self.settings(DEV_AUTH_ROLES=["LOGISTICS"], DEV_AUTH_USER_ID="executor"):
                    prep = self.client.post(
                        f"/api/v1/replenishment/needs-list/{needs_list_id}/start-preparation",
                        {},
                        format="json",
                    )
                    self.assertEqual(prep.status_code, 200)
                    self.assertEqual(prep.json().get("status"), "IN_PROGRESS")
                    self.assertIsNotNone(prep.json().get("prep_started_at"))

                    premature_received = self.client.post(
                        f"/api/v1/replenishment/needs-list/{needs_list_id}/mark-received",
                        {},
                        format="json",
                    )
                    self.assertEqual(premature_received.status_code, 409)

                    premature_completed = self.client.post(
                        f"/api/v1/replenishment/needs-list/{needs_list_id}/mark-completed",
                        {},
                        format="json",
                    )
                    self.assertEqual(premature_completed.status_code, 409)

                    dispatched = self.client.post(
                        f"/api/v1/replenishment/needs-list/{needs_list_id}/mark-dispatched",
                        {},
                        format="json",
                    )
                    self.assertEqual(dispatched.status_code, 200)
                    self.assertIsNotNone(dispatched.json().get("dispatched_at"))

                    dispatch_again = self.client.post(
                        f"/api/v1/replenishment/needs-list/{needs_list_id}/mark-dispatched",
                        {},
                        format="json",
                    )
                    self.assertEqual(dispatch_again.status_code, 409)

                    received = self.client.post(
                        f"/api/v1/replenishment/needs-list/{needs_list_id}/mark-received",
                        {},
                        format="json",
                    )
                    self.assertEqual(received.status_code, 200)
                    self.assertIsNotNone(received.json().get("received_at"))

                    completed = self.client.post(
                        f"/api/v1/replenishment/needs-list/{needs_list_id}/mark-completed",
                        {},
                        format="json",
                    )
                    self.assertEqual(completed.status_code, 200)
                    self.assertEqual(completed.json().get("status"), "FULFILLED")
                    self.assertIsNotNone(completed.json().get("completed_at"))

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
    def test_execution_denied_before_approved(
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

            denied = self.client.post(
                f"/api/v1/replenishment/needs-list/{needs_list_id}/start-preparation",
                {},
                format="json",
            )
            self.assertEqual(denied.status_code, 409)

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
    def test_execution_denied_for_wrong_role(
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
                    f"/api/v1/replenishment/needs-list/{needs_list_id}/approve",
                    {},
                    format="json",
                )

            with self.settings(DEV_AUTH_ROLES=["EXECUTIVE"], DEV_AUTH_USER_ID="exec"):
                denied = self.client.post(
                    f"/api/v1/replenishment/needs-list/{needs_list_id}/start-preparation",
                    {},
                    format="json",
                )
                self.assertEqual(denied.status_code, 403)

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
    def test_cancel_constraints(
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
                    f"/api/v1/replenishment/needs-list/{needs_list_id}/approve",
                    {},
                    format="json",
                )

            cancel_ok = self.client.post(
                f"/api/v1/replenishment/needs-list/{needs_list_id}/cancel",
                {"reason": "No longer needed"},
                format="json",
            )
            self.assertEqual(cancel_ok.status_code, 200)

            draft_two = self.client.post(
                "/api/v1/replenishment/needs-list/draft",
                self._draft_payload(),
                format="json",
            ).json()
            needs_list_id_two = draft_two["needs_list_id"]
            self.client.post(
                f"/api/v1/replenishment/needs-list/{needs_list_id_two}/submit",
                {},
                format="json",
            )
            with self.settings(DEV_AUTH_ROLES=["EXECUTIVE"], DEV_AUTH_USER_ID="reviewer"):
                self.client.post(
                    f"/api/v1/replenishment/needs-list/{needs_list_id_two}/approve",
                    {},
                    format="json",
                )

            with self.settings(DEV_AUTH_ROLES=["LOGISTICS"], DEV_AUTH_USER_ID="executor"):
                self.client.post(
                    f"/api/v1/replenishment/needs-list/{needs_list_id_two}/start-preparation",
                    {},
                    format="json",
                )
                self.client.post(
                    f"/api/v1/replenishment/needs-list/{needs_list_id_two}/mark-dispatched",
                    {},
                    format="json",
                )
                cancel_denied = self.client.post(
                    f"/api/v1/replenishment/needs-list/{needs_list_id_two}/cancel",
                    {"reason": "Late cancel"},
                    format="json",
                )
                self.assertEqual(cancel_denied.status_code, 409)

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
    def test_approval_requires_escalation_for_cross_parish_over_500(
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
            record = workflow_store.get_record(needs_list_id)
            item = (record.get("snapshot") or {}).get("items", [])[0]
            item["transfer_scope"] = "cross_parish"
            item["transfer_qty"] = 600
            workflow_store.update_record(needs_list_id, record)

            self.client.post(
                f"/api/v1/replenishment/needs-list/{needs_list_id}/submit",
                {},
                format="json",
            )

            with self.settings(DEV_AUTH_ROLES=["EXECUTIVE"], DEV_AUTH_USER_ID="reviewer"):
                approve = self.client.post(
                    f"/api/v1/replenishment/needs-list/{needs_list_id}/approve",
                    {},
                    format="json",
                )
                self.assertEqual(approve.status_code, 409)


class WorkflowStoreDbSerializationTests(TestCase):
    @patch("replenishment.workflow_store_db.data_access.get_event_name")
    @patch("replenishment.workflow_store_db.data_access.get_warehouse_name")
    @patch("replenishment.workflow_store_db.data_access.get_item_names")
    def test_needs_list_to_dict_returns_review_ui_fields(
        self,
        mock_item_names,
        mock_warehouse_name,
        mock_event_name,
    ) -> None:
        mock_item_names.return_value = ({9: {"name": "MEALS READY TO EAT", "code": "MRE-12"}}, [])
        mock_warehouse_name.return_value = "ODPEM MARCUS GARVEY WAREHOUSE (MG)"
        mock_event_name.return_value = "HURRICANE MELISSA"

        needs_list = NeedsList.objects.create(
            needs_list_no="NL-1-2-20260216-001",
            event_id=1,
            warehouse_id=2,
            event_phase="BASELINE",
            calculation_dtime=timezone.now(),
            demand_window_hours=24,
            planning_window_hours=72,
            safety_factor=1.25,
            data_freshness_level="HIGH",
            status_code="PENDING_APPROVAL",
            total_gap_qty=100,
            notes_text='{"selected_method":"A","warnings":["cost_missing_for_approval"]}',
            create_by_id="tester",
            update_by_id="tester",
        )
        NeedsListItem.objects.create(
            needs_list=needs_list,
            item_id=9,
            uom_code="EA",
            burn_rate=2.5,
            burn_rate_source="CALCULATED",
            available_stock=20,
            reserved_qty=0,
            inbound_transfer_qty=5,
            inbound_donation_qty=3,
            inbound_procurement_qty=0,
            required_qty=100,
            coverage_qty=28,
            gap_qty=72,
            time_to_stockout_hours=8,
            severity_level="WARNING",
            horizon_a_qty=10,
            horizon_b_qty=20,
            horizon_c_qty=42,
            create_by_id="tester",
            update_by_id="tester",
        )

        record = workflow_store_db._needs_list_to_dict(needs_list)
        snapshot_item = record["snapshot"]["items"][0]

        self.assertEqual(record.get("event_name"), "HURRICANE MELISSA")
        self.assertEqual(record.get("warehouses", [])[0]["warehouse_name"], "ODPEM MARCUS GARVEY WAREHOUSE (MG)")
        self.assertEqual(record.get("selected_method"), "A")
        self.assertIn("cost_missing_for_approval", record.get("snapshot", {}).get("warnings", []))

        self.assertEqual(snapshot_item["item_name"], "MEALS READY TO EAT")
        self.assertEqual(snapshot_item["item_code"], "MRE-12")
        self.assertEqual(snapshot_item["warehouse_name"], "ODPEM MARCUS GARVEY WAREHOUSE (MG)")
        self.assertEqual(snapshot_item["burn_rate_per_hour"], 2.5)
        self.assertEqual(snapshot_item["inbound_strict_qty"], 8.0)
        self.assertEqual(snapshot_item["horizon"]["A"]["recommended_qty"], 10.0)
        self.assertEqual(snapshot_item["horizon"]["B"]["recommended_qty"], 20.0)
        self.assertEqual(snapshot_item["horizon"]["C"]["recommended_qty"], 42.0)

    @patch("replenishment.workflow_store_db.data_access.get_event_name")
    @patch("replenishment.workflow_store_db.data_access.get_warehouse_name")
    @patch("replenishment.workflow_store_db.data_access.get_item_names")
    def test_create_draft_persists_preview_shape_values(
        self,
        mock_item_names,
        mock_warehouse_name,
        mock_event_name,
    ) -> None:
        mock_item_names.return_value = ({9: {"name": "MEALS READY TO EAT", "code": "MRE-12"}}, [])
        mock_warehouse_name.return_value = "ODPEM MARCUS GARVEY WAREHOUSE (MG)"
        mock_event_name.return_value = "HURRICANE MELISSA"

        payload = {
            "event_id": 1,
            "warehouse_id": 2,
            "phase": "BASELINE",
            "as_of_datetime": timezone.now().isoformat(),
            "planning_window_days": 3,
            "selected_method": "A",
            "selected_item_keys": ["9_2"],
        }
        items = [
            {
                "item_id": 9,
                "available_qty": 20,
                "inbound_strict_qty": 8,
                "burn_rate_per_hour": 2.5,
                "required_qty": 100,
                "gap_qty": 72,
                "time_to_stockout": 8,
                "severity": "WARNING",
                "horizon": {
                    "A": {"recommended_qty": 10},
                    "B": {"recommended_qty": 20},
                    "C": {"recommended_qty": 42},
                },
            }
        ]

        record = workflow_store_db.create_draft(
            payload,
            items,
            warnings=["cost_missing_for_approval"],
            actor="tester",
        )
        saved_item = NeedsListItem.objects.get(needs_list_id=int(record["needs_list_id"]), item_id=9)

        self.assertEqual(float(saved_item.burn_rate), 2.5)
        self.assertEqual(float(saved_item.inbound_transfer_qty), 0.0)
        self.assertEqual(float(saved_item.inbound_donation_qty), 0.0)
        self.assertEqual(float(saved_item.coverage_qty), 28.0)
        self.assertEqual(float(saved_item.horizon_a_qty), 10.0)
        self.assertEqual(float(saved_item.horizon_b_qty), 20.0)
        self.assertEqual(float(saved_item.horizon_c_qty), 42.0)

    @patch("replenishment.workflow_store_db.data_access.get_event_name")
    @patch("replenishment.workflow_store_db.data_access.get_warehouse_name")
    @patch("replenishment.workflow_store_db.data_access.get_item_names")
    def test_create_draft_derives_transfer_from_strict_and_donation_when_missing(
        self,
        mock_item_names,
        mock_warehouse_name,
        mock_event_name,
    ) -> None:
        mock_item_names.return_value = ({9: {"name": "MEALS READY TO EAT", "code": "MRE-12"}}, [])
        mock_warehouse_name.return_value = "ODPEM MARCUS GARVEY WAREHOUSE (MG)"
        mock_event_name.return_value = "HURRICANE MELISSA"

        payload = {
            "event_id": 1,
            "warehouse_id": 2,
            "phase": "BASELINE",
            "as_of_datetime": timezone.now().isoformat(),
            "planning_window_days": 3,
            "selected_method": "A",
            "selected_item_keys": ["9_2"],
        }
        items = [
            {
                "item_id": 9,
                "available_qty": 20,
                "inbound_strict_qty": 8,
                "inbound_donation_qty": 3,
                "burn_rate_per_hour": 2.5,
                "required_qty": 100,
                "gap_qty": 72,
                "time_to_stockout": 8,
                "severity": "WARNING",
                "horizon": {
                    "A": {"recommended_qty": 10},
                    "B": {"recommended_qty": 20},
                    "C": {"recommended_qty": 42},
                },
            }
        ]

        record = workflow_store_db.create_draft(
            payload,
            items,
            warnings=["cost_missing_for_approval"],
            actor="tester",
        )
        saved_item = NeedsListItem.objects.get(needs_list_id=int(record["needs_list_id"]), item_id=9)

        self.assertEqual(float(saved_item.inbound_transfer_qty), 5.0)
        self.assertEqual(float(saved_item.inbound_donation_qty), 3.0)
        self.assertEqual(float(saved_item.coverage_qty), 28.0)

    @patch("replenishment.workflow_store_db.data_access.get_event_name")
    @patch("replenishment.workflow_store_db.data_access.get_warehouse_name")
    @patch("replenishment.workflow_store_db.data_access.get_item_names")
    def test_create_draft_clamps_derived_transfer_to_non_negative(
        self,
        mock_item_names,
        mock_warehouse_name,
        mock_event_name,
    ) -> None:
        mock_item_names.return_value = ({9: {"name": "MEALS READY TO EAT", "code": "MRE-12"}}, [])
        mock_warehouse_name.return_value = "ODPEM MARCUS GARVEY WAREHOUSE (MG)"
        mock_event_name.return_value = "HURRICANE MELISSA"

        payload = {
            "event_id": 1,
            "warehouse_id": 2,
            "phase": "BASELINE",
            "as_of_datetime": timezone.now().isoformat(),
            "planning_window_days": 3,
            "selected_method": "A",
            "selected_item_keys": ["9_2"],
        }
        items = [
            {
                "item_id": 9,
                "available_qty": 20,
                "inbound_strict_qty": 2,
                "inbound_donation_qty": 3,
                "burn_rate_per_hour": 2.5,
                "required_qty": 100,
                "gap_qty": 72,
                "time_to_stockout": 8,
                "severity": "WARNING",
                "horizon": {
                    "A": {"recommended_qty": 10},
                    "B": {"recommended_qty": 20},
                    "C": {"recommended_qty": 42},
                },
            }
        ]

        record = workflow_store_db.create_draft(
            payload,
            items,
            warnings=["cost_missing_for_approval"],
            actor="tester",
        )
        saved_item = NeedsListItem.objects.get(needs_list_id=int(record["needs_list_id"]), item_id=9)

        self.assertEqual(float(saved_item.inbound_transfer_qty), 0.0)
        self.assertEqual(float(saved_item.inbound_donation_qty), 3.0)
        self.assertEqual(float(saved_item.coverage_qty), 22.0)

    @patch("replenishment.workflow_store_db.data_access.get_event_name")
    @patch("replenishment.workflow_store_db.data_access.get_warehouse_name")
    @patch("replenishment.workflow_store_db.data_access.get_item_names")
    def test_create_draft_supersedes_open_records_for_same_scope_and_actor(
        self,
        mock_item_names,
        mock_warehouse_name,
        mock_event_name,
    ) -> None:
        mock_item_names.return_value = ({9: {"name": "MEALS READY TO EAT", "code": "MRE-12"}}, [])
        mock_warehouse_name.return_value = "ODPEM MARCUS GARVEY WAREHOUSE (MG)"
        mock_event_name.return_value = "HURRICANE MELISSA"

        older = NeedsList.objects.create(
            needs_list_no="NL-1-2-20260216-001",
            event_id=1,
            warehouse_id=2,
            event_phase="BASELINE",
            calculation_dtime=timezone.now(),
            demand_window_hours=24,
            planning_window_hours=72,
            safety_factor=1.25,
            data_freshness_level="HIGH",
            status_code="PENDING_APPROVAL",
            total_gap_qty=100,
            create_by_id="tester",
            update_by_id="tester",
            submitted_by="tester",
            submitted_at=timezone.now(),
        )

        payload = {
            "event_id": 1,
            "warehouse_id": 2,
            "phase": "BASELINE",
            "as_of_datetime": timezone.now().isoformat(),
            "planning_window_days": 3,
            "selected_method": "A",
            "selected_item_keys": ["9_2"],
        }
        items = [
            {
                "item_id": 9,
                "available_qty": 20,
                "inbound_strict_qty": 8,
                "burn_rate_per_hour": 2.5,
                "required_qty": 100,
                "gap_qty": 72,
                "time_to_stockout": 8,
                "severity": "WARNING",
                "horizon": {
                    "A": {"recommended_qty": 10},
                    "B": {"recommended_qty": 20},
                    "C": {"recommended_qty": 42},
                },
            }
        ]

        record = workflow_store_db.create_draft(
            payload,
            items,
            warnings=[],
            actor="tester",
        )

        older.refresh_from_db()
        self.assertEqual(older.status_code, "SUPERSEDED")
        self.assertEqual(str(older.superseded_by_id), str(record["needs_list_id"]))
        self.assertIn(str(older.needs_list_id), record.get("supersedes_needs_list_ids", []))
        older_record = workflow_store_db._needs_list_to_dict(older)
        self.assertEqual(
            older_record.get("supersede_reason"),
            "Replaced by newer draft calculation.",
        )

    @patch("replenishment.workflow_store_db.data_access.get_event_names")
    @patch("replenishment.workflow_store_db.data_access.get_warehouse_names")
    @patch("replenishment.workflow_store_db.data_access.get_item_names")
    def test_list_records_batches_name_and_item_lookups(
        self,
        mock_item_names,
        mock_warehouse_names,
        mock_event_names,
    ) -> None:
        mock_warehouse_names.return_value = ({2: "ODPEM MARCUS GARVEY WAREHOUSE (MG)"}, [])
        mock_event_names.return_value = ({1: "HURRICANE MELISSA"}, [])
        mock_item_names.return_value = (
            {
                9: {"name": "MEALS READY TO EAT", "code": "MRE-12"},
                17: {"name": "BOTTLED WATER", "code": "BW-01"},
            },
            [],
        )

        first = NeedsList.objects.create(
            needs_list_no="NL-1-2-20260216-001",
            event_id=1,
            warehouse_id=2,
            event_phase="BASELINE",
            calculation_dtime=timezone.now(),
            demand_window_hours=24,
            planning_window_hours=72,
            safety_factor=1.25,
            data_freshness_level="HIGH",
            status_code="PENDING_APPROVAL",
            total_gap_qty=100,
            create_by_id="tester",
            update_by_id="tester",
        )
        second = NeedsList.objects.create(
            needs_list_no="NL-1-2-20260216-002",
            event_id=1,
            warehouse_id=2,
            event_phase="BASELINE",
            calculation_dtime=timezone.now(),
            demand_window_hours=24,
            planning_window_hours=72,
            safety_factor=1.25,
            data_freshness_level="HIGH",
            status_code="PENDING_APPROVAL",
            total_gap_qty=50,
            create_by_id="tester",
            update_by_id="tester",
        )

        NeedsListItem.objects.create(
            needs_list=first,
            item_id=9,
            uom_code="EA",
            burn_rate=2.5,
            burn_rate_source="CALCULATED",
            available_stock=20,
            reserved_qty=0,
            inbound_transfer_qty=5,
            inbound_donation_qty=3,
            inbound_procurement_qty=0,
            required_qty=100,
            coverage_qty=28,
            gap_qty=72,
            time_to_stockout_hours=8,
            severity_level="WARNING",
            horizon_a_qty=10,
            horizon_b_qty=20,
            horizon_c_qty=42,
            create_by_id="tester",
            update_by_id="tester",
        )
        NeedsListItem.objects.create(
            needs_list=second,
            item_id=17,
            uom_code="EA",
            burn_rate=1.0,
            burn_rate_source="CALCULATED",
            available_stock=10,
            reserved_qty=0,
            inbound_transfer_qty=0,
            inbound_donation_qty=0,
            inbound_procurement_qty=0,
            required_qty=20,
            coverage_qty=10,
            gap_qty=10,
            time_to_stockout_hours=4,
            severity_level="CRITICAL",
            horizon_a_qty=5,
            horizon_b_qty=10,
            horizon_c_qty=5,
            create_by_id="tester",
            update_by_id="tester",
        )

        # list_records normalizes API-facing status aliases via _STATUS_ALIASES,
        # so querying SUBMITTED intentionally matches records stored as PENDING_APPROVAL.
        records = workflow_store_db.list_records(["SUBMITTED"])

        self.assertEqual(len(records), 2)
        mock_warehouse_names.assert_called_once_with([2])
        mock_event_names.assert_called_once_with([1])
        mock_item_names.assert_called_once_with([9, 17])


class StockStateFileLockTests(SimpleTestCase):
    # These are intentional white-box tests that assert internal lock helpers
    # around stock-state persistence/loading. Refactors of private helpers may
    # require updating this test class even if public API behavior is unchanged.
    def test_persist_snapshot_uses_exclusive_file_lock(self) -> None:
        from replenishment import views

        with TemporaryDirectory() as temp_dir:
            store_path = Path(temp_dir) / "stock_state_cache.json"
            with override_settings(NEEDS_STOCK_STATE_STORE_PATH=str(store_path)):
                with patch("replenishment.views._acquire_stock_state_file_lock") as mock_lock, patch(
                    "replenishment.views._release_stock_state_file_lock"
                ):
                    views._persist_stock_state_snapshot(
                        event_id=1,
                        warehouse_id=2,
                        phase="SURGE",
                        as_of_datetime=timezone.now().isoformat(),
                        items=[
                            {
                                "item_id": 9,
                                "burn_rate_per_hour": 1.5,
                                "gap_qty": 0.0,
                                "severity": "OK",
                            }
                        ],
                        warnings=[],
                    )

                self.assertTrue(store_path.exists())
                self.assertIn('"1:2:SURGE"', store_path.read_text(encoding="utf-8"))
                self.assertTrue(
                    any(call.kwargs.get("exclusive") is True for call in mock_lock.call_args_list)
                )

    def test_load_snapshot_uses_shared_file_lock(self) -> None:
        from replenishment import views

        with TemporaryDirectory() as temp_dir:
            store_path = Path(temp_dir) / "stock_state_cache.json"
            with override_settings(NEEDS_STOCK_STATE_STORE_PATH=str(store_path)):
                views._persist_stock_state_snapshot(
                    event_id=5,
                    warehouse_id=10,
                    phase="BASELINE",
                    as_of_datetime=timezone.now().isoformat(),
                    items=[
                        {
                            "item_id": 1,
                            "burn_rate_per_hour": 2.0,
                            "gap_qty": 1.0,
                            "severity": "WARNING",
                        }
                    ],
                    warnings=["burn_data_missing"],
                )

                with patch("replenishment.views._acquire_stock_state_file_lock") as mock_lock, patch(
                    "replenishment.views._release_stock_state_file_lock"
                ):
                    snapshot = views._load_stock_state_snapshot(5, 10, "BASELINE")

                self.assertIsNotNone(snapshot)
                self.assertEqual(snapshot.get("restored_from_needs_list_id"), "stock_state_cache")
                self.assertTrue(
                    any(call.kwargs.get("exclusive") is False for call in mock_lock.call_args_list)
                )
