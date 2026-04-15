# Production Hardening and Flask Retirement Strategy

Last updated: 2026-04-14
Status: Comprehensive pre-production strategy

## Purpose

This document is the execution and transition strategy for getting DMIS close to production-ready while the product is still in development.

The canonical architecture baseline now lives in `docs/adr/system_application_architecture.md`. This strategy document should be used for sequencing, workstream planning, production hardening execution, and Flask retirement tracking.

It covers:

- current-state architecture and documentation reality
- the main gaps against scalability, performance, reliability, availability, and security goals
- the target production architecture
- a phased hardening roadmap
- the plan to retire the remaining Flask application from the live path and then remove it entirely

## Strategic Outcome

DMIS should move to a hardened Angular + Django platform that can support live operational workflows without relying on development-mode settings, optional infrastructure for correctness, or legacy Flask paths for business-critical capability.

The recommended end state is a production-grade modular monolith with:

- Angular SPA at the edge
- Django API nodes as the primary application runtime
- PostgreSQL as the system of record
- Redis as mandatory shared cache and coordination
- Celery or equivalent workers for background and retryable work
- OIDC/JWT identity integration as the only production auth model
- durable artifact storage for exports, waybills, and audit evidence
- full observability, recovery, and release gates
- no Flask application in the live path

## Source-of-Truth Map

| Category | Best Current Source |
| --- | --- |
| Target-state functional and NFR intent | `docs/attached_assets/DMIS_PRD_v2_0.docx` |
| Phasing, backlog, and guardrails | `docs/attached_assets/DMIS_Product_Backlog_v3.2.xlsx` |
| Personas and access assumptions | `docs/attached_assets/DMIS_Stakeholder_Personas_v2.2.xlsx` |
| Workflow transitions | `docs/attached_assets/Appendix D - State_Transitions (Workflow).docx` |
| Current implementation reality | `README.md`, `backend/`, `frontend/`, `docs/implementation/` |
| Current approval policy reality | `docs/ops/replenishment-approval-policy-current-state.md` |
| Canonical system/application architecture | `docs/adr/system_application_architecture.md` |
| Security hardening target | `docs/security/SECURITY_ARCHITECTURE.md`, `docs/security/THREAT_MODEL.md`, `docs/security/CONTROLS_MATRIX.md` |

## Current-State Summary

### What is already strong

- Angular is on a modern stack and uses signals, standalone patterns, and widespread OnPush change detection.
- Django provides a clearer modular backend structure than the legacy Flask surface.
- JWT/JWKS validation, RBAC, and tenant context resolution already exist in the backend.
- Functional requirements and workflow intent are well documented in the attached assets.

### What is still preventing production confidence

- security posture still depends too much on runtime toggles and development-only paths
- some critical workflows are still synchronous and SQL-heavy
- shared coordination relies on optional Redis
- observability and readiness are too thin for operational use
- generated artifacts are not always durably stored
- frontend auth and error handling are not centralized enough
- several docs still describe the wrong stack
- Flask has not yet been fully removed from the live-path risk surface

## Gap Matrix By Non-Functional Requirement

| NFR | Current State | Main Gaps | Strategy Response |
| --- | --- | --- | --- |
| Scalability | Angular and Django can scale horizontally in principle | SQL-heavy request paths, client-heavy data shaping, no worker offload, weak shared-cache guarantees without Redis | add worker plane, require Redis, move expensive operations off request path, bound data loading |
| Performance | Modern frontend foundation and PostgreSQL base are adequate | full-array UI transformations, synchronous backend workflows, inconsistent pagination and aggregation patterns | push aggregation server-side, optimize hot queries, add route/component chunking, use async jobs for expensive work |
| Reliability | Core workflows exist across Django and Angular | retries, idempotency, artifact persistence, and state recovery are incomplete | introduce durable jobs, idempotent commands, stored artifacts, and stronger workflow integrity checks |
| Availability | Architecture can be made resilient | health endpoint is too shallow, telemetry is weak, Redis is optional, DR evidence is limited | implement readiness/liveness, HA dependency posture, alerting, and tested restore procedures |
| Security | JWT/RBAC/tenant model exists and Django middleware is present | auth optionality, dev impersonation, stale docs, limited global throttling, route inconsistencies, legacy Flask exposure | enforce secure defaults, centralize auth and HTTP handling, align docs, retire Flask |
| Governance | backlog and requirements artifacts are rich | current-state and target-state docs are fragmented and inconsistent | use the new strategy/security docs as the production-readiness baseline |

## Target Production Architecture

```text
Users
  |
  v
CDN / WAF
  |
  v
NGINX / Ingress
  |-------------------------------> Angular SPA
  |
  +-------------------------------> Django API nodes
                                        |
                                        +--> OIDC provider (Keycloak or equivalent)
                                        +--> PostgreSQL primary
                                        |      +--> replica / PITR backups
                                        +--> Redis HA
                                        +--> Celery workers + scheduler
                                        +--> Object storage
                                        +--> Observability stack
```

