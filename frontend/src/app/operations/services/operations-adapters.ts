import {
  AllocationCandidate,
  AllocationItemGroup,
  AllocationLine,
  AllocationOptionsResponse,
  AllocationSummary,
  AlternateWarehouseOption,
  ConsolidationLeg,
  ConsolidationLegDispatchResponse,
  ConsolidationLegItem,
  ConsolidationLegReceiveResponse,
  ConsolidationLegsResponse,
  ConsolidationWaybillResponse,
  DispatchDetailResponse,
  DispatchQueueItem,
  DispatchRecordSummary,
  DispatchTransportSummary,
  EligibilityDetailResponse,
  FulfillmentMode,
  OperationsEntityType,
  OperationsTask,
  OperationsTaskListResponse,
  PackageDetailResponse,
  PackageLegSummary,
  PackageQueueItem,
  PackageSplitChild,
  PackageSplitReferences,
  PackageSummary,
  PartialReleaseApproveResponse,
  PartialReleaseRequestResponse,
  PickupReleaseResponse,
  RequestDetailResponse,
  RequestItem,
  RequestSummary,
  StagingRecommendationResponse,
  StagingSelectionBasis,
  SuggestedAllocationLine,
  WarehouseAllocationBatch,
  WarehouseAllocationCard,
  WaybillResponse,
} from '../models/operations.model';
import { formatPackageStatus, formatRequestStatus } from '../models/operations-status.util';

type UnknownRecord = Record<string, unknown>;

