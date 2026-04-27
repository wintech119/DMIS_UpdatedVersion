# Master Data Production Readiness + Module Gating — Codex Handoff

This document is the canonical source for six Codex implementation briefs that, taken together, prepare the **Catalog** and **Operational Master Data** modules for QA/Staging/Production deployment and gate the **Supply Replenishment** and **Relief Request (Operations)** modules out of all non-`local-harness` environments. Each brief is self-contained — Codex does not need any conversation context to execute it.

## Context

**Why**: Catalog and Operational Master Data must be QA-ready by tomorrow across QA / Shared Dev / Staging / Production. In those same environments, the Supply Replenishment and Relief Request modules must be fully hidden — they remain available only in the `local-harness` environment for further development. The current codebase has all three modules unconditionally registered for every environment.

**Outcome**:
1. Master Data CRUD is hardened against the most material production risks (parish read-only enforced server-side, IDOR on update payloads re-checked, write-tier rate limiting per `docs/security/SECURITY_ARCHITECTURE.md:186-226`, silent exception swallowing replaced with structured logging, key negative tests added).
2. Replenishment + Operations are gated out at the URL layer in non-local environments (404 on `/api/v1/replenishment/*` and `/api/v1/operations/*`; route + nav hidden on the frontend).
3. Change is environment-driven via the existing `DMIS_RUNTIME_ENV` mechanism and the existing Angular `define` build-constant mechanism — no new feature-flag system, no new artifact shapes, no GitLab pipeline rewiring.

**Scope confirmation**:
- Table grouping uses `backend/masterdata/services/catalog_governance.py:38-48`:
  - **Catalog (governed, 9)**: `item_categories, ifrc_families, ifrc_item_references, items, uom, countries, currencies, parishes, events`
  - **Operational Masters (5)**: `warehouses, agencies, custodians, donors, suppliers`
- Hardening bar: critical-only today; centralized audit-log table + full negative-test matrix deferred to QA-feedback iteration.
- Module gating: fully hidden (no stub pages).
- Frontend config: build-time constants reusing the existing `DMIS_LOCAL_AUTH_HARNESS_BUILD` pattern at `frontend/angular.json:59`.

**Pipeline-safety note**: `INSTALLED_APPS` is intentionally **not** gated. The GitLab `replenishment-export-audit-migration` pre-deploy job (`.gitlab-ci.yml:669-682`) runs `python manage.py apply_replenishment_sql_migration` on `develop`/`staging`/`release-*` branches and requires the `replenishment` app installed for the management command to be discoverable. URL non-registration is the security boundary; the migration/admin attachment is intentionally preserved.

## Execution order (sequential, incremental)

Backend first, then frontend. Each brief becomes its own commit so the verifier can cherry-pick.

1. **Brief #1** — backend module gating (settings + urls.py + .env.example)
2. **Brief #2** — master data critical hardening + tests
3. **Brief #3** — backend verification (with regression detection via `git stash`)
4. **Brief #4** — frontend `angular.json` `define` flags + ambient declarations
5. **Brief #5** — frontend `environmentFeatureGuard` + sidenav filtering
6. **Brief #6** — frontend verification (lint, build, test)

After all six land, the verifier runs the Deploy-Readiness Review (§"Deploy-Readiness Review" below) against `.gitlab-ci.yml` and the architecture docs.

---

## Codex Brief #1 — Backend Module Gating (B1 + B2)

**Goal**: Gate Replenishment and Operations URLs to `local-harness` only. `INSTALLED_APPS` stays static.

**Files to edit**:
- `backend/dmis_api/settings.py`
- `backend/dmis_api/urls.py`
- `backend/.env.example`

**Patterns to mirror (read first)**:
- `backend/dmis_api/settings.py:117-122` — existing `_REAL_AUTH_ONLY_RUNTIME_ENVIRONMENTS` set
- `backend/dmis_api/settings.py:322-369` — `validate_runtime_auth_configuration` validator + error-message style
- `backend/dmis_api/settings.py:696` — `DMIS_RUNTIME_ENV` definition
- `backend/dmis_api/settings.py:707-718` — `INSTALLED_APPS` (LEAVE STATIC)
- `backend/dmis_api/settings.py:1007-1014` — validator call site
- `backend/dmis_api/settings.py:72-77` — `_get_bool_env(name, default)` helper

**Required changes**:

1. In `settings.py`, add module-gating env sets adjacent to `_REAL_AUTH_ONLY_RUNTIME_ENVIRONMENTS` (~L117):
   ```python
   _REPLENISHMENT_ENABLED_RUNTIME_ENVIRONMENTS = {"local-harness"}
   _OPERATIONS_ENABLED_RUNTIME_ENVIRONMENTS = {"local-harness"}
   ```

2. Add a `validate_runtime_module_configuration` function alongside the other validators (after `validate_runtime_auth_configuration` ends ~L369):
   ```python
   def validate_runtime_module_configuration(
       *,
       runtime_env: str,
       replenishment_enabled: bool,
       operations_enabled: bool,
       testing: bool,
   ) -> None:
       if testing or runtime_env == "test":
           return
       if runtime_env in _REAL_AUTH_ONLY_RUNTIME_ENVIRONMENTS:
           if replenishment_enabled:
               raise RuntimeError(
                   f"DMIS_RUNTIME_ENV={runtime_env} requires DMIS_REPLENISHMENT_ENABLED=0; "
                   "the replenishment module is local-harness only."
               )
           if operations_enabled:
               raise RuntimeError(
                   f"DMIS_RUNTIME_ENV={runtime_env} requires DMIS_OPERATIONS_ENABLED=0; "
                   "the operations module is local-harness only."
               )
   ```

3. Just BEFORE `INSTALLED_APPS` at L707 (and after `DMIS_RUNTIME_ENV` is defined at L696), derive the flags:
   ```python
   DMIS_REPLENISHMENT_ENABLED = _get_bool_env(
       "DMIS_REPLENISHMENT_ENABLED",
       DMIS_RUNTIME_ENV in _REPLENISHMENT_ENABLED_RUNTIME_ENVIRONMENTS,
   )
   DMIS_OPERATIONS_ENABLED = _get_bool_env(
       "DMIS_OPERATIONS_ENABLED",
       DMIS_RUNTIME_ENV in _OPERATIONS_ENABLED_RUNTIME_ENVIRONMENTS,
   )
   ```

4. **Do NOT modify `INSTALLED_APPS`.** Leave it exactly as-is.

5. Call the new validator immediately after `validate_runtime_auth_configuration(...)` at L1007:
   ```python
   validate_runtime_module_configuration(
       runtime_env=DMIS_RUNTIME_ENV,
       replenishment_enabled=DMIS_REPLENISHMENT_ENABLED,
       operations_enabled=DMIS_OPERATIONS_ENABLED,
       testing=TESTING,
   )
   ```

6. Replace entire contents of `backend/dmis_api/urls.py` with:
   ```python
   from django.conf import settings
   from django.urls import include, path

   urlpatterns = [
       path("api/v1/", include("api.urls")),
       path("api/v1/masterdata/", include("masterdata.urls")),
   ]
   if settings.DMIS_REPLENISHMENT_ENABLED:
       urlpatterns.append(path("api/v1/replenishment/", include("replenishment.urls")))
   if settings.DMIS_OPERATIONS_ENABLED:
       urlpatterns.append(path("api/v1/operations/", include("operations.urls")))
   ```

7. In `backend/.env.example`, locate the existing `DMIS_RUNTIME_ENV` block (~L6) and append:
   ```
   # Module availability gating (local-harness only).
   # These flags default to ON only when DMIS_RUNTIME_ENV=local-harness.
   # In QA, Shared Dev, Staging, and Production: leave UNSET (or =0).
   # Setting either to 1 in a non-local environment will hard-fail startup.
   # DMIS_REPLENISHMENT_ENABLED=
   # DMIS_OPERATIONS_ENABLED=
   ```

**Constraints**:
- Do NOT modify `INSTALLED_APPS`.
- Do NOT modify any other files.
- Do NOT change the order of existing settings.
- Do NOT add new dependencies.
- Preserve all existing imports and comments.
- Local-harness developer experience must be unchanged (both flags default `True` there).

**Acceptance**:
1. `python manage.py check` succeeds with `DMIS_RUNTIME_ENV=local-harness` and existing local config.
2. `DMIS_RUNTIME_ENV=staging DMIS_REPLENISHMENT_ENABLED=1 python manage.py check` raises `RuntimeError` from the new validator.
3. With `DMIS_RUNTIME_ENV=staging`, `urlpatterns` contains exactly two entries (api + masterdata).
4. `INSTALLED_APPS` unchanged.
5. Diff touches only the three listed files.

