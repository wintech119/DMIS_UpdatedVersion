"""
Item Status Service
Handles relief request item status validation and allowed status computation
"""
from decimal import Decimal
from typing import Dict, List, Tuple
from app.db import db
from app.db.models import ReliefRqstItemStatus

# Cache for active status lookup
_status_cache = None

def clear_status_cache():
    """Clear the status cache to force reload from database"""
    global _status_cache
    _status_cache = None

def load_status_map(force_reload: bool = False) -> Dict[str, Dict[str, str]]:
    """
    Load and cache active relief request item statuses
    
    Args:
        force_reload: If True, clears cache and reloads from database
    
    Returns: {status_code: {'desc': str, 'qty_rule': str}}
    """
    global _status_cache
    
    if force_reload:
        clear_status_cache()
    
    if _status_cache is None:
        statuses = ReliefRqstItemStatus.query.filter_by(active_flag=True).all()
        _status_cache = {
            s.status_code: {
                'desc': s.status_desc,
                'qty_rule': s.item_qty_rule
            }
            for s in statuses
        }
    
    return _status_cache

def compute_allowed_statuses(
    current_status: str, 
    total_allocated: Decimal, 
    requested_qty: Decimal,
    has_allocation_activity: bool = False
) -> Tuple[str, List[str]]:
    """
    Compute allowed status options based on allocation state and allocation activity history.
    
    Args:
        current_status: Current item status code
        total_allocated: Total quantity allocated across all warehouses
        requested_qty: Requested quantity for the item
        has_allocation_activity: True if drawer has been opened/saved for this item
    
    Returns:
        Tuple of (auto_status, allowed_status_codes)
        - auto_status: Automatically determined status based on allocation
        - allowed_status_codes: List of status codes that can be manually selected
    
    Rules:
        1. Initial Load (has_allocation_activity=False, allocated==0):
           - auto='R' (REQUESTED), allowed=['R', 'U', 'D', 'W']
        
        2. After Allocation Activity (has_allocation_activity=True, allocated==0):
           - auto='U' (UNAVAILABLE), allowed=['U', 'D', 'W']
           - REQUESTED no longer available
        
        3. Fully Allocated (allocated==requested):
           - auto='F' (FILLED), allowed=['F']
           - Dropdown is locked (read-only)
        
        4. Partially Allocated (0<allocated<requested):
           - auto='P' (PARTLY FILLED), allowed=['P', 'L']
    """
    status_map = load_status_map()
    
    # Determine auto status and allowed statuses based on allocation
    if total_allocated == Decimal('0'):
        if not has_allocation_activity:
            # Case 1: Initial Load - No allocation activity yet
            auto_status = 'R'  # REQUESTED
            allowed_statuses = ['R', 'U', 'D', 'W']
        else:
            # Case 2: After allocation activity with zero allocation
            auto_status = 'U'  # UNAVAILABLE
            allowed_statuses = ['U', 'D', 'W']  # No REQUESTED anymore
    elif total_allocated == requested_qty:
        # Case 3: Fully Allocated
        auto_status = 'F'  # FILLED
        allowed_statuses = ['F']  # Locked to FILLED only
    elif total_allocated < requested_qty:
        # Case 4: Partially Allocated
        auto_status = 'P'  # PARTLY FILLED
        allowed_statuses = ['P', 'L']  # PARTLY FILLED or ALLOWED LIMIT
    else:
        # Over-allocated (should not normally happen, but handle gracefully)
        auto_status = 'F'  # FILLED
        allowed_statuses = ['F']
    
    # Filter to only active statuses that exist in the database
    allowed_statuses = [s for s in allowed_statuses if s in status_map]
    
    return auto_status, allowed_statuses

def validate_status_transition(
    item_id: int,
    current_status: str,
    new_status: str,
    total_allocated: Decimal,
    requested_qty: Decimal,
    has_allocation_activity: bool = False
) -> Tuple[bool, str]:
    """
    Validate if a status transition is allowed based on allocation state.
    
    Args:
        item_id: The item ID being validated
        current_status: Current status code
        new_status: Requested new status code
        total_allocated: Total quantity allocated
        requested_qty: Requested quantity
        has_allocation_activity: Whether the batch drawer has been opened/used for this item
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    # Allow no-op transitions (status staying the same)
    if current_status == new_status:
        return True, ""
    
    auto_status, allowed_statuses = compute_allowed_statuses(
        current_status, total_allocated, requested_qty, has_allocation_activity
    )
    
    if new_status not in allowed_statuses:
        status_map = load_status_map()
        current_desc = status_map.get(current_status, {}).get('desc', current_status)
        new_desc = status_map.get(new_status, {}).get('desc', new_status)
        
        # Build friendly list of allowed status names
        allowed_names = [status_map.get(s, {}).get('desc', s) for s in allowed_statuses]
        allowed_str = ', '.join(allowed_names)
        
        if total_allocated == Decimal('0'):
            return False, f"Item #{item_id}: With zero allocation, status must be one of: {allowed_str} (not {new_desc})"
        elif total_allocated >= requested_qty:
            return False, f"Item #{item_id}: Fully allocated items must be: {allowed_str} (not {new_desc})"
        else:
            return False, f"Item #{item_id}: Partially allocated items must be: {allowed_str} (not {new_desc})"
    
    return True, ""

def validate_quantity_limit(
    item_id: int,
    total_allocated: Decimal,
    requested_qty: Decimal
) -> Tuple[bool, str]:
    """
    Validate that total allocation does not exceed requested quantity.
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if total_allocated > requested_qty:
        return False, f"Item #{item_id}: Total allocated ({total_allocated}) exceeds requested quantity ({requested_qty})"
    
    return True, ""

def get_status_label(status_code: str) -> str:
    """Get human-readable label for a status code"""
    status_map = load_status_map()
    return status_map.get(status_code, {}).get('desc', status_code)
