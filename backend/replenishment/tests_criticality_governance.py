from __future__ import annotations

from contextlib import nullcontext
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from replenishment.services import criticality_governance


class HazardDefaultApprovalSeparationTests(SimpleTestCase):
    @patch("replenishment.services.criticality_governance._is_sqlite", return_value=False)
    def test_approve_hazard_default_blocks_self_approval(self, _mock_sqlite) -> None:
        mock_cursor = MagicMock()
        mock_cursor.fetchone.side_effect = [
            None,
            ("PENDING_APPROVAL", "director-user"),
        ]
        cursor_cm = MagicMock()
        cursor_cm.__enter__.return_value = mock_cursor
        cursor_cm.__exit__.return_value = None
        mock_connection = MagicMock(cursor=MagicMock(return_value=cursor_cm))

        with (
            patch(
                "replenishment.services.criticality_governance.transaction.atomic",
                return_value=nullcontext(),
            ),
            patch(
                "replenishment.services.criticality_governance.connection",
                new=mock_connection,
            ),
        ):
            approved, warnings = criticality_governance.approve_hazard_default(
                hazard_item_criticality_id=10,
                actor_id="director-user",
            )

        self.assertIsNone(approved)
        self.assertEqual(warnings, ["criticality_hazard_default_self_approval_forbidden"])
        update_sql, update_params = mock_cursor.execute.call_args_list[0].args
        self.assertIn("submitted_by_id IS DISTINCT FROM %s", update_sql)
        self.assertEqual(update_params[-1], "director-user")

    @patch("replenishment.services.criticality_governance._is_sqlite", return_value=False)
    def test_reject_hazard_default_blocks_self_rejection(self, _mock_sqlite) -> None:
        mock_cursor = MagicMock()
        mock_cursor.fetchone.side_effect = [
            None,
            ("PENDING_APPROVAL", "director-user"),
        ]
        cursor_cm = MagicMock()
        cursor_cm.__enter__.return_value = mock_cursor
        cursor_cm.__exit__.return_value = None
        mock_connection = MagicMock(cursor=MagicMock(return_value=cursor_cm))

        with (
            patch(
                "replenishment.services.criticality_governance.transaction.atomic",
                return_value=nullcontext(),
            ),
            patch(
                "replenishment.services.criticality_governance.connection",
                new=mock_connection,
            ),
        ):
            rejected, warnings = criticality_governance.reject_hazard_default(
                hazard_item_criticality_id=10,
                actor_id="director-user",
                reason_text="Needs revision.",
            )

        self.assertIsNone(rejected)
        self.assertEqual(warnings, ["criticality_hazard_default_self_rejection_forbidden"])
        update_sql, update_params = mock_cursor.execute.call_args_list[0].args
        self.assertIn("submitted_by_id IS DISTINCT FROM %s", update_sql)
        self.assertEqual(update_params[-1], "director-user")

    @patch("replenishment.services.criticality_governance._is_sqlite", return_value=False)
    def test_approve_hazard_default_keeps_invalid_state_warning_for_other_cases(
        self,
        _mock_sqlite,
    ) -> None:
        mock_cursor = MagicMock()
        mock_cursor.fetchone.side_effect = [
            None,
            ("APPROVED", "different-user"),
        ]
        cursor_cm = MagicMock()
        cursor_cm.__enter__.return_value = mock_cursor
        cursor_cm.__exit__.return_value = None
        mock_connection = MagicMock(cursor=MagicMock(return_value=cursor_cm))

        with (
            patch(
                "replenishment.services.criticality_governance.transaction.atomic",
                return_value=nullcontext(),
            ),
            patch(
                "replenishment.services.criticality_governance.connection",
                new=mock_connection,
            ),
        ):
            approved, warnings = criticality_governance.approve_hazard_default(
                hazard_item_criticality_id=10,
                actor_id="director-user",
            )

        self.assertIsNone(approved)
        self.assertEqual(
            warnings,
            ["criticality_hazard_default_approve_invalid_state_or_missing"],
        )
