# Relief Management Implementation Sequencing Checklist

Last updated: 2026-04-25
Status: Execution baseline after freeze; updated for EP-05 module-by-module sequencing (Module 1 closure deliverables, Module 4 Phase 2 prerequisites)
Scope: Relief Management implementation order across backend, frontend, and QA

## Purpose

Turn the frozen Relief Management business rules into a practical execution sequence so coding starts in the correct order and each lane hands off a stable contract to the next.

This checklist must be used together with:

- `docs/implementation/relief_management_freeze_before_coding_spec.md`
- `docs/implementation/odpem_operational_procurement_context_note.md`

## Implementation Order

```text
Phase 0 -> Freeze complete
Phase 1 -> Backend first
Phase 2 -> Frontend second
Phase 3 -> QA third
Phase 4 -> Release and handoff alignment
```

## Phase 0 | Freeze Confirmation

Do not start new implementation work until these are confirmed:

- [x] tenant hierarchy and request-authority rules are frozen
- [x] lower-level tenant needs-list rules are frozen
- [x] status transition model is frozen
- [x] notification event model is frozen
- [x] Operations-native permission target is frozen
- [x] target Operations schema baseline is frozen
- [x] dispatch is frozen as a transport-aware workflow
- [x] stock timing rules are frozen and unchanged

## Phase 1 | Backend First

### Entry criteria

- Freeze spec approved as the implementation baseline
- No unresolved contradiction remains on request authority, roles, or stock timing

### Goal

Publish the real Operations backend contract before frontend work proceeds.

### Must finish in backend

- [ ] Implement hierarchy-aware request authority validation
- [ ] Support request creation modes:
  - [ ] self
  - [ ] for subordinate entity
  - [ ] ODPEM bridge on behalf
- [ ] Preserve lower-level tenant needs-list support and constrained downstream usage
- [ ] Introduce or formalize Operations-native status vocabulary
- [ ] Implement exact role gating for:
  - [ ] eligibility approval
  - [ ] fulfillment
  - [ ] dispatch
- [ ] Implement internal workflow notification generation
- [ ] Implement queue-assignment creation for workflow handoffs
- [ ] Make dispatch transport-aware in the backend contract
- [ ] Promote these to first-class Operations ownership:
  - [ ] package lock
  - [ ] waybill artifact
  - [ ] receipt artifact
  - [ ] Operations-native permissions
- [ ] Keep current stock reservation and deduction timing unchanged
- [ ] Module 1 closure deliverables (per freeze spec §3a, §6a, §7a, §"Status Transition Matrix" Cancel row, §"Operations-Native Permission Matrix"):
  - [ ] Cancel relief request endpoint (`POST /api/v1/operations/requests/{id}/cancel`) with `operations.request.cancel` permission, idempotency-key required, `Workflow` rate-limit tier, status_history + action_audit writes, queue cleanup, notification fan-out, cancellation_reason validation
  - [ ] Cross-tenant negative tests on `PATCH /requests/{id}` and `POST /requests/{id}/submit`
  - [ ] Apply-from-needs-list authority pre-check endpoint (`GET /api/v1/operations/requests/authority-preview?source_needs_list_id={id}`) returning `{can_create, allowed_origin_modes, required_authority_tenant_id, beneficiary_tenant_id, beneficiary_agency_id, suggested_event_id, blocked_reason_code}`; `Read` rate-limit tier
  - [ ] Audit timeline read contract on `GET /api/v1/operations/requests/{id}` exposing combined status_history + action_audit per freeze spec §7a, with cross-tenant role-name redaction
