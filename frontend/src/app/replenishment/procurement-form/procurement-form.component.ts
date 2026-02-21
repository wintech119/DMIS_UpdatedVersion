import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
  OnInit
} from '@angular/core';
import { CurrencyPipe, DecimalPipe } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import {
  FormBuilder,
  FormArray,
  FormGroup,
  ReactiveFormsModule,
  Validators
} from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { switchMap, startWith, map, debounceTime } from 'rxjs/operators';
import { of } from 'rxjs';

import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatAutocompleteModule } from '@angular/material/autocomplete';
import { MatDialogModule } from '@angular/material/dialog';

import { ReplenishmentService } from '../services/replenishment.service';
import { DmisNotificationService } from '../services/notification.service';
import { DmisSkeletonLoaderComponent } from '../shared/dmis-skeleton-loader/dmis-skeleton-loader.component';
import {
  ProcurementOrder,
  ProcurementMethod,
  PROCUREMENT_METHOD_LABELS,
  Supplier,
  CreateSupplierPayload,
  UpdateProcurementPayload
} from '../models/procurement.model';

@Component({
  selector: 'app-procurement-form',
  standalone: true,
  imports: [
    CurrencyPipe,
    DecimalPipe,
    ReactiveFormsModule,
    MatButtonModule,
    MatIconModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatAutocompleteModule,
    MatDialogModule,
    DmisSkeletonLoaderComponent
  ],
  templateUrl: './procurement-form.component.html',
  styleUrl: './procurement-form.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class ProcurementFormComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly fb = inject(FormBuilder);
  private readonly replenishmentService = inject(ReplenishmentService);
  private readonly notifications = inject(DmisNotificationService);
  private readonly destroyRef = inject(DestroyRef);

  // ── State signals ──────────────────────────────────────────────────────────
  readonly loading = signal(true);
  readonly saving = signal(false);
  readonly submitting = signal(false);
  readonly error = signal(false);
  readonly showSupplierDialog = signal(false);
  readonly creatingSupplier = signal(false);

  readonly procurement = signal<ProcurementOrder | null>(null);
  readonly suppliers = signal<Supplier[]>([]);
  readonly filteredSuppliers = signal<Supplier[]>([]);
  readonly removedProcurementItemIds = signal<number[]>([]);

  readonly isEditMode = signal(false);
  readonly pageTitle = computed(() => this.isEditMode() ? 'Edit Procurement Order' : 'New Procurement Order');

  readonly procurementMethods = Object.entries(PROCUREMENT_METHOD_LABELS).map(
    ([value, label]) => ({ value: value as ProcurementMethod, label })
  );

  // ── Reactive Forms ─────────────────────────────────────────────────────────
  readonly headerForm = this.fb.group({
    supplier_id: [null as number | null],
    supplier_search: [''],
    procurement_method: ['EMERGENCY_DIRECT' as ProcurementMethod, Validators.required],
    notes: ['']
  });

  readonly lineItemsArray: FormArray<FormGroup> = this.fb.array<FormGroup>([]);

  readonly supplierForm = this.fb.group({
    supplier_code: ['', Validators.required],
    supplier_name: ['', Validators.required],
    contact_name: [''],
    phone_no: [''],
    email_text: ['', Validators.email],
    default_lead_time_days: [14, [Validators.required, Validators.min(1)]]
  });

  // ── Computed values ────────────────────────────────────────────────────────
  readonly totalValue = computed(() => {
    const proc = this.procurement();
    if (!proc) return 0;
    // Recalculate from current form state is done via the form itself
    let total = 0;
    for (let i = 0; i < this.lineItemsArray.length; i++) {
      const group = this.lineItemsArray.at(i);
      const qty = group.get('ordered_qty')?.value || 0;
      const price = group.get('unit_price')?.value || 0;
      total += qty * price;
    }
    return total;
  });

  readonly isDraft = computed(() => {
    const proc = this.procurement();
    return !proc || proc.status_code === 'DRAFT';
  });

  readonly hasLineItems = computed(() => this.lineItemsArray.length > 0);

  // ── Lifecycle ──────────────────────────────────────────────────────────────
  ngOnInit(): void {
    this.loadSuppliers();
    this.setupSupplierAutocomplete();
    this.resolveRoute();
  }

  // ── Supplier autocomplete ──────────────────────────────────────────────────
  private setupSupplierAutocomplete(): void {
    this.headerForm.get('supplier_search')!.valueChanges.pipe(
      startWith(''),
      debounceTime(200),
      takeUntilDestroyed(this.destroyRef)
    ).subscribe(searchTerm => {
      const term = this.normalizeSupplierSearchTerm(searchTerm);
      if (!term) {
        this.filteredSuppliers.set(this.suppliers());
      } else {
        this.filteredSuppliers.set(
          this.suppliers().filter(s =>
            s.supplier_name.toLowerCase().includes(term) ||
            s.supplier_code.toLowerCase().includes(term)
          )
        );
      }
    });
  }

  displaySupplierFn = (supplier: Supplier | null): string => {
    return supplier ? `${supplier.supplier_name} (${supplier.supplier_code})` : '';
  };

  selectSupplier(supplier: Supplier): void {
    this.headerForm.patchValue(
      {
        supplier_id: supplier.supplier_id,
        supplier_search: `${supplier.supplier_name} (${supplier.supplier_code})`
      },
      { emitEvent: false }
    );
  }

  // ── Route resolution ───────────────────────────────────────────────────────
  private resolveRoute(): void {
    const procId = this.route.snapshot.paramMap.get('procId');

    if (procId) {
      // Edit mode
      this.isEditMode.set(true);
      this.loadProcurement(Number(procId));
    } else {
      // Create mode
      const needsListId = this.route.snapshot.queryParamMap.get('needsListId');
      if (needsListId) {
        this.createFromNeedsList(needsListId);
      } else {
        // Standalone form - no auto-create
        this.loading.set(false);
      }
    }
  }

  private loadProcurement(procId: number): void {
    this.loading.set(true);
    this.error.set(false);

    this.replenishmentService.getProcurement(procId).pipe(
      takeUntilDestroyed(this.destroyRef)
    ).subscribe({
      next: (order) => {
        if (order.status_code !== 'DRAFT') {
          this.notifications.showError('Only DRAFT procurement orders can be edited.');
          this.navigateToProcurementList();
          return;
        }
        this.procurement.set(order);
        this.populateForm(order);
        this.loading.set(false);
      },
      error: () => {
        this.error.set(true);
        this.loading.set(false);
        this.notifications.showError('Failed to load procurement order.');
      }
    });
  }

  private createFromNeedsList(needsListId: string): void {
    this.loading.set(true);
    this.error.set(false);

    this.replenishmentService.createProcurement({ needs_list_id: needsListId }).pipe(
      takeUntilDestroyed(this.destroyRef)
    ).subscribe({
      next: (order) => {
        this.isEditMode.set(true);
        this.procurement.set(order);
        this.populateForm(order);
        this.loading.set(false);
        this.notifications.showSuccess('Procurement draft created from needs list.');
        // Update the URL to edit mode without reloading
        this.router.navigate(
          ['/replenishment/procurement', order.procurement_id, 'edit'],
          { replaceUrl: true }
        );
      },
      error: () => {
        this.error.set(true);
        this.loading.set(false);
        this.notifications.showError('Failed to create procurement from needs list.');
      }
    });
  }

  // ── Form population ────────────────────────────────────────────────────────
  private populateForm(order: ProcurementOrder): void {
    this.removedProcurementItemIds.set([]);
    this.headerForm.patchValue({
      supplier_id: order.supplier?.supplier_id ?? null,
      supplier_search: order.supplier
        ? `${order.supplier.supplier_name} (${order.supplier.supplier_code})`
        : '',
      procurement_method: order.procurement_method,
      notes: order.notes_text || ''
    });

    // Clear existing line items and rebuild
    this.lineItemsArray.clear();
    for (const item of order.items) {
      this.lineItemsArray.push(this.createLineItemGroup(item));
    }
  }

  private createLineItemGroup(item: {
    procurement_item_id?: number;
    item_id: number;
    item_name: string;
    uom_code: string;
    ordered_qty: number;
    unit_price: number | null;
  }): FormGroup {
    const group = this.fb.group({
      procurement_item_id: [item.procurement_item_id ?? null],
      item_id: [item.item_id],
      item_name: [item.item_name],
      uom_code: [item.uom_code],
      ordered_qty: [item.ordered_qty, [Validators.required, Validators.min(1)]],
      unit_price: [item.unit_price ?? 0, [Validators.required, Validators.min(0)]],
      line_total: [{ value: (item.ordered_qty || 0) * (item.unit_price || 0), disabled: true }]
    });

    // Auto-calculate line total when qty or price changes
    group.get('ordered_qty')!.valueChanges.pipe(
      takeUntilDestroyed(this.destroyRef)
    ).subscribe(() => this.recalcLineTotal(group));

    group.get('unit_price')!.valueChanges.pipe(
      takeUntilDestroyed(this.destroyRef)
    ).subscribe(() => this.recalcLineTotal(group));

    return group;
  }

  private recalcLineTotal(group: FormGroup): void {
    const qty = group.get('ordered_qty')?.value || 0;
    const price = group.get('unit_price')?.value || 0;
    group.get('line_total')?.setValue(qty * price, { emitEvent: false });
    // Trigger total recomputation by touching the procurement signal
    this.procurement.update(p => p ? { ...p } : p);
  }

  // ── Suppliers ──────────────────────────────────────────────────────────────
  private loadSuppliers(): void {
    this.replenishmentService.listSuppliers().pipe(
      takeUntilDestroyed(this.destroyRef)
    ).subscribe({
      next: (response) => {
        this.suppliers.set(response.suppliers || []);
        this.filteredSuppliers.set(response.suppliers || []);
      },
      error: () => {
        this.notifications.showError('Failed to load suppliers.');
      }
    });
  }

  toggleSupplierDialog(): void {
    this.showSupplierDialog.update(v => !v);
    if (this.showSupplierDialog()) {
      this.supplierForm.reset({ default_lead_time_days: 14 });
    }
  }

  createSupplier(): void {
    if (this.supplierForm.invalid) return;

    this.creatingSupplier.set(true);
    const payload: CreateSupplierPayload = {
      supplier_code: this.supplierForm.value.supplier_code!,
      supplier_name: this.supplierForm.value.supplier_name!,
      contact_name: this.supplierForm.value.contact_name || undefined,
      phone_no: this.supplierForm.value.phone_no || undefined,
      email_text: this.supplierForm.value.email_text || undefined,
      default_lead_time_days: this.supplierForm.value.default_lead_time_days ?? 14
    };

    this.replenishmentService.createSupplier(payload).pipe(
      takeUntilDestroyed(this.destroyRef)
    ).subscribe({
      next: (supplier) => {
        this.creatingSupplier.set(false);
        this.suppliers.update(list => [...list, supplier]);
        this.filteredSuppliers.update(list => [...list, supplier]);
        this.selectSupplier(supplier);
        this.headerForm.patchValue({
          supplier_search: `${supplier.supplier_name} (${supplier.supplier_code})`
        });
        this.showSupplierDialog.set(false);
        this.notifications.showSuccess(`Supplier "${supplier.supplier_name}" created.`);
      },
      error: () => {
        this.creatingSupplier.set(false);
        this.notifications.showError('Failed to create supplier.');
      }
    });
  }

  // ── Line item management ───────────────────────────────────────────────────
  removeLine(index: number): void {
    const group = this.lineItemsArray.at(index);
    const procurementItemId = Number(group.get('procurement_item_id')?.value);
    if (Number.isFinite(procurementItemId) && procurementItemId > 0) {
      this.removedProcurementItemIds.update((ids) =>
        ids.includes(procurementItemId) ? ids : [...ids, procurementItemId]
      );
    }
    this.lineItemsArray.removeAt(index);
    this.procurement.update(p => p ? { ...p } : p);
  }

  getLineTotal(index: number): number {
    const group = this.lineItemsArray.at(index);
    const qty = group.get('ordered_qty')?.value || 0;
    const price = group.get('unit_price')?.value || 0;
    return qty * price;
  }

  getGrandTotal(): number {
    let total = 0;
    for (let i = 0; i < this.lineItemsArray.length; i++) {
      total += this.getLineTotal(i);
    }
    return total;
  }

  // ── Save & Submit ──────────────────────────────────────────────────────────
  saveDraft(): void {
    if (!this.validateForm()) return;

    const proc = this.procurement();
    if (!proc) {
      this.notifications.showError('No procurement order to save.');
      return;
    }

    this.saving.set(true);
    const payload = this.buildUpdatePayload();

    this.replenishmentService.updateProcurement(proc.procurement_id, payload).pipe(
      takeUntilDestroyed(this.destroyRef)
    ).subscribe({
      next: (updated) => {
        this.saving.set(false);
        this.procurement.set(updated);
        this.populateForm(updated);
        this.notifications.showSuccess('Procurement draft saved.');
      },
      error: () => {
        this.saving.set(false);
        this.notifications.showError('Failed to save procurement draft.');
      }
    });
  }

  submitForApproval(): void {
    if (!this.validateForm()) return;

    const proc = this.procurement();
    if (!proc) {
      this.notifications.showError('No procurement order to submit.');
      return;
    }

    this.submitting.set(true);
    const payload = this.buildUpdatePayload();

    // Save first, then submit
    this.replenishmentService.updateProcurement(proc.procurement_id, payload).pipe(
      switchMap((updated) =>
        this.replenishmentService.submitProcurement(updated.procurement_id)
      ),
      takeUntilDestroyed(this.destroyRef)
    ).subscribe({
      next: (submitted) => {
        this.submitting.set(false);
        this.notifications.showSuccess('Procurement order submitted for approval.');
        this.navigateToProcurementList();
      },
      error: () => {
        this.submitting.set(false);
        this.notifications.showError('Failed to submit procurement order.');
      }
    });
  }

  cancel(): void {
    this.navigateToProcurementList();
  }

  // ── Validation ─────────────────────────────────────────────────────────────
  private validateForm(): boolean {
    this.headerForm.markAllAsTouched();

    if (this.lineItemsArray.length === 0) {
      this.notifications.showWarning('At least one line item is required.');
      return false;
    }

    let valid = true;
    for (let i = 0; i < this.lineItemsArray.length; i++) {
      const group = this.lineItemsArray.at(i);
      group.markAllAsTouched();
      if (group.invalid) {
        valid = false;
      }
    }

    if (!valid) {
      this.notifications.showWarning('Please fix validation errors before saving.');
      return false;
    }

    return true;
  }

  private navigateToProcurementList(): void {
    const needsListId =
      String(
        this.procurement()?.needs_list_id ??
        this.route.snapshot.queryParamMap.get('needsListId') ??
        ''
      ).trim();
    if (needsListId) {
      this.router.navigate(['/replenishment/needs-list', needsListId, 'procurement']);
      return;
    }
    this.router.navigate(['/replenishment/dashboard']);
  }

  private normalizeSupplierSearchTerm(searchTerm: unknown): string {
    if (typeof searchTerm === 'string') {
      return searchTerm.toLowerCase().trim();
    }
    if (searchTerm && typeof searchTerm === 'object') {
      const supplier = searchTerm as Partial<Supplier>;
      const supplierName = String(supplier.supplier_name ?? '').trim();
      const supplierCode = String(supplier.supplier_code ?? '').trim();
      return `${supplierName} ${supplierCode}`.toLowerCase().trim();
    }
    return '';
  }

  private buildUpdatePayload(): UpdateProcurementPayload {
    const formVal = this.headerForm.getRawValue();
    const removedItemIds = this.removedProcurementItemIds();
    return {
      supplier_id: formVal.supplier_id,
      procurement_method: formVal.procurement_method as ProcurementMethod,
      notes: formVal.notes || '',
      deleted_procurement_item_ids: removedItemIds.length ? removedItemIds : undefined,
      items: this.lineItemsArray.controls.map(group => {
        const val = group.getRawValue();
        return {
          procurement_item_id: val.procurement_item_id ?? undefined,
          item_id: val.item_id,
          ordered_qty: val.ordered_qty,
          unit_price: val.unit_price
        };
      })
    };
  }
}
