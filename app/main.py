"""
DRIMS - Disaster Relief Inventory Management System
Main Flask Application
"""

from flask import Flask, render_template, redirect, url_for, flash, request
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_wtf.csrf import CSRFProtect, generate_csrf
from werkzeug.security import check_password_hash
from flask_migrate import Migrate
import os
from flask import (Flask, abort, render_template, redirect, url_for,
                   flash, request)
from flask_login import LoginManager, login_required, current_user


from app.db import db, init_db
from app.db.models import User, Role, Event, Warehouse, Item, Inventory, Agency, ReliefRqst
from .settings import Config
from app.security.csp import init_csp
from app.security.cache_control import init_cache_control
from app.security.header_sanitization import init_header_sanitization
from app.security.error_handling import init_error_handling
from app.security.query_string_protection import init_query_string_protection
from app.utils.timezone import format_datetime, datetime_to_jamaica, now
from app.security.user_keycloak import check_refresh_token, keycloak_login, keycloak_logout
from app.security.user_ldap import ldap_login, ldap_logout
from app.security.csrf_validation import init_csrf_origin_validation
from app.security.url_safety import is_safe_url, get_safe_redirect_url
from app.security.rate_limiting import init_rate_limiting, limiter, RATE_LIMIT_AUTH
from app.security.cors_config import init_cors
from app.security.audit_logger import (
    init_audit_logging, 
    AuditAction, AuditOutcome
)

app = Flask(__name__)
app.config.from_object(Config)

init_db(app)
init_csp(app)
init_cache_control(app)
init_header_sanitization(app)
init_error_handling(app)
init_query_string_protection(app)
init_rate_limiting(app)
init_cors(app)
init_audit_logging(app)

csrf = CSRFProtect(app)
init_csrf_origin_validation(app)
migrate = Migrate(app, db)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
_login_logout = {
    'ldap': (ldap_login, ldap_logout),
    'keycloak': (keycloak_login, keycloak_logout)
}
_user_auth_mode = app.config.get('USER_AUTH_MODE', 'ldap')
_do_login, _do_logout = _login_logout[_user_auth_mode]


@login_manager.user_loader
def load_user(user_id):
    ''' use the token refresh process to determine if the user is still
    signed in. But, we will only refresh if the access token has expired
    If the refresh token has expired, the user will be signed out.
    '''
    def _getuser():
        user_q = User.query.filter_by(user_uuid=user_id)
        return user_q.first()
    
    if _user_auth_mode == 'keycloak':
        if check_refresh_token():
            return _getuser()
    else:
        return _getuser()
    return None


from app.features.events import events_bp
from app.features.warehouses import warehouses_bp
from app.features.items import items_bp
from app.features.item_categories import item_categories_bp
from app.features.uom import uom_bp
from app.features.inventory import inventory_bp
from app.features.requests_aidmgmt import requests_bp
from app.features.packaging import packaging_bp
from app.features.donations import donations_bp
from app.features.donation_intake import donation_intake_bp
from app.features.intake_aidmgmt import bp as intake_bp
from app.features.user_admin import user_admin_bp
from app.features.donors import donors_bp
from app.features.agencies import agencies_bp
from app.features.custodians import custodians_bp
from app.features.dashboard import dashboard_bp
from app.features.transfers import transfers_bp
from app.features.notifications import notifications_bp
from app.features.reports import reports_bp
from app.features.account_requests import account_requests_bp
from app.features.eligibility import eligibility_bp
from app.features.odpem_director import director_bp
from app.features.profile import profile_bp
from app.features.operations_dashboard import operations_dashboard_bp
from app.core.status import get_status_label, get_status_badge_class
from app.core.rbac import (
    has_role, has_all_roles, has_warehouse_access,
    is_admin, is_logistics_manager, is_logistics_officer, is_director_level, is_executive,
    can_manage_users, can_view_reports, has_permission, EXECUTIVE_ROLES
)
from app.core.feature_registry import FeatureRegistry

def get_feature_details(feature_key):
    """Get complete feature details from registry for templates."""
    if feature_key in FeatureRegistry.FEATURES:
        return {
            'key': feature_key,
            **FeatureRegistry.FEATURES[feature_key]
        }
    return None

@app.context_processor
def inject_csrf_token():
    """Make CSRF token available to all templates."""
    return dict(csrf_token=generate_csrf)

from app.utils.timezone import now as get_now

app.jinja_env.globals.update(
    has_role=has_role,
    has_all_roles=has_all_roles,
    has_warehouse_access=has_warehouse_access,
    is_admin=is_admin,
    is_logistics_manager=is_logistics_manager,
    is_logistics_officer=is_logistics_officer,
    is_director_level=is_director_level,
    is_executive=is_executive,
    can_manage_users=can_manage_users,
    can_view_reports=can_view_reports,
    has_permission=has_permission,
    has_feature=lambda feature_key: FeatureRegistry.has_access(current_user, feature_key),
    get_dashboard_features=lambda: FeatureRegistry.get_dashboard_features(current_user),
    get_navigation_features=lambda group=None: FeatureRegistry.get_navigation_features(current_user, group),
    get_user_features=lambda: FeatureRegistry.get_accessible_features(current_user),
    get_user_primary_role=lambda: FeatureRegistry.get_primary_role(current_user),
    get_role_display_name=FeatureRegistry.get_role_display_name,
    get_feature_details=get_feature_details,
    now=get_now
)

# Date formatting filter moved below to use timezone utilities

