# DMIS System and Application Architecture

Last updated: 2026-04-15
Status: Canonical current-state and target-state architecture reference

## Purpose and Scope

This document is the canonical architecture source of truth for DMIS.

It defines:

- the current system and application architecture
- the recommended target architecture
- the component and responsibility boundaries that new work should preserve
- the production-shaping non-functional architecture expectations for scalability, performance, reliability, availability, and security
- the architectural position of Redis, async workers, durable artifacts, observability, and Flask decommission status
- the rules that determine when new plans or implementations are aligned or misaligned with the intended platform direction

This document should be used as the first architecture reference by implementation agents, planning agents, reviewers, and release decision-makers.

## Architecture Scope

The architecture covered here includes:

- Angular frontend in `frontend/`
- Django modular monolith in `backend/`
- PostgreSQL as the system of record
- Redis as the shared cache and coordination layer in production
- Celery or equivalent worker plane for asynchronous and retryable work
- object storage for durable operational artifacts and exports
- OIDC/JWT identity integration
- edge delivery components such as CDN, WAF, and ingress
- the historical Flask cutover record preserved in `docs/` and Git history

## Current-State Architecture

DMIS is currently an Angular + Django platform. DMIS-10 completed the legacy Flask runtime decommission.

### Current logical shape

- Angular 21 SPA provides the user-facing application experience.
- Django 4.2 provides the main API and business workflow runtime.
- PostgreSQL is the primary system of record.
- Redis support exists in code but is still optional in current runtime behavior.
- Long-running or retryable operations are not yet consistently offloaded to a background worker plane.
- Some operational artifacts are still reconstructed from workflow state rather than durably stored.
- No executable Flask runtime or rollback gate remains in the repo or deployable system.

### Current strengths

- Angular uses modern standalone and reactive patterns.
- Django is already a better backend center of gravity than the old Flask surface.
- JWT/JWKS validation, RBAC, and tenant context resolution already exist.
- Functional workflow intent is well represented in the attached assets and implementation docs.

### Current architecture risks

- auth posture is still too dependent on environment toggles and dev-only paths
- tenant protection relies heavily on application logic across complex workflows
- request-path SQL and synchronous heavy workflows threaten scale and resiliency
- Redis-backed protections do not become truly reliable until Redis is mandatory in production
- generated artifacts and audit evidence are not yet durable enough
- stale deployment assumptions can still mislead production preparation
- alternate-runtime drift would recreate duplicate-control-path risk that DMIS-10 removed

## Target-State Architecture

DMIS should move to a hardened modular monolith built around Angular and Django.

### Target architecture summary

- Angular SPA served behind CDN/WAF and ingress
- Django API nodes as the authoritative application runtime
- PostgreSQL primary database with backup and recovery posture, plus read scaling where needed
- Redis HA as the mandatory shared cache and coordination layer in production
- Celery workers and scheduler for background, expensive, retryable, and externally dependent work
- object storage for generated waybills, exports, attachments, and audit-relevant artifacts
- Keycloak or equivalent OIDC provider as the only production identity model
- centralized metrics, logs, traces, alerting, readiness, and recovery controls
- no Flask runtime or rollback path in the supported platform

### Recommended runtime topology

```text
Users
  |
  v
CDN / WAF
  |
  v
Ingress / Reverse Proxy
  |-------------------------------> Angular SPA assets
  |
  +-------------------------------> Django API nodes
                                        |
                                        +--> OIDC provider
                                        |
                                        +--> PostgreSQL primary
                                        |      |
                                        |      +--> replica / PITR backups
                                        |
                                        +--> Redis HA
                                        |
                                        +--> Celery workers + scheduler
                                        |
                                        +--> Object storage
                                        |
                                        +--> Metrics / logs / traces / alerting
```

## Architecture Principles

1. Prefer a hardened modular monolith over premature microservices.
2. Keep backend authorization authoritative; frontend access checks are UX only.
3. Make shared coordination correct before trying to scale horizontally.
4. Push expensive, retryable, or externally dependent work off request paths.
5. Persist audit-relevant artifacts durably instead of reconstructing them from mutable state.
6. Treat observability, recovery, and readiness as architecture requirements, not afterthoughts.
7. Keep dev-only features isolated from staging and production behavior.
8. Reduce duplicate control paths, especially those introduced by legacy Flask.
9. Preserve tenant-safe boundaries across API, service, and data access layers.
10. Prefer explicit architecture alignment over convenience-driven local exceptions.

## Logical Component View

### Frontend

The Angular frontend owns:

- route composition and navigation
- forms, workflow presentation, and interaction states
- accessibility and responsive behavior
- frontend validation for UX only
- centralized HTTP, auth, and error-state handling
- route-guard and permission-aware user experience

The frontend must not become the authoritative enforcement point for security-sensitive decisions.

### Backend

The Django backend owns:

- authentication and authorization enforcement
- tenancy and object access enforcement
- workflow state changes and business rule execution
- data validation and normalization at API, serializer, form, and service boundaries
- audit generation and operational traceability
- durable artifact persistence decisions
- rate limiting and abuse protections

### Data tier

