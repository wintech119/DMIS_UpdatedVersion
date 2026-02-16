const STATUS_LABELS: Record<string, string> = {
  DRAFT: 'Draft',
  MODIFIED: 'Modified',
  SUBMITTED: 'Submitted',
  PENDING_APPROVAL: 'Pending Approval',
  PENDING: 'Pending Approval',
  UNDER_REVIEW: 'Under Review',
  APPROVED: 'Approved',
  REJECTED: 'Rejected',
  RETURNED: 'Returned',
  ESCALATED: 'Escalated',
  IN_PREPARATION: 'In Preparation',
  IN_PROGRESS: 'In Progress',
  DISPATCHED: 'Dispatched',
  RECEIVED: 'Received',
  COMPLETED: 'Completed',
  FULFILLED: 'Fulfilled',
  CANCELLED: 'Cancelled',
  SUPERSEDED: 'Superseded'
};

function toTitleCaseStatus(status: string): string {
  return status
    .split('_')
    .filter((segment) => segment.length > 0)
    .map((segment) => segment.charAt(0).toUpperCase() + segment.slice(1).toLowerCase())
    .join(' ');
}

export function formatStatusLabel(status: string | undefined | null): string {
  if (!status) {
    return 'Unknown';
  }

  const normalized = status.toUpperCase();
  return STATUS_LABELS[normalized] ?? toTitleCaseStatus(normalized);
}
