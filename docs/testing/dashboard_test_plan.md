# Dashboard Testing Plan - Phase 4

## Test Accounts
All test accounts use password: `test123` (except admin which uses `admin123`)

These accounts are created by running `python scripts/create_test_users.py`

| Email | Role | Dashboard |
|-------|------|-----------|
| test.logistics@odpem.gov.jm | Logistics Manager | Logistics Dashboard |
| test.agency@gmail.com | Agency Shelter | Agency Dashboard |
| test.director@odpem.gov.jm | Director General | Director Dashboard |
| test.inventory@odpem.gov.jm | Inventory Clerk | Inventory Dashboard |
| admin [at] odpem [dot] gov [dot] jm | System Administrator | Admin Dashboard |

## Test Execution Checklist

### 1. Logistics Dashboard Test (`test.logistics@odpem.gov.jm`)
**Route:** Should auto-route from `/` to logistics dashboard

- [ ] Login successful
- [ ] Routes to `/` showing **Logistics Dashboard** (not Admin)
- [ ] Page header shows "Logistics Dashboard" with speedometer icon
- [ ] **4 Summary Cards Display:**
  - [ ] Pending Fulfillment (warning badge)
  - [ ] Being Prepared (info badge)
  - [ ] Ready for Dispatch (success badge)
  - [ ] Completed (secondary badge)
- [ ] **Filter Tabs Work:**
  - [ ] Pending tab
  - [ ] In Progress tab
  - [ ] Ready tab
  - [ ] Completed tab
  - [ ] All tab
  - [ ] Count badges show accurate numbers
- [ ] Requests table displays with modern styling
- [ ] "View All Fulfillment" button appears (top right)
- [ ] Action buttons appropriate for each status:
  - Pending requests show "Prepare" button
  - In Progress shows "In Progress" lock icon
  - Ready shows "Review" button
- [ ] No console errors
- [ ] Modern UI matches Relief Package pages

### 2. Agency Dashboard Test (`test.agency@gmail.com`)
**Route:** Should auto-route from `/` to agency dashboard

- [ ] Login successful
- [ ] Routes to `/` showing **Agency Dashboard** (not Admin)
- [ ] Page header shows "Agency Dashboard" with building icon
- [ ] **4 Summary Cards Display:**
  - [ ] Draft Requests (secondary badge)
  - [ ] Pending Review (warning badge)
  - [ ] Approved & In Progress (info badge)
  - [ ] Completed (success badge)
- [ ] **Filter Tabs Work:**
  - [ ] Active tab (default)
  - [ ] Draft tab
  - [ ] Pending tab
  - [ ] Approved tab
  - [ ] Completed tab
  - [ ] Count badges show accurate numbers
- [ ] Shows only THIS agency's requests (not all requests)
- [ ] "Create New Request" button appears (top right)
- [ ] Action buttons appropriate for status:
  - Draft requests show "Edit" button
  - Other statuses show "View" button
- [ ] Empty state shows helpful message if no requests
- [ ] No console errors

### 3. Director Dashboard Test (`test.director@odpem.gov.jm`)
**Route:** Should auto-route from `/` to director dashboard

- [ ] Login successful
- [ ] Routes to `/` showing **Director Dashboard** (not Admin)
- [ ] Page header shows "Director Dashboard" with clipboard icon
- [ ] **4 Summary Cards Display:**
  - [ ] Pending Review (warning badge)
  - [ ] Approved (success badge)
  - [ ] In Progress (info badge)
  - [ ] Completed (secondary badge)
- [ ] **Filter Tabs Work:**
  - [ ] Pending tab
  - [ ] Approved tab
  - [ ] In Progress tab
  - [ ] Completed tab
  - [ ] All tab
  - [ ] Count badges show accurate numbers
- [ ] "Review Eligibility" button appears (top right)
- [ ] Requests table shows all agencies (not filtered to one)
- [ ] Action buttons appropriate for status:
  - Pending (status 1) shows "Review" button
  - Other statuses show "View" button
- [ ] No console errors

### 4. Inventory Dashboard Test (`test.inventory@odpem.gov.jm`)
**Route:** Should auto-route from `/` to inventory dashboard

- [ ] Login successful
- [ ] Routes to `/` showing **Inventory Dashboard** (not Admin)
- [ ] Page header shows "Inventory Dashboard" with boxes icon
- [ ] **4 Summary Cards Display:**
  - [ ] Total Inventory Value (primary badge)
  - [ ] Low Stock Items (warning badge)
  - [ ] Recent Intakes (info badge)
  - [ ] Pending Transfers (secondary badge)
