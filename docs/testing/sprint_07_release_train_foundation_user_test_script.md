# DMIS | Sprint 07 | User Test Script | Release Train Foundation

Last updated: 2026-03-18  
Status: Ready for tester execution  
Primary source: `docs/requirements/sprint_07_logistics_masters_implementation_brief.md`

## Purpose

This document gives a tester a step-by-step Sprint 07 user walkthrough to validate that the implemented application behavior matches the approved Sprint 07 scope.

It is written to be:

- easy to execute manually
- easy to export to PDF or Word
- specific enough for page, form, click, and typed-value validation

## Sprint 07 Scope Covered By This Script

- item categories
- IFRC families
- IFRC item references
- item master
- agencies
- warehouses and hub structure
- scoped location flow
- stock visibility
- stock-health visibility baseline
- create-only UOM repackaging
- basic authorization checks

## Test Users

Use the existing test accounts from `docs/testing/role_based_system_testing_guide.md`.
Retrieve the current email addresses and passwords from the QA admin or approved secret store for the target environment. Do not store plaintext credentials in this document.

| Role | Account Retrieval Method | Main Use In This Script |
| --- | --- | --- |
| System Administrator | Obtain the current admin test account from QA admin or the approved secret store | Create and maintain master data |
| Inventory Clerk | Obtain the current inventory-clerk test account from QA admin or the approved secret store | Verify stock visibility and execute repackaging |
| Logistics Manager | Obtain the current logistics-manager test account from QA admin or the approved secret store | Optional cross-check of operational visibility |
| Agency User | Obtain the current agency-user test account from QA admin or the approved secret store | Negative permission check |

If the environment uses masked emails, use the equivalent active account for the same role.

## Test Data To Use

Use the following values unless they already exist. If a value already exists, generate the next valid test-specific value for that field:

- for code or name fields, append a suffix such as `-B` or `-02`
- for email fields, use the environment's approved test-account alias pattern
- for enumerations, keep the documented valid enum and choose a different field value elsewhere
- for numeric identifiers, use the next available seeded test value rather than changing the format

| Field | Value |
| --- | --- |
| Category Code | `S07WASH` |
| Category Description | `Sprint 07 Water and Hygiene` |
| IFRC Family Label | `Water Purification` |
| IFRC Group Code | `WASH` |
| IFRC Group Label | `Water and Sanitation` |
| IFRC Family Code | `WTRPUR` |
| IFRC Source Version | `DMIS-S07` |
| IFRC Reference Description | `Water purification tablet, 100 tabs` |
| Size or Weight | `100 TABS` |
| Form | `TABLET` |
| Material | `CHLORINE` |
| IFRC Reference Category Code | `WTRTAB` |
| IFRC Reference Category Label | `Water Treatment Tablet` |
| Item Name | `WATER PURIFICATION TABLET, 100 TABS` |
| Local Item Code | `LOC-S07-WASH-001` |
| SKU Code | `SKU-S07-WTAB-100` |
| Item Description | `Water purification tablet, 100 tabs, chlorine based, emergency response stock` |
| Default UOM | `EA` |
| Alternate UOM 1 | `CASE` |
| Units in Alternate UOM 1 | `24` |
| Alternate UOM 2 | `PACK` |
| Units in Alternate UOM 2 | `6` |
| Reorder Quantity | `100` |
| Baseline Burn Rate | `10` |
| Min Stock Threshold | `75` |
| Criticality Level | `CRITICAL` |
| Agency Name | `S07 TEST DISTRIBUTOR AGENCY` |
| Warehouse Name | `S07 TEST MAIN HUB` |
| Warehouse Type | `MAIN-HUB` |
| Location Description | `S07-AISLE-01-BIN-01` |
| Repackaging Reason | `SPLIT_EACHES` |

## Preconditions

Before executing the use case, confirm:

1. Sprint 07 backend and frontend are deployed in the test environment.
2. The tester can log in with the admin and inventory-clerk accounts.
3. At least one valid custodian exists for warehouse creation.
4. At least one parish exists for warehouse and agency setup.
5. At least one UOM such as `EA` exists and is active.
6. Item Master Step 3 includes the inline `Item UOM Conversions` section and the UOM repackaging UI is available in the environment.
7. Inventory stock exists for the test item before running the repackaging steps.
8. A stock-health view is available either in Item detail, Inventory, or the Stock Status Dashboard.

If stock does not yet exist for the test item, stop and request a seeded stock record before continuing with the repackaging steps.

## Use Case Overview

This test script follows one realistic Sprint 07 flow:

1. Admin creates the governed catalog records.
2. Admin creates the operational master records.
3. Admin creates the item and verifies stock-rule fields.
4. Admin or seeded data provides inventory for the item.
5. Inventory Clerk confirms stock and stock-health visibility.
6. Inventory Clerk performs create-only UOM repackaging.
7. Tester validates negative cases and role restrictions.

## Use Case 1: Create Sprint 07 Catalog Foundations

### Step 1. Login as System Administrator

1. Open the application login page.
2. In the email field, enter the current System Administrator test account email retrieved for this environment.
3. In the password field, enter the corresponding password retrieved from the approved secure source.
4. Click `Login`.

Expected result:

- the user is authenticated successfully
- the admin dashboard or home page loads
- the left navigation shows master-data maintenance entries

Evidence to capture:

- screenshot of the logged-in landing page

### Step 2. Create Item Category

1. In the left navigation, click `Master Data`.
2. Click `Item Categories`.
3. Click `New` or `Add Item Category`.
4. In `Code`, type `S07WASH`.
5. In `Description`, type `Sprint 07 Water and Hygiene`.
6. In `Type`, select `Goods`.
7. In `Comments`, type `Sprint 07 release-train user test category`.
8. In `Status`, leave `Active`.
9. Click `Save`.

Expected result:

- the record saves successfully
- the category appears in the list
- the list shows code `S07WASH`
- the list shows description `Sprint 07 Water and Hygiene`
- the status shows `Active`

Evidence to capture:

- saved category detail or list row

### Step 3. Create IFRC Family

1. In `Master Data`, click `IFRC Families`.
2. Click `New` or `Add IFRC Family`.
3. In `Family Label`, type `Water Purification`.
4. In `Level 1 Category`, select `Sprint 07 Water and Hygiene`.
5. If `Suggest Family Values` is available, click it.
6. If `Group Code` is blank, type `WASH`.
7. If `Family Code` is blank, type `WTRPUR`.
8. In `Group Label`, type `Water and Sanitation`.
9. In `Source Version`, type `DMIS-S07`.
10. In `Status`, leave `Active`.
11. Click `Save`.

Expected result:

- the family saves successfully
- the list shows the new family
- the family is linked to the Sprint 07 category
- if codes were generated automatically, they stay populated after save

Evidence to capture:

- family detail page or list row

### Step 4. Create IFRC Item Reference

1. In `Master Data`, click `IFRC Item References`.
2. Click `New` or `Add IFRC Item Reference`.
3. In `IFRC Family`, select `Water Purification`.
4. In `Reference Description`, type `Water purification tablet, 100 tabs`.
5. In `Size or Weight`, type `100 TABS`.
6. In `Form`, type `TABLET`.
7. In `Material`, type `CHLORINE`.
8. If `Suggest Reference Values` is available, click it.
9. If `Category Code` is blank, type `WTRTAB`.
10. If `Category Label` is blank, type `Water Treatment Tablet`.
11. If `Source Version` is blank, type `DMIS-S07`.
12. In `Status`, leave `Active`.
13. Click `Save`.

Expected result:

- the item reference saves successfully
- the record shows an IFRC code after save
- the record remains linked to the selected IFRC family
- the record is active and available for item selection

Evidence to capture:

- saved IFRC reference showing code and description

## Use Case 2: Create Operational Masters

### Step 5. Create Warehouse

