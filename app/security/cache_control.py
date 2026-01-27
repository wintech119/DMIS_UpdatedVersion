"""
Cache Control middleware for DMIS
Prevents caching of authenticated and sensitive pages to eliminate "SSL Pages Are Cacheable" vulnerability
"""
from flask import request
from flask_login import current_user


def should_apply_no_cache(response):
    """
    Determine if no-cache headers should be applied to this response
    
    Applies no-cache to:
    - All authenticated pages (user is logged in)
    - All dynamic pages (not static assets)
    
    Skips no-cache for:
    - Static assets (CSS, JS, images, fonts)
    - Public resources
    
    Args:
        response: Flask response object
        
    Returns:
        bool: True if no-cache headers should be applied
    """
    # Static asset paths that should be cached
    static_paths = [
        '/static/',
        '/favicon.ico',
        '/robots.txt'
    ]
    
    # Check if request path is a static asset
    for path in static_paths:
        if request.path.startswith(path):
            return False
    
    # Apply no-cache to all authenticated pages
    if current_user.is_authenticated:
        return True
    
    # Apply no-cache to login page (sensitive form)
    if request.path == '/login' or request.path.startswith('/login'):
        return True
    
    # Apply no-cache to all other dynamic pages by default
    # (only static assets should be cached)
    return True


def add_no_cache_headers(response):
    """
    Add cache-control headers to prevent caching of sensitive/authenticated pages
    
    Headers added:
    - Cache-Control: no-store, no-cache, must-revalidate
    - Pragma: no-cache (HTTP/1.0 compatibility)
    - Expires: 0 (legacy browser compatibility)
    
    Args:
        response: Flask response object
        
    Returns:
        Modified response with cache-control headers
    """
    if should_apply_no_cache(response):
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    
    return response


def init_cache_control(app):
    """
    Initialize cache-control middleware for Flask application
    
    Args:
        app: Flask application instance
    """
    
    @app.after_request
    def apply_cache_control(response):
        """Apply cache-control headers to appropriate responses"""
        return add_no_cache_headers(response)
