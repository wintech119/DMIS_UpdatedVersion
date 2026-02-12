# DMIS Supply Replenishment Module - Codex Prompt Guide

> **How to use:** Copy the **Context Block** at the start of each session, then use individual prompts. Always paste relevant code with each prompt.

---

## 🔹 CONTEXT BLOCK (Paste at start of every session)

```text
PROJECT: DMIS (Disaster Management Information System) - Jamaica ODPEM
MODULE: EP-02 Supply Replenishment / Needs List Generation

TECH STACK:
- Frontend: Angular 21+, Angular Material, TypeScript
- Backend: Django 6.0, Django REST Framework
- Database: PostgreSQL 16+

PRIMARY USER: Kemar (Logistics Manager)
- Works in the field on mobile devices
- Needs fast, accurate, real-time visibility
- Low tolerance for messy data
- "If it's not logged, it didn't happen"

KEY BUSINESS LOGIC:

Event Phases:
| Phase      | Demand Window | Planning Window |
|------------|---------------|-----------------|
| SURGE      | 6 hours       | 72 hours        |
| STABILIZED | 72 hours      | 7 days          |
| BASELINE   | 30 days       | 30 days         |

Formulas:
- Burn Rate = Fulfilled Qty ÷ Demand Window (hours) → units/hour
- Time-to-Stockout = Available Stock ÷ Burn Rate → hours
- Required Qty = Burn Rate × Planning Window × 1.25
- Gap = Required Qty - (Available Stock + Confirmed Inbound)

Severity Levels (based on Time-to-Stockout):
- CRITICAL (red): < 8 hours
- WARNING (amber): 8-24 hours
- WATCH (yellow): 24-72 hours
- OK (green): > 72 hours

Data Freshness (based on last sync time):
- HIGH (green): < 2 hours old
- MEDIUM (amber): 2-6 hours old
- LOW (red): > 6 hours old

Three Horizons (replenishment sources in order):
- Horizon A: Transfers (6-8 hour lead time)
- Horizon B: Donations (2-7 days lead time)
- Horizon C: Procurement (14+ days lead time)

API ENDPOINTS:
- GET  /api/replenishment/stock-status/
- GET  /api/replenishment/burn-rates/
- POST /api/replenishment/needs-list/generate/
- GET  /api/replenishment/needs-list/{id}/
- POST /api/replenishment/needs-list/{id}/submit/
- POST /api/replenishment/needs-list/{id}/approve/
- POST /api/replenishment/needs-list/{id}/reject/
```

---

## 🔹 PROMPT 1: Dashboard Visual Hierarchy

**Task:** Improve stock overview dashboard so critical items are immediately visible.

```
TASK: Refactor this Angular dashboard component to improve visual hierarchy.

REQUIREMENTS:
1. Sort items by Time-to-Stockout ascending (most urgent first)
2. Add severity-based row styling:
   - CRITICAL (< 8 hours): red background (#FFEBEE), red left border
   - WARNING (8-24 hours): amber background (#FFF8E1), amber left border
   - WATCH (24-72 hours): yellow background (#FFFDE7)
   - OK (> 72 hours): no special styling
3. Add a summary card at top showing:
   - Count of CRITICAL items
   - Count of WARNING items
   - "Generate Needs List" button (primary color when CRITICAL > 0)
4. Show last data sync timestamp in header

CURRENT CODE:
[PASTE YOUR COMPONENT .ts AND .html HERE]

OUTPUT: Updated component files with the changes.
```

---

## 🔹 PROMPT 2: Burn Rate Display

**Task:** Improve burn rate display with units, trends, and confidence.

```
TASK: Create/update an Angular component to display burn rate with context.

REQUIREMENTS:
1. Display format: "50 units/hr" (not just "50")
2. Add trend indicator:
   - ↑ (up arrow) if burn rate increased >10% from previous period
   - ↓ (down arrow) if decreased >10%
   - → (stable) if within ±10%
3. Add confidence badge based on data freshness:
   - HIGH: green badge, no icon
   - MEDIUM: amber badge, ⚠ icon
   - LOW: red badge, ⛔ icon, tooltip "Data is X hours old"
4. Special cases:
   - If burn rate = 0 AND data is fresh: show "0 - No demand" in gray
   - If burn rate = 0 AND data is stale: show "0 (est.)" in amber with warning

INPUTS:
- burnRate: number (units per hour)
- previousBurnRate: number (for trend)
- lastSyncTime: Date
- uom: string (unit of measure)

CURRENT CODE (if updating existing):
[PASTE YOUR COMPONENT HERE]

OUTPUT: Complete Angular component (.ts, .html, .scss)
```

