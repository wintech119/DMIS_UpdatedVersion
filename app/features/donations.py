"""
Donation Management Routes
Accept and process donations from donors with full item tracking.

Access: LOGISTICS_MANAGER, LOGISTICS_OFFICER only
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from datetime import datetime, date
from decimal import Decimal
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from app.db import db
from app.security.log_sanitizer import sanitize_for_log, sanitize_exception_for_log
from app.security.audit_logger import log_data_event, AuditAction, AuditOutcome
from app.utils.timezone import now as jamaica_now
from app.db.models import (Donation, DonationItem, DonationDoc, Donor, Event, Custodian, 
                          Item, UnitOfMeasure, Country, Currency, ItemCostDef)
from app.core.audit import add_audit_fields, add_verify_fields
from app.core.decorators import feature_required
from app.core import session_utils
import os
from werkzeug.utils import secure_filename
import mimetypes
from app.security.safe_path import safe_join

donations_bp = Blueprint('donations', __name__, url_prefix='/donations')


def _get_adhoc_event():
    """Get the ADHOC event for default selection"""
    return Event.query.filter(Event.event_name.ilike('%ADHOC%')).first()


def _get_donation_form_data():
    """Get all data needed for donation form dropdowns"""
    donors = Donor.query.order_by(Donor.donor_name).all()
    events = Event.query.filter_by(status_code='A').order_by(Event.event_name).all()
    custodians = Custodian.query.order_by(Custodian.custodian_name).all()
    items = Item.query.filter_by(status_code='A').order_by(Item.item_name).all()
    uoms = UnitOfMeasure.query.filter_by(status_code='A').order_by(UnitOfMeasure.uom_desc).all()
    countries = Country.query.filter_by(status_code='A').order_by(Country.country_name).all()
    currencies = Currency.query.filter_by(status_code='A').order_by(Currency.currency_name).all()
    cost_defs = ItemCostDef.query.filter_by(status_code='A').order_by(ItemCostDef.cost_type, ItemCostDef.cost_name).all()
    adhoc_event = _get_adhoc_event()
    
    items_json = [{'item_id': item.item_id, 'item_name': item.item_name, 'sku_code': item.sku_code, 'default_uom_code': item.default_uom_code} for item in items]
    uoms_json = [{'uom_code': uom.uom_code, 'uom_desc': uom.uom_desc} for uom in uoms]
    countries_json = [{'country_id': c.country_id, 'country_name': c.country_name, 'currency_code': c.currency_code} for c in countries]
    currencies_json = [{'currency_code': cur.currency_code, 'currency_name': cur.currency_name, 'currency_sign': cur.currency_sign} for cur in currencies]
    cost_defs_json = [{'cost_id': cd.cost_id, 'cost_name': cd.cost_name, 'cost_desc': cd.cost_desc, 'cost_type': cd.cost_type} for cd in cost_defs]
    
    return {
        'donors': donors,
        'events': events,
        'custodians': custodians,
        'items': items_json,
        'uoms': uoms_json,
        'countries': countries_json,
        'currencies': currencies_json,
        'cost_defs': cost_defs_json,
        'adhoc_event': adhoc_event,
        'today': date.today().isoformat()
    }


@donations_bp.route('/')
@login_required
@feature_required('donation_management')
def list_donations():
    """List all donations with filter and search capabilities"""
    from app.security.param_validation import validate_status_code, safe_id
    
    # Validate status filter against allowed donation status codes
    ALLOWED_DONATION_STATUSES = {'all', 'E', 'V', 'P'}
    status_filter = validate_status_code(
        request.args.get('status', 'all'), 
        ALLOWED_DONATION_STATUSES, 
        default='all'
    )
    donor_filter = safe_id(request.args.get('donor_id'), default=None)
    event_filter = safe_id(request.args.get('event_id'), default=None)
    search_query = request.args.get('search', '').strip()
    
    query = Donation.query
    
    if status_filter != 'all':
        query = query.filter_by(status_code=status_filter.upper())
    
    if donor_filter:
        query = query.filter_by(donor_id=donor_filter)
    
    if event_filter:
        query = query.filter_by(event_id=event_filter)
    
    if search_query:
        search_pattern = '%' + search_query + '%'
        query = query.filter(
            db.or_(
                Donation.donation_desc.ilike(search_pattern),
                Donation.comments_text.ilike(search_pattern)
            )
        )
    
    donations = query.order_by(Donation.received_date.desc()).all()
    
    status_counts = {
        'all': Donation.query.count(),
        'E': Donation.query.filter_by(status_code='E').count(),
        'V': Donation.query.filter_by(status_code='V').count(),
        'P': Donation.query.filter_by(status_code='P').count()
    }
    
    donors = Donor.query.order_by(Donor.donor_name).all()
    events = Event.query.filter_by(status_code='A').order_by(Event.event_name).all()
    
    return render_template('donations/list.html', 
                         donations=donations,
                         status_counts=status_counts,
                         current_filter=status_filter,
                         donor_filter=donor_filter,
                         event_filter=event_filter,
                         search_query=search_query,
                         donors=donors,
                         events=events)


@donations_bp.route('/api/item-category/<int:item_id>')
@login_required
@feature_required('donation_management')
def get_item_category(item_id):
    """
    API endpoint to get item category information for dynamic form behavior.
    Returns category_type (GOODS/FUNDS) and category details.
    """
    from app.db.models import ItemCategory
    
    item = Item.query.get_or_404(item_id)
    category = ItemCategory.query.get(item.category_id)
    
    if not category:
        return jsonify({'error': 'Category not found'}), 404
    
    return jsonify({
        'item_id': item.item_id,
        'item_name': item.item_name,
        'sku_code': item.sku_code,
        'category_id': category.category_id,
        'category_code': category.category_code,
        'category_desc': category.category_desc,
        'category_type': category.category_type,
        'default_uom_code': item.default_uom_code
    })


@donations_bp.route('/create', methods=['GET', 'POST'])
@login_required
@feature_required('donation_management')
def create_donation():
    """
    Create new donation with header and items in a single atomic transaction.
    If any validation or save error occurs, rollback entire transaction.
    """
    if request.method == 'POST':
        try:
            donor_id = request.form.get('donor_id')
            event_id = request.form.get('event_id')
            custodian_id = request.form.get('custodian_id')
            donation_desc = request.form.get('donation_desc', '').strip()
            received_date_str = request.form.get('received_date')
            origin_country_id = request.form.get('origin_country_id')
            origin_address1 = request.form.get('origin_address1_text', '').strip()
            origin_address2 = request.form.get('origin_address2_text', '').strip()
            comments_text = request.form.get('comments_text', '').strip()
            
            tot_item_cost_str = request.form.get('tot_item_cost', '0.00').strip()
            storage_cost_str = request.form.get('storage_cost', '0.00').strip()
            haulage_cost_str = request.form.get('haulage_cost', '0.00').strip()
            other_cost_str = request.form.get('other_cost', '0.00').strip()
            other_cost_desc = request.form.get('other_cost_desc', '').strip()
            
            errors = []
            
            if not donor_id:
                errors.append('Donor is required')
            if not event_id:
                errors.append('Event is required')
            if not custodian_id:
                errors.append('Custodian is required')
            if not donation_desc:
                errors.append('Donation description is required')
            if not received_date_str:
                errors.append('Received date is required')
            if not origin_country_id:
                errors.append('Origin country is required')
            
            if received_date_str:
                received_date = datetime.strptime(received_date_str, '%Y-%m-%d').date()
                if received_date > date.today():
                    errors.append('Received date cannot be in the future')
            
            tot_item_cost_value = Decimal('0.00')
            try:
                tot_item_cost_value = Decimal(tot_item_cost_str) if tot_item_cost_str else Decimal('0.00')
                if tot_item_cost_value <= 0:
                    errors.append('Total Donation Value must be greater than 0')
            except:
                errors.append('Invalid Total Donation Value')
            
            storage_cost_value = Decimal('0.00')
            try:
                storage_cost_value = Decimal(storage_cost_str) if storage_cost_str else Decimal('0.00')
                if storage_cost_value < 0:
                    errors.append('Storage cost must be >= 0')
            except:
                errors.append('Invalid storage cost value')
            
            haulage_cost_value = Decimal('0.00')
            try:
                haulage_cost_value = Decimal(haulage_cost_str) if haulage_cost_str else Decimal('0.00')
                if haulage_cost_value < 0:
                    errors.append('Haulage cost must be >= 0')
            except:
                errors.append('Invalid haulage cost value')
            
            other_cost_value = Decimal('0.00')
            try:
                other_cost_value = Decimal(other_cost_str) if other_cost_str else Decimal('0.00')
                if other_cost_value < 0:
                    errors.append('Other cost must be >= 0')
            except:
                errors.append('Invalid other cost value')
            
            if other_cost_value > 0 and not other_cost_desc:
                errors.append('Other cost description is required when other cost is greater than 0')
            
            item_data = []
            item_ids_seen = set()
            for key in request.form.keys():
                if key.startswith('item_id_'):
                    item_num = key.split('_')[-1]
                    item_id = request.form.get(f'item_id_{item_num}')
                    donation_type = request.form.get(f'donation_type_{item_num}', 'GOODS').upper()
                    quantity_str = request.form.get(f'quantity_{item_num}')
                    item_cost_str = request.form.get(f'item_cost_{item_num}', '0.00')
                    uom_id = request.form.get(f'uom_id_{item_num}')
                    currency_code = request.form.get(f'currency_code_{item_num}')
                    location_name = request.form.get(f'location_name_{item_num}', 'DONATION RECEIVED').strip()
                    item_comments = request.form.get(f'item_comments_{item_num}', '').strip()
                    
                    if item_id:
                        # Check for duplicate items in the same donation
                        if item_id in item_ids_seen:
                            errors.append(f'Duplicate item detected in row #{item_num}. Each item can only be added once per donation.')
                            continue
                        item_ids_seen.add(item_id)
                        
                        # Validate donation type
                        if donation_type not in ('GOODS', 'FUNDS'):
                            errors.append(f'Invalid donation type for item #{item_num}. Must be GOODS or FUNDS.')
                        
                        # Validate quantity
                        quantity_value = None
                        if not quantity_str:
                            errors.append(f'Quantity is required for item #{item_num}')
                        else:
                            try:
                                quantity_value = Decimal(quantity_str)
                                if quantity_value < 0:
                                    errors.append(f'Quantity must be >= 0 for item #{item_num}')
                            except:
                                errors.append(f'Invalid quantity for item #{item_num}')
                        
                        # Validate item_cost
                        item_cost_value = Decimal('0.00')
                        try:
                            item_cost_value = Decimal(item_cost_str)
                            if item_cost_value < 0:
                                errors.append(f'Item cost must be >= 0 for item #{item_num}')
                        except:
                            errors.append(f'Invalid item cost for item #{item_num}')

                        # Validate based on donation type: GOODS needs uom_code, FUNDS needs currency_code
                        if donation_type == 'GOODS':
                            if not uom_id:
                                errors.append(f'UOM is required for GOODS item #{item_num}')
                        elif donation_type == 'FUNDS':
                            if not currency_code:
                                errors.append(f'Currency is required for FUNDS item #{item_num}')

                        try:
                            item_data.append({
                                'item_id': int(item_id),
                                'donation_type': donation_type,
                                'quantity': quantity_value,
                                'item_cost': item_cost_value,
                                'uom_code': uom_id if donation_type == 'GOODS' else None,
                                'currency_code': currency_code if donation_type == 'FUNDS' else None,
                                'location_name': location_name,
                                'item_comments': item_comments
                            })
                        except ValueError as ve:
                            errors.append(f'Invalid data for item #{item_num}: {str(ve)}')
            
            if not item_data:
                errors.append('At least one donation item is required')
            
            if errors:
                for error in errors:
                    flash(error, 'danger')
                form_data = _get_donation_form_data()
                form_data['form_data'] = request.form
                return render_template('donations/create.html', **form_data)
            
            donation = Donation()
            donation.donor_id = int(donor_id)
            donation.event_id = int(event_id)
            donation.custodian_id = int(custodian_id)
            donation.donation_desc = donation_desc.upper()
            donation.received_date = received_date
            donation.origin_country_id = int(origin_country_id) if origin_country_id else None
            donation.origin_address1_text = origin_address1.upper() if origin_address1 else None
            donation.origin_address2_text = origin_address2.upper() if origin_address2 else None
            donation.status_code = 'E'
            donation.comments_text = comments_text.upper() if comments_text else None
            
            donation.storage_cost = storage_cost_value
            donation.haulage_cost = haulage_cost_value
            donation.other_cost = other_cost_value
            donation.other_cost_desc = other_cost_desc.upper() if other_cost_desc else None
            
            current_timestamp = jamaica_now()
            
            add_audit_fields(donation, current_user, is_new=True)
            
            # Verify fields remain NULL for status 'E' (Entry/Pending verification)
            # They will be populated only when donation is verified (status='V')
            donation.verify_by_id = None
            donation.verify_dtime = None
            
            db.session.add(donation)
            db.session.flush()
            
            # Calculate total donation value and validate items before persisting
            total_value = Decimal('0.00')
            validated_items = []
            
            for item_info in item_data:
                # Enhanced validation for cost requirements
                donation_type = item_info['donation_type']
                item_cost = item_info['item_cost']
                # FUNDS items: Server-side enforcement - quantity is always 1.00
                quantity = Decimal('1.00') if donation_type == 'FUNDS' else item_info['quantity']
                
                # Validate quantity for all types (allow >= 0 to match DB constraint)
                if quantity < 0:
                    errors.append(f"Donation items must have quantity >= 0")
                    continue
                
                if donation_type == 'FUNDS':
                    # FUNDS must have item_cost > 0 and quantity >= 0
                    if item_cost <= 0:
                        errors.append(f"FUNDS donations must have item cost greater than 0.00")
                        continue
                elif donation_type == 'GOODS':
                    # GOODS should have item_cost >= 0
                    if item_cost < 0:
                        errors.append(f"GOODS donations cannot have negative item cost")
                        continue
                
                # If item passed validation, add to validated list
                validated_items.append(item_info)
                
                # Add to total value (item_cost * quantity)
                total_value += Decimal(str(item_cost)) * Decimal(str(quantity))
            
            # Check if there were any validation errors
            if errors:
                db.session.rollback()
                for error in errors:
                    flash(error, 'danger')
                form_data = _get_donation_form_data()
                form_data['form_data'] = request.form
                return render_template('donations/create.html', **form_data)
            
            # All items validated - now persist them
            for item_info in validated_items:
                donation_item = DonationItem()
                donation_item.donation_id = donation.donation_id
                donation_item.item_id = item_info['item_id']
                donation_item.donation_type = item_info['donation_type']
                # FUNDS items: Server-side enforcement - quantity is always 1.00
                donation_item.item_qty = Decimal('1.00') if item_info['donation_type'] == 'FUNDS' else item_info['quantity']
                donation_item.item_cost = item_info['item_cost']
                donation_item.uom_code = item_info['uom_code']
                donation_item.currency_code = item_info['currency_code']
                donation_item.location_name = item_info['location_name'].upper()
                donation_item.status_code = 'P'
                donation_item.comments_text = item_info['item_comments'].upper() if item_info['item_comments'] else None
                
                add_audit_fields(donation_item, current_user, is_new=True)
                
                # Verify fields remain NULL for status 'P' (Pending verification)
                # They will be populated only when item is verified (status='V')
                donation_item.verify_by_id = None
                donation_item.verify_dtime = None
                
                db.session.add(donation_item)
            
            # Note: Total donation value may differ from sum of item costs due to currency differences
            # (e.g., donation received in USD, items valued in JMD)
            # Show informational message if values differ significantly, but allow submission
            # Logistics Manager will review and verify during the verification process
            value_difference = abs(tot_item_cost_value - total_value)
            if value_difference > Decimal('0.01'):
                flash(f'Note: Total Donation Value (J${tot_item_cost_value:,.2f}) differs from sum of item costs (J${total_value:,.2f}). This may be due to currency differences and will be reviewed during verification.', 'info')
            
            # Set total item cost from manually entered value
            donation.tot_item_cost = tot_item_cost_value
            
            # Handle document uploads - validate all first, then save
            document_count = 0
            doc_errors = []
            validated_docs = []
            uploaded_files = request.files.getlist('document_files')
            document_types = request.form.getlist('document_type')
            document_descs = request.form.getlist('document_desc')
            
            upload_folder = current_app.config.get('UPLOAD_FOLDER')
            
            for idx, uploaded_file in enumerate(uploaded_files):
                if uploaded_file and uploaded_file.filename and uploaded_file.filename.strip():
                    original_filename = uploaded_file.filename.strip()
                    
                    mime_type = mimetypes.guess_type(original_filename)[0]
                    if mime_type not in ['application/pdf', 'image/jpeg']:
                        doc_errors.append(f'Invalid file type for document {idx + 1}. Only PDF and JPEG files are allowed.')
                        continue
                    
                    doc_type = document_types[idx] if idx < len(document_types) else 'Other'
                    doc_desc = document_descs[idx] if idx < len(document_descs) else ''
                    
                    if not doc_desc.strip():
                        doc_errors.append(f'Document description is required for document {idx + 1}.')
                        continue
                    
                    import uuid
                    safe_base_name = secure_filename(original_filename)
                    unique_filename = f"{uuid.uuid4().hex[:8]}_{safe_base_name}"
                    
                    uploaded_file.seek(0, os.SEEK_END)
                    file_size_bytes = uploaded_file.tell()
                    uploaded_file.seek(0)
                    
                    validated_docs.append({
                        'file': uploaded_file,
                        'unique_filename': unique_filename,
                        'doc_type': doc_type.upper(),
                        'doc_desc': doc_desc.strip().upper(),
                        'mime_type': mime_type,
                        'file_size_bytes': file_size_bytes,
                        'idx': idx
                    })
            
            if doc_errors:
                db.session.rollback()
                for error in doc_errors:
                    flash(error, 'danger')
                form_data = _get_donation_form_data()
                form_data['form_data'] = request.form
                return render_template('donations/create.html', **form_data)
            
            if validated_docs:
                if not upload_folder:
                    db.session.rollback()
                    flash('File storage is not configured. Please contact the system administrator to set up the upload folder before attaching documents.', 'danger')
                    form_data = _get_donation_form_data()
                    form_data['form_data'] = request.form
                    return render_template('donations/create.html', **form_data)
                
                if not os.path.exists(upload_folder):
                    os.makedirs(upload_folder, exist_ok=True)
                
                saved_files = []
                try:
                    for doc_info in validated_docs:
                        try:
                            file_path = safe_join(upload_folder, doc_info['unique_filename'])
                        except ValueError as path_err:
                            raise ValueError(f"Invalid file path for document: {path_err}")
                        doc_info['file'].save(file_path)
                        saved_files.append(file_path)
                        
                        donation_doc = DonationDoc()
                        donation_doc.donation_id = donation.donation_id
                        donation_doc.document_type = doc_info['doc_type']
                        donation_doc.document_desc = doc_info['doc_desc']
                        donation_doc.file_name = doc_info['unique_filename']
                        donation_doc.file_type = doc_info['mime_type']
                        
                        file_size_bytes = doc_info['file_size_bytes']
                        if file_size_bytes < 1024:
                            donation_doc.file_size = f'{file_size_bytes}B'
                        elif file_size_bytes < 1024 * 1024:
                            donation_doc.file_size = f'{file_size_bytes / 1024:.1f}KB'
                        else:
                            donation_doc.file_size = f'{file_size_bytes / (1024 * 1024):.1f}MB'
                        
                        add_audit_fields(donation_doc, current_user, is_new=True)
                        db.session.add(donation_doc)
                        document_count += 1
                except Exception as save_error:
                    for saved_path in saved_files:
                        try:
                            os.remove(saved_path)
                        except OSError:
                            pass
                    db.session.rollback()
                    current_app.logger.exception('Failed to save document')
                    flash('Failed to save document. Please try again or contact support.', 'danger')
                    form_data = _get_donation_form_data()
                    form_data['form_data'] = request.form
                    return render_template('donations/create.html', **form_data)
            
            db.session.commit()
            
            log_data_event(
                action=AuditAction.CREATE,
                user_id=current_user.user_id,
                entity_type='donation',
                entity_id=donation.donation_id,
                outcome=AuditOutcome.SUCCESS,
                details={
                    'item_count': len(item_data),
                    'document_count': document_count,
                    'total_value': str(tot_item_cost_value),
                    'donor_id': donation.donor_id
                }
            )
            
            flash(f'Donation #{donation.donation_id} created successfully with {len(item_data)} item(s) and {document_count} document(s).', 'success')
            return redirect(url_for('donations.view_donation', donation_id=donation.donation_id))
            
        except ValueError as e:
            db.session.rollback()
            current_app.logger.exception('Validation error creating donation')
            flash('Validation error. Please check your input and try again.', 'danger')
            form_data = _get_donation_form_data()
            form_data['form_data'] = request.form
            return render_template('donations/create.html', **form_data)
        except IntegrityError as e:
            db.session.rollback()
            error_message = str(e.orig) if hasattr(e, 'orig') else str(e)
            current_app.logger.error("Donation create IntegrityError: %s", sanitize_exception_for_log(e))
            
            # Check if it's a duplicate donation item error
            if ('pk_donation_item' in error_message or 
                'duplicate key' in error_message.lower() or 
                'UNIQUE constraint failed' in error_message):
                flash('Duplicate item detected. Each item can only be added once per donation. Please check your items and try again.', 'danger')
            else:
                flash(f'Unable to create donation due to a database constraint. Please check your input and try again.', 'danger')
                current_app.logger.error("Full IntegrityError details: %s", sanitize_exception_for_log(e))
            
            form_data = _get_donation_form_data()
            form_data['form_data'] = request.form
            return render_template('donations/create.html', **form_data)
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('Unexpected error creating donation')
            flash('An unexpected error occurred. Please try again or contact support.', 'danger')
            form_data = _get_donation_form_data()
            form_data['form_data'] = request.form
            return render_template('donations/create.html', **form_data)
    
    form_data = _get_donation_form_data()
    
    if not form_data['donors']:
        flash('No donors available. Please create a donor first.', 'warning')
        return redirect(url_for('donations.list_donations'))
    
    if not form_data['custodians']:
        flash('No custodians available. Please create a custodian first.', 'warning')
        return redirect(url_for('donations.list_donations'))
    
    if not form_data['items']:
        flash('No items available. Please create items first.', 'warning')
        return redirect(url_for('donations.list_donations'))
    
    if not form_data['uoms']:
        flash('No units of measure available. Please create UOMs first.', 'warning')
        return redirect(url_for('donations.list_donations'))
    
    return render_template('donations/create.html', **form_data)


@donations_bp.route('/<int:donation_id>')
@login_required
@feature_required('donation_management')
def view_donation(donation_id):
    """View donation details including all items"""
    donation = Donation.query.get_or_404(donation_id)
    
    items_with_details = []
    for donation_item in donation.items:
        items_with_details.append({
            'item': donation_item.item,
            'item_qty': donation_item.item_qty,
            'uom': donation_item.uom,
            'location_name': donation_item.location_name,
            'status_code': donation_item.status_code,
            'comments_text': donation_item.comments_text,
            'version_nbr': donation_item.version_nbr
        })
    
    return render_template('donations/view.html', 
                         donation=donation,
                         items=items_with_details)


@donations_bp.route('/<int:donation_id>/edit', methods=['GET', 'POST'])
@login_required
@feature_required('donation_management')
def edit_donation(donation_id):
    """
    Edit donation header and items (only for 'Entered' status).
    Supports adding new items, deleting existing items, and updating header fields.
    Uses optimistic locking for concurrency control.
    """
    from app.db.models import ItemCategory
    
    donation = Donation.query.get_or_404(donation_id)
    
    # Prevent editing of verified or processed donations
    if donation.status_code == 'V':
        flash('Cannot edit a verified donation. Donation has been verified and is now read-only.', 'danger')
        return redirect(url_for('donations.view_donation', donation_id=donation_id))
    
    if donation.status_code == 'P':
        flash('Cannot edit a processed donation. It has already been added to warehouse inventory.', 'danger')
        return redirect(url_for('donations.view_donation', donation_id=donation_id))
    
    if request.method == 'POST':
        try:
            from decimal import Decimal
            from app.security.param_validation import safe_version_number, safe_id, safe_amount
            
            version_nbr = safe_version_number(request.form.get('version_nbr', 0))
            
            if version_nbr != donation.version_nbr:
                flash('This donation has been modified by another user. Please reload and try again.', 'danger')
                return redirect(url_for('donations.edit_donation', donation_id=donation_id))
            
            # Header fields
            donor_id = request.form.get('donor_id')
            event_id = request.form.get('event_id')
            custodian_id = request.form.get('custodian_id')
            donation_desc = request.form.get('donation_desc', '').strip()
            received_date_str = request.form.get('received_date')
            comments_text = request.form.get('comments_text', '').strip()
            origin_country_id = request.form.get('origin_country_id')
            origin_address1 = request.form.get('origin_address1_text', '').strip()
            origin_address2 = request.form.get('origin_address2_text', '').strip()
            
            # Cost fields
            tot_item_cost_str = request.form.get('tot_item_cost', '0.00').strip()
            storage_cost_str = request.form.get('storage_cost', '0.00').strip()
            haulage_cost_str = request.form.get('haulage_cost', '0.00').strip()
            other_cost_str = request.form.get('other_cost', '0.00').strip()
            other_cost_desc = request.form.get('other_cost_desc', '').strip()
            
            errors = []
            
            # Validate header fields
            if not donor_id:
                errors.append('Donor is required')
            if not event_id:
                errors.append('Event is required')
            if not custodian_id:
                errors.append('Custodian is required')
            if not donation_desc:
                errors.append('Donation description is required')
            if not received_date_str:
                errors.append('Received date is required')
            if not origin_country_id:
                errors.append('Origin country is required')
            
            received_date = None
            if received_date_str:
                received_date = datetime.strptime(received_date_str, '%Y-%m-%d').date()
                if received_date > date.today():
                    errors.append('Received date cannot be in the future')
            
            # Validate cost fields using safe_amount (handles InvalidOperation gracefully)
            tot_item_cost_value = safe_amount(tot_item_cost_str, default='0.00', min_amount=Decimal('0'))
            if tot_item_cost_value <= 0:
                errors.append('Total Donation Value must be greater than 0')
            
            storage_cost_value = safe_amount(storage_cost_str, default='0.00', min_amount=Decimal('0'))
            haulage_cost_value = safe_amount(haulage_cost_str, default='0.00', min_amount=Decimal('0'))
            other_cost_value = safe_amount(other_cost_str, default='0.00', min_amount=Decimal('0'))
            
            if other_cost_value > 0 and not other_cost_desc:
                errors.append('Other cost description is required when other cost is greater than 0')
            
            # Parse items from form
            item_data = []
            existing_item_ids = []
            item_ids_seen = set()
            
            for key in request.form.keys():
                if key.startswith('item_id_'):
                    item_num = key.split('_')[-1]
                    item_id = request.form.get(f'item_id_{item_num}')
                    donation_type = request.form.get(f'donation_type_{item_num}', 'GOODS').upper()
                    quantity_str = request.form.get(f'quantity_{item_num}')
                    item_cost_str = request.form.get(f'item_cost_{item_num}', '0.00')
                    uom_id = request.form.get(f'uom_id_{item_num}')
                    currency_code = request.form.get(f'currency_code_{item_num}')
                    location_name = request.form.get(f'location_name_{item_num}', 'DONATION RECEIVED').strip()
                    item_comments = request.form.get(f'item_comments_{item_num}', '').strip()
                    existing_donation_item_id = request.form.get(f'donation_item_id_{item_num}')
                    
                    if item_id:
                        if item_id in item_ids_seen:
                            errors.append(f'Duplicate item detected in row #{item_num}. Each item can only be added once per donation.')
                            continue
                        item_ids_seen.add(item_id)
                        
                        if donation_type not in ('GOODS', 'FUNDS'):
                            errors.append(f'Invalid donation type for item #{item_num}. Must be GOODS or FUNDS.')
                        
                        from app.security.param_validation import safe_quantity, safe_amount as safe_item_cost
                        
                        quantity_value = None
                        if not quantity_str:
                            errors.append(f'Quantity is required for item #{item_num}')
                        else:
                            quantity_value = safe_quantity(quantity_str, min_qty=Decimal('0'))
                            if quantity_value < 0:
                                errors.append(f'Quantity must be >= 0 for item #{item_num}')
                        
                        item_cost_value = safe_item_cost(item_cost_str, min_amount=Decimal('0'))
                        
                        # Validate based on donation type: GOODS needs uom_code, FUNDS needs currency_code
                        if donation_type == 'GOODS':
                            if not uom_id:
                                errors.append(f'UOM is required for GOODS item #{item_num}')
                        elif donation_type == 'FUNDS':
                            if not currency_code:
                                errors.append(f'Currency is required for FUNDS item #{item_num}')
                        
                        is_existing_item = request.form.get(f'is_existing_{item_num}', 'false') == 'true'
                        
                        try:
                            item_data.append({
                                'item_id': int(item_id),
                                'donation_type': donation_type,
                                'quantity': quantity_value,
                                'item_cost': item_cost_value,
                                'uom_code': uom_id if donation_type == 'GOODS' else None,
                                'currency_code': currency_code if donation_type == 'FUNDS' else None,
                                'location_name': location_name,
                                'item_comments': item_comments,
                                'is_existing': is_existing_item
                            })
                            if is_existing_item:
                                existing_item_ids.append(int(item_id))
                        except ValueError as ve:
                            errors.append(f'Invalid data for item #{item_num}: {str(ve)}')
            
            if not item_data:
                errors.append('At least one donation item is required')
            
            if errors:
                for error in errors:
                    flash(error, 'danger')
                form_data = _get_donation_form_data()
                form_data['donation'] = donation
                form_data['form_data'] = request.form
                form_data['today'] = date.today().isoformat()
                
                # Get existing items for restoration
                existing_items = []
                for di in donation.items:
                    existing_items.append({
                        'is_existing': True,
                        'item_id': di.item_id,
                        'item_name': di.item.item_name if di.item else 'Unknown',
                        'donation_type': di.donation_type,
                        'quantity': float(di.item_qty) if di.item_qty else 0,
                        'item_cost': float(di.item_cost) if di.item_cost else 0,
                        'uom_code': di.uom_code,
                        'currency_code': di.currency_code,
                        'location_name': di.location_name or 'DONATION RECEIVED',
                        'comments': di.comments_text or ''
                    })
                form_data['existing_items'] = existing_items
                
                return render_template('donations/edit.html', **form_data)
            
            # Update header fields
            donation.donor_id = int(donor_id)
            donation.event_id = int(event_id)
            donation.custodian_id = int(custodian_id)
            donation.donation_desc = donation_desc.upper()
            donation.received_date = received_date
            donation.origin_country_id = int(origin_country_id) if origin_country_id else None
            donation.origin_address1_text = origin_address1.upper() if origin_address1 else None
            donation.origin_address2_text = origin_address2.upper() if origin_address2 else None
            donation.comments_text = comments_text.upper() if comments_text else None
            donation.storage_cost = storage_cost_value
            donation.haulage_cost = haulage_cost_value
            donation.other_cost = other_cost_value
            donation.other_cost_desc = other_cost_desc.upper() if other_cost_desc else None
            
            # Delete items that are no longer in the form
            # Get current item_ids from the donation
            current_item_ids = [di.item_id for di in donation.items]
            # Form submitted item_ids
            submitted_item_ids = [item['item_id'] for item in item_data]
            # Items to delete are those in database but not in form
            items_to_delete = [iid for iid in current_item_ids if iid not in submitted_item_ids]
            for iid in items_to_delete:
                item_to_delete = DonationItem.query.get((donation.donation_id, iid))
                if item_to_delete:
                    db.session.delete(item_to_delete)
            
            # Calculate total item cost and update/add items
            total_item_cost = Decimal('0.00')
            
            for item_info in item_data:
                item_cost = item_info['item_cost']
                # FUNDS items: Server-side enforcement - quantity is always 1.00
                quantity = Decimal('1.00') if item_info['donation_type'] == 'FUNDS' else item_info['quantity']
                line_total = item_cost * quantity
                total_item_cost += line_total
                
                if item_info['is_existing']:
                    # Update existing item using composite key (donation_id, item_id)
                    existing_item = DonationItem.query.get((donation.donation_id, item_info['item_id']))
                    if existing_item:
                        existing_item.donation_type = item_info['donation_type']
                        existing_item.item_qty = quantity
                        existing_item.item_cost = item_cost
                        existing_item.uom_code = item_info['uom_code']
                        existing_item.currency_code = item_info['currency_code']
                        existing_item.location_name = item_info['location_name'].upper() if item_info['location_name'] else 'DONATION RECEIVED'
                        existing_item.comments_text = item_info['item_comments'].upper() if item_info['item_comments'] else None
                        add_audit_fields(existing_item, current_user, is_new=False)
                else:
                    # Add new item
                    new_item = DonationItem()
                    new_item.donation_id = donation.donation_id
                    new_item.item_id = item_info['item_id']
                    new_item.donation_type = item_info['donation_type']
                    new_item.item_qty = quantity
                    new_item.item_cost = item_cost
                    new_item.uom_code = item_info['uom_code']
                    new_item.currency_code = item_info['currency_code']
                    new_item.location_name = item_info['location_name'].upper() if item_info['location_name'] else 'DONATION RECEIVED'
                    new_item.comments_text = item_info['item_comments'].upper() if item_info['item_comments'] else None
                    new_item.status_code = 'P'
                    add_audit_fields(new_item, current_user, is_new=True)
                    new_item.verify_by_id = None
                    new_item.verify_dtime = None
                    db.session.add(new_item)
            
            # Set total donation value from user input (user-entered value)
            donation.tot_item_cost = tot_item_cost_value
            
            add_audit_fields(donation, current_user, is_new=False)
            
            db.session.commit()
            
            items_added_count = len([i for i in item_data if not i['is_existing']])
            items_removed_count = len(items_to_delete)
            log_data_event(
                action=AuditAction.UPDATE,
                user_id=current_user.user_id,
                entity_type='donation',
                entity_id=donation.donation_id,
                outcome=AuditOutcome.SUCCESS,
                details={
                    'items_added': items_added_count,
                    'items_removed': items_removed_count,
                    'total_value': str(tot_item_cost_value)
                }
            )
            
            flash(f'Donation #{donation.donation_id} updated successfully', 'success')
            return redirect(url_for('donations.view_donation', donation_id=donation.donation_id))
            
        except StaleDataError:
            db.session.rollback()
            flash('This donation has been modified by another user. Please reload and try again.', 'danger')
            return redirect(url_for('donations.edit_donation', donation_id=donation_id))
        except IntegrityError as e:
            db.session.rollback()
            current_app.logger.exception('Database error editing donation')
            flash('A database error occurred. Please check your input and try again.', 'danger')
            return redirect(url_for('donations.edit_donation', donation_id=donation_id))
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('Unexpected error editing donation')
            flash('An unexpected error occurred. Please try again or contact support.', 'danger')
            return redirect(url_for('donations.edit_donation', donation_id=donation_id))
    
    # GET request - load form with existing data
    form_data = _get_donation_form_data()
    form_data['donation'] = donation
    form_data['today'] = date.today().isoformat()
    
    # Get existing items with full details
    # Use item_id as identifier since DonationItem uses composite key (donation_id, item_id)
    existing_items = []
    for di in donation.items:
        existing_items.append({
            'is_existing': True,
            'item_id': di.item_id,
            'item_name': di.item.item_name if di.item else 'Unknown',
            'donation_type': di.donation_type,
            'quantity': float(di.item_qty) if di.item_qty else 0,
            'item_cost': float(di.item_cost) if di.item_cost else 0,
            'uom_code': di.uom_code,
            'currency_code': di.currency_code,
            'location_name': di.location_name or 'DONATION RECEIVED',
            'comments': di.comments_text or ''
        })
    form_data['existing_items'] = existing_items
    
    return render_template('donations/edit.html', **form_data)


@donations_bp.route('/<int:donation_id>/delete', methods=['POST'])
@login_required
@feature_required('donation_management')
def delete_donation(donation_id):
    """Delete donation (only if no items exist)"""
    donation = Donation.query.get_or_404(donation_id)
    
    # Prevent deleting verified or processed donations
    if donation.status_code == 'V':
        flash('Cannot delete a verified donation. Donation has been verified and is now read-only.', 'danger')
        return redirect(url_for('donations.view_donation', donation_id=donation_id))
    
    # Prevent deleting processed donations (already in warehouse)
    if donation.status_code == 'P':
        flash('Cannot delete a processed donation. It has already been added to warehouse inventory.', 'danger')
        return redirect(url_for('donations.view_donation', donation_id=donation_id))
    
    if donation.items:
        flash('Cannot delete donation with existing items. Remove all items first.', 'danger')
        return redirect(url_for('donations.view_donation', donation_id=donation_id))
    
    try:
        db.session.delete(donation)
        db.session.commit()
        flash(f'Donation #{donation_id} deleted successfully', 'success')
        return redirect(url_for('donations.list_donations'))
    except IntegrityError as e:
        db.session.rollback()
        current_app.logger.exception('Cannot delete donation')
        flash('Cannot delete donation due to existing dependencies.', 'danger')
        return redirect(url_for('donations.view_donation', donation_id=donation_id))


@donations_bp.route('/<int:donation_id>/items/add', methods=['GET', 'POST'])
@login_required
@feature_required('donation_management')
def add_donation_item(donation_id):
    """Add item to donation"""
    donation = Donation.query.get_or_404(donation_id)
    
    # Prevent adding items to verified or processed donations
    if donation.status_code == 'V':
        flash('Cannot add items to a verified donation. Donation has been verified and items cannot be modified.', 'danger')
        return redirect(url_for('donations.view_donation', donation_id=donation_id))
    
    # Prevent adding items to processed donations (already in warehouse)
    if donation.status_code == 'P':
        flash('Cannot add items to a processed donation. It has already been added to warehouse inventory.', 'danger')
        return redirect(url_for('donations.view_donation', donation_id=donation_id))
    
    if request.method == 'POST':
        try:
            item_id = request.form.get('item_id')
            item_qty = request.form.get('item_qty')
            uom_code = request.form.get('uom_code')
            location_name = request.form.get('location_name', '').strip()
            comments_text = request.form.get('comments_text', '').strip()
            
            errors = []
            
            if not item_id:
                errors.append('Item is required')
            if not item_qty:
                errors.append('Quantity is required')
            elif Decimal(item_qty) <= 0:
                errors.append('Quantity must be greater than 0')
            if not uom_code:
                errors.append('Unit of measure is required')
            if not location_name:
                errors.append('Location is required')
            
            # Check for duplicate item before attempting database insert
            duplicate_item_id = None
            if item_id:
                existing = DonationItem.query.filter_by(
                    donation_id=donation_id,
                    item_id=int(item_id)
                ).first()
                if existing:
                    errors.append('This item has already been added to the donation. Please edit the existing item instead.')
                    duplicate_item_id = item_id
            
            if errors:
                for error in errors:
                    flash(error, 'danger')
                items = Item.query.order_by(Item.item_name).all()
                uoms = UnitOfMeasure.query.order_by(UnitOfMeasure.uom_code).all()
                return render_template('donations/add_item.html',
                                     donation=donation,
                                     items=items,
                                     uoms=uoms,
                                     form_data=request.form,
                                     duplicate_item_id=duplicate_item_id)
            
            donation_item = DonationItem()
            donation_item.donation_id = donation_id
            donation_item.item_id = int(item_id)
            donation_item.item_qty = Decimal(item_qty)
            donation_item.uom_code = uom_code
            donation_item.location_name = location_name.upper()
            # Set status based on parent donation status
            # Items added to unverified donations (status='E') should be pending
            donation_item.status_code = 'P' if donation.status_code == 'E' else 'V'
            donation_item.comments_text = comments_text.upper() if comments_text else None
            
            add_audit_fields(donation_item, current_user, is_new=True)
            
            # Verify fields remain NULL for pending items (status='P')
            # They will be populated only when item is verified (status='V')
            if donation_item.status_code == 'P':
                donation_item.verify_by_id = None
                donation_item.verify_dtime = None
            else:
                current_timestamp = jamaica_now()
                donation_item.verify_by_id = session_utils.get_user_name()
                donation_item.verify_dtime = current_timestamp
            
            db.session.add(donation_item)
            db.session.commit()
            
            flash(f'Item added to donation successfully', 'success')
            return redirect(url_for('donations.view_donation', donation_id=donation_id))
            
        except IntegrityError as e:
            db.session.rollback()
            error_message = str(e.orig) if hasattr(e, 'orig') else str(e)
            
            if ('pk_donation_item' in error_message or 
                'duplicate key' in error_message.lower() or 
                'UNIQUE constraint failed' in error_message):
                flash('This item has already been added to the donation. Please edit the existing item instead.', 'danger')
                items = Item.query.order_by(Item.item_name).all()
                uoms = UnitOfMeasure.query.order_by(UnitOfMeasure.uom_code).all()
                return render_template('donations/add_item.html',
                                     donation=donation,
                                     items=items,
                                     uoms=uoms,
                                     form_data=request.form,
                                     duplicate_item_id=item_id)
            else:
                flash('Unable to add item due to a database constraint. Please check your input and try again.', 'danger')
                items = Item.query.order_by(Item.item_name).all()
                uoms = UnitOfMeasure.query.order_by(UnitOfMeasure.uom_code).all()
                return render_template('donations/add_item.html',
                                     donation=donation,
                                     items=items,
                                     uoms=uoms,
                                     form_data=request.form)
        except Exception as e:
            db.session.rollback()
            flash('An unexpected error occurred. Please try again.', 'danger')
            return redirect(url_for('donations.add_donation_item', donation_id=donation_id))
    
    items = Item.query.order_by(Item.item_name).all()
    uoms = UnitOfMeasure.query.order_by(UnitOfMeasure.uom_code).all()
    
    if not items:
        flash('No items available. Please create items first.', 'warning')
        return redirect(url_for('donations.view_donation', donation_id=donation_id))
    
    return render_template('donations/add_item.html',
                         donation=donation,
                         items=items,
                         uoms=uoms)


@donations_bp.route('/<int:donation_id>/items/<int:item_id>/edit', methods=['GET', 'POST'])
@login_required
@feature_required('donation_management')
def edit_donation_item(donation_id, item_id):
    """Edit donation item (optimistic locking)"""
    donation = Donation.query.get_or_404(donation_id)
    donation_item = DonationItem.query.get_or_404((donation_id, item_id))
    
    # Prevent editing items from verified or processed donations
    if donation.status_code == 'V':
        flash('Cannot edit items from a verified donation. Donation has been verified and items cannot be modified.', 'danger')
        return redirect(url_for('donations.view_donation', donation_id=donation_id))
    
    # Prevent editing of processed donations (already in warehouse)
    if donation.status_code == 'P':
        flash('Cannot edit items from a processed donation. It has already been added to warehouse inventory.', 'danger')
        return redirect(url_for('donations.view_donation', donation_id=donation_id))
    
    if request.method == 'POST':
        try:
            version_nbr = int(request.form.get('version_nbr', 0))
            
            if version_nbr != donation_item.version_nbr:
                flash('This item has been modified by another user. Please reload and try again.', 'danger')
                return redirect(url_for('donations.edit_donation_item', 
                                      donation_id=donation_id, 
                                      item_id=item_id))
            
            item_qty = request.form.get('item_qty')
            uom_code = request.form.get('uom_code')
            location_name = request.form.get('location_name', '').strip()
            status_code = request.form.get('status_code')
            comments_text = request.form.get('comments_text', '').strip()
            
            errors = []
            
            if not item_qty:
                errors.append('Quantity is required')
            elif Decimal(item_qty) <= 0:
                errors.append('Quantity must be greater than 0')
            if not uom_code:
                errors.append('Unit of measure is required')
            if not location_name:
                errors.append('Location is required')
            if not status_code or status_code not in ['P', 'V']:
                errors.append('Valid status code is required')
            
            if errors:
                for error in errors:
                    flash(error, 'danger')
                uoms = UnitOfMeasure.query.order_by(UnitOfMeasure.uom_code).all()
                return render_template('donations/edit_item.html',
                                     donation=donation,
                                     donation_item=donation_item,
                                     uoms=uoms,
                                     form_data=request.form)
            
            donation_item.item_qty = Decimal(item_qty)
            donation_item.uom_code = uom_code
            
            donation_item.location_name = location_name.upper()
            donation_item.status_code = status_code
            donation_item.comments_text = comments_text.upper() if comments_text else None
            
            add_audit_fields(donation_item, current_user, is_new=False)
            
            # Verify fields are only populated for verified items (status='V')
            # They remain/become NULL for pending items (status='P')
            if status_code == 'V':
                donation_item.verify_by_id = session_utils.get_user_name()
                donation_item.verify_dtime = jamaica_now()
            else:
                # Clear verify fields when status is 'P' (Pending)
                donation_item.verify_by_id = None
                donation_item.verify_dtime = None
            
            db.session.commit()
            
            flash(f'Donation item updated successfully', 'success')
            return redirect(url_for('donations.view_donation', donation_id=donation_id))
            
        except StaleDataError:
            db.session.rollback()
            flash('This item has been modified by another user. Please reload and try again.', 'danger')
            return redirect(url_for('donations.edit_donation_item', 
                                  donation_id=donation_id, 
                                  item_id=item_id))
        except IntegrityError as e:
            db.session.rollback()
            current_app.logger.exception('Database error editing donation item')
            flash('A database error occurred. Please check your input and try again.', 'danger')
            return redirect(url_for('donations.edit_donation_item', 
                                  donation_id=donation_id, 
                                  item_id=item_id))
    
    uoms = UnitOfMeasure.query.order_by(UnitOfMeasure.uom_code).all()
    
    return render_template('donations/edit_item.html',
                         donation=donation,
                         donation_item=donation_item,
                         uoms=uoms)


@donations_bp.route('/<int:donation_id>/items/<int:item_id>/delete', methods=['POST'])
@login_required
@feature_required('donation_management')
def delete_donation_item(donation_id, item_id):
    """Delete donation item"""
    donation = Donation.query.get_or_404(donation_id)
    donation_item = DonationItem.query.get_or_404((donation_id, item_id))
    
    # Prevent deleting items from verified or processed donations
    if donation.status_code == 'V':
        flash('Cannot delete items from a verified donation. Donation has been verified and items cannot be modified.', 'danger')
        return redirect(url_for('donations.view_donation', donation_id=donation_id))
    
    # Prevent deleting items from processed donations (already in warehouse)
    if donation.status_code == 'P':
        flash('Cannot delete items from a processed donation. It has already been added to warehouse inventory.', 'danger')
        return redirect(url_for('donations.view_donation', donation_id=donation_id))
    
    try:
        db.session.delete(donation_item)
        db.session.commit()
        flash(f'Donation item removed successfully', 'success')
        return redirect(url_for('donations.view_donation', donation_id=donation_id))
    except IntegrityError as e:
        db.session.rollback()
        current_app.logger.exception('Cannot delete donation item')
        flash('Cannot delete item due to existing dependencies.', 'danger')
        return redirect(url_for('donations.view_donation', donation_id=donation_id))


# =============================================================================
# WORKFLOW B - DONATION VERIFICATION
# =============================================================================

@donations_bp.route('/verify')
@login_required
@feature_required('donation_verification')
def verify_list():
    """
    List donations pending verification (status_code = 'E').
    Only accessible to LOGISTICS_MANAGER role.
    """
    search_query = request.args.get('search', '').strip()
    donor_filter = request.args.get('donor_id', type=int)
    event_filter = request.args.get('event_id', type=int)
    
    query = Donation.query.filter_by(status_code='E')
    
    if donor_filter:
        query = query.filter_by(donor_id=donor_filter)
    
    if event_filter:
        query = query.filter_by(event_id=event_filter)
    
    if search_query:
        search_pattern = '%' + search_query + '%'
        query = query.filter(
            db.or_(
                Donation.donation_desc.ilike(search_pattern),
                Donation.comments_text.ilike(search_pattern)
            )
        )
    
    donations = query.order_by(Donation.received_date.desc()).all()
    
    pending_count = Donation.query.filter_by(status_code='E').count()
    
    donors = Donor.query.order_by(Donor.donor_name).all()
    events = Event.query.filter_by(status_code='A').order_by(Event.event_name).all()
    
    return render_template('donations/verify_list.html',
                         donations=donations,
                         pending_count=pending_count,
                         search_query=search_query,
                         donor_filter=donor_filter,
                         event_filter=event_filter,
                         donors=donors,
                         events=events)


@donations_bp.route('/verify/<int:donation_id>', methods=['GET', 'POST'])
@login_required
@feature_required('donation_verification')
def verify_donation_detail(donation_id):
    """
    Verification detail page for a donation.
    GET: Load donation for verification with editable fields.
    POST: Validate and verify the donation in a single transaction.
    """
    from app.db.models import ItemCategory
    
    donation = Donation.query.get_or_404(donation_id)
    
    if donation.status_code != 'E':
        if donation.status_code == 'V':
            flash('This donation has already been verified.', 'info')
        elif donation.status_code == 'P':
            flash('This donation has already been processed into warehouse inventory.', 'info')
        return redirect(url_for('donations.view_donation', donation_id=donation_id))
    
    if request.method == 'POST':
        try:
            version_nbr = request.form.get('version_nbr', type=int)
            if version_nbr is None:
                flash('Missing version information. Please reload and try again.', 'danger')
                return redirect(url_for('donations.verify_donation_detail', donation_id=donation_id))
            
            if donation.version_nbr != version_nbr:
                flash('This donation was changed by another user. Please reload and try again.', 'danger')
                return redirect(url_for('donations.verify_donation_detail', donation_id=donation_id))
            
            donor_id = request.form.get('donor_id')
            event_id = request.form.get('event_id')
            custodian_id = request.form.get('custodian_id')
            donation_desc = request.form.get('donation_desc', '').strip()
            received_date_str = request.form.get('received_date')
            origin_country_id = request.form.get('origin_country_id')
            origin_address1 = request.form.get('origin_address1_text', '').strip()
            origin_address2 = request.form.get('origin_address2_text', '').strip()
            comments_text = request.form.get('comments_text', '').strip()
            
            tot_item_cost_str = request.form.get('tot_item_cost', '0.00').strip()
            storage_cost_str = request.form.get('storage_cost', '0.00').strip()
            haulage_cost_str = request.form.get('haulage_cost', '0.00').strip()
            other_cost_str = request.form.get('other_cost', '0.00').strip()
            other_cost_desc = request.form.get('other_cost_desc', '').strip()
            
            errors = []
            
            if not donor_id:
                errors.append('Donor is required')
            if not event_id:
                errors.append('Event is required')
            if not custodian_id:
                errors.append('Custodian is required')
            if not donation_desc:
                errors.append('Donation description is required')
            if not received_date_str:
                errors.append('Received date is required')
            if not origin_country_id:
                errors.append('Origin country is required')
            
            received_date = None
            if received_date_str:
                received_date = datetime.strptime(received_date_str, '%Y-%m-%d').date()
                if received_date > date.today():
                    errors.append('Received date cannot be in the future')
            
            tot_item_cost_value = Decimal('0.00')
            try:
                tot_item_cost_value = Decimal(tot_item_cost_str) if tot_item_cost_str else Decimal('0.00')
                if tot_item_cost_value <= 0:
                    errors.append('Total Donation Value must be greater than 0')
            except:
                errors.append('Invalid Total Donation Value')
            
            storage_cost_value = Decimal('0.00')
            try:
                storage_cost_value = Decimal(storage_cost_str) if storage_cost_str else Decimal('0.00')
                if storage_cost_value < 0:
                    errors.append('Storage cost must be >= 0')
            except:
                errors.append('Invalid storage cost value')
            
            haulage_cost_value = Decimal('0.00')
            try:
                haulage_cost_value = Decimal(haulage_cost_str) if haulage_cost_str else Decimal('0.00')
                if haulage_cost_value < 0:
                    errors.append('Haulage cost must be >= 0')
            except:
                errors.append('Invalid haulage cost value')
            
            other_cost_value = Decimal('0.00')
            try:
                other_cost_value = Decimal(other_cost_str) if other_cost_str else Decimal('0.00')
                if other_cost_value < 0:
                    errors.append('Other cost must be >= 0')
            except:
                errors.append('Invalid other cost value')
            
            if other_cost_value > 0 and not other_cost_desc:
                errors.append('Other cost description is required when other cost is greater than 0')
            
            item_data = []
            item_ids_in_form = set()
            for key in request.form.keys():
                if key.startswith('item_id_'):
                    item_num = key.split('_')[-1]
                    item_id = request.form.get(f'item_id_{item_num}')
                    donation_type = request.form.get(f'donation_type_{item_num}', 'GOODS').upper()
                    quantity_str = request.form.get(f'quantity_{item_num}')
                    item_cost_str = request.form.get(f'item_cost_{item_num}', '0.00')
                    uom_code = request.form.get(f'uom_id_{item_num}')
                    currency_code = request.form.get(f'currency_code_{item_num}')
                    location_name = request.form.get(f'location_name_{item_num}', 'DONATION RECEIVED').strip()
                    item_comments = request.form.get(f'item_comments_{item_num}', '').strip()
                    
                    if item_id:
                        if item_id in item_ids_in_form:
                            errors.append(f'Duplicate item detected in row #{item_num}. Each item can only be added once per donation.')
                            continue
                        item_ids_in_form.add(item_id)
                        
                        if donation_type not in ('GOODS', 'FUNDS'):
                            errors.append(f'Invalid donation type for item #{item_num}. Must be GOODS or FUNDS.')
                        
                        quantity_value = None
                        if not quantity_str:
                            errors.append(f'Quantity is required for item #{item_num}')
                        else:
                            try:
                                quantity_value = Decimal(quantity_str)
                                if quantity_value < 0:
                                    errors.append(f'Quantity must be >= 0 for item #{item_num}')
                                if donation_type == 'FUNDS' and quantity_value != Decimal('1.00'):
                                    errors.append(f'Quantity must be 1.00 for FUNDS items (item #{item_num})')
                            except:
                                errors.append(f'Invalid quantity for item #{item_num}')
                        
                        item_cost_value = Decimal('0.00')
                        try:
                            item_cost_value = Decimal(item_cost_str)
                            if item_cost_value < 0:
                                errors.append(f'Item cost must be >= 0 for item #{item_num}')
                            if donation_type == 'FUNDS' and item_cost_value <= 0:
                                errors.append(f'Item cost must be > 0 for FUNDS items (item #{item_num})')
                        except:
                            errors.append(f'Invalid item cost for item #{item_num}')

                        # Validate based on donation type: GOODS needs uom_code, FUNDS needs currency_code
                        if donation_type == 'GOODS':
                            if not uom_code:
                                errors.append(f'UOM is required for GOODS item #{item_num}')
                        elif donation_type == 'FUNDS':
                            if not currency_code:
                                errors.append(f'Currency is required for FUNDS item #{item_num}')
                        
                        item_obj = Item.query.get(int(item_id))
                        if item_obj:
                            category = ItemCategory.query.get(item_obj.category_id)
                            if category and category.category_type != donation_type:
                                errors.append(f'Donation type mismatch for item #{item_num}: item category is {category.category_type} but form says {donation_type}')
                        
                        try:
                            item_data.append({
                                'item_id': int(item_id),
                                'donation_type': donation_type,
                                'quantity': quantity_value,
                                'item_cost': item_cost_value,
                                'uom_code': uom_code if donation_type == 'GOODS' else None,
                                'currency_code': currency_code if donation_type == 'FUNDS' else None,
                                'location_name': location_name,
                                'item_comments': item_comments
                            })
                        except ValueError as ve:
                            errors.append(f'Invalid data for item #{item_num}: {str(ve)}')
            
            if not item_data:
                errors.append('At least one donation item is required')
            
            if errors:
                for error in errors:
                    flash(error, 'danger')
                form_data = _get_donation_form_data()
                form_data['donation'] = donation
                form_data['form_data'] = request.form
                return render_template('donations/verify.html', **form_data)
            
            current_timestamp = jamaica_now()
            
            donation.donor_id = int(donor_id)
            donation.event_id = int(event_id)
            donation.custodian_id = int(custodian_id)
            donation.donation_desc = donation_desc.upper()
            donation.received_date = received_date
            donation.origin_country_id = int(origin_country_id) if origin_country_id else None
            donation.origin_address1_text = origin_address1.upper() if origin_address1 else None
            donation.origin_address2_text = origin_address2.upper() if origin_address2 else None
            donation.comments_text = comments_text.upper() if comments_text else None
            donation.storage_cost = storage_cost_value
            donation.haulage_cost = haulage_cost_value
            donation.other_cost = other_cost_value
            donation.other_cost_desc = other_cost_desc.upper() if other_cost_desc else None
            donation.status_code = 'V'
            
            add_audit_fields(donation, current_user, is_new=False)
            donation.verify_by_id = session_utils.get_user_name()
            donation.verify_dtime = current_timestamp
            
            total_value = Decimal('0.00')
            
            existing_item_ids = {item.item_id for item in donation.items}
            new_item_ids = {item_info['item_id'] for item_info in item_data}
            
            items_to_delete = existing_item_ids - new_item_ids
            for item_id_to_delete in items_to_delete:
                item_to_delete = DonationItem.query.get((donation_id, item_id_to_delete))
                if item_to_delete:
                    db.session.delete(item_to_delete)
            
            for item_info in item_data:
                item_cost = item_info['item_cost']
                # FUNDS items: Server-side enforcement - quantity is always 1.00
                quantity = Decimal('1.00') if item_info['donation_type'] == 'FUNDS' else item_info['quantity']

                # Add to total value (item_cost * quantity)
                total_value += Decimal(str(item_cost)) * Decimal(str(quantity))
                
                existing_item = DonationItem.query.get((donation_id, item_info['item_id']))
                
                if existing_item:
                    existing_item.donation_type = item_info['donation_type']
                    existing_item.item_qty = quantity
                    existing_item.item_cost = item_info['item_cost']
                    existing_item.uom_code = item_info['uom_code']
                    existing_item.currency_code = item_info['currency_code']
                    existing_item.location_name = item_info['location_name'].upper()
                    existing_item.comments_text = item_info['item_comments'].upper() if item_info['item_comments'] else None
                    existing_item.status_code = 'V'
                    add_audit_fields(existing_item, current_user, is_new=False)
                    existing_item.verify_by_id = session_utils.get_user_name()
                    existing_item.verify_dtime = current_timestamp
                else:
                    donation_item = DonationItem()
                    donation_item.donation_id = donation_id
                    donation_item.item_id = item_info['item_id']
                    donation_item.donation_type = item_info['donation_type']
                    # Use the enforced quantity (already set to 1.00 for FUNDS above)
                    donation_item.item_qty = quantity
                    donation_item.item_cost = item_info['item_cost']
                    donation_item.uom_code = item_info['uom_code']
                    donation_item.currency_code = item_info['currency_code']
                    donation_item.location_name = item_info['location_name'].upper()
                    donation_item.status_code = 'V'
                    donation_item.comments_text = item_info['item_comments'].upper() if item_info['item_comments'] else None
                    add_audit_fields(donation_item, current_user, is_new=True)
                    donation_item.verify_by_id = session_utils.get_user_name()
                    donation_item.verify_dtime = current_timestamp
                    db.session.add(donation_item)
            
            # Note: Total donation value may differ from sum of item costs due to currency differences
            # (e.g., donation received in USD, items valued in JMD)
            # LM should review and confirm the values are acceptable
            value_difference = abs(tot_item_cost_value - total_value)
            if value_difference > Decimal('0.01'):
                flash(f'Note: Total Donation Value (J${tot_item_cost_value:,.2f}) differs from sum of item costs (J${total_value:,.2f}). Please confirm this is correct (e.g., due to currency differences).', 'warning')
            
            # Set total item cost from manually entered value
            donation.tot_item_cost = tot_item_cost_value
            
            # Handle document uploads - validate all first, then save
            document_count = 0
            doc_errors = []
            validated_docs = []
            uploaded_files = request.files.getlist('document_files')
            document_types = request.form.getlist('document_type')
            document_descs = request.form.getlist('document_desc')
            
            upload_folder = current_app.config.get('UPLOAD_FOLDER')
            
            for idx, uploaded_file in enumerate(uploaded_files):
                if uploaded_file and uploaded_file.filename and uploaded_file.filename.strip():
                    original_filename = uploaded_file.filename.strip()
                    
                    mime_type = mimetypes.guess_type(original_filename)[0]
                    if mime_type not in ['application/pdf', 'image/jpeg']:
                        doc_errors.append(f'Invalid file type for document {idx + 1}. Only PDF and JPEG files are allowed.')
                        continue
                    
                    doc_type = document_types[idx] if idx < len(document_types) else 'Other'
                    doc_desc = document_descs[idx] if idx < len(document_descs) else ''
                    
                    if not doc_desc.strip():
                        doc_errors.append(f'Document description is required for document {idx + 1}.')
                        continue
                    
                    import uuid
                    safe_base_name = secure_filename(original_filename)
                    unique_filename = f"{uuid.uuid4().hex[:8]}_{safe_base_name}"
                    
                    uploaded_file.seek(0, os.SEEK_END)
                    file_size_bytes = uploaded_file.tell()
                    uploaded_file.seek(0)
                    
                    validated_docs.append({
                        'file': uploaded_file,
                        'unique_filename': unique_filename,
                        'doc_type': doc_type.upper(),
                        'doc_desc': doc_desc.strip().upper(),
                        'mime_type': mime_type,
                        'file_size_bytes': file_size_bytes,
                        'idx': idx
                    })
            
            if doc_errors:
                db.session.rollback()
                for error in doc_errors:
                    flash(error, 'danger')
                form_data = _get_donation_form_data()
                form_data['donation'] = donation
                form_data['form_data'] = request.form
                return render_template('donations/verify.html', **form_data)
            
            if validated_docs:
                if not upload_folder:
                    db.session.rollback()
                    flash('File storage is not configured. Please contact the system administrator to set up the upload folder before attaching documents.', 'danger')
                    form_data = _get_donation_form_data()
                    form_data['donation'] = donation
                    form_data['form_data'] = request.form
                    return render_template('donations/verify.html', **form_data)
                
                if not os.path.exists(upload_folder):
                    os.makedirs(upload_folder, exist_ok=True)
                
                saved_files = []
                try:
                    for doc_info in validated_docs:
                        try:
                            file_path = safe_join(upload_folder, doc_info['unique_filename'])
                        except ValueError as path_err:
                            raise ValueError(f"Invalid file path for document: {path_err}")
                        doc_info['file'].save(file_path)
                        saved_files.append(file_path)
                        
                        donation_doc = DonationDoc()
                        donation_doc.donation_id = donation_id
                        donation_doc.document_type = doc_info['doc_type']
                        donation_doc.document_desc = doc_info['doc_desc']
                        donation_doc.file_name = doc_info['unique_filename']
                        donation_doc.file_type = doc_info['mime_type']
                        
                        file_size_bytes = doc_info['file_size_bytes']
                        if file_size_bytes < 1024:
                            donation_doc.file_size = f'{file_size_bytes}B'
                        elif file_size_bytes < 1024 * 1024:
                            donation_doc.file_size = f'{file_size_bytes / 1024:.1f}KB'
                        else:
                            donation_doc.file_size = f'{file_size_bytes / (1024 * 1024):.1f}MB'
                        
                        add_audit_fields(donation_doc, current_user, is_new=True)
                        db.session.add(donation_doc)
                        document_count += 1
                except Exception as save_error:
                    for saved_path in saved_files:
                        try:
                            os.remove(saved_path)
                        except OSError:
                            pass
                    db.session.rollback()
                    current_app.logger.exception('Failed to save document during verification')
                    flash('Failed to save document. Please try again or contact support.', 'danger')
                    form_data = _get_donation_form_data()
                    form_data['donation'] = donation
                    form_data['form_data'] = request.form
                    return render_template('donations/verify.html', **form_data)
            
            db.session.commit()
            
            log_data_event(
                action=AuditAction.VERIFY,
                user_id=current_user.user_id,
                entity_type='donation',
                entity_id=donation_id,
                outcome=AuditOutcome.SUCCESS,
                details={
                    'item_count': len(item_data),
                    'total_value': str(tot_item_cost_value),
                    'previous_status': 'E',
                    'new_status': 'V'
                }
            )
            
            flash(f'Donation #{donation_id} verified successfully.', 'success')
            return redirect(url_for('donations.view_donation', donation_id=donation_id))
            
        except StaleDataError:
            db.session.rollback()
            flash('This donation was changed by another user. Please reload and try again.', 'danger')
            return redirect(url_for('donations.verify_donation_detail', donation_id=donation_id))
        except IntegrityError as e:
            db.session.rollback()
            error_message = str(e.orig) if hasattr(e, 'orig') else str(e)
            if 'duplicate key' in error_message.lower():
                flash('Duplicate item detected. Each item can only be added once per donation.', 'danger')
            else:
                flash('Unable to verify donation due to a database constraint. Please check your input and try again.', 'danger')
            form_data = _get_donation_form_data()
            form_data['donation'] = donation
            form_data['form_data'] = request.form
            return render_template('donations/verify.html', **form_data)
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('Unexpected error verifying donation')
            flash('An unexpected error occurred. Please try again or contact support.', 'danger')
            form_data = _get_donation_form_data()
            form_data['donation'] = donation
            form_data['form_data'] = request.form
            return render_template('donations/verify.html', **form_data)
    
    form_data = _get_donation_form_data()
    form_data['donation'] = donation
    form_data['today'] = date.today().isoformat()
    
    items_with_categories = []
    for item in donation.items:
        item_obj = Item.query.get(item.item_id)
        category = None
        if item_obj:
            from app.db.models import ItemCategory
            category = ItemCategory.query.get(item_obj.category_id)
        items_with_categories.append({
            'item': item,
            'category_type': category.category_type if category else 'GOODS'
        })
    form_data['items_with_categories'] = items_with_categories
    
    return render_template('donations/verify.html', **form_data)
