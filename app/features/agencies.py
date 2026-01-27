from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, current_app
from flask_login import login_required, current_user
from datetime import datetime
from sqlalchemy.exc import IntegrityError
from sqlalchemy import or_
from app.db.models import db, Agency, Parish, Event, Warehouse, ReliefRqst
from app.core.audit import add_audit_fields
from app.core.phone_utils import validate_phone_format, get_phone_validation_error
from app.core.decorators import feature_required
import re

agencies_bp = Blueprint('agencies', __name__)

# Constants
AGENCY_TYPES = ['SHELTER', 'DISTRIBUTOR']
STATUS_CODES = ['A', 'I']

def validate_email(email):
    """Validate email format using simple regex"""
    if not email:
        return True
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def validate_agency_data(form_data, is_update=False, agency_id=None):
    """
    Validate agency form data according to business rules.
    Returns: (is_valid, errors, normalized_data)
    """
    errors = {}
    normalized_data = {}
    
    # 1. Agency Name - Mandatory, uppercase, max 120 chars, unique
    agency_name = form_data.get('agency_name', '').strip()
    if not agency_name:
        errors['agency_name'] = 'Agency name is required'
    elif len(agency_name) > 120:
        errors['agency_name'] = 'Agency name cannot exceed 120 characters'
    else:
        agency_name_upper = agency_name.upper()
        # Check uniqueness
        existing = Agency.query.filter_by(agency_name=agency_name_upper).first()
        if existing and (not is_update or existing.agency_id != agency_id):
            errors['agency_name'] = f'An agency with the name "{agency_name_upper}" already exists'
        normalized_data['agency_name'] = agency_name_upper
    
    # 2. Agency Type - Mandatory, must be SHELTER or DISTRIBUTOR
    agency_type = form_data.get('agency_type', '').strip()
    if not agency_type:
        errors['agency_type'] = 'Agency type is required'
    elif agency_type not in AGENCY_TYPES:
        errors['agency_type'] = f'Agency type must be one of: {", ".join(AGENCY_TYPES)}'
    normalized_data['agency_type'] = agency_type
    
    # 3. Address1 - Mandatory, max 255 chars
    address1_text = form_data.get('address1_text', '').strip()
    if not address1_text:
        errors['address1_text'] = 'Address line 1 is required'
    elif len(address1_text) > 255:
        errors['address1_text'] = 'Address line 1 cannot exceed 255 characters'
    normalized_data['address1_text'] = address1_text
    
    # 4. Address2 - Optional, max 255 chars
    address2_text = form_data.get('address2_text', '').strip()
    if address2_text and len(address2_text) > 255:
        errors['address2_text'] = 'Address line 2 cannot exceed 255 characters'
    normalized_data['address2_text'] = address2_text if address2_text else None
    
    # 5. Parish - Mandatory, must be valid
    parish_code = form_data.get('parish_code', '').strip()
    if not parish_code:
        errors['parish_code'] = 'Parish is required'
    else:
        parish = Parish.query.get(parish_code)
        if not parish:
            errors['parish_code'] = 'Invalid parish code'
    normalized_data['parish_code'] = parish_code
    
    # 6. Contact Name - Mandatory, max 50 chars, uppercase
    contact_name = form_data.get('contact_name', '').strip()
    if not contact_name:
        errors['contact_name'] = 'Contact name is required'
    elif len(contact_name) > 50:
        errors['contact_name'] = 'Contact name cannot exceed 50 characters'
    normalized_data['contact_name'] = contact_name.upper()
    
    # 7. Phone Number - Mandatory, max 20 chars, valid format
    phone_no = form_data.get('phone_no', '').strip()
    if not phone_no:
        errors['phone_no'] = 'Phone number is required'
    elif len(phone_no) > 20:
        errors['phone_no'] = 'Phone number cannot exceed 20 characters'
    elif not validate_phone_format(phone_no):
        errors['phone_no'] = get_phone_validation_error('Phone number')
    normalized_data['phone_no'] = phone_no
    
    # 8. Email - Optional, max 100 chars, valid format
    email_text = form_data.get('email_text', '').strip().lower()
    if email_text:
        if len(email_text) > 100:
            errors['email_text'] = 'Email cannot exceed 100 characters'
        elif not validate_email(email_text):
            errors['email_text'] = 'Invalid email format'
    normalized_data['email_text'] = email_text if email_text else None
    
    # 9. Warehouse - Business rule based on agency_type
    warehouse_id_str = form_data.get('warehouse_id', '').strip()
    warehouse_id = int(warehouse_id_str) if warehouse_id_str else None
    
    if agency_type == 'DISTRIBUTOR':
        if not warehouse_id:
            errors['warehouse_id'] = 'DISTRIBUTOR agencies must have a warehouse assigned'
        else:
            # Validate warehouse exists
            warehouse = Warehouse.query.get(warehouse_id)
            if not warehouse:
                errors['warehouse_id'] = 'Invalid warehouse'
    elif agency_type == 'SHELTER':
        if warehouse_id:
            errors['warehouse_id'] = 'SHELTER agencies cannot have a warehouse assigned'
        warehouse_id = None
    
    normalized_data['warehouse_id'] = warehouse_id
    
    # 10. Status Code - Mandatory, must be A or I
    status_code = form_data.get('status_code', '').strip()
    if not status_code:
        errors['status_code'] = 'Status code is required'
    elif status_code not in STATUS_CODES:
        errors['status_code'] = f'Status code must be one of: {", ".join(STATUS_CODES)}'
    normalized_data['status_code'] = status_code
    
    # 11. Ineligible Event - Optional
    ineligible_event_id_str = form_data.get('ineligible_event_id', '').strip()
    ineligible_event_id = int(ineligible_event_id_str) if ineligible_event_id_str else None
    normalized_data['ineligible_event_id'] = ineligible_event_id
    
    return len(errors) == 0, errors, normalized_data


