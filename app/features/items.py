"""
Item Management Routes (CUSTODIAN Role Only)

Full CRUD operations for relief items with:
- Role-based access control (CUSTODIAN only)
- Comprehensive validation and business rules
- Optimistic locking (version_nbr)
- No physical deletes (inactivation only)
- Stock/transaction checks before inactivation
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from decimal import Decimal, InvalidOperation
import re

from app.db import db
from app.db.models import Item, ItemCategory, UnitOfMeasure, Inventory
from app.core.audit import add_audit_fields
from app.core.decorators import feature_required

items_bp = Blueprint('items', __name__, url_prefix='/items')

# ============================================================================
# VALIDATION HELPERS
# ============================================================================

def validate_item_code(item_code):
    """Validate item_code: 1-16 chars, alphanumeric with allowed special chars"""
    if not item_code or not item_code.strip():
        raise ValueError('Item Code is required')
    
    item_code = item_code.strip().upper()
    
    if len(item_code) > 16:
        raise ValueError('Item Code must not exceed 16 characters')
    
    if not re.match(r'^[A-Z0-9\-_\.]+$', item_code):
        raise ValueError('Item Code must contain only letters, numbers, hyphens, underscores, and dots')
    
    return item_code

def validate_item_name(item_name):
    """Validate item_name: required, 1-60 chars"""
    if not item_name or not item_name.strip():
        raise ValueError('Item Name is required')
    
    item_name = item_name.strip().upper()
    
    if len(item_name) > 60:
        raise ValueError('Item Name must not exceed 60 characters')
    
    return item_name

def validate_sku_code(sku_code):
    """Validate sku_code: required, 1-30 chars"""
    if not sku_code or not sku_code.strip():
        raise ValueError('SKU Code is required')
    
    sku_code = sku_code.strip().upper()
    
    if len(sku_code) > 30:
        raise ValueError('SKU Code must not exceed 30 characters')
    
    return sku_code

def validate_reorder_qty(reorder_qty_str):
    """Validate reorder_qty: must be positive decimal"""
    if not reorder_qty_str or not reorder_qty_str.strip():
        raise ValueError('Reorder Quantity is required')
    
    try:
        qty = Decimal(reorder_qty_str)
    except (InvalidOperation, ValueError):
        raise ValueError('Reorder Quantity must be a valid number')
    
    if qty <= 0:
        raise ValueError('Reorder Quantity must be greater than zero')
    
    return qty

def validate_comments(comments_text):
    """Validate comments_text: max 300 characters"""
    if comments_text and len(comments_text) > 300:
        raise ValueError('Comments must not exceed 300 characters')
    return comments_text

def validate_issuance_order(issuance_order):
    """Validate issuance_order: FIFO, FEFO, or LIFO"""
    allowed = ['FIFO', 'FEFO', 'LIFO']
    if issuance_order not in allowed:
        raise ValueError(f'Issuance Order must be one of: {", ".join(allowed)}')
    return issuance_order

def check_item_can_be_inactivated(item_id):
    """
    Check if item can be inactivated.
    Returns (can_inactivate: bool, message: str)
    """
    # Check if item has any inventory stock on hand
    total_stock = db.session.query(
        db.func.sum(Inventory.usable_qty)
    ).filter(
        Inventory.item_id == item_id
    ).scalar() or Decimal('0')
    
    if total_stock > 0:
        return False, f'This item cannot be inactivated because it has {total_stock} units of stock on hand'
    
    # Check reserved quantities
    total_reserved = db.session.query(
        db.func.sum(Inventory.reserved_qty)
    ).filter(
        Inventory.item_id == item_id
    ).scalar() or Decimal('0')
    
    if total_reserved > 0:
        return False, f'This item cannot be inactivated because it has {total_reserved} units reserved'
    
    # Add more checks here for open transactions, orders, etc. when those modules exist
    
    return True, 'Item can be inactivated'

def check_uniqueness(item_id, item_code, item_name, sku_code):
    """
    Check for uniqueness of item_code, item_name, and sku_code.
    Excludes the current item (if editing).
    Returns list of error messages.
    """
    errors = []
    
    # Check item_code uniqueness
    query = Item.query.filter(Item.item_code == item_code)
    if item_id:
        query = query.filter(Item.item_id != item_id)
    if query.first():
        errors.append(f'Item Code "{item_code}" is already in use')
    
    # Check item_name uniqueness
    query = Item.query.filter(Item.item_name == item_name)
    if item_id:
        query = query.filter(Item.item_id != item_id)
    if query.first():
        errors.append(f'Item Name "{item_name}" is already in use')
    
    # Check sku_code uniqueness
    query = Item.query.filter(Item.sku_code == sku_code)
    if item_id:
        query = query.filter(Item.item_id != item_id)
    if query.first():
        errors.append(f'SKU Code "{sku_code}" is already in use')
    
    return errors

# ============================================================================
# ROUTES
# ============================================================================

@items_bp.route('/')
@login_required
@feature_required('item_management')
def list_items():
    """List items with search, filters, and pagination (CUSTODIAN only)"""
    # Get filter parameters
    filter_type = request.args.get('filter', 'active')
    search_query = request.args.get('search', '').strip()
    category_filter = request.args.get('category', '').strip()
    is_batched_filter = request.args.get('is_batched', '').strip()
    can_expire_filter = request.args.get('can_expire', '').strip()
    
    # Base query
    query = Item.query
    
    # Apply status filter
    if filter_type == 'active':
        query = query.filter_by(status_code='A')
    elif filter_type == 'inactive':
        query = query.filter_by(status_code='I')
    # 'all' shows both
    
    # Apply search filter
    if search_query:
        search_term = f'%{search_query}%'
        query = query.filter(
            db.or_(
                Item.item_code.ilike(search_term),
                Item.item_name.ilike(search_term),
                Item.sku_code.ilike(search_term),
                Item.item_desc.ilike(search_term)
            )
        )
    
    # Apply category filter
    if category_filter:
        try:
            category_id = int(category_filter)
            query = query.filter_by(category_id=category_id)
        except ValueError:
            pass
    
    # Apply boolean filters
    if is_batched_filter == 'true':
        query = query.filter_by(is_batched_flag=True)
    elif is_batched_filter == 'false':
        query = query.filter_by(is_batched_flag=False)
    
    if can_expire_filter == 'true':
        query = query.filter_by(can_expire_flag=True)
    elif can_expire_filter == 'false':
        query = query.filter_by(can_expire_flag=False)
    
    # Get items
    items = query.order_by(Item.item_name).all()
    
    # Calculate metrics
    total_items = Item.query.count()
    active_items = Item.query.filter_by(status_code='A').count()
    inactive_items = Item.query.filter_by(status_code='I').count()
    batched_items = Item.query.filter_by(is_batched_flag=True, status_code='A').count()
    expirable_items = Item.query.filter_by(can_expire_flag=True, status_code='A').count()
    
    metrics = {
        'total_items': total_items,
        'active_items': active_items,
        'inactive_items': inactive_items,
        'batched_items': batched_items,
        'expirable_items': expirable_items
    }
    
    # Get all categories for filter dropdown
    categories = ItemCategory.query.filter_by(status_code='A').order_by(ItemCategory.category_desc).all()
    
    return render_template(
        'items/list.html',
        items=items,
        filter_type=filter_type,
        search_query=search_query,
        category_filter=category_filter,
        is_batched_filter=is_batched_filter,
        can_expire_filter=can_expire_filter,
        metrics=metrics,
        categories=categories
    )

@items_bp.route('/create', methods=['GET', 'POST'])
@login_required
@feature_required('item_management')
def create_item():
    """Create new item (CUSTODIAN only)"""
    if request.method == 'POST':
        # Extract raw form values first (so they're available in error handlers)
        item_code_raw = request.form.get('item_code', '').strip()
        item_name_raw = request.form.get('item_name', '').strip()
        sku_code_raw = request.form.get('sku_code', '').strip()
        
        try:
            # Validate and clean all fields
            item_code = validate_item_code(item_code_raw)
            item_name = validate_item_name(item_name_raw)
            sku_code = validate_sku_code(sku_code_raw)
            item_desc = (request.form.get('item_desc', '') or '').strip()
            reorder_qty = validate_reorder_qty(request.form.get('reorder_qty', ''))
            category_id = request.form.get('category_id', type=int)
            default_uom_code = request.form.get('default_uom_code', '').strip()
            units_size_vary_flag = request.form.get('units_size_vary_flag') == 'on'
            usage_desc = (request.form.get('usage_desc', '') or '').strip() or None
            storage_desc = (request.form.get('storage_desc', '') or '').strip() or None
            is_batched_flag = request.form.get('is_batched_flag') == 'on'
            can_expire_flag = request.form.get('can_expire_flag') == 'on'
            issuance_order = request.form.get('issuance_order', 'FIFO')
            comments_text = (request.form.get('comments_text', '') or '').strip() or None
            status_code = request.form.get('status_code', 'A')
            
            # Additional validations
            if not item_desc:
                raise ValueError('Item Description is required')
            
            if not category_id:
                raise ValueError('Category is required')
            
            if not default_uom_code:
                raise ValueError('Default Unit of Measure is required')
            
            if status_code not in ['A', 'I']:
                status_code = 'A'
            
            validate_issuance_order(issuance_order)
            validate_comments(comments_text)
            
            # Check uniqueness
            uniqueness_errors = check_uniqueness(None, item_code, item_name, sku_code)
            if uniqueness_errors:
                for error in uniqueness_errors:
                    flash(error, 'danger')
                raise ValueError('Validation failed')
            
            # Create item
            item = Item()
            item.item_code = item_code
            item.item_name = item_name
            item.sku_code = sku_code
            item.category_id = category_id
            item.item_desc = item_desc
            item.reorder_qty = reorder_qty
            item.default_uom_code = default_uom_code
            item.units_size_vary_flag = units_size_vary_flag
            item.usage_desc = usage_desc
            item.storage_desc = storage_desc
            item.is_batched_flag = is_batched_flag
            item.can_expire_flag = can_expire_flag
            item.issuance_order = issuance_order
            item.comments_text = comments_text
            item.status_code = status_code
            
            add_audit_fields(item, current_user, is_new=True)
            
            db.session.add(item)
            db.session.commit()
            
            flash(f'Item "{item.item_name}" created successfully', 'success')
            return redirect(url_for('items.view_item', item_id=item.item_id))
            
        except ValueError as e:
            if str(e) != 'Validation failed':
                flash(str(e), 'danger')
            categories = ItemCategory.query.filter_by(status_code='A').order_by(ItemCategory.category_desc).all()
            uoms = UnitOfMeasure.query.order_by(UnitOfMeasure.uom_desc).all()
            return render_template('items/create.html', categories=categories, uoms=uoms)
            
        except IntegrityError as e:
            db.session.rollback()
            error_msg = str(e.orig).lower()
            if 'uk_item_1' in error_msg or 'item_code' in error_msg:
                flash(f'Item Code "{item_code_raw.upper()}" is already in use', 'danger')
            elif 'uk_item_2' in error_msg or 'item_name' in error_msg:
                flash(f'Item Name "{item_name_raw.upper()}" is already in use', 'danger')
            elif 'uk_item_3' in error_msg or 'sku_code' in error_msg:
                flash(f'SKU Code "{sku_code_raw.upper()}" is already in use', 'danger')
            else:
                current_app.logger.exception('Database error creating item')
                flash('A database error occurred. Please check your input and try again.', 'danger')
            categories = ItemCategory.query.filter_by(status_code='A').order_by(ItemCategory.category_desc).all()
            uoms = UnitOfMeasure.query.order_by(UnitOfMeasure.uom_desc).all()
            return render_template('items/create.html', categories=categories, uoms=uoms)
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('Error creating item')
            flash('An unexpected error occurred. Please try again or contact support.', 'danger')
            categories = ItemCategory.query.filter_by(status_code='A').order_by(ItemCategory.category_desc).all()
            uoms = UnitOfMeasure.query.order_by(UnitOfMeasure.uom_desc).all()
            return render_template('items/create.html', categories=categories, uoms=uoms)
    
    # GET request
    categories = ItemCategory.query.filter_by(status_code='A').order_by(ItemCategory.category_desc).all()
    uoms = UnitOfMeasure.query.order_by(UnitOfMeasure.uom_desc).all()
    return render_template('items/create.html', categories=categories, uoms=uoms)

@items_bp.route('/<int:item_id>')
@login_required
@feature_required('item_management')
def view_item(item_id):
    """View item details (CUSTODIAN only)"""
    item = Item.query.get_or_404(item_id)
    return render_template('items/view.html', item=item)

@items_bp.route('/<int:item_id>/edit', methods=['GET', 'POST'])
@login_required
@feature_required('item_management')
def edit_item(item_id):
    """Edit item with optimistic locking (CUSTODIAN only)"""
    item = Item.query.get_or_404(item_id)
    
    if request.method == 'POST':
        # Extract raw form values first (so they're available in error handlers)
        item_code_raw = request.form.get('item_code', '').strip()
        item_name_raw = request.form.get('item_name', '').strip()
        sku_code_raw = request.form.get('sku_code', '').strip()
        
        try:
            # Check optimistic locking
            submitted_version = request.form.get('version_nbr', type=int)
            if submitted_version != item.version_nbr:
                flash('This item was modified by another user. Please refresh and try again.', 'warning')
                return redirect(url_for('items.edit_item', item_id=item_id))
            
            # Validate and clean all fields
            item_code = validate_item_code(item_code_raw)
            item_name = validate_item_name(item_name_raw)
            sku_code = validate_sku_code(sku_code_raw)
            item_desc = (request.form.get('item_desc', '') or '').strip()
            reorder_qty = validate_reorder_qty(request.form.get('reorder_qty', ''))
            category_id = request.form.get('category_id', type=int)
            default_uom_code = request.form.get('default_uom_code', '').strip()
            units_size_vary_flag = request.form.get('units_size_vary_flag') == 'on'
            usage_desc = (request.form.get('usage_desc', '') or '').strip() or None
            storage_desc = (request.form.get('storage_desc', '') or '').strip() or None
            is_batched_flag = request.form.get('is_batched_flag') == 'on'
            can_expire_flag = request.form.get('can_expire_flag') == 'on'
            issuance_order = request.form.get('issuance_order', 'FIFO')
            comments_text = (request.form.get('comments_text', '') or '').strip() or None
            status_code = request.form.get('status_code', 'A')
            
            # Additional validations
            if not item_desc:
                raise ValueError('Item Description is required')
            
            if not category_id:
                raise ValueError('Category is required')
            
            if not default_uom_code:
                raise ValueError('Default Unit of Measure is required')
            
            if status_code not in ['A', 'I']:
                status_code = 'A'
            
            validate_issuance_order(issuance_order)
            validate_comments(comments_text)
            
            # Check uniqueness (excluding current item)
            uniqueness_errors = check_uniqueness(item_id, item_code, item_name, sku_code)
            if uniqueness_errors:
                for error in uniqueness_errors:
                    flash(error, 'danger')
                raise ValueError('Validation failed')
            
            # Update item
            item.item_code = item_code
            item.item_name = item_name
            item.sku_code = sku_code
            item.category_id = category_id
            item.item_desc = item_desc
            item.reorder_qty = reorder_qty
            item.default_uom_code = default_uom_code
            item.units_size_vary_flag = units_size_vary_flag
            item.usage_desc = usage_desc
            item.storage_desc = storage_desc
            item.is_batched_flag = is_batched_flag
            item.can_expire_flag = can_expire_flag
            item.issuance_order = issuance_order
            item.comments_text = comments_text
            item.status_code = status_code
            
            add_audit_fields(item, current_user, is_new=False)
            
            db.session.commit()
            
            flash(f'Item "{item.item_name}" updated successfully', 'success')
            return redirect(url_for('items.view_item', item_id=item.item_id))
            
        except ValueError as e:
            if str(e) != 'Validation failed':
                flash(str(e), 'danger')
            categories = ItemCategory.query.filter_by(status_code='A').order_by(ItemCategory.category_desc).all()
            uoms = UnitOfMeasure.query.order_by(UnitOfMeasure.uom_desc).all()
            return render_template('items/edit.html', item=item, categories=categories, uoms=uoms)
            
        except StaleDataError:
            db.session.rollback()
            flash('This item was modified by another user. Please refresh and try again.', 'warning')
            return redirect(url_for('items.edit_item', item_id=item_id))
            
        except IntegrityError as e:
            db.session.rollback()
            error_msg = str(e.orig).lower()
            if 'uk_item_1' in error_msg or 'item_code' in error_msg:
                flash(f'Item Code "{item_code_raw.upper()}" is already in use', 'danger')
            elif 'uk_item_2' in error_msg or 'item_name' in error_msg:
                flash(f'Item Name "{item_name_raw.upper()}" is already in use', 'danger')
            elif 'uk_item_3' in error_msg or 'sku_code' in error_msg:
                flash(f'SKU Code "{sku_code_raw.upper()}" is already in use', 'danger')
            else:
                current_app.logger.exception('Database error updating item')
                flash('A database error occurred. Please check your input and try again.', 'danger')
            categories = ItemCategory.query.filter_by(status_code='A').order_by(ItemCategory.category_desc).all()
            uoms = UnitOfMeasure.query.order_by(UnitOfMeasure.uom_desc).all()
            return render_template('items/edit.html', item=item, categories=categories, uoms=uoms)
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('Error updating item')
            flash('An unexpected error occurred. Please try again or contact support.', 'danger')
            categories = ItemCategory.query.filter_by(status_code='A').order_by(ItemCategory.category_desc).all()
            uoms = UnitOfMeasure.query.order_by(UnitOfMeasure.uom_desc).all()
            return render_template('items/edit.html', item=item, categories=categories, uoms=uoms)
    
    # GET request
    categories = ItemCategory.query.filter_by(status_code='A').order_by(ItemCategory.category_desc).all()
    uoms = UnitOfMeasure.query.order_by(UnitOfMeasure.uom_desc).all()
    return render_template('items/edit.html', item=item, categories=categories, uoms=uoms)

@items_bp.route('/<int:item_id>/inactivate', methods=['POST'])
@login_required
@feature_required('item_management')
def inactivate_item(item_id):
    """Inactivate item (no physical delete) - CUSTODIAN only"""
    item = Item.query.get_or_404(item_id)
    
    # Check if already inactive
    if item.status_code == 'I':
        flash(f'Item "{item.item_name}" is already inactive', 'info')
        return redirect(url_for('items.view_item', item_id=item_id))
    
    # Check if item can be inactivated
    can_inactivate, message = check_item_can_be_inactivated(item_id)
    
    if not can_inactivate:
        flash(message, 'danger')
        return redirect(url_for('items.view_item', item_id=item_id))
    
    try:
        # Inactivate item
        item.status_code = 'I'
        add_audit_fields(item, current_user, is_new=False)
        
        db.session.commit()
        
        flash(f'Item "{item.item_name}" has been inactivated', 'success')
        return redirect(url_for('items.list_items'))
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error inactivating item')
        flash('An unexpected error occurred. Please try again or contact support.', 'danger')
        return redirect(url_for('items.view_item', item_id=item_id))

@items_bp.route('/<int:item_id>/activate', methods=['POST'])
@login_required
@feature_required('item_management')
def activate_item(item_id):
    """Reactivate an inactive item - CUSTODIAN only"""
    item = Item.query.get_or_404(item_id)
    
    if item.status_code == 'A':
        flash(f'Item "{item.item_name}" is already active', 'info')
        return redirect(url_for('items.view_item', item_id=item_id))
    
    try:
        item.status_code = 'A'
        add_audit_fields(item, current_user, is_new=False)
        
        db.session.commit()
        
        flash(f'Item "{item.item_name}" has been reactivated', 'success')
        return redirect(url_for('items.view_item', item_id=item_id))
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error activating item')
        flash('An unexpected error occurred. Please try again or contact support.', 'danger')
        return redirect(url_for('items.view_item', item_id=item_id))
