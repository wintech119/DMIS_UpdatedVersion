# DMIS v5.1 Master-Table Alignment Implementation

This folder contains concrete implementation artifacts to align live-schema master/config tables with `DMIS_Requirements_Specification_v5_1 Consolidated`.

## Baseline Used
- Live schema export: `__live_dmis_schema.sql` (captured from `dmis` on `localhost:5432`)
- Requirements extract: `__dmis_v51_text.txt`

## Deliverables
- `01_master_alignment_matrix.md`:
  - Table-by-table alignment for all live master/config/reference tables in scope
  - FR mapping, coverage status, gap summary, and migration action
- `02_target_master_data_spec.md`:
  - Decision-complete target model and interface changes
- `03_form_backlog_and_strategy.md`:
  - Form backlog and behavior rules for master data administration
- `04_validation_and_acceptance.md`:
  - SQL checks and acceptance criteria mapped to requirements
- `sql/`:
  - Ordered SQL migration scripts implementing the alignment

## Migration Order
1. `sql/001_wave1_reference_catalogs.sql`
2. `sql/002_wave2_governance_policy_tables.sql`
3. `sql/003_wave3_extend_existing_master_tables.sql`
4. `sql/004_wave4_tenant_rls_alignment.sql`
5. `sql/005_wave5_validation_queries.sql`

## Execution Notes
- Scripts are additive and migration-oriented (they are not executed in this workspace).
- Where backward compatibility is required, check constraints are widened to include both legacy and v5.1 canonical values.
- RLS policies are introduced for tenant-scoped tables and depend on session setting:
  - `SET app.tenant_ids = '1,2,...';`
  - `SET app.user_id = '<app_user_id>';`
- RLS strict enforcement is toggle-based for safe rollout:
  - `SET app.enforce_tenant_rls = 'on';`
  - Default behavior is fail-safe (non-enforcing) until the application is ready.
