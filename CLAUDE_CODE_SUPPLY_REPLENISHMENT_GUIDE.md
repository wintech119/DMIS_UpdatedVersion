# Claude Code Prompt Guide: DMIS Supply Replenishment Module (EP-02)

## Overview

This guide provides structured prompts and context for using Claude Code in Cursor AI to refine the Supply Replenishment (Needs List Generation) module. The goal is to create a seamless, intuitive UI/UX that Kemar (Logistics Manager) can use efficiently under pressure.

---

## 🎯 Primary User: Kemar (Logistics Manager)

**Key Traits to Design For:**
- **Field-first mindset**: Expects mobile-friendly workflows, near real-time visibility
- **Low tolerance for messy data**: Wants fast entry with controls that prevent errors
- **Bias for speed and accuracy**: If it's not logged, it didn't happen
- **Frequently in the field**: Needs remote visibility, works under pressure

**What Success Looks Like for Kemar:**
> "I can see at a glance which items are at risk, generate a needs list in 3 clicks, and submit it for approval before the stockout happens."

---

## 📋 Project Context (Paste at Start of Session)

```
I'm working on the DMIS (Disaster Management Information System) Supply Replenishment module.

Tech Stack:
- Frontend: Angular 18+, Angular Material, TypeScript
- Backend: Django 6.0, Django REST Framework
- Database: PostgreSQL 16+
- State Management: NgRx (if used) or component state

The Supply Replenishment module (EP-02) helps Logistics Managers:
1. Monitor stock levels and burn rates across warehouses
2. Calculate time-to-stockout for critical items
3. Generate draft needs lists when gaps are detected
4. Submit needs lists for approval (SURGE: Senior Director, BASELINE: Logistics Manager)
5. Track replenishment through Three Horizons: A (Transfers), B (Donations), C (Procurement)

Key Formulas:
- Burn Rate = Total Fulfilled Quantity / Demand Window Hours
- Time-to-Stockout = Available Stock / Burn Rate
- Required Quantity = Burn Rate × Planning Window × Safety Factor (1.25)
- Gap = Required Quantity - (Available Stock + Confirmed Inbound)

Event Phases:
- SURGE: Demand Window = 6hrs, Planning Window = 72hrs
- STABILIZED: Demand Window = 72hrs, Planning Window = 7 days
- BASELINE: Demand Window = 30 days, Planning Window = 30 days

The primary user is Kemar, a Logistics Manager who needs fast, accurate, mobile-friendly interfaces.
```

---

## 🔧 UI/UX Improvement Prompts by Screen

### 1. Dashboard / Stock Overview Screen

**Current Issues to Fix:**
- Too much data, not enough hierarchy
- Critical alerts not prominent enough
- Unclear what action to take next

**Prompt:**
```
Review my stock overview dashboard component. I need to improve the visual hierarchy so that:

1. CRITICAL items (Time-to-Stockout < 8 hours) are immediately visible with red alert styling
2. WARNING items (8-24 hours) show in amber
3. HEALTHY items (>24 hours) are de-emphasized

Add a "Quick Actions" card at the top showing:
- Count of items needing attention by severity
- "Generate Needs List" button that's prominent when there are critical items
- Last data sync timestamp with freshness indicator (green/amber/red)

The user (Kemar) should be able to understand the situation in 5 seconds.
```

**Follow-up:**
```
Now add sorting and filtering:
1. Default sort by Time-to-Stockout ascending (most urgent first)
2. Filter chips for: Warehouse, Item Category, Event Phase, Severity Level
3. Remember filter state in localStorage so Kemar doesn't have to re-select each time
4. Add a "Reset Filters" button

Make sure the filters are collapsible on mobile to save screen space.
```

---

### 2. Burn Rate Calculation Display

**Current Issues:**
- Numbers without context are meaningless
- No visual trend indication
- Data freshness not shown

