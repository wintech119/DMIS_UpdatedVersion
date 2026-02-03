# DMIS EP-02 Database Migration Guide

## Overview

This guide outlines the steps to apply the EP-02 Supply Replenishment Module database schema changes to the DMIS PostgreSQL database.

## Prerequisites

- **PostgreSQL 16+** database server
- **Database Administrator** access
- **Backup** of current database
- **pg_dump** and **psql** command-line tools
- Estimated downtime: **15-30 minutes** for medium-sized databases

## Pre-Migration Checklist

### 1. Verify Current Schema
```sql
-- Check existing tables
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN ('event', 'warehouse', 'item', 'transfer', 'inventory');

-- Check for conflicting table names (should return 0 rows)
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN ('needs_list', 'procurement', 'supplier', 'lead_time_config');
```

### 2. Create Backup
```bash
# Full database backup
pg_dump -h localhost -U dmis_user -d dmis_db -F c -b -v -f dmis_backup_pre_ep02_$(date +%Y%m%d_%H%M%S).backup

# Schema-only backup (faster, for rollback)
pg_dump -h localhost -U dmis_user -d dmis_db --schema-only -f dmis_schema_backup_$(date +%Y%m%d_%H%M%S).sql
```

### 3. Verify Dependencies
```sql
-- Check for foreign key constraints on tables being altered
SELECT
    tc.table_name,
    kcu.column_name,
    ccu.table_name AS foreign_table_name,
    ccu.column_name AS foreign_column_name
FROM information_schema.table_constraints AS tc
JOIN information_schema.key_column_usage AS kcu
  ON tc.constraint_name = kcu.constraint_name
JOIN information_schema.constraint_column_usage AS ccu
  ON ccu.constraint_name = tc.constraint_name
WHERE constraint_type = 'FOREIGN KEY'
  AND tc.table_name IN ('event', 'warehouse', 'item', 'transfer');
```

## Migration Steps

### Step 1: Stop Application Services

```bash
# Stop Django API server
sudo systemctl stop dmis_api

# Stop Nginx (if applicable)
sudo systemctl stop nginx

# Verify no active connections to database
psql -h localhost -U dmis_user -d dmis_db -c "SELECT COUNT(*) FROM pg_stat_activity WHERE datname = 'dmis_db' AND state = 'active';"
```

### Step 2: Apply Schema Changes

```bash
# Connect to database
psql -h localhost -U dmis_user -d dmis_db

# Or apply from file
psql -h localhost -U dmis_user -d dmis_db -f EP02_SUPPLY_REPLENISHMENT_SCHEMA.sql
```

**Expected Output:**
```
ALTER TABLE
ALTER TABLE
ALTER TABLE
...
CREATE TABLE
CREATE INDEX
COMMENT
...
INSERT 0 3
```

### Step 3: Verify Schema Changes

```sql
-- Verify new columns in event table
\d+ event

-- Verify new columns in warehouse table
\d+ warehouse

-- Verify new columns in item table
\d+ item

-- Verify new columns in transfer table
\d+ transfer

-- Verify new tables exist
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN (
    'needs_list',
    'needs_list_item',
    'needs_list_audit',
    'event_phase_config',
    'event_phase_history',
    'burn_rate_snapshot',
    'warehouse_sync_log',
    'procurement',
    'procurement_item',
    'supplier',
    'lead_time_config'
  )
ORDER BY table_name;

-- Verify constraints
SELECT conname, contype
FROM pg_constraint
WHERE conrelid = 'public.needs_list'::regclass;

-- Verify indexes
\di public.idx_needs_list_*

-- Verify triggers
SELECT trigger_name, event_manipulation, event_object_table
FROM information_schema.triggers
WHERE trigger_schema = 'public'
  AND trigger_name IN ('trg_warehouse_sync_status', 'trg_event_phase_change');

-- Verify views
SELECT table_name
FROM information_schema.views
WHERE table_schema = 'public'
  AND table_name IN ('v_stock_status', 'v_inbound_stock');
```

