# Plan: Adopt Django Built-in Auth Framework (Adapter / Phased)

> **Status**: Approved by user 2026-04-30. Implementation delegated to Codex GPT 5.5, one phase at a time, verified by Claude before next phase begins.
> **Scope locked**: Phases 1–3 only. Briefs 4 and 5 are reference templates, not in this initiative.
> **App location**: new standalone `accounts` Django app.
> **Local harness**: `X-DMIS-Local-User` header flow preserved (maps to `login()` via `LocalHarnessBackend`).

## Context

You asked to re-configure users, roles, permissions to use Django's built-in auth framework while keeping **Keycloak** for authentication everywhere except **local-harness**, where only Django built-in auth is used. The exploration confirmed this is **high risk if done in one shot** — the codebase already runs a fully working custom RBAC layer (`user`, `role`, `permission`, `user_role`, `role_permission`, `tenant_user`, `user_tenant_role`, `user_warehouse`) that is consumed by 109 call sites and has just been hardened with tenant-first user creation. A rip-and-replace would break dispatch, receipt, eligibility, audit, and tenancy enforcement at the same time.

This plan documents the **lowest-risk path**: introduce Django auth as an **adapter on top of the existing schema**, migrate behavior in incremental, independently shippable phases, and never break the current `Principal`-based consumer contract until it is fully retired.

The migration must satisfy non-negotiables in `docs/adr/system_application_architecture.md`, `docs/security/SECURITY_ARCHITECTURE.md`, and `docs/security/CONTROLS_MATRIX.md` (Keycloak as sole production identity, tenant-first user creation atomicity, backend authorization authoritative, no dev impersonation in production, Redis-backed rate limiting in production, MFA for privileged roles).

---

## Recommendation: Adapter / Bridge Pattern (Not Replacement)

**Core idea**

1. Introduce a custom Django `AUTH_USER_MODEL` that maps onto the **existing `"user"` table** via `db_table = '"user"'`. No data migration of `auth_user` rows.
2. `request.user` becomes a **real Django `User` instance** that **also exposes `Principal`-shaped attributes** (`user_id`, `username`, `roles`, `permissions`, `is_authenticated`) so all 109 consumer sites keep working unchanged.
3. Roles and permissions get a **two-way bridge** to Django `auth.Group` and `auth.Permission` so `user.has_perm(...)` works alongside the existing `'masterdata.view' in principal.permissions` checks.
4. Authentication backends are split:
   - **Keycloak (non-local)** — existing JWT validation populates the Django user via a custom `RemoteUser`-style backend (`get_or_create` on the custom `User`).
   - **Local harness** — uses Django's `ModelBackend` against the same `User` model. The `X-DMIS-Local-User` allowlist behavior is preserved as a development convenience header that calls `login()`.
5. Tenancy stays exactly where it is (`api/tenancy.py`, `tenant_user`, `user_tenant_role`). It is **out of scope** for this migration. The new `User` model is consumed wherever `Principal` is consumed today, and tenant resolution still keys off `user_id`.

**Why this is the lowest-risk path**

| Concern | Mitigation |
|---|---|
| 109 consumer sites | Adapter exposes `Principal` attributes on `User`. Zero changes required to start. |
| Tenant-first creation just hardened | Untouched — the new model points at the same table; existing code still owns creation. |
| 60+ permission codes in non-Django format | Two-way bridge keeps `'masterdata.view'` working AND maps it to `auth.Permission(codename='view', content_type=...)` so `user.has_perm('masterdata.view_master_data')` works in parallel. |
| Production must keep using Keycloak | Keycloak path is preserved; new auth backend just wraps it. |
| Local harness must work without Keycloak | New `ModelBackend` against custom `User` table. Single source of truth, no Keycloak dependency. |
| `auth_user` table is currently empty (system check warns if populated) | We do **not** populate `auth_user`. We point Django auth at the existing `"user"` table. The W002 check stays valid. |
| Architecture docs mandate central RBAC, MFA, durable audit | All preserved — adapter does not relax any control. |

---

## Phases (Each Phase is Independently Shippable)

### Phase 1 — Custom User Model Bound to Existing `"user"` Table

**Risk**: Low–Medium. **Reversible**: Yes (single setting flip).

