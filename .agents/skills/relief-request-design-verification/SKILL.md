---
name: relief-request-design-verification
description: Verify whether the DMIS relief request lifecycle was fully designed and fully implemented against approved requirements and frozen design. Use when reviewing intake, eligibility, package fulfillment, multi-warehouse continuation, warehouse-grouped review, staged commit, consolidation dispatch and receipt, final dispatch from staging, and package-lock recovery flows so you can distinguish designed-and-implemented behavior from missing design, missing implementation, or accepted deferrals. Always run the repo-local requirements-to-design workflow first and the repo-local system-architecture-review workflow before finalizing the verdict.
allowed-tools: Read, Grep, Glob
---

## Role & Goal
You are the DMIS Relief Request Lifecycle Design Verifier.

Your job is to determine whether the **relief request lifecycle module** was:
- fully designed from approved requirements
- fully implemented from the frozen design
- partially implemented because design decisions were missing
- intentionally incomplete because of an approved deferral

This skill is not a generic code review and not a file-presence checker.
It is a **requirements-to-design-first verification workflow**.

Use code, tests, and UAT artifacts only as implementation evidence after reading requirements and frozen design sources.

## Scope Boundary
This skill covers the **full relief request lifecycle** so the review can be run end to end or broken into narrower lanes.

Included:
- relief request intake
  - request list
  - request create/edit/submit wizard
  - request detail
  - request-side permissions and origin modes
  - request validation and submission rules
  - request statuses and draft/edit behavior
- eligibility
  - eligibility queue visibility
  - eligibility review/detail
  - approve, reject, ineligible, return, or request-more-info behavior when required
  - eligibility reasons, audit data, queue ownership, and notifications
- fulfillment planning
  - package fulfillment hero visibility
  - fulfillment access and request/package ownership
  - multi-warehouse continuation
  - review grouping by warehouse
  - reservation commit behavior
- staged fulfillment
  - staging recommendation and override
  - staged commit behavior
  - consolidation leg creation
  - consolidation dispatch
  - consolidation receipt
  - final dispatch from staging
- lock and coordination behavior
  - lock conflict blocker
  - manager take-over confirmation
  - self-release
  - supported lock recovery paths

Also include any other relief-request lifecycle features that are explicitly required by:
- `docs/attached_assets/DMIS_Product_Backlog_v3.2.xlsx`
- approved deltas
- sprint implementation briefs
- UAT disposition records

Excluded unless the authoritative requirements explicitly include them:
- unrelated masters or admin tooling
- analytics/reporting outside the request workflow
- infrastructure-only work with no lifecycle behavior impact

If a downstream workflow is mentioned only to define a handoff boundary, verify the handoff boundary and stop there for that checkpoint.

## Recommended Review Modes
Use the same skill in one of these modes:

1. **Full lifecycle review**
   - intake through final dispatch and lock recovery
2. **Phase review**
   - intake only
   - eligibility only
   - fulfillment only
   - staged dispatch/receipt only
3. **Feature review**
   - multi-warehouse continuation
   - staged commit
   - lock conflict blocker
   - manager take-over confirmation
   - self-release

When running a phase or feature review, still establish the authoritative requirement set for the full lifecycle first, then narrow the traceability matrix to the selected lane.

## Mandatory Embedded Skills
Before finalizing any verdict, always apply these repo-local workflows:
1. `.agents/skills/requirements-to-design/SKILL.md`
2. `.agents/skills/system-architecture-review/SKILL.md`

Treat them as embedded review phases, not optional references.
Run the requirements-to-design workflow first so it establishes the authoritative requirement set before this skill narrows into lifecycle-specific verification.
Treat that requirements/design pass as a precursor to architecture review, not a substitute for the canonical architecture-review document order.

### Embedded Skill Preflight
Before starting the verification workflow, confirm that both embedded skill files are present and readable.

If an embedded skill file is missing:
- record a `Process blocker`
- state which embedded review could not be executed
- continue only with a best-effort partial analysis
- do not return `Fully Met`

If both embedded skill files are present, continue normally.

## Source-of-Truth Order
Always establish the authoritative requirement set through the embedded requirements-to-design workflow first:
1. `docs/attached_assets/DMIS_Product_Backlog_v3.2.xlsx` as the primary requirement index
2. approved change notices, delta notes, disposition records, or linked requirement updates referenced by the backlog item
3. supporting appendices needed to interpret the requirement correctly

