# DMIS Deployment Guide

## Purpose

This guide describes the current DMIS deployment baseline for the Angular + Django stack.

Use these source-of-truth documents first when making deployment or hardening decisions:

- `docs/adr/system_application_architecture.md`
- `docs/security/SECURITY_ARCHITECTURE.md`
- `docs/security/THREAT_MODEL.md`
- `docs/security/CONTROLS_MATRIX.md`
- `docs/implementation/production_readiness_checklist.md`
- `docs/implementation/production_hardening_and_flask_retirement_strategy.md`

This file is intentionally focused on deployment posture. It does not declare DMIS production-ready by itself.

## Runtime environments

| Environment | `DMIS_RUNTIME_ENV` | Auth posture | Secure deployment posture |
| --- | --- | --- | --- |
| Local harness | `local-harness` | Local-only harness auth | Local-friendly debug mode; no production security requirements |
| Prod-like local | `prod-like-local` | Real auth only | Explicit secret key and hosts required, but HTTPS redirect, secure cookies, and HSTS may remain off for local smoke testing |
| Shared dev | `shared-dev` | Real auth only | HTTPS redirect on, secure cookies on, HSTS `3600`, trusted reverse proxy required |
| Staging | `staging` | Real auth only | HTTPS redirect on, secure cookies on, HSTS `86400`, trusted reverse proxy required |
| Production | `production` | Real auth only | HTTPS redirect on, secure cookies on, HSTS `31536000`, `includeSubDomains=1`, preload opt-in only, trusted reverse proxy required |

## Redis runtime posture

| Environment | Redis expectation | Degraded mode |
| --- | --- | --- |
| Local harness | Recommended and used by default in the documented harness workflow | Allowed only when `REDIS_URL` is intentionally unset for local-only development |
| Prod-like local | Required | Not allowed |
| Shared dev | Required | Not allowed |
| Staging | Required | Not allowed |
| Production | Required | Not allowed |

Carry-forward note: Angular production-style builds now exclude the local harness path, but the full Angular OIDC login/logout/token flow is still incomplete. End-to-end production-auth validation remains a separate follow-up and is not resolved by this document.

## Async worker runtime posture

| Environment | Async posture | Worker process expectation | If the worker is absent |
| --- | --- | --- | --- |
| Local harness | `DMIS_ASYNC_EAGER=1` by default | Optional | Queue readiness may report `skipped` because jobs run inline |
| Prod-like local | Redis-backed queueing required | Run Django API plus one Celery worker | Readiness fails closed |
| Shared dev | Redis-backed queueing required | Run Django API plus one or more Celery workers | Readiness fails closed |
| Staging | Redis-backed queueing required | Run Django API plus one or more Celery workers | Readiness fails closed |
| Production | Redis-backed queueing required | Run Django API plus one or more Celery workers | Readiness fails closed |

Current async adoption slice:

- needs-list donation CSV export
- needs-list procurement CSV export

Explicit follow-up async migrations:

- IFRC / Ollama suggestion work
- transfer generation if latency becomes operationally significant
- operator repair / replay commands
- object storage for artifacts larger or longer-lived than the current DB-backed queued-export slice

## Backend environment variables

Create `backend/.env` from `backend/.env.example` and set real values before any non-local deployment.

Required for every non-local deployment:

```bash
DMIS_RUNTIME_ENV=shared-dev|staging|production|prod-like-local
DJANGO_DEBUG=0
DJANGO_SECRET_KEY=<real-random-secret>
DJANGO_ALLOWED_HOSTS=<comma-separated-hostnames>

DB_NAME=<postgres-db>
DB_USER=<postgres-user>
DB_PASSWORD=<postgres-password>
DB_HOST=<postgres-host>
DB_PORT=5432
REDIS_URL=redis://redis:6379/1
DMIS_ASYNC_EAGER=0
DMIS_DURABLE_EXPORT_RETENTION_SECONDS=7776000

AUTH_ENABLED=1
DEV_AUTH_ENABLED=0
LOCAL_AUTH_HARNESS_ENABLED=0
AUTH_ISSUER=<oidc-issuer-url>
AUTH_AUDIENCE=<oidc-client-id>
AUTH_JWKS_URL=<issuer-jwks-url>
AUTH_USER_ID_CLAIM=sub
AUTH_USERNAME_CLAIM=preferred_username
AUTH_USE_DB_RBAC=1
```