- Create new app `accounts` with `AbstractBaseUser` + `PermissionsMixin` subclass `DmisUser`:
  - `db_table = '"user"'` and `managed = False` (no migration creates the table; we adopt the existing one).
  - Map existing columns: `user_id` (PK), `username`, `email`, `full_name`, `is_active`, `password_hash` (to `password`), `mfa_enabled`, `status_code`, `login_count`, audit cols.
  - `USERNAME_FIELD = 'username'`, `REQUIRED_FIELDS = ['email']`.
  - Property aliases so existing code reads identically:
    - `is_authenticated` provided by `AbstractBaseUser`; only override if the existing semantics differ.
    - `roles` and `permissions` are deferred to Phase 2 (Phase 1 must not change auth flow).
    - `user_id` already exists; ensure type-equivalence with existing `Principal.user_id`.
- Set `AUTH_USER_MODEL = 'accounts.DmisUser'`.
- **Do not** add or alter columns on the `"user"` table in this phase.
- Provide a `DmisUserManager(BaseUserManager)` with `create_user`, `create_superuser` that **calls into existing `tenant-first` user provisioning service** (preserve atomicity).

**Verification**
- `python manage.py check` clean.
- `python manage.py shell` → `User.objects.get(username='test_user')` returns row with all fields.
- All existing tests pass with `AUTH_USER_MODEL` set.
- W002 system check still passes (no rows in `auth_user`).

---

### Phase 2 — Authentication Backends Split

**Risk**: Medium. **Reversible**: Yes (revert to current `LegacyCompatAuthentication`).

- Add `AUTHENTICATION_BACKENDS`:
  - `accounts.backends.KeycloakOidcBackend` — wraps existing JWT validation; on success calls `User.objects.get_or_create(user_id=...)` and returns the `User`.
  - `accounts.backends.LocalHarnessBackend` — extends `ModelBackend` for `(username, password)` against `"user"`. Used by Django admin and the local harness flow.
  - `django.contrib.auth.backends.ModelBackend` last (covers admin / shell access).
- Refactor `LegacyCompatAuthentication.authenticate()` so:
  - Keycloak path delegates to `KeycloakOidcBackend` and returns its `User`.
  - Local harness path: `X-DMIS-Local-User` header + allowlist + `_resolve_dev_override_principal` now produces a real `User` via `LocalHarnessBackend.get_user()`. **Behavior is unchanged externally** (same header, same allowlist).
- Preserve **all** existing settings (`AUTH_ENABLED`, `DEV_AUTH_ENABLED`, `LOCAL_AUTH_HARNESS_ENABLED`, `LOCAL_AUTH_HARNESS_USERNAMES`, `DMIS_RUNTIME_ENV` validation).
- `Principal` dataclass becomes a **thin compatibility shim** that wraps `User` for the few sites that explicitly construct it (mostly tests). New code uses `request.user` directly.

**Verification**
- `whoami` endpoint returns same JSON for the same JWT as before.
- Local harness `X-DMIS-Local-User` flow returns same JSON as before.
- Legacy `X-Dev-User` still rejected.
- Runtime-env validation in `dmis_api/settings.py` still trips on misconfig.
- All RBAC tests pass.

---

### Phase 3 — Two-Way Permission/Group Bridge (Read-Only First)

**Risk**: Medium. **Reversible**: Yes (registration flag).

- Create `accounts/management/commands/sync_rbac_to_django_auth.py`:
  - Reads `role` + `role_permission` + `permission` from custom tables.
  - For each `role.code`: ensures `Group(name=role.code)` exists.
  - For each `permission(resource, action)`: maps to a Django `Permission` keyed by `(content_type, codename)` where `codename = f"{resource}__{action}"` (double underscore avoids collision with built-in `view_/add_/change_/delete_`). Creates a synthetic `ContentType` per resource if one is not already present.
  - Re-applies `Group.permissions = [...]` mapping from `role_permission`.
  - Re-applies `User.groups = [...]` from `user_role`.
- Run idempotently on every deploy (post-migrate signal or release task).
- `User.has_perm('masterdata__view')` works alongside `'masterdata.view' in user.permissions`.
- Bridge is **read-only** — DMIS code keeps writing to the custom tables; the Django side is always derived.

**Verification**
- After running the sync command, `user.has_perm('masterdata__view')` matches `'masterdata.view' in user.permissions` for every test fixture user.
- Group/Permission counts match `role`/`permission` row counts.
- Re-running the sync is a no-op (idempotent).

---

### Phase 4 — Migrate Permission Checks Incrementally (Reference Only — Not in Scope)

Kept as a future-reference template. Not implemented in this initiative per locked scope.