The data tier owns:

- durable system-of-record persistence in PostgreSQL
- relational integrity and transactional safety
- backup and restore posture
- future read-scaling where needed
- durable object storage for generated artifacts and exports

### Tenant Type Taxonomy

`ref_tenant_type` is the canonical source of truth for DMIS tenant classifications. The approved baseline codes are `NATIONAL`, `MILITARY`, `SOCIAL_SERVICES`, `PARISH`, `COMMUNITY`, `NGO`, `UTILITY`, `SHELTER_OPERATOR`, and `PARTNER`.

Tenant records must reference this table through `tenant.tenant_type`; duplicate hard-coded check constraints or frontend-only option lists are not authoritative. Tenant-type administration is a restricted Advanced/System capability, and the Django backend remains the enforcement point for baseline-only codes, write authorization, tenant-context checks, and in-use inactivation blocking.

### Tenant-First User Creation

Advanced/System user creation is tenant-first. Creating a user requires a tenant and must atomically create exactly one active primary `tenant_user` membership in the same database transaction; a membership failure invalidates the whole create.

`agency_id` remains optional legacy compatibility only and must not drive new user provisioning. Primary Tenant display is read from `tenant_user` plus `tenant`, and the flat user edit form cannot change primary tenant membership.

### Tenant-First Warehouse Ownership

Warehouse ownership and management are tenant-first. `warehouse.tenant_id` is the authoritative managing tenant for create, edit, list, and detail behavior, and warehouse tenant ownership changes must be authorized against both the current warehouse and the target tenant.

`custodian_id` remains only a legacy/transitional compatibility field for older workflows and data. Custodian maintenance is not a future-facing Master Data setup path and must not be linked from normal Master Data navigation or operational cards.

### Coordination tier

Redis and the worker plane own:

- shared counters and throttling correctness
- locks and coordination primitives
- queue-backed execution for long-running or retryable work
- circuit-breaker and degraded-mode support where relevant

## Runtime and Deployment View

### Local and development

Local development may support productivity-focused tooling, seeded test users, local dev auth helpers, and non-HA dependencies, but:

- local-only behavior must be explicitly gated by environment
- local behavior must not silently leak into staging or production
- production architecture decisions must not be weakened for developer convenience

### Staging

Staging should behave like production wherever security, topology, and operational posture matter.

Minimum expectations:

- auth mandatory
- production-like secure settings enabled
- production-like ingress behavior
- Redis enabled
- representative observability and readiness checks
- no production-path dev impersonation behavior

### Production

Production release gates / target-state requirements until runtime enforcement is complete:

- mandatory OIDC/JWT auth
- secure deployment defaults
- Redis as a required dependency
- worker plane active for expensive and retryable work
- durable artifact storage
- tested backup, restore, and rollback procedures
- explicit monitoring and alerting for critical dependencies

## Data and Integration View

### System of record

- PostgreSQL is the canonical transactional store.
- Raw SQL usage on legacy paths must be constrained, reviewed, and progressively reduced on hot or sensitive flows.
- New persistence patterns should favor reusable service and data access boundaries over ad hoc query duplication.

### Artifact durability

The following classes of outputs should be durably stored rather than reconstructed only from workflow state:

- waybills
- exports and downloadable reports
- operational approval evidence where documents matter
- future signed or externally shared operational documents

### Integration boundaries

- identity integration must validate issuer, audience, key material, and privileged claims deterministically
- external services must use timeouts, retries, and circuit-breaker-aware behavior
- queue-backed or externalized work must be idempotent where retries are possible

## Quality Attribute Strategy

### Scalability

The target scalability model is horizontal application scaling with correct shared coordination.

This requires:

- Redis as the shared coordination layer in production
- bounded query size and pagination
- reduced in-browser full-dataset processing on operationally critical screens
- async execution for expensive or burst-sensitive work
- query and route-level profiling for known hot paths

### Performance

The target performance model is predictable latency for operational workflows under normal and surge load.

This requires:

- server-side aggregation and pagination where data volume is significant
- query optimization on SQL-heavy endpoints
- minimized synchronous long-running work in request/response paths
- frontend routes and interaction states that fail clearly rather than hanging silently
- performance budgets for high-risk workflows

### Reliability

The target reliability model is correct behavior under retries, partial failures, and multi-step operational flows.

This requires:

- idempotency for critical writes
- durable workflow evidence
- explicit degraded-mode behavior for cache, queue, and identity dependencies
- clear ownership of state transitions in backend services
- reduction of duplicate business logic across layers

### Availability

The target availability model is a platform that remains observable, restartable, and recoverable during real operational use.

This requires:

- liveness and readiness semantics instead of a shallow health endpoint only
- Redis, PostgreSQL, queue, and object-storage dependency visibility
- tested backup and restore procedures
- alerting that detects sustained degradation before it becomes outage
- reduced dependence on optional infrastructure for correctness

### Security

The target security model is secure-by-default, tenant-safe, auditable, and production-first.

This requires:

- mandatory auth outside local development
- privileged-role MFA and stronger governance
- backend-enforced authorization and tenant-safe object access
- globally consistent validation, output safety, and throttling controls
- durable auditability for approvals, dispatch, receipt, and other high-risk operations
- complete Flask decommission from the runtime and deployable system

