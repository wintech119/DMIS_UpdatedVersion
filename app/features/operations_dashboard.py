"""
Operations Dashboard Blueprint - Executive Performance Dashboard

Provides high-level operational metrics and visualizations for:
- Director General (DG)
- Deputy Director General (Deputy DG)
- Director, PEOD

Shows system-wide operational performance for donations and relief fulfillment.
Read-only dashboard with KPIs and charts.
"""

from flask import Blueprint, render_template, jsonify, request
from flask_login import login_required, current_user
from sqlalchemy import func, desc, extract, and_
from app.db.models import (
    db, Donation, DonationItem, ReliefRqst, ReliefPkg, 
    ReliefPkgItem, Agency, Event
)
from app.core.rbac import executive_required
from app.services import relief_request_service as rr_service
from datetime import datetime, timedelta
from collections import defaultdict
from app.utils.timezone import now as jamaica_now

operations_dashboard_bp = Blueprint('operations_dashboard', __name__)

@operations_dashboard_bp.route('/executive/operations')
@login_required
@executive_required
def index():
    """
    Executive Operations Dashboard showing system-wide operational metrics.
    Access restricted to DG, Deputy DG, and Director PEOD only.
    """
    # Get time period from query parameter (default: 30 days)
    # Validate period_days: must be 1-365 to prevent DoS
    from app.security.param_validation import safe_period_days
    period_days = safe_period_days(request.args.get('period', 30))
    start_date = jamaica_now() - timedelta(days=period_days)
    
    # =======================
    # DONATION METRICS
    # =======================
    
    # Total donations in period
    total_donations = Donation.query.filter(
        Donation.received_date >= start_date.date()
    ).count()
    
    # Total donation items
    total_donation_items = db.session.query(func.count(DonationItem.donation_id)).join(
        Donation
    ).filter(
        Donation.received_date >= start_date.date()
    ).scalar() or 0
    
    # Donations by donor (top 10)
    from app.db.models import Donor
    donations_by_donor = db.session.query(
        Donor.donor_name,
        func.count(Donation.donation_id).label('count')
    ).join(
        Donation, Donor.donor_id == Donation.donor_id
    ).filter(
        Donation.received_date >= start_date.date()
    ).group_by(
        Donor.donor_name
    ).order_by(
        desc('count')
    ).limit(10).all()
    
    # Donations timeline (by week)
    donations_timeline_raw = db.session.query(
        func.date_trunc('week', Donation.received_date).label('week'),
        func.count(Donation.donation_id).label('count')
    ).filter(
        Donation.received_date >= start_date.date()
    ).group_by(
        'week'
    ).order_by(
        'week'
    ).all()
    
    # Convert to JSON-serializable format
    donations_timeline = {
        'labels': [row.week.strftime('%Y-%m-%d') if row.week else '' for row in donations_timeline_raw],
        'values': [int(row.count) for row in donations_timeline_raw]
    }
    
    # =======================
    # RELIEF REQUEST METRICS
    # =======================
    
    # Total relief requests in period
    total_requests = ReliefRqst.query.filter(
        ReliefRqst.create_dtime >= start_date
    ).count()
    
    # Requests by status
    requests_by_status = db.session.query(
        ReliefRqst.status_code,
        func.count(ReliefRqst.reliefrqst_id).label('count')
    ).filter(
        ReliefRqst.create_dtime >= start_date
    ).group_by(
        ReliefRqst.status_code
    ).all()
    
    # Convert to dict with readable labels using canonical status constants
    status_labels = {
        rr_service.STATUS_DRAFT: 'Draft',
        rr_service.STATUS_AWAITING_APPROVAL: 'Awaiting Approval',
        rr_service.STATUS_CANCELLED: 'Cancelled',
        rr_service.STATUS_SUBMITTED: 'Submitted',
        rr_service.STATUS_DENIED: 'Denied',
        rr_service.STATUS_PART_FILLED: 'Partly Filled',
        rr_service.STATUS_CLOSED: 'Closed',
        rr_service.STATUS_FILLED: 'Filled',
        rr_service.STATUS_INELIGIBLE: 'Ineligible'
    }
    
    status_breakdown = {
        'labels': [status_labels.get(status, f'Status {status}') for status, count in requests_by_status],
        'values': [count for status, count in requests_by_status]
    }
    
    # Current operational counts (all-time, not just period)
    current_counts = {
        'awaiting_filling': ReliefRqst.query.filter_by(status_code=3).count(),
        'being_prepared': ReliefRqst.query.filter_by(status_code=5).count(),
        'awaiting_approval': ReliefRqst.query.filter_by(status_code=6).count(),
        'approved_dispatch': ReliefPkg.query.filter(
            ReliefPkg.status_code == 'D',
            ReliefPkg.received_dtime.is_(None)
        ).count(),
        'completed': ReliefRqst.query.filter_by(status_code=7).count()
    }
    
    # =======================
    # FULFILLMENT METRICS
    # =======================
    
    # Total packages created in period
    total_packages = ReliefPkg.query.filter(
        ReliefPkg.create_dtime >= start_date
    ).count()
    
    # Packages dispatched in period
    packages_dispatched = ReliefPkg.query.filter(
        ReliefPkg.dispatch_dtime >= start_date,
        ReliefPkg.status_code == 'D'
    ).count()
    
    # Packages received in period
    packages_received = ReliefPkg.query.filter(
        ReliefPkg.received_dtime >= start_date,
        ReliefPkg.status_code == 'R'
    ).count()
    
    # Top requesting agencies (by fulfilled requests)
    top_agencies_raw = db.session.query(
        Agency.agency_name,
        func.count(ReliefRqst.reliefrqst_id).label('count')
    ).join(
        ReliefRqst
    ).filter(
        ReliefRqst.status_code == 7,  # Completed
        ReliefRqst.action_dtime >= start_date
    ).group_by(
        Agency.agency_name
    ).order_by(
        desc('count')
    ).limit(10).all()
    
    # Convert to JSON-serializable format
    top_agencies = {
        'labels': [row.agency_name for row in top_agencies_raw],
        'values': [int(row.count) for row in top_agencies_raw]
    }
    
    # Relief requests timeline (by week)
    requests_timeline_raw = db.session.query(
        func.date_trunc('week', ReliefRqst.create_dtime).label('week'),
        func.count(ReliefRqst.reliefrqst_id).label('count')
    ).filter(
        ReliefRqst.create_dtime >= start_date
    ).group_by(
        'week'
    ).order_by(
        'week'
    ).all()
    
    # Fulfilled requests timeline (by week)
    fulfilled_timeline_raw = db.session.query(
        func.date_trunc('week', ReliefRqst.action_dtime).label('week'),
        func.count(ReliefRqst.reliefrqst_id).label('count')
    ).filter(
        ReliefRqst.status_code == 7,
        ReliefRqst.action_dtime >= start_date
    ).group_by(
        'week'
    ).order_by(
        'week'
    ).all()
    
    # Convert to JSON-serializable format
    requests_timeline = {
        'labels': [row.week.strftime('%Y-%m-%d') if row.week else '' for row in requests_timeline_raw],
        'values': [int(row.count) for row in requests_timeline_raw]
    }
    
    fulfilled_timeline = {
        'labels': [row.week.strftime('%Y-%m-%d') if row.week else '' for row in fulfilled_timeline_raw],
        'values': [int(row.count) for row in fulfilled_timeline_raw]
    }
    
    # =======================
    # AVERAGE TIME METRICS
    # =======================
    
    # Average time from submission to approval (days)
    avg_approval_time = db.session.query(
        func.avg(
            func.extract('epoch', ReliefRqst.review_dtime - ReliefRqst.create_dtime) / 86400
        )
    ).filter(
        ReliefRqst.review_dtime.isnot(None),
        ReliefRqst.create_dtime >= start_date
    ).scalar()
    
    # Average time from approval to dispatch (days)
    avg_dispatch_time = db.session.query(
        func.avg(
            func.extract('epoch', ReliefPkg.dispatch_dtime - ReliefRqst.review_dtime) / 86400
        )
    ).join(
        ReliefRqst, ReliefPkg.reliefrqst_id == ReliefRqst.reliefrqst_id
    ).filter(
        ReliefPkg.dispatch_dtime.isnot(None),
        ReliefRqst.review_dtime.isnot(None),
        ReliefPkg.dispatch_dtime >= start_date
    ).scalar()
    
    context = {
        'period_days': period_days,
        # Donation KPIs
        'total_donations': total_donations,
        'total_donation_items': total_donation_items,
        'donations_timeline': donations_timeline,
        # Relief Request KPIs
        'total_requests': total_requests,
        'status_breakdown': status_breakdown,
        'current_counts': current_counts,
        'requests_timeline': requests_timeline,
        'fulfilled_timeline': fulfilled_timeline,
        # Fulfillment KPIs
        'total_packages': total_packages,
        'packages_dispatched': packages_dispatched,
        'packages_received': packages_received,
        'top_agencies': top_agencies,
        # Time metrics
        'avg_approval_time': round(avg_approval_time, 1) if avg_approval_time else None,
        'avg_dispatch_time': round(avg_dispatch_time, 1) if avg_dispatch_time else None,
    }
    
    return render_template('operations_dashboard/index.html', **context)
