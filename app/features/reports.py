from flask import Blueprint, render_template, Response, request
from flask_login import login_required
from sqlalchemy import func, desc
from app.db.models import db, Inventory, Item, Warehouse, Event, Donor, Donation, DonationItem, DonationIntakeItem, Country, Currency
from datetime import datetime, date
from decimal import Decimal
import csv
from io import StringIO
import logging
from app.utils.timezone import now as jamaica_now
from app.core.rbac import executive_required
from app.security.rate_limiting import limit_export, limit_reports

logger = logging.getLogger(__name__)

reports_bp = Blueprint('reports', __name__)

@reports_bp.route('/')
@login_required
def index():
    return render_template('reports/index.html')

@reports_bp.route('/inventory_summary')
@login_required
@limit_reports
def inventory_summary():
    summary = db.session.query(
        Warehouse.warehouse_name,
        Item.item_name,
        func.sum(Inventory.usable_qty).label('usable'),
        func.sum(Inventory.reserved_qty).label('reserved'),
        func.sum(Inventory.defective_qty).label('defective'),
        func.sum(Inventory.expired_qty).label('expired')
    ).join(
        Inventory, Warehouse.warehouse_id == Inventory.inventory_id
    ).join(
        Item, Inventory.item_id == Item.item_id
    ).group_by(
        Warehouse.warehouse_name, Item.item_name
    ).all()
    
    return render_template('reports/inventory_summary.html', summary=summary)

@reports_bp.route('/inventory_summary/export')
@login_required
@limit_export
def export_inventory():
    summary = db.session.query(
        Warehouse.warehouse_name,
        Item.item_name,
        func.sum(Inventory.usable_qty).label('usable'),
        func.sum(Inventory.reserved_qty).label('reserved'),
        func.sum(Inventory.defective_qty).label('defective'),
        func.sum(Inventory.expired_qty).label('expired')
    ).join(
        Inventory, Warehouse.warehouse_id == Inventory.inventory_id
    ).join(
        Item, Inventory.item_id == Item.item_id
    ).group_by(
        Warehouse.warehouse_name, Item.item_name
    ).all()
    
    si = StringIO()
    writer = csv.writer(si)
    writer.writerow(['Warehouse', 'Item', 'Usable Qty', 'Reserved Qty', 'Defective Qty', 'Expired Qty'])
    
    for row in summary:
        writer.writerow([row.warehouse_name, row.item_name, 
                        float(row.usable or 0), float(row.reserved or 0),
                        float(row.defective or 0), float(row.expired or 0)])
    
    output = si.getvalue()
    si.close()
    
    return Response(
        output,
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename=inventory_summary_{jamaica_now().strftime("%Y%m%d_%H%M%S")}.csv'}
    )

@reports_bp.route('/donations_summary')
@login_required
@limit_reports
def donations_summary():
    # Calculate total value from DonationIntakeItem (quantity * unit value)
    donations = db.session.query(
        Donor.donor_name,
        func.count(func.distinct(Donation.donation_id)).label('donation_count'),
        func.sum(
            (DonationIntakeItem.usable_qty + 
             DonationIntakeItem.defective_qty + 
             DonationIntakeItem.expired_qty) * 
            DonationIntakeItem.avg_unit_value
        ).label('total_value')
    ).join(
        Donation, Donor.donor_id == Donation.donor_id
    ).outerjoin(
        DonationIntakeItem, Donation.donation_id == DonationIntakeItem.donation_id
    ).group_by(
        Donor.donor_name
    ).order_by(
        func.sum(
            (DonationIntakeItem.usable_qty + 
             DonationIntakeItem.defective_qty + 
             DonationIntakeItem.expired_qty) * 
            DonationIntakeItem.avg_unit_value
        ).desc()
    ).all()
    
    return render_template('reports/donations_summary.html', donations=donations)


@reports_bp.route('/funds_donations')
@login_required
@executive_required
@limit_reports
def funds_donations():
    """
    Funds Donations Report - Read-only report for ODPEM Executives.
    Shows all FUNDS-type donations with filters for country, date range, and currency.
    Only accessible to DG, Deputy DG, and Director PEOD.
    """
    from app.security.param_validation import safe_page, safe_id
    
    page = safe_page(request.args.get('page', 1))
    per_page = 25
    
    country_filter = request.args.get('country_id', '', type=str)
    date_from = request.args.get('date_from', '', type=str)
    date_to = request.args.get('date_to', '', type=str)
    currency_filter = request.args.get('currency_code', '', type=str)
    
    query = db.session.query(
        Donation.donation_id,
        Donation.received_date,
        Country.country_name.label('origin_country'),
        DonationItem.item_cost.label('donation_amount'),
        DonationItem.currency_code,
        Currency.currency_name,
        Currency.currency_sign,
        DonationItem.location_name
    ).join(
        DonationItem, Donation.donation_id == DonationItem.donation_id
    ).join(
        Country, Donation.origin_country_id == Country.country_id
    ).join(
        Currency, DonationItem.currency_code == Currency.currency_code
    ).filter(
        DonationItem.donation_type == 'FUNDS'
    )
    
    if country_filter:
        try:
            query = query.filter(Donation.origin_country_id == int(country_filter))
        except ValueError:
            pass
    
    if date_from:
        try:
            from_date = datetime.strptime(date_from, '%Y-%m-%d').date()
            query = query.filter(Donation.received_date >= from_date)
        except ValueError:
            pass
    
    if date_to:
        try:
            to_date = datetime.strptime(date_to, '%Y-%m-%d').date()
            query = query.filter(Donation.received_date <= to_date)
        except ValueError:
            pass
    
    if currency_filter:
        query = query.filter(DonationItem.currency_code == currency_filter)
    
    query = query.order_by(desc(Donation.received_date))
    
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    funds_donations_list = pagination.items
    
    total_donations = pagination.total
    unique_countries = db.session.query(
        func.count(func.distinct(Country.country_id))
    ).join(
        Donation, Country.country_id == Donation.origin_country_id
    ).join(
        DonationItem, Donation.donation_id == DonationItem.donation_id
    ).filter(
        DonationItem.donation_type == 'FUNDS'
    ).scalar() or 0
    
    unique_currencies = db.session.query(
        func.count(func.distinct(DonationItem.currency_code))
    ).filter(
        DonationItem.donation_type == 'FUNDS'
    ).scalar() or 0
    
    countries = Country.query.filter_by(status_code='A').order_by(Country.country_name).all()
    
    currencies = db.session.query(
        Currency.currency_code,
        Currency.currency_name
    ).join(
        DonationItem, Currency.currency_code == DonationItem.currency_code
    ).filter(
        DonationItem.donation_type == 'FUNDS'
    ).distinct().order_by(Currency.currency_name).all()
    
    return render_template(
        'reports/funds_donations.html',
        donations=funds_donations_list,
        pagination=pagination,
        countries=countries,
        currencies=currencies,
        total_donations=total_donations,
        unique_countries=unique_countries,
        unique_currencies=unique_currencies,
        filters={
            'country_id': country_filter,
            'date_from': date_from,
            'date_to': date_to,
            'currency_code': currency_filter
        }
    )
