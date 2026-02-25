import { Component, OnInit, Output, EventEmitter, DestroyRef, inject } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router } from '@angular/router';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';

import { WizardStateService } from '../../services/wizard-state.service';
import { DmisConfirmDialogComponent, ConfirmDialogData } from '../../../shared/dmis-confirm-dialog/dmis-confirm-dialog.component';
import { DmisNotificationService } from '../../../services/notification.service';
import { DmisSkeletonLoaderComponent } from '../../../shared/dmis-skeleton-loader/dmis-skeleton-loader.component';
import { WizardState } from '../../models/wizard-state.model';
import { ReplenishmentService, ActiveEvent, NeedsListDuplicateSummary, Warehouse } from '../../../services/replenishment.service';
import {
  DuplicateWarningResult,
  NeedsListDuplicateWarningData,
  NeedsListDuplicateWarningDialogComponent
} from '../../../shared/needs-list-duplicate-warning-dialog/needs-list-duplicate-warning-dialog.component';
import { EventPhase, PhaseWindows, PHASE_WINDOWS } from '../../../models/stock-status.model';
import { catchError, distinctUntilChanged, map, switchMap } from 'rxjs/operators';
import { forkJoin, Observable, of } from 'rxjs';

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
    ReactiveFormsModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatButtonModule,
    MatCardModule,
    MatIconModule,
    MatProgressBarModule,
    MatProgressSpinnerModule,
    MatDialogModule,
    DmisSkeletonLoaderComponent
],
  templateUrl: './scope-step.component.html',
  styleUrl: './scope-step.component.scss'
})
export class ScopeStepComponent implements OnInit {
  private fb = inject(FormBuilder);
  private wizardService = inject(WizardStateService);
  private replenishmentService = inject(ReplenishmentService);
  private router = inject(Router);

  @Output() next = new EventEmitter<void>();

  form: FormGroup;
  phaseOptions: EventPhase[] = ['SURGE', 'STABILIZED', 'BASELINE'];
  loading = false;
  loadingInitialData = false;
  errors: string[] = [];
  calculationProgress = '';
  private calculationTimer: ReturnType<typeof setInterval> | null = null;
  private destroyRef = inject(DestroyRef);
  private notificationService = inject(DmisNotificationService);

  private readonly calculationSteps = [
    'Loading warehouse data...',
    'Calculating burn rates...',
    'Analyzing Horizon A (Transfers)...',
    'Analyzing Horizon B (Donations)...',
    'Analyzing Horizon C (Procurement)...',
    'Computing gaps...'
  ];

  // Fetched from API
  availableWarehouses: Warehouse[] = [];
  activeEvent: ActiveEvent | null = null;

  private dialog = inject(MatDialog);

  constructor() {
    this.form = this.fb.group({
      event_id: [null, [Validators.required, Validators.min(1)]],
      warehouse_ids: [[], [Validators.required, Validators.minLength(1)]],
      phase: ['BASELINE', Validators.required],
      as_of_datetime: ['']
    });
  }

