"""
Donation Intake Blueprint

Handles the intake of verified donations into warehouse inventory.
Implements a two-stage workflow:
  - Entry (Workflow A): LOGISTICS_OFFICER creates/edits intakes
  - Verification (Workflow B): LOGISTICS_MANAGER verifies and commits to inventory

Key Features:
- Select verified donations (status='V')
- Filter only GOODS items (category_type='GOODS')
- Choose target warehouse/inventory
- Create dnintake headers with status I (draft) or C (submitted)
- Verification updates itembatch and inventory with optimistic locking
- Mark donations as Processed only after verification

Author: DRIMS Development Team
Date: 2025-11-18
Updated: 2025-11-25 - Added Entry/Verification workflow separation
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from sqlalchemy import or_, and_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from decimal import Decimal, InvalidOperation
from datetime import datetime, date, timedelta

from app.db import db
from app.security.audit_logger import log_data_event, AuditAction, AuditOutcome
from app.utils.timezone import now as jamaica_now
from app.db.models import (
    Donation, DonationItem, DonationIntake, DonationIntakeItem,
    Item, ItemCategory, ItemBatch, Warehouse, Inventory, UnitOfMeasure
)
from app.core.decorators import feature_required
from app.core.audit import add_audit_fields


donation_intake_bp = Blueprint('donation_intake', __name__, url_prefix='/donation-intake')


# =============================================================================
# LIST VIEWS
# =============================================================================

@donation_intake_bp.route('/')
@login_required
@feature_required('donation_intake_management')
def list_intakes():
    """
    List all donation intakes.
    Shows intake history with status-based filters.
    Entry Role (LOGISTICS_OFFICER) sees their drafts and submitted.
    """
    from app.security.param_validation import validate_filter_value
    
    # Validate filter against allowed values
    ALLOWED_INTAKE_FILTERS = {'all', 'draft', 'submitted', 'verified', 'recent'}
    filter_type = validate_filter_value(
        request.args.get('filter', 'all'),
        ALLOWED_INTAKE_FILTERS,
        default='all'
    )
    search_query = request.args.get('search', '').strip()
    
    query = db.session.query(DonationIntake).join(
        Donation, DonationIntake.donation_id == Donation.donation_id
    ).join(
        Warehouse, DonationIntake.inventory_id == Warehouse.warehouse_id
    )
    
    if filter_type == 'draft':
        query = query.filter(DonationIntake.status_code == 'I')
    elif filter_type == 'submitted':
        query = query.filter(DonationIntake.status_code == 'C')
    elif filter_type == 'verified':
        query = query.filter(DonationIntake.status_code == 'V')
    elif filter_type == 'recent':
        thirty_days_ago = date.today() - timedelta(days=30)
        query = query.filter(DonationIntake.intake_date >= thirty_days_ago)
    
    if search_query:
        search_pattern = '%' + search_query + '%'
        query = query.filter(
            or_(
                Donation.donation_desc.ilike(search_pattern),
                Warehouse.warehouse_name.ilike(search_pattern)
            )
        )
    
    intakes = query.order_by(DonationIntake.update_dtime.desc()).all()
    
    all_count = db.session.query(DonationIntake).count()
    draft_count = db.session.query(DonationIntake).filter(DonationIntake.status_code == 'I').count()
    submitted_count = db.session.query(DonationIntake).filter(DonationIntake.status_code == 'C').count()
    verified_count = db.session.query(DonationIntake).filter(DonationIntake.status_code == 'V').count()
    
    counts = {
        'all': all_count,
        'draft': draft_count,
        'submitted': submitted_count,
        'verified': verified_count
    }
    
    return render_template('donation_intake/list.html',
                         intakes=intakes,
                         current_filter=filter_type,
                         search_query=search_query,
                         counts=counts)


@donation_intake_bp.route('/verify')
@login_required
@feature_required('donation_intake_verification')
def verify_list():
    """
    List intakes pending verification (status_code = 'C').
    Only accessible to LOGISTICS_MANAGER role.
    """
    search_query = request.args.get('search', '').strip()
    
    query = db.session.query(DonationIntake).filter(
        DonationIntake.status_code == 'C'
    ).join(
        Donation, DonationIntake.donation_id == Donation.donation_id
    ).join(
        Warehouse, DonationIntake.inventory_id == Warehouse.warehouse_id
    )
    
    if search_query:
        search_pattern = '%' + search_query + '%'
        query = query.filter(
            or_(
                Donation.donation_desc.ilike(search_pattern),
                Warehouse.warehouse_name.ilike(search_pattern)
            )
        )
    
    intakes = query.order_by(DonationIntake.update_dtime.desc()).all()
    
    pending_count = db.session.query(DonationIntake).filter(
        DonationIntake.status_code == 'C'
    ).count()
    
    return render_template('donation_intake/verify_list.html',
                         intakes=intakes,
                         search_query=search_query,
                         pending_count=pending_count)


# =============================================================================
# ENTRY WORKFLOW (Workflow A)
# =============================================================================

@donation_intake_bp.route('/create', methods=['GET', 'POST'])
@login_required
@feature_required('donation_intake_management')
def create_intake():
    """
    Step 1: Select donation and warehouse for intake.
    Shows list of verified donations (status='V') and active warehouses.
    """
    if request.method == 'POST':
        donation_id = request.form.get('donation_id')
        inventory_id = request.form.get('inventory_id')
        
        if not donation_id or not inventory_id:
            flash('Please select both a donation and a warehouse', 'danger')
            return redirect(url_for('donation_intake.create_intake'))
        
        return redirect(url_for('donation_intake.intake_form',
                              donation_id=donation_id,
                              inventory_id=inventory_id))
    
    from sqlalchemy.orm import joinedload
    
    verified_donations = Donation.query.filter_by(status_code='V').options(
        joinedload(Donation.items)
    ).order_by(
        Donation.received_date.desc()
    ).all()
    
    warehouses = Warehouse.query.filter_by(status_code='A').order_by(
        Warehouse.warehouse_name
    ).all()
    
    return render_template('donation_intake/create.html',
                         verified_donations=verified_donations,
                         warehouses=warehouses)


@donation_intake_bp.route('/intake/<int:donation_id>/<int:inventory_id>', methods=['GET', 'POST'])
@login_required
@feature_required('donation_intake_management')
def intake_form(donation_id, inventory_id):
    """
    Step 2: Complete intake form with donation items and batch details.
    Entry workflow - creates dnintake and dnintake_item with status I or C.
    Does NOT update inventory or itembatch - that happens on verification.
    Only shows GOODS items (category_type='GOODS').
    """
    donation = Donation.query.get_or_404(donation_id)
    warehouse = Warehouse.query.get_or_404(inventory_id)
    
    if donation.status_code != 'V':
        flash('Only verified donations can be intaken', 'danger')
        return redirect(url_for('donation_intake.list_intakes'))
    
    existing_intake = DonationIntake.query.get((donation_id, inventory_id))
    
    if existing_intake and existing_intake.status_code == 'V':
        flash(f'Intake already verified for Donation #{donation_id} at {warehouse.warehouse_name}', 'warning')
        return redirect(url_for('donation_intake.list_intakes'))
    
    if request.method == 'POST':
        action = request.form.get('action', 'submit')
        
        try:
            result = _process_entry_submission(donation, warehouse, existing_intake, action)
            
            if result['success']:
                flash(result['message'], 'success')
                return redirect(url_for('donation_intake.list_intakes'))
            else:
                db.session.rollback()
                for error in result['errors']:
                    flash(error, 'danger')
        
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('Error processing intake')
            flash('An error occurred while processing the intake. Please try again or contact support.', 'danger')
    
    donation_items = _get_goods_items_for_donation(donation_id)
    
    if not donation_items:
        flash('No GOODS items found in this donation. Only GOODS items can be intaken.', 'warning')
        return redirect(url_for('donation_intake.create_intake'))
    
    existing_intake_items = {}
    if existing_intake:
        for item in existing_intake.items:
            existing_intake_items[item.item_id] = item
    
    uoms = UnitOfMeasure.query.filter_by(status_code='A').order_by(
        UnitOfMeasure.uom_desc
    ).all()
    
    return render_template('donation_intake/intake_form.html',
                         donation=donation,
                         warehouse=warehouse,
                         donation_items=donation_items,
                         existing_intake=existing_intake,
                         existing_intake_items=existing_intake_items,
                         uoms=uoms,
                         today=date.today().isoformat(),
                         mode='entry')


@donation_intake_bp.route('/edit/<int:donation_id>/<int:inventory_id>', methods=['GET', 'POST'])
@login_required
@feature_required('donation_intake_management')
def edit_intake(donation_id, inventory_id):
    """
    Edit an existing draft intake (status='I').
    """
    intake = DonationIntake.query.get_or_404((donation_id, inventory_id))
    
    if intake.status_code != 'I':
        flash('Only draft intakes can be edited', 'warning')
        return redirect(url_for('donation_intake.list_intakes'))
    
    return redirect(url_for('donation_intake.intake_form',
                          donation_id=donation_id,
                          inventory_id=inventory_id))


def _get_goods_items_for_donation(donation_id):
    """
    Get only GOODS items from a donation.
    Filters donation_item where itemcatg.category_type = 'GOODS'.
    """
    return db.session.query(DonationItem).join(
        Item, DonationItem.item_id == Item.item_id
    ).join(
        ItemCategory, Item.category_id == ItemCategory.category_id
    ).filter(
        DonationItem.donation_id == donation_id,
        ItemCategory.category_type == 'GOODS'
    ).all()


def _process_entry_submission(donation, warehouse, existing_intake, action):
    """
    Process intake entry form submission.
    Creates or updates dnintake header and items.
    Does NOT touch inventory or itembatch - that's for verification.
    
    action: 'save_draft' -> status_code = 'I'
           'submit' -> status_code = 'C'
    """
    errors = []
    
    intake_date_str = request.form.get('intake_date')
    comments_text = request.form.get('comments_text', '').strip()
    
    intake_date = None
    if not intake_date_str:
        errors.append('Intake date is required')
    else:
        try:
            intake_date = datetime.strptime(intake_date_str, '%Y-%m-%d').date()
            if intake_date > date.today():
                errors.append('Intake date cannot be in the future')
        except ValueError:
            errors.append('Invalid intake date format')
    
    if len(comments_text) > 255:
        errors.append('Comments must be 255 characters or less')
    
    donation_items = _get_goods_items_for_donation(donation.donation_id)
    intake_items_data = []
    item_totals = {}
    
    for donation_item in donation_items:
        item_id = donation_item.item_id
        item = donation_item.item
        
        batch_no_key = f'batch_no_{item_id}'
        if batch_no_key not in request.form:
            errors.append(f'{item.item_name}: Missing intake data in form submission')
            continue
        
        batch_no_raw = request.form.get(batch_no_key, '').strip().upper()
        batch_date_str = request.form.get(f'batch_date_{item_id}', '').strip()
        expiry_date_str = request.form.get(f'expiry_date_{item_id}', '').strip()
        uom_code = request.form.get(f'uom_code_{item_id}')
        avg_unit_value_str = request.form.get(f'avg_unit_value_{item_id}')
        usable_qty_str = request.form.get(f'usable_qty_{item_id}', '0')
        defective_qty_str = request.form.get(f'defective_qty_{item_id}', '0')
        expired_qty_str = request.form.get(f'expired_qty_{item_id}', '0')
        item_comments = request.form.get(f'item_comments_{item_id}', '').strip()
        
        batch_no = None
        batch_date = None
        
        if item.is_batched_flag:
            if not batch_no_raw:
                errors.append(f'{item.item_name}: Batch number is required for batched items')
                continue
            if not batch_date_str:
                errors.append(f'{item.item_name}: Batch date is required for batched items')
                continue
            batch_no = batch_no_raw
            try:
                batch_date = datetime.strptime(batch_date_str, '%Y-%m-%d').date()
                if batch_date > date.today():
                    errors.append(f'{item.item_name}: Batch date cannot be in the future')
                    continue
            except ValueError:
                errors.append(f'{item.item_name}: Invalid batch date format')
                continue
        else:
            if batch_no_raw and not batch_date_str:
                errors.append(f'{item.item_name}: Please enter a Batch Date when a Batch No is provided')
                continue
            elif not batch_no_raw and batch_date_str:
                errors.append(f'{item.item_name}: Please enter a Batch No when a Batch Date is provided')
                continue
            elif batch_no_raw and batch_date_str:
                batch_no = batch_no_raw
                try:
                    batch_date = datetime.strptime(batch_date_str, '%Y-%m-%d').date()
                    if batch_date > date.today():
                        errors.append(f'{item.item_name}: Batch date cannot be in the future')
                        continue
                except ValueError:
                    errors.append(f'{item.item_name}: Invalid batch date format')
                    continue
            else:
                batch_no = item.item_code
                batch_date = date.today()
        
        expiry_date = None
        if item.can_expire_flag:
            if not expiry_date_str:
                errors.append(f'{item.item_name}: Expiry Date is required for perishable items')
                continue
            try:
                expiry_date = datetime.strptime(expiry_date_str, '%Y-%m-%d').date()
                if expiry_date < date.today():
                    errors.append(f'{item.item_name}: Expiry date cannot be in the past')
                    continue
                if batch_date and expiry_date < batch_date:
                    errors.append(f'{item.item_name}: Expiry date must be on or after batch date')
                    continue
            except ValueError:
                errors.append(f'{item.item_name}: Invalid expiry date format')
                continue
        else:
            # Non-expirable items: parse user-provided expiry date if given, otherwise leave as None
            if expiry_date_str:
                try:
                    expiry_date = datetime.strptime(expiry_date_str, '%Y-%m-%d').date()
                except ValueError:
                    pass
            # Do NOT set a placeholder date - expiry_date remains None for non-expirable items
        
        if not uom_code:
            errors.append(f'{item.item_name}: UOM is required')
            continue
        
        try:
            usable_qty = Decimal(usable_qty_str) if usable_qty_str else Decimal('0')
            defective_qty = Decimal(defective_qty_str) if defective_qty_str else Decimal('0')
            expired_qty = Decimal(expired_qty_str) if expired_qty_str else Decimal('0')
            
            if usable_qty < 0 or defective_qty < 0 or expired_qty < 0:
                errors.append(f'{item.item_name}: Quantities cannot be negative')
                continue
            
            if usable_qty == 0:
                errors.append(f'{item.item_name}: Usable quantity cannot be zero')
                continue
            
            total_qty = usable_qty + defective_qty + expired_qty
        except (InvalidOperation, ValueError):
            errors.append(f'{item.item_name}: Invalid quantity values')
            continue
        
        try:
            avg_unit_value = Decimal(avg_unit_value_str) if avg_unit_value_str else Decimal('0')
            if avg_unit_value <= 0:
                errors.append(f'{item.item_name}: Unit cost must be greater than 0')
                continue
        except (InvalidOperation, ValueError):
            errors.append(f'{item.item_name}: Invalid unit cost value')
            continue
        
        ext_item_cost = total_qty * avg_unit_value
        
        if item_id not in item_totals:
            item_totals[item_id] = Decimal('0')
        item_totals[item_id] += total_qty
        
        intake_items_data.append({
            'item_id': item_id,
            'item': item,
            'batch_no': batch_no,
            'batch_date': batch_date,
            'expiry_date': expiry_date,
            'uom_code': uom_code,
            'avg_unit_value': avg_unit_value,
            'ext_item_cost': ext_item_cost,
            'usable_qty': usable_qty,
            'defective_qty': defective_qty,
            'expired_qty': expired_qty,
            'comments_text': item_comments.upper() if item_comments else None
        })
    
    seen_batches = set()
    for item_data in intake_items_data:
        batch_key = (item_data['item_id'], item_data['batch_no'])
        if batch_key in seen_batches:
            errors.append(
                f'{item_data["item"].item_name}: Duplicate batch number "{item_data["batch_no"]}" in this submission'
            )
        seen_batches.add(batch_key)
    
    for donation_item in donation_items:
        expected_qty = donation_item.item_qty
        actual_qty = item_totals.get(donation_item.item_id, Decimal('0'))
        
        if actual_qty != expected_qty:
            errors.append(
                f'{donation_item.item.item_name}: Intake quantity ({actual_qty}) must equal donation quantity ({expected_qty})'
            )
    
    for donation_item in donation_items:
        if donation_item.item_id not in item_totals:
            errors.append(f'{donation_item.item.item_name}: Must have intake data')
    
    if errors:
        return {'success': False, 'errors': errors, 'message': None}
    
    try:
        current_timestamp = jamaica_now()
        new_status = 'I' if action == 'save_draft' else 'C'
        
        if existing_intake:
            intake = existing_intake
            intake.intake_date = intake_date
            intake.comments_text = comments_text.upper() if comments_text else None
            intake.status_code = new_status
            # Keep original creator metadata intact when updating a draft or resubmitting
            add_audit_fields(intake, current_user, is_new=False)
            
            DonationIntakeItem.query.filter_by(
                donation_id=donation.donation_id,
                inventory_id=warehouse.warehouse_id
            ).delete()
        else:
            intake = DonationIntake()
            intake.donation_id = donation.donation_id
            intake.inventory_id = warehouse.warehouse_id
            intake.intake_date = intake_date
            intake.comments_text = comments_text.upper() if comments_text else None
            intake.status_code = new_status
            intake.verify_by_id = ''
            intake.verify_dtime = None
            add_audit_fields(intake, current_user, is_new=True)
            db.session.add(intake)
        
        db.session.flush()
        
        for item_data in intake_items_data:
            intake_item = DonationIntakeItem()
            intake_item.donation_id = donation.donation_id
            intake_item.inventory_id = warehouse.warehouse_id
            intake_item.item_id = item_data['item_id']
            intake_item.batch_no = item_data['batch_no']
            intake_item.batch_date = item_data['batch_date']
            intake_item.expiry_date = item_data['expiry_date']
            intake_item.uom_code = item_data['uom_code']
            intake_item.avg_unit_value = item_data['avg_unit_value']
            intake_item.ext_item_cost = item_data['ext_item_cost']
            intake_item.usable_qty = item_data['usable_qty']
            intake_item.defective_qty = item_data['defective_qty']
            intake_item.expired_qty = item_data['expired_qty']
            intake_item.status_code = 'P'
            intake_item.comments_text = item_data['comments_text']
            add_audit_fields(intake_item, current_user, is_new=True)
            db.session.add(intake_item)
        
        db.session.commit()
        
        if action == 'save_draft':
            message = f'Draft saved for Donation #{donation.donation_id}'
            log_data_event(
                action=AuditAction.CREATE,
                user_id=current_user.user_id,
                entity_type='donation_intake',
                entity_id=f'{donation.donation_id}:{warehouse.warehouse_id}',
                outcome=AuditOutcome.SUCCESS,
                details={
                    'donation_id': donation.donation_id,
                    'warehouse_id': warehouse.warehouse_id,
                    'item_count': len(intake_items_data),
                    'status': 'I',
                    'action': 'save_draft'
                }
            )
        else:
            message = f'Donation #{donation.donation_id} intake submitted for verification'
            log_data_event(
                action=AuditAction.CREATE,
                user_id=current_user.user_id,
                entity_type='donation_intake',
                entity_id=f'{donation.donation_id}:{warehouse.warehouse_id}',
                outcome=AuditOutcome.SUCCESS,
                details={
                    'donation_id': donation.donation_id,
                    'warehouse_id': warehouse.warehouse_id,
                    'item_count': len(intake_items_data),
                    'status': 'C',
                    'action': 'submit_for_verification'
                }
            )
        
        return {'success': True, 'message': message, 'errors': []}
    
    except IntegrityError as e:
        db.session.rollback()
        return {'success': False, 'errors': [f'Database constraint error: {str(e)}'], 'message': None}
    except Exception as e:
        db.session.rollback()
        return {'success': False, 'errors': [f'Database error: {str(e)}'], 'message': None}


# =============================================================================
# VERIFICATION WORKFLOW (Workflow B)
# =============================================================================

@donation_intake_bp.route('/verify/<int:donation_id>/<int:inventory_id>', methods=['GET', 'POST'])
@login_required
@feature_required('donation_intake_verification')
def verify_intake(donation_id, inventory_id):
    """
    Verification page for a submitted intake (status='C').
    Only accessible to LOGISTICS_MANAGER role.
    
    GET: Load intake for verification with limited editable fields.
    POST: Validate and verify the intake, updating inventory and itembatch.
    """
    intake = DonationIntake.query.get_or_404((donation_id, inventory_id))
    
    if intake.status_code != 'C':
        if intake.status_code == 'V':
            flash('This intake has already been verified', 'info')
        else:
            flash('Only submitted intakes can be verified', 'warning')
        return redirect(url_for('donation_intake.verify_list'))
    
    donation = intake.donation
    warehouse = intake.warehouse
    
    if request.method == 'POST':
        try:
            result = _process_verification_submission(intake, donation, warehouse)
            
            if result['success']:
                flash(result['message'], 'success')
                return redirect(url_for('donation_intake.verify_list'))
            else:
                db.session.rollback()
                for error in result['errors']:
                    flash(error, 'danger')
        
        except StaleDataError:
            db.session.rollback()
            flash('This intake was modified by another user. Please refresh and try again.', 'danger')
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('Error verifying intake')
            flash('An error occurred while verifying the intake. Please try again or contact support.', 'danger')
    
    intake_items = DonationIntakeItem.query.filter_by(
        donation_id=donation_id,
        inventory_id=inventory_id
    ).all()
    
    uoms = UnitOfMeasure.query.filter_by(status_code='A').order_by(
        UnitOfMeasure.uom_desc
    ).all()
    
    return render_template('donation_intake/verify_form.html',
                         intake=intake,
                         donation=donation,
                         warehouse=warehouse,
                         intake_items=intake_items,
                         uoms=uoms,
                         today=date.today().isoformat(),
                         mode='verify')


def _process_verification_submission(intake, donation, warehouse):
    """
    Process intake verification submission.
    Updates intake status to V, creates/updates itembatch, updates inventory.
    All operations in a single atomic transaction with optimistic locking.
    """
    errors = []
    
    intake_items = DonationIntakeItem.query.filter_by(
        donation_id=intake.donation_id,
        inventory_id=intake.inventory_id
    ).all()

    donation_items = DonationItem.query.filter_by(
        donation_id=donation.donation_id
    ).all()
    donation_items_by_id = {di.item_id: di for di in donation_items}
    
    verified_items_data = []
    
    for intake_item in intake_items:
        item_id = intake_item.item_id
        item = intake_item.item
        
        defective_qty_str = request.form.get(f'defective_qty_{item_id}', str(intake_item.defective_qty))
        expired_qty_str = request.form.get(f'expired_qty_{item_id}', str(intake_item.expired_qty))
        batch_no_default = intake_item.batch_no or ''
        batch_no_raw = request.form.get(f'batch_no_{item_id}', batch_no_default).strip().upper()
        batch_date_str = request.form.get(f'batch_date_{item_id}', '')
        expiry_date_str = request.form.get(f'expiry_date_{item_id}', '')
        item_comments = request.form.get(f'item_comments_{item_id}', intake_item.comments_text or '').strip()
        
        try:
            defective_qty = Decimal(defective_qty_str) if defective_qty_str else Decimal('0')
            expired_qty = Decimal(expired_qty_str) if expired_qty_str else Decimal('0')

            if defective_qty < 0 or expired_qty < 0:
                errors.append(f'{item.item_name}: Quantities cannot be negative')
                continue

            donation_item = donation_items_by_id.get(item_id)

            if not donation_item:
                errors.append(f'{item.item_name}: Donation item not found')
                continue

            donation_qty = donation_item.item_qty or Decimal('0')

            if donation_qty <= 0:
                errors.append(
                    f"{item.item_name}: Donation quantity must be greater than zero before verification"
                )
                continue

            intake_item_total = (
                (intake_item.usable_qty or Decimal('0'))
                + (intake_item.defective_qty or Decimal('0'))
                + (intake_item.expired_qty or Decimal('0'))
            )

            if intake_item_total <= 0:
                errors.append(
                    f"{item.item_name}: Intake quantity must be greater than zero before verification"
                )
                continue

            total_deductions = defective_qty + expired_qty
            if total_deductions > intake_item_total:
                errors.append(
                    f'{item.item_name}: Defective + Expired cannot exceed the intake quantity ({intake_item_total})'
                )
                continue

            if total_deductions > donation_qty:
                errors.append(
                    f"{item.item_name}: Defective + Expired cannot exceed donated quantity ({donation_qty})"
                )
                continue

            usable_qty = intake_item_total - defective_qty - expired_qty

            if usable_qty <= 0:
                errors.append(f'{item.item_name}: Usable quantity must be greater than zero')
                continue

        except (InvalidOperation, ValueError):
            errors.append(f'{item.item_name}: Invalid quantity values')
            continue
        
        batch_no = batch_no_raw if batch_no_raw else intake_item.batch_no
        
        batch_date = intake_item.batch_date
        if batch_date_str:
            try:
                batch_date = datetime.strptime(batch_date_str, '%Y-%m-%d').date()
                if batch_date > date.today():
                    errors.append(f'{item.item_name}: Batch date cannot be in the future')
                    continue
            except ValueError:
                errors.append(f'{item.item_name}: Invalid batch date format')
                continue
        
        expiry_date = intake_item.expiry_date
        if expiry_date_str:
            try:
                expiry_date = datetime.strptime(expiry_date_str, '%Y-%m-%d').date()
                if item.can_expire_flag and expiry_date < date.today():
                    errors.append(f'{item.item_name}: Expiry date cannot be in the past for perishable items')
                    continue
                if batch_date and expiry_date < batch_date:
                    errors.append(f'{item.item_name}: Expiry date must be on or after batch date')
                    continue
            except ValueError:
                errors.append(f'{item.item_name}: Invalid expiry date format')
                continue
        
        ext_item_cost = intake_item_total * intake_item.avg_unit_value
        
        verified_items_data.append({
            'intake_item': intake_item,
            'item': item,
            'batch_no': batch_no,
            'batch_date': batch_date,
            'expiry_date': expiry_date,
            'usable_qty': usable_qty,
            'defective_qty': defective_qty,
            'expired_qty': expired_qty,
            'ext_item_cost': ext_item_cost,
            'comments_text': item_comments.upper() if item_comments else None
        })
    
    if errors:
        return {'success': False, 'errors': errors, 'message': None}
    
    try:
        current_timestamp = jamaica_now()
        
        intake.status_code = 'V'
        intake.verify_by_id = current_user.user_name
        intake.verify_dtime = current_timestamp
        add_audit_fields(intake, current_user, is_new=False)
        
        for item_data in verified_items_data:
            intake_item = item_data['intake_item']
            item = item_data['item']
            
            if intake_item.batch_no != item_data['batch_no']:
                DonationIntakeItem.query.filter_by(
                    donation_id=intake.donation_id,
                    inventory_id=intake.inventory_id,
                    item_id=intake_item.item_id,
                    batch_no=intake_item.batch_no
                ).delete()
                
                new_intake_item = DonationIntakeItem()
                new_intake_item.donation_id = intake.donation_id
                new_intake_item.inventory_id = intake.inventory_id
                new_intake_item.item_id = item_data['item'].item_id
                new_intake_item.batch_no = item_data['batch_no']
                new_intake_item.batch_date = item_data['batch_date']
                new_intake_item.expiry_date = item_data['expiry_date']
                new_intake_item.uom_code = intake_item.uom_code
                new_intake_item.avg_unit_value = intake_item.avg_unit_value
                new_intake_item.ext_item_cost = item_data['ext_item_cost']
                new_intake_item.usable_qty = item_data['usable_qty']
                new_intake_item.defective_qty = item_data['defective_qty']
                new_intake_item.expired_qty = item_data['expired_qty']
                new_intake_item.status_code = 'V'
                new_intake_item.comments_text = item_data['comments_text']
                add_audit_fields(new_intake_item, current_user, is_new=True)
                db.session.add(new_intake_item)
                intake_item = new_intake_item
            else:
                intake_item.batch_date = item_data['batch_date']
                intake_item.expiry_date = item_data['expiry_date']
                intake_item.usable_qty = item_data['usable_qty']
                intake_item.defective_qty = item_data['defective_qty']
                intake_item.expired_qty = item_data['expired_qty']
                intake_item.ext_item_cost = item_data['ext_item_cost']
                intake_item.status_code = 'V'
                intake_item.comments_text = item_data['comments_text']
                add_audit_fields(intake_item, current_user, is_new=False)
            
            existing_batch = ItemBatch.query.filter_by(
                inventory_id=warehouse.warehouse_id,
                item_id=item_data['item'].item_id,
                batch_no=item_data['batch_no']
            ).with_for_update().first()
            
            if existing_batch:
                existing_batch.usable_qty = (existing_batch.usable_qty or Decimal('0')) + item_data['usable_qty']
                existing_batch.defective_qty = (existing_batch.defective_qty or Decimal('0')) + item_data['defective_qty']
                existing_batch.expired_qty = (existing_batch.expired_qty or Decimal('0')) + item_data['expired_qty']
                if item_data['expiry_date'] and (not existing_batch.expiry_date or item_data['expiry_date'] < existing_batch.expiry_date):
                    existing_batch.expiry_date = item_data['expiry_date']
                add_audit_fields(existing_batch, current_user, is_new=False)
            else:
                item_batch = ItemBatch()
                item_batch.inventory_id = warehouse.warehouse_id
                item_batch.item_id = item_data['item'].item_id
                item_batch.batch_no = item_data['batch_no']
                item_batch.batch_date = item_data['batch_date']
                item_batch.expiry_date = item_data['expiry_date']
                item_batch.uom_code = intake_item.uom_code
                item_batch.avg_unit_value = intake_item.avg_unit_value
                item_batch.usable_qty = item_data['usable_qty']
                item_batch.defective_qty = item_data['defective_qty']
                item_batch.expired_qty = item_data['expired_qty']
                item_batch.reserved_qty = Decimal('0')
                item_batch.status_code = 'A'
                item_batch.comments_text = item_data['comments_text']
                add_audit_fields(item_batch, current_user, is_new=True)
                db.session.add(item_batch)
            
            inventory = Inventory.query.filter_by(
                inventory_id=warehouse.warehouse_id,
                item_id=item_data['item'].item_id
            ).with_for_update().first()
            
            if inventory:
                inventory.usable_qty = (inventory.usable_qty or Decimal('0')) + item_data['usable_qty']
                inventory.defective_qty = (inventory.defective_qty or Decimal('0')) + item_data['defective_qty']
                inventory.expired_qty = (inventory.expired_qty or Decimal('0')) + item_data['expired_qty']
                add_audit_fields(inventory, current_user, is_new=False)
            else:
                inventory = Inventory()
                inventory.inventory_id = warehouse.warehouse_id
                inventory.item_id = item_data['item'].item_id
                inventory.uom_code = intake_item.uom_code
                inventory.usable_qty = item_data['usable_qty']
                inventory.defective_qty = item_data['defective_qty']
                inventory.expired_qty = item_data['expired_qty']
                inventory.reserved_qty = Decimal('0')
                inventory.status_code = 'A'
                add_audit_fields(inventory, current_user, is_new=True)
                db.session.add(inventory)
        
        donation.status_code = 'P'
        add_audit_fields(donation, current_user, is_new=False)
        
        db.session.commit()
        
        log_data_event(
            action=AuditAction.VERIFY,
            user_id=current_user.user_id,
            entity_type='donation_intake',
            entity_id=f'{donation.donation_id}:{warehouse.warehouse_id}',
            outcome=AuditOutcome.SUCCESS,
            details={
                'donation_id': donation.donation_id,
                'warehouse_id': warehouse.warehouse_id,
                'warehouse_name': warehouse.warehouse_name,
                'item_count': len(verified_items_data),
                'donation_status_changed': 'V->P'
            }
        )
        
        message = f'Donation #{donation.donation_id} intake verified and inventory updated at {warehouse.warehouse_name}'
        return {'success': True, 'message': message, 'errors': []}
    
    except IntegrityError as e:
        db.session.rollback()
        return {'success': False, 'errors': [f'Database constraint error: {str(e)}'], 'message': None}
    except StaleDataError:
        db.session.rollback()
        raise
    except Exception as e:
        db.session.rollback()
        return {'success': False, 'errors': [f'Database error: {str(e)}'], 'message': None}


# =============================================================================
# API ENDPOINTS
# =============================================================================

@donation_intake_bp.route('/api/donation/<int:donation_id>/goods-items')
@login_required
@feature_required('donation_intake_management')
def get_donation_goods_items(donation_id):
    """
    API endpoint to get GOODS items for a donation.
    Returns JSON with item details for client-side processing.
    """
    items = _get_goods_items_for_donation(donation_id)
    
    result = []
    for di in items:
        result.append({
            'item_id': di.item_id,
            'item_code': di.item.item_code,
            'item_name': di.item.item_name,
            'item_qty': float(di.item_qty),
            'uom_code': di.uom_code,
            'is_batched': di.item.is_batched_flag,
            'can_expire': di.item.can_expire_flag
        })
    
    return jsonify({'items': result, 'count': len(result)})
