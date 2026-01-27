"""
Inventory Reservation Service

Manages inventory reservations during package preparation to prevent
double-allocation across concurrent package fulfillment operations.

Key Functions:
- reserve_inventory(): Updates reserved_qty when saving draft allocations
- release_inventory(): Releases reserved_qty when canceling or abandoning
- commit_inventory(): Converts reservations to actual deductions on dispatch
"""

from decimal import Decimal
from typing import List, Dict, Tuple, Optional
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import func
from app.db import db
from app.db.models import Inventory, ReliefPkgItem, ItemBatch
from app.security.log_sanitizer import sanitize_exception_for_log


def get_current_reservations(reliefrqst_id: int) -> Dict[Tuple[int, int], Decimal]:
    """
    Get current inventory reservations for a relief request.
    
    Returns: {(item_id, inventory_id): reserved_qty}
    Note: inventory_id IS the warehouse_id (composite PK pattern)
    """
    # Get the parent ReliefPkg first to get the reliefrqst_id mapping
    from app.db.models import ReliefPkg
    pkg = ReliefPkg.query.filter_by(reliefrqst_id=reliefrqst_id).first()
    
    if not pkg:
        return {}
    
    pkg_items = ReliefPkgItem.query.filter_by(reliefpkg_id=pkg.reliefpkg_id).all()
    
    reservations = {}
    for pkg_item in pkg_items:
        if pkg_item.item_qty and pkg_item.item_qty > 0:
            # inventory_id IS the warehouse_id (composite PK: inventory_id, item_id)
            # fr_inventory_id is the warehouse_id
            key = (pkg_item.item_id, pkg_item.fr_inventory_id)
            reservations[key] = pkg_item.item_qty
    
    return reservations


def get_current_batch_reservations(reliefrqst_id: int) -> Dict[Tuple[int, int, int], Decimal]:
    """
    Get current batch-level reservations for a relief request.
    
    Returns: {(item_id, inventory_id, batch_id): reserved_qty}
    Note: inventory_id IS the warehouse_id (composite PK pattern)
    """
    from app.db.models import ReliefPkg
    pkg = ReliefPkg.query.filter_by(reliefrqst_id=reliefrqst_id).first()
    
    if not pkg:
        return {}
    
    pkg_items = ReliefPkgItem.query.filter_by(reliefpkg_id=pkg.reliefpkg_id).all()
    
    batch_reservations = {}
    for pkg_item in pkg_items:
        if pkg_item.item_qty and pkg_item.item_qty > 0:
            key = (pkg_item.item_id, pkg_item.fr_inventory_id, pkg_item.batch_id)
            batch_reservations[key] = pkg_item.item_qty
    
    return batch_reservations


