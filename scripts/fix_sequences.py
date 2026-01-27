#!/usr/bin/env python3
"""
DMIS Database Sequence Reset Script
====================================
Purpose: Reset all auto-increment sequences to be in sync with max ID values.
Usage:   python scripts/fix_sequences.py

Run after database restore/import to fix "duplicate key violates unique constraint" errors.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text


LEGACY_SEQUENCES = [
    ('item', 'item_id', 'public.item_new_item_id_seq'),
]


def get_all_sequences(db_session):
    """Dynamically discover all sequences and their associated tables."""
    query = text("""
        SELECT 
            t.relname as table_name,
            a.attname as column_name,
            pg_get_serial_sequence(t.relname::text, a.attname::text) as sequence_name
        FROM pg_class t
        JOIN pg_attribute a ON a.attrelid = t.oid
        JOIN pg_attrdef d ON d.adrelid = t.oid AND d.adnum = a.attnum
        WHERE t.relkind = 'r'
        AND pg_get_serial_sequence(t.relname::text, a.attname::text) IS NOT NULL
        ORDER BY t.relname;
    """)
    
    result = db_session.execute(query)
    sequences = [(row.table_name, row.column_name, row.sequence_name) for row in result]
    
    for legacy_seq in LEGACY_SEQUENCES:
        if legacy_seq not in sequences:
            sequences.append(legacy_seq)
    
    return sorted(sequences, key=lambda x: x[0])


def check_sequence_status(db_session, table_name, column_name, sequence_name):
    """Check if a sequence is out of sync with its table."""
    if table_name == 'user':
        table_ref = '"user"'
    else:
        table_ref = table_name
    
    max_query = text(f'SELECT COALESCE(MAX({column_name}), 0) as max_id FROM {table_ref}')
    seq_query = text(f"SELECT last_value FROM {sequence_name}")
    
    max_id = db_session.execute(max_query).scalar()
    seq_value = db_session.execute(seq_query).scalar()
    
    is_synced = seq_value > max_id
    return max_id, seq_value, is_synced


def fix_sequence(db_session, table_name, column_name, sequence_name):
    """Reset a sequence to max(id) + 1."""
    if table_name == 'user':
        table_ref = '"user"'
    else:
        table_ref = table_name
    
    fix_query = text(f"""
        SELECT setval('{sequence_name}', 
            COALESCE((SELECT MAX({column_name}) FROM {table_ref}), 0) + 1,
            false
        )
    """)
    
    new_value = db_session.execute(fix_query).scalar()
    db_session.commit()
    return new_value


def main():
    """Main function to check and fix all sequences."""
    from drims_app import app
    from app.db import db
    
    with app.app_context():
        print("=" * 60)
        print("DMIS Database Sequence Reset Script")
        print("=" * 60)
        print()
        
        sequences = get_all_sequences(db.session)
        
        if not sequences:
            print("No sequences found in database.")
            return
        
        print(f"Found {len(sequences)} sequence(s) to check.\n")
        
        issues_found = 0
        fixed_count = 0
        
        print(f"{'Table':<25} {'Column':<15} {'Max ID':<10} {'Seq Val':<10} {'Status'}")
        print("-" * 75)
        
        for table_name, column_name, sequence_name in sequences:
            try:
                max_id, seq_value, is_synced = check_sequence_status(
                    db.session, table_name, column_name, sequence_name
                )
                
                if is_synced:
                    status = "OK"
                else:
                    status = "OUT OF SYNC"
                    issues_found += 1
                
                max_display = str(max_id) if max_id else "(empty)"
                print(f"{table_name:<25} {column_name:<15} {max_display:<10} {seq_value:<10} {status}")
                
                if not is_synced:
                    new_value = fix_sequence(db.session, table_name, column_name, sequence_name)
                    print(f"  -> FIXED: Sequence reset to {new_value}")
                    fixed_count += 1
                    
            except Exception as e:
                print(f"{table_name:<25} {column_name:<15} ERROR: {str(e)}")
        
        print()
        print("=" * 60)
        print(f"Summary: {issues_found} issue(s) found, {fixed_count} fixed.")
        print("=" * 60)


if __name__ == '__main__':
    main()
