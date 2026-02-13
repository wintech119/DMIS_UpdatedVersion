import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';

export interface RejectReasonDialogResult {
  reason: string;
  notes?: string;
}

@Component({
  selector: 'app-reject-reason-dialog',
  imports: [
    MatDialogModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    ReactiveFormsModule
  ],
  template: `
    <h2 mat-dialog-title>Reject Needs List</h2>

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
        <button matButton="outlined" type="button" mat-dialog-close>Cancel</button>
        <button matButton="filled" color="warn" type="submit">Reject</button>
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
export class RejectReasonDialogComponent {
  private readonly fb = inject(FormBuilder);
  private readonly dialogRef = inject(
    MatDialogRef<RejectReasonDialogComponent, RejectReasonDialogResult>
  );

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
