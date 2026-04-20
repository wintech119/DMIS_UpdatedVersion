# Backend Lessons Learned

## How To Use This File
- Capture durable backend lessons from real bugs, not one-off anecdotes.
- Prefer entries that document an invariant, the bad pattern that violated it, the good pattern to use instead, and the regression tests that must exist.
- When a new change touches an area with an existing lesson, mention that in the implementation closeout.

## Fulfillment Queue Tenant Misrouting

### Symptom
- An approved external relief request did not appear on the Package Fulfillment hero page for ODPEM logistics users even though the request had open fulfillment queue assignments.

### Concrete Example
- `RQ95009`

### Root Cause
- Fulfillment queue assignments were created under the external beneficiary tenant scope instead of the operational ODPEM fulfillment tenant scope.
- ODPEM logistics users were correctly filtered by their active tenant, so the queue item became invisible to the users who actually owned the work.

### Why The Bug Escaped
- The workflow logic used data origin (`beneficiary_tenant_id`) as a shortcut for operational ownership.
- Queue creation and queue visibility were both individually correct, but they were not validated together against the real fulfillment persona and tenant context.
- Tests did not originally assert that approved external requests become visible to ODPEM fulfillment users.

### Invariant
- Relief requests approved for fulfillment must route into the operational ODPEM fulfillment tenant scope, not the external requesting/beneficiary tenant scope, unless a requirement explicitly says fulfillment is owned by that external tenant.

### Correct Architectural Rule
- Queue routing must follow the tenant that owns the work, not simply the tenant that originated or benefits from the data.
- For ODPEM-owned fulfillment work, resolve the fulfillment queue tenant explicitly through a canonical helper rather than reusing request tenant fields inline.
- Request-level fulfillment work in the Package Fulfillment workspace, including approval entry and request-level override approval, belongs to the ODPEM fulfillment tenant.
- Downstream package execution queues such as dispatch, consolidation dispatch, staging receipt, pickup release, and receipt remain beneficiary-scoped unless a requirement explicitly reassigns that operational ownership.

### Code Smell To Watch For
- Inline queue routing like:
  - `tenant_id=request_record.beneficiary_tenant_id`
- Any fulfillment or dispatch routing decision that infers operational ownership from request origin without an explicit ownership rule.

### Regression Tests That Must Exist
- Approving an external request creates fulfillment queue assignments under the ODPEM fulfillment tenant.
- ODPEM fulfillment users can see approved external requests in Package Fulfillment.
- Fulfillment access checks succeed for correctly routed ODPEM-owned work and do not rely on external-tenant membership.
- Requester or beneficiary visibility is not unintentionally broadened by the fulfillment fix.
- Request-level override approval work is also routed into the ODPEM fulfillment tenant when it is surfaced in the Package Fulfillment workspace.
- Direct fulfillment package routing still creates downstream dispatch work under the beneficiary tenant.
- Staged fulfillment package routing still creates downstream consolidation and dispatch work under the beneficiary tenant.

### Reviewer Checklist
- Are queue assignments being created under the tenant that actually owns the work?
- Are we routing by operational ownership rather than data origin?
- Do role and tenant filters align with the real users who must see the queue?
- Is there a regression test for cross-tenant external-request routing into ODPEM fulfillment?
- If a canonical tenant resolver exists for this workflow, is the code using it instead of a request field shortcut?

### Bad Pattern
```python
create_role_notifications(
    queue_code=QUEUE_CODE_FULFILLMENT,
    entity_type=ENTITY_REQUEST,
    entity_id=request_id,
    role_codes=FULFILLMENT_ROLE_CODES,
    tenant_id=request_record.beneficiary_tenant_id,
)
```

### Good Pattern
```python
create_role_notifications(
    queue_code=QUEUE_CODE_FULFILLMENT,
    entity_type=ENTITY_REQUEST,
    entity_id=request_id,
    role_codes=FULFILLMENT_ROLE_CODES,
    tenant_id=resolve_odpem_fulfillment_tenant_id(),
)
```

### Closeout Expectation
- If a change touches fulfillment routing, tenant scoping, workflow queues, or operational ownership rules, mention this lesson in the closeout and confirm the relevant regression tests were run.

## Workflow-Safe Queue And Approval Signals

### Symptom
- Active fulfillment work disappeared from the Package Fulfillment queue when stale open assignments existed for already fulfilled requests.
- Override no-self-approval checks could rely on request or package creators instead of the user who actually submitted the override for review.

