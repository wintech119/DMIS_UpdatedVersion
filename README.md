# Disaster Management Information System (DMIS)

DMIS is delivered as a Django + Angular application.

## Stack

- Backend: Django 4.2 (LTS) + Django REST Framework
- Frontend: Angular 21+
- Database: PostgreSQL 16+
- Cache: Redis (required for `prod-like-local`, `shared-dev`, `staging`, and `production`; default in `local-harness`)
- Optional AI runtime: Ollama (for IFRC suggestion classification)

## Important architecture note

- The Flask stack is being phased out.
- New features are implemented only in Django + Angular.
- The local multi-user workflow harness is documented in `docs/implementation/dmis_00_local_multi_user_test_harness.md`.
- Architecture and security source-of-truth docs live in:
  - `docs/adr/system_application_architecture.md`
  - `docs/security/SECURITY_ARCHITECTURE.md`
  - `docs/security/THREAT_MODEL.md`
  - `docs/security/CONTROLS_MATRIX.md`
  - `docs/implementation/production_readiness_checklist.md`

## Runtime posture

- `scripts/run_new_stack.ps1` is a dev-only local harness helper. It is not a production, staging, shared-dev, or prod-like deployment path.
- The local multi-user harness is local-only and uses `X-DMIS-Local-User` only when the app is running in explicit `local-harness` mode.
- The default local-harness workflow is Redis-backed via `REDIS_URL=redis://localhost:6379/1`.
- `X-Dev-User` is retired and no longer supported.
- Shared dev, staging, and production must use real Keycloak/OIDC/JWT auth only. Dev-auth and local-harness flags are rejected outside explicit local-harness mode.
- Production-style Angular builds omit the local harness switcher/interceptor path rather than shipping it behind a runtime toggle.

## Runtime security matrix

| Environment | `DMIS_RUNTIME_ENV` | Debug / auth posture | HTTPS / cookie posture | HSTS posture | Proxy assumption | Intended use |
|---|---|---|---|---|---|---|
| Local developer harness | `local-harness` | `DJANGO_DEBUG=1`, `AUTH_ENABLED=0`, `DEV_AUTH_ENABLED=1`, `LOCAL_AUTH_HARNESS_ENABLED=1` | Local-friendly. HTTPS redirect and secure cookies may remain off. | Disabled. | No trusted reverse-proxy requirement. | Local-only multi-user workflow testing. `run_new_stack.ps1` targets this mode. |
| Prod-like local smoke test | `prod-like-local` | `DJANGO_DEBUG=0`, `AUTH_ENABLED=1`, `DEV_AUTH_ENABLED=0`, `LOCAL_AUTH_HARNESS_ENABLED=0` | Local-friendly. HTTPS redirect, secure cookies, and HSTS may remain off. | Disabled. | No trusted reverse-proxy requirement. | Optional local smoke test with real auth config. Use `DMIS_SKIP_LOCAL_ENV=1` so `.env.local` does not re-enable the harness. |
| Shared dev | `shared-dev` | `DJANGO_DEBUG=0`, real OIDC/JWT auth only | HTTPS redirect on, secure cookies on. | `3600` seconds, no subdomain include, no preload. | Trusted TLS-terminating ingress forwards `X-Forwarded-Proto`. | Shared environment with production-like security posture. No local header switching. |
| Staging | `staging` | `DJANGO_DEBUG=0`, real OIDC/JWT auth only | HTTPS redirect on, secure cookies on. | `86400` seconds, no subdomain include, no preload. | Trusted TLS-terminating ingress forwards `X-Forwarded-Proto`. | Production-like pre-release validation. No local header switching. |
| Production | `production` | `DJANGO_DEBUG=0`, real OIDC/JWT auth only | HTTPS redirect on, secure cookies on. | `31536000` seconds, `includeSubDomains=1`, preload opt-in only. | Trusted TLS-terminating ingress forwards `X-Forwarded-Proto`. | Live posture. Real auth only, fail-closed on incompatible config. |

## Redis posture

