"""
Generic raw-SQL CRUD for legacy master-data tables.

Each table is described by a registry entry so that views, validation and
front-end config can all be driven from one source of truth.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from django.db import DatabaseError, connection, transaction

from masterdata.item_master_taxonomy import taxonomy_source_version

logger = logging.getLogger(__name__)

_ORDER_BY_PATTERN = re.compile(
    r"^\s*(?P<column>[A-Za-z_][A-Za-z0-9_]*)\s*(?:(?P<direction>ASC|DESC))?\s*$",
    re.IGNORECASE,
)
INACTIVE_ITEM_FORWARD_WRITE_CODE = "inactive_item_forward_write_blocked"

_FORWARD_WRITE_BLOCK_ALWAYS_TABLES = {"inventory", "itembatch", "item_location"}
_FORWARD_WRITE_STATE_TABLES = {
    "transfer_item": {"DRAFT", "PENDING"},
    "needs_list_item": {"DRAFT", "DRAFT_GENERATION"},
    "donation_item": {"ENTERED", "PENDING"},
    "procurement_item": {"DRAFT"},
    "reliefpkg_item": {"DRAFT"},
    "reliefrqst_item": {"DRAFT"},
}
_WORKFLOW_STATE_ALIASES = {
    "P": "PENDING",
    "PENDING_APPROVAL": "PENDING",
    "PENDING_REVIEW": "PENDING",
    "D": "DRAFT",
    "DRAFT_PENDING": "PENDING",
    "ENTER": "ENTERED",
    "E": "ENTERED",
    "CREATE": "DRAFT",
    "CREATED": "DRAFT",
}


# ---------------------------------------------------------------------------
# DB helpers (same pattern as replenishment.services.data_access)
# ---------------------------------------------------------------------------

def _is_sqlite() -> bool:
    from django.conf import settings
    if os.getenv("DJANGO_USE_SQLITE", "0") == "1":
        return True
    return settings.DATABASES["default"]["ENGINE"].endswith("sqlite3")


def _schema_name() -> str:
    schema = os.getenv("DMIS_DB_SCHEMA", "public")
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema):
        return schema
    logger.warning("Invalid DMIS_DB_SCHEMA %r, defaulting to public", schema)
    return "public"


def _safe_rollback() -> None:
    try:
        connection.rollback()
    except Exception:
        pass


def _db_error_warnings(exc: Exception) -> list[str]:
    warnings = ["db_error", f"db_exception:{exc.__class__.__name__}"]
    message = re.sub(r"\s+", " ", str(exc or "")).strip()
    if message:
        warnings.append(f"db_message:{message[:240]}")
    return warnings


def _is_postgresql() -> bool:
    return getattr(connection, "vendor", "") == "postgresql"


def _auto_pk_config(table_key: str) -> tuple["TableConfig", "FieldDef"] | tuple[None, None]:
    cfg = TABLE_REGISTRY.get(table_key)
    pk_def = getattr(cfg, "_pk_def", None)
    if cfg is None or pk_def is None or not pk_def.auto_pk:
        return None, None
    return cfg, pk_def


def inspect_auto_pk_sequence(table_key: str) -> tuple[dict[str, Any] | None, list[str]]:
    cfg, pk_def = _auto_pk_config(table_key)
    if cfg is None or pk_def is None:
        return None, ["auto_pk_not_supported"]
    if _is_sqlite():
        return None, ["db_unavailable"]
    if not _is_postgresql():
        return None, ["db_vendor_not_supported"]

    schema = _schema_name()
    qualified_table = f"{schema}.{cfg.db_table}"
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_get_serial_sequence(%s, %s)",
                [qualified_table, cfg.pk_field],
            )
            sequence_row = cursor.fetchone()
            sequence_name = sequence_row[0] if sequence_row else None
            if not sequence_name:
                return None, ["pk_sequence_not_found"]

            cursor.execute(
                f"SELECT COALESCE(MAX({cfg.pk_field}), 0) FROM {schema}.{cfg.db_table}"
            )
            max_pk_row = cursor.fetchone()
            max_pk = int(max_pk_row[0] or 0) if max_pk_row else 0

            cursor.execute(f"SELECT last_value, is_called FROM {sequence_name}")
            state_row = cursor.fetchone()
            last_value = int(state_row[0]) if state_row else 0
            is_called = bool(state_row[1]) if state_row else False

        return {
            "table_key": table_key,
            "schema": schema,
            "table_name": cfg.db_table,
            "pk_field": cfg.pk_field,
            "sequence_name": sequence_name,
            "max_pk": max_pk,
            "last_value": last_value,
            "is_called": is_called,
            "next_value": last_value + 1 if is_called else last_value,
        }, []
    except DatabaseError as exc:
        logger.warning("inspect_auto_pk_sequence(%s) failed: %s", table_key, exc)
        _safe_rollback()
        return None, ["pk_sequence_inspection_failed"]


def resync_auto_pk_sequence(table_key: str) -> tuple[bool, dict[str, Any] | None, list[str]]:
    info, warnings = inspect_auto_pk_sequence(table_key)
    if info is None:
        return False, None, warnings

    target_value = int(info["max_pk"]) + 1
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT setval(%s::regclass, %s, false)",
                    [info["sequence_name"], target_value],
                )
                row = cursor.fetchone()
                applied_value = int(row[0]) if row else target_value
    except DatabaseError as exc:
        logger.warning("resync_auto_pk_sequence(%s) failed: %s", table_key, exc)
        _safe_rollback()
        return False, info, warnings + ["pk_sequence_resync_failed"]

    updated_info = dict(info)
    updated_info.update(
        {
            "last_value": applied_value,
            "is_called": False,
            "next_value": target_value,
            "target_value": target_value,
        }
    )
    return True, updated_info, warnings + ["pk_sequence_resynced"]


def _is_auto_pk_duplicate_violation(table_key: str, exc: Exception) -> bool:
    cfg, pk_def = _auto_pk_config(table_key)
    if cfg is None or pk_def is None:
        return False
    if _is_sqlite() or not _is_postgresql():
        return False

    cause = getattr(exc, "__cause__", None)
    sqlstate = getattr(cause, "pgcode", None) or getattr(cause, "sqlstate", None)
    if sqlstate and str(sqlstate) != "23505":
        return False

    constraint_name = getattr(getattr(cause, "diag", None), "constraint_name", None)
    normalized_constraint = str(constraint_name or "").strip().lower()
    if normalized_constraint in {f"pk_{cfg.db_table}".lower(), f"{cfg.db_table}_pkey".lower()}:
        return True

    message = re.sub(r"\s+", " ", str(exc or "")).strip().lower()
    if "duplicate key value violates unique constraint" not in message:
        return False
    if normalized_constraint and normalized_constraint not in {
        f"pk_{cfg.db_table}".lower(),
        f"{cfg.db_table}_pkey".lower(),
    }:
        return False
    return f"({cfg.pk_field})=" in message


# ---------------------------------------------------------------------------
# Field descriptor
# ---------------------------------------------------------------------------

class FieldDef:
    """Describes a single column in a legacy table."""

    def __init__(
        self,
        name: str,
        *,
        label: str = "",
        db_type: str = "varchar",
        max_length: int | None = None,
        required: bool = False,
        unique: bool = False,
        uppercase: bool = False,
        pk: bool = False,
        auto_pk: bool = False,
        readonly: bool = False,
        fk_table: str | None = None,
        fk_pk: str | None = None,
        fk_label: str | None = None,
        default: Any = None,
        choices: list | None = None,
        pattern: str | None = None,
        pattern_message: str | None = None,
        searchable: bool = False,
        empty_as_null: bool = False,
    ):
        self.name = name
        self.label = label or name.replace("_", " ").title()
        self.db_type = db_type
        self.max_length = max_length
        self.required = required
        self.unique = unique
        self.uppercase = uppercase
        self.pk = pk
        self.auto_pk = auto_pk
        self.readonly = readonly
        self.fk_table = fk_table
        self.fk_pk = fk_pk
        self.fk_label = fk_label
        self.default = default
        self.choices = choices
        self.pattern = pattern
        self.pattern_message = pattern_message
        self.searchable = searchable
        self.empty_as_null = empty_as_null


# ---------------------------------------------------------------------------
# Dependency descriptor
# ---------------------------------------------------------------------------

class DependencyDef:
    """Describes a referential-integrity check before inactivation."""

    def __init__(self, table: str, fk_column: str, label: str):
        self.table = table
        self.fk_column = fk_column
        self.label = label


# ---------------------------------------------------------------------------
# Table registry entry
# ---------------------------------------------------------------------------

class TableConfig:
    def __init__(
        self,
        key: str,
        db_table: str,
        pk_field: str,
        fields: list[FieldDef],
        *,
        display_name: str = "",
        status_field: str = "status_code",
        version_field: str = "version_nbr",
        audit_create_user: str = "create_by_id",
        audit_create_time: str = "create_dtime",
        audit_update_user: str = "update_by_id",
        audit_update_time: str = "update_dtime",
        default_order: str = "",
        dependencies: list[DependencyDef] | None = None,
        active_status: str = "A",
        inactive_status: str = "I",
        has_audit: bool = True,
        has_version: bool = True,
    ):
        self.key = key
        self.db_table = db_table
        self.pk_field = pk_field
        self.fields = fields
        self.display_name = display_name or key.replace("_", " ").title()
        self.status_field = status_field  # empty string means no status column
        self.version_field = version_field
        self.audit_create_user = audit_create_user
        self.audit_create_time = audit_create_time
        self.audit_update_user = audit_update_user
        self.audit_update_time = audit_update_time
        self.default_order = default_order or pk_field
        self.dependencies = dependencies or []
        self.active_status = active_status
        self.inactive_status = inactive_status
        self.has_audit = has_audit
        self.has_version = has_version

        self._field_map: dict[str, FieldDef] = {f.name: f for f in fields}
        self._pk_def: FieldDef | None = next((f for f in fields if f.pk), None)

    def field(self, name: str) -> FieldDef | None:
        return self._field_map.get(name)

    @property
    def searchable_fields(self) -> list[FieldDef]:
        return [f for f in self.fields if f.searchable]

    @property
    def unique_fields(self) -> list[FieldDef]:
        return [f for f in self.fields if f.unique]

    @property
    def has_status(self) -> bool:
        return bool(self.status_field)

    @property
    def data_fields(self) -> list[FieldDef]:
        """Fields that appear in create/update payloads (excludes auto-PK, audit, version)."""
        exclude: set[str] = set()
        if self.has_audit:
            exclude.update({
                self.audit_create_user, self.audit_create_time,
                self.audit_update_user, self.audit_update_time,
            })
        if self.has_version:
            exclude.add(self.version_field)
        return [f for f in self.fields if not f.auto_pk and f.name not in exclude]


# ---------------------------------------------------------------------------
# TABLE REGISTRY
# ---------------------------------------------------------------------------

TABLE_REGISTRY: Dict[str, TableConfig] = {}


def _register(cfg: TableConfig) -> TableConfig:
    TABLE_REGISTRY[cfg.key] = cfg
    return cfg


# ── Item Categories ───────────────────────────────────────────────────────
_register(TableConfig(
    key="item_categories",
    db_table="itemcatg",
    pk_field="category_id",
    display_name="Item Categories",
    default_order="category_code",
    fields=[
        FieldDef("category_id", pk=True, auto_pk=True, db_type="int", label="ID"),
        FieldDef("category_type", max_length=5, default="GOODS",
                 choices=["GOODS", "FUNDS"], label="Type"),
        FieldDef("category_code", required=True, unique=True, uppercase=True,
                 max_length=30, searchable=True, label="Code"),
        FieldDef("category_desc", required=True, max_length=60,
                 searchable=True, label="Description"),
        FieldDef("comments_text", max_length=300, label="Comments"),
        FieldDef("status_code", required=True, max_length=1, default="A",
                 choices=["A", "I"], label="Status"),
    ],
    dependencies=[
        DependencyDef("item", "category_id", "Items"),
    ],
))

# -- IFRC Families -----------------------------------------------------------
_register(TableConfig(
    key="ifrc_families",
    db_table="ifrc_family",
    pk_field="ifrc_family_id",
    display_name="IFRC Families",
    default_order="family_label",
    fields=[
        FieldDef("ifrc_family_id", pk=True, auto_pk=True, db_type="int", label="ID"),
        FieldDef("category_id", required=True, db_type="int", label="Level 1 Category",
                 fk_table="itemcatg", fk_pk="category_id", fk_label="category_desc"),
        FieldDef("family_label", required=True, max_length=160,
                 searchable=True, label="Family Label"),
        FieldDef("group_code", required=True, uppercase=True, max_length=4,
                 searchable=True, label="Group Code"),
        FieldDef("group_label", required=True, max_length=120,
                 searchable=True, label="Group Label"),
        FieldDef("family_code", required=True, uppercase=True, max_length=6,
                 searchable=True, label="Family Code"),
        FieldDef("source_version", required=False, max_length=80,
                 default=taxonomy_source_version(), label="Source Version"),
        FieldDef("status_code", required=True, max_length=1, default="A",
                 choices=["A", "I"], label="Status"),
    ],
    dependencies=[
        DependencyDef("item", "ifrc_family_id", "Items"),
        DependencyDef("ifrc_item_reference", "ifrc_family_id", "IFRC Item References"),
    ],
))

# -- IFRC Item References ----------------------------------------------------
_register(TableConfig(
    key="ifrc_item_references",
    db_table="ifrc_item_reference",
    pk_field="ifrc_item_ref_id",
    display_name="IFRC Item References",
    default_order="reference_desc",
    fields=[
        FieldDef("ifrc_item_ref_id", pk=True, auto_pk=True, db_type="int", label="ID"),
        FieldDef("ifrc_family_id", required=True, db_type="int", label="IFRC Family",
                 fk_table="ifrc_family", fk_pk="ifrc_family_id", fk_label="family_label"),
        FieldDef("ifrc_code", required=True, unique=True, uppercase=True,
                 max_length=30, searchable=True, label="IFRC Code"),
        FieldDef("reference_desc", required=True, max_length=255,
                 searchable=True, label="Reference Description"),
        FieldDef("category_code", required=True, uppercase=True, max_length=6,
                 searchable=True, label="Reference Category Code"),
        FieldDef("category_label", required=True, max_length=160,
                 searchable=True, label="Reference Category Label"),
        FieldDef("spec_segment", required=False, uppercase=True, max_length=7,
                 searchable=True, empty_as_null=True, label="Spec Segment"),
        FieldDef("size_weight", required=False, uppercase=True, max_length=40,
                 searchable=True, empty_as_null=True, label="Size or Weight"),
        FieldDef("form", required=False, uppercase=True, max_length=40,
                 searchable=True, empty_as_null=True, label="Form"),
        FieldDef("material", required=False, uppercase=True, max_length=40,
                 searchable=True, empty_as_null=True, label="Material"),
        FieldDef("source_version", required=False, max_length=80,
                 default=taxonomy_source_version(), label="Source Version"),
        FieldDef("status_code", required=True, max_length=1, default="A",
                 choices=["A", "I"], label="Status"),
    ],
    dependencies=[
        DependencyDef("item", "ifrc_item_ref_id", "Items"),
    ],
))

# ── Units of Measure ─────────────────────────────────────────────────────
_register(TableConfig(
    key="uom",
    db_table="unitofmeasure",
    pk_field="uom_code",
    display_name="Units of Measure",
    default_order="uom_code",
    fields=[
        FieldDef("uom_code", pk=True, required=True, unique=True,
                 uppercase=True, max_length=25, searchable=True, label="Code"),
        FieldDef("uom_desc", required=True, max_length=60,
                 searchable=True, label="Description"),
        FieldDef("comments_text", max_length=300, label="Comments"),
        FieldDef("status_code", required=True, max_length=1, default="A",
                 choices=["A", "I"], label="Status"),
    ],
    dependencies=[
        DependencyDef("item", "default_uom_code", "Items"),
        DependencyDef("itembatch", "uom_code", "Inventory Batches"),
    ],
))

# ── Items ─────────────────────────────────────────────────────────────────
_register(TableConfig(
    key="items",
    db_table="item",
    pk_field="item_id",
    display_name="Items",
    default_order="item_name",
    fields=[
        FieldDef("item_id", pk=True, auto_pk=True, db_type="int", label="ID"),
        FieldDef("item_code", required=False, unique=True, uppercase=True,
                 max_length=30, searchable=True, label="Item Code",
                 pattern=r"^[A-Z0-9\-_\.]+$",
                 pattern_message="Only uppercase letters, digits, hyphens, underscores, dots"),
        FieldDef("legacy_item_code", required=False, uppercase=True,
                 max_length=30, searchable=True, label="Legacy Item Code",
                 pattern=r"^[A-Z0-9\-_\.]+$",
                 pattern_message="Only uppercase letters, digits, hyphens, underscores, dots",
                 empty_as_null=True),
        FieldDef("item_name", required=True, unique=True, uppercase=True,
                 max_length=60, searchable=True, label="Item Name"),
        FieldDef("sku_code", required=False, unique=True, uppercase=True,
                 max_length=30, searchable=True, label="SKU Code",
                 empty_as_null=True),
        FieldDef("category_id", required=True, db_type="int", label="Category",
                 fk_table="itemcatg", fk_pk="category_id", fk_label="category_desc"),
        FieldDef("ifrc_family_id", db_type="int", label="IFRC Family",
                 fk_table="ifrc_family", fk_pk="ifrc_family_id", fk_label="family_label"),
        FieldDef("ifrc_item_ref_id", db_type="int", label="IFRC Item Reference",
                 fk_table="ifrc_item_reference", fk_pk="ifrc_item_ref_id", fk_label="reference_desc"),
        FieldDef("item_desc", required=True, label="Description"),
        FieldDef("reorder_qty", required=True, db_type="numeric", label="Reorder Quantity"),
        FieldDef("default_uom_code", required=True, max_length=25, label="Default UOM",
                 fk_table="unitofmeasure", fk_pk="uom_code", fk_label="uom_desc"),
        FieldDef("units_size_vary_flag", db_type="boolean", default=False,
                 label="Units Size Vary"),
        FieldDef("usage_desc", max_length=300, label="Usage Description"),
        FieldDef("storage_desc", max_length=300, label="Storage Description"),
        FieldDef("is_batched_flag", db_type="boolean", default=True,
                 label="Batch Tracked"),
        FieldDef("can_expire_flag", db_type="boolean", default=False,
                 label="Can Expire"),
        FieldDef("issuance_order", required=True, max_length=20,
                 choices=["FIFO", "FEFO", "LIFO"], default="FIFO",
                 label="Issuance Order"),
        FieldDef("baseline_burn_rate", db_type="numeric", default=0,
                 label="Baseline Burn Rate"),
        FieldDef("min_stock_threshold", db_type="numeric", default=0,
                 label="Min Stock Threshold"),
        FieldDef("criticality_level", max_length=10, default="NORMAL",
                 choices=["LOW", "NORMAL", "HIGH", "CRITICAL"],
                 label="Criticality Level"),
        FieldDef("comments_text", max_length=300, label="Comments"),
        FieldDef("status_code", required=True, max_length=1, default="A",
                 choices=["A", "I"], label="Status"),
    ],
    dependencies=[
        DependencyDef("itembatch", "item_id", "Inventory Batches"),
    ],
))


# -- Inventory ---------------------------------------------------------------
_register(TableConfig(
    key="inventory",
    db_table="inventory",
    pk_field="inventory_id",
    display_name="Inventory",
    default_order="inventory_id DESC",
    fields=[
        FieldDef("inventory_id", pk=True, auto_pk=True, db_type="int", label="ID"),
        FieldDef("item_id", required=True, db_type="int", label="Item",
                 fk_table="item", fk_pk="item_id", fk_label="item_name"),
        FieldDef("usable_qty", db_type="numeric", default=0, label="Usable Quantity"),
        FieldDef("reserved_qty", db_type="numeric", default=0, label="Reserved Quantity"),
        FieldDef("defective_qty", db_type="numeric", default=0, label="Defective Quantity"),
        FieldDef("expired_qty", db_type="numeric", default=0, label="Expired Quantity"),
        FieldDef("uom_code", max_length=25, label="UOM",
                 fk_table="unitofmeasure", fk_pk="uom_code", fk_label="uom_desc"),
        FieldDef("reorder_qty", db_type="numeric", default=0, label="Reorder Quantity"),
        FieldDef("last_verified_by", max_length=20, label="Last Verified By"),
        FieldDef("last_verified_date", db_type="date", label="Last Verified Date"),
        FieldDef("comments_text", label="Comments"),
        FieldDef("status_code", required=True, max_length=1, default="A",
                 choices=["A", "I"], label="Status"),
    ],
    dependencies=[
        DependencyDef("location", "inventory_id", "Locations"),
        DependencyDef("item_location", "inventory_id", "Item-Location Assignments"),
        DependencyDef("batchlocation", "inventory_id", "Batch-Location Assignments"),
    ],
))

# -- Locations ---------------------------------------------------------------
_register(TableConfig(
    key="locations",
    db_table="location",
    pk_field="location_id",
    display_name="Locations",
    default_order="location_desc",
    fields=[
        FieldDef("location_id", pk=True, auto_pk=True, db_type="int", label="ID"),
        FieldDef("inventory_id", required=True, db_type="int", label="Inventory",
                 fk_table="inventory", fk_pk="inventory_id", fk_label="inventory_id"),
        FieldDef("location_desc", required=True, max_length=255, searchable=True, label="Location Description"),
        FieldDef("comments_text", max_length=255, label="Comments"),
        FieldDef("status_code", required=True, max_length=1, default="A",
                 choices=["A", "I"], label="Status"),
    ],
    dependencies=[
        DependencyDef("item_location", "location_id", "Item-Location Assignments"),
        DependencyDef("batchlocation", "location_id", "Batch-Location Assignments"),
    ],
))
# ── Warehouses ────────────────────────────────────────────────────────────
_register(TableConfig(
    key="warehouses",
    db_table="warehouse",
    pk_field="warehouse_id",
    display_name="Warehouses",
    default_order="warehouse_name",
    fields=[
        FieldDef("warehouse_id", pk=True, auto_pk=True, db_type="int", label="ID"),
        FieldDef("warehouse_name", required=True, unique=True, max_length=255,
                 searchable=True, label="Warehouse Name"),
        FieldDef("warehouse_type", required=True, max_length=10,
                 choices=["MAIN-HUB", "SUB-HUB"], label="Type"),
        FieldDef("address1_text", required=True, max_length=255, label="Address Line 1"),
        FieldDef("address2_text", max_length=255, label="Address Line 2"),
        FieldDef("parish_code", required=True, max_length=2, label="Parish",
                 fk_table="parish", fk_pk="parish_code", fk_label="parish_name"),
        FieldDef("contact_name", required=True, uppercase=True, max_length=50,
                 searchable=True, label="Contact Name"),
        FieldDef("phone_no", required=True, max_length=20, label="Phone",
                 pattern=r"^\+1 \(\d{3}\) \d{3}-\d{4}$",
                 pattern_message="Format: +1 (XXX) XXX-XXXX"),
        FieldDef("email_text", max_length=100, label="Email",
                 pattern=r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$",
                 pattern_message="Invalid email format"),
        FieldDef("custodian_id", required=True, db_type="int", label="Custodian",
                 fk_table="custodian", fk_pk="custodian_id", fk_label="custodian_name"),
        FieldDef("min_stock_threshold", db_type="numeric", default=0,
                 label="Min Stock Threshold"),
        FieldDef("reason_desc", max_length=255, label="Reason"),
        FieldDef("status_code", required=True, max_length=1, default="A",
                 choices=["A", "I"], label="Status"),
    ],
    dependencies=[
        DependencyDef("inventory", "warehouse_id", "Inventory Records"),
        DependencyDef("agency", "warehouse_id", "Agencies"),
    ],
))

# ── Agencies ──────────────────────────────────────────────────────────────
_register(TableConfig(
    key="agencies",
    db_table="agency",
    pk_field="agency_id",
    display_name="Agencies",
    default_order="agency_name",
    fields=[
        FieldDef("agency_id", pk=True, auto_pk=True, db_type="int", label="ID"),
        FieldDef("agency_name", required=True, unique=True, uppercase=True,
                 max_length=120, searchable=True, label="Agency Name"),
        FieldDef("agency_type", required=True, max_length=16,
                 choices=["SHELTER", "DISTRIBUTOR"], label="Type"),
        FieldDef("address1_text", required=True, max_length=255, label="Address Line 1"),
        FieldDef("address2_text", max_length=255, label="Address Line 2"),
        FieldDef("parish_code", required=True, max_length=2, label="Parish",
                 fk_table="parish", fk_pk="parish_code", fk_label="parish_name"),
        FieldDef("contact_name", required=True, uppercase=True, max_length=50,
                 searchable=True, label="Contact Name"),
        FieldDef("phone_no", required=True, max_length=20, label="Phone",
                 pattern=r"^\+1 \(\d{3}\) \d{3}-\d{4}$",
                 pattern_message="Format: +1 (XXX) XXX-XXXX"),
        FieldDef("email_text", max_length=100, label="Email",
                 pattern=r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$",
                 pattern_message="Invalid email format"),
        FieldDef("warehouse_id", db_type="int", label="Warehouse",
                 fk_table="warehouse", fk_pk="warehouse_id", fk_label="warehouse_name"),
        FieldDef("ineligible_event_id", db_type="int", label="Ineligible Event",
                 fk_table="event", fk_pk="event_id", fk_label="event_name"),
        FieldDef("agency_priority", db_type="int", label="Priority"),
        FieldDef("status_code", required=True, max_length=1, default="A",
                 choices=["A", "I"], label="Status"),
    ],
    dependencies=[
        DependencyDef("reliefrqst", "agency_id", "Relief Requests"),
    ],
))

# ── Custodians ────────────────────────────────────────────────────────────
# NOTE: custodian table has NO status_code column in the live DB.
_register(TableConfig(
    key="custodians",
    db_table="custodian",
    pk_field="custodian_id",
    display_name="Custodians",
    default_order="custodian_name",
    status_field="",  # custodian table has no status column
    fields=[
        FieldDef("custodian_id", pk=True, auto_pk=True, db_type="int", label="ID"),
        FieldDef("custodian_name", required=True, unique=True, uppercase=True,
                 max_length=120, searchable=True, label="Custodian Name"),
        FieldDef("address1_text", required=True, max_length=255, label="Address Line 1"),
        FieldDef("address2_text", max_length=255, label="Address Line 2"),
        FieldDef("parish_code", required=True, max_length=2, label="Parish",
                 fk_table="parish", fk_pk="parish_code", fk_label="parish_name"),
        FieldDef("contact_name", required=True, uppercase=True, max_length=50,
                 searchable=True, label="Contact Name"),
        FieldDef("phone_no", required=True, max_length=20, label="Phone",
                 pattern=r"^\+1 \(\d{3}\) \d{3}-\d{4}$",
                 pattern_message="Format: +1 (XXX) XXX-XXXX"),
        FieldDef("email_text", max_length=100, label="Email",
                 pattern=r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$",
                 pattern_message="Invalid email format"),
    ],
    dependencies=[
        DependencyDef("warehouse", "custodian_id", "Warehouses"),
    ],
))

# ── Donors ────────────────────────────────────────────────────────────────
# NOTE: donor table has NO status_code column in the live DB.
_register(TableConfig(
    key="donors",
    db_table="donor",
    pk_field="donor_id",
    display_name="Donors",
    default_order="donor_name",
    status_field="",  # donor table has no status column
    fields=[
        FieldDef("donor_id", pk=True, auto_pk=True, db_type="int", label="ID"),
        FieldDef("donor_code", required=True, unique=True, uppercase=True,
                 max_length=16, searchable=True, label="Donor Code"),
        FieldDef("donor_name", required=True, unique=True, uppercase=True,
                 max_length=255, searchable=True, label="Donor Name"),
        FieldDef("org_type_desc", max_length=30, label="Organization Type"),
        FieldDef("address1_text", required=True, max_length=255, label="Address Line 1"),
        FieldDef("address2_text", max_length=255, label="Address Line 2"),
        FieldDef("country_id", required=True, db_type="smallint", default=388, label="Country",
                 fk_table="country", fk_pk="country_id", fk_label="country_name"),
        FieldDef("phone_no", required=True, max_length=20, label="Phone",
                 pattern=r"^\+1 \(\d{3}\) \d{3}-\d{4}$",
                 pattern_message="Format: +1 (XXX) XXX-XXXX"),
        FieldDef("email_text", max_length=100, label="Email",
                 pattern=r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$",
                 pattern_message="Invalid email format"),
    ],
    dependencies=[
        DependencyDef("donation", "donor_id", "Donations"),
    ],
))

# ── Events ────────────────────────────────────────────────────────────────
_register(TableConfig(
    key="events",
    db_table="event",
    pk_field="event_id",
    display_name="Events",
    default_order="start_date DESC",
    active_status="A",
    inactive_status="C",
    fields=[
        FieldDef("event_id", pk=True, auto_pk=True, db_type="int", label="ID"),
        FieldDef("event_type", required=True, max_length=16, label="Event Type",
                 choices=["STORM", "HURRICANE", "TORNADO", "FLOOD", "TSUNAMI",
                          "FIRE", "EARTHQUAKE", "WAR", "EPIDEMIC", "ADHOC"]),
        FieldDef("start_date", required=True, db_type="date", label="Start Date"),
        FieldDef("event_name", required=True, max_length=60,
                 searchable=True, label="Event Name"),
        FieldDef("event_desc", required=True, max_length=255,
                 searchable=True, label="Description"),
        FieldDef("impact_desc", required=True, label="Impact Description"),
        FieldDef("status_code", required=True, max_length=1, default="A",
                 choices=["A", "C"], label="Status"),
        FieldDef("closed_date", db_type="date", label="Closed Date"),
        FieldDef("reason_desc", max_length=255, label="Closure Reason"),
        FieldDef("current_phase", max_length=15, default="BASELINE",
                 choices=["BASELINE", "SURGE", "STABILIZED"],
                 readonly=True, label="Current Phase"),
        FieldDef("phase_changed_at", db_type="timestamp", readonly=True,
                 label="Phase Changed At"),
        FieldDef("phase_changed_by", max_length=20, readonly=True,
                 label="Phase Changed By"),
    ],
    dependencies=[
        DependencyDef("reliefrqst", "event_id", "Relief Requests"),
    ],
))

# ── Countries ─────────────────────────────────────────────────────────────
_register(TableConfig(
    key="countries",
    db_table="country",
    pk_field="country_id",
    display_name="Countries",
    default_order="country_name",
    fields=[
        FieldDef("country_id", pk=True, auto_pk=True, db_type="smallint", label="ID"),
        FieldDef("country_name", required=True, unique=True, max_length=80,
                 searchable=True, label="Country Name"),
        FieldDef("currency_code", required=True, max_length=10, label="Currency",
                 fk_table="currency", fk_pk="currency_code", fk_label="currency_name"),
        FieldDef("status_code", required=True, max_length=1, default="A",
                 choices=["A", "I"], label="Status"),
    ],
    dependencies=[
        DependencyDef("donor", "country_id", "Donors"),
    ],
))

# ── Currencies ────────────────────────────────────────────────────────────
_register(TableConfig(
    key="currencies",
    db_table="currency",
    pk_field="currency_code",
    display_name="Currencies",
    default_order="currency_code",
    fields=[
        FieldDef("currency_code", pk=True, required=True, unique=True,
                 uppercase=True, max_length=10, searchable=True, label="Code"),
        FieldDef("currency_name", required=True, max_length=60,
                 searchable=True, label="Currency Name"),
        FieldDef("currency_sign", required=True, max_length=6, label="Sign"),
        FieldDef("status_code", required=True, max_length=1, default="A",
                 choices=["A", "I"], label="Status"),
    ],
    dependencies=[
        DependencyDef("country", "currency_code", "Countries"),
    ],
))

# ── Parishes ──────────────────────────────────────────────────────────────
# NOTE: parish table only has parish_code and parish_name. No status, audit, or version.
_register(TableConfig(
    key="parishes",
    db_table="parish",
    pk_field="parish_code",
    display_name="Parishes",
    default_order="parish_name",
    status_field="",
    has_audit=False,
    has_version=False,
    fields=[
        FieldDef("parish_code", pk=True, required=True, unique=True,
                 uppercase=True, max_length=2, searchable=True, label="Code"),
        FieldDef("parish_name", required=True, max_length=40,
                 searchable=True, label="Parish Name"),
    ],
    dependencies=[
        DependencyDef("warehouse", "parish_code", "Warehouses"),
        DependencyDef("agency", "parish_code", "Agencies"),
        DependencyDef("custodian", "parish_code", "Custodians"),
    ],
))

# ── Suppliers ─────────────────────────────────────────────────────────────
_register(TableConfig(
    key="suppliers",
    db_table="supplier",
    pk_field="supplier_id",
    display_name="Suppliers",
    default_order="supplier_name",
    fields=[
        FieldDef("supplier_id", pk=True, auto_pk=True, db_type="int", label="ID"),
        FieldDef("supplier_code", required=True, unique=True, uppercase=True,
                 max_length=20, searchable=True, label="Supplier Code"),
        FieldDef("supplier_name", required=True, unique=True, max_length=120,
                 searchable=True, label="Supplier Name"),
        FieldDef("contact_name", max_length=80, searchable=True, label="Contact Name"),
        FieldDef("phone_no", max_length=20, label="Phone"),
        FieldDef("email_text", max_length=100, label="Email",
                 pattern=r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$",
                 pattern_message="Invalid email format"),
        FieldDef("address_text", max_length=255, label="Address"),
        FieldDef("parish_code", max_length=2, label="Parish",
                 fk_table="parish", fk_pk="parish_code", fk_label="parish_name"),
        FieldDef("country_id", db_type="int", label="Country",
                 fk_table="country", fk_pk="country_id", fk_label="country_name"),
        FieldDef("default_lead_time_days", db_type="int", default=14,
                 label="Default Lead Time (days)"),
        FieldDef("is_framework_supplier", db_type="boolean", default=False,
                 label="Framework Supplier"),
        FieldDef("framework_contract_no", max_length=50, label="Framework Contract No."),
        FieldDef("framework_expiry_date", db_type="date", label="Framework Expiry Date"),
        FieldDef("trn_no", max_length=30, label="TRN"),
        FieldDef("tcc_no", max_length=30, label="TCC"),
        FieldDef("status_code", required=True, max_length=1, default="A",
                 choices=["A", "I"], label="Status"),
    ],
    dependencies=[
        DependencyDef("procurement", "supplier_id", "Procurement Orders"),
    ],
))


# ---------------------------------------------------------------------------
# Generic CRUD operations
# ---------------------------------------------------------------------------

def get_table_config(table_key: str) -> TableConfig | None:
    return TABLE_REGISTRY.get(table_key)


def _parse_sort_expression(
    sort_expr: str | None,
    *,
    allowed_columns: dict[str, str],
) -> str | None:
    """
    Parse and normalize a sortable expression to:
      "<column> ASC|DESC"

    Accepted forms:
      - "column"
      - "column ASC"
      - "column DESC"
      - "-column"
    """
    if not sort_expr:
        return None

    sort_expr = sort_expr.strip()
    if not sort_expr:
        return None

    if sort_expr.startswith("-"):
        col = sort_expr[1:].strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", col):
            return None
        normalized_col = allowed_columns.get(col.lower())
        if not normalized_col:
            return None
        return f"{normalized_col} DESC"

    match = _ORDER_BY_PATTERN.fullmatch(sort_expr)
    if not match:
        return None

    col = match.group("column")
    normalized_col = allowed_columns.get(col.lower())
    if not normalized_col:
        return None

    direction = (match.group("direction") or "ASC").upper()
    return f"{normalized_col} {direction}"


def _resolve_order_by(cfg: TableConfig, requested_order_by: str | None) -> Tuple[str, bool]:
    """
    Resolve a safe ORDER BY expression from request + table config.
    Returns (<order_sql>, <requested_order_was_invalid>).
    """
    allowed_columns = {fd.name.lower(): fd.name for fd in cfg.fields}
    requested = _parse_sort_expression(requested_order_by, allowed_columns=allowed_columns)
    explicit_requested = bool(requested_order_by and requested_order_by.strip())
    if requested:
        return requested, False

    default_order = _parse_sort_expression(cfg.default_order, allowed_columns=allowed_columns)
    if default_order:
        return default_order, explicit_requested

    logger.warning(
        "Invalid default_order=%r for table=%s; falling back to %s ASC",
        cfg.default_order,
        cfg.key,
        cfg.pk_field,
    )
    pk_col = allowed_columns.get(cfg.pk_field.lower(), cfg.pk_field)
    return f"{pk_col} ASC", explicit_requested


def list_records(
    table_key: str,
    *,
    status_filter: str | None = None,
    search: str | None = None,
    order_by: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> Tuple[List[Dict[str, Any]], int, List[str]]:
    """
    Paginated list with optional status filter and search.
    Returns (rows, total_count, warnings).
    """
    cfg = TABLE_REGISTRY[table_key]
    if _is_sqlite():
        return [], 0, ["db_unavailable"]

    schema = _schema_name()
    warnings: List[str] = []
    columns = ", ".join(f.name for f in cfg.fields)
    where_clauses: list[str] = []
    params: list[Any] = []

    if status_filter and cfg.has_status:
        where_clauses.append(f"{cfg.status_field} = %s")
        params.append(status_filter)

    if search and cfg.searchable_fields:
        search_conditions = " OR ".join(
            f"UPPER({f.name}) LIKE %s" for f in cfg.searchable_fields
        )
        where_clauses.append(f"({search_conditions})")
        search_param = f"%{search.upper()}%"
        params.extend([search_param] * len(cfg.searchable_fields))

    where_sql = ""
    if where_clauses:
        where_sql = "WHERE " + " AND ".join(where_clauses)

    sort_col, invalid_order_by = _resolve_order_by(cfg, order_by)
    if invalid_order_by:
        warnings.append("invalid_order_by")
    count_params = list(params)

    try:
        with connection.cursor() as cursor:
            # Total count
            cursor.execute(
                f"SELECT COUNT(*) FROM {schema}.{cfg.db_table} {where_sql}",
                count_params,
            )
            total = cursor.fetchone()[0]

            # Rows
            cursor.execute(
                f"""
                SELECT {columns}
                FROM {schema}.{cfg.db_table}
                {where_sql}
                ORDER BY {sort_col}
                LIMIT %s OFFSET %s
                """,
                params + [limit, offset],
            )
            col_names = [f.name for f in cfg.fields]
            rows = [dict(zip(col_names, row)) for row in cursor.fetchall()]

        return rows, total, warnings
    except DatabaseError as exc:
        logger.warning("list_records(%s) failed: %s", table_key, exc)
        try:
            connection.rollback()
        except Exception:
            pass
        return [], 0, ["db_error"]


def get_record(
    table_key: str, pk_value: Any
) -> Tuple[Dict[str, Any] | None, List[str]]:
    """Fetch a single record by PK."""
    cfg = TABLE_REGISTRY[table_key]
    if _is_sqlite():
        return None, ["db_unavailable"]

    schema = _schema_name()
    columns = ", ".join(f.name for f in cfg.fields)
    # Include audit + version columns if present
    extra_cols: list[str] = []
    if cfg.has_audit:
        extra_cols.extend([
            cfg.audit_create_user, cfg.audit_create_time,
            cfg.audit_update_user, cfg.audit_update_time,
        ])
    if cfg.has_version:
        extra_cols.append(cfg.version_field)
    all_cols = columns
    if extra_cols:
        all_cols += ", " + ", ".join(extra_cols)

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {all_cols}
                FROM {schema}.{cfg.db_table}
                WHERE {cfg.pk_field} = %s
                """,
                [pk_value],
            )
            row = cursor.fetchone()
            if not row:
                return None, []

            col_names = [f.name for f in cfg.fields] + extra_cols
            return dict(zip(col_names, row)), []
    except DatabaseError as exc:
        logger.warning("get_record(%s, %s) failed: %s", table_key, pk_value, exc)
        try:
            connection.rollback()
        except Exception:
            pass
        return None, ["db_error"]


