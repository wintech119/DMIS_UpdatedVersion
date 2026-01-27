#!/usr/bin/env python3
"""
HADR Relief Aid Import Script
Imports data from HADR_Relief_Aid_Tracking_Document.xlsx into hadr_aid_movement_staging table.

Usage:
    python import_hadr_aid_staging.py <excel_file> [--db-url <connection_string>] [--dry-run]
"""

import argparse
import os
import re
import sys
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

import pandas as pd

# Sheet name to category code mapping
SHEET_CATEGORY_MAP = {
    'Food & Water ': 'FOOD_WATER',
    'Medical Supplies ': 'MEDICAL',
    'Shelter&NFI': 'SHELTER',
    'Hygiene and Sanitation': 'HYGIENE',
    'Logistics & Engineering Equipme': 'LOGS_ENGR',
}

# Known warehouse code normalization
WAREHOUSE_CODE_MAP = {
    'KW': 'KW',
    'MG': 'MG',
    'MOBAY': 'MOBAY',
    'Mobay': 'MOBAY',
    'mobay': 'MOBAY',
    'KG': 'KW',  # Typo in data - KG should be KW (Kingston)
}


def normalize_warehouse_code(location: str) -> list[str]:
    """
    Extract and normalize warehouse codes from location field.
    Handles complex cases like 'MG, KW', 'Mobay - 4', 'MG, 199-Mobay', etc.
    Returns a list of normalized warehouse codes.
    """
    if pd.isna(location) or not str(location).strip():
        return []
    
    location = str(location).strip()
    codes = []
    
    # First try direct mapping for simple single codes
    loc_upper = location.upper()
    if loc_upper in ['KW', 'MG', 'MOBAY', 'KG']:
        return ['KW'] if loc_upper == 'KG' else [loc_upper if loc_upper != 'MOBAY' else 'MOBAY']
    
    # Handle patterns like 'Mobay-48', 'Mobay - 4', etc. (single MOBAY location)
    if re.match(r'^Mobay\s*[-]?\s*\d*$', location, re.IGNORECASE):
        return ['MOBAY']
    
    # Handle complex multi-warehouse patterns
    # Split by comma, 'and', or spaces around hyphens that separate warehouses
    # e.g., 'MG, KW', 'KW and MG', '21-MG, 36-KG', 'Mobay-49 and 1593 MG'
    
    # Normalize the string for easier parsing
    loc_normalized = location.upper()
    
    # Check for each warehouse code
    if 'MOBAY' in loc_normalized or 'MB-' in loc_normalized or re.search(r'MB\d', loc_normalized):
        codes.append('MOBAY')
    
    # Check for MG (but not as part of MOBAY)
    # Use word boundary or number prefix patterns
    if re.search(r'\bMG\b', loc_normalized) or re.search(r'\d+\s*-?\s*MG', loc_normalized):
        codes.append('MG')
    
    # Check for KW
    if re.search(r'\bKW\b', loc_normalized) or re.search(r'\d+\s*-?\s*KW', loc_normalized):
        codes.append('KW')
    
    # Check for KG (typo for KW)
    if re.search(r'\bKG\b', loc_normalized) or re.search(r'\d+\s*-?\s*KG', loc_normalized):
        codes.append('KW')  # Map KG to KW
    
    return list(set(codes)) if codes else []


def safe_decimal(value, default=None) -> Optional[Decimal]:
    """Convert value to Decimal safely."""
    if pd.isna(value):
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return default