### Phase 5 — Decommission `Principal`-Only Compatibility Shims (Reference Only — Not in Scope)

Kept as a future-reference template. Not implemented in this initiative per locked scope.

---

## Out of Scope (Explicitly Deferred)

- Tenant model changes (`tenant_user`, `user_tenant_role`, `user_warehouse`). These stay as-is; the adapter doesn't touch tenancy.
- Permission code renames in the frontend (`app-access.service.ts` access keys keep their string codes).
- MFA enrollment UX. Backend `mfa_enabled` flag is preserved on the User; enforcement is a separate Workstream.
- Migrating `auth_user` rows. The `auth_user` table stays empty; the W002 system check still applies.
- Frontend route guards (`appAccessGuard`). They keep their access keys and continue to be UX-only.
- Phase 4 and Phase 5 (long-tail call-site migration and Principal removal) — see locked scope.

---

## Critical Files

**Will be modified (by phase)**

| Phase | Files |
|---|---|
| 1 | `backend/accounts/models.py` (new), `backend/accounts/managers.py` (new), `backend/accounts/apps.py` (new), `backend/accounts/migrations/0001_initial.py` (new), `backend/accounts/tests.py` (new), `backend/api/tests_auth_parity_fixtures/*.json` (new), `backend/api/management/commands/capture_auth_parity_snapshots.py` (new), `backend/dmis_api/settings.py` (`AUTH_USER_MODEL`, `INSTALLED_APPS`), `backend/masterdata/services/iam_data_access.py` (extract `create_user_with_primary_tenant`, `verify_user_primary_tenant_membership`, `UserCreateRecordError`, `UserPrimaryTenantMembershipError`), `backend/masterdata/views.py` (structural refactor only — replace inline atomic block at 1566–1583 with helper call; update imports), `backend/masterdata/tests_iam_services.py` (new helper tests) |
| 2 | `backend/accounts/backends.py` (new), `backend/accounts/tests_backends.py` (new), `backend/api/tests_auth_parity.py` (new), `backend/api/authentication.py` (refactor `LegacyCompatAuthentication` to delegate), `backend/dmis_api/settings.py` (`AUTHENTICATION_BACKENDS`) |
| 3 | `backend/accounts/management/commands/sync_rbac_to_django_auth.py` (new), `backend/accounts/tests_bridge.py` (new), `backend/accounts/permissions.py` (new helper), `backend/api/rbac.py` (no semantic changes; add bridge-aware helpers if needed), `docs/adr/django-auth-adapter.md` (new ADR-lite) or appended paragraph in `docs/adr/system_application_architecture.md` |

**Read-only references for the implementer**

- `backend/api/authentication.py:20-26` — current `Principal` dataclass
- `backend/api/authentication.py:283-358` — `LegacyCompatAuthentication`
- `backend/api/authentication.py:98-156` — `_ensure_user_row` (reuse logic in `KeycloakOidcBackend`)
- `backend/api/rbac.py:537-581` — `resolve_roles_and_permissions` (used unchanged through Phase 3)
- `backend/api/checks.py:134-184` — W002 check (must still pass)
- `backend/dmis_api/settings.py:324-372, 976-1047` — runtime-env validation + auth settings
- `backend/api/tenancy.py` — tenancy resolution (untouched)
- `backend/DMIS_latest_schema_pgadmin.sql:5231-5262` — custom `"user"` table schema (model must match)
- `frontend/src/app/core/app-access.service.ts` — access keys (untouched)

---

## Verification Plan

### Per-phase gate

1. `python manage.py check` clean (run from `backend/`).
2. Full test suite: `python manage.py test --verbosity=2` (run from `backend/`).
3. New parity tests:
   - `whoami` returns identical JSON before and after the phase for the same input (JWT and `X-DMIS-Local-User`).
   - For each fixture user, `set(old_principal.permissions) == set(new_user.permissions)` and `set(old_principal.roles) == set(new_user.roles)`.
   - Local harness `X-DMIS-Local-User` allowlist: requests with allowlisted vs. non-allowlisted users behave exactly as before.
   - Legacy `X-Dev-User` continues to be rejected.
4. RBAC system check (W002) still passes (no rows in `auth_user`).
5. Tenant-first user creation tests (recent commits) all green.
6. IDOR negative tests pass (cross-tenant fetches return 403/404).

### End-to-end

