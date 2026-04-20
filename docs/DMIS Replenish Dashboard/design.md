# FR05.06 — Package Fulfillment Item Allocation Redesign

**Status:** Design-ready spec for frontend implementation
**Scope:** FR05.06, FR05.06a, FR05.06b, FR05.06c, FR05.06d
**Owner surface:** `package-fulfillment-workspace` → item allocation step
**Target user:** Kemar — Logistics Manager, hurricane-response field operator
**Visual system:** `src/lib/prompts/generation.tsx` (DMIS "Notion for ops", warm neutrals, Sections 4, 4c, 4d)

---

## 0. Design summary

The current allocation screen is a legacy batch table with a "continuation" hack welded to the side. It forces Kemar to reason about default sources and manual overrides, and it conflates **partial fulfillment** (a normal compliant outcome) with **override** (an exception that must be reviewed). It also hides *why* the system is recommending a warehouse — operators can't explain the choice without leaving the screen.

The redesign lifts the generation.tsx **Multi-Warehouse Allocation Pattern (§4c)** as the organizing principle: each item renders a **vertical stack of warehouse cards** in FEFO/FIFO rank order, the top card is explicitly the recommendation with its reason inline, shortfall is always visible in one aggregate bar, and adding the next-ranked warehouse is a primary affordance — not a recovery path. Partial fulfillment gets its own **compliant-partial** state that reads as OK, distinct from override.

Two state shapes drive the screen:
- **Stocked path** — one or more ranked warehouse cards with quantity inputs, batch detail on demand, aggregate shortfall bar.
- **Unstocked path** — the existing `ops-stock-availability-state` blocker (unchanged visual, tightened copy).

No new components need to be invented. The pattern reuses `ops-allocation-card`, `ops-allocation-summary`, `ops-chip`, `ops-metric-strip`, `ops-context-strip`, `dmis-empty-state`, and the shell button tiers already defined in `operations-shell.scss`.

---

## 1. User flow — item allocation

```
Enter step → items panel (left) selects first unfulfilled item
  │
  ├─► item has stock in ≥1 warehouse  ──► STOCKED PATH
  │     ▸ primary card pre-filled with min(available, requested)
  │     ▸ user confirms OR edits qty
  │     ▸ if shortfall > 0: "Add next warehouse" → menu of remaining ranked whs
  │     ▸ aggregate bar updates live: Reserving X of Y  |  Shortfall Z
  │     ▸ status: Filled (Reserving = Requested) | Compliant partial (Reserving < Requested, user accepts) | Draft
  │     └─► next item (auto-advance) OR Continue
  │
  └─► item has zero available stock anywhere  ──► BLOCKER PATH
        ▸ ops-stock-availability-state blocker (existing)
        ▸ operator has 3 recovery options:
            · Skip item (mark intentional partial at package level)
            · Jump to another item
            · Back to request
```

**Auto-advance rule:** when a card moves to Filled status and shortfall = 0, focus shifts to the next unfulfilled item after a 300 ms pause (respects `prefers-reduced-motion` — instant). The left-rail checkmark animates in.

**Successive warehouse rule (FR05.06b):** adding warehouse N+1 pre-fills its qty input with `min(available_here, remaining_shortfall)`. Users can override the suggestion freely; validation only fires if qty exceeds `available_here`.

---

## 2. Information hierarchy

Top → bottom priority for the item allocation pane:

1. **Item identity line** — name, code, requested qty, rank rule badge (`FEFO` / `FIFO`).
2. **Aggregate state strip** — 5 KPIs: Requested · Reserving · Shortfall · Warehouses used · Status. (Replaces the current "Available here / Reserving / Shortfall / Status" strip; adds Warehouses used and promotes Reserving.)
3. **Ranked warehouse card stack** — primary card first, secondary cards below. Each card is self-describing (rank, reason, qty).
4. **Shortfall footer / aggregate bar** — `ops-allocation-summary`, always visible, becomes CTA when shortfall > 0.
5. **Step actions** — Back · Cancel · Save Draft · Continue (generation.tsx §4d).

Things that are **demoted** from the current screen:
- Raw batch table → collapsed inside each card, opens on demand.
- "Clear selection" / "Manual override" link cluster → relocated into the primary card's overflow menu (rare action, not a top-right link).
- Per-card "Status" cell → rolled into the aggregate strip + a quiet inline pill on the card header.

---

## 3. Layout structure

**Desktop (≥ 1100 px)** — two-column shell consistent with existing workspace:

