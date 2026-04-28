# Advanced/System Master Data — Codex Handoff (Phase 1)

This document is the canonical source for seven Codex implementation briefs that, taken together, make the **Advanced/System** master-data subdomain reachable from the UI for SYSTEM_ADMINISTRATOR users. Eight RBAC/identity tables (`user`, `role`, `permission`, `user_role`, `role_permission`, `tenant`, `tenant_user`, `user_tenant_role`) become managed via flat config-driven CRUD plus four bespoke many-to-many assignment surfaces. Phase 2 (per-tenant scoping for tenant-admin self-service, audit log, invitation flow, MFA) is documented at the bottom but not in scope here.

Each brief is self-contained — Codex does not need any conversation context to execute it.

## Context

**Why**: The 8 RBAC/identity tables exist in the schema (`backend/DMIS_latest_schema_pgadmin.sql`) but are not reachable through any endpoint. Users provisioned via Keycloak have no DB row in `user` until manually inserted via raw SQL. There are no UI surfaces for users/roles/permissions/tenants. Phase 1 closes the platform-team CRUD gap so production deploy is unblocked; Phase 2 layers tenant-admin self-service on top.

**Outcome**:
1. JWT auth path auto-creates a `user` row on first successful validation when none exists (Keycloak remains source of identity).
2. Four flat tables (`user, role, permission, tenant`) reachable via the existing config-driven masterdata CRUD pattern, gated by new `masterdata.advanced.{view,create,edit,inactivate}` permissions seeded onto `SYSTEM_ADMINISTRATOR`.
3. Four nested junction-table endpoints under `/api/v1/masterdata/...` for many-to-many assignment.
4. Four bespoke Angular standalone components for the same junctions, anchored by `frontend/src/lib/prompts/generation.ts` and the per-component design specs in §"Design Spec Appendix".
5. Sidenav "Advanced/System" entry becomes a working link.

**Pipeline-safety note**: This work adds endpoints under `/api/v1/masterdata/`. The existing `validate_runtime_module_configuration` only gates `replenishment` and `operations` — `masterdata` is always registered. No GitLab pipeline rewiring required. The `replenishment-export-audit-migration` pre-deploy job is unaffected.

**Risk classification**: High (~9-11 pts) — touches RBAC, identity lifecycle, trust boundary between sysadmin and tenant admin. Architecture re-review mandatory after implementation per project CLAUDE.md.

## Execution order (sequential)

Backend first, frontend second. Each brief becomes its own commit so the verifier can cherry-pick.

1. **Brief #1** — Backend: First-login auto-provision in JWT auth path
2. **Brief #2** — Backend: Permission constants + flat-table TABLE_REGISTRY entries (user, role, permission, tenant)
3. **Brief #3** — Backend: Junction-table endpoints (user_role, role_permission, tenant_user, user_tenant_role)
4. **Brief #4** — Backend verification (with regression detection via `git stash`)
5. **Brief #5** — Frontend: Advanced-domain table configs + routes
6. **Brief #6** — Frontend: Many-to-many assignment components (anchored by `generation.ts` + Design Spec Appendix below)
7. **Brief #7** — Frontend verification

After all 7 land, the verifier runs a Deploy-Readiness Review against `.gitlab-ci.yml` and the architecture docs.

---

## Codex Brief #1 — Backend: First-login auto-provision in JWT auth path

**Goal**: When a JWT validates for a user whose `user_id` does not exist in the `user` table, auto-create a minimal row so DB-side role assignment can target it. Keycloak remains the source of identity (auth/password/MFA).

**Files to edit**:
- `backend/api/authentication.py` (modify)
- `backend/api/tests_authentication.py` or equivalent (extend with 3 new tests)

**Patterns to mirror**:
- `backend/api/authentication.py:151-168` — local-harness DB user lookup pattern (raw SQL against `user` table)
- `backend/api/authentication.py:218-287` — JWT validation flow

**Required changes**:

1. Add helper `_ensure_user_row(user_id, username, email, full_name) -> None`:
   - No-op when `AUTH_USE_DB_RBAC=0` (return immediately)
   - Raw SQL `INSERT INTO "user" (...) VALUES (...) ON CONFLICT (user_id) DO NOTHING`
   - Set `status_code='A'`, `password_algo='argon2id'`, `password_hash=''`, `is_active=true`
   - Log `logger.info("Auto-provisioned DMIS user row for user_id=%s username=%s", user_id, username)` only on actual insert (use cursor.rowcount to detect)
   - Wrap in try/except `DatabaseError` that logs `logger.exception(...)` but does not raise (auth must continue)

2. Call from JWT validation success path immediately after `Principal` is constructed and before returning. Source `email` from `email` claim, `full_name` from `name`/`given_name`+`family_name`.

3. Do NOT call from local-harness mode (`L151-168` already requires the row).

**Constraints**:
- No new dependencies, no migrations.
- Sensitive fields (`password_hash`, `mfa_secret`, `failed_login_count`) get default values; never sourced from JWT.
- Existing local-harness behavior unchanged.

**Acceptance**:
1. Test: JWT validates for unseen user_id → DB row exists, `status_code='A'`, `password_hash=''`.
2. Test: JWT validates for existing user_id → no INSERT (idempotent).
3. Test: `AUTH_USE_DB_RBAC=0` → no DB write.
4. Existing auth tests unaffected.

**Reporting**: short diff per file, confirmation of `ON CONFLICT` idempotency, list of fields set on auto-provision, any deviations.

---

## Codex Brief #2 — Backend: Permission constants + flat-table TABLE_REGISTRY entries

**Goal**: Add `masterdata.advanced.{view,create,edit,inactivate}` permissions and seed onto `SYSTEM_ADMINISTRATOR`. Register the 4 flat tables (`user, role, permission, tenant`) in `TABLE_REGISTRY` so the existing config-driven CRUD endpoints work for them with the new permission gate.

