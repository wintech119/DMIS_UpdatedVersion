# DMIS Supply Replenishment Module - Technical Reference Guide

> Complete technical reference for the EP-02 Supply Replenishment module.
> Covers backend API, frontend architecture, workflow state machine, RBAC, and business rules.

---

## 1. Project Overview

**System**: DMIS (Disaster Management Information System) for Jamaica's ODPEM
**Module**: EP-02 Supply Replenishment / Needs List Generation

**Tech Stack**:
- Frontend: Angular 21+, Angular Material, TypeScript, standalone components
- Backend: Django 6.0, Django REST Framework
- Database: PostgreSQL 16+ (with SQLite dev fallback)
- Auth: Keycloak OIDC (with dev-mode bypass)

**Primary Users**:
- **Kemar** (Logistics Manager) - Creates, edits, and submits needs lists
- **Andrea** (Senior Director / Executive) - Reviews and approves needs lists

---

## 2. Business Logic & Formulas

### Event Phases

| Phase        | Demand Window | Planning Window |
|--------------|---------------|-----------------|
| SURGE        | 6 hours       | 72 hours (3d)   |
| STABILIZED   | 72 hours (3d) | 168 hours (7d)  |
| BASELINE     | 720 hours (30d)| 720 hours (30d) |

### Core Formulas

```
Burn Rate       = Fulfilled Qty / Demand Window (hours)  → units/hour
Time-to-Stockout = Available Stock / Burn Rate            → hours
Required Qty    = Burn Rate × Planning Window × 1.25 (safety factor)
Gap             = Required Qty - (Available Stock + Confirmed Inbound)
```

### Severity Levels (Time-to-Stockout)

| Level    | Threshold    | Color   | Hex       |
|----------|-------------|---------|-----------|
| CRITICAL | < 8 hours   | Red     | `#dc3545` |
| WARNING  | 8-24 hours  | Amber   | `#fd7e14` |
| WATCH    | 24-72 hours | Yellow  | `#ffc107` |
| OK       | > 72 hours  | Green   | `#28a745` |

### Data Freshness

| Level  | Threshold      | Color |
|--------|---------------|-------|
| HIGH   | < 2 hours old | Green |
| MEDIUM | 2-6 hours old | Amber |
| LOW    | > 6 hours old | Red   |

### Three Horizons

| Horizon | Source       | Lead Time   | Color   | Icon            |
|---------|-------------|-------------|---------|-----------------|
| A       | Transfers   | 6-8 hours   | Green   | `swap_horiz`    |
| B       | Donations   | 2-7 days    | Orange  | `card_giftcard` |
| C       | Procurement | 14+ days    | Blue    | `shopping_cart`  |

---

## 3. Backend Architecture

### 3.1 API Endpoints

All endpoints are prefixed with `/api/v1/replenishment/`.

#### Reference Data

| Method | Path             | View                 | Permission         | Description                    |
|--------|------------------|----------------------|--------------------|--------------------------------|
| GET    | `active-event`   | `get_active_event`   | `preview`          | Get current active event       |
| GET    | `warehouses`     | `get_all_warehouses` | `preview`          | List all active warehouses     |

#### Needs List Preview (Read-Only Computation)

| Method | Path                    | View                      | Permission | Description                          |
|--------|-------------------------|---------------------------|------------|--------------------------------------|
| POST   | `needs-list/preview`    | `needs_list_preview`      | `preview`  | Compute gaps for single warehouse    |
| POST   | `needs-list/preview-multi` | `needs_list_preview_multi` | `preview` | Compute gaps for multiple warehouses |

#### Needs List Workflow (State-Changing)

