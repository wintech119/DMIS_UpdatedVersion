import {
  Component,
  ChangeDetectionStrategy,
  computed,
  inject,
  signal,
  OnInit,
} from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';

import { AuthRbacService } from '../../replenishment/services/auth-rbac.service';
import { DmisEmptyStateComponent } from '../../replenishment/shared/dmis-empty-state/dmis-empty-state.component';
import { DmisSkeletonLoaderComponent } from '../../replenishment/shared/dmis-skeleton-loader/dmis-skeleton-loader.component';
import { OpsMetricStripComponent, OpsMetricStripItem } from '../shared/ops-metric-strip.component';
import { OpsStatusChipComponent } from '../shared/ops-status-chip.component';
import { OperationsService } from '../services/operations.service';
import { PackageQueueItem } from '../models/operations.model';
import {
  formatOperationsPackageStatus,
  formatOperationsRequestStatus,
  formatOperationsUrgency,
  formatOperationsAge,
  formatOperationsDateTime,
  formatOperationsLineCount,
  buildOperationsQueueSeenStorageKey,
  countOperationsUnreadIds,
  extractOperationsHttpErrorMessage,
  getOperationsPackageTone,
  getOperationsRequestTone,
  getOperationsUrgencyTone,
  handleRovingRadioKeydown,
  mergeOperationsQueueSeenEntries,
  mapOperationsToneToChipTone,
  OperationsTone,
  readOperationsQueueSeenEntries,
  writeOperationsQueueSeenEntries,
} from '../operations-display.util';

export type FulfillmentFilter = 'all' | 'awaiting' | 'drafts' | 'preparing' | 'ready';
type FulfillmentStage = FulfillmentFilter | 'excluded';

const OUT_OF_CONTRACT_STATUSES = new Set(['DISPATCHED', 'RECEIVED', 'REJECTED']);
const OUT_OF_CONTRACT_LEGACY_STATUSES = new Set(['D', 'C']);

