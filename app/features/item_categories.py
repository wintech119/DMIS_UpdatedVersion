"""
Item Category Management Routes (CUSTODIAN Role)

This module implements comprehensive CRUD operations for item category management
with strict validation, business rules, and RBAC based on item_category_management feature.

Permission-Based Access Control:
- All operations restricted to CUSTODIAN role via @feature_required decorator

Validation Rules:
- category_code: Mandatory, unique, UPPERCASE, max 30 characters
- category_desc: Mandatory, max 60 characters, trimmed
- comments_text: Optional, max 300 characters
- status_code: 'A' (Active) or 'I' (Inactive)
- Optimistic locking via version_nbr
- Auto-populate audit fields: create_by_id, create_dtime, update_by_id, update_dtime

Delete Rules:
- Cannot delete if referenced by any items (referential integrity)
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from datetime import datetime
from sqlalchemy import or_, and_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from app.db import db
from app.db.models import ItemCategory, Item
from app.core.decorators import feature_required
from app.core.audit import add_audit_fields

item_categories_bp = Blueprint('item_categories', __name__, url_prefix='/item-categories')

# Constants for validation
STATUS_CODES = ['A', 'I']  # Active, Inactive
MAX_CATEGORY_CODE_LENGTH = 30
MAX_CATEGORY_DESC_LENGTH = 60
MAX_COMMENTS_LENGTH = 300

def validate_category_data(form_data, is_update=False, category_id=None):
    """
    Validate item category data against all business rules.
    Returns (is_valid, errors_dict, normalized_data_dict)
    
    The normalized_data dict contains cleaned/normalized values that should be used
    for persistence (e.g., category_code converted to UPPERCASE).
    """
    errors = {}
    
    # Get form data and normalize
    category_code = form_data.get('category_code', '').strip().upper()
    category_desc = form_data.get('category_desc', '').strip()
    comments_text = form_data.get('comments_text', '').strip() if form_data.get('comments_text') else None
    status_code = form_data.get('status_code', '').strip()
    
    # Build normalized data dictionary
    normalized_data = {
        'category_code': category_code,
        'category_desc': category_desc,
        'comments_text': comments_text,
        'status_code': status_code
    }
    
    # Category Code validation
    if not category_code:
        errors['category_code'] = 'Category code is required'
    else:
        # Validate length (after uppercase conversion)
        if len(category_code) > MAX_CATEGORY_CODE_LENGTH:
            errors['category_code'] = f'Category code must not exceed {MAX_CATEGORY_CODE_LENGTH} characters'
        
        # Check uniqueness (category_code is already uppercase)
        query = ItemCategory.query.filter(
            db.func.upper(ItemCategory.category_code) == category_code
        )
        if is_update and category_id:
            query = query.filter(ItemCategory.category_id != category_id)
        if query.first():
            errors['category_code'] = 'A category with this code already exists'
    
    # Category Description validation
    if not category_desc:
        errors['category_desc'] = 'Category description is required'
    elif len(category_desc) > MAX_CATEGORY_DESC_LENGTH:
        errors['category_desc'] = f'Category description must not exceed {MAX_CATEGORY_DESC_LENGTH} characters'
    
    # Comments validation
    if comments_text and len(comments_text) > MAX_COMMENTS_LENGTH:
        errors['comments_text'] = f'Comments must not exceed {MAX_COMMENTS_LENGTH} characters'
    
    # Status Code validation
    if not status_code:
        errors['status_code'] = 'Status code is required'
    elif status_code not in STATUS_CODES:
        errors['status_code'] = f'Status code must be one of: {", ".join(STATUS_CODES)}'
    
    return len(errors) == 0, errors, normalized_data

@item_categories_bp.route('/')
@login_required
@feature_required('item_category_management')
def list_categories():
    """
    Display list of all item categories with filter and search capabilities.
    """
    # Get filter parameter
    filter_type = request.args.get('filter', 'all')
    search_query = request.args.get('search', '').strip()
    
    # Base query
    query = ItemCategory.query
    
    # Apply filters
    if filter_type == 'active':
        query = query.filter(ItemCategory.status_code == 'A')
    elif filter_type == 'inactive':
        query = query.filter(ItemCategory.status_code == 'I')
    
    # Apply search
    if search_query:
        search_pattern = f'%{search_query}%'
        query = query.filter(
            or_(
                ItemCategory.category_code.ilike(search_pattern),
                ItemCategory.category_desc.ilike(search_pattern)
            )
        )
    
    # Order by category code
    categories = query.order_by(ItemCategory.category_code).all()
    
    # Calculate metrics
    total_categories = ItemCategory.query.count()
    active_categories = ItemCategory.query.filter_by(status_code='A').count()
    inactive_categories = ItemCategory.query.filter_by(status_code='I').count()
    
    metrics = {
        'total_categories': total_categories,
        'active_categories': active_categories,
        'inactive_categories': inactive_categories
    }
    
    return render_template('item_categories/list.html', 
                         categories=categories, 
                         metrics=metrics,
                         filter_type=filter_type,
                         search_query=search_query)

@item_categories_bp.route('/create', methods=['GET', 'POST'])
@login_required
@feature_required('item_category_management')
def create_category():
    """
    Create a new item category.
    """
    if request.method == 'POST':
        # Validate form data and get normalized values
        is_valid, errors, normalized_data = validate_category_data(request.form)
        
        # Convert None to empty string for template display compatibility
        display_data = {k: (v if v is not None else '') for k, v in normalized_data.items()}
        
        if not is_valid:
            # Flash each error
            for field, error in errors.items():
                flash(error, 'danger')
            # Re-render form with errors using normalized data
            return render_template('item_categories/create.html', 
                                 form_data=display_data,
                                 errors=errors)
        
        try:
            # Create new category using normalized data
            category = ItemCategory()
            
            # Set normalized form data (category_code is already UPPERCASE from validator)
            category.category_code = normalized_data['category_code']
            category.category_desc = normalized_data['category_desc']
            category.comments_text = normalized_data['comments_text']
            category.status_code = normalized_data['status_code']
            
            # Add audit fields
            add_audit_fields(category, current_user, is_new=True)
            
            # Save to database
            db.session.add(category)
            db.session.commit()
            
            flash(f'Item category "{category.category_code}" created successfully', 'success')
            return redirect(url_for('item_categories.view_category', category_id=category.category_id))
            
        except IntegrityError as e:
            db.session.rollback()
            flash('Failed to create category. A category with this code may already exist.', 'danger')
            return render_template('item_categories/create.html', 
                                 form_data=display_data,
                                 errors={})
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('Error creating item category')
            flash('An unexpected error occurred. Please try again or contact support.', 'danger')
            return render_template('item_categories/create.html', 
                                 form_data=display_data,
                                 errors={})
    
    # GET request - show empty form
    return render_template('item_categories/create.html', 
                         form_data={},
                         errors={})

@item_categories_bp.route('/<int:category_id>')
@login_required
@feature_required('item_category_management')
def view_category(category_id):
    """
    View details of a specific item category.
    """
    category = ItemCategory.query.get_or_404(category_id)
    
    # Count items using this category
    item_count = Item.query.filter_by(category_id=category_id).count()
    
    return render_template('item_categories/view.html', 
                         category=category,
                         item_count=item_count)

@item_categories_bp.route('/<int:category_id>/edit', methods=['GET', 'POST'])
@login_required
@feature_required('item_category_management')
def edit_category(category_id):
    """
    Edit an existing item category.
    """
    category = ItemCategory.query.get_or_404(category_id)
    
    if request.method == 'POST':
        # Get submitted version number for optimistic locking
        submitted_version = request.form.get('version_nbr', type=int)
        
        # Check for stale data
        if submitted_version != category.version_nbr:
            flash('This category has been modified by another user. Please reload and try again.', 'warning')
            return redirect(url_for('item_categories.edit_category', category_id=category_id))
        
        # Validate form data and get normalized values
        is_valid, errors, normalized_data = validate_category_data(request.form, is_update=True, category_id=category_id)
        
        # Convert None to empty string for template display compatibility
        display_data = {k: (v if v is not None else '') for k, v in normalized_data.items()}
        
        if not is_valid:
            # Flash each error
            for field, error in errors.items():
                flash(error, 'danger')
            # Re-render form with errors using normalized data
            return render_template('item_categories/edit.html', 
                                 category=category,
                                 form_data=display_data,
                                 errors=errors)
        
        try:
            # Update category fields using normalized data (category_code is already UPPERCASE from validator)
            category.category_code = normalized_data['category_code']
            category.category_desc = normalized_data['category_desc']
            category.comments_text = normalized_data['comments_text']
            category.status_code = normalized_data['status_code']
            
            # Update audit fields
            add_audit_fields(category, current_user, is_new=False)
            
            # Save to database (version_nbr will be incremented automatically)
            db.session.commit()
            
            flash(f'Item category "{category.category_code}" updated successfully', 'success')
            return redirect(url_for('item_categories.view_category', category_id=category.category_id))
            
        except StaleDataError:
            db.session.rollback()
            flash('This category has been modified by another user. Please reload and try again.', 'warning')
            return redirect(url_for('item_categories.edit_category', category_id=category_id))
        except IntegrityError as e:
            db.session.rollback()
            flash('Failed to update category. A category with this code may already exist.', 'danger')
            return render_template('item_categories/edit.html', 
                                 category=category,
                                 form_data=display_data,
                                 errors={})
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('Error updating item category')
            flash('An unexpected error occurred. Please try again or contact support.', 'danger')
            return render_template('item_categories/edit.html', 
                                 category=category,
                                 form_data=display_data,
                                 errors={})
    
    # GET request - show form with current data
    return render_template('item_categories/edit.html', 
                         category=category,
                         form_data=None,
                         errors={})

@item_categories_bp.route('/<int:category_id>/delete', methods=['POST'])
@login_required
@feature_required('item_category_management')
def delete_category(category_id):
    """
    Delete an item category.
    Blocked if category is referenced by any items (referential integrity).
    """
    category = ItemCategory.query.get_or_404(category_id)
    
    # Check referential integrity - prevent deletion if category is in use
    item_count = Item.query.filter_by(category_id=category_id).count()
    
    if item_count > 0:
        flash(f'Cannot delete category "{category.category_code}" because it is in use by {item_count} item(s). Please reassign or remove those items first.', 'danger')
        return redirect(url_for('item_categories.view_category', category_id=category_id))
    
    try:
        category_code = category.category_code
        db.session.delete(category)
        db.session.commit()
        flash(f'Item category "{category_code}" deleted successfully', 'success')
        return redirect(url_for('item_categories.list_categories'))
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error deleting item category')
        flash('Failed to delete category. Please try again or contact support.', 'danger')
        return redirect(url_for('item_categories.view_category', category_id=category_id))
