# DMIS Frontend Controls Checklist

Required controls for any frontend change. Sources: `frontend/AGENTS.md`, `.claude/CLAUDE.md`, `docs/security/SECURITY_ARCHITECTURE.md`.

## Form validation (mirror backend column limits)
- Every text `<input>` and `<textarea>`: `maxlength` attribute matching the backend DB column.
- Every text `FormControl`: `Validators.maxLength(n)` matching the same value.
- Required: `Validators.required` on the FormControl + `required` template attribute.
- Numeric: `Validators.min/max` + HTML `type="number"` with `min`/`max`.
- Trim user text with `.trim()` before submit (reason, notes, comments).
- No `innerHTML` bindings of user-provided content; use `{{ … }}` interpolation (Angular auto-escapes).

## Auth UX (do NOT replace backend authorization)
- Frontend guard (`appAccessGuard`) controls route visibility, not security.
- Hidden buttons are not security; the backend must independently enforce.
- Dev-user behavior must NEVER be normalized into production paths.
- Read-only access patterns must show clearly (disabled state, not just hidden controls).

## Accessibility (WCAG 2.2 AA baseline)
- Semantic HTML; `<button>` for actions, `<a>` for navigation.
- Keyboard navigation works on every interactive control.
- Focus order is logical; focus management on modal open/close.
- Form inputs have visible labels, not placeholder-only.
- Color is not the sole channel for status; pair with text or icon.
- Status / error messaging is announced to assistive tech (`role="status"`, `role="alert"` as appropriate).
- Template accessibility ESLint rules are review blockers, not warnings.

## Performance
- `trackBy` on dynamic lists.
- No expensive method calls inside templates.
- Loading skeleton, not spinner.
- Lazy routes for every feature module.
- `OnPush` change detection where possible.
- Avoid repeated API calls triggered by lifecycle/UI mistakes.

## ESLint selectors
- Components: `app-*` or `dmis-*` (kebab-case, element type).
- Directives: `app*` or `dmis*` (camelCase, attribute type).

## Mobile (Kemar field-first)
- Cards stack vertically on small screens.
- Tables become card lists on small screens.
- Tap targets ≥ 44 px.
- Forms remain usable on small screens with assistive keyboards.

## Frontend security
- No secrets in `environment.ts` (frontend bundle is public).
- No tokens in `localStorage` / `sessionStorage`; tokens come from Keycloak at runtime.
- Validate query and route params before using them.
- Avoid direct DOM manipulation; let Angular manage rendering.
- No `bypassSecurityTrust*` calls without an explicit comment justifying the source of the trusted content.

## Data freshness (must surface to the user)
- HIGH: < 2h
- MEDIUM: 2–6h
- LOW: > 6h

Every dashboard tile or status card should make its last-refresh state visible — Kemar must never act on stale data without knowing it is stale.

## Non-negotiable from CLAUDE.md
- No auto-actions: system recommends, humans approve.
- Audit everything: all changes logged with user, timestamp, reason (frontend surfaces this; backend persists it).
- Strict inbound: only count DISPATCHED transfers, IN-TRANSIT donations, SHIPPED procurement.
- Mobile-friendly: cards stack vertically, tables become card lists on small screens.
