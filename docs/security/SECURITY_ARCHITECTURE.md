# DMIS Security Architecture

Last updated: 2026-04-09
Status: Current-state and target-state security reference

## Purpose

This document describes the Disaster Management Information System (DMIS) security architecture as it exists today and the production-ready target architecture required before go-live.

This version supersedes the earlier Flask-centric description of the platform. DMIS is now centered on an Angular frontend and a Django backend, with the legacy Flask application treated as transition risk that should be retired from the live path.

## Scope

- Angular frontend in `frontend/`
- Django API in `backend/`
- PostgreSQL data tier
- Redis cache and coordination layer
- Future async worker platform for background jobs
- Object storage for generated artifacts and exports
- Identity provider integration for OIDC/JWT
- Residual Flask application in `app/`

## Security Objectives

DMIS must be hardened to support the stated non-functional requirements for security, scalability, performance, reliability, and availability.

The target state is expected to align to:

- ISO/IEC 25010 for quality attributes
- ISO 27001 control governance
- NIST Cybersecurity Framework 2.0 and selected NIST 800-53 operational controls
- OWASP ASVS Level 2 for application security verification
- ISO 22301 for continuity and recovery posture
- WCAG 2.1 AA for frontend resilience and accessibility

## Current-State Architecture

| Layer | Current Implementation | Current Risk |
| --- | --- | --- |
| Edge | NGINX example config under `docs/deploy/`, static Angular serving assumed | Deployment guidance is stale and still contains Flask-era assumptions |
| Frontend | Angular 21 SPA with lazy feature domains, signals, and OnPush components | Dev-user impersonation is still compiled into the app; route guards and failure handling are inconsistent |
| API | Django 4.2 modular monolith with `api`, `operations`, `replenishment`, and `masterdata` apps | Security posture is env-dependent; several request paths remain synchronous and SQL-heavy |
| Identity | JWT/JWKS validation exists in Django | Authentication can still be disabled by environment; frontend OIDC integration is incomplete |
| Authorization | RBAC and tenant context are resolved server-side from DB state | Tenant isolation is primarily enforced in application logic rather than stronger data-tier boundaries |
| Cache | Redis is supported; LocMemCache is used when Redis is absent | Shared counters, circuit breakers, and coordination become incorrect in multi-worker production without Redis |
| Background work | No mandatory worker plane yet | Long-running or retriable work remains coupled to request latency |
| Artifact storage | Some workflow documents are reconstructed from state rather than durably stored | Auditability and recovery are weaker than required for production operations |
| Legacy runtime | Flask application remains in repo and in transition planning | Residual live dependencies create operational, security, and change-management risk |

## Current-State Reference Topology

```text
Users
  |
  v
CDN / WAF / Reverse Proxy
  |-------------------------------> Angular SPA
  |
  +-------------------------------> Django API
                                      |
                                      +--> PostgreSQL
                                      |
                                      +--> Redis (optional today)
                                      |
                                      +--> External IdP / JWKS
                                      |
                                      +--> Legacy Flask dependencies still under retirement planning
```

## Trust Boundaries

1. Internet to edge boundary
   Traffic from browsers and partner integrations crosses the public trust boundary and must be protected by TLS, request filtering, and abuse controls.

2. Edge to application boundary
   Reverse proxy and ingress components must preserve identity, trace, and tenant headers safely while preventing spoofed internal headers.

3. Application to identity boundary
   Django trusts JWT metadata from the identity provider; token validation, issuer validation, audience validation, and privileged-role governance must be deterministic.

4. Application to data boundary
   PostgreSQL, Redis, object storage, and future worker queues are separate trust zones and require least-privilege access, encryption in transit, and strong operational controls.

5. Admin and operator boundary
   Tenant administrators, national operators, and platform administrators are highly privileged users and require stronger authentication, audit logging, and approval boundaries.

6. Legacy transition boundary
   The remaining Flask application is a special risk boundary because it can bypass or duplicate controls if it stays reachable while Django/Angular become the live path.

## Target Production Architecture

The recommended production-ready architecture is a hardened modular monolith, not a premature microservices split.

