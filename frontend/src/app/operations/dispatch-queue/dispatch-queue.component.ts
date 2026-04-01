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
  getOperationsPackageTone,
  mapOperationsToneToChipTone,
  OperationsTone,
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
  private readonly operationsService = inject(OperationsService);
  private readonly router = inject(Router);

  readonly loading = signal(true);
  readonly items = signal<DispatchQueueItem[]>([]);
  readonly searchTerm = signal('');
  readonly activeFilter = signal<DispatchFilter>('all');

  readonly filterOptions: readonly { label: string; value: DispatchFilter }[] = [
    { label: 'All', value: 'all' },
    { label: 'Ready', value: 'ready' },
    { label: 'In Transit', value: 'in_transit' },
    { label: 'Completed', value: 'completed' },
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
    const ready = items.filter((item) => this.getDispatchStage(item) === 'ready').length;
    const inTransit = items.filter((item) => this.getDispatchStage(item) === 'in_transit').length;
    const completed = items.filter((item) => this.getDispatchStage(item) === 'completed').length;
    return [
      { label: 'Ready', value: ready, note: 'Awaiting handoff' },
      { label: 'In Transit', value: inTransit, note: 'Dispatched, receipt pending' },
      { label: 'Completed', value: completed, note: 'Receipt confirmed' },
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
    return {
      total: rows.length,
      ready: rows.filter((r) => this.getDispatchStage(r) === 'ready').length,
      inTransit: rows.filter((r) => this.getDispatchStage(r) === 'in_transit').length,
      completed: rows.filter((r) => this.getDispatchStage(r) === 'completed').length,
    };
  });

  readonly formatPackageStatus = formatOperationsPackageStatus;
  readonly formatAge = formatOperationsAge;
  readonly formatDateTime = formatOperationsDateTime;
  readonly getPackageTone = getOperationsPackageTone;

  ngOnInit(): void {
    this.refreshQueue();
  }

  refreshQueue(): void {
    this.loadQueue();
  }

  setFilter(filter: DispatchFilter): void {
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

  onSearch(value: string): void {
    this.searchTerm.set(value);
  }

  viewDispatch(item: DispatchQueueItem): void {
    this.router.navigate(['/operations/dispatch', item.reliefpkg_id]);
  }

  trackByPackageId(_index: number, item: DispatchQueueItem): number {
    return item.reliefpkg_id;
  }

  chipTone(tone: OperationsTone): 'neutral' | 'soft' | 'critical' | 'warning' | 'success' | 'info' | 'outline' {
    return mapOperationsToneToChipTone(tone);
  }

  private getDispatchStage(row: DispatchQueueItem): DispatchStage {
    const s = String(row.status_code ?? '').trim().toUpperCase();
    if (s === 'P' || s === 'COMMITTED' || s === 'READY_FOR_DISPATCH') {
      return 'ready';
    }
    if ((s === 'D' || s === 'DISPATCHED') && !row.received_dtime) {
      return 'in_transit';
    }
    if (s === 'C' || s === 'RECEIVED') {
      return 'completed';
    }
    return 'unknown';
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

    this.operationsService.getDispatchQueue().subscribe({
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
