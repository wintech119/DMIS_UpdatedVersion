#!/usr/bin/env python3
"""
Migrate HADR Aid Movement Staging Data to Transaction Table

This script migrates records from hadr_aid_movement_staging to the transaction table,
handling FK lookups and preventing duplicates.

Usage:
    python migrate_staging_to_transaction.py --db-url <connection_string> [options]

Options:
    --dry-run           Show what would be migrated without executing
    --date-from         Only migrate staging records from this date onwards
    --date-to           Only migrate staging records up to this date
    --sql-output        Generate SQL file instead of direct execution
    --created-by        Value for created_by field (default: 'HADR_IMPORT')
"""

import argparse
import sys
from datetime import datetime
from typing import Optional


def get_db_connection(db_url: str):
    """Create database connection."""
    try:
        import psycopg2
        return psycopg2.connect(db_url)
    except ImportError:
        print("Error: psycopg2 not installed. Install with: pip install psycopg2-binary", file=sys.stderr)
        sys.exit(1)


def get_lookup_tables_info(conn) -> dict:
    """Fetch information about lookup tables for FK resolution."""
    import re
    cur = conn.cursor()
    
    info = {
        'items': {},
        'warehouses': {},
        'has_item_table': False,
        'has_warehouse_table': False,
        'item_table_structure': None,
        'warehouse_table_structure': None,
    }
    
    # Check for item table (common names: item, items, inventory_item)
    cur.execute("""
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'public' 
        AND table_name IN ('item', 'items', 'inventory_item', 'product', 'products')
    """)
    item_tables = cur.fetchall()
    
    if item_tables:
        item_table = item_tables[0][0]
        info['has_item_table'] = True
        info['item_table_name'] = item_table
        
        # Get column info
        cur.execute(f"""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = '{item_table}' AND table_schema = 'public'
        """)
        info['item_table_structure'] = {row[0]: row[1] for row in cur.fetchall()}
        
        # Try to load items - look for common column patterns
        # DMIS uses item_id and item_name
        cols = info['item_table_structure']
        if 'item_id' in cols and 'item_name' in cols:
            cur.execute(f"SELECT item_id, item_name FROM {item_table}")
            for row in cur.fetchall():
                info['items'][row[1].upper().strip()] = row[0]
        elif 'id' in cols and 'name' in cols:
            cur.execute(f"SELECT id, name FROM {item_table}")
            for row in cur.fetchall():
                info['items'][row[1].upper().strip()] = row[0]
        elif 'id' in cols and 'item_name' in cols:
            cur.execute(f"SELECT id, item_name FROM {item_table}")
            for row in cur.fetchall():
                info['items'][row[1].upper().strip()] = row[0]
    
    # Check for warehouse table (prefer 'warehouse' over 'location')
    cur.execute("""
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'public' 
        AND table_name IN ('warehouse', 'warehouses', 'location', 'locations')
        ORDER BY CASE 
            WHEN table_name = 'warehouse' THEN 1 
            WHEN table_name = 'warehouses' THEN 2 
            ELSE 3 
        END
    """)
    wh_tables = cur.fetchall()
    
    if wh_tables:
        wh_table = wh_tables[0][0]
        info['has_warehouse_table'] = True
        info['warehouse_table_name'] = wh_table
        
        # Get column info
        cur.execute(f"""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = '{wh_table}' AND table_schema = 'public'
        """)
        info['warehouse_table_structure'] = {row[0]: row[1] for row in cur.fetchall()}
        
        # Try to load warehouses
        # DMIS uses warehouse_id and warehouse_name with codes in parentheses
        cols = info['warehouse_table_structure']
        if 'warehouse_id' in cols and 'warehouse_name' in cols:
            cur.execute(f"SELECT warehouse_id, warehouse_name FROM {wh_table}")
            for row in cur.fetchall():
                wh_id, wh_name = row
                match = re.search(r'\(([A-Z]+)\)', wh_name)
                if match:
                    code = match.group(1)
                    info['warehouses'][code] = wh_id
                if 'UNKNOWN' in wh_name.upper():
                    info['warehouses']['UNKNOWN'] = wh_id
        elif 'id' in cols and 'code' in cols:
            cur.execute(f"SELECT id, code FROM {wh_table}")
            for row in cur.fetchall():
                info['warehouses'][row[1]] = row[0]
        elif 'id' in cols and 'name' in cols:
            cur.execute(f"SELECT id, name FROM {wh_table}")
            for row in cur.fetchall():
                info['warehouses'][row[1]] = row[0]
    
    cur.close()
    return info