```
ops-shell
  ops-shell__back + ops-shell__title        ← "Package PK-2026-0418-014 · Allocate items"
  ops-context-strip                          ← Request, authority, FEFO/FIFO policy, deadline
  ops-shell__stepper (dmis-step-tracker)     ← "3 of 4 · Allocate"
  ops-layout--wide-right
    LEFT  (280 px fixed)                     ← items-to-fulfil list, checkmarks, progress
      ops-items-rail
        ops-item-chip (selected / done / pending / blocked)
    RIGHT (flex)                             ← active item allocation
      ops-item-header                        ← name · code · rule badge · overflow menu
      ops-metric-strip                       ← 5 KPIs (see §2.2)
      ops-allocation-stack                   ← ranked warehouse cards
        ops-allocation-card (rank 1, primary)
        ops-allocation-card (rank 2)
        ops-allocation-card (rank n)
        ops-allocation-stack__add            ← "Add next warehouse" (shows remaining whs in rank order)
      ops-allocation-summary                 ← aggregate reservation + shortfall + CTA
  ops-form-actions                           ← Back · Cancel · Save Draft · Continue
```

**Breakpoints** (generation.tsx §3):
- `> 1100 px` — two-col as above.
- `760–1100 px` — items rail collapses to a horizontal scrollable chip row pinned under the stepper. Right column becomes full-width.
- `520–760 px` — item chips become a `<mat-select>` "Showing: FACE MASK… (2 of 7)". Metric strip drops to 2×2 (Requested, Reserving, Shortfall, Status). Cards stack full-width.
- `< 520 px` — mobile spec in §8.

---

## 4. Warehouse card / stack pattern

Each card is an `article.ops-allocation-card` with `role="group"` and `aria-label="Warehouse allocation: {name}, rank {n}"`.

### 4.1 Card anatomy

```
┌─ ops-allocation-card --primary ──────────────────────────────────────────┐
│ ┌─ header ─────────────────────────────────────────────────────────────┐ │
│ │ [📦] PORT ANTONIO CENTRAL WAREHOUSE                                  │ │
│ │       Primary · FEFO   ·   145 available   ·   Expires 12 May 2026   │ │
│ │                                               [⋮ overflow]           │ │
│ └─────────────────────────────────────────────────────────────────────┘ │
│                                                                          │
│ ┌─ reason ──────────────────────────────────────────────────────────── ┐ │
│ │ ⓘ Ranked first — earliest expiring batch (12 May), covers full need. │ │
│ └─────────────────────────────────────────────────────────────────────┘ │
│                                                                          │
│ ┌─ qty row ───────────────────────────────────────────────────────────┐ │
│ │ Allocating from this warehouse                                       │ │
│ │ ┌──────────────┐                                                     │ │
│ │ │      20      │   of 145 available    [ Use max ]  [ Clear ]        │ │
│ │ └──────────────┘                                                     │ │
│ │ Validates: 0 ≤ qty ≤ 145                                             │ │
│ └─────────────────────────────────────────────────────────────────────┘ │
│                                                                          │
│ ┌─ batch detail (collapsed) ──────────────────────────────────────────┐ │
│ │ ▸ 2 batches reserved · show batch detail                             │ │
│ └─────────────────────────────────────────────────────────────────────┘ │
│                                                                          │
│ status pill (quiet): ● Filled from this warehouse                        │
└──────────────────────────────────────────────────────────────────────────┘
```

### 4.2 Rank badges

| Rank | Label | Pill tone | Rule |
|------|-------|-----------|------|
| 1 | `Primary · FEFO` or `Primary · FIFO` | `ops-chip--info` filled | Always the backend-ranked top warehouse. `canRemove = false` when it is the only card. |
| 2 | `+1 · FEFO` | `ops-chip--info` outline | Second rank. |
| n | `+{n-1} · FEFO` | `ops-chip--neutral` outline | 3rd and beyond — visually quieter. |

Rank rule is pulled from the item's `ranking_policy` field — FEFO when expiry present, FIFO otherwise.

### 4.3 "Why this rank" reason line

Below the header, every card gets a single sentence that explains the ranking decision in operator language. Backend returns `warehouse_cards[].rank_reason` as a typed enum; the UI maps it to copy:

