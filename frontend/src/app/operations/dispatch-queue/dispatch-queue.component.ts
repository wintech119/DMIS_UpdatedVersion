import {
  Component,
  ChangeDetectionStrategy,
  computed,
  inject,
  signal,
  OnInit,
} from '@angular/core';
import { Router } from '@angular/router';

import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';

import { AuthRbacService } from '../../replenishment/services/auth-rbac.service';
import { DmisEmptyStateComponent } from '../../replenishment/shared/dmis-empty-state/dmis-empty-state.component';
import { DmisSkeletonLoaderComponent } from '../../replenishment/shared/dmis-skeleton-loader/dmis-skeleton-loader.component';
import { OpsMetricStripComponent, OpsMetricStripItem } from '../shared/ops-metric-strip.component';
import { OpsStatusChipComponent } from '../shared/ops-status-chip.component';
import { OperationsService } from '../services/operations.service';
import { DispatchQueueItem } from '../models/operations.model';
import {
  formatOperationsPackageStatus,
  formatOperationsAge,
  formatOperationsDateTime,
  formatLegProgressLabel,
  buildOperationsQueueSeenStorageKey,
  countOperationsUnreadIds,
  getOperationsDispatchStage,
  getOperationsPackageTone,
  getLegProgressTone,
  handleRovingRadioKeydown,
  mergeOperationsQueueSeenEntries,
  mapOperationsToneToChipTone,
  OperationsTone,
  readOperationsQueueSeenEntries,
  writeOperationsQueueSeenEntries,
} from '../operations-display.util';

type DispatchFilter = 'all' | 'ready' | 'in_transit' | 'completed';
type DispatchStage = DispatchFilter | 'unknown';

