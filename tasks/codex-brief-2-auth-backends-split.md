# Codex Brief 2 — Phase 2: Authentication Backends Split

> **Source-of-truth plan**: `tasks/django-auth-adapter-plan.md` (read first for full context).
> **Pre-requisites**: Brief 1 (Phase 1) merged and verified by Claude.
> **Risk**: Medium. **Reversible**: Yes (revert `LegacyCompatAuthentication` and remove `AUTHENTICATION_BACKENDS`).
> **Working directory**: `C:\Users\wbowe\OneDrive\Desktop\project\DMIS_UpdatedVersion\.claude\worktrees\funny-goldberg-8bdebc`

---

## Goal

Replace the body of `LegacyCompatAuthentication.authenticate()` with delegation to two new Django authentication backends:

- `KeycloakOidcBackend` for non-local environments (preserves existing JWT/JWKS validation).
- `LocalHarnessBackend` for the local-harness `X-DMIS-Local-User` flow.

After this phase, `request.user` is a real `accounts.DmisUser` instance (not a `Principal` dataclass) but exposes the same attributes (`user_id`, `username`, `roles`, `permissions`, `is_authenticated`) so all 109 existing call sites continue to work.

The local harness header behavior, allowlist semantics, runtime-env validation, and legacy `X-Dev-User` rejection are preserved exactly.

---

## Repository context (read before writing code)

- Phase 1 delivered:
  - `accounts.DmisUser` model bound to the existing `"user"` table.
  - `DmisUserManager` calling the tenant-first creation helper.
  - Parity snapshots under `backend/api/tests_auth_parity_fixtures/whoami_<username>.json`.
  - `is_superuser` locked to `False`.
- Existing auth surface to refactor:
  - `backend/api/authentication.py:283-358` — `LegacyCompatAuthentication.authenticate()` (the body you are replacing).
  - `backend/api/authentication.py:42-78` — `_verify_jwt_with_jwks()` (move into `KeycloakOidcBackend` or call from it).
  - `backend/api/authentication.py:98-156` — `_ensure_user_row()` (replaced by `User.objects.update_or_create` inside `KeycloakOidcBackend`).
  - `backend/api/authentication.py:179-185` — `_enforce_dev_override_header_policy()` (legacy `X-Dev-User` rejection — must remain in the dispatcher).
  - `backend/api/authentication.py:198-243` — `_resolve_dev_override_principal()` (becomes `LocalHarnessBackend.get_user()` flow).
  - `backend/api/authentication.py:158-172` — `local_auth_harness_enabled()` and `_configured_local_auth_harness_users()` (allowlist gate — preserve exactly).
- DRF still needs an `Authentication` class (DRF runs the auth class first, then per-view). Keep `LegacyCompatAuthentication` as a **dispatcher** that delegates to the right Django backend rather than ripping it out.
- `request.user` is consumed at ~109 sites as `Principal`. After Phase 2 it is a `DmisUser` with `Principal`-shape properties.

---

## Concrete tasks

### 1. `backend/accounts/backends.py` (new)

```python
class KeycloakOidcBackend(BaseBackend):
    """Validates Keycloak/OIDC JWT and returns the matching DmisUser."""

    def authenticate(self, request, jwt: str | None = None):
        # Reproduce existing _verify_jwt_with_jwks() + claim extraction.
        # On success: User.objects.update_or_create(user_id=..., defaults={...})
        # Emit the same audit log lines as today (event names + payloads).
        ...

    def get_user(self, user_id):
        return DmisUser.objects.filter(pk=user_id).first()


class LocalHarnessBackend(ModelBackend):
    """Username/password against `"user"` table. Used by Django admin, shell, and the harness flow."""
    # Override get_user only if needed; otherwise inherit ModelBackend behavior.
```

- `KeycloakOidcBackend.authenticate` extracts JWT from `Authorization: Bearer ...` header (or accepts a `jwt=` kwarg for unit-testing convenience).
- Replace `_ensure_user_row()` with `User.objects.update_or_create(user_id=..., defaults={'username': ..., 'email': ..., 'full_name': ...})` populated from JWT claims. Emit identical audit log lines.

### 2. Add `Principal`-shape attributes to `DmisUser`

In `backend/accounts/models.py`:

- `@property def roles(self) -> list[str]`: resolved by calling existing `resolve_roles_and_permissions(request, self)` from `backend/api/rbac.py`. Cache on the instance for the request lifecycle. Use a `_rbac_resolved` private flag and `_rbac_roles` / `_rbac_permissions` private attributes to avoid double resolution. The request object isn't always available on the instance — pass `request=None` and let `resolve_roles_and_permissions` handle it (it caches on `request._rbac_cache` when a request is present).
- `@property def permissions(self) -> list[str]`: same pattern.
- `is_authenticated` is already provided by `AbstractBaseUser`. Verify it returns `True` for authenticated `DmisUser` instances; do not override.

### 3. Refactor `backend/api/authentication.py`

- `LegacyCompatAuthentication.authenticate()` becomes a dispatcher:
  1. Run `_enforce_dev_override_header_policy(request)` (legacy `X-Dev-User` rejection — unchanged).
  2. If `local_auth_harness_enabled()` is true and `X-DMIS-Local-User` is set: validate against allowlist (existing logic) → call `LocalHarnessBackend.get_user_by_harness_header(...)` (new helper) → call `login(request, user, backend='accounts.backends.LocalHarnessBackend')` → return `(user, None)` for DRF.
  3. Else if `DEV_AUTH_ENABLED` (without harness): preserve existing dev-auth behavior but return a `DmisUser` populated from the dev fixture.
  4. Else if `AUTH_ENABLED`: extract JWT, call `KeycloakOidcBackend.authenticate(request, jwt=...)`, return `(user, None)`.
  5. Else: return `None` (DRF treats request as anonymous).
