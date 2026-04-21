import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { FormControl, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatDialogModule, MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatSelectModule } from '@angular/material/select';
import { Warehouse } from '../../services/replenishment.service';

export interface ScopePickerDialogData {
  availableWarehouses: Warehouse[];
  preselectedWarehouseId?: number | null;
}

export interface ScopePickerDialogResult {
  warehouseId: number;
}

@Component({
  selector: 'app-scope-picker-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ReactiveFormsModule,
    MatDialogModule,
    MatFormFieldModule,
    MatSelectModule,
    MatButtonModule
  ],
  template: `
    <h2 mat-dialog-title>Select a warehouse</h2>
    <div mat-dialog-content>
      <p class="scope-picker-help">
        Choose the warehouse you want to create a needs list for.
      </p>
      <mat-form-field appearance="fill" class="scope-picker-field">
        <mat-label>Warehouse</mat-label>
        <mat-select
          [formControl]="warehouseControl"
          aria-label="Warehouse selection"
          required>
          @for (warehouse of data.availableWarehouses; track warehouse.warehouse_id) {
            <mat-option [value]="warehouse.warehouse_id">
              {{ warehouse.warehouse_name }}
            </mat-option>
          }
        </mat-select>
        @if (warehouseControl.hasError('required')) {
          <mat-error>Warehouse is required.</mat-error>
        }
      </mat-form-field>
    </div>
    <div mat-dialog-actions align="end">
      <button mat-button type="button" (click)="cancel()">Cancel</button>
      <button
        matButton="filled"
        color="primary"
        type="button"
        (click)="submit()"
        [disabled]="warehouseControl.invalid">
        Continue
      </button>
    </div>
  `,
  styles: [`
    .scope-picker-help {
      margin: 0 0 16px;
      color: var(--color-text-secondary, #555);
      font-size: var(--text-sm, 13px);
    }
    .scope-picker-field {
      width: 320px;
      max-width: 100%;
    }
  `]
})
export class ScopePickerDialogComponent {
  private dialogRef = inject<MatDialogRef<ScopePickerDialogComponent, ScopePickerDialogResult>>(MatDialogRef);
  data = inject<ScopePickerDialogData>(MAT_DIALOG_DATA);

  warehouseControl = new FormControl<number | null>(this.data.preselectedWarehouseId ?? null, {
    validators: [Validators.required]
  });

  submit(): void {
    if (this.warehouseControl.invalid || this.warehouseControl.value == null) {
      this.warehouseControl.markAsTouched();
      return;
    }
    this.dialogRef.close({ warehouseId: this.warehouseControl.value });
  }

  cancel(): void {
    this.dialogRef.close();
  }
}
