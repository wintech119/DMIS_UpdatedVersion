import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';

import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';

import { AuthRbacService } from '../../replenishment/services/auth-rbac.service';
import { DmisEmptyStateComponent } from '../../replenishment/shared/dmis-empty-state/dmis-empty-state.component';
import { DmisSkeletonLoaderComponent } from '../../replenishment/shared/dmis-skeleton-loader/dmis-skeleton-loader.component';
import { OpsStatusChipComponent } from '../shared/ops-status-chip.component';
import { OperationsService } from '../services/operations.service';
import { RequestSummary } from '../models/operations.model';
import {
  formatOperationsAge,
  formatOperationsDateTime,
  formatOperationsLineCount,
  formatOperationsRequestStatus,
  formatOperationsUrgency,
  buildOperationsQueueSeenStorageKey,
  countOperationsUnreadIds,
  getOperationsRequestTone,
  getOperationsUrgencyTone,
  handleRovingRadioKeydown,
  mergeOperationsQueueSeenEntries,
  mapOperationsToneToChipTone,
  OperationsTone,
  readOperationsQueueSeenEntries,
  writeOperationsQueueSeenEntries,
} from '../operations-display.util';

type ReviewFilter = 'all' | 'critical' | 'high' | 'submitted' | 'closed';

interface ReviewMetric {
  label: string;
  value: number;
  note: string;
  route: string;
}

interface ReviewSummary {
  total: number;
  oldest: RequestSummary | null;
  newest: RequestSummary | null;
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
    OpsStatusChipComponent,
  ],
  templateUrl: './eligibility-review-queue.component.html',
  styleUrls: ['./eligibility-review-queue.component.scss', '../operations-shell.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class EligibilityReviewQueueComponent implements OnInit {
  private readonly auth = inject(AuthRbacService);
  private readonly operationsService = inject(OperationsService);
  private readonly router = inject(Router);
  private readonly seenStorageScope = 'eligibility-review';

  readonly loading = signal(true);
  readonly requests = signal<RequestSummary[]>([]);
  readonly searchTerm = signal('');
  readonly activeFilter = signal<ReviewFilter>('all');
  readonly seenFilters = signal<Record<string, number[]>>({});

  readonly filterOptions: readonly { label: string; value: ReviewFilter }[] = [
    { label: 'Critical', value: 'critical' },
    { label: 'High', value: 'high' },
    { label: 'Submitted', value: 'submitted' },
    { label: 'Closed', value: 'closed' },
    { label: 'All', value: 'all' },
  ];

  readonly filteredRequests = computed(() => {
    const term = this.searchTerm().trim().toLowerCase();
    const filter = this.activeFilter();

    return this.requests().filter((request) => {
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
    const rows = this.requests();
    return [
      { label: 'Pending', value: rows.filter((row) => row.status_code === 'SUBMITTED' || row.status_code === 'UNDER_ELIGIBILITY_REVIEW' || row.status_code === 'APPROVED_FOR_FULFILLMENT').length, note: 'Awaiting a decision', route: '/operations/eligibility-review' },
      { label: 'Critical', value: rows.filter((row) => String(row.urgency_ind ?? '').toUpperCase() === 'C').length, note: 'Immediate attention', route: '/operations/eligibility-review' },
      { label: 'High', value: rows.filter((row) => String(row.urgency_ind ?? '').toUpperCase() === 'H').length, note: 'Priority review lane', route: '/operations/eligibility-review' },
      { label: 'Closed', value: rows.filter((row) => row.status_code === 'CANCELLED' || row.status_code === 'REJECTED' || row.status_code === 'FULFILLED' || row.status_code === 'INELIGIBLE').length, note: 'Finalized decisions', route: '/operations/eligibility-review' },
    ];
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
    const rows = this.requests();
    const seen = this.seenFilters();

    return {
      all: 0,
      critical: countOperationsUnreadIds(this.getFilterRequestIds('critical', rows), seen['critical']),
      high: countOperationsUnreadIds(this.getFilterRequestIds('high', rows), seen['high']),
      submitted: countOperationsUnreadIds(this.getFilterRequestIds('submitted', rows), seen['submitted']),
      closed: countOperationsUnreadIds(this.getFilterRequestIds('closed', rows), seen['closed']),
    };
  });

  readonly formatOperationsRequestStatus = formatOperationsRequestStatus;
  readonly formatOperationsUrgency = formatOperationsUrgency;
  readonly formatOperationsDateTime = formatOperationsDateTime;
  readonly formatOperationsAge = formatOperationsAge;
  readonly formatOperationsLineCount = formatOperationsLineCount;
  readonly getOperationsRequestTone = getOperationsRequestTone;
  readonly getOperationsUrgencyTone = getOperationsUrgencyTone;

  ngOnInit(): void {
    this.auth.ensureLoaded().subscribe({
      next: () => {
        this.loadSeenFilters();
        this.loadQueue();
      },
      error: () => {
        this.loadSeenFilters();
        this.requests.set([]);
        this.loading.set(false);
      },
    });
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

  openMetric(metric: ReviewMetric): void {
    this.router.navigateByUrl(metric.route);
  }

  openReview(request: RequestSummary): void {
    this.router.navigate(['/operations/eligibility-review', request.reliefrqst_id]);
  }

  chipTone(tone: OperationsTone): 'neutral' | 'soft' | 'critical' | 'warning' | 'success' | 'info' | 'outline' {
    return mapOperationsToneToChipTone(tone);
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


  private loadQueue(): void {
    this.loading.set(true);

    this.operationsService.getEligibilityQueue().subscribe({
      next: (response) => {
        const rows = [...response.results].sort((left, right) =>
          new Date(right.create_dtime ?? right.request_date ?? 0).getTime() -
          new Date(left.create_dtime ?? left.request_date ?? 0).getTime(),
        );
        this.requests.set(rows);
        this.syncSeenFilterForActiveView();
        this.loading.set(false);
      },
      error: () => {
        this.requests.set([]);
        this.loading.set(false);
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
    rows: readonly RequestSummary[] = this.requests(),
  ): number[] {
    return rows
      .filter((request) => this.matchesFilter(request, filter))
      .map((request) => request.reliefrqst_id);
  }

  private matchesFilter(request: RequestSummary, filter: ReviewFilter): boolean {
    switch (filter) {
      case 'critical':
        return String(request.urgency_ind ?? '').toUpperCase() === 'C';
      case 'high':
        return String(request.urgency_ind ?? '').toUpperCase() === 'H';
      case 'submitted':
        return request.status_code === 'SUBMITTED'
          || request.status_code === 'UNDER_ELIGIBILITY_REVIEW'
          || request.status_code === 'APPROVED_FOR_FULFILLMENT';
      case 'closed':
        return request.status_code === 'CANCELLED'
          || request.status_code === 'REJECTED'
          || request.status_code === 'INELIGIBLE'
          || request.status_code === 'FULFILLED';
      case 'all':
      default:
        return true;
    }
  }
}
