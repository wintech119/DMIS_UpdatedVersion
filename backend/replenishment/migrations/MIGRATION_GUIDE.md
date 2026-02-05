# Supply Replenishment Module - Database Migration Guide

## Overview

The Supply Replenishment Module (EP-02) requires new database tables and alterations to existing tables. This guide will help you apply the complete database schema.

## What Will Be Changed

### Existing Tables Altered
1. **event** - Adds: `current_phase`, `phase_changed_at`, `phase_changed_by`
2. **warehouse** - Adds: `min_stock_threshold`, `last_sync_dtime`, `sync_status`
3. **item** - Adds: `baseline_burn_rate`, `min_stock_threshold`, `criticality_level`
4. **transfer** - Adds: `dispatched_at`, `dispatched_by`, `expected_arrival`, `received_at`, `received_by`, `needs_list_id`

### New Tables Created
1. **event_phase_config** - Phase-specific parameters per event
2. **event_phase_history** - Audit trail for phase transitions
3. **needs_list** - Main needs list header
4. **needs_list_item** - Individual item lines with calculations
5. **needs_list_audit** - Immutable audit trail
6. **burn_rate_snapshot** - Historical burn rate calculations
7. **warehouse_sync_log** - Data freshness tracking
8. **procurement** - Horizon C procurement orders
9. **procurement_item** - Procurement line items
10. **supplier** - Supplier/vendor master
11. **lead_time_config** - Configurable lead times

### Views & Triggers
- **v_stock_status** - Real-time stock status view
- **v_inbound_stock** - Confirmed inbound by source
- Triggers for auto-updating sync status and logging phase changes

## Migration Steps

### Option 1: Using pgAdmin4 (Recommended for GUI users)

1. **Open pgAdmin4** and connect to your DMIS database

2. **Create a backup first** (important!)
   - Right-click on your database
   - Select "Backup..."
   - Choose a location and name (e.g., `dmis_backup_before_replenishment.backup`)
   - Click "Backup"

3. **Open the Query Tool**
   - Right-click on your database
   - Select "Query Tool"

4. **Load the migration script**
   - Click File > Open
   - Navigate to: `backend\EP02_SUPPLY_REPLENISHMENT_SCHEMA.sql`
   - The file contents will appear in the editor

5. **Execute the migration**
   - Click the "Execute/Refresh" button (⚡ icon) or press F5
   - Wait for completion (may take 1-2 minutes)
   - Check the "Messages" tab at the bottom for any errors

6. **Verify the migration**
   - In the Object Explorer, refresh your database
   - Expand "Schemas" > "public" > "Tables"
   - Verify new tables exist (needs_list, procurement, supplier, etc.)
   - Right-click on "event" table > "Properties" > "Columns"
   - Verify `current_phase` column exists

### Option 2: Using psql Command Line

1. **Create a backup first**
   ```bash
   cd "C:\Program Files\PostgreSQL\18\bin"
   pg_dump -U your_username -d your_database_name -F c -f "C:\backup\dmis_backup_before_replenishment.backup"
   ```

2. **Run the migration**
   ```bash
   psql -U your_username -d your_database_name -f "C:\Users\user\Desktop\DMIS_UpgradedVersion\DMIS_UpdatedVersion\backend\EP02_SUPPLY_REPLENISHMENT_SCHEMA.sql"
   ```

3. **Check for errors** in the output. Successful migration should show:
   - "ALTER TABLE" for each alteration
   - "CREATE TABLE" for each new table
   - "CREATE INDEX" for indexes
   - No ERROR messages

### Option 3: Using Django Migrations (Future Enhancement)

Django migrations for these tables can be created later using:
```bash
python manage.py makemigrations replenishment
python manage.py migrate replenishment
```

However, since the models reference legacy tables not managed by Django, the SQL script approach is recommended.

## Post-Migration Tasks

### 1. Verify Schema

Run this query in pgAdmin4 or psql to verify the migration:

