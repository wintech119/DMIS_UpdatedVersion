# Architecture-Review Handoff

The DMIS architecture-review gate is mandatory by `frontend/AGENTS.md#mandatory-architecture-review` and `backend/AGENTS.md#mandatory-architecture-review` for low-medium and higher risk work. The six analysis/implementation/review files stay structurally consistent through the pre-commit drift hook, but frontend and backend variants may contain domain-specific differences; for example, the backend-review-project variant includes a more comprehensive backend trigger list and additional exemptions.

## Risk rubric

Score the change with the rubric in `.agents/skills/system-architecture-review/SKILL.md`. Score each axis 0–2 and sum.

| Axis | 0 | 1 | 2 |
|---|---|---|---|
| Blast radius | One screen / endpoint, isolated | One module | Cross-module or platform-wide |
| Data sensitivity | Reference / public | Operational, tenant-scoped | Beneficiary, audit-relevant, or PII |
| Authority change | None | Touches role gating or workflow guard | Adds/removes a permission or transition |
| Reversibility | Pure refactor, easy revert | Schema-additive, behavior-preserving | Schema-destructive, contract-breaking, or releases sensitive data |
| External surface | Internal only | Internal API contract change | Public/partner contract or new third-party |
| Operational impact | No change to deploy/runtime | Affects logging, metrics, runtime config | Affects deploy topology, HA, backup, rollback |

- 0–3: **Low** — skip unless an explicit trigger applies.
- 4–6: **Low-Medium** — abbreviated workflow (steps 1–3 of the skill).
- 7–9: **Medium** — full workflow.
- 10+: **High** — full workflow plus mandatory ADR (new or update).
- **Any single axis = 2 → run regardless of total.**

## Always-on triggers (run regardless of score)

From `frontend/AGENTS.md#mandatory-frontend-review-triggers`:
- Auth bootstrap, route guards, role and permission handling, token or session handling, dev-user behavior
- `localStorage` or browser-held workflow state that could affect security, resilience, or multi-user correctness
- HTTP interceptors, API platform services, error-state handling, correlation, retry behavior
- Large dataset rendering, client-heavy transformations, performance-sensitive route behavior
- Workflow-critical UI for approvals, dispatch, receipt, exports, audit evidence, artifact handling
- Any work that could expand Flask dependence or weaken the Angular + Django target architecture

## Two checkpoints (mandatory)

1. **Before finalizing the plan** — design must be architecturally aligned before code is written.
2. **Before final output** — re-run the gate after implementation; if `Misaligned`, do not declare done.

## How to invoke

Use the Skill tool: `Skill skill="system-architecture-review"`. When invoking from another skill, return only the architecture verdict and findings; do not duplicate the host skill's output structure.

If the result is `Conditionally Aligned`, complete the required changes (each named with the gate that proves closure: test, ADR, hook, evidence) before declaring the work done.

If the result is `Misaligned`, the work is incomplete. Resolve and re-review.

## Low-risk exemptions

Skip only when the change is clearly:
- Typo-only documentation edits
- Comment-only edits
- Isolated styling adjustments with no architecture, behavior, or security impact
- Isolated tests that do not alter behavior or contracts

If there is any reasonable doubt, perform the review.
