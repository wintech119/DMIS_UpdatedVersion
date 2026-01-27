"""
Inventory Management Routes
"""
from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required
from sqlalchemy import func

from app.db import db
from app.db.models import Inventory, Warehouse, Item

inventory_bp = Blueprint('inventory', __name__, url_prefix='/inventory')

@inventory_bp.route('/api/stock_check')
@login_required
def stock_check():
    """API endpoint to check available stock for an item at a warehouse"""
    warehouse_id = request.args.get('warehouse_id', type=int)
    item_id = request.args.get('item_id', type=int)
    
    if not warehouse_id or not item_id:
        return jsonify({'error': 'Missing warehouse_id or item_id'}), 400
    
    inventory = Inventory.query.filter_by(
        inventory_id=warehouse_id,
        item_id=item_id,
        status_code='A'
    ).first()
    
    if inventory:
        return jsonify({
            'available_qty': float(inventory.usable_qty or 0),
            'reserved_qty': float(inventory.reserved_qty or 0),
            'defective_qty': float(inventory.defective_qty or 0)
        })
    else:
        return jsonify({
            'available_qty': 0,
            'reserved_qty': 0,
            'defective_qty': 0
        })

@inventory_bp.route('/')
@login_required
def list_inventory():
    """List inventory summary"""
    from app.core.rbac import has_role
    from flask_login import current_user
    
    warehouse_id = request.args.get('warehouse_id', type=int)
    item_id = request.args.get('item_id', type=int)
    
    query = db.session.query(
        Inventory,
        Item.item_name,
        Item.sku_code,
        Warehouse.warehouse_name
    ).join(Item).join(Warehouse)
    
    # Inventory Clerks can only see inventory from their assigned warehouses
    if has_role('INVENTORY_CLERK'):
        user_warehouse_ids = [w.warehouse_id for w in current_user.warehouses]
        if user_warehouse_ids:
            query = query.filter(Inventory.inventory_id.in_(user_warehouse_ids))
        else:
            # If no warehouses assigned, show nothing
            inventory_items = []
            warehouses = []
            items = []
            return render_template('inventory/list.html', 
                                 inventory_items=inventory_items,
                                 warehouses=warehouses,
                                 items=items,
                                 selected_warehouse_id=warehouse_id,
                                 selected_item_id=item_id)
    
    # Apply additional warehouse filter if specified
    if warehouse_id:
        query = query.filter(Inventory.inventory_id == warehouse_id)
    
    # Apply item filter if specified
    if item_id:
        query = query.filter(Inventory.item_id == item_id)
    
    inventory_items = query.filter(Inventory.status_code == 'A').all()
    
    # For Inventory Clerks, only show their assigned warehouses in the dropdown
    if has_role('INVENTORY_CLERK'):
        user_warehouse_ids = [w.warehouse_id for w in current_user.warehouses]
        warehouses = Warehouse.query.filter(
            Warehouse.warehouse_id.in_(user_warehouse_ids),
            Warehouse.status_code == 'A'
        ).order_by(Warehouse.warehouse_name).all()
    else:
        warehouses = Warehouse.query.filter_by(status_code='A').order_by(Warehouse.warehouse_name).all()
    
    # Get all active items for the filter dropdown
    items = Item.query.filter_by(status_code='A').order_by(Item.item_name).all()
    
    return render_template('inventory/list.html', 
                         inventory_items=inventory_items,
                         warehouses=warehouses,
                         items=items,
                         selected_warehouse_id=warehouse_id,
                         selected_item_id=item_id)