def _normalize_field_value(fd: FieldDef, value: Any) -> Any:
    if fd.empty_as_null and isinstance(value, str):
        value = value.strip()
        if not value:
            return None
    if fd.uppercase and isinstance(value, str):
        value = value.strip().upper()
    if fd.name == "email_text" and isinstance(value, str):
        value = value.strip().lower()
    return value


def _normalize_workflow_state(workflow_state: str) -> str:
    normalized = str(workflow_state or "").strip().upper()
    if not normalized:
        return "UNKNOWN"
    return _WORKFLOW_STATE_ALIASES.get(normalized, normalized)


def _is_forward_write_guarded_state(table_key: str, workflow_state: str) -> Tuple[bool, str]:
    normalized_table = str(table_key or "").strip().lower()
    normalized_state = _normalize_workflow_state(workflow_state)

    if normalized_table in _FORWARD_WRITE_BLOCK_ALWAYS_TABLES:
        return True, "ALWAYS"

    allowed_states = _FORWARD_WRITE_STATE_TABLES.get(normalized_table)
    if not allowed_states:
        return False, normalized_state

    return normalized_state in allowed_states, normalized_state


def _guard_inactive_item_forward_write(
    *,
    table_key: str,
    item_id: Any,
    workflow_state: str,
) -> Tuple[bool, List[str]]:
    """
    Enforce inactive-item forward-write guardrails for write paths.

    Returns ``(allowed, warnings)``. For non-guarded table keys, always allowed.
    """
    should_guard, normalized_state = _is_forward_write_guarded_state(
        table_key,
        workflow_state,
    )
    if not should_guard:
        return True, []
    if item_id in (None, ""):
        return True, []
    if _is_sqlite():
        # Keep local sqlite test/dev mode permissive.
        return True, []

    schema = _schema_name()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT status_code
                FROM {schema}.item
                WHERE item_id = %s
                LIMIT 1
                """,
                [item_id],
            )
            row = cursor.fetchone()
    except DatabaseError as exc:
        logger.warning("Item status lookup failed for item_id=%s: %s", item_id, exc)
        _safe_rollback()
        return False, ["item_status_lookup_failed"]

    if not row:
        # FK validation handles missing item IDs separately.
        return True, []

    status_code = str(row[0] or "").strip().upper()
    if status_code == "A":
        return True, []

    return False, [
        INACTIVE_ITEM_FORWARD_WRITE_CODE,
        f"inactive_item_id_{item_id}",
        f"forward_write_table_{table_key}",
        f"forward_write_workflow_{normalized_state}",
    ]


def _lookup_inventory_item_id(inventory_id: Any) -> Tuple[Any | None, List[str]]:
    """
    Resolve ``item_id`` for an inventory record to enforce item-status guardrails
    even when update payloads do not include ``item_id``.
    """
    if _is_sqlite():
        return None, []

    schema = _schema_name()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT item_id
                FROM {schema}.inventory
                WHERE inventory_id = %s
                LIMIT 1
                """,
                [inventory_id],
            )
            row = cursor.fetchone()
    except DatabaseError as exc:
        logger.warning(
            "Inventory item lookup failed for inventory_id=%s: %s",
            inventory_id,
            exc,
        )
        _safe_rollback()
        return None, ["inventory_item_lookup_failed"]

    if not row:
        return None, []
    return row[0], []