| `rank_reason` enum | Display copy |
|---|---|
| `EARLIEST_EXPIRY` | "Ranked first — earliest expiring batch ({date}), covers {pct}% of need." |
| `EARLIEST_RECEIPT` | "Ranked first — oldest receipt date ({date}), FIFO priority." |
| `COVERS_REMAINDER` | "Ranks next — holds {avail} which covers the remaining shortfall." |
| `PROXIMITY` | "Ranked {n} — nearest warehouse with matching stock." |
| `LAST_RESORT` | "Remaining available stock for this item." |

Reason line is `ops-chip--info` background (`#eef4ff`), a `info` icon, and 0.9 rem body text. If `rank_reason` is null, the line is omitted rather than faked.

### 4.4 Quantity input

- `<mat-form-field>` compact density, `type="number"`, `min="0"`, `max="{available_here}"`, step 1.
- Pre-filled from `warehouse_cards[].suggested_qty` (backend-computed greedy FEFO/FIFO fill).
- Two helpers beside the field:
  - **Use max** — sets qty to `min(available_here, remaining_shortfall + current_qty)` so the user doesn't have to do mental arithmetic.
  - **Clear** — sets qty to 0. Card stays, so user can revisit.
- On blur: recompute aggregate + shortfall. No modal confirmations on qty edits.
- Inline validation tone: warning (`#fde8b1 / #6e4200`) when qty > available_here, with message "Cannot exceed 145 available at Port Antonio."
- Keyboard: ↑/↓ increments 1, Shift+↑/↓ increments 10. Announced via `aria-describedby` pointing at the validation hint.

### 4.5 Batch detail (collapsed)

Disclosure row shows "`▸ 2 batches reserved · show batch detail`" (or "`▸ no batches reserved yet`" when qty = 0).

Expanded table columns: **Lot no.** · **Receipt date** · **Expiry** · **Available** · **Reserved** · **Qty to reserve**. FEFO or FIFO-ordered per the item policy. Editing a row's qty-to-reserve instantly recomputes the card's total. If the user prefers a single qty input, the card's top-level qty distributes greedily across batches in rule order — this is the default and most flows never open the table.

### 4.6 Overflow menu per card

`mat-icon-button` with `more_vert`, menu items:
- **Use max available here**
- **Clear allocation from this warehouse**
- **Remove warehouse** — disabled when it is the only card (tooltip: "At least one warehouse must remain")
- **Open in Inventory** — opens the warehouse detail in a new tab (operator can verify stock)

### 4.7 Card status pill (quiet, bottom of card)

Only the card-scope status. The big-picture status lives in the aggregate strip.

| Card state | Pill | Tone | When |
|---|---|---|---|
| Draft | `◌ Not yet allocated` | neutral | qty = 0 |
| Partial from here | `◐ Partial from this warehouse` | info | 0 < qty < available_here AND qty < requested - sum(other cards) |
| Filled from here | `● Filled from this warehouse` | success | qty = available_here OR qty contributes to sum = requested |
| Over | `▲ Exceeds available` | warning | qty > available_here (also blocks Continue) |

---

## 5. Continuation / add-next-warehouse

`ops-allocation-stack__add` is a full-width stroked button (not a link) directly below the last card. It is the affordance that makes multi-warehouse feel native.

### 5.1 States of the Add button

| Condition | Button state | Copy | Tone |
|---|---|---|---|
| Shortfall > 0 AND `alternate_warehouses` non-empty | Emphasised (outlined primary, pulsing focus ring) | `+ Add next warehouse (2 available)` | primary |
| Shortfall = 0 AND `alternate_warehouses` non-empty | Default stroked | `+ Add another warehouse` | neutral |
| `alternate_warehouses` empty AND shortfall > 0 | Disabled | `No further warehouses hold this item` | neutral, `aria-disabled="true"` |
| `alternate_warehouses` empty AND shortfall = 0 | Hidden | — | — |

### 5.2 Menu

Click opens a `<mat-menu>` showing **only** warehouses that: (a) have `available > 0` for this item, (b) are not already rendered as a card. Items in the menu are sorted by `issuance_order` from the backend.

Each row in the menu shows:
```
+1 · FEFO    SAVANNA-LA-MAR DEPOT
              85 available · next-earliest expiry 03 Jun 2026
```

Selecting a row:
1. Optimistically inserts a new card at the bottom of the stack with `suggested_qty = min(available, remaining_shortfall)`.
2. Scrolls the new card into view (without using `scrollIntoView` — uses `window.scrollTo({top, behavior})` on the parent panel).
3. Focus lands on the new qty input.
4. Card enters with an `opacity` + `translateY(4px → 0)` transition (180 ms, reduced-motion → instant).