| Environment | Redis expectation | If Redis is absent |
|---|---|---|
| `local-harness` | Recommended and used by default in the documented harness workflow | Allowed only as an explicit local-only degraded mode when `REDIS_URL` is unset |
| `prod-like-local` | Required | Startup fails closed |
| `shared-dev` | Required | Startup fails closed |
| `staging` | Required | Startup fails closed |
| `production` | Required | Startup fails closed |

Redis backs shared counters, rate limiting, and circuit-breaker state. DMIS does not allow non-local runtimes to silently fall back to `LocMemCache`.

Frontend note: production-style builds file-replace the local harness switcher/interceptor with no-op implementations. The Angular client now expects a deployment-supplied runtime OIDC config in `frontend/public/auth-config.json`, uses Authorization Code + PKCE for the non-local login path, stores tokens in `sessionStorage` only, and fails protected navigation closed into explicit `/auth/login` or `/access-denied` UX instead of silently rendering an empty shell.

Remaining frontend auth gap: this thread does not add refresh-token rotation or offline session renewal. When the access token expires or the backend rejects it, the frontend clears the stored session and forces a fresh OIDC sign-in.

## Repository structure

- `backend/`: Django API and domain services
- `frontend/`: Angular application
- `.venv/`: recommended Python virtual environment at repo root

## Local setup

### 1. Python environment

```powershell
# from repository root
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt
```

If PowerShell blocks script execution:

- Run once: `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`
- Or use `cmd` with `.venv\Scripts\activate.bat`

### 2. Frontend dependencies

```powershell
cd frontend
npm ci
```

If PowerShell blocks `npm`, use `npm.cmd` instead:

```powershell
npm.cmd run -s lint
```

### 2a. Frontend runtime auth config

Non-local Angular deployments require `frontend/public/auth-config.json` to be populated at deploy time. The file is part of the public bundle and must contain only non-secret client metadata:

```json
{
  "enabled": true,
  "issuer": "https://keycloak.example.org/realms/dmis",
  "clientId": "dmis-web",
  "scope": "openid profile email",
  "redirectPath": "/auth/callback",
  "postLogoutRedirectPath": "/auth/login",
  "audience": "dmis-api"
}
```

- `enabled`: must be `true` for shared-dev, staging, and production.
- `issuer`: the OIDC issuer / Keycloak realm URL.
- `clientId`: the public SPA client identifier.
- `scope`: requested scopes for the login flow.
- `redirectPath`: Angular callback route used to exchange the authorization code.
- `postLogoutRedirectPath`: Angular route to return to after logout.
- `audience`: optional audience when the identity provider requires it.

Non-local frontend behavior is real-auth only:

- Protected routes redirect unauthenticated, expired, or backend-auth-failure sessions to `/auth/login?returnUrl=...`.
- Authenticated users without the required route permission land on `/access-denied`.
- The frontend no longer treats auth bootstrap failures as a successful empty UI state.

### 3. Backend environment variables

Choose one local posture:

```powershell
copy backend\.env.example backend\.env
copy backend\.env.local.example backend\.env.local
```

- Use `backend\.env.local.example` only for the local harness workflow.
- Use `backend\.env.example` for shared-dev/staging/production-style settings, or for a prod-like local smoke test with `DMIS_SKIP_LOCAL_ENV=1`.
- The default local harness example includes `REDIS_URL=redis://localhost:6379/1`. Unset `REDIS_URL` only if you intentionally want the documented local-only degraded cache mode.

Set database variables in `.env`:

- `DB_NAME`
- `DB_USER`
- `DB_PASSWORD`
- `DB_HOST`
- `DB_PORT`
- `DMIS_RUNTIME_ENV`
- `REDIS_URL` for every non-harness runtime, and by default for `local-harness`

## Database migrations

Run from `backend/`:

```powershell
..\.venv\Scripts\python.exe manage.py migrate
```

Check migration status:

```powershell
..\.venv\Scripts\python.exe manage.py showmigrations masterdata
..\.venv\Scripts\python.exe manage.py migrate --check
```

## Production configuration

### Required environment variables

