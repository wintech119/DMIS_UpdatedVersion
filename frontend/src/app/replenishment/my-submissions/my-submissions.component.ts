import { ChangeDetectionStrategy, Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatPaginatorModule, PageEvent } from '@angular/material/paginator';
import { EMPTY, Observable, Subject, forkJoin, of } from 'rxjs';
import { catchError, map, switchMap, tap } from 'rxjs/operators';

import { MySubmissionsResponse, NeedsListSummary } from '../models/needs-list.model';
import {
  MySubmissionsQueryParams,
  ReplenishmentService
} from '../services/replenishment.service';
import { DmisNotificationService } from '../services/notification.service';
import { SubmissionSnapshotService } from '../services/submission-snapshot.service';
import { CompactSubmissionCardComponent } from '../shared/compact-submission-card/compact-submission-card.component';
import { DmisEmptyStateComponent } from '../shared/dmis-empty-state/dmis-empty-state.component';
import { DmisSkeletonLoaderComponent } from '../shared/dmis-skeleton-loader/dmis-skeleton-loader.component';
import { getNeedsListActionTarget, HorizonActionTarget } from '../shared/needs-list-action.util';

export type SubmissionTab = 'all' | 'action' | 'progress' | 'done';

const TAB_STATUSES: Record<Exclude<SubmissionTab, 'all'>, ReadonlySet<string>> = {
  action: new Set(['DRAFT', 'MODIFIED', 'RETURNED']),
  progress: new Set(['PENDING_APPROVAL', 'SUBMITTED', 'UNDER_REVIEW', 'APPROVED', 'IN_PROGRESS', 'DISPATCHED', 'IN_TRANSIT']),
  done: new Set(['FULFILLED', 'RECEIVED', 'COMPLETED', 'REJECTED', 'CANCELLED', 'SUPERSEDED'])
};

interface GroupedSubmissions {
  action: NeedsListSummary[];
  progress: NeedsListSummary[];
  done: NeedsListSummary[];
}

const CLIENT_SIDE_SUBMISSIONS_PAGE_SIZE = 100;

