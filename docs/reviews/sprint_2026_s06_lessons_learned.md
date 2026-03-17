# Lessons Learned: Sprint 2026-S06 | DMIS | Master Data & Category Model

**Date:** March 15, 2026  
**Related Sprint Review:** [sprint_2026_s06_review.md](C:/Users/wbowe/OneDrive/Desktop/project/DMIS_UpdatedVersion/docs/reviews/sprint_2026_s06_review.md)

## Purpose

Capture lessons from Sprint `2026-S06` that should improve how future DMIS sprints are planned, reviewed, implemented, and closed.

## Lessons Learned

### 1. Freeze the business rules before teams start implementing
- The Item Master work only became stable once the business rules for IFRC identity, governed selection, fallback behavior, and legacy handling were written down clearly.
- Future sprints should lock the product rules earlier, especially when backend, frontend, and QA all depend on the same decisions.

### 2. Keep one shared contract across backend, frontend, and QA
- A lot of churn came from contract drift between what the backend returned, what the frontend expected, and what QA validated.
- Future sprints should keep one durable contract or baseline summary that all lanes use, instead of letting each lane interpret the feature separately.

### 3. Separate official data from helper or fallback behavior
- The sprint surfaced an important distinction:
  - official governed IFRC references
  - fallback or assistive suggestions
- Treating these as separate concepts made the model more reliable and easier to explain.
- Future sprints should make this split explicit anytime the system mixes governed records with AI or generated helpers.

### 4. Migrations must be self-contained
- One of the biggest review risks came from migration logic that could have depended on mutable app code or live taxonomy helpers.
- Future sprint delivery should require migration files to be deterministic, frozen, and safe to run later without depending on current application behavior.

### 5. Structured backend errors are worth it only if the UI shows them
- The backend had already started returning `detail`, `diagnostic`, and `warnings`, but the value was limited until the frontend displayed them clearly.
- Future sprints should treat error contracts as end-to-end work:
  - backend structure
  - frontend display
  - QA coverage

### 6. Review bots are useful, but they need disposition discipline
- Bot feedback helped catch real migration, readback, and guardrail issues.
- It also produced comments that were already fixed later, style-only, or out of scope.
- Future sprints should create a short disposition note during PR review:
  - fix now
  - already fixed
  - defer
  - ignore

### 7. Sprint closure should be based on merged state, not pre-merge review state
- Several earlier concerns were resolved by later commits before the PR merged.
- The final sprint assessment only became accurate after checking the merged code, not just the earlier review thread.
- Future sprint closeout should always review:
  - merged PR state
  - final status checks
  - post-merge repo evidence

### 8. Keep follow-up improvements separate from sprint blockers
- This sprint had a few good follow-up ideas that did not need to block completion.
- Future sprints should explicitly separate:
  - blocker issues
  - non-blocking polish
  - later enhancements

### 9. Notion closeout should not be the only durable record
- The repo-level documentation was critical when Notion auth was unavailable.
- Future sprints should always produce a durable in-repo sprint review or implementation summary so closure evidence does not depend on one external tool being reachable.

## Reusable Practices for Future Sprints

Use this checklist for future sprint closeout:

1. Confirm the main implementation PR is merged.
2. Confirm final GitHub status checks are green.
3. Run or verify the targeted validation suite.
4. Review the merged code for any previously high-risk comments.
5. Record blockers separately from non-blocking follow-ups.
6. Write a short sprint review in the repo.
7. Sync the sprint conclusion into Notion after the repo review is complete.

## Recommended Carry-Forward Rules

- Write implementation-ready product rules before backend and frontend split into separate threads.
- Treat migrations as release-grade artifacts, not just code that happens to work today.
- Keep backend error payloads structured and require the UI to render them meaningfully.
- Require one shared acceptance baseline for backend, frontend, and QA.
- Use plain-language guidance for operations, governance, and closeout notes.

## Suggested Use in Other Sprints

This lessons-learned note should be referenced when future sprints involve:
- data-model changes
- migration-heavy delivery
- governed catalogs or taxonomy work
- cross-lane backend/frontend/QA contracts
- AI-assisted helper flows mixed with official records