| Variable | Description |
|---|---|
| `DMIS_RUNTIME_ENV` | One of `prod-like-local`, `shared-dev`, `staging`, or `production` for every non-local deployment |
| `DJANGO_SECRET_KEY` | Long random string - never use the generated debug key or placeholder values |
| `DJANGO_DEBUG` | Must be `0` |
| `DJANGO_ALLOWED_HOSTS` | Explicit comma-separated hostnames, e.g. `api.dmis.gov.jm` |
| `DB_NAME` / `DB_USER` / `DB_PASSWORD` / `DB_HOST` / `DB_PORT` | PostgreSQL connection |
| `REDIS_URL` | Required for `prod-like-local`, `shared-dev`, `staging`, and `production`; recommended by default for `local-harness` |
| `AUTH_ENABLED` | Set to `1` to enforce Keycloak JWT validation |
| `AUTH_ISSUER` | Keycloak realm URL |
| `AUTH_AUDIENCE` | Client ID registered in Keycloak |
| `AUTH_JWKS_URL` | `<AUTH_ISSUER>/protocol/openid-connect/certs` |
| `AUTH_USER_ID_CLAIM` | JWT claim containing the user ID (e.g. `sub`) |
| `AUTH_USERNAME_CLAIM` | JWT claim for display name |
| `AUTH_ROLES_CLAIM` | JWT claim carrying role list (if not using DB RBAC) |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Optional HTTPS origins only, comma-separated, when the browser origin differs from the API origin |

Non-local rule: `AUTH_ENABLED=1`, `DEV_AUTH_ENABLED=0`, `LOCAL_AUTH_HARNESS_ENABLED=0`, and no `X-DMIS-Local-User` / `X-Dev-User` override behavior.

Non-local deployment rule: `shared-dev`, `staging`, and `production` assume a trusted TLS-terminating ingress that forwards `X-Forwarded-Proto`. Django now sets `SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https")` for those runtimes and keeps `USE_X_FORWARDED_HOST=0`.

Security-default rule: shared-dev, staging, and production now fail closed if secure cookies, HTTPS redirect, HSTS, secret key, or allowed-host posture are incompatible with the declared runtime environment.

### Redis cache

The IFRC circuit breaker and per-user rate limiter use Django's cache framework.

- `local-harness`: the documented default uses Redis. If you intentionally unset `REDIS_URL`, the harness falls back to `LocMemCache` and runs in explicit local-only degraded mode.
- `prod-like-local`, `shared-dev`, `staging`, `production`: `REDIS_URL` is required and startup fails closed if the runtime is not Redis-backed.

```bash
# Example
REDIS_URL=redis://redis:6379/1
```

### LLM / Ollama in production

Set `IFRC_LLM_ENABLED=1` only when an Ollama instance is reachable at `OLLAMA_BASE_URL`. The agent has a built-in circuit breaker - if Ollama is unreachable it falls back to rule-based classification automatically. Tune `IFRC_CB_FAILURE_THRESHOLD` and `IFRC_CB_RESET_TIMEOUT` to match your Ollama SLA.

### WSGI server

Django's `manage.py runserver` is not suitable for production. Use Gunicorn (or uWSGI):

```bash
pip install gunicorn
gunicorn dmis_api.wsgi:application --workers 4 --bind 0.0.0.0:8000
```

### Startup validation

Run from `backend/` before promoting a non-local deployment:

```bash
python manage.py check --deploy
```

This complements the startup fail-closed validation in `dmis_api.settings`; it does not replace it.

Django's deploy checks are broader than the DMIS runtime matrix and may still emit advisory warnings, for example when production keeps HSTS preload opt-in rather than mandatory. Treat the DMIS runtime validator as the enforced baseline and review any remaining Django warnings explicitly before promotion.

### Liveness and readiness

DMIS now exposes separate health probe semantics:

- `GET /api/v1/health/` and `GET /api/v1/health/live/`: liveness only. These endpoints answer whether the Django process can respond.
- `GET /api/v1/health/ready/`: readiness. This endpoint answers whether the instance is safe to receive traffic.

