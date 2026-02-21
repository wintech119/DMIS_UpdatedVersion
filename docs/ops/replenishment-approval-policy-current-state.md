# Replenishment Approval Policy (Current State)

Date: 2026-02-20

## Scope
This note documents the current implementation state for approvals in the replenishment workflow.

## Current Policy (Implemented)
1. Transfer (`selected_method = A`)
- Primary approver: Logistics Manager roles.
- On-behalf rule: Director PEOD roles are allowed when the submitter is in a logistics role.

2. Donation (`selected_method = B`)
- Approver set is Senior Director / PEOD-capable roles.

3. Procurement (`selected_method = C`)
- In-system approval is Director PEOD roles.
- Director General (DG) approval is manual and outside system flow.

## Keycloak-Managed Users
- Keycloak role claims are supported for authorization.
- Permissions are resolved from role claims against DB `role` + `role_permission` mappings (not only `user_role` assignments).

## Deferred by Decision (Not Implemented Now)
- Tenant-configurable approval policy in application runtime.
- Tenant-admin approval policy UI/API.
- Any dynamic per-tenant approval matrix loaded from `tenant_config` for runtime authorization.

## Operational Ownership
- Approval behavior above is code-driven for now.
- Tenant system administrators should manage who can approve by controlling role assignment and role-permission mappings.

## Next Phase (When Approved)
- Introduce tenant-admin-managed approval policy configuration with governance and audit controls.
- Keep policy writes restricted to system administrators for the tenant.