def reserve_inventory(reliefrqst_id: int, new_allocations: List[Dict], old_allocations: Optional[Dict[Tuple[int, int, int], Decimal]] = None) -> Tuple[bool, str]:
    """
    Reserve inventory for package allocations at BOTH batch and warehouse levels.
    
    Updates reserved_qty in:
    1. itembatch table (batch-level) for each allocated batch
    2. inventory table (warehouse-level) as sum of batch reservations
    
    Ensures consistency: sum(itembatch.reserved_qty) == inventory.reserved_qty
    for each (item_id, inventory_id) pair.
    
    Args:
        reliefrqst_id: Relief request ID
        new_allocations: List of {item_id, batch_id, warehouse_id, allocated_qty}
        old_allocations: Dict of {(item_id, inventory_id, batch_id): allocated_qty} from before update
                        If None, queries database for current reservations
    
    Returns:
        (success, error_message)
    
    Note: inventory_id IS the warehouse_id (composite PK pattern)
    """
    try:
        # Get old batch-level reservations (use provided or query from database)
        if old_allocations is not None:
            old_batch_reservations = old_allocations
        else:
            old_batch_reservations = get_current_batch_reservations(reliefrqst_id)
        
        # Build new batch-level reservations map
        new_batch_reservations = {}
        for alloc in new_allocations:
            if alloc['allocated_qty'] > 0:
                # Key: (item_id, inventory_id, batch_id)
                key = (alloc['item_id'], alloc['warehouse_id'], alloc['batch_id'])
                new_batch_reservations[key] = alloc['allocated_qty']
        
        # Seed affected_inventory from UNION of old and new allocations
        # This ensures warehouse totals are recalculated even when batches net to zero or are removed
        affected_inventory = set()
        for item_id, inventory_id, batch_id in old_batch_reservations.keys():
            if inventory_id is not None:  # Skip NULL inventory_id (invalid data)
                affected_inventory.add((item_id, inventory_id))
        for item_id, warehouse_id, batch_id in new_batch_reservations.keys():
            if warehouse_id is not None:  # Skip NULL warehouse_id (invalid data)
                affected_inventory.add((item_id, warehouse_id))
        
        # Update batch-level reservations (itembatch.reserved_qty)
        all_batch_keys = set(old_batch_reservations.keys()) | set(new_batch_reservations.keys())
        
        for key in all_batch_keys:
            item_id, inventory_id, batch_id = key
            
            # Skip entries with NULL inventory_id (invalid data)
            if inventory_id is None:
                return False, f'Invalid batch allocation: inventory_id is NULL for batch {batch_id}'
            
            old_batch_qty = old_batch_reservations.get(key, Decimal('0'))
            new_batch_qty = new_batch_reservations.get(key, Decimal('0'))
            batch_delta = new_batch_qty - old_batch_qty
            
            if batch_delta != 0:
                # Update batch reserved_qty using delta
                batch = ItemBatch.query.filter_by(
                    batch_id=batch_id,
                    item_id=item_id,
                    inventory_id=inventory_id
                ).with_for_update().first()
                
                if not batch:
                    # FAIL FAST: If trying to INCREASE reservation, this is a critical error
                    if batch_delta > 0:
                        return False, f'Batch {batch_id} not found for item {item_id} at warehouse {inventory_id}'
                    # If trying to DECREASE (release), log warning but continue
                    # The batch may have been deleted, but we still need to recalculate warehouse totals
                    from flask import current_app
                    current_app.logger.warning(
                        f'Cannot release reservation from missing batch: '
                        f'batch_id={batch_id}, item_id={item_id}, inventory_id={inventory_id}, '
                        f'delta={batch_delta}'
                    )
                    continue
                
                # Apply delta to batch reserved_qty
                new_batch_reserved = batch.reserved_qty + batch_delta
                
                # Validate: reserved_qty cannot be negative or exceed usable_qty
                if new_batch_reserved < 0:
                    batch.reserved_qty = Decimal('0')
                elif new_batch_reserved > batch.usable_qty:
                    available = batch.usable_qty - batch.reserved_qty
                    return False, f'Cannot reserve {batch_delta} units from batch {batch_id} - only {available} available'
                else:
                    batch.reserved_qty = new_batch_reserved
        
        # Update warehouse-level reservations (inventory.reserved_qty)
        # Recalculate from sum of batch reservations to ensure consistency
        for item_id, inventory_id in affected_inventory:
            # Sum all batch reservations for this item+warehouse
            batch_totals = db.session.query(
                db.func.sum(ItemBatch.reserved_qty).label('total_reserved')
            ).filter(
                ItemBatch.item_id == item_id,
                ItemBatch.inventory_id == inventory_id
            ).first()
            
            # Get the inventory record
            inventory = Inventory.query.filter_by(
                item_id=item_id,
                inventory_id=inventory_id,
                status_code='A'
            ).with_for_update().first()
            
            if not inventory:
                return False, f'No active inventory found for item {item_id} at warehouse {inventory_id}'
            
            # Update inventory reserved_qty from batch sum
            inventory.reserved_qty = batch_totals.total_reserved if batch_totals.total_reserved is not None else Decimal('0')
            
            # Validate: reserved_qty must not exceed usable_qty
            if inventory.reserved_qty > inventory.usable_qty:
                return False, f'Total reservations exceed available inventory for item {item_id} at warehouse {inventory_id}'
        
        return True, ''
        
    except SQLAlchemyError as e:
        db.session.rollback()
        return False, f'Database error during reservation: {str(e)}'


