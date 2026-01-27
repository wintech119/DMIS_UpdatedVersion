from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from app.db import db
from app.db.models import AgencyAccountRequest, AgencyAccountRequestAudit, Agency, User
from app.core.rbac import is_admin
from sqlalchemy.orm.exc import StaleDataError
from datetime import datetime
from app.security.rate_limiting import limiter

account_requests_bp = Blueprint('account_requests', __name__, url_prefix='/account-requests')

@account_requests_bp.route('/submit', methods=['GET'])
@limiter.limit("10 per minute")
def submit_form():
    return render_template('account_requests/submit.html')

@account_requests_bp.route('/', methods=['POST'])
@limiter.limit("5 per minute")
def create_request():
    try:
        agency_name = request.form.get('agency_name', '').strip().upper()
        contact_name = request.form.get('contact_name', '').strip().upper()
        contact_phone = request.form.get('contact_phone', '').strip()
        contact_email = request.form.get('contact_email', '').strip().lower()
        reason_text = request.form.get('reason_text', '').strip().upper()
        
        if not all([agency_name, contact_name, contact_phone, contact_email, reason_text]):
            flash('All fields are required.', 'danger')
            return redirect(url_for('account_requests.submit_form'))
        
        existing = AgencyAccountRequest.query.filter(
            AgencyAccountRequest.contact_email == contact_email,
            AgencyAccountRequest.status_code.in_(['S', 'R'])
        ).first()
        
        if existing:
            flash('An active request already exists for this email address.', 'warning')
            return redirect(url_for('account_requests.submit_form'))
        
        actor_id = current_user.user_id if current_user.is_authenticated else 1
        
        new_request = AgencyAccountRequest(
            agency_name=agency_name,
            contact_name=contact_name,
            contact_phone=contact_phone,
            contact_email=contact_email,
            reason_text=reason_text,
            status_code='S',
            created_by_id=actor_id,
            updated_by_id=actor_id
        )
        
        db.session.add(new_request)
        db.session.flush()
        
        audit = AgencyAccountRequestAudit(
            request_id=new_request.request_id,
            event_type='submitted',
            event_notes='Request submitted',
            actor_user_id=actor_id
        )
        db.session.add(audit)
        db.session.commit()
        
        flash('Your agency account request has been submitted successfully. You will be notified once it is reviewed.', 'success')
        return redirect(url_for('account_requests.submit_form'))
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error submitting account request')
        flash('An error occurred while submitting your request. Please try again or contact support.', 'danger')
        return redirect(url_for('account_requests.submit_form'))

@account_requests_bp.route('/', methods=['GET'])
@login_required
def list_requests():
    if not is_admin():
        flash('Access denied. Administrator privileges required.', 'danger')
        return redirect(url_for('dashboard.index'))
    
    from app.security.param_validation import validate_status_code
    
    # Validate status filter against allowed account request status codes
    ALLOWED_REQUEST_STATUSES = {'all', 'S', 'R', 'A', 'D'}  # Submitted, Review, Approved, Denied
    status_filter = validate_status_code(
        request.args.get('status', 'all'),
        ALLOWED_REQUEST_STATUSES,
        default='all'
    )
    
    query = AgencyAccountRequest.query
    
    if status_filter != 'all':
        query = query.filter_by(status_code=status_filter)
    
    requests = query.order_by(AgencyAccountRequest.created_at.desc()).all()
    
    return render_template('account_requests/list.html', 
                         requests=requests, 
                         status_filter=status_filter)

@account_requests_bp.route('/<int:request_id>', methods=['GET'])
@login_required
def view_request(request_id):
    if not is_admin():
        flash('Access denied. Administrator privileges required.', 'danger')
        return redirect(url_for('dashboard.index'))
    
    account_request = AgencyAccountRequest.query.get_or_404(request_id)
    audit_log = AgencyAccountRequestAudit.query.filter_by(
        request_id=request_id
    ).order_by(AgencyAccountRequestAudit.event_dtime.desc()).all()
    
    return render_template('account_requests/view.html', 
                         account_request=account_request,
                         audit_log=audit_log)

