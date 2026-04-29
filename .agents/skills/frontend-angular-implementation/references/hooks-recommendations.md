# Recommended Harness Hooks

Hooks the user can land via the `update-config` skill in `.claude/settings.json`. **This skill does not modify settings.json directly.** This file is duplicated across all six skills; the pre-commit drift hook keeps the copies identical.

| Hook | Path / event | Purpose |
|---|---|---|
| `PreToolUse` on Write/Edit | `docs/adr/**`, `docs/security/**`, `frontend/src/lib/prompts/generation.ts`, `frontend/src/styles.scss`, `frontend/src/app/shared/**`, `backend/dmis_api/settings.py` | Confirm before editing canonical architecture, security, settings, or design-system files. `generation.ts` is the canonical DMIS component-generation prompt (warm-neutral palette, status tones, typography, spacing); a change there ripples into every future Angular component. |
| `PostToolUse` on Edit | `backend/**.py` → `python manage.py check` | Catch settings/ORM regressions early |
| `PostToolUse` on Edit | `frontend/**/*.{ts,html,scss}` → `npm run lint` | Catch ESLint and template-accessibility regressions |
| `PreCommit` | diff `references/dmis-django-reading-map.md` across the 3 backend skills and `references/dmis-angular-reading-map.md` across the 3 frontend skills; fail on divergence | Prevent the duplicated reference content from drifting |
| `PreCommit` | `diff -r .agents/skills/<name>/ .claude/skills/<name>/` for the six skills (`backend-django-*`, `frontend-angular-*`); fail on divergence | Keep the canonical source-of-truth (`.agents/skills/`) in lockstep with the harness-discoverable mirror (`.claude/skills/`). The harness loads only from `.claude/skills/`, but `.agents/skills/` is what AGENTS.md, CLAUDE.md, and `system-architecture-review` reference; both must be identical |
| `Stop` hook | fast architecture-lint pass: grep for forbidden imports, dev-only auth flags, `innerHTML` on user content, hard-coded design tokens | Block declaring done before alignment check |
| `PreCompact` | snapshot pending architecture findings | Preserve findings across context compactions |

## How to apply

1. Run `Skill skill="update-config"`.
2. Ask it to add the relevant hook entries to `.claude/settings.json`.
3. Verify with `cat .claude/settings.json` (or via Read).

## Why hooks not skills

Hooks run automatically on harness events (tool use, commit, compact, stop). Skills run only when invoked. Use hooks for invariants the agent might forget (run `manage.py check` after Python edits); use skills for workflows the agent must reason about (architecture review, requirements-to-design).
