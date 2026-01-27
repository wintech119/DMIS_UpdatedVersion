"""
Database Migration Script: Normalize Phone Numbers to Standard Format
+1 (XXX) XXX-XXXX

This script migrates existing phone numbers across all DRIMS tables to the new
standardized format required by the system.

Affected Tables:
- warehouse (phone_no)
- agency (phone_no)
- donor (phone_no)
- Any other tables with phone_no fields

Usage:
    python scripts/migrate_phone_numbers.py [--dry-run]

Options:
    --dry-run    Preview changes without applying them
"""

import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app import create_app
from app.db import db
from app.db.models import Warehouse, Agency, Donor
from app.core.phone_utils import normalize_phone_number, validate_phone_format
from sqlalchemy import text

def migrate_table_phone_numbers(table_class, table_name, dry_run=False):
    """
    Migrate phone numbers for a specific table
    
    Args:
        table_class: SQLAlchemy model class
        table_name: Name of the table for logging
        dry_run: If True, preview changes without committing
    
    Returns:
        tuple: (updated_count, failed_count, failed_records)
    """
    print(f"\n{'='*80}")
    print(f"Processing {table_name} table...")
    print(f"{'='*80}")
    
    records = table_class.query.all()
    print(f"Found {len(records)} records to process")
    
    updated_count = 0
    failed_count = 0
    failed_records = []
    
    for record in records:
        if not hasattr(record, 'phone_no') or not record.phone_no:
            continue
        
        current_phone = record.phone_no
        
        # Skip if already in correct format
        if validate_phone_format(current_phone):
            print(f"✓ ID {getattr(record, f'{table_name}_id', 'N/A')}: {current_phone} (already valid)")
            continue
        
        # Try to normalize
        normalized_phone = normalize_phone_number(current_phone)
        
        if normalized_phone:
            print(f"→ ID {getattr(record, f'{table_name}_id', 'N/A')}: {current_phone} → {normalized_phone}")
            
            if not dry_run:
                record.phone_no = normalized_phone
                updated_count += 1
            else:
                print(f"  [DRY RUN] Would update to: {normalized_phone}")
                updated_count += 1
        else:
            print(f"✗ ID {getattr(record, f'{table_name}_id', 'N/A')}: {current_phone} (CANNOT NORMALIZE)")
            failed_count += 1
            failed_records.append({
                'id': getattr(record, f'{table_name}_id', 'N/A'),
                'current_phone': current_phone,
                'table': table_name
            })
    
    return updated_count, failed_count, failed_records

def main():
    """Main migration execution"""
    dry_run = '--dry-run' in sys.argv
    
    print("\n" + "="*80)
    print("DRIMS Phone Number Migration Script")
    print("Standard Format: +1 (XXX) XXX-XXXX")
    print("="*80)
    
    if dry_run:
        print("\n⚠️  DRY RUN MODE - No changes will be committed ⚠️\n")
    else:
        print("\n🚀 LIVE MODE - Changes will be committed to the database 🚀\n")
        response = input("Are you sure you want to proceed? (yes/no): ")
        if response.lower() != 'yes':
            print("Migration cancelled.")
            return
    
    app = create_app()
    
    with app.app_context():
        all_updated = 0
        all_failed = 0
        all_failed_records = []
        
        # Migrate Warehouse phone numbers
        try:
            updated, failed, failed_recs = migrate_table_phone_numbers(
                Warehouse, 'warehouse', dry_run
            )
            all_updated += updated
            all_failed += failed
            all_failed_records.extend(failed_recs)
        except Exception as e:
            print(f"❌ Error migrating warehouse table: {str(e)}")
        
        # Migrate Agency phone numbers
        try:
            updated, failed, failed_recs = migrate_table_phone_numbers(
                Agency, 'agency', dry_run
            )
            all_updated += updated
            all_failed += failed
            all_failed_records.extend(failed_recs)
        except Exception as e:
            print(f"❌ Error migrating agency table: {str(e)}")
        
        # Migrate Donor phone numbers
        try:
            updated, failed, failed_recs = migrate_table_phone_numbers(
                Donor, 'donor', dry_run
            )
            all_updated += updated
            all_failed += failed
            all_failed_records.extend(failed_recs)
        except Exception as e:
            print(f"❌ Error migrating donor table: {str(e)}")
        
        # Commit changes if not dry run
        if not dry_run and all_updated > 0:
            try:
                db.session.commit()
                print(f"\n✅ Successfully committed {all_updated} phone number updates")
            except Exception as e:
                db.session.rollback()
                print(f"\n❌ Error committing changes: {str(e)}")
                return
        
        # Print summary
        print(f"\n{'='*80}")
        print("MIGRATION SUMMARY")
        print(f"{'='*80}")
        print(f"Total records updated: {all_updated}")
        print(f"Total records failed: {all_failed}")
        
        if all_failed_records:
            print(f"\n{'='*80}")
            print("FAILED RECORDS (Manual Review Required)")
            print(f"{'='*80}")
            for record in all_failed_records:
                print(f"Table: {record['table']}, ID: {record['id']}, Phone: {record['current_phone']}")
            print(f"\n⚠️  These records require manual correction by a CUSTODIAN user")
        
        if dry_run:
            print(f"\n⚠️  This was a DRY RUN - no changes were committed")
            print(f"Run without --dry-run to apply changes")
        else:
            print(f"\n✅ Migration complete!")

if __name__ == '__main__':
    main()
