import os
import shutil
import uuid
from pathlib import Path
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.db import DatabaseError, connection, transaction
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient, APIRequestFactory, force_authenticate

from api.models import AsyncJob
from api.rbac import (
    PERM_CRITICALITY_HAZARD_APPROVE,
    PERM_CRITICALITY_HAZARD_MANAGE,
    PERM_CRITICALITY_OVERRIDE_MANAGE,
    PERM_EVENT_PHASE_WINDOW_MANAGE,
)
from api.tenancy import TenantContext, TenantMembership
from replenishment import apps as replenishment_apps, phase_window_views, rules, views, workflow_store_db
try:
    from replenishment import workflow_store
except ImportError:  # pragma: no cover - test fallback for repos without the legacy file store module.
    workflow_store = workflow_store_db
from replenishment.models import (
    NeedsList,
    NeedsListAudit,
    NeedsListItem,
    Procurement,
    ProcurementItem,
)
from replenishment.services import (
    approval as approval_service,
    criticality as criticality_service,
    data_access,
    needs_list,
    phase_window_policy,
    procurement as procurement_service,
)
from replenishment.services.needs_list import (
    allocate_horizons,
    compute_confidence_and_warnings,
    compute_gap,
    compute_inbound_strict,
    compute_time_to_stockout_hours,
)


class RepackagingDetailScopeTests(SimpleTestCase):
    def setUp(self) -> None:
        self.factory = APIRequestFactory()
        self.user = SimpleNamespace(is_authenticated=True, user_id="planner", roles=[])

    @patch("replenishment.views._require_warehouse_scope", return_value=object())
    @patch(
        "replenishment.views.repackaging_service.get_repackaging_transaction",
        return_value=({"repackaging_id": 7, "warehouse_id": 2}, []),
    )
    @patch("api.permissions.resolve_roles_and_permissions", return_value=([], [views.PERM_MASTERDATA_VIEW]))
    def test_detail_returns_404_when_record_is_out_of_scope(
        self,
        _mock_roles,
        _mock_get_detail,
        _mock_scope,
    ) -> None:
        request = self.factory.get("/api/v1/replenishment/repackaging/7/")
        force_authenticate(request, user=self.user)

        response = views.inventory_repackaging_detail(request, 7)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data["detail"], "Not found.")


class ReplenishmentRequestIpTests(SimpleTestCase):
    def setUp(self) -> None:
        self.factory = APIRequestFactory()

    def test_request_client_ip_ignores_untrusted_forwarded_for_headers(self) -> None:
        request = self.factory.get(
            "/api/v1/replenishment/needs-list/NL-A/donations/export",
            REMOTE_ADDR="10.0.0.25",
            HTTP_X_FORWARDED_FOR="198.51.100.77, 203.0.113.9",
        )

        self.assertEqual(views._request_client_ip(request), "10.0.0.25")

    @override_settings(TRUSTED_PROXIES={"10.0.0.25", "203.0.113.9"})
    def test_request_client_ip_uses_first_untrusted_forwarded_for_when_peer_is_trusted(
        self,
    ) -> None:
        request = self.factory.get(
            "/api/v1/replenishment/needs-list/NL-A/donations/export",
            REMOTE_ADDR="10.0.0.25",
            HTTP_X_FORWARDED_FOR="198.51.100.77, 203.0.113.9",
        )

        self.assertEqual(views._request_client_ip(request), "198.51.100.77")


class ReplenishmentBootstrapTests(SimpleTestCase):
    @patch("replenishment.workflow_store_db._ensure_workflow_metadata_table")
    def test_bootstrap_workflow_metadata_table_uses_migrated_db_alias(
        self,
        mock_ensure_workflow_metadata_table,
    ) -> None:
        app_config = SimpleNamespace(name="replenishment")

        replenishment_apps._bootstrap_workflow_metadata_table(
            app_config=app_config,
            using="analytics",
        )

        mock_ensure_workflow_metadata_table.assert_called_once_with(using="analytics")




def _ensure_legacy_reference_rows() -> None:
    if connection.vendor != "postgresql":
        return

    statements = [
        (
            """
            INSERT INTO parish (parish_code, parish_name)
            VALUES (%s, %s)
            ON CONFLICT (parish_code) DO NOTHING
            """,
            ["01", "KINGSTON"],
        ),
        (
            """
            INSERT INTO ref_tenant_type (
                tenant_type_code,
                tenant_type_name,
                status_code,
                create_by_id,
                create_dtime,
                update_by_id,
                update_dtime,
                version_nbr
            )
            VALUES (%s, %s, 'A', 'SYSTEM', NOW(), 'SYSTEM', NOW(), 1)
            ON CONFLICT (tenant_type_code) DO NOTHING
            """,
            ["PARISH", "PARISH"],
        ),
        (
            """
            INSERT INTO ref_event_phase (
                phase_code,
                phase_name,
                sort_order,
                description,
                status_code,
                create_by_id,
                create_dtime,
                update_by_id,
                update_dtime,
                version_nbr
            )
            VALUES (%s, %s, %s, %s, 'A', 'SYSTEM', NOW(), 'SYSTEM', NOW(), 1)
            ON CONFLICT (phase_code) DO NOTHING
            """,
            ["BASELINE", "Baseline", 4, "Baseline phase"],
        ),
        (
            """
            INSERT INTO tenant (
                tenant_id,
                tenant_code,
                tenant_name,
                tenant_type,
                parish_code,
                data_scope,
                pii_access,
                mobile_priority,
                offline_required,
                status_code,
                create_by_id,
                create_dtime,
                update_by_id,
                update_dtime,
                version_nbr
            )
            VALUES (
                1,
                'TEST_TENANT_1',
                'TEST TENANT 1',
                'PARISH',
                '01',
                'OWN_DATA',
                'NONE',
                'LOW',
                FALSE,
                'A',
                'SYSTEM',
                NOW(),
                'SYSTEM',
                NOW(),
                1
            )
            ON CONFLICT (tenant_id) DO NOTHING
            """,
            [],
        ),
        (
            """
            INSERT INTO custodian (
                custodian_id,
                custodian_name,
                address1_text,
                parish_code,
                contact_name,
                phone_no,
                create_by_id,
                create_dtime,
                update_by_id,
                update_dtime,
                version_nbr,
                tenant_id
            )
            VALUES (
                1,
                'TEST CUSTODIAN 1',
                '1 TEST STREET',
                '01',
                'TEST CONTACT',
                '5550001',
                'SYSTEM',
                NOW(),
                'SYSTEM',
                NOW(),
                1,
                1
            )
            ON CONFLICT (custodian_id) DO NOTHING
            """,
            [],
        ),
        (
            """
            INSERT INTO warehouse (
                warehouse_id,
                warehouse_name,
                warehouse_type,
                address1_text,
                address2_text,
                parish_code,
                contact_name,
                phone_no,
                email_text,
                custodian_id,
                status_code,
                reason_desc,
                create_by_id,
                create_dtime,
                update_by_id,
                update_dtime,
                version_nbr,
                min_stock_threshold,
                last_sync_dtime,
                sync_status,
                tenant_id
            )
            VALUES (
                %s,
                %s,
                'MAIN-HUB',
                '1 TEST STREET',
                NULL,
                '01',
                'TEST MANAGER',
                '5550101',
                NULL,
                1,
                'A',
                NULL,
                'SYSTEM',
                NOW(),
                'SYSTEM',
                NOW(),
                1,
                0.00,
                NULL,
                'UNKNOWN',
                1
            )
            ON CONFLICT (warehouse_id) DO NOTHING
            """,
            [1, "TEST WAREHOUSE 1"],
        ),
        (
            """
            INSERT INTO warehouse (
                warehouse_id,
                warehouse_name,
                warehouse_type,
                address1_text,
                address2_text,
                parish_code,
                contact_name,
                phone_no,
                email_text,
                custodian_id,
                status_code,
                reason_desc,
                create_by_id,
                create_dtime,
                update_by_id,
                update_dtime,
                version_nbr,
                min_stock_threshold,
                last_sync_dtime,
                sync_status,
                tenant_id
            )
            VALUES (
                %s,
                %s,
                'MAIN-HUB',
                '2 TEST STREET',
                NULL,
                '01',
                'TEST MANAGER',
                '5550102',
                NULL,
                1,
                'A',
                NULL,
                'SYSTEM',
                NOW(),
                'SYSTEM',
                NOW(),
                1,
                0.00,
                NULL,
                'UNKNOWN',
                1
            )
            ON CONFLICT (warehouse_id) DO NOTHING
            """,
            [2, "TEST WAREHOUSE 2"],
        ),
        (
            """
            INSERT INTO warehouse (
                warehouse_id,
                warehouse_name,
                warehouse_type,
                address1_text,
                address2_text,
                parish_code,
                contact_name,
                phone_no,
                email_text,
                custodian_id,
                status_code,
                reason_desc,
                create_by_id,
                create_dtime,
                update_by_id,
                update_dtime,
                version_nbr,
                min_stock_threshold,
                last_sync_dtime,
                sync_status,
                tenant_id
            )
            VALUES (
                %s,
                %s,
                'MAIN-HUB',
                '10 TEST STREET',
                NULL,
                '01',
                'TEST MANAGER',
                '5550110',
                NULL,
                1,
                'A',
                NULL,
                'SYSTEM',
                NOW(),
                'SYSTEM',
                NOW(),
                1,
                0.00,
                NULL,
                'UNKNOWN',
                1
            )
            ON CONFLICT (warehouse_id) DO NOTHING
            """,
            [10, "TEST WAREHOUSE 10"],
        ),
        (
            """
            INSERT INTO event (
                event_id,
                event_type,
                start_date,
                event_name,
                event_desc,
                impact_desc,
                status_code,
                closed_date,
                reason_desc,
                create_by_id,
                create_dtime,
                update_by_id,
                update_dtime,
                version_nbr,
                current_phase,
                phase_changed_at,
                phase_changed_by
            )
            VALUES (
                %s,
                'HURRICANE',
                CURRENT_DATE,
                %s,
                'TEST EVENT',
                'TEST IMPACT',
                'A',
                NULL,
                NULL,
                'SYSTEM',
                NOW(),
                'SYSTEM',
                NOW(),
                1,
                'BASELINE',
                NULL,
                NULL
            )
            ON CONFLICT (event_id) DO NOTHING
            """,
            [1, "TEST EVENT 1"],
        ),
        (
            """
            INSERT INTO event (
                event_id,
                event_type,
                start_date,
                event_name,
                event_desc,
                impact_desc,
                status_code,
                closed_date,
                reason_desc,
                create_by_id,
                create_dtime,
                update_by_id,
                update_dtime,
                version_nbr,
                current_phase,
                phase_changed_at,
                phase_changed_by
            )
            VALUES (
                %s,
                'HURRICANE',
                CURRENT_DATE,
                %s,
                'TEST EVENT',
                'TEST IMPACT',
                'A',
                NULL,
                NULL,
                'SYSTEM',
                NOW(),
                'SYSTEM',
                NOW(),
                1,
                'BASELINE',
                NULL,
                NULL
            )
            ON CONFLICT (event_id) DO NOTHING
            """,
            [5, "TEST EVENT 5"],
        ),
    ]

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM needs_list_audit")
            cursor.execute("DELETE FROM needs_list_item")
            cursor.execute("DELETE FROM needs_list_workflow_metadata")
            cursor.execute("DELETE FROM needs_list")
            for statement, params in statements:
                cursor.execute(statement, params)


def setUpModule() -> None:
    _ensure_legacy_reference_rows()

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
            freshness_level="HIGH",
        )
        level_present, _, _ = compute_confidence_and_warnings(
            burn_source="reliefpkg",
            warnings=[],
            procurement_available=True,
            mapping_best_effort=False,
            freshness_level="HIGH",
        )
        self.assertEqual(level_missing, "LOW")
        self.assertEqual(level_present, "HIGH")

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
            horizon_c_hours=336,
            burn_source="none",
            as_of_dt=as_of_dt,
            phase="BASELINE",
            inventory_as_of=inventory_as_of,
            base_warnings=["burn_data_missing"],
        )
        item_one = items[0]
        self.assertEqual(item_one["confidence"]["level"], "LOW")
        self.assertEqual(item_one["freshness"]["state"], "LOW")
        self.assertIn("burn_rate_estimated", item_one["warnings"])
        self.assertEqual(fallback_counts["category_avg"], 2)

    def test_freshness_unknown_without_timestamp(self) -> None:
        state, warnings, _ = needs_list.compute_freshness_state(
            "BASELINE", None, timezone.now()
        )
        self.assertEqual(state, "LOW")
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
            horizon_c_hours=336,
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
            horizon_c_hours=336,
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
            horizon_c_hours=336,
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
            horizon_c_hours=336,
            burn_source="reliefpkg",
            as_of_dt=as_of_dt,
            phase="SURGE",
            inventory_as_of=inventory_as_of,
            base_warnings=[],
            effective_criticality_by_item={
                1: {
                    "effective_criticality_level": "CRITICAL",
                    "effective_criticality_source": "EVENT_OVERRIDE",
                }
            },
        )
        triggers = items[0]["triggers"]
        self.assertTrue(triggers["activate_all"])
        self.assertTrue(triggers["activate_B"])
        self.assertTrue(triggers["activate_C"])
        self.assertEqual(items[0]["effective_criticality_level"], "CRITICAL")
        self.assertEqual(items[0]["effective_criticality_source"], "EVENT_OVERRIDE")

    def test_surge_critical_category_activates_all(self) -> None:
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
            horizon_c_hours=336,
            burn_source="reliefpkg",
            as_of_dt=as_of_dt,
            phase="SURGE",
            inventory_as_of=inventory_as_of,
            base_warnings=[],
            effective_criticality_by_item={
                1: {
                    "effective_criticality_level": "HIGH",
                    "effective_criticality_source": "HAZARD_TYPE_DEFAULT",
                }
            },
        )
        triggers = items[0]["triggers"]
        self.assertTrue(triggers["activate_all"])
        self.assertTrue(triggers["activate_B"])
        self.assertTrue(triggers["activate_C"])
        self.assertEqual(items[0]["effective_criticality_level"], "HIGH")
        self.assertEqual(items[0]["effective_criticality_source"], "HAZARD_TYPE_DEFAULT")

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
            horizon_c_hours=336,
            burn_source="reliefpkg",
            as_of_dt=as_of_dt,
            phase="SURGE",
            inventory_as_of=inventory_as_of,
            base_warnings=[],
        )
        self.assertEqual(items[0]["effective_criticality_level"], "NORMAL")
        self.assertEqual(items[0]["effective_criticality_source"], "ITEM_DEFAULT")

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
            horizon_c_hours=336,
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
            horizon_c_hours=336,
            burn_source="reliefpkg",
            as_of_dt=as_of_dt,
            phase="BASELINE",
            inventory_as_of=inventory_as_of,
            base_warnings=[],
        )
        item = items[0]
        self.assertEqual(item["burn_rate_per_hour"], 1.5)
        self.assertIn("burn_rate_estimated", item["warnings"])
        self.assertEqual(item["confidence"]["level"], "LOW")
        self.assertEqual(item["freshness"]["state"], "LOW")
        self.assertNotIn("burn_no_rows_in_window", item["warnings"])

    def test_burn_category_fallback_low_confidence_inventory_missing(self) -> None:
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
            horizon_c_hours=336,
            burn_source="reliefpkg",
            as_of_dt=as_of_dt,
            phase="BASELINE",
            inventory_as_of=None,
            base_warnings=[],
        )
        item = items[0]
        self.assertEqual(item["burn_rate_per_hour"], 1.5)
        self.assertIn("burn_rate_estimated", item["warnings"])
        self.assertIn("inventory_timestamp_unavailable", item["warnings"])
        self.assertEqual(item["confidence"]["level"], "LOW")
        self.assertEqual(item["freshness"]["state"], "LOW")

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

    def test_determine_approval_tier_donation_not_procurement_conservative(self) -> None:
        approval, warnings, rationale = approval_service.determine_approval_tier(
            phase="BASELINE",
            total_cost=None,
            cost_missing=True,
            selected_method="B",
        )
        self.assertEqual(approval["tier"], "Below Tier 1")
        self.assertEqual(approval["approver_role"], "Senior Director (Andrea)")
        self.assertEqual(warnings, [])
        self.assertIn("Donation workflow selected", rationale)

    def test_determine_approval_tier_maps_transfer_alias(self) -> None:
        approval, warnings, rationale = approval_service.determine_approval_tier(
            phase="BASELINE",
            total_cost=None,
            cost_missing=True,
            selected_method="TRANSFER",
        )
        self.assertEqual(approval["tier"], "Below Tier 1")
        self.assertEqual(approval["approver_role"], "Logistics Manager (Kemar)")
        self.assertEqual(warnings, [])
        self.assertIn("Transfer workflow selected", rationale)
    def test_default_windows_match_backlog_v3_2(self) -> None:
        self.assertEqual(
            rules.get_phase_windows("SURGE"),
            {"demand_hours": 6, "planning_hours": 24},
        )
        self.assertEqual(
            rules.get_phase_windows("STABILIZED"),
            {"demand_hours": 72, "planning_hours": 72},
        )
        self.assertEqual(
            rules.get_phase_windows("BASELINE"),
            {"demand_hours": 720, "planning_hours": 168},
        )

    def test_phase_windows_ignore_deprecated_env_version_override(self) -> None:
        with patch.dict(os.environ, {"NEEDS_WINDOWS_VERSION": "v40"}):
            self.assertEqual(
                rules.get_phase_windows("SURGE"),
                {"demand_hours": 6, "planning_hours": 24},
            )

    def test_default_horizon_lead_times_match_backlog(self) -> None:
        self.assertEqual(
            rules.get_default_horizon_lead_times(),
            {"A": 8, "B": 72, "C": 336},
        )

    def test_freshness_thresholds_matrix(self) -> None:
        self.assertEqual(
            rules.FRESHNESS_THRESHOLDS,
            {
                "SURGE": {"fresh_max_hours": 2, "warn_max_hours": 4},
                "STABILIZED": {"fresh_max_hours": 6, "warn_max_hours": 12},
                "BASELINE": {"fresh_max_hours": 24, "warn_max_hours": 48},
            },
        )

    def test_strict_inbound_mapping_moves_to_db_governed_paths(self) -> None:
        self.assertFalse(hasattr(rules, "resolve_strict_inbound_donation_codes"))
        self.assertFalse(hasattr(rules, "resolve_strict_inbound_transfer_codes"))

    def test_normalize_horizon_key_accepts_method_aliases(self) -> None:
        self.assertEqual(views._normalize_horizon_key("TRANSFER"), "A")
        self.assertEqual(views._normalize_horizon_key("donation"), "B")
        self.assertEqual(views._normalize_horizon_key("Procurement"), "C")

    def test_submission_status_requires_actor_scope_includes_returned(self) -> None:
        self.assertTrue(views._submission_status_requires_actor_scope("RETURNED"))

    def test_record_owned_by_actor_uses_created_by(self) -> None:
        record = {
            "created_by": "owner-user",
            "submitted_by": "owner-user",
            "updated_by": "reviewer-user",
        }
        self.assertTrue(views._record_owned_by_actor(record, "owner-user"))
        self.assertFalse(views._record_owned_by_actor(record, "reviewer-user"))

    def test_record_owned_by_actor_db_uses_created_by(self) -> None:
        needs_list = NeedsList(
            create_by_id="owner-user",
            submitted_by="submitter-user",
            update_by_id="reviewer-user",
        )
        self.assertTrue(workflow_store_db._record_owned_by_actor(needs_list, "owner-user"))
        self.assertFalse(workflow_store_db._record_owned_by_actor(needs_list, "submitter-user"))
        self.assertFalse(workflow_store_db._record_owned_by_actor(needs_list, "reviewer-user"))

    def test_duplicate_conflicts_match_item_and_warehouse_pairs(self) -> None:
        current_record = {
            "needs_list_id": "CUR-1",
            "warehouse_id": 1,
            "warehouse_ids": [1, 2],
            "snapshot": {
                "items": [
                    {"item_id": 10, "warehouse_id": 1, "required_qty": 5},
                ]
            },
        }
        existing_diff_warehouse = {
            "needs_list_id": "EX-DIFF",
            "needs_list_no": "NL-EX-DIFF",
            "status": "APPROVED",
            "warehouse_id": 2,
            "warehouse_ids": [2],
            "warehouses": [{"warehouse_name": "Warehouse 2"}],
            "snapshot": {
                "items": [
                    {"item_id": 10, "warehouse_id": 2, "required_qty": 5},
                ]
            },
        }
        existing_same_pair = {
            "needs_list_id": "EX-SAME",
            "needs_list_no": "NL-EX-SAME",
            "status": "APPROVED",
            "warehouse_id": 1,
            "warehouse_ids": [1],
            "warehouses": [{"warehouse_name": "Warehouse 1"}],
            "snapshot": {
                "items": [
                    {"item_id": 10, "warehouse_id": 1, "required_qty": 5},
                ]
            },
        }

        with patch.object(
            views.workflow_store,
            "list_records",
            return_value=[existing_diff_warehouse, existing_same_pair],
        ), patch.object(
            views.workflow_store,
            "apply_overrides",
            side_effect=lambda rec: rec.get("snapshot") or {},
        ):
            conflicts = views._find_submitted_or_approved_overlap_conflicts(current_record)

        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].get("needs_list_id"), "EX-SAME")
        self.assertEqual(conflicts[0].get("overlap_item_ids"), [10])

    def test_duplicate_conflicts_fall_back_to_item_warehouse_scope(self) -> None:
        current_record = {
            "needs_list_id": "CUR-NO-WAREHOUSE",
            "warehouse_id": None,
            "warehouse_ids": [],
            "snapshot": {
                "items": [
                    {"item_id": 10, "warehouse_id": 1, "required_qty": 5},
                ]
            },
        }
        existing_diff_warehouse = {
            "needs_list_id": "EX-NO-WAREHOUSE-DIFF",
            "needs_list_no": "NL-EX-NO-WAREHOUSE-DIFF",
            "status": "APPROVED",
            "warehouse_id": None,
            "warehouse_ids": [],
            "warehouses": [{"warehouse_name": "Warehouse 2"}],
            "snapshot": {
                "items": [
                    {"item_id": 10, "warehouse_id": 2, "required_qty": 5},
                ]
            },
        }
        existing_same_warehouse = {
            "needs_list_id": "EX-NO-WAREHOUSE-SAME",
            "needs_list_no": "NL-EX-NO-WAREHOUSE-SAME",
            "status": "APPROVED",
            "warehouse_id": None,
            "warehouse_ids": [],
            "warehouses": [{"warehouse_name": "Warehouse 1"}],
            "snapshot": {
                "items": [
                    {"item_id": 10, "warehouse_id": 1, "required_qty": 5},
                ]
            },
        }

        with patch.object(
            views.workflow_store,
            "list_records",
            return_value=[existing_diff_warehouse, existing_same_warehouse],
        ), patch.object(
            views.workflow_store,
            "apply_overrides",
            side_effect=lambda rec: rec.get("snapshot") or {},
        ):
            conflicts = views._find_submitted_or_approved_overlap_conflicts(current_record)

        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].get("needs_list_id"), "EX-NO-WAREHOUSE-SAME")
        self.assertEqual(conflicts[0].get("overlap_item_ids"), [10])


