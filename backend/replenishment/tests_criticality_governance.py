from __future__ import annotations

from contextlib import nullcontext
from unittest.mock import MagicMock, patch

from api.rbac import PERM_CRITICALITY_OVERRIDE_MANAGE
from django.test import override_settings
from django.test import SimpleTestCase
from rest_framework.test import APIClient

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


class EventOverrideClosedEventTests(SimpleTestCase):
    @patch("replenishment.services.criticality_governance._is_sqlite", return_value=False)
    def test_update_event_override_blocks_reactivation_for_closed_event(self, _mock_sqlite) -> None:
        mock_cursor = MagicMock()
        mock_cursor.fetchone.side_effect = [
            (55,),
            ("CLOSED",),
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
            updated, warnings = criticality_governance.update_event_override(
                override_id=10,
                updates={"is_active": True},
                actor_id="planner-user",
            )

        self.assertIsNone(updated)
        self.assertEqual(warnings, ["event_closed_override_not_allowed"])
        self.assertEqual(len(mock_cursor.execute.call_args_list), 2)
        schema = criticality_governance._schema_name()
        self.assertIn(
            f"FROM {schema}.event_item_criticality_override",
            mock_cursor.execute.call_args_list[0].args[0],
        )
        self.assertIn(
            f"FROM {schema}.event",
            mock_cursor.execute.call_args_list[1].args[0],
        )


class EventOverrideApiTests(SimpleTestCase):
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
    @patch("replenishment.views.criticality_governance.update_event_override")
    def test_event_override_update_returns_conflict_for_closed_event(
        self,
        mock_update,
    ) -> None:
        mock_update.return_value = (None, ["event_closed_override_not_allowed"])

        response = self.client.patch(
            "/api/v1/replenishment/criticality/event-overrides/10",
            {"is_active": True},
            format="json",
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json()["errors"]["criticality"],
            ["event_closed_override_not_allowed"],
        )
