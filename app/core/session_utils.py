"""
Session Utilities for Trust Boundary Validation

This module provides type-validated access to session-derived user data,
addressing Trust Boundary Violation concerns by ensuring all session values
are properly validated before use in business logic, SQL queries, or
authorization decisions.

All accessors perform type checking and return None for invalid/missing data.
"""
from flask_login import current_user
from typing import Optional, List


VALID_STATUS_CODES = frozenset(['A', 'I', 'D', 'L', 'P'])

MAX_ROLE_CODE_LENGTH = 50

_valid_role_codes_cache = None

def _get_valid_role_codes() -> frozenset:
    """
    Get valid role codes from the database.
    Caches the result for performance.
    
    Returns:
        frozenset: Set of valid role codes from the database
    """
    global _valid_role_codes_cache
    if _valid_role_codes_cache is not None:
        return _valid_role_codes_cache
    
    try:
        from flask import has_app_context
        if not has_app_context():
            return frozenset()
        
        from app.db.models import Role
        roles = Role.query.with_entities(Role.code).all()
        _valid_role_codes_cache = frozenset(r.code.strip().upper() for r in roles if r.code)
        return _valid_role_codes_cache
    except Exception:
        return frozenset()


def clear_role_codes_cache():
    """Clear the cached role codes (useful for testing or after role changes)."""
    global _valid_role_codes_cache
    _valid_role_codes_cache = None


def is_authenticated() -> bool:
    """
    Check if current user is authenticated with valid session.
    
    Returns:
        bool: True if user is authenticated and session is valid
    """
    try:
        return current_user is not None and current_user.is_authenticated
    except (AttributeError, TypeError):
        return False


def get_user_id() -> Optional[int]:
    """
    Get the current user's ID with type validation.
    
    Returns:
        Optional[int]: User ID if valid, None otherwise
    """
    if not is_authenticated():
        return None
    
    try:
        user_id = current_user.user_id
        if user_id is None:
            return None
        if isinstance(user_id, int):
            return user_id if user_id > 0 else None
        user_id_int = int(user_id)
        return user_id_int if user_id_int > 0 else None
    except (AttributeError, TypeError, ValueError):
        return None


def get_user_name() -> Optional[str]:
    """
    Get the current user's username with type validation.
    
    Returns:
        Optional[str]: Username string if valid, None otherwise
    """
    if not is_authenticated():
        return None
    
    try:
        user_name = current_user.user_name
        if not isinstance(user_name, str):
            return None
        user_name = user_name.strip()
        if len(user_name) == 0 or len(user_name) > 20:
            return None
        return user_name
    except (AttributeError, TypeError):
        return None


def get_email() -> Optional[str]:
    """
    Get the current user's email with type and format validation.
    
    Returns:
        Optional[str]: Email string if valid, None otherwise
    """
    if not is_authenticated():
        return None
    
    try:
        email = current_user.email
        if not isinstance(email, str):
            return None
        email = email.strip().lower()
        if len(email) == 0 or len(email) > 200:
            return None
        if '@' not in email or '.' not in email:
            return None
        return email
    except (AttributeError, TypeError):
        return None


def get_agency_id() -> Optional[int]:
    """
    Get the current user's agency ID with type validation.
    
    Returns:
        Optional[int]: Agency ID if valid, None if not set or invalid
    """
    if not is_authenticated():
        return None
    
    try:
        agency_id = current_user.agency_id
        if agency_id is None:
            return None
        if isinstance(agency_id, int):
            return agency_id if agency_id > 0 else None
        agency_id_int = int(agency_id)
        return agency_id_int if agency_id_int > 0 else None
    except (AttributeError, TypeError, ValueError):
        return None


def get_role_codes() -> List[str]:
    """
    Get the current user's role codes with validation against database roles.
    
    Validates that each role code:
    1. Is a string type
    2. Is within expected length bounds
    3. Exists in the database Role table (authoritative source)
    
    This addresses Trust Boundary Violation by validating session-derived
    role codes against the database before use in authorization decisions.
    
    Returns:
        List[str]: List of validated role code strings
    """
    if not is_authenticated():
        return []
    
    try:
        roles = current_user.roles
        if roles is None:
            return []
        
        valid_codes = _get_valid_role_codes()
        validated_codes = []
        for role in roles:
            if hasattr(role, 'code') and isinstance(role.code, str):
                code = role.code.strip().upper()
                if 0 < len(code) <= MAX_ROLE_CODE_LENGTH and code in valid_codes:
                    validated_codes.append(code)
        return validated_codes
    except (AttributeError, TypeError):
        return []


def get_role_names() -> List[str]:
    """
    Get the current user's role names with type validation.
    
    Returns:
        List[str]: List of role name strings
    """
    if not is_authenticated():
        return []
    
    try:
        roles = current_user.roles
        if roles is None:
            return []
        
        validated_names = []
        for role in roles:
            if hasattr(role, 'name') and isinstance(role.name, str):
                name = role.name.strip()
                if 0 < len(name) <= 100:
                    validated_names.append(name)
        return validated_names
    except (AttributeError, TypeError):
        return []


