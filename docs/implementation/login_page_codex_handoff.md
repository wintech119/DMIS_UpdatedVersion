# Login Page Keycloak Readiness — Codex Handoff

This document is the canonical source for **five Codex implementation briefs** that, taken together, complete the DMIS Login Page for Keycloak OIDC readiness. Each brief is self-contained — Codex does not need any conversation context to execute it.

## Context

**Why**: The Angular SPA already implements OIDC Authorization Code + PKCE end-to-end (`AuthSessionService`, `/auth/login` + `/auth/callback` + `/access-denied` pages, `sessionStorage` token persistence, Keycloak `end_session_endpoint` logout, OIDC discovery via `.well-known/openid-configuration`). The dev team will set Keycloak realm/client configuration in GitLab CI/CD and a deployed `auth-config.json` artifact before launch. This handoff closes the remaining architectural gaps and ships the dev-team config contract.

**Outcome**:
1. `/replenishment` is no longer publicly navigable — `appAccessMatchGuard` + `accessKey: 'replenishment.dashboard'` redirects unauthenticated users to `/auth/login` (closes Threat-Model E.1; satisfies `frontend/AGENTS.md` "appAccessGuard plus an accessKey is mandatory on every protected route").
2. The login + callback + access-denied surfaces apply the **Civic Editorial** visual concept (Accessible & Ethical + Swiss Modernism 2.0) using only existing `--color-*` tokens in `frontend/src/styles.scss`. No new hex literals, no AI-aesthetic gradients, no spinners.
3. `backend/.env.example` documents the Keycloak env-var contract.
4. New dev-team handoff doc `docs/implementation/login_page_keycloak_handoff.md` tells operators how to template `auth-config.json` per environment and threat-models the `sessionStorage` token persistence.
5. ADR-lite paragraph appended to `docs/adr/system_application_architecture.md` records the three architectural choices: public-client + PKCE (no client secret in bundle), runtime config artifact (one build, many environments), `sessionStorage` token storage with documented sunset path.
6. Tests assert the new guard binding and the new accessibility contract on the auth surface.

**Scope confirmation**:
- Token storage **stays in `sessionStorage`** per user decision. BFF httpOnly-cookie redesign is **out of scope**.
- Visual concept applies the Civic Editorial spec from Section "Visual Concept" below — sourced from the `ui-ux-pro-max` skill.
- Local-harness developer experience is preserved unchanged. Everything keyed off `DMIS_LOCAL_AUTH_HARNESS_BUILD === true` continues to work the same way.
- No new dependencies. No `npm install` / `npm ci` (supply-chain hold per `.claude/CLAUDE.md`). Do not introduce `axios` or anything sourced from it.

**Pipeline-safety note**: `frontend/public/auth-config.json` stays committed with `enabled: false` placeholder values. Per-environment values are injected at deploy time by the dev team's pipeline (documented in the new dev-team handoff). Do **not** put real Keycloak issuer URLs, client IDs, or audiences in the committed file.

## Required prior reading (do this first, in order)

Codex must load these files into working memory before executing any brief. Treat them as the design and architectural ground truth.

1. **`frontend/src/lib/prompts/generation.ts`** — the canonical DMIS component-generation prompt. Read these sections at minimum:
   - **§1 Visual Identity — "Notion for disaster ops"** (~L20–66): warm-neutral palette, NEVER cold grays; status tones with **both** colour AND text/icon backup; system-font typography stack; spacing/radius tokens; interactions including `prefers-reduced-motion` mandate.
   - **§2 Component Architecture** (~L68–103): `standalone: true`, `ChangeDetectionStrategy.OnPush`, signals-based reactivity preferred over RxJS, `aria-label` on every section/landmark, `focus-visible` styling on every interactive element, **skeleton loaders preferred over spinners**.
   - **§3 Styling Rules** (~L105–145): use CSS custom properties from `frontend/src/styles.scss`; class naming `ops-{block}__{element}--{modifier}` BEM-like (the auth pages use `auth-{element}` — keep that local convention); responsive breakpoints; SCSS rules.
   - **§6 Accessibility (Non-negotiable)** (~L1747–1756): `aria-label` on sections, radio-group filters, `prefers-reduced-motion` reduces transitions to none.
   - **§7 Quality Checklist** (~L1758–1786): standalone, OnPush, signals, no spinners, no BehaviorSubject for component state.
   - **§8 Anti-patterns to Avoid** (~L1788+): no `BehaviorSubject` for local component state, no spinners, no `ViewChild` for DOM queries (prefer template variables and signals).

