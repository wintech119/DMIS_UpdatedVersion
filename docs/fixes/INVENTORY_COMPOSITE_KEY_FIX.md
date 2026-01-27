# Fix: InvalidRequestError on Inventory Query with Composite Primary Key

**Date:** November 18, 2025  
**Status:** ✅ Fixed  
**Severity:** Critical - Blocks package preparation page loading

## Problem

When loading the package preparation page, the application threw an `InvalidRequestError`:

```
sqlalchemy.exc.InvalidRequestError: Incorrect number of values in identifier to formulate 
primary key for session.get(); primary key columns are 'inventory.inventory_id','inventory.item_id'
```

**Stack Trace Location:**
- File: `app/features/packaging.py`, line 325
- Function: `prepare_package()` (GET request handler)

## Root Cause

### Composite Primary Key

The `Inventory` table uses a **composite primary key** consisting of both `inventory_id` and `item_id`:

```python
class Inventory(db.Model):
    inventory_id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, primary_key=True)
    # ... other fields
```

### The Bug

When querying with `.get()`, the code was only passing one value:

```python
# BROKEN CODE:
warehouse_id = Inventory.query.get(pkg_item.fr_inventory_id).warehouse_id
```

SQLAlchemy's `.get()` method requires **all primary key values** when dealing with composite keys. The correct syntax would be:

```python
# Would work but is inefficient:
warehouse_id = Inventory.query.get((pkg_item.fr_inventory_id, pkg_item.item_id)).warehouse_id
```

### Schema Understanding

However, there's a simpler solution! According to the database schema:

> **inventory_id IS the warehouse_id** - named for table alignment.

This means `fr_inventory_id` in the `reliefpkg_item` table is already the warehouse_id, so we don't need to query the Inventory table at all.

## Solution

### Code Changes

**File:** `app/features/packaging.py` (line 329)

**Before (Broken):**
```python
existing_allocations = {}
for pkg in existing_packages:
    for pkg_item in pkg.items:
        item_id = pkg_item.item_id
        warehouse_id = Inventory.query.get(pkg_item.fr_inventory_id).warehouse_id
        # ... rest of logic
```

**After (Fixed):**
```python
existing_allocations = {}
for pkg in existing_packages:
    for pkg_item in pkg.items:
        item_id = pkg_item.item_id
        # fr_inventory_id IS the warehouse_id (inventory_id = warehouse_id in schema)
        warehouse_id = pkg_item.fr_inventory_id
        # ... rest of logic
```

### Benefits of This Fix

1. ✅ **Eliminates the error** - No more InvalidRequestError
2. ✅ **More efficient** - Removes unnecessary database query
3. ✅ **Clearer code** - Directly uses the warehouse_id value
4. ✅ **Follows schema design** - Respects that inventory_id = warehouse_id

## Understanding Composite Primary Keys in SQLAlchemy

### Single Primary Key
```python
# Model with single PK
class User(db.Model):
    user_id = db.Column(db.Integer, primary_key=True)

# Query with .get()
user = User.query.get(123)  # ✅ Pass single value
```

### Composite Primary Key
```python
# Model with composite PK
class Inventory(db.Model):
    inventory_id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, primary_key=True)

# Query with .get()
inventory = Inventory.query.get((5, 10))  # ✅ Pass tuple of (inventory_id, item_id)
inventory = Inventory.query.get(5)         # ❌ ERROR: Missing item_id
```

### Alternative Query Methods

When you can't use `.get()` with composite keys, use filters instead:

```python
# Option 1: filter_by
inventory = Inventory.query.filter_by(
    inventory_id=warehouse_id,
    item_id=item_id
).first()

# Option 2: filter with conditions
inventory = Inventory.query.filter(
    Inventory.inventory_id == warehouse_id,
    Inventory.item_id == item_id
).first()
```

## Schema Clarification

### Inventory Table Structure

```sql
CREATE TABLE inventory (
    inventory_id INTEGER PRIMARY KEY,  -- Actually represents warehouse_id
    item_id INTEGER PRIMARY KEY,        -- Creates composite PK
    usable_qty NUMERIC(12,2),
    warehouse_id INTEGER REFERENCES warehouse(warehouse_id),
    -- ... other fields
);
```

**Important Note:** While the table has a `warehouse_id` column, the `inventory_id` column is the primary key and **also represents the warehouse_id**. This design choice was made for historical compatibility with the ODPEM schema.

### ReliefPkgItem Reference

```python
class ReliefPkgItem(db.Model):
    reliefpkg_id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.Integer, primary_key=True)
    fr_inventory_id = db.Column(db.Integer)  # This IS the warehouse_id
    # ... other fields
```

The `fr_inventory_id` field stores the warehouse_id directly, eliminating the need to look it up from the Inventory table.

## Testing

### Test Case: Load Package Preparation Page

**Before Fix:**
```
1. Navigate to /packaging/<reliefrqst_id>/prepare
2. ❌ Page crashes with InvalidRequestError
3. ❌ Cannot view or edit package allocations
```

**After Fix:**
```
1. Navigate to /packaging/<reliefrqst_id>/prepare
2. ✅ Page loads successfully
3. ✅ Existing allocations displayed correctly
4. ✅ Can view and edit package allocations
```

### Test Case: Multiple Packages

**Scenario:** Relief request with multiple draft packages from different warehouses

**Result:**
```python
existing_allocations = {
    7: {  # item_id
        1: Decimal('10.00'),  # warehouse 1: 10 units
        2: Decimal('5.00')    # warehouse 2: 5 units
    },
    8: {  # item_id
        1: Decimal('20.00')   # warehouse 1: 20 units
    }
}
```

✅ All allocations calculated correctly without database errors

## Impact

### Before Fix
❌ Package preparation page completely broken  
❌ Cannot load existing allocations  
❌ Cannot view or edit packages  
❌ InvalidRequestError on every page load  

### After Fix
✅ Package preparation page loads perfectly  
✅ Existing allocations displayed correctly  
✅ More efficient (one less database query per package item)  
✅ Clearer, more maintainable code  

## Related Files

- ✅ `app/features/packaging.py` - Fixed warehouse_id retrieval
- ✅ `app/db/models.py` - Contains Inventory model with composite PK

## Lessons Learned

1. **Understand composite keys** - Tables can have multiple primary key columns
2. **Check schema documentation** - Understand column naming conventions (inventory_id = warehouse_id)
3. **Avoid unnecessary queries** - If data is already available, use it directly
4. **Read error messages carefully** - SQLAlchemy clearly stated "primary key columns are 'inventory.inventory_id','inventory.item_id'"
5. **Test with real data** - This error only appears when loading existing packages

## Documentation Updates

Updated `replit.md` to clarify:
- Inventory table uses composite primary key (inventory_id, item_id)
- inventory_id IS the warehouse_id (naming convention for schema alignment)
