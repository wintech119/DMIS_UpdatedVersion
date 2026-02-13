import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';

export interface DmisReasonDialogData {
  title: string;
  actionLabel: string;
  actionColor?: 'primary' | 'accent' | 'warn';
}

export interface DmisReasonDialogResult {
  reason: string;
  notes?: string;
}

@Component({
  selector: 'dmis-reason-dialog',
  imports: [
    MatDialogModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    ReactiveFormsModule
  ],
  template: `
    <h2 mat-dialog-title>{{ data.title }}</h2>

    <form [formGroup]="form" (ngSubmit)="submit()">
      <mat-dialog-content>
        <mat-form-field appearance="outline" class="dialog-field">
          <mat-label>Reason</mat-label>
          <textarea matInput rows="3" formControlName="reason"></textarea>
          @if (form.controls.reason.invalid && form.controls.reason.touched) {
            <mat-error>Reason is required.</mat-error>
          }
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
    reason: ['', [Validators.required]],
    notes: ['']
  });

  submit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }

    const reason = this.form.controls.reason.value.trim();
    const notes = this.form.controls.notes.value.trim();

    this.dialogRef.close({
      reason,
      notes: notes || undefined
    });
  }
}
