import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';

import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';

import { AuthRbacService } from '../../replenishment/services/auth-rbac.service';
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
  formatRequestMode,
  buildOperationsQueueSeenStorageKey,
  countOperationsUnreadIds,
  getOperationsRequestTone,
  getOperationsTimeInStageTone,
  getOperationsUrgencyTone,
  handleRovingRadioKeydown,
  mergeOperationsQueueSeenEntries,
  mapOperationsToneToChipTone,
  OperationsTone,
  OperationsTimeInStageTone,
  readOperationsQueueSeenEntries,
  writeOperationsQueueSeenEntries,
} from '../operations-display.util';

type RequestFilter = 'all' | 'draft' | 'review' | 'approved' | 'dispatched' | 'closed';
type RequestStatusGroup = RequestFilter | 'other';

interface QueueMetric {
  label: string;
  value: number;
  filter: RequestFilter;
  tone: 'draft' | 'review' | 'success' | 'warning' | 'danger' | 'muted';
  note: string;
}

@Component({
  selector: 'app-relief-request-list',
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
  templateUrl: './relief-request-list.component.html',
  styleUrls: ['./relief-request-list.component.scss', '../operations-shell.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ReliefRequestListComponent implements OnInit {
  private readonly auth = inject(AuthRbacService);
  private readonly operationsService = inject(OperationsService);
  private readonly router = inject(Router);
  private readonly seenStorageScope = 'relief-requests';

  readonly loading = signal(true);
  readonly requests = signal<RequestSummary[]>([]);
  readonly searchTerm = signal('');
  readonly activeFilter = signal<RequestFilter>('all');
  readonly seenFilters = signal<Record<string, number[]>>({});
  readonly lastRefreshedAt = signal<number>(Date.now());

  readonly activeQueueCount = computed(() => this.requests().length);
  readonly lastRefreshedLabel = computed(() => formatOperationsRefreshedLabel(this.lastRefreshedAt()));

  readonly filterOptions: readonly { label: string; value: RequestFilter }[] = [
    { label: 'Draft', value: 'draft' },
    { label: 'Review', value: 'review' },
    { label: 'Approved', value: 'approved' },
    { label: 'Dispatched', value: 'dispatched' },
    { label: 'Closed', value: 'closed' },
    { label: 'All', value: 'all' },
  ];

  readonly filteredRequests = computed(() => {
    const term = this.searchTerm().trim().toLowerCase();
    const filter = this.activeFilter();

    return this.requests().filter((request) => {
      const statusGroup = this.getStatusGroup(request);
      if (filter !== 'all' && statusGroup !== filter) {
        return false;
      }

      if (!term) {
        return true;
      }

      const haystack = [
        request.tracking_no,
        request.agency_name,
        request.event_name,
        request.status_label,
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

  readonly metrics = computed<QueueMetric[]>(() => {
    const rows = this.requests();
    const draft = rows.filter((row) => row.status_code === 'DRAFT').length;
    const review = rows.filter((row) => this.getStatusGroup(row) === 'review').length;
    const approved = rows.filter((row) => this.getStatusGroup(row) === 'approved').length;
    const dispatched = rows.filter((row) => this.getStatusGroup(row) === 'dispatched').length;

    return [
      { label: 'Drafts', value: draft, filter: 'draft', tone: 'draft', note: 'Unsubmitted and editable' },
      { label: 'In Review', value: review, filter: 'review', tone: 'review', note: 'Queued for decision' },
      { label: 'Approved', value: approved, filter: 'approved', tone: 'warning', note: 'Awaiting fulfillment' },
      { label: 'Dispatched', value: dispatched, filter: 'dispatched', tone: 'success', note: 'Packages on the road' },
    ];
  });

  readonly metricStrip = computed<OpsMetricStripItem[]>(() => {
    const accentByFilter: Record<RequestFilter, string> = {
      all: '#6b7280',
      draft: '#3d4b99',
      review: '#b7833f',
      approved: '#7a4fd1',
      dispatched: '#2e8a48',
      closed: '#6b7280',
    };
    const active = this.activeFilter();
    return this.metrics().map((metric) => ({
      label: metric.label,
      value: String(metric.value),
      hint: metric.note,
      interactive: true,
      token: metric.filter,
      active: active === metric.filter,
      accent: accentByFilter[metric.filter],
    }));
  });

  readonly statusSummary = computed<{
    total: number;
    critical: number;
    high: number;
    newest: RequestSummary | null;
  }>(() => {
    const rows = this.filteredRequests();
    return {
      total: rows.length,
      critical: rows.filter((row) => String(row.urgency_ind ?? '').toUpperCase() === 'C').length,
      high: rows.filter((row) => String(row.urgency_ind ?? '').toUpperCase() === 'H').length,
      newest: rows[0] ?? null,
    };
  });

  readonly unreadCounts = computed<Record<RequestFilter, number>>(() => {
    const rows = this.requests();
    const seen = this.seenFilters();

    return {
      all: 0,
      draft: countOperationsUnreadIds(this.getFilterRequestIds('draft', rows), seen['draft']),
      review: countOperationsUnreadIds(this.getFilterRequestIds('review', rows), seen['review']),
      approved: countOperationsUnreadIds(this.getFilterRequestIds('approved', rows), seen['approved']),
      dispatched: countOperationsUnreadIds(this.getFilterRequestIds('dispatched', rows), seen['dispatched']),
      closed: countOperationsUnreadIds(this.getFilterRequestIds('closed', rows), seen['closed']),
    };
  });

  readonly formatOperationsRequestStatus = formatOperationsRequestStatus;
  readonly formatOperationsUrgency = formatOperationsUrgency;
  readonly formatOperationsAge = formatOperationsAge;
  readonly formatOperationsDateTime = formatOperationsDateTime;
  readonly formatOperationsLineCount = formatOperationsLineCount;
  readonly formatRequestMode = formatRequestMode;
  readonly getOperationsRequestTone = getOperationsRequestTone;
  readonly getOperationsUrgencyTone = getOperationsUrgencyTone;

  ngOnInit(): void {
    this.loadSeenFilters();
    this.loadRequests();
  }

  setFilter(filter: RequestFilter): void {
    this.activeFilter.set(filter);
    this.markFilterSeen(filter);
  }

  onFilterKeydown(event: KeyboardEvent, index: number): void {
    handleRovingRadioKeydown(event, index, this.filterOptions, (value) => this.setFilter(value));
  }

  onSearch(value: string): void {
    this.searchTerm.set(value);
  }

  newRequest(): void {
    this.router.navigateByUrl('/operations/relief-requests/new');
  }

  openRequest(request: RequestSummary): void {
    this.router.navigate(['/operations/relief-requests', request.reliefrqst_id]);
  }

  openMetric(metric: OpsMetricStripItem): void {
    if (!this.isRequestFilter(metric.token)) {
      return;
    }
    this.setFilter(metric.token);
  }

  chipTone(tone: OperationsTone): 'neutral' | 'soft' | 'critical' | 'warning' | 'success' | 'info' | 'outline' {
    return mapOperationsToneToChipTone(tone);
  }

  rowStageClass(request: RequestSummary): string {
    switch (this.getStatusGroup(request)) {
      case 'draft': return 'ops-row--drafts';
      case 'review': return 'ops-row--info';
      case 'approved': return 'ops-row--preparing';
      case 'dispatched': return 'ops-row--transit';
      case 'closed': return 'ops-row--completed';
      default: return 'ops-row--neutral';
    }
  }

  stageLabel(request: RequestSummary): string {
    switch (this.getStatusGroup(request)) {
      case 'draft': return 'Draft';
      case 'review': return 'In Review';
      case 'approved': return 'Approved';
      case 'dispatched': return 'Dispatched';
      case 'closed': return 'Closed';
      default: return 'Other';
    }
  }

  stagePillClass(request: RequestSummary): string {
    switch (this.getStatusGroup(request)) {
      case 'draft': return 'ops-stage-pill--drafts';
      case 'review': return 'ops-stage-pill--info';
      case 'approved': return 'ops-stage-pill--preparing';
      case 'dispatched': return 'ops-stage-pill--transit';
      case 'closed': return 'ops-stage-pill--completed';
      default: return 'ops-stage-pill--neutral';
    }
  }

  timePillClass(request: RequestSummary): string {
    return `ops-time-pill--${this.timePillTone(request)}`;
  }

  timePillTone(request: RequestSummary): OperationsTimeInStageTone {
    const group = this.getStatusGroup(request);
    if (group === 'closed' || group === 'dispatched') {
      return 'fresh';
    }
    return getOperationsTimeInStageTone(request.create_dtime ?? request.request_date ?? null);
  }

  actionClass(request: RequestSummary): string {
    switch (this.getStatusGroup(request)) {
      case 'draft': return 'ops-action--drafts';
      case 'review': return 'ops-action--info';
      case 'approved': return 'ops-action--preparing';
      case 'dispatched': return 'ops-action--transit';
      case 'closed': return 'ops-action--completed';
      default: return 'ops-action--neutral';
    }
  }

  actionLabel(request: RequestSummary): string {
    switch (this.getStatusGroup(request)) {
      case 'draft': return 'Resume draft';
      case 'review': return 'Review request';
      case 'approved': return 'Start fulfillment';
      case 'dispatched': return 'Track shipment';
      case 'closed': return 'View request';
      default: return 'Open request';
    }
  }

  partyLabel(request: RequestSummary): string {
    return request.agency_name ?? `Agency ${request.agency_id}`;
  }

  hasUnread(filter: RequestFilter): boolean {
    return filter !== 'all' && this.unreadCount(filter) > 0;
  }

  unreadCount(filter: RequestFilter): number {
    return this.unreadCounts()[filter] ?? 0;
  }

  filterAriaLabel(label: string, filter: RequestFilter): string {
    const unread = this.unreadCount(filter);
    if (!unread) {
      return label;
    }
    return `${label}, ${unread} new ${unread === 1 ? 'request' : 'requests'}`;
  }

  trackByRequestId(_index: number, request: RequestSummary): number {
    return request.reliefrqst_id;
  }

  private loadRequests(): void {
    this.loading.set(true);

    this.operationsService.listRequests().subscribe({
      next: (response) => {
        const rows = [...response.results].sort((left, right) =>
          new Date(right.create_dtime ?? right.request_date ?? 0).getTime() -
          new Date(left.create_dtime ?? left.request_date ?? 0).getTime(),
        );
        this.requests.set(rows);
        this.syncSeenFilterForActiveView();
        this.lastRefreshedAt.set(Date.now());
        this.loading.set(false);
      },
      error: () => {
        this.requests.set([]);
        this.loading.set(false);
      },
    });
  }

  private getStatusGroup(request: RequestSummary): RequestStatusGroup {
    switch (String(request.status_code ?? '').trim().toUpperCase()) {
      case 'DRAFT':
        return 'draft';
      case 'SUBMITTED':
      case 'UNDER_ELIGIBILITY_REVIEW':
        return 'review';
      case 'APPROVED_FOR_FULFILLMENT':
        return 'approved';
      case 'PARTIALLY_FULFILLED':
      case 'FULFILLED':
        return 'dispatched';
      case 'CANCELLED':
      case 'REJECTED':
      case 'INELIGIBLE':
        return 'closed';
      default:
        return 'other';
    }
  }

  private isRequestFilter(value: string | undefined): value is RequestFilter {
    return value === 'all'
      || value === 'draft'
      || value === 'review'
      || value === 'approved'
      || value === 'dispatched'
      || value === 'closed';
  }

  private getSeenStorageKey(): string | null {
    return buildOperationsQueueSeenStorageKey(this.seenStorageScope, this.auth.currentUserRef());
  }

  private loadSeenFilters(): void {
    this.seenFilters.set(readOperationsQueueSeenEntries(this.getSeenStorageKey()));
  }

  private markFilterSeen(filter: RequestFilter): void {
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
    filter: Exclude<RequestFilter, 'all'>,
    rows: readonly RequestSummary[] = this.requests(),
  ): number[] {
    return rows
      .filter((request) => this.getStatusGroup(request) === filter)
      .map((request) => request.reliefrqst_id);
  }
}
