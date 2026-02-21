import { ChangeDetectionStrategy, Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { CurrencyPipe, DecimalPipe } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { NeedsListItem } from '../models/needs-list.model';
import { ReplenishmentService } from '../services/replenishment.service';
import { DmisNotificationService } from '../services/notification.service';
import { DmisEmptyStateComponent } from '../shared/dmis-empty-state/dmis-empty-state.component';
import { DmisSkeletonLoaderComponent } from '../shared/dmis-skeleton-loader/dmis-skeleton-loader.component';

interface ProcurementLine {
  item_id: number;
  item_name: string;
  uom: string;
  required_qty: number;
  est_unit_cost: number | null;
  est_total_cost: number | null;
}

@Component({
  selector: 'app-procurement-export',
  standalone: true,
  imports: [
    CurrencyPipe,
    DecimalPipe,
    MatButtonModule,
    MatIconModule,
    DmisEmptyStateComponent,
    DmisSkeletonLoaderComponent
  ],
  templateUrl: './procurement-export.component.html',
  styleUrl: './procurement-export.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class ProcurementExportComponent {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly replenishmentService = inject(ReplenishmentService);
  private readonly notifications = inject(DmisNotificationService);
  private readonly destroyRef = inject(DestroyRef);

  readonly loading = signal(true);
  readonly error = signal(false);
  readonly lines = signal<ProcurementLine[]>([]);
  readonly exporting = signal(false);

  private needsListId = '';

  readonly hasLines = computed(() => this.lines().length > 0);
  readonly totalEstimatedCost = computed(() =>
    this.lines().reduce((sum, l) => sum + (l.est_total_cost || 0), 0)
  );

  constructor() {
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      this.needsListId = String(params.get('id') || '').trim();
      if (!this.needsListId) {
        this.error.set(true);
        this.loading.set(false);
        return;
      }
      this.loadProcurementItems();
    });
  }

  backToTracker(): void {
    this.router.navigate(['/replenishment/needs-list', this.needsListId, 'track']);
  }

  exportAs(format: 'csv' | 'pdf'): void {
    this.exporting.set(true);
    this.replenishmentService.exportProcurementNeeds(this.needsListId, format).subscribe({
      next: (blob) => {
        this.exporting.set(false);
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `procurement_needs_${this.needsListId}.${format}`;
        a.click();
        URL.revokeObjectURL(url);
        this.notifications.showSuccess(`Procurement needs exported as ${format.toUpperCase()}.`);
      },
      error: () => {
        this.exporting.set(false);
        this.notifications.showError('Failed to export procurement needs.');
      }
    });
  }

  private loadProcurementItems(): void {
    this.loading.set(true);
    this.error.set(false);

    this.replenishmentService.getNeedsList(this.needsListId).subscribe({
      next: (response) => {
        const items = response.items || [];
        const procItems: ProcurementLine[] = items
          .filter(item => {
            const cQty = ((item.horizon || {}) as any)?.C?.recommended_qty;
            return cQty && cQty > 0;
          })
          .map(item => ({
            item_id: item.item_id,
            item_name: item.item_name || `Item ${item.item_id}`,
            uom: (item as any).uom_code || 'EA',
            required_qty: (item.horizon as any)?.C?.recommended_qty || 0,
            est_unit_cost: item.procurement?.est_unit_cost ?? null,
            est_total_cost: item.procurement?.est_total_cost ?? null,
          }));
        this.lines.set(procItems);
        this.loading.set(false);
      },
      error: () => {
        this.error.set(true);
        this.loading.set(false);
        this.notifications.showError('Failed to load procurement items.');
      }
    });
  }
}