**Files to edit/create**:
- `backend/api/rbac.py` — add 4 permission constants
- `backend/api/migrations/000<next>_seed_masterdata_advanced_permissions.py` (NEW)
- `backend/masterdata/services/data_access.py` — add 4 `TableConfig` entries
- `backend/masterdata/permissions.py` — gate flat-advanced tables on `masterdata.advanced.*`
- `backend/masterdata/tests/test_masterdata_advanced.py` (NEW)

**Patterns to mirror**:
- `backend/api/rbac.py:54-80` — existing permission constants
- `backend/api/migrations/0003_seed_operations_request_cancel_permission.py:35-124` — seed migration template (raw SQL, ON CONFLICT, role_permission JOIN)
- `backend/masterdata/services/data_access.py:643-700+` — existing `TableConfig` (e.g., `warehouse`)
- `backend/masterdata/permissions.py:13-45` — `MasterDataPermission`

**Required changes**:

1. **Permission constants** in `rbac.py`:
   ```python
   PERM_MASTERDATA_ADVANCED_VIEW = "masterdata.advanced.view"
   PERM_MASTERDATA_ADVANCED_CREATE = "masterdata.advanced.create"
   PERM_MASTERDATA_ADVANCED_EDIT = "masterdata.advanced.edit"
   PERM_MASTERDATA_ADVANCED_INACTIVATE = "masterdata.advanced.inactivate"
   ```

2. **Seed migration** — new file in `backend/api/migrations/`. Use the next sequential number. Mirror `0003_seed_operations_request_cancel_permission.py` exactly (RunPython, raw SQL `INSERT INTO permission ... ON CONFLICT (resource, action) DO NOTHING`, then JOIN onto `role` to seed `role_permission` for `code='SYSTEM_ADMINISTRATOR'`). Reverse migration deletes the same rows.

3. **TableConfig entries** for the 4 flat tables:
   - `user` (table name `"user"` — quote-needed): pk=`user_id`, status=`status_code` with values **A/I/L** (extend status validation accordingly), `has_audit=True`, `has_version=True`. Visible fields: `username`, `email` (max 200), `first_name`, `last_name`, `full_name`, `is_active` (bool), `assigned_warehouse_id` (FK → warehouses), `agency_id` (FK → agencies), `phone`, `timezone`, `language`, `status_code`. **Excluded** from `data_fields` (never returned in payloads): `password_hash`, `password_algo`, `mfa_enabled`, `mfa_secret`, `failed_login_count`, `lock_until_at`, `last_login_at`, `login_count`, `password_changed_at`.
   - `role`: pk=`id`, no status (`has_status=False`, `status_field=""`), `has_audit=False` (only `created_at` exists). Fields: `code` (required, max 50, regex `^[A-Z_][A-Z0-9_]*$`, unique), `name`, `description`.
   - `permission`: pk=`perm_id`, no status, has audit. Fields: `resource` (max 40), `action` (max 32). Composite uniqueness on `(resource, action)`.
   - `tenant`: pk=`tenant_id`, has status, has audit. Fields: `tenant_code` (max 20, unique), `tenant_name`, `tenant_type`, `parent_tenant_id` (FK self), `data_scope`, `pii_access`, `offline_required`, `mobile_priority`, `address1_text`, `parish_code` (FK → parishes), `contact_name`, `phone_no`, `email_text`.

4. **Permission gate per table**: extend `MasterDataPermission` so for `cfg.key in {"user", "role", "permission", "tenant"}` the required permission is `masterdata.advanced.{view|create|edit|inactivate}` instead of standard `masterdata.*`. Reuse the existing `required_permission` dict-mapping mechanism.

5. **Tests** in new `test_masterdata_advanced.py`:
   - `test_user_list_requires_advanced_view` (standard user → 403; sysadmin → 200)
   - `test_role_create_requires_advanced_create`
   - `test_user_password_hash_not_returned` (GET response excludes sensitive fields)
   - `test_role_code_pattern_enforced` (POST `code="lower-case"` → 400)
   - `test_permission_uniqueness` (duplicate `(resource, action)` → 400/409)

**Constraints**:
- No new dependencies.
- Do NOT modify the 14 existing `TableConfig` entries.
- Do NOT alter existing `masterdata.*` permissions.
- Sensitive fields MUST be excluded from list/detail responses.

**Acceptance**:
1. `python manage.py migrate` applies the new seed cleanly.
2. `python manage.py test masterdata --verbosity=2` passes including new tests.
3. `GET /api/v1/masterdata/role/` returns 200 for sysadmin, 403 for standard user.
4. `GET /api/v1/masterdata/user/<id>` does not contain `password_hash` or `mfa_secret`.

**Reporting**: diff per file, list of fields excluded from `user` payload, list of new permissions and seeded role, any deviations.

---

## Codex Brief #3 — Backend: Junction-table endpoints

**Goal**: 4 nested REST endpoints for the junctions. Each supports GET (list assignments), POST (assign — idempotent via `ON CONFLICT DO NOTHING`), DELETE (revoke). All gated by `masterdata.advanced.*`.

**Files to edit/create**:
- `backend/masterdata/views_advanced.py` (NEW — junction views)
- `backend/masterdata/urls.py` (modify — 4 nested routes)
- `backend/masterdata/services/iam_data_access.py` (NEW — raw SQL helpers)
- `backend/masterdata/tests/test_masterdata_advanced.py` (extend)

**Required endpoints**:

| URL | GET | POST | DELETE |
|-----|-----|------|--------|
| `/api/v1/masterdata/user/<int:user_id>/roles` | list `{role_id, code, name, assigned_at}` | `{role_id}` → assign (idempotent) | `?role_id=N` → revoke |
| `/api/v1/masterdata/role/<int:role_id>/permissions` | list `{perm_id, resource, action, scope_json}` | `{perm_id, scope_json?}` → assign | `?perm_id=N` → revoke |
| `/api/v1/masterdata/tenant/<int:tenant_id>/users` | list `{user_id, username, email, access_level, is_primary_tenant, last_login_at}` | `{user_id, access_level}` → assign | `?user_id=N` → revoke |
| `/api/v1/masterdata/tenant/<int:tenant_id>/users/<int:user_id>/roles` | list `{role_id, code, name}` for that pair | `{role_id}` → assign | `?role_id=N` → revoke |

