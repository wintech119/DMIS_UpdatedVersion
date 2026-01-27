"""
Agency Relief Request Management (AIDMGMT Workflow)
Allows agency users to prepare and submit relief requests for disaster response.
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, abort, current_app
from flask_login import login_required, current_user
from datetime import datetime, date
from decimal import Decimal
from sqlalchemy.exc import SQLAlchemyError

from app.db import db
from app.db.models import ReliefRqst, ReliefRqstItem, Agency, Item, Event, UnitOfMeasure, ItemCategory
from app.core.rbac import agency_user_required, is_admin, is_logistics_manager, is_logistics_officer, can_access_relief_request, is_director_level
from app.core.decorators import feature_required
from app.core.exceptions import OptimisticLockError
from app.core import session_utils
from app.services import relief_request_service as rr_service

requests_bp = Blueprint('requests', __name__, url_prefix='/relief-requests')


@requests_bp.route('/<int:reliefrqst_id>/prepare-package')
@login_required
def prepare_package_alias(reliefrqst_id):
    """Friendly alias route that redirects to the modern packaging workflow"""
    return redirect(url_for('packaging.prepare_package', reliefrqst_id=reliefrqst_id))


@requests_bp.route('/')
@login_required
def list_requests():
    """
    List relief requests.
    - Agency users see their own agency's requests
    - Logistics users see all requests
    """
    from app.security.param_validation import validate_filter_value
    
    # Support both 'filter' and 'status' params for backward compatibility
    # Validate against allowed filter values
    ALLOWED_FILTERS = {'submitted', 'draft', 'awaiting', 'processing', 'dispatched', 'completed', 'all'}
    raw_filter = request.args.get('filter') or request.args.get('status', 'submitted')
    status_filter = validate_filter_value(raw_filter, ALLOWED_FILTERS, default='submitted')
    
    # Check if user is in read-only mode (director-level executives)
    is_read_only = is_director_level()
    
    # Get validated agency_id from session
    user_agency_id = session_utils.get_agency_id()
    
    # Base query with eager loading
    if is_logistics_manager() or is_logistics_officer() or is_director_level():
        # Logistics users and director-level executives see all requests
        base_query = ReliefRqst.query.options(
            db.joinedload(ReliefRqst.agency),
            db.joinedload(ReliefRqst.items).joinedload(ReliefRqstItem.item).joinedload(Item.default_uom),
            db.joinedload(ReliefRqst.items).joinedload(ReliefRqstItem.item).joinedload(Item.category)
        )
    elif user_agency_id:
        # Agency users see only their agency's requests
        base_query = ReliefRqst.query.filter_by(agency_id=user_agency_id).options(
            db.joinedload(ReliefRqst.agency),
            db.joinedload(ReliefRqst.items).joinedload(ReliefRqstItem.item).joinedload(Item.default_uom),
            db.joinedload(ReliefRqst.items).joinedload(ReliefRqstItem.item).joinedload(Item.category)
        )
    else:
        # User has no agency and no logistics role - should not happen
        flash('You do not have permission to view relief requests.', 'danger')
        abort(403)
    
    # Calculate counts for filter tabs - each count uses the EXACT same logic as its corresponding filter
    counts = {
        'submitted': base_query.filter(ReliefRqst.status_code.in_([
            rr_service.STATUS_SUBMITTED, rr_service.STATUS_PART_FILLED
        ])).count(),
        'draft': base_query.filter_by(status_code=rr_service.STATUS_DRAFT).count(),
        'awaiting': base_query.filter_by(status_code=rr_service.STATUS_AWAITING_APPROVAL).count(),
        'completed': base_query.filter_by(status_code=rr_service.STATUS_FILLED).count(),
        'processing': base_query.filter(ReliefRqst.status_code.in_([
            rr_service.STATUS_AWAITING_APPROVAL, rr_service.STATUS_PART_FILLED
        ])).count(),  # Legacy filter count
        'dispatched': base_query.filter_by(status_code=rr_service.STATUS_CLOSED).count(),  # Legacy filter count
        'all': base_query.count()  # Total count of all requests visible to user
    }
    
    # Apply status filter with full backward compatibility
    if status_filter == 'draft':
        query = base_query.filter_by(status_code=rr_service.STATUS_DRAFT)
    elif status_filter == 'awaiting':
        query = base_query.filter_by(status_code=rr_service.STATUS_AWAITING_APPROVAL)
    elif status_filter == 'processing':
        # Legacy: processing includes both awaiting-approval and part-filled
        query = base_query.filter(ReliefRqst.status_code.in_([
            rr_service.STATUS_AWAITING_APPROVAL, rr_service.STATUS_PART_FILLED
        ]))
    elif status_filter == 'dispatched':
        # Legacy: dispatched maps to closed/filled
        query = base_query.filter_by(status_code=rr_service.STATUS_CLOSED)
    elif status_filter == 'completed':
        query = base_query.filter_by(status_code=rr_service.STATUS_FILLED)
    elif status_filter == 'all':
        query = base_query  # Show all requests
    else:
        # Default to submitted/part-filled
        query = base_query.filter(ReliefRqst.status_code.in_([
            rr_service.STATUS_SUBMITTED, rr_service.STATUS_PART_FILLED
        ]))
    
    requests_list = query.order_by(ReliefRqst.request_date.desc()).all()
    
    return render_template('relief_requests/list.html',
                         requests=requests_list,
                         current_filter=status_filter,
                         counts=counts,
                         is_read_only=is_read_only,
                         STATUS_DRAFT=rr_service.STATUS_DRAFT,
                         STATUS_SUBMITTED=rr_service.STATUS_SUBMITTED,
                         STATUS_CLOSED=rr_service.STATUS_CLOSED,
                         STATUS_FILLED=rr_service.STATUS_FILLED)


@requests_bp.route('/create', methods=['GET', 'POST'])
@login_required
@feature_required('relief_request_creation')
def create_request():
    """Create new draft relief request for current user's agency or redirect Logistics users"""
    # Get validated session data
    user_agency_id = session_utils.get_agency_id()
    user_email = session_utils.get_email()
    
    # Redirect Logistics personnel (without agency) to the "create on behalf" route
    # Allow dual-role users with agency_id to use the normal flow for their own agency
    if (is_logistics_manager() or is_logistics_officer()) and not user_agency_id:
        return redirect(url_for('packaging.create_request_on_behalf'))
    
    # Verify user has agency_id for this route
    if not user_agency_id:
        flash('You must be associated with an agency to use this form. Use "Create on Behalf" instead.', 'warning')
        return redirect(url_for('packaging.create_request_on_behalf'))
    
    if request.method == 'POST':
        try:
            urgency_ind = request.form.get('urgency_ind', 'M')
            eligible_event_id = request.form.get('eligible_event_id')
            eligible_event_id = int(eligible_event_id) if eligible_event_id else None
            rqst_notes_text = request.form.get('rqst_notes_text', '').strip()
            
            # Validate urgency
            if urgency_ind not in ['H', 'M', 'L']:
                flash('Invalid urgency level', 'danger')
                return redirect(url_for('requests.create_request'))
            
            # Create draft request
            relief_request = rr_service.create_draft_request(
                agency_id=user_agency_id,
                urgency_ind=urgency_ind,
                eligible_event_id=eligible_event_id,
                rqst_notes_text=rqst_notes_text,
                user_email=user_email
            )
            
            db.session.commit()
            
            flash(f'Draft relief request #{relief_request.reliefrqst_id} created successfully. Add items to continue.', 'success')
            return redirect(url_for('requests.edit_items', request_id=relief_request.reliefrqst_id))
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('Error creating relief request')
            flash('An error occurred while creating the request. Please try again.', 'danger')
            return redirect(url_for('requests.create_request'))
    
    # GET request - show form
    events = Event.query.filter_by(status_code='A').order_by(Event.start_date.desc()).all()
    
    return render_template('requests/create.html',
                         events=events,
                         today=date.today().isoformat())