1. In `Master Data`, click `Warehouses`.
2. Click `New` or `Add Warehouse`.
3. In `Warehouse Name`, type `S07 TEST MAIN HUB`.
4. In `Type`, select `Main Hub`.
5. In `Custodian`, choose an available test custodian.
6. In `Min Stock Threshold`, type `50`.
7. In `Address Line 1`, type `1 Test Logistics Way`.
8. In `Address Line 2`, type `Kingston Test Block`.
9. In `Parish`, choose a valid parish.
10. In `Contact Name`, type `SPRINT SEVEN LEAD`.
11. In `Phone`, type `+1 (876) 555-0101`.
12. In `Email`, type `s07warehouse@test.gov.jm`.
13. In `Status`, leave `Active`.
14. Click `Save`.

Expected result:

- the warehouse saves successfully
- the warehouse list shows `S07 TEST MAIN HUB`
- the warehouse type shows `Main Hub`
- the status shows `Active`

Evidence to capture:

- warehouse list row or detail page

### Step 6. Create Agency

1. In `Master Data`, click `Agencies`.
2. Click `New` or `Add Agency`.
3. In `Agency Name`, type `S07 TEST DISTRIBUTOR AGENCY`.
4. In `Type`, select `Distributor`.
5. In `Warehouse`, select `S07 TEST MAIN HUB`.
6. In `Priority`, type `1`.
7. Leave `Ineligible Event` blank unless required by the environment.
8. In `Address Line 1`, type `2 Test Response Road`.
9. In `Address Line 2`, type `Kingston Shelter Zone`.
10. In `Parish`, choose the same parish used for the warehouse.
11. In `Contact Name`, type `AGENCY TEST USER`.
12. In `Phone`, type `+1 (876) 555-0102`.
13. In `Email`, type `s07agency@test.gov.jm`.
14. In `Status`, leave `Active`.
15. Click `Save`.

Expected result:

- the agency saves successfully
- the agency list shows the new agency
- the agency is linked to the test warehouse

Evidence to capture:

- agency detail or list row

## Use Case 3: Create Item Master and Validate Rules

### Step 7. Create Item And Configure Inline UOM Conversions

1. In `Master Data`, click `Items`.
2. Click `New` or `Add Item`.
3. Do not type anything in `Item Code` unless the environment requires manual entry.
4. In `Local Item Code`, type `LOC-S07-WASH-001`.
5. In `Item Name`, type `WATER PURIFICATION TABLET, 100 TABS`.
6. In `SKU Code (Optional)`, type `SKU-S07-WTAB-100`.
7. In `Level 1 Category`, select `Sprint 07 Water and Hygiene`.
8. In `Level 2 IFRC Family`, select `Water Purification`.
9. In `Level 3 IFRC Item Reference`, select `Water purification tablet, 100 tabs`.
10. In `Description`, type `Water purification tablet, 100 tabs, chlorine based, emergency response stock`.
11. In `Default UOM`, select `EA`.
12. In `Reorder Quantity`, type `100`.
13. In `Issuance Order`, select `FEFO`.
14. In `Baseline Burn Rate`, type `10`.
15. In `Min Stock Threshold`, type `75`.
16. In `Criticality Level`, select `Critical`.
17. Ensure `Batch Tracked` is enabled.
18. Ensure `Can Expire` is enabled.
19. Leave `Units Size Vary` disabled.
20. In the same Step 3 `UOM & Conversions` screen, locate the inline `Item UOM Conversions` section near `Default UOM`.
21. Confirm the section shows that the default UOM is treated as `1` or is otherwise marked as system-managed.
22. Click `Add Conversion`.
23. In `Alternate UOM`, select `CASE`.
24. In `Units in Alternate UOM`, type `24`.
25. Click `Add Conversion` again.
26. In the new row, select `PACK` for `Alternate UOM`.
27. In `Units in Alternate UOM`, type `6`.
28. In `Usage Description`, type `Issued to shelters and field teams during water safety response`.
29. In `Storage Description`, type `Store in a cool dry area and rotate by expiry`.
30. In `Comments`, type `Sprint 07 user acceptance test item`.
31. In `Status`, leave `Active`.
32. Click `Save`.

