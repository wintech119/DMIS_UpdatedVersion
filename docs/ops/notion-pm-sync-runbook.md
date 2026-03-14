# Notion PM Sync Runbook

## Purpose

Use the Product Management Workspace in Notion as the PM system of record for sprint planning, execution coordination, and cross-lane reporting.

The sync model has two separate flows:

- `sync sprint plan from <artifact-url-or-id>`
- `sync sprint execution for <sprint-url-or-id>`

These are prompts for Codex in this workspace, not shell commands.

## Planning Sync

Run planning sync when a Product & Analysis implementation brief is ready for handoff.

The source artifact must:

- be an `Artifacts` record using the Implementation Brief structure
- have `Product` and `Sprint` relations populated
- include `## Sprint Goal`
- include `## Planning Risks`
- include `## Planned Activities`

The `Planned Activities` table must contain these columns:

- `Work Item ID`
- `Title`
- `Lane`
- `Item Type`
- `Priority`
- `Due Date`
- `Owner`
- `Acceptance Criteria`

Planning sync will:

- create or update one `Work Items` row per planned activity
- generate missing `DMIS-WI-###` IDs using the product code
- update the linked sprint `Sprint Goal`
- update the linked sprint `Risks / Blockers`
- ensure the source artifact links the synced work items
- create or update a draft `Daily Updates` entry titled `YYYY-MM-DD | <ProductCode> | Cross-Lane Sprint Summary`

Planning sync will not overwrite these execution-managed fields:

- `Status`
- `Branch Name`
- `PR Link`
- `Repo Path / Doc Link`
- `Ready for QA`
- `QA Result`
- `Parent Item`
- Slack or Zoom fields

## Execution Sync

Run execution sync after meaningful branch, commit, or pull request movement for work items already linked to a sprint.

Execution sync reads:

- work items linked to the selected sprint
- local git branch and recent commit activity
- GitHub pull request metadata when a work item already has a PR link or a PR matches the work item ID convention

Matching precedence:

1. `DMIS-WI-###` in branch name, PR title, or PR body
2. existing `PR Link`
3. existing `Branch Name`

Execution sync may update:

- `Branch Name`
- `PR Link`
- `Repo Path / Doc Link` when the target is already present or unambiguous

Execution sync will not:

- delete work items
- move status backward
- overwrite manual status decisions directly
- auto-change sprint `Status`
- auto-change sprint `Sprint Health`

Instead, it produces suggested status movement in the sync report and daily digest.

Execution sync also appends an automation-managed block to sprint `Risks / Blockers` summarizing:

- blocked work items
- work items missing PR linkage
- merged PRs awaiting QA movement
- unmatched execution signals that need manual review

It creates or updates a draft `Daily Updates` entry titled `YYYY-MM-DD | <ProductCode> | Cross-Lane Daily Digest`.

## Branch And PR Convention

Use the work item ID in both branches and pull requests so execution sync can match confidently.

Examples:

- branch: `feature/DMIS-WI-104-item-category-admin-ui`
- PR title: `DMIS-WI-104 | Build item category admin UI`

## Sync Report Shape

Each sync run should report:

- `created`
- `updated`
- `suggested`
- `skipped`
- `unmatched`
- `errors`

## Daily Automation

Daily execution automation should run once per day at 6:00 PM America/Bogota.

Behavior:

- find active sprints in Notion
- run execution sync for each active sprint
- refresh the draft cross-lane daily digest for the day
- preserve manual status decisions and manual sprint notes

## Current Seeded Example

The current seeded sprint flow uses:

- Product: `Unified DMIS`
- Sprint: `2026-S06 | DMIS | Master Data & Category Model`
- Artifact: `DMIS | Sprint 06 | Implementation Brief | Item Category Module`

Use that artifact and sprint as the reference example when validating future sync changes.