### 5.3 Aggregate summary as secondary affordance

The `ops-allocation-summary` bar at the bottom doubles as a CTA when shortfall > 0:

```
┌──────────────────────────────────────────────────────────────────────────┐
│ ⓘ Reserving 85 of 120 · Shortfall 35                                     │
│ [ + Add next warehouse ]  or  [ Accept partial (35 short) ]              │
└──────────────────────────────────────────────────────────────────────────┘
```

"Accept partial" is how the operator **intentionally** commits to partial fulfillment — see §7.

---

## 6. Validation, warnings, overrides

Three distinct severity tones, per generation.tsx §1.

| Signal | Tone | When | Blocks Continue? |
|---|---|---|---|
| **Info** (`#eef4ff / #17447f`) | info chip | Rank reason explanation; "Backend suggested these qtys, you can edit freely." | No |
| **Warning** (`#fde8b1 / #6e4200`) | warning chip | Qty > available, partial accepted with justification missing, FEFO bypass detected | Partially — see below |
| **Critical** (`#fdddd8 / #8c1d13`) | critical chip | No stock anywhere, sum = 0 on an unskipped item, backend lock lost | Yes |

### 6.1 Qty exceeds available

Inline under the field: warning chip `▲ Cannot exceed 145 available at Port Antonio.`
Continue is disabled while any card is in this state. The card's pill shifts to `▲ Exceeds available`.

### 6.2 FEFO bypass warning (FR05.06c)

If the operator zeroes out the primary FEFO card while lower-ranked cards still have qty, show a **non-blocking** warning at the top of the stack:

```
▲  You have skipped the earliest-expiry warehouse. Stock at Port Antonio
   expires 12 May 2026 and should be moved first. Reason required to continue.
```

Paired with a required `<mat-form-field>` textarea, `bypass_reason`, min 10 chars, max 500 chars. Continue enabled once filled. This IS an override — see §6.4.

### 6.3 Partial fulfillment is NOT an override

This is the single most important distinction in the redesign. Today the UI implies that reserving less than requested is an exception. It isn't.

- **Compliant partial** — operator reserves everything available across all ranked warehouses, there is genuinely no more stock system-wide, and the operator explicitly clicks **Accept partial**. The aggregate strip shows `Status: Compliant partial · {short} short`, success-info tone (the existing `ops-chip--info` paired with a check icon). No reason required. FR05.06 considers the package fulfillable.
- **Override / non-compliant** — operator chooses not to use an available warehouse, OR zeros out the FEFO-primary when later cards have qty, OR manually edits quantities against the suggestion in a way that underfills despite available stock. This requires `bypass_reason`, renders with warning tone, and the package is flagged for override review downstream.

The UI distinguishes them with a small decision tree after the user clicks Accept partial:

```
Click "Accept partial"
 │
 ├─ remaining_shortfall_qty > 0 AND alternate_warehouses is empty
 │    → Compliant partial. Confirm dialog: "Confirm partial fulfillment (35 short)"
 │      Copy: "No other warehouses hold this item. The package will dispatch with 85 of 120."
 │      Confirm action = accept, no reason required.
 │
 └─ remaining_shortfall_qty > 0 AND alternate_warehouses is non-empty
      → Override-adjacent. Confirm dialog: "Accept partial despite available stock?"
        Copy: "2 other warehouses hold this item (SAV-LA-MAR 85, MONTEGO 40).
               Accepting partial here flags this package for override review."
        Requires bypass_reason textarea before confirm is enabled.
        confirmColor="warn"
```

### 6.4 Override surfacing

When bypass_reason is set on any card or at the package level, the aggregate strip adds an `Override flagged` chip in critical tone. The status card in the right rail (outside this spec) reads the same flag. On Continue, the payload includes `override_flagged: true` and `override_reason: "..."`.

### 6.5 Recovery state — no stock anywhere

When `warehouse_cards.length === 0` AND `alternate_warehouses.length === 0`, render the existing `app-ops-stock-availability-state` blocker (current screenshot shows this). Tighten the copy:

| Field | Current | Redesigned |
|---|---|---|
| Title | "FACE MASK, MEDIUM, 23 CM is not stocked in an available warehouse" | "No warehouse currently holds FACE MASK, MEDIUM, 23 CM" |
| Body | "The allocation workspace loaded successfully, but there are no matching stock lines to reserve for the selected item right now." | "Inventory shows zero availability across all warehouses for this item." |
| Impact | "Item-level blocker" | unchanged |
| Next step | "Choose another item, replenish stock in a valid warehouse, or return later once inventory for this item is available." | "Skip this item and accept partial, request inventory replenishment, or return once stock arrives." |
| Primary action | (none) | `Skip and mark partial` (stroked) · `Request replenishment` (stroked) · `Back to request` (tertiary) |

The workflow blocker copy is translated from the backend's raw `availability_state.code` into one of three operator-facing frames: `NO_MATCH_AT_SELECTED`, `NO_STOCK_ANYWHERE`, `LOCKED_BY_OTHER_OPERATOR`.

---

## 7. Presenting partial fulfillment

Partial must read as a **legitimate operational outcome**, not a mistake. Visual treatment:

- Aggregate strip `Status` cell shows `● Compliant partial` with info-success tone (success chip palette: `#edf7ef / #286a36`), not warning tone.
- Shortfall KPI stays info-tone (not critical) when compliant.
- The package-level summary (upstream of this screen) reports `2 of 7 items fully filled · 4 partial · 1 skipped` as a neutral breakdown, not a red error.
- When dispatched, the printable pack list shows `Partial fulfillment — 85 of 120. No other stock available system-wide.` as an audit trail.

The **only** thing that gets critical tone is: qty > available, no cards at all when `continuation_recommended` says there should be, or the bypass-without-reason state.

---

## 8. Mobile adaptation (< 520 px)

Kemar often works from a tablet in a field ops centre or a phone at a staging site. The allocation screen must not collapse into a scrolling wall.

### 8.1 Layout

- Stepper becomes a slim 3-dot progress bar with "Step 3 of 4 · Allocate".
- Items rail → a top-pinned `<mat-select>` labelled "Item 2 of 7 · FACE MASK…" with a 44 px hit target. Next/Prev chevrons on either side for one-tap walking.
- Metric strip drops to a 2-column grid showing only **Requested · Reserving** on the top row, **Shortfall · Status** on the bottom. Warehouses-used is folded into the aggregate bar.
- Warehouse cards become full-width. Rank badge moves under the warehouse name (not in a trailing cluster).
- Batch detail stays collapsed; expanded table becomes horizontally scrollable with the first column (lot no.) sticky.
- Step actions pin to the bottom of the viewport as a single row: `Back` (icon) · `Save draft` (icon) · `Continue` (full-width). Cancel moves into an overflow in the top bar.

### 8.2 Qty input ergonomics

- `inputmode="numeric"` + `pattern="[0-9]*"` to trigger numeric keypad.
- Thumb-reachable stepper: `–` and `+` buttons flank the input, each a 44 px square. Long-press increments by 10.
- **Use max** is a full-width button below the input on mobile, not a trailing chip.

### 8.3 Add warehouse on mobile

`ops-allocation-stack__add` opens a full-height bottom sheet instead of `<mat-menu>`, listing alternate warehouses with their rank, available, and expiry. Tap a row to add and auto-close.

### 8.4 Reduced motion

All transitions respect `prefers-reduced-motion: reduce` — entry animations and scroll behaviours go instant. Non-negotiable per generation.tsx §3.

---

## 9. Copy guidance

Voice: calm, operational, second-person, never scolding. No "you must" / "you cannot" — use "requires" / "exceeds".

| Surface | Copy |
|---|---|
| Page title (step 3) | Allocate items · Package {code} |
| Context strip — policy | FEFO first, FIFO on tie. Earlier-expiring stock is drawn down before newer stock. |
| Item header — FEFO badge | `FEFO` · tooltip: "First-Expired, First-Out — earliest-expiry batches ship first." |
| Aggregate KPI labels | Requested · Reserving · Shortfall · Warehouses used · Status |
| Aggregate status — filled | ● Filled · {n} warehouses |
| Aggregate status — partial ok | ● Compliant partial · {short} short |
| Aggregate status — draft | ◌ Draft |
| Aggregate status — override | ▲ Override flagged — reason required |
| Card rank — primary | Primary · FEFO  (or Primary · FIFO) |
| Card rank — follow-on | +1 · FEFO,  +2 · FEFO, … |
| Add warehouse — default | + Add another warehouse |
| Add warehouse — shortfall | + Add next warehouse ({n} available) |
| Add warehouse — exhausted | No further warehouses hold this item |
| Accept partial — default | Accept partial ({short} short) |
| Accept partial — override dialog title | Accept partial despite available stock? |
| Accept partial — compliant dialog title | Confirm partial fulfillment |
| Bypass reason label | Reason for skipping the earliest-expiry warehouse |
| Bypass reason helper | Recorded in the audit trail. Visible to reviewers and dispatch. |
| Validation — over | Cannot exceed {avail} available at {warehouse}. |
| Validation — no cards at all | Reserve at least one warehouse before continuing. |
| Cancel dialog (generation.tsx §4d) | Cancel this fulfillment? — unchanged from existing pattern. |

