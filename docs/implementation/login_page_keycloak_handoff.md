# Login Page Keycloak Integration — Dev-Team Handoff

## 1. Purpose & Audience

This document is the contract between the DMIS application team and the dev-team / deployment operators / Keycloak realm administrator who will configure and run the login page in shared-dev, staging, and production environments. **Audience is operators, not Codex.** The frontend OIDC flow is already implemented; this document tells you what to set, where to set it, and how to verify the result. For the implementation handoff that landed this work, see [docs/implementation/login_page_codex_handoff.md](login_page_codex_handoff.md).

## 2. Already implemented in the SPA (do not re-build)

The following are wired in the current branch tip and require no further code work:

| Surface | Implementation reference |
| --- | --- |
| `/auth/login` route + page (signed-out entry point) | [frontend/src/app/auth/auth-pages.component.ts](../../frontend/src/app/auth/auth-pages.component.ts) (`DmisAuthLoginPageComponent`) |
| `/auth/callback` route + page (handles `?code=...&state=...` return) | same file (`DmisAuthCallbackPageComponent`) |
| `/access-denied` route + page (authenticated but unauthorised) | same file (`DmisAccessDeniedPageComponent`) |
| OIDC Authorization Code + PKCE S256 redirect | [frontend/src/app/core/auth-session.service.ts:173-207](../../frontend/src/app/core/auth-session.service.ts) |
| OIDC `state` CSRF check on callback | [auth-session.service.ts:415-435](../../frontend/src/app/core/auth-session.service.ts) |
| Code → token exchange against discovered `token_endpoint` | [auth-session.service.ts:437-470](../../frontend/src/app/core/auth-session.service.ts) |
| OIDC discovery via `.well-known/openid-configuration` | [auth-session.service.ts:399-413](../../frontend/src/app/core/auth-session.service.ts) |
| `whoami` hydration after successful exchange | [auth-session.service.ts:340-367](../../frontend/src/app/core/auth-session.service.ts) |
| Token persistence in `sessionStorage` with expiry skew | [auth-session.service.ts:486-496](../../frontend/src/app/core/auth-session.service.ts) |
| Logout via Keycloak `end_session_endpoint` | [auth-session.service.ts:209-240](../../frontend/src/app/core/auth-session.service.ts) |
| Topbar "Sign out" control | [frontend/src/app/app.component.html:24-26](../../frontend/src/app/app.component.html) |
| Route protection via `appAccessMatchGuard` for replenishment, master-data, operations | [frontend/src/app/app.routes.ts](../../frontend/src/app/app.routes.ts), [frontend/src/app/core/app-access.guard.ts](../../frontend/src/app/core/app-access.guard.ts) |
| Open-redirect protection on `returnUrl` | [app-access.guard.ts:96-117](../../frontend/src/app/core/app-access.guard.ts) (`normalizeRequestedUrlString`) |
| Local-harness developer experience preserved (`DMIS_LOCAL_AUTH_HARNESS_BUILD === true`) | [frontend/angular.json:48-78](../../frontend/angular.json), [frontend/src/app/core/dev-user.interceptor.ts](../../frontend/src/app/core/dev-user.interceptor.ts) |
| Dev-impersonation excluded from production bundle (`fileReplacements`) | [frontend/angular.json:48-60](../../frontend/angular.json) |
| Backend `KeycloakJWTAuthentication` (JWKS validation, claim extraction) | [backend/api/authentication.py](../../backend/api/authentication.py) |
| Backend `auth_posture_validation` CI gate (rejects `DEV_AUTH_ENABLED=1` outside local-harness) | [.gitlab-ci.yml:24-120](../../.gitlab-ci.yml) |

**You do not need to touch any of these files.** Configure Keycloak and the env vars below, drop a real `auth-config.json` at deploy time, and the SPA will work.

## 3. Keycloak realm setup checklist

The Keycloak admin executes the following. Use a different realm or client per environment if your operations team prefers per-env isolation.

**Realm**
- Create a realm. Recommended name: `dmis`. The realm name is environment-driven; whatever you choose, the value goes into `AUTH_ISSUER` as `https://<keycloak-host>/realms/<realm-name>`.

