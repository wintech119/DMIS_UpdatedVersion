import { Component, ChangeDetectionStrategy, computed, inject, signal, OnInit } from '@angular/core';
import { Router } from '@angular/router';
import { DatePipe } from '@angular/common';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatChipsModule } from '@angular/material/chips';
import { MatIconModule } from '@angular/material/icon';
import { MatTableModule } from '@angular/material/table';
import { MatTooltipModule } from '@angular/material/tooltip';

import { NeedsListResponse } from '../models/needs-list.model';
import { ReplenishmentService } from '../services/replenishment.service';
import { DmisNotificationService } from '../services/notification.service';
import { DmisSkeletonLoaderComponent } from '../shared/dmis-skeleton-loader/dmis-skeleton-loader.component';
import { DmisEmptyStateComponent } from '../shared/dmis-empty-state/dmis-empty-state.component';
import { formatStatusLabel } from './status-label.util';

@Component({
  selector: 'app-needs-list-review-queue',
  imports: [
    DatePipe,
    MatButtonModule,
    MatCardModule,
    MatChipsModule,
    MatIconModule,
    MatTableModule,
    MatTooltipModule,
    DmisSkeletonLoaderComponent,
    DmisEmptyStateComponent
  ],
  templateUrl: './needs-list-review-queue.component.html',
  styleUrl: './needs-list-review-queue.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class NeedsListReviewQueueComponent implements OnInit {
  private readonly router = inject(Router);
  private readonly replenishmentService = inject(ReplenishmentService);
  private readonly notifications = inject(DmisNotificationService);
  private readonly reviewQueueStatuses = ['SUBMITTED', 'PENDING_APPROVAL', 'PENDING', 'UNDER_REVIEW'] as const;

  readonly loading = signal(true);
  readonly needsLists = signal<NeedsListResponse[]>([]);
  readonly error = signal(false);
  readonly searchQuery = signal('');
  readonly selectedStatus = signal('ALL');
  readonly selectedPhase = signal('ALL');
  readonly selectedSubmitter = signal('ALL');

  readonly displayedColumns = [
    'needs_list_ref',
    'event_id',
    'phase',
    'warehouse',
    'submitted_by',
    'submitted_at',
    'items_count',
    'status'
  ];

  readonly phaseFilterOptions = computed(() =>
    this.uniqueNonEmptyValues(this.needsLists().map((row) => row.phase))
  );

  readonly submitterFilterOptions = computed(() =>
    this.uniqueNonEmptyValues(this.needsLists().map((row) => row.submitted_by))
  );

  readonly statusFilterOptions = computed(() => {
    const statuses = this.uniqueNonEmptyValues(
      this.needsLists().map((row) => this.normalizeStatusForFilter(row.status))
    );
    return statuses.map((value) => ({
      value,
      label: this.statusLabel(value)
    }));
  });

  readonly filteredNeedsLists = computed(() => {
    const query = this.searchQuery().trim().toLowerCase();
    const selectedStatus = this.selectedStatus();
    const selectedPhase = this.selectedPhase();
    const selectedSubmitter = this.selectedSubmitter();

    return this.needsLists().filter((row) => {
      if (selectedStatus !== 'ALL' && this.normalizeStatusForFilter(row.status) !== selectedStatus) {
        return false;
      }

      if (selectedPhase !== 'ALL' && (row.phase ?? '') !== selectedPhase) {
        return false;
      }

      const submitter = this.normalizedText(row.submitted_by);
      if (selectedSubmitter !== 'ALL' && submitter !== selectedSubmitter) {
        return false;
      }

      if (!query) {
        return true;
      }

      return this.buildSearchableText(row).includes(query);
    });
  });

  readonly hasActiveFilters = computed(
    () =>
      this.searchQuery().trim().length > 0 ||
      this.selectedStatus() !== 'ALL' ||
      this.selectedPhase() !== 'ALL' ||
      this.selectedSubmitter() !== 'ALL'
  );

  readonly activeFilterCount = computed(() => {
    let count = 0;
    if (this.searchQuery().trim().length > 0) count++;
    if (this.selectedStatus() !== 'ALL') count++;
    if (this.selectedPhase() !== 'ALL') count++;
    if (this.selectedSubmitter() !== 'ALL') count++;
    return count;
  });

  readonly filtersExpanded = signal(false);

  toggleFilters(): void {
    this.filtersExpanded.set(!this.filtersExpanded());
  }

  ngOnInit(): void {
    this.loadQueue();
  }

  loadQueue(): void {
    this.loading.set(true);
    this.error.set(false);
    this.replenishmentService.listNeedsLists([...this.reviewQueueStatuses]).subscribe({
      next: (data) => {
        const sorted = [...data.needs_lists].sort((a, b) => this.submittedAtTimestamp(b) - this.submittedAtTimestamp(a));
        this.needsLists.set(sorted);
        this.loading.set(false);
      },
      error: () => {
        this.loading.set(false);
        this.error.set(true);
        this.notifications.showError('Failed to load review queue.');
      }
    });
  }

  openReview(row: NeedsListResponse): void {
    if (row.needs_list_id) {
      this.router.navigate(['/replenishment/needs-list-review', row.needs_list_id]);
    }
  }

  backToDashboard(): void {
    this.router.navigate(['/replenishment/dashboard']);
  }

  warehouseLabel(row: NeedsListResponse): string {
    if (row.warehouses?.length) {
      return row.warehouses.map(w => w.warehouse_name).join(', ');
    }
    if (row.warehouse_ids?.length) {
      return row.warehouse_ids.join(', ');
    }
    if (row.warehouse_id) {
      return `Warehouse ${row.warehouse_id}`;
    }
    return 'N/A';
  }

  statusIcon(status: string | undefined): string {
    switch (status) {
      case 'SUBMITTED': return 'send';
      case 'PENDING_APPROVAL':
      case 'PENDING': return 'hourglass_top';
      case 'UNDER_REVIEW': return 'rate_review';
      default: return 'info';
    }
  }

  statusLabel(status: string | undefined): string {
    return formatStatusLabel(status);
  }

  needsListReference(row: NeedsListResponse): string {
    const value = this.needsListReferenceValue(row);
    if (value === 'N/A') {
      return value;
    }
    if (/^\d+$/.test(value) || value.length <= 18) {
      return value;
    }
    return `${value.slice(0, 12)}...`;
  }

  needsListReferenceTooltip(row: NeedsListResponse): string {
    return this.needsListReferenceValue(row);
  }

  itemsCount(row: NeedsListResponse): number {
    return row.items?.length ?? 0;
  }

  onSearchInput(event: Event): void {
    const target = event.target as HTMLInputElement;
    this.searchQuery.set(target.value);
  }

  onStatusFilterChange(event: Event): void {
    const target = event.target as HTMLSelectElement;
    this.selectedStatus.set(target.value);
  }

  onPhaseFilterChange(event: Event): void {
    const target = event.target as HTMLSelectElement;
    this.selectedPhase.set(target.value);
  }

  onSubmitterFilterChange(event: Event): void {
    const target = event.target as HTMLSelectElement;
    this.selectedSubmitter.set(target.value);
  }

  clearFilters(): void {
    this.searchQuery.set('');
    this.selectedStatus.set('ALL');
    this.selectedPhase.set('ALL');
    this.selectedSubmitter.set('ALL');
  }

  reviewAriaLabel(row: NeedsListResponse): string {
    return `Review needs list ${this.needsListReferenceValue(row)}`;
  }

  private normalizeStatusForFilter(status: string | undefined): string {
    if (!status) {
      return '';
    }
    return status.toUpperCase() === 'PENDING' ? 'PENDING_APPROVAL' : status.toUpperCase();
  }

  private uniqueNonEmptyValues(values: (string | undefined | null)[]): string[] {
    return Array.from(
      new Set(
        values
          .map((value) => this.normalizedText(value))
          .filter((value) => value.length > 0)
      )
    ).sort((left, right) => left.localeCompare(right));
  }

  private normalizedText(value: string | undefined | null): string {
    return (value ?? '').trim();
  }

  private needsListReferenceValue(row: NeedsListResponse): string {
    const value = this.normalizedText(row.needs_list_no);
    return value || 'N/A';
  }

  private buildSearchableText(row: NeedsListResponse): string {
    return [
      this.needsListReferenceValue(row),
      row.needs_list_no,
      row.event_name,
      row.event_id?.toString(),
      row.phase,
      this.warehouseLabel(row),
      row.submitted_by,
      row.submitted_at,
      this.statusLabel(row.status)
    ]
      .map((value) => this.normalizedText(value).toLowerCase())
      .join(' ');
  }

  private submittedAtTimestamp(row: NeedsListResponse): number {
    if (!row.submitted_at) {
      return 0;
    }
    const parsed = Date.parse(row.submitted_at);
    return Number.isFinite(parsed) ? parsed : 0;
  }
}
