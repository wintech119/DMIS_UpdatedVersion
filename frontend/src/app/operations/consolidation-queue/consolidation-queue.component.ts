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

import { AuthRbacService } from '../../replenishment/services/auth-rbac.service';
import { DmisNotificationService } from '../../replenishment/services/notification.service';
import { DmisEmptyStateComponent } from '../../replenishment/shared/dmis-empty-state/dmis-empty-state.component';
import { DmisSkeletonLoaderComponent } from '../../replenishment/shared/dmis-skeleton-loader/dmis-skeleton-loader.component';
import { OpsMetricStripComponent, OpsMetricStripItem } from '../shared/ops-metric-strip.component';
import { OpsStatusChipComponent } from '../shared/ops-status-chip.component';
import { OperationsService } from '../services/operations.service';
import { PackageQueueItem, PackageLegSummary } from '../models/operations.model';
import {
  formatOperationsAge,
  formatOperationsConsolidationStatus,
  formatOperationsDateTime,
  formatOperationsFulfillmentMode,
  formatOperationsRefreshedLabel,
  formatOperationsUrgency,
  formatLegProgressLabel,
  getConsolidationStageFromLegs,
  getLegProgressTone,
  getOperationsConsolidationStatusTone,
  getOperationsTimeInStageTone,
  getOperationsUrgencyTone,
  handleRovingRadioKeydown,
  mapOperationsToneToChipTone,
  OperationsTone,
  OperationsTimeInStageTone,
  type ConsolidationStage,
} from '../operations-display.util';

type ConsolidationFilter = ConsolidationStage | 'all';

