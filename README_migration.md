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

## Postgres Smoke Test (opt-in)
Run the integration smoke test against Postgres with DEBUG off:
```powershell
cd backend
$env:DJANGO_USE_SQLITE = "0"
$env:DJANGO_USE_POSTGRES_TEST = "1"
$env:DJANGO_DEBUG = "0"
$env:DJANGO_SECRET_KEY = "smoke-test-$(New-Guid)"
$env:DJANGO_ALLOWED_HOSTS = "localhost"
$env:DB_NAME = "dmis"
$env:DB_USER = "postgres"
$env:DB_PASSWORD = "your_password"
$env:DB_HOST = "localhost"
$env:DB_PORT = "5432"
python -m unittest replenishment.tests_postgres
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

## Workflow Dev Store (Needs List Drafts)
The draft workflow is dev-only and persists to a local JSON file. It is disabled by default.

Enable the dev store:
```powershell
$env:NEEDS_WORKFLOW_DEV_STORE = "1"
```

Store location:
```text
backend/.local/needs_list_store.json
```

Endpoints (dev store only):
```text
POST  /api/v1/replenishment/needs-list/draft
GET   /api/v1/replenishment/needs-list/{needs_list_id}
PATCH /api/v1/replenishment/needs-list/{needs_list_id}/lines
POST  /api/v1/replenishment/needs-list/{needs_list_id}/submit
POST  /api/v1/replenishment/needs-list/{needs_list_id}/review/start
POST  /api/v1/replenishment/needs-list/{needs_list_id}/return
POST  /api/v1/replenishment/needs-list/{needs_list_id}/reject
POST  /api/v1/replenishment/needs-list/{needs_list_id}/approve
POST  /api/v1/replenishment/needs-list/{needs_list_id}/escalate
POST  /api/v1/replenishment/needs-list/{needs_list_id}/start-preparation
POST  /api/v1/replenishment/needs-list/{needs_list_id}/mark-dispatched
POST  /api/v1/replenishment/needs-list/{needs_list_id}/mark-received
POST  /api/v1/replenishment/needs-list/{needs_list_id}/mark-completed
POST  /api/v1/replenishment/needs-list/{needs_list_id}/cancel
```

Example curl (create draft + submit):
```powershell
curl -Method Post http://localhost:8001/api/v1/replenishment/needs-list/draft `
  -ContentType "application/json" `
  -Body '{ "event_id": 1, "warehouse_id": 1, "phase": "BASELINE" }'

curl -Method Post http://localhost:8001/api/v1/replenishment/needs-list/{needs_list_id}/submit `
  -ContentType "application/json" `
  -Body '{}'

curl -Method Post http://localhost:8001/api/v1/replenishment/needs-list/{needs_list_id}/approve `
  -ContentType "application/json" `
  -Body '{ "comment": "Approved for release." }'

curl -Method Post http://localhost:8001/api/v1/replenishment/needs-list/{needs_list_id}/escalate `
  -ContentType "application/json" `
  -Body '{ "reason": "Requires higher authority." }'

curl -Method Post http://localhost:8001/api/v1/replenishment/needs-list/{needs_list_id}/start-preparation `
  -ContentType "application/json" `
  -Body '{}'
```

Reminder: draft storage is local only. Persisting needs lists to Postgres requires a future DB change proposal.

Windows + thresholds follow v4.1 + Appendix D Technical Specifications.

Default phase windows (hours):

| Phase | Demand window | Planning window |
| --- | --- | --- |
| SURGE | 6 | 72 |
| STABILIZED | 72 | 168 |
| BASELINE | 720 | 720 |

Freshness thresholds (hours since inventory timestamp):

| Phase | High <= | Warning <= | Stale > |
| --- | --- | --- | --- |
| SURGE | 2 | 4 | 4 |
| STABILIZED | 6 | 12 | 12 |
| BASELINE | 24 | 48 | 48 |

Optional override (legacy v4.0 windows only):
```ini
NEEDS_WINDOWS_VERSION=v40
```

Note: `planning_window_days` is computed from the phase windows above and is returned in the response; client-provided `planning_window_days` is ignored.

Horizon C is status-only in the preview: procurement workflow steps remain in GOJEP, but the API returns
approval tier, suggested approver, and allowed method(s) per the v4.1 threshold matrix, plus a GOJEP note.
Procurement inbound counts only after shipment status is eligible (SHIPPED / IN_TRANSIT / PARTIALLY_RECEIVED),
but procurement tables are not yet modeled so inbound remains 0 with warnings.

Configuration knobs:

```ini
NEEDS_SAFETY_FACTOR=1.25
NEEDS_HORIZON_A_DAYS=7
NEEDS_HORIZON_B_DAYS=
NEEDS_DONATION_LEAD_TIME_HOURS=24
NEEDS_PROCUREMENT_LEAD_TIME_HOURS=336
NEEDS_GOJEP_URL=https://gojep.gov.jm
NEEDS_CRITICAL_ITEM_IDS=1,2,3
NEEDS_CRITICAL_CATEGORY_IDS=10,12
NEEDS_STRICT_INBOUND_DONATION_STATUSES=V,P
NEEDS_STRICT_INBOUND_TRANSFER_STATUSES=V,P
NEEDS_INVENTORY_ACTIVE_STATUS=A
NEEDS_BURN_SOURCE=reliefpkg
NEEDS_BURN_FALLBACK=reliefrqst
```

Note: donation status model is E/V/P only; do not use A/P/C.

Optional overrides for inbound donation mapping (if needed):
```ini
DONATION_CONFIRMED_CODES=V
DONATION_IN_TRANSIT_CODES=V
```

Status code mappings (legacy code -> conceptual inbound):
```ini
TRANSFER_DISPATCHED_CODES=D
```

Mappings are best-effort until schema/docs align; no DB changes are introduced.

Known limitations (doc-aligned, schema-constrained):
- Procurement/shipment tables are not present; Horizon C remains recommendation-only.
- Donation in-transit/shipped status is not modeled; inbound donations are treated as 0 with warnings.