**Reporting**: short diff per file (lines added/changed), confirmation `INSTALLED_APPS` untouched, any deviations or unexpected findings.

---

## Codex Brief #2 — Master Data Critical Hardening + Tests

**Goal**: Apply five critical-only hardening fixes and add supporting tests.

**Files to edit/create**:
- `backend/masterdata/views.py` (modify)
- `backend/masterdata/services/validation.py` (modify — replace bare except)
- `backend/masterdata/permissions.py` (read-only reference)
- `backend/masterdata/throttling.py` (NEW — write-tier throttle class)
- `backend/dmis_api/settings.py` (modify if needed for `DEFAULT_THROTTLE_RATES["masterdata-write"]`)
- `backend/masterdata/tests/test_masterdata_core.py` (extend with new test class)
- `backend/masterdata/tests/test_module_gating.py` (NEW — posture-validator tests)

### H1 — Parish backend lock
- In `views.py` `_handle_update` (starts ~L1464) and the analogous item path, early-return `Response({"detail": "Parishes are read-only."}, status=405)` when `cfg.key == "parishes"`. Place the check BEFORE the governed-catalog gate.
- Confirm `master_inactivate` also rejects parishes — the existing `cfg.has_status` guard should already do so. If not, add an explicit early return.

### H2 — Replace bare `except`
- `views.py:1377-1383` (function `_coerce_pk`):
  ```python
  try:
      return int(pk_str)
  except (ValueError, TypeError):
      pass
  ```
  Replace `pass` with `logger.warning("Failed to coerce pk for %s: %s", cfg.key, exc)`, capture `as exc`. Ensure module-level `logger = logging.getLogger(__name__)` exists; add if absent.
- `validation.py:155-158`: similar bare `except (ValueError, TypeError): pass` — replace `pass` with `logger.warning(...)` capturing the exception. Reuse module logger or add one.

### H3 — IDOR re-check on update payloads
- Identify existing helpers used during *create* to verify caller can write to a target warehouse/agency (likely in `backend/masterdata/permissions.py` or `views.py`, called from `_handle_create` / `_handle_item_create`). Look for: `_require_warehouse_scope`, `can_access_warehouse`, `_require_tenant_scope`.
- Inside `_handle_update` and `_handle_item_update`, if PATCH payload contains `warehouse_id` or `agency_id`, run the same scope helper against payload values BEFORE applying the update. Propagate 403/404 unchanged.
- Do NOT invent a new helper. If you cannot find one, report as deviation.

### H4 — Write-tier rate limiting
- Create `backend/masterdata/throttling.py`:
  ```python
  from rest_framework.throttling import UserRateThrottle


  class MasterDataWriteThrottle(UserRateThrottle):
      scope = "masterdata-write"
      rate = "40/minute"
  ```
- If `backend/dmis_api/settings.py` `REST_FRAMEWORK` has `DEFAULT_THROTTLE_RATES`, add `"masterdata-write": "40/minute"` without disturbing existing keys/order.
- Apply `@throttle_classes([MasterDataWriteThrottle])` (after `@api_view` and `@permission_classes`) to: `master_list_create` (POST), `master_detail_update` (PATCH), `master_inactivate`, `master_activate`, and any item-specific create/update endpoints.
- Read-tier endpoints (GET, summary, lookup, IFRC suggest) NOT throttled by this class.

### H5 — Tests in `test_masterdata_core.py`
Locate existing test patterns (`@override_settings`, request-builder helpers, fixture creation). Reuse them. Add class `MasterDataCriticalHardeningTests`:
- `test_parish_patch_returns_405`: PATCH `/api/v1/masterdata/parishes/<existing_pk>` as `SYSTEM_ADMINISTRATOR` → 405.
- `test_warehouse_update_payload_rejects_cross_tenant`: user in tenant A PATCHes a warehouse with `warehouse_id` from tenant B → 403.
- `test_item_create_requires_system_administrator`: user with only `masterdata.view` POSTs `/api/v1/masterdata/items/` → 403.
- `test_masterdata_write_throttle`: 41 rapid PATCHes → 41st returns 429 with `Retry-After`. Use `override_settings(REST_FRAMEWORK={...})` for deterministic throttle if needed; clear cache in `setUp/tearDown`.

