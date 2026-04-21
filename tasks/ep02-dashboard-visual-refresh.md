# EP-02 Supply Replenishment Dashboard — Claude Design Visual Refresh

## Source of Truth

- Visual target: `C:\Users\wbowe\Downloads\Supply Replenish Dashbaord\DESIGN.md` + pinned screenshot (2026-04-20).
- Implementation guardrail: `frontend/src/lib/prompts/generation.tsx` (Notion-warm ops-page-shell vocabulary).
- Backend contract (locked, already fixed in prior commit 09ae7ea):
  - `/api/v1/replenishment/*` — no `/api/v1/supply/*`.
  - CTA route: `/replenishment/needs-list-wizard?event_id=&event_name=&warehouse_id=&phase=`.
  - Phases: SURGE / STABILIZED / BASELINE only (no RECOVERY).
  - Display severity: CRITICAL / WARNING / GOOD.
  - Refresh cadence: SURGE 5m / STABILIZED 30m / BASELINE 2h.
  - Phase windows event-scoped: GET/PUT `/api/v1/replenishment/events/{eventId}/phase-windows[/{phase}]` with required `justification`.

## Scope

Replace the dashboard template + SCSS (`stock-status-dashboard.component.{html,scss}`) so the rendered page matches the screenshot. Extend the component TS to feed the new regions (action inbox, freshness panel, risk-by-category). Keep all backend-contract logic, gating dialogs, safe-poll, phase-window wiring from 09ae7ea intact — **only visual surface changes plus additive signals/computeds**.

## Region Map (screenshot → Angular)

| # | Screenshot region | Angular markup | Data source |
|---|-------------------|----------------|-------------|
| 1 | Hero band (eyebrow "EP-02 · Supply Replenishment", title, Refresh + Generate buttons, phase chip, window pill, "11/14 fresh" + MEDIUM chip, Configure windows) | `header.ops-hero` inside `div.ops-page-shell` with `ops-hero__eyebrow` + `ops-hero__title` + inline chip row + `ops-hero__actions` | `activeEvent()`, `phaseWindows()`, `freshnessSummary()` computed |
| 2 | Your Action Inbox bar | `section.ops-action-inbox` (new scoped class, inside ops-page-shell) with `app-ops-status-chip` pills for counts + `Review Queue` link | New computed `actionInbox()` derived from `pendingNeedsLists()` counts by status |
| 3 | LOW confidence banner | `aside.ops-banner.ops-banner--critical` conditional on `hasLowConfidence()` | `warehouseGroups()` → any confidence==='LOW' |
| 4 | KPI strip (4 cards) | `<app-ops-metric-strip [items]="kpiStrip()">` | Existing `kpiStrip()` + wire in confidence/delta token + severity tone |
| 5 | Warehouses at risk panel (LEFT 2/3) | `section.ops-panel` with `ops-toolbar` + severity chips + scope/sort/search + warehouse cards using `details/summary` expanders and inner `<table class="ops-row-list">` for items | Existing `filteredWarehouseGroups()`, extended with paging + expanded state signal |
| 6 | Data freshness panel (RIGHT top) | `section.ops-panel` with title + thresholds sub-copy + list rows (warehouse · age · chip) | New computed `freshnessRows()` from `warehouseGroups()` |
| 7 | Risk by category panel (RIGHT bottom) | `section.ops-panel` with stacked progress bars per category | New computed `categoryRollup()` from item-level severity grouped by `item.category` |

Map view is intentionally omitted (DESIGN.md Phase 3 deferred).

## Component TS additions (no breaking changes)

```
// ————— Action Inbox (FR02.93 display vocabulary) —————
readonly actionInbox = computed(() => {
  const lists = this.activeNeedsLists();
  const byStatus = (predicate: (s: string) => boolean) =>
    lists.filter(l => predicate(this.toDisplayStatus(l.status))).length;
  return {
    awaitingApproval: byStatus(s => s === 'SUBMITTED'),
    draftsInProgress: byStatus(s => s === 'DRAFT'),
    returned: byStatus(s => s === 'MODIFIED' || s === 'REJECTED'),
  };
});

// ————— Freshness panel rows —————
readonly freshnessRows = computed(() => /* flatten warehouseGroups() → { name, syncedAgoLabel, confidenceTone } */);

// ————— Risk by category —————
readonly categoryRollup = computed(() => /* group items by category → { name, critical, warning, good, atRisk, total } */);

// ————— Freshness summary chip for hero —————
readonly freshnessSummary = computed(() => ({ fresh: N, total: M, tone: 'HIGH'|'MEDIUM'|'LOW' }));
```

All new computeds are pure projections of existing data; no new HTTP calls.

## SCSS strategy

