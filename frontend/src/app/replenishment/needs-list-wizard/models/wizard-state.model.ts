import { EventPhase } from '../../models/stock-status.model';
import { NeedsListResponse } from '../../models/needs-list.model';

export interface WizardState {
  // Step 1 data
  event_id?: number;
  warehouse_ids?: number[];          // Array for multi-selection
  phase?: EventPhase;
  as_of_datetime?: string;

  // Step 2 data (from preview-multi API)
  previewResponse?: NeedsListResponse;
  adjustments: Record<string, ItemAdjustment>;  // key: "{item_id}_{warehouse_id}"

  // Step 3 data
  draft_ids?: string[];              // Array if creating multiple drafts (one per warehouse)
  notes?: string;
}

export interface ItemAdjustment {
  item_id: number;
  warehouse_id: number;
  original_qty: number;
  adjusted_qty: number;
  reason: AdjustmentReason;
  notes?: string;
}

export type AdjustmentReason =
  | 'PARTIAL_COVERAGE'
  | 'DEMAND_ADJUSTED'
  | 'PRIORITY_CHANGE'
  | 'BUDGET_CONSTRAINT'
  | 'OTHER';

export const ADJUSTMENT_REASON_LABELS: Record<AdjustmentReason, string> = {
  PARTIAL_COVERAGE: 'Partial Coverage',
  DEMAND_ADJUSTED: 'Demand Adjusted',
  PRIORITY_CHANGE: 'Priority Change',
  BUDGET_CONSTRAINT: 'Budget Constraint',
  OTHER: 'Other'
};
