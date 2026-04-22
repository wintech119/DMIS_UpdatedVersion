import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';

import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';

import { AuthRbacService } from '../../replenishment/services/auth-rbac.service';
import { DmisNotificationService } from '../../replenishment/services/notification.service';
import { DmisEmptyStateComponent } from '../../replenishment/shared/dmis-empty-state/dmis-empty-state.component';
import { DmisSkeletonLoaderComponent } from '../../replenishment/shared/dmis-skeleton-loader/dmis-skeleton-loader.component';
import { OpsMetricStripComponent, OpsMetricStripItem } from '../shared/ops-metric-strip.component';
import { OpsStatusChipComponent } from '../shared/ops-status-chip.component';
import { OperationsService } from '../services/operations.service';
import { RequestSummary } from '../models/operations.model';
import {
  formatOperationsAge,
  formatOperationsDateTime,
  formatOperationsLineCount,
  formatOperationsRefreshedLabel,
  formatOperationsRequestStatus,
  formatOperationsUrgency,
  buildOperationsQueueSeenStorageKey,
  countOperationsUnreadIds,
  getOperationsRequestTone,
  getOperationsTimeInStageTone,
  getOperationsUrgencyTone,
  handleRovingRadioKeydown,
  mergeOperationsQueueSeenEntries,
  mapOperationsToneToChipTone,
  OPERATIONS_QUEUE_SEARCH_MAX_LENGTH,
  OperationsTone,
  OperationsTimeInStageTone,
  readOperationsQueueSeenEntries,
  writeOperationsQueueSeenEntries,
} from '../operations-display.util';

type ReviewFilter = 'all' | 'critical' | 'high' | 'standard';

interface ReviewMetric {
  label: string;
  value: number;
  note: string;
  filter: ReviewFilter;
  accent: string;
}

interface ReviewSummary {
  total: number;
  oldest: RequestSummary | null;
  newest: RequestSummary | null;
}

const AWAITING_ACTION_STATUS: RequestSummary['status_code'] = 'UNDER_ELIGIBILITY_REVIEW';
const LOAD_ERROR_MESSAGE = 'We could not load the eligibility queue. Check your connection and try again.';

function urgencyCode(request: RequestSummary): string {
  return String(request.urgency_ind ?? '').trim().toUpperCase();
}

function requestTimestampValue(
  row: Pick<RequestSummary, 'create_dtime' | 'request_date'>,
): string | null {
  const candidates = [row.create_dtime, row.request_date];
  for (const candidate of candidates) {
    const value = typeof candidate === 'string' ? candidate.trim() : '';
    if (!value) {
      continue;
    }

    const stamp = new Date(value).getTime();
    if (Number.isFinite(stamp)) {
      return value;
    }
  }
  return null;
}

function requestTimestampMs(
  row: Pick<RequestSummary, 'create_dtime' | 'request_date'>,
  fallbackMs: number,
): number {
  const value = requestTimestampValue(row);
  if (!value) {
    return fallbackMs;
  }

  return new Date(value).getTime();
}

function oldestAgeHours(rows: readonly RequestSummary[]): number {
  if (!rows.length) {
    return 0;
  }
  const now = Date.now();
  let oldestMs = now;
  for (const row of rows) {
    const stamp = requestTimestampMs(row, now);
    if (stamp < oldestMs) {
      oldestMs = stamp;
    }
  }
  return Math.max(0, Math.floor((now - oldestMs) / 3_600_000));
}

