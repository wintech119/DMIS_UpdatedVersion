# DMIS Role-Based System Testing Guide

## Overview
This guide covers role-based validation for the DMIS Angular + Django platform.
For shared-dev, staging, and production validation, Angular routes under `/replenishment/*`, `/operations/*`, and `/master-data` are the only authoritative live user paths.
Legacy Flask dashboard routes such as `/dashboard/*`, `/executive/operations`, `/eligibility/*`, `/packaging/*`, `/reports/*`, and `/notifications/*` are retired and must not be used as release-readiness evidence.

For current replenishment approval rules and deferred tenant-config policy scope, see `docs/ops/replenishment-approval-policy-current-state.md`.

## Test Accounts

### Admin Account
- **Email:** `admin [at] odpem [dot] gov [dot] jm`
- **Password:** `admin123`
- **Roles:** System Administrator
- **Expected Access:** Full system access to all Angular + Django features

### Single-Role Test Accounts
All test accounts use password: `test123`

1. **Logistics Manager**
   - **Email:** `test.logistics@odpem.gov.jm`
   - **Role:** `LOGISTICS_MANAGER`
   - **Primary Areas:** replenishment, operations, operational master data

2. **Agency User**
   - **Email:** `test.agency@gmail.com`
   - **Role:** `AGENCY_SHELTER`
   - **Primary Areas:** relief request creation and tracking

3. **Director**
   - **Email:** `test.director@odpem.gov.jm`
   - **Role:** `ODPEM_DG`
   - **Primary Areas:** eligibility review and global oversight

4. **Inventory Clerk**
   - **Email:** `test.inventory@odpem.gov.jm`
   - **Role:** `INVENTORY_CLERK`
   - **Primary Areas:** operational inventory and warehouse workflows

## DMIS-09 Live-Path Validation Checklist

### 1. Authentication and Default Landing Route
**Steps:**
1. Log in as each test account.
2. If no `returnUrl` is provided, observe the post-login landing page.
3. Log out between role changes.

**Expected Results:**
- ✅ Default login landing route resolves to `/replenishment/dashboard`.
- ✅ Authorized deep links stay inside Angular routes such as `/operations/*`, `/replenishment/*`, and `/master-data`.
- ❌ No login flow or redirect lands on legacy Flask dashboard routes such as `/dashboard/logistics`, `/dashboard/agency`, `/dashboard/director`, `/dashboard/inventory`, or `/dashboard/admin`.

### 2. Navigation and Visible Route Validation
**Steps:**
1. Log in as each role.
2. Check the sidebar navigation items and click each visible link.
3. Cross-check unexpected visibility with `/api/v1/auth/whoami/` permissions.

**Expected Results:**
- ✅ Visible navigation items use internal Angular router targets only.
- ✅ Replenishment links stay under `/replenishment/*`.
- ✅ Operations links stay under `/operations/*`.
- ✅ Master Data links stay under `/master-data`.
- ✅ Disabled placeholders may appear, but they are not active links to legacy pages.
- ❌ No visible navigation item targets `/dashboard/*`, `/executive/operations`, `/eligibility/*`, `/packaging/*`, `/reports/*`, or `/notifications/*`.

### 3. Current Live Route Map
Use this map when checking visible routes for parity with the live platform.

| Area | Angular route |
| --- | --- |
| Default landing | `/replenishment/dashboard` |
| My Drafts and Submissions | `/replenishment/my-submissions` |
| Needs List Wizard | `/replenishment/needs-list-wizard` |
| Review Queue | `/replenishment/needs-list-review` |
| Operations Dashboard | `/operations/dashboard` |
| Relief Requests | `/operations/relief-requests` |
| Eligibility Review | `/operations/eligibility-review` |
| Package Fulfillment | `/operations/package-fulfillment` |
| Consolidation | `/operations/consolidation` |
| Dispatch | `/operations/dispatch` |
| Task Center | `/operations/tasks` |
| Master Data | `/master-data` |

### 4. Access-Key-Based Navigation Checks
When a route appears or is hidden unexpectedly, validate it against the current backend contract and Angular access rules.

| Nav access key | Expected live route |
| --- | --- |
| `replenishment.dashboard` | `/replenishment/dashboard` |
| `replenishment.submissions` | `/replenishment/my-submissions` |
| `replenishment.wizard` | `/replenishment/needs-list-wizard` |
| `replenishment.review` | `/replenishment/needs-list-review` |
| `operations.dashboard` | `/operations/dashboard` |
| `operations.relief-requests` | `/operations/relief-requests` |
| `operations.eligibility` | `/operations/eligibility-review` |
| `operations.fulfillment` | `/operations/package-fulfillment` and `/operations/consolidation` |
| `operations.dispatch` | `/operations/dispatch` |
| `operations.tasks` | `/operations/tasks` |
| `master.any` | `/master-data` |

### 5. Direct URL Authorization Checks
**Steps:**
1. Log in as a lower-privilege role.
2. Manually navigate to a route that should be restricted.
3. Repeat as an authorized role.

**Expected Results:**
- ✅ Unauthorized Angular routes redirect to access control handling rather than rendering protected content.
- ✅ Authorized roles can load the route through Angular guards and the Django API contract.
- ✅ Backend authorization remains the source of truth even if a user types a URL directly.

### 6. Backend Contract Validation
**Steps:**
1. While signed in, call `/api/v1/auth/whoami/`.
2. Compare returned permissions with the visible navigation and route access.
3. Exercise at least one allowed route and one denied route for each role under test.

**Expected Results:**
- ✅ Visible navigation aligns with returned permissions and tenant context.
- ✅ Backend responses remain available only through `/api/v1/*`.
- ✅ No user flow depends on Flask being reachable for page rendering or API access.

## Regression Checklist

After any auth, routing, navigation, or Flask-retirement change, verify:
- ✅ Users can sign in and sign out successfully.
- ✅ Default landing stays on `/replenishment/dashboard`.
- ✅ Navigation remains Angular-route based with no live Flask targets.
- ✅ Protected routes are enforced by Angular guards and backend authorization.
- ✅ No browser console errors appear during normal navigation.
- ✅ No operator or QA instruction requires Flask to be running for normal validation.

## Historical Note
This file replaces the earlier pre-cutover dashboard checklist.
The old Flask dashboard route assumptions are preserved in version history only and are no longer authoritative for DMIS release validation.