class GlobalPhaseWindowPolicyTests(SimpleTestCase):
    @override_settings(
        NATIONAL_PHASE_WINDOW_ADMIN_CODES=[
            "ODPEM-NEOC",
            "OFFICE-OF-DISASTER-P",
            "ODPEM-LOGISTICS",
        ]
    )
    def test_authority_codes_filter_stale_or_non_odpem_overrides(self) -> None:
        self.assertEqual(
            phase_window_policy._configured_admin_codes(),
            ["OFFICE_OF_DISASTER_P"],
        )

    def test_hour_validation_rejects_float_truncation(self) -> None:
        self.assertEqual(
            phase_window_policy._coerce_positive_hours(" 6 ", "demand_hours"),
            6,
        )
        self.assertEqual(
            phase_window_policy._coerce_positive_hours(6, "demand_hours"),
            6,
        )

        for bad_value in (True, False, 6.1, "6.1", "+6", "six", ""):
            with self.subTest(value=bad_value):
                with self.assertRaises(phase_window_policy.PhaseWindowPolicyError):
                    phase_window_policy._coerce_positive_hours(
                        bad_value,
                        "demand_hours",
                    )

    def test_expire_active_global_phase_window_configs_targets_full_active_scope(self) -> None:
        cursor = MagicMock()
        now = timezone.now()
        today = timezone.localdate()

        phase_window_policy._expire_active_global_phase_window_configs(
            cursor,
            tenant_id=27,
            config_key="replenishment.phase_window.surge",
            actor_ref="phase-admin",
            now=now,
            today=today,
        )

        sql, params = cursor.execute.call_args.args
        self.assertIn("tenant_id = %s", sql)
        self.assertIn("config_key = %s", sql)
        self.assertIn("effective_date <= %s", sql)
        self.assertIn("expiry_date IS NULL", sql)
        self.assertNotIn("config_id =", sql.lower())
        self.assertEqual(
            params,
            [
                today,
                "phase-admin",
                now,
                27,
                "replenishment.phase_window.surge",
                today,
                today,
            ],
        )

    def test_effective_phase_windows_fall_back_to_backlog_default(self) -> None:
        with patch(
            "replenishment.services.phase_window_policy._resolve_authoritative_phase_window_tenant",
            return_value={"tenant_id": 27, "tenant_code": "OFFICE-OF-DISASTER-P", "tenant_name": "ODPEM"},
        ), patch(
            "replenishment.services.phase_window_policy._fetch_effective_global_phase_window_config",
            return_value=None,
        ):
            windows = phase_window_policy.get_effective_phase_windows(14, "SURGE")

        self.assertEqual(windows["event_id"], 14)
        self.assertEqual(windows["scope"], "global")
        self.assertTrue(windows["applies_globally"])
        self.assertEqual(windows["source"], "backlog_default")
        self.assertEqual(windows["demand_hours"], 6)
        self.assertEqual(windows["planning_hours"], 24)

    def test_effective_phase_windows_prefer_global_tenant_config(self) -> None:
        record = phase_window_policy.GlobalPhaseWindowConfigRecord(
            config_id=91,
            tenant_id=27,
            tenant_code="OFFICE-OF-DISASTER-P",
            tenant_name="ODPEM",
            effective_date="2026-04-18",
            update_dtime="2026-04-18T12:00:00Z",
            value={
                "phase": "SURGE",
                "demand_hours": 12,
                "planning_hours": 36,
                "justification": "Backlog-authorized hurricane recalibration",
                "audit": {
                    "prior_values": {"demand_hours": 6, "planning_hours": 24},
                    "new_values": {"demand_hours": 12, "planning_hours": 36},
                },
            },
        )
        with patch(
            "replenishment.services.phase_window_policy._resolve_authoritative_phase_window_tenant",
            return_value={"tenant_id": 27, "tenant_code": "OFFICE-OF-DISASTER-P", "tenant_name": "ODPEM"},
        ), patch(
            "replenishment.services.phase_window_policy._fetch_effective_global_phase_window_config",
            return_value=record,
        ):
            windows = phase_window_policy.get_effective_phase_windows(99, "SURGE")

        self.assertEqual(windows["source"], "tenant_config_global")
        self.assertEqual(windows["demand_hours"], 12)
        self.assertEqual(windows["planning_hours"], 36)
        self.assertEqual(
            windows["audit"]["prior_values"],
            {"demand_hours": 6, "planning_hours": 24},
        )
        self.assertEqual(
            windows["audit"]["new_values"],
            {"demand_hours": 12, "planning_hours": 36},
        )

    def test_set_global_phase_windows_rejects_unchanged_default_values_without_existing_row(self) -> None:
        cursor = MagicMock()
        with patch(
            "replenishment.services.phase_window_policy._tenant_row_by_id",
            return_value={"tenant_id": 27, "tenant_code": "OFFICE-OF-DISASTER-P", "tenant_name": "ODPEM"},
        ), patch(
            "replenishment.services.phase_window_policy._is_authoritative_phase_window_tenant",
            return_value=True,
        ), patch(
            "replenishment.services.phase_window_policy._fetch_effective_global_phase_window_config",
            return_value=None,
        ), patch(
            "replenishment.services.phase_window_policy.connection.cursor",
        ) as cursor_mock:
            cursor_mock.return_value.__enter__.return_value = cursor
            with self.assertRaises(phase_window_policy.PhaseWindowPolicyError) as raised:
                phase_window_policy.set_global_phase_windows(
                    phase="SURGE",
                    demand_hours=6,
                    planning_hours=24,
                    justification="Align to Product Backlog v3.2",
                    actor="phase-admin",
                    tenant_id=27,
                )

        self.assertEqual(str(raised.exception), "No phase-window change detected.")

    def test_set_global_phase_windows_persists_uppercase_json_config_type(self) -> None:
        cursor = MagicMock()
        existing = phase_window_policy.GlobalPhaseWindowConfigRecord(
            config_id=91,
            tenant_id=27,
            tenant_code="OFFICE-OF-DISASTER-P",
            tenant_name="ODPEM",
            effective_date="2026-04-18",
            update_dtime="2026-04-18T12:00:00Z",
            value={"phase": "SURGE", "demand_hours": 6, "planning_hours": 24},
        )
        with patch(
            "replenishment.services.phase_window_policy._tenant_row_by_id",
            return_value={"tenant_id": 27, "tenant_code": "OFFICE-OF-DISASTER-P", "tenant_name": "ODPEM"},
        ), patch(
            "replenishment.services.phase_window_policy._is_authoritative_phase_window_tenant",
            return_value=True,
        ), patch(
            "replenishment.services.phase_window_policy._fetch_effective_global_phase_window_config",
            return_value=existing,
        ), patch(
            "replenishment.services.phase_window_policy.get_effective_phase_windows",
            return_value={"phase": "SURGE", "scope": "global"},
        ), patch(
            "replenishment.services.phase_window_policy.connection.cursor",
        ) as cursor_mock:
            cursor_mock.return_value.__enter__.return_value = cursor

            phase_window_policy.set_global_phase_windows(
                phase="SURGE",
                demand_hours=12,
                planning_hours=36,
                justification="Align to Product Backlog v3.2",
                actor="phase-admin",
                tenant_id=27,
            )

        insert_params = cursor.execute.call_args_list[-1].args[1]
        self.assertEqual(insert_params[3], "JSON")


