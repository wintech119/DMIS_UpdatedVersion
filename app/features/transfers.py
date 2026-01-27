from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from datetime import datetime, date
from app.db.models import db, Transfer, TransferItem, Warehouse, Inventory, Item, UnitOfMeasure
from app.core.audit import add_audit_fields, add_verify_fields
from sqlalchemy import and_

transfers_bp = Blueprint('transfers', __name__)

@transfers_bp.route('/')
@login_required
def list_transfers():
    transfers = Transfer.query.order_by(Transfer.transfer_date.desc()).all()
    return render_template('transfers/index.html', transfers=transfers)

@transfers_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    if request.method == 'POST':
        from app.security.param_validation import safe_id, safe_float
        
        from_warehouse_id = safe_id(request.form.get('from_warehouse_id'))
        to_warehouse_id = safe_id(request.form.get('to_warehouse_id'))
        item_id = safe_id(request.form.get('item_id'))
        # Validate quantity with reasonable bounds
        quantity = safe_float(request.form.get('quantity'), default=0.0, min_val=0.0, max_val=999999999.99)
        uom_code = request.form.get('uom_code')
        transport_mode = request.form.get('transport_mode', '').strip()
        comments_text = request.form.get('comments_text', '').strip()
        
        if not all([from_warehouse_id > 0, to_warehouse_id > 0, item_id > 0, quantity > 0, uom_code]):
            flash('Please fill in all required fields.', 'danger')
            return redirect(url_for('transfers.create'))
        
        if from_warehouse_id == to_warehouse_id:
            flash('Cannot transfer to the same warehouse.', 'danger')
            return redirect(url_for('transfers.create'))
        
        from_inventory = Inventory.query.filter_by(
            inventory_id=from_warehouse_id, 
            item_id=item_id
        ).first()
        
        if not from_inventory or from_inventory.usable_qty < quantity:
            flash(f'Insufficient usable quantity in source warehouse. Available: {from_inventory.usable_qty if from_inventory else 0}', 'danger')
            return redirect(url_for('transfers.create'))
        
        to_inventory = Inventory.query.filter_by(
            inventory_id=to_warehouse_id, 
            item_id=item_id
        ).first()
        
        if not to_inventory:
            to_inventory = Inventory(
                inventory_id=to_warehouse_id,
                item_id=item_id,
                uom_code=from_inventory.uom_code,
                usable_qty=0,
                reserved_qty=0,
                defective_qty=0,
                expired_qty=0,
                status_code='A'
            )
            add_audit_fields(to_inventory, current_user)
            db.session.add(to_inventory)
            db.session.flush()
        
        new_transfer = Transfer(
            fr_inventory_id=from_inventory.inventory_id,
            to_inventory_id=to_inventory.inventory_id,
            transfer_date=date.today(),
            transport_mode=transport_mode or None,
            comments_text=comments_text or None,
            status_code='P'
        )
        
        add_audit_fields(new_transfer, current_user)
        add_verify_fields(new_transfer, current_user)
        
        db.session.add(new_transfer)
        db.session.flush()
        
        transfer_item = TransferItem(
            transfer_id=new_transfer.transfer_id,
            item_id=item_id,
            item_qty=quantity,
            uom_code=uom_code,
            reason_text=comments_text or None
        )
        add_audit_fields(transfer_item, current_user)
        
        db.session.add(transfer_item)
        db.session.commit()
        
        flash(f'Transfer #{new_transfer.transfer_id} created successfully.', 'success')
        return redirect(url_for('transfers.view', transfer_id=new_transfer.transfer_id))
    
    warehouses = Warehouse.query.filter_by(status_code='A').all()
    items = Item.query.filter_by(status_code='A').all()
    uoms = UnitOfMeasure.query.all()
    return render_template('transfers/create.html', warehouses=warehouses, items=items, uoms=uoms)

@transfers_bp.route('/<int:transfer_id>')
@login_required
def view(transfer_id):
    transfer = Transfer.query.get_or_404(transfer_id)
    return render_template('transfers/view.html', transfer=transfer)

@transfers_bp.route('/<int:transfer_id>/execute', methods=['POST'])
@login_required
def execute(transfer_id):
    transfer = Transfer.query.get_or_404(transfer_id)
    
    if transfer.status_code != 'P':
        flash('Only pending transfers can be executed.', 'danger')
        return redirect(url_for('transfers.view', transfer_id=transfer_id))
    
    from_inventory = transfer.from_inventory
    to_inventory = transfer.to_inventory
    
    for transfer_item in transfer.items:
        if from_inventory.usable_qty < transfer_item.item_qty:
            flash(f'Insufficient quantity for {transfer_item.item.item_name}. Transfer cancelled.', 'danger')
            return redirect(url_for('transfers.view', transfer_id=transfer_id))
        
        from_inventory.usable_qty -= transfer_item.item_qty
        to_inventory.usable_qty += transfer_item.item_qty
        
        add_audit_fields(from_inventory, current_user, is_new=False)
        add_audit_fields(to_inventory, current_user, is_new=False)
    
    transfer.status_code = 'C'
    add_audit_fields(transfer, current_user, is_new=False)
    add_verify_fields(transfer, current_user)
    
    db.session.commit()
    
    flash(f'Transfer #{transfer_id} completed successfully. Inventory has been updated.', 'success')
    return redirect(url_for('transfers.view', transfer_id=transfer_id))

@transfers_bp.route('/api/inventory/<int:warehouse_id>/<int:item_id>')
@login_required
def get_inventory_quantity(warehouse_id, item_id):
    inventory = Inventory.query.filter_by(
        warehouse_id=warehouse_id, 
        item_id=item_id
    ).first()
    
    if inventory:
        return jsonify({
            'available': float(inventory.usable_qty),
            'reserved': float(inventory.reserved_qty)
        })
    return jsonify({'available': 0, 'reserved': 0})
