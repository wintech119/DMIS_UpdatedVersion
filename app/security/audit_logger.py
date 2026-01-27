"""
Security Audit Logger - NIST 800-53 Compliant Audit Logging

This module provides standardized security/audit logging for DMIS aligned with
NIST 800-53 audit controls (AU-2, AU-3, AU-8, AU-12) and GOJ cybersecurity requirements.

Key Features:
- Structured logging format for SIEM ingestion
- Consistent event categories and actions
- User attribution and target entity tracking
- Timestamp standardization (Jamaica timezone)
- Sensitive data protection (no secrets logged)

Event Categories:
- AUTHENTICATION: Login, logout, session events
- AUTHORIZATION: Access control, privilege checks
- USER_MANAGEMENT: Account creation, role changes
- DATA_ACCESS: Create, read, update, delete operations
- SYSTEM: Configuration changes, security events

Usage:
    from app.security.audit_logger import audit_log, AuditCategory, AuditAction
    
    # Log successful login
    audit_log(
        category=AuditCategory.AUTHENTICATION,
        action=AuditAction.LOGIN_SUCCESS,
        user_id=user.user_id,
        details={'ip_address': request.remote_addr}
    )
    
    # Log data modification
    audit_log(
        category=AuditCategory.DATA_ACCESS,
        action=AuditAction.CREATE,
        user_id=current_user.user_id,
        target_entity='donation',
        target_id=donation.donation_id,
        details={'donor_id': donor.donor_id}
    )

NIST 800-53 Controls Addressed:
- AU-2: Audit Events - Defines auditable events
- AU-3: Content of Audit Records - Specifies required fields
- AU-8: Time Stamps - Uses standardized Jamaica timezone
- AU-12: Audit Generation - Automated logging at key points
"""

import logging
from enum import Enum
from typing import Any, Optional, Union
from datetime import datetime
from functools import wraps

from app.security.log_sanitizer import sanitize_for_log, sanitize_dict_for_log


security_logger = logging.getLogger("dmis.security")
audit_logger = logging.getLogger("dmis.audit")


class AuditCategory(str, Enum):
    """Categories of auditable security events"""
    AUTHENTICATION = "AUTHENTICATION"
    AUTHORIZATION = "AUTHORIZATION"
    USER_MANAGEMENT = "USER_MGMT"
    DATA_ACCESS = "DATA_ACCESS"
    SYSTEM = "SYSTEM"
    SECURITY = "SECURITY"


class AuditAction(str, Enum):
    """Specific auditable actions within each category"""
    LOGIN_SUCCESS = "LOGIN_SUCCESS"
    LOGIN_FAILURE = "LOGIN_FAILURE"
    LOGIN_LOCKED = "LOGIN_LOCKED"
    LOGIN_INACTIVE = "LOGIN_INACTIVE"
    LOGOUT = "LOGOUT"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    
    ACCESS_GRANTED = "ACCESS_GRANTED"
    ACCESS_DENIED = "ACCESS_DENIED"
    PRIVILEGE_CHECK = "PRIVILEGE_CHECK"
    ROLE_REQUIRED = "ROLE_REQUIRED"
    
    USER_CREATE = "USER_CREATE"
    USER_UPDATE = "USER_UPDATE"
    USER_DELETE = "USER_DELETE"
    USER_LOCK = "USER_LOCK"
    USER_UNLOCK = "USER_UNLOCK"
    ROLE_ASSIGN = "ROLE_ASSIGN"
    ROLE_REVOKE = "ROLE_REVOKE"
    PASSWORD_CHANGE = "PASSWORD_CHANGE"
    PASSWORD_RESET = "PASSWORD_RESET"
    
    CREATE = "CREATE"
    READ = "READ"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    EXPORT = "EXPORT"
    IMPORT = "IMPORT"
    
    DISPATCH = "DISPATCH"
    CANCEL = "CANCEL"
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    VERIFY = "VERIFY"
    SUBMIT = "SUBMIT"
    
    CONFIG_CHANGE = "CONFIG_CHANGE"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    CSRF_VIOLATION = "CSRF_VIOLATION"
    INVALID_INPUT = "INVALID_INPUT"
    SECURITY_ALERT = "SECURITY_ALERT"


class AuditOutcome(str, Enum):
    """Outcome of the audited action"""
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    DENIED = "DENIED"
    ERROR = "ERROR"


def _get_jamaica_timestamp() -> str:
    """Get current timestamp in Jamaica timezone (ISO 8601 format)"""
    try:
        from app.utils.timezone import now as jamaica_now
        return jamaica_now().isoformat()
    except ImportError:
        return datetime.utcnow().isoformat() + "Z"