---

## 🔹 PROMPT 3: Time-to-Stockout Display

**Task:** Create a countdown-style time-to-stockout component.

```
TASK: Create an Angular component for Time-to-Stockout display.

REQUIREMENTS:
1. Display format: "4h 30m" or "2d 6h" (days if > 24 hours)
2. Color coding based on severity:
   - CRITICAL (< 8 hrs): red (#F44336), pulsing animation
   - WARNING (8-24 hrs): amber (#FF9800)
   - WATCH (24-72 hrs): yellow (#FFC107)
   - OK (> 72 hrs): green (#4CAF50)
3. Show progress bar (100% = full stock, 0% = stockout)
4. Add action icon indicating recommended horizon:
   - 🚚 if < 8 hours (Horizon A - Transfer)
   - 📦 if 8-72 hours (Horizon B - Donation)
   - 🛒 if > 72 hours (Horizon C - Procurement)
5. If Time-to-Stockout is null/infinite (no burn rate): show "∞" with "No demand" text

INPUTS:
- availableStock: number
- burnRate: number
- severity: 'CRITICAL' | 'WARNING' | 'WATCH' | 'OK'

OUTPUT: Complete Angular component with:
- time-to-stockout.component.ts
- time-to-stockout.component.html
- time-to-stockout.component.scss
```

---

## 🔹 PROMPT 4: Data Freshness Warning Banner

**Task:** Create persistent warning banner for stale data.

```
TASK: Create an Angular component for data freshness warning banner.

REQUIREMENTS:
1. Three states:
   - ALL_FRESH: No banner shown
   - SOME_STALE: Amber banner
     Text: "⚠ Warning: Some warehouse data is stale. [View Details]"
   - CRITICAL_STALE: Red banner (cannot be dismissed)
     Text: "⛔ Critical: {warehouseName} data is {hours} hours old."
2. Banner is sticky at top of content area (below main nav)
3. "View Details" expands to show per-warehouse freshness table:
   | Warehouse | Last Sync | Status |
4. Include "Refresh Data" button that emits an event
5. Use Angular Material components (MatToolbar, MatExpansionPanel)

INPUTS:
- warehouses: Array<{ id, name, lastSync: Date, status: string }>

EVENTS:
- refreshRequested: EventEmitter<void>

OUTPUT: Complete Angular component files.
```

---

## 🔹 PROMPT 5: Needs List Generation Wizard

**Task:** Create a 3-step wizard for generating needs lists.

```
TASK: Create an Angular stepper component for needs list generation.

REQUIREMENTS:

STEP 1 - "Select Scope":
- Show current event phase (SURGE/STABILIZED/BASELINE) as read-only chip
- Checkbox list of warehouses to include (default: all checked)
- Display planning window and demand window for current phase
- "Calculate Gaps" button to proceed

STEP 2 - "Review Results":
- Table with columns: Item | Warehouse | Gap | Source (A/B/C) | Lead Time
- Allow quantity adjustment:
  - Click quantity to edit
  - If changed, require reason dropdown: "Demand Adjusted", "Partial Coverage", "Budget Constraint", "Other"
- Show total gap quantity and estimated value at bottom
- Highlight items that can't be fully covered in amber

STEP 3 - "Submit":
- Summary card: X items, Y total units, Z estimated value
- Show approver based on phase (SURGE: Senior Director, BASELINE: Logistics Manager)
- Optional notes textarea
- Two buttons: "Save as Draft" (secondary), "Submit for Approval" (primary)

Use Angular Material Stepper (MatStepper).

INPUTS:
- eventPhase: string
- phaseConfig: { demandWindow, planningWindow }
- warehouses: Array<Warehouse>

API CALLS:
- POST /api/replenishment/needs-list/generate/ (Step 1 → 2)
- POST /api/replenishment/needs-list/{id}/submit/ (Step 3)

OUTPUT: Complete stepper component with all three steps.
```

---

## 🔹 PROMPT 6: Three Horizons Display

