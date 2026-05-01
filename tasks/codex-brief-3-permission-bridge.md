# Codex Brief 3 — Phase 3: Two-Way Permission/Group Bridge

> **Source-of-truth plan**: `tasks/django-auth-adapter-plan.md` (read first for full context).
> **Pre-requisites**: Brief 1 (Phase 1) and Brief 2 (Phase 2) merged and verified by Claude.
> **Risk**: Medium. **Reversible**: Yes (registration flag; bridge sync command can be re-run or disabled).
> **Working directory**: `C:\Users\wbowe\OneDrive\Desktop\project\DMIS_UpdatedVersion\.claude\worktrees\funny-goldberg-8bdebc`

---

## Goal

Make `request.user.has_perm(...)` work alongside `'code' in request.user.permissions` by syncing the custom `role`/`permission`/`user_role`/`role_permission` data into Django's `auth.Group` and `auth.Permission` tables. The custom tables remain the source of truth; the Django side is derived.

After this phase:
- Django admin works with proper permission gating.
- `user.has_perm('masterdata__view')` returns the same answer as `'masterdata.view' in user.permissions`.
- The bridge is idempotent and re-runnable on every deploy.

---

## Repository context (read before writing code)

- Phase 1 delivered: `accounts.DmisUser` model bound to `"user"` table; `is_superuser=False` lock.
- Phase 2 delivered: `KeycloakOidcBackend` and `LocalHarnessBackend`; `request.user` is a real `DmisUser` with `Principal`-shape properties; parity snapshots match.
- Existing custom RBAC tables (per `backend/DMIS_latest_schema_pgadmin.sql`):
  - `role(id PK, code, name, description, created_at)` — role definitions.
  - `permission(perm_id PK, resource, action, ...audit cols)` — permission definitions; permission codes are `f"{resource}.{action}"` (e.g., `masterdata.view`).
  - `role_permission(role_id, perm_id, scope_json, ...audit cols)` — role↔permission M2M.
  - `user_role(user_id, role_id, assigned_at, assigned_by, ...audit cols)` — user↔role M2M.
- Existing resolution: `backend/api/rbac.py:537-581` `resolve_roles_and_permissions(request, principal)` returns `(roles[], permissions[])` from these tables, with compatibility overrides in `_ROLE_PERMISSION_COMPAT_OVERRIDES` (lines 206–508) and dev-mode overrides in `_DEV_ROLE_PERMISSION_MAP` (lines 93–192).
- `backend/api/checks.py:134-184` — W002 check warns if Django auth tables have rows. Must not warn on `auth_group_permissions` after this phase (you may need to widen the check to allow that and document why).
- Frontend permission codes (read-only context): `frontend/src/app/core/app-access.service.ts` uses string codes like `'masterdata.view'` — those stay unchanged.

---

## Concrete tasks

### 1. `backend/accounts/management/commands/sync_rbac_to_django_auth.py` (new)

A management command that maps the custom RBAC tables into Django's `auth.Group` and `auth.Permission`:

```python
class Command(BaseCommand):
    help = "Sync DMIS custom RBAC tables into Django auth.Group / auth.Permission. Idempotent."

    def handle(self, *args, **options):
        # 1. For each row in `permission` (resource, action):
        #    - ensure ContentType(app_label='dmis', model=resource) exists
        #    - ensure Permission(codename=f"{resource}__{action}", content_type=ct, name=auto_label)
        #    Use double underscore to avoid collision with built-in view_/add_/change_/delete_.
        # 2. For each row in `role` (code, name):
        #    - ensure Group(name=role.code)
        # 3. For each row in `role_permission`:
        #    - resolve to (Group, Permission)
        #    - set Group.permissions = [...] exactly (full reset to mirror DB)
        # 4. For each row in `user_role`:
        #    - resolve to (User, Group)
        #    - set User.groups = [...] exactly (full reset to mirror DB)
        # 5. Print structured summary: counts created/updated/unchanged per table.
```

Implementation notes:

- Run inside a single transaction (`@transaction.atomic`) so failures roll back cleanly.
- Use `bulk_create(..., ignore_conflicts=True)` plus follow-up SELECTs, or `update_or_create` per row — measure and pick the cheaper one for the expected RBAC table sizes.
- Handle deletions: if a `role` was removed from the custom table since last sync, delete its `Group`. Same for `Permission` rows whose `(resource, action)` no longer exists.
- Codename construction: `codename = f"{resource}__{action}"`. Confirm the resulting codename respects Django's 100-char limit (truncate with a warning if any DMIS permission codes exceed it).
- ContentType `app_label` is the literal string `'dmis'`, not `accounts` — these are synthetic ContentTypes that don't map to a Django model.
- Print summary in this format:
  ```
  Permissions: 60 created, 0 updated, 5 unchanged, 0 deleted
  Groups: 25 created, 0 updated, 0 unchanged, 0 deleted
  Group permissions: 312 mappings synced
  User groups: 8 user-group assignments synced
  ```

### 2. Wire post-migrate signal (dev/test only)

In `backend/accounts/apps.py`:

```python
class AccountsConfig(AppConfig):
    def ready(self):
        from django.db.models.signals import post_migrate
        from django.conf import settings

        if getattr(settings, "RBAC_BRIDGE_AUTORUN_ON_MIGRATE", False):
            post_migrate.connect(_run_rbac_bridge_sync, sender=self)
```

Default `RBAC_BRIDGE_AUTORUN_ON_MIGRATE = False`. Set it to `True` only in `local-harness` and `prod-like-local` runtime environments. **Production runs the command manually as a release step** — do not auto-run on every request or every migrate in production.

### 3. `backend/accounts/permissions.py` (new helper)