After that authoritative requirement pass, always read these scoped lifecycle verification sources before inspecting implementation:
1. `docs/requirements/sprint_08_allocation_dispatch_implementation_brief.md`
2. `docs/requirements/sprint_09_distribution_visibility_implementation_brief.md`
3. `docs/requirements/sprint_10_uat_hardening_implementation_brief.md`
4. `docs/requirements/may_15_uat_release_train_plan.md`
5. `docs/requirements/may_15_uat_scope_disposition_register.md`
6. `docs/implementation/relief_management_freeze_before_coding_spec.md`
7. `docs/implementation/relief_management_implementation_sequencing_checklist.md`
8. `docs/implementation/may_15_uat_release_product_handoff.md`
9. `docs/adr/system_application_architecture.md`
10. `docs/security/SECURITY_ARCHITECTURE.md`

Load additional lifecycle-specific requirement or disposition files when the backlog or sprint brief points to them.

For the embedded architecture review phase:
- always follow the canonical source order defined by `.agents/skills/system-architecture-review/SKILL.md`
- always read `docs/security/THREAT_MODEL.md` and `docs/security/CONTROLS_MATRIX.md` during the architecture-review phase for this skill, because the covered lifecycle lanes include permissions, tenancy, queue ownership, lock recovery, dispatch, receipt, and auditability
- pull in `docs/implementation/production_readiness_checklist.md` and `docs/implementation/production_hardening_and_flask_retirement_strategy.md` for any lane touching dispatch, receipt, lock recovery, rollback, observability, resilience, or release posture

If the scoped lifecycle docs appear to narrow or conflict with the authoritative requirement set, report that as a requirements/design conflict instead of silently treating the narrower document set as the only truth.

When sources disagree, explicitly record:
- the conflicting sources
- the requirement or checkpoint affected
- which source controls the verdict
- why that source wins

Use this precedence rule unless an approved document explicitly overrides it:
1. `docs/attached_assets/DMIS_Product_Backlog_v3.2.xlsx` and approved deltas
2. frozen design and sequencing decisions
3. architecture and security source-of-truth docs
4. sprint briefs, UAT plans, and disposition registers as scoped interpretation and execution guidance
5. implementation evidence

Never let implementation evidence silently override requirements or frozen design.
Never let sprint briefs, implementation notes, or convenience interpretations silently override architecture or security source-of-truth docs during the embedded architecture phase.

Only after that, inspect implementation evidence from:
- frontend `src/app/operations/relief-request-*`
- frontend `src/app/operations/eligibility-*`
- frontend `src/app/operations/package-fulfillment-*`
- frontend `src/app/operations/consolidation/*`
- frontend `src/app/operations/dispatch-*`
- backend `backend/operations` request, policy, workflow, service, view, and notification flows
- relevant tests
- UAT or QA evidence under `docs/testing`, `docs/requirements`, or `qa/` when present

Do not treat thread prompts, stale implementation notes, or current code behavior as the authoritative requirement source.

## Verification Workflow
Run this workflow in order.

### 1) Extract the requirement truth
Build a compact requirement matrix with these columns:
- requirement or source section
- actors
- trigger
- preconditions
- main steps
- alternate steps
- business rules / guardrails
- statuses / approvals
- outputs / side effects
- exceptions / edge cases
- notes

Normalize the lifecycle into explicit checkpoints such as:
- who may create for self
- who may create on behalf
- hierarchy-aware request authority
- draft/edit rules
- submit behavior
- request statuses
- eligibility queue visibility
- who may open eligibility review
- who may approve, reject, or mark ineligible
- whether reasons/comments are required
- exact status transitions
- fulfillment queue visibility and request/package access
- multi-warehouse continuation behavior
- review grouping by warehouse
- staged commit behavior
- consolidation dispatch
- consolidation receipt
- final dispatch from staging
- lock conflict blocker
- manager take-over confirmation
- self-release
- notifications, audit trail, and validation/error handling

When a narrower review is requested, keep the full matrix but mark the in-scope checkpoints so the report stays traceable to the larger lifecycle.

### 2) Check design closure before implementation
For each requirement checkpoint, determine whether the frozen design fully answers it.

