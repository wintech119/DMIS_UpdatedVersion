# Current Task Plan

## Advanced/System Master Data Brief #6 - Frontend Many-to-Many Assignments - 2026-04-28

Risk score: 7 / Medium using the architecture-review handoff rubric.
Axes: blast radius 1, data sensitivity 1, authority change 2, reversibility 1, external surface 1, operational impact 1.

1. Completed: read the approved Brief #6 handoff, generation.ts sections 1-4, the Brief #6 design appendix, frontend implementation skill, and architecture/security review references.
2. Completed: inspect existing master-data components, services, routes, models, and backend assignment endpoint contracts before adding new assignment files.
3. Completed: implement the IAM assignment service and four standalone, OnPush, signal-IO assignment components.
4. Completed: embed the panels into the flat-table detail pages and add the tenant-user roles logical deep-link route.
5. Completed: run lint, build, tests, visual grep checks, and architecture-review closeout. Pending after commit: Playwright visual verification.

## Advanced/System Master Data Brief #1 - JWT User Auto-Provision - 2026-04-27

Risk score: 8 / Medium-High using the architecture-review handoff rubric.
Axes: blast radius 2, data sensitivity 2, authority change 1, reversibility 1, external surface 1, operational impact 1.

1. Completed: read the approved handoff brief, backend auth/test patterns, schema constraints, and architecture/security references.
2. Completed: added first-login DB user auto-provisioning to the JWT success path without changing local-harness behavior.
3. Completed: added focused tests for first-login insert, idempotent existing-user behavior, and `AUTH_USE_DB_RBAC=0` no-write behavior.
4. Completed: ran targeted Django checks/tests and completed the post-implementation architecture review.

## Worktree and Branch Cleanup - 2026-04-26

1. In progress: inventory local worktrees, branch tracking state, and dirty files before cleanup.
2. Pending: classify stale detached worktrees, attached worktrees, and local branches by safety to remove.
3. Pending: remove only unused clean worktrees/branches and prune git worktree metadata.
4. Pending: verify the final worktree and branch state after cleanup.

## EP-05 Module 1 Relief Request Intake Closure - 2026-04-25

Risk score: 8 / Medium using the architecture-review handoff rubric.
Axes: blast radius 2, data sensitivity 1, authority change 2, reversibility 1, external surface 1, operational impact 1.

1. Completed: created fresh worktree `codex/ep05-module1-closure-gpt55`, copied the gitignored `generation.ts` visual reference, and read the required plan, freeze spec, checklist, and backend/frontend skill workflows.
2. Completed: implemented backend cancel, authority-preview, audit timeline, permission, and IDOR regression coverage using existing function-based DRF and operations service patterns.
3. Completed: implemented frontend model/service contracts, apply-from-needs-list bridge route/component, wizard bridge-state ingestion, and detail audit timeline rendering without visual polish.
4. Completed: ran required Django and Angular verification gates; manual smoke behavior is covered by automated backend/frontend probes in this worktree.
5. Completed: ran architecture-review checkpoint 2 on the resulting diff and closed required changes with test/check evidence.

## Branch Cleanup

1. Completed: refreshed remote-tracking refs with `git fetch --prune origin`.
2. Completed: classified local branches by merge status, upstream state, worktree usage, and recency.
3. Completed: deleted confirmed merged/stale local branches after approval.
4. Completed: verified `prototype-supply-replenishment` had no open PRs and deleted the merged stale remote branch after approval.

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

## Allocation Review Comment Verification Sweep

1. Completed: verified each cited backend and frontend finding against the current code before changing behavior.
2. Completed: patched only the findings that still reproduced, preserving current frontend layout and style.
3. Completed: ran focused Django and Angular tests for the changed paths.
4. Completed: completed backend, frontend, and architecture review closeout before final response.

## Frontend Lint Cleanup

1. Completed: inspected the reported lint sites and local frontend guidance.
2. Completed: patched only TypeScript lint violations without visual layout changes.
3. Completed: ran targeted frontend lint verification.
4. Completed: completed frontend and architecture review sanity checks.

## Package Fulfillment Residual Cap Fix

1. Completed: traced the max-quantity clamp from the fulfillment item detail component into the warehouse allocation card.
2. Completed: patched the parent cap to use residual `remaining_qty` instead of original `request_qty`, preserving the active card's editable allocation.
3. Completed: added focused regression coverage in the existing fulfillment item detail spec.
4. Completed: ran the targeted Angular spec and completed the architecture-review closeout.

## Review Comment Verification Sweep - 2026-04-22

