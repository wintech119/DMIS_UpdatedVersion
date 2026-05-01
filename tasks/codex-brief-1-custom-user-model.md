# Codex Brief 1 — Phase 1: Custom User Model Bound to Existing `"user"` Table

> **Source-of-truth plan**: `tasks/django-auth-adapter-plan.md` (read first for full context).
> **Pre-requisites**: None. This is the first phase.
> **Risk**: Low–Medium. **Reversible**: Yes (single setting flip).
> **Working directory**: `{WORKING_DIR}`

---

## Goal

Introduce a custom Django `AUTH_USER_MODEL = 'accounts.DmisUser'` that maps onto the existing PostgreSQL `"user"` table without altering any column or creating any migration that touches that table.

After this phase, Django ORM can load users from the custom table via `accounts.DmisUser.objects.get(...)`, and the authentication adapter surface may return `accounts.DmisUser` on Django-auth paths while preserving the Principal-compatible roles/permissions shape expected by existing DRF/local-harness flows.

---

## Repository context (read before writing code)

- Django 4.2 LTS + DRF, Python 3.11+, PostgreSQL 16+. Backend is `backend/`. `manage.py` lives at `backend/manage.py`.
- DMIS does **not** use Django's `auth_user` table. There is a custom `"user"` table in PostgreSQL (note the literal double quotes around `user` because `user` is a reserved word in some SQL contexts). It is fully populated. `auth_user` is empty. A system check `W002` in `backend/api/checks.py:134-184` warns if `auth_user` has rows — it must keep passing.
- `request.user` compatibility remains critical: existing call sites read `request.user.user_id`, `.username`, `.roles`, `.permissions`, `.is_authenticated`. Phase 1 now includes the auth adapter/local-harness compatibility work needed to preserve that shape while introducing `accounts.DmisUser`. The actual scope includes `backend/api/authentication.py` and the local-harness auth flow, not only the ORM model.
- The custom `"user"` table columns (per `backend/DMIS_latest_schema_pgadmin.sql` lines 5231–5262) include at least: `user_id` (PK, integer, generated), `email`, `username`, `user_name`, `password_hash`, `password_algo`, `mfa_enabled`, `is_active`, `status_code` ('A'|'I'|'L'), `version_nbr`, `login_count`, plus audit columns (`create_by_id`, `create_dtime`, `update_by_id`, `update_dtime`). Inspect the SQL file to confirm exact column types and any columns omitted; mirror them faithfully.
- Tenant-first user creation was just hardened in commits `3ade06b0`, `7243aab3`, `9a189f57`, `292b5ada`, `57efc4a0`. The canonical tenant-first user creation helper lives in `backend/masterdata/services/data_access.py` (and is called from `backend/masterdata/views.py`). You **must** call this helper from `DmisUserManager.create_user`. If you cannot find a clean entry point, **stop and document the question** in your summary — do not bypass it.

---

## Concrete tasks

### 0. Service-layer helper extraction (PREREQUISITE for Task 2)

**Why this is here**: The original brief assumed a tenant-first user-creation helper already existed in `masterdata/services/data_access.py`. It does not — the atomic logic currently lives inline in `backend/masterdata/views.py:1566-1583`, calling `create_record()` plus `iam_data_access.assign_tenant_user()`. `DmisUserManager.create_user` cannot call view code, so the atomic flow must be lifted into the service layer first. This is a **non-functional refactor** — zero behavior change for existing API consumers.

**Where it goes**: `backend/masterdata/services/iam_data_access.py` (this module already houses `assign_tenant_user`, `has_active_primary_tenant_membership`, `count_active_primary_tenant_memberships` — the helper belongs alongside them).

**Changes to `backend/masterdata/services/iam_data_access.py`**:

1. **Move** `UserCreateRecordError` and `UserPrimaryTenantMembershipError` class definitions from `backend/masterdata/views.py:122-128` into this module (verbatim — same fields, same semantics).
2. **Move** `_verify_user_primary_tenant_membership(tenant_id, user_id)` from `backend/masterdata/views.py:278-286` into this module. **Rename** to `verify_user_primary_tenant_membership` (drop the leading underscore — it's now public API of the service).
3. **Add** the new helper:

   ```python
   def create_user_with_primary_tenant(
       *,
       tenant_id: int,
       record_data: dict[str, Any],
       actor_id: Any,
       access_level: str = "STANDARD",
   ) -> tuple[int, list[str]]:
       """
       Atomically create a user row and exactly one active primary
       tenant_user membership. Returns (user_id, warnings).

       Raises:
           UserCreateRecordError: when create_record returns None.
           UserPrimaryTenantMembershipError: when the membership insert
               returns 0 rows or verification fails.

       The transaction rolls back on any raised exception, so a membership
       failure leaves no orphan user row.
       """
       from masterdata.services.data_access import create_record  # local import to avoid cycle

       with transaction.atomic():
           raw_pk_val, warnings = create_record("user", record_data, actor_id)
           if raw_pk_val is None:
               raise UserCreateRecordError(warnings)
           pk_val = int(raw_pk_val)
           membership_created = assign_tenant_user(
               tenant_id, pk_val, access_level, actor_id,
               is_primary_tenant=True,
           )
           if not membership_created:
               raise UserPrimaryTenantMembershipError(
                   "Primary tenant membership insert did not create a row."
               )
           verify_user_primary_tenant_membership(tenant_id, pk_val)
           return pk_val, list(warnings or [])
   ```

**Changes to `backend/masterdata/views.py`** (the ONLY allowed view edits in this phase — purely structural, zero behavior change):

1. **Remove** the local definitions of `UserCreateRecordError` and `UserPrimaryTenantMembershipError` (lines 122–128).
2. **Remove** the local `_verify_user_primary_tenant_membership` (lines 278–286).
3. **Add** an import from the service module:

   ```python
   from masterdata.services.iam_data_access import (
       UserCreateRecordError,
       UserPrimaryTenantMembershipError,
       verify_user_primary_tenant_membership,
       create_user_with_primary_tenant,
   )
   ```

4. **Update** the call site at line 337 inside `_validate_user_update_assigned_warehouse_tenant` to use `verify_user_primary_tenant_membership` (no underscore).
5. **Replace** the atomic block at lines 1566–1583 with a single call:

   ```python
   try:
       pk_val, warnings = create_user_with_primary_tenant(
           tenant_id=tenant_id,
           record_data=data,
           actor_id=_actor_id(request),
       )
   except UserCreateRecordError as exc:
       # existing handler at lines 1584–1603 stays unchanged
       ...
   except Exception as exc:
       # existing handler at lines 1604–1612 stays unchanged
       ...
   ```

   The surrounding error-handling code (lines 1584–1612) stays unchanged because the helper raises exactly the same exception types.

**Tests for the helper** — `backend/masterdata/tests_iam_services.py` (new file):

- `test_create_user_with_primary_tenant_happy_path`: returns `(user_id, warnings)` with both DB rows present.
- `test_raises_user_create_record_error_when_create_returns_none`.
- `test_raises_membership_error_when_assign_returns_false`.
- `test_raises_membership_error_when_verification_fails`.
- `test_rolls_back_user_row_when_membership_fails`: assert no orphan row in `"user"` after a forced membership failure.

**Existing tests must pass without modification.** Run the masterdata test suite to confirm:

```bash
python manage.py test masterdata --verbosity=2
```

Zero new failures. If any existing test breaks, the refactor changed observable behavior — fix the refactor, do not modify the test.

---

### 1. Create app skeleton

Create the `accounts` Django app under `backend/`:

- `backend/accounts/__init__.py`
- `backend/accounts/apps.py` with `AccountsConfig(name='accounts')`
- `backend/accounts/managers.py`
- `backend/accounts/models.py`
- `backend/accounts/migrations/__init__.py`
- `backend/accounts/migrations/0001_initial.py` (no-op for the database; see task 6)
- `backend/accounts/tests.py`

### 2. `DmisUserManager(BaseUserManager)`

- `create_user(username, email, password=None, **extra_fields)`:
  - Requires `tenant_id` (or `tenant_code` resolved to `tenant_id` via a lookup against the `tenant` table) in `extra_fields`. Raise `ImproperlyConfigured` if absent.
  - Builds a `record_data` dict matching the shape `create_record('user', ...)` expects (mirror what the API view assembles in `backend/masterdata/views.py` around line 1490 — at minimum `username`, `email`, `password_hash`, `full_name` or `user_name`, `is_active`, `status_code='A'`).
  - Hashes the supplied password via `make_password()` and stores it in the `password_hash` field of `record_data`.
  - Calls `create_user_with_primary_tenant(tenant_id=..., record_data=..., actor_id="system")` from `masterdata.services.iam_data_access`. Use `actor_id="system"` (or the user_id of the caller if invoked through Django admin) — do not invent a new pattern.
  - Translates helper exceptions: `UserCreateRecordError` → `IntegrityError` (or `ValidationError` if a more useful surface exists); `UserPrimaryTenantMembershipError` → `IntegrityError`.
  - Returns the `DmisUser` instance freshly loaded via `self.get(pk=user_id)`.
- `create_superuser(username, email, password=None, **extra_fields)`:
  - Requires `tenant_id` or `tenant_code` extra field.
  - Calls `create_user(...)` to obtain the new user.
  - Adds the user to the `SYSTEM_ADMINISTRATOR` role via the existing custom RBAC tables (insert into `user_role` with the role lookup). Use parameterised raw SQL — do not invent a new pattern. Run inside a `transaction.atomic()` block so failure rolls back the role assignment without orphaning state in `user_role`.
  - Returns the `DmisUser` instance.

### 3. `DmisUser(AbstractBaseUser, PermissionsMixin)`

- `class Meta: db_table = '"user"'`; `managed = False`. Confirm the literal quoted name renders correctly in the SQL Django generates; if not, use `db_table = 'user'` and document the choice (some Django versions handle reserved-word quoting automatically).
- Field definitions exactly match the `"user"` columns:
  - `user_id` as `BigAutoField` (or `IntegerField` if the column is plain `integer`) primary key
  - `username`, `email`, `full_name` (or `user_name` — verify which column carries the full name)
  - `is_active` (`BooleanField`)
  - `password` mapped to the custom `password_hash` column via `db_column='password_hash'`
  - `password_algo` (read-only or non-editable)
  - `mfa_enabled` (`BooleanField`)
  - `status_code` (`CharField(max_length=1)`)
  - `login_count` (`IntegerField`)
  - audit cols: `create_by_id`, `create_dtime`, `update_by_id`, `update_dtime`, `version_nbr`
- `USERNAME_FIELD = 'username'`, `REQUIRED_FIELDS = ['email']`.
- `objects = DmisUserManager()`.

#### `is_superuser` MUST always be `False` (HARD REQUIREMENT)

`PermissionsMixin.has_perm` short-circuits to `True` when `is_superuser=True`, which would silently bypass DMIS RBAC. RBAC must remain the only source of permission truth.

To override the field from `PermissionsMixin`, **redeclare `is_superuser` on `DmisUser` as a property (not a model field)**. The simplest correct pattern:

> **Do not inherit `PermissionsMixin` directly if it injects an `is_superuser` field.** Instead, manually add the `groups` and `user_permissions` `ManyToManyField` relations the same way `PermissionsMixin` does, define `get_user_permissions`, `get_group_permissions`, `get_all_permissions`, `has_perm`, `has_perms`, and `has_module_perms` exactly as `PermissionsMixin` does **but with the `is_superuser` short-circuit removed**, and define `is_superuser` as a `@property` returning `False`.

Confirm with `python manage.py shell` that `user.is_superuser` is always `False` and that `user.has_perm(...)` does not short-circuit (returns `False` for a user with no groups). Document the chosen pattern in your summary.

#### `is_staff` derivation

`is_staff` is a `@cached_property` that runs a parameterised SQL query joining `user_role` and `role` to check `SYSTEM_ADMINISTRATOR` membership. Do not add a column.

#### Properties NOT to add in this phase

Do **not** add `roles` or `permissions` properties yet — that is Phase 2's job.

### 4. Settings update

In `backend/dmis_api/settings.py`:

- Add `'accounts'` to `INSTALLED_APPS` (after `'django.contrib.auth'` and before the DMIS apps so the auth-app discovery order is correct).
- Add `AUTH_USER_MODEL = 'accounts.DmisUser'` in a clearly commented block after the existing auth settings around line 976.
- Do **not** touch `AUTH_ENABLED`, `DEV_AUTH_ENABLED`, `LOCAL_AUTH_HARNESS_ENABLED`, runtime-env validation (lines 324–372), or any other auth setting.

### 5. Tests at `backend/accounts/tests.py`

- `DmisUserModelTests`: load an existing fixture user via `DmisUser.objects.get(username=...)` and assert all fields populate correctly. Test `password_hash` round-trip via `check_password` if it works — if hashes are stored in a non-Django-native format, document why this is skipped.
- `DmisUserSecurityTests`:
  - `test_is_superuser_is_always_false`: assert `user.is_superuser is False` for every code path (loaded, created, modified attempt to set True).
  - `test_has_perm_does_not_short_circuit`: create a user, give them no groups, assert `user.has_perm('anything')` returns `False`.
- `DmisUserManagerTests`:
  - `test_create_user_calls_tenant_first_helper`: mock the helper and assert it's invoked with the expected arguments.
  - `test_create_user_requires_tenant`: assert `create_user` raises `ImproperlyConfigured` if no `tenant_id`/`tenant_code` is provided.
  - `test_create_superuser_assigns_system_administrator_role`: mock the role-assignment SQL and assert it runs.

### 6. Migration `backend/accounts/migrations/0001_initial.py`

Use `migrations.SeparateDatabaseAndState` so the migration registers `DmisUser` in Django's state graph **without** issuing any DDL against the `"user"` table:

```python
state_operations=[
    migrations.CreateModel(
        name='DmisUser',
        fields=[...],  # mirror DmisUser fields
        options={'db_table': '"user"', 'managed': False, ...},
    ),
]
database_operations=[]
```

The migration must depend on `('auth', '0012_alter_user_first_name_max_length')` so swappable-model resolution works.

### 7. AUTH_USER_MODEL swap pre-flight

Before declaring done, run from `backend/`:

```bash
python manage.py check
python manage.py migrate --check
```

If Django flags the swap (typical messages: `User model X does not inherit from AbstractBaseUser...`, `Swappable model already pointed at...`, or migration-graph errors referencing existing apps' `auth.User` references), **stop and ask** — do not force-fake migrations or alter existing migration files in `api/`, `operations/`, `replenishment/`, or `masterdata/` to change their `auth.User` references. The fix may require a new "compat" migration in those apps; that is out of scope for Phase 1.

### 8. Capture parity snapshots

Phase 2 will assert against these. Generate them now while `LegacyCompatAuthentication` still produces a `Principal`.

- Identify canonical fixture users by reading existing fixtures:
  - `LOCAL_AUTH_HARNESS_USERNAMES` defaults in `backend/dmis_api/settings.py:1035-1039`
  - Dev role mappings in `backend/api/rbac.py:93-192`
  - `backend/operations/management/commands/seed_relief_management_frontend_test_users.py`
- Pick at minimum: one `SYSTEM_ADMINISTRATOR`, one `LOGISTICS_OFFICER`, one `EXECUTIVE`, one `AGENCY_DISTRIBUTOR`.
- For each fixture user, hit `/api/v1/auth/whoami/` via the **current** `LegacyCompatAuthentication` flow (use a Django test client with the `X-DMIS-Local-User` header pointed at that user). Save the JSON response under `backend/api/tests_auth_parity_fixtures/whoami_<username>.json`. Pretty-print with `indent=2, sort_keys=True` for stable diffs.
- Generation script lives at `backend/api/management/commands/capture_auth_parity_snapshots.py` (new). Idempotent. Print a summary of files written.
- Brief 2 will run the same command (or the same code path) and assert byte-for-byte identical JSON.

### 9. `createsuperuser` decision

Document in the PR summary how `manage.py createsuperuser` should be invoked given that a tenant is required. Pick **one** of:

- **(a)** Override `createsuperuser` to require `--tenant-code` and validate against `tenant.tenant_code`.
- **(b)** Provide a separate management command `create_admin_user` that wraps `create_user` with `is_active=True` and `SYSTEM_ADMINISTRATOR` role assignment.

Implement the chosen option and explain why.

---

## Constraints (HARD — do not violate)

- Auth-layer edits are limited to adapter/local-harness compatibility in `backend/api/authentication.py`; do not modify `backend/api/rbac.py`, `backend/api/permissions.py`, `backend/api/tenancy.py`, or auth-related views unless a later phase brief explicitly requires it.
- The allowed view edit in this phase is `backend/masterdata/views.py` for the structural refactor described in **Task 0** (move exceptions and verification function into `iam_data_access.py`; replace the inline atomic block at lines 1566–1583 with a call to `create_user_with_primary_tenant`; update the call site at line 337). **Zero behavior change.** If any existing masterdata test fails after this edit, the refactor is wrong — fix the refactor, do not modify the test.
- **Do not** add or alter columns on the `"user"` table. No DDL.
- **Do not** create rows in `auth_user`. The W002 check (`backend/api/checks.py:134-184`) must keep passing.
- **Do not** touch tenancy code or the `tenant_user` schema.
- **Do not** change frontend code.
- `is_superuser = False` always, locked behind a property, with a test that asserts it.
- Follow `backend/AGENTS.md` rules on input validation and SQL parameterization. Use `%s` placeholders only. Quote table/column names via `connection.ops.quote_name()` if needed.
- Match coding standards in `.claude/CLAUDE.md` (function-based views; raw SQL via `data_access.py`; no `.format()` or f-strings in SQL).
- Supply-chain hold: do **not** run `npm install`, do **not** introduce or update `axios`. Backend-only work; this should not arise.

## Verification gates (must pass before declaring done)

Run from `backend/`:

```bash
python manage.py check
python manage.py migrate --check
python manage.py test accounts --verbosity=2
python manage.py test --verbosity=2
```

All four must pass. The full test suite must show zero new failures vs. the pre-Phase-1 baseline.

---

## Deliverable

A 250-word summary at the end of your reply containing:

1. **Files created and files modified**, with line counts.
2. **Design decisions** for tricky areas:
   - `password` ↔ `password_hash` mapping
   - `is_staff` derivation
   - The **`is_superuser=False` lock pattern you chose** (and why it does not break `PermissionsMixin.has_perm`)
   - The `db_table = '"user"'` quoting decision
3. **Tenant-first creation entry point**: which helper you called, where, and why.
4. **`createsuperuser` decision** (option a or b) and rationale.
5. **Parity snapshot files written**: list filenames.
6. **Test commands run and their results** (e.g., "ran `python manage.py test accounts --verbosity=2` → 6 passed; ran `python manage.py test --verbosity=2` → N passed, 0 failed; `python manage.py check` clean; `python manage.py migrate --check` clean").
7. **Any deviation from this brief**, with justification.
8. **Any open questions** for Claude that should be resolved before Phase 2.

If you encounter ambiguity, **stop and report the question** instead of guessing. This work is medium-risk and Claude will architecture-review it on return before approving Phase 2.