- Local harness: log in as `test_user`, hit `/api/v1/auth/whoami/`, run a needs-list create + submit, run a master-data CRUD round-trip.
- Keycloak path (staging): same flow with a real OIDC token.
- Architecture review per `.agents/skills/system-architecture-review/SKILL.md` at end of each phase before merging.

---

## Codex GPT 5.5 Handoff Briefs (One Per Phase)

> **Operating contract**: Codex GPT 5.5 implements **one phase at a time**. After each phase Codex hands the diff back to Claude. Claude verifies against `Verification Plan` and the relevant canonical docs, requests fixes if needed, and only then approves moving to the next phase.

### Brief 1 — Phase 1: Custom User Model

**Repository state**: Branch `claude/funny-goldberg-8bdebc`. Working dir `C:\Users\wbowe\OneDrive\Desktop\project\DMIS_UpdatedVersion\.claude\worktrees\funny-goldberg-8bdebc`.

**Goal**: Introduce a custom `AUTH_USER_MODEL` that points at the existing PostgreSQL `"user"` table without altering any column or creating any migration that touches that table. After this phase, `request.user` is still a `Principal` (do **not** change auth flow yet); but Django ORM can now load users from the custom table via `accounts.DmisUser.objects.get(...)`.

**Concrete tasks**

1. Create `backend/accounts/__init__.py`, `backend/accounts/apps.py` (`AccountsConfig`), `backend/accounts/managers.py`, `backend/accounts/models.py`, `backend/accounts/migrations/__init__.py`, `backend/accounts/migrations/0001_initial.py`, `backend/accounts/tests.py`.
2. `DmisUserManager(BaseUserManager)`:
   - `create_user(username, email, password=None, **extra_fields)` calls into the existing tenant-first user creation service in `backend/masterdata/services/data_access.py` so primary `tenant_user` membership is created atomically. **Do not bypass it.** If the helper is not directly importable, raise `ImproperlyConfigured` rather than creating a tenant-less user.
   - `create_superuser` requires a `tenant_id` (or `tenant_code`) extra field, calls `create_user`, sets `is_active=True`, and adds the user to the `SYSTEM_ADMINISTRATOR` role via the existing custom RBAC tables (insert into `user_role` with the role lookup). Use parameterised raw SQL or the existing helpers — do not invent a new pattern.
3. `DmisUser(AbstractBaseUser, PermissionsMixin)`:
   - `class Meta: db_table = '"user"'`; `managed = False`. Confirm the literal quoted name renders correctly in SQL Django generates; if not, use `db_table = 'user'` and document the choice (some Django versions handle reserved-word quoting automatically).
   - Fields exactly match existing columns (`user_id` as `BigAutoField` PK; `username`, `email`, `full_name`, `is_active`, `password` mapped to `password_hash` via `db_column='password_hash'`, `mfa_enabled`, `status_code`, `login_count`, audit cols `create_by_id`, `create_dtime`, `update_by_id`, `update_dtime`, `version_nbr`).
   - `USERNAME_FIELD = 'username'`, `REQUIRED_FIELDS = ['email']`.
   - **`is_superuser` MUST be a read-only property returning `False` always**. `PermissionsMixin.has_perm` short-circuits when `is_superuser=True`, which would bypass DMIS RBAC silently. RBAC must remain the only source of permission truth. Override the field — possible patterns: redefine `is_superuser` as a `@property` (do NOT inherit `PermissionsMixin` directly if it injects the field; instead, manually add the `groups` and `user_permissions` M2M relationships so `user.has_perm` still flows through groups), or shadow with `BooleanField(default=False, editable=False)` plus a property override. Confirm with `python manage.py shell` that `user.is_superuser` is always `False` and that `user.has_perm(...)` does not short-circuit. Document the chosen pattern in your summary.
   - `is_staff` derived from membership in the `SYSTEM_ADMINISTRATOR` role: a `@cached_property` that runs a parameterised SQL query joining `user_role` and `role` to check membership. Do not add a column.
