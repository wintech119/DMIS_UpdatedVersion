#!/usr/bin/env python3
"""
MLSS Warehouse Operations Import Script
Imports data from MLSS_Warehouse_Operations Excel file into hadr_aid_movement_staging table.

This file tracks operations at Up Park Camp (UPC) warehouse for MLSS relief operations.

Usage:
    python import_mlss_warehouse_staging.py <excel_file> [--db-url <connection_string>] [--dry-run]

Enhancements:
    1. Donor Extraction: Extracts donor information from "Items Donated" sheet's Entity column
       and stores it in comments_text as "Donor: <name>". For sheets without donor info,
       defaults to "Donor: GOJ" (Government of Jamaica).
    2. UOM Normalization: Normalizes non-standard unit of measure values from Excel
       (e.g., "6*27" -> "pack", "Brunswick" -> "tin") before saving to database.
"""

import argparse
import os
import re
import sys
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from typing import Optional

import pandas as pd

# Default warehouse code for MLSS Up Park Camp operations
DEFAULT_WAREHOUSE = 'UPC'  # Up Park Camp

# Default donor for records without explicit donor information (Government of Jamaica)
DEFAULT_DONOR = 'GOJ'


# =============================================================================
# UOM NORMALIZATION
# =============================================================================
# Maps non-standard or unusual UOM values from Excel to normalized values.
# If a raw UOM matches a key (case-insensitive), it returns the mapped value.
# Otherwise, returns the original UOM or 'ea' if missing/empty.
# =============================================================================

UOM_NORMALIZATION_MAP = {
    '6*27': 'pack',
    '12x2': 'pack',
    'brunswick': 'tin',
    '18x30': 'bag',
    '18x30 & 20x30': 'bag',
    '60ftx40ft': 'sheet',
    'tote': 'tote',
}


def normalize_uom(raw_unit: Optional[str]) -> str:
    """
    Normalize unit of measure (UOM) values.
    
    Maps non-standard UOM values from Excel to standardized values.
    Examples:
        - "6*27" -> "pack"
        - "Brunswick" -> "tin"
        - "18x30" -> "bag"
    
    Args:
        raw_unit: The raw unit string from Excel (may be None or empty)
    
    Returns:
        Normalized UOM string, defaults to 'ea' if input is None/empty
    """
    if not raw_unit or pd.isna(raw_unit):
        return 'ea'
    
    raw_unit_str = str(raw_unit).strip()
    if not raw_unit_str:
        return 'ea'
    
    # Check normalization map (case-insensitive)
    raw_lower = raw_unit_str.lower()
    if raw_lower in UOM_NORMALIZATION_MAP:
        return UOM_NORMALIZATION_MAP[raw_lower]
    
    # Return original (lowercase) if no mapping found, truncated to 25 chars
    return raw_unit_str.lower()[:25]


def safe_decimal(value, default=None) -> Optional[Decimal]:
    """Convert value to Decimal safely."""
    if pd.isna(value):
        return default
    try:
        val = Decimal(str(value))
        return val if val != 0 else default
    except (InvalidOperation, ValueError):
        return default