### Root Cause
- Queue selection applied the 200-row cap before filtering out rows that were no longer active fulfillment work.
- Override approval and rejection fallback logic used creator fields as a proxy for the override submitter even when workflow history contained a better signal.
- Override approval response assembly reused the legacy pre-transition result instead of rebuilding from the final post-review package state.
- Override approval also treated a review decision as physical fulfillment and advanced the request lifecycle too early.

### Invariant
- Workflow-sensitive queue limits must apply after status, authorization, and active-work filters.
- Workflow-sensitive approval guards must prefer persisted workflow actors such as execution links or status-history transitions over creator heuristics.
- Review-only approval decisions must not advance request fulfillment lifecycle state before downstream dispatch or receipt work occurs.
- Workflow responses and cached idempotent payloads must reflect the final persisted post-transition state, not an intermediate legacy result captured before downstream routing logic runs.

### Correct Architectural Rule
- Treat queue assignment rows and creator fields as hints, not authoritative workflow truth, when later workflow state can invalidate them.
- For fulfillment queues, only visible active-work rows should count toward list caps.
- For override review, use the recorded actor who moved the package into pending override approval when available, then fall back only when no stronger workflow signal exists.

### Regression Tests That Must Exist
- The fulfillment queue still returns active work when 200+ stale fulfilled assignments exist ahead of it.
- Override approval passes the actual pending-override submitter into downstream no-self-approval validation.
- Override rejection blocks self-approval for the actual pending-override submitter, not merely the request creator.
- Override approval keeps the request at `APPROVED_FOR_FULFILLMENT` until downstream dispatch or receipt transitions advance it.
- Staged override approval responses return `CONSOLIDATING`, `READY_FOR_PICKUP`, or `READY_FOR_DISPATCH` when those are the final package outcomes, and the response matches persisted package state.

### Closeout Expectation
- If a change touches fulfillment queue visibility, override approval, or override rejection, mention this lesson in the closeout and confirm the related regression tests were run.

## Frozen Outcome Semantics Must Match Workflow Labels

### Symptom
- An `override reject` endpoint reset the package back to `DRAFT`, cleared allocation lines, and reopened active fulfillment work even though the frozen design never defined that reject outcome.

### Root Cause
- The backlog required `Approve`, `Return for Adjustments`, and `Reject`, but the freeze only closed approval plus the existence of supervisor rejection.
- Implementation filled the missing design gap by reusing a draft-reset helper, which silently turned `reject` into an unfrozen return-for-adjustments path.

### Invariant
- Workflow action labels such as `reject`, `cancel`, and `return for adjustments` must map only to outcomes explicitly frozen in the design.

### Correct Architectural Rule
- When the freeze names an action but does not define the resulting state, queue, and audit outcome, backend behavior must narrow to a documented design-gap error rather than inventing a new state transition.
- Reusable helpers like allocation reset or cancel flows must not be reused under a different workflow label unless the frozen design explicitly equates those outcomes.

### Regression Tests That Must Exist
- Override rejection must not reset a package to `DRAFT` or reopen fulfillment work unless that exact outcome is frozen.
- Reject-route tests must not encode return-for-adjustments semantics under a successful `reject` response.

### Closeout Expectation
- If a change touches workflow outcomes whose labels appear in the freeze but whose state effects are incomplete, call out the design gap explicitly in the closeout instead of treating current code behavior as the requirement.

## Item Allocation Discovery Must Stay Item-Scoped

### Symptom
- Allocation discovery exposed a package-level `source_warehouse_id` contract that could outrank the true FEFO/FIFO warehouse for a specific item and could present continuation warehouses in quantity order instead of item-rule order.

### Root Cause
- The backend already had item-level FEFO/FIFO ranking internally, but the public contract still treated a shared package/source warehouse as the main selector and reduced continuation to a secondary convenience list.
- Draft reload logic and continuation previews then had to infer rank from mixed fields instead of one canonical item-scoped warehouse list.

### Invariant
- Package allocation discovery is item-scoped: the canonical warehouse order must be computed per item from FEFO/FIFO applicability before any default or continuation selection is exposed.

