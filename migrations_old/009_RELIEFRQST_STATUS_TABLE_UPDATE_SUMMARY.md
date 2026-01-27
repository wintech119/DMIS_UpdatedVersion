# Migration 009: Relief Request Status Table Update

## Overview
Updated the `reliefrqst_status` lookup table to expand status description length, add missing status code, update reason requirements, and create supporting views for workflow categorization.

## Migration Date
November 18, 2025

## Changes Applied

### 1. Column Modification
**Expanded status_desc column:**
- **Before**: `VARCHAR(20)`
- **After**: `VARCHAR(30)`
- **Reason**: Allow longer status descriptions like "AWAITING APPROVAL" without truncation

### 2. Data Updates
**Updated reason_rqrd_flag for specific statuses:**

| Status Code | Status Desc | Old Flag | New Flag | Reason |
|-------------|-------------|----------|----------|--------|
| 4 | DENIED | FALSE | TRUE | Denial requires documented reason |
| 6 | CLOSED | FALSE | TRUE | Closure requires documented reason |
| 8 | INELIGIBLE | FALSE | TRUE | Ineligibility requires documented reason |

### 3. Missing Status Added
**Inserted status 9:**
```sql
INSERT INTO reliefrqst_status VALUES (9, 'PROCESSED', FALSE, TRUE);
```

### 4. Views Created
Three supporting views for workflow categorization:

#### v_status4reliefrqst_create
Statuses used during relief request creation:
- 0 = DRAFT
- 1 = AWAITING APPROVAL
- 2 = CANCELLED
- 3 = SUBMITTED

#### v_status4reliefrqst_action
Statuses used during relief request actioning:
- 4 = DENIED (requires reason)
- 5 = PART FILLED
- 6 = CLOSED (requires reason)
- 7 = FILLED
- 8 = INELIGIBLE (requires reason)

#### v_status4reliefrqst_processed
Status for processed relief requests:
- 9 = PROCESSED

## Complete Status Reference

| Code | Status Description | Workflow | Reason Required | Active |
|------|-------------------|----------|-----------------|--------|
| 0 | DRAFT | Creation | No | Yes |
| 1 | AWAITING APPROVAL | Creation | No | Yes |
| 2 | CANCELLED | Creation | No | Yes |
| 3 | SUBMITTED | Creation | No | Yes |
| 4 | DENIED | Action | **Yes** | Yes |
| 5 | PART FILLED | Action | No | Yes |
| 6 | CLOSED | Action | **Yes** | Yes |
| 7 | FILLED | Action | No | Yes |
| 8 | INELIGIBLE | Action | **Yes** | Yes |
| 9 | PROCESSED | Processed | No | Yes |

## Technical Details

### Migration Sequence
Due to view dependencies on the table column, the migration required a specific sequence:
1. Drop all dependent views
2. Alter column type from VARCHAR(20) to VARCHAR(30)
3. Update reason_rqrd_flag values
4. Insert missing status code 9
5. Recreate all views with updated structure

### Referential Integrity
**Maintained**: One foreign key reference from `reliefrqst` table:
```sql
FOREIGN KEY (status_code) REFERENCES reliefrqst_status(status_code)
```
No data disruption - all existing status codes preserved.

### View Definitions

```sql
-- View for creation workflow statuses
CREATE VIEW v_status4reliefrqst_create AS
    SELECT status_code, status_desc, reason_rqrd_flag
    FROM reliefrqst_status
    WHERE status_code IN (0,1,2,3) AND is_active_flag = TRUE;

-- View for action workflow statuses
CREATE VIEW v_status4reliefrqst_action AS
    SELECT status_code, status_desc, reason_rqrd_flag
    FROM reliefrqst_status
    WHERE status_code IN (4,5,6,7,8) AND is_active_flag = TRUE;

-- View for processed workflow statuses
CREATE VIEW v_status4reliefrqst_processed AS
    SELECT status_code, status_desc, reason_rqrd_flag
    FROM reliefrqst_status
    WHERE status_code IN (9) AND is_active_flag = TRUE;
```

