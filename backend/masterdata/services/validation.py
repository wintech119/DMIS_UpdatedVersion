"""
Server-side validation for master data records.

Returns ``{field_name: error_message}`` dicts that the views map back to
the Angular form controls via ``control.setErrors({server: msg})``.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Dict, List, Tuple

from masterdata.services.data_access import (
    TableConfig,
    check_fk_exists,
    check_uniqueness,
)


def validate_record(
    cfg: TableConfig,
    data: Dict[str, Any],
    *,
    is_update: bool = False,
    current_pk: Any = None,
    existing_record: Dict[str, Any] | None = None,
) -> Dict[str, str]:
    """
    Run all field-level validations against *data*.
    Returns a dict of ``{field: message}``; empty dict means valid.
    """
    errors: Dict[str, str] = {}

    for fd in cfg.data_fields:
        if fd.auto_pk:
            continue
        if is_update and fd.readonly:
            continue

        value = data.get(fd.name)

        # Required check
        if fd.required and not is_update:
            if value is None or (isinstance(value, str) and not value.strip()):
                errors[fd.name] = f"{fd.label} is required."
                continue
        if fd.required and is_update and fd.name in data:
            if value is None or (isinstance(value, str) and not value.strip()):
                errors[fd.name] = f"{fd.label} is required."
                continue

        if value is None or (isinstance(value, str) and not value.strip()):
            continue

        # String validations
        if isinstance(value, str):
            value = value.strip()

            # Max length
            if fd.max_length and len(value) > fd.max_length:
                errors[fd.name] = (
                    f"{fd.label} must be at most {fd.max_length} characters."
                )
                continue

            # Pattern
            if fd.pattern and not re.fullmatch(fd.pattern, value, re.IGNORECASE):
                errors[fd.name] = fd.pattern_message or f"{fd.label} has invalid format."
                continue

        # Choices
        if fd.choices:
            check_val = value.upper() if isinstance(value, str) else value
            if check_val not in fd.choices:
                errors[fd.name] = (
                    f"{fd.label} must be one of: {', '.join(str(c) for c in fd.choices)}."
                )
                continue

        # Numeric > 0 check for reorder_qty, lead time, etc.
        if fd.db_type == "numeric" and fd.name == "reorder_qty":
            try:
                if float(value) <= 0:
                    errors[fd.name] = f"{fd.label} must be greater than zero."
                    continue
            except (ValueError, TypeError):
                errors[fd.name] = f"{fd.label} must be a number."
                continue

        # Uniqueness
        if fd.unique and fd.name in data:
            exclude = current_pk if is_update else None
            is_unique, _ = check_uniqueness(cfg.key, fd.name, value, exclude)
            if not is_unique:
                errors[fd.name] = f"{fd.label} already exists."
                continue

        # FK existence
        if fd.fk_table and value is not None:
            exists, _ = check_fk_exists(fd.fk_table, fd.fk_pk, value)
            if not exists:
                errors[fd.name] = f"Selected {fd.label} does not exist."
                continue

    # Cross-field validations
    errors.update(
        _cross_field_validation(
            cfg,
            data,
            is_update=is_update,
            existing_record=existing_record,
        )
    )

    return errors


def _cross_field_validation(
    cfg: TableConfig,
    data: Dict[str, Any],
    *,
    is_update: bool = False,
    existing_record: Dict[str, Any] | None = None,
) -> Dict[str, str]:
    """Business rules that span multiple fields."""
    errors: Dict[str, str] = {}

    def _merged_value(field_name: str):
        if field_name in data:
            return data.get(field_name)
        if is_update and existing_record is not None:
            return existing_record.get(field_name)
        return None

    def _merged_text(field_name: str) -> str:
        return str(_merged_value(field_name) or "").strip()

    # Events: closed_date/reason required when status=C
    if cfg.key == "events":
        status = _merged_text("status_code").upper()
        closed_date = _merged_value("closed_date")
        reason_desc = _merged_text("reason_desc")
        if status == "C":
            if not closed_date:
                errors["closed_date"] = "Closed date is required when closing an event."
            if not reason_desc:
                errors["reason_desc"] = "Reason is required when closing an event."
            # closed_date >= start_date
            cd = closed_date
            sd = _merged_value("start_date")
            if cd and sd:
                try:
                    cd_date = cd if isinstance(cd, date) else date.fromisoformat(str(cd))
                    sd_date = sd if isinstance(sd, date) else date.fromisoformat(str(sd))
                    if cd_date < sd_date:
                        errors["closed_date"] = "Closed date cannot be before start date."
                except (ValueError, TypeError):
                    pass
        elif status == "A":
            if closed_date:
                errors["closed_date"] = "Closed date must be empty for active events."
            if reason_desc:
                errors["reason_desc"] = "Reason must be empty for active events."

        # start_date not in future
        sd = _merged_value("start_date")
        if sd:
            try:
                sd_date = sd if isinstance(sd, date) else date.fromisoformat(str(sd))
                if sd_date > date.today():
                    errors["start_date"] = "Start date cannot be in the future."
            except (ValueError, TypeError):
                errors["start_date"] = "Invalid date format."

    # Agencies: DISTRIBUTOR requires warehouse, SHELTER must not have warehouse
    if cfg.key == "agencies":
        agency_type = _merged_text("agency_type").upper()
        warehouse_id = _merged_text("warehouse_id")
        if agency_type == "DISTRIBUTOR" and not warehouse_id:
            errors["warehouse_id"] = "Warehouse is required for DISTRIBUTOR agencies."
        if agency_type == "SHELTER" and warehouse_id:
            errors["warehouse_id"] = "SHELTER agencies cannot have a warehouse."

    # Warehouses: reason required when status=I
    if cfg.key == "warehouses":
        status = str(_merged_value("status_code") or "").strip().upper()
        warehouse_type = str(_merged_value("warehouse_type") or "").strip().upper()
        current_warehouse_id = _merged_text("warehouse_id")
        parent_warehouse_id = _merged_text("parent_warehouse_id")
        reason_desc = _merged_text("reason_desc")
        if status == "I" and not reason_desc:
            errors["reason_desc"] = "Reason is required when inactivating a warehouse."
        if status == "A" and reason_desc:
            errors["reason_desc"] = "Reason must be empty for active warehouses."
        if warehouse_type == "SUB-HUB" and not parent_warehouse_id:
            errors["parent_warehouse_id"] = "Parent Warehouse is required for SUB-HUB warehouses."
        if warehouse_type == "MAIN-HUB" and parent_warehouse_id:
            errors["parent_warehouse_id"] = "MAIN-HUB warehouses cannot have a Parent Warehouse."
        if current_warehouse_id and parent_warehouse_id == current_warehouse_id:
            errors["parent_warehouse_id"] = "A warehouse cannot be its own parent."

    # Items: FEFO/perishable validation is bidirectional.
    if cfg.key == "items":
        issuance_order = str(_merged_value("issuance_order") or "").upper().strip()
        can_expire = _merged_value("can_expire_flag")
        if issuance_order == "FEFO" and can_expire is not True:
            errors["can_expire_flag"] = (
                "Can Expire must be enabled when Issuance Order is FEFO."
            )
        if can_expire is True and issuance_order and issuance_order != "FEFO":
            errors["issuance_order"] = (
                "Issuance Order must be FEFO when Can Expire is enabled."
            )

    return errors