**Required SQL helpers** in `iam_data_access.py` (parameterized `%s`, never f-strings on user input):
- `list_user_roles(user_id) → list[dict]`
- `assign_user_role(user_id, role_id, assigned_by) → bool` (uses `ON CONFLICT (user_id, role_id) DO NOTHING`)
- `revoke_user_role(user_id, role_id) → bool` (returns whether row was deleted)
- Same shape for `role_permissions`, `tenant_users`, `user_tenant_roles`.

**Permission gate**:
- GET → `masterdata.advanced.view`
- POST/DELETE → `masterdata.advanced.edit`

**Throttle**: apply `@throttle_classes([MasterDataWriteThrottle])` (already 40/min) to POST + DELETE.

**Audit logging** (Phase 1 — log-only, no audit table yet): on every successful POST/DELETE, `logger.info("masterdata.advanced.<action>: <table> by user_id=%s payload=%s", request.principal.user_id, payload)`. Capture `assigned_by` from `request.principal.user_id` for `user_role.assigned_by` and `tenant_user.assigned_by` columns.

**Constraints**:
- No new dependencies.
- All SQL parameterized.
- DELETE returns 204 on success, 404 on no-match.
- POST returns 201 on insert, 200 on idempotent.
- For `role_permission`, accept optional `scope_json` (JSONB) in payload.

**Acceptance**:
1. New tests cover GET/POST/DELETE for all 4 junctions, happy path + 403.
2. Idempotent POST does not duplicate or error.
3. Revoking nonexistent assignment returns 404.
4. `assigned_by` audit column populated on assign.

**Reporting**: full diff, helper signatures, sample request/response per endpoint, deviations.

---

## Codex Brief #4 — Backend Verification

**Files**: read-only except for one transient `git stash` cycle.

Run from `backend/`:

1. **Confirm any test failures are pre-existing**:
   ```
   python manage.py test masterdata --verbosity=2
   python manage.py test api --verbosity=2
   ```
   For each failure, note name and whether it references new advanced code (regression) or existing governed-catalog/UOM (pre-existing).

   To confirm pre-existence:
   ```
   git stash push -m "verification-stash" -- backend/api/authentication.py backend/api/rbac.py backend/api/migrations/*advanced* backend/masterdata/services/data_access.py backend/masterdata/services/iam_data_access.py backend/masterdata/permissions.py backend/masterdata/views_advanced.py backend/masterdata/urls.py backend/masterdata/tests/test_masterdata_advanced.py
   python manage.py test masterdata --verbosity=2 2>&1 | tail -80
   git stash pop
   ```

2. **Posture validators**:
   ```
   DMIS_RUNTIME_ENV=staging DJANGO_DEBUG=0 AUTH_ENABLED=1 DEV_AUTH_ENABLED=0 LOCAL_AUTH_HARNESS_ENABLED=0 DJANGO_ALLOWED_HOSTS=staging.dmis.example.org REDIS_URL=redis://localhost:6379/1 DJANGO_SECRET_KEY=verify-secret python manage.py check
   ```
   MUST succeed (no new posture failures).

3. **Migration check**:
   ```
   python manage.py migrate --check
   ```
   MUST show no missing migrations.

4. **Endpoint smoke** (via test client with SYSTEM_ADMINISTRATOR principal):
   - `GET /api/v1/masterdata/role/` returns role list
   - `POST /api/v1/masterdata/user/<uid>/roles` with `{role_id: N}` → 201 then 200 idempotent
   - `DELETE /api/v1/masterdata/user/<uid>/roles?role_id=N` → 204
   - `GET /api/v1/masterdata/user/<uid>` excludes `password_hash`

**Constraints**: no source-file modification; `git stash` MUST be reverted before reporting.

**Reporting**: pass/fail per step, mark each failure PRE-EXISTING or REGRESSION, count of new tests, overall verdict (ready for frontend / regressions / blocked).

---

## Codex Brief #5 — Frontend: Advanced-domain table configs + routes

**Goal**: Wire the 4 flat tables into the existing config-driven master-data UI under `domain: 'advanced'`, sysadmin-only.

**Files to edit/create**:
- `frontend/src/app/master-data/models/table-configs/users.config.ts` (NEW)
- `frontend/src/app/master-data/models/table-configs/roles.config.ts` (NEW)
- `frontend/src/app/master-data/models/table-configs/permissions.config.ts` (NEW)
- `frontend/src/app/master-data/models/table-configs/tenants.config.ts` (NEW)
- `frontend/src/app/master-data/models/master-domain-map.ts` (modify — populate `implementedRoutePaths` for `advanced`)
- `frontend/src/app/master-data/master-data.routes.ts` (modify — add 4 route triples)
- `frontend/src/app/layout/sidenav/nav-config.ts` (modify — remove standalone "User Management" placeholder; the existing Advanced/System entry under MANAGEMENT_SECTION already covers it)

**Pattern to mirror**: existing `frontend/src/app/master-data/models/table-configs/warehouses.config.ts` or `agencies.config.ts`.

**Required changes**:

1. **`users.config.ts`** — `tableKey: 'user'`, `displayName: 'Users'`, `domain: 'advanced'`, `pkField: 'user_id'`, `routePath: 'users'`, `hasStatus: true`. Fields: username, email (required, email pattern, max 200), first_name, last_name, full_name, phone, timezone, language, assigned_warehouse_id (FK → warehouses), agency_id (FK → agencies), is_active, status_code (select: A/I/L). NO password_hash field.