def release_all_reservations(reliefrqst_id: int) -> Tuple[bool, str]:
    """
    Release all inventory reservations for a relief request at BOTH batch and warehouse levels.
    
    Called when:
    - User cancels package preparation
    - Lock expires without saving
    - Package is abandoned
    
    Updates:
    1. Decreases itembatch.reserved_qty for each batch allocated to this package
    2. Recalculates inventory.reserved_qty from SUM(itembatch.reserved_qty)
    
    Args:
        reliefrqst_id: Relief request ID
    
    Returns:
        (success, error_message)
    
    Note: inventory_id IS the warehouse_id (composite PK pattern)
    """
    try:
        # Get batch-level reservations for this package
        batch_reservations = get_current_batch_reservations(reliefrqst_id)
        
        # Track affected (item_id, inventory_id) pairs for warehouse-level recalculation
        affected_inventory = set()
        
        # Release batch-level reservations (itembatch.reserved_qty)
        for (item_id, inventory_id, batch_id), reserved_qty in batch_reservations.items():
            if reserved_qty > 0:
                # Skip entries with NULL inventory_id (invalid data)
                if inventory_id is None:
                    from flask import current_app
                    current_app.logger.warning(
                        f'Skipping batch release for NULL inventory_id: '
                        f'batch_id={batch_id}, item_id={item_id}, reserved_qty={reserved_qty}'
                    )
                    continue
                
                # Get the batch and release reservation
                batch = ItemBatch.query.filter_by(
                    batch_id=batch_id,
                    item_id=item_id,
                    inventory_id=inventory_id
                ).with_for_update().first()
                
                if batch:
                    # Reduce batch reserved_qty, ensuring it doesn't go below zero
                    batch.reserved_qty = max(Decimal('0'), batch.reserved_qty - reserved_qty)
                    # Track this warehouse for inventory-level recalculation
                    affected_inventory.add((item_id, inventory_id))
                else:
                    # Log warning if batch not found but continue releasing other batches
                    from flask import current_app
                    current_app.logger.warning(
                        f'Batch not found during release: '
                        f'batch_id={batch_id}, item_id={item_id}, inventory_id={inventory_id}'
                    )
                    # Still track for warehouse recalculation
                    affected_inventory.add((item_id, inventory_id))
        
        # Recalculate warehouse-level reservations (inventory.reserved_qty) from batch sums
        for item_id, inventory_id in affected_inventory:
            # Sum all batch reservations for this item+warehouse
            batch_totals = db.session.query(
                func.sum(ItemBatch.reserved_qty).label('total_reserved')
            ).filter(
                ItemBatch.item_id == item_id,
                ItemBatch.inventory_id == inventory_id
            ).first()
            
            # Get the inventory record
            inventory = Inventory.query.filter_by(
                item_id=item_id,
                inventory_id=inventory_id,
                status_code='A'
            ).with_for_update().first()
            
            if inventory:
                # Update inventory reserved_qty from batch sum
                inventory.reserved_qty = batch_totals.total_reserved if batch_totals.total_reserved is not None else Decimal('0')
        
        return True, ''
        
    except SQLAlchemyError as e:
        db.session.rollback()
        return False, f'Database error during release: {str(e)}'