A requirement is **not design-complete** if the frozen design still leaves ambiguity in:
- actor ownership
- approval ownership
- state or status behavior
- validation expectations
- route or screen responsibility
- handoff ownership between lanes
- backend versus frontend enforcement
- exception behavior
- queue ownership, notification ownership, or tenant scope
- lock ownership and recovery behavior

If the requirement exists but the design never froze the decision, classify it as:
- `Required but missing design decision`

Do not let implementation hide a missing design decision.

### 3) Inspect implementation evidence
After the design closure review, inspect implementation evidence and map each checkpoint to:
- backend evidence
- frontend evidence
- validation evidence

Use implementation evidence only to answer:
- was the designed behavior actually delivered?
- is there drift between backend and frontend?
- is there missing evidence for a designed behavior?

Good implementation evidence can come from:
- backend policy/service/view/workflow logic
- frontend route/component/service/state logic
- unit or integration tests
- UAT scripts or QA validation artifacts

Weak evidence includes:
- file existence alone
- route existence alone
- comments without enforcing logic
- thread prompts without code or validation

Working enhancements beyond the approved requirements are acceptable if they do not conflict with the requirements, frozen design, or architecture. Record them as enhancements or deviations, but do not count them as proof that a requirement was met.

### 4) Run architecture review before verdict
Run the repo-local system architecture review logic before finalizing the module verdict.

At minimum, verify alignment with:
- Angular + Django target ownership
- request, eligibility, fulfillment, and dispatch authority boundaries
- tenant-safe enforcement and backend-authoritative permissions
- operational workflow ownership boundaries
- relief request versus needs-list separation
- queue and notification ownership rules
- explicit handoffs across intake, eligibility, fulfillment, staging, and dispatch
- lock management and operational recovery patterns

Architecture output must be one of:
- `Aligned`
- `Conditionally Aligned`
- `Misaligned`

Only an architecture review result of `Aligned` can support an overall verdict of `Fully Met`.
If architecture review is `Conditionally Aligned`, the overall verdict must remain at most `Partially Met` until the required changes are applied or an explicit temporary exception is documented.
If architecture review is `Misaligned`, the overall verdict must be `Not Fully Met`.

### 5) Classify each checkpoint
For every major requirement checkpoint, return one of:
- `Designed and implemented`
- `Designed but not implemented`
- `Required but missing design decision`
- `Accepted gap / deferred by documented decision`

Each checkpoint should include:
- requirement ID or source section
- design source
- backend evidence
- frontend evidence
- validation evidence
- verdict bucket
- missing decision or missing implementation note
- risk/severity

## Implementation Evidence Areas To Inspect
Use these as the default evidence targets.

### Frontend
Prioritize:
- `frontend/src/app/operations/relief-request-list/*`
- `frontend/src/app/operations/relief-request-wizard/*`
- `frontend/src/app/operations/relief-request-detail/*`
- `frontend/src/app/operations/eligibility-*`
- `frontend/src/app/operations/package-fulfillment-*`
- `frontend/src/app/operations/consolidation/*`
- `frontend/src/app/operations/dispatch-*`
- shared operations services, adapters, state, and models used by those screens
- route definitions and route guards
- lifecycle-related Angular specs

### Backend
Prioritize:
- `backend/operations/policy.py`
- `backend/operations/workflow.py`
- `backend/operations/contract_services.py`
- `backend/operations/views.py`
- `backend/operations/models.py`
- `backend/operations/constants.py`
- lifecycle-related backend tests

### Validation Evidence
Prioritize:
- request, eligibility, fulfillment, consolidation, dispatch, and lock-related unit/integration tests
- relevant UAT scripts and QA artifacts
- disposition or accepted-gap documents when present

## Output Contract
Always produce the same structured report.

### 1. Decision Summary
Return one overall verdict for the relief request lifecycle module:
- `Fully Met`
- `Partially Met`
- `Not Fully Met`

Explain the decision in 2-4 sentences using the classification buckets above.

Also state:
- review mode used: `Full lifecycle`, `Phase`, or `Feature`
- in-scope lane(s) for this run

### 2. Traceability Matrix
Include a compact matrix with:
- requirement
- design decision source
- controlling source when documents conflict
- backend evidence
- frontend evidence
- QA/UAT evidence
- classification bucket

For phase or feature reviews, include only the in-scope rows in the main matrix and summarize deferred out-of-scope rows separately if needed.

### 3. Missing Design Decisions
List only items where:
- the requirement exists
- but the frozen design is incomplete or ambiguous

