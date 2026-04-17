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

### Invariant
- Workflow-sensitive queue limits must apply after status, authorization, and active-work filters.
- Workflow-sensitive approval guards must prefer persisted workflow actors such as execution links or status-history transitions over creator heuristics.

### Correct Architectural Rule
- Treat queue assignment rows and creator fields as hints, not authoritative workflow truth, when later workflow state can invalidate them.
- For fulfillment queues, only visible active-work rows should count toward list caps.
- For override review, use the recorded actor who moved the package into pending override approval when available, then fall back only when no stronger workflow signal exists.

### Regression Tests That Must Exist
- The fulfillment queue still returns active work when 200+ stale fulfilled assignments exist ahead of it.
- Override approval passes the actual pending-override submitter into downstream no-self-approval validation.
- Override rejection blocks self-approval for the actual pending-override submitter, not merely the request creator.

### Closeout Expectation
- If a change touches fulfillment queue visibility, override approval, or override rejection, mention this lesson in the closeout and confirm the related regression tests were run.