@override_settings(AUTH_ENABLED=False, DEV_AUTH_ENABLED=True, TEST_DEV_AUTH_ENABLED=True)
class GlobalPhaseWindowViewTests(SimpleTestCase):
    def setUp(self) -> None:
        self.factory = APIRequestFactory()
        self.national_context = TenantContext(
            requested_tenant_id=27,
            active_tenant_id=27,
            active_tenant_code="OFFICE-OF-DISASTER-P",
            active_tenant_type="NATIONAL",
            memberships=(
                TenantMembership(
                    tenant_id=27,
                    tenant_code="OFFICE-OF-DISASTER-P",
                    tenant_name="ODPEM National",
                    tenant_type="NATIONAL",
                    is_primary=True,
                    access_level="admin",
                ),
            ),
            can_read_all_tenants=False,
            can_act_cross_tenant=False,
        )

    def _request(self, payload: dict[str, object]):
        request = self.factory.put(
            "/api/v1/replenishment/events/14/phase-windows/SURGE",
            payload,
            format="json",
        )
        user = SimpleNamespace(
            is_authenticated=True,
            user_id="phase-admin",
            username="phase-admin",
        )
        force_authenticate(request, user=user)
        return request

    @patch(
        "api.permissions.resolve_roles_and_permissions",
        return_value=([], [PERM_EVENT_PHASE_WINDOW_MANAGE]),
    )
    @patch(
        "replenishment.phase_window_views.resolve_roles_and_permissions",
        return_value=([], [PERM_EVENT_PHASE_WINDOW_MANAGE]),
    )
    @patch("replenishment.phase_window_views._tenant_context")
    @patch("replenishment.phase_window_views.phase_window_policy.set_global_phase_windows")
    def test_put_requires_justification(
        self,
        mock_set_windows,
        mock_tenant_context,
        _mock_phase_view_roles,
        _mock_permission_roles,
    ) -> None:
        mock_tenant_context.return_value = self.national_context

        response = phase_window_views.event_phase_window_detail(
            self._request({"demand_hours": 6, "planning_hours": 24}),
            14,
            "SURGE",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("payload", response.data["errors"])
        mock_set_windows.assert_not_called()

    @patch(
        "api.permissions.resolve_roles_and_permissions",
        return_value=([], [PERM_EVENT_PHASE_WINDOW_MANAGE]),
    )
    @patch(
        "replenishment.phase_window_views.resolve_roles_and_permissions",
        return_value=([], [PERM_EVENT_PHASE_WINDOW_MANAGE]),
    )
    @patch("replenishment.phase_window_views._tenant_context")
    @patch("replenishment.phase_window_views.phase_window_policy.set_global_phase_windows")
    def test_put_rejects_cross_tenant_scope_even_with_manage_permission(
        self,
        mock_set_windows,
        mock_tenant_context,
        _mock_phase_view_roles,
        _mock_permission_roles,
    ) -> None:
        mock_tenant_context.return_value = TenantContext(
            requested_tenant_id=28,
            active_tenant_id=28,
            active_tenant_code="ODPEM-LOGISTICS",
            active_tenant_type="NATIONAL",
            memberships=(
                TenantMembership(
                    tenant_id=28,
                    tenant_code="ODPEM-LOGISTICS",
                    tenant_name="ODPEM Logistics",
                    tenant_type="NATIONAL",
                    is_primary=True,
                    access_level="admin",
                ),
            ),
            can_read_all_tenants=False,
            can_act_cross_tenant=False,
        )

        response = phase_window_views.event_phase_window_detail(
            self._request(
                {
                    "demand_hours": 6,
                    "planning_hours": 24,
                    "justification": "Align to Product Backlog v3.2",
                }
            ),
            14,
            "SURGE",
        )

        self.assertEqual(response.status_code, 403)
        self.assertIn("tenant_scope", response.data["errors"])
        mock_set_windows.assert_not_called()

    @patch(
        "api.permissions.resolve_roles_and_permissions",
        return_value=([], [PERM_EVENT_PHASE_WINDOW_MANAGE]),
    )
    @patch(
        "replenishment.phase_window_views.resolve_roles_and_permissions",
        return_value=([], [PERM_EVENT_PHASE_WINDOW_MANAGE]),
    )
    @patch("replenishment.phase_window_views._tenant_context")
    @patch("replenishment.phase_window_views.phase_window_policy.set_global_phase_windows")
    def test_put_persists_global_windows_with_justification(
        self,
        mock_set_windows,
        mock_tenant_context,
        _mock_phase_view_roles,
        _mock_permission_roles,
    ) -> None:
        mock_tenant_context.return_value = self.national_context
        mock_set_windows.return_value = {
            "phase": "SURGE",
            "scope": "global",
            "applies_globally": True,
            "demand_hours": 6,
            "planning_hours": 24,
            "source": "tenant_config_global",
            "config_id": 91,
        }

        response = phase_window_views.event_phase_window_detail(
            self._request(
                {
                    "demand_hours": 6,
                    "planning_hours": 24,
                    "justification": "Align to Product Backlog v3.2",
                }
            ),
            14,
            "SURGE",
        )

        self.assertEqual(response.status_code, 200)
        mock_set_windows.assert_called_once_with(
            phase="SURGE",
            demand_hours=6,
            planning_hours=24,
            justification="Align to Product Backlog v3.2",
            actor="phase-admin",
            tenant_id=27,
        )
        self.assertEqual(response.data["windows"]["scope"], "global")
        self.assertTrue(response.data["windows"]["applies_globally"])


class CriticalityResolverTests(SimpleTestCase):
    def test_missing_tables_no_longer_emit_table_missing_warnings(self) -> None:
        as_of_dt = timezone.now()
        with patch("replenishment.services.criticality._is_sqlite", return_value=False), patch(
            "replenishment.services.criticality._table_exists",
            return_value=False,
        ):
            hazard_defaults, hazard_warnings = criticality_service._load_hazard_defaults(
                "public",
                "HURRICANE",
                [1],
                as_of_dt,
            )
            event_overrides, override_warnings = criticality_service._load_event_overrides(
                "public",
                1,
                [1],
                as_of_dt,
            )

        self.assertEqual(hazard_defaults, {})
        self.assertEqual(event_overrides, {})
        self.assertEqual(hazard_warnings, [])
        self.assertEqual(override_warnings, [])

    def test_hazard_default_lookup_filters_to_approved_rows_when_supported(self) -> None:
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [(1, "HIGH")]
        mock_context = MagicMock()
        mock_context.__enter__.return_value = mock_cursor
        mock_context.__exit__.return_value = False
        mock_connection = MagicMock()
        mock_connection.cursor.return_value = mock_context

        with patch("replenishment.services.criticality._is_sqlite", return_value=False), patch(
            "replenishment.services.criticality._table_exists",
            return_value=True,
        ), patch(
            "replenishment.services.criticality._table_columns",
            return_value={
                "item_id",
                "criticality_level",
                "event_type",
                "is_active",
                "status_code",
                "approval_status",
                "effective_from",
                "effective_to",
                "update_dtime",
                "hazard_item_criticality_id",
            },
        ), patch("replenishment.services.criticality.connection", mock_connection):
            resolved, warnings = criticality_service._load_hazard_defaults(
                "public",
                "HURRICANE",
                [1],
                timezone.now(),
            )

        self.assertEqual(resolved, {1: "HIGH"})
        self.assertEqual(warnings, [])
        executed_sql = mock_cursor.execute.call_args.args[0]
        self.assertIn("UPPER(approval_status) IN ('APPROVED', 'A')", executed_sql)


class CriticalityGovernanceApiTests(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="dev-user",
        DEV_AUTH_ROLES=["LOGISTICS"],
        DEV_AUTH_PERMISSIONS=[PERM_CRITICALITY_OVERRIDE_MANAGE],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch("replenishment.views.criticality_governance.create_event_override")
    def test_event_override_create_endpoint(self, mock_create):
        mock_create.return_value = (
            {
                "override_id": 1,
                "event_id": 5,
                "item_id": 11,
                "criticality_level": "HIGH",
                "is_active": True,
            },
            [],
        )

        response = self.client.post(
            "/api/v1/replenishment/criticality/event-overrides",
            {
                "event_id": 5,
                "item_id": 11,
                "criticality_level": "HIGH",
                "reason_text": "Road access delayed.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["override"]["criticality_level"], "HIGH")
        mock_create.assert_called_once()

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="dev-user",
        DEV_AUTH_ROLES=["LOGISTICS"],
        DEV_AUTH_PERMISSIONS=[PERM_CRITICALITY_HAZARD_APPROVE],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch("replenishment.views.criticality_governance.approve_hazard_default")
    def test_hazard_default_approve_requires_director_role(
        self,
        mock_approve,
    ) -> None:
        response = self.client.post(
            "/api/v1/replenishment/criticality/hazard-defaults/10/approve",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertIn("approval", response.json().get("errors", {}))
        mock_approve.assert_not_called()

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="director-user",
        DEV_AUTH_ROLES=["ODPEM_DIR_PEOD"],
        DEV_AUTH_PERMISSIONS=[PERM_CRITICALITY_HAZARD_APPROVE],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch("replenishment.views.criticality_governance.approve_hazard_default")
    def test_hazard_default_approve_allows_director_role(
        self,
        mock_approve,
    ) -> None:
        mock_approve.return_value = (
            {
                "hazard_item_criticality_id": 10,
                "event_type": "HURRICANE",
                "item_id": 11,
                "criticality_level": "CRITICAL",
                "approval_status": "APPROVED",
            },
            [],
        )

        response = self.client.post(
            "/api/v1/replenishment/criticality/hazard-defaults/10/approve",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["hazard_default"]["approval_status"], "APPROVED")
        mock_approve.assert_called_once()


class ApprovalRoleResolutionTests(SimpleTestCase):
    def setUp(self) -> None:
        approval_service._TABLE_COLUMNS_CACHE.clear()

    def test_transfer_policy_allows_on_behalf_for_logistics_submitter(self) -> None:
        roles = approval_service.required_roles_for_approval(
            {"approver_role": "Logistics Manager (Kemar)"},
            record={"selected_method": "A", "warehouse_id": 1},
            submitter_roles={"LOGISTICS_MANAGER"},
        )
        self.assertIn("LOGISTICS_MANAGER", roles)
        self.assertIn("ODPEM_DIR_PEOD", roles)

    def test_transfer_policy_excludes_on_behalf_when_condition_not_met(self) -> None:
        roles = approval_service.required_roles_for_approval(
            {"approver_role": "Logistics Manager (Kemar)"},
            record={"selected_method": "A", "warehouse_id": 1},
            submitter_roles={"INVENTORY_CLERK"},
        )
        self.assertIn("LOGISTICS_MANAGER", roles)
        self.assertNotIn("ODPEM_DIR_PEOD", roles)

    def test_transfer_policy_treats_logistics_officer_as_logistics_submitter(self) -> None:
        roles = approval_service.required_roles_for_approval(
            {"approver_role": "Logistics Manager (Kemar)"},
            record={"selected_method": "A", "warehouse_id": 1},
            submitter_roles={"LOGISTICS_OFFICER"},
        )
        self.assertIn("LOGISTICS_MANAGER", roles)
        self.assertIn("ODPEM_DIR_PEOD", roles)

    def test_transfer_policy_treats_test_logistics_officer_as_logistics_submitter(self) -> None:
        roles = approval_service.required_roles_for_approval(
            {"approver_role": "Logistics Manager (Kemar)"},
            record={"selected_method": "A", "warehouse_id": 1},
            submitter_roles={"TST_LOGISTICS_OFFICER"},
        )
        self.assertIn("LOGISTICS_MANAGER", roles)
        self.assertIn("ODPEM_DIR_PEOD", roles)

    def test_procurement_policy_uses_director_peod_only(self) -> None:
        roles = approval_service.required_roles_for_approval(
            {"approver_role": "DG + PPC Endorsement"},
            record={"selected_method": "C", "warehouse_id": 1},
            submitter_roles={"LOGISTICS_MANAGER"},
        )
        self.assertIn("ODPEM_DIR_PEOD", roles)
        self.assertIn("SYSTEM_ADMINISTRATOR", roles)
        self.assertNotIn("LOGISTICS_MANAGER", roles)
        self.assertNotIn("ODPEM_DG", roles)

    def test_procurement_policy_includes_test_role_alias_for_dir_peod(self) -> None:
        roles = approval_service.required_roles_for_approval(
            {"approver_role": "DG + PPC Endorsement"},
            record={"selected_method": "C", "warehouse_id": 1},
            submitter_roles={"TST_LOGISTICS_MANAGER"},
        )
        self.assertIn("TST_DIR_PEOD", roles)

    def test_donation_policy_allows_logistics_manager(self) -> None:
        roles = approval_service.required_roles_for_approval(
            {"approver_role": "Senior Director (Andrea)"},
            record={"selected_method": "B", "warehouse_id": 1},
            submitter_roles={"LOGISTICS_MANAGER"},
        )
        self.assertIn("LOGISTICS_MANAGER", roles)
        self.assertIn("SENIOR_DIRECTOR", roles)

    def test_table_columns_uses_configured_schema_for_postgres_introspection(
        self,
    ) -> None:
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [("user_id",), ("username",)]
        mock_context = MagicMock()
        mock_context.__enter__.return_value = mock_cursor
        mock_context.__exit__.return_value = False
        mock_connection = MagicMock()
        mock_connection.vendor = "postgresql"
        mock_connection.cursor.return_value = mock_context

        with patch.dict(os.environ, {"DMIS_DB_SCHEMA": "dmis_custom"}), patch(
            "replenishment.services.approval.connection",
            mock_connection,
        ):
            columns = approval_service._table_columns("user")

        self.assertEqual(columns, {"user_id", "username"})
        mock_cursor.execute.assert_called_once()
        execute_sql, execute_params = mock_cursor.execute.call_args.args
        self.assertIn("table_schema = %s", execute_sql)
        self.assertEqual(execute_params, ["dmis_custom", "user"])

    def test_table_columns_cache_is_scoped_by_schema(
        self,
    ) -> None:
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [("user_id",)]
        mock_context = MagicMock()
        mock_context.__enter__.return_value = mock_cursor
        mock_context.__exit__.return_value = False
        mock_connection = MagicMock()
        mock_connection.vendor = "postgresql"
        mock_connection.cursor.return_value = mock_context

        with patch("replenishment.services.approval.connection", mock_connection):
            with patch.dict(os.environ, {"DMIS_DB_SCHEMA": "schema_one"}):
                first = approval_service._table_columns("user")
            with patch.dict(os.environ, {"DMIS_DB_SCHEMA": "schema_two"}):
                second = approval_service._table_columns("user")

        self.assertEqual(first, {"user_id"})
        self.assertEqual(second, {"user_id"})
        self.assertEqual(mock_cursor.execute.call_count, 2)


class NeedsListPreviewApiTests(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()

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
        self.assertTrue(any(warning in body["warnings"] for warning in ("db_unavailable_preview_stub", "burn_data_missing")))
        self.assertIn("debug_summary", body)
        self.assertEqual(
            body["debug_summary"]["burn"].get("filter"),
            "reliefpkg_item.fr_inventory_id warehouse scope, "
            "reliefpkg.status_code IN ('D','R'), dispatch_dtime window",
        )

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
    @patch("replenishment.views.data_access.get_item_categories")
    @patch("replenishment.views.data_access.get_category_burn_fallback_rates")
    @patch("replenishment.views.data_access.get_burn_by_item")
    @patch("replenishment.views.data_access.get_inbound_transfers_by_item")
    @patch("replenishment.views.data_access.get_inbound_donations_by_item")
    @patch("replenishment.views.data_access.get_effective_criticality_by_item")
    @patch("replenishment.views.data_access.get_available_by_item")
    def test_preview_endpoint_includes_required_fields(
        self,
        mock_available,
        mock_criticality,
        mock_donations,
        mock_transfers,
        mock_burn,
        mock_fallback,
        mock_categories,
    ) -> None:
        mock_available.return_value = ({1: 10.0}, [], None)
        mock_criticality.return_value = (
            {
                1: {
                    "effective_criticality_level": "HIGH",
                    "effective_criticality_source": "ITEM_DEFAULT",
                }
            },
            [],
        )
        mock_donations.return_value = ({}, [])
        mock_transfers.return_value = ({}, [])
        mock_burn.return_value = (
            {1: 24.0},
            [],
            "reliefpkg",
            {
                "filter": (
                    "reliefpkg_item.fr_inventory_id warehouse scope, "
                    "reliefpkg.status_code IN ('D','R'), dispatch_dtime window"
                )
            },
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
        self.assertEqual(len(body["items"]), 1)
        self.assertEqual(
            body.get("phase_window", {}).get("source"),
            "backlog_default",
        )
        self.assertEqual(
            body.get("horizon_lead_times_hours"),
            {"A": 8, "B": 72, "C": 336},
        )
        item = body["items"][0]
        self.assertIn("required_qty", item)
        self.assertIn("time_to_stockout", item)
        self.assertIn("effective_criticality_level", item)
        self.assertIn("effective_criticality_source", item)
        self.assertEqual(item.get("freshness_state"), "LOW")
        self.assertEqual(body.get("freshness_summary"), {"HIGH": 0, "MEDIUM": 0, "LOW": 1})

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
    @patch("replenishment.views.data_access.get_inbound_transfers_by_item")
    @patch("replenishment.views.data_access.get_inbound_donations_by_item")
    @patch("replenishment.views.data_access.get_available_by_item")
    def test_preview_endpoint_fails_fast_when_inbound_view_missing(
        self,
        mock_available,
        mock_donations,
        mock_transfers,
    ) -> None:
        mock_available.return_value = ({}, [], None)
        mock_donations.return_value = ({}, ["strict_inbound_workflow_view_missing"])
        mock_transfers.return_value = ({}, ["strict_inbound_workflow_view_missing"])

        response = self.client.post(
            "/api/v1/replenishment/needs-list/preview",
            {"event_id": 1, "warehouse_id": 1, "phase": "BASELINE"},
            format="json",
        )

        self.assertEqual(response.status_code, 503)
        self.assertIn("strict_inbound_workflow_view_missing", response.json().get("errors", {}))


class NeedsListPreviewMultiApiTests(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()

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
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="dev-user",
        DEV_AUTH_ROLES=["LOGISTICS"],
        DEV_AUTH_PERMISSIONS=[],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch("replenishment.views.data_access.get_inbound_transfers_by_item")
    @patch("replenishment.views.data_access.get_inbound_donations_by_item")
    @patch("replenishment.views.data_access.get_available_by_item")
    def test_preview_multi_fails_fast_when_inbound_view_missing(
        self,
        mock_available,
        mock_donations,
        mock_transfers,
    ) -> None:
        mock_available.return_value = ({}, [], None)
        mock_donations.return_value = ({}, ["strict_inbound_workflow_view_missing"])
        mock_transfers.return_value = ({}, ["strict_inbound_workflow_view_missing"])

        response = self.client.post(
            "/api/v1/replenishment/needs-list/preview-multi",
            {"event_id": 1, "warehouse_ids": [1, 2], "phase": "BASELINE"},
            format="json",
        )

        self.assertEqual(response.status_code, 503)
        body = response.json()
        self.assertEqual(body.get("warehouse_id"), 1)
        self.assertIn("strict_inbound_workflow_view_missing", body.get("errors", {}))

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
        TEST_DEV_AUTH_ENABLED=True,
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


class DataAccessBurnQueryTests(SimpleTestCase):
    def _mock_connection_for_destination_only_rows(self, rows) -> tuple[MagicMock, MagicMock]:
        cursor = MagicMock()

        def execute(sql, params):
            cursor.executed_sql = sql
            cursor.executed_params = params
            cursor.fetchall.return_value = rows if "rp.to_inventory_id = %s" in sql else []

        cursor.execute.side_effect = execute
        cursor_context = MagicMock()
        cursor_context.__enter__.return_value = cursor
        cursor_context.__exit__.return_value = False
        mock_connection = MagicMock()
        mock_connection.cursor.return_value = cursor_context
        return cursor, mock_connection

    def test_burn_query_ignores_destination_only_packages(self) -> None:
        cursor, mock_connection = self._mock_connection_for_destination_only_rows(
            [(10, Decimal("12.0"))]
        )

        with patch("replenishment.services.data_access._is_sqlite", return_value=False), patch(
            "replenishment.services.data_access._schema_name",
            return_value="public",
        ), patch(
            "replenishment.services.data_access.connection",
            mock_connection,
        ):
            burn_by_item, warnings, source, _debug = data_access.get_burn_by_item(
                event_id=1,
                warehouse_id=7,
                demand_window_hours=24,
                as_of_dt=timezone.now(),
            )

        self.assertEqual(burn_by_item, {})
        self.assertEqual(source, "none")
        self.assertIn("burn_data_missing", warnings)
        self.assertIn("rpi.fr_inventory_id = %s", cursor.executed_sql)
        self.assertNotIn("rp.to_inventory_id = %s", cursor.executed_sql)
        self.assertEqual(cursor.executed_params[0], 7)

    def test_category_fallback_query_ignores_destination_only_packages(self) -> None:
        cursor, mock_connection = self._mock_connection_for_destination_only_rows(
            [(3, Decimal("48.0"))]
        )

        with patch("replenishment.services.data_access._is_sqlite", return_value=False), patch(
            "replenishment.services.data_access._schema_name",
            return_value="public",
        ), patch(
            "replenishment.services.data_access.connection",
            mock_connection,
        ):
            category_rates, warnings, _debug = data_access.get_category_burn_fallback_rates(
                event_id=1,
                warehouse_id=7,
                lookback_days=30,
                as_of_dt=timezone.now(),
            )

        self.assertEqual(category_rates, {})
        self.assertEqual(warnings, [])
        self.assertIn("rpi.fr_inventory_id = %s", cursor.executed_sql)
        self.assertNotIn("rp.to_inventory_id = %s", cursor.executed_sql)
        self.assertEqual(cursor.executed_params[0], 7)


class DataAccessAtomicityTests(TestCase):
    @patch("replenishment.services.data_access.get_transfers_for_needs_list")
    @patch(
        "replenishment.services.data_access.create_draft_transfer_with_items",
        side_effect=DatabaseError("insert failed"),
    )
    @patch("replenishment.services.data_access._schema_name", return_value="public")
    @patch("replenishment.services.data_access._is_sqlite", return_value=False)
    def test_create_draft_transfers_if_absent_aborts_on_insert_failure(
        self,
        _mock_is_sqlite,
        _mock_schema_name,
        mock_create_transfer,
        mock_get_transfers,
    ) -> None:
        cursor = MagicMock()
        cursor.fetchone.return_value = None  # No pre-existing transfers.
        cursor_cm = MagicMock()
        cursor_cm.__enter__.return_value = cursor
        cursor_cm.__exit__.return_value = False

        with patch("replenishment.services.data_access.connection.cursor", return_value=cursor_cm):
            transfers, created_count, already_exists, warnings = (
                data_access.create_draft_transfers_if_absent(
                    needs_list_id="NL-A",
                    transfer_specs=[
                        {
                            "from_warehouse_id": 1,
                            "to_warehouse_id": 2,
                            "event_id": 3,
                            "needs_list_id": "NL-A",
                            "reason": "test",
                            "actor_id": "tester",
                            "items": [{"item_id": 10, "item_qty": 1, "uom_code": "EA"}],
                        }
                    ],
                )
            )

        self.assertEqual(transfers, [])
        self.assertEqual(created_count, 0)
        self.assertFalse(already_exists)
        self.assertIn("db_error_insert_transfer", warnings)
        mock_create_transfer.assert_called_once()
        mock_get_transfers.assert_not_called()

    @patch("replenishment.services.data_access._schema_name", return_value="public")
    @patch("replenishment.services.data_access._is_sqlite", return_value=False)
    def test_confirm_transfer_draft_uses_select_for_update(
        self,
        _mock_is_sqlite,
        _mock_schema_name,
    ) -> None:
        cursor = MagicMock()
        cursor.fetchone.return_value = ("P",)
        cursor.rowcount = 1
        cursor_cm = MagicMock()
        cursor_cm.__enter__.return_value = cursor
        cursor_cm.__exit__.return_value = False

        with patch("replenishment.services.data_access.connection.cursor", return_value=cursor_cm):
            success, warnings = data_access.confirm_transfer_draft(
                transfer_id=77,
                needs_list_id="NL-A",
                actor_id="tester",
            )

        self.assertTrue(success)
        self.assertEqual(warnings, [])
        self.assertGreaterEqual(cursor.execute.call_count, 2)
        executed_queries = [
            str(call.args[0]) for call in cursor.execute.call_args_list if call.args
        ]
        self.assertTrue(
            any(
                "SELECT STATUS_CODE" in query.upper() and "FOR UPDATE" in query.upper()
                for query in executed_queries
            )
        )


@override_settings(TENANT_SCOPE_ENFORCEMENT=False)
class NeedsListWorkflowApiTests(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        store_path_fn = getattr(workflow_store, "_store_path", None)
        if callable(store_path_fn):
            store_path = store_path_fn()
            if store_path.exists():
                store_path.unlink()

    def tearDown(self) -> None:
        store_path_fn = getattr(workflow_store, "_store_path", None)
        if callable(store_path_fn):
            store_path = store_path_fn()
            if store_path.exists():
                store_path.unlink()

    def _draft_payload(self) -> dict:
        return {"event_id": 1, "warehouse_id": 1, "phase": "BASELINE"}

    @override_settings(TENANT_SCOPE_ENFORCEMENT=True)
    def test_accessible_read_warehouse_ids_keeps_read_all_context_unbounded(self) -> None:
        request = APIRequestFactory().get(
            "/api/v1/replenishment/needs-list/",
            {"tenant_id": "1"},
        )
        context = TenantContext(
            requested_tenant_id=1,
            active_tenant_id=1,
            active_tenant_code="ODPEM-NEOC",
            active_tenant_type="NATIONAL",
            memberships=(),
            can_read_all_tenants=True,
            can_act_cross_tenant=False,
        )

        with patch("replenishment.views._tenant_context", return_value=context):
            self.assertIsNone(views._accessible_read_warehouse_ids(request))

    @override_settings(TENANT_SCOPE_ENFORCEMENT=True)
    @patch("replenishment.views.data_access.get_warehouse_ids_for_tenants", return_value=set())
    def test_accessible_read_warehouse_ids_treats_empty_scope_as_deny_all(
        self,
        mock_get_warehouse_ids_for_tenants,
    ) -> None:
        request = APIRequestFactory().get(
            "/api/v1/replenishment/needs-list/",
            {"tenant_id": "1"},
        )
        context = TenantContext(
            requested_tenant_id=2,
            active_tenant_id=1,
            active_tenant_code="AGENCY_A",
            active_tenant_type="AGENCY",
            memberships=(
                TenantMembership(
                    tenant_id=1,
                    tenant_code="AGENCY_A",
                    tenant_name="Agency A",
                    tenant_type="AGENCY",
                    is_primary=True,
                    access_level="WRITE",
                ),
            ),
            can_read_all_tenants=False,
            can_act_cross_tenant=False,
        )

        with patch("replenishment.views._tenant_context", return_value=context):
            self.assertEqual(views._accessible_read_warehouse_ids(request), set())

        mock_get_warehouse_ids_for_tenants.assert_called_once_with({1})

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
    @patch("replenishment.views.workflow_store.get_record")
    @patch("replenishment.views.workflow_store.store_enabled_or_raise")
    @patch("replenishment.views.data_access.update_transfer_draft")
    def test_transfer_update_scoped_to_needs_list(
        self,
        mock_update_transfer,
        _mock_store_enabled,
        mock_get_record,
    ) -> None:
        mock_get_record.return_value = {"needs_list_id": "NL-A"}
        mock_update_transfer.return_value = ["transfer_not_found_for_needs_list"]

        response = self.client.patch(
            "/api/v1/replenishment/needs-list/NL-A/transfers/77",
            {"reason": "Update requested", "items": []},
            format="json",
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json().get("errors", {}).get("transfer_id"),
            "Not found for this needs list.",
        )
        mock_update_transfer.assert_called_once_with(
            77,
            "NL-A",
            {"reason": "Update requested", "items": []},
        )

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
    @patch("replenishment.views.workflow_store.get_record")
    @patch("replenishment.views.workflow_store.store_enabled_or_raise")
    @patch("replenishment.views.data_access.update_transfer_draft")
    def test_transfer_update_handles_null_reason(
        self,
        mock_update_transfer,
        _mock_store_enabled,
        mock_get_record,
    ) -> None:
        mock_get_record.return_value = {"needs_list_id": "NL-A"}

        response = self.client.patch(
            "/api/v1/replenishment/needs-list/NL-A/transfers/77",
            {"reason": None, "items": [{"item_id": 1, "item_qty": 2}]},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json().get("errors", {}).get("reason"),
            "Reason is required when modifying quantities.",
        )
        mock_update_transfer.assert_not_called()

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
    @patch("replenishment.views.workflow_store.get_record")
    @patch("replenishment.views.workflow_store.store_enabled_or_raise")
    @patch("replenishment.views.data_access.update_transfer_draft")
    def test_transfer_update_rejects_non_draft_transfer(
        self,
        mock_update_transfer,
        _mock_store_enabled,
        mock_get_record,
    ) -> None:
        mock_get_record.return_value = {"needs_list_id": "NL-A"}
        mock_update_transfer.return_value = ["transfer_not_found_or_not_draft"]

        response = self.client.patch(
            "/api/v1/replenishment/needs-list/NL-A/transfers/77",
            {"reason": "Update requested", "items": [{"item_id": 1, "item_qty": 2}]},
            format="json",
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json().get("errors", {}).get("status"),
            "Only draft transfers can be updated.",
        )

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
    @patch("replenishment.views.workflow_store.get_record")
    @patch("replenishment.views.workflow_store.store_enabled_or_raise")
    @patch("replenishment.views.data_access.confirm_transfer_draft")
    def test_transfer_confirm_scoped_to_needs_list(
        self,
        mock_confirm_transfer,
        _mock_store_enabled,
        mock_get_record,
    ) -> None:
        mock_get_record.return_value = {"needs_list_id": "NL-A"}
        mock_confirm_transfer.return_value = (
            False,
            ["transfer_not_found_for_needs_list"],
        )

        response = self.client.post(
            "/api/v1/replenishment/needs-list/NL-A/transfers/77/confirm",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json().get("errors", {}).get("transfer_id"),
            "Not found for this needs list.",
        )
        args, _ = mock_confirm_transfer.call_args
        self.assertEqual(args[0], 77)
        self.assertEqual(args[1], "NL-A")

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
    @patch("replenishment.views.workflow_store.get_record")
    @patch("replenishment.views.workflow_store.store_enabled_or_raise")
    @patch("replenishment.views.data_access.confirm_transfer_draft")
    def test_transfer_confirm_rejects_non_draft_transfer(
        self,
        mock_confirm_transfer,
        _mock_store_enabled,
        mock_get_record,
    ) -> None:
        mock_get_record.return_value = {"needs_list_id": "NL-A"}
        mock_confirm_transfer.return_value = (
            False,
            ["transfer_not_found_or_not_draft"],
        )

        response = self.client.post(
            "/api/v1/replenishment/needs-list/NL-A/transfers/77/confirm",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 409)
        self.assertIn(
            "Transfer not found or not in draft status.",
            response.json().get("errors", {}).get("transfer", ""),
        )

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
    def test_generate_transfers_sets_item_inventory_id_from_source(self) -> None:
        record = {
            "needs_list_id": "NL-A",
            "needs_list_no": "NL-A-001",
            "status": "APPROVED",
            "warehouse_id": 10,
            "event_id": 1,
            "snapshot": {
                "items": [
                    {
                        "item_id": 101,
                        "item_name": "Water",
                        "uom_code": "EA",
                        "horizon": {"A": {"recommended_qty": 5}},
                    }
                ]
            },
        }

        with patch("replenishment.views.workflow_store.store_enabled_or_raise"), patch(
            "replenishment.views.workflow_store.get_record", return_value=record
        ), patch(
            "replenishment.views.data_access.get_warehouses_with_stock",
            return_value=(
                {
                    101: [
                        {
                            "warehouse_id": 2,
                            "warehouse_name": "Source",
                            "available_qty": 10,
                        }
                    ]
                },
                [],
            ),
        ), patch(
            "replenishment.views.data_access.create_draft_transfers_if_absent",
            return_value=([{"transfer_id": 99}], 1, False, []),
        ) as mock_create_transfers:
            response = self.client.post(
                "/api/v1/replenishment/needs-list/NL-A/generate-transfers",
                {},
                format="json",
            )

        self.assertEqual(response.status_code, 201)
        mock_create_transfers.assert_called_once()
        _, kwargs = mock_create_transfers.call_args
        transfer_specs = kwargs["transfer_specs"]
        self.assertEqual(kwargs["needs_list_id"], "NL-A")
        self.assertEqual(transfer_specs[0]["from_warehouse_id"], 2)
        self.assertEqual(transfer_specs[0]["to_warehouse_id"], 10)
        self.assertEqual(transfer_specs[0]["items"][0]["inventory_id"], 2)

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="dev-user",
        DEV_AUTH_ROLES=["LOGISTICS"],
        DEV_AUTH_PERMISSIONS=[],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
        TENANT_SCOPE_ENFORCEMENT=True,
    )
    @patch("replenishment.views.operations_policy.resolve_odpem_tenant_id", return_value=27)
    @patch("replenishment.views.resolve_warehouse_tenant_id", return_value=27)
    def test_odpem_replenishment_needs_list_can_still_generate_transfer_sourcing(
        self,
        resolve_warehouse_tenant_id_mock,
        resolve_odpem_tenant_id_mock,
    ) -> None:
        record = {
            "needs_list_id": "NL-ODPEM-A",
            "needs_list_no": "NL-ODPEM-001",
            "status": "APPROVED",
            "warehouse_id": 10,
            "event_id": 1,
            "snapshot": {
                "items": [
                    {
                        "item_id": 101,
                        "item_name": "Water",
                        "uom_code": "EA",
                        "horizon": {"A": {"recommended_qty": 5}},
                    }
                ]
            },
        }

        with patch("replenishment.views.workflow_store.store_enabled_or_raise"), patch(
            "replenishment.views.workflow_store.get_record", return_value=record
        ), patch(
            "replenishment.views.data_access.get_warehouses_with_stock",
            return_value=(
                {
                    101: [
                        {
                            "warehouse_id": 2,
                            "warehouse_name": "Source",
                            "available_qty": 10,
                        }
                    ]
                },
                [],
            ),
        ), patch(
            "replenishment.views.data_access.create_draft_transfers_if_absent",
            return_value=([{"transfer_id": 99}], 1, False, []),
        ) as mock_create_transfers:
            response = self.client.post(
                "/api/v1/replenishment/needs-list/NL-ODPEM-A/generate-transfers",
                {},
                format="json",
            )

        self.assertEqual(response.status_code, 201)
        mock_create_transfers.assert_called_once()
        resolve_odpem_tenant_id_mock.assert_called_once()
        resolve_warehouse_tenant_id_mock.assert_called_once_with(record["warehouse_id"])

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="dev-user",
        DEV_AUTH_ROLES=["LOGISTICS"],
        DEV_AUTH_PERMISSIONS=[],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
        TENANT_SCOPE_ENFORCEMENT=True,
    )
    @patch("replenishment.views.operations_policy.resolve_odpem_tenant_id", return_value=99)
    @patch("replenishment.views.resolve_warehouse_tenant_id", return_value=99)
    def test_odpem_replenishment_generate_transfer_sourcing_denies_cross_tenant_access(
        self,
        resolve_warehouse_tenant_id_mock,
        resolve_odpem_tenant_id_mock,
    ) -> None:
        record = {
            "needs_list_id": "NL-ODPEM-A",
            "needs_list_no": "NL-ODPEM-001",
            "status": "APPROVED",
            "warehouse_id": 10,
            "event_id": 1,
            "snapshot": {
                "items": [
                    {
                        "item_id": 101,
                        "item_name": "Water",
                        "uom_code": "EA",
                        "horizon": {"A": {"recommended_qty": 5}},
                    }
                ]
            },
        }

        with patch("replenishment.views.workflow_store.store_enabled_or_raise"), patch(
            "replenishment.views.workflow_store.get_record", return_value=record
        ), patch(
            "replenishment.views.data_access.get_warehouses_with_stock",
            return_value=(
                {
                    101: [
                        {
                            "warehouse_id": 2,
                            "warehouse_name": "Source",
                            "available_qty": 10,
                        }
                    ]
                },
                [],
            ),
        ), patch(
            "replenishment.views.data_access.create_draft_transfers_if_absent",
            return_value=([{"transfer_id": 99}], 1, False, []),
        ) as mock_create_transfers:
            response = self.client.post(
                "/api/v1/replenishment/needs-list/NL-ODPEM-A/generate-transfers",
                {},
                format="json",
            )

        self.assertIn(response.status_code, {403, 404})
        mock_create_transfers.assert_not_called()
        resolve_odpem_tenant_id_mock.assert_called_once()
        resolve_warehouse_tenant_id_mock.assert_called_once_with(record["warehouse_id"])

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
    def test_generate_transfers_returns_existing_when_atomic_helper_detects_drafts(self) -> None:
        record = {
            "needs_list_id": "NL-A",
            "needs_list_no": "NL-A-001",
            "status": "APPROVED",
            "warehouse_id": 10,
            "event_id": 1,
            "snapshot": {
                "items": [
                    {
                        "item_id": 101,
                        "item_name": "Water",
                        "uom_code": "EA",
                        "horizon": {"A": {"recommended_qty": 5}},
                    }
                ]
            },
        }
        existing_transfers = [{"transfer_id": 91}]

        with patch("replenishment.views.workflow_store.store_enabled_or_raise"), patch(
            "replenishment.views.workflow_store.get_record", return_value=record
        ), patch(
            "replenishment.views.data_access.get_warehouses_with_stock",
            return_value=(
                {
                    101: [
                        {
                            "warehouse_id": 2,
                            "warehouse_name": "Source",
                            "available_qty": 10,
                        }
                    ]
                },
                [],
            ),
        ), patch(
            "replenishment.views.data_access.create_draft_transfers_if_absent",
            return_value=(existing_transfers, 0, True, []),
        ):
            response = self.client.post(
                "/api/v1/replenishment/needs-list/NL-A/generate-transfers",
                {},
                format="json",
            )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json().get("transfers"), existing_transfers)

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
    def test_donations_endpoint_reads_items_from_snapshot(self) -> None:
        record = {
            "needs_list_id": "NL-A",
            "status": "APPROVED",
            "warehouse_id": 10,
            "snapshot": {
                "items": [
                    {
                        "item_id": 201,
                        "item_name": "Blankets",
                        "uom_code": "EA",
                        "horizon": {"B": {"recommended_qty": 7}},
                    }
                ]
            },
        }

        with patch("replenishment.views.workflow_store.store_enabled_or_raise"), patch(
            "replenishment.views.workflow_store.get_record", return_value=record
        ), patch("replenishment.views.logger.info") as mock_logger_info:
            response = self.client.get(
                "/api/v1/replenishment/needs-list/NL-A/donations",
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        lines = response.json().get("lines", [])
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["item_id"], 201)
        self.assertEqual(lines[0]["required_qty"], 7)
        donation_read_logs = [
            call.kwargs.get("extra", {})
            for call in mock_logger_info.call_args_list
            if call.args and call.args[0] == "needs_list_donations"
        ]
        self.assertEqual(len(donation_read_logs), 1)
        log_data = donation_read_logs[0]
        self.assertEqual(log_data.get("event_type"), "READ")
        self.assertEqual(log_data.get("action"), "READ_DONATIONS_LIST")
        self.assertEqual(log_data.get("needs_list_id"), "NL-A")
        self.assertEqual(log_data.get("line_count"), 1)
        self.assertEqual(log_data.get("user_id"), "dev-user")
        self.assertEqual(log_data.get("username"), "dev-user")
        self.assertTrue(str(log_data.get("timestamp") or "").strip())

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
    def test_donations_export_reads_items_from_snapshot(self) -> None:
        record = {
            "needs_list_id": "NL-A",
            "status": "APPROVED",
            "warehouse_id": 10,
            "snapshot": {
                "items": [
                    {
                        "item_id": 202,
                        "item_name": "Generator",
                        "uom_code": "EA",
                        "horizon": {"B": {"recommended_qty": 2}},
                    }
                ]
            },
        }

        with patch("replenishment.views.workflow_store.store_enabled_or_raise"), patch(
            "replenishment.views.workflow_store.get_record", return_value=record
        ):
            response = self.client.get(
                "/api/v1/replenishment/needs-list/NL-A/donations/export?format=json",
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        items = response.json().get("items", [])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["item_id"], 202)
        self.assertEqual(items[0]["required_qty"], 2)

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
    def test_donations_export_get_csv_requires_async_post(self) -> None:
        record = {
            "needs_list_id": "NL-A",
            "status": "APPROVED",
            "warehouse_id": 10,
            "snapshot": {"items": []},
        }

        with patch("replenishment.views.workflow_store.store_enabled_or_raise"), patch(
            "replenishment.views.workflow_store.get_record", return_value=record
        ):
            response = self.client.get(
                "/api/v1/replenishment/needs-list/NL-A/donations/export?format=csv",
                format="json",
            )

        self.assertEqual(response.status_code, 409)
        self.assertIn("Queue this export with POST", response.json()["errors"]["format"])

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
    @patch("replenishment.views.logger.info")
    @patch("replenishment.views.import_module")
    def test_donations_export_post_queues_and_deduplicates_async_jobs(
        self,
        mock_import_module,
        mock_logger_info,
    ) -> None:
        record = {
            "needs_list_id": "NL-A",
            "needs_list_no": "NL-ASYNC-A",
            "status": "APPROVED",
            "warehouse_id": 10,
            "updated_at": "2026-04-10T12:00:00Z",
            "snapshot": {
                "items": [
                    {
                        "item_id": 202,
                        "item_name": "Generator",
                        "uom_code": "EA",
                        "horizon": {"B": {"recommended_qty": 2}},
                    }
                ]
            },
        }
        delay = MagicMock()
        mock_import_module.return_value = SimpleNamespace(
            run_async_job=SimpleNamespace(delay=delay)
        )

        with patch("replenishment.views.workflow_store.store_enabled_or_raise"), patch(
            "replenishment.views.workflow_store.get_record", return_value=record
        ):
            first_response = self.client.post(
                "/api/v1/replenishment/needs-list/NL-A/donations/export",
                {"format": "csv"},
                format="json",
            )
            second_response = self.client.post(
                "/api/v1/replenishment/needs-list/NL-A/donations/export",
                {"format": "csv"},
                format="json",
            )

        self.assertEqual(first_response.status_code, 202)
        self.assertEqual(second_response.status_code, 202)
        first_body = first_response.json()
        second_body = second_response.json()
        self.assertEqual(first_body["status"], "QUEUED")
        self.assertEqual(first_body["job_type"], AsyncJob.JobType.NEEDS_LIST_DONATION_EXPORT)
        self.assertEqual(second_body["job_id"], first_body["job_id"])
        self.assertTrue(second_body["deduplicated"])
        self.assertEqual(AsyncJob.objects.count(), 1)
        job = AsyncJob.objects.get()
        self.assertEqual(job.source_snapshot_version, "NL-A|2026-04-10T12:00:00Z|APPROVED")
        delay.assert_called_once_with(job.job_id)
        queued_logs = [
            call.kwargs.get("extra", {})
            for call in mock_logger_info.call_args_list
            if call.args and call.args[0] == "job.queued"
        ]
        self.assertEqual(len(queued_logs), 1)
        self.assertEqual(queued_logs[0].get("job_id"), job.job_id)
        self.assertEqual(queued_logs[0].get("source_snapshot_version"), job.source_snapshot_version)

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
    @patch("replenishment.views.import_module")
    def test_donations_export_post_deduplicated_requests_do_not_consume_rate_limit(
        self,
        mock_import_module,
    ) -> None:
        record = {
            "needs_list_id": "NL-A",
            "needs_list_no": "NL-ASYNC-A",
            "status": "APPROVED",
            "warehouse_id": 10,
            "tenant_id": 5,
            "event_phase": "SURGE",
            "updated_at": "2026-04-10T12:00:00Z",
            "snapshot": {"items": []},
        }
        delay = MagicMock()
        mock_import_module.return_value = SimpleNamespace(
            run_async_job=SimpleNamespace(delay=delay)
        )
        cache.clear()
        try:
            with patch("replenishment.views.workflow_store.store_enabled_or_raise"), patch(
                "replenishment.views.workflow_store.get_record", return_value=record
            ):
                responses = [
                    self.client.post(
                        "/api/v1/replenishment/needs-list/NL-A/donations/export",
                        {"format": "csv"},
                        format="json",
                    )
                    for _ in range(6)
                ]
        finally:
            cache.clear()

        self.assertTrue(all(response.status_code == 202 for response in responses))
        self.assertEqual(AsyncJob.objects.count(), 1)
        self.assertEqual(delay.call_count, 1)
        self.assertTrue(all(response.json().get("deduplicated") for response in responses[1:]))

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
    @patch("replenishment.views.logger.warning")
    @patch("replenishment.views.import_module")
    def test_donations_export_post_rate_limits_after_five_requests(
        self,
        mock_import_module,
        mock_logger_warning,
    ) -> None:
        records = [
            {
                "needs_list_id": "NL-A",
                "needs_list_no": "NL-ASYNC-A",
                "status": "APPROVED",
                "warehouse_id": 10,
                "tenant_id": 5,
                "event_phase": "SURGE",
                "updated_at": f"2026-04-10T12:00:0{index}Z",
                "snapshot": {"items": []},
            }
            for index in range(6)
        ]
        delay = MagicMock()
        mock_import_module.return_value = SimpleNamespace(
            run_async_job=SimpleNamespace(delay=delay)
        )
        cache.clear()
        try:
            with patch("replenishment.views.workflow_store.store_enabled_or_raise"), patch(
                "replenishment.views.workflow_store.get_record", side_effect=records
            ):
                responses = [
                    self.client.post(
                        "/api/v1/replenishment/needs-list/NL-A/donations/export",
                        {"format": "csv"},
                        format="json",
                    )
                    for _ in range(6)
                ]
        finally:
            cache.clear()

        self.assertTrue(all(response.status_code == 202 for response in responses[:5]))
        self.assertEqual(responses[5].status_code, 429)
        self.assertIn("Retry-After", responses[5])
        self.assertEqual(AsyncJob.objects.count(), 5)
        self.assertEqual(delay.call_count, 5)
        throttle_logs = [
            call.kwargs.get("extra", {})
            for call in mock_logger_warning.call_args_list
            if call.args and call.args[0] == "request.throttled"
        ]
        self.assertEqual(len(throttle_logs), 1)
        self.assertEqual(throttle_logs[0].get("actor_user_id"), "dev-user")
        self.assertEqual(throttle_logs[0].get("tenant_id"), 5)
        self.assertEqual(throttle_logs[0].get("endpoint_tier"), "file_export")
        self.assertEqual(throttle_logs[0].get("active_event_phase"), "SURGE")

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
    @patch(
        "replenishment.views.get_replenishment_export_audit_schema_status",
        return_value=(
            "failed",
            "Queued export durability requires needs_list_audit.request_id to exist; apply the replenishment export audit schema update.",
        ),
    )
    @patch("replenishment.views.logger.error")
    @patch("replenishment.views.import_module")
    def test_donations_export_post_blocks_when_export_audit_schema_is_missing(
        self,
        mock_import_module,
        mock_logger_error,
        _mock_schema_status,
    ) -> None:
        record = {
            "needs_list_id": "NL-A",
            "needs_list_no": "NL-ASYNC-A",
            "status": "APPROVED",
            "warehouse_id": 10,
            "updated_at": "2026-04-10T12:00:00Z",
            "snapshot": {
                "items": [
                    {
                        "item_id": 202,
                        "item_name": "Generator",
                        "uom_code": "EA",
                        "horizon": {"B": {"recommended_qty": 2}},
                    }
                ]
            },
        }

        with patch("replenishment.views.workflow_store.store_enabled_or_raise"), patch(
            "replenishment.views.workflow_store.get_record", return_value=record
        ):
            response = self.client.post(
                "/api/v1/replenishment/needs-list/NL-A/donations/export",
                {"format": "csv"},
                format="json",
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(AsyncJob.objects.count(), 0)
        self.assertIn("Queued export is unavailable", response.json()["errors"]["async"])
        self.assertIn("request_id", response.json()["detail"])
        mock_import_module.assert_not_called()
        mock_logger_error.assert_called_once()

    @override_settings(
        TENANT_SCOPE_ENFORCEMENT=True,
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="tenant-b-user",
        DEV_AUTH_ROLES=["LOGISTICS"],
        DEV_AUTH_PERMISSIONS=[],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch(
        "replenishment.views.resolve_tenant_context",
        return_value=TenantContext(
            requested_tenant_id=20,
            active_tenant_id=20,
            active_tenant_code="TENANT_B",
            active_tenant_type="TENANT",
            memberships=(
                TenantMembership(
                    tenant_id=20,
                    tenant_code="TENANT_B",
                    tenant_name="Tenant B",
                    tenant_type="TENANT",
                    is_primary=True,
                    access_level="FULL",
                ),
            ),
            can_read_all_tenants=False,
            can_act_cross_tenant=False,
        ),
    )
    @patch("replenishment.views.resolve_warehouse_tenant_id", return_value=10)
    @patch("replenishment.views.workflow_store.get_record")
    @patch("replenishment.views.workflow_store.store_enabled_or_raise")
    def test_donations_export_get_denies_cross_tenant_preview(
        self,
        _mock_store_enabled,
        mock_get_record,
        _mock_resolve_warehouse_tenant_id,
        _mock_resolve_tenant_context,
    ) -> None:
        mock_get_record.return_value = {
            "needs_list_id": "NL-A",
            "status": "APPROVED",
            "warehouse_id": 10,
            "snapshot": {"items": []},
        }

        response = self.client.get(
            "/api/v1/replenishment/needs-list/NL-A/donations/export?format=json",
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(AsyncJob.objects.count(), 0)

    @override_settings(
        TENANT_SCOPE_ENFORCEMENT=True,
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="tenant-b-user",
        DEV_AUTH_ROLES=["LOGISTICS"],
        DEV_AUTH_PERMISSIONS=[],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch("replenishment.views.logger.info")
    @patch("replenishment.views.import_module")
    @patch(
        "replenishment.views.resolve_tenant_context",
        return_value=TenantContext(
            requested_tenant_id=20,
            active_tenant_id=20,
            active_tenant_code="TENANT_B",
            active_tenant_type="TENANT",
            memberships=(
                TenantMembership(
                    tenant_id=20,
                    tenant_code="TENANT_B",
                    tenant_name="Tenant B",
                    tenant_type="TENANT",
                    is_primary=True,
                    access_level="FULL",
                ),
            ),
            can_read_all_tenants=False,
            can_act_cross_tenant=False,
        ),
    )
    @patch("replenishment.views.resolve_warehouse_tenant_id", return_value=10)
    @patch("replenishment.views.workflow_store.get_record")
    @patch("replenishment.views.workflow_store.store_enabled_or_raise")
    def test_donations_export_post_denies_cross_tenant_queueing(
        self,
        _mock_store_enabled,
        mock_get_record,
        _mock_resolve_warehouse_tenant_id,
        _mock_resolve_tenant_context,
        mock_import_module,
        mock_logger_info,
    ) -> None:
        mock_get_record.return_value = {
            "needs_list_id": "NL-A",
            "needs_list_no": "NL-ASYNC-A",
            "status": "APPROVED",
            "warehouse_id": 10,
            "updated_at": "2026-04-10T12:00:00Z",
            "snapshot": {
                "items": [
                    {
                        "item_id": 202,
                        "item_name": "Generator",
                        "uom_code": "EA",
                        "horizon": {"B": {"recommended_qty": 2}},
                    }
                ]
            },
        }

        response = self.client.post(
            "/api/v1/replenishment/needs-list/NL-A/donations/export",
            {"format": "csv"},
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(AsyncJob.objects.count(), 0)
        mock_import_module.assert_not_called()
        queued_logs = [
            call.kwargs.get("extra", {})
            for call in mock_logger_info.call_args_list
            if call.args and call.args[0] == "job.queued"
        ]
        self.assertEqual(queued_logs, [])

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
    def test_donations_export_sanitizes_content_disposition_ref(self) -> None:
        from replenishment.views import _safe_content_disposition_ref

        safe_ref = _safe_content_disposition_ref(
            'NL-A"\r\nX-Test: injected',
            "NL-A",
        )
        self.assertEqual(safe_ref, "NL-AX-Test: injected")
        self.assertNotIn("\r", safe_ref)
        self.assertNotIn("\n", safe_ref)
        self.assertNotIn('"', safe_ref)

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
    def test_donations_allocate_returns_not_implemented(self) -> None:
        record = {
            "needs_list_id": "NL-A",
            "status": "APPROVED",
            "snapshot": {"items": []},
        }

        with patch("replenishment.views.workflow_store.store_enabled_or_raise"), patch(
            "replenishment.views.workflow_store.get_record", return_value=record
        ):
            response = self.client.post(
                "/api/v1/replenishment/needs-list/NL-A/donations/allocate",
                [{"item_id": 1, "donation_id": 7, "allocated_qty": 2}],
                format="json",
            )

        self.assertEqual(response.status_code, 501)
        self.assertEqual(
            response.json().get("errors", {}).get("donations"),
            "donation_allocation_not_implemented",
        )
        self.assertIsNone(response.json().get("allocated_count"))

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
    def test_procurement_export_reads_items_from_snapshot(self) -> None:
        record = {
            "needs_list_id": "NL-A",
            "status": "APPROVED",
            "warehouse_id": 10,
            "snapshot": {
                "items": [
                    {
                        "item_id": 203,
                        "item_name": "Water Pump",
                        "uom_code": "EA",
                        "horizon": {"C": {"recommended_qty": 4}},
                        "procurement": {"est_unit_cost": 12.5, "est_total_cost": 50.0},
                    }
                ]
            },
        }

        with patch("replenishment.views.workflow_store.store_enabled_or_raise"), patch(
            "replenishment.views.workflow_store.get_record", return_value=record
        ):
            response = self.client.get(
                "/api/v1/replenishment/needs-list/NL-A/procurement/export?format=json",
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        items = response.json().get("items", [])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["item_id"], 203)
        self.assertEqual(items[0]["required_qty"], 4)

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
    @patch("replenishment.views.import_module")
    def test_procurement_export_post_queues_procurement_async_job(
        self,
        mock_import_module,
    ) -> None:
        record = {
            "needs_list_id": "NL-A",
            "needs_list_no": "NL-ASYNC-C",
            "status": "APPROVED",
            "warehouse_id": 10,
            "updated_at": "2026-04-10T12:00:00Z",
            "snapshot": {
                "items": [
                    {
                        "item_id": 203,
                        "item_name": "Water Pump",
                        "uom_code": "EA",
                        "horizon": {"C": {"recommended_qty": 4}},
                        "procurement": {"est_unit_cost": 12.5, "est_total_cost": 50.0},
                    }
                ]
            },
        }
        delay = MagicMock()
        mock_import_module.return_value = SimpleNamespace(
            run_async_job=SimpleNamespace(delay=delay)
        )

        with patch("replenishment.views.workflow_store.store_enabled_or_raise"), patch(
            "replenishment.views.workflow_store.get_record", return_value=record
        ):
            response = self.client.post(
                "/api/v1/replenishment/needs-list/NL-A/procurement/export",
                {"format": "csv"},
                format="json",
            )

        self.assertEqual(response.status_code, 202)
        body = response.json()
        self.assertEqual(body["job_type"], AsyncJob.JobType.NEEDS_LIST_PROCUREMENT_EXPORT)
        self.assertEqual(body["status"], "QUEUED")
        self.assertTrue(body["status_url"].endswith(body["job_id"]))
        delay.assert_called_once_with(body["job_id"])

    @override_settings(
        TENANT_SCOPE_ENFORCEMENT=True,
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="tenant-b-user",
        DEV_AUTH_ROLES=["LOGISTICS"],
        DEV_AUTH_PERMISSIONS=[],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch(
        "replenishment.views.resolve_tenant_context",
        return_value=TenantContext(
            requested_tenant_id=20,
            active_tenant_id=20,
            active_tenant_code="TENANT_B",
            active_tenant_type="TENANT",
            memberships=(
                TenantMembership(
                    tenant_id=20,
                    tenant_code="TENANT_B",
                    tenant_name="Tenant B",
                    tenant_type="TENANT",
                    is_primary=True,
                    access_level="FULL",
                ),
            ),
            can_read_all_tenants=False,
            can_act_cross_tenant=False,
        ),
    )
    @patch("replenishment.views.resolve_warehouse_tenant_id", return_value=10)
    @patch("replenishment.views.workflow_store.get_record")
    @patch("replenishment.views.workflow_store.store_enabled_or_raise")
    def test_procurement_export_get_denies_cross_tenant_preview(
        self,
        _mock_store_enabled,
        mock_get_record,
        _mock_resolve_warehouse_tenant_id,
        _mock_resolve_tenant_context,
    ) -> None:
        mock_get_record.return_value = {
            "needs_list_id": "NL-A",
            "status": "APPROVED",
            "warehouse_id": 10,
            "snapshot": {"items": []},
        }

        response = self.client.get(
            "/api/v1/replenishment/needs-list/NL-A/procurement/export?format=json",
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(AsyncJob.objects.count(), 0)

    @override_settings(
        TENANT_SCOPE_ENFORCEMENT=True,
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="tenant-b-user",
        DEV_AUTH_ROLES=["LOGISTICS"],
        DEV_AUTH_PERMISSIONS=[],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch("replenishment.views.logger.info")
    @patch("replenishment.views.import_module")
    @patch(
        "replenishment.views.resolve_tenant_context",
        return_value=TenantContext(
            requested_tenant_id=20,
            active_tenant_id=20,
            active_tenant_code="TENANT_B",
            active_tenant_type="TENANT",
            memberships=(
                TenantMembership(
                    tenant_id=20,
                    tenant_code="TENANT_B",
                    tenant_name="Tenant B",
                    tenant_type="TENANT",
                    is_primary=True,
                    access_level="FULL",
                ),
            ),
            can_read_all_tenants=False,
            can_act_cross_tenant=False,
        ),
    )
    @patch("replenishment.views.resolve_warehouse_tenant_id", return_value=10)
    @patch("replenishment.views.workflow_store.get_record")
    @patch("replenishment.views.workflow_store.store_enabled_or_raise")
    def test_procurement_export_post_denies_cross_tenant_queueing(
        self,
        _mock_store_enabled,
        mock_get_record,
        _mock_resolve_warehouse_tenant_id,
        _mock_resolve_tenant_context,
        mock_import_module,
        mock_logger_info,
    ) -> None:
        mock_get_record.return_value = {
            "needs_list_id": "NL-A",
            "needs_list_no": "NL-ASYNC-C",
            "status": "APPROVED",
            "warehouse_id": 10,
            "updated_at": "2026-04-10T12:00:00Z",
            "snapshot": {
                "items": [
                    {
                        "item_id": 203,
                        "item_name": "Water Pump",
                        "uom_code": "EA",
                        "horizon": {"C": {"recommended_qty": 4}},
                        "procurement": {"est_unit_cost": 12.5, "est_total_cost": 50.0},
                    }
                ]
            },
        }
        before_count = AsyncJob.objects.count()

        response = self.client.post(
            "/api/v1/replenishment/needs-list/NL-A/procurement/export",
            {"format": "csv"},
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(AsyncJob.objects.count(), before_count)
        mock_import_module.assert_not_called()
        queued_logs = [
            call.kwargs.get("extra", {})
            for call in mock_logger_info.call_args_list
            if call.args and call.args[0] == "job.queued"
        ]
        self.assertEqual(queued_logs, [])

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
    def test_procurement_export_sanitizes_content_disposition_ref(self) -> None:
        from replenishment.views import _safe_content_disposition_ref

        safe_ref = _safe_content_disposition_ref('"\r\n', "NL-A")
        self.assertEqual(safe_ref, "NL-A")

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
        store_path_fn = getattr(workflow_store, "_store_path", None)
        if callable(store_path_fn):
            store_path = store_path_fn()
            self.assertTrue(store_path.exists())

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
        TEST_DEV_AUTH_ENABLED=True,
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
        TEST_DEV_AUTH_ENABLED=True,
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
        TEST_DEV_AUTH_ENABLED=True,
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
    def test_submit_blocks_duplicate_overlap_when_existing_non_draft_exists(
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
            with self.settings(DEV_AUTH_USER_ID="officer-1", DEV_AUTH_ROLES=["LOGISTICS"]):
                first_draft = self.client.post(
                    "/api/v1/replenishment/needs-list/draft",
                    self._draft_payload(),
                    format="json",
                ).json()
                first_submit = self.client.post(
                    f"/api/v1/replenishment/needs-list/{first_draft['needs_list_id']}/submit",
                    {},
                    format="json",
                )
                self.assertEqual(first_submit.status_code, 200)

            with self.settings(DEV_AUTH_USER_ID="manager-1", DEV_AUTH_ROLES=["LOGISTICS"]):
                second_draft = self.client.post(
                    "/api/v1/replenishment/needs-list/draft",
                    self._draft_payload(),
                    format="json",
                ).json()
                second_submit = self.client.post(
                    f"/api/v1/replenishment/needs-list/{second_draft['needs_list_id']}/submit",
                    {},
                    format="json",
                )

        self.assertEqual(second_submit.status_code, 409)
        body = second_submit.json()
        self.assertIn("duplicate", body.get("errors", {}))
        self.assertGreaterEqual(len(body.get("conflicts", [])), 1)

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
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
    def test_submit_returns_retry_error_for_duplicate_validation_error(
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
            with patch(
                "replenishment.views._find_submitted_or_approved_overlap_conflicts",
                side_effect=views.DuplicateConflictValidationError("invalid duplicate scope"),
            ):
                submit = self.client.post(
                    f"/api/v1/replenishment/needs-list/{needs_list_id}/submit",
                    {},
                    format="json",
                )

        self.assertEqual(submit.status_code, 503)
        self.assertEqual(
            submit.json().get("errors", {}).get("duplicate"),
            "Failed to validate duplicate needs lists. Please retry.",
        )

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
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
    def test_submit_propagates_unexpected_duplicate_validation_exception(
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
            with patch(
                "replenishment.views._find_submitted_or_approved_overlap_conflicts",
                side_effect=RuntimeError("unexpected duplicate validator failure"),
            ):
                with self.assertRaises(RuntimeError):
                    self.client.post(
                        f"/api/v1/replenishment/needs-list/{needs_list_id}/submit",
                        {},
                        format="json",
                    )

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
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
    def test_bulk_submit_returns_retry_error_for_duplicate_validation_error(
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
            with patch(
                "replenishment.views._find_submitted_or_approved_overlap_conflicts",
                side_effect=views.DuplicateConflictValidationError("invalid duplicate scope"),
            ):
                submit = self.client.post(
                    "/api/v1/replenishment/needs-list/bulk-submit/",
                    {"ids": [needs_list_id]},
                    format="json",
                )

        self.assertEqual(submit.status_code, 200)
        body = submit.json()
        self.assertEqual(body.get("count"), 0)
        self.assertEqual(body.get("submitted_ids"), [])
        self.assertEqual(len(body.get("errors", [])), 1)
        self.assertEqual(body["errors"][0].get("id"), needs_list_id)
        self.assertEqual(
            body["errors"][0].get("error"),
            "Failed to validate duplicate needs lists. Please retry.",
        )

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
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
        TEST_DEV_AUTH_ENABLED=True,
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
        TEST_DEV_AUTH_ENABLED=True,
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
        TEST_DEV_AUTH_ENABLED=True,
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
        TEST_DEV_AUTH_ENABLED=True,
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
    def test_needs_list_list_mine_filter_limits_hydrated_records(
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

            with patch(
                "replenishment.views.workflow_store.get_records_by_ids",
                wraps=workflow_store.get_records_by_ids,
            ) as mock_get_records_by_ids:
                response = self.client.get(
                    "/api/v1/replenishment/needs-list/?mine=true&include_closed=false"
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [row.get("needs_list_id") for row in response.json().get("needs_lists", [])],
            [mine_draft.get("needs_list_id")],
        )
        hydrated_ids = list(mock_get_records_by_ids.call_args.args[0])
        self.assertEqual(hydrated_ids, [mine_draft.get("needs_list_id")])

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="submitter",
        DEV_AUTH_ROLES=["LOGISTICS"],
        DEV_AUTH_PERMISSIONS=[],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch("replenishment.views.workflow_store.list_record_headers")
    @patch("replenishment.views.workflow_store.store_enabled_or_raise")
    @patch("replenishment.views._actor_id", return_value=None)
    def test_needs_list_list_returns_empty_personal_list_when_actor_missing(
        self,
        _mock_actor_id,
        _mock_store_enabled,
        mock_list_record_headers,
    ) -> None:
        response = self.client.get(
            "/api/v1/replenishment/needs-list/?mine=true&include_closed=false"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"needs_lists": [], "count": 0})
        mock_list_record_headers.assert_not_called()

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="neoc-reader",
        DEV_AUTH_ROLES=["EXECUTIVE"],
        DEV_AUTH_PERMISSIONS=[],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
        TENANT_SCOPE_ENFORCEMENT=True,
    )
    @patch("replenishment.views.workflow_store.list_record_headers", return_value=[])
    def test_needs_list_list_does_not_narrow_read_all_context_with_requested_tenant(
        self,
        mock_list_record_headers,
    ) -> None:
        context = TenantContext(
            requested_tenant_id=1,
            active_tenant_id=1,
            active_tenant_code="ODPEM-NEOC",
            active_tenant_type="NATIONAL",
            memberships=(),
            can_read_all_tenants=True,
            can_act_cross_tenant=False,
        )

        with patch("replenishment.views._tenant_context", return_value=context):
            response = self.client.get("/api/v1/replenishment/needs-list/?tenant_id=1")

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(mock_list_record_headers.call_args.kwargs.get("allowed_warehouse_ids"))

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="tenant-reader",
        DEV_AUTH_ROLES=["LOGISTICS"],
        DEV_AUTH_PERMISSIONS=[],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
        TENANT_SCOPE_ENFORCEMENT=True,
    )
    @patch("replenishment.views.workflow_store.list_record_headers", return_value=[])
    @patch("replenishment.views.data_access.get_warehouse_ids_for_tenants", return_value={11})
    def test_needs_list_list_keeps_active_tenant_scope_when_requested_tenant_is_out_of_scope(
        self,
        mock_get_warehouse_ids_for_tenants,
        mock_list_record_headers,
    ) -> None:
        context = TenantContext(
            requested_tenant_id=2,
            active_tenant_id=1,
            active_tenant_code="AGENCY_A",
            active_tenant_type="AGENCY",
            memberships=(
                TenantMembership(
                    tenant_id=1,
                    tenant_code="AGENCY_A",
                    tenant_name="Agency A",
                    tenant_type="AGENCY",
                    is_primary=True,
                    access_level="WRITE",
                ),
            ),
            can_read_all_tenants=False,
            can_act_cross_tenant=False,
        )

        with patch("replenishment.views._tenant_context", return_value=context):
            response = self.client.get("/api/v1/replenishment/needs-list/?tenant_id=2")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"needs_lists": [], "count": 0})
        mock_get_warehouse_ids_for_tenants.assert_called_once_with({1})
        self.assertEqual(
            mock_list_record_headers.call_args.kwargs.get("allowed_warehouse_ids"),
            {11},
        )

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
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
    def test_needs_list_list_does_not_hydrate_execution_payload_per_row(
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
            self.client.post(
                "/api/v1/replenishment/needs-list/draft",
                self._draft_payload(),
                format="json",
            )

            with patch(
                "replenishment.views._execution_payload_for_record",
                side_effect=AssertionError("list endpoint should not hydrate execution payload"),
            ):
                response = self.client.get(
                    "/api/v1/replenishment/needs-list/?mine=true&include_closed=false"
                )

        self.assertEqual(response.status_code, 200)
        self.assertIn("needs_lists", response.json())

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
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
    def test_owner_scoped_visibility_ignores_updated_by_for_modified_records(
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
                DEV_AUTH_ROLES=["LOGISTICS"],
                DEV_AUTH_PERMISSIONS=[],
            ):
                draft = self.client.post(
                    "/api/v1/replenishment/needs-list/draft",
                    self._draft_payload(),
                    format="json",
                ).json()
                submit_response = self.client.post(
                    f"/api/v1/replenishment/needs-list/{draft['needs_list_id']}/submit",
                    {},
                    format="json",
                )
                self.assertEqual(submit_response.status_code, 200)

            returned = self.client.post(
                f"/api/v1/replenishment/needs-list/{draft['needs_list_id']}/return",
                {"reason_code": "DATA_QUALITY", "reason": "Data mismatch"},
                format="json",
            )
            self.assertEqual(returned.status_code, 200)
            self.assertEqual(returned.json().get("status"), "MODIFIED")

            mine_only = self.client.get(
                "/api/v1/replenishment/needs-list/?mine=true&include_closed=false"
            )
            my_submissions = self.client.get(
                "/api/v1/replenishment/needs-list/my-submissions/?page=1&page_size=20"
            )

        self.assertEqual(mine_only.status_code, 200)
        self.assertEqual(my_submissions.status_code, 200)

        mine_ids = [row.get("needs_list_id") for row in mine_only.json().get("needs_lists", [])]
        my_submission_ids = [row.get("id") for row in my_submissions.json().get("results", [])]
        self.assertNotIn(draft.get("needs_list_id"), mine_ids)
        self.assertNotIn(draft.get("needs_list_id"), my_submission_ids)

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
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
        TEST_DEV_AUTH_ENABLED=True,
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
    def test_my_submissions_paginates_before_record_hydration(
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
            for warehouse_id in (1, 2, 3):
                self.client.post(
                    "/api/v1/replenishment/needs-list/draft",
                    {**self._draft_payload(), "warehouse_id": warehouse_id},
                    format="json",
                )

            with patch(
                "replenishment.views.workflow_store.get_records_by_ids",
                wraps=workflow_store.get_records_by_ids,
            ) as mock_get_records_by_ids:
                response = self.client.get(
                    "/api/v1/replenishment/needs-list/my-submissions/?page=1&page_size=1"
                )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body.get("count"), 3)
        self.assertEqual(len(body.get("results", [])), 1)
        hydrated_ids = list(mock_get_records_by_ids.call_args.args[0])
        self.assertEqual(len(hydrated_ids), 1)
        self.assertEqual(body["results"][0].get("id"), hydrated_ids[0])
    
    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
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
    def test_my_submissions_requests_bounded_header_page(
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
            for warehouse_id in (1, 2, 3):
                self.client.post(
                    "/api/v1/replenishment/needs-list/draft",
                    {**self._draft_payload(), "warehouse_id": warehouse_id},
                    format="json",
                )

            with patch(
                "replenishment.views.workflow_store.list_record_headers",
                side_effect=AssertionError("my-submissions should not use the full header list helper"),
            ), patch(
                "replenishment.views.workflow_store.list_record_headers_page",
                wraps=workflow_store.list_record_headers_page,
            ) as mock_list_record_headers_page:
                response = self.client.get(
                    "/api/v1/replenishment/needs-list/my-submissions/?page=2&page_size=1"
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get("count"), 3)
        self.assertEqual(len(response.json().get("results", [])), 1)
        self.assertEqual(mock_list_record_headers_page.call_args.kwargs.get("offset"), 1)
        self.assertEqual(mock_list_record_headers_page.call_args.kwargs.get("limit"), 1)

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="neoc-reader",
        DEV_AUTH_ROLES=["EXECUTIVE"],
        DEV_AUTH_PERMISSIONS=[],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
        TENANT_SCOPE_ENFORCEMENT=True,
    )
    @patch("replenishment.views.workflow_store.list_record_headers_page", return_value=([], 0))
    def test_my_submissions_does_not_narrow_read_all_context_with_requested_tenant(
        self,
        mock_list_record_headers_page,
    ) -> None:
        context = TenantContext(
            requested_tenant_id=1,
            active_tenant_id=1,
            active_tenant_code="ODPEM-NEOC",
            active_tenant_type="NATIONAL",
            memberships=(),
            can_read_all_tenants=True,
            can_act_cross_tenant=False,
        )

        with patch("replenishment.views._tenant_context", return_value=context):
            response = self.client.get(
                "/api/v1/replenishment/needs-list/my-submissions/?tenant_id=1&page=1&page_size=10"
            )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(mock_list_record_headers_page.call_args.kwargs.get("allowed_warehouse_ids"))

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="tenant-reader",
        DEV_AUTH_ROLES=["LOGISTICS"],
        DEV_AUTH_PERMISSIONS=[],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
        TENANT_SCOPE_ENFORCEMENT=True,
    )
    @patch("replenishment.views.workflow_store.list_record_headers_page", return_value=([], 0))
    @patch("replenishment.views.data_access.get_warehouse_ids_for_tenants", return_value={11})
    def test_my_submissions_keeps_active_tenant_scope_when_requested_tenant_is_out_of_scope(
        self,
        mock_get_warehouse_ids_for_tenants,
        mock_list_record_headers_page,
    ) -> None:
        context = TenantContext(
            requested_tenant_id=2,
            active_tenant_id=1,
            active_tenant_code="AGENCY_A",
            active_tenant_type="AGENCY",
            memberships=(
                TenantMembership(
                    tenant_id=1,
                    tenant_code="AGENCY_A",
                    tenant_name="Agency A",
                    tenant_type="AGENCY",
                    is_primary=True,
                    access_level="WRITE",
                ),
            ),
            can_read_all_tenants=False,
            can_act_cross_tenant=False,
        )

        with patch("replenishment.views._tenant_context", return_value=context):
            response = self.client.get(
                "/api/v1/replenishment/needs-list/my-submissions/?tenant_id=2&page=1&page_size=10"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"count": 0, "next": None, "previous": None, "results": []},
        )
        mock_get_warehouse_ids_for_tenants.assert_called_once_with({1})
        self.assertEqual(
            mock_list_record_headers_page.call_args.kwargs.get("allowed_warehouse_ids"),
            {11},
        )

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="submitter",
        DEV_AUTH_ROLES=["LOGISTICS"],
        DEV_AUTH_PERMISSIONS=[],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch("replenishment.views.workflow_store.store_enabled_or_raise")
    def test_my_submissions_rejects_invalid_pagination_params(
        self,
        _mock_store_enabled,
    ) -> None:
        response = self.client.get(
            "/api/v1/replenishment/needs-list/my-submissions/?page=abc&page_size=10"
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"errors": {"page": "Must be an integer."}})

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
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
    def test_my_submissions_does_not_hydrate_execution_payload_per_row(
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
            self.client.post(
                "/api/v1/replenishment/needs-list/draft",
                self._draft_payload(),
                format="json",
            )

            with patch(
                "replenishment.views._execution_payload_for_record",
                side_effect=AssertionError("summary endpoint should not hydrate execution payload"),
            ):
                response = self.client.get(
                    "/api/v1/replenishment/needs-list/my-submissions/?page=1&page_size=10"
                )

        self.assertEqual(response.status_code, 200)
        self.assertIn("results", response.json())

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="reviewer",
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
    def test_my_submissions_shows_submitted_from_others_but_hides_their_drafts(
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
            with override_settings(
                AUTH_ENABLED=False,
                DEV_AUTH_ENABLED=True,
                TEST_DEV_AUTH_ENABLED=True,
                DEV_AUTH_USER_ID="submitter",
                DEV_AUTH_ROLES=["LOGISTICS"],
                DEV_AUTH_PERMISSIONS=[],
                DEBUG=True,
                AUTH_USE_DB_RBAC=False,
            ):
                submitted = self.client.post(
                    "/api/v1/replenishment/needs-list/draft",
                    self._draft_payload(),
                    format="json",
                ).json()
                submit_response = self.client.post(
                    f"/api/v1/replenishment/needs-list/{submitted['needs_list_id']}/submit",
                    {},
                    format="json",
                )
                self.assertEqual(submit_response.status_code, 200)

                other_draft = self.client.post(
                    "/api/v1/replenishment/needs-list/draft",
                    {**self._draft_payload(), "phase": "SURGE"},
                    format="json",
                ).json()

            response = self.client.get(
                "/api/v1/replenishment/needs-list/my-submissions/?page=1&page_size=20"
            )

        self.assertEqual(response.status_code, 200)
        ids = [row.get("id") for row in response.json().get("results", [])]
        self.assertIn(submitted.get("needs_list_id"), ids)
        self.assertNotIn(other_draft.get("needs_list_id"), ids)

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="reviewer",
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
    def test_my_submissions_mine_true_forces_actor_only_filtering(
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
            with override_settings(
                AUTH_ENABLED=False,
                DEV_AUTH_ENABLED=True,
                TEST_DEV_AUTH_ENABLED=True,
                DEV_AUTH_USER_ID="submitter",
                DEV_AUTH_ROLES=["LOGISTICS"],
                DEV_AUTH_PERMISSIONS=[],
                DEBUG=True,
                AUTH_USE_DB_RBAC=False,
            ):
                submitted = self.client.post(
                    "/api/v1/replenishment/needs-list/draft",
                    self._draft_payload(),
                    format="json",
                ).json()
                submit_response = self.client.post(
                    f"/api/v1/replenishment/needs-list/{submitted['needs_list_id']}/submit",
                    {},
                    format="json",
                )
                self.assertEqual(submit_response.status_code, 200)

            own_draft = self.client.post(
                "/api/v1/replenishment/needs-list/draft",
                self._draft_payload(),
                format="json",
            ).json()

            global_response = self.client.get(
                "/api/v1/replenishment/needs-list/my-submissions/?page=1&page_size=20"
            )
            mine_response = self.client.get(
                "/api/v1/replenishment/needs-list/my-submissions/?mine=true&page=1&page_size=20"
            )

        self.assertEqual(global_response.status_code, 200)
        global_ids = [row.get("id") for row in global_response.json().get("results", [])]
        self.assertIn(submitted.get("needs_list_id"), global_ids)
        self.assertIn(own_draft.get("needs_list_id"), global_ids)

        self.assertEqual(mine_response.status_code, 200)
        mine_ids = [row.get("id") for row in mine_response.json().get("results", [])]
        self.assertIn(own_draft.get("needs_list_id"), mine_ids)
        self.assertNotIn(submitted.get("needs_list_id"), mine_ids)

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
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
    def test_my_submissions_pagination_links_use_absolute_urls(
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
            self.client.post(
                "/api/v1/replenishment/needs-list/draft",
                self._draft_payload(),
                format="json",
            )
            self.client.post(
                "/api/v1/replenishment/needs-list/draft",
                {**self._draft_payload(), "phase": "SURGE"},
                format="json",
            )

            page_one = self.client.get(
                "/api/v1/replenishment/needs-list/my-submissions/?page=1&page_size=1"
            )
            page_two = self.client.get(
                "/api/v1/replenishment/needs-list/my-submissions/?page=2&page_size=1"
            )

        self.assertEqual(page_one.status_code, 200)
        self.assertEqual(page_two.status_code, 200)

        next_url = page_one.json().get("next")
        previous_url = page_two.json().get("previous")

        self.assertIsNotNone(next_url)
        self.assertIn("http://testserver/api/v1/replenishment/needs-list/my-submissions/", str(next_url))
        self.assertIn("page=2", str(next_url))
        self.assertIsNone(page_one.json().get("previous"))

        self.assertIsNotNone(previous_url)
        self.assertIn("http://testserver/api/v1/replenishment/needs-list/my-submissions/", str(previous_url))
        self.assertIn("page=1", str(previous_url))

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
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
        TEST_DEV_AUTH_ENABLED=True,
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
        TEST_DEV_AUTH_ENABLED=True,
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
    def test_my_submissions_method_filter_uses_selected_method(
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
            draft_a = self.client.post(
                "/api/v1/replenishment/needs-list/draft",
                {**self._draft_payload(), "selected_method": "A"},
                format="json",
            ).json()
            draft_b = self.client.post(
                "/api/v1/replenishment/needs-list/draft",
                {**self._draft_payload(), "selected_method": "B"},
                format="json",
            ).json()

            filtered_b = self.client.get(
                "/api/v1/replenishment/needs-list/my-submissions/?method=B&page=1&page_size=10"
            )
            invalid = self.client.get(
                "/api/v1/replenishment/needs-list/my-submissions/?method=Z&page=1&page_size=10"
            )

        self.assertEqual(filtered_b.status_code, 200)
        rows = filtered_b.json().get("results", [])
        ids = [row.get("id") for row in rows]
        self.assertIn(draft_b.get("needs_list_id"), ids)
        self.assertNotIn(draft_a.get("needs_list_id"), ids)
        for row in rows:
            self.assertEqual(row.get("selected_method"), "B")

        self.assertEqual(invalid.status_code, 400)
        self.assertIn("method", invalid.json().get("errors", {}))

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
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
    def test_my_submissions_method_filter_falls_back_to_snapshot_method(
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
                {**self._draft_payload(), "selected_method": "C"},
                format="json",
            ).json()
            needs_list_id = draft.get("needs_list_id")
            self.assertIsNotNone(needs_list_id)

            record = workflow_store.get_record(needs_list_id)
            self.assertIsNotNone(record)
            if record is None:
                self.fail("Expected workflow record to exist")
            record["selected_method"] = None
            snapshot = record.get("snapshot")
            if not isinstance(snapshot, dict):
                snapshot = {}
                record["snapshot"] = snapshot
            snapshot["selected_method"] = "C"
            workflow_store.update_record(needs_list_id, record)

            filtered = self.client.get(
                "/api/v1/replenishment/needs-list/my-submissions/?method=C&page=1&page_size=10"
            )

        self.assertEqual(filtered.status_code, 200)
        rows = filtered.json().get("results", [])
        matched = next((row for row in rows if row.get("id") == needs_list_id), None)
        self.assertIsNotNone(matched)
        self.assertEqual((matched or {}).get("selected_method"), "C")

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
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
        TEST_DEV_AUTH_ENABLED=True,
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
        TEST_DEV_AUTH_ENABLED=True,
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
    def test_my_submissions_horizon_summary_falls_back_to_selected_method(
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
                {
                    **self._draft_payload(),
                    "selected_method": "C",
                },
                format="json",
            ).json()
            needs_list_id = draft["needs_list_id"]

            record = workflow_store.get_record(needs_list_id)
            self.assertIsNotNone(record)
            snapshot_items = (record or {}).get("snapshot", {}).get("items", [])
            self.assertTrue(snapshot_items)
            snapshot_items[0]["horizon"] = {
                "A": {"recommended_qty": 0},
                "B": {"recommended_qty": 0},
                "C": {"recommended_qty": 0},
            }
            snapshot_items[0]["horizon_a_qty"] = 0
            snapshot_items[0]["horizon_b_qty"] = 0
            snapshot_items[0]["horizon_c_qty"] = 0
            workflow_store.update_record(needs_list_id, record)

            response = self.client.get(
                "/api/v1/replenishment/needs-list/my-submissions/?page=1&page_size=10"
            )

        self.assertEqual(response.status_code, 200)
        summary = next(
            (
                row
                for row in response.json().get("results", [])
                if row.get("id") == needs_list_id
            ),
            None,
        )
        self.assertIsNotNone(summary)
        horizon_summary = (summary or {}).get("horizon_summary", {})
        self.assertEqual((horizon_summary.get("horizon_c") or {}).get("count"), 1)
        self.assertEqual((horizon_summary.get("horizon_a") or {}).get("count"), 0)

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
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
    def test_fulfillment_sources_horizon_falls_back_to_selected_method(
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
                {
                    **self._draft_payload(),
                    "selected_method": "C",
                },
                format="json",
            ).json()
            needs_list_id = draft["needs_list_id"]

            record = workflow_store.get_record(needs_list_id)
            self.assertIsNotNone(record)
            snapshot_items = (record or {}).get("snapshot", {}).get("items", [])
            self.assertTrue(snapshot_items)
            snapshot_items[0]["horizon"] = {
                "A": {"recommended_qty": 0},
                "B": {"recommended_qty": 0},
                "C": {"recommended_qty": 0},
            }
            snapshot_items[0]["horizon_a_qty"] = 0
            snapshot_items[0]["horizon_b_qty"] = 0
            snapshot_items[0]["horizon_c_qty"] = 0
            workflow_store.update_record(needs_list_id, record)

            response = self.client.get(
                f"/api/v1/replenishment/needs-list/{needs_list_id}/fulfillment-sources"
            )

        self.assertEqual(response.status_code, 200)
        lines = response.json().get("lines", [])
        self.assertTrue(lines)
        self.assertEqual(lines[0].get("horizon"), "C")

    def test_resolve_item_horizon_prefers_a_over_slower_horizons_without_fallback(self) -> None:
        from replenishment.views import _resolve_item_horizon

        item = {
            "horizon": {
                "A": {"recommended_qty": 10},
                "B": {"recommended_qty": 20},
                "C": {"recommended_qty": 30},
            }
        }

        self.assertEqual(_resolve_item_horizon(item), "A")

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
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
    def test_my_submissions_horizon_summary_prefers_selected_method_over_item_horizon(
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
                {
                    **self._draft_payload(),
                    "selected_method": "B",
                },
                format="json",
            ).json()
            needs_list_id = draft["needs_list_id"]

            record = workflow_store.get_record(needs_list_id)
            self.assertIsNotNone(record)
            snapshot_items = (record or {}).get("snapshot", {}).get("items", [])
            self.assertTrue(snapshot_items)
            snapshot_items[0]["horizon"] = {
                "A": {"recommended_qty": 10},
                "B": {"recommended_qty": 0},
                "C": {"recommended_qty": 0},
            }
            snapshot_items[0]["horizon_a_qty"] = 10
            snapshot_items[0]["horizon_b_qty"] = 0
            snapshot_items[0]["horizon_c_qty"] = 0
            workflow_store.update_record(needs_list_id, record)

            response = self.client.get(
                "/api/v1/replenishment/needs-list/my-submissions/?page=1&page_size=10"
            )

        self.assertEqual(response.status_code, 200)
        summary = next(
            (
                row
                for row in response.json().get("results", [])
                if row.get("id") == needs_list_id
            ),
            None,
        )
        self.assertIsNotNone(summary)
        horizon_summary = (summary or {}).get("horizon_summary", {})
        self.assertEqual((horizon_summary.get("horizon_b") or {}).get("count"), 1)
        self.assertEqual((horizon_summary.get("horizon_a") or {}).get("count"), 0)

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
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
    def test_fulfillment_sources_horizon_prefers_selected_method_over_item_horizon(
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
                {
                    **self._draft_payload(),
                    "selected_method": "B",
                },
                format="json",
            ).json()
            needs_list_id = draft["needs_list_id"]

            record = workflow_store.get_record(needs_list_id)
            self.assertIsNotNone(record)
            snapshot_items = (record or {}).get("snapshot", {}).get("items", [])
            self.assertTrue(snapshot_items)
            snapshot_items[0]["horizon"] = {
                "A": {"recommended_qty": 10},
                "B": {"recommended_qty": 0},
                "C": {"recommended_qty": 0},
            }
            snapshot_items[0]["horizon_a_qty"] = 10
            snapshot_items[0]["horizon_b_qty"] = 0
            snapshot_items[0]["horizon_c_qty"] = 0
            workflow_store.update_record(needs_list_id, record)

            response = self.client.get(
                f"/api/v1/replenishment/needs-list/{needs_list_id}/fulfillment-sources"
            )

        self.assertEqual(response.status_code, 200)
        lines = response.json().get("lines", [])
        self.assertTrue(lines)
        self.assertEqual(lines[0].get("horizon"), "B")

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
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
        TEST_DEV_AUTH_ENABLED=True,
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
    def test_new_draft_does_not_supersede_under_review_records(
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

            under_review_record = workflow_store.get_record(first_id)
            self.assertIsNotNone(under_review_record)
            under_review_record = dict(under_review_record or {})
            under_review_record["status"] = "UNDER_REVIEW"
            under_review_record["review_started_by"] = "approver"
            under_review_record["review_started_at"] = timezone.now().isoformat()
            workflow_store.update_record(first_id, under_review_record)

            second_draft = self.client.post(
                "/api/v1/replenishment/needs-list/draft",
                self._draft_payload(),
                format="json",
            )
            self.assertEqual(second_draft.status_code, 200)
            second_body = second_draft.json()

            first_after = self.client.get(f"/api/v1/replenishment/needs-list/{first_id}")
            self.assertEqual(first_after.status_code, 200)

            queue = self.client.get(
                "/api/v1/replenishment/needs-list/?status=UNDER_REVIEW"
            )

        self.assertEqual(first_after.json().get("status"), "UNDER_REVIEW")
        self.assertNotIn(first_id, second_body.get("supersedes_needs_list_ids", []))
        queue_ids = [row.get("needs_list_id") for row in queue.json().get("needs_lists", [])]
        self.assertIn(first_id, queue_ids)

    def test_create_draft_does_not_supersede_when_warehouse_ids_differ(self) -> None:
        with patch.dict(os.environ, {"NEEDS_WORKFLOW_DEV_STORE": "1"}):
            first = workflow_store.create_draft(
                {
                    "event_id": 1,
                    "warehouse_id": 1,
                    "warehouse_ids": [1, 2],
                    "phase": "BASELINE",
                },
                [],
                [],
                "submitter",
            )
            second = workflow_store.create_draft(
                {
                    "event_id": 1,
                    "warehouse_id": 1,
                    "warehouse_ids": [1],
                    "phase": "BASELINE",
                },
                [],
                [],
                "submitter",
            )
            first_after = workflow_store.get_record(first["needs_list_id"])

            self.assertIsNotNone(first_after)
            self.assertEqual(first_after.get("status"), "DRAFT")
            self.assertNotIn(first["needs_list_id"], second.get("supersedes_needs_list_ids", []))

    def test_create_draft_does_not_supersede_when_warehouse_ids_differ_with_no_warehouse_id(
        self,
    ) -> None:
        with patch.dict(os.environ, {"NEEDS_WORKFLOW_DEV_STORE": "1"}):
            first = workflow_store.create_draft(
                {
                    "event_id": 1,
                    "warehouse_id": None,
                    "warehouse_ids": [1, 2],
                    "phase": "BASELINE",
                },
                [],
                [],
                "submitter",
            )
            second = workflow_store.create_draft(
                {
                    "event_id": 1,
                    "warehouse_id": None,
                    "warehouse_ids": [1],
                    "phase": "BASELINE",
                },
                [],
                [],
                "submitter",
            )
            first_after = workflow_store.get_record(first["needs_list_id"])

            self.assertIsNotNone(first_after)
            self.assertEqual(first_after.get("status"), "DRAFT")
            self.assertNotIn(first["needs_list_id"], second.get("supersedes_needs_list_ids", []))

    def test_create_draft_treats_empty_and_none_warehouse_ids_as_same_scope(self) -> None:
        with patch.dict(os.environ, {"NEEDS_WORKFLOW_DEV_STORE": "1"}):
            first = workflow_store.create_draft(
                {
                    "event_id": 1,
                    "warehouse_id": None,
                    "warehouse_ids": None,
                    "phase": "BASELINE",
                },
                [],
                [],
                "submitter",
            )
            second = workflow_store.create_draft(
                {
                    "event_id": 1,
                    "warehouse_id": None,
                    "warehouse_ids": [],
                    "phase": "BASELINE",
                },
                [],
                [],
                "submitter",
            )
            first_after = workflow_store.get_record(first["needs_list_id"])

            self.assertIsNotNone(first_after)
            self.assertEqual(first_after.get("status"), "SUPERSEDED")
            self.assertEqual(first_after.get("superseded_by"), second.get("needs_list_id"))
            self.assertIn(first["needs_list_id"], second.get("supersedes_needs_list_ids", []))

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
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
            self.assertEqual(approve.status_code, 409)

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
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
                self.assertEqual(approve_denied.status_code, 409)

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
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
    def test_logistics_manager_can_approve_donation_method(
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
                {**self._draft_payload(), "selected_method": "B"},
                format="json",
            ).json()
            needs_list_id = draft["needs_list_id"]
            self.client.post(
                f"/api/v1/replenishment/needs-list/{needs_list_id}/submit",
                {},
                format="json",
            )

            with self.settings(DEV_AUTH_ROLES=["LOGISTICS"], DEV_AUTH_USER_ID="approver"):
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
        TEST_DEV_AUTH_ENABLED=True,
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
    def test_logistics_manager_cannot_approve_procurement_method(
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
                {**self._draft_payload(), "selected_method": "C"},
                format="json",
            ).json()
            needs_list_id = draft["needs_list_id"]
            self.client.post(
                f"/api/v1/replenishment/needs-list/{needs_list_id}/submit",
                {},
                format="json",
            )

            with self.settings(DEV_AUTH_ROLES=["LOGISTICS"], DEV_AUTH_USER_ID="approver"):
                approve = self.client.post(
                    f"/api/v1/replenishment/needs-list/{needs_list_id}/approve",
                    {},
                    format="json",
                )
                self.assertEqual(approve.status_code, 403)

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
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
    def test_logistics_manager_cannot_reject_procurement_method(
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
                {**self._draft_payload(), "selected_method": "C"},
                format="json",
            ).json()
            needs_list_id = draft["needs_list_id"]
            self.client.post(
                f"/api/v1/replenishment/needs-list/{needs_list_id}/submit",
                {},
                format="json",
            )

            with self.settings(DEV_AUTH_ROLES=["LOGISTICS"], DEV_AUTH_USER_ID="approver"):
                reject = self.client.post(
                    f"/api/v1/replenishment/needs-list/{needs_list_id}/reject",
                    {"reason": "Unauthorized for procurement approval flow"},
                    format="json",
                )
                self.assertEqual(reject.status_code, 403)

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
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
        TEST_DEV_AUTH_ENABLED=True,
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
        TEST_DEV_AUTH_ENABLED=True,
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
        TEST_DEV_AUTH_ENABLED=True,
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
        TEST_DEV_AUTH_ENABLED=True,
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
        TEST_DEV_AUTH_ENABLED=True,
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
                    HTTP_IDEMPOTENCY_KEY=f"dispatch-{needs_list_id}",
                )
                self.assertEqual(dispatched.status_code, 200)
                dispatch_without_key = self.client.post(
                    f"/api/v1/replenishment/needs-list/{needs_list_id}/mark-dispatched",
                    {},
                    format="json",
                )
                self.assertNotEqual(dispatch_without_key.status_code, 200)
                self.assertEqual(
                    str(workflow_store.get_record(needs_list_id).get("status") or "").upper(),
                    "DISPATCHED",
                )
                received = self.client.post(
                    f"/api/v1/replenishment/needs-list/{needs_list_id}/mark-received",
                    {},
                    format="json",
                    HTTP_IDEMPOTENCY_KEY=f"receive-{needs_list_id}",
                )
                self.assertEqual(received.status_code, 200)
                receive_without_key = self.client.post(
                    f"/api/v1/replenishment/needs-list/{needs_list_id}/mark-received",
                    {},
                    format="json",
                )
                self.assertNotEqual(receive_without_key.status_code, 200)
                self.assertEqual(
                    str(workflow_store.get_record(needs_list_id).get("status") or "").upper(),
                    "RECEIVED",
                )
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
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="executor",
        DEV_AUTH_ROLES=["LOGISTICS"],
        DEV_AUTH_PERMISSIONS=[],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch("replenishment.views.workflow_store.update_record")
    @patch("replenishment.views.workflow_store.transition_status")
    @patch("replenishment.views.workflow_store.get_record")
    @patch("replenishment.views.workflow_store.store_enabled_or_raise")
    def test_mark_completed_normalizes_fulfilled_status_to_completed(
        self,
        _mock_store_enabled,
        mock_get_record,
        mock_transition_status,
        mock_update_record,
    ) -> None:
        mock_get_record.return_value = {
            "needs_list_id": "NL-A",
            "status": "RECEIVED",
            "warehouse_id": 10,
            "received_at": "2026-04-10T12:00:00Z",
        }
        mock_transition_status.return_value = {
            "needs_list_id": "NL-A",
            "status": "FULFILLED",
            "warehouse_id": 10,
            "received_at": "2026-04-10T12:00:00Z",
            "completed_at": "2026-04-10T13:00:00Z",
        }

        response = self.client.post(
            "/api/v1/replenishment/needs-list/NL-A/mark-completed",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get("status"), "COMPLETED")
        self.assertEqual(response.json().get("completed_at"), "2026-04-10T13:00:00Z")
        mock_update_record.assert_called_once()

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
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
                    HTTP_IDEMPOTENCY_KEY=f"premature-receive-{needs_list_id}",
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
                    HTTP_IDEMPOTENCY_KEY=f"dispatch-{needs_list_id}",
                )
                self.assertEqual(dispatched.status_code, 200)
                self.assertIsNotNone(dispatched.json().get("dispatched_at"))

                dispatch_again = self.client.post(
                    f"/api/v1/replenishment/needs-list/{needs_list_id}/mark-dispatched",
                    {},
                    format="json",
                    HTTP_IDEMPOTENCY_KEY=f"dispatch-again-{needs_list_id}",
                )
                self.assertEqual(dispatch_again.status_code, 409)

                received = self.client.post(
                    f"/api/v1/replenishment/needs-list/{needs_list_id}/mark-received",
                    {},
                    format="json",
                    HTTP_IDEMPOTENCY_KEY=f"receive-{needs_list_id}",
                )
                self.assertEqual(received.status_code, 200)
                self.assertIsNotNone(received.json().get("received_at"))

                completed = self.client.post(
                    f"/api/v1/replenishment/needs-list/{needs_list_id}/mark-completed",
                    {},
                    format="json",
                )
                self.assertEqual(completed.status_code, 200)
                self.assertEqual(completed.json().get("status"), "COMPLETED")
                self.assertIsNotNone(completed.json().get("completed_at"))

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
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
        TEST_DEV_AUTH_ENABLED=True,
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
        TEST_DEV_AUTH_ENABLED=True,
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
                    HTTP_IDEMPOTENCY_KEY=f"dispatch-{needs_list_id_two}",
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
        TEST_DEV_AUTH_ENABLED=True,
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
    def test_iso_or_none_preserves_nulls(self) -> None:
        self.assertIsNone(workflow_store_db._iso_or_none(None))

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

    @patch("replenishment.workflow_store_db.data_access.get_event_name")
    @patch("replenishment.workflow_store_db.data_access.get_warehouse_name")
    @patch("replenishment.workflow_store_db.data_access.get_item_names")
    def test_create_draft_does_not_supersede_under_review_records(
        self,
        mock_item_names,
        mock_warehouse_name,
        mock_event_name,
    ) -> None:
        mock_item_names.return_value = ({9: {"name": "MEALS READY TO EAT", "code": "MRE-12"}}, [])
        mock_warehouse_name.return_value = "ODPEM MARCUS GARVEY WAREHOUSE (MG)"
        mock_event_name.return_value = "HURRICANE MELISSA"

        older = NeedsList.objects.create(
            needs_list_no="NL-1-2-20260216-002",
            event_id=1,
            warehouse_id=2,
            event_phase="BASELINE",
            calculation_dtime=timezone.now(),
            demand_window_hours=24,
            planning_window_hours=72,
            safety_factor=1.25,
            data_freshness_level="HIGH",
            status_code="UNDER_REVIEW",
            total_gap_qty=100,
            create_by_id="tester",
            update_by_id="approver",
            submitted_by="tester",
            submitted_at=timezone.now(),
            under_review_by="approver",
            under_review_at=timezone.now(),
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
        self.assertEqual(older.status_code, "UNDER_REVIEW")
        self.assertIsNone(older.superseded_by_id)
        self.assertNotIn(str(older.needs_list_id), record.get("supersedes_needs_list_ids", []))

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

    @patch("replenishment.workflow_store_db.data_access.get_event_names")
    @patch("replenishment.workflow_store_db.data_access.get_warehouse_names")
    @patch("replenishment.workflow_store_db.data_access.get_item_names")
    def test_get_records_by_ids_respects_base_queryset(
        self,
        mock_item_names,
        mock_warehouse_names,
        mock_event_names,
    ) -> None:
        mock_warehouse_names.return_value = ({2: "Warehouse 2"}, [])
        mock_event_names.return_value = ({1: "Event 1"}, [])
        mock_item_names.return_value = ({}, [])

        allowed = NeedsList.objects.create(
            needs_list_no="NL-1-2-20260216-020",
            event_id=1,
            warehouse_id=2,
            event_phase="BASELINE",
            calculation_dtime=timezone.now(),
            demand_window_hours=24,
            planning_window_hours=72,
            safety_factor=1.25,
            data_freshness_level="HIGH",
            status_code="PENDING_APPROVAL",
            total_gap_qty=10,
            create_by_id="tester",
            update_by_id="tester",
        )
        denied = NeedsList.objects.create(
            needs_list_no="NL-1-3-20260216-021",
            event_id=1,
            warehouse_id=3,
            event_phase="BASELINE",
            calculation_dtime=timezone.now(),
            demand_window_hours=24,
            planning_window_hours=72,
            safety_factor=1.25,
            data_freshness_level="HIGH",
            status_code="PENDING_APPROVAL",
            total_gap_qty=15,
            create_by_id="tester",
            update_by_id="tester",
        )

        records = workflow_store_db.get_records_by_ids(
            [allowed.needs_list_id, denied.needs_list_id],
            base_queryset=NeedsList.objects.filter(warehouse_id=2),
            include_audit_logs=False,
        )

        self.assertEqual(
            [record["needs_list_id"] for record in records],
            [str(allowed.needs_list_id)],
        )

    @patch("replenishment.workflow_store_db.data_access.get_event_names")
    @patch("replenishment.workflow_store_db.data_access.get_warehouse_names")
    @patch("replenishment.workflow_store_db.data_access.get_item_names")
    def test_get_records_by_ids_without_prefetched_audits_uses_db_fallback_for_review_fields(
        self,
        mock_item_names,
        mock_warehouse_names,
        mock_event_names,
    ) -> None:
        mock_warehouse_names.return_value = ({2: "Warehouse 2"}, [])
        mock_event_names.return_value = ({1: "Event 1"}, [])
        mock_item_names.return_value = ({9: {"name": "Water", "code": "WTR"}}, [])

        needs_list = NeedsList.objects.create(
            needs_list_no="NL-1-2-20260216-024",
            event_id=1,
            warehouse_id=2,
            event_phase="BASELINE",
            calculation_dtime=timezone.now(),
            demand_window_hours=24,
            planning_window_hours=72,
            safety_factor=1.25,
            data_freshness_level="HIGH",
            status_code="IN_PROGRESS",
            total_gap_qty=20,
            create_by_id="tester",
            update_by_id="tester",
        )
        item = NeedsListItem.objects.create(
            needs_list=needs_list,
            item_id=9,
            uom_code="EA",
            burn_rate=Decimal("1.00"),
            burn_rate_source="CALCULATED",
            available_stock=Decimal("5.00"),
            reserved_qty=Decimal("0.00"),
            inbound_transfer_qty=Decimal("0.00"),
            inbound_donation_qty=Decimal("0.00"),
            inbound_procurement_qty=Decimal("0.00"),
            required_qty=Decimal("10.00"),
            coverage_qty=Decimal("5.00"),
            gap_qty=Decimal("5.00"),
            time_to_stockout_hours=Decimal("5.00"),
            severity_level="WARNING",
            horizon_a_qty=Decimal("1.00"),
            horizon_b_qty=Decimal("2.00"),
            horizon_c_qty=Decimal("2.00"),
            create_by_id="tester",
            update_by_id="tester",
        )
        NeedsListAudit.objects.create(
            needs_list=needs_list,
            action_type="STATUS_CHANGED",
            field_name="status_code",
            old_value="PENDING_APPROVAL",
            new_value="IN_PROGRESS",
            notes_text="Preparation started.",
            actor_user_id="reviewer",
        )
        NeedsListAudit.objects.create(
            needs_list=needs_list,
            needs_list_item=item,
            action_type="COMMENT_ADDED",
            notes_text="Need more detail.",
            actor_user_id="reviewer",
        )

        records = workflow_store_db.get_records_by_ids(
            [needs_list.needs_list_id],
            base_queryset=NeedsList.objects.filter(needs_list_id=needs_list.needs_list_id),
            include_audit_logs=False,
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["prep_started_by"], "reviewer")
        self.assertIsNotNone(records[0]["prep_started_at"])
        self.assertEqual(
            records[0]["line_review_notes"]["9"]["comment"],
            "Need more detail.",
        )

    @patch("replenishment.workflow_store_db.data_access.get_event_names")
    @patch("replenishment.workflow_store_db.data_access.get_warehouse_names")
    @patch("replenishment.workflow_store_db.data_access.get_item_names")
    def test_list_records_respects_allowed_warehouse_ids(
        self,
        mock_item_names,
        mock_warehouse_names,
        mock_event_names,
    ) -> None:
        mock_warehouse_names.return_value = ({2: "Warehouse 2"}, [])
        mock_event_names.return_value = ({1: "Event 1"}, [])
        mock_item_names.return_value = ({}, [])

        allowed = NeedsList.objects.create(
            needs_list_no="NL-1-2-20260216-022",
            event_id=1,
            warehouse_id=2,
            event_phase="BASELINE",
            calculation_dtime=timezone.now(),
            demand_window_hours=24,
            planning_window_hours=72,
            safety_factor=1.25,
            data_freshness_level="HIGH",
            status_code="PENDING_APPROVAL",
            total_gap_qty=20,
            create_by_id="tester",
            update_by_id="tester",
        )
        NeedsList.objects.create(
            needs_list_no="NL-1-3-20260216-023",
            event_id=1,
            warehouse_id=3,
            event_phase="BASELINE",
            calculation_dtime=timezone.now(),
            demand_window_hours=24,
            planning_window_hours=72,
            safety_factor=1.25,
            data_freshness_level="HIGH",
            status_code="PENDING_APPROVAL",
            total_gap_qty=25,
            create_by_id="tester",
            update_by_id="tester",
        )

        records = workflow_store_db.list_records(
            ["SUBMITTED"],
            allowed_warehouse_ids=[2],
            include_audit_logs=False,
        )

        self.assertEqual(
            [record["needs_list_id"] for record in records],
            [str(allowed.needs_list_id)],
        )

    @patch("replenishment.workflow_store_db.data_access.get_event_names")
    @patch("replenishment.workflow_store_db.data_access.get_warehouse_names")
    def test_list_record_headers_page_method_filter_falls_back_to_legacy_notes_text(
        self,
        mock_warehouse_names,
        mock_event_names,
    ) -> None:
        mock_warehouse_names.return_value = ({2: "ODPEM MARCUS GARVEY WAREHOUSE (MG)"}, [])
        mock_event_names.return_value = ({1: "HURRICANE MELISSA"}, [])

        matching = NeedsList.objects.create(
            needs_list_no="NL-1-2-20260216-010",
            event_id=1,
            warehouse_id=2,
            event_phase="BASELINE",
            calculation_dtime=timezone.now(),
            demand_window_hours=24,
            planning_window_hours=72,
            safety_factor=1.25,
            data_freshness_level="HIGH",
            status_code="PENDING_APPROVAL",
            total_gap_qty=25,
            notes_text='{"selected_method":"B"}',
            create_by_id="tester",
            update_by_id="tester",
        )
        NeedsList.objects.create(
            needs_list_no="NL-1-2-20260216-011",
            event_id=1,
            warehouse_id=2,
            event_phase="BASELINE",
            calculation_dtime=timezone.now(),
            demand_window_hours=24,
            planning_window_hours=72,
            safety_factor=1.25,
            data_freshness_level="HIGH",
            status_code="PENDING_APPROVAL",
            total_gap_qty=30,
            notes_text='{"selected_method":"A"}',
            create_by_id="tester",
            update_by_id="tester",
        )

        with patch(
            "replenishment.workflow_store_db._ensure_workflow_metadata_table"
        ) as mock_ensure_workflow_metadata_table:
            headers, total_count = workflow_store_db.list_record_headers_page(
                method_filter="B",
                offset=0,
                limit=10,
            )
            mock_ensure_workflow_metadata_table.assert_not_called()

        self.assertEqual(total_count, 1)
        self.assertEqual(len(headers), 1)
        self.assertEqual(headers[0]["needs_list_id"], str(matching.needs_list_id))
        self.assertEqual(headers[0]["selected_method"], "B")


class StockStateFileLockTests(SimpleTestCase):
    # These are intentional white-box tests that assert internal lock helpers
    # around stock-state persistence/loading. Refactors of private helpers may
    # require updating this test class even if public API behavior is unchanged.
    def _make_test_dir(self) -> Path:
        base_dir = Path(__file__).resolve().parents[1] / "runtime" / "stock_state_lock_tests"
        test_dir = base_dir / uuid.uuid4().hex
        test_dir.mkdir(parents=True, exist_ok=True)
        return test_dir

    def test_persist_snapshot_uses_exclusive_file_lock(self) -> None:
        from replenishment import views

        test_dir = self._make_test_dir()
        try:
            store_path = test_dir / "stock_state_cache.json"
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
        finally:
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_load_snapshot_uses_shared_file_lock(self) -> None:
        from replenishment import views

        test_dir = self._make_test_dir()
        try:
            store_path = test_dir / "stock_state_cache.json"
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
        finally:
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_windows_sidecar_lock_failure_does_not_fallback_unlocked(self) -> None:
        from replenishment import views

        test_dir = self._make_test_dir()
        try:
            store_path = test_dir / "stock_state_cache.json"
            with override_settings(NEEDS_STOCK_STATE_STORE_PATH=str(store_path)):
                with patch("replenishment.views.fcntl", None), patch(
                    "replenishment.views._acquire_stock_state_file_lock",
                    side_effect=OSError("lock busy"),
                ), patch("replenishment.views._fallback_stock_state_file") as mock_fallback:
                    with self.assertRaises(OSError):
                        with views._locked_stock_state_file(exclusive=True):
                            pass

                mock_fallback.assert_not_called()
        finally:
            shutil.rmtree(test_dir, ignore_errors=True)


class ProcurementPermissionApiTests(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="exec-user",
        DEV_AUTH_ROLES=["EXECUTIVE"],
        DEV_AUTH_PERMISSIONS=["replenishment.procurement.view"],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch("replenishment.views.procurement_service.list_procurements", return_value=([], 0))
    def test_procurement_create_requires_create_permission(self, _mock_list_procurements) -> None:
        get_response = self.client.get("/api/v1/replenishment/procurement/")
        self.assertEqual(get_response.status_code, 200)

        post_response = self.client.post(
            "/api/v1/replenishment/procurement/",
            {"needs_list_id": "NL-1"},
            format="json",
        )
        self.assertEqual(post_response.status_code, 403)

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="exec-user",
        DEV_AUTH_ROLES=["EXECUTIVE"],
        DEV_AUTH_PERMISSIONS=["replenishment.procurement.view"],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch("replenishment.views.procurement_service.list_procurements", return_value=([], 0))
    def test_procurement_list_opt_in_item_payload_passthrough(
        self,
        mock_list_procurements,
    ) -> None:
        default_response = self.client.get("/api/v1/replenishment/procurement/")
        self.assertEqual(default_response.status_code, 200)
        mock_list_procurements.assert_called_with(
            None,
            allowed_warehouse_ids=None,
            include_items=False,
            offset=0,
            limit=100,
        )

        include_items_response = self.client.get(
            "/api/v1/replenishment/procurement/?needs_list_id=NL-1&include_items=true"
        )
        self.assertEqual(include_items_response.status_code, 200)
        self.assertEqual(mock_list_procurements.call_args_list[-1].args, ({"needs_list_id": "NL-1"},))
        self.assertEqual(
            mock_list_procurements.call_args_list[-1].kwargs,
            {
                "allowed_warehouse_ids": None,
                "include_items": True,
                "offset": 0,
                "limit": 100,
            },
        )

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="exec-user",
        DEV_AUTH_ROLES=["EXECUTIVE"],
        DEV_AUTH_PERMISSIONS=["replenishment.procurement.view"],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch(
        "replenishment.views.procurement_service.list_procurements",
        return_value=([{"procurement_id": 99, "items": []}], 3),
    )
    def test_procurement_list_returns_bounded_paginated_contract(
        self,
        mock_list_procurements,
    ) -> None:
        response = self.client.get(
            "/api/v1/replenishment/procurement/?page=2&page_size=1"
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body.get("count"), 3)
        self.assertEqual(len(body.get("procurements", [])), 1)
        self.assertIn("page=3", str(body.get("next")))
        self.assertIn("page=1", str(body.get("previous")))
        mock_list_procurements.assert_called_with(
            None,
            allowed_warehouse_ids=None,
            include_items=False,
            offset=1,
            limit=1,
        )

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="exec-user",
        DEV_AUTH_ROLES=["EXECUTIVE"],
        DEV_AUTH_PERMISSIONS=["replenishment.procurement.view"],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch("replenishment.views.procurement_service.list_procurements")
    def test_procurement_list_rejects_invalid_pagination_params(
        self,
        mock_list_procurements,
    ) -> None:
        response = self.client.get("/api/v1/replenishment/procurement/?page=abc")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"errors": {"page": "Must be an integer."}})
        mock_list_procurements.assert_not_called()

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="exec-user",
        DEV_AUTH_ROLES=["EXECUTIVE"],
        DEV_AUTH_PERMISSIONS=["replenishment.procurement.view"],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch("replenishment.views.procurement_service.list_procurements")
    def test_procurement_list_rejects_invalid_include_items_flag(
        self,
        mock_list_procurements,
    ) -> None:
        response = self.client.get(
            "/api/v1/replenishment/procurement/?include_items=not-a-bool"
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {"errors": {"include_items": "Must be a boolean."}},
        )
        mock_list_procurements.assert_not_called()

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="exec-user",
        DEV_AUTH_ROLES=["EXECUTIVE"],
        DEV_AUTH_PERMISSIONS=["replenishment.procurement.view"],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch("replenishment.views.procurement_service.list_procurements")
    def test_procurement_list_rejects_invalid_filters(
        self,
        mock_list_procurements,
    ) -> None:
        response = self.client.get(
            "/api/v1/replenishment/procurement/?warehouse_id=abc&status=NOT_A_STATUS"
        )

        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body["errors"]["warehouse_id"], "Must be an integer.")
        self.assertIn("status", body["errors"])
        mock_list_procurements.assert_not_called()

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="exec-user",
        DEV_AUTH_ROLES=["EXECUTIVE"],
        DEV_AUTH_PERMISSIONS=["replenishment.procurement.view"],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
        TENANT_SCOPE_ENFORCEMENT=True,
    )
    @patch("replenishment.views.procurement_service.list_procurements", return_value=([], 0))
    def test_procurement_list_uses_active_tenant_scope_when_requested_tenant_is_out_of_scope(
        self,
        mock_list_procurements,
    ) -> None:
        context = TenantContext(
            requested_tenant_id=2,
            active_tenant_id=1,
            active_tenant_code="AGENCY_A",
            active_tenant_type="AGENCY",
            memberships=(
                TenantMembership(
                    tenant_id=1,
                    tenant_code="AGENCY_A",
                    tenant_name="Agency A",
                    tenant_type="AGENCY",
                    is_primary=True,
                    access_level="WRITE",
                ),
            ),
            can_read_all_tenants=False,
            can_act_cross_tenant=False,
        )

        with patch("replenishment.views._tenant_context", return_value=context), patch(
            "replenishment.views.data_access.get_warehouse_ids_for_tenants",
            return_value={11},
        ) as mock_get_warehouse_ids_for_tenants:
            response = self.client.get("/api/v1/replenishment/procurement/?tenant_id=2")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"count": 0, "next": None, "previous": None, "procurements": []},
        )
        mock_list_procurements.assert_called_once_with(
            None,
            allowed_warehouse_ids={11},
            include_items=False,
            offset=0,
            limit=100,
        )
        mock_get_warehouse_ids_for_tenants.assert_called_once_with({1})

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="exec-user",
        DEV_AUTH_ROLES=["EXECUTIVE"],
        DEV_AUTH_PERMISSIONS=["replenishment.procurement.view"],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch("replenishment.views.procurement_service.list_suppliers", return_value=[])
    def test_supplier_create_requires_create_permission(self, _mock_list_suppliers) -> None:
        get_response = self.client.get("/api/v1/replenishment/suppliers/")
        self.assertEqual(get_response.status_code, 200)

        post_response = self.client.post(
            "/api/v1/replenishment/suppliers/",
            {"supplier_code": "SUP-1", "supplier_name": "Supplier 1"},
            format="json",
        )
        self.assertEqual(post_response.status_code, 403)

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="submitter-1",
        DEV_AUTH_ROLES=["EXECUTIVE"],
        DEV_AUTH_PERMISSIONS=["replenishment.procurement.approve"],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch("replenishment.views.procurement_service.approve_procurement")
    @patch("replenishment.views.Procurement.objects.get")
    def test_procurement_approve_blocks_submitter_self_approval(
        self,
        mock_get_procurement,
        mock_approve_procurement,
    ) -> None:
        mock_get_procurement.return_value = MagicMock(
            create_by_id="submitter-1",
            status_code="PENDING_APPROVAL",
        )

        response = self.client.post(
            "/api/v1/replenishment/procurement/123/approve",
            {"notes": "Looks good"},
            format="json",
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json(),
            {"errors": {"approval": "Approver must be different from submitter."}},
        )
        mock_get_procurement.assert_called_once_with(procurement_id=123)
        mock_approve_procurement.assert_not_called()

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="submitter-2",
        DEV_AUTH_ROLES=["EXECUTIVE"],
        DEV_AUTH_PERMISSIONS=["replenishment.procurement.approve"],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch("replenishment.views.procurement_service.approve_procurement")
    @patch("replenishment.views.Procurement.objects.get")
    def test_procurement_approve_blocks_actual_submitter_when_creator_differs(
        self,
        mock_get_procurement,
        mock_approve_procurement,
    ) -> None:
        mock_get_procurement.return_value = MagicMock(
            create_by_id="creator-1",
            update_by_id="submitter-2",
            status_code="PENDING_APPROVAL",
        )

        response = self.client.post(
            "/api/v1/replenishment/procurement/123/approve",
            {"notes": "Looks good"},
            format="json",
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json(),
            {"errors": {"approval": "Approver must be different from submitter."}},
        )
        mock_get_procurement.assert_called_once_with(procurement_id=123)
        mock_approve_procurement.assert_not_called()

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="approver-2",
        DEV_AUTH_ROLES=["EXECUTIVE"],
        DEV_AUTH_PERMISSIONS=["replenishment.procurement.approve"],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch("replenishment.views.procurement_service.approve_procurement")
    @patch("replenishment.views.Procurement.objects.get")
    def test_procurement_approve_blocks_when_submitter_is_missing(
        self,
        mock_get_procurement,
        mock_approve_procurement,
    ) -> None:
        mock_get_procurement.return_value = MagicMock(
            create_by_id=None,
            update_by_id=None,
            status_code="PENDING_APPROVAL",
        )

        response = self.client.post(
            "/api/v1/replenishment/procurement/123/approve",
            {"notes": "Looks good"},
            format="json",
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json(),
            {"errors": {"approval": "Approver must be different from submitter."}},
        )
        mock_get_procurement.assert_called_once_with(procurement_id=123)
        mock_approve_procurement.assert_not_called()

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="approver-1",
        DEV_AUTH_ROLES=["EXECUTIVE"],
        DEV_AUTH_PERMISSIONS=["replenishment.procurement.reject"],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch("replenishment.views.procurement_service.get_procurement")
    @patch("replenishment.views.procurement_service.reject_procurement")
    def test_procurement_reject_requires_non_empty_reason(
        self,
        mock_reject_procurement,
        mock_get_procurement,
    ) -> None:
        response = self.client.post(
            "/api/v1/replenishment/procurement/123/reject",
            {"reason": None},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"errors": {"reason": "Reason is required."}})
        mock_get_procurement.assert_not_called()
        mock_reject_procurement.assert_not_called()

    @override_settings(
        AUTH_ENABLED=False,
        DEV_AUTH_ENABLED=True,
        TEST_DEV_AUTH_ENABLED=True,
        DEV_AUTH_USER_ID="logistics-1",
        DEV_AUTH_ROLES=["LOGISTICS"],
        DEV_AUTH_PERMISSIONS=["replenishment.procurement.cancel"],
        DEBUG=True,
        AUTH_USE_DB_RBAC=False,
    )
    @patch("replenishment.views.procurement_service.get_procurement")
    @patch("replenishment.views.procurement_service.cancel_procurement")
    def test_procurement_cancel_requires_non_empty_reason(
        self,
        mock_cancel_procurement,
        mock_get_procurement,
    ) -> None:
        response = self.client.post(
            "/api/v1/replenishment/procurement/123/cancel",
            {"reason": "   "},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"errors": {"reason": "Reason is required."}})
        mock_get_procurement.assert_not_called()
        mock_cancel_procurement.assert_not_called()


class ProcurementDraftUpdateTests(TestCase):
    def test_update_procurement_draft_clears_line_total_when_price_removed(self) -> None:
        proc = Procurement.objects.create(
            procurement_no="PROC-TEST-001",
            event_id=1,
            target_warehouse_id=1,
            procurement_method="SINGLE_SOURCE",
            status_code="DRAFT",
            create_by_id="tester",
            update_by_id="tester",
        )
        line = ProcurementItem.objects.create(
            procurement=proc,
            item_id=100,
            ordered_qty=Decimal("5.00"),
            unit_price=Decimal("2.00"),
            line_total=Decimal("10.00"),
            uom_code="EA",
            create_by_id="tester",
            update_by_id="tester",
        )

        procurement_service.update_procurement_draft(
            proc.procurement_id,
            {
                "items": [
                    {
                        "procurement_item_id": line.procurement_item_id,
                        "unit_price": None,
                    }
                ]
            },
            actor_id="editor",
        )

        line.refresh_from_db()
        proc.refresh_from_db()

        self.assertIsNone(line.unit_price)
        self.assertIsNone(line.line_total)
        self.assertEqual(proc.total_value, Decimal("0.00"))

    def test_update_procurement_draft_deletes_removed_items(self) -> None:
        proc = Procurement.objects.create(
            procurement_no="PROC-TEST-002",
            event_id=1,
            target_warehouse_id=1,
            procurement_method="SINGLE_SOURCE",
            status_code="DRAFT",
            create_by_id="tester",
            update_by_id="tester",
        )
        line_one = ProcurementItem.objects.create(
            procurement=proc,
            item_id=100,
            ordered_qty=Decimal("5.00"),
            unit_price=Decimal("2.00"),
            line_total=Decimal("10.00"),
            uom_code="EA",
            create_by_id="tester",
            update_by_id="tester",
        )
        line_two = ProcurementItem.objects.create(
            procurement=proc,
            item_id=200,
            ordered_qty=Decimal("1.00"),
            unit_price=Decimal("3.00"),
            line_total=Decimal("3.00"),
            uom_code="EA",
            create_by_id="tester",
            update_by_id="tester",
        )

        procurement_service.update_procurement_draft(
            proc.procurement_id,
            {
                "deleted_procurement_item_ids": [line_two.procurement_item_id],
                "items": [
                    {
                        "procurement_item_id": line_one.procurement_item_id,
                        "ordered_qty": 5,
                        "unit_price": 2,
                    }
                ],
            },
            actor_id="editor",
        )

        proc.refresh_from_db()
        remaining_item_ids = set(
            ProcurementItem.objects.filter(procurement=proc).values_list(
                "procurement_item_id", flat=True
            )
        )
        self.assertIn(line_one.procurement_item_id, remaining_item_ids)
        self.assertNotIn(line_two.procurement_item_id, remaining_item_ids)
        self.assertEqual(proc.total_value, Decimal("10.00"))

    def test_compute_total_value_recalculates_line_totals(self) -> None:
        proc = Procurement.objects.create(
            procurement_no="PROC-TEST-003",
            event_id=1,
            target_warehouse_id=1,
            procurement_method="SINGLE_SOURCE",
            status_code="DRAFT",
            create_by_id="tester",
            update_by_id="tester",
        )
        line = ProcurementItem.objects.create(
            procurement=proc,
            item_id=300,
            ordered_qty=Decimal("2.00"),
            unit_price=Decimal("5.00"),
            # Seed an incorrect persisted value to ensure recomputation happens.
            line_total=Decimal("99.00"),
            uom_code="EA",
            create_by_id="tester",
            update_by_id="tester",
        )

        total = procurement_service._compute_total_value(proc)
        line.refresh_from_db()

        self.assertEqual(total, Decimal("10.00"))
        self.assertEqual(line.line_total, Decimal("10.00"))

    def test_update_procurement_draft_rejects_invalid_ordered_qty_for_existing_line(self) -> None:
        proc = Procurement.objects.create(
            procurement_no="PROC-TEST-004",
            event_id=1,
            target_warehouse_id=1,
            procurement_method="SINGLE_SOURCE",
            status_code="DRAFT",
            create_by_id="tester",
            update_by_id="tester",
        )
        line = ProcurementItem.objects.create(
            procurement=proc,
            item_id=100,
            ordered_qty=Decimal("5.00"),
            unit_price=Decimal("2.00"),
            line_total=Decimal("10.00"),
            uom_code="EA",
            create_by_id="tester",
            update_by_id="tester",
        )

        with self.assertRaises(procurement_service.ProcurementError) as ctx:
            procurement_service.update_procurement_draft(
                proc.procurement_id,
                {
                    "items": [
                        {
                            "procurement_item_id": line.procurement_item_id,
                            "ordered_qty": {"qty": "bad"},
                        }
                    ]
                },
                actor_id="editor",
            )

        self.assertEqual(ctx.exception.code, "invalid_ordered_qty")
        self.assertIn(str(line.procurement_item_id), ctx.exception.message)

    def test_update_procurement_draft_rejects_invalid_unit_price_for_new_line(self) -> None:
        proc = Procurement.objects.create(
            procurement_no="PROC-TEST-005",
            event_id=1,
            target_warehouse_id=1,
            procurement_method="SINGLE_SOURCE",
            status_code="DRAFT",
            create_by_id="tester",
            update_by_id="tester",
        )

        with self.assertRaises(procurement_service.ProcurementError) as ctx:
            procurement_service.update_procurement_draft(
                proc.procurement_id,
                {
                    "items": [
                        {
                            "item_id": 200,
                            "ordered_qty": 2,
                            "unit_price": {"value": "bad"},
                        }
                    ]
                },
                actor_id="editor",
            )

        self.assertEqual(ctx.exception.code, "invalid_unit_price")
        self.assertIn("item 200", ctx.exception.message)
        self.assertFalse(
            ProcurementItem.objects.filter(procurement=proc, item_id=200).exists()
        )

    @patch(
        "replenishment.services.procurement._compute_total_value",
        return_value=Decimal("0.00"),
    )
    def test_update_procurement_draft_zero_unit_price_sets_line_total_for_new_line(
        self, _mock_total
    ) -> None:
        proc = Procurement.objects.create(
            procurement_no="PROC-TEST-006",
            event_id=1,
            target_warehouse_id=1,
            procurement_method="SINGLE_SOURCE",
            status_code="DRAFT",
            create_by_id="tester",
            update_by_id="tester",
        )

        procurement_service.update_procurement_draft(
            proc.procurement_id,
            {
                "items": [
                    {
                        "item_id": 300,
                        "ordered_qty": 5,
                        "unit_price": 0,
                    }
                ]
            },
            actor_id="editor",
        )

        line = ProcurementItem.objects.get(procurement=proc, item_id=300)
        self.assertEqual(line.unit_price, Decimal("0.00"))
        self.assertEqual(line.line_total, Decimal("0.00"))


class ProcurementListPerformanceTests(TestCase):
    def _create_procurement(
        self,
        procurement_no: str,
        *,
        item_ids: list[int],
        warehouse_id: int = 1,
    ) -> Procurement:
        procurement = Procurement.objects.create(
            procurement_no=procurement_no,
            event_id=1,
            target_warehouse_id=warehouse_id,
            procurement_method="SINGLE_SOURCE",
            status_code="DRAFT",
            create_by_id="tester",
            update_by_id="tester",
        )
        for offset, item_id in enumerate(item_ids, start=1):
            ProcurementItem.objects.create(
                procurement=procurement,
                item_id=item_id,
                ordered_qty=Decimal(str(offset)),
                unit_price=Decimal("2.00"),
                line_total=Decimal(str(offset * 2)),
                uom_code="EA",
                create_by_id="tester",
                update_by_id="tester",
            )
        return procurement

    def test_list_procurements_summary_uses_batched_helpers_and_skips_item_payloads(self) -> None:
        self._create_procurement("PROC-LIST-001", item_ids=[100, 101])
        self._create_procurement("PROC-LIST-002", item_ids=[200])

        with patch(
            "replenishment.services.procurement.data_access.get_warehouse_names",
            return_value=({1: "Kingston Central Depot"}, []),
        ) as mock_get_warehouse_names, patch(
            "replenishment.services.procurement.data_access.get_warehouse_name"
        ) as mock_get_warehouse_name, patch(
            "replenishment.services.procurement.data_access.get_item_names"
        ) as mock_get_item_names:
            procurements, count = procurement_service.list_procurements(
                allowed_warehouse_ids=None
            )

        self.assertEqual(count, 2)
        self.assertEqual(len(procurements), 2)
        self.assertTrue(all(row.get("items") == [] for row in procurements))
        mock_get_warehouse_names.assert_called_once_with([1, 1])
        mock_get_warehouse_name.assert_not_called()
        mock_get_item_names.assert_not_called()

    def test_list_procurements_include_items_batches_item_name_lookup(self) -> None:
        self._create_procurement("PROC-LIST-003", item_ids=[100, 101])
        self._create_procurement("PROC-LIST-004", item_ids=[101, 102])

        with patch(
            "replenishment.services.procurement.data_access.get_warehouse_names",
            return_value=({1: "Kingston Central Depot"}, []),
        ) as mock_get_warehouse_names, patch(
            "replenishment.services.procurement.data_access.get_item_names",
            return_value=(
                {
                    100: {"name": "Water", "code": "WTR"},
                    101: {"name": "Blanket", "code": "BLN"},
                    102: {"name": "Flashlight", "code": "FLS"},
                },
                [],
            ),
        ) as mock_get_item_names, patch(
            "replenishment.services.procurement.data_access.get_warehouse_name"
        ) as mock_get_warehouse_name:
            procurements, count = procurement_service.list_procurements(
                allowed_warehouse_ids=None,
                include_items=True,
            )

        self.assertEqual(count, 2)
        self.assertEqual(len(procurements[0].get("items", [])), 2)
        self.assertEqual(len(procurements[1].get("items", [])), 2)
        mock_get_warehouse_names.assert_called_once_with([1, 1])
        mock_get_item_names.assert_called_once_with([100, 101, 102])
        mock_get_warehouse_name.assert_not_called()

    def test_list_procurements_summary_query_count_is_constant_with_line_items(self) -> None:
        self._create_procurement("PROC-LIST-005", item_ids=[100, 101, 102])
        self._create_procurement("PROC-LIST-006", item_ids=[103, 104, 105])

        with patch(
            "replenishment.services.procurement.data_access.get_warehouse_names",
            return_value=({1: "Kingston Central Depot"}, []),
        ):
            with CaptureQueriesContext(connection) as captured:
                procurements, count = procurement_service.list_procurements(
                    allowed_warehouse_ids=None
                )

        self.assertEqual(count, 2)
        self.assertEqual(len(procurements), 2)
        self.assertEqual(len(captured), 1)

    def test_list_procurements_applies_allowed_warehouse_scope(self) -> None:
        first = self._create_procurement("PROC-LIST-007", item_ids=[100], warehouse_id=1)
        second = self._create_procurement("PROC-LIST-008", item_ids=[101], warehouse_id=2)

        with patch(
            "replenishment.services.procurement.data_access.get_warehouse_names",
            return_value=({2: "Montego Bay Depot"}, []),
        ):
            procurements, count = procurement_service.list_procurements(
                allowed_warehouse_ids={2}
            )

        self.assertEqual(count, 1)
        self.assertEqual(len(procurements), 1)
        self.assertEqual(procurements[0].get("procurement_id"), second.procurement_id)
        self.assertNotEqual(procurements[0].get("procurement_id"), first.procurement_id)

    def test_list_procurements_honors_offset_and_limit(self) -> None:
        first = self._create_procurement("PROC-LIST-010", item_ids=[100])
        second = self._create_procurement("PROC-LIST-011", item_ids=[101])
        third = self._create_procurement("PROC-LIST-012", item_ids=[102])

        base_time = timezone.now()
        Procurement.objects.filter(procurement_id=first.procurement_id).update(
            create_dtime=base_time - timedelta(minutes=3)
        )
        Procurement.objects.filter(procurement_id=second.procurement_id).update(
            create_dtime=base_time - timedelta(minutes=2)
        )
        Procurement.objects.filter(procurement_id=third.procurement_id).update(
            create_dtime=base_time - timedelta(minutes=1)
        )

        with patch(
            "replenishment.services.procurement.data_access.get_warehouse_names",
            return_value=({1: "Kingston Central Depot"}, []),
        ):
            first_page, first_count = procurement_service.list_procurements(
                allowed_warehouse_ids=None,
                offset=0,
                limit=1,
            )
            second_page, second_count = procurement_service.list_procurements(
                allowed_warehouse_ids=None,
                offset=1,
                limit=1,
            )

        self.assertEqual(first_count, 3)
        self.assertEqual(second_count, 3)
        self.assertEqual(len(first_page), 1)
        self.assertEqual(len(second_page), 1)
        self.assertEqual(first_page[0].get("procurement_id"), third.procurement_id)
        self.assertEqual(second_page[0].get("procurement_id"), second.procurement_id)
        self.assertNotEqual(first_page[0].get("procurement_id"), second_page[0].get("procurement_id"))

    def test_list_procurements_paginated_summary_query_count_is_constant_with_line_items(self) -> None:
        self._create_procurement("PROC-LIST-020", item_ids=[100, 101, 102])
        self._create_procurement("PROC-LIST-021", item_ids=[103, 104, 105])

        with patch(
            "replenishment.services.procurement.data_access.get_warehouse_names",
            return_value=({1: "Kingston Central Depot"}, []),
        ):
            with CaptureQueriesContext(connection) as captured:
                procurements, count = procurement_service.list_procurements(
                    allowed_warehouse_ids=None,
                    offset=0,
                    limit=1,
                )

        self.assertEqual(count, 2)
        self.assertEqual(len(procurements), 1)
        self.assertEqual(len(captured), 2)


class ProcurementReceiveItemsTests(TestCase):
    def test_receive_items_rejects_invalid_received_qty(self) -> None:
        proc = Procurement.objects.create(
            procurement_no="PROC-TEST-RECV-001",
            event_id=1,
            target_warehouse_id=1,
            procurement_method="SINGLE_SOURCE",
            status_code="SHIPPED",
            create_by_id="tester",
            update_by_id="tester",
        )
        line = ProcurementItem.objects.create(
            procurement=proc,
            item_id=999,
            ordered_qty=Decimal("5.00"),
            uom_code="EA",
            create_by_id="tester",
            update_by_id="tester",
        )

        with self.assertRaises(procurement_service.ProcurementError) as raised:
            procurement_service.receive_items(
                proc.procurement_id,
                [
                    {
                        "procurement_item_id": line.procurement_item_id,
                        "received_qty": "abc",
                    }
                ],
                actor_id="receiver",
            )

        self.assertEqual(raised.exception.code, "invalid_quantity")
        self.assertIn(str(line.procurement_item_id), raised.exception.message)


class ProcurementNumberGenerationTests(TestCase):
    def _create_needs_list_with_horizon_c(self, needs_list_no: str) -> NeedsList:
        needs_list = NeedsList.objects.create(
            needs_list_no=needs_list_no,
            event_id=1,
            warehouse_id=1,
            event_phase="BASELINE",
            calculation_dtime=timezone.now(),
            demand_window_hours=24,
            planning_window_hours=72,
            safety_factor=Decimal("1.25"),
            data_freshness_level="HIGH",
            status_code="APPROVED",
            total_gap_qty=Decimal("5.00"),
            create_by_id="tester",
            update_by_id="tester",
        )
        NeedsListItem.objects.create(
            needs_list=needs_list,
            item_id=123,
            uom_code="EA",
            burn_rate=Decimal("1.0000"),
            burn_rate_source="CALCULATED",
            available_stock=Decimal("0.00"),
            reserved_qty=Decimal("0.00"),
            inbound_transfer_qty=Decimal("0.00"),
            inbound_donation_qty=Decimal("0.00"),
            inbound_procurement_qty=Decimal("0.00"),
            required_qty=Decimal("5.00"),
            coverage_qty=Decimal("0.00"),
            gap_qty=Decimal("5.00"),
            time_to_stockout_hours=Decimal("1.00"),
            severity_level="CRITICAL",
            horizon_a_qty=Decimal("0.00"),
            horizon_b_qty=Decimal("0.00"),
            horizon_c_qty=Decimal("5.00"),
            create_by_id="tester",
            update_by_id="tester",
        )
        return needs_list

    def test_generate_procurement_no_uses_numeric_max_sequence(self) -> None:
        today = timezone.now().strftime("%Y%m%d")
        prefix = f"PROC-{today}-"
        Procurement.objects.create(
            procurement_no=f"{prefix}999",
            event_id=1,
            target_warehouse_id=1,
            procurement_method="SINGLE_SOURCE",
            status_code="DRAFT",
            create_by_id="tester",
            update_by_id="tester",
        )
        Procurement.objects.create(
            procurement_no=f"{prefix}1000",
            event_id=1,
            target_warehouse_id=1,
            procurement_method="SINGLE_SOURCE",
            status_code="DRAFT",
            create_by_id="tester",
            update_by_id="tester",
        )

        generated = procurement_service.generate_procurement_no()
        self.assertEqual(generated, f"{prefix}1001")

    @patch("replenishment.services.procurement.time.sleep", return_value=None)
    def test_create_procurement_standalone_retries_duplicate_procurement_no(self, _mock_sleep) -> None:
        today = timezone.now().strftime("%Y%m%d")
        duplicate_no = f"PROC-{today}-001"
        next_no = f"PROC-{today}-002"
        Procurement.objects.create(
            procurement_no=duplicate_no,
            event_id=1,
            target_warehouse_id=1,
            procurement_method="SINGLE_SOURCE",
            status_code="DRAFT",
            create_by_id="tester",
            update_by_id="tester",
        )

        with patch(
            "replenishment.services.procurement.generate_procurement_no",
            side_effect=[duplicate_no, next_no],
        ):
            created = procurement_service.create_procurement_standalone(
                event_id=1,
                target_warehouse_id=1,
                items=[{"item_id": 100, "ordered_qty": 2, "unit_price": 3}],
                actor_id="tester",
            )

        self.assertEqual(created.get("procurement_no"), next_no)
        self.assertTrue(Procurement.objects.filter(procurement_no=next_no).exists())

    @patch("replenishment.services.procurement.time.sleep", return_value=None)
    def test_create_procurement_from_needs_list_retries_duplicate_procurement_no(self, _mock_sleep) -> None:
        needs_list = self._create_needs_list_with_horizon_c("NL-PROC-RETRY-001")
        today = timezone.now().strftime("%Y%m%d")
        duplicate_no = f"PROC-{today}-010"
        next_no = f"PROC-{today}-011"
        Procurement.objects.create(
            procurement_no=duplicate_no,
            event_id=1,
            target_warehouse_id=1,
            procurement_method="SINGLE_SOURCE",
            status_code="DRAFT",
            create_by_id="tester",
            update_by_id="tester",
        )

        with patch(
            "replenishment.services.procurement.generate_procurement_no",
            side_effect=[duplicate_no, next_no],
        ):
            created = procurement_service.create_procurement_from_needs_list(
                needs_list.needs_list_no,
                actor_id="tester",
            )

        self.assertEqual(created.get("procurement_no"), next_no)
        self.assertTrue(Procurement.objects.filter(procurement_no=next_no).exists())

    @patch("replenishment.services.procurement.time.sleep", return_value=None)
    def test_create_procurement_standalone_raises_after_retry_exhaustion(self, _mock_sleep) -> None:
        today = timezone.now().strftime("%Y%m%d")
        duplicate_no = f"PROC-{today}-050"
        Procurement.objects.create(
            procurement_no=duplicate_no,
            event_id=1,
            target_warehouse_id=1,
            procurement_method="SINGLE_SOURCE",
            status_code="DRAFT",
            create_by_id="tester",
            update_by_id="tester",
        )

        with patch(
            "replenishment.services.procurement.generate_procurement_no",
            side_effect=[duplicate_no, duplicate_no, duplicate_no],
        ):
            with self.assertRaises(procurement_service.ProcurementError) as ctx:
                procurement_service.create_procurement_standalone(
                    event_id=1,
                    target_warehouse_id=1,
                    items=[{"item_id": 100, "ordered_qty": 2, "unit_price": 3}],
                    actor_id="tester",
                )

        self.assertEqual(ctx.exception.code, "duplicate_procurement_no")

    def test_create_procurement_standalone_rejects_invalid_unit_price(self) -> None:
        procurement_count = Procurement.objects.count()

        with self.assertRaises(procurement_service.ProcurementError) as ctx:
            procurement_service.create_procurement_standalone(
                event_id=1,
                target_warehouse_id=1,
                items=[
                    {
                        "item_id": 100,
                        "ordered_qty": 2,
                        "unit_price": {"value": "bad"},
                    }
                ],
                actor_id="tester",
            )

        self.assertEqual(ctx.exception.code, "invalid_unit_price")
        self.assertIn("item 100", ctx.exception.message)
        self.assertEqual(Procurement.objects.count(), procurement_count)

    def test_create_procurement_standalone_rejects_invalid_ordered_qty(self) -> None:
        procurement_count = Procurement.objects.count()

        with self.assertRaises(procurement_service.ProcurementError) as ctx:
            procurement_service.create_procurement_standalone(
                event_id=1,
                target_warehouse_id=1,
                items=[
                    {
                        "item_id": 100,
                        "ordered_qty": {"qty": "bad"},
                        "unit_price": "3.00",
                    }
                ],
                actor_id="tester",
            )

        self.assertEqual(ctx.exception.code, "invalid_ordered_qty")
        self.assertIn("item 100", ctx.exception.message)
        self.assertEqual(Procurement.objects.count(), procurement_count)

