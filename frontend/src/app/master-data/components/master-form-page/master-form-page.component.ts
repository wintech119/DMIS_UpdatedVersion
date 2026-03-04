import {
  Component, OnInit, DestroyRef, ChangeDetectionStrategy,
  inject, signal, computed,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { ReactiveFormsModule, FormGroup, FormControl, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatDatepickerModule } from '@angular/material/datepicker';
import { MatNativeDateModule } from '@angular/material/core';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatCardModule } from '@angular/material/card';
import { MatTooltipModule } from '@angular/material/tooltip';

import { LookupItem, MasterFieldConfig, MasterTableConfig } from '../../models/master-data.models';
import { ALL_TABLE_CONFIGS } from '../../models/table-configs';
import { MasterDataService } from '../../services/master-data.service';
import { DmisNotificationService } from '../../../replenishment/services/notification.service';
import { ReplenishmentService } from '../../../replenishment/services/replenishment.service';

@Component({
  selector: 'master-form-page',
  standalone: true,
  imports: [
    CommonModule, ReactiveFormsModule, RouterModule,
    MatFormFieldModule, MatInputModule, MatSelectModule, MatButtonModule,
    MatIconModule, MatCheckboxModule, MatDatepickerModule, MatNativeDateModule,
    MatProgressBarModule, MatCardModule, MatTooltipModule,
  ],
  templateUrl: './master-form-page.component.html',
  styleUrl: './master-form-page.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MasterFormPageComponent implements OnInit {
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private service = inject(MasterDataService);
  private replenishmentService = inject(ReplenishmentService);
  private notify = inject(DmisNotificationService);
  private destroyRef = inject(DestroyRef);

  config = signal<MasterTableConfig | null>(null);
  form = new FormGroup<Record<string, FormControl>>({});
  isEdit = signal(false);
  isLoading = signal(false);
  isSaving = signal(false);
  assigningLocation = signal(false);
  lookups = signal<Record<string, LookupItem[]>>({});
  lookupErrors = signal<Record<string, string>>({});
  pk = signal<string | number | null>(null);

  private versionNbr: number | null = null;
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

  /** Group form fields by their group property */
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

  isItemRecord = computed(() => this.config()?.tableKey === 'items');
  isBatchedItem = computed(() => Boolean(this.form.get('is_batched_flag')?.value));
  canAssignLocation = computed(() => this.isItemRecord() && this.isEdit() && this.toPositiveInt(this.pk()) != null);

  ngOnInit(): void {
    this.route.data.pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(data => {
      const routePath = data['routePath'] as string;
      const cfg = ALL_TABLE_CONFIGS[routePath];
      if (cfg) {
        this.config.set(cfg);
        this.buildForm(cfg);
        this.loadLookups(cfg);
      }
    });

    this.route.params.pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(params => {
      const pkParam = params['pk'];
      if (pkParam && pkParam !== 'new') {
        this.pk.set(pkParam);
        this.isEdit.set(true);
        this.loadRecord();
      }
    });
  }

  private buildForm(cfg: MasterTableConfig): void {
    for (const field of cfg.formFields) {
      const validators = [];
      if (field.required) validators.push(Validators.required);
      if (field.maxLength) validators.push(Validators.maxLength(field.maxLength));
      if (field.pattern) validators.push(Validators.pattern(field.pattern));
      if (field.type === 'email') {
        validators.push(Validators.email);
      }

      this.form.addControl(
        field.field,
        new FormControl(field.defaultValue ?? null, validators),
      );
    }
  }

  private loadLookups(cfg: MasterTableConfig): void {
    const lookupFields = cfg.formFields.filter(f => f.type === 'lookup' && f.lookupTable);
    const lookupTables = new Map<string, string>();
    for (const field of lookupFields) {
      lookupTables.set(field.lookupTable!, field.label);
    }
    if (cfg.tableKey === 'items') {
      lookupTables.set('inventory', 'Inventory');
      lookupTables.set('locations', 'Location');
    }

    const loaded: Record<string, LookupItem[]> = {};
    this.lookupErrors.set({});

    for (const [tableKey, label] of lookupTables.entries()) {
      this.service.lookup(tableKey).pipe(
        takeUntilDestroyed(this.destroyRef),
      ).subscribe({
        next: items => {
          loaded[tableKey] = items;
          this.lookups.set({ ...loaded });

          if (this.lookupErrors()[tableKey]) {
            const nextErrors = { ...this.lookupErrors() };
            delete nextErrors[tableKey];
            this.lookupErrors.set(nextErrors);
          }
        },
        error: () => {
          loaded[tableKey] = [];
          this.lookups.set({ ...loaded });
          this.lookupErrors.set({
            ...this.lookupErrors(),
            [tableKey]: `Failed to load ${label} options.`,
          });
        },
      });
    }
  }

  private loadRecord(): void {
    const cfg = this.config();
    if (!cfg || !this.pk()) return;

    this.isLoading.set(true);
    this.service.get(cfg.tableKey, this.pk()!).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: res => {
        const record = res.record;
        this.versionNbr = record['version_nbr'] ?? null;

        for (const field of cfg.formFields) {
          const control = this.form.get(field.field);
          if (control && record[field.field] !== undefined) {
            control.setValue(record[field.field]);
          }
          if (field.readonlyOnEdit && this.isEdit() && control) {
            control.disable();
          }
        }
        this.isLoading.set(false);
      },
      error: () => {
        this.notify.showError('Failed to load record.');
        this.navigateBack();
      },
    });
  }

  onSave(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }

    const cfg = this.config();
    if (!cfg) return;

    this.isSaving.set(true);
    const rawData = this.form.getRawValue();

    // Apply uppercase transforms
    for (const field of cfg.formFields) {
      if (field.uppercase && typeof rawData[field.field] === 'string') {
        rawData[field.field] = rawData[field.field].trim().toUpperCase();
      }
    }

    const obs$ = this.isEdit()
      ? this.service.update(cfg.tableKey, this.pk()!, {
          ...rawData,
          ...(this.versionNbr != null ? { version_nbr: this.versionNbr } : {}),
        })
      : this.service.create(cfg.tableKey, rawData);

    obs$.pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: (res) => {
        this.notify.showSuccess(this.isEdit() ? 'Record updated.' : 'Record created.');
        this.service.clearLookupCache(cfg.tableKey);
        const newPk = res.record?.[cfg.pkField] || this.pk();
        if (this.isEdit()) {
          this.navigateBack();
        } else {
          this.router.navigate(['/master-data', cfg.routePath, newPk]);
        }
      },
      error: (err) => {
        this.isSaving.set(false);
        if (err.status === 400 && err.error?.errors) {
          const errors = err.error.errors as Record<string, string>;
          for (const [field, msg] of Object.entries(errors)) {
            const control = this.form.get(field);
            if (control) {
              control.setErrors({ server: msg });
              control.markAsTouched();
            }
          }
          this.notify.showWarning('Please fix the validation errors.');
        } else if (err.status === 409) {
          this.notify.showError(err.error?.detail || 'Record was modified by another user. Please reload.');
        } else {
          this.notify.showError(err.error?.detail || 'Save failed.');
        }
      },
    });
  }

  onAssignStorageLocation(): void {
    if (!this.canAssignLocation()) return;

    const itemId = this.toPositiveInt(this.pk());
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

  onCancel(): void {
    this.navigateBack();
  }

  getLocationFieldError(fieldName: 'inventory_id' | 'location_id' | 'batch_id'): string | null {
    const control = this.locationForm.controls[fieldName];
    if (!control || !control.touched || !control.errors) return null;
    if (control.errors['required']) return 'This field is required.';
    if (control.errors['min']) return 'Must be a positive number.';
    if (control.errors['server']) return String(control.errors['server']);
    return 'Invalid value.';
  }

  private navigateBack(): void {
    const cfg = this.config();
    if (cfg) {
      this.router.navigate(['/master-data', cfg.routePath]);
    }
  }

  private toPositiveInt(value: unknown): number | null {
    if (value == null || value === '') return null;
    const parsed = Number(value);
    if (!Number.isInteger(parsed) || parsed <= 0) return null;
    return parsed;
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
}
