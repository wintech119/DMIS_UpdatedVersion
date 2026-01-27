# Migration 008: Donation Intake Item Table Recreation

## Overview
Dropped and recreated the `dnintake_item` table to fix data type precision issues, constraint bugs, and add missing constraints to match DRIMS specifications.

## Migration Date
November 18, 2025

## Changes Applied

### 1. Quantity Precision Correction
**Critical Change**: Changed quantity columns from `DECIMAL(15,4)` to `DECIMAL(12,2)`

| Column | Old Precision | New Precision | Impact |
|--------|---------------|---------------|--------|
| usable_qty | DECIMAL(15,4) | DECIMAL(12,2) | Matches spec, reduces storage |
| defective_qty | DECIMAL(15,4) | DECIMAL(12,2) | Matches spec, reduces storage |
| expired_qty | DECIMAL(15,4) | DECIMAL(12,2) | Matches spec, reduces storage |

**Reason**: The specification requires DECIMAL(12,2) for all quantity fields to maintain consistency across donation intake tracking.

### 2. Constraint Fixes

#### Fixed: avg_unit_value Constraint
- **Old**: `c_dnintake_item_1d CHECK (avg_unit_value >= 0.00)`
- **New**: `c_dnintake_item_1d CHECK (avg_unit_value > 0.00)`
- **Reason**: Average unit value must be positive (greater than zero), not just non-negative

#### Fixed: expired_qty Constraint Bug
- **Old**: `c_dnintake_item_4 CHECK (defective_qty >= 0.00)` ❌ (checking wrong column!)
- **New**: `c_dnintake_item_4 CHECK (expired_qty >= 0.00)` ✅
- **Reason**: Constraint was incorrectly checking defective_qty instead of expired_qty

#### Added: expiry_date Constraint
- **New**: `c_dnintake_item_1c CHECK (expiry_date >= CURRENT_DATE OR expiry_date IS NULL)`
- **Reason**: Missing from previous version, ensures expiry dates are in the future or NULL

### Table Structure

#### Primary Key
Composite primary key on four columns:
```sql
PRIMARY KEY (donation_id, inventory_id, item_id, batch_no)
```

#### Foreign Keys
1. **fk_dnintake_item_intake**: `(donation_id, inventory_id)` → `dnintake(donation_id, inventory_id)`
2. **fk_dnintake_item_donation_item**: `(donation_id, item_id)` → `donation_item(donation_id, item_id)`
3. **fk_dnintake_item_unitofmeasure**: `uom_code` → `unitofmeasure(uom_code)`

#### Check Constraints (10 total)
| Constraint | Purpose | Rule |
|------------|---------|------|
| c_dnintake_item_1a | Batch number uppercase | `batch_no = UPPER(batch_no)` |
| c_dnintake_item_1b | Batch date validity | `batch_date <= CURRENT_DATE` |
| c_dnintake_item_1c | Expiry date validity | `expiry_date >= CURRENT_DATE OR NULL` |
| c_dnintake_item_1d | Positive unit value | `avg_unit_value > 0.00` |
| c_dnintake_item_2 | Non-negative usable qty | `usable_qty >= 0.00` |
| c_dnintake_item_3 | Non-negative defective qty | `defective_qty >= 0.00` |
| c_dnintake_item_4 | Non-negative expired qty | `expired_qty >= 0.00` |
| c_dnintake_item_5 | Valid status code | `status_code IN ('P','V')` |

#### Indexes
1. **dk_dnintake_item_1**: `(inventory_id, item_id)` - Composite lookup
2. **dk_dnintake_item_2**: `(item_id)` - Single-column lookup
3. **pk_dnintake_item**: Unique index on primary key (auto-created)

### Status Codes
- **P** = Processed (intake processed/completed)
- **V** = Verified (intake verified by custodian)

## Technical Details

### Data Impact
- **Zero data loss**: Table had 0 rows before migration
- **No dependencies**: No tables reference dnintake_item
- **Safe operation**: Clean drop and recreate with no cascade effects

### Full Table Schema
```sql
CREATE TABLE dnintake_item
(
    donation_id INTEGER NOT NULL,
    inventory_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    batch_no VARCHAR(20) NOT NULL
        CONSTRAINT c_dnintake_item_1a CHECK (batch_no = UPPER(batch_no)),
    batch_date DATE NOT NULL
        CONSTRAINT c_dnintake_item_1b CHECK (batch_date <= CURRENT_DATE),
    expiry_date DATE 
        CONSTRAINT c_dnintake_item_1c CHECK (expiry_date >= CURRENT_DATE OR expiry_date IS NULL),
    uom_code VARCHAR(25) NOT NULL
        CONSTRAINT fk_dnintake_item_unitofmeasure REFERENCES unitofmeasure(uom_code),
    avg_unit_value DECIMAL(10,2) NOT NULL
        CONSTRAINT c_dnintake_item_1d CHECK (avg_unit_value > 0.00),
    usable_qty DECIMAL(12,2) NOT NULL
        CONSTRAINT c_dnintake_item_2 CHECK (usable_qty >= 0.00),
    defective_qty DECIMAL(12,2) NOT NULL
        CONSTRAINT c_dnintake_item_3 CHECK (defective_qty >= 0.00),
    expired_qty DECIMAL(12,2) NOT NULL
        CONSTRAINT c_dnintake_item_4 CHECK (expired_qty >= 0.00),
    status_code CHAR(1) NOT NULL
        CONSTRAINT c_dnintake_item_5 CHECK (status_code IN ('P','V')),
    comments_text VARCHAR(255),
    create_by_id VARCHAR(20) NOT NULL,
    create_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    update_by_id VARCHAR(20) NOT NULL,
    update_dtime TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL,
    version_nbr INTEGER NOT NULL,
    CONSTRAINT fk_dnintake_item_intake FOREIGN KEY (donation_id, inventory_id) 
        REFERENCES dnintake(donation_id, inventory_id),
    CONSTRAINT fk_dnintake_item_donation_item FOREIGN KEY(donation_id, item_id)
        REFERENCES donation_item(donation_id, item_id),
    CONSTRAINT pk_dnintake_item PRIMARY KEY(donation_id, inventory_id, item_id, batch_no)
);
```

