"""
Donor Management Routes for DRIMS

Role-based access: All operations restricted to CUSTODIAN role via @feature_required('donor_management')

Business Rules:
- donor_code: Mandatory, max 16 chars, UPPERCASE, unique, trimmed
- donor_name: Mandatory, max 255 chars, UPPERCASE, unique, trimmed
- org_type_desc: Optional, max 30 chars, trimmed
- address1_text: Mandatory, max 255 chars, trimmed
- address2_text: Optional, max 255 chars, trimmed
- country_id: Mandatory, must exist in Country table, defaults to 388 (Jamaica)
- phone_no: Mandatory, max 20 chars, validated format +1 (XXX) XXX-XXXX
- email_text: Optional, max 100 chars, email format validation, trimmed
- Optimistic locking via version_nbr
- Delete only allowed if no donations exist for this donor
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, current_app
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError
from datetime import datetime
import re
from app.db.models import db, Donor, Donation
from app.core.decorators import feature_required
from app.core.audit import add_audit_fields
from app.core.phone_utils import validate_phone_format, get_phone_validation_error

donors_bp = Blueprint('donors', __name__, url_prefix='/donors')

def validate_email(email):
    """Validate email format"""
    if not email:
        return True  # Optional field
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def validate_donor_data(form_data, is_update=False, donor_id=None):
    """
    Validate donor data against all business rules.
    Returns (is_valid, errors_dict)
    """
    errors = {}
    
    # Get form data - trim first, then process
    donor_code = (form_data.get('donor_code') or '').strip()
    donor_name = (form_data.get('donor_name') or '').strip()
    org_type_desc = (form_data.get('org_type_desc') or '').strip()
    address1_text = (form_data.get('address1_text') or '').strip()
    address2_text = (form_data.get('address2_text') or '').strip()
    country_id = (form_data.get('country_id') or '').strip()
    phone_no = (form_data.get('phone_no') or '').strip()
    email_text = (form_data.get('email_text') or '').strip()
    
    # Donor Code validation
    if not donor_code:
        errors['donor_code'] = 'Donor code is required'
    else:
        # Check length
        if len(donor_code) > 16:
            errors['donor_code'] = 'Donor code must not exceed 16 characters'
        else:
            # Validate uppercase
            donor_code_upper = donor_code.upper()
            if donor_code != donor_code_upper:
                errors['donor_code'] = 'Donor code must be uppercase'
            
            # Check uniqueness (compare trimmed, uppercased values)
            query = Donor.query.filter(
                db.func.upper(db.func.trim(Donor.donor_code)) == donor_code_upper
            )
            if is_update and donor_id:
                query = query.filter(Donor.donor_id != donor_id)
            if query.first():
                errors['donor_code'] = 'Donor code already exists'
    
    # Donor Name validation
    if not donor_name:
        errors['donor_name'] = 'Donor name is required'
    else:
        # Check length
        if len(donor_name) > 255:
            errors['donor_name'] = 'Donor name must not exceed 255 characters'
        else:
            # Check uniqueness (compare trimmed, uppercased values)
            donor_name_upper = donor_name.upper()
            query = Donor.query.filter(
                db.func.upper(db.func.trim(Donor.donor_name)) == donor_name_upper
            )
            if is_update and donor_id:
                query = query.filter(Donor.donor_id != donor_id)
            if query.first():
                errors['donor_name'] = 'A donor with this name already exists'
    
    # Organization Type Description validation
    if org_type_desc:
        if len(org_type_desc) > 30:
            errors['org_type_desc'] = 'Organization type must not exceed 30 characters'
    
    # Address validation
    if not address1_text:
        errors['address1_text'] = 'Address line 1 is required'
    elif len(address1_text) > 255:
        errors['address1_text'] = 'Address line 1 must not exceed 255 characters'
    
    if address2_text and len(address2_text) > 255:
        errors['address2_text'] = 'Address line 2 must not exceed 255 characters'
    
    # Country validation (defaults to 388 Jamaica if not provided)
    if not country_id:
        country_id = '388'  # Default to Jamaica
    
    try:
        country_id_int = int(country_id)
        # Verify country exists
        country_exists = db.session.execute(
            db.text("SELECT 1 FROM country WHERE country_id = :id"),
            {'id': country_id_int}
        ).fetchone()
        if not country_exists:
            errors['country_id'] = 'Invalid country selected'
    except ValueError:
        errors['country_id'] = 'Invalid country ID'
    
    # Phone validation
    if not phone_no:
        errors['phone_no'] = 'Phone number is required'
    elif len(phone_no) > 20:
        errors['phone_no'] = 'Phone number must not exceed 20 characters'
    elif not validate_phone_format(phone_no):
        errors['phone_no'] = get_phone_validation_error('Phone number')
    
    # Email validation (stored lowercase)
    if email_text:
        email_text_lower = email_text.lower()
        if len(email_text_lower) > 100:
            errors['email_text'] = 'Email must not exceed 100 characters'
        elif not validate_email(email_text_lower):
            errors['email_text'] = 'Invalid email format'
    
    return (len(errors) == 0, errors)


@donors_bp.route('/')
@login_required
@feature_required('donor_management')
def list_donors():
    """List all donors with search and filter capabilities"""
    # Get filter and search parameters
    search_query = request.args.get('search', '').strip()
    
    # Base query
    query = Donor.query
    
    # Apply search filter
    if search_query:
        search_pattern = f'%{search_query}%'
        query = query.filter(
            db.or_(
                Donor.donor_code.ilike(search_pattern),
                Donor.donor_name.ilike(search_pattern),
                Donor.org_type_desc.ilike(search_pattern),
                Donor.address1_text.ilike(search_pattern),
                Donor.phone_no.ilike(search_pattern),
                Donor.email_text.ilike(search_pattern)
            )
        )
    
    # Order by donor name
    donors = query.order_by(Donor.donor_name).all()
    
    # Get counts for summary
    total_count = Donor.query.count()
    
    # Get countries for display
    countries_dict = {}
    countries = db.session.execute(
        db.text("SELECT country_id, country_name FROM country")
    ).fetchall()
    for country in countries:
        countries_dict[country.country_id] = country.country_name
    
    return render_template(
        'donors/list.html',
        donors=donors,
        countries=countries_dict,
        search_query=search_query,
        counts={'total': total_count, 'filtered': len(donors)}
    )


@donors_bp.route('/create', methods=['GET', 'POST'])
@login_required
@feature_required('donor_management')
def create():
    """Create new donor"""
    if request.method == 'POST':
        # Validate form data
        is_valid, errors = validate_donor_data(request.form)
        
        if not is_valid:
            # Show validation errors
            for field, error in errors.items():
                flash(error, 'danger')
            
            # Return to form with entered data
            countries = db.session.execute(
                db.text("SELECT country_id, country_name FROM country ORDER BY country_name")
            ).fetchall()
            
            return render_template(
                'donors/create.html',
                countries=countries,
                form_data=request.form,
                errors=errors
            )
        
        try:
            from app.security.param_validation import safe_id
            
            # Create donor
            donor = Donor()
            donor.donor_code = (request.form.get('donor_code') or '').strip().upper()
            donor.donor_name = (request.form.get('donor_name') or '').strip().upper()
            donor.org_type_desc = request.form.get('org_type_desc', '').strip() or None
            donor.address1_text = (request.form.get('address1_text') or '').strip()
            donor.address2_text = request.form.get('address2_text', '').strip() or None
            donor.country_id = safe_id(request.form.get('country_id'), default=388)
            donor.phone_no = (request.form.get('phone_no') or '').strip()
            donor.email_text = request.form.get('email_text', '').strip().lower() or None
            
            # Audit fields
            add_audit_fields(donor, current_user, is_new=True)
            
            db.session.add(donor)
            db.session.commit()
            
            flash(f'Donor "{donor.donor_name}" created successfully', 'success')
            return redirect(url_for('donors.view', donor_id=donor.donor_id))
            
        except IntegrityError as e:
            db.session.rollback()
            current_app.logger.exception('Database integrity error creating donor')
            if 'donor_name' in str(e.orig):
                flash('A donor with this name already exists', 'danger')
            elif 'donor_code' in str(e.orig):
                flash('Donor code already exists', 'danger')
            else:
                flash('A database constraint prevented saving this donor. Please check for duplicate values.', 'danger')
            
            countries = db.session.execute(
                db.text("SELECT country_id, country_name FROM country ORDER BY country_name")
            ).fetchall()
            
            return render_template(
                'donors/create.html',
                countries=countries,
                form_data=request.form,
                errors={}
            )
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('Error creating donor')
            flash('An error occurred while creating the donor. Please try again or contact support.', 'danger')
            
            countries = db.session.execute(
                db.text("SELECT country_id, country_name FROM country ORDER BY country_name")
            ).fetchall()
            
            return render_template(
                'donors/create.html',
                countries=countries,
                form_data=request.form,
                errors={}
            )
    
    # GET request
    countries = db.session.execute(
        db.text("SELECT country_id, country_name FROM country ORDER BY country_name")
    ).fetchall()
    
    return render_template('donors/create.html', countries=countries)


@donors_bp.route('/<int:donor_id>')
@login_required
@feature_required('donor_management')
def view(donor_id):
    """View donor details"""
    donor = Donor.query.get_or_404(donor_id)
    
    # Get country name
    country = db.session.execute(
        db.text("SELECT country_name FROM country WHERE country_id = :id"),
        {'id': donor.country_id}
    ).fetchone()
    country_name = country.country_name if country else 'Unknown'
    
    # Get donations for this donor
    donations = Donation.query.filter_by(donor_id=donor_id).order_by(Donation.received_date.desc()).all()
    
    return render_template(
        'donors/view.html',
        donor=donor,
        country_name=country_name,
        donations=donations
    )


@donors_bp.route('/<int:donor_id>/edit', methods=['GET', 'POST'])
@login_required
@feature_required('donor_management')
def edit(donor_id):
    """Edit existing donor"""
    donor = Donor.query.get_or_404(donor_id)
    
    if request.method == 'POST':
        # Optimistic locking check
        submitted_version = request.form.get('version_nbr', type=int)
        if submitted_version != donor.version_nbr:
            flash('This donor record was updated by another user. Please reload and try again.', 'warning')
            return redirect(url_for('donors.view', donor_id=donor_id))
        
        # Validate form data
        is_valid, errors = validate_donor_data(request.form, is_update=True, donor_id=donor_id)
        
        if not is_valid:
            # Show validation errors
            for field, error in errors.items():
                flash(error, 'danger')
            
            # Return to form with entered data
            countries = db.session.execute(
                db.text("SELECT country_id, country_name FROM country ORDER BY country_name")
            ).fetchall()
            
            return render_template(
                'donors/edit.html',
                donor=donor,
                countries=countries,
                form_data=request.form,
                errors=errors
            )
        
        try:
            from app.security.param_validation import safe_id
            
            # Update donor (donor_code read-only, donor_name editable)
            donor.donor_name = (request.form.get('donor_name') or '').strip().upper()
            donor.org_type_desc = request.form.get('org_type_desc', '').strip() or None
            donor.address1_text = (request.form.get('address1_text') or '').strip()
            donor.address2_text = request.form.get('address2_text', '').strip() or None
            donor.country_id = safe_id(request.form.get('country_id'), default=388)
            donor.phone_no = (request.form.get('phone_no') or '').strip()
            donor.email_text = request.form.get('email_text', '').strip().lower() or None
            
            # Update audit fields
            add_audit_fields(donor, current_user, is_new=False)
            
            # Increment version
            donor.version_nbr += 1
            
            db.session.commit()
            
            flash(f'Donor "{donor.donor_name}" updated successfully', 'success')
            return redirect(url_for('donors.view', donor_id=donor.donor_id))
            
        except IntegrityError as e:
            db.session.rollback()
            current_app.logger.exception('Database integrity error updating donor')
            if 'donor_name' in str(e.orig):
                flash('A donor with this name already exists', 'danger')
            else:
                flash('A database constraint prevented saving this donor. Please check for duplicate values.', 'danger')
            
            countries = db.session.execute(
                db.text("SELECT country_id, country_name FROM country ORDER BY country_name")
            ).fetchall()
            
            return render_template(
                'donors/edit.html',
                donor=donor,
                countries=countries,
                form_data=request.form,
                errors={}
            )
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('Error updating donor')
            flash('An error occurred while updating the donor. Please try again or contact support.', 'danger')
            
            countries = db.session.execute(
                db.text("SELECT country_id, country_name FROM country ORDER BY country_name")
            ).fetchall()
            
            return render_template(
                'donors/edit.html',
                donor=donor,
                countries=countries,
                form_data=request.form,
                errors={}
            )
    
    # GET request
    countries = db.session.execute(
        db.text("SELECT country_id, country_name FROM country ORDER BY country_name")
    ).fetchall()
    
    return render_template('donors/edit.html', donor=donor, countries=countries)


@donors_bp.route('/<int:donor_id>/delete', methods=['POST'])
@login_required
@feature_required('donor_management')
def delete(donor_id):
    """Delete donor - only if no donations exist"""
    donor = Donor.query.get_or_404(donor_id)
    
    # Check if donor is referenced by any donations
    donation_count = Donation.query.filter_by(donor_id=donor_id).count()
    
    if donation_count > 0:
        flash(
            f'This donor cannot be deleted because it is referenced by {donation_count} existing donation record(s).',
            'danger'
        )
        return redirect(url_for('donors.view', donor_id=donor_id))
    
    try:
        donor_name = donor.donor_name
        db.session.delete(donor)
        db.session.commit()
        
        flash(f'Donor "{donor_name}" deleted successfully', 'success')
        return redirect(url_for('donors.list_donors'))
        
    except IntegrityError as e:
        db.session.rollback()
        flash(
            'This donor cannot be deleted because it is referenced by existing donation records.',
            'danger'
        )
        return redirect(url_for('donors.view', donor_id=donor_id))
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error deleting donor')
        flash('An error occurred while deleting the donor. Please try again or contact support.', 'danger')
        return redirect(url_for('donors.view', donor_id=donor_id))