Readiness checks:

- database connectivity is always required
- Redis connectivity is required for `prod-like-local`, `shared-dev`, `staging`, and `production`
- `local-harness` may report Redis as `skipped` only when `REDIS_URL` is intentionally unset for the documented local-only degraded mode

## IFRC Item Code Generator Agent (v3)

This repository uses the v3 approach:

- Generates IFRC-compliant item codes from item name and item attributes
- Does not depend on scraping/syncing external IFRC catalogue data at runtime
- Suggests code only; user approval/save remains explicit
- Logs suggestions in `item_ifrc_suggest_log` for audit traceability

### LLM behavior and model switching

- The agent uses `init_chat_model(...)` in:
  - `backend/masterdata/ifrc_code_agent.py`
- LLM is optional and controlled by environment variables.
- Change models by setting `OLLAMA_MODEL_ID` only.

Key IFRC settings in `backend/dmis_api/settings.py`:

- `IFRC_ENABLED` (default `true`)
- `IFRC_LLM_ENABLED` (default `false`)
- `OLLAMA_BASE_URL` (default `http://localhost:11434`)
- `OLLAMA_MODEL_ID` (default `qwen3.5:0.8b`)
- `OLLAMA_TIMEOUT_SECONDS` (default `10`)
- `IFRC_AUTO_FILL_THRESHOLD` (default `0.80`)
- `IFRC_MIN_INPUT_LENGTH` (default `3`)
- `IFRC_MAX_INPUT_LENGTH` (default `120`)
- `IFRC_CB_FAILURE_THRESHOLD` (default `5`)
- `IFRC_CB_RESET_TIMEOUT` (default `120`)
- `IFRC_RATE_LIMIT_PER_MINUTE` (default `30`)

### API endpoints

Under `api/v1/masterdata`:

- `GET /items/ifrc-suggest?name=<item_name>`
- `GET /items/ifrc-health`

Notes:

- Suggest endpoint validates/sanitizes input and rate-limits requests per user.
- Suggest response includes `suggestion_id`; item save can pass `ifrc_suggest_log_id` so selected code is written back to the log row.

## Item code and validation rules

- `item.item_code` is `VARCHAR(30)`.
- FEFO rule is enforced on both frontend and backend:
  - If `issuance_order === "FEFO"`, then `can_expire_flag` must be `true`.

## Run the apps

### Backend

```powershell
cd backend
..\.venv\Scripts\python.exe manage.py runserver 0.0.0.0:8001
```

Use `http://localhost:8001`, not `https://localhost:8001`. The Django dev server in this repo is HTTP-only for local development.
For the local multi-user harness, use `scripts/run_new_stack.ps1` instead of treating `runserver` plus ad hoc env flags as the production baseline.

### Frontend

```powershell
cd frontend
npm.cmd start
```

Open `http://localhost:4200`. Angular proxies `/api` to the backend on `http://localhost:8001`.

If Django still logs HTTPS handshake errors while the UI is open, run the frontend with `npm.cmd start -- --verbose` and watch the proxy output. The dev proxy now logs the exact upstream URL for every `/api` request.

## Verification commands

### Backend tests

```powershell
cd backend
..\.venv\Scripts\python.exe manage.py test masterdata.tests --verbosity=2
```

### Frontend lint/build

```powershell
cd frontend
npm.cmd run -s lint
npm.cmd run -s build
```

## Current implementation files for IFRC v3

- `backend/masterdata/ifrc_code_agent.py`
- `backend/masterdata/views.py`
- `backend/masterdata/serializers.py`
- `backend/masterdata/models.py`
- `backend/masterdata/migrations/0003_ifrc_v3_generator_schema.py`
- `frontend/src/app/master-data/services/ifrc-suggest.service.ts`
- `frontend/src/app/master-data/models/ifrc-suggest.models.ts`
- `frontend/src/app/master-data/components/master-form-page/master-form-page.component.ts`
- `frontend/src/app/master-data/components/master-form-page/master-form-page.component.html`
