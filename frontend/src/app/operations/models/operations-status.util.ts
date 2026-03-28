import { PackageStatusCode, RequestStatusCode, UrgencyCode } from './operations.model';

// ── Request status ─────────────────────────────────────────────────

const REQUEST_STATUS_LABELS: Record<number, string> = {
  0: 'Draft',
  1: 'Under Review',
  2: 'Cancelled',
  3: 'Approved',
  4: 'Rejected',
  5: 'Partially Filled',
  6: 'Closed',
  7: 'Filled',
  8: 'Ineligible',
};

export function formatRequestStatus(code: RequestStatusCode | number): string {
  return REQUEST_STATUS_LABELS[code] ?? 'Unknown';
}

export function getRequestStatusColor(code: RequestStatusCode | number): string {
  switch (code) {
    case 0: return 'var(--color-text-secondary)';
    case 1: return 'var(--color-warning)';
    case 2: return 'var(--color-text-tertiary)';
    case 3: return 'var(--color-info)';
    case 4: return 'var(--color-critical)';
    case 5: return 'var(--color-warning)';
    case 6: return 'var(--color-text-tertiary)';
    case 7: return 'var(--color-success)';
    case 8: return 'var(--color-critical)';
    default: return 'var(--color-text-secondary)';
  }
}

export function getRequestStatusCssClass(code: RequestStatusCode | number): string {
  switch (code) {
    case 0: return 'status-draft';
    case 1: return 'status-awaiting';
    case 2: return 'status-cancelled';
    case 3: return 'status-submitted';
    case 4: return 'status-denied';
    case 5: return 'status-partial';
    case 6: return 'status-closed';
    case 7: return 'status-filled';
    case 8: return 'status-ineligible';
    default: return 'status-unknown';
  }
}

// ── Package status ─────────────────────────────────────────────────

const PKG_STATUS_LABELS: Record<string, string> = {
  A: 'Draft',
  P: 'Ready for Dispatch',
  D: 'Dispatched',
  C: 'Completed',
};

export function formatPackageStatus(code: PackageStatusCode | string): string {
  return PKG_STATUS_LABELS[code] ?? 'Unknown';
}

export function getPackageStatusCssClass(code: PackageStatusCode | string): string {
  switch (code) {
    case 'A': return 'status-draft';
    case 'P': return 'status-awaiting';
    case 'D': return 'status-submitted';
    case 'C': return 'status-filled';
    default: return 'status-unknown';
  }
}

// ── Item status ────────────────────────────────────────────────────

const ITEM_STATUS_LABELS: Record<string, string> = {
  R: 'Requested',
  P: 'Partial',
  F: 'Fulfilled',
};

export function formatItemStatus(code: string): string {
  return ITEM_STATUS_LABELS[code] ?? 'Unknown';
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
