import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import {
  FormControl,
  FormGroup,
  ReactiveFormsModule,
  Validators,
} from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { finalize } from 'rxjs/operators';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSelectModule } from '@angular/material/select';
import { MatTableModule } from '@angular/material/table';
import { MatTooltipModule } from '@angular/material/tooltip';

import { MasterDataService } from '../../master-data/services/master-data.service';
import { MasterRecord } from '../../master-data/models/master-data.models';
import { AuthRbacService } from '../services/auth-rbac.service';
import { DmisNotificationService } from '../services/notification.service';
import {
  CreateUomRepackagingPayload,
  ReplenishmentService,
  UomRepackagingListResponse,
  UomRepackagingMutationResponse,
  UomRepackagingPreviewPayload,
  UomRepackagingPreviewResponse,
  Warehouse,
} from '../services/replenishment.service';

interface ItemLookupOption {
  item_id: number;
  item_name: string;
  item_code: string;
}

interface ItemUomOption {
  item_uom_option_id?: number;
  uom_code: string;
  conversion_factor: number;
  is_default: boolean;
  sort_order?: number;
  status_code?: string;
}

interface RepackagingErrorState {
  message: string;
  details: string[];
}

@Component({
  selector: 'app-uom-repackaging',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    MatButtonModule,
    MatCardModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatProgressBarModule,
    MatSelectModule,
    MatTableModule,
    MatTooltipModule,
  ],
  templateUrl: './uom-repackaging.component.html',
  styleUrl: './uom-repackaging.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class UomRepackagingComponent {
  private readonly masterDataService = inject(MasterDataService);
  private readonly replenishmentService = inject(ReplenishmentService);
  private readonly notify = inject(DmisNotificationService);
  private readonly authRbac = inject(AuthRbacService);
  private readonly destroyRef = inject(DestroyRef);

  readonly form = new FormGroup({
    warehouse_id: new FormControl<number | null>(null, [Validators.required, Validators.min(1)]),
    item_id: new FormControl<number | null>(null, [Validators.required, Validators.min(1)]),
    batch_or_lot: new FormControl<string>(''),
    source_uom_code: new FormControl<string>('', [Validators.required]),
    source_qty: new FormControl<number | null>(null, [Validators.required, Validators.min(0.000001)]),
    target_uom_code: new FormControl<string>('', [Validators.required]),
    reason_code: new FormControl<string>('', [Validators.required]),
    note: new FormControl<string>(''),
  });

  readonly warehouses = signal<Warehouse[]>([]);
  readonly items = signal<ItemLookupOption[]>([]);
  readonly selectedItem = signal<MasterRecord | null>(null);
  readonly preview = signal<UomRepackagingPreviewResponse | null>(null);
  readonly recentRecords = signal<UomRepackagingMutationResponse['record'][]>([]);

  readonly pageLoading = signal(true);
  readonly itemLoading = signal(false);
  readonly previewLoading = signal(false);
  readonly submitLoading = signal(false);
  readonly activityLoading = signal(false);

  readonly pageError = signal<string | null>(null);
  readonly previewError = signal<RepackagingErrorState | null>(null);
  readonly submitError = signal<RepackagingErrorState | null>(null);

  readonly displayedColumns = [
    'created_at',
    'warehouse_name',
    'item_name',
    'source',
    'target',
    'reason_code',
    'created_by',
  ];

  readonly reasonOptions = [
    { value: 'WAREHOUSE_HANDLING', label: 'Warehouse Handling' },
    { value: 'RIGHT_SIZE_FOR_ISSUE', label: 'Right Size for Issue' },
    { value: 'DAMAGED_OUTER_PACK', label: 'Damaged Outer Pack' },
    { value: 'COUNT_NORMALIZATION', label: 'Count Normalization' },
    { value: 'OTHER', label: 'Other' },
  ];

  readonly allowedUomOptions = computed<ItemUomOption[]>(() => {
    const rawOptions = this.selectedItem()?.['uom_options'];
    if (!Array.isArray(rawOptions)) {
      return [];
    }

    return rawOptions
      .filter((option): option is Record<string, unknown> => option != null && typeof option === 'object')
      .map((option) => ({
        item_uom_option_id: typeof option['item_uom_option_id'] === 'number' ? option['item_uom_option_id'] : undefined,
        uom_code: String(option['uom_code'] ?? '').trim().toUpperCase(),
        conversion_factor: Number(option['conversion_factor'] ?? 0),
        is_default: Boolean(option['is_default']),
        sort_order: typeof option['sort_order'] === 'number' ? option['sort_order'] : undefined,
        status_code: typeof option['status_code'] === 'string'
          ? String(option['status_code']).trim().toUpperCase()
          : undefined,
      }))
      .filter((option) => option.uom_code.length > 0 && option.status_code !== 'I')
      .sort((left, right) => {
        if (left.is_default !== right.is_default) {
          return left.is_default ? -1 : 1;
        }
        return left.uom_code.localeCompare(right.uom_code);
      });
  });

  readonly canExecute = computed(() => {
    const roles = this.authRbac.roles().map((role) => role.trim().toUpperCase());
    if (roles.some((role) => [
      'SYSTEM_ADMINISTRATOR',
      'LOGISTICS_MANAGER',
      'LOGISTICS MANAGER',
      'LOGISTICS_OFFICER',
      'LOGISTICS OFFICER',
      'INVENTORY_CLERK',
      'INVENTORY CLERK',
    ].includes(role))) {
      return true;
    }
    return this.authRbac.hasPermission('replenishment.needs_list.preview');
  });

  readonly canPreview = computed(() => {
    const value = this.form.getRawValue();
    return this.canExecute()
      && !this.previewLoading()
      && this.allowedUomOptions().length > 1
      && Number.isInteger(value.warehouse_id ?? 0)
      && Number.isInteger(value.item_id ?? 0)
      && typeof value.source_uom_code === 'string'
      && value.source_uom_code.length > 0
      && typeof value.target_uom_code === 'string'
      && value.target_uom_code.length > 0
      && value.source_uom_code !== value.target_uom_code
      && Number(value.source_qty ?? 0) > 0;
  });

  constructor() {
    this.authRbac.load();
    this.loadPageData();

    this.form.controls.item_id.valueChanges.pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe((itemId) => {
      this.clearPreviewState();
      this.clearSubmitError();
      if (!itemId) {
        this.selectedItem.set(null);
        return;
      }
      this.loadItem(itemId);
    });

    this.form.controls.warehouse_id.valueChanges.pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(() => {
      this.clearPreviewState();
      this.clearSubmitError();
      this.loadRecentRecords();
    });

    this.form.controls.source_uom_code.valueChanges.pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(() => {
      this.clearPreviewState();
      this.clearSubmitError();
    });

    this.form.controls.target_uom_code.valueChanges.pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(() => {
      this.clearPreviewState();
      this.clearSubmitError();
    });

    this.form.controls.source_qty.valueChanges.pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(() => {
      this.clearPreviewState();
      this.clearSubmitError();
    });

    this.form.controls.batch_or_lot.valueChanges.pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(() => {
      this.clearPreviewState();
      this.clearSubmitError();
    });
  }

  getItemLabel(item: ItemLookupOption): string {
    return item.item_code ? `${item.item_name} (${item.item_code})` : item.item_name;
  }

  getUomLabel(option: ItemUomOption): string {
    const factor = Number(option.conversion_factor || 0);
    if (option.is_default) {
      return `${option.uom_code} (default)`;
    }
    return Number.isFinite(factor) && factor > 0
      ? `${option.uom_code} (${factor} default units)`
      : option.uom_code;
  }

  getPreviewErrorDetails(): string[] {
    return this.previewError()?.details ?? [];
  }

  getSubmitErrorDetails(): string[] {
    return this.submitError()?.details ?? [];
  }

  getControlError(fieldName: keyof typeof this.form.controls): string | null {
    const control = this.form.controls[fieldName];
    if (!control.touched || !control.errors) {
      return null;
    }
    if (control.errors['required']) {
      return 'This field is required.';
    }
    if (control.errors['min']) {
      return 'Enter a value greater than zero.';
    }
    if (control.errors['sameUom']) {
      return 'Source and target UOM must be different.';
    }
    if (control.errors['server']) {
      return String(control.errors['server']);
    }
    return 'Invalid value.';
  }

  onPreview(): void {
    this.clearPreviewState();
    this.clearSubmitError();
    this.clearServerErrors();

    if (!this.canExecute()) {
      this.notify.showWarning('Only authorized warehouse-facing users can create repackaging transactions.');
      return;
    }

    if (this.isSameUomSelection()) {
      this.applySameUomError();
      this.notify.showWarning('Choose different source and target UOM values.');
      return;
    }

    if (!this.canPreview()) {
      this.form.markAllAsTouched();
      return;
    }

    const payload = this.buildPreviewPayload();
    if (!payload) {
      this.form.markAllAsTouched();
      return;
    }

    this.previewLoading.set(true);
    this.replenishmentService.previewUomRepackaging(payload).pipe(
      finalize(() => this.previewLoading.set(false)),
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: (response) => {
        this.preview.set(response);
        if ((response.warnings ?? []).length > 0) {
          this.notify.showWarning('Preview loaded with warnings. Review them before submitting.');
        }
      },
      error: (error) => {
        this.previewError.set(this.extractErrorState(error, 'Unable to preview the repackaging transaction.'));
      },
    });
  }

  onSubmit(): void {
    this.clearSubmitError();
    this.clearServerErrors();

    if (!this.preview()) {
      this.notify.showWarning('Preview the repackaging transaction before submitting it.');
      return;
    }

    if (!this.canExecute()) {
      this.notify.showWarning('Only authorized warehouse-facing users can create repackaging transactions.');
      return;
    }

    if (this.form.controls.reason_code.invalid) {
      this.form.controls.reason_code.markAsTouched();
      return;
    }

    const payload = this.buildCreatePayload();
    if (!payload) {
      this.form.markAllAsTouched();
      return;
    }

    this.submitLoading.set(true);
    this.replenishmentService.createUomRepackaging(payload).pipe(
      finalize(() => this.submitLoading.set(false)),
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: (response) => {
        this.preview.set(null);
        this.recentRecords.update((records) => [response.record, ...records].slice(0, 10));
        this.form.patchValue({
          reason_code: '',
          note: '',
        });
        this.form.markAsPristine();
        this.notify.showSuccess('Repackaging transaction recorded.');
      },
      error: (error) => {
        const parsedError = this.extractErrorState(error, 'Unable to save the repackaging transaction.');
        this.submitError.set(parsedError);
        this.applyServerFieldErrors(error?.error?.errors);
      },
    });
  }

  private loadPageData(): void {
    this.pageLoading.set(true);
    this.pageError.set(null);

    this.replenishmentService.getAllWarehouses().pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: (warehouses) => {
        this.warehouses.set(warehouses);
        this.loadItems();
        this.loadRecentRecords();
        this.pageLoading.set(false);
      },
      error: () => {
        this.pageLoading.set(false);
        this.pageError.set('Failed to load warehouses for repackaging.');
      },
    });
  }

  private loadItems(): void {
    this.masterDataService.list('items', {
      status: 'A',
      orderBy: 'item_name',
      limit: 250,
      offset: 0,
    }).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: (response) => {
        this.items.set(
          response.results
            .map((row) => ({
              item_id: Number(row['item_id']),
              item_name: String(row['item_name'] ?? '').trim(),
              item_code: String(row['item_code'] ?? '').trim(),
            }))
            .filter((row) => Number.isInteger(row.item_id) && row.item_name.length > 0)
        );
      },
      error: () => {
        this.pageError.set('Failed to load active items for repackaging.');
      },
    });
  }

  private loadItem(itemId: number): void {
    this.itemLoading.set(true);
    this.masterDataService.get('items', itemId).pipe(
      finalize(() => this.itemLoading.set(false)),
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: (response) => {
        this.selectedItem.set(response.record);
        this.syncSelectedUoms();
      },
      error: () => {
        this.selectedItem.set(null);
        this.notify.showError('Failed to load the selected item details.');
      },
    });
  }

  private loadRecentRecords(): void {
    this.activityLoading.set(true);
    const warehouseId = this.form.controls.warehouse_id.value ?? undefined;
    this.replenishmentService.listUomRepackaging({
      warehouse_id: warehouseId ?? undefined,
      limit: 10,
    }).pipe(
      finalize(() => this.activityLoading.set(false)),
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: (response: UomRepackagingListResponse) => {
        this.recentRecords.set(response.results ?? []);
      },
      error: () => {
        this.recentRecords.set([]);
      },
    });
  }

  private syncSelectedUoms(): void {
    const options = this.allowedUomOptions();
    const defaultOption = options.find((option) => option.is_default) ?? options[0] ?? null;
    const currentSource = String(this.form.controls.source_uom_code.value ?? '').trim().toUpperCase();
    const currentTarget = String(this.form.controls.target_uom_code.value ?? '').trim().toUpperCase();

    if (!currentSource && defaultOption) {
      this.form.controls.source_uom_code.setValue(defaultOption.uom_code);
    } else if (currentSource && !options.some((option) => option.uom_code === currentSource)) {
      this.form.controls.source_uom_code.setValue(defaultOption?.uom_code ?? '');
    }

    if (currentTarget && !options.some((option) => option.uom_code === currentTarget)) {
      this.form.controls.target_uom_code.setValue('');
    }

    if (
      options.length > 1
      && !this.form.controls.target_uom_code.value
      && this.form.controls.source_uom_code.value
    ) {
      const fallbackTarget = options.find((option) => option.uom_code !== this.form.controls.source_uom_code.value);
      this.form.controls.target_uom_code.setValue(fallbackTarget?.uom_code ?? '');
    }
  }

  private buildPreviewPayload(): UomRepackagingPreviewPayload | null {
    const warehouseId = this.form.controls.warehouse_id.value;
    const itemId = this.form.controls.item_id.value;
    const sourceQty = Number(this.form.controls.source_qty.value);
    const sourceUomCode = String(this.form.controls.source_uom_code.value ?? '').trim().toUpperCase();
    const targetUomCode = String(this.form.controls.target_uom_code.value ?? '').trim().toUpperCase();
    const batchOrLot = String(this.form.controls.batch_or_lot.value ?? '').trim();

    if (!warehouseId || !itemId || !sourceUomCode || !targetUomCode || !(sourceQty > 0)) {
      return null;
    }

    return {
      warehouse_id: warehouseId,
      item_id: itemId,
      batch_or_lot: batchOrLot || null,
      source_uom_code: sourceUomCode,
      source_qty: sourceQty,
      target_uom_code: targetUomCode,
    };
  }

  private buildCreatePayload(): CreateUomRepackagingPayload | null {
    const previewPayload = this.buildPreviewPayload();
    const reasonCode = String(this.form.controls.reason_code.value ?? '').trim().toUpperCase();
    const note = String(this.form.controls.note.value ?? '').trim();

    if (!previewPayload || !reasonCode) {
      return null;
    }

    return {
      ...previewPayload,
      reason_code: reasonCode,
      note: note || null,
    };
  }

  private isSameUomSelection(): boolean {
    return String(this.form.controls.source_uom_code.value ?? '').trim().toUpperCase()
      === String(this.form.controls.target_uom_code.value ?? '').trim().toUpperCase()
      && String(this.form.controls.source_uom_code.value ?? '').trim().length > 0;
  }

  private applySameUomError(): void {
    this.form.controls.target_uom_code.setErrors({ ...(this.form.controls.target_uom_code.errors ?? {}), sameUom: true });
    this.form.controls.target_uom_code.markAsTouched();
  }

  private clearPreviewState(): void {
    this.preview.set(null);
    this.previewError.set(null);
    if (this.form.controls.target_uom_code.errors?.['sameUom']) {
      const nextErrors = { ...(this.form.controls.target_uom_code.errors ?? {}) };
      delete nextErrors['sameUom'];
      this.form.controls.target_uom_code.setErrors(Object.keys(nextErrors).length > 0 ? nextErrors : null);
    }
  }

  private clearSubmitError(): void {
    this.submitError.set(null);
  }

  private clearServerErrors(): void {
    Object.values(this.form.controls).forEach((control) => {
      if (!control.errors?.['server']) {
        return;
      }
      const nextErrors = { ...control.errors };
      delete nextErrors['server'];
      control.setErrors(Object.keys(nextErrors).length > 0 ? nextErrors : null);
    });
  }

  private applyServerFieldErrors(errors: unknown): void {
    if (!errors || typeof errors !== 'object') {
      return;
    }

    for (const [fieldName, value] of Object.entries(errors as Record<string, unknown>)) {
      const control = this.form.controls[fieldName as keyof typeof this.form.controls];
      if (!control) {
        continue;
      }
      control.setErrors({ ...(control.errors ?? {}), server: String(value) });
      control.markAsTouched();
    }
  }

  private extractErrorState(error: unknown, fallbackMessage: string): RepackagingErrorState {
    const err = error as {
      error?: {
        detail?: string;
        diagnostic?: string;
        warnings?: string[];
        errors?: Record<string, unknown>;
      };
    };

    const message = String(err?.error?.detail ?? '').trim() || fallbackMessage;
    const details: string[] = [];
    const diagnostic = String(err?.error?.diagnostic ?? '').trim();
    if (diagnostic) {
      details.push(`Diagnostic: ${diagnostic}`);
    }
    for (const warning of err?.error?.warnings ?? []) {
      const normalized = String(warning).trim();
      if (normalized) {
        details.push(normalized);
      }
    }
    for (const [fieldName, value] of Object.entries(err?.error?.errors ?? {})) {
      details.push(`${fieldName}: ${String(value)}`);
    }

    return {
      message,
      details: [...new Set(details)],
    };
  }
}
