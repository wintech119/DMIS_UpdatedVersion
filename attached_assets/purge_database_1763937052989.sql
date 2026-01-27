-- ============================================================================
-- DRIMS Database Purge Script
-- ============================================================================
-- This script safely purges all data from the database while maintaining
-- referential integrity by deleting records in the correct order.
--
-- IMPORTANT: This script will DELETE ALL DATA from all tables!
-- It is recommended to:
-- 1. Create a backup before running this script
-- 2. Review the script carefully
-- 3. Test in a non-production environment first
-- ============================================================================

-- Start transaction to ensure atomicity
BEGIN;

-- Disable triggers temporarily for faster deletion (optional)
-- SET session_replication_role = 'replica';

-- ============================================================================
-- PHASE 1: Delete from child tables (tables with foreign keys to other tables)
-- ============================================================================

-- Delete audit and tracking tables first (these reference other tables)
TRUNCATE TABLE public.agency_account_request_audit CASCADE;
TRUNCATE TABLE public.notification CASCADE;

-- Delete fulfillment locks
TRUNCATE TABLE public.relief_request_fulfillment_lock CASCADE;

-- Delete batch locations (references inventory and location)
TRUNCATE TABLE public.batchlocation CASCADE;

-- Delete user associations
TRUNCATE TABLE public.user_role CASCADE;
TRUNCATE TABLE public.user_warehouse CASCADE;

-- Delete transfer requests (references warehouses, items, users)
TRUNCATE TABLE public.transfer_request CASCADE;

-- Delete distribution-related data
TRUNCATE TABLE public.xfreturn_item CASCADE;
TRUNCATE TABLE public.xfreturn CASCADE;

-- Delete real-time intake items (references rtintake)
TRUNCATE TABLE public.rtintake_item CASCADE;
TRUNCATE TABLE public.rtintake CASCADE;

-- Delete distribution records (references reliefpkg)
TRUNCATE TABLE public.distribution CASCADE;

-- Delete package items (references reliefpkg and inventory)
TRUNCATE TABLE public.reliefpkg_item CASCADE;

-- Delete relief packages (references reliefrqst)
TRUNCATE TABLE public.reliefpkg CASCADE;

-- Delete relief request items
TRUNCATE TABLE public.reliefrqst_item CASCADE;

-- Delete relief requests
TRUNCATE TABLE public.reliefrqst CASCADE;

-- Delete transactions (references multiple tables)
TRUNCATE TABLE public.transaction CASCADE;

-- Delete intake records for various types
TRUNCATE TABLE public.dbintake CASCADE;
TRUNCATE TABLE public.fdintake CASCADE;
TRUNCATE TABLE public.pvintake CASCADE;

-- Delete inventory locations
TRUNCATE TABLE public.inventorylocation CASCADE;

-- Delete inventory records (references item and warehouse)
TRUNCATE TABLE public.inventory CASCADE;

-- Delete item requests
TRUNCATE TABLE public.itemrqst CASCADE;

-- Delete kit items (references kit and item)
TRUNCATE TABLE public.kit_item CASCADE;

-- Delete agency account requests (references agency)
TRUNCATE TABLE public.agency_account_request CASCADE;

-- ============================================================================
-- PHASE 2: Delete from main entity tables
-- ============================================================================

-- Delete users (references agency and warehouse)
TRUNCATE TABLE public."user" CASCADE;

-- Delete locations (references warehouse)
TRUNCATE TABLE public.location CASCADE;

-- Delete agencies (references event, warehouse)
TRUNCATE TABLE public.agency CASCADE;

-- Delete warehouses (references custodian and parish)
TRUNCATE TABLE public.warehouse CASCADE;

-- Delete custodians (references parish)
TRUNCATE TABLE public.custodian CASCADE;

-- Delete kits (references item)
TRUNCATE TABLE public.kit CASCADE;

-- Delete items (references itemtype, uom)
TRUNCATE TABLE public.item CASCADE;

-- Delete events
TRUNCATE TABLE public.event CASCADE;

-- Delete donors (references country)
TRUNCATE TABLE public.donor CASCADE;

-- ============================================================================
-- PHASE 3: Delete from lookup/reference tables (no foreign key dependencies)
-- ============================================================================

