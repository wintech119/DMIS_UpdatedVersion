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

Carry-forward note: Angular production-style builds now exclude the local harness path, but the full Angular OIDC login/logout/token flow is still incomplete. End-to-end production-auth validation remains a separate follow-up and is not resolved by this document.

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
- `local-harness` remains local-only and should not be reused as a shared deployment baseline.

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
python manage.py collectstatic --no-input
gunicorn dmis_api.wsgi:application --bind 127.0.0.1:8000 --workers 4
```

Build the Angular application with the production-style configuration:

```bash
cd frontend
npm.cmd run -s build
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

These CI checks complement the startup fail-closed validation in `dmis_api.settings`; they do not replace it.

Django's deploy checks are broader than the DMIS runtime matrix and may still emit advisory warnings, for example when production keeps HSTS preload opt-in rather than mandatory. Use the DMIS runtime validator as the enforced baseline and review any remaining Django warnings explicitly before promotion.

## Related documents

- `README.md`
- `backend/.env.example`
- `backend/.env.local.example`
- `docs/deploy/nginx.conf.example`