### Step 4: Apply Initial Data

```sql
-- Verify default lead time config was inserted
SELECT * FROM public.lead_time_config WHERE is_default = TRUE;

-- Update existing events with default phase if NULL
UPDATE public.event
SET current_phase = 'BASELINE',
    phase_changed_at = update_dtime,
    phase_changed_by = update_by_id
WHERE current_phase IS NULL;

-- Update existing warehouses with sync status
UPDATE public.warehouse
SET sync_status = CASE
    WHEN last_sync_dtime IS NULL THEN 'UNKNOWN'
    WHEN last_sync_dtime > NOW() - INTERVAL '2 hours' THEN 'ONLINE'
    WHEN last_sync_dtime > NOW() - INTERVAL '6 hours' THEN 'STALE'
    ELSE 'OFFLINE'
END
WHERE sync_status = 'UNKNOWN';
```

### Step 5: Grant Permissions

```sql
-- Grant permissions to application user
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO dmis_app_user;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO dmis_app_user;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO dmis_readonly_user;

-- Specific grants for new tables
GRANT ALL PRIVILEGES ON TABLE public.needs_list TO dmis_app_user;
GRANT ALL PRIVILEGES ON TABLE public.needs_list_item TO dmis_app_user;
GRANT ALL PRIVILEGES ON TABLE public.needs_list_audit TO dmis_app_user;
GRANT ALL PRIVILEGES ON TABLE public.procurement TO dmis_app_user;
GRANT ALL PRIVILEGES ON TABLE public.supplier TO dmis_app_user;
GRANT ALL PRIVILEGES ON TABLE public.lead_time_config TO dmis_app_user;
```

### Step 6: Test Schema Integrity

```sql
-- Test inserting a sample needs list (rollback after test)
BEGIN;

INSERT INTO public.needs_list (
    needs_list_no,
    event_id,
    warehouse_id,
    event_phase,
    calculation_dtime,
    demand_window_hours,
    planning_window_hours,
    safety_factor,
    data_freshness_level,
    status_code,
    create_by_id,
    update_by_id
) VALUES (
    'NL-TEST-001',
    1,  -- Ensure this event_id exists
    1,  -- Ensure this warehouse_id exists
    'BASELINE',
    NOW(),
    720,
    720,
    1.25,
    'HIGH',
    'DRAFT',
    'SYSTEM',
    'SYSTEM'
);

-- Verify insertion
SELECT * FROM public.needs_list WHERE needs_list_no = 'NL-TEST-001';

-- Test audit trigger
UPDATE public.needs_list
SET status_code = 'SUBMITTED'
WHERE needs_list_no = 'NL-TEST-001';

-- Verify audit entry (should be empty in test)
SELECT * FROM public.needs_list_audit WHERE needs_list_id = (
    SELECT needs_list_id FROM public.needs_list WHERE needs_list_no = 'NL-TEST-001'
);

ROLLBACK;

-- Test phase change trigger
BEGIN;

UPDATE public.event
SET current_phase = 'SURGE',
    phase_changed_at = NOW(),
    phase_changed_by = 'TEST_USER'
WHERE event_id = 1;

-- Verify phase history entry
SELECT * FROM public.event_phase_history WHERE event_id = 1 ORDER BY changed_at DESC LIMIT 1;

ROLLBACK;
```

### Step 7: Restart Application Services

```bash
# Start Django API server
sudo systemctl start dmis_api

# Verify Django server is running
curl http://localhost:8000/api/v1/health/

# Start Nginx
sudo systemctl start nginx

# Check application logs
sudo journalctl -u dmis_api -f
```

### Step 8: Smoke Test from Application

```bash
# Test health endpoint
curl -X GET http://localhost:8000/api/v1/health/

# Test needs list preview (replace with actual values)
curl -X POST http://localhost:8000/api/v1/replenishment/needs-list/preview \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "event_id": 1,
    "warehouse_id": 1,
    "phase": "BASELINE"
  }'
```

