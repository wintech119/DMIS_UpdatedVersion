#!/usr/bin/env python3
"""
Populate UPC Inventory from MLSS Staging Data

This script:
1. Creates missing items in the item table
2. Calculates net inventory (Received - Issued) per item
3. Inserts inventory records for UPC warehouse (inventory_id = 5)
"""

import os
import sys
import re
from datetime import datetime
from decimal import Decimal

def get_db_connection():
    """Create database connection."""
    try:
        import psycopg2
        db_url = os.environ.get('DATABASE_URL')
        if not db_url:
            print("Error: DATABASE_URL not set", file=sys.stderr)
            sys.exit(1)
        return psycopg2.connect(db_url)
    except ImportError:
        print("Error: psycopg2 not installed", file=sys.stderr)
        sys.exit(1)

def generate_item_code(item_desc: str, existing_codes: set) -> str:
    """Generate a unique item code from description (max 16 chars)."""
    clean = re.sub(r'[^A-Za-z0-9]', '', item_desc.upper())[:12]
    if not clean:
        clean = "ITEM"
    
    code = clean
    counter = 1
    while code in existing_codes:
        suffix = str(counter)
        code = clean[:16-len(suffix)] + suffix
        counter += 1
    
    existing_codes.add(code)
    return code[:16]

def create_missing_items(conn, dry_run=False):
    """Create items that exist in staging but not in item table."""
    cur = conn.cursor()
    
    cur.execute("SELECT MAX(item_id) FROM item")
    max_id = cur.fetchone()[0] or 0
    next_id = max_id + 1
    
    cur.execute("SELECT item_code FROM item")
    existing_codes = {row[0] for row in cur.fetchall()}
    
    cur.execute("SELECT UPPER(TRIM(item_name)) FROM item")
    existing_names = {row[0] for row in cur.fetchall()}
    
    cur.execute("""
        SELECT DISTINCT s.item_desc, s.category_code,
            CASE s.category_code 
                WHEN 'FOOD_WATER' THEN 1
                WHEN 'MEDICAL' THEN 2
                WHEN 'SHELTER' THEN 3
                WHEN 'HYGIENE' THEN 4
                WHEN 'LOGS_ENGR' THEN 5
            END as category_id
        FROM hadr_aid_movement_staging s
        LEFT JOIN item i ON UPPER(TRIM(s.item_desc)) = UPPER(TRIM(i.item_name))
        WHERE s.create_by_id = 'MLSS_IMPORT'
        AND i.item_id IS NULL
        ORDER BY category_id, s.item_desc
    """)
    
    all_missing = cur.fetchall()
    
    seen_names = set(existing_names)
    missing_items = []
    for desc, cat, cat_id in all_missing:
        name_upper = desc.upper().strip()
        if name_upper not in seen_names:
            missing_items.append((desc, cat, cat_id))
            seen_names.add(name_upper)
    
    print(f"Found {len(all_missing)} potentially missing items")
    print(f"After deduplication: {len(missing_items)} unique items to create")
    
    if dry_run:
        print("\n[DRY RUN] Would create these items:")
        for item_desc, category_code, category_id in missing_items[:10]:
            print(f"  {category_code}: {item_desc[:50]}")
        if len(missing_items) > 10:
            print(f"  ... and {len(missing_items) - 10} more")
        return []
    
    created_items = []
    for item_desc, category_code, category_id in missing_items:
        item_code = generate_item_code(item_desc, existing_codes)
        item_name = item_desc.upper()[:60]
        
        cur.execute("""
            INSERT INTO item (
                item_id, item_code, item_name, sku_code, category_id, item_desc,
                reorder_qty, default_uom_code, units_size_vary_flag, is_batched_flag,
                can_expire_flag, issuance_order, status_code, create_by_id,
                create_dtime, update_by_id, update_dtime, version_nbr
            ) VALUES (
                %s, %s, %s, %s, %s, 'GOODS',
                10, 'EA', false, true,
                false, 'FIFO', 'A', 'MLSS_IMPORT',
                CURRENT_TIMESTAMP, 'MLSS_IMPORT', CURRENT_TIMESTAMP, 1
            )
        """, (next_id, item_code, item_name, item_code, category_id))
        
        created_items.append((next_id, item_name))
        next_id += 1
    
    conn.commit()
    print(f"Created {len(created_items)} new items (IDs {max_id + 1} to {next_id - 1})")
    return created_items

