from django.test import SimpleTestCase

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
