import { NeedsListStatus, NeedsListSummaryStatus } from '../models/needs-list.model';

export type NeedsListActionStatus = NeedsListStatus | NeedsListSummaryStatus;

export interface NeedsListActionTarget {
  label: string;
  commands: (string | number)[];
  queryParams?: Record<string, string>;
  readOnly: boolean;
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

export function toNeedsListStatusLabel(status: string | null | undefined): string {
  const normalized = String(status || '').trim();
  if (!normalized) {
    return 'Unknown';
  }
  return normalized.replaceAll('_', ' ');
}