def _get_client_ip() -> Optional[str]:
    """Get client IP address from request context"""
    try:
        from flask import request, has_request_context
        if has_request_context():
            x_forwarded_for = request.headers.get('X-Forwarded-For')
            if x_forwarded_for:
                return x_forwarded_for.split(',')[0].strip()
            return request.remote_addr
    except Exception:
        pass
    return None


def _get_request_context() -> dict:
    """Extract relevant request context for audit logging"""
    try:
        from flask import request, has_request_context
        if has_request_context():
            return {
                'ip': _get_client_ip(),
                'method': request.method,
                'path': sanitize_for_log(request.path, max_length=200),
                'user_agent': sanitize_for_log(
                    request.headers.get('User-Agent', 'unknown')[:100],
                    max_length=100
                )
            }
    except Exception:
        pass
    return {}


def audit_log(
    category: AuditCategory,
    action: AuditAction,
    user_id: Optional[Union[int, str]] = None,
    target_entity: Optional[str] = None,
    target_id: Optional[Union[int, str]] = None,
    outcome: AuditOutcome = AuditOutcome.SUCCESS,
    details: Optional[dict] = None,
    level: int = logging.INFO
) -> None:
    """
    Log a security/audit event with structured format.
    
    Args:
        category: Event category (authentication, authorization, etc.)
        action: Specific action being logged
        user_id: ID of the user performing the action (None for anonymous)
        target_entity: Type of entity being acted upon (e.g., 'donation', 'user')
        target_id: ID of the target entity
        outcome: Result of the action (success, failure, denied, error)
        details: Additional context as dictionary (will be sanitized)
        level: Logging level (default INFO, use WARNING for failures/denials)
    
    Log Format (structured for SIEM parsing):
        timestamp=<ISO8601> category=<CATEGORY> action=<ACTION> 
        user_id=<ID> target=<entity:id> outcome=<OUTCOME> 
        ip=<IP> details=<sanitized_dict>
    """
    timestamp = _get_jamaica_timestamp()
    request_ctx = _get_request_context()
    
    target_str = None
    if target_entity:
        if target_id is not None:
            target_str = f"{sanitize_for_log(target_entity)}:{sanitize_for_log(target_id)}"
        else:
            target_str = sanitize_for_log(target_entity)
    
    details_str = sanitize_dict_for_log(details) if details else None
    
    log_parts = [
        f"timestamp={timestamp}",
        f"category={category.value}",
        f"action={action.value}",
        f"user_id={sanitize_for_log(user_id) if user_id else 'anonymous'}",
    ]
    
    if target_str:
        log_parts.append(f"target={target_str}")
    
    log_parts.append(f"outcome={outcome.value}")
    
    if request_ctx.get('ip'):
        log_parts.append(f"ip={request_ctx['ip']}")
    
    if details_str:
        log_parts.append(f"details={details_str}")
    
    log_message = " ".join(log_parts)
    
    if outcome in (AuditOutcome.FAILURE, AuditOutcome.DENIED, AuditOutcome.ERROR):
        level = max(level, logging.WARNING)
    
    audit_logger.log(level, log_message)


def log_authentication_event(
    action: AuditAction,
    user_id: Optional[int] = None,
    email: Optional[str] = None,
    outcome: AuditOutcome = AuditOutcome.SUCCESS,
    reason: Optional[str] = None
) -> None:
    """
    Convenience function for logging authentication events.
    
    Args:
        action: Authentication action (LOGIN_SUCCESS, LOGIN_FAILURE, etc.)
        user_id: User ID if known
        email: Email address (will be partially masked in logs)
        outcome: Success or failure
        reason: Reason for failure (if applicable)
    """
    details = {}
    
    if email:
        if '@' in email:
            parts = email.split('@')
            masked_email = parts[0][:2] + '***@' + parts[1]
        else:
            masked_email = email[:2] + '***'
        details['email'] = masked_email
    
    if reason:
        details['reason'] = sanitize_for_log(reason, max_length=100)
    
    audit_log(
        category=AuditCategory.AUTHENTICATION,
        action=action,
        user_id=user_id,
        outcome=outcome,
        details=details if details else None,
        level=logging.WARNING if outcome != AuditOutcome.SUCCESS else logging.INFO
    )


def log_authorization_event(
    user_id: int,
    resource: str,
    action: str = "access",
    granted: bool = True,
    required_role: Optional[str] = None
) -> None:
    """
    Convenience function for logging authorization events.
    
    Args:
        user_id: ID of user requesting access
        resource: Resource being accessed
        action: Action attempted on the resource
        granted: Whether access was granted
        required_role: Role that was required (if applicable)
    """
    details = {'resource_action': action}
    if required_role:
        details['required_role'] = required_role
    
    audit_log(
        category=AuditCategory.AUTHORIZATION,
        action=AuditAction.ACCESS_GRANTED if granted else AuditAction.ACCESS_DENIED,
        user_id=user_id,
        target_entity=resource,
        outcome=AuditOutcome.SUCCESS if granted else AuditOutcome.DENIED,
        details=details
    )


