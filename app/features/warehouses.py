"""
Warehouse Management Routes (CUSTODIAN Role)

This module implements comprehensive CRUD operations for warehouse management
with strict validation, business rules, and RBAC based on warehouse_management feature.

Permission-Based Access Control:
- All operations restricted to CUSTODIAN role via @feature_required decorator

Validation Rules:
- warehouse_name: Mandatory, unique per organization, max TEXT length
- warehouse_type: Must be one of: MAIN-HUB, SUB-HUB
- address1_text: Mandatory, max 255 characters
- address2_text: Optional, max 255 characters
- parish_code: Mandatory, must exist in Parish table
- contact_name: Mandatory, max 50 characters, UPPERCASE
- phone_no: Mandatory, max 20 characters, numeric validation
- email_text: Optional, max 100 characters, email format validation
- custodian_id: Mandatory, must exist in Custodian table
- status_code: 'A' (Active) or 'I' (Inactive)
- When status='I', reason_desc is required
- When status='A', reason_desc must be null
- Optimistic locking via version_nbr
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from datetime import datetime
from sqlalchemy import or_, and_
from sqlalchemy.exc import IntegrityError
import re

from app.db import db
from app.db.models import Warehouse, Parish, Custodian
from app.core.decorators import feature_required
from app.core.audit import add_audit_fields
from app.core.phone_utils import validate_phone_format, get_phone_validation_error, PHONE_FORMAT_EXAMPLE

warehouses_bp = Blueprint('warehouses', __name__, url_prefix='/warehouses')

# Constants for validation
WAREHOUSE_TYPES = ['MAIN-HUB', 'SUB-HUB']
STATUS_CODES = ['A', 'I']  # Active, Inactive

def validate_email(email):
    """Validate email format"""
    if not email:
        return True  # Optional field
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def validate_phone(phone):
    """
    Validate phone number format: +1 (XXX) XXX-XXXX
    Uses centralized phone validation from phone_utils
    """
    if not phone:
        return False
    return validate_phone_format(phone)

def validate_warehouse_data(form_data, is_update=False, warehouse_id=None):
    """
    Validate warehouse data against all business rules.
    Returns (is_valid, errors_dict)
    """
    errors = {}
    
    # Get form data
    warehouse_name = form_data.get('warehouse_name', '').strip()
    warehouse_type = form_data.get('warehouse_type', '').strip()
    address1_text = form_data.get('address1_text', '').strip()
    address2_text = form_data.get('address2_text', '').strip()
    parish_code = form_data.get('parish_code', '').strip()
    contact_name = form_data.get('contact_name', '').strip()
    phone_no = form_data.get('phone_no', '').strip()
    email_text = form_data.get('email_text', '').strip()
    custodian_id = form_data.get('custodian_id', '').strip()
    status_code = form_data.get('status_code', '').strip()
    reason_desc = form_data.get('reason_desc', '').strip()
    
    # Warehouse Name validation
    if not warehouse_name:
        errors['warehouse_name'] = 'Warehouse name is required'
    else:
        # Check uniqueness
        query = Warehouse.query.filter(
            db.func.upper(Warehouse.warehouse_name) == warehouse_name.upper()
        )
        if is_update and warehouse_id:
            query = query.filter(Warehouse.warehouse_id != warehouse_id)
        if query.first():
            errors['warehouse_name'] = 'A warehouse with this name already exists'
    
    # Warehouse Type validation
    if not warehouse_type:
        errors['warehouse_type'] = 'Warehouse type is required'
    elif warehouse_type not in WAREHOUSE_TYPES:
        errors['warehouse_type'] = f'Warehouse type must be one of: {", ".join(WAREHOUSE_TYPES)}'
    
    # Address validation
    if not address1_text:
        errors['address1_text'] = 'Address line 1 is required'
    elif len(address1_text) > 255:
        errors['address1_text'] = 'Address line 1 must not exceed 255 characters'
    
    if address2_text and len(address2_text) > 255:
        errors['address2_text'] = 'Address line 2 must not exceed 255 characters'
    
    # Parish validation
    if not parish_code:
        errors['parish_code'] = 'Parish is required'
    else:
        parish = Parish.query.filter_by(parish_code=parish_code).first()
        if not parish:
            errors['parish_code'] = 'Invalid parish selected'
    
    # Contact Name validation
    if not contact_name:
        errors['contact_name'] = 'Contact name is required'
    elif len(contact_name) > 50:
        errors['contact_name'] = 'Contact name must not exceed 50 characters'
    
    # Phone Number validation
    if not phone_no:
        errors['phone_no'] = 'Phone number is required'
    elif not validate_phone(phone_no):
        errors['phone_no'] = get_phone_validation_error('Phone number')
    
    # Email validation
    if email_text:
        if len(email_text) > 100:
            errors['email_text'] = 'Email must not exceed 100 characters'
        elif not validate_email(email_text):
            errors['email_text'] = 'Invalid email format'
    
    # Custodian validation
    if not custodian_id:
        errors['custodian_id'] = 'Custodian is required'
    else:
        try:
            custodian_id_int = int(custodian_id)
            custodian = Custodian.query.get(custodian_id_int)
            if not custodian:
                errors['custodian_id'] = 'Invalid custodian selected'
        except ValueError:
            errors['custodian_id'] = 'Invalid custodian ID'
    
    # Status validation
    if not status_code:
        errors['status_code'] = 'Status is required'
    elif status_code not in STATUS_CODES:
        errors['status_code'] = 'Status must be A (Active) or I (Inactive)'
    
    # Status-Reason interdependent validation
    if status_code == 'I':
        if not reason_desc:
            errors['reason_desc'] = 'Reason is required for inactive warehouses'
        elif len(reason_desc) > 255:
            errors['reason_desc'] = 'Reason must not exceed 255 characters'
    elif status_code == 'A':
        if reason_desc:
            errors['reason_desc'] = 'Active warehouses cannot have a reason for inactivation'
    
    return (len(errors) == 0, errors)


@warehouses_bp.route('/')
@login_required
@feature_required('warehouse_management')
def list_warehouses():
    """List all warehouses with filtering and summary counts"""
    # Get filter parameters
    current_filter = request.args.get('filter', 'all').strip().lower()
    search_query = request.args.get('search', '').strip()
    
    # Calculate summary counts
    total_count = Warehouse.query.count()
    active_count = Warehouse.query.filter_by(status_code='A').count()
    inactive_count = Warehouse.query.filter_by(status_code='I').count()
    
    counts = {
        'total': total_count,
        'active': active_count,
        'inactive': inactive_count
    }
    
    # Build query based on filter
    query = Warehouse.query
    
    if current_filter == 'active':
        query = query.filter_by(status_code='A')
    elif current_filter == 'inactive':
        query = query.filter_by(status_code='I')
    # else 'all' - no filter
    
    # Apply search if provided
    if search_query:
        search_pattern = f'%{search_query}%'
        query = query.filter(
            or_(
                Warehouse.warehouse_name.ilike(search_pattern),
                Warehouse.address1_text.ilike(search_pattern),
                Warehouse.contact_name.ilike(search_pattern)
            )
        )
    
    # Order by warehouse name
    warehouses = query.order_by(Warehouse.warehouse_name).all()
    
    return render_template(
        'warehouses/list.html',
        warehouses=warehouses,
        counts=counts,
        current_filter=current_filter,
        search_query=search_query
    )


@warehouses_bp.route('/create', methods=['GET', 'POST'])
@login_required
@feature_required('warehouse_management')
def create_warehouse():
    """Create new warehouse"""
    if request.method == 'POST':
        # Validate form data
        is_valid, errors = validate_warehouse_data(request.form)
        
        if not is_valid:
            # Show validation errors
            for field, error in errors.items():
                flash(error, 'danger')
            
            # Return to form with entered data
            parishes = Parish.query.order_by(Parish.parish_name).all()
            custodians = Custodian.query.order_by(Custodian.custodian_name).all()
            
            return render_template(
                'warehouses/create.html',
                parishes=parishes,
                custodians=custodians,
                warehouse_types=WAREHOUSE_TYPES,
                form_data=request.form,
                errors=errors
            )
        
        try:
            # Create warehouse
            warehouse = Warehouse()
            warehouse.warehouse_name = request.form.get('warehouse_name').strip().upper()
            warehouse.warehouse_type = request.form.get('warehouse_type').strip()
            warehouse.address1_text = request.form.get('address1_text').strip()
            warehouse.address2_text = request.form.get('address2_text', '').strip() or None
            warehouse.parish_code = request.form.get('parish_code').strip()
            warehouse.contact_name = request.form.get('contact_name').strip().upper()
            warehouse.phone_no = request.form.get('phone_no').strip()
            warehouse.email_text = request.form.get('email_text', '').strip() or None
            from app.security.param_validation import safe_id
            custodian_id = safe_id(request.form.get('custodian_id'))
            if custodian_id <= 0:
                flash('Invalid custodian selected', 'danger')
                return redirect(url_for('warehouses.create_warehouse'))
            warehouse.custodian_id = custodian_id
            warehouse.status_code = request.form.get('status_code').strip()
            warehouse.reason_desc = request.form.get('reason_desc', '').strip() or None
            
            # Audit fields
            add_audit_fields(warehouse, current_user, is_new=True)
            
            db.session.add(warehouse)
            db.session.commit()
            
            flash(f'Warehouse "{warehouse.warehouse_name}" created successfully', 'success')
            return redirect(url_for('warehouses.list_warehouses', filter='all'))
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('Error creating warehouse')
            flash('An error occurred while creating the warehouse. Please try again or contact support.', 'danger')
            
            parishes = Parish.query.order_by(Parish.parish_name).all()
            custodians = Custodian.query.order_by(Custodian.custodian_name).all()
            
            return render_template(
                'warehouses/create.html',
                parishes=parishes,
                custodians=custodians,
                warehouse_types=WAREHOUSE_TYPES,
                form_data=request.form
            )
    
    # GET request
    parishes = Parish.query.order_by(Parish.parish_name).all()
    custodians = Custodian.query.order_by(Custodian.custodian_name).all()
    
    return render_template(
        'warehouses/create.html',
        parishes=parishes,
        custodians=custodians,
        warehouse_types=WAREHOUSE_TYPES
    )


@warehouses_bp.route('/<int:warehouse_id>')
@login_required
@feature_required('warehouse_management')
def view_warehouse(warehouse_id):
    """View warehouse details"""
    warehouse = Warehouse.query.get_or_404(warehouse_id)
    return render_template('warehouses/view.html', warehouse=warehouse)


@warehouses_bp.route('/<int:warehouse_id>/edit', methods=['GET', 'POST'])
@login_required
@feature_required('warehouse_management')
def edit_warehouse(warehouse_id):
    """Edit existing warehouse"""
    warehouse = Warehouse.query.get_or_404(warehouse_id)
    
    if request.method == 'POST':
        # Optimistic locking check
        submitted_version = request.form.get('version_nbr', type=int)
        if submitted_version != warehouse.version_nbr:
            flash('This warehouse record was updated by another user. Please reload and try again.', 'warning')
            return redirect(url_for('warehouses.view_warehouse', warehouse_id=warehouse_id))
        
        # Validate form data
        is_valid, errors = validate_warehouse_data(request.form, is_update=True, warehouse_id=warehouse_id)
        
        if not is_valid:
            # Show validation errors
            for field, error in errors.items():
                flash(error, 'danger')
            
            # Return to form with entered data
            parishes = Parish.query.order_by(Parish.parish_name).all()
            custodians = Custodian.query.order_by(Custodian.custodian_name).all()
            
            return render_template(
                'warehouses/edit.html',
                warehouse=warehouse,
                parishes=parishes,
                custodians=custodians,
                warehouse_types=WAREHOUSE_TYPES,
                form_data=request.form,
                errors=errors
            )
        
        try:
            from app.security.param_validation import safe_id
            
            # Update warehouse
            warehouse.warehouse_name = request.form.get('warehouse_name').strip().upper()
            warehouse.warehouse_type = request.form.get('warehouse_type').strip()
            warehouse.address1_text = request.form.get('address1_text').strip()
            warehouse.address2_text = request.form.get('address2_text', '').strip() or None
            warehouse.parish_code = request.form.get('parish_code').strip()
            warehouse.contact_name = request.form.get('contact_name').strip().upper()
            warehouse.phone_no = request.form.get('phone_no').strip()
            warehouse.email_text = request.form.get('email_text', '').strip() or None
            custodian_id = safe_id(request.form.get('custodian_id'))
            if custodian_id <= 0:
                flash('Invalid custodian selected', 'danger')
                return redirect(url_for('warehouses.edit_warehouse', warehouse_id=warehouse_id))
            warehouse.custodian_id = custodian_id
            warehouse.status_code = request.form.get('status_code').strip()
            warehouse.reason_desc = request.form.get('reason_desc', '').strip() or None
            
            # Audit fields
            add_audit_fields(warehouse, current_user, is_new=False)
            
            db.session.commit()
            
            flash(f'Warehouse "{warehouse.warehouse_name}" updated successfully', 'success')
            return redirect(url_for('warehouses.list_warehouses', filter='all'))
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('Error updating warehouse')
            flash('An error occurred while updating the warehouse. Please try again or contact support.', 'danger')
            
            parishes = Parish.query.order_by(Parish.parish_name).all()
            custodians = Custodian.query.order_by(Custodian.custodian_name).all()
            
            return render_template(
                'warehouses/edit.html',
                warehouse=warehouse,
                parishes=parishes,
                custodians=custodians,
                warehouse_types=WAREHOUSE_TYPES,
                form_data=request.form
            )
    
    # GET request
    parishes = Parish.query.order_by(Parish.parish_name).all()
    custodians = Custodian.query.order_by(Custodian.custodian_name).all()
    
    return render_template(
        'warehouses/edit.html',
        warehouse=warehouse,
        parishes=parishes,
        custodians=custodians,
        warehouse_types=WAREHOUSE_TYPES
    )


@warehouses_bp.route('/<int:warehouse_id>/delete', methods=['POST'])
@login_required
@feature_required('warehouse_management')
def delete_warehouse(warehouse_id):
    """Delete warehouse with FK reference checks"""
    warehouse = Warehouse.query.get_or_404(warehouse_id)
    
    # Check for FK references
    # Check inventory table
    from app.db.models import Inventory
    if Inventory.query.filter_by(inventory_id=warehouse_id).first():
        flash('This warehouse cannot be deleted because it is referenced in inventory records.', 'danger')
        return redirect(url_for('warehouses.view_warehouse', warehouse_id=warehouse_id))
    
    # Check user_warehouse table
    if warehouse.users and len(warehouse.users) > 0:
        flash('This warehouse cannot be deleted because it is assigned to users.', 'danger')
        return redirect(url_for('warehouses.view_warehouse', warehouse_id=warehouse_id))
    
    try:
        warehouse_name = warehouse.warehouse_name
        db.session.delete(warehouse)
        db.session.commit()
        
        flash(f'Warehouse "{warehouse_name}" deleted successfully', 'success')
        return redirect(url_for('warehouses.list_warehouses'))
        
    except IntegrityError as e:
        db.session.rollback()
        flash('This warehouse cannot be deleted because it is referenced by other records.', 'danger')
        return redirect(url_for('warehouses.view_warehouse', warehouse_id=warehouse_id))
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error deleting warehouse')
        flash('An error occurred while deleting the warehouse. Please try again or contact support.', 'danger')
        return redirect(url_for('warehouses.view_warehouse', warehouse_id=warehouse_id))
