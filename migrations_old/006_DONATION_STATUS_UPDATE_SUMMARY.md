# Migration 006: Donation Status Constraint Update

## Overview
Updated the `donation` table's status code check constraint to support a new 'P' (Processed) status, expanding the donation workflow from 2 to 3 states.

## Migration Date
November 18, 2025

## Changes Applied

### Status Code Constraint Update
- **Previous**: `status_code IN ('E', 'V')`
- **Updated**: `status_code IN ('E', 'V', 'P')`

### Status Code Meanings
- **E** = Entered (initial entry of donation record)
- **V** = Verified (donation verified by custodian)
- **P** = Processed (donation intake completed, items added to inventory)

## Technical Details

### Constraint Modified
```sql
ALTER TABLE donation DROP CONSTRAINT IF EXISTS c_donation_2;
ALTER TABLE donation ADD CONSTRAINT c_donation_2 
    CHECK (status_code IN ('E', 'V', 'P'));
```

### Referential Integrity
All foreign key constraints maintained:
- `fk_donation_donor` → donor(donor_id)
- `fk_donation_event` → event(event_id)
- `fk_donation_custodian` → custodian(custodian_id)

### Data Impact
- **Zero data loss**: Constraint update is non-destructive
- **Backward compatible**: Existing 'E' and 'V' statuses remain valid
- **No data migration required**: All existing donation records unchanged

## Validation Results

### Table Structure
✅ All 13 columns present with correct data types
✅ Primary key constraint (pk_donation) intact
✅ Check constraints (c_donation_1, c_donation_2) verified
✅ All foreign key constraints verified

### Referential Integrity
✅ donor_id references: VALID
✅ event_id references: VALID  
✅ custodian_id references: VALID

### Referenced By
✅ dnintake.donation_id → donation(donation_id)
✅ donation_item.donation_id → donation(donation_id)

## SQLAlchemy Model Updates

### Model Documentation
Added comprehensive docstring with status code explanations:
```python
class Donation(db.Model):
    """Donation
    
    Tracks donations received from donors for specific events.
    
    Status Codes:
        E = Entered (initial entry)
        V = Verified (verified by custodian)
        P = Processed (donation intake completed)
    """
```

### Table Args
Added explicit check constraints to model:
```python
__table_args__ = (
    db.CheckConstraint("received_date <= CURRENT_DATE", name='c_donation_1'),
    db.CheckConstraint("status_code IN ('E', 'V', 'P')", name='c_donation_2'),
)
```

## Files Modified
1. `migrations/006_alter_donation_status_constraint.sql` - Migration SQL
2. `app/db/models.py` - Updated Donation model with documentation and constraints
3. `replit.md` - Updated database architecture documentation

## Next Steps
The donation table is now ready to support the full donation intake workflow with three distinct status states, enabling proper tracking of donations from entry through verification to final processing.
