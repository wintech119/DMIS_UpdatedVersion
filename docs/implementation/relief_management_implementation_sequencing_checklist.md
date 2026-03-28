# Relief Management Implementation Sequencing Checklist

Last updated: 2026-03-26
Status: Execution baseline after freeze
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

### Backend contract must be stable for frontend

- [ ] Request create/edit/detail contract finalized
- [ ] Eligibility queue/detail/decision contract finalized
- [ ] Package queue/detail/allocation/override contract finalized
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
