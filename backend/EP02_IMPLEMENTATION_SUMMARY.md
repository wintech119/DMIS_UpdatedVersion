# EP-02 Supply Replenishment Database Integration - Implementation Summary

## Overview

This document summarizes the database schema implementation for the DMIS Supply Replenishment Module (EP-02). The system has been updated to use a proper PostgreSQL database schema instead of JSON file storage, making it production-ready.

## Changes Made

### 1. Database Schema (SQL)

**File:** `backend/EP02_SUPPLY_REPLENISHMENT_SCHEMA.sql`

#### Alterations to Existing Tables:
- **event**: Added `current_phase`, `phase_changed_at`, `phase_changed_by`
- **warehouse**: Added `min_stock_threshold`, `last_sync_dtime`, `sync_status`
- **item**: Added `baseline_burn_rate`, `min_stock_threshold`, `criticality_level`
- **transfer**: Added `dispatched_at`, `dispatched_by`, `expected_arrival`, `received_at`, `received_by`, `needs_list_id`

#### New Tables Created:
1. **event_phase_config** - Phase-specific configuration (demand/planning windows, safety factors)
2. **event_phase_history** - Audit trail for phase transitions
3. **needs_list** - Main needs list header with workflow status
4. **needs_list_item** - Individual item lines with calculations and horizon allocations
5. **needs_list_audit** - Immutable audit trail for all actions
6. **burn_rate_snapshot** - Historical burn rate calculations for trending
7. **warehouse_sync_log** - Data freshness tracking
8. **procurement** - Horizon C procurement orders
9. **procurement_item** - Procurement line items
10. **supplier** - Supplier/vendor master
11. **lead_time_config** - Configurable lead times for three horizons

#### Views Created:
1. **v_stock_status** - Real-time stock status with freshness indicators
2. **v_inbound_stock** - Confirmed inbound by source type

#### Triggers Created:
1. **trg_warehouse_sync_status** - Auto-update warehouse sync status
2. **trg_event_phase_change** - Log phase transitions to history table

### 2. Django Models

**File:** `backend/replenishment/models.py`

Created Django ORM models for all new tables:
- `EventPhaseConfig` - Phase configuration model
- `EventPhaseHistory` - Phase change audit model
- `NeedsList` - Main needs list model with workflow tracking
- `NeedsListItem` - Line item model with burn rates and horizons
- `NeedsListAudit` - Audit trail model
- `BurnRateSnapshot` - Historical burn rate model
- `WarehouseSyncLog` - Sync tracking model
- `Supplier` - Supplier master model
- `Procurement` - Procurement order model
- `ProcurementItem` - Procurement line item model
- `LeadTimeConfig` - Lead time configuration model

**Key Features:**
- All models include proper constraints matching database schema
- Audit fields (create_by_id, create_dtime, update_by_id, update_dtime, version_nbr)
- Choice fields for enums (status codes, severity levels, etc.)
- Foreign key relationships where appropriate
- Proper indexing for query performance

### 3. Database-Backed Workflow Store

**File:** `backend/replenishment/workflow_store_db.py`

Created database-backed version of the workflow store using Django ORM:
- `create_draft()` - Creates needs list with line items in database
- `get_record()` - Retrieves needs list from database
- `update_record()` - Updates needs list in database
- `apply_overrides()` - Applies line item adjustments
- `add_line_overrides()` - Adds quantity overrides with audit trail
- `add_line_review_notes()` - Adds reviewer comments with audit trail
- `transition_status()` - Changes workflow status with audit trail

**Advantages over JSON file storage:**
- Transactional integrity (ACID properties)
- Concurrent access without file locks
- Query capabilities (search, filter, aggregate)
- Automatic audit trail
- No data loss on server restart
- Production-ready scaling

### 4. Migration Guide

**File:** `backend/DATABASE_MIGRATION_GUIDE.md`

Comprehensive guide for database administrators covering:
- Pre-migration checklist and backups
- Step-by-step migration procedure
- Verification queries
- Rollback procedures
- Common issues and solutions
- Migration timeline and responsibilities

## How to Apply the Changes

### Step 1: Database Migration (DBA Task)

1. **Backup the database:**
   ```bash
   pg_dump -h localhost -U dmis_user -d dmis_db -F c -b -v -f dmis_backup_$(date +%Y%m%d_%H%M%S).backup
   ```

2. **Stop application services:**
   ```bash
   sudo systemctl stop dmis_api
   ```

3. **Apply schema:**
   ```bash
   psql -h localhost -U dmis_user -d dmis_db -f backend/EP02_SUPPLY_REPLENISHMENT_SCHEMA.sql
   ```

4. **Verify schema:**
   ```sql
   -- Check new tables exist
   SELECT table_name FROM information_schema.tables
   WHERE table_schema = 'public'
     AND table_name LIKE 'needs_list%';

   -- Check constraints
   SELECT conname FROM pg_constraint
   WHERE conrelid = 'public.needs_list'::regclass;
   ```

5. **Restart services:**
   ```bash
   sudo systemctl start dmis_api
   ```

### Step 2: Update Django Settings

**File:** `backend/dmis_api/settings.py`

Add replenishment models to Django:
```python
INSTALLED_APPS = [
    # ... existing apps ...
    'replenishment',
]
```

### Step 3: Switch to Database-Backed Store

**Option A: Gradual Migration (Recommended)**

Keep both stores active during transition:

```python
# In backend/replenishment/views.py
import os

# Check environment variable to choose store
USE_DB_STORE = os.getenv('NEEDS_USE_DB_STORE', '0') == '1'

if USE_DB_STORE:
    from replenishment import workflow_store_db as workflow_store
else:
    from replenishment import workflow_store
```

Set environment variable:
```bash
export NEEDS_USE_DB_STORE=1
```