| Method | Path                                        | View                        | Permission        | From Status      | To Status       |
|--------|---------------------------------------------|-----------------------------|-------------------|------------------|-----------------|
| GET    | `needs-list/`                               | `needs_list_list`           | `preview`         | -                | -               |
| POST   | `needs-list/draft`                          | `needs_list_draft`          | `create_draft`    | -                | DRAFT           |
| GET    | `needs-list/<id>`                           | `needs_list_get`            | any workflow perm | -                | -               |
| PATCH  | `needs-list/<id>/lines`                     | `needs_list_edit_lines`     | `edit_lines`      | DRAFT            | DRAFT           |
| POST   | `needs-list/<id>/submit`                    | `needs_list_submit`         | `submit`          | DRAFT            | SUBMITTED       |
| POST   | `needs-list/<id>/review/start`              | `needs_list_review_start`   | `review_start`    | SUBMITTED        | UNDER_REVIEW    |
| PATCH  | `needs-list/<id>/review-comments`           | `needs_list_review_comments`| `review_comments` | UNDER_REVIEW     | UNDER_REVIEW    |
| POST   | `needs-list/<id>/approve`                   | `needs_list_approve`        | `approve`         | UNDER_REVIEW     | APPROVED        |
| POST   | `needs-list/<id>/reject`                    | `needs_list_reject`         | `reject`          | UNDER_REVIEW     | REJECTED        |
| POST   | `needs-list/<id>/return`                    | `needs_list_return`         | `return`          | UNDER_REVIEW     | DRAFT           |
| POST   | `needs-list/<id>/escalate`                  | `needs_list_escalate`       | `escalate`        | UNDER_REVIEW     | ESCALATED       |
| POST   | `needs-list/<id>/start-preparation`         | `needs_list_start_preparation` | `execute`      | APPROVED         | IN_PREPARATION  |
| POST   | `needs-list/<id>/mark-dispatched`           | `needs_list_mark_dispatched`| `execute`         | IN_PREPARATION   | DISPATCHED      |
| POST   | `needs-list/<id>/mark-received`             | `needs_list_mark_received`  | `execute`         | DISPATCHED       | RECEIVED        |
| POST   | `needs-list/<id>/mark-completed`            | `needs_list_mark_completed` | `execute`         | RECEIVED         | COMPLETED       |
| POST   | `needs-list/<id>/cancel`                    | `needs_list_cancel`         | `cancel`          | APPROVED/IN_PREP | CANCELLED       |

#### Auth

| Method | Path                  | Description                      |
|--------|-----------------------|----------------------------------|
| GET    | `/api/v1/auth/whoami/`| Returns user ID, roles, permissions |

### 3.2 Workflow State Machine

```
DRAFT ──submit──> SUBMITTED ──start_review──> UNDER_REVIEW
                                                   │
                              ┌─────────────────────┼─────────────────────┐
                              │                     │                     │
                           approve              reject/return          escalate
                              │                     │                     │
                              v                     v                     v
                          APPROVED             REJECTED/DRAFT        ESCALATED
                              │
                       start_preparation
                              │
                              v
                       IN_PREPARATION ──cancel──> CANCELLED
                              │
                        mark_dispatched
                              │
                              v
                         DISPATCHED
                              │
                        mark_received
                              │
                              v
                          RECEIVED
                              │
                        mark_completed
                              │
                              v
                         COMPLETED
```

**Key rules**:
- `review/start` enforces that the reviewer must be a **different user** than the submitter
- `approve` enforces that the approver must be a **different user** than the submitter
- `approve` checks the user's role against the required approval tier role
- `return` transitions back to DRAFT (not a separate RETURNED status)
- `cancel` requires a reason and is only allowed from APPROVED or IN_PREPARATION
- All state transitions are audit-logged with user, timestamp, and reason

### 3.3 Data Storage

**Dev mode**: JSON file store at `backend/.local/needs_list_store.json`
- Controlled by `NEEDS_WORKFLOW_DEV_STORE=1` env var (set in `manage.py`)
- Thread-safe with `threading.Lock`

**Production**: PostgreSQL with Django models (`NeedsList`, `NeedsListItem`, `BurnRateSnapshot`)

### 3.4 RBAC Permissions

All permissions are prefixed with `replenishment.needs_list.`:

| Permission        | LOGISTICS Role | EXECUTIVE Role | Description                    |
|-------------------|:-:|:-:|----------------------------------------------|
| `preview`         | x | x | View stock status and preview gap calculations |
| `create_draft`    | x |   | Create a draft needs list from preview         |
| `edit_lines`      | x |   | Adjust quantities on draft items               |
| `submit`          | x |   | Submit draft for approval                      |
| `review_start`    |   | x | Start reviewing a submitted needs list         |
| `review_comments` |   | x | Add review comments on items                   |
| `approve`         |   | x | Approve a needs list under review              |
| `reject`          |   | x | Reject a needs list under review               |
| `return`          |   | x | Return a needs list to draft for revision      |
| `escalate`        |   | x | Escalate a needs list to higher authority      |
| `execute`         | x |   | Start preparation, dispatch, receive, complete |
| `cancel`          | x | x | Cancel an approved or in-preparation list      |

### 3.5 Procurement Approval Tiers

Based on the Public Procurement Act 2015 (Jamaica):

| Max Cost (JMD) | Tier           | Approver (Baseline)       | Approver (Surge)          |
|----------------|----------------|---------------------------|---------------------------|
| 3,000,000      | Below Tier 1   | Logistics Manager (Kemar) | Logistics Manager (Kemar) |
| 15,000,000     | Below Tier 1   | Senior Director (Andrea)  | Logistics Manager (Kemar) |
| 40,000,000     | Below Tier 1   | Director General (Marcus) | Senior Director (Andrea)  |
| 60,000,000     | Tier 1         | Director General (Marcus) | Director General (Marcus) |
| 100,000,000    | Tier 2         | DG + PPC Endorsement      | DG + PPC Endorsement      |
| > 100,000,000  | Tier 3         | DG + PPC + Cabinet        | DG + PPC + Cabinet        |

**Special case**: When `selected_method = "A"` (Transfer), approval bypasses procurement tier logic; Logistics Manager is the approver.

### 3.6 Key Backend Files

| File | Purpose |
|------|---------|
| `backend/replenishment/views.py` | All API view functions |
| `backend/replenishment/urls.py` | URL routing |
| `backend/replenishment/workflow_store.py` | JSON-file workflow state management (dev) |
| `backend/replenishment/workflow_store_db.py` | PostgreSQL workflow state management (prod) |
| `backend/replenishment/rules.py` | Phase windows, severity, approval tier rules |
| `backend/replenishment/services/approval.py` | Approval tier computation, Appendix C authority |
| `backend/replenishment/services/data_access.py` | Database queries for stock, burn rates, inbound |
| `backend/replenishment/services/needs_list.py` | Build preview items, merge warnings |
| `backend/replenishment/models.py` | Django ORM models |
| `backend/dmis_api/settings.py` | All NEEDS_*, AUTH_*, DEV_AUTH_* settings |
| `backend/api/rbac.py` | Permission constants, role resolution |
| `backend/api/authentication.py` | Keycloak OIDC / dev-mode auth |

---

## 4. Frontend Architecture

### 4.1 Routes

| Path | Component | Description |
|------|-----------|-------------|
| `/replenishment/dashboard` | `StockStatusDashboardComponent` | Main stock overview dashboard |
| `/replenishment/needs-list-wizard` | `NeedsListWizardComponent` | 3-step wizard (Scope/Preview/Submit) |
| `/replenishment/needs-list-review` | `NeedsListReviewQueueComponent` | Approval queue for reviewers |
| `/replenishment/needs-list-review/:id` | `NeedsListReviewDetailComponent` | Detailed review/approve/reject page |

### 4.2 Components

All components use **standalone** architecture and **OnPush** change detection.

#### Major Components

| Component | Location | Description |
|-----------|----------|-------------|
| `StockStatusDashboardComponent` | `stock-status-dashboard/` | Main dashboard with stock table, severity indicators, warehouse cards |
| `NeedsListWizardComponent` | `needs-list-wizard/` | Container with Material Stepper for 3-step wizard |
| `ScopeStepComponent` | `needs-list-wizard/steps/step1-scope/` | Step 1: Select event, warehouses, phase |
| `PreviewStepComponent` | `needs-list-wizard/steps/step2-preview/` | Step 2: View computed items, adjust quantities, filter/select |
| `SubmitStepComponent` | `needs-list-wizard/steps/step3-submit/` | Step 3: Summary card, approval path, submit |
| `NeedsListReviewQueueComponent` | `needs-list-review/` | Table/card list of SUBMITTED + UNDER_REVIEW needs lists |
| `NeedsListReviewDetailComponent` | `needs-list-review/` | Full detail view with approval actions |

