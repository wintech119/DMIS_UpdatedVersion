# Relief Management Freeze Before Coding Specification

Last updated: 2026-04-17
Status: Pre-implementation freeze baseline with approved consolidation and staged fulfillment additions from backlog v3.2
Scope: Relief Request, Eligibility Review, Package Fulfillment, Consolidation and Staged Fulfillment, Dispatch, Receipt, Notifications, Tenancy, and target Operations data ownership

## Purpose

This document freezes the clarified business rules, workflow, permissions, and target data model for the Relief Management module before further implementation work proceeds.

It exists to prevent additional coding against unstable assumptions, especially around:

- tenant hierarchy and request authority
- lower-level tenant behavior
- needs-list usage boundaries
- role-based workflow ownership
- notification expectations
- dispatch as a transport workflow
- first-class Operations data ownership

## Source Alignment

This freeze preserves the existing Relief Request and logistics model unless explicitly overridden by:

- the clarified rules captured during the March 26, 2026 product freeze session
- the approved consolidation and staged fulfillment additions now captured in Product Backlog v3.2 EP05 FR05.22-FR05.65 / FR-CON-01 through FR-CON-44

Related planning notes:

- `docs/attached_assets/DMIS_Product_Backlog_v3.2.xlsx` (EP05 FR05.22-FR05.65 / FR-CON-01 through FR-CON-44)
- `docs/requirements/sprint_08_allocation_dispatch_implementation_brief.md`
- `docs/requirements/sprint_09_distribution_visibility_implementation_brief.md`
- `docs/requirements/sprint_10_uat_hardening_implementation_brief.md`
- `docs/implementation/sprint_08_needs_list_execution_boundary_and_migration.md`
- `docs/implementation/sprint_08_operations_cutover_and_flask_retirement.md`
- `docs/implementation/odpem_operational_procurement_context_note.md`

## Preserved Baseline

These decisions remain unchanged:

- `NeedsList` is a planning and sourcing artifact, not a fulfillment-execution artifact
- `ReliefRqst` is the formal operational request
- `ReliefPkg` is the fulfillment and dispatch execution unit
- stock is not changed on request creation
- stock is not changed on eligibility approval
- stock is reserved on package commit
- stock is deducted on each physical outbound movement
- stock is not deducted again on receipt
- staged fulfillment uses the same timing principle:
  - reserve stock on package commit
  - deduct from the source warehouse when a consolidation leg is dispatched
  - post stock into the staging warehouse on staging receipt
  - deduct staged stock again only when it physically leaves the staging hub through final dispatch or pickup release

## Domain Boundary

Freeze this language:

| Object | Meaning |
| --- | --- |
| `NeedsList` | Planning / sourcing artifact used to express needs and launch approved downstream actions |
| `ReliefRqst` | Formal operational request for assistance |
| `ReliefPkg` | Package allocation / dispatch execution unit |
| `Transfer` | Replenishment execution output from approved planning |
| `Donation Export / Broadcast` | Needs-list-driven downstream sourcing actions |

## Clarified Business Rule Overrides

The following rules override any earlier simplified assumptions:

### Relief request creation rules

- lower-level and community tenants that report to a Parish-level tenant cannot create relief requests for themselves
- in those cases, the Parish-level tenant creates the relief request on their behalf
- all other tenants may create relief requests for themselves, provided they do not report to a higher-level tenant that is responsible for making requests for them
- a requesting agency may create a request only for:
  - itself
  - an entity or agency under its control
- ODPEM on-behalf request creation remains a transitional bridge and not the permanent ownership model

### Needs-list rules for lower-level tenants

- lower-level tenants must be able to create needs lists
- high-level and national ODPEM needs-list behavior must remain unchanged unless explicitly revised later
- a needs list may only be used for:
  - applying for a relief request from ODPEM
  - exporting for donation purposes
  - broadcasting as a request for donation to other tenants in the system

### Workflow and notification rules

- the system must generate internal workflow notifications when workflow tasks are completed
- when eligibility is approved, the relevant fulfillment roles must be notified and work must appear in their queue
- internal workflow notifications are in scope and must be treated separately from the narrower external receiving-agency dispatch notification discussion

### Approval and fulfillment role rules

- eligibility approval roles:
  - Deputy DG
  - Director of PEOD
  - DG
- fulfillment roles:
  - Logistics Officer
  - Logistics Manager
- dispatch roles:
  - Inventory Clerk
  - Logistics Officer
  - Logistics Manager

### Dispatch and transport rules

- dispatch must not be modeled as only a stock movement
- dispatch must record transport details where transport is involved
- transport details must include:
  - driver
  - vehicle
  - relevant transport information
- dispatch design must support future extension into last-mile delivery to the beneficiary, including beneficiary delivery and receipt information

### Consolidation and staged fulfillment rules

- the canonical stored/API fulfillment mode codes for staged work are:
  - `DIRECT` with user-facing label `Direct`
  - `PICKUP_AT_STAGING` with user-facing label `Pickup at Staging Hub`
  - `DELIVER_FROM_STAGING` with user-facing label `Deliver from Staging Hub`
- freeze rule:
  - prose may use the human-readable staging-hub labels for clarity
  - schema fields, status matrices, API contracts, and implementation planning must use the canonical stored/API codes above
- a package in either staged fulfillment mode must not be committed without a selected staging warehouse
- selectable staging warehouses must be restricted to active ODPEM-owned staging hubs
- the system should recommend a staging hub from beneficiary geography and must display the recommendation basis when a recommendation exists
- an authorized actor may override the recommended staging hub, but the override reason must be captured
- committing a staged package must create a consolidation plan
- the consolidation plan must create one leg for each source warehouse with allocated stock that is different from the selected staging hub
- no consolidation leg may be created for allocated stock already located in the selected staging hub
- each consolidation leg must record:
  - package reference
  - source warehouse
  - staging warehouse
  - allocated items and quantities
  - lifecycle status
  - audit metadata
