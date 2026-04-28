# Master-Data Forms — Visual Refresh + Per-Field Copy Uplift (Codex Handoff)

This document is the canonical source for three Codex briefs that (A) bring the 4 master-data shell components into full alignment with the updated `frontend/src/lib/prompts/generation.ts` (now 2,621 lines, 7 sections, lots of new form-UX guidance), (B) populate per-field operator-facing description + example across all 18 master-data TableConfigs, and (C) verify the result. **Zero behavior change.** Each brief is self-contained — Codex does not need conversation context.

## Context

**Why**: Phase 2 (tenant-admin self-service) is on hold. Before production deployment, master-data forms need to (a) match the modern UI/UX standard documented in the updated `generation.ts`, and (b) carry per-field operator-facing copy so a SYSTEM_ADMINISTRATOR can fill any form correctly without institutional knowledge.

**What's already strong**:
- Token architecture sound: `frontend/src/styles.scss` has `--color-*`, `--text-*`, `--weight-*`, `--radius-*`, `--dmis-font-*` plus a complete `--ops-*` alias layer added in earlier Brief #6 work.
- Brief #6's 4 assignment components (`user-roles-assignment`, `role-permissions-assignment`, `tenant-users-assignment`, `tenant-user-roles-assignment`) are already production-grade visually — they are the reference for clean kebab-BEM, signals-first IO, only `--ops-*` tokens, mobile breakpoints, skeleton loaders, status pills with text+icon backup.

**Visible drift to close**:
- `master-list.component.scss` has 6 hardcoded status/boolean colors at lines 320-339 and 5 `!important` declarations at lines 142-146/275.
- `master-form-page.component.scss` has ~50 hardcoded colors in `.form-submit-alert`, `.ifrc-applied-banner`, `.ifrc-suggestion-candidate`, `.catalog-suggestion-preview__messages` — most are severity tones that should map to `--color-{critical,warning,success,info}-bg/-text` aliases that already exist.
- `master-detail-page.component.scss` has hardcoded status badge colors per status.
- The shell components don't use the **density-tier** pattern from `generation.ts:2213-2234` (`--ops-form-density: comfortable | compact | dense`) or the **error-summary-on-submit** pattern from lines 607-633.
- No mixin extraction: `%card-base`, `%focus-ring`, `%eyebrow`, `%pill-badge` are defined locally in `master-form-page.component.scss:2-27` but not shared.
- Per-field copy is sparse: most TableConfig field entries set `label` and validators but skip `hint`/`placeholder`/`description`. Operators see field names like `parish_code`, `parent_tenant_id`, `data_scope` with no in-form guidance.

**Pipeline-safety**: Both briefs touch only `frontend/src/app/master-data/` and `frontend/src/styles.scss` (token aliases) and `docs/implementation/` (CSV review artifact). No backend changes. No GitLab pipeline rewiring required.

**Risk classification**: Low-Medium (~4-5 pts) — frontend-only, no auth, no schema, no API change.

## Execution order

Briefs A and B can dispatch **in parallel** (disjoint files). Brief C runs after both land.

1. **Brief A** — Visual refresh of master-data shell components (`master-list`, `master-form-page`, `master-detail-page`, `master-home`).
2. **Brief B** — Per-field copy uplift across all 18 TableConfigs + emit `master_data_field_copy_review.csv`.
3. **Brief C** — Verification + Playwright before/after sweep.
4. After Brief C: Claude Code reads the CSV, compiles a redline list, and dispatches a small follow-up Codex prompt that applies the edits in a single commit.

---

## Codex Brief A — Visual refresh of master-data shell components

**Goal**: Update the 4 shell components to fully match `generation.ts` (sections 1, 2, 3, 4, 4b, 4f, 4g) and remove all hardcoded colors / `!important` declarations. **Zero behavior change** — only SCSS, template structure (where needed for ARIA / error-summary / page-shell wrapping), and any accompanying TypeScript signal-state for new visual concerns. FormGroup wiring, validators, lookups, save handlers stay identical.