def parse_excel_data(excel_path: str, date_from: Optional[datetime] = None, date_to: Optional[datetime] = None) -> list[dict]:
    """
    Parse the Excel file and extract all movement records.
    Returns list of dictionaries ready for database insertion.
    """
    xlsx = pd.ExcelFile(excel_path)
    records = []
    
    for sheet_name, category_code in SHEET_CATEGORY_MAP.items():
        if sheet_name not in xlsx.sheet_names:
            print(f"Warning: Sheet '{sheet_name}' not found in workbook", file=sys.stderr)
            continue
        
        df = pd.read_excel(xlsx, sheet_name=sheet_name, header=None)
        
        # Get date columns from row 0 (dates start at column 6)
        # Dynamically find all date columns instead of hardcoding range
        dates = []
        for col_idx in range(6, len(df.columns) - 2, 2):  # Dynamic range based on actual columns
            date_val = df.iloc[0, col_idx]
            if pd.notna(date_val):
                if isinstance(date_val, datetime):
                    parsed_date = date_val.date()
                else:
                    try:
                        parsed_date = pd.to_datetime(date_val).date()
                    except Exception:
                        # Skip non-date columns (e.g., "Quantity in Store")
                        continue
                
                # Apply date filters if specified
                if date_from and parsed_date < date_from.date():
                    continue
                if date_to and parsed_date > date_to.date():
                    continue
                    
                dates.append((col_idx, parsed_date))
        
        # Find unit cost column - look for it after the date columns
        # It's typically labeled or in a fixed position near the end
        unit_cost_col = None
        for col_idx in range(len(df.columns) - 1, 50, -1):
            # Look for a column with numeric values that could be unit costs
            if col_idx < len(df.columns):
                header_val = df.iloc[1, col_idx] if len(df) > 1 else None
                if pd.notna(header_val) and 'cost' in str(header_val).lower():
                    unit_cost_col = col_idx
                    break
        if unit_cost_col is None:
            unit_cost_col = len(df.columns) - 2  # Fallback: second to last column
        
        # Process data rows (starting from row 2, skipping headers in rows 0-1)
        for row_idx in range(2, len(df)):
            item_desc = df.iloc[row_idx, 0]
            if pd.isna(item_desc) or not str(item_desc).strip():
                continue
            
            item_desc = str(item_desc).strip()
            unit_label = str(df.iloc[row_idx, 1]).strip() if pd.notna(df.iloc[row_idx, 1]) else None
            location = df.iloc[row_idx, 5]
            unit_cost = safe_decimal(df.iloc[row_idx, unit_cost_col])
            
            # Get warehouse codes
            warehouse_codes = normalize_warehouse_code(location)
            if not warehouse_codes:
                warehouse_codes = ['UNKNOWN']
            
            # Process each date column pair
            for date_col_idx, movement_date in dates:
                received_col = date_col_idx
                issued_col = date_col_idx + 1
                
                received_qty = safe_decimal(df.iloc[row_idx, received_col], Decimal('0'))
                issued_qty = safe_decimal(df.iloc[row_idx, issued_col], Decimal('0'))
                
                # Create record for received quantity (if > 0)
                if received_qty and received_qty > 0:
                    for wh_code in warehouse_codes:
                        total_cost = (received_qty * unit_cost) if unit_cost else None
                        records.append({
                            'category_code': category_code,
                            'item_desc': item_desc,
                            'unit_label': unit_label,
                            'warehouse_code': wh_code,
                            'movement_date': movement_date,
                            'movement_type': 'R',
                            'qty': received_qty,
                            'unit_cost_usd': unit_cost,
                            'total_cost_usd': total_cost,
                            'source_sheet': sheet_name.strip(),
                            'source_row_nbr': row_idx + 1,  # 1-based for Excel
                            'source_col_idx': received_col,
                            'comments_text': f"Location: {location}" if pd.notna(location) else None,
                        })
                
                # Create record for issued quantity (if > 0)
                if issued_qty and issued_qty > 0:
                    for wh_code in warehouse_codes:
                        total_cost = (issued_qty * unit_cost) if unit_cost else None
                        records.append({
                            'category_code': category_code,
                            'item_desc': item_desc,
                            'unit_label': unit_label,
                            'warehouse_code': wh_code,
                            'movement_date': movement_date,
                            'movement_type': 'I',
                            'qty': issued_qty,
                            'unit_cost_usd': unit_cost,
                            'total_cost_usd': total_cost,
                            'source_sheet': sheet_name.strip(),
                            'source_row_nbr': row_idx + 1,
                            'source_col_idx': issued_col,
                            'comments_text': f"Location: {location}" if pd.notna(location) else None,
                        })
    
    return records


def insert_records(records: list[dict], db_url: str, create_by_id: str = 'IMPORT'):
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


