# Item Table Migration Guide

This directory contains scripts to migrate the existing `item` table to match the authoritative schema definition.

## Overview

The migration updates the `item` table structure to include new columns, correct constraint naming, and ensure full compliance with the target schema while **preserving all existing data**.

## Key Changes

### New Columns Added
- `item_code` - VARCHAR(16), unique, uppercase, primary business identifier
- `units_size_vary_flag` - BOOLEAN, default FALSE
- `is_batched_flag` - BOOLEAN, default TRUE  
- `can_expire_flag` - BOOLEAN, default FALSE (replaces `expiration_apply_flag`)
- `issuance_order` - VARCHAR(20), default 'FIFO'

### Columns Removed
- `category_code` - Replaced by `category_id` foreign key
- `expiration_apply_flag` - Replaced by `can_expire_flag`

### Constraints Updated
- All constraint names standardized to match schema (c_item_*, uk_item_*, fk_item_*)
- `category_id` changed from nullable to NOT NULL
- Three unique constraints: item_code, item_name, sku_code

### Indexes Added
- `dk_item_2` on `category_id`
- `dk_item_3` on `sku_code`

## Migration Process

### Step 1: Pre-Migration Validation

Run the pre-migration check to verify data integrity:

```bash
psql -d your_database -f migrations/item_pre_migration_check.sql
```

**Review the output carefully:**
- Ensure all `category_id` values are populated (no NULLs)
- Verify no duplicate `item_name` or `sku_code` values exist
- Check that all `reorder_qty` values are > 0
- Review the proposed auto-generated `item_code` values

**Fix any issues before proceeding:**

```sql
-- Example: Populate NULL category_id values
UPDATE item SET category_id = 1 WHERE category_id IS NULL;

-- Example: Fix duplicate item names
UPDATE item SET item_name = item_name || '-' || item_id::text 
WHERE item_name IN (
    SELECT item_name FROM item GROUP BY item_name HAVING COUNT(*) > 1
);
```

### Step 2: **REQUIRED** - Populate Item Codes

**This step is MANDATORY.** The migration will fail if you skip this.

You must populate the `item_code` column with your business values before running the migration.

**Requirements:**
- Max length: 16 characters
- Must be UPPERCASE
- Must be UNIQUE across all items
- Cannot be NULL

**Example population strategies:**

```sql
-- Option 1: Use existing SKU code (if it meets requirements)
UPDATE item SET item_code = sku_code;

-- Option 2: Create codes from item name abbreviation + ID
UPDATE item 
SET item_code = UPPER(SUBSTRING(item_name, 1, 8) || '-' || item_id);

-- Option 3: Custom business logic (category prefix + sequence)
UPDATE item 
SET item_code = 'CAT' || category_id || '-' || LPAD(item_id::text, 6, '0');

-- Option 4: Manual entry for each item (for smaller datasets)
UPDATE item SET item_code = 'BLANKET-001' WHERE item_id = 1;
UPDATE item SET item_code = 'WATER-500ML' WHERE item_id = 2;
UPDATE item SET item_code = 'MRE-ADULT' WHERE item_id = 3;
-- ... etc
```

**Verify your item codes:**

```sql
-- Check all are populated
SELECT COUNT(*) as total, COUNT(item_code) as populated 
FROM item;

-- Check uniqueness (should return no rows)
SELECT item_code, COUNT(*) 
FROM item 
GROUP BY item_code 
HAVING COUNT(*) > 1;

-- Check uppercase (should return no rows)
SELECT item_code 
FROM item 
WHERE item_code != UPPER(item_code);

-- Check length (should return no rows)
SELECT item_code, LENGTH(item_code) 
FROM item 
WHERE LENGTH(item_code) > 16;
```

### Step 3: Backup Your Database

**CRITICAL: Always backup before migration!**

```bash
pg_dump -d your_database -f item_table_backup_$(date +%Y%m%d_%H%M%S).sql
```

### Step 4: Run the Migration

Execute the migration script:

```bash
psql -d your_database -f migrations/item_table_migration.sql
```

The script uses a transaction, so if any step fails, all changes will be rolled back automatically.

**Expected output:**
- `BEGIN`
- Series of `ALTER TABLE` commands
- `COMMIT`
- Verification query results

### Step 5: Post-Migration Verification

Run the verification script to confirm success:

```bash
psql -d your_database -f migrations/item_post_migration_verify.sql
```

**All tests should show:**
- ✅ All required columns exist with correct types
- ✅ All constraints exist (pk_item, uk_item_1/2/3, fk_item_itemcatg, etc.)
- ✅ All indexes exist (dk_item_1/2/3)
- ✅ All uppercase checks pass
- ✅ Data integrity maintained (same row count, all unique values preserved)

## Rollback Plan

If you need to rollback:

```bash
# Restore from backup
psql -d your_database -f item_table_backup_YYYYMMDD_HHMMSS.sql
```

Or manually reverse the changes:

```sql
BEGIN;

-- Restore dropped columns
ALTER TABLE item ADD COLUMN category_code varchar(30);
ALTER TABLE item ADD COLUMN expiration_apply_flag boolean;

-- Migrate data back
UPDATE item SET expiration_apply_flag = can_expire_flag;

-- Drop new columns
ALTER TABLE item DROP COLUMN item_code;
ALTER TABLE item DROP COLUMN units_size_vary_flag;
ALTER TABLE item DROP COLUMN is_batched_flag;
ALTER TABLE item DROP COLUMN can_expire_flag;
ALTER TABLE item DROP COLUMN issuance_order;

-- Restore old constraint names (reverse the renames)
-- ... (add as needed)

COMMIT;
```

## Files in This Directory

1. **item_pre_migration_check.sql** - Pre-migration validation queries
2. **item_table_migration.sql** - Main migration script
3. **item_post_migration_verify.sql** - Post-migration verification tests
4. **ITEM_MIGRATION_README.md** - This file

## Troubleshooting

### Issue: "category_id has NULL values"
**Solution:** Populate all NULL category_id values before migration:
```sql
UPDATE item SET category_id = <valid_category_id> WHERE category_id IS NULL;
```

### Issue: "duplicate key value violates unique constraint"
**Solution:** Fix duplicate values before migration:
```sql
-- Find duplicates
SELECT item_name, COUNT(*) FROM item GROUP BY item_name HAVING COUNT(*) > 1;

-- Fix them (example)
UPDATE item SET item_name = item_name || '-' || item_id WHERE ...;
```

### Issue: Migration fails mid-way
**Solution:** The transaction will auto-rollback. Fix the issue and re-run.

### Issue: Want different item_code values
**Solution:** Populate item_code column yourself before running migration:
```sql
UPDATE item SET item_code = <your_logic>;
```

## Success Criteria

After migration, verify:
- [ ] Same number of rows in item table
- [ ] All item_code values are unique and uppercase
- [ ] All item_name values are unique and uppercase  
- [ ] All sku_code values are unique and uppercase
- [ ] All category_id values are populated (NOT NULL)
- [ ] All new boolean columns have appropriate defaults
- [ ] All constraints and indexes exist as expected
- [ ] No application errors when querying the table

## Support

If you encounter issues:
1. Check the verification script output
2. Review the constraint/index listings
3. Verify sample data looks correct
4. Check application logs for any errors

## Notes

- The migration preserves ALL existing data
- Constraint renames do not affect functionality, only naming convention
- New columns get default values automatically
- The script is idempotent for most operations (safe to re-run after fixing issues)
