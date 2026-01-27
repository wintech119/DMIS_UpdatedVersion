-- Migration: Create currency_rate table for caching exchange rates
-- Date: 2025-11-26
-- Purpose: Add a new table to cache exchange rates for converting foreign currencies 
--          to JMD for display purposes. Rates can be inserted manually or via an
--          external API provider (if configured).
-- 
-- This is an ADDITIVE migration - no existing tables are modified or dropped.

BEGIN;

-- Create currency_rate table
CREATE TABLE IF NOT EXISTS currency_rate
(
    currency_code   VARCHAR(3) NOT NULL,
    rate_to_jmd     NUMERIC(18, 8) NOT NULL,
    source          VARCHAR(50) NOT NULL DEFAULT 'UNCONFIGURED',
    rate_date       DATE NOT NULL,
    create_dtime    TIMESTAMP(0) WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    
    -- Primary key on currency_code and rate_date (allows one rate per currency per date)
    CONSTRAINT pk_currency_rate PRIMARY KEY (currency_code, rate_date),
    
    -- Ensure currency_code is always uppercase
    CONSTRAINT c_currency_rate_code_upper CHECK (currency_code = UPPER(currency_code)),
    
    -- Ensure rate is positive
    CONSTRAINT c_currency_rate_positive CHECK (rate_to_jmd > 0)
);

-- Add index for faster lookups by currency code
CREATE INDEX IF NOT EXISTS idx_currency_rate_code ON currency_rate(currency_code);

-- Add index for rate date lookups (for finding most recent rate)
CREATE INDEX IF NOT EXISTS idx_currency_rate_date ON currency_rate(rate_date DESC);

-- Add comment for documentation
COMMENT ON TABLE currency_rate IS 'Cached exchange rates to JMD. Used for display-only currency conversion. Rates can be inserted manually or via API.';
COMMENT ON COLUMN currency_rate.currency_code IS 'ISO 4217 currency code (uppercase), e.g., USD, EUR, GBP';
COMMENT ON COLUMN currency_rate.rate_to_jmd IS 'Exchange rate: how many JMD for 1 unit of the currency';
COMMENT ON COLUMN currency_rate.source IS 'Rate source identifier. Values: MANUAL (user-entered), LEGACY (historical imported rates), UNCONFIGURED (default when no provider configured).';
COMMENT ON COLUMN currency_rate.rate_date IS 'The date the rate applies to';
COMMENT ON COLUMN currency_rate.create_dtime IS 'Timestamp when the rate was cached';

COMMIT;