- consolidation leg lifecycle statuses must include at least:
  - `PLANNED`
  - `IN_TRANSIT`
  - `RECEIVED_AT_STAGING`
  - `CANCELLED`
- consolidation legs may be rebuilt only while every leg remains in `PLANNED`
- transport details are required before a consolidation leg can be dispatched
- dispatching a consolidation leg must:
  - create a shadow transfer record
  - deduct stock from the source warehouse
  - generate a unique inbound waybill artifact
  - place the leg into a staging receipt queue
- receiving a consolidation leg at staging must:
  - capture receiver identity, receipt timestamp, notes, and receipt artifact
  - capture line-level variances for shortages, overages, and damages
  - post received stock into the staging warehouse
  - reserve that staged stock to the originating package
- package-level consolidation statuses must include at least:
  - `AWAITING_LEGS`
  - `LEGS_IN_TRANSIT`
  - `PARTIALLY_RECEIVED`
  - `ALL_RECEIVED`
  - `PARTIAL_RELEASE_REQUESTED`
- package-level consolidation status must update automatically from the current states of the package's consolidation legs
- if all allocated stock is already available at the selected staging hub, the system must bypass consolidation leg creation and move the package directly to the next staged-ready state
- a fully staged `PICKUP_AT_STAGING` package must transition to `READY_FOR_PICKUP`
- a fully staged `DELIVER_FROM_STAGING` package must transition to `READY_FOR_DISPATCH`
- for `DELIVER_FROM_STAGING`, the staging warehouse becomes the effective source for final dispatch and final dispatch stock lines must be remapped to staged stock before dispatch can occur
- pickup release may occur only when the package is in `READY_FOR_PICKUP`
- pickup release must capture:
  - collector identity
  - releasing actor
  - release timestamp
  - release evidence
- completing pickup release must consume the reserved staged stock
- partial release may be requested only when some, but not all, required consolidation legs have been received at staging
- partial release requests require a reason and an authorized approval before any release proceeds
- approving a partial release must split the package into:
  - a released child package using only stock already received at staging
  - a residual child package that remains in consolidation
- partial-release lineage source of truth must be explicit:
  - `operations_package.split_parent_package_id` is the authoritative package-lineage graph
  - `operations_partial_release_request` is the immutable workflow record for request, approval, and split outcome
  - `operations_partial_release_request.released_child_package_id` and `operations_partial_release_request.residual_child_package_id` may duplicate the resulting child package ids for audit convenience only and must not replace package-lineage authority
- the system must provide a consolidation workspace showing the package, staging hub, consolidation status, legs, leg statuses, pending actions, and staged artifacts
- the system must enforce step-specific permissions for:
  - staging hub selection
  - staging hub override
  - leg dispatch
  - leg receipt
  - partial release request
  - partial release approval
  - pickup release
  - final dispatch from staging
- idempotency protection is required for:
  - consolidation leg dispatch
  - consolidation leg receipt
  - pickup release
  - partial release approval
- the system must maintain an immutable audit trail for consolidation actions including actor, tenant, package, leg, warehouse, timestamp, action, reason, and artifact reference
- users must not be able to view or act on consolidation packages, legs, or artifacts outside their authorized tenant and role scope
- invalid status transitions and duplicate processing must be blocked for all consolidation, staging receipt, pickup release, and staged dispatch actions

### Staged audit write contract

- `operations_status_history` is authoritative for lifecycle status transitions
- `operations_action_audit` is authoritative for immutable operational action evidence on staged/consolidation workflow actions
- when an action both changes status and represents a material staged/consolidation operation, both records must be written
- for this staged/consolidation slice, the following actions must write both `operations_status_history` and `operations_action_audit`:
  - staged override approval when it changes the package out of `PENDING_OVERRIDE_APPROVAL`
  - consolidation leg dispatch
  - consolidation leg receipt
  - pickup release completion
  - partial release request
  - partial release approval
- `operations_partial_release_request` remains the workflow record for the request/approval transaction, but it does not replace either audit table
- actions that create immutable artifacts without changing lifecycle status may write `operations_action_audit` only
- status-only transitions outside staged/consolidation operations may write `operations_status_history` without `operations_action_audit`

### First-class database ownership rules

These must become first-class database concepts:

- package lock
- fulfillment mode and staging warehouse selection
- consolidation plan and consolidation leg
- consolidation action audit trail
- staging receipt artifact
- pickup release artifact
- partial release lineage and split-child relationships
- waybill artifact
- receipt artifact
- clean operations status model
- operations-native permissions

## Tenant Hierarchy and Request Authority Model

### Conceptual hierarchy

```text
NATIONAL TENANT
  ODPEM
    |
    +-- PARISH TENANT
    |     Parish Council / Parish Operations
    |       |
    |       +-- LOWER-LEVEL / COMMUNITY TENANT
    |       |     Community entity / local operator
    |       |
    |       +-- SHELTER / SUBORDINATE OPERATING UNIT
    |
    +-- OTHER DIRECT TENANTS
          NGO / PARTNER / MILITARY / SHELTER_OPERATOR / UTILITY
```

### Request authority truth table

