from __future__ import annotations

import importlib
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase


migration_0003 = importlib.import_module("operations.migrations.0003_widen_legacy_tracking_numbers")
migration_0004 = importlib.import_module("operations.migrations.0004_make_reliefpkg_destination_nullable")


def _schema_editor(search_path: str | None = None):
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor
    cursor.fetchone.return_value = ((search_path,) if search_path is not None else (None,))

    connection = MagicMock()
    connection.vendor = "postgresql"
    connection.cursor.return_value = cursor

    schema_editor = MagicMock()
    schema_editor.connection = connection
    return schema_editor, cursor


class MigrationSchemaNameTests(SimpleTestCase):
    def test_0003_schema_name_prefers_dmisb_schema_env(self) -> None:
        schema_editor, cursor = _schema_editor("tenant_a, public")

        with patch.dict("os.environ", {"DMIS_DB_SCHEMA": "tenant_b"}):
            schema = migration_0003._schema_name(schema_editor)

        self.assertEqual(schema, "tenant_b")
        cursor.execute.assert_not_called()

    def test_0003_schema_name_falls_back_to_public_when_env_missing(self) -> None:
        schema_editor, cursor = _schema_editor("tenant_a, public")

        with patch.dict("os.environ", {}, clear=True):
            schema = migration_0003._schema_name(schema_editor)

        self.assertEqual(schema, "public")
        cursor.execute.assert_not_called()

    def test_0004_schema_name_uses_first_search_path_entry(self) -> None:
        schema_editor, cursor = _schema_editor('"tenant_a", public')

        with patch.dict("os.environ", {}, clear=True):
            schema = migration_0004._schema_name(schema_editor)

        self.assertEqual(schema, "tenant_a")
        cursor.execute.assert_called_once_with("SHOW search_path")

    def test_0004_schema_name_skips_special_search_path_entries(self) -> None:
        schema_editor, cursor = _schema_editor('current_schema(), "$user", tenant_a, public')

        with patch.dict("os.environ", {}, clear=True):
            schema = migration_0004._schema_name(schema_editor)

        self.assertEqual(schema, "tenant_a")
        cursor.execute.assert_called_once_with("SHOW search_path")

    def test_0004_schema_name_falls_back_to_public_for_blank_search_path(self) -> None:
        schema_editor, cursor = _schema_editor("")

        with patch.dict("os.environ", {}, clear=True):
            schema = migration_0004._schema_name(schema_editor)

        self.assertEqual(schema, "public")
        cursor.execute.assert_called_once_with("SHOW search_path")

    def test_0004_schema_name_honors_env_override(self) -> None:
        schema_editor, cursor = _schema_editor("tenant_a, public")

        with patch.dict("os.environ", {"DMIS_DB_SCHEMA": "tenant_a"}):
            schema = migration_0004._schema_name(schema_editor)

        self.assertEqual(schema, "tenant_a")
        cursor.execute.assert_not_called()
