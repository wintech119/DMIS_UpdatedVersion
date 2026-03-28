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
  styleUrl: './dispatch-queue.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DispatchQueueComponent implements OnInit {
  private readonly operationsService = inject(OperationsService);
  private readonly router = inject(Router);

  readonly loading = signal(true);
  readonly items = signal<DispatchQueueItem[]>([]);

  readonly queueStats = computed(() => {
    const items = this.items();
    const total = items.length;
    const dispatched = items.filter((item) => item.status_code === 'D').length;
    const completed = items.filter((item) => item.status_code === 'C').length;
    const pending = items.filter((item) => item.status_code === 'P').length;
    return [
      { label: 'Pending Dispatch', value: pending, note: 'Awaiting handoff' },
      { label: 'Dispatched', value: dispatched, note: 'Already in transit' },
      { label: 'Completed', value: completed, note: 'Receipt recorded' },
      { label: 'All Packages', value: total, note: 'Visible in queue' },
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

  viewDispatch(item: DispatchQueueItem): void {
    this.router.navigate(['/operations/dispatch', item.reliefpkg_id]);
  }

  trackByPackageId(_index: number, item: DispatchQueueItem): number {
    return item.reliefpkg_id;
  }

  statusTone(code: string | null | undefined): 'neutral' | 'soft' | 'critical' | 'warning' | 'success' | 'info' | 'outline' {
    switch (String(code ?? '').trim().toUpperCase()) {
      case 'C':
        return 'success';
      case 'D':
        return 'info';
      case 'P':
        return 'warning';
      case 'A':
        return 'soft';
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