### Architecture decisions

1. Keep a modular monolith for now.
   The current scale and maturity level do not justify a microservices split. The bigger risk is weak operational discipline, not insufficient service decomposition.

2. Make Redis mandatory in production.
   Shared rate limits, locks, and circuit-breaker behavior should not depend on per-process memory.

3. Add a worker plane before launch.
   Exports, notifications, expensive integrations, document generation, and retryable workflows should run outside request latency.

4. Persist operational artifacts.
   Waybills, exports, and other audit-relevant outputs should be stored durably and versioned where appropriate.

5. Keep authorization centralized in the backend.
   Frontend gating improves UX, but backend authorization remains authoritative.

6. Remove Flask from the live path completely before production.
   If Flask remains live, the platform will keep paying an unnecessary reliability and security tax.

## Workstreams

### Workstream A: Secure Production Baseline

Outcome:
DMIS can no longer boot into an unsafe production posture.

Core work:

- require auth in staging and production
- remove production dev-user impersonation behavior
- enforce secure Django deployment settings
- require MFA for privileged roles
- align ingress, TLS, and cookie behavior to production controls

### Workstream B: Reliability and Availability Foundation

Outcome:
The platform can detect dependency failure, degrade predictably, and recover safely.

Core work:

- add readiness and liveness checks
- make Redis required and observable
- add request correlation, structured runtime/auth/error logs, and alert-ready incident visibility
- define backup, restore, rollback, and failover procedures with dated evidence expectations
- introduce durable artifacts and audit evidence

Current implementation note:

- DMIS-06 established the first Celery-backed worker-plane slice for the Django modular monolith.
- Needs-list donation and procurement CSV exports now queue as async jobs with status/download endpoints, retry-aware lifecycle logging, and queue readiness tied to worker heartbeat.
- DMIS-08 hardens that async export slice by persisting queued CSV payloads in PostgreSQL-backed `async_job_artifact` rows, preserving authenticated job download paths, and linking durable artifacts back to immutable `NeedsListAudit` evidence with actor and request correlation.
- Durable object storage for larger or longer-lived artifacts remains a follow-up; the current slice now uses bounded DB-backed retention for small CSV outputs instead of inline-only payload storage.
- DMIS-07 reduced request-path amplification on two live Django read surfaces:
  - needs-list list filters now narrow the DB-backed record set before item hydration, and `my-submissions` now uses a bounded header-page path so date/status/warehouse ordering and page selection happen before full-record hydration; method-filtered pages fall back to bounded batch scanning instead of full header materialization
  - procurement list responses now default to summary rows, batch warehouse lookups, avoid inline line-item serialization unless a caller explicitly opts in with `include_items=true`, and return bounded pages via `page` / `page_size` while keeping the `procurements` payload key stable
- DMIS-07 follow-up hotspots still worth profiling and prioritizing:
  - `allocation_dispatch.get_allocation_options` for larger approved needs lists
  - broader needs-list dashboard/list feeds that still materialize full item snapshots per record
  - procurement detail, receive, and update flows under production-scale item counts
  - transfer generation if real operational latency continues to grow

### Workstream C: Performance and Scalability Hardening

Outcome:
The system performs predictably as data volume and concurrency increase.

Core work:

- identify and optimize hot SQL paths
- move expensive work to async workers
- add server pagination and bounded queries
- break up large Angular route chunks and oversized feature files
- reduce browser-only state assumptions for critical workflows

Immediate async migration follow-ups after DMIS-06:

- IFRC / Ollama suggestion work
- transfer generation if it becomes operationally latency-heavy
- operator repair / replay commands
- object storage lifecycle automation for artifact classes that outgrow the current DB-backed queued-export slice
- Celery beat / scheduled operational jobs only when there is a concrete supported use case

### Workstream D: Governance and Documentation Alignment

Outcome:
Architecture, controls, and release decisions are made from current and accurate information.

Core work:

- keep security docs aligned to the active stack
- publish one current-state and target-state narrative
- add hardening gates to release decisions
- keep attached-asset contradictions explicit rather than implicit

### Workstream E: Flask Retirement and Decommission

Outcome:
Flask is first removed from the live path, then removed from the deployable system.

Core work:

- inventory legacy routes, dependencies, and data flows
- confirm parity or explicit replacement in Django/Angular
- redirect or isolate all legacy live entry points
- mark any residual capability as rollback-only with an end date
- remove Flask-specific deployment and operational assumptions
- delete legacy runtime once parity and rollback decisions are closed

## Phased Roadmap

### Phase 0: Documentation and Production Gates

Objective:
Stop architecture drift and establish one production-readiness baseline.

Deliverables:

- updated security architecture, threat model, and controls matrix
- release checklist for security, observability, backup, rollback, and Flask retirement
- explicit mapping of current state vs target state vs deferred items

