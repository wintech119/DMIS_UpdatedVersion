"""
Unit of Measure (UOM) Management Blueprint

This module provides CRUD operations for managing units of measure (UOM).
Access is restricted to users with the CUSTODIAN role.

Features:
- Create, Read, Update, Delete UOM records
- Uppercase enforcement for uom_code
- Optimistic locking via version_nbr
- Referential integrity checks before deletion
- Audit trail tracking (create_by_id, update_by_id, timestamps)
- Status-based filtering (Active/Inactive)
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from sqlalchemy import or_
from app.db.models import db, UnitOfMeasure, Item, Inventory, DonationIntakeItem, ReliefPkgItem, TransferItem
from app.core.decorators import feature_required
from app.core.audit import add_audit_fields

# Create Blueprint
uom_bp = Blueprint('uom', __name__, url_prefix='/uom')

# Constants
STATUS_CODES = ['A', 'I']
MAX_UOM_CODE_LENGTH = 25
MAX_UOM_DESC_LENGTH = 60
MAX_COMMENTS_LENGTH = 300

def validate_uom_data(form_data, is_update=False, uom_code=None):
    """
    Validate unit of measure data against all business rules.
    Returns (is_valid, errors_dict, normalized_data_dict)
    
    The normalized_data dict contains cleaned/normalized values that should be used
    for persistence (e.g., uom_code converted to UPPERCASE).
    """
    errors = {}
    
    # Get form data and normalize
    code = form_data.get('uom_code', '').strip().upper()
    desc = form_data.get('uom_desc', '').strip()
    comments = form_data.get('comments_text', '').strip() if form_data.get('comments_text') else None
    status = form_data.get('status_code', '').strip()
    
    # Build normalized data dictionary
    normalized_data = {
        'uom_code': code,
        'uom_desc': desc,
        'comments_text': comments,
        'status_code': status
    }
    
    # UOM Code validation
    if not code:
        errors['uom_code'] = 'UOM code is required'
    else:
        # Validate length (after uppercase conversion)
        if len(code) > MAX_UOM_CODE_LENGTH:
            errors['uom_code'] = f'UOM code must not exceed {MAX_UOM_CODE_LENGTH} characters'
        
        # Check uniqueness (code is already uppercase)
        query = UnitOfMeasure.query.filter(
            db.func.upper(UnitOfMeasure.uom_code) == code
        )
        if is_update and uom_code:
            query = query.filter(UnitOfMeasure.uom_code != uom_code)
        if query.first():
            errors['uom_code'] = 'A unit of measure with this code already exists'
    
    # UOM Description validation
    if not desc:
        errors['uom_desc'] = 'UOM description is required'
    elif len(desc) > MAX_UOM_DESC_LENGTH:
        errors['uom_desc'] = f'UOM description must not exceed {MAX_UOM_DESC_LENGTH} characters'
    
    # Comments validation
    if comments and len(comments) > MAX_COMMENTS_LENGTH:
        errors['comments_text'] = f'Comments must not exceed {MAX_COMMENTS_LENGTH} characters'
    
    # Status Code validation
    if not status:
        errors['status_code'] = 'Status code is required'
    elif status not in STATUS_CODES:
        errors['status_code'] = f'Status code must be one of: {", ".join(STATUS_CODES)}'
    
    return len(errors) == 0, errors, normalized_data

@uom_bp.route('/')
@login_required
@feature_required('uom_management')
def list_uom():
    """
    Display list of all units of measure with filter and search capabilities.
    """
    # Get filter parameter
    filter_type = request.args.get('filter', 'all')
    search_query = request.args.get('search', '').strip()
    
    # Base query
    query = UnitOfMeasure.query
    
    # Apply filters
    if filter_type == 'active':
        query = query.filter(UnitOfMeasure.status_code == 'A')
    elif filter_type == 'inactive':
        query = query.filter(UnitOfMeasure.status_code == 'I')
    
    # Apply search
    if search_query:
        search_pattern = f'%{search_query}%'
        query = query.filter(
            or_(
                UnitOfMeasure.uom_code.ilike(search_pattern),
                UnitOfMeasure.uom_desc.ilike(search_pattern)
            )
        )
    
    # Order by UOM code
    uoms = query.order_by(UnitOfMeasure.uom_code).all()
    
    # Calculate metrics
    total_uoms = UnitOfMeasure.query.count()
    active_uoms = UnitOfMeasure.query.filter_by(status_code='A').count()
    inactive_uoms = UnitOfMeasure.query.filter_by(status_code='I').count()
    
    metrics = {
        'total_uoms': total_uoms,
        'active_uoms': active_uoms,
        'inactive_uoms': inactive_uoms
    }
    
    return render_template('uom/list.html', 
                         uoms=uoms, 
                         metrics=metrics,
                         filter_type=filter_type,
                         search_query=search_query)

@uom_bp.route('/create', methods=['GET', 'POST'])
@login_required
@feature_required('uom_management')
def create_uom():
    """
    Create a new unit of measure.
    """
    if request.method == 'POST':
        # Validate form data and get normalized values
        is_valid, errors, normalized_data = validate_uom_data(request.form)
        
        # Convert None to empty string for template display compatibility
        display_data = {k: (v if v is not None else '') for k, v in normalized_data.items()}
        
        if not is_valid:
            # Flash each error
            for field, error in errors.items():
                flash(error, 'danger')
            # Re-render form with errors using normalized data
            return render_template('uom/create.html', 
                                 form_data=display_data,
                                 errors=errors)
        
        try:
            # Create new UOM using normalized data
            uom = UnitOfMeasure()
            
            # Set normalized form data (uom_code is already UPPERCASE from validator)
            uom.uom_code = normalized_data['uom_code']
            uom.uom_desc = normalized_data['uom_desc']
            uom.comments_text = normalized_data['comments_text']
            uom.status_code = normalized_data['status_code']
            
            # Add audit fields
            add_audit_fields(uom, current_user, is_new=True)
            
            # Save to database
            db.session.add(uom)
            db.session.commit()
            
            flash(f'Unit of measure "{uom.uom_code}" created successfully', 'success')
            return redirect(url_for('uom.view_uom', uom_code=uom.uom_code))
            
        except IntegrityError as e:
            db.session.rollback()
            flash('Failed to create UOM. A unit with this code may already exist.', 'danger')
            return render_template('uom/create.html', 
                                 form_data=display_data,
                                 errors={})
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('Error creating unit of measure')
            flash('An unexpected error occurred. Please try again or contact support.', 'danger')
            return render_template('uom/create.html', 
                                 form_data=display_data,
                                 errors={})
    
    # GET request - show empty form
    return render_template('uom/create.html', 
                         form_data={},
                         errors={})

@uom_bp.route('/<string:uom_code>')
@login_required
@feature_required('uom_management')
def view_uom(uom_code):
    """
    Display details of a specific unit of measure.
    """
    uom = UnitOfMeasure.query.get_or_404(uom_code)
    
    # Check if UOM is referenced by other tables (for delete button visibility)
    is_in_use = check_uom_references(uom_code)
    
    return render_template('uom/view.html', 
                         uom=uom,
                         is_in_use=is_in_use)

@uom_bp.route('/<string:uom_code>/edit', methods=['GET', 'POST'])
@login_required
@feature_required('uom_management')
def edit_uom(uom_code):
    """
    Edit an existing unit of measure.
    Implements optimistic locking via version_nbr.
    """
    uom = UnitOfMeasure.query.get_or_404(uom_code)
    
    if request.method == 'POST':
        # Get submitted version number for optimistic locking
        submitted_version = request.form.get('version_nbr', type=int)
        
        # Check for stale data
        if submitted_version != uom.version_nbr:
            flash('This unit of measure has been modified by another user. Please reload and try again.', 'warning')
            return redirect(url_for('uom.edit_uom', uom_code=uom_code))
        
        # Validate form data and get normalized values
        is_valid, errors, normalized_data = validate_uom_data(request.form, is_update=True, uom_code=uom_code)
        
        # Convert None to empty string for template display compatibility
        display_data = {k: (v if v is not None else '') for k, v in normalized_data.items()}
        
        if not is_valid:
            # Flash each error
            for field, error in errors.items():
                flash(error, 'danger')
            # Re-render form with errors using normalized data
            return render_template('uom/edit.html', 
                                 uom=uom,
                                 form_data=display_data,
                                 errors=errors)
        
        try:
            # Update UOM fields using normalized data (uom_code is already UPPERCASE from validator)
            uom.uom_code = normalized_data['uom_code']
            uom.uom_desc = normalized_data['uom_desc']
            uom.comments_text = normalized_data['comments_text']
            uom.status_code = normalized_data['status_code']
            
            # Update audit fields
            add_audit_fields(uom, current_user, is_new=False)
            
            # Save to database (version_nbr will be incremented automatically)
            db.session.commit()
            
            flash(f'Unit of measure "{uom.uom_code}" updated successfully', 'success')
            return redirect(url_for('uom.view_uom', uom_code=uom.uom_code))
            
        except StaleDataError:
            db.session.rollback()
            flash('This unit of measure has been modified by another user. Please reload and try again.', 'warning')
            return redirect(url_for('uom.edit_uom', uom_code=uom_code))
        except IntegrityError as e:
            db.session.rollback()
            flash('Failed to update UOM. A unit with this code may already exist.', 'danger')
            return render_template('uom/edit.html', 
                                 uom=uom,
                                 form_data=display_data,
                                 errors={})
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('Error updating unit of measure')
            flash('An unexpected error occurred. Please try again or contact support.', 'danger')
            return render_template('uom/edit.html', 
                                 uom=uom,
                                 form_data=display_data,
                                 errors={})
    
    # GET request - show form with current data
    return render_template('uom/edit.html', 
                         uom=uom,
                         form_data={},
                         errors={})

@uom_bp.route('/<string:uom_code>/delete', methods=['POST'])
@login_required
@feature_required('uom_management')
def delete_uom(uom_code):
    """
    Delete a unit of measure.
    Implements referential integrity checks - cannot delete if in use.
    """
    uom = UnitOfMeasure.query.get_or_404(uom_code)
    
    # Check if UOM is referenced by other records
    if check_uom_references(uom_code):
        flash('This unit of measure cannot be deleted because it is in use by existing records.', 'danger')
        return redirect(url_for('uom.view_uom', uom_code=uom_code))
    
    try:
        db.session.delete(uom)
        db.session.commit()
        flash(f'Unit of measure "{uom_code}" deleted successfully', 'success')
        return redirect(url_for('uom.list_uom'))
    except IntegrityError:
        db.session.rollback()
        flash('Cannot delete this unit of measure because it is referenced by other records.', 'danger')
        return redirect(url_for('uom.view_uom', uom_code=uom_code))
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error deleting unit of measure')
        flash('An unexpected error occurred. Please try again or contact support.', 'danger')
        return redirect(url_for('uom.view_uom', uom_code=uom_code))

def check_uom_references(uom_code):
    """
    Check if a UOM is referenced by any other tables.
    Returns True if the UOM is in use, False otherwise.
    """
    # Check items (default_uom_code)
    item_count = Item.query.filter(Item.default_uom_code == uom_code).count()
    if item_count > 0:
        return True
    
    # Check inventory
    inventory_count = Inventory.query.filter(Inventory.uom_code == uom_code).count()
    if inventory_count > 0:
        return True
    
    # Check donation intake items
    donation_item_count = DonationIntakeItem.query.filter(DonationIntakeItem.uom_code == uom_code).count()
    if donation_item_count > 0:
        return True
    
    # Check relief package items
    reliefpkg_item_count = ReliefPkgItem.query.filter(ReliefPkgItem.uom_code == uom_code).count()
    if reliefpkg_item_count > 0:
        return True
    
    # Check transfer items
    transfer_item_count = TransferItem.query.filter(TransferItem.uom_code == uom_code).count()
    if transfer_item_count > 0:
        return True
    
    return False
