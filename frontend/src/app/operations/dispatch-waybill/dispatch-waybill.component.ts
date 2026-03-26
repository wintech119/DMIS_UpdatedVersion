import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, DestroyRef, computed, inject, signal, OnInit } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import { HttpErrorResponse } from '@angular/common/http';

import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatIconModule } from '@angular/material/icon';

import { DmisEmptyStateComponent } from '../../replenishment/shared/dmis-empty-state/dmis-empty-state.component';
import { DmisSkeletonLoaderComponent } from '../../replenishment/shared/dmis-skeleton-loader/dmis-skeleton-loader.component';
import { OpsMetricStripComponent } from '../shared/ops-metric-strip.component';
import { OpsStatusChipComponent } from '../shared/ops-status-chip.component';
import { OperationsService } from '../services/operations.service';
import { WaybillResponse } from '../models/operations.model';

@Component({
  selector: 'app-dispatch-waybill',
  standalone: true,
  imports: [
    DatePipe,
    MatButtonModule,
    MatCardModule,
    MatIconModule,
    OpsMetricStripComponent,
    OpsStatusChipComponent,
    DmisEmptyStateComponent,
    DmisSkeletonLoaderComponent,
  ],
  templateUrl: './dispatch-waybill.component.html',
  styleUrl: './dispatch-waybill.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DispatchWaybillComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly operationsService = inject(OperationsService);
  private readonly destroyRef = inject(DestroyRef);

  readonly loading = signal(true);
  readonly error = signal<string | null>(null);
  readonly waybill = signal<WaybillResponse | null>(null);

  readonly packageId = signal(0);
  readonly summary = computed(() => {
    const payload = this.waybill()?.waybill_payload;
    const lines = payload?.line_items ?? [];
    return [
      { label: 'Waybill No', value: this.waybill()?.waybill_no || 'Pending' },
      { label: 'Package', value: payload?.package_tracking_no || 'Pending' },
      { label: 'Destination', value: payload?.destination_warehouse_name || 'Not set' },
      { label: 'Line Items', value: String(lines.length) },
    ];
  });

  readonly totalQuantity = computed(() => {
    const wb = this.waybill();
    if (!wb?.waybill_payload?.line_items?.length) return '0';
    return wb.waybill_payload.line_items
      .reduce((sum, line) => sum + parseFloat(line.quantity || '0'), 0)
      .toFixed(2);
  });

  readonly lineItemCount = computed(() => {
    return this.waybill()?.waybill_payload?.line_items?.length ?? 0;
  });

  readonly sourceWarehouseLabel = computed(() => {
    const wb = this.waybill();
    const names = wb?.waybill_payload?.source_warehouse_names ?? [];
    return names.length > 0 ? names.join(', ') : 'Source pending';
  });

  readonly destinationLabel = computed(() => {
    return this.waybill()?.waybill_payload?.destination_warehouse_name || 'Destination pending';
  });

  readonly transportModeLabel = computed(() => {
    return this.waybill()?.waybill_payload?.transport_mode || 'Not specified';
  });

  ngOnInit(): void {
    const rawId = this.route.snapshot.paramMap.get('reliefpkgId')
      ?? this.route.snapshot.paramMap.get('reliefpkg_id')
      ?? this.route.snapshot.paramMap.get('id');
    const packageId = Number(rawId ?? 0);
    this.packageId.set(packageId);
    if (!packageId) {
      this.error.set('Invalid package identifier.');
      this.loading.set(false);
      return;
    }
    this.loadWaybill(packageId);
  }

  backToDispatch(): void {
    const packageId = this.packageId();
    if (packageId) {
      this.router.navigate(['/operations/dispatch', packageId]);
      return;
    }
    this.router.navigate(['/operations/dispatch']);
  }

  printPage(): void {
    window.print();
  }

  private loadWaybill(packageId: number): void {
    this.loading.set(true);
    this.error.set(null);
    this.operationsService.getWaybill(packageId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (waybill) => {
          this.waybill.set(waybill);
          this.loading.set(false);
        },
        error: (error: HttpErrorResponse) => {
          this.loading.set(false);
          this.error.set(this.extractError(error, 'Waybill is not available yet.'));
        },
      });
  }

  private extractError(error: HttpErrorResponse, fallback: string): string {
    const detail = typeof error.error?.detail === 'string' ? error.error.detail.trim() : '';
    const message = typeof error.error?.message === 'string' ? error.error.message.trim() : '';
    return message || detail || fallback;
  }
}