| Tenant condition | Can create Needs List | Can create Relief Request for self | Can create Relief Request for subordinate entity | Can create on behalf | Frozen rule |
| --- | --- | --- | --- | --- | --- |
| Lower-level/community tenant that reports to a Parish request-authority tenant | Yes | No | No | No | Must escalate through Parish |
| Shelter/subordinate operating unit under Parish request authority | Yes | No | No | No | Must escalate through Parish |
| Parish tenant designated as request authority | Yes | Yes | Yes | Yes, for entities under control | May request for self or subordinate entity it controls |
| Independent operational tenant with no higher request-authority parent | Yes, if replenishment-enabled | Yes | Yes, only for entities under control | No | Self-service allowed |
| ODPEM / national bridge actor | Existing ODPEM needs-list behavior unchanged | No, not through this lane as steady state | No, unless explicit control rule exists | Yes, transitional only | ODPEM on-behalf is policy-gated bridge behavior |
| Any tenant attempting to request for unrelated or out-of-scope entity | Possibly | No | No | No | Must be rejected by backend |

### Frozen request-authority rule

```text
A tenant may create a Relief Request only for:
1. itself, or
2. an entity or agency under its control.

If a lower-level tenant reports to a higher-level request-authority tenant,
the lower-level tenant cannot create the Relief Request for itself.
```

## Personas and Tenant Context

| Persona | Main action | Typical tenant context |
| --- | --- | --- |
| Lower-level/community operator | Create needs list | Lower-level/community tenant |
| Shelter/subordinate operating unit operator | Create needs list | Subordinate operating unit |
| Parish request operator | Create request for self or subordinate entity | Parish-level tenant |
| Direct operational tenant requester | Create request for self | NGO / Partner / direct operational tenant |
| ODPEM bridge operator | Transitional on-behalf request creation | National / ODPEM |
| Deputy DG | Eligibility approval | National / high-level |
| Director of PEOD | Eligibility approval | National / high-level |
| DG | Eligibility approval | National / high-level |
| Logistics Officer | Fulfillment and dispatch | Operations / logistics |
| Logistics Manager | Fulfillment, dispatch, override governance | Operations / logistics |
| Inventory Clerk | Dispatch | Warehouse / logistics |
| Receiver / downstream actor | Confirm receipt | Receiving tenant / agency |

## End-to-End Workflow

```text
LOWER-LEVEL TENANT
  -> Needs List
  -> Apply for Relief Request

REQUEST-AUTHORITY TENANT
  -> Relief Request create / submit

ELIGIBILITY APPROVER
  -> Review and approve / reject

FULFILLMENT TEAM
  -> Build package
  -> Select fulfillment mode
  -> Reserve stock

CONSOLIDATION TEAM (staged modes only)
  -> Create consolidation plan
  -> Dispatch source legs to staging
  -> Receive legs at staging
  -> Ready package for pickup or final dispatch

DISPATCH / PICKUP TEAM
  -> Direct dispatch, final dispatch from staging, or pickup release
  -> Deduct stock when goods physically leave the warehouse or staging hub
  -> Generate waybill or pickup-release artifact

RECEIVER
  -> Confirm receipt
```

## Page-by-Page Workflow Script

### Supply Replenishment

#### 1. Needs List Create

Route:

- `/replenishment/needs-list/new`

Primary personas:

- lower-level/community operator
- shelter/subordinate operating unit operator
- Parish operator
- ODPEM planner

Page must:

- allow lower-level tenants to create needs lists
- preserve existing ODPEM/high-level needs-list behavior
- remain a planning screen only

Page must not:

- allocate stock
- dispatch stock
- act as a fulfillment workspace

#### 2. Needs List Review

Route:

- `/replenishment/needs-list/:id/review`

Page must:

- show planning artifact summary
- support only these next actions:
  - apply for relief request
  - donation export
  - donation broadcast

Page must not:

- expose allocation or dispatch as active workflow ownership

#### 3. Apply for Relief Request from Needs List

Route:

- `/replenishment/needs-list/:id/apply-relief-request`

Page must:

- show needs-list summary
- determine who has request authority
- launch Relief Request creation only when current tenant is authorized
- otherwise show which higher-level tenant must create the request

### Operations

#### 4. Operations Dashboard

Route:

- `/operations/dashboard`

Page must:

- act as an operational command center
- show queue counts, notifications, and urgent work
- route users to the correct queue or task

#### 5. Relief Request Queue

Route:

- `/operations/relief-requests`

Page must:

- list requests visible to the active tenant or user
- clearly show request mode:
  - self
  - for subordinate entity
  - ODPEM bridge on behalf

#### 6. Relief Request Create Wizard

Route:

- `/operations/relief-requests/new`

Page must:

- use a multi-step flow
- select agency by name
- select event by name
- show request date as backend-generated
- clearly show request mode
- capture items, urgency, and justification

Page must not:

- require raw Agency ID or Event ID entry
- allow unauthorized lower-level tenant request creation

#### 7. Relief Request Detail

Route:

- `/operations/relief-requests/:id`

Page must:

- show request summary, tenant context, item lines, audit timeline, and related package state
- support draft edit only if still allowed by status and authority

#### 8. Eligibility Review Queue

Route:

- `/operations/eligibility-review`

Page must:

- show only requests awaiting eligibility action
- be visible as a work queue only to authorized eligibility approvers

#### 9. Eligibility Review Detail

Route:

- `/operations/eligibility-review/:id`

Page must:

- allow only Deputy DG, Director of PEOD, or DG to decide
- support approve, reject, or ineligible decision paths
- capture reason where required
- trigger downstream fulfillment tasking on approval

#### 10. Package Fulfillment Queue

Route:

- `/operations/package-fulfillment`

Page must:

- list requests ready for package work
- show lock state, override state, and readiness

#### 11. Package Fulfillment Workspace

Route:

- `/operations/package-fulfillment/:reliefrqst_id`

Page must:

