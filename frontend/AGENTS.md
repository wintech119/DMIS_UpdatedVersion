# Frontend Project Instructions

## Purpose
- Before implementing, consult the approved feature docs in `../docs`.
- This project owns screens, forms, components, accessibility, frontend validation, and frontend tests.
- Do not change backend contract assumptions without flagging the mismatch.

## Scope
- Angular routes, screens, components, forms, services, and view models live here.
- Frontend behavior should align with approved requirements, API contracts, and UX rules from `../docs`.

## Working Rules
- Preserve backend contract assumptions unless an approved contract update exists.
- Surface data freshness, status, and audit-relevant context where decisions are made.
- Favor accessible forms, clear validation states, and mobile-reliable interactions for field use.
- Add or update focused frontend tests when behavior changes.
- If the UI exposes a workflow or rule not documented in `../docs`, flag it rather than silently normalizing it.

## Mandatory Architecture Review
- For medium- and high-risk frontend work, use the shared architecture reviewer at `../.agents/skills/system-architecture-review/SKILL.md` before finalizing a plan.
- Run the same architecture review again before final output when implementation work touches architecture-sensitive frontend areas.
- Treat `../docs/adr/system_application_architecture.md` as the primary architecture source of truth.
- Treat `../docs/security/SECURITY_ARCHITECTURE.md`, `../docs/security/THREAT_MODEL.md`, and `../docs/security/CONTROLS_MATRIX.md` as the primary security and control references.
- Treat `../docs/implementation/production_readiness_checklist.md` as the release-gating reference.
- Treat `../docs/implementation/production_hardening_and_flask_retirement_strategy.md` as supporting execution guidance, not the main architecture baseline.

### Mandatory frontend review triggers
- auth bootstrap, route guards, role and permission handling, token or session handling, and dev-user behavior
- localStorage or browser-held workflow state that could affect security, resilience, or multi-user correctness
- HTTP interceptors, API platform services, error-state handling, correlation, or retry behavior
- large dataset rendering, client-heavy transformations, or performance-sensitive route behavior
- workflow-critical UI for approvals, dispatch, receipt, exports, audit evidence, or artifact handling
- any work that could expand Flask dependence or weaken the Angular + Django target architecture

### Low-risk exemptions
- typo-only documentation edits
- comment-only changes
- isolated styling adjustments with no architecture, behavior, or security impact
- isolated tests that do not alter behavior or contracts

### Frontend architecture expectations
- Do not normalize dev-user or impersonation behavior into production paths.
- Keep backend authorization authoritative; frontend checks remain UX-only.
- Prefer centralized auth, HTTP, and failure-handling patterns over screen-specific exceptions.
- Call out any deviation from the target Angular + Django + OIDC + Redis + async-worker architecture.
- If the architecture review returns `Misaligned`, do not treat the work as complete.
## Regression Guardrails
- Treat the current frontend codebase as the authoritative baseline for component formats, templates, structure, interaction patterns, and test shape.
- Before changing a component or adding a related one, inspect the current nearby implementation and extend the existing pattern instead of rewriting it toward an older commit version.
- If a newer local frontend pattern already exists, do not reintroduce a superseded template, structure, or legacy implementation unless the approved docs explicitly require that change.


