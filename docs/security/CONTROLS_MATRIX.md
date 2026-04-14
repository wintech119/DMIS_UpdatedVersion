# DMIS Security Controls Matrix

Last updated: 2026-04-09
Status: Current-state controls and pre-production target controls

## Purpose

This matrix tracks the control posture required to move DMIS from active development into a production-ready state.

Status values:

- `Implemented`: materially present in the current stack
- `Partial`: present but incomplete, inconsistent, or not production-safe yet
- `Missing`: not yet in place
- `Planned`: agreed target control, not yet implemented

## Identity and Access Controls

| ID | Control | Current State | Target State | Status | Production Gate | Standards |
| --- | --- | --- | --- | --- | --- | --- |
| IAM-01 | Mandatory OIDC/JWT auth in non-local environments | Backend supports JWT/JWKS validation, but auth can still be disabled by environment | Authentication required in staging and production | Partial | Yes | ISO 27001, OWASP ASVS 2 |
| IAM-02 | No dev impersonation in production | Dev-user override still exists in Angular and Django dev paths | Build-time exclusion from production bundle and runtime hard-disable in production | Partial | Yes | OWASP ASVS 2 |
| IAM-03 | MFA for privileged roles | Not evidenced as enforced in active stack | MFA for system admins, tenant admins, and national privileged users | Missing | Yes | NIST CSF PR.AA |
| IAM-04 | Central RBAC enforcement | Django resolves roles and permissions centrally | Keep backend as source of truth, expand test coverage for critical roles | Partial | Yes | OWASP ASVS 4 |
| IAM-05 | Access review and role governance | Role mappings exist, but operational review cadence is not clearly documented | Quarterly privileged access review and auditable role changes | Missing | No | ISO 27001, NIST PR.AA |

## Tenant and Data Boundary Controls

| ID | Control | Current State | Target State | Status | Production Gate | Standards |
| --- | --- | --- | --- | --- | --- | --- |
| TEN-01 | Tenant membership enforcement | Tenant context and access checks exist in backend services | Mandatory validation for all tenant-sensitive workflows and query paths | Partial | Yes | OWASP ASVS 4 |
| TEN-02 | Cross-tenant action governance | Some policy controls exist for national/NEOC actions | Explicit approval, audit, and configuration governance for cross-tenant actions | Partial | Yes | ISO 27001 |
| TEN-03 | Least-privilege database access | Not fully evidenced in repo-level deployment posture | Dedicated production DB credentials with minimal permissions | Missing | Yes | NIST PR.AC |
| TEN-04 | Durable artifact storage | Some operational documents are still reconstructed from workflow state | Store immutable workflow artifacts in durable storage | Partial | Yes | NIST AU, ISO 27001 |
| TEN-05 | Data recovery validation | Backup targets exist in requirements, but restore evidence is not present here | Scheduled restore tests and documented RPO/RTO validation | Missing | Yes | ISO 22301 |

## Application and API Controls

| ID | Control | Current State | Target State | Status | Production Gate | Standards |
| --- | --- | --- | --- | --- | --- | --- |
| API-01 | Global API throttling | IFRC endpoint has local rate limiting; broad platform throttling is limited | Global throttling plus endpoint-specific quotas for expensive flows | Partial | Yes | OWASP ASVS 4 |
| API-02 | Input validation and output safety | Mixed; modern Angular patterns reduce some client risk, but backend patterns are uneven | Standard validation boundaries and safe error behavior across all APIs | Partial | Yes | OWASP ASVS 5 |
| API-03 | Secure-by-default Django settings | Deploy warnings show missing production-safe settings when debug posture is active | Secure cookies, HSTS, HTTPS redirect, and hardened non-local config | Partial | Yes | OWASP ASVS 14 |
| API-04 | Async offload for expensive work | Most work remains synchronous in request paths | Worker queue for exports, notifications, artifact generation, and retries | Missing | Yes | ISO 25010, availability |
| API-05 | Idempotency and retry safety | Not consistently evident across mutating operations | Idempotent write patterns for high-risk workflows and background jobs | Missing | Yes | Reliability |
| API-06 | Structured correlation and error handling | Limited evidence of correlation IDs or normalized cross-layer error handling | Request IDs, trace IDs, and structured service errors | Missing | No | NIST DE, ISO 25010 |

## Frontend Controls

