"""
Relief Request Service Layer
Handles business logic, optimistic locking, and notifications for agency relief requests
"""
from datetime import datetime, date
from decimal import Decimal
from typing import List, Dict, Optional, Tuple
from flask import url_for

from app.db import db
from app.db.models import (
    ReliefRqst, ReliefRqstItem, Item, Event, Agency, User, Notification,
    ReliefPkg, ReliefPkgItem, DBIntake, DBIntakeItem, Role
)
from app.core.exceptions import OptimisticLockError
from app.utils.timezone import now as jamaica_now


# Status codes mapping (from reliefrqst_status lookup table)
STATUS_DRAFT = 0              # DRAFT - Request being prepared
STATUS_AWAITING_APPROVAL = 1  # Awaiting approval - Internal approval pending
STATUS_CANCELLED = 2          # CANCELLED - Request cancelled
STATUS_SUBMITTED = 3          # SUBMITTED - Submitted to ODPEM
STATUS_DENIED = 4             # DENIED - Request denied by ODPEM
STATUS_PART_FILLED = 5        # PART FILLED - Partially fulfilled
STATUS_CLOSED = 6             # CLOSED - Request closed
STATUS_FILLED = 7             # FILLED - Request completely fulfilled
STATUS_INELIGIBLE = 8         # INELIGIBLE - Request marked ineligible

# Relief Request Item status codes (from reliefrqst_item.status_code constraint)
ITEM_STATUS_REQUESTED = 'R'       # Requested
ITEM_STATUS_UNAVAILABLE = 'U'     # Unavailable
ITEM_STATUS_WAITING = 'W'         # Waiting availability
ITEM_STATUS_DENIED = 'D'          # Denied
ITEM_STATUS_PARTLY_FILLED = 'P'   # Partly filled
ITEM_STATUS_LIMIT_ALLOWED = 'L'   # Limit allowed
ITEM_STATUS_FILLED = 'F'          # Filled

# Relief Request Item status code labels
ITEM_STATUS_LABELS = {
    'R': 'Requested',
    'U': 'Unavailable',
    'W': 'Waiting availability',
    'D': 'Denied',
    'P': 'Partly filled',
    'L': 'Limit allowed',
    'F': 'Filled'
}

URGENCY_HIGH = 'H'
URGENCY_MEDIUM = 'M'
URGENCY_LOW = 'L'
URGENCY_CRITICAL = 'C'

# Relief Package (ReliefPkg) status codes
PKG_STATUS_PENDING = 'P'         # Pending - Package being prepared or awaiting approval
PKG_STATUS_DISPATCHED = 'D'      # Dispatched - Package sent to inventory clerk
PKG_STATUS_COMPLETED = 'C'       # Completed - Package received and processed

# Relief Package status labels
PKG_STATUS_LABELS = {
    'P': 'Pending',
    'D': 'Dispatched',
    'C': 'Completed'
}


def get_workflow_steps(status_code: int) -> Dict:
    """
    Map status code to workflow step for the dynamic stepper component.
    Returns current step number (1-5) and step metadata.
    """
    if status_code == STATUS_DRAFT:
        return {'current_step': 1, 'step_name': 'Prepare Request', 'status': 'active'}
    elif status_code in [STATUS_AWAITING_APPROVAL, STATUS_SUBMITTED]:
        return {'current_step': 2, 'step_name': 'Submitted to ODPEM', 'status': 'active'}
    elif status_code == STATUS_PART_FILLED:
        return {'current_step': 3, 'step_name': 'ODPEM Processing', 'status': 'active'}
    elif status_code == STATUS_CLOSED:
        return {'current_step': 4, 'step_name': 'Goods Dispatched', 'status': 'active'}
    elif status_code == STATUS_FILLED:
        return {'current_step': 5, 'step_name': 'Goods Received', 'status': 'completed'}
    elif status_code in [STATUS_CANCELLED, STATUS_DENIED, STATUS_INELIGIBLE]:
        # Terminal states where the request will not proceed further
        return {'current_step': 2, 'step_name': 'Request Closed', 'status': 'terminated'}
    else:
        return {'current_step': 1, 'step_name': 'Unknown', 'status': 'active'}