def _execute_create_insert(
    cfg: "TableConfig",
    schema: str,
    col_sql: str,
    ph_sql: str,
    final_values: list[Any],
    data: Dict[str, Any],
) -> Any | None:
    returning = f"RETURNING {cfg.pk_field}" if cfg._pk_def and cfg._pk_def.auto_pk else ""
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                INSERT INTO {schema}.{cfg.db_table} ({col_sql})
                VALUES ({ph_sql})
                {returning}
                """,
                final_values,
            )
            if returning:
                row = cursor.fetchone()
                return row[0] if row else None
            return data.get(cfg.pk_field)


def create_record(
    table_key: str, data: Dict[str, Any], actor_id: str
) -> Tuple[Any | None, List[str]]:
    """
    Insert a new record. Returns (pk_value, warnings).
    For auto-PK tables returns the generated PK.
    For string-PK tables the PK comes from data.
    """
    cfg = TABLE_REGISTRY[table_key]
    if _is_sqlite():
        return None, ["db_unavailable"]

    schema = _schema_name()
    warnings: List[str] = []

    # Inactive item guardrail (inventory creation).
    workflow_state = str(data.get("workflow_state") or "ALWAYS")
    allow_write, guard_warnings = _guard_inactive_item_forward_write(
        table_key=table_key,
        item_id=data.get("item_id"),
        workflow_state=workflow_state,
    )
    warnings.extend(guard_warnings)
    if not allow_write:
        return None, warnings

    # Build column/value lists
    columns: list[str] = []
    values: list[Any] = []

    for fd in cfg.data_fields:
        if fd.auto_pk:
            continue
        if fd.name in data:
            val = _normalize_field_value(fd, data[fd.name])
            columns.append(fd.name)
            values.append(val)
        elif fd.default is not None:
            columns.append(fd.name)
            values.append(fd.default)

    # Audit columns
    if cfg.has_audit:
        columns.extend([cfg.audit_create_user, cfg.audit_create_time,
                         cfg.audit_update_user, cfg.audit_update_time])
        values.extend([actor_id, "NOW()", actor_id, "NOW()"])
    if cfg.has_version:
        columns.append(cfg.version_field)
        values.append(1)

    # Build SQL -- handle NOW() literals
    placeholders = []
    final_values = []
    for col, val in zip(columns, values):
        if val == "NOW()":
            placeholders.append("NOW()")
        else:
            placeholders.append("%s")
            final_values.append(val)

    col_sql = ", ".join(columns)
    ph_sql = ", ".join(placeholders)

    try:
        pk_val = _execute_create_insert(
            cfg,
            schema,
            col_sql,
            ph_sql,
            final_values,
            data,
        )
        return pk_val, warnings
    except DatabaseError as exc:
        if _is_auto_pk_duplicate_violation(table_key, exc):
            _safe_rollback()
            recovered, _info, recovery_warnings = resync_auto_pk_sequence(table_key)
            warnings.extend(recovery_warnings)
            if recovered:
                try:
                    pk_val = _execute_create_insert(
                        cfg,
                        schema,
                        col_sql,
                        ph_sql,
                        final_values,
                        data,
                    )
                    return pk_val, warnings
                except DatabaseError as retry_exc:
                    exc = retry_exc
        logger.warning("create_record(%s) failed: %s", table_key, exc)
        warnings.extend(_db_error_warnings(exc))
        return None, warnings


def update_record(
    table_key: str,
    pk_value: Any,
    data: Dict[str, Any],
    actor_id: str,
    expected_version: int | None = None,
) -> Tuple[bool, List[str]]:
    """
    Update a record with optimistic locking.
    Returns (success, warnings).
    """
    cfg = TABLE_REGISTRY[table_key]
    if _is_sqlite():
        return False, ["db_unavailable"]

    schema = _schema_name()
    warnings: List[str] = []

    # Inactive item guardrail:
    # - inventory writes always enforce against the associated item
    # - other tables enforce only when item_id is explicitly present in payload
    guard_item_id = data.get("item_id")
    if table_key == "inventory" and "item_id" not in data:
        guard_item_id, lookup_warnings = _lookup_inventory_item_id(pk_value)
        warnings.extend(lookup_warnings)
        if "inventory_item_lookup_failed" in lookup_warnings:
            return False, warnings

    workflow_state = str(data.get("workflow_state") or "ALWAYS")
    if table_key == "inventory" or "item_id" in data:
        allow_write, guard_warnings = _guard_inactive_item_forward_write(
            table_key=table_key,
            item_id=guard_item_id,
            workflow_state=workflow_state,
        )
        warnings.extend(guard_warnings)
        if not allow_write:
            return False, warnings

    set_parts: list[str] = []
    params: list[Any] = []

    for fd in cfg.data_fields:
        if fd.pk or fd.readonly:
            continue
        if fd.name in data:
            val = _normalize_field_value(fd, data[fd.name])
            set_parts.append(f"{fd.name} = %s")
            params.append(val)

    if not set_parts:
        return False, ["no_fields_to_update"]

    # Audit
    if cfg.has_audit:
        set_parts.append(f"{cfg.audit_update_user} = %s")
        params.append(actor_id)
        set_parts.append(f"{cfg.audit_update_time} = NOW()")
    if cfg.has_version:
        set_parts.append(f"{cfg.version_field} = {cfg.version_field} + 1")

    set_sql = ", ".join(set_parts)

    # WHERE with optimistic lock
    where_parts = [f"{cfg.pk_field} = %s"]
    params.append(pk_value)

    if expected_version is not None and cfg.has_version:
        where_parts.append(f"{cfg.version_field} = %s")
        params.append(expected_version)

    where_sql = " AND ".join(where_parts)

    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    UPDATE {schema}.{cfg.db_table}
                    SET {set_sql}
                    WHERE {where_sql}
                    """,
                    params,
                )
                if cursor.rowcount == 0:
                    if expected_version is not None and cfg.has_version:
                        warnings.append("version_conflict")
                    else:
                        warnings.append("not_found")
                    return False, warnings
                return True, warnings
    except DatabaseError as exc:
        logger.warning("update_record(%s, %s) failed: %s", table_key, pk_value, exc)
        warnings.extend(_db_error_warnings(exc))
        return False, warnings