2. **`frontend/src/styles.scss`** L1–90 — the canonical token sheet. Every colour, font-size, weight, tracking, line-height, radius, page-padding, and focus-ring used in this work MUST be a `var(--*)` reference from this file. Do not introduce new hex literals.

3. **`frontend/src/app/auth/auth-pages.component.ts`** (entire file) — the existing login/callback/access-denied components you will restyle. Note: `signals`, `computed`, OnPush, and the `localAuthHarnessClientEnabled()` branch are already correct and must be preserved.

4. **`frontend/src/app/core/auth-session.service.ts`** — the OIDC machine. **Do NOT modify this file.** PKCE, state CSRF, callback handling, token endpoint exchange, `whoami` hydration, and `end_session_endpoint` logout are already correct.

5. **`frontend/src/app/core/app-access.guard.ts`** — the existing guard pattern you will rebind for `/replenishment`. Use `appAccessMatchGuard` (CanMatchFn) — do **not** create a new sibling guard.

6. **`frontend/src/app/core/app-access.service.ts:194-196`** — confirms `canAccessNavKey('replenishment.dashboard')` returns `true` for any authenticated user, so the guard binding is purely an auth check, not a permission narrowing.

7. **`frontend/src/app/core/app-access.guard.spec.ts`** — the test pattern to mirror for the new replenishment guard spec.

8. **`docs/security/SECURITY_ARCHITECTURE.md`** §"Identity and Access" + §"Canonical Input Validation and Output Safety Standard". Backend authorization remains authoritative; frontend checks are UX only.

9. **`docs/security/THREAT_MODEL.md`** S.1 (dev-user impersonation), I.1 (cross-tenant guards), E.1 (privilege drift across route boundaries). The work in this handoff closes E.1 and reinforces S.1 mitigations.

## Visual Concept — "Civic Editorial" (apply in Brief #4)

A fusion of *Accessible & Ethical* (best-for: government, healthcare, education, public) + *Swiss Modernism 2.0* (rational grid, mathematical spacing, single accent, high contrast). Reads as "official Jamaican government utility, calmly competent" — not a SaaS marketing page, not a glassmorphic toy.

**Anti-patterns to avoid (named explicitly)**: ornate design, low contrast, motion effects on the entry state, AI purple/pink gradients, multi-stop teal-to-cyan gradient pills, scale-on-hover transforms, glassmorphism, spinner loaders.

**Palette layering** (use only existing `--color-*` tokens from `frontend/src/styles.scss`):

| Surface | Token composition |
| --- | --- |
| Outer page background | `var(--color-surface-muted)` `#F7F6F3` flat. Replace the existing radial+linear gradient. |
| Page top-edge accent | 4 px `var(--color-accent)` hairline rule across the top of the viewport via `:host::before`. |
| Card surface | `var(--color-surface)` `#ffffff`; 1 px solid `var(--color-border)`; `var(--radius-card)` 8 px; box-shadow `0 1px 2px rgba(55, 53, 47, 0.04)` only. |
| Card top stripe | 3 px `var(--color-accent)` inset bar via `.auth-card::before`. |
| Primary CTA | **Solid** `var(--color-accent)` (replace gradient). White text. 8 px radius (replace `999px` pill). |
| Local-harness warning | `var(--color-bg-warning)` background, `var(--color-warning-text)` text, 1 px `var(--color-border)` border. |
| Eyebrow | `var(--color-accent)`. |
| Focus halo | `var(--color-focus-ring)`, 3 px ring + 0 px offset via `box-shadow` (so it survives the solid fill). |

**Typography** — system stack only (`var(--dmis-font-sans)`):

| Role | Size | Weight | Tracking | Line-height |
| --- | --- | --- | --- | --- |
| Eyebrow | `var(--text-xs)` | 700 | `var(--tracking-wide)` | 1.25 |
| H1 | `clamp(1.875rem, 5.5vw, 2.25rem)` | 700 | `-0.01em` | 1.1 |
| Body | `var(--text-base)` | 400 | normal | `var(--leading-relaxed)` |
| Hint | `var(--text-sm)` | 400 | normal | 1.5 |
| CTA label | `var(--text-md)` | 600 | `var(--tracking-tight)` | 1 |

**Layout**: card `width: min(100%, 26rem)`; padding `2rem 1.75rem`; status messaging in a single `role="status" aria-live="polite"` paragraph between H1 and CTA. Page uses `min-height: 100dvh` (with `100vh` fallback) — `100vh` alone has the mobile browser-chrome problem.