```text
Users
  |
  v
CDN / WAF
  |
  v
NGINX / Ingress
  |-------------------------------> Angular SPA assets
  |
  +-------------------------------> Django API nodes
                                        |
                                        +--> Keycloak or equivalent OIDC provider
                                        |
                                        +--> PostgreSQL primary
                                        |      |
                                        |      +--> Read replica / PITR backups
                                        |
                                        +--> Redis HA
                                        |
                                        +--> Celery workers + scheduler
                                        |
                                        +--> Object storage for exports, waybills, and audit artifacts
                                        |
                                        +--> Metrics / logs / traces / alerting
```

## Target Security Principles

### Identity and Access

- OIDC/JWT authentication required in every non-local environment
- MFA required for system administrators, tenant administrators, and nationally privileged users
- No dev impersonation code in production bundles or production runtime
- Server-side authorization remains the source of truth; frontend checks stay UX-only

### Tenant Isolation

- Tenant membership and tenant scope enforcement remain mandatory on the backend
- Cross-tenant access is explicit, audited, and policy-driven
- Sensitive workflows should validate tenant scope at both service and data access layers
- Long term, tenant-sensitive hot paths should move away from ad hoc query patterns toward safer, reusable data access boundaries

### Application and API Protection

- Secure-by-default Django settings in all non-local environments
- Global API throttling and endpoint-class throttling for sensitive or expensive workflows
- Centralized error handling, correlation IDs, and structured audit events
- Async processing for expensive, retriable, or externally dependent work

### Data Protection

- PostgreSQL connections encrypted in transit
- Least-privilege DB credentials per runtime
- Durable storage of generated operational artifacts
- Backups encrypted, routinely restored in test, and governed by retention policy

## Canonical Input Validation and Output Safety Standard

This section is the canonical validation and output-safety reference for DMIS.

### Validation boundary principles

- Backend enforcement is authoritative; frontend validation exists for UX only.
- Validate and normalize external input at the API, serializer, form, and service boundaries.
- Never trust client-supplied values for identity, permissions, status transitions, pricing, or other sensitive business logic.
- Reject invalid values explicitly rather than silently coercing or truncating them.
- Treat output safety as part of validation: do not leak stack traces, raw SQL, secrets, or sensitive internal state in errors or responses.

### Backend validation requirements

- Enforce `max_length` and shape constraints for all string fields.
- Use explicit allowlists for enum, status, and ordering inputs.
- Validate numeric inputs for type and range.
- Validate array inputs for type, length, and per-element shape.
- Parse and validate date and datetime values before they reach SQL or business logic.
- Normalize free-text fields with bounded length before storage.
- Use parameterized SQL only; never interpolate user input into raw SQL.
- Restrict dynamic table, column, and schema selection to hardcoded registries or safe quoting paths.

### Frontend validation requirements

- Every user-editable text input must enforce the same effective length constraints expected by the backend.
- Angular forms should apply required, length, and numeric bounds consistently in both the form model and template.
- User-entered text should be trimmed before submission where whitespace is not semantically meaningful.
- Do not rely on hidden controls, disabled controls, or route guards as security controls.
- Do not render user-provided content through unsafe HTML binding paths.

### Output safety and object access

- Unauthorized object lookups should return safe responses that do not leak object existence where that matters.
- Tenant-safe lookup and authorization must happen server-side for all reads, updates, deletes, approvals, dispatches, receipts, and exports.
- Error responses must remain bounded, safe, and correlation-friendly.

## Canonical API Rate Limiting Standard

This section is the canonical rate-limiting standard for DMIS.

### Policy principles

- Enforce rate limits per user, per tenant, and per IP for authenticated traffic.
- Use IP-only enforcement for public or unauthenticated traffic.
- During disaster `SURGE` phases, protections must defend the platform without blocking legitimate field operations.
- Prefer token-bucket or sliding-window approaches with burst tolerance over rigid fixed-window counters on surge-critical paths.

### Tiered limits

| Tier | Limit | Endpoints |
| --- | --- | --- |
| Read | 120 req/min | Stock status, dashboards, warehouse lists, needs list GET, queues, lookups, `whoami` |
| Write | 40 req/min | Needs list draft/edit, relief request create/update, procurement create/edit, supplier CRUD, master data CRUD |
| Workflow | 15 req/min | Submit, approve, reject, return, escalate, cancel, allocation commit, override approve |
| High-risk ops | 10 req/min | Dispatch handoff, receipt confirmation, mark-dispatched, mark-received, mark-completed, stock location assignment, repackaging |