**Prompt:**
```
Improve the burn rate display for each item. Currently it just shows a number.

Change it to show:
1. Burn rate with units: "50 units/hr" not just "50"
2. Mini sparkline chart showing 24hr trend (up/down/stable arrow if chart is too complex)
3. Confidence indicator based on data freshness:
   - HIGH (green): Data < 2 hours old
   - MEDIUM (amber): Data 2-6 hours old  
   - LOW (red): Data > 6 hours old, show "⚠ Stale Data" badge
4. Tooltip on hover showing: "Based on X fulfillments over Y hours"

If burn rate is 0 with stale data, show: "0 (estimated - no recent data)" in amber
If burn rate is genuinely 0 with fresh data, show: "0 - No current demand" in gray
```

---

### 3. Time-to-Stockout Visualization

**Prompt:**
```
Create a Time-to-Stockout component that makes urgency immediately clear.

Requirements:
1. Show as a countdown-style display: "4h 30m until stockout"
2. Color coding:
   - CRITICAL (red, pulsing): < 8 hours (less than lead time for transfers)
   - WARNING (amber): 8-24 hours
   - WATCH (yellow): 24-72 hours
   - OK (green): > 72 hours
3. Progress bar showing stock depletion visually
4. If Time-to-Stockout is N/A (no burn rate), show "∞ - No current demand"

Add an icon that shows the recommended action:
- 🚚 (truck): Can be resolved with transfer (Horizon A)
- 📦 (box): Needs donation (Horizon B)  
- 🛒 (cart): Requires procurement (Horizon C)

This helps Kemar instantly know what type of action is needed.
```

---

### 4. Needs List Generation Workflow

**Current Issues:**
- Multi-step process is confusing
- User doesn't understand what will happen
- No preview before generation

**Prompt:**
```
Redesign the Needs List generation flow to be a clear 3-step wizard:

Step 1: Review & Confirm Scope
- Show which warehouses and items will be included
- Display current event phase (SURGE/STABILIZED/BASELINE) with key parameters
- Checkbox to include/exclude specific warehouses
- "Calculate Gaps" button

Step 2: Preview Results
- Table showing: Item | Warehouse | Gap | Recommended Source (A/B/C) | Lead Time
- Allow quantity adjustment with mandatory reason field (dropdown: "Partial Coverage", "Demand Adjusted", "Other")
- Show total estimated cost if available
- Highlight any items that can't be fully covered

Step 3: Submit for Approval
- Summary card: X items, Y total units, Z estimated cost
- Show who will approve (based on event phase and value)
- Optional notes field
- "Submit for Approval" primary button, "Save as Draft" secondary button

Add a stepper component at the top so user knows where they are.
```

---

### 5. Three Horizons Display

**Prompt:**
```
Create a visual Three Horizons component for the needs list detail view.

Layout: Three columns or tabs (based on screen size):

HORIZON A - TRANSFERS (Hours)
- Icon: 🚚
- Color: Green (#4CAF50)
- Lead Time: 6-8 hours
- Show: Available surplus from other warehouses
- Action: "Create Transfer Request"

HORIZON B - DONATIONS (Days)  
- Icon: 📦
- Color: Blue (#2196F3)
- Lead Time: 2-7 days
- Show: Expected donations in pipeline
- Action: "Request from Donors"

HORIZON C - PROCUREMENT (Weeks)
- Icon: 🛒
- Color: Orange (#FF9800)
- Lead Time: 14+ days
- Show: Remaining gap after A and B
- Action: "Generate Procurement Package"

For each horizon, show:
- Quantity that can be fulfilled
- Remaining gap passing to next horizon
- Estimated arrival date

Make it clear this is a waterfall: A fills first, remainder goes to B, remainder goes to C.
```

---

### 6. Data Freshness Warning Banner

**Prompt:**
```
Create a persistent warning banner component for data freshness issues.

States:
1. ALL_FRESH: No banner shown
2. SOME_STALE: Amber banner at top of page
   "⚠ Warning: Some warehouse data is stale. [View Details]"
3. CRITICAL_STALE: Red banner, cannot be dismissed
   "⛔ Critical: [Warehouse Name] data is [X] hours old. Burn rate calculations may be inaccurate."

The banner should:
- Be sticky at the top of the content area (below nav)
- Expand on click to show per-warehouse freshness table
- Have a "Refresh Data" button that triggers a sync
- Show last successful sync time

This is critical because Kemar should never approve a needs list based on stale data without knowing.
```