### Module gating tests (NEW `backend/masterdata/tests/test_module_gating.py`)
Fresh `TestCase` file. Import `validate_runtime_module_configuration` from `dmis_api.settings`. Add:
- `test_validator_rejects_replenishment_enabled_in_staging`: assert call with `runtime_env="staging", replenishment_enabled=True, operations_enabled=False, testing=False` raises `RuntimeError`.
- `test_validator_allows_local_harness`: same call with `runtime_env="local-harness"` and both flags `True` does not raise.
- `test_validator_skipped_when_testing`: `testing=True` short-circuits regardless of inputs.

**Constraints**:
- No new tables, migrations, or models.
- No centralized audit log table (deferred).
- Do not modify existing tests.
- No new dependencies.
- Preserve `Response` shapes used elsewhere.
- Throttle rate exactly `40/minute`.

**Acceptance**:
1. `python manage.py test masterdata --verbosity=2` passes including new tests (sandbox may not run — document if blocked).
2. No existing tests regress (logical check via reading if sandbox blocks).
3. Bare `except: pass` gone from `views.py:1377-1383` and `validation.py:155-158`.
4. `MasterDataWriteThrottle` defined and applied to write endpoints.
5. Diff touches only listed files.

**Reporting**: diff per file, list of write endpoints that received the throttle decorator, which existing helper(s) reused for IDOR re-check (file:symbol), what `validation.py:155-158` actually does, any unverifiable acceptance criteria.

---

## Codex Brief #3 — Backend Verification (with regression detection)

**Files**: read-only except for one transient `git stash` / `git stash pop` cycle in step 1 (which MUST be reverted before reporting).

**Tasks (in order)**:

1. **Confirm any test failures are pre-existing, not regressions.**
   ```
   python manage.py test masterdata --verbosity=2
   ```
   For each failure, note test name, last 10 lines of traceback, and whether it references parish lock, write throttle, or IDOR re-check (regression indicators) vs item/uom governed-catalog access (likely pre-existing).
   
   To definitively confirm pre-existence:
   ```
   git stash push -m "verification-stash" -- backend/masterdata/views.py backend/masterdata/services/validation.py backend/masterdata/throttling.py backend/masterdata/tests/test_masterdata_core.py backend/masterdata/tests/test_module_gating.py backend/dmis_api/settings.py backend/dmis_api/urls.py backend/.env.example
   python manage.py test masterdata --verbosity=2 2>&1 | tail -80
   git stash pop
   ```
   Failures in BOTH runs = pre-existing. Failures only post-implementation = regression.

2. **Backend regression smoke**: `python manage.py test api --verbosity=2`

3. **Posture validators** (both must behave as expected):
   - Staging with module enabled MUST hard-fail:
     ```
     DMIS_RUNTIME_ENV=staging DMIS_REPLENISHMENT_ENABLED=1 DJANGO_DEBUG=0 AUTH_ENABLED=1 DEV_AUTH_ENABLED=0 LOCAL_AUTH_HARNESS_ENABLED=0 DJANGO_ALLOWED_HOSTS=staging.dmis.example.org REDIS_URL=redis://localhost:6379/1 DJANGO_SECRET_KEY=verify-secret python manage.py check
     ```
     Expect non-zero exit with `DMIS_REPLENISHMENT_ENABLED=0; the replenishment module is local-harness only`.
   - Local harness MUST succeed:
     ```
     DMIS_RUNTIME_ENV=local-harness DJANGO_DEBUG=1 AUTH_ENABLED=0 DEV_AUTH_ENABLED=1 LOCAL_AUTH_HARNESS_ENABLED=1 python manage.py check
     ```

4. **URL surface under staging** (no module flags overridden):
   ```
   DMIS_RUNTIME_ENV=staging DJANGO_DEBUG=0 AUTH_ENABLED=1 DEV_AUTH_ENABLED=0 LOCAL_AUTH_HARNESS_ENABLED=0 DJANGO_ALLOWED_HOSTS=staging.dmis.example.org REDIS_URL=redis://localhost:6379/1 DJANGO_SECRET_KEY=verify-secret python manage.py shell -c "from django.urls import get_resolver; r=get_resolver(); print([p.pattern for p in r.url_patterns])"
   ```
   Output must show exactly 2 entries (api + masterdata).