2. **`roles.config.ts`** — `tableKey: 'role'`, pk=`id`, `hasStatus: false`, `domain: 'advanced'`. Fields: code (required, max 50, pattern `^[A-Z_][A-Z0-9_]*$`, uppercase, `readonlyOnEdit: true`), name, description (textarea).

3. **`permissions.config.ts`** — `tableKey: 'permission'`, pk=`perm_id`, no status, `domain: 'advanced'`. Fields: resource (max 40, `readonlyOnEdit: true`), action (max 32, `readonlyOnEdit: true`).

4. **`tenants.config.ts`** — `tableKey: 'tenant'`, pk=`tenant_id`, `hasStatus: true`, `domain: 'advanced'`. Fields: tenant_code (max 20, unique), tenant_name, tenant_type (select: NEOC/NATIONAL_LEVEL/AGENCY/SHELTER/OTHER), parent_tenant_id (FK self), data_scope, pii_access, offline_required, mobile_priority, address1_text, parish_code (FK → parishes), contact_name, phone_no, email_text.

5. **`master-domain-map.ts`** — replace `implementedRoutePaths: []` for `advanced` with `['users', 'roles', 'permissions', 'tenants']`.

6. **`master-data.routes.ts`** — add 4 list/form/detail route triples, all guarded by existing `masterDataAccessGuard`.

7. **`nav-config.ts`** — remove the standalone `disabled: true` "User Management" entry from `MANAGEMENT_SECTION`. The existing "Advanced/System" sub-entry under "Master Data" already covers it.

**Design anchors (read first, in order)**:
1. `frontend/src/lib/prompts/generation.ts` — DMIS_GENERATION_PROMPT, **the canonical token + pattern source**. Read sections 1 (Visual Identity / Status Tones), 2 (Component Architecture — signals-first, OnPush, standalone), 3 (Styling Rules — only `var(--ops-*)` tokens, kebab-BEM, no `!important`), 4 (Page Layout Patterns). Every config decision (column choice, status pill mapping, form grouping, hint copy) must align with this file. The 4 configs are data-only — they do NOT carry inline styling — but the data choices determine what the existing `master-list` and `master-form-page` shells render, so config decisions ARE design decisions.
2. §"Design Spec Appendix (for Brief #5)" below — per-table list columns, search placeholder, status-tone mapping, form grouping, empty-state copy, mobile column collapse. **The appendix is the source of truth for column choices, sort defaults, and tone mappings.** Codex MAY additionally invoke its own `ui-ux-pro-max` skill for cross-checks or to enrich any decision the appendix leaves underspecified, but the appendix is canonical when there's a conflict. Document any skill-derived additions in the brief's Reporting section.
3. Reference configs: `frontend/src/app/master-data/models/table-configs/agencies.config.ts` and `warehouses.config.ts` — copy their TypeScript shape (imports, type signatures, field-grouping idiom). These already comply with generation.ts.

**Constraints**:
- No styling changes; configs are data-only. The existing `master-list` and `master-form-page` shells render them through generation.ts-compliant CSS.
- Status-tone mapping (per generation.ts §1 Status Tones table): every status pill must include color + text + icon (Material ligature name). Never color-only.
- Column choices, sort defaults, search placeholders, form grouping, hint copy, and empty-state copy must match the §"Design Spec Appendix (for Brief #5)" verbatim.
- ui-ux-pro-max critical rules (already enforced by the master-list shell, but verify config doesn't bypass): cursor-pointer on rows, ≥44×44px touch targets, skeleton loaders not spinners (handled by shell), hover state without layout shift, contrast ≥4.5:1 on every status pill (the appendix's tone mappings comply).
- Each config file ≤ 80 lines.
- Reuse existing `MasterDataService`.

**Acceptance**:
- `cd frontend && npm run lint` clean.
- `cd frontend && npm run build` succeeds.
- `cd frontend && npx ng build --configuration development` succeeds.
- Navigating to `/master-data?domain=advanced` as sysadmin shows 4 cards (users/roles/permissions/tenants), each clickable to a working list page.
- Each list page renders the columns specified in the appendix in the specified order, with the specified status-tone pills.
- Each form page renders the field groups specified in the appendix with `readonlyOnEdit` correctly applied to the canonical-key fields.
- After Codex commits, **Codex runs a Playwright MCP visual verification** (see §"Post-Brief-#5 Visual Verification (Playwright MCP)" below). Codex has access to both `ui-ux-pro-max` and `mcp__playwright__*` tools in its sandbox; Claude Code only sees a verification summary.

**Reporting**: diff per file, mapping of each config's columns/groups back to the appendix (one line per table: "users → columns L1-L4 per appendix §1, form groups Identity/Operational/Locale/Status per appendix §1"), any deviations from the appendix or generation.ts, sandbox blockers.

---

## Codex Brief #6 — Frontend: Many-to-many assignment components

**Goal**: 4 bespoke standalone Angular components for the junction endpoints from Brief #3, embedded as sections on the corresponding flat-table detail pages. Anchor on `frontend/src/lib/prompts/generation.ts` (DMIS_GENERATION_PROMPT) and the per-component design specs in §"Design Spec Appendix" below.

**Files to create**:
- `frontend/src/app/master-data/components/user-roles-assignment/user-roles-assignment.component.ts` + `.html` + `.scss`
- `frontend/src/app/master-data/components/role-permissions-assignment/...`
- `frontend/src/app/master-data/components/tenant-users-assignment/...`
- `frontend/src/app/master-data/components/tenant-user-roles-assignment/...`
- `frontend/src/app/master-data/services/iam-assignment.service.ts` (NEW — HTTP client)

**Files to modify**: embed each component on its parent detail page (`/master-data/users/<id>`, `/master-data/roles/<id>`, `/master-data/tenants/<id>`, `/master-data/tenants/<id>/users/<uid>/roles`) — wrap or extend `master-form-page` to render the assignment section below the flat-table form.

