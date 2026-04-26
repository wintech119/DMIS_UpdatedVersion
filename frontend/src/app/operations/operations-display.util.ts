import { HttpErrorResponse } from '@angular/common/http';

import { PackageLegSummary, PackageSummary, RequestSummary } from './models/operations.model';

export type OperationsTone = 'draft' | 'review' | 'success' | 'warning' | 'danger' | 'muted';

export interface FulfillmentEntryAction {
  label: 'Open Fulfillment' | 'Continue from Stock-Aware Selection';
  disabled: boolean;
  disabledReason: string | null;
}

export type OperationsDispatchStage = 'ready' | 'in_transit' | 'completed' | 'unknown';

const OPERATIONS_QUEUE_SEEN_LIMIT = 250;
// Bound queue search terms to the longest searchable request free-text field.
export const OPERATIONS_QUEUE_SEARCH_MAX_LENGTH = 500;

const REQUEST_STATUS_LABELS: Record<string, string> = {
  DRAFT: 'Draft',
  SUBMITTED: 'Submitted',
  UNDER_ELIGIBILITY_REVIEW: 'Under Review',
  APPROVED_FOR_FULFILLMENT: 'Approved',
  PARTIALLY_FULFILLED: 'Partially Fulfilled',
  FULFILLED: 'Fulfilled',
  INELIGIBLE: 'Ineligible',
  REJECTED: 'Rejected',
  CANCELLED: 'Cancelled',
};

const REQUEST_STATUS_TONES: Record<string, OperationsTone> = {
  DRAFT: 'draft',
  SUBMITTED: 'review',
  UNDER_ELIGIBILITY_REVIEW: 'review',
  APPROVED_FOR_FULFILLMENT: 'success',
  PARTIALLY_FULFILLED: 'warning',
  FULFILLED: 'success',
  INELIGIBLE: 'danger',
  REJECTED: 'danger',
  CANCELLED: 'muted',
};

const PACKAGE_STATUS_LABELS: Record<string, string> = {
  // Legacy single-char codes
  A: 'Draft',
  P: 'Pending',
  V: 'Ready for Dispatch',
  D: 'Dispatched',
  C: 'Completed',
  // Operations-layer status codes
  DRAFT: 'Draft',
  PENDING_OVERRIDE_APPROVAL: 'Override Pending',
  REJECTED: 'Rejected',
  COMMITTED: 'Ready for Dispatch',
  READY_FOR_DISPATCH: 'Ready for Dispatch',
  DISPATCHED: 'Dispatched',
  RECEIVED: 'Received',
  CANCELLED: 'Cancelled',
  // Staged fulfillment status codes
  CONSOLIDATING: 'Consolidating',
  READY_FOR_PICKUP: 'Ready for Pickup',
  SPLIT: 'Split',
};

const PACKAGE_STATUS_TONES: Record<string, OperationsTone> = {
  // Legacy single-char codes
  A: 'muted',
  P: 'review',
  V: 'success',
  D: 'warning',
  C: 'success',
  // Operations-layer status codes
  DRAFT: 'muted',
  PENDING_OVERRIDE_APPROVAL: 'warning',
  REJECTED: 'danger',
  COMMITTED: 'success',
  READY_FOR_DISPATCH: 'success',
  DISPATCHED: 'warning',
  RECEIVED: 'success',
  CANCELLED: 'muted',
  // Staged fulfillment status codes
  CONSOLIDATING: 'warning',
  READY_FOR_PICKUP: 'review',
  SPLIT: 'muted',
};

const CONSOLIDATION_STATUS_LABELS: Record<string, string> = {
  AWAITING_LEGS: 'Awaiting legs',
  LEGS_IN_TRANSIT: 'Legs in transit',
  PARTIALLY_RECEIVED: 'Partially received',
  ALL_RECEIVED: 'All received',
  PARTIAL_RELEASE_REQUESTED: 'Partial release requested',
};

const CONSOLIDATION_STATUS_TONES: Record<string, OperationsTone> = {
  AWAITING_LEGS: 'draft',
  LEGS_IN_TRANSIT: 'warning',
  PARTIALLY_RECEIVED: 'warning',
  ALL_RECEIVED: 'success',
  PARTIAL_RELEASE_REQUESTED: 'review',
};

