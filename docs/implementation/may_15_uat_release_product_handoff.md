# DMIS | May 15 UAT Release | Product Handoff

Last updated: 2026-03-24  
Status: Historical handoff scaffold - superseded for current deployment guidance  
Release target: `UAT-ready by May 15, 2026`

Historical note:
This handoff captures the May 15 cutover program context. It is not the current operational baseline. For current deployment posture, treat Angular + Django as the live path of record, and note that DMIS-10 later fully removed the legacy Flask runtime and rollback gate.

## Purpose

This handoff is the final cross-lane product record for the May 15 UAT release target. It summarizes delivered capability, requirement traceability, final QA evidence, accepted gaps, immediate post-UAT backlog, and the Operations cutover from Flask to Django and Angular.

## Required Inputs Before Signoff

- Sprint 07 foundation evidence
- Sprint 08 boundary-correction evidence
- Sprint 08 backend-first Operations rebuild evidence
- Sprint 08 Angular Operations cutover evidence
- Sprint 08 Flask retirement evidence from the historical cutover window
- Sprint 09 distribution confirmation and operational tracking evidence
- Sprint 10 UAT execution and hardening evidence
- final blocker disposition
- accepted-gap register
- final scope disposition register
- included-module alignment summary for donation, procurement, transfer, and replenishment

## Interim Release Update | 2026-03-24

### Boundary Correction Summary

- Sprint 08 is corrected to treat `NeedsList` as the replenishment planning artifact, not the owner of package execution.
- Relief requests, eligibility review, package fulfillment, and dispatch are being rebuilt under a new Django and Angular Operations path.
- Legacy Flask Operations was the behavior reference and temporary scaffold only during the cutover window.
- May 15 signoff requires live Operations navigation and APIs to land on the new Angular and Django stack, not on Flask.

### Product Impact

- `Supply Replenishment` stays focused on stock status, needs-list generation, needs-list review, and sourcing outputs.
- `Operations` becomes the live Django and Angular path for relief requests, eligibility review, package fulfillment, allocation, and dispatch.
- This correction removes ambiguity for implementation, QA, and UAT signoff and prevents further work from being attached to the wrong aggregate.

### Analysis and Traceability Note

- Durable sources for this correction are:
  - `docs/implementation/sprint_08_needs_list_execution_boundary_and_migration.md`
  - `docs/implementation/sprint_08_operations_cutover_and_flask_retirement.md`
- The Sprint 08 brief, lane prompts, release plan, and scope register were updated together to reflect the same backend-first, frontend-second, QA-third cutover narrative.
- No new May 15 scope was introduced by this correction. The update fixes ownership, sequencing, and signoff criteria.

### UAT Readiness Note

- This correction clears the product-definition blocker for May 15.
- UAT readiness still depends on backend parity, Angular Operations cutover, QA evidence, and explicit Flask retirement treatment in the historical cutover record.

## Interim Release Update | 2026-03-24 | Location-Storage Command Restoration

### Summary

- The restored backend command path for location-storage policy enforcement is now green on the active May 15 release branch.
- The command `enforce_location_storage_policy` was validated successfully on the Django stack, including dry-run and live-Postgres apply behavior.
- No allocation or dispatch backend smoke regression was found alongside this restoration.

### Product Impact

- This change enforces correct storage writes for batched versus non-batched items through the intended location-routing enforcement path.
- It improves confidence that location-assignment behavior writes against the correct storage-routing rules before May 15 UAT.
- It does not change user-facing stock ownership semantics or underlying quantity ownership.

### Analysis and Traceability Note

- This is a command plus SQL enforcement and view-contract update, not a base-table migration.
- Base inventory and batch stock tables were not altered by this restoration.
- Inventory and batch stock quantity fields remain on their underlying tables.
- The restored view contract now aligns to the intended routing schema with `inventory_id`, `item_id`, `location_id`, `batch_id`, and `is_batched_flag`.

### UAT Readiness Note

- This restored command path no longer blocks May 15 UAT readiness for location-storage enforcement behavior.
- The pre-existing `api.W001` warning remains out of scope for this specific update.