def commit_inventory(reliefrqst_id: int) -> Tuple[bool, str]:
    """
    Commit inventory allocations on package dispatch at BATCH LEVEL.
    
    Converts reservations to actual deductions:
    - Decreases batch.usable_qty by allocated amounts for each batch
    - Decreases batch.reserved_qty by allocated amounts for each batch
    - Updates warehouse-level inventory.usable_qty and inventory.reserved_qty
    
    Called when Logistics Manager sends package for dispatch.
    
    Args:
        reliefrqst_id: Relief request ID
    
    Returns:
        (success, error_message)
    """
    try:
        # Get all package items with their batch-level allocations
        from app.db.models import ReliefPkg
        pkg = ReliefPkg.query.filter_by(reliefrqst_id=reliefrqst_id).first()
        
        if not pkg:
            return False, 'No package found for this relief request'
        
        pkg_items = ReliefPkgItem.query.filter_by(reliefpkg_id=pkg.reliefpkg_id).all()
        
        # Track affected (item_id, inventory_id) combinations for inventory table update
        affected_inventory = set()
        
        # Process each batch allocation
        for pkg_item in pkg_items:
            if pkg_item.item_qty and pkg_item.item_qty > 0:
                # Deduct from the specific batch
                batch = ItemBatch.query.filter_by(
                    batch_id=pkg_item.batch_id,
                    inventory_id=pkg_item.fr_inventory_id,
                    item_id=pkg_item.item_id
                ).with_for_update().first()
                
                if not batch:
                    return False, f'Batch {pkg_item.batch_id} not found for item {pkg_item.item_id}'
                
                # Validate sufficient batch quantity
                if batch.usable_qty < pkg_item.item_qty:
                    from app.db.models import Warehouse
                    warehouse = Warehouse.query.get(pkg_item.fr_inventory_id)
                    warehouse_name = warehouse.warehouse_name if warehouse else f'ID {pkg_item.fr_inventory_id}'
                    return False, f'Insufficient inventory at warehouse {warehouse_name}: need {pkg_item.item_qty}, have {batch.usable_qty}'
                
                # Commit batch allocation - deduct from batch
                batch.usable_qty -= pkg_item.item_qty
                batch.reserved_qty = max(Decimal('0'), batch.reserved_qty - pkg_item.item_qty)
                
                # Track this inventory record for update
                affected_inventory.add((pkg_item.item_id, pkg_item.fr_inventory_id))
        
        # Update inventory table totals by recalculating from batch sums
        # This ensures inventory.usable_qty and inventory.reserved_qty match the sum of their batches
        for item_id, inventory_id in affected_inventory:
            # Recalculate totals from itembatch table
            batch_totals = db.session.query(
                db.func.sum(ItemBatch.usable_qty).label('total_usable'),
                db.func.sum(ItemBatch.reserved_qty).label('total_reserved')
            ).filter(
                ItemBatch.item_id == item_id,
                ItemBatch.inventory_id == inventory_id
            ).first()
            
            # Get the inventory record (with lock for update)
            inventory = Inventory.query.filter_by(
                item_id=item_id,
                inventory_id=inventory_id
            ).with_for_update().first()
            
            if inventory:
                # Update inventory totals based on batch sums
                # Use coalesce to handle NULL (when all batches are deleted)
                inventory.usable_qty = batch_totals.total_usable if batch_totals.total_usable is not None else Decimal('0')
                inventory.reserved_qty = batch_totals.total_reserved if batch_totals.total_reserved is not None else Decimal('0')
        
        return True, ''
        
    except SQLAlchemyError as e:
        db.session.rollback()
        return False, f'Database error during commit: {str(e)}'


