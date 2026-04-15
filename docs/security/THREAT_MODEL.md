# DMIS Threat Model

Last updated: 2026-04-15
Status: Current-state pre-production threat model

## Purpose

This document captures the principal threats to the current DMIS implementation and the mitigations required to reach a production-ready posture.

It replaces the earlier Flask-centric threat model and reflects the active Angular + Django architecture, the multi-tenant access model, and the post-DMIS-10 requirement to prevent alternate-runtime drift.

## Modeling Approach

This review uses STRIDE as the primary threat framing and cross-checks the results against OWASP ASVS Level 2 expectations and the non-functional requirements for scalability, performance, reliability, availability, and security.

## Scope and Assumptions

- Angular SPA is the user-facing client
- Django is the primary application runtime
- PostgreSQL is the system of record
- Redis is intended for shared coordination and caching
- OIDC/JWT is the intended production identity model
- No legacy Flask runtime or rollback path remains in the supported repo or deployment model

## High-Priority Current Risks

| Priority | Threat | Why It Matters Now | Required Direction |
| --- | --- | --- | --- |
| Critical | Authentication bypass or spoofing through dev-only behavior | Auth can be env-disabled and dev-user override behavior is still near the production path | Make auth mandatory in non-local environments and remove dev impersonation from production builds |
| Critical | Tenant boundary failure | Tenant access is primarily enforced in application logic across complex workflows | Strengthen tenant-safe service boundaries, audit cross-tenant flows, and reduce ad hoc data access |
| High | Application-level denial of service | Expensive synchronous endpoints and limited global throttling can degrade response during emergency operations | Add global throttling, async offload, queue controls, and edge protections |
| High | Availability degradation from optional infrastructure | Redis is optional in code even though shared counters and coordination rely on it | Make Redis mandatory in production and monitor it as a critical dependency |
| High | Audit and artifact gaps | Some operational artifacts are rebuilt from state rather than durably stored | Persist artifacts and strengthen audit evidence for operational workflows |
| High | Unsafe deployment by documentation drift | Security and deployment docs can still drift away from the actual Angular + Django stack | Align docs to the actual stack and use them as production gates |

## STRIDE Analysis

### S - Spoofing Identity

#### Threat: Dev-user impersonation reaches production behavior

| Aspect | Details |
| --- | --- |
| Description | The frontend currently registers a dev-user interceptor and stores a selected dev identity in local storage. If backend toggles are misconfigured, users can impersonate other principals. |
| Impact | Unauthorized access, audit corruption, privileged action spoofing |
| Likelihood | Medium today; unacceptable for production |
| Severity | Critical |

Required mitigations:

- remove dev-user features from production frontend bundles
- hard-disable dev impersonation on production backend deployments
- require production OIDC/JWT auth for all user access
- alert on any attempt to send internal-only auth override headers

#### Threat: Weak privileged identity controls

| Aspect | Details |
| --- | --- |
| Description | National, tenant-admin, and platform-admin roles have elevated authority, but stronger controls such as MFA and formal access review are not yet clearly enforced in the active implementation. |
| Impact | Full administrative compromise |
| Likelihood | Medium |
| Severity | Critical |

Required mitigations:

- MFA for all privileged roles
- quarterly access review for privileged roles
- auditable approval and role-assignment workflows
- break-glass procedure with explicit logging and review

### T - Tampering With Data

#### Threat: Unsafe or inconsistent workflow mutation across SQL-heavy paths

| Aspect | Details |
| --- | --- |
| Description | Large portions of the replenishment and operations flows still rely on request-path raw SQL and hybrid data access patterns. |
| Impact | Data integrity errors, inconsistent reservations, workflow corruption |
| Likelihood | Medium |
| Severity | High |

Existing strengths:

- PostgreSQL remains the system of record
- some transactional boundaries and locks already exist

Required mitigations:

- consolidate critical write paths behind reusable service boundaries
- reduce direct SQL duplication for hot workflows
- add idempotency and compensating behavior for mutating operations
- expand integrity checks for stock, allocation, approval, and dispatch flows

#### Threat: Artifact tampering or loss

| Aspect | Details |
| --- | --- |
| Description | Documents such as waybills are not always durably stored as immutable artifacts. |
| Impact | Weak audit evidence, dispute risk, operational ambiguity |
| Likelihood | Medium |
| Severity | High |

Required mitigations:

- persist generated artifacts to object storage or equivalent durable storage
- hash and version critical generated documents
- record generation metadata in audit logs

### R - Repudiation

#### Threat: Operational actions cannot be proven strongly enough

| Aspect | Details |
| --- | --- |
| Description | Approval, dispatch, and fulfillment workflows need durable, attributable records. Documentation and artifact persistence are not yet consistently aligned with this need. |
| Impact | Weak accountability, audit disputes, compliance issues |
| Likelihood | Medium |
| Severity | High |

Required mitigations:

- durable audit logging for privileged and state-changing actions
- trace IDs and request IDs propagated across systems
- stored artifacts for critical workflow outputs
- retention and export policy for audit evidence