def create_draft_request(agency_id: int, urgency_ind: str, eligible_event_id: Optional[int],
                         rqst_notes_text: Optional[str], user_email: str) -> ReliefRqst:
    """
    Create a new draft relief request for an agency.
    
    Args:
        agency_id: ID of the requesting agency
        urgency_ind: H/M/L/C urgency indicator
        eligible_event_id: Optional associated event ID
        rqst_notes_text: Overall request notes
        user_email: Email of creating user for audit trail
        
    Returns:
        Newly created ReliefRqst instance
        
    Raises:
        ValueError: If the agency, eligible event, or user cannot be found or provided values are invalid
    """
    # Validate urgency indicator
    if urgency_ind not in [URGENCY_HIGH, URGENCY_MEDIUM, URGENCY_LOW, URGENCY_CRITICAL]:
        raise ValueError("Invalid urgency indicator. Must be one of H, M, L, or C.")
    
    # Validate agency exists
    agency = Agency.query.get(agency_id)
    if not agency:
        raise ValueError(f"Agency with id {agency_id} not found")
    
    # Validate eligible event if provided
    if eligible_event_id is not None:
        event = Event.query.get(eligible_event_id)
        if not event:
            raise ValueError(f"Eligible event with id {eligible_event_id} not found")
    
    from app.utils.timezone import today as jamaica_today
    
    relief_request = ReliefRqst()
    relief_request.agency_id = agency_id
    relief_request.request_date = jamaica_today()
    relief_request.urgency_ind = urgency_ind
    relief_request.eligible_event_id = eligible_event_id
    relief_request.rqst_notes_text = rqst_notes_text
    relief_request.status_code = STATUS_DRAFT
    relief_request.version_nbr = 1
    
    # Audit fields - get user by email to retrieve user_name
    user = User.query.filter_by(email=user_email).first()
    if not user:
        db.session.rollback()
        raise ValueError(f"User with email {user_email} not found")
    
    relief_request.create_by_id = user.user_name
    relief_request.create_dtime = jamaica_now()
    
    db.session.add(relief_request)
    db.session.flush()
    
    return relief_request


def add_or_update_request_item(reliefrqst_id: int, item_id: int, request_qty: Decimal,
                                urgency_ind: str, rqst_reason_desc: Optional[str],
                                required_by_date: Optional[date], user_email: str,
                                current_version: Optional[int] = None) -> ReliefRqstItem:
    """
    Add or update an item on a draft relief request.
    Enforces optimistic locking if updating existing item.
    
    Args:
        reliefrqst_id: Relief request ID
        item_id: Item ID from catalog
        request_qty: Requested quantity
        urgency_ind: Item-level urgency (H/M/L/C)
        rqst_reason_desc: Justification for requesting this item (required for High urgency)
        required_by_date: Date when item must be delivered (YYYY-MM-DD format)
        user_email: User performing the action
        current_version: Current version number for optimistic locking (if updating)
        
    Returns:
        ReliefRqstItem instance
        
    Raises:
        OptimisticLockError: If version mismatch on update
        ValueError: If quantity or urgency indicators are invalid
    """
    # Validate inputs
    if request_qty <= 0:
        raise ValueError("Requested quantity must be greater than zero")
    
    if urgency_ind not in [URGENCY_HIGH, URGENCY_MEDIUM, URGENCY_LOW, URGENCY_CRITICAL]:
        raise ValueError("Invalid item urgency indicator. Must be H, M, L, or C")
    
    # Check if item already exists
    existing_item = ReliefRqstItem.query.filter_by(
        reliefrqst_id=reliefrqst_id,
        item_id=item_id
    ).first()
    
    if existing_item:
        # Update existing item with optimistic locking
        if current_version is not None and existing_item.version_nbr != current_version:
            raise OptimisticLockError(
                f"Item {item_id} was modified by another user. Please refresh and try again."
            )
        
        existing_item.request_qty = request_qty
        existing_item.urgency_ind = urgency_ind
        existing_item.rqst_reason_desc = rqst_reason_desc
        existing_item.required_by_date = required_by_date
        existing_item.version_nbr += 1
        
        return existing_item
    else:
        # Create new item
        request_item = ReliefRqstItem()
        request_item.reliefrqst_id = reliefrqst_id
        request_item.item_id = item_id
        request_item.request_qty = request_qty
        request_item.issue_qty = Decimal('0.00')  # Initially 0, filled by ODPEM
        request_item.urgency_ind = urgency_ind
        request_item.rqst_reason_desc = rqst_reason_desc
        request_item.required_by_date = required_by_date
        request_item.status_code = ITEM_STATUS_REQUESTED  # Requested (default 'R')
        request_item.version_nbr = 1
        
        db.session.add(request_item)
        return request_item