const CONSOLIDATION_LEG_STATUS_LABELS: Record<string, string> = {
  PLANNED: 'Planned',
  IN_TRANSIT: 'In transit',
  RECEIVED_AT_STAGING: 'Received at staging',
  CANCELLED: 'Cancelled',
};

const CONSOLIDATION_LEG_STATUS_TONES: Record<string, OperationsTone> = {
  PLANNED: 'draft',
  IN_TRANSIT: 'warning',
  RECEIVED_AT_STAGING: 'success',
  CANCELLED: 'muted',
};

const FULFILLMENT_MODE_LABELS: Record<string, string> = {
  DIRECT: 'Direct dispatch',
  DELIVER_FROM_STAGING: 'Deliver from staging',
  PICKUP_AT_STAGING: 'Pickup at staging',
};

const URGENCY_LABELS: Record<string, string> = {
  C: 'Critical',
  H: 'High',
  M: 'Medium',
  L: 'Low',
};

const URGENCY_TONES: Record<string, OperationsTone> = {
  C: 'danger',
  H: 'warning',
  M: 'warning',
  L: 'review',
};

const FULFILLMENT_ENTRY_REQUEST_STATUSES = new Set([
  'APPROVED_FOR_FULFILLMENT',
]);

const FULFILLMENT_RESUME_REQUEST_STATUSES = new Set([
  'PARTIALLY_FULFILLED',
  'FULFILLED',
]);

const FULFILLMENT_RESUME_PACKAGE_STATUSES = new Set([
  'A',
  'P',
  'D',
  'C',
  'DRAFT',
  'PENDING_OVERRIDE_APPROVAL',
  'COMMITTED',
  'CONSOLIDATING',
  'READY_FOR_DISPATCH',
  'READY_FOR_PICKUP',
  'DISPATCHED',
  'RECEIVED',
  'SPLIT',
]);

const NON_CANCELABLE_FULFILLMENT_STATUSES = new Set([
  'D',
  'C',
  'COMMITTED',
  'READY_FOR_DISPATCH',
  'READY_FOR_PICKUP',
  'DISPATCHED',
  'RECEIVED',
  'SPLIT',
  'CANCELLED',
]);

// Packages may enter the dispatch workspace only after stock has been committed.
// DRAFT / PENDING_OVERRIDE_APPROVAL / CONSOLIDATING packages must be kept out —
// opening the dispatch workspace for them would show a meaningless empty state
// and previously caused the backend to materialize an orphan dispatch record.
const DISPATCH_READY_PACKAGE_STATUSES = new Set([
  // Legacy single-char codes (D=Dispatched, C=Completed/Received)
  'D',
  'C',
  // Operations-layer status codes
  'COMMITTED',
  'READY_FOR_DISPATCH',
  'READY_FOR_PICKUP',
  'DISPATCHED',
  'RECEIVED',
]);

const FULFILLMENT_ACCESS_DISABLED_REASON =
  'Only fulfillment logistics roles can open the package workspace.';

const PACKAGE_DISPATCH_NOT_READY_REASON =
  'Dispatch preparation unlocks after the package is committed in fulfillment.';

export function formatOperationsRequestStatus(code: number | string | null | undefined): string {
  const normalized = String(code ?? '').trim().toUpperCase();
  return REQUEST_STATUS_LABELS[normalized] ?? 'Unknown';
}

export function getOperationsRequestTone(code: number | string | null | undefined): OperationsTone {
  const normalized = String(code ?? '').trim().toUpperCase();
  return REQUEST_STATUS_TONES[normalized] ?? 'muted';
}

function normalizeOperationsPackageStatus(
  code: string | null | undefined,
  executionStatus: string | null | undefined,
): string {
  const normalizedExecutionStatus = String(executionStatus ?? '').trim().toUpperCase();
  const normalizedCode = String(code ?? '').trim().toUpperCase();
  switch (normalizedExecutionStatus) {
    case 'PENDING_OVERRIDE_APPROVAL':
    case 'COMMITTED':
    case 'READY_FOR_DISPATCH':
    case 'DISPATCHED':
      return normalizedExecutionStatus;
    case 'OVERRIDE_APPROVED':
      return 'READY_FOR_DISPATCH';
    default:
      return normalizedCode === 'V' ? 'COMMITTED' : normalizedCode;
  }
}

