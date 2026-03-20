# Sprint 07 Validation Report

Date: 2026-03-20  
Validated worktree: `C:\Users\wbowe\.codex\worktrees\21c2\DMIS_UpdatedVersion`  
Requested branch baseline: `codex/dmis-may15-release-train`  
Validated commit: `01d18bad21a24a28e8736e0cacaeee8b5237c2f4`

## Summary

Sprint 07 was validated against the release-train foundation brief and the Sprint 07 user test script, with the sprint brief treated as the source of truth.

Overall outcome:

- Pass with blockers
- Core master-data, stock-health, scoped location, and touched regression foundations are present
- Backend repackaging behavior is implemented and covered by tests
- Sprint 07 cannot be considered fully passed end to end because the frontend UOM repackaging user flow required by the test script is not exposed in the Angular application

## Scope Validated

In-scope Sprint 07 validation covered:

- catalog setup
- item master
- agency, warehouse, and scoped location behavior
- stock visibility and stock-health checks
- create-only UOM repackaging
- negative checks for invalid repackaging and unauthorized access
- regression checks for replenishment, transfer, donation, and procurement dependencies where Sprint 07 touches them

Out of scope:

- Sprint 08 or later workflow expansion
- reversal or void behavior beyond confirming it is absent
- dedicated repackaging reporting or export beyond confirming it is absent

## Execution Approach

Primary references used:

- `C:\Users\wbowe\OneDrive\Desktop\project\DMIS_UpdatedVersion\docs\requirements\sprint_07_logistics_masters_implementation_brief.md`
- `C:\Users\wbowe\OneDrive\Desktop\project\DMIS_UpdatedVersion\docs\requirements\qa_sprint_07_logistics_masters_thread_prompt.md`
- `C:\Users\wbowe\OneDrive\Desktop\project\DMIS_UpdatedVersion\docs\testing\sprint_07_release_train_foundation_user_test_script.md`

Validation method:

- targeted backend automated test execution
- targeted frontend Angular spec execution
- route/config inspection for shipped UI surface
- code-path review for repackaging, stock-health, location, and governed catalog behavior

## Pass/Fail By Scenario

| Scenario | Status | Notes |
| --- | --- | --- |
| Catalog foundations: item categories, IFRC families, IFRC item references | Pass with non-blocking issues | Backend and frontend coverage present; governed-catalog UX copy has drift in two Angular specs. |
| Item master setup and rules | Pass | IFRC linkage, local draft handling, FEFO/expiry alignment, reorder/min stock fields, and UOM option handling are covered. |
| Warehouse and agency operational masters | Pass | Warehouse hierarchy and agency-to-warehouse validation are covered; stock-health summary is exposed on warehouse flows. |
| Scoped location behavior | Pass with non-blocking issue | Scoped UI surface is limited to `location.config.ts`; assignment APIs and routing behavior pass. Supporting management command is missing. |
| Stock visibility | Pass | Inventory, item, and warehouse surfaces are routed and covered; touched read models passed in backend validation. |
| Stock-health baseline | Pass | Warehouse stock-health endpoints and dashboard behavior are covered and passed. |
| Valid create-only UOM repackaging | Fail | Backend create/list/detail behavior and invariants exist, but the required frontend user flow is missing. |
| Negative repackaging validation | Pass at backend/API level | Same-UOM, insufficient stock, invalid mapping, quantity-conservation, and scope checks are implemented in backend coverage. |
| Unauthorized access checks | Pass at backend/API level | Write/read scope and permission gating are covered in location and repackaging API tests. |
| Regression: replenishment dependencies | Pass | Relevant backend suites passed. |
| Regression: transfer dependencies | Pass | Relevant backend suites passed. |
| Regression: donation dependencies | Pass | Relevant backend suites passed. |
| Regression: procurement dependencies | Pass | Relevant backend suites passed. |

## Defects

### Blocking Defects

#### 1. Missing frontend UOM repackaging screen blocks the Sprint 07 user flow

- Severity: Blocker
- Impacted flow: Use Case 5 and related negative checks in the Sprint 07 user test script
- Expected:
  - inventory/logistics user can open a Sprint 07 repackaging page
  - user can preview and submit a create-only repackaging transaction
  - UI can be used for same-UOM rejection, insufficient-stock rejection, and unauthorized access checks
- Actual:
  - no Angular route or navigation entry for repackaging was found
  - backend endpoints exist, but the UI flow required by the test script is not exposed
- Reproduction steps:
  1. Open the Angular application from this worktree.
  2. Review the shipped routes and navigation.
  3. Attempt to find a `Repackaging` or `UOM Repackaging` screen under inventory/logistics.
  4. Attempt to locate a repackaging route in the frontend route configuration.
- Evidence:
  - backend route present in `backend/replenishment/urls.py`
  - backend handler present in `backend/replenishment/views.py`
  - no matching frontend route in `frontend/src/app/app.routes.ts`
  - no matching navigation item in `frontend/src/app/layout/sidenav/nav-config.ts`

### Non-Blocking Defects

#### 2. Missing `enforce_location_storage_policy` management command causes Sprint 07 support-tooling test failure

- Severity: Medium
- Impacted flow: supporting location-policy enforcement tooling, not the core end-user location assignment API
- Expected:
  - `enforce_location_storage_policy` command exists and the related test cases pass
- Actual:
  - command is missing from `backend/replenishment/management/commands`
  - corresponding backend tests fail with `Unknown command: 'enforce_location_storage_policy'`
- Reproduction steps:
  1. Run `backend/manage.py test replenishment.tests_location_assignment.EnforceLocationStoragePolicyCommandTests`.
  2. Observe the command lookup failure.
- Evidence:
  - missing command directory entry
  - failing tests in `backend/replenishment/tests_location_assignment.py`