- show request context
- present allocation options
- enforce FEFO / FIFO recommendation
- support override flow where needed
- support fulfillment mode selection of direct or staged modes
- require staging warehouse selection before staged commit
- restrict staging selection to active ODPEM-owned staging hubs
- show staging recommendation basis when a recommendation exists
- require override reason when staging recommendation is overridden
- reserve stock on commit
- use multi-step workflow for clarity

#### 11A. Consolidation Workspace

Route:

- `/operations/consolidation/:reliefpkg_id`

Page must:

- show package context, selected staging hub, fulfillment mode, and package-level consolidation status
- show one consolidation leg for each source warehouse with allocated stock that differs from the selected staging hub
- not show a synthetic leg for stock already at the staging hub
- surface pending actions for leg dispatch, leg receipt, partial release, pickup release, or final dispatch
- expose leg and package artifact links where allowed by role

#### 11B. Consolidation Leg Dispatch / Detail

Route:

- `/operations/consolidation/:reliefpkg_id/leg/:leg_id`

Page must:

- show source warehouse, staging warehouse, item lines, quantities, and current leg status
- require transport details before leg dispatch
- generate and expose the inbound waybill artifact after dispatch
- block duplicate dispatch and invalid status transitions

#### 11C. Staging Receipt Workspace

Route:

- `/operations/staging-receipt/:leg_id`

Page must:

- allow only authorized staging-hub receiving users to receive an in-transit leg
- capture receiver, timestamp, notes, receipt artifact, and line-level variances
- post received stock into staging and reserve it to the originating package
- update package-level consolidation status after each receipt

#### 11D. Pickup Release Workspace

Route:

- `/operations/pickup-release/:reliefpkg_id`

Page must:

- allow pickup release only when the package is `READY_FOR_PICKUP`
- capture collector identity, releasing actor, release timestamp, and release evidence
- consume the reserved staged stock only when pickup release is completed

#### 11E. Partial Release Request / Approval

Route:

- integrated into `/operations/consolidation/:reliefpkg_id` or a dedicated staged-release surface

Page must:

- allow partial release request only when some, but not all, required legs have been received
- require a reason when a partial release is requested
- require authorized approval before any partial release proceeds
- show released-child and residual-child package outcomes after approval

#### 12. Override Approval Queue / State

Route:

- queue filter or dedicated Operations queue

Page must:

- show non-compliant allocation plan
- show reason for override
- enforce no-self-approval
- allow supervisor approval or rejection

#### 13. Dispatch Queue

Route:

- `/operations/dispatch`

Page must:

- show packages truly awaiting dispatch
- distinguish direct packages from staged packages that are now ready for final dispatch
- separate ready, in-transit, and recently dispatched states

#### 14. Dispatch Workspace / Transport Log

Route:

- `/operations/dispatch/:reliefpkg_id`

Page must:

- capture driver, vehicle, departure, ETA, and transport notes
- treat dispatch as transport workflow plus stock movement
- use the staging hub as the effective dispatch source for `DELIVER_FROM_STAGING` packages (user-facing label: `Deliver from Staging Hub`)
- remap final dispatch lines to staged stock before final dispatch from staging
- deduct stock on dispatch
- generate waybill artifact

#### 15. Waybill View

Route:

- `/operations/dispatch/:reliefpkg_id/waybill`

Page must:

- show official dispatch artifact
- support both final outbound waybills and inbound consolidation-leg waybills through the appropriate workflow surface
- remain unavailable before dispatch

#### 16. Receipt Confirmation

Route:

- `/operations/receipt-confirmation/:reliefpkg_id`

Page must:

- confirm receipt
- create receipt artifact
- support future last-mile delivery extension
- never deduct stock again

#### 17. Notifications / Task Center

Route:

- `/operations/tasks` or equivalent dashboard-integrated surface

Page must:

- show workflow notifications and next-action tasks
- connect completed events to next responsible roles

## Status Transition Matrix

### Request lifecycle

| From | Trigger | Actor | To | Stock effect | Notes |
| --- | --- | --- | --- | --- | --- |
| `DRAFT` | Save draft | Request owner | `DRAFT` | None | Request date stamped by backend |
| `DRAFT` | Submit | Request owner | `SUBMITTED` | None | Must have at least one item |
| `SUBMITTED` | Queue intake / reviewer opens | System / workflow | `UNDER_ELIGIBILITY_REVIEW` | None | Recommended explicit state |
| `UNDER_ELIGIBILITY_REVIEW` | Approve | Deputy DG / Director PEOD / DG | `APPROVED_FOR_FULFILLMENT` | None | Sends work to fulfillment queue |
| `UNDER_ELIGIBILITY_REVIEW` | Mark ineligible | Deputy DG / Director PEOD / DG | `INELIGIBLE` | None | Must capture reason |
| `UNDER_ELIGIBILITY_REVIEW` | Reject | Deputy DG / Director PEOD / DG | `REJECTED` | None | Separate only if business distinguishes from ineligible |
| `APPROVED_FOR_FULFILLMENT` | First package committed | Fulfillment role | `PARTIALLY_FULFILLED` | Reserve stock | Use if request not fully covered yet |
| `PARTIALLY_FULFILLED` | All required quantities dispatched | System | `FULFILLED` | None | Deduction already occurred on dispatch |
| `DRAFT` / `SUBMITTED` / `UNDER_ELIGIBILITY_REVIEW` | Cancel | Authorized actor | `CANCELLED` | None | Pre-fulfillment cancellation |

### Package lifecycle

