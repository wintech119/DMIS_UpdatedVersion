# Donation Item Table Migration Summary

**Date:** November 17, 2025  
**Migration File:** `migrations/005_drop_replace_donation_item.sql`  
**Status:** ✅ COMPLETED SUCCESSFULLY

## Overview

Successfully dropped and recreated the **donation_item** table with standardized constraint names and updated data types while maintaining full referential integrity with dependent tables.

---

## Migration Strategy

This migration used a **DROP and RECREATE** approach rather than ALTER because:
1. Table was empty (0 records) - no data loss risk
2. Multiple constraint names needed standardization
3. Data type changes required (numeric(15,4) → decimal(12,2))
4. Cleaner and safer than multiple ALTER statements

---

## Changes Made

### Structure Changes

#### Data Type Updated:
- **Before:** `item_qty` = numeric(15,4)
- **After:** `item_qty` = decimal(12,2)
- **Reason:** Align with specification for monetary/quantity precision

#### Constraint Names Standardized:

**Primary Key:**
- Before: `donation_item_pkey`
- After: `pk_donation_item`

**Foreign Keys:**
- Before: `donation_item_donation_id_fkey` → After: `fk_donation_item_donation`
- Before: `donation_item_item_id_fkey` → After: `fk_donation_item_item`
- Before: `donation_item_uom_code_fkey` → After: `fk_donation_item_unitofmeasure`

**Check Constraints:**
- Before: `donation_item_item_qty_check` → After: `c_donation_item_1` (item_qty >= 0.00)
- Before: `donation_item_status_code_check` → After: `c_donation_item_2` (status_code IN ('P','V'))

### Table Structure (Final):

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| donation_id | INTEGER | NO | Donation (FK) |
| item_id | INTEGER | NO | Item (FK) |
| item_qty | DECIMAL(12,2) | NO | Quantity received (>= 0.00) |
| uom_code | VARCHAR(25) | NO | Unit of measure (FK) |
| location_name | TEXT | NO | Physical location |
| status_code | CHAR(1) | NO | P=Pending, V=Verified |
| comments_text | TEXT | YES | Optional comments |
| create_by_id | VARCHAR(20) | NO | Created by |
| create_dtime | TIMESTAMP | NO | Creation time |
| verify_by_id | VARCHAR(20) | NO | Verified by |
| verify_dtime | TIMESTAMP | NO | Verification time |
| version_nbr | INTEGER | NO | Optimistic locking |

---

## Referential Integrity Management

### Dependent Table: dnintake_item

**Before Migration:**
- `dnintake_item` had FK: `fk_dnintake_item_donation_item` referencing `donation_item(donation_id, item_id)`

**Migration Steps:**
1. ✅ Dropped FK from dnintake_item **before** dropping donation_item
2. ✅ Dropped and recreated donation_item table
3. ✅ Re-established FK from dnintake_item **after** recreating donation_item

**After Migration:**
- ✅ FK restored: `fk_dnintake_item_donation_item` → `donation_item(donation_id, item_id)`

### Verification Results ✅

**Referenced Tables (FKs from donation_item):**
- ✅ donation_item.donation_id → donation.donation_id (fk_donation_item_donation)
- ✅ donation_item.item_id → item.item_id (fk_donation_item_item)
- ✅ donation_item.uom_code → unitofmeasure.uom_code (fk_donation_item_unitofmeasure)

**Referencing Tables (FKs to donation_item):**
- ✅ dnintake_item(donation_id, item_id) → donation_item(donation_id, item_id)

**Data Integrity:**
- ✅ 0 records in donation_item (as expected - table was empty before migration)
- ✅ 0 orphaned records in dnintake_item
- ✅ All foreign key constraints functioning correctly

---

## Database Constraints (Final State)

| Constraint Name | Type | Definition |
|----------------|------|------------|
| pk_donation_item | PRIMARY KEY | (donation_id, item_id) |
| fk_donation_item_donation | FOREIGN KEY | donation_id → donation |
| fk_donation_item_item | FOREIGN KEY | item_id → item |
| fk_donation_item_unitofmeasure | FOREIGN KEY | uom_code → unitofmeasure |
| c_donation_item_1 | CHECK | item_qty >= 0.00 |
| c_donation_item_2 | CHECK | status_code IN ('P', 'V') |

---

## Application Impact

### Code Changes Required:
- **SQLAlchemy Model:** No model currently exists for donation_item in the codebase
  - If a model is added in the future, it should reflect the new structure
- **Business Logic:** Any code inserting into donation_item must use decimal(12,2) for item_qty

### UI Impact:
- No direct UI impact (donation_item is a detail/line item table)
- Any donation item entry forms must validate:
  - item_qty as decimal(12,2) format
  - status_code as 'P' or 'V' only
  - item_qty must be non-negative

---

## Migration Safety Features

1. **Pre-Drop Verification:**
   - Confirmed table was empty (0 records)
   - Identified dependent FK from dnintake_item

2. **FK Management:**
   - Explicitly dropped dependent FK before table drop
   - Explicitly recreated FK after table creation
   - Prevented CASCADE issues