@Component({
  selector: 'app-my-submissions',
  standalone: true,
  imports: [
    MatButtonModule,
    MatIconModule,
    MatPaginatorModule,
    CompactSubmissionCardComponent,
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
  readonly allSubmissions = signal<NeedsListSummary[]>([]);
  readonly totalCount = signal(0);
  readonly recentlyChangedIds = signal<Set<string>>(new Set());

  // New simplified filters
  readonly activeTab = signal<SubmissionTab>('all');
  readonly searchQuery = signal('');
  readonly sortNewest = signal(true);

  // Pagination
  readonly pageSize = signal(20);
  readonly pageIndex = signal(0);

  // Batch selection
  readonly selectedDraftIds = signal<Set<string>>(new Set<string>());
  readonly selectedCount = computed(() => this.selectedDraftIds().size);

  // Completed group collapse
  readonly completedExpanded = signal(false);

  // Filtered + grouped submissions (client-side)
  readonly filteredSubmissions = computed((): NeedsListSummary[] => {
    let items = this.allSubmissions();
    const tab = this.activeTab();
    const query = this.searchQuery().trim().toLowerCase();

    // Tab filter
    if (tab !== 'all') {
      const allowedStatuses = TAB_STATUSES[tab];
      items = items.filter(s => allowedStatuses.has(s.status));
    }

    // Search filter
    if (query) {
      items = items.filter(s =>
        s.reference_number.toLowerCase().includes(query) ||
        (s.warehouse?.name || '').toLowerCase().includes(query)
      );
    }

    // Sort
    items = [...items].sort((a, b) => {
      const dateA = new Date(a.last_updated_at || a.submitted_at || 0).getTime();
      const dateB = new Date(b.last_updated_at || b.submitted_at || 0).getTime();
      return this.sortNewest() ? dateB - dateA : dateA - dateB;
    });

    return items;
  });

  readonly groupedSubmissions = computed((): GroupedSubmissions => {
    const items = this.filteredSubmissions();
    const groups: GroupedSubmissions = { action: [], progress: [], done: [] };

    for (const item of items) {
      if (TAB_STATUSES.action.has(item.status)) {
        groups.action.push(item);
      } else if (TAB_STATUSES.done.has(item.status)) {
        groups.done.push(item);
      } else {
        groups.progress.push(item);
      }
    }

    return groups;
  });

  // Tab counts (from all submissions, ignoring search)
  readonly tabCounts = computed(() => {
    const items = this.allSubmissions();
    let action = 0, progress = 0, done = 0;
    for (const item of items) {
      if (TAB_STATUSES.action.has(item.status)) action++;
      else if (TAB_STATUSES.done.has(item.status)) done++;
      else progress++;
    }
    return { all: items.length, action, progress, done };
  });

  readonly hasResults = computed(() => this.filteredSubmissions().length > 0);
  readonly hasActiveFilters = computed(() =>
    this.activeTab() !== 'all' || this.searchQuery().trim() !== ''
  );

  // Paginated view
  readonly paginatedSubmissions = computed((): GroupedSubmissions => {
    const groups = this.groupedSubmissions();
    const start = this.pageIndex() * this.pageSize();
    const end = start + this.pageSize();

    // Flatten, paginate, then re-group
    const allFlat = [...groups.action, ...groups.progress, ...groups.done];
    const page = allFlat.slice(start, end);

    const result: GroupedSubmissions = { action: [], progress: [], done: [] };
    for (const item of page) {
      if (TAB_STATUSES.action.has(item.status)) result.action.push(item);
      else if (TAB_STATUSES.done.has(item.status)) result.done.push(item);
      else result.progress.push(item);
    }
    return result;
  });

  constructor() {
    // Apply initial tab from query params
    const statusParam = this.route.snapshot.queryParamMap.get('status');
    if (statusParam) {
      const upper = statusParam.toUpperCase();
      if (TAB_STATUSES.action.has(upper)) this.activeTab.set('action');
      else if (TAB_STATUSES.progress.has(upper)) this.activeTab.set('progress');
      else if (TAB_STATUSES.done.has(upper)) this.activeTab.set('done');
    }

    this.loadRequests.pipe(
      tap(() => {
        this.loading.set(true);
        this.error.set(false);
      }),
      switchMap(() =>
        this.loadAllSubmissions(this.buildQueryParams()).pipe(
          catchError(() => {
            this.loading.set(false);
            this.error.set(true);
            this.allSubmissions.set([]);
            this.totalCount.set(0);
            this.selectedDraftIds.set(new Set<string>());
            this.notifications.showError('Failed to load needs list submissions.');
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

      // Sort changed submissions to the top within their groups
      if (changed.size > 0) {
        const changedItems = results.filter(r => changed.has(r.id));
        const otherItems = results.filter(r => !changed.has(r.id));
        this.allSubmissions.set([...changedItems, ...otherItems]);
      } else {
        this.allSubmissions.set(results);
      }

      this.totalCount.set(response.count || 0);
      this.loading.set(false);

      // Prune batch selection to items still on page
      const allowedOnPage = new Set(
        results
          .filter(row => this.canBatchSelect(row.status))
          .map(row => row.id)
      );
      const nextSelection = new Set<string>();
      for (const id of this.selectedDraftIds()) {
        if (allowedOnPage.has(id)) nextSelection.add(id);
      }
      this.selectedDraftIds.set(nextSelection);

      // Mark as seen after 5 seconds
      if (this.seenTimer !== null) clearTimeout(this.seenTimer);
      this.seenTimer = setTimeout(() => {
        this.snapshotService.markAsSeen(results);
        this.seenTimer = null;
      }, 5000);
    });

    this.loadSubmissions();
  }

  loadSubmissions(): void {
    this.loadRequests.next();
  }

  onTabChange(tab: SubmissionTab): void {
    this.activeTab.set(tab);
    this.pageIndex.set(0);
  }

  onSearchInput(event: Event): void {
    const target = event.target as HTMLInputElement | null;
    this.searchQuery.set(target?.value || '');
    this.pageIndex.set(0);
  }

  toggleSort(): void {
    this.sortNewest.update(v => !v);
  }

  toggleCompleted(): void {
    this.completedExpanded.update(v => !v);
  }

  clearFilters(): void {
    this.activeTab.set('all');
    this.searchQuery.set('');
    this.sortNewest.set(true);
    this.pageIndex.set(0);
  }

  // Card event handlers
  onCardClick(submission: NeedsListSummary): void {
    const target = getNeedsListActionTarget(submission.id, submission.status);
    this.router.navigate(target.commands, { queryParams: target.queryParams });
  }

  onCardAction(event: { submission: NeedsListSummary; action: string }): void {
    const target = getNeedsListActionTarget(event.submission.id, event.submission.status);
    this.router.navigate(target.commands, { queryParams: target.queryParams });
  }

  onHorizonAction(target: HorizonActionTarget): void {
    this.router.navigate(target.commands);
  }

  // Batch selection
  canBatchSelect(status: string): boolean {
    return status === 'DRAFT' || status === 'MODIFIED';
  }

  isSelected(id: string): boolean {
    return this.selectedDraftIds().has(id);
  }

  onSelectionToggle(event: { id: string; selected: boolean }): void {
    const next = new Set(this.selectedDraftIds());
    if (event.selected) {
      next.add(event.id);
    } else {
      next.delete(event.id);
    }
    this.selectedDraftIds.set(next);
  }

  submitSelectedDrafts(): void {
    const ids = [...this.selectedDraftIds()];
    if (!ids.length) return;

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
    if (!ids.length) return;

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

  onPageChange(event: PageEvent): void {
    this.pageIndex.set(event.pageIndex);
    this.pageSize.set(event.pageSize);
  }

  backToDashboard(): void {
    this.router.navigate(['/replenishment/dashboard']);
  }

  private buildQueryParams(): MySubmissionsQueryParams {
    // Fetch all submissions from server (no server-side filtering — client handles it)
    return {
      sort_by: 'date',
      sort_order: 'desc',
      page: 1,
      page_size: CLIENT_SIDE_SUBMISSIONS_PAGE_SIZE
    };
  }

  private loadAllSubmissions(
    params: MySubmissionsQueryParams
  ): Observable<MySubmissionsResponse> {
    const firstPageParams: MySubmissionsQueryParams = {
      ...params,
      page: 1,
      page_size: CLIENT_SIDE_SUBMISSIONS_PAGE_SIZE
    };

    return this.replenishmentService.getMySubmissions(firstPageParams).pipe(
      switchMap((firstPage) => {
        const firstResults = firstPage.results || [];
        const totalPages = Math.max(
          1,
          Math.ceil((firstPage.count || firstResults.length) / CLIENT_SIDE_SUBMISSIONS_PAGE_SIZE)
        );

        if (totalPages === 1) {
          return of(firstPage);
        }

        const remainingPages = Array.from({ length: totalPages - 1 }, (_, index) =>
          this.replenishmentService.getMySubmissions({
            ...firstPageParams,
            page: index + 2
          })
        );

        return forkJoin(remainingPages).pipe(
          map((responses) => ({
            count: firstPage.count,
            next: null,
            previous: null,
            results: [firstPage, ...responses].flatMap((response) => response.results || [])
          }))
        );
      })
    );
  }
}