4. `INSTALLED_APPS += ['accounts']` and `AUTH_USER_MODEL = 'accounts.DmisUser'` in `backend/dmis_api/settings.py`. Add the setting **after** the existing auth block; do not touch `AUTH_ENABLED`/`DEV_AUTH_ENABLED`/`LOCAL_AUTH_HARNESS_ENABLED` or runtime-env validation.
5. Add a no-op migration (`0001_initial.py`) for the `accounts` app that **only** registers the model (`SeparateDatabaseAndState` with `state_operations=[CreateModel(...)]` and `database_operations=[]`) so Django's migration graph stays consistent without touching the `"user"` table. Migration must depend on `('auth', '0012_alter_user_first_name_max_length')` so swappable-model resolution works.
6. Add `backend/accounts/tests.py` covering: model loads existing rows; password check works against `password_hash` (or document why); `create_user` calls the tenant-first helper and raises `ImproperlyConfigured` when no tenant is provided; `is_superuser` is always `False`; `user.has_perm('anything')` does not short-circuit when the user has no groups.

**Constraints**

- **Do not** modify `backend/api/authentication.py`, `backend/api/rbac.py`, `backend/api/permissions.py`, `backend/api/tenancy.py`, or any view in this phase.
- **Do not** add or alter columns on the `"user"` table.
- **Do not** create rows in `auth_user`. The W002 system check (`backend/api/checks.py:134-184`) must still pass.
- **Do not** touch tenancy code or the `tenant_user` schema.
- **`is_superuser` MUST be a read-only property returning `False`**. Locked behind a property, with a test that asserts it.
- `is_staff` may be derived from membership in the `SYSTEM_ADMINISTRATOR` role (used only for Django admin gating).
- **AUTH_USER_MODEL swap recipe**: confirm `auth_user` is empty (W002 guard already does this), confirm no existing migration depends on `auth.User` directly, then set `AUTH_USER_MODEL`. Run `python manage.py migrate --check`. If Django flags the swap, **stop and ask** — do not force-fake migrations.
- Follow `backend/AGENTS.md` rules on input validation and SQL parameterization. Use `%s` placeholders only. Quote table/column names via `connection.ops.quote_name()` if needed.
- Match coding standards in `.claude/CLAUDE.md` (function-based views, raw SQL via `data_access.py`, no `.format()` or f-strings in SQL).
- Supply-chain hold: do **not** run `npm install`, do **not** introduce or update `axios`. Backend-only work; this should not arise.

**Additional Phase 1 deliverables (locked by architecture review)**

- Capture parity snapshots for Phase 2: for each canonical fixture user, record `whoami` JSON via the **current** `LegacyCompatAuthentication` and store under `backend/api/tests_auth_parity_fixtures/whoami_<username>.json` (pretty-print with `indent=2, sort_keys=True` for stable diffs). Generation script lives at `backend/api/management/commands/capture_auth_parity_snapshots.py` (new). Idempotent. Pick at minimum: one `SYSTEM_ADMINISTRATOR`, one `LOGISTICS_OFFICER`, one `EXECUTIVE`, one `AGENCY_DISTRIBUTOR`. Identify canonical fixture users via `LOCAL_AUTH_HARNESS_USERNAMES` defaults, dev role mappings in `backend/api/rbac.py:93-192`, and `backend/operations/management/commands/seed_relief_management_frontend_test_users.py`.
- Document the `createsuperuser` flow: since `DmisUserManager.create_user` requires a tenant, `manage.py createsuperuser` must be wrapped or extended to require a `--tenant` argument. Two options: (a) override `createsuperuser` to require `--tenant-code`; or (b) provide a separate `create_admin_user` management command. Pick one and explain why in the PR summary.

**Deliverable**: A single PR with model, manager, settings change, no-op migration, parity snapshots, tests, and a 250-word summary: files changed (with line counts); design decisions for tricky fields (`password` ↔ `password_hash`, `is_staff` derivation, `is_superuser=False` lock pattern with rationale); tenant-first creation entry point chosen; `createsuperuser` decision; parity snapshot files written; test commands run with results (`python manage.py check`, `python manage.py migrate --check`, `python manage.py test accounts --verbosity=2`, `python manage.py test --verbosity=2`); any deviation from this brief; any open questions.

**Verification Claude will run on return**: `python manage.py check`, `python manage.py migrate --check`, full test suite, fixture round-trip, W002 still passing, parity-snapshot files present, `is_superuser` lock asserted, no edits to forbidden files, architecture review against `docs/adr/system_application_architecture.md` and `docs/security/CONTROLS_MATRIX.md`.

---

### Brief 2 — Phase 2: Authentication Backends Split

**Pre-requisite**: Phase 1 merged.

**Goal**: Replace the body of `LegacyCompatAuthentication.authenticate()` with delegation to two new Django authentication backends. After this phase, `request.user` is a real `DmisUser` instance (not a `Principal` dataclass) but exposes the same attributes (`user_id`, `username`, `roles`, `permissions`, `is_authenticated`) so all 109 existing call sites continue to work.

