# Validation and Acceptance

## Objective
Validate that live-schema master/config tables are aligned to v5.1 and that new governance tables operate correctly.

## Validation Groups

## 1) Structural Alignment
1. Every table in `01_master_alignment_matrix.md` has implemented action (`keep`, `extend`, `new`).
2. New reference catalogs exist and are seeded.
3. New policy tables exist with required keys and constraints.

## 2) Constraint and Domain Alignment
1. `tenant.tenant_type` allows v5.1 set including `SOCIAL_SERVICES`, `NGO`.
2. Event phase checks include `RECOVERY` in all related tables.
3. `lead_time_config` supports donor-specific Horizon-B rules.
4. `supplier` stores TRN/TCC compliance fields.
5. Needs-list/procurement status checks accept canonical v5.1 lifecycle values (legacy-compatible transition window acceptable).

## 3) Tenant Isolation
1. RLS enabled on tenant-scoped master tables.
2. Policies enforce tenant visibility based on `app.tenant_ids`.
3. No rows from other tenants are visible without valid sharing context.

## 4) Governance Behavior
1. Threshold policies resolve approval tier deterministically.
2. Authority matrix sequence validates mandatory approval chain.
3. Workflow transitions block invalid status moves.
4. SoD flag in transition rules blocks same actor request+approve where configured.
5. Override-required flows enforce reason codes from `reason_code_master`.

## 5) Acceptance Criteria (Plan-level)
1. 100% of in-scope master/config tables from live schema appear in alignment matrix.
2. 100% of matrix rows map to FR IDs and an implementation action.
3. All `gap` rows have concrete tables/scripts in `sql/`.
4. All `partial` rows have concrete extension scripts in `sql/`.
5. Validation SQL in `sql/005_wave5_validation_queries.sql` returns expected pass conditions.

## Suggested Test Scenarios
1. Create tenant with `tenant_type='SOCIAL_SERVICES'`: succeeds.
2. Insert `event_phase.phase_code='RECOVERY'`: succeeds.
3. Insert Horizon-B lead-time with donor and horizon `B`: succeeds.
4. Insert invalid workflow transition not in rule table: rejected by application/service layer.
5. Query tenant-scoped table under `SET app.tenant_ids='1'`: only tenant 1 (and global where allowed) is visible.

