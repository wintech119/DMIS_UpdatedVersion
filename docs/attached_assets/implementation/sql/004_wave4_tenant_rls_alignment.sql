-- Wave 4: Tenant isolation and RLS alignment
-- Note: Application/session must set app.tenant_ids, example:
--   SET app.tenant_ids = '1,2';
-- and app.user_id, example:
--   SET app.user_id = '123';
-- Strict enforcement is toggle-based to avoid outage during rollout:
--   SET app.enforce_tenant_rls = 'on';

BEGIN;

CREATE SCHEMA IF NOT EXISTS app;

CREATE OR REPLACE FUNCTION app.current_tenant_ids()
RETURNS integer[]
LANGUAGE sql
STABLE
AS $$
    SELECT COALESCE(
        ARRAY(
            SELECT trim(x)::integer
            FROM regexp_split_to_table(COALESCE(current_setting('app.tenant_ids', true), ''), ',') AS x
            WHERE trim(x) ~ '^[0-9]+$'
        ),
        ARRAY[]::integer[]
    );
$$;

CREATE OR REPLACE FUNCTION app.tenant_rls_enforced()
RETURNS boolean
LANGUAGE sql
STABLE
AS $$
    SELECT COALESCE(lower(current_setting('app.enforce_tenant_rls', true)), 'off') IN ('on', 'true', '1');
$$;

CREATE OR REPLACE FUNCTION app.has_tenant_context()
RETURNS boolean
LANGUAGE sql
STABLE
AS $$
    SELECT COALESCE(array_length(app.current_tenant_ids(), 1), 0) > 0;
$$;

CREATE OR REPLACE FUNCTION app.current_app_user_id()
RETURNS integer
LANGUAGE sql
STABLE
AS $$
    SELECT CASE
        WHEN COALESCE(current_setting('app.user_id', true), '') ~ '^[0-9]+$'
            THEN current_setting('app.user_id', true)::integer
        ELSE NULL
    END;
$$;

CREATE OR REPLACE FUNCTION app.tenant_context_authorized()
RETURNS boolean
LANGUAGE sql
STABLE
AS $$
    SELECT
        app.has_tenant_context()
        AND app.current_app_user_id() IS NOT NULL
        AND NOT EXISTS (
            SELECT 1
            FROM unnest(app.current_tenant_ids()) AS t(tenant_id)
            WHERE NOT EXISTS (
                SELECT 1
                FROM public.tenant_user tu
                WHERE tu.tenant_id = t.tenant_id
                  AND tu.user_id = app.current_app_user_id()
                  AND tu.status_code = 'A'
            )
        );
$$;

-- Helper function to create policies idempotently
CREATE OR REPLACE FUNCTION app.ensure_policy(
    p_table regclass,
    p_policy_name text,
    p_using_expr text
)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    v_schema text;
    v_table text;
BEGIN
    SELECT n.nspname, c.relname
      INTO v_schema, v_table
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE c.oid = p_table;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_policies
        WHERE schemaname = v_schema
          AND tablename = v_table
          AND policyname = p_policy_name
    ) THEN
        EXECUTE format(
            'CREATE POLICY %I ON %s USING (%s)',
            p_policy_name,
            p_table,
            p_using_expr
        );
    END IF;
END;
$$;

-- Tenant table (self-visible to assigned tenant IDs)
ALTER TABLE public.tenant ENABLE ROW LEVEL SECURITY;
SELECT app.ensure_policy(
    'public.tenant',
    'tenant_isolation_policy',
    '(NOT app.tenant_rls_enforced()) OR (app.tenant_context_authorized() AND tenant_id = ANY(app.current_tenant_ids()))'
);

-- Existing tenant-scoped tables
ALTER TABLE public.warehouse ENABLE ROW LEVEL SECURITY;
SELECT app.ensure_policy(
    'public.warehouse',
    'warehouse_tenant_isolation_policy',
    '(NOT app.tenant_rls_enforced()) OR (app.tenant_context_authorized() AND (tenant_id IS NULL OR tenant_id = ANY(app.current_tenant_ids())))'
);

ALTER TABLE public.custodian ENABLE ROW LEVEL SECURITY;
SELECT app.ensure_policy(
    'public.custodian',
    'custodian_tenant_isolation_policy',
    '(NOT app.tenant_rls_enforced()) OR (app.tenant_context_authorized() AND (tenant_id IS NULL OR tenant_id = ANY(app.current_tenant_ids())))'
);

ALTER TABLE public.tenant_config ENABLE ROW LEVEL SECURITY;
SELECT app.ensure_policy(
    'public.tenant_config',
    'tenant_config_isolation_policy',
    '(NOT app.tenant_rls_enforced()) OR (app.tenant_context_authorized() AND tenant_id = ANY(app.current_tenant_ids()))'
);