export function formatOperationsPackageStatus(
  code: string | null | undefined,
  executionStatus?: string | null | undefined,
): string {
  const normalized = normalizeOperationsPackageStatus(code, executionStatus);
  return PACKAGE_STATUS_LABELS[normalized] ?? 'Unknown';
}

export function getOperationsPackageTone(
  code: string | null | undefined,
  executionStatus?: string | null | undefined,
): OperationsTone {
  const normalized = normalizeOperationsPackageStatus(code, executionStatus);
  return PACKAGE_STATUS_TONES[normalized] ?? 'muted';
}

export function getFulfillmentEntryAction(options: {
  requestStatus: string | null | undefined;
  packageStatus?: string | null | undefined;
  executionStatus?: string | null | undefined;
  hasExistingPackage?: boolean;
  hasFulfillmentAccess?: boolean;
}): FulfillmentEntryAction | null {
  const requestStatus = String(options.requestStatus ?? '').trim().toUpperCase();
  const packageStatus = normalizeOperationsPackageStatus(options.packageStatus, options.executionStatus);
  const hasFulfillmentAccess = options.hasFulfillmentAccess ?? true;
  const hasExistingPackage = Boolean(options.hasExistingPackage) || Boolean(packageStatus);
  const canStartFulfillment = FULFILLMENT_ENTRY_REQUEST_STATUSES.has(requestStatus);
  const canResumeFulfillment =
    hasExistingPackage && FULFILLMENT_RESUME_REQUEST_STATUSES.has(requestStatus);

  if (!canStartFulfillment && !canResumeFulfillment) {
    return null;
  }

  const shouldContinue = canResumeFulfillment
    || (hasExistingPackage && FULFILLMENT_RESUME_PACKAGE_STATUSES.has(packageStatus));

  return {
    label: shouldContinue ? 'Continue from Stock-Aware Selection' : 'Open Fulfillment',
    disabled: !hasFulfillmentAccess,
    disabledReason: hasFulfillmentAccess ? null : FULFILLMENT_ACCESS_DISABLED_REASON,
  };
}

export function getRequestFulfillmentEntryAction(
  request: Pick<RequestSummary, 'status_code' | 'reliefpkg_id'> & {
    packages?: readonly Pick<PackageSummary, 'status_code' | 'execution_status'>[];
  },
  hasFulfillmentAccess = true,
): FulfillmentEntryAction | null {
  const currentPackage = request.packages?.[0];
  return getFulfillmentEntryAction({
    requestStatus: request.status_code,
    packageStatus: currentPackage?.status_code,
    executionStatus: currentPackage?.execution_status,
    hasExistingPackage: Boolean(request.reliefpkg_id) || Boolean(request.packages?.length),
    hasFulfillmentAccess,
  });
}

export function isFulfillmentCancellationAllowed(
  code: string | null | undefined,
  executionStatus?: string | null | undefined,
): boolean {
  const normalized = normalizeOperationsPackageStatus(code, executionStatus);
  if (!normalized) {
    return true;
  }
  return !NON_CANCELABLE_FULFILLMENT_STATUSES.has(normalized);
}

export function isPackageDispatchReady(
  code: string | null | undefined,
  executionStatus?: string | null | undefined,
): boolean {
  const normalized = normalizeOperationsPackageStatus(code, executionStatus);
  return DISPATCH_READY_PACKAGE_STATUSES.has(normalized);
}

export interface PackageDispatchAction {
  disabled: boolean;
  disabledReason: string | null;
}

export function getPackageDispatchAction(
  pkg: Pick<PackageSummary, 'status_code' | 'execution_status'> | null | undefined,
): PackageDispatchAction {
  if (!pkg) {
    return { disabled: true, disabledReason: PACKAGE_DISPATCH_NOT_READY_REASON };
  }
  const ready = isPackageDispatchReady(pkg.status_code, pkg.execution_status);
  return {
    disabled: !ready,
    disabledReason: ready ? null : PACKAGE_DISPATCH_NOT_READY_REASON,
  };
}