### Correct Architectural Rule
- Treat `warehouse_cards` as the authoritative ranked warehouse contract for an item, and derive recommendation, continuation, and draft rehydration from that rank order.
- Package-level or request-level source warehouse fields may survive only as convenience aliases or downstream summaries; they must not be the authority for multi-warehouse item selection.
- For continuation-only warehouses that are loaded outside the aggregate stock list, placeholder labels must stay fallback-only; authoritative warehouse metadata should come from the batch candidates when available.

### Regression Tests That Must Exist
- Package options recommend different rank-0 warehouses for different items when FEFO/FIFO rules differ.
- Continuation warehouses follow the same ranked FEFO/FIFO order exposed in `warehouse_cards`, not quantity-first order.
- Draft-aware previews that pull in additional selected warehouses preserve pre-draft batch visibility while still computing suggestions from allocatable quantities.
- Continuation-only warehouses loaded through `additional_warehouse_ids` preserve the real warehouse name from batch metadata instead of surfacing a synthetic placeholder label.

### Closeout Expectation
- If a change touches allocation discovery, continuation, or draft warehouse rehydration, mention this lesson in the closeout and confirm the ranked-warehouse regression tests were run.

## Allocation Enforcement Must Reuse The Ranked Item Contract

### Symptom
- Save-time FEFO/FIFO enforcement could be bypassed by submitting only a caller-chosen warehouse subset, and execution-linked package options could still return the old compat bootstrap shape instead of the ranked item contract.

### Root Cause
- The backend had already frozen `warehouse_cards` as the canonical per-item ranking contract, but commit-time validation still derived its comparison set from selected/default warehouses and the execution-link package options branch still short-circuited into the needs-list compat payload.

### Invariant
- The backend must evaluate allocation compliance against the full per-item ranked warehouse universe, not only the warehouses the caller selected.

### Correct Architectural Rule
- Save-time override detection and approval-required logic must reuse the same FEFO/FIFO-ranked item universe that powers item allocation discovery, so omitting a better-ranked warehouse cannot bypass `allocation_order_override`.
- Execution-linked package options may enrich the ranked response with compatibility metadata, but they must not downgrade item groups back to the old compat-only allocation shape.

### Regression Tests That Must Exist
- Submitting only a lower-ranked warehouse while a better-ranked warehouse still has stock triggers `allocation_order_override`.
- Ranked multi-warehouse continuation remains compliant.
- Intentional partial fulfillment remains compliant when the submitted rows follow rank order and simply stop early.
- Execution-linked package options expose `warehouse_cards`, recommendation metadata, shortfall, and continuation fields just like non-execution-linked requests.

### Closeout Expectation
- If a change touches allocation enforcement or execution-linked package allocation options, mention this lesson in the closeout and confirm the ranked-allocation enforcement regressions were run.

## Staged Fulfillment Actions Need Dual Workflow Evidence

### Symptom
- Consolidation leg dispatch/receipt, pickup release, and partial-release actions could update lifecycle state without writing `operations_action_audit`, and partial-release request/approval evidence lived only on mutable package fields.

### Root Cause
- The package fulfillment closure work treated `operations_status_history` as sufficient lifecycle evidence for staged actions, even though the freeze requires both lifecycle history and immutable operational action evidence for staged/consolidation workflows.
- Partial-release request state was stored directly on `OperationsPackage`, which made the request/approval transaction less explicit than the frozen `operations_partial_release_request` workflow record.

### Invariant
- Frozen staged, consolidation, override, and partial-release actions that materially change workflow state must write both `operations_status_history` and `operations_action_audit`.
- Partial-release request and approval transactions must be reconstructable from `operations_partial_release_request`; package split lineage remains authoritative through `OperationsPackage.split_from_package`.

### Correct Architectural Rule
- Use `operations_status_history` for lifecycle transitions and `operations_action_audit` for immutable action evidence; do not substitute one ledger for the other.
- Keep package compatibility fields in sync only as convenience state. The partial-release request row is the workflow evidence for request, approval, and released/residual child references.

### Regression Tests That Must Exist
- Consolidation leg dispatch and receipt each write a status-history row and a matching action-audit row.
- Pickup release completion writes package status history and a pickup release action-audit row.
- Partial-release request creates a pending workflow row, writes consolidation-status history, and writes action audit.
- Partial-release approval updates the workflow row with approved metadata and released/residual child package ids, and failed split approval leaves child references unset.

### Closeout Expectation
- If a change touches staged fulfillment, consolidation, pickup release, or partial release, mention this lesson in the closeout and confirm the dual-ledger and partial-release workflow-record regressions were run.