Owner: Platform architecture / security lead
Evidence:
- runtime and environment gates in `backend/dmis_api/settings.py`
- auth-mode enforcement and local-harness restrictions in `backend/api/authentication.py`
- launch and readiness evidence in `docs/implementation/production_readiness_checklist.md`
- document any frontend/backend assumption mismatches in `docs/` as part of the same change set

## Canonical Security and Control References

The following security documents remain authoritative for the listed concerns:

- `docs/security/SECURITY_ARCHITECTURE.md`
  - canonical security architecture
  - canonical input validation and output safety standard
  - canonical API rate limiting standard
  - production gate expectations
- `docs/security/THREAT_MODEL.md`
  - threat framing and production exit risks
- `docs/security/CONTROLS_MATRIX.md`
  - control implementation status and target posture
- `docs/implementation/production_readiness_checklist.md`
  - release gating and readiness evidence
- `docs/implementation/production_hardening_and_flask_retirement_strategy.md`
  - phased execution and transition sequencing

## Environment Expectations

### Local and development expectations

Allowed temporarily:

- local dev auth or impersonation helpers
- non-HA local dependencies
- seeded test data and role matrices
- browser-profile-based manual multi-user testing

Not allowed:

- weakening production-safe design decisions for local convenience
- shipping local-only auth behavior into non-local builds or runtimes

### Staging expectations

- mirror production auth and secure settings
- exercise production-like route protection and tenant enforcement
- run with representative infrastructure dependencies enabled
- serve as the proving ground for readiness, observability, and rollback evidence

### Production expectations

- no optional auth
- no optional Redis where shared correctness depends on it
- no production-path dev-user behavior
- no critical synchronous workflow that should be queued
- no alternate runtime dependency for normal user journeys

## Legacy Flask Position

DMIS-10 completed the Flask decommission:

- the executable Flask runtime was removed from the repo
- the root Flask packaging metadata and lockfile were removed
- the rollback-only gate was removed
- historical cutover notes remain only as non-current documentation

### Prohibited

- adding new business logic to Flask for forward progress
- reintroducing Flask as a supported runtime, deployment assumption, or rollback path
- duplicating modernized security or workflow logic across Flask and Django without an explicit retirement reason

### Decommission direction

- preserve traceability in historical docs and Git history only
- keep active docs and CI aligned to Angular + Django as the only supported platform
- treat any proposal to reintroduce a parallel runtime as an architecture review trigger

## Architecture Decision Rules

### Prefer

- extending Angular + Django patterns already aligned to the target architecture
- backend service-layer enforcement for security-sensitive workflow logic
- durable persistence for operational evidence
- Redis-backed shared coordination in production
- worker-backed async execution for expensive or retryable work
- explicit observability and readiness requirements in major changes
- documentation updates when architecture-sensitive changes are made

### Avoid

- expanding Flask
- introducing new production dependencies that bypass existing security and observability patterns without strong justification
- storing sensitive or authoritative workflow state only in the browser
- relying on frontend-only enforcement for security-sensitive actions
- adding ad hoc SQL-heavy patterns to hot or tenant-sensitive paths when safer reusable boundaries can be extended
- accepting optional infrastructure for correctness-critical behavior in production

### Misalignment indicators

A plan or implementation should be treated as architecturally misaligned if it:

- expands or normalizes Flask on the live path
- keeps auth optional outside local development
- preserves dev impersonation in staging or production behavior
- introduces correctness-sensitive production behavior that depends on in-process memory instead of Redis
- leaves durable operational artifacts as reconstruct-only state where persistence is required
- adds architecture-significant changes without corresponding security, reliability, or observability considerations
- weakens tenant-safe boundaries or backend authorization centralization

## Architecture Review Triggers

Medium- and high-risk work should trigger architecture review when it touches:

- auth, RBAC, tenancy, route guards, impersonation, tokens, or session handling
- secure settings, secrets, headers, cookies, CORS, uploads, validation, IDOR, or throttling
- raw SQL, Redis, caching, queues, workers, external integrations, or object storage
- workflow logic, approvals, dispatch, receipt, audit trails, or durable artifacts
- deployment topology, readiness, liveness, observability, backup, restore, or rollback
- API contracts, persistence strategy, or Flask migration/decommissioning

## Traceability References

Use these documents together, in this order, when architecture-sensitive work is being planned, implemented, or reviewed:

1. `docs/adr/system_application_architecture.md`
2. `docs/security/SECURITY_ARCHITECTURE.md`
3. `docs/security/THREAT_MODEL.md`
4. `docs/security/CONTROLS_MATRIX.md`
5. `docs/implementation/production_readiness_checklist.md`
6. `docs/implementation/production_hardening_and_flask_retirement_strategy.md`

## Governance

This architecture should be reviewed:

- whenever auth, tenancy, deployment topology, or worker architecture changes
- whenever alternate-runtime assumptions or historical Flask references change materially
- whenever the platform posture for security, reliability, or availability changes materially
- before production launch decisions
