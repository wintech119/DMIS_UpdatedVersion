import {
  Component,
  ChangeDetectionStrategy,
  computed,
  inject,
  signal,
  OnInit,
} from '@angular/core';
import { Router } from '@angular/router';
import { DatePipe } from '@angular/common';

import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatTableModule } from '@angular/material/table';

import { DmisEmptyStateComponent } from '../../replenishment/shared/dmis-empty-state/dmis-empty-state.component';
import { DmisSkeletonLoaderComponent } from '../../replenishment/shared/dmis-skeleton-loader/dmis-skeleton-loader.component';
import { OpsMetricStripComponent, OpsMetricStripItem } from '../shared/ops-metric-strip.component';
import { OpsStatusChipComponent } from '../shared/ops-status-chip.component';
import { OperationsService } from '../services/operations.service';
import { DispatchQueueItem } from '../models/operations.model';
import { formatPackageStatus } from '../models/operations-status.util';

type DispatchFilter = 'all' | 'ready' | 'in_transit' | 'completed';

@Component({
  selector: 'app-dispatch-queue',
  standalone: true,
  imports: [
    DatePipe,
    MatCardModule,
    MatButtonModule,
    MatIconModule,
    MatTableModule,
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
  readonly activeFilter = signal<DispatchFilter>('all');

  readonly filterOptions: readonly { label: string; value: DispatchFilter }[] = [
    { label: 'All', value: 'all' },
    { label: 'Ready', value: 'ready' },
    { label: 'In Transit', value: 'in_transit' },
    { label: 'Completed', value: 'completed' },
  ];

  readonly filteredItems = computed(() => {
    const filter = this.activeFilter();
    const allItems = this.items();
    const norm = (code: string | undefined) => String(code ?? '').trim().toUpperCase();
    switch (filter) {
      case 'ready':
        return allItems.filter((item) => {
          const s = norm(item.status_code);
          return s === 'P' || s === 'COMMITTED' || s === 'READY_FOR_DISPATCH';
        });
      case 'in_transit':
        return allItems.filter((item) => {
          const s = norm(item.status_code);
          return (s === 'D' || s === 'DISPATCHED') && !item.received_dtime;
        });
      case 'completed':
        return allItems.filter((item) => {
          const s = norm(item.status_code);
          return s === 'C' || s === 'RECEIVED';
        });
      default:
        return allItems;
    }
  });

  readonly queueStats = computed(() => {
    const items = this.items();
    const norm = (code: string | undefined) => String(code ?? '').trim().toUpperCase();
    const ready = items.filter((item) => {
      const s = norm(item.status_code);
      return s === 'P' || s === 'COMMITTED' || s === 'READY_FOR_DISPATCH';
    }).length;
    const inTransit = items.filter((item) => {
      const s = norm(item.status_code);
      return (s === 'D' || s === 'DISPATCHED') && !item.received_dtime;
    }).length;
    const recentlyDispatched = items.filter((item) => {
      const s = norm(item.status_code);
      if ((s !== 'C' && s !== 'RECEIVED') || !item.received_dtime) {
        return false;
      }
      const receivedDate = new Date(item.received_dtime);
      const ageMs = Date.now() - receivedDate.getTime();
      return ageMs >= 0 && ageMs < 48 * 60 * 60 * 1000;
    }).length;
    const completed = items.filter((item) => {
      const s = norm(item.status_code);
      return s === 'C' || s === 'RECEIVED';
    }).length;
    return [
      { label: 'Ready', value: ready, note: 'Awaiting handoff' },
      { label: 'In Transit', value: inTransit, note: 'Dispatched, receipt pending' },
      { label: 'Recently Dispatched', value: recentlyDispatched, note: 'Received within 48h' },
      { label: 'Completed', value: completed, note: 'Receipt confirmed' },
    ];
  });

  readonly queueMetrics = computed<readonly OpsMetricStripItem[]>(() =>
    this.queueStats().map((stat) => ({
      label: stat.label,
      value: String(stat.value),
      hint: stat.note,
    })),
  );

  readonly displayedColumns = [
    'package_tracking_no',
    'request',
    'agency',
    'status',
    'dispatch_date',
    'actions',
  ];

  readonly formatPackageStatus = formatPackageStatus;

  ngOnInit(): void {
    this.refreshQueue();
  }

  refreshQueue(): void {
    this.loadQueue();
  }

  setFilter(filter: DispatchFilter): void {
    this.activeFilter.set(filter);
  }

  viewDispatch(item: DispatchQueueItem): void {
    this.router.navigate(['/operations/dispatch', item.reliefpkg_id]);
  }

  trackByPackageId(_index: number, item: DispatchQueueItem): number {
    return item.reliefpkg_id;
  }

  statusTone(code: string | null | undefined): 'neutral' | 'soft' | 'critical' | 'warning' | 'success' | 'info' | 'outline' {
    switch (String(code ?? '').trim().toUpperCase()) {
      case 'C':
      case 'RECEIVED':
        return 'success';
      case 'D':
      case 'DISPATCHED':
        return 'info';
      case 'P':
      case 'COMMITTED':
      case 'READY_FOR_DISPATCH':
        return 'warning';
      case 'A':
      case 'DRAFT':
        return 'soft';
      case 'PENDING_OVERRIDE_APPROVAL':
        return 'warning';
      case 'CANCELLED':
        return 'neutral';
      default:
        return 'neutral';
    }
  }

  transportTone(value: string | null | undefined): 'neutral' | 'soft' | 'critical' | 'warning' | 'success' | 'info' | 'outline' {
    return String(value ?? '').trim() ? 'soft' : 'neutral';
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
