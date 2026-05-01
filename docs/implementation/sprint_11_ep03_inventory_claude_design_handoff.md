# DMIS EP-03 — Sprint 1 Inventory UI: Claude Design Wireframe Handoff

> **Use this prompt verbatim in Claude Design (or any LLM-driven wireframe generator).**
> The receiving model has no prior context — everything it needs is in this file.
>
> **Authoritative reference plan (do not paste into Claude Design — for human reviewers only):**
> [`docs/implementation/sprint_11_ep03_inventory_implementation_plan.md`](sprint_11_ep03_inventory_implementation_plan.md)

---

## Begin handoff prompt

```
You are designing low-fidelity wireframes for the DMIS EP-03 Inventory & Stockpile module — Sprint 1, the Disaster Management Information System used by Jamaica's Office of Disaster Preparedness and Emergency Management (ODPEM). Output: HTML mockups with inline CSS, one file per page, mobile-first, fully accessible (WCAG 2.1 AA).

================================================================================
PROJECT CONTEXT
================================================================================

DMIS is a logistics command system for hurricane response. Three modules: Replenishment (stock planning), Operations (relief request fulfillment), Master Data (reference catalogs). EP-03 (Inventory) is being added now to make stock movement trustworthy.

CUTOVER MODEL — DESIGN MUST REFLECT THIS:

DMIS inventory begins at ZERO. The system does NOT migrate or backfill from any legacy inventory data. To make a warehouse operational, an authorized warehouse user must perform a physical stock count, capture it in an Opening Balance draft (with evidence: count sheets, photos, sign-off), submit for approval, and once posted, the warehouse transitions to INVENTORY_ACTIVE. Until then, the warehouse shows zero stock everywhere and is excluded from operational reads (dashboard, replenishment burn-rate, dispatch).

The wireframes must depict:
- An empty inventory dashboard for newly-onboarded warehouses with a clear "Pending Opening Balance" state.
- The Opening Balance lifecycle states:
    ZERO_BALANCE -> OPENING_BALANCE_DRAFT -> PENDING_APPROVAL -> APPROVED -> POSTED -> INVENTORY_ACTIVE
    -> AVAILABLE / QUARANTINE / DAMAGED / EXPIRED / HOLD
- The full OB workflow: Start -> All Warehouses Start at Zero Inventory -> Warehouse User Performs Physical Stock Count -> Create OB Draft -> Enter Item, Quantity, UOM, Batch, Expiry, Condition, Location -> Attach Evidence (Count Sheet / Photos / Sign-off) -> Submit for Approval -> Approver Reviews -> (Approve OR Reject/Return) -> Opening Balance Approved -> Post -> Create Immutable Stock Ledger Entries -> Update Ledger-Derived Inventory Balance -> Warehouse Inventory Becomes Active -> Stock Status (AVAILABLE -> Can Be Reserved/Picked/Dispatched OR QUARANTINE/DAMAGED/EXPIRED/HOLD -> Blocked from Allocation) -> Dashboard / COP / Replenishment Reads Ledger Balance.

PRIMARY USER: "Kemar" — Logistics Manager. Field-first mindset. Often on a phone or tablet during hurricane response, sometimes outdoors, sometimes with poor connectivity. Low tolerance for messy data. Phrase he uses: "If it's not logged, it didn't happen." Design test for every screen: "Could Kemar use this on a tablet, in a wind-blown shelter, with one hand?" If no, simplify it.

SECONDARY USERS:
- Logistics Officer (creates opening balances, picks stock, runs the physical count).
- Logistics Manager (approves opening balances ≤ JMD 500K, posts to ledger).
- Senior Director PEOD (approves JMD 500K–2M tier, and any SAGE_DEFERRED_EXECUTIVE_ROUTE).
- System Administrator (configures source types, statuses, reason codes, UOM conversions).
- Inventory Auditor (read-only).

NON-NEGOTIABLES:
1. No auto-actions. System recommends; humans approve.
2. Audit everything. Every state change shows who/when/why.
3. Data freshness must be visible. HIGH < 2h, MEDIUM 2–6h, LOW > 6h. Show a freshness pill on every dashboard.
4. Strict inbound: only DISPATCHED transfers, IN-TRANSIT donations, SHIPPED procurement count toward inbound.
5. Mobile-friendly: cards stack vertically; tables become card-lists below 768px.
6. Status colors must always have a text label and an icon — never color alone (a11y).
7. Missing unit cost on an OB line NEVER lowers the approval tier. The valuation pipeline cascades ITEM_UNIT_COST -> CATEGORY_ESTIMATE -> SAGE_DEFERRED_EXECUTIVE_ROUTE; the third option ELEVATES the route to Director PEOD / Executive.

DESIGN SYSTEM:
- Angular 21 + Angular Material is the implementation target. Wireframes mirror Material primitives but stay low-fi (no fancy gradients).
- Reuse these CSS tokens (real names from the project's operations-theme.scss):
    --ops-font-sans: 'Inter', system-ui, sans-serif (use plain sans-serif in mockups)
    --ops-surface (page background, near-white)
    --ops-section (card background, white)
    --ops-card (interior card, very light grey)
    --ops-ink (primary text, near-black)
    --ops-outline (border, light grey)
    --ops-radius-md: 10px
    --ops-radius-pill: 999px
- Status palette (paired with text + icon, never color alone):
    GREEN (OK): #1F8A4C
    AMBER (WARNING): #C77800
    RED (CRITICAL): #B3261E
    YELLOW (WATCH): #C58D00
    GREY (NEUTRAL): #6E7780
- Typography: page title 1.6–2.2rem clamp, weight 800, tabular-nums for numbers; body 0.95rem.
- Spacing: 8px base unit; cards 16–24px padding; gap-12 between cards.

ACCESSIBILITY:
- WCAG 2.1 AA: 4.5:1 contrast on text; visible focus rings; keyboard-navigable; semantic HTML (<main>, <nav>, <table>); aria-labels on icon buttons; aria-live="polite" on toasts.
- Every status chip: color + icon + visible label.
- Every loading state: skeleton placeholders, not just spinners.
- Every empty state: friendly headline + subtle illustration + helpful primary action.

OFFLINE / SLOW NETWORK PATTERNS:
- Show a persistent banner when offline: "Working offline — changes will sync when connection returns."
- Step 1 (header) and Step 2 (lines) of the OB Wizard auto-save server-side on each blur via PATCH (NOT localStorage). Step 3 (evidence) and Step 4 (review) are server-state-only. The "draft" is a server-side OB row in DRAFT status, not browser-local storage.
- Avoid skeleton screens that flicker; once a card has data it never reverts to skeleton on refetch.

================================================================================
PAGES TO DESIGN (Sprint 1 only)
================================================================================

For each page, produce a single HTML file. Use a thin shell at the top with a left sidebar (collapsible on mobile), a top bar (search + user menu + freshness pill), and a main content area. The shell can be repeated identically across pages.

----------
1) /inventory/dashboard — INVENTORY DASHBOARD (FR03.01–.04, .13, .16, .80 partial)
----------

- Page header: "Inventory Dashboard" + subtitle "Live stock posture across your warehouses". Right side: data freshness pill (HIGH/MEDIUM/LOW) + last refreshed timestamp.
- Filter row: warehouse multiselect, item search, item-category select, status select. Clear filters button.
- Onboarding banner (zero-balance cutover): At top of page, render a contextual banner whenever any warehouse in the user's tenant scope is not yet INVENTORY_ACTIVE. Example: "3 warehouses are pending Opening Balance onboarding. They are not yet contributing to operational stock. Onboard now." Click → opens warehouse-state queue.
- Per-warehouse "Pending Opening Balance" badge in any warehouse-grouping section, with icon and the literal label.
- KPI strip (4 cards): only counts INVENTORY_ACTIVE warehouses. Tooltip on each KPI: "Excludes X warehouses still in ZERO_BALANCE / OPENING_BALANCE_DRAFT / PENDING_APPROVAL".
    Card 1 — Usable Stock (green); shows total qty + delta vs yesterday.
    Card 2 — Reserved Stock (amber).
    Card 3 — Defective Stock (red).
    Card 4 — Expired Stock (red, with "Quarantine required" subtitle).
    Optional fifth card — Total Stock Value (grey, "Sage integration deferred — manual cost basis"); show hint icon.
- Section: "Low Stock Items — Immediate Attention Required" (FR03.13). Card-list. Each card: item name, SKU, current qty / reorder qty, GREEN/AMBER/RED health pill (FR03.16), warehouse, last movement timestamp. Click → drill-down.
- Section: "Expiring Soon (90/60/30/7 days)". Tabbed pill row with 4 buckets, count per bucket. Below: card-list of items in selected bucket; each card shows item, batch, expiry date, days remaining (countdown pill), warehouse, qty.
- Section: "Open Exceptions" (FR03.80, OB-only in Sprint 1). Card-list of pending-approval-overdue OBs, negative-balance attempts, "warehouse-stuck-in-zero-balance >7 days" alerts. Each card has a "Resolve" or "Onboard" button.
- Section: "Warehouse Onboarding Status" — grid showing each warehouse with its current state chip (ZERO_BALANCE | OPENING_BALANCE_DRAFT | PENDING_APPROVAL | APPROVED | POSTED | INVENTORY_ACTIVE), latest OB id link, and "Activated at" date. INVENTORY_ACTIVE warehouses use a green "Active" pill.
- Footer: "Sources counted as inbound: only DISPATCHED transfers, IN-TRANSIT donations, SHIPPED procurement. DMIS inventory begins at zero — only Opening-Balance-posted stock is operational."
- Mobile: KPI cards stack 2x2; sections collapse into accordions.

----------
2) /inventory/items/{id}/provenance — ITEM PROVENANCE TIMELINE (FR03.20)
----------

- Page header: item name + SKU + back link. Filter row: batch dropdown, date range.
- Timeline (vertical, newest at top): each row shows source-type badge (DONATION_RECEIPT / OPENING_BALANCE / etc.), action verb ("Posted as opening balance"), warehouse, qty, batch, status transition (e.g., "→ AVAILABLE"), actor name + ID, timestamp, optional reason text. Click row → side drawer with full ledger entry detail (raw JSON-like fields) + linked evidence thumbnails.
- Empty state: "No movements recorded yet for this item."
- Mobile: timeline becomes vertical card-list.

----------
3) /inventory/opening-balance/list — OPENING BALANCE LIST (FR03.29)
----------

- Page header: "Opening Balances" + primary button "+ New Opening Balance".
- Tabs: Drafts | Pending Approval | Approved | Posted | Rejected | Cancelled.
- Table (becomes card-list on mobile): OB number, warehouse, purpose, line count, total default-uom qty, valuation basis chip, status pill, requested by, submitted at, approved by, posted at. Row click → detail.
- Filter row: warehouse, purpose, requester, date range.
- Bulk actions: select multiple drafts → "Submit selected" (queue-style).

----------
4) /inventory/opening-balance/wizard — OPENING BALANCE WIZARD (FR03.29, .30, .67, .74)
----------

Header banner: "Opening Balance is a controlled physical-count onboarding process. DMIS inventory begins at zero. The values you enter must match the physical stock you have counted on-site."

4 steps with Material-style step tracker:

STEP 1 — Header
    Fields: warehouse (required, dropdown — disabled if user only manages one), purpose (required: GO_LIVE / ONBOARD_WAREHOUSE / MIGRATION), notes (optional textarea, max 500 chars).
    Help text: "Opening balance establishes initial stock by physical count. Auto-population from legacy inventory is not supported."

STEP 2 — Lines
    Two entry modes (tabs): Manual entry | CSV upload.
    Manual: line table with columns: item (autocomplete search), uom (dropdown, with conversion factor preview), qty, batch_no, expiry_date, location (dropdown), initial status (AVAILABLE / QUARANTINE / DAMAGED), unit_cost_estimate (optional), line notes. + Add line, ✕ Delete row, ⚌ Drag handle.
    CSV: drop zone + template download link. Show parse results inline: total rows, invalid rows (with row numbers + error messages), duplicates skipped.
    NO backfill / no auto-populate from legacy. A small link "Download legacy inventory snapshot (REFERENCE ONLY — do not import)" is available so warehouse users have a starting list during their physical count, but the file cannot be imported as OB lines.
    Live banner: "X of Y lines have UOM conversion warnings" (warning) / "Z lines exceed reorder qty" (info). Sum row at the bottom: total default-uom qty.

STEP 3 — Evidence (REQUIRED)
    Photo / document drop zone (multi-file). Each upload shows thumbnail, filename, size, hash (truncated). At minimum require: signed count sheet OR photo of the counted stock OR digital sign-off from a second warehouse staff member (any one). "Photos required for any line marked DAMAGED or QUARANTINE." Submit blocked until at least one evidence file is attached.

STEP 4 — Review & Submit
    Read-only summary. Show by category: items, total qty, valuation. Show lines flagged with warnings (expired AVAILABLE, missing UOM conversion, location mismatch).
    VALUATION BASIS panel (always visible) shows which of the three valuation methods will apply:
      • ITEM_UNIT_COST — every line has a unit_cost_estimate; tier computed from line-level cost × qty.
      • CATEGORY_ESTIMATE — some lines lack unit cost but a category default is configured; tier computed from category default × qty.
      • SAGE_DEFERRED_EXECUTIVE_ROUTE — neither available; approval ELEVATED to Director PEOD / Executive (≥ $500K–$2M tier) regardless of qty. Records a MANUAL_OVERRIDE exception. Missing cost NEVER lowers the approval tier.
    Three actions when cost is incomplete:
      1) "Enter unit cost estimates" → returns to Step 2 with missing-cost lines highlighted.
      2) "Use category default costs" → only available if at least one line's category has a default; pre-fills CATEGORY_ESTIMATE basis.
      3) "Continue with Executive approval routing" → SAGE_DEFERRED_EXECUTIVE_ROUTE basis; submit proceeds; tier elevated.
    Tier preview banner: "Approval routes to Logistics Officer (≤$500K)" or "Approval routes to Senior Director PEOD ($500K–$2M)" or "Approval route elevated — Sage integration deferred. Routes to Director PEOD / Executive."
    Confirmation modal on submit: "You will not be able to edit after submitting. Valuation basis: [basis]. Approval tier: [tier]. Continue?"

Mobile: each step takes the full screen; long line table scrolls horizontally with the leftmost two columns sticky.

----------
5) /inventory/opening-balance/{id}/detail — OPENING BALANCE DETAIL (FR03.30, .67)
----------

- Header: OB number, status pill, warehouse, purpose. Action bar (right side): conditional buttons:
    DRAFT: Edit | Submit | Cancel
    PENDING_APPROVAL: Approve | Reject | Cancel
      Hide Approve if current user == requested_by_id (segregation of duties — show greyed-out hint "You cannot approve your own request").
    APPROVED: Post (idempotent, requires confirmation modal)
    POSTED / REJECTED / CANCELLED: no actions.
- VALUATION BASIS panel (always visible, prominent): shows ITEM_UNIT_COST / CATEGORY_ESTIMATE / SAGE_DEFERRED_EXECUTIVE_ROUTE plus the resulting approval tier. When SAGE_DEFERRED_EXECUTIVE_ROUTE: amber banner "Approval route elevated — Sage integration deferred. Routes to Director PEOD / Executive. Approval authority is NOT lowered by missing cost."
- Tabs: Lines | Evidence | History | Audit.
    Lines tab: read-only line table with status per line, expiry pill, location, unit_cost_estimate (if any), posted_ledger_id link → opens provenance drawer.
    Evidence tab: thumbnail grid + download + delete (admin only).
    History tab: status timeline with actor + timestamp per transition.
    Audit tab: full immutable audit log (read-only). Includes valuation_basis transitions and any MANUAL_OVERRIDE exception entries linked to this OB.
- Banner at top if approved tier requires escalation (e.g., "$500K–$2M — requires Senior Director PEOD approval").
- Mobile: tabs become accordion.

----------
6) /inventory/opening-balance/approval-queue — APPROVAL QUEUE (FR03.30)
----------

- Manager-only view. List of OBs in PENDING_APPROVAL status, scoped to manager's tenant. Sort by submitted_at ascending (oldest first).
- Each row: OB number, warehouse, requested by, line count, total qty, valuation basis chip (ITEM_UNIT_COST / CATEGORY_ESTIMATE / SAGE_DEFERRED_EXECUTIVE_ROUTE), valuation tier (≤500K / 500K–2M / 2M–10M / >10M with color coding), submitted ago. Right-aligned: Approve / Reject buttons.
- When valuation basis is SAGE_DEFERRED_EXECUTIVE_ROUTE, show amber "Elevated route — Sage deferred" pill so the approver immediately knows the OB was routed to them not because of computed value but because cost data is missing.
- Empty state: "No opening balances awaiting your approval."

----------
7) /inventory/exceptions — EXCEPTION DASHBOARD (FR03.80, OB-only in Sprint 1)
----------

- List of unresolved exceptions, grouped by severity (CRITICAL / HIGH / MEDIUM / LOW).
- Each card: exception type pill, related entity link, detected at, severity badge, resolve button.
- Filter: type, severity, warehouse.
- Empty state: "No open exceptions. All operational gates clear."

----------
8) /inventory/pick-confirm — PICK CONFIRMATION (FR03.53, .54)
----------

- Worker-focused mobile-first layout (one-handed tablet use).
- Top: active reservation badge (target type + id, qty required).
- FEFO/FIFO recommended pick: card showing batch, location, qty, expiry, freshness pill. "Recommended" sticker. Below: alternative picks (collapsible).
- Form: scan-style fields (large text inputs) for item barcode, batch barcode, location code, picked qty. Big "Confirm Pick" button at bottom; haptic-style press feedback.
- Validation messages inline. On mismatch, red banner with retry guidance.
- Mobile: form takes full viewport; keyboard does not cover the Confirm button.

----------
9) /inventory/reservations — RESERVATIONS (read-only) (FR03.51, .52)
----------

- List view: target type, target id, item, batch, location, qty, status, reserved_at. Filter by warehouse, item, target type. Empty/skeleton states required.

----------
10) Master-data screens (extends existing project pattern; no new design):
----------

    - /master-data/stock-source-type
    - /master-data/stock-status
    - /master-data/variance-reason-code
    - /master-data/writeoff-reason-code
    - /master-data/quarantine-reason-code
    - /master-data/count-threshold
    - /master-data/uom-conversion

================================================================================
WORKFLOW DIAGRAMS (include as a separate page after wireframes)
================================================================================

Use Mermaid for these diagrams.

DIAGRAM 1 — Opening Balance lifecycle (warehouse-level inventory state):

[*] -> ZERO_BALANCE
ZERO_BALANCE -> OPENING_BALANCE_DRAFT (warehouse user begins onboarding; perm: inventory.opening_balance.create)
OPENING_BALANCE_DRAFT -> PENDING_APPROVAL (Submit; perm: inventory.opening_balance.submit)
PENDING_APPROVAL -> OPENING_BALANCE_DRAFT (Rejected / Returned; perm: inventory.opening_balance.reject)
PENDING_APPROVAL -> APPROVED (Approve; perm: inventory.opening_balance.approve; SoD: actor != requested_by_id; tier-routing by total value)
APPROVED -> POSTED (Post creates immutable ledger entries; perm: inventory.opening_balance.post; idempotency required)
POSTED -> INVENTORY_ACTIVE (Ledger-derived balance updated; system-driven transition)
INVENTORY_ACTIVE -> AVAILABLE | QUARANTINE | DAMAGED | EXPIRED | HOLD (per-stock-row status branches)

Optional cancel transitions:
OPENING_BALANCE_DRAFT -> CANCELLED
PENDING_APPROVAL -> CANCELLED
APPROVED -> CANCELLED (manager only, before post; emits compensating audit row)

DIAGRAM 2 — Stock Status state machine (FR03.49, .50):

AVAILABLE <-> RESERVED -> PICKED -> STAGED -> ISSUED
AVAILABLE -> QUARANTINE / DAMAGED / EXPIRED / HOLD / RETURN_PENDING / DISPOSAL_PENDING
QUARANTINE -> AVAILABLE (release-approve) / DISPOSAL_PENDING / RETURN_PENDING
RETURN_PENDING -> RETURNED
DISPOSAL_PENDING -> DISPOSED
Note: only AVAILABLE permits allocation, picking, transfer, dispatch.

DIAGRAM 3 — Inventory Source-Type Map:
A simple table-style diagram showing the 10 source-type codes and which workflow drives each. In Sprint 1, only OPENING_BALANCE has a working UI (highlighted); others are configured but parked.

DIAGRAM 4 — End-to-end OB cutover:
Start: EP-03 Ledger Cutover -> All Warehouses Start at Zero Inventory -> Warehouse User Performs Physical Stock Count -> Create OB Draft -> Enter Item, Quantity, UOM, Batch, Expiry, Condition, Location -> Attach Evidence (Count Sheet / Photos / Sign-off) -> Submit for Approval -> Approver Reviews -> (Approve OR Reject/Return) -> Opening Balance Approved -> Post -> Create Immutable Stock Ledger Entries -> Update Ledger-Derived Inventory Balance -> Warehouse Inventory Becomes Active -> Stock Status (AVAILABLE -> Can Be Reserved/Picked/Dispatched OR QUARANTINE/DAMAGED/EXPIRED/HOLD -> Blocked from Allocation) -> Dashboard / COP / Replenishment Reads Ledger Balance.

================================================================================
COMPONENTS TO RE-USE ACROSS PAGES
================================================================================

- StatusChip(label, tone, icon) — tone = {available | reserved | quarantine | damaged | expired | hold | in_transit | picked | staged | issued | returned | disposed | unknown}.
- SeverityBadge(level) — GREEN / AMBER / RED with text + icon.
- ExpiryCountdown(days) — pill with days remaining.
- FreshnessPill(latency_minutes) — HIGH / MEDIUM / LOW.
- EvidenceThumbnail(file) — image preview + filename + size + hash (truncated).
- KpiCard(label, value, delta, tone).
- DataTable(columns, rows) — desktop table; collapses to card-list <768px.
- StepTracker(steps, activeIndex) — for the OB wizard (mirrors the existing project DmisStepTrackerComponent).
- ConfirmDialog(title, message, primaryAction).
- EmptyState(headline, body, primaryAction).
- SkeletonRow / SkeletonCard.
- ToastInline(message, level) — top-right; auto-dismiss.
- ValuationBasisPanel(basis, tier) — used in Step 4 of the wizard, the OB Detail page, and the Approval Queue.
- WarehouseStateBadge(state_code) — used wherever warehouse state appears.

================================================================================
DELIVERABLE FORMAT
================================================================================

- One HTML file per page, in a folder structure mirroring the routes:
    inventory/dashboard.html
    inventory/items/{id}/provenance.html
    inventory/opening-balance/list.html
    inventory/opening-balance/wizard.html
    inventory/opening-balance/{id}/detail.html
    inventory/opening-balance/approval-queue.html
    inventory/exceptions.html
    inventory/pick-confirm.html
    inventory/reservations.html
    diagrams.html
- Inline CSS only (no external stylesheets).
- Use semantic HTML5 elements.
- All interactive elements keyboard-focusable.
- Pages independently viewable (no required server).
- Include a README.md with the page list, design tokens cheat sheet, and a "next steps" section pointing to Angular component file paths under frontend/src/app/inventory/pages/... so the implementing engineer knows where each wireframe lands.

End of brief.
```
