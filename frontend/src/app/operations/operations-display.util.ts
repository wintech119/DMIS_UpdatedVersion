export type OperationsTone = 'draft' | 'review' | 'success' | 'warning' | 'danger' | 'muted';

const REQUEST_STATUS_LABELS: Record<number, string> = {
  0: 'Draft',
  1: 'Under Review',
  2: 'Cancelled',
  3: 'Submitted',
  4: 'Rejected',
  5: 'Partially Fulfilled',
  6: 'Closed',
  7: 'Fulfilled',
  8: 'Ineligible',
};

const REQUEST_STATUS_TONES: Record<number, OperationsTone> = {
  0: 'draft',
  1: 'review',
  2: 'muted',
  3: 'review',
  4: 'danger',
  5: 'warning',
  6: 'muted',
  7: 'success',
  8: 'danger',
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
  const normalized = Number(code);
  return REQUEST_STATUS_LABELS[normalized] ?? 'Unknown';
}

export function getOperationsRequestTone(code: number | string | null | undefined): OperationsTone {
  const normalized = Number(code);
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
    return `${Math.max(1, minutes)}m`;
  }
  const hours = Math.round(minutes / 60);
  if (hours < 24) {
    return `${hours}h`;
  }
  const days = Math.round(hours / 24);
  return `${days}d`;
}

export function formatOperationsLineCount(count: number): string {
  return count === 1 ? '1 item' : `${count} items`;
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