3. **Transaction Wrapping:**
   - All changes in BEGIN/COMMIT block
   - Automatic rollback on any error

4. **Post-Migration Verification:**
   - Verified all FK relationships intact
   - Checked for orphaned records
   - Confirmed constraint definitions

---

## Rollback Information

If rollback is needed:

```sql
BEGIN;

-- Drop current FK from dnintake_item
ALTER TABLE dnintake_item 
DROP CONSTRAINT IF EXISTS fk_dnintake_item_donation_item;

-- Drop current table
DROP TABLE IF EXISTS donation_item CASCADE;

-- Recreate with old structure (numeric(15,4))
CREATE TABLE donation_item
(
    donation_id INTEGER NOT NULL
        CONSTRAINT donation_item_donation_id_fkey REFERENCES donation(donation_id),
    item_id INTEGER NOT NULL
        CONSTRAINT donation_item_item_id_fkey REFERENCES item(item_id),
    item_qty NUMERIC(15,4) NOT NULL
        CONSTRAINT donation_item_item_qty_check CHECK (item_qty >= 0.00),
    uom_code VARCHAR(25) NOT NULL
        CONSTRAINT donation_item_uom_code_fkey REFERENCES unitofmeasure(uom_code),
    location_name TEXT NOT NULL,
    status_code CHAR(1) NOT NULL
        CONSTRAINT donation_item_status_code_check CHECK (status_code IN ('P','V')),
    comments_text TEXT,
    create_by_id VARCHAR(20) NOT NULL,
    create_dtime TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    verify_by_id VARCHAR(20) NOT NULL,
    verify_dtime TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    version_nbr INTEGER NOT NULL,
    CONSTRAINT donation_item_pkey PRIMARY KEY(donation_id, item_id)
);

-- Restore FK from dnintake_item
ALTER TABLE dnintake_item 
ADD CONSTRAINT fk_dnintake_item_donation_item 
FOREIGN KEY (donation_id, item_id) 
REFERENCES donation_item(donation_id, item_id);

COMMIT;
```

**Note:** Rollback will lose any data inserted after the migration.

---

## Testing Recommendations

Since the table was empty before and after migration, testing should focus on:

1. **Insert New Record:**
   ```sql
   INSERT INTO donation_item (
       donation_id, item_id, item_qty, uom_code, 
       location_name, status_code,
       create_by_id, create_dtime, 
       verify_by_id, verify_dtime, version_nbr
   ) VALUES (
       1, 1, 10.50, 'UNITS', 
       'Warehouse A', 'P',
       'TEST_USER', NOW(), 
       'TEST_USER', NOW(), 1
   );
   ```

2. **Verify Constraints:**
   - Test negative quantity (should fail)
   - Test invalid status code (should fail)
   - Test invalid donation_id (should fail - FK constraint)
   - Test invalid item_id (should fail - FK constraint)
   - Test invalid uom_code (should fail - FK constraint)

3. **Verify Decimal Precision:**
   - Insert value with 2 decimal places: 10.25 (should work)
   - Insert value with 3 decimal places: 10.255 (should round to 10.26)

4. **Verify dnintake_item FK:**
   - Ensure dnintake_item can still reference donation_item records

---

## Files Modified

### Database:
- `migrations/005_drop_replace_donation_item.sql` (new)

### Documentation:
- `DRIMS_DATABASE_SCHEMA.md` (updated)
- `migrations/DONATION_ITEM_MIGRATION_SUMMARY.md` (this file)

### Code:
- No SQLAlchemy model exists for this table
- Future model should match new structure

---

## Success Criteria

✅ Old donation_item table successfully dropped  
✅ New donation_item table created with correct structure  
✅ All constraint names follow DRIMS naming standards  
✅ Data type updated: numeric(15,4) → decimal(12,2)  
✅ Primary key constraint properly defined  
✅ All foreign key constraints intact (3 outbound FKs)  
✅ Dependent FK from dnintake_item successfully restored  
✅ Check constraints enforce business rules  
✅ Documentation updated with new structure  
✅ Zero data loss (table was empty)  

---

## Related Migrations

This migration follows the pattern established in:
- `migrations/003_alter_donor_table.sql` - Donor table alterations
- `migrations/004_alter_donation_table.sql` - Donation constraint renaming

All three migrations demonstrate DRIMS standards:
1. ✅ Explicit, meaningful constraint names
2. ✅ Referential integrity preservation
3. ✅ Comprehensive documentation
4. ✅ Transaction-wrapped with verification
5. ✅ Clear rollback procedures

---

## Notes

- **No data loss:** Table was empty before migration (0 records)
- **No application downtime:** Drop/recreate was instantaneous
- **Future-proof:** New structure matches current specification exactly
- **Backward compatibility:** Precision reduced (15,4 → 12,2) is acceptable as table was empty
- **FK management:** Explicitly handled dependent FK to prevent CASCADE issues
- The donation_item table is a junction/detail table linking donations to items with quantity and location information