| From | Trigger | Actor | To | Stock effect | Notes |
| --- | --- | --- | --- | --- | --- |
| none | Create package draft | Logistics Officer / Logistics Manager | `DRAFT` | None | Package may acquire lock |
| `DRAFT` | Save draft allocation | Fulfillment role | `DRAFT` | None | Editable |
| `DRAFT` | Commit compliant direct allocation | Fulfillment role | `COMMITTED` | Reserve stock | Freeze for direct dispatch lane |
| `DRAFT` | Commit compliant staged allocation with off-staging source stock | Fulfillment role | `CONSOLIDATING` | Reserve stock | Create consolidation plan and legs |
| `DRAFT` | Commit staged allocation when all stock is already at selected staging hub | Fulfillment role | `READY_FOR_PICKUP` or `READY_FOR_DISPATCH` | Reserve stock | Bypass consolidation legs based on fulfillment mode and selected canonical fulfillment mode code |
| `DRAFT` | Commit non-compliant allocation | Fulfillment role | `PENDING_OVERRIDE_APPROVAL` | None | Requires reason + supervisor approval |
| `PENDING_OVERRIDE_APPROVAL` | Approve override for `DIRECT` package | Authorized supervisor | `COMMITTED` | Reserve stock | No self-approval; direct mode follows the direct dispatch lane |
| `PENDING_OVERRIDE_APPROVAL` | Approve override for staged package with off-staging source stock | Authorized supervisor | `CONSOLIDATING` | Reserve stock | No self-approval; create or retain consolidation plan and legs |
| `PENDING_OVERRIDE_APPROVAL` | Approve override for staged package when all allocated stock is already at selected staging hub | Authorized supervisor | `READY_FOR_PICKUP` or `READY_FOR_DISPATCH` | Reserve stock | No self-approval; apply the same staged-ready bypass rule used for compliant staged commit |
| `COMMITTED` | Finalize transport prep | Dispatch role | `READY_FOR_DISPATCH` | None | Transport artifact required where applicable |
| `CONSOLIDATING` | All required stock received at staging for pickup mode | System | `READY_FOR_PICKUP` | None | Package-level consolidation status becomes `ALL_RECEIVED` |
| `CONSOLIDATING` | All required stock received at staging for deliver-from-staging mode | System | `READY_FOR_DISPATCH` | None | Final dispatch source becomes staging hub |
| `CONSOLIDATING` | Approve partial release | Authorized approver | `SPLIT` | None | Creates released-child and residual-child packages |
| `READY_FOR_DISPATCH` | Dispatch / handoff | Inventory Clerk / Logistics Officer / Logistics Manager | `DISPATCHED` | Deduct stock | Waybill artifact created |
| `READY_FOR_PICKUP` | Pickup release completed | Authorized staging release actor | `RECEIVED` | Deduct staged reserved stock | Pickup-release artifact created |
| `DISPATCHED` | Receipt confirmed | Receiver / authorized actor | `RECEIVED` | None | Receipt artifact created |
| `DRAFT` / `PENDING_OVERRIDE_APPROVAL` / `COMMITTED` / `CONSOLIDATING` | Cancel | Authorized actor | `CANCELLED` | Release reserve if applicable | Audit required |

### Consolidation lifecycle

| From | Trigger | Actor | To | Stock effect | Notes |
| --- | --- | --- | --- | --- | --- |
| none | Staged package committed with off-staging stock | System | `AWAITING_LEGS` | None | Package-level consolidation status |
| `AWAITING_LEGS` | First consolidation leg dispatched | Dispatch-capable role | `LEGS_IN_TRANSIT` | Deduct stock from source warehouse for dispatched leg | Shadow transfer and inbound waybill required |
| `LEGS_IN_TRANSIT` / `AWAITING_LEGS` | Some but not all required legs received | Authorized staging receiver | `PARTIALLY_RECEIVED` | Post received stock into staging and reserve to package | Variances captured at line level |
| `PARTIALLY_RECEIVED` | Partial release requested | Authorized fulfillment actor | `PARTIAL_RELEASE_REQUESTED` | None | Reason required |
| `PARTIALLY_RECEIVED` / `LEGS_IN_TRANSIT` | Remaining required legs received | Authorized staging receiver | `ALL_RECEIVED` | Post received stock into staging and reserve to package | Package becomes ready for pickup or final dispatch based on fulfillment mode |

### Consolidation leg lifecycle

| From | Trigger | Actor | To | Stock effect | Notes |
| --- | --- | --- | --- | --- | --- |
| none | Staged package committed | System | `PLANNED` | None | Leg may be rebuilt only while all legs are planned |
| `PLANNED` | Dispatch consolidation leg | Dispatch-capable role | `IN_TRANSIT` | Deduct stock from source warehouse | Transport details, shadow transfer, and inbound waybill required |
| `IN_TRANSIT` | Receive at staging | Authorized staging receiver | `RECEIVED_AT_STAGING` | Post received stock into staging and reserve to package | Receipt artifact and variance capture required |
| `PLANNED` | Cancel before dispatch | Authorized actor | `CANCELLED` | None | Must not allow cancellation after dispatch without explicit reversal policy |

### Dispatch lifecycle

| From | Trigger | Actor | To | Stock effect | Notes |
| --- | --- | --- | --- | --- | --- |
| none | Dispatch record opened | Dispatch role | `READY` | None | Transport details captured |
| `READY` | Actual departure / handoff | Dispatch role | `IN_TRANSIT` | Deduct stock | Same moment package becomes dispatched; for staged final dispatch the effective source is the staging hub |
| `IN_TRANSIT` | Arrival acknowledged | Receiver / downstream actor | `DELIVERED` | None | Optional pre-receipt state |
| `DELIVERED` / `IN_TRANSIT` | Receipt confirmed | Receiver / authorized actor | `RECEIVED` | None | Final receipt state |
| `READY` / `IN_TRANSIT` | Cancel / void | Authorized actor | `CANCELLED` | Depends on reversal policy | Must be explicitly defined if post-handoff |