def inactivate_record(
    table_key: str,
    pk_value: Any,
    actor_id: str,
    expected_version: int | None = None,
) -> Tuple[bool, List[str]]:
    """Soft-delete by setting status to inactive."""
    cfg = TABLE_REGISTRY[table_key]
    if not cfg.has_status:
        return False, ["no_status_field"]
    return update_record(
        table_key, pk_value,
        {cfg.status_field: cfg.inactive_status},
        actor_id, expected_version,
    )


def activate_record(
    table_key: str,
    pk_value: Any,
    actor_id: str,
    expected_version: int | None = None,
) -> Tuple[bool, List[str]]:
    """Reactivate by setting status to active."""
    cfg = TABLE_REGISTRY[table_key]
    if not cfg.has_status:
        return False, ["no_status_field"]
    return update_record(
        table_key, pk_value,
        {cfg.status_field: cfg.active_status},
        actor_id, expected_version,
    )


def get_summary_counts(table_key: str) -> Tuple[Dict[str, int], List[str]]:
    """Returns {total, active, inactive} counts."""
    cfg = TABLE_REGISTRY[table_key]
    if _is_sqlite():
        return {"total": 0, "active": 0, "inactive": 0}, ["db_unavailable"]

    schema = _schema_name()
    try:
        with connection.cursor() as cursor:
            if cfg.has_status:
                cursor.execute(
                    f"""
                    SELECT
                        COUNT(*) AS total,
                        COUNT(*) FILTER (WHERE {cfg.status_field} = %s) AS active,
                        COUNT(*) FILTER (WHERE {cfg.status_field} = %s) AS inactive
                    FROM {schema}.{cfg.db_table}
                    """,
                    [cfg.active_status, cfg.inactive_status],
                )
                row = cursor.fetchone()
                return {
                    "total": row[0],
                    "active": row[1],
                    "inactive": row[2],
                }, []
            else:
                cursor.execute(
                    f"SELECT COUNT(*) FROM {schema}.{cfg.db_table}"
                )
                total = cursor.fetchone()[0]
                return {"total": total, "active": total, "inactive": 0}, []
    except DatabaseError as exc:
        logger.warning("get_summary_counts(%s) failed: %s", table_key, exc)
        try:
            connection.rollback()
        except Exception:
            pass
        return {"total": 0, "active": 0, "inactive": 0}, ["db_error"]