@Component({
  selector: 'app-package-fulfillment-queue',
  standalone: true,
  imports: [
    FormsModule,
    MatButtonModule,
    MatIconModule,
    OpsMetricStripComponent,
    OpsStatusChipComponent,
    DmisEmptyStateComponent,
    DmisSkeletonLoaderComponent,
  ],
  templateUrl: './package-fulfillment-queue.component.html',
  styleUrls: ['./package-fulfillment-queue.component.scss', '../operations-shell.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PackageFulfillmentQueueComponent implements OnInit {
  private readonly auth = inject(AuthRbacService);
  private readonly operationsService = inject(OperationsService);
  private readonly router = inject(Router);
  private readonly seenStorageScope = 'package-fulfillment';

  readonly loading = signal(true);
  readonly loadError = signal<string | null>(null);
  readonly items = signal<PackageQueueItem[]>([]);
  readonly searchTerm = signal('');
  readonly activeFilter = signal<FulfillmentFilter>('all');
  readonly seenFilters = signal<Record<string, number[]>>({});

  readonly errored = computed(() => !this.loading() && this.loadError() !== null);

  readonly filterOptions: readonly { label: string; value: FulfillmentFilter }[] = [
    { label: 'Awaiting', value: 'awaiting' },
    { label: 'Drafts', value: 'drafts' },
    { label: 'Preparing', value: 'preparing' },
    { label: 'Ready', value: 'ready' },
    { label: 'All', value: 'all' },
  ];

  readonly filteredItems = computed(() => {
    const term = this.searchTerm().trim().toLowerCase();
    const filter = this.activeFilter();

    return this.items().filter((row) => {
      const stage = this.getFulfillmentStage(row);
      if (stage === 'excluded') {
        return false;
      }
      if (filter !== 'all' && stage !== filter) {
        return false;
      }
      if (!term) {
        return true;
      }
      const haystack = [
        row.tracking_no ?? `REQ-${row.reliefrqst_id}`,
        row.agency_name,
        row.event_name,
        row.rqst_notes_text,
        row.package_tracking_no,
        row.current_package?.tracking_no,
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase();
      return haystack.includes(term);
    });
  });

  readonly queueStats = computed(() => {
    const items = this.items();
    const total = items.length;
    const awaiting = items.filter((item) => this.getFulfillmentStage(item) === 'awaiting').length;
    const drafts = items.filter((item) => this.getFulfillmentStage(item) === 'drafts').length;
    const preparing = items.filter((item) => this.getFulfillmentStage(item) === 'preparing').length;
    const ready = items.filter((item) => this.getFulfillmentStage(item) === 'ready').length;
    return [
      { label: 'Awaiting Fulfillment', value: awaiting, note: 'New work in queue' },
      { label: 'Drafts To Resume', value: drafts, note: 'Saved package work' },
      { label: 'Preparing', value: preparing, note: 'Reservation in progress' },
      { label: 'Ready to Dispatch', value: ready, note: 'Packages committed' },
      { label: 'All Requests', value: total, note: 'Visible in the queue' },
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
    return {
      total: rows.length,
      awaiting: rows.filter((r) => this.getFulfillmentStage(r) === 'awaiting').length,
      drafts: rows.filter((r) => this.getFulfillmentStage(r) === 'drafts').length,
      preparing: rows.filter((r) => this.getFulfillmentStage(r) === 'preparing').length,
      ready: rows.filter((r) => this.getFulfillmentStage(r) === 'ready').length,
    };
  });

  readonly unreadCounts = computed<Record<FulfillmentFilter, number>>(() => {
    const rows = this.items();
    const seen = this.seenFilters();

    return {
      all: 0,
      awaiting: countOperationsUnreadIds(this.getFilterRequestIds('awaiting', rows), seen['awaiting']),
      drafts: countOperationsUnreadIds(this.getFilterRequestIds('drafts', rows), seen['drafts']),
      preparing: countOperationsUnreadIds(this.getFilterRequestIds('preparing', rows), seen['preparing']),
      ready: countOperationsUnreadIds(this.getFilterRequestIds('ready', rows), seen['ready']),
    };
  });

  readonly formatPackageStatus = formatOperationsPackageStatus;
  readonly formatRequestStatus = formatOperationsRequestStatus;
  readonly formatUrgency = formatOperationsUrgency;
  readonly formatAge = formatOperationsAge;
  readonly formatDateTime = formatOperationsDateTime;
  readonly formatLineCount = formatOperationsLineCount;
  readonly getPackageTone = getOperationsPackageTone;
  readonly getRequestTone = getOperationsRequestTone;
  readonly getUrgencyTone = getOperationsUrgencyTone;

  ngOnInit(): void {
    this.loadSeenFilters();
    this.refreshQueue();
  }

  refreshQueue(): void {
    this.loadQueue();
  }

  fulfillRequest(item: PackageQueueItem): void {
    this.router.navigate(['/operations/package-fulfillment', item.reliefrqst_id]);
  }

  trackByRequestId(_index: number, item: PackageQueueItem): number {
    return item.reliefrqst_id;
  }

  chipTone(tone: OperationsTone): 'neutral' | 'soft' | 'critical' | 'warning' | 'success' | 'info' | 'outline' {
    return mapOperationsToneToChipTone(tone);
  }

  isLocked(row: PackageQueueItem): boolean {
    const exec = String(row.current_package?.execution_status ?? row.execution_status ?? '').trim().toUpperCase();
    return exec === 'COMMITTED';
  }

  isOverridePending(row: PackageQueueItem): boolean {
    const exec = String(row.current_package?.execution_status ?? row.execution_status ?? '').trim().toUpperCase();
    return exec === 'PENDING_OVERRIDE_APPROVAL';
  }

  isDraft(row: PackageQueueItem): boolean {
    return String(row.current_package?.status_code ?? '').trim().toUpperCase() === 'DRAFT';
  }

  isReady(row: PackageQueueItem): boolean {
    // DISPATCHED / RECEIVED rows are excluded by getFulfillmentStage() as
    // out-of-contract for the active-work queue — the legacy branches from
    // the pre-FR05.08 queue have been removed.
    const normalizedStatus = String(row.current_package?.status_code ?? '').trim().toUpperCase();
    return (
      normalizedStatus === 'COMMITTED'
      || normalizedStatus === 'READY_FOR_DISPATCH'
      || normalizedStatus === 'READY_FOR_PICKUP'
      || (normalizedStatus === 'P' && !this.isOverridePending(row))
      || (
        !normalizedStatus
        && String(row.package_status ?? '').trim().toUpperCase() === 'P'
        && !this.isOverridePending(row)
      )
    );
  }

  onSearch(value: string): void {
    this.searchTerm.set(value);
  }

  setFilter(filter: FulfillmentFilter): void {
    this.activeFilter.set(filter);
    this.markFilterSeen(filter);
  }

  onFilterKeydown(event: KeyboardEvent, index: number): void {
    handleRovingRadioKeydown(event, index, this.filterOptions, (value) => this.setFilter(value));
  }

  hasUnread(filter: FulfillmentFilter): boolean {
    return filter !== 'all' && this.unreadCount(filter) > 0;
  }

  unreadCount(filter: FulfillmentFilter): number {
    return this.unreadCounts()[filter] ?? 0;
  }

  filterAriaLabel(label: string, filter: FulfillmentFilter): string {
    const unread = this.unreadCount(filter);
    if (!unread) {
      return label;
    }
    return `${label}, ${unread} new ${unread === 1 ? 'request' : 'requests'}`;
  }

  getFulfillmentStage(row: PackageQueueItem): FulfillmentStage {
    const currentStatus = String(row.current_package?.status_code ?? '').trim().toUpperCase();
    const rowStatus = String(row.status_code ?? '').trim().toUpperCase();
    const legacyStatus = String(row.package_status ?? '').trim().toUpperCase();

    // TODO(FR05.08-FE-DEFENSIVE-FILTER): sunset after backend contract confirmed
    // clean in staging for 2 weeks. Tracking issue logged in PR body.
    if (
      OUT_OF_CONTRACT_STATUSES.has(currentStatus)
      || OUT_OF_CONTRACT_STATUSES.has(rowStatus)
      || OUT_OF_CONTRACT_LEGACY_STATUSES.has(legacyStatus)
    ) {
      console.warn('[fulfillment-queue] backend leaked out-of-contract row', {
        reliefrqst_id: row.reliefrqst_id,
        status_code: row.status_code,
        package_status: row.package_status,
        package_current_status: row.current_package?.status_code ?? null,
      });
      return 'excluded';
    }

    if (!currentStatus && !legacyStatus) return 'awaiting';
    if (currentStatus === 'DRAFT') return 'drafts';
    if (currentStatus === 'PENDING_OVERRIDE_APPROVAL') return 'preparing';
    if (
      currentStatus === 'COMMITTED'
      || currentStatus === 'READY_FOR_DISPATCH'
      || currentStatus === 'READY_FOR_PICKUP'
    ) {
      return 'ready';
    }
    if (legacyStatus === 'P') return this.isOverridePending(row) ? 'preparing' : 'ready';
    return row.current_package ? 'preparing' : 'awaiting';
  }

  private loadQueue(): void {
    this.loading.set(true);
    this.loadError.set(null);

    this.operationsService.getPackagesQueue().subscribe({
      next: (response) => {
        this.items.set(response.results);
        this.loadError.set(null);
        this.syncSeenFilterForActiveView();
        this.loading.set(false);
      },
      error: (error: HttpErrorResponse) => {
        this.items.set([]);
        this.loadError.set(
          extractOperationsHttpErrorMessage(
            error,
            "We couldn't load the fulfillment queue. Check your connection and try again.",
          ),
        );
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

  private markFilterSeen(filter: FulfillmentFilter): void {
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
    filter: Exclude<FulfillmentFilter, 'all'>,
    rows: readonly PackageQueueItem[] = this.items(),
  ): number[] {
    return rows
      .filter((row) => {
        const stage = this.getFulfillmentStage(row);
        return stage !== 'excluded' && stage === filter;
      })
      .map((row) => row.reliefrqst_id);
  }
}
