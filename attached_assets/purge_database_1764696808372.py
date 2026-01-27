#!/usr/bin/env python3
"""
Database Dump Purge Script for DRIMS/HADR Database

This script processes a PostgreSQL dump file and removes data (COPY statements)
for tables that are NOT in the preservation list, while keeping ALL schema 
elements (CREATE TABLE, indexes, constraints, sequences, etc.) intact.

Tables to preserve (data will be kept):
- country, currency, hadr_aid_movement_staging, transaction, inventory, 
- itembatch, item (items), itemcatg, parish, role, unit_of_measure (unitofmeasure),
- user_warehouse, user, user_role, reliefrqstitem_status, reliefrqst_status, 
- custodian, warehouse

All other tables will have their data purged but schema preserved.

Usage: python purge_database.py <input_file> <output_file>
"""

import re
import sys
from pathlib import Path


# Tables whose data should be PRESERVED (case-insensitive matching)
# Note: "items" -> "item", "unit_of_measure" -> "unitofmeasure" based on actual schema
TABLES_TO_PRESERVE = {
    'country',
    'currency',
    'hadr_aid_movement_staging',
    'transaction',
    'inventory',
    'itembatch',
    'item',                    # user said "items" but table is "item"
    'itemcatg',
    'parish',
    'role',
    'unitofmeasure',           # user said "unit_of_measure" but table is "unitofmeasure"
    'user_warehouse',
    'user',
    'user_role',
    'reliefrqstitem_status',
    'reliefrqst_status',
    'custodian',
    'warehouse',
}


def normalize_table_name(name: str) -> str:
    """Normalize table name for comparison (lowercase, strip quotes and schema)."""
    # Remove schema prefix if present (e.g., public.tablename -> tablename)
    if '.' in name:
        name = name.split('.')[-1]
    # Remove quotes
    name = name.replace('"', '').replace("'", '')
    return name.lower().strip()


def should_preserve_table(table_name: str) -> bool:
    """Check if a table's data should be preserved."""
    normalized = normalize_table_name(table_name)
    return normalized in TABLES_TO_PRESERVE


def process_dump(input_path: str, output_path: str) -> dict:
    """
    Process the database dump file, removing data for non-preserved tables.
    
    Returns statistics about what was processed.
    """
    stats = {
        'total_lines': 0,
        'tables_preserved': [],
        'tables_purged': [],
        'copy_blocks_processed': 0,
    }
    
    # Pattern to match COPY ... FROM stdin statements
    # Matches: COPY public.tablename (...) FROM stdin;
    # Also matches: COPY public."tablename" (...) FROM stdin;
    copy_pattern = re.compile(
        r'^COPY\s+(?:public\.)?(["\w]+)\s*\([^)]*\)\s+FROM\s+stdin;',
        re.IGNORECASE
    )
    
    with open(input_path, 'r', encoding='utf-8') as infile:
        lines = infile.readlines()
    
    stats['total_lines'] = len(lines)
    
    output_lines = []
    i = 0
    
    while i < len(lines):
        line = lines[i]
        
        # Check if this line starts a COPY block
        match = copy_pattern.match(line)
        
        if match:
            table_name = match.group(1)
            stats['copy_blocks_processed'] += 1
            
            if should_preserve_table(table_name):
                # Keep this COPY block (header + data + terminator)
                stats['tables_preserved'].append(normalize_table_name(table_name))
                output_lines.append(line)
                i += 1
                
                # Copy all data lines until we hit the terminator (\.)
                while i < len(lines) and lines[i].strip() != '\\.':
                    output_lines.append(lines[i])
                    i += 1
                
                # Copy the terminator
                if i < len(lines):
                    output_lines.append(lines[i])
                    i += 1
            else:
                # Purge this table's data - keep COPY header but replace data with empty
                stats['tables_purged'].append(normalize_table_name(table_name))
                output_lines.append(line)
                i += 1
                
                # Skip all data lines until terminator
                while i < len(lines) and lines[i].strip() != '\\.':
                    i += 1
                
                # Keep the terminator (empty COPY block)
                if i < len(lines):
                    output_lines.append(lines[i])
                    i += 1
        else:
            # Not a COPY line - keep it as-is
            output_lines.append(line)
            i += 1
    
    # Write output
    with open(output_path, 'w', encoding='utf-8') as outfile:
        outfile.writelines(output_lines)
    
    # Deduplicate and sort stats lists
    stats['tables_preserved'] = sorted(set(stats['tables_preserved']))
    stats['tables_purged'] = sorted(set(stats['tables_purged']))
    
    return stats


def main():
    if len(sys.argv) < 2:
        input_file = '/mnt/user-data/uploads/database_dump_2025-12-02.sql'
        output_file = '/mnt/user-data/outputs/database_dump_2025-12-02_purged.sql'
    elif len(sys.argv) == 2:
        input_file = sys.argv[1]
        output_file = str(Path(input_file).stem) + '_purged.sql'
    else:
        input_file = sys.argv[1]
        output_file = sys.argv[2]
    
    print(f"Database Dump Purge Script")
    print(f"=" * 60)
    print(f"Input:  {input_file}")
    print(f"Output: {output_file}")
    print()
    
    print(f"Tables to PRESERVE (data will be kept):")
    for table in sorted(TABLES_TO_PRESERVE):
        print(f"  - {table}")
    print()
    
    # Process the dump
    stats = process_dump(input_file, output_file)
    
    # Print results
    print(f"Processing Complete")
    print(f"=" * 60)
    print(f"Total lines processed: {stats['total_lines']:,}")
    print(f"COPY blocks processed: {stats['copy_blocks_processed']}")
    print()
    
    print(f"Tables with data PRESERVED ({len(stats['tables_preserved'])}):")
    for table in stats['tables_preserved']:
        print(f"  ✓ {table}")
    print()
    
    print(f"Tables with data PURGED ({len(stats['tables_purged'])}):")
    for table in stats['tables_purged']:
        print(f"  ✗ {table}")
    print()
    
    print(f"Output written to: {output_file}")
    print()
    print("NOTE: All schema elements (tables, indexes, constraints, sequences,")
    print("      triggers, views) are preserved. Only the data rows were removed")
    print("      for the purged tables.")


if __name__ == '__main__':
    main()