- [ ] Low stock alert section displays if items below reorder level
- [ ] Low stock items table shows:
  - [ ] Item name
  - [ ] Current stock with warning badge
  - [ ] Reorder level
  - [ ] Status badge (Out of Stock/Low Stock/In Stock)
  - [ ] "View Details" action button
- [ ] "Record Intake" button appears (top right)
- [ ] "View Inventory" button appears (top right)
- [ ] Success alert shows "All good!" if no low stock items
- [ ] No console errors

### 5. Admin Dashboard Test (`admin [at] odpem [dot] gov [dot] jm`)
**Route:** Should auto-route from `/` to admin dashboard

- [ ] Login successful  
- [ ] Routes to `/` showing **System Administration** dashboard
- [ ] Page header shows "System Administration" with gear icon
- [ ] **4 System Metrics Cards Display:**
  - [ ] Total Users (primary badge)
  - [ ] Active Agencies (info badge)
  - [ ] Warehouses (success badge)
  - [ ] Relief Items (warning badge)
- [ ] Recent relief requests table displays (up to 10)
- [ ] Quick Links section displays with all features user has access to:
  - [ ] Manage Users
  - [ ] Manage Agencies
  - [ ] Manage Warehouses
  - [ ] Manage Items
  - [ ] Manage Events
  - [ ] View Reports
- [ ] Recent users section displays (up to 5)
- [ ] "Manage Users" button appears (top right)
- [ ] No console errors

## Common UI Elements Verification

All dashboards should have these consistent elements:

### Visual Styling
- [ ] Uses `relief-requests-ui.css` stylesheet
- [ ] Summary cards have:
  - [ ] Icon on left with colored background
  - [ ] Label text below value
  - [ ] Proper color variants (primary/info/success/warning/secondary)
  - [ ] Clean white background with shadow
- [ ] Filter tabs have:
  - [ ] Active tab highlighted with bottom border
  - [ ] Count badges with proper styling
  - [ ] Hover effects
- [ ] Tables use `relief-requests-table` class with:
  - [ ] Zebra striping
  - [ ] Hover row highlighting
  - [ ] Modern table styling
- [ ] Action buttons use:
  - [ ] `btn-relief-primary` for primary actions (green)
  - [ ] `btn-relief-secondary` for secondary actions (outlined)
  - [ ] Proper icon + text combination
  
### Navigation & Branding
- [ ] GOJ header with coat of arms and ODPEM logo
- [ ] Navigation sidebar with user's available features
- [ ] Notification bell icon (top right)
- [ ] User profile dropdown
- [ ] Footer with GOJ branding

### Responsive Design
- [ ] Desktop layout (>992px): Full sidebar, wide content
- [ ] Tablet layout (768-991px): Collapsed sidebar, medium content
- [ ] Mobile layout (<768px): Hidden sidebar (hamburger menu), full-width content

## Edge Cases

### No Data Scenarios
- [ ] Brand new user with no requests sees empty state
- [ ] Empty state shows helpful message
- [ ] Empty state has icon
- [ ] Empty state offers action (e.g., "Create Your First Request")

### Large Data Scenarios
- [ ] Dashboard with 100+ requests loads in <2 seconds
- [ ] Filter tabs still perform well
- [ ] Count badges accurate
- [ ] No pagination issues

### Error Scenarios
- [ ] User with no agency_id doesn't crash agency dashboard
- [ ] User with no assigned warehouse doesn't crash inventory dashboard
- [ ] Missing data shows "N/A" instead of blank or error

## Performance Checks

- [ ] Dashboard initial load: <2 seconds
- [ ] Filter tab click: Instant (<200ms)
- [ ] Count queries optimized (no N+1 queries)
- [ ] Uses SQLAlchemy joinedload for related data
- [ ] No excessive database queries (check logs)

## Browser Compatibility

Test in these browsers:
- [ ] Chrome (latest)
- [ ] Firefox (latest)
- [ ] Safari (latest)
- [ ] Edge (latest)

## Accessibility

- [ ] All filter tabs have `aria-current` when active
- [ ] Tables have `role="table"` and proper headers
- [ ] Icon-only buttons have `aria-label`
- [ ] Color is not the only indicator of status (text labels present)
- [ ] Keyboard navigation works (Tab, Enter, Escape)

## Test Execution Notes

Record any issues found during testing:

```
Issue #1:
Dashboard: 
Description:
Steps to reproduce:
Expected:
Actual:
Priority: High/Medium/Low
```

## Sign-Off

- [ ] All 5 dashboards tested successfully
- [ ] All UI elements consistent across dashboards
- [ ] No console errors in any dashboard
- [ ] Performance acceptable
- [ ] Ready for production use

**Tested by:** _________________  
**Date:** _________________  
**Version:** Phase 4 (November 14, 2025)
