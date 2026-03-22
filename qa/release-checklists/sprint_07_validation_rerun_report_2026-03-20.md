# Sprint 07 QA Validation Rerun Report

Date: 2026-03-20
Validated branch: `codex/dmis-may15-release-train`
Validated commit: `4821f9d51dbeaab5cb46a572f285e114d1c8838d`

## Summary

This rerun was executed against the Sprint 07 brief as the source of truth and focused only on the post-fix repackaging scope called out in the 2026-03-20 fix brief.

Current rerun outcome:

- frontend master-data form remediation is present in the current branch
- affected frontend validation/spec drift is cleared
- same-UOM, insufficient-stock, and unauthorized-access behavior remain covered and passing in targeted validation
- the local PostgreSQL runtime still does not contain a valid alternate-UOM repackaging fixture, so Use Case 5 could not be completed as a live create transaction through the browser
- Sprint 07 is therefore **not yet ready for sign-off** from this rerun alone

## Pass/Fail By Rerun Scenario

| Rerun scenario | Status | Notes |
| --- | --- | --- |
| Updated master-data form flow is exposed in the actual UI | Pass | The current branch serves the revised `MasterFormPageComponent` workflow locally; the earlier standalone repackaging route/component is not part of this branch’s frontend evidence. |
| Frontend validation/spec drift tied to the fix scope is cleared | Pass | Targeted Angular rerun is green for the affected master-data form and navigation coverage in the rerun scope. |
| Use Case 5 valid repackaging transaction end-to-end through the actual UI | Fail / blocked by runtime fixture | The live runtime database currently has `0` items with multiple active UOM options, so no valid alternate-UOM candidate exists for a real submit path. |
| Same-UOM rejection | Pass | Backend targeted repackaging coverage passed and the affected frontend validation/spec checks remain green for the rerun scope. |
| Insufficient-stock rejection | Pass | Backend targeted repackaging coverage passed and the affected frontend validation/spec checks remain green for rendered error handling. |
| Unauthorized repackaging access | Pass | Backend targeted permission coverage passed for protected location/repackaging paths; no new regression was found in the rerun scope. |
| Affected frontend validation/spec checks | Pass | Targeted Angular rerun completed `50/50` passing, including the governed warning/helper-text assertions and related master-data form coverage. |

## Sprint 07 Sign-Off Assessment

### Is the original Sprint 07 blocker cleared?

Yes, the specific frontend validation/spec blocker from the 2026-03-20 QA report is cleared in the current branch:

- the affected master-data form remediation is present in the served frontend
- the frontend validation/spec checks tied to the blocker now pass

### Is Sprint 07 now ready for sign-off?

No.

Reasons:

1. the rerun could not complete a live create transaction through the actual UI because the local PostgreSQL runtime does not currently contain a valid alternate-UOM repackaging fixture
2. `docs/implementation/sprint_07_logistics_masters_product_handoff.md` still records Sprint 07 as `Not ready - follow-on action required`
3. the Sprint 07 handoff still says the cross-module alignment artifact needs to be linked before Sprint 07 can be treated as closed

## Blockers Still Open

- actual-browser completion of Use Case 5 remains blocked in the local runtime by missing alternate-UOM fixture data
- Sprint 07 closeout/sign-off remains blocked by the still-open handoff/alignment readiness gate recorded in repo

## Non-Blocking Follow-Ons Still Open

- `enforce_location_storage_policy` is still unresolved
  - targeted user-facing/location-routing coverage passed
  - the full location-assignment test module still reports `2` errors because the management command is absent

## Non-Blocking Follow-Ons Cleared In This Rerun

- governed warning/helper-text alignment is no longer open in the affected frontend rerun scope
  - the targeted Angular rerun passed the previously failing governed warning dialog assertion
  - the targeted Angular rerun passed the IFRC helper cue assertion (`Fill these in first`)

## Evidence Captured

### Frontend/UI exposure evidence

- `frontend/src/app/master-data/components/master-form-page/master-form-page.component.ts` contains the revised wizard and validation flow covered by this rerun
- `frontend/src/app/master-data/components/master-form-page/master-form-page.component.html` contains the served UI changes covered by this rerun
- `frontend/src/app/master-data/components/master-form-page/master-form-page.component.scss` contains the corresponding visual/interaction updates
- local Angular runtime served:
  - `http://127.0.0.1:4200/` -> `200`

### Frontend automated evidence

- targeted Angular rerun:
  - command path: `frontend`
  - result: `50/50` passing
  - included scopes:
    - `master-form-page.component.spec.ts`
    - `master-detail-page.component.spec.ts`

### Backend automated evidence

- targeted backend rerun:
  - `replenishment.tests_repackaging`
  - `replenishment.tests_location_assignment.LocationAssignmentApiTests`
  - `replenishment.tests_location_assignment.LocationStorageRoutingTests`
  - result: `28/28` passing

- support-tooling follow-on verification:
  - full `replenishment.tests_location_assignment` module result: `30` tests, `2` errors
  - both errors remain tied to missing `enforce_location_storage_policy`

### Local runtime/data evidence

- local PostgreSQL-backed backend responded successfully to:
  - `/api/v1/health`
  - `/api/v1/auth/dev-users/`
  - `/api/v1/auth/whoami/`
  - `/api/v1/replenishment/warehouses`
  - `/api/v1/masterdata/items/lookup`

- database evidence for live repackaging fixture gap:
  - `public.item_uom_option` contains active UOM rows, but the count of items with more than one active UOM is `0`
  - this prevents a valid live create-only repackaging submission in the current runtime dataset

## Final Disposition

- Sprint 07 frontend master-data remediation blocker: `cleared`
- Sprint 07 overall sign-off readiness: `not ready`
- blocking reason from this rerun: `live actual-UI create transaction still blocked by runtime fixture gap, and repo handoff still records open closeout work`