## Post-Migration Validation

### 1. Check Table Counts
```sql
-- Should have records (existing data)
SELECT 'event' AS table_name, COUNT(*) AS record_count FROM public.event
UNION ALL
SELECT 'warehouse', COUNT(*) FROM public.warehouse
UNION ALL
SELECT 'item', COUNT(*) FROM public.item
UNION ALL
SELECT 'transfer', COUNT(*) FROM public.transfer
UNION ALL
-- Should be empty (new tables)
SELECT 'needs_list', COUNT(*) FROM public.needs_list
UNION ALL
SELECT 'procurement', COUNT(*) FROM public.procurement
UNION ALL
SELECT 'supplier', COUNT(*) FROM public.supplier
UNION ALL
SELECT 'lead_time_config', COUNT(*) FROM public.lead_time_config;
```

### 2. Verify Constraints Are Enforced
```sql
-- Test invalid phase (should fail)
BEGIN;
INSERT INTO public.needs_list (needs_list_no, event_id, warehouse_id, event_phase, calculation_dtime, demand_window_hours, planning_window_hours, safety_factor, create_by_id, update_by_id)
VALUES ('TEST', 1, 1, 'INVALID', NOW(), 10, 10, 1.0, 'TEST', 'TEST');
ROLLBACK;
-- Expected: ERROR:  new row for relation "needs_list" violates check constraint "c_needs_list_phase"
```

### 3. Performance Check
```sql
-- Check index usage on new tables
SELECT schemaname, tablename, indexname, idx_scan
FROM pg_stat_user_indexes
WHERE schemaname = 'public'
  AND tablename LIKE 'needs_list%'
ORDER BY tablename, indexname;
```

## Rollback Plan

If migration fails or issues are discovered:

### Option 1: Restore from Backup (Full)
```bash
# Stop application
sudo systemctl stop dmis_api

# Drop and recreate database
psql -h localhost -U postgres -c "DROP DATABASE dmis_db;"
psql -h localhost -U postgres -c "CREATE DATABASE dmis_db OWNER dmis_user;"

# Restore from backup
pg_restore -h localhost -U dmis_user -d dmis_db dmis_backup_pre_ep02_*.backup

# Restart application
sudo systemctl start dmis_api
```

### Option 2: Selective Rollback (Removes Only EP-02 Changes)
```sql
-- Drop new tables (cascades to foreign keys)
DROP TABLE IF EXISTS public.needs_list_audit CASCADE;
DROP TABLE IF EXISTS public.needs_list_item CASCADE;
DROP TABLE IF EXISTS public.needs_list CASCADE;
DROP TABLE IF EXISTS public.procurement_item CASCADE;
DROP TABLE IF EXISTS public.procurement CASCADE;
DROP TABLE IF EXISTS public.supplier CASCADE;
DROP TABLE IF EXISTS public.lead_time_config CASCADE;
DROP TABLE IF EXISTS public.event_phase_config CASCADE;
DROP TABLE IF EXISTS public.event_phase_history CASCADE;
DROP TABLE IF EXISTS public.burn_rate_snapshot CASCADE;
DROP TABLE IF EXISTS public.warehouse_sync_log CASCADE;

-- Drop views
DROP VIEW IF EXISTS public.v_inbound_stock;
DROP VIEW IF EXISTS public.v_stock_status;

-- Drop triggers
DROP TRIGGER IF EXISTS trg_warehouse_sync_status ON public.warehouse;
DROP TRIGGER IF EXISTS trg_event_phase_change ON public.event;

-- Drop functions
DROP FUNCTION IF EXISTS public.update_warehouse_sync_status();
DROP FUNCTION IF EXISTS public.log_event_phase_change();

-- Remove new columns from existing tables
ALTER TABLE public.event
DROP COLUMN IF EXISTS current_phase,
DROP COLUMN IF EXISTS phase_changed_at,
DROP COLUMN IF EXISTS phase_changed_by;

ALTER TABLE public.warehouse
DROP COLUMN IF EXISTS min_stock_threshold,
DROP COLUMN IF EXISTS last_sync_dtime,
DROP COLUMN IF EXISTS sync_status;

ALTER TABLE public.item
DROP COLUMN IF EXISTS baseline_burn_rate,
DROP COLUMN IF EXISTS min_stock_threshold,
DROP COLUMN IF EXISTS criticality_level;

ALTER TABLE public.transfer
DROP COLUMN IF EXISTS dispatched_at,
DROP COLUMN IF EXISTS dispatched_by,
DROP COLUMN IF EXISTS expected_arrival,
DROP COLUMN IF EXISTS received_at,
DROP COLUMN IF EXISTS received_by,
DROP COLUMN IF EXISTS needs_list_id;
```