def log_data_event(
    action: AuditAction,
    user_id: int,
    entity_type: str,
    entity_id: Optional[Union[int, str]] = None,
    details: Optional[dict] = None,
    outcome: AuditOutcome = AuditOutcome.SUCCESS
) -> None:
    """
    Convenience function for logging data access/modification events.
    
    Args:
        action: Data action (CREATE, UPDATE, DELETE, etc.)
        user_id: ID of user performing the action
        entity_type: Type of entity (donation, transfer, relief_request, etc.)
        entity_id: ID of the entity
        details: Additional context
        outcome: Result of the operation
    """
    audit_log(
        category=AuditCategory.DATA_ACCESS,
        action=action,
        user_id=user_id,
        target_entity=entity_type,
        target_id=entity_id,
        outcome=outcome,
        details=details
    )


def log_user_management_event(
    action: AuditAction,
    actor_id: int,
    target_user_id: int,
    details: Optional[dict] = None,
    outcome: AuditOutcome = AuditOutcome.SUCCESS
) -> None:
    """
    Convenience function for logging user management events.
    
    Args:
        action: User management action (USER_CREATE, ROLE_ASSIGN, etc.)
        actor_id: ID of user performing the action
        target_user_id: ID of user being modified
        details: Additional context (role changes, etc.)
        outcome: Result of the operation
    """
    audit_log(
        category=AuditCategory.USER_MANAGEMENT,
        action=action,
        user_id=actor_id,
        target_entity='user',
        target_id=target_user_id,
        outcome=outcome,
        details=details
    )


def log_security_event(
    action: AuditAction,
    user_id: Optional[int] = None,
    details: Optional[dict] = None,
    level: int = logging.WARNING
) -> None:
    """
    Convenience function for logging security-related events.
    
    Args:
        action: Security action (RATE_LIMIT_EXCEEDED, CSRF_VIOLATION, etc.)
        user_id: ID of user if known
        details: Additional context
        level: Logging level (default WARNING)
    """
    audit_log(
        category=AuditCategory.SECURITY,
        action=action,
        user_id=user_id,
        outcome=AuditOutcome.FAILURE,
        details=details,
        level=level
    )


def audit_action(
    category: AuditCategory,
    action: AuditAction,
    target_entity: Optional[str] = None,
    get_target_id: Optional[callable] = None
):
    """
    Decorator to automatically audit function calls.
    
    Args:
        category: Event category
        action: Action being logged
        target_entity: Type of entity being acted upon
        get_target_id: Callable to extract target ID from function result
    
    Usage:
        @audit_action(AuditCategory.DATA_ACCESS, AuditAction.CREATE, 'donation')
        def create_donation(...):
            ...
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            from flask_login import current_user
            
            user_id = None
            if hasattr(current_user, 'user_id') and current_user.is_authenticated:
                user_id = current_user.user_id
            
            try:
                result = f(*args, **kwargs)
                
                target_id = None
                if get_target_id and result:
                    try:
                        target_id = get_target_id(result)
                    except Exception:
                        pass
                
                audit_log(
                    category=category,
                    action=action,
                    user_id=user_id,
                    target_entity=target_entity,
                    target_id=target_id,
                    outcome=AuditOutcome.SUCCESS
                )
                
                return result
                
            except Exception as e:
                audit_log(
                    category=category,
                    action=action,
                    user_id=user_id,
                    target_entity=target_entity,
                    outcome=AuditOutcome.ERROR,
                    details={'error': str(type(e).__name__)}
                )
                raise
        
        return wrapper
    return decorator


def init_audit_logging(app):
    """
    Initialize audit logging for the Flask application.
    
    Sets up:
    - Dedicated audit log handler
    - Structured log format for SIEM
    - Log rotation (if file-based)
    
    Args:
        app: Flask application instance
    """
    log_format = logging.Formatter(
        '%(asctime)s [%(name)s] %(levelname)s: %(message)s',
        datefmt='%Y-%m-%dT%H:%M:%S%z'
    )
    
    if not audit_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(log_format)
        audit_logger.addHandler(handler)
        audit_logger.setLevel(logging.INFO)
    
    if not security_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(log_format)
        security_logger.addHandler(handler)
        security_logger.setLevel(logging.INFO)
    
    app.logger.info("Audit logging initialized")