---

### 7. Approval Workflow Status

**Prompt:**
```
Create a visual status tracker for needs list approval workflow.

Show as a horizontal stepper:
[DRAFT] → [PENDING APPROVAL] → [APPROVED] → [IN PROGRESS] → [FULFILLED]

Each step should show:
- Status icon (circle with checkmark when complete, current step highlighted)
- Timestamp when that status was reached
- User who performed the action
- Comments/notes if any

For PENDING APPROVAL, show:
- Who needs to approve (role + name if known)
- Approval threshold that applies
- "Send Reminder" button if pending > 4 hours

For rejected items, show a branch:
[PENDING APPROVAL] → [RETURNED FOR REVISION] (red)
With the rejection reason displayed.

Add these details in an expandable panel below the stepper.
```

---

### 8. Mobile Responsiveness

**Prompt:**
```
Review my Supply Replenishment components for mobile responsiveness.

Key requirements for Kemar in the field:
1. Dashboard cards should stack vertically on mobile
2. Data tables should become card lists on screens < 768px
3. Filter panel should be a bottom sheet or slide-out drawer on mobile
4. Critical alerts should be even MORE prominent on mobile (larger, top of screen)
5. "Generate Needs List" button should be a FAB (floating action button) on mobile
6. Touch targets should be at least 44x44px

Check each component and suggest specific changes for mobile breakpoints.
Focus on the most common mobile action: checking stock status and generating a quick needs list.
```

---

### 9. Loading States and Error Handling

**Prompt:**
```
Add proper loading and error states to all Supply Replenishment components.

Loading States:
1. Initial page load: Skeleton screens for each card/table
2. Data refresh: Subtle spinner in header, don't block the UI
3. Generating needs list: Full-page overlay with progress: "Calculating gaps... Analyzing Horizon A... etc."
4. Submit for approval: Button loading state with spinner

Error States:
1. Network error: Toast notification + retry button
2. Validation error: Inline field errors, scroll to first error
3. Server error: Modal with error details + "Report Issue" button
4. Partial failure: "3 of 5 items saved. Retry failed items?"

Empty States:
1. No items at risk: "✓ All items have healthy stock levels" with illustration
2. No needs lists: "No needs lists yet. Generate one when stock is low."
3. No search results: "No items match your filters. [Clear Filters]"

Make sure loading states don't cause layout shift.
```

---

### 10. Accessibility Improvements

**Prompt:**
```
Audit my Supply Replenishment components for accessibility.

Check and fix:
1. All interactive elements have focus indicators
2. Color is not the only indicator of status (add icons/text)
3. Screen reader support: aria-labels on icon-only buttons
4. Keyboard navigation: Can complete all workflows without mouse
5. Contrast ratios meet WCAG AA (especially for status colors)
6. Form fields have associated labels
7. Tables have proper headers and scope attributes
8. Modals trap focus and can be closed with Escape key

Pay special attention to the status colors - Kemar might be viewing this in bright sunlight in the field.
```

---

## 🔄 Backend Integration Prompts

### API Data Shaping

```
Review the API response from /api/replenishment/stock-status/ and help me transform it for the UI.

Current response:
{
  "items": [
    {"item_id": 1, "name": "Bottled Water", "warehouse_id": 1, "available": 500, ...}
  ]
}

I need to:
1. Group by warehouse for the dashboard view
2. Calculate derived fields (time_to_stockout, severity_level, recommended_action)
3. Sort by urgency
4. Cache with a TTL matching the data freshness threshold

Create an Angular service method that handles this transformation.
```

### Form Validation

```
Create validation for the Needs List adjustment form:

Fields:
- adjusted_quantity: number, required, must be > 0, cannot exceed 2x recommended
- adjustment_reason: enum, required when quantity differs from recommended
- notes: string, optional, max 500 chars

Show validation errors inline and prevent submission until valid.
Add a confirmation dialog if adjustment is >50% different from recommendation.
```

---

