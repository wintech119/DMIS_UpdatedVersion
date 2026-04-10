# Backend Project Instructions

## Purpose
- Before implementing, consult the approved feature docs in `../docs`.
- This project owns schema, migrations, APIs, services, backend validation, security, auditability, and backend tests.
- Do not invent new business rules if requirements are unclear; instead flag the gap.

## Scope
- Django settings, apps, models, serializers, views, services, permissions, checks, and migrations live here.
- Backend behavior should follow approved requirements, contracts, and decisions documented in `../docs`.

## Working Rules
- Preserve API compatibility unless the approved docs explicitly call for a breaking change.
- Treat auditability and traceability as first-class concerns for approvals, overrides, and operational actions.
- Validate schema-affecting changes against the actual database metadata when available.
- Prefer focused backend tests near the changed app, plus `manage.py check` for lightweight validation.
- If frontend assumptions conflict with backend reality, document the mismatch and resolve it through `../docs`.
- Read `backend/lessons_learned.md` before changing sensitive workflow, tenancy, queue-routing, or approval logic.
- If a real bug reveals a reusable backend lesson, add or update an entry in `backend/lessons_learned.md`.
- Proactively disclose in your closeout when a change touches an area already covered by `backend/lessons_learned.md`, and confirm the relevant regression tests were run.
- Never expose API keys, tokens, client secrets, passwords, signing keys, or connection strings in code, logs, screenshots, commits, pull requests, issues, docs, or test fixtures.
- If a real secret is encountered, redact it immediately and refer to it only with placeholders such as `<REDACTED>` or `YOUR_API_KEY`.
- Use environment variables or the existing secret-management pattern for all credentials; never hardcode live secret values.
- When debugging or sharing examples, only use masked values and never print full secret material in terminal output or agent responses.

## Mandatory Architecture Review
- For medium- and high-risk backend work, use the shared architecture reviewer at `../.agents/skills/system-architecture-review/SKILL.md` before finalizing a plan.
- Run the same architecture review again before final output when implementation work touches architecture-sensitive backend areas.
- Treat `../docs/adr/system_application_architecture.md` as the primary architecture source of truth.
- Treat `../docs/security/SECURITY_ARCHITECTURE.md`, `../docs/security/THREAT_MODEL.md`, and `../docs/security/CONTROLS_MATRIX.md` as the primary security and control references.
- Treat `../docs/implementation/production_readiness_checklist.md` as the release-gating reference.
- Treat `../docs/implementation/production_hardening_and_flask_retirement_strategy.md` as supporting execution guidance, not the main architecture baseline.

### Mandatory backend review triggers
- auth, RBAC, tenancy, impersonation, tokens, sessions, route protection, or privileged-role handling
- secure settings, secrets, headers, cookies, CORS, uploads, input validation, object access, or rate limiting
- raw SQL, Redis, caching, queues, workers, object storage, or external integrations
- workflow logic for approvals, dispatch, receipt, exports, audit evidence, or durable artifact handling
- deployment, readiness, liveness, observability, backup, restore, rollback, or HA posture
- any work that could expand Flask dependence or weaken the Angular + Django target architecture

### Low-risk exemptions
- typo-only documentation edits
- comment-only changes
- isolated tests that do not alter behavior or contracts

### Backend architecture expectations
- Keep backend authorization and tenant-safe enforcement authoritative.
- Follow the canonical validation and rate-limiting standards in `../docs/security/SECURITY_ARCHITECTURE.md`.
- Do not accept correctness-critical production behavior that depends on in-process memory instead of Redis.
- Prefer service-layer orchestration, durable artifact persistence, and async offload for expensive or retryable work.
- Call out any deviation from the hardening baseline or target architecture.
- If the architecture review returns `Misaligned`, do not treat the work as complete.
## Regression Guardrails
- Treat the current backend codebase as the authoritative baseline for services, APIs, workflow logic, validation patterns, architecture, and test structure.
- Before refactoring or extending backend logic, inspect the current app and module implementation and preserve the present architecture instead of restoring an older commit version.
- Do not resurrect removed or superseded backend code paths, workflow structures, or legacy implementations unless the approved docs explicitly require that change.

