# DMIS-00 Local Multi-User Test Harness

Last updated: 2026-04-09
Status: Implemented local-only developer harness

## Purpose

This runbook defines the local-only auth and user-switching harness that lets one developer test DMIS workflows across multiple users, roles, and tenant contexts without weakening the production target state.

This harness is intentionally scoped to local development. It is not a staging feature and it is not part of the production auth path.

## Recommended Approach

Use the existing Django dev-auth baseline only as the local bootstrap, then layer an explicit local harness on top of it:

- `DEV_AUTH_ENABLED=1` keeps local development unblocked.
- `LOCAL_AUTH_HARNESS_ENABLED=1` explicitly turns on multi-user switching.
- `LOCAL_AUTH_HARNESS_USERNAMES=...` limits switching to a curated, local-only allowlist.
- `DEV_AUTH_USER_ID=local_system_admin_tst` makes the default browser session land on a stable local system-admin user.

The browser never gets a generic impersonate-anyone capability. Instead:

- the Angular app only sends the local harness header on local hosts such as `localhost`, `127.0.0.1`, and `.local`
- Django only honors the switch-user header when all local harness gates are active
- the requested username must be present in the configured allowlist

## What Changed

### Backend

- Added an explicit `LOCAL_AUTH_HARNESS_ENABLED` gate in Django settings.
- Added `LOCAL_AUTH_HARNESS_USERNAMES` so local switching only works for approved harness users.
- Added `/api/v1/auth/local-harness/` to expose the curated harness matrix to the Angular app.
- Restricted header-based user switching to:
  - `DJANGO_DEBUG=1`
  - `DEV_AUTH_ENABLED=1`
  - `LOCAL_AUTH_HARNESS_ENABLED=1`
  - `AUTH_ENABLED=0`
  - a username present in `LOCAL_AUTH_HARNESS_USERNAMES`
- Extended the existing Relief Management frontend test-user seeder to create:
  - a national/local system admin
  - an ODPEM/national Deputy Director for eligibility review and approval
  - an ODPEM/national logistics manager
  - an ODPEM/national logistics officer
  - an agency/requester user

### Frontend

- Reworked the top-bar switcher into an explicit `Local test mode` control.
- Switched the header name to `X-DMIS-Local-User`.
- Scoped the header to local browser hosts only.
- Stopped relying on the generic `/auth/dev-users/` list for the main UI path.
- Kept per-profile state in browser local storage so separate browser profiles stay isolated.

## Required Local Users

The recommended default matrix uses four shared ODPEM/national profiles plus one requester profile on the target tenant:

| Persona | Username | Current role mapping | Expected tenant context | Primary use |
| --- | --- | --- | --- | --- |
| System Admin | `local_system_admin_tst` | `SYSTEM_ADMINISTRATOR` | ODPEM/NEOC national tenant | Global admin, cross-tenant visibility, master-data governance |
| ODPEM Deputy Director | `local_odpem_deputy_director_tst` | `ODPEM_DDG` | ODPEM/NEOC national tenant | Eligibility review and approval testing from the national approver lane |
| ODPEM Logistics Manager | `local_odpem_logistics_manager_tst` | `ODPEM_LOGISTICS_MANAGER` | ODPEM/NEOC national tenant | National logistics review, queue visibility, and ODPEM-led workflow validation |
| ODPEM Logistics Officer | `local_odpem_logistics_officer_tst` | `LOGISTICS_OFFICER` | ODPEM/NEOC national tenant | National fulfillment and dispatch workflow validation from the ODPEM tenant context |
| Agency Requester | `relief_jrc_requester_tst` | `AGENCY_DISTRIBUTOR` | `JRC` | Relief-request intake and agency-scoped workflow testing |

Notes:

- The current codebase has an `ODPEM_LOGISTICS_MANAGER` role but no separate `ODPEM_LOGISTICS_OFFICER` role code. The harness therefore assigns the canonical `LOGISTICS_OFFICER` role to a user whose primary tenant membership is the ODPEM/NEOC national tenant.
- If you need a parish-to-subordinate scenario, seed an additional subordinate tenant and append its usernames to `LOCAL_AUTH_HARNESS_USERNAMES`.

## Exact Local Setup

### 1. Prepare the local env file

From the repository root:

```powershell
copy backend\.env.local.example backend\.env.local
```

The default example is already wired for the mixed ODPEM/JRC matrix:

```env
DJANGO_DEBUG=1
DEV_AUTH_ENABLED=1
TEST_DEV_AUTH_ENABLED=1
LOCAL_AUTH_HARNESS_ENABLED=1
DEV_AUTH_USER_ID=local_system_admin_tst
LOCAL_AUTH_HARNESS_USERNAMES=local_system_admin_tst,local_odpem_deputy_director_tst,local_odpem_logistics_manager_tst,local_odpem_logistics_officer_tst,relief_jrc_requester_tst
DEV_AUTH_ROLES=SYSTEM_ADMINISTRATOR
TENANT_SCOPE_ENFORCEMENT=1
```

