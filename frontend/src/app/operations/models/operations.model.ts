// Status code types
export type RequestStatusCode = 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8;
export type PackageStatusCode = 'A' | 'P' | 'D' | 'C';
export type ItemStatusCode = 'R' | 'P' | 'F';
export type UrgencyCode = 'C' | 'H' | 'M' | 'L';
export type EligibilityDecision = 'Y' | 'N';
export type AllocationSourceType = 'ON_HAND' | 'TRANSFER' | 'DONATION' | 'PROCUREMENT';
export type AllocationMethod = 'FEFO' | 'FIFO' | 'MIXED' | 'MANUAL';
export type AllocationItemStatus =
  | 'not_started'
  | 'partly_allocated'
  | 'fully_allocated'
  | 'unavailable'
  | 'complete';
export type OperationsEntityType = 'RELIEF_REQUEST' | 'REQUEST' | 'PACKAGE' | 'DISPATCH';

export interface RequestReferenceOption {
  value: number;
  label: string;
}

export interface RequestReferenceDataResponse {
  agencies: RequestReferenceOption[];
  events: RequestReferenceOption[];
  items: RequestReferenceOption[];
}

// Request
export interface RequestItem {
  item_id: number;
  item_code: string | null;
  item_name: string | null;
  request_qty: string;
  issue_qty: string;
  urgency_ind: UrgencyCode | null;
  rqst_reason_desc: string | null;
  required_by_date: string | null;
  status_code: ItemStatusCode | null;
}

export interface PackageSummary {
  reliefpkg_id: number;
  tracking_no: string | null;
  reliefrqst_id: number;
  agency_id: number | null;
  eligible_event_id: number | null;
  to_inventory_id: number | null;
  destination_warehouse_name: string | null;
  status_code: PackageStatusCode;
  status_label: string;
  dispatch_dtime: string | null;
  received_dtime: string | null;
  transport_mode: string | null;
  comments_text: string | null;
  version_nbr: number;
  execution_status: string | null;
  needs_list_id: number | null;
  compatibility_bridge: boolean;
}

export interface RequestSummary {
  reliefrqst_id: number;
  tracking_no: string | null;
  agency_id: number | null;
  agency_name: string | null;
  eligible_event_id: number | null;
  event_name: string | null;
  urgency_ind: UrgencyCode | null;
  status_code: RequestStatusCode;
  status_label: string;
  request_date: string | null;
  create_dtime: string | null;
  review_dtime: string | null;
  action_dtime: string | null;
  rqst_notes_text: string | null;
  review_notes_text: string | null;
  status_reason_desc: string | null;
  version_nbr: number;
  item_count: number;
  total_requested_qty: string;
  total_issued_qty: string;
  reliefpkg_id: number | null;
  package_tracking_no: string | null;
  package_status: PackageStatusCode | null;
  execution_status: string | null;
  needs_list_id: number | null;
  compatibility_bridge: boolean;
  request_mode: 'SELF' | 'SUBORDINATE' | 'ODPEM_BRIDGE' | null;
  authority_context: string | null;
}

export interface RequestDetailResponse extends RequestSummary {
  items: RequestItem[];
  packages: PackageSummary[];
}

export interface RequestListResponse {
  results: RequestSummary[];
}

// Create / Update payloads
export interface CreateRequestItemPayload {
  item_id: number;
  request_qty: string;
  urgency_ind?: UrgencyCode;
  rqst_reason_desc?: string;
  required_by_date?: string;
}

export interface CreateRequestPayload {
  agency_id: number;
  urgency_ind: UrgencyCode;
  eligible_event_id?: number | null;
  rqst_notes_text?: string;
  items: CreateRequestItemPayload[];
}

export interface UpdateRequestPayload {
  agency_id?: number;
  urgency_ind?: UrgencyCode;
  eligible_event_id?: number | null;
  rqst_notes_text?: string;
  items?: CreateRequestItemPayload[];
}

