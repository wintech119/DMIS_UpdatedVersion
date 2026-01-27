"""Timezone utility module for DRIMS.

All datetime operations in DRIMS use Jamaica Standard Time (UTC-05:00).
This module provides helper functions for consistent timezone handling.

IMPORTANT: The database stores timestamps as naive datetimes that should be
treated as UTC. These utilities help convert between UTC storage and Jamaica display time.
"""

from datetime import datetime, timezone, timedelta
from typing import Optional

# Jamaica timezone - UTC-05:00 (no daylight saving time)
JAMAICA_TZ = timezone(timedelta(hours=-5))
UTC_TZ = timezone.utc


def now() -> datetime:
    """Get current datetime in Jamaica timezone (naive for database storage).
    
    The returned datetime is naive (no tzinfo) but represents Jamaica time.
    This is converted from UTC and matches how SQLAlchemy stores timestamps.
    
    Returns:
        datetime: Current time in Jamaica timezone as naive datetime
    """
    utc_now = datetime.now(UTC_TZ)
    jamaica_aware = utc_now.astimezone(JAMAICA_TZ)
    # Return naive datetime for database compatibility
    return jamaica_aware.replace(tzinfo=None)


def today():
    """Get current date in Jamaica timezone.
    
    Returns:
        date: Current date in Jamaica timezone
        
    Note: This should be used instead of date.today() to ensure consistency
    with PostgreSQL CURRENT_DATE when the server is in a different timezone.
    """
    from datetime import date
    return now().date()


def get_date_only(dt: Optional[datetime] = None) -> datetime:
    """Get start of day at midnight in Jamaica time.
    
    Args:
        dt: Optional datetime (defaults to current time)
        
    Returns:
        datetime: Naive datetime at midnight in Jamaica timezone
    """
    if dt is None:
        dt = now()
    else:
        dt = utc_to_jamaica(dt)
    
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def utc_to_jamaica(dt: Optional[datetime]) -> Optional[datetime]:
    """Convert UTC naive datetime to Jamaica naive datetime.
    
    Args:
        dt: Naive datetime in UTC (or aware datetime), or date object
        
    Returns:
        datetime: Naive datetime in Jamaica timezone, or None
    """
    if dt is None:
        return None
    
    # Handle date objects - just return them as-is (dates don't have timezone)
    from datetime import date
    if isinstance(dt, date) and not isinstance(dt, datetime):
        return dt
    
    # Treat naive datetime as UTC
    if dt.tzinfo is None:
        utc_aware = dt.replace(tzinfo=UTC_TZ)
    else:
        utc_aware = dt.astimezone(UTC_TZ)
    
    # Convert to Jamaica time
    jamaica_aware = utc_aware.astimezone(JAMAICA_TZ)
    
    # Return naive for database compatibility
    return jamaica_aware.replace(tzinfo=None)


def to_jamaica_time(dt: Optional[datetime]) -> Optional[datetime]:
    """Convert any datetime to Jamaica timezone.
    
    For naive datetimes, assumes they are UTC and converts to Jamaica time.
    For aware datetimes, converts to Jamaica timezone.
    
    Args:
        dt: Datetime object (aware or naive, assumed UTC if naive)
        
    Returns:
        datetime: Naive datetime in Jamaica timezone, or None
    """
    return utc_to_jamaica(dt)


def make_aware(dt: datetime) -> datetime:
    """Make a naive datetime timezone-aware in Jamaica time.
    
    DEPRECATED: Use utc_to_jamaica() instead which properly converts from UTC.
    
    Args:
        dt: Naive datetime (assumed to be UTC)
        
    Returns:
        datetime: Timezone-aware datetime in Jamaica time
    """
    if dt.tzinfo is None:
        # Assume naive datetime is UTC
        utc_aware = dt.replace(tzinfo=UTC_TZ)
        return utc_aware.astimezone(JAMAICA_TZ)
    return dt.astimezone(JAMAICA_TZ)


def format_datetime(dt: Optional[datetime], format_str: str = '%Y-%m-%d %H:%M:%S') -> str:
    """Format datetime in Jamaica timezone.
    
    Assumes naive datetimes are in UTC and converts them to Jamaica time for display.
    Handles both datetime and date objects.
    
    Args:
        dt: Datetime or date object to format (naive UTC or aware)
        format_str: strftime format string
        
    Returns:
        str: Formatted datetime string in Jamaica time, or empty string if dt is None
    """
    if dt is None:
        return ''
    
    # Handle date objects - just format them directly
    from datetime import date
    if isinstance(dt, date) and not isinstance(dt, datetime):
        return dt.strftime(format_str)
    
    jamaica_dt = to_jamaica_time(dt)
    return jamaica_dt.strftime(format_str)


def datetime_to_jamaica(dt: Optional[datetime]) -> Optional[datetime]:
    """Convert datetime to Jamaica timezone (for template contexts).
    
    Args:
        dt: Datetime object (naive UTC or aware)
        
    Returns:
        datetime: Naive datetime in Jamaica timezone, or None
    """
    if dt is None:
        return None
    return to_jamaica_time(dt)
