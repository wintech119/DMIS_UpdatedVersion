# DMIS Backend Controls Checklist

Required controls for any backend change. Sources: `backend/AGENTS.md`, `docs/security/SECURITY_ARCHITECTURE.md`, `docs/security/CONTROLS_MATRIX.md`, `.claude/CLAUDE.md`.

## Input validation (canonical, backend-authoritative)
- Backend is the enforcement layer; never trust client values.
- Validate at API / serializer / form / service boundaries.
- Strings: enforce DB-column `max_length`; reject 400, do not silently truncate.
- Enum / status: whitelist sets, `.strip().upper()` before comparison.
- Numeric query params: use `_parse_positive_int` from `replenishment/views.py`.
- Free-text (reason, notes, comment): max 500, `.strip()` before storage.
- Order/sort params: column-name whitelist (no dynamic ORDER BY by user input).
- Array inputs: type-check, length limit, validate each element.
- Datetime: use `_parse_optional_datetime`, never raw strings into SQL or ORM.

## Raw SQL safety
- `%s` parameterized placeholders only.
- Table/column names from hardcoded `TABLE_REGISTRY` or via `connection.ops.quote_name()`.
- Schema-name validation: `re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema)` (see `masterdata/services/data_access.py:66`).

## AuthZ at the view
- Authenticate first; reject unauthenticated unless explicitly public.
- Resolve via `resolve_roles_and_permissions(request, request.user)` for action-level decisions.
- Check `Principal.permissions` before reading or mutating.
- DRF permission classes alone are NOT sufficient for action-level authorization.

## Tenant safety
- Filter every queryset and every raw SQL query by `tenant_id`.
- Reject reads where `obj.tenant_id != request_tenant_id` unless caller has cross-tenant permission.
- Background jobs must receive tenant context explicitly; no implicit "all tenants" jobs.
- Reports / exports / search / lookup endpoints must respect isolation.

## IDOR (insecure direct object reference) prevention
- Never authorize access to a record by ID alone.
- Scope object lookup by tenant + role + object-level permission.
- Return 404 (not 403) for unauthorized lookups where existence itself is sensitive.
- Every endpoint test suite includes a negative cross-tenant test.
- Workflow state transitions must verify the caller holds the permission for the *current* state.

## Rate-limit tier (assign for every new endpoint)

| Tier | Limit | Examples |
|---|---|---|
| Read | 120/min | Stock status, dashboards, lookups, `whoami` |
| Write | 40/min | Needs list draft/edit, request create/update, supplier CRUD, master data CRUD |
| Workflow | 15/min | Submit, approve, reject, return, escalate, cancel, allocation commit, override approve |
| High-risk | 10/min | Dispatch, receipt, mark-dispatched, mark-received, mark-completed, repackaging, stock location assignment |

Special:
- Login attempts: 5 per 15 min (account + IP)
- Exports CSV/PDF: 5/min per user
- IFRC suggest (LLM): 30/min per user (uses `IFRC_RATE_LIMIT_PER_MINUTE` in settings)
- Bulk operations: 5/min per user
- Public/unauthenticated: 60/min per IP

Enforcement rules:
- Key: `user_id + tenant_id + IP` for authenticated; IP-only for public.
- Backend cache: Django framework with Redis in any non-local environment; `LocMemCache` only for explicit local-only dev.
- Token-bucket / sliding-window with burst tolerance; not fixed-window.
- 429 response: include `Retry-After` header.
- Idempotency keys required on approve / dispatch / receipt actions.
- `national.act_cross_tenant` roles get 2x limits during active SURGE/STABILIZED events.

## Migration safety
- Avoid destructive changes without a transition plan.
- Add nullable column → deploy code that writes both shapes → backfill safely → make required.
- Avoid large blocking data migrations; batch and monitor.
- `migrate --check` must pass.

## Audit / compliance
- Capture user + timestamp + reason for approvals, edits, deletes, status changes, exports.
- Never log secrets, raw tokens, full PII, or full request bodies.
- Sensitive data minimized in serializer output and error responses.

## Production gates (from `CONTROLS_MATRIX.md`)
- `AUTH_ENABLED=1` in non-local; no dev impersonation paths reachable from production.
- Secure Django settings: `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `SECURE_HSTS_SECONDS`, `SECURE_CONTENT_TYPE_NOSNIFF`.
- Redis is mandatory for cache and rate limiting in non-local; no `LocMemCache` fallback.
- Async offload (Celery or equivalent) for expensive or retryable work.
- Readiness/liveness probes plus observability.
- Durable artifacts for waybills / exports.
- Flask remains decommissioned (DMIS-10); do not reintroduce executable Flask paths.