### Special limits

| Action | Limit | Scope |
| --- | --- | --- |
| Login attempts | 5 per 15 min | Per account + per IP |
| File exports (CSV/PDF) | 5 per min | Per user |
| IFRC suggest (LLM) | 30 per min | Per user |
| Bulk operations | 5 per min | Per user |
| Public/unauthenticated | 60 per min | Per IP |

### Surge handling and operational rules

- Treat IP as a secondary abuse signal for authenticated users because shared networks are common in emergency operations.
- `national.act_cross_tenant` roles should receive 2x limits during active events as the emergency override path.
- Designated field operational roles may receive temporary surge overrides when telemetry shows legitimate emergency demand.
- `429` responses must include `Retry-After`.
- Frontend handling for throttling should use a recoverable toast or inline status pattern, not a hard failure screen.
- Log and monitor rate-limit hits by endpoint, tenant, role, and event phase.
- Use Redis-backed counters in production so throttling remains correct across multiple workers and nodes.

### Infrastructure and Operations

- Redis mandatory in production
- Health endpoints split into liveness and readiness semantics
- Metrics, logs, and traces emitted for API nodes, workers, database, and queue health
- Recovery objectives backed by tested procedures, not just declared targets

### Secure Delivery

- SAST, dependency scanning, and configuration review in CI
- Production change gates for security, observability, rollback, and data recovery
- Architecture and controls documentation kept aligned with the active stack

## Control Domains

| Domain | Current State | Target State |
| --- | --- | --- |
| Authentication | JWT validation exists, but auth can still be disabled by env | Mandatory OIDC/JWT in production and staging, with MFA for privileged roles |
| Authorization | RBAC and tenant context are present in Django | Unified backend enforcement with complete route and workflow coverage |
| Frontend security | Angular uses modern patterns, but dev impersonation and route inconsistency remain | Build-time separation of dev-only features, centralized HTTP/auth platform layer |
| API abuse protection | IFRC endpoint has local rate limiting; broader API throttling is limited | Global throttling, per-endpoint quotas, and edge rate controls |
| Data safety | PostgreSQL is the primary store; artifact persistence is inconsistent | Strong audit durability, stored artifacts, tested restore paths |
| Cache/coordination | Redis is optional in code | Redis HA required wherever shared counters, locks, or circuit breakers matter |
| Async operations | Mostly request-coupled today | Celery-backed workers for exports, notifications, document generation, and retries |
| Observability | Minimal health endpoint; limited evidence of platform telemetry | Logs, metrics, traces, alerts, and readiness checks across all critical components |
| Legacy isolation | Flask remains part of the transition plan | Flask removed from the live path, then decommissioned entirely |

## Production Gates

The following gates should be treated as mandatory before production launch:

- `DEBUG = False`, secure cookies enabled, HSTS enabled, HTTPS redirect enabled
- Authentication mandatory in production and staging
- Dev-user impersonation removed from production frontend builds and production backend runtime
- Redis mandatory in production
- Background worker platform active for long-running and retryable workloads
- Durable storage for operational artifacts such as waybills and exports
- Liveness, readiness, metrics, and alerting in place
- Backup, restore, and rollback procedures tested
- Flask live routes retired or explicitly isolated as rollback-only during transition
- Security architecture, threat model, and controls matrix aligned to the actual stack

## Residual Risks To Eliminate

The most important residual risks visible today are:

- optional authentication and dev-only behavior still close to the production path
- request-path raw SQL and synchronous workflow coupling
- weak operational observability and simplistic health semantics
- cache correctness depending on optional Redis
- documentation drift that could lead to unsafe deployment decisions
- incomplete retirement of the Flask application

## Governance

- Security architecture review: at least quarterly, and before any launch decision
- Threat model review: whenever the auth model, tenant model, or deployment model changes
- Controls matrix review: whenever a control changes state from missing to partial or implemented
- Flask retirement review: until all legacy routes and dependencies are removed from the live path

