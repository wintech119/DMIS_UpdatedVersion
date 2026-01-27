-- =====================================================
-- DRIMS Event Management Module - Permissions Seeding
-- =====================================================
-- This script is idempotent and safe to run multiple times.
-- It seeds permissions for the Event management module and 
-- maps them to the CUSTODIAN role.
-- =====================================================

-- 1. Ensure CUSTODIAN role exists
INSERT INTO role (code, name, description)
VALUES (
    'CUSTODIAN',
    'Custodian',
    'Role responsible for managing disaster events and event lifecycle in DRIMS.'
)
ON CONFLICT (code) DO NOTHING;

-- 2. Create Event permissions
INSERT INTO permission (resource, action, create_by_id, create_dtime, update_by_id, update_dtime, version_nbr)
VALUES
    ('EVENT', 'VIEW', 'SYSTEM', CURRENT_TIMESTAMP, 'SYSTEM', CURRENT_TIMESTAMP, 1),
    ('EVENT', 'CREATE', 'SYSTEM', CURRENT_TIMESTAMP, 'SYSTEM', CURRENT_TIMESTAMP, 1),
    ('EVENT', 'UPDATE', 'SYSTEM', CURRENT_TIMESTAMP, 'SYSTEM', CURRENT_TIMESTAMP, 1),
    ('EVENT', 'CLOSE', 'SYSTEM', CURRENT_TIMESTAMP, 'SYSTEM', CURRENT_TIMESTAMP, 1),
    ('EVENT', 'DELETE', 'SYSTEM', CURRENT_TIMESTAMP, 'SYSTEM', CURRENT_TIMESTAMP, 1)
ON CONFLICT (resource, action) DO NOTHING;

-- 3. Map CUSTODIAN role to Event permissions
WITH custodian_role AS (
    SELECT id AS role_id
    FROM role
    WHERE code = 'CUSTODIAN'
),
event_perms AS (
    SELECT perm_id
    FROM permission
    WHERE resource = 'EVENT'
      AND action IN ('VIEW', 'CREATE', 'UPDATE', 'CLOSE', 'DELETE')
)
INSERT INTO role_permission (role_id, perm_id, scope_json, create_by_id, create_dtime, update_by_id, update_dtime, version_nbr)
SELECT
    r.role_id,
    p.perm_id,
    '{}'::jsonb,  -- global/default scope
    'SYSTEM' AS create_by_id,
    CURRENT_TIMESTAMP AS create_dtime,
    'SYSTEM' AS update_by_id,
    CURRENT_TIMESTAMP AS update_dtime,
    1 AS version_nbr
FROM custodian_role r
CROSS JOIN event_perms p
ON CONFLICT (role_id, perm_id) DO NOTHING;

-- 4. Verification Query (Optional - for manual verification)
-- Uncomment to see the results after running this script:
/*
SELECT 
    r.code AS role_code,
    r.name AS role_name,
    p.resource,
    p.action
FROM role r
JOIN role_permission rp ON r.id = rp.role_id
JOIN permission p ON rp.perm_id = p.perm_id
WHERE r.code = 'CUSTODIAN'
ORDER BY p.resource, p.action;
*/
