# Master Forms Backlog and Strategy

## Form Strategy Rules
- All dropdowns must be sourced from master/reference tables (no hardcoded enums).
- All master forms include audit columns and active/inactive lifecycle controls.
- Tenant-aware forms must enforce scoped visibility using tenant context.
- High-risk forms (approval matrix, transition rules, allocation rules) require dual-control approval.

## Wave 1 Forms (Reference Catalogs)
1. `Tenant Type Catalog`
   - CRUD: `ref_tenant_type`
   - Validations: unique code, active status
2. `Event Phase Catalog`
   - CRUD: `ref_event_phase`
   - Includes `RECOVERY`
3. `Procurement Method Catalog`
   - CRUD: `ref_procurement_method`
4. `Approval Tier Catalog`
   - CRUD: `ref_approval_tier`
5. `Reason Code Catalog`
   - CRUD: `reason_code_master`
   - Domain filter + requires-comment flag

## Wave 2 Forms (Governance/Policy)
1. `Approval Threshold Policy`
   - CRUD: `approval_threshold_policy`
   - Validations: amount ranges non-overlapping by entity/method/currency/tenant/effective window
2. `Approval Authority Matrix`
   - CRUD: `approval_authority_matrix`
   - Validations: contiguous sequence, no duplicate role per sequence
3. `Workflow Transition Rules`
   - CRUD: `workflow_transition_rule`
   - Validations: no duplicate transition rows per entity/from/to/tenant
4. `Allocation Rules`
   - CRUD: `allocation_rule`
   - Validations: weight totals and phase compatibility
5. `Allocation Limits`
   - CRUD: `allocation_limit`
   - Validations: no overlapping limit windows for same event/agency/category
6. `Tenant-Scoped User Roles`
   - CRUD: `user_tenant_role`
   - Validations: user and role must already be active in tenant scope
7. `Category Baseline Burn Rates`
   - CRUD: `item_category_baseline_rate`
   - Validations: positive rate, single active row per category/phase/tenant
8. `MPF Criteria Weights`
   - CRUD: `mpf_criteria_weight`
   - Validations: normalized weights by profile if required

## Wave 3 Forms (Existing Table Extensions)
1. `Tenant Registry` (extended)
   - Table: `tenant`
   - Add managed type options incl. `SOCIAL_SERVICES`, `NGO`
2. `Event Phase Configuration` (extended)
   - Tables: `event_phase`, `event_phase_config`
   - Add `RECOVERY` phase support
3. `Lead Time Configuration` (extended)
   - Table: `lead_time_config`
   - Add donor-driven Horizon-B entries
4. `Supplier Registry` (extended)
   - Table: `supplier`
   - Add TRN/TCC fields
5. `Needs List Workflow Settings` (extended)
   - Table: `needs_list_workflow_metadata` + `workflow_transition_rule`
   - Replace ad hoc JSON-only governance with managed rules

## Access Control by Form
- `System Administrator`: full CRUD for all master forms.
- `Senior Director (PEOD)`: approve/publish policy forms, view all.
- `Logistics Manager`: CRUD for operational masters (item/category/uom/supplier/lead-time), view governance forms.
- `Auditor`: read-only across all forms.

## Release Sequencing
1. Deploy catalog forms first.
2. Deploy policy forms next and freeze manual threshold logic.
3. Deploy extended existing forms and enable strict validation.
4. Enable RLS-aware UI filtering in all tenant-scoped forms.