**Option B: Direct Replacement**

Replace import statement:
```python
# Old:
from replenishment import workflow_store

# New:
from replenishment import workflow_store_db as workflow_store
```

### Step 4: Test the Changes

1. **Create a test needs list:**

3. **Verify in database:**
   ```sql
   SELECT needs_list_no, status_code, create_dtime
   FROM public.needs_list
   ORDER BY create_dtime DESC
   LIMIT 5;

   SELECT COUNT(*) FROM public.needs_list_item;
   SELECT COUNT(*) FROM public.needs_list_audit;
   ```

## Benefits of Database-Backed Storage

### Production Readiness
- **No data loss**: Persists across server restarts
- **Concurrent access**: Multiple users can work simultaneously
- **Transactional**: All-or-nothing operations ensure data integrity
- **Scalable**: Can handle thousands of needs lists

### Operational Improvements
- **Audit trail**: Every action is logged automatically
- **Query capabilities**: Can search, filter, and aggregate needs lists
- **Reporting**: Can generate reports directly from database
- **Data integrity**: Foreign key constraints prevent orphaned records

### Developer Experience
- **Django ORM**: Use Python instead of raw SQL
- **Type safety**: Model validation prevents bad data
- **Migrations**: Track schema changes over time
- **Testing**: Easy to set up test databases

## Backward Compatibility

The new `workflow_store_db.py` maintains the same function signatures as the original `workflow_store.py`, ensuring:
- Existing API endpoints continue to work
- No changes needed to views.py
- Gradual migration path available
- Can switch back to JSON files if needed (though not recommended)

## Migration Path for Existing JSON Data (If Applicable)

If you have existing needs lists in JSON files that need to be migrated:

```python
import json
from pathlib import Path
from django.db import transaction
from replenishment import workflow_store_db
from replenishment.models import NeedsList

# Load existing JSON store
json_path = Path(__file__).parent / '.local' / 'needs_list_store.json'
with json_path.open('r') as f:
    json_data = json.load(f)

# Migrate each needs list
for needs_list_id, record in json_data.get('needs_lists', {}).items():
    with transaction.atomic():
        # Create needs list in database
        snapshot = record.get('snapshot', {})
        items = snapshot.get('items', [])
        warnings = snapshot.get('warnings', [])

        payload = {
            'event_id': record.get('event_id'),
            'warehouse_id': record.get('warehouse_id'),
            'phase': record.get('phase'),
            'as_of_datetime': record.get('as_of_datetime'),
            'planning_window_days': record.get('planning_window_days'),
        }

        new_record = workflow_store_db.create_draft(
            payload=payload,
            items=items,
            warnings=warnings,
            actor=record.get('created_by', 'MIGRATION')
        )

        # Update status if not DRAFT
        if record.get('status') != 'DRAFT':
            workflow_store_db.transition_status(
                record=new_record,
                to_status=record.get('status'),
                actor=record.get('updated_by', 'MIGRATION')
            )

        print(f"Migrated {needs_list_id} → {new_record['needs_list_no']}")
```

## Next Steps

1. **Apply database schema** (DBA task)
2. **Test in development environment**
3. **Migrate existing JSON data** (if applicable)
4. **Switch to database store** (set env var or update imports)
5. **Deploy to staging**
6. **Run acceptance tests**
7. **Deploy to production**

## Rollback Plan

If issues are encountered:

1. **Stop application:**
   ```bash
   sudo systemctl stop dmis_api
   ```

2. **Restore database:**
   ```bash
   pg_restore -h localhost -U dmis_user -d dmis_db dmis_backup_*.backup
   ```

3. **Revert code changes:**
   ```bash
   git revert <commit-hash>
   ```

4. **Restart application:**
   ```bash
   sudo systemctl start dmis_api
   ```

## Support and Troubleshooting

### Common Issues

**Issue**: `relation "needs_list" does not exist`
- **Solution**: Schema not applied. Run SQL script.

**Issue**: `ImportError: cannot import name 'NeedsList'`
- **Solution**: Models not installed. Add 'replenishment' to INSTALLED_APPS.

**Issue**: `IntegrityError: duplicate key value violates unique constraint`
- **Solution**: Duplicate needs_list_no. Check sequence generator.

**Issue**: `OperationalError: no such table: needs_list`
- **Solution**: Using SQLite instead of PostgreSQL. Check DATABASE settings.

### Performance Tuning

After migration, analyze query performance:
```sql
-- Check index usage
SELECT schemaname, tablename, indexname, idx_scan
FROM pg_stat_user_indexes
WHERE schemaname = 'public'
  AND tablename LIKE 'needs_list%'
ORDER BY idx_scan DESC;

-- Check slow queries
SELECT query, calls, mean_exec_time
FROM pg_stat_statements
WHERE query LIKE '%needs_list%'
ORDER BY mean_exec_time DESC
LIMIT 10;
```

## Conclusion

The EP-02 database schema integration makes DMIS production-ready by:
- Replacing temporary JSON file storage with PostgreSQL persistence
- Adding proper audit trails for compliance
- Enabling concurrent multi-user workflows
- Providing query capabilities for reporting and analytics
- Maintaining backward compatibility with existing code

Follow the migration guide carefully and test thoroughly in development before deploying to production.

---

**Files Created:**
- `backend/EP02_SUPPLY_REPLENISHMENT_SCHEMA.sql` - Database schema
- `backend/DATABASE_MIGRATION_GUIDE.md` - Migration instructions
- `backend/replenishment/models.py` - Django ORM models
- `backend/replenishment/workflow_store_db.py` - Database-backed workflow store
- `backend/EP02_IMPLEMENTATION_SUMMARY.md` - This document

**Last Updated:** February 2026
**Version:** 1.0
