# Architecture-Review Handoff

The DMIS architecture-review gate is mandatory by `backend/AGENTS.md:31` and `frontend/AGENTS.md:24` for low-medium and higher risk work. This file is duplicated across all six analysis/implementation/review skills and kept in lockstep by the pre-commit drift hook.

## Risk rubric

Score the change with the rubric in `.agents/skills/system-architecture-review/SKILL.md`. Score each axis 0–2 and sum.

| Axis | 0 | 1 | 2 |
|---|---|---|---|
| Blast radius | One screen / endpoint, isolated | One module | Cross-module or platform-wide |
| Data sensitivity | Reference / public | Operational, tenant-scoped | Beneficiary, audit-relevant, or PII |
| Authority change | None | Touches role gating or workflow guard | Adds/removes a permission or transition |
| Reversibility | Pure refactor | Schema-additive | Schema-destructive or contract-breaking |
| External surface | Internal only | Internal API contract change | Public/partner contract or new third-party |
| Operational impact | None | Affects logging, metrics, runtime config | Affects deploy topology, HA, backup, rollback |

- 0–3: **Low** — skip unless an explicit trigger applies.
- 4–6: **Low-Medium** — abbreviated workflow (steps 1–3 of the skill).
- 7–9: **Medium** — full workflow.
- 10+: **High** — full workflow plus mandatory ADR (new or update).
- **Any single axis = 2 → run regardless of total.**

## Always-on triggers (run regardless of score)

From `backend/AGENTS.md` and `frontend/AGENTS.md`:
- Auth, RBAC, tenancy, impersonation, tokens, sessions, route guards
- Secure settings, headers, cookies, CORS, secrets, uploads, input validation, IDOR, rate limits
- Raw SQL, Redis, caching, queues, workers, object storage, external integrations
- Workflow logic for approvals, dispatch, receipt, exports, audit evidence, durable artifacts
- Deployment, readiness, liveness, observability, backup, restore, rollback, HA posture
- API contract changes (`/api/v1/**`), persistence strategy, architecture docs
- Frontend route structure, lazy module boundaries, shared component reuse, design-system surfaces
- Dependency / supply-chain changes
- Anything that could expand Flask dependence (Flask is decommissioned; reintroduction is misalignment)

## Two checkpoints (mandatory)

1. **Before finalizing the plan** — design must be architecturally aligned before code is written.
2. **Before final output** — re-run the gate after implementation; if `Misaligned`, do not declare done.

## How to invoke

Use the Skill tool: `Skill skill="system-architecture-review"`. When invoking from another skill, return only the architecture verdict and findings; do not duplicate the host skill's output structure.

If the result is `Conditionally Aligned`, complete the required changes (each named with the gate that proves closure: test, ADR, hook, evidence) before declaring the work done.

If the result is `Misaligned`, the work is not complete. Resolve and re-review.

## Low-risk exemptions

Skip only when the change is clearly:
- Typo-only documentation edits
- Comment-only edits
- Isolated styling adjustments with no architecture, behavior, or security impact
- Isolated tests that do not alter behavior, contracts, or controls
- Dependency updates that are non-security and have a documented compatibility matrix

If there is any reasonable doubt, perform the review.
