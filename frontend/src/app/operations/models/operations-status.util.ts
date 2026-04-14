import { PackageStatusCode, RequestStatusCode, UrgencyCode } from './operations.model';

// ── Request status ─────────────────────────────────────────────────

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

export function formatRequestStatus(code: RequestStatusCode | string): string {
  const key = String(code ?? '').toUpperCase();
  return REQUEST_STATUS_LABELS[key] ?? 'Unknown';
}

export function getRequestStatusColor(code: RequestStatusCode | string): string {
  const key = String(code ?? '').toUpperCase();
  switch (key) {
    case 'DRAFT': return 'var(--color-text-secondary)';
    case 'SUBMITTED':
    case 'UNDER_ELIGIBILITY_REVIEW': return 'var(--color-warning)';
    case 'CANCELLED': return 'var(--color-text-tertiary)';
    case 'APPROVED_FOR_FULFILLMENT': return 'var(--color-info)';
    case 'REJECTED': return 'var(--color-critical)';
    case 'PARTIALLY_FULFILLED': return 'var(--color-warning)';
    case 'FULFILLED': return 'var(--color-success)';
    case 'INELIGIBLE': return 'var(--color-critical)';
    default: return 'var(--color-text-secondary)';
  }
}

export function getRequestStatusCssClass(code: RequestStatusCode | string): string {
  const key = String(code ?? '').toUpperCase();
  switch (key) {
    case 'DRAFT': return 'status-draft';
    case 'SUBMITTED':
    case 'UNDER_ELIGIBILITY_REVIEW': return 'status-awaiting';
    case 'CANCELLED': return 'status-cancelled';
    case 'APPROVED_FOR_FULFILLMENT': return 'status-submitted';
    case 'REJECTED': return 'status-denied';
    case 'PARTIALLY_FULFILLED': return 'status-partial';
    case 'FULFILLED': return 'status-filled';
    case 'INELIGIBLE': return 'status-ineligible';
    default: return 'status-unknown';
  }
}

// ── Package status ─────────────────────────────────────────────────

const PKG_STATUS_LABELS: Record<string, string> = {
  // Legacy single-char codes
  A: 'Draft',
  P: 'Ready for Dispatch',
  V: 'Ready for Dispatch',
  D: 'Dispatched',
  C: 'Completed',
  // Operations-layer status codes
  DRAFT: 'Draft',
  PENDING_OVERRIDE_APPROVAL: 'Override Pending',
  COMMITTED: 'Ready for Dispatch',
  READY_FOR_DISPATCH: 'Ready for Dispatch',
  DISPATCHED: 'Dispatched',
  RECEIVED: 'Received',
  CANCELLED: 'Cancelled',
  // Staged fulfillment status codes
  CONSOLIDATING: 'Consolidating at Staging',
  READY_FOR_PICKUP: 'Ready for Pickup',
  SPLIT: 'Split',
};

export function formatPackageStatus(code: PackageStatusCode | string): string {
  const key = String(code ?? '').trim().toUpperCase();
  return PKG_STATUS_LABELS[key] ?? PKG_STATUS_LABELS[code] ?? 'Unknown';
}

export function getPackageStatusCssClass(code: PackageStatusCode | string): string {
  const key = String(code ?? '').trim().toUpperCase();
  switch (key) {
    case 'A':
    case 'DRAFT': return 'status-draft';
    case 'P':
    case 'V':
    case 'COMMITTED':
    case 'READY_FOR_DISPATCH':
    case 'READY_FOR_PICKUP':
    case 'CONSOLIDATING':
    case 'PENDING_OVERRIDE_APPROVAL': return 'status-awaiting';
    case 'D':
    case 'DISPATCHED': return 'status-submitted';
    case 'C':
    case 'RECEIVED': return 'status-filled';
    case 'SPLIT': return 'status-split';
    case 'CANCELLED': return 'status-cancelled';
    default: return 'status-unknown';
  }
}

// ── Urgency ────────────────────────────────────────────────────────

const URGENCY_LABELS: Record<string, string> = {
  C: 'Critical',
  H: 'High',
  M: 'Medium',
  L: 'Low',
};

export function formatUrgency(code: UrgencyCode | string | null): string {
  return URGENCY_LABELS[code ?? ''] ?? 'Unknown';
}