@agencies_bp.route('/')
@login_required
@feature_required('agency_management')
def list_agencies():
    """
    Display list of all agencies with filter and search capabilities.
    Custodian-only access.
    """
    # Get filter parameters
    filter_type = request.args.get('filter', 'all')
    search_query = request.args.get('search', '').strip()
    agency_type_filter = request.args.get('agency_type', '')
    parish_filter = request.args.get('parish', '')
    
    # Base query
    query = Agency.query
    
    # Apply status filter
    if filter_type == 'active':
        query = query.filter(Agency.status_code == 'A')
    elif filter_type == 'inactive':
        query = query.filter(Agency.status_code == 'I')
    
    # Apply agency type filter
    if agency_type_filter:
        query = query.filter(Agency.agency_type == agency_type_filter)
    
    # Apply parish filter
    if parish_filter:
        query = query.filter(Agency.parish_code == parish_filter)
    
    # Apply search
    if search_query:
        search_pattern = f'%{search_query}%'
        query = query.filter(
            or_(
                Agency.agency_name.ilike(search_pattern),
                Agency.contact_name.ilike(search_pattern),
                Agency.phone_no.ilike(search_pattern)
            )
        )
    
    # Order by agency name
    agencies = query.order_by(Agency.agency_name).all()
    
    # Calculate metrics
    total_agencies = Agency.query.count()
    active_agencies = Agency.query.filter_by(status_code='A').count()
    inactive_agencies = Agency.query.filter_by(status_code='I').count()
    shelter_agencies = Agency.query.filter_by(agency_type='SHELTER').count()
    distributor_agencies = Agency.query.filter_by(agency_type='DISTRIBUTOR').count()
    
    metrics = {
        'total_agencies': total_agencies,
        'active_agencies': active_agencies,
        'inactive_agencies': inactive_agencies,
        'shelter_agencies': shelter_agencies,
        'distributor_agencies': distributor_agencies
    }
    
    # Get parishes for filter dropdown
    parishes = Parish.query.order_by(Parish.parish_name).all()
    
    return render_template('agencies/list.html', 
                         agencies=agencies, 
                         metrics=metrics,
                         filter_type=filter_type,
                         search_query=search_query,
                         agency_type_filter=agency_type_filter,
                         parish_filter=parish_filter,
                         parishes=parishes)


