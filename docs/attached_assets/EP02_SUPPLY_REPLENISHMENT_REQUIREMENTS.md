# EP-02: Supply Replenishment Module - Complete Requirements

> This file contains all requirements, formulas, acceptance criteria, and edge cases for the Supply Replenishment module. Place in your project's `/docs` folder for Claude Code reference.

---

## 1. Module Purpose

Convert low-stock signals and demand patterns into approved, actionable needs lists that prevent stockouts during disaster response.

**Product Outcome (PO-02):** Prevent stockouts via low-stock triggers and approved needs list

**Primary KPI:** Critical stockout duration: 0-4 hours maximum

---

## 2. Primary User: Kemar (Logistics Manager)

### Profile
- **Role:** Logistics Manager at ODPEM
- **Tenure:** New to ODPEM; experienced logistics manager
- **Predisposition:** Supportive (change champion)
- **Working Context:** Frequently in the field doing post-relief work; needs remote visibility

### Characteristics
- Hands-on; field-oriented; pragmatic; detail-conscious
- Works well under pressure; communicates clearly and directly
- Low tolerance for messy data; sees spreadsheets/legacy tools as root causes of poor decisions

### Key Beliefs
- "If it's not logged, it didn't happen"
- Bias for speed AND accuracy
- Field-first mindset: expects mobile-friendly workflows and near real-time visibility

### Goals
- Improve inventory accuracy and movement traceability
- Generate reliable, evidence-based restocking recommendations
- Enable proactive resupply before stockouts occur

### Needs
- Fast data entry with controls that prevent errors
- Mobile access to dashboards and approval workflows
- Clear audit trail for all decisions and overrides

### Obstacles
- Data latency from field sync issues
- Legacy systems that don't talk to each other
- Training gaps and staff rotation affecting consistency

---

## 3. Event Phase Parameters

| Phase | Demand Window | Planning Window | Safety Buffer | Description |
|-------|---------------|-----------------|---------------|-------------|
| **SURGE** | 6 hours | 72 hours | 50% | First 72 hours after disaster strike |
| **STABILIZED** | 72 hours | 7 days | 25% | Post-surge, active response ongoing |
| **BASELINE** | 30 days | 30 days | 10% | Normal operations or recovery |

### Lead Times (Default)
| Horizon | Source | Lead Time | When to Use |
|---------|--------|-----------|-------------|
| A | Transfers | 6-8 hours | First option; fastest |
| B | Donations | 2-7 days (72 hrs default) | When transfers can't cover gap |
| C | Procurement | 14+ days (336 hrs default) | Last resort; longest lead time |

---

## 4. Core Formulas

### 4.1 Burn Rate Calculation
```
Burn Rate = Total Fulfilled Quantity / Demand Window (hours)
```

**Rules:**
- Only include **validated/completed** fulfillments
- Exclude REJECTED and CANCELLED requests
- Use fulfillments within the current event phase's demand window
- Unit: units/hour

**Example (SURGE Phase):**
```
Demand Window = 6 hours
Fulfillments in last 6 hours: 300 units (3 requests × 100 units each)
Burn Rate = 300 / 6 = 50 units/hour
```

### 4.2 Time-to-Stockout
```
Time-to-Stockout = Available Stock / Burn Rate
```

**Rules:**
- If Burn Rate = 0 and data is fresh: Display "∞ - No current demand"
- If Burn Rate = 0 and data is stale: Use baseline rate, show warning
- Unit: hours

**Example:**
```
Available Stock = 200 units
Burn Rate = 50 units/hour
Time-to-Stockout = 200 / 50 = 4 hours
```

### 4.3 Required Quantity
```
Required Quantity = Burn Rate × Planning Window (hours) × Safety Factor
```

**Safety Factor:** 1.25 (25% buffer) — configurable

**Example (SURGE):**
```
Burn Rate = 50 units/hour
Planning Window = 72 hours
Safety Factor = 1.25
Required Quantity = 50 × 72 × 1.25 = 4,500 units
```

### 4.4 Gap Calculation
```
Gap = Required Quantity - (Available Stock + Confirmed Inbound)
```

**Rules:**
- If Gap > 0: Generate Draft Needs List entry
- If Gap ≤ 0: No needs list entry; show "Sufficient Coverage" on dashboard

**Confirmed Inbound (Strict Definition):**
- Transfers with status = DISPATCHED
- Donations with status = CONFIRMED and IN-TRANSIT
- Procurement with status = SHIPPED

