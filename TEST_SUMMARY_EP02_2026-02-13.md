# EP-02 Test Summary (2026-02-13)

## Scope

Test summary for Supply Replenishment workflow validation across backend and frontend automated suites.

## Commands Executed

Backend:

```powershell
$env:DJANGO_USE_SQLITE='1'; $env:DJANGO_DEBUG='1'; .\.venv\Scripts\python.exe backend\manage.py test api replenishment
```

Frontend:

```powershell
npm test -- --watch=false --browsers=ChromeHeadless
```

## Results

- Backend: PASS
  - Ran: 54 tests
  - Passed: 53
  - Skipped: 1
- Frontend: FAIL
  - Total: 33
  - Passed: 26
  - Failed: 7

## Key Failure Details

All 7 frontend failures are in `ScopeStepComponent` tests and share the same root cause:

- `TypeError: this.replenishmentService.getActiveEvent is not a function`
- `TypeError: this.replenishmentService.getAllWarehouses is not a function`

The component now loads initial data using these methods, but the test mock only defines `getStockStatusMulti`.

## What Is Missing

- Frontend unit tests are not aligned with current service API usage in scope step.
- Automated UI coverage is still missing for approval action visibility and summary correctness per role.
- RBAC integration coverage with real DB role-permission mappings is missing (current tests rely mostly on dev-auth overrides).
- Postgres integration suite was not executed in this run (`tests_postgres.py` is conditional).
- End-to-end validation is missing for:
  - stale-data submit acknowledgement flow,
  - warehouse offline behavior,
  - supersede behavior,
  - audit trail completeness checks (who/what/when/why and before/after).

## Remaining Work

1. Update `scope-step.component.spec.ts` mocks to include `getActiveEvent` and `getAllWarehouses`.
2. Re-run frontend unit tests until all 33 pass.
3. Add/extend tests for review detail actions (Approve/Reject/Request Changes) by role and permission.
4. Run Postgres-backed tests (`DJANGO_USE_POSTGRES_TEST=1`) and capture outcomes.
5. Add end-to-end workflow tests for DRAFT -> SUBMITTED -> APPROVED/REJECTED/MODIFIED -> execution statuses.
6. Add audit trail assertions for all critical transitions.

## Notes

- Backend test logs include expected negative-path responses (400/403/409) that are currently validated by tests.
- Current status indicates backend workflow logic is broadly stable; primary blocker is frontend test drift and missing integration/e2e coverage.