def submit_request(reliefrqst_id: int, current_version: int, user_email: str) -> Tuple[bool, str]:
    """
    Submit a draft relief request to ODPEM for processing.
    Enforces optimistic locking and creates notifications.
    
    Args:
        reliefrqst_id: Relief request ID
        current_version: Current version number for optimistic locking
        user_email: User performing the submission
        
    Returns:
        Tuple of (success: bool, message: str)
        
    Raises:
        OptimisticLockError: If version mismatch
    """
    relief_request = ReliefRqst.query.get_or_404(reliefrqst_id)
    
    # Validate status
    if relief_request.status_code != STATUS_DRAFT:
        return False, f"Only draft requests can be submitted. Current status: {relief_request.status_code}"
    
    # Validate at least one item
    if not relief_request.items or len(relief_request.items) == 0:
        return False, "Cannot submit request without any items"
    
    # Check for items with zero quantity
    items_with_qty = [item for item in relief_request.items if item.request_qty > 0]
    if len(items_with_qty) == 0:
        return False, "Cannot submit request without items with quantity > 0"
    
    # Optimistic locking check
    if relief_request.version_nbr != current_version:
        raise OptimisticLockError(
            "This request was modified by another user. Please refresh and try again."
        )
    
    # Update status to AWAITING_APPROVAL (status = 1)
    # Constraint c_reliefrqst_4a allows review_by_id to be null when status < 2
    # ODPEM eligibility review will later move it to SUBMITTED (3) and set review_by_id
    # Review fields (review_by_id/review_dtime) capture ODPEM eligibility decisions
    # Action fields (action_by_id/action_dtime) are reserved for fulfillment (status >= 4)
    relief_request.status_code = STATUS_AWAITING_APPROVAL
    relief_request.version_nbr += 1
    
    db.session.flush()
    
    # Create notifications for ODPEM users (admin users)
    _create_odpem_notifications(relief_request)
    
    # TODO: Send emails to ODPEM distribution list
    
    return True, f"Relief request #{reliefrqst_id} submitted successfully"


def _create_odpem_notifications(relief_request: ReliefRqst) -> None:
    """Create in-app notifications for ODPEM staff about new request submission"""
    from app.services.notification_service import NotificationService
    
    # Get all ODPEM director users (roles: ODPEM_DIR_PEOD, ODPEM_DDG, ODPEM_DG)
    odpem_director_roles = Role.query.filter(
        Role.code.in_(['ODPEM_DIR_PEOD', 'ODPEM_DDG', 'ODPEM_DG'])
    ).all()
    
    admin_users = []
    for role in odpem_director_roles:
        admin_users.extend([u for u in role.users if u.is_active])
    
    # Use centralized notification service with proper deep-linking
    NotificationService.create_relief_request_submitted_notification(
        relief_request=relief_request,
        recipient_users=admin_users
    )


def create_dispatch_notifications(relief_request: ReliefRqst) -> None:
    """
    Create in-app and email notifications when goods are dispatched for a request.
    Called when status transitions to DISPATCHED (70).
    
    Args:
        relief_request: The ReliefRqst that has been dispatched
    """
    # Get all active users for the requesting agency
    agency_users = User.query.filter_by(
        agency_id=relief_request.agency_id,
        is_active=True
    ).all()
    
    event_name = relief_request.eligible_event.event_name if relief_request.eligible_event else "N/A"
    dispatch_date = jamaica_now().strftime('%Y-%m-%d')
    
    for user in agency_users:
        # Create in-app notification
        notification = Notification(
            user_id=user.user_id,
            reliefrqst_id=relief_request.reliefrqst_id,
            title='Relief Goods Dispatched by ODPEM',
            message=f'ODPEM has dispatched goods for relief request #{relief_request.reliefrqst_id} (Event: {event_name}). Please confirm receipt when delivered.',
            type='reliefrqst_dispatch',
            status='unread',
            link_url=url_for('requests.view_request', request_id=relief_request.reliefrqst_id, _external=False),
            is_archived=False
        )
        db.session.add(notification)
        
        # TODO: Send email notification
        # send_email(
        #     to=user.email,
        #     subject='DRIMS – Goods dispatched for your relief request',
        #     body=f'Dear {user.first_name},\n\n'
        #          f'ODPEM has dispatched goods for your relief request #{relief_request.reliefrqst_id}.\n'
        #          f'Event: {event_name}\n'
        #          f'Dispatch Date: {dispatch_date}\n\n'
        #          f'Please confirm receipt when the goods are delivered.\n\n'
        #          f'View request: {url_for("requests.view_request", request_id=relief_request.reliefrqst_id, _external=True)}'
        # )


