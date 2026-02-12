import { Component, ChangeDetectionStrategy, inject, signal, OnInit } from '@angular/core';
import { Router } from '@angular/router';
import { DatePipe, SlicePipe } from '@angular/common';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatChipsModule } from '@angular/material/chips';
import { MatIconModule } from '@angular/material/icon';
import { MatTableModule } from '@angular/material/table';
import { MatTooltipModule } from '@angular/material/tooltip';

import { NeedsListResponse } from '../models/needs-list.model';
import { ReplenishmentService } from '../services/replenishment.service';
import { DmisNotificationService } from '../services/notification.service';
import { DmisSkeletonLoaderComponent } from '../shared/dmis-skeleton-loader/dmis-skeleton-loader.component';
import { DmisEmptyStateComponent } from '../shared/dmis-empty-state/dmis-empty-state.component';
import { formatStatusLabel } from './status-label.util';

@Component({
  selector: 'app-needs-list-review-queue',
  imports: [
    DatePipe,
    SlicePipe,
    MatButtonModule,
    MatCardModule,
    MatChipsModule,
    MatIconModule,
    MatTableModule,
    MatTooltipModule,
    DmisSkeletonLoaderComponent,
    DmisEmptyStateComponent
  ],
  templateUrl: './needs-list-review-queue.component.html',
  styleUrl: './needs-list-review-queue.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class NeedsListReviewQueueComponent implements OnInit {
  private readonly router = inject(Router);
  private readonly replenishmentService = inject(ReplenishmentService);
  private readonly notifications = inject(DmisNotificationService);

  readonly loading = signal(true);
  readonly needsLists = signal<NeedsListResponse[]>([]);
  readonly error = signal(false);

  readonly displayedColumns = [
    'needs_list_id',
    'event_id',
    'phase',
    'warehouse',
    'submitted_by',
    'submitted_at',
    'items_count',
    'status'
  ];

  ngOnInit(): void {
    this.loadQueue();
  }

  loadQueue(): void {
    this.loading.set(true);
    this.error.set(false);
    this.replenishmentService.listNeedsLists(['SUBMITTED', 'UNDER_REVIEW']).subscribe({
      next: (data) => {
        this.needsLists.set(data.needs_lists);
        this.loading.set(false);
      },
      error: () => {
        this.loading.set(false);
        this.error.set(true);
        this.notifications.showError('Failed to load review queue.');
      }
    });
  }

  openReview(row: NeedsListResponse): void {
    if (row.needs_list_id) {
      this.router.navigate(['/replenishment/needs-list-review', row.needs_list_id]);
    }
  }

  backToDashboard(): void {
    this.router.navigate(['/replenishment/dashboard']);
  }

  warehouseLabel(row: NeedsListResponse): string {
    if (row.warehouses?.length) {
      return row.warehouses.map(w => w.warehouse_name).join(', ');
    }
    if (row.warehouse_ids?.length) {
      return row.warehouse_ids.join(', ');
    }
    if (row.warehouse_id) {
      return `Warehouse ${row.warehouse_id}`;
    }
    return 'N/A';
  }

  statusIcon(status: string | undefined): string {
    switch (status) {
      case 'SUBMITTED': return 'send';
      case 'UNDER_REVIEW': return 'rate_review';
      default: return 'info';
    }
  }

  statusLabel(status: string | undefined): string {
    return formatStatusLabel(status);
  }
}