### I - Information Disclosure

#### Threat: Sensitive operational or tenant data leaks across boundaries

| Aspect | Details |
| --- | --- |
| Description | Multi-tenant access is enforced mainly in application logic, and frontend routes do not always apply consistent guards. |
| Impact | Cross-tenant exposure, unauthorized operational visibility |
| Likelihood | Medium |
| Severity | High |

Required mitigations:

- tenant checks in every sensitive backend service and query path
- consistent frontend route guards
- least-privilege data loading patterns
- stronger review of multi-tenant query behavior

#### Threat: Sensitive implementation detail leaks from insecure deployment posture

| Aspect | Details |
| --- | --- |
| Description | Current deploy checks show development-oriented settings that should not exist in production. |
| Impact | Elevated attack surface and easier exploitation |
| Likelihood | High if deployed as-is |
| Severity | High |

Required mitigations:

- secure Django deployment settings in all non-local environments
- deployment validation gate before release
- environment-specific configuration review in CI/CD

### D - Denial of Service

#### Threat: Expensive synchronous workflows exhaust app capacity

| Aspect | Details |
| --- | --- |
| Description | Long-running work remains coupled to synchronous API calls, while several screens and endpoints process substantial data in-memory. |
| Impact | Slow responses, worker exhaustion, degraded emergency operations |
| Likelihood | High |
| Severity | High |

Required mitigations:

- worker queue for exports, notifications, and expensive downstream actions
- server-side pagination and bounded query sizes
- endpoint-specific and global throttling
- performance budgets and regression checks

#### Threat: Shared coordination fails under multi-node load

| Aspect | Details |
| --- | --- |
| Description | Redis-dependent circuit breaker and rate-limit behavior fall back to in-process memory when Redis is absent. |
| Impact | Inconsistent protection across workers and degraded resilience |
| Likelihood | Medium |
| Severity | High |

Required mitigations:

- production deployments must require Redis
- add health and alerting for cache dependency loss
- define degraded-mode behavior explicitly

### E - Elevation of Privilege

#### Threat: Authorization gaps across route, feature, and workflow boundaries

| Aspect | Details |
| --- | --- |
| Description | Backend authorization is stronger than frontend gating, but route coverage and UI behavior are inconsistent. Privilege drift is possible where logic is duplicated or UI states mask auth failures. |
| Impact | Unauthorized access attempts, confused-deputy behavior, reduced trust in controls |
| Likelihood | Medium |
| Severity | High |

Required mitigations:

- complete frontend guard coverage
- keep backend authorization as the source of truth
- centralize frontend auth state and permission handling
- test high-risk roles and tenant scenarios regularly

#### Threat: Reintroduction of a parallel runtime bypasses modernized controls

| Aspect | Details |
| --- | --- |
| Description | If a legacy or parallel runtime is reintroduced after DMIS-10, it can recreate an alternate control path with different protections, audit behavior, or data semantics. |
| Impact | Split-brain authorization, incomplete hardening, and operator confusion |
| Likelihood | Low after DMIS-10, but high impact if reintroduced |
| Severity | High |

Required mitigations:

- keep executable legacy runtime paths out of the repo and deployment model
- keep CI and active docs aligned to Angular + Django as the only supported stack
- no implicit alternate runtime dependency for production workflows

## OWASP Risk Alignment

| OWASP Area | DMIS Current Concern |
| --- | --- |
| A01 Broken Access Control | Route inconsistency, tenant-scope reliance on application logic, alternate-runtime reintroduction risk |
| A02 Cryptographic Failures | Production-safe transport and cookie settings must be enforced consistently |
| A04 Insecure Design | Current-state and target-state docs were previously misaligned with the real platform |
| A05 Security Misconfiguration | Deploy checks already show critical production hardening gaps |
| A06 Vulnerable and Outdated Components | Reintroducing retired runtime components would increase platform complexity and review scope |
| A07 Identification and Authentication Failures | Auth optionality and dev impersonation are the highest current identity risks |
| A08 Software and Data Integrity Failures | Generated artifacts and workflow mutations need stronger durability and control |
| A09 Security Logging and Monitoring Failures | Telemetry and operational detection are not yet strong enough for production confidence |
| A10 SSRF and External Dependency Risks | Future async and external integrations need explicit allowlists, retries, and circuit breakers |

## Production Exit Criteria From This Threat Model

The following conditions should be met before production launch:

- no production path depends on dev-user impersonation
- no non-local deployment can run with auth disabled
- Flask remains fully decommissioned and no alternate runtime path is reintroduced
- tenant-safe authorization is validated across high-risk workflows
- global throttling and expensive-work offload are in place
- readiness, metrics, logging, and alerting exist for critical dependencies
- critical artifacts are durably stored
- security documentation reflects the active stack

## Review Triggers

Re-run this threat model when any of the following change:

- auth provider or token model
- tenant model or cross-tenant policy
- queueing or background processing architecture
- artifact storage design
- alternate runtime or decommission status
- deployment topology or operational hosting model