Exit criteria:

- no critical production doc still describes Flask as the main runtime
- release stakeholders agree on hardening gates

### Phase 1: Security Baseline Hardening

Objective:
Remove the highest-risk identity and configuration weaknesses.

Deliverables:

- production auth mandatory
- dev impersonation removed from production paths
- secure Django deployment settings enforced
- privileged-role MFA policy and implementation path agreed
- consistent frontend route protection and auth handling

Exit criteria:

- staging cannot run with auth disabled
- production frontend build does not include dev-user behavior
- deploy checks pass without high-signal security warnings

### Phase 2: Reliability and Availability Foundation

Objective:
Make the platform operationally supportable.

Deliverables:

- Redis mandatory in production
- liveness and readiness endpoints with dependency checks
- request IDs, structured runtime/auth/readiness/error logs, and alert-ready monitoring guidance
- metrics, logs, traces, and alerting
- tested backup and restore procedure or explicitly tracked evidence gap with owner
- defined degraded-mode behavior for cache, queue, and IdP failures

Exit criteria:

- critical dependencies are observable
- incidents can be correlated to request IDs or equivalent backend trace fields
- restore test evidence exists
- on-call or support team has usable incident visibility

### Phase 3: Performance and Scalability Hardening

Objective:
Reduce the risk that growth or emergency usage overloads the live system.

Deliverables:

- profiling and optimization of hot backend queries
- server-side pagination and aggregation where required
- async queue for expensive workflows
- reduction of oversized Angular feature chunks and client-heavy transforms
- explicit capacity targets and load-test criteria

Exit criteria:

- critical workflows meet agreed latency under representative load
- no production-critical workflow depends on full client-side dataset processing

### Phase 4: Flask Live-Path Removal

Objective:
Ensure no live user journey or production dependency still relies on Flask.

Deliverables:

- route-by-route legacy inventory
- parity confirmation or explicit retirement decision per capability
- redirects or removals for all legacy live entry points
- release notes and handoff docs updated to show Flask is not live

Exit criteria:

- no live navigation points to Flask
- no production workflow requires Flask for normal operations
- any rollback-only dependency is documented with owner and removal date

### Phase 5: Full Flask Decommission

Objective:
Remove the legacy application from the operational and security surface area.

Deliverables:

- delete Flask deployment assumptions
- remove Flask runtime from deployment manifests and infrastructure
- archive any required reference material
- remove or quarantine dead code after verification

Exit criteria:

- Flask is not deployed
- Flask is not a documented rollback path
- release and security documentation no longer list Flask as part of the platform

## Production Readiness Gates

DMIS should not be considered production-ready until all of the following are true:

- security docs match the deployed stack
- production auth is mandatory and dev impersonation is excluded
- secure deployment settings are enforced
- Redis is mandatory in production
- worker-based async processing exists for long-running or retryable jobs
- observability and alerting exist for edge, API, DB, cache, and queue dependencies
- backup and restore testing has been completed successfully
- critical artifacts are durably stored
- Flask is out of the live path

## Flask Retirement Strategy

### Step 1: Inventory

Build a route and dependency inventory covering:

- user-visible Flask pages
- API endpoints still sourced from Flask
- shared templates or auth/session assumptions
- batch jobs, reports, or ops utilities still tied to Flask

### Step 2: Parity Decision

For each Flask capability, mark it as one of:

- replaced in Django/Angular
- intentionally retired
- rollback-only until a named milestone

### Step 3: Cutover Controls

- remove Flask links from live navigation
- redirect legacy URLs where appropriate
- update release notes and QA evidence in the same change set
- never leave Flask in the live path implicitly

### Step 4: Decommission

- remove Flask from deployed environments
- remove obsolete documentation and deployment instructions
- archive only what is needed for traceability

## Immediate Next Actions

The highest-value next actions are:

1. treat the updated `docs/security/*` files as the new production-readiness baseline
   see checklist 6 (`Delivery and Governance`)
2. create a concrete engineering backlog mapped to Phase 1 through Phase 5
   see checklist 6 (`Delivery and Governance`) and the Exit Rule
3. harden auth and deployment defaults first
   see checklist 1 (`Security Baseline`) and checklist 2 (`Authorization and Tenant Safety`)
4. require Redis and add readiness plus observability next
   see checklist 3 (`Platform Reliability and Availability`) and checklist 5 (`Data and Audit Integrity`)
5. parallelize Flask route inventory and parity validation while the platform hardening work proceeds
   see checklist 7 (`Flask Retirement`)

## What "Almost Production Ready" Means Here

Because the application is still in development, "almost production ready" should mean:

- the architecture is stable enough to harden rather than redesign
- the highest-severity security and reliability gaps are closed first
- every remaining known gap is explicitly documented, prioritized, and owned
- legacy runtime dependencies are being intentionally retired rather than tolerated indefinitely

That is the standard this strategy is designed to support.


