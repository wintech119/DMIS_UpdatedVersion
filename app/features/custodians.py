from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, current_app
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from datetime import datetime
import re
from app.db.models import db, Custodian, Parish, Warehouse
from app.core.audit import add_audit_fields
from app.core.decorators import feature_required
from app.core.phone_utils import validate_phone_format, get_phone_validation_error

custodians_bp = Blueprint('custodians', __name__)


def validate_email(email):
    """Validate email format"""
    if not email:
        return True
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None


def validate_custodian_data(form_data, is_update=False, custodian_id=None):
    """
    Validate custodian data against all business rules.
    Returns (is_valid, errors_dict)
    """
    errors = {}
    
    custodian_name = form_data.get('custodian_name', '').strip()
    address1_text = form_data.get('address1_text', '').strip()
    address2_text = form_data.get('address2_text', '').strip()
    parish_code = form_data.get('parish_code', '').strip()
    contact_name = form_data.get('contact_name', '').strip()
    phone_no = form_data.get('phone_no', '').strip()
    email_text = form_data.get('email_text', '').strip()
    
    if not custodian_name:
        errors['custodian_name'] = 'Custodian name is required'
    else:
        if len(custodian_name) > 120:
            errors['custodian_name'] = 'Custodian name must not exceed 120 characters'
        else:
            query = Custodian.query.filter(
                db.func.upper(Custodian.custodian_name) == custodian_name.upper()
            )
            if is_update and custodian_id:
                query = query.filter(Custodian.custodian_id != custodian_id)
            if query.first():
                errors['custodian_name'] = 'A custodian with this name already exists'
    
    if not address1_text:
        errors['address1_text'] = 'Address line 1 is required'
    elif len(address1_text) > 255:
        errors['address1_text'] = 'Address line 1 must not exceed 255 characters'
    
    if address2_text and len(address2_text) > 255:
        errors['address2_text'] = 'Address line 2 must not exceed 255 characters'
    
    if not parish_code:
        errors['parish_code'] = 'Parish is required'
    else:
        parish = Parish.query.filter_by(parish_code=parish_code).first()
        if not parish:
            errors['parish_code'] = 'Invalid parish code selected'
    
    if not contact_name:
        errors['contact_name'] = 'Contact name is required'
    elif len(contact_name) > 50:
        errors['contact_name'] = 'Contact name must not exceed 50 characters'
    
    if not phone_no:
        errors['phone_no'] = 'Phone number is required'
    else:
        if not validate_phone_format(phone_no):
            errors['phone_no'] = get_phone_validation_error('Phone number')
    
    if email_text:
        if len(email_text) > 100:
            errors['email_text'] = 'Email must not exceed 100 characters'
        elif not validate_email(email_text):
            errors['email_text'] = 'Invalid email format'
    
    return (len(errors) == 0, errors)


@custodians_bp.route('/')
@login_required
@feature_required('custodian_management')
def list_custodians():
    """List all custodians with filtering and search"""
    search_query = request.args.get('search', '').strip()
    
    total_count = Custodian.query.count()
    
    counts = {
        'total': total_count
    }
    
    query = Custodian.query
    
    if search_query:
        search_pattern = f'%{search_query}%'
        query = query.filter(
            db.or_(
                Custodian.custodian_name.ilike(search_pattern),
                Custodian.contact_name.ilike(search_pattern),
                Custodian.address1_text.ilike(search_pattern)
            )
        )
    
    custodians = query.order_by(Custodian.custodian_name).all()
    
    return render_template(
        'custodians/index.html',
        custodians=custodians,
        counts=counts,
        search_query=search_query
    )


@custodians_bp.route('/create', methods=['GET', 'POST'])
@login_required
@feature_required('custodian_management')
def create():
    """Create new custodian"""
    if request.method == 'POST':
        is_valid, errors = validate_custodian_data(request.form)
        
        if not is_valid:
            for field, error in errors.items():
                flash(error, 'danger')
            
            parishes = Parish.query.order_by(Parish.parish_name).all()
            
            return render_template(
                'custodians/create.html',
                parishes=parishes,
                form_data=request.form,
                errors=errors
            )
        
        try:
            custodian = Custodian(
                custodian_name=request.form.get('custodian_name').strip().upper(),
                address1_text=request.form.get('address1_text').strip(),
                address2_text=request.form.get('address2_text', '').strip() or None,
                parish_code=request.form.get('parish_code').strip(),
                contact_name=request.form.get('contact_name').strip().upper(),
                phone_no=request.form.get('phone_no').strip(),
                email_text=request.form.get('email_text', '').strip() or None
            )
            
            add_audit_fields(custodian, current_user, is_new=True)
            
            db.session.add(custodian)
            db.session.commit()
            
            flash(f'Custodian {custodian.custodian_name} created successfully.', 'success')
            return redirect(url_for('custodians.list_custodians'))
            
        except IntegrityError as e:
            db.session.rollback()
            if 'unique' in str(e).lower() or 'duplicate' in str(e).lower():
                flash('A custodian with this name already exists.', 'danger')
            else:
                flash('Cannot create custodian due to data integrity constraint.', 'danger')
            parishes = Parish.query.order_by(Parish.parish_name).all()
            return render_template(
                'custodians/create.html',
                parishes=parishes,
                form_data=request.form,
                errors=errors
            )
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('Error creating custodian')
            flash('An unexpected error occurred. Please try again or contact support.', 'danger')
            parishes = Parish.query.order_by(Parish.parish_name).all()
            return render_template(
                'custodians/create.html',
                parishes=parishes,
                form_data=request.form,
                errors=errors
            )
    
    parishes = Parish.query.order_by(Parish.parish_name).all()
    return render_template('custodians/create.html', parishes=parishes)