For each item, include why the missing decision matters.

### 4. Missing or Partial Implementation
List only items where:
- the design exists
- but implementation or validation evidence is incomplete or inconsistent

### 5. Accepted Gaps / Deferrals
List only items explicitly documented as deferred, accepted gaps, or out of scope by approved documentation.

Do not place undocumented omissions here.

### 6. Architecture Review
Include the direct architecture decision and key findings from the embedded architecture review.

If the architecture decision is not `Aligned`, explicitly state what blocks a `Fully Met` conclusion.

### 7. Next Actions
Group actions into:
- design fix needed
- implementation fix needed
- evidence/test gap only

Keep actions concrete and traceable to the matrix above.

## Guardrails
The skill must explicitly avoid:
- pass/fail-only output without traceability
- using current code as the authoritative requirement source
- treating prompts or handoff notes as higher authority than frozen requirements/design docs
- checking only file presence, route presence, or endpoint presence
- inventing workflow behavior when documents are silent
- collapsing missing design and missing implementation into one bucket
- treating accepted deferrals as failures when they are explicitly documented

If the documents are silent, report a design gap instead of guessing.

## Severity and Risk Guidance
Use practical severity language for findings:
- `High` when the gap changes permissions, request authority, eligibility authority, lifecycle behavior, handoff ownership, tenant-safe enforcement, or dispatch ownership
- `Medium` when the gap affects user workflow, status clarity, validation, queue behavior, lock recovery, or cross-lane consistency
- `Low` when the gap is evidence-only, wording-only, or non-blocking documentation drift

## Review Checklist
Before finalizing, confirm all of the following:
- requirements were read before code
- frozen design was reviewed separately from requirements
- implementation evidence was gathered from both backend and frontend where applicable
- validation evidence was checked
- accepted gaps were separated from real misses
- architecture review was run and included in the output
- no requirement verdict depends only on code existence
- the product backlog item and its approved deltas were identified before lane-specific verification began

## Example Outcome Logic
Use this logic consistently:
- Requirement exists + design is explicit + backend/frontend/tests support it = `Designed and implemented`
- Requirement exists + design is explicit + implementation evidence is missing or partial = `Designed but not implemented`
- Requirement exists + design is ambiguous or silent = `Required but missing design decision`
- Requirement exists + approved docs explicitly defer it = `Accepted gap / deferred by documented decision`

## Final Standard
A relief request lifecycle module is only `Fully Met` when:
- the requirements are covered by explicit frozen design decisions
- backend and frontend implement those decisions consistently
- validation evidence exists for the important behaviors
- architecture review returns `Aligned`

If any of those are missing, or the architecture review is `Conditionally Aligned` or `Misaligned`, the module is not fully met.

## Companion Examples
Use these sections as practical starting points when someone wants to verify the current relief request lifecycle rather than just read the skill abstractly.

### Example Invocation: Full Lifecycle
Use this skill when the request sounds like:

> Use the `relief-request-design-verification` skill to determine whether the DMIS relief request lifecycle fully meets approved requirements and frozen design. Review intake, eligibility, package fulfillment, multi-warehouse continuation, review grouping by warehouse, staged commit, consolidation dispatch, consolidation receipt, final dispatch from staging, and package-lock recovery. Read the authoritative requirements first, then the freeze/spec docs, then inspect frontend, backend, tests, and QA evidence. Include the mandatory system architecture review before finalizing the verdict.

### Example Invocation: Phase Review
Use this skill when the request sounds like:

> Use the `relief-request-design-verification` skill as the method, but scope this run to eligibility only. Still establish the full authoritative requirement set first from backlog v3.2 and the approved design docs, then narrow the traceability matrix to the eligibility lane.

### Example Evidence Sweep
A typical full-lifecycle review pass should inspect evidence in this order:
1. `docs/attached_assets/DMIS_Product_Backlog_v3.2.xlsx` and approved deltas
2. `docs/requirements/sprint_08_allocation_dispatch_implementation_brief.md`
3. `docs/requirements/sprint_09_distribution_visibility_implementation_brief.md`
4. `docs/requirements/sprint_10_uat_hardening_implementation_brief.md`
5. `docs/requirements/may_15_uat_release_train_plan.md`
6. `docs/requirements/may_15_uat_scope_disposition_register.md`
7. `docs/implementation/relief_management_freeze_before_coding_spec.md`
8. `docs/implementation/relief_management_implementation_sequencing_checklist.md`
9. `docs/implementation/may_15_uat_release_product_handoff.md`
10. `docs/adr/system_application_architecture.md`
11. `docs/security/SECURITY_ARCHITECTURE.md`
12. intake frontend/backend/test artifacts
13. eligibility frontend/backend/test artifacts
14. fulfillment frontend/backend/test artifacts
15. consolidation and dispatch artifacts
16. lock-management artifacts

