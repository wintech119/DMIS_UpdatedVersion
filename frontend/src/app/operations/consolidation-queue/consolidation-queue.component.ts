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
  formatOperationsUrgency,
  formatLegProgressLabel,
  getConsolidationStageFromLegs,
  getLegProgressTone,
  getOperationsConsolidationStatusTone,
  getOperationsUrgencyTone,
  handleRovingRadioKeydown,
  mapOperationsToneToChipTone,
  OperationsTone,
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
  private readonly operationsService = inject(OperationsService);
  private readonly router = inject(Router);

  readonly loading = signal(true);
  readonly items = signal<PackageQueueItem[]>([]);
  readonly searchTerm = signal('');
  readonly activeFilter = signal<ConsolidationFilter>('all');

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
    const active = this.activeFilter();
    return [
      {
        label: 'In Consolidation',
        value: String(stats.total),
        hint: 'Staged packages with active legs',
        interactive: true,
        token: 'all',
        active: active === 'all',
        accent: '#6b7280',
      },
      {
        label: 'Awaiting Legs',
        value: String(stats.awaiting),
        hint: 'Planned, not yet dispatched',
        interactive: true,
        token: 'awaiting',
        active: active === 'awaiting',
        accent: '#b7833f',
      },
      {
        label: 'In Transit',
        value: String(stats.inTransit),
        hint: 'Legs en route to hub',
        interactive: true,
        token: 'in_transit',
        active: active === 'in_transit',
        accent: '#17447f',
      },
      {
        label: 'Partial',
        value: String(stats.partial),
        hint: 'Some legs received',
        interactive: true,
        token: 'partial',
        active: active === 'partial',
        accent: '#7a4fd1',
      },
      {
        label: 'Ready to Dispatch',
        value: String(stats.ready),
        hint: 'All legs received',
        interactive: true,
        token: 'ready',
        active: active === 'ready',
        accent: '#2e8a48',
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

  openMetric(metric: OpsMetricStripItem): void {
    if (!this.isConsolidationFilter(metric.token)) {
      return;
    }
    this.setFilter(metric.token);
  }

  private isConsolidationFilter(value: string | undefined): value is ConsolidationFilter {
    return value === 'all'
      || value === 'awaiting'
      || value === 'in_transit'
      || value === 'partial'
      || value === 'ready';
  }

  getConsolidationStage(row: PackageQueueItem): ConsolidationStage {
    return getConsolidationStageFromLegs(row.current_package?.leg_summary);
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
