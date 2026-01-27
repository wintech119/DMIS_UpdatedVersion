"""
Parameter validation utilities for security-hardened input handling.

This module provides functions to safely validate and sanitize request parameters
to prevent parameter tampering and unchecked input vulnerabilities.

Usage:
    from app.security.param_validation import (
        safe_int, safe_decimal, safe_page, safe_per_page,
        validate_status_code, validate_filter_value, clamp
    )
"""

from decimal import Decimal, InvalidOperation
from typing import Optional, Set, Any, TypeVar

T = TypeVar('T')


def clamp(value: int, min_val: int, max_val: int) -> int:
    """Clamp an integer value between min and max bounds."""
    return max(min_val, min(value, max_val))


def safe_int(value: Any, default: int = 0, min_val: Optional[int] = None, 
             max_val: Optional[int] = None) -> int:
    """
    Safely convert a value to an integer with optional bounds.
    
    Args:
        value: The value to convert (typically from request.args/form)
        default: Default value if conversion fails
        min_val: Optional minimum bound
        max_val: Optional maximum bound
        
    Returns:
        Integer value within bounds, or default if conversion fails
    """
    if value is None:
        return default
    
    try:
        result = int(value)
    except (ValueError, TypeError):
        return default
    
    if min_val is not None:
        result = max(result, min_val)
    if max_val is not None:
        result = min(result, max_val)
    
    return result


def safe_float(value: Any, default: float = 0.0, min_val: Optional[float] = None,
               max_val: Optional[float] = None) -> float:
    """
    Safely convert a value to a float with optional bounds.
    
    Args:
        value: The value to convert
        default: Default value if conversion fails
        min_val: Optional minimum bound
        max_val: Optional maximum bound
        
    Returns:
        Float value within bounds, or default if conversion fails
    """
    if value is None:
        return default
    
    try:
        result = float(value)
    except (ValueError, TypeError):
        return default
    
    if min_val is not None:
        result = max(result, min_val)
    if max_val is not None:
        result = min(result, max_val)
    
    return result


def safe_decimal(value: Any, default: str = '0', min_val: Optional[Decimal] = None,
                 max_val: Optional[Decimal] = None) -> Decimal:
    """
    Safely convert a value to a Decimal with optional bounds.
    
    Args:
        value: The value to convert
        default: Default value string if conversion fails
        min_val: Optional minimum bound (as Decimal)
        max_val: Optional maximum bound (as Decimal)
        
    Returns:
        Decimal value within bounds, or default Decimal if conversion fails
    """
    if value is None or (isinstance(value, str) and value.strip() == ''):
        return Decimal(default)
    
    try:
        result = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)
    
    if min_val is not None and result < min_val:
        result = min_val
    if max_val is not None and result > max_val:
        result = max_val
    
    return result


def safe_page(value: Any, default: int = 1) -> int:
    """
    Safely convert a page number parameter.
    Page numbers must be >= 1.
    
    Args:
        value: The page value from request.args
        default: Default page number (typically 1)
        
    Returns:
        Valid page number (always >= 1)
    """
    return safe_int(value, default=default, min_val=1)


def safe_per_page(value: Any, default: int = 25, max_per_page: int = 100) -> int:
    """
    Safely convert a per_page/page_size parameter.
    
    Args:
        value: The per_page value from request.args
        default: Default items per page
        max_per_page: Maximum allowed items per page (prevents DoS)
        
    Returns:
        Valid per_page value (between 1 and max_per_page)
    """
    return safe_int(value, default=default, min_val=1, max_val=max_per_page)


def safe_period_days(value: Any, default: int = 30, min_days: int = 1, 
                     max_days: int = 365) -> int:
    """
    Safely convert a period/days parameter for date range filters.
    
    Args:
        value: The period value from request.args
        default: Default period in days
        min_days: Minimum allowed days
        max_days: Maximum allowed days
        
    Returns:
        Valid period value within bounds
    """
    return safe_int(value, default=default, min_val=min_days, max_val=max_days)


def safe_loop_count(value: Any, default: int = 0, max_count: int = 1000) -> int:
    """
    Safely convert a value used in loop iteration counts.
    Enforces upper bound to prevent DoS through excessive iterations.
    
    Args:
        value: The count value that will control loop iterations
        default: Default count if conversion fails
        max_count: Maximum allowed iterations (prevents DoS)
        
    Returns:
        Valid count value (between 0 and max_count)
    """
    return safe_int(value, default=default, min_val=0, max_val=max_count)


def validate_status_code(value: Any, allowed_values: Set[str], 
                         default: str = 'all') -> str:
    """
    Validate a status code parameter against an allowlist.
    
    Args:
        value: The status code from request.args/form
        allowed_values: Set of allowed status codes
        default: Default value if not in allowlist
        
    Returns:
        The status code if valid, otherwise default
    """
    if value is None:
        return default
    
    value_str = str(value).strip()
    
    if value_str in allowed_values:
        return value_str
    
    return default


def validate_filter_value(value: Any, allowed_values: Set[str], 
                          default: str = 'all') -> str:
    """
    Validate a filter parameter against an allowlist.
    Case-insensitive comparison.
    
    Args:
        value: The filter value from request.args
        allowed_values: Set of allowed filter values (lowercase)
        default: Default value if not in allowlist
        
    Returns:
        The filter value if valid (lowercase), otherwise default
    """
    if value is None:
        return default
    
    value_str = str(value).strip().lower()
    
    if value_str in allowed_values:
        return value_str
    
    return default


def safe_quantity(value: Any, default: str = '0', min_qty: Decimal = Decimal('0'),
                  max_qty: Decimal = Decimal('999999999.99')) -> Decimal:
    """
    Safely convert a quantity parameter with business-appropriate bounds.
    
    Args:
        value: The quantity value from request.form
        default: Default quantity string if conversion fails
        min_qty: Minimum allowed quantity (typically 0)
        max_qty: Maximum allowed quantity
        
    Returns:
        Valid Decimal quantity within bounds
    """
    return safe_decimal(value, default=default, min_val=min_qty, max_val=max_qty)


def safe_amount(value: Any, default: str = '0.00', min_amount: Decimal = Decimal('0'),
                max_amount: Decimal = Decimal('999999999999.99')) -> Decimal:
    """
    Safely convert a monetary amount parameter.
    
    Args:
        value: The amount value from request.form
        default: Default amount string if conversion fails
        min_amount: Minimum allowed amount
        max_amount: Maximum allowed amount
        
    Returns:
        Valid Decimal amount within bounds
    """
    return safe_decimal(value, default=default, min_val=min_amount, max_val=max_amount)


def safe_id(value: Any, default: int = 0) -> int:
    """
    Safely convert an ID parameter.
    IDs must be positive integers.
    
    Args:
        value: The ID value from request.args/form
        default: Default ID if conversion fails (typically 0 for "not found")
        
    Returns:
        Valid positive integer ID, or default
    """
    return safe_int(value, default=default, min_val=0)


def safe_version_number(value: Any, default: int = 0) -> int:
    """
    Safely convert a version number for optimistic locking.
    Version numbers must be non-negative.
    
    Args:
        value: The version_nbr value from request.form
        default: Default version if conversion fails
        
    Returns:
        Valid non-negative version number
    """
    return safe_int(value, default=default, min_val=0)