@Component({
  selector: 'app-eligibility-review-queue',
  standalone: true,
  imports: [
    FormsModule,
    MatButtonModule,
    MatIconModule,
    MatInputModule,
    DmisEmptyStateComponent,
    DmisSkeletonLoaderComponent,
    OpsMetricStripComponent,
    OpsStatusChipComponent,
  ],
  templateUrl: './eligibility-review-queue.component.html',
  styleUrls: ['./eligibility-review-queue.component.scss', '../operations-shell.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class EligibilityReviewQueueComponent implements OnInit {
  private readonly auth = inject(AuthRbacService);
  private readonly notify = inject(DmisNotificationService);
  private readonly operationsService = inject(OperationsService);
  private readonly router = inject(Router);
  private readonly seenStorageScope = 'eligibility-review';
  private loadRequestToken = 0;

  readonly loading = signal(true);
  readonly loadError = signal<string | null>(null);
  readonly requests = signal<RequestSummary[]>([]);
  readonly searchTerm = signal('');
  readonly activeFilter = signal<ReviewFilter>('all');
  readonly seenFilters = signal<Record<string, number[]>>({});
  readonly lastRefreshedAt = signal<number>(Date.now());

  readonly lastRefreshedLabel = computed(() => formatOperationsRefreshedLabel(this.lastRefreshedAt()));

  readonly filterOptions: readonly { label: string; value: ReviewFilter }[] = [
    { label: 'Critical', value: 'critical' },
    { label: 'High', value: 'high' },
    { label: 'Standard', value: 'standard' },
    { label: 'All', value: 'all' },
  ];
  readonly searchMaxLength = OPERATIONS_QUEUE_SEARCH_MAX_LENGTH;

  // UX defense only. Authoritative queue scope lives in
  // backend/operations/contract_services.py — never treat this as an
  // authorization boundary. Keeps the UI from leaking decided items if a
  // transient contract drift emits them.
  readonly actionableRequests = computed(() =>
    this.requests().filter((request) => request.status_code === AWAITING_ACTION_STATUS),
  );

  readonly activeQueueCount = computed(() => this.actionableRequests().length);

  readonly filteredRequests = computed(() => {
    const term = this.searchTerm().trim().toLowerCase();
    const filter = this.activeFilter();

    return this.actionableRequests().filter((request) => {
      if (!this.matchesFilter(request, filter)) {
        return false;
      }

      if (!term) {
        return true;
      }

      const haystack = [
        request.tracking_no,
        request.agency_name,
        request.event_name,
        request.rqst_notes_text,
        request.review_notes_text,
        request.status_reason_desc,
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase();

      return haystack.includes(term);
    });
  });

  readonly metrics = computed<ReviewMetric[]>(() => {
    const rows = this.actionableRequests();
    return [
      { label: 'Awaiting action', value: rows.length, note: 'Needs an eligibility decision', filter: 'all', accent: '#3d4b99' },
      { label: 'Critical', value: rows.filter((row) => urgencyCode(row) === 'C').length, note: 'Immediate attention', filter: 'critical', accent: '#b42318' },
      { label: 'High', value: rows.filter((row) => urgencyCode(row) === 'H').length, note: 'Priority review lane', filter: 'high', accent: '#b7833f' },
      { label: 'Oldest waiting (h)', value: oldestAgeHours(rows), note: 'Hours since oldest submission', filter: 'standard', accent: '#6b7280' },
    ];
  });

  readonly metricStrip = computed<OpsMetricStripItem[]>(() => {
    const active = this.activeFilter();
    return this.metrics().map((metric) => ({
      label: metric.label,
      value: String(metric.value),
      hint: metric.note,
      interactive: true,
      token: metric.filter,
      active: active === metric.filter,
      accent: metric.accent,
    }));
  });

  readonly summary = computed<ReviewSummary>(() => {
    const rows = this.filteredRequests();
    return {
      total: rows.length,
      oldest: rows[rows.length - 1] ?? null,
      newest: rows[0] ?? null,
    };
  });

  readonly unreadCounts = computed<Record<ReviewFilter, number>>(() => {
    const rows = this.actionableRequests();
    const seen = this.seenFilters();

    return {
      all: 0,
      critical: countOperationsUnreadIds(this.getFilterRequestIds('critical', rows), seen['critical']),
      high: countOperationsUnreadIds(this.getFilterRequestIds('high', rows), seen['high']),
      standard: countOperationsUnreadIds(this.getFilterRequestIds('standard', rows), seen['standard']),
    };
  });

  readonly formatOperationsRequestStatus = formatOperationsRequestStatus;
  readonly formatOperationsUrgency = formatOperationsUrgency;
  readonly formatOperationsDateTime = formatOperationsDateTime;
  readonly formatOperationsAge = formatOperationsAge;
  readonly formatOperationsLineCount = formatOperationsLineCount;
  readonly getOperationsRequestTone = getOperationsRequestTone;
  readonly getOperationsUrgencyTone = getOperationsUrgencyTone;
  readonly requestTimestamp = requestTimestampValue;

  ngOnInit(): void {
    this.loadSeenFilters();
    this.loadQueue();
  }

  setFilter(filter: ReviewFilter): void {
    this.activeFilter.set(filter);
    this.markFilterSeen(filter);
  }

  onFilterKeydown(event: KeyboardEvent, index: number): void {
    handleRovingRadioKeydown(event, index, this.filterOptions, (value) => this.setFilter(value));
  }

  onSearch(value: string): void {
    this.searchTerm.set(value);
  }

  openMetric(metric: OpsMetricStripItem): void {
    if (!this.isReviewFilter(metric.token)) {
      return;
    }
    this.setFilter(metric.token);
  }

  private isReviewFilter(value: string | undefined): value is ReviewFilter {
    return value === 'all'
      || value === 'critical'
      || value === 'high'
      || value === 'standard';
  }

  openReview(request: RequestSummary): void {
    this.router.navigate(['/operations/eligibility-review', request.reliefrqst_id]);
  }

  chipTone(tone: OperationsTone): 'neutral' | 'soft' | 'critical' | 'warning' | 'success' | 'info' | 'outline' {
    return mapOperationsToneToChipTone(tone);
  }

  rowStageClass(request: RequestSummary): string {
    const urgency = urgencyCode(request);
    if (urgency === 'C') {
      return 'ops-row--critical';
    }
    if (urgency === 'H') {
      return 'ops-row--warning';
    }
    return 'ops-row--info';
  }

  stageLabel(request: RequestSummary): string {
    const urgency = urgencyCode(request);
    if (urgency === 'C') {
      return 'Critical';
    }
    if (urgency === 'H') {
      return 'High';
    }
    return 'Standard';
  }

  stagePillClass(request: RequestSummary): string {
    const urgency = urgencyCode(request);
    if (urgency === 'C') {
      return 'ops-stage-pill--critical';
    }
    if (urgency === 'H') {
      return 'ops-stage-pill--warning';
    }
    return 'ops-stage-pill--info';
  }

  timePillClass(request: RequestSummary): string {
    return `ops-time-pill--${this.timePillTone(request)}`;
  }

  timePillTone(request: RequestSummary): OperationsTimeInStageTone {
    return getOperationsTimeInStageTone(requestTimestampValue(request));
  }

  actionClass(request: RequestSummary): string {
    const urgency = urgencyCode(request);
    if (urgency === 'C') {
      return 'ops-action--critical';
    }
    if (urgency === 'H') {
      return 'ops-action--warning';
    }
    return 'ops-action--info';
  }

  actionLabel(request: RequestSummary): string {
    const urgency = urgencyCode(request);
    if (urgency === 'C') {
      return 'Review critical';
    }
    if (urgency === 'H') {
      return 'Review priority';
    }
    return 'Review request';
  }

  partyLabel(request: RequestSummary): string {
    return request.agency_name ?? `Agency ${request.agency_id}`;
  }

  hasUnread(filter: ReviewFilter): boolean {
    return filter !== 'all' && this.unreadCount(filter) > 0;
  }

  unreadCount(filter: ReviewFilter): number {
    return this.unreadCounts()[filter] ?? 0;
  }

  filterAriaLabel(label: string, filter: ReviewFilter): string {
    const unread = this.unreadCount(filter);
    if (!unread) {
      return label;
    }
    return `${label}, ${unread} new ${unread === 1 ? 'request' : 'requests'}`;
  }

  trackByRequestId(_index: number, request: RequestSummary): number {
    return request.reliefrqst_id;
  }

  retryLoad(): void {
    if (this.loading()) {
      return;
    }
    this.loadQueue();
  }

  private loadQueue(): void {
    const requestToken = ++this.loadRequestToken;
    this.loading.set(true);
    this.loadError.set(null);

    this.operationsService.getEligibilityQueue().subscribe({
      next: (response) => {
        if (requestToken !== this.loadRequestToken) {
          return;
        }

        const now = Date.now();
        const rows = [...response.results].sort((left, right) =>
          requestTimestampMs(right, now) - requestTimestampMs(left, now),
        );
        this.requests.set(rows);
        this.syncSeenFilterForActiveView();
        this.lastRefreshedAt.set(Date.now());
        this.loading.set(false);
      },
      error: () => {
        if (requestToken !== this.loadRequestToken) {
          return;
        }

        this.requests.set([]);
        this.loadError.set(LOAD_ERROR_MESSAGE);
        this.loading.set(false);
        this.notify.showNetworkError(LOAD_ERROR_MESSAGE, () => this.retryLoad());
      },
    });
  }

  private getSeenStorageKey(): string | null {
    return buildOperationsQueueSeenStorageKey(this.seenStorageScope, this.auth.currentUserRef());
  }

  private loadSeenFilters(): void {
    this.seenFilters.set(readOperationsQueueSeenEntries(this.getSeenStorageKey()));
  }

  private markFilterSeen(filter: ReviewFilter): void {
    if (filter === 'all') {
      return;
    }

    const ids = this.getFilterRequestIds(filter);
    if (!ids.length) {
      return;
    }

    const next = mergeOperationsQueueSeenEntries(this.seenFilters(), filter, ids);
    this.seenFilters.set(next);
    writeOperationsQueueSeenEntries(this.getSeenStorageKey(), next);
  }

  private syncSeenFilterForActiveView(): void {
    const filter = this.activeFilter();
    if (filter !== 'all') {
      this.markFilterSeen(filter);
    }
  }

  private getFilterRequestIds(
    filter: Exclude<ReviewFilter, 'all'>,
    rows: readonly RequestSummary[] = this.actionableRequests(),
  ): number[] {
    return rows
      .filter((request) => this.matchesFilter(request, filter))
      .map((request) => request.reliefrqst_id);
  }

  private matchesFilter(request: RequestSummary, filter: ReviewFilter): boolean {
    const urgency = urgencyCode(request);
    switch (filter) {
      case 'critical':
        return urgency === 'C';
      case 'high':
        return urgency === 'H';
      case 'standard':
        return urgency !== 'C' && urgency !== 'H';
      case 'all':
      default:
        return true;
    }
  }
}
