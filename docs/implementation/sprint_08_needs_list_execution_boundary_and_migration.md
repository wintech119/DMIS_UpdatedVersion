# Sprint 08 | Needs List Execution Boundary and Migration

Last updated: 2026-04-15  
Status: Historical correction baseline - superseded for current deployment guidance

Historical note:
This note records the Sprint 08 boundary correction used during the May 15 cutover window. It is not current deployment guidance. DMIS-10 later fully removed the legacy Flask runtime and rollback gate from the repo.

## Purpose

This note is the durable historical source for the Sprint 08 boundary correction. It explains the cutover-era misbuild, the corrected product boundary, and the implementation sequence that was used to move Operations off Flask before May 15.

## Correct Domain Language

| Object | Correct Meaning |
| --- | --- |
| `NeedsList` | Replenishment planning snapshot and approval artifact |
| `ReliefRqst` | Operational demand plus eligibility workflow |
| `ReliefPkg` | Package allocation, dispatch, and receipt aggregate |
| `Transfer` | Replenishment execution output from an approved needs list |
| `Procurement` | Replenishment execution output from an approved needs list |

## Historical Sprint 08 Problem

During Sprint 08, the repo already had useful replenishment planning work in Django and Angular, but parts of allocation and dispatch were attached to `needs_list` and the live Operations user path still depended on Flask.

That was not the approved end state for May 15.

## Target State

### Replenishment

Owns only:

- stock dashboard
- needs-list drafts, review, and approval
- sourcing outputs for transfer, donation, and procurement

### Operations

Owns:

- relief request creation and tracking
- eligibility review
- package fulfillment and allocation
- dispatch and receipt preparation

Target runtime shape:

- Angular routes under `/operations/*`
- Django APIs under `/api/v1/operations/*`
- request and package contracts keyed by `reliefrqst_id` and `reliefpkg_id`, not `needs_list_id`

## Historical Execution Sequence

1. source-of-truth correction across briefs, prompts, migration notes, and release docs
2. backend first: build the Django Operations domain and freeze further `needs_list` execution expansion
3. frontend second: build Angular Operations routes and screens and move shell navigation off Flask during the cutover
4. QA third: validate parity, regressions, and Flask retirement from the live user path

## Route Rules

Canonical replenishment detail route:

- `/replenishment/needs-list/:id/review`

Routes to remove from the live replenishment journey:

- `/replenishment/needs-list/:id/track`
- `/replenishment/needs-list/:id/allocation`
- `/replenishment/needs-list/:id/dispatch`
- `/replenishment/needs-list/:id/history`
- `/replenishment/needs-list/:id/superseded`

Target Operations routes:

- `/operations/dashboard`
- `/operations/relief-requests`
- `/operations/eligibility-review`
- `/operations/package-fulfillment`
- `/operations/dispatch`

## Historical Compatibility and Retirement Rule

- existing `needs_list` execution endpoints remain frozen as transitional compatibility code only
- legacy redirects for removed replenishment execution routes may remain for bookmarks, but active UI navigation must target `/replenishment/needs-list/:id/review` directly
- existing Angular allocation and dispatch components may remain as migration reference until the true Operations module exists
- temporary shell links back to Flask could exist during the historical build window, but May 15 signoff required the live user path to stop depending on them
- no new UI contract may be built on top of `needs_list` execution APIs

## Stock and Lifecycle Rules

- needs-list approval does not deduct stock
- stock is reserved on formal allocation or package commitment
- stock is deducted on dispatch only
- distribution confirmation later must not re-deduct source stock
- override approvals remain narrow: reason code plus supervisor approval, with no self-approval

## Historical May 15 Readiness Rule

The historical release was valid only if:

- replenishment planning remains stable on Django and Angular
- Operations is rebuilt on Django and Angular with the required parity evidence
- the live user path no longer depends on Flask Operations by default
- the cutover and retirement checklist in `docs/implementation/sprint_08_operations_cutover_and_flask_retirement.md` is complete or explicitly marks any still-open item as a temporary historical cutover exception