def get_lookup(
    table_key: str, *, active_only: bool = True
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Minimal {value, label} list for FK dropdowns.
    """
    cfg = TABLE_REGISTRY[table_key]
    if _is_sqlite():
        return [], ["db_unavailable"]

    schema = _schema_name()
    # Find the best label column (first searchable, or first non-pk non-status)
    label_field = None
    for fd in cfg.fields:
        if fd.searchable and not fd.pk:
            label_field = fd.name
            break
    if not label_field:
        for fd in cfg.fields:
            if not fd.pk and fd.name != cfg.status_field:
                label_field = fd.name
                break
    if not label_field:
        label_field = cfg.pk_field

    where = ""
    params: list[Any] = []
    if active_only and cfg.has_status:
        where = f"WHERE {cfg.status_field} = %s"
        params.append(cfg.active_status)

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {cfg.pk_field}, {label_field}
                FROM {schema}.{cfg.db_table}
                {where}
                ORDER BY {label_field}
                """,
                params,
            )
            rows = [
                {"value": row[0], "label": str(row[1]) if row[1] else str(row[0])}
                for row in cursor.fetchall()
            ]
            return rows, []
    except DatabaseError as exc:
        logger.warning("get_lookup(%s) failed: %s", table_key, exc)
        try:
            connection.rollback()
        except Exception:
            pass
        return [], ["db_error"]