**Never say:** "override" when the operator is committing a compliant partial. **Never say:** "insufficient" when there's simply no stock anywhere — that framing blames the operator.

---

## 10. Component breakdown

Reuse-first. Only two net-new presentational components; everything else is a composition.

### 10.1 New

**`app-ops-allocation-card`** (§4)
- `selector: app-ops-allocation-card`
- Inputs (signals):
  - `card: InputSignal<OpsWarehouseCard>` — the full backend card.
  - `rank: InputSignal<number>` — 1-indexed rank.
  - `requestedQty: InputSignal<number>` — item's requested qty, for card-scope status.
  - `remainingShortfall: InputSignal<number>` — parent-computed.
  - `canRemove: InputSignal<boolean>` — false when it is the only card.
  - `rankingPolicy: InputSignal<'FEFO' | 'FIFO'>`.
- Outputs (signal functions):
  - `qtyChange: OutputEmitterRef<{ warehouseId: string; qty: number }>`
  - `batchQtyChange: OutputEmitterRef<{ warehouseId: string; batchId: string; qty: number }>`
  - `removeRequested: OutputEmitterRef<string>`
  - `bypassReasonChange: OutputEmitterRef<{ warehouseId: string; reason: string | null }>`
- Internal signals: `expanded`, `localQty`, `localBypassReason`.
- Template: header / reason / qty row / batch detail / status pill as §4.1.
- OnPush. Uses `@for` with track on batch id.

**`app-ops-allocation-stack`** (§4, §5)
- Wraps the card list + `ops-allocation-stack__add` + `ops-allocation-summary`.
- `selector: app-ops-allocation-stack`
- Inputs:
  - `cards: InputSignal<OpsWarehouseCard[]>`
  - `alternateWarehouses: InputSignal<OpsAlternateWarehouse[]>`
  - `requestedQty: InputSignal<number>`
  - `rankingPolicy: InputSignal<'FEFO' | 'FIFO'>`
- Outputs:
  - `cardAdded: OutputEmitterRef<string>`  ( warehouseId )
  - `cardRemoved: OutputEmitterRef<string>`
  - `qtyChanged: OutputEmitterRef<{ warehouseId: string; qty: number }>`
  - `acceptPartialRequested: OutputEmitterRef<{ reason: string | null }>`
- Computed:
  - `totalReserving = sum(cards.qty)`
  - `shortfall = max(0, requestedQty - totalReserving)`
  - `aggregateStatus: 'DRAFT' | 'FILLED' | 'PARTIAL_COMPLIANT' | 'PARTIAL_OVERRIDE' | 'OVER'`
- Owns the mat-menu / bottom-sheet for add, the aggregate bar, and the Accept partial confirm dialog invocation.

### 10.2 Reused without change

- `app-ops-metric-strip` — for the top KPI row.
- `app-ops-status-chip` — rank pills, card status pills, aggregate status.
- `app-ops-stock-availability-state` — zero-stock blocker (§6.5, with tightened copy).
- `app-dmis-empty-state` — rail when no items are left to allocate.
- `app-dmis-skeleton-loader` — on initial fetch of `warehouse_cards`.
- `DmisConfirmDialogComponent` — Accept partial and Cancel confirms.
- `ops-context-strip`, `ops-form-actions`, `ops-shell`, `dmis-step-tracker` — layout primitives.

### 10.3 Retired

- The old single-select "Available warehouses" panel with linked batch table — replaced entirely by the stack + per-card batch detail.
- The top-right "Clear selection · Manual override" link cluster — relocated into card overflow and the bypass-reason flow.

### 10.4 Types (TypeScript contracts the component will consume)