  ngOnInit(): void {
    this.destroyRef.onDestroy(() => this.stopCalculationProgress());

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
      const update: Partial<WizardState> = {
        event_id: values.event_id,
        warehouse_ids: values.warehouse_ids,
        phase: values.phase,
        as_of_datetime: values.as_of_datetime
      };

      if (this.activeEvent?.event_name) {
        update.event_name = this.activeEvent.event_name;
      }

      this.wizardService.updateState(update);
    });
  }

  private loadInitialData(): void {
    this.loadingInitialData = true;
    this.form.disable();

    forkJoin({
      event: this.replenishmentService.getActiveEvent(),
      warehouses: this.replenishmentService.getAllWarehouses()
    }).pipe(
      takeUntilDestroyed(this.destroyRef)
    ).subscribe({
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
        this.notificationService.showNetworkError(
          'Failed to load event and warehouse data.',
          () => this.loadInitialData()
        );
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
    const excludeNeedsListId = this.resolveNeedsListIdToExclude();

    this.loading = true;

    forkJoin(
      (warehouse_ids as number[]).map((wid) =>
        this.replenishmentService.checkActiveNeedsLists(
          event_id,
          wid,
          phase,
          excludeNeedsListId
        )
      )
    ).pipe(
      catchError((err) => {
        console.warn('[DuplicateCheck] Failed, proceeding without warning:', err);
        return of([] as NeedsListDuplicateSummary[][]);
      }),
      switchMap((resultsPerWarehouse) => {
        const allConflicts = (resultsPerWarehouse as NeedsListDuplicateSummary[][]).flat();
        const uniqueConflicts: NeedsListDuplicateSummary[] = [];
        const seenNeedsListIds = new Set<string>();
        for (const conflict of allConflicts) {
          const needsListId = String(conflict?.needs_list_id || '').trim();
          if (!needsListId || seenNeedsListIds.has(needsListId)) {
            continue;
          }
          seenNeedsListIds.add(needsListId);
          uniqueConflicts.push(conflict);
        }

        if (uniqueConflicts.length === 0) {
          return of('continue' as DuplicateWarningResult);
        }

        return this.dialog.open(NeedsListDuplicateWarningDialogComponent, {
          data: {
            existingLists: uniqueConflicts,
            warehouseCount: (warehouse_ids as number[]).length
          } as NeedsListDuplicateWarningData,
          width: '560px',
          ariaLabel: 'Active needs list warning'
        }).afterClosed() as Observable<DuplicateWarningResult | undefined>;
      }),
      switchMap((result: DuplicateWarningResult | undefined) => {
        if (!result || result === 'cancel' || result === 'view') {
          return of(null);
        }
        this.startCalculationProgress();
        return this.replenishmentService.getStockStatusMulti(
          event_id,
          warehouse_ids,
          phase,
          as_of_datetime || undefined
        );
      }),
      takeUntilDestroyed(this.destroyRef)
    ).subscribe({
      next: (response) => {
        this.stopCalculationProgress();
        this.loading = false;
        if (response === null) return;
        this.wizardService.updateState({ previewResponse: response });
        this.next.emit();
      },
      error: (error) => {
        this.stopCalculationProgress();
        this.loading = false;
        const errorMessage = error.error?.errors
          ? Object.values(error.error.errors).join(', ')
          : error.message || 'Failed to calculate gaps. Please try again.';
        this.notificationService.showNetworkError(errorMessage, () => this.calculateGaps());
      }
    });
  }

  private resolveNeedsListIdToExclude(): string | undefined {
    const state = this.wizardService.getState();
    const fromDrafts = (state.draft_ids || [])
      .map((id) => String(id || '').trim())
      .find((id) => id.length > 0);
    if (fromDrafts) {
      return fromDrafts;
    }

    const fromPreview = String(state.previewResponse?.needs_list_id || '').trim();
    return fromPreview || undefined;
  }

  private startCalculationProgress(): void {
    let stepIndex = 0;
    this.calculationProgress = this.calculationSteps[0];

    this.calculationTimer = setInterval(() => {
      stepIndex = (stepIndex + 1) % this.calculationSteps.length;
      this.calculationProgress = this.calculationSteps[stepIndex];
    }, 600);
  }

  private stopCalculationProgress(): void {
    if (this.calculationTimer) {
      clearInterval(this.calculationTimer);
      this.calculationTimer = null;
    }
    this.calculationProgress = '';
  }

  get isValid(): boolean {
    return this.form.valid;
  }

  cancel(): void {
    const data: ConfirmDialogData = {
      title: 'Cancel Wizard',
      message: 'Are you sure you want to cancel? Any unsaved changes will be lost.',
      confirmLabel: 'Yes, Cancel',
      cancelLabel: 'Keep Working'
    };

    this.dialog.open(DmisConfirmDialogComponent, {
      data,
      width: '400px',
      ariaLabel: 'Confirm cancel wizard'
    }).afterClosed().subscribe((confirmed: boolean) => {
      if (confirmed) {
        this.wizardService.reset();
        this.router.navigate(['/replenishment/dashboard']);
      }
    });
  }
}
