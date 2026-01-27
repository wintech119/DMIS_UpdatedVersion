"""
ODPEM Director Dashboard
Unified view for ODPEM directors (DG, DDG, Dir, PEOD) to see all relief requests,
pending eligibility reviews, and pending fulfillments in one place.
"""
from flask import Blueprint, render_template, request
from flask_login import login_required
from sqlalchemy.orm import joinedload

from app.db import db
from app.db.models import ReliefRqst, ReliefRqstItem, Item
from app.core.rbac import role_required
from app.services import relief_request_service as rr_service

director_bp = Blueprint('director', __name__, url_prefix='/director')


@director_bp.route('/dashboard')
@login_required
@role_required('ODPEM_DG', 'ODPEM_DDG', 'ODPEM_DIR_PEOD')
def dashboard():
    """
    Unified dashboard for ODPEM directors showing all relief requests
    with sections for pending eligibility review and pending fulfillment.
    """
    from app.security.param_validation import validate_filter_value
    
    # Get filter from query params with validation
    ALLOWED_DIRECTOR_FILTERS = {'pending_review', 'pending_fulfillment', 'in_progress', 'completed', 'all'}
    view_filter = validate_filter_value(
        request.args.get('filter', 'pending_review'),
        ALLOWED_DIRECTOR_FILTERS,
        default='pending_review'
    )
    
    # Calculate counts using independent queries (avoid cumulative filter issue)
    counts = {
        'pending_review': ReliefRqst.query.filter_by(
            status_code=rr_service.STATUS_AWAITING_APPROVAL
        ).filter(
            ReliefRqst.review_by_id.is_(None)
        ).count(),
        'pending_fulfillment': ReliefRqst.query.filter(
            ReliefRqst.status_code.in_([
                rr_service.STATUS_SUBMITTED,
                rr_service.STATUS_PART_FILLED
            ])
        ).count(),
        'in_progress': ReliefRqst.query.filter(
            ReliefRqst.status_code.in_([
                rr_service.STATUS_AWAITING_APPROVAL,
                rr_service.STATUS_SUBMITTED,
                rr_service.STATUS_PART_FILLED
            ])
        ).count(),
        'completed': ReliefRqst.query.filter_by(
            status_code=rr_service.STATUS_FILLED
        ).count()
    }
    
    # Total includes all statuses
    counts['total'] = ReliefRqst.query.count()
    
    # Build query with comprehensive eager loading (independent for each filter)
    def build_query():
        """Create a fresh query with all eager loading"""
        return ReliefRqst.query.options(
            joinedload(ReliefRqst.agency),
            joinedload(ReliefRqst.items).joinedload(ReliefRqstItem.item).joinedload(Item.default_uom),
            joinedload(ReliefRqst.items).joinedload(ReliefRqstItem.item).joinedload(Item.category),
            joinedload(ReliefRqst.eligible_event),
            joinedload(ReliefRqst.status)
        )
    
    # Apply filter with independent queries
    if view_filter == 'pending_review':
        # Requests awaiting eligibility review
        requests = build_query().filter_by(
            status_code=rr_service.STATUS_AWAITING_APPROVAL
        ).filter(
            ReliefRqst.review_by_id.is_(None)
        ).order_by(
            ReliefRqst.create_dtime.desc()
        ).all()
    elif view_filter == 'pending_fulfillment':
        # Requests approved and awaiting fulfillment
        requests = build_query().filter(
            ReliefRqst.status_code.in_([
                rr_service.STATUS_SUBMITTED,
                rr_service.STATUS_PART_FILLED
            ])
        ).order_by(
            ReliefRqst.create_dtime.desc()
        ).all()
    elif view_filter == 'in_progress':
        # All requests in progress (not completed/cancelled/denied)
        requests = build_query().filter(
            ReliefRqst.status_code.in_([
                rr_service.STATUS_AWAITING_APPROVAL,
                rr_service.STATUS_SUBMITTED,
                rr_service.STATUS_PART_FILLED
            ])
        ).order_by(
            ReliefRqst.create_dtime.desc()
        ).all()
    elif view_filter == 'completed':
        # Completed/filled requests
        requests = build_query().filter_by(
            status_code=rr_service.STATUS_FILLED
        ).order_by(
            ReliefRqst.create_dtime.desc()
        ).all()
    else:
        # All requests (complete history)
        requests = build_query().order_by(
            ReliefRqst.create_dtime.desc()
        ).all()
    
    return render_template('director/dashboard.html',
                         requests=requests,
                         current_filter=view_filter,
                         counts=counts,
                         STATUS_DRAFT=rr_service.STATUS_DRAFT,
                         STATUS_AWAITING_APPROVAL=rr_service.STATUS_AWAITING_APPROVAL,
                         STATUS_SUBMITTED=rr_service.STATUS_SUBMITTED,
                         STATUS_PART_FILLED=rr_service.STATUS_PART_FILLED,
                         STATUS_FILLED=rr_service.STATUS_FILLED,
                         STATUS_INELIGIBLE=rr_service.STATUS_INELIGIBLE,
                         STATUS_DENIED=rr_service.STATUS_DENIED,
                         STATUS_CANCELLED=rr_service.STATUS_CANCELLED,
                         STATUS_CLOSED=rr_service.STATUS_CLOSED)