export function getUrgencyCssClass(code: UrgencyCode | string | null): string {
  switch (code) {
    case 'C': return 'urgency-critical';
    case 'H': return 'urgency-high';
    case 'M': return 'urgency-medium';
    case 'L': return 'urgency-low';
    default: return '';
  }
}

// ── Allocation method ──────────────────────────────────────────────

export function formatAllocationMethod(value: string | null | undefined): string {
  const normalized = String(value ?? '').trim().toUpperCase();
  switch (normalized) {
    case 'FEFO': return 'First Expired, First Out';
    case 'FIFO': return 'First In, First Out';
    case 'MIXED': return 'Mixed';
    case 'MANUAL': return 'Manual Override';
    default: return normalized || 'Not set';
  }
}

// ── Override approval ──────────────────────────────────────────────

const OVERRIDE_APPROVER_ROLES = new Set([
  'LOGISTICS_MANAGER',
  'LOGISTICS_OFFICER',
  'EXECUTIVE',
  'SYSTEM_ADMINISTRATOR',
]);

export function isOverrideApproverRole(roles: string[]): boolean {
  return roles.some((role) => OVERRIDE_APPROVER_ROLES.has(role.trim().toUpperCase()));
}

// ── Source type ───────────────────────────────────────────────────

export function formatSourceType(sourceType: string | null | undefined): string {
  const normalized = String(sourceType ?? '').trim().toUpperCase();
  switch (normalized) {
    case 'ON_HAND': return 'On Hand';
    case 'TRANSFER': return 'Transfer';
    case 'DONATION': return 'Donation';
    case 'PROCUREMENT': return 'Procurement';
    default: return normalized || 'Unknown';
  }
}

// ── Execution status ─────────────────────────────────────────────

export function formatExecutionStatus(status: string | null | undefined): string {
  const normalized = String(status ?? '').trim().toUpperCase();
  switch (normalized) {
    case 'PREPARING': return 'Preparing';
    case 'PENDING_OVERRIDE_APPROVAL': return 'Pending Override Approval';
    case 'COMMITTED': return 'Committed';
    case 'DISPATCHED': return 'Dispatched';
    case 'OVERRIDE_APPROVED': return 'Override Approved';
    case '': return 'Not started';
    default: return normalized;
  }
}

// ── Staged fulfillment ───────────────────────────────────────────

export function formatFulfillmentMode(mode: string | null | undefined): string {
  const normalized = String(mode ?? '').trim().toUpperCase();
  switch (normalized) {
    case 'DIRECT': return 'Direct dispatch';
    case 'DELIVER_FROM_STAGING': return 'Deliver from staging';
    case 'PICKUP_AT_STAGING': return 'Pickup at staging';
    case '': return 'Not set';
    default: return normalized;
  }
}

export function formatConsolidationStatus(status: string | null | undefined): string {
  const normalized = String(status ?? '').trim().toUpperCase();
  switch (normalized) {
    case 'AWAITING_LEGS': return 'Awaiting legs';
    case 'LEGS_IN_TRANSIT': return 'Legs in transit';
    case 'PARTIALLY_RECEIVED': return 'Partially received';
    case 'ALL_RECEIVED': return 'All received';
    case 'PARTIAL_RELEASE_REQUESTED': return 'Partial release requested';
    case '': return 'Not started';
    default: return normalized;
  }
}

export function formatConsolidationLegStatus(status: string | null | undefined): string {
  const normalized = String(status ?? '').trim().toUpperCase();
  switch (normalized) {
    case 'PLANNED': return 'Planned';
    case 'IN_TRANSIT': return 'In transit';
    case 'RECEIVED_AT_STAGING': return 'Received at staging';
    case 'CANCELLED': return 'Cancelled';
    case '': return 'Not set';
    default: return normalized;
  }
}

export function formatStagingSelectionBasis(basis: string | null | undefined): string {
  const normalized = String(basis ?? '').trim().toUpperCase();
  switch (normalized) {
    case 'SAME_PARISH': return 'Same parish as destination';
    case 'PROXIMITY_MATRIX': return 'Nearest staging hub (proximity)';
    case 'ALPHABETICAL_FALLBACK': return 'Alphabetical fallback';
    case 'MANUAL_OVERRIDE': return 'Manual override';
    case '': return 'Not set';
    default: return normalized;
  }
}