@requests_bp.route('/<int:request_id>')
@login_required
def view_request(request_id):
    """View relief request details"""
    relief_request = ReliefRqst.query.options(
        db.joinedload(ReliefRqst.agency),
        db.joinedload(ReliefRqst.items).joinedload(ReliefRqstItem.item).joinedload(Item.default_uom),
        db.joinedload(ReliefRqst.items).joinedload(ReliefRqstItem.item).joinedload(Item.category)
    ).get(request_id)
    
    if not relief_request:
        abort(404)
    
    # Verify user has access to this request
    if not can_access_relief_request(relief_request):
        flash('You do not have permission to view this request.', 'danger')
        abort(403)
    
    # Calculate metrics for summary cards (using Decimal for consistency)
    from decimal import Decimal
    total_requested = sum(item.request_qty for item in relief_request.items) if relief_request.items else Decimal(0)
    fulfilled_count = sum(item.issue_qty or Decimal(0) for item in relief_request.items) if relief_request.items else Decimal(0)
    shortfall_count = max(Decimal(0), total_requested - fulfilled_count)  # Prevent negative values
    fulfillment_rate = int((float(fulfilled_count) / float(total_requested) * 100) if total_requested > 0 else 0)
    
    # Get dispatch and receive dates from packages (if any)
    dispatch_date = None
    receive_date = None
    confirmed_by = None
    confirmed_agency = None
    
    # Build timeline events
    timeline_events = []
    if relief_request.create_dtime:
        timeline_events.append({
            'icon': 'file-earmark-text',
            'title': 'Request Created',
            'description': f'Draft created by {relief_request.agency.agency_name}',
            'timestamp': relief_request.create_dtime,
            'variant': 'default'
        })
    
    if relief_request.request_date and relief_request.status_code >= rr_service.STATUS_AWAITING_APPROVAL:
        timeline_events.append({
            'icon': 'send',
            'title': 'Submitted to ODPEM',
            'description': 'Request submitted for review',
            'timestamp': relief_request.request_date,
            'variant': 'primary'
        })
    
    if relief_request.status_code >= rr_service.STATUS_SUBMITTED:
        timeline_events.append({
            'icon': 'check-circle',
            'title': 'Approved',
            'description': 'Request approved for fulfillment',
            'timestamp': relief_request.review_dtime,
            'variant': 'success'
        })
    
    # Check if user is in read-only mode (director-level executives)
    is_read_only = is_director_level()
    
    return render_template('relief_requests/details.html',
                         request=relief_request,
                         total_requested=total_requested,
                         fulfilled_count=fulfilled_count,
                         shortfall_count=shortfall_count,
                         fulfillment_rate=fulfillment_rate,
                         dispatch_date=dispatch_date,
                         receive_date=receive_date,
                         confirmed_by=confirmed_by,
                         confirmed_agency=confirmed_agency,
                         timeline_events=timeline_events,
                         is_read_only=is_read_only)


