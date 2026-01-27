"""
Role-Based Access Control (RBAC) utilities
"""
from functools import wraps
from flask import flash, redirect, url_for, abort
from flask_login import current_user
from app.db import db
from sqlalchemy import text
from app.core import session_utils


# =============================================================================
# ROLE GROUP CONSTANTS
# =============================================================================
# Executive roles - Director General, Deputy DG, and Director PEOD
# These roles share the same executive-level permissions for eligibility approval
EXECUTIVE_ROLES = ('ODPEM_DG', 'ODPEM_DDG', 'ODPEM_DIR_PEOD')

# Logistics team roles
LOGISTICS_ROLES = ('LOGISTICS_MANAGER', 'LOGISTICS_OFFICER')

# Agency roles
AGENCY_ROLES = ('AGENCY_DISTRIBUTOR', 'AGENCY_SHELTER')


def role_required(*role_codes):
    """
    Decorator to restrict access to routes based on user roles.
    
    Usage:
        @role_required('LOGISTICS_MANAGER', 'SYSTEM_ADMINISTRATOR')
        def my_route():
            ...
    
    Args:
        *role_codes: One or more role codes that are allowed to access the route
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not session_utils.is_authenticated():
                flash('Please log in to access this page.', 'warning')
                return redirect(url_for('login'))
            
            user_role_codes = session_utils.get_role_codes()
            
            if not any(code in user_role_codes for code in role_codes):
                flash('You do not have permission to access this page.', 'danger')
                abort(403)
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def has_role(*role_codes):
    """
    Check if the current user has any of the specified roles.
    
    Usage in templates:
        {% if has_role('LOGISTICS_MANAGER', 'SYSTEM_ADMINISTRATOR') %}
            <a href="#">Admin Link</a>
        {% endif %}
    
    Args:
        *role_codes: One or more role codes to check
        
    Returns:
        bool: True if user has any of the specified roles
    """
    return session_utils.has_valid_role(*role_codes)


def has_all_roles(*role_codes):
    """
    Check if the current user has ALL of the specified roles.
    
    Args:
        *role_codes: One or more role codes to check
        
    Returns:
        bool: True if user has all of the specified roles
    """
    if not session_utils.is_authenticated():
        return False
    
    user_role_codes = session_utils.get_role_codes()
    return all(code in user_role_codes for code in role_codes)


def agency_user_required(f):
    """
    Decorator to restrict access to agency users only.
    Ensures current_user has an agency_id set.
    
    Usage:
        @agency_user_required
        def my_route():
            # Only accessible to users with agency_id
            ...
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session_utils.is_authenticated():
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('login'))
        
        if not session_utils.get_agency_id():
            flash('This page is only accessible to agency users.', 'danger')
            abort(403)
        
        return f(*args, **kwargs)
    return decorated_function


def is_agency_user():
    """
    Check if the current user is an agency user (has agency_id set).
    
    Returns:
        bool: True if user is authenticated and has agency_id
    """
    return session_utils.is_agency_user()


def can_access_relief_request(relief_request):
    """
    Check if the current user can access/edit a relief request.
    
    User has access if:
    1. Request belongs to their agency (for agency users)
    2. User is a Logistics Manager or Logistics Officer (can access all requests)
    3. User is an ODPEM Executive (DG, Deputy DG, Director PEOD - read-only access to all requests)
    
    Args:
        relief_request: ReliefRqst object to check access for
        
    Returns:
        bool: True if user can access the request
    """
    if not session_utils.is_authenticated():
        return False
    
    # Logistics Managers and Officers have access to all relief requests
    if has_role(*LOGISTICS_ROLES):
        return True
    
    # ODPEM Executives have read-only access to all relief requests
    if has_role(*EXECUTIVE_ROLES):
        return True
    
    # Agency users can access their own agency's requests
    user_agency_id = session_utils.get_agency_id()
    if user_agency_id and relief_request.agency_id == user_agency_id:
        return True
    
    return False


def has_warehouse_access(warehouse_id):
    """
    Check if the current user has access to a specific warehouse.
    
    Args:
        warehouse_id: The warehouse ID to check
        
    Returns:
        bool: True if user has access to the warehouse
    """
    return session_utils.has_warehouse_access(warehouse_id)


