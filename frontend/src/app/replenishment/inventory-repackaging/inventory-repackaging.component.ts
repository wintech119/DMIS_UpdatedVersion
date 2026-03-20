import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { CommonModule, DatePipe, DecimalPipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  FormBuilder,
  ReactiveFormsModule,
  Validators,
} from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { forkJoin } from 'rxjs';

import { MatAutocompleteModule } from '@angular/material/autocomplete';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatTooltipModule } from '@angular/material/tooltip';

import { LookupItem, MasterRecord } from '../../master-data/models/master-data.models';
import { MasterDataService } from '../../master-data/services/master-data.service';
import {
  CreateRepackagingPayload,
  RepackagingAuditRow,
  RepackagingRecord,
  RepackagingRecordSummary,
} from '../models/repackaging.model';
import { DmisNotificationService } from '../services/notification.service';
import { ReplenishmentService, Warehouse } from '../services/replenishment.service';
import { DmisEmptyStateComponent } from '../shared/dmis-empty-state/dmis-empty-state.component';
import { DmisSkeletonLoaderComponent } from '../shared/dmis-skeleton-loader/dmis-skeleton-loader.component';

interface ItemLookupOption {
  itemId: number;
  label: string;
  itemCode: string;
  itemName: string;
}

interface ItemUomOption {
  uomCode: string;
  conversionFactor: number;
  isDefault: boolean;
}

interface ItemContext {
  itemId: number;
  itemCode: string;
  itemName: string;
  defaultUomCode: string;
  isBatched: boolean;
  canExpire: boolean;
  uomOptions: ItemUomOption[];
}

interface PreviewSummary {
  sourceFactor: number;
  targetFactor: number;
  targetQty: number;
  equivalentDefaultQty: number;
}

interface ErrorSummary {
  title: string;
  details: string[];
}

const DEFAULT_LIMIT = 8;

