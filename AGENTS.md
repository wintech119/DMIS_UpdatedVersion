# DMIS Agent Guide (Codex-Optimized)

## Purpose
This file gives repository-specific guidance for coding agents working in this project.
It should complement system/developer instructions, not conflict with them.

## Product Context
- DMIS (Disaster Management Information System) for Jamaica ODPEM.
- EP-02 supply replenishment focuses on stock health, needs-list workflows, and replenishment planning.
- Primary operational user: logistics manager in field conditions (mobile-first reliability matters).

## Active Architecture
- Preferred stack: Django + Angular.
- Legacy stack: Flask (obsolescing).
- Default expectation: implement new behavior in Django/Angular only unless the user explicitly asks for Flask changes.

## Tech Stack
- Frontend: Angular 21+, Angular Material, TypeScript
- Backend: Django 4.2 LTS + Django REST Framework
- Database: PostgreSQL
- Auth: Keycloak OIDC (environment-dependent)

## Agent Operating Rules (Repo-Specific)
- Make targeted changes only in files relevant to the task.
- Do not refactor unrelated areas during feature/bug work.
- Preserve existing uncommitted user changes.
- Validate changes with lightweight checks when feasible:
- Backend: `manage.py check` (and focused tests when touched)
- Frontend: `npm run build` or targeted lint/test as applicable
- For schema-affecting requests, verify against live DB metadata (`information_schema`) when available.
- Keep backward-compatibility in API contracts unless user requests breaking changes.

## Safety and Data Handling
- Never commit secrets or local env files.
- Treat dumps/test data as disposable unless explicitly designated canonical.
- Keep human-in-the-loop behavior for operational decisions (recommendations are not auto-actions).

## Domain Rules to Preserve

### Event Phase Windows
| Phase | Demand Window | Planning Window |
|---|---|---|
| SURGE | 6 hours | 72 hours |
| STABILIZED | 72 hours | 168 hours |
| BASELINE | 720 hours | 720 hours |

### Core Formulas
```text
Burn Rate        = Fulfilled Qty / Demand Window (hours)
Time-to-Stockout = Available Stock / Burn Rate
Required Qty     = Burn Rate * Planning Window * 1.25
Gap              = Required Qty - (Available + Confirmed Inbound)
```

### Guardrails
- Auditability: approvals/overrides/changes should be traceable.
- Data freshness should be visible in UI where decisions are made.
- Inbound counting must follow approved operational statuses only.
- Reports/exports should avoid beneficiary PII.

## Practical Commands
```powershell
# Backend
cd backend
..\.venv\Scripts\python.exe manage.py check
..\.venv\Scripts\python.exe manage.py test

# Frontend
cd frontend
npm.cmd run -s build
npm.cmd run -s lint
```

## Notes for Future Updates
- Keep this file concise and conflict-free with top-level agent instructions.
- Prefer stable, verified project facts (README / current codebase) over historical assumptions.