def generate_sql_inserts(records: list[dict], output_path: str, create_by_id: str = 'IMPORT'):
    """Generate SQL INSERT statements to a file."""
    with open(output_path, 'w') as f:
        f.write("-- HADR Aid Movement Staging Data Import\n")
        f.write(f"-- Generated: {datetime.now().isoformat()}\n\n")
        
        f.write("INSERT INTO public.hadr_aid_movement_staging (\n")
        f.write("    category_code, item_desc, unit_label, warehouse_code,\n")
        f.write("    movement_date, movement_type, qty, unit_cost_usd, total_cost_usd,\n")
        f.write("    source_sheet, source_row_nbr, source_col_idx, comments_text,\n")
        f.write("    create_by_id\n")
        f.write(") VALUES\n")
        
        for i, r in enumerate(records):
            unit_cost = f"{float(r['unit_cost_usd']):.2f}" if r['unit_cost_usd'] else "NULL"
            total_cost = f"{float(r['total_cost_usd']):.2f}" if r['total_cost_usd'] else "NULL"
            comments = f"'{r['comments_text']}'" if r['comments_text'] else "NULL"
            
            # Escape single quotes in item_desc
            item_desc = r['item_desc'].replace("'", "''")
            source_sheet = r['source_sheet'].replace("'", "''")
            
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
    parser = argparse.ArgumentParser(description='Import HADR Relief Aid data into staging table')
    parser.add_argument('excel_file', help='Path to the Excel file')
    parser.add_argument('--db-url', help='PostgreSQL connection URL')
    parser.add_argument('--sql-output', help='Generate SQL INSERT file instead of direct insert')
    parser.add_argument('--dry-run', action='store_true', help='Parse and show summary without inserting')
    parser.add_argument('--create-by', default='IMPORT', help='Value for create_by_id field')
    parser.add_argument('--date-from', help='Only import records from this date onwards (YYYY-MM-DD)')
    parser.add_argument('--date-to', help='Only import records up to this date (YYYY-MM-DD)')
    
    args = parser.parse_args()
    
    if not os.path.exists(args.excel_file):
        print(f"Error: File not found: {args.excel_file}", file=sys.stderr)
        sys.exit(1)
    
    # Parse date filters
    date_from = None
    date_to = None
    if args.date_from:
        try:
            date_from = datetime.strptime(args.date_from, '%Y-%m-%d')
            print(f"Filtering: records from {args.date_from} onwards")
        except ValueError:
            print(f"Error: Invalid date format for --date-from: {args.date_from}. Use YYYY-MM-DD", file=sys.stderr)
            sys.exit(1)
    if args.date_to:
        try:
            date_to = datetime.strptime(args.date_to, '%Y-%m-%d')
            print(f"Filtering: records up to {args.date_to}")
        except ValueError:
            print(f"Error: Invalid date format for --date-to: {args.date_to}. Use YYYY-MM-DD", file=sys.stderr)
            sys.exit(1)
    
    print(f"Parsing Excel file: {args.excel_file}")
    records = parse_excel_data(args.excel_file, date_from=date_from, date_to=date_to)
    
    # Summary
    print(f"\nParsed {len(records)} movement records:")
    categories = {}
    movement_types = {'R': 0, 'I': 0}
    warehouses = {}
    
    for r in records:
        categories[r['category_code']] = categories.get(r['category_code'], 0) + 1
        movement_types[r['movement_type']] += 1
        warehouses[r['warehouse_code']] = warehouses.get(r['warehouse_code'], 0) + 1
    
    print("\nBy Category:")
    for cat, count in sorted(categories.items()):
        print(f"  {cat}: {count}")
    
    print("\nBy Movement Type:")
    print(f"  Received (R): {movement_types['R']}")
    print(f"  Issued (I): {movement_types['I']}")
    
    print("\nBy Warehouse:")
    for wh, count in sorted(warehouses.items()):
        print(f"  {wh}: {count}")
    
    if args.dry_run:
        print("\n[Dry run - no data inserted]")
        # Show sample records
        print("\nSample records (first 5):")
        for r in records[:5]:
            print(f"  {r['movement_date']} | {r['movement_type']} | {r['category_code']} | "
                  f"{r['item_desc'][:30]}... | {r['qty']} | {r['warehouse_code']}")
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