**Files to edit**:
- `frontend/src/app/master-data/components/master-list/master-list.component.{scss,html,ts}`
- `frontend/src/app/master-data/components/master-form-page/master-form-page.component.{scss,html,ts}`
- `frontend/src/app/master-data/components/master-detail-page/master-detail-page.component.{scss,html,ts}`
- `frontend/src/app/master-data/components/master-home/master-home.component.{scss,html,ts}`
- `frontend/src/styles.scss` (only if a needed severity-tone alias is missing)

**Files to create**:
- `frontend/src/app/master-data/_master-data-mixins.scss` — extract `%card-base`, `%focus-ring`, `%eyebrow`, `%pill-badge` from `master-form-page.component.scss:2-27`. Each shell SCSS file `@use '../../master-data-mixins' as *;` (path may need adjustment — Codex resolves relative path).

**Patterns to anchor on (read first, in order)**:
1. `frontend/src/lib/prompts/generation.ts` — sections 1 (Visual Identity), 2 (Component Architecture), 3 (Styling Rules), 4 (Page Layout Patterns), **4b (Form Field UX Rules, lines 2118-2249)**, **4f (Work-Pipeline Queue Pattern, lines 1051-1983)**, **4g (Shared Queue-Card Primitives, lines 1986-2115)**.
2. `frontend/src/app/master-data/components/user-roles-assignment/user-roles-assignment.component.scss` — Brief #6 reference. Cleanest example of `--ops-*`-only tokens with kebab-BEM namespace.
3. `frontend/src/app/operations/operations-shell/` — polished ops-shell (eyebrow + title + filters + body) that master-data shells should match for visual rhythm.

**Required changes (numbered for verification mapping)**:

A1. **Hardcoded colors → token aliases.** Audit every SCSS file in scope. Replace every `#hex` / `rgb(...)` value with the matching `--color-*` or `--ops-*` token defined in `frontend/src/styles.scss`. Severity tones map to `--color-{success,critical,warning,info}-{bg,text}` aliases that already exist. If a color is not yet aliased, add the alias to `styles.scss` first, then reference it; do NOT introduce new hardcoded values.

A2. **Remove `!important` declarations.** The 5+ instances on `.clear-btn` and `.actions-col` in `master-list.component.scss:142-146,275` are Material override workarounds. Replace with higher-specificity selectors using `:host ::ng-deep` (already permitted in this project) or with cascade-layer ordering via `@layer` per generation.ts §3.

A3. **Density tier system.** Wrap each form in `<div class="ops-form-stage" style="--ops-form-density: comfortable;">` (or `compact` for the master-list inline filter bar). Drive `<mat-form-field>` height through `--mat-form-field-container-height` mapped from `--ops-form-density`. Implement once in `_master-data-mixins.scss` as `@mixin ops-form-density-stage`. Generation.ts §4b lines 2213-2234 is the contract.

A4. **Error summary on submit.** Per generation.ts §4 lines 607-633: add to `master-form-page.component.html` a `<section #errorSummary role="alert" aria-live="assertive">` rendered when `formGroup.invalid && formGroup.touched`. Each invalid control gets a `<a [href]="'#' + control.id">` linking to its field. Auto-focus the heading via `afterNextRender(() => errorSummary.nativeElement.querySelector('h2')?.focus())`. **The submit handler is unchanged** — only post-submit error rendering is added.

A5. **Page-shell + eyebrow + title pattern.** Wrap each shell page in `<div class="ops-page-shell">` per generation.ts §4. Header consists of: `<p class="ops-page-shell__eyebrow">{{ tableLabel | uppercase }}</p>`, `<h1 class="ops-page-shell__title">{{ pageTitle() }}</h1>`, optional `<p class="ops-page-shell__subtitle">{{ pageSubtitle() }}</p>`. Page titles are unchanged — same string, new wrapper.