**Design anchors (read first)**:
- `frontend/src/lib/prompts/generation.ts` — read sections 1 (Visual Identity), 2 (Component Architecture), 3 (Styling Rules), 4 (Page Layout Patterns) before writing any code file.
- §"Design Spec Appendix" below — per-component layout, status tones, empty/loading/error treatment, mobile breakpoint behavior, interaction model. Treat the appendix as the source of layout/interaction truth; treat `generation.ts` as the source of token/pattern truth.

**`iam-assignment.service.ts`** signature:
```ts
listUserRoles(userId: number): Observable<UserRoleAssignment[]>
assignUserRole(userId: number, roleId: number): Observable<void>
revokeUserRole(userId: number, roleId: number): Observable<void>
listRolePermissions(roleId: number): Observable<RolePermission[]>
assignRolePermission(roleId: number, permId: number, scopeJson?: object): Observable<void>
revokeRolePermission(roleId: number, permId: number): Observable<void>
listTenantUsers(tenantId: number): Observable<TenantUser[]>
assignTenantUser(tenantId: number, userId: number, accessLevel: string): Observable<void>
revokeTenantUser(tenantId: number, userId: number): Observable<void>
listTenantUserRoles(tenantId: number, userId: number): Observable<UserRoleAssignment[]>
assignTenantUserRole(tenantId: number, userId: number, roleId: number): Observable<void>
revokeTenantUserRole(tenantId: number, userId: number, roleId: number): Observable<void>
```

**Constraints (non-negotiable)**:
- Standalone components only (Angular 21 default), `OnPush` change detection, **signals-first IO** (`input()` / `output()` — NEVER `@Input()` / `@Output()`).
- Selector prefix: `app-` or `dmis-`.
- SCSS uses **only** `var(--ops-*)` tokens. **No** hardcoded color values, **no** `!important`, **no** deprecated `-webkit-` prefixes. Font-family names with spaces are quoted.
- Use Material modules selectively (`MatButtonModule`, `MatIconModule`, `MatAutocompleteModule`, `MatSelectModule`, `MatDialogModule`, `MatSnackBarModule`) — no barrel imports.
- Every interactive element keyboard-accessible with `:focus-visible` styling. Touch targets ≥44×44px.
- Every `<section>` and landmark gets an `aria-label`.
- Cursor `pointer` on all clickable elements.
- Loading: skeleton rows (per generation.ts §2), NEVER a spinner.
- Status tones with color + text + icon backup (per generation.ts §1 Status Tones table).
- Honor `@media (prefers-reduced-motion: reduce)` — disable transforms/transitions when set.
- No emoji icons; only Material `<mat-icon>` ligature-based.
- Reuse `appAccessMatchGuard` / `masterDataAccessGuard` on the parent route — components themselves do not re-check.

**Acceptance**:
- `npm run lint` clean.
- `npm run build` succeeds.
- `npm test --watch=false --browsers=ChromeHeadless` — existing suite still passes.
- Visual diff sanity:
  - `grep -E "color: #[0-9a-fA-F]{3,6};|background: #[0-9a-fA-F]{3,6};" frontend/src/app/master-data/components/*-assignment/**/*.scss` → 0 matches (no hardcoded colors).
  - `grep -c "@Input\(\)\|@Output\(\)" frontend/src/app/master-data/components/*-assignment/**/*.ts` → 0 (signals-first IO).

**Reporting**: diff per file, signature of `iam-assignment.service.ts`, four design-spec sections that were followed (one paragraph each: layout decision, status-tone usage, empty/loading/error treatment, mobile behavior), deviations from spec or generation.ts, sandbox blockers.

---

## Codex Brief #7 — Frontend Verification

Run from `frontend/`:

1. `npm run lint` — clean.
2. `npm run build` — production succeeds.
3. `npx ng build --configuration development` — succeeds.
4. `npm test -- --watch=false --browsers=ChromeHeadless` — full Karma suite passes.
5. Bundle-grep sanity: `grep -c "users-assignment\|tenant-users-assignment" dist/dmis-frontend/browser/*.js | head -3` — confirm new components emit.

**Constraints**: do NOT run `npm install` / `npm ci` (supply-chain hold per `CLAUDE.md`). Report missing `node_modules` as a blocker.

**Reporting**: pass/fail per command, new warnings vs baseline, 5-line summary of bundle-size delta, sandbox blockers.

---

## Design Spec Appendix (for Brief #5)

Per-table config-design specifications produced by Claude Code's `ui-ux-pro-max` design pre-pass. The appendix is the source of truth for column choices, sort defaults, search placeholders, status-tone mappings, form grouping, and empty-state copy. Status tones reference generation.ts §1 (warm-neutral palette + color+text+icon Status Tones table). All Material icon names are ligature-based (no emoji per ui-ux-pro-max common rule).

### 1. users — `/master-data/users`

- **List columns** (4 visible, in order): `username` (monospace, primary clickable row label, sortable) → `full_name` (sortable) → `agency_id` (FK rendered as agency code/name, sortable) → `status_code` (pill, sortable). Rows have `cursor: pointer`, hover background `var(--ops-emphasis)` no layout shift, transition 180ms ease per generation.ts §1.
- **Search placeholder**: `"Search by username, email, or full name"`. Backend ILIKE on those three columns case-insensitive.
- **Status-tone mapping** (`status_code`):
  - `A` (Active) → **Success** (`#edf7ef` / `#286a36`, `check_circle`)
  - `I` (Inactive) → **Neutral** (`#e2dfd7` / `#37352F`, `radio_button_unchecked`)
  - `L` (Locked) → **Critical** (`#fdddd8` / `#8c1d13`, `lock`)
- **Form grouping**:
  - `Identity` (colspan 2): `username` (`readonlyOnEdit: true`, hint "External Keycloak identity. Cannot rename."), `email` (required, email pattern, max 200), `first_name` (colspan 1), `last_name` (colspan 1), `full_name` (colspan 2)
  - `Operational`: `assigned_warehouse_id` (FK lookup), `agency_id` (FK lookup), `is_active` (toggle)
  - `Locale`: `phone` (hint "Mobile preferred for SURGE alerts"), `timezone`, `language` (each colspan 1)
  - `Status` (edit-only): `status_code` (select; hint when L: "Locked accounts cannot log in. Reset password to unlock.")
