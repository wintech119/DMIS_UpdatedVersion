# DRIMS Role-Based System Testing Guide

## Overview
This guide provides comprehensive test scenarios for validating DRIMS role-based access control, dynamic navigation, and feature-based permissions across all user roles.

## Test Accounts

### Admin Account
- **Email:** `admin [at] odpem [dot] gov [dot] jm`
- **Password:** `admin123`
- **Roles:** System Administrator
- **Expected Access:** Full system access to all features

### Single-Role Test Accounts
All test accounts use password: `test123`

1. **Logistics Manager**
   - **Email:** `test.logistics@odpem.gov.jm`
   - **Role:** LOGISTICS_MANAGER
   - **Dashboard:** Logistics Dashboard

2. **Agency User**
   - **Email:** `test.agency@gmail.com`
   - **Role:** AGENCY_SHELTER
   - **Dashboard:** Agency Dashboard

3. **Director**
   - **Email:** `test.director@odpem.gov.jm`
   - **Role:** ODPEM_DG (Director General)
   - **Dashboard:** Director Dashboard

4. **Inventory Clerk**
   - **Email:** `test.inventory@odpem.gov.jm`
   - **Role:** INVENTORY_CLERK
   - **Dashboard:** Inventory Dashboard

## Phase 8 Test Checklist

### 1. Authentication & Navigation Tests

#### Test 1.1: Login and Auto-Routing
**Steps:**
1. Log in as `test.logistics@odpem.gov.jm`
2. Verify redirect to Logistics Dashboard (`/dashboard/logistics`)
3. Logout and repeat for each test account

**Expected Results:**
- ✅ Logistics → `/dashboard/logistics`
- ✅ Agency → `/dashboard/agency`
- ✅ Director → `/dashboard/director`
- ✅ Inventory → `/dashboard/inventory`
- ✅ Admin → `/dashboard/admin`

#### Test 1.2: Dynamic Navigation
**Steps:**
1. Log in as each role
2. Check sidebar navigation items

**Expected Navigation Items:**

**Logistics Manager:**
- ✅ Dashboard
- ✅ Inventory features (View Inventory, Manage Stock, Transfers)
- ✅ Package fulfillment features
- ✅ Approve packages
- ✅ Warehouses, Items, Locations
- ❌ Should NOT see: Agency requests, Eligibility review, User admin

**Agency User:**
- ✅ Dashboard
- ✅ Create Relief Requests
- ✅ Track My Requests
- ❌ Should NOT see: Inventory management, Package fulfillment, User admin

**Director:**
- ✅ Dashboard
- ✅ Eligibility Review
- ✅ Approve Relief Requests
- ✅ View Reports
- ❌ Should NOT see: Package fulfillment details, User admin

**Inventory Clerk:**
- ✅ Dashboard
- ✅ View Inventory
- ✅ Stock Levels
- ✅ Receive Stock (Donations)
- ❌ Should NOT see: Relief requests, User admin, Approve packages

**Admin:**
- ✅ All navigation items visible

### 2. Dashboard Feature Tests

#### Test 2.1: Dashboard Widgets
**Steps:**
1. Log in as each role
2. Verify dashboard shows role-appropriate widgets

**Expected Widgets:**

**Logistics Dashboard:**
- ✅ Pending fulfillment count
- ✅ Packages in progress
- ✅ Ready for dispatch
- ✅ Low stock alerts
- ✅ Quick action: Prepare package

**Agency Dashboard:**
- ✅ My active requests
- ✅ Pending requests
- ✅ Approved requests
- ✅ Quick action: Create new request

**Director Dashboard:**
- ✅ Pending eligibility reviews
- ✅ Approved requests
- ✅ In-progress requests
- ✅ Quick action: Review eligibility

**Inventory Dashboard:**
- ✅ Total inventory value
- ✅ Low stock items
- ✅ Stock by warehouse
- ✅ Quick action: Receive stock

