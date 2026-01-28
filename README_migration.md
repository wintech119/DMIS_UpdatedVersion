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
$env:DEV_AUTH_ENABLED = "1"
$env:DEV_AUTH_USER_ID = "dev-user"
$env:DEV_AUTH_ROLES = "LOGISTICS"
```

Warning: `DEV_AUTH_ENABLED` must never be enabled in production.

## Needs List Preview (API)
Endpoint:
```
POST /api/v1/replenishment/needs-list/preview
```

Example curl (dev auth):
```powershell
$env:DEV_AUTH_ENABLED = "1"
$env:DEV_AUTH_USER_ID = "dev-user"
$env:DEV_AUTH_ROLES = "LOGISTICS"

curl -Method Post http://localhost:8001/api/v1/replenishment/needs-list/preview `
  -ContentType "application/json" `
  -Body '{ "event_id": 1, "warehouse_id": 1, "planning_window_days": 14 }'
```

Configuration knobs (TBD finalize from PRD/appendices):
```
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
v4.1 is authoritative. v4.0 is retained only for back-compat validation. Choose the ruleset version via:
```
NEEDS_WINDOWS_VERSION=v41  # Gap Updates v4.1 + Appendix D Technical (default)
NEEDS_WINDOWS_VERSION=v40  # PRD/Reqs v4.0 + Appendix H (legacy)
```

Status code mappings (legacy code -> conceptual inbound):
```
TRANSFER_DISPATCHED_CODES=D
DONATION_CONFIRMED_CODES=V
DONATION_IN_TRANSIT_CODES=V
```

Mappings are best-effort until schema/docs align; no DB changes are introduced.
