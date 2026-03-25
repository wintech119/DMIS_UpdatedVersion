# Sprint 08 Operations Cutover Notes

This app is the first Django-owned `/api/v1/operations/*` slice for the May 15 cutover.

What it replaces:
- Flask relief request list/detail/create/update/submit
- Flask eligibility queue/detail/decision
- Flask package fulfillment queue/detail and first package write contracts
- Flask dispatch queue/detail/handoff and waybill readback

What stays compatibility-only:
- `replenishment` `needs-list/*` execution endpoints remain frozen transitional wrappers.
- When a request/package already has a `NeedsListExecutionLink`, Operations reuses that compatibility bridge so the existing reservation, audit, and waybill persistence logic is not duplicated.

Known temporary cutover dependencies:
- Direct Operations requests can be created and reviewed in Django without `needs_list`.
- Allocation/dispatch parity is strongest when the request/package is linked through `NeedsListExecutionLink`.
- For direct Operations requests without a planning link, allocation and dispatch run on the legacy request/package tables, but waybill JSON persistence is not yet backed by a dedicated Operations table.

Remaining blockers before full Flask retirement:
- Angular Operations still needs to switch its request, eligibility, package, and dispatch screens to these Django routes.
- Dedicated Operations RBAC permissions are not introduced here; this slice temporarily reuses existing Django permissions to avoid a broad approval/RBAC redesign during Sprint 08.
- Full request/package locking parity with the old Flask fulfillment lock table still needs a dedicated Django ownership surface if Angular requires explicit lock acquisition UX.
