import { EventPhase, SeverityLevel } from '../models/stock-status.model';

export interface NeedsListItem {
  item_id: number;
  item_name?: string;
  item_code?: string;
  uom_code?: string;
  warehouse_id?: number;             // NEW for multi-warehouse
  warehouse_name?: string;           // NEW for multi-warehouse
  available_qty: number;
  inbound_strict_qty: number;
  inbound_transfer_qty?: number;
  inbound_donation_qty?: number;
  inbound_procurement_qty?: number;
  burn_rate_per_hour: number;
  required_qty?: number;
  computed_required_qty?: number;
  gap_qty: number;
  time_to_stockout?: string | number;
  time_to_stockout_hours?: number;
  severity?: SeverityLevel;
  horizon?: HorizonAllocation;
  confidence?: ConfidenceInfo;
  freshness?: FreshnessInfo;
  warnings?: string[];
  override_reason?: string;
  override_updated_by?: string;
  override_updated_at?: string;
  review_comment?: string;
  review_updated_by?: string;
  review_updated_at?: string;
  fulfilled_qty?: number;
  fulfillment_status?: string | null;
  procurement?: ProcurementInfo;
  triggers?: {
    activate_B: boolean;
    activate_C: boolean;
    activate_all: boolean;
  };
  freshness_state?: string;
  procurement_status?: string | null;
}

export interface HorizonAllocation {
  A: { recommended_qty: number | null };
  B: { recommended_qty: number | null };
  C: { recommended_qty: number | null };
}

export interface ConfidenceInfo {
  level: string;
  reasons: string[];
}

export interface FreshnessInfo {
  state: string;
  age_hours: number | null;
  inventory_as_of: string | null;
}

export interface ProcurementInfo {
  recommended_qty: number;
  est_unit_cost?: number | null;
  est_total_cost?: number | null;
  lead_time_hours_default: number;
  approval?: {
    tier: string;
    approver_role: string;
    methods_allowed: string[];
  };
  gojep_note?: {
    label: string;
    url: string;
  };
}

export interface WarehouseInfo {
  warehouse_id: number;
  warehouse_name: string;
}

export interface ApprovalSummary {
  total_required_qty: number;
  total_estimated_cost: number | null;
  approval?: {
    tier: string;
    approver_role: string;
    methods_allowed: string[];
  };
  warnings?: string[];
  rationale?: string;
  escalation_required?: boolean;
}

export interface ReviewReminderInfo {
  pending_hours: number;
  reminder_sent_at: string;
  escalation_recommended: boolean;
}

export type NeedsListSummaryStatus =
  | 'DRAFT'
  | 'MODIFIED'
  | 'RETURNED'
  | 'PENDING_APPROVAL'
  | 'APPROVED'
  | 'REJECTED'
  | 'IN_PROGRESS'
  | 'FULFILLED'
  | 'SUPERSEDED'
  | 'CANCELLED';

export interface HorizonSummaryBucket {
  count: number;
  estimated_value: number;
}

export interface ExternalUpdateSummary {
  item_name: string;
  original_qty: number;
  covered_qty: number;
  remaining_qty: number;
  source_type: 'DONATION' | 'TRANSFER' | 'PROCUREMENT';
  source_reference: string;
  updated_at: string | null;
}

export interface NeedsListSummary {
  id: string;
  reference_number: string;
  warehouse: {
    id: number | null;
    name: string;
    code: string;
  };
  event: {
    id: number | null;
    name: string;
    phase: EventPhase;
  };
  selected_method?: 'A' | 'B' | 'C' | null;
  status: NeedsListSummaryStatus;
  total_items: number;
  fulfilled_items: number;
  remaining_items: number;
  horizon_summary: {
    horizon_a: HorizonSummaryBucket;
    horizon_b: HorizonSummaryBucket;
    horizon_c: HorizonSummaryBucket;
  };
  submitted_at: string | null;
  approved_at: string | null;
  last_updated_at: string | null;
  superseded_by_id: string | null;
  supersedes_id: string | null;
  has_external_updates: boolean;
  external_update_summary: ExternalUpdateSummary[];
  data_version?: string;
  created_by: {
    id: number | null;
    name: string;
  };
}

export interface MySubmissionsResponse {
  count: number;
  next: string | null;
  previous: string | null;
  results: NeedsListSummary[];
}

export interface NeedsListFulfillmentSource {
  source_type: 'DONATION' | 'TRANSFER' | 'PROCUREMENT' | 'NEEDS_LIST_LINE';
  source_id: number | null;
  source_reference: string;
  quantity: number;
  status: string;
  date: string | null;
  eta?: string | null;
}

export interface NeedsListFulfillmentLine {
  id: number | null;
  item: {
    id: number | null;
    name: string;
    uom: string;
  };
  original_qty: number;
  covered_qty: number;
  remaining_qty: number;
  horizon: 'A' | 'B' | 'C';
  fulfillment_sources: NeedsListFulfillmentSource[];
  total_coverage: number;
  is_fully_covered: boolean;
}

