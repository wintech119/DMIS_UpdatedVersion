# Migration Runbook

## Preconditions
1. Backup live database.
2. Confirm target DB is `dmis` and schema is `public`.
3. Ensure no write-heavy maintenance jobs are running.

## Recommended Execution
Run scripts in strict order:

```sql
\i implementation/sql/001_wave1_reference_catalogs.sql
\i implementation/sql/002_wave2_governance_policy_tables.sql
\i implementation/sql/003_wave3_extend_existing_master_tables.sql
\i implementation/sql/004_wave4_tenant_rls_alignment.sql
\i implementation/sql/005_wave5_validation_queries.sql
```

## Cutover Steps
1. Deploy DB migrations.
2. Deploy application changes that:
   - read reference catalogs for dropdowns
   - use `user_tenant_role` for authorization checks
   - enforce transition rules via `workflow_transition_rule`
   - set session variable `app.tenant_ids`
   - set session variable `app.user_id`
3. Keep strict RLS OFF during initial rollout (default safe mode).
4. After app session bootstrap is verified in all services/jobs, enable strict RLS:
   - `SET app.enforce_tenant_rls = 'on';` (session-level), or role/database parameter by DBA policy.
5. Enable policy-driven screens (approval matrix, allocation rules, reason code maintenance).

## Rollback Strategy
1. If Wave 1 or Wave 2 fails:
   - rollback transaction and fix DDL.
2. If Wave 3 fails:
   - rollback transaction and re-run once data conflicts are corrected.
3. If Wave 4 (RLS) causes access disruption:
   - temporarily disable RLS on affected tables:
     - `ALTER TABLE <table> DISABLE ROW LEVEL SECURITY;`
   - correct policy logic and re-enable.

## Operational Verification
1. Execute validation script queries.
2. Verify at least one tenant-scoped user can access only expected records.
3. Verify policy-based approval routing with a test procurement.
4. Verify stale-data baseline lookup works with `item_category_baseline_rate`.
5. Verify strict RLS mode:
   - with `app.enforce_tenant_rls=on`, valid `app.tenant_ids`, and valid `app.user_id`, queries are scoped.
   - with `app.enforce_tenant_rls=on` and missing/invalid tenant context, queries return no tenant rows.