A6. **Master-list status pill backup.** Status badges currently render color-only at `master-list.component.scss:320-339`. Replace with `<span class="ops-pill ops-pill--{{tone}}">` (color + leading `<mat-icon>` + text label). Use the new mixin `%pill-badge`. Tone map: A → success/check_circle, I → neutral/radio_button_unchecked, L → critical/lock, C → info/info.

A7. **Mobile breakpoints standardize.** Confirm all 4 shell SCSS files use the same media query order (1024 / 768 / 520 / 480). master-list already does; verify and align the others.

A8. **No new dependencies.** Do NOT install any new npm package. Do NOT touch `package.json` / `package-lock.json`.

A9. **Signals-first IO compliance.** Any new TypeScript additions (e.g., `errorSummary` ViewChild signal, page-shell title computed signal) must use `viewChild()`, `input()`, `output()`, `signal()`, `computed()` — NEVER `@ViewChild`, `@Input`, `@Output`. Existing decorator code may stay if untouched, but new additions must be signals-first. Generation.ts §2 line 73-77 is the rule.

A10. **No `@Input()` / `@Output()` decorator regressions.** Run `grep -c "@Input\(\)\|@Output\(\)" frontend/src/app/master-data/components/{master-list,master-form-page,master-detail-page,master-home}/**/*.ts` after the changes — count must not increase from the pre-change baseline.

**Constraints**:
- Zero behavior change. FormGroup wiring, validators, save handlers, lookup calls, route guards stay identical.
- Pure visual + accessibility additions only.
- No new shared components beyond the SCSS mixin partial.
- No npm install / npm ci.

**Acceptance**:
1. `cd frontend && npm run lint` clean.
2. `cd frontend && npm run build` succeeds with no NEW warnings (existing 2 SCSS budget warnings on operations-shell + stock-status-dashboard remain).
3. `cd frontend && npx ng build --configuration development` succeeds.
4. `cd frontend && npm test -- --watch=false --browsers=ChromeHeadless` passes (existing 685 SUCCESS or higher).
5. `grep -E "color: #[0-9a-fA-F]{3,6};|background: #[0-9a-fA-F]{3,6};" frontend/src/app/master-data/components/{master-list,master-form-page,master-detail-page,master-home}/**/*.scss` returns **zero matches**.
6. `grep -c "!important" frontend/src/app/master-data/components/{master-list,master-form-page,master-detail-page,master-home}/**/*.scss` returns **zero**.
7. **Playwright before/after snapshots** at desktop (1280×800) and mobile (375×812) for: `/master-data` home, `/master-data/items` (densest list), `/master-data/items/new` (densest form), `/master-data/tenants/<id>` (form with FK + select + toggle mix). Capture pre-change snapshots from `git stash`-ed working tree first, then post-change snapshots, then include both file paths in the report.

**Reporting**: diff per file, mapping of each numbered required change A1-A10 to lines/files where applied (one line per change), Playwright snapshot pairs (before/after) for 4 pages × 2 widths = 8 image pairs, deviations from generation.ts (with line numbers cited), sandbox blockers if any.

---

## Codex Brief B — Per-field copy uplift across all 18 TableConfigs

