import { Component, OnInit, Output, EventEmitter } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';

import { WizardStateService } from '../../services/wizard-state.service';
import { ReplenishmentService } from '../../../services/replenishment.service';
import { EventPhase } from '../../../models/stock-status.model';

interface PhaseWindow {
  demand_hours: number;
  planning_hours: number;
  safety_factor: number;
}

const PHASE_WINDOWS: Record<EventPhase, PhaseWindow> = {
  SURGE: { demand_hours: 6, planning_hours: 72, safety_factor: 1.25 },
  STABILIZED: { demand_hours: 72, planning_hours: 168, safety_factor: 1.25 },
  BASELINE: { demand_hours: 720, planning_hours: 720, safety_factor: 1.25 }
};

@Component({
  selector: 'app-scope-step',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatButtonModule,
    MatCardModule,
    MatIconModule,
    MatProgressBarModule
  ],
  templateUrl: './scope-step.component.html',
  styleUrl: './scope-step.component.scss'
})
export class ScopeStepComponent implements OnInit {
  @Output() next = new EventEmitter<void>();

  form: FormGroup;
  phaseOptions: EventPhase[] = ['SURGE', 'STABILIZED', 'BASELINE'];
  loading = false;
  errors: string[] = [];

  // Hardcoded warehouse list for MVP (can be fetched from API later)
  availableWarehouses = [
    { id: 1, name: 'Kingston Central' },
    { id: 2, name: 'Montego Bay' },
    { id: 3, name: 'Spanish Town' },
    { id: 4, name: 'Portmore' },
    { id: 5, name: 'May Pen' }
  ];

  constructor(
    private fb: FormBuilder,
    private wizardService: WizardStateService,
    private replenishmentService: ReplenishmentService
  ) {
    this.form = this.fb.group({
      event_id: [null, [Validators.required, Validators.min(1)]],
      warehouse_ids: [[], [Validators.required, Validators.minLength(1)]],
      phase: ['BASELINE', Validators.required],
      as_of_datetime: ['']
    });
  }

  ngOnInit(): void {
    // Load from wizard state
    const state = this.wizardService.getState();
    if (state.event_id) {
      this.form.patchValue({
        event_id: state.event_id,
        warehouse_ids: state.warehouse_ids || [],
        phase: state.phase || 'BASELINE',
        as_of_datetime: state.as_of_datetime || ''
      });
    }

    // Auto-save form changes to state
    this.form.valueChanges.subscribe(values => {
      this.wizardService.updateState({
        event_id: values.event_id,
        warehouse_ids: values.warehouse_ids,
        phase: values.phase,
        as_of_datetime: values.as_of_datetime
      });
    });
  }

  getPhaseInfo(phase: EventPhase): PhaseWindow {
    return PHASE_WINDOWS[phase];
  }

  get selectedPhaseInfo(): PhaseWindow | null {
    const phase = this.form.value.phase;
    return phase ? this.getPhaseInfo(phase) : null;
  }

  calculateGaps(): void {
    this.errors = [];

    if (this.form.invalid) {
      this.errors = ['Please provide valid event ID, warehouse(s), and phase.'];
      this.form.markAllAsTouched();
      return;
    }

    const { event_id, warehouse_ids, phase, as_of_datetime } = this.form.value;

    this.loading = true;

    // Call preview-multi API
    this.replenishmentService.getStockStatusMulti(
      event_id,
      warehouse_ids,
      phase,
      as_of_datetime || undefined
    ).subscribe({
      next: (response) => {
        // Store preview response in wizard state
        this.wizardService.updateState({
          previewResponse: response
        });
        this.loading = false;
        this.next.emit();  // Move to next step
      },
      error: (error) => {
        this.loading = false;
        const errorMessage = error.error?.errors
          ? Object.values(error.error.errors).join(', ')
          : error.message || 'Failed to calculate gaps. Please try again.';
        this.errors = [errorMessage];
      }
    });
  }

  get isValid(): boolean {
    return this.form.valid;
  }
}