def safe_date(value) -> Optional[date]:
    """Convert value to date safely."""
    if pd.isna(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return pd.to_datetime(value).date()
    except Exception:
        return None


def categorize_item(item_desc: str) -> str:
    """Determine category code based on item description."""
    item_lower = item_desc.lower()
    
    # Food & Water items
    food_keywords = [
        'sugar', 'cornmeal', 'crackers', 'vegetables', 'lasco', 'peas', 'rice',
        'beans', 'mackerel', 'sardine', 'corn beef', 'sausage', 'flour', 'oil',
        'oats', 'cup soup', 'food package', 'snack', 'water', 'chicken', 'tea',
        'syrup', 'coconut', 'pepsi', 'schweppes', 'drink', 'meal', 'cereal',
        'vienna', 'baked bean', 'cooking'
    ]
    
    # Hygiene items
    hygiene_keywords = [
        'soap', 'hygiene', 'tissue', 'bleach', 'disinfectant', 'sanitizer',
        'toothbrush', 'shaving', 'diaper', 'towel', 'sanitation'
    ]
    
    # Shelter/NFI items
    shelter_keywords = [
        'mattress', 'tarpaulin', 'tarparlin', 'tent', 'cot', 'blanket',
        'dinnerware', 'bucket', 'mosquito', 'stove', 'gas', 'bungee'
    ]
    
    # Logistics items
    logistics_keywords = [
        'generator', 'lantern', 'flashlight', 'rope', 'tool', 'packing',
        'packaging', 'bag'
    ]
    
    for kw in food_keywords:
        if kw in item_lower:
            return 'FOOD_WATER'
    
    for kw in hygiene_keywords:
        if kw in item_lower:
            return 'HYGIENE'
    
    for kw in shelter_keywords:
        if kw in item_lower:
            return 'SHELTER'
    
    for kw in logistics_keywords:
        if kw in item_lower:
            return 'LOGS_ENGR'
    
    # Default to FOOD_WATER for this dataset (primarily food distribution)
    return 'FOOD_WATER'


def extract_unit_from_item(item_desc: str) -> tuple[str, str]:
    """
    Extract unit label from item description if present.
    
    Handles patterns like "Sugar (case)", "Rice (bag)", "Tarpaulin (18x30)", etc.
    The extracted unit is then normalized via normalize_uom().
    
    Returns:
        Tuple of (clean_item_description, normalized_unit)
    """
    # Match parenthetical content at end of item description
    # This pattern captures content in parentheses that may include special chars
    match = re.search(r'\(([^)]+)\)\s*$', item_desc)
    if match:
        raw_unit = match.group(1).strip()
        clean_item = re.sub(r'\s*\([^)]+\)\s*$', '', item_desc).strip()
        # Apply UOM normalization to extracted unit
        normalized_unit = normalize_uom(raw_unit)
        return clean_item, normalized_unit
    return item_desc, 'ea'


# =============================================================================
# DONOR EXTRACTION HELPER
# =============================================================================
# Builds comments_text with donor information.
# For "Items Donated" sheet: extracts donor from Entity column.
# For other sheets: uses default donor (GOJ).
# =============================================================================

def build_comments_with_donor(comments_parts: list, donor: Optional[str] = None) -> str:
    """
    Build comments_text string including donor information.
    
    Args:
        comments_parts: List of existing comment strings (e.g., "Location: X", "Collected by: Y")
        donor: Donor name from Entity column, or None to use default
    
    Returns:
        Semicolon-separated comments string with donor information included
    """
    # Use provided donor or default to GOJ
    donor_name = donor.strip() if donor and str(donor).strip() else DEFAULT_DONOR
    
    # Add donor to comments
    all_parts = list(comments_parts)  # Copy to avoid mutation
    all_parts.append(f"Donor: {donor_name}")
    
    return '; '.join(all_parts)


def parse_package_distributions(df: pd.DataFrame, sheet_name: str) -> list[dict]:
    """Parse Package distributions sheet - issued items."""
    records = []
    current_date = None
    
    for row_idx in range(len(df)):
        row = df.iloc[row_idx]
        
        # Check for date in column 1
        date_val = safe_date(row.iloc[1])
        if date_val:
            current_date = date_val
            continue
        
        # Skip header rows and total rows
        if pd.isna(row.iloc[0]) or str(row.iloc[0]).strip().lower() in ['ser', 'nan', '']:
            continue
        if str(row.iloc[1]).strip().lower() == 'total':
            continue
        
        # Try to get serial number - indicates a data row
        try:
            ser = int(float(row.iloc[0]))
        except (ValueError, TypeError):
            continue
        
        amount = safe_decimal(row.iloc[2])
        if not amount or not current_date:
            continue
        
        location = str(row.iloc[3]).strip() if pd.notna(row.iloc[3]) else None
        collected_by = str(row.iloc[4]).strip() if pd.notna(row.iloc[4]) else None
        remarks = str(row.iloc[5]).strip() if len(row) > 5 and pd.notna(row.iloc[5]) else None
        
        # Build comments (donor defaults to GOJ for non-donation sheets)
        comments_parts = []
        if location:
            comments_parts.append(f"Location: {location}")
        if collected_by:
            comments_parts.append(f"Collected by: {collected_by}")
        if remarks:
            comments_parts.append(f"Remarks: {remarks}")
        
        # Add default donor (GOJ) for distribution records
        comments_text = build_comments_with_donor(comments_parts, None)
        
        records.append({
            'category_code': 'FOOD_WATER',
            'item_desc': 'Food Package',
            'unit_label': normalize_uom('ea'),
            'warehouse_code': DEFAULT_WAREHOUSE,
            'movement_date': current_date,
            'movement_type': 'I',  # Issued/distributed
            'qty': amount,
            'unit_cost_usd': None,
            'total_cost_usd': None,
            'source_sheet': sheet_name.strip(),
            'source_row_nbr': row_idx + 1,
            'source_col_idx': 2,
            'comments_text': comments_text,
        })
    
    return records


def parse_bulk_items_distributed(df: pd.DataFrame, sheet_name: str) -> list[dict]:
    """Parse Bulk Items distributed sheet - issued items."""
    records = []
    current_date = None
    current_location = None
    
    for row_idx in range(len(df)):
        row = df.iloc[row_idx]
        
        # Check for date in column 0
        date_val = safe_date(row.iloc[0])
        if date_val:
            current_date = date_val
            current_location = None
            continue
        
        # Skip header rows
        if pd.isna(row.iloc[0]) or str(row.iloc[0]).strip().lower() in ['ser', 'nan', '']:
            if pd.notna(row.iloc[1]) and str(row.iloc[1]).strip().lower() == 'items':
                continue
            # Check if this row has location info
            if pd.notna(row.iloc[4]):
                current_location = str(row.iloc[4]).strip()
        
        # Try to get serial number
        try:
            ser = int(float(row.iloc[0]))
        except (ValueError, TypeError):
            # Check for continuation rows (no serial but has amount)
            if pd.notna(row.iloc[2]) and safe_decimal(row.iloc[2]):
                pass
            else:
                continue
        
        item = row.iloc[1]
        if pd.isna(item) or not str(item).strip():
            continue
        
        item_desc = str(item).strip()
        amount = safe_decimal(row.iloc[2])
        
        if not amount or not current_date:
            continue
        
        raw_unit = str(row.iloc[3]).strip() if pd.notna(row.iloc[3]) else None
        location = str(row.iloc[4]).strip() if pd.notna(row.iloc[4]) else current_location
        collected_by = str(row.iloc[5]).strip() if len(row) > 5 and pd.notna(row.iloc[5]) else None
        remarks = str(row.iloc[6]).strip() if len(row) > 6 and pd.notna(row.iloc[6]) else None
        
        # Update current location if provided
        if location:
            current_location = location
        
        item_clean, extracted_unit = extract_unit_from_item(item_desc)
        # Use raw_unit from column if provided, otherwise use extracted unit
        if raw_unit:
            unit = normalize_uom(raw_unit)
        else:
            unit = extracted_unit
        
        comments_parts = []
        if current_location:
            comments_parts.append(f"Location: {current_location}")
        if collected_by:
            comments_parts.append(f"Collected by: {collected_by}")
        if remarks:
            comments_parts.append(f"Remarks: {remarks}")
        
        # Add default donor (GOJ) for distribution records
        comments_text = build_comments_with_donor(comments_parts, None)
        
        records.append({
            'category_code': categorize_item(item_desc),
            'item_desc': item_clean,
            'unit_label': unit,
            'warehouse_code': DEFAULT_WAREHOUSE,
            'movement_date': current_date,
            'movement_type': 'I',
            'qty': amount,
            'unit_cost_usd': None,
            'total_cost_usd': None,
            'source_sheet': sheet_name.strip(),
            'source_row_nbr': row_idx + 1,
            'source_col_idx': 2,
            'comments_text': comments_text,
        })
    
    return records


def parse_snack_packages(df: pd.DataFrame, sheet_name: str) -> list[dict]:
    """Parse Snack Packages Distributions sheet."""
    records = []
    current_date = None
    
    for row_idx in range(3, len(df)):  # Skip header rows
        row = df.iloc[row_idx]
        
        # Check for date in column 1
        date_val = safe_date(row.iloc[1])
        if date_val:
            current_date = date_val
        
        amount = safe_decimal(row.iloc[2])
        if not amount or not current_date:
            continue
        
        location = str(row.iloc[3]).strip() if pd.notna(row.iloc[3]) else None
        collected_by = str(row.iloc[4]).strip() if pd.notna(row.iloc[4]) else None
        remarks = str(row.iloc[5]).strip() if len(row) > 5 and pd.notna(row.iloc[5]) else None
        
        comments_parts = []
        if location:
            comments_parts.append(f"Location: {location}")
        if collected_by:
            comments_parts.append(f"Collected by: {collected_by}")
        if remarks:
            comments_parts.append(f"Remarks: {remarks}")
        
        # Add default donor (GOJ) for distribution records
        comments_text = build_comments_with_donor(comments_parts, None)
        
        records.append({
            'category_code': 'FOOD_WATER',
            'item_desc': 'Snack Package',
            'unit_label': normalize_uom('ea'),
            'warehouse_code': DEFAULT_WAREHOUSE,
            'movement_date': current_date,
            'movement_type': 'I',
            'qty': amount,
            'unit_cost_usd': None,
            'total_cost_usd': None,
            'source_sheet': sheet_name.strip(),
            'source_row_nbr': row_idx + 1,
            'source_col_idx': 2,
            'comments_text': comments_text,
        })
    
    return records


def parse_packages_produced(df: pd.DataFrame, sheet_name: str) -> list[dict]:
    """Parse Packages produced per day sheet - internal production (Received into inventory)."""
    records = []
    
    for row_idx in range(3, len(df)):  # Skip header rows
        row = df.iloc[row_idx]
        
        date_val = safe_date(row.iloc[1])
        if not date_val:
            continue
        
        completed = safe_decimal(row.iloc[2])
        partial = safe_decimal(row.iloc[3])
        remarks = str(row.iloc[4]).strip() if pd.notna(row.iloc[4]) else None
        
        # Record completed packages as received
        # Production records use GOJ as donor (government operation)
        if completed and completed > 0:
            base_comment = "Completed packages"
            if remarks:
                base_comment = f"{base_comment}; {remarks}"
            comments_text = build_comments_with_donor([base_comment], None)
            
            records.append({
                'category_code': 'FOOD_WATER',
                'item_desc': 'Food Package (Produced)',
                'unit_label': normalize_uom('ea'),
                'warehouse_code': DEFAULT_WAREHOUSE,
                'movement_date': date_val,
                'movement_type': 'R',  # Received (produced)
                'qty': completed,
                'unit_cost_usd': None,
                'total_cost_usd': None,
                'source_sheet': sheet_name.strip(),
                'source_row_nbr': row_idx + 1,
                'source_col_idx': 2,
                'comments_text': comments_text,
            })
        
        # Record partial packages separately if present
        if partial and partial > 0:
            base_comment = "Partial packages"
            if remarks:
                base_comment = f"{base_comment}; {remarks}"
            comments_text = build_comments_with_donor([base_comment], None)
            
            records.append({
                'category_code': 'FOOD_WATER',
                'item_desc': 'Food Package (Partial)',
                'unit_label': normalize_uom('ea'),
                'warehouse_code': DEFAULT_WAREHOUSE,
                'movement_date': date_val,
                'movement_type': 'R',
                'qty': partial,
                'unit_cost_usd': None,
                'total_cost_usd': None,
                'source_sheet': sheet_name.strip(),
                'source_row_nbr': row_idx + 1,
                'source_col_idx': 3,
                'comments_text': comments_text,
            })
    
    return records


def parse_items_donated(df: pd.DataFrame, sheet_name: str) -> list[dict]:
    """
    Parse Items Donated sheet - received items with donor extraction.
    
    DONOR EXTRACTION LOGIC:
    -----------------------
    This function handles both older and newer Excel file formats:
    
    A) Newer files: Have an "Entity" column (column index 3) containing donor names
       such as "Food for the Poor", "JMMB and Sagicor (JMEA)", "ODPEM", etc.
       The donor name is extracted and added to comments_text as "Donor: <name>".
    
    B) Older files: Do NOT have a donor/Entity column, or the column is empty.
       In this case, the donor defaults to "GOJ" (Government of Jamaica).
    
    The donor information is stored in comments_text field (not a separate column)
    to avoid schema changes.
    """
    records = []
    current_date = None
    current_entity = None  # Track entity for rows that inherit from previous row
    
    for row_idx in range(2, len(df)):  # Skip header rows
        row = df.iloc[row_idx]
        
        # Check for date
        date_val = safe_date(row.iloc[1])
        if date_val:
            current_date = date_val
            current_entity = None  # Reset entity when date changes
        
        # Special handling for "3 Novemeber" text date
        if pd.notna(row.iloc[1]) and 'novem' in str(row.iloc[1]).lower():
            current_date = date(2025, 11, 3)
        
        if not current_date:
            continue
        
        item = row.iloc[2]
        if pd.isna(item) or not str(item).strip():
            continue
        
        item_desc = str(item).strip()
        
        # =================================================================
        # DONOR EXTRACTION from Entity column (column index 3)
        # =================================================================
        # Check if Entity column has a value for this row.
        # If present, use it as the donor and remember it for subsequent rows.
        # If absent, use the last known entity or default to GOJ.
        # =================================================================
        entity_value = row.iloc[3] if len(row) > 3 else None
        if pd.notna(entity_value) and str(entity_value).strip():
            current_entity = str(entity_value).strip()
        
        # Donor is either the current entity or defaults to GOJ
        donor = current_entity if current_entity else DEFAULT_DONOR
        
        qty = safe_decimal(row.iloc[4])
        
        if not qty:
            continue
        
        item_clean, unit = extract_unit_from_item(item_desc)
        
        # Build comments with donor information
        # For donated items, the primary comment is the donor
        comments_text = f"Donor: {donor}"
        
        records.append({
            'category_code': categorize_item(item_desc),
            'item_desc': item_clean,
            'unit_label': unit,
            'warehouse_code': DEFAULT_WAREHOUSE,
            'movement_date': current_date,
            'movement_type': 'R',  # Received
            'qty': qty,
            'unit_cost_usd': None,
            'total_cost_usd': None,
            'source_sheet': sheet_name.strip(),
            'source_row_nbr': row_idx + 1,
            'source_col_idx': 4,
            'comments_text': comments_text,
        })
    
    return records


def parse_goods_received_procurement(df: pd.DataFrame, sheet_name: str) -> list[dict]:
    """Parse Goods Received from procurement sheet - received items by date columns."""
    records = []
    
    # Get dates from row 1 (index 1)
    date_cols = {}
    for col_idx in range(2, len(df.columns) - 1):  # Skip Ser, Item, and Total columns
        date_val = safe_date(df.iloc[1, col_idx])
        if date_val:
            date_cols[col_idx] = date_val
    
    # Process item rows (starting from row 2)
    for row_idx in range(2, len(df)):
        row = df.iloc[row_idx]
        
        item = row.iloc[1]
        if pd.isna(item) or not str(item).strip():
            continue
        
        item_desc = str(item).strip()
        item_clean, unit = extract_unit_from_item(item_desc)
        
        # Process each date column
        for col_idx, movement_date in date_cols.items():
            qty = safe_decimal(row.iloc[col_idx])
            if not qty:
                continue
            
            # Procurement items are from GOJ (government purchases)
            comments_text = build_comments_with_donor(["Procurement"], None)
            
            records.append({
                'category_code': categorize_item(item_desc),
                'item_desc': item_clean,
                'unit_label': unit,
                'warehouse_code': DEFAULT_WAREHOUSE,
                'movement_date': movement_date,
                'movement_type': 'R',  # Received
                'qty': qty,
                'unit_cost_usd': None,
                'total_cost_usd': None,
                'source_sheet': sheet_name.strip(),
                'source_row_nbr': row_idx + 1,
                'source_col_idx': col_idx,
                'comments_text': comments_text,
            })
    
    return records


def parse_staff_items(df: pd.DataFrame, sheet_name: str) -> list[dict]:
    """Parse Items taken for Staff sheet - issued items."""
    records = []
    
    # Get dates from row 0
    date_cols = {}
    for col_idx in range(1, len(df.columns)):
        date_val = safe_date(df.iloc[0, col_idx])
        if date_val:
            date_cols[col_idx] = date_val
    
    # Process item rows (starting from row 2)
    for row_idx in range(2, len(df)):
        row = df.iloc[row_idx]
        
        item = row.iloc[0]
        if pd.isna(item) or not str(item).strip():
            continue
        
        item_desc = str(item).strip()
        
        for col_idx, movement_date in date_cols.items():
            qty = safe_decimal(row.iloc[col_idx])
            if not qty:
                continue
            
            # Staff consumption uses GOJ as donor (internal use)
            comments_text = build_comments_with_donor(["Staff consumption"], None)
            
            records.append({
                'category_code': categorize_item(item_desc),
                'item_desc': item_desc,
                'unit_label': normalize_uom('ea'),
                'warehouse_code': DEFAULT_WAREHOUSE,
                'movement_date': movement_date,
                'movement_type': 'I',  # Issued to staff
                'qty': qty,
                'unit_cost_usd': None,
                'total_cost_usd': None,
                'source_sheet': sheet_name.strip(),
                'source_row_nbr': row_idx + 1,
                'source_col_idx': col_idx,
                'comments_text': comments_text,
            })
    
    return records


def parse_excel_data(excel_path: str) -> list[dict]:
    """Parse the Excel file and extract all movement records."""
    xlsx = pd.ExcelFile(excel_path)
    records = []
    
    sheet_parsers = {
        'Package distributions ': parse_package_distributions,
        'Bulk Items distributed': parse_bulk_items_distributed,
        'Snack Packages Distributions': parse_snack_packages,
        'Packages produced per day': parse_packages_produced,
        'Items Donated': parse_items_donated,
        'Goods Received from procurement': parse_goods_received_procurement,
        'Items taken for Staff': parse_staff_items,
    }
    
    for sheet_name, parser in sheet_parsers.items():
        if sheet_name not in xlsx.sheet_names:
            print(f"Warning: Sheet '{sheet_name}' not found", file=sys.stderr)
            continue
        
        df = pd.read_excel(xlsx, sheet_name=sheet_name, header=None)
        sheet_records = parser(df, sheet_name)
        records.extend(sheet_records)
        print(f"  {sheet_name}: {len(sheet_records)} records")
    
    return records


def insert_records(records: list[dict], db_url: str, create_by_id: str = 'MLSS_IMPORT'):
    """Insert records into the staging table using psycopg2."""
    try:
        import psycopg2
        from psycopg2.extras import execute_values
    except ImportError:
        print("Error: psycopg2 not installed. Install with: pip install psycopg2-binary", file=sys.stderr)
        sys.exit(1)
    
    conn = psycopg2.connect(db_url)
    cur = conn.cursor()
    
    insert_sql = """
        INSERT INTO public.hadr_aid_movement_staging (
            category_code, item_desc, unit_label, warehouse_code,
            movement_date, movement_type, qty, unit_cost_usd, total_cost_usd,
            source_sheet, source_row_nbr, source_col_idx, comments_text,
            create_by_id
        ) VALUES %s
    """
    
    values = [
        (
            r['category_code'],
            r['item_desc'],
            r['unit_label'],
            r['warehouse_code'],
            r['movement_date'],
            r['movement_type'],
            float(r['qty']),
            float(r['unit_cost_usd']) if r['unit_cost_usd'] else None,
            float(r['total_cost_usd']) if r['total_cost_usd'] else None,
            r['source_sheet'],
            r['source_row_nbr'],
            r['source_col_idx'],
            r['comments_text'],
            create_by_id,
        )
        for r in records
    ]
    
    try:
        execute_values(cur, insert_sql, values, page_size=1000)
        conn.commit()
        print(f"Successfully inserted {len(records)} records")
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cur.close()
        conn.close()


def generate_sql_inserts(records: list[dict], output_path: str, create_by_id: str = 'MLSS_IMPORT'):
    """Generate SQL INSERT statements to a file."""
    with open(output_path, 'w') as f:
        f.write("-- MLSS Warehouse Operations Staging Data Import\n")
        f.write(f"-- Generated: {datetime.now().isoformat()}\n")
        f.write(f"-- Source: MLSS Up Park Camp Warehouse Operations\n\n")
        
        f.write("INSERT INTO public.hadr_aid_movement_staging (\n")
        f.write("    category_code, item_desc, unit_label, warehouse_code,\n")
        f.write("    movement_date, movement_type, qty, unit_cost_usd, total_cost_usd,\n")
        f.write("    source_sheet, source_row_nbr, source_col_idx, comments_text,\n")
        f.write("    create_by_id\n")
        f.write(") VALUES\n")
        
        for i, r in enumerate(records):
            unit_cost = f"{float(r['unit_cost_usd']):.2f}" if r['unit_cost_usd'] else "NULL"
            total_cost = f"{float(r['total_cost_usd']):.2f}" if r['total_cost_usd'] else "NULL"
            
            # Escape single quotes
            item_desc = r['item_desc'].replace("'", "''")
            source_sheet = r['source_sheet'].replace("'", "''")
            comments = f"'{r['comments_text'].replace(chr(39), chr(39)+chr(39))}'" if r['comments_text'] else "NULL"
            
            line = (
                f"('{r['category_code']}', '{item_desc}', "
                f"'{r['unit_label']}', '{r['warehouse_code']}', "
                f"'{r['movement_date']}', '{r['movement_type']}', "
                f"{float(r['qty']):.2f}, {unit_cost}, {total_cost}, "
                f"'{source_sheet}', {r['source_row_nbr']}, {r['source_col_idx']}, "
                f"{comments}, '{create_by_id}')"
            )
            
            if i < len(records) - 1:
                f.write(f"    {line},\n")
            else:
                f.write(f"    {line};\n")
    
    print(f"Generated SQL file: {output_path}")


def main():
    parser = argparse.ArgumentParser(description='Import MLSS Warehouse Operations data into staging table')
    parser.add_argument('excel_file', help='Path to the Excel file')
    parser.add_argument('--db-url', help='PostgreSQL connection URL')
    parser.add_argument('--sql-output', help='Generate SQL INSERT file instead of direct insert')
    parser.add_argument('--dry-run', action='store_true', help='Parse and show summary without inserting')
    parser.add_argument('--create-by', default='MLSS_IMPORT', help='Value for create_by_id field')
    
    args = parser.parse_args()
    
    if not os.path.exists(args.excel_file):
        print(f"Error: File not found: {args.excel_file}", file=sys.stderr)
        sys.exit(1)
    
    print(f"Parsing Excel file: {args.excel_file}")
    print(f"Warehouse code: {DEFAULT_WAREHOUSE} (Up Park Camp)")
    print(f"Default donor: {DEFAULT_DONOR} (Government of Jamaica)\n")
    
    records = parse_excel_data(args.excel_file)
    
    # Summary
    print(f"\nTotal: {len(records)} movement records")
    
    categories = {}
    movement_types = {'R': 0, 'I': 0}
    donors = {}
    
    for r in records:
        categories[r['category_code']] = categories.get(r['category_code'], 0) + 1
        movement_types[r['movement_type']] += 1
        # Extract donor from comments for summary
        if r['comments_text'] and 'Donor:' in r['comments_text']:
            donor_match = re.search(r'Donor:\s*([^;]+)', r['comments_text'])
            if donor_match:
                donor_name = donor_match.group(1).strip()
                donors[donor_name] = donors.get(donor_name, 0) + 1
    
    print("\nBy Category:")
    for cat, count in sorted(categories.items()):
        print(f"  {cat}: {count}")
    
    print("\nBy Movement Type:")
    print(f"  Received (R): {movement_types['R']}")
    print(f"  Issued (I): {movement_types['I']}")
    
    print("\nBy Donor:")
    for donor, count in sorted(donors.items(), key=lambda x: -x[1]):
        print(f"  {donor}: {count}")
    
    if args.dry_run:
        print("\n[Dry run - no data inserted]")
        print("\nSample records (first 10):")
        for r in records[:10]:
            print(f"  {r['movement_date']} | {r['movement_type']} | {r['category_code']} | "
                  f"{r['item_desc'][:25]}... | {r['qty']} | {r['unit_label']} | {r['source_sheet'][:15]}")
        return
    
    if args.sql_output:
        generate_sql_inserts(records, args.sql_output, args.create_by)
    elif args.db_url:
        print(f"\nInserting into database...")
        insert_records(records, args.db_url, args.create_by)
    else:
        print("\nNo output specified. Use --db-url to insert directly or --sql-output to generate SQL file.")
        print("Use --dry-run to see what would be imported.")


if __name__ == '__main__':
    main()