## Validation Results

### Table Structure
✅ 18 columns with correct data types
✅ Quantity columns using DECIMAL(12,2) as specified
✅ avg_unit_value using DECIMAL(10,2) as specified

### Constraints
✅ 1 Primary key constraint
✅ 3 Foreign key constraints (referential integrity maintained)
✅ 8 Check constraints (all bugs fixed)
✅ 3 Indexes (2 custom + 1 PK index)

### Referential Integrity
✅ dnintake parent table exists and accessible
✅ donation_item parent table exists and accessible
✅ unitofmeasure parent table exists and accessible
✅ All foreign key relationships valid

## SQLAlchemy Model Updates

### Updated DonationIntakeItem Model
```python
class DonationIntakeItem(db.Model):
    """Donation Intake Item - Batch-level intake tracking for donations
    
    Status Codes:
        P = Processed
        V = Verified
    """
    __tablename__ = 'dnintake_item'
    
    # Composite primary key
    donation_id = db.Column(db.Integer, primary_key=True)
    inventory_id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, primary_key=True)
    batch_no = db.Column(db.String(20), primary_key=True, nullable=False)
    
    # Batch tracking
    batch_date = db.Column(db.Date, nullable=False)
    expiry_date = db.Column(db.Date)
    
    # Quantities (DECIMAL(12,2))
    usable_qty = db.Column(db.Numeric(12, 2), nullable=False)
    defective_qty = db.Column(db.Numeric(12, 2), nullable=False)
    expired_qty = db.Column(db.Numeric(12, 2), nullable=False)
    
    # Unit details
    uom_code = db.Column(db.String(25), db.ForeignKey('unitofmeasure.uom_code'), nullable=False)
    avg_unit_value = db.Column(db.Numeric(10, 2), nullable=False)
    
    # Status and audit
    status_code = db.Column(db.CHAR(1), nullable=False)
    # ... audit fields ...
    
    __table_args__ = (
        db.ForeignKeyConstraint(['donation_id', 'inventory_id'], 
                               ['dnintake.donation_id', 'dnintake.inventory_id'], 
                               name='fk_dnintake_item_intake'),
        db.ForeignKeyConstraint(['donation_id', 'item_id'], 
                               ['donation_item.donation_id', 'donation_item.item_id'], 
                               name='fk_dnintake_item_donation_item'),
        db.CheckConstraint("batch_no = UPPER(batch_no)", name='c_dnintake_item_1a'),
        db.CheckConstraint("batch_date <= CURRENT_DATE", name='c_dnintake_item_1b'),
        db.CheckConstraint("expiry_date >= CURRENT_DATE OR expiry_date IS NULL", name='c_dnintake_item_1c'),
        db.CheckConstraint("avg_unit_value > 0.00", name='c_dnintake_item_1d'),
        db.CheckConstraint("usable_qty >= 0.00", name='c_dnintake_item_2'),
        db.CheckConstraint("defective_qty >= 0.00", name='c_dnintake_item_3'),
        db.CheckConstraint("expired_qty >= 0.00", name='c_dnintake_item_4'),
        db.CheckConstraint("status_code IN ('P', 'V')", name='c_dnintake_item_5'),
        db.Index('dk_dnintake_item_1', 'inventory_id', 'item_id'),
        db.Index('dk_dnintake_item_2', 'item_id'),
    )
```

## Important Notes

### Batch Management Logic
The table tracks batch-level intake of donated items. When processing intake:
1. Check if batch exists in `itembatch` table
2. If not exists: Create new batch with batch_id and zero quantities
3. Update batch quantities with amounts from this intake record
4. This preserves batch traceability across the donation intake workflow

### Quantity Precision Impact
Changing from DECIMAL(15,4) to DECIMAL(12,2) affects:
- **Storage**: Slightly reduced storage per row
- **Precision**: From 4 decimal places to 2 (appropriate for quantities)
- **Maximum value**: From 99,999,999,999.9999 to 9,999,999,999.99 (still ample)
- **DRIMS consistency**: Now matches other quantity fields across the system

## Files Modified
1. `migrations/008_recreate_dnintake_item_table.sql` - Migration SQL
2. `app/db/models.py` - Updated DonationIntakeItem model with correct precision and all constraints

## Next Steps
The dnintake_item table is now ready to support donation intake processing with:
- Correct quantity precision (DECIMAL 12,2)
- All constraint bugs fixed
- Full referential integrity maintained
- Complete batch tracking capability