5. **`replenishment` migration command discoverable** (proves leaving `INSTALLED_APPS` static was correct):
   ```
   DMIS_RUNTIME_ENV=staging DJANGO_DEBUG=0 AUTH_ENABLED=1 DEV_AUTH_ENABLED=0 LOCAL_AUTH_HARNESS_ENABLED=0 DJANGO_ALLOWED_HOSTS=staging.dmis.example.org REDIS_URL=redis://localhost:6379/1 DJANGO_SECRET_KEY=verify-secret python manage.py help apply_replenishment_sql_migration | head -3
   ```

**Constraints**:
- Do NOT modify source files.
- `git stash` MUST be reverted (`git stash pop`) before reporting.

**Reporting**: pass/fail per step, mark each failure PRE-EXISTING or REGRESSION, count of newly added tests, any unexpected warnings, overall verdict (ready for frontend / regressions / blocked).

---

## Codex Brief #4 — Frontend Build-Time Module Flags

**Goal**: Add two build-time JS constants (`DMIS_REPLENISHMENT_ENABLED`, `DMIS_OPERATIONS_ENABLED`) using the existing Angular CLI `define` mechanism. Production build (the GitLab pipeline ships this to QA/Staging/Production) gets both `false`. Development build (used by `ng serve` locally) gets both `true`.

**Files to edit**:
- `frontend/angular.json` (extend `production` + `development` `define` blocks)
- The ambient TypeScript declaration file containing `declare const DMIS_LOCAL_AUTH_HARNESS_BUILD: boolean;` — locate via grep (likely `frontend/src/typings.d.ts` or similar)

**Pattern to mirror**: existing `define` block at `frontend/angular.json:58-60` (`"DMIS_LOCAL_AUTH_HARNESS_BUILD": "false"`). String values evaluated as JS expressions at build time — `"false"` becomes the boolean `false`.

**Required changes**:

1. In `frontend/angular.json`, extend the `production` configuration's `define` block (currently L58-60) to:
   ```json
   "define": {
     "DMIS_LOCAL_AUTH_HARNESS_BUILD": "false",
     "DMIS_REPLENISHMENT_ENABLED": "false",
     "DMIS_OPERATIONS_ENABLED": "false"
   }
   ```

2. Extend the `development` configuration's `define` block (currently L76-78) to:
   ```json
   "define": {
     "DMIS_LOCAL_AUTH_HARNESS_BUILD": "true",
     "DMIS_REPLENISHMENT_ENABLED": "true",
     "DMIS_OPERATIONS_ENABLED": "true"
   }
   ```

3. Find the `.d.ts` file containing `declare const DMIS_LOCAL_AUTH_HARNESS_BUILD: boolean;`. Add adjacent declarations:
   ```ts
   declare const DMIS_REPLENISHMENT_ENABLED: boolean;
   declare const DMIS_OPERATIONS_ENABLED: boolean;
   ```

**Constraints**:
- Do NOT introduce per-env environment files (no `environment.qa.ts` etc). The GitLab pipeline only builds `production`.
- Do NOT modify `tsconfig*.json`, `package.json`, or any other source files.
- Preserve key order in `define` blocks (new keys appended last).
- Do NOT run `npm install` or `npm ci` (project under temporary supply-chain hold per `CLAUDE.md`).

**Acceptance**:
- `cd frontend && npm run build` succeeds with no new warnings.
- `cd frontend && npx ng build --configuration development` succeeds.
- `cd frontend && npm run lint` clean.

**Reporting**: short diff per file, file path of the `.d.ts` you modified, any sandbox blockers (missing `node_modules`, etc.).

---

## Codex Brief #5 — Frontend Route Guard + Sidenav Filtering

**Pure non-visual change.** No styling, no template restructuring.

**Prerequisite**: Brief #4 complete (build-time constants declared).

**Files to edit/create**:
- `frontend/src/app/core/environment-feature.guard.ts` (NEW)
- `frontend/src/app/app.routes.ts` (modify replenishment + operations route entries)
- `frontend/src/app/layout/sidenav/nav-config.ts` (refactor `NAV_SECTIONS` only)

**Pattern to mirror**: existing `appAccessMatchGuard` at `frontend/src/app/core/app-access.guard.ts:22-27`. Same `CanMatchFn` shape, same `inject(Router).createUrlTree(['/'])` redirect.