// Eligibility
export interface EligibilityDetailResponse extends RequestDetailResponse {
  decision_made: boolean;
  can_edit: boolean;
}

export interface EligibilityDecisionPayload {
  decision: EligibilityDecision;
  reason?: string;
}

// Package Fulfillment
export interface AllocationLine {
  item_id: number;
  inventory_id: number;
  batch_id: number;
  batch_no?: string | null;
  quantity: string;
  uom_code?: string | null;
  source_type: AllocationSourceType | string;
  source_record_id?: number | null;
  allocation_rank?: number;
  override_reason_code?: string | null;
  override_note?: string | null;
  rule_bypass_flag?: boolean;
  supervisor_approved_by?: string | null;
  supervisor_approved_at?: string | null;
}

export interface AllocationSummary {
  allocation_lines: AllocationLine[];
  reserved_stock_summary: {
    line_count: number;
    total_qty: string;
  };
  waybill_no: string | null;
}

export interface PackageDetailResponse {
  request: RequestSummary;
  package: PackageSummary | null;
  items: RequestItem[];
  allocation?: AllocationSummary;
  compatibility_only: boolean;
}

export interface PackageQueueItem extends RequestSummary {
  current_package: PackageSummary | null;
}

export interface PackageQueueResponse {
  results: PackageQueueItem[];
}

// Allocation Options
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
  item_id: number;
  item_code?: string | null;
  item_name?: string | null;
  request_qty: string;
  issue_qty: string;
  remaining_qty: string;
  urgency_ind: UrgencyCode | null;
  candidates: AllocationCandidate[];
  suggested_allocations: SuggestedAllocationLine[];
  remaining_after_suggestion: string;
  can_expire_flag: boolean;
  issuance_order: 'FEFO' | 'FIFO' | string;
  compliance_markers: string[];
  override_required: boolean;
}

export interface AllocationOptionsResponse {
  request: RequestSummary;
  items: AllocationItemGroup[];
}

// Allocation Commit
export interface AllocationSelectionPayload {
  item_id: number;
  inventory_id: number;
  batch_id: number;
  quantity: string | number;
  source_type?: AllocationSourceType | string;
  source_record_id?: number | null;
  uom_code?: string | null;
}

export interface AllocationCommitPayload {
  to_inventory_id?: number;
  transport_mode?: string;
  comments_text?: string;
  allocations: AllocationSelectionPayload[];
}

export interface AllocationCommitResponse {
  status: 'COMMITTED' | 'PENDING_OVERRIDE_APPROVAL';
  reliefrqst_id: number;
  reliefpkg_id: number;
  request_tracking_no: string;
  package_tracking_no: string;
  override_required: boolean;
  override_markers: string[];
  allocation_lines: AllocationLine[];
}

export interface OverrideApprovalPayload {
  allocations: AllocationSelectionPayload[];
  override_reason_code: string;
  override_note: string;
}

// Dispatch
export interface DispatchTransportSummary {
  driver_name: string | null;
  driver_license_no: string | null;
  vehicle_id: string | null;
  vehicle_registration: string | null;
  vehicle_type: string | null;
  transport_mode: string | null;
  departure_dtime: string | null;
  estimated_arrival_dtime: string | null;
  transport_notes: string | null;
  route_override_reason: string | null;
}

export interface DispatchRecordSummary {
  dispatch_id: number;
  dispatch_no: string | null;
  status_code: string | null;
  status_label: string | null;
  dispatch_at: string | null;
  dispatched_by_id: string | null;
  source_warehouse_id: number | null;
  destination_tenant_id: number | null;
  destination_agency_id: number | null;
  transport: DispatchTransportSummary | null;
}

export interface DispatchQueueItem extends PackageSummary {
  request_tracking_no?: string | null;
  agency_name?: string | null;
  event_name?: string | null;
  request?: RequestSummary | null;
  dispatch?: DispatchRecordSummary | null;
}

export interface DispatchQueueResponse {
  results: DispatchQueueItem[];
}