**NOT included in inbound:**
- Pledged donations (not confirmed)
- Procurement that's APPROVED but not SHIPPED
- Transfers that are REQUESTED but not DISPATCHED

**Example:**
```
Required Quantity = 4,500 units
Available Stock = 500 units
Confirmed Inbound:
  - Transfer (DISPATCHED): 200 units
  - Donation (IN-TRANSIT): 300 units
Total Coverage = 500 + 200 + 300 = 1,000 units
Gap = 4,500 - 1,000 = 3,500 units → Generate Needs List
```

---

## 5. Three Horizons Logic

When a gap exists, the system recommends replenishment sources in waterfall order:

### Horizon A: Transfers (Hours)
1. Search other warehouses for **surplus** (Available - Minimum Threshold)
2. Only recommend transfer if source warehouse has surplus
3. Never deplete a warehouse below its safety stock
4. Create transfer request if surplus can cover part/all of gap

### Horizon B: Donations (Days)
1. Check expected donations in pipeline
2. Match against remaining gap (after Horizon A)
3. Generate donor request for unfilled portion

### Horizon C: Procurement (Weeks)
1. Calculate remaining gap after A and B
2. Generate procurement package
3. Route to Procurement Focal for processing

**Waterfall Example:**
```
Total Gap: 3,500 units

Horizon A (Transfers):
  - Kingston Hub has surplus: 800 units
  - Remaining gap: 3,500 - 800 = 2,700 units

Horizon B (Donations):
  - Expected donation arriving in 3 days: 1,000 units
  - Remaining gap: 2,700 - 1,000 = 1,700 units

Horizon C (Procurement):
  - Generate procurement request for 1,700 units
  - Estimated arrival: 14+ days
```

---

## 6. Data Freshness & Confidence

### Freshness Thresholds
| Level | Age | Color | Action |
|-------|-----|-------|--------|
| HIGH | < 2 hours | Green | Normal operations |
| MEDIUM | 2-6 hours | Amber | Show warning indicator |
| LOW | > 6 hours | Red | Show alert banner; use baseline rates |

### Dashboard Freshness Indicator
Every dashboard view must display:
- Overall confidence level (HIGH/MEDIUM/LOW) with color
- Per-warehouse last sync timestamp
- Count of warehouses in each freshness state
- Clickable link to drill down into sync details

### Warning Messages

**MEDIUM (2-6 hours stale):**
```
⚠ Warning: Data is [X] hours old. Calculations may not reflect current stock levels.
Last sync: [TIMESTAMP]
```

**LOW (>6 hours stale):**
```
⛔ STALE DATA ALERT: Inventory data for [WAREHOUSE_NAME] exceeds freshness threshold 
([X] hours since last sync). Burn rate calculations are using safe baseline rate. 
Verify stock levels before approving needs list. Last sync: [TIMESTAMP]
```

**Zero burn rate + stale data:**
```
ℹ Note: Calculated burn rate is zero but data is stale. System is using safe baseline 
rate of [X] units/hour for [ITEM_NAME] to prevent under-ordering. Verify actual demand 
before approval.
```

---

## 7. Status Severity Levels

