"""
Audit field helpers for DRIMS
All aidmgmt-3.sql tables require audit fields on insert/update
"""
from app.utils.timezone import now as jamaica_now

def add_audit_fields(obj, user, is_new=True):
    """
    Add or update audit fields on a model object
    
    Args:
        obj: SQLAlchemy model instance
        user: User object (must have user_name field populated)
        is_new: True if creating new record, False if updating
    
    Raises:
        ValueError: If user does not have a valid user_name
        
    Note:
        Does NOT manually increment version_nbr on updates when the model
        has __mapper_args__ = {'version_id_col': version_nbr} configured,
        as SQLAlchemy handles version increment automatically.
    """
    now = jamaica_now()
    
    # Require user_name field - no fallback to email
    if not hasattr(user, 'user_name') or not user.user_name or not user.user_name.strip():
        raise ValueError(f'User object must have a non-empty user_name field for audit tracking. Got: {user}')
    
    audit_id = user.user_name.upper().strip()
    
    if is_new:
        if hasattr(obj, 'create_by_id'):
            obj.create_by_id = audit_id
        if hasattr(obj, 'create_dtime'):
            obj.create_dtime = now
        if hasattr(obj, 'version_nbr'):
            obj.version_nbr = 1
    
    if hasattr(obj, 'update_by_id'):
        obj.update_by_id = audit_id
    if hasattr(obj, 'update_dtime'):
        obj.update_dtime = now
    
    # Do NOT manually increment version_nbr on updates
    # SQLAlchemy's version_id_col handles this automatically for models
    # with __mapper_args__ = {'version_id_col': version_nbr}
    
    return obj

def add_verify_fields(obj, user):
    """
    Add verification audit fields
    
    Args:
        obj: SQLAlchemy model instance
        user: User object (must have user_name field populated)
    
    Raises:
        ValueError: If user does not have a valid user_name
    """
    now = jamaica_now()
    
    # Require user_name field - no fallback to email
    if not hasattr(user, 'user_name') or not user.user_name or not user.user_name.strip():
        raise ValueError(f'User object must have a non-empty user_name field for audit tracking. Got: {user}')
    
    audit_id = user.user_name.upper().strip()
    
    if hasattr(obj, 'verify_by_id'):
        obj.verify_by_id = audit_id
    if hasattr(obj, 'verify_dtime'):
        obj.verify_dtime = now
    
    return obj
