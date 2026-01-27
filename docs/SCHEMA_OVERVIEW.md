# DRIMS Database Schema Overview

**Export Date**: November 12, 2025  
**Database**: PostgreSQL 16.9 (Neon)  
**Total Tables**: 47  
**Schema File**: `current_schema.sql` (3,354 lines)

---

## Table Categories

### Core ODPEM Tables (26 tables)
From the authoritative `aidmgmt-3.sql` schema:
1. **country** - Country reference data
2. **parish** - Jamaica parishes (14 parishes)
3. **event** - Disaster events
4. **donor** - Donation entities
5. **custodian** - GOJ/ODPEM warehouse custodians
6. **unitofmeasure** - Units of measure
7. **itemcatg** - Item categories
8. **item** - Relief items master
9. **donation** - Donation records
10. **donation_item** - Items in donations
11. **warehouse** - Storage facilities
12. **inventory** - Warehouse inventory
13. **location** - Bin/shelf locations
14. **item_location** - Item location tracking
15. **agency** - Distribution agencies & shelters ✅ **UPDATED**
16. **reliefrqst** - Relief requests ✅ **UPDATED**
17. **reliefrqst_item** - Request line items ✅ **UPDATED**
18. **reliefpkg** - Relief packages ✅ **UPDATED**
19. **reliefpkg_item** - Package line items
20. **transfer** - Warehouse transfers ✅ **UPDATED**
21. **transfer_item** - Transfer line items
22. **dnintake** - Donation intake
23. **dnintake_item** - Donation intake items
24. **xfintake** - Transfer intake
25. **xfintake_item** - Transfer intake items
26. **dbintake** - Distribution intake

### New AIDMGMT-3.1 Tables (6 tables)
Added for complete intake/return workflow coverage:
1. **xfreturn** - Transfer returns
2. **xfreturn_item** - Transfer return items
3. **rtintake** - Return intake
4. **rtintake_item** - Return intake items

### DRIMS Extension Tables (15 tables)
Modern workflow enhancements:
1. **user** - User authentication
2. **role** - RBAC roles
3. **user_role** - User-role assignments
4. **user_warehouse** - Warehouse access control
5. **needs_list** - Modern needs assessment
6. **needs_list_item** - Needs list items
7. **fulfilment** - Fulfilment processing
8. **fulfilment_line_item** - Fulfilment items
9. **fulfilment_edit_log** - Edit audit trail
10. **dispatch_manifest** - Dispatch tracking
11. **receipt_record** - Receipt confirmation
12. **distribution_package** - Alternative workflow
13. **distribution_package_item** - Package items
14. **transfer_request** - Transfer workflow
15. **notification** - System notifications

---

## Key Features

### Extensions Enabled
- ✅ **citext** - Case-insensitive text matching

### Foreign Key Relationships
- Comprehensive referential integrity
- Cascade rules where appropriate
- Composite foreign keys for multi-column relationships

### Constraints
- ✅ Check constraints for status codes
- ✅ Business logic validation
- ✅ Data quality enforcement

### Indexes
- Primary key indexes on all tables
- Foreign key indexes for performance
- Custom indexes for common queries
- Unique indexes for business keys

### Audit Fields
All ODPEM tables include:
- `create_by_id`, `create_dtime`
- `update_by_id`, `update_dtime`
- `version_nbr` for optimistic locking

---

## Recent Updates (aidmgmt-3.1 Migration)

5 tables updated to match aidmgmt-3.1 specification:

1. **transfer**: Added event tracking, removed transport details
2. **agency**: Added type classification and eligibility tracking
3. **reliefrqst**: Added event eligibility and enhanced notes
4. **reliefrqst_item**: Removed auto-defaults, added performance index
5. **reliefpkg**: Added receipt tracking with dedicated status

See `MIGRATION_SUMMARY.md` for detailed change log.

---

## Schema Files

- **Current Schema**: `current_schema.sql` (3,354 lines)
- **Original AIDMGMT-3**: `attached_assets/aidmgmt-3_1762964100193.sql`
- **Updated AIDMGMT-3.1**: `attached_assets/aidmgmt-3.1_1762965522221.sql`
- **Complete Schema**: `attached_assets/DRIMS_Complete_Schema_1762917808553.sql`

---

## Usage

To recreate the database from current schema:

```bash
# Drop and recreate (WARNING: Destroys all data)
PGPASSWORD=$PGPASSWORD psql -h $PGHOST -U $PGUSER -d $PGDATABASE -p $PGPORT < current_schema.sql

# Or use the initialization script
python scripts/init_db.py
```

To export fresh schema anytime:

```bash
PGPASSWORD=$PGPASSWORD pg_dump -h $PGHOST -U $PGUSER -d $PGDATABASE -p $PGPORT \
  --schema-only --no-owner --no-privileges > fresh_schema.sql
```

---

## Database Statistics

- **Total Tables**: 47
- **AIDMGMT Core**: 26 tables
- **AIDMGMT Extensions**: 6 tables
- **DRIMS Extensions**: 15 tables
- **Total Relationships**: 100+ foreign keys
- **Total Indexes**: 150+ indexes
- **Total Constraints**: 200+ constraints

---

## Compliance

✅ 100% aligned with ODPEM AIDMGMT-3.1 specification  
✅ Extended with modern DRIMS workflows  
✅ Full audit trail capabilities  
✅ Role-based access control ready  
✅ Event-driven disaster response support
