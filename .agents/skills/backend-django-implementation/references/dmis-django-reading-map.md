# DMIS Django Reading Map

A canonical pointer-set the skill loads on demand. Verified 2026-04-25.
This file is duplicated across the three backend skills; the pre-commit drift hook keeps the copies identical.

Read `backend/lessons_learned.md` before changing workflow, tenancy, queue-routing, or approval logic.
Consult approved feature docs in `../docs` before implementing features.
Treat `../docs/adr/system_application_architecture.md` as the primary architecture source of truth.

## Apps and entry points
- `backend/dmis_api/` — project config (`settings.py`, `urls.py`, `wsgi.py`)
- `backend/api/` — auth, `Principal`, RBAC, tenancy, task engine
- `backend/replenishment/` — EP-02 needs lists, transfers, donations, procurement, criticality
- `backend/operations/` — relief requests, eligibility, packaging, dispatch, receipt
- `backend/masterdata/` — config-driven CRUD over 12 legacy reference tables
- `backend/manage.py` — Django entry point; CWD for `python manage.py …`

## URL routes (under `/api/v1/`)
- `api.urls` — health, `/auth/whoami/`, `/auth/local-harness/`
- `replenishment.urls` — needs lists, warehouses, procurement, suppliers, tenants, phase windows
- `operations.urls` — requests, eligibility, packages, dispatch, receipt, tasks
- `masterdata.urls` — generic CRUD per `table_key`

## Data access layer
- `backend/replenishment/services/data_access.py` — raw SQL against legacy PostgreSQL tables. Use this; do NOT use Django ORM for legacy data.
- `inventory_id == warehouse_id` (1:1 mapping in legacy schema).
- Burn rate from `reliefpkg` + `reliefpkg_item` (statuses `D`, `R`).

## Validation helpers (must reuse — never duplicate)
- `backend.replenishment.views:_parse_positive_int(value, field_name, errors)` — int regex + type + > 0 range
- `backend.replenishment.views:_parse_optional_bool(value, field_name, errors)` — whitelist boolean parse
- `backend.replenishment.views:_parse_optional_datetime(value, …)` — ISO with timezone awareness
- `backend.replenishment.views:_parse_selected_item_keys(raw_keys, errors)` — array of `\d+_\d+` keys
- `backend.masterdata.services.validation:validate_record(cfg, data)` — config-driven field validation (required, max_length, pattern, choices, uniqueness, FK existence, cross-field rules)

## AuthN / AuthZ
- `backend/api/authentication.py` — `KeycloakJWTAuthentication`, `LegacyCompatAuthentication`, `Principal(user_id, username, roles, permissions)`
- `backend.api.rbac:resolve_roles_and_permissions(request, request.user)` — call inside views before authorizing actions
- `Principal.permissions` — list-checked before reads/writes
- DB RBAC tables: `role`, `permission`, `user_role`, `role_permission` when `AUTH_USE_DB_RBAC=1`
- Local-harness only: `LegacyCompatAuthentication` accepts the allowlisted `X-DMIS-Local-User` header; backend rejects legacy `X-Dev-User`.

## Tenant safety
- `TENANT_SCOPE_ENFORCEMENT=1` is the canonical default.
- Every queryset and every raw SQL filter MUST include `tenant_id`.
- Cross-tenant reads only via `national.read_all_tenants`.
- Cross-tenant writes only via `national.act_cross_tenant`.

## Tests
- Per app: `tests.py` and `tests_*.py` (no separate `tests/` package).
- Standard override for legacy auth-disabled tests: `@override_settings(AUTH_ENABLED=False, DEV_AUTH_ENABLED=True, TEST_DEV_AUTH_ENABLED=True)`.
- Negative IDOR test required for every endpoint that takes an object ID (different tenant returns 404, different role returns 403).
- Workflow contract tests pattern: see `operations/tests_contract_services.py`.

## Migrations
- `python manage.py migrate --check` is the gate.
- Phased rollout for risky changes: add nullable column → deploy code that writes both shapes → backfill safely → make required.
- Legacy data is dirty; assume invalid rows exist when tightening constraints.

## What NOT to do
- Do NOT use Django ORM for legacy tables — go through `data_access.py`.
- Do NOT write new `_parse_*` helpers — reuse the ones above.
- Do NOT use f-strings or `.format()` in raw SQL — use `%s` parameterized placeholders.
- Do NOT scope object access by ID alone; always include tenant + role + object-level checks.
- Do NOT introduce ViewSets where the existing pattern is function-based `@api_view`.
