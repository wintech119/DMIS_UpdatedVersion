# Current Task Plan

## EP02 Backend Workflow Review Fixes

1. Completed: fixed remaining workflow review findings around supersede scoping, downstream draft durability, approval failure semantics, and regression coverage.
2. Completed: reran focused replenishment workflow tests and the broader workflow API class.
3. In progress: complete backend/architecture review closeout and summarize the stable API contract changes.

## EP02 Backend Workflow Persistence

1. Completed: read Product Backlog v3.2 rows FR02.83-FR02.85, FR02.90-FR02.98, and FR02.100-FR02.101 plus the EP02 Codex review.
2. Completed: confirmed the current live view path already imports `workflow_store_db` and that the legacy JSON workflow store file is absent from this checkout.
3. Completed: aligned DB-backed needs-list persistence with the backlog status vocabulary and preserved preview payload fields in persisted records.
4. Completed: updated schema/migration contract and focused backend tests for status, supersede, approval separation, and payload preservation.
5. Completed: ran Python compilation and Django system checks; the focused Django suite is blocked by missing legacy `parish` table setup in the local test database, so that blocker is documented for closeout.

## ODPEM HQ Harness Alignment

1. Completed: traced `RQ95010` through eligibility approval, queue assignment, and notification fan-out to confirm the request was approved and routed into the HQ fulfillment lane.
2. Completed: aligned the local-harness ODPEM national personas with the same explicit `ODPEM_TENANT_ID` used by request-level fulfillment routing, and updated the local harness docs/example accordingly.
3. Completed: ran targeted backend tests and reseeded the local-harness users so the Logistics Manager and Officer operate in the HQ tenant context locally.
4. Completed: verified the repaired local state against `RQ95010` and captured the tenant-alignment lesson in `tasks/lessons.md`.

1. Completed: verified the new test/auth and lessons wording comments against the current contract-service tests and task notes.
2. Completed: applied the still-valid fixes in `backend/operations/tests_contract_services.py` and `tasks/lessons.md`.
3. Completed: ran targeted backend tests for the class-level auth override and the eligibility cross-tenant idempotency regression.
4. Completed: finished the backend and architecture review pass, calling out which comments were already stale; audit artifact: [relief_request_wizard_frontend_architecture_review_2026-04-17.md](../docs/reviews/relief_request_wizard_frontend_architecture_review_2026-04-17.md). Mandatory review coverage included tenancy/RBAC boundaries, backend-authoritative input-validation parity, legacy request-mode compatibility, and audit-trail/documentation updates. PR description should reference the same artifact.

## Consolidation Requirements Task Plan

1. In progress: collect authoritative repo-local consolidation and staging sources across requirements docs, operations backend, and operations frontend.
2. Pending: extract the confirmed workflow, actors, statuses, controls, and edge cases for staging warehouse and consolidation flows.
3. Pending: provide a requirements-oriented summary that separates documented/implemented behavior from best-practice recommendations and open gaps.

## Fulfillment Queue Override-Rejection Fix

1. Completed: aligned the package-fulfillment queue stage filter with the backend contract for override-rejected package attempts.
2. Completed: updated the queue spec coverage so rejected package attempts stay visible while dispatched and received rows remain excluded.
3. Completed: ran the targeted Angular package-fulfillment queue spec and the shared operations service spec.

## Review Comment Verification Sweep

1. Completed: verified each cited frontend/backend review finding against the current code and the listed source-of-truth docs before making any edits.
2. Completed: applied only the findings that still reproduced in the current implementation, keeping frontend and backend behavior aligned with the relief-management contract.
3. Completed: ran targeted Angular and Django tests for every changed area and completed the architecture-review closeout against the checked docs.

## Relief Request Idempotency Header Fix

1. Completed: audited the operations frontend service against backend idempotency-required endpoints to identify every relief-request workflow action missing `Idempotency-Key`.
2. Completed: patched the shared operations API service so all affected workflow actions emit idempotency headers without per-button duplication.
3. Completed: extended targeted Angular service specs to cover each affected endpoint and ran the focused frontend test suite.

## Eligibility Decision 404 Fix

1. Completed: traced the live `RQ95011` eligibility-decision 404 through backend request scope enforcement and local-harness actor context, confirming the request exists and the masked 404 only reproduces for the system-admin write path.
2. Completed: patched the backend request access helper so `SYSTEM_ADMINISTRATOR` write flows stay aligned with the existing eligibility read/admin behavior.
3. Completed: added a targeted backend regression test for the helper-level cross-tenant system-admin request access path and ran the focused operations test slice.
