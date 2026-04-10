# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

DMIS (Disaster Management Information System) for Jamaica's ODPEM. Three main modules:
- **Replenishment (EP-02)**: Stock monitoring, burn rate, time-to-stockout, needs lists, Three Horizons fulfillment (Transfers -> Donations -> Procurement)
- **Operations**: Relief request intake, eligibility review, package fulfillment, dispatch, receipt confirmation
- **Master Data**: Config-driven CRUD for 12 legacy reference tables (items, warehouses, agencies, etc.)

## Tech Stack

- **Frontend**: Angular 21+ (standalone components, Angular Material, SCSS, TypeScript 5.9)
- **Backend**: Django 4.2 LTS, Django REST Framework, raw SQL data access for legacy tables
- **Database**: PostgreSQL 16+
- **Auth**: Keycloak OIDC (production), `DEV_AUTH_ENABLED=1` (development), DB RBAC via `AUTH_USE_DB_RBAC`
- **Node**: ^20.19.0 || ^22.12.0 || ^24.0.0
- **Python**: >=3.11

## Temporary Supply-Chain Hold

- Do not run `npm run install`.
- Do not download, install, fetch, or update anything from `axios`, including the `axios` npm package and any artifacts sourced from it.
- If a task would require either action, stop and ask the user for an alternative until this hold is removed.

## Development Commands

### Backend (from `backend/` directory)
```bash
# Run dev server (HTTP only, port 8001)
python manage.py runserver 0.0.0.0:8001

# Run all tests for a specific app
python manage.py test replenishment --verbosity=2
python manage.py test masterdata.tests --verbosity=2
python manage.py test operations --verbosity=2
python manage.py test api --verbosity=2

# Run a single test class
python manage.py test replenishment.tests_tenant_views.TenantApprovalPolicyTests --verbosity=2

# Run a single test method
python manage.py test replenishment.tests_tenant_views.TenantApprovalPolicyTests.test_get_policy --verbosity=2

# Check migrations
python manage.py showmigrations masterdata
python manage.py migrate --check

# Django settings module
DJANGO_SETTINGS_MODULE=dmis_api.settings
```

### Frontend (from `frontend/` directory)
```bash
npm start          # ng serve (proxies /api to localhost:8001)
npm run build      # ng build (production by default)
npm run lint       # ng lint (eslint with angular-eslint)
npm test           # ng test (Karma + Jasmine)
npm test -- --watch=false   # Single run
```

### Windows Notes
- On PowerShell, use `npm.cmd` instead of `npm` if script execution is blocked
- Python venv: `.venv\Scripts\Activate.ps1` (or `activate.bat` in cmd)
- Backend requirements: `pip install -r backend/requirements.txt`
- Frontend deps: `cd frontend && npm ci` only after confirming it will not fetch `axios`; otherwise do not run dependency installation while the hold is active

## Architecture

### Backend Structure
```
backend/
  dmis_api/          # Django project config (settings.py, urls.py, wsgi.py)
  api/               # Core: auth (Principal), RBAC, tenancy, task engine
  replenishment/     # EP-02: needs lists, transfers, donations, procurement, criticality
  operations/        # Relief requests, eligibility, packaging, dispatch, receipt
  masterdata/        # Config-driven CRUD for 12 legacy reference tables
```

### URL Routing
All API routes under `/api/v1/`:
- `/api/v1/` - `api.urls` (health check, `/auth/whoami/`, `/auth/dev-users/`)
- `/api/v1/replenishment/` - `replenishment.urls` (needs lists, warehouses, procurement, suppliers, tenants, phase windows)
- `/api/v1/operations/` - `operations.urls` (requests, eligibility, packages, dispatch, receipt, tasks)
- `/api/v1/masterdata/` - `masterdata.urls` (generic CRUD for reference tables, IFRC suggest)

### Authentication Flow
1. **Production**: Keycloak JWT -> `KeycloakJWTAuthentication` validates via JWKS -> extracts `Principal(user_id, username, roles, permissions)`
2. **Dev mode**: `DEV_AUTH_ENABLED=1` -> `DevAuthentication` creates Principal from `X-Dev-User-Id` header (or defaults)
3. **RBAC**: DB tables `role`, `permission`, `user_role`, `role_permission` when `AUTH_USE_DB_RBAC=1`; otherwise roles from JWT claim

