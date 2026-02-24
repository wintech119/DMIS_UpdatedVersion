import {
  Component, ChangeDetectionStrategy, inject, signal, computed, OnInit, DestroyRef
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import { HttpErrorResponse } from '@angular/common/http';
import { CurrencyPipe, DatePipe, DecimalPipe } from '@angular/common';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';

import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatChipsModule } from '@angular/material/chips';
import { MatDialog, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatDatepickerModule } from '@angular/material/datepicker';
import { MatNativeDateModule } from '@angular/material/core';
import { MatTableModule } from '@angular/material/table';
import { MatTooltipModule } from '@angular/material/tooltip';

import { ReplenishmentService } from '../services/replenishment.service';
import { DmisNotificationService } from '../services/notification.service';
import { AuthRbacService } from '../services/auth-rbac.service';
import { DmisSkeletonLoaderComponent } from '../shared/dmis-skeleton-loader/dmis-skeleton-loader.component';
import { DmisConfirmDialogComponent, ConfirmDialogData } from '../shared/dmis-confirm-dialog/dmis-confirm-dialog.component';
import { DmisReasonDialogComponent, DmisReasonDialogData, DmisReasonDialogResult } from '../shared/dmis-reason-dialog/dmis-reason-dialog.component';
import {
  ProcurementOrder,
  ProcurementStatus,
  ProcurementItemStatus,
  PROCUREMENT_STATUS_LABELS,
  PROCUREMENT_STATUS_COLORS,
  PROCUREMENT_METHOD_LABELS
} from '../models/procurement.model';

// ── Lifecycle steps for the status stepper ──

const LIFECYCLE_STEPS: ProcurementStatus[] = [
  'DRAFT',
  'PENDING_APPROVAL',
  'APPROVED',
  'ORDERED',
  'SHIPPED',
  'RECEIVED'
];

const TERMINAL_STATUSES = new Set<ProcurementStatus>(['REJECTED', 'CANCELLED']);

const ITEM_STATUS_LABELS: Record<ProcurementItemStatus, string> = {
  PENDING: 'Pending',
  PARTIAL: 'Partial',
  RECEIVED: 'Received',
  CANCELLED: 'Cancelled'
};

const PERM_PROCUREMENT_EDIT = 'replenishment.procurement.edit';
const PERM_PROCUREMENT_SUBMIT = 'replenishment.procurement.submit';
const PERM_PROCUREMENT_APPROVE = 'replenishment.procurement.approve';
const PERM_PROCUREMENT_REJECT = 'replenishment.procurement.reject';
const PERM_PROCUREMENT_ORDER = 'replenishment.procurement.order';
const PERM_PROCUREMENT_RECEIVE = 'replenishment.procurement.receive';
const PERM_PROCUREMENT_CANCEL = 'replenishment.procurement.cancel';

const LOGISTICS_ROLE_LABEL = 'Logistics';
const EXECUTIVE_ROLE_LABEL = 'Executive';

// ════════════════════════════════════════════════════════════════════
// Inline Dialog: PO Number Input
// ════════════════════════════════════════════════════════════════════