## Validation Results

### Table Structure
✅ 4 columns with correct data types
✅ status_desc now VARCHAR(30)
✅ Primary key on status_code maintained

### Data Integrity
✅ All 10 status codes present (0-9)
✅ reason_rqrd_flag correctly set for statuses 4, 6, 8
✅ All statuses active (is_active_flag = TRUE)
✅ No orphaned foreign key references

### Views
✅ v_status4reliefrqst_create: Returns 4 statuses
✅ v_status4reliefrqst_action: Returns 5 statuses
✅ v_status4reliefrqst_processed: Returns 1 status
✅ All views functioning correctly

### Referential Integrity
✅ Foreign key from reliefrqst table maintained
✅ No data loss or corruption
✅ All existing relief requests still valid

## SQLAlchemy Model Updates

### Updated ReliefRqstStatus Model
```python
class ReliefRqstStatus(db.Model):
    """Relief Request Status Lookup Table
    
    Status Codes:
        0 = DRAFT (creation workflow)
        1 = AWAITING APPROVAL (creation workflow)
        2 = CANCELLED (creation workflow)
        3 = SUBMITTED (creation workflow)
        4 = DENIED (action workflow, requires reason)
        5 = PART FILLED (action workflow)
        6 = CLOSED (action workflow, requires reason)
        7 = FILLED (action workflow)
        8 = INELIGIBLE (action workflow, requires reason)
        9 = PROCESSED (processed workflow)
    
    Views:
        v_status4reliefrqst_create: Statuses 0,1,2,3 (creation)
        v_status4reliefrqst_action: Statuses 4,5,6,7,8 (action)
        v_status4reliefrqst_processed: Status 9 (processed)
    """
    __tablename__ = 'reliefrqst_status'
    
    status_code = db.Column(db.SmallInteger, primary_key=True)
    status_desc = db.Column(db.String(30), nullable=False)  # Updated from 20 to 30
    reason_rqrd_flag = db.Column(db.Boolean, nullable=False, default=False)
    is_active_flag = db.Column(db.Boolean, nullable=False, default=True)
```

## Workflow Integration

### Creation Workflow (Agencies)
Use `v_status4reliefrqst_create` view to populate status dropdowns:
- DRAFT → Initial request creation
- AWAITING APPROVAL → Pending internal review
- SUBMITTED → Sent to ODPEM
- CANCELLED → Request cancelled

### Action Workflow (ODPEM Directors)
Use `v_status4reliefrqst_action` view for decision statuses:
- DENIED → Request rejected (reason required)
- INELIGIBLE → Agency/event not eligible (reason required)
- PART FILLED → Partially fulfilled
- FILLED → Completely fulfilled
- CLOSED → Request closed (reason required)

### Processed Workflow (Post-fulfillment)
Use `v_status4reliefrqst_processed` view:
- PROCESSED → Relief packages distributed/completed

## Reason Requirement Logic

When updating relief request status to codes 4, 6, or 8, the application must:
1. Check `reason_rqrd_flag` for the target status
2. If TRUE, validate that `reason_desc` field is populated
3. Prevent status update if reason is missing
4. Display appropriate validation error to user

Example validation:
```python
status = ReliefRqstStatus.query.get(new_status_code)
if status.reason_rqrd_flag and not relief_request.reason_desc:
    raise ValidationError(f"Reason required when status is {status.status_desc}")
```

## Files Modified
1. `migrations/009_alter_reliefrqst_status_table.sql` - Migration SQL
2. `app/db/models.py` - Updated ReliefRqstStatus model with documentation

## Next Steps
The reliefrqst_status table is now ready to support the complete relief request workflow with:
- 10 distinct status codes covering all workflow stages
- Proper reason requirements for denial/closure/ineligibility
- Three workflow-specific views for UI filtering
- Full referential integrity maintained
