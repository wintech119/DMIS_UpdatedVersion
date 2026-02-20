import { ChangeDetectionStrategy, Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatPaginatorModule, PageEvent } from '@angular/material/paginator';
import { EMPTY, Subject } from 'rxjs';
import { catchError, switchMap, tap } from 'rxjs/operators';

import { NeedsListSummary, NeedsListSummaryStatus } from '../models/needs-list.model';
import {
  MySubmissionsQueryParams,
  ReplenishmentService,
  Warehouse
} from '../services/replenishment.service';
import { DmisNotificationService } from '../services/notification.service';
import { SubmissionCardComponent } from '../shared/submission-card/submission-card.component';
import { DmisEmptyStateComponent } from '../shared/dmis-empty-state/dmis-empty-state.component';
import { DmisSkeletonLoaderComponent } from '../shared/dmis-skeleton-loader/dmis-skeleton-loader.component';
import { getNeedsListActionTarget } from '../shared/needs-list-action.util';

interface EventOption {
  id: number | null;
  name: string;
}

@Component({
  selector: 'app-my-submissions',
  standalone: true,
  imports: [
    MatButtonModule,
    MatIconModule,
    MatPaginatorModule,
    SubmissionCardComponent,
    DmisEmptyStateComponent,
    DmisSkeletonLoaderComponent
  ],
  templateUrl: './my-submissions.component.html',
  styleUrl: './my-submissions.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class MySubmissionsComponent {
  private readonly replenishmentService = inject(ReplenishmentService);
  private readonly notifications = inject(DmisNotificationService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);
  private readonly loadRequests = new Subject<void>();

  readonly loading = signal(false);
  readonly error = signal(false);
  readonly submissions = signal<NeedsListSummary[]>([]);
  readonly totalCount = signal(0);

  readonly statusFilter = signal<string>('ALL');
  readonly warehouseFilter = signal<number | null>(null);
  readonly eventFilter = signal<number | null>(null);
  readonly dateFromFilter = signal<string>('');
  readonly dateToFilter = signal<string>('');
  readonly sortBy = signal<'date' | 'status' | 'warehouse'>('date');
  readonly sortOrder = signal<'asc' | 'desc'>('desc');
  readonly pageSize = signal(10);
  readonly pageIndex = signal(0);

  readonly selectedDraftIds = signal<Set<string>>(new Set<string>());
  readonly warehouseOptions = signal<Warehouse[]>([]);
  readonly eventOptions = signal<EventOption[]>([]);

  readonly selectedCount = computed(() => this.selectedDraftIds().size);
  readonly hasResults = computed(() => this.submissions().length > 0);
  readonly hasActiveFilters = computed(() =>
    this.statusFilter() !== 'ALL' ||
    this.warehouseFilter() !== null ||
    this.eventFilter() !== null ||
    this.dateFromFilter() !== '' ||
    this.dateToFilter() !== ''
  );

  constructor() {
const VALID_STATUSES: ReadonlySet<string> = new Set([
  'ALL', 'DRAFT', 'MODIFIED', 'SUBMITTED', /* ... remaining NeedsListSummaryStatus values */
]);

constructor() {
    const statusParam = this.route.snapshot.queryParamMap.get('status');
    if (statusParam && VALID_STATUSES.has(statusParam)) {
      this.statusFilter.set(statusParam);
    }
    // ...existing constructor logic...
}
    this.loadRequests.pipe(
      tap(() => {
        this.loading.set(true);
        this.error.set(false);
      }),
      switchMap(() =>
        this.replenishmentService.getMySubmissions(this.buildQueryParams()).pipe(
          catchError(() => {
            this.loading.set(false);
            this.error.set(true);
            this.submissions.set([]);
            this.totalCount.set(0);
            this.selectedDraftIds.set(new Set<string>());
            this.notifications.showError('Failed to load your submissions.');
            return EMPTY;
          })
        )
      ),
      takeUntilDestroyed(this.destroyRef)
    ).subscribe((response) => {
      this.submissions.set(response.results || []);
      this.totalCount.set(response.count || 0);
      this.mergeEventOptions(response.results || []);
      this.loading.set(false);

      const allowedOnPage = new Set(
        (response.results || [])
          .filter((row) => this.canBatchSelect(row.status))
          .map((row) => row.id)
      );
      const nextSelection = new Set<string>();
      for (const id of this.selectedDraftIds()) {
        if (allowedOnPage.has(id)) {
          nextSelection.add(id);
        }
      }
      this.selectedDraftIds.set(nextSelection);
    });
    this.loadWarehouseOptions();
    this.loadSubmissions();
  }

  loadSubmissions(): void {
    this.loadRequests.next();
  }

  refreshSubmission(_id: string): void {
    void _id;
    this.loadSubmissions();
  }

  onOpenAction(event: { id: string; status: NeedsListSummaryStatus }): void {
    const target = getNeedsListActionTarget(event.id, event.status);
    this.router.navigate(target.commands, { queryParams: target.queryParams });
  }

  onStatusFilterChange(event: Event): void {
    const target = event.target as HTMLSelectElement | null;
    this.statusFilter.set(target?.value || 'ALL');
    this.resetPageAndReload();
  }

  onWarehouseFilterChange(event: Event): void {
    const target = event.target as HTMLSelectElement | null;
    const raw = target?.value || '';
    this.warehouseFilter.set(raw ? Number(raw) : null);
    this.resetPageAndReload();
  }

  onEventFilterChange(event: Event): void {
    const target = event.target as HTMLSelectElement | null;
    const raw = target?.value || '';
    this.eventFilter.set(raw ? Number(raw) : null);
    this.resetPageAndReload();
  }

  onDateFromChange(event: Event): void {
    const target = event.target as HTMLInputElement | null;
    this.dateFromFilter.set(target?.value || '');
    this.resetPageAndReload();
  }

  onDateToChange(event: Event): void {
    const target = event.target as HTMLInputElement | null;
    this.dateToFilter.set(target?.value || '');
    this.resetPageAndReload();
  }

  onSortByChange(event: Event): void {
    const target = event.target as HTMLSelectElement | null;
    const value = target?.value;
    if (value === 'date' || value === 'status' || value === 'warehouse') {
      this.sortBy.set(value);
      this.resetPageAndReload();
    }
  }

  toggleSortOrder(): void {
    this.sortOrder.set(this.sortOrder() === 'desc' ? 'asc' : 'desc');
    this.resetPageAndReload();
  }

  onPageChange(event: PageEvent): void {
    this.pageIndex.set(event.pageIndex);
    this.pageSize.set(event.pageSize);
    this.loadSubmissions();
  }

  clearFilters(): void {
    this.statusFilter.set('ALL');
    this.warehouseFilter.set(null);
    this.eventFilter.set(null);
    this.dateFromFilter.set('');
    this.dateToFilter.set('');
    this.sortBy.set('date');
    this.sortOrder.set('desc');
    this.pageIndex.set(0);
    this.loadSubmissions();
  }

  canBatchSelect(status: string): boolean {
    return status === 'DRAFT' || status === 'MODIFIED';
  }

  isSelected(id: string): boolean {
    return this.selectedDraftIds().has(id);
  }

  onDraftSelectionChange(id: string, selected: boolean): void {
    const next = new Set(this.selectedDraftIds());
    if (selected) {
      next.add(id);
    } else {
      next.delete(id);
    }
    this.selectedDraftIds.set(next);
  }

  submitSelectedDrafts(): void {
    const ids = [...this.selectedDraftIds()];
    if (!ids.length) {
      return;
    }

    this.replenishmentService
      .bulkSubmitDrafts(ids)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (result) => {
          this.selectedDraftIds.set(new Set<string>());
          if (result.errors?.length) {
            this.notifications.showWarning(
              `Submitted ${result.count}. ${result.errors.length} could not be submitted.`
            );
          } else {
            this.notifications.showSuccess(`Submitted ${result.count} draft(s).`);
          }
          this.loadSubmissions();
        },
        error: () => {
          this.notifications.showError('Failed to submit selected drafts.');
        }
      });
  }

  deleteSelectedDrafts(): void {
    const ids = [...this.selectedDraftIds()];
    if (!ids.length) {
      return;
    }

    this.replenishmentService
      .bulkDeleteDrafts(ids)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (result) => {
          this.selectedDraftIds.set(new Set<string>());
          if (result.errors?.length) {
            this.notifications.showWarning(
              `Removed ${result.count}. ${result.errors.length} could not be removed.`
            );
          } else {
            this.notifications.showSuccess(`Removed ${result.count} draft(s).`);
          }
          this.loadSubmissions();
        },
        error: () => {
          this.notifications.showError('Failed to remove selected drafts.');
        }
      });
  }

  backToDashboard(): void {
    this.router.navigate(['/replenishment/dashboard']);
  }

  private resetPageAndReload(): void {
    this.pageIndex.set(0);
    this.loadSubmissions();
  }

  private buildQueryParams(): MySubmissionsQueryParams {
    return {
      status: this.statusFilter() === 'ALL' ? undefined : this.statusFilter(),
      warehouse_id: this.warehouseFilter() ?? undefined,
      event_id: this.eventFilter() ?? undefined,
      date_from: this.dateFromFilter() || undefined,
      date_to: this.dateToFilter() || undefined,
      sort_by: this.sortBy(),
      sort_order: this.sortOrder(),
      page: this.pageIndex() + 1,
      page_size: this.pageSize()
    };
  }

  private loadWarehouseOptions(): void {
    this.replenishmentService
      .getAllWarehouses()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (warehouses) => {
          this.warehouseOptions.set(warehouses || []);
        },
        error: () => {
          this.warehouseOptions.set([]);
        }
      });
  }

  private mergeEventOptions(rows: NeedsListSummary[]): void {
    const existing = new Map<number, EventOption>();

    for (const row of rows) {
      const id = row.event.id;
      if (typeof id === 'number' && Number.isInteger(id) && id > 0 && !existing.has(id)) {
        existing.set(id, { id, name: row.event.name || `Event ${id}` });
      }
    }

    const merged = [...existing.values()].sort((left, right) =>
      left.name.localeCompare(right.name)
    );
    this.eventOptions.set(merged);
  }
}
