import { HorizonSummaryBucket, NeedsListStatus, NeedsListSummaryStatus } from '../models/needs-list.model';

export type NeedsListActionStatus = NeedsListStatus | NeedsListSummaryStatus;

export interface NeedsListActionTarget {
  label: string;
  commands: (string | number)[];
  queryParams?: Record<string, string>;
  readOnly: boolean;
}

export interface HorizonActionTarget {
  horizon: 'A' | 'B' | 'C';
  label: string;
  icon: string;
  commands: (string | number)[];
}

export interface HorizonSummary {
  horizon_a: HorizonSummaryBucket;
  horizon_b: HorizonSummaryBucket;
  horizon_c: HorizonSummaryBucket;
}

export function getNeedsListActionTarget(
  id: string,
  status: NeedsListActionStatus
): NeedsListActionTarget {
  const normalized = String(status || '').trim().toUpperCase();

  switch (normalized) {
    case 'DRAFT':
    case 'MODIFIED':
    case 'RETURNED':
      return {
        label: 'Edit Draft',
        commands: ['/replenishment/needs-list', id, 'wizard'],
        queryParams: { step: 'preview' },
        readOnly: false
      };
    case 'SUBMITTED':
    case 'PENDING':
    case 'PENDING_APPROVAL':
    case 'UNDER_REVIEW':
      return {
        label: 'View Details',
        commands: ['/replenishment/needs-list', id, 'review'],
        readOnly: true
      };
    case 'APPROVED':
    case 'IN_PROGRESS':
    case 'IN_PREPARATION':
    case 'DISPATCHED':
    case 'RECEIVED':
      return {
        label: 'Track Fulfillment',
        commands: ['/replenishment/needs-list', id, 'track'],
        readOnly: true
      };
    case 'FULFILLED':
    case 'COMPLETED':
      return {
        label: 'View History',
        commands: ['/replenishment/needs-list', id, 'history'],
        readOnly: true
      };
    case 'REJECTED':
      return {
        label: 'View Rejection',
        commands: ['/replenishment/needs-list', id, 'review'],
        queryParams: { rejected: 'true' },
        readOnly: true
      };
    case 'ESCALATED':
      return {
        label: 'View Escalation',
        commands: ['/replenishment/needs-list', id, 'review'],
        queryParams: { escalated: 'true' },
        readOnly: true
      };
    case 'SUPERSEDED':
      return {
        label: 'View Superseded',
        commands: ['/replenishment/needs-list', id, 'superseded'],
        readOnly: true
      };
    case 'CANCELLED':
      return {
        label: 'View Cancelled',
        commands: ['/replenishment/needs-list', id, 'history'],
        readOnly: true
      };
    default:
      return {
        label: 'View Details',
        commands: ['/replenishment/needs-list', id, 'review'],
        readOnly: true
      };
  }
}

const EXECUTION_STATUSES: ReadonlySet<string> = new Set([
  'APPROVED', 'IN_PROGRESS', 'IN_PREPARATION'
]);

export function getHorizonActionTargets(
  id: string,
  status: NeedsListActionStatus,
  horizonSummary: HorizonSummary | undefined
): HorizonActionTarget[] {
  const normalized = String(status || '').trim().toUpperCase();
  if (!EXECUTION_STATUSES.has(normalized) || !horizonSummary) {
    return [];
  }

  const targets: HorizonActionTarget[] = [];

  if (horizonSummary.horizon_a.count > 0) {
    targets.push({
      horizon: 'A',
      label: 'Draft Transfers',
      icon: 'local_shipping',
      commands: ['/replenishment/needs-list', id, 'transfers']
    });
  }

  if (horizonSummary.horizon_b.count > 0) {
    targets.push({
      horizon: 'B',
      label: 'Allocate Donations',
      icon: 'volunteer_activism',
      commands: ['/replenishment/needs-list', id, 'donations']
    });
  }

  if (horizonSummary.horizon_c.count > 0) {
    targets.push({
      horizon: 'C',
      label: 'Export Procurement',
      icon: 'shopping_cart',
      commands: ['/replenishment/needs-list', id, 'procurement']
    });
  }

  return targets;
}

const STATUS_LABELS: Record<string, string> = {
  DRAFT: 'Draft',
  MODIFIED: 'Modified',
  RETURNED: 'Returned',
  PENDING_APPROVAL: 'Pending Approval',
  APPROVED: 'Approved',
  REJECTED: 'Rejected',
  IN_PROGRESS: 'In Progress',
  FULFILLED: 'Fulfilled',
  SUPERSEDED: 'Superseded',
  CANCELLED: 'Cancelled',
  SUBMITTED: 'Submitted',
  PENDING: 'Pending',
  UNDER_REVIEW: 'Under Review',
  IN_PREPARATION: 'In Preparation',
  DISPATCHED: 'Dispatched',
  RECEIVED: 'Received',
  COMPLETED: 'Completed',
  ESCALATED: 'Escalated'
};

export function toNeedsListStatusLabel(status: string | null | undefined): string {
  const normalized = String(status || '').trim().toUpperCase();
  if (!normalized) {
    return 'Unknown';
  }
  return STATUS_LABELS[normalized] ?? normalized.replaceAll('_', ' ');
}
