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
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatProgressBarModule } from '@angular/material/progress-bar';

import { MasterFieldConfig, MasterRecord, MasterTableConfig } from '../../models/master-data.models';
import { ALL_TABLE_CONFIGS } from '../../models/table-configs';
import { MasterDataService } from '../../services/master-data.service';
import { DmisNotificationService } from '../../../replenishment/services/notification.service';
import { ReplenishmentService } from '../../../replenishment/services/replenishment.service';
import { DmisConfirmDialogComponent, ConfirmDialogData } from '../../../replenishment/shared/dmis-confirm-dialog/dmis-confirm-dialog.component';
import { MasterEditGateDialogComponent, EditGateDialogData } from '../master-edit-gate-dialog/master-edit-gate-dialog.component';

/** Maps table keys to downstream modules that depend on them */
const TABLE_IMPACT_MAP: Record<string, { modules: string[]; description: string }> = {
  items: {
    modules: ['Replenishment', 'Needs Lists', 'Transfers', 'Procurement', 'Donations', 'Stock Monitoring'],
    description: 'Changes to this item will propagate to all supply chain modules and active workflows.',
  },
  warehouses: {
    modules: ['Inventory', 'Replenishment', 'Transfers', 'Stock Monitoring'],
    description: 'Warehouse changes affect inventory tracking and active transfer operations.',
  },
  item_categories: {
    modules: ['Items', 'Classification', 'Replenishment'],
    description: 'Category changes cascade to all items in this classification group.',
  },
  uom: {
    modules: ['Items', 'Replenishment', 'Procurement'],
    description: 'Unit of measure changes affect quantity calculations across the system.',
  },
  agencies: {
    modules: ['Warehouses', 'Transfers', 'Events'],
    description: 'Agency changes affect associated warehouses and coordination assignments.',
  },
  events: {
    modules: ['Replenishment', 'Needs Lists', 'Stock Monitoring'],
    description: 'Event changes affect active response operations and planning windows.',
  },
  donors: {
    modules: ['Donations', 'Procurement'],
    description: 'Donor changes affect active and historical donation records.',
  },
  suppliers: {
    modules: ['Procurement'],
    description: 'Supplier changes affect active and pending procurement orders.',
  },
  ifrc_families: {
    modules: ['Items', 'Classification'],
    description: 'Changes to governed IFRC families cascade to item references and mapped items.',
  },
  ifrc_item_references: {
    modules: ['Items', 'Classification'],
    description: 'Changes to governed IFRC references affect all items mapped to this reference.',
  },
};

@Component({
  selector: 'dmis-master-detail-page',
  standalone: true,
  imports: [
    CommonModule, RouterModule, ReactiveFormsModule,
    MatButtonModule, MatIconModule, MatCardModule, MatTooltipModule,
    MatDialogModule, MatProgressBarModule, MatFormFieldModule, MatInputModule,
  ],
  templateUrl: './master-detail-page.component.html',
  styleUrl: './master-detail-page.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MasterDetailPageComponent implements OnInit {
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private service = inject(MasterDataService);
  private replenishmentService = inject(ReplenishmentService);
  private notify = inject(DmisNotificationService);
  private dialog = inject(MatDialog);
  private clipboard = inject(Clipboard);
  private destroyRef = inject(DestroyRef);
  private latestRecordRequestId = 0;

  config = signal<MasterTableConfig | null>(null);
  record = signal<MasterRecord | null>(null);
  isLoading = signal(true);
  pk = signal<string | number | null>(null);
  assigningLocation = signal(false);

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

  auditExpanded = signal(false);

  isActive = computed(() => {
    const r = this.record();
    const cfg = this.config();
    if (!r || !cfg) return false;
    return r[cfg.statusField || 'status_code'] === 'A';
  });

  readonly recordTitle = computed(() => {
    const r = this.record();
    const cfg = this.config();
    if (!r || !cfg) return '';

    const nameFields = [
      'item_name', 'warehouse_name', 'agency_name', 'event_name',
      'donor_name', 'supplier_name', 'custodian_name', 'country_name',
      'currency_name', 'parish_name', 'family_label', 'reference_desc',
      'category_desc', 'uom_desc', 'description', 'name',
      'item_code', 'category_code', 'uom_code', 'warehouse_code',
    ];

    for (const field of nameFields) {
      const val = r[field];
      if (val != null && String(val).trim()) return String(val).trim();
    }

    return `${cfg.displayName} ${this.pk()}`;
  });

  readonly statusGroup = computed(() => {
    const cfg = this.config();
    if (!cfg || cfg.hasStatus === false) return null;
    const statusFields = cfg.formFields.filter(f =>
      f.field === (cfg.statusField || 'status_code') ||
      (f.group === 'Status' && f.type === 'select')
    );
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
    this.route.data.pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(data => {
      const routePath = data['routePath'] as string;
      const cfg = ALL_TABLE_CONFIGS[routePath];
      if (cfg) this.config.set(cfg);
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

    const isGoverned = cfg.tableKey === 'ifrc_families' || cfg.tableKey === 'ifrc_item_references';
    const lockedFields = cfg.formFields
      .filter(f => f.readonlyOnEdit)
      .map(f => f.label);
    const impact = TABLE_IMPACT_MAP[cfg.tableKey];

    const dialogRef = this.dialog.open(MasterEditGateDialogComponent, {
      data: {
        recordName: this.recordTitle() || `${cfg.displayName} Record`,
        tableName: cfg.displayName,
        tableIcon: cfg.icon,
        warningText: isGoverned
          ? 'This record is under active governance. Modifications may require administrative approval and will be audited.'
          : `You are about to edit ${cfg.displayName.toLowerCase()} master data. Changes will be audited and may affect dependent modules.`,
        isGoverned,
        lockedFields,
        impactModules: impact?.modules ?? [],
        impactDescription: impact?.description ?? `Changes to this ${cfg.displayName.toLowerCase()} record will be tracked in the audit log.`,
      } as EditGateDialogData,
      width: '460px',
      panelClass: 'dmis-edit-gate-panel',
      autoFocus: 'first-tabbable',
    });

    dialogRef.afterClosed().pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(confirmed => {
      if (confirmed) {
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
      this.notify.showWarning('Batch ID is required for batched items.');
      return;
    }

    if (!this.isBatchedItem() && batchId) {
      this.notify.showWarning('Batch ID must be empty for non-batched items.');
      this.locationForm.controls.batch_id.setErrors({ server: 'Must be empty for non-batched items.' });
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
    if (control.errors['required']) return 'This field is required.';
    if (control.errors['min']) return 'Must be a positive number.';
    if (control.errors['server']) return String(control.errors['server']);
    return 'Invalid value.';
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

  isEmptyValue(value: unknown): boolean {
    return value == null || value === '';
  }

  isCopyableField(fieldName: string): boolean {
    return fieldName.endsWith('_code') || fieldName.endsWith('_id');
  }

  copyValue(value: unknown): void {
    if (value == null || value === '') return;
    this.clipboard.copy(String(value));
    this.notify.showSuccess('Copied to clipboard');
  }

  navigateBack(): void {
    const cfg = this.config();
    if (cfg) {
      this.router.navigate(['/master-data', cfg.routePath]);
    }
  }
}

