"""
Fulfillment Lock Service
Manages exclusive access to relief requests during packaging/fulfillment
Integrated with inventory reservation service to release reservations on lock expiry/release
"""
from datetime import timedelta
from typing import Optional, Tuple
from sqlalchemy.exc import IntegrityError

from app.db import db
from app.db.models import ReliefRequestFulfillmentLock, User, ReliefRqst
from app.utils.timezone import now


DEFAULT_LOCK_EXPIRY_HOURS = 24


def acquire_lock(reliefrqst_id: int, user_id: int, user_email: str, expiry_hours: int = DEFAULT_LOCK_EXPIRY_HOURS) -> Tuple[bool, str, Optional[ReliefRequestFulfillmentLock]]:
    """
    Acquire fulfillment lock for a relief request.
    
    Args:
        reliefrqst_id: Relief request ID to lock
        user_id: User ID attempting to acquire lock
        user_email: User email for audit trail
        expiry_hours: Hours until lock expires (default 24)
        
    Returns:
        Tuple of (success: bool, message: str, lock: ReliefRequestFulfillmentLock or None)
    """
    existing_lock = ReliefRequestFulfillmentLock.query.filter_by(reliefrqst_id=reliefrqst_id).first()
    
    if existing_lock:
        if existing_lock.fulfiller_user_id == user_id:
            return True, "You already have the lock", existing_lock
        
        if existing_lock.expires_at and existing_lock.expires_at < now():
            db.session.delete(existing_lock)
            db.session.commit()
        else:
            user = User.query.get(existing_lock.fulfiller_user_id)
            user_name = f"{user.first_name} {user.last_name}" if user and user.first_name else existing_lock.fulfiller_email
            return False, f"Currently being prepared by {user_name}", existing_lock
    
    try:
        expires_at = now() + timedelta(hours=expiry_hours) if expiry_hours > 0 else None
        
        lock = ReliefRequestFulfillmentLock(
            reliefrqst_id=reliefrqst_id,
            fulfiller_user_id=user_id,
            fulfiller_email=user_email,
            acquired_at=now(),
            expires_at=expires_at
        )
        
        db.session.add(lock)
        db.session.commit()
        
        return True, "Lock acquired successfully", lock
        
    except IntegrityError:
        db.session.rollback()
        existing_lock = ReliefRequestFulfillmentLock.query.filter_by(reliefrqst_id=reliefrqst_id).first()
        if existing_lock and existing_lock.fulfiller_user_id == user_id:
            return True, "You already have the lock", existing_lock
        user = User.query.get(existing_lock.fulfiller_user_id) if existing_lock else None
        user_name = f"{user.first_name} {user.last_name}" if user and user.first_name else (existing_lock.fulfiller_email if existing_lock else "Another user")
        return False, f"Currently being prepared by {user_name}", existing_lock


def release_lock(reliefrqst_id: int, user_id: int, force: bool = False, release_reservations: bool = False) -> Tuple[bool, str]:
    """
    Release fulfillment lock for a relief request.
    
    Args:
        reliefrqst_id: Relief request ID to unlock
        user_id: User ID attempting to release lock
        force: If True, allows releasing another user's lock (for privileged workflows)
        release_reservations: If True, also releases inventory reservations (for Cancel/Abandon scenarios)
        
    Returns:
        Tuple of (success: bool, message: str)
    """
    lock = ReliefRequestFulfillmentLock.query.filter_by(reliefrqst_id=reliefrqst_id).first()
    
    if not lock:
        return True, "No lock exists"
    
    if lock.fulfiller_user_id != user_id and not force:
        return False, "You cannot release another user's lock"
    
    # Release inventory reservations if requested (Cancel/Abandon scenarios)
    if release_reservations:
        from app.services import inventory_reservation_service as reservation_service
        success, error_msg = reservation_service.release_all_reservations(reliefrqst_id)
        if not success:
            # Log error but continue with lock release
            import logging
            from app.security.log_sanitizer import sanitize_for_log
            logger = logging.getLogger(__name__)
            logger.warning("Failed to release reservations for request %s: %s", sanitize_for_log(reliefrqst_id), sanitize_for_log(error_msg))
    
    db.session.delete(lock)
    db.session.commit()
    
    return True, "Lock released successfully"


def check_lock(reliefrqst_id: int, user_id: int) -> Tuple[bool, Optional[str], Optional[ReliefRequestFulfillmentLock]]:
    """
    Check if user can edit a relief request (has lock or no lock exists).
    Automatically releases expired locks and their inventory reservations.
    
    Args:
        reliefrqst_id: Relief request ID to check
        user_id: User ID to check
        
    Returns:
        Tuple of (can_edit: bool, blocking_user_name: str or None, lock: ReliefRequestFulfillmentLock or None)
    """
    lock = ReliefRequestFulfillmentLock.query.filter_by(reliefrqst_id=reliefrqst_id).first()
    
    if not lock:
        return True, None, None
    
    if lock.expires_at and lock.expires_at < now():
        # Lock expired - release reservations and delete lock
        from app.services import inventory_reservation_service as reservation_service
        reservation_service.release_all_reservations(reliefrqst_id)
        db.session.delete(lock)
        db.session.commit()
        return True, None, None
    
    if lock.fulfiller_user_id == user_id:
        return True, None, lock
    
    user = User.query.get(lock.fulfiller_user_id)
    user_name = f"{user.first_name} {user.last_name}" if user and user.first_name else lock.fulfiller_email
    
    return False, user_name, lock


def cleanup_expired_locks() -> int:
    """
    Remove all expired locks and release their inventory reservations.
    Should be called periodically by a background job/cron.
    
    Returns:
        Number of locks removed
    """
    from app.services import inventory_reservation_service as reservation_service
    
    expired_locks = ReliefRequestFulfillmentLock.query.filter(
        ReliefRequestFulfillmentLock.expires_at < now()
    ).all()
    
    count = len(expired_locks)
    
    for lock in expired_locks:
        # Release inventory reservations for this request
        reservation_service.release_all_reservations(lock.reliefrqst_id)
        db.session.delete(lock)
    
    db.session.commit()
    
    return count