#### Shared Components

| Component | Location | Description |
|-----------|----------|-------------|
| `DmisApprovalStatusTrackerComponent` | `shared/dmis-approval-status-tracker/` | Visual workflow status stepper |
| `DmisDataFreshnessBannerComponent` | `shared/dmis-data-freshness-banner/` | Sticky banner for stale data warnings |
| `DmisSkeletonLoaderComponent` | `shared/dmis-skeleton-loader/` | Skeleton loading placeholders |
| `DmisEmptyStateComponent` | `shared/dmis-empty-state/` | Empty state with icon and action button |
| `DmisConfirmDialogComponent` | `shared/dmis-confirm-dialog/` | Generic confirmation dialog |
| `DmisErrorDialogComponent` | `shared/dmis-error-dialog/` | Error display dialog |
| `DmisReasonDialogComponent` | `shared/dmis-reason-dialog/` | Dialog for return/escalate with required reason |
| `RejectReasonDialogComponent` | `shared/reject-reason-dialog/` | Dialog for rejection with required reason |
| `PhaseSelectDialogComponent` | `phase-select-dialog/` | Phase selection for dashboard |
| `TimeToStockoutComponent` | `time-to-stockout/` | Countdown-style time display with severity coloring |

### 4.3 Services

| Service | File | Description |
|---------|------|-------------|
| `ReplenishmentService` | `services/replenishment.service.ts` | All API calls (preview, draft, submit, review, approve, etc.) |
| `DashboardDataService` | `services/dashboard-data.service.ts` | Dashboard data loading and caching |
| `DataFreshnessService` | `services/data-freshness.service.ts` | Data freshness computation |
| `DmisNotificationService` | `services/notification.service.ts` | Toast notifications (success, error, warning, info) |
| `WizardStateService` | `needs-list-wizard/services/wizard-state.service.ts` | Wizard step state management |

### 4.4 Models

| File | Key Types |
|------|-----------|
| `models/stock-status.model.ts` | `EventPhase`, `SeverityLevel`, `FreshnessLevel`, `StockStatusItem`, `StockStatusResponse`, `calculateSeverity()`, `formatTimeToStockout()` |
| `models/needs-list.model.ts` | `NeedsListItem`, `NeedsListResponse`, `NeedsListStatus`, `ApprovalSummary`, `HorizonAllocation`, `TrackerStep`, `TrackerBranch` |
| `models/approval-workflows.model.ts` | `HorizonType`, `ApprovalWorkflowConfig`, `APPROVAL_WORKFLOWS` |

### 4.5 NeedsListStatus Enum

```typescript
type NeedsListStatus =
  | 'DRAFT'
  | 'SUBMITTED'
  | 'UNDER_REVIEW'
  | 'APPROVED'
  | 'REJECTED'
  | 'RETURNED'
  | 'IN_PROGRESS'
  | 'FULFILLED'
  | 'CANCELLED'
  | 'SUPERSEDED';
```

---

## 5. User Workflows

### 5.1 Logistics Manager (Kemar) - Create & Submit Needs List

1. **Dashboard** (`/replenishment/dashboard`):
   - View stock status across warehouses
   - See severity indicators (CRITICAL items at top)
   - Click "Generate Needs List" button

2. **Wizard Step 1 - Scope** (`/replenishment/needs-list-wizard`):
   - Event auto-loaded from active event
   - Select warehouses (multi-select with checkboxes)
   - Phase auto-detected from event, can override
   - Click "Calculate Gaps"

3. **Wizard Step 2 - Preview**:
   - View computed items table (all warehouses aggregated)
   - Columns: Item, Warehouse, Available, Inbound, Burn Rate, Required, Gap, Severity, Horizon A/B/C
   - Adjust quantities (click to edit, requires reason from dropdown)
   - Bulk select/deselect items
   - Filter by severity, warehouse, search text
   - Select replenishment method (A/B/C)
   - Click "Continue to Summary"

4. **Wizard Step 3 - Submit**:
   - Summary card with totals (items, qty, estimated cost)
   - Approval path display (tier, approver role)
   - Warnings shown as amber chips
   - Save as Draft or Submit for Approval
   - On submit: draft is created then immediately submitted (DRAFT → SUBMITTED)