- **Empty state**: icon `person_off`, heading "No users yet", body "Users are auto-provisioned on first Keycloak login.", next-step `add` "Add User".
- **Mobile <520px**: 3 columns — `username`, `full_name`, `status_code`.

### 2. roles — `/master-data/roles`

- **List columns** (3 visible, in order): `code` (monospace, font-weight 600, primary clickable row label, sortable) → `name` (sortable) → `description` (truncated 80 chars, ellipsis, not sortable). Row height ~52px for ~12 rows per 1080p viewport. No status pill (table has no `status_code`).
- **Search placeholder**: `"Search by code or name"`. Backend ILIKE on both.
- **Status-tone mapping** by privilege class (rendered on the `code` chip):
  - `SYSTEM_ADMINISTRATOR` → **Warning** (`#fde8b1` / `#6e4200`, `shield`)
  - codes starting with `NATIONAL_` → **Info** (`#eef4ff` / `#17447f`, `language`)
  - all others → **Neutral** (`var(--ops-emphasis)` / `var(--ops-ink)`, no icon)
- **Form grouping** (single section):
  - `Identity`: `code` (colspan 2, monospace, uppercase auto-transform, `readonlyOnEdit: true`, hint "Canonical role key. Cannot be changed."), `name` (colspan 2), `description` (textarea, colspan 4, 3 rows)
- **Empty state**: icon `assignment_ind`, heading "No roles defined", body "Roles bundle permissions. Create one before assigning users.", next-step `add` "Add Role".
- **Mobile <520px**: 2 columns — `code`, `name`.

### 3. permissions — `/master-data/permissions`

- **List columns** (3 visible, in order): `resource` (monospace, font-weight 500, sortable, primary clickable row label) → `action` (monospace pill, sortable) → `update_dtime` (relative time, right-aligned, `--ops-ink-muted`, sortable). ~80-120 permissions paginated 25/page.
- **Search placeholder**: `"Search by resource or action (e.g. masterdata.advanced)"`. Backend ILIKE on `resource || '.' || action`.
- **Status-tone mapping** on the `action` pill (no `status_code` exists):
  - `view` / `read` / `list` → **Neutral** (`var(--ops-emphasis)` / `var(--ops-ink)`)
  - `create` / `edit` / `update` → **Info** (`#eef4ff` / `#17447f`, `edit`)
  - `delete` / `inactivate` / `purge` → **Critical** (`#fdddd8` / `#8c1d13`, `delete_outline`)
  - `approve` / `dispatch` / `act_cross_tenant` → **Warning** (`#fde8b1` / `#6e4200`, `gavel`)
- **Form grouping** (single section):
  - `Definition`: `resource` (colspan 2, max 40, `readonlyOnEdit: true`, hint "Dot-namespaced area, e.g. `masterdata.advanced`"), `action` (colspan 2, max 32, `readonlyOnEdit: true`, hint "Verb. Common: view, create, edit, inactivate, approve, act_cross_tenant")
  - Both fields readonly-on-edit because `(resource, action)` is the composite uniqueness key referenced by every `role_permission` row.
- **Empty state**: icon `key`, heading "No permissions defined", body "Permissions are seeded by migrations. Manual additions are rare.", next-step `add` "Add Permission" (de-emphasized button).
- **Mobile <520px**: 2 columns — `resource`, `action`.

### 4. tenants — `/master-data/tenants`

