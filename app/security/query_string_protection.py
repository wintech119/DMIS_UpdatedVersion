"""
Query String Parameter Protection for DMIS

Prevents sensitive parameters from being accepted through GET query strings.
This security measure protects against:
1. Password/credential leakage in browser history
2. Sensitive data exposure in server logs
3. Parameter tampering via URL manipulation
4. Information disclosure through referer headers

All sensitive parameters MUST be submitted via POST request body only.
"""

from flask import request, g
from functools import wraps
import logging
from app.security.log_sanitizer import sanitize_for_log

logger = logging.getLogger(__name__)

# Define sensitive parameter names that should NEVER appear in query strings
# These are truly sensitive parameters that contain passwords, PII, or form submission data
SENSITIVE_PARAMETERS = {
    # Authentication & Security
    'password',
    'current_password',
    'new_password',
    'confirm_password',
    'password_hash',
    'token',
    'api_key',
    'secret',
    'auth_token',
    'session_token',
    'csrf_token',
    
    # Personal Identifiable Information (PII)
    'email',
    'phone',
    'phone_no',
    'contact_phone',
    'contact_email',
    'first_name',
    'last_name',
    'user_name',
    'full_name',
    'address',
    'address1_text',
    'address2_text',
    'postal_code',
    'national_id',
    'tax_id',
    'ssn',
    
    # Financial & Payment Data
    'credit_card',
    'card_number',
    'cvv',
    'account_number',
    'bank_account',
    'salary',
    
    # Form Submission Data (should be in POST body)
    # These are long-form text fields that should never be in URLs
    'donation_desc',
    'comments_text',
    'reason_text',
    'reason_desc',
    'rqst_notes_text',
    'impact_desc',
    'event_desc',
    'agency_name',
    'contact_name',
    'donor_name',
    'warehouse_name',
    'item_name',
    'category_desc',
    'uom_desc',
    
    # Batch & Inventory Data (should be in POST body)
    'batch_no',
    'batch_date',
    'expiry_date',
    'received_date',
    'verify_dtime',
    'dispatch_dtime',
    
    # User Management (form submission data)
    'is_active',
    'job_title',
    'organization',
    'roles',
    'warehouse_assignment',
}

# Note: These are NOT included as they are legitimate GET filter parameters:
# - donor_id, event_id, warehouse_id, item_id (reference IDs for filtering)
# - amount, price, cost, quantity (legitimate filter/search params)
# - page, limit, offset (pagination params)
# - status, status_code (filter params)

# Lowercase versions for case-insensitive matching
SENSITIVE_PARAMETERS_LOWER = {param.lower() for param in SENSITIVE_PARAMETERS}


def is_sensitive_parameter(param_name):
    """
    Check if a parameter name is considered sensitive.
    
    Args:
        param_name: The parameter name to check
        
    Returns:
        bool: True if parameter is sensitive, False otherwise
    """
    if not param_name:
        return False
    
    param_lower = param_name.lower()
    
    # Direct match
    if param_lower in SENSITIVE_PARAMETERS_LOWER:
        return True
    
    # Pattern matching for dynamically named fields (e.g., item_id_1, quantity_2)
    sensitive_patterns = [
        'password',
        'email',
        'phone',
        'address',
        'token',
        'secret',
        'credit',
        'card',
        'account',
        'ssn',
        'national_id',
    ]
    
    for pattern in sensitive_patterns:
        if pattern in param_lower:
            return True
    
    return False


def sanitize_query_string(query_args):
    """
    Remove sensitive parameters from query arguments.
    
    Args:
        query_args: ImmutableMultiDict of query parameters
        
    Returns:
        tuple: (sanitized_dict, list of removed parameters)
    """
    sanitized = {}
    removed_params = []
    
    for key, value in query_args.items():
        if is_sensitive_parameter(key):
            removed_params.append(key)
            logger.warning(
                "Blocked sensitive parameter in query string: %s (IP: %s, Path: %s)",
                sanitize_for_log(key),
                sanitize_for_log(request.remote_addr),
                sanitize_for_log(request.path)
            )
        else:
            sanitized[key] = value
    
    return sanitized, removed_params


def strip_sensitive_query_params():
    """
    Middleware to block sensitive parameters from query strings.
    
    This runs before request processing to ensure sensitive data
    never makes it into logs, analytics, or application code.
    
    IMPORTANT: Blocks sensitive parameters in query strings for ALL HTTP methods
    (GET, POST, PUT, DELETE, etc.) because sensitive data should NEVER be in URLs
    regardless of the HTTP method used.
    
    Should be registered as a before_request handler.
    
    Returns:
        - 400 Bad Request if sensitive parameters are detected in query string
        - None (continues processing) if no sensitive parameters found
    """
    from flask import abort, make_response
    
    # Check query string for ALL HTTP methods (GET, POST, PUT, DELETE, etc.)
    # Sensitive parameters should never be in URLs regardless of method
    if request.args:
        # Check for sensitive parameters in query string
        sensitive_found = []
        
        for param_name in request.args.keys():
            if is_sensitive_parameter(param_name):
                sensitive_found.append(param_name)
        
        if sensitive_found:
            logger.warning(
                "SECURITY VIOLATION: Sensitive parameters blocked in query string - "
                "Parameters: %s | IP: %s | Path: %s | Method: %s",
                sanitize_for_log(', '.join(sensitive_found)),
                sanitize_for_log(request.remote_addr),
                sanitize_for_log(request.path),
                sanitize_for_log(request.method)
            )
            
            # Store blocked parameters for potential security auditing
            g.blocked_query_params = sensitive_found
            
            # CRITICAL: Block the request - return 400 Bad Request
            # This prevents sensitive data from:
            # 1. Appearing in server access logs
            # 2. Being stored in browser history
            # 3. Being leaked via referer headers
            # 4. Being processed by application code
            # 
            # Note: This blocks for ALL HTTP methods (GET, POST, PUT, DELETE, etc.)
            # because sensitive data in URLs is dangerous regardless of method
            
            response = make_response(
                (
                    '<h1>400 Bad Request</h1>'
                    '<p>Sensitive data must not be passed via URL parameters.</p>'
                    '<p>Please submit sensitive information via POST request body only.</p>'
                ), 
                400
            )
            response.headers['Content-Type'] = 'text/html'
            return response