def _workflow_state_tokens(*states: str) -> List[str]:
    tokens: set[str] = set()
    for state in states:
        normalized = _normalize_workflow_state(state)
        if normalized:
            tokens.add(normalized)
        for raw, mapped in _WORKFLOW_STATE_ALIASES.items():
            if mapped == normalized:
                tokens.add(raw)
    return sorted({token.upper() for token in tokens if token})


def _run_dependency_count(
    *,
    schema: str,
    sql_from_where: str,
    params: List[Any],
    status_column: str | None = None,
    statuses: List[str] | None = None,
) -> int:
    where_sql = sql_from_where
    final_params = list(params)
    if status_column and statuses:
        placeholders = ", ".join(["%s"] * len(statuses))
        where_sql += f" AND UPPER(COALESCE({status_column}, '')) IN ({placeholders})"
        final_params.extend(statuses)

    with connection.cursor() as cursor:
        cursor.execute(f"SELECT COUNT(*) {where_sql}", final_params)
        row = cursor.fetchone()
        return int(row[0] or 0) if row else 0


def _check_item_forward_write_dependencies(item_id: Any) -> Tuple[List[str], List[str]]:
    """
    Status-scoped dependency checks for item inactivation.
    Implements the approved inactive-item forward-write matrix.
    """
    schema = _schema_name()
    blocking: List[str] = []
    warnings: List[str] = []

    active_statuses = ["A", "ACTIVE"]
    draft_pending_statuses = _workflow_state_tokens("DRAFT", "PENDING")
    draft_generation_statuses = _workflow_state_tokens("DRAFT", "DRAFT_GENERATION")
    entered_pending_statuses = _workflow_state_tokens("ENTERED", "PENDING")
    draft_statuses = _workflow_state_tokens("DRAFT")

    rules = [
        {
            "table": "inventory",
            "label": "Inventory Records",
            "sql": f"FROM {schema}.inventory inv WHERE inv.item_id = %s",
            "status_col": "inv.status_code",
            "statuses": active_statuses,
        },
        {
            "table": "itembatch",
            "label": "Inventory Batches",
            "sql": f"FROM {schema}.itembatch ib WHERE ib.item_id = %s",
            "status_col": "ib.status_code",
            "statuses": active_statuses,
        },
        {
            "table": "item_location",
            "label": "Item-Location Assignments",
            "sql": (
                f"FROM {schema}.item_location il "
                f"JOIN {schema}.inventory inv ON inv.inventory_id = il.inventory_id "
                "WHERE inv.item_id = %s"
            ),
            "status_col": "inv.status_code",
            "statuses": active_statuses,
        },
        {
            "table": "transfer_item",
            "label": "Draft/Pending Transfers",
            "sql": (
                f"FROM {schema}.transfer_item ti "
                f"JOIN {schema}.transfer t ON t.transfer_id = ti.transfer_id "
                "WHERE ti.item_id = %s"
            ),
            "status_col": "t.status_code",
            "statuses": draft_pending_statuses,
        },
        {
            "table": "needs_list_item",
            "label": "Draft Needs Lists",
            "sql": (
                f"FROM {schema}.needs_list_item nli "
                f"JOIN {schema}.needs_list nl ON nl.needs_list_id = nli.needs_list_id "
                "WHERE nli.item_id = %s"
            ),
            "status_col": "nl.status_code",
            "statuses": draft_generation_statuses,
        },
        {
            "table": "donation_item",
            "label": "Entered/Pending Donations",
            "sql": (
                f"FROM {schema}.donation_item di "
                f"JOIN {schema}.donation d ON d.donation_id = di.donation_id "
                "WHERE di.item_id = %s"
            ),
            "status_col": "d.status_code",
            "statuses": entered_pending_statuses,
        },
        {
            "table": "procurement_item",
            "label": "Draft Procurements",
            "sql": (
                f"FROM {schema}.procurement_item pi "
                f"JOIN {schema}.procurement p ON p.procurement_id = pi.procurement_id "
                "WHERE pi.item_id = %s"
            ),
            "status_col": "p.status_code",
            "statuses": draft_statuses,
        },
        {
            "table": "reliefpkg_item",
            "label": "Draft Relief Packages",
            "sql": (
                f"FROM {schema}.reliefpkg_item rpi "
                f"JOIN {schema}.reliefpkg rp ON rp.reliefpkg_id = rpi.reliefpkg_id "
                "WHERE rpi.item_id = %s"
            ),
            "status_col": "rp.status_code",
            "statuses": draft_statuses,
        },
        {
            "table": "reliefrqst_item",
            "label": "Draft Relief Requests",
            "sql": (
                f"FROM {schema}.reliefrqst_item rri "
                f"JOIN {schema}.reliefrqst rr ON rr.reliefrqst_id = rri.reliefrqst_id "
                "WHERE rri.item_id = %s"
            ),
            "status_col": "rr.status_code",
            "statuses": draft_statuses,
        },
    ]

    for rule in rules:
        try:
            count = _run_dependency_count(
                schema=schema,
                sql_from_where=rule["sql"],
                params=[item_id],
                status_column=rule["status_col"],
                statuses=rule["statuses"],
            )
            if count > 0:
                blocking.append(f"{rule['label']} ({count} records)")
        except DatabaseError as exc:
            logger.warning(
                "check_dependencies(items, %s) query on %s failed: %s",
                item_id,
                rule["table"],
                exc,
            )
            warnings.append(f"dependency_check_failed_{rule['table']}")
            _safe_rollback()

    return blocking, warnings