#### 3. Governed catalog warning text contract is inconsistent between backend and frontend expectations

- Severity: Medium
- Impacted flow: governed IFRC family/reference edit gate guidance
- Expected:
  - governed warning text is consistent across API guidance, frontend dialog behavior, and frontend tests
- Actual:
  - backend emits older shorter warning text
  - frontend edit-gate service and spec expect richer Sprint 07 impact wording
  - Angular validation fails on the mismatch
- Reproduction steps:
  1. Review backend governed warning constants in `backend/masterdata/services/catalog_governance.py`.
  2. Review frontend edit-gate defaults in `frontend/src/app/master-data/services/master-edit-gate.service.ts`.
  3. Run the targeted Angular suite including `master-form-page.component.spec.ts`.
  4. Observe the failed assertion for impact wording.
- Evidence:
  - backend text: `catalog_governance.py`
  - frontend expected text: `master-edit-gate.service.ts`
  - failing test: `frontend/src/app/master-data/components/master-form-page/master-form-page.component.spec.ts`

#### 4. Governed catalog readiness helper text is incomplete for IFRC family suggestion gating

- Severity: Low
- Impacted flow: IFRC family suggestion guidance
- Expected:
  - readiness area includes the helper cue asserted by the Sprint 07 spec when prerequisites are missing
- Actual:
  - readiness string is shown, but the helper phrase `Fill these in first` is not rendered
  - Angular validation fails on the missing helper cue
- Reproduction steps:
  1. Open the IFRC Family create page.
  2. Leave `Family Label` empty.
  3. Review the suggestion CTA section.
  4. Run the targeted Angular suite and observe the failed assertion.
- Evidence:
  - readiness logic in `frontend/src/app/master-data/components/master-form-page/master-form-page.component.ts`
  - rendered CTA section in `frontend/src/app/master-data/components/master-form-page/master-form-page.component.html`
  - failing test in `frontend/src/app/master-data/components/master-form-page/master-form-page.component.spec.ts`

## Blockers Vs Non-Blocking Issues

### Blockers

- Missing frontend repackaging page prevents completion of the Sprint 07 user-script repackaging flow and its UI-level negative checks.

### Non-Blocking Issues

- Missing `enforce_location_storage_policy` support command
- Governed catalog warning-text contract drift
- Missing governed catalog helper cue text for suggestion readiness

## Evidence Captured

### Backend Automated Evidence

Targeted backend suites passed:

- `masterdata.tests.test_operational_masters`
- `masterdata.tests.test_item_master_phase1`
- `masterdata.tests.test_masterdata_core`
- `replenishment.tests_data_access_inbound`
- `replenishment.tests_procurement_guard`
- `replenishment.tests_repackaging`
- `replenishment.tests_location_assignment.LocationAssignmentApiTests`
- `replenishment.tests_location_assignment.LocationStorageRoutingTests`

Run results:

- Master-data and touched regression backend suites: `212/212` passed
- User-facing repackaging and location backend subset: `28/28` passed
- Full combined Sprint 07 backend run: `242` tests, `2` errors
  - both errors tied to the missing `enforce_location_storage_policy` command

### Frontend Automated Evidence

Targeted Angular validation run:

- Total: `73`
- Passed: `71`
- Failed: `2`

Failed frontend specs:

- governed edit warning dialog impact guidance
- IFRC family suggestion prerequisite helper text

### Static Validation Evidence

- Master-data route surface confirmed in `frontend/src/app/master-data/master-data.routes.ts`
- Scoped location UI surface confirmed in `frontend/src/app/master-data/models/table-configs/location.config.ts`
- Item master rules surface confirmed in `frontend/src/app/master-data/models/table-configs/item.config.ts`
- Warehouse hierarchy and threshold surface confirmed in `frontend/src/app/master-data/models/table-configs/warehouse.config.ts`
- Repackaging backend endpoints confirmed in `backend/replenishment/urls.py` and `backend/replenishment/views.py`
- Repackaging backend invariants confirmed in `backend/replenishment/services/repackaging.py`
- Frontend repackaging UI absence confirmed in `frontend/src/app/app.routes.ts` and `frontend/src/app/layout/sidenav/nav-config.ts`

## Environment Assumptions And Gaps

- The QA worktree is detached at the same commit as `codex/dmis-may15-release-train`; the branch itself is attached to the main project checkout.
- The worktree does not contain `docs/requirements`; Sprint 07 source documents were read from the main project checkout path provided in the request.
- No live environment credentials or seeded test accounts were provided, so this validation used automated suites and code-path validation instead of browser-based manual execution.
- No seeded live stock record was provided for end-to-end manual repackaging execution.
- Backend tests were executed in local SQLite test mode with:
  - `DJANGO_USE_SQLITE=1`
  - `DJANGO_ALLOW_SQLITE=1`
  - `DJANGO_DEBUG=1`
- Repackaging is intentionally unavailable in SQLite runtime mode and requires PostgreSQL for actual transaction execution.
- Frontend dependency resolution in the QA worktree required a temporary junction to the already-installed `node_modules` in the main checkout for Angular spec execution; that temporary junction was removed after validation.

## Recommendation

Sprint 07 should be treated as:

- functionally close on master-data, stock-health, scoped location, and touched regression foundations
- blocked for full sign-off until the repackaging UI flow required by the Sprint 07 script is exposed in the frontend

Recommended immediate actions:

1. Add or expose the Sprint 07 frontend repackaging screen and navigation entry.
2. Restore or add the `enforce_location_storage_policy` management command expected by the location-policy tests.
3. Align governed-catalog warning text between backend API guidance and frontend expectations.
4. Restore or intentionally revise the IFRC family suggestion CTA helper text and corresponding spec.
