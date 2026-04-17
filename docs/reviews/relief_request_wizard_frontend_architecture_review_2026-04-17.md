# Relief Request Wizard Frontend Architecture Review

Date: 2026-04-17
Scope: Relief request wizard validation parity, legacy request-mode normalization, and audit-trail updates.

## Decision
Aligned

## Architecture Findings
- Severity: Low
  Area: Forms / Validation
  What is wrong: The frontend request-notes and item-reason flows had drifted from the backend-aligned length/required constraints, and the step-component spec bypassed urgency-driven validation by injecting validators directly.
  Why it matters: DMIS architecture requires frontend validation for UX parity while keeping backend enforcement authoritative. Drift here weakens operator feedback and makes regressions harder to detect before submission.
  Recommended fix: Preserve `rqst_notes_text` max-length validation while toggling high-urgency required state, mirror the required/maxlength semantics in the template, and drive tests through urgency controls instead of direct validator mutation.
- Severity: Low
  Area: Compatibility / Display
  What is wrong: Legacy whitespace-only `request_mode` values could suppress `origin_mode` fallback during adapter normalization, and unnormalized `SUBORDINATE` values could render as raw text in UI formatters.
  Why it matters: Transitional compatibility issues create inconsistent operator-facing labels and can obscure the authoritative backend state that RBAC/tenancy-aware workflows depend on.
  Recommended fix: Trim both request-mode candidates before selecting the first non-empty value, preserve the canonical `SUBORDINATE` to `FOR_SUBORDINATE` mapping, and keep a formatter alias for legacy display inputs.

## Required Changes Before Completion
- Keep `rqst_notes_text` at the backend-matched 500-character limit in both the form model and template.
- Preserve the fixed max-length validator when urgency toggles request-notes required state.
- Mirror urgency-driven `required` semantics in the request-items step template.
- Update the request-items step spec to exercise the real urgency-driven validation path.
- Link this artifact from the task note and PR audit trail.

## Accepted Deviations / Temporary Exceptions
None.

## Docs Checked
- [DMIS System and Application Architecture](../adr/system_application_architecture.md)
- [DMIS Security Architecture](../security/SECURITY_ARCHITECTURE.md)