def require_post_for_sensitive_data(f):
    """
    Decorator to ensure sensitive data is only processed via POST.
    
    Usage:
        @app.route('/create', methods=['GET', 'POST'])
        @login_required
        @require_post_for_sensitive_data
        def create_user():
            # This route will only process POST requests
            # GET requests show the form but don't process data
            pass
    
    This decorator:
    1. Allows GET requests to display forms
    2. Blocks sensitive parameters from query strings on GET
    3. Only processes data from POST request body
    4. Logs security events when sensitive params found in query string
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # For GET requests, verify no sensitive data in query string
        if request.method == 'GET':
            sensitive_in_query = []
            
            for param_name in request.args.keys():
                if is_sensitive_parameter(param_name):
                    sensitive_in_query.append(param_name)
            
            if sensitive_in_query:
                logger.warning(
                    "SECURITY: Attempted to pass sensitive data via GET query string - "
                    "Route: %s | Parameters: %s | IP: %s | User: %s",
                    sanitize_for_log(request.endpoint),
                    sanitize_for_log(', '.join(sensitive_in_query)),
                    sanitize_for_log(request.remote_addr),
                    sanitize_for_log(getattr(request, 'user', 'Anonymous'))
                )
                
                # Store for potential audit logging
                g.security_violation = {
                    'type': 'sensitive_query_params',
                    'params': sensitive_in_query,
                    'route': request.endpoint,
                    'method': request.method,
                }
        
        # Continue with normal request processing
        # The route function itself should use request.form for POST data
        return f(*args, **kwargs)
    
    return decorated_function


def validate_post_only_submission(form_fields):
    """
    Validate that sensitive fields come from POST body, not query string.
    
    Args:
        form_fields: List of field names to validate
        
    Returns:
        tuple: (is_valid, error_message)
    
    Usage:
        if request.method == 'POST':
            is_valid, error = validate_post_only_submission(['email', 'password'])
            if not is_valid:
                flash(error, 'danger')
                return redirect(url_for('login'))
    """
    if request.method != 'POST':
        return True, None
    
    # Check if any sensitive fields are in query string
    sensitive_in_query = []
    
    for field in form_fields:
        if field in request.args and is_sensitive_parameter(field):
            sensitive_in_query.append(field)
    
    if sensitive_in_query:
        error_msg = (
            "Security Error: Sensitive data must be submitted via secure form, "
            "not URL parameters."
        )
        
        logger.error(
            "SECURITY VIOLATION: Sensitive POST fields found in query string - "
            "Fields: %s | Route: %s | IP: %s",
            sanitize_for_log(', '.join(sensitive_in_query)),
            sanitize_for_log(request.endpoint),
            sanitize_for_log(request.remote_addr)
        )
        
        return False, error_msg
    
    return True, None


def get_safe_query_params():
    """
    Get query parameters with all sensitive parameters removed.
    
    Returns:
        dict: Sanitized query parameters safe for logging/display
    
    Usage:
        safe_params = get_safe_query_params()
        logger.info(f"Request received with params: {safe_params}")
    """
    sanitized, _ = sanitize_query_string(request.args)
    return sanitized


def audit_sensitive_query_attempts():
    """
    Check if any sensitive parameters were blocked and return audit info.
    
    Returns:
        dict or None: Audit information if violations found, None otherwise
    
    Usage (in after_request handler):
        audit_info = audit_sensitive_query_attempts()
        if audit_info:
            # Log to security audit system
            security_log.write(audit_info)
    """
    if hasattr(g, 'blocked_query_params') and g.blocked_query_params:
        return {
            'timestamp': g.get('request_start_time'),
            'ip_address': request.remote_addr,
            'path': request.path,
            'method': request.method,
            'blocked_params': g.blocked_query_params,
            'user_agent': request.user_agent.string if request.user_agent else None,
            'endpoint': request.endpoint,
        }
    
    return None


# Initialization function to register middleware
def init_query_string_protection(app):
    """
    Initialize query string protection for the Flask application.
    
    Args:
        app: Flask application instance
    
    Usage:
        from app.security.query_string_protection import init_query_string_protection
        init_query_string_protection(app)
    """
    # Register before_request handler to strip sensitive params
    app.before_request(strip_sensitive_query_params)
    
    logger.info("Query string protection initialized - Sensitive parameters will be blocked from GET requests")