def check_and_autoclose_request(reliefrqst_id: int) -> Tuple[bool, str]:
    """
    Check if all allocated goods for a request have been received and auto-close if satisfied.
    Called after each dbintake update.
    
    Logic:
    - For each reliefrqst_item, compare total received usable_qty vs issue_qty
    - Request is fully received when all items are satisfied AND no pending packages
    - Update status to DELIVERED (80) when conditions are met
    
    Args:
        reliefrqst_id: Relief request ID to check
        
    Returns:
        Tuple of (closed: bool, message: str)
    """
    relief_request = ReliefRqst.query.get(reliefrqst_id)
    if not relief_request:
        return False, "Request not found"
    
    # Skip if already closed
    if relief_request.status_code == STATUS_FILLED:
        return False, "Request already closed"
    
    # Check for pending packages (status P or D)
    pending_packages = ReliefPkg.query.filter_by(reliefrqst_id=reliefrqst_id).filter(
        ReliefPkg.status_code.in_(['P', 'D'])
    ).count()
    
    if pending_packages > 0:
        return False, f"{pending_packages} package(s) still pending dispatch/receipt"
    
    # Check each item to see if received quantity >= issued quantity
    all_items_satisfied = True
    for req_item in relief_request.items:
        issued_qty = req_item.issue_qty or Decimal('0.00')
        
        # Calculate total received usable quantity for this item across all packages
        received_qty = db.session.query(db.func.sum(DBIntakeItem.usable_qty)).join(
            DBIntake
        ).join(
            ReliefPkg
        ).filter(
            ReliefPkg.reliefrqst_id == reliefrqst_id,
            DBIntakeItem.item_id == req_item.item_id
        ).scalar() or Decimal('0.00')
        
        if received_qty < issued_qty:
            all_items_satisfied = False
            break
    
    if not all_items_satisfied:
        return False, "Not all items have been fully received"
    
    # All conditions met - auto-close the request
    relief_request.status_code = STATUS_FILLED
    relief_request.version_nbr += 1
    
    db.session.flush()
    
    # Create notification for agency confirming closure
    _create_closure_notification(relief_request)
    
    return True, f"Relief request #{reliefrqst_id} automatically closed - all goods received"


def _create_closure_notification(relief_request: ReliefRqst) -> None:
    """Create notification for agency when request is auto-closed"""
    agency_users = User.query.filter_by(
        agency_id=relief_request.agency_id,
        is_active=True
    ).all()
    
    for user in agency_users:
        notification = Notification(
            user_id=user.user_id,
            reliefrqst_id=relief_request.reliefrqst_id,
            title='Relief Request Fully Received and Closed',
            message=f'Relief request #{relief_request.reliefrqst_id} has been fully received and automatically closed. All allocated goods have been confirmed.',
            type='reliefrqst_closed',
            status='unread',
            link_url=url_for('requests.view_request', request_id=relief_request.reliefrqst_id, _external=False),
            is_archived=False
        )
        db.session.add(notification)


