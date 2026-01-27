"""
Batch Allocation Service - FEFO/FIFO allocation logic for relief packages

Supports First Expired First Out (FEFO) for expirable items and
First In First Out (FIFO) for non-expirable items based on item configuration.
"""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import List, Dict, Tuple, Optional
from sqlalchemy import and_, or_
from sqlalchemy.orm import joinedload

from app.db import db
from app.db.models import Item, ItemBatch, Inventory, Warehouse


def safe_decimal(value, default=Decimal("0")):
    """
    Safely convert a value to Decimal, handling None, empty strings, NaN, and invalid values.
    
    Args:
        value: The value to convert (can be None, Decimal, int, float, str)
        default: The default value to return if conversion fails (default: Decimal("0"))
        
    Returns:
        Decimal value or the default if conversion fails
    """
    if value is None:
        return default
    if isinstance(value, Decimal):
        # Check if Decimal is NaN or Infinite
        if value.is_nan() or value.is_infinite():
            return default
        return value
    # Check for float NaN
    if isinstance(value, float):
        import math
        if math.isnan(value) or math.isinf(value):
            return default
    # Check for string "nan" or "inf"
    if isinstance(value, str):
        lower_val = value.lower().strip()
        if lower_val in ('nan', 'inf', '-inf', 'infinity', '-infinity'):
            return default
    try:
        result = Decimal(str(value))
        # Double-check the result isn't NaN or Inf
        if result.is_nan() or result.is_infinite():
            return default
        return result
    except (InvalidOperation, ValueError, TypeError):
        # Log for debugging if needed
        # import logging
        # logging.warning(f"safe_decimal: Invalid value '{value}', using default {default}")
        return default