export function getOperationsDispatchStage(pkg: {
  status_code: string | null | undefined;
  execution_status?: string | null | undefined;
  received_dtime?: string | null | undefined;
}): OperationsDispatchStage {
  const normalized = normalizeOperationsPackageStatus(pkg.status_code, pkg.execution_status);
  if (pkg.received_dtime) {
    return 'completed';
  }
  if (normalized === 'D' || normalized === 'DISPATCHED') {
    return 'in_transit';
  }
  if (normalized === 'C' || normalized === 'RECEIVED') {
    return 'completed';
  }
  if (
    normalized === 'P'
    || normalized === 'COMMITTED'
    || normalized === 'READY_FOR_DISPATCH'
    || normalized === 'READY_FOR_PICKUP'
  ) {
    return 'ready';
  }
  return 'unknown';
}

export function formatOperationsConsolidationStatus(code: string | null | undefined): string {
  const normalized = String(code ?? '').trim().toUpperCase();
  return CONSOLIDATION_STATUS_LABELS[normalized] ?? 'Unknown';
}

export function getOperationsConsolidationStatusTone(code: string | null | undefined): OperationsTone {
  const normalized = String(code ?? '').trim().toUpperCase();
  return CONSOLIDATION_STATUS_TONES[normalized] ?? 'muted';
}

export function formatOperationsConsolidationLegStatus(code: string | null | undefined): string {
  const normalized = String(code ?? '').trim().toUpperCase();
  return CONSOLIDATION_LEG_STATUS_LABELS[normalized] ?? 'Unknown';
}

export function getOperationsConsolidationLegTone(code: string | null | undefined): OperationsTone {
  const normalized = String(code ?? '').trim().toUpperCase();
  return CONSOLIDATION_LEG_STATUS_TONES[normalized] ?? 'muted';
}

export function formatOperationsFulfillmentMode(code: string | null | undefined): string {
  const raw = String(code ?? '').trim();
  if (!raw) {
    return 'Not set';
  }
  const normalized = raw.toUpperCase();
  return FULFILLMENT_MODE_LABELS[normalized] ?? raw;
}

/**
 * Format a leg progress label like "2 / 4 legs" for staged consolidation
 * packages. Returns "No legs planned" when the package has no legs yet
 * (either direct fulfillment or staged but not yet committed).
 */
export function formatLegProgressLabel(
  summary: PackageLegSummary | null | undefined,
): string {
  if (!summary || summary.total_legs === 0) {
    return 'No legs planned';
  }
  return `${summary.received_legs} / ${summary.total_legs} legs`;
}

/**
 * Map a leg summary to a status tone for the queue chip.
 * - success when all legs received (ready to dispatch)
 * - warning when partially received (some legs still missing)
 * - review when legs are in transit
 * - draft when nothing has been dispatched from source warehouses yet
 */
export function getLegProgressTone(
  summary: PackageLegSummary | null | undefined,
): OperationsTone {
  if (!summary || summary.total_legs === 0) {
    return 'muted';
  }
  if (summary.all_received) {
    return 'success';
  }
  if (summary.received_legs > 0) {
    return 'warning';
  }
  if (summary.in_transit_legs > 0) {
    return 'review';
  }
  return 'draft';
}

/**
 * Classify a package's consolidation stage for filter/count logic on the
 * Consolidation queue. Works from the leg_summary rollup so the queue does
 * not need a second roundtrip per row.
 */
export type ConsolidationStage = 'awaiting' | 'in_transit' | 'partial' | 'ready';

export function getConsolidationStageFromLegs(
  summary: PackageLegSummary | null | undefined,
): ConsolidationStage {
  if (!summary || summary.total_legs === 0) {
    return 'awaiting';
  }
  if (summary.all_received) {
    return 'ready';
  }
  if (summary.received_legs > 0) {
    return 'partial';
  }
  if (summary.in_transit_legs > 0) {
    return 'in_transit';
  }
  return 'awaiting';
}

export function formatOperationsUrgency(code: string | null | undefined): string {
  const normalized = String(code ?? '').trim().toUpperCase();
  return URGENCY_LABELS[normalized] ?? 'Unknown';
}

