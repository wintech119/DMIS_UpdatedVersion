import { Component, OnInit, Output, EventEmitter, DestroyRef, inject } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router } from '@angular/router';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';

import { WizardStateService } from '../../services/wizard-state.service';
import { ReplenishmentService, ActiveEvent, Warehouse } from '../../../services/replenishment.service';
import { EventPhase, PhaseWindows, PHASE_WINDOWS } from '../../../models/stock-status.model';
import { distinctUntilChanged, map } from 'rxjs/operators';
import { forkJoin } from 'rxjs';

interface ScopeFormValue {
  event_id: number | null;
  warehouse_ids: number[];
  phase: EventPhase;
  as_of_datetime: string;
}

const isSameScopeFormValue = (a: ScopeFormValue, b: ScopeFormValue): boolean => {
  if (a.event_id !== b.event_id) return false;
  if (a.phase !== b.phase) return false;
  if (a.as_of_datetime !== b.as_of_datetime) return false;
  if (a.warehouse_ids.length !== b.warehouse_ids.length) return false;
  for (let i = 0; i < a.warehouse_ids.length; i += 1) {
    if (a.warehouse_ids[i] !== b.warehouse_ids[i]) return false;
  }
  return true;
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
  loadingInitialData = false;
  errors: string[] = [];
  private destroyRef = inject(DestroyRef);

  // Fetched from API
  availableWarehouses: Warehouse[] = [];
  activeEvent: ActiveEvent | null = null;

  constructor(
    private fb: FormBuilder,
    private wizardService: WizardStateService,
    private replenishmentService: ReplenishmentService,
    private router: Router
  ) {
    this.form = this.fb.group({
      event_id: [null, [Validators.required, Validators.min(1)]],
      warehouse_ids: [[], [Validators.required, Validators.minLength(1)]],
      phase: ['BASELINE', Validators.required],
      as_of_datetime: ['']
    });
  }

  ngOnInit(): void {
    // Load initial data (event and warehouses)
    this.loadInitialData();

    // Sync form with wizard state
    this.wizardService.getState$().pipe(
      map(state => ({
        event_id: state.event_id ?? null,
        warehouse_ids: state.warehouse_ids ?? [],
        phase: state.phase ?? 'BASELINE',
        as_of_datetime: state.as_of_datetime ?? ''
      })),
      distinctUntilChanged(isSameScopeFormValue),
      takeUntilDestroyed(this.destroyRef)
    ).subscribe(values => {
      this.form.patchValue(values, { emitEvent: false });
    });

    // Auto-save form changes to state
    this.form.valueChanges.pipe(
      takeUntilDestroyed(this.destroyRef)
    ).subscribe(values => {
      this.wizardService.updateState({
        event_id: values.event_id,
        event_name: this.activeEvent?.event_name,
        warehouse_ids: values.warehouse_ids,
        phase: values.phase,
        as_of_datetime: values.as_of_datetime
      });
    });
  }

  private loadInitialData(): void {
    this.loadingInitialData = true;
    this.form.disable();

    forkJoin({
      event: this.replenishmentService.getActiveEvent(),
      warehouses: this.replenishmentService.getAllWarehouses()
    }).subscribe({
      next: ({ event, warehouses }) => {
        this.activeEvent = event;
        this.availableWarehouses = warehouses;

        // If active event exists and form doesn't have event_id, set it
        if (event && !this.form.value.event_id) {
          this.form.patchValue({ event_id: event.event_id });
        }

        // Always save event_name to state when event is loaded
        if (event) {
          this.wizardService.updateState({
            event_name: event.event_name
          });
        }

        this.loadingInitialData = false;
        this.form.enable();
      },
      error: (error) => {
        this.loadingInitialData = false;
        this.form.enable();
        this.errors = ['Failed to load event and warehouse data. Please try again.'];
        console.error('Error loading initial data:', error);
      }
    });
  }

  getPhaseInfo(phase: EventPhase): PhaseWindows {
    return PHASE_WINDOWS[phase];
  }

  get selectedPhaseInfo(): PhaseWindows | null {
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

  cancel(): void {
    const confirmed = confirm('Are you sure you want to cancel? Any unsaved changes will be lost.');
    if (confirmed) {
      this.wizardService.reset();
      this.router.navigate(['/replenishment/dashboard']);
    }
  }
}