def get_warehouse_ids() -> List[int]:
    """
    Get the current user's accessible warehouse IDs with validation.
    
    Returns:
        List[int]: List of validated warehouse ID integers
    """
    if not is_authenticated():
        return []
    
    try:
        warehouses = current_user.warehouses
        if warehouses is None:
            return []
        
        validated_ids = []
        for warehouse in warehouses:
            if hasattr(warehouse, 'warehouse_id'):
                wh_id = warehouse.warehouse_id
                if isinstance(wh_id, int) and wh_id > 0:
                    validated_ids.append(wh_id)
                elif wh_id is not None:
                    try:
                        wh_id_int = int(wh_id)
                        if wh_id_int > 0:
                            validated_ids.append(wh_id_int)
                    except (TypeError, ValueError):
                        continue
        return validated_ids
    except (AttributeError, TypeError):
        return []


def get_first_name() -> Optional[str]:
    """
    Get the current user's first name with type validation.
    
    Returns:
        Optional[str]: First name string if valid, None otherwise
    """
    if not is_authenticated():
        return None
    
    try:
        first_name = current_user.first_name
        if not isinstance(first_name, str):
            return None
        first_name = first_name.strip()
        if len(first_name) == 0 or len(first_name) > 100:
            return None
        return first_name
    except (AttributeError, TypeError):
        return None


def get_last_name() -> Optional[str]:
    """
    Get the current user's last name with type validation.
    
    Returns:
        Optional[str]: Last name string if valid, None otherwise
    """
    if not is_authenticated():
        return None
    
    try:
        last_name = current_user.last_name
        if not isinstance(last_name, str):
            return None
        last_name = last_name.strip()
        if len(last_name) == 0 or len(last_name) > 100:
            return None
        return last_name
    except (AttributeError, TypeError):
        return None


def get_full_name() -> Optional[str]:
    """
    Get the current user's full name with type validation.
    Falls back to constructing from first/last name if full_name not set.
    
    Returns:
        Optional[str]: Full name string if valid, None otherwise
    """
    if not is_authenticated():
        return None
    
    try:
        full_name = current_user.full_name
        if isinstance(full_name, str):
            full_name = full_name.strip()
            if 0 < len(full_name) <= 200:
                return full_name
        
        first = get_first_name()
        last = get_last_name()
        if first and last:
            return f"{first} {last}"
        return first or last
    except (AttributeError, TypeError):
        return None


def get_display_name() -> str:
    """
    Get a display name for the current user.
    Falls back through full name -> first name -> email prefix -> 'User'.
    
    Returns:
        str: Display name (never None)
    """
    full_name = get_full_name()
    if full_name:
        return full_name
    
    first_name = get_first_name()
    if first_name:
        return first_name
    
    email = get_email()
    if email:
        return email.split('@')[0]
    
    return 'User'


def has_valid_role(*role_codes: str) -> bool:
    """
    Check if user has any of the specified roles with validation.
    
    Args:
        *role_codes: Role codes to check against
        
    Returns:
        bool: True if user has any of the specified roles
    """
    if not role_codes:
        return False
    
    user_roles = get_role_codes()
    if not user_roles:
        return False
    
    check_codes = set()
    for code in role_codes:
        if isinstance(code, str):
            normalized = code.strip().upper()
            if normalized:
                check_codes.add(normalized)
    
    return bool(check_codes & set(user_roles))


def has_warehouse_access(warehouse_id) -> bool:
    """
    Check if user has access to a specific warehouse with validation.
    
    Args:
        warehouse_id: Warehouse ID to check
        
    Returns:
        bool: True if user has access to the warehouse
    """
    if warehouse_id is None:
        return False
    
    try:
        wh_id = int(warehouse_id)
        if wh_id <= 0:
            return False
    except (TypeError, ValueError):
        return False
    
    if has_valid_role('SYSTEM_ADMINISTRATOR', 'SYS_ADMIN', 'LOGISTICS_MANAGER'):
        return True
    
    return wh_id in get_warehouse_ids()


def is_agency_user() -> bool:
    """
    Check if current user is an agency user (has valid agency_id).
    
    Returns:
        bool: True if user is authenticated and has valid agency_id
    """
    return get_agency_id() is not None


def require_user_id() -> int:
    """
    Get user ID or raise ValueError if not available.
    Use this for operations that require a valid user ID.
    
    Returns:
        int: Valid user ID
        
    Raises:
        ValueError: If user is not authenticated or user_id is invalid
    """
    user_id = get_user_id()
    if user_id is None:
        raise ValueError("Valid user session required")
    return user_id


def require_user_name() -> str:
    """
    Get username or raise ValueError if not available.
    Use this for audit trail operations.
    
    Returns:
        str: Valid username
        
    Raises:
        ValueError: If user is not authenticated or user_name is invalid
    """
    user_name = get_user_name()
    if user_name is None:
        raise ValueError("Valid user session required")
    return user_name


def require_agency_id() -> int:
    """
    Get agency ID or raise ValueError if not available.
    Use this for agency-scoped operations.
    
    Returns:
        int: Valid agency ID
        
    Raises:
        ValueError: If user is not an agency user or agency_id is invalid
    """
    agency_id = get_agency_id()
    if agency_id is None:
        raise ValueError("Agency user required for this operation")
    return agency_id