### 5.2 Executive (Andrea) - Review & Approve Needs List

1. **Dashboard** → Click "Review Queue" button (visible to EXECUTIVE role)

2. **Review Queue** (`/replenishment/needs-list-review`):
   - Table of needs lists with status SUBMITTED or UNDER_REVIEW
   - Sorted by submitted_at ascending (oldest/most urgent first)
   - Columns: ID, Event, Phase, Warehouse(s), Submitted By, Items, Status
   - Click row to open detail

3. **Review Detail** (`/replenishment/needs-list-review/:id`):
   - Header with needs list ID, status badge, event name, phase, warehouses
   - Approval Status Tracker showing workflow progress
   - Approval Summary card (purple gradient) with totals, tier, warnings
   - Items table with all item details and severity chips
   - Per-item review comment inputs (when UNDER_REVIEW)

4. **Actions** (sticky bottom bar, permission-based):
   - **Start Review** (when SUBMITTED + has `review_start` permission)
   - **Approve** (when UNDER_REVIEW + has `approve` permission)
   - **Reject** (when UNDER_REVIEW + has `reject` permission → opens reason dialog)
   - **Return for Revision** (when UNDER_REVIEW + has `return` permission → opens reason dialog)
   - **Escalate** (when UNDER_REVIEW + has `escalate` permission → opens reason dialog)

### 5.3 Fulfillment Flow (Post-Approval)

After approval, the needs list moves through:

```
APPROVED → IN_PREPARATION → DISPATCHED → RECEIVED → COMPLETED
```

Each transition requires `execute` permission and is logged with actor + timestamp.
Cancellation (with reason) is possible from APPROVED or IN_PREPARATION states.

---

## 6. Design System

### 6.1 Color Palette

```scss
// Primary gradient (approval cards, wizard summary)
background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);

// Accent/hover color
$accent: #667eea;

// Severity colors
$critical: #dc3545;    $critical-bg: #fce4ec;
$warning:  #fd7e14;    $warning-bg:  #fff8e1;
$watch:    #ffc107;    $watch-bg:    #fffde7;
$ok:       #28a745;    $ok-bg:       #e8f5e9;

// Status chip colors
$submitted:    #1565c0 on #e3f2fd;
$under-review: #f57f17 on #fff8e1;
$approved:     #2e7d32 on #e8f5e9;
$rejected:     #c62828 on #fce4ec;
$returned:     #e65100 on #fff3e0;
$escalated:    #7b1fa2 on #f3e5f5;

// Phase chip colors
$surge:      #c62828 on #fce4ec;
$stabilized: #f57f17 on #fff8e1;
$baseline:   #2e7d32 on #e8f5e9;

// Horizon colors
$horizon-a: #4caf50 (green - transfers)
$horizon-b: #ff9800 (orange - donations)
$horizon-c: #2196f3 (blue - procurement)
```

### 6.2 Layout Patterns

- **Max width**: 1400px, centered with `margin: 0 auto`
- **Cards**: White background, `border-radius: 8px`, `box-shadow: 0 2px 4px rgba(0,0,0,0.1)`
- **Glassmorphism** (on purple cards): `background: rgba(255,255,255,0.1)`, `backdrop-filter: blur(10px)`
- **Sticky action bar**: `position: sticky; bottom: 0; box-shadow: 0 -4px 12px rgba(0,0,0,0.1)`
- **Tables**: `table-layout: fixed`, header `background: #f5f5f5`, hover `rgba(102,126,234,0.04)`

### 6.3 Responsive Breakpoints

| Breakpoint | Behavior |
|------------|----------|
| > 968px    | Full layout (summary grid: 2 columns) |
| 768-968px  | Summary grid collapses to 1 column |
| < 768px    | Tables become card lists, action bar becomes fixed full-width |
| < 480px    | Reduced padding, smaller fonts |

### 6.4 Accessibility

- Status colors always have **text labels and/or icons** as backup
- Severity chips include `data-severity` attributes for styling
- Touch targets minimum 48px on mobile
- `focus-visible` outlines on interactive elements
- `aria-label` on icon-only buttons