#### Test 2.2: Dashboard Filters
**Steps:**
1. Log in as Logistics user
2. Click filter tabs (Pending, In Progress, Ready, All)
3. Verify table updates accordingly

**Expected Results:**
- ✅ Filter tabs show correct counts
- ✅ Table filters match selected tab
- ✅ Empty states show when no data

### 3. Profile & User Menu Tests

#### Test 3.1: User Profile Access
**Steps:**
1. Log in as any test account
2. Click user dropdown (top right)
3. Click "My Profile"

**Expected Results:**
- ✅ Profile page loads at `/profile/`
- ✅ Shows user's name, email, role
- ✅ Shows accessible features organized by category
- ✅ Shows warehouse assignments (if applicable)

#### Test 3.2: Profile Feature Display
**Steps:**
1. View profile as Logistics user
2. Check features section

**Expected Results:**
- ✅ Features grouped by category
- ✅ Shows Inventory, Relief Requests, Management categories
- ✅ Does NOT show Admin features

#### Test 3.3: Profile Actions
**Steps:**
1. Click "Edit Profile"
2. Update phone number
3. Click "Save Changes"

**Expected Results:**
- ✅ Form validation works
- ✅ Changes save successfully
- ✅ Redirect back to profile view

### 4. Backend Security Tests

#### Test 4.1: Direct URL Access (Unauthorized)
**Steps:**
1. Log in as Agency user
2. Manually navigate to `/users` (admin-only route)

**Expected Results:**
- ✅ Redirected or 403 error
- ✅ Flash message: "You do not have permission..."
- ❌ Should NOT see user list

#### Test 4.2: Direct URL Access (Authorized)
**Steps:**
1. Log in as Admin user
2. Navigate to `/users`

**Expected Results:**
- ✅ User list displays
- ✅ No error messages

### 5. Feature Registry Integration Tests

#### Test 5.1: Feature Access Check
**Steps:**
1. Log in as Logistics user
2. Navigate to any inventory page
3. Log out
4. Log in as Agency user
5. Try to navigate to inventory page (if link visible)

**Expected Results:**
- ✅ Logistics user can access
- ✅ Agency user cannot access (or link not shown)

#### Test 5.2: Multi-Role Feature Access
**Steps:**
1. Create a user with multiple roles (Admin + Logistics)
2. Log in and check available features

**Expected Results:**
- ✅ Sees combined features from both roles
- ✅ Navigation shows all accessible items
- ✅ Dashboard routes to highest priority role

### 6. UI/UX Consistency Tests

#### Test 6.1: Modern UI Elements
**Steps:**
1. Navigate through different pages
2. Check for consistent styling

**Expected Elements:**
- ✅ Summary metric cards with icons
- ✅ Filter tabs with count badges
- ✅ relief-requests-table styling
- ✅ btn-relief-primary and btn-relief-secondary buttons
- ✅ Color-coded status badges
- ✅ GOJ green/gold branding throughout

#### Test 6.2: Responsive Design
**Steps:**
1. Test on different screen sizes
2. Toggle sidebar with hamburger menu

**Expected Results:**
- ✅ Sidebar collapses on mobile
- ✅ Hamburger menu works
- ✅ Content adjusts to sidebar state
- ✅ Footer maintains layout

### 7. Notification System Tests

#### Test 7.1: Notification Bell
**Steps:**
1. Log in as any user
2. Check notification bell (top right)

**Expected Results:**
- ✅ Bell icon visible
- ✅ Badge shows count if notifications exist
- ✅ Click opens notification panel

#### Test 7.2: Notification List
**Steps:**
1. Click notification bell
2. View notifications in panel

**Expected Results:**
- ✅ Recent notifications display
- ✅ Mark as read functionality works
- ✅ Click notification navigates to relevant page

### 8. Data Integrity Tests