## Notification Event Matrix

Internal workflow notifications are in scope.

| Event | Triggered by | Notify | Queue impact | Required |
| --- | --- | --- | --- | --- |
| Relief Request submitted | Request owner | Eligibility approvers | Add to eligibility queue | Yes |
| Relief Request approved | Deputy DG / Director PEOD / DG | Logistics Officers, Logistics Managers | Add to fulfillment queue | Yes |
| Relief Request rejected / ineligible | Approver | Request owner | Close or remove active work item | Yes |
| Package lock acquired | Fulfillment actor | Fulfillment team as needed | Show locked state | Yes |
| Override requested | Fulfillment actor | Override approver cohort | Add to override approval queue | Yes |
| Override approved | Supervisor approver | Fulfillment actor | Return item to active fulfillment flow | Yes |
| Staged package committed | Fulfillment actor | Consolidation-capable roles | Add to consolidation queue | Yes |
| Direct package committed | Fulfillment actor | Dispatch-capable roles | Add to dispatch queue | Yes |
| Consolidation leg dispatched | Dispatch-capable role | Staging receipt actors, package owner roles | Add to staging receipt queue | Yes |
| Consolidation leg received | Authorized staging receiver | Fulfillment roles, dispatch-capable roles | Update consolidation workspace and ready-state evaluation | Yes |
| Package ready for pickup | System | Authorized pickup-release actors | Add to pickup-release queue | Yes |
| Package ready for staged dispatch | System | Dispatch-capable roles | Add to dispatch queue | Yes |
| Partial release requested | Authorized fulfillment actor | Partial-release approver cohort | Add to approval queue | Yes |
| Partial release approved | Authorized approver | Fulfillment, dispatch, and receiving roles for affected children | Update staged package queues | Yes |
| Pickup release completed | Authorized staging release actor | Request owner, fulfillment roles, dispatch roles | Close pickup-release work item | Yes |
| Dispatch completed | Dispatch actor | Receiver-facing actors, request owner, fulfillment roles | Add to receipt queue | Yes |
| Receipt confirmed | Receiver / authorized actor | Request owner, fulfillment roles, dispatch roles | Close receipt queue item | Yes |
| External receiving-agency dispatch notification | Dispatch actor / system | External receiver | Separate from internal workflow queue | Separate decision |

## Operations-Native Permission Matrix

| Role / persona | Tenant context | Permissions |
| --- | --- | --- |
| Lower-level/community planner | Lower-level tenant under parent authority | Replenishment needs-list permissions only; no direct Operations request-create permission |
| Parish requester | Parish request-authority tenant | `operations.request.create.self`, `operations.request.create.for_subordinate`, `operations.request.edit.draft`, `operations.request.submit`, `operations.notification.receive`, `operations.queue.view` |
| Independent tenant requester | Direct tenant with self-request authority | `operations.request.create.self`, `operations.request.edit.draft`, `operations.request.submit`, `operations.notification.receive`, `operations.queue.view` |
| ODPEM bridge requester | National / ODPEM transitional bridge | `operations.request.create.on_behalf_bridge`, `operations.request.edit.draft`, `operations.request.submit`, `operations.notification.receive`, `operations.queue.view` |
| Eligibility approver | Deputy DG / Director PEOD / DG | `operations.eligibility.review`, `operations.eligibility.approve`, `operations.eligibility.reject`, `operations.queue.view`, `operations.notification.receive` |
| Logistics Officer | Operations / logistics | `operations.package.create`, `operations.package.lock`, `operations.package.allocate`, `operations.package.fulfillment_mode.set`, `operations.package.staging.select`, `operations.package.override.request`, `operations.consolidation.view`, `operations.consolidation.leg.dispatch`, `operations.partial_release.request`, `operations.dispatch.prepare`, `operations.dispatch.execute`, `operations.pickup_release.view`, `operations.waybill.view`, `operations.notification.receive`, `operations.queue.view` |
| Logistics Manager | Operations / logistics | All Logistics Officer permissions plus `operations.package.override.approve`, `operations.package.staging.override`, `operations.partial_release.approve`, `operations.pickup_release.execute` |
| Inventory Clerk | Warehouse / logistics | `operations.consolidation.leg.dispatch`, `operations.dispatch.prepare`, `operations.dispatch.execute`, `operations.waybill.view`, `operations.notification.receive`, `operations.queue.view` |
| Staging receiver / releasing actor | Staging hub operational scope | `operations.consolidation.leg.receive`, `operations.pickup_release.execute`, `operations.artifact.view`, `operations.notification.receive`, limited `operations.queue.view` |
| Receiver / receiving agency actor | Receiving tenant | `operations.receipt.confirm`, `operations.waybill.view`, `operations.notification.receive`, limited `operations.queue.view` |
| Auditor / read-only oversight | Authorized read-only scope | Read-only Operations and artifact view permissions only |

Freeze rule:

- the long-term Operations model must stop depending on `needs_list` permission names
- compatibility mapping may exist temporarily, but Operations-native permissions are the target baseline

## Target Operations Schema Baseline

### A. Tenant hierarchy and authority

```text
tenant_hierarchy
- hierarchy_id PK
- parent_tenant_id FK tenant
- child_tenant_id FK tenant
- relationship_type
- can_parent_request_on_behalf_flag
- effective_date
- expiry_date
- status_code
```

```text
tenant_request_policy
- policy_id PK
- tenant_id FK tenant
- can_self_request_flag
- request_authority_tenant_id FK tenant nullable
- can_create_needs_list_flag
- can_apply_needs_list_to_relief_request_flag
- can_export_needs_list_for_donation_flag
- can_broadcast_needs_list_for_donation_flag
- allow_odpem_bridge_flag
- effective_date
- expiry_date
- status_code
```

