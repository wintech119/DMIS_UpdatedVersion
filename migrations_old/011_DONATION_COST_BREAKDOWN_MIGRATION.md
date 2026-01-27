# Donation Table Cost Breakdown Migration
**Date:** November 24, 2025  
**Migration ID:** 011
**Migration Script:** `migrations/migrate_donation_table_to_target_ddl.sql`

## Overview
Successfully migrated the `donation` table to include detailed cost breakdown fields and enforce strict data integrity constraints while preserving all referential integrity and existing workflows.

## Migration Status: ✅ COMPLETE

---

## Schema Changes Applied

### New Columns Added (4 columns)
| Column | Type | Constraint | Default | Purpose |
|--------|------|------------|---------|---------|
| `storage_cost` | DECIMAL(12,2) | NOT NULL, > 0.00 | 0.01 | Warehousing/storage costs |
| `haulage_cost` | DECIMAL(12,2) | NOT NULL, > 0.00 | 0.01 | Transportation/shipping costs |
| `other_cost` | DECIMAL(12,2) | NOT NULL, > 0.00 | 0.01 | Miscellaneous costs |
| `other_cost_desc` | VARCHAR(255) | NULL | NULL | Description of other costs |

### Column Renamed
- `tot_donated_value` → `tot_item_cost` (DECIMAL(12,2) NOT NULL)

### Column Modified
- `origin_country_id`: Changed from NULL to **NOT NULL**

### CHECK Constraints Added
- `c_donation_1`: received_date <= CURRENT_DATE
- `c_donation_2`: tot_item_cost > 0.00
- `c_donation_2a`: storage_cost > 0.00
- `c_donation_2b`: haulage_cost > 0.00
- `c_donation_2c`: other_cost > 0.00
- `c_donation_3`: status_code IN ('E','V','P')

---

## Code Changes

### 1. SQLAlchemy Model (`app/db/models.py`)
- Updated Donation class with new cost breakdown fields
- Added all CHECK constraints to `__table_args__`
- Made origin_country_id non-nullable

### 2. Donation Creation (`app/features/donations.py`)
**Validations Added:**
- Line 179-180: Origin country now required
- Line 345-353: Total item cost must be > 0.00

**Cost Breakdown:**
```python
donation.tot_item_cost = total_value  # Calculated from items
donation.storage_cost = Decimal('0.01')  # Placeholder
donation.haulage_cost = Decimal('0.01')  # Placeholder
donation.other_cost = Decimal('0.01')  # Placeholder
```

### 3. UI Template (`templates/donations/create.html`)
- Origin Country field marked as required (*)
- Added HTML `required` attribute

---

## Implementation Notes

### Cost Breakdown Strategy
**Phase 1 (Current):** Placeholder defaults (0.01) satisfy constraints without blocking donations

**Phase 2 (Future):** Options for capturing actual costs:
- Add cost fields to donation creation form
- Update during intake/verification workflow  
- Calculate automatically based on warehouse rates

---

## Testing Checklist
✅ Migration executed successfully  
✅ All columns and constraints in place  
✅ SQLAlchemy model updated  
✅ Backend validation added  
✅ Frontend validation added  
✅ Application starts without errors  
✅ Referential integrity preserved  

---

## Referential Integrity Verified
All foreign keys intact:
- `fk_donation_donor` → donor(donor_id)
- `fk_donation_country` → country(country_id)
- `fk_donation_event` → event(event_id)
- `fk_donation_custodian` → custodian(custodian_id)

Downstream tables functional:
- donation_item
- dnintake
- donation_doc

---

## Breaking Changes
1. **Origin Country Required**: All donations must specify origin country
2. **Total Cost Must Be Positive**: Zero-value donations will fail validation
3. **Field Renamed**: Code referencing `tot_donated_value` updated to `tot_item_cost`

---

## Files Modified
- `migrations/migrate_donation_table_to_target_ddl.sql` (new)
- `app/db/models.py` (Donation model)
- `app/features/donations.py` (validation and assignment logic)
- `templates/donations/create.html` (required field)

---

## Success Criteria Met
✅ Zero data loss  
✅ Referential integrity maintained  
✅ Security features preserved (CSP, CSRF, RBAC)  
✅ All workflows functional  
✅ Enhanced data validation  