**Concrete tasks**

1. Create `backend/accounts/backends.py`:
   - `KeycloakOidcBackend(BaseBackend)`: `authenticate(request, jwt=None)` runs the JWT-validation logic currently inside `LegacyCompatAuthentication` (extract claims, verify via `_verify_jwt_with_jwks`), then `User.objects.get_or_create(user_id=...)` populating fields from claims. Returns the `User` instance.
   - `LocalHarnessBackend(ModelBackend)`: standard username/password auth against `DmisUser`. Used by Django admin, shell, and the harness flow.
2. Add `Principal`-shape attributes to `DmisUser`:
   - `@property def roles(self) -> list[str]` and `@property def permissions(self) -> list[str]` resolved by calling existing `resolve_roles_and_permissions(request, self)` and caching on the instance per request. Use a `_rbac_resolved` private flag to avoid double resolution.
   - `@property def is_authenticated` is already provided by `AbstractBaseUser`; just verify semantics match.
3. Refactor `backend/api/authentication.py`:
   - `LegacyCompatAuthentication.authenticate()` becomes a dispatcher: legacy header rejection (unchanged), then call the right backend based on `local_auth_harness_enabled()` / `AUTH_ENABLED` / `DEV_AUTH_ENABLED`.
   - Replace `Principal(...)` constructions with returns of `User` instances. Keep the `Principal` dataclass importable but mark deprecated; tests that construct `Principal` directly should still work.
   - `_ensure_user_row` is replaced by `User.objects.update_or_create` inside `KeycloakOidcBackend`.
4. Add `AUTHENTICATION_BACKENDS = ['accounts.backends.KeycloakOidcBackend', 'accounts.backends.LocalHarnessBackend', 'django.contrib.auth.backends.ModelBackend']` to settings.
5. Tests:
   - `backend/accounts/tests_backends.py`: unit-test each backend in isolation.
   - Update `backend/api/tests.py` (or wherever `Principal`-construction patterns live) to assert the new return type wherever it appears.
   - **Parity tests** (new file `backend/api/tests_auth_parity.py`): for each canonical fixture user, hit `whoami` with the same JWT + harness header through both `LegacyCompatAuthentication` (snapshot from Phase 1) and the new flow; assert identical response JSON.
   - Local harness flow: `X-DMIS-Local-User` allowlisted user → 200 with same payload; non-allowlisted → 403; legacy `X-Dev-User` → 401.

**Constraints**

- **Do not** change any RBAC table schema, permission codes, role codes, or `resolve_roles_and_permissions` logic.
- **Do not** touch tenancy resolution.
- **Do not** populate `auth_user` rows.
- Runtime-env validation in `backend/dmis_api/settings.py:324-372` must still trip on misconfiguration.
- Preserve `LOCAL_AUTH_HARNESS_USERNAMES` allowlist semantics exactly.
- **Preserve every existing auth audit emission**. Every `_log_auth_warning(...)` call (legacy header rejection, allowlist rejection, JWKS validation failure) must keep emitting the same event name and payload from the new backends. Successful auth events that emit logs today must keep emitting them. (NIST CSF DE.AE-3.)
- **Apply login throttling to `LocalHarnessBackend`**. The 5-per-15-min login limit defined in `backend/AGENTS.md` and `docs/security/SECURITY_ARCHITECTURE.md` must cover the new backend. If login throttling is currently in middleware, ensure the harness path goes through it.
- Follow `backend/AGENTS.md` for auth changes — this is medium-risk work; document the architecture review checkpoint outcome in the PR description.

**Deliverable**: Single PR. 250-word summary describing the dispatcher refactor, parity-test results (assert against the snapshots captured in Phase 1), audit-log preservation evidence, throttle wiring, and any subtle differences in response payload (must be zero in production paths).

**Verification Claude will run on return**: parity test suite vs. Phase 1 snapshots, runtime-env validation tests, IDOR negative tests, audit-log emission diff, login-throttle test, the architecture review skill against `docs/security/SECURITY_ARCHITECTURE.md` and `docs/security/THREAT_MODEL.md`.

---

### Brief 3 — Phase 3: Two-Way Permission/Group Bridge

**Pre-requisite**: Phase 2 merged.

