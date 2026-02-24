import { ChangeDetectionStrategy, Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { CurrencyPipe, DatePipe } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatChipsModule } from '@angular/material/chips';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { ReplenishmentService } from '../services/replenishment.service';
import { DmisNotificationService } from '../services/notification.service';
import { DmisEmptyStateComponent } from '../shared/dmis-empty-state/dmis-empty-state.component';
import { DmisSkeletonLoaderComponent } from '../shared/dmis-skeleton-loader/dmis-skeleton-loader.component';
import {
  ProcurementOrder,
  PROCUREMENT_STATUS_LABELS,
  PROCUREMENT_STATUS_COLORS,
  ProcurementStatus
} from '../models/procurement.model';

@Component({
  selector: 'app-procurement-list',
  standalone: true,
  imports: [
    CurrencyPipe,
    DatePipe,
    MatButtonModule,
    MatIconModule,
    MatChipsModule,
    DmisEmptyStateComponent,
    DmisSkeletonLoaderComponent
  ],
  templateUrl: './procurement-list.component.html',
  styleUrl: './procurement-list.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class ProcurementListComponent {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly replenishmentService = inject(ReplenishmentService);
  private readonly notifications = inject(DmisNotificationService);
  private readonly destroyRef = inject(DestroyRef);

  readonly loading = signal(true);
  readonly error = signal(false);
  readonly creating = signal(false);
  readonly procurements = signal<ProcurementOrder[]>([]);

  private needsListId = '';

  readonly hasProcurements = computed(() => this.procurements().length > 0);

  readonly statusLabels = PROCUREMENT_STATUS_LABELS;
  readonly statusColors = PROCUREMENT_STATUS_COLORS;

  constructor() {
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      this.needsListId = String(params.get('id') || '').trim();
      if (!this.needsListId) {
        this.error.set(true);
        this.loading.set(false);
        return;
      }
      this.loadProcurements();
    });
  }

  backToTracker(): void {
    this.router.navigate(['/replenishment/needs-list', this.needsListId, 'track']);
  }

  createProcurementOrder(): void {
    this.creating.set(true);
    this.replenishmentService.createProcurement({ needs_list_id: this.needsListId }).subscribe({
      next: (order) => {
        this.creating.set(false);
        this.notifications.showSuccess('Procurement order created successfully.');
        this.router.navigate(['/replenishment/procurement', order.procurement_id]);
      },
      error: () => {
        this.creating.set(false);
        this.notifications.showError('Failed to create procurement order.');
      }
    });
  }

  navigateToDetail(procurementId: number): void {
    this.router.navigate(['/replenishment/procurement', procurementId]);
  }

  getStatusLabel(status: ProcurementStatus): string {
    return this.statusLabels[status] || status;
  }

  getStatusColor(status: ProcurementStatus): string {
    return this.statusColors[status] || '#9e9e9e';
  }

  private loadProcurements(): void {
    this.loading.set(true);
    this.error.set(false);

    this.replenishmentService.listProcurements({ needs_list_id: this.needsListId }).subscribe({
      next: (response) => {
        this.procurements.set(response.procurements || []);
        this.loading.set(false);
      },
      error: () => {
        this.error.set(true);
        this.loading.set(false);
        this.notifications.showError('Failed to load procurement orders.');
      }
    });
  }
}