```sql
-- Check if event table has current_phase column
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'event'
  AND column_name = 'current_phase';

-- Check if new tables exist
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN (
    'needs_list', 'needs_list_item', 'needs_list_audit',
    'burn_rate_snapshot', 'warehouse_sync_log',
    'procurement', 'procurement_item', 'supplier',
    'lead_time_config', 'event_phase_config', 'event_phase_history'
  )
ORDER BY table_name;
```

You should see 1 row for `current_phase` and 11 rows for the new tables.

### 2. Update Existing Events

After migration, update any existing events to have a phase:

```sql
-- Set all existing events to STABILIZED phase (or appropriate phase)
UPDATE public.event
SET current_phase = 'STABILIZED',
    phase_changed_at = CURRENT_TIMESTAMP,
    phase_changed_by = 'MIGRATION'
WHERE current_phase IS NULL OR current_phase = 'BASELINE';
```

### 3. Configure Default Phase Settings

Insert phase configurations for your active event (replace EVENT_ID with your actual event ID):

```sql
-- Insert phase configs for active event
INSERT INTO public.event_phase_config (
    event_id, phase, demand_window_hours, planning_window_hours,
    safety_factor, create_by_id, update_by_id
)
VALUES
    (1, 'SURGE', 6, 72, 1.50, 'SYSTEM', 'SYSTEM'),
    (1, 'STABILIZED', 72, 168, 1.25, 'SYSTEM', 'SYSTEM'),
    (1, 'BASELINE', 720, 720, 1.10, 'SYSTEM', 'SYSTEM')
ON CONFLICT (event_id, phase) DO NOTHING;
```

### 4. Restart Backend Server

After migration, restart your Django development server to reload the database connections:

```bash
# Stop the server (Ctrl+C if running)
# Then restart:
python manage.py runserver
```

## Troubleshooting

### Error: "column already exists"

If you see errors about columns already existing, it's safe - the script uses `IF NOT EXISTS` for most operations.

### Error: "relation does not exist"

This likely means a referenced table (like `warehouse`, `item`, `event`) doesn't exist in your schema. Check that your base DMIS schema is properly installed.

### Error: "foreign key constraint fails"

This might happen if:
- The `country` table doesn't exist (supplier table references it)
- Solution: Either create a dummy country table or modify the supplier table FK to be nullable

### Dashboard still shows "No Active Events"

Check that you have:
1. An event in the `event` table with `status_code = 'ACTIVE'`
2. The `current_phase` column is populated (not NULL)
3. Restarted the Django backend server

Query to verify:
```sql
SELECT event_id, event_name, status_code, current_phase, declaration_date
FROM public.event
WHERE UPPER(status_code) = 'ACTIVE'
ORDER BY declaration_date DESC;
```

## Rollback (If Needed)

If something goes wrong, you can restore from the backup:

### Using pgAdmin4:
1. Right-click on your database
2. Select "Restore..."
3. Choose the backup file you created
4. Click "Restore"

### Using psql:
```bash
pg_restore -U your_username -d your_database_name "C:\backup\dmis_backup_before_replenishment.backup"
```

## Next Steps

After successful migration:
1. ✅ Backend will now be able to query event phases
2. ✅ Dashboard will load with active event and warehouses
3. ✅ Stock status calculations will work
4. 📝 You can start using the Needs List Wizard to generate replenishment recommendations

## Support

If you encounter issues not covered in this guide:
1. Check the Django logs: `backend/logs/` or console output
2. Check PostgreSQL logs: typically in `C:\Program Files\PostgreSQL\18\data\log\`
3. Review the error messages carefully - they often indicate exactly what's missing

## Files Involved

- **Schema SQL**: `backend/EP02_SUPPLY_REPLENISHMENT_SCHEMA.sql` (main migration)
- **Backend Code**: `backend/replenishment/services/data_access.py` (updated to use `current_phase`)
- **Django Models**: `backend/replenishment/models.py` (ORM definitions)
