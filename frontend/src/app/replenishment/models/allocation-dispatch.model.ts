export type ExecutionSelectedMethod = 'FEFO' | 'FIFO' | 'MIXED' | 'MANUAL';

export type ExecutionStatus =
  | 'PREPARING'
  | 'PENDING_OVERRIDE_APPROVAL'
  | 'COMMITTED'
  | 'DISPATCHED'
  | 'RECEIVED'
  | 'CANCELLED';

export type AllocationSourceType = 'ON_HAND' | 'TRANSFER' | 'DONATION' | 'PROCUREMENT';

export type ExecutionUrgencyCode = 'C' | 'H' | 'M' | 'L';

export interface ReservedStockSummaryLine {
  item_id: number;
  batch_id: number | null;
  reserved_qty: string;
}

export interface ReservedStockSummary {
  line_count: number;
  total_qty: string;
  by_item_batch: ReservedStockSummaryLine[];
}

export interface AllocationCommittedLine {
  item_id: number;
  inventory_id: number;
  batch_id: number;
  batch_no?: string | null;
  quantity: string;
  uom_code?: string | null;
  source_type: AllocationSourceType | string;
  source_record_id?: number | null;
  needs_list_item_id?: number | null;
  allocation_rank?: number;
  override_reason_code?: string | null;
  override_note?: string | null;
  rule_bypass_flag?: boolean;
  supervisor_approved_by?: string | null;
  supervisor_approved_at?: string | null;
}

export interface LinkedSourceReference {
  source_type: AllocationSourceType | string;
  source_record_id: number;
}

export interface AllocationCandidate {
  batch_id: number;
  inventory_id: number;
  item_id: number;
  batch_no?: string | null;
  batch_date?: string | null;
  expiry_date?: string | null;
  usable_qty: string;
  reserved_qty: string;
  available_qty: string;
  uom_code?: string | null;
  source_type: AllocationSourceType | string;
  source_record_id?: number | null;
  warehouse_name?: string | null;
  can_expire_flag: boolean;
  issuance_order: 'FEFO' | 'FIFO' | string;
  item_code?: string | null;
  item_name?: string | null;
  compliance_markers?: string[];
}

export interface SuggestedAllocationLine {
  item_id: number;
  inventory_id: number;
  batch_id: number;
  batch_no?: string | null;
  source_type: AllocationSourceType | string;
  source_record_id?: number | null;
  uom_code?: string | null;
  quantity: string;
}

export interface AllocationItemGroup {
  needs_list_item_id: number;
  item_id: number;
  item_code?: string | null;
  item_name?: string | null;
  criticality_level?: string | null;
  criticality_rank: number;
  required_qty: string;
  fulfilled_qty: string;
  reserved_qty: string;
  remaining_qty: string;
  remaining_after_suggestion: string;
  item_uom_code?: string | null;
  can_expire_flag: boolean;
  issuance_order: 'FEFO' | 'FIFO' | string;
  candidates: AllocationCandidate[];
  suggested_allocations: SuggestedAllocationLine[];
  compliance_markers: string[];
  override_required: boolean;
}

export interface AllocationOptionsResponse {
  needs_list: {
    needs_list_id: number;
    needs_list_no?: string | null;
    warehouse_id?: number | null;
    event_id?: number | null;
    status_code?: string | null;
    submitted_at?: string | null;
    create_dtime?: string | null;
  };
  items: AllocationItemGroup[];
  flat_candidates: (AllocationCandidate & { item_id: number })[];
}

export interface AllocationSelectionPayload {
  item_id: number;
  inventory_id: number;
  batch_id: number;
  quantity: string | number;
  source_type: AllocationSourceType | string;
  source_record_id?: number | null;
  uom_code?: string | null;
  needs_list_item_id?: number | null;
}

export interface AllocationCommitPayload {
  allocations: AllocationSelectionPayload[];
  selected_method?: ExecutionSelectedMethod;
  agency_id?: number;
  urgency_ind?: ExecutionUrgencyCode;
  transport_mode?: string;
  request_notes?: string;
  package_comments?: string;
  override_reason_code?: string;
  override_note?: string;
}

export interface AllocationOverrideApprovalPayload {
  allocations?: AllocationSelectionPayload[];
  selected_method?: ExecutionSelectedMethod;
  override_reason_code: string;
  override_note: string;
}

export interface WaybillLineItem {
  item_id: number;
  inventory_id: number;
  batch_id: number;
  batch_no?: string | null;
  quantity: string;
  uom_code?: string | null;
  source_type?: AllocationSourceType | string;
  source_record_id?: number | null;
}

export interface WaybillPayload {
  waybill_no: string;
  request_tracking_no?: string | null;
  package_tracking_no?: string | null;
  needs_list_id?: number | string;
  needs_list_no?: string | null;
  agency_id?: number | null;
  event_id?: number | null;
  event_name?: string | null;
  source_warehouse_ids?: number[];
  source_warehouse_names?: string[];
  source_warehouse_id?: number | null;
  destination_warehouse_id?: number | null;
  destination_warehouse_name?: string | null;
  actor_user_id?: string | null;
  dispatch_dtime?: string | null;
  transport_mode?: string | null;
  line_items?: WaybillLineItem[];
}

export interface WaybillResponse {
  needs_list_id: string;
  waybill_no: string;
  waybill_payload: WaybillPayload;
  request_tracking_no?: string | null;
  package_tracking_no?: string | null;
}

export const EXECUTION_URGENCY_OPTIONS: readonly { value: ExecutionUrgencyCode; label: string; hint: string }[] = [
  { value: 'C', label: 'Critical', hint: 'Immediate action is required.' },
  { value: 'H', label: 'High', hint: 'Prioritize for urgent dispatch planning.' },
  { value: 'M', label: 'Medium', hint: 'Standard operational urgency.' },
  { value: 'L', label: 'Low', hint: 'Can be scheduled after higher-priority work.' },
];

export const EXECUTION_OVERRIDE_REASON_OPTIONS: readonly { value: string; label: string }[] = [
  { value: 'FEFO_BYPASS', label: 'FEFO / FIFO bypass' },
  { value: 'SHORT_PICK', label: 'Short pick / limited compliant stock' },
  { value: 'SOURCE_EXCEPTION', label: 'Source exception' },
  { value: 'OTHER', label: 'Other' },
];