- [ ] Module 4 prerequisites (Phase 2, per freeze spec "Damaged stock disposition rules" and "Variance-based partial release rules"):
  - [ ] Damaged stock disposition schema: `operations_damaged_stock_case`, `operations_damaged_stock_evidence`, `operations_damaged_stock_inventory_state`
  - [ ] Damaged stock disposition endpoints (case create on receipt, inspect, attach evidence, submit for approval, approve/reject, apply disposition, queue list, escalation scheduler)
  - [ ] New permissions: `operations.damaged_stock.inspect`, `operations.damaged_stock.attach_evidence`, `operations.damaged_stock.approve_disposition`, `operations.partial_release.request_variance`, `operations.partial_release.approve_variance`
  - [ ] Damaged inventory state must not be available for package reservation, dispatch, pickup release, allocation, or stock-availability calculations
  - [ ] Variance-based partial release endpoint with `request_kind_code='VARIANCE'`, three-actor record (requester / approver / release executor), no-self-approval enforcement, damaged-stock case linkage where damage drives the variance
  - [ ] Idempotency on damaged-stock disposition approval and on variance partial-release approval
  - [ ] Notification fan-out for damaged stock recorded, overdue, disposition approved/rejected, variance partial release requested/approved

### Backend contract must be stable for frontend

- [ ] Request create/edit/detail contract finalized
- [ ] Eligibility queue/detail/decision contract finalized
- [ ] Package queue/detail/allocation/override contract finalized
  - [ ] FR05.08 override review outcomes frozen for approve / return for adjustments / reject, including package state, reservation effect, queue routing, and audit expectations
- [ ] Dispatch queue/detail/handoff/waybill contract finalized
- [ ] Receipt confirmation contract finalized or explicitly stubbed with frozen shape
- [ ] Notification / queue payload shape finalized

### Backend no-go conditions

Do not hand off to frontend if any of these are still unresolved:

- [ ] unclear request-authority behavior by tenant type
- [ ] missing eligibility role enforcement
- [ ] dispatch still modeled as stock-only without transport fields
- [ ] package lock still undefined as a first-class concept
- [ ] waybill / receipt still only ad hoc compatibility behavior without defined target contract
- [ ] frontend would need to invent unsupported APIs

### Required backend handoff outputs

- [ ] API contract summary
- [ ] request-authority and tenancy summary
- [ ] status model summary
- [ ] notification event and queue-assignment summary
- [ ] dispatch transport summary
- [ ] exact schema changes or staged migration plan
- [ ] blocker list for frontend if any remain

## Phase 2 | Frontend Second

### Entry criteria

- Backend contract is published and stable
- Request authority, statuses, and transport requirements are frozen in the backend

### Goal

Build the live Angular Operations path on top of the frozen backend contract and approved workflow model.

### Must finish in frontend

- [ ] Reflect request authority modes in the Relief Request UI:
  - [ ] self
  - [ ] for subordinate entity
  - [ ] ODPEM bridge on behalf
- [ ] Module 1 frontend closure deliverables (per freeze spec §3a, §6a, §7a):
  - [ ] Add `source_needs_list_id?: number | null` to `CreateRequestPayload` and `UpdateRequestPayload` and carry through wizard route state and submit
  - [ ] New apply-from-needs-list bridge route + component calling the authority pre-check endpoint; block navigation when `can_create=false`
  - [ ] Render `request_mode` (SELF / FOR_SUBORDINATE / ODPEM_BRIDGE) on the relief-request list as a column or badge
  - [ ] Hide unavailable modes in the wizard per actor permissions; auto-render single-mode label when only one mode is allowed; show creation-blocked panel only when zero modes are allowed
  - [ ] Render the audit timeline on the relief-request detail screen per freeze spec §7a, including bridge intake and cancel events
- [ ] Keep request create/edit name-first:
  - [ ] agency by name
  - [ ] event by name
  - [ ] request date display-only
- [ ] Preserve lower-level needs-list creation behavior
- [ ] Limit needs-list downstream actions to:
  - [ ] apply for relief request
  - [ ] donation export
  - [ ] donation broadcast
- [ ] Build role-correct queues and screens for:
  - [ ] eligibility
  - [ ] package fulfillment
  - [ ] override review with approve / return / reject on one manager review surface
  - [ ] dispatch
  - [ ] receipt confirmation
- [ ] Show notifications and next-action tasks in the UI
- [ ] Make dispatch screens transport-aware
- [ ] Present waybill and receipt as first-class workflow artifacts
- [ ] Remove any remaining live ownership confusion between Replenishment and Operations

