# DMIS Angular Reading Map

A canonical pointer-set the skill loads on demand. Verified 2026-04-25.
This file is duplicated across the three frontend skills; the pre-commit drift hook keeps the copies identical.

## Layout
- `frontend/src/app/core/` — auth bootstrap and HTTP cross-cutting
  - `app-access.guard.ts` — route guard `appAccessGuard`
  - `app-access.service.ts` — access-key resolution
  - `auth-session.service.ts` — session bootstrap
  - `dev-user.interceptor.ts` — adds `X-DMIS-Local-User` only when running in `local-harness`
  - `dev-user.interceptor.disabled.ts` — production-side disabling variant
  - `http-interceptors.ts` — interceptor registration
- `frontend/src/app/layout/` — sidenav shell
- `frontend/src/app/shared/dmis-step-tracker/` — only shared component today (`.component.ts/html/scss/spec.ts`)
- Feature modules (lazy-loaded): `replenishment/`, `operations/`, `master-data/`

## Routing
- Lazy `loadChildren` for every feature route.
- Every protected route has `appAccessGuard` registered with an `accessKey` in `data`.
- Backend is the security boundary; the guard exists for UX continuity only.

## Auth UX
- `devUserInterceptor` adds `X-DMIS-Local-User` only when `DMIS_RUNTIME_ENV=local-harness`.
- Backend rejects legacy `X-Dev-User` requests entirely.
- Tokens come from Keycloak in production; never stored in `environment.ts`.

## API proxy
- `frontend/proxy.conf.cjs` — forwards `/api`, `/relief-requests`, `/eligibility`, `/packaging`, `/dashboard`, `/static` to `http://localhost:8001` in dev.
- `npm start` uses `ng serve` against this proxy.

## Design-system surface (canonical)
- **`frontend/src/lib/prompts/generation.tsx`** — the canonical DMIS component-generation prompt. Encodes the design system (warm-neutral palette, status tones, typography, spacing, radius), coding patterns, and quality standards for any new Angular component. Local-only reference (not shipped in the production bundle). Cite this file when generating, reviewing, or refactoring components; do not duplicate or drift its tokens.
- `frontend/src/styles.scss` — global tokens and theme entry that align with `generation.tsx`.
- `frontend/src/app/operations/shared/operations-theme.scss` — module-specific theme.
- `frontend/src/app/shared/dmis-step-tracker/dmis-step-tracker.component.scss` — shared component styling.
- ESLint frontend config — selector prefix rules (`app-*` element, `dmis-*` element; `app*` / `dmis*` attribute).
- Angular Material is integrated through `styles.scss`.

If `generation.tsx` is absent, do not pull UI rules from `main` by default. Use `frontend/src/styles.scss` in the current worktree for runtime tokens, consult mirrored skill docs in `../docs` or the current branch for prompt/component rules, and allow cross-branch retrieval only when an explicit approved doc or flag authorizes it.

## Build / test commands
- `npm start` — `ng serve` with proxy
- `npm run build` — production build by default
- `npm run lint` — `ng lint` with `angular-eslint`
- `npm test -- --watch=false` — single Karma + Jasmine run

## Component standards
- Standalone components (Angular 21+).
- Signals preferred over RxJS where appropriate.
- `OnPush` change detection where possible.
- Reactive forms for inputs.
- Status colors must have a text or icon backup (accessibility).
- Loading uses skeletons, not spinners.

## Mobile / field
- Cards stack vertically on small screens.
- Tables become card lists on small screens.
- "Kemar field-first" usability test: would a logistics manager use this on a phone in a hurricane response?

## Schematics defaults
- SCSS by default.
- `app-` / `dmis-` prefixes for components (kebab-case element).
- `app` / `dmis` prefixes for directives (camelCase attribute).

## What NOT to do
- Do NOT bind `innerHTML` to user-provided content.
- Do NOT bypass the service layer with direct `HttpClient` use in components.
- Do NOT add a route without `appAccessGuard` + `accessKey`.
- Do NOT hardcode tokens or feature flags into `environment.ts` (frontend bundle is public).
- Do NOT duplicate or drift the design tokens defined in `frontend/src/lib/prompts/generation.tsx` (warm-neutral palette, status tones, typography, spacing, radius). Cite the file rather than reinventing values.
- Do NOT regress to NgModules where standalone components are the convention.