def delete_request_item(reliefrqst_id: int, item_id: int) -> Tuple[bool, str]:
    """
    Delete an item from a draft relief request.
    
    Args:
        reliefrqst_id: Relief request ID
        item_id: Item ID to remove
        
    Returns:
        Tuple of (success: bool, message: str)
    """
    # Verify request is in draft status
    relief_request = ReliefRqst.query.get(reliefrqst_id)
    if not relief_request:
        return False, "Request not found"
    
    if relief_request.status_code != STATUS_DRAFT:
        return False, "Can only delete items from draft requests"
    
    # Find and delete the item
    request_item = ReliefRqstItem.query.filter_by(
        reliefrqst_id=reliefrqst_id,
        item_id=item_id
    ).first()
    
    if not request_item:
        return False, "Item not found in request"
    
    db.session.delete(request_item)
    return True, "Item removed successfully"


# ============================================================================
# ELIGIBILITY APPROVAL WORKFLOW
# ============================================================================

def get_pending_eligibility_requests() -> List[ReliefRqst]:
    """
    Get all relief requests pending eligibility review.
    Returns requests that are AWAITING_APPROVAL (status_code=1) without eligibility decision.
    
    Returns:
        List of ReliefRqst instances pending eligibility review
    """
    # A request is pending eligibility if it's AWAITING_APPROVAL and review_by_id is NULL
    return ReliefRqst.query.filter_by(
        status_code=STATUS_AWAITING_APPROVAL
    ).filter(
        ReliefRqst.review_by_id.is_(None)
    ).order_by(
        ReliefRqst.request_date.asc(),
        ReliefRqst.urgency_ind.desc()
    ).all()


def get_request_eligibility_details(reliefrqst_id: int) -> Optional[Dict]:
    """
    Get full details of a relief request for eligibility review.
    
    Args:
        reliefrqst_id: Relief request ID
        
    Returns:
        Dict with request details, items, and eligibility decision status
    """
    relief_request = ReliefRqst.query.get(reliefrqst_id)
    if not relief_request:
        return None
    
    # Check if eligibility decision has been made
    # Decision made if review_by_id is set OR status is INELIGIBLE/DENIED
    decision_made = (
        relief_request.review_by_id is not None or
        relief_request.status_code in [STATUS_INELIGIBLE, STATUS_DENIED]
    )
    
    return {
        'request': relief_request,
        'items': relief_request.items,
        'decision_made': decision_made,
        'can_edit': not decision_made and relief_request.status_code == STATUS_AWAITING_APPROVAL
    }


def submit_eligibility_decision(reliefrqst_id: int, decision: str, reason: Optional[str],
                                reviewer_email: str) -> Tuple[bool, str]:
    """
    Submit eligibility decision for a relief request.
    
    Args:
        reliefrqst_id: Relief request ID
        decision: 'Y' for eligible, 'N' for ineligible
        reason: Reason for ineligibility (required if decision='N')
        reviewer_email: Email of the reviewing director
        
    Returns:
        Tuple of (success: bool, message: str)
    """
    relief_request = ReliefRqst.query.get_or_404(reliefrqst_id)
    
    # Validate status - must be AWAITING_APPROVAL
    if relief_request.status_code != STATUS_AWAITING_APPROVAL:
        return False, f"Cannot review request with status {relief_request.status_code}. Must be AWAITING_APPROVAL."
    
    # Check if decision already made
    if relief_request.review_by_id is not None:
        return False, "Eligibility decision has already been recorded for this request."
    
    # Validate decision
    if decision not in ['Y', 'N']:
        return False, "Decision must be 'Y' (eligible) or 'N' (ineligible)."
    
    # Validate reason for ineligible decision
    if decision == 'N' and (not reason or not reason.strip()):
        return False, "Reason is required when marking a request as ineligible."
    
    # Get the reviewer user object
    reviewer = User.query.filter_by(email=reviewer_email).first()
    if not reviewer:
        return False, f"Reviewer with email {reviewer_email} not found."
    
    # Record the decision using user_name field
    relief_request.review_by_id = reviewer.user_name
    relief_request.review_dtime = jamaica_now()
    
    if decision == 'N':
        # Mark as INELIGIBLE and set review fields
        # Constraint c_reliefrqst_5a requires action_by_id when status_code >= 4
        # Constraint c_reliefrqst_5b requires action_dtime when action_by_id is set
        relief_request.status_code = STATUS_INELIGIBLE
        relief_request.status_reason_desc = reason.strip() if reason else None
        relief_request.action_by_id = reviewer.user_name
        relief_request.action_dtime = jamaica_now()
        relief_request.version_nbr += 1
        
        db.session.flush()
        
        # Notify the requester (agency)
        _create_ineligible_notification(relief_request, reason.strip() if reason else '')
        
        return True, f"Request #{reliefrqst_id} marked as INELIGIBLE. Requester has been notified."
    
    else:  # decision == 'Y'
        # Mark as SUBMITTED (eligible) and set review fields
        relief_request.status_code = STATUS_SUBMITTED
        relief_request.version_nbr += 1
        
        db.session.flush()
        
        # Notify logistics team (LO and LM) that request is eligible and ready for fulfillment
        approver_name = f"{reviewer.first_name} {reviewer.last_name}" if reviewer and reviewer.first_name else "ODPEM Director"
        _create_eligible_notification(relief_request, approver_name)
        
        return True, f"Request #{reliefrqst_id} marked as ELIGIBLE. Logistics team has been notified."


