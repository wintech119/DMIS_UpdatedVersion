"""
Eligibility Approval Workflow
Allows Directors (PEOD, DDG, DG) to review and approve/deny relief requests
"""
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, abort, current_app
from flask_login import login_required, current_user

from app.db import db
from app.core.rbac import executive_required
from app.core import session_utils
from app.services import relief_request_service as rr_service

eligibility_bp = Blueprint('eligibility', __name__, url_prefix='/eligibility')


@eligibility_bp.route('/pending')
@login_required
@executive_required
def pending_list():
    """
    List all relief requests pending eligibility review.
    Only accessible to users with reliefrqst.approve_eligibility permission.
    """
    from app.db.models import ReliefRqst, ReliefRqstItem, Item
    from sqlalchemy.orm import joinedload
    
    # Get priority filter from query params
    priority_filter = request.args.get('priority', 'all')
    
    # Base query for pending requests with eager loading
    base_query = ReliefRqst.query.filter_by(
        status_code=rr_service.STATUS_AWAITING_APPROVAL
    ).filter(
        ReliefRqst.review_by_id.is_(None)
    ).options(
        joinedload(ReliefRqst.agency),
        joinedload(ReliefRqst.items).joinedload(ReliefRqstItem.item).joinedload(Item.default_uom),
        joinedload(ReliefRqst.items).joinedload(ReliefRqstItem.item).joinedload(Item.category),
        joinedload(ReliefRqst.eligible_event)
    )
    
    # Get all pending for metrics
    all_pending = base_query.order_by(
        ReliefRqst.request_date.desc(),
        ReliefRqst.urgency_ind.desc()
    ).all()
    
    # Apply filter if specified
    if priority_filter == 'high':
        pending_requests = [req for req in all_pending if req.urgency_ind in ['C', 'H']]
    else:
        pending_requests = all_pending
    
    # Calculate metrics from all pending
    total_pending = len(all_pending)
    high_priority = sum(1 for req in all_pending if req.urgency_ind in ['C', 'H'])
    total_items = sum(len(req.items) if req.items else 0 for req in all_pending)
    
    return render_template('eligibility/pending.html',
                         requests=pending_requests,
                         total_pending=total_pending,
                         high_priority=high_priority,
                         total_items=total_items,
                         current_filter=priority_filter)


@eligibility_bp.route('/review/<int:request_id>')
@login_required
@executive_required
def review_request(request_id):
    """
    View full details of a relief request for eligibility review.
    """
    from app.db.models import ReliefRqst, ReliefRqstItem, Item
    from sqlalchemy.orm import joinedload
    from flask import abort
    
    # Get request with eager loading to prevent N+1 queries
    relief_request = ReliefRqst.query.options(
        joinedload(ReliefRqst.agency),
        joinedload(ReliefRqst.items).joinedload(ReliefRqstItem.item).joinedload(Item.default_uom),
        joinedload(ReliefRqst.items).joinedload(ReliefRqstItem.item).joinedload(Item.category),
        joinedload(ReliefRqst.eligible_event),
        joinedload(ReliefRqst.status)
    ).get(request_id)
    
    if not relief_request:
        flash('Relief request not found.', 'danger')
        return redirect(url_for('eligibility.pending_list'))
    
    # Check if eligibility decision has been made
    decision_made = (
        relief_request.review_by_id is not None or
        relief_request.status_code in [rr_service.STATUS_INELIGIBLE, rr_service.STATUS_DENIED]
    )
    
    can_edit = not decision_made and relief_request.status_code == rr_service.STATUS_AWAITING_APPROVAL
    
    return render_template('eligibility/review.html',
                         request=relief_request,
                         items=relief_request.items,
                         decision_made=decision_made,
                         can_edit=can_edit,
                         STATUS_AWAITING_APPROVAL=rr_service.STATUS_AWAITING_APPROVAL,
                         STATUS_INELIGIBLE=rr_service.STATUS_INELIGIBLE,
                         STATUS_SUBMITTED=rr_service.STATUS_SUBMITTED)


