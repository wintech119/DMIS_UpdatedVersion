from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from sqlalchemy import func
from datetime import datetime, date
from app.db import db
from app.db.models import (DBIntake, DBIntakeItem, ReliefPkg, Inventory, Item, 
                          Warehouse, UnitOfMeasure, ReliefPkgItem)
from app.services.batch_creation_service import BatchCreationService

bp = Blueprint('intake', __name__, url_prefix='/intake')

@bp.route('/create', methods=['GET', 'POST'])
@login_required
def create_intake():
    """Create new donation/distribution intake record"""
    if request.method == 'POST':
        try:
            reliefpkg_id = request.form.get('reliefpkg_id')
            warehouse_id = request.form.get('warehouse_id')
            intake_date_str = request.form.get('intake_date')
            comments = request.form.get('comments', '').upper()
            
            intake_date = datetime.strptime(intake_date_str, '%Y-%m-%d').date() if intake_date_str else None
            
            if not reliefpkg_id or not warehouse_id or not intake_date:
                flash('Relief Package, Warehouse, and Intake Date are required', 'danger')
                return redirect(url_for('intake.create_intake'))
            
            package = ReliefPkg.query.get(reliefpkg_id)
            if not package:
                flash('Relief Package not found', 'danger')
                return redirect(url_for('intake.create_intake'))
            
            if package.status_code != 'D':
                flash('Only dispatched packages can be received', 'danger')
                return redirect(url_for('intake.create_intake'))
            
            warehouse = Warehouse.query.get(warehouse_id)
            if not warehouse:
                flash('Warehouse not found', 'danger')
                return redirect(url_for('intake.create_intake'))
            
            item_ids = request.form.getlist('item_id[]')
            usable_qtys = request.form.getlist('usable_qty[]')
            defective_qtys = request.form.getlist('defective_qty[]')
            expired_qtys = request.form.getlist('expired_qty[]')
            
            has_positive_qty = False
            for u, d, e in zip(usable_qtys, defective_qtys, expired_qtys):
                u_val = float(u) if u else 0
                d_val = float(d) if d else 0
                e_val = float(e) if e else 0
                if u_val > 0 or d_val > 0 or e_val > 0:
                    has_positive_qty = True
                    break
            
            if not item_ids or not has_positive_qty:
                flash('At least one item with positive quantity is required', 'danger')
                return redirect(url_for('intake.create_intake'))
            
            from app.utils.timezone import now
            user_id_upper = str(current_user.user_id).upper()
            current_time = now()
            
            first_inventory_id = None
            
            for item_id, usable_qty, defective_qty, expired_qty in zip(item_ids, usable_qtys, defective_qtys, expired_qtys):
                if item_id:
                    usable = float(usable_qty) if usable_qty else 0
                    defective = float(defective_qty) if defective_qty else 0
                    expired = float(expired_qty) if expired_qty else 0
                    
                    if usable < 0 or defective < 0 or expired < 0:
                        flash('Quantities cannot be negative', 'danger')
                        db.session.rollback()
                        return redirect(url_for('intake.create_intake'))
                    
                    if usable == 0 and defective == 0 and expired == 0:
                        continue
                    
                    pkg_item = ReliefPkgItem.query.filter_by(
                        reliefpkg_id=reliefpkg_id,
                        item_id=item_id
                    ).first()
                    
                    if not pkg_item:
                        flash(f'Item {item_id} not in relief package', 'danger')
                        db.session.rollback()
                        return redirect(url_for('intake.create_intake'))
                    
                    total_qty = usable + defective + expired
                    if total_qty > pkg_item.item_qty:
                        flash(f'Total quantity ({total_qty}) exceeds package quantity ({pkg_item.item_qty})', 'danger')
                        db.session.rollback()
                        return redirect(url_for('intake.create_intake'))
                    
                    item_inventory = Inventory.query.filter_by(
                        inventory_id=warehouse_id,
                        item_id=item_id
                    ).first()
                    
                    if not item_inventory:
                        item_inventory = Inventory(
                            inventory_id=warehouse_id,
                            item_id=item_id,
                            usable_qty=0,
                            defective_qty=0,
                            expired_qty=0,
                            on_hand_qty=0,
                            issue_qty=0,
                            receive_qty=0,
                            status_code='A'
                        )
                        db.session.add(item_inventory)
                        db.session.flush()
                    
                    if first_inventory_id is None:
                        first_inventory_id = item_inventory.inventory_id
                    
                    existing_intake = DBIntake.query.filter_by(
                        reliefpkg_id=reliefpkg_id,
                        inventory_id=item_inventory.inventory_id
                    ).first()
                    
                    if not existing_intake:
                        intake = DBIntake(
                            reliefpkg_id=reliefpkg_id,
                            inventory_id=item_inventory.inventory_id,
                            intake_date=intake_date,
                            comments_text=comments if comments else None,
                            status_code='I',
                            create_by_id=user_id_upper,
                            create_dtime=now,
                            update_by_id=user_id_upper,
                            update_dtime=now,
                            version_nbr=1
                        )
                        db.session.add(intake)
                    
                    intake_item = DBIntakeItem(
                        reliefpkg_id=reliefpkg_id,
                        inventory_id=item_inventory.inventory_id,
                        item_id=item_id,
                        usable_qty=usable,
                        defective_qty=defective,
                        expired_qty=expired,
                        uom_code=pkg_item.uom_code,
                        status_code='P',
                        create_by_id=user_id_upper,
                        create_dtime=now,
                        update_by_id=user_id_upper,
                        update_dtime=now,
                        version_nbr=1
                    )
                    db.session.add(intake_item)
                    
                    item_inventory.on_hand_qty += usable
                    item_inventory.usable_qty += usable
                    item_inventory.defective_qty += defective
                    item_inventory.expired_qty += expired
                    item_inventory.receive_qty += total_qty
                    
                    item = Item.query.get(item_id)
                    if item and item.is_batched_flag:
                        batch = BatchCreationService.create_batch_for_intake(
                            inventory_id=item_inventory.inventory_id,
                            item_id=item_id,
                            usable_qty=usable,
                            defective_qty=defective,
                            expired_qty=expired,
                            batch_date=intake_date,
                            expiry_date=None,
                            uom_code=pkg_item.uom_code,
                            user_name=current_user.user_name
                        )
                        if batch:
                            db.session.add(batch)
            
            if first_inventory_id is None:
                flash('No valid items were processed', 'danger')
                db.session.rollback()
                return redirect(url_for('intake.create_intake'))
            
            db.session.commit()
            flash('Intake record created successfully', 'success')
            return redirect(url_for('intake.view_intake', reliefpkg_id=reliefpkg_id, inventory_id=first_inventory_id))
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('Error creating intake')
            flash('An error occurred while creating the intake. Please try again or contact support.', 'danger')
            return redirect(url_for('intake.create_intake'))
    
    dispatched_packages = ReliefPkg.query.filter_by(status_code='D').all()
    warehouses = Warehouse.query.filter_by(status_code='A').all()
    items = Item.query.filter_by(status_code='A').all()
    
    return render_template('intake/create.html', 
                         packages=dispatched_packages,
                         warehouses=warehouses,
                         items=items)