```text
tenant_control_scope
- control_scope_id PK
- controller_tenant_id FK tenant
- controlled_tenant_id FK tenant
- control_type
- effective_date
- expiry_date
- status_code
```

### B. Relief request

```text
operations_relief_request
- relief_request_id PK
- request_no unique
- requesting_tenant_id FK tenant
- requesting_agency_id FK agency
- beneficiary_tenant_id FK tenant nullable
- beneficiary_agency_id FK agency nullable
- origin_mode (SELF / FOR_SUBORDINATE / ODPEM_BRIDGE)
- source_needs_list_id FK needs_list nullable
- event_id FK event
- request_date
- urgency_code
- notes_text
- status_code
- submitted_by_id nullable
- submitted_at nullable
- reviewed_by_id nullable
- reviewed_at nullable
- fulfilled_at nullable
- cancelled_at nullable
- create_by_id
- create_dtime
- update_by_id
- update_dtime
- version_nbr
```

```text
operations_relief_request_item
- relief_request_item_id PK
- relief_request_id FK operations_relief_request
- item_id FK item
- request_qty
- issued_qty default 0
- urgency_code
- justification_text nullable
- required_by_date nullable
- status_code
- create_by_id
- create_dtime
- update_by_id
- update_dtime
- version_nbr
```

### C. Eligibility decision

```text
operations_eligibility_decision
- decision_id PK
- relief_request_id FK operations_relief_request
- decision_code (APPROVED / INELIGIBLE / REJECTED)
- decision_reason nullable
- decided_by_user_id
- decided_by_role_code
- decided_at
```

### D. Package and allocation

```text
operations_package
- package_id PK
- package_no unique
- relief_request_id FK operations_relief_request
- source_warehouse_id FK warehouse
- fulfillment_mode_code (DIRECT / PICKUP_AT_STAGING / DELIVER_FROM_STAGING)
- staging_warehouse_id FK warehouse nullable
- staging_recommendation_basis_code nullable
- staging_override_reason nullable
- destination_tenant_id FK tenant nullable
- destination_agency_id FK agency nullable
- status_code
- consolidation_status_code nullable
- override_status_code nullable
- committed_at nullable
- dispatched_at nullable
- received_at nullable
- ready_for_pickup_at nullable
- split_parent_package_id FK operations_package nullable  # authoritative package-lineage source of truth for split children
- create_by_id
- create_dtime
- update_by_id
- update_dtime
- version_nbr
```

```text
operations_package_item
- package_item_id PK
- package_id FK operations_package
- item_id FK item
- source_warehouse_id FK warehouse
- source_inventory_id FK inventory
- batch_id FK itembatch nullable
- allocated_qty
- uom_code
- allocation_method_code
- override_flag
- override_reason_code nullable
- create_by_id
- create_dtime
- update_by_id
- update_dtime
- version_nbr
```

```text
operations_package_lock
- package_lock_id PK
- package_id FK operations_package
- lock_owner_user_id
- lock_owner_role_code
- lock_started_at
- lock_expires_at nullable
- lock_status
```

### E. Consolidation and staged fulfillment

```text
operations_consolidation_leg
- consolidation_leg_id PK
- package_id FK operations_package
- leg_no unique
- source_warehouse_id FK warehouse
- staging_warehouse_id FK warehouse
- status_code
- shadow_transfer_id nullable
- dispatched_at nullable
- received_at nullable
- create_by_id
- create_dtime
- update_by_id
- update_dtime
- version_nbr
```

```text
operations_consolidation_leg_item
- consolidation_leg_item_id PK
- consolidation_leg_id FK operations_consolidation_leg
- package_item_id FK operations_package_item
- item_id FK item
- source_inventory_id FK inventory
- batch_id FK itembatch nullable
- planned_qty
- received_qty nullable
- shortage_qty nullable
- overage_qty nullable
- damaged_qty nullable
- variance_reason_text nullable
```

```text
operations_consolidation_receipt
- consolidation_receipt_id PK
- consolidation_leg_id FK operations_consolidation_leg
- received_by_user_id nullable
- received_by_name nullable
- received_at
- receipt_notes nullable
- receipt_artifact_json nullable
```

```text
operations_pickup_release
- pickup_release_id PK
- package_id FK operations_package
- collector_name
- collector_identity_ref
- released_by_user_id
- released_at
- release_notes nullable
- release_evidence_json nullable
```

```text
operations_partial_release_request
- partial_release_request_id PK
- package_id FK operations_package
- request_reason
- approval_status_code
- requested_by_user_id
- requested_at
- approved_by_user_id nullable
- approved_at nullable
- released_child_package_id FK operations_package nullable  # duplicate child reference for immutable workflow/audit convenience only
- residual_child_package_id FK operations_package nullable  # duplicate child reference for immutable workflow/audit convenience only
```

### F. Dispatch and transport

```text
operations_dispatch
- dispatch_id PK
- package_id FK operations_package
- dispatch_no unique
- status_code
- dispatch_at nullable
- dispatched_by_id nullable
- source_warehouse_id FK warehouse
- destination_tenant_id FK tenant nullable
- destination_agency_id FK agency nullable
- create_by_id
- create_dtime
- update_by_id
- update_dtime
- version_nbr
```

```text
operations_dispatch_transport
- dispatch_transport_id PK
- dispatch_id FK operations_dispatch
- driver_name
- driver_license_no nullable
- vehicle_id nullable
- vehicle_registration nullable
- vehicle_type nullable
- transport_mode nullable
- departure_dtime nullable
- estimated_arrival_dtime nullable
- transport_notes nullable
- route_override_reason nullable
```

