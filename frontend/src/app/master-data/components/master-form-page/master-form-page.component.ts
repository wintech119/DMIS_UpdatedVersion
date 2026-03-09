import {
  Component, OnInit, DestroyRef, ChangeDetectionStrategy,
  inject, signal, computed,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { ReactiveFormsModule, FormGroup, FormControl, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { of, Subject } from 'rxjs';
import {
  catchError, debounceTime, distinctUntilChanged, finalize, map, switchMap,
} from 'rxjs/operators';
import { TextFieldModule } from '@angular/cdk/text-field';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatDatepickerModule } from '@angular/material/datepicker';
import { MatNativeDateModule } from '@angular/material/core';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatCardModule } from '@angular/material/card';
import { MatTooltipModule } from '@angular/material/tooltip';

import { LookupItem, MasterFieldConfig, MasterTableConfig } from '../../models/master-data.models';
import { ALL_TABLE_CONFIGS } from '../../models/table-configs';
import { MasterDataService } from '../../services/master-data.service';
import { IfrcSuggestService } from '../../services/ifrc-suggest.service';
import { DmisNotificationService } from '../../../replenishment/services/notification.service';
import { ReplenishmentService } from '../../../replenishment/services/replenishment.service';
import { validateFefoRequiresExpiry } from '../../models/table-configs/item.config';
import { IFRCSuggestion } from '../../models/ifrc-suggest.models';

interface InactiveItemForwardWriteGuard {
  table: string;
  workflow_state: string;
  item_ids: number[];
}

