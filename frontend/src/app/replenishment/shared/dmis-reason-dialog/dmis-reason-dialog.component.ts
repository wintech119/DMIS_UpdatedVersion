import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { AbstractControl, FormBuilder, ReactiveFormsModule, ValidationErrors, Validators } from '@angular/forms';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';

export interface DmisReasonDialogData {
  title: string;
  actionLabel: string;
  actionColor?: 'primary' | 'accent' | 'warn';
  reasonCodeLabel?: string;
  reasonCodeOptions?: readonly { value: string; label: string }[];
  reasonLabel?: string;
  reasonPlaceholder?: string;
  maxLength?: number;
}

export interface DmisReasonDialogResult {
  reason_code?: string;
  reason: string;
  notes?: string;
}

@Component({
  selector: 'dmis-reason-dialog',
  imports: [
    MatDialogModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatButtonModule,
    ReactiveFormsModule
  ],
  template: `
    <h2 mat-dialog-title>{{ data.title }}</h2>

    <form [formGroup]="form" (ngSubmit)="submit()">
      <mat-dialog-content>
        @if (data.reasonCodeOptions?.length) {
          <mat-form-field appearance="outline" class="dialog-field">
            <mat-label>{{ data.reasonCodeLabel ?? 'Reason Code' }}</mat-label>
            <mat-select formControlName="reason_code">
              @for (option of data.reasonCodeOptions; track option.value) {
                <mat-option [value]="option.value">{{ option.label }}</mat-option>
              }
            </mat-select>
            @if (form.controls.reason_code.invalid && form.controls.reason_code.touched) {
              <mat-error>Reason code is required.</mat-error>
            }
          </mat-form-field>
        }

        <mat-form-field appearance="outline" class="dialog-field">
          <mat-label>{{ data.reasonLabel ?? 'Reason' }}</mat-label>
            <textarea
              matInput
              rows="3"
              formControlName="reason"
              required
              [attr.maxlength]="data.maxLength ?? null"
              [attr.placeholder]="data.reasonPlaceholder ?? null"
              [attr.aria-describedby]="data.maxLength ? 'dmis-reason-count' : null"></textarea>
          @if (data.maxLength) {
            <mat-hint id="dmis-reason-count" align="end">
              {{ form.controls.reason.value.length }} / {{ data.maxLength }}
            </mat-hint>
          }
          <mat-error aria-live="polite">
            @if (form.controls.reason.hasError('required')) {
              <span>{{ data.reasonLabel ?? 'Reason' }} is required.</span>
            } @else if (form.controls.reason.hasError('maxlength')) {
              <span>Keep the reason to {{ data.maxLength }} characters or fewer.</span>
            }
          </mat-error>
        </mat-form-field>

        <mat-form-field appearance="outline" class="dialog-field">
          <mat-label>Notes (optional)</mat-label>
          <textarea matInput rows="3" formControlName="notes"></textarea>
        </mat-form-field>
      </mat-dialog-content>

      <mat-dialog-actions align="end">
        <button mat-button type="button" mat-dialog-close>Cancel</button>
        <button mat-flat-button [color]="data.actionColor ?? 'primary'" type="submit">
          {{ data.actionLabel }}
        </button>
      </mat-dialog-actions>
    </form>
  `,
  styles: `
    .dialog-field {
      width: 100%;
      margin-top: 8px;
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class DmisReasonDialogComponent {
  private readonly fb = inject(FormBuilder);
  private readonly dialogRef = inject(MatDialogRef<DmisReasonDialogComponent, DmisReasonDialogResult>);
  readonly data: DmisReasonDialogData = inject(MAT_DIALOG_DATA);

  readonly form = this.fb.nonNullable.group({
    reason_code: [''],
    reason: ['', [trimmedRequiredValidator]],
    notes: ['']
  });

  constructor() {
    if (this.data.reasonCodeOptions?.length) {
      this.form.controls.reason_code.addValidators(Validators.required);
      this.form.controls.reason_code.updateValueAndValidity({ emitEvent: false });
      if (this.data.reasonCodeOptions.length === 1) {
        this.form.controls.reason_code.setValue(this.data.reasonCodeOptions[0].value);
      }
    }
    if (typeof this.data.maxLength === 'number' && this.data.maxLength > 0) {
      this.form.controls.reason.addValidators(Validators.maxLength(this.data.maxLength));
      this.form.controls.reason.updateValueAndValidity({ emitEvent: false });
    }
  }

  submit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }

    const reason = this.form.controls.reason.value.trim();
    const notes = this.form.controls.notes.value.trim();

    this.dialogRef.close({
      reason_code: this.form.controls.reason_code.value || undefined,
      reason,
      notes: notes || undefined
    });
  }
}

function trimmedRequiredValidator(control: AbstractControl): ValidationErrors | null {
  return String(control.value ?? '').trim().length > 0 ? null : { required: true };
}
