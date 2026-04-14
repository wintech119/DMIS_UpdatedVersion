# DMIS Product and Analysis Workspace

This `docs/` workspace is the Codex project for product definition, analysis, and planning. It is intended to be the source of truth that the backend, frontend, and QA projects consult before making implementation or validation changes.

## Four-project operating model

The repository remains a single working monorepo:

- `docs/`: product, analysis, requirements, decisions, contracts, and plans
- `backend/`: Django APIs, schema, services, auditability, and backend tests
- `frontend/`: Angular UI, forms, accessibility, and frontend tests
- `qa/`: test plans, release readiness, regression coverage, and operational validation

Codex app projects should point at those folders directly rather than trying to split or move code out of the current repository.

## What belongs here

- `features/`: approved or draft feature specifications
- `requirements/`: requirement sets, acceptance criteria, user flows, and rules
- `adr/`: architecture and implementation decisions, including the canonical `system_application_architecture.md` baseline
- `templates/`: reusable authoring templates for specs, plans, contracts, UX rules, and traceability

## Existing documentation areas

This repository already uses `docs/` for several active documentation streams. Keep them in place and reference them where useful:

- `ops/`: operational policies and runbook-oriented notes
- `testing/`: test plans and validation notes
- `security/`: architecture, controls, and threat-model artifacts
- `reviews/`: review findings and analysis notes
- `deploy/`: deployment-related configuration examples
- `migration/`: migration guidance and transition notes
- `fixes/`: targeted issue write-ups
- `attached_assets/`: source reference material imported into the repo

## Working expectations

- Requirements and acceptance criteria should be stable before implementation whenever possible.
- If backend or frontend discovers a requirement gap, document it here before treating it as approved behavior.
- Plans should define milestones and explicit acceptance checkpoints.
- Traceability should link requirements to backend changes, frontend changes, and validation evidence.
