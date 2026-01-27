# Optimistic Locking in DRIMS

## Overview

DRIMS uses SQLAlchemy's `version_id_col` feature to implement optimistic locking across all database tables that include a `version_nbr` column. This prevents data loss when multiple users attempt to update the same record simultaneously.

## How It Works

### Configuration

The `setup_optimistic_locking()` function in `app/core/optimistic_locking.py` automatically configures optimistic locking for all models:

1. **Iterates through all model classes** in `app.db.models`
2. **Detects models with `version_nbr` column**
3. **Configures `version_id_col`** on the SQLAlchemy mapper
4. **Enables automatic version management** by SQLAlchemy

### Automatic Version Increment

When configured, SQLAlchemy automatically:
- Includes the current version number in the UPDATE statement's WHERE clause
- Increments the version number on successful updates
- Raises `StaleDataError` if another session updated the record first

### Example UPDATE Statement

Without optimistic locking:
```sql
UPDATE warehouse SET phone = '876-555-1111' WHERE warehouse_id = 'WH001';
```

With optimistic locking:
```sql
UPDATE warehouse 
SET phone = '876-555-1111', version_nbr = 5
WHERE warehouse_id = 'WH001' AND version_nbr = 4;
```

If the WHERE clause matches zero rows (because another session already updated version_nbr to 5), SQLAlchemy raises `StaleDataError`.

## Affected Tables

Optimistic locking is enabled on all tables with `version_nbr` column, including:

- `warehouse`
- `item`
- `inventory`
- `agency`
- `donor`
- `custodian`
- `relief_rqst`
- `reliefpkg`
- `donation`
- `transfer`
- `location`
- And all other ODPEM tables with audit fields

## How to Handle Concurrent Updates

### In Application Code

When a concurrent modification conflict occurs, SQLAlchemy raises `StaleDataError`:

```python
from sqlalchemy.orm.exc import StaleDataError
from app.db import db

try:
    warehouse = Warehouse.query.get(warehouse_id)
    warehouse.phone = new_phone
    db.session.commit()
except StaleDataError:
    db.session.rollback()
    flash('This record was updated by another user. Please refresh and try again.', 'warning')
    return redirect(url_for('warehouses.view', id=warehouse_id))
```

### User Experience

When a conflict occurs:
1. **User A** loads warehouse record (version 4)
2. **User B** loads same warehouse record (version 4)
3. **User A** saves changes → version becomes 5
4. **User B** attempts to save → StaleDataError raised
5. **User B** sees error message and must refresh to see User A's changes

## Verification

To verify optimistic locking is working:

```python
from app import app
from app.db.models import Warehouse
from app.db import db
from sqlalchemy import inspect

with app.app_context():
    # Check configuration
    mapper = inspect(Warehouse)
    print(f"Version column configured: {mapper.version_id_col is not None}")
    
    # Test version increment
    warehouse = Warehouse.query.first()
    print(f"Current version: {warehouse.version_nbr}")
    
    warehouse.phone = "TEST-876-555-9999"
    db.session.commit()
    
    db.session.refresh(warehouse)
    print(f"New version: {warehouse.version_nbr}")  # Should increment
```

## Testing Concurrent Access

To properly test optimistic locking, you need **separate database sessions**:

```python
from sqlalchemy.orm import sessionmaker
from app.db import db

# Create two independent sessions
Session = sessionmaker(bind=db.engine)
session1 = Session()
session2 = Session()

# Both sessions load same record
warehouse1 = session1.query(Warehouse).get('WH001')
warehouse2 = session2.query(Warehouse).get('WH001')

# Session 1 updates and commits
warehouse1.phone = '876-555-1111'
session1.commit()

# Session 2 attempts update (should fail)
warehouse2.phone = '876-555-2222'
session2.commit()  # Raises StaleDataError!
```

## Implementation Details

### Setup Function

The setup happens automatically during app initialization in `app/db/__init__.py`:

```python
def init_db(app):
    db.init_app(app)
    
    with app.app_context():
        setup_optimistic_locking(db)  # Configures all models
    
    return db
```

### Database Schema

The `version_nbr` column is part of the ODPEM audit fields:
- Type: `INTEGER`
- Default: `1`
- Auto-incremented by SQLAlchemy on updates
- Included in UPDATE statement WHERE clause

## Best Practices

1. **Always handle StaleDataError** in forms that update critical data
2. **Show meaningful error messages** to users when conflicts occur
3. **Provide refresh mechanism** so users can see latest data and retry
4. **Don't suppress StaleDataError** - it indicates genuine data conflicts
5. **Use optimistic locking for high-read, low-write scenarios** (perfect for DRIMS)

## Custom Exception (Optional)

A custom `OptimisticLockError` class exists in `app/core/exceptions.py` for wrapping `StaleDataError` with application-specific messaging:

```python
from app.core.exceptions import OptimisticLockError
from sqlalchemy.orm.exc import StaleDataError

try:
    db.session.commit()
except StaleDataError as e:
    db.session.rollback()
    raise OptimisticLockError(
        model_name=warehouse.__class__.__name__,
        record_id=warehouse.warehouse_id,
        message="This record was modified by another user. Please refresh and try again."
    )
```

Note: Currently, `StaleDataError` is raised directly by SQLAlchemy. To use `OptimisticLockError` application-wide, you would need to add a global exception handler or wrap commits in a try-except block.

## Benefits

✓ **Prevents lost updates** - No silent data overwrites  
✓ **No database locks** - Better performance than pessimistic locking  
✓ **Simple implementation** - Automatic version management  
✓ **Clear error handling** - Explicit conflict detection  
✓ **Audit compliance** - Version history preserved  

## Summary

Optimistic locking in DRIMS:
- ✓ **Configured automatically** on all tables with `version_nbr`
- ✓ **Managed by SQLAlchemy** - no manual version tracking needed
- ✓ **Raises StaleDataError** on concurrent update conflicts
- ✓ **Verified working** - version numbers increment on updates
- ✓ **Production-ready** - handles real-world concurrent access scenarios