### Data Access Pattern
- `replenishment/services/data_access.py` and `operations/services.py` use **raw SQL** against legacy PostgreSQL tables (not Django ORM for legacy data)
- `inventory_id` = `warehouse_id` (1:1 mapping in legacy schema)
- Burn rate calculated from `reliefpkg` + `reliefpkg_item` tables
- Needs list workflow state managed via `workflow_store.py` (file-based) or `workflow_store_db.py` (DB-backed)

### Frontend Structure
```
frontend/src/app/
  core/              # Auth guard (appAccessGuard), dev-user interceptor, app-access service
  layout/            # Sidenav shell
  shared/            # Shared components (dmis-step-tracker)
  replenishment/     # Dashboard, needs-list wizard/review, transfers, donations, procurement
  operations/        # Relief requests, eligibility, fulfillment, dispatch, receipt, task center
  master-data/       # Config-driven table management, IFRC suggest
```

### Frontend Patterns
- **Routing**: Lazy-loaded feature routes (`loadChildren`), guarded with `appAccessGuard` using `accessKey` data
- **API Proxy**: `proxy.conf.cjs` forwards `/api`, `/relief-requests`, `/eligibility`, `/packaging`, `/dashboard`, `/static` to `http://localhost:8001`
- **Auth**: `devUserInterceptor` adds `X-Dev-User-Id` header in dev mode
- **Schematics**: SCSS by default, `app`/`dmis` prefixes for components, kebab-case element selectors, camelCase attribute selectors

### ESLint Rules
- Component selectors: `app-*` or `dmis-*` (kebab-case, element type)
- Directive selectors: `app*` or `dmis*` (camelCase, attribute type)
- Template accessibility rules enabled

## Mandatory Architecture Review

For medium- and high-risk plans or implementation work, use the shared architecture reviewer at `.agents/skills/system-architecture-review/SKILL.md` before the work is treated as complete.

Primary source-of-truth order:
1. `docs/adr/system_application_architecture.md`
2. `docs/security/SECURITY_ARCHITECTURE.md`
3. `docs/security/THREAT_MODEL.md`
4. `docs/security/CONTROLS_MATRIX.md`
5. `docs/implementation/production_readiness_checklist.md`
6. `docs/implementation/production_hardening_and_flask_retirement_strategy.md`

Expect two checkpoints for medium- and high-risk work:
- review before finalizing the plan
- review again before final output after implementation

Use the local project instructions in `frontend/AGENTS.md` and `backend/AGENTS.md` when work is scoped there.
Treat `system_application_architecture.md` as the canonical architecture baseline.
Treat the hardening and Flask-retirement strategy as supporting execution guidance, not the main architecture reference.
If the architecture review returns `Misaligned`, do not treat the work as complete.
## Key Business Logic

### Event Phases
| Phase | Demand Window | Planning Window |
|-------|---------------|-----------------|
| SURGE | 6 hours | 72 hours |
| STABILIZED | 72 hours | 7 days |
| BASELINE | 30 days | 30 days |

### Core Formulas
```
Burn Rate = Fulfilled Qty / Demand Window (hrs)
Time-to-Stockout = Available Stock / Burn Rate
Required Qty = Burn Rate x Planning Window x 1.25 (safety factor)
Gap = Required Qty - (Available + Confirmed Inbound)
```

### Status Severity
- **CRITICAL** (red): Time-to-Stockout < 8 hours
- **WARNING** (amber): 8-24 hours
- **WATCH** (yellow): 24-72 hours
- **OK** (green): > 72 hours

### Three Horizons
- **A (Transfers)**: 6-8 hour lead time, use first
- **B (Donations)**: 2-7 day lead time, fills remaining gap
- **C (Procurement)**: 14+ day lead time, last resort

## Primary User: Kemar (Logistics Manager)

Field-first mindset, works on mobile during hurricane response. Low tolerance for messy data. Needs fast, accurate, real-time visibility. "If it's not logged, it didn't happen."