## Input Validation
- Sanitize all user inputs.
- Validate and normalize all external input at the API, serializer, form, and service boundaries.
- Never trust client-supplied values for permissions, identity, pricing, status transitions, or other sensitive business logic.

## Object Access Control
- Prevent insecure direct object references on all APIs, views, downloads, exports, and workflow actions.
- Never authorize access to a record by ID alone; always scope object lookup by the authenticated user's tenant, role, and object-level permissions.
- Use server-side ownership and tenancy checks for every read, update, delete, approve, dispatch, receipt, and export action.
- Do not expose sequential or guessable identifiers when a safer public identifier pattern already exists for the workflow.
- Return `404` or equivalent safe responses for unauthorized object lookups where exposing object existence would leak sensitive information.

## Rate Limiting Policy
- Enforce per-user + per-tenant + per-IP rate limits.
- During disaster `SURGE` phases, field users cannot afford to be blocked; limits must protect the system without impeding legitimate emergency operations.

### Tiered Limits
| Tier | Limit | Endpoints |
|---|---|---|
| Read | 120 req/min | Stock status, dashboards, warehouse lists, needs list GET, queues, lookups, `whoami` |
| Write | 40 req/min | Needs list draft/edit, relief request create/update, procurement create/edit, supplier CRUD, master data CRUD |
| Workflow | 15 req/min | Submit, approve, reject, return, escalate, cancel, allocation commit, override approve |
| High-risk ops | 10 req/min | Dispatch handoff, receipt confirmation, mark-dispatched, mark-received, mark-completed, stock location assignment, repackaging |

### Special Limits
| Action | Limit | Scope |
|---|---|---|
| Login attempts | 5 per 15 min | Per account + per IP |
| File exports (CSV/PDF) | 5 per min | Per user |
| IFRC suggest (LLM) | 30 per min | Per user; already defined in `settings.py` |
| Bulk operations | 5 per min | Per user |
| Public/unauthenticated | 60 per min | Per IP |

### Implementation Rules
- Enforcement key: `user_id + tenant_id + IP` for authenticated traffic; IP-only for public traffic.
- Backend enforcement uses Django cache framework with Redis in production and `LocMemCache` in development.
- Use token-bucket or sliding-window enforcement with short burst tolerance; avoid rigid fixed-window counters on surge-critical endpoints.
- For authenticated traffic, treat IP as a secondary abuse signal. Shared NATs at EOCs, warehouses, shelters, and partner facilities must not block legitimate users who remain within per-user and per-tenant limits.
- Require idempotency keys on critical writes including approve, dispatch, and receipt actions.
- `429` responses must include a `Retry-After` header; frontend should show a toast, not a hard error screen.
- `national.act_cross_tenant` roles get 2x limits during active events as the emergency override path.
- Designated field operational roles can receive temporary surge overrides during active events for read, workflow, and high-risk endpoints when telemetry shows legitimate emergency demand.
- Approved system integrations can receive elevated limits through environment-variable configuration for service accounts.
- Log rate-limit hits and tune thresholds from production data.
- Monitor `429` rates by endpoint, tenant, role, and event phase; sustained spikes during active events require operational review and threshold tuning.

### Calibration Notes
- Read limits stay generous at `120 req/min` because dashboard and stock views are refreshed heavily during `SURGE`.
- Workflow and high-risk limits stay tight at `10-15 req/min` because these are human-paced actions; sustained hits usually indicate abuse, automation bugs, or runaway retries.
- Emergency override at 2x for national roles ensures NEOC and cross-tenant coordination users are not blocked during active events.
- Shared-network sites and intermittent connectivity can create bursty retries, scanner syncs, and clustered traffic; burst tolerance is required so legitimate field activity is not misclassified as abuse.
- Treat `SURGE` thresholds as tunable from drills and production telemetry; tighten them only with evidence that legitimate operations are not being impeded.
- IFRC suggest already has its own limiter in `settings.py`; keep this policy aligned with that implementation for consistency.