**Goal**: Make `request.user.has_perm(...)` work alongside `'code' in request.user.permissions` by syncing the custom `role`/`permission`/`user_role`/`role_permission` data into Django's `auth.Group` and `auth.Permission` tables. The custom tables remain the source of truth; the Django side is derived.

**Concrete tasks**

1. Create `backend/accounts/management/commands/sync_rbac_to_django_auth.py`:
   - Idempotent.
   - For each row in `permission`: ensure a `ContentType(app_label='dmis', model=resource)` exists; ensure a `Permission(codename=f"{resource}__{action}", content_type=ct, name=...)`. Use double underscore to avoid colliding with Django's built-in `view_/add_/change_/delete_` codenames.
   - For each row in `role`: ensure `Group(name=role.code)`. Resolve `role_permission` rows and set `Group.permissions = [...]` exactly.
   - For each row in `user_role`: set `User.groups.add(group)` (or full reset to mirror DB).
   - Print a structured summary (counts created/updated/unchanged).
2. Wire the command into a post-migrate signal **only in dev/test settings** (production runs it as a release step — do not run on every request).
3. Add a helper `accounts.permissions.bridge_codename(resource: str, action: str) -> str` so call sites can opt into Django checks: `user.has_perm(bridge_codename('masterdata', 'view'))`.
4. Tests:
   - `backend/accounts/tests_bridge.py`: run the sync against a fixture, assert `set(user.get_all_permissions())` matches `set(resolve_roles_and_permissions(...).permissions)` (translated through `bridge_codename`).
   - Idempotency: running the command twice produces identical state.

**Constraints**

- **Do not** change the format of permission codes returned by `resolve_roles_and_permissions`. Existing string-based checks (`'masterdata.view' in principal.permissions`) must keep working.
- **Do not** populate `auth_user` rows — only `auth_group`, `auth_permission`, `auth_group_permissions`, and the M2M on `User.groups`.
- The W002 system check needs an exemption clarified: it currently warns on `auth_user` rows; ensure it still does and does **not** warn on `auth_group_permissions`. If the check needs to be widened to allow group-permission rows, update `backend/api/checks.py` and document why.

**Additional Phase 3 deliverable (locked by architecture review)**

- **ADR-lite append** to `docs/adr/system_application_architecture.md` (or a new `docs/adr/django-auth-adapter.md`): one paragraph documenting the adapter decision, alternatives considered (full migration rejected as high-risk), the bridge sunset condition, and a link back to this plan.

**Deliverable**: Single PR. 200-word summary including: command usage, sample output, parity-test result, the W002 check decision, and the ADR-lite append link.

**Verification Claude will run on return**: parity test, idempotency test, ADR-lite append present, architecture review against `docs/security/CONTROLS_MATRIX.md` (IAM-04 central RBAC enforcement).

---

## Architecture Review (Pre-Plan, Mandatory per CLAUDE.md)

Performed against `.agents/skills/system-architecture-review/SKILL.md`.

**Risk score: 8 / Medium**

| Axis | Score | Justification |
|---|---|---|
| Blast radius | 2 | Auth + RBAC is platform-wide |
| Data sensitivity | 2 | Identity is the most control-sensitive surface |
| Authority change | 2 | Adds Django auth as a parallel authority |
| Reversibility | 1 | Schema-additive only (no-op migration, settings flip, group/permission rows can be deleted) |
| External surface | 0 | No `/api/v1/**` contract change |
| Operational impact | 1 | Adds `sync_rbac_to_django_auth` to deploy pipeline |

**Decision: Conditionally Aligned.** The phased adapter design respects every non-negotiable from the canonical docs (Keycloak as sole production identity, tenant-first user creation atomicity, backend authorization authoritative, no dev impersonation in production, central RBAC, durable audit). It does not introduce f-string SQL, dev-impersonation leak paths, or in-process-memory dependencies. The required changes below are completeness items, not redesigns.

**Required Changes (folded into the briefs and locked decisions)**