- Replace `Principal(...)` constructions with returns of `DmisUser` instances.
- Keep the `Principal` dataclass importable but mark it deprecated with a `DeprecationWarning` in its `__post_init__` (so test sites that still construct it explicitly can be migrated incrementally without breaking).
- `_ensure_user_row` becomes a thin wrapper that delegates to `KeycloakOidcBackend`'s update_or_create, OR is removed entirely if no other callers remain.

### 4. Settings update

Add to `backend/dmis_api/settings.py` near the auth block:

```python
AUTHENTICATION_BACKENDS = [
    'accounts.backends.KeycloakOidcBackend',
    'accounts.backends.LocalHarnessBackend',
    'django.contrib.auth.backends.ModelBackend',  # admin / shell fallback
]
```

Place it after the existing auth settings. Do not touch `AUTH_ENABLED`, `DEV_AUTH_ENABLED`, `LOCAL_AUTH_HARNESS_ENABLED`, runtime-env validation, or any other auth setting.

### 5. Tests

- **`backend/accounts/tests_backends.py`** (new): unit-test each backend in isolation.
  - `KeycloakOidcBackendTests`: valid JWT → returns DmisUser; invalid JWT → returns None and emits the expected audit log; `update_or_create` populates fields correctly.
  - `LocalHarnessBackendTests`: valid username/password → returns DmisUser; invalid → returns None.
- **`backend/api/tests_auth_parity.py`** (new): for each canonical fixture user (loaded from `backend/api/tests_auth_parity_fixtures/whoami_<username>.json`):
  - Hit `/api/v1/auth/whoami/` with the harness header pointed at that user via the new flow.
  - Assert the response JSON is byte-for-byte identical to the snapshot.
  - Use `json.dumps(actual, indent=2, sort_keys=True)` and compare against the file content directly.
- **Local harness flow tests** (extend existing if present):
  - `X-DMIS-Local-User` allowlisted user → 200 with same payload as snapshot.
  - `X-DMIS-Local-User` non-allowlisted → 403.
  - Legacy `X-Dev-User` → 401 with `auth.rejected_legacy_dev_header` log emission.
- Update existing tests that construct `Principal(...)` directly to either keep doing so (Principal still importable) or assert the new `DmisUser` return type where DRF auth runs.

---

## Constraints (HARD — do not violate)

- **Do not** change any RBAC table schema, permission codes, role codes, or `resolve_roles_and_permissions` logic (`backend/api/rbac.py`).
- **Do not** touch tenancy resolution (`backend/api/tenancy.py`).
- **Do not** populate `auth_user` rows.
- Runtime-env validation in `backend/dmis_api/settings.py:324-372` must still trip on misconfiguration.
- Preserve `LOCAL_AUTH_HARNESS_USERNAMES` allowlist semantics exactly.
- **Preserve every existing auth audit emission**. Every `_log_auth_warning(...)` call (legacy header rejection, allowlist rejection, JWKS validation failure) must keep emitting the same event name and payload from the new backends. Successful auth events that emit logs today must keep emitting them. [NIST CSF DE.AE-3; ASVS V7.1]
- **Apply login throttling to `LocalHarnessBackend`**. The 5-per-15-min login limit defined in `backend/AGENTS.md` and `docs/security/SECURITY_ARCHITECTURE.md` must cover the new backend. If login throttling is currently implemented in middleware, ensure the harness path goes through it; if it is implemented in a decorator, wire it up. [ASVS V2.2.1]
- Follow `backend/AGENTS.md` for auth changes — this is medium-risk work; document the architecture review checkpoint outcome in the PR description.
- Supply-chain hold: do not run `npm install`, do not introduce or update `axios`.

## Verification gates (must pass before declaring done)

Run from `backend/`:

```bash
python manage.py check
python manage.py test accounts --verbosity=2
python manage.py test api.tests_auth_parity --verbosity=2
python manage.py test --verbosity=2
```

All must pass. Specifically:
- All Phase 1 parity snapshots must match byte-for-byte.
- W002 system check still passes.
- Runtime-env validation still trips on misconfiguration.
- IDOR negative tests still pass.

---

## Deliverable

A 250-word summary at the end of your reply containing:

1. **Files created and files modified**, with line counts.
2. **Dispatcher refactor**: how `LegacyCompatAuthentication.authenticate()` now delegates, and what stayed inside it (legacy header rejection, allowlist gate).
3. **Parity-test results**: every snapshot matched / list any deltas (must be zero in production paths).
4. **Audit-log preservation evidence**: list every `_log_auth_warning` event name, where it now fires from, and a test that asserts each emission.
5. **Throttle wiring**: how `LocalHarnessBackend` participates in the 5-per-15-min login limit; show the test.
6. **Test commands run and their results**.
7. **Any deviation from this brief**, with justification.
8. **Any open questions** for Claude that should be resolved before Phase 3.

If you encounter ambiguity, **stop and report the question** instead of guessing. This work is medium-risk and Claude will architecture-review it on return before approving Phase 3.
