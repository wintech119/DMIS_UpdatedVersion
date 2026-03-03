-- Wave 5: Validation queries (run after migrations)

-- 1) Confirm required master tables exist
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN (
      'ref_tenant_type',
      'ref_event_phase',
      'ref_procurement_method',
      'ref_approval_tier',
      'reason_code_master',
      'approval_threshold_policy',
      'approval_authority_matrix',
      'workflow_transition_rule',
      'allocation_rule',
      'allocation_limit',
      'user_tenant_role',
      'item_category_baseline_rate',
      'mpf_criteria_weight'
  )
ORDER BY table_name;

-- 2) Tenant type alignment (should return 0 rows)
SELECT tenant_id, tenant_code, tenant_type
FROM public.tenant
WHERE tenant_type NOT IN (
    'NATIONAL','MILITARY','SOCIAL_SERVICES','PARISH','NGO','MINISTRY','EXTERNAL','INFRASTRUCTURE','PUBLIC'
);

-- 3) Event phase alignment (should return 0 rows)
SELECT event_id, current_phase
FROM public.event
WHERE current_phase NOT IN ('SURGE','STABILIZED','RECOVERY','BASELINE');

-- 4) Horizon-B lead-time donor support (should return 0 rows)
SELECT config_id, horizon, donor_id, is_default
FROM public.lead_time_config
WHERE horizon = 'B'
  AND donor_id IS NULL
  AND is_default = false;

-- 5) Supplier compliance data quality
SELECT supplier_id, supplier_code, supplier_name, trn_no, tcc_no
FROM public.supplier
WHERE status_code = 'A'
  AND (trn_no IS NULL OR tcc_no IS NULL);

-- 6) Policy completeness check (threshold policy without matrix)
SELECT p.policy_id, p.entity_type, p.approval_tier_code
FROM public.approval_threshold_policy p
LEFT JOIN public.approval_authority_matrix m
  ON m.threshold_policy_id = p.policy_id
 AND m.status_code = 'A'
WHERE p.status_code = 'A'
GROUP BY p.policy_id, p.entity_type, p.approval_tier_code
HAVING COUNT(m.matrix_id) = 0;

-- 6b) Potential overlapping active threshold policies (manual resolution required)
SELECT a.policy_id AS policy_a,
       b.policy_id AS policy_b,
       a.entity_type,
       COALESCE(a.procurement_method_code, 'ALL') AS method_scope,
       a.currency_code,
       COALESCE(a.tenant_id, -1) AS tenant_scope
FROM public.approval_threshold_policy a
JOIN public.approval_threshold_policy b
  ON a.policy_id < b.policy_id
 AND a.status_code = 'A'
 AND b.status_code = 'A'
 AND a.entity_type = b.entity_type
 AND COALESCE(a.procurement_method_code, '') = COALESCE(b.procurement_method_code, '')
 AND a.currency_code = b.currency_code
 AND COALESCE(a.tenant_id, -1) = COALESCE(b.tenant_id, -1)
 AND numrange(a.min_amount, COALESCE(a.max_amount, 1e18::numeric), '[]')
     && numrange(b.min_amount, COALESCE(b.max_amount, 1e18::numeric), '[]')
 AND daterange(a.effective_date, COALESCE(a.expiry_date, '9999-12-31'::date), '[]')
     && daterange(b.effective_date, COALESCE(b.expiry_date, '9999-12-31'::date), '[]');

-- 7) Duplicate transition rules (should return 0 rows)
SELECT entity_type, from_status, to_status, role_code, tenant_id, COUNT(*) AS rule_count
FROM public.workflow_transition_rule
WHERE status_code = 'A'
GROUP BY entity_type, from_status, to_status, role_code, tenant_id
HAVING COUNT(*) > 1;

-- 8) Allocation limit overlap (simple overlap check)
SELECT a.limit_id AS limit_id_a, b.limit_id AS limit_id_b, a.event_id, a.agency_id
FROM public.allocation_limit a
JOIN public.allocation_limit b
  ON a.limit_id < b.limit_id
 AND a.event_id = b.event_id
 AND a.agency_id = b.agency_id
 AND COALESCE(a.item_category_id, -1) = COALESCE(b.item_category_id, -1)
 AND daterange(a.effective_date, COALESCE(a.expiry_date, '9999-12-31'::date), '[]')
     && daterange(b.effective_date, COALESCE(b.expiry_date, '9999-12-31'::date), '[]')
WHERE a.status_code = 'A'
  AND b.status_code = 'A';

-- 9) RLS status
SELECT c.relname AS table_name, c.relrowsecurity AS rls_enabled
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND c.relname IN (
      'tenant',
      'warehouse',
      'custodian',
      'tenant_config',
      'tenant_user',
      'tenant_warehouse',
      'data_sharing_agreement',
      'supplier',
      'approval_threshold_policy',
      'approval_authority_matrix',
      'workflow_transition_rule',
      'allocation_rule',
      'allocation_limit',
      'user_tenant_role',
      'item_category_baseline_rate',
      'mpf_criteria_weight'
  )
ORDER BY c.relname;

-- 10) RLS policy presence
SELECT schemaname, tablename, policyname
FROM pg_policies
WHERE schemaname = 'public'
ORDER BY tablename, policyname;

-- 11) Helper functions for safe/strict RLS rollout
SELECT p.proname
FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'app'
  AND p.proname IN (
      'current_tenant_ids',
      'tenant_rls_enforced',
      'has_tenant_context',
      'current_app_user_id',
      'tenant_context_authorized'
  )
ORDER BY p.proname;

-- 12) Overlap-prevention trigger exists
SELECT t.tgname, c.relname AS table_name
FROM pg_trigger t
JOIN pg_class c ON c.oid = t.tgrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND c.relname = 'approval_threshold_policy'
  AND t.tgname = 'trg_prevent_overlap_approval_threshold_policy'
  AND NOT t.tgisinternal;