**Client**
- Create client `dmis-web` inside the realm.
- **Client mode: Public + PKCE S256.** Set "Client authentication" to **OFF** (no client authentication). Set "Standard flow" to ON. Disable "Direct access grants" unless you have a separate use for them.
- **Rationale**: the SPA is a public bundle. Any client secret embedded in the JS would be readable by every user. PKCE S256 replaces the secret as the proof-of-possession mechanism for the code exchange. If you ever need a confidential client (e.g. a future backend BFF), create a separate client; do not flip `dmis-web` to confidential.
- Advanced settings → "Proof Key for Code Exchange Code Challenge Method" = `S256`.

**Valid Redirect URIs** (one entry per environment; no wildcards in production)
- `https://<host>/auth/callback`

**Valid Post-Logout Redirect URIs**
- `https://<host>/auth/login`

**Web Origins**
- `https://<host>`
- (Set to `+` only if your operations team has reviewed the implications.)

**Required scopes**
- Default scope set: `openid`, `profile`, `email`. The SPA requests `openid profile email` (see [auth-config.json](../../frontend/public/auth-config.json) `scope`).

**Required claims**
- `sub` — used as `user_id` (`AUTH_USER_ID_CLAIM=sub` on the backend).
- `preferred_username` — used as `username` (`AUTH_USERNAME_CLAIM=preferred_username`).
- Audience: include `dmis-web` in the `aud` claim. In Keycloak, configure a "Audience" mapper on the client scope so tokens carry `aud=dmis-web`. The backend validates this against `AUTH_AUDIENCE=dmis-web`.
- `realm_access.roles` is **not** required when `AUTH_USE_DB_RBAC=1` (recommended). Roles and permissions come from the DB tables `role`, `permission`, `user_role`, `role_permission` once the user is identified.

**Token lifetimes**
- Keycloak defaults are acceptable. Tokens are short-lived; the SPA reauthenticates on expiry by redirecting through `/auth/login` again.