Expected result:

- the item saves successfully
- the item code is generated or retained correctly
- the item remains linked to the chosen IFRC family and IFRC reference
- `FEFO` and `Can Expire` remain aligned after save
- the inline `Item UOM Conversions` entries for `CASE = 24` and `PACK = 6` save successfully
- the record appears active in the item list

Evidence to capture:

- saved item detail page
- screenshot of Step 3 `UOM & Conversions` showing the inline `Item UOM Conversions` section before save

### Step 8. Verify Inline UOM Conversion Setup Persists On Edit

1. From the saved item page, click `Edit`.
2. Return to Step 3: `UOM & Conversions`.
3. Locate the inline `Item UOM Conversions` section near `Default UOM`.
4. Confirm the saved rows for `CASE = 24` and `PACK = 6` are visible as editable alternate rows.
5. Confirm the default UOM `EA` is still treated as system-managed rather than as a manually editable alternate row.
6. Do not change the values.
7. Click `Cancel` or return to the saved item page without changing the item.

Expected result:

- the inline alternate UOM rows load correctly on edit
- both alternate UOM values remain available for the item
- the saved conversions are available to the repackaging flow

Evidence to capture:

- screenshot of Step 3 `UOM & Conversions` on edit showing the saved alternate UOM rows

## Use Case 4: Verify Stock, Location, and Stock Health

### Step 9. Confirm Inventory Exists For The Item

1. In `Master Data`, click `Inventory`.
2. Search for the saved item by item ID, item code, or item name.
3. Open the relevant inventory record if one exists.

Expected result:

- the tester can locate an inventory record for the item
- the record shows `Usable Quantity` greater than `0`
- the record shows the expected default UOM
- the record shows the reorder quantity

If no inventory exists:

- stop the script here
- record the gap as `blocked by missing seeded or intake-created inventory`

Evidence to capture:

- screenshot of the inventory record

### Step 10. Create Or Verify Scoped Location Record

1. In `Master Data`, click `Locations`.
2. Click `New` or `Add Location`.
3. In `Inventory`, select the inventory record for the Sprint 07 item.
4. In `Location Description`, type `S07-AISLE-01-BIN-01`.
5. In `Comments`, type `Sprint 07 scoped location assignment test`.
6. In `Status`, leave `Active`.
7. Click `Save`.

Expected result:

- the location saves successfully
- the location remains tied to the selected inventory record
- the list shows the new location

Evidence to capture:

- location detail or list row

### Step 11. Verify Stock-Health Visibility

1. Open the stock visibility page used in the environment for Sprint 07 validation.
2. If available, use `Inventory`, `Item detail`, or `Stock Status Dashboard`.
3. Search for the Sprint 07 test item.
4. Review the displayed health or severity indicator.

Expected result:

- the item shows a visible stock-health indicator
- the indicator is based on stock and reorder settings, not on free text
- the indicator is readable to a user without opening the database
- if the environment renders health as color or severity labels, the item is classified consistently with its quantity and thresholds

Evidence to capture:

- screenshot of the stock-health indicator

## Use Case 5: Execute Create-Only UOM Repackaging

### Step 12. Login as Inventory Clerk

1. Logout from the admin account.
2. Return to the login page.
3. In the email field, enter the current Inventory Clerk test account email retrieved for this environment.
4. In the password field, enter the corresponding password retrieved from the approved secure source.
5. Click `Login`.

Expected result:

- the inventory dashboard loads
- the inventory user can access stock and operational inventory functions

Evidence to capture:

- screenshot of the inventory dashboard

### Step 13. Open UOM Repackaging

1. In the left navigation, click the inventory or logistics operational menu.
2. Click `Repackaging`, `UOM Repackaging`, or the equivalent Sprint 07 operational entry point.

Expected result:

