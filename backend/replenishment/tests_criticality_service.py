from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from replenishment.services import criticality


class CriticalityEventContextTests(SimpleTestCase):
    @patch("replenishment.services.criticality._is_sqlite", return_value=False)
    @patch(
        "replenishment.services.criticality._table_columns",
        return_value={"event_type_code", "hazard_type", "status_code"},
    )
    def test_load_event_context_uses_available_event_type_fallback_columns(
        self,
        _mock_columns,
        _mock_sqlite,
    ) -> None:
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = ("storm", "c")
        cursor_cm = MagicMock()
        cursor_cm.__enter__.return_value = mock_cursor
        cursor_cm.__exit__.return_value = None
        mock_connection = MagicMock(cursor=MagicMock(return_value=cursor_cm))

        with patch("replenishment.services.criticality.connection", new=mock_connection):
            event_type, status_code, warnings = criticality._load_event_context("tenant_a", 42)

        self.assertEqual(event_type, "STORM")
        self.assertEqual(status_code, "C")
        self.assertEqual(warnings, [])
        executed_sql, params = mock_cursor.execute.call_args.args
        self.assertIn(
            "SELECT COALESCE(event_type_code, hazard_type) AS event_type, status_code",
            executed_sql,
        )
        self.assertEqual(params, [42])

    @patch("replenishment.services.criticality._is_sqlite", return_value=False)
    @patch(
        "replenishment.services.criticality._table_columns",
        return_value={"event_type", "event_type_code", "hazard_type", "status_code"},
    )
    def test_load_event_context_prefers_event_type_order_defined_in_module(
        self,
        _mock_columns,
        _mock_sqlite,
    ) -> None:
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = ("hurricane", "a")
        cursor_cm = MagicMock()
        cursor_cm.__enter__.return_value = mock_cursor
        cursor_cm.__exit__.return_value = None
        mock_connection = MagicMock(cursor=MagicMock(return_value=cursor_cm))

        with patch("replenishment.services.criticality.connection", new=mock_connection):
            event_type, status_code, warnings = criticality._load_event_context("tenant_a", 7)

        self.assertEqual(event_type, "HURRICANE")
        self.assertEqual(status_code, "A")
        self.assertEqual(warnings, [])
        executed_sql = mock_cursor.execute.call_args.args[0]
        self.assertIn(
            "SELECT COALESCE(event_type, event_type_code, hazard_type) AS event_type, status_code",
            executed_sql,
        )