| ID | Control | Current State | Target State | Status | Production Gate | Standards |
| --- | --- | --- | --- | --- | --- | --- |
| FE-01 | Production-safe auth and HTTP platform layer | Angular app only has dev-user interceptor globally | Central auth, timeout, retry, correlation, and error interceptors | Partial | Yes | OWASP ASVS 4 |
| FE-02 | Consistent route protection | Some routes use guards; coverage is inconsistent | All sensitive feature routes protected consistently | Partial | Yes | Broken access control |
| FE-03 | Server-bounded data loading | Several screens transform full datasets client-side | Pagination, filtering, and aggregation pushed server-side where needed | Partial | No | Performance, scalability |
| FE-04 | Durable UX state strategy | Several workflows use local storage for state continuity | Local state only for non-critical convenience; critical drafts recover server-side | Partial | No | Reliability |
| FE-05 | Client observability | Placeholder console logging is still present | Structured client error reporting and trace correlation | Missing | No | NIST DE |

## Platform and Infrastructure Controls

| ID | Control | Current State | Target State | Status | Production Gate | Standards |
| --- | --- | --- | --- | --- | --- | --- |
| OPS-01 | Redis as shared coordination layer | Redis is optional and code falls back to LocMemCache | Redis mandatory in production, monitored as a critical dependency | Partial | Yes | Availability |
| OPS-02 | Health checks | Separate liveness and readiness endpoints now exist with DB/Redis verification, but broader dependency coverage is still incomplete | Separate liveness and readiness checks with dependency verification | Partial | Yes | ISO 22301 |
| OPS-03 | Metrics, logs, traces, alerting | API request IDs, structured runtime/auth/readiness/error logs, and operator alert guidance exist, but worker, edge, and metrics coverage remain incomplete | End-to-end observability for API, workers, DB, Redis, and edge components | Partial | Yes | NIST DE, ISO 27001 |
| OPS-04 | Backup and restore procedures | Recovery and rollback guidance is documented, but tested restore evidence remains limited | Tested backup, restore, and rollback procedures | Partial | Yes | ISO 22301 |
| OPS-05 | High-availability data and cache posture | PostgreSQL is primary data store; HA specifics are not operationalized here | Primary/replica DB posture and HA Redis with failover expectations | Planned | No | Availability |
| OPS-06 | Secrets management and rotation | Environment-driven configuration exists | Managed secret store, rotation policy, and separation by environment | Partial | Yes | ISO 27001 |
| OPS-07 | Edge protection | Reverse proxy guidance exists but is stale | WAF/CDN, TLS, rate limiting, and hardened ingress config aligned to active stack | Partial | Yes | OWASP ASVS 14 |

## Governance and Delivery Controls

| ID | Control | Current State | Target State | Status | Production Gate | Standards |
| --- | --- | --- | --- | --- | --- | --- |
| GOV-01 | Current-state architecture documentation | Security and deployment docs were previously misaligned with the real stack | Docs match the active Angular/Django architecture and transition status | Partial | Yes | ISO 27001 |
| GOV-02 | Threat model maintenance | Prior threat model was stale | Threat model reviewed on architecture and auth changes | Partial | No | OWASP ASVS 1 |
| GOV-03 | Vulnerability scanning | Some scanning artifacts exist | SAST, dependency, and config scanning enforced in CI for release branches | Partial | No | Secure SDLC |
| GOV-04 | Production release gates | Some handoff docs exist, but hardening gates are not yet one coherent checklist | Release checklist includes security, observability, backup, rollback, and Flask retirement | Missing | Yes | Governance |
| GOV-05 | Flask retirement control | A sprint cutover doc exists, but full platform retirement is still in progress | Flask isolated, redirected, then removed from the live and deployed path | Partial | Yes | Change management |

## Summary

| Status | Count |
| --- | ---: |
| Implemented | 0 |
| Partial | 18 |
| Missing | 10 |
| Planned | 1 |

## Highest-Priority Control Gaps

The most important controls to close before production are:

1. mandatory production authentication and removal of dev impersonation from production paths
2. secure Django deployment defaults in non-local environments
3. Redis as a required production dependency
4. worker-based async processing for expensive and retriable workloads
5. readiness checks, telemetry, alerting, and tested recovery
6. tenant-safe enforcement and durable artifact storage
7. full retirement of Flask from live workflows

## Review Cadence

- weekly while the platform is in active hardening
- before each release-candidate decision
- after any auth, tenant, queue, or deployment-model change
