-- Migration: Update currency_rate source column default
-- Date: 2025-11-26
-- Purpose: Change the default value for 'source' column from 'FRANKFURTER_ECB' to 'UNCONFIGURED'
--          This reflects that no external currency API is currently configured.
-- 
-- This is a SAFE migration - only modifies the DEFAULT value, does not alter data.

BEGIN;

-- Update the default value for the source column
ALTER TABLE currency_rate
ALTER COLUMN source SET DEFAULT 'UNCONFIGURED';

-- Update table comment to reflect current state
COMMENT ON TABLE currency_rate IS 'Cached exchange rates to JMD. Used for display-only currency conversion. Rates can be inserted manually.';
COMMENT ON COLUMN currency_rate.source IS 'Rate source identifier. Default is UNCONFIGURED when no external provider is configured.';

COMMIT;
