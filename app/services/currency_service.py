"""
Currency Conversion Service for DRIMS

NOTE FOR DEVELOPERS:
====================
External currency API integration is currently disabled.
The system retains currency conversion capability using
cached/manual values in the currency_rate table.

To add a new provider:
1. Implement fetch_rate_from_provider() function
2. Configure the provider's base URL & API key in config.py
3. Update get_or_update_rate_to_jmd() to call your new function
4. Insert a new value for 'source' in currency_rate as needed

Current Behavior:
- get_cached_rate() returns cached rates from currency_rate table
- store_rate() allows manual/programmatic rate insertion
- get_or_update_rate_to_jmd() returns cached rates only (no external fetch)
- convert_to_jmd() works with cached rates only
- refresh_all_rates() is disabled (no external API configured)
- set_usd_jmd_rate() allows manual USD/JMD rate setting

Key Features (still operational):
- Reads cached rates from the currency_rate database table
- Provides JMD conversion for display purposes (read-only)
- Graceful fallback when rates are unavailable

Usage Example:
    from app.services.currency_service import CurrencyService
    
    # Get cached rate (returns None if not cached)
    rate = CurrencyService.get_or_update_rate_to_jmd('USD', date.today())
    
    # Convert amount using cached rates
    jmd_amount = CurrencyService.convert_to_jmd(100.00, 'USD', date.today())
    
    # Manually set a rate
    CurrencyService.store_rate('EUR', date.today(), Decimal('170.50'), 'MANUAL')
"""

import logging
from decimal import Decimal, InvalidOperation
from datetime import date, datetime
from typing import Optional, List, Tuple
from flask import current_app

from app.db import db
from sqlalchemy import text

logger = logging.getLogger(__name__)


class CurrencyRate(db.Model):
    """Model for cached currency exchange rates."""
    __tablename__ = 'currency_rate'
    
    currency_code = db.Column(db.String(3), primary_key=True)
    rate_date = db.Column(db.Date, primary_key=True)
    rate_to_jmd = db.Column(db.Numeric(18, 8), nullable=False)
    source = db.Column(db.String(50), nullable=False, default='UNCONFIGURED')
    create_dtime = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<CurrencyRate {self.currency_code}={self.rate_to_jmd} JMD on {self.rate_date}>'


class CurrencyServiceError(Exception):
    """Base exception for currency service errors."""
    pass


class NoProviderConfiguredError(CurrencyServiceError):
    """Raised when attempting to fetch rates but no external provider is configured."""
    pass