@custodians_bp.route('/<int:custodian_id>')
@login_required
@feature_required('custodian_management')
def view(custodian_id):
    """View custodian details"""
    custodian = Custodian.query.get_or_404(custodian_id)
    return render_template('custodians/view.html', custodian=custodian)


@custodians_bp.route('/<int:custodian_id>/edit', methods=['GET', 'POST'])
@login_required
@feature_required('custodian_management')
def edit(custodian_id):
    """Edit existing custodian"""
    custodian = Custodian.query.get_or_404(custodian_id)
    
    if request.method == 'POST':
        submitted_version = request.form.get('version_nbr', type=int)
        if submitted_version != custodian.version_nbr:
            flash('This custodian record has been modified by another user. Please reload and try again.', 'warning')
            return redirect(url_for('custodians.view', custodian_id=custodian_id))
        
        is_valid, errors = validate_custodian_data(request.form, is_update=True, custodian_id=custodian_id)
        
        if not is_valid:
            for field, error in errors.items():
                flash(error, 'danger')
            
            parishes = Parish.query.order_by(Parish.parish_name).all()
            
            return render_template(
                'custodians/edit.html',
                custodian=custodian,
                parishes=parishes,
                form_data=request.form,
                errors=errors
            )
        
        try:
            custodian.custodian_name = request.form.get('custodian_name').strip().upper()
            custodian.address1_text = request.form.get('address1_text').strip()
            custodian.address2_text = request.form.get('address2_text', '').strip() or None
            custodian.parish_code = request.form.get('parish_code').strip()
            custodian.contact_name = request.form.get('contact_name').strip().upper()
            custodian.phone_no = request.form.get('phone_no').strip()
            custodian.email_text = request.form.get('email_text', '').strip() or None
            
            add_audit_fields(custodian, current_user, is_new=False)
            
            db.session.commit()
            
            flash('Custodian updated successfully.', 'success')
            return redirect(url_for('custodians.view', custodian_id=custodian_id))
            
        except StaleDataError:
            db.session.rollback()
            flash('This custodian record has been modified by another user. Please reload and try again.', 'warning')
            return redirect(url_for('custodians.view', custodian_id=custodian_id))
            
        except IntegrityError as e:
            db.session.rollback()
            if 'unique' in str(e).lower() or 'duplicate' in str(e).lower():
                flash('A custodian with this name already exists.', 'danger')
            else:
                flash('Cannot update custodian due to data integrity constraint.', 'danger')
            parishes = Parish.query.order_by(Parish.parish_name).all()
            return render_template(
                'custodians/edit.html',
                custodian=custodian,
                parishes=parishes,
                form_data=request.form,
                errors=errors
            )
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('Error updating custodian')
            flash('An unexpected error occurred. Please try again or contact support.', 'danger')
            parishes = Parish.query.order_by(Parish.parish_name).all()
            return render_template(
                'custodians/edit.html',
                custodian=custodian,
                parishes=parishes,
                form_data=request.form,
                errors=errors
            )
    
    parishes = Parish.query.order_by(Parish.parish_name).all()
    return render_template('custodians/edit.html', custodian=custodian, parishes=parishes)


@custodians_bp.route('/<int:custodian_id>/delete', methods=['POST'])
@login_required
@feature_required('custodian_management')
def delete(custodian_id):
    """Delete custodian (conditional on no references)"""
    custodian = Custodian.query.get_or_404(custodian_id)
    
    warehouse_count = Warehouse.query.filter_by(custodian_id=custodian_id).count()
    if warehouse_count > 0:
        flash('This custodian cannot be deleted because it is referenced by other records.', 'danger')
        return redirect(url_for('custodians.view', custodian_id=custodian_id))
    
    try:
        custodian_name = custodian.custodian_name
        db.session.delete(custodian)
        db.session.commit()
        
        flash(f'Custodian {custodian_name} deleted successfully.', 'success')
        return redirect(url_for('custodians.list_custodians'))
        
    except IntegrityError as e:
        db.session.rollback()
        flash('This custodian cannot be deleted because it is referenced by other records.', 'danger')
        return redirect(url_for('custodians.view', custodian_id=custodian_id))
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error deleting custodian')
        flash('An unexpected error occurred. Please try again or contact support.', 'danger')
        return redirect(url_for('custodians.view', custodian_id=custodian_id))