@Component({
  selector: 'app-dispatch-queue',
  standalone: true,
  imports: [
    MatButtonModule,
    MatIconModule,
    OpsMetricStripComponent,
    OpsStatusChipComponent,
    DmisEmptyStateComponent,
    DmisSkeletonLoaderComponent,
  ],
  templateUrl: './dispatch-queue.component.html',
  styleUrls: ['./dispatch-queue.component.scss', '../operations-shell.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DispatchQueueComponent implements OnInit {
  private readonly auth = inject(AuthRbacService);
  private readonly operationsService = inject(OperationsService);
  private readonly router = inject(Router);
  private readonly seenStorageScope = 'dispatch';

  readonly loading = signal(true);
  readonly items = signal<DispatchQueueItem[]>([]);
  readonly searchTerm = signal('');
  readonly activeFilter = signal<DispatchFilter>('all');
  readonly seenFilters = signal<Record<string, number[]>>({});

  readonly filterOptions: readonly { label: string; value: DispatchFilter }[] = [
    { label: 'Ready', value: 'ready' },
    { label: 'In Transit', value: 'in_transit' },
    { label: 'Completed', value: 'completed' },
    { label: 'All', value: 'all' },
  ];

  readonly filteredItems = computed(() => {
    const term = this.searchTerm().trim().toLowerCase();
    const filter = this.activeFilter();

    return this.items().filter((row) => {
      if (filter !== 'all' && this.getDispatchStage(row) !== filter) {
        return false;
      }
      if (!term) {
        return true;
      }
      const haystack = [
        row.tracking_no ?? `PKG-${row.reliefpkg_id}`,
        row.request_tracking_no,
        row.agency_name,
        row.event_name,
        row.transport_mode,
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase();
      return haystack.includes(term);
    });
  });

  readonly queueStats = computed(() => {
    const items = this.items();
    const summary = this.summarizeDispatchStages(items);
    return [
      { label: 'Ready', value: summary.ready, note: 'Awaiting handoff' },
      { label: 'In Transit', value: summary.inTransit, note: 'Dispatched, receipt pending' },
      { label: 'Completed', value: summary.completed, note: 'Receipt confirmed' },
      { label: 'All Packages', value: items.length, note: 'Visible in the queue' },
    ];
  });

  readonly queueMetrics = computed<readonly OpsMetricStripItem[]>(() =>
    this.queueStats().map((stat) => ({
      label: stat.label,
      value: String(stat.value),
      hint: stat.note,
    })),
  );

  readonly sidebarSummary = computed(() => {
    const rows = this.filteredItems();
    const summary = this.summarizeDispatchStages(rows);
    return {
      total: rows.length,
      ready: summary.ready,
      inTransit: summary.inTransit,
      completed: summary.completed,
    };
  });

  readonly unreadCounts = computed<Record<DispatchFilter, number>>(() => {
    const rows = this.items();
    const seen = this.seenFilters();

    return {
      all: 0,
      ready: countOperationsUnreadIds(this.getFilterPackageIds('ready', rows), seen['ready']),
      in_transit: countOperationsUnreadIds(this.getFilterPackageIds('in_transit', rows), seen['in_transit']),
      completed: countOperationsUnreadIds(this.getFilterPackageIds('completed', rows), seen['completed']),
    };
  });

  readonly formatPackageStatus = formatOperationsPackageStatus;
  readonly formatAge = formatOperationsAge;
  readonly formatDateTime = formatOperationsDateTime;
  readonly formatLegProgress = formatLegProgressLabel;
  readonly getPackageTone = getOperationsPackageTone;
  readonly legProgressTone = getLegProgressTone;

  ngOnInit(): void {
    this.auth.ensureLoaded().subscribe(() => {
      this.loadSeenFilters();
      this.refreshQueue();
    });
  }

  refreshQueue(): void {
    this.loadQueue();
  }

  setFilter(filter: DispatchFilter): void {
    this.activeFilter.set(filter);
    this.markFilterSeen(filter);
  }

  onFilterKeydown(event: KeyboardEvent, index: number): void {
    handleRovingRadioKeydown(event, index, this.filterOptions, (value) => this.setFilter(value));
  }

  hasUnread(filter: DispatchFilter): boolean {
    return filter !== 'all' && this.unreadCount(filter) > 0;
  }

  unreadCount(filter: DispatchFilter): number {
    return this.unreadCounts()[filter] ?? 0;
  }

  filterAriaLabel(label: string, filter: DispatchFilter): string {
    const unread = this.unreadCount(filter);
    if (!unread) {
      return label;
    }
    return `${label}, ${unread} new ${unread === 1 ? 'package' : 'packages'}`;
  }

  onSearch(value: string): void {
    this.searchTerm.set(value);
  }

  viewDispatch(item: DispatchQueueItem): void {
    if (this.isPickupRelease(item)) {
      this.router.navigate(['/operations/pickup-release', item.reliefpkg_id]);
      return;
    }
    this.router.navigate(['/operations/dispatch', item.reliefpkg_id]);
  }

  primaryActionLabel(item: DispatchQueueItem): string {
    return this.isPickupRelease(item)
      ? 'Open pickup release'
      : 'Open dispatch';
  }

  primaryActionIcon(item: DispatchQueueItem): string {
    return this.isPickupRelease(item) ? 'front_hand' : 'local_shipping';
  }

  trackByPackageId(_index: number, item: DispatchQueueItem): number {
    return item.reliefpkg_id;
  }

  chipTone(tone: OperationsTone): 'neutral' | 'soft' | 'critical' | 'warning' | 'success' | 'info' | 'outline' {
    return mapOperationsToneToChipTone(tone);
  }

  private getDispatchStage(row: DispatchQueueItem): DispatchStage {
    return getOperationsDispatchStage(row);
  }

  private summarizeDispatchStages(rows: readonly DispatchQueueItem[]): {
    ready: number;
    inTransit: number;
    completed: number;
  } {
    let ready = 0;
    let inTransit = 0;
    let completed = 0;

    for (const row of rows) {
      switch (this.getDispatchStage(row)) {
        case 'ready':
          ready += 1;
          break;
        case 'in_transit':
          inTransit += 1;
          break;
        case 'completed':
          completed += 1;
          break;
        default:
          break;
      }
    }

    return { ready, inTransit, completed };
  }

  private loadQueue(): void {
    this.loading.set(true);

    this.operationsService.getDispatchQueue().subscribe({
      next: (response) => {
        this.items.set(response.results);
        this.syncSeenFilterForActiveView();
        this.loading.set(false);
      },
      error: () => {
        this.items.set([]);
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

  private markFilterSeen(filter: DispatchFilter): void {
    if (filter === 'all') {
      return;
    }

    const ids = this.getFilterPackageIds(filter);
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

  private getFilterPackageIds(
    filter: Exclude<DispatchFilter, 'all'>,
    rows: readonly DispatchQueueItem[] = this.items(),
  ): number[] {
    return rows
      .filter((row) => this.getDispatchStage(row) === filter)
      .map((row) => row.reliefpkg_id);
  }

  private isPickupRelease(item: Pick<DispatchQueueItem, 'fulfillment_mode' | 'status_code' | 'execution_status'>): boolean {
    return item.fulfillment_mode === 'PICKUP_AT_STAGING'
      || String(item.execution_status ?? item.status_code ?? '').trim().toUpperCase() === 'READY_FOR_PICKUP';
  }
}
