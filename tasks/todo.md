# Current Task Plan

1. Leave the `backend/operations/views.py` request-body comments untouched because the live code already routes request bodies through `_payload_object()` and rejects non-object JSON before `draft_save` or boolean flag access.
2. Fix the verified frontend mismatch in `frontend/src/app/operations/package-fulfillment-queue/package-fulfillment-queue.component.ts` so `isReady()` treats legacy `package_status === 'P'` rows the same way as `getFulfillmentStage()`, while still honoring pending-override behavior.
3. Update the verified regression tests in `backend/operations/tests_relief_request_policy.py` and `frontend/src/app/operations/package-fulfillment-workspace/package-fulfillment-workspace.component.spec.ts`:
   - assert pending-override saves keep package headers in `PKG_STATUS_DRAFT`
   - replace the private `collectDetailErrors()` test call with the public `goToReview()` flow
   - seed and clear `store.lockConflict` in the force-release lock test
4. Do not apply the stale `fulfillment-details-step.component.ts` comments because the referenced `onStagingApplied` / duplicate `reliefrqstId()` code path does not exist in the current component.
5. Run targeted backend and frontend tests for the touched files, then record any reusable lesson in `tasks/lessons.md`.
