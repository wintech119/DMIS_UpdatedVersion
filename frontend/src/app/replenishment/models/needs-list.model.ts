import { EventPhase, SeverityLevel, FreshnessLevel } from '../models/stock-status.model';

export interface NeedsListItem {
  item_id: number;
  item_name?: string;
  warehouse_id?: number;             // NEW for multi-warehouse
  warehouse_name?: string;           // NEW for multi-warehouse
  available_qty: number;
  inbound_strict_qty: number;
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

export interface NeedsListResponse {
  event_id: number;
  phase: EventPhase;
  warehouse_ids?: number[];          // NEW (array for multi-warehouse)
  warehouses?: WarehouseInfo[];      // NEW (warehouse metadata)
  items: NeedsListItem[];
  as_of_datetime: string;
  planning_window_days?: number;
  warnings?: string[];
  needs_list_id?: string;
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
  return_reason?: string | null;
  reject_reason?: string | null;
}

export type NeedsListStatus =
  | 'DRAFT'
  | 'SUBMITTED'
  | 'UNDER_REVIEW'
  | 'APPROVED'
  | 'REJECTED'
  | 'RETURNED'
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
  type: 'REJECTED' | 'RETURNED' | 'CANCELLED' | 'SUPERSEDED';
  reason: string | null;
  actor: string | null;
  timestamp: string | null;
  fromStep: TrackerStepId;
}