**Design test**: "Would Kemar be able to use this in the field during a hurricane response?" If no, simplify it.

## Non-Negotiable Requirements

1. **No auto-actions**: System recommends, humans approve
2. **Audit everything**: All changes logged with user, timestamp, reason
3. **Data freshness visible**: User must know when data is stale (HIGH <2h, MEDIUM 2-6h, LOW >6h)
4. **Strict inbound**: Only count DISPATCHED transfers, IN-TRANSIT donations, SHIPPED procurement
5. **Mobile-friendly**: Cards stack vertically, tables become card lists on small screens

## Working Rules

### Regression Guardrails

**Principle**: The current local codebase is the authoritative implementation baseline. Do not regress the repo toward older commit-era structures, templates, workflow logic, or legacy code paths when newer local patterns already exist, unless the approved docs in `docs/` explicitly require that change.

**Frontend (Angular, templates, components, tests)**:
- Preserve and extend the existing component formats, templates, layout structure, interaction patterns, and test structure in the current frontend codebase instead of rewriting them toward older commit versions.
- Before changing a component or adding a related one, inspect the current nearby implementation and extend the existing pattern.
- If a newer local frontend pattern already exists, do not reintroduce a superseded legacy template, layout, or older commit-era structure unless the approved docs explicitly require that change.

**Backend (Django apps, services, APIs, validation, workflow, tests)**:
- The existing current backend service, API, validation, workflow, and test patterns are authoritative and must not be regressed to older commit versions.
- Before refactoring or extending backend logic, inspect the current app and module shape and preserve the present architecture unless the approved docs require a different direction.
- Do not resurrect removed or superseded legacy backend code paths, structures, or older workflow implementations simply because they existed in prior commits.

## Coding Standards

### Angular
- Standalone components (Angular 21+ default)
- Signals-based reactivity preferred over RxJS where appropriate
- OnPush change detection where possible
- Services for API calls, components for display
- Reactive forms for inputs
- Status colors must have text/icon backup (accessibility)
- Loading states use skeletons, not spinners

### Django
- Function-based views with `@api_view` decorators
- Raw SQL via `data_access.py` for legacy tables; Django ORM for new EP-02 tables
- Permission checks via `Principal.permissions` list from RBAC
- `manage.py` is in `backend/` (the Django project root)
- Tests use `@override_settings(AUTH_ENABLED=False, DEV_AUTH_ENABLED=True, TEST_DEV_AUTH_ENABLED=True)` pattern
- Test files: `tests.py` and `tests_*.py` per app (not in a separate `tests/` package)

### Input Validation: Sanitize All User Inputs

**Principle**: Backend is the enforcement layer. Frontend provides UX feedback. Never trust client-side validation alone.

#### Backend (Django views)

**Reuse existing helpers** in `replenishment/views.py`:
- `_parse_positive_int(value, field_name, errors)` â€” validates integers with regex, type check, and >0 range
- `_parse_optional_bool(value, field_name, errors)` â€” whitelist-based boolean parsing
- `_parse_optional_datetime(value, field_name, errors)` â€” ISO datetime with timezone awareness
- `_parse_selected_item_keys(raw_keys, errors)` â€” array of `\d+_\d+` formatted keys

**Reuse masterdata validation framework** in `masterdata/services/validation.py`:
- `validate_record(cfg, data)` â€” config-driven field validation (required, max_length, pattern, choices, uniqueness, FK existence, cross-field rules)

**Rules for all new and modified views**:
- **String fields**: Always enforce `max_length` matching the DB column. Reject with 400, don't silently truncate
- **Enum/status fields**: Whitelist allowed values with explicit sets. Use `.strip().upper()` before comparison
- **Numeric params**: Use `_parse_positive_int()` or validate type and range explicitly
- **Free-text fields** (reason, notes, comment): Enforce max_length (typically 500), `.strip()` before storage
- **Query params** (search, order_by, status): Validate against allowed values; for `order_by` use a whitelist of column names
- **Array inputs**: Validate type is list, enforce max length on the array, validate each element
- **Date fields**: Use `_parse_optional_datetime()` â€” never pass raw strings to SQL or ORM

