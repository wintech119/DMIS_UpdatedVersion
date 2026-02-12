"""
Relief Request Packaging Blueprint
Allows Logistics Officers/Managers to prepare relief packages from approved requests
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, abort, current_app
from flask_login import login_required, current_user
from datetime import datetime, date, timedelta
from decimal import Decimal
from sqlalchemy import and_
from sqlalchemy.orm import joinedload
import uuid

from app.db import db
from app.security.log_sanitizer import sanitize_for_log, sanitize_exception_for_log
from app.security.audit_logger import log_data_event, AuditAction, AuditOutcome
from app.security.url_safety import get_safe_redirect_url
from app.utils.timezone import now as jamaica_now
from app.db.models import (
    ReliefRqst, ReliefRqstItem, Item, Warehouse, Inventory, ItemBatch,
    User, Notification,
    ReliefPkg, ReliefPkgItem, ReliefRqstItemStatus
)
from app.core.rbac import has_permission, permission_required
from app.core import session_utils
from app.services import relief_request_service as rr_service
from app.services import item_status_service
from app.services import inventory_reservation_service as reservation_service
from app.services.batch_allocation_service import BatchAllocationService, safe_decimal
from app.core.exceptions import OptimisticLockError


def _validate_version_nbr(entity_name, expected_version, actual_version):
    """
    Validate version_nbr for optimistic locking.
    Raises OptimisticLockError if versions don't match.
    
    Args:
        entity_name: User-friendly name of the entity (e.g., "relief request", "package")
        expected_version: Version sent from UI
        actual_version: Current version in database
    """
    if expected_version is None:
        raise OptimisticLockError(f"Version number is required for {entity_name}")
    
    if int(expected_version) != int(actual_version):
        raise OptimisticLockError(
            f"This {entity_name} has been updated by another user. Please refresh the page and try again."
        )


packaging_bp = Blueprint('packaging', __name__, url_prefix='/packaging')


@packaging_bp.route('/pending-approval')
@login_required
def pending_approval():
    """
    LM approval queue - shows packages submitted by LO awaiting LM approval.
    
    Criteria for "Pending LM Approval":
    - Relief Request status = SUBMITTED or PART_FILLED (allows multi-batch fulfillment)
    - ReliefPkg exists with status_code='P' (Pending - submitted for approval)
    - Not yet dispatched (dispatch_dtime is NULL)
    
    Concurrency control is handled via optimistic locking (version_nbr).
    """
    from app.core.rbac import is_logistics_manager
    if not is_logistics_manager():
        flash('Access denied. Only Logistics Managers can view this page.', 'danger')
        abort(403)
    
    # Find all relief requests with packages awaiting LM approval
    # IMPORTANT: Include both SUBMITTED and PART_FILLED to support multi-batch fulfillment
    # (After first dispatch, status becomes PART_FILLED but may need additional batches)
    all_requests = ReliefRqst.query.options(
        joinedload(ReliefRqst.agency),
        joinedload(ReliefRqst.eligible_event),
        joinedload(ReliefRqst.status),
        joinedload(ReliefRqst.items),
        joinedload(ReliefRqst.packages)
    ).filter(
        ReliefRqst.status_code.in_([rr_service.STATUS_SUBMITTED, rr_service.STATUS_PART_FILLED])
    ).order_by(ReliefRqst.create_dtime.desc()).all()
    
    # Filter to requests with packages pending LM approval
    # Package must have: status='P', verify_by_id!=NULL (submitted, not draft), dispatch_dtime=NULL (not dispatched)
    pending_requests = []
    for req in all_requests:
        # Check if there's a ReliefPkg submitted for approval (verify_by_id is set)
        relief_pkg = next((pkg for pkg in req.packages 
                          if pkg.status_code == rr_service.PKG_STATUS_PENDING 
                          and pkg.verify_by_id is not None  # Only submitted packages (not drafts)
                          and pkg.dispatch_dtime is None), None)
        
        if relief_pkg:
            # Package exists and is submitted for approval (not just a draft)
            pending_requests.append(req)
    
    counts = {
        'pending_approval': len(pending_requests)
    }
    
    return render_template('packaging/pending_approval.html',
                         requests=pending_requests,
                         counts=counts,
                         STATUS_SUBMITTED=rr_service.STATUS_SUBMITTED,
                         STATUS_PART_FILLED=rr_service.STATUS_PART_FILLED,
                         PKG_STATUS_PENDING=rr_service.PKG_STATUS_PENDING)


@packaging_bp.route('/<int:reliefrqst_id>/review-approval', methods=['GET', 'POST'])
@login_required
def review_approval(reliefrqst_id):
    """
    LM reviews LO-submitted package and approves for dispatch.
    GET: Display allocations for review
    POST: Approve and dispatch to inventory clerk
    """
    from app.core.rbac import is_logistics_manager
    if not is_logistics_manager():
        flash('Access denied. Only Logistics Managers can review and approve packages.', 'danger')
        abort(403)
    
    relief_request = ReliefRqst.query.options(
        joinedload(ReliefRqst.agency),
        joinedload(ReliefRqst.eligible_event),
        joinedload(ReliefRqst.status),
        joinedload(ReliefRqst.items).joinedload(ReliefRqstItem.item).joinedload(Item.category),
        joinedload(ReliefRqst.items).joinedload(ReliefRqstItem.item).joinedload(Item.default_uom),
        joinedload(ReliefRqst.packages)
    ).get_or_404(reliefrqst_id)
    
    # Get the pending ReliefPkg
    relief_pkg = next((pkg for pkg in relief_request.packages if pkg.status_code == rr_service.PKG_STATUS_PENDING), None)
    
    if not relief_pkg:
        flash('No pending package found for this relief request.', 'danger')
        return redirect(url_for('packaging.pending_approval'))
    
    if relief_pkg.dispatch_dtime is not None:
        flash('This package has already been dispatched.', 'warning')
        return redirect(url_for('packaging.pending_approval'))
    
    if request.method == 'GET':
        # Load allocations for display
        warehouses = Warehouse.query.filter_by(status_code='A').order_by(Warehouse.warehouse_name).all()
        
        # Build allocation map from ReliefPkgItem
        allocations = {}
        for pkg_item in relief_pkg.items:
            item_id = pkg_item.item_id
            # fr_inventory_id IS the warehouse_id (inventory_id = warehouse_id in schema)
            warehouse_id = pkg_item.fr_inventory_id
            
            if item_id not in allocations:
                allocations[item_id] = {}
            
            allocations[item_id][warehouse_id] = pkg_item.item_qty
        
        return render_template('packaging/review_approval.html',
                             relief_request=relief_request,
                             relief_pkg=relief_pkg,
                             warehouses=warehouses,
                             allocations=allocations)
    
    # POST: Approve and dispatch
    action = request.form.get('action')
    relief_request_version = request.form.get('relief_request_version')
    package_version = request.form.get('package_version')
    
    if action == 'approve_and_dispatch':
        try:
            _validate_version_nbr("relief request", relief_request_version, relief_request.version_nbr)
            _validate_version_nbr("package", package_version, relief_pkg.version_nbr)
            # CRITICAL VALIDATION: Ensure package has items AND issue_qty matches ReliefPkgItem totals
            # Get all ReliefPkgItem records for this package
            pkg_items = ReliefPkgItem.query.filter_by(reliefpkg_id=relief_pkg.reliefpkg_id).all()
            
            if not pkg_items:
                # No items allocated - package is empty
                # Check if all items have valid unavailability statuses (U, D, W)
                unavailability_statuses = {'U', 'D', 'W'}
                all_items_unavailable = all(
                    item.status_code in unavailability_statuses 
                    for item in relief_request.items
                )
                
                if not all_items_unavailable:
                    raise ValueError('Cannot dispatch package: no items have been allocated. All requested items must either have batch allocations or be marked as Unavailable (U), Denied (D), or Awaiting Availability (W).')
            
            # Validate that ReliefPkgItem quantities match issue_qty for data integrity
            # Build totals from ReliefPkgItem records
            pkg_item_totals = {}
            for pkg_item in pkg_items:
                if pkg_item.item_id not in pkg_item_totals:
                    pkg_item_totals[pkg_item.item_id] = Decimal('0')
                pkg_item_totals[pkg_item.item_id] += pkg_item.item_qty
            
            # Verify each item's issue_qty matches ReliefPkgItem total
            for item in relief_request.items:
                pkg_total = pkg_item_totals.get(item.item_id, Decimal('0'))
                
                # For items with issue_qty > 0, must have matching ReliefPkgItem records
                if item.issue_qty > 0 and pkg_total == Decimal('0'):
                    raise ValueError(f'Data integrity error: Item {item.item.item_name} has issue_qty={item.issue_qty} but no package items allocated. Please re-prepare the package.')
                
                # Verify totals match (allowing small decimal precision differences)
                if abs(item.issue_qty - pkg_total) > Decimal('0.001'):
                    raise ValueError(f'Data integrity error: Item {item.item.item_name} issue_qty ({item.issue_qty}) does not match allocated quantity ({pkg_total}). Please re-prepare the package.')
            
            # Verify at least one item has allocated quantity (support partial fulfillment)
            # UNLESS all items are marked as unavailable (U, D, W)
            has_allocated_items = any(item.issue_qty > 0 for item in relief_request.items)
            
            if not has_allocated_items:
                # Check if all items have valid unavailability statuses
                unavailability_statuses = {'U', 'D', 'W'}
                all_items_unavailable = all(
                    item.status_code in unavailability_statuses 
                    for item in relief_request.items
                )
                
                if not all_items_unavailable:
                    # Items have no allocations AND not all marked unavailable
                    raise ValueError('Cannot dispatch empty package. Please allocate items before dispatching or mark all items as unavailable.')
            
            # LM approval: set verify_by_id and verify_dtime
            relief_pkg.verify_by_id = session_utils.get_user_name()
            relief_pkg.verify_dtime = jamaica_now()
            
            # Mark package as dispatched
            relief_pkg.status_code = rr_service.PKG_STATUS_DISPATCHED
            relief_pkg.dispatch_dtime = jamaica_now()
            relief_pkg.update_by_id = session_utils.get_user_name()
            relief_pkg.update_dtime = jamaica_now()
            relief_pkg.version_nbr += 1
            
            # Commit inventory: convert reservations to actual deductions
            success, error_msg = reservation_service.commit_inventory(relief_request.reliefrqst_id)
            if not success:
                raise ValueError(f'Inventory commit failed: {error_msg}')
            
            # Update relief request status
            relief_request.action_by_id = session_utils.get_user_name()
            relief_request.action_dtime = jamaica_now()
            relief_request.status_code = rr_service.STATUS_PART_FILLED
            relief_request.version_nbr += 1
            
            # Notify logistics officers and agency users about package approval
            try:
                from app.services.notification_service import NotificationService
                
                # Notify logistics officers
                lo_users = NotificationService.get_active_users_by_role_codes(['LOGISTICS_OFFICER'])
                
                # Notify agency users
                agency_users = []
                if relief_request.agency_id:
                    agency_users = NotificationService.get_agency_active_users(relief_request.agency_id)
                
                all_recipients = lo_users + agency_users
                approver_name = session_utils.get_display_name()
                
                NotificationService.create_package_approved_notification(
                    relief_pkg=relief_pkg,
                    recipient_users=all_recipients,
                    approver_name=approver_name
                )
            except Exception as e:
                # Don't fail dispatch if notification fails
                import logging
                logger = logging.getLogger(__name__)
                logger.warning('Failed to send approval notification: %s', sanitize_exception_for_log(e))
            
            db.session.commit()
            
            flash(f'Relief request #{relief_request.reliefrqst_id} approved and dispatched to inventory clerk', 'success')
            return redirect(url_for('packaging.pending_approval'))
            
        except (OptimisticLockError, ValueError) as e:
            db.session.rollback()
            current_app.logger.warning('Validation error in approve action: %s', sanitize_exception_for_log(e))
            flash('A validation error occurred. Please refresh the page and try again.', 'danger')
            return redirect(url_for('packaging.review_approval', reliefrqst_id=reliefrqst_id))
    
    elif action == 'reject':
        try:
            _validate_version_nbr("relief request", relief_request_version, relief_request.version_nbr)
            _validate_version_nbr("package", package_version, relief_pkg.version_nbr)
            
            # Reset LM approval fields so Logistics Officer can revise and resubmit
            relief_pkg.verify_by_id = None
            relief_pkg.verify_dtime = None
            relief_pkg.status_code = rr_service.PKG_STATUS_PENDING
            relief_pkg.update_by_id = session_utils.get_user_name()
            relief_pkg.update_dtime = jamaica_now()
            relief_pkg.version_nbr += 1
            
            # Record action on the relief request for audit trail
            relief_request.action_by_id = session_utils.get_user_name()
            relief_request.action_dtime = jamaica_now()
            relief_request.version_nbr += 1
            
            db.session.commit()
            
            flash('Package rejected and sent back to Logistics Officer for revision.', 'info')
            return redirect(url_for('packaging.pending_approval'))
        except (OptimisticLockError, ValueError) as e:
            db.session.rollback()
            current_app.logger.warning('Validation error in reject action: %s', sanitize_exception_for_log(e))
            flash('A validation error occurred. Please refresh the page and try again.', 'danger')
            return redirect(url_for('packaging.review_approval', reliefrqst_id=reliefrqst_id))
    
    else:
        flash('Invalid action', 'danger')
        return redirect(url_for('packaging.review_approval', reliefrqst_id=reliefrqst_id))


@packaging_bp.route('/package/<int:reliefpkg_id>/cancel', methods=['POST'])
@login_required
def cancel_package(reliefpkg_id):
    """
    Cancel a relief package and fully reverse all reservations.
    
    Only Logistics Managers can cancel packages.
    Uses optimistic locking to prevent conflicts.
    Fully transactional - all-or-nothing operation.
    
    Cancellation Process:
    1. Validates package exists and can be cancelled (P=Pending or D=Dispatched only)
    2. Releases batch-level reservations (itembatch.reserved_qty) with version_nbr check
    3. Releases warehouse-level reservations (inventory.reserved_qty) with version_nbr check
    4. Deletes all ReliefPkgItem records
    5. Deletes the ReliefPkg record
    
    If any version_nbr mismatch or validation error occurs, the entire operation is rolled back.
    """
    from app.core.rbac import is_logistics_manager
    from app.services.inventory_reservation_service import cancel_relief_package
    
    if not is_logistics_manager():
        flash('Access denied. Only Logistics Managers can cancel packages.', 'danger')
        abort(403)
    
    try:
        relief_pkg = ReliefPkg.query.get(reliefpkg_id)
        relief_request_id = relief_pkg.reliefrqst_id if relief_pkg else None
        
        # Call the service function to cancel the package with optimistic locking
        success, error_msg = cancel_relief_package(reliefpkg_id, session_utils.get_user_name())
        
        if not success:
            db.session.rollback()
            flash(error_msg, 'danger')
            return redirect(get_safe_redirect_url(request.referrer, 'packaging.pending_approval'))
        
        # Commit the transaction
        db.session.commit()
        
        log_data_event(
            action=AuditAction.CANCEL,
            user_id=current_user.user_id,
            entity_type='relief_package',
            entity_id=reliefpkg_id,
            outcome=AuditOutcome.SUCCESS,
            details={
                'relief_request_id': relief_request_id,
                'reservations_released': True
            }
        )
        
        flash(f'Relief package #{reliefpkg_id} has been successfully cancelled. All reservations have been released.', 'success')
        return redirect(url_for('packaging.pending_approval'))
        
    except Exception as e:
        db.session.rollback()
        
        # Log the error for debugging
        import logging
        logger = logging.getLogger(__name__)
        logger.error('Unexpected error in cancel_package route: %s', sanitize_exception_for_log(e), exc_info=True)
        
        # Show user-friendly error message
        flash('An unexpected error occurred while canceling the package. Please contact system administrator if this persists.', 'danger')
        return redirect(get_safe_redirect_url(request.referrer, 'packaging.pending_approval'))


@packaging_bp.route('/<int:reliefrqst_id>/approve', methods=['GET', 'POST'])
@login_required
def approve_package(reliefrqst_id):
    """
    LM approves package with full editing capability.
    Similar to prepare_package but:
    - LM-only access
    - Loads existing allocations from pending package
    - Allows editing with batch drawer (FEFO/FIFO logic)
    - Save Draft or Approve & Dispatch
    """
    from app.core.rbac import is_logistics_manager
    if not is_logistics_manager():
        flash('Access denied. Only Logistics Managers can approve packages.', 'danger')
        abort(403)
    
    relief_request = ReliefRqst.query.options(
        joinedload(ReliefRqst.agency),
        joinedload(ReliefRqst.eligible_event),
        joinedload(ReliefRqst.status),
        joinedload(ReliefRqst.items).joinedload(ReliefRqstItem.item).joinedload(Item.category),
        joinedload(ReliefRqst.items).joinedload(ReliefRqstItem.item).joinedload(Item.default_uom),
        joinedload(ReliefRqst.packages)
    ).get_or_404(reliefrqst_id)
    
    # Get the pending package
    relief_pkg = next((pkg for pkg in relief_request.packages if pkg.status_code == rr_service.PKG_STATUS_PENDING), None)
    
    if not relief_pkg:
        flash('No pending package found for this relief request.', 'danger')
        return redirect(url_for('packaging.pending_approval'))
    
    if relief_pkg.dispatch_dtime is not None:
        flash('This package has already been dispatched.', 'warning')
        return redirect(url_for('packaging.pending_approval'))
    
    if request.method == 'GET':
        
        # Load warehouses
        warehouses = Warehouse.query.filter_by(status_code='A').order_by(Warehouse.warehouse_name).all()
        
        # Load inventory availability for each item
        item_inventory_map = {}
        for item in relief_request.items:
            inventories = Inventory.query.filter_by(
                item_id=item.item_id,
                status_code='A'
            ).filter(
                Inventory.usable_qty > 0
            ).join(Warehouse).order_by(Warehouse.warehouse_name).all()
            
            item_inventory_map[item.item_id] = inventories
        
        # Load existing BATCH-LEVEL allocations from the pending package
        # This ensures LM sees LO's prepared allocations exactly as submitted
        # CRITICAL: Build set of items with allocation activity BEFORE processing allocations
        items_with_pkg_records = set()
        
        # CRITICAL: Explicitly query ReliefPkgItem records to ensure zero-qty markers are loaded
        existing_batch_allocations = {}
        pkg_items = ReliefPkgItem.query.filter_by(reliefpkg_id=relief_pkg.reliefpkg_id).all()
        for pkg_item in pkg_items:
            item_id = pkg_item.item_id
            
            # CRITICAL: Mark this item as having allocation activity
            items_with_pkg_records.add(item_id)
            
            warehouse_id = pkg_item.fr_inventory_id  # fr_inventory_id IS the warehouse_id
            batch_id = pkg_item.batch_id
            
            if item_id not in existing_batch_allocations:
                existing_batch_allocations[item_id] = []
            
            # Store batch-level allocation details
            existing_batch_allocations[item_id].append({
                'warehouse_id': warehouse_id,
                'batch_id': batch_id,
                'qty': float(pkg_item.item_qty)  # Convert Decimal to float for JSON
            })
        
        # Load item status map
        status_map = item_status_service.load_status_map()
        
        # Compute item status options
        item_status_options = {}
        
        # items_with_pkg_records was already built from the explicit ReliefPkgItem query above
        # This includes zero-qty records that serve as activity markers
        
        for item in relief_request.items:
            total_allocated = Decimal('0')
            if item.item_id in existing_batch_allocations:
                for batch_allocation in existing_batch_allocations[item.item_id]:
                    total_allocated += safe_decimal(batch_allocation['qty'])
            
            # Check if item has allocation activity (drawer opened/saved)
            # An item has activity if a ReliefPkgItem record exists, even with qty=0
            has_allocation_activity = item.item_id in items_with_pkg_records
            
            auto_status, allowed_codes = item_status_service.compute_allowed_statuses(
                item.status_code,
                total_allocated,
                item.request_qty,
                has_allocation_activity
            )
            
            item_status_options[item.item_id] = {
                'auto_status': auto_status,
                'allowed_codes': allowed_codes,
                'total_allocated': float(total_allocated),
                'has_allocation_activity': has_allocation_activity
            }
        
        return render_template('packaging/approve.html',
                             relief_request=relief_request,
                             relief_pkg=relief_pkg,
                             warehouses=warehouses,
                             item_inventory_map=item_inventory_map,
                             existing_batch_allocations=existing_batch_allocations,
                             status_map=status_map,
                             item_status_options=item_status_options)
    
    # POST: Handle actions
    
    action = request.form.get('action')
    
    # Extract version numbers for optimistic locking
    relief_request_version = request.form.get('relief_request_version')
    package_version = request.form.get('package_version')
    
    if action == 'save_draft':
        return _save_draft_approval(relief_request, relief_pkg, relief_request_version, package_version)
    elif action == 'approve_and_dispatch':
        return _approve_and_dispatch(relief_request, relief_pkg, relief_request_version, package_version)
    else:
        flash('Invalid action', 'danger')
        return redirect(url_for('packaging.approve_package', reliefrqst_id=reliefrqst_id))


def _save_draft_approval(relief_request, relief_pkg, relief_request_version, package_version):
    """
    LM saves draft changes during approval workflow.
    
    Draft behavior:
    - Updates allocations with delta-based itembatch changes
    - Keeps package in Pending status with verify_by_id set (indicates submitted for approval)
    - Package stays in "Awaiting Approval" queue for continued LM editing
    - No notifications sent
    - Concurrency control via optimistic locking (version_nbr)
    """
    try:
        # OPTIMISTIC LOCKING: Validate relief request version
        _validate_version_nbr("relief request", relief_request_version, relief_request.version_nbr)
        
        # OPTIMISTIC LOCKING: Validate package version
        _validate_version_nbr("package", package_version, relief_pkg.version_nbr)
        
        # Process batch allocations and update ReliefPkgItem
        new_allocations = _process_allocations(relief_request, validate_complete=False)
        
        # Keep package in pending status
        relief_pkg.status_code = rr_service.PKG_STATUS_PENDING
        relief_pkg.update_by_id = session_utils.get_user_name()
        relief_pkg.update_dtime = jamaica_now()
        relief_pkg.version_nbr += 1
        
        # Flush to persist allocations before reservation
        db.session.flush()
        
        # Update inventory reservations with delta-based changes
        old_allocations = relief_request._old_allocations if hasattr(relief_request, '_old_allocations') else {}
        success, error_msg = reservation_service.reserve_inventory(
            relief_request.reliefrqst_id,
            new_allocations,
            old_allocations
        )
        
        if not success:
            # Reservation failed - rollback
            db.session.rollback()
            flash(f'{error_msg}', 'warning')
            flash('Draft not saved due to insufficient inventory.', 'info')
            return redirect(url_for('packaging.approve_package', reliefrqst_id=relief_request.reliefrqst_id))
        
        # Commit changes
        db.session.commit()
        
        flash(f'Draft saved for relief request #{relief_request.reliefrqst_id}.', 'success')
        
        # Redirect back to approval page so LM can continue editing
        return redirect(url_for('packaging.approve_package', reliefrqst_id=relief_request.reliefrqst_id))
        
    except OptimisticLockError as e:
        db.session.rollback()
        current_app.logger.warning('Concurrency conflict in save draft: %s', sanitize_exception_for_log(e))
        flash('This record was modified by another user. Please refresh the page and try again.', 'warning')
        return redirect(url_for('packaging.approve_package', reliefrqst_id=relief_request.reliefrqst_id))
    except ValueError as e:
        db.session.rollback()
        current_app.logger.warning('Validation error in save draft: %s', sanitize_exception_for_log(e))
        flash('A validation error occurred. Please check your input and try again.', 'danger')
        return redirect(url_for('packaging.approve_package', reliefrqst_id=relief_request.reliefrqst_id))
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error saving draft in approval')
        flash('An error occurred while saving the draft. Please try again.', 'danger')
        return redirect(url_for('packaging.approve_package', reliefrqst_id=relief_request.reliefrqst_id))


def _approve_and_dispatch(relief_request, relief_pkg, relief_request_version, package_version):
    """
    LM approves package and dispatches to Inventory Clerk.
    - Validates allocations
    - Updates reliefrqst_item.issue_qty
    - Commits inventory (reserved -> actual deduction)
    - Transitions to Dispatched status
    - Notifies Inventory Clerk
    - Releases lock
    """
    try:
        # OPTIMISTIC LOCKING: Validate relief request version
        _validate_version_nbr("relief request", relief_request_version, relief_request.version_nbr)
        
        # OPTIMISTIC LOCKING: Validate package version
        _validate_version_nbr("package", package_version, relief_pkg.version_nbr)
        
        # Process and validate allocations (can be partial)
        new_allocations = _process_allocations(relief_request, validate_complete=False)
        
        # CRITICAL VALIDATION: Ensure package has items AND issue_qty matches ReliefPkgItem totals
        # Get all ReliefPkgItem records for this package
        pkg_items = ReliefPkgItem.query.filter_by(reliefpkg_id=relief_pkg.reliefpkg_id).all()
        
        if not pkg_items:
            # No items allocated - package is empty
            # Check if all items have valid unavailability statuses (U, D, W)
            unavailability_statuses = {'U', 'D', 'W'}
            all_items_unavailable = all(
                item.status_code in unavailability_statuses 
                for item in relief_request.items
            )
            
            if not all_items_unavailable:
                raise ValueError('Cannot dispatch package: no items have been allocated. All requested items must either have batch allocations or be marked as Unavailable (U), Denied (D), or Awaiting Availability (W).')
        
        # Validate that ReliefPkgItem quantities match issue_qty for data integrity
        # Build totals from ReliefPkgItem records
        pkg_item_totals = {}
        for pkg_item in pkg_items:
            if pkg_item.item_id not in pkg_item_totals:
                pkg_item_totals[pkg_item.item_id] = Decimal('0')
            pkg_item_totals[pkg_item.item_id] += pkg_item.item_qty
        
        # Verify each item's issue_qty matches ReliefPkgItem total
        for item in relief_request.items:
            pkg_total = pkg_item_totals.get(item.item_id, Decimal('0'))
            
            # For items with issue_qty > 0, must have matching ReliefPkgItem records
            if item.issue_qty > 0 and pkg_total == Decimal('0'):
                raise ValueError(f'Data integrity error: Item {item.item.item_name} has issue_qty={item.issue_qty} but no package items allocated. Please re-prepare the package.')
            
            # Verify totals match (allowing small decimal precision differences)
            if abs(item.issue_qty - pkg_total) > Decimal('0.001'):
                raise ValueError(f'Data integrity error: Item {item.item.item_name} issue_qty ({item.issue_qty}) does not match allocated quantity ({pkg_total}). Please re-prepare the package.')
        
        # Verify at least one item has allocated quantity (support partial fulfillment)
        # UNLESS all items are marked as unavailable (U, D, W)
        has_allocated_items = any(alloc['allocated_qty'] > 0 for alloc in new_allocations)
        
        if not has_allocated_items:
            # Check if all items have valid unavailability statuses
            unavailability_statuses = {'U', 'D', 'W'}
            all_items_unavailable = all(
                item.status_code in unavailability_statuses 
                for item in relief_request.items
            )
            
            if not all_items_unavailable:
                # Items have no allocations AND not all marked unavailable
                raise ValueError('Cannot dispatch empty package. Please allocate items before dispatching or mark all items as unavailable.')
        
        # Update issue_qty for each item based on total allocated quantity
        for item in relief_request.items:
            total_allocated = Decimal('0')
            for alloc in new_allocations:
                if alloc['item_id'] == item.item_id:
                    total_allocated += alloc['allocated_qty']
            
            item.issue_qty = total_allocated
            item.version_nbr += 1
        
        # LM approval: set verify_by_id and verify_dtime
        relief_pkg.verify_by_id = session_utils.get_user_name()
        relief_pkg.verify_dtime = jamaica_now()
        
        # Mark package as dispatched
        relief_pkg.status_code = rr_service.PKG_STATUS_DISPATCHED
        relief_pkg.dispatch_dtime = jamaica_now()
        relief_pkg.update_by_id = session_utils.get_user_name()
        relief_pkg.update_dtime = jamaica_now()
        relief_pkg.version_nbr += 1
        
        # Flush to persist allocations
        db.session.flush()
        
        # Commit inventory: convert reservations to actual deductions
        success, error_msg = reservation_service.commit_inventory(relief_request.reliefrqst_id)
        if not success:
            raise ValueError(f'Inventory commit failed: {error_msg}')
        
        # Update relief request status
        relief_request.action_by_id = session_utils.get_user_name()
        relief_request.action_dtime = jamaica_now()
        relief_request.status_code = rr_service.STATUS_PART_FILLED
        relief_request.version_nbr += 1
        
        # Notify Inventory Clerk and agency users
        try:
            from app.services.notification_service import NotificationService
            
            # Notify logistics officers (inventory clerks)
            lo_users = NotificationService.get_active_users_by_role_codes(['LOGISTICS_OFFICER', 'INVENTORY_CLERK'])
            
            # Notify agency users
            agency_users = []
            if relief_request.agency_id:
                agency_users = NotificationService.get_agency_active_users(relief_request.agency_id)
            
            all_recipients = lo_users + agency_users
            approver_name = session_utils.get_display_name()
            
            NotificationService.create_package_approved_notification(
                relief_pkg=relief_pkg,
                recipient_users=all_recipients,
                approver_name=approver_name
            )
        except Exception as e:
            # Don't fail dispatch if notification fails
            import logging
            logger = logging.getLogger(__name__)
            logger.warning('Failed to send approval notification: %s', sanitize_exception_for_log(e))
        
        db.session.commit()
        
        log_data_event(
            action=AuditAction.DISPATCH,
            user_id=current_user.user_id,
            entity_type='relief_package',
            entity_id=relief_pkg.reliefpkg_id,
            outcome=AuditOutcome.SUCCESS,
            details={
                'relief_request_id': relief_request.reliefrqst_id,
                'agency_id': relief_request.agency_id,
                'workflow': 'approve_and_dispatch',
                'previous_status': 'P',
                'new_status': 'D'
            }
        )
        
        flash(f'Relief request #{relief_request.reliefrqst_id} approved and dispatched to inventory clerk', 'success')
        return redirect(url_for('packaging.transaction_summary', reliefpkg_id=relief_pkg.reliefpkg_id))
        
    except ValueError as e:
        db.session.rollback()
        current_app.logger.warning('Validation error approving package: %s', sanitize_exception_for_log(e))
        flash('A validation error occurred. Please check your input and try again.', 'danger')
        return redirect(url_for('packaging.approve_package', reliefrqst_id=relief_request.reliefrqst_id))
    except OptimisticLockError as e:
        db.session.rollback()
        current_app.logger.warning('Concurrency conflict approving package: %s', sanitize_exception_for_log(e))
        flash('This record was modified by another user. Please refresh the page and try again.', 'danger')
        return redirect(url_for('packaging.approve_package', reliefrqst_id=relief_request.reliefrqst_id))
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error approving package')
        flash('An error occurred while approving the package. Please try again.', 'danger')
        return redirect(url_for('packaging.approve_package', reliefrqst_id=relief_request.reliefrqst_id))


@packaging_bp.route('/package/<int:reliefpkg_id>/submit-dispatch', methods=['POST'])
@login_required
def submit_for_dispatch(reliefpkg_id):
    """
    WORKFLOW C: LM Submit for Dispatch.
    
    This is the final dispatch operation when Logistics Manager clicks "Submit for Dispatch".
    Implements Workflow C algorithm:
    1. Undo LO reservations (from reliefpkg_item) in itembatch and inventory
    2. Overwrite reliefpkg_item with LM's final plan
    3. Deplete usable stock in itembatch and inventory based on LM plan
    4. Update reliefpkg header status to Dispatched
    5. Update reliefrqst_item.issue_qty with actual dispatched quantities
    
    All operations execute in ONE atomic transaction with optimistic locking.
    On any failure, the entire transaction is rolled back.
    
    IMPORTANT: This route does NOT modify Workflow A or B logic.
    It only handles the final dispatch step for LM.
    """
    from app.core.rbac import is_logistics_manager
    from app.services import dispatch_service
    
    if not is_logistics_manager():
        flash('Access denied. Only Logistics Managers can submit packages for dispatch.', 'danger')
        abort(403)
    
    # Get the package
    relief_pkg = ReliefPkg.query.get_or_404(reliefpkg_id)
    
    # Extract version number for optimistic locking
    package_version = request.form.get('package_version')
    if package_version is None:
        flash('Version number is required for concurrency control.', 'danger')
        return redirect(url_for('packaging.approve_package', reliefrqst_id=relief_pkg.reliefrqst_id))
    
    try:
        package_version = int(package_version)
    except (ValueError, TypeError):
        flash('Invalid version number format.', 'danger')
        return redirect(url_for('packaging.approve_package', reliefrqst_id=relief_pkg.reliefrqst_id))
    
    # Build LM plan from form data or current package items
    # Check if allocations are provided in form data (JSON format)
    allocations_json = request.form.get('allocations_json')
    
    if allocations_json:
        import json
        try:
            form_data = json.loads(allocations_json)
            lm_plan = dispatch_service.build_lm_plan_from_form(form_data, reliefpkg_id)
        except json.JSONDecodeError:
            flash('Invalid allocation data format.', 'danger')
            return redirect(url_for('packaging.approve_package', reliefrqst_id=relief_pkg.reliefrqst_id))
    else:
        # Use current package items as LM plan (LM approves without modifications)
        lm_plan = dispatch_service.build_lm_plan_from_pkg_items(reliefpkg_id)
    
    # Validate LM plan has allocations (unless all items are marked unavailable)
    if not lm_plan:
        # Check if all items have valid unavailability statuses
        relief_request = ReliefRqst.query.get(relief_pkg.reliefrqst_id)
        unavailability_statuses = {'U', 'D', 'W'}
        all_items_unavailable = all(
            item.status_code in unavailability_statuses 
            for item in relief_request.items
        )
        
        if not all_items_unavailable:
            flash('Cannot dispatch empty package. Please allocate items before dispatching or mark all items as unavailable.', 'danger')
            return redirect(url_for('packaging.approve_package', reliefrqst_id=relief_pkg.reliefrqst_id))
    
    # Execute Workflow C dispatch
    relief_request_for_log = ReliefRqst.query.get(relief_pkg.reliefrqst_id)
    
    try:
        success, message = dispatch_service.submit_for_dispatch(
            reliefpkg_id=reliefpkg_id,
            lm_plan=lm_plan,
            user_id=session_utils.get_user_name(),
            package_version_nbr=package_version
        )
        
        if not success:
            db.session.rollback()
            flash(message, 'danger')
            return redirect(url_for('packaging.approve_package', reliefrqst_id=relief_pkg.reliefrqst_id))
        
        # Notify Inventory Clerk and agency users
        try:
            from app.services.notification_service import NotificationService
            
            # Notify logistics officers (inventory clerks)
            lo_users = NotificationService.get_active_users_by_role_codes(['LOGISTICS_OFFICER', 'INVENTORY_CLERK'])
            
            # Notify agency users
            agency_users = []
            if relief_request_for_log and relief_request_for_log.agency_id:
                agency_users = NotificationService.get_agency_active_users(relief_request_for_log.agency_id)
            
            all_recipients = lo_users + agency_users
            approver_name = session_utils.get_display_name()
            
            NotificationService.create_package_approved_notification(
                relief_pkg=relief_pkg,
                recipient_users=all_recipients,
                approver_name=approver_name
            )
        except Exception as e:
            # Don't fail dispatch if notification fails
            import logging
            logger = logging.getLogger(__name__)
            logger.warning('Failed to send dispatch notification: %s', sanitize_exception_for_log(e))
        
        db.session.commit()
        
        log_data_event(
            action=AuditAction.DISPATCH,
            user_id=current_user.user_id,
            entity_type='relief_package',
            entity_id=reliefpkg_id,
            outcome=AuditOutcome.SUCCESS,
            details={
                'relief_request_id': relief_pkg.reliefrqst_id,
                'agency_id': relief_request_for_log.agency_id if relief_request_for_log else None,
                'workflow': 'submit_for_dispatch',
                'previous_status': 'P',
                'new_status': 'D'
            }
        )
        
        flash(f'Package #{reliefpkg_id} successfully submitted for dispatch.', 'success')
        return redirect(url_for('packaging.transaction_summary', reliefpkg_id=reliefpkg_id))
        
    except Exception as e:
        db.session.rollback()
        import logging
        logger = logging.getLogger(__name__)
        logger.error('Error in submit_for_dispatch: %s', sanitize_exception_for_log(e), exc_info=True)
        # Sanitized error message - never expose raw exception details to users
        flash('An error occurred while submitting the package for dispatch. Please try again or contact support.', 'danger')
        return redirect(url_for('packaging.approve_package', reliefrqst_id=relief_pkg.reliefrqst_id))


@packaging_bp.route('/transaction-summary/<int:reliefpkg_id>')
@login_required
def transaction_summary(reliefpkg_id):
    """
    Display print-friendly transaction summary after LM approval.
    Shows all package details, allocations by warehouse/batch, and signature section.
    """
    from app.core.rbac import is_logistics_manager, is_logistics_officer
    if not (is_logistics_manager() or is_logistics_officer()):
        flash('Access denied. Only Logistics Officers and Managers can view transaction summaries.', 'danger')
        abort(403)
    
    # Get the tab the user came from (for proper back navigation)
    from_tab = request.args.get('from_tab', 'approved_for_dispatch')
    
    # Load package with all related data
    relief_pkg = ReliefPkg.query.options(
        joinedload(ReliefPkg.relief_request).joinedload(ReliefRqst.agency),
        joinedload(ReliefPkg.relief_request).joinedload(ReliefRqst.eligible_event),
        joinedload(ReliefPkg.relief_request).joinedload(ReliefRqst.items).joinedload(ReliefRqstItem.item).joinedload(Item.default_uom),
        joinedload(ReliefPkg.relief_request).joinedload(ReliefRqst.items).joinedload(ReliefRqstItem.item_status),
        joinedload(ReliefPkg.items)
    ).get_or_404(reliefpkg_id)
    
    # Get package creator and approver info
    creator = User.query.filter_by(user_name=relief_pkg.create_by_id).first() if relief_pkg.create_by_id else None
    approver = User.query.filter_by(user_name=relief_pkg.verify_by_id).first() if relief_pkg.verify_by_id else None
    
    # Organize items by batch with warehouse info
    items_with_batches = []
    for req_item in relief_pkg.relief_request.items:
        # Get all package items (batches) for this request item
        pkg_items = [pi for pi in relief_pkg.items if pi.item_id == req_item.item_id]
        
        batches_info = []
        for pkg_item in pkg_items:
            # Load batch and warehouse info
            batch = ItemBatch.query.get(pkg_item.batch_id) if pkg_item.batch_id else None
            warehouse = Warehouse.query.get(pkg_item.fr_inventory_id) if pkg_item.fr_inventory_id else None
            
            batches_info.append({
                'warehouse_name': warehouse.warehouse_name if warehouse else 'Unknown',
                'batch_no': batch.batch_no if batch else 'N/A',
                'batch_date': batch.batch_date if batch else None,
                'expiry_date': batch.expiry_date if batch else None,
                'qty': pkg_item.item_qty
            })
        
        total_issued = sum(b['qty'] for b in batches_info)
        
        items_with_batches.append({
            'item': req_item.item,
            'requested_qty': req_item.request_qty,
            'issued_qty': total_issued,
            'batches': batches_info,
            'status_code': req_item.status_code,
            'status_desc': req_item.item_status.status_desc if req_item.item_status else None,
            'status_reason': req_item.status_reason_desc
        })
    
    # Calculate summary totals
    total_items = len(items_with_batches)
    total_batches = sum(len(item['batches']) for item in items_with_batches)
    unique_warehouses = set()
    for item in items_with_batches:
        for batch in item['batches']:
            unique_warehouses.add(batch['warehouse_name'])
    warehouses_used = len(unique_warehouses)
    
    return render_template('packaging/transaction_summary.html',
                         relief_pkg=relief_pkg,
                         relief_request=relief_pkg.relief_request,
                         items_with_batches=items_with_batches,
                         creator=creator,
                         approver=approver,
                         total_items=total_items,
                         total_batches=total_batches,
                         warehouses_used=warehouses_used,
                         generated_at=jamaica_now(),
                         from_tab=from_tab)


@packaging_bp.route('/create-request-on-behalf', methods=['GET', 'POST'])
@login_required
def create_request_on_behalf():
    """
    Create relief request on behalf of an agency.
    - Logistics Officers/Managers: Can select any agency
    - Agency Users: Automatically use their own agency
    """
    from app.core.rbac import is_logistics_officer, is_logistics_manager, is_agency_user
    from app.db.models import Agency, Event
    
    # Allow logistics users and agency users
    is_logistics = is_logistics_officer() or is_logistics_manager()
    is_agency = is_agency_user()
    
    if not (is_logistics or is_agency):
        flash('Access denied.', 'danger')
        abort(403)
    
    if request.method == 'POST':
        try:
            # Agency users use their own agency; logistics users select from dropdown
            if is_agency:
                agency_id = session_utils.get_agency_id()
                if not agency_id:
                    flash('Your user account is not associated with an agency.', 'danger')
                    return redirect(url_for('packaging.create_request_on_behalf'))
            else:
                # Logistics users select agency
                agency_id = request.form.get('agency_id')
                if not agency_id:
                    flash('Please select an agency', 'danger')
                    return redirect(url_for('packaging.create_request_on_behalf'))
                agency_id = int(agency_id)
            
            urgency_ind = request.form.get('urgency_ind', 'M')
            eligible_event_id = request.form.get('eligible_event_id')
            eligible_event_id = int(eligible_event_id) if eligible_event_id else None
            rqst_notes_text = request.form.get('rqst_notes_text', '').strip()
            
            # Validate agency
            agency = Agency.query.get(agency_id)
            if not agency:
                flash('Invalid agency selected', 'danger')
                return redirect(url_for('packaging.create_request_on_behalf'))
            
            # Validate urgency
            if urgency_ind not in ['H', 'M', 'L']:
                flash('Invalid urgency level', 'danger')
                return redirect(url_for('packaging.create_request_on_behalf'))
            
            # Create draft request using existing service
            relief_request = rr_service.create_draft_request(
                agency_id=agency_id,
                urgency_ind=urgency_ind,
                eligible_event_id=eligible_event_id,
                rqst_notes_text=rqst_notes_text,
                user_email=session_utils.get_email()
            )
            
            db.session.commit()
            
            flash(f'Draft relief request #{relief_request.reliefrqst_id} created successfully for {agency.agency_name}. Add items to continue.', 'success')
            # Redirect to the standard edit_items page in requests blueprint
            return redirect(url_for('requests.edit_items', request_id=relief_request.reliefrqst_id))
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('Error creating request on behalf')
            flash('An error occurred while creating the request. Please try again.', 'danger')
            return redirect(url_for('packaging.create_request_on_behalf'))
    
    # GET request - show form
    events = Event.query.filter_by(status_code='A').order_by(Event.start_date.desc()).all()
    
    # For agency users, get their agency; for logistics, get all agencies
    if is_agency:
        user_agency = Agency.query.get(session_utils.get_agency_id()) if session_utils.get_agency_id() else None
        agencies = None  # Don't show agency selector for agency users
    else:
        user_agency = None
        agencies = Agency.query.filter_by(status_code='A').order_by(Agency.agency_name).all()
    
    from app.utils.timezone import today as jamaica_today
    
    return render_template('packaging/create_request_on_behalf.html',
                         agencies=agencies,
                         user_agency=user_agency,
                         is_logistics=is_logistics,
                         events=events,
                         today=jamaica_today().isoformat())


@packaging_bp.route('/pending-fulfillment')
@login_required
def pending_fulfillment():
    """
    List all approved relief requests awaiting package preparation.
    Shows SUBMITTED (3) and PART_FILLED (5) requests for LO/LM to fulfill.
    Also shows approved packages (status='D') for informational purposes.
    
    Uses tab-specific dataset builders to ensure badge counts exactly match displayed rows.
    """
    from app.core.rbac import is_logistics_officer, is_logistics_manager
    if not (is_logistics_officer() or is_logistics_manager()):
        flash('Access denied. Only Logistics Officers and Managers can view this page.', 'danger')
        abort(403)
    
    filter_type = request.args.get('filter', 'awaiting')
    current_user_name = session_utils.get_user_name()
    is_lm = is_logistics_manager()
    
    # Helper functions
    def has_pending_approval(req):
        """
        Check if request has a package submitted for LM approval.
        
        Distinguishes "submitted for approval" from "draft being prepared":
        - Submitted: verify_by_id == '__PENDING_LM__' (sentinel marker)
        - Draft: verify_by_id == NULL
        - Approved: verify_by_id == LM's username
        """
        return (req.status_code == rr_service.STATUS_PART_FILLED and
                any(pkg.status_code == rr_service.PKG_STATUS_PENDING 
                    and pkg.dispatch_dtime is None
                    and pkg.verify_by_id == '__PENDING_LM__'  # Must be submitted (not draft)
                    for pkg in req.packages))
    
    def has_dispatched_package(req):
        """Check if request has any packages that have been approved and dispatched."""
        return any(pkg.status_code == rr_service.PKG_STATUS_DISPATCHED 
                   for pkg in req.packages)
    
    def is_lo_involved_with_request(req):
        """Check if LO is involved with this request (created, took action on, or worked on packages/items)."""
        # LO created the request
        if req.create_by_id == current_user_name:
            return True
        # LO took action on the request (fulfillment actions)
        if hasattr(req, 'action_by_id') and req.action_by_id == current_user_name:
            return True
        # LO took action on any request items
        if any(hasattr(item, 'action_by_id') and item.action_by_id == current_user_name 
               for item in req.items):
            return True
        # LO worked on any packages
        return any(pkg.create_by_id == current_user_name or pkg.update_by_id == current_user_name 
                  for pkg in req.packages)
    
    def is_lo_involved_with_package(pkg):
        """Check if LO is involved with this package."""
        return (pkg.create_by_id == current_user_name or 
                pkg.update_by_id == current_user_name or
                (pkg.relief_request and pkg.relief_request.create_by_id == current_user_name))
    
    # Tab-specific dataset builders - each returns the EXACT dataset to be displayed
    def get_awaiting_requests():
        """Get requests awaiting to be filled (SUBMITTED status)."""
        all_requests = ReliefRqst.query.options(
            joinedload(ReliefRqst.agency),
            joinedload(ReliefRqst.eligible_event),
            joinedload(ReliefRqst.status),
            joinedload(ReliefRqst.items),
            joinedload(ReliefRqst.packages)
        ).filter(
            ReliefRqst.status_code == rr_service.STATUS_SUBMITTED
        ).order_by(ReliefRqst.create_dtime.desc()).all()
        
        results = []
        for req in all_requests:
            # Skip requests with pending approval or dispatched packages
            if has_pending_approval(req) or has_dispatched_package(req):
                continue
            # All LOs and LMs see all approved/eligible requests (no ownership filtering)
            results.append(req)
        return results
    
    def get_in_progress_requests():
        """Get requests being prepared (PART_FILLED status)."""
        all_requests = ReliefRqst.query.options(
            joinedload(ReliefRqst.agency),
            joinedload(ReliefRqst.eligible_event),
            joinedload(ReliefRqst.status),
            joinedload(ReliefRqst.items),
            joinedload(ReliefRqst.packages)
        ).filter(
            ReliefRqst.status_code == rr_service.STATUS_PART_FILLED
        ).order_by(ReliefRqst.create_dtime.desc()).all()
        
        results = []
        for req in all_requests:
            # Skip requests with pending approval or dispatched packages
            if has_pending_approval(req) or has_dispatched_package(req):
                continue
            # All LOs and LMs see all approved/eligible requests (no ownership filtering)
            results.append(req)
        return results
    
    def get_pending_approval_requests():
        """Get requests with packages awaiting LM approval."""
        all_requests = ReliefRqst.query.options(
            joinedload(ReliefRqst.agency),
            joinedload(ReliefRqst.eligible_event),
            joinedload(ReliefRqst.status),
            joinedload(ReliefRqst.items),
            joinedload(ReliefRqst.packages)
        ).filter(
            ReliefRqst.status_code.in_([rr_service.STATUS_SUBMITTED, rr_service.STATUS_PART_FILLED])
        ).order_by(ReliefRqst.create_dtime.desc()).all()
        
        results = []
        for req in all_requests:
            if not has_pending_approval(req):
                continue
            # All LOs and LMs see all approved/eligible requests (no ownership filtering)
            results.append(req)
        return results
    
    def get_approved_packages_with_items():
        """Get approved packages WITH items allocated (total quantity > 0)."""
        all_packages = ReliefPkg.query.options(
            joinedload(ReliefPkg.relief_request).joinedload(ReliefRqst.agency),
            joinedload(ReliefPkg.relief_request).joinedload(ReliefRqst.eligible_event),
            joinedload(ReliefPkg.items).joinedload(ReliefPkgItem.item)
        ).filter(
            ReliefPkg.status_code == rr_service.PKG_STATUS_DISPATCHED,
            ReliefPkg.received_dtime.is_(None)
        ).order_by(ReliefPkg.dispatch_dtime.desc()).all()
        
        results = []
        for pkg in all_packages:
            # Calculate total quantity - matches template logic
            total_qty = sum(item.item_qty for item in pkg.items if item.item_qty)
            # Only packages WITH total quantity > 0
            if total_qty == 0:
                continue
            # All LOs and LMs see all approved packages (no ownership filtering)
            results.append(pkg)
        return results
    
    def get_approved_packages_no_items():
        """Get approved packages WITHOUT items allocated (total quantity == 0)."""
        all_packages = ReliefPkg.query.options(
            joinedload(ReliefPkg.relief_request).joinedload(ReliefRqst.agency),
            joinedload(ReliefPkg.relief_request).joinedload(ReliefRqst.eligible_event),
            joinedload(ReliefPkg.relief_request).joinedload(ReliefRqst.items),
            joinedload(ReliefPkg.items).joinedload(ReliefPkgItem.item)
        ).filter(
            ReliefPkg.status_code == rr_service.PKG_STATUS_DISPATCHED,
            ReliefPkg.received_dtime.is_(None)
        ).order_by(ReliefPkg.dispatch_dtime.desc()).all()
        
        results = []
        for pkg in all_packages:
            # Calculate total quantity - matches template logic
            total_qty = sum(item.item_qty for item in pkg.items if item.item_qty)
            # Only packages WITHOUT total quantity (zero or no items)
            if total_qty > 0:
                continue
            # All LOs and LMs see all approved packages (no ownership filtering)
            results.append(pkg)
        return results
    
    # Build ALL tab datasets and calculate counts from them
    # This ensures badge counts EXACTLY match displayed rows
    awaiting_requests = get_awaiting_requests()
    in_progress_requests = get_in_progress_requests()
    pending_approval_requests = get_pending_approval_requests()
    approved_with_items = get_approved_packages_with_items()
    approved_no_items = get_approved_packages_no_items()
    
    # Calculate counts from the EXACT datasets that will be displayed
    all_tab_counts = {
        'submitted': len(awaiting_requests),
        'in_progress': len(in_progress_requests),
        'pending_approval': len(pending_approval_requests),
        'approved': len(approved_with_items),
        'approved_no_allocation': len(approved_no_items)
    }
    
    # Return the appropriate dataset based on filter_type
    if filter_type == 'approved_for_dispatch':
        # Show approved packages WITH items - use pre-built dataset
        package_data = []
        for pkg in approved_with_items:
            package_data.append({
                'package': pkg,
                'relief_request': pkg.relief_request,
                'item_count': len(pkg.items),
                'total_qty': sum(item.item_qty for item in pkg.items if item.item_qty)
            })
        
        return render_template('packaging/pending_fulfillment.html',
                             requests=[],
                             packages=package_data,
                             counts=all_tab_counts,
                             global_counts=all_tab_counts,
                             current_filter=filter_type,
                             now=jamaica_now())
    
    elif filter_type == 'approved_no_allocation':
        # Show approved packages WITHOUT items - use pre-built dataset
        package_data = []
        for pkg in approved_no_items:
            package_data.append({
                'package': pkg,
                'relief_request': pkg.relief_request,
                'item_count': 0,
                'total_qty': 0
            })
        
        return render_template('packaging/pending_fulfillment.html',
                             requests=[],
                             packages=package_data,
                             counts=all_tab_counts,
                             global_counts=all_tab_counts,
                             current_filter=filter_type,
                             now=jamaica_now())
    
    elif filter_type == 'awaiting':
        filtered_requests = awaiting_requests
    elif filter_type == 'in_progress':
        filtered_requests = in_progress_requests
    elif filter_type == 'pending_approval':
        filtered_requests = pending_approval_requests
    else:
        # Default: show all requests user is involved with
        filtered_requests = (awaiting_requests + in_progress_requests + pending_approval_requests)
    
    return render_template('packaging/pending_fulfillment.html',
                         requests=filtered_requests,
                         packages=[],
                         counts=all_tab_counts,
                         global_counts=all_tab_counts,
                         current_filter=filter_type,
                         STATUS_SUBMITTED=rr_service.STATUS_SUBMITTED,
                         STATUS_PART_FILLED=rr_service.STATUS_PART_FILLED)


@packaging_bp.route('/<int:reliefrqst_id>/prepare', methods=['GET', 'POST'])
@login_required
def prepare_package(reliefrqst_id):
    """
    Main packaging page - shows all items and warehouse allocations.
    Handles both GET (display) and POST (save/submit).
    """
    from app.core.rbac import is_logistics_officer, is_logistics_manager
    if not (is_logistics_officer() or is_logistics_manager()):
        flash('Access denied. Only Logistics Officers and Managers can prepare packages.', 'danger')
        abort(403)
    relief_request = ReliefRqst.query.options(
        joinedload(ReliefRqst.agency),
        joinedload(ReliefRqst.eligible_event),
        joinedload(ReliefRqst.status),
        joinedload(ReliefRqst.items).joinedload(ReliefRqstItem.item).joinedload(Item.category),
        joinedload(ReliefRqst.items).joinedload(ReliefRqstItem.item).joinedload(Item.default_uom)
    ).get_or_404(reliefrqst_id)
    
    if relief_request.status_code not in [rr_service.STATUS_SUBMITTED, rr_service.STATUS_PART_FILLED]:
        flash(f'Only SUBMITTED or PART FILLED requests can be packaged. Current status: {relief_request.status.status_desc}', 'danger')
        return redirect(url_for('packaging.pending_fulfillment'))
    
    # ACCESS CONTROL: LOs viewing submitted packages should see read-only UI
    # A package is "submitted to LM" when relief request status is PART_FILLED
    # Draft packages have request status = SUBMITTED
    is_read_only_for_lo = (
        relief_request.status_code == rr_service.STATUS_PART_FILLED and 
        is_logistics_officer() and 
        not is_logistics_manager()
    )
    
    if request.method == 'GET':
        
        warehouses = Warehouse.query.filter_by(status_code='A').order_by(Warehouse.warehouse_name).all()
        
        item_inventory_map = {}
        for item in relief_request.items:
            inventories = Inventory.query.filter_by(
                item_id=item.item_id,
                status_code='A'
            ).filter(
                Inventory.usable_qty > 0
            ).join(Warehouse).order_by(Warehouse.warehouse_name).all()
            
            item_inventory_map[item.item_id] = inventories
        
        # Get existing package for this relief request (should only be one)
        existing_package = ReliefPkg.query.filter_by(reliefrqst_id=reliefrqst_id).first()
        
        existing_allocations = {}
        existing_batch_allocations = {}
        
        # CRITICAL: Build set of items with allocation activity BEFORE processing allocations
        # This includes items with zero-qty ReliefPkgItem records (activity markers)
        items_with_pkg_records = set()
        
        # CRITICAL: Explicitly query ReliefPkgItem records to ensure zero-qty markers are loaded
        # SQLAlchemy relationships may not eagerly load all records, so we query directly
        if existing_package:
            pkg_items = ReliefPkgItem.query.filter_by(reliefpkg_id=existing_package.reliefpkg_id).all()
            for pkg_item in pkg_items:
                item_id = pkg_item.item_id
                
                # CRITICAL: Mark this item as having allocation activity
                items_with_pkg_records.add(item_id)
                
                # fr_inventory_id IS the warehouse_id (inventory_id = warehouse_id in schema)
                warehouse_id = pkg_item.fr_inventory_id
                batch_id = pkg_item.batch_id
                
                # Warehouse-level aggregation (for backward compatibility)
                if item_id not in existing_allocations:
                    existing_allocations[item_id] = {}
                
                if warehouse_id not in existing_allocations[item_id]:
                    existing_allocations[item_id][warehouse_id] = Decimal('0')
                
                existing_allocations[item_id][warehouse_id] += pkg_item.item_qty
                
                # Batch-level allocations (for drawer persistence)
                if item_id not in existing_batch_allocations:
                    existing_batch_allocations[item_id] = []
                
                existing_batch_allocations[item_id].append({
                    'warehouse_id': warehouse_id,
                    'batch_id': batch_id,
                    'qty': float(pkg_item.item_qty)  # Convert Decimal to float for JSON
                })
        
        # Load active item statuses
        status_map = item_status_service.load_status_map()
        
        # Compute allowed status options for each item based on allocation state
        item_status_options = {}
        
        # items_with_pkg_records was already built from the explicit ReliefPkgItem query above
        # This includes zero-qty records that serve as activity markers
        
        for item in relief_request.items:
            # Calculate total allocated for this item
            total_allocated = Decimal('0')
            if item.item_id in existing_allocations:
                for warehouse_qty in existing_allocations[item.item_id].values():
                    total_allocated += warehouse_qty
            
            # Check if item has allocation activity (drawer opened/saved)
            # An item has activity if a ReliefPkgItem record exists, even with qty=0
            has_allocation_activity = item.item_id in items_with_pkg_records
            
            # Get auto status and allowed transitions
            auto_status, allowed_codes = item_status_service.compute_allowed_statuses(
                item.status_code,
                total_allocated,
                item.request_qty,
                has_allocation_activity
            )
            
            item_status_options[item.item_id] = {
                'auto_status': auto_status,
                'allowed_codes': allowed_codes,
                'total_allocated': float(total_allocated),
                'has_allocation_activity': has_allocation_activity
            }
        
        return render_template('packaging/prepare.html',
                             relief_request=relief_request,
                             existing_package=existing_package,
                             warehouses=warehouses,
                             item_inventory_map=item_inventory_map,
                             existing_allocations=existing_allocations,
                             existing_batch_allocations=existing_batch_allocations,
                             status_map=status_map,
                             item_status_options=item_status_options,
                             is_read_only=is_read_only_for_lo)
    
    action = request.form.get('action')
    
    # Extract version numbers for optimistic locking
    relief_request_version = request.form.get('relief_request_version')
    package_version = request.form.get('package_version')
    
    if action == 'save_draft':
        return _save_draft(relief_request, relief_request_version, package_version)
    elif action == 'submit_for_approval':
        return _submit_for_approval(relief_request, relief_request_version, package_version)
    elif action == 'send_for_dispatch':
        return _send_for_dispatch(relief_request, relief_request_version, package_version)
    else:
        flash('Invalid action', 'danger')
        return redirect(url_for('packaging.prepare_package', reliefrqst_id=reliefrqst_id))


def _save_draft(relief_request, relief_request_version, package_version):
    """
    Save packaging progress as draft.
    
    Draft packages:
    - Change request status to PART_FILLED (to show in "Being Prepared" tab)
    - Create ReliefPkg with status='P' and received_by_id=NULL (draft marker)
    - Reserve inventory
    - NO notifications sent
    - Package stays in "Being Prepared" tab and OUT of "Pending Approval" tab
    
    IMPORTANT: Uses atomic transaction to ensure allocations and reservations stay in sync.
    If inventory reservation fails, entire transaction rolls back to prevent phantom allocations.
    Concurrency control is handled via optimistic locking (version_nbr).
    """
    try:
        # OPTIMISTIC LOCKING: Validate relief request version
        _validate_version_nbr("relief request", relief_request_version, relief_request.version_nbr)
        
        # OPTIMISTIC LOCKING: Validate package version if it exists
        existing_pkg = ReliefPkg.query.filter_by(reliefrqst_id=relief_request.reliefrqst_id).first()
        if existing_pkg and package_version:
            _validate_version_nbr("package", package_version, existing_pkg.version_nbr)
        
        # Process and validate allocations (creates ReliefPkgItem records in pending transaction)
        new_allocations = _process_allocations(relief_request, validate_complete=False)
        
        # Get the package created/updated by _process_allocations
        relief_pkg = ReliefPkg.query.filter_by(reliefrqst_id=relief_request.reliefrqst_id).first()
        if relief_pkg:
            # CRITICAL: Ensure verify_by_id is NULL for drafts (distinguishes draft from submitted)
            # Only "Submit for Approval" sets verify_by_id to '__PENDING_LM__' sentinel
            # This keeps drafts OUT of "Pending Approval" tab
            relief_pkg.verify_by_id = None
            relief_pkg.verify_dtime = None
            # NOTE: Do NOT increment version_nbr here - _process_allocations already does it
        
        # Change request status to PART_FILLED to show in "Being Prepared" tab
        relief_request.status_code = rr_service.STATUS_PART_FILLED
        relief_request.action_by_id = session_utils.get_user_name()
        relief_request.action_dtime = jamaica_now()
        relief_request.version_nbr += 1
        
        # Flush to database (still in transaction - not committed yet)
        db.session.flush()
        
        # Attempt inventory reservation BEFORE commit (same transaction)
        # This ensures atomicity: either both allocations and reservations succeed, or both fail
        old_allocations = relief_request._old_allocations if hasattr(relief_request, '_old_allocations') else {}
        success, error_msg = reservation_service.reserve_inventory(
            relief_request.reliefrqst_id,
            new_allocations,
            old_allocations
        )
        
        if not success:
            # Reservation failed - rollback to prevent phantom allocations
            db.session.rollback()
            flash(f'{error_msg}', 'warning')
            flash('Draft not saved due to insufficient inventory. Please adjust allocations or wait for inventory to become available.', 'info')
            return redirect(url_for('packaging.prepare_package', reliefrqst_id=relief_request.reliefrqst_id))
        
        # Reservation succeeded - commit both allocations and reservations atomically
        db.session.commit()
        
        flash(f'Draft saved for relief request #{relief_request.reliefrqst_id} with inventory reserved.', 'success')
        
        return redirect(url_for('packaging.pending_fulfillment'))
        
    except OptimisticLockError as e:
        db.session.rollback()
        current_app.logger.warning('Concurrency conflict saving draft: %s', sanitize_exception_for_log(e))
        flash('This record was modified by another user. Please refresh the page and try again.', 'warning')
        return redirect(url_for('packaging.prepare_package', reliefrqst_id=relief_request.reliefrqst_id))
    except ValueError as e:
        db.session.rollback()
        current_app.logger.warning('Validation error saving draft: %s', sanitize_exception_for_log(e))
        flash('A validation error occurred. Please check your input and try again.', 'danger')
        return redirect(url_for('packaging.prepare_package', reliefrqst_id=relief_request.reliefrqst_id))
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error saving draft in preparation')
        flash('An error occurred while saving the draft. Please try again.', 'danger')
        return redirect(url_for('packaging.prepare_package', reliefrqst_id=relief_request.reliefrqst_id))


def _submit_for_approval(relief_request, relief_request_version, package_version):
    """
    Submit package for Logistics Manager approval (LO only) - allows partial allocations.
    Workflow: LO fulfills → Submit to LM → LM approves → Dispatch to Inventory Clerk
    
    Note: LO submission preserves any existing verify_* audit fields. The "pending LM approval"
    state is indicated by: status_code='P' + no active lock + verify_by_id is NULL (first submission)
    or verify_by_id has value (resubmission after previous LM approval).
    """
    from app.core.rbac import is_logistics_officer
    if not is_logistics_officer():
        flash('Only Logistics Officers can submit for approval', 'danger')
        return redirect(url_for('packaging.prepare_package', reliefrqst_id=relief_request.reliefrqst_id))
    
    try:
        # OPTIMISTIC LOCKING: Validate relief request version
        _validate_version_nbr("relief request", relief_request_version, relief_request.version_nbr)
        
        # SUBMIT-ONCE GUARD: Prevent multiple LOs from submitting the same relief request
        # Check if package already exists and is ALREADY in PENDING status (submitted for LM approval)
        existing_pkg = ReliefPkg.query.filter_by(reliefrqst_id=relief_request.reliefrqst_id).first()
        
        # OPTIMISTIC LOCKING: Validate package version if it exists
        if existing_pkg and package_version:
            _validate_version_nbr("package", package_version, existing_pkg.version_nbr)
        
        # Store the current package version for optimistic locking check (before processing)
        pkg_version_before = existing_pkg.version_nbr if existing_pkg else None
        
        # A package is considered "already submitted" if it exists and status is PENDING ('P')
        # Status 'P' with a package record means it's either being prepared or already submitted for approval
        # To differentiate, we check if this is a "fresh" submission vs. an update to existing draft
        was_already_pending = existing_pkg and existing_pkg.status_code == rr_service.PKG_STATUS_PENDING
        
        # CRITICAL: If package is already PENDING, only allow the SAME user to update it (not a different LO)
        # This prevents LO #2 from submitting after LO #1 has already submitted
        if was_already_pending and existing_pkg.create_by_id != session_utils.get_user_name():
            flash('This relief request has already been submitted to the Logistics Manager for approval by another user.', 'warning')
            return redirect(url_for('packaging.pending_fulfillment'))
        
        # Process and validate allocations
        new_allocations = _process_allocations(relief_request, validate_complete=False)
        
        # Get the ReliefPkg that was created/updated by _process_allocations
        relief_pkg = ReliefPkg.query.filter_by(reliefrqst_id=relief_request.reliefrqst_id).first()
        if not relief_pkg:
            raise ValueError('Failed to create relief package')
        
        # OPTIMISTIC LOCKING CHECK: Verify package hasn't been modified by another LO in parallel
        # If package existed before and version_nbr has changed, another user modified it
        if pkg_version_before is not None and relief_pkg.version_nbr != pkg_version_before:
            # Package was modified by another user - they may have submitted it
            # Re-check the creator to see if it's a different LO
            if relief_pkg.status_code == rr_service.PKG_STATUS_PENDING and relief_pkg.create_by_id != session_utils.get_user_name():
                flash('This relief request has already been submitted to the Logistics Manager for approval by another user.', 'warning')
                db.session.rollback()
                return redirect(url_for('packaging.pending_fulfillment'))
        
        # Mark package as submitted for approval (status stays 'P' but we're now in "awaiting LM approval" state)
        # CRITICAL: Set verify_by_id to sentinel value '__PENDING_LM__' to mark as submitted
        # This distinguishes "submitted for approval" from "draft being prepared"
        # LM approval will overwrite this sentinel with the actual LM's username
        relief_pkg.status_code = rr_service.PKG_STATUS_PENDING
        relief_pkg.verify_by_id = '__PENDING_LM__'  # Sentinel: submitted for LM approval
        relief_pkg.verify_dtime = jamaica_now()  # Mark submission time
        relief_pkg.update_by_id = session_utils.get_user_name()
        relief_pkg.update_dtime = jamaica_now()
        relief_pkg.version_nbr += 1
        
        # Change request status to PART_FILLED (submitted for approval)
        relief_request.status_code = rr_service.STATUS_PART_FILLED
        relief_request.action_by_id = session_utils.get_user_name()
        relief_request.action_dtime = jamaica_now()
        relief_request.version_nbr += 1
        
        # Flush to persist allocations before calculating reservation deltas
        db.session.flush()
        
        # Update inventory reservations (pass old allocations for delta calculation)
        old_allocations = relief_request._old_allocations if hasattr(relief_request, '_old_allocations') else {}
        success, error_msg = reservation_service.reserve_inventory(
            relief_request.reliefrqst_id,
            new_allocations,
            old_allocations
        )
        if not success:
            raise ValueError(f'Reservation failed: {error_msg}')
        
        # Notify all Logistics Managers about the pending approval
        # Only send notifications if this is a NEW submission (not a resubmission)
        if not was_already_pending:
            try:
                from app.services.notification_service import NotificationService
                import logging
                logger = logging.getLogger(__name__)
                
                lm_users = NotificationService.get_active_users_by_role_codes(['LOGISTICS_MANAGER'])
                logger.info('Found %s Logistics Manager(s) to notify for relief request #%s', len(lm_users), sanitize_for_log(relief_request.reliefrqst_id))
                
                if lm_users:
                    preparer_name = session_utils.get_display_name()
                    notifications = NotificationService.create_package_ready_for_approval_notification(
                        relief_pkg=relief_pkg,
                        recipient_users=lm_users,
                        preparer_name=preparer_name
                    )
                    logger.info('Created %s notification(s) for LM approval of relief request #%s', len(notifications), sanitize_for_log(relief_request.reliefrqst_id))
                else:
                    logger.warning('No Logistics Managers found to notify for relief request #%s', sanitize_for_log(relief_request.reliefrqst_id))
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.error('Failed to send LM approval notification: %s', sanitize_exception_for_log(e), exc_info=True)
        
        db.session.commit()
        
        flash(f'Relief request #{relief_request.reliefrqst_id} submitted for Logistics Manager approval', 'success')
        return redirect(url_for('packaging.pending_fulfillment'))
        
    except ValueError as e:
        db.session.rollback()
        current_app.logger.warning('Validation error submitting for approval: %s', sanitize_exception_for_log(e))
        flash('A validation error occurred. Please check your input and try again.', 'danger')
        return redirect(url_for('packaging.prepare_package', reliefrqst_id=relief_request.reliefrqst_id))


def _send_for_dispatch(relief_request, relief_request_version, package_version):
    """
    Send package for dispatch (LM only).
    Workflow: LM fulfills directly → Dispatch to Inventory Clerk (bypasses approval)
    """
    from app.core.rbac import is_logistics_manager
    if not is_logistics_manager():
        flash('Only Logistics Managers can send for dispatch', 'danger')
        return redirect(url_for('packaging.prepare_package', reliefrqst_id=relief_request.reliefrqst_id))
    
    try:
        # OPTIMISTIC LOCKING: Validate relief request version
        _validate_version_nbr("relief request", relief_request_version, relief_request.version_nbr)
        
        # OPTIMISTIC LOCKING: Validate package version if it exists
        existing_pkg = ReliefPkg.query.filter_by(reliefrqst_id=relief_request.reliefrqst_id).first()
        if existing_pkg and package_version:
            _validate_version_nbr("package", package_version, existing_pkg.version_nbr)
        
        # Process and validate allocations (must be complete)
        new_allocations = _process_allocations(relief_request, validate_complete=True)
        
        # Get the ReliefPkg that was created/updated by _process_allocations
        relief_pkg = ReliefPkg.query.filter_by(reliefrqst_id=relief_request.reliefrqst_id).first()
        if not relief_pkg:
            raise ValueError('Failed to create relief package')
        
        # LM approval: set verify_by_id to current LM (bypasses LO approval step)
        relief_pkg.verify_by_id = session_utils.get_user_name()
        relief_pkg.verify_dtime = jamaica_now()
        
        # Mark package as dispatched
        relief_pkg.status_code = rr_service.PKG_STATUS_DISPATCHED
        relief_pkg.dispatch_dtime = jamaica_now()
        relief_pkg.update_by_id = session_utils.get_user_name()
        relief_pkg.update_dtime = jamaica_now()
        
        # Flush to persist allocations
        db.session.flush()
        
        # Commit inventory: convert reservations to actual deductions
        success, error_msg = reservation_service.commit_inventory(relief_request.reliefrqst_id)
        if not success:
            raise ValueError(f'Inventory commit failed: {error_msg}')
        
        # Update relief request status
        relief_request.action_by_id = session_utils.get_user_name()
        relief_request.action_dtime = jamaica_now()
        relief_request.status_code = rr_service.STATUS_PART_FILLED
        relief_request.version_nbr += 1
        
        # Notify agency users and logistics managers about dispatch
        try:
            from app.services.notification_service import NotificationService
            
            # Notify agency users
            agency_users = []
            if relief_request.agency_id:
                agency_users = NotificationService.get_agency_active_users(relief_request.agency_id)
            
            # Optionally notify logistics managers
            lm_users = NotificationService.get_active_users_by_role_codes(['LOGISTICS_MANAGER'])
            
            all_recipients = agency_users + lm_users
            dispatcher_name = session_utils.get_display_name()
            
            NotificationService.create_package_dispatched_notification(
                relief_pkg=relief_pkg,
                recipient_users=all_recipients,
                dispatcher_name=dispatcher_name
            )
        except Exception as e:
            # Don't fail dispatch if notification fails
            import logging
            logger = logging.getLogger(__name__)
            logger.warning('Failed to send dispatch notification: %s', sanitize_exception_for_log(e))
        
        db.session.commit()
        
        flash(f'Relief request #{relief_request.reliefrqst_id} sent for dispatch', 'success')
        return redirect(url_for('packaging.pending_fulfillment'))
        
    except ValueError as e:
        db.session.rollback()
        current_app.logger.warning('Validation error sending for dispatch: %s', sanitize_exception_for_log(e))
        flash('A validation error occurred. Please check your input and try again.', 'danger')
        return redirect(url_for('packaging.prepare_package', reliefrqst_id=relief_request.reliefrqst_id))


def _process_allocations(relief_request, validate_complete=False):
    """
    Process batch-level allocations from form data.
    Updates issue_qty and item status codes, and persists allocations to ReliefPkgItem.
    
    Args:
        relief_request: The ReliefRqst being packaged
        validate_complete: If True, ensures all items are fully allocated
    
    Returns:
        List of new allocations for inventory reservation
    """
    new_allocations = []
    
    # Get or create ReliefPkg for this relief request
    relief_pkg = ReliefPkg.query.filter_by(reliefrqst_id=relief_request.reliefrqst_id).first()
    if not relief_pkg:
        # Generate tracking number (7-char uppercase from UUID, matching database default)
        tracking_no = str(uuid.uuid4()).replace('-', '').upper()[:7]
        
        # Create a new relief package for tracking allocations
        # NOTE: verify_by_id and received_by_id are NOT set for drafts
        # They will be set when package is submitted for approval or dispatched
        relief_pkg = ReliefPkg(
            agency_id=relief_request.agency_id,
            tracking_no=tracking_no,
            reliefrqst_id=relief_request.reliefrqst_id,
            to_inventory_id=1,  # Placeholder, will be updated on dispatch
            start_date=date.today(),
            status_code='P',  # Preparing
            create_by_id=session_utils.get_user_name(),
            create_dtime=jamaica_now(),
            update_by_id=session_utils.get_user_name(),
            update_dtime=jamaica_now(),
            verify_by_id=None,  # NULL for drafts, set when submitted for approval
            received_by_id=None,  # NULL until package is received
            version_nbr=1
        )
        db.session.add(relief_pkg)
        db.session.flush()  # Get the reliefpkg_id
    
    # CRITICAL: Capture existing allocations BEFORE modification for reservation delta calculation
    existing_pkg_items = ReliefPkgItem.query.filter_by(reliefpkg_id=relief_pkg.reliefpkg_id).all()
    existing_allocations_map = {}
    existing_records_map = {}  # Map composite key to ReliefPkgItem object for upsert logic
    items_with_existing_pkg_records = set()  # Track which items have allocation activity
    for pkg_item in existing_pkg_items:
        # Track by (item_id, inventory_id, batch_id) for batch-level reservations
        # fr_inventory_id IS the warehouse_id (inventory_id in the composite PK)
        key = (pkg_item.item_id, pkg_item.fr_inventory_id, pkg_item.batch_id)
        existing_allocations_map[key] = pkg_item.item_qty
        # Store the actual object for upsert logic (respecting composite PK)
        # Composite key: (reliefpkg_id, fr_inventory_id, batch_id, item_id)
        record_key = (pkg_item.reliefpkg_id, pkg_item.fr_inventory_id, pkg_item.batch_id, pkg_item.item_id)
        existing_records_map[record_key] = pkg_item
        # Track items that have ReliefPkgItem records (allocation activity)
        items_with_existing_pkg_records.add(pkg_item.item_id)
    
    # Store old allocations on relief_request object for access in save/submit functions
    relief_request._old_allocations = existing_allocations_map
    
    # Track which records we're keeping/updating (to delete orphaned records later)
    processed_record_keys = set()
    
    for item in relief_request.items:
        item_id = item.item_id
        request_qty = item.request_qty
        
        total_allocated = Decimal('0')
        batch_allocations = []
        
        # Look for batch allocation keys: batch_allocation_{item_id}_{batch_id}
        allocation_keys = [k for k in request.form.keys() if k.startswith(f'batch_allocation_{item_id}_')]
        
        # Sort keys to ensure deterministic locking order (prevent deadlocks)
        allocation_keys = sorted(allocation_keys)
        
        for key in allocation_keys:
            parts = key.split('_')
            if len(parts) >= 4:
                from app.security.param_validation import safe_id, safe_quantity
                
                batch_id = safe_id(parts[3])
                if batch_id <= 0:
                    continue  # Skip invalid batch IDs
                allocated_qty = safe_quantity(request.form.get(key) or '0')
                
                # Get batch details first (needed for warehouse_id and validation)
                batch = ItemBatch.query.options(
                    joinedload(ItemBatch.inventory).joinedload(Inventory.warehouse)
                ).get(batch_id)
                
                if not batch:
                    raise ValueError(f'Batch {batch_id} not found')
                
                # Look up current allocation for this batch from existing package
                # Key: (item_id, inventory_id, batch_id)
                existing_key = (item_id, batch.inventory_id, batch_id)
                current_allocated_qty = existing_allocations_map.get(existing_key, Decimal('0'))
                
                # Validate batch allocation (with "release" logic for re-allocation)
                if allocated_qty > 0:
                    is_valid, error_msg = BatchAllocationService.validate_batch_allocation(
                        batch_id, item_id, allocated_qty, current_allocated_qty
                    )
                    if not is_valid:
                        raise ValueError(error_msg)
                
                total_allocated += allocated_qty
                # CRITICAL: Include zero-qty allocations to track drawer activity
                # This ensures ReliefPkgItem records persist even when qty=0
                batch_allocations.append((batch_id, batch.inventory_id, allocated_qty, batch.uom_code))
                
                # Collect for reservation service (only non-zero allocations)
                if allocated_qty > 0:
                    new_allocations.append({
                        'item_id': item_id,
                        'batch_id': batch_id,
                        'warehouse_id': batch.inventory.inventory_id,
                        'allocated_qty': allocated_qty
                    })
        
        # Validate quantity limit using service
        is_valid, error_msg = item_status_service.validate_quantity_limit(
            item_id, total_allocated, request_qty
        )
        if not is_valid:
            raise ValueError(error_msg)
        
        # Get requested status from form, or use calculated status
        form_status = request.form.get(f'status_{item_id}')
        
        # Check if item has status that allows partial allocation
        # U, D, W: Unavailable items (zero allocation allowed)
        # L, P: Partial fulfillment items (partial allocation allowed)
        partial_allocation_statuses = {'U', 'D', 'W', 'L', 'P'}
        allows_partial = form_status in partial_allocation_statuses if form_status else False
        
        # Validate completeness only if status doesn't explicitly allow partial allocation
        if validate_complete and total_allocated < request_qty and not allows_partial:
            raise ValueError(f'Item {item.item.item_name} is not fully allocated ({total_allocated} of {request_qty})')
        
        # Determine the correct status based on allocation
        # CRITICAL: Status must match issue_qty to satisfy database constraints
        if total_allocated == Decimal('0'):
            # No allocation -> Requested
            calculated_status = 'R'
        elif total_allocated >= request_qty:
            # Fully allocated -> Filled
            calculated_status = 'F'
        else:
            # Partially allocated -> Partly Filled
            calculated_status = 'P'
        
        # Use form_status already retrieved above, or use calculated status
        if form_status:
            # Explicit status provided in form (manual override)
            requested_status = form_status
        else:
            # No explicit status - use calculated status
            requested_status = calculated_status
        
        # Get custom reason if provided (for D/L statuses)
        custom_reason = request.form.get(f'status_reason_{item_id}', '').strip()
        
        # Determine if item has allocation activity
        # CRITICAL: Check database for existing records OR form keys
        # This prevents bypassing validation by manipulating form data
        has_allocation_activity = (
            item_id in items_with_existing_pkg_records or  # Database check (persisted records)
            len(allocation_keys) > 0  # Form check (current submission)
        )
        
        # Validate status transition using service
        is_valid, error_msg = item_status_service.validate_status_transition(
            item_id,
            item.status_code,
            requested_status,
            total_allocated,
            request_qty,
            has_allocation_activity
        )
        if not is_valid:
            raise ValueError(error_msg)
        
        # Update relief request item fields - MUST be done atomically
        # Set status first to ensure constraint satisfaction
        item.status_code = requested_status
        
        # Set issue_qty based on status code according to constraint c_reliefrqst_item_2a:
        # - R, U, W, D: issue_qty must be 0
        # - P, L: issue_qty must be < request_qty
        # - F: issue_qty must equal request_qty
        if requested_status in ['R', 'U', 'W', 'D']:
            item.issue_qty = 0
        elif requested_status in ['P', 'L']:
            # Partial fill - use allocated amount (must be < request_qty)
            item.issue_qty = min(total_allocated, item.request_qty - Decimal('0.01'))
        elif requested_status == 'F':
            # Fully filled - must equal request_qty
            item.issue_qty = item.request_qty
        else:
            # Default: set to allocated amount
            item.issue_qty = total_allocated
        
        # Set status_reason_desc for statuses that require it (D, L)
        if requested_status in ['D', 'L']:
            # Use custom reason if provided, otherwise use defaults
            if custom_reason:
                item.status_reason_desc = custom_reason
            elif requested_status == 'L':
                item.status_reason_desc = f'Allocated {total_allocated} of {request_qty} based on available stock'
            elif requested_status == 'D':
                item.status_reason_desc = 'Item denied due to logistics constraints'
        else:
            # Clear reason for other statuses
            item.status_reason_desc = None
        
        # Only set action_by_id when status is NOT 'R' (per constraint c_reliefrqst_item_7)
        if requested_status != 'R':
            item.action_by_id = session_utils.get_user_name()
            item.action_dtime = jamaica_now()
        else:
            # When status is 'R', action_by_id must be NULL
            item.action_by_id = None
            item.action_dtime = None
        
        item.version_nbr += 1
        
        # Create or update ReliefPkgItem records for each batch allocation (including zero-qty)
        # CRITICAL: Zero-qty records serve as markers that the drawer was opened/used
        # This ensures has_allocation_activity persists across page reloads
        # UPSERT LOGIC: Respect composite PK (reliefpkg_id, fr_inventory_id, batch_id, item_id)
        for batch_id, inventory_id, allocated_qty, uom_code in batch_allocations:
            # Composite primary key for this allocation
            record_key = (relief_pkg.reliefpkg_id, inventory_id, batch_id, item_id)
            
            # Check if record already exists
            if record_key in existing_records_map:
                # UPDATE existing record
                pkg_item = existing_records_map[record_key]
                pkg_item.item_qty = allocated_qty
                pkg_item.uom_code = uom_code
                pkg_item.update_by_id = session_utils.get_user_name()
                pkg_item.update_dtime = jamaica_now()
                pkg_item.version_nbr += 1
            else:
                # INSERT new record
                pkg_item = ReliefPkgItem(
                    reliefpkg_id=relief_pkg.reliefpkg_id,
                    fr_inventory_id=inventory_id,
                    item_id=item_id,
                    batch_id=batch_id,  # REQUIRED in new schema
                    item_qty=allocated_qty,  # Can be zero
                    uom_code=uom_code,
                    create_by_id=session_utils.get_user_name(),
                    create_dtime=jamaica_now(),
                    update_by_id=session_utils.get_user_name(),
                    update_dtime=jamaica_now(),
                    version_nbr=1
                )
                db.session.add(pkg_item)
            
            # Track that we processed this record (keep it, don't delete)
            processed_record_keys.add(record_key)
    
    # Delete orphaned records (allocations removed by user)
    # These are records that exist in the database but weren't in the new form submission
    for record_key, pkg_item in existing_records_map.items():
        if record_key not in processed_record_keys:
            # This record was not processed (user removed this allocation)
            db.session.delete(pkg_item)
    
    return new_allocations




@packaging_bp.route('/<int:reliefrqst_id>/cancel', methods=['POST'])
@login_required
def cancel_preparation(reliefrqst_id):
    """
    Cancel package preparation - discards all changes, releases inventory reservations and lock.
    Does NOT save any draft.
    """
    try:
        # Get the relief package for this request (if it exists)
        relief_pkg = ReliefPkg.query.filter_by(reliefrqst_id=reliefrqst_id).first()
        
        if relief_pkg:
            # Delete all relief package items (discard any draft allocations)
            ReliefPkgItem.query.filter_by(reliefpkg_id=relief_pkg.reliefpkg_id).delete()
            db.session.flush()
        
        # Release inventory reservations
        success, error_msg = reservation_service.release_all_reservations(reliefrqst_id)
        if not success:
            flash(f'Warning: Failed to release reservations: {error_msg}', 'warning')
        
        # Commit the deletion of package items
        db.session.commit()
        
        flash(f'Package preparation for relief request #{reliefrqst_id} has been cancelled', 'info')
        return redirect(url_for('packaging.pending_fulfillment'))
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error canceling preparation')
        flash('An error occurred while canceling the preparation. Please try again.', 'danger')
        return redirect(url_for('packaging.prepare_package', reliefrqst_id=reliefrqst_id))


@packaging_bp.route('/api/inventory/<int:item_id>/<int:warehouse_id>')
@login_required
def get_inventory(item_id, warehouse_id):
    """API endpoint to get current inventory for an item at a warehouse.
    Note: warehouse_id is stored as inventory_id in the composite PK."""
    inventory = Inventory.query.filter_by(
        item_id=item_id,
        inventory_id=warehouse_id,  # Use inventory_id (which IS the warehouse_id)
        status_code='A'
    ).first()
    
    if inventory:
        return jsonify({
            'usable_qty': float(inventory.usable_qty or 0),
            'reserved_qty': float(inventory.reserved_qty or 0),
            'defective_qty': float(inventory.defective_qty or 0)
        })
    else:
        return jsonify({
            'usable_qty': 0,
            'reserved_qty': 0,
            'defective_qty': 0
        })


@packaging_bp.route('/api/item/<int:item_id>/batches')
@login_required
def get_item_batches(item_id):
    """
    API endpoint to get available batches for an item.
    Returns limited batch list (minimum needed to fulfill) with priority groups.
    Supports new drawer workflow requirements.
    """
    try:
        # Get query parameters
        remaining_qty = request.args.get('remaining_qty', type=float)
        required_uom = request.args.get('required_uom', type=str)
        allocated_batch_ids_str = request.args.get('allocated_batch_ids', type=str)
        current_allocations_str = request.args.get('current_allocations', type=str)
        
        # Parse allocated batch IDs from comma-separated string
        allocated_batch_ids = []
        if allocated_batch_ids_str:
            try:
                allocated_batch_ids = [int(bid) for bid in allocated_batch_ids_str.split(',') if bid.strip()]
            except ValueError:
                pass  # Ignore invalid batch IDs
        
        # Parse current allocations from JSON (batch_id -> quantity mapping)
        current_allocations = {}
        if current_allocations_str:
            try:
                import json
                current_allocations = json.loads(current_allocations_str)
                # Convert keys to int and values to Decimal (JSON keys are strings)
                current_allocations = {int(k): safe_decimal(v) for k, v in current_allocations.items()}
            except (ValueError, json.JSONDecodeError):
                pass  # Ignore invalid JSON
        
        # Get item to check if it's batched
        item = Item.query.get(item_id)
        if not item:
            return jsonify({'error': 'Item not found'}), 404
        
        # Use new method to get limited batches if remaining_qty provided
        # Include remaining_qty=0 case for editing existing allocations
        if remaining_qty is not None:
            limited_batches, total_available, shortfall = BatchAllocationService.get_limited_batches_for_drawer(
                item_id,
                safe_decimal(remaining_qty),
                required_uom,
                allocated_batch_ids,
                current_allocations
            )
            
            
            # Assign priority groups
            batch_groups = BatchAllocationService.assign_priority_groups(limited_batches, item)
            
            # Format batches with priority groups
            result = []
            for batch, priority_group in batch_groups:
                # Calculate available_qty: release current package's allocations from reserved_qty
                released_qty = current_allocations.get(batch.batch_id, Decimal('0'))
                available_qty = safe_decimal(batch.usable_qty) - (safe_decimal(batch.reserved_qty) - released_qty)
                batch_info = {
                    'batch_id': batch.batch_id,
                    'batch_no': batch.batch_no,
                    'batch_date': batch.batch_date.isoformat() if batch.batch_date else None,
                    'expiry_date': batch.expiry_date.isoformat() if batch.expiry_date else None,
                    'warehouse_id': batch.inventory.inventory_id,
                    'warehouse_name': batch.inventory.warehouse.warehouse_name,
                    'inventory_id': batch.inventory_id,
                    'usable_qty': float(safe_decimal(batch.usable_qty)),
                    'reserved_qty': float(safe_decimal(batch.reserved_qty)),
                    'available_qty': float(available_qty),
                    'defective_qty': float(safe_decimal(batch.defective_qty)),
                    'expired_qty': float(safe_decimal(batch.expired_qty)),
                    'uom_code': batch.uom_code,
                    'size_spec': batch.size_spec,
                    'is_expired': batch.is_expired,
                    'status_code': batch.status_code,
                    'priority_group': priority_group
                }
                result.append(batch_info)
            
            return jsonify({
                'item_id': item_id,
                'item_name': item.item_name,
                'is_batched': item.is_batched_flag,
                'can_expire': item.can_expire_flag,
                'issuance_order': item.issuance_order,
                'batches': result,
                'total_available': float(safe_decimal(total_available)),
                'shortfall': float(safe_decimal(shortfall)),
                'can_fulfill': safe_decimal(shortfall) == 0
            })
        else:
            # Legacy mode: return all batches grouped by warehouse (for backward compatibility)
            warehouse_batches = BatchAllocationService.get_batches_by_warehouse(item_id)
            
            result = {}
            for wh_id, batch_list in warehouse_batches.items():
                result[wh_id] = []
                for batch in batch_list:
                    available_qty = safe_decimal(batch.usable_qty) - safe_decimal(batch.reserved_qty)
                    result[wh_id].append({
                        'batch_id': batch.batch_id,
                        'batch_no': batch.batch_no,
                        'batch_date': batch.batch_date.isoformat() if batch.batch_date else None,
                        'expiry_date': batch.expiry_date.isoformat() if batch.expiry_date else None,
                        'warehouse_id': batch.inventory.inventory_id,
                        'warehouse_name': batch.inventory.warehouse.warehouse_name,
                        'inventory_id': batch.inventory_id,
                        'usable_qty': float(safe_decimal(batch.usable_qty)),
                        'reserved_qty': float(safe_decimal(batch.reserved_qty)),
                        'available_qty': float(available_qty),
                        'defective_qty': float(safe_decimal(batch.defective_qty)),
                        'expired_qty': float(safe_decimal(batch.expired_qty)),
                        'uom_code': batch.uom_code,
                        'size_spec': batch.size_spec,
                        'is_expired': batch.is_expired,
                        'status_code': batch.status_code
                    })
            
            return jsonify({
                'item_id': item_id,
                'item_name': item.item_name,
                'is_batched': item.is_batched_flag,
                'can_expire': item.can_expire_flag,
                'issuance_order': item.issuance_order,
                'batches': result
            })
        
    except Exception as e:
        current_app.logger.exception('Error fetching item batches')
        return jsonify({'error': 'An error occurred while fetching batch data. Please try again.'}), 500


@packaging_bp.route('/api/item/<int:item_id>/auto-allocate', methods=['POST'])
@login_required
def auto_allocate_item(item_id):
    """
    API endpoint to auto-allocate batches for an item using FEFO/FIFO rules.
    
    Expected JSON payload:
    {
        "requested_qty": 100,
        "warehouse_id": 1  # optional
    }
    """
    try:
        data = request.get_json()
        requested_qty = safe_decimal(data.get('requested_qty', 0))
        warehouse_id = data.get('warehouse_id')
        
        if requested_qty <= 0:
            return jsonify({'error': 'Requested quantity must be greater than zero'}), 400
        
        # Get auto-allocations
        allocations = BatchAllocationService.auto_allocate_batches(
            item_id,
            requested_qty,
            warehouse_id
        )
        
        # Calculate totals
        total_allocated = sum(safe_decimal(a['allocated_qty']) for a in allocations)
        shortage = requested_qty - total_allocated if total_allocated < requested_qty else Decimal('0')
        
        return jsonify({
            'item_id': item_id,
            'requested_qty': float(requested_qty),
            'total_allocated': float(total_allocated),
            'shortage': float(shortage),
            'allocations': allocations
        })
        
    except Exception as e:
        current_app.logger.exception('Error auto-allocating item batches')
        return jsonify({'error': 'An error occurred during auto-allocation. Please try again.'}), 500


@packaging_bp.route('/api/batch/<int:batch_id>')
@login_required
def get_batch_details(batch_id):
    """API endpoint to get detailed information about a specific batch"""
    try:
        batch_details = BatchAllocationService.get_batch_details(batch_id)
        
        if not batch_details:
            return jsonify({'error': 'Batch not found'}), 404
        
        # Convert date objects to ISO format for JSON
        if batch_details.get('batch_date'):
            batch_details['batch_date'] = batch_details['batch_date'].isoformat()
        if batch_details.get('expiry_date'):
            batch_details['expiry_date'] = batch_details['expiry_date'].isoformat()
        
        return jsonify(batch_details)
        
    except Exception as e:
        current_app.logger.exception('Error fetching batch details')
        return jsonify({'error': 'An error occurred while fetching batch details. Please try again.'}), 500


# ==================== INVENTORY CLERK DISPATCH ROUTES ====================

@packaging_bp.route('/dispatch/awaiting')
@login_required
def awaiting_dispatch():
    """
    Inventory Clerk - Awaiting Dispatch page.
    Shows packages approved by LM and dispatched, filtered by clerk's warehouse(s).
    Only displays items allocated from warehouses the clerk has access to.
    """
    from app.core.rbac import has_role
    
    if not has_role('INVENTORY_CLERK'):
        flash('Access denied. This page is for Inventory Clerks only.', 'danger')
        abort(403)
    
    # Get user's assigned warehouses
    user_warehouse_ids = session_utils.get_warehouse_ids()
    
    if not user_warehouse_ids:
        flash('You have not been assigned to any warehouses. Please contact your administrator.', 'warning')
        return render_template('packaging/awaiting_dispatch.html', 
                             packages=[], 
                             counts={}, 
                             current_filter='awaiting',
                             global_counts={})
    
    # Get filter parameter
    current_filter = request.args.get('filter', 'awaiting')
    
    # Query packages that are dispatched (status='D') but not yet completed
    # Filter to show only packages with items from clerk's warehouse(s)
    from sqlalchemy import func, exists
    
    base_query = db.session.query(ReliefPkg).options(
        joinedload(ReliefPkg.relief_request).joinedload(ReliefRqst.agency),
        joinedload(ReliefPkg.relief_request).joinedload(ReliefRqst.eligible_event),
        joinedload(ReliefPkg.items)
    ).join(ReliefRqst).filter(
        ReliefPkg.status_code == rr_service.PKG_STATUS_DISPATCHED,
        # Only show packages with items from clerk's warehouses
        exists().where(
            and_(
                ReliefPkgItem.reliefpkg_id == ReliefPkg.reliefpkg_id,
                ReliefPkgItem.fr_inventory_id.in_(user_warehouse_ids)
            )
        )
    )
    
    # Apply filters
    if current_filter == 'awaiting':
        # Not yet handed over (no received_dtime)
        packages = base_query.filter(ReliefPkg.received_dtime == None).order_by(
            ReliefPkg.dispatch_dtime.desc()
        ).all()
    elif current_filter == 'completed':
        # Already handed over (has received_dtime)
        packages = base_query.filter(ReliefPkg.received_dtime != None).order_by(
            ReliefPkg.received_dtime.desc()
        ).all()
    else:  # 'all'
        packages = base_query.order_by(ReliefPkg.dispatch_dtime.desc()).all()
    
    # Calculate counts for filter tabs
    global_counts = {
        'awaiting': base_query.filter(ReliefPkg.received_dtime == None).count(),
        'completed': base_query.filter(ReliefPkg.received_dtime != None).count(),
    }
    global_counts['all'] = global_counts['awaiting'] + global_counts['completed']
    
    # For each package, calculate totals specific to this clerk's warehouses
    package_data = []
    for pkg in packages:
        # Count items and total qty for this clerk's warehouses only
        warehouse_items = [item for item in pkg.items if item.fr_inventory_id in user_warehouse_ids]
        
        package_data.append({
            'package': pkg,
            'relief_request': pkg.relief_request,
            'item_count': len(warehouse_items),
            'total_qty': sum(item.item_qty for item in warehouse_items if item.item_qty),
            'warehouse_items': warehouse_items
        })
    
    counts = global_counts.copy()
    
    return render_template('packaging/awaiting_dispatch.html',
                         packages=package_data,
                         counts=counts,
                         current_filter=current_filter,
                         global_counts=global_counts,
                         user_warehouse_ids=user_warehouse_ids)


@packaging_bp.route('/dispatch/<int:reliefpkg_id>/details')
@login_required
def dispatch_details(reliefpkg_id):
    """
    Dispatch Details page for Inventory Clerk.
    Shows package details for items from clerk's warehouse(s) only.
    Includes print-friendly layout option.
    """
    from app.core.rbac import has_role
    
    if not has_role('INVENTORY_CLERK'):
        flash('Access denied. This page is for Inventory Clerks only.', 'danger')
        abort(403)
    
    # Get user's assigned warehouses
    user_warehouse_ids = session_utils.get_warehouse_ids()
    
    if not user_warehouse_ids:
        flash('You have not been assigned to any warehouses.', 'warning')
        return redirect(url_for('packaging.awaiting_dispatch'))
    
    # Load package with all necessary relationships
    relief_pkg = ReliefPkg.query.options(
        joinedload(ReliefPkg.relief_request).joinedload(ReliefRqst.agency),
        joinedload(ReliefPkg.relief_request).joinedload(ReliefRqst.eligible_event),
        joinedload(ReliefPkg.relief_request).joinedload(ReliefRqst.items).joinedload(ReliefRqstItem.item),
        joinedload(ReliefPkg.items).joinedload(ReliefPkgItem.item),
        joinedload(ReliefPkg.items).joinedload(ReliefPkgItem.batch)
    ).get_or_404(reliefpkg_id)
    
    # Verify package is dispatched
    if relief_pkg.status_code != rr_service.PKG_STATUS_DISPATCHED:
        flash('This package is not in dispatched status.', 'warning')
        return redirect(url_for('packaging.awaiting_dispatch'))
    
    # Filter items to only those from clerk's warehouses
    warehouse_items = [item for item in relief_pkg.items if item.fr_inventory_id in user_warehouse_ids]
    
    if not warehouse_items:
        flash('This package has no items allocated from your assigned warehouses.', 'warning')
        return redirect(url_for('packaging.awaiting_dispatch'))
    
    # Group items by warehouse for display
    from collections import defaultdict
    items_by_warehouse = defaultdict(list)
    for item in warehouse_items:
        items_by_warehouse[item.fr_inventory_id].append(item)
    
    # Get warehouse objects
    warehouses = {w.warehouse_id: w for w in Warehouse.query.filter(
        Warehouse.warehouse_id.in_(user_warehouse_ids)
    ).all()}
    
    # Check if print mode
    print_mode = request.args.get('print', '0') == '1'
    
    return render_template('packaging/dispatch_details.html',
                         relief_pkg=relief_pkg,
                         relief_request=relief_pkg.relief_request,
                         warehouse_items=warehouse_items,
                         items_by_warehouse=items_by_warehouse,
                         warehouses=warehouses,
                         print_mode=print_mode)


@packaging_bp.route('/dispatch/<int:reliefpkg_id>/handover', methods=['POST'])
@login_required
def mark_handover(reliefpkg_id):
    """
    Mark dispatch as handed over to agency.
    Inventory Clerk confirms that items have been physically given to the agency.
    Updates status, triggers notifications to LO/LM.
    """
    from app.core.rbac import has_role
    from app.services.notification_service import NotificationService
    
    if not has_role('INVENTORY_CLERK'):
        flash('Access denied. Only Inventory Clerks can mark handovers.', 'danger')
        abort(403)
    
    # Get user's assigned warehouses
    user_warehouse_ids = session_utils.get_warehouse_ids()
    
    if not user_warehouse_ids:
        flash('You have not been assigned to any warehouses.', 'warning')
        return redirect(url_for('packaging.awaiting_dispatch'))
    
    # Load package
    relief_pkg = ReliefPkg.query.options(
        joinedload(ReliefPkg.relief_request).joinedload(ReliefRqst.agency),
        joinedload(ReliefPkg.items)
    ).get_or_404(reliefpkg_id)
    
    # Verify package is dispatched and not already handed over
    if relief_pkg.status_code != rr_service.PKG_STATUS_DISPATCHED:
        flash('This package is not in dispatched status.', 'warning')
        return redirect(url_for('packaging.awaiting_dispatch'))
    
    if relief_pkg.received_dtime:
        flash('This package has already been marked as handed over.', 'info')
        return redirect(url_for('packaging.dispatch_details', reliefpkg_id=reliefpkg_id))
    
    # Verify clerk has items from their warehouse in this package
    warehouse_items = [item for item in relief_pkg.items if item.fr_inventory_id in user_warehouse_ids]
    
    if not warehouse_items:
        flash('This package has no items from your assigned warehouses.', 'warning')
        return redirect(url_for('packaging.awaiting_dispatch'))
    
    try:
        # Mark as received/handed over
        relief_pkg.received_by_id = session_utils.get_user_name()
        relief_pkg.received_dtime = jamaica_now()
        relief_pkg.update_by_id = session_utils.get_user_name()
        relief_pkg.update_dtime = jamaica_now()
        
        # Note: Status remains 'D' (Dispatched). We use received_dtime to track handover.
        # Status changes to 'C' (Completed) when agency signs off, if needed.
        
        db.session.commit()
        
        # Send notifications to LO and LM
        try:
            # Get all logistics officers and managers
            lo_users = User.query.filter(User.roles.like('%LOGISTICS_OFFICER%')).all()
            lm_users = User.query.filter(User.roles.like('%LOGISTICS_MANAGER%')).all()
            all_recipients = lo_users + lm_users
            
            if all_recipients:
                # Get warehouse names for notification
                warehouse_names = [w.warehouse_name for w in Warehouse.query.filter(
                    Warehouse.warehouse_id.in_(user_warehouse_ids)
                ).all()]
                warehouse_list = ', '.join(warehouse_names)
                
                agency_name = relief_pkg.relief_request.agency.agency_name if relief_pkg.relief_request.agency else 'Unknown Agency'
                
                for user in all_recipients:
                    notification = Notification(
                        user_id=user.user_id,
                        reliefrqst_id=relief_pkg.reliefrqst_id,
                        title='Package Handed Over to Agency',
                        message=f'Package for {agency_name} (RR-{relief_pkg.reliefrqst_id:06d}) has been handed over from warehouse: {warehouse_list}',
                        type='package_handover',
                        status='unread',
                        link_url=url_for('packaging.dispatch_received_details', reliefpkg_id=relief_pkg.reliefpkg_id, _external=False),
                        is_archived=False
                    )
                    db.session.add(notification)
                
                db.session.commit()
        except Exception as e:
            # Log error but don't fail the handover
            import logging
            logger = logging.getLogger(__name__)
            logger.warning('Failed to send handover notification: %s', sanitize_exception_for_log(e))
        
        flash(f'Package successfully marked as handed over to {relief_pkg.relief_request.agency.agency_name if relief_pkg.relief_request.agency else "agency"}.', 'success')
        return redirect(url_for('packaging.awaiting_dispatch', filter='completed'))
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error marking handover')
        flash('An error occurred while marking the handover. Please try again.', 'danger')
        return redirect(url_for('packaging.dispatch_details', reliefpkg_id=reliefpkg_id))


# ==================== LO/LM DISPATCH RECEIVED QUEUE ====================

@packaging_bp.route('/dispatch/received')
@login_required
def dispatch_received():
    """
    Logistics Officer/Manager - Dispatch Received queue.
    Shows packages that have been handed over by Inventory Clerks.
    Read-only view for tracking completed dispatches.
    """
    from app.core.rbac import has_role
    
    if not (has_role('LOGISTICS_OFFICER') or has_role('LOGISTICS_MANAGER')):
        flash('Access denied. This page is for Logistics Officers and Managers only.', 'danger')
        abort(403)
    
    # Get filter parameter
    current_filter = request.args.get('filter', 'recent')
    
    # Query packages that have been handed over (have received_dtime)
    base_query = db.session.query(ReliefPkg).options(
        joinedload(ReliefPkg.relief_request).joinedload(ReliefRqst.agency),
        joinedload(ReliefPkg.relief_request).joinedload(ReliefRqst.eligible_event),
        joinedload(ReliefPkg.items).joinedload(ReliefPkgItem.item),
        joinedload(ReliefPkg.items).joinedload(ReliefPkgItem.batch)
    ).join(ReliefRqst).filter(
        ReliefPkg.status_code == rr_service.PKG_STATUS_DISPATCHED,
        ReliefPkg.received_dtime != None  # Has been handed over
    )
    
    # Apply filters
    if current_filter == 'recent':
        # Last 30 days
        from datetime import timedelta
        cutoff_date = jamaica_now() - timedelta(days=30)
        packages = base_query.filter(
            ReliefPkg.received_dtime >= cutoff_date
        ).order_by(ReliefPkg.received_dtime.desc()).all()
    else:  # 'all'
        packages = base_query.order_by(ReliefPkg.received_dtime.desc()).all()
    
    # Calculate counts
    from datetime import timedelta
    cutoff_date = jamaica_now() - timedelta(days=30)
    global_counts = {
        'recent': base_query.filter(ReliefPkg.received_dtime >= cutoff_date).count(),
        'all': base_query.count()
    }
    
    # Prepare package data with warehouse information
    package_data = []
    for pkg in packages:
        # Get unique warehouses for this package
        warehouse_ids = set(item.fr_inventory_id for item in pkg.items if item.fr_inventory_id)
        warehouses = Warehouse.query.filter(Warehouse.warehouse_id.in_(warehouse_ids)).all() if warehouse_ids else []
        warehouse_names = [w.warehouse_name for w in warehouses]
        
        package_data.append({
            'package': pkg,
            'relief_request': pkg.relief_request,
            'warehouse_names': ', '.join(warehouse_names) if warehouse_names else 'N/A',
            'item_count': len(pkg.items),
            'total_qty': sum(item.item_qty for item in pkg.items if item.item_qty)
        })
    
    counts = global_counts.copy()
    
    return render_template('packaging/dispatch_received.html',
                         packages=package_data,
                         counts=counts,
                         current_filter=current_filter,
                         global_counts=global_counts)


@packaging_bp.route('/dispatch/<int:reliefpkg_id>/received-details')
@login_required
def dispatch_received_details(reliefpkg_id):
    """
    Read-only dispatch details for LO/LM.
    Shows complete package information after handover by Inventory Clerk.
    """
    from app.core.rbac import has_role
    
    if not (has_role('LOGISTICS_OFFICER') or has_role('LOGISTICS_MANAGER')):
        flash('Access denied. This page is for Logistics Officers and Managers only.', 'danger')
        abort(403)
    
    # Load package with all relationships
    relief_pkg = ReliefPkg.query.options(
        joinedload(ReliefPkg.relief_request).joinedload(ReliefRqst.agency),
        joinedload(ReliefPkg.relief_request).joinedload(ReliefRqst.eligible_event),
        joinedload(ReliefPkg.relief_request).joinedload(ReliefRqst.items).joinedload(ReliefRqstItem.item),
        joinedload(ReliefPkg.items).joinedload(ReliefPkgItem.item),
        joinedload(ReliefPkg.items).joinedload(ReliefPkgItem.batch)
    ).get_or_404(reliefpkg_id)
    
    # Verify package has been handed over
    if not relief_pkg.received_dtime:
        flash('This package has not been handed over yet.', 'warning')
        return redirect(url_for('packaging.dispatch_received'))
    
    # Group items by warehouse
    from collections import defaultdict
    items_by_warehouse = defaultdict(list)
    for item in relief_pkg.items:
        if item.fr_inventory_id:
            items_by_warehouse[item.fr_inventory_id].append(item)
    
    # Get warehouse objects
    warehouse_ids = set(item.fr_inventory_id for item in relief_pkg.items if item.fr_inventory_id)
    warehouses = {w.warehouse_id: w for w in Warehouse.query.filter(
        Warehouse.warehouse_id.in_(warehouse_ids)
    ).all()} if warehouse_ids else {}
    
    return render_template('packaging/dispatch_received_details.html',
                         relief_pkg=relief_pkg,
                         relief_request=relief_pkg.relief_request,
                         items_by_warehouse=items_by_warehouse,
                         warehouses=warehouses)
