"""
Dispatch Service - Workflow C: LM Submit for Dispatch

Handles the final dispatch operation when Logistics Manager submits a package for dispatch.
This service implements the complete Workflow C algorithm:

1. Undo LO reservations (from reliefpkg_item) in itembatch and inventory
2. Overwrite reliefpkg_item with LM's final plan
3. Deplete usable stock in itembatch and inventory based on LM plan
4. Update reliefpkg header status to Dispatched
5. Update reliefrqst_item.issue_qty with actual dispatched quantities

All operations execute in ONE atomic transaction with optimistic locking.
On any failure, the entire transaction is rolled back.

IMPORTANT: This module does NOT modify Workflow A or B. It only handles
the final dispatch step when LM clicks "Submit for Dispatch".
"""

from decimal import Decimal
from typing import List, Dict, Tuple, Optional
from collections import defaultdict
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import func

from app.db import db
from app.security.log_sanitizer import sanitize_for_log, sanitize_exception_for_log
from app.db.models import (
    ReliefPkg, ReliefPkgItem, ItemBatch, Inventory, 
    ReliefRqst, ReliefRqstItem
)
from app.utils.timezone import now as jamaica_now
from app.services import relief_request_service as rr_service


class DispatchError(Exception):
    """Raised when dispatch operation fails"""
    pass


class OptimisticLockError(Exception):
    """Raised when version_nbr mismatch detected"""
    pass


class InsufficientStockError(Exception):
    """Raised when usable stock is insufficient for dispatch"""
    pass


def submit_for_dispatch(
    reliefpkg_id: int,
    lm_plan: List[Dict],
    user_id: str,
    package_version_nbr: int
) -> Tuple[bool, str]:
    """
    Execute Workflow C: LM Submit for Dispatch.
    
    This is the main entry point for the dispatch workflow. It performs
    all operations in one atomic transaction with optimistic locking.
    
    Args:
        reliefpkg_id: The package ID being dispatched
        lm_plan: List of dicts with LM's final allocations:
            [
                {
                    "fr_inventory_id": warehouse_id,
                    "batch_id": batch_id,
                    "item_id": item_id,
                    "lm_qty": Decimal quantity to dispatch,
                    "uom_code": UOM code
                },
                ...
            ]
        user_id: The LM user performing the dispatch
        package_version_nbr: Expected version_nbr for optimistic locking
        
    Returns:
        Tuple of (success: bool, message: str)
        
    Raises:
        DispatchError: On validation or business logic failure
        OptimisticLockError: On version mismatch
        InsufficientStockError: On insufficient usable stock
    """
    try:
        # Step 0: Validate and lock the package
        package = ReliefPkg.query.filter_by(reliefpkg_id=reliefpkg_id).with_for_update().first()
        
        if not package:
            return False, f"Package #{reliefpkg_id} not found"
            
        if package.version_nbr != package_version_nbr:
            return False, "Package has been modified. Please refresh and try again."
            
        if package.status_code == rr_service.PKG_STATUS_DISPATCHED:
            return False, "Package has already been dispatched."
            
        if package.status_code not in ('P', 'V'):
            return False, f"Package cannot be dispatched from status '{package.status_code}'"
        
        # Get the relief request for updating issue_qty
        relief_request = ReliefRqst.query.filter_by(
            reliefrqst_id=package.reliefrqst_id
        ).with_for_update().first()
        
        if not relief_request:
            return False, "Relief request not found"
            
        # Step C.3.2: Retrieve LO quantities from reliefpkg_item
        lo_plan = _get_lo_plan(reliefpkg_id)
        
        # Step C.3.3: Undo LO reservations
        success, error_msg = _undo_lo_reservations(lo_plan, user_id)
        if not success:
            return False, error_msg
            
        # Step C.3.4: Overwrite reliefpkg_item with LM final plan
        success, error_msg = _overwrite_package_items(
            reliefpkg_id, lm_plan, lo_plan, user_id
        )
        if not success:
            return False, error_msg
            
        # Step C.3.5: Deplete usable stock using LM_PLAN
        success, error_msg = _deplete_usable_stock(lm_plan, user_id)
        if not success:
            return False, error_msg
            
        # Step C.3.6: Update reliefpkg header and reliefrqst_item
        success, error_msg = _update_dispatch_records(
            package, relief_request, lm_plan, user_id
        )
        if not success:
            return False, error_msg
            
        return True, f"Package #{reliefpkg_id} successfully submitted for dispatch"
        
    except (DispatchError, OptimisticLockError, InsufficientStockError) as e:
        db.session.rollback()
        return False, str(e)
    except SQLAlchemyError as e:
        db.session.rollback()
        import logging
        logger = logging.getLogger(__name__)
        logger.error(
            "Database error during dispatch for package %s: %s",
            sanitize_for_log(reliefpkg_id),
            sanitize_exception_for_log(e)
        )
        return False, "A system error occurred during dispatch. Please try again or contact support."
    except Exception as e:
        db.session.rollback()
        import logging
        logger = logging.getLogger(__name__)
        logger.error(
            "Unexpected error during dispatch for package %s: %s",
            sanitize_for_log(reliefpkg_id),
            sanitize_exception_for_log(e)
        )
        return False, "An unexpected error occurred. Please try again or contact support."