**SQL safety**:
- All raw SQL must use `%s` parameterized placeholders â€” never f-strings or `.format()` with user values
- Table/column names in dynamic SQL must come from hardcoded registries (e.g., `TABLE_REGISTRY`) or be quoted via `connection.ops.quote_name()`
- Schema names must be validated with `re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema)` (see `masterdata/services/data_access.py:66`)

#### Frontend (Angular)

**Rules for all form inputs**:
- Every `<input>` and `<textarea>` must have a `maxlength` attribute matching the backend DB column limit
- Every `FormControl` for text fields must include `Validators.maxLength(n)` in addition to the template attribute
- Required fields: `Validators.required` on the `FormControl` + `required` attribute in template
- Numeric fields: `Validators.min()` / `Validators.max()` + HTML `type="number"` with `min`/`max` attributes
- `.trim()` user text before submitting to API (reason, notes, comments)
- No `innerHTML` bindings with user-provided content â€” use `{{ interpolation }}` (Angular auto-escapes)

### Secret & API Key Protection

- **Never commit secrets**: API keys, tokens, passwords, `DJANGO_SECRET_KEY`, DB credentials, Keycloak client secrets, and Ollama keys must never appear in source code, templates, or commit history
- **Environment variables only**: All secrets are loaded from `backend/.env` (local) or environment variables (production). See `dmis_api/settings.py` for the `.env` loader
- **`.env` is gitignored**: Only `.env.example` (with placeholder values) may be committed. Never copy real values into example files
- **Frontend**: No secrets in Angular code â€” the frontend is a public bundle. Auth tokens come from Keycloak at runtime, not from config files. `environment.ts` must contain only non-secret config (API base URLs, feature flags)
- **Git hygiene**: Before committing, verify no secrets in staged files. Never add `.env`, `credentials.json`, `*.pem`, or `*.key` files to git
- **If a secret is accidentally committed**: Rotate it immediately â€” removing from history is not sufficient since it may already be cached or cloned

### Rate Limiting Policy

Enforce per-user + per-tenant + per-IP rate limits. During disaster SURGE phases, field users cannot afford to be blocked â€” limits are tuned to protect the system without impeding legitimate emergency operations.

#### Tiered Limits (per authenticated user per minute)

| Tier | Limit | Endpoints |
|------|-------|-----------|
| **Read** | 120 req/min | Stock status, dashboards, warehouse lists, needs list GET, queues, lookups, `whoami` |
| **Write** | 40 req/min | Needs list draft/edit, relief request create/update, procurement create/edit, supplier CRUD, master data CRUD |
| **Workflow** | 15 req/min | Submit, approve, reject, return, escalate, cancel, allocation commit, override approve |
| **High-risk ops** | 10 req/min | Dispatch handoff, receipt confirmation, mark-dispatched, mark-received, mark-completed, stock location assignment, repackaging |

#### Special Limits

| Action | Limit | Scope |
|--------|-------|-------|
| Login attempts | 5 per 15 min | Per account + per IP |
| File exports (CSV/PDF) | 5 per min | Per user |
| IFRC suggest (LLM) | 30 per min | Per user (already configured in `settings.py` `IFRC_RATE_LIMIT_PER_MINUTE`) |
| Bulk operations (bulk-submit, bulk-delete) | 5 per min | Per user |
| Public/unauthenticated endpoints | 60 per min | Per IP |

#### Surge-Phase Handling

- **Burst-tolerant rate limiting**: Use a token-bucket or sliding-window algorithm (not fixed-window) so short bursts during SURGE don't trigger false 429s. A field user rapidly refreshing stock status after a warehouse update must not be penalized
- **IP as secondary signal**: For authenticated users, enforce limits primarily by `user_id + tenant_id`. IP is a secondary signal only â€” field teams often share mobile hotspots or satellite links where many users appear behind a single IP
- **Temporary surge overrides**: Designated field roles (`LOGISTICS_OFFICER`, `LOGISTICS_MANAGER`, `AGENCY_DISTRIBUTOR`, and roles with `national.act_cross_tenant`) get 2x limits automatically when an active event exists in SURGE or STABILIZED phase
- **429 spike monitoring**: During active events, alert on sustained 429 rates (>5% of requests over a 5-minute window). This indicates limits are too aggressive for the operational tempo and must be tuned in real-time