## Common Issues and Solutions

### Issue 1: Constraint Violation on Existing Data
**Symptom:** `ERROR: check constraint violation`

**Solution:**
```sql
-- Temporarily disable constraint, update data, re-enable
ALTER TABLE public.event DROP CONSTRAINT c_event_phase;
UPDATE public.event SET current_phase = 'BASELINE' WHERE current_phase NOT IN ('SURGE', 'STABILIZED', 'BASELINE');
ALTER TABLE public.event ADD CONSTRAINT c_event_phase CHECK (current_phase IN ('SURGE', 'STABILIZED', 'BASELINE'));
```

### Issue 2: Foreign Key Violation
**Symptom:** `ERROR: foreign key constraint failed`

**Solution:**
```sql
-- Check for orphaned records
SELECT transfer_id, needs_list_id
FROM public.transfer
WHERE needs_list_id IS NOT NULL
  AND needs_list_id NOT IN (SELECT needs_list_id FROM public.needs_list);

-- Set orphaned references to NULL
UPDATE public.transfer SET needs_list_id = NULL WHERE needs_list_id NOT IN (SELECT needs_list_id FROM public.needs_list);
```

### Issue 3: Trigger Not Firing
**Symptom:** Phase changes not logged in `event_phase_history`

**Solution:**
```sql
-- Verify trigger exists
SELECT * FROM information_schema.triggers WHERE trigger_name = 'trg_event_phase_change';

-- Recreate trigger if missing
DROP TRIGGER IF EXISTS trg_event_phase_change ON public.event;
CREATE TRIGGER trg_event_phase_change
AFTER UPDATE OF current_phase ON public.event
FOR EACH ROW EXECUTE FUNCTION public.log_event_phase_change();
```

## Migration Timeline

| Step | Duration | Responsibility |
|------|----------|----------------|
| 1. Pre-migration backup | 10-15 min | DBA |
| 2. Stop services | 1 min | DevOps |
| 3. Apply schema | 5-10 min | DBA |
| 4. Verification tests | 5 min | DBA |
| 5. Restart services | 2 min | DevOps |
| 6. Smoke tests | 5 min | QA/Dev Team |
| **Total Downtime** | **15-30 min** | |

## Support Contacts

- **Database Administrator:** [Contact Info]
- **Backend Developer:** [Contact Info]
- **DevOps Engineer:** [Contact Info]

## References

- Schema File: `/backend/EP02_SUPPLY_REPLENISHMENT_SCHEMA.sql`
- Requirements Doc: `/docs/attached_assets/EP02_SUPPLY_REPLENISHMENT_REQUIREMENTS.md`
- CLAUDE.md: `/CLAUDE.md`

---

**Migration Checklist:**

- [ ] Backup completed
- [ ] Services stopped
- [ ] Schema applied
- [ ] Verification queries run
- [ ] Triggers tested
- [ ] Permissions granted
- [ ] Services restarted
- [ ] Smoke tests passed
- [ ] Team notified

**Sign-off:**

- DBA: __________________ Date: __________
- Lead Developer: __________________ Date: __________
- DevOps: __________________ Date: __________