**Interactions** (no scale-transforms, no spinners):
- Idle → solid `--color-accent` fill.
- Hover → `color-mix(in srgb, var(--color-accent) 88%, black)` (color-only, 200 ms `transition: background-color`).
- Focus-visible → `box-shadow: 0 0 0 3px var(--color-focus-ring); outline: none;`.
- Pressed → `transform: translateY(1px)` + `color-mix(in srgb, var(--color-accent) 80%, black)`.
- Loading → **skeleton bar replaces the CTA label** (12 px tall, 60 % button width, `background: color-mix(in srgb, white 25%, var(--color-accent))`, `border-radius: 4px`, with a `prefers-reduced-motion: no-preference` shimmer keyframe). Button keeps its dimensions. Set `[attr.aria-busy]` to the `working()` / `localHarnessWorking()` signal value.
- Error → status paragraph shows the failure message with a 1 px-left border in `var(--color-critical)` driven by a `data-tone` attribute. CTA stays enabled so the user can retry.
- Disabled → `opacity: 0.55; cursor: not-allowed`.

**Mobile spec at 360 × 640**: 4 px page accent stripe → 64 px breathing space → card (full width minus 24 px each side) → end of viewport. Card contents top-to-bottom: 32 × 32 brand-mark slot → 12 px gap → eyebrow → 8 px → H1 → 16 px → status copy → 24 px → CTA (full card width minus inner padding) → 16 px → return-URL hint or local-harness block. CTA 44 px tall × 100 % wide. Local-harness switcher buttons inherit `min-height: 44px` from `styles.scss:328-341`.

**Brand-mark slot**: 32 × 32 placeholder above the eyebrow. `aspect-ratio: 1; background: var(--color-surface-muted); border-radius: 4px;`. If `frontend/public/dmis-mark.svg` exists later, swap to an `<img>` element — no reflow required.

**Three deliberate rejections** (so the result does not read as AI-generated):
1. No multi-stop gradient on the CTA.
2. No 1.5 rem-radius rounded card (reduced to 8 px / `--radius-card`).
3. No spinner on loading (skeleton-bar replacement only).

## Execution order (sequential, incremental)

Backend doc-only briefs first, then frontend code, then verification + ADR. Each brief becomes its own commit so the verifier can cherry-pick.

1. **Brief #1** — `backend/.env.example` Keycloak block
2. **Brief #2** — dev-team handoff doc `docs/implementation/login_page_keycloak_handoff.md`
3. **Brief #3** — frontend route guard binding for `/replenishment` + spec
4. **Brief #4** — apply Civic Editorial visual concept to `frontend/src/app/auth/auth-pages.component.ts` + spec
5. **Brief #5** — ADR-lite append to `docs/adr/system_application_architecture.md` and verification (`npm run lint`, `npm run build`, `npm test -- --watch=false`, `python manage.py check`, manual 360 px smoke)

After all five land, run the post-implementation `system-architecture-review` skill against the diff. Verdict must reach `Aligned`.

---

## Codex Brief #1 — Backend `.env.example` Keycloak block

**Goal**: Make the Keycloak env-var contract visible to the dev team in the canonical example file.

**Files to edit**:
- `backend/.env.example`

**Patterns to mirror (read first)**:
- `backend/.env.example:74-83` — the existing "Non-local auth baseline" comment block. Keep its style (commented-out `KEY=value` lines with leading `#`) and stay adjacent to it.
- `backend/dmis_api/settings.py:975-995` — the actual env-var read sites; confirms key names and defaults.
- `.gitlab-ci.yml:39-56` — placeholder values used by the `auth_posture_validation` CI stage.

**Required changes**:

In `backend/.env.example`, immediately AFTER the existing `# LOCAL_AUTH_HARNESS_ENABLED=0` line (~L78) and BEFORE the `# Local-only auth bypass` block (~L79), insert:

```env
# Keycloak OIDC configuration (required when AUTH_ENABLED=1).
# Replace the example values below with your real Keycloak realm endpoints.
# AUTH_ISSUER=https://idp.example/realms/dmis
# AUTH_AUDIENCE=dmis-web
# AUTH_JWKS_URL=https://idp.example/realms/dmis/protocol/openid-connect/certs
# AUTH_USER_ID_CLAIM=sub
# AUTH_USERNAME_CLAIM=preferred_username
# AUTH_ALGORITHMS=RS256
# AUTH_USE_DB_RBAC=1
# See docs/implementation/login_page_keycloak_handoff.md for full setup.
```