**Required changes**:

1. Create `frontend/src/app/core/environment-feature.guard.ts`:
   ```ts
   import { inject } from '@angular/core';
   import { CanMatchFn, Router } from '@angular/router';

   export const environmentFeatureGuard: CanMatchFn = (route) => {
     const feature = route.data?.['feature'] as string | undefined;
     if (!feature) return true;
     if (feature === 'replenishment' && !DMIS_REPLENISHMENT_ENABLED) {
       return inject(Router).createUrlTree(['/']);
     }
     if (feature === 'operations' && !DMIS_OPERATIONS_ENABLED) {
       return inject(Router).createUrlTree(['/']);
     }
     return true;
   };
   ```

2. In `frontend/src/app/app.routes.ts`, modify existing `replenishment` and `operations` route entries to attach `environmentFeatureGuard` and `data.feature`:
   ```ts
   {
     path: 'replenishment',
     canMatch: [environmentFeatureGuard],
     data: { feature: 'replenishment' },
     loadChildren: () => import('./replenishment/replenishment.routes').then(m => m.REPLENISHMENT_ROUTES),
   },
   {
     path: 'operations',
     canMatch: [appAccessMatchGuard, environmentFeatureGuard],
     data: { accessKey: 'operations.dashboard', feature: 'operations' },
     loadChildren: () => import('./operations/operations.routes').then(m => m.OPERATIONS_ROUTES),
   }
   ```
   Do NOT change `path`, `loadChildren`, or other guards. `master-data` route unchanged.

3. In `frontend/src/app/layout/sidenav/nav-config.ts`, refactor static `NAV_SECTIONS` array (currently L31-133):
   - Extract the four section literals into named `const` exports: `MAIN_SECTION`, `REPLENISHMENT_SECTION`, `OPERATIONS_SECTION`, `MANAGEMENT_SECTION`.
   - Reassemble:
     ```ts
     export const NAV_SECTIONS: NavSection[] = [
       MAIN_SECTION,
       ...(DMIS_REPLENISHMENT_ENABLED ? [REPLENISHMENT_SECTION] : []),
       ...(DMIS_OPERATIONS_ENABLED ? [OPERATIONS_SECTION] : []),
       MANAGEMENT_SECTION,
     ];
     ```
   - **NO styling, template, layout, or NavSection-shape changes.**

**Constraints**:
- Pure non-visual. No CSS, no SCSS, no HTML touched.
- Preserve existing imports, types, exports beyond what's listed.
- Do NOT run `npm install` or `npm ci`.

**Acceptance**:
- `cd frontend && npm run lint` clean.
- `cd frontend && npm run build` succeeds (production).
- `cd frontend && npx ng build --configuration development` succeeds.

**Reporting**: diff per file, list any extra imports needed, any sandbox blockers.

---

## Codex Brief #6 — Frontend Verification

**Files**: read-only.

Run from `frontend/`:
1. `npm run lint` — must pass clean.
2. `npm run build` — must succeed (production configuration, the GitLab artifact).
3. `npx ng build --configuration development` — must succeed.
4. `npm test -- --watch=false --browsers=ChromeHeadless` — existing Karma/Jasmine suite must still pass.
5. Optional sanity check: `grep -r "DMIS_REPLENISHMENT_ENABLED" dist/dmis-frontend/browser/*.js | head -1` — production bundle should contain `false` substituted, not the identifier.

**Constraints**:
- IMPORTANT: do NOT run `npm install` or `npm ci`. Project is under a temporary supply-chain hold (see `CLAUDE.md` "Temporary Supply-Chain Hold"). If `node_modules` is missing or stale, report that as a blocker rather than installing.
- Do NOT modify any source files.

**Reporting**: pass/fail per command, any new warnings vs baseline, 5-line summary of what changed in the bundle, any sandbox blockers.

---

## Reused Utilities (do not reinvent)

- `_get_bool_env(...)` and `validate_runtime_*_configuration(...)` patterns — `backend/dmis_api/settings.py:110-370`
- `local_auth_harness_enabled()` template style — `backend/api/authentication.py:93-99`
- `MasterDataPermission`, `_require_governed_catalog_access`, warehouse/tenant scope helpers — `backend/masterdata/permissions.py` and `views.py`
- IFRC-suggest throttle class — model the new `MasterDataWriteThrottle` after it (already 30/min/user)
- `validate_record(cfg, data)` — `backend/masterdata/services/validation.py` (already enforces max_length, regex, FK, uniqueness, cross-field)
- `appAccessMatchGuard` pattern — `frontend/src/app/core/app-access.guard.ts:22-27`
- `define`/`DMIS_LOCAL_AUTH_HARNESS_BUILD` build-constant pattern — `frontend/angular.json:59`

