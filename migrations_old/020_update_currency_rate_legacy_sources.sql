-- Migration: Update legacy source values in currency_rate table
-- Date: 2025-11-26
-- Purpose: Replace 'FRANKFURTER_ECB' source values with 'LEGACY' to remove
--          references to the deprecated external API provider while preserving
--          historical rate data and referential integrity.
--
-- Rollback: UPDATE currency_rate SET source = 'FRANKFURTER_ECB' WHERE source = 'LEGACY';

-- Update existing FRANKFURTER_ECB sources to LEGACY
UPDATE currency_rate 
SET source = 'LEGACY' 
WHERE source = 'FRANKFURTER_ECB';

-- Add comment documenting the change
COMMENT ON COLUMN currency_rate.source IS 'Rate source identifier. Values: MANUAL (user-entered), LEGACY (historical imported rates), UNCONFIGURED (default when no provider configured).';
