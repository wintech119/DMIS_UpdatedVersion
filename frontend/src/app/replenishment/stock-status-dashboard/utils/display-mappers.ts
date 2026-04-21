import {
  DisplaySeverity,
  DisplayStatus,
  EventPhase,
  SeverityLevel
} from '../../models/stock-status.model';

const SEVERITY_MAP: Record<SeverityLevel, DisplaySeverity> = {
  CRITICAL: 'CRITICAL',
  WARNING: 'WARNING',
  WATCH: 'WARNING',
  OK: 'GOOD'
};

const STATUS_MAP: Record<string, DisplayStatus> = {
  DRAFT: 'DRAFT',
  MODIFIED: 'MODIFIED',
  RETURNED: 'MODIFIED',
  SUBMITTED: 'SUBMITTED',
  PENDING: 'SUBMITTED',
  PENDING_APPROVAL: 'SUBMITTED',
  UNDER_REVIEW: 'SUBMITTED',
  APPROVED: 'APPROVED',
  REJECTED: 'REJECTED',
  IN_PROGRESS: 'IN_PROGRESS',
  IN_PREPARATION: 'IN_PROGRESS',
  DISPATCHED: 'IN_PROGRESS',
  RECEIVED: 'IN_PROGRESS',
  FULFILLED: 'FULFILLED',
  COMPLETED: 'FULFILLED',
  CANCELLED: 'SUPERSEDED',
  SUPERSEDED: 'SUPERSEDED'
};

export function toDisplaySeverity(internal: SeverityLevel | null | undefined): DisplaySeverity {
  if (!internal) {
    return 'GOOD';
  }
  const mapped = SEVERITY_MAP[internal];
  if (!mapped) {
    console.warn('[ep02:display-mapper]', { source: 'severity', value: internal });
    return 'CRITICAL';
  }
  return mapped;
}

export function toDisplayStatus(backendStatus: string | null | undefined): DisplayStatus {
  if (!backendStatus) {
    return 'DRAFT';
  }
  const key = String(backendStatus).trim().toUpperCase();
  const mapped = STATUS_MAP[key];
  if (!mapped) {
    console.warn('[ep02:display-mapper]', { source: 'status', value: backendStatus });
    return 'UNKNOWN';
  }
  return mapped;
}

export interface FreshnessThresholds {
  highMaxHours: number;
  mediumMaxHours: number;
}

/**
 * Freshness thresholds per event phase.
 *
 * TODO: Mirrors backend `backend/replenishment/rules.py::FRESHNESS_THRESHOLDS`.
 * Re-sync if backend changes. A pinning unit test in the dashboard spec guards
 * against drift by asserting these exact values.
 */
const FRESHNESS_THRESHOLDS: Record<EventPhase, FreshnessThresholds> = {
  SURGE: { highMaxHours: 2, mediumMaxHours: 4 },
  STABILIZED: { highMaxHours: 6, mediumMaxHours: 12 },
  BASELINE: { highMaxHours: 24, mediumMaxHours: 48 }
};

export function getFreshnessThresholdsForPhase(phase: EventPhase): FreshnessThresholds {
  return FRESHNESS_THRESHOLDS[phase] ?? FRESHNESS_THRESHOLDS.BASELINE;
}

const PHASE_INTERVAL_MS: Record<EventPhase, number> = {
  SURGE: 300_000,
  STABILIZED: 1_800_000,
  BASELINE: 7_200_000
};

export function phaseToIntervalMs(phase: EventPhase): number {
  return PHASE_INTERVAL_MS[phase] ?? PHASE_INTERVAL_MS.BASELINE;
}