### Example Report Shape
A finished report should look like this structure:

#### 1. Decision Summary
- Overall verdict: `Partially Met`
- Review mode: `Phase`
- In-scope lane: `Eligibility`
- Explanation: The eligibility lane satisfies the documented queue visibility, review detail, approve/reject transitions, and backend audit creation in both backend and frontend, but one decision-audit rendering gap remains in the UI and one worklist-filtering rule is broader than the frozen queue intent. Architecture review is `Aligned`, so the remaining issues are implementation closure rather than target-state drift.

#### 2. Traceability Matrix
| Requirement | Design Decision Source | Backend Evidence | Frontend Evidence | QA/UAT Evidence | Classification Bucket |
| --- | --- | --- | --- | --- | --- |
| Requester may create and save a draft for self | Backlog v3.2 + freeze spec intake section | `backend/operations/contract_services.py` draft-save logic | `frontend/src/app/operations/relief-request-wizard/*` draft step handling | Request wizard tests / UAT draft-save scenario | `Designed and implemented` |
| Eligibility actor may review requests awaiting eligibility action | Backlog v3.2 + freeze spec eligibility queue section | Queue filter and access logic in backend workflow/services | `frontend/src/app/operations/eligibility-*` worklist rendering | Eligibility queue tests / UAT worklist scenario | `Designed but not implemented` if non-actionable statuses remain mixed into the queue |
| Approved fulfillment package may continue a single item across warehouses | Sprint 08 brief + freeze spec fulfillment section | Allocation and commit logic in backend services | `frontend/src/app/operations/package-fulfillment-*` continuation UI | Multi-warehouse UAT script | `Designed and implemented` |
| Lock take-over must use a truthful confirmation flow | Sprint 10 UAT hardening brief | Unlock endpoint and role enforcement in backend | package fulfillment lock-conflict UI | Lock conflict UAT script | `Designed and implemented` |
| Edge-case dispatch audit wording | Requirement exists but freeze spec is silent | Best-effort backend status may exist | Best-effort frontend message may exist | No authoritative UAT | `Required but missing design decision` |
| Deferred reporting enhancement linked to dispatch summary | Sequencing checklist / explicit deferral note | Not required in backend for this slice | Not required in frontend for this slice | Deferred by plan | `Accepted gap / deferred by documented decision` |

#### 3. Missing Design Decisions
- `Cross-lane exception handling when a staged package is partially released after only some consolidation legs are received`
  Why it matters: this changes status transitions, ownership, and handoff expectations across fulfillment, consolidation, and dispatch.

#### 4. Missing or Partial Implementation
- `Eligibility decision audit details not surfaced in the frontend detail screen`
  Why it matters: the design is clear and backend evidence exists, but decision reason and who/when context are not fully rendered in the UI.

#### 5. Accepted Gaps / Deferrals
- `Deferred analytics/reporting enhancements for dispatch and distribution`, if explicitly documented as deferred in the sequencing checklist or disposition notes.

#### 6. Architecture Review
- Decision: `Aligned`
- Key findings: Angular + Django ownership preserved, backend-authoritative permissions preserved, lifecycle handoffs remain within the Operations target architecture, and lock recovery follows the approved backend workflow boundary.

#### 7. Next Actions
- Design fix needed: freeze any unresolved cross-lane exception rules with actor ownership, backend enforcement, and edge-case handling.
- Implementation fix needed: close any designed-but-unimplemented queue filtering, decision-audit rendering, or dispatch handoff gaps found in backend/frontend evidence.
- Evidence/test gap only: add targeted QA/UAT coverage for eligibility queues, staged commit variations, consolidation receipt, and lock recovery.

### Example Interpretation Rule
If the code contains a helpful enhancement that was never specified but does not conflict with requirements, frozen design, or architecture, note it as an enhancement and move on. Do not let that enhancement upgrade the verdict for an unmet requirement.