@agencies_bp.route('/create', methods=['GET', 'POST'])
@login_required
@feature_required('agency_management')
def create_agency():
    """
    Create a new agency.
    Custodian-only access.
    """
    if request.method == 'POST':
        # Validate form data
        is_valid, errors, normalized_data = validate_agency_data(request.form)
        
        # Convert None to empty string for template display compatibility
        display_data = {k: (v if v is not None else '') for k, v in normalized_data.items()}
        
        if not is_valid:
            # Flash each error
            for field, error in errors.items():
                flash(error, 'danger')
            
            # Get lookup data for form
            parishes = Parish.query.order_by(Parish.parish_name).all()
            events = Event.query.filter_by(status_code='A').order_by(Event.event_name).all()
            warehouses = Warehouse.query.filter_by(status_code='A').order_by(Warehouse.warehouse_name).all()
            
            return render_template('agencies/create.html',
                                 form_data=display_data,
                                 errors=errors,
                                 parishes=parishes,
                                 events=events,
                                 warehouses=warehouses)
        
        try:
            # Create new agency
            new_agency = Agency(
                agency_name=normalized_data['agency_name'],
                agency_type=normalized_data['agency_type'],
                address1_text=normalized_data['address1_text'],
                address2_text=normalized_data['address2_text'],
                parish_code=normalized_data['parish_code'],
                contact_name=normalized_data['contact_name'],
                phone_no=normalized_data['phone_no'],
                email_text=normalized_data['email_text'],
                ineligible_event_id=normalized_data['ineligible_event_id'],
                warehouse_id=normalized_data['warehouse_id'],
                status_code=normalized_data['status_code']
            )
            
            # Add audit fields
            add_audit_fields(new_agency, current_user)
            
            db.session.add(new_agency)
            db.session.commit()
            
            flash(f'Agency "{new_agency.agency_name}" created successfully', 'success')
            return redirect(url_for('agencies.view_agency', agency_id=new_agency.agency_id))
            
        except IntegrityError as e:
            db.session.rollback()
            flash('Database constraint violation. Please check that all fields are valid and try again.', 'danger')
            
            # Get lookup data for form
            parishes = Parish.query.order_by(Parish.parish_name).all()
            events = Event.query.filter_by(status_code='A').order_by(Event.event_name).all()
            warehouses = Warehouse.query.filter_by(status_code='A').order_by(Warehouse.warehouse_name).all()
            
            return render_template('agencies/create.html',
                                 form_data=display_data,
                                 errors={},
                                 parishes=parishes,
                                 events=events,
                                 warehouses=warehouses)
    
    # GET request - show form
    parishes = Parish.query.order_by(Parish.parish_name).all()
    events = Event.query.filter_by(status_code='A').order_by(Event.event_name).all()
    warehouses = Warehouse.query.filter_by(status_code='A').order_by(Warehouse.warehouse_name).all()
    
    return render_template('agencies/create.html',
                         form_data={},
                         errors={},
                         parishes=parishes,
                         events=events,
                         warehouses=warehouses)


@agencies_bp.route('/<int:agency_id>')
@login_required
@feature_required('agency_management')
def view_agency(agency_id):
    """
    View details of a specific agency.
    Custodian-only access.
    """
    agency = Agency.query.get_or_404(agency_id)
    
    # Count relief requests from this agency
    request_count = ReliefRqst.query.filter_by(agency_id=agency_id).count()
    
    return render_template('agencies/view.html', 
                         agency=agency,
                         request_count=request_count)


