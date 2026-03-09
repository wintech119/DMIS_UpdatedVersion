from __future__ import annotations

from contextlib import nullcontext
from io import StringIO
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.test import SimpleTestCase

from replenishment.sql_migration_templates import (
    SUPPORTED_SQL_TEMPLATE_NAMES,
    render_sql_template,
)


class ApplyItemsCriticalityLayersCommandTests(SimpleTestCase):
    @patch.dict("os.environ", {"DMIS_DB_SCHEMA": "tenant_a"})
    def test_dry_run_reports_schema(self) -> None:
        output = StringIO()

        call_command("apply_items_criticality_layers", stdout=output)

        text = output.getvalue()
        self.assertIn("Item criticality governance migration:", text)
        self.assertIn("Schema: tenant_a", text)
        self.assertIn("Dry-run only", text)

    @patch.dict("os.environ", {"DMIS_DB_SCHEMA": "tenant_a"})
    def test_apply_executes_schema_rendered_sql(self) -> None:
        output = StringIO()
        mock_cursor = MagicMock()
        cursor_cm = MagicMock()
        cursor_cm.__enter__.return_value = mock_cursor
        cursor_cm.__exit__.return_value = None

        with (
            patch(
                "replenishment.management.commands.apply_items_criticality_layers.transaction.atomic",
                return_value=nullcontext(),
            ),
            patch(
                "replenishment.management.commands.apply_items_criticality_layers.connection",
                new=MagicMock(cursor=MagicMock(return_value=cursor_cm)),
            ),
        ):
            call_command("apply_items_criticality_layers", apply=True, stdout=output)

        executed_sql = mock_cursor.execute.call_args.args[0]
        self.assertIn(
            "CREATE TABLE IF NOT EXISTS tenant_a.event_item_criticality_override",
            executed_sql,
        )
        self.assertIn("REFERENCES tenant_a.event(event_id)", executed_sql)
        self.assertIn("REFERENCES tenant_a.item(item_id)", executed_sql)
        self.assertIn(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_hazard_item_criticality_one_approved_row",
            executed_sql,
        )
        self.assertIn(
            "ON tenant_a.hazard_item_criticality(event_type, item_id)",
            executed_sql,
        )
        self.assertIn(
            "WHERE approval_status = 'APPROVED'",
            executed_sql,
        )
        self.assertIn("AND is_active = TRUE", executed_sql)
        self.assertIn("AND effective_to IS NULL", executed_sql)
        self.assertIn(
            "CREATE OR REPLACE FUNCTION tenant_a.fn_expire_event_item_criticality_override_on_event_close()",
            executed_sql,
        )
        self.assertIn(
            "DROP TRIGGER IF EXISTS tr_event_close_expire_item_criticality_override ON tenant_a.event",
            executed_sql,
        )
        self.assertIn("UPDATE tenant_a.event_item_criticality_override eico", executed_sql)
        self.assertIn("FROM tenant_a.event e", executed_sql)
        self.assertNotIn("public.event_item_criticality_override", executed_sql)


class ReplenishmentSqlTemplateRenderingTests(SimpleTestCase):
    @patch.dict("os.environ", {"DMIS_DB_SCHEMA": "tenant_a"})
    def test_all_supported_templates_render_with_configured_schema(self) -> None:
        for template_name in SUPPORTED_SQL_TEMPLATE_NAMES:
            with self.subTest(template_name=template_name):
                rendered_sql = render_sql_template(template_name, "tenant_a")
                self.assertIn("tenant_a.", rendered_sql)
                self.assertNotIn("public.", rendered_sql)


class ApplyReplenishmentSqlMigrationCommandTests(SimpleTestCase):
    @patch.dict("os.environ", {"DMIS_DB_SCHEMA": "tenant_a"})
    def test_dry_run_reports_selected_template(self) -> None:
        output = StringIO()

        call_command(
            "apply_replenishment_sql_migration",
            "20260308_inbound_stock_view.sql",
            stdout=output,
        )

        text = output.getvalue()
        self.assertIn("Replenishment SQL migration:", text)
        self.assertIn("Schema: tenant_a", text)
        self.assertIn("20260308_inbound_stock_view.sql", text)
        self.assertIn("Dry-run only", text)

    @patch.dict("os.environ", {"DMIS_DB_SCHEMA": "tenant_a"})
    def test_apply_executes_rendered_sql_for_selected_template(self) -> None:
        output = StringIO()
        mock_cursor = MagicMock()
        cursor_cm = MagicMock()
        cursor_cm.__enter__.return_value = mock_cursor
        cursor_cm.__exit__.return_value = None

        with (
            patch(
                "replenishment.management.commands.apply_replenishment_sql_migration.transaction.atomic",
                return_value=nullcontext(),
            ),
            patch(
                "replenishment.management.commands.apply_replenishment_sql_migration.connection",
                new=MagicMock(cursor=MagicMock(return_value=cursor_cm)),
            ),
        ):
            call_command(
                "apply_replenishment_sql_migration",
                "20260308_inbound_stock_view.sql",
                apply=True,
                stdout=output,
            )

        executed_sql = mock_cursor.execute.call_args.args[0]
        self.assertIn("CREATE OR REPLACE VIEW tenant_a.v_inbound_stock AS", executed_sql)
        self.assertIn("FROM tenant_a.transfer t", executed_sql)
        self.assertIn("JOIN tenant_a.procurement_item pi", executed_sql)
        self.assertIn("COMMENT ON VIEW tenant_a.v_inbound_stock IS", executed_sql)
        self.assertNotIn("public.v_inbound_stock", executed_sql)
