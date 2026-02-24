import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import {
  FormArray,
  FormControl,
  FormGroup,
  ReactiveFormsModule,
  Validators,
} from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { filter, map, startWith } from 'rxjs/operators';

import { ReplenishmentService } from '../services/replenishment.service';
import { DmisNotificationService } from '../services/notification.service';
import { DmisSkeletonLoaderComponent } from '../shared/dmis-skeleton-loader/dmis-skeleton-loader.component';
import {
  DmisConfirmDialogComponent,
  ConfirmDialogData,
} from '../shared/dmis-confirm-dialog/dmis-confirm-dialog.component';
import {
  ProcurementOrder,
  ProcurementOrderItem,
  PROCUREMENT_STATUS_LABELS,
  PROCUREMENT_STATUS_COLORS,
  ProcurementStatus,
} from '../models/procurement.model';

interface LineItemFormGroup {
  procurement_item_id: FormControl<number>;
  qty_to_receive: FormControl<number>;
}

interface LineItemFormValue {
  procurement_item_id: number;
  qty_to_receive: number;
}

@Component({
  selector: 'app-procurement-intake',
  standalone: true,
  imports: [
    DecimalPipe,
    ReactiveFormsModule,
    MatButtonModule,
    MatIconModule,
    MatFormFieldModule,
    MatInputModule,
    MatDialogModule,
    DmisSkeletonLoaderComponent,
  ],
  templateUrl: './procurement-intake.component.html',
  styleUrl: './procurement-intake.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ProcurementIntakeComponent {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly dialog = inject(MatDialog);
  private readonly replenishmentService = inject(ReplenishmentService);
  private readonly notifications = inject(DmisNotificationService);
  private readonly destroyRef = inject(DestroyRef);

  readonly loading = signal(true);
  readonly error = signal<string | null>(null);
  readonly submitting = signal(false);
  readonly procurement = signal<ProcurementOrder | null>(null);

  readonly statusLabels = PROCUREMENT_STATUS_LABELS;
  readonly statusColors = PROCUREMENT_STATUS_COLORS;

  readonly lineItemsForm = new FormArray<FormGroup<LineItemFormGroup>>([]);
  private readonly lineItemsFormValues = toSignal<LineItemFormValue[]>(
    this.lineItemsForm.valueChanges.pipe(
      startWith(this.lineItemsForm.getRawValue()),
      map((values) =>
        values.map((value) => ({
          procurement_item_id: Number(value?.procurement_item_id ?? 0),
          qty_to_receive: Number(value?.qty_to_receive ?? 0),
        }))
      )
    ),
    { initialValue: this.lineItemsForm.getRawValue() }
  );

  private procId = 0;

  /** Items with their computed remaining quantities */
  readonly lineItems = computed(() => {
    const proc = this.procurement();
    if (!proc) return [];
    return proc.items.map((item) => ({
      ...item,
      remaining_qty: item.ordered_qty - item.received_qty,
    }));
  });

  /** Count of line items where qty_to_receive > 0 */
  readonly receivingCount = computed(() => {
    const items = this.lineItems();
    const formValues = this.lineItemsFormValues();
    let count = 0;
    for (let i = 0; i < items.length; i++) {
      const qtyToReceive = formValues[i]?.qty_to_receive ?? 0;
      if (qtyToReceive > 0) {
        count++;
      }
    }
    return count;
  });

  /** Whether the form has at least one item with qty > 0 and no validation errors */
  readonly canSubmit = computed(() => {
    if (this.submitting()) return false;
    const items = this.lineItems();
    const formValues = this.lineItemsFormValues();
    if (items.length === 0) return false;
    let hasQty = false;
    for (let i = 0; i < items.length; i++) {
      const group = this.lineItemsForm.at(i);
      if (!group || group.invalid) return false;
      const qtyToReceive = formValues[i]?.qty_to_receive ?? 0;
      if (qtyToReceive > 0) {
        hasQty = true;
      }
    }
    return hasQty;
  });

  constructor() {
    this.route.paramMap
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((params) => {
        const id = Number(params.get('procId'));
        if (!id || isNaN(id)) {
          this.error.set('Invalid procurement ID.');
          this.loading.set(false);
          return;
        }
        this.procId = id;
        this.loadProcurement();
      });
  }

  getStatusLabel(status: ProcurementStatus): string {
    return this.statusLabels[status] || status;
  }

  getStatusColor(status: ProcurementStatus): string {
    return this.statusColors[status] || '#9e9e9e';
  }

  navigateBack(): void {
    this.router.navigate(['/replenishment/procurement', this.procId]);
  }

  recordReceipt(): void {
    if (!this.canSubmit()) return;

    const receipts: { procurement_item_id: number; received_qty: number }[] = [];
    for (let i = 0; i < this.lineItemsForm.length; i++) {
      const group = this.lineItemsForm.at(i);
      const qty = group.controls.qty_to_receive.value;
      if (qty > 0) {
        receipts.push({
          procurement_item_id: group.controls.procurement_item_id.value,
          received_qty: qty,
        });
      }
    }

    const dialogData: ConfirmDialogData = {
      title: 'Confirm Receipt',
      message: `Record receipt for ${receipts.length} item${receipts.length !== 1 ? 's' : ''}?`,
      confirmLabel: 'Record Receipt',
      cancelLabel: 'Cancel',
    };

    const dialogRef = this.dialog.open(DmisConfirmDialogComponent, {
      data: dialogData,
      width: '420px',
      autoFocus: false,
    });

    dialogRef
      .afterClosed()
      .pipe(filter((confirmed) => confirmed === true))
      .subscribe(() => {
        this.submitReceipt(receipts);
      });
  }

  private submitReceipt(
    receipts: { procurement_item_id: number; received_qty: number }[]
  ): void {
    this.submitting.set(true);

    this.replenishmentService
      .receiveProcurementItems(this.procId, { receipts })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.submitting.set(false);
          this.notifications.showSuccess('Receipt recorded successfully.');
          this.router.navigate(['/replenishment/procurement', this.procId]);
        },
        error: () => {
          this.submitting.set(false);
          this.notifications.showError('Failed to record receipt. Please try again.');
        },
      });
  }

  private loadProcurement(): void {
    this.loading.set(true);
    this.error.set(null);

    this.replenishmentService
      .getProcurement(this.procId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (order) => {
          if (
            order.status_code !== 'SHIPPED' &&
            order.status_code !== 'PARTIAL_RECEIVED'
          ) {
            this.error.set(
              `Cannot receive items for a procurement in "${this.getStatusLabel(order.status_code)}" status. ` +
              'Only SHIPPED or PARTIAL RECEIVED procurements can be received.'
            );
            this.loading.set(false);
            return;
          }

          this.procurement.set(order);
          this.buildFormArray(order.items);
          this.loading.set(false);
        },
        error: () => {
          this.error.set('Failed to load procurement order.');
          this.loading.set(false);
        },
      });
  }

  private buildFormArray(items: ProcurementOrderItem[]): void {
    this.lineItemsForm.clear();

    for (const item of items) {
      const remaining = item.ordered_qty - item.received_qty;
      const group = new FormGroup<LineItemFormGroup>({
        procurement_item_id: new FormControl<number>(item.procurement_item_id, {
          nonNullable: true,
        }),
        qty_to_receive: new FormControl<number>(0, {
          nonNullable: true,
          validators: [
            Validators.required,
            Validators.min(0),
            Validators.max(remaining),
          ],
        }),
      });
      this.lineItemsForm.push(group);
    }
  }
}