```ts
interface OpsItemAllocation {
  itemId: string;
  itemName: string;
  itemCode: string;
  requestedQty: number;
  rankingPolicy: 'FEFO' | 'FIFO';
  recommendedWarehouseId: string;
  selectedWarehouseIds: string[];
  warehouseCards: OpsWarehouseCard[];
  alternateWarehouses: OpsAlternateWarehouse[];
  remainingShortfallQty: number;
  continuationRecommended: boolean;
  availabilityState: OpsAvailabilityState | null;  // blocker case
  overrideFlagged: boolean;
  overrideReason: string | null;
}

interface OpsWarehouseCard {
  warehouseId: string;
  warehouseName: string;
  totalAvailable: number;
  suggestedQty: number;
  issuanceOrder: number;         // rank, 1-indexed
  rankReason: OpsRankReason | null;
  rankReasonDate?: string;       // ISO, for EARLIEST_EXPIRY / EARLIEST_RECEIPT
  rankReasonPct?: number;        // for EARLIEST_EXPIRY coverage
  batches: OpsBatchLine[];
  qty: number;                   // operator-editable, starts at suggestedQty
  bypassReason: string | null;   // set only on override
}

interface OpsBatchLine {
  batchId: string;
  lotNo: string;
  receiptDate: string;
  expiryDate: string | null;
  available: number;
  reservedInOtherPackages: number;
  qtyToReserve: number;
}

interface OpsAlternateWarehouse {
  warehouseId: string;
  warehouseName: string;
  available: number;
  issuanceOrder: number;
  nextExpiryDate?: string;
}

type OpsRankReason =
  | 'EARLIEST_EXPIRY'
  | 'EARLIEST_RECEIPT'
  | 'COVERS_REMAINDER'
  | 'PROXIMITY'
  | 'LAST_RESORT';
```

Commit payload on Continue — matches the FR05.06 backend contract:

```ts
interface OpsAllocationCommit {
  packageId: string;
  idempotencyKey: string;
  items: Array<{
    itemId: string;
    lines: Array<{
      warehouseId: string;
      batchId: string;
      qty: number;
    }>;
    acceptedPartial: boolean;
    overrideReason: string | null;
  }>;
}
```

One line per (item, warehouse, batch) — respects the `OperationsAllocationLine` unique constraint called out in generation.tsx §4c.

---

## 11. State & interaction notes for the implementer

1. **Signal ownership.** The parent workspace (`package-fulfillment-workspace.component.ts`) owns the `FormGroup`-less signal store: one top-level `allocations = signal<Map<itemId, OpsItemAllocation>>(...)`. `ops-allocation-stack` is pure presentational — it emits changes, never mutates. Generation.tsx §4b: "Step components are presentational."
2. **Derived state only.** `shortfall`, `totalReserving`, `aggregateStatus`, `canContinue` are all `computed()` from the store. Never store them.
3. **Optimistic updates.** Adding a warehouse inserts the card synchronously from `alternateWarehouses`; the backend confirmation updates `suggestedQty` + batch rows when it returns. If backend fails, the card is removed and an error toast fires.
4. **Debounced qty commits.** Qty input `valueChanges` pipes through `debounceTime(250)` → workspace store. No commit on every keystroke.
5. **Auto-advance on complete.** When an item's `aggregateStatus === 'FILLED'` (not PARTIAL), the left-rail selection advances to the next unfulfilled item after 300 ms. If `prefers-reduced-motion`, advance immediately. Operator can disable in Tweaks-style preference (out of scope).
6. **Draft persistence.** Save Draft POSTs the current `allocations` snapshot. On reload, the same shape rehydrates from `GET /packages/{id}/allocation-workspace`. The stepper position is persisted alongside.
7. **Continue validation gate.** Continue is enabled when for every item: `aggregateStatus !== 'OVER'` AND (status === 'FILLED' OR acceptedPartial === true OR item is explicitly skipped).
8. **Override reason coupling.** Setting any card's qty in a way that triggers FEFO bypass (§6.2) forces `overrideFlagged = true` at the item level; the reason textarea becomes required. Clearing the bypass condition does NOT auto-clear the reason — the operator must remove it manually (audit hygiene).
9. **Cancel wiring.** Reuse the abandon-draft endpoint from generation.tsx §4d. Cancel confirm, Idempotency-Key header, release locks, delete draft lines, return request to `APPROVED_FOR_FULFILLMENT`. Visible on every step incl. this one.
10. **Never scrollIntoView.** Use `window.scrollTo` on the allocation pane's scroll container (per system prompt rule).
11. **Locking.** If the workspace loses its lock mid-allocation (backend returns `LOCKED_BY_OTHER_OPERATOR`), render the zero-stock blocker variant with a dedicated reason: "Another operator took over this package. Return to the request to see who." Continue is disabled.
12. **No `[innerHTML]`.** All dynamic copy goes through interpolation and a typed copy-map keyed on the backend enums.

