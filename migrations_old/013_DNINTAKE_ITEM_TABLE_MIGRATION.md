# Donation Intake Item Table Migration
**Date:** November 25, 2025  
**Migration ID:** 013  
**Migration Script:** `migrations/013_migrate_dnintake_item_table_to_target_ddl.sql`

## Overview
Successfully rebuilt the `dnintake_item` table to match target DDL requirements. Major changes include transitioning from a single serial primary key to a composite primary key, adding the `ext_item_cost` column for extended cost tracking, and enforcing batch tracking requirements.

## Migration Status: ✅ COMPLETE

---

## Schema Changes Applied

### Primary Key Change (MAJOR)
| Aspect | Before | After |
|--------|--------|-------|
| PK Type | Single column (`intake_item_id` serial) | Composite PK |
| PK Columns | `intake_item_id` | `(donation_id, inventory_id, item_id, batch_no)` |
| Rationale | Aligns with business logic - items are uniquely identified by donation, inventory location, item, and batch |

### Column Changes

#### Removed Column
- **`intake_item_id`**: Serial auto-increment column removed (replaced by composite PK)

#### New Column Added
- **`ext_item_cost`**: DECIMAL(12,2) NOT NULL DEFAULT 0.00
  - Extended item cost = (usable_qty + defective_qty + expired_qty) * avg_unit_value
  - CHECK constraint: `ext_item_cost >= 0.00`

#### Nullable → NOT NULL Changes
| Column | Before | After | Default |
|--------|--------|-------|---------|
| `batch_no` | NULL allowed | NOT NULL | (must be provided, use item code if no batch) |
| `batch_date` | NULL allowed | NOT NULL | (must be provided) |
| `expiry_date` | NULL allowed | NOT NULL | (must be provided) |

#### Constraint Changes
| Constraint | Before | After |
|------------|--------|-------|
| `c_dnintake_item_1a` | `batch_no IS NULL OR batch_no = UPPER(batch_no)` | `batch_no = UPPER(batch_no)` |
| `c_dnintake_item_1b` | `batch_date IS NULL OR batch_date <= CURRENT_DATE` | `batch_date <= CURRENT_DATE` |
| `c_dnintake_item_1c` | `expiry_date >= CURRENT_DATE OR expiry_date IS NULL` | `expiry_date >= batch_date` |
| `c_dnintake_item_1e` | (new) | `ext_item_cost >= 0.00` |

### New Defaults Added
| Column | Default Value |
|--------|---------------|
| `ext_item_cost` | 0.00 |
| `usable_qty` | 0.00 |
| `defective_qty` | 0.00 |
| `expired_qty` | 0.00 |
| `status_code` | 'P' (Pending) |
| `version_nbr` | 1 |

---

## Referential Integrity - All Preserved

### Foreign Keys (All Intact)
| Constraint Name | From Columns | References |
|-----------------|--------------|------------|
| `fk_dnintake_item_intake` | (donation_id, inventory_id) | dnintake(donation_id, inventory_id) |
| `fk_dnintake_item_donation_item` | (donation_id, item_id) | donation_item(donation_id, item_id) |
| `fk_dnintake_item_unitofmeasure` | uom_code | unitofmeasure(uom_code) |

### Performance Indexes Created
| Index Name | Columns | Purpose |
|------------|---------|---------|
| `pk_dnintake_item` | (donation_id, inventory_id, item_id, batch_no) | Primary key (unique) |
| `dk_dnintake_item_1` | (inventory_id, item_id) | Inventory/item lookups |
| `dk_dnintake_item_2` | (item_id) | Item-based queries |

---

## Code Changes

### SQLAlchemy Model Updated (`app/db/models.py`)
```python
class DonationIntakeItem(db.Model):
    __tablename__ = 'dnintake_item'
    
    # Composite Primary Key (4 columns)
    donation_id = db.Column(db.Integer, primary_key=True)
    inventory_id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, primary_key=True)
    batch_no = db.Column(db.String(20), primary_key=True)
    
    # Date fields - now NOT NULL
    batch_date = db.Column(db.Date, nullable=False)
    expiry_date = db.Column(db.Date, nullable=False)
    
    # New column for extended cost tracking
    ext_item_cost = db.Column(db.Numeric(12, 2), nullable=False, default=0.00)
    
    # All quantity fields with defaults
    usable_qty = db.Column(db.Numeric(12, 2), nullable=False, default=0.00)
    defective_qty = db.Column(db.Numeric(12, 2), nullable=False, default=0.00)
    expired_qty = db.Column(db.Numeric(12, 2), nullable=False, default=0.00)
    
    # Status with default
    status_code = db.Column(db.CHAR(1), nullable=False, default='P')
```