@account_requests_bp.route('/<int:request_id>/start-review', methods=['POST'])
@login_required
def start_review(request_id):
    if not is_admin():
        flash('Access denied. Administrator privileges required.', 'danger')
        return redirect(url_for('dashboard.index'))
    
    try:
        account_request = AgencyAccountRequest.query.get_or_404(request_id)
        version = account_request.version_nbr
        
        if account_request.status_code != 'S':
            flash('Only submitted requests can be moved to review.', 'warning')
            return redirect(url_for('account_requests.view_request', request_id=request_id))
        
        account_request.status_code = 'R'
        account_request.updated_by_id = current_user.user_id
        
        audit = AgencyAccountRequestAudit(
            request_id=request_id,
            event_type='moved_to_review',
            event_notes='Request moved to review',
            actor_user_id=current_user.user_id
        )
        db.session.add(audit)
        db.session.commit()
        
        flash('Request moved to review status.', 'success')
        
    except StaleDataError:
        db.session.rollback()
        flash('This request was modified by another user. Please refresh and try again.', 'warning')
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error updating account request')
        flash('An error occurred while updating the request. Please try again.', 'danger')
    
    return redirect(url_for('account_requests.view_request', request_id=request_id))

@account_requests_bp.route('/<int:request_id>/approve', methods=['POST'])
@login_required
def approve_request(request_id):
    if not is_admin():
        flash('Access denied. Administrator privileges required.', 'danger')
        return redirect(url_for('dashboard.index'))
    
    try:
        account_request = AgencyAccountRequest.query.get_or_404(request_id)
        notes = request.form.get('notes', '').strip().upper()
        
        if account_request.status_code not in ['S', 'R']:
            flash('Only submitted or under-review requests can be approved.', 'warning')
            return redirect(url_for('account_requests.view_request', request_id=request_id))
        
        account_request.status_code = 'A'
        account_request.status_reason = notes
        account_request.updated_by_id = current_user.user_id
        
        audit = AgencyAccountRequestAudit(
            request_id=request_id,
            event_type='approved',
            event_notes=notes or 'Request approved',
            actor_user_id=current_user.user_id
        )
        db.session.add(audit)
        db.session.commit()
        
        flash('Request approved successfully. You can now provision the agency and user account.', 'success')
        
    except StaleDataError:
        db.session.rollback()
        flash('This request was modified by another user. Please refresh and try again.', 'warning')
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error approving account request')
        flash('An error occurred while approving the request. Please try again.', 'danger')
    
    return redirect(url_for('account_requests.view_request', request_id=request_id))

@account_requests_bp.route('/<int:request_id>/deny', methods=['POST'])
@login_required
def deny_request(request_id):
    if not is_admin():
        flash('Access denied. Administrator privileges required.', 'danger')
        return redirect(url_for('dashboard.index'))
    
    try:
        account_request = AgencyAccountRequest.query.get_or_404(request_id)
        reason = request.form.get('reason', '').strip().upper()
        
        if not reason:
            flash('Denial reason is required.', 'danger')
            return redirect(url_for('account_requests.view_request', request_id=request_id))
        
        if account_request.status_code not in ['S', 'R']:
            flash('Only submitted or under-review requests can be denied.', 'warning')
            return redirect(url_for('account_requests.view_request', request_id=request_id))
        
        account_request.status_code = 'D'
        account_request.status_reason = reason
        account_request.updated_by_id = current_user.user_id
        
        audit = AgencyAccountRequestAudit(
            request_id=request_id,
            event_type='denied',
            event_notes=reason,
            actor_user_id=current_user.user_id
        )
        db.session.add(audit)
        db.session.commit()
        
        flash('Request has been denied.', 'info')
        
    except StaleDataError:
        db.session.rollback()
        flash('This request was modified by another user. Please refresh and try again.', 'warning')
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error denying account request')
        flash('An error occurred while denying the request. Please try again.', 'danger')
    
    return redirect(url_for('account_requests.view_request', request_id=request_id))

@account_requests_bp.route('/<int:request_id>/provision', methods=['POST'])
@login_required
def provision_account(request_id):
    if not is_admin():
        flash('Access denied. Administrator privileges required.', 'danger')
        return redirect(url_for('dashboard.index'))
    
    flash('Account provisioning feature coming soon. This will create the agency and user account.', 'info')
    return redirect(url_for('account_requests.view_request', request_id=request_id))
