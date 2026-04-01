import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';

import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';

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
  OperationsTone,
  getOperationsRequestTone,
  getOperationsUrgencyTone,
  mapOperationsToneToChipTone,
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
  private readonly operationsService = inject(OperationsService);
  private readonly router = inject(Router);

  readonly loading = signal(true);
  readonly requests = signal<RequestSummary[]>([]);
  readonly searchTerm = signal('');
  readonly activeFilter = signal<ReviewFilter>('all');

  readonly filterOptions: readonly { label: string; value: ReviewFilter }[] = [
    { label: 'All', value: 'all' },
    { label: 'Critical', value: 'critical' },
    { label: 'High', value: 'high' },
    { label: 'Submitted', value: 'submitted' },
    { label: 'Closed', value: 'closed' },
  ];

  readonly filteredRequests = computed(() => {
    const term = this.searchTerm().trim().toLowerCase();
    const filter = this.activeFilter();

    return this.requests().filter((request) => {
      if (filter === 'critical' && String(request.urgency_ind ?? '').toUpperCase() !== 'C') {
        return false;
      }
      if (filter === 'high' && String(request.urgency_ind ?? '').toUpperCase() !== 'H') {
        return false;
      }
      if (filter === 'submitted' && !(request.status_code === 'SUBMITTED' || request.status_code === 'UNDER_ELIGIBILITY_REVIEW' || request.status_code === 'APPROVED_FOR_FULFILLMENT')) {
        return false;
      }
      if (filter === 'closed' && !(request.status_code === 'CANCELLED' || request.status_code === 'REJECTED' || request.status_code === 'INELIGIBLE' || request.status_code === 'FULFILLED')) {
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

  readonly formatOperationsRequestStatus = formatOperationsRequestStatus;
  readonly formatOperationsUrgency = formatOperationsUrgency;
  readonly formatOperationsDateTime = formatOperationsDateTime;
  readonly formatOperationsAge = formatOperationsAge;
  readonly formatOperationsLineCount = formatOperationsLineCount;
  readonly getOperationsRequestTone = getOperationsRequestTone;
  readonly getOperationsUrgencyTone = getOperationsUrgencyTone;

  ngOnInit(): void {
    this.loadQueue();
  }

  setFilter(filter: ReviewFilter): void {
    this.activeFilter.set(filter);
  }

  onFilterKeydown(event: KeyboardEvent, index: number): void {
    const targetIndex = this.getFilterTargetIndex(event.key, index);
    if (targetIndex === null) {
      return;
    }

    const target = this.filterOptions[targetIndex];
    if (!target) {
      return;
    }

    event.preventDefault();
    this.setFilter(target.value);

    const group = (event.currentTarget as HTMLElement | null)?.closest('[role="radiogroup"]');
    const buttons = Array.from(group?.querySelectorAll<HTMLElement>('[role="radio"]') ?? []);
    requestAnimationFrame(() => buttons[targetIndex]?.focus());
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

  trackByRequestId(_index: number, request: RequestSummary): number {
    return request.reliefrqst_id;
  }

  private getFilterTargetIndex(key: string, currentIndex: number): number | null {
    const lastIndex = this.filterOptions.length - 1;
    if (lastIndex < 0) {
      return null;
    }

    switch (key) {
      case 'ArrowRight':
      case 'ArrowDown':
        return currentIndex === lastIndex ? 0 : currentIndex + 1;
      case 'ArrowLeft':
      case 'ArrowUp':
        return currentIndex === 0 ? lastIndex : currentIndex - 1;
      case 'Home':
        return 0;
      case 'End':
        return lastIndex;
      default:
        return null;
    }
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
        this.loading.set(false);
      },
      error: () => {
        this.requests.set([]);
        this.loading.set(false);
      },
    });
  }
}