@Component({
  selector: 'dmis-master-form-page',
  standalone: true,
  imports: [
    CommonModule, ReactiveFormsModule, RouterModule,
    TextFieldModule,
    MatFormFieldModule, MatInputModule, MatSelectModule, MatButtonModule,
    MatIconModule, MatSlideToggleModule, MatDatepickerModule, MatNativeDateModule,
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
  private ifrcSuggestService = inject(IfrcSuggestService);
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
  ifrcLoading = signal(false);
  ifrcSuggestion = signal<IFRCSuggestion | null>(null);
  ifrcError = signal<string | null>(null);
  submissionError = signal<string | null>(null);
  submissionErrorDetails = signal<string[]>([]);
  pk = signal<string | number | null>(null);

  /** IFRC specification hint controls — not saved to DB, used only for code generation */
  ifrcSpecForm = new FormGroup({
    size_weight: new FormControl<string>(''),
    form: new FormControl<string>(''),
    material: new FormControl<string>(''),
  });

  private readonly ifrcTrigger$ = new Subject<string>();
  readonly formErrorMessages: Record<string, string> = {
    fefoRequiresExpiry: 'Can Expire must be enabled when Issuance Order is FEFO.',
    expiryRequiresFefo: 'Issuance Order must be FEFO when Can Expire is enabled.',
  };

  private versionNbr: number | null = null;
  private ifrcSuggestLogId: string | null = null;
  private itemCodeAutoFilled = false;
  private readonly inactiveItemForwardWriteCode = 'inactive_item_forward_write_blocked';
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
        this.setupItemIfrcSuggestion(cfg);
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

    if (cfg.tableKey === 'items') {
      this.form.setValidators(validateFefoRequiresExpiry);
      this.form.updateValueAndValidity({ emitEvent: false });
    }

    this.form.valueChanges.pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(() => {
      if (this.submissionError()) {
        this.clearSubmissionError();
      }
    });
  }

  private setupItemIfrcSuggestion(cfg: MasterTableConfig): void {
    this.ifrcSuggestion.set(null);
    this.ifrcError.set(null);
    this.ifrcSuggestLogId = null;
    this.itemCodeAutoFilled = false;

    if (cfg.tableKey !== 'items') return;

    const itemNameControl = this.form.get('item_name');
    const itemCodeControl = this.form.get('item_code');
    if (!itemNameControl || !itemCodeControl) return;

    // Reset auto-fill flag whenever user manually edits item_code
    itemCodeControl.valueChanges.pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(() => {
      this.itemCodeAutoFilled = false;
    });

    // Item name changes → push to trigger stream (debounced + deduplicated)
    itemNameControl.valueChanges.pipe(
      map((v) => (typeof v === 'string' ? v.trim() : '')),
      debounceTime(600),
      distinctUntilChanged(),
      takeUntilDestroyed(this.destroyRef),
    ).subscribe((name) => this.ifrcTrigger$.next(name));

    // Spec hint changes → re-trigger with current item name
    this.ifrcSpecForm.valueChanges.pipe(
      debounceTime(400),
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(() => {
      const name = String(itemNameControl.value ?? '').trim();
      this.ifrcTrigger$.next(name);
    });

    // Main suggest pipeline
    this.ifrcTrigger$.pipe(
      switchMap((itemName) => {
        if (itemName.length < 3) {
          this.ifrcSuggestion.set(null);
          this.ifrcError.set(null);
          this.ifrcSuggestLogId = null;
          return of(null);
        }
        this.ifrcLoading.set(true);
        const { size_weight, form, material } = this.ifrcSpecForm.value;
        return this.ifrcSuggestService.suggest(itemName, {
          size_weight: size_weight ?? '',
          form: form ?? '',
          material: material ?? '',
        }).pipe(
          catchError((error) => {
            this.ifrcError.set(this.getIfrcErrorMessage(error));
            return of(null);
          }),
          finalize(() => this.ifrcLoading.set(false)),
        );
      }),
      takeUntilDestroyed(this.destroyRef),
    ).subscribe((suggestion) => {
      if (!suggestion) {
        this.ifrcSuggestion.set(null);
        this.ifrcSuggestLogId = null;
        if (this.itemCodeAutoFilled) {
          itemCodeControl.patchValue('', { emitEvent: false });
        }
        this.itemCodeAutoFilled = false;
        const currentName = String(itemNameControl.value ?? '').trim();
        if (currentName.length < 3) {
          this.ifrcError.set(null);
        }
        return;
      }

      this.ifrcSuggestion.set(suggestion);
      this.ifrcError.set(null);
      this.ifrcSuggestLogId = suggestion.suggestion_id;

      const confidence = Number(suggestion.confidence ?? 0);
      const threshold = Number(suggestion.auto_fill_threshold ?? 1);
      const meetsAutoFillThreshold = Number.isFinite(confidence)
        && Number.isFinite(threshold)
        && confidence >= threshold;

      const currentCode = String(itemCodeControl.value ?? '').trim();
      if (!suggestion.ifrc_code
        || !meetsAutoFillThreshold
        || (!this.itemCodeAutoFilled && currentCode.length > 0)) {
        return;
      }

      itemCodeControl.patchValue(suggestion.ifrc_code, { emitEvent: false });
      this.itemCodeAutoFilled = true;
    });
  }

  private getIfrcErrorMessage(error: unknown): string {
    if (typeof error === 'string' && error.trim()) {
      return error.trim();
    }

    const errObj = error as {
      message?: unknown;
      status?: unknown;
      error?: unknown;
    };
    const payload = errObj?.error;
    if (payload && typeof payload === 'object') {
      const payloadObj = payload as Record<string, unknown>;
      const detail = payloadObj['detail'];
      if (typeof detail === 'string' && detail.trim()) {
        return detail.trim();
      }
      const payloadError = payloadObj['error'];
      if (typeof payloadError === 'string' && payloadError.trim()) {
        return payloadError.trim();
      }
      const payloadMessage = payloadObj['message'];
      if (typeof payloadMessage === 'string' && payloadMessage.trim()) {
        return payloadMessage.trim();
      }
    }

    if (typeof errObj?.message === 'string' && errObj.message.trim()) {
      return errObj.message.trim();
    }
    if (typeof errObj?.status === 'number') {
      return `IFRC suggestion request failed (${errObj.status}).`;
    }
    return 'Failed to load IFRC suggestion.';
  }

  private hasIfrcItemCodeProvenance(record: Record<string, unknown>): boolean {
    const sourceKeys = [
      'item_code_source',
      'item_code_provenance',
      'ifrc_code_source',
      'ifrc_provenance',
    ];
    for (const key of sourceKeys) {
      const value = record[key];
      if (typeof value === 'string' && value.trim().toLowerCase().includes('ifrc')) {
        return true;
      }
    }

    const booleanKeys = [
      'item_code_ifrc_generated',
      'ifrc_generated_flag',
    ];
    for (const key of booleanKeys) {
      if (record[key] === true) {
        return true;
      }
    }

    const suggestLogId = record['ifrc_suggest_log_id'];
    if (suggestLogId === null || suggestLogId === undefined) {
      return false;
    }
    return String(suggestLogId).trim().length > 0;
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
        this.versionNbr = typeof record['version_nbr'] === 'number'
          ? record['version_nbr']
          : null;

        for (const field of cfg.formFields) {
          const control = this.form.get(field.field);
          if (control && record[field.field] !== undefined) {
            control.setValue(record[field.field], { emitEvent: false });
          }
          if (field.readonlyOnEdit && this.isEdit() && control) {
            control.disable();
          }
        }

        // Re-run cross-field validators (e.g. FEFO requires expiry) after silent patch
        this.form.updateValueAndValidity({ emitEvent: false });

        // For items: only preserve auto-filled behavior when persisted provenance
        // indicates the current item_code originated from IFRC suggestion flow.
        if (cfg.tableKey === 'items') {
          this.itemCodeAutoFilled = this.hasIfrcItemCodeProvenance(
            record as Record<string, unknown>,
          );
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
    this.clearSubmissionError();

    if (!this.form.valid) {
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
    if (cfg.tableKey === 'items' && this.ifrcSuggestLogId) {
      rawData['ifrc_suggest_log_id'] = this.ifrcSuggestLogId;
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
        this.clearSubmissionError();
        this.notify.showSuccess(this.isEdit() ? 'Record updated.' : 'Record created.');
        this.service.clearLookupCache(cfg.tableKey);
        const newPk = res.record?.[cfg.pkField] ?? null;
        if (this.isEdit()) {
          this.navigateBack();
        } else if (newPk != null && newPk !== '') {
          this.router.navigate(['/master-data', cfg.routePath, newPk]);
        } else {
          this.notify.showWarning('Record saved, but no primary key was returned.');
          this.navigateBack();
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
          return;
        }

        const inactiveItemGuard = this.extractInactiveItemForwardWriteGuard(err);
        if (inactiveItemGuard) {
          const details = this.buildInactiveItemGuardDetails(inactiveItemGuard);
          this.setSubmissionError(
            'Save blocked because the selected item is inactive for forward-looking writes.',
            details,
            this.inactiveItemForwardWriteCode,
          );
          this.applyInactiveItemControlError(inactiveItemGuard);
          this.notify.showError('Save blocked by inactive-item forward-write guard.');
          return;
        } else if (err.status === 409) {
          const message = err.error?.detail || 'Record was modified by another user. Please reload.';
          this.setSubmissionError(message, [], 'versionConflict');
          this.notify.showError(message);
        } else {
          const message = err.error?.detail || 'Save failed.';
          this.setSubmissionError(message, [], 'submitFailure');
          this.notify.showError(message);
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
      'Item Identity': 'label',
      'Classification': 'category',
      'Inventory Rules': 'inventory_2',
      'Tracking & Behaviour': 'track_changes',
      'Notes & Storage': 'notes',
      'Notes': 'notes',
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

  getFormErrorMessage(errorKey: string): string {
    return this.formErrorMessages[errorKey] || 'Please fix the validation errors.';
  }

  isFormErrorVisible(errorKey: string): boolean {
    if (!this.form.hasError(errorKey)) return false;

    const issuanceTouched = this.form.get('issuance_order')?.touched ?? false;
    const canExpireTouched = this.form.get('can_expire_flag')?.touched ?? false;
    return issuanceTouched || canExpireTouched || this.form.touched;
  }

  private setSubmissionError(message: string, details: string[], formErrorKey: string): void {
    this.submissionError.set(message);
    this.submissionErrorDetails.set(details);
    this.form.setErrors({
      ...(this.form.errors || {}),
      [formErrorKey]: true,
    });
  }

  private clearSubmissionError(): void {
    this.submissionError.set(null);
    this.submissionErrorDetails.set([]);

    const formErrors = this.form.errors;
    if (!formErrors) return;

    const nextErrors: Record<string, unknown> = { ...formErrors };
    delete nextErrors[this.inactiveItemForwardWriteCode];
    delete nextErrors['versionConflict'];
    delete nextErrors['submitFailure'];
    this.form.setErrors(Object.keys(nextErrors).length ? nextErrors : null);
  }

  private extractInactiveItemForwardWriteGuard(error: unknown): InactiveItemForwardWriteGuard | null {
    const err = error as {
      error?: {
        errors?: Record<string, unknown>;
      };
    };
    const rawGuard = err?.error?.errors?.[this.inactiveItemForwardWriteCode];
    if (!rawGuard || typeof rawGuard !== 'object') {
      return null;
    }

    const guard = rawGuard as Record<string, unknown>;
    const itemIds = Array.isArray(guard['item_ids'])
      ? guard['item_ids']
        .map((value) => Number(value))
        .filter((value) => Number.isInteger(value) && value > 0)
      : [];

    return {
      table: String(guard['table'] || '').trim() || 'unknown',
      workflow_state: String(guard['workflow_state'] || '').trim() || 'UNKNOWN',
      item_ids: [...new Set(itemIds)].sort((a, b) => a - b),
    };
  }

  private buildInactiveItemGuardDetails(guard: InactiveItemForwardWriteGuard): string[] {
    const details = [
      `Table: ${this.humanizeToken(guard.table)}`,
      `Workflow State: ${this.humanizeToken(guard.workflow_state)}`,
    ];

    if (guard.item_ids.length > 0) {
      details.push(`Inactive Item ID(s): ${guard.item_ids.join(', ')}`);
    }

    return details;
  }

  private applyInactiveItemControlError(guard: InactiveItemForwardWriteGuard): void {
    const itemControl = this.form.get('item_id');
    if (!itemControl) return;

    const message = guard.item_ids.length > 0
      ? `Inactive item ID(s): ${guard.item_ids.join(', ')}`
      : 'Selected item is inactive for forward-looking writes.';

    itemControl.setErrors({
      ...(itemControl.errors || {}),
      server: message,
    });
    itemControl.markAsTouched();
  }

  private humanizeToken(rawValue: string): string {
    const normalized = String(rawValue || '').trim();
    if (!normalized) return 'Unknown';

    return normalized
      .split('_')
      .filter(Boolean)
      .map((token) => token.charAt(0).toUpperCase() + token.slice(1).toLowerCase())
      .join(' ');
  }
}
