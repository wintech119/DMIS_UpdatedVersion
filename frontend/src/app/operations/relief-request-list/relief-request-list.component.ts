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

type RequestFilter = 'all' | 'draft' | 'review' | 'submitted' | 'closed';

interface QueueMetric {
  label: string;
  value: number;
  route: string;
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
    OpsStatusChipComponent,
  ],
  templateUrl: './relief-request-list.component.html',
  styleUrls: ['./relief-request-list.component.scss', '../operations-shell.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ReliefRequestListComponent implements OnInit {
  private readonly operationsService = inject(OperationsService);
  private readonly router = inject(Router);

  readonly loading = signal(true);
  readonly requests = signal<RequestSummary[]>([]);
  readonly searchTerm = signal('');
  readonly activeFilter = signal<RequestFilter>('all');

  readonly filterOptions: readonly { label: string; value: RequestFilter }[] = [
    { label: 'All', value: 'all' },
    { label: 'Draft', value: 'draft' },
    { label: 'Review', value: 'review' },
    { label: 'Submitted', value: 'submitted' },
    { label: 'Closed', value: 'closed' },
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
    const draft = rows.filter((row) => row.status_code === 0).length;
    const review = rows.filter((row) => this.getStatusGroup(row) === 'review').length;
    const submitted = rows.filter((row) => this.getStatusGroup(row) === 'submitted').length;
    const closed = rows.filter((row) => this.getStatusGroup(row) === 'closed').length;

    return [
      { label: 'Drafts', value: draft, route: '/operations/relief-requests', tone: 'draft', note: 'Unsubmitted and editable' },
      { label: 'In Review', value: review, route: '/operations/eligibility-review', tone: 'review', note: 'Queued for decision' },
      { label: 'Submitted', value: submitted, route: '/operations/relief-requests', tone: 'warning', note: 'Waiting in the live queue' },
      { label: 'Closed', value: closed, route: '/operations/relief-requests', tone: 'success', note: 'Fulfilled or completed' },
    ];
  });

  readonly statusSummary = computed(() => {
    const rows = this.filteredRequests();
    return {
      total: rows.length,
      critical: rows.filter((row) => String(row.urgency_ind ?? '').toUpperCase() === 'C').length,
      high: rows.filter((row) => String(row.urgency_ind ?? '').toUpperCase() === 'H').length,
      newest: rows[0] ?? null,
    };
  });

  readonly formatOperationsRequestStatus = formatOperationsRequestStatus;
  readonly formatOperationsUrgency = formatOperationsUrgency;
  readonly formatOperationsAge = formatOperationsAge;
  readonly formatOperationsDateTime = formatOperationsDateTime;
  readonly formatOperationsLineCount = formatOperationsLineCount;
  readonly getOperationsRequestTone = getOperationsRequestTone;
  readonly getOperationsUrgencyTone = getOperationsUrgencyTone;

  ngOnInit(): void {
    this.loadRequests();
  }

  setFilter(filter: RequestFilter): void {
    this.activeFilter.set(filter);
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

  openMetric(metric: QueueMetric): void {
    this.router.navigateByUrl(metric.route);
  }

  chipTone(tone: OperationsTone): 'neutral' | 'soft' | 'critical' | 'warning' | 'success' | 'info' | 'outline' {
    return mapOperationsToneToChipTone(tone);
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
        this.loading.set(false);
      },
      error: () => {
        this.requests.set([]);
        this.loading.set(false);
      },
    });
  }

  private getStatusGroup(request: RequestSummary): RequestFilter {
    if (request.status_code === 0) {
      return 'draft';
    }
    if (request.status_code === 1 || request.status_code === 3) {
      return 'review';
    }
    if (request.status_code === 2 || request.status_code === 4 || request.status_code === 8) {
      return 'closed';
    }
    return 'submitted';
  }
}