**Constraints**:
- All lines stay commented out — `.env.example` ships placeholder values only.
- Do NOT modify any other section of the file.
- Do NOT change the order of existing variables.
- Keep the leading `#` and exact spelling of every key — they must match the names read by `backend/dmis_api/settings.py`.

**Acceptance**:
1. Diff touches only `backend/.env.example`.
2. New block sits between the existing "Non-local auth baseline" comment and "Local-only auth bypass" comment.
3. Each new line begins with `#` (commented out).
4. All key names match `backend/dmis_api/settings.py` env reads exactly.

**Reporting**: short diff (lines added), confirmation that no other section was touched.

---

## Codex Brief #2 — Dev-team handoff doc

**Goal**: Create the contract document for the dev team / operators covering Keycloak realm setup, the env-var contract, the `auth-config.json` deploy-time templating contract, and the `sessionStorage` token-storage threat model.

**Files to create**:
- `docs/implementation/login_page_keycloak_handoff.md`

**Patterns to mirror (read first)**:
- `docs/implementation/master_data_production_readiness_codex_handoff.md` — overall structure, tone, "Why / Outcome / Scope confirmation / Pipeline-safety note" header, file:line references, code blocks for exact syntax.
- `frontend/src/app/core/auth-session.service.ts:173-484` — the OIDC flow being documented (PKCE, state CSRF, code exchange against `token_endpoint`, `whoami` hydration, `end_session_endpoint` logout).
- `frontend/public/auth-config.json` — the runtime artifact whose deploy-time replacement is being documented.

**Required structure (sections, in order)**:

1. **Purpose & Audience** — one paragraph. Audience: DMIS dev team, deployment operators, Keycloak realm administrator. Not Codex, not end users.

2. **Already implemented in the SPA (do not re-build)** — a short audit table listing: `/auth/login`, `/auth/callback`, `/access-denied` routes; `AuthSessionService` PKCE + state CSRF + code exchange + whoami hydration + end-session logout; topbar logout control; `appAccessMatchGuard`-based route protection; sessionStorage token persistence with expiry skew; OIDC discovery via `.well-known/openid-configuration`. Cite the file:line refs from required-reading section above.

3. **Keycloak realm setup checklist** — explicit, copy-pasteable for a Keycloak admin:
   - Create realm `dmis` (or whatever name the deployment uses; it is environment-driven).
   - Create client `dmis-web`.
   - **Client mode: PUBLIC + PKCE S256**. (No client authentication. SPA holds no secret.) State the rationale: the SPA is a public bundle and any embedded secret would leak.
   - Valid Redirect URIs: `https://<host>/auth/callback`. Add one per environment (shared-dev, staging, production). No wildcards in production.
   - Valid Post-Logout Redirect URIs: `https://<host>/auth/login`.
   - Web Origins: `https://<host>`.
   - Required scopes: `openid`, `profile`, `email`. (Default scope set is acceptable.)
   - Required claims: `sub` (user_id), `preferred_username`, optionally `realm_access.roles` only if `AUTH_USE_DB_RBAC=0`. With DB RBAC `=1` (recommended), roles come from the DB and the JWT claim is unused.
   - Audience mapping: ensure `aud` claim contains `dmis-web` so the backend `AUTH_AUDIENCE=dmis-web` validation passes.
   - Token lifetimes: state Keycloak defaults are acceptable; tokens are short-lived and the SPA reauthenticates on expiry.

4. **Backend env contract** — table of every var the backend reads, with example values, with a column marking which are CI/CD-secret-worthy vs plain config:
   - `AUTH_ENABLED=1` (config) — must be 1 for shared-dev / staging / production. CI-validated.
   - `AUTH_ISSUER` (config) — `https://<keycloak-host>/realms/<realm>`.
   - `AUTH_AUDIENCE` (config) — `dmis-web`.
   - `AUTH_JWKS_URL` (config) — `<issuer>/protocol/openid-connect/certs`.
   - `AUTH_USER_ID_CLAIM=sub` (config).
   - `AUTH_USERNAME_CLAIM=preferred_username` (config).
   - `AUTH_ALGORITHMS=RS256` (config).
   - `AUTH_USE_DB_RBAC=1` (config) — recommended; pulls roles/permissions from the DB rather than the JWT claim.
   - `DEV_AUTH_ENABLED=0`, `LOCAL_AUTH_HARNESS_ENABLED=0`, `DJANGO_DEBUG=0` for non-local environments. The `auth_posture_validation` CI stage in `.gitlab-ci.yml` already enforces these.