def _create_ineligible_notification(relief_request: ReliefRqst, reason: str) -> None:
    """Create notifications for agency users when request is marked ineligible"""
    agency_users = User.query.filter_by(
        agency_id=relief_request.agency_id,
        is_active=True
    ).all()
    
    event_name = relief_request.eligible_event.event_name if relief_request.eligible_event else "N/A"
    tracking_no = relief_request.tracking_no if hasattr(relief_request, 'tracking_no') else str(relief_request.reliefrqst_id)
    
    for user in agency_users:
        notification = Notification(
            user_id=user.user_id,
            reliefrqst_id=relief_request.reliefrqst_id,
            title='Relief Request Marked Ineligible',
            message=f'Your relief request {tracking_no} (Event: {event_name}) has been marked ineligible. Reason: {reason}',
            type='reliefrqst_ineligible',
            status='unread',
            link_url=url_for('requests.view_request', request_id=relief_request.reliefrqst_id, _external=False),
            is_archived=False
        )
        db.session.add(notification)
        
        # TODO: Send email notification
        # send_email(
        #     to=user.email,
        #     subject=f'DRIMS – Relief Request {tracking_no} Marked Ineligible',
        #     body=f'Dear {user.first_name or user.email},\n\n'
        #          f'Your relief request {tracking_no} for event "{event_name}" has been reviewed '
        #          f'and marked as INELIGIBLE by ODPEM.\n\n'
        #          f'Reason: {reason}\n\n'
        #          f'If you have questions, please contact ODPEM.\n\n'
        #          f'View request: {url_for("requests.view_request", request_id=relief_request.reliefrqst_id, _external=True)}'
        # )


def _create_eligible_notification(relief_request: ReliefRqst, approver_name: str) -> None:
    """Create notifications for logistics team when request is marked eligible"""
    from app.db.models import Role
    from app.services.notification_service import NotificationService
    
    # Get all users with Logistics Officer or Logistics Manager roles
    logistics_roles = Role.query.filter(
        Role.code.in_(['LOGISTICS_OFFICER', 'LOGISTICS_MANAGER'])
    ).all()
    
    logistics_users = []
    for role in logistics_roles:
        logistics_users.extend([user for user in role.users if user.is_active])
    
    # Remove duplicates
    logistics_users = list({user.user_id: user for user in logistics_users}.values())
    
    # Use centralized notification service with deep-linking to package preparation
    NotificationService.create_relief_request_approved_notification(
        relief_request=relief_request,
        recipient_users=logistics_users,
        approver_name=approver_name
    )


def can_process_request(reliefrqst_id: int) -> Tuple[bool, str]:
    """
    Check if a relief request can be processed for fulfillment/dispatch.
    Blocks processing of ineligible requests.
    
    Args:
        reliefrqst_id: Relief request ID
        
    Returns:
        Tuple of (can_process: bool, message: str)
    """
    relief_request = ReliefRqst.query.get(reliefrqst_id)
    if not relief_request:
        return False, "Request not found"
    
    if relief_request.status_code == STATUS_INELIGIBLE:
        return False, "This relief request is marked ineligible and cannot be processed."
    
    if relief_request.status_code in [STATUS_CANCELLED, STATUS_DENIED]:
        return False, f"This relief request has been {relief_request.status_code} and cannot be processed."
    
    return True, "Request can be processed"
