import {
  Component,
  ChangeDetectionStrategy,
  computed,
  inject,
  signal,
  OnInit,
} from '@angular/core';
import { Router } from '@angular/router';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatTableModule } from '@angular/material/table';

import { DmisEmptyStateComponent } from '../../replenishment/shared/dmis-empty-state/dmis-empty-state.component';
import { DmisSkeletonLoaderComponent } from '../../replenishment/shared/dmis-skeleton-loader/dmis-skeleton-loader.component';
import { OpsMetricStripComponent, OpsMetricStripItem } from '../shared/ops-metric-strip.component';
import { OpsStatusChipComponent } from '../shared/ops-status-chip.component';
import { OperationsService } from '../services/operations.service';
import { PackageQueueItem } from '../models/operations.model';
import { formatUrgency } from '../models/operations-status.util';

@Component({
  selector: 'app-package-fulfillment-queue',
  standalone: true,
  imports: [
    MatCardModule,
    MatButtonModule,
    MatIconModule,
    MatTableModule,
    OpsMetricStripComponent,
    OpsStatusChipComponent,
    DmisEmptyStateComponent,
    DmisSkeletonLoaderComponent,
  ],
  templateUrl: './package-fulfillment-queue.component.html',
  styleUrl: './package-fulfillment-queue.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PackageFulfillmentQueueComponent implements OnInit {
  private readonly operationsService = inject(OperationsService);
  private readonly router = inject(Router);

  readonly loading = signal(true);
  readonly items = signal<PackageQueueItem[]>([]);

  readonly queueStats = computed(() => {
    const items = this.items();
    const total = items.length;
    const awaiting = items.filter((item) => !item.current_package || item.current_package.status_code === 'A').length;
    const pending = items.filter((item) => item.current_package?.status_code === 'P').length;
    const ready = items.filter((item) => item.current_package?.status_code === 'D').length;
    return [
      { label: 'Awaiting Fulfillment', value: awaiting, note: 'New work in queue' },
      { label: 'Preparing', value: pending, note: 'Reservation in progress' },
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

  readonly displayedColumns = [
    'tracking_no',
    'agency',
    'urgency',
    'request_status',
    'package',
    'items',
    'actions',
  ];

  readonly formatUrgency = formatUrgency;

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

  urgencyTone(code: string | null | undefined): 'neutral' | 'soft' | 'critical' | 'warning' | 'success' | 'info' | 'outline' {
    switch (String(code ?? '').trim().toUpperCase()) {
      case 'C':
        return 'critical';
      case 'H':
        return 'warning';
      case 'M':
        return 'info';
      case 'L':
        return 'soft';
      default:
        return 'neutral';
    }
  }

  statusTone(code: number | string | null | undefined): 'neutral' | 'soft' | 'critical' | 'warning' | 'success' | 'info' | 'outline' {
    switch (String(code ?? '').trim().toUpperCase()) {
      case '7':
      case 'F':
      case 'P':
      case 'D':
        return 'success';
      case '5':
      case '1':
        return 'warning';
      case '8':
      case '4':
      case '2':
        return 'critical';
      default:
        return 'soft';
    }
  }

  packageTone(code: string | null | undefined): 'neutral' | 'soft' | 'critical' | 'warning' | 'success' | 'info' | 'outline' {
    switch (String(code ?? '').trim().toUpperCase()) {
      case 'P':
        return 'success';
      case 'D':
        return 'info';
      case 'A':
        return 'soft';
      default:
        return 'neutral';
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