@Component({
  selector: 'app-inventory-repackaging',
  standalone: true,
  imports: [
    CommonModule,
    DatePipe,
    DecimalPipe,
    ReactiveFormsModule,
    MatAutocompleteModule,
    MatButtonModule,
    MatCardModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatSelectModule,
    MatTooltipModule,
    DmisEmptyStateComponent,
    DmisSkeletonLoaderComponent,
  ],
  templateUrl: './inventory-repackaging.component.html',
  styleUrl: './inventory-repackaging.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class InventoryRepackagingComponent {
  private readonly fb = inject(FormBuilder);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  private readonly masterDataService = inject(MasterDataService);
  private readonly replenishmentService = inject(ReplenishmentService);
  private readonly notifications = inject(DmisNotificationService);

  readonly loading = signal(true);
  readonly historyLoading = signal(false);
  readonly detailLoading = signal(false);
  readonly itemLoading = signal(false);
  readonly submitting = signal(false);

  readonly warehouses = signal<Warehouse[]>([]);
  readonly items = signal<ItemLookupOption[]>([]);
  readonly selectedItem = signal<ItemContext | null>(null);
  readonly selectedRecord = signal<RepackagingRecord | null>(null);
  readonly history = signal<RepackagingRecordSummary[]>([]);
  readonly pageWarnings = signal<string[]>([]);
  readonly submitError = signal<ErrorSummary | null>(null);
  readonly accessDenied = signal<string | null>(null);
  readonly previewRequested = signal(false);

  readonly form = this.fb.nonNullable.group({
    warehouse_id: [0, [Validators.required, Validators.min(1)]],
    item_id: [0, [Validators.required, Validators.min(1)]],
    item_search: [''],
    source_uom_code: ['', Validators.required],
    source_qty: [0, [Validators.required, Validators.min(0.000001)]],
    target_uom_code: ['', Validators.required],
    reason_code: ['', [Validators.required, Validators.maxLength(80)]],
    batch_id: [null as number | null],
    batch_or_lot: ['', [Validators.maxLength(80)]],
    note_text: ['', [Validators.maxLength(500)]],
  });

  readonly filteredItems = computed(() => {
    const term = this.form.controls.item_search.value.trim().toLowerCase();
    if (!term) {
      return this.items().slice(0, 25);
    }
    return this.items()
      .filter((item) => (
        item.label.toLowerCase().includes(term)
        || item.itemCode.toLowerCase().includes(term)
      ))
      .slice(0, 25);
  });

  readonly availableUoms = computed(() => this.selectedItem()?.uomOptions ?? []);
  readonly requiresBatchContext = computed(() => {
    const item = this.selectedItem();
    return Boolean(item?.isBatched || item?.canExpire);
  });
  readonly localValidationMessages = computed(() => this.buildLocalValidationMessages());
  readonly preview = computed(() => this.buildPreviewSummary());

  constructor() {
    this.loadPageData();
    this.watchFilters();
    this.watchRoute();
    this.watchFormChanges();
  }

  displayItem(option: ItemLookupOption | string | null): string {
    if (!option) {
      return '';
    }
    return typeof option === 'string' ? option : option.label;
  }

  onItemSelected(option: ItemLookupOption): void {
    this.form.patchValue({
      item_id: option.itemId,
      item_search: option.label,
    }, { emitEvent: false });
    this.loadItemContext(option.itemId, option.label);
  }

  onPreview(): void {
    this.previewRequested.set(true);
    this.clearSubmitError();
    this.clearAccessDenied();

    if (this.form.invalid) {
      this.form.markAllAsTouched();
      this.notifications.showWarning('Complete the repackaging form before previewing the transaction.');
      return;
    }

    const issues = this.localValidationMessages();
    if (issues.length > 0) {
      this.notifications.showWarning(issues[0]);
      return;
    }

    const preview = this.preview();
    if (!preview) {
      this.notifications.showWarning('Preview values are unavailable until the selected item UOM setup is loaded.');
      return;
    }

    this.notifications.showSuccess('Preview updated. Backend values remain authoritative when you submit.');
  }

  onSubmit(): void {
    this.previewRequested.set(true);
    this.clearSubmitError();
    this.clearAccessDenied();
    this.clearServerErrors();

    if (this.form.invalid) {
      this.form.markAllAsTouched();
      this.notifications.showWarning('Complete the required repackaging fields before submitting.');
      return;
    }

    const issues = this.localValidationMessages();
    if (issues.length > 0) {
      this.setSubmitError('Repackaging could not be submitted.', issues);
      this.notifications.showWarning(issues[0]);
      return;
    }

    const preview = this.preview();
    if (!preview) {
      this.setSubmitError(
        'Preview values are unavailable.',
        ['Load the item UOM conversions before submitting the transaction.'],
      );
      this.notifications.showWarning('Preview values are unavailable until the selected item UOM setup is loaded.');
      return;
    }

    const payload = this.buildCreatePayload(preview);
    if (!payload) {
      this.setSubmitError(
        'Repackaging could not be prepared.',
        ['The current form values do not produce a valid Sprint 07 repackaging payload.'],
      );
      return;
    }

    this.submitting.set(true);
    this.replenishmentService.createRepackagingTransaction(payload)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (response) => {
          this.submitting.set(false);
          this.selectedRecord.set(response.record);
          this.pageWarnings.set(response.warnings ?? []);
          this.notifications.showSuccess('Repackaging transaction saved.');
          this.loadHistory();
          void this.router.navigate(['/replenishment/inventory/repackaging', response.record.repackaging_id]);
        },
        error: (error: HttpErrorResponse) => {
          this.submitting.set(false);
          this.handleApiError(error, 'Failed to submit the repackaging transaction.');
        },
      });
  }

  openTransaction(recordId: number): void {
    void this.router.navigate(['/replenishment/inventory/repackaging', recordId]);
  }

  startNewTransaction(): void {
    this.selectedRecord.set(null);
    this.clearSubmitError();
    this.clearAccessDenied();
    void this.router.navigate(['/replenishment/inventory/repackaging']);
  }

  getFieldError(fieldName: keyof typeof this.form.controls): string | null {
    const control = this.form.controls[fieldName];
    if (!control.touched && !control.dirty) {
      return null;
    }

    if (control.hasError('required')) {
      switch (fieldName) {
        case 'warehouse_id':
          return 'Warehouse is required.';
        case 'item_id':
          return 'Item is required.';
        case 'source_uom_code':
          return 'Source UOM is required.';
        case 'source_qty':
          return 'Source quantity is required.';
        case 'target_uom_code':
          return 'Target UOM is required.';
        case 'reason_code':
          return 'Reason is required.';
        default:
          return 'This field is required.';
      }
    }

    if (control.hasError('min')) {
      return 'Enter a positive value.';
    }

    if (control.hasError('maxlength')) {
      const requiredLength = control.getError('maxlength')?.requiredLength ?? 'the allowed';
      return `Use ${requiredLength} characters or fewer.`;
    }

    if (control.hasError('server')) {
      return String(control.getError('server'));
    }

    return null;
  }

  formatReason(reasonCode: string | null | undefined): string {
    const normalized = String(reasonCode ?? '').trim();
    if (!normalized) {
      return 'Not provided';
    }
    return normalized
      .split('_')
      .filter(Boolean)
      .map((token) => token.charAt(0).toUpperCase() + token.slice(1).toLowerCase())
      .join(' ');
  }

  trackHistory(_: number, record: RepackagingRecordSummary): number {
    return record.repackaging_id;
  }

  trackAudit(_: number, row: RepackagingAuditRow): number {
    return row.repackaging_audit_id;
  }

  private loadPageData(): void {
    this.loading.set(true);

    forkJoin({
      warehouses: this.replenishmentService.getAllWarehouses(),
      items: this.masterDataService.lookup('items'),
    })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: ({ warehouses, items }) => {
          this.warehouses.set(warehouses);
          this.items.set(items
            .map((item) => this.toItemLookupOption(item))
            .filter((option): option is ItemLookupOption => option != null));
          this.loading.set(false);
          this.loadHistory();
        },
        error: () => {
          this.loading.set(false);
          this.setSubmitError(
            'Failed to load repackaging prerequisites.',
            ['Warehouse and item lookups must load before the Sprint 07 repackaging flow can run.'],
          );
        },
      });
  }

  private watchFilters(): void {
    this.form.controls.warehouse_id.valueChanges
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(() => {
        this.clearSubmitError();
        this.clearAccessDenied();
        this.loadHistory();
      });

    this.form.controls.item_search.valueChanges
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((value) => {
        const selectedItem = this.selectedItem();
        if (!selectedItem) {
          return;
        }

        const normalized = String(value ?? '').trim();
        const currentLabel = selectedItem.itemCode
          ? `${selectedItem.itemCode} - ${selectedItem.itemName}`
          : selectedItem.itemName;
        if (normalized === currentLabel) {
          return;
        }

        if (!normalized) {
          this.form.patchValue({ item_id: 0 }, { emitEvent: false });
          this.selectedItem.set(null);
        }
      });

    this.form.controls.item_id.valueChanges
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((itemId) => {
        if (itemId > 0) {
          this.loadHistory();
        }
      });
  }

  private watchRoute(): void {
    this.route.paramMap
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((params) => {
        const recordId = this.toPositiveInt(params.get('repackagingId'));
        if (!recordId) {
          this.selectedRecord.set(null);
          return;
        }
        this.loadDetail(recordId);
      });
  }

  private watchFormChanges(): void {
    this.form.valueChanges
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(() => {
        if (this.submitError()) {
          this.clearSubmitError();
        }
        this.clearServerErrors();
      });
  }

  private loadItemContext(itemId: number, fallbackLabel = ''): void {
    this.itemLoading.set(true);
    this.clearSubmitError();
    this.clearAccessDenied();

    this.masterDataService.get('items', itemId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (response) => {
          const context = this.toItemContext(response.record, fallbackLabel);
          this.selectedItem.set(context);
          this.itemLoading.set(false);

          const defaultSourceUom = context.defaultUomCode
            || context.uomOptions.find((option) => option.isDefault)?.uomCode
            || '';
          const currentTarget = this.form.controls.target_uom_code.value;
          const nextTarget = currentTarget && currentTarget !== defaultSourceUom
            ? currentTarget
            : '';

          this.form.patchValue({
            source_uom_code: defaultSourceUom,
            target_uom_code: nextTarget,
            batch_id: null,
            batch_or_lot: '',
          }, { emitEvent: false });

          this.loadHistory();
        },
        error: () => {
          this.itemLoading.set(false);
          this.selectedItem.set(null);
          this.setSubmitError(
            'Failed to load item UOM conversions.',
            ['The selected item could not be prepared for Sprint 07 repackaging.'],
          );
        },
      });
  }

  private loadHistory(): void {
    this.historyLoading.set(true);

    this.replenishmentService.listRepackagingTransactions({
      warehouse_id: this.toPositiveInt(this.form.controls.warehouse_id.value) ?? undefined,
      item_id: this.toPositiveInt(this.form.controls.item_id.value) ?? undefined,
      limit: DEFAULT_LIMIT,
      offset: 0,
    })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (response) => {
          this.historyLoading.set(false);
          this.history.set(response.results ?? []);
          this.pageWarnings.set(response.warnings ?? []);
        },
        error: (error: HttpErrorResponse) => {
          this.historyLoading.set(false);
          this.history.set([]);
          if (error.status === 403) {
            this.accessDenied.set('You do not have permission to view repackaging history for this scope.');
          }
        },
      });
  }

  private loadDetail(recordId: number): void {
    this.detailLoading.set(true);
    this.clearAccessDenied();

    this.replenishmentService.getRepackagingTransaction(recordId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (response) => {
          this.detailLoading.set(false);
          this.selectedRecord.set(response.record);
          this.pageWarnings.set(response.warnings ?? []);
        },
        error: (error: HttpErrorResponse) => {
          this.detailLoading.set(false);
          this.selectedRecord.set(null);
          if (error.status === 403) {
            this.accessDenied.set('You do not have permission to view this repackaging transaction.');
            return;
          }
          this.setSubmitError(
            'Failed to load the repackaging transaction.',
            [this.extractFallbackMessage(error, 'Open the history list and retry the selected transaction.')],
          );
        },
      });
  }

  private buildLocalValidationMessages(): string[] {
    const messages: string[] = [];
    const sourceUom = this.form.controls.source_uom_code.value.trim();
    const targetUom = this.form.controls.target_uom_code.value.trim();
    const sourceQty = Number(this.form.controls.source_qty.value);
    const batchId = this.toPositiveInt(this.form.controls.batch_id.value);
    const batchOrLot = this.form.controls.batch_or_lot.value.trim();

    if (sourceUom && targetUom && sourceUom === targetUom) {
      messages.push('Source and target UOM must be different.');
    }

    if (Number.isFinite(sourceQty) && sourceQty <= 0) {
      messages.push('Source quantity must be greater than zero.');
    }

    if (this.requiresBatchContext() && !batchId && !batchOrLot) {
      messages.push('Batch ID or batch / lot reference is required for batched or expiring items.');
    }

    if (!this.requiresBatchContext() && (batchId || batchOrLot)) {
      messages.push('Batch ID and batch / lot are only allowed for batched or expiring items.');
    }

    const preview = this.buildPreviewSummary();
    if (sourceUom && targetUom && !preview && !messages.length) {
      messages.push('The selected UOM combination is not configured for this item.');
    }

    return messages;
  }

  private buildPreviewSummary(): PreviewSummary | null {
    const item = this.selectedItem();
    if (!item) {
      return null;
    }

    const sourceUom = this.form.controls.source_uom_code.value.trim();
    const targetUom = this.form.controls.target_uom_code.value.trim();
    const sourceQty = Number(this.form.controls.source_qty.value);
    if (!sourceUom || !targetUom || !Number.isFinite(sourceQty) || sourceQty <= 0) {
      return null;
    }

    const sourceOption = item.uomOptions.find((option) => option.uomCode === sourceUom);
    const targetOption = item.uomOptions.find((option) => option.uomCode === targetUom);
    if (!sourceOption || !targetOption) {
      return null;
    }

    const equivalentDefaultQty = sourceQty * sourceOption.conversionFactor;
    const targetQty = equivalentDefaultQty / targetOption.conversionFactor;
    if (!Number.isFinite(targetQty) || targetQty <= 0) {
      return null;
    }

    return {
      sourceFactor: sourceOption.conversionFactor,
      targetFactor: targetOption.conversionFactor,
      targetQty,
      equivalentDefaultQty,
    };
  }

  private buildCreatePayload(preview: PreviewSummary): CreateRepackagingPayload | null {
    const warehouseId = this.toPositiveInt(this.form.controls.warehouse_id.value);
    const itemId = this.toPositiveInt(this.form.controls.item_id.value);
    const sourceQty = Number(this.form.controls.source_qty.value);
    const reasonCode = this.form.controls.reason_code.value.trim();
    const sourceUom = this.form.controls.source_uom_code.value.trim();
    const targetUom = this.form.controls.target_uom_code.value.trim();

    if (!warehouseId || !itemId || !reasonCode || !sourceUom || !targetUom || !Number.isFinite(sourceQty) || sourceQty <= 0) {
      return null;
    }

    const payload: CreateRepackagingPayload = {
      warehouse_id: warehouseId,
      item_id: itemId,
      source_uom_code: sourceUom,
      source_qty: sourceQty,
      target_uom_code: targetUom,
      reason_code: reasonCode,
      target_qty: preview.targetQty,
      equivalent_default_qty: preview.equivalentDefaultQty,
    };

    const noteText = this.form.controls.note_text.value.trim();
    if (noteText) {
      payload.note_text = noteText;
    }

    const batchId = this.toPositiveInt(this.form.controls.batch_id.value);
    const batchOrLot = this.form.controls.batch_or_lot.value.trim();
    if (batchId) {
      payload.batch_id = batchId;
    }
    if (batchOrLot) {
      payload.batch_or_lot = batchOrLot;
    }

    return payload;
  }

  private handleApiError(error: HttpErrorResponse, fallbackTitle: string): void {
    if (error.status === 403) {
      this.accessDenied.set('You do not have permission to execute repackaging transactions.');
    }

    const payload = (error.error && typeof error.error === 'object') ? error.error as Record<string, unknown> : {};
    const title = this.readString(payload['detail']) || this.extractFallbackMessage(error, fallbackTitle);
    const details: string[] = [];

    const diagnostic = this.readString(payload['diagnostic']);
    if (diagnostic) {
      details.push(`Diagnostic: ${diagnostic}`);
    }

    const warnings = Array.isArray(payload['warnings'])
      ? payload['warnings']
        .map((warning) => this.readString(warning))
        .filter((warning): warning is string => Boolean(warning))
      : [];

    const errors = payload['errors'];
    if (errors && typeof errors === 'object' && !Array.isArray(errors)) {
      for (const [key, value] of Object.entries(errors as Record<string, unknown>)) {
        const fieldMessage = this.extractFieldErrorMessage(key, value);
        if (fieldMessage) {
          const control = this.form.controls[key as keyof typeof this.form.controls];
          if (control) {
            control.setErrors({ ...(control.errors || {}), server: fieldMessage });
            control.markAsTouched();
            continue;
          }
        }

        details.push(this.formatBackendErrorDetail(key, value));
      }
    }

    for (const warning of warnings) {
      if (!details.includes(warning) && warning !== title) {
        details.push(warning);
      }
    }

    this.setSubmitError(title, details);
    this.notifications.showError(title);
  }

  private extractFieldErrorMessage(key: string, value: unknown): string | null {
    const control = this.form.controls[key as keyof typeof this.form.controls];
    if (!control) {
      return null;
    }

    if (typeof value === 'string') {
      return value;
    }
    if (Array.isArray(value)) {
      return value.map((entry) => this.readString(entry)).filter(Boolean).join(' ');
    }
    return null;
  }

  private formatBackendErrorDetail(code: string, value: unknown): string {
    if (code === 'same_uom_not_allowed') {
      return 'Source and target UOM must be different for create-only repackaging.';
    }

    if (code === 'insufficient_stock' && value && typeof value === 'object') {
      const payload = value as Record<string, unknown>;
      const available = this.readString(payload['available_default_qty']) ?? 'unknown';
      const required = this.readString(payload['required_default_qty']) ?? 'unknown';
      return `Insufficient stock: available default qty ${available}, required default qty ${required}.`;
    }

    if (code === 'invalid_uom_mapping' && value && typeof value === 'object') {
      const payload = value as Record<string, unknown>;
      const missingCodes = Array.isArray(payload['missing_uom_codes'])
        ? payload['missing_uom_codes']
          .map((entry) => this.readString(entry))
          .filter((entry): entry is string => Boolean(entry))
        : [];
      return missingCodes.length > 0
        ? `Missing UOM mapping: ${missingCodes.join(', ')}.`
        : 'The selected UOM mapping is not configured for this item.';
    }

    if (typeof value === 'string') {
      return value;
    }

    if (Array.isArray(value)) {
      const messages = value.map((entry) => this.readString(entry)).filter((entry): entry is string => Boolean(entry));
      if (messages.length > 0) {
        return messages.join(' ');
      }
    }

    return `${this.humanizeToken(code)} failed.`;
  }

  private toItemLookupOption(item: LookupItem): ItemLookupOption | null {
    const itemId = this.toPositiveInt(item['value']);
    if (!itemId) {
      return null;
    }

    const itemCode = this.readString(item['item_code']) ?? '';
    const itemName = this.readString(item['item_name']) ?? this.readString(item['label']) ?? `Item ${itemId}`;
    const label = itemCode ? `${itemCode} - ${itemName}` : itemName;

    return {
      itemId,
      itemCode,
      itemName,
      label,
    };
  }

  private toItemContext(record: MasterRecord, fallbackLabel: string): ItemContext {
    const uomOptions = Array.isArray(record['uom_options'])
      ? record['uom_options']
        .map((entry) => this.toItemUomOption(entry))
        .filter((entry): entry is ItemUomOption => entry != null)
      : [];

    const fallbackName = fallbackLabel.split(' - ').slice(-1)[0] ?? fallbackLabel;
    const defaultUom = this.readString(record['default_uom_code'])
      ?? uomOptions.find((option) => option.isDefault)?.uomCode
      ?? '';

    return {
      itemId: this.toPositiveInt(record['item_id']) ?? this.toPositiveInt(record['value']) ?? 0,
      itemCode: this.readString(record['item_code']) ?? '',
      itemName: this.readString(record['item_name']) ?? fallbackName ?? 'Selected item',
      defaultUomCode: defaultUom,
      isBatched: this.readBoolean(record['is_batched_flag']),
      canExpire: this.readBoolean(record['can_expire_flag']),
      uomOptions,
    };
  }

  private toItemUomOption(value: unknown): ItemUomOption | null {
    if (!value || typeof value !== 'object') {
      return null;
    }

    const option = value as Record<string, unknown>;
    const uomCode = this.readString(option['uom_code']);
    const conversionFactor = this.toPositiveNumber(option['conversion_factor']);
    if (!uomCode || conversionFactor == null) {
      return null;
    }

    return {
      uomCode,
      conversionFactor,
      isDefault: this.readBoolean(option['is_default']) || conversionFactor === 1,
    };
  }

  private setSubmitError(title: string, details: string[]): void {
    this.submitError.set({
      title,
      details: [...new Set(details.filter((detail) => detail.trim().length > 0))],
    });
  }

  private clearSubmitError(): void {
    this.submitError.set(null);
  }

  private clearAccessDenied(): void {
    this.accessDenied.set(null);
  }

  private clearServerErrors(): void {
    Object.values(this.form.controls).forEach((control) => {
      if (!control.errors?.['server']) {
        return;
      }

      const nextErrors = { ...(control.errors || {}) };
      delete nextErrors['server'];
      control.setErrors(Object.keys(nextErrors).length ? nextErrors : null);
    });
  }

  private toPositiveInt(value: unknown): number | null {
    if (value == null || value === '') {
      return null;
    }
    const numeric = Number(value);
    return Number.isInteger(numeric) && numeric > 0 ? numeric : null;
  }

  private toPositiveNumber(value: unknown): number | null {
    if (value == null || value === '') {
      return null;
    }
    const numeric = Number(value);
    return Number.isFinite(numeric) && numeric > 0 ? numeric : null;
  }

  private readString(value: unknown): string | null {
    const normalized = String(value ?? '').trim();
    return normalized.length > 0 ? normalized : null;
  }

  private readBoolean(value: unknown): boolean {
    if (typeof value === 'boolean') {
      return value;
    }
    const normalized = String(value ?? '').trim().toLowerCase();
    return normalized === 'true' || normalized === '1' || normalized === 'y';
  }

  private humanizeToken(value: string): string {
    return String(value ?? '')
      .trim()
      .split('_')
      .filter(Boolean)
      .map((token) => token.charAt(0).toUpperCase() + token.slice(1).toLowerCase())
      .join(' ');
  }

  private extractFallbackMessage(error: HttpErrorResponse, fallback: string): string {
    const apiMessage = this.readString((error.error as { message?: unknown })?.message);
    const statusText = this.readString(error.statusText);
    return apiMessage || statusText || fallback;
  }
}
