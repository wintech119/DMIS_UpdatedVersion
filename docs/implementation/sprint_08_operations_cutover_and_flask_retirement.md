# Sprint 08 | Operations Cutover and Flask Retirement

Last updated: 2026-03-24  
Status: Active cutover plan

## Purpose

This document is the cutover source of truth for removing Flask Operations from the live May 15 path.

## Legacy-to-Target Mapping

| Legacy Flask Surface | Target Angular Route | Target Django API Namespace | Notes |
| --- | --- | --- | --- |
| `/executive/operations` | `/operations/dashboard` | `/api/operations/dashboard/*` | Angular becomes the live landing point |
| `/relief-requests/*` | `/operations/relief-requests/*` | `/api/operations/requests/*` | Request create, list, detail, edit, tracking |
| `/eligibility/*` | `/operations/eligibility-review/*` | `/api/operations/eligibility/*` | Review queues and decisions |
| `/packaging/pending-fulfillment` | `/operations/package-fulfillment` | `/api/operations/packages/*` | Queue and package preparation |
| `/packaging/dispatch/*` | `/operations/dispatch/*` | `/api/operations/dispatch/*` | Dispatch queue, detail, and handover |

## Entry Criteria For Cutover

- the corrected domain boundary is documented and approved
- backend Operations contracts exist for the required request, package, allocation, and dispatch flows
- Angular Operations screens exist for the required live paths
- parity QA can run against the new stack

## Exit Criteria For Cutover

- live navigation no longer sends users to Flask Operations pages
- Angular `operations/*` is the default Operations route tree
- Django `/api/operations/*` handles the live Operations reads and writes
- required parity, stock-integrity, and audit checks are green
- release docs and QA evidence no longer describe Flask as the live Operations path

## Flask Retirement Checklist

- remove or disable default Operations nav links that point to Flask
- redirect or retire public Flask Operations entry points used by live users
- mark any remaining Flask Operations endpoints as rollback-only or internal-only
- update release notes, QA notes, and handoff artifacts to show the cutover state
- capture any residual fallback procedure explicitly rather than leaving Flask as an implicit live dependency

## Rollback Rule

If a release-blocking parity defect is found late in Sprint 08 or Sprint 10:

- record the blocker and affected route or API
- decide explicitly whether the Flask path is a temporary rollback path for that specific capability
- update the release handoff and scope disposition record in the same change set
- do not silently leave Flask in the live path without naming the rollback decision

## Evidence Required

- legacy-to-target route and API mapping
- backend parity note for stock, reservation, approval, dispatch, and audit behavior
- frontend parity note for workflow screens and navigation
- QA cutover evidence showing live-user-path removal of Flask Operations
- explicit retirement or rollback-only status for each legacy Operations entry point