class BatchAllocationService:
    """Service for managing batch-level allocations with FEFO/FIFO rules"""
    
    @staticmethod
    def get_available_batches(item_id: int, warehouse_id: int = None, required_uom: str = None) -> List[ItemBatch]:
        """
        Get available batches for an item, optionally filtered by warehouse and UOM.
        
        Args:
            item_id: Item to get batches for
            warehouse_id: Optional warehouse filter
            required_uom: Optional UOM filter (matches request UOM)
            
        Returns:
            List of ItemBatch objects with available quantity > 0
        """
        query = ItemBatch.query.options(
            joinedload(ItemBatch.inventory).joinedload(Inventory.warehouse),
            joinedload(ItemBatch.item),
            joinedload(ItemBatch.uom)
        ).join(
            Inventory,
            and_(
                ItemBatch.inventory_id == Inventory.inventory_id,
                ItemBatch.item_id == Inventory.item_id
            )
        ).join(
            Warehouse,
            Inventory.inventory_id == Warehouse.warehouse_id
        ).filter(
            ItemBatch.item_id == item_id,
            ItemBatch.status_code == 'A',
            Inventory.status_code == 'A',
            Warehouse.status_code == 'A',
            ItemBatch.usable_qty > ItemBatch.reserved_qty
        )
        
        if warehouse_id:
            query = query.filter(Inventory.inventory_id == warehouse_id)
        
        if required_uom:
            query = query.filter(ItemBatch.uom_code == required_uom)
        
        return query.all()
    
    @staticmethod
    def sort_batches_for_drawer(batches: List[ItemBatch], item: Item, allocated_batch_ids: set = None) -> List[ItemBatch]:
        """
        Sort batches for drawer display based ONLY on can_expire_flag.
        Ignores item.issuance_order field to ensure consistent FEFO/FIFO behavior.
        
        Drawer Sorting Rules (per warehouse):
        - If can_expire_flag = TRUE: Sort by earliest expiry_date, then oldest batch_date
        - If can_expire_flag = FALSE: Sort by oldest batch_date (FIFO)
        
        Args:
            batches: List of batches to sort (already filtered for available qty > 0)
            item: Item object with can_expire_flag
            allocated_batch_ids: Set of batch IDs that are allocated (must be preserved even if available <= 0)
            
        Returns:
            Sorted list of batches
        """
        today = date.today()
        allocated_batch_ids = allocated_batch_ids or set()
        
        # Filter out expired batches if item can expire
        # NULL expiry dates are treated as "never expires" and are allowed
        if item.can_expire_flag:
            active_batches = [
                b for b in batches 
                if not b.expiry_date or b.expiry_date >= today
            ]
        else:
            active_batches = batches
        
        # Filter out batches with zero available quantity
        # EXCEPT allocated batches which MUST be shown to LM for editing
        active_batches = [
            b for b in active_batches 
            if (safe_decimal(b.usable_qty) - safe_decimal(b.reserved_qty)) > 0 
            or b.batch_id in allocated_batch_ids
        ]
        
        # Sort based ONLY on can_expire_flag (ignore issuance_order)
        if item.can_expire_flag:
            # FEFO: Sort by earliest expiry date, then oldest batch date
            return sorted(
                active_batches,
                key=lambda b: (
                    b.expiry_date is None,  # NULL expiry dates go to end
                    b.expiry_date if b.expiry_date else date.max, 
                    b.batch_date if b.batch_date else date.max
                )
            )
        else:
            # FIFO: Sort by oldest batch date
            return sorted(
                active_batches, 
                key=lambda b: (
                    b.batch_date if b.batch_date else date.min
                )
            )
    
    @staticmethod
    def sort_batches_by_allocation_rule(batches: List[ItemBatch], item: Item) -> List[ItemBatch]:
        """
        Sort batches according to FEFO/FIFO rules based on item configuration.
        Includes deterministic tie-breaker on usable_qty DESC.
        
        Args:
            batches: List of batches to sort
            item: Item object with issuance_order and can_expire_flag
            
        Returns:
            Sorted list of batches with priority group assignments
        """
        today = date.today()
        
        # Filter out expired batches if item can expire
        # NULL expiry dates are treated as "never expires" and are allowed
        if item.can_expire_flag:
            active_batches = [
                b for b in batches 
                if not b.expiry_date or b.expiry_date >= today
            ]
        else:
            active_batches = batches
        
        # Filter out batches with zero available quantity
        # Only show warehouses/batches that have actual usable stock
        active_batches = [
            b for b in active_batches 
            if (safe_decimal(b.usable_qty) - safe_decimal(b.reserved_qty)) > 0
        ]
        
        # Sort based on issuance order with tie-breakers
        if item.issuance_order == 'FEFO' and item.can_expire_flag:
            # First Expired First Out - sort by earliest expiry date, then batch date, then qty DESC
            return sorted(
                active_batches,
                key=lambda b: (
                    b.expiry_date is None, 
                    b.expiry_date if b.expiry_date else date.max, 
                    b.batch_date if b.batch_date else date.max,
                    -(safe_decimal(b.usable_qty) - safe_decimal(b.reserved_qty))  # Negative for DESC
                )
            )
        elif item.issuance_order == 'LIFO':
            # Last In First Out - sort by latest batch date, then qty DESC
            return sorted(
                active_batches, 
                key=lambda b: (
                    -(b.batch_date.toordinal() if b.batch_date else 0),
                    -(safe_decimal(b.usable_qty) - safe_decimal(b.reserved_qty))
                )
            )
        else:  # FIFO (default)
            # First In First Out - sort by earliest batch date, then qty DESC
            return sorted(
                active_batches, 
                key=lambda b: (
                    b.batch_date if b.batch_date else date.min,
                    -(safe_decimal(b.usable_qty) - safe_decimal(b.reserved_qty))
                )
            )
    
    @staticmethod
    def auto_allocate_batches(
        item_id: int,
        requested_qty: Decimal,
        warehouse_id: int = None
    ) -> List[Dict]:
        """
        Auto-allocate batches for an item following FEFO/FIFO rules.
        
        Args:
            item_id: Item to allocate
            requested_qty: Total quantity to allocate
            warehouse_id: Optional warehouse filter
            
        Returns:
            List of allocation dicts with keys:
                - batch_id: Batch ID
                - batch_no: Batch number
                - warehouse_id: Warehouse ID
                - warehouse_name: Warehouse name
                - inventory_id: Inventory ID
                - batch_date: Batch date
                - expiry_date: Expiry date (if any)
                - available_qty: Available quantity in batch
                - allocated_qty: Quantity allocated from this batch
                - uom_code: Unit of measure
        """
        # Get item to check allocation rules
        item = Item.query.get(item_id)
        if not item:
            return []
        
        # Get available batches
        batches = BatchAllocationService.get_available_batches(item_id, warehouse_id)
        
        # Sort by allocation rule
        sorted_batches = BatchAllocationService.sort_batches_by_allocation_rule(batches, item)
        
        # Allocate quantities
        allocations = []
        remaining_qty = safe_decimal(requested_qty)
        
        for batch in sorted_batches:
            if remaining_qty <= 0:
                break
            
            available_qty = safe_decimal(batch.usable_qty) - safe_decimal(batch.reserved_qty)
            allocated_qty = min(available_qty, remaining_qty)
            
            if allocated_qty > 0:
                allocations.append({
                    'batch_id': batch.batch_id,
                    'batch_no': batch.batch_no,
                    'warehouse_id': batch.inventory.inventory_id,
                    'warehouse_name': batch.inventory.warehouse.warehouse_name,
                    'inventory_id': batch.inventory_id,
                    'batch_date': batch.batch_date,
                    'expiry_date': batch.expiry_date,
                    'available_qty': float(available_qty),
                    'allocated_qty': float(allocated_qty),
                    'uom_code': batch.uom_code,
                    'size_spec': batch.size_spec
                })
                remaining_qty -= allocated_qty
        
        return allocations
    
    @staticmethod
    def get_batch_details(batch_id: int) -> Optional[Dict]:
        """
        Get detailed information about a specific batch.
        
        Args:
            batch_id: Batch ID
            
        Returns:
            Dict with batch details or None if not found
        """
        batch = ItemBatch.query.options(
            joinedload(ItemBatch.inventory).joinedload(Inventory.warehouse),
            joinedload(ItemBatch.item),
            joinedload(ItemBatch.uom)
        ).get(batch_id)
        
        if not batch:
            return None
        
        available_qty = safe_decimal(batch.usable_qty) - safe_decimal(batch.reserved_qty)
        is_expired = batch.expiry_date and batch.expiry_date < date.today() if batch.expiry_date else False
        
        return {
            'batch_id': batch.batch_id,
            'batch_no': batch.batch_no,
            'warehouse_id': batch.inventory.inventory_id,
            'warehouse_name': batch.inventory.warehouse.warehouse_name,
            'inventory_id': batch.inventory_id,
            'item_id': batch.item_id,
            'item_name': batch.item.item_name,
            'batch_date': batch.batch_date,
            'expiry_date': batch.expiry_date,
            'usable_qty': float(safe_decimal(batch.usable_qty)),
            'reserved_qty': float(safe_decimal(batch.reserved_qty)),
            'available_qty': float(available_qty),
            'defective_qty': float(safe_decimal(batch.defective_qty)),
            'expired_qty': float(safe_decimal(batch.expired_qty)),
            'uom_code': batch.uom_code,
            'size_spec': batch.size_spec,
            'status_code': batch.status_code,
            'is_expired': is_expired
        }
    
    @staticmethod
    def validate_batch_allocation(
        batch_id: int,
        item_id: int,
        allocated_qty: Decimal,
        current_allocated_qty: Decimal = Decimal('0')
    ) -> Tuple[bool, str]:
        """
        Validate a batch allocation.
        
        When re-allocating from an existing package, the current package's allocation
        is "released" from reserved_qty to calculate true availability. This allows
        users to modify their existing allocations without false "no inventory" errors.
        
        Args:
            batch_id: Batch ID to allocate from
            item_id: Item being allocated
            allocated_qty: Quantity to allocate
            current_allocated_qty: Current allocation from this package for this batch (default: 0)
                                   This qty is "released" from reserved_qty when calculating availability
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        batch = ItemBatch.query.get(batch_id)
        
        if not batch:
            return False, f'Batch {batch_id} not found'
        
        if batch.item_id != item_id:
            return False, f'Batch {batch_id} does not contain item {item_id}'
        
        if batch.status_code != 'A':
            return False, f'Batch {batch.batch_no} is not available (status: {batch.status_code})'
        
        # Check expiry
        if batch.expiry_date and batch.expiry_date < date.today():
            return False, f'Batch {batch.batch_no} is expired (expiry: {batch.expiry_date})'
        
        # Check quantity
        # CRITICAL: "Release" current package's allocation when calculating availability
        # This prevents false "no inventory" errors when re-allocating from existing packages
        available_qty = safe_decimal(batch.usable_qty) - (safe_decimal(batch.reserved_qty) - current_allocated_qty)
        if allocated_qty > available_qty:
            if available_qty <= 0:
                return False, (f'Batch {batch.batch_no} has no available inventory (all {safe_decimal(batch.usable_qty)} units are reserved or allocated). '
                             f'This may occur if another user allocated from this batch while you were working. '
                             f'Please refresh the page and select a different batch with available stock.')
            else:
                return False, (f'Batch {batch.batch_no} has only {available_qty:.4f} units available, cannot allocate {allocated_qty:.4f}. '
                             f'Please reduce the allocation quantity or select an additional batch.')
        
        if allocated_qty <= 0:
            return False, 'Allocated quantity must be greater than zero'
        
        return True, ''
    
    @staticmethod
    def get_batches_by_warehouse(item_id: int) -> Dict[int, List[ItemBatch]]:
        """
        Get batches grouped by warehouse for an item.
        
        Args:
            item_id: Item ID
            
        Returns:
            Dict mapping warehouse_id to list of batches
        """
        batches = BatchAllocationService.get_available_batches(item_id)
        item = Item.query.get(item_id)
        
        if item:
            batches = BatchAllocationService.sort_batches_by_allocation_rule(batches, item)
        
        warehouse_batches = {}
        for batch in batches:
            wh_id = batch.inventory.inventory_id
            if wh_id not in warehouse_batches:
                warehouse_batches[wh_id] = []
            warehouse_batches[wh_id].append(batch)
        
        return warehouse_batches
    
    @staticmethod
    def get_limited_batches_for_drawer(
        item_id: int,
        remaining_qty: Decimal,
        required_uom: str = None,
        allocated_batch_ids: List[int] = None,
        current_allocations: dict = None
    ) -> Tuple[List[ItemBatch], Decimal, Decimal]:
        """
        Get batches for the drawer display with warehouse-based filtering and sorting.
        
        Warehouse Filtering: Only shows warehouses where total (usable_qty - reserved_qty) > 0.
        Per-Warehouse Sorting: Batches sorted within each warehouse (FEFO if can_expire, else FIFO).
        Early Stopping: For each warehouse, stops loading batches once cumulative quantity 
        meets or exceeds remaining_qty.
        
        Important: When current_allocations is provided, those quantities are "released" from
        reserved_qty when calculating available_qty. This allows LM to re-allocate freely
        when editing existing package allocations.
        
        Args:
            item_id: Item ID
            remaining_qty: Remaining quantity to fulfill
            required_uom: Required unit of measure
            allocated_batch_ids: List of batch IDs that are already allocated (for editing)
            current_allocations: Dict mapping batch_id -> qty for current package's allocations
                                 (these are "released" from reserved_qty when calculating available)
            
        Returns:
            Tuple of:
                - List of batches (limited per warehouse based on remaining_qty)
                - Total available from these batches
                - Shortfall (0 if can fulfill, positive if not)
        """
        # Get item and all available batches
        item = Item.query.get(item_id)
        if not item:
            return [], Decimal('0'), remaining_qty
        
        # Get all available batches (with available qty > 0)
        all_batches = BatchAllocationService.get_available_batches(item_id, required_uom=required_uom)
        allocated_batch_ids_set = set(allocated_batch_ids or [])
        current_allocations = current_allocations or {}
        
        # CRITICAL FIX: Also fetch allocated batches that might have zero available quantity
        # These batches were filtered out by get_available_batches() but MUST be shown to LM
        if allocated_batch_ids_set:
            allocated_batches = ItemBatch.query.options(
                joinedload(ItemBatch.inventory).joinedload(Inventory.warehouse),
                joinedload(ItemBatch.item),
                joinedload(ItemBatch.uom)
            ).join(
                Inventory,
                and_(
                    ItemBatch.inventory_id == Inventory.inventory_id,
                    ItemBatch.item_id == Inventory.item_id
                )
            ).join(
                Warehouse,
                Inventory.inventory_id == Warehouse.warehouse_id
            ).filter(
                ItemBatch.batch_id.in_(list(allocated_batch_ids_set)),
                ItemBatch.item_id == item_id,
                ItemBatch.status_code == 'A',
                Inventory.status_code == 'A',
                Warehouse.status_code == 'A'
            ).all()
            
            # Merge allocated batches with available batches (avoid duplicates)
            existing_batch_ids = {b.batch_id for b in all_batches}
            for allocated_batch in allocated_batches:
                if allocated_batch.batch_id not in existing_batch_ids:
                    all_batches.append(allocated_batch)
        
        # Helper function to calculate effective available quantity
        # This "releases" current package's allocations from reserved_qty
        def calc_available_qty(batch):
            released_qty = current_allocations.get(batch.batch_id, Decimal('0'))
            return safe_decimal(batch.usable_qty) - (safe_decimal(batch.reserved_qty) - released_qty)
        
        # Group batches by warehouse first (before sorting)
        warehouse_groups = {}
        for batch in all_batches:
            warehouse_id = batch.inventory.inventory_id
            if warehouse_id not in warehouse_groups:
                warehouse_groups[warehouse_id] = {
                    'batches': [],
                    'total_available': Decimal('0'),
                    'has_allocated_batches': False
                }
            
            available_qty = calc_available_qty(batch)
            is_allocated = batch.batch_id in allocated_batch_ids_set
            
            # Skip batches with zero or negative available inventory
            # EXCEPT if they're already allocated (need to show them for editing)
            if available_qty <= 0 and not is_allocated:
                continue
            
            warehouse_groups[warehouse_id]['batches'].append(batch)
            warehouse_groups[warehouse_id]['total_available'] += max(Decimal('0'), available_qty)
            if is_allocated:
                warehouse_groups[warehouse_id]['has_allocated_batches'] = True
        
        # Filter out warehouses with zero total available quantity
        # UNLESS they have allocated batches (Set A) which must always be shown to LM
        warehouse_groups = {
            wh_id: wh_data 
            for wh_id, wh_data in warehouse_groups.items() 
            if wh_data['total_available'] > 0 or wh_data['has_allocated_batches']
        }
        
        # Sort batches WITHIN each warehouse using drawer-specific FEFO/FIFO rules
        # (ignores issuance_order, only uses can_expire_flag)
        # Pass allocated_batch_ids to preserve them even if available <= 0
        for warehouse_id, wh_data in warehouse_groups.items():
            wh_data['batches'] = BatchAllocationService.sort_batches_for_drawer(
                wh_data['batches'],
                item,
                allocated_batch_ids_set
            )
        
        # Build limited batch list with per-warehouse early stopping
        limited_batches = []
        
        for warehouse_id, wh_data in warehouse_groups.items():
            warehouse_cumulative_qty = Decimal('0')
            warehouse_has_fulfilled = False
            
            for batch in wh_data['batches']:
                is_allocated = batch.batch_id in allocated_batch_ids_set
                available_qty = calc_available_qty(batch)
                
                # Always include allocated batches with available inventory (for editing)
                if is_allocated:
                    limited_batches.append(batch)
                    warehouse_cumulative_qty += available_qty
                    
                    # Check if allocated batches alone already meet remaining_qty
                    if warehouse_cumulative_qty >= remaining_qty:
                        warehouse_has_fulfilled = True
                    
                    continue
                
                # For non-allocated batches, only include if warehouse hasn't fulfilled yet
                if not warehouse_has_fulfilled:
                    limited_batches.append(batch)
                    warehouse_cumulative_qty += available_qty
                    
                    # Stop loading more batches once this warehouse can fulfill remaining_qty
                    if warehouse_cumulative_qty >= remaining_qty:
                        warehouse_has_fulfilled = True
        
        # Calculate total available and shortfall
        cumulative_available = Decimal('0')
        for batch in limited_batches:
            available_qty = calc_available_qty(batch)
            cumulative_available += available_qty
        
        shortfall = max(Decimal('0'), remaining_qty - cumulative_available)
        
        return limited_batches, cumulative_available, shortfall
    
    @staticmethod
    def assign_priority_groups(batches: List[ItemBatch], item: Item) -> List[Tuple[ItemBatch, int]]:
        """
        Assign priority group IDs to batches based on FEFO/FIFO rules.
        Batches in the same priority group have the same expiry_date and batch_date.
        
        Args:
            batches: Sorted list of batches
            item: Item with issuance order configuration
            
        Returns:
            List of (batch, priority_group_id) tuples
        """
        if not batches:
            return []
        
        batch_groups = []
        current_group_id = 0
        prev_key = None
        
        for batch in batches:
            # Define priority key based on issuance order
            if item.issuance_order == 'FEFO' and item.can_expire_flag:
                current_key = (batch.expiry_date, batch.batch_date)
            else:  # FIFO or LIFO
                current_key = (batch.batch_date,)
            
            # Increment group ID if key changed
            if prev_key is not None and current_key != prev_key:
                current_group_id += 1
            
            batch_groups.append((batch, current_group_id))
            prev_key = current_key
        
        return batch_groups
