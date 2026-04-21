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
import { Router, RouterLink } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';

import { AuthRbacService } from '../../replenishment/services/auth-rbac.service';
import { DmisEmptyStateComponent } from '../../replenishment/shared/dmis-empty-state/dmis-empty-state.component';
import { DmisSkeletonLoaderComponent } from '../../replenishment/shared/dmis-skeleton-loader/dmis-skeleton-loader.component';
import type { OpsMetricStripItem } from '../shared/ops-metric-strip.component';
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
export type TimeInStageTone = 'fresh' | 'normal' | 'stale' | 'breach';

const OUT_OF_CONTRACT_PACKAGE_STATUSES = new Set(['DISPATCHED', 'RECEIVED']);
const OUT_OF_CONTRACT_REQUEST_STATUSES = new Set(['REJECTED']);
const OUT_OF_CONTRACT_LEGACY_STATUSES = new Set(['D', 'C']);

const PAGE_SIZE = 5;

// SLA thresholds (hours) — placeholder per design spec §14 Q2.
const TIME_IN_STAGE_THRESHOLDS = {
  fresh: 4,
  normal: 24,
  stale: 48,
} as const;

interface ActionInboxPill {
  readonly token: Exclude<FulfillmentFilter, 'all'>;
  readonly label: string;
  readonly count: number;
  readonly severity: 'info' | 'warning' | 'success';
  readonly icon: string;
}

