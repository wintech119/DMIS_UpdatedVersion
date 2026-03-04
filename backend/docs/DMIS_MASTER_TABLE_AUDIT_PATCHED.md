# DMIS Master Table Audit (Patched)

Date: 2026-03-03  
Scope: Live PostgreSQL schema used by `backend/dmis_api`

## 1. Purpose
This patched audit replaces the draft Word document with an implementation-ready, evidence-backed version.  
It focuses on:
- redundant/obsolete master-table patterns
- boundary ambiguities that create double-write risk
- missing master tables needed for the current DMIS roadmap

## 2. Validation Snapshot (Live DB)
Observed on 2026-03-03.

Pre-wave baseline:
- `auth_permission`: 64 rows
- `auth_user`: 0 rows
- `auth_group`: 0 rows
- `auth_group_permissions`: 0 rows
- `auth_user_groups`: 0 rows
- `auth_user_user_permissions`: 0 rows
- `warehouse_sync_status`: 11 rows
- `warehouse`: 11 rows
- `warehouse_sync_log`: 13 rows
- `event_phase`: 2 rows
- `event_phase_config`: 0 rows
- `itemcostdef`: 0 rows
- `hadr_aid_movement_staging`: 1562 rows

After wave-1 execution in this run:
- `event_phase_config`: 5 rows
- `itemcostdef`: dropped (table no longer exists)

After wave-2 execution in this run:
- `warehouse_sync_status` parity with `warehouse` status: reconciled (`11/11` matched)
- `custodian -> tenant` alignment: already aligned (`0` null backfills, `0` mismatches)

After wave-3 execution in this run:
- single-writer policy enforced with DB triggers:
  - `trg_enforce_item_location_policy`
  - `trg_enforce_batchlocation_policy`
- derived batched-location view created: `v_item_location_batched`
- MVP missing master tables scaffolded:
  - `role_scope_policy`
  - `approval_reason_code` (seeded with 5 rows)
  - `event_severity_profile`
  - `resource_capability_ref` (seeded with 4 rows)
  - `allocation_priority_rule`
  - `tenant_access_policy`

## 3. Patched Findings

### 3.1 Obsolete / Redundant (Action Required)

1. `auth_user`, `auth_group`, `auth_group_permissions`, `auth_user_groups`, `auth_user_user_permissions`  
   Keep as Django framework infrastructure only. Application authorization must remain DMIS RBAC-driven (`user`, `role`, `permission`, `role_permission`, `user_role`).

2. `warehouse_sync_status` (staged retirement candidate)  
   Current-state sync already exists on `warehouse` (`last_sync_dtime`, `sync_status`) and history in `warehouse_sync_log`.  
   Do not drop immediately because table is populated and still part of current schema footprint.

3. `custodian` (transitional overlap with `tenant`)  
   Ownership semantics overlap with multi-tenant model.  
   Migrate ownership policy to `tenant` and keep `custodian` as deprecated transitional reference until donation/warehouse references are resolved.

4. `itemcostdef`  
   Empty table and no FK dependencies were verified in live DB.  
   Wave-1 guarded cleanup executed: table dropped.

5. `hadr_aid_movement_staging`  
   ETL staging table, not a domain master table.  
   Move to ETL boundary (`etl` schema or archive policy) and remove from core-domain master catalog.

6. `event_phase` snapshot columns vs `event_phase_config`  
   Snapshot pattern is valid but undocumented.  
   `event_phase` should keep runtime snapshot values; `event_phase_config` is pre-activation policy source.  
   Add explicit DB comments and seed/backfill `event_phase_config`.

### 3.2 Questionable / Boundary Clarification Needed

1. `country`  
   Keep for donor/supplier international context.  
   Consider deprecating `country.currency_code` linkage from business logic.

2. `batchlocation` vs `item_location`  
   Define single-writer rule:
   - batched items -> `batchlocation` source-of-truth
   - non-batched items -> `item_location` source-of-truth
   Add service-layer guardrails to prevent double-write behavior.

3. `distribution_package` style mismatch  
   Functionally valid but naming conventions differ from legacy DMIS tables.  
   Standardize via migration convention policy; avoid immediate physical renames.

## 4. Group 3: Necessary Master Tables (Enumerated)
The original draft mentioned 22 tables but did not list them.  
Patched list (current-state keep/enhance):

1. `agency`
2. `allocation_limit`
3. `allocation_rule`
4. `approval_authority_matrix`
5. `approval_threshold_policy`
6. `country`
7. `currency`
8. `event`
9. `event_phase_config`
10. `item`
11. `itemcatg`
12. `lead_time_config`
13. `location`
14. `parish`
15. `permission`
16. `ref_approval_tier`
17. `ref_event_phase`
18. `ref_procurement_method`
19. `ref_tenant_type`
20. `role`
21. `supplier`
22. `tenant`

## 5. Group 4: Missing Master Tables (MVP for Current Roadmap)
The original draft declared missing masters without concrete definitions.  
Patched MVP set for current DMIS phases (now scaffolded in schema):

1. `role_scope_policy`  
   Purpose: Normalize role-to-scope constraints (tenant, warehouse, cross-tenant flags).

2. `approval_reason_code`  
   Purpose: Canonical reason catalog for return/reject/escalate decisions.

3. `event_severity_profile`  
   Purpose: Structured severity and operating assumptions per event.

4. `resource_capability_ref`  
   Purpose: Master list for operational capability categories used in allocation.

5. `allocation_priority_rule`  
   Purpose: Declarative weighting model metadata for needs/prioritization.

6. `tenant_access_policy`  
   Purpose: Explicit policy defaults for cross-tenant read/write behavior.

## 6. Contradictions Fixed from Draft
- Draft implied all Django auth tables should remain empty.  
  Patched: `auth_permission` is populated and expected for framework metadata.
- Draft suggested direct drop of `warehouse_sync_status`.  
  Patched: staged retirement only.
- Draft omitted Group 3 and Group 4 concrete inventories.  
  Patched: both fully enumerated.
- Draft implied config authority without accounting for zero rows in `event_phase_config`.  
  Patched: seed/backfill was executed before policy-only enforcement.

## 7. Migration Runbook (Phased, Safe)

### Wave 1 (safe, additive)
- add operational checks and snapshot tooling
- seed/backfill `event_phase_config` from `event_phase`/defaults
- add snapshot-semantics comments on `event_phase` columns
- remove dead references and drop `itemcostdef` (after reference confirmation)

### Wave 2 (controlled deprecation)
- deprecate `warehouse_sync_status` reads
- transition `custodian` ownership semantics into `tenant`
- isolate `hadr_aid_movement_staging` into ETL boundary

### Wave 3 (policy hardening)
- enforce single-writer rule for `batchlocation`/`item_location`
- implement missing master tables required by active roadmap

## 8. Acceptance Gates
- `manage.py check` passes with no errors
- no app authorization path depends on Django `auth_group` membership
- `event_phase_config` is populated for active event-phase contexts
- migration scripts provide rollback path for each destructive change
- location storage writes respect batched/non-batched policy at DB trigger level