**Goal**: For every field in every TableConfig under `frontend/src/app/master-data/models/table-configs/`, populate operator-facing **description** (rendered as Material `<mat-hint>` below the field) and **example** (rendered as the input's `placeholder` attribute). Apply `generation.ts §4b` "label from next actor's perspective" guidance and DMIS domain context. Emit a CSV review artifact for follow-up red-lining.

**Files to edit** (18 config files):
- `frontend/src/app/master-data/models/table-configs/{item-categories,ifrc-families,ifrc-item-references,items,uom,countries,currencies,parishes,events,warehouses,agencies,custodians,donors,suppliers,users,roles,permissions,tenants}.config.ts`

**Files to create**:
- `docs/implementation/master_data_field_copy_review.csv` — review artifact. Columns `table_key,field_name,label,description,example,notes`. One row per field across all 18 tables. **Notes** column lists any field where Codex chose between two plausible drafts or where the field's purpose is ambiguous.

**Files to MODIFY ONLY IF the schema lacks the relevant field**:
- `frontend/src/app/master-data/models/master-data.models.ts` — extend `FormField` interface to add `description?: string` if not present. (`hint` already exists; if equivalent, reuse `hint`. If `placeholder` not present, add it.)

**Patterns to anchor on**:
1. `frontend/src/lib/prompts/generation.ts:2125-2128` — labels and hint text from next actor's perspective. **Read first.**
2. `frontend/src/lib/prompts/generation.ts:2118-2249` — Section 4b Form Field UX Rules in full.
3. `backend/masterdata/services/data_access.py` — for each field, read the column's purpose from the surrounding `TableConfig` definition; the `label` and `fk_label` give domain semantics.
4. `frontend/src/app/master-data/models/table-configs/warehouses.config.ts` and `agencies.config.ts` — these have a few `hint` strings already; mirror their voice and density.

**Copy authoring rules**:
1. **Description** (1-2 sentences, max ~120 chars): explains what the operator should enter and why, from next actor's perspective. "This warehouse stocks the items dispatched during SURGE — pick the closest physical hub", not "FK to warehouse table". Avoid jargon and unfamiliar abbreviations.
2. **Example** (1 short value, no "e.g." prefix): a real-shaped sample value the operator can model from. For `tenant_code`: `KINGSTON_NEOC`. For `email`: `kemar.brown@odpem.gov.jm`. For `phone`: `+1 876 555 0123`. For numeric/select fields: leave placeholder empty (Material's select shows "Choose…" by default; numeric fields with sentinel placeholders are visually noisy).
3. **`readonlyOnEdit` fields**: include the description but mark example as `(set on creation; locked once saved)`.
4. **FK fields**: description names what the FK references in human terms ("the warehouse this user manages day-to-day"); example omitted (lookup surfaces choices).
5. **Boolean toggle fields**: description states ON-state and OFF-state in operator terms; example omitted.
6. **Status fields**: description states lifecycle meaning; example omitted (select).
7. **Voice**: clear, neutral, slightly formal — match DMIS UI copy. No emoji, no marketing language, no "please".

**Required changes**:

B1. **Audit the FormField interface** (`frontend/src/app/master-data/models/master-data.models.ts`). Confirm whether `description` and `placeholder` exist as properties on the field type. If `description` is missing, add it as `description?: string` (used to populate `<mat-hint>`). If `placeholder` is missing, add it as `placeholder?: string`. Reuse existing `hint` if it already serves the description purpose — Codex's call. Document the choice in the report.

B2. **For every field of every config file**: populate `description` and `placeholder` (or equivalent) per the copy authoring rules above. Use the schema-derived `label` to ground purpose; do NOT guess at fields whose intent is unclear — flag them in the CSV `notes` column for user review.

B3. **Wire the description to the form template.** Confirm `master-form-page.component.html` already renders `<mat-hint>{{ field.hint || field.description }}</mat-hint>` and `[placeholder]="field.placeholder || field.example"`. If not, add the binding (template-only edit — do NOT touch the form's TypeScript controller).

B4. **Emit `docs/implementation/master_data_field_copy_review.csv`.** UTF-8, comma-delimited, RFC-4180-quoted where needed. Header row exact: `table_key,field_name,label,description,example,notes`. One row per field across all 18 tables. Notes column non-empty for any flagged ambiguity.

B5. **Commit message** must list both the 18 modified config files and the new CSV path.

**Constraints**:
- **Zero behavior change.** Only data-layer config additions and a possible template binding wire-up. No FormGroup wiring touched, no validator changes.
- No npm install / npm ci.
- Do NOT modify Brief #6 assignment components or detail pages.
- Do NOT modify `tasks/todo.md` or any unrelated doc.

**Acceptance**:
1. `cd frontend && npm run lint` clean.
2. `cd frontend && npm run build` succeeds.
3. Every field in every config file has either (a) a `description` populated AND a `placeholder` populated (free-text and email/phone fields), or (b) a `description` populated and a documented reason for omitting `placeholder` (FK / select / toggle / status fields). Codex must verify with a grep + count.
4. `docs/implementation/master_data_field_copy_review.csv` exists, UTF-8, RFC-4180-compliant, exact header row, one row per field. Codex reports the row count.
5. **Playwright spot-check**: navigate to `/master-data/tenants/new` (form with the most fields). Snapshot. Assert: every field renders a non-empty `<mat-hint>` text and free-text fields render a non-empty `placeholder`. Capture one screenshot at desktop width.

**Reporting**: diff stat per file, schema choice (existing `hint` reused vs new `description` added; same for `placeholder`), CSV row count, sample 5 rows of the CSV pasted in-line, list of fields flagged in the `notes` column for user review, Playwright spot-check screenshot path, deviations from copy authoring rules.

---

## Codex Brief C — Verification + Playwright before/after sweep

**Files**: read-only; one transient `git stash` cycle reverted before reporting.

Run from `frontend/` (or repo root where appropriate):

1. `npm run lint` — clean.
2. `npm run build` — production succeeds, no new warnings vs the pre-Brief-A/B baseline.
3. `npx ng build --configuration development` — succeeds.
4. `npm test -- --watch=false --browsers=ChromeHeadless` — full Karma suite passes.
5. **Playwright sweep** at desktop (1280×800) + mobile (375×812):
   - `/master-data` (home grid)
   - `/master-data/items` (densest list)
   - `/master-data/items/new` (densest form)
   - `/master-data/tenants/<existing_id>` (form with FK + select + toggle mix)
   - For each: assert no `console.error`, no 4xx/5xx network on `/api/v1/masterdata/*`. Snapshot.
6. **Token migration sanity grep**: zero hardcoded colors and zero `!important` in the 4 shell SCSS files.
7. **Per-field copy sanity grep**: count fields with `description:` and `placeholder:` across the 18 config files; report against the CSV row count.
8. **Tear down** the dev server.

**Constraints**: do NOT run `npm install` / `npm ci`. Report missing `node_modules` as a blocker.

**Reporting**: pass/fail per step, before/after Playwright snapshot pairs (8 pairs minimum), token-migration counts, per-field copy counts, deviations, sandbox blockers.

---

## Reused Utilities (do not reinvent)

- All `--ops-*`, `--color-*`, `--text-*`, `--weight-*`, `--radius-*`, `--dmis-font-*` tokens — `frontend/src/styles.scss`
- `MasterTableConfig`, `FormField` types — `frontend/src/app/master-data/models/master-data.models.ts`
- `MasterDataService` — `frontend/src/app/master-data/services/master-data.service.ts`
- `masterDataAccessGuard`, `MasterDataAccessService.isSystemAdmin()` — `frontend/src/app/master-data/guards/`, `services/master-data-access.service.ts`
- `frontend/src/lib/prompts/generation.ts` — canonical design prompt (sections 1, 2, 3, 4, 4b, 4f, 4g)
- Brief #6 reference for token-only SCSS shape: `frontend/src/app/master-data/components/user-roles-assignment/user-roles-assignment.component.scss`
- Operations-shell pattern reference for visual rhythm: `frontend/src/app/operations/operations-shell/`

## Out of Scope

- Phase 2 (tenant-admin self-service, audit log, invitation flow, MFA) — held per user direction.
- Brief #6 assignment components (already production-grade visually).
- Master-data detail pages (display-only; out of scope per user's "All master-data forms" answer).
- Backend API enrichment (FK label joins on list endpoints) — separate platform-wide epic.
- Replacing shell components with a different layout primitive (e.g., side-panel form drawer) — that's a redesign, not a refresh.
- Microcopy beyond per-field description + example (page-level help text, contextual tours) — separate copy work.
