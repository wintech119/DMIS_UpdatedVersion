# Master Alignment Matrix (Live Schema vs v5.1)

Legend:
- Coverage: `covered` | `partial` | `gap`
- Action: `keep` | `extend` | `new`

| Domain | Table | Requirement IDs | Coverage | Gap Summary | Action | Wave |
|---|---|---|---|---|---|---|
| Multi-tenancy | `tenant` | FR13.01, FR13.08, FR13.10 | partial | Tenant type set does not fully match v5.1 canonical values (`SOCIAL_SERVICES`, `NGO`); no unique `tenant_code` constraint in live schema. | extend | 3 |
| Multi-tenancy | `tenant_user` | FR13.03 | partial | Users are mapped to tenants, but roles are not tenant-scoped in this table. | extend | 2 |
| Multi-tenancy | `tenant_warehouse` | FR13.04 | covered | Structure supports shared-warehouse model. | keep | 1 |
| Multi-tenancy | `tenant_config` | FR13.05 | partial | Generic K/V exists, but no typed policy tables for approval/workflow/event controls. | extend | 2 |
| Multi-tenancy | `data_sharing_agreement` | FR13.06, FR13.07 | partial | Core structure exists; no policy enforcement linkage at query guard level. | extend | 4 |
| Multi-tenancy | `warehouse` (`tenant_id`) | FR13.02 | partial | Tenant FK exists, but RLS policies are absent. | extend | 4 |
| Multi-tenancy | `custodian` (`tenant_id`) | FR13.02 | partial | Tenant FK exists, but RLS policies are absent. | extend | 4 |
| Security/RBAC | `role` | FR11.09, FR11.10, FR11.11, FR11.12 | partial | Role catalog exists; no tenant-scoped role assignment table. | extend | 2 |
| Security/RBAC | `permission` | FR11.09, FR11.11 | covered | Resource/action matrix exists. | keep | 1 |
| Security/RBAC | `role_permission` | FR11.11 | covered | Mapping exists with optional `scope_json`. | keep | 1 |
| Security/RBAC | `user_role` | FR11.10, FR11.14, FR13.03 | partial | User-role assignment exists but not tenant-scoped; warehouse scoping handled separately. | extend | 2 |
| Security/RBAC | `user_warehouse` | FR11.14 | covered | Warehouse-scoped access table exists. | keep | 1 |
| Security/RBAC | `user` | FR11.01–FR11.08 | covered | Account fields support identity, status, lockout controls. | keep | 1 |
| Event/Phase | `event` | FR02.01 | partial | `current_phase` allows `SURGE/STABILIZED/BASELINE`; missing `RECOVERY`. | extend | 3 |
| Event/Phase | `event_phase` | FR02.01, FR02.04.1 | partial | Phase check excludes `RECOVERY`; justification not enforced for changes. | extend | 3 |
| Event/Phase | `event_phase_config` | FR02.04.1, FR02.45, FR13.05 | partial | Config exists, but phase check excludes `RECOVERY`; no tenant override column. | extend | 3 |
| Event/Phase | `event_phase_history` | FR02.01 | partial | Transition history exists but excludes `RECOVERY`. | extend | 3 |
| Replenishment Config | `lead_time_config` | FR02.53 | partial | A and C are modeled; B donor-specific lead-time is not modeled (no `donor_id`). | extend | 3 |
| Replenishment Config | `warehouse_sync_status` | FR02.83, FR02.85, FR07.06 | covered | Freshness/status dimensions are present. | keep | 1 |
| Replenishment Config | `warehouse_sync_log` | FR07.06 | covered | Sync event logging exists. | keep | 1 |
| Supply Master | `itemcatg` | FR03.03, FR02.34.1, FR02.82 | partial | Category master exists; no explicit per-category baseline policy table for stale-data burn rate fallback. | extend | 2 |
| Supply Master | `item` | FR03.03, FR03.04, FR03.16, FR06.01 | partial | Criticality and baseline burn exist; issuance mode not normalized, and category baseline fallback governance is externalized. | extend | 3 |
| Supply Master | `unitofmeasure` | FR01.08, FR03.04 | covered | UOM master is present and linked. | keep | 1 |
| Supply Master | `supplier` | FR02.10, FR02.11, FR02.53 | partial | Supplier master exists; explicit `TRN/TCC` fields absent. | extend | 3 |
| Supply Master | `donor` | FR01.06, FR01.16, FR02.53 | partial | Donor master exists; no donor lead-time linkage for Horizon B config. | extend | 3 |
| Supply Master | `agency` | FR05.01, FR09.03 | partial | Agency master exists; needs explicit agency-priority support for allocation rule engine. | extend | 3 |
| Supply Master | `warehouse` | FR04.01, FR04.02, FR04.03 | covered | Warehouse hierarchy and type constraints exist. | keep | 1 |
| Supply Master | `parish` | FR04.05, FR06.01, FR09.03 | covered | Geographic master exists. | keep | 1 |
| Supply Master | `country` | FR01.03, FR01.06 | covered | Country master exists. | keep | 1 |
| Supply Master | `currency` | FR08.03, FR08.04 | covered | Currency master exists. | keep | 1 |
| Workflow Config | `needs_list_workflow_metadata` | FR02.90–FR02.98 | partial | Free JSON metadata exists; formal transition policy/rule table absent. | extend | 2 |
| Workflow Status | `reliefrqst_status` | FR05.04 | covered | Request status master exists. | keep | 1 |
| Workflow Status | `reliefrqstitem_status` | FR05.07, FR05.08 | covered | Item-level status master exists. | keep | 1 |
| Procurement Master | `procurement` | FR02.14, FR02.16, FR02.73, FR02.74 | partial | Status/method checks partially align, but canonical v5.1 method and lifecycle vocabulary are not fully normalized. | extend | 3 |
| Procurement Master | `procurement_item` | FR02.14, FR02.72 | covered | Line-item structure supports lifecycle and needs list linkage. | keep | 1 |
| Allocation Policy | `allocation_rule` | FR06.01, FR06.02, FR06.04, FR06.06 | gap | No dedicated allocation rule master in live schema. | new | 2 |
| Allocation Policy | `allocation_limit` | FR06.03 | gap | No configurable agency/event limit master table. | new | 2 |
| Approval Policy | `approval_threshold_policy` | FR02.16, FR08.05, FR13.05 | gap | No canonical threshold policy table; logic currently implied. | new | 2 |
| Approval Policy | `approval_authority_matrix` | FR04.05, FR02.16, FR08.05 | gap | No explicit role/sequence approval matrix table by entity + threshold. | new | 2 |
| Workflow Governance | `workflow_transition_rule` | FR02.14, FR02.93, FR11.13, FR11.17 | gap | No declarative transition rule table with SoD and reason-code requirements. | new | 2 |
| Reason Governance | `reason_code_master` | FR03.11, FR06.06, FR11.17 | gap | Reason codes exist as free text/check constraints in many tables; no central governance table. | new | 1 |
| Reference Catalog | `ref_tenant_type` | FR13.08 | gap | No normalized tenant-type reference table for governed values and evolution. | new | 1 |
| Reference Catalog | `ref_event_phase` | FR02.01, FR13.05 | gap | Phase values are constraint-bound; no reusable reference catalog. | new | 1 |
| Reference Catalog | `ref_procurement_method` | FR02.73 | gap | Method values are constraint-bound; no governed code table. | new | 1 |
| Reference Catalog | `ref_approval_tier` | FR02.16, FR08.05 | gap | Approval tiers are constraint-bound; no policy catalog. | new | 1 |
| Tenant RBAC | `user_tenant_role` | FR13.03, FR11.10, FR11.12 | gap | Tenant membership and role assignment are not joined in one authoritative mapping. | new | 2 |
| Analytics Policy | `item_category_baseline_rate` | FR02.34.1, FR02.82 | gap | Baseline fallback required by category; live schema only has item-level baseline. | new | 2 |
| Prioritization Policy | `mpf_criteria_weight` | FR06.11, FR06.12 | gap | MPF RAG weighting criteria are not modeled as governed configuration. | new | 2 |

## Scope Clarification
- Excluded by design: framework/system tables (`auth_*`, `django_*`).
- Transaction-only tables are referenced only where they consume master/config data.