export interface DispatchDetailResponse extends PackageSummary {
  request: RequestSummary;
  dispatch?: DispatchRecordSummary | null;
  allocation?: AllocationSummary;
  waybill: WaybillResponse | null;
}

export interface DispatchHandoffPayload {
  transport_mode?: string;
  driver_name?: string;
  vehicle_id?: string;
  vehicle_registration?: string;
  vehicle_type?: string;
  departure_dtime?: string;
  estimated_arrival_dtime?: string;
  transport_notes?: string;
}

export interface DispatchHandoffResponse {
  status: 'DISPATCHED';
  reliefrqst_id: number;
  reliefpkg_id: number;
  request_tracking_no: string;
  package_tracking_no: string;
  waybill_no: string;
  waybill_payload: WaybillPayload;
  waybill_artifact_mode?: string;
  dispatched_rows: AllocationLine[];
}

// Waybill
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
  agency_id?: number | null;
  event_id?: number | null;
  event_name?: string | null;
  source_warehouse_ids?: number[];
  source_warehouse_names?: string[];
  destination_warehouse_id?: number | null;
  destination_warehouse_name?: string | null;
  actor_user_id?: string | null;
  dispatch_dtime?: string | null;
  transport_mode?: string | null;
  line_items?: WaybillLineItem[];
}

export interface WaybillResponse {
  waybill_no: string;
  waybill_payload: WaybillPayload;
  persisted: boolean;
  artifact_mode?: string;
  derived_from_dispatch_record?: boolean;
  compatibility_bridge?: boolean;
}

// Constants
export const URGENCY_OPTIONS: readonly { value: UrgencyCode; label: string; hint: string }[] = [
  { value: 'C', label: 'Critical', hint: 'Immediate action required.' },
  { value: 'H', label: 'High', hint: 'Prioritize for urgent dispatch.' },
  { value: 'M', label: 'Medium', hint: 'Standard operational urgency.' },
  { value: 'L', label: 'Low', hint: 'Can be scheduled after higher-priority work.' },
];

// Task / Notification
export type TaskStatus = 'PENDING' | 'IN_PROGRESS' | 'COMPLETED' | 'DISMISSED';
export type OperationsTaskSource = 'QUEUE_ASSIGNMENT' | 'NOTIFICATION';

export interface OperationsTask {
  id: number;
  source: OperationsTaskSource;
  task_type: string;
  title: string;
  description: string;
  status: TaskStatus;
  priority: UrgencyCode | null;
  related_entity_type: OperationsEntityType | null;
  related_entity_id: number | null;
  created_at: string;
  due_date: string | null;
  assigned_to: string | null;
  queue_code: string | null;
}

export interface OperationsTaskListResponse {
  queue_assignments: OperationsTask[];
  notifications: OperationsTask[];
  results: OperationsTask[];
}

// Receipt Confirmation
export type ReceiptStatusCode = 'RECEIVED';

export interface ReceiptConfirmationPayload {
  received_by_name: string;
  receipt_notes?: string;
  beneficiary_delivery_ref?: string;
}

export interface ReceiptArtifact {
  receipt_status_code: ReceiptStatusCode;
  received_by_user_id: string | null;
  received_by_name: string;
  received_at: string;
  receipt_notes: string | null;
  beneficiary_delivery_ref: string | null;
}

export interface ReceiptConfirmationResponse {
  status: ReceiptStatusCode;
  reliefpkg_id: number;
  package_tracking_no: string | null;
  receipt: ReceiptArtifact;
}

export const OVERRIDE_REASON_OPTIONS: readonly { value: string; label: string }[] = [
  { value: 'FEFO_BYPASS', label: 'FEFO / FIFO bypass' },
  { value: 'SHORT_PICK', label: 'Short pick / limited compliant stock' },
  { value: 'SOURCE_EXCEPTION', label: 'Source exception' },
  { value: 'OTHER', label: 'Other' },
];