def cancel_relief_package(reliefpkg_id: int, current_user_name: str) -> Tuple[bool, str]:
    """
    Cancel a relief package and fully reverse all reservations with optimistic locking.
    
    This function:
    1. Validates the package exists and can be cancelled
    2. Retrieves all ReliefPkgItem allocations for this package
    3. Releases batch-level reservations (itembatch.reserved_qty) with optimistic locking
    4. Releases warehouse-level reservations (inventory.reserved_qty) with optimistic locking
    5. Deletes all ReliefPkgItem records
    6. Deletes the ReliefPkg record
    
    All operations are performed in a single transaction (all-or-nothing).
    
    Optimistic Locking:
    - Uses version_nbr on both itembatch and inventory tables
    - If any version mismatch occurs, the entire cancellation is rolled back
    
    Validation:
    - Ensures reserved_qty >= allocated_qty before decrementing
    - Ensures reserved_qty >= 0 after decrementing
    - On any validation failure, rolls back the entire transaction
    
    Args:
        reliefpkg_id: ID of the relief package to cancel
        current_user_name: Username of the current user (for audit trail)
    
    Returns:
        (success: bool, error_message: str)
        - success=True with empty error_message on successful cancellation
        - success=False with descriptive error_message on failure
    
    Usage:
        success, error = cancel_relief_package(123, 'admin')
        if not success:
            flash(error, 'danger')
            return redirect(...)
        flash('Package cancelled successfully', 'success')
    """
    try:
        from app.db.models import ReliefPkg, User, Warehouse
        from app.utils.timezone import now as jamaica_now
        
        # Get the relief package with lock
        relief_pkg = ReliefPkg.query.filter_by(reliefpkg_id=reliefpkg_id).with_for_update().first()
        
        if not relief_pkg:
            return False, f'Relief package #{reliefpkg_id} not found'
        
        # Validation: Only Pending (P) or Dispatched (D) packages can be cancelled
        # Completed (C) packages cannot be cancelled as they've been received
        if relief_pkg.status_code not in ('P', 'D'):
            status_names = {'P': 'Pending', 'D': 'Dispatched', 'C': 'Completed', 
                          'V': 'Verified', 'R': 'Received', 'A': 'Draft'}
            current_status = status_names.get(relief_pkg.status_code, relief_pkg.status_code)
            return False, f'Cannot cancel package with status: {current_status}. Only Pending or Dispatched packages can be cancelled.'
        
        # Get all package items (allocations) for this package
        pkg_items = ReliefPkgItem.query.filter_by(reliefpkg_id=reliefpkg_id).all()
        
        if not pkg_items:
            # No allocations to cancel - can safely delete the empty package
            db.session.delete(relief_pkg)
            return True, ''
        
        # Track affected (item_id, inventory_id) pairs for inventory-level recalculation
        affected_inventory = set()
        
        # Track batch version numbers for optimistic locking
        batch_versions = {}
        
        # PHASE 1: Release batch-level reservations (itembatch.reserved_qty)
        for pkg_item in pkg_items:
            item_id = pkg_item.item_id
            inventory_id = pkg_item.fr_inventory_id
            batch_id = pkg_item.batch_id
            reserved_for_pkg = pkg_item.item_qty
            
            if reserved_for_pkg <= 0:
                continue
            
            # Get the batch with optimistic lock
            batch = ItemBatch.query.filter_by(
                batch_id=batch_id,
                item_id=item_id,
                inventory_id=inventory_id
            ).with_for_update().first()
            
            if not batch:
                # Batch was deleted after package creation - log and continue
                # (reservations will be recalculated at inventory level)
                from flask import current_app
                current_app.logger.warning(
                    f'Batch not found during cancellation: '
                    f'batch_id={batch_id}, item_id={item_id}, inventory_id={inventory_id}'
                )
                affected_inventory.add((item_id, inventory_id))
                continue
            
            # Store original version for optimistic locking check
            original_version = batch.version_nbr
            batch_versions[(batch_id, item_id, inventory_id)] = original_version
            
            # VALIDATION: Ensure reserved_qty >= reserved_for_pkg (data consistency check)
            if batch.reserved_qty < reserved_for_pkg:
                from app.db.models import Warehouse, Item
                warehouse = Warehouse.query.get(inventory_id)
                item = Item.query.get(item_id)
                warehouse_name = warehouse.warehouse_name if warehouse else f'ID {inventory_id}'
                item_name = item.item_name if item else f'ID {item_id}'
                
                db.session.rollback()
                return False, (
                    f'Cancellation failed: Inconsistent reservation data detected. '
                    f'Batch {batch_id} for {item_name} at {warehouse_name} has reserved_qty={batch.reserved_qty}, '
                    f'but package allocated {reserved_for_pkg}. Please contact system administrator.'
                )
            
            # Release reservation from batch
            batch.reserved_qty -= reserved_for_pkg
            
            # VALIDATION: Ensure reserved_qty >= 0 after decrement
            if batch.reserved_qty < 0:
                db.session.rollback()
                return False, (
                    f'Cancellation failed: Batch reserved_qty would become negative. '
                    f'Please contact system administrator.'
                )
            
            # Update audit fields and increment version_nbr for optimistic locking
            batch.update_by_id = current_user_name
            batch.update_dtime = jamaica_now()
            batch.version_nbr += 1
            
            # Track this inventory for warehouse-level recalculation
            affected_inventory.add((item_id, inventory_id))
        
        # PHASE 2: Release warehouse-level reservations (inventory.reserved_qty)
        # Recalculate from SUM(itembatch.reserved_qty) to ensure consistency
        inventory_versions = {}
        
        for item_id, inventory_id in affected_inventory:
            # Sum all batch reservations for this item+warehouse
            batch_totals = db.session.query(
                func.sum(ItemBatch.reserved_qty).label('total_reserved')
            ).filter(
                ItemBatch.item_id == item_id,
                ItemBatch.inventory_id == inventory_id
            ).first()
            
            # Get the inventory record with optimistic lock
            inventory = Inventory.query.filter_by(
                item_id=item_id,
                inventory_id=inventory_id
            ).with_for_update().first()
            
            if not inventory:
                db.session.rollback()
                return False, f'Inventory record not found for item {item_id} at warehouse {inventory_id}'
            
            # Store original version for optimistic locking
            original_version = inventory.version_nbr
            inventory_versions[(item_id, inventory_id)] = original_version
            
            # Calculate new warehouse-level reserved_qty from batch sums
            new_reserved_qty = batch_totals.total_reserved if batch_totals.total_reserved is not None else Decimal('0')
            
            # VALIDATION: Ensure new reserved_qty >= 0
            if new_reserved_qty < 0:
                db.session.rollback()
                return False, (
                    f'Cancellation failed: Inventory reserved_qty would become negative '
                    f'for item {item_id} at warehouse {inventory_id}. '
                    f'Please contact system administrator.'
                )
            
            # Update inventory reserved_qty
            inventory.reserved_qty = new_reserved_qty
            
            # Update audit fields and increment version_nbr for optimistic locking
            inventory.update_by_id = current_user_name
            inventory.update_dtime = jamaica_now()
            inventory.version_nbr += 1
        
        # PHASE 3: Delete package items and package
        # Delete all ReliefPkgItem records
        for pkg_item in pkg_items:
            db.session.delete(pkg_item)
        
        # Delete the ReliefPkg record
        db.session.delete(relief_pkg)
        
        # Transaction will be committed by caller
        return True, ''
        
    except SQLAlchemyError as e:
        db.session.rollback()
        
        # Check if this was an optimistic locking failure (StaleDataError)
        from sqlalchemy.orm.exc import StaleDataError
        error_str = str(e)
        
        if isinstance(e, StaleDataError) or 'stale' in error_str.lower() or 'version' in error_str.lower() or 'concurrent' in error_str.lower():
            return False, (
                'This package or its inventory was updated by another user. '
                'Please refresh the page and try again.'
            )
        
        from flask import current_app
        current_app.logger.error('Database error during package cancellation: %s', sanitize_exception_for_log(e), exc_info=True)
        
        return False, (
            'Cancellation failed due to a database error. '
            'Please contact system administrator if this persists.'
        )
    
    except Exception as e:
        db.session.rollback()
        
        from flask import current_app
        current_app.logger.error('Unexpected error during package cancellation: %s', sanitize_exception_for_log(e), exc_info=True)
        
        return False, (
            'An unexpected error occurred during cancellation. '
            'Please contact system administrator if this persists.'
        )