@Component({
  selector: 'app-consolidation-queue',
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
  templateUrl: './consolidation-queue.component.html',
  styleUrls: ['./consolidation-queue.component.scss', '../operations-shell.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ConsolidationQueueComponent implements OnInit {
  private readonly auth = inject(AuthRbacService);
  private readonly notifications = inject(DmisNotificationService);
  private readonly operationsService = inject(OperationsService);
  private readonly router = inject(Router);

  readonly loading = signal(true);
  readonly items = signal<PackageQueueItem[]>([]);
  readonly searchTerm = signal('');
  readonly activeFilter = signal<ConsolidationFilter>('all');
  readonly lastRefreshedAt = signal<number>(Date.now());

  readonly lastRefreshedLabel = computed(() => formatOperationsRefreshedLabel(this.lastRefreshedAt()));

  readonly filterOptions: readonly { label: string; value: ConsolidationFilter }[] = [
    { label: 'Awaiting legs', value: 'awaiting' },
    { label: 'In transit', value: 'in_transit' },
    { label: 'Partially received', value: 'partial' },
    { label: 'Ready to dispatch', value: 'ready' },
    { label: 'All', value: 'all' },
  ];

  /**
   * Only staged packages (non-DIRECT) with materialized legs appear here.
   * A staged package without a committed plan has no legs yet and belongs
   * on the Package Fulfillment queue, not the Consolidation queue.
   */
  readonly stagedItems = computed(() =>
    this.items().filter((row) => {
      const pkg = row.current_package;
      if (!pkg) {
        return false;
      }
      const mode = String(pkg.fulfillment_mode ?? '').toUpperCase();
      if (!mode || mode === 'DIRECT') {
        return false;
      }
      const total = pkg.leg_summary?.total_legs ?? 0;
      return total > 0;
    }),
  );

  readonly activeQueueCount = computed(() => this.stagedItems().length);

  readonly filteredItems = computed(() => {
    const term = this.searchTerm().trim().toLowerCase();
    const filter = this.activeFilter();

    return this.stagedItems().filter((row) => {
      if (filter !== 'all' && this.getConsolidationStage(row) !== filter) {
        return false;
      }
      if (!term) {
        return true;
      }
      const haystack = [
        row.tracking_no,
        row.agency_name,
        row.event_name,
        row.current_package?.tracking_no,
        row.current_package?.destination_warehouse_name,
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase();
      return haystack.includes(term);
    });
  });

  readonly queueStats = computed(() => {
    const rows = this.stagedItems();
    let awaiting = 0;
    let inTransit = 0;
    let partial = 0;
    let ready = 0;
    for (const row of rows) {
      switch (this.getConsolidationStage(row)) {
        case 'awaiting':
          awaiting += 1;
          break;
        case 'in_transit':
          inTransit += 1;
          break;
        case 'partial':
          partial += 1;
          break;
        case 'ready':
          ready += 1;
          break;
      }
    }
    return { total: rows.length, awaiting, inTransit, partial, ready };
  });

  readonly queueMetrics = computed<readonly OpsMetricStripItem[]>(() => {
    const stats = this.queueStats();
    return [
      {
        label: 'In Consolidation',
        value: String(stats.total),
        hint: 'Staged packages with active legs',
        token: 'info',
        badge: { label: 'STAGED', tone: 'info' },
      },
      {
        label: 'Awaiting Legs',
        value: String(stats.awaiting),
        hint: 'Planned, not yet dispatched',
        token: 'awaiting',
        interactive: true,
        active: this.activeFilter() === 'awaiting',
        badge: { label: 'AWAITING', tone: 'awaiting' },
      },
      {
        label: 'In Transit',
        value: String(stats.inTransit),
        hint: 'Legs en route to hub',
        token: 'transit',
        interactive: true,
        active: this.activeFilter() === 'in_transit',
        badge: { label: 'TRANSIT', tone: 'transit' },
      },
      {
        label: 'Partial',
        value: String(stats.partial),
        hint: 'Some legs received',
        token: 'preparing',
        interactive: true,
        active: this.activeFilter() === 'partial',
        badge: { label: 'PARTIAL', tone: 'preparing' },
      },
      {
        label: 'Ready to Dispatch',
        value: String(stats.ready),
        hint: 'All legs received',
        token: 'ready',
        interactive: true,
        active: this.activeFilter() === 'ready',
        badge: { label: 'READY', tone: 'ready' },
      },
    ];
  });

  readonly sidebarSummary = computed(() => {
    const rows = this.filteredItems();
    const hubCounts = new Map<string, { count: number; label: string }>();
    for (const row of rows) {
      const pkg = row.current_package;
      const hubId = pkg?.staging_warehouse_id ?? pkg?.to_inventory_id;
      if (hubId == null) {
        continue;
      }
      const key = String(hubId);
      const label = pkg?.destination_warehouse_name ?? `Hub #${hubId}`;
      const existing = hubCounts.get(key);
      hubCounts.set(key, {
        count: (existing?.count ?? 0) + 1,
        label: existing?.label ?? label,
      });
    }
    return {
      total: rows.length,
      hubs: Array.from(hubCounts.entries())
        .map(([hubId, value]) => ({ hubId, count: value.count, label: value.label }))
        .sort((a, b) => b.count - a.count),
    };
  });

  readonly formatConsolidationStatus = formatOperationsConsolidationStatus;
  readonly formatFulfillmentMode = formatOperationsFulfillmentMode;
  readonly formatUrgency = formatOperationsUrgency;
  readonly formatAge = formatOperationsAge;
  readonly formatDateTime = formatOperationsDateTime;
  readonly formatLegProgress = formatLegProgressLabel;
  readonly getConsolidationStatusTone = getOperationsConsolidationStatusTone;
  readonly getUrgencyTone = getOperationsUrgencyTone;
  readonly legProgressTone = getLegProgressTone;

  ngOnInit(): void {
    this.refreshQueue();
  }

  refreshQueue(): void {
    this.loadQueue();
  }

  openConsolidation(item: PackageQueueItem): void {
    const pkgId = item.current_package?.reliefpkg_id;
    if (pkgId == null) {
      return;
    }
    this.router.navigate(['/operations/consolidation', pkgId]);
  }

  trackByRequestId(_index: number, item: PackageQueueItem): number {
    return item.reliefrqst_id;
  }

  chipTone(tone: OperationsTone): 'neutral' | 'soft' | 'critical' | 'warning' | 'success' | 'info' | 'outline' {
    return mapOperationsToneToChipTone(tone);
  }

  legSummary(row: PackageQueueItem): PackageLegSummary | null {
    return row.current_package?.leg_summary ?? null;
  }

  onSearch(value: string): void {
    this.searchTerm.set(value);
  }

  setFilter(filter: ConsolidationFilter): void {
    this.activeFilter.set(filter);
  }

  onFilterKeydown(event: KeyboardEvent, index: number): void {
    handleRovingRadioKeydown(event, index, this.filterOptions, (value) => this.setFilter(value));
  }

  openMetric(item: OpsMetricStripItem): void {
    const filter = this.tileTokenToFilter(item.token);
    if (filter === null) {
      return;
    }
    this.setFilter(filter);
  }

  private tileTokenToFilter(token: string | undefined): ConsolidationFilter | null {
    switch (token) {
      case 'awaiting':
        return 'awaiting';
      case 'transit':
        return 'in_transit';
      case 'preparing':
        return 'partial';
      case 'ready':
        return 'ready';
      default:
        return null;
    }
  }

  getConsolidationStage(row: PackageQueueItem): ConsolidationStage {
    return getConsolidationStageFromLegs(row.current_package?.leg_summary);
  }

  rowStageClass(row: PackageQueueItem): string {
    switch (this.getConsolidationStage(row)) {
      case 'awaiting':
        return 'ops-row--awaiting';
      case 'in_transit':
        return 'ops-row--transit';
      case 'partial':
        return 'ops-row--preparing';
      case 'ready':
        return 'ops-row--ready';
      default:
        return 'ops-row--neutral';
    }
  }

  stageLabel(row: PackageQueueItem): string {
    switch (this.getConsolidationStage(row)) {
      case 'awaiting':
        return 'Awaiting Legs';
      case 'in_transit':
        return 'In Transit';
      case 'partial':
        return 'Partially Received';
      case 'ready':
        return 'Ready to Dispatch';
      default:
        return 'Open';
    }
  }

  stagePillClass(row: PackageQueueItem): string {
    switch (this.getConsolidationStage(row)) {
      case 'awaiting':
        return 'ops-stage-pill--awaiting';
      case 'in_transit':
        return 'ops-stage-pill--transit';
      case 'partial':
        return 'ops-stage-pill--preparing';
      case 'ready':
        return 'ops-stage-pill--ready';
      default:
        return 'ops-stage-pill--neutral';
    }
  }

  timePillClass(row: PackageQueueItem): string {
    return `ops-time-pill--${this.timePillTone(row)}`;
  }

  timePillTone(row: PackageQueueItem): OperationsTimeInStageTone {
    return getOperationsTimeInStageTone(row.create_dtime ?? row.request_date ?? null);
  }

  actionClass(row: PackageQueueItem): string {
    switch (this.getConsolidationStage(row)) {
      case 'ready':
        return 'ops-action--ready';
      case 'partial':
        return 'ops-action--preparing';
      case 'in_transit':
        return 'ops-action--transit';
      case 'awaiting':
        return 'ops-action--awaiting';
      default:
        return 'ops-action--neutral';
    }
  }

  actionLabel(row: PackageQueueItem): string {
    switch (this.getConsolidationStage(row)) {
      case 'ready':
        return 'Release to dispatch';
      case 'partial':
        return 'Review partial release';
      case 'in_transit':
        return 'Track legs';
      case 'awaiting':
        return 'Open consolidation';
      default:
        return 'Open consolidation';
    }
  }

  partyLabel(row: PackageQueueItem): string {
    return row.agency_name ?? `Agency ${row.agency_id}`;
  }

  private loadQueue(): void {
    this.loading.set(true);
    this.operationsService.getPackagesQueue().subscribe({
      next: (response) => {
        this.items.set(response.results);
        this.lastRefreshedAt.set(Date.now());
        this.loading.set(false);
      },
      error: () => {
        this.loading.set(false);
        this.notifications.showNetworkError(
          'We could not refresh the consolidation queue.',
          () => this.loadQueue(),
        );
      },
    });
  }
}
