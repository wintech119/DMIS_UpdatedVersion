from __future__ import annotations

from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from replenishment.models import Procurement
from replenishment.services import procurement as procurement_service


class ProcurementDraftWriteGuardTests(SimpleTestCase):
    @patch(
        "replenishment.services.procurement.data_access.get_inactive_item_ids",
        return_value=([], ["inactive_item_lookup_failed"]),
    )
    def test_assert_active_item_for_draft_write_fails_closed_on_lookup_warning(
        self,
        _mock_inactive_lookup,
    ) -> None:
        with self.assertRaises(procurement_service.ProcurementError) as ctx:
            procurement_service._assert_active_item_for_draft_write(
                101,
                table_key="procurement_item",
                workflow_state="DRAFT",
            )

        self.assertEqual(ctx.exception.code, "inactive_item_guard_untrusted")
        self.assertIn("inactive_item_lookup_failed", ctx.exception.message)
        self.assertIn("item_id=101", ctx.exception.message)


class ProcurementCreateGuardRollbackTests(TestCase):
    @patch(
        "replenishment.services.procurement.data_access.get_inactive_item_ids",
        return_value=([], ["inactive_item_lookup_failed"]),
    )
    def test_create_procurement_standalone_blocks_when_guard_untrusted(
        self,
        _mock_inactive_lookup,
    ) -> None:
        procurement_count = Procurement.objects.count()

        with self.assertRaises(procurement_service.ProcurementError) as ctx:
            procurement_service.create_procurement_standalone(
                event_id=1,
                target_warehouse_id=1,
                items=[{"item_id": 100, "ordered_qty": 2, "unit_price": 3}],
                actor_id="tester",
            )

        self.assertEqual(ctx.exception.code, "inactive_item_guard_untrusted")
        self.assertIn("inactive_item_lookup_failed", ctx.exception.message)
        self.assertEqual(Procurement.objects.count(), procurement_count)