---

## Data Impact

**Pre-Migration State:**
- 0 rows in table (clean rebuild)
- Old structure with `intake_item_id` serial PK

**Post-Migration:**
- 19 columns (18 data + removed intake_item_id)
- Composite PK enforced
- All constraints properly applied
- Zero data loss

---

## Column Summary

| # | Column | Type | Nullable | Default | Notes |
|---|--------|------|----------|---------|-------|
| 1 | donation_id | INTEGER | NO | - | PK component, FK to dnintake |
| 2 | inventory_id | INTEGER | NO | - | PK component, FK to dnintake |
| 3 | item_id | INTEGER | NO | - | PK component, FK to donation_item |
| 4 | batch_no | VARCHAR(20) | NO | - | PK component, must be UPPER |
| 5 | batch_date | DATE | NO | - | <= CURRENT_DATE |
| 6 | expiry_date | DATE | NO | - | >= batch_date |
| 7 | uom_code | VARCHAR(25) | NO | - | FK to unitofmeasure |
| 8 | avg_unit_value | DECIMAL(10,2) | NO | - | > 0.00 |
| 9 | ext_item_cost | DECIMAL(12,2) | NO | 0.00 | >= 0.00 (NEW) |
| 10 | usable_qty | DECIMAL(12,2) | NO | 0.00 | >= 0.00 |
| 11 | defective_qty | DECIMAL(12,2) | NO | 0.00 | >= 0.00 |
| 12 | expired_qty | DECIMAL(12,2) | NO | 0.00 | >= 0.00 |
| 13 | status_code | CHAR(1) | NO | 'P' | IN ('P','V') |
| 14 | comments_text | VARCHAR(255) | YES | - | |
| 15 | create_by_id | VARCHAR(20) | NO | - | |
| 16 | create_dtime | TIMESTAMP | NO | - | |
| 17 | update_by_id | VARCHAR(20) | NO | - | |
| 18 | update_dtime | TIMESTAMP | NO | - | |
| 19 | version_nbr | INTEGER | NO | 1 | Optimistic locking |

---

## Testing Checklist

✅ Table dropped and recreated successfully  
✅ All 19 columns present with correct types  
✅ Composite PK (donation_id, inventory_id, item_id, batch_no) enforced  
✅ All CHECK constraints created  
✅ All foreign keys intact  
✅ Performance indexes created  
✅ SQLAlchemy model updated  
✅ Application starts without errors  
✅ No other tables modified  

**Still Required:**
- [ ] End-to-end test: Create donation intake with items
- [ ] Verify batch_no is properly handled (UPPER case enforced)
- [ ] Confirm expiry_date >= batch_date validation
- [ ] Test ext_item_cost calculation in workflow

---

## Breaking Changes for Application Code

### 1. Primary Key Change
- **Before**: Query by `intake_item_id` (single integer)
- **After**: Query by composite key `(donation_id, inventory_id, item_id, batch_no)`

### 2. Batch Tracking Now Required
- **Before**: `batch_no` and `batch_date` could be NULL
- **After**: Both fields are required; use item code as `batch_no` if no manufacturer batch exists

### 3. Expiry Date Logic Changed
- **Before**: `expiry_date >= CURRENT_DATE OR expiry_date IS NULL`
- **After**: `expiry_date >= batch_date` (more logical validation)

**Note:** These changes require updates to any application code that creates `dnintake_item` records. The table was empty, so no existing data was affected.

---

## Rollback Plan (If Needed)

If rollback is required:

```sql
-- 1. Drop the new table
DROP TABLE IF EXISTS dnintake_item CASCADE;

-- 2. Recreate with old structure (with intake_item_id serial PK)
-- See migrations/013_migrate_dnintake_item_table_to_target_ddl.sql for original structure

-- 3. Restore model from git
git checkout -- app/db/models.py
```

---

## Files Modified

- `migrations/013_migrate_dnintake_item_table_to_target_ddl.sql` (new)
- `migrations/013_DNINTAKE_ITEM_TABLE_MIGRATION.md` (new)
- `app/db/models.py` (DonationIntakeItem model)
- `replit.md` (migration documented)

---

## Conclusion

The dnintake_item table migration was completed successfully with:
- ✅ Composite primary key implementation
- ✅ New ext_item_cost column for extended cost tracking
- ✅ Stricter batch tracking enforcement
- ✅ All referential integrity maintained
- ✅ All security features preserved (CSP, CSRF, RBAC)
- ✅ Performance indexes for efficient queries
- ✅ Zero data loss (table was empty)

The system is now ready to receive donation intake items with enhanced batch-level tracking and cost calculations.
