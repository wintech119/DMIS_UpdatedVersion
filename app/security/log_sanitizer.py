"""
Log Sanitizer - Prevents Log Forging attacks

This module provides utilities to sanitize user input before including it in log messages,
preventing attackers from injecting malicious content (newlines, control characters)
that could forge log entries or exploit log analysis tools.

Security Context:
- Log Forging (CWE-117): Writing user input to logs without validation can allow
  attackers to forge log entries by injecting newline characters
- This can lead to log injection, log tampering, and can mislead security investigations

Usage:
    from app.security.log_sanitizer import sanitize_for_log
    
    logger.info("User %s logged in", sanitize_for_log(username))
    logger.warning("Failed login attempt for user %s from IP %s", 
                   sanitize_for_log(username), sanitize_for_log(ip_address))
"""

import re
from typing import Any, Optional


def sanitize_for_log(value: Any, max_length: int = 500) -> str:
    """
    Sanitize a value for safe inclusion in log messages.
    
    This function:
    1. Converts input to string safely (handles None, objects, etc.)
    2. Replaces newline characters (\\n, \\r) with safe markers to prevent log forging
    3. Replaces other control characters that could corrupt logs
    4. Truncates overly long strings to prevent log flooding
    5. Removes or escapes characters that could be used for log injection
    
    Args:
        value: Any value to sanitize (will be converted to string)
        max_length: Maximum length of the output string (default 500)
        
    Returns:
        A sanitized string safe for logging
        
    Examples:
        >>> sanitize_for_log("normal user input")
        'normal user input'
        
        >>> sanitize_for_log("line1\\nline2")
        'line1[LF]line2'
        
        >>> sanitize_for_log(None)
        '[None]'
        
        >>> sanitize_for_log("x" * 1000, max_length=100)
        'xxxx...(truncated)'
    """
    if value is None:
        return "[None]"
    
    try:
        s = str(value)
    except Exception:
        return "[UnprintableObject]"
    
    s = s.replace("\r\n", "[CRLF]")
    s = s.replace("\n", "[LF]")
    s = s.replace("\r", "[CR]")
    
    s = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '[CTRL]', s)
    
    s = s.replace('\t', '[TAB]')
    
    if len(s) > max_length:
        s = s[:max_length] + "...(truncated)"
    
    return s


def sanitize_url_for_log(url: str, max_length: int = 200) -> str:
    """
    Sanitize a URL for safe inclusion in log messages.
    
    Special handling for URLs:
    - Preserves URL structure for debugging
    - Masks query string values (could contain sensitive data)
    - Removes fragments
    - Applies standard sanitization
    
    Args:
        url: URL string to sanitize
        max_length: Maximum length of the output string (default 200)
        
    Returns:
        A sanitized URL string safe for logging
    """
    if not url:
        return "[EmptyURL]"
    
    try:
        base_url = sanitize_for_log(url.split('?')[0], max_length=max_length)
        
        if '?' in url:
            query_part = url.split('?', 1)[1]
            if query_part:
                param_count = query_part.count('=')
                base_url += f"?[{param_count} param(s) redacted]"
        
        return base_url
        
    except Exception:
        return sanitize_for_log(url, max_length)


def sanitize_dict_for_log(d: dict, max_length: int = 500, 
                          sensitive_keys: Optional[set] = None) -> str:
    """
    Sanitize a dictionary for safe inclusion in log messages.
    
    Args:
        d: Dictionary to sanitize
        max_length: Maximum length of the output string
        sensitive_keys: Set of keys whose values should be redacted
        
    Returns:
        A sanitized string representation of the dictionary
    """
    if d is None:
        return "[None]"
    
    if not isinstance(d, dict):
        return sanitize_for_log(d, max_length)
    
    if sensitive_keys is None:
        sensitive_keys = {
            'password', 'secret', 'token', 'key', 'auth', 'credential',
            'ssn', 'credit_card', 'card_number', 'cvv', 'pin'
        }
    
    sanitized_items = []
    for key, value in d.items():
        key_lower = str(key).lower()
        if any(sensitive in key_lower for sensitive in sensitive_keys):
            sanitized_items.append(f"{key}=[REDACTED]")
        else:
            sanitized_items.append(f"{key}={sanitize_for_log(value, max_length=100)}")
    
    result = "{" + ", ".join(sanitized_items) + "}"
    
    if len(result) > max_length:
        result = result[:max_length] + "...(truncated)}"
    
    return result


def sanitize_exception_for_log(exc: Exception, max_length: int = 500) -> str:
    """
    Sanitize an exception message for safe inclusion in log messages.
    
    Args:
        exc: Exception to sanitize
        max_length: Maximum length of the output string
        
    Returns:
        A sanitized exception message string
    """
    if exc is None:
        return "[NoException]"
    
    try:
        exc_type = type(exc).__name__
        exc_msg = sanitize_for_log(str(exc), max_length=max_length - len(exc_type) - 3)
        return f"{exc_type}: {exc_msg}"
    except Exception:
        return "[UnprintableException]"