5. **Frontend deploy contract for `auth-config.json`** — the SPA reads `frontend/public/auth-config.json` at runtime to discover Keycloak. The committed file ships with `enabled: false` and empty placeholders. Per environment, replace it before serving the SPA bundle. Document THREE options and recommend ONE:
   - **Option A — k8s ConfigMap mount (recommended for k8s deployments)**: ConfigMap with the JSON, mounted at `/usr/share/nginx/html/auth-config.json` inside the SPA container.
   - **Option B — Init-container envsubst at startup**: include a sample envsubst template that takes `AUTH_ISSUER`, `AUTH_CLIENT_ID`, `AUTH_AUDIENCE` from env and writes the JSON to the SPA static-assets volume before nginx starts.
   - **Option C — GitLab CI generate-and-publish**: a CI stage emits the per-environment JSON as an artifact picked up by the deploy step.
   - State: option A is the recommendation when the deployment target is Kubernetes; option B otherwise. Provide a sample JSON shape:
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
   - Warn: do NOT commit a real-issuer JSON to the repo. Real values live in the deployment artefact only.

6. **Token-storage threat model (sessionStorage)** — explicit and honest:
   - **Statement of the choice**: the SPA stores the access token in `sessionStorage`, not an httpOnly cookie. Quote `frontend/src/app/core/auth-session.service.ts:486-496` as the persistence implementation.
   - **Mitigations in place**: PKCE eliminates code-interception attacks; tokens are scoped to the browser tab (sessionStorage clears on tab close); the production bundle ships zero third-party scripts (verified by Angular build budget at `frontend/angular.json:61-71`); short Keycloak token lifetimes (Keycloak default) limit the window of an exfiltrated token; the `dev-user.interceptor` is fileReplaced out of the production bundle (see `frontend/angular.json:48-60`) so dev impersonation cannot reach prod (Threat-Model S.1 mitigation).
   - **Residual risk**: an XSS in any DMIS surface elevates to full session takeover for the duration of the token lifetime. A strict Content Security Policy is the highest-leverage future control.
   - **Sunset path**: a backend BFF `/api/v1/auth/login-callback` endpoint that holds the Keycloak client secret (confidential client), exchanges the code server-side, and returns an httpOnly Secure SameSite=Lax session cookie. Documented as out of scope for this thread; tracked as a future ADR.

7. **Verification checklist** — what the dev team / operators run after configuring their environment:
   - `cd frontend && npm run lint` — clean.
   - `cd frontend && npm run build` — production config; clean within existing 1.5 MB / 2 MB initial-bundle budget.
   - Visit `/replenishment/dashboard` while signed-out → redirect to `/auth/login?reason=unauthenticated&returnUrl=%2Freplenishment%2Fdashboard`.
   - Click "Sign in with OIDC" → browser navigates to `${AUTH_ISSUER}/protocol/openid-connect/auth?response_type=code&client_id=dmis-web&redirect_uri=...&scope=openid+profile+email&state=<random>&code_challenge=<base64url>&code_challenge_method=S256`.
   - Successful callback returns to `returnUrl` with the topbar "Sign out" button visible.
   - Logout from topbar → browser navigates to `${end_session_endpoint}?client_id=dmis-web&post_logout_redirect_uri=...&id_token_hint=...`.
   - Manual 360 px viewport smoke: no horizontal scroll on `/auth/login` or `/auth/callback` (use Chromium device toolbar at iPhone SE / 360 × 667).

8. **Out of scope** (explicit list):
   - Keycloak realm provisioning automation, secret rotation, Keycloak role-mapping logic, custom Keycloak login-screen theme.
   - MFA enrolment UI, password reset, account creation (Keycloak owns these flows).
   - Login-attempt rate limiting on the DMIS backend (Keycloak handles brute-force on its own login surface).
   - Backend BFF httpOnly-cookie redesign (sunset path noted; not in this thread).

**Constraints**:
- Do NOT include real Keycloak issuer URLs, client IDs, audiences, or any secret values in the doc. All examples must use `idp.example` / `<host>` / placeholder shape.
- Do NOT re-document the OIDC flow steps; cite `auth-session.service.ts` line ranges instead.
- Do NOT introduce new deploy options outside A/B/C above.

**Acceptance**:
1. New file at `docs/implementation/login_page_keycloak_handoff.md`.
2. All eight sections present in order.
3. Every code block uses fenced markdown.
4. No real secrets / real domains anywhere in the doc.
5. Cross-references to `auth-session.service.ts`, `angular.json`, `.gitlab-ci.yml`, `master_data_production_readiness_codex_handoff.md` use repo-relative paths and click through.

