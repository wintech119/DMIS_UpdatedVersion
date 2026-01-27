"""
DMIS Rate Limiting Module
=========================

Implements rate limiting controls aligned with OWASP API Top 10 to protect
against API abuse, brute force attacks, and denial of service.

Rate Limit Categories:
- Authentication: Strict limits to prevent brute force (5/minute)
- Standard: Normal API usage (100/minute)
- Expensive: Report generation, exports (10/minute)
- Bulk: Large data operations (5/minute)

Configuration:
- Limits can be overridden via environment variables
- Uses X-Forwarded-For header behind reverse proxy
- Logs rate limit violations for security monitoring

Usage:
    from app.security.rate_limiting import limiter, limit_auth, limit_expensive
    
    @app.route('/login', methods=['POST'])
    @limit_auth
    def login():
        ...
    
    @reports_bp.route('/export')
    @limit_expensive
    def export_report():
        ...
"""

import os
import logging
from functools import wraps
from flask import request, jsonify, current_app, g
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address


logger = logging.getLogger(__name__)


def _get_client_ip():
    """
    Get the real client IP address.
    
    Handles X-Forwarded-For header for clients behind reverse proxies (NGINX).
    Falls back to remote_addr for direct connections.
    
    Security Note: In production, ensure NGINX is configured to set X-Forwarded-For
    and that only trusted proxies are allowed to set this header.
    """
    x_forwarded_for = request.headers.get('X-Forwarded-For')
    if x_forwarded_for:
        client_ip = x_forwarded_for.split(',')[0].strip()
    else:
        client_ip = get_remote_address()
    return client_ip


def _get_rate_limit_key():
    """
    Generate rate limit key combining IP and user identity (if authenticated).
    
    This prevents:
    - Single IP from making too many requests
    - Single user from circumventing limits via multiple IPs (when authenticated)
    """
    from flask_login import current_user
    
    client_ip = _get_client_ip()
    
    if hasattr(current_user, 'is_authenticated') and current_user.is_authenticated:
        return f"{client_ip}:{current_user.user_id}"
    return client_ip


limiter = Limiter(
    key_func=_get_rate_limit_key,
    default_limits=[
        os.getenv('DMIS_RATE_LIMIT_DEFAULT', '200 per hour'),
        os.getenv('DMIS_RATE_LIMIT_BURST', '50 per minute')
    ],
    storage_uri=os.getenv('DMIS_RATE_LIMIT_STORAGE', 'memory://'),
    strategy='fixed-window',
    headers_enabled=True,
    swallow_errors=True,
)


RATE_LIMIT_AUTH = os.getenv('DMIS_RATE_LIMIT_AUTH', '5 per minute')
RATE_LIMIT_STANDARD = os.getenv('DMIS_RATE_LIMIT_STANDARD', '100 per minute')
RATE_LIMIT_EXPENSIVE = os.getenv('DMIS_RATE_LIMIT_EXPENSIVE', '10 per minute')
RATE_LIMIT_EXPORT = os.getenv('DMIS_RATE_LIMIT_EXPORT', '3 per hour')
RATE_LIMIT_REPORTS = os.getenv('DMIS_RATE_LIMIT_REPORTS', '10 per minute')
RATE_LIMIT_BULK = os.getenv('DMIS_RATE_LIMIT_BULK', '5 per minute')
RATE_LIMIT_API = os.getenv('DMIS_RATE_LIMIT_API', '60 per minute')


def _log_rate_limit_exceeded(endpoint_type='standard'):
    """Log rate limit violation for security monitoring."""
    from app.security.log_sanitizer import sanitize_for_log
    
    client_ip = _get_client_ip()
    path = sanitize_for_log(request.path)
    method = request.method
    
    logger.warning(
        f"Rate limit exceeded - type={endpoint_type} ip={client_ip} "
        f"method={method} path={path}"
    )


def limit_auth(f):
    """
    Rate limiter decorator for authentication endpoints.
    
    Applies strict rate limiting (5/minute by default) to prevent
    brute force attacks on login endpoints.
    """
    @wraps(f)
    @limiter.limit(RATE_LIMIT_AUTH, error_message="Too many login attempts. Please wait before trying again.")
    def decorated_function(*args, **kwargs):
        return f(*args, **kwargs)
    return decorated_function