### G. Waybill and receipt artifacts

```text
operations_waybill
- waybill_id PK
- dispatch_id FK operations_dispatch nullable
- consolidation_leg_id FK operations_consolidation_leg nullable
- waybill_no unique
- waybill_type_code (FINAL_DISPATCH / CONSOLIDATION_INBOUND)
- artifact_payload_json
- artifact_version
- generated_by_id
- generated_at
- is_final_flag
```

```text
operations_receipt
- receipt_id PK
- dispatch_id FK operations_dispatch
- package_id FK operations_package
- receipt_status_code
- received_by_user_id nullable
- received_by_name nullable
- received_at nullable
- receipt_notes nullable
- receipt_artifact_json nullable
- beneficiary_delivery_ref nullable
```

### H. Notifications and queue routing

```text
operations_notification
- notification_id PK
- event_code
- entity_type
- entity_id
- recipient_user_id nullable
- recipient_role_code nullable
- recipient_tenant_id nullable
- message_text
- queue_code nullable
- read_at nullable
- created_at
```

```text
operations_queue_assignment
- queue_assignment_id PK
- queue_code
- entity_type
- entity_id
- assigned_role_code
- assigned_tenant_id nullable
- assigned_user_id nullable
- assignment_status
- assigned_at
- completed_at nullable
```

### I. Operational action audit

```text
operations_action_audit
- action_audit_id PK
- entity_type
- entity_id
- package_id FK operations_package nullable
- consolidation_leg_id FK operations_consolidation_leg nullable
- tenant_id FK tenant nullable
- warehouse_id FK warehouse nullable
- action_code
- action_reason nullable
- artifact_reference nullable
- acted_by_user_id
- acted_by_role_code
- acted_at
```

### J. Status history

```text
operations_status_history
- status_history_id PK
- entity_type
- entity_id
- from_status_code
- to_status_code
- changed_by_id
- changed_at
- reason_text nullable
```

Schema note:

- `operations_status_history` is the authoritative transition ledger for lifecycle status changes
- `operations_action_audit` is the authoritative immutable evidence ledger for staged and consolidation actions
- implementation planning must treat the two tables as complementary, not interchangeable

## Impacted Areas

### Frontend

- Relief Request wizard mode logic must support:
  - self
  - for subordinate entity
  - ODPEM bridge
- Needs-list UI must support lower-level tenant creation and constrained downstream actions
- Eligibility screens must reflect exact approver roles
- Package screens must expose lock, override, fulfillment mode, staging selection, and consolidation state clearly
- Consolidation screens must support staging recommendation, leg dispatch, leg receipt, partial release, pickup release, and staged-ready transitions
- Dispatch screens must be transport-aware, not stock-only, and must support final dispatch from staging
- Notifications and queues must be integrated visibly

### Backend

- request authority must move from simple self vs ODPEM bridge into hierarchy-aware logic
- request validation must support subordinate-control rules
- internal notifications must become first-class workflow outputs
- eligibility role enforcement must be explicit
- staged fulfillment must create consolidation plans and legs from committed package allocations
- consolidation leg dispatch and receipt must enforce idempotency, status transitions, tenant scope, and audit capture
- dispatch must persist transport artifact and support future last-mile extension, including final dispatch from staging
- Operations-native permissions must be introduced

### Database

- tenant hierarchy and request-policy support
- Operations-native request/package/consolidation/dispatch/receipt artifacts
- package lock ownership
- staging warehouse selection and consolidation lineage
- immutable action audit capture for staged work
- pickup release and partial release ownership
- waybill artifact ownership
- clean status model
- notification and queue assignment model

### QA

- hierarchy authority cases
- lower-level needs-list creation and usage cases
- exact approver role gating
- notification fan-out and queue assignment
- staging recommendation and override behavior
- consolidation leg creation, dispatch, receipt, and variance capture
- partial release split behavior
- pickup release artifact capture
- dispatch transport capture including staged final dispatch
- artifact persistence and visibility
- no stock-regression checks

## Requirement Gaps and Contradictions To Resolve

- `Deputy DG` is now part of eligibility approval and must be mapped to a formal role code if not already present
- internal workflow notifications are now required, but external dispatch notification to receiving agency remains a distinct scope decision and must be separated clearly
- earlier simplified non-ODPEM self-service logic is superseded by hierarchy-based request authority and must be removed from future implementation assumptions
- current hybrid use of legacy relief tables and bridge logic is acceptable only as transition; first-class Operations data ownership is now the target baseline
- if a distinct staging-hub receiver role code does not already exist, it must be resolved through an Operations permission assignment pattern before implementation is treated as complete
- final direct-dispatch and staged-dispatch queue behavior must stay separate from consolidation-only work queues

## What Must Change Before Further Implementation Starts

- freeze tenant hierarchy and request-authority rules in product and technical docs
- freeze lower-level needs-list behavior and allowed downstream actions
- freeze exact eligibility, fulfillment, and dispatch role matrix
- freeze staged fulfillment mode and staging-hub selection rules
- freeze consolidation leg lifecycle, package-level consolidation status model, and staged-ready transitions
- freeze pickup-release and partial-release rules
- freeze Operations-native status model
- freeze notification event matrix
- freeze dispatch and consolidation transport requirements
- freeze staged-work idempotency and immutable audit expectations
- freeze target Operations schema baseline
- keep current stock timing rules unchanged

## Forward-Looking Constraint

Separate from the immediate Relief Management scope, remember:

- procurement is not only a needs-list downstream artifact
- ODPEM must retain a standing operational procurement path for minimum-threshold readiness stock maintenance outside a donation flow or specific event-triggered request flow

See:

- `docs/implementation/odpem_operational_procurement_context_note.md`
