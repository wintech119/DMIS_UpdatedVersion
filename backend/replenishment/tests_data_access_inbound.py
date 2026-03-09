from __future__ import annotations

from datetime import datetime, timezone as dt_timezone
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from django.utils import timezone

from replenishment.services import data_access


class StrictInboundAsOfTests(SimpleTestCase):
    @patch("replenishment.services.data_access._is_sqlite", return_value=False)
    @patch("replenishment.services.data_access._table_or_view_exists", return_value=True)
    def test_get_inbound_from_view_by_source_applies_as_of_filter(
        self,
        _mock_exists,
        _mock_sqlite,
    ) -> None:
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [(10, 4.5)]
        cursor_cm = MagicMock()
        cursor_cm.__enter__.return_value = mock_cursor
        cursor_cm.__exit__.return_value = None
        mock_connection = MagicMock(cursor=MagicMock(return_value=cursor_cm))
        as_of_dt = timezone.make_aware(datetime(2026, 3, 9, 12, 0, 0), dt_timezone.utc)

        with patch("replenishment.services.data_access.connection", new=mock_connection):
            inbound, warnings = data_access._get_inbound_from_view_by_source(
                3,
                "TRANSFER",
                as_of_dt,
            )

        self.assertEqual(inbound, {10: 4.5})
        self.assertEqual(warnings, [])
        executed_sql, params = mock_cursor.execute.call_args.args
        self.assertIn("AND inbound_start_dtime <= %s", executed_sql)
        self.assertIn(
            "AND (inbound_end_dtime IS NULL OR inbound_end_dtime > %s)",
            executed_sql,
        )
        normalized_as_of = data_access._normalize_datetime(as_of_dt)
        self.assertEqual(params, [3, "TRANSFER", normalized_as_of, normalized_as_of])

    @patch("replenishment.services.data_access._get_inbound_from_view_by_source")
    def test_get_inbound_donations_by_item_forwards_as_of_dt(self, mock_helper) -> None:
        as_of_dt = timezone.now()
        mock_helper.return_value = ({1: 2.0}, [])

        inbound, warnings = data_access.get_inbound_donations_by_item(5, as_of_dt)

        self.assertEqual(inbound, {1: 2.0})
        self.assertEqual(warnings, [])
        mock_helper.assert_called_once_with(5, "DONATION", as_of_dt)

    @patch("replenishment.services.data_access._get_inbound_from_view_by_source")
    def test_get_inbound_transfers_by_item_forwards_as_of_dt(self, mock_helper) -> None:
        as_of_dt = timezone.now()
        mock_helper.return_value = ({7: 3.0}, [])

        inbound, warnings = data_access.get_inbound_transfers_by_item(9, as_of_dt)

        self.assertEqual(inbound, {7: 3.0})
        self.assertEqual(warnings, [])
        mock_helper.assert_called_once_with(9, "TRANSFER", as_of_dt)