def get_staging_records(conn, date_from: Optional[datetime] = None, 
                        date_to: Optional[datetime] = None) -> list[dict]:
    """Fetch staging records with optional date filtering."""
    cur = conn.cursor()
    
    query = """
        SELECT 
            staging_id, category_code, item_desc, unit_label, warehouse_code,
            movement_date, movement_type, qty, unit_cost_usd, total_cost_usd,
            source_sheet, source_row_nbr, source_col_idx, comments_text,
            create_by_id, create_dtime
        FROM public.hadr_aid_movement_staging
        WHERE 1=1
    """
    params = []
    
    if date_from:
        query += " AND movement_date >= %s"
        params.append(date_from.date())
    if date_to:
        query += " AND movement_date <= %s"
        params.append(date_to.date())
    
    query += " ORDER BY movement_date, staging_id"
    
    cur.execute(query, params)
    columns = [desc[0] for desc in cur.description]
    records = [dict(zip(columns, row)) for row in cur.fetchall()]
    cur.close()
    
    return records


def get_existing_transactions(conn, created_by_pattern: str = 'HADR%') -> set:
    """
    Get existing transactions to prevent duplicates.
    Returns a set of (item_id, ttype, qty, warehouse_id, notes) tuples.
    
    Uses created_by field to identify previously imported records.
    """
    cur = conn.cursor()
    
    # Build a signature for existing transactions
    # We use a combination of fields that should uniquely identify a transaction
    cur.execute("""
        SELECT 
            COALESCE(item_id, -1),
            ttype,
            qty,
            COALESCE(warehouse_id, -1),
            COALESCE(notes, '')
        FROM public.transaction
        WHERE created_by LIKE %s
    """, (created_by_pattern,))
    
    existing = set()
    for row in cur.fetchall():
        existing.add(row)
    
    cur.close()
    return existing


def build_transaction_signature(item_id: Optional[int], ttype: str, qty: float,
                                warehouse_id: Optional[int], notes: Optional[str]) -> tuple:
    """Build a signature tuple for duplicate detection."""
    return (
        item_id if item_id else -1,
        ttype,
        qty,
        warehouse_id if warehouse_id else -1,
        notes if notes else ''
    )


