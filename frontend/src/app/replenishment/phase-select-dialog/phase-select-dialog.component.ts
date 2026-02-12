
import { Component, inject } from '@angular/core';
import { FormControl, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatDialogModule, MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatSelectModule } from '@angular/material/select';
import { EventPhase } from '../models/stock-status.model';

export interface PhaseSelectDialogData {
  currentPhase: EventPhase | null | undefined;
}

@Component({
  selector: 'app-phase-select-dialog',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatDialogModule,
    MatFormFieldModule,
    MatSelectModule,
    MatButtonModule
],
  templateUrl: './phase-select-dialog.component.html',
  styleUrl: './phase-select-dialog.component.scss'
})
export class PhaseSelectDialogComponent {
  private dialogRef = inject<MatDialogRef<PhaseSelectDialogComponent, EventPhase>>(MatDialogRef);
  data = inject<PhaseSelectDialogData>(MAT_DIALOG_DATA);

  readonly phaseOptions: EventPhase[] = ['SURGE', 'STABILIZED', 'BASELINE'];
  phaseControl: FormControl<EventPhase | null>;

  constructor() {
    this.phaseControl = new FormControl<EventPhase | null>(this.data.currentPhase ?? null, {
      nonNullable: false,
      validators: [Validators.required]
    });
  }

  submit(): void {
    if (this.phaseControl.invalid) {
      this.phaseControl.markAsTouched();
      return;
    }
    this.dialogRef.close(this.phaseControl.value as EventPhase);
  }

  cancel(): void {
    this.dialogRef.close();
  }
}
