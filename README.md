# Disaster Management Information System (DMIS)

DMIS is delivered as a Django + Angular application.

## Stack

- Backend: Django 4.2 (LTS) + Django REST Framework
- Frontend: Angular 21+
- Database: PostgreSQL 16+
- Cache: Redis (optional in dev, required in production)
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

## Auth posture

- `scripts/run_new_stack.ps1` is a dev-only local harness helper. It is not a production, staging, shared-dev, or prod-like deployment path.
- The local multi-user harness is local-only and uses `X-DMIS-Local-User` only when the app is running in explicit `local-harness` mode.
- `X-Dev-User` is retired and no longer supported.
- Shared dev, staging, and production must use real Keycloak/OIDC/JWT auth only. Dev-auth and local-harness flags are rejected outside explicit local-harness mode.
- Production-style Angular builds omit the local harness switcher/interceptor path rather than shipping it behind a runtime toggle.

## Environment matrix

| Environment | `DMIS_RUNTIME_ENV` | Required auth flags | Intended use |
|---|---|---|---|
| Local developer harness | `local-harness` | `AUTH_ENABLED=0`, `DEV_AUTH_ENABLED=1`, `LOCAL_AUTH_HARNESS_ENABLED=1`, `DJANGO_DEBUG=1` | Local-only multi-user workflow testing. `run_new_stack.ps1` targets this mode. |
| Prod-like local smoke test | `prod-like-local` | `AUTH_ENABLED=1`, `DEV_AUTH_ENABLED=0`, `LOCAL_AUTH_HARNESS_ENABLED=0`, `DJANGO_DEBUG=0` | Optional local smoke test with real auth config. Use `DMIS_SKIP_LOCAL_ENV=1` so `.env.local` does not re-enable the harness. |
| Shared dev | `shared-dev` | `AUTH_ENABLED=1`, `DEV_AUTH_ENABLED=0`, `LOCAL_AUTH_HARNESS_ENABLED=0`, `DJANGO_DEBUG=0` | Shared environment with production-like auth posture. No local header switching. |
| Staging | `staging` | `AUTH_ENABLED=1`, `DEV_AUTH_ENABLED=0`, `LOCAL_AUTH_HARNESS_ENABLED=0`, `DJANGO_DEBUG=0` | Production-like pre-release validation. No local header switching. |
| Production | `production` | `AUTH_ENABLED=1`, `DEV_AUTH_ENABLED=0`, `LOCAL_AUTH_HARNESS_ENABLED=0`, `DJANGO_DEBUG=0` | Live posture. Real auth only, fail-closed on incompatible config. |

Frontend note: production-style builds file-replace the local harness switcher/interceptor with no-op implementations, but full end-to-end OIDC login validation still depends on completing the remaining Angular OIDC integration work.

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

### 3. Backend environment variables

Choose one local posture:

```powershell
copy backend\.env.example backend\.env
copy backend\.env.local.example backend\.env.local
```

- Use `backend\.env.local.example` only for the local harness workflow.
- Use `backend\.env.example` for shared-dev/staging/production-style settings, or for a prod-like local smoke test with `DMIS_SKIP_LOCAL_ENV=1`.

Set database variables in `.env`:

- `DB_NAME`
- `DB_USER`
- `DB_PASSWORD`
- `DB_HOST`
- `DB_PORT`
- `DMIS_RUNTIME_ENV`

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
| `DJANGO_SECRET_KEY` | Long random string - never use the dev default |
| `DJANGO_DEBUG` | Must be `0` |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated hostnames, e.g. `api.dmis.gov.jm` |
| `DB_NAME` / `DB_USER` / `DB_PASSWORD` / `DB_HOST` / `DB_PORT` | PostgreSQL connection |
| `REDIS_URL` | Redis connection string, e.g. `redis://redis:6379/1` |
| `AUTH_ENABLED` | Set to `1` to enforce Keycloak JWT validation |
| `AUTH_ISSUER` | Keycloak realm URL |
| `AUTH_AUDIENCE` | Client ID registered in Keycloak |
| `AUTH_JWKS_URL` | `<AUTH_ISSUER>/protocol/openid-connect/certs` |
| `AUTH_USER_ID_CLAIM` | JWT claim containing the user ID (e.g. `sub`) |
| `AUTH_USERNAME_CLAIM` | JWT claim for display name |
| `AUTH_ROLES_CLAIM` | JWT claim carrying role list (if not using DB RBAC) |

Non-local rule: `AUTH_ENABLED=1`, `DEV_AUTH_ENABLED=0`, `LOCAL_AUTH_HARNESS_ENABLED=0`, and no `X-DMIS-Local-User` / `X-Dev-User` override behavior.

### Redis cache

The IFRC circuit breaker and per-user rate limiter use Django's cache framework.

- **Dev (no Redis)**: leave `REDIS_URL` unset - falls back to in-process memory cache. Circuit breaker state is not shared across workers.
- **Production**: set `REDIS_URL`. All workers share circuit breaker state and rate-limit counters correctly.

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