**Task:** Create visual Three Horizons allocation component.

```
TASK: Create an Angular component showing Three Horizons breakdown.

REQUIREMENTS:
1. Three columns (or tabs on mobile):

   HORIZON A - TRANSFERS
   - Header: green (#4CAF50), truck icon 🚚
   - Lead time: "6-8 hours"
   - Show: source warehouse name, available surplus
   - Quantity allocated to this horizon
   - Button: "Create Transfer" (if qty > 0)

   HORIZON B - DONATIONS
   - Header: blue (#2196F3), box icon 📦
   - Lead time: "2-7 days"
   - Show: expected donations in pipeline
   - Quantity allocated to this horizon
   - Button: "Request Donation" (if qty > 0)

   HORIZON C - PROCUREMENT
   - Header: orange (#FF9800), cart icon 🛒
   - Lead time: "14+ days"
   - Show: remaining gap after A and B
   - Quantity allocated to this horizon
   - Button: "Generate Procurement" (if qty > 0)

2. Show waterfall visualization:
   Total Gap: 3,500 → [A: 800] → [B: 1,000] → [C: 1,700]

3. Responsive: stack vertically on mobile (< 768px)

INPUTS:
- totalGap: number
- horizonA: { qty, sourceWarehouse, leadTimeHours }
- horizonB: { qty, expectedDonations, leadTimeHours }
- horizonC: { qty, leadTimeHours }

OUTPUT: Complete Angular component files.
```

---

## 🔹 PROMPT 7: Approval Workflow Status Tracker

**Task:** Create visual status tracker for needs list workflow.

```
TASK: Create an Angular component showing approval workflow status.

REQUIREMENTS:
1. Horizontal stepper showing statuses:
   [DRAFT] → [PENDING APPROVAL] → [APPROVED] → [IN PROGRESS] → [FULFILLED]

2. Each step shows:
   - Circle icon (checkmark if complete, dot if current, empty if future)
   - Status name
   - Timestamp when reached (if applicable)
   - User who performed action (if applicable)

3. For PENDING_APPROVAL status, show:
   - "Awaiting: {approverRole}" (e.g., "Senior Director")
   - "Pending for: {hours} hours"
   - "Send Reminder" button if pending > 4 hours

4. For REJECTED/RETURNED, show:
   - Branch off from PENDING with red styling
   - Display rejection reason
   - "Revise" button

5. Expandable details panel below stepper with full audit history

INPUTS:
- currentStatus: string
- statusHistory: Array<{ status, timestamp, user, notes }>
- approverRole: string

EVENTS:
- sendReminder: EventEmitter<void>
- revise: EventEmitter<void>

OUTPUT: Complete Angular component files.
```

---

## 🔹 PROMPT 8: Approval Functionality (API Integration)

**Task:** Connect approval UI to backend APIs.

```
TASK: Add approval functionality to the needs list detail component.

REQUIREMENTS:
1. "Submit for Approval" button:
   - Calls POST /api/replenishment/needs-list/{id}/submit/
   - Disabled if status !== 'DRAFT'
   - Show loading spinner during request
   - On success: update status, show success toast
   - On error: show error toast with message

2. "Approve" button (only visible to approvers):
   - Calls POST /api/replenishment/needs-list/{id}/approve/
   - Optional notes field
   - Disabled if status !== 'PENDING_APPROVAL'
   - On success: update status, show success toast

3. "Reject" button (only visible to approvers):
   - Opens dialog with required reason field
   - Calls POST /api/replenishment/needs-list/{id}/reject/
   - Body: { reason: string, notes?: string }
   - On success: update status, show info toast

4. Role-based visibility:
   - Submit: visible to Logistics Manager when status = DRAFT
   - Approve/Reject: visible to Senior Director (SURGE) or Logistics Manager (BASELINE)

CURRENT CODE:
[PASTE YOUR NEEDS LIST DETAIL COMPONENT HERE]

CURRENT SERVICE:
[PASTE YOUR REPLENISHMENT SERVICE HERE]

OUTPUT: Updated component and service with approval methods.
```

---

## 🔹 PROMPT 9: Mobile Responsiveness

**Task:** Make components mobile-friendly.