-- Delete roles
TRUNCATE TABLE public.role CASCADE;

-- Delete item types
TRUNCATE TABLE public.itemtype CASCADE;

-- Delete unit of measure
TRUNCATE TABLE public.unitofmeasure CASCADE;

-- Delete parishes
TRUNCATE TABLE public.parish CASCADE;

-- Delete countries
TRUNCATE TABLE public.country CASCADE;

-- ============================================================================
-- PHASE 4: Reset sequences to start values
-- ============================================================================

-- Reset all sequences to start from 1
ALTER SEQUENCE public.agency_account_request_audit_audit_id_seq RESTART WITH 1;
ALTER SEQUENCE public.agency_account_request_request_id_seq RESTART WITH 1;
ALTER SEQUENCE public.agency_agency_id_seq RESTART WITH 1;
ALTER SEQUENCE public.custodian_custodian_id_seq RESTART WITH 1;
ALTER SEQUENCE public.distribution_distrib_id_seq RESTART WITH 1;
ALTER SEQUENCE public.donor_donor_id_seq RESTART WITH 1;
ALTER SEQUENCE public.event_event_id_seq RESTART WITH 1;
ALTER SEQUENCE public.inventory_inventory_id_seq RESTART WITH 1;
ALTER SEQUENCE public.item_item_id_seq RESTART WITH 1;
ALTER SEQUENCE public.itemrqst_itemrqst_id_seq RESTART WITH 1;
ALTER SEQUENCE public.itemtype_itemtype_id_seq RESTART WITH 1;
ALTER SEQUENCE public.kit_item_kit_item_id_seq RESTART WITH 1;
ALTER SEQUENCE public.kit_kit_id_seq RESTART WITH 1;
ALTER SEQUENCE public.location_location_id_seq RESTART WITH 1;
ALTER SEQUENCE public.notification_id_seq RESTART WITH 1;
ALTER SEQUENCE public.relief_request_fulfillment_lock_lock_id_seq RESTART WITH 1;
ALTER SEQUENCE public.reliefrqst_item_reliefrqst_item_id_seq RESTART WITH 1;
ALTER SEQUENCE public.reliefrqst_reliefrqst_id_seq RESTART WITH 1;
ALTER SEQUENCE public.reliefpkg_item_reliefpkg_item_id_seq RESTART WITH 1;
ALTER SEQUENCE public.reliefpkg_reliefpkg_id_seq RESTART WITH 1;
ALTER SEQUENCE public.role_id_seq RESTART WITH 1;
ALTER SEQUENCE public.rtintake_intake_id_seq RESTART WITH 1;
ALTER SEQUENCE public.rtintake_item_intake_item_id_seq RESTART WITH 1;
ALTER SEQUENCE public.transaction_transaction_id_seq RESTART WITH 1;
ALTER SEQUENCE public.transfer_request_request_id_seq RESTART WITH 1;
ALTER SEQUENCE public.user_role_id_seq RESTART WITH 1;
ALTER SEQUENCE public.user_user_id_seq RESTART WITH 1;
ALTER SEQUENCE public.user_warehouse_id_seq RESTART WITH 1;
ALTER SEQUENCE public.warehouse_warehouse_id_seq RESTART WITH 1;
ALTER SEQUENCE public.xfreturn_item_xfreturn_item_id_seq RESTART WITH 1;
ALTER SEQUENCE public.xfreturn_xfreturn_id_seq RESTART WITH 1;

-- Re-enable triggers if disabled
-- SET session_replication_role = 'origin';

-- ============================================================================
-- Verification Query (Optional)
-- ============================================================================
-- Uncomment to verify all tables are empty:
/*
SELECT 
    schemaname,
    tablename,
    (xpath('/row/cnt/text()', 
           query_to_xml(format('SELECT COUNT(*) as cnt FROM %I.%I', 
                              schemaname, tablename), 
                       false, true, '')))[1]::text::int AS row_count
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY tablename;
*/

-- Commit the transaction
COMMIT;

-- Display completion message
DO $$
BEGIN
    RAISE NOTICE '============================================================================';
    RAISE NOTICE 'Database purge completed successfully!';
    RAISE NOTICE 'All data has been deleted and sequences have been reset.';
    RAISE NOTICE '============================================================================';
END $$;