export function getOperationsUrgencyTone(code: string | null | undefined): OperationsTone {
  const normalized = String(code ?? '').trim().toUpperCase();
  return URGENCY_TONES[normalized] ?? 'muted';
}

export function formatOperationsDateTime(value: string | null | undefined): string {
  if (!value) {
    return 'Pending';
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString([], {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function formatOperationsAge(value: string | null | undefined): string {
  if (!value) {
    return 'Pending';
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return 'Pending';
  }
  const minutes = Math.max(0, Math.round((Date.now() - parsed.getTime()) / 60000));
  if (minutes < 60) {
    const displayMinutes = Math.max(1, minutes);
    return displayMinutes === 1 ? '1 min' : `${displayMinutes} mins`;
  }
  const hours = Math.round(minutes / 60);
  if (hours < 24) {
    return hours === 1 ? '1 hr' : `${hours} hrs`;
  }
  const days = Math.round(hours / 24);
  return days === 1 ? '1 day' : `${days} days`;
}

// Relative "Updated" label for the ops queue hero meta pill. Takes an epoch
// milliseconds timestamp (typically Date.now() captured when the queue
// successfully refreshed) and returns a human-friendly freshness phrase.
export function formatOperationsRefreshedLabel(timestampMs: number | null | undefined): string {
  if (timestampMs == null || !Number.isFinite(timestampMs)) {
    return 'just now';
  }
  const diffMs = Date.now() - timestampMs;
  if (diffMs < 60_000) {
    return 'just now';
  }
  const minutes = Math.floor(diffMs / 60_000);
  if (minutes < 60) {
    return minutes === 1 ? '1 min ago' : `${minutes} mins ago`;
  }
  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    return hours === 1 ? '1 hr ago' : `${hours} hrs ago`;
  }
  const days = Math.floor(hours / 24);
  return days === 1 ? '1 day ago' : `${days} days ago`;
}

export type OperationsTimeInStageTone = 'fresh' | 'normal' | 'stale' | 'breach';

// Shared SLA thresholds (hours) — same placeholder values the Package
// Fulfillment Queue uses so every ops queue rings the same time-in-stage
// pill color language. Queue pages simply feed the row's "created" or
// "updated" timestamp into `getOperationsTimeInStageTone`.
const OPERATIONS_TIME_IN_STAGE_THRESHOLDS = {
  fresh: 4,
  normal: 24,
  stale: 48,
} as const;

export function getOperationsTimeInStageTone(
  value: string | null | undefined,
): OperationsTimeInStageTone {
  if (!value) {
    return 'normal';
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return 'normal';
  }
  const hours = Math.max(0, (Date.now() - parsed.getTime()) / (60 * 60 * 1000));
  if (hours < OPERATIONS_TIME_IN_STAGE_THRESHOLDS.fresh) {
    return 'fresh';
  }
  if (hours < OPERATIONS_TIME_IN_STAGE_THRESHOLDS.normal) {
    return 'normal';
  }
  if (hours < OPERATIONS_TIME_IN_STAGE_THRESHOLDS.stale) {
    return 'stale';
  }
  return 'breach';
}

export function extractOperationsErrorMessage(value: unknown): string | null {
  if (typeof value === 'string') {
    return value.trim() || null;
  }
  if (Array.isArray(value)) {
    const nested = value.map(extractOperationsErrorMessage).find(Boolean);
    return nested ?? null;
  }
  if (isOperationsRecord(value)) {
    if (typeof value['message'] === 'string' && value['message'].trim()) {
      return value['message'].trim();
    }
    if (typeof value['detail'] === 'string' && value['detail'].trim()) {
      return value['detail'].trim();
    }
    if (value['detail'] !== undefined) {
      const nestedDetail = extractOperationsErrorMessage(value['detail']);
      if (nestedDetail) {
        return nestedDetail;
      }
    }
    if (isOperationsRecord(value['errors'])) {
      const nested = Object.values(value['errors']).map(extractOperationsErrorMessage).find(Boolean);
      return nested ?? null;
    }
  }
  return null;
}

/**
 * Translate an {@link HttpErrorResponse} into a user-facing message.
 *
 * For 429 responses, the backend sends a `Retry-After` header (seconds). We
 * surface it in the toast so Kemar knows when to try again, rather than
 * seeing a generic "Too many requests" line.
 */
export function extractOperationsHttpErrorMessage(
  error: HttpErrorResponse,
  fallback: string,
): string {
  if (error.status === 429) {
    const retrySeconds = parseRetryAfterSeconds(error.headers?.get?.('Retry-After'));
    const base = extractOperationsErrorMessage(error.error) ?? 'Too many requests.';
    return retrySeconds > 0 ? `${base} Try again in ${retrySeconds}s.` : base;
  }
  const errorMap = isOperationsRecord(error.error)
    ? error.error['errors']
    : null;
  if (isOperationsRecord(errorMap)) {
    const messages = Object.values(errorMap)
      .flatMap((value) => Array.isArray(value) ? value : [value])
      .map((value) => extractOperationsErrorMessage(value)?.trim() ?? '')
      .filter(Boolean);
    if (messages.length) {
      return messages[0];
    }
  }
  return extractOperationsErrorMessage(error.error) ?? fallback;
}

function parseRetryAfterSeconds(headerValue: string | null | undefined): number {
  if (!headerValue) {
    return 0;
  }
  const parsed = Number(headerValue);
  if (Number.isFinite(parsed) && parsed > 0) {
    return Math.round(parsed);
  }
  const parsedDate = Date.parse(headerValue);
  if (Number.isFinite(parsedDate)) {
    return Math.max(0, Math.round((parsedDate - Date.now()) / 1000));
  }
  return 0;
}

/**
 * Attempt to read an audit correlation id from either the response body
 * (action_id / audit_log_id) or the HTTP headers (X-Request-Id /
 * X-Correlation-Id). Returns null when neither is present so callers can
 * omit the reference row rather than fabricate one.
 */
export function readOperationsAuditReferenceId(
  error: HttpErrorResponse | null,
  body: { action_id?: string | number | null; audit_log_id?: string | number | null } | null | undefined,
  headers?: { get: (name: string) => string | null } | null,
): string | null {
  const bodyRef = body?.action_id ?? body?.audit_log_id ?? null;
  if (bodyRef != null && String(bodyRef).trim()) {
    return String(bodyRef).trim();
  }
  const source = headers ?? error?.headers ?? null;
  if (source && typeof source.get === 'function') {
    const requestId = source.get('X-Request-Id') ?? source.get('X-Correlation-Id');
    if (requestId && requestId.trim()) {
      return requestId.trim();
    }
  }
  return null;
}

export function formatOperationsLineCount(count: number): string {
  return count === 1 ? '1 item' : `${count} items`;
}

const REQUEST_MODE_LABELS: Record<string, string> = {
  SELF: 'Self',
  FOR_SUBORDINATE: 'For subordinate',
  SUBORDINATE: 'For subordinate',
  ODPEM_BRIDGE: 'ODPEM Bridge',
};

export function formatRequestMode(mode: string | null | undefined): string {
  return REQUEST_MODE_LABELS[String(mode ?? '').toUpperCase()] ?? String(mode ?? 'Unknown');
}

const TASK_TYPE_LABELS: Record<string, string> = {
  ELIGIBILITY_REVIEW: 'Eligibility Review',
  PACKAGE_FULFILLMENT: 'Package Fulfillment',
  OVERRIDE_APPROVAL: 'Override Approval',
  DISPATCH: 'Dispatch',
  RECEIPT_CONFIRMATION: 'Receipt Confirmation',
  REQUEST_TRACKING: 'Request Tracking',
  REQUEST_SUBMITTED: 'Request Submitted',
  REQUEST_APPROVED: 'Request Approved',
  REQUEST_REJECTED: 'Request Rejected',
  REQUEST_INELIGIBLE: 'Request Ineligible',
  PACKAGE_LOCKED: 'Package Locked',
  PACKAGE_OVERRIDE_REQUESTED: 'Override Requested',
  PACKAGE_OVERRIDE_APPROVED: 'Override Approved',
  PACKAGE_COMMITTED: 'Package Committed',
  DISPATCH_COMPLETED: 'Dispatch Completed',
  RECEIPT_CONFIRMED: 'Receipt Confirmed',
};

const TASK_TYPE_TONES: Record<string, OperationsTone> = {
  ELIGIBILITY_REVIEW: 'review',
  PACKAGE_FULFILLMENT: 'warning',
  OVERRIDE_APPROVAL: 'warning',
  DISPATCH: 'warning',
  RECEIPT_CONFIRMATION: 'success',
  REQUEST_TRACKING: 'review',
  REQUEST_SUBMITTED: 'review',
  REQUEST_APPROVED: 'success',
  REQUEST_REJECTED: 'danger',
  REQUEST_INELIGIBLE: 'danger',
  PACKAGE_LOCKED: 'warning',
  PACKAGE_OVERRIDE_REQUESTED: 'warning',
  PACKAGE_OVERRIDE_APPROVED: 'success',
  PACKAGE_COMMITTED: 'success',
  DISPATCH_COMPLETED: 'success',
  RECEIPT_CONFIRMED: 'success',
};

const RECEIPT_STATUS_LABELS: Record<string, string> = {
  RECEIVED: 'Received',
};

const RECEIPT_STATUS_TONES: Record<string, OperationsTone> = {
  RECEIVED: 'success',
};

export function formatTaskType(type: string | null | undefined): string {
  const normalized = String(type ?? '').trim().toUpperCase();
  return TASK_TYPE_LABELS[normalized] ?? type ?? 'Task';
}

export function getTaskTone(type: string | null | undefined): OperationsTone {
  const normalized = String(type ?? '').trim().toUpperCase();
  return TASK_TYPE_TONES[normalized] ?? 'muted';
}

export function formatReceiptStatus(code: string | null | undefined): string {
  const normalized = String(code ?? '').trim().toUpperCase();
  return RECEIPT_STATUS_LABELS[normalized] ?? 'Unknown';
}

export function getReceiptStatusTone(code: string | null | undefined): OperationsTone {
  const normalized = String(code ?? '').trim().toUpperCase();
  return RECEIPT_STATUS_TONES[normalized] ?? 'muted';
}

export function getTaskEntityRoute(
  entityType: string | null | undefined,
  entityId: number | null | undefined,
): string | null {
  if (!entityType || !entityId) {
    return null;
  }
  switch (entityType) {
    case 'RELIEF_REQUEST':
    case 'REQUEST':
      return `/operations/relief-requests/${entityId}`;
    case 'PACKAGE':
      return `/operations/package-fulfillment/${entityId}`;
    case 'DISPATCH':
      return `/operations/dispatch/${entityId}`;
    default:
      return null;
  }
}

export function mapOperationsToneToChipTone(
  tone: OperationsTone | null | undefined,
): 'neutral' | 'soft' | 'critical' | 'warning' | 'success' | 'info' | 'outline' {
  switch (tone) {
    case 'draft':
      return 'outline';
    case 'review':
      return 'info';
    case 'success':
      return 'success';
    case 'warning':
      return 'warning';
    case 'danger':
      return 'critical';
    case 'muted':
    default:
      return 'neutral';
  }
}

export function buildOperationsQueueSeenStorageKey(
  scope: string,
  userRef: string | null | undefined,
): string | null {
  const normalizedScope = String(scope ?? '').trim().toLowerCase();
  const normalizedUserRef = String(userRef ?? '').trim().toLowerCase();
  if (!normalizedScope || !normalizedUserRef) {
    return null;
  }
  return `dmis_operations_queue_seen:${normalizedScope}:${normalizedUserRef}`;
}

export function readOperationsQueueSeenEntries(
  storageKey: string | null | undefined,
): Record<string, number[]> {
  if (!storageKey) {
    return {};
  }

  try {
    const raw = localStorage.getItem(storageKey);
    if (!raw) {
      return {};
    }

    const parsed = JSON.parse(raw);
    if (!isOperationsRecord(parsed)) {
      return {};
    }

    const entries: Record<string, number[]> = {};
    for (const [filterKey, ids] of Object.entries(parsed)) {
      const normalized = normalizeOperationsQueueIds(ids);
      if (normalized.length) {
        entries[filterKey] = normalized;
      }
    }
    return entries;
  } catch {
    return {};
  }
}

export function mergeOperationsQueueSeenEntries(
  current: Record<string, readonly number[]> | null | undefined,
  filterKey: string,
  ids: readonly number[],
): Record<string, number[]> {
  const normalizedFilterKey = String(filterKey ?? '').trim();
  if (!normalizedFilterKey) {
    return sanitizeOperationsQueueSeenEntries(current);
  }

  const existing = normalizeOperationsQueueIds(current?.[normalizedFilterKey]);
  const incoming = normalizeOperationsQueueIds(ids);
  if (!incoming.length) {
    return sanitizeOperationsQueueSeenEntries(current);
  }

  const merged = normalizeOperationsQueueIds([...existing, ...incoming]);
  return {
    ...sanitizeOperationsQueueSeenEntries(current),
    [normalizedFilterKey]: merged,
  };
}

export function writeOperationsQueueSeenEntries(
  storageKey: string | null | undefined,
  entries: Record<string, readonly number[]> | null | undefined,
): void {
  if (!storageKey) {
    return;
  }

  try {
    localStorage.setItem(storageKey, JSON.stringify(sanitizeOperationsQueueSeenEntries(entries)));
  } catch {
    // localStorage can be unavailable or full; unread indicators can still work in-memory.
  }
}

export function countOperationsUnreadIds(
  ids: readonly number[],
  seenIds: readonly number[] | null | undefined,
): number {
  const currentIds = normalizeOperationsQueueIds(ids, { cap: false });
  if (!currentIds.length) {
    return 0;
  }

  const seen = new Set(normalizeOperationsQueueIds(seenIds, { cap: false }));
  return currentIds.reduce((count, id) => count + (seen.has(id) ? 0 : 1), 0);
}

function getRovingRadioTargetIndex(
  key: string,
  currentIndex: number,
  optionCount: number,
): number | null {
  const lastIndex = optionCount - 1;
  if (lastIndex < 0) {
    return null;
  }

  switch (key) {
    case 'ArrowRight':
    case 'ArrowDown':
      return currentIndex === lastIndex ? 0 : currentIndex + 1;
    case 'ArrowLeft':
    case 'ArrowUp':
      return currentIndex === 0 ? lastIndex : currentIndex - 1;
    case 'Home':
      return 0;
    case 'End':
      return lastIndex;
    default:
      return null;
  }
}

export function handleRovingRadioKeydown<T extends string>(
  event: KeyboardEvent,
  currentIndex: number,
  options: readonly { value: T }[],
  setValue: (value: T) => void,
): void {
  const targetIndex = getRovingRadioTargetIndex(event.key, currentIndex, options.length);
  if (targetIndex === null) {
    return;
  }

  const target = options[targetIndex];
  if (!target) {
    return;
  }

  event.preventDefault();
  setValue(target.value);

  const group = (event.currentTarget as HTMLElement | null)?.closest('[role="radiogroup"]');
  const buttons = Array.from(group?.querySelectorAll<HTMLElement>('[role="radio"]') ?? []);
  requestAnimationFrame(() => buttons[targetIndex]?.focus());
}

function isOperationsRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function sanitizeOperationsQueueSeenEntries(
  entries: Record<string, readonly number[]> | null | undefined,
): Record<string, number[]> {
  if (!entries || !isOperationsRecord(entries)) {
    return {};
  }

  const sanitized: Record<string, number[]> = {};
  for (const [filterKey, ids] of Object.entries(entries)) {
    const normalized = normalizeOperationsQueueIds(ids);
    if (normalized.length) {
      sanitized[filterKey] = normalized;
    }
  }
  return sanitized;
}

function normalizeOperationsQueueIds(
  values: readonly number[] | unknown,
  options?: { cap?: boolean },
): number[] {
  if (!Array.isArray(values)) {
    return [];
  }

  const unique = new Set<number>();
  for (const value of values) {
    const normalized = Number(value);
    if (!Number.isInteger(normalized) || normalized <= 0 || unique.has(normalized)) {
      continue;
    }
    unique.add(normalized);
  }

  const normalized = Array.from(unique);
  if (options?.cap === false) {
    return normalized;
  }
  return normalized.slice(-OPERATIONS_QUEUE_SEEN_LIMIT);
}
