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
import { SubmissionSnapshotService } from '../services/submission-snapshot.service';
import { SubmissionCardComponent } from '../shared/submission-card/submission-card.component';
import { DmisEmptyStateComponent } from '../shared/dmis-empty-state/dmis-empty-state.component';
import { DmisSkeletonLoaderComponent } from '../shared/dmis-skeleton-loader/dmis-skeleton-loader.component';
import { getNeedsListActionTarget, HorizonActionTarget } from '../shared/needs-list-action.util';

interface EventOption {
  id: number | null;
  name: string;
}

type ReplenishmentMethodFilter = 'ALL' | 'A' | 'B' | 'C';

const VALID_STATUSES: ReadonlySet<NeedsListSummaryStatus> = new Set([
  'DRAFT',
  'MODIFIED',
  'RETURNED',
  'PENDING_APPROVAL',
  'APPROVED',
  'REJECTED',
  'IN_PROGRESS',
  'FULFILLED',
  'SUPERSEDED',
  'CANCELLED'
]);

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
  private readonly snapshotService = inject(SubmissionSnapshotService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);
  private readonly loadRequests = new Subject<void>();
  private seenTimer: ReturnType<typeof setTimeout> | null = null;

  readonly loading = signal(false);
  readonly error = signal(false);
  readonly submissions = signal<NeedsListSummary[]>([]);
  readonly totalCount = signal(0);
  readonly recentlyChangedIds = signal<Set<string>>(new Set());

  readonly statusFilter = signal<string>('ALL');
  readonly methodFilter = signal<ReplenishmentMethodFilter>('ALL');
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
    this.methodFilter() !== 'ALL' ||
    this.warehouseFilter() !== null ||
    this.eventFilter() !== null ||
    this.dateFromFilter() !== '' ||
    this.dateToFilter() !== ''
  );

  constructor() {
    const statusParam = this.route.snapshot.queryParamMap.get('status');
    if (statusParam) {
      if (statusParam === 'ALL') {
        this.statusFilter.set('ALL');
      } else {
        const parsedStatuses = statusParam
          .split(',')
          .map((value) => value.trim().toUpperCase())
          .filter(Boolean);
        if (parsedStatuses.length > 0 && parsedStatuses.every((value) => VALID_STATUSES.has(value as NeedsListSummaryStatus))) {
          this.statusFilter.set(parsedStatuses.join(','));
        }
      }
    }
    const methodParam = String(this.route.snapshot.queryParamMap.get('method') || '').trim().toUpperCase();
    if (methodParam === 'A' || methodParam === 'B' || methodParam === 'C') {
      this.methodFilter.set(methodParam);
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
      const results = response.results || [];

      // Detect which submissions changed since last visit
      const changed = this.snapshotService.detectChanges(results);
      this.recentlyChangedIds.set(changed);

      // Sort changed submissions to the top, preserving relative order within each group
      if (changed.size > 0) {
        const changedItems = results.filter((r) => changed.has(r.id));
        const otherItems = results.filter((r) => !changed.has(r.id));
        this.submissions.set([...changedItems, ...otherItems]);
      } else {
        this.submissions.set(results);
      }

      this.totalCount.set(response.count || 0);
      this.mergeWarehouseOptions(results);
      this.mergeEventOptions(results);
      this.loading.set(false);

      const allowedOnPage = new Set(
        results
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

      // Mark as seen after 5 seconds so highlights clear on next visit
      if (this.seenTimer !== null) {
        clearTimeout(this.seenTimer);
      }
      this.seenTimer = setTimeout(() => {
        this.snapshotService.markAsSeen(results);
        this.seenTimer = null;
      }, 5000);
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

  onHorizonAction(target: HorizonActionTarget): void {
    this.router.navigate(target.commands);
  }

  onStatusFilterChange(event: Event): void {
    const target = event.target as HTMLSelectElement | null;
    this.statusFilter.set(target?.value || 'ALL');
    this.resetPageAndReload();
  }

  onWarehouseFilterChange(event: Event): void {
    const target = event.target as HTMLSelectElement | null;
    const raw = target?.value || '';
    this.warehouseFilter.set(this.parsePositiveIntFilter(raw));
    this.resetPageAndReload();
  }

  onEventFilterChange(event: Event): void {
    const target = event.target as HTMLSelectElement | null;
    const raw = target?.value || '';
    this.eventFilter.set(this.parsePositiveIntFilter(raw));
    this.resetPageAndReload();
  }

  onMethodFilterChange(event: Event): void {
    const target = event.target as HTMLSelectElement | null;
    const raw = String(target?.value || 'ALL').trim().toUpperCase();
    if (raw === 'A' || raw === 'B' || raw === 'C') {
      this.methodFilter.set(raw);
    } else {
      this.methodFilter.set('ALL');
    }
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
    this.methodFilter.set('ALL');
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
    const method = this.methodFilter();
    return {
      status: this.statusFilter() === 'ALL' ? undefined : this.statusFilter(),
      method: method === 'ALL' ? undefined : method,
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
          const merged = new Map<number, Warehouse>();
          for (const warehouse of this.warehouseOptions()) {
            if (this.isValidWarehouse(warehouse)) {
              merged.set(warehouse.warehouse_id, warehouse);
            }
          }
          for (const warehouse of warehouses || []) {
            if (this.isValidWarehouse(warehouse)) {
              merged.set(warehouse.warehouse_id, warehouse);
            }
          }
          this.warehouseOptions.set(
            [...merged.values()].sort((left, right) =>
              left.warehouse_name.localeCompare(right.warehouse_name)
            )
          );
        },
        error: () => {
          // Keep any already-cached options to avoid collapsing filters on transient failures.
        }
      });
  }

  private mergeWarehouseOptions(rows: NeedsListSummary[]): void {
    const merged = new Map<number, Warehouse>();
    for (const warehouse of this.warehouseOptions()) {
      if (this.isValidWarehouse(warehouse)) {
        merged.set(warehouse.warehouse_id, warehouse);
      }
    }

    for (const row of rows) {
      const id = row.warehouse?.id;
      if (id == null || !Number.isInteger(id) || id <= 0) {
        continue;
      }
      const name = String(row.warehouse?.name || `Warehouse ${id}`).trim();
      merged.set(id, {
        warehouse_id: id,
        warehouse_name: name || `Warehouse ${id}`
      });
    }

    this.warehouseOptions.set(
      [...merged.values()].sort((left, right) =>
        left.warehouse_name.localeCompare(right.warehouse_name)
      )
    );
  }

  private mergeEventOptions(rows: NeedsListSummary[]): void {
    const existing = new Map<number, EventOption>();

    for (const option of this.eventOptions()) {
      const id = option.id;
      if (typeof id === 'number' && Number.isInteger(id) && id > 0) {
        existing.set(id, { id, name: option.name || `Event ${id}` });
      }
    }

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

  private parsePositiveIntFilter(raw: string): number | null {
    const normalized = String(raw || '').trim();
    if (!normalized) {
      return null;
    }
    const parsed = Number(normalized);
    if (!Number.isInteger(parsed) || parsed <= 0) {
      return null;
    }
    return parsed;
  }

  private isValidWarehouse(value: Warehouse | null | undefined): value is Warehouse {
    if (!value) {
      return false;
    }
    if (!Number.isInteger(value.warehouse_id) || value.warehouse_id <= 0) {
      return false;
    }
    return String(value.warehouse_name || '').trim().length > 0;
  }
}
