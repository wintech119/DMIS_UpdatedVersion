-- =====================================================
-- DMIS Database Sequence Reset Script
-- =====================================================
-- Purpose: Reset all auto-increment sequences to be in sync
--          with the maximum existing ID values in each table.
-- Usage:   Run after database restore/import to fix
--          "duplicate key violates unique constraint" errors.
-- Date:    2025-12-05
-- =====================================================

-- Begin transaction for safety
BEGIN;

-- =====================================================
-- Core System Tables
-- =====================================================

-- Fix user sequence
SELECT setval(
    pg_get_serial_sequence('public.user', 'user_id'),
    COALESCE((SELECT MAX(user_id) FROM "user"), 0) + 1,
    false
);

-- Fix role sequence
SELECT setval(
    'public.role_id_seq',
    COALESCE((SELECT MAX(id) FROM role), 0) + 1,
    false
);

-- Fix notification sequence
SELECT setval(
    'public.notification_id_seq',
    COALESCE((SELECT MAX(id) FROM notification), 0) + 1,
    false
);

-- =====================================================
-- Inventory & Item Tables
-- =====================================================

-- Fix item sequence (uses non-standard name from legacy schema)
SELECT setval(
    'public.item_new_item_id_seq',
    COALESCE((SELECT MAX(item_id) FROM item), 0) + 1,
    false
);

-- Fix transaction sequence
SELECT setval(
    'public.transaction_id_seq',
    COALESCE((SELECT MAX(id) FROM transaction), 0) + 1,
    false
);

-- =====================================================
-- Distribution & Transfer Tables
-- =====================================================

-- Fix distribution_package sequence
SELECT setval(
    'public.distribution_package_id_seq',
    COALESCE((SELECT MAX(id) FROM distribution_package), 0) + 1,
    false
);

-- Fix distribution_package_item sequence
SELECT setval(
    'public.distribution_package_item_id_seq',
    COALESCE((SELECT MAX(id) FROM distribution_package_item), 0) + 1,
    false
);

-- Fix transfer_request sequence
SELECT setval(
    'public.transfer_request_id_seq',
    COALESCE((SELECT MAX(id) FROM transfer_request), 0) + 1,
    false
);

-- Fix xfreturn sequence
SELECT setval(
    'public.xfreturn_xfreturn_id_seq',
    COALESCE((SELECT MAX(xfreturn_id) FROM xfreturn), 0) + 1,
    false
);

-- =====================================================
-- Verification: Display current sequence values
-- =====================================================
SELECT 
    'user' as table_name,
    (SELECT MAX(user_id) FROM "user") as max_id,
    (SELECT last_value FROM public.user_id_seq) as sequence_value
UNION ALL
SELECT 
    'role',
    (SELECT MAX(id) FROM role),
    (SELECT last_value FROM public.role_id_seq)
UNION ALL
SELECT 
    'item',
    (SELECT MAX(item_id) FROM item),
    (SELECT last_value FROM public.item_new_item_id_seq)
UNION ALL
SELECT 
    'transaction',
    (SELECT MAX(id) FROM transaction),
    (SELECT last_value FROM public.transaction_id_seq)
UNION ALL
SELECT 
    'notification',
    (SELECT MAX(id) FROM notification),
    (SELECT last_value FROM public.notification_id_seq)
UNION ALL
SELECT 
    'distribution_package',
    (SELECT MAX(id) FROM distribution_package),
    (SELECT last_value FROM public.distribution_package_id_seq)
UNION ALL
SELECT 
    'transfer_request',
    (SELECT MAX(id) FROM transfer_request),
    (SELECT last_value FROM public.transfer_request_id_seq)
UNION ALL
SELECT 
    'xfreturn',
    (SELECT MAX(xfreturn_id) FROM xfreturn),
    (SELECT last_value FROM public.xfreturn_xfreturn_id_seq);

COMMIT;

-- =====================================================
-- End of Script
-- =====================================================
