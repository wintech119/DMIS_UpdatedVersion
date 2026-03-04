from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase
from rest_framework.request import Request

from masterdata import views

from masterdata.services.data_access import TABLE_REGISTRY, _resolve_order_by


class OrderByValidationTests(SimpleTestCase):
    def test_accepts_known_column_default_direction(self):
        cfg = TABLE_REGISTRY["items"]
        sort_sql, invalid = _resolve_order_by(cfg, "item_name")
        self.assertEqual(sort_sql, "item_name ASC")
        self.assertFalse(invalid)

    def test_accepts_explicit_desc_direction(self):
        cfg = TABLE_REGISTRY["items"]
        sort_sql, invalid = _resolve_order_by(cfg, "item_name desc")
        self.assertEqual(sort_sql, "item_name DESC")
        self.assertFalse(invalid)

    def test_accepts_dash_prefix_desc(self):
        cfg = TABLE_REGISTRY["items"]
        sort_sql, invalid = _resolve_order_by(cfg, "-item_name")
        self.assertEqual(sort_sql, "item_name DESC")
        self.assertFalse(invalid)

    def test_rejects_sql_fragment_and_falls_back_to_default(self):
        cfg = TABLE_REGISTRY["items"]
        sort_sql, invalid = _resolve_order_by(cfg, "item_name; DROP TABLE item; --")
        self.assertEqual(sort_sql, "item_name ASC")
        self.assertTrue(invalid)

    def test_rejects_unknown_column_and_falls_back_to_default(self):
        cfg = TABLE_REGISTRY["items"]
        sort_sql, invalid = _resolve_order_by(cfg, "does_not_exist DESC")
        self.assertEqual(sort_sql, "item_name ASC")
        self.assertTrue(invalid)

    def test_preserves_valid_default_direction(self):
        cfg = TABLE_REGISTRY["events"]
        sort_sql, invalid = _resolve_order_by(cfg, None)
        self.assertEqual(sort_sql, "start_date DESC")
        self.assertFalse(invalid)


class PaginationLimitClampTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.cfg = TABLE_REGISTRY["items"]

    @patch("masterdata.views.list_records", return_value=([], 0, []))
    def test_negative_limit_is_clamped_to_minimum(self, mock_list_records):
        request = Request(self.factory.get(
            "/api/v1/masterdata/items/",
            {"limit": "-1", "offset": "0"},
        ))
        response = views._handle_list(request, self.cfg)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["limit"], 1)
        kwargs = mock_list_records.call_args.kwargs
        self.assertEqual(kwargs["limit"], 1)

    @patch("masterdata.views.list_records", return_value=([], 0, []))
    def test_excessive_limit_is_clamped_to_maximum(self, mock_list_records):
        request = Request(self.factory.get(
            "/api/v1/masterdata/items/",
            {"limit": "999999", "offset": "0"},
        ))
        response = views._handle_list(request, self.cfg)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["limit"], 500)
        kwargs = mock_list_records.call_args.kwargs
        self.assertEqual(kwargs["limit"], 500)
