"""
DMIS Configuration Module

Configuration settings are loaded from environment variables.
Sensitive values MUST be set via environment variables in production.

Environment Variables:
- DMIS_SECRET_KEY / SECRET_KEY: Flask secret key (required in production)
- DMIS_DATABASE_URL / DATABASE_URL: Database connection string
- DMIS_DEBUG: Enable debug mode (default: false)
- DMIS_TESTING: Enable testing mode (default: false)
- DMIS_UPLOAD_FOLDER: Path for file uploads
- DMIS_LOG_TO_STDOUT: Log to stdout (default: false)
- DMIS_WORKFLOW_MODE: Application workflow mode (default: AIDMGMT)
- DMIS_ALLOW_DEV_SECRET_KEY: Allow auto-generated secret key in dev (default: false)

Security Notes:
- Never commit credentials or secrets to version control
- DEBUG is OFF by default - explicitly set DMIS_DEBUG=true for development
- Production deployments MUST set DMIS_SECRET_KEY environment variable
"""
import os
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv(usecwd=True))

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def _get_env(dmis_key: str, fallback_key: str = None, default: str = None) -> str | None:
    """
    Get environment variable with DMIS_ prefix priority.
    
    Checks DMIS_<key> first, then falls back to <key> for backward compatibility,
    then returns the default value.
    """
    value = os.environ.get(f'DMIS_{dmis_key}')
    if value is not None:
        return value
    if fallback_key:
        value = os.environ.get(fallback_key)
        if value is not None:
            return value
    return default


def _get_bool_env(dmis_key: str, fallback_key: str = None, default: bool = False) -> bool:
    """Get boolean environment variable with DMIS_ prefix priority."""
    value = _get_env(dmis_key, fallback_key)
    if value is None:
        return default
    return value.lower() in ('true', '1', 'yes', 'on')


def _get_secret_key() -> str | None:
    """
    Get SECRET_KEY from environment with secure fallback for development only.
    
    In production (DEBUG=false), SECRET_KEY must be explicitly set.
    In development (DEBUG=true or ALLOW_DEV_SECRET_KEY=true), a random key is generated.
    """
    secret_key = _get_env('SECRET_KEY', 'SECRET_KEY')
    if secret_key:
        return secret_key
    
    is_debug = _get_bool_env('DEBUG', 'FLASK_DEBUG', default=False)
    is_testing = _get_bool_env('TESTING', 'TESTING', default=False)
    is_allow_dev_key = _get_bool_env('ALLOW_DEV_SECRET_KEY', 'ALLOW_DEV_SECRET_KEY', default=False)
    
    if is_debug or is_testing or is_allow_dev_key:
        import secrets
        return secrets.token_hex(32)
    
    raise ValueError(
        "DMIS_SECRET_KEY environment variable must be set in production. "
        "Set DMIS_DEBUG=true for development or DMIS_ALLOW_DEV_SECRET_KEY=true "
        "to allow auto-generated keys."
    )



_keycloak = {
    'realm': os.getenv('KEYCLOAK_REALM', 'drims'),
    'server_url': os.getenv('KEYCLOAK_AUTH_SERVER_URL', 'http://localhost:8082'),
    'client_id': os.getenv('KEYCLOAK_CLIENT_ID','drims-web'),
    'client_secret': os.getenv('KEYCLOAK_CREDENTIALS_SECRET'),
    'admin_client': os.getenv('KEYCLOAK_ADMIN_CLI_ID', 'drims-web-admin'),
    'admin_secret': os.getenv('KEYCLOAK_ADMIN_CLI_SECRET', 'drims-web-admin-secret'),
    'metadata_url': '/realms/%(realm)s/.well-known/openid-configuration',
    'logout_url': '',
    'token_url': '/realms/%(realm)s/protocol/openid-connect/token'
}
_keycloak.update(
    metadata_url='%(server_url)s/realms/%(realm)s/.well-known/openid-configuration' % _keycloak,
)

def _env_true(varname, default_val='no'):
    val = os.getenv(varname, default_val)
    return val.upper() in ['TRUE', 'YES', '1'] 