@eligibility_bp.route('/decision/<int:request_id>', methods=['POST'])
@login_required
@executive_required
def submit_decision(request_id):
    """
    Submit eligibility decision for a relief request.
    POST body: { decision: 'Y' | 'N', reason: string (required if decision='N') }
    """
    try:
        decision = request.form.get('decision')
        reason = request.form.get('reason', '').strip()
        
        # Validate decision
        if not decision or decision not in ['Y', 'N']:
            flash('Invalid decision. Please select Eligible or Ineligible.', 'danger')
            return redirect(url_for('eligibility.review_request', request_id=request_id))
        
        # Validate reason for ineligible
        if decision == 'N' and not reason:
            flash('Reason is required when marking a request as ineligible.', 'danger')
            return redirect(url_for('eligibility.review_request', request_id=request_id))
        
        # Submit decision
        success, message = rr_service.submit_eligibility_decision(
            reliefrqst_id=request_id,
            decision=decision,
            reason=reason if decision == 'N' else None,
            reviewer_email=session_utils.get_email()
        )
        
        if success:
            db.session.commit()
            flash(message, 'success')
            return redirect(url_for('eligibility.pending_list'))
        else:
            flash(message, 'danger')
            return redirect(url_for('eligibility.review_request', request_id=request_id))
            
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error submitting eligibility decision')
        flash('An error occurred while submitting your decision. Please try again or contact support.', 'danger')
        return redirect(url_for('eligibility.review_request', request_id=request_id))


# API Endpoints for JavaScript/AJAX if needed

@eligibility_bp.route('/api/pending', methods=['GET'])
@login_required
@executive_required
def api_pending_list():
    """
    API endpoint: Get pending eligibility requests as JSON.
    """
    pending_requests = rr_service.get_pending_eligibility_requests()
    
    result = []
    for req in pending_requests:
        result.append({
            'reliefrqst_id': req.reliefrqst_id,
            'tracking_no': req.tracking_no if hasattr(req, 'tracking_no') else str(req.reliefrqst_id),
            'agency_id': req.agency_id,
            'agency_name': req.agency.agency_name if req.agency else 'Unknown',
            'request_date': req.request_date.isoformat() if req.request_date else None,
            'urgency_ind': req.urgency_ind,
            'status_code': req.status_code
        })
    
    return jsonify(result)


@eligibility_bp.route('/api/<int:request_id>', methods=['GET'])
@login_required
@executive_required
def api_get_request(request_id):
    """
    API endpoint: Get full request details for eligibility review.
    """
    eligibility_data = rr_service.get_request_eligibility_details(request_id)
    
    if not eligibility_data:
        return jsonify({'error': 'Request not found'}), 404
    
    relief_request = eligibility_data['request']
    items = eligibility_data['items']
    
    result = {
        'request': {
            'reliefrqst_id': relief_request.reliefrqst_id,
            'tracking_no': relief_request.tracking_no if hasattr(relief_request, 'tracking_no') else str(relief_request.reliefrqst_id),
            'agency_id': relief_request.agency_id,
            'agency_name': relief_request.agency.agency_name if relief_request.agency else 'Unknown',
            'request_date': relief_request.request_date.isoformat() if relief_request.request_date else None,
            'urgency_ind': relief_request.urgency_ind,
            'status_code': relief_request.status_code,
            'rqst_notes_text': relief_request.rqst_notes_text,
            'review_notes_text': relief_request.review_notes_text,
            'status_reason_desc': relief_request.status_reason_desc,
        },
        'items': [
            {
                'item_id': item.item_id,
                'item_name': item.item.item_name if item.item else 'Unknown',
                'request_qty': float(item.request_qty),
                'urgency_ind': item.urgency_ind,
                'rqst_reason_desc': item.rqst_reason_desc
            }
            for item in items
        ],
        'decision_made': eligibility_data['decision_made'],
        'can_edit': eligibility_data['can_edit']
    }
    
    return jsonify(result)


@eligibility_bp.route('/api/decision/<int:request_id>', methods=['POST'])
@login_required
@executive_required
def api_submit_decision(request_id):
    """
    API endpoint: Submit eligibility decision.
    POST JSON: { decision: 'Y' | 'N', reason: string (optional) }
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'Invalid JSON'}), 400
        
        decision = data.get('decision')
        reason = data.get('reason', '').strip()
        
        # Validate
        if not decision or decision not in ['Y', 'N']:
            return jsonify({'error': 'Invalid decision. Must be Y or N.'}), 400
        
        if decision == 'N' and not reason:
            return jsonify({'error': 'Reason is required for ineligible decisions.'}), 400
        
        # Submit decision
        success, message = rr_service.submit_eligibility_decision(
            reliefrqst_id=request_id,
            decision=decision,
            reason=reason if decision == 'N' else None,
            reviewer_email=session_utils.get_email()
        )
        
        if success:
            db.session.commit()
            return jsonify({'success': True, 'message': message}), 200
        else:
            return jsonify({'success': False, 'error': message}), 400
            
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500