## Critical Files Reference

**Backend — Modify**:
- `backend/dmis_api/settings.py` — env sets, derived flags, validator, optional throttle rate in `DEFAULT_THROTTLE_RATES`
- `backend/dmis_api/urls.py` — conditional `include()`
- `backend/masterdata/views.py` — parish lock, IDOR re-check, throttle decorators, replace bare `except` at L1381-1382 (`_coerce_pk`)
- `backend/masterdata/services/validation.py` — replace bare `except` at L155-158
- `backend/.env.example` — document `DMIS_REPLENISHMENT_ENABLED` / `DMIS_OPERATIONS_ENABLED`

**Backend — Create**:
- `backend/masterdata/throttling.py` — `MasterDataWriteThrottle` class
- `backend/masterdata/tests/test_module_gating.py` — posture-validator tests

**Backend — Extend (existing files)**:
- `backend/masterdata/tests/test_masterdata_core.py` — 4 critical-hardening cases

**Frontend — Modify**:
- `frontend/angular.json` — extend `define` blocks of `production` + `development` configurations only
- `frontend/src/app/app.routes.ts` — attach `environmentFeatureGuard` to `replenishment` and `operations` route entries
- `frontend/src/app/layout/sidenav/nav-config.ts` — conditional `NAV_SECTIONS` assembly
- Ambient declaration file (locate via grep on `DMIS_LOCAL_AUTH_HARNESS_BUILD`) — add 2 `declare const` lines

**Frontend — Create**:
- `frontend/src/app/core/environment-feature.guard.ts` — `CanMatchFn` reading the build-time constants

## Deploy-Readiness Review (post-implementation)

After all six briefs land, the verifier walks `.gitlab-ci.yml` and confirms each job will pass with the implemented diff:

| Job | What to verify |
|-----|----------------|
| `sast` | No new Semgrep findings (new throttle, guard, validator avoid known-bad patterns). |
| `secret_detection` | No secrets in `.env.example` (placeholder lines only). |
| `dependency_scanning` | No new dependencies (`requirements.txt`, `package.json` unchanged). |
| `auth_posture_validation` | Eight existing posture cases still pass; new validator coexists cleanly. |
| `secure_posture_validation` | No regression — gating is independent of secure-cookie/HSTS posture. |
| `redis_posture_validation` | No regression — gating is independent of Redis. |
| `markdown_symbol_reference_validation` | If reading-maps reference master data symbols, ensure they still exist. |
| `build-live-stack-bundle` | `npm run build -- --configuration production` succeeds; bundle contains `false` substituted for both new build constants. |
| `verify-live-stack-bundle` | Tarball-extraction assertions still hold; new `backend/masterdata/throttling.py` ships. |
| `replenishment-export-audit-migration` | MITIGATED in Brief #1 by leaving `INSTALLED_APPS` static — `apply_replenishment_sql_migration` remains discoverable on `develop`/`staging`/`release-*`. Verify by running `python manage.py help apply_replenishment_sql_migration` with the staging env profile. |

Cross-check the implemented diff against `docs/adr/system_application_architecture.md`, `docs/security/SECURITY_ARCHITECTURE.md`, `docs/security/CONTROLS_MATRIX.md`, `docs/implementation/production_readiness_checklist.md`, `frontend/AGENTS.md`, and `backend/AGENTS.md`.

## Out of Scope / Deferred

- Centralized `masterdata_audit_log` table + read endpoint (CRITICAL-list item, deferred per "critical-only today" scope decision).
- Full IDOR negative-test matrix across all 14 tables (today covers warehouses + items only).
- DB trigger for parish read-only (defense-in-depth; API-layer lock sufficient for QA).
- Sprint-07 closure: alternate-UOM runtime fixture, cross-module alignment artifact, final merged-state evidence.
- Confirmation step that `LOCAL_AUTH_HARNESS_ENABLED` posture remains correct after the new validator is wired in (smoke test in local-harness).