def _get_lo_plan(reliefpkg_id: int) -> Dict[Tuple[int, int, int], Dict]:
    """
    Step C.3.2: Retrieve LO quantities from reliefpkg_item.
    
    Returns:
        Dict keyed by (fr_inventory_id, batch_id, item_id) with values:
        {
            "lo_qty": Decimal,
            "uom_code": str,
            "version_nbr": int
        }
    """
    lo_plan = {}
    
    pkg_items = ReliefPkgItem.query.filter_by(reliefpkg_id=reliefpkg_id).all()
    
    for item in pkg_items:
        key = (item.fr_inventory_id, item.batch_id, item.item_id)
        lo_plan[key] = {
            "lo_qty": item.item_qty or Decimal('0'),
            "uom_code": item.uom_code,
            "version_nbr": item.version_nbr
        }
        
    return lo_plan


def _undo_lo_reservations(lo_plan: Dict, user_id: str) -> Tuple[bool, str]:
    """
    Step C.3.3: Undo LO reservations using LO_PLAN.
    
    For each entry in LO_PLAN with lo_qty > 0:
    1. Decrement itembatch.reserved_qty by lo_qty
    2. Decrement inventory.reserved_qty by total lo_qty per (inventory_id, item_id)
    
    Uses optimistic locking on all updates.
    """
    now = jamaica_now()
    
    # Track totals per (inventory_id, item_id) for inventory table update
    inventory_totals = defaultdict(Decimal)
    
    # Process each batch in LO_PLAN
    for (inv_id, batch_id, item_id), plan_data in lo_plan.items():
        lo_qty = plan_data["lo_qty"]
        
        if lo_qty <= 0:
            continue
            
        # Lock and update itembatch
        batch = ItemBatch.query.filter_by(
            inventory_id=inv_id,
            batch_id=batch_id,
            item_id=item_id
        ).with_for_update().first()
        
        if not batch:
            return False, f"Batch {batch_id} not found for item {item_id} at warehouse {inv_id}"
            
        # Validate: reserved_qty >= lo_qty
        if batch.reserved_qty < lo_qty:
            return False, (
                f"Inconsistent reservation state: batch {batch_id} has reserved_qty "
                f"{batch.reserved_qty} but LO allocated {lo_qty}. "
                "Stock may have changed. Please refresh and try again."
            )
            
        # Update batch reserved_qty
        expected_version = batch.version_nbr
        batch.reserved_qty = batch.reserved_qty - lo_qty
        batch.update_by_id = user_id
        batch.update_dtime = now
        batch.version_nbr = expected_version + 1
        
        # Track for inventory update
        inventory_totals[(inv_id, item_id)] += lo_qty
        
    # Update inventory.reserved_qty for each (inventory_id, item_id)
    for (inv_id, item_id), total_lo_qty in inventory_totals.items():
        inventory = Inventory.query.filter_by(
            inventory_id=inv_id,
            item_id=item_id
        ).with_for_update().first()
        
        if not inventory:
            return False, f"Inventory record not found for item {item_id} at warehouse {inv_id}"
            
        if inventory.reserved_qty < total_lo_qty:
            return False, (
                f"Inconsistent inventory reservation: warehouse {inv_id} has "
                f"reserved_qty {inventory.reserved_qty} but need to release {total_lo_qty}"
            )
            
        expected_version = inventory.version_nbr
        inventory.reserved_qty = inventory.reserved_qty - total_lo_qty
        inventory.update_by_id = user_id
        inventory.update_dtime = now
        inventory.version_nbr = expected_version + 1
        
    return True, ""