## 🧪 Testing Prompts

### Component Tests

```
Write unit tests for the TimeToStockoutComponent:

Test cases:
1. Displays "4h 30m" for 4.5 hours
2. Shows CRITICAL styling when < 8 hours
3. Shows WARNING styling when 8-24 hours
4. Shows "∞ - No current demand" when burn rate is 0
5. Shows truck icon when < 8 hours (Horizon A)
6. Shows cart icon when > 72 hours (Horizon C)
7. Handles null/undefined values gracefully
```

### E2E Tests

```
Write a Cypress E2E test for the needs list generation workflow:

1. Navigate to Supply Replenishment dashboard
2. Verify at least one item shows CRITICAL status
3. Click "Generate Needs List"
4. Complete Step 1 (confirm scope)
5. Verify Step 2 shows calculated gaps
6. Adjust one quantity and select a reason
7. Submit for approval
8. Verify redirect to needs list detail with PENDING status
9. Verify audit trail shows creation event
```

---

## 🐛 Debugging Prompts

### When Things Don't Work

```
The burn rate calculation is showing incorrect values. Help me debug:

Expected: 50 units/hr (300 units / 6 hours)
Actual: 100 units/hr

Check:
1. What demand window is being used? (Should be 6hrs for SURGE)
2. Are rejected fulfillments being excluded?
3. Is the timestamp filter correct for the window?
4. Are we summing fulfilled_qty correctly?

Show me how to add logging to trace the calculation.
```

### Performance Issues

```
The stock status dashboard is slow to load (>3 seconds).

Help me:
1. Profile the Angular component to find bottlenecks
2. Check if we're making too many API calls
3. Implement virtual scrolling if the list is long
4. Add caching for data that doesn't change frequently
5. Consider pagination vs. loading all data

Show me before/after performance metrics.
```

---

## 📐 Design System Consistency

### Shared Components to Create

```
Create these reusable components for DMIS that we'll use across all modules:

1. DmisStatusChip - status indicator with icon and color
2. DmisDataFreshnessIndicator - shows sync time with color coding
3. DmisApprovalStepper - workflow status visualization  
4. DmisFilterPanel - collapsible filters with chips
5. DmisAlertBanner - persistent warning/error banners
6. DmisKpiCard - dashboard metric display
7. DmisDataTable - sortable, filterable table with export

For each component, use Angular Material as the base and add DMIS-specific styling.
Document the API (inputs/outputs) for each component.
```

---

## 🚀 Quick Wins to Start With

If you're overwhelmed, start with these high-impact improvements:

1. **Add loading skeletons** - Instant perceived performance boost
2. **Fix the data freshness indicator** - Critical for trust
3. **Improve Time-to-Stockout display** - Makes urgency clear
4. **Add mobile FAB for "Generate Needs List"** - Key action accessible
5. **Sort by urgency by default** - Most important items first

---

## 📝 Session Checklist

Before ending a Claude Code session:

- [ ] All changes follow Angular best practices
- [ ] Components are properly typed with TypeScript
- [ ] Error states are handled
- [ ] Loading states are smooth
- [ ] Mobile breakpoints are tested
- [ ] Accessibility basics are met
- [ ] Code is documented with JSDoc comments
- [ ] Git commit with descriptive message

---

## Example Full Session Flow

```
1. Start session with project context (see above)

2. "Show me the current stock-overview component"

3. "Let's improve the visual hierarchy. First, add severity-based styling..."

4. "Now add the data freshness indicator to the top..."

5. "Let's make this mobile-responsive..."

6. "Add unit tests for the new severity logic..."

7. "Commit these changes with message: 'feat(replenishment): improve dashboard visual hierarchy and mobile UX'"
```

---

## Need Help?

If Claude Code gets stuck:

1. **Provide more context**: Share the current component code
2. **Break it down**: Ask for one small change at a time
3. **Show examples**: Share a screenshot or mockup of what you want
4. **Check the console**: Share any error messages
5. **Reset context**: Start a fresh chat if it's going off track

Good luck refining EP-02! Once this is polished, it becomes the template for all other DMIS modules.