function asRecord(value: unknown): UnknownRecord {
  return typeof value === 'object' && value !== null ? (value as UnknownRecord) : {};
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function asNumber(value: unknown, fallback = 0): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function asNullableNumber(value: unknown): number | null {
  if (value == null || value === '') {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function asString(value: unknown, fallback = ''): string {
  if (value == null) {
    return fallback;
  }
  return String(value);
}

function asNullableString(value: unknown): string | null {
  if (value == null || value === '') {
    return null;
  }
  return String(value);
}

function asBoolean(value: unknown): boolean {
  return value === true || value === 'true' || value === 1 || value === '1';
}

function asStringArray(value: unknown): string[] {
  return asArray(value).map((entry) => String(entry)).filter(Boolean);
}

export function normalizeRequestItem(raw: unknown): RequestItem {
  const source = asRecord(raw);
  return {
    item_id: asNumber(source['item_id']),
    item_code: asNullableString(source['item_code']),
    item_name: asNullableString(source['item_name']),
    request_qty: asString(source['request_qty'], '0'),
    issue_qty: asString(source['issue_qty'], '0'),
    urgency_ind: asNullableString(source['urgency_ind']) as RequestItem['urgency_ind'],
    rqst_reason_desc: asNullableString(source['rqst_reason_desc']),
    required_by_date: asNullableString(source['required_by_date']),
    status_code: asNullableString(source['status_code']) as RequestItem['status_code'],
  };
}

function normalizeFulfillmentMode(value: unknown): FulfillmentMode | undefined {
  const normalized = asString(value).trim().toUpperCase();
  if (
    normalized === 'DIRECT'
    || normalized === 'PICKUP_AT_STAGING'
    || normalized === 'DELIVER_FROM_STAGING'
  ) {
    return normalized;
  }
  return undefined;
}

function normalizeStagingBasis(value: unknown): StagingSelectionBasis | null {
  const normalized = asString(value).trim().toUpperCase();
  if (
    normalized === 'SAME_PARISH'
    || normalized === 'PROXIMITY_MATRIX'
    || normalized === 'MANUAL_OVERRIDE'
  ) {
    return normalized;
  }
  return null;
}

function normalizePackageLegSummary(raw: unknown): PackageLegSummary | null {
  if (raw == null) {
    return null;
  }
  const source = asRecord(raw);
  if (!Object.keys(source).length) {
    return null;
  }
  return {
    total_legs: asNumber(source['total_legs']),
    planned_legs: asNumber(source['planned_legs']),
    in_transit_legs: asNumber(source['in_transit_legs']),
    received_legs: asNumber(source['received_legs']),
    cancelled_legs: asNumber(source['cancelled_legs']),
    all_received: asBoolean(source['all_received']),
  };
}

function normalizePackageSplitChild(raw: unknown): PackageSplitChild {
  const source = asRecord(raw);
  return {
    package_id: asNumber(source['package_id']),
    package_no: asNullableString(source['package_no']),
    status_code: asString(source['status_code'], ''),
  };
}

function normalizePackageSplit(raw: unknown): PackageSplitReferences | null {
  if (raw == null) {
    return null;
  }
  const source = asRecord(raw);
  if (!Object.keys(source).length) {
    return null;
  }
  return {
    split_from_package_id: asNullableNumber(source['split_from_package_id']),
    split_from_package_no: asNullableString(source['split_from_package_no']),
    split_children: asArray(source['split_children']).map(normalizePackageSplitChild),
  };
}

export function normalizePackageSummary(raw: unknown): PackageSummary {
  const source = asRecord(raw);
  const statusCode = asString(source['status_code'], 'A') as PackageSummary['status_code'];
  return {
    reliefpkg_id: asNumber(source['reliefpkg_id']),
    tracking_no: asNullableString(source['tracking_no']),
    reliefrqst_id: asNumber(source['reliefrqst_id']),
    agency_id: asNullableNumber(source['agency_id']),
    eligible_event_id: asNullableNumber(source['eligible_event_id']),
    source_warehouse_id: asNullableNumber(source['source_warehouse_id']),
    to_inventory_id: asNullableNumber(source['to_inventory_id']),
    destination_warehouse_name: asNullableString(source['destination_warehouse_name']),
    status_code: statusCode,
    status_label: asString(source['status_label'], formatPackageStatus(statusCode)),
    dispatch_dtime: asNullableString(source['dispatch_dtime']),
    received_dtime: asNullableString(source['received_dtime']),
    transport_mode: asNullableString(source['transport_mode']),
    comments_text: asNullableString(source['comments_text']),
    version_nbr: asNumber(source['version_nbr'], 0),
    execution_status: asNullableString(source['execution_status']),
    needs_list_id: asNullableNumber(source['needs_list_id']),
    compatibility_bridge: asBoolean(source['compatibility_bridge']),
    fulfillment_mode: normalizeFulfillmentMode(source['fulfillment_mode']),
    staging_warehouse_id: asNullableNumber(source['staging_warehouse_id']),
    recommended_staging_warehouse_id: asNullableNumber(source['recommended_staging_warehouse_id']),
    staging_selection_basis: normalizeStagingBasis(source['staging_selection_basis']),
    staging_override_reason: asNullableString(source['staging_override_reason']),
    consolidation_status: asNullableString(
      source['consolidation_status'],
    ) as PackageSummary['consolidation_status'],
    effective_dispatch_source_warehouse_id: asNullableNumber(
      source['effective_dispatch_source_warehouse_id'],
    ),
    leg_summary: normalizePackageLegSummary(source['leg_summary']),
    split: normalizePackageSplit(source['split']),
  };
}

export function normalizeRequestSummary(raw: unknown): RequestSummary {
  const source = asRecord(raw);
  const VALID_STATUS_CODES = new Set<string>([
    'DRAFT', 'SUBMITTED', 'UNDER_ELIGIBILITY_REVIEW', 'APPROVED_FOR_FULFILLMENT',
    'PARTIALLY_FULFILLED', 'FULFILLED', 'INELIGIBLE', 'REJECTED', 'CANCELLED',
  ]);
  const rawStatus = asString(source['status_code'], 'DRAFT').trim().toUpperCase();
  const statusCode = (VALID_STATUS_CODES.has(rawStatus) ? rawStatus : 'DRAFT') as RequestSummary['status_code'];
  return {
    reliefrqst_id: asNumber(source['reliefrqst_id']),
    tracking_no: asNullableString(source['tracking_no']),
    agency_id: asNullableNumber(source['agency_id']),
    agency_name: asNullableString(source['agency_name']),
    eligible_event_id: asNullableNumber(source['eligible_event_id']),
    event_name: asNullableString(source['event_name']),
    urgency_ind: asNullableString(source['urgency_ind']) as RequestSummary['urgency_ind'],
    status_code: statusCode,
    status_label: formatRequestStatus(statusCode),
    request_date: asNullableString(source['request_date']),
    create_dtime: asNullableString(source['create_dtime']),
    review_dtime: asNullableString(source['review_dtime']),
    action_dtime: asNullableString(source['action_dtime']),
    rqst_notes_text: asNullableString(source['rqst_notes_text']),
    review_notes_text: asNullableString(source['review_notes_text']),
    status_reason_desc: asNullableString(source['status_reason_desc']),
    version_nbr: asNumber(source['version_nbr'], 0),
    item_count: asNumber(source['item_count'], 0),
    total_requested_qty: asString(source['total_requested_qty'], '0'),
    total_issued_qty: asString(source['total_issued_qty'], '0'),
    reliefpkg_id: asNullableNumber(source['reliefpkg_id']),
    package_tracking_no: asNullableString(source['package_tracking_no']),
    package_status: asNullableString(source['package_status']) as RequestSummary['package_status'],
    execution_status: asNullableString(source['execution_status']),
    needs_list_id: asNullableNumber(source['needs_list_id']),
    compatibility_bridge: asBoolean(source['compatibility_bridge']),
    request_mode: asNullableString(source['request_mode']) as RequestSummary['request_mode'],
    authority_context: asNullableString(source['authority_context']),
  };
}

export function normalizeRequestDetail(raw: unknown): RequestDetailResponse {
  const source = asRecord(raw);
  return {
    ...normalizeRequestSummary(source),
    items: asArray(source['items']).map(normalizeRequestItem),
    packages: asArray(source['packages']).map(normalizePackageSummary),
  };
}

export function normalizeEligibilityDetail(raw: unknown): EligibilityDetailResponse {
  const source = asRecord(raw);
  return {
    ...normalizeRequestDetail(source),
    decision_made: asBoolean(source['decision_made']),
    can_edit: asBoolean(source['can_edit']),
  };
}

function normalizeAllocationLine(raw: unknown): AllocationLine {
  const source = asRecord(raw);
  return {
    item_id: asNumber(source['item_id']),
    inventory_id: asNumber(source['inventory_id']),
    batch_id: asNumber(source['batch_id']),
    batch_no: asNullableString(source['batch_no']),
    quantity: asString(source['quantity'], '0'),
    uom_code: asNullableString(source['uom_code']),
    source_type: asString(source['source_type'], 'ON_HAND'),
    source_record_id: asNullableNumber(source['source_record_id']),
    allocation_rank: asNumber(source['allocation_rank'], 0) || undefined,
    override_reason_code: asNullableString(source['override_reason_code']),
    override_note: asNullableString(source['override_note']),
    rule_bypass_flag: asBoolean(source['rule_bypass_flag']),
    supervisor_approved_by: asNullableString(source['supervisor_approved_by']),
    supervisor_approved_at: asNullableString(source['supervisor_approved_at']),
    item_code: asNullableString(source['item_code']),
    item_name: asNullableString(source['item_name']),
  };
}

export function normalizeAllocationSummary(raw: unknown): AllocationSummary {
  const source = asRecord(raw);
  const allocationLines = asArray(source['allocation_lines']).map(normalizeAllocationLine);
  const reservedSummary = asRecord(source['reserved_stock_summary']);
  return {
    allocation_lines: allocationLines,
    reserved_stock_summary: {
      line_count: asNumber(reservedSummary['line_count'], allocationLines.length),
      total_qty: asString(
        reservedSummary['total_qty'],
        allocationLines.reduce((sum, row) => sum + asNumber(row.quantity), 0).toFixed(4),
      ),
    },
    waybill_no: asNullableString(source['waybill_no']),
  };
}

function normalizeSuggestedAllocationLine(raw: unknown): SuggestedAllocationLine {
  const source = asRecord(raw);
  return {
    item_id: asNumber(source['item_id']),
    inventory_id: asNumber(source['inventory_id']),
    batch_id: asNumber(source['batch_id']),
    batch_no: asNullableString(source['batch_no']),
    source_type: asString(source['source_type'], 'ON_HAND'),
    source_record_id: asNullableNumber(source['source_record_id']),
    uom_code: asNullableString(source['uom_code']),
    quantity: asString(source['quantity'], '0'),
  };
}

function normalizeAllocationCandidate(raw: unknown): AllocationCandidate {
  const source = asRecord(raw);
  const markers = asStringArray(source['compliance_markers']);
  const canExpire = asBoolean(source['can_expire_flag']);
  const issuanceOrder = asString(source['issuance_order'], canExpire ? 'FEFO' : 'FIFO').toUpperCase();

  return {
    batch_id: asNumber(source['batch_id']),
    inventory_id: asNumber(source['inventory_id']),
    item_id: asNumber(source['item_id']),
    batch_no: asNullableString(source['batch_no']),
    batch_date: asNullableString(source['batch_date']),
    expiry_date: asNullableString(source['expiry_date']),
    usable_qty: asString(source['usable_qty'], asString(source['available_qty'], '0')),
    reserved_qty: asString(source['reserved_qty'], '0'),
    available_qty: asString(source['available_qty'], asString(source['usable_qty'], '0')),
    uom_code: asNullableString(source['uom_code']),
    source_type: asString(source['source_type'], 'ON_HAND'),
    source_record_id: asNullableNumber(source['source_record_id']),
    warehouse_name: asNullableString(source['warehouse_name']),
    can_expire_flag: canExpire,
    issuance_order: issuanceOrder,
    item_code: asNullableString(source['item_code']),
    item_name: asNullableString(source['item_name']),
    compliance_markers: markers,
  };
}

export function normalizeAlternateWarehouseOption(raw: unknown): AlternateWarehouseOption {
  const source = asRecord(raw);
  return {
    warehouse_id: asNumber(source['warehouse_id']),
    warehouse_name: asString(source['warehouse_name'], ''),
    available_qty: asString(source['available_qty'], '0'),
    suggested_qty: asString(source['suggested_qty'], '0'),
    can_fully_cover: asBoolean(source['can_fully_cover']),
  };
}

export function normalizeWarehouseAllocationBatch(raw: unknown): WarehouseAllocationBatch {
  const source = asRecord(raw);
  return {
    batch_id: asNumber(source['batch_id']),
    inventory_id: asNumber(source['inventory_id']),
    batch_no: asNullableString(source['batch_no']),
    batch_date: asNullableString(source['batch_date']),
    expiry_date: asNullableString(source['expiry_date']),
    available_qty: asString(source['available_qty'], '0'),
    usable_qty: asString(source['usable_qty'], '0'),
    reserved_qty: asString(source['reserved_qty'], '0'),
    uom_code: asNullableString(source['uom_code']),
    source_type: asString(source['source_type'], 'ON_HAND'),
    source_record_id: asNullableNumber(source['source_record_id']),
  };
}

export function normalizeWarehouseAllocationCard(raw: unknown): WarehouseAllocationCard {
  const source = asRecord(raw);
  return {
    warehouse_id: asNumber(source['warehouse_id']),
    warehouse_name: asString(source['warehouse_name'], ''),
    rank: asNumber(source['rank']),
    issuance_order: asString(source['issuance_order'], 'FIFO').toUpperCase(),
    total_available: asString(source['total_available'], '0'),
    suggested_qty: asString(source['suggested_qty'], '0'),
    batches: asArray(source['batches']).map(normalizeWarehouseAllocationBatch),
  };
}

export function normalizeAllocationItemGroup(raw: unknown): AllocationItemGroup {
  const source = asRecord(raw);
  const candidates = asArray(source['candidates']).map(normalizeAllocationCandidate);
  const candidateMarkers = candidates.flatMap((candidate) => candidate.compliance_markers ?? []);
  const complianceMarkers = [...new Set([...asStringArray(source['compliance_markers']), ...candidateMarkers])];
  const canExpire = candidates.some((candidate) => candidate.can_expire_flag) || asBoolean(source['can_expire_flag']);
  const issuanceOrder = asString(
    source['issuance_order'],
    candidates.find((candidate) => candidate.issuance_order)?.issuance_order ?? (canExpire ? 'FEFO' : 'FIFO'),
  ).toUpperCase();

  return {
    item_id: asNumber(source['item_id']),
    item_code: asNullableString(source['item_code']),
    item_name: asNullableString(source['item_name']),
    request_qty: asString(source['request_qty'], '0'),
    issue_qty: asString(source['issue_qty'], '0'),
    remaining_qty: asString(source['remaining_qty'], '0'),
    fully_issued: asBoolean(source['fully_issued']),
    urgency_ind: asNullableString(source['urgency_ind']) as AllocationItemGroup['urgency_ind'],
    candidates,
    suggested_allocations: asArray(source['suggested_allocations']).map(normalizeSuggestedAllocationLine),
    remaining_after_suggestion: asString(source['remaining_after_suggestion'], asString(source['remaining_qty'], '0')),
    can_expire_flag: canExpire,
    issuance_order: issuanceOrder,
    compliance_markers: complianceMarkers,
    override_required: asBoolean(source['override_required']),
    source_warehouse_id: asNullableNumber(source['source_warehouse_id']),
    stock_integrity_issue: asNullableString(source['stock_integrity_issue']),
    remaining_shortfall_qty: asString(source['remaining_shortfall_qty'], '0'),
    continuation_recommended: asBoolean(source['continuation_recommended']),
    alternate_warehouses: asArray(source['alternate_warehouses']).map(normalizeAlternateWarehouseOption),
    warehouse_cards: asArray(source['warehouse_cards']).map(normalizeWarehouseAllocationCard),
    draft_selected_qty:
      source['draft_selected_qty'] != null ? asString(source['draft_selected_qty'], '0') : undefined,
    effective_remaining_qty:
      source['effective_remaining_qty'] != null ? asString(source['effective_remaining_qty'], '0') : undefined,
  };
}

export function normalizeAllocationOptions(raw: unknown): AllocationOptionsResponse {
  const source = asRecord(raw);
  return {
    request: normalizeRequestSummary(source['request']),
    items: asArray(source['items']).map(normalizeAllocationItemGroup),
  };
}

export function normalizePackageDetail(raw: unknown): PackageDetailResponse {
  const source = asRecord(raw);
  const nestedPackage = source['package'];
  const packageRecord = nestedPackage != null && nestedPackage !== false
    ? normalizePackageSummary(nestedPackage)
    : (source['reliefpkg_id'] != null ? normalizePackageSummary(source) : null);
  const nestedAllocation = nestedPackage != null
    ? asRecord(nestedPackage)['allocation']
    : source['allocation'];

  return {
    request: normalizeRequestSummary(source['request']),
    package: packageRecord,
    items: asArray(source['items']).map(normalizeRequestItem),
    allocation: nestedAllocation ? normalizeAllocationSummary(nestedAllocation) : undefined,
    compatibility_only: asBoolean(source['compatibility_only']),
  };
}

export function normalizePackageQueueItem(raw: unknown): PackageQueueItem {
  const source = asRecord(raw);
  return {
    ...normalizeRequestSummary(source),
    current_package: source['current_package'] ? normalizePackageSummary(source['current_package']) : null,
  };
}

export function normalizeWaybill(raw: unknown): WaybillResponse {
  const source = asRecord(raw);
  return {
    waybill_no: asString(source['waybill_no']),
    waybill_payload: asRecord(source['waybill_payload']) as unknown as WaybillResponse['waybill_payload'],
    persisted: asBoolean(source['persisted']),
    artifact_mode: asNullableString(source['artifact_mode']) ?? undefined,
    derived_from_dispatch_record: source['derived_from_dispatch_record'] == null
      ? undefined
      : asBoolean(source['derived_from_dispatch_record']),
    compatibility_bridge: source['compatibility_bridge'] == null
      ? undefined
      : asBoolean(source['compatibility_bridge']),
  };
}

function normalizeDispatchTransport(raw: unknown): DispatchTransportSummary {
  const source = asRecord(raw);
  return {
    driver_name: asNullableString(source['driver_name']),
    driver_license_last4:
      asNullableString(source['driver_license_last4']) ??
      asNullableString(source['driver_license_no']),
    vehicle_id: asNullableString(source['vehicle_id']),
    vehicle_registration: asNullableString(source['vehicle_registration']),
    vehicle_type: asNullableString(source['vehicle_type']),
    transport_mode: asNullableString(source['transport_mode']),
    departure_dtime: asNullableString(source['departure_dtime']),
    estimated_arrival_dtime: asNullableString(source['estimated_arrival_dtime']),
    transport_notes: asNullableString(source['transport_notes']),
    route_override_reason: asNullableString(source['route_override_reason']),
  };
}

function normalizeDispatchRecord(raw: unknown): DispatchRecordSummary | null {
  const source = asRecord(raw);
  if (!Object.keys(source).length) {
    return null;
  }
  return {
    dispatch_id: asNumber(source['dispatch_id']),
    dispatch_no: asNullableString(source['dispatch_no']),
    status_code: asNullableString(source['status_code']),
    status_label: asNullableString(source['status_label']),
    dispatch_at: asNullableString(source['dispatch_at']),
    dispatched_by_id: asNullableString(source['dispatched_by_id']),
    source_warehouse_id: asNullableNumber(source['source_warehouse_id']),
    destination_tenant_id: asNullableNumber(source['destination_tenant_id']),
    destination_agency_id: asNullableNumber(source['destination_agency_id']),
    transport: source['transport'] ? normalizeDispatchTransport(source['transport']) : null,
  };
}

export function normalizeDispatchDetail(raw: unknown): DispatchDetailResponse {
  const source = asRecord(raw);
  const packageSource = source['package'] ? asRecord(source['package']) : source;
  const packageSummary = normalizePackageSummary(packageSource);
  const dispatch = normalizeDispatchRecord(source['dispatch']);
  const allocationSource = packageSource['allocation'] ?? source['allocation'];
  return {
    ...packageSummary,
    dispatch,
    dispatch_dtime: dispatch?.dispatch_at ?? packageSummary.dispatch_dtime,
    transport_mode: dispatch?.transport?.transport_mode ?? packageSummary.transport_mode,
    request: normalizeRequestSummary(source['request']),
    items: asArray(source['items']).map(normalizeRequestItem),
    allocation: allocationSource ? normalizeAllocationSummary(allocationSource) : undefined,
    waybill: source['waybill'] ? normalizeWaybill(source['waybill']) : null,
  };
}

export function createDispatchDetailFallback(detail: PackageDetailResponse): DispatchDetailResponse | null {
  if (!detail.package) {
    return null;
  }

  return {
    ...detail.package,
    request: detail.request,
    allocation: detail.allocation,
    waybill: null,
  };
}

export function createDispatchQueueItemFromPackage(item: PackageQueueItem): DispatchQueueItem | null {
  const currentPackage = item.current_package;
  if (!currentPackage) {
    return null;
  }

  return {
    ...currentPackage,
    request_tracking_no: item.tracking_no,
    agency_name: item.agency_name,
    event_name: item.event_name,
    request: item,
  };
}

export function normalizeDispatchQueueItem(raw: unknown): DispatchQueueItem {
  const source = asRecord(raw);
  const packageSummary = normalizePackageSummary(source);
  const request = source['request'] ? normalizeRequestSummary(source['request']) : null;
  const dispatch = normalizeDispatchRecord(source['dispatch']);
  return {
    ...packageSummary,
    dispatch,
    dispatch_dtime: dispatch?.dispatch_at ?? packageSummary.dispatch_dtime,
    transport_mode: dispatch?.transport?.transport_mode ?? packageSummary.transport_mode,
    request_tracking_no: request?.tracking_no ?? null,
    agency_name: request?.agency_name ?? null,
    event_name: request?.event_name ?? null,
    request,
  };
}

function normalizeEntityType(value: unknown): OperationsEntityType | null {
  const entityType = asString(value).trim().toUpperCase();
  switch (entityType) {
    case 'RELIEF_REQUEST':
    case 'REQUEST':
    case 'PACKAGE':
    case 'DISPATCH':
      return entityType;
    default:
      return null;
  }
}

function formatQueueCode(queueCode: string | null): string {
  switch (queueCode) {
    case 'ELIGIBILITY_REVIEW':
      return 'Eligibility Review';
    case 'PACKAGE_FULFILLMENT':
      return 'Package Fulfillment';
    case 'OVERRIDE_APPROVAL':
      return 'Override Approval';
    case 'DISPATCH':
      return 'Dispatch';
    case 'RECEIPT_CONFIRMATION':
      return 'Receipt Confirmation';
    case 'REQUEST_TRACKING':
      return 'Request Tracking';
    default:
      return 'Operations Queue';
  }
}

function formatEventCode(eventCode: string | null): string {
  switch (eventCode) {
    case 'REQUEST_SUBMITTED':
      return 'Request Submitted';
    case 'REQUEST_APPROVED':
      return 'Request Approved';
    case 'REQUEST_REJECTED':
      return 'Request Rejected';
    case 'REQUEST_INELIGIBLE':
      return 'Request Ineligible';
    case 'PACKAGE_LOCKED':
      return 'Package Locked';
    case 'PACKAGE_OVERRIDE_REQUESTED':
      return 'Override Requested';
    case 'PACKAGE_OVERRIDE_APPROVED':
      return 'Override Approved';
    case 'PACKAGE_COMMITTED':
      return 'Package Committed';
    case 'DISPATCH_COMPLETED':
      return 'Dispatch Completed';
    case 'RECEIPT_CONFIRMED':
      return 'Receipt Confirmed';
    default:
      return 'Operations Notification';
  }
}

function normalizeQueueAssignmentTask(raw: unknown): OperationsTask {
  const source = asRecord(raw);
  const queueCode = asNullableString(source['queue_code']);
  const assignedRole = asNullableString(source['assigned_role_code']);
  const assignedUser = asNullableString(source['assigned_user_id']);
  const assignmentStatus = asString(source['assignment_status']).trim().toUpperCase();
  return {
    id: asNumber(source['queue_assignment_id']),
    source: 'QUEUE_ASSIGNMENT',
    task_type: queueCode ?? 'QUEUE_ASSIGNMENT',
    title: `${formatQueueCode(queueCode)} Assignment`,
    description: assignedUser
      ? `Assigned directly to ${assignedUser}. Open the related workflow item to continue.`
      : assignedRole
        ? `Assigned to the ${assignedRole.replace(/_/g, ' ')} queue. Open the related workflow item to continue.`
        : 'Open the related workflow item to continue.',
    status: assignmentStatus === 'COMPLETED' ? 'COMPLETED' : 'PENDING',
    priority: null,
    related_entity_type: normalizeEntityType(source['entity_type']),
    related_entity_id: asNullableNumber(source['entity_id']),
    created_at: asNullableString(source['assigned_at']) ?? '',
    due_date: null,
    assigned_to: assignedUser ?? assignedRole,
    queue_code: queueCode,
  };
}

function normalizeNotificationTask(raw: unknown): OperationsTask {
  const source = asRecord(raw);
  const eventCode = asNullableString(source['event_code']);
  const assignedTo = asNullableString(source['recipient_user_id']) ?? asNullableString(source['recipient_role_code']);
  return {
    id: asNumber(source['notification_id']),
    source: 'NOTIFICATION',
    task_type: eventCode ?? 'NOTIFICATION',
    title: formatEventCode(eventCode),
    description: asString(source['message_text'], 'Operations workflow notification.'),
    status: asNullableString(source['read_at']) ? 'COMPLETED' : 'PENDING',
    priority: null,
    related_entity_type: normalizeEntityType(source['entity_type']),
    related_entity_id: asNullableNumber(source['entity_id']),
    created_at: asNullableString(source['created_at']) ?? '',
    due_date: null,
    assigned_to: assignedTo,
    queue_code: asNullableString(source['queue_code']),
  };
}

function normalizeConsolidationLegItem(raw: unknown): ConsolidationLegItem {
  const source = asRecord(raw);
  return {
    leg_item_id: asNumber(source['leg_item_id']),
    item_id: asNumber(source['item_id']),
    batch_id: asNullableNumber(source['batch_id']),
    quantity: asString(source['quantity'], '0'),
    source_type: asString(source['source_type'], 'ON_HAND'),
    source_record_id: asNullableNumber(source['source_record_id']),
    staging_batch_id: asNullableNumber(source['staging_batch_id']),
    uom_code: asNullableString(source['uom_code']),
  };
}

export function normalizeConsolidationLeg(raw: unknown): ConsolidationLeg {
  const source = asRecord(raw);
  const statusCode = asString(source['status_code'], 'PLANNED') as ConsolidationLeg['status_code'];
  return {
    leg_id: asNumber(source['leg_id']),
    package_id: asNumber(source['package_id']),
    leg_sequence: asNumber(source['leg_sequence']),
    source_warehouse_id: asNumber(source['source_warehouse_id']),
    staging_warehouse_id: asNumber(source['staging_warehouse_id']),
    status_code: statusCode,
    status_label: asString(source['status_label'], statusCode),
    shadow_transfer_id: asNullableNumber(source['shadow_transfer_id']),
    driver_name: asNullableString(source['driver_name']),
    driver_license_last4:
      asNullableString(source['driver_license_last4']) ??
      asNullableString(source['driver_license_no']),
    vehicle_id: asNullableString(source['vehicle_id']),
    vehicle_registration: asNullableString(source['vehicle_registration']),
    vehicle_type: asNullableString(source['vehicle_type']),
    transport_mode: asNullableString(source['transport_mode']),
    transport_notes: asNullableString(source['transport_notes']),
    dispatched_by_id: asNullableString(source['dispatched_by_id']),
    dispatched_at:
      asNullableString(source['dispatched_at'])
      ?? asNullableString(source['departure_dtime']),
    departure_dtime:
      asNullableString(source['departure_dtime'])
      ?? asNullableString(source['dispatched_at']),
    estimated_arrival_dtime:
      asNullableString(source['estimated_arrival_dtime'])
      ?? asNullableString(source['expected_arrival_at']),
    route_override_reason: asNullableString(source['route_override_reason']),
    expected_arrival_at:
      asNullableString(source['expected_arrival_at'])
      ?? asNullableString(source['estimated_arrival_dtime']),
    received_by_user_id: asNullableString(source['received_by_user_id']),
    received_at: asNullableString(source['received_at']),
    items: asArray(source['items']).map(normalizeConsolidationLegItem),
    waybill_no: asNullableString(source['waybill_no']),
  };
}

export function normalizeConsolidationLegsResponse(raw: unknown): ConsolidationLegsResponse {
  const source = asRecord(raw);
  return {
    package: normalizePackageSummary(source['package']),
    results: asArray(source['results']).map(normalizeConsolidationLeg),
  };
}

export function normalizeConsolidationLegDispatchResponse(raw: unknown): ConsolidationLegDispatchResponse {
  const source = asRecord(raw);
  return {
    status: asString(source['status'], 'IN_TRANSIT') as ConsolidationLegDispatchResponse['status'],
    package: normalizePackageSummary(source['package']),
    leg: normalizeConsolidationLeg(source['leg']),
  };
}

export function normalizeConsolidationLegReceiveResponse(raw: unknown): ConsolidationLegReceiveResponse {
  const source = asRecord(raw);
  return {
    status: asString(source['status'], 'RECEIVED_AT_STAGING') as ConsolidationLegReceiveResponse['status'],
    package: normalizePackageSummary(source['package']),
    leg: normalizeConsolidationLeg(source['leg']),
  };
}

export function normalizeConsolidationWaybill(raw: unknown): ConsolidationWaybillResponse {
  const source = asRecord(raw);
  return {
    waybill_no: asString(source['waybill_no']),
    waybill_payload: asRecord(source['waybill_payload']) as unknown as ConsolidationWaybillResponse['waybill_payload'],
    persisted: asBoolean(source['persisted']),
  };
}

export function normalizeStagingRecommendation(raw: unknown): StagingRecommendationResponse {
  const source = asRecord(raw);
  return {
    reliefrqst_id: asNumber(source['reliefrqst_id']),
    recommended_staging_warehouse_id: asNullableNumber(source['recommended_staging_warehouse_id']),
    recommended_staging_warehouse_name: asNullableString(source['recommended_staging_warehouse_name']),
    recommended_staging_parish_code: asNullableString(source['recommended_staging_parish_code']),
    staging_selection_basis: normalizeStagingBasis(source['staging_selection_basis']),
  };
}

export function normalizePartialReleaseRequestResponse(raw: unknown): PartialReleaseRequestResponse {
  const source = asRecord(raw);
  return {
    status: 'PARTIAL_RELEASE_REQUESTED',
    package: normalizePackageSummary(source['package']),
  };
}

export function normalizePartialReleaseApproveResponse(raw: unknown): PartialReleaseApproveResponse {
  const source = asRecord(raw);
  return {
    parent: normalizePackageSummary(source['parent']),
    residual: source['residual'] ? normalizePackageSummary(source['residual']) : null,
    released: source['released'] ? normalizePackageSummary(source['released']) : null,
  };
}

export function normalizePickupReleaseResponse(raw: unknown): PickupReleaseResponse {
  const source = asRecord(raw);
  return {
    status: 'RECEIVED',
    package: normalizePackageSummary(source['package']),
  };
}

export function normalizeTaskFeed(raw: unknown): OperationsTaskListResponse {
  const source = asRecord(raw);
  const queueAssignments = asArray(source['queue_assignments']).map(normalizeQueueAssignmentTask);
  const notifications = asArray(source['notifications']).map(normalizeNotificationTask);
  const results = [...queueAssignments, ...notifications].sort((left, right) =>
    new Date(right.created_at ?? 0).getTime() - new Date(left.created_at ?? 0).getTime(),
  );
  return {
    queue_assignments: queueAssignments,
    notifications,
    results,
  };
}