#### Implementation Rules

- **Enforcement key**: `user_id + tenant_id` for authenticated requests (IP as tiebreaker for abuse detection); IP-only for public/unauthenticated
- **Backend**: Use Django cache framework (Redis in production, LocMemCache in dev) for counters
- **Idempotency keys**: Require on critical write actions (approve, dispatch, receipt) to prevent duplicate processing on retries
- **429 responses**: Return `Retry-After` header with seconds until reset. Frontend should show a toast, not a hard error
- **System integrations**: Approved service accounts may have elevated limits configured via environment variables
- **Monitoring**: Log all rate-limit hits with user, tenant, endpoint tier, and active event phase; tune thresholds based on production usage data

### Insecure Direct Object Reference (IDOR) Prevention

Every endpoint that accepts an object ID (needs list, relief request, procurement, warehouse, transfer, etc.) must verify the requesting user is authorized to access that specific object â€” not just that they hold the right permission.

#### Authorization Checks by Layer

**1. Tenant scoping (mandatory when `TENANT_SCOPE_ENFORCEMENT=1`)**
- Every object query must filter by the authenticated user's `tenant_id` from `Principal` context
- Cross-tenant access only permitted for principals with `national.read_all_tenants` (read) or `national.act_cross_tenant` (write)
- Raw SQL queries must include `WHERE tenant_id = %s` â€” never rely on the URL path alone

**2. Ownership / role-gated access**
| Resource | Who can read | Who can write/act |
|----------|-------------|-------------------|
| Needs list | Creator, assigned reviewers, tenant logistics roles, national roles | Only current workflow actor (submitter can't approve their own) |
| Relief request | Creator, eligibility reviewers, fulfillment staff, dispatch staff | Role appropriate to current workflow step |
| Procurement order | Creator, approvers within tenant | Step-appropriate role only |
| Warehouse / inventory | Any authenticated user within tenant | Logistics roles with warehouse-level assignment |
| Master data records | Any user with `masterdata.view` | `SYSTEM_ADMINISTRATOR` only for create/edit/inactivate |

**3. Implementation rules for views**
- After fetching an object by ID, **always check** `obj.tenant_id == request_tenant_id` (or national override) before returning data
- Never trust the URL path parameter alone â€” `/api/v1/replenishment/needs-list/{id}` must verify the caller can see that specific needs list
- For list endpoints, filter querysets/SQL by tenant â€” don't fetch all then filter in Python
- Workflow state transitions must verify the caller holds the permission for the *current* state, not just any workflow permission
- Use `resolve_roles_and_permissions()` from `api/rbac.py` to get the full permission set, then check against the specific action

**4. Frontend guard alignment**
- `appAccessGuard` and `appAccessMatchGuard` control route visibility but are NOT security â€” backend must independently enforce
- Never hide a UI element as a substitute for backend authorization. Hidden buttons can still be called via devtools

**5. Testing IDOR**
- Every endpoint test suite must include a negative test: user A creates an object, user B (same permission, different tenant) attempts to access it and gets 403/404
- Workflow tests must verify that the wrong-role user cannot advance a state (e.g., submitter cannot approve)

### Error Handling
- Toast for network errors with retry
- Inline validation for forms
- Empty states with helpful actions
- Never fail silently

## Workflow Orchestration

1. **Plan First**: Enter plan mode for non-trivial tasks (3+ steps). Write plan to `tasks/todo.md`
2. **Subagents**: Use liberally for research and parallel analysis
3. **Self-Improvement**: After corrections, update `tasks/lessons.md`
4. **Verify Before Done**: Run tests, check logs, demonstrate correctness
5. **Autonomous Bug Fixing**: Just fix it. Point at logs, errors, tests - resolve them
6. **Simplicity First**: Make every change as simple as possible. Minimal impact. No temporary fixes.