---

## 12. Accessibility

Baseline from generation.tsx §6 plus surface-specific needs:

- Every `ops-allocation-card` is `role="group"` with `aria-label="Warehouse allocation: {warehouseName}, rank {n} of {total}"`.
- Rank pill text is always visible and machine-readable — never conveyed by color alone.
- Status chips pair `<mat-icon>` + text; `aria-label` on the icon mirrors the chip text so SR users don't hear duplication.
- Qty input: associated `<mat-label>`, `aria-describedby="qty-hint-{warehouseId} qty-error-{warehouseId}"` pointing at the helper and validation nodes.
- Aggregate bar is `role="status"` `aria-live="polite"` — shortfall changes and status transitions are announced without interrupting.
- Remove warehouse button: `aria-label="Remove {warehouseName} from allocation"`.
- Bypass-reason textarea: required field announced via `aria-required="true"` AND a visible asterisk; error message tied via `aria-describedby`.
- Add-warehouse menu: `role="menu"` with `role="menuitem"` rows; each row's accessible name is `"Add {warehouseName}, rank +{n-1}, {available} available, next expiry {date}"`.
- Keyboard:
  - Tab order: rank pill (none, decorative) → qty input → Use max → Clear → overflow menu → batch disclosure → next card.
  - Shift+↑/↓ on qty = ±10.
  - Enter on Add warehouse opens the menu; Esc closes it.
- Focus management: when a card is added, focus moves to its qty input; when a card is removed, focus lands on the preceding card's qty input, or on Add warehouse if it was the only non-primary.
- Reduced motion: all 180 ms transitions become 0 ms; scroll-into-view is instant.
- Color independence: the Filled/Partial/Override distinction is carried by icon, pill text, and tone — any one alone is sufficient.
- Contrast: all token pairs used (§generation.tsx §1) already pass WCAG AA; no new color pairs are introduced.

---

## 13. Open questions and tradeoffs

1. **Should `Accept partial` require a reason when the shortfall is structurally unavoidable?** Current spec says no (compliant partial = no reason). Audit team may want an optional free-text field anyway. Recommend: keep mandatory-off, add optional "Notes to dispatch" at the package level instead of per-item.
2. **Batch-level editing in mobile.** The horizontally-scrollable batch table is workable but not great on a small phone. Option: on < 520 px, collapse the batch table entirely and force the card-level qty to distribute greedily with no manual batch picking. Recommend this unless audit requires batch-edit on mobile.
3. **"Use max" semantics when other cards have qty.** Current: sets this card to `min(available_here, remaining_shortfall + current_qty)` — i.e. fills exactly to the shortfall. Alternative: sets to `available_here` regardless, letting total exceed requested. Recommend current behavior; exceeding requested is not a legitimate state.
4. **Auto-advance on Filled.** Some operators may find this jarring. Consider a user-preference toggle in a later phase. Leaving it on by default matches field-feedback that Kemar moves through many items fast.
5. **Continuation without primary.** If an operator zeros the primary FEFO card entirely (not partial — fully skipped), do we keep the card rendered with zero qty for audit, or remove it and show a "primary skipped" chip in its place? Recommend: keep the card, set `bypassReason` required on it, so the evidence is legible. Implementer decision.
6. **`rank_reason` for non-FEFO/FIFO rules.** Proximity and last-resort are handled. If the backend later adds donor-preference or cost-weighted ranking, add new enums rather than repurposing existing ones.
7. **Items rail on tablets.** 760–1100 px collapses to a horizontal chip row. For packages with 20+ items this gets unwieldy; we may want a "Jump to item" overflow. Deferred to a follow-up once data shows package size distribution.
8. **Printing / export.** Not in this scope, but the data contract (§10.4) is print-friendly — a later phase can render a PDF of the same shape.

---

## 14. What stays the same

Explicitly **not** redesigned:
- Operations module shell, nav, and chrome.
- Dispatch and receipt surfaces.
- Override review (the screen operators go to after this one flags an override).
- Request queue, package queue.
- The step tracker visual — we reuse `dmis-step-tracker` unchanged.
- Button hierarchy tiers — pulled straight from `operations-shell.scss`.

The redesign is **additive within the DMIS system**, not a visual reboot.