@agencies_bp.route('/<int:agency_id>/edit', methods=['GET', 'POST'])
@login_required
@feature_required('agency_management')
def edit_agency(agency_id):
    """
    Edit an existing agency.
    Custodian-only access with optimistic locking.
    """
    agency = Agency.query.get_or_404(agency_id)
    
    if request.method == 'POST':
        # Check optimistic locking
        submitted_version = request.form.get('version_nbr', type=int)
        
        if submitted_version != agency.version_nbr:
            flash('This agency has been modified by another user. Please reload and try again.', 'warning')
            return redirect(url_for('agencies.edit_agency', agency_id=agency_id))
        
        # Validate form data
        is_valid, errors, normalized_data = validate_agency_data(request.form, is_update=True, agency_id=agency_id)
        
        # Convert None to empty string for template display compatibility
        display_data = {k: (v if v is not None else '') for k, v in normalized_data.items()}
        
        if not is_valid:
            # Flash each error
            for field, error in errors.items():
                flash(error, 'danger')
            
            # Get lookup data for form
            parishes = Parish.query.order_by(Parish.parish_name).all()
            events = Event.query.filter_by(status_code='A').order_by(Event.event_name).all()
            warehouses = Warehouse.query.filter_by(status_code='A').order_by(Warehouse.warehouse_name).all()
            
            return render_template('agencies/edit.html',
                                 agency=agency,
                                 form_data=display_data,
                                 errors=errors,
                                 parishes=parishes,
                                 events=events,
                                 warehouses=warehouses)
        
        try:
            # Update agency fields
            agency.agency_name = normalized_data['agency_name']
            agency.agency_type = normalized_data['agency_type']
            agency.address1_text = normalized_data['address1_text']
            agency.address2_text = normalized_data['address2_text']
            agency.parish_code = normalized_data['parish_code']
            agency.contact_name = normalized_data['contact_name']
            agency.phone_no = normalized_data['phone_no']
            agency.email_text = normalized_data['email_text']
            agency.ineligible_event_id = normalized_data['ineligible_event_id']
            agency.warehouse_id = normalized_data['warehouse_id']
            agency.status_code = normalized_data['status_code']
            
            # Update audit fields and increment version
            add_audit_fields(agency, current_user, is_new=False)
            
            db.session.commit()
            
            flash(f'Agency "{agency.agency_name}" updated successfully', 'success')
            return redirect(url_for('agencies.view_agency', agency_id=agency.agency_id))
            
        except IntegrityError as e:
            db.session.rollback()
            flash('Database constraint violation. Please check that all fields are valid and try again.', 'danger')
            
            # Get lookup data for form
            parishes = Parish.query.order_by(Parish.parish_name).all()
            events = Event.query.filter_by(status_code='A').order_by(Event.event_name).all()
            warehouses = Warehouse.query.filter_by(status_code='A').order_by(Warehouse.warehouse_name).all()
            
            return render_template('agencies/edit.html',
                                 agency=agency,
                                 form_data=display_data,
                                 errors={},
                                 parishes=parishes,
                                 events=events,
                                 warehouses=warehouses)
    
    # GET request - show form with current values
    parishes = Parish.query.order_by(Parish.parish_name).all()
    events = Event.query.filter_by(status_code='A').order_by(Event.event_name).all()
    warehouses = Warehouse.query.filter_by(status_code='A').order_by(Warehouse.warehouse_name).all()
    
    # Prepare form data from current agency
    form_data = {
        'agency_name': agency.agency_name,
        'agency_type': agency.agency_type,
        'address1_text': agency.address1_text,
        'address2_text': agency.address2_text or '',
        'parish_code': agency.parish_code,
        'contact_name': agency.contact_name,
        'phone_no': agency.phone_no,
        'email_text': agency.email_text or '',
        'ineligible_event_id': agency.ineligible_event_id or '',
        'warehouse_id': agency.warehouse_id or '',
        'status_code': agency.status_code
    }
    
    return render_template('agencies/edit.html',
                         agency=agency,
                         form_data=form_data,
                         errors={},
                         parishes=parishes,
                         events=events,
                         warehouses=warehouses)


@agencies_bp.route('/<int:agency_id>/deactivate', methods=['POST'])
@login_required
@feature_required('agency_management')
def deactivate_agency(agency_id):
    """
    Deactivate an agency (soft delete - set status to Inactive).
    Custodian-only access.
    Cannot deactivate if referenced by active transactions.
    """
    agency = Agency.query.get_or_404(agency_id)
    
    # Check if agency has any active relief requests
    active_requests = ReliefRqst.query.filter_by(agency_id=agency_id).filter(
        ReliefRqst.status_code.in_([0, 1, 2, 3, 4, 5])  # Active statuses
    ).count()
    
    if active_requests > 0:
        flash(f'Cannot deactivate agency "{agency.agency_name}" because it has {active_requests} active relief request(s). Please complete or cancel those requests first.', 'danger')
        return redirect(url_for('agencies.view_agency', agency_id=agency_id))
    
    try:
        agency.status_code = 'I'
        add_audit_fields(agency, current_user, is_new=False)
        db.session.commit()
        
        flash(f'Agency "{agency.agency_name}" has been deactivated successfully', 'success')
        return redirect(url_for('agencies.list_agencies'))
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error deactivating agency')
        flash('An unexpected error occurred. Please try again or contact support.', 'danger')
        return redirect(url_for('agencies.view_agency', agency_id=agency_id))
