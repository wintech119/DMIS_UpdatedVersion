// Status code types
export type RequestStatusCode =
  | 'DRAFT'
  | 'SUBMITTED'
  | 'UNDER_ELIGIBILITY_REVIEW'
  | 'APPROVED_FOR_FULFILLMENT'
  | 'PARTIALLY_FULFILLED'
  | 'FULFILLED'
  | 'INELIGIBLE'
  | 'REJECTED'
  | 'CANCELLED';

// Legacy single-char package codes used by older components and legacy payloads.
export type LegacyPackageStatusCode = 'A' | 'P' | 'D' | 'C' | 'V';
// Extended codes introduced for staged fulfillment and explicit state names.
export type StagedPackageStatusCode =
  | 'DRAFT'
  | 'PENDING_OVERRIDE_APPROVAL'
  | 'REJECTED'
  | 'COMMITTED'
  | 'CONSOLIDATING'
  | 'READY_FOR_PICKUP'
  | 'READY_FOR_DISPATCH'
  | 'SPLIT'
  | 'DISPATCHED'
  | 'RECEIVED'
  | 'CANCELLED';
export type PackageStatusCode = LegacyPackageStatusCode | StagedPackageStatusCode;

// Staged fulfillment routing decision for a relief package.
export type FulfillmentMode = 'DIRECT' | 'PICKUP_AT_STAGING' | 'DELIVER_FROM_STAGING';

// Rolled-up state of all consolidation legs for a staged package.
export type ConsolidationStatus =
  | 'AWAITING_LEGS'
  | 'LEGS_IN_TRANSIT'
  | 'PARTIALLY_RECEIVED'
  | 'ALL_RECEIVED'
  | 'PARTIAL_RELEASE_REQUESTED';

// Why the backend selected a particular staging warehouse.
export type StagingSelectionBasis =
  | 'SAME_PARISH'
  | 'PROXIMITY_MATRIX'
  | 'ALPHABETICAL_FALLBACK'
  | 'MANUAL_OVERRIDE';

// Lifecycle of a single consolidation leg from a source warehouse into the staging hub.
export type ConsolidationLegStatus =
  | 'PLANNED'
  | 'IN_TRANSIT'
  | 'RECEIVED_AT_STAGING'
  | 'CANCELLED';

export type ItemStatusCode = 'R' | 'P' | 'F';
export type UrgencyCode = 'C' | 'H' | 'M' | 'L';
export type EligibilityDecision = 'Y' | 'APPROVED' | 'REJECTED' | 'INELIGIBLE';
export type AllocationSourceType = 'ON_HAND' | 'TRANSFER' | 'DONATION' | 'PROCUREMENT';
export type AllocationMethod = 'FEFO' | 'FIFO' | 'MIXED' | 'MANUAL';
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

export interface PackageLegSummary {
  total_legs: number;
  planned_legs: number;
  in_transit_legs: number;
  received_legs: number;
  cancelled_legs: number;
  all_received: boolean;
}

export interface PackageSplitChild {
  package_id: number;
  package_no: string | null;
  status_code: PackageStatusCode | string;
}

export interface PackageSplitReferences {
  split_from_package_id: number | null;
  split_from_package_no: string | null;
  split_children: PackageSplitChild[];
}