@Component({
  selector: 'app-package-fulfillment-queue',
  standalone: true,
  imports: [
    FormsModule,
    RouterLink,
    MatButtonModule,
    MatIconModule,
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
  private readonly warnedOutOfContractRequestIds = new Set<number>();

  readonly loading = signal(true);
  readonly loadError = signal<string | null>(null);
  readonly items = signal<PackageQueueItem[]>([]);
  readonly searchTerm = signal('');
  readonly activeFilter = signal<FulfillmentFilter>('all');
  readonly seenFilters = signal<Record<string, number[]>>({});
  readonly page = signal(1);

  // Secondary scoped filters rendered as toolbar selects — currently
  // presentational pass-through; backend integration is tracked as a
  // follow-up so the visual toolbar matches the approved design today.
  readonly priorityFilter = signal<'all' | 'HIGH' | 'MEDIUM' | 'LOW'>('all');
  readonly warehouseFilter = signal<string>('all');
  readonly sortOrder = signal<'oldest' | 'newest'>('oldest');

  readonly errored = computed(() => !this.loading() && this.loadError() !== null);

  readonly filterOptions: readonly { label: string; value: FulfillmentFilter }[] = [
    { label: 'All', value: 'all' },
    { label: 'Awaiting', value: 'awaiting' },
    { label: 'Drafts', value: 'drafts' },
    { label: 'Preparing', value: 'preparing' },
    { label: 'Ready', value: 'ready' },
  ];

  readonly pageSize = PAGE_SIZE;

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

  readonly totalPages = computed(() =>
    Math.max(1, Math.ceil(this.filteredItems().length / PAGE_SIZE)),
  );

  readonly currentPage = computed(() => Math.min(this.page(), this.totalPages()));

  readonly pagedItems = computed(() => {
    const rows = this.filteredItems();
    const page = this.currentPage();
    const start = (page - 1) * PAGE_SIZE;
    return rows.slice(start, start + PAGE_SIZE);
  });

  readonly pageRange = computed(() => {
    const total = this.filteredItems().length;
    if (total === 0) {
      return { start: 0, end: 0, total: 0 };
    }
    const page = this.currentPage();
    const start = (page - 1) * PAGE_SIZE + 1;
    const end = Math.min(start + PAGE_SIZE - 1, total);
    return { start, end, total };
  });

  readonly visiblePages = computed<(number | 'ellipsis')[]>(() => {
    const total = this.totalPages();
    const current = this.currentPage();
    if (total <= 5) {
      return Array.from({ length: total }, (_, i) => i + 1);
    }
    const pages: (number | 'ellipsis')[] = [1];
    const start = Math.max(2, current - 1);
    const end = Math.min(total - 1, current + 1);
    if (start > 2) pages.push('ellipsis');
    for (let i = start; i <= end; i++) pages.push(i);
    if (end < total - 1) pages.push('ellipsis');
    pages.push(total);
    return pages;
  });

  readonly queueStats = computed(() => {
    const items = this.items();
    const awaiting = items.filter((item) => this.getFulfillmentStage(item) === 'awaiting').length;
    const drafts = items.filter((item) => this.getFulfillmentStage(item) === 'drafts').length;
    const preparing = items.filter((item) => this.getFulfillmentStage(item) === 'preparing').length;
    const ready = items.filter((item) => this.getFulfillmentStage(item) === 'ready').length;
    return [
      {
        id: 'awaiting' as const,
        label: 'Awaiting Fulfillment',
        value: awaiting,
        note: 'New work in queue',
        icon: 'pending_actions',
      },
      {
        id: 'drafts' as const,
        label: 'Drafts to Resume',
        value: drafts,
        note: 'Saved package work',
        icon: 'drafts',
      },
      {
        id: 'preparing' as const,
        label: 'Preparing',
        value: preparing,
        note: 'Reservation in progress',
        icon: 'inventory_2',
      },
      {
        id: 'ready' as const,
        label: 'Ready to Dispatch',
        value: ready,
        note: 'Packages committed',
        icon: 'local_shipping',
      },
    ];
  });

  readonly queueMetrics = computed<readonly OpsMetricStripItem[]>(() => {
    const active = this.activeFilter();
    return this.queueStats().map((stat) => ({
      label: stat.label,
      value: String(stat.value),
      hint: stat.note,
      interactive: true,
      token: stat.id,
      active: active === stat.id,
      icon: stat.icon,
      ariaLabel: `Filter queue to ${stat.label.toLowerCase()}, ${stat.value} ${stat.value === 1 ? 'package' : 'packages'}${active === stat.id ? ', active filter' : ''}`,
    }));
  });

  readonly activeQueueCount = computed(() =>
    this.items().filter((item) => this.getFulfillmentStage(item) !== 'excluded').length,
  );

  readonly defaultWarehouseLabel = signal('All warehouses');

  readonly actionInbox = computed<readonly ActionInboxPill[]>(() => {
    const stats = this.queueStats();
    const awaiting = stats.find((s) => s.id === 'awaiting')?.value ?? 0;
    const drafts = stats.find((s) => s.id === 'drafts')?.value ?? 0;
    const ready = stats.find((s) => s.id === 'ready')?.value ?? 0;

    const pills: ActionInboxPill[] = [];
    if (drafts > 0) {
      pills.push({
        token: 'drafts',
        label: drafts === 1 ? '1 draft to resume' : `${drafts} drafts to resume`,
        count: drafts,
        severity: 'info',
        icon: 'edit_note',
      });
    }
    if (awaiting > 0) {
      pills.push({
        token: 'awaiting',
        label:
          awaiting === 1
            ? '1 awaiting stock reservation'
            : `${awaiting} awaiting stock reservation`,
        count: awaiting,
        severity: 'warning',
        icon: 'pending_actions',
      });
    }
    if (ready > 0) {
      pills.push({
        token: 'ready',
        label: ready === 1 ? '1 ready to hand off' : `${ready} ready to hand off`,
        count: ready,
        severity: 'success',
        icon: 'local_shipping',
      });
    }
    return pills;
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

  readonly filterChipCounts = computed<Record<FulfillmentFilter, number>>(() => {
    const stats = this.queueStats();
    return {
      all: this.activeQueueCount(),
      awaiting: stats.find((s) => s.id === 'awaiting')?.value ?? 0,
      drafts: stats.find((s) => s.id === 'drafts')?.value ?? 0,
      preparing: stats.find((s) => s.id === 'preparing')?.value ?? 0,
      ready: stats.find((s) => s.id === 'ready')?.value ?? 0,
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
    this.page.set(1);
  }

  setFilter(filter: FulfillmentFilter): void {
    if (this.activeFilter() !== filter) {
      this.page.set(1);
    }
    this.activeFilter.set(filter);
    this.markFilterSeen(filter);
  }

  onMetricClick(item: OpsMetricStripItem): void {
    const token = item.token as FulfillmentFilter | undefined;
    if (!token) {
      return;
    }
    this.setFilter(token);
  }

  onInboxClick(pill: ActionInboxPill): void {
    this.setFilter(pill.token);
  }

  onFilterKeydown(event: KeyboardEvent, index: number): void {
    handleRovingRadioKeydown(event, index, this.filterOptions, (value) => this.setFilter(value));
  }

  nextAction(row: PackageQueueItem): { label: string; icon: string } {
    const stage = this.getFulfillmentStage(row);
    switch (stage) {
      case 'drafts':
        return { label: 'Resume draft', icon: 'edit_note' };
      case 'preparing':
        return { label: 'Continue packing', icon: 'inventory_2' };
      case 'ready':
        return { label: 'Hand off to dispatch', icon: 'local_shipping' };
      case 'awaiting':
      default:
        return { label: 'Allocate stock', icon: 'play_arrow' };
    }
  }

  nextActionAriaLabel(row: PackageQueueItem): string {
    const { label } = this.nextAction(row);
    const id = row.tracking_no ?? `REQ-${row.reliefrqst_id}`;
    return `${label} for ${id}`;
  }

  timeInStageHours(row: PackageQueueItem): number | null {
    const value = row.create_dtime ?? row.request_date;
    if (!value) {
      return null;
    }
    const then = new Date(value).getTime();
    if (Number.isNaN(then)) {
      return null;
    }
    return Math.max(0, (Date.now() - then) / (60 * 60 * 1000));
  }

  timeInStageTone(row: PackageQueueItem): TimeInStageTone {
    const hours = this.timeInStageHours(row);
    if (hours === null) {
      return 'normal';
    }
    if (hours < TIME_IN_STAGE_THRESHOLDS.fresh) {
      return 'fresh';
    }
    if (hours < TIME_IN_STAGE_THRESHOLDS.normal) {
      return 'normal';
    }
    if (hours < TIME_IN_STAGE_THRESHOLDS.stale) {
      return 'stale';
    }
    return 'breach';
  }

  stageLabel(row: PackageQueueItem): string {
    const stage = this.getFulfillmentStage(row);
    switch (stage) {
      case 'awaiting':
        return 'Awaiting';
      case 'drafts':
        return 'Draft';
      case 'preparing':
        return 'Preparing';
      case 'ready':
        return 'Ready';
      default:
        return '—';
    }
  }

  stageBadgeLabel(id: 'awaiting' | 'drafts' | 'preparing' | 'ready'): string {
    switch (id) {
      case 'awaiting':
        return 'AWAITING';
      case 'drafts':
        return 'DRAFT';
      case 'preparing':
        return 'PREPARING';
      case 'ready':
        return 'READY';
    }
  }

  inboxBody(pill: ActionInboxPill): string {
    // Strip the leading numeric count because the badge already shows it —
    // keeps the row visually balanced without duplicating the number.
    return pill.label.replace(/^\d+\s+/, '');
  }

  onPriorityChange(value: string): void {
    const next = (value === 'HIGH' || value === 'MEDIUM' || value === 'LOW')
      ? value
      : 'all';
    this.priorityFilter.set(next);
  }

  onWarehouseChange(value: string): void {
    this.warehouseFilter.set(value || 'all');
  }

  onSortChange(value: string): void {
    this.sortOrder.set(value === 'newest' ? 'newest' : 'oldest');
  }

  stageDotClass(row: PackageQueueItem): string {
    const stage = this.getFulfillmentStage(row);
    return stage === 'excluded' ? '' : `ops-stage-dot--${stage}`;
  }

  stageClass(row: PackageQueueItem): string {
    const stage = this.getFulfillmentStage(row);
    return stage === 'excluded' ? '' : `ops-row--${stage}`;
  }

  actionClass(row: PackageQueueItem): string {
    const stage = this.getFulfillmentStage(row);
    return stage === 'excluded' ? 'pfq-action--awaiting' : `pfq-action--${stage}`;
  }

  ageClass(row: PackageQueueItem): string {
    const days = this.ageInDays(row.create_dtime ?? row.request_date);
    if (days === null) {
      return '';
    }
    if (days >= 14) {
      return 'ops-age--old';
    }
    if (days <= 3) {
      return 'ops-age--fresh';
    }
    return '';
  }

  private ageInDays(value: string | null | undefined): number | null {
    if (!value) {
      return null;
    }
    const then = new Date(value).getTime();
    if (Number.isNaN(then)) {
      return null;
    }
    const diffMs = Date.now() - then;
    return Math.max(0, Math.floor(diffMs / (24 * 60 * 60 * 1000)));
  }

  hasUnread(filter: FulfillmentFilter): boolean {
    return filter !== 'all' && this.unreadCount(filter) > 0;
  }

  unreadCount(filter: FulfillmentFilter): number {
    return this.unreadCounts()[filter] ?? 0;
  }

  filterAriaLabel(label: string, filter: FulfillmentFilter): string {
    const count = this.filterChipCounts()[filter] ?? 0;
    const unread = this.unreadCount(filter);
    const base = `${label}, ${count} ${count === 1 ? 'request' : 'requests'}`;
    if (!unread) {
      return base;
    }
    return `${base}, ${unread} new ${unread === 1 ? 'request' : 'requests'}`;
  }

  setPage(page: number): void {
    const clamped = Math.max(1, Math.min(this.totalPages(), page));
    this.page.set(clamped);
  }

  nextPage(): void {
    this.setPage(this.currentPage() + 1);
  }

  prevPage(): void {
    this.setPage(this.currentPage() - 1);
  }

  trackByPage(_index: number, value: number | 'ellipsis'): string {
    return typeof value === 'number' ? `p-${value}` : `e-${_index}`;
  }

  private isOutOfContractRow(row: PackageQueueItem): boolean {
    const currentStatus = String(row.current_package?.status_code ?? '').trim().toUpperCase();
    const rowStatus = String(row.status_code ?? '').trim().toUpperCase();
    const legacyStatus = String(row.package_status ?? '').trim().toUpperCase();

    return (
      OUT_OF_CONTRACT_PACKAGE_STATUSES.has(currentStatus)
      || OUT_OF_CONTRACT_REQUEST_STATUSES.has(rowStatus)
      || OUT_OF_CONTRACT_LEGACY_STATUSES.has(legacyStatus)
    );
  }

  private warnOutOfContractRows(rows: readonly PackageQueueItem[]): void {
    for (const row of rows) {
      if (!this.isOutOfContractRow(row) || this.warnedOutOfContractRequestIds.has(row.reliefrqst_id)) {
        continue;
      }
      this.warnedOutOfContractRequestIds.add(row.reliefrqst_id);
      console.warn('[fulfillment-queue] backend leaked out-of-contract row', {
        reliefrqst_id: row.reliefrqst_id,
        status_code: row.status_code,
        package_status: row.package_status,
        package_current_status: row.current_package?.status_code ?? null,
      });
    }
  }

  getFulfillmentStage(row: PackageQueueItem): FulfillmentStage {
    const currentStatus = String(row.current_package?.status_code ?? '').trim().toUpperCase();
    const legacyStatus = String(row.package_status ?? '').trim().toUpperCase();

    // TODO(FR05.08-FE-DEFENSIVE-FILTER): sunset after backend contract confirmed
    // clean in staging for 2 weeks. Tracking issue logged in PR body.
    if (this.isOutOfContractRow(row)) {
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
        const rows = response.results;
        this.warnOutOfContractRows(rows);
        this.items.set(rows);
        this.loadError.set(null);
        this.page.set(1);
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