| Level | Time-to-Stockout | Color | Icon | Recommended Action |
|-------|------------------|-------|------|-------------------|
| CRITICAL | < 8 hours | Red (#F44336) | 🚨 | Immediate transfer (Horizon A) |
| WARNING | 8-24 hours | Amber (#FF9800) | ⚠️ | Plan transfer or donation |
| WATCH | 24-72 hours | Yellow (#FFC107) | 👁️ | Monitor; prepare needs list |
| OK | > 72 hours | Green (#4CAF50) | ✓ | No action needed |

---

## 8. User Flow: Generate Needs List

| Step | Action | System Response |
|------|--------|-----------------|
| 1 | Logistics Manager navigates to Replenishment > Needs List | Display current event phase with parameters |
| 2 | System shows stock status dashboard | Burn rate, time-to-stockout, inbound, gap for each item |
| 3 | User clicks "Generate Draft Needs List" | System calculates gaps for all items |
| 4 | System applies Three Horizons logic | Allocate gaps to A (Transfers), B (Donations), C (Procurement) |
| 5 | Draft Needs List displayed | User can adjust quantities with mandatory reason |
| 6 | User clicks "Submit for Approval" | Status changes to PENDING_APPROVAL |
| 7 | Approver reviews and approves/rejects | If approved: status = APPROVED; if rejected: RETURNED with reason |
| 8 | Approved items trigger downstream actions | Transfer requests, donor notifications, procurement packages |

---

## 9. Needs List Statuses

```
[DRAFT] → [PENDING_APPROVAL] → [APPROVED] → [IN_PROGRESS] → [FULFILLED]
                ↓
         [RETURNED] (with reason)
                ↓
           [DRAFT] (revised)
```

| Status | Description | Who Can Act |
|--------|-------------|-------------|
| DRAFT | Initial calculation, not yet submitted | Logistics Manager |
| PENDING_APPROVAL | Awaiting approver review | Senior Director (SURGE) or Logistics Manager (BASELINE) |
| RETURNED | Sent back for revision with reason | Logistics Manager |
| APPROVED | Ready for execution | System auto-triggers actions |
| IN_PROGRESS | Transfers/procurement initiated | Logistics Manager monitors |
| FULFILLED | All items received | System auto-closes |
| SUPERSEDED | Replaced by newer calculation | N/A (historical) |

---

## 10. Approval Thresholds

### By Event Phase
| Phase | Approver | Notes |
|-------|----------|-------|
| SURGE | Senior Director (Andrea) | Higher authority during emergency |
| STABILIZED | Senior Director (Andrea) | Transition period |
| BASELINE | Logistics Manager (Kemar) | Normal operations |

### By Value (Procurement - Horizon C)
| Value Range (JMD) | Approver | Methods |
|-------------------|----------|---------|
| ≤ J$3,000,000 | Logistics Manager | Single-Source, RFQ |
| J$3M - J$15M | Senior Director | Restricted Bidding |
| > J$15M | Director General | Open Tender |

---

## 11. Acceptance Criteria

### AC01: Burn Rate Calculation (SURGE)
```
GIVEN the system is in SURGE phase with 6-hour demand window
AND Kingston Hub has 3 validated fulfillments totaling 300 units in the past 6 hours
WHEN burn rate calculation executes
THEN burn rate = 300 / 6 = 50 units/hour
```

### AC02: Zero Burn Rate with Fresh Data
```
GIVEN no validated fulfillments exist within the demand window
AND data freshness is HIGH (recent sync)
WHEN burn rate calculation executes
THEN burn rate displays "N/A – No current demand"
AND Time-to-Stockout is not calculated
```

### AC03: Zero Burn Rate with Stale Data
```
GIVEN no validated fulfillments exist within the demand window
AND data freshness is LOW (stale data)
WHEN burn rate calculation executes
THEN system uses BASELINE_BURN_RATE from item configuration
AND displays "[X] units/hr (baseline)" with warning icon
```

### AC04: Rejected Requests Excluded
```
GIVEN a relief request with status = REJECTED
WHEN burn rate calculation executes
THEN rejected request quantities are NOT included in burn rate SUM
```

### AC05: Positive Gap Calculation
```
GIVEN burn rate = 100 units/hr, planning window = 72 hours (SURGE)
AND available stock = 500 units, confirmed inbound = 200 units
WHEN gap analysis executes
THEN Required Qty = 100 × 72 × 1.25 = 9,000 units
AND Gap = 9,000 - 700 = 8,300 units
AND Draft Needs List line is generated
```

### AC06: Zero/Negative Gap
```
GIVEN Gap calculation results in Gap ≤ 0
WHEN gap analysis executes
THEN no needs list entry is created
AND dashboard displays "✓ Sufficient Coverage"
```

### AC07: Strict Inbound Definition
```
GIVEN a donation with status = PLEDGED (not CONFIRMED)
WHEN gap analysis calculates inbound
THEN pledged donation is NOT included in confirmed inbound
```

### AC08: Needs List Preview
```
GIVEN user clicks "Generate Draft Needs List"
WHEN Needs List Preview screen is displayed
THEN all lines show: Item, Warehouse, Recommended Qty, Horizon (A/B/C), Source, Lead Time, Expected Arrival, Status = DRAFT
```

### AC09: Superseding Previous Draft
```
GIVEN a Draft Needs List exists for a warehouse/item combination
AND a new calculation produces updated recommendations
WHEN the new calculation completes
THEN previous DRAFT is marked SUPERSEDED
AND new DRAFT is created with link to superseded record
```

### AC10: Manual Modification
```
GIVEN Logistics Manager views Needs List Preview
WHEN user modifies a quantity
THEN system requires selection of adjustment reason
AND logs modification to audit trail
```

### AC11: Data Freshness Warning
```
GIVEN warehouse data is older than freshness threshold
WHEN user attempts to submit needs list for approval
THEN system displays warning: "Data for [WAREHOUSE] is [X] hours old"
AND requires explicit acknowledgment before submission
```

---

## 12. Edge Cases

### EC-CALC-001: No Disbursement Data
**Trigger:** No validated fulfillments exist within the demand window
**Behavior:**
1. Check if this is due to stale data or genuinely no demand
2. If data is fresh: Display burn rate as 0 with "No current demand"
3. If data is stale: Use BASELINE_BURN_RATE, flag as "estimated" with LOW confidence
4. Show warning icon on dashboard

### EC-CALC-002: Negative Gap (Surplus)
**Trigger:** Gap calculation results in negative value (warehouse has more than needed)
**Behavior:**
1. Set Gap = 0 (no replenishment needed)
2. Calculate Surplus = Coverage - Required Qty
3. Mark warehouse as potential transfer SOURCE for other locations
4. Display "Surplus: [X] units available for transfer" on dashboard

### EC-CALC-003: Partial Horizon Coverage
**Trigger:** Horizon A can only partially fill gap
**Behavior:**
1. Create transfer recommendation for available surplus
2. Pass remaining gap to Horizon B
3. Display: "Transfer covers [X] of [Y] units needed. Remaining [Z] allocated to donations/procurement."

### EC-DATA-001: Warehouse Offline
**Trigger:** No data received from warehouse for > 6 hours
**Behavior:**
1. Display "⛔ WAREHOUSE OFFLINE" banner
2. Exclude warehouse from gap calculations
3. Alert Logistics Manager to investigate
4. Log incident for audit trail

### EC-APPROVAL-001: Approver Unavailable
**Trigger:** Needs list pending approval > 4 hours
**Behavior:**
1. Send reminder notification to approver
2. After 8 hours: Escalate to next level (Senior Director → Director General)
3. Log escalation in audit trail

---

## 13. Audit Requirements

Every action must be logged with:
- **What:** Action type (CREATE, UPDATE, APPROVE, REJECT, etc.)
- **Who:** User ID and role
- **When:** Timestamp (UTC)
- **Why:** Reason code or notes (required for adjustments/rejections)
- **Before/After:** Previous and new values for any changes

### Audit Events for Needs List
| Event | Required Fields |
|-------|-----------------|
| DRAFT_CREATED | items, quantities, calculations used |
| QUANTITY_ADJUSTED | item_id, old_qty, new_qty, reason_code, notes |
| SUBMITTED_FOR_APPROVAL | submitted_by, approver_role |
| APPROVED | approved_by, notes |
| REJECTED | rejected_by, reason_code, notes |
| SUPERSEDED | new_needs_list_id |

---

## 14. API Endpoints (Reference)

```
# Stock Status
GET  /api/replenishment/stock-status/
GET  /api/replenishment/stock-status/?warehouse_id={id}

# Burn Rates
GET  /api/replenishment/burn-rates/
GET  /api/replenishment/burn-rates/?item_id={id}&warehouse_id={id}

# Needs List
POST /api/replenishment/needs-list/generate/
GET  /api/replenishment/needs-list/
GET  /api/replenishment/needs-list/{id}/
PATCH /api/replenishment/needs-list/{id}/
POST /api/replenishment/needs-list/{id}/submit/
POST /api/replenishment/needs-list/{id}/approve/
POST /api/replenishment/needs-list/{id}/reject/

# Three Horizons
GET  /api/replenishment/horizons/{needs_list_id}/
POST /api/replenishment/horizons/{needs_list_id}/transfers/
POST /api/replenishment/horizons/{needs_list_id}/procurement/

# Data Freshness
GET  /api/replenishment/data-freshness/
POST /api/replenishment/sync/trigger/
```

---

## 15. Non-Negotiable Rules

1. **No automated actions:** System recommends; humans approve
2. **Strict inbound definition:** Only count physically confirmed stock
3. **Audit everything:** All changes logged with user, timestamp, reason
4. **Data freshness visible:** User must always know when data is stale
5. **Never deplete safety stock:** Transfers cannot reduce source below minimum threshold
6. **Separation of duties:** Creator cannot approve their own needs list

---

*Last Updated: February 2026*
*Version: 4.1*
*Source: DMIS Requirements Specification v4.0, Gap Updates v4.1, Appendices D-G*