- Replace every legacy block class (`.dmis-page`, `.page-header`, `.context-card`, `.filters-panel`, `.warehouses-container`, `.warehouse-card`, `.dmis-table`, `.empty-state-card`, `.mobile-card-list`, `.mobile-item-card`, `.mobile-fab`, `.stats-row`, `.burn-rate-cell`, `.gap-cell`, `.hero-cta`) with the global ops-shell equivalents.
- File stays as `stock-status-dashboard.component.scss` but becomes **small additive styles only** — bucket classes (`chip-critical/warning/good/watch/ok` used by internal filter state), stale-data micro-chip, action-inbox specifics, risk-by-category bars, freshness row density. Everything else flows from `operations-shell.scss` tokens already globally available.
- Tokens used exclusively: `--ops-card`, `--ops-ink-muted`, `--ops-outline`, `--ops-outline-strong`, `--ops-radius-md`, `--ops-radius-sm`, `--color-critical`, `--color-warning`, `--color-success`.
- No `!important`, no hardcoded hex for colors that have a token, no cold Material grays.

## Preserved from 09ae7ea (must not regress)

- `generateNeedsListWithGates` CTA path on hero, FAB, and warehouse card.
- `checkActiveNeedsLists` + duplicate/low-confidence/scope-picker dialogs.
- Safe poll loop (document.hidden pause, 429 Retry-After, in-flight guard, debounced manual refresh).
- Phase-window event-scoped URLs + required justification.
- 3-bucket display severity at template boundary; 4-bucket internal selector logic retained for filters.
- `PHASE_WINDOWS` fallback Backlog v3.2 values.
- `loadPhaseWindows()` only after `activeEvent.event_id` resolved.

## Spec updates

- New DOM assertions for the rewritten regions (eyebrow, action inbox chips, freshness panel rows, category rollup bars).
- Keep the "never renders raw WATCH or OK" and severity-filter-chips tests — move selectors from legacy `.badge` / `col-status` to the new ops-chip markup.
- Keep all phase-windows tests (passes eventId, hidden when not manageable, 403 toast, justification required).
- Add test: "Action Inbox counts reflect FR02.93 status buckets".
- Add test: "Risk by category shows zero-aware bars without divide-by-zero".

## Files touched

- `frontend/src/app/replenishment/stock-status-dashboard/stock-status-dashboard.component.html` — full rewrite.
- `frontend/src/app/replenishment/stock-status-dashboard/stock-status-dashboard.component.scss` — major reduction/rewrite.
- `frontend/src/app/replenishment/stock-status-dashboard/stock-status-dashboard.component.ts` — additive signals/computeds, no removals.
- `frontend/src/app/replenishment/stock-status-dashboard/stock-status-dashboard.component.spec.ts` — selector updates + 2 new tests.

No new files; no route changes; no service changes; no model changes.

## Verification

1. `cmd /c npx ng test --watch=false --browsers=ChromeHeadless --include src/app/replenishment/stock-status-dashboard/stock-status-dashboard.component.spec.ts` → 100% pass.
2. `cmd /c npx ng build --configuration production` → green.
3. Manual smoke at `localhost:4200/replenishment/dashboard` → regions match screenshot.
4. Post-implementation architecture review per CLAUDE.md.

## Risk

- **Medium**: substantial template + SCSS rewrite, but additive-only on TS and no backend changes.
- Mitigations: reuse existing shared components + ops-shell tokens, keep computeds pure, preserve every existing binding target, spec-level DOM assertions.

## Pre-plan architecture review — required changes incorporated (Conditionally Aligned → Aligned)

1. **Category rollup** — bucket items whose `category` is missing into an explicit `Uncategorized` bucket; zero-aware bars guard against divide-by-zero. Plan updated.
2. **Freshness source** — use `warehouseGroups()[i].overall_freshness` as the primary signal + max per-item `age_hours` for the "X ago" label. No new API call.
3. **Action Inbox source** — derives from existing `myNeedsLists` signal (populated by `loadMyNeedsLists()` via `replenishmentService.listNeedsLists(..., { mine: true })`). Review Queue link targets `/replenishment/needs-list-review` (existing route, verified in `replenishment.routes.ts:22`). No new fetch.
4. **SCSS scope guard** — rewrite is confined to `stock-status-dashboard.component.scss`; global `styles.scss` (including its `.page-header` rule) is out of scope. The global class is also used by wizard/review queue pages and must not be touched.
5. **Mobile FAB preserved** — the field-first one-tap CTA for Kemar on mobile is retained and re-expressed as an `ops-toolbar`-anchored sticky primary within the ops-shell vocabulary. Added to "Preserved from 09ae7ea".

Non-blocking: spec adds one assertion that the FAB remains rendered on narrow viewports.