Optional only when the browser origin differs from the API origin:

```bash
DJANGO_CSRF_TRUSTED_ORIGINS=https://app.example.org,https://admin.example.org
```

Do not use placeholder secret keys, wildcard hosts, URL-shaped host entries, or non-HTTPS CSRF trusted origins in non-local deployments.

## Secure runtime behavior

DMIS now enforces deployment defaults by `DMIS_RUNTIME_ENV` at Django startup:

- `shared-dev`, `staging`, and `production` fail closed unless secure cookies, HTTPS redirect, HSTS, and reverse-proxy TLS handling match the expected profile.
- `prod-like-local` still requires an explicit secret key and explicit allowed hosts, but it stays local-friendly and does not force internet-facing HTTPS assumptions.
- `prod-like-local`, `shared-dev`, `staging`, and `production` also fail closed unless `REDIS_URL` is configured and the default cache backend is Redis-backed.
- `prod-like-local`, `shared-dev`, `staging`, and `production` also fail closed unless the async worker plane is Redis-backed and `DMIS_ASYNC_EAGER=0`.
- `local-harness` remains local-only and should not be reused as a shared deployment baseline. It may run without Redis only as an explicit local-only degraded mode.

For `shared-dev`, `staging`, and `production`, Django assumes a trusted TLS-terminating ingress that forwards:

```text
X-Forwarded-Proto: https
```

DMIS sets `SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https")` for those environments and keeps `USE_X_FORWARDED_HOST=0`.

## Application processes

Run the Django API with Gunicorn rather than `manage.py runserver`:

```bash
cd backend
python manage.py migrate
python manage.py apply_replenishment_sql_migration 20260414_dmis08_export_audit_request_id.sql --apply
python manage.py collectstatic --no-input
gunicorn dmis_api.wsgi:application --bind 127.0.0.1:8000 --workers 4
```

Protected-branch release pipelines now run the same replenishment SQL migration in a `pre_deploy` step before `awx-deploy`, so rollout stops if the schema update fails.

Run the async worker plane as a separate process whenever `DMIS_ASYNC_EAGER=0`:

```bash
cd backend
python -m celery -A dmis_api worker --loglevel=INFO
```

Worker-loss recovery posture:

- Celery runs queued jobs with late acknowledgement and a Redis visibility timeout so broker redelivery can resume work after worker loss.
- `job.recovered` in worker logs indicates a previously running async job was picked up again after redelivery.
- Keep readiness tied to worker heartbeat; if the heartbeat disappears, treat the worker plane as unavailable until a worker is healthy again.

Queued export artifact posture:

- needs-list donation and procurement CSV exports now persist their payloads in the PostgreSQL-backed `async_job_artifact` table before the job is marked `SUCCEEDED`
- retrieval remains on the authenticated `/api/v1/jobs/{job_id}/download` path and inherits the same needs-list permission and tenant-scope checks as the source workflow
- `DMIS_DURABLE_EXPORT_RETENTION_SECONDS` defaults to 90 days for non-local runtimes and is the retention window surfaced by `expires_at`
- `DMIS_ASYNC_INLINE_ARTIFACT_MAX_BYTES` remains the size guard for this interim DB-backed storage; larger exports should fail closed until object storage is introduced
- queued exports and production-style readiness now fail closed until `python manage.py apply_replenishment_sql_migration 20260414_dmis08_export_audit_request_id.sql --apply` has been run against the active schema
- clean up expired durable rows and expired legacy inline payloads with `python manage.py purge_expired_async_job_artifacts --apply`
- this is an interim hardening step for small CSV outputs, not the final object-storage design