If you seed a different tenant than `JRC`, update `LOCAL_AUTH_HARNESS_USERNAMES` to match the usernames printed by the user-seed command.

### 2. Seed the local RBAC and test data

Run these commands from `backend/`:

```powershell
..\.venv\Scripts\python.exe manage.py seed_operations_rbac_permissions --apply
..\.venv\Scripts\python.exe manage.py bootstrap_relief_management_authority_baseline --apply
..\.venv\Scripts\python.exe manage.py seed_relief_management_frontend_test_data --tenant-code JRC --apply
..\.venv\Scripts\python.exe manage.py seed_relief_management_frontend_test_users --tenant-code JRC --apply
```

The last command prints the recommended values for:

- `DEV_AUTH_USER_ID`
- `LOCAL_AUTH_HARNESS_USERNAMES`

Optional subordinate/parish scenario:

```powershell
..\.venv\Scripts\python.exe manage.py seed_relief_management_frontend_test_data --tenant-code FFP --apply
..\.venv\Scripts\python.exe manage.py seed_relief_management_frontend_test_users --tenant-code FFP --apply
..\.venv\Scripts\python.exe manage.py seed_relief_management_hierarchy_test_data --parish-tenant-code PARISH-KN --subordinate-tenant-code FFP --apply
```

If you do this, append the new `FFP` usernames to `LOCAL_AUTH_HARNESS_USERNAMES`.

### 3. Start the backend

From `backend/`:

```powershell
..\.venv\Scripts\python.exe manage.py runserver 0.0.0.0:8001
```

### 4. Start the frontend

From `frontend/`:

```powershell
npm.cmd start
```

Do not install or update frontend dependencies while the current supply-chain hold is active.

### 5. Open separate browser sessions

Use separate browser profiles or separate browsers so each session keeps its own local storage:

1. Browser profile 1: leave the selector on `Default local user (local_system_admin_tst)`.
2. Browser profile 2: select `local_odpem_deputy_director_tst`.
3. Browser profile 3: select `local_odpem_logistics_manager_tst`.
4. Browser profile 4: select `local_odpem_logistics_officer_tst`.
5. Browser profile 5: select `relief_jrc_requester_tst`.

Each profile stores its own local harness selection, so you can keep all four sessions open at once.

## Exact Local Test Steps

1. Load `http://localhost:4200` in each browser profile.
2. Confirm the top bar shows `Local test mode`.
3. In profile 1, keep the default user to validate the national/system-admin baseline.
4. In the other profiles, pick the Deputy Director, ODPEM logistics manager, ODPEM logistics officer, and requester users from the dropdown.
5. Refresh each profile once and confirm the selected local user persists.
6. Open `whoami`-driven pages and confirm the visible navigation and workflow actions differ by role.
7. Use the JRC requester profile to create or edit requester-scoped flows.
8. Use the ODPEM Deputy Director profile to validate eligibility review and approval flows.
9. Use the ODPEM logistics officer profile to validate fulfillment or dispatch-prep flows from the national tenant context.
10. Use the ODPEM logistics manager profile to validate national logistics review and elevated operational actions.
11. Use the system-admin profile to validate cross-tenant visibility and admin-only areas.

## Safety Boundaries

This harness is intentionally blocked outside local development:

- Angular only sends the local harness header on local browser hosts.
- Django ignores the local harness header unless the explicit harness gate is enabled.
- Django rejects switching to users outside the configured allowlist.
- The default local user still comes from `DEV_AUTH_USER_ID`, so a stale browser selection cannot silently expand access when the harness endpoint is unavailable.
- If `/api/v1/auth/local-harness/` is unavailable, the Angular app clears the stored local harness selection.

## Risks and Follow-Ups For DMIS-01

DMIS-01 should treat this harness as a temporary local development tool and finish the production hardening split:

1. Remove the legacy `/api/v1/auth/dev-users/` alias once the local harness route is the only supported local selector source.
2. Strip local-harness code from non-local frontend bundles instead of relying only on runtime host checks.
3. Make `AUTH_ENABLED=1` mandatory in all non-local environments and add explicit deploy-time checks for incompatible local harness flags.
4. Replace the current tenant-admin surrogate with a canonical tenant-admin role and permission bundle.
5. Audit whether any local-only header names or storage keys remain referenced outside the dedicated harness path.
6. Ensure the eventual production OIDC path fully replaces all header-based local user switching.

## Related Baseline Documents

- `docs/implementation/production_hardening_and_flask_retirement_strategy.md`
- `docs/implementation/production_readiness_checklist.md`
- `docs/security/SECURITY_ARCHITECTURE.md`
- `docs/security/THREAT_MODEL.md`
- `docs/security/CONTROLS_MATRIX.md`