**Reporting**: word count, list of cross-references made, confirmation that no real values were committed.

---

## Codex Brief #3 — Route guard binding for `/replenishment` + spec

**Goal**: Apply `appAccessMatchGuard` + `accessKey: 'replenishment.dashboard'` to the `/replenishment` route. Add a guard spec mirroring the `master.any` / `operations.dashboard` pattern.

**Files to edit**:
- `frontend/src/app/app.routes.ts`
- `frontend/src/app/core/app-access.guard.spec.ts`

**Patterns to mirror (read first)**:
- `frontend/src/app/app.routes.ts:26-37` — existing `master-data` and `operations` guard bindings with `canMatch` + `data: { accessKey: ... }`.
- `frontend/src/app/core/app-access.guard.ts:22-62` — `appAccessMatchGuard` (`CanMatchFn`) and the `evaluateProtectedRouteAccess` helper that produces the `/auth/login?reason=...&returnUrl=...` redirect tree.
- `frontend/src/app/core/app-access.service.ts:188-247` — `canAccessNavKey` switch; case `'replenishment.dashboard'` returns `true` unconditionally (line 195) — confirms this binding is purely auth, not permission.
- `frontend/src/app/core/app-access.guard.spec.ts` — TestBed + Jasmine spy pattern, async guard via `firstValueFrom`, mock `AuthSessionService` / `Router` / `AppAccessService`. Mirror its describe-block style.

**Required changes**:

1. In `frontend/src/app/app.routes.ts`, modify the `replenishment` route (lines 22–25) to add the guard and access-key:
   ```ts
   {
     path: 'replenishment',
     canMatch: [appAccessMatchGuard],
     data: { accessKey: 'replenishment.dashboard' },
     loadChildren: () => import('./replenishment/replenishment.routes').then(m => m.REPLENISHMENT_ROUTES),
   },
   ```
   `appAccessMatchGuard` is already imported at the top of the file. No new import needed.

2. In `frontend/src/app/core/app-access.guard.spec.ts`, add a new test case asserting `appAccessMatchGuard` accepts `replenishment.dashboard` for an authenticated user. Mirror the existing TestBed pattern.

**Constraints**:
- Do NOT create a new sibling guard (`authenticatedGuard.ts`) — `appAccessMatchGuard` is the conventional pattern. Sibling creation is forbidden by `frontend/AGENTS.md` Regression Guardrails.
- Do NOT change `app-access.service.ts` or any other production code.
- Do NOT add new permissions to `replenishment.dashboard` access-key resolution.
- Test setup must use the existing helper pattern; do not introduce a new mocking framework.

**Acceptance**:
1. `app.routes.ts` diff is exactly the addition of `canMatch: [appAccessMatchGuard]` and `data: { accessKey: 'replenishment.dashboard' }` on the `replenishment` route.
2. New test case passes.
3. `cd frontend && npm test -- --watch=false` is clean (other guard tests still pass).
4. `cd frontend && npm run lint` is clean.

**Reporting**: diff per file (lines added / modified), test-run output (PASS counts), confirmation that no other guard / route was touched.

---

## Codex Brief #4 — Apply Civic Editorial visual concept

**Goal**: Restyle `DmisAuthLoginPageComponent`, `DmisAuthCallbackPageComponent`, and `DmisAccessDeniedPageComponent` to the Civic Editorial concept documented in the "Visual Concept" section above. Component logic, signals, computed values, and method signatures stay unchanged.

**Files to edit**:
- `frontend/src/app/auth/auth-pages.component.ts`
- `frontend/src/app/auth/auth-pages.component.spec.ts` (create)

**Patterns to mirror (read first)**:
- `frontend/src/lib/prompts/generation.ts` §1 (palette, status tones, typography), §2 (component architecture: standalone, OnPush, signals, aria-label, focus-visible, skeleton-not-spinner), §3 (CSS custom properties, BEM-like class naming).
- `frontend/src/styles.scss:1-90` — the canonical `--color-*`, `--text-*`, `--weight-*`, `--leading-*`, `--tracking-*`, `--radius-*`, `--page-padding`, `--color-focus-ring` token sheet. Every value used in this brief must be a `var(--*)` reference from this file.
- `frontend/src/styles.scss:293-310` — global `:focus-visible` outline rule. Note the gradient-pill problem the box-shadow technique solves.
- `frontend/src/styles.scss:325-356` — global mobile rules (44 px touch targets, etc.).
- `frontend/src/app/auth/auth-pages.component.ts` (entire file) — preserve every signal, computed, method signature, and `localAuthHarnessClientEnabled()` branch.

