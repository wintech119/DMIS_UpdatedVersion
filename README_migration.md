# Migration Scaffold (Strangler Architecture)

This repository will transition to a strangler architecture where the legacy Flask app remains the primary system while a new Django API and Angular SPA are introduced feature-by-feature.

## Approach
- Legacy Flask stays authoritative during migration.
- New functionality is added in parallel (Django API + Angular SPA) and routed to selectively.
- All behavior remains stable until a feature is explicitly migrated and validated.

## Edge Routing (Initial Slice)
NGINX will route only a single path to the SPA as the first experiment:

- Example: `/replenishment/needs-list-preview`

All other paths continue to serve the legacy Flask application.

### Local enablement (optional)
Build and deploy the SPA under the preview path and use the NGINX location rule:
```powershell
cd frontend
npm install
npm run build -- --base-href /replenishment/needs-list-preview/ --deploy-url /replenishment/needs-list-preview/
```
Then copy `frontend/dist/dmis-frontend/` to `/var/www/dmis/spa/` (or your chosen NGINX root),
and use the `docs/deploy/nginx.conf.example` location block for `/replenishment/needs-list-preview`
before reloading NGINX. All other routes continue to proxy to Flask.

## Non-Negotiables
- No breaking changes to existing behavior.
- RBAC and audit logging parity with legacy behavior.
- No database changes without explicit approval.

## Thin-Slice Definition: "Needs List Preview"
The first migrated slice is read-only and must output:
- Burn rate
- Strict inbound
- Gap
- Horizons A/B/C

No write paths are included in this slice.

## Backend (Django/DRF) Local Run
These commands run the new Django API in parallel without impacting legacy Flask.

PowerShell (Windows):
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

$env:DJANGO_SECRET_KEY = "dev-only"
$env:DB_NAME = "dmis"
$env:DB_USER = "postgres"
$env:DB_PASSWORD = "postgres"
$env:DB_HOST = "localhost"
$env:DB_PORT = "5432"

python manage.py runserver 0.0.0.0:8001
```

Run tests (uses local SQLite to avoid touching Postgres):
```powershell
cd backend
.\.venv\Scripts\Activate.ps1
$env:DJANGO_USE_SQLITE = "1"
python manage.py test api replenishment
```

Note: DB changes require explicit approval; do not run `migrate`.

## Dev Auth (local only)
For local testing, you can enable a dev auth bypass (never use in prod):

```powershell
$env:DJANGO_DEBUG = "1"
$env:DEV_AUTH_ENABLED = "1"
$env:DEV_AUTH_USER_ID = "dev-user"
$env:DEV_AUTH_ROLES = "LOGISTICS"
$env:DEV_AUTH_PERMISSIONS = "replenishment.needs_list.preview"
```

Warning: `DEV_AUTH_ENABLED` requires `DJANGO_DEBUG=1` and must never be enabled in production.

## SPA + API Local Dev (no Keycloak)
Run the Django API with dev auth, then start Angular with the proxy:

```powershell
# API
cd backend
.\.venv\Scripts\Activate.ps1
$env:DJANGO_DEBUG = "1"
$env:DEV_AUTH_ENABLED = "1"
$env:DEV_AUTH_USER_ID = "dev-user"
$env:DEV_AUTH_ROLES = "LOGISTICS"
$env:DEV_AUTH_PERMISSIONS = "replenishment.needs_list.preview"
python manage.py runserver 0.0.0.0:8001

# SPA (new terminal)
cd frontend
npm install
npm start
```

## Needs List Preview (API)
Endpoint:
```text
POST /api/v1/replenishment/needs-list/preview
```

Example curl (dev auth):
```powershell
$env:DJANGO_DEBUG = "1"
$env:DEV_AUTH_ENABLED = "1"
$env:DEV_AUTH_USER_ID = "dev-user"
$env:DEV_AUTH_ROLES = "LOGISTICS"
$env:DEV_AUTH_PERMISSIONS = "replenishment.needs_list.preview"

curl -Method Post http://localhost:8001/api/v1/replenishment/needs-list/preview `
  -ContentType "application/json" `
  -Body '{ "event_id": 1, "warehouse_id": 1, "phase": "BASELINE" }'
```

Note: `planning_window_days` is computed from the phase windows (v4.1 default) and is returned in the response; client-provided `planning_window_days` is ignored.

Configuration knobs (TBD finalize from PRD/appendices):
```ini
NEEDS_SAFETY_FACTOR=1.25
NEEDS_HORIZON_A_DAYS=7
NEEDS_HORIZON_B_DAYS=
NEEDS_STRICT_INBOUND_DONATION_STATUSES=V,P
NEEDS_STRICT_INBOUND_TRANSFER_STATUSES=V,P
NEEDS_INVENTORY_ACTIVE_STATUS=A
NEEDS_BURN_SOURCE=reliefpkg
NEEDS_BURN_FALLBACK=reliefrqst
```

Note: donation status model is E/V/P only; do not use A/P/C.

## Needs List Ruleset (Doc-Backed)
Default windows use v4.0 timings (v40). v4.1 remains available for comparison/override. Choose the ruleset version via:
```ini
NEEDS_WINDOWS_VERSION=v40  # PRD/Reqs v4.0 + Appendix H (default)
NEEDS_WINDOWS_VERSION=v41  # Gap Updates v4.1 + Appendix D Technical
```

Status code mappings (legacy code -> conceptual inbound):
```ini
TRANSFER_DISPATCHED_CODES=D
DONATION_CONFIRMED_CODES=V
DONATION_IN_TRANSIT_CODES=V
```

Mappings are best-effort until schema/docs align; no DB changes are introduced.
