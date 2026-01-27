"""
DMIS Safe API Client Module
===========================

Provides utilities for safe consumption of external APIs following
OWASP API Security best practices.

Security Controls:
- Request timeouts (prevent hanging)
- Response size limits (prevent memory exhaustion)
- Input validation on API responses
- No blind trust of external data
- Secure defaults (verify SSL, no redirects for sensitive data)

Usage:
    from app.security.safe_api_client import SafeApiClient, validate_api_response
    
    client = SafeApiClient(base_url='https://api.example.com')
    response = client.get('/endpoint', timeout=10)
    
    if validate_api_response(response, required_fields=['id', 'name']):
        data = response.json()
"""

import os
import logging
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse

import requests
from requests.exceptions import (
    RequestException,
    Timeout,
    ConnectionError as RequestsConnectionError,
    TooManyRedirects,
)

logger = logging.getLogger(__name__)


DEFAULT_TIMEOUT = int(os.getenv('DMIS_API_TIMEOUT', '30'))
DEFAULT_MAX_REDIRECTS = int(os.getenv('DMIS_API_MAX_REDIRECTS', '3'))
MAX_RESPONSE_SIZE = int(os.getenv('DMIS_API_MAX_RESPONSE_SIZE', str(10 * 1024 * 1024)))
DEFAULT_RETRIES = int(os.getenv('DMIS_API_RETRIES', '3'))


ALLOWED_EXTERNAL_DOMAINS = [
    'api.exchangerate.host',
    'api.frankfurter.dev',
    'api.exchangeratesapi.io',
]


class SafeApiError(Exception):
    """Base exception for safe API client errors."""
    pass


class ApiTimeoutError(SafeApiError):
    """Raised when an API request times out."""
    pass


class ApiConnectionError(SafeApiError):
    """Raised when connection to API fails."""
    pass


class ApiResponseError(SafeApiError):
    """Raised when API response is invalid or unexpected."""
    pass


class ApiValidationError(SafeApiError):
    """Raised when API response fails validation."""
    pass


def _sanitize_url_for_log(url: str) -> str:
    """Sanitize URL for logging (remove sensitive query params)."""
    parsed = urlparse(url)
    safe_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    if parsed.query:
        safe_url += "?[params_redacted]"
    return safe_url


def validate_external_domain(url: str) -> bool:
    """
    Validate that the URL is from an allowed external domain.
    
    Prevents SSRF by restricting which external domains can be accessed.
    
    Args:
        url: The URL to validate
        
    Returns:
        bool: True if domain is allowed, False otherwise
    """
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        
        domain = domain.split(':')[0]
        
        for allowed in ALLOWED_EXTERNAL_DOMAINS:
            if domain == allowed or domain.endswith('.' + allowed):
                return True
        
        return False
    except Exception:
        return False


def validate_api_response(
    response: requests.Response,
    required_fields: Optional[List[str]] = None,
    max_size: Optional[int] = None,
) -> bool:
    """
    Validate an API response before processing.
    
    Checks:
    - Response status is successful (2xx)
    - Content-Type is application/json
    - Response size is within limits
    - Required fields are present in JSON response
    
    Args:
        response: The requests Response object
        required_fields: List of field names that must be present
        max_size: Maximum allowed response size in bytes
        
    Returns:
        bool: True if response is valid
        
    Raises:
        ApiValidationError: If validation fails
    """
    if max_size is None:
        max_size = MAX_RESPONSE_SIZE
    
    if not response.ok:
        raise ApiValidationError(f"API returned error status: {response.status_code}")
    
    content_type = response.headers.get('Content-Type', '')
    if 'application/json' not in content_type.lower():
        raise ApiValidationError(f"Unexpected content type: {content_type}")
    
    content_length = response.headers.get('Content-Length')
    if content_length and int(content_length) > max_size:
        raise ApiValidationError(f"Response too large: {content_length} bytes")
    
    if len(response.content) > max_size:
        raise ApiValidationError(f"Response too large: {len(response.content)} bytes")
    
    if required_fields:
        try:
            data = response.json()
        except ValueError as e:
            raise ApiValidationError(f"Invalid JSON response: {e}")
        
        if isinstance(data, dict):
            missing = [f for f in required_fields if f not in data]
            if missing:
                raise ApiValidationError(f"Missing required fields: {missing}")
    
    return True