export interface PackageSummary {
  reliefpkg_id: number;
  tracking_no: string | null;
  reliefrqst_id: number;
  agency_id: number | null;
  eligible_event_id: number | null;
  source_warehouse_id: number | null;
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
  // Staged fulfillment fields (optional for backwards compatibility with legacy
  // callers that still type objects as PackageSummary without staging data).
  fulfillment_mode?: FulfillmentMode;
  staging_warehouse_id?: number | null;
  recommended_staging_warehouse_id?: number | null;
  staging_selection_basis?: StagingSelectionBasis | null;
  staging_override_reason?: string | null;
  consolidation_status?: ConsolidationStatus | null;
  effective_dispatch_source_warehouse_id?: number | null;
  leg_summary?: PackageLegSummary | null;
  split?: PackageSplitReferences | null;
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
  request_mode: 'SELF' | 'FOR_SUBORDINATE' | 'ODPEM_BRIDGE' | null;
  authority_context: string | null;
  requesting_tenant_id: number | null;
  requesting_agency_id: number | null;
  beneficiary_tenant_id: number | null;
  beneficiary_agency_id: number | null;
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
export interface EligibilityDecisionMetadata {
  decision_code: 'APPROVED' | 'REJECTED' | 'INELIGIBLE';
  decision_reason: string | null;
  decided_by_user_id: string | null;
  decided_by_role_code: string | null;
  decided_at: string | null;
}

export interface EligibilityDetailResponse extends RequestDetailResponse {
  decision_made: boolean;
  can_edit: boolean;
  eligibility_decision: EligibilityDecisionMetadata | null;
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
  item_code?: string | null;
  item_name?: string | null;
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

export interface AlternateWarehouseOption {
  warehouse_id: number;
  warehouse_name: string;
  available_qty: string;
  suggested_qty: string;
  can_fully_cover: boolean;
}

/**
 * Batch detail carried inside a {@link WarehouseAllocationCard}. These are
 * pre-sorted by the item's FEFO/FIFO rule on the server, so the frontend never
 * re-sorts.
 */
export interface WarehouseAllocationBatch {
  batch_id: number;
  inventory_id: number;
  batch_no?: string | null;
  batch_date?: string | null;
  expiry_date?: string | null;
  available_qty: string;
  usable_qty: string;
  reserved_qty: string;
  uom_code?: string | null;
  source_type: AllocationSourceType | string;
  source_record_id?: number | null;
}

/**
 * Response shape for the non-terminal abandon-draft endpoint.
 */
export interface PackageAbandonDraftResponse {
  reliefpkg_id?: number;
  package_id?: number;
  status?: string;
  status_code?: string;
  abandoned: boolean;
  request_status: string;
  reason: string | null;
  previous_status_code?: string;
  released?: {
    line_count: number;
    total_qty: string;
  };
}

/**
 * Backend-computed rationale for a warehouse card's rank position. Dates are
 * raw ISO strings so existing pipes (DatePipe) format them at render time.
 */
export interface RankingContext {
  basis: 'FEFO' | 'FIFO' | string;
  top_batch_id: number | null;
  top_batch_no: string | null;
  top_batch_date: string | null;
  top_expiry_date: string | null;
}

/**
 * One warehouse's contribution toward an item, as the backend pre-ranked and
 * pre-filled it for the Stock-Aware step. Every warehouse card in the payload
 * represents a warehouse that currently holds stock of the item — the
 * frontend renders them stacked in the order delivered.
 */
export interface WarehouseAllocationCard {
  warehouse_id: number;
  warehouse_name: string;
  /** Zero-based rank within the FEFO/FIFO-ordered list of cards. */
  rank: number;
  /** True when this warehouse is the FEFO/FIFO-recommended source (typically rank 0). */
  recommended?: boolean;
  issuance_order: 'FEFO' | 'FIFO' | string;
  /** Total available usable stock for this item at this warehouse. */
  total_available: string;
  /**
   * Available qty after subtracting the operator's draft allocations. Absent on
   * the initial GET; populated on POST preview responses. Falls back to
   * {@link total_available} when missing.
   */
  allocatable_available_qty?: string;
  /** Server-suggested greedy fill against the item's remaining requested qty. */
  suggested_qty: string;
  /** Ranking rationale metadata; null when backend omits it. */
  ranking_context?: RankingContext | null;
  batches: WarehouseAllocationBatch[];
  /**
   * Client-only synthetic marker. Set to `true` when the frontend has added
   * a card for an alternate warehouse that the user selected via
   * "Add next warehouse" but the backend allocation-preview POST has not yet
   * returned its batch detail. These cards render with a subtle "loading"
   * visual cue and a trimmed metric strip until the preview populates.
   *
   * NEVER set by the backend — the normalizer leaves it undefined. Intended
   * only to differentiate real, pre-ranked cards from in-flight placeholders.
   */
  pending?: boolean;
}

export interface AllocationItemGroup {
  item_id: number;
  item_code?: string | null;
  item_name?: string | null;
  request_qty: string;
  issue_qty: string;
  remaining_qty: string;
  /**
   * True when the backend reports that this item is already fully issued
   * (`issue_qty >= request_qty`). The Stock-Aware Selection step uses this
   * flag to show an "Already Issued" state and disable the qty inputs
   * instead of letting the operator run into a misleading "Over-Allocated"
   * validation error.
   */
  fully_issued?: boolean;
  urgency_ind: UrgencyCode | null;
  candidates: AllocationCandidate[];
  suggested_allocations: SuggestedAllocationLine[];
  remaining_after_suggestion: string;
  can_expire_flag: boolean;
  issuance_order: 'FEFO' | 'FIFO' | string;
  compliance_markers: string[];
  override_required: boolean;
  /** Source warehouse for this item (set when using per-item warehouse override). */
  source_warehouse_id?: number | null;
  /** Ranked/selected warehouse IDs currently active for this item. */
  selected_warehouse_ids?: number[];
  /** Backend-recommended primary warehouse, when a ranked option exists. */
  recommended_warehouse_id?: number | null;
  /** Data-integrity issue for the active source warehouse aggregate, if any. */
  stock_integrity_issue?: string | null;
  /** Quantity still needed after using this warehouse only. */
  remaining_shortfall_qty: string;
  /** Backend hint that the operator should add another warehouse for this item. */
  continuation_recommended: boolean;
  /** Alternate warehouses that could cover the remaining shortfall. */
  alternate_warehouses: AlternateWarehouseOption[];
  /**
   * Ranked, pre-suggested list of warehouses that currently hold stock of
   * this item. Drives the Stock-Aware step's stacked card layout. Order is
   * FEFO/FIFO per the item's issuance rule.
   */
  warehouse_cards: WarehouseAllocationCard[];
  /** Total quantity already chosen across draft selections (POST preview only). */
  draft_selected_qty?: string;
  /** Remaining qty after subtracting draft selections (POST preview only). */
  effective_remaining_qty?: string;
}

export interface ItemAllocationPreviewPayload {
  source_warehouse_id?: number;
  additional_warehouse_ids?: number[];
  draft_allocations: SuggestedAllocationLine[];
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
  source_warehouse_id?: number;
  to_inventory_id?: number;
  transport_mode?: string;
  comments_text?: string;
  fulfillment_mode?: FulfillmentMode;
  staging_warehouse_id?: number | null;
  staging_override_reason?: string | null;
  override_reason_code?: string;
  override_note?: string;
  allocations: AllocationSelectionPayload[];
}

export interface AllocationCommitResponse {
  status:
    | 'COMMITTED'
    | 'PENDING_OVERRIDE_APPROVAL'
    | 'CONSOLIDATING'
    | 'READY_FOR_PICKUP'
    | 'READY_FOR_DISPATCH';
  reliefrqst_id: number;
  reliefpkg_id: number;
  request_tracking_no: string;
  package_tracking_no: string;
  override_required: boolean;
  override_markers: string[];
  allocation_lines: AllocationLine[];
  override_status_code?: 'APPROVED' | null;
  action_id?: string | number | null;
  audit_log_id?: string | number | null;
}

export interface OverrideApprovalPayload {
  allocations?: AllocationSelectionPayload[];
  override_reason_code?: string;
  override_note?: string;
}

export interface OverrideReturnPayload {
  reason: string;
}

export interface OverrideRejectPayload {
  reason: string;
}

export interface OverrideReviewResponse {
  status: 'RETURNED_FOR_ADJUSTMENT' | 'REJECTED';
  reliefrqst_id: number;
  reliefpkg_id: number;
  override_status_code: 'RETURNED_FOR_ADJUSTMENT' | 'REJECTED';
  package_status_code: 'DRAFT' | 'REJECTED';
  request_status?: string | null;
  package?: PackageSummary | null;
  action_id?: string | number | null;
  audit_log_id?: string | number | null;
}

// Dispatch
export interface DispatchTransportSummary {
  driver_name: string | null;
  driver_license_last4: string | null;
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
  items?: RequestItem[];
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

export const TRANSPORT_MODE_OPTIONS: readonly { value: string; label: string }[] = [
  { value: 'TRUCK', label: 'Truck' },
  { value: 'VAN', label: 'Van' },
  { value: 'AIR', label: 'Air' },
  { value: 'BOAT', label: 'Boat' },
  { value: 'ROAD', label: 'Road' },
  { value: 'SEA', label: 'Sea' },
  { value: 'MOTORCYCLE', label: 'Motorcycle' },
  { value: 'OTHER', label: 'Other' },
];

export const OVERRIDE_REASON_OPTIONS: readonly { value: string; label: string }[] = [
  { value: 'FEFO_BYPASS', label: 'FEFO / FIFO bypass' },
  { value: 'SHORT_PICK', label: 'Short pick / limited compliant stock' },
  { value: 'SOURCE_EXCEPTION', label: 'Source exception' },
  { value: 'OTHER', label: 'Other' },
];

// Staged Fulfillment ──────────────────────────────────────────────

export const FULFILLMENT_MODE_OPTIONS: readonly {
  value: FulfillmentMode;
  label: string;
  hint: string;
}[] = [
  {
    value: 'DIRECT',
    label: 'Direct dispatch',
    hint: 'Ship straight from the source warehouse to the destination.',
  },
  {
    value: 'DELIVER_FROM_STAGING',
    label: 'Deliver from staging',
    hint: 'Consolidate items at a staging hub before onward delivery.',
  },
  {
    value: 'PICKUP_AT_STAGING',
    label: 'Pickup at staging',
    hint: 'Beneficiary collects the package directly from the staging hub.',
  },
];

export interface ConsolidationLegItem {
  leg_item_id: number;
  item_id: number;
  batch_id: number | null;
  quantity: string;
  source_type: AllocationSourceType | string;
  source_record_id: number | null;
  staging_batch_id: number | null;
  uom_code: string | null;
}

export interface ConsolidationLeg {
  leg_id: number;
  package_id: number;
  leg_sequence: number;
  source_warehouse_id: number;
  staging_warehouse_id: number;
  status_code: ConsolidationLegStatus;
  status_label: string;
  shadow_transfer_id: number | null;
  driver_name: string | null;
  /** Only the last 4 characters are persisted and returned by the backend. */
  driver_license_last4: string | null;
  vehicle_id: string | null;
  vehicle_registration: string | null;
  vehicle_type: string | null;
  transport_mode: string | null;
  transport_notes: string | null;
  dispatched_by_id: string | null;
  dispatched_at: string | null;
  departure_dtime: string | null;
  estimated_arrival_dtime: string | null;
  route_override_reason: string | null;
  expected_arrival_at: string | null;
  received_by_user_id: string | null;
  received_at: string | null;
  items: ConsolidationLegItem[];
  waybill_no: string | null;
}

export interface ConsolidationLegsResponse {
  package: PackageSummary;
  results: ConsolidationLeg[];
}

export interface ConsolidationLegDispatchPayload {
  driver_name: string;
  driver_license_last4?: string;
  vehicle_id?: string;
  vehicle_registration?: string;
  vehicle_type?: string;
  transport_mode?: string;
  transport_notes?: string;
  departure_dtime?: string;
  estimated_arrival_dtime?: string;
}

export interface ConsolidationLegDispatchResponse {
  status: 'IN_TRANSIT';
  package: PackageSummary;
  leg: ConsolidationLeg;
}

export interface ConsolidationLegReceivePayload {
  received_by_name?: string;
  receipt_notes?: string;
}

export interface ConsolidationLegReceiveResponse {
  status: 'RECEIVED_AT_STAGING';
  package: PackageSummary;
  leg: ConsolidationLeg;
}

export interface ConsolidationWaybillResponse {
  waybill_no: string;
  waybill_payload: WaybillPayload;
  persisted: boolean;
}

export interface StagingRecommendationResponse {
  reliefrqst_id: number;
  recommended_staging_warehouse_id: number | null;
  recommended_staging_warehouse_name: string | null;
  recommended_staging_parish_code: string | null;
  staging_selection_basis: StagingSelectionBasis | null;
  staging_hubs: StagingHubOption[];
}

export interface StagingHubOption {
  warehouse_id: number;
  warehouse_name: string;
  parish_code: string | null;
}

export interface PartialReleaseRequestPayload {
  reason: string;
}

export interface PartialReleaseRequestResponse {
  status: 'PARTIAL_RELEASE_REQUESTED';
  package: PackageSummary;
}

export interface PartialReleaseApprovePayload {
  approval_reason?: string;
}

export interface PartialReleaseApproveResponse {
  parent: PackageSummary;
  residual: PackageSummary | null;
  released: PackageSummary | null;
}

export interface PickupReleasePayload {
  collected_by_name: string;
  collected_by_id_ref?: string;
  released_by_name?: string;
  release_notes?: string;
}

export interface PickupReleaseResponse {
  status: 'RECEIVED';
  package: PackageSummary;
}

export interface PackageDraftPayload {
  source_warehouse_id?: number;
  to_inventory_id?: number;
  transport_mode?: string;
  comments_text?: string;
  allocations?: AllocationSelectionPayload[];
  fulfillment_mode?: FulfillmentMode;
  staging_warehouse_id?: number | null;
  recommended_staging_warehouse_id?: number | null;
  staging_override_reason?: string | null;
}

export interface PackageLockConflict {
  lock: string;
  lock_owner_user_id: string | null;
  lock_owner_role_code: string | null;
  lock_expires_at: string | null;
}

export interface PackageLockReleaseResponse {
  released: boolean;
  message: string;
  package_id: number | null;
  package_no: string | null;
  previous_lock_owner_user_id: string | null;
  previous_lock_owner_role_code: string | null;
  released_by_user_id: string | null;
  released_at: string | null;
  lock_status: 'ACTIVE' | 'RELEASED' | null;
  lock_expires_at: string | null;
}