**Out of scope here**
- Realm provisioning automation (Terraform/Keycloak CLI is your team's choice).
- MFA enrolment, password reset, account creation — Keycloak owns these flows in its own UI.
- Custom Keycloak login-screen theme — Keycloak realm admin owns that.

## 4. Backend env contract

These env vars are read by [backend/dmis_api/settings.py](../../backend/dmis_api/settings.py) (lines 975–1015) and validated by the `auth_posture_validation` CI stage in [.gitlab-ci.yml](../../.gitlab-ci.yml). All examples are placeholders — replace with real values per environment via your CI/CD secret store.

| Env var | Example | Type | Notes |
| --- | --- | --- | --- |
| `AUTH_ENABLED` | `1` | config | Must be `1` for shared-dev / staging / production. Already CI-validated. |
| `AUTH_ISSUER` | `https://<keycloak-host>/realms/dmis` | config | Source of truth for OIDC discovery. |
| `AUTH_AUDIENCE` | `dmis-web` | config | Must match the `aud` claim Keycloak issues for `dmis-web`. |
| `AUTH_JWKS_URL` | `${AUTH_ISSUER}/protocol/openid-connect/certs` | config | Used by Django's JWKS validator. |
| `AUTH_USER_ID_CLAIM` | `sub` | config | |
| `AUTH_USERNAME_CLAIM` | `preferred_username` | config | |
| `AUTH_ALGORITHMS` | `RS256` | config | Comma-separated allowed algorithms. Keycloak default is RS256. |
| `AUTH_USE_DB_RBAC` | `1` | config | Recommended. Pulls roles/permissions from DB rather than the JWT. |
| `DEV_AUTH_ENABLED` | `0` | config | **Must** be `0` outside `local-harness`. CI-enforced. |
| `LOCAL_AUTH_HARNESS_ENABLED` | `0` | config | **Must** be `0` outside `local-harness`. CI-enforced. |
| `DJANGO_DEBUG` | `0` | config | **Must** be `0` in production. CI-enforced. |

None of the values listed above are secret — they are configuration. The DB credentials (`DB_PASSWORD`), `DJANGO_SECRET_KEY`, and any future Keycloak admin credentials remain CI/CD secret-store-only.

The `auth_posture_validation` CI job already runs each release with these matrix cases:
- shared-dev / staging / production with `AUTH_ENABLED=1`, `DEV_AUTH_ENABLED=0`, `LOCAL_AUTH_HARNESS_ENABLED=0` → **pass**.
- staging with `LOCAL_AUTH_HARNESS_ENABLED=1` → **fail** (rejected by validator).
- production with `DJANGO_DEBUG=1` → **fail** (rejected by validator).

If your environment fails this stage, fix the env config before deploying — do not add bypasses.

## 5. Frontend deploy contract for `auth-config.json`

The SPA reads `frontend/public/auth-config.json` at runtime startup to discover the Keycloak realm. The committed file ships with `enabled: false` placeholder values and **must not** be edited in the repo. Per environment, replace it before serving the SPA bundle.

**Sample shape** (this is what `auth-config.json` must look like at runtime):

```json
{
  "enabled": true,
  "issuer": "https://idp.example.org/realms/dmis",
  "clientId": "dmis-web",
  "scope": "openid profile email",
  "redirectPath": "/auth/callback",
  "postLogoutRedirectPath": "/auth/login",
  "audience": "dmis-web"
}
```

Replace `https://idp.example.org/realms/dmis` and the values under it with your real Keycloak realm endpoint per environment. **Do not commit a real-issuer JSON to the repo.**

Three deployment options, in order of preference:

### Option A — Kubernetes ConfigMap mount (recommended for k8s deployments)

Define a per-environment ConfigMap holding the JSON, then mount it at the SPA static-assets path. Example (for an nginx-based SPA container that serves `frontend/dist/dmis-frontend/`):

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: dmis-auth-config
  namespace: dmis-staging
data:
  auth-config.json: |
    {
      "enabled": true,
      "issuer": "https://idp.example.org/realms/dmis",
      "clientId": "dmis-web",
      "scope": "openid profile email",
      "redirectPath": "/auth/callback",
      "postLogoutRedirectPath": "/auth/login",
      "audience": "dmis-web"
    }
---
# Excerpt of the SPA Deployment spec
spec:
  template:
    spec:
      containers:
      - name: dmis-spa
        image: dmis-frontend:<tag>
        volumeMounts:
        - name: auth-config
          mountPath: /usr/share/nginx/html/auth-config.json
          subPath: auth-config.json
      volumes:
      - name: auth-config
        configMap:
          name: dmis-auth-config
```

The `subPath: auth-config.json` is important — it overlays a single file rather than replacing the whole directory.

### Option B — Init-container envsubst at startup (recommended for non-k8s deployments)

If you are deploying with Docker Compose, Nomad, or another orchestrator that lacks ConfigMap, run an init-container that templates the file from env vars before the SPA container starts:

```bash
#!/bin/sh
# init-container entrypoint: render auth-config.json from env vars
cat > /spa-static/auth-config.json <<EOF
{
  "enabled": true,
  "issuer": "${AUTH_ISSUER}",
  "clientId": "${AUTH_CLIENT_ID:-dmis-web}",
  "scope": "${AUTH_SCOPE:-openid profile email}",
  "redirectPath": "/auth/callback",
  "postLogoutRedirectPath": "/auth/login",
  "audience": "${AUTH_AUDIENCE:-dmis-web}"
}
EOF
```

Mount `/spa-static/` into the SPA container at the static-assets root.

### Option C — GitLab CI generate-and-publish

Emit the JSON as a CI artifact during the deploy stage and let the deploy step copy it onto the SPA host. Mechanically equivalent to Option B but moves the templating into the pipeline rather than the runtime. Acceptable when your deployment target is a static-asset host (Pages, S3, etc.) without an orchestrator.

**Pick one.** Mixing options across environments creates configuration drift.

## 6. Token-storage threat model (`sessionStorage`)

**The choice**: The SPA stores the access token in `sessionStorage` (see [auth-session.service.ts:486-496](../../frontend/src/app/core/auth-session.service.ts)), not in an httpOnly cookie. The token is written after the OIDC code exchange and read by the auth interceptor when attaching `Authorization: Bearer <token>` to `/api/*` requests.

**Mitigations in place**:
- **PKCE S256 eliminates code-interception attacks**: even if the redirect URL is logged or sniffed, the attacker cannot complete the token exchange without the original `code_verifier`, which never leaves the browser tab.
- **Tab-scoped persistence**: `sessionStorage` clears on tab close. There is no cross-tab token leakage.
- **Zero third-party scripts in the production bundle**: enforced by the Angular build budget at [frontend/angular.json:61-71](../../frontend/angular.json) (1.5 MB initial-bundle warning, 30 kB any-component-style warning). Keep it that way.
- **Short Keycloak token lifetimes** (Keycloak defaults are minutes, not hours): an exfiltrated token expires quickly.
- **Dev-user impersonation is fileReplaced out of the production bundle**: see [frontend/angular.json:48-60](../../frontend/angular.json). The `dev-user.interceptor.ts` cannot reach prod — closing Threat-Model S.1.

**Residual risk**: an XSS in any DMIS surface elevates to full session takeover for the duration of the token lifetime. The highest-leverage mitigation is a strict Content Security Policy (`script-src 'self'`, `connect-src 'self' <keycloak-host>`, `frame-ancestors 'none'`, no `unsafe-inline`). Configure the CSP at the edge proxy / NGINX layer per environment.

**Sunset path**: a future backend BFF endpoint `/api/v1/auth/login-callback` can hold the Keycloak client secret (confidential client mode), perform the code exchange server-side, and return an httpOnly Secure SameSite=Lax session cookie. The SPA would stop persisting tokens entirely. This is **out of scope** for this thread and tracked as a future ADR — do not start it without an explicit decision record.

## 7. Verification checklist

After configuring Keycloak, the env vars, and `auth-config.json` per environment, run:

**Frontend build & static checks**

```bash
cd frontend
npm run lint           # must be clean
npm run build          # production config (default); must stay within the 1.5 MB initial-bundle budget
npm test -- --watch=false   # all specs pass
```

(Do not run `npm install` / `npm ci` per the [supply-chain hold](../../.claude/CLAUDE.md). Assume `node_modules` is present.)

**Backend startup checks**

```bash
cd backend
DMIS_RUNTIME_ENV=staging python manage.py check
```

The CI `auth_posture_validation` stage already exercises shared-dev / staging / production / prod-like-local scenarios — see [.gitlab-ci.yml:24-120](../../.gitlab-ci.yml).

**Browser smoke**

1. Visit `/replenishment/dashboard` while signed-out. Expect redirect to `/auth/login?reason=unauthenticated&returnUrl=%2Freplenishment%2Fdashboard`.
2. Click the "Sign in with OIDC" button. Expect navigation to `${AUTH_ISSUER}/protocol/openid-connect/auth?response_type=code&client_id=dmis-web&redirect_uri=...&scope=openid+profile+email&state=<random>&code_challenge=<base64url>&code_challenge_method=S256`.
3. Complete sign-in in Keycloak. Expect return to `/replenishment/dashboard` with the topbar "Sign out" button visible.
4. Click "Sign out". Expect navigation to `${end_session_endpoint}?client_id=dmis-web&post_logout_redirect_uri=...&id_token_hint=...`.
5. Open Chromium dev tools → device toolbar → set viewport to 360 × 667. Visit `/auth/login`. Verify: no horizontal scroll, top accent stripe visible, card centred, CTA full-width and 44 px tall, focus ring visible on Tab key, no spinner anywhere.
6. Manually test the error path: visit `/auth/callback?error=login_required&error_description=test`. Expect the recoverable-error state with a "Return to sign-in" link.

If any step fails, fix configuration before declaring deploy ready. Do not add code bypasses.

## 8. Out of scope

The following are explicitly NOT part of this handoff:
- Keycloak realm provisioning automation, secret rotation policies, role-mapping logic between Keycloak roles and DMIS DB roles.
- Custom Keycloak login-screen theme.
- MFA enrolment UI, password reset, account creation — Keycloak owns these flows.
- Login-attempt rate limiting on the DMIS backend (Keycloak handles brute-force on its own login surface).
- Backend BFF httpOnly-cookie redesign — sunset path noted in §6; not in this thread.
- New brand assets — the brand-mark slot in the login card is reserved but empty. If ODPEM provides an SVG mark, drop it at `frontend/public/dmis-mark.svg` and the slot fills automatically.
