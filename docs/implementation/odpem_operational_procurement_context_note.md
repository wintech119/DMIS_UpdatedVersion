# ODPEM Operational Procurement Context Note

Last updated: 2026-03-26
Status: Forward-looking planning note

## Purpose

Capture a procurement-context decision that must be preserved for future sprint planning, even though it is not being implemented in the current relief-management freeze.

## Decision

Procurement is not only a replenishment byproduct from needs-list planning.

ODPEM Operations must also have a standing procurement path for stock-readiness maintenance outside a specific donation flow or event-triggered request flow.

## Meaning

There are at least two procurement contexts in the product model:

1. Replenishment-driven procurement
   - originates from approved needs-list planning
   - used as one sourcing output alongside transfers and donations

2. ODPEM operational procurement
   - used by ODPEM operations to maintain readiness stock
   - used to keep stock at or above minimum threshold
   - may be initiated outside donation workflows and outside a specific event-response workflow

## Constraint For Future Sprints

Future sprint planning must not model procurement as only a needs-list downstream artifact.

The design must preserve support for an ODPEM-led operational procurement workflow for baseline readiness and minimum-threshold stock maintenance.

## Current Scope Note

This note does not expand the current relief-management implementation scope by itself.

It is a planning constraint to carry into the next sprint freeze and any future procurement workflow redesign.