1. Completed: verified each cited backend and frontend finding against the current code before editing; stale findings were identified for the phase-window dialog caller, warehouse-card CTA propagation, moved override-routing test code, and allocation-card zero max coverage.
2. Completed: patched confirmed backend authorization, validation, allocation comparison, and phase-window policy/view issues.
3. Completed: patched confirmed frontend auth failure handling, live-region placement, idempotency-key retry support, metric filter validation, and stale warning visibility without visual redesign.
4. Completed: ran focused Django and Angular tests, the production Angular build, and completed backend/frontend architecture-review closeout.

## Review Comment Verification Sweep - 2026-04-23

## django-ai-boost MCP Server Cleanup

1. Completed: identified duplicate Codex MCP aliases and repo-local launcher files for `django-ai-boost`.
2. Completed: confirmed the local backend venv has `django-ai-boost==0.8.0` and the MCP-only requirements pin now matches it.
3. Completed: updated the MCP-only requirements pin and launcher dependency guard while keeping the server installed.
4. Completed: cleaned up the duplicate Codex MCP alias and verified TOML parsing plus a short launcher startup smoke.

1. Completed: verified each cited backend and frontend finding against the current code before editing.
2. Completed: patched only backend service, view, and test findings that still reproduced.
3. Completed: applied only non-visual frontend fixes needed for idempotency headers and lint-safe SCSS syntax/spacing; visual frontend comments were left untouched per instruction.
4. Completed: ran targeted Django and Angular verification, then completed architecture-review closeout.

## Review Comment Verification Sweep - 2026-04-23 (Follow-up)

1. Completed: re-verified the newly cited backend and frontend review findings against the current tree and identified which comments were already stale versus still actionable.
2. Completed: applied only the remaining non-visual fix in the shared operations metric strip and added regression coverage in the task-center spec.
3. Completed: ran focused Django and Angular verification for the rechecked areas and completed the architecture-review closeout.

## Review Comment Verification Sweep - 2026-04-23 (Architecture / No-Visual Pass)

1. Completed: re-verified the newly cited backend and frontend findings against the live tree, classifying them as already fixed, stale, or still actionable under the no-frontend-visual-change constraint.
2. Completed: applied the remaining backend control fixes and only non-visual frontend behavior, accessibility, idempotency, error-handling, and lint updates that still reproduced.
3. Completed: ran focused Django and Angular verification where the local environment supports it, added direct replenishment smoke checks for the blocked module surfaces, and completed the architecture-alignment closeout against the canonical docs.

## Review Comment Verification Sweep - 2026-04-25

1. Completed: verified each cited backend and frontend finding against the current code before editing.
2. Completed: patched only confirmed backend service/test gaps, preserving tenant-scope enforcement.

## Review Comment Verification Sweep - 2026-04-26

Risk score: 4 / Low-Medium using the architecture-review handoff rubric.
Axes: blast radius 1, data sensitivity 1, authority change 1, reversibility 0, external surface 0, operational impact 1.

1. Completed: verified each cited skill-doc, backend, frontend, and CI finding against the current tree before editing.
2. Completed: patched only confirmed gaps while preserving backend authorization enforcement and avoiding visual layout/style changes.
3. Completed: ran focused Django, Angular, markdown-reference, and diff verification.
4. Completed: completed post-implementation backend/frontend and architecture-review closeout.

## Advanced/System Master Data Brief #2 - 2026-04-27

Risk score: 9 / High-by-brief using the architecture-review handoff. Axes: blast radius 2, data sensitivity 2, authority change 2, reversibility 1, external surface 1, operational impact 1.

1. Completed: read the implementation brief, backend implementation skill, backend guidance, and targeted architecture/security controls.
2. Completed: inspect current RBAC, masterdata permission, validation, registry, schema, and test patterns before editing.
3. Completed: add advanced permission constants, seed migration, flat advanced `TableConfig` entries, permission routing, and focused tests.
4. Completed: run migration and targeted advanced masterdata verification; full masterdata suite was attempted and hit pre-existing baseline failures after rerun with `--keepdb`.
5. Completed: completed post-implementation architecture review and report per the brief.

## Advanced/System Master Data Brief #3 - 2026-04-27

Risk score: 9 / Medium using the architecture-review handoff. Axes: blast radius 2, data sensitivity 2, authority change 2, reversibility 1, external surface 1, operational impact 1.

1. Completed: verified prerequisite commits `8c27857` and `6a6ad5e1` on the current branch, read the Brief #3 handoff, backend implementation skill, backend guidance, and architecture/security controls.
2. Completed: inspected current masterdata views, permissions, throttling, URL routing, schema, and test patterns; duplicate search found no existing IAM junction endpoint/service helper.
3. Completed: add advanced junction raw-SQL helpers, views, URL routes, and focused tests.
4. Completed: ran compile, Django check, migration check, focused advanced tests, attempted exact full masterdata suite, reran preserved-DB suite, and completed post-implementation architecture review.