app.register_blueprint(dashboard_bp, url_prefix='/dashboard')
app.register_blueprint(events_bp)
app.register_blueprint(warehouses_bp)
app.register_blueprint(items_bp)
app.register_blueprint(item_categories_bp)
app.register_blueprint(uom_bp)
app.register_blueprint(inventory_bp)
app.register_blueprint(requests_bp)
app.register_blueprint(packaging_bp)
app.register_blueprint(donations_bp)
app.register_blueprint(donation_intake_bp)
app.register_blueprint(intake_bp)
app.register_blueprint(user_admin_bp, url_prefix='/users')
app.register_blueprint(donors_bp, url_prefix='/donors')
app.register_blueprint(agencies_bp, url_prefix='/agencies')
app.register_blueprint(custodians_bp, url_prefix='/custodians')
app.register_blueprint(transfers_bp, url_prefix='/transfers')
app.register_blueprint(notifications_bp, url_prefix='/notifications')
app.register_blueprint(reports_bp, url_prefix='/reports')
app.register_blueprint(account_requests_bp)
app.register_blueprint(eligibility_bp)
app.register_blueprint(director_bp)
app.register_blueprint(profile_bp)
app.register_blueprint(operations_dashboard_bp)

@app.template_filter('status_badge')
def status_badge_filter(status_code, entity_type):
    """Return Bootstrap badge color class for status codes"""
    return get_status_badge_class(status_code, entity_type)

@app.template_filter('status_label')
def status_label_filter(status_code, entity_type):
    """Return human-readable label for status codes"""
    return get_status_label(status_code, entity_type)

@app.context_processor
def inject_now():
    """Inject current datetime for footer year and other templates"""
    return {'now': now()}

# Register timezone-aware Jinja filters

@app.template_filter('format_datetime')
def format_datetime_filter(dt, format_str='%Y-%m-%d %H:%M:%S'):
    """Format datetime in Jamaica timezone"""
    return format_datetime(dt, format_str)

@app.template_filter('format_date')
def format_date_filter(dt):
    """Format date only"""
    return format_datetime(dt, '%Y-%m-%d')

@app.template_filter('to_jamaica')
def to_jamaica_filter(dt):
    """Convert datetime to Jamaica timezone"""
    return datetime_to_jamaica(dt)

@app.route('/static/')
@app.route('/static')
def block_static_directory():
    """
    Prevent directory browsing of /static/ folder
    Returns 404 to hide directory existence for security
    Individual static files are still accessible via Flask's built-in static serving
    """
    abort(404)

@app.route('/')
@login_required
def index():
    """Redirect to role-based dashboard"""
    return redirect('/dashboard/')

@app.route('/login', methods=['GET', 'POST'])
@limiter.limit(RATE_LIMIT_AUTH, methods=['POST'])
def login():
    """User login with rate limiting to prevent brute force attacks"""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))
    
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        success = _do_login(email, password)
        if success:
            next_page = request.args.get('next')
            return redirect(get_safe_redirect_url(next_page, 'dashboard.index'))
        else:
            flash('Invalid email or password', 'danger')
    
    return render_template('login.html')

@app.route('/test-feature-components')
@login_required
def test_feature_components():
    """Test feature registry components"""
    return render_template('test_feature_components.html')

@app.route('/logout')
@login_required
def logout():
    """User logout"""
    _do_logout()
    flash('You have been logged out', 'info')
    return redirect(url_for('login'))


import click
from datetime import date
from decimal import Decimal

@app.cli.command('currency-refresh')
@click.option('--date', 'target_date', default=None, help='Date for rates (YYYY-MM-DD). Defaults to today.')
def currency_refresh(target_date):
    """Refresh exchange rates for all donation currencies from Frankfurter.app."""
    from app.services.currency_service import CurrencyService
    
    if target_date:
        try:
            target_date = date.fromisoformat(target_date)
        except ValueError:
            click.echo("Invalid date format. Use YYYY-MM-DD.")
            return
    else:
        target_date = date.today()
    
    click.echo(f"Refreshing currency rates for {target_date}...")
    
    currencies = CurrencyService.get_donation_currencies()
    click.echo(f"Found {len(currencies)} currencies in donations: {', '.join(currencies) if currencies else 'None'}")
    
    success, failed = CurrencyService.refresh_all_rates(target_date)
    
    click.echo(f"Refresh complete: {success} succeeded, {failed} failed")


@app.cli.command('currency-set-usd')
@click.argument('rate', type=float)
@click.option('--date', 'target_date', default=None, help='Date for rate (YYYY-MM-DD). Defaults to today.')
def currency_set_usd(rate, target_date):
    """Manually set the USD to JMD exchange rate."""
    from app.services.currency_service import CurrencyService
    
    if target_date:
        try:
            target_date = date.fromisoformat(target_date)
        except ValueError:
            click.echo("Invalid date format. Use YYYY-MM-DD.")
            return
    else:
        target_date = date.today()
    
    rate_decimal = Decimal(str(rate))
    
    if CurrencyService.set_usd_jmd_rate(rate_decimal, target_date):
        click.echo(f"Set USD/JMD rate to {rate_decimal} for {target_date}")
    else:
        click.echo("Failed to set USD/JMD rate")


@app.cli.command('currency-list')
def currency_list():
    """List all cached currency rates."""
    from app.services.currency_service import CurrencyRate
    
    rates = CurrencyRate.query.order_by(
        CurrencyRate.currency_code, 
        CurrencyRate.rate_date.desc()
    ).all()
    
    if not rates:
        click.echo("No cached currency rates found.")
        return
    
    click.echo(f"{'Currency':<10} {'Rate to JMD':<18} {'Date':<12} {'Source':<20}")
    click.echo("-" * 60)
    
    for rate in rates:
        click.echo(f"{rate.currency_code:<10} {rate.rate_to_jmd:<18.4f} {rate.rate_date.isoformat():<12} {rate.source:<20}")


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=app.config['DEBUG'])
