# Historical Sprint 08 Operations Cutover Notes

Historical note:
This file records the Sprint 08 cutover state. The current DMIS-09 posture is that Angular `operations/*` routes and Django `/api/v1/operations/*` APIs are the live shared-dev, staging, and production path of record. Flask is no longer part of the normal live path.

What it replaces:
- Flask relief request list/detail/create/update/submit
- Flask eligibility queue/detail/decision
- Flask package fulfillment queue/detail and first package write contracts
- Flask dispatch queue/detail/handoff and waybill readback

What stays compatibility-only:
- `replenishment` `needs-list/*` execution endpoints remain frozen transitional wrappers.
- When a request/package already has a `NeedsListExecutionLink`, Operations reuses that compatibility bridge so the existing reservation, audit, and waybill persistence logic is not duplicated. This is Django compatibility behavior, not a Flask runtime dependency.

Known temporary cutover dependencies:
- Direct Operations requests can be created and reviewed in Django without `needs_list`.
- Allocation/dispatch parity is strongest when the request/package is linked through `NeedsListExecutionLink`.
- For direct Operations requests without a planning link, allocation and dispatch run on the legacy request/package tables, but waybill JSON persistence is not yet backed by a dedicated Operations table.

Current DMIS-09 status:
- Angular Operations screens already route to these Django APIs and no normal live navigation points users to Flask.
- Flask runtime activation is now gated behind the temporary `DMIS_FLASK_RUNTIME_MODE=rollback-only` exception.
- Canonical DB RBAC permission rows remain an operational hardening follow-up, but they are not a reason to keep Flask in the live path.

Relief request tenancy governance note:
- Relief requests remain an Operations-owned workflow and are not normalized back into Supply Replenishment ownership.
- The intended steady-state owner is the non-ODPEM operational tenant that is requesting assistance.
- ODPEM may create a relief request on behalf of a non-ODPEM tenant only as a transitional bridge while lower-level tenants are still onboarding to DMIS direct entry.
- That ODPEM on-behalf path must stay policy-gated and should not be treated as the permanent ownership model for request origination.
- ODPEM-owned agencies are intentionally excluded from this request-entry flow so the frontend can present ODPEM as a processor/on-behalf actor, not as the default requesting owner.

Frontend readiness runbook:
- Apply the schema migration first: `python manage.py migrate operations`
- Seed canonical DB RBAC rows with `python manage.py seed_operations_rbac_permissions --apply`
- Seed the flat/direct tenant baseline with `python manage.py bootstrap_relief_management_authority_baseline --apply`
- Load explicit hierarchy and request-authority data with `python manage.py import_relief_management_authority operations/examples/relief_management_authority_seed.example.json --apply`
- Replace the example file with real tenant rows before using it in a shared environment.
- If frontend needs temporary non-ODPEM beneficiary master data, seed it with `python manage.py seed_relief_management_frontend_test_data --tenant-code JRC --apply`
- If frontend needs temporary non-ODPEM tenant users, seed them with `python manage.py seed_relief_management_frontend_test_users --tenant-code JRC --apply`
- If QA needs temporary parish-to-subordinate request-authority coverage, seed it with `python manage.py seed_relief_management_hierarchy_test_data --parish-tenant-code PARISH-KN --subordinate-tenant-code FFP --apply`
- Audit beneficiary-agency readiness with `python manage.py audit_relief_management_agency_scope --json-out operations/examples/agency_scope_audit.json`
- Verify live readiness with `python manage.py check_relief_management_readiness`
- To retire the temporary JRC frontend data later, run `python manage.py cleanup_relief_management_frontend_test_data --tenant-code JRC --apply`
- To retire the temporary parish-to-subordinate QA authority data later, run `python manage.py cleanup_relief_management_hierarchy_test_data --parish-tenant-code PARISH-KN --subordinate-tenant-code FFP --apply`
- For targeted rollout checks, add tenant IDs: `python manage.py check_relief_management_readiness --tenant-id 300 --tenant-id 400`
- If DB RBAC must be canonical before promotion, run the readiness check with `--strict-permissions` and seed canonical `operations.*` permission rows before promotion.
- If no active non-ODPEM agencies resolve to a tenant via `agency -> warehouse -> tenant`, the Relief Request create flow still lacks real beneficiary-agency targets outside ODPEM-owned data.
- The agency audit command writes the exact agency, warehouse, and tenant ownership inventory needed for master-data remediation without inventing new ownership rules in code.