class CurrencyService:
    """
    Centralized service for currency conversion.
    
    NOTE: External API integration is currently disabled.
    The service operates using cached/manual rates only.
    
    All methods are designed to fail gracefully - if a rate cannot be retrieved,
    methods return None rather than raising exceptions, allowing the app to
    continue functioning.
    """
    
    # Default source for manually inserted rates
    DEFAULT_SOURCE = 'MANUAL'
    HTTP_TIMEOUT = 5  # seconds (retained for future provider integration)
    
    @staticmethod
    def get_cached_rate(currency_code: str, rate_date: date) -> Optional[Decimal]:
        """
        Get a cached exchange rate from the database.
        
        Args:
            currency_code: ISO 4217 currency code (e.g., 'USD', 'EUR')
            rate_date: The date for which to retrieve the rate
            
        Returns:
            The exchange rate to JMD, or None if not cached
        """
        if not currency_code:
            return None
            
        currency_code = currency_code.upper().strip()
        
        if currency_code == 'JMD':
            return Decimal('1')
        
        try:
            rate = CurrencyRate.query.filter_by(
                currency_code=currency_code,
                rate_date=rate_date
            ).first()
            
            if rate:
                return Decimal(str(rate.rate_to_jmd))
            
            rate = CurrencyRate.query.filter(
                CurrencyRate.currency_code == currency_code,
                CurrencyRate.rate_date <= rate_date
            ).order_by(CurrencyRate.rate_date.desc()).first()
            
            if rate:
                logger.debug(f"Using fallback rate from {rate.rate_date} for {currency_code}")
                return Decimal(str(rate.rate_to_jmd))
                
            return None
            
        except Exception as e:
            logger.error(f"Error getting cached rate for {currency_code}: {e}")
            return None
    
    @staticmethod
    def store_rate(currency_code: str, rate_date: date, rate_to_jmd: Decimal, 
                   source: str = 'MANUAL') -> bool:
        """
        Store or update an exchange rate in the database.
        
        Args:
            currency_code: ISO 4217 currency code
            rate_date: The date the rate applies to
            rate_to_jmd: Exchange rate (how many JMD for 1 unit of currency)
            source: Rate source identifier (default: 'MANUAL')
            
        Returns:
            True if successful, False otherwise
        """
        if not currency_code or currency_code.upper() == 'JMD':
            return False
            
        currency_code = currency_code.upper().strip()
        
        try:
            existing = CurrencyRate.query.filter_by(
                currency_code=currency_code,
                rate_date=rate_date
            ).first()
            
            if existing:
                existing.rate_to_jmd = rate_to_jmd
                existing.source = source
                existing.create_dtime = datetime.utcnow()
            else:
                new_rate = CurrencyRate(
                    currency_code=currency_code,
                    rate_date=rate_date,
                    rate_to_jmd=rate_to_jmd,
                    source=source,
                    create_dtime=datetime.utcnow()
                )
                db.session.add(new_rate)
            
            db.session.commit()
            logger.info(f"Stored rate: 1 {currency_code} = {rate_to_jmd} JMD for {rate_date}")
            return True
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error storing rate for {currency_code}: {e}")
            return False
    
    @staticmethod
    def fetch_rate_from_provider(currency_code: str, rate_date: Optional[date] = None) -> Optional[Decimal]:
        """
        Fetch an exchange rate from an external API provider.
        
        NOTE: No external currency API is currently configured.
        This method is a placeholder for future provider integration.
        
        To implement a new provider:
        1. Add provider configuration (base URL, API key) to config.py
        2. Implement the API call logic in this method
        3. Return the rate as a Decimal, or None if fetch failed
        
        Args:
            currency_code: ISO 4217 currency code (e.g., 'USD', 'EUR')
            rate_date: Optional date for historical rate; None for latest
            
        Returns:
            Exchange rate to JMD, or None if fetch failed
            
        Raises:
            NoProviderConfiguredError: Always raised as no provider is configured
        """
        raise NoProviderConfiguredError(
            "No external currency API is configured. "
            "Please add an exchange-rate provider to enable automatic rates."
        )
    
    @staticmethod
    def _get_usd_jmd_rate() -> Decimal:
        """
        Get the USD to JMD exchange rate from cache.
        
        Returns the most recent cached USD rate, or a default approximation
        if no rate is cached.
        
        Returns:
            Decimal rate for 1 USD to JMD
        """
        try:
            cached = CurrencyRate.query.filter_by(
                currency_code='USD'
            ).order_by(CurrencyRate.rate_date.desc()).first()
            
            if cached:
                return Decimal(str(cached.rate_to_jmd))
        except Exception:
            pass
        
        # Default approximation (can be updated via set_usd_jmd_rate)
        return Decimal('157.50')
    
    @staticmethod
    def get_or_update_rate_to_jmd(currency_code: str, rate_date: date) -> Optional[Decimal]:
        """
        Get exchange rate to JMD from cache.
        
        NOTE: External API fetching is disabled. This method returns
        cached rates only. Use store_rate() to manually add rates.
        
        Args:
            currency_code: ISO 4217 currency code
            rate_date: The date for which to get the rate
            
        Returns:
            Exchange rate to JMD, or None if not cached
        """
        if not currency_code:
            return None
            
        currency_code = currency_code.upper().strip()
        
        if currency_code == 'JMD':
            return Decimal('1')
        
        # Return cached rate only (no external fetch)
        cached_rate = CurrencyService.get_cached_rate(currency_code, rate_date)
        if cached_rate is not None:
            return cached_rate
        
        # Log that no rate is available (external fetch disabled)
        logger.debug(f"No cached rate available for {currency_code} on {rate_date}. "
                     "External API fetch is disabled.")
        return None
    
    @staticmethod
    def convert_to_jmd(amount: Decimal, currency_code: str, 
                       rate_date: Optional[date] = None) -> Optional[Decimal]:
        """
        Convert an amount to JMD.
        
        Args:
            amount: The amount to convert
            currency_code: The source currency code
            rate_date: Optional date for historical rate; defaults to today
            
        Returns:
            Converted amount in JMD, or None if conversion failed
        """
        if amount is None:
            return None
            
        if not currency_code:
            return None
            
        currency_code = currency_code.upper().strip()
        
        if currency_code == 'JMD':
            return Decimal(str(amount))
        
        if rate_date is None:
            rate_date = date.today()
        
        rate = CurrencyService.get_or_update_rate_to_jmd(currency_code, rate_date)
        
        if rate is None:
            return None
        
        try:
            return Decimal(str(amount)) * rate
        except (InvalidOperation, TypeError):
            return None
    
    @staticmethod
    def get_donation_currencies() -> List[str]:
        """
        Get the list of distinct currency codes used in donations.
        
        Returns:
            List of unique currency codes from donation records
        """
        try:
            result = db.session.execute(
                text("SELECT DISTINCT currency_code FROM donation_item WHERE currency_code IS NOT NULL ORDER BY currency_code")
            )
            return [row[0] for row in result.fetchall() if row[0]]
        except Exception as e:
            logger.error(f"Error getting donation currencies: {e}")
            return []
    
    @staticmethod
    def refresh_all_rates(target_date: Optional[date] = None) -> Tuple[int, int]:
        """
        Refresh exchange rates for all currencies used in donations.
        
        NOTE: External API fetching is disabled. This method currently
        returns (0, 0) as no rates can be fetched automatically.
        
        To enable automatic rate refresh:
        1. Implement fetch_rate_from_provider()
        2. Configure the provider in config.py
        3. Update this method to use the new provider
        
        Args:
            target_date: Date for which to fetch rates; defaults to today
            
        Returns:
            Tuple of (successful_count, failed_count) - always (0, 0) when disabled
        """
        logger.warning("refresh_all_rates called but no external API is configured. "
                      "Rates must be inserted manually using store_rate() or set_usd_jmd_rate().")
        return (0, 0)
    
    @staticmethod
    def set_usd_jmd_rate(rate: Decimal, rate_date: Optional[date] = None) -> bool:
        """
        Manually set the USD to JMD exchange rate.
        
        This allows administrators to set/update the USD/JMD rate manually.
        Other currency rates can be set using store_rate().
        
        Args:
            rate: The USD to JMD exchange rate
            rate_date: Date for the rate; defaults to today
            
        Returns:
            True if successful, False otherwise
        """
        if rate_date is None:
            rate_date = date.today()
        
        return CurrencyService.store_rate('USD', rate_date, rate, 'MANUAL')
    
    @staticmethod
    def list_cached_rates(limit: int = 50) -> List[CurrencyRate]:
        """
        List cached exchange rates.
        
        Args:
            limit: Maximum number of rates to return (default 50)
            
        Returns:
            List of CurrencyRate objects, ordered by date descending
        """
        try:
            return CurrencyRate.query.order_by(
                CurrencyRate.rate_date.desc(),
                CurrencyRate.currency_code
            ).limit(limit).all()
        except Exception as e:
            logger.error(f"Error listing cached rates: {e}")
            return []
