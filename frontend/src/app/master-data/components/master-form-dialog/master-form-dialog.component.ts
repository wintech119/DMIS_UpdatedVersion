import {
  Component, OnInit, DestroyRef, ChangeDetectionStrategy,
  inject, signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { ReactiveFormsModule, FormGroup, FormControl, Validators } from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatProgressBarModule } from '@angular/material/progress-bar';

import { LookupItem, MasterTableConfig } from '../../models/master-data.models';
import { MasterDataService } from '../../services/master-data.service';
import { DmisNotificationService } from '../../../replenishment/services/notification.service';
import { validateFefoRequiresExpiry } from '../../models/table-configs/item.config';

export interface MasterFormDialogData {
  config: MasterTableConfig;
  pk: string | number | null;
}

@Component({
  selector: 'dmis-master-form-dialog',
  standalone: true,
  imports: [
    CommonModule, ReactiveFormsModule,
    MatDialogModule, MatFormFieldModule, MatInputModule, MatSelectModule,
    MatButtonModule, MatIconModule, MatCheckboxModule, MatProgressBarModule,
  ],
  template: `
    <div class="dialog-header">
      <mat-icon class="dialog-icon">{{ data.config.icon }}</mat-icon>
      <h2 mat-dialog-title>{{ isEdit() ? 'Edit' : 'Create' }} {{ data.config.displayName }}</h2>
    </div>

    @if (isLoadingRecord()) {
      <mat-progress-bar mode="indeterminate" />
    }

    <mat-dialog-content>
      <form [formGroup]="form" class="dialog-form">
        @for (field of data.config.formFields; track field.field) {
          @switch (field.type) {
            @case ('textarea') {
              <mat-form-field appearance="outline" class="full-width">
                <mat-label>{{ field.label }}</mat-label>
                <textarea matInput [formControlName]="field.field"
                  [maxlength]="field.maxLength || null"
                  rows="3"
                  [attr.aria-required]="field.required || null"></textarea>
                @if (form.get(field.field)?.hasError('required')) {
                  <mat-error>{{ field.label }} is required</mat-error>
                }
                @if (form.get(field.field)?.hasError('server')) {
                  <mat-error>{{ form.get(field.field)?.getError('server') }}</mat-error>
                }
                @if (field.maxLength) {
                  <mat-hint align="end">
                    {{ (form.get(field.field)?.value?.length || 0) }} / {{ field.maxLength }}
                  </mat-hint>
                }
              </mat-form-field>
            }
            @case ('select') {
              <mat-form-field appearance="outline" class="full-width">
                <mat-label>{{ field.label }}</mat-label>
                <mat-select [formControlName]="field.field"
                  [attr.aria-required]="field.required || null">
                  @for (opt of field.options; track opt.value) {
                    <mat-option [value]="opt.value">{{ opt.label }}</mat-option>
                  }
                </mat-select>
                @if (form.get(field.field)?.hasError('required')) {
                  <mat-error>{{ field.label }} is required</mat-error>
                }
                @if (field.field === 'issuance_order' && isFormErrorVisible('fefoRequiresExpiry')) {
                  <mat-error>{{ getFormErrorMessage('fefoRequiresExpiry') }}</mat-error>
                }
                @if (field.field === 'issuance_order' && isFormErrorVisible('expiryRequiresFefo')) {
                  <mat-error>{{ getFormErrorMessage('expiryRequiresFefo') }}</mat-error>
                }
                @if (form.get(field.field)?.hasError('server')) {
                  <mat-error>{{ form.get(field.field)?.getError('server') }}</mat-error>
                }
              </mat-form-field>
            }
            @case ('lookup') {
              <mat-form-field appearance="outline" class="full-width">
                <mat-label>{{ field.label }}</mat-label>
                <mat-select [formControlName]="field.field"
                  [attr.aria-required]="field.required || null">
                  @for (item of lookups()[field.lookupTable!] || []; track item.value) {
                    <mat-option [value]="item.value">{{ item.label }}</mat-option>
                  }
                </mat-select>
                @if (form.get(field.field)?.hasError('required')) {
                  <mat-error>{{ field.label }} is required</mat-error>
                }
                @if (form.get(field.field)?.hasError('server')) {
                  <mat-error>{{ form.get(field.field)?.getError('server') }}</mat-error>
                }
              </mat-form-field>
            }
            @case ('boolean') {
              <div class="bool-field-wrap">
                <mat-checkbox [formControlName]="field.field" class="bool-field">
                  {{ field.label }}
                </mat-checkbox>
                @if (field.field === 'can_expire_flag' && isFormErrorVisible('fefoRequiresExpiry')) {
                  <p class="bool-error">{{ getFormErrorMessage('fefoRequiresExpiry') }}</p>
                }
                @if (field.field === 'can_expire_flag' && isFormErrorVisible('expiryRequiresFefo')) {
                  <p class="bool-error">{{ getFormErrorMessage('expiryRequiresFefo') }}</p>
                }
              </div>
            }
            @default {
              <mat-form-field appearance="outline" class="full-width">
                <mat-label>{{ field.label }}</mat-label>
                <input matInput [formControlName]="field.field"
                  [type]="field.type === 'number' ? 'number' : 'text'"
                  [maxlength]="field.maxLength || null"
                  [attr.aria-required]="field.required || null" />
                @if (form.get(field.field)?.hasError('required')) {
                  <mat-error>{{ field.label }} is required</mat-error>
                }
                @if (form.get(field.field)?.hasError('maxlength')) {
                  <mat-error>Max {{ field.maxLength }} characters</mat-error>
                }
                @if (form.get(field.field)?.hasError('pattern')) {
                  <mat-error>{{ field.patternMessage || 'Invalid format' }}</mat-error>
                }
                @if (form.get(field.field)?.hasError('server')) {
                  <mat-error>{{ form.get(field.field)?.getError('server') }}</mat-error>
                }
              </mat-form-field>
            }
          }
        }
      </form>
    </mat-dialog-content>

    <mat-dialog-actions class="dialog-actions">
      <button mat-stroked-button mat-dialog-close class="cancel-btn">Cancel</button>
      <button mat-flat-button color="primary" class="save-btn"
        [disabled]="isSaving() || form.invalid"
        (click)="onSave()">
        @if (isSaving()) {
          <mat-icon class="spin">sync</mat-icon> Saving...
        } @else {
          <mat-icon>save</mat-icon> {{ isEdit() ? 'Update' : 'Create' }}
        }
      </button>
    </mat-dialog-actions>
  `,
  styles: [`
    :host {
      font-family: var(--dmis-font-sans, Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif);
    }
    .dialog-header {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 20px 24px 0;
    }
    .dialog-icon {
      color: #0f766e;
      font-size: 24px;
      width: 24px;
      height: 24px;
    }
    h2[mat-dialog-title] {
      margin: 0;
      padding: 0;
      font-size: 1.125rem;
      font-weight: 600;
      color: #1a1a1a;
    }
    .dialog-form {
      display: flex;
      flex-direction: column;
      gap: 8px;
      padding-top: 12px;
      min-width: 380px;
    }
    .full-width { width: 100%; }
    .bool-field-wrap {
      margin: 4px 0 8px;
    }
    .bool-field {
      margin: 0;
    }
    .bool-error {
      margin: 4px 2px 0;
      color: #b3261e;
      font-size: 0.75rem;
      line-height: 1.2;
    }
    .dialog-actions {
      padding: 12px 24px 20px;
      gap: 10px;
      border-top: 1px solid #e5e7eb;
      margin-top: 4px;
    }
    .cancel-btn {
      color: #6b7280;
      font-weight: 500;
    }
    .save-btn {
      font-weight: 600;
      border-radius: 8px;
      min-height: 40px;
      padding: 0 20px;
    }
    .save-btn mat-icon {
      font-size: 18px;
      width: 18px;
      height: 18px;
    }
    .spin {
      animation: spin 1s linear infinite;
    }
    @keyframes spin {
      from { transform: rotate(0deg); }
      to { transform: rotate(360deg); }
    }
    @media (max-width: 480px) {
      .dialog-form {
        min-width: unset;
      }
      .dialog-actions {
        flex-direction: column-reverse;
      }
      .dialog-actions button {
        width: 100%;
        min-height: 44px;
      }
    }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MasterFormDialogComponent implements OnInit {
  data = inject<MasterFormDialogData>(MAT_DIALOG_DATA);
  private dialogRef = inject(MatDialogRef<MasterFormDialogComponent>);
  private service = inject(MasterDataService);
  private notify = inject(DmisNotificationService);
  private destroyRef = inject(DestroyRef);

  form = new FormGroup<Record<string, FormControl>>({});
  isEdit = signal(false);
  isSaving = signal(false);
  isLoadingRecord = signal(false);
  lookups = signal<Record<string, LookupItem[]>>({});
  readonly formErrorMessages: Record<string, string> = {
    fefoRequiresExpiry: 'Can Expire must be enabled when Issuance Order is FEFO.',
    expiryRequiresFefo: 'Issuance Order must be FEFO when Can Expire is enabled.',
  };

  private versionNbr: number | null = null;

  ngOnInit(): void {
    this.isEdit.set(this.data.pk != null);
    this.buildForm();
    this.loadLookups();

    if (this.isEdit()) {
      this.loadRecord();
    }
  }

  private buildForm(): void {
    for (const field of this.data.config.formFields) {
      const validators = [];
      if (field.required) validators.push(Validators.required);
      if (field.maxLength) validators.push(Validators.maxLength(field.maxLength));
      if (field.pattern) validators.push(Validators.pattern(field.pattern));

      this.form.addControl(
        field.field,
        new FormControl(field.defaultValue ?? null, validators),
      );
    }

    if (this.data.config.tableKey === 'items') {
      this.form.setValidators(validateFefoRequiresExpiry);
      this.form.updateValueAndValidity({ emitEvent: false });
    }
  }

  private loadLookups(): void {
    const lookupFields = this.data.config.formFields.filter(f => f.type === 'lookup' && f.lookupTable);
    const loaded: Record<string, LookupItem[]> = {};

    for (const field of lookupFields) {
      this.service.lookup(field.lookupTable!).pipe(
        takeUntilDestroyed(this.destroyRef),
      ).subscribe(items => {
        loaded[field.lookupTable!] = items;
        this.lookups.set({ ...loaded });
      });
    }
  }

  private loadRecord(): void {
    this.isLoadingRecord.set(true);
    this.service.get(this.data.config.tableKey, this.data.pk!).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: res => {
        const record = res.record;
        this.versionNbr = typeof record['version_nbr'] === 'number'
          ? record['version_nbr']
          : null;

        for (const field of this.data.config.formFields) {
          const control = this.form.get(field.field);
          if (control && record[field.field] !== undefined) {
            control.setValue(record[field.field]);
          }
          if (field.readonlyOnEdit && control) {
            control.disable();
          }
        }
        this.isLoadingRecord.set(false);
      },
      error: () => {
        this.notify.showError('Failed to load record.');
        this.dialogRef.close(false);
      },
    });
  }

  onSave(): void {
    if (!this.form.valid) {
      this.form.markAllAsTouched();
      return;
    }

    this.isSaving.set(true);
    const rawData = this.form.getRawValue();

    // Apply uppercase transforms
    for (const field of this.data.config.formFields) {
      if (field.uppercase && typeof rawData[field.field] === 'string') {
        rawData[field.field] = rawData[field.field].trim().toUpperCase();
      }
    }

    const obs$ = this.isEdit()
      ? this.service.update(this.data.config.tableKey, this.data.pk!, {
          ...rawData,
          ...(this.versionNbr != null ? { version_nbr: this.versionNbr } : {}),
        })
      : this.service.create(this.data.config.tableKey, rawData);

    obs$.pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: () => {
        this.notify.showSuccess(
          this.isEdit() ? 'Record updated.' : 'Record created.',
        );
        this.dialogRef.close(true);
      },
      error: (err) => {
        this.isSaving.set(false);
        if (err.status === 400 && err.error?.errors) {
          // Map server errors to form controls
          const errors = err.error.errors as Record<string, string>;
          for (const [field, msg] of Object.entries(errors)) {
            const control = this.form.get(field);
            if (control) {
              control.setErrors({ server: msg });
              control.markAsTouched();
            }
          }
        } else if (err.status === 409) {
          this.notify.showError(err.error?.detail || 'Record was modified by another user.');
        } else {
          this.notify.showError(err.error?.detail || 'Save failed.');
        }
      },
    });
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
}