def _overwrite_package_items(
    reliefpkg_id: int,
    lm_plan: List[Dict],
    lo_plan: Dict[Tuple[int, int, int], Dict],
    user_id: str
) -> Tuple[bool, str]:
    """
    Step C.3.4: Overwrite reliefpkg_item with LM final plan.
    
    - Update existing rows with LM quantities
    - Insert new rows for batches not in LO plan
    - Set item_qty = 0 for LO rows not in LM plan (preserve history)
    """
    now = jamaica_now()
    
    # Build set of keys in LM plan for comparison
    lm_keys = set()
    for alloc in lm_plan:
        key = (alloc["fr_inventory_id"], alloc["batch_id"], alloc["item_id"])
        lm_keys.add(key)
        
        existing = ReliefPkgItem.query.filter_by(
            reliefpkg_id=reliefpkg_id,
            fr_inventory_id=alloc["fr_inventory_id"],
            batch_id=alloc["batch_id"],
            item_id=alloc["item_id"]
        ).first()
        
        lm_qty = Decimal(str(alloc["lm_qty"])) if alloc["lm_qty"] else Decimal('0')
        
        if existing:
            # Update existing row
            existing.item_qty = lm_qty
            existing.uom_code = alloc["uom_code"]
            existing.update_by_id = user_id
            existing.update_dtime = now
            existing.version_nbr = existing.version_nbr + 1
        else:
            # Insert new row
            new_item = ReliefPkgItem(
                reliefpkg_id=reliefpkg_id,
                fr_inventory_id=alloc["fr_inventory_id"],
                batch_id=alloc["batch_id"],
                item_id=alloc["item_id"],
                item_qty=lm_qty,
                uom_code=alloc["uom_code"],
                create_by_id=user_id,
                create_dtime=now,
                update_by_id=user_id,
                update_dtime=now,
                version_nbr=1
            )
            db.session.add(new_item)
            
    # Set item_qty = 0 for LO rows not in LM plan (preserve history)
    for lo_key in lo_plan.keys():
        if lo_key not in lm_keys:
            inv_id, batch_id, item_id = lo_key
            existing = ReliefPkgItem.query.filter_by(
                reliefpkg_id=reliefpkg_id,
                fr_inventory_id=inv_id,
                batch_id=batch_id,
                item_id=item_id
            ).first()
            
            if existing and existing.item_qty > 0:
                existing.item_qty = Decimal('0')
                existing.update_by_id = user_id
                existing.update_dtime = now
                existing.version_nbr = existing.version_nbr + 1
                
    return True, ""


def _deplete_usable_stock(lm_plan: List[Dict], user_id: str) -> Tuple[bool, str]:
    """
    Step C.3.5: Deplete usable stock using LM_PLAN.
    
    For each entry in LM_PLAN with lm_qty > 0:
    1. Decrement itembatch.usable_qty by lm_qty
    2. Decrement inventory.usable_qty by total lm_qty per (inventory_id, item_id)
    
    Validates sufficient usable stock before deduction.
    """
    now = jamaica_now()
    
    # Track totals per (inventory_id, item_id) for inventory table update
    inventory_totals = defaultdict(Decimal)
    
    # Process each allocation in LM_PLAN
    for alloc in lm_plan:
        lm_qty = Decimal(str(alloc["lm_qty"])) if alloc["lm_qty"] else Decimal('0')
        
        if lm_qty <= 0:
            continue
            
        inv_id = alloc["fr_inventory_id"]
        batch_id = alloc["batch_id"]
        item_id = alloc["item_id"]
        
        # Lock and update itembatch
        batch = ItemBatch.query.filter_by(
            inventory_id=inv_id,
            batch_id=batch_id,
            item_id=item_id
        ).with_for_update().first()
        
        if not batch:
            return False, f"Batch {batch_id} not found for item {item_id} at warehouse {inv_id}"
            
        # Validate: usable_qty >= lm_qty
        if batch.usable_qty < lm_qty:
            from app.db.models import Warehouse, Item
            warehouse = Warehouse.query.get(inv_id)
            item = Item.query.get(item_id)
            warehouse_name = warehouse.warehouse_name if warehouse else f"ID {inv_id}"
            item_name = item.item_name if item else f"ID {item_id}"
            
            return False, (
                f"Insufficient usable stock for {item_name} in {warehouse_name}: "
                f"need {lm_qty}, available {batch.usable_qty}. "
                "Please adjust quantities and try again."
            )
            
        # Update batch usable_qty
        expected_version = batch.version_nbr
        batch.usable_qty = batch.usable_qty - lm_qty
        batch.update_by_id = user_id
        batch.update_dtime = now
        batch.version_nbr = expected_version + 1
        
        # Track for inventory update
        inventory_totals[(inv_id, item_id)] += lm_qty
        
    # Update inventory.usable_qty for each (inventory_id, item_id)
    for (inv_id, item_id), total_lm_qty in inventory_totals.items():
        inventory = Inventory.query.filter_by(
            inventory_id=inv_id,
            item_id=item_id
        ).with_for_update().first()
        
        if not inventory:
            return False, f"Inventory record not found for item {item_id} at warehouse {inv_id}"
            
        if inventory.usable_qty < total_lm_qty:
            from app.db.models import Warehouse, Item
            warehouse = Warehouse.query.get(inv_id)
            item = Item.query.get(item_id)
            warehouse_name = warehouse.warehouse_name if warehouse else f"ID {inv_id}"
            item_name = item.item_name if item else f"ID {item_id}"
            
            return False, (
                f"Insufficient warehouse inventory for {item_name} in {warehouse_name}: "
                f"need {total_lm_qty}, available {inventory.usable_qty}"
            )
            
        expected_version = inventory.version_nbr
        inventory.usable_qty = inventory.usable_qty - total_lm_qty
        inventory.update_by_id = user_id
        inventory.update_dtime = now
        inventory.version_nbr = expected_version + 1
        
    return True, ""