@requests_bp.route('/<int:request_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_request(request_id):
    """Edit relief request header (only for drafts)"""
    relief_request = ReliefRqst.query.options(
        db.joinedload(ReliefRqst.agency),
        db.joinedload(ReliefRqst.items).joinedload(ReliefRqstItem.item).joinedload(Item.default_uom),
        db.joinedload(ReliefRqst.items).joinedload(ReliefRqstItem.item).joinedload(Item.category)
    ).get(request_id)
    
    if not relief_request:
        abort(404)
    
    # Verify user has access to this request
    if not can_access_relief_request(relief_request):
        flash('You do not have permission to edit this request.', 'danger')
        abort(403)
    
    # Can only edit drafts
    if relief_request.status_code != rr_service.STATUS_DRAFT:
        flash('Only draft requests can be edited.', 'warning')
        return redirect(url_for('requests.view_request', request_id=request_id))
    
    # Calculate metrics for summary cards
    if relief_request.items:
        allocated_count = sum(1 for item in relief_request.items if item.issue_qty and item.issue_qty >= item.request_qty)
        partial_count = sum(1 for item in relief_request.items if item.issue_qty and 0 < item.issue_qty < item.request_qty)
        unallocated_count = sum(1 for item in relief_request.items if not item.issue_qty or item.issue_qty == 0)
    else:
        allocated_count = partial_count = unallocated_count = 0
    
    if request.method == 'POST':
        try:
            version_str = request.form.get('version_nbr')
            current_version = int(version_str) if version_str else relief_request.version_nbr
            
            # Optimistic locking check
            if relief_request.version_nbr != current_version:
                raise OptimisticLockError(record_id=request_id, message='This request was modified by another user. Please refresh.')
            
            # Update fields
            relief_request.urgency_ind = request.form.get('urgency_ind', 'M')
            eligible_event_id = request.form.get('eligible_event_id')
            relief_request.eligible_event_id = int(eligible_event_id) if eligible_event_id else None
            relief_request.rqst_notes_text = request.form.get('rqst_notes_text', '').strip()
            relief_request.version_nbr += 1
            
            db.session.commit()
            
            flash('Request updated successfully', 'success')
            return redirect(url_for('requests.view_request', request_id=request_id))
            
        except OptimisticLockError as e:
            db.session.rollback()
            flash(str(e), 'danger')
            return redirect(url_for('requests.edit_request', request_id=request_id))
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('Error updating relief request')
            flash('An error occurred while updating the request. Please try again.', 'danger')
    
    events = Event.query.filter_by(status_code='A').order_by(Event.start_date.desc()).all()
    
    return render_template('relief_requests/edit.html',
                         request=relief_request,
                         events=events,
                         allocated_count=allocated_count,
                         partial_count=partial_count,
                         unallocated_count=unallocated_count)


@requests_bp.route('/<int:request_id>/items', methods=['GET'])
@login_required
def get_items(request_id):
    """API endpoint: Get all items for a request"""
    relief_request = ReliefRqst.query.get_or_404(request_id)
    
    # Verify user has access to this request
    if not can_access_relief_request(relief_request):
        return jsonify({'error': 'Unauthorized'}), 403
    
    items_data = []
    for req_item in relief_request.items:
        items_data.append({
            'item_id': req_item.item_id,
            'item_name': req_item.item.item_name,
            'sku_code': req_item.item.sku_code,
            'category': req_item.item.category.category_desc if req_item.item.category else '',
            'request_qty': float(req_item.request_qty),
            'issue_qty': float(req_item.issue_qty),
            'urgency_ind': req_item.urgency_ind,
            'rqst_reason_desc': req_item.rqst_reason_desc or '',
            'status_code': req_item.status_code,
            'version_nbr': req_item.version_nbr
        })
    
    return jsonify({'items': items_data})


@requests_bp.route('/<int:request_id>/items/edit', methods=['GET', 'POST'])
@login_required
def edit_items(request_id):
    """Add/edit items on a draft relief request"""
    relief_request = ReliefRqst.query.get_or_404(request_id)
    
    # Verify user has access to this request
    if not can_access_relief_request(relief_request):
        flash('You do not have permission to edit this request.', 'danger')
        abort(403)
    
    # Can only edit items on drafts
    if relief_request.status_code != rr_service.STATUS_DRAFT:
        flash('Items can only be edited on draft requests.', 'warning')
        return redirect(url_for('requests.view_request', request_id=request_id))
    
    if request.method == 'POST':
        try:
            from app.security.param_validation import safe_id, safe_quantity, validate_filter_value
            
            item_id = safe_id(request.form.get('item_id'))
            if item_id <= 0:
                flash('Invalid item ID', 'danger')
                return redirect(url_for('requests.edit_items', request_id=request_id))
            
            request_qty = safe_quantity(request.form.get('request_qty', '0'))
            # Validate urgency_ind against allowed values
            ALLOWED_URGENCY = {'H', 'M', 'L'}  # High, Medium, Low
            urgency_ind = validate_filter_value(
                request.form.get('urgency_ind', 'M').upper(),
                ALLOWED_URGENCY,
                default='M'
            ).upper()
            rqst_reason_desc = request.form.get('rqst_reason_desc', '').strip()
            required_by_date_str = request.form.get('required_by_date', '').strip()
            
            # Parse required_by_date (YYYY-MM-DD format)
            required_by_date = None
            if required_by_date_str:
                try:
                    required_by_date = datetime.strptime(required_by_date_str, '%Y-%m-%d').date()
                except ValueError:
                    flash('Invalid date format. Please use YYYY-MM-DD format.', 'danger')
                    return redirect(url_for('requests.edit_items', request_id=request_id))
            
            # Validate item is active and is a GOODS item (not FUNDS)
            item = Item.query.options(
                db.joinedload(Item.category)
            ).get_or_404(item_id)
            if item.status_code != 'A':
                flash('Cannot add inactive items to request', 'danger')
                return redirect(url_for('requests.edit_items', request_id=request_id))
            
            # Server-side validation: Only GOODS items allowed in relief requests
            if item.category and item.category.category_type != 'GOODS':
                flash('Only GOODS items can be added to relief requests. FUNDS items are not allowed.', 'danger')
                return redirect(url_for('requests.edit_items', request_id=request_id))
            
            if request_qty <= 0:
                flash('Quantity must be greater than zero', 'danger')
                return redirect(url_for('requests.edit_items', request_id=request_id))
            
            # Validate required_by_date and justification based on urgency
            if urgency_ind == 'H':
                if not required_by_date:
                    flash('High priority items require a "Required By Date"', 'danger')
                    return redirect(url_for('requests.edit_items', request_id=request_id))
                if not rqst_reason_desc:
                    flash('High priority items require a justification', 'danger')
                    return redirect(url_for('requests.edit_items', request_id=request_id))
            
            # Add or update item
            rr_service.add_or_update_request_item(
                reliefrqst_id=request_id,
                item_id=item_id,
                request_qty=request_qty,
                urgency_ind=urgency_ind,
                rqst_reason_desc=rqst_reason_desc,
                required_by_date=required_by_date,
                user_email=session_utils.get_email()
            )
            
            db.session.commit()
            
            flash(f'Item "{item.item_name}" added successfully', 'success')
            return redirect(url_for('requests.edit_items', request_id=request_id))
            
        except OptimisticLockError as e:
            db.session.rollback()
            flash(str(e), 'danger')
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('Error adding item to relief request')
            flash('An error occurred while adding the item. Please try again.', 'danger')
    
    # GET request - show items and add form
    # Only show GOODS items for relief requests (exclude FUNDS items)
    active_items = Item.query.join(
        ItemCategory, Item.category_id == ItemCategory.category_id
    ).filter(
        Item.status_code == 'A',
        ItemCategory.category_type == 'GOODS'
    ).order_by(Item.item_name).all()
    
    return render_template('requests/edit_items.html',
                         request=relief_request,
                         active_items=active_items)


@requests_bp.route('/<int:request_id>/items/<int:item_id>/delete', methods=['POST'])
@login_required
def delete_item(request_id, item_id):
    """Delete an item from a draft request"""
    relief_request = ReliefRqst.query.get_or_404(request_id)
    
    # Verify user has access to this request
    if not can_access_relief_request(relief_request):
        return jsonify({'error': 'Unauthorized'}), 403
    
    try:
        success, message = rr_service.delete_request_item(request_id, item_id)
        
        if success:
            db.session.commit()
            flash(message, 'success')
        else:
            flash(message, 'warning')
        
        return redirect(url_for('requests.edit_items', request_id=request_id))
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error deleting item from relief request')
        flash('An error occurred while deleting the item. Please try again.', 'danger')
        return redirect(url_for('requests.edit_items', request_id=request_id))


@requests_bp.route('/<int:request_id>/save_draft', methods=['POST'])
@login_required
def save_draft(request_id):
    """Save current state of draft relief request (allows user to return later)"""
    relief_request = ReliefRqst.query.get_or_404(request_id)
    
    # Verify user has access to this request
    if not can_access_relief_request(relief_request):
        flash('You do not have permission to save this request.', 'danger')
        abort(403)
    
    # Verify it's still a draft
    if relief_request.status_code != rr_service.STATUS_DRAFT:
        flash('Only draft requests can be saved.', 'warning')
        return redirect(url_for('requests.view_request', request_id=request_id))
    
    try:
        # The draft is already saved (items are added/updated via edit_items route)
        # This route just provides feedback to the user that their work is saved
        db.session.commit()
        flash('Draft saved successfully. You can return later to complete this request.', 'success')
        return redirect(url_for('requests.edit_items', request_id=request_id))
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error saving draft relief request')
        flash('An error occurred while saving the draft. Please try again.', 'danger')
        return redirect(url_for('requests.edit_items', request_id=request_id))


@requests_bp.route('/<int:request_id>/cancel', methods=['POST'])
@login_required
def cancel_request(request_id):
    """Cancel and delete a draft relief request"""
    relief_request = ReliefRqst.query.get_or_404(request_id)
    
    # Verify user has access to this request
    if not can_access_relief_request(relief_request):
        flash('You do not have permission to cancel this request.', 'danger')
        abort(403)
    
    # Only allow cancelling draft requests
    if relief_request.status_code != rr_service.STATUS_DRAFT:
        flash('Only draft requests can be cancelled. This request has already been submitted.', 'warning')
        return redirect(url_for('requests.view_request', request_id=request_id))
    
    try:
        # Delete all items first (due to foreign key constraints)
        ReliefRqstItem.query.filter_by(reliefrqst_id=request_id).delete()
        
        # Delete the request
        db.session.delete(relief_request)
        db.session.commit()
        
        flash(f'Draft relief request #{request_id} has been cancelled and deleted.', 'info')
        
        # Redirect based on user type
        if session_utils.get_agency_id():
            # Agency users go to their requests list
            return redirect(url_for('requests.list_requests'))
        else:
            # Logistics users without agency go to packaging fulfillment
            return redirect(url_for('packaging.pending_fulfillment'))
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error cancelling relief request')
        flash('An error occurred while cancelling the request. Please try again.', 'danger')
        return redirect(url_for('requests.view_request', request_id=request_id))


@requests_bp.route('/<int:request_id>/submit', methods=['POST'])
@login_required
def submit_request(request_id):
    """Submit a draft relief request to ODPEM for processing"""
    relief_request = ReliefRqst.query.get_or_404(request_id)
    
    # Verify user has access to this request
    if not can_access_relief_request(relief_request):
        flash('You do not have permission to submit this request.', 'danger')
        abort(403)
    
    try:
        # Get version_nbr from form, with defensive handling
        version_nbr_str = request.form.get('version_nbr')
        if not version_nbr_str:
            # Fallback to current request version if not provided in form
            current_version = relief_request.version_nbr
        else:
            current_version = int(version_nbr_str)
        
        success, message = rr_service.submit_request(
            reliefrqst_id=request_id,
            current_version=current_version,
            user_email=session_utils.get_email()
        )
        
        if success:
            db.session.commit()
            flash(message, 'success')
            return redirect(url_for('requests.view_request', request_id=request_id))
        else:
            # Validation failed - redirect to edit items page so user can add items
            flash(message, 'warning')
            return redirect(url_for('requests.edit_items', request_id=request_id))
        
    except OptimisticLockError as e:
        db.session.rollback()
        flash(str(e), 'danger')
        return redirect(url_for('requests.view_request', request_id=request_id))
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error submitting relief request')
        flash('An error occurred while submitting the request. Please try again.', 'danger')
        return redirect(url_for('requests.view_request', request_id=request_id))