Windows local smoke-test variant:

```powershell
cd backend
..\.venv\Scripts\python.exe -m celery -A dmis_api worker --loglevel=INFO --pool=solo
```

Build the Angular application with the production-style configuration:

```bash
cd frontend
npm run build
```

Do not treat the local harness scripts as a production or staging deployment path.

## Reverse proxy

Use `docs/deploy/nginx.conf.example` as the current NGINX baseline for:

- serving the Angular SPA from `/`
- proxying `/api/` to Gunicorn
- forwarding `Host` and `X-Forwarded-Proto`
- keeping edge HTTPS/HSTS/referrer behavior aligned with the Django runtime profile

The NGINX example is parameterized for the HSTS portion of the edge policy. Render or replace these placeholders before use:

| Environment | `HSTS_SECONDS` | `HSTS_INCLUDE_SUBDOMAINS` | `HSTS_PRELOAD` | Rendered HSTS value |
| --- | --- | --- | --- | --- |
| Shared dev | `3600` | empty | empty | `max-age=3600` |
| Staging | `86400` | empty | empty | `max-age=86400` |
| Production (default) | `31536000` | `; includeSubDomains` | empty | `max-age=31536000; includeSubDomains` |
| Production (preload opt-in only) | `31536000` | `; includeSubDomains` | `; preload` | `max-age=31536000; includeSubDomains; preload` |

This keeps the reverse-proxy example aligned with the same runtime matrix enforced in `dmis_api.settings`.

If your CDN, WAF, or ingress layer injects security headers, keep those values aligned with the Django runtime environment declared in `DMIS_RUNTIME_ENV`.

Health probe routing should preserve:

- `GET /api/v1/health/` or `GET /api/v1/health/live/` for liveness
- `GET /api/v1/health/ready/` for readiness

Do not use the liveness probe as a readiness gate in shared-dev, staging, or production.

The ingress layer should also preserve or set:

```text
X-Request-ID: <edge-generated-or-forwarded-request-id>
```

DMIS accepts a sanitized `X-Request-ID` when present, otherwise it generates one. Every API response echoes the request ID in the response headers, and DRF error responses also include `request_id` in the JSON body.

## Operational visibility

Current API/runtime signals:

| Signal | Where it appears | Why it matters |
| --- | --- | --- |
| `runtime.posture.initialized` | startup logs | Confirms the runtime environment, auth posture, Redis posture, cache backend, and secure-cookie / HTTPS posture at boot |
| `X-Request-ID` / `request_id` | every API response and DRF error body | Lets operators correlate ingress logs, backend logs, and user-reported failures |
| `auth.request_rejected` | backend warning logs | Indicates missing/invalid auth or rejected local-only auth headers |
| `auth.jwt_verification_failed` | backend warning logs | Indicates JWT validation failures without logging the raw token |
| `job.queued` / `job.started` / `job.retrying` / `job.recovered` / `job.succeeded` / `job.failed` | backend worker/API logs | Shows async job lifecycle, retries, worker-loss recovery, and operator-visible failures using the same request/job correlation; `job.succeeded` now includes `artifact_id` for durable export evidence |
| `readiness.not_ready` | backend warning logs and `/api/v1/health/ready/` | Indicates DB, Redis, or queue dependency failure and keeps the instance out of rotation |
| `request.unhandled_exception` | backend error logs | Indicates an unhandled server-side exception tied to a request ID |

Logging guardrails:

- DMIS intentionally avoids logging bearer tokens, raw JWT claims, secrets, and connection strings.
- Local-harness rejection logs no longer include the raw requested username or email.
- The current implementation is alert-ready but not tied to a third-party observability platform in this thread; connect your log and metrics pipeline to these signals.

## Alert-ready conditions

At minimum, wire monitoring or alert rules for:

- repeated `/api/v1/health/ready/` `503` responses from one or more instances
- any readiness failure whose `checks.database.status`, `checks.redis.status`, or `checks.queue.status` becomes `failed`
- repeated `job.failed` events for the same `job_type`
- repeated `job.retrying` events that never resolve to `job.succeeded`
- spikes in `auth.request_rejected` or `auth.jwt_verification_failed`
- repeated `request.unhandled_exception` events or sustained API `5xx` rates
- startup failures caused by invalid runtime posture, missing auth config, or missing Redis config in non-local environments

Recommended operator response:

1. Capture the affected `X-Request-ID` or `request_id`.
2. Pull the matching backend log lines first.
3. Confirm whether the issue is isolated to one instance, one dependency, or the entire environment.
4. Remove unhealthy instances from rotation before restart or rollback.

## Minimum recovery actions

### App restart or deployment rollback

1. Remove the unhealthy instance or release from traffic using readiness or ingress controls.
2. Check the most recent `runtime.posture.initialized`, `readiness.not_ready`, and `request.unhandled_exception` logs for the affected `X-Request-ID` or release window.
3. Restart the Django API process if the issue is process-local.
4. If the problem started with the current release, roll back to the previous known-good deployment rather than weakening runtime controls.
5. Return traffic only after `/api/v1/health/ready/` is green again.

### Database dependency failure

1. Treat DB readiness failure as critical and keep the instance out of rotation.
2. Verify database reachability, credentials, TLS/network posture, and migration state.
3. Do not bypass the readiness gate or force the app into service without DB connectivity.
4. If failover or restore is required, record the exact evidence used and the recovery window achieved.

### Redis dependency failure

1. Treat Redis failure as critical in `prod-like-local`, `shared-dev`, `staging`, and `production`.
2. Restore Redis availability or the correct Redis-backed cache configuration.
3. Do not switch non-local environments to `LocMemCache` as a recovery shortcut.
4. Return traffic only after readiness shows Redis `ok`.

### Async worker or queue failure

1. Treat queue readiness failure as critical in `prod-like-local`, `shared-dev`, `staging`, and `production`.
2. Check for fresh worker heartbeat, running Celery worker processes, and recent `job.failed` / `job.retrying` / `job.recovered` logs.
3. Do not re-enable `DMIS_ASYNC_EAGER` as a production recovery shortcut.
4. Return traffic only after readiness shows queue `ok` and the worker plane is consuming jobs again.

### Invalid runtime posture or configuration drift

1. DMIS is designed to fail closed on invalid non-local runtime posture.
2. Correct the environment variables or secret/config source rather than bypassing the validation.
3. Re-run `python manage.py check --deploy` and restart or redeploy with the corrected configuration.
4. Capture the resulting startup log as recovery evidence.

### Backup, restore, and evidence expectations

- Before promotion, keep a documented backup procedure, rollback owner, and dated restore-test evidence.
- If backup/restore verification is still manual, store the evidence in the release record and treat missing evidence as an open readiness gap.
- A restore exercise should record the restore date, operator, backup source, target environment, observed RPO/RTO, and any follow-up remediation.

## Validation before promotion

Run these checks from `backend/` before promoting any non-local deployment:

```bash
python manage.py check --deploy
python manage.py showmigrations
python manage.py migrate --check
```

The repository CI now includes:

- auth posture validation
- secure deployment posture validation
- Redis runtime posture validation
- async worker-plane runtime posture validation

These CI checks complement the startup fail-closed validation in `dmis_api.settings`; they do not replace it.

Django's deploy checks are broader than the DMIS runtime matrix and may still emit advisory warnings, for example when production keeps HSTS preload opt-in rather than mandatory. Use the DMIS runtime validator as the enforced baseline and review any remaining Django warnings explicitly before promotion.

## Related documents

- `README.md`
- `backend/.env.example`
- `backend/.env.local.example`
- `docs/deploy/nginx.conf.example`
