export type OperationsTone = 'draft' | 'review' | 'success' | 'warning' | 'danger' | 'muted';

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
  APPROVED_FOR_FULFILLMENT: 'review',
  PARTIALLY_FULFILLED: 'warning',
  FULFILLED: 'success',
  INELIGIBLE: 'danger',
  REJECTED: 'danger',
  CANCELLED: 'muted',
};

const PACKAGE_STATUS_LABELS: Record<string, string> = {
  A: 'Draft',
  P: 'Pending',
  D: 'Dispatched',
  C: 'Completed',
};

const PACKAGE_STATUS_TONES: Record<string, OperationsTone> = {
  A: 'draft',
  P: 'review',
  D: 'warning',
  C: 'success',
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
  M: 'review',
  L: 'muted',
};

export function formatOperationsRequestStatus(code: number | string | null | undefined): string {
  const normalized = String(code ?? '').trim().toUpperCase();
  return REQUEST_STATUS_LABELS[normalized] ?? 'Unknown';
}

export function getOperationsRequestTone(code: number | string | null | undefined): OperationsTone {
  const normalized = String(code ?? '').trim().toUpperCase();
  return REQUEST_STATUS_TONES[normalized] ?? 'muted';
}

export function formatOperationsPackageStatus(code: string | null | undefined): string {
  const normalized = String(code ?? '').trim().toUpperCase();
  return PACKAGE_STATUS_LABELS[normalized] ?? 'Unknown';
}

export function getOperationsPackageTone(code: string | null | undefined): OperationsTone {
  const normalized = String(code ?? '').trim().toUpperCase();
  return PACKAGE_STATUS_TONES[normalized] ?? 'muted';
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

export function formatOperationsLineCount(count: number): string {
  return count === 1 ? '1 item' : `${count} items`;
}

const REQUEST_MODE_LABELS: Record<string, string> = {
  SELF: 'Self',
  SUBORDINATE: 'Subordinate',
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
