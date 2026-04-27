# Output Contract

Every analysis or review produced by this skill must use this structure. It mirrors the canonical contract in `.agents/skills/system-architecture-review/SKILL.md` so chain output remains consistent.

## Decision
One of:
- `Aligned`
- `Conditionally Aligned`
- `Misaligned`

State the risk score breakdown inline (per the rubric in `references/architecture-review-handoff.md`).

## Findings

For each finding:
- **Severity:** Critical / High / Medium / Low
- **ISO 25010 characteristic:** Functional suitability / Performance efficiency / Compatibility / Usability / Reliability / Security / Maintainability / Portability
- **Control reference (when applicable):** OWASP ASVS / OWASP Top 10 / NIST CSF / WCAG / DMIS-internal (e.g. `backend/AGENTS.md:88`)
- **Area:** Architecture / Security / Authorization / ORM / Database / DRF / Migration / Performance / Compliance / Operations
- **Finding:** What is wrong or risky (file:line where possible)
- **Why it matters:** Operational impact in DMIS terms (Kemar, SURGE, audit trail, tenant isolation)
- **Recommended fix:** Concrete step
- **Confidence:** High / Medium / Low
- **Suspected agent source (if drift):** Claude Code / Codex / cross-agent / n/a

## Required Changes Before Completion

Each item names the gate that proves closure: test, ADR, hook, evidence. Missing-gate items end up here, not under "deviations."

## Accepted Deviations / Temporary Exceptions

Or `None`. Each must point to the doc recording the deviation and its sunset condition.

## Conformance Evidence

Concrete artifacts: test runs, scan output, file:line references, ADR links. If missing, list under Required Changes instead.

## ADR Action

One of:
- `New ADR required` (with proposed title)
- `Existing ADR update required` (with the path)
- `ADR-lite append acceptable` (with the doc that gets the paragraph)
- `No ADR change required`

## Hooks / Automation Recommendations

Reference `references/hooks-recommendations.md`. Route the user to the `update-config` skill to apply.

## Docs Checked

Source-of-truth docs actually consulted in the review.

## Standards Cited

ISO 25010 chars, ASVS controls, NIST controls, WCAG criteria, DMIS doc references.

## Style notes

- Be direct. Prefer concrete file:line references over vague claims.
- Cite specific control identifiers (e.g. `ASVS V2.1.1`, `WCAG 2.2 1.4.3`), not "best practice."
- Distinguish temporary transition allowances from target-state alignment.
- Name agent source for drift findings so prompts and hooks can be tuned.
- Recommend the cheapest enforcement layer (test > lint > hook > human review).