#### Test 8.1: Role Assignment
**Steps:**
1. Log in as Admin
2. Navigate to User Management
3. Create new user with specific role
4. Log out and log in as new user

**Expected Results:**
- ✅ User sees only features for assigned role
- ✅ Dashboard matches role
- ✅ Navigation filtered correctly

#### Test 8.2: Warehouse Access
**Steps:**
1. Assign user to specific warehouse
2. Check inventory views

**Expected Results:**
- ✅ User sees assigned warehouse
- ✅ Inventory filtered by warehouse (if applicable)

### 9. Error Handling Tests

#### Test 9.1: Invalid Login
**Steps:**
1. Try to log in with wrong password
2. Try to log in with non-existent email

**Expected Results:**
- ✅ Error message displayed
- ✅ No sensitive information leaked
- ✅ User remains on login page

#### Test 9.2: Session Expiry
**Steps:**
1. Log in
2. Wait for session to expire (or clear cookies)
3. Try to navigate to protected page

**Expected Results:**
- ✅ Redirected to login
- ✅ Next parameter preserves intended destination
- ✅ After login, redirects to original destination

### 10. Performance Tests

#### Test 10.1: Page Load Times
**Steps:**
1. Navigate to dashboard
2. Check load time

**Expected Results:**
- ✅ Dashboard loads in < 2 seconds
- ✅ No visible lag
- ✅ Widgets load smoothly

#### Test 10.2: Filter Performance
**Steps:**
1. On dashboard, switch between filter tabs
2. Check response time

**Expected Results:**
- ✅ Filters update immediately
- ✅ No delays or flickering
- ✅ Count badges accurate

## Regression Testing Checklist

After any code changes, verify:
- ✅ All test accounts can log in
- ✅ Dashboard routing works for each role
- ✅ Navigation shows appropriate items
- ✅ Profile page loads correctly
- ✅ Backend decorators enforce permissions
- ✅ No console errors in browser
- ✅ No Python errors in workflow logs

## Known Issues & Limitations

### LSP Diagnostics (Non-blocking)
- **Issue:** 5 type-checking warnings in `app/features/user_admin.py`
- **Impact:** None - false positives from SQLAlchemy model constructors
- **Resolution:** Code runs correctly; type checker doesn't recognize SQLAlchemy patterns

### Profile Preferences (Needs User Testing)
- **Issue:** Notification preferences persistence needs database verification
- **Impact:** Preferences may not save correctly
- **Resolution:** User testing required to verify schema compatibility

## Testing Best Practices

1. **Always test with fresh login** - Logout between role tests
2. **Clear browser cache** - Prevents stale UI issues
3. **Check both UI and logs** - Verify backend behaves correctly
4. **Test edge cases** - Empty states, no data scenarios
5. **Document new issues** - Add to Known Issues section

## Automated Testing (Future)

Recommended test coverage:
- Unit tests for FeatureRegistry methods
- Integration tests for decorators
- E2E tests for login flow
- Role-based access tests
- Dashboard rendering tests

## Test Results Template

```
Test Date: ____________________
Tester: _______________________
DRIMS Version: ________________

| Test ID | Description | Status | Notes |
|---------|-------------|--------|-------|
| 1.1     | Auto-routing| ✅ Pass |       |
| 1.2     | Navigation  | ✅ Pass |       |
| 2.1     | Widgets     | ✅ Pass |       |
| ...     | ...         | ...    |       |

Overall Result: ✅ Pass / ❌ Fail
Critical Issues: _________________
Recommendations: _________________
```

## Summary

This comprehensive testing guide ensures DRIMS role-based system works correctly across all user types. Complete all tests before deploying to production or after significant changes to authentication, authorization, or navigation systems.

For questions or issues, refer to:
- `docs/backend_security_decorators.md` - Security implementation
- `docs/testing/dashboard_test_plan.md` - Dashboard-specific tests
- `replit.md` - Project architecture and changes