def check_dependencies(
    table_key: str, pk_value: Any
) -> Tuple[List[str], List[str]]:
    """
    Check referential integrity before inactivation.
    Returns (blocking_labels, warnings).
    blocking_labels is a list of human-readable names of tables with active references.
    """
    cfg = TABLE_REGISTRY[table_key]
    if _is_sqlite():
        return [], ["db_unavailable"]

    if table_key == "items":
        return _check_item_forward_write_dependencies(pk_value)

    schema = _schema_name()
    blocking: List[str] = []
    warnings: List[str] = []

    for dep in cfg.dependencies:
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM {schema}.{dep.table}
                    WHERE {dep.fk_column} = %s
                    """,
                    [pk_value],
                )
                count = cursor.fetchone()[0]
                if count > 0:
                    blocking.append(f"{dep.label} ({count} records)")
        except DatabaseError as exc:
            logger.warning(
                "check_dependencies(%s, %s) query on %s failed: %s",
                table_key, pk_value, dep.table, exc,
            )
            warnings.append(f"dependency_check_failed_{dep.table}")
            _safe_rollback()

    return blocking, warnings


def check_uniqueness(
    table_key: str,
    field_name: str,
    value: Any,
    exclude_pk: Any = None,
) -> Tuple[bool, List[str]]:
    """
    Check if a value is unique for a given field.
    Returns (is_unique, warnings).
    """
    cfg = TABLE_REGISTRY[table_key]
    fd = cfg.field(field_name)
    if not fd:
        logger.warning(
            "check_uniqueness(%s.%s): invalid field_name",
            table_key,
            field_name,
        )
        return True, ["invalid_field"]

    if _is_sqlite():
        return True, ["db_unavailable"]

    schema = _schema_name()
    safe_field_name = fd.name
    where_parts = [f"UPPER({safe_field_name}) = UPPER(%s)"]
    params: list[Any] = [value]

    if exclude_pk is not None:
        where_parts.append(f"{cfg.pk_field} != %s")
        params.append(exclude_pk)

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT COUNT(*)
                FROM {schema}.{cfg.db_table}
                WHERE {" AND ".join(where_parts)}
                """,
                params,
            )
            count = cursor.fetchone()[0]
            return count == 0, []
    except DatabaseError as exc:
        logger.warning("check_uniqueness(%s.%s) failed: %s", table_key, field_name, exc)
        return True, ["db_error"]


def check_fk_exists(
    fk_table: str, fk_pk: str, value: Any
) -> Tuple[bool, List[str]]:
    """Check that a foreign key value exists in the referenced table."""
    if _is_sqlite():
        return True, ["db_unavailable"]

    schema = _schema_name()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT 1 FROM {schema}.{fk_table} WHERE {fk_pk} = %s LIMIT 1",
                [value],
            )
            return cursor.fetchone() is not None, []
    except DatabaseError as exc:
        logger.warning("check_fk_exists(%s.%s=%s) failed: %s", fk_table, fk_pk, value, exc)
        return True, ["db_error"]