def calculate_net_inventory(conn):
    """Calculate net inventory (Received - Issued) per item for MLSS data."""
    cur = conn.cursor()
    
    cur.execute("""
        SELECT 
            UPPER(TRIM(s.item_desc)) as item_name,
            SUM(CASE WHEN s.movement_type = 'R' THEN s.qty ELSE 0 END) as received,
            SUM(CASE WHEN s.movement_type = 'I' THEN s.qty ELSE 0 END) as issued,
            SUM(CASE WHEN s.movement_type = 'R' THEN s.qty ELSE 0 END) - 
            SUM(CASE WHEN s.movement_type = 'I' THEN s.qty ELSE 0 END) as net_qty
        FROM hadr_aid_movement_staging s
        WHERE s.create_by_id = 'MLSS_IMPORT'
        GROUP BY UPPER(TRIM(s.item_desc))
        ORDER BY item_name
    """)
    
    inventory_data = []
    for row in cur.fetchall():
        item_name, received, issued, net_qty = row
        inventory_data.append({
            'item_name': item_name,
            'received': float(received),
            'issued': float(issued),
            'net_qty': float(net_qty)
        })
    
    print(f"\nCalculated net inventory for {len(inventory_data)} unique items")
    
    positive = sum(1 for i in inventory_data if i['net_qty'] > 0)
    zero = sum(1 for i in inventory_data if i['net_qty'] == 0)
    negative = sum(1 for i in inventory_data if i['net_qty'] < 0)
    
    print(f"  Positive stock: {positive} items")
    print(f"  Zero stock: {zero} items")
    print(f"  Negative stock: {negative} items (issued more than received)")
    
    return inventory_data

def populate_upc_inventory(conn, inventory_data, dry_run=False):
    """Insert inventory records for UPC warehouse (inventory_id = 5)."""
    cur = conn.cursor()
    
    cur.execute("DELETE FROM inventory WHERE inventory_id = 5")
    deleted = cur.rowcount
    if deleted > 0:
        print(f"\nCleared {deleted} existing UPC inventory records")
    
    cur.execute("SELECT item_id, UPPER(TRIM(item_name)) as item_name FROM item")
    item_lookup = {row[1]: row[0] for row in cur.fetchall()}
    
    inserted = 0
    skipped_no_item = 0
    skipped_zero = 0
    
    for inv in inventory_data:
        item_id = item_lookup.get(inv['item_name'])
        
        if not item_id:
            skipped_no_item += 1
            continue
        
        usable_qty = max(0, inv['net_qty'])
        
        if usable_qty == 0:
            skipped_zero += 1
            continue
        
        if dry_run:
            inserted += 1
            continue
        
        cur.execute("""
            INSERT INTO inventory (
                inventory_id, item_id, usable_qty, reserved_qty, defective_qty,
                expired_qty, uom_code, status_code, reorder_qty,
                create_by_id, create_dtime, update_by_id, update_dtime, version_nbr
            ) VALUES (
                5, %s, %s, 0, 0,
                0, 'EA', 'A', 10,
                'MLSS_IMPORT', CURRENT_TIMESTAMP, 'MLSS_IMPORT', CURRENT_TIMESTAMP, 1
            )
        """, (item_id, usable_qty))
        inserted += 1
    
    if not dry_run:
        conn.commit()
    
    print(f"\n{'[DRY RUN] Would insert' if dry_run else 'Inserted'} {inserted} inventory records for UPC")
    print(f"  Skipped (item not found): {skipped_no_item}")
    print(f"  Skipped (zero/negative stock): {skipped_zero}")
    
    return inserted

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Populate UPC Inventory from MLSS data')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done')
    args = parser.parse_args()
    
    print("=" * 60)
    print("MLSS -> UPC Inventory Population")
    print("=" * 60)
    
    conn = get_db_connection()
    
    try:
        print("\nStep 1: Creating missing items...")
        create_missing_items(conn, args.dry_run)
        
        print("\nStep 2: Calculating net inventory...")
        inventory_data = calculate_net_inventory(conn)
        
        print("\nStep 3: Populating UPC inventory...")
        populate_upc_inventory(conn, inventory_data, args.dry_run)
        
        print("\n" + "=" * 60)
        print("COMPLETED" + (" [DRY RUN]" if args.dry_run else ""))
        print("=" * 60)
        
    except Exception as e:
        conn.rollback()
        print(f"\nError: {e}", file=sys.stderr)
        raise
    finally:
        conn.close()

if __name__ == '__main__':
    main()
