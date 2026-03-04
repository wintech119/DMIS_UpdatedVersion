import {
  Component, OnInit, DestroyRef, ChangeDetectionStrategy,
  inject, signal, computed,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
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

  isActive = computed(() => {
    const r = this.record();
    const cfg = this.config();
    if (!r || !cfg) return false;
    return r[cfg.statusField || 'status_code'] === 'A';
  });

  /** Group form fields for display sections */
  fieldGroups = computed(() => {
    const cfg = this.config();
    if (!cfg) return [];
    const groups: { label: string; fields: MasterFieldConfig[] }[] = [];
    const seen = new Map<string, MasterFieldConfig[]>();

    for (const f of cfg.formFields) {
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
    if (cfg && this.pk()) {
      this.router.navigate(['/master-data', cfg.routePath, this.pk(), 'edit']);
    }
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
  getSectionIcon(groupLabel: string): string {
    const iconMap: Record<string, string> = {
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
    };
    return iconMap[groupLabel] || 'folder';
  }

  getDisplayValue(field: MasterFieldConfig, value: unknown): string {
    if (value == null || value === '') return '-';
    if (field.type === 'boolean') return value ? 'Yes' : 'No';
    if (field.type === 'select' && field.options) {
      const opt = field.options.find(o => o.value === value);
      return opt?.label || String(value);
    }
    return String(value);
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

  navigateBack(): void {
    const cfg = this.config();
    if (cfg) {
      this.router.navigate(['/master-data', cfg.routePath]);
    }
  }
}