def limit_expensive(f):
    """
    Rate limiter decorator for expensive operations.
    
    Applies moderate rate limiting (10/minute by default) to prevent
    abuse of resource-intensive endpoints like:
    - Dashboard analytics
    - Complex searches
    """
    @wraps(f)
    @limiter.limit(RATE_LIMIT_EXPENSIVE, error_message="Too many requests. Please wait before generating another report.")
    def decorated_function(*args, **kwargs):
        return f(*args, **kwargs)
    return decorated_function


def limit_export(f):
    """
    Rate limiter decorator for export operations.
    
    Applies strict rate limiting (3/hour by default) to prevent
    abuse of data export endpoints like:
    - CSV exports
    - PDF generation
    - Large data downloads
    """
    @wraps(f)
    @limiter.limit(RATE_LIMIT_EXPORT, error_message="Export limit reached. You can generate up to 3 exports per hour.")
    def decorated_function(*args, **kwargs):
        return f(*args, **kwargs)
    return decorated_function


def limit_reports(f):
    """
    Rate limiter decorator for report view endpoints.
    
    Applies moderate rate limiting (10/minute by default) to prevent
    abuse of report viewing and generation endpoints.
    """
    @wraps(f)
    @limiter.limit(RATE_LIMIT_REPORTS, error_message="Too many report requests. Please wait before viewing another report.")
    def decorated_function(*args, **kwargs):
        return f(*args, **kwargs)
    return decorated_function


def limit_bulk(f):
    """
    Rate limiter decorator for bulk operations.
    
    Applies strict rate limiting (5/minute by default) to prevent
    abuse of bulk data operations like:
    - Bulk updates
    - Mass notifications
    - Large data imports
    """
    @wraps(f)
    @limiter.limit(RATE_LIMIT_BULK, error_message="Too many bulk operations. Please wait before trying again.")
    def decorated_function(*args, **kwargs):
        return f(*args, **kwargs)
    return decorated_function


def limit_api(f):
    """
    Rate limiter decorator for API endpoints.
    
    Applies standard API rate limiting (60/minute by default) for
    AJAX/fetch endpoints used by the frontend.
    """
    @wraps(f)
    @limiter.limit(RATE_LIMIT_API, error_message="API rate limit exceeded. Please slow down your requests.")
    def decorated_function(*args, **kwargs):
        return f(*args, **kwargs)
    return decorated_function


def init_rate_limiting(app):
    """
    Initialize rate limiting for the Flask application.
    
    Sets up:
    - Global rate limiter
    - Error handlers for rate limit exceeded
    - Exempt routes (health checks, static files)
    - Request logging for rate limit violations
    
    Args:
        app: Flask application instance
    """
    limiter.init_app(app)
    
    @limiter.request_filter
    def _skip_rate_limit():
        """Skip rate limiting for health checks and static files."""
        if request.path == '/health':
            return True
        if request.path.startswith('/static/'):
            return True
        return False
    
    @app.errorhandler(429)
    def ratelimit_handler(e):
        """Handle rate limit exceeded errors."""
        _log_rate_limit_exceeded()
        
        if request.is_json or request.path.startswith('/api/'):
            return jsonify({
                'error': 'rate_limit_exceeded',
                'message': str(e.description),
                'retry_after': e.retry_after if hasattr(e, 'retry_after') else 60
            }), 429
        
        from flask import render_template
        return render_template('errors/429.html', retry_after=60), 429
    
    app.logger.info("Rate limiting initialized")


HIGH_RISK_ENDPOINTS = {
    'authentication': [
        '/login',
    ],
    'exports_reports': [
        '/reports/inventory_summary/export',
        '/reports/donations_summary',
        '/reports/funds_donations',
    ],
    'expensive_queries': [
        '/dashboard/donations-analytics',
        '/dashboard/aid-movement',
        '/dashboard/aid-movement/item-detail',
        '/dashboard/logistics',
        '/dashboard/director',
        '/executive/operations',
        '/director/dashboard',
    ],
    'state_changes': [
        '/packaging/<int:reliefpkg_id>/submit-dispatch',
        '/packaging/<int:reliefpkg_id>/cancel',
        '/transfers/<int:transfer_id>/execute',
        '/donation-intake/complete/<int:donation_id>/<int:inventory_id>',
    ],
    'bulk_operations': [
        '/notifications/clear-all',
        '/notifications/api/clear-all',
    ],
    'public_endpoints': [
        '/account-requests/submit',
        '/account-requests/',
    ],
}
