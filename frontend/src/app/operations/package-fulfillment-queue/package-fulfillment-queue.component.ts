import {
  Component,
  ChangeDetectionStrategy,
  computed,
  inject,
  signal,
  OnInit,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';

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
  getOperationsPackageTone,
  getOperationsRequestTone,
  getOperationsUrgencyTone,
  mapOperationsToneToChipTone,
  OperationsTone,
} from '../operations-display.util';

type FulfillmentFilter = 'all' | 'awaiting' | 'preparing' | 'ready' | 'dispatched';

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
  private readonly operationsService = inject(OperationsService);
  private readonly router = inject(Router);

  readonly loading = signal(true);
  readonly items = signal<PackageQueueItem[]>([]);
  readonly searchTerm = signal('');
  readonly activeFilter = signal<FulfillmentFilter>('all');

  readonly filterOptions: readonly { label: string; value: FulfillmentFilter }[] = [
    { label: 'All', value: 'all' },
    { label: 'Awaiting', value: 'awaiting' },
    { label: 'Preparing', value: 'preparing' },
    { label: 'Ready', value: 'ready' },
    { label: 'Dispatched', value: 'dispatched' },
  ];

  readonly filteredItems = computed(() => {
    const term = this.searchTerm().trim().toLowerCase();
    const filter = this.activeFilter();

    return this.items().filter((row) => {
      if (filter !== 'all' && this.getFulfillmentStage(row) !== filter) {
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
    const preparing = items.filter((item) => this.getFulfillmentStage(item) === 'preparing').length;
    const ready = items.filter((item) => this.getFulfillmentStage(item) === 'ready').length;
    return [
      { label: 'Awaiting Fulfillment', value: awaiting, note: 'New work in queue' },
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
      preparing: rows.filter((r) => this.getFulfillmentStage(r) === 'preparing').length,
      ready: rows.filter((r) => this.getFulfillmentStage(r) === 'ready').length,
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

  isReady(row: PackageQueueItem): boolean {
    const pkg = row.current_package;
    if (!pkg) {
      return false;
    }
    return pkg.status_code === 'P' && !this.isOverridePending(row);
  }

  onSearch(value: string): void {
    this.searchTerm.set(value);
  }

  setFilter(filter: FulfillmentFilter): void {
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

  getFulfillmentStage(row: PackageQueueItem): FulfillmentFilter {
    const pkgStatus = row.current_package?.status_code ?? row.package_status;
    if (!pkgStatus) return 'awaiting';
    if (pkgStatus === 'P') return this.isOverridePending(row) ? 'preparing' : 'ready';
    if (pkgStatus === 'D' || pkgStatus === 'C') return 'dispatched';
    return row.current_package ? 'preparing' : 'awaiting';
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

    this.operationsService.getPackagesQueue().subscribe({
      next: (response) => {
        this.items.set(response.results);
        this.loading.set(false);
      },
      error: () => {
        this.items.set([]);
        this.loading.set(false);
      },
    });
  }
}
