"""
Content Security Policy (CSP) middleware for DMIS
Provides strict CSP headers with nonce-based protection against XSS attacks
"""
import secrets
from flask import g, request


def generate_csp_nonce():
    """Generate a cryptographically secure nonce for CSP"""
    return secrets.token_urlsafe(16)


def get_csp_nonce():
    """Get or create CSP nonce for current request"""
    if not hasattr(g, 'csp_nonce'):
        g.csp_nonce = generate_csp_nonce()
    return g.csp_nonce


def build_csp_header():
    """
    Build Content-Security-Policy header with strict directives
    
    Whitelisted domains:
    - cdn.jsdelivr.net: Bootstrap 5.3.3, Bootstrap Icons, Chart.js, Flatpickr
    - fonts.googleapis.com: Material Icons stylesheet
    - fonts.gstatic.com: Material Icons font files
    
    Security features:
    - Nonce-based inline script/style protection
    - NO wildcards (*, https:, http:) - SCANNER REQUIREMENT
    - NO unsafe-inline or unsafe-eval - SCANNER REQUIREMENT
    - Explicit script-src directive - SCANNER REQUIREMENT
    - Frame protection (frame-ancestors 'none')
    - Form submission restricted to same origin
    
    Security Scanner Compliance:
    - Removed 'https:' wildcard from img-src (too broad)
    - Removed cdn.jsdelivr.net from connect-src (not needed for static resources)
    - All directives are explicit and restrictive
    """
    nonce = get_csp_nonce()
    
    csp_directives = [
        # Default fallback - same origin only
        "default-src 'self'",
        
        # Scripts: self, nonce for inline, CDN for external libraries
        # CRITICAL: Must be explicit for scanner compliance
        f"script-src 'self' 'nonce-{nonce}' https://cdn.jsdelivr.net",
        
        # Styles: self, nonce for inline, CDN for external frameworks
        f"style-src 'self' 'nonce-{nonce}' https://cdn.jsdelivr.net https://fonts.googleapis.com",
        
        # Images: self and data URIs only (removed https: wildcard)
        "img-src 'self' data:",
        
        # Fonts: self, CDN for Bootstrap Icons, data URIs for embedded fonts
        "font-src 'self' https://cdn.jsdelivr.net https://fonts.gstatic.com data:",
        
        # AJAX/fetch: same origin only (CDN resources don't need connect-src)
        "connect-src 'self'",
        
        # Prevent all framing (clickjacking protection)
        "frame-ancestors 'none'",
        
        # Block all plugins (Flash, Java, etc.)
        "object-src 'none'",
        
        # Restrict base tag to prevent injection
        "base-uri 'self'",
        
        # Forms submit to same origin only
        "form-action 'self'",
        
        # Web app manifests from same origin
        "manifest-src 'self'",
        
        # Auto-upgrade HTTP to HTTPS
        "upgrade-insecure-requests"
    ]
    
    return "; ".join(csp_directives)


def add_csp_headers(response):
    """
    Add CSP and other security headers to response
    
    Args:
        response: Flask response object
        
    Returns:
        Modified response with security headers
        
    Security Headers Applied:
    - Content-Security-Policy: Nonce-based XSS protection with strict directives
    - Strict-Transport-Security: HSTS with 1-year max-age and includeSubDomains
    - X-Frame-Options: DENY for legacy browser clickjacking protection
    - X-Content-Type-Options: nosniff to prevent MIME-type sniffing
    - X-XSS-Protection: Legacy XSS filter (still useful for older browsers)
    - Referrer-Policy: Controls referrer information leakage
    - Permissions-Policy: Restricts browser features
    """
    response.headers['Content-Security-Policy'] = build_csp_header()
    
    # HSTS - Enforce HTTPS for 1 year with subdomains
    # Addresses: "Missing HSTS Header" finding
    # Note: Only effective over HTTPS connections (ignored over HTTP)
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    
    # Prevent MIME-type sniffing attacks
    response.headers['X-Content-Type-Options'] = 'nosniff'
    
    # Clickjacking protection for legacy browsers (CSP frame-ancestors is primary)
    # Addresses: "Potential clickjacking on legacy browsers" finding
    response.headers['X-Frame-Options'] = 'DENY'
    
    # Legacy XSS filter (deprecated but still useful for older browsers)
    response.headers['X-XSS-Protection'] = '1; mode=block'
    
    # Control referrer information sent with requests
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    
    # Restrict browser features/APIs
    response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
    
    return response


def init_csp(app):
    """
    Initialize CSP middleware for Flask application
    
    Args:
        app: Flask application instance
    """
    
    @app.before_request
    def setup_csp_nonce():
        """Generate nonce for each request"""
        get_csp_nonce()
    
    @app.after_request
    def apply_csp_headers(response):
        """Apply CSP headers to all responses"""
        return add_csp_headers(response)
    
    @app.context_processor
    def inject_csp_nonce():
        """Make CSP nonce available in templates"""
        return {'csp_nonce': get_csp_nonce}