@Component({
  selector: 'dmis-po-number-dialog',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatDialogModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule
  ],
  template: `
    <h2 mat-dialog-title>Enter Purchase Order Number</h2>
    <form [formGroup]="form" (ngSubmit)="submit()">
      <mat-dialog-content>
        <mat-form-field appearance="outline" class="dialog-field">
          <mat-label>PO Number</mat-label>
          <input matInput formControlName="poNumber" placeholder="e.g. PO-2026-0042" />
          @if (form.controls.poNumber.invalid && form.controls.poNumber.touched) {
            <mat-error>PO number is required.</mat-error>
          }
        </mat-form-field>
      </mat-dialog-content>
      <mat-dialog-actions align="end">
        <button mat-button type="button" mat-dialog-close>Cancel</button>
        <button mat-flat-button color="primary" type="submit">Confirm</button>
      </mat-dialog-actions>
    </form>
  `,
  styles: [`
    .dialog-field { width: 100%; margin-top: 8px; }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class PoNumberDialogComponent {
  private readonly fb = inject(FormBuilder);
  private readonly dialogRef = inject(MatDialogRef<PoNumberDialogComponent, string>);

  readonly form = this.fb.nonNullable.group({
    poNumber: ['', [Validators.required]]
  });

  submit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    this.dialogRef.close(this.form.controls.poNumber.value.trim());
  }
}

// ════════════════════════════════════════════════════════════════════
// Inline Dialog: Shipped Dates Input
// ════════════════════════════════════════════════════════════════════

export interface ShippedDatesResult {
  shipped_at: string;
  expected_arrival?: string;
}

@Component({
  selector: 'dmis-shipped-dates-dialog',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatDialogModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    MatDatepickerModule,
    MatNativeDateModule
  ],
  template: `
    <h2 mat-dialog-title>Enter Shipping Details</h2>
    <form [formGroup]="form" (ngSubmit)="submit()">
      <mat-dialog-content>
        <mat-form-field appearance="outline" class="dialog-field">
          <mat-label>Shipped Date</mat-label>
          <input matInput [matDatepicker]="shippedPicker" formControlName="shipped_at" />
          <mat-datepicker-toggle matIconSuffix [for]="shippedPicker"></mat-datepicker-toggle>
          <mat-datepicker #shippedPicker></mat-datepicker>
          @if (form.controls.shipped_at.invalid && form.controls.shipped_at.touched) {
            <mat-error>Shipped date is required.</mat-error>
          }
        </mat-form-field>

        <mat-form-field appearance="outline" class="dialog-field">
          <mat-label>Expected Arrival (optional)</mat-label>
          <input matInput [matDatepicker]="arrivalPicker" formControlName="expected_arrival" />
          <mat-datepicker-toggle matIconSuffix [for]="arrivalPicker"></mat-datepicker-toggle>
          <mat-datepicker #arrivalPicker></mat-datepicker>
        </mat-form-field>
      </mat-dialog-content>
      <mat-dialog-actions align="end">
        <button mat-button type="button" mat-dialog-close>Cancel</button>
        <button mat-flat-button color="primary" type="submit">Confirm</button>
      </mat-dialog-actions>
    </form>
  `,
  styles: [`
    .dialog-field { width: 100%; margin-top: 8px; }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class ShippedDatesDialogComponent {
  private readonly fb = inject(FormBuilder);
  private readonly dialogRef = inject(MatDialogRef<ShippedDatesDialogComponent, ShippedDatesResult>);

  readonly form = this.fb.nonNullable.group({
    shipped_at: ['', [Validators.required]],
    expected_arrival: ['']
  });

  submit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    const shippedAt = this.form.controls.shipped_at.value;
    const expectedArrival = this.form.controls.expected_arrival.value;
    this.dialogRef.close({
      shipped_at: this.toBackendDateTime(shippedAt),
      expected_arrival: expectedArrival ? this.toBackendDateTime(expectedArrival) : undefined
    });
  }

  private toBackendDateTime(value: string | Date): string {
    if (value instanceof Date) {
      const year = value.getFullYear();
      const month = String(value.getMonth() + 1).padStart(2, '0');
      const day = String(value.getDate()).padStart(2, '0');
      return `${year}-${month}-${day}T00:00:00`;
    }
    const normalized = String(value).trim();
    if (!normalized) {
      return '';
    }
    return normalized.includes('T') ? normalized : `${normalized}T00:00:00`;
  }
}

// ════════════════════════════════════════════════════════════════════
// Main Component: Procurement Detail
// ════════════════════════════════════════════════════════════════════

@Component({
  selector: 'app-procurement-detail',
  standalone: true,
  imports: [
    CurrencyPipe,
    DatePipe,
    DecimalPipe,
    MatButtonModule,
    MatCardModule,
    MatChipsModule,
    MatDialogModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatTableModule,
    MatTooltipModule,
    DmisSkeletonLoaderComponent
  ],
  templateUrl: './procurement-detail.component.html',
  styleUrl: './procurement-detail.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class ProcurementDetailComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly dialog = inject(MatDialog);
  private readonly destroyRef = inject(DestroyRef);
  private readonly replenishmentService = inject(ReplenishmentService);
  private readonly notifications = inject(DmisNotificationService);
  private readonly authRbac = inject(AuthRbacService);

  // ── State signals ──

  readonly loading = signal(true);
  readonly procurement = signal<ProcurementOrder | null>(null);
  readonly error = signal(false);
  readonly actionLoading = signal<string | null>(null);

  // ── Computed ──

  readonly status = computed(() => this.procurement()?.status_code ?? 'DRAFT');
  readonly statusLabel = computed(() => PROCUREMENT_STATUS_LABELS[this.status()]);
  readonly statusColor = computed(() => PROCUREMENT_STATUS_COLORS[this.status()]);
  readonly isTerminal = computed(() => TERMINAL_STATUSES.has(this.status()));

  readonly items = computed(() => this.procurement()?.items ?? []);
  readonly permissionsLoaded = computed(() => this.authRbac.loaded());

  readonly canEdit = computed(() =>
    this.status() === 'DRAFT' && this.authRbac.hasPermission(PERM_PROCUREMENT_EDIT)
  );

  readonly canCancel = computed(() =>
    this.status() === 'DRAFT' && this.authRbac.hasPermission(PERM_PROCUREMENT_CANCEL)
  );

  readonly canSubmit = computed(() =>
    this.status() === 'DRAFT' && this.authRbac.hasPermission(PERM_PROCUREMENT_SUBMIT)
  );

  readonly canApprove = computed(() =>
    this.status() === 'PENDING_APPROVAL' && this.authRbac.hasPermission(PERM_PROCUREMENT_APPROVE)
  );

  readonly canReject = computed(() =>
    this.status() === 'PENDING_APPROVAL' && this.authRbac.hasPermission(PERM_PROCUREMENT_REJECT)
  );

  readonly canOrder = computed(() =>
    this.status() === 'APPROVED' && this.authRbac.hasPermission(PERM_PROCUREMENT_ORDER)
  );

  readonly canShip = computed(() =>
    this.status() === 'ORDERED' && this.authRbac.hasPermission(PERM_PROCUREMENT_ORDER)
  );

  readonly canReceive = computed(() =>
    (this.status() === 'SHIPPED' || this.status() === 'PARTIAL_RECEIVED')
    && this.authRbac.hasPermission(PERM_PROCUREMENT_RECEIVE)
  );

  readonly hasVisibleActions = computed(() =>
    this.canEdit()
    || this.canCancel()
    || this.canSubmit()
    || this.canApprove()
    || this.canReject()
    || this.canOrder()
    || this.canShip()
    || this.canReceive()
  );

  readonly actionRoleHint = computed(() => {
    if (!this.permissionsLoaded() || this.hasVisibleActions()) {
      return null;
    }
    const allowedRoles = this.getAllowedRolesForStage();
    if (!allowedRoles.length) {
      return null;
    }
    return `No actions available for your account at this stage. Allowed role(s): ${allowedRoles.join(', ')}.`;
  });

  readonly displayedColumns = [
    'item_name', 'uom', 'ordered_qty', 'unit_price', 'line_total', 'received_qty', 'status'
  ];

  readonly lifecycleSteps = LIFECYCLE_STEPS;

  readonly currentStepIndex = computed(() => {
    const s = this.status();
    // PARTIAL_RECEIVED maps to the SHIPPED step (between SHIPPED and RECEIVED)
    if (s === 'PARTIAL_RECEIVED') return LIFECYCLE_STEPS.indexOf('SHIPPED');
    const idx = LIFECYCLE_STEPS.indexOf(s);
    return idx >= 0 ? idx : -1;
  });

  readonly methodLabel = computed(() => {
    const proc = this.procurement();
    if (!proc) return '';
    return PROCUREMENT_METHOD_LABELS[proc.procurement_method] ?? proc.procurement_method;
  });

  readonly totalValue = computed(() => {
    const proc = this.procurement();
    if (!proc) return 0;
    return parseFloat(proc.total_value) || 0;
  });

  private procId = 0;

  // ── Lifecycle ──

  ngOnInit(): void {
    this.authRbac.load();
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(params => {
      this.procId = Number(params.get('procId') ?? '0');
      if (this.procId) {
        this.loadProcurement();
      }
    });
  }

  loadProcurement(): void {
    this.loading.set(true);
    this.error.set(false);
    this.replenishmentService.getProcurement(this.procId).subscribe({
      next: (data) => {
        this.procurement.set(data);
        this.loading.set(false);
      },
      error: () => {
        this.loading.set(false);
        this.error.set(true);
        this.notifications.showError('Failed to load procurement order.');
      }
    });
  }

  // ── Navigation ──

  goBack(): void {
    const needsListId = this.procurement()?.needs_list_id;
    if (needsListId) {
      this.router.navigate(['/replenishment/needs-list', needsListId, 'procurement']);
      return;
    }
    this.router.navigate(['/replenishment/dashboard']);
  }

  navigateToEdit(): void {
    if (!this.canEdit()) return;
    this.router.navigate(['/replenishment/procurement', this.procId, 'edit']);
  }

  navigateToReceive(): void {
    if (!this.canReceive()) return;
    this.router.navigate(['/replenishment/procurement', this.procId, 'receive']);
  }

  // ── Actions ──

  submitForApproval(): void {
    if (!this.canSubmit() || this.actionLoading()) return;
    const data: ConfirmDialogData = {
      title: 'Submit for Approval',
      message: 'Are you sure you want to submit this procurement order for approval?',
      confirmLabel: 'Submit'
    };
    this.dialog.open(DmisConfirmDialogComponent, {
      width: '440px',
      data,
      autoFocus: false
    }).afterClosed()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((confirmed?: boolean) => {
        if (!confirmed) return;
        this.actionLoading.set('submit');
        this.replenishmentService.submitProcurement(this.procId).subscribe({
          next: (updated) => {
            this.procurement.set(updated);
            this.actionLoading.set(null);
            this.notifications.showSuccess('Procurement submitted for approval.');
          },
          error: (err: HttpErrorResponse) => {
            this.actionLoading.set(null);
            this.notifications.showError(this.extractError(err, 'Failed to submit procurement.'));
          }
        });
      });
  }

  cancelProcurement(): void {
    if (!this.canCancel() || this.actionLoading()) return;
    const data: DmisReasonDialogData = {
      title: 'Cancel Procurement',
      actionLabel: 'Cancel Procurement',
      actionColor: 'warn'
    };
    this.dialog.open(DmisReasonDialogComponent, {
      width: '520px',
      data,
      autoFocus: false
    }).afterClosed()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((result?: DmisReasonDialogResult) => {
        if (!result) return;
        this.actionLoading.set('cancel');
        this.replenishmentService.cancelProcurement(this.procId, result.reason).subscribe({
          next: (updated) => {
            this.procurement.set(updated);
            this.actionLoading.set(null);
            this.notifications.showWarning('Procurement cancelled.');
          },
          error: (err: HttpErrorResponse) => {
            this.actionLoading.set(null);
            this.notifications.showError(this.extractError(err, 'Failed to cancel procurement.'));
          }
        });
      });
  }

  approveProcurement(): void {
    if (!this.canApprove() || this.actionLoading()) return;
    const data: ConfirmDialogData = {
      title: 'Approve Procurement',
      message: 'Are you sure you want to approve this procurement order?',
      confirmLabel: 'Approve'
    };
    this.dialog.open(DmisConfirmDialogComponent, {
      width: '440px',
      data,
      autoFocus: false
    }).afterClosed()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((confirmed?: boolean) => {
        if (!confirmed) return;
        this.actionLoading.set('approve');
        this.replenishmentService.approveProcurement(this.procId).subscribe({
          next: (updated) => {
            this.procurement.set(updated);
            this.actionLoading.set(null);
            this.notifications.showSuccess('Procurement approved.');
          },
          error: (err: HttpErrorResponse) => {
            this.actionLoading.set(null);
            this.notifications.showError(this.extractError(err, 'Approval failed.'));
          }
        });
      });
  }

  rejectProcurement(): void {
    if (!this.canReject() || this.actionLoading()) return;
    const data: DmisReasonDialogData = {
      title: 'Reject Procurement',
      actionLabel: 'Reject',
      actionColor: 'warn'
    };
    this.dialog.open(DmisReasonDialogComponent, {
      width: '520px',
      data,
      autoFocus: false
    }).afterClosed()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((result?: DmisReasonDialogResult) => {
        if (!result) return;
        this.actionLoading.set('reject');
        this.replenishmentService.rejectProcurement(this.procId, result.reason).subscribe({
          next: (updated) => {
            this.procurement.set(updated);
            this.actionLoading.set(null);
            this.notifications.showWarning('Procurement rejected.');
          },
          error: (err: HttpErrorResponse) => {
            this.actionLoading.set(null);
            this.notifications.showError(this.extractError(err, 'Rejection failed.'));
          }
        });
      });
  }

  markAsOrdered(): void {
    if (!this.canOrder() || this.actionLoading()) return;
    this.dialog.open(PoNumberDialogComponent, {
      width: '440px',
      autoFocus: true
    }).afterClosed()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((poNumber?: string) => {
        if (!poNumber) return;
        this.actionLoading.set('order');
        this.replenishmentService.markProcurementOrdered(this.procId, poNumber).subscribe({
          next: (updated) => {
            this.procurement.set(updated);
            this.actionLoading.set(null);
            this.notifications.showSuccess(`Procurement marked as ordered (PO: ${poNumber}).`);
          },
          error: (err: HttpErrorResponse) => {
            this.actionLoading.set(null);
            this.notifications.showError(this.extractError(err, 'Failed to mark as ordered.'));
          }
        });
      });
  }

  markAsShipped(): void {
    if (!this.canShip() || this.actionLoading()) return;
    this.dialog.open(ShippedDatesDialogComponent, {
      width: '440px',
      autoFocus: true
    }).afterClosed()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((result?: ShippedDatesResult) => {
        if (!result) return;
        this.actionLoading.set('ship');
        this.replenishmentService.markProcurementShipped(this.procId, {
          shipped_at: result.shipped_at,
          expected_arrival: result.expected_arrival
        }).subscribe({
          next: (updated) => {
            this.procurement.set(updated);
            this.actionLoading.set(null);
            this.notifications.showSuccess('Procurement marked as shipped.');
          },
          error: (err: HttpErrorResponse) => {
            this.actionLoading.set(null);
            this.notifications.showError(this.extractError(err, 'Failed to mark as shipped.'));
          }
        });
      });
  }

  // ── Display helpers ──

  stepLabel(step: ProcurementStatus): string {
    return PROCUREMENT_STATUS_LABELS[step];
  }

  stepState(index: number): 'completed' | 'active' | 'future' {
    const current = this.currentStepIndex();
    if (index < current) return 'completed';
    if (index === current) return 'active';
    return 'future';
  }

  itemStatusLabel(status: ProcurementItemStatus): string {
    return ITEM_STATUS_LABELS[status] ?? status;
  }

  itemStatusColor(status: ProcurementItemStatus): string {
    switch (status) {
      case 'RECEIVED': return '#4caf50';
      case 'PARTIAL': return '#ff9800';
      case 'CANCELLED': return '#9e9e9e';
      default: return '#2196f3';
    }
  }

  // ── Private helpers ──

  getAllowedRolesForStage(status: ProcurementStatus = this.status()): string[] {
    switch (status) {
      case 'DRAFT':
      case 'APPROVED':
      case 'ORDERED':
      case 'SHIPPED':
      case 'PARTIAL_RECEIVED':
        return [LOGISTICS_ROLE_LABEL];
      case 'PENDING_APPROVAL': {
        const approverRole = String(this.procurement()?.approval?.approver_role ?? '').trim();
        return approverRole ? [approverRole] : [EXECUTIVE_ROLE_LABEL];
      }
      default:
        return [];
    }
  }

  private extractError(error: HttpErrorResponse, fallback: string): string {
    if (error.status === 403) return 'You do not have permission to perform this action.';
    if (error.error?.errors) {
      const errors = error.error.errors;
      if (Array.isArray(errors)) return errors[0] ?? fallback;
      const entries = Object.entries(errors);
      if (entries.length) {
        const [field, msg] = entries[0];
        return `${field}: ${Array.isArray(msg) ? msg[0] : msg}`;
      }
    }
    const apiMessage =
      typeof error.error?.message === 'string' ? error.error.message.trim() : '';
    const statusText = typeof error.statusText === 'string' ? error.statusText.trim() : '';
    return apiMessage || statusText || fallback || 'An unexpected error occurred';
  }
}