def migrate_records(conn, records: list[dict], lookup_info: dict,
                    created_by: str = 'HADR_IMPORT', dry_run: bool = False) -> dict:
    """
    Migrate staging records to transaction table.
    Returns statistics about the migration.
    """
    cur = conn.cursor()
    
    stats = {
        'total_staging': len(records),
        'inserted': 0,
        'skipped_duplicate': 0,
        'skipped_no_item': 0,
        'skipped_no_warehouse': 0,
        'errors': [],
    }
    
    # Get existing transactions for duplicate detection
    existing = get_existing_transactions(conn, f'{created_by}%')
    print(f"Found {len(existing)} existing transactions with created_by LIKE '{created_by}%'")
    
    items = lookup_info.get('items', {})
    warehouses = lookup_info.get('warehouses', {})
    
    insert_sql = """
        INSERT INTO public.transaction (
            item_id, ttype, qty, warehouse_id, donor_id, event_id,
            expiry_date, notes, created_by
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    
    to_insert = []
    
    for r in records:
        # Resolve item_id (case-insensitive match)
        item_desc_upper = r['item_desc'].upper().strip() if r['item_desc'] else ''
        item_id = items.get(item_desc_upper)
        if not item_id and lookup_info['has_item_table']:
            stats['skipped_no_item'] += 1
            stats['errors'].append(f"Item not found: {r['item_desc'][:50]}")
            continue
        
        # Resolve warehouse_id
        warehouse_id = warehouses.get(r['warehouse_code'])
        if not warehouse_id and r['warehouse_code'] != 'UNKNOWN' and lookup_info['has_warehouse_table']:
            stats['skipped_no_warehouse'] += 1
            stats['errors'].append(f"Warehouse not found: {r['warehouse_code']}")
            continue
        
        # Build notes with movement date and source info
        notes_parts = []
        if r['movement_date']:
            notes_parts.append(f"Date: {r['movement_date']}")
        if r['comments_text']:
            notes_parts.append(r['comments_text'])
        if r['source_sheet']:
            notes_parts.append(f"Source: {r['source_sheet']} Row {r['source_row_nbr']}")
        notes = '; '.join(notes_parts) if notes_parts else None
        
        # Check for duplicate
        sig = build_transaction_signature(
            item_id, r['movement_type'], float(r['qty']), warehouse_id, notes
        )
        if sig in existing:
            stats['skipped_duplicate'] += 1
            continue
        
        # Add to insert batch
        to_insert.append((
            item_id,
            r['movement_type'],  # 'R' or 'I'
            float(r['qty']),
            warehouse_id,
            None,  # donor_id - not in staging data
            None,  # event_id - not in staging data
            None,  # expiry_date - not in staging data
            notes,
            created_by,
        ))
        
        # Add to existing set to prevent duplicates within this batch
        existing.add(sig)
    
    stats['to_insert'] = len(to_insert)
    
    if dry_run:
        print(f"\n[DRY RUN] Would insert {len(to_insert)} records")
        # Show sample
        if to_insert:
            print("\nSample records (first 5):")
            for rec in to_insert[:5]:
                print(f"  item_id={rec[0]}, ttype={rec[1]}, qty={rec[2]}, "
                      f"warehouse_id={rec[3]}, notes={rec[7][:50] if rec[7] else 'NULL'}...")
    else:
        # Execute inserts
        try:
            from psycopg2.extras import execute_batch
            execute_batch(cur, insert_sql, to_insert, page_size=1000)
            conn.commit()
            stats['inserted'] = len(to_insert)
            print(f"\nSuccessfully inserted {stats['inserted']} records")
        except Exception as e:
            conn.rollback()
            stats['errors'].append(f"Insert failed: {str(e)}")
            raise
    
    cur.close()
    return stats


def generate_sql_migration(conn, records: list[dict], lookup_info: dict,
                           output_path: str, created_by: str = 'HADR_IMPORT'):
    """Generate SQL file for migration."""
    
    items = lookup_info.get('items', {})
    warehouses = lookup_info.get('warehouses', {})
    
    with open(output_path, 'w') as f:
        f.write("-- HADR Staging to Transaction Migration\n")
        f.write(f"-- Generated: {datetime.now().isoformat()}\n")
        f.write(f"-- Source records: {len(records)}\n\n")
        
        # Add duplicate prevention wrapper
        f.write("-- This script uses a CTE to prevent duplicates\n")
        f.write("-- It checks if a matching transaction already exists before inserting\n\n")
        
        f.write("BEGIN;\n\n")
        
        inserted_count = 0
        skipped_count = 0
        
        for r in records:
            item_id = items.get(r['item_desc'])
            warehouse_id = warehouses.get(r['warehouse_code'])
            
            # Build notes
            notes_parts = []
            if r['movement_date']:
                notes_parts.append(f"Date: {r['movement_date']}")
            if r['comments_text']:
                notes_parts.append(r['comments_text'])
            if r['source_sheet']:
                notes_parts.append(f"Source: {r['source_sheet']} Row {r['source_row_nbr']}")
            notes = '; '.join(notes_parts) if notes_parts else None
            
            # Format values
            item_id_sql = str(item_id) if item_id else 'NULL'
            warehouse_id_sql = str(warehouse_id) if warehouse_id else 'NULL'
            notes_sql = f"'{notes.replace(chr(39), chr(39)+chr(39))}'" if notes else 'NULL'
            
            # Insert with duplicate check
            f.write(f"""
