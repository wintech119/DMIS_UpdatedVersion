"""
DMIS CORS Configuration Module
==============================

Configures Cross-Origin Resource Sharing (CORS) for the DMIS application
following OWASP API security best practices.

Security Principles:
- No wildcard (*) origins for credential-bearing endpoints
- Explicit allowed origins list (ODPEM/JAMICTA domains)
- Restricted methods per endpoint type
- Proper credential handling

Configuration:
- DMIS_CORS_ORIGINS: Comma-separated list of allowed origins
- DMIS_CORS_ENABLED: Enable/disable CORS (default: false in production)

Usage:
    from app.security.cors_config import init_cors
    
    init_cors(app)
"""

import os
import logging
from flask_cors import CORS

logger = logging.getLogger(__name__)


def _get_allowed_origins():
    """
    Get the list of allowed CORS origins.
    
    In production, this should be explicitly configured via environment variable.
    In development, localhost origins are allowed.
    
    Returns:
        List of allowed origin URLs
    """
    env_origins = os.getenv('DMIS_CORS_ORIGINS', '')
    
    if env_origins:
        return [origin.strip() for origin in env_origins.split(',') if origin.strip()]
    
    is_debug = os.getenv('DMIS_DEBUG', 'false').lower() in ('true', '1', 'yes', 'on')
    
    if is_debug:
        return [
            'http://localhost:5000',
            'http://127.0.0.1:5000',
            'http://0.0.0.0:5000',
        ]
    
    return [
        'https://dmis.odpem.gov.jm',
        'https://www.odpem.gov.jm',
        'https://odpem.gov.jm',
    ]


CORS_CONFIG_API = {
    'origins': _get_allowed_origins,
    'methods': ['GET', 'POST', 'OPTIONS'],
    'allow_headers': ['Content-Type', 'X-CSRFToken', 'X-Requested-With'],
    'expose_headers': ['X-RateLimit-Limit', 'X-RateLimit-Remaining', 'X-RateLimit-Reset'],
    'supports_credentials': True,
    'max_age': 600,
}


CORS_CONFIG_PUBLIC = {
    'origins': '*',
    'methods': ['GET', 'OPTIONS'],
    'allow_headers': ['Content-Type'],
    'supports_credentials': False,
    'max_age': 3600,
}


API_PATTERNS = [
    r'/api/*',
    r'/notifications/api/*',
    r'/eligibility/api/*',
    r'/packaging/api/*',
    r'/transfers/api/*',
    r'/donations/api/*',
    r'/donation-intake/api/*',
]


PUBLIC_PATTERNS = [
    r'/health',
    r'/account-requests/submit',
]


def init_cors(app):
    """
    Initialize CORS for the Flask application.
    
    Applies different CORS policies based on endpoint type:
    - API endpoints: Restricted origins, credentials allowed
    - Public endpoints: Open access, no credentials
    - Default: Restricted to same-origin
    
    Args:
        app: Flask application instance
    """
    cors_enabled = os.getenv('DMIS_CORS_ENABLED', 'false').lower() in ('true', '1', 'yes', 'on')
    
    if not cors_enabled:
        logger.info("CORS is disabled (DMIS_CORS_ENABLED=false)")
        return
    
    CORS(
        app,
        resources={
            r'/api/*': CORS_CONFIG_API,
            r'/notifications/api/*': CORS_CONFIG_API,
            r'/eligibility/api/*': CORS_CONFIG_API,
            r'/packaging/api/*': CORS_CONFIG_API,
            r'/health': CORS_CONFIG_PUBLIC,
            r'/account-requests/submit': CORS_CONFIG_PUBLIC,
        },
    )
    
    allowed_origins = _get_allowed_origins()
    logger.info(f"CORS initialized with allowed origins: {allowed_origins}")


def validate_origin(request_origin):
    """
    Validate that a request origin is in the allowed list.
    
    Use this for manual origin validation in sensitive endpoints.
    
    Args:
        request_origin: The Origin header value from the request
        
    Returns:
        bool: True if origin is allowed, False otherwise
    """
    if not request_origin:
        return True
    
    allowed = _get_allowed_origins()
    
    if callable(allowed):
        allowed = allowed()
    
    return request_origin in allowed