```
TASK: Update this component for mobile responsiveness.

REQUIREMENTS:
1. Breakpoint: 768px
2. For screens < 768px:
   - Data tables become card lists (one card per row)
   - Filter panel becomes bottom sheet or collapsible drawer
   - Action buttons become FAB (floating action button) at bottom right
   - Horizontal steppers become vertical
3. Touch targets: minimum 44x44px
4. Critical alerts should be MORE prominent on mobile (larger font, top of screen)

CURRENT CODE:
[PASTE YOUR COMPONENT .html AND .scss HERE]

OUTPUT: Updated template and styles with mobile breakpoints.
```

---

## 🔹 PROMPT 10: Loading States

**Task:** Add loading skeletons and states.

```
TASK: Add loading states to this component.

REQUIREMENTS:
1. Initial page load: Show skeleton screens (not spinners)
   - Use Angular Material placeholder styling
   - Match layout of actual content
2. Data refresh: Subtle spinner in header, don't block UI
3. Form submission: Button loading state with spinner, disable button
4. Error state: Toast notification with retry button

CURRENT CODE:
[PASTE YOUR COMPONENT HERE]

OUTPUT: Updated component with loading states and skeleton template.
```

---

## 🔹 PROMPT 11: Error Handling

**Task:** Add comprehensive error handling.

```
TASK: Add error handling to this Angular service and component.

REQUIREMENTS:
1. Network error: Show toast "Connection error. Please try again." + Retry button
2. 400 Bad Request: Show inline validation errors from response
3. 401 Unauthorized: Redirect to login
4. 403 Forbidden: Show toast "You don't have permission for this action"
5. 404 Not Found: Show "Item not found" message
6. 500 Server Error: Show toast "Something went wrong" + "Report Issue" button
7. Timeout (>30s): Show toast "Request timed out" + Retry button

CURRENT SERVICE:
[PASTE YOUR SERVICE HERE]

CURRENT COMPONENT:
[PASTE YOUR COMPONENT HERE]

OUTPUT: Updated service with error interceptor and component with error handling.
```

---

## 🔹 PROMPT 12: Unit Tests

**Task:** Generate unit tests for a component.

```
TASK: Write Jasmine unit tests for this Angular component.

TEST CASES:
1. Should display burn rate with correct units (e.g., "50 units/hr")
2. Should show CRITICAL styling when time-to-stockout < 8 hours
3. Should show WARNING styling when time-to-stockout is 8-24 hours
4. Should show "∞ - No demand" when burn rate is 0 and data is fresh
5. Should show warning badge when data freshness is LOW
6. Should emit event when refresh button clicked
7. Should handle null/undefined inputs gracefully

COMPONENT CODE:
[PASTE YOUR COMPONENT HERE]

OUTPUT: Complete .spec.ts file with all test cases.
```

---

## 🔹 QUICK REFERENCE: Common Patterns

### Angular Material Imports
```typescript
import { MatTableModule } from '@angular/material/table';
import { MatChipsModule } from '@angular/material/chips';
import { MatStepperModule } from '@angular/material/stepper';
import { MatSnackBarModule } from '@angular/material/snack-bar';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatDialogModule } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
```

### Severity Colors
```scss
$critical: #F44336;
$warning: #FF9800;
$watch: #FFC107;
$ok: #4CAF50;

$critical-bg: #FFEBEE;
$warning-bg: #FFF8E1;
$watch-bg: #FFFDE7;
$ok-bg: #E8F5E9;
```

### Status Enum
```typescript
enum NeedsListStatus {
  DRAFT = 'DRAFT',
  PENDING_APPROVAL = 'PENDING_APPROVAL',
  APPROVED = 'APPROVED',
  REJECTED = 'REJECTED',
  RETURNED = 'RETURNED',
  IN_PROGRESS = 'IN_PROGRESS',
  FULFILLED = 'FULFILLED',
  CANCELLED = 'CANCELLED',
  SUPERSEDED = 'SUPERSEDED'
}
```

---

## 🔹 TIPS FOR CODEX

1. **One task per prompt** — don't combine multiple features
2. **Always include current code** — Codex can't browse your files
3. **Specify output format** — "Output: complete .ts and .html files"
4. **Include types/interfaces** — helps Codex generate correct code
5. **If output is truncated**, ask: "Continue from where you left off"
6. **For fixes**, show the error message and relevant code

---

*Last updated: February 2026*