@bp.route('/list')
@login_required
def list_intakes():
    """List all intake records"""
    intakes = db.session.query(
        DBIntake,
        ReliefPkg,
        Warehouse
    ).join(
        ReliefPkg, DBIntake.reliefpkg_id == ReliefPkg.reliefpkg_id
    ).join(
        Inventory, DBIntake.inventory_id == Inventory.inventory_id
    ).join(
        Warehouse, Inventory.inventory_id == Warehouse.warehouse_id
    ).all()
    
    return render_template('intake/list.html', intakes=intakes)

@bp.route('/<int:reliefpkg_id>/<int:inventory_id>')
@login_required
def view_intake(reliefpkg_id, inventory_id):
    """View intake record details"""
    intake = DBIntake.query.filter_by(
        reliefpkg_id=reliefpkg_id,
        inventory_id=inventory_id
    ).first_or_404()
    
    package = ReliefPkg.query.get(reliefpkg_id)
    inventory = Inventory.query.get((inventory_id, package.items[0].item_id if package.items else 1))
    warehouse = Warehouse.query.get(inventory_id)
    
    items = db.session.query(
        DBIntakeItem,
        Item
    ).join(
        Item, DBIntakeItem.item_id == Item.item_id
    ).filter(
        DBIntakeItem.reliefpkg_id == reliefpkg_id,
        DBIntakeItem.inventory_id == inventory_id
    ).all()
    
    return render_template('intake/view.html',
                         intake=intake,
                         package=package,
                         warehouse=warehouse,
                         items=items)

@bp.route('/<int:reliefpkg_id>/<int:inventory_id>/complete', methods=['POST'])
@login_required
def complete_intake(reliefpkg_id, inventory_id):
    """Mark intake as complete"""
    intake = DBIntake.query.filter_by(
        reliefpkg_id=reliefpkg_id,
        inventory_id=inventory_id
    ).first_or_404()
    
    if intake.status_code != 'I':
        flash('Only incomplete intakes can be completed', 'danger')
        return redirect(url_for('intake.view_intake', reliefpkg_id=reliefpkg_id, inventory_id=inventory_id))
    
    from app.utils.timezone import now
    intake.status_code = 'C'
    intake.update_by_id = str(current_user.user_id).upper()
    intake.update_dtime = now()
    intake.version_nbr += 1
    
    db.session.commit()
    flash('Intake marked as complete', 'success')
    return redirect(url_for('intake.view_intake', reliefpkg_id=reliefpkg_id, inventory_id=inventory_id))
