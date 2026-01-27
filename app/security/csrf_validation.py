"""
CSRF Validation - Origin/Referer Defense-in-Depth
Provides additional validation beyond CSRF tokens
"""
from flask import request, current_app, abort
from urllib.parse import urlparse
from app.security.log_sanitizer import sanitize_for_log


def validate_origin_referer():
    """
    Validate Origin/Referer headers for state-changing requests.
    Defense-in-depth measure complementing CSRF tokens.
    
    Uses strict origin matching (not prefix matching) to prevent subdomain bypass.
    Only trusts X-Forwarded-* headers when explicitly configured.
    """
    # Only validate unsafe methods
    if request.method in ['POST', 'PUT', 'PATCH', 'DELETE']:
        # Build allowed origins list with strict domain matching
        allowed_origins = set()
        
        # Only trust X-Forwarded-* headers if explicitly enabled
        trust_proxy_headers = current_app.config.get('CSRF_TRUST_PROXY_HEADERS', False)
        
        if trust_proxy_headers:
            # Get scheme from X-Forwarded-Proto (if behind proxy)
            forwarded_proto = request.headers.get('X-Forwarded-Proto', request.scheme)
            # Get host from X-Forwarded-Host (if behind proxy)
            forwarded_host = request.headers.get('X-Forwarded-Host', request.host)
            allowed_origins.add(f"{forwarded_proto}://{forwarded_host}")
        else:
            # Use direct request values (not proxy headers)
            allowed_origins.add(f"{request.scheme}://{request.host}")
        
        # REPLIT FIX: Allow both HTTP and HTTPS for the same host
        # This handles the case where Replit's proxy uses HTTPS but Flask dev server uses HTTP
        # Extract just the host part and add both protocols
        current_host = request.host
        allowed_origins.add(f"http://{current_host}")
        allowed_origins.add(f"https://{current_host}")
        
        # Add SERVER_NAME if configured
        server_name = current_app.config.get('SERVER_NAME')
        preferred_scheme = current_app.config.get('PREFERRED_URL_SCHEME', 'https')
        if server_name:
            allowed_origins.add(f"{preferred_scheme}://{server_name}")
        
        # Add custom trusted origins from config (for multi-domain deployments)
        trusted_origins = current_app.config.get('CSRF_TRUSTED_ORIGINS', [])
        allowed_origins.update(trusted_origins)
        
        # Check Origin header (preferred)
        origin = request.headers.get('Origin')
        if origin:
            # Parse and validate with exact match (not prefix)
            parsed_origin = urlparse(origin)
            origin_normalized = f"{parsed_origin.scheme}://{parsed_origin.netloc}"
            
            if origin_normalized not in allowed_origins:
                current_app.logger.warning(
                    "CSRF Origin validation failed: expected one of %s, got %s",
                    sanitize_for_log(str(allowed_origins)),
                    sanitize_for_log(origin_normalized)
                )
                abort(403, description="Invalid request origin")
            return True
        
        referer = request.headers.get('Referer')
        if referer:
            parsed_referer = urlparse(referer)
            referer_origin = f"{parsed_referer.scheme}://{parsed_referer.netloc}"
            
            if referer_origin not in allowed_origins:
                current_app.logger.warning(
                    "CSRF Referer validation failed: expected one of %s, got %s",
                    sanitize_for_log(str(allowed_origins)),
                    sanitize_for_log(referer_origin)
                )
                abort(403, description="Invalid request referer")
            return True
        
        if request.is_secure and request.is_json:
            current_app.logger.info(
                "CSRF validation: Missing Origin/Referer for HTTPS AJAX request "
                "(not failing - relying on CSRF token validation)"
            )
    
    return True


def init_csrf_origin_validation(app):
    """Initialize Origin/Referer validation."""
    @app.before_request
    def check_origin_referer():
        # Skip for certain routes that don't need validation
        if request.endpoint and request.endpoint.startswith('static'):
            return None
        
        # Run validation
        validate_origin_referer()
        return None
    
    app.logger.info("CSRF Origin/Referer validation initialized")
