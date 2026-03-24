from __future__ import annotations

import os
import re
from pathlib import Path


SUPPORTED_SQL_TEMPLATE_NAMES = (
    "add_phase_column.sql",
    "20260307_needs_list_item_effective_criticality.sql",
    "20260308_inbound_stock_view.sql",
    "20260308_items_criticality_layers.sql",
    "20260324_sprint08_allocation_persistence.sql",
    "20260324_sprint08_audit_actions.sql",
    "20260324_sprint08_allocation_precision_fix.sql",
)

_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def schema_name() -> str:
    schema = os.getenv("DMIS_DB_SCHEMA", "public")
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema):
        return schema
    return "public"


def sql_template_path(template_name: str) -> Path:
    if template_name not in SUPPORTED_SQL_TEMPLATE_NAMES:
        raise ValueError(f"Unsupported replenishment SQL template: {template_name}")
    return _MIGRATIONS_DIR / template_name


def render_sql_template(template_name: str, schema: str | None = None) -> str:
    resolved_schema = schema or schema_name()
    template = sql_template_path(template_name).read_text(encoding="utf-8")
    return template.format(schema=resolved_schema)