def _update_dispatch_records(
    package: ReliefPkg,
    relief_request: ReliefRqst,
    lm_plan: List[Dict],
    user_id: str
) -> Tuple[bool, str]:
    """
    Step C.3.6: Update reliefpkg header and reliefrqst_item.issue_qty.
    
    1. Set package status to Dispatched with dispatch_dtime
    2. Update reliefrqst_item.issue_qty for each item
    """
    now = jamaica_now()
    
    # Update package header
    package.status_code = rr_service.PKG_STATUS_DISPATCHED
    package.dispatch_dtime = now
    package.verify_by_id = user_id
    package.verify_dtime = now
    package.update_by_id = user_id
    package.update_dtime = now
    package.version_nbr = package.version_nbr + 1
    
    # Calculate total dispatched per item_id from LM_PLAN
    item_totals = defaultdict(Decimal)
    for alloc in lm_plan:
        lm_qty = Decimal(str(alloc["lm_qty"])) if alloc["lm_qty"] else Decimal('0')
        if lm_qty > 0:
            item_totals[alloc["item_id"]] += lm_qty
            
    # Update reliefrqst_item.issue_qty for each item
    for item_id, dispatched_qty in item_totals.items():
        rqst_item = ReliefRqstItem.query.filter_by(
            reliefrqst_id=relief_request.reliefrqst_id,
            item_id=item_id
        ).with_for_update().first()
        
        if rqst_item:
            # Add to existing issue_qty (supports multiple packages)
            current_issue = rqst_item.issue_qty or Decimal('0')
            rqst_item.issue_qty = current_issue + dispatched_qty
            rqst_item.update_by_id = user_id
            rqst_item.update_dtime = now
            rqst_item.version_nbr = rqst_item.version_nbr + 1
            
    # Update relief request status and action tracking
    relief_request.action_by_id = user_id
    relief_request.action_dtime = now
    relief_request.status_code = rr_service.STATUS_PART_FILLED
    relief_request.version_nbr = relief_request.version_nbr + 1
    
    return True, ""


def build_lm_plan_from_form(form_data: Dict, reliefpkg_id: int) -> List[Dict]:
    """
    Build LM_PLAN array from form/JSON submission data.
    
    Expected form_data structure:
    {
        "allocations": [
            {
                "fr_inventory_id": int,
                "batch_id": int,
                "item_id": int,
                "quantity": float/Decimal,
                "uom_code": str
            },
            ...
        ]
    }
    
    Returns:
        List of dicts matching LM_PLAN structure for submit_for_dispatch()
    """
    lm_plan = []
    
    allocations = form_data.get("allocations", [])
    
    for alloc in allocations:
        qty = alloc.get("quantity", 0)
        
        # Only include non-zero allocations
        if qty and Decimal(str(qty)) > 0:
            lm_plan.append({
                "fr_inventory_id": int(alloc["fr_inventory_id"]),
                "batch_id": int(alloc["batch_id"]),
                "item_id": int(alloc["item_id"]),
                "lm_qty": Decimal(str(qty)),
                "uom_code": alloc.get("uom_code", "")
            })
            
    return lm_plan


def build_lm_plan_from_pkg_items(reliefpkg_id: int) -> List[Dict]:
    """
    Build LM_PLAN from current reliefpkg_item records.
    
    Used when LM approves without modifications - uses existing allocations.
    
    Returns:
        List of dicts matching LM_PLAN structure for submit_for_dispatch()
    """
    lm_plan = []
    
    pkg_items = ReliefPkgItem.query.filter_by(reliefpkg_id=reliefpkg_id).all()
    
    for item in pkg_items:
        if item.item_qty and item.item_qty > 0:
            lm_plan.append({
                "fr_inventory_id": item.fr_inventory_id,
                "batch_id": item.batch_id,
                "item_id": item.item_id,
                "lm_qty": item.item_qty,
                "uom_code": item.uom_code
            })
            
    return lm_plan
