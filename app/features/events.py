"""
Event Management Routes (CUSTODIAN Role)

This module implements comprehensive CRUD operations for disaster events
with strict validation, lifecycle rules, and RBAC based on Event permissions.

Permission-Based Access Control:
- VIEW: EVENT / VIEW
- CREATE: EVENT / CREATE
- UPDATE: EVENT / UPDATE  
- CLOSE: EVENT / CLOSE
- DELETE: EVENT / DELETE

Validation Rules:
- event_type: Must be one of 10 approved disaster types (STORM, HURRICANE, TORNADO, FLOOD, TSUNAMI, FIRE, EARTHQUAKE, WAR, EPIDEMIC, ADHOC)
- start_date: Cannot be in the future
- status_code: 'A' (Active) or 'C' (Closed)
- Closed events must have closed_date and reason_desc
- Active events must not have closed_date or reason_desc
- Optimistic locking via version_nbr
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from datetime import date, datetime
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from app.db import db
from app.db.models import Event
from app.core.decorators import feature_required
from app.core.audit import add_audit_fields

events_bp = Blueprint('events', __name__, url_prefix='/events')

# Constants for validation
EVENT_TYPES = ['STORM', 'HURRICANE', 'TORNADO', 'FLOOD', 'TSUNAMI', 'FIRE', 'EARTHQUAKE', 'WAR', 'EPIDEMIC', 'ADHOC']
STATUS_CODES = ['A', 'C']  # Active, Closed

def validate_event_data(form_data, is_update=False):
    """
    Validate event data against all business rules.
    Returns (is_valid, errors_dict)
    """
    errors = {}
    
    # Required fields
    event_type = form_data.get('event_type', '').strip()
    start_date_str = form_data.get('start_date', '').strip()
    event_name = form_data.get('event_name', '').strip()
    event_desc = form_data.get('event_desc', '').strip()
    impact_desc = form_data.get('impact_desc', '').strip()
    status_code = form_data.get('status_code', '').strip()
    
    # Event Type validation
    if not event_type:
        errors['event_type'] = 'Event type is required'
    elif event_type not in EVENT_TYPES:
        errors['event_type'] = f'Event type must be one of: {", ".join(EVENT_TYPES)}'
    
    # Start Date validation
    if not start_date_str:
        errors['start_date'] = 'Start date is required'
    else:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            if start_date > date.today():
                errors['start_date'] = 'Start date cannot be in the future'
        except ValueError:
            errors['start_date'] = 'Invalid date format'
    
    # Event Name validation
    if not event_name:
        errors['event_name'] = 'Event name is required'
    elif len(event_name) > 60:
        errors['event_name'] = 'Event name must not exceed 60 characters'
    
    # Event Description validation
    if not event_desc:
        errors['event_desc'] = 'Event description is required'
    elif len(event_desc) > 255:
        errors['event_desc'] = 'Event description must not exceed 255 characters'
    
    # Impact Description validation
    if not impact_desc:
        errors['impact_desc'] = 'Impact description is required'
    
    # Status Code validation (only for create operations)
    if not is_update:
        if not status_code:
            errors['status_code'] = 'Status is required'
        elif status_code not in STATUS_CODES:
            errors['status_code'] = f'Status must be A (Active) or C (Closed)'
        
        # Closed Date and Reason validation (interdependent rules) - only for create
        closed_date_str = form_data.get('closed_date', '').strip()
        reason_desc = form_data.get('reason_desc', '').strip()
        
        if status_code == 'C':
            # Closed event must have closed_date
            if not closed_date_str:
                errors['closed_date'] = 'Closed date is required for closed events'
            else:
                try:
                    closed_date = datetime.strptime(closed_date_str, '%Y-%m-%d').date()
                    # Closed date must not be earlier than start date
                    if start_date_str:
                        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                        if closed_date < start_date:
                            errors['closed_date'] = 'Closed date cannot be earlier than start date'
                except ValueError:
                    errors['closed_date'] = 'Invalid date format'
            
            # Closed event must have reason_desc
            if not reason_desc:
                errors['reason_desc'] = 'Reason for closure is required for closed events'
            elif len(reason_desc) > 255:
                errors['reason_desc'] = 'Reason must not exceed 255 characters'
        
        elif status_code == 'A':
            # Active event must NOT have closed_date or reason_desc
            if closed_date_str:
                errors['closed_date'] = 'Active events cannot have a closed date'
            if reason_desc:
                errors['reason_desc'] = 'Active events cannot have a closure reason'
    
    return (len(errors) == 0, errors)


@events_bp.route('/')
@login_required
@feature_required('event_management')
def list_events():
    """List all events with filtering and summary counts"""
    # Get filter parameters
    current_filter = request.args.get('filter', 'all').strip().lower()
    search_query = request.args.get('search', '').strip()
    
    # Calculate summary counts
    total_count = Event.query.count()
    active_count = Event.query.filter_by(status_code='A').count()
    closed_count = Event.query.filter_by(status_code='C').count()
    
    counts = {
        'total': total_count,
        'active': active_count,
        'closed': closed_count
    }
    
    # Build query based on filter
    query = Event.query
    
    if current_filter == 'active':
        query = query.filter_by(status_code='A')
    elif current_filter == 'closed':
        query = query.filter_by(status_code='C')
    # else 'all' - no filter
    
    # Apply search if provided
    if search_query:
        search_pattern = f'%{search_query}%'
        query = query.filter(
            or_(
                Event.event_name.ilike(search_pattern),
                Event.event_desc.ilike(search_pattern),
                Event.impact_desc.ilike(search_pattern)
            )
        )
    
    # Order by start_date descending (most recent first)
    events = query.order_by(Event.start_date.desc()).all()
    
    return render_template(
        'events/list.html',
        events=events,
        event_types=EVENT_TYPES,
        counts=counts,
        current_filter=current_filter,
        search_query=search_query
    )


@events_bp.route('/create', methods=['GET', 'POST'])
@login_required
@feature_required('event_management')
def create_event():
    """Create new event"""
    if request.method == 'POST':
        # Prepare form data with default status for new events
        form_data = request.form.to_dict()
        form_data['status_code'] = 'A'
        
        # Validate form data
        is_valid, errors = validate_event_data(form_data)
        
        if not is_valid:
            # Show validation errors
            for field, error in errors.items():
                flash(error, 'danger')
            
            # Return to form with entered data
            return render_template(
                'events/create.html',
                event_types=EVENT_TYPES,
                today=date.today().strftime('%Y-%m-%d'),
                form_data=request.form,
                errors=errors
            )
        
        try:
            # Create event
            event = Event()
            event.event_type = request.form.get('event_type').strip()
            event.start_date = datetime.strptime(request.form.get('start_date').strip(), '%Y-%m-%d').date()
            event.event_name = request.form.get('event_name').strip()
            event.event_desc = request.form.get('event_desc').strip()
            event.impact_desc = request.form.get('impact_desc').strip()
            event.status_code = 'A'
            event.closed_date = None
            event.reason_desc = None
            
            # Audit fields
            add_audit_fields(event, current_user, is_new=True)
            
            db.session.add(event)
            db.session.commit()
            
            flash(f'Event "{event.event_name}" created successfully', 'success')
            return redirect(url_for('events.view_event', event_id=event.event_id))
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('Error creating event')
            flash('An error occurred while creating the event. Please try again or contact support.', 'danger')
            return render_template(
                'events/create.html',
                event_types=EVENT_TYPES,
                today=date.today().strftime('%Y-%m-%d'),
                form_data=request.form
            )
    
    # GET request
    return render_template(
        'events/create.html',
        event_types=EVENT_TYPES,
        today=date.today().strftime('%Y-%m-%d')
    )


@events_bp.route('/<int:event_id>')
@login_required
@feature_required('event_management')
def view_event(event_id):
    """View event details"""
    event = Event.query.get_or_404(event_id)
    return render_template('events/view.html', event=event)


@events_bp.route('/<int:event_id>/edit', methods=['GET', 'POST'])
@login_required
@feature_required('event_management')
def edit_event(event_id):
    """Edit existing event with optimistic locking"""
    event = Event.query.get_or_404(event_id)
    
    # Prevent editing closed events
    if event.status_code == 'C':
        flash('Closed events cannot be edited', 'warning')
        return redirect(url_for('events.view_event', event_id=event_id))
    
    if request.method == 'POST':
        from app.security.param_validation import safe_version_number
        
        # Optimistic locking check
        submitted_version = safe_version_number(request.form.get('version_nbr', 0))
        if submitted_version != event.version_nbr:
            flash('This record has been modified by another user. Please reload before updating.', 'warning')
            return redirect(url_for('events.view_event', event_id=event_id))
        
        # Validate form data
        is_valid, errors = validate_event_data(request.form, is_update=True)
        
        if not is_valid:
            # Show validation errors
            for field, error in errors.items():
                flash(error, 'danger')
            
            # Return to form
            return render_template(
                'events/edit.html',
                event=event,
                event_types=EVENT_TYPES,
                today=date.today().strftime('%Y-%m-%d'),
                errors=errors
            )
        
        try:
            # Issue fresh SELECT with row lock to prevent concurrent modifications
            fresh_event = db.session.query(Event).filter_by(event_id=event_id).with_for_update().first()
            
            if not fresh_event:
                flash('Event not found', 'danger')
                return redirect(url_for('events.list_events'))
            
            # Check version against fresh database state
            if submitted_version != fresh_event.version_nbr:
                db.session.rollback()
                flash('This record has been modified by another user. Please reload before updating.', 'warning')
                return redirect(url_for('events.view_event', event_id=event_id))
            
            # Check status against fresh database state
            if fresh_event.status_code == 'C':
                db.session.rollback()
                flash('This event was closed by another user. Changes cannot be saved.', 'warning')
                return redirect(url_for('events.view_event', event_id=event_id))
            
            # Update event fields using the freshly queried instance
            fresh_event.event_type = request.form.get('event_type').strip()
            fresh_event.start_date = datetime.strptime(request.form.get('start_date').strip(), '%Y-%m-%d').date()
            fresh_event.event_name = request.form.get('event_name').strip()
            fresh_event.event_desc = request.form.get('event_desc').strip()
            fresh_event.impact_desc = request.form.get('impact_desc').strip()
            
            # Update audit fields
            add_audit_fields(fresh_event, current_user, is_new=False)
            
            db.session.commit()
            
            flash(f'Event "{fresh_event.event_name}" updated successfully', 'success')
            return redirect(url_for('events.view_event', event_id=event_id))
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('Error updating event')
            flash('An error occurred while updating the event. Please try again or contact support.', 'danger')
            return render_template(
                'events/edit.html',
                event=event,
                event_types=EVENT_TYPES
            )
    
    # GET request
    return render_template(
        'events/edit.html',
        event=event,
        event_types=EVENT_TYPES,
        today=date.today().strftime('%Y-%m-%d')
    )


@events_bp.route('/<int:event_id>/close', methods=['POST'])
@login_required
@feature_required('event_management')
def close_event(event_id):
    """Close an active event with concurrent modification protection"""
    # Get reason from form
    reason_desc = request.form.get('reason_desc', '').strip()
    
    # Validation
    if not reason_desc:
        flash('Reason for closure is required', 'danger')
        return redirect(url_for('events.view_event', event_id=event_id))
    
    try:
        # Parse and validate closed_date inside try block
        closed_date_str = request.form.get('closed_date', '').strip()
        if not closed_date_str:
            closed_date = date.today()
        else:
            closed_date = datetime.strptime(closed_date_str, '%Y-%m-%d').date()
        
        # Issue fresh SELECT with row lock to prevent concurrent modifications
        event = db.session.query(Event).filter_by(event_id=event_id).with_for_update().first()
        
        if not event:
            flash('Event not found', 'danger')
            return redirect(url_for('events.list_events'))
        
        # Check if already closed
        if event.status_code == 'C':
            db.session.rollback()
            flash('Event is already closed', 'warning')
            return redirect(url_for('events.view_event', event_id=event_id))
        
        # Validate closed_date is not before start_date
        if closed_date < event.start_date:
            db.session.rollback()
            flash('Closed date cannot be earlier than start date', 'danger')
            return redirect(url_for('events.view_event', event_id=event_id))
        
        # Close the event
        event.status_code = 'C'
        event.closed_date = closed_date
        event.reason_desc = reason_desc
        add_audit_fields(event, current_user, is_new=False)
        
        db.session.commit()
        
        flash(f'Event "{event.event_name}" has been closed', 'success')
        return redirect(url_for('events.view_event', event_id=event_id))
        
    except ValueError:
        flash('Invalid date format', 'danger')
        return redirect(url_for('events.view_event', event_id=event_id))
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error closing event')
        flash('An error occurred while closing the event. Please try again or contact support.', 'danger')
        return redirect(url_for('events.view_event', event_id=event_id))


@events_bp.route('/<int:event_id>/delete', methods=['POST'])
@login_required
@feature_required('event_management')
def delete_event(event_id):
    """Delete event (only if not referenced)"""
    event = Event.query.get_or_404(event_id)
    event_name = event.event_name
    
    try:
        # Check for references (FK constraints will prevent deletion if referenced)
        db.session.delete(event)
        db.session.commit()
        
        flash(f'Event "{event_name}" deleted successfully', 'success')
        return redirect(url_for('events.list_events'))
        
    except IntegrityError as e:
        db.session.rollback()
        flash('This event cannot be deleted because it is referenced by other records.', 'danger')
        return redirect(url_for('events.view_event', event_id=event_id))
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error deleting event')
        flash('An error occurred while deleting the event. Please try again or contact support.', 'danger')
        return redirect(url_for('events.view_event', event_id=event_id))
