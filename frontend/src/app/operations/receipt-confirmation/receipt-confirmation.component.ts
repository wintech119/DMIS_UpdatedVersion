import { DatePipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, DestroyRef, OnInit, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';

import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';

import { DmisEmptyStateComponent } from '../../replenishment/shared/dmis-empty-state/dmis-empty-state.component';
import { DmisSkeletonLoaderComponent } from '../../replenishment/shared/dmis-skeleton-loader/dmis-skeleton-loader.component';
import { DispatchDetailResponse, ReceiptConfirmationPayload } from '../models/operations.model';
import { OperationsService } from '../services/operations.service';
import { OpsMetricStripComponent, OpsMetricStripItem } from '../shared/ops-metric-strip.component';
import { OpsStatusChipComponent } from '../shared/ops-status-chip.component';

@Component({
  selector: 'app-receipt-confirmation',
  standalone: true,
  imports: [
    DatePipe,
    FormsModule,
    MatButtonModule,
    MatCardModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    OpsMetricStripComponent,
    OpsStatusChipComponent,
    DmisEmptyStateComponent,
    DmisSkeletonLoaderComponent,
  ],
  templateUrl: './receipt-confirmation.component.html',
  styleUrl: './receipt-confirmation.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ReceiptConfirmationComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly operationsService = inject(OperationsService);
  private readonly destroyRef = inject(DestroyRef);

  readonly loading = signal(true);
  readonly error = signal<string | null>(null);
  readonly detail = signal<DispatchDetailResponse | null>(null);
  readonly packageId = signal(0);

  readonly receivedBy = signal('');
  readonly receiptNotes = signal('');
  readonly beneficiaryDeliveryRef = signal('');
  readonly submitting = signal(false);
  readonly submitted = signal(false);
  readonly submitError = signal<string | null>(null);

  readonly canSubmit = computed(() =>
    this.receivedBy().trim().length > 0 && !this.submitting() && !this.submitted()
  );

  readonly isAlreadyConfirmed = computed(() => !!this.detail()?.received_dtime);

  readonly isReady = computed(() => {
    const detail = this.detail();
    return !!detail?.dispatch_dtime || detail?.status_code === 'D' || !!detail?.waybill;
  });

  readonly summary = computed<readonly OpsMetricStripItem[]>(() => [
    {
      label: 'Package',
      value: this.detail()?.tracking_no || 'Pending',
      hint: 'Operational handoff record',
    },
    {
      label: 'Waybill',
      value: this.detail()?.waybill?.waybill_no || 'Pending',
      hint: 'Dispatch artifact reference',
    },
    {
      label: 'Dispatch',
      value: this.detail()?.dispatch_dtime ? 'Recorded' : 'Pending',
      hint: this.detail()?.dispatch_dtime ? 'Dispatch time captured' : 'No dispatch timestamp yet',
    },
    {
      label: 'Receipt',
      value: this.submitted() || this.isAlreadyConfirmed() ? 'Confirmed' : this.isReady() ? 'Ready for capture' : 'Pending',
      hint: this.submitted() || this.isAlreadyConfirmed() ? 'Receipt has been recorded' : 'Awaiting confirmation',
    },
  ]);

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
    this.loadDetail(packageId);
  }

  submitReceipt(): void {
    if (!this.canSubmit()) {
      return;
    }
    const pkgId = this.detail()?.reliefpkg_id;
    if (!pkgId) {
      return;
    }

    this.submitting.set(true);
    this.submitError.set(null);

    const payload: ReceiptConfirmationPayload = {
      received_by_name: this.receivedBy().trim(),
      receipt_notes: this.receiptNotes().trim() || undefined,
      beneficiary_delivery_ref: this.beneficiaryDeliveryRef().trim() || undefined,
    };

    this.operationsService.confirmReceipt(pkgId, payload)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.submitted.set(true);
          this.submitting.set(false);
        },
        error: (err) => {
          this.submitError.set(err?.error?.detail || err?.message || 'Receipt confirmation failed.');
          this.submitting.set(false);
        },
      });
  }

  backToDispatch(): void {
    const packageId = this.packageId();
    if (packageId) {
      this.router.navigate(['/operations/dispatch', packageId]);
      return;
    }
    this.router.navigate(['/operations/dispatch']);
  }

  private loadDetail(packageId: number): void {
    this.loading.set(true);
    this.error.set(null);
    this.operationsService.getDispatchDetail(packageId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (detail) => {
          this.detail.set(detail);
          this.loading.set(false);
        },
        error: (error: HttpErrorResponse) => {
          this.loading.set(false);
          this.error.set(this.extractError(error, 'Receipt confirmation route is waiting on its backend contract.'));
        },
      });
  }

  private extractError(error: HttpErrorResponse, fallback: string): string {
    const detail = typeof error.error?.detail === 'string' ? error.error.detail.trim() : '';
    const message = typeof error.error?.message === 'string' ? error.error.message.trim() : '';
    return message || detail || fallback;
  }
}
