# Master Table Deprecation Roadmap (Phased, Safe)

Date: 2026-03-03

## Scope
This roadmap operationalizes the patched master-table audit into staged implementation work, with explicit preconditions and rollback posture.

## Phase 0: Baseline + Safety Rails
1. Run schema snapshot:
   - `python manage.py master_table_audit_snapshot --format markdown --output docs/reviews/master_table_snapshot.md`
2. Validate `manage.py check` output and confirm DMIS RBAC boundary warnings are reviewed.
3. Back up database before destructive changes.

## Phase 1: Additive / Low Risk

### 1. event_phase_config backfill and snapshot semantics
Command:
```powershell
python manage.py seed_event_phase_config_baseline --apply --actor SYSTEM
```

Outcome:
- creates/updates `event_phase_config` rows for active event-phase contexts
- adds comments documenting snapshot semantics on `event_phase` columns

Rollback:
- remove seeded rows by actor/time window if needed
- comments can be replaced with previous text

### 2. itemcostdef retirement (candidate)
Preconditions:
- no runtime SQL references
- no FK dependencies (already validated)
- table has no required data (currently empty)

Change:
```sql
DROP TABLE IF EXISTS itemcostdef;
```

Rollback:
- recreate table from DDL in `database_dump_pgadmin (new).sql` and restore from backup if needed

## Phase 2: Controlled Deprecation

### 1. warehouse_sync_status retirement
Preconditions:
- no API/service read paths depend on table
- parity check between table and `warehouse.sync_status` for at least one release cycle

Change path:
1. remove table reads in app code
2. monitor parity checks
3. drop FK/table only after stable zero-usage period

Execution status (2026-03-03):
- runtime code scan showed no active application read paths using `warehouse_sync_status`
- parity command added and executed:
  - `python manage.py verify_warehouse_sync_status_parity --repair-shadow`
  - post-repair parity: 11 matched, 0 mismatched

### 2. custodian -> tenant ownership transition
Preconditions:
- mapping established for every `custodian` row to `tenant`
- `warehouse` ownership policy moved to `tenant_id`

Change path:
1. stop creating new `custodian` records
2. migrate donation/warehouse references incrementally
3. deprecate table after all references are replaced

Execution status (2026-03-03):
- alignment command added and executed:
  - `python manage.py align_custodian_tenant_mapping --apply --actor SYSTEM`
  - results: 0 null backfills required, 0 mismatches, all 3 custodians already tenant-aligned

## Phase 3: Boundary Hardening

### 1. batchlocation vs item_location single-writer policy
- batched items: write `batchlocation`
- non-batched items: write `item_location`
- reporting via derived/aggregate view

Execution status (2026-03-03):
- enforcement command added and executed:
  - `python manage.py enforce_location_storage_policy --apply`
- SQL mirror artifact: `docs/migration/master_table_wave3.sql`
- DB objects created:
  - trigger `trg_enforce_item_location_policy` on `item_location`
  - trigger `trg_enforce_batchlocation_policy` on `batchlocation`
  - view `v_item_location_batched`
- validation:
  - batched-item write into `item_location` is blocked with policy exception
  - trigger and view existence verified in PostgreSQL catalog

### 2. Missing master table rollout (MVP)
- `role_scope_policy`
- `approval_reason_code`
- `event_severity_profile`
- `resource_capability_ref`
- `allocation_priority_rule`
- `tenant_access_policy`

Execution status (2026-03-03):
- scaffolding command added and executed:
  - `python manage.py scaffold_wave3_master_tables --apply`
- SQL mirror artifact: `docs/migration/master_table_wave3.sql`
- created all six MVP tables
- seeded:
  - `approval_reason_code`: 5 rows
  - `resource_capability_ref`: 4 rows

## Acceptance Criteria
1. `python manage.py check` returns no errors.
2. `master_table_audit_snapshot` shows expected contradictions resolved per phase.
3. Authorization continues to resolve from DMIS RBAC tables.
4. No production workflow regression in replenishment/masterdata endpoints.