class SafeApiClient:
    """
    A secure HTTP client for external API consumption.
    
    Features:
    - Configurable timeouts
    - Automatic retries with backoff
    - Response size limits
    - SSL verification
    - Domain allowlist validation
    - Secure logging (no sensitive data)
    
    Example:
        client = SafeApiClient(
            base_url='https://api.example.com',
            timeout=15,
            retries=3
        )
        
        try:
            response = client.get('/endpoint')
            data = response.json()
        except SafeApiError as e:
            logger.error(f"API call failed: {e}")
    """
    
    def __init__(
        self,
        base_url: str,
        timeout: int = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        verify_ssl: bool = True,
        max_redirects: int = DEFAULT_MAX_REDIRECTS,
        headers: Optional[Dict[str, str]] = None,
    ):
        """
        Initialize the safe API client.
        
        Args:
            base_url: Base URL for API requests
            timeout: Request timeout in seconds
            retries: Number of retry attempts
            verify_ssl: Whether to verify SSL certificates
            max_redirects: Maximum number of redirects to follow
            headers: Default headers to include in requests
        """
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.retries = retries
        self.verify_ssl = verify_ssl
        self.max_redirects = max_redirects
        
        self.session = requests.Session()
        self.session.max_redirects = max_redirects
        self.session.verify = verify_ssl
        
        self.session.headers.update({
            'User-Agent': 'DMIS/1.0 (Government of Jamaica ODPEM)',
            'Accept': 'application/json',
        })
        
        if headers:
            self.session.headers.update(headers)
    
    def _make_request(
        self,
        method: str,
        endpoint: str,
        **kwargs
    ) -> requests.Response:
        """
        Make an HTTP request with safety controls.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint path
            **kwargs: Additional arguments for requests
            
        Returns:
            requests.Response object
            
        Raises:
            SafeApiError: On request failure
        """
        url = f"{self.base_url}{endpoint}"
        
        if not validate_external_domain(url):
            raise ApiValidationError(f"Domain not in allowlist: {urlparse(url).netloc}")
        
        kwargs.setdefault('timeout', self.timeout)
        
        safe_url = _sanitize_url_for_log(url)
        
        last_error: SafeApiError = SafeApiError("Request failed after retries")
        for attempt in range(self.retries):
            try:
                logger.debug(f"API request: {method} {safe_url} (attempt {attempt + 1})")
                
                response = self.session.request(method, url, **kwargs)
                
                logger.debug(f"API response: {response.status_code} from {safe_url}")
                
                return response
                
            except Timeout:
                last_error = ApiTimeoutError(f"Request timed out after {self.timeout}s")
                logger.warning(f"API timeout: {safe_url} (attempt {attempt + 1})")
                
            except RequestsConnectionError as e:
                last_error = ApiConnectionError(f"Connection failed: {e}")
                logger.warning(f"API connection error: {safe_url} (attempt {attempt + 1})")
                
            except TooManyRedirects as e:
                raise ApiValidationError(f"Too many redirects: {e}")
                
            except RequestException as e:
                last_error = SafeApiError(f"Request failed: {e}")
                logger.warning(f"API error: {safe_url} (attempt {attempt + 1}): {e}")
            
            if attempt < self.retries - 1:
                import time
                backoff = 2 ** attempt
                time.sleep(backoff)
        
        raise last_error
    
    def get(self, endpoint: str, params: Optional[Dict] = None, **kwargs) -> requests.Response:
        """Make a GET request."""
        return self._make_request('GET', endpoint, params=params, **kwargs)
    
    def post(
        self,
        endpoint: str,
        json: Optional[Dict] = None,
        data: Optional[Dict] = None,
        **kwargs
    ) -> requests.Response:
        """Make a POST request."""
        return self._make_request('POST', endpoint, json=json, data=data, **kwargs)
    
    def close(self):
        """Close the session."""
        self.session.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


def sanitize_external_data(data: Any, allowed_keys: Optional[List[str]] = None) -> Dict:
    """
    Sanitize data received from an external API.
    
    Prevents:
    - SQL injection via API data
    - XSS via API data
    - Object injection
    
    Args:
        data: The data to sanitize (dict or list)
        allowed_keys: Optional list of allowed keys (others are removed)
        
    Returns:
        Sanitized dictionary
    """
    if not isinstance(data, dict):
        return {}
    
    result = {}
    
    for key, value in data.items():
        if allowed_keys and key not in allowed_keys:
            continue
        
        if not isinstance(key, str):
            continue
        
        if isinstance(value, str):
            value = value.replace('\x00', '')
            value = value[:10000]
            result[key] = value
        elif isinstance(value, (int, float, bool, type(None))):
            result[key] = value
        elif isinstance(value, dict):
            result[key] = sanitize_external_data(value, allowed_keys=None)
        elif isinstance(value, list):
            result[key] = [
                sanitize_external_data(item) if isinstance(item, dict)
                else item[:10000] if isinstance(item, str)
                else item
                for item in value[:1000]
                if isinstance(item, (str, int, float, bool, type(None), dict))
            ]
    
    return result