INSERT INTO public.transaction (item_id, ttype, qty, warehouse_id, donor_id, event_id, expiry_date, notes, created_by)
SELECT {item_id_sql}, '{r['movement_type']}', {float(r['qty'])}, {warehouse_id_sql}, NULL, NULL, NULL, {notes_sql}, '{created_by}'
WHERE NOT EXISTS (
    SELECT 1 FROM public.transaction 
    WHERE COALESCE(item_id, -1) = COALESCE({item_id_sql}, -1)
    AND ttype = '{r['movement_type']}'
    AND qty = {float(r['qty'])}
    AND COALESCE(warehouse_id, -1) = COALESCE({warehouse_id_sql}, -1)
    AND COALESCE(notes, '') = COALESCE({notes_sql}, '')
);
""")
            inserted_count += 1
        
        f.write("\nCOMMIT;\n")
        f.write(f"\n-- Total INSERT statements: {inserted_count}\n")
    
    print(f"Generated SQL file: {output_path}")


def print_migration_summary(stats: dict, lookup_info: dict):
    """Print migration summary."""
    print("\n" + "="*60)
    print("MIGRATION SUMMARY")
    print("="*60)
    print(f"Total staging records: {stats['total_staging']}")
    print(f"Records to insert: {stats.get('to_insert', 'N/A')}")
    print(f"Inserted: {stats['inserted']}")
    print(f"Skipped (duplicate): {stats['skipped_duplicate']}")
    print(f"Skipped (item not found): {stats['skipped_no_item']}")
    print(f"Skipped (warehouse not found): {stats['skipped_no_warehouse']}")
    
    if stats['errors']:
        print(f"\nErrors/Warnings ({len(stats['errors'])}):")
        # Show unique errors
        unique_errors = list(set(stats['errors']))[:10]
        for err in unique_errors:
            print(f"  - {err}")
        if len(stats['errors']) > 10:
            print(f"  ... and {len(stats['errors']) - 10} more")
    
    print("\nLookup Tables Info:")
    if lookup_info['has_item_table']:
        print(f"  Item table: {lookup_info.get('item_table_name')} ({len(lookup_info['items'])} items loaded)")
    else:
        print("  Item table: NOT FOUND - item_id will be NULL")
    
    if lookup_info['has_warehouse_table']:
        print(f"  Warehouse table: {lookup_info.get('warehouse_table_name')} ({len(lookup_info['warehouses'])} warehouses loaded)")
    else:
        print("  Warehouse table: NOT FOUND - warehouse_id will be NULL")


def main():
    parser = argparse.ArgumentParser(description='Migrate HADR staging data to transaction table')
    parser.add_argument('--db-url', required=True, help='PostgreSQL connection URL')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be migrated without executing')
    parser.add_argument('--sql-output', help='Generate SQL file instead of direct execution')
    parser.add_argument('--date-from', help='Only migrate records from this date (YYYY-MM-DD)')
    parser.add_argument('--date-to', help='Only migrate records up to this date (YYYY-MM-DD)')
    parser.add_argument('--created-by', default='HADR_IMPORT', help='Value for created_by field')
    
    args = parser.parse_args()
    
    # Parse date filters
    date_from = None
    date_to = None
    if args.date_from:
        try:
            date_from = datetime.strptime(args.date_from, '%Y-%m-%d')
        except ValueError:
            print(f"Error: Invalid date format: {args.date_from}", file=sys.stderr)
            sys.exit(1)
    if args.date_to:
        try:
            date_to = datetime.strptime(args.date_to, '%Y-%m-%d')
        except ValueError:
            print(f"Error: Invalid date format: {args.date_to}", file=sys.stderr)
            sys.exit(1)
    
    print("Connecting to database...")
    conn = get_db_connection(args.db_url)
    
    print("Discovering lookup tables...")
    lookup_info = get_lookup_tables_info(conn)
    
    print("Fetching staging records...")
    if date_from:
        print(f"  Filtering from: {date_from.date()}")
    if date_to:
        print(f"  Filtering to: {date_to.date()}")
    
    records = get_staging_records(conn, date_from, date_to)
    print(f"Found {len(records)} staging records")
    
    if not records:
        print("No records to migrate.")
        conn.close()
        return
    
    if args.sql_output:
        generate_sql_migration(conn, records, lookup_info, args.sql_output, args.created_by)
        print_migration_summary({
            'total_staging': len(records),
            'inserted': 0,
            'skipped_duplicate': 0,
            'skipped_no_item': 0,
            'skipped_no_warehouse': 0,
            'errors': [],
        }, lookup_info)
    else:
        stats = migrate_records(conn, records, lookup_info, args.created_by, args.dry_run)
        print_migration_summary(stats, lookup_info)
    
    conn.close()
    print("\nDone.")


if __name__ == '__main__':
    main()
