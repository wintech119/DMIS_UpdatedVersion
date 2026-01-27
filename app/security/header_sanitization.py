"""
HTTP Response Header Sanitization for DMIS
Removes or neutralizes headers that leak technology stack details

Note: For Flask's development server, the Server header is added by Python's
http.server module at the HTTP layer. We override this behavior by patching
http.server.BaseHTTPRequestHandler.version_string().

In production with Gunicorn/uWSGI, the WSGI middleware handles header removal.
"""
import http.server


class HeaderSanitizationMiddleware:
    """
    WSGI middleware to remove info-leaking HTTP response headers
    
    This middleware wraps the Flask WSGI application and intercepts
    responses to remove headers that reveal technology stack details
    before they are sent to the client.
    
    Headers removed:
    - Server: Web server type and version
    - X-Powered-By: Framework/language details
    - X-AspNet-Version, X-AspNetMvc-Version: ASP.NET details
    - X-Runtime: Request processing time/language
    - Via: Proxy/cache server details
    """
    
    def __init__(self, app):
        """
        Initialize middleware with WSGI application
        
        Args:
            app: WSGI application (Flask app.wsgi_app)
        """
        self.app = app
        self.headers_to_remove = {
            'Server',
            'X-Powered-By',
            'X-AspNet-Version',
            'X-AspNetMvc-Version',
            'X-Runtime',
            'Via'
        }
    
    def __call__(self, environ, start_response):
        """
        WSGI application interface
        
        Intercepts start_response to filter out info-leaking headers
        
        Args:
            environ: WSGI environment dict
            start_response: WSGI start_response callable
            
        Returns:
            WSGI response iterable
        """
        def sanitizing_start_response(status, headers, exc_info=None):
            """
            Wrapper for start_response that removes info-leaking headers
            
            Args:
                status: HTTP status line
                headers: List of (header_name, header_value) tuples
                exc_info: Exception information (optional)
                
            Returns:
                Result of calling original start_response
            """
            headers_to_remove_lower = {h.lower() for h in self.headers_to_remove}
            
            sanitized_headers = [
                (name, value) for name, value in headers
                if name.lower() not in headers_to_remove_lower
            ]
            
            return start_response(status, sanitized_headers, exc_info)
        
        return self.app(environ, sanitizing_start_response)


def remove_development_server_header():
    """
    Override Python's http.server to prevent Server header in development
    
    Flask's development server (Werkzeug) uses Python's http.server module,
    which hardcodes the Server header. We override version_string() to
    return an empty string, preventing the header from being added.
    
    This only affects Flask's development server (app.run()).
    Production WSGI servers (Gunicorn, uWSGI) are handled by the WSGI middleware.
    """
    http.server.BaseHTTPRequestHandler.version_string = lambda self: ""


def init_header_sanitization(app):
    """
    Initialize header sanitization for Flask application
    
    Applies two-layer protection:
    1. Overrides Python's http.server for development server (app.run())
    2. Wraps WSGI app with middleware for production servers (Gunicorn, uWSGI)
    
    This ensures info-leaking headers are removed in both development
    and production environments.
    
    Args:
        app: Flask application instance
    """
    remove_development_server_header()
    
    app.wsgi_app = HeaderSanitizationMiddleware(app.wsgi_app)
