# Migration Scaffold (Operations Cutover)

This repository is migrating under a strangler architecture, but the May 15 target is a real Operations cutover rather than a permanent split runtime.

## Target Runtime By May 15

- Django and Angular are authoritative for `Supply Replenishment`
- Django and Angular are authoritative for the live `Operations` path
- Flask Operations is behavior reference and rollback-only scaffolding, not the approved live destination

## Domain Boundary

Freeze this split for migration work:

- `NeedsList` = replenishment planning snapshot and approval artifact
- `ReliefRqst` = operational demand plus eligibility workflow
- `ReliefPkg` = package allocation, dispatch, and receipt aggregate
- `Transfer` and `Procurement` = replenishment execution outputs from approved needs lists

Do not migrate `needs_list` execution endpoints as if they were the final fulfillment architecture.

## Approach

1. keep Django and Angular focused on replenishment planning for EP-02
2. build a Django `operations` domain keyed by `reliefrqst_id` and `reliefpkg_id`
3. build Angular `operations/*` routes and screens on top of the new backend contracts
4. cut over live navigation and APIs away from Flask before May 15
5. leave Flask only as named rollback scaffolding when explicitly required

## First Backend Slice

Backend comes first.

Priority slices:

- request and eligibility read models
- package queue and detail read models
- allocation draft, save, approval, and dispatch contracts
- locking, reservation, waybill, and stock-integrity rules

## Frontend After Backend

Frontend starts after backend contracts are published.

Priority slices:

- `operations/dashboard`
- `operations/relief-requests`
- `operations/eligibility-review`
- `operations/package-fulfillment`
- `operations/dispatch`

Use the Flask UI as a behavior reference only and reuse the existing Angular multi-step templates where they fit.

## QA After Frontend

QA validates:

- parity against the required legacy Operations behavior
- replenishment planning regressions
- live-user-path removal of Flask Operations
- stock reservation, dispatch deduction, audit, and approval integrity

## Transitional Compatibility Rule

During the cutover period:

- frozen `needs_list` execution endpoints may remain in code as compatibility scaffolding
- frozen Angular allocation or dispatch components may remain as migration reference
- temporary links to Flask may exist during active implementation
- May 15 signoff still requires Flask to be removed from the default live path

## Non-Negotiables

- no breaking changes to replenishment planning behavior
- no migration of the current `needs_list` execution model into the final Operations design
- RBAC and audit parity with required legacy behavior
- no database changes without explicit approval

## Backend (Django/DRF) Local Run

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

Run tests:
```powershell
cd backend
.\.venv\Scripts\Activate.ps1
$env:DJANGO_USE_SQLITE = "1"
python manage.py test api replenishment
```

## Workflow Dev Store Note

The workflow dev store remains planning-focused scaffolding. It is not proof of final Operations readiness.

## Related Artifacts

- `docs/implementation/sprint_08_needs_list_execution_boundary_and_migration.md`
- `docs/implementation/sprint_08_operations_cutover_and_flask_retirement.md`
- `docs/requirements/sprint_08_allocation_dispatch_implementation_brief.md`
- `docs/migration/status-code-alignment.md`
