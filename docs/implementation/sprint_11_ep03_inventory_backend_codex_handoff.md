# DMIS EP-03 — Sprint 1 Backend: Codex Implementation Handoff

> **Use this prompt verbatim with Codex / GPT-5.4 (or equivalent autonomous coding agent).**
> The receiving model has no prior conversation context — everything it needs is referenced inline below.
>
> **Required reading before any code is written:**
> 1. [`docs/implementation/sprint_11_ep03_inventory_implementation_plan.md`](sprint_11_ep03_inventory_implementation_plan.md) — the approved EP-03 plan (authoritative)
> 2. `.claude/CLAUDE.md` — project guardrails, regression rules, secrets policy, rate limits, IDOR rules, mandatory architecture review
> 3. `backend/AGENTS.md` — backend-local rules (raw SQL discipline, ORM-only for new tables, tenancy enforcement)
> 4. `docs/adr/system_application_architecture.md` — canonical architecture
> 5. `docs/security/SECURITY_ARCHITECTURE.md`, `docs/security/THREAT_MODEL.md`, `docs/security/CONTROLS_MATRIX.md`
> 6. `docs/implementation/production_readiness_checklist.md`
> 7. `docs/implementation/production_hardening_and_flask_retirement_strategy.md`

---

## Begin handoff prompt

```
You are implementing the BACKEND for DMIS EP-03 (Stockpile/Warehouse Operations) Sprint 1, the inventory-accuracy backbone for Jamaica's ODPEM disaster response system. The complete design is the approved plan at:

  docs/implementation/sprint_11_ep03_inventory_implementation_plan.md

Read that plan in full BEFORE writing any code. It is the authoritative source of truth for: scope (60 Must-Have FRs across Phase 1+2 minus Sage minus location hierarchy), data model, service-layer chokepoint, RBAC, URL surface, migration plan, day-by-day sequencing, test plan, and verification.

Working directory: C:/Users/wbowe/OneDrive/Desktop/project/DMIS_UpdatedVersion/.claude/worktrees/intelligent-brown-926f56

================================================================================
DAY 1 IS ALREADY DONE
================================================================================

The following files exist and are verified working (manage.py check passes; makemigrations produced a clean 0001_initial.py). Extend them; do not duplicate.

CREATED:
  backend/inventory/__init__.py
  backend/inventory/apps.py                                — InventoryConfig
  backend/inventory/models.py                              — 25+ ORM tables (foundation + active OB workflow + scaffolded workflows)
  backend/inventory/exceptions.py                          — InventoryError + 9 subclasses
  backend/inventory/permissions.py                         — DRF permission classes per workflow
  backend/inventory/throttling.py                          — 5 throttle scopes (read/write/workflow/high-risk/bulk)
  backend/inventory/views.py                               — health endpoint stub
  backend/inventory/urls.py                                — mounted at /api/v1/inventory/
  backend/inventory/serializers.py                         — read-side stubs (StockSourceType, StockStatus, StockLedger, OB, etc.)
  backend/inventory/migrations/0001_initial.py             — auto-generated; covers all 25+ ORM tables
  backend/inventory/migrations/__init__.py
  backend/inventory/services/__init__.py
  backend/inventory/management/__init__.py
  backend/inventory/management/commands/__init__.py

MODIFIED:
  backend/dmis_api/settings.py                             — added 'inventory' to INSTALLED_APPS; added DMIS_INVENTORY_ENABLED, INVENTORY_BULK_DAILY_LINE_CAP, INVENTORY_EVIDENCE_MAX_BYTES, INVENTORY_AUDIT_PAYLOAD_MAX_BYTES, STOCK_EVIDENCE_STORAGE_PATH
  backend/dmis_api/urls.py                                 — /api/v1/inventory/ mounted behind DMIS_INVENTORY_ENABLED feature flag

YOUR JOB STARTS AT DAY 2.

================================================================================
NON-NEGOTIABLE GUARDRAILS
================================================================================

1. ZERO-BALANCE CUTOVER (governing rule):
   - DMIS inventory begins at ZERO. The system shall NOT mirror Opening Balance postings into legacy `inventory` or `itembatch` tables. There is NO automatic backfill from legacy.
   - All operational reads (replenishment dashboard, COP, dispatch availability, EP-02 needs lists) read from the ledger-derived sources in `inventory.selectors`, NEVER from legacy `inventory.usable_qty` directly.
   - Legacy `inventory` and `itembatch` are RETAINED as historical reference only. A reference-only CSV export is provided to logistics teams as a starting point for their physical count.

2. OPENING BALANCE IS THE ONLY OPERATIONAL SOURCE TYPE IN SPRINT 1:
   - All 10 StockSourceType codes are seeded (DONATION_RECEIPT, PROCUREMENT_RECEIPT, TRANSFER_RECEIPT, OPENING_BALANCE, POSITIVE_ADJUSTMENT, FIELD_RETURN, DISPATCH_REVERSAL, QUARANTINE_RELEASE, REPACK_KIT_OUTPUT, DATA_IMPORT).
   - Only OPENING_BALANCE has working services/views/UI in Sprint 1. The other 9 are configured but parked (workflow models exist but no service, no views, no UI). Future sprints implement them.

3. VALUATION PIPELINE — MISSING UNIT COST NEVER LOWERS APPROVAL TIER:
   The cascade is ITEM_UNIT_COST -> CATEGORY_ESTIMATE -> SAGE_DEFERRED_EXECUTIVE_ROUTE.
   The third option ELEVATES the approval route to Director PEOD / Executive (≥ $500K–$2M tier minimum) regardless of qty. Records a MANUAL_OVERRIDE exception (informational, audit). Tests must assert that no input combination can lower the approval tier when cost is missing.

4. IMMUTABLE AUDIT — UPDATE/DELETE BLOCK VIA PG TRIGGER:
   `stock_ledger` and `inventory_audit_log` are append-only. PostgreSQL trigger blocks UPDATE/DELETE. Migration 0002_immutable_triggers installs and reverses cleanly.

5. ALL INVENTORY MUTATIONS GO THROUGH services/ledger.post_entry:
   - Single chokepoint. No other code path inserts into `stock_ledger`.
   - Acquires PostgreSQL advisory lock on (tenant_id, warehouse_id, item_id, batch_id).
   - Validates source_type whitelist (FR03.26).
   - Validates from_status / to_status against StockStatusTransition.
   - Asserts `available_qty + delta >= 0` (FR03.55) — else raises NegativeBalanceError + writes StockException.
   - Inserts immutable StockLedger row.
   - Triggers debounced dashboard refresh (transaction.on_commit + Redis 60s lock).
   - Advances WarehouseInventoryState if needed (ZERO_BALANCE → ... → INVENTORY_ACTIVE on first OB post).
   - Emits InventoryAuditLog row.
   - Returns the StockLedger row.

6. SEPARATE SELECTOR FAMILIES — DASHBOARD vs OPERATIONAL:
   `v_inventory_dashboard` (materialized view) is for reporting/dashboard reads ONLY. Operational selectors (compute_available, compute_status_balance, assert_warehouse_inventory_active, assert_available_for_reservation, assert_no_negative_balance) MUST NOT query the materialized view. They read direct ledger aggregation OR `inventory_balance_aggregate` if the Day 9 perf-test triggers the fallback. CI test asserts no operational selector imports the dashboard view.

7. SEGREGATION OF DUTIES (FR03.63, BR01.15):
   `services/sod.py.assert_different_actor(actor_id, originator_id, action)` raises SegregationOfDutyError when actor == originator. Called by every approve/post endpoint.

8. IDEMPOTENCY ON CRITICAL WRITES:
   Approve/post endpoints accept `Idempotency-Key` header. SHA256(actor + endpoint + key) stored in StockIdempotency for 24h. Replay returns the original response without re-running side effects. Required for /opening-balances/{id}/approve and /post.

9. RATE LIMITS (Redis-backed in prod, LocMemCache only in single-developer local):
   inventory-read 120/min, inventory-write 40/min, inventory-workflow 15/min, inventory-high-risk 10/min, inventory-bulk 5/min. Plus per-tenant per-day cap of INVENTORY_BULK_DAILY_LINE_CAP (default 50000) on bulk OB line import.

10. TENANT SCOPING — every endpoint:
    Uses `replenishment.services.data_access.get_warehouse_ids_for_tenants(principal.membership_tenant_ids)` (or `national.act_cross_tenant` override with audit). Cross-tenant OB approve is OUT of Sprint 1 scope and recorded as a CROSS_TENANT_ACT exception if attempted.

11. NO NEW DEPENDENCIES:
    Supply-chain hold: do NOT install or fetch axios. Do NOT run `npm install` (frontend is out of scope here, but worth noting). For backend, do not add new pip packages without checking with the user first.

12. NO `python manage.py migrate` WITHOUT EXPLICIT USER APPROVAL:
    Settings.py says "DB changes require explicit approval; do not run migrate." Generate migration files with `makemigrations`, but DO NOT run `migrate` against any database without checking in.

13. NO NEW ROLES IN SPRINT 1:
    Per architecture review MF2, do NOT create LOGISTICS_MANAGER or INVENTORY_AUDITOR. Grant the new inventory.* permissions to existing LOGISTICS, EXECUTIVE, SYSTEM_ADMINISTRATOR roles via migration 0005_grant_inventory_perms_to_existing_roles.py.

================================================================================
DAY-BY-DAY DELIVERABLES (DAYS 2 THROUGH 10)
================================================================================

Refer to the plan file's "Backend Sprint 1 Sequencing" section for the full breakdown. Summary:

DAY 2 — Ledger writer + invariants
  Implement:
    backend/inventory/services/ledger.py             — post_entry() chokepoint
    backend/inventory/services/sod.py                — assert_different_actor()
    backend/inventory/services/idempotency.py        — Idempotency-Key store wrapper
    backend/inventory/services/source_types.py       — whitelist helper
    backend/inventory/services/statuses.py           — state-machine validator
    backend/inventory/services/audit.py              — bounded + PII-masked JSON serializer for InventoryAuditLog
    backend/inventory/migrations/0002_immutable_triggers.py
        — RunSQL: PG trigger blocking UPDATE/DELETE on stock_ledger and inventory_audit_log; reversible
  Tests (under backend/inventory/):
    tests_ledger.py                                  — happy path, advisory lock, negative-balance assertion + StockException recorded, status-transition denial, idempotency replay
    tests_audit_immutability.py                      — UPDATE on stock_ledger raises; DELETE raises; same for inventory_audit_log
    tests_sod.py                                     — assert_different_actor raises on equal; allows on different
    tests_audit_serializer.py                        — bounded payload, PII masking, schema validation

DAY 3 — Opening Balance domain
  Implement:
    backend/inventory/services/opening_balance.py    — create_draft, add_lines, edit_lines, submit, approve, post, reject, cancel
        - Use existing replenishment.services.repackaging.uom_conversion lookup for UOM normalization.
        - approve(): SoD check, valuation pipeline (ITEM_UNIT_COST -> CATEGORY_ESTIMATE -> SAGE_DEFERRED_EXECUTIVE_ROUTE), tier-routing.
        - post(): for each line, calls ledger.post_entry(source_type_code='OPENING_BALANCE', ...); transitions WarehouseInventoryState through APPROVED -> POSTED -> INVENTORY_ACTIVE on first post.
  Tests:
    tests_opening_balance.py                         — full happy path; SoD denial; tier routing 500K boundary; reject path returns to DRAFT; cancel; approve idempotency; bulk-line CSV (5000 lines)
    tests_valuation_pipeline.py                     — ITEM_UNIT_COST tier; CATEGORY_ESTIMATE used when line cost missing AND category default exists; SAGE_DEFERRED_EXECUTIVE_ROUTE forces tier elevation regardless of qty; ASSERTION that no input combo can lower tier on missing cost; MANUAL_OVERRIDE exception only on the SAGE_DEFERRED path

DAY 4 — Permissions + role grants
  Modify:
    backend/api/rbac.py                              — append PERM_INVENTORY_* constants (full list in plan); grant to LOGISTICS, EXECUTIVE, SYSTEM_ADMINISTRATOR in _DEV_ROLE_PERMISSION_MAP
  Implement:
    backend/inventory/migrations/0005_grant_inventory_perms_to_existing_roles.py
        — Data migration: insert role_permission rows for the new perms onto existing roles. Idempotent. Reversible.

DAY 5 — Read-side selectors + materialized view + warehouse-state seed + cutover
  Implement:
    backend/inventory/selectors.py                   — TWO selector families:
        Dashboard/reporting: inventory_dashboard, warehouse_drilldown, item_drilldown, stock_health_indicator, provenance_timeline
        Operational: compute_available, compute_status_balance, assert_warehouse_inventory_active, assert_available_for_reservation, assert_no_negative_balance
        Operational selectors read direct ledger aggregation; never v_inventory_dashboard.
    backend/inventory/services/expiry.py             — 90/60/30/7-day scan helper
    backend/inventory/management/commands/expire_stock_scan.py
    backend/inventory/migrations/0003_seed_lookups.py  — data migration: 10 source types, 14 statuses, full StockStatusTransition pair list, variance/writeoff/quarantine reason codes, item_category_default_cost stub rows
    backend/inventory/migrations/0004_dashboard_view.py
        — RunSQL: CREATE MATERIALIZED VIEW v_inventory_dashboard (per plan) + UNIQUE INDEX; reversible
    backend/inventory/migrations/0006_seed_warehouse_states.py
        — Data migration: insert WarehouseInventoryState(state_code='ZERO_BALANCE') for every legacy warehouse; idempotent; reversible
    backend/masterdata/services/data_access.py       — append 7 entries to TABLE_REGISTRY: stock_source_type, stock_status, variance_reason_code, writeoff_reason_code, quarantine_reason_code, count_threshold, uom_conversion. Edit-guard SYSTEM_ADMINISTRATOR.
  CUTOVER (touches shared paths — be careful):
    backend/replenishment/services/data_access.py    — REWIRE warehouse-stock read functions to call inventory.selectors.compute_available() and inventory.selectors.inventory_dashboard() instead of querying legacy `inventory` table. Add a top-of-file docstring declaring the zero-balance cutover model.
    backend/operations/views.py (and wherever dispatch availability is checked) — replace legacy availability check with inventory.selectors.compute_available(); return 403 with 'Warehouse not yet onboarded — Opening Balance required' when WarehouseInventoryState.state_code != 'INVENTORY_ACTIVE'.
  Tests:
    tests_selectors.py                               — tenant scoping; FEFO/FIFO ordering; stock-health GREEN/AMBER/RED
    tests_selectors_separation.py                    — static-analysis grep + runtime test confirming operational selectors do not query v_inventory_dashboard
    tests_warehouse_state.py                         — ZERO_BALANCE on init; transitions through OPENING_BALANCE_DRAFT, PENDING_APPROVAL, APPROVED, POSTED, INVENTORY_ACTIVE; idempotent migration

DAY 6 — Read API endpoints
  Implement (backend/inventory/views.py + urls.py):
    GET  /api/v1/inventory/dashboard/
    GET  /api/v1/inventory/dashboard/by-warehouse/<int:id>/
    GET  /api/v1/inventory/dashboard/by-item/<int:id>/
    GET  /api/v1/inventory/items/<int:id>/provenance/
    GET  /api/v1/inventory/exceptions/
    POST /api/v1/inventory/exceptions/<int:id>/resolve/
    GET  /api/v1/inventory/ledger/
    GET  /api/v1/inventory/ledger/<int:id>/
    GET  /api/v1/inventory/source-types/
    GET  /api/v1/inventory/stock-statuses/
    GET  /api/v1/inventory/warehouses/
    GET  /api/v1/inventory/warehouses/<int:id>/state/
    GET  /api/v1/inventory/opening-balances/
    GET  /api/v1/inventory/opening-balances/<int:id>/
    GET  /api/v1/inventory/opening-balances/<int:id>/lines/
    GET  /api/v1/inventory/reservations/
  Each endpoint:
    - Authenticated (Principal resolved by existing KeycloakJWTAuthentication / LegacyCompatAuthentication).
    - InventoryPermission(required_permission=...).
    - Throttled (read 120/min default).
    - Tenant-scoped (get_warehouse_ids_for_tenants).
    - Whitelisted order_by columns; _parse_positive_int / _parse_optional_datetime for validation.
  Tests:
    tests_views_read.py                              — 200/400/403/404/429; Retry-After header; IDOR cross-tenant 403

DAY 7 — Write/workflow API endpoints
  Implement:
    POST  /api/v1/inventory/opening-balances/                          — create
    PATCH /api/v1/inventory/opening-balances/<int:id>/                 — edit DRAFT
    POST  /api/v1/inventory/opening-balances/<int:id>/submit/
    POST  /api/v1/inventory/opening-balances/<int:id>/approve/         — Idempotency-Key required
    POST  /api/v1/inventory/opening-balances/<int:id>/post/            — Idempotency-Key required
    POST  /api/v1/inventory/opening-balances/<int:id>/reject/
    POST  /api/v1/inventory/opening-balances/<int:id>/cancel/
    POST  /api/v1/inventory/opening-balances/<int:id>/lines/
    PATCH /api/v1/inventory/opening-balances/<int:id>/lines/<int:lid>/
    DELETE /api/v1/inventory/opening-balances/<int:id>/lines/<int:lid>/
    POST  /api/v1/inventory/opening-balances/<int:id>/import-lines/    — bulk CSV (5/min, 5000 lines/OB cap, 50000 lines/tenant/day cap)
    POST  /api/v1/inventory/reservations/
    POST  /api/v1/inventory/reservations/<int:id>/release/
    POST  /api/v1/inventory/picking/recommend/
    POST  /api/v1/inventory/picking/confirm/                           — Idempotency-Key required
    POST  /api/v1/inventory/evidence/                                  — multipart upload, hash + size cap
    GET   /api/v1/inventory/evidence/<int:id>/
    DELETE /api/v1/inventory/evidence/<int:id>/                        — admin only
  Tests:
    tests_views_write.py                             — full E2E approve→post happy path; SoD denial; double-allocation prevention; pick-confirm verifies reservation match; evidence hash dedup; idempotency replay

DAY 8 — Cutover tooling
  Implement (under backend/inventory/management/commands/):
    initialize_warehouse_states.py                   — idempotent; one ZERO_BALANCE row per legacy warehouse
    export_legacy_inventory_snapshot.py              — CSV export with mandatory "REFERENCE ONLY — DMIS does not treat these values as truth" banner in the file. Cannot be imported back as OB lines.
    detect_inventory_exceptions.py                   — Sprint 1 detector: OB pending-approval overdue (>24h), expired allocation attempt, negative-balance attempt, manual override, warehouse-stuck-in-zero-balance >7 days
    seed_inventory_lookups.py                        — idempotent re-seed wrapper around 0003

DAY 9 — Hardening + perf decision + arch review
  - EXPLAIN ANALYZE on dashboard, drilldown, ledger list, operational availability queries under realistic data volumes.
  - PERF DECISION (CRITICAL):
      If ledger-direct aggregation (compute_available et al.) p95 < 100ms at 200 concurrent users (NFR03.04): keep ledger-direct.
      Else: activate inventory_balance_aggregate fallback.
        - Apply migration 0007_inventory_balance_aggregate.py (additive, reversible).
        - Run `manage.py rebuild_inventory_balance_aggregate` (idempotent).
        - Update operational selectors to read from the aggregate.
      Decision recorded in the implementation brief with EXPLAIN ANALYZE evidence.
  - Static-analysis grep: confirm no operational selector imports v_inventory_dashboard.
  - Idempotency-Key enforcement on all approve/post endpoints (reject if missing for high-risk ops).
  - Run mandatory architecture review (.agents/skills/system-architecture-review/SKILL.md). Resolve all must-fix items before proceeding.
  - Run backend-review-project skill for security/quality pass.
  - Threat-model walkthrough for new endpoints (IDOR, SoD bypass, ledger forgery, bulk-import injection).

DAY 10 — Smoke + handoff
  - python manage.py test inventory --verbosity=2
  - python manage.py test replenishment operations masterdata --verbosity=2  (regression)
  - End-to-end smoke against staging-like Postgres with backfilled data.
  - Hand off API contract to frontend (already in flight from Day 5).
  - Documentation updates:
      docs/adr/system_application_architecture.md   — add inventory module section + zero-balance cutover statement + ledger-as-source-of-truth
      docs/security/CONTROLS_MATRIX.md              — add TEN-05 entry recording zero-balance cutover; update IAM-04, TEN-01, API-05 rows
      docs/security/THREAT_MODEL.md                 — appendix on EP-03 threats (ledger forgery, OB bulk-import injection, SoD bypass, cross-tenant query, mass bulk-import DoS)
      docs/implementation/sprint_11_ep03_inventory_foundation.md (NEW)  — implementation brief recording the perf decision + rollback runbook

================================================================================
VERIFICATION CRITERIA (must pass before sign-off)
================================================================================

- python manage.py migrate --check passes (after generating migrations; do not run migrate without user approval)
- python manage.py test inventory --verbosity=2 — all green
- python manage.py test replenishment operations masterdata --verbosity=2 — all green (regression)
- Zero-balance proof:
    - After applying 0006_seed_warehouse_states, every WarehouseInventoryState row has state_code='ZERO_BALANCE'
    - Legacy `inventory` table is unchanged after a successful OB post
    - Replenishment dashboard returns zero for ZERO_BALANCE warehouses
    - Operations dispatch returns 403 for ZERO_BALANCE warehouses
- Reject path proof: OPENING_BALANCE_DRAFT -> PENDING_APPROVAL -> OPENING_BALANCE_DRAFT (with rejection reason captured)
- SoD proof: same-user approve denied with 403
- Idempotency proof: identical Idempotency-Key returns same response without duplicate ledger row
- Negative-balance proof: post that would drive available <0 returns 409 + records StockException
- Valuation proof: ITEM_UNIT_COST and CATEGORY_ESTIMATE compute tiers correctly; SAGE_DEFERRED_EXECUTIVE_ROUTE always routes to Executive regardless of qty; no input combo can lower tier when cost is missing
- Selector separation proof: static-analysis grep over inventory/services/, inventory/selectors.py, inventory/views.py confirms no operational selector imports v_inventory_dashboard; runtime test simulates stale view and proves operational reads still correct
- Architecture review returns Aligned
- No new dependencies added; supply-chain hold respected (no axios pulled)

================================================================================
HOW TO RUN BACKEND LOCALLY
================================================================================

cd backend
# Virtual env: .venv\Scripts\Activate.ps1 (Windows) or .venv/bin/activate (Unix)

# Required env vars for local-harness mode:
DJANGO_USE_SQLITE=1
DJANGO_ALLOW_SQLITE=1
DMIS_RUNTIME_ENV=local-harness
DEV_AUTH_ENABLED=1
LOCAL_AUTH_HARNESS_ENABLED=1
DJANGO_DEBUG=1

python manage.py check
python manage.py makemigrations inventory --dry-run     # safe; doesn't write
python manage.py makemigrations inventory                # writes migration file
python manage.py test inventory --verbosity=2

# DO NOT run `python manage.py migrate` without explicit user approval.

================================================================================
PR / GIT EXPECTATIONS
================================================================================

- One PR per day's work (Day 2 PR, Day 3 PR, etc.) OR one PR for the whole sprint, whichever the user prefers. Confirm with user.
- Commit messages: imperative; reference FR ids when relevant. Example:
    "Implement inventory.services.ledger.post_entry chokepoint (FR03.27, .55, .73)"
- Every PR includes:
    - Code changes
    - Migrations (no `migrate` run)
    - Tests with the FR ids in test names
    - Updated docs if applicable
    - PR body: scope, FR coverage, verification evidence, deferred items

================================================================================
WHEN TO ESCALATE
================================================================================

Stop and ask the user before:
- Running `python manage.py migrate` against any database
- Adding new pip dependencies
- Modifying any file in `backend/replenishment/` or `backend/operations/` beyond the explicitly listed cutover edits in Day 5
- Changing the canonical RBAC role catalog (creating new roles)
- Touching `backend/api/rbac.py` _DEV_ROLE_PERMISSION_MAP in any way besides the explicitly listed Day 4 grants
- Removing or replacing the existing `backend/replenishment/services/repackaging.py` (extend, do not replace)
- Activating the inventory_balance_aggregate fallback (Day 9 decision must be recorded)

End of brief.
```
