import { AllocationSourceType, ExecutionSelectedMethod, ExecutionStatus } from '../models/allocation-dispatch.model';

const OVERRIDE_APPROVER_ROLE_CODES = new Set([
  'LOGISTICS',
  'LOGISTICS_MANAGER',
  'ODPEM_LOGISTICS_MANAGER',
  'SYSTEM_ADMINISTRATOR',
  'EXECUTIVE',
  'ODPEM_DIR_PEOD',
  'SENIOR_DIRECTOR',
  'SENIOR_DIRECTOR_DONATIONS',
  'DIRECTOR_PEOD',
  'TST_LOGISTICS_MANAGER',
  'TST_DIR_PEOD',
]);

export function normalizeRoleCode(value: unknown): string {
  return String(value ?? '').trim().toUpperCase().replace(/[-\s]+/g, '_');
}

export function isOverrideApproverRole(roles: string[]): boolean {
  return roles.some((role) => OVERRIDE_APPROVER_ROLE_CODES.has(normalizeRoleCode(role)));
}

export function formatExecutionStatus(status: string | null | undefined): string {
  const normalized = String(status ?? '').trim().toUpperCase();
  switch (normalized) {
    case 'PREPARING':
      return 'Preparing';
    case 'PENDING_OVERRIDE_APPROVAL':
      return 'Pending Override Approval';
    case 'COMMITTED':
      return 'Committed';
    case 'DISPATCHED':
      return 'Dispatched';
    case 'RECEIVED':
      return 'Received';
    case 'CANCELLED':
      return 'Cancelled';
    default:
      return normalized ? normalized.replace(/_/g, ' ') : 'Not Started';
  }
}

export function formatPackageStatus(status: string | null | undefined): string {
  const normalized = String(status ?? '').trim().toUpperCase();
  switch (normalized) {
    case 'A':
      return 'Draft Allocation';
    case 'P':
      return 'Reserved';
    case 'C':
      return 'Committed';
    case 'V':
      return 'Verified';
    case 'D':
      return 'Dispatched';
    case 'R':
      return 'Released';
    default:
      return normalized || 'Not Started';
  }
}

export function formatExecutionMethod(method: string | null | undefined): string {
  const normalized = String(method ?? '').trim().toUpperCase();
  switch (normalized) {
    case 'FEFO':
      return 'FEFO';
    case 'FIFO':
      return 'FIFO';
    case 'MIXED':
      return 'Mixed';
    case 'MANUAL':
      return 'Manual';
    default:
      return normalized || 'System Recommended';
  }
}

export function formatSourceType(sourceType: AllocationSourceType | string | null | undefined): string {
  const normalized = String(sourceType ?? '').trim().toUpperCase();
  switch (normalized) {
    case 'ON_HAND':
      return 'On Hand';
    case 'TRANSFER':
      return 'Transfer';
    case 'DONATION':
      return 'Donation';
    case 'PROCUREMENT':
      return 'Procurement';
    default:
      return normalized || 'Unknown';
  }
}