---

## 7. Key Configuration (Environment Variables)

### Backend Settings (`dmis_api/settings.py`)

| Variable | Default | Description |
|----------|---------|-------------|
| `NEEDS_WORKFLOW_DEV_STORE` | `1` (via manage.py) | Enable JSON file workflow store |
| `NEEDS_SAFETY_FACTOR` | `1.25` | Safety stock multiplier |
| `NEEDS_HORIZON_A_DAYS` | `7` | Horizon A planning window |
| `NEEDS_BURN_SOURCE` | `reliefpkg` | Primary burn rate data source |
| `NEEDS_BURN_FALLBACK` | `reliefrqst` | Fallback burn rate source |
| `DEV_AUTH_ENABLED` | `0` | Enable dev-mode authentication bypass |
| `DEV_AUTH_USER_ID` | `dev-user` | Dev mode user ID |
| `DEV_AUTH_ROLES` | `` | Comma-separated roles for dev user |
| `DEV_AUTH_PERMISSIONS` | See settings.py | Comma-separated permissions for dev user |
| `AUTH_ENABLED` | `0` | Enable Keycloak OIDC auth |
| `DJANGO_USE_SQLITE` | `0` | Use SQLite instead of PostgreSQL |

---

## 8. Development Commands

**Important:** The frontend proxy sends `/api` to `http://localhost:8001`. The Django server **must** run on port **8001** or you will see `ECONNREFUSED` proxy errors.

```bash
# Backend (must use port 8001 to match frontend proxy)
cd backend
python manage.py runserver 0.0.0.0:8001     # Django dev server
python manage.py test replenishment         # Run backend tests

# Frontend
cd frontend
ng serve                                    # Angular dev server (port 4200), proxies /api -> :8001
ng build                                    # Production build
ng test --watch=false                       # Run unit tests

# Run both in one go (PowerShell, from repo root)
.\scripts\run_new_stack.ps1                 # Opens Django window (:8001) + Angular window (:4200)

# API testing (examples)
curl http://localhost:8001/api/v1/replenishment/active-event
curl http://localhost:8001/api/v1/replenishment/warehouses
curl "http://localhost:8001/api/v1/replenishment/needs-list/?status=SUBMITTED,UNDER_REVIEW"
curl http://localhost:8001/api/v1/replenishment/needs-list/<uuid>
```

### Troubleshooting: `[vite] http proxy error: ... ECONNREFUSED`

This means the Angular app cannot reach the backend. **Start the Django server** in a separate terminal (see below).

### Troubleshooting: `password authentication failed for user "postgres"`

Django is trying to use PostgreSQL but the password is wrong or not set. For **local development without PostgreSQL**, use SQLite:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1   # if you use a venv
$env:DJANGO_USE_SQLITE = "1"
$env:DJANGO_DEBUG = "1"
$env:DEV_AUTH_ENABLED = "1"
python manage.py migrate --noinput   # create SQLite DB and tables (first time only)
python manage.py runserver 0.0.0.0:8001
```

To use **PostgreSQL**, set credentials in `backend\.env` (copy from `backend\.env.example`). Default local values:

- `DB_NAME=dmis`
- `DB_USER=postgres`
- `DB_PASSWORD=<your password>` (use quotes if it contains special characters, e.g. `DB_PASSWORD="Excellence!00"`)
- `DB_HOST=localhost`
- `DB_PORT=5432`

Do **not** set `DJANGO_USE_SQLITE`, or set it to `0`. `run_new_stack.ps1` loads `backend\.env` automatically.

---

## 9. Non-Negotiable Requirements

1. **No auto-actions**: System recommends, humans approve
2. **Audit everything**: All state changes logged with user, timestamp, reason
3. **Data freshness visible**: User must know when data is stale
4. **Strict inbound**: Only count DISPATCHED transfers, IN-TRANSIT donations, SHIPPED procurement
5. **Mobile-friendly**: Kemar works in the field during hurricane response
6. **Separation of duties**: Submitter cannot be the reviewer/approver
7. **Loading states**: Skeleton loaders, never spinners
8. **Error handling**: Toast notifications with retry, never fail silently

---

*Last updated: February 2026*
