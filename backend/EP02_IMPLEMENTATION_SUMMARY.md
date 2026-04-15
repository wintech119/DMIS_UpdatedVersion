# EP-02 Supply Replenishment Integration Summary

Historical migration note:
DMIS-10 fully removed the legacy Flask runtime from the repo and deployable system. References below to Flask describe historical behavior context for the Operations cutover, not a current runtime path.

## Overview

This document summarizes the current Django `replenishment` implementation for EP-02.

The valid EP-02 target is:

- stock visibility and freshness
- needs-list planning and approval
- transfer, donation, and procurement outputs from approved needs lists

EP-02 is not the owner of relief-request fulfillment, package allocation, dispatch, or receipt.

## What Remains Valid

- PostgreSQL-backed replenishment schema for planning artifacts
- Django ORM models for needs-list planning, audit, burn-rate snapshots, warehouse sync, and procurement lineage
- stock preview and replenishment calculations
- needs-list draft, review, approval, rejection, return, and escalation workflows
- approved needs-list outputs into transfer, donation, and procurement paths

## Correction Note

The repo still contains frozen `needs_list` execution behavior and supporting persistence for allocation, dispatch, and waybill compatibility.

That code is transitional scaffolding only and should continue shrinking as the Django `operations` domain replaces the remaining compatibility surface.

Freeze this language:

- `NeedsList` = replenishment planning snapshot
- `ReliefRqst` = operational demand plus eligibility
- `ReliefPkg` = package allocation, dispatch, and receipt aggregate

## Current Runtime Reality

- Django replenishment remains the active planning slice
- the workflow dev store is still environment-gated and not proof of production Operations readiness
- the historical May 15 cutover depended on the new Django and Angular Operations implementation, not on keeping Flask Operations live

## Implementation Guardrails

- do not expand `needs_list` execution routes as if they were the future Operations API
- do not claim that current compatibility coverage is already the final DB-backed Operations implementation
- when reviewing the migration-era behavior baseline, use the former Flask request and package rules as historical reference only, not as a current runtime dependency

## Migration Direction

The target architecture is:

- Django `replenishment` for planning
- Django `operations` for fulfillment
- Angular replenishment module for planning
- Angular operations module for fulfillment

The compatibility surface should continue shrinking as Django operations replaces the remaining cutover-era wrappers.
