/**
 * DMIS Component Generation Prompt
 * ─────────────────────────────────
 * This file encodes the design system, coding patterns, and quality
 * standards for generating Angular components in the DMIS project.
 * Feed this prompt to an LLM when asking it to produce new components.
 *
 * NOT shipped in the production bundle. Local-only reference.
 */

export const DMIS_GENERATION_PROMPT = `
# DMIS Component Generation Guidelines

You are generating Angular standalone components for DMIS (Disaster Management Information System),
a Notion-inspired operations platform built for Jamaica's ODPEM. Every component you produce must
feel at home alongside existing pages: warm, minimal, information-dense without being cluttered.

---

## 1. Visual Identity — "Notion for disaster ops"

### Color Palette (warm neutrals, NOT cold grays)
\`\`\`
Ink (primary text):      #37352F
Ink muted (secondary):   #787774
Ink subtle (tertiary):   #908d87
Surface:                 #ffffff
Surface muted (page bg): #F7F6F3
Section (card inset bg): #fbfaf7
Emphasis (hover/active): #eceae4
Outline:                 rgba(55, 53, 47, 0.08)
Outline strong:          rgba(55, 53, 47, 0.14)
Accent (teal):           #0f766e
\`\`\`

### Status Tones — Always provide both color AND text/icon backup
| Tone     | Background | Text    | Use case                        |
|----------|------------|---------|---------------------------------|
| Critical | #fdddd8    | #8c1d13 | Stockout, rejected, failed      |
| Warning  | #fde8b1    | #6e4200 | Low stock, expiring, high urg.  |
| Success  | #edf7ef    | #286a36 | Approved, fulfilled, received   |
| Info     | #eef4ff    | #17447f | In review, informational        |
| Neutral  | #e2dfd7    | #37352F | Draft, default                  |

### Typography
- Font stack: \`ui-sans-serif, -apple-system, "BlinkMacSystemFont", "Segoe UI", "Helvetica", sans-serif\`
- Page title: \`clamp(1.6rem, 2.5vw, 2.2rem)\`, weight 800, tracking \`-0.04em\`
- Section title: \`1.15rem-1.42rem\`, weight 700, tracking \`-0.02em\` to \`-0.03em\`
- Eyebrow: \`0.68-0.72rem\`, weight 700, tracking \`0.2em\`, uppercase
- Body: \`0.92-1rem\`, weight 400, line-height 1.5-1.65
- KPI values: \`clamp(1.5rem, 2vw, 2.2rem)\`, weight 600

### Spacing & Radius
- Card padding: \`22px-28px\`
- Card radius: \`10px\` (--ops-radius-md)
- Pill radius: \`999px\`
- Grid gap: \`12px-30px\`
- Subtle shadow: \`0 1px 3px rgba(0, 0, 0, 0.04)\`

### Interactions
- Hover: background shift to \`#fbfaf7\`, border becomes visible, \`translateY(-1px)\`
- Transition: \`180ms ease\` for background, border, transform
- Focus: \`2px solid #1565c0\` outline with \`2px\` offset
- Always support \`@media (prefers-reduced-motion: reduce)\` — disable transforms and transitions

---

## 2. Component Architecture

### Must-have patterns
- \`standalone: true\` (Angular 21+ default)
- \`changeDetection: ChangeDetectionStrategy.OnPush\`
- Signals-first reactivity: use \`signal()\`, \`computed()\`, \`input()\`, \`output()\`
- NEVER use \`@Input()\` / \`@Output()\` decorators — use \`input()\` / \`output()\` signal functions.
  This is **non-negotiable for newly generated components.** When extending an older file
  that still uses decorators, migrate that specific surface or match the existing pattern
  and flag the debt — but new files must never introduce decorator-based IO.
- Use \`inject()\` instead of constructor injection
- Template syntax: \`@for\`, \`@if\`, \`@switch\` (new Angular control flow, NOT *ngFor/*ngIf)
- Track expressions: always provide \`track\` in \`@for\` blocks
- Read signal inputs in templates with \`()\`: \`{{ warehouse().name }}\`, not \`{{ warehouse.name }}\`

### Imports
- Angular Material: import specific modules (\`MatButtonModule\`, \`MatIconModule\`) not barrel exports
- Only import what the template actually uses
- Use Material Icons (ligature-based): \`<mat-icon>icon_name</mat-icon>\`

### Naming
- Selector prefix: \`app-\` or \`dmis-\` (kebab-case, element type)
- File naming: \`feature-name.component.ts\`
- Interface naming: \`OpsFeatureName\` for operations domain types

### Template rules
- ALWAYS use \`{{ interpolation }}\` for text (Angular auto-escapes). NEVER use \`[innerHTML]\`
- Every \`<section>\` and landmark gets an \`aria-label\`
- Every \`<img>\` gets an \`alt\` attribute
- Interactive elements: keyboard-accessible, \`focus-visible\` styling
- Empty states: always provide a helpful message, never a blank area
- Recovery states: distinguish "missing setup / prerequisite" from "loaded but no matching data"
- Empty and blocker states must include a heading, explanation, next-step guidance, and icon + text backup
- Loading: skeleton loaders preferred over spinners

---

## 3. Styling Rules

### Use CSS custom properties from the design system
\`\`\`scss
// GOOD — references existing tokens
background: var(--ops-card);
color: var(--ops-ink-muted);
border: 1px solid var(--ops-outline);
border-radius: var(--ops-radius-md);

// BAD — hardcoded values that drift from the system
background: #ffffff;
color: #787774;
border-radius: 10px;
\`\`\`

### Class naming convention: \`ops-{block}__{element}--{modifier}\`
\`\`\`html
<section class="ops-activity">
  <header class="ops-activity__header">...</header>
  <div class="ops-activity__item ops-activity__item--highlighted">...</div>
</section>
\`\`\`

### Responsive breakpoints
| Breakpoint   | Behavior                                    |
|--------------|---------------------------------------------|
| > 1100px     | Two-column layouts, full grids              |
| 760-1100px   | Single column, stacked panels               |
| 520-760px    | Simplified grids, reduced padding           |
| < 520px      | Mobile: single column, compact cards        |

### SCSS rules
- NO \`!important\` — ever
- Prefer \`var(--token)\` over hardcoded values
- Quote font-family names that contain spaces
- No deprecated CSS (e.g., no \`-webkit-\` prefixes unless necessary)
- Component styles go in the \`styles\` array (inline) for small components, or \`styleUrl\` for larger ones

---

## 4. Page Layout Patterns

### Standard queue page structure (ALL queue/list pages must follow)
\`\`\`
div.ops-page-shell
  header.ops-hero
    ops-hero__eyebrow (mat-icon + "Module / Section" breadcrumb)
    ops-hero__title
    ops-hero__copy (1 sentence describing the queue's purpose)
    ops-hero__actions (Refresh / primary action buttons)
  app-ops-metric-strip [items]="queueMetrics()" (itemClick)="openMetric($event)"  (3–4 PFQ-aligned KPI tiles; shared component, not hand-rolled SCSS)
  div.ops-grid.ops-grid--split
    LEFT: section.ops-panel
      ops-panel__header (ops-section__eyebrow + ops-section__title + ops-section__copy + item count)
      ops-panel__body
        ops-toolbar
          ops-toolbar__search (label with search input + mat-icon)
          ops-toolbar__filters (chip buttons with role="radiogroup" + aria-label)
        Loading: dmis-skeleton-loader variant="table-row"
        Empty: dmis-empty-state with icon, title, message
        ops-row-list
          article.ops-row.ops-row--interactive (tabindex="0", role="button", keyboard handlers)
            ops-row__lead > ops-row__header (title + status chips) + ops-row__meta (pipe-separated details)
            ops-row__actions (age chip + chevron_right mat-icon)
    RIGHT: aside.ops-grid
      section.ops-card (Workload — ops-summary-grid with 4x ops-summary-card metric cells)
      section.ops-card (Guidance — ops-timeline with 3-4 workflow steps using colored dots)
\`\`\`

**Consistency rule**: Every operations queue page (Relief Requests, Package Fulfillment, Dispatch) uses this identical structure. The only differences are the data fields, filter options, and guidance content. Never create custom shell or row classes for queue pages.

### Standard detail page structure
\`\`\`
ops-shell
  ops-hero
    ops-hero__lead (back button + title/eyebrow/subtitle)
    ops-hero__trail
      ops-hero__status (status + urgency chips — read-only visual badges)
      ops-hero__actions (workflow action buttons)
  ops-layout--two-col or ops-layout--wide-right
    LEFT: ops-document (primary content: meta grid, items table, timeline)
    RIGHT: ops-stack (sidebar: status card, actions, related info)
\`\`\`

### Detail page hero pattern
- **Back button**: always present — \`mat-icon-button\` with \`arrow_back\`, navigates to the parent list
- **Status badges and action buttons live in separate containers** — never mix them in a single flex row
- **\`ops-hero__trail\`** stacks vertically (column) on desktop, aligns chips right with actions below
- On mobile (\`<768px\`), \`ops-hero__trail\` aligns start and stacks below the title

### Action button hierarchy rules
- **Primary (filled)** = the action that moves the record forward in its workflow (submit, approve, dispatch)
- **Secondary (stroked)** = editing, viewing related records, or utility actions (edit draft, open workspace)
- **Destructive (stroked warn)** = reject, deny, ineligible, cancel — any action that blocks or reverses workflow
- Never make the backward/utility action the primary button

### Button styling (Angular Material MDC tokens)

**CRITICAL**: Use \`--mat-button-filled-*\` and \`--mat-button-outlined-*\` token names (NOT the old \`--mdc-filled-button-*\` names — those are dead in Angular Material 21+).

**No transparent button backgrounds on white surfaces.** Every outlined button must have a visible \`background-color\`.

| Tier | Directive | Color attr | Background | Text | Border | WCAG ratio |
|------|-----------|-----------|------------|------|--------|------------|
| Primary | \`mat-flat-button\` | \`color="primary"\` | \`#37352F\` | \`#ffffff\` | none | 12.6:1 |
| Secondary | \`mat-stroked-button\` | (none) | \`#f7f6f3\` | \`#37352F\` | \`rgba(55,53,47,0.28)\` | 9.8:1 text |
| Destructive | \`mat-stroked-button\` | \`color="warn"\` | \`#fdddd8\` | \`#8c1d13\` | \`rgba(140,29,19,0.32)\` | 7.2:1 text |
| Outlined primary | \`mat-stroked-button\` | \`color="primary"\` | \`#e2dfd7\` | \`#37352F\` | \`rgba(55,53,47,0.40)\` | 6.5:1 text |

These tiers are defined in \`operations-shell.scss\` and applied via the \`:host\` selector. Every operations component must import the shell SCSS to inherit button styling.

\`\`\`scss
// Example: Secondary outlined button override
[mat-stroked-button]:not([color]) {
  --mat-button-outlined-label-text-color: #37352F;
  --mat-button-outlined-outline-color: rgba(55, 53, 47, 0.28);
  --mat-button-outlined-state-layer-color: #37352F;
  --mat-button-outlined-ripple-color: color-mix(in srgb, #37352F 12%, transparent);
  background-color: #f7f6f3;
}
\`\`\`

The destructive tier reuses the \`ops-chip--critical\` palette (\`#fdddd8\` / \`#8c1d13\`) for visual consistency with status chips.

### Shared components available for reuse
- \`<app-ops-stock-availability-state>\` â€” warehouse blocker or no-stock empty state for operations workflows
- \`<app-ops-metric-strip [items]="..." (itemClick)="...">\` — **canonical KPI tile strip for every operations queue page**. Renders 3–4 PFQ-aligned cards with left accent bar, optional top-right badge pill (with leading dot), large tabular-nums value, and muted hint. Drives stage colour via the \`token\` field.
  - **Data contract** (\`OpsMetricStripItem\` from \`operations/shared/ops-metric-strip.component.ts\`):
    \`\`\`ts
    interface OpsMetricStripItem {
      label: string;           // Title-Case label (0.82rem)
      value: string;           // large tabular-nums numeral (1.9rem)
      hint?: string;           // muted subtitle
      interactive?: boolean;   // true -> renders as <button>, aria-pressed mirrors active
      active?: boolean;        // filter-active state (stronger outline, warm fill)
      token?: OpsMetricTileTone; // drives .ops-flow-strip__card--{token} accent bar
      icon?: string;           // mat-icon name (rendered only when no badge)
      ariaLabel?: string;
      badge?: { label: string; tone: OpsMetricTileTone }; // top-right pill w/ leading dot
    }
    type OpsMetricTileTone =
      | 'awaiting' | 'drafts' | 'preparing' | 'ready'   // PFQ stage palette
      | 'transit' | 'completed' | 'info' | 'neutral';    // extended ops palette
    \`\`\`
  - Typical caller shape:
    \`\`\`ts
    readonly queueMetrics = computed<readonly OpsMetricStripItem[]>(() => [
      { label: 'Awaiting', value: String(this.counts().awaiting), hint: 'Needs triage',
        token: 'awaiting', interactive: true, active: this.activeFilter() === 'awaiting',
        badge: { label: 'AWAITING', tone: 'awaiting' } },
      // ... 2–3 more, one per stage
    ]);

    openMetric(item: OpsMetricStripItem): void {
      const filter = this.tileTokenToFilter(item.token);
      if (filter) this.setFilter(filter);
    }
    \`\`\`
  - Template: \`<app-ops-metric-strip [items]="queueMetrics()" (itemClick)="openMetric($event)" aria-label="Queue summary" />\`
  - The component owns all card chrome (surface, border, radius, shadow, accent bar via \`::before\`, badge pill). Callers never hand-roll \`.pfq-metric\` / \`.ops-queue-tile\` SCSS for KPIs. All 5 operations queue pages (Relief Requests, Eligibility Review, Package Fulfillment, Consolidation, Dispatch, Task Center) are migrated onto this shared component.
- \`<app-ops-status-chip label="..." tone="..." [showDot]="true">\` — status pill
- \`<app-ops-activity-feed [items]="..." title="..." eyebrow="...">\` — timeline feed
- \`<app-dmis-empty-state>\` — empty placeholder with icon + message
- \`<app-dmis-skeleton-loader>\` — content skeleton for loading states
- \`<app-ops-source-warehouse-picker>\` — default warehouse selector with override count badge

### Standard wizard / form page structure
\`\`\`
ops-shell
  ops-shell__back + ops-shell__title (compact header — NO meta cards)
  ops-context-strip (inline: authority icon + mode label + date)
  ops-shell__stepper (dmis-step-tracker, inside the form shell)
  ops-form-stage
    ops-form-section (form fields, urgency selector, notes — minimal panel chrome)
    ops-form-items (item lines with inline fields, compact density)
  ops-form-actions (cancel + next / save buttons, separated by border-top)
\`\`\`

### Information hierarchy rules
- **Never duplicate data** — if the step tracker shows progress, don't also show it in header meta cards
- **Read-only metadata** (dates, submission modes, authority context) belongs in a compact inline strip, not tall cards with 120px min-height
- **Form fields are primary content** — minimize spacing and chrome between the user and the inputs
- **Urgency / status selectors**: compact 2x2 pill grid on desktop, single-column on mobile

### Form density guidelines
- Panel padding: \`16px 20px\` (not \`20px 24px\`)
- Panel gap: \`14px\` (not \`20px\`)
- Panel intro margin-bottom: \`12px\`
- Use inline context strips for read-only data instead of card-style containers
- Item lines: single-row inline fields with compact Material density (\`--mat-form-field-container-height: 44px\`)

### Compact context strip pattern
\`\`\`html
<div class="ops-context-strip" role="status">
  <mat-icon aria-hidden="true">security</mat-icon>
  <span class="ops-context-strip__mode">
    <strong>Mode label</strong>
    <span>Description text</span>
  </span>
  <span class="ops-context-strip__meta">
    <mat-icon aria-hidden="true">calendar_today</mat-icon>
    Secondary info
  </span>
</div>
\`\`\`

### Context bar pattern
When a persistent control (like a warehouse selector) affects downstream content:
\`\`\`
ops-context-bar (elevated card, full-width above the split layout)
  identity: icon + current selection label
  helper: short description of what this controls
  actions: selector control + override count badge
  override-row (visible only when overrides exist): count chip + reset button
\`\`\`
- Context bar sits ABOVE the split layout, not inside a toolbar
- Changes to the context bar reload downstream content
- Override badge shows how many items differ from the default

---

## 4c. Multi-Warehouse Allocation Pattern

When a workflow asks the user to reserve stock **per item** and that stock can come from
more than one warehouse, render the item's allocation area as a **vertical stack of
warehouse cards**, not a single default-source picker with overrides.

### When to use
- Any stock-aware selection step where the requested item quantity may exceed what a
  single warehouse holds.
- Any workflow where the system can rank warehouses (FEFO / FIFO / proximity) and the
  user needs to see *all* warehouses that can contribute.

### Do NOT use
- A "default source warehouse + per-item overrides" pattern. That model forces the user
  to reason about what the default hides; stacked cards always show what is actually
  reservable.

### Card anatomy (per warehouse)
\`\`\`
article.ops-allocation-card (role="group", aria-label="Warehouse: {name}")
  header:
    warehouse icon + name
    rank pill (e.g. "Primary FEFO", "+1 FIFO", "+2 FIFO")
    available-at-this-warehouse count
    remove button (icon "close", only if canRemove())
  metric-row (5 compact KPIs):
    REQUESTED (the item's full requested qty — same across cards)
    AVAILABLE HERE
    ALLOCATING (this card's input value)
    SHORTFALL (the parent-computed remaining across all cards)
    STATUS (filled / partial / empty — tone follows value)
  batch-detail (collapsed by default):
    expand affordance reveals the FEFO/FIFO-ordered batch table
    batch row: lot no | batch date | expiry | available | reserved | qty-to-reserve
  footer:
    qty input (mat-form-field, type="number", min=0, max=availableHere)
    inline validation (e.g. "Cannot exceed 300 available")
\`\`\`

### Stacking and ordering rules
- The **first card** is always the backend-ranked primary warehouse for that item's
  FEFO/FIFO rule. It has \`canRemove = false\` when it is the only card.
- Additional cards appear in rank order beneath the primary card. Each card displays its
  rank badge (\`Primary FEFO\`, \`+1 FIFO\`, ...). Ranks are 1-indexed.
- Users can add a warehouse via an **Add warehouse** footer button that opens a
  \`mat-menu\` dropdown showing ONLY warehouses that hold a positive available qty of
  the selected item AND are not already rendered as a card. Never allow duplicates.
- Backend pre-computes greedy FEFO/FIFO quantities: first card gets
  \`min(available, requested)\`, second gets the new remainder, etc. Users can edit freely.

### Aggregate bar
Under the card stack, show an aggregate reservation bar:
\`\`\`
ops-allocation-summary
  "Reserving {sum} of {requested}"
  "Shortfall {remaining}" (hidden when zero)
  status tone tracks filled/partial/empty with matching mat-icon
\`\`\`
When shortfall > 0, reveal a compact hint: "Add another warehouse to fully fulfill this item."

### State and API contract
- Per-item state shape: \`{ itemId, entries: Array<{warehouseId, qty, batches[]}> }\`
- Backend response shape: \`items[].warehouse_cards: Array<{warehouse_id, warehouse_name, total_available, suggested_qty, batches[], issuance_order}>\`
- Commit payload emits one allocation line per (item, warehouse, batch) so the database's
  \`OperationsAllocationLine\` unique constraint on
  \`(package, source_warehouse_id, batch_id, item_id)\` is respected.
- Total reserved qty is the sum across all cards; validation fails if any card's qty
  exceeds its warehouse's available.

### Accessibility
- Each card is a \`role="group"\` with \`aria-label\` derived from the warehouse name.
- Status tones always pair with \`<mat-icon>\` + text (no color-only signaling).
- Qty input has a matching \`<mat-label>\`, \`aria-describedby\` pointing at the validation hint,
  and keyboard up/down increments 1 by default.
- The remove button announces \`aria-label="Remove {warehouse name} from allocation"\`.

---

## 4d. Workflow Abandon Pattern (Cancel vs Back)

Multi-step workflows (wizards, stepper flows) need a **clear distinction** between
\`Back to Request\` (navigation) and \`Cancel\` (revert the work-in-progress on the server).
Do not collapse them into a single button.

### Button semantics
| Button | Intent | Server effect | Placement |
|--------|--------|---------------|-----------|
| Back to Request | Navigate away, keep draft | None | Far left, tertiary link style |
| Save Draft | Persist in-memory edits | Upsert draft state | Center, secondary stroked |
| Cancel | Abandon + revert on server | Release locks, delete draft, return to prior state | Left of Save Draft, destructive stroked-warn |
| Primary | Move to next step or commit | Varies by step | Far right, mat-flat-button color="primary" |

### Cancel copy (mandatory confirm dialog)
\`\`\`
Title:   Cancel this {workflow}?
Body:    This releases any reserved stock and returns the record to the
         queue so another operator can start fresh. You cannot undo this.
Confirm: Cancel {workflow}   (warn)
Decline: Keep working
\`\`\`
Never let Cancel fire without a confirm dialog. Use \`DmisConfirmDialogComponent\` with
\`confirmColor="warn"\` and an icon of \`cancel\` or \`restart_alt\`.

### Backend contract
- The cancel action must call a **dedicated abandon-draft endpoint** — do NOT reuse any
  endpoint named \`cancel\` if that endpoint moves the record to a terminal state.
- The endpoint MUST:
  - Release any package / record lock held by the current actor.
  - Reverse reserved stock deltas.
  - Delete draft allocation lines.
  - Return the parent relief request to its prior workflow status (e.g.
    \`APPROVED_FOR_FULFILLMENT\`).
  - Accept an optional \`reason\` string (max 500 chars, \`.strip()\`).
  - Accept an \`Idempotency-Key\` header so a retry after a flaky network does not
    corrupt the audit trail.
  - Refuse to run if the record has already advanced past a revertible state (dispatched,
    received, split, cancelled).

### Client wiring
- Show Cancel on **every** wizard step (not just step 1), because field users may realize
  in step 2 or 3 that another officer needs the request.
- Disable Cancel while \`submitting()\` or \`savingDraft()\` is true.
- On success: show a success toast ("Fulfillment cancelled. Stock released.") and
  navigate to the parent request detail or queue. Do NOT pop back into the wizard.
- On error: show an error toast with the server message, stay on the current step.

### When Cancel should be hidden
- Step 4 (Confirmation) after a successful commit — the work is done, there is nothing
  to abandon.
- Read-only views (plan pending override approval that the current user cannot act on).

### Async content swap
When a user action triggers a data reload for part of the page:
- Do NOT clear the DOM and show a full loading state
- Show a shimmer overlay on just the affected region
- Keep surrounding content visible and interactive
- Cross-fade with \`opacity\` transition (180ms ease)
- Support \`prefers-reduced-motion\`: instant swap, no animation
- Use a \`switching\` signal separate from the main \`loading\` signal

---

## 4e. Stock-Status Dashboard Pattern (Supply Replenishment)

The Supply Replenishment Dashboard (SRD) is the canonical pattern for **multi-warehouse
operational surveillance** screens: a hero band announcing the active event, a filter
toolbar, one card per warehouse, and inline detail tables. Copy this pattern for any
"monitor many locations at once" screen.

### Namespace
All classes use the \`srd-*\` prefix (\`srd-hero\`, \`srd-toolbar\`, \`srd-warehouses\`,
\`srd-wh-card\`, \`srd-wh-card__parish\`, etc.). Do **not** reuse the \`ops-*\` operations
namespace — the SRD is its own layout with its own tokens (\`--dash-surface\`,
\`--dash-border\`, \`--dash-muted\`).

### Page anatomy
\`\`\`
srd-hero (white band — matches ops-hero--with-context)
  eyebrow:  "ACTIVE EVENT" (letterspaced, muted)
  title:    event name (clamp 1.6rem – 2.05rem, weight 800, tight letterspacing)
  meta:     phase chip | demand/planning windows | last refreshed
  actions:  Refresh + Configure Windows (only if manageable_by_active_tenant)

srd-toolbar (flex-wrap — never CSS grid)
  group--search:   input, flex: 1 1 240px, min-width: 200px
  group--scope:    native <select> wrapped in srd-toolbar__select-wrap
  group--severity: chip filters (Critical / Warning / Watch / OK)
  group--sort:     sort buttons (Time to stockout / Gap)
  group--actions:  margin-left:auto; Export / Refresh

srd-warehouses (transparent container — NO outer frame)
  srd-warehouses__body (flex column, gap: 12px, padding: 4px)
    srd-wh-card  (each warehouse = its own bordered card, expandable)
    srd-wh-card
    ...

srd-empty-state (filter-aware — see Empty State below)
\`\`\`

### Hero band rules
- Background: \`var(--color-surface-container-lowest, #ffffff)\` — plain white.
- Border: \`1px solid rgba(55, 53, 47, 0.08)\`, radius \`0.75rem\`, shadow
  \`0 1px 3px rgba(0, 0, 0, 0.04)\`.
- Title and eyebrow MUST declare \`font-family: var(--dmis-font-sans)\` explicitly —
  Material's global font can otherwise override and break visual consistency with the
  Operations hero (\`ops-hero--with-context\`).
- Phase chip uses phase-colored tone (SURGE red, STABILIZED amber, BASELINE green) and
  includes an icon.
- "Configure Windows" button is only rendered when
  \`canManagePhaseWindows() === true\`, which is a \`computed\` of
  \`phaseWindows()?.manageable_by_active_tenant\`. Never show the action if the backend
  did not confirm the tenant can manage.

### Toolbar rules
- Use \`display: flex; flex-wrap: wrap; column-gap: 18px; row-gap: 10px\` — NOT
  \`display: grid\`. Grid toolbars overflow on narrow viewports and overlap at 100%
  browser zoom.
- Every group gets a sensible \`flex\` basis so reflow is predictable. Search grows
  (\`flex: 1 1 240px\`), actions pin right (\`margin-left: auto\`), buttons use
  \`white-space: nowrap\`.
- Warehouse scope is a **native \`<select>\`** wrapped in \`.srd-toolbar__select-wrap\` —
  NOT a \`mat-menu\` trigger. Native select is accessible, keyboard-friendly, works on
  mobile without custom code, and never collapses into an invisible state. The wrapper
  adds the leading \`warehouse\` icon and trailing \`expand_more\` chevron via absolute
  positioning; the select itself is \`appearance: none\`.
- Severity chips are \`role="radiogroup"\` with an \`aria-label\`. Each chip shows text +
  icon + count — never color alone.

### Per-warehouse card (the load-bearing unit)
\`\`\`
article.srd-wh-card (own border, own radius, own shadow, own expand state)
  ::before         colored left accent bar whose tone = worst severity in the card
                   (hidden when [open] to keep expanded body clean)
  header (clickable — toggles [open])
    srd-wh-card__name
      warehouse name
      srd-wh-card__parish (muted): "· {parish_name} ({parish_code})"
    srd-wh-card__meta
      severity summary chips (Critical / Warning / Watch / OK counts)
      items-at-risk count
      chevron (rotates on open)
  body (revealed when [open])
    items table (9 columns — see below)
    srd-wh-card__actions: "Open needs list" / "Jump to warehouse detail"
\`\`\`
- Cards are siblings in a flex column — never nested inside a single outer "warehouses
  panel" frame. Each card owns its own border + shadow; the outer container is
  transparent.
- When \`[open]\`: card background becomes \`var(--dash-surface)\` (white/cream neutral),
  the \`::before\` accent is hidden, and the stale-data banner (\`srd-wh-card__stale-note\`)
  is **not rendered** — stale information already shows in the hero's "last refreshed"
  field.
- Parish display: use \`getWarehouseParish(warehouseId)\` (client-side lookup against
  \`allWarehouses\`) with optional chaining on \`parish_name\` / \`parish_code\`. Omit the
  parish span entirely when both are empty. When name equals code, show just one.
- Backend \`get_warehouses()\` must LEFT JOIN \`parish\` on \`warehouse.parish_code\` so
  warehouses without a parish row don't disappear.

### Items table schema (inside card body)
Nine columns, in order: **Severity · Item · Available · Inbound · Burn rate ·
Time to stockout · Required · Gap · Conf.** On narrow viewports the table degrades to a
stacked card list, not a horizontal scroll. Each row's severity cell pairs an icon + a
tone class (\`severity-critical\`, \`severity-warning\`, \`severity-watch\`, \`severity-ok\`).

### Time-to-stockout cell
- Render as **plain colored text** — no background fill, no border-left accent bar, no
  progress bar, no hover transform. Historical designs included all of these and they
  cluttered the scan view.
- Colors (severity-only, with icon backup elsewhere in the row):
  \`critical #B42318\`, \`warning #B54708\`, \`watch #B54708\`, \`ok #067647\`.
- Keep the countdown format short: "6h 12m" / "2d 4h" / "> 72h".

### Phase-aware freshness panel
Show a small "Data freshness" panel whose thresholds follow the active phase:
\`HIGH < 2h\`, \`MEDIUM 2–6h\`, \`LOW > 6h\`. The panel is informational, not a blocker —
users must still be able to act on stale data during a disaster.

### Categories panel
Below the warehouse stack, render a categories segmented bar showing the severity
distribution across item categories (Food, Shelter, WASH, Medical, ...). This is the
only cross-warehouse roll-up on the page.

### Empty state (must remain filter-aware)
- The toolbar must render whenever \`activeEvent && (warehouseGroups.length > 0 ||
  allWarehouses.length > 0)\`. If the guard is "\`warehouseGroups.length > 0\`" alone, a
  user who filters to a healthy warehouse loses the filter UI and gets stuck.
- When a scope filter is active and zero items match, show an empty-state card reading
  "No items at risk in this warehouse" with a "Show all warehouses" button that calls
  \`clearWarehouseFilter()\`. Never hide the toolbar.

### Responsive rules
- All SRD components must stay clean from 320px through 1920px and between 90%-125%
  browser zoom.
- Toolbar reflows via \`flex-wrap\`, not media queries.
- Tables degrade to stacked rows under ~720px.
- Hero title uses \`clamp(1.6rem, 2.4vw, 2.05rem)\` so it scales with viewport.

### Tokens and palette
- Primary surface: \`--dash-surface\`
- Border: \`--dash-border\`
- Muted text: \`--dash-muted\`
- Hero surface: \`--color-surface-container-lowest\` (reuse so SRD and ops-hero never
  drift apart)
- Font: \`--dmis-font-sans\` declared explicitly on hero title + eyebrow

### Do NOT
- Do NOT put warehouses inside a single outer "warehouses panel" frame — they stack as
  independent cards.
- Do NOT replace the native scope \`<select>\` with a \`mat-menu\`, \`mat-select\`, or
  custom dropdown. Native wins on mobile and accessibility.
- Do NOT tint expanded warehouse cards with warm beige/orange. Expanded = white.
- Do NOT render the "STALE DATA" banner inside the card body; rely on the hero's
  last-refreshed meta.
- Do NOT use a progress bar or background color for time-to-stockout cells.
- Do NOT use a grid toolbar — flex-wrap only.
- Do NOT rely solely on color to communicate severity — always pair with icon + text.

---

## 4f. Work-Pipeline Queue Pattern (canonical — Package Fulfillment)

The **Package Fulfillment Queue (PFQ)** is the canonical visual and structural reference
for every DMIS work-pipeline queue page. **Every queue page — Package Fulfillment,
Dispatch, Receipt, Consolidation, Eligibility Review, and any future queue — must match
this spec end-to-end.** The only things that legitimately vary between queues are:

- the per-queue namespace prefix on feature classes (\`pfq-*\` / \`dqu-*\` / \`rcv-*\` / ...),
- the stage names, stage colors, and per-stage next-action labels,
- the row body copy (fields displayed, chip tones used),
- the sidebar tip content (\`What to do next\`).

Everything else — layout, spacing, typography, tokens, pills, chips, pager, sidebar,
responsive breakpoints, loading/error/empty states, accessibility — is fixed by this
section and must be copied verbatim.

### Namespace rule
Pick a short, lowercase, 3-letter prefix for the queue (\`pfq\` = Package Fulfillment,
\`dqu\` = Dispatch, \`rcv\` = Receipt, \`con\` = Consolidation, \`elg\` = Eligibility
Review). Throughout this section that prefix is referred to as \`{ns}\`. Feature classes
are \`{ns}-hero\`, \`{ns}-metric\`, \`{ns}-row\`, etc. Shared primitives
(\`ops-page-shell\`, \`ops-grid\`, \`ops-grid--split\`, \`ops-panel\`,
\`ops-section__eyebrow\`, \`ops-queue-tile\`, \`ops-queue-row\` — Section 4g) still come
from \`operations-shell.scss\`. Each queue composes the primitive with its own namespaced
feature class.

### Shell-level tokens (copy verbatim per queue)
The root \`.{ns}-shell\` declares the token palette for the page. Stage colors change per
queue; SLA + surface + ink tokens do NOT. This exact token list is the PFQ contract —
ship it unchanged on every queue:

\`\`\`scss
.{ns}-shell {
  // Stage palette — rename tokens per queue but keep the hex values when reusing the
  // amber / indigo / purple / green set. If a queue has different stages, pick tones
  // that read in the same severity family (cool = early, warm = aging, green = done).
  --{ns}-awaiting:  #b7833f;   // amber  — first stage (incoming work)
  --{ns}-drafts:    #3d4b99;   // indigo — paused / in your hands
  --{ns}-preparing: #7a4fd1;   // purple — actively working
  --{ns}-ready:     #2e8a48;   // green  — done / hand off

  // SLA tones (time-in-stage pill). These are FIXED across every queue.
  --{ns}-breach:    #b42318;
  --{ns}-warn:      #b54708;
  --{ns}-fresh:     #067647;

  // Surface + text tokens. These are FIXED across every queue.
  --{ns}-surface:       var(--color-surface-container-lowest);
  --{ns}-surface-warm:  #f5f1e8;
  --{ns}-border:        rgba(55, 53, 47, 0.12);
  --{ns}-border-soft:   rgba(55, 53, 47, 0.08);
  --{ns}-ink:           #1f1b14;
  --{ns}-ink-muted:     #5a554a;
  --{ns}-primary:       #1f2a5a;    // focus ring + primary button fill

  display: grid;
  gap: 1.1rem;
}
\`\`\`

Do NOT set \`font-family\` on the shell or any descendant — the system sans stack is
inherited app-wide, and overriding it breaks visual consistency with the SRD and the
ops hero. Numeric text uses \`font-variant-numeric: tabular-nums\` (NOT a monospace
font-family).

### Page anatomy — full DOM tree (follow exactly)

\`\`\`
div.ops-page-shell.{ns}-shell                    // grid, gap: 1.1rem
  header.{ns}-hero                               // 2-col grid: lead | actions
    div.{ns}-hero__lead                          // stacked, gap: 0.55rem
      p.{ns}-hero__eyebrow                       // "Operations · Package Fulfillment"
        span "Operations"
        span.{ns}-hero__sep aria-hidden "·"
        span "Package Fulfillment"
      h1.{ns}-hero__title                        // queue name (e.g. "Package Fulfillment Queue")
      p.{ns}-hero__copy                          // 1 sentence describing queue purpose + where rows go when they leave
      div.{ns}-hero__context
        span.{ns}-hero__pill.{ns}-hero__pill--status aria-live="polite"
          span.{ns}-hero__pill-dot                // amber dot (stage-neutral visual signal)
          span "Active work"
          span.{ns}-hero__pill-sep "·"
          strong "{activeCount} in queue"
        span.{ns}-hero__pill.{ns}-hero__pill--meta
          mat-icon "schedule"
          span "Updated"
          strong "just now"
        span.{ns}-hero__warehouse "Default warehouse: <strong>{warehouseLabel}</strong>"
    div.{ns}-hero__actions
      @if ({ns}-has-my-drafts) button.{ns}-hero__btn.{ns}-hero__btn--ghost
        "Show my drafts · {count}"
      button.{ns}-hero__btn.{ns}-hero__btn--primary
        mat-icon "refresh"
        "Refresh queue"

  @if (!loading && !errored && actionInbox().length > 0)
    section.{ns}-inbox aria-label="Your action inbox"
      p.{ns}-inbox__eyebrow "Your action inbox"
      div.{ns}-inbox__pills
        @for (pill of actionInbox(); track pill.token)
          button.{ns}-inbox__pill.{ns}-inbox__pill--{severity}    // warning | info | success
            span.{ns}-inbox__badge "{pill.count}"                   // tone follows severity
            span.{ns}-inbox__label "{pill.label}"
            mat-icon.{ns}-inbox__chev "chevron_right"
      a.{ns}-inbox__link routerLink="..."                          // "Open {other} Queue" link
        span "Open Dispatch Queue"
        mat-icon "open_in_new"

  app-ops-metric-strip
    [items]="queueMetrics()"                                       // OpsMetricStripItem[]
    (itemClick)="openMetric($event)"                               // stage filter toggle
    aria-label="Queue metrics"
    //
    // queueMetrics() returns 3–4 items. Each item carries:
    //   label     "Awaiting Fulfillment" (Title-Case)
    //   value     "{count}"              (1.9rem, tabular-nums, owned by the component)
    //   hint      "New work in queue"    (short explainer under value)
    //   token     'awaiting'|'drafts'|'preparing'|'ready'|'transit'|'completed'|'info'|'neutral'
    //   badge     { label: 'AWAITING', tone: 'awaiting' }  // top-right pill with leading dot
    //   interactive: true                // renders as <button>, aria-pressed mirrors active
    //   active:      activeFilter() === 'awaiting'
    //
    // Do NOT hand-roll .{ns}-metric / .pfq-metric / .ops-queue-tile SCSS for KPIs.

  div.ops-grid.ops-grid--split.{ns}-split                          // 1fr | 18rem, collapses < 1180px
    section.ops-panel.{ns}-panel                                   // LEFT: work queue
      div.{ns}-panel__header                                       // flex, space-between
        div.{ns}-panel__heading
          p.ops-section__eyebrow "Queue"
          h2.{ns}-panel__title   "Fulfillment Work Queue"
          p.{ns}-panel__copy     "Search and filter requests awaiting fulfillment, saved as drafts, preparing, or ready to commit."
        span.{ns}-panel__meta    "{N} requests"                     // tabular-nums
      div.{ns}-panel__body
        label.{ns}-search                                          // full-width search input
          mat-icon "search"
          input type="search" placeholder="Search by tracking number, agency, event, or notes"
        div.{ns}-toolbar                                           // flex-wrap, space-between
          div.{ns}-chips role="radiogroup" aria-label="Filter queue by stage"
            @for (filter of filterOptions; track filter.value)
              button.{ns}-chip
                [.{ns}-chip--active]="activeFilter() === filter.value"
                [.{ns}-chip--unread]="hasUnread(filter.value)"
                role="radio" [aria-checked] [tabindex]              // radiogroup semantics
                span.{ns}-chip__label  "All" | "Awaiting" | ...
                span.{ns}-chip__count  "{count}"                    // tabular-nums
                @if (hasUnread) span.{ns}-chip__unread  "{unread}"  // red dot badge
          div.{ns}-selects role="group" aria-label="Queue sort and scope"
            label.{ns}-select                                      // native <select>, NOT mat-select
              span.{ns}-select__label "Priority:"
              select.{ns}-select__control                          // appearance: none
              mat-icon "expand_more"
            label.{ns}-select ... "Warehouse:"
            label.{ns}-select ... "Sort:"                          // "Oldest first" | "Newest first"

        @if (loading())
          dmis-skeleton-loader variant="table-row" [count]="5"
        @else if (errored())
          dmis-empty-state icon="error_outline" title="..." [message] actionLabel="Retry" (action)
        @else if (filteredItems().length === 0)
          div.{ns}-empty
            dmis-empty-state icon="inbox"
              title="No active {queue} work"
              message="Dispatched and received packages have moved on. New approved requests will appear here."
        @else
          div.{ns}-rows role="list"                                // grid, gap: 0.6rem
            @for (row of pagedItems(); track trackByRequestId)
              article.ops-queue-row.{ns}-row.ops-row--{stage}       // primitive + feature + stage
                tabindex="0" role="listitem"
                (click) (keydown.enter) (keydown.space.prevent) -> row's primary action
                div.{ns}-row__lead                                 // LEFT: identity + signals
                  div.{ns}-row__title                              // flex-wrap line
                    span.{ns}-row__id        "RQ95012"             // tabular-nums
                    @if (pkgNo) span.{ns}-row__pkg
                      span.{ns}-row__pkg-label "PKG"               // uppercase pill
                      span.{ns}-row__pkg-value "{pkgNo}"
                    span.{ns}-row__urgency.{ns}-row__urgency--{tone}    "HIGH" | ...
                    span.{ns}-row__authority.{ns}-row__authority--{tone}
                      span.{ns}-row__authority-dot
                      "Approved"
                  p.{ns}-row__party  "{agencyName}"                // weight 600
                  p.{ns}-row__meta                                 // flex-wrap inline line
                    span.{ns}-row__meta-item
                      mat-icon "warning_amber" | "inventory_2" | "apartment"
                      span "{event | itemCount | destinationWarehouse}"
                    span.{ns}-row__meta-sep "·"
                    span "Created {datetime}"
                div.{ns}-row__next                                 // RIGHT: stage + action
                  div.{ns}-row__pills
                    span.{ns}-stage-pill.{ns}-stage-pill--{stage}
                      span.{ns}-stage-pill__dot
                      "DRAFT"                                      // uppercase
                    span.{ns}-time-pill.{ns}-time-pill--{tone}
                      mat-icon "schedule"
                      span "3 days in stage"                       // tabular-nums
                  button.{ns}-action.{ns}-action--{stage}
                    span "{nextActionLabel}"                       // "Allocate stock" | "Resume draft" | ...
        @if (filteredItems().length > 0)
          footer.{ns}-pager role="navigation" aria-label="Queue pagination"
            span.{ns}-pager__range
              "Showing <strong>{start}–{end}</strong> of <strong>{total}</strong> · Page <strong>{current}</strong> of <strong>{total}</strong>"
            @if (totalPages() > 1)
              div.{ns}-pager__nav
                button.{ns}-pager__btn aria-label="Previous page" "‹"
                @for (n of visiblePages())
                  @if (n === 'ellipsis')
                    span.{ns}-pager__ellipsis "…"
                  @else
                    button.{ns}-pager__btn
                      [.{ns}-pager__btn--active]="n === currentPage()"
                      [aria-current]="n === currentPage() ? 'page' : null"
                      "{n}"
                button.{ns}-pager__btn aria-label="Next page" "›"

    aside.{ns}-sidebar aria-label="Queue workload and guidance"    // RIGHT: persistent aid
      section.{ns}-side-card                                       // "Workload / Queue at a glance"
        div.{ns}-side-card__header
          p.{ns}-side-card__eyebrow "Workload"
          h2.{ns}-side-card__title  "Queue at a glance"
        div.{ns}-glance
          div.{ns}-glance__row.{ns}-glance__row--total
            span.{ns}-glance__label "Total shown"
            span.{ns}-glance__value.{ns}-glance__value--lg "{total}"
          div.{ns}-glance__grid                                    // 2-col grid
            @for stage of [awaiting, drafts, preparing, ready]
              div.{ns}-glance__cell
                span.{ns}-glance__label "{Stage}"                   // uppercase
                span.{ns}-glance__value.{ns}-glance__value--{stage} "{count}"
      section.{ns}-side-card                                       // "Guidance / What to do next"
        div.{ns}-side-card__header
          p.{ns}-side-card__eyebrow "Guidance"
          h2.{ns}-side-card__title  "What to do next"
        ul.{ns}-tips role="list"
          @for stage of [awaiting, drafts, preparing, ready]        // exactly 4 tips
            li.{ns}-tips__item                                     // dot color = stage token
              span.{ns}-tips__dot
              div.{ns}-tips__body
                p.{ns}-tips__title "{one-line stage heading}"
                p.{ns}-tips__meta  "{one-sentence instruction for the operator}"
\`\`\`

**Consistency rule**: This tree is the complete queue page. The metric strip + action
inbox + filter chips stay as global top-of-page context. The left panel carries the
active work queue. The right aside carries the persistent "Queue at a glance" summary
and "What to do next" guidance; it is the steady orientation aid that helps new
operators learn the pipeline and senior operators keep their bearings mid-shift. The
sidebar collapses below the panel at 1180px — it never disappears, it only restacks.

### Hero band — exact SCSS contract
\`\`\`scss
.{ns}-hero {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: start;
  gap: 1.25rem;
  padding: 1.25rem 1.35rem 1.1rem;
  background: var(--{ns}-surface);
  border: 1px solid var(--{ns}-border-soft);
  border-radius: 1rem;
  box-shadow: 0 18px 36px rgba(26, 28, 28, 0.04);
}
.{ns}-hero__eyebrow {
  font-size: 0.72rem; letter-spacing: 0.18em; text-transform: uppercase;
  color: var(--{ns}-ink-muted); font-weight: var(--weight-semibold, 600);
}
.{ns}-hero__title {
  font-size: 1.6rem; line-height: 1.2; letter-spacing: -0.01em;
  font-weight: var(--weight-semibold, 600); color: var(--{ns}-ink);
}
.{ns}-hero__copy {
  max-width: 70ch; font-size: 0.92rem; line-height: 1.5; color: var(--{ns}-ink-muted);
}
.{ns}-hero__pill {
  display: inline-flex; align-items: center; gap: 0.4rem;
  padding: 0.35rem 0.75rem; border-radius: 999px;
  background: var(--{ns}-surface-warm); border: 1px solid var(--{ns}-border-soft);
  font-size: 0.78rem; color: var(--{ns}-ink);
}
.{ns}-hero__pill--status {              // stage-1 (amber) status pill
  background: #fbf3e5;
  border-color: rgba(183, 131, 63, 0.24);
}
.{ns}-hero__pill-dot {                  // 8px dot, amber by default
  width: 8px; height: 8px; border-radius: 999px;
  background: var(--{ns}-awaiting);
}
.{ns}-hero__btn {
  display: inline-flex; align-items: center; gap: 0.4rem;
  padding: 0.55rem 0.95rem; border-radius: 10px;
  border: 1px solid var(--{ns}-border);
  background: var(--{ns}-surface); color: var(--{ns}-ink);
  font-size: 0.85rem; font-weight: var(--weight-semibold, 600);
  transition: background 120ms ease, border-color 120ms ease, transform 120ms ease, box-shadow 120ms ease;
  &:hover { transform: translateY(-1px); box-shadow: 0 8px 18px rgba(26, 28, 28, 0.08); }
  &:focus-visible { outline: 2px solid var(--{ns}-primary); outline-offset: 2px; }
}
.{ns}-hero__btn--primary {              // Refresh button — always dark ink fill
  background: var(--{ns}-primary);
  border-color: var(--{ns}-primary);
  color: #fff;
  &:hover { background: #162046; }
}
\`\`\`

- The hero has TWO columns on desktop (content | actions) and collapses to a single
  column under 900px, where actions left-align under the title.
- The "Show my drafts" ghost button is rendered only when
  \`filterChipCounts().drafts > 0\` — never show a zero-count draft shortcut.
- The primary button uses \`--{ns}-primary\` (\`#1f2a5a\`), NOT Material
  \`color="primary"\`. Don't swap in \`mat-flat-button\` here — the hero button has its own
  compact sizing.

### Action inbox strip — exact SCSS contract
\`\`\`scss
.{ns}-inbox {
  display: grid;
  grid-template-columns: 1fr auto;
  grid-template-areas:
    "eyebrow link"
    "pills   link";
  column-gap: 1rem; row-gap: 0.65rem;
  align-items: center;
  padding: 0.9rem 1.1rem;
  background: var(--{ns}-surface);
  border-radius: 1rem;
  border: 1px solid var(--{ns}-border-soft);
  box-shadow: 0 18px 36px rgba(26, 28, 28, 0.04);
}
.{ns}-inbox__pill {
  display: inline-flex; align-items: center; gap: 0.55rem;
  padding: 0.4rem 0.6rem 0.4rem 0.45rem;
  border-radius: 999px;
  border: 1px solid var(--{ns}-border);
  background: var(--{ns}-surface); color: var(--{ns}-ink);
  font-size: 0.82rem; font-weight: var(--weight-semibold, 600);
}
.{ns}-inbox__badge {                    // circular count chip
  min-width: 1.55rem; height: 1.55rem; padding: 0 0.4rem;
  border-radius: 999px;
  background: var(--{ns}-ink); color: #fff;
  font-size: 0.78rem; font-variant-numeric: tabular-nums;
}
.{ns}-inbox__pill--warning .{ns}-inbox__badge { background: var(--{ns}-breach); }
.{ns}-inbox__pill--info    .{ns}-inbox__badge { background: #2a3880; }
.{ns}-inbox__pill--success .{ns}-inbox__badge { background: var(--{ns}-ready); }
\`\`\`

- The inbox is rendered only when the viewer has at least one pending action — never
  as empty chrome.
- The "Open {Other} Queue" \`.{ns}-inbox__link\` sits in the \`link\` grid area on
  desktop; under 900px it restacks below the pills.
- At <640px, inbox pills become full-width (\`flex: 1 1 100%\`).

### KPI metric strip — use \`<app-ops-metric-strip>\`, do NOT hand-roll SCSS

Every operations queue page renders its KPI cards through the shared
\`<app-ops-metric-strip>\` component in \`operations/shared/ops-metric-strip.component.ts\`.
The component encapsulates the entire PFQ-aligned tile chrome:

- Flat rectangular left-edge accent bar (\`::before\`, clipped by card radius)
- Title-Case label (0.82rem) + large tabular-nums value (1.9rem) + muted hint (0.78rem)
- Optional top-right badge pill with a leading coloured dot — mirrors \`.pfq-metric__badge\`
- Hover lift, focus-visible outline, \`aria-pressed\` when interactive
- 8 built-in tones driving both the accent bar and the badge pill:
  \`awaiting\` / \`drafts\` / \`preparing\` / \`ready\` (PFQ palette) and
  \`transit\` / \`completed\` / \`info\` / \`neutral\` (extended ops palette)

Callers provide data, not SCSS:

\`\`\`ts
import { OpsMetricStripComponent, OpsMetricStripItem } from '../shared/ops-metric-strip.component';

@Component({
  imports: [OpsMetricStripComponent, /* ... */],
  template: \`
    <app-ops-metric-strip
      [items]="queueMetrics()"
      (itemClick)="openMetric($event)"
      aria-label="Queue summary" />
  \`,
})
export class MyQueueComponent {
  readonly activeFilter = signal<StageFilter>('awaiting');
  readonly counts = computed(() => /* ... */);

  readonly queueMetrics = computed<readonly OpsMetricStripItem[]>(() => [
    { label: 'Awaiting',  value: String(this.counts().awaiting),  hint: 'Needs triage',
      token: 'awaiting',  interactive: true, active: this.activeFilter() === 'awaiting',
      badge: { label: 'AWAITING',  tone: 'awaiting'  } },
    { label: 'Drafts',    value: String(this.counts().drafts),    hint: 'In progress',
      token: 'drafts',    interactive: true, active: this.activeFilter() === 'drafts',
      badge: { label: 'DRAFT',     tone: 'drafts'    } },
    { label: 'Preparing', value: String(this.counts().preparing), hint: 'Picking & packing',
      token: 'preparing', interactive: true, active: this.activeFilter() === 'preparing',
      badge: { label: 'PREPARING', tone: 'preparing' } },
    { label: 'Ready',     value: String(this.counts().ready),     hint: 'Hand off to dispatch',
      token: 'ready',     interactive: true, active: this.activeFilter() === 'ready',
      badge: { label: 'READY',     tone: 'ready'     } },
  ]);

  openMetric(item: OpsMetricStripItem): void {
    const filter = this.tileTokenToFilter(item.token);
    if (filter) this.activeFilter.set(filter);
  }
}
\`\`\`

**Rules**:
- 3–4 tiles, one per stage the queue exposes. Never add a 5th "All" card — the "all"
  pivot belongs on the filter chips, not the metric strip.
- \`interactive: true\` + \`active: activeFilter() === stage\` makes each tile a filter
  toggle. The component renders \`<button>\` with \`aria-pressed\` reflecting \`active\`.
- \`token\` drives the accent bar colour. \`badge.tone\` drives the pill and dot colour —
  normally the same tone, but pages may mix (e.g. \`info\` tile + \`drafts\` badge).
- Badge labels are short ALL-CAPS (\`AWAITING\`, \`DRAFT\`, \`PREPARING\`, \`READY\`,
  \`DISPATCHED\`, \`DONE\`) — the component handles letter-spacing, uppercasing, and the
  leading coloured dot.
- Never hand-roll \`.{ns}-metric\` / \`.pfq-metric\` / \`.ops-queue-tile\` SCSS to build a
  KPI tile. That composition is superseded by this shared component.

### Split layout + panel header — exact SCSS contract
\`\`\`scss
// Two-class selector wins over the shared .ops-grid--split default (1.6fr / 0.9fr)
// which otherwise gives the sidebar too much column on wide viewports.
.ops-grid--split.{ns}-split {
  grid-template-columns: minmax(0, 1fr) 18rem;
  gap: 1.1rem;
}
.{ns}-panel { min-width: 0; }
.{ns}-panel__header {
  display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem;
}
.{ns}-panel__heading { display: grid; gap: 0.2rem; min-width: 0; }
.{ns}-panel__title {
  font-size: 1.1rem; font-weight: var(--weight-semibold, 600);
  letter-spacing: -0.01em; color: var(--{ns}-ink);
}
.{ns}-panel__copy {                     // the one-sentence panel description
  font-size: 0.85rem; color: var(--{ns}-ink-muted); line-height: 1.5;
}
.{ns}-panel__meta {                     // "{N} requests" count pill
  flex-shrink: 0; font-size: 0.8rem; color: var(--{ns}-ink-muted);
  font-variant-numeric: tabular-nums; font-weight: var(--weight-semibold, 600);
}
.{ns}-panel__body { display: grid; gap: 0.85rem; padding-top: 0.85rem; }
\`\`\`

Omitting the one-sentence \`.{ns}-panel__copy\` description is a regression — new
operators rely on it to understand what the panel is showing.

### Search + toolbar (chips + native selects) — exact SCSS contract
\`\`\`scss
.{ns}-search {                          // full-width search row
  display: inline-flex; align-items: center; gap: 0.55rem;
  padding: 0.65rem 0.9rem;
  background: var(--{ns}-surface);
  border: 1px solid var(--{ns}-border);
  border-radius: 10px;
  &:focus-within {
    border-color: var(--{ns}-primary);
    box-shadow: 0 0 0 3px rgba(31, 42, 90, 0.12);
  }
  input {
    flex: 1; border: none; background: transparent;
    font-size: 0.88rem; color: var(--{ns}-ink);
    &:focus { outline: none; }
    &::placeholder { color: var(--{ns}-ink-muted); }
  }
}

.{ns}-toolbar {
  display: flex; flex-wrap: wrap; align-items: center; gap: 0.75rem;
  justify-content: space-between;       // chips left, selects right
}
.{ns}-chips { display: inline-flex; flex-wrap: wrap; gap: 0.4rem; }

.{ns}-chip {                            // radio chip
  display: inline-flex; align-items: center; gap: 0.45rem;
  padding: 0.4rem 0.75rem; border-radius: 999px;
  border: 1px solid var(--{ns}-border);
  background: var(--{ns}-surface); color: var(--{ns}-ink);
  font-size: 0.82rem; font-weight: var(--weight-semibold, 600);
  &:hover          { background: var(--{ns}-surface-warm); }
  &:focus-visible  { outline: 2px solid var(--{ns}-primary); outline-offset: 2px; }
}
.{ns}-chip--active {                    // dark-ink fill when selected
  background: var(--{ns}-ink); color: #fff; border-color: var(--{ns}-ink);
}
.{ns}-chip__count {                     // inline count badge, tabular-nums
  min-width: 1.4rem; padding: 0 0.4rem; border-radius: 999px;
  background: rgba(55, 53, 47, 0.08); color: var(--{ns}-ink-muted);
  font-size: 0.7rem; line-height: 1.4rem; text-align: center;
  font-variant-numeric: tabular-nums;
}
.{ns}-chip--active .{ns}-chip__count {
  background: rgba(255, 255, 255, 0.22); color: inherit;
}
.{ns}-chip__unread {                    // red unread badge — appears only when hasUnread()
  min-width: 1.2rem; padding: 0 0.35rem; border-radius: 999px;
  background: var(--{ns}-breach); color: #fff;
  font-size: 0.68rem; line-height: 1.2rem; text-align: center;
  font-variant-numeric: tabular-nums;
}

.{ns}-selects { display: inline-flex; flex-wrap: wrap; gap: 0.5rem; }
.{ns}-select {                          // wraps a native <select> + leading label + trailing icon
  display: inline-flex; align-items: center; gap: 0.4rem;
  padding: 0.35rem 0.5rem 0.35rem 0.75rem;
  border-radius: 10px;
  border: 1px solid var(--{ns}-border);
  background: var(--{ns}-surface);
  font-size: 0.82rem; color: var(--{ns}-ink);
  &:focus-within {
    border-color: var(--{ns}-primary);
    box-shadow: 0 0 0 3px rgba(31, 42, 90, 0.12);
  }
}
.{ns}-select__label   { color: var(--{ns}-ink-muted); font-size: 0.78rem; font-weight: 600; }
.{ns}-select__control {
  appearance: none; background: transparent; border: none; padding: 0;
  font-size: 0.82rem; color: var(--{ns}-ink); font-weight: 600; cursor: pointer;
}
\`\`\`

- **Filter chips are \`role="radiogroup"\` with \`role="radio"\` children** — full
  keyboard navigation via arrow keys (implement \`onFilterKeydown(event, index)\`). The
  chips render \`All\` first, followed by one per stage in pipeline order.
- **Priority / Warehouse / Sort are native \`<select>\`** with \`appearance: none\`,
  wrapped by \`.{ns}-select\` — NOT \`mat-select\`. Native wins on mobile, accessibility,
  and keyboard support. The same rule applies on the SRD (Section 4e) for the
  warehouse-scope selector.
- The toolbar is \`display: flex; flex-wrap: wrap\` with \`justify-content:
  space-between\` — NOT a grid. Grid toolbars overlap at 100% zoom.

### Row anatomy — exact SCSS contract
\`\`\`scss
.{ns}-rows { display: grid; gap: 0.6rem; }

// Composes with .ops-queue-row from operations-shell.scss (Section 4g). The
// primitive supplies background (subtle #f6f5f1 grey), border, radius, and the flat
// ::before accent bar. Feature class carries only layout + interaction.
.{ns}-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;   // lead grows, next-cluster auto-sizes
  align-items: start;
  column-gap: 1rem; row-gap: 0.5rem;
  cursor: pointer;
  transition: background 120ms ease, box-shadow 120ms ease, transform 120ms ease;
  &:hover {
    transform: translateY(-1px);
    box-shadow: 0 10px 20px rgba(26, 28, 28, 0.05);
    --ops-queue-surface: #fbfaf6;       // warm one step on hover without flipping white
  }
  &:focus-visible { outline: 2px solid var(--{ns}-primary); outline-offset: 2px; }
}
.ops-row--awaiting  { --ops-queue-accent: var(--{ns}-awaiting); }
.ops-row--drafts    { --ops-queue-accent: var(--{ns}-drafts); }
.ops-row--preparing { --ops-queue-accent: var(--{ns}-preparing); }
.ops-row--ready     { --ops-queue-accent: var(--{ns}-ready); }

.{ns}-row__lead   { display: grid; gap: 0.3rem; min-width: 0; }
.{ns}-row__title  { display: inline-flex; flex-wrap: wrap; align-items: center; gap: 0.55rem; }
.{ns}-row__id {
  font-size: 0.95rem; font-weight: 600; color: var(--{ns}-ink);
  font-variant-numeric: tabular-nums; letter-spacing: -0.01em;
  // DO NOT apply a monospace font-family here — system sans + tabular-nums only.
}
.{ns}-row__pkg {
  display: inline-flex; align-items: center; gap: 0.3rem;
  font-size: 0.72rem; color: var(--{ns}-ink-muted); font-variant-numeric: tabular-nums;
}
.{ns}-row__pkg-label {                  // uppercase "PKG" pill
  padding: 0.1rem 0.35rem; border-radius: 4px;
  background: var(--{ns}-surface-warm); color: var(--{ns}-ink-muted);
  letter-spacing: 0.08em; text-transform: uppercase; font-size: 0.64rem;
}
.{ns}-row__party  { font-size: 0.88rem; font-weight: 600; color: var(--{ns}-ink); }
.{ns}-row__meta {
  display: inline-flex; flex-wrap: wrap; align-items: center;
  gap: 0.55rem 0.85rem; font-size: 0.78rem; color: var(--{ns}-ink-muted);
}
.{ns}-row__meta-item {
  display: inline-flex; align-items: center; gap: 0.35rem;
  mat-icon { font-size: 16px; width: 16px; height: 16px; line-height: 16px;
             color: var(--{ns}-ink-muted); }
}
.{ns}-row__meta-sep { color: rgba(55, 53, 47, 0.3); }
\`\`\`

The row's **urgency and authority pills** share a tone palette. Reuse these exact
mappings on every queue:

| Class suffix | Background | Text / dot | Border | Use case |
|-------------|-----------|------------|--------|----------|
| \`--danger\`  | \`#fbebea\` | \`var(--{ns}-breach)\` | \`rgba(180, 35, 24, 0.24)\` | HIGH / rejected / critical |
| \`--warning\` | \`#fdf0e3\` | \`var(--{ns}-warn)\`   | \`rgba(181, 71, 8, 0.24)\` | MEDIUM / expiring / warn |
| \`--review\`  | \`#fbf3e5\` | \`#7f5a1f\`            | \`rgba(183, 131, 63, 0.24)\` | Review / awaiting |
| \`--success\` | \`#ebf5ee\` | \`var(--{ns}-fresh)\`  | \`rgba(6, 118, 71, 0.24)\` | Approved / fulfilled |
| \`--draft\`   | \`#eef1fb\` | \`#2a3880\`            | \`rgba(61, 75, 153, 0.24)\` | Draft / pending |
| \`--muted\`   | \`var(--{ns}-surface-warm)\` | \`var(--{ns}-ink-muted)\` | — | Default / LOW |

The urgency pill is uppercase (\`0.06em\` letterspacing) and unpadded to the left of the
icon-less label; the authority pill carries a small \`currentColor\` dot on its left.

### Next-action cluster (stage pill + time pill + action button) — exact SCSS contract
\`\`\`scss
.{ns}-row__next {
  display: grid; gap: 0.5rem;
  align-content: space-between;
  justify-items: end; align-self: stretch; min-width: 0;
}
.{ns}-row__pills {
  display: inline-flex; flex-wrap: wrap; gap: 0.35rem;
  justify-content: flex-end; align-items: center;
}

// Stage pill — uppercase, letterspaced, dot + label
.{ns}-stage-pill {
  display: inline-flex; align-items: center; gap: 0.35rem;
  padding: 0.2rem 0.6rem 0.2rem 0.5rem;
  border-radius: 999px;
  font-size: 0.7rem; font-weight: 600;
  letter-spacing: 0.04em; text-transform: uppercase;
  background: var(--{ns}-surface-warm); color: var(--{ns}-ink-muted);
  border: 1px solid var(--{ns}-border-soft);
}
.{ns}-stage-pill__dot { width: 6px; height: 6px; border-radius: 999px; background: currentColor; }
.{ns}-stage-pill--awaiting  { background: #fbf3e5; color: #7f5a1f; border-color: rgba(183, 131, 63, 0.28); }
.{ns}-stage-pill--drafts    { background: #eef1fb; color: #2a3880; border-color: rgba(61, 75, 153, 0.24); }
.{ns}-stage-pill--preparing { background: #f3ecfb; color: #563898; border-color: rgba(122, 79, 209, 0.24); }
.{ns}-stage-pill--ready     { background: #ebf5ee; color: #225d33; border-color: rgba(46, 138, 72, 0.24); }

// Time-in-stage pill — icon + "X in stage" label, tone follows SLA threshold
.{ns}-time-pill {
  display: inline-flex; align-items: center; gap: 0.3rem;
  padding: 0.2rem 0.55rem; border-radius: 999px;
  font-size: 0.72rem; font-weight: 600;
  font-variant-numeric: tabular-nums; white-space: nowrap;
  background: var(--{ns}-surface-warm); color: var(--{ns}-ink-muted);
  border: 1px solid var(--{ns}-border-soft);
  mat-icon { font-size: 14px; width: 14px; height: 14px; line-height: 14px; }
}
.{ns}-time-pill--fresh   { background: #ebf5ee; color: var(--{ns}-fresh);  border-color: rgba(6, 118, 71, 0.22); }
.{ns}-time-pill--normal  { background: var(--{ns}-surface-warm); color: var(--{ns}-ink-muted); }
.{ns}-time-pill--stale   { background: #fdf0e3; color: var(--{ns}-warn);   border-color: rgba(181, 71, 8, 0.24); }
.{ns}-time-pill--breach  { background: #fbebea; color: var(--{ns}-breach); border-color: rgba(180, 35, 24, 0.24); }

// Action button — auto-sized, anchored bottom-right, stage-tinted
.{ns}-action {
  justify-self: end; width: auto;
  display: inline-flex; align-items: center; justify-content: center;
  gap: 0.4rem; padding: 0.5rem 0.95rem; border-radius: 8px;
  font-weight: 600; font-size: 0.82rem; line-height: 1.1;
  border: 1px solid transparent; cursor: pointer; white-space: nowrap;
  transition: background 120ms ease, transform 120ms ease, box-shadow 120ms ease;
  &:hover { transform: translateY(-1px); box-shadow: 0 8px 18px rgba(26, 28, 28, 0.09); }
  &:focus-visible { outline: 2px solid var(--{ns}-primary); outline-offset: 2px; }
}
.{ns}-action--awaiting  { background: var(--{ns}-ink);   color: #fff;    border-color: var(--{ns}-ink);   &:hover { background: #000; } }
.{ns}-action--drafts    { background: #eef1fb;            color: #2a3880; border-color: rgba(61, 75, 153, 0.32); &:hover { background: #e2e6f5; } }
.{ns}-action--preparing { background: #f3ecfb;            color: #563898; border-color: rgba(122, 79, 209, 0.30); &:hover { background: #e8dff5; } }
.{ns}-action--ready     { background: var(--{ns}-ready); color: #fff;    border-color: var(--{ns}-ready); &:hover { background: #256f3a; } }
\`\`\`

- **Awaiting** and **Ready** use **filled** backgrounds (high emphasis — creating a
  reservation record or handing off to another team). **Drafts** and **Preparing**
  use **soft tinted** backgrounds (medium emphasis — in-progress personal work).
- Never use \`color="primary"\` / \`color="warn"\` on stage action buttons — stage
  tokens, always.
- The action button stops click propagation so the card-level click handler doesn't
  fire twice: \`(click)="...; $event.stopPropagation()"\`.

### Pager — exact SCSS contract
\`\`\`scss
.{ns}-pager {
  display: flex; flex-wrap: wrap;
  align-items: center; justify-content: space-between;
  gap: 0.85rem;
  padding-top: 0.9rem; margin-top: 0.5rem;
  border-top: 1px solid var(--{ns}-border-soft);
  font-size: 0.78rem; color: var(--{ns}-ink-muted);
}
.{ns}-pager__range strong {
  color: var(--{ns}-ink); font-variant-numeric: tabular-nums;
}
.{ns}-pager__nav { display: inline-flex; align-items: center; gap: 0.2rem; }
.{ns}-pager__btn {
  min-width: 2rem; height: 2rem; padding: 0 0.55rem;
  border: 1px solid var(--{ns}-border);
  background: var(--{ns}-surface); color: var(--{ns}-ink-muted);
  border-radius: 8px;
  font-size: 0.82rem; font-weight: 600; font-variant-numeric: tabular-nums;
  cursor: pointer;
  transition: background 120ms ease, color 120ms ease, border-color 120ms ease;
  &:hover:not(:disabled) { background: var(--{ns}-surface-warm); color: var(--{ns}-ink); }
  &:disabled { opacity: 0.4; cursor: not-allowed; }
}
.{ns}-pager__btn--active {              // current page — dark ink fill
  background: var(--{ns}-ink); color: #fff; border-color: var(--{ns}-ink);
  &:hover:not(:disabled) { background: #000; }
}
.{ns}-pager__ellipsis { padding: 0 0.2rem; color: rgba(55, 53, 47, 0.45); }
\`\`\`

Component state (copy verbatim):
- \`page = signal(1)\`, \`PAGE_SIZE = 5\` (bump to 10 only if row density demands it).
- \`currentPage\`, \`totalPages\`, \`pagedItems\`, \`pageRange\`, \`visiblePages\` are
  \`computed()\`s.
- \`onSearch\`, \`setFilter\`, and successful \`loadQueue\` reset \`page\` to 1.
- \`visiblePages()\` returns \`Array<number | 'ellipsis'>\`; track by value.

### Sidebar cards ("Queue at a glance" + "What to do next") — exact SCSS contract
\`\`\`scss
.{ns}-sidebar {
  display: grid; gap: 1rem; align-content: start; min-width: 0;
}
.{ns}-side-card {
  display: grid; gap: 0.75rem;
  padding: 0.95rem 1rem;
  background: var(--{ns}-surface);
  border: 1px solid var(--{ns}-border-soft);
  border-radius: 0.9rem;
  box-shadow: 0 18px 36px rgba(26, 28, 28, 0.04);
  min-width: 0;
}
.{ns}-side-card__eyebrow {
  font-size: 0.7rem; letter-spacing: 0.22em; text-transform: uppercase;
  color: var(--{ns}-ink-muted); font-weight: 600;
}
.{ns}-side-card__title {
  font-size: 1rem; letter-spacing: -0.01em;
  font-weight: 600; color: var(--{ns}-ink);
}

// "Queue at a glance"
.{ns}-glance { display: grid; gap: 0.75rem; }
.{ns}-glance__row {
  display: flex; align-items: baseline; justify-content: space-between; gap: 0.6rem;
}
.{ns}-glance__row--total {
  padding-bottom: 0.65rem;
  border-bottom: 1px solid var(--{ns}-border-soft);
}
.{ns}-glance__label {
  font-size: 0.72rem; letter-spacing: 0.06em; text-transform: uppercase;
  color: var(--{ns}-ink-muted); font-weight: 600;
}
.{ns}-glance__value {
  font-size: 0.95rem; font-weight: 600; color: var(--{ns}-ink);
  font-variant-numeric: tabular-nums;
}
.{ns}-glance__value--lg       { font-size: 1.4rem; letter-spacing: -0.02em; line-height: 1.1; }
.{ns}-glance__value--awaiting  { color: var(--{ns}-awaiting); }
.{ns}-glance__value--drafts    { color: var(--{ns}-drafts); }
.{ns}-glance__value--preparing { color: var(--{ns}-preparing); }
.{ns}-glance__value--ready     { color: var(--{ns}-ready); }
.{ns}-glance__grid {
  display: grid; grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.65rem 1rem;
}

// "What to do next" — 4 tips, one per stage, dot color keyed to stage
.{ns}-tips       { list-style: none; display: grid; gap: 0.75rem; padding: 0; margin: 0; }
.{ns}-tips__item { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 0.5rem; }
.{ns}-tips__dot  { width: 7px; height: 7px; border-radius: 999px; margin-top: 0.45rem;
                   background: var(--{ns}-ink-muted); }
.{ns}-tips__item:nth-child(1) .{ns}-tips__dot { background: var(--{ns}-awaiting); }
.{ns}-tips__item:nth-child(2) .{ns}-tips__dot { background: var(--{ns}-drafts); }
.{ns}-tips__item:nth-child(3) .{ns}-tips__dot { background: var(--{ns}-preparing); }
.{ns}-tips__item:nth-child(4) .{ns}-tips__dot { background: var(--{ns}-ready); }
.{ns}-tips__title { font-size: 0.82rem; font-weight: 600; color: var(--{ns}-ink);
                    line-height: 1.35; }
.{ns}-tips__meta  { font-size: 0.76rem; color: var(--{ns}-ink-muted); line-height: 1.4; }
\`\`\`

The sidebar stays visible above 1180px; under 1180px it restacks below the panel.
Never drop it — it is the permanent orientation aid that lets new operators learn the
pipeline without clicking into a help doc.

### Responsive breakpoints (fixed contract)
\`\`\`scss
@media (max-width: 1180px) {
  .ops-grid--split.{ns}-split { grid-template-columns: 1fr; }
  .{ns}-sidebar               { gap: 0.85rem; }
  // Note: the KPI strip's responsive collapse is owned by <app-ops-metric-strip>;
  // callers do not override a .{ns}-metrics grid any more.
}
@media (max-width: 1100px) {
  .{ns}-row                   { grid-template-columns: 1fr; row-gap: 0.75rem; }
  .{ns}-row__next             { justify-items: stretch;
                                padding-top: 0.55rem;
                                border-top: 1px solid var(--{ns}-border-soft); }
  .{ns}-row__pills            { justify-content: flex-start; }
  .{ns}-action                { justify-self: start; }
}
@media (max-width: 900px) {
  .{ns}-hero                  { grid-template-columns: 1fr; }
  .{ns}-hero__actions         { justify-content: flex-start; }
  .{ns}-inbox                 { grid-template-columns: 1fr;
                                grid-template-areas: "eyebrow" "pills" "link";
                                row-gap: 0.55rem; }
  .{ns}-inbox__link           { justify-self: flex-start; }
  .{ns}-toolbar               { flex-direction: column; align-items: stretch; }
  .{ns}-selects               { justify-content: flex-start; }
}
@media (max-width: 640px) {
  .{ns}-inbox__pill           { flex: 1 1 100%; justify-content: flex-start; }
  .{ns}-pager                 { justify-content: center; text-align: center; }
  .{ns}-pager__range          { width: 100%; }
  .{ns}-glance__grid          { grid-template-columns: 1fr; }
  // KPI tiles stack via the shared <app-ops-metric-strip>; no .{ns}-metrics override.
}
\`\`\`

These breakpoints are **fixed across every queue**. Do not invent new breakpoints;
extend the existing ones if a queue has unique content.

### Loading / error / empty states (fixed contract)
- **Loading**: \`<dmis-skeleton-loader variant="table-row" [count]="5" />\`
  inside \`.{ns}-panel__body\`, replacing the row list only (toolbar stays visible).
- **Error**: \`<dmis-empty-state icon="error_outline" title="..." [message] actionLabel="Retry" (action)="refreshQueue()" />\`.
  The \`icon="error_outline"\` attribute is a **test selector contract** — several specs
  query it directly. Do not change the icon.
- **Empty (post-load, not errored)**: \`<div class="{ns}-empty"><dmis-empty-state icon="inbox" title="..." message="..." /></div>\`.
  Do NOT duplicate the 4-stage guidance inside the empty state — guidance lives in the
  sidebar, one source of truth per page.

### Stage model (four stages, ordered)

Every queue page ships with **exactly four stages**, rendered left-to-right through the
pipeline. Rename the stage tokens per queue if needed, but keep the token positions
(amber → indigo → purple → green) and the "two filled / two soft" action-button
emphasis pattern — this preserves a shared mental model across Package Fulfillment,
Dispatch, Receipt, Eligibility, and Consolidation.

| Stage | Palette token (PFQ) | Action button emphasis | Typical next-action label |
|-------|----------------------|------------------------|---------------------------|
| Awaiting | \`--{ns}-awaiting #b7833f\` (amber) | Filled (ink on white) — high emphasis, creates a reservation | "Allocate stock" |
| Drafts | \`--{ns}-drafts #3d4b99\` (indigo) | Soft tint — medium emphasis, resume personal work | "Resume draft" |
| Preparing | \`--{ns}-preparing #7a4fd1\` (purple) | Soft tint — medium emphasis, continue in-progress work | "Continue packing" |
| Ready | \`--{ns}-ready #2e8a48\` (green) | Filled (green on white) — high emphasis, external hand-off | "Hand off to dispatch" |

Stages are derived by a component-local helper (\`getFulfillmentStage(row)\` /
\`getDispatchStage(row)\` / \`getReceiptStage(row)\` / ...) that maps backend status codes
to one of the four stage strings. **Never branch on the raw status_code in the
template** — the stage helper is the single source of truth for colour, label, dot,
next-action, and aria-label.

Sister queues translate 1:1 — e.g. Dispatch: staged → in-transit → delivered → complete;
Receipt: en-route → offloading → inspecting → confirmed. The palette positions stay
fixed (amber first, green last); only the labels change.

### Time-in-stage SLA thresholds

Every row carries a \`.{ns}-time-pill--{tone}\` (see Row anatomy SCSS above). Tone is
computed by \`timeInStageTone(row)\` from \`timeInStageHours(row)\`. The raw age is
rendered via \`formatAge(row.create_dtime ?? row.request_date)\` appended with "in stage".

| Tone | Hours in stage | Visual | Intent |
|------|----------------|--------|--------|
| \`fresh\` | < 4h | green | Just arrived — no pressure |
| \`normal\` | 4–24h | warm neutral | Within normal handling window |
| \`stale\` | 24–48h | amber | Starting to age — expedite |
| \`breach\` | > 48h | red | SLA breach — escalate |

Keep the thresholds in a single \`TIME_IN_STAGE_THRESHOLDS\` constant on the component,
not scattered as magic numbers in templates or helpers. Tune the hour values per queue
(Receipt might breach at 24h, not 48h), but never inline them.

### Test-contract guardrails

When rewriting a queue's layout — or standing up a new queue — preserve these contracts
so the shared operations test harness keeps working:

- Preserve \`filterOptions\` values **and order** (tests rely on indexed positions).
  \`All\` always first, then stages in pipeline order.
- Keep the error branch selector \`dmis-empty-state[icon="error_outline"]\` — several
  specs query it directly. Do not change the icon name.
- Keep \`onMetricClick(token)\` routing from metric-card tokens to \`setFilter()\` so KPI
  clicks still navigate to the corresponding stage.
- Keep \`queueMetrics().active\` synced with \`activeFilter()\` so tests asserting "the
  clicked metric is active" continue to pass.
- Out-of-contract row exclusion (\`isOutOfContractRow\`, \`warnOutOfContractRows\`), urgency
  + authority tone mappings, and stage-mapping helpers (\`getFulfillmentStage\`,
  \`isReady\`, \`isDraft\`, \`isLocked\`, \`isOverridePending\`) must remain intact. Rename
  the helpers per queue, but keep the contract surface (same input shape, same output
  stage strings).
- \`page\`, \`PAGE_SIZE\`, \`currentPage\`, \`totalPages\`, \`pagedItems\`, \`pageRange\`,
  \`visiblePages\` are required signals/computeds on every queue component — pagination
  tests call them by name.
- \`onSearch\`, \`setFilter\`, and a successful \`loadQueue\` **must** reset \`page\` to 1.

### Do NOT

- Do NOT drop the sidebar (\`ops-grid--split\` + \`.{ns}-sidebar\`) to reclaim horizontal
  space — "Queue at a glance" and "What to do next" are the permanent orientation aids
  that let new operators learn the pipeline without clicking into a help doc.
- Do NOT duplicate "What to do next" guidance inline in the empty state when the
  sidebar already shows it — one source of truth per page.
- Do NOT apply a monospace \`font-family\` to \`.{ns}-row__id\`, \`.{ns}-row__pkg\`, counts,
  or any numeric pill. Stay on the inherited system sans stack and use
  \`font-variant-numeric: tabular-nums\` for alignment. Monospace drifts from
  \`ops-row__title\` on sister queues and from the SRD.
- Do NOT include an "All Requests" KPI card — the "all" filter is a chip, not a KPI.
- Do NOT render a bare chevron as the row's next-action affordance — always pair with
  a named button whose label matches the stage.
- Do NOT hard-code time-in-stage thresholds inside templates or helpers — centralize
  in \`TIME_IN_STAGE_THRESHOLDS\`.
- Do NOT use Material \`color="primary"\` / \`color="warn"\` for stage action buttons —
  use stage-specific \`.{ns}-action--{stage}\` so every stage reads as its own palette,
  not a generic primary/warn tier.
- Do NOT paginate server-side for queues small enough to fit in a single signal; local
  \`.{ns}-pager\` over \`filteredItems()\` is simpler, cache-friendly, and consistent with
  EP-02's \`srd-pager\`.
- Do NOT reintroduce a "Show Drafts" hero-level toggle — drafts are a filter chip,
  period. The hero button slot is for Refresh + "Show my drafts · N" (only when N > 0).
- Do NOT reintroduce raw \`border-left-color\` modifiers on queue metric tiles or rows —
  the bar curves with the card radius and drifts from the SRD warehouse-card look.
  Metric tiles get their accent bar from \`<app-ops-metric-strip>\` via the \`token\`
  field; row stage colour is driven through \`--ops-queue-accent\` on the shared
  \`.ops-queue-row\` primitive (Section 4g).
- Do NOT leave queue request rows pure white — let \`.ops-queue-row\` apply its subtle
  \`--ops-queue-surface: #f6f5f1\` fill so rows read as distinct cards against the white
  panel. Override the token only when the queue needs its own tone.
- Do NOT render the action inbox strip, the pager, or the sidebar "Queue at a glance"
  numbers while the queue is loading or errored — those are signals that need a known
  queue shape to be truthful.
- Do NOT use \`mat-select\` for Priority / Warehouse / Sort — native \`<select>\` inside
  \`.{ns}-select\` is the contract (mobile, accessibility, keyboard).
- Do NOT use \`grid\` for the toolbar — \`flex\` + \`flex-wrap\` + \`justify-content:
  space-between\` is the contract. Grids overlap at 100% zoom on narrow laptops.
- Do NOT invent new breakpoints. Extend 1180 / 1100 / 900 / 640 with additional
  overrides if a queue has unique content, but keep those four anchor widths.

---

## 4g. Shared queue-card primitives (\`.ops-queue-tile\` / \`.ops-queue-row\`)

Every work-pipeline queue (Package Fulfillment, Dispatch, Receipt, Eligibility Review,
Consolidation, ...) shares the same card chrome: a flat rectangular left-edge accent
bar telegraphing stage/severity, and a subtle neutral fill so rows read as distinct
cards against the white queue panel. Those chrome rules are factored out of the
queue-specific classes (\`pfq-*\`, \`dqu-*\`, \`rcv-*\`) into two shared primitives that live
in \`frontend/src/app/operations/operations-shell.scss\`.

### Class contract
\`\`\`scss
.ops-queue-tile,
.ops-queue-row {
  --ops-queue-accent: rgba(55, 53, 47, 0.18);        // caller overrides per stage
  --ops-queue-accent-width: 6px;                     // tile default; row narrows to 5px
  --ops-queue-surface: var(--color-surface-container-lowest);
  --ops-queue-border: rgba(55, 53, 47, 0.08);

  position: relative;
  overflow: hidden;                                  // clips the ::before at card radius
  background: var(--ops-queue-surface);
  border: 1px solid var(--ops-queue-border);
  border-radius: 0.75rem;

  &::before {
    content: '';
    position: absolute;
    left: 0; top: 0; bottom: 0;
    width: var(--ops-queue-accent-width);
    background: var(--ops-queue-accent);
    border-top-left-radius: inherit;
    border-bottom-left-radius: inherit;
  }
}

.ops-queue-tile {
  --ops-queue-accent-width: 6px;
  padding: 0.95rem 1rem 0.95rem 1.25rem;
  box-shadow: 0 6px 14px rgba(26, 28, 28, 0.03);
}

.ops-queue-row {
  --ops-queue-accent-width: 5px;
  --ops-queue-surface: #f6f5f1;                      // subtle grey distinct from panel
  padding: 0.85rem 1rem 0.85rem 1.15rem;
}
\`\`\`

### Why \`::before\` + \`overflow: hidden\` (not \`border-left\`)
A 4-6px \`border-left\` on a rounded card curves at the top-left and bottom-left corners,
producing a soft "highlighted tab" look. Design review flagged that as visually noisy
against the Supply Replenishment Dashboard warehouse cards (\`.srd-wh-card\`), which use
a flat rectangular bar clipped by the card's rounded corners. \`::before\` renders a true
rectangle; \`overflow: hidden\` on the parent clips it flush with the card's radius,
giving the same clean, flat bar seen on \`.srd-wh-card\`. \`border-radius: inherit\` on the
bar is defensive — if a parent overrides \`overflow\`, the bar still shape-matches the
card.

### How callers compose
\`\`\`html
<!-- Queue metric tiles (KPI cards) — use the shared component, never hand-roll .ops-queue-tile -->
<app-ops-metric-strip
  [items]="queueMetrics()"
  (itemClick)="openMetric($event)"
  aria-label="Queue summary" />

<!-- Queue list row — still composes the shared .ops-queue-row primitive -->
<article class="ops-queue-row pfq-row ops-row--drafts" tabindex="0" role="listitem"> ... </article>
\`\`\`

\`\`\`scss
// Row feature SCSS carries only display / layout / interactions. It sets
// --ops-queue-accent per stage; the primitive supplies the bar + surface.
.pfq-row {
  display: grid; /* layout only */
  &:hover { --ops-queue-surface: #fbfaf6; }          // warm one step without flipping white
}
.ops-row--awaiting  { --ops-queue-accent: var(--pfq-awaiting); }
.ops-row--drafts    { --ops-queue-accent: var(--pfq-drafts); }
.ops-row--preparing { --ops-queue-accent: var(--pfq-preparing); }
.ops-row--ready     { --ops-queue-accent: var(--pfq-ready); }
\`\`\`

Note: the older hand-rolled \`.pfq-metric\` / \`.{ns}-metric\` composition on top of
\`.ops-queue-tile\` is superseded by \`<app-ops-metric-strip>\` (see Section 4f —
"KPI metric strip — use \`<app-ops-metric-strip>\`"). Do not reintroduce it for new
queue pages.

### When to use which
- \`<app-ops-metric-strip>\` — KPI metric cards on every operations queue page
  (awaiting / drafts / preparing / ready counters, etc.). The component encapsulates
  the tile chrome, accent bar, value typography, and optional badge pill. Pass
  \`OpsMetricStripItem[]\` with a \`token\` per stage; do not compose
  \`.ops-queue-tile\` directly any more.
- \`.ops-queue-row\` — list rows representing one work item in the queue. Row-density
  padding, narrower accent bar (\`5px\`), and a subtle \`#f6f5f1\` grey fill so rows read
  as separate cards against the white queue panel.
- \`.ops-queue-tile\` still exists as an internal primitive for non-KPI tile chrome
  (rare — most queues only need the strip component). Prefer the shared component
  unless you need a one-off card that can't be expressed as \`OpsMetricStripItem\`.

### Tokens callers may override
| Custom property | Default | Override when |
|-----------------|---------|---------------|
| \`--ops-queue-accent\` | \`rgba(55, 53, 47, 0.18)\` | Always — per stage / severity |
| \`--ops-queue-accent-width\` | tile 6px / row 5px | Queue uses a denser or bolder bar |
| \`--ops-queue-surface\` | tile white / row \`#f6f5f1\` | Queue needs a warmer or cooler row tone, or \`:hover\` / \`:focus-within\` needs a tint (PFQ uses \`#fbfaf6\` on hover) |
| \`--ops-queue-border\` | \`rgba(55, 53, 47, 0.08)\` | Active / selected state needs a stronger outline |

### Do and do NOT
- DO use \`<app-ops-metric-strip>\` for every KPI tile strip on operations queue pages.
  Pass an \`OpsMetricStripItem[]\` with a \`token\` per stage and let the component own
  the chrome, accent bar, value typography, and badge pill.
- DO compose the row primitive on the queue-specific class (\`ops-queue-row pfq-row\`,
  \`ops-queue-row dqu-row\`) so feature SCSS keeps layout + interactions and the
  primitive owns chrome.
- DO drive row stage colour by setting \`--ops-queue-accent\` on the stage modifier
  (\`.ops-row--drafts\`, \`.rcv-row--intransit\`, etc.), not by re-declaring backgrounds
  or borders on the feature class.
- DO NOT hand-roll \`.pfq-metric\` / \`.{ns}-metric\` / \`.ops-queue-tile\` compositions
  for KPI tiles — that pattern is superseded by \`<app-ops-metric-strip>\`.
- DO NOT re-add \`background\`, \`border\`, \`border-left\`, \`border-radius\`, or
  \`box-shadow\` to the feature-local row class when composing the primitive — you will
  fight the primitive's \`::before\` or re-introduce the curvy \`border-left\` look.
- DO NOT fork a parallel \`.xxx-queue-row\` per queue. Add a namespaced modifier
  (\`.rcv-row--intransit\`) that *sets a token* and compose the shared primitive.
- DO NOT put card chrome (radius, shadow, surface) on the \`<ops-panel>\` wrapper around
  the queue — the panel is the outer frame; each row's chrome comes from
  \`.ops-queue-row\`.

---

## 4b. Form Field UX Rules

### Reference data fields — always use lookup dropdowns
- **Warehouse selection**: Never expose raw numeric IDs to users. Use \`MasterDataService.lookup('warehouses')\` with \`toSignal()\` and render a \`<mat-select>\` showing warehouse names. The stored value is the ID string.
- **Enumerated fields** (transport mode, status, urgency): Use \`<mat-select>\` with a predefined constant array, not freetext \`<input>\`. Freetext leads to inconsistent data.
- **Pattern**: \`toSignal(masterData.lookup('tableKey'), { initialValue: [] })\` in the component class, \`@for (item of options(); track item.value)\` in the template.

### Label from the next person's perspective
- Form labels should communicate what the *next workflow actor* needs to know, not internal field names.
- Example: "Further Instructions" (what the inventory clerk will see) instead of "Package Comments" (a database column name).
- Hint text should explain the field's purpose in the workflow, e.g., "Where this package will be received" not "Numeric warehouse / inventory identifier."

### Form ownership in stepper flows
- The parent workspace component owns the \`FormGroup\` and passes it to step sub-components via \`input()\`.
- Step components are presentational: they render form controls via \`formControlName\` but do not create the form.
- Cross-step validation (e.g., departure < arrival) uses group-level validators on the parent form.
- The parent reads form values for API submission; steps never emit individual field changes.
- When a record is already finalized (e.g., dispatched), the parent calls \`form.disable()\` once — sub-components do not need per-field \`[disabled]\` bindings.

### Transport mode constant pattern
- Use \`TRANSPORT_MODE_OPTIONS\` (ROAD, AIR, SEA) with \`<mat-select>\` for transport mode, not freetext input.
- In the review step, resolve the stored value to its label using a \`Map\` built from the options constant.

### No metric duplication in stepper steps
- If the parent workspace displays a metric strip (tracking numbers, lifecycle status), step sub-components must NOT repeat the same data in their own card grids.
- Steps should only add information that is new or specific to that step's context.

---

## 5. Data & Service Patterns

### API calls
- Services use \`inject(HttpClient)\` and return \`Observable<T>\`
- Components subscribe in \`ngOnInit\` and push results into signals
- Use \`forkJoin\` for parallel API calls, \`catchError(() => of(fallback))\` for resilience
- Show loading skeleton during fetch, error callout on failure

### Filtering pattern
\`\`\`typescript
readonly activeFilter = signal<FilterType>('all');
readonly searchTerm = signal('');
readonly filteredItems = computed(() => {
  const filter = this.activeFilter();
  const term = this.searchTerm().trim().toLowerCase();
  return this.items().filter(item => {
    if (filter !== 'all' && item.status !== filter) return false;
    if (!term) return true;
    return item.searchableText.toLowerCase().includes(term);
  });
});
\`\`\`

---

## 6. Accessibility (Non-negotiable)

- Status colors MUST have text/icon backup — never color-only indicators
- \`role="list"\` / \`role="listitem"\` on custom list markup
- \`aria-label\` on sections, toolbars, navigation regions
- Radio groups for filters: \`role="radiogroup"\` with \`aria-label\`
- Interactive cards: \`tabindex="0"\` + keyboard event handling
- Reduced motion: \`@media (prefers-reduced-motion: reduce) { transition: none; }\`

---

## 7. Quality Checklist

Before considering a component complete, verify:

- [ ] OnPush change detection
- [ ] Standalone with explicit imports
- [ ] Signals for all reactive state (no BehaviorSubject for component state)
- [ ] New control flow syntax (@for, @if, @switch — NOT *ngFor, *ngIf)
- [ ] \`track\` expression on every \`@for\`
- [ ] Warm Notion palette — no cold grays (#f5f5f5, #e0e0e0, etc.)
- [ ] CSS custom properties used, not hardcoded colors
- [ ] Responsive at all 4 breakpoints
- [ ] Empty state provided
- [ ] Workflow blocker states translate backend failures into user-facing recovery copy
- [ ] Shared empty or blocker patterns are extracted into reusable presentational components
- [ ] Accessible (landmarks, labels, keyboard, color-not-alone)
- [ ] No \`!important\` in styles
- [ ] No \`[innerHTML]\` bindings
- [ ] Loading state handles network delay gracefully
- [ ] Wizard action strips include Cancel + Save Draft + Primary (Section 4d)
- [ ] Multi-warehouse item panels use stacked warehouse cards, not a default-warehouse picker (Section 4c)
- [ ] Stock-status / multi-warehouse surveillance screens follow the SRD pattern: white hero, flex-wrap toolbar, native scope \`<select>\`, independent warehouse cards with parish, filter-aware empty state (Section 4e)
- [ ] Work-pipeline queues follow the PFQ pattern: split layout (work panel + "Queue at a glance" / "What to do next" sidebar), action inbox strip, 3–4-tile KPI strip rendered via \`<app-ops-metric-strip>\` (no "All" card), one-sentence \`ops-section__copy\` description under the panel title, stage-tiered rows with time-in-stage SLA pill (system sans + tabular-nums — no monospace), named next-action button, local \`pfq-pager\` pagination (Section 4f)
- [ ] KPI tiles are rendered via \`<app-ops-metric-strip [items]="..." (itemClick)="...">\` with an \`OpsMetricStripItem[]\` carrying \`token\` + \`badge: { label, tone }\`; no hand-rolled \`.pfq-metric\` / \`.{ns}-metric\` / \`.ops-queue-tile\` SCSS for KPIs (Section 4f)
- [ ] Queue list rows compose \`.ops-queue-row\`; stage colour is driven via \`--ops-queue-accent\` on the stage modifier and no feature class re-declares \`background\` / \`border\` / \`border-left\` / \`border-radius\` / \`box-shadow\` (Section 4g)
- [ ] Cancel button opens a confirm dialog and calls a dedicated abandon-draft endpoint with Idempotency-Key
- [ ] Signal inputs are read as functions in templates (\`warehouse()\`, not \`warehouse\`)

---

## 8. Anti-patterns to Avoid

- Cold Material gray palette — DMIS uses Notion's warm beige/cream
- Constructor injection — use \`inject()\`
- \`*ngFor\` / \`*ngIf\` — use \`@for\` / \`@if\`
- BehaviorSubject for local component state — use signals
- Spinners — use skeleton loaders
- Color-only status indicators — always pair with text or icon
- Generic empty states ("No data") — always explain what would appear and what action to take
- Barrel imports from Angular Material
- \`ViewChild\` for DOM queries — prefer template variables and signals
- Overly nested component trees — keep components flat and composable
- Creating per-feature shell/row/chip classes (e.g. \`pfq-page-shell\`, \`dqu-row-base\`, \`rcv-chip\`) when \`ops-page-shell\`, \`ops-row\`, \`ops-chip\`, and the shared queue primitives (\`ops-queue-row\` in Section 4g, \`<app-ops-metric-strip>\` in Section 4f) from \`operations-shell.scss\` and \`operations/shared/\` already cover the need — compose and layer a namespaced modifier on top of the shared class instead of forking it
- Hand-rolling \`.pfq-metric\` / \`.{ns}-metric\` / \`.ops-queue-tile\` compositions for KPI tiles on a new queue page when \`<app-ops-metric-strip>\` already encodes the PFQ-aligned tile chrome (accent bar, label, value, hint, badge pill). Use the shared component; extend \`OpsMetricTileTone\` before adding a new bespoke SCSS file
- Raw backend validation strings shown directly to operators without a translated recovery message
- Adding more inline empty/error markup to already-large workflow components when a shared component fits
- Raw numeric ID inputs for reference data (warehouses, agencies, items) — always use lookup dropdowns
- Freetext inputs for enumerated values (transport mode, status codes) — use \`<mat-select>\` with constants
- Labeling fields with database column names instead of user-facing workflow language
- Grid-based toolbars on dashboards — they overlap at 100% zoom; use flex-wrap instead
- \`mat-menu\` or custom dropdowns for warehouse scope selection — use a native \`<select>\` wrapped with icon styling
- Wrapping warehouse cards in a single outer panel frame — each warehouse is its own bordered card
- Tinted (beige/warm) backgrounds on expanded warehouse cards — expanded state is white
- Progress bars or background fills for time-to-stockout cells — plain colored text only
- Rendering a "STALE DATA" banner inside a warehouse card body — rely on hero last-refreshed meta
- Hiding the filter toolbar when the current filter yields zero results — always keep it visible and show a filter-aware empty state
- Dropping the "Queue at a glance" / "What to do next" sidebar from a work-pipeline queue — the split layout and its two sidebar cards are the permanent orientation aid; removing them leaves operators hunting for the pipeline shape when they're interrupted mid-shift
- Duplicating the four-stage guidance inline inside the empty state when the sidebar already carries it — one source of truth per page
- Applying a monospace font-family (\`JetBrains Mono\`, \`IBM Plex Mono\`, etc.) to \`pfq-row__id\` or \`pfq-row__pkg\` — stay on the inherited system sans stack and use \`font-variant-numeric: tabular-nums\` for alignment
- Exposing an "All Requests" or "Total" KPI card on a work-pipeline queue — the "all" pivot belongs on the filter chips, not the metric strip (and \`<app-ops-metric-strip>\` caps at 3–4 tiles precisely for that reason)
- Rendering a bare chevron (\`"↳"\`, \`"→"\`, \`chevron_right\` alone) as the row's next-action affordance — pair the chevron with a named, stage-specific action button ("Allocate stock", "Resume draft", "Continue packing", "Hand off to dispatch")
- Using Material \`color="primary" / "warn"\` for stage action buttons — use stage-specific tokens (\`pfq-action--awaiting\`, \`--drafts\`, \`--preparing\`, \`--ready\`) so every stage reads as its own palette
- Omitting the one-sentence \`ops-section__copy\` description under the panel title ("Search and filter requests awaiting fulfillment…") — new operators need it to orient
- Reintroducing hero-level stage toggles (e.g. "Show Drafts") on work-pipeline queues — drafts are a filter chip, period
- Scattering time-in-stage SLA thresholds (4h/24h/48h) as magic numbers in templates or helpers — centralize in a single \`TIME_IN_STAGE_THRESHOLDS\` constant on the component
`;
