import {
  Component, OnInit, DestroyRef, ChangeDetectionStrategy,
  inject, signal, computed,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Clipboard } from '@angular/cdk/clipboard';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatProgressBarModule } from '@angular/material/progress-bar';

import { CatalogEditGuidance, MasterFieldConfig, MasterRecord, MasterTableConfig } from '../../models/master-data.models';
import { ALL_TABLE_CONFIGS } from '../../models/table-configs';
import { MasterDataService } from '../../services/master-data.service';
import { MasterEditGateService } from '../../services/master-edit-gate.service';
import { DmisNotificationService } from '../../../replenishment/services/notification.service';
import {
  ReplenishmentService,
  StorageAssignmentOption,
  StorageAssignmentOptionsResponse,
} from '../../../replenishment/services/replenishment.service';
import { DmisConfirmDialogComponent, ConfirmDialogData } from '../../../replenishment/shared/dmis-confirm-dialog/dmis-confirm-dialog.component';
import { MasterEditGateDialogComponent } from '../master-edit-gate-dialog/master-edit-gate-dialog.component';

@Component({
  selector: 'dmis-master-detail-page',
  standalone: true,
  imports: [
    CommonModule, RouterModule, ReactiveFormsModule,
    MatButtonModule, MatIconModule, MatCardModule, MatTooltipModule,
    MatDialogModule, MatProgressBarModule, MatFormFieldModule, MatInputModule, MatSelectModule,
  ],
  templateUrl: './master-detail-page.component.html',
  styleUrl: './master-detail-page.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MasterDetailPageComponent implements OnInit {
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private service = inject(MasterDataService);
  private editGate = inject(MasterEditGateService);
  private replenishmentService = inject(ReplenishmentService);
  private notify = inject(DmisNotificationService);
  private dialog = inject(MatDialog);
  private clipboard = inject(Clipboard);
  private destroyRef = inject(DestroyRef);
  private latestRecordRequestId = 0;
  private latestStorageAssignmentRequestId = 0;

  config = signal<MasterTableConfig | null>(null);
  record = signal<MasterRecord | null>(null);
  editGuidance = signal<CatalogEditGuidance | null>(null);
  isLoading = signal(true);
  pk = signal<string | number | null>(null);
  assigningLocation = signal(false);
  storageAssignmentLoading = signal(false);
  storageAssignmentError = signal<string | null>(null);
  storageAssignmentOptions = signal<StorageAssignmentOptionsResponse | null>(null);
  private readonly locationFormVersion = signal(0);

  locationForm = new FormGroup({
    inventory_id: new FormControl<number | null>(null, [
      Validators.required,
      Validators.min(1),
    ]),
    location_id: new FormControl<number | null>(null, [
      Validators.required,
      Validators.min(1),
    ]),
    batch_id: new FormControl<number | null>(null, [Validators.min(1)]),
  });

  isItemRecord = computed(() => this.config()?.tableKey === 'items');
  isBatchedItem = computed(() => Boolean(this.record()?.['is_batched_flag']));
  inventoryAssignmentOptions = computed<StorageAssignmentOption[]>(() => (
    this.storageAssignmentOptions()?.inventories ?? []
  ));
  selectedAssignmentInventoryId = computed<number | null>(() => {
    this.locationFormVersion();
    return this.toPositiveInt(this.locationForm.controls.inventory_id.value);
  });
  locationAssignmentOptions = computed<StorageAssignmentOption[]>(() => {
    const inventoryId = this.selectedAssignmentInventoryId();
    const options = this.storageAssignmentOptions()?.locations ?? [];
    if (inventoryId == null) {
      return [];
    }
    return options.filter((option) => this.toPositiveInt(option.inventory_id) === inventoryId);
  });
  batchAssignmentOptions = computed<StorageAssignmentOption[]>(() => {
    const inventoryId = this.selectedAssignmentInventoryId();
    const options = this.storageAssignmentOptions()?.batches ?? [];
    if (inventoryId == null) {
      return [];
    }
    return options.filter((option) => this.toPositiveInt(option.inventory_id) === inventoryId);
  });

  auditExpanded = signal(false);

  isActive = computed(() => {
    const r = this.record();
    const cfg = this.config();
    if (!r || !cfg) return false;
    return r[cfg.statusField || 'status_code'] === 'A';
  });

  readonly recordTitle = computed(() => {
    return this.editGate.getRecordTitle(this.record(), this.config(), this.pk());
  });

  readonly statusGroup = computed(() => {
    const cfg = this.config();
    if (!cfg || cfg.hasStatus === false) return null;
    const includedFields = new Set<string>();
    const statusFieldName = cfg.statusField || 'status_code';
    const statusFields = cfg.formFields.filter((field) => {
      const shouldInclude = field.group === 'Status' || field.field === statusFieldName;
      if (!shouldInclude || includedFields.has(field.field)) {
        return false;
      }
      includedFields.add(field.field);
      return true;
    });
    if (statusFields.length === 0) return null;
    return statusFields;
  });

  /** Group form fields for display sections */
  fieldGroups = computed(() => {
    const cfg = this.config();
    if (!cfg) return [];
    const groups: { label: string; fields: MasterFieldConfig[] }[] = [];
    const seen = new Map<string, MasterFieldConfig[]>();

    for (const f of cfg.formFields) {
      if (f.group === 'Status') continue;
      const groupLabel = f.group || 'General';
      if (!seen.has(groupLabel)) {
        seen.set(groupLabel, []);
        groups.push({ label: groupLabel, fields: seen.get(groupLabel)! });
      }
      seen.get(groupLabel)!.push(f);
    }
    return groups;
  });

  ngOnInit(): void {
    this.locationForm.valueChanges.pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(() => {
      this.locationFormVersion.update((version) => version + 1);
    });

    this.locationForm.controls.inventory_id.valueChanges.pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(() => {
      this.locationForm.controls.location_id.setValue(null, { emitEvent: false });
      this.locationForm.controls.batch_id.setValue(null, { emitEvent: false });
      this.locationFormVersion.update((version) => version + 1);
    });

    this.route.data.pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(data => {
      const routePath = data['routePath'] as string;
      const cfg = ALL_TABLE_CONFIGS[routePath];
      if (cfg) {
        this.config.set(cfg);
        if (cfg.tableKey !== 'items') {
          this.resetStorageAssignmentState();
        }
      }
    });

    this.route.params.pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(params => {
      const pkParam = params['pk'];
      if (pkParam) {
        this.pk.set(pkParam);
        this.loadRecord();
      }
    });
  }

  private loadRecord(): void {
    const cfg = this.config();
    if (!cfg || !this.pk()) return;

    const requestId = ++this.latestRecordRequestId;
    this.isLoading.set(true);
    this.service.get(cfg.tableKey, this.pk()!).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: res => {
        if (requestId !== this.latestRecordRequestId) return;
        this.record.set(res.record);
        this.editGuidance.set(this.editGate.getEffectiveCatalogEditGuidance(cfg, res.edit_guidance));
        this.loadStorageAssignmentOptions(this.toPositiveInt(res.record['item_id']) ?? null);
        this.isLoading.set(false);
      },
      error: () => {
        if (requestId !== this.latestRecordRequestId) return;
        this.isLoading.set(false);
        this.notify.showError('Record not found.');
        this.navigateBack();
      },
    });
  }

  onEdit(): void {
    const cfg = this.config();
    if (!cfg || !this.pk()) return;

    const dialogRef = this.dialog.open(MasterEditGateDialogComponent, {
      data: this.editGate.buildDialogData({
        config: cfg,
        recordName: this.recordTitle(),
        editGuidance: this.editGuidance(),
        isEdit: true,
      }),
      width: '460px',
      panelClass: 'dmis-edit-gate-panel',
      autoFocus: 'first-tabbable',
      ariaLabelledBy: 'gate-dialog-title',
    });

    dialogRef.afterClosed().pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(confirmed => {
      if (confirmed) {
        if (this.editGate.isGovernedCatalogTable(cfg.tableKey)) {
          this.editGate.markDetailEditGatePassed();
        }
        this.router.navigate(['/master-data', cfg.routePath, this.pk(), 'edit']);
      }
    });
  }

  onAssignStorageLocation(): void {
    if (!this.isItemRecord()) return;

    const currentRecord = this.record();
    const itemId = this.toPositiveInt(currentRecord?.['item_id']);
    if (!itemId) {
      this.notify.showError('Cannot assign location: invalid item ID.');
      return;
    }

    this.clearLocationServerErrors();

    if (this.locationForm.invalid) {
      this.locationForm.markAllAsTouched();
      return;
    }

    const inventoryId = this.toPositiveInt(this.locationForm.controls.inventory_id.value);
    const locationId = this.toPositiveInt(this.locationForm.controls.location_id.value);
    const batchId = this.toPositiveInt(this.locationForm.controls.batch_id.value);

    if (!inventoryId || !locationId) {
      this.locationForm.markAllAsTouched();
      return;
    }

    if (this.isBatchedItem() && !batchId) {
      this.locationForm.controls.batch_id.setErrors({ required: true });
      this.locationForm.controls.batch_id.markAsTouched();
      this.notify.showWarning('Select a batch or lot for batched items.');
      return;
    }

    if (!this.isBatchedItem() && batchId) {
      this.notify.showWarning('Batch or lot must stay empty for non-batched items.');
      this.locationForm.controls.batch_id.setErrors({ server: 'Must stay empty for non-batched items.' });
      this.locationForm.controls.batch_id.markAsTouched();
      return;
    }

    const payload: {
      item_id: number;
      inventory_id: number;
      location_id: number;
      batch_id?: number;
    } = {
      item_id: itemId,
      inventory_id: inventoryId,
      location_id: locationId,
    };
    if (batchId) {
      payload.batch_id = batchId;
    }

    this.assigningLocation.set(true);
    this.replenishmentService.assignStorageLocation(payload).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: (response) => {
        this.assigningLocation.set(false);
        const action = response.created ? 'saved' : 'already exists';
        this.notify.showSuccess(
          `Location assignment ${action} in ${response.storage_table}.`
        );
      },
      error: (err) => {
        this.assigningLocation.set(false);
        this.applyLocationAssignmentErrors(err?.error?.errors);
      },
    });
  }

  onToggleStatus(): void {
    const cfg = this.config();
    const r = this.record();
    if (!cfg || !r) return;
    const versionNbr = this.coerceVersionNumber(r['version_nbr']);

    if (this.isActive()) {
      const dialogRef = this.dialog.open(DmisConfirmDialogComponent, {
        data: {
          title: 'Confirm Inactivation',
          message: 'Are you sure you want to inactivate this record?',
          confirmLabel: 'Inactivate',
          cancelLabel: 'Cancel',
          icon: 'block',
          iconColor: '#f44336',
          confirmColor: 'warn',
        } as ConfirmDialogData,
        width: '400px',
      });
      dialogRef.afterClosed().pipe(
        takeUntilDestroyed(this.destroyRef),
      ).subscribe(confirmed => {
        if (confirmed) {
          this.service.inactivate(cfg.tableKey, this.pk()!, versionNbr).pipe(
            takeUntilDestroyed(this.destroyRef),
          ).subscribe({
            next: () => {
              this.notify.showSuccess('Record inactivated.');
              this.loadRecord();
            },
            error: (err) => {
              const blocking = err.error?.blocking;
              if (blocking?.length) {
                this.notify.showError(`Cannot inactivate: referenced by ${blocking.join(', ')}`);
              } else {
                this.notify.showError(err.error?.detail || 'Inactivation failed.');
              }
            },
          });
        }
      });
    } else {
      this.service.activate(cfg.tableKey, this.pk()!, versionNbr).pipe(
        takeUntilDestroyed(this.destroyRef),
      ).subscribe({
        next: () => {
          this.notify.showSuccess('Record activated.');
          this.loadRecord();
        },
        error: () => this.notify.showError('Activation failed.'),
      });
    }
  }

  /** Map section group labels to Material icons */
  private readonly sectionIconMap: Record<string, string> = {
    'Basic Information': 'info',
    'General': 'info',
    'Details': 'description',
    'Contact': 'contact_phone',
    'Contact Information': 'contact_phone',
    'Address': 'location_on',
    'Location': 'location_on',
    'Status': 'toggle_on',
    'Inventory Settings': 'inventory_2',
    'Procurement': 'shopping_cart',
    'Financial': 'payments',
    'Item Identity': 'label',
    'Classification': 'category',
    'Inventory Rules': 'inventory_2',
    'Tracking & Behaviour': 'track_changes',
    'Notes & Storage': 'notes',
  };

  getSectionIcon(groupLabel: string): string {
    return this.sectionIconMap[groupLabel] || 'folder';
  }

  getDisplayValue(field: MasterFieldConfig, value: unknown): string {
    const record = this.record();
    const companionDisplayValue = field.displayField && record
      ? record[field.displayField]
      : undefined;
    const displayValue = companionDisplayValue != null && companionDisplayValue !== ''
      ? companionDisplayValue
      : value;

    if (displayValue == null || displayValue === '') return '-';
    if (field.type === 'boolean') return displayValue ? 'Yes' : 'No';
    if (field.type === 'select' && field.options) {
      const opt = field.options.find((option) => option.value === displayValue);
      return opt?.label || String(displayValue);
    }
    return String(displayValue);
  }

  getStatusLabel(): string {
    const r = this.record();
    const cfg = this.config();
    if (!r || !cfg) return '';
    const val = r[cfg.statusField || 'status_code'];
    if (val === 'A') return cfg.activeLabel || 'Active';
    return cfg.inactiveLabel || 'Inactive';
  }

  getAuditCreatedAt(record: MasterRecord): string | number | Date | null {
    return this.toDateInput(record['create_dtime'] ?? record['created_at']);
  }

  getAuditUpdatedAt(record: MasterRecord): string | number | Date | null {
    return this.toDateInput(record['update_dtime'] ?? record['updated_at']);
  }

  getLocationFieldError(fieldName: 'inventory_id' | 'location_id' | 'batch_id'): string | null {
    const control = this.locationForm.controls[fieldName];
    if (!control || !control.touched || !control.errors) return null;
    if (control.errors['required']) {
      if (fieldName === 'inventory_id') return 'Select a warehouse.';
      if (fieldName === 'location_id') return 'Select a location.';
      return 'Select a batch or lot.';
    }
    if (control.errors['min']) return 'Must be a positive number.';
    if (control.errors['server']) return String(control.errors['server']);
    return 'Invalid value.';
  }

  getStorageAssignmentOptionDetail(option: StorageAssignmentOption): string | null {
    const detail = String(option.detail ?? '').trim();
    return detail || null;
  }

  private toPositiveInt(value: unknown): number | null {
    if (value == null || value === '') return null;
    const parsed = Number(value);
    if (!Number.isInteger(parsed) || parsed <= 0) return null;
    return parsed;
  }

  private toDateInput(value: unknown): string | number | Date | null {
    if (value == null) return null;
    if (value instanceof Date) return value;
    if (typeof value === 'string' || typeof value === 'number') return value;
    return null;
  }

  private coerceVersionNumber(value: unknown): number | undefined {
    return typeof value === 'number' ? value : undefined;
  }

  private clearLocationServerErrors(): void {
    const controls = this.locationForm.controls;
    for (const control of [controls.inventory_id, controls.location_id, controls.batch_id]) {
      if (!control.errors?.['server']) continue;
      const nextErrors = { ...control.errors };
      delete nextErrors['server'];
      const remaining = Object.keys(nextErrors).length ? nextErrors : null;
      control.setErrors(remaining);
    }
  }

  private applyLocationAssignmentErrors(rawErrors: unknown): void {
    if (!rawErrors || typeof rawErrors !== 'object') {
      this.notify.showError('Failed to assign storage location.');
      return;
    }

    const errors = rawErrors as Record<string, unknown>;
    let fallbackMessage: string | null = null;

    for (const [key, value] of Object.entries(errors)) {
      const message = String(value);
      if (key === 'inventory_id' || key === 'location_id' || key === 'batch_id') {
        this.locationForm.controls[key].setErrors({ server: message });
        this.locationForm.controls[key].markAsTouched();
      } else if (!fallbackMessage) {
        fallbackMessage = message;
      }
    }

    this.notify.showError(fallbackMessage || 'Storage location assignment failed.');
  }

  private resetStorageAssignmentState(): void {
    this.latestStorageAssignmentRequestId += 1;
    this.storageAssignmentLoading.set(false);
    this.storageAssignmentError.set(null);
    this.storageAssignmentOptions.set(null);
    this.locationForm.reset(
      {
        inventory_id: null,
        location_id: null,
        batch_id: null,
      },
      { emitEvent: false },
    );
    this.locationForm.markAsPristine();
    this.locationForm.markAsUntouched();
    this.locationFormVersion.update((version) => version + 1);
  }

  private loadStorageAssignmentOptions(itemId: number | null): void {
    if (!this.isItemRecord() || itemId == null) {
      this.resetStorageAssignmentState();
      return;
    }

    const requestId = ++this.latestStorageAssignmentRequestId;
    this.storageAssignmentLoading.set(true);
    this.storageAssignmentError.set(null);
    this.replenishmentService.getStorageAssignmentOptions(itemId).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: (options) => {
        if (requestId !== this.latestStorageAssignmentRequestId || options.item_id !== itemId) {
          return;
        }
        this.storageAssignmentLoading.set(false);
        this.storageAssignmentOptions.set(options);
        this.storageAssignmentError.set(null);
        this.syncStorageAssignmentSelections();
      },
      error: (err) => {
        if (requestId !== this.latestStorageAssignmentRequestId) {
          return;
        }
        this.storageAssignmentLoading.set(false);
        this.storageAssignmentOptions.set(null);
        this.storageAssignmentError.set(
          String(err?.error?.detail || 'Failed to load storage assignment choices.'),
        );
      },
    });
  }

  private syncStorageAssignmentSelections(): void {
    const inventoryId = this.toPositiveInt(this.locationForm.controls.inventory_id.value);
    if (inventoryId == null) {
      return;
    }

    if (!this.hasStorageOption(this.inventoryAssignmentOptions(), inventoryId)) {
      this.locationForm.reset(
        {
          inventory_id: null,
          location_id: null,
          batch_id: null,
        },
        { emitEvent: false },
      );
      this.locationFormVersion.update((version) => version + 1);
      return;
    }

    const locationId = this.toPositiveInt(this.locationForm.controls.location_id.value);
    if (locationId != null && !this.hasStorageOption(this.locationAssignmentOptions(), locationId)) {
      this.locationForm.controls.location_id.setValue(null, { emitEvent: false });
    }

    const batchId = this.toPositiveInt(this.locationForm.controls.batch_id.value);
    if (batchId != null && !this.hasStorageOption(this.batchAssignmentOptions(), batchId)) {
      this.locationForm.controls.batch_id.setValue(null, { emitEvent: false });
    }

    this.locationFormVersion.update((version) => version + 1);
  }

  private hasStorageOption(options: StorageAssignmentOption[], value: number): boolean {
    return options.some((option) => this.toPositiveInt(option.value) === value);
  }

  isEmptyValue(value: unknown): boolean {
    return value == null || value === '';
  }

  isCopyableField(fieldName: string): boolean {
    return fieldName.endsWith('_code') || fieldName.endsWith('_id');
  }

  copyValue(value: unknown): void {
    if (value == null || value === '') return;
    const copied = this.clipboard.copy(String(value));
    if (copied) {
      this.notify.showSuccess('Copied to clipboard');
    }
  }

  navigateBack(): void {
    const cfg = this.config();
    if (cfg) {
      this.router.navigate(['/master-data', cfg.routePath]);
    }
  }
}