- **List columns** (5 visible, in order): `tenant_code` (monospace, font-weight 600, primary clickable row label, sortable) → `tenant_name` (sortable) → `tenant_type` (pill, sortable) → `parent_tenant_id` (FK rendered as parent's `tenant_code` with leading `subdirectory_arrow_right` if non-null, not sortable) → `status_code` (pill, sortable). Hierarchy hint via parent column gives org-structure context without a tree view.
- **Search placeholder**: `"Search by code, name, or parent tenant"`. Backend ILIKE across `tenant_code`, `tenant_name`, and resolved parent `tenant_code`.
- **Status-tone mapping** — two pills per row:
  - `tenant_type`: `NEOC` → **Critical** (`#fdddd8` / `#8c1d13`, `crisis_alert`); `NATIONAL_LEVEL` → **Warning** (`#fde8b1` / `#6e4200`, `account_balance`); `AGENCY` → **Info** (`#eef4ff` / `#17447f`, `apartment`); `SHELTER` → **Success** (`#edf7ef` / `#286a36`, `home`); `OTHER` → **Neutral**.
  - `status_code` (A/I): Success / Neutral with `check_circle` / `radio_button_unchecked` (matches user-table convention).
- **Form grouping**:
  - `Identity` (colspan 4): `tenant_code` (`readonlyOnEdit: true`, monospace, max 20), `tenant_name`, `tenant_type` (select), `parent_tenant_id` (FK self-lookup, hint "Leave empty for top-level. Cycles will be rejected.")
  - `Data Governance`: `data_scope`, `pii_access`, `offline_required` (toggle), `mobile_priority` (toggle)
  - `Contact`: `address1_text` (colspan 4), `parish_code` (FK), `contact_name`, `phone_no`, `email_text` (email pattern)
  - `Status` (edit-only): `status_code`
- **Empty state**: icon `domain`, heading "No tenants configured", body "At least one tenant is required for any user to operate. Start with the NEOC root tenant.", next-step `add` "Add Tenant".
- **Mobile <520px**: 3 columns — `tenant_code`, `tenant_type`, `status_code`.

---

## Post-Brief-#5 Visual Verification (Playwright MCP)

**Owner**: Codex — runs immediately after committing the Brief #5 configs. Codex has access to `mcp__playwright__*` tools and the `ui-ux-pro-max` skill in its sandbox.

**Prerequisite**: Brief #5 commit on the branch + dev server running on `http://localhost:4200` with `--configuration development` (so `DMIS_REPLENISHMENT_ENABLED=true`; advanced-domain pages render via the existing `master-list` and `master-form-page` shells). If `node_modules` is missing, the supply-chain hold prevents `npm install`/`npm ci` — Codex must report this as a Playwright blocker rather than installing.

**Steps**:

1. **Start dev server in background**: `cd frontend && npm start` (or `npx ng serve --configuration development`). Wait until `http://localhost:4200/` returns 200.
2. **Navigate** via `mcp__playwright__browser_navigate` to `http://localhost:4200/master-data?domain=advanced`. The `dev-user.interceptor.ts` adds the `X-DMIS-Local-User` header automatically in the `development` build with a `local_system_admin_tst` default; if the harness picker UI prompts, select `local_system_admin_tst`.
3. **Snapshot** (`mcp__playwright__browser_snapshot`) the master-home cards. Assert: 4 cards render — Users, Roles, Permissions, Tenants — each with the icon and route specified by the appendix's empty-state metadata.
4. For each table (`users`, `roles`, `permissions`, `tenants`):
   - Navigate to `/master-data/<routePath>`.
   - Snapshot the list page. Assert: column count + order match the appendix; status pills render per appendix tone mapping (verify text + icon presence, not just color); search placeholder text matches; row hover does not shift layout (compare snapshots before and after `mcp__playwright__browser_hover`).
   - Click the "+ Add" button via `mcp__playwright__browser_click`. Snapshot the form. Assert: form groups render in appendix order with appendix labels; `readonlyOnEdit` fields are correctly disabled in edit mode (test by also navigating to an existing record's edit view).
   - Resize to 375px width via `mcp__playwright__browser_resize`. Snapshot. Assert: only the appendix-specified mobile columns remain; no horizontal scroll.
5. **Console + network tap**: `mcp__playwright__browser_console_messages` — assert no `console.error`. `mcp__playwright__browser_network_requests` — assert no 4xx/5xx on `/api/v1/masterdata/{user,role,permission,tenant}/` endpoints.
6. **Tear down**: stop the dev server background process.
7. **Report**: pass/fail per assertion, paste base64 (or file paths) of screenshots for each page at desktop (1280×800) + mobile (375×812) widths, list of any tone-mapping or column-order deviations from the appendix. If Playwright MCP is unavailable in Codex's sandbox at the time of execution, document the blocker and skip — does not block Brief #6 dispatch.

---

## Design Spec Appendix (for Brief #6)

Per-component layout, tone, state, mobile, and interaction specifications produced by the `ui-ux-pro-max` design pre-pass. Each spec is the source of truth for layout/interaction; `generation.ts` is the source of truth for tokens/patterns.

### Component 1 — `user-roles-assignment`

- **Layout**: card-inset (`ops-card` wrapper, `22-28px` padding, `border-radius: var(--ops-radius-md)`), embedded as a "Roles" section directly below the user form. Single vertical row list — each row: `[role.code monospace pill] [role.name] [assigned_at relative time] [trash icon]`. Above the list: inline "Add role" form with `<mat-autocomplete>` over un-assigned roles + Material primary "Assign" button. Header eyebrow: `0.7rem`, weight 700, tracking `0.2em`, uppercase, reading `ROLES (n)`.
- **Status tones**: role chip uses neutral `--ops-emphasis` background + `--ops-ink` text by default. `SYSTEM_ADMINISTRATOR` chip uses **Warning** tone (`#fde8b1` bg, `#6e4200` text, leading `shield` icon) — explicit privileged signal. Newly added rows briefly highlight with **Info** background `#eef4ff` (fades over 600ms; respects `prefers-reduced-motion`).
- **Empty/loading/error**: empty → `lock_outline` icon + heading "No roles assigned" + body "Add a role from the picker above to grant this user system-wide capabilities." + suggestion "Most users need at least one operational role (e.g., LOGISTICS_OFFICER)." Loading → 4 skeleton rows. Error → inline `<mat-error>` strip above the list with retry link; HTTP 4xx flashes a `MatSnackBar` toast.
- **Mobile <520px**: row collapses to 2-line stacked card — line 1 = chip + name; line 2 = relative time + trailing trash icon. Add form's autocomplete becomes full-width with submit button stacked below.
- **Interaction**: pessimistic write (no optimistic update — RBAC is sensitive). Confirm dialog on revoke ("Remove role <code> from this user? They will lose any permissions granted only by this role.") via `MatDialog`. Touch targets ≥44×44px. Cursor `pointer` on all interactive surfaces.

### Component 2 — `role-permissions-assignment`

- **Layout**: card-inset, embedded under role form. Information density is highest here (a role can have 30+ permissions), so use a **two-column "available / assigned" picker**. Left column = available permissions filtered by autocomplete; right column = currently assigned. Both scrollable. Bulk assign via center `>` button or click individual chips. Header eyebrow `PERMISSIONS (n)` + a search input that filters BOTH columns by `resource.action` substring.
- **Status tones**: permission chip neutral by default. Chips containing `.advanced.` or `.delete` action use **Warning** tone (privileged signal). `tenant.act_cross_tenant` permissions use **Info** tone (cross-cutting). Optional `scope_json` constraint shown as a trailing `tune` icon — clicking opens an inline `<mat-expansion-panel>` JSON editor.
- **Empty/loading/error**: empty (assigned column) → `key_off` icon + "No permissions yet" + "Assign at least one permission so users with this role can do anything." Loading → 6 skeleton chips per column. Error → inline strip + toast.
- **Mobile <520px**: two columns collapse into a single tab-switched view (`<mat-tab-group>` with "Available" / "Assigned (n)" tabs). Bulk assign button replaced by per-chip tap. Search input pinned above tabs.
- **Interaction**: pessimistic (high blast radius). Multi-select via shift-click on desktop; on mobile, individual taps. Confirm dialog only when revoking 5+ permissions in one batch ("Remove 7 permissions from <ROLE>? This will revoke them from every user with this role."). Touch targets ≥44×44px.

### Component 3 — `tenant-users-assignment`

- **Layout**: card-inset, headed `USERS IN THIS TENANT (n)`. Vertical row list, denser than role-assignment because access_level matters per row: `[avatar circle] [username + email] [access_level select] [is_primary toggle] [last_login_at relative] [trash]`. Add row via Material autocomplete over user list (search by username/email) + access_level select + "Add" button. Sort dropdown above list: by username / by access_level / by last_login.
- **Status tones**: access_level pills with deliberate tone mapping —
  - `ADMIN` → **Critical** (`#fdddd8` / `#8c1d13`, `admin_panel_settings` icon) — privileged
  - `FULL` → **Warning** (`#fde8b1` / `#6e4200`, `verified` icon)
  - `STANDARD` → **Neutral** (`#e2dfd7` / `#37352F`, default)
  - `LIMITED` → **Info** (`#eef4ff` / `#17447f`, `tune` icon)
  - `READ_ONLY` → **Info** muted (`visibility` icon)

  `is_primary_tenant=true` shown as leading `star` icon next to username.
- **Empty/loading/error**: empty → `groups` icon + "No users in this tenant" + "Add at least one user with ADMIN access to enable tenant-side configuration." Loading → 5 skeleton rows. Error → inline strip + toast. Optimistic update **only** for access_level changes (rollback on 4xx); pessimistic for add/remove.
- **Mobile <520px**: row collapses to two lines: line 1 = star + username + access_level pill + trash; line 2 = email + last_login. Trailing pill becomes a tap-to-edit chip.
- **Interaction**: editing access_level is in-row `<mat-select>` (no modal). Confirm dialog on revoke ("Remove <username> from <TENANT_NAME>? They will lose all tenant-scoped roles assigned here.") and on access_level downgrade from ADMIN ("Demote <username> from ADMIN access? They will no longer be able to manage this tenant's users."). Touch targets ≥44×44px.

### Component 4 — `tenant-user-roles-assignment`

- **Layout**: section-inset (smaller than card; `ops-section` wrapper with `--ops-section` background), embedded **inside** the tenant-user row from Component 3 — clicking a user expands an inline panel showing roles scoped to (tenant, user). Lives at logical route `/master-data/tenants/<tid>/users/<uid>/roles` (URL-deep-linkable) but renders inline. Layout mirrors Component 1 — single vertical row list, autocomplete add. Header eyebrow `ROLES IN THIS TENANT (n)` disambiguates from global roles.
- **Status tones**: identical to Component 1 (`SYSTEM_ADMINISTRATOR` Warning, others Neutral). Addition: a small leading `domain` icon on each row to remind the operator these are **tenant-scoped**, not global. A subtle inline note above the list reads "These roles apply only when the user operates within `<tenant_code>`. Global roles assigned at user level remain separate" (using `--ops-ink-muted`, `0.85rem`).
- **Empty/loading/error**: empty → `domain_disabled` icon + "No roles assigned in this tenant" + "Tenant-scoped roles let this user act within `<tenant_code>` without affecting their global access." Loading → 3 skeleton rows. Error → inline strip + toast.
- **Mobile <520px**: identical collapse behavior to Component 1. Parent tenant-users row remains expanded (no full-screen modal).
- **Interaction**: pessimistic write. Confirm dialog mentions tenant context ("Remove <ROLE> from <username>'s assignments in <TENANT_CODE>?"). Touch targets ≥44×44px. Reuse the same `iam-assignment.service.ts` (`assignTenantUserRole`, `revokeTenantUserRole`).

---

## Reused Utilities (do not reinvent)

- `Principal` dataclass + JWT validation — `backend/api/authentication.py:20-26, 218-287`
- `resolve_roles_and_permissions()` — `backend/api/rbac.py:527`
- `TableConfig`, `FieldDef`, `TABLE_REGISTRY`, raw-SQL helpers — `backend/masterdata/services/data_access.py`
- `MasterDataPermission` — `backend/masterdata/permissions.py:13-45`
- `MasterDataWriteThrottle` (40/min) — `backend/masterdata/throttling.py` (apply to junction POST/DELETE in Brief #3)
- Seed-migration template — `backend/api/migrations/0003_seed_operations_request_cancel_permission.py`
- Master-data UI shell — `frontend/src/app/master-data/components/master-list/`, `master-form-page/`, `master-detail-page/`
- `MasterDataService` — `frontend/src/app/master-data/services/master-data.service.ts`
- `masterDataAccessGuard`, `MasterDataAccessService.isSystemAdmin()` — `frontend/src/app/master-data/guards/`, `services/master-data-access.service.ts`
- **DMIS_GENERATION_PROMPT** — `frontend/src/lib/prompts/generation.ts` (canonical design system reference; Brief #6 components MUST anchor on this)

## Phase 2 Outline (separate plan, not in scope here)

- Per-tenant role filtering in `_fetch_roles()` — today returns global roles
- New permission set `tenant.users.{view,invite,edit,deactivate}` and `tenant.roles.assign`
- `TenantAdminPermission` class
- Tenant-scoped endpoints `/api/v1/tenants/<id>/users` (distinct from sysadmin's `/api/v1/masterdata/...`)
- `iam_audit_log` table + write-side instrumentation (Phase 1 logs to application log only)
- Frontend tenant-admin shell (separate route, separate nav)
- Invitation flow (email link → Keycloak first-login)
- MFA enforcement for privileged roles (CONTROLS_MATRIX `IAM-03`)
- Quarterly access review surface (CONTROLS_MATRIX `IAM-05`)

## Out of Scope / Deferred

- Phase 2 (tenant admin self-service)
- 2 audit-log placeholder tables (`event_phase_history`, `warehouse_sync_log`) — read-only audit views, separate plan
- Invitation flow + MFA
- Bulk import of users/roles via CSV