class Config:
    """
    Flask application configuration.
    
    All sensitive values are loaded from environment variables.
    No credentials are hard-coded in this file.
    """
    
    SECRET_KEY = _get_secret_key()
    
    DATABASE_URL = _get_env('DATABASE_URL', 'DATABASE_URL')
    SQLALCHEMY_DATABASE_URI = DATABASE_URL
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    DEBUG = _get_bool_env('DEBUG', 'FLASK_DEBUG', default=False)
    TESTING = _get_bool_env('TESTING', 'TESTING', default=False)
    
    WORKFLOW_MODE = _get_env('WORKFLOW_MODE', 'WORKFLOW_MODE', default='AIDMGMT')
    
    TIMEZONE = 'America/Jamaica'
    TIMEZONE_OFFSET = -5
    
    GOJ_GREEN = '#006B3E'
    GOJ_GOLD = '#FFD100'
    
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max upload
    
    _upload_folder = _get_env('UPLOAD_FOLDER', 'UPLOAD_FOLDER')
    UPLOAD_FOLDER = _upload_folder if _upload_folder else os.path.join(BASE_DIR, 'uploads', 'donations')
    ALLOWED_EXTENSIONS = {'pdf', 'jpg', 'jpeg'}
    
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    
    LOG_TO_STDOUT = _get_bool_env('LOG_TO_STDOUT', 'LOG_TO_STDOUT', default=False)

    USER_AUTH_MODE = 'keycloak'  # or 'ldap'

    LDAP_CONF = {
        'server': os.getenv('LDAP_SERVER', 'mbox.fsl.org.jm'),
        'use_ssl': _env_true('LDAP_USE_SSL'),
        'start_tls': _env_true('LDAP_START_TLS'),
        'port': int(os.getenv('LDAP_SERVER_PORT', 389)),
        'admin_dn': os.getenv('LDAP_ADMIN_DN', None),
        'admin_pw': os.getenv('LDAP_ADMIN_PW', None),
        'user_base_dn': os.getenv('LDAP_USER_BASE_DN'),
        'user_object_class': ['inetOrgPerson', 'inetUser'],
        'user_login_attr': 'mail'
    }

    KEYCLOAK_CONF = {
        'server_url': _keycloak['server_url'],
        'client_id': _keycloak['client_id'],
        'realm_name': _keycloak['realm'],
        'client_secret_key': _keycloak['client_secret'],
        'verify': False
        
    }
    
    KEYCLOAK_ADMIN = {
        'server_url': _keycloak['server_url'],
        'username': _keycloak['admin_client'],
        'password': _keycloak['admin_secret'],
        'realm_name': _keycloak['realm'],
        'client_id': 'admin-cli',
        'verify': False
    }
    
    PREFERRED_URL_SCHEME = 'https'
    
    @classmethod
    def is_production(cls) -> bool:
        """Check if running in production mode (DEBUG=False)."""
        return not cls.DEBUG and not cls.TESTING
    
    @classmethod
    def validate_production_config(cls) -> list:
        """
        Validate configuration for production deployment.
        Returns a list of warnings/errors.
        """
        issues = []
        
        if not cls.SECRET_KEY:
            issues.append("SECRET_KEY is not set")
        elif len(cls.SECRET_KEY) < 32:
            issues.append("SECRET_KEY is too short (should be at least 32 characters)")
        
        if not cls.DATABASE_URL:
            issues.append("DATABASE_URL is not set")
        
        if cls.DEBUG:
            issues.append("DEBUG mode is enabled - should be disabled in production")
        
        return issues


class DevelopmentConfig(Config):
    """Development configuration with debug enabled."""
    DEBUG = True
    TESTING = False


class TestingConfig(Config):
    """Testing configuration."""
    DEBUG = False
    TESTING = True
    WTF_CSRF_ENABLED = False


class ProductionConfig(Config):
    """Production configuration with strict security settings."""
    DEBUG = False
    TESTING = False
    
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Strict'


config_by_name = {
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'production': ProductionConfig,
    'default': Config
}


def get_config(config_name: str = None):
    """
    Get configuration class by name.
    
    If no name provided, determines config based on environment variables.
    """
    if config_name:
        return config_by_name.get(config_name, Config)
    
    if _get_bool_env('TESTING', 'TESTING', default=False):
        return TestingConfig
    elif _get_bool_env('DEBUG', 'FLASK_DEBUG', default=False):
        return DevelopmentConfig
    else:
        return ProductionConfig
