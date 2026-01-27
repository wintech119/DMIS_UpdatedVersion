"""
Security decorators for DRIMS route protection.

Provides feature-based access control using FeatureRegistry.
"""

from functools import wraps
from flask import abort, flash, redirect, url_for, request
from flask_login import current_user
from app.core.feature_registry import FeatureRegistry
from app.core import session_utils


def feature_required(feature_key):
    """
    Decorator to restrict route access based on feature permissions.
    
    Usage:
        @feature_required('view_inventory')
        def inventory_list():
            ...
    
    Args:
        feature_key: The feature key from FeatureRegistry.FEATURES
        
    Returns:
        Decorator function that checks user has access to the feature
        
    Raises:
        403 Forbidden if user doesn't have access to the feature
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not session_utils.is_authenticated():
                flash('Please log in to access this page.', 'warning')
                return redirect(url_for('login', next=request.url))
            
            if not FeatureRegistry.has_access(current_user, feature_key):
                feature = FeatureRegistry.FEATURES.get(feature_key, {})
                feature_name = feature.get('name', 'this feature')
                flash(f'You do not have permission to access {feature_name}.', 'danger')
                abort(403)
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def any_feature_required(*feature_keys):
    """
    Decorator to allow access if user has ANY of the specified features.
    
    Usage:
        @any_feature_required('view_inventory', 'manage_inventory')
        def inventory_page():
            ...
    
    Args:
        *feature_keys: Variable number of feature keys
        
    Returns:
        Decorator function that checks user has at least one feature
        
    Raises:
        403 Forbidden if user doesn't have any of the features
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not session_utils.is_authenticated():
                flash('Please log in to access this page.', 'warning')
                return redirect(url_for('login', next=request.url))
            
            has_access = any(
                FeatureRegistry.has_access(current_user, key) 
                for key in feature_keys
            )
            
            if not has_access:
                flash('You do not have permission to access this page.', 'danger')
                abort(403)
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def all_features_required(*feature_keys):
    """
    Decorator to require ALL specified features for access.
    
    Usage:
        @all_features_required('view_reports', 'export_data')
        def export_report():
            ...
    
    Args:
        *feature_keys: Variable number of feature keys
        
    Returns:
        Decorator function that checks user has all features
        
    Raises:
        403 Forbidden if user doesn't have all features
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not session_utils.is_authenticated():
                flash('Please log in to access this page.', 'warning')
                return redirect(url_for('login', next=request.url))
            
            has_all = all(
                FeatureRegistry.has_access(current_user, key) 
                for key in feature_keys
            )
            
            if not has_all:
                flash('You do not have permission to access this page.', 'danger')
                abort(403)
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator
