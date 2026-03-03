# Target Master Data Specification (v5.1 Alignment)

This specification defines the target master/config model to close live-schema gaps identified in `01_master_alignment_matrix.md`.

## 1) New Reference Catalogs

## 1.1 `ref_tenant_type`
- Purpose: Govern valid tenant types with extensible metadata.
- Keys:
  - PK: `tenant_type_code`
- Required codes:
  - `NATIONAL`, `MILITARY`, `SOCIAL_SERVICES`, `PARISH`, `NGO`, `MINISTRY`, `EXTERNAL`, `INFRASTRUCTURE`, `PUBLIC`
- Consumers:
  - `tenant.tenant_type`

## 1.2 `ref_event_phase`
- Purpose: Govern event phase vocabulary.
- Required codes:
  - `SURGE`, `STABILIZED`, `RECOVERY`, `BASELINE`
- Consumers:
  - `event.current_phase`
  - `event_phase.phase_code`
  - `event_phase_config.phase`
  - `event_phase_history.from_phase`, `event_phase_history.to_phase`

## 1.3 `ref_procurement_method`
- Purpose: Canonical procurement methods and display labels.
- Required codes:
  - `EMERGENCY_DIRECT_PURCHASE`
  - `FRAMEWORK_CALLOFF`
  - `COMPETITIVE_QUOTATION`
  - `OPEN_TENDER`
- Compatibility:
  - Keep legacy codes accepted during migration window.

## 1.4 `ref_approval_tier`
- Purpose: Govern approval tier taxonomy for thresholds.
- Required codes:
  - `TIER_1`, `TIER_2`, `TIER_3`, `EMERGENCY`

## 1.5 `reason_code_master`
- Purpose: Centralize reason codes across workflows.
- Core fields:
  - `reason_domain` (e.g., `ALLOCATION_OVERRIDE`, `REJECTION`, `DISPOSAL`, `SOD_EXCEPTION`)
  - `reason_code`
  - `reason_desc`
  - `requires_comment_flag`
  - `status_code`

## 2) New Governance and Policy Tables

## 2.1 `approval_threshold_policy`
- Purpose: Encode approval thresholds by entity/method/amount.
- Key fields:
  - `entity_type` (`PROCUREMENT`, `DISBURSEMENT`, `TRANSFER`, ...)
  - `procurement_method_code` (nullable for non-procurement entities)
  - `min_amount`, `max_amount`, `currency_code`
  - `approval_tier_code`
  - `requires_ppc`, `requires_cabinet`
  - `tenant_id` (nullable for global defaults)
  - `effective_date`, `expiry_date`, `status_code`

## 2.2 `approval_authority_matrix`
- Purpose: Define who approves, and in what sequence, per policy.
- Key fields:
  - `threshold_policy_id`
  - `role_code`
  - `approval_sequence`
  - `is_mandatory`
  - `same_parish_only`, `cross_parish_only`
  - `tenant_id`, `effective_date`, `expiry_date`, `status_code`

## 2.3 `workflow_transition_rule`
- Purpose: Declarative workflow status transitions and controls.
- Key fields:
  - `entity_type` (`NEEDS_LIST`, `PROCUREMENT`, `TRANSFER`, `DISBURSEMENT`, ...)
  - `from_status`, `to_status`
  - `role_code`
  - `requires_reason_code`
  - `reason_domain` (if required)
  - `enforce_sod` (no same actor request+approve)
  - `tenant_id`

## 2.4 `allocation_rule`
- Purpose: Configurable allocation prioritization.
- Key fields:
  - `event_phase_code`
  - `item_criticality`
  - `agency_priority`
  - `geographic_scope` (e.g., parish or national)
  - `population_weight`, `urgency_weight`, `criticality_weight`, `chronology_weight`
  - `is_override_allowed`
  - `tenant_id`, effective dates, status

## 2.5 `allocation_limit`
- Purpose: Per-agency/event allocation caps.
- Key fields:
  - `event_id`, `agency_id`, `item_category_id`
  - `max_qty`, `max_value`, `currency_code`
  - `tenant_id`
  - effective dates, status

## 2.6 `user_tenant_role`
- Purpose: Enforce tenant-scoped role assignments.
- Composite PK:
  - `tenant_id`, `user_id`, `role_id`
- Behavior:
  - Reconciles `tenant_user` + `user_role` into explicit scoped assignment.

## 2.7 `item_category_baseline_rate`
- Purpose: Category-level baseline rates for stale-data burn fallback.
- Fields:
  - `category_id`, `event_phase_code`, `baseline_rate_per_hour`
  - `tenant_id` (nullable global)
  - effective dates, status

## 2.8 `mpf_criteria_weight`
- Purpose: MPF criteria and RAG weighting governance.
- Fields:
  - `criteria_code`, `criteria_desc`, `loe_objective`
  - `weight_value`
  - `tenant_id`, effective dates, status

## 3) Existing Table Extensions

## 3.1 `tenant`
- Add unique constraint on `tenant_code`.
- Expand valid type set to include v5.1 values: `SOCIAL_SERVICES`, `NGO`.

## 3.2 `event`, `event_phase`, `event_phase_config`, `event_phase_history`
- Extend phase checks to include `RECOVERY`.

## 3.3 `lead_time_config`
- Add `donor_id` to support Horizon-B donor lead times.
- Add Horizon-B donor/default consistency check.

## 3.4 `supplier`
- Add `trn_no`, `tcc_no` fields for compliance capture.
- Optional scope model: `tenant_id` + `is_global`.

## 3.5 `procurement`
- Expand status/method checks to include canonical v5.1 terminology while preserving backward compatibility.
- Keep `approval_threshold_tier` but align to `ref_approval_tier`.

## 3.6 `needs_list`
- Expand status checks to include explicit `MODIFIED`, `SUBMITTED`.
- Preserve legacy statuses for compatibility during transition.

## 4) Tenant Isolation and RLS

## 4.1 Session Contract
- App must set:
  - `SET app.tenant_ids = '1,2,...';`

## 4.2 Policy Rule
- For tenant-scoped tables:
  - `tenant_id = ANY(app.current_tenant_ids())`
  - optionally allow `tenant_id IS NULL` for global records where applicable.

## 4.3 Tables to enforce first
- Existing: `warehouse`, `tenant_config`, `tenant_user`, `tenant_warehouse`, `data_sharing_agreement`
- New: all policy/config tables carrying `tenant_id`

## 5) Compatibility and Migration Defaults
- Keep legacy status/method codes valid in checks during transition.
- Seed reference catalogs before any FK enforcement.
- Add new columns as nullable first, backfill, then harden constraints where safe.
- Do not drop existing operational columns in this phase.