**Required changes** (see "Visual Concept" section above for the full token / state / layout spec): replace gradient page background with flat `--color-surface-muted`; reduce card radius from 1.5 rem to `--radius-card` (8 px) and width from 34 rem to 26 rem; replace gradient pill CTA with solid `--color-accent` 8 px-radius button; replace all hard-coded hex with token references; add 4 px page accent stripe via `:host::before`; add 3 px card accent stripe via `.auth-card::before`; wrap status copy in `role="status" aria-live="polite"` with `data-tone` attribute; replace spinner concept with skeleton bar inside CTA on `working()`; add 32×32 brand-mark slot above the eyebrow; switch `min-height: 100vh` → `100dvh`.

Add `auth-pages.component.spec.ts` asserting:
1. `role="status"` element exists in the rendered login template.
2. While `working()` returns `true`, the auth-primary button has `aria-busy="true"` and contains a `.auth-primary__skeleton` element.
3. No `<mat-progress-spinner>` or `class*="spin"` element renders anywhere on the auth pages.

**Constraints**:
- Do NOT modify `auth-session.service.ts`, `app-access.guard.ts`, `app-access.service.ts`, or any non-auth file.
- Do NOT change a single signal, computed, method signature, or constructor logic in `auth-pages.component.ts`. Only `template`, `styles`, and the addition of a `state` computed are allowed.
- Do NOT add new external dependencies or imports.
- Do NOT introduce new `--color-*` tokens. If a colour you need is not in `frontend/src/styles.scss`, stop and report — do not invent a token.
- Do NOT add a spinner. Use the skeleton pattern.
- Preserve the existing `dmis-local-harness-switcher` component reference and its enclosing `.auth-local-harness` block.

**Acceptance**:
1. `cd frontend && npm run lint` clean.
2. `cd frontend && npm run build` clean (production config).
3. `cd frontend && npm test -- --watch=false` clean (new auth-pages spec passes).
4. Manual smoke at 360 × 640 in Chromium device toolbar: no horizontal scroll, top accent stripe visible, card 3 px inset stripe, CTA solid teal not gradient, no spinner, focus ring visible on tab to CTA.
5. No new hex literals; every colour comes from a `var(--color-*)` token.

**Reporting**: SCSS line counts (added / removed), template diff summary, confirmation no signal / method was modified, lint+build+test output.

---

## Codex Brief #5 — ADR-lite append + verification

**Goal**: Append a one-paragraph ADR-lite note to the architecture doc capturing the three decisions (public-client + PKCE, runtime config artifact, `sessionStorage` token storage), then run all verification gates.

**Files to edit**:
- `docs/adr/system_application_architecture.md`

**Required changes**:

1. Append to `docs/adr/system_application_architecture.md` at the end of `## Architecture Decision Rules` (after the "Misalignment indicators" subsection, before `## Architecture Review Triggers`):
   ```markdown
   ### Recorded Decisions

   #### Login Page Keycloak Integration (2026-04-27)

   The Angular SPA implements OIDC Authorization Code with PKCE S256 against Keycloak as a **public client** (no client secret in the bundle). Client configuration loads from a runtime artifact `frontend/public/auth-config.json` that the deployment pipeline replaces per environment, rather than from build-time `define` constants — chosen to allow one build to serve all environments. Access tokens persist in `sessionStorage` with documented mitigations (PKCE eliminates code interception, dev-user interceptor is fileReplaced from the production bundle, no third-party scripts in bundle, short Keycloak token lifetimes); a backend BFF httpOnly-cookie redesign is recorded as the sunset path. See `docs/implementation/login_page_keycloak_handoff.md` for the operator contract and `docs/implementation/login_page_codex_handoff.md` for the implementation handoff that landed this work.
   ```

2. Run verification:
   - `cd frontend && npm run lint`
   - `cd frontend && npm run build` (production config — default)
   - `cd frontend && npm test -- --watch=false`
   - `cd backend && python manage.py check`
   - Manual 360 × 640 smoke (Chromium device toolbar) — document in reporting.
   - Re-run the `system-architecture-review` skill against the diff. Expect verdict `Aligned`.

**Constraints**:
- Do NOT replace or rewrite existing ADR sections — append only.
- Do NOT skip any verification step.
- Do NOT run `npm install` or `npm ci` (supply-chain hold).