1. **AUTH_USER_MODEL swap gotcha**. Django treats `AUTH_USER_MODEL` as swappable only on a fresh DB. Brief 1 must include the recipe for an existing DB: confirm `auth_user` is empty (W002 guard already does this), set `AUTH_USER_MODEL` *before* any new migrations, and document that any test DB created from snapshot data needs the auth-app migration sequence checked. If `manage.py migrate --check` flags the swap, Codex stops and asks.
2. **`is_superuser=False` always**. `PermissionsMixin.has_perm` short-circuits to True when `is_superuser=True`, which would silently bypass DMIS RBAC. Brief 1 must hard-code `is_superuser` as `False` (read-only property returning False) so RBAC remains the only source of permission truth. `is_staff` derivation from `SYSTEM_ADMINISTRATOR` group is fine (admin access only). [ASVS V4.1.5; ISO 25010: Security — Authenticity]
3. **Parity snapshot is a Phase 1 deliverable**, not Phase 2. Brief 1 captures `whoami` JSON for canonical fixtures + JWTs and stores them in `backend/api/tests_auth_parity_fixtures/`. Brief 2 asserts against those snapshots.
4. **Preserve all auth audit emissions**. `_log_auth_warning("auth.rejected_legacy_dev_header", ...)`, allowlist rejections, JWKS validation failures, and successful auth events all currently emit log lines. Brief 2's new backends must emit identical event names and structured payloads. [NIST CSF DE.AE-3; ASVS V7.1]
5. **Login throttle covers `LocalHarnessBackend`**. The 5-per-15-min login limit (per `backend/AGENTS.md`) currently applies to legacy paths. Brief 2 must wire the same tier to the new backend; otherwise harness-mode brute force would be ungated. [ASVS V2.2.1]
6. **ADR-lite append**. Risk score 8 falls in the "ADR-lite append acceptable" band per the skill's rubric. Append a paragraph to `docs/adr/system_application_architecture.md` (or a new `docs/adr/django-auth-adapter.md`) recording: decision, alternatives considered, sunset condition for the bridge, and link to this plan. Brief 3's deliverable includes the ADR-lite append.
7. **Architecture-review checkpoint embedded in each brief**. Each brief deliverable must include the architecture review run by the implementer (or by Claude on return) before merge, citing this section.

**Conformance evidence to capture per phase**

- `python manage.py check` clean — every phase
- Full backend test suite — every phase
- `migrate --check` — Phases 1 and 3
- W002 system check still passing — every phase
- Parity test JSON deltas — Phase 2
- Bridge sync idempotency — Phase 3
- ADR-lite append PR link — Phase 3

**Standards cited**: ISO 25010 (Security: Authenticity, Confidentiality; Maintainability: Modifiability; Reliability: Recoverability); ASVS V2.1.1, V2.2.1, V4.1.5, V7.1; NIST CSF DE.AE-3, IAM control family; OWASP API Top 10 (BOLA — preserved by tenancy untouched).

**Docs checked**: `docs/adr/system_application_architecture.md`, `docs/security/SECURITY_ARCHITECTURE.md`, `docs/security/THREAT_MODEL.md`, `docs/security/CONTROLS_MATRIX.md`, `docs/implementation/production_readiness_checklist.md`, `backend/AGENTS.md`, `frontend/AGENTS.md`, `.claude/CLAUDE.md`, `.agents/skills/system-architecture-review/SKILL.md`.

---

## Decisions Locked (Confirmed by User)

1. **Scope: Phases 1–3 only.** No Phase 4 or 5 in this initiative. The bridge serves both styles indefinitely. Briefs 4 and 5 (above sections marked "Reference Only") are kept as future-reference templates only — Codex GPT 5.5 should **not** implement them.
2. **App location: new standalone `accounts` app.**
3. **Local harness: keep `X-DMIS-Local-User` header flow.** The header maps to a `login()` under the hood through `LocalHarnessBackend`. Allowlist semantics, runtime-env validation, and legacy `X-Dev-User` rejection are preserved exactly.
4. **Tenant-first creation entry point**: Codex must identify the canonical helper from the recent hardening commits (`3ade06b0`, `7243aab3`, `9a189f57`, `292b5ada`, `57efc4a0`) and call it from `DmisUserManager.create_user`. If multiple entry points exist, Codex documents which it chose and why; if none is exposed cleanly, Codex stops and asks before bypassing.

---

## Risk Summary

| Phase | Risk | Reversible | Ship value |
|---|---|---|---|
| 1 | Low–Medium | Yes (revert setting) | Django ORM access to users |
| 2 | Medium | Yes | `request.user` is a real Django User |
| 3 | Medium | Yes | `user.has_perm` works; admin & shell usable |

**Stopping at Phase 3 gives you most of the benefit at the lowest total risk** — Django auth is fully in place, `user.has_perm` works, the local harness uses `ModelBackend`, Keycloak still authenticates production, and you don't have to touch 100+ call sites.