- the repackaging page opens
- the page is clearly an operational transaction screen, not a master-data screen
- the page does not show reversal or void actions

Evidence to capture:

- screenshot of the repackaging page

### Step 14. Submit A Valid Repackaging Transaction

1. In `Warehouse`, select `S07 TEST MAIN HUB`.
2. In `Item`, select `WATER PURIFICATION TABLET, 100 TABS`.
3. If batch or lot is required, select the available active batch for this item.
4. In `Source UOM`, select `EA`.
5. In `Source Quantity`, type `10`.
6. In `Target UOM`, select the alternate UOM created in Step 7.
7. Verify that `Computed Target Quantity` is shown by the system and matches the expected conversion for the selected UOMs. Example: if `10 EA` converts at `10:1`, the computed target quantity should display `1` in the target UOM.
8. In `Reason`, type `SPLIT_EACHES`.
9. Click `Preview`, `Validate`, or the equivalent pre-submit action if present.
10. Review the computed values.
11. Click `Submit`, `Save`, or `Confirm`.

Expected result:

- the transaction saves successfully
- the system shows a success message
- the saved result remains in the same item and same warehouse
- the saved result shows source and target UOM values
- the saved result shows a persisted audit or transaction record
- the page does not suggest transfer, procurement receipt, or donation intake behavior

Evidence to capture:

- screenshot of the pre-submit preview
- screenshot of the saved repackaging result

### Step 15. Verify Persisted Outcome

1. Open the repackaging detail page or transaction history view.
2. Confirm the source quantity, target quantity, and reason are visible.
3. Confirm the persisted transaction detail matches the saved preview values.
4. Confirm audit metadata such as actor and time is visible where the product exposes it.

Expected result:

- the persisted record matches the submitted transaction
- quantities shown after save match the saved transaction, not just the preview
- the transaction history or detail view shows the saved actor/time metadata where exposed

Evidence to capture:

- screenshot of persisted transaction detail
- screenshot of transaction history or audit metadata

## Negative Checks

### Step 16. Same-UOM Rejection

1. Return to the repackaging page.
2. Select the same warehouse and item.
3. Set `Source UOM` and `Target UOM` to the same value.
4. Enter a source quantity.
5. Click `Submit` or `Validate`.

Expected result:

- the system blocks the action
- the user sees a clear validation message
- no transaction is created

### Step 17. Insufficient Stock Rejection

1. Start a new repackaging transaction.
2. Use a source quantity larger than the available stock, such as `999999`.
3. Click `Submit` or `Validate`.

Expected result:

- the system blocks the action
- the user sees an insufficient-stock error
- no transaction is created

### Step 18. Unauthorized Access Check

1. Logout from the inventory-clerk account.
2. Log in as the agency user.
3. Try to navigate directly to:
   - `Master Data > Item Categories`
   - the UOM repackaging page
4. If needed, paste the direct URL for the repackaging page into the browser.

Expected result:

- the agency user cannot access governed catalog maintenance
- the agency user cannot execute repackaging
- the system redirects, hides the feature, or shows a permission error

Evidence to capture:

- screenshot of the blocked access result

## Pass Criteria

Sprint 07 passes this user test if all of the following are true:

- governed catalog records can be created and saved
- item master links correctly to category, IFRC family, and IFRC reference
- warehouse, agency, and scoped location records can be saved
- stock is visible for the created item
- stock-health is visible in at least one approved Sprint 07 stock view
- valid repackaging succeeds
- invalid repackaging is blocked
- unauthorized users are blocked from protected functions

## Defect Logging Format

When the tester finds a defect, log:

- page name
- action taken
- value entered
- expected result
- actual result
- screenshot
- severity

Example:

- Page: `UOM Repackaging`
- Action: Submit with same source and target UOM
- Expected: Validation blocks save
- Actual: Transaction saved successfully
- Severity: High

## Export Note

This file is intentionally structured for export. It can be:

- exported directly as Markdown
- converted to PDF
- copied into Word or Notion with minimal cleanup