def get_user_role_codes():
    """
    Get a list of role codes for the current user.
    
    Returns:
        list: List of role code strings
    """
    return session_utils.get_role_codes()


def get_user_role_names():
    """
    Get a list of role names for the current user.
    
    Returns:
        list: List of role name strings
    """
    return session_utils.get_role_names()


def is_admin():
    """
    Check if the current user is a system administrator.
    
    Returns:
        bool: True if user is an admin
    """
    return has_role('SYSTEM_ADMINISTRATOR', 'SYS_ADMIN')


def is_logistics_manager():
    """
    Check if the current user is a logistics manager.
    
    Returns:
        bool: True if user is a logistics manager
    """
    return has_role('LOGISTICS_MANAGER')


def is_logistics_officer():
    """
    Check if the current user is a logistics officer.
    
    Returns:
        bool: True if user is a logistics officer
    """
    return has_role('LOGISTICS_OFFICER')


def is_director_level():
    """
    Check if the current user is a director-level ODPEM executive.
    Only Director General, Deputy Director General, and Director PEOD.
    
    Returns:
        bool: True if user is director-level
    """
    return has_role(*EXECUTIVE_ROLES)


def is_executive():
    """
    Alias for is_director_level().
    Check if the current user is an ODPEM Executive (DG, DDG, or Director PEOD).
    These roles share executive-level permissions for eligibility approval.
    
    Returns:
        bool: True if user is an executive
    """
    return is_director_level()


def executive_required(f):
    """
    Decorator to restrict access to ODPEM Executive roles only.
    Executive roles: Director General, Deputy Director General, Director PEOD.
    
    Usage:
        @executive_required
        def my_route():
            # Only accessible to executives
            ...
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session_utils.is_authenticated():
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('login'))
        
        if not is_executive():
            flash('This page is only accessible to ODPEM Executives.', 'danger')
            abort(403)
        
        return f(*args, **kwargs)
    return decorated_function


def can_manage_users():
    """
    Check if the current user can manage users.
    
    Returns:
        bool: True if user can manage users
    """
    return has_role('SYSTEM_ADMINISTRATOR', 'SYS_ADMIN')


def can_view_reports():
    """
    Check if the current user can view reports.
    
    Returns:
        bool: True if user can view reports
    """
    return session_utils.is_authenticated()


def has_permission(resource, action):
    """
    Check if the current user has a specific permission based on their roles.
    
    Args:
        resource: The resource name (e.g., 'reliefrqst', 'inventory')
        action: The action name (e.g., 'approve_eligibility', 'view_all')
        
    Returns:
        bool: True if user has the permission
    """
    if not session_utils.is_authenticated():
        return False
    
    # Validate resource and action parameters
    if not isinstance(resource, str) or not resource.strip():
        return False
    if not isinstance(action, str) or not action.strip():
        return False
    
    # Get user's role IDs from current_user (validated roles)
    user_role_codes = session_utils.get_role_codes()
    if not user_role_codes:
        return False
    
    # Use SQLAlchemy ORM instead of raw SQL for database compatibility
    from app.db.models import Permission, RolePermission, Role
    
    # Query for permission through role_permission join using ORM
    permission_count = db.session.query(Permission).join(
        RolePermission, Permission.perm_id == RolePermission.perm_id
    ).join(
        Role, Role.id == RolePermission.role_id
    ).filter(
        Role.code.in_(user_role_codes),
        Permission.resource == resource.strip(),
        Permission.action == action.strip()
    ).count()
    
    return permission_count > 0


def permission_required(resource, action):
    """
    Decorator to restrict access to routes based on permissions.
    
    Usage:
        @permission_required('reliefrqst', 'approve_eligibility')
        def my_route():
            ...
    
    Args:
        resource: The resource name (e.g., 'reliefrqst')
        action: The action name (e.g., 'approve_eligibility')
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not session_utils.is_authenticated():
                flash('Please log in to access this page.', 'warning')
                return redirect(url_for('login'))
            
            if not has_permission(resource, action):
                flash('You do not have permission to perform this action.', 'danger')
                abort(403)
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator
