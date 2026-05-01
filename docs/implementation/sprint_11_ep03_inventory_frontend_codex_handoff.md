# DMIS EP-03 — Sprint 1 Frontend: Codex Implementation Handoff

> **Use this prompt verbatim with Codex / GPT-5.4 (or equivalent autonomous coding agent).**
> The receiving model has no prior conversation context — everything it needs is referenced inline below.
>
> **Required reading before any code is written:**
> 1. [`docs/implementation/sprint_11_ep03_inventory_implementation_plan.md`](sprint_11_ep03_inventory_implementation_plan.md) — the approved EP-03 plan (authoritative)
> 2. `.claude/CLAUDE.md` — project guardrails, supply-chain hold, frontend rules, IDOR rules
> 3. `frontend/AGENTS.md` — frontend-local rules (auth, route guards, schematics)
> 4. **Approved Claude Design wireframes** — provided separately by the user once design is accepted (folder of HTML mockups under e.g. `docs/wireframes/sprint_11_ep03/...`)
> 5. **Backend API contract** — produced by the backend Codex thread (see `sprint_11_ep03_inventory_backend_codex_handoff.md`); the URL surface section of the plan is the source of truth
> 6. `docs/security/SECURITY_ARCHITECTURE.md` (frontend-relevant sections), `docs/implementation/production_readiness_checklist.md` (FE checklist items)

---

## Begin handoff prompt

```
You are implementing the FRONTEND for DMIS EP-03 (Stockpile/Warehouse Operations) Sprint 1, the inventory & stockpile UI for Jamaica's ODPEM disaster response system. The complete design is the approved plan at:

  docs/implementation/sprint_11_ep03_inventory_implementation_plan.md

Read that plan in full BEFORE writing any code. It is the authoritative source of truth for: scope (60 Must-Have FRs across Phase 1+2 minus Sage minus location hierarchy), URL surface, valuation pipeline, zero-balance cutover, accessibility expectations, mobile-first behavior.

Working directory: C:/Users/wbowe/OneDrive/Desktop/project/DMIS_UpdatedVersion/.claude/worktrees/intelligent-brown-926f56

Approved wireframes: see the folder the user points you to (the Claude Design output). Use them as the visual contract — every Sprint 1 page below has a corresponding HTML mockup. If a wireframe is unclear, escalate; do not invent.

Backend API contract: see the URL surface in the plan and the backend handoff prompt at docs/implementation/sprint_11_ep03_inventory_backend_codex_handoff.md. The backend lands by end of Day 7; you can begin from Day 5 against stub responses, then switch to the real backend.

================================================================================
NON-NEGOTIABLE GUARDRAILS
================================================================================

1. SUPPLY-CHAIN HOLD:
   - Do NOT run `npm install` or `npm.cmd install` (the project tracks deps via existing package-lock.json).
   - Do NOT pull `axios` or any artifact sourced from axios. The HttpClient pattern uses Angular's built-in HttpClient.
   - Do NOT add new npm dependencies without checking with the user first. Reuse existing Angular Material modules.

2. NO REGRESSION:
   - The current local codebase is the authoritative implementation baseline.
   - Reuse the existing patterns: standalone components, signals where appropriate, OnPush change detection, reactive forms, Material modules.
   - Reuse existing shared components (DmisStepTrackerComponent, DmisSkeletonLoaderComponent, DmisEmptyStateComponent, DmisConfirmDialogComponent, DmisNotificationService).
   - Reuse existing master-data config-driven CRUD pattern for all 7 new lookup tables.

3. AUTH IS BACKEND-AUTHORITATIVE:
   - Frontend route guards are UX only.
   - Use existing appAccessGuard with new accessKey values (one per lazy route — see plan).
   - The dev-user interceptor (devUserInterceptor) adds X-DMIS-Local-User header in local-harness mode only. Do not introduce a new interceptor for inventory.
   - All authenticated requests rely on the existing core/ patterns; do not roll your own.

4. ZERO-BALANCE CUTOVER UI BEHAVIOR:
   - The Inventory Dashboard renders an explicit "Pending Opening Balance" badge on every warehouse whose WarehouseInventoryState is not INVENTORY_ACTIVE.
   - The Stock Status Dashboard (existing replenishment dashboard) is updated to render a "Pending Opening Balance" pill for ZERO_BALANCE warehouses and to exclude them from burn-rate / time-to-stockout calculations. This is a small targeted edit; preserve existing component formats and tests.
   - The OB Wizard does NOT offer "auto-populate from legacy". A small link "Download legacy inventory snapshot (REFERENCE ONLY)" is present.

5. VALUATION PIPELINE — MISSING UNIT COST NEVER LOWERS APPROVAL TIER:
   - The OB Wizard Step 4 shows a Valuation Basis panel: ITEM_UNIT_COST | CATEGORY_ESTIMATE | SAGE_DEFERRED_EXECUTIVE_ROUTE.
   - When SAGE_DEFERRED_EXECUTIVE_ROUTE is in effect, the tier preview banner reads "Approval route elevated — Sage integration deferred. Routes to Director PEOD / Executive."
   - The OB Detail page shows the Valuation Basis to the approver prominently.
   - The Approval Queue row shows a basis chip and an amber "Elevated route — Sage deferred" pill when applicable.
   - Frontend does NOT compute the tier independently; trust the backend response.

6. ACCESSIBILITY (WCAG 2.1 AA):
   - Status colors are paired with text + icon; never color alone.
   - Visible focus rings; keyboard navigability; aria-labels on icon buttons; aria-live="polite" on toasts.
   - Loading states use skeletons (DmisSkeletonLoaderComponent), not bare spinners.
   - Empty states use DmisEmptyStateComponent with helpful primary action.

7. INPUT VALIDATION (mirror backend):
   - Every <input> and <textarea> has a maxlength matching the backend DB column.
   - FormControls have Validators.maxLength(n) AND template `maxlength` attribute.
   - Required: Validators.required + `required` attribute.
   - Numerics: Validators.min/max + type="number" with min/max attributes.
   - Trim text before submit (reason, notes, comments).
   - No innerHTML bindings with user content; rely on Angular interpolation.

8. IDEMPOTENCY-KEY:
   - For approve and post calls (high-risk endpoints), the service generates a UUID via crypto.randomUUID() and persists it on the OB record in the component state.
   - The same UUID is sent on retry; the backend returns the original response.

9. OFFLINE/SLOW NETWORK:
   - Persistent banner when offline.
   - OB Wizard Step 1 (header) and Step 2 (lines) auto-save server-side on each blur via PATCH (NOT localStorage). The "draft" is a server-side OB row in DRAFT status.
   - Step 3 (evidence) and Step 4 (review) are server-state-only.

10. NO INVENTED API ENDPOINTS:
    - Use only the endpoints defined in the plan's URL surface section.
    - If a wireframe implies an endpoint that does not exist in the plan, escalate.

================================================================================
DELIVERABLES — FRONTEND
================================================================================

Create new feature folder: frontend/src/app/inventory/

----------
ROUTES (frontend/src/app/inventory/inventory.routes.ts)
----------

Lazy-loaded child routes registered in frontend/src/app/app.routes.ts under /inventory. Each route uses appAccessGuard with the accessKey as listed.

  /inventory/dashboard                                      accessKey: inventory.view
  /inventory/items/:id/provenance                           accessKey: inventory.provenance.view
  /inventory/exceptions                                     accessKey: inventory.exception.view
  /inventory/opening-balance/list                           accessKey: inventory.view
  /inventory/opening-balance/wizard                         accessKey: inventory.opening_balance.create
  /inventory/opening-balance/:id/detail                     accessKey: inventory.view
  /inventory/opening-balance/approval-queue                 accessKey: inventory.opening_balance.approve
  /inventory/pick-confirm                                   accessKey: inventory.pick.confirm
  /inventory/reservations                                   accessKey: inventory.reservation.view

Sidenav entry under frontend/src/app/layout/ adds "Inventory" with accessKey 'inventory.view'.

----------
SERVICES (frontend/src/app/inventory/services/)
----------

Use HttpClient (NOT axios). Mirror the pattern in frontend/src/app/replenishment/services/replenishment.service.ts.

  inventory.service.ts                  — dashboard, drilldowns, source-types, stock-statuses, warehouse-state list/get, exceptions
  ledger.service.ts                     — list ledger, get ledger
  provenance.service.ts                 — item provenance timeline
  opening-balance.service.ts            — full CRUD + workflow actions (submit, approve, reject, post, cancel; passes Idempotency-Key)
  reservation.service.ts                — list / create / release
  picking.service.ts                    — recommend / confirm
  evidence.service.ts                   — upload (multipart) / get / delete

----------
MODELS (frontend/src/app/inventory/models/)
----------

  stock-source-type.enum.ts             — DONATION_RECEIPT, PROCUREMENT_RECEIPT, ..., DATA_IMPORT
  stock-status.enum.ts                  — AVAILABLE, RESERVED, ..., DISPOSED
  warehouse-inventory-state.enum.ts     — ZERO_BALANCE, OPENING_BALANCE_DRAFT, ..., INVENTORY_ACTIVE
  valuation-basis.enum.ts               — ITEM_UNIT_COST, CATEGORY_ESTIMATE, SAGE_DEFERRED_EXECUTIVE_ROUTE
  approval-tier.enum.ts                 — LOGISTICS_LE_500K, EXECUTIVE_500K_2M, DEPUTY_DG_2M_10M, DG_GT_10M
  stock-ledger.model.ts
  opening-balance.model.ts
  opening-balance-line.model.ts
  stock-reservation.model.ts
  stock-evidence.model.ts
  stock-exception.model.ts
  exception-type.enum.ts                — NEGATIVE_BALANCE_ATTEMPT, EXPIRED_ALLOC_ATTEMPT, MANUAL_OVERRIDE, OB_PENDING_APPROVAL_OVERDUE, WAREHOUSE_STUCK_IN_ZERO_BALANCE, ...

----------
SHARED COMPONENTS (frontend/src/app/inventory/shared/)
----------

Each is a standalone component using Material primitives. Reuse existing component formats from frontend/src/app/shared/.

  inventory-status-chip.component.ts     — tone {available, reserved, quarantine, damaged, expired, hold, in_transit, picked, staged, issued, returned, disposed, unknown}; icon + label always
  warehouse-state-badge.component.ts     — ZERO_BALANCE / OPENING_BALANCE_DRAFT / PENDING_APPROVAL / APPROVED / POSTED / INVENTORY_ACTIVE
  severity-badge.component.ts            — GREEN / AMBER / RED with text + icon (FR03.16)
  expiry-countdown.component.ts          — pill with days remaining; tone derived from 90/60/30/7-day buckets (FR03.07)
  freshness-pill.component.ts            — HIGH/MEDIUM/LOW data-freshness pill
  evidence-uploader.component.ts         — multi-file drop zone; thumbnail + filename + size + hash; size cap from settings; hash computed client-side via SubtleCrypto
  evidence-thumbnail.component.ts        — preview of a single evidence item
  batch-picker.component.ts              — search-as-you-type batch selector
  location-picker.component.ts           — flat location dropdown (hierarchy deferred to Sprint 2)
  quantity-input.component.ts            — uom-aware numeric input (calls inventory.service for conversion factor preview)
  valuation-basis-panel.component.ts     — shows ITEM_UNIT_COST / CATEGORY_ESTIMATE / SAGE_DEFERRED_EXECUTIVE_ROUTE chip + tier preview banner
  kpi-card.component.ts                  — used by the dashboard
  pending-onboarding-banner.component.ts — top-of-page banner when any warehouse not INVENTORY_ACTIVE

----------
PAGES (frontend/src/app/inventory/pages/)
----------

  inventory-dashboard/                   — KPI cards, low-stock, expiring-soon, exceptions, warehouse onboarding status (FR03.01-04, .07, .13, .16, .80)
  item-provenance/                       — read-only timeline (FR03.20)
  exception-dashboard/                   — list + resolve (FR03.80)
  opening-balance/
    ob-list/                             — tabs: Drafts, Pending Approval, Approved, Posted, Rejected, Cancelled
    ob-wizard/                           — 4-step wizard using DmisStepTrackerComponent (FR03.29, .30, .67, .74)
        step1-header/
        step2-lines/                     — manual + CSV tabs; NO backfill option
        step3-evidence/                  — required evidence upload
        step4-review/                    — Valuation Basis panel + tier preview + 3 action choices
    ob-detail/                           — header + Valuation Basis panel + tabs (Lines, Evidence, History, Audit) + conditional action bar (DRAFT/PENDING_APPROVAL/APPROVED/POSTED/REJECTED/CANCELLED)
    ob-approval-queue/                   — manager view; basis chips; "Elevated route — Sage deferred" pill where applicable
  pick-confirm/                          — mobile-first picker workspace (FR03.53, .54)
  reservations/                          — read-only list (FR03.51, .52)

----------
MASTER-DATA CONFIGS (frontend/src/app/master-data/models/table-configs/)
----------

Add 7 new MasterTableConfig files following the existing pattern. Register them in ALL_TABLE_CONFIGS (index.ts) and add routes in frontend/src/app/master-data/master-data.routes.ts.

  stock-source-type.config.ts
  stock-status.config.ts
  variance-reason-code.config.ts
  writeoff-reason-code.config.ts
  quarantine-reason-code.config.ts
  count-threshold.config.ts
  uom-conversion.config.ts

Each config:
- tableKey, displayName, icon, pkField, routePath, formMode (page or dialog).
- columns with type (text/status/number), sortable, hideMobile, toneMap for status colors.
- formFields with field, label, type, required, maxLength matching backend, pattern, placeholder, group, hint.

Edit-guard: SYSTEM_ADMINISTRATOR (masterdata.advanced.edit) for all 7.

----------
EXISTING PATTERNS TO REUSE (DO NOT REIMPLEMENT)
----------

  frontend/src/app/shared/dmis-step-tracker/dmis-step-tracker.component.ts  — the OB wizard tracker
  frontend/src/app/shared/* — skeleton loader, empty state, confirm dialog, notification service
  frontend/src/app/operations/shared/operations-theme.scss                  — design tokens (--ops-*)
  frontend/src/app/master-data/services/master-data.service.ts              — generic CRUD client for the 7 lookup tables
  frontend/src/app/replenishment/services/replenishment.service.ts          — HttpClient pattern reference
  frontend/src/app/core/app-access.service.ts                               — register inventory.* accessKey values

----------
EXISTING FILES TO MODIFY (touch shared paths carefully)
----------

  frontend/src/app/app.routes.ts                — add /inventory lazy route
  frontend/src/app/layout/                      — sidenav entry "Inventory" with accessKey 'inventory.view'
  frontend/src/app/core/app-access.service.ts   — register all inventory.* access keys
  frontend/src/app/master-data/master-data.routes.ts — register 7 new lookup routes
  frontend/src/app/master-data/models/table-configs/index.ts — export new configs
  frontend/src/app/replenishment/stock-status-dashboard/stock-status-dashboard.component.ts (and template) — render "Pending Opening Balance" pill for ZERO_BALANCE warehouses; exclude them from burn-rate / time-to-stockout (small targeted edit; preserve existing tests)

================================================================================
TESTING (Karma + Jasmine)
================================================================================

For each service:
  - Mock HttpClient via HttpClientTestingModule.
  - Verify request URL, method, body, headers (including Idempotency-Key on approve/post).

For each page component:
  - Loading, empty, error, success states render correctly.
  - Forms: required validators, maxLength validators, trim before submit.
  - SoD UI: hide Approve when current user == requested_by_id; show greyed-out hint.
  - Tier-elevation banner appears when valuation_basis === 'SAGE_DEFERRED_EXECUTIVE_ROUTE'.
  - Idempotency-Key uses crypto.randomUUID(); same key on retry.

Cross-cutting:
  - IDOR negative test: simulate principal switching tenants; verify 403 toast and no UI leakage.
  - Route-guard test: deny route without inventory.view; redirect to no-access page.
  - a11y check via Angular ESLint template rules + axe (existing project setup).

Run via:
  cd frontend
  npm.cmd start    # ng serve, proxies /api to localhost:8001
  npm.cmd test -- --watch=false
  npm.cmd run lint
  npm.cmd run build

Do NOT run `npm install` or `npm.cmd install`. Do NOT pull axios or any artifact sourced from axios.

================================================================================
DAY-BY-DAY (overlapping with backend, starting Day 5)
================================================================================

Day 5–6 — Scaffolding + Inventory Dashboard
  - inventory module skeleton + services + models + shared components
  - Dashboard page (KPI cards, filters, drill-down link, "Pending Opening Balance" badges, warehouse onboarding status section)
  - Sidenav + access-key registration
  - Master-data 7 configs

Day 6–7 — Item Provenance + Exception Dashboard
  - Provenance timeline page
  - Exception dashboard list + resolve

Day 7–9 — Opening Balance Wizard + Detail + Approval Queue
  - 4-step wizard with DmisStepTrackerComponent
  - Detail page with Valuation Basis panel and tabs
  - Approval queue with basis chips and tier-elevation pills

Day 9–10 — Picking + Reservations + tightening
  - Pick-confirm workspace (mobile-first)
  - Reservations read-only list
  - Update existing replenishment Stock Status Dashboard to render "Pending Opening Balance" pill for ZERO_BALANCE warehouses
  - Smoke test full flow against backend; lint + build + tests green

================================================================================
VERIFICATION CRITERIA
================================================================================

- npm.cmd run lint — clean
- npm.cmd run build — clean
- npm.cmd test -- --watch=false — all green
- Manual smoke (after backend is up):
    /inventory/dashboard — KPIs render; warehouse onboarding section shows ZERO_BALANCE warehouses with "Pending Opening Balance" badge; filters work; drill-down navigates
    /inventory/opening-balance/wizard — full 4-step flow; submit creates DRAFT; approve as different user; post; verify warehouse transitions to INVENTORY_ACTIVE in the dashboard
    /inventory/items/9001/provenance — timeline shows OPENING_BALANCE entry from above
    /inventory/exceptions — empty initially; appears after triggering pending-approval-overdue or attempting to post negative
    /master-data/stock-source-type — 10 rows visible; SYSTEM_ADMINISTRATOR can edit; other roles cannot
    Stock Status Dashboard (replenishment) — ZERO_BALANCE warehouses show "Pending Opening Balance" pill and are excluded from burn-rate
    Valuation Basis: when an OB has missing unit cost AND no category default, Step 4 shows the SAGE_DEFERRED_EXECUTIVE_ROUTE option, the tier preview reads "Routes to Director PEOD / Executive", and the Detail / Approval Queue render the elevated-route pill
    SoD: same user cannot see Approve button on OB they created
    Idempotency: clicking Post twice in rapid succession does not create duplicate entries; the response is identical

================================================================================
WHEN TO ESCALATE
================================================================================

Stop and ask the user before:
- Running `npm install` / `npm.cmd install`
- Adding new npm dependencies
- Pulling axios or any artifact sourced from axios
- Modifying any file in `frontend/src/app/operations/`, `frontend/src/app/replenishment/` (other than the explicit Stock Status Dashboard pill edit), or `frontend/src/app/core/` (other than registering new access keys)
- Replacing or duplicating shared components — extend the existing ones
- Changing the design tokens (--ops-*) — reuse only
- Inventing API endpoints not listed in the plan's URL surface
- Implementing UI for any of the 9 deferred source types (GRN, count, write-off, quarantine, return, reversal, transformation, import, adjustment) — Sprint 1 ships only Opening Balance + read-only dashboards/provenance/exceptions/picking/reservations

End of brief.
```