**Acceptance**:
1. `docs/adr/system_application_architecture.md` has the new ADR-lite paragraph in `## Architecture Decision Rules`. No other change.
2. All four verification commands pass.
3. Manual smoke confirms 360 px layout integrity.
4. Architecture review verdict is `Aligned`.

**Reporting**: ADR-lite diff (~6 lines), verification command outputs (PASS counts, build size, lint warnings), architecture-review verdict full output.

---

## Reused utilities and patterns

Codex MUST find and reuse, not invent:

| Utility / pattern | Where it lives | Used by |
| --- | --- | --- |
| `appAccessMatchGuard` (`CanMatchFn`) | `frontend/src/app/core/app-access.guard.ts:22-28` | Brief #3 |
| `evaluateProtectedRouteAccess` helper | `frontend/src/app/core/app-access.guard.ts:30-62` | Brief #3 (read for understanding only) |
| `canAccessNavKey` switch | `frontend/src/app/core/app-access.service.ts:188-247` | Brief #3 (mirror existing access-key cases) |
| `AuthSessionService` (PKCE, state CSRF, code exchange, whoami, logout) | `frontend/src/app/core/auth-session.service.ts` | Brief #4 (read for understanding only — DO NOT MODIFY) |
| `localAuthHarnessClientEnabled()` | `frontend/src/app/core/dev-user.interceptor.ts:38-42` | Brief #4 (preserve existing branch logic) |
| `.sr-only` utility | `frontend/src/styles.scss:313-323` | Brief #4 (reuse for screen-reader-only labels) |
| Global `:focus-visible` outline | `frontend/src/styles.scss:293-310` | Brief #4 (the box-shadow technique on solid-fill buttons supplements this) |
| Global mobile rules (44 px touch targets) | `frontend/src/styles.scss:325-356` | Brief #4 (CTA inherits) |
| `DMIS_GENERATION_PROMPT` design system | `frontend/src/lib/prompts/generation.ts` | All briefs (cite §1, §2, §3, §6, §7, §8) |
| Existing guard spec pattern | `frontend/src/app/core/app-access.guard.spec.ts` | Brief #3 |
| Existing handoff-doc shape | `docs/implementation/master_data_production_readiness_codex_handoff.md` | Brief #2 |

## Critical files reference

| File | Status in this work |
| --- | --- |
| `frontend/src/app/app.routes.ts` | modified (Brief #3) |
| `frontend/src/app/auth/auth-pages.component.ts` | modified (Brief #4) |
| `frontend/src/app/auth/auth-pages.component.spec.ts` | created (Brief #4) |
| `frontend/src/app/core/app-access.guard.spec.ts` | extended (Brief #3) |
| `backend/.env.example` | modified (Brief #1) |
| `docs/implementation/login_page_keycloak_handoff.md` | created (Brief #2) |
| `docs/implementation/login_page_codex_handoff.md` | this document — created at the start of implementation |
| `docs/adr/system_application_architecture.md` | appended (Brief #5) |
| `frontend/src/app/core/auth-session.service.ts` | read-only — do not modify |
| `frontend/src/app/core/app-access.guard.ts` | read-only — do not modify |
| `frontend/src/app/core/app-access.service.ts` | read-only — do not modify |
| `frontend/src/app/core/http-interceptors.ts` | read-only — do not modify |
| `frontend/src/app/core/dev-user.interceptor.ts` | read-only — do not modify |
| `frontend/angular.json` | read-only — do not modify (existing `define` + `fileReplacements` are correct) |
| `frontend/public/auth-config.json` | read-only — keep `enabled: false` placeholder (deploy-time replacement only) |
| `frontend/src/styles.scss` | read-only — token sheet is ground truth |
| `frontend/src/lib/prompts/generation.ts` | read-only — design-system spec |

## Out of scope (do NOT do)

- Backend BFF login-callback endpoint / httpOnly cookie redesign.
- Keycloak realm provisioning automation.
- New backend rate-limiting on auth endpoints (Keycloak handles brute-force on its own surface).
- New `define` constants in `frontend/angular.json` for Keycloak values (runtime artifact is the chosen path).
- A new `authenticatedGuard` sibling — `appAccessMatchGuard` is the conventional pattern.
- Sidenav-footer logout — topbar logout is sufficient.
- Custom Keycloak login-screen theme.
- MFA / password-reset / account-creation UI (Keycloak owns).
- New brand assets (mark slot is reserved but empty — drop a real SVG into `frontend/public/dmis-mark.svg` later if ODPEM provides one).
- Any change that introduces `axios` or any artifact sourced from it.