ALTER TABLE public.tenant_user ENABLE ROW LEVEL SECURITY;
SELECT app.ensure_policy(
    'public.tenant_user',
    'tenant_user_isolation_policy',
    '(NOT app.tenant_rls_enforced()) OR (app.has_tenant_context() AND tenant_id = ANY(app.current_tenant_ids()))'
);

ALTER TABLE public.tenant_warehouse ENABLE ROW LEVEL SECURITY;
SELECT app.ensure_policy(
    'public.tenant_warehouse',
    'tenant_warehouse_isolation_policy',
    '(NOT app.tenant_rls_enforced()) OR (app.tenant_context_authorized() AND tenant_id = ANY(app.current_tenant_ids()))'
);

ALTER TABLE public.data_sharing_agreement ENABLE ROW LEVEL SECURITY;
SELECT app.ensure_policy(
    'public.data_sharing_agreement',
    'data_sharing_isolation_policy',
    '(NOT app.tenant_rls_enforced()) OR (app.tenant_context_authorized() AND (from_tenant_id = ANY(app.current_tenant_ids()) OR to_tenant_id = ANY(app.current_tenant_ids())))'
);

-- Newly introduced tenant-scoped policy/config tables
ALTER TABLE public.approval_threshold_policy ENABLE ROW LEVEL SECURITY;
SELECT app.ensure_policy(
    'public.approval_threshold_policy',
    'approval_threshold_policy_isolation_policy',
    '(NOT app.tenant_rls_enforced()) OR (app.tenant_context_authorized() AND (tenant_id IS NULL OR tenant_id = ANY(app.current_tenant_ids())))'
);

ALTER TABLE public.approval_authority_matrix ENABLE ROW LEVEL SECURITY;
SELECT app.ensure_policy(
    'public.approval_authority_matrix',
    'approval_authority_matrix_isolation_policy',
    '(NOT app.tenant_rls_enforced()) OR (app.tenant_context_authorized() AND (tenant_id IS NULL OR tenant_id = ANY(app.current_tenant_ids())))'
);

ALTER TABLE public.workflow_transition_rule ENABLE ROW LEVEL SECURITY;
SELECT app.ensure_policy(
    'public.workflow_transition_rule',
    'workflow_transition_rule_isolation_policy',
    '(NOT app.tenant_rls_enforced()) OR (app.tenant_context_authorized() AND (tenant_id IS NULL OR tenant_id = ANY(app.current_tenant_ids())))'
);

ALTER TABLE public.allocation_rule ENABLE ROW LEVEL SECURITY;
SELECT app.ensure_policy(
    'public.allocation_rule',
    'allocation_rule_isolation_policy',
    '(NOT app.tenant_rls_enforced()) OR (app.tenant_context_authorized() AND (tenant_id IS NULL OR tenant_id = ANY(app.current_tenant_ids())))'
);

ALTER TABLE public.allocation_limit ENABLE ROW LEVEL SECURITY;
SELECT app.ensure_policy(
    'public.allocation_limit',
    'allocation_limit_isolation_policy',
    '(NOT app.tenant_rls_enforced()) OR (app.tenant_context_authorized() AND (tenant_id IS NULL OR tenant_id = ANY(app.current_tenant_ids())))'
);

ALTER TABLE public.user_tenant_role ENABLE ROW LEVEL SECURITY;
SELECT app.ensure_policy(
    'public.user_tenant_role',
    'user_tenant_role_isolation_policy',
    '(NOT app.tenant_rls_enforced()) OR (app.tenant_context_authorized() AND tenant_id = ANY(app.current_tenant_ids()))'
);

ALTER TABLE public.item_category_baseline_rate ENABLE ROW LEVEL SECURITY;
SELECT app.ensure_policy(
    'public.item_category_baseline_rate',
    'item_category_baseline_rate_isolation_policy',
    '(NOT app.tenant_rls_enforced()) OR (app.tenant_context_authorized() AND (tenant_id IS NULL OR tenant_id = ANY(app.current_tenant_ids())))'
);

ALTER TABLE public.mpf_criteria_weight ENABLE ROW LEVEL SECURITY;
SELECT app.ensure_policy(
    'public.mpf_criteria_weight',
    'mpf_criteria_weight_isolation_policy',
    '(NOT app.tenant_rls_enforced()) OR (app.tenant_context_authorized() AND (tenant_id IS NULL OR tenant_id = ANY(app.current_tenant_ids())))'
);

-- Optional tenant scope for supplier (added in Wave 3)
ALTER TABLE public.supplier ENABLE ROW LEVEL SECURITY;
SELECT app.ensure_policy(
    'public.supplier',
    'supplier_tenant_isolation_policy',
    '(NOT app.tenant_rls_enforced()) OR (app.tenant_context_authorized() AND (tenant_id IS NULL OR tenant_id = ANY(app.current_tenant_ids())))'
);

COMMIT;
