# Current Task Plan

1. Verify every reported frontend/backend finding against the current code instead of assuming the comment context is still live.
2. Patch only the findings that remain valid:
   - warehouse allocation card quantity/expiry/input-step handling
   - relief request detail spec navigation assertion
   - staged-stock reservation before `READY_FOR_DISPATCH`
3. Leave stale/already-fixed comments untouched and note that verification in the final summary.
4. Run targeted frontend and backend tests for the touched areas.
5. Record any reusable lesson in `tasks/lessons.md` only if this pass surfaces one that is not already captured.
