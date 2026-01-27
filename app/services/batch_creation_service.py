"""Batch Creation Service

Automatically creates batches for items with is_batched_flag=TRUE during intake processes.
Ensures batch-level traceability for inventory management.
"""

from datetime import date
from sqlalchemy import func
from app import db
from app.db.models import ItemBatch, Item
from app.utils.timezone import now


class BatchCreationService:
    """Service for automatic batch creation during inventory intake"""
    
    @staticmethod
    def generate_batch_number(item_code, inventory_id, batch_date=None):
        """Generate unique batch number: ITEM-WH-YYYYMMDD-SEQ
        
        Args:
            item_code: Item code
            inventory_id: Warehouse/inventory ID
            batch_date: Batch date (defaults to today)
            
        Returns:
            str: Generated batch number (e.g., RICE-001-20250117-001)
        """
        if batch_date is None:
            batch_date = date.today()
        
        date_str = batch_date.strftime('%Y%m%d')
        prefix = str(item_code) + '-' + str(inventory_id).zfill(3) + '-' + date_str
        search_prefix = prefix + '%'
        
        max_batch = db.session.query(
            func.max(ItemBatch.batch_no)
        ).filter(
            ItemBatch.batch_no.like(search_prefix)
        ).scalar()
        
        if max_batch:
            seq = int(max_batch.split('-')[-1]) + 1
        else:
            seq = 1
        
        return f"{prefix}-{seq:03d}"
    
    @staticmethod
    def create_batch_for_intake(
        inventory_id,
        item_id,
        usable_qty=0,
        defective_qty=0,
        expired_qty=0,
        batch_date=None,
        expiry_date=None,
        uom_code=None,
        size_spec=None,
        avg_unit_value=0,
        user_name=None,
        batch_no=None
    ):
        """Create a batch record for an intake item
        
        Args:
            inventory_id: Warehouse/inventory ID
            item_id: Item ID
            usable_qty: Usable quantity received
            defective_qty: Defective quantity received
            expired_qty: Expired quantity received
            batch_date: Date batch was received (defaults to today)
            expiry_date: Expiry date for the batch (optional)
            uom_code: Unit of measure code
            size_spec: Size specification (optional)
            avg_unit_value: Average unit value (optional)
            user_name: User creating the batch
            batch_no: Batch number (if provided, otherwise auto-generated)
            
        Returns:
            ItemBatch: Created batch record
        """
        item = Item.query.get(item_id)
        if not item:
            raise ValueError(f"Item {item_id} not found")
        
        if not item.is_batched_flag:
            return None
        
        if batch_date is None:
            batch_date = date.today()
        
        if batch_no is None:
            batch_no = BatchCreationService.generate_batch_number(
                item.item_code, 
                inventory_id, 
                batch_date
            )
        
        batch_no = batch_no.upper()
        
        if uom_code is None:
            uom_code = item.uom_code
        
        if size_spec:
            size_spec = size_spec.upper()
        
        current_time = now()
        
        batch = ItemBatch(
            inventory_id=inventory_id,
            item_id=item_id,
            batch_no=batch_no,
            batch_date=batch_date,
            expiry_date=expiry_date,
            usable_qty=usable_qty,
            reserved_qty=0,
            defective_qty=defective_qty,
            expired_qty=expired_qty,
            uom_code=uom_code,
            size_spec=size_spec,
            avg_unit_value=avg_unit_value,
            status_code='A',
            create_by_id=user_name,
            create_dtime=current_time,
            update_by_id=user_name,
            update_dtime=current_time,
            version_nbr=1
        )
        
        db.session.add(batch)
        
        return batch
    
    @staticmethod
    def update_or_create_batch(
        inventory_id,
        item_id,
        batch_no,
        usable_qty=0,
        defective_qty=0,
        expired_qty=0,
        batch_date=None,
        expiry_date=None,
        uom_code=None,
        size_spec=None,
        avg_unit_value=0,
        user_name=None
    ):
        """Update existing batch or create new one if it doesn't exist
        
        This is useful for transfers where we want to preserve batch identity
        across warehouses.
        
        Args:
            inventory_id: Warehouse/inventory ID
            item_id: Item ID
            batch_no: Batch number to find or create
            usable_qty: Usable quantity to add
            defective_qty: Defective quantity to add
            expired_qty: Expired quantity to add
            batch_date: Date batch was received (defaults to today)
            expiry_date: Expiry date for the batch (optional)
            uom_code: Unit of measure code
            size_spec: Size specification (optional)
            avg_unit_value: Average unit value (optional)
            user_name: User creating/updating the batch
            
        Returns:
            ItemBatch: Updated or created batch record
        """
        item = Item.query.get(item_id)
        if not item or not item.is_batched_flag:
            return None
        
        batch_no = batch_no.upper()
        
        existing_batch = ItemBatch.query.filter_by(
            inventory_id=inventory_id,
            item_id=item_id,
            batch_no=batch_no
        ).first()
        
        if existing_batch:
            existing_batch.usable_qty += usable_qty
            existing_batch.defective_qty += defective_qty
            existing_batch.expired_qty += expired_qty
            existing_batch.update_by_id = user_name
            existing_batch.update_dtime = now()
            existing_batch.version_nbr += 1
            
            return existing_batch
        else:
            return BatchCreationService.create_batch_for_intake(
                inventory_id=inventory_id,
                item_id=item_id,
                usable_qty=usable_qty,
                defective_qty=defective_qty,
                expired_qty=expired_qty,
                batch_date=batch_date,
                expiry_date=expiry_date,
                uom_code=uom_code,
                size_spec=size_spec,
                avg_unit_value=avg_unit_value,
                user_name=user_name,
                batch_no=batch_no
            )