### Frontend no-go conditions

Do not hand off to QA if any of these remain:

- [ ] lower-level tenant UI still implies direct self-request where not allowed
- [ ] needs-list still exposes fulfillment ownership
- [ ] dispatch screen still behaves like a plain stock-movement form
- [ ] queue transitions are invisible or misleading
- [ ] role-specific screens are not aligned to the frozen role matrix
- [ ] transport, waybill, or receipt states are unclear to users

### Required frontend handoff outputs

- [ ] route inventory
- [ ] page-to-persona map
- [ ] multi-step form reuse note
- [ ] request authority UX note
- [ ] notification/task-center UX note
- [ ] screenshots or walkthrough notes
- [ ] known limitations for QA focus

## Phase 3 | QA Third

### Entry criteria

- Backend and frontend contracts are both in place
- Roles, statuses, and notifications are visible enough to test

### Goal

Validate the frozen model end to end and confirm no implementation lane drifted away from the agreed rules.

### Must finish in QA

- [ ] Validate tenant hierarchy request authority
- [ ] Validate lower-level tenant needs-list behavior
- [ ] Validate Parish request creation for subordinate entity
- [ ] Validate ODPEM bridge restrictions
- [ ] Validate exact eligibility approver roles
- [ ] Validate fulfillment role gating
- [ ] Validate dispatch role gating
- [ ] Validate stock reserve on commit
- [ ] Validate stock deduction on dispatch only
- [ ] Validate no stock deduction on receipt
- [ ] Validate transport fields in dispatch workflow
- [ ] Validate notification generation and queue transitions
- [ ] Validate waybill artifact behavior
- [ ] Validate receipt artifact behavior
- [ ] Validate Replenishment / Operations boundary separation

### QA no-go conditions

Do not sign off for release progression if any of these remain:

- [ ] request authority outcomes are inconsistent by tenant type
- [ ] workflow notifications do not reliably generate the next queue item
- [ ] dispatch transport details are missing or optional where required
- [ ] stock behavior changed from the frozen timing model
- [ ] waybill or receipt artifacts are missing from required workflow states
- [ ] user-facing ownership is still confused between Needs Lists and Relief Requests

### Required QA outputs

- [ ] authority matrix test evidence
- [ ] role-gating evidence
- [ ] stock-timing evidence
- [ ] notification/queue evidence
- [ ] transport/dispatch evidence
- [ ] waybill/receipt artifact evidence
- [ ] blocker vs follow-up defect split

## Phase 4 | Release and Handoff Alignment

### Must be updated after QA passes

- [ ] product handoff
- [ ] UAT release train plan
- [ ] scope disposition register
- [ ] sprint brief
- [ ] backend/frontend/QA thread prompts for any next sprint carry-over
- [ ] Notion sprint/work-item state if requested

## Cross-Lane Non-Negotiables

These rules apply in every lane:

- [ ] Do not move fulfillment ownership back under Needs Lists
- [ ] Do not change stock timing behavior
- [ ] Do not treat ODPEM bridge behavior as the permanent ownership model
- [ ] Do not collapse dispatch into a stock-only transaction
- [ ] Do not keep using old permission language as the long-term Operations model
- [ ] Do not leave package lock, waybill, or receipt as vague compatibility-only concepts
- [ ] Do not begin Module 4 (Consolidation / Staged Fulfillment) implementation work that touches damaged-stock disposition or variance-based partial release until the matching freeze-spec sections ("Damaged stock disposition rules" and "Variance-based partial release rules") are merged into the canonical worktree freeze spec; Codex worktrees must be rebased before implementation

## Recommended Immediate Next Execution

The next active working order should be:

1. backend implementation thread against the frozen request-authority, status, notification, and schema model
2. frontend implementation thread against the published backend contract
3. QA thread against the frozen business rules and cutover path

## Short Readout

```text
Backend first:
  make the rules real

Frontend second:
  make the workflow usable

QA third:
  prove the workflow matches the rules
```