export interface NeedsListFulfillmentSourcesResponse {
  needs_list_id: string;
  lines: NeedsListFulfillmentLine[];
}

export interface NeedsListSummaryVersionResponse {
  needs_list_id: string;
  status: NeedsListSummaryStatus;
  last_updated_at: string | null;
  data_version: string;
}

export interface NeedsListResponse {
  event_id: number;
  event_name?: string;
  phase: EventPhase;
  warehouse_id?: number;             // Legacy single-warehouse workflow response
  warehouse_ids?: number[];          // NEW (array for multi-warehouse)
  warehouses?: WarehouseInfo[];      // NEW (warehouse metadata)
  items: NeedsListItem[];
  as_of_datetime: string;
  planning_window_days?: number;
  warnings?: string[];
  needs_list_id?: string;
  needs_list_no?: string;
  status?: NeedsListStatus;
  approval_summary?: ApprovalSummary;
  created_by?: string | null;
  created_at?: string | null;
  updated_by?: string | null;
  updated_at?: string | null;
  submitted_by?: string | null;
  submitted_at?: string | null;
  reviewed_by?: string | null;
  reviewed_at?: string | null;
  review_comment?: string | null;
  approved_by?: string | null;
  approved_at?: string | null;
  escalated_by?: string | null;
  escalated_at?: string | null;
  escalation_reason?: string | null;
  return_reason_code?: string | null;
  return_reason?: string | null;
  reject_reason?: string | null;
  review_reminder?: ReviewReminderInfo;
  selected_method?: 'A' | 'B' | 'C';
  selected_item_keys?: string[];
  superseded_by?: string | null;
  superseded_at?: string | null;
  superseded_by_actor?: string | null;
  superseded_by_needs_list_id?: string | null;
  supersedes_needs_list_ids?: string[];
  supersede_reason?: string | null;
}

export type NeedsListStatus =
  | 'DRAFT'
  | 'MODIFIED'
  | 'SUBMITTED'
  | 'PENDING_APPROVAL'
  | 'PENDING'
  | 'UNDER_REVIEW'
  | 'APPROVED'
  | 'REJECTED'
  | 'RETURNED'
  | 'ESCALATED'
  | 'IN_PREPARATION'
  | 'DISPATCHED'
  | 'RECEIVED'
  | 'COMPLETED'
  | 'IN_PROGRESS'
  | 'FULFILLED'
  | 'CANCELLED'
  | 'SUPERSEDED';

// Approval Status Tracker types
export type TrackerStepId = 'DRAFT' | 'PENDING_APPROVAL' | 'APPROVED' | 'IN_PROGRESS' | 'FULFILLED';

export type TrackerStepState = 'completed' | 'active' | 'pending' | 'rejected' | 'returned' | 'cancelled';

export interface TrackerStep {
  id: TrackerStepId;
  label: string;
  icon: string;
  state: TrackerStepState;
  timestamp: string | null;
  actor: string | null;
  comment: string | null;
}

export interface TrackerBranch {
  type: 'REJECTED' | 'RETURNED' | 'ESCALATED' | 'CANCELLED' | 'SUPERSEDED';
  reason: string | null;
  actor: string | null;
  timestamp: string | null;
  fromStep: TrackerStepId;
}

// ── Transfer Draft Models (Horizon A) ─────────────────────────────────────

export interface TransferDraftItem {
  item_id: number;
  item_name: string;
  uom_code: string;
  item_qty: number;
}

export interface TransferDraft {
  transfer_id: number;
  from_warehouse: { id: number; name: string };
  to_warehouse: { id: number; name: string };
  status: string;
  transfer_date: string | null;
  reason: string | null;
  created_by: string | null;
  created_at: string | null;
  items: TransferDraftItem[];
}

export interface TransferDraftsResponse {
  needs_list_id: string;
  transfers: TransferDraft[];
  warnings?: string[];
}

// ── Donation Models (Horizon B) ───────────────────────────────────────────

export interface DonationLineItem {
  item_id: number;
  item_name: string;
  uom: string;
  required_qty: number;
  allocated_qty: number;
  available_donations: { donation_id: number; donor_name: string; available_qty: number }[];
}

export interface DonationsResponse {
  needs_list_id: string;
  lines: DonationLineItem[];
  warnings?: string[];
}

// ── Procurement Models (Horizon C) ────────────────────────────────────────

export interface ProcurementLineItem {
  item_id: number;
  item_name: string;
  uom: string;
  required_qty: number;
  est_unit_cost: number | null;
  est_total_cost: number | null;
}

export interface ProcurementExportResponse {
  needs_list_id: string;
  format: string;
  items: ProcurementLineItem[];
}