```python
def bridge_codename(resource: str, action: str) -> str:
    """Translate a DMIS permission code (resource, action) into the Django codename used by the bridge."""
    return f"{resource}__{action}"
```

So call sites can opt into Django checks: `user.has_perm(bridge_codename('masterdata', 'view'))`.

### 4. Tests

- **`backend/accounts/tests_bridge.py`** (new):
  - `test_sync_creates_groups_and_permissions`: run the sync against a fixture; assert every `role` row has a matching `Group`; every `permission` row has a matching `Permission`; counts match.
  - `test_sync_assigns_user_groups`: assert `user.groups.all()` matches the rows in `user_role` for that user.
  - `test_has_perm_via_bridge_matches_resolve_roles_and_permissions`: for each fixture user, assert
    ```python
    set(user.get_all_permissions()) == {
        f"dmis.{bridge_codename(r, a)}"
        for r, a in resolve_roles_and_permissions_split(...)
    }
    ```
    where the right-hand side uses the existing `resolve_roles_and_permissions` translated through `bridge_codename`.
  - `test_sync_is_idempotent`: run the command twice; assert state is identical (counts in second run are 0 created / 0 updated / N unchanged).
  - `test_sync_deletes_orphans`: insert a `Group` whose `role` doesn't exist; run sync; assert it's deleted.

### 5. W002 check decision

The current W002 check (`backend/api/checks.py:134-184`) warns if Django auth tables have rows. Phase 3 populates `auth_group`, `auth_permission`, `auth_group_permissions`, and the `<app>_<user>_groups` M2M for `accounts.DmisUser`.

You must:
- Confirm the W002 check still warns on rows in `auth_user` (which remains empty).
- Confirm the W002 check does **not** warn on rows in `auth_group`, `auth_permission`, `auth_group_permissions`, or the User-Groups M2M after the bridge has run.
- If the check needs to be widened, update `backend/api/checks.py` so the warning is scoped to `auth_user` specifically. Document the change in the PR description with the rationale.

---

## Additional Phase 3 deliverable (locked by architecture review)

### ADR-lite append

Append to `docs/adr/system_application_architecture.md` **or** create a new ADR at `docs/adr/django-auth-adapter.md`. Choose the approach that fits the existing ADR conventions in the repo (read `docs/adr/` first to see how prior ADRs are structured).

The ADR-lite must record:

1. **Decision**: Adopt Django's `auth.User`, `auth.Group`, `auth.Permission` as a parallel authority via an adapter on the existing `"user"` table; bridge custom RBAC into Django auth via `sync_rbac_to_django_auth`.
2. **Alternatives considered**: Full migration (rejected — high risk, 109 consumer sites, would break tenant-first creation hardening); claim-only RBAC (rejected — violates "backend authorization authoritative").
3. **Sunset condition for the bridge**: The bridge can be retired once all permission checks have migrated from `'code' in user.permissions` to `user.has_perm(...)` (Phase 4 territory; out of scope for this initiative).
4. **Link** to `tasks/django-auth-adapter-plan.md`.

---

## Constraints (HARD — do not violate)

- **Do not** change the format of permission codes returned by `resolve_roles_and_permissions`. Existing string-based checks (`'masterdata.view' in principal.permissions`) must keep working.
- **Do not** populate `auth_user` rows — only `auth_group`, `auth_permission`, `auth_group_permissions`, and the M2M on `User.groups`.
- **Do not** modify the custom RBAC tables (`role`, `permission`, `user_role`, `role_permission`) — they remain the source of truth.
- **Do not** touch `_DEV_ROLE_PERMISSION_MAP` or `_ROLE_PERMISSION_COMPAT_OVERRIDES` in `backend/api/rbac.py`. Their output continues to feed `resolve_roles_and_permissions`; the bridge mirrors that output into Django auth, not the inputs.
- **Do not** auto-run the bridge sync on every request. Post-migrate signal in dev/test only; production is a release step.
- Follow `backend/AGENTS.md` for SQL parameterization and input validation.
- Supply-chain hold: do not run `npm install`, do not introduce or update `axios`.

## Verification gates (must pass before declaring done)

Run from `backend/`:

```bash
python manage.py check
python manage.py migrate --check
python manage.py sync_rbac_to_django_auth          # first run
python manage.py sync_rbac_to_django_auth          # second run (idempotency)
python manage.py test accounts --verbosity=2
python manage.py test --verbosity=2
```

All must pass. Specifically:
- `user.has_perm(bridge_codename('masterdata', 'view'))` matches `'masterdata.view' in user.permissions` for every fixture user.
- Bridge sync is idempotent (second run shows zero created / zero updated).
- W002 check still warns on `auth_user` rows (try inserting one in a test, assert it warns) and does NOT warn on `auth_group_permissions` rows.
- Phase 1 and Phase 2 parity snapshots still match.

---

## Deliverable

A 250-word summary at the end of your reply containing:

1. **Files created and files modified**, with line counts.
2. **Command usage**: example invocation, sample output (counts).
3. **Parity-test result**: confirmation that `user.has_perm` via the bridge matches `resolve_roles_and_permissions` for every fixture user. Note any unmappable permission codes (e.g., codes that exceed Django's 100-char codename limit) and how you handled them.
4. **Idempotency check**: counts from first and second sync runs.
5. **W002 check decision**: did you widen the check? What is its current behavior?
6. **ADR-lite append**: link to the file you appended or created.
7. **Test commands run and their results**.
8. **Any deviation from this brief**, with justification.
9. **Any open questions** for Claude.

If you encounter ambiguity, **stop and report the question** instead of guessing. This is the final phase in scope; after Claude verifies it, the adapter is complete.
