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
import { NeedsListItem, NeedsListResponse } from '../../../models/needs-list.model';
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
    const excludedNeedsListIds = this.resolveNeedsListIdsToExclude();
    this.loading = true;
    this.startCalculationProgress();

    const duplicateCheck$ = forkJoin(
      (warehouse_ids as number[]).map((wid) =>
        this.replenishmentService.checkActiveNeedsLists(
          event_id,
          wid,
          phase
        )
      )
    );

    forkJoin({
      previewResponse: this.replenishmentService.getStockStatusMulti(
        event_id,
        warehouse_ids,
        phase,
        as_of_datetime || undefined
      ),
      duplicateResults: duplicateCheck$
    }).pipe(
      switchMap(({ previewResponse, duplicateResults }) => {
        const conflicts = this.resolveDuplicateConflicts(
          previewResponse,
          duplicateResults,
          excludedNeedsListIds
        );

        if (conflicts.length === 0) {
          return of(previewResponse);
        }

        this.stopCalculationProgress();
        return this.dialog.open(NeedsListDuplicateWarningDialogComponent, {
          data: {
            existingLists: conflicts,
            warehouseCount: (warehouse_ids as number[]).length
          } as NeedsListDuplicateWarningData,
          width: '560px',
          ariaLabel: 'Active needs list warning'
        }).afterClosed().pipe(
          map((result: DuplicateWarningResult | undefined) => {
            if (!result || result === 'cancel' || result === 'view') {
              return null;
            }
            return previewResponse;
          })
        ) as Observable<NeedsListResponse | null>;
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

  private resolveDuplicateConflicts(
    previewResponse: NeedsListResponse,
    resultsPerWarehouse: NeedsListDuplicateSummary[][],
    excludedNeedsListIds: Set<string>
  ): NeedsListDuplicateSummary[] {
    const requestedItemIdsByWarehouse = this.collectRequestedItemIdsByWarehouse(
      previewResponse.items || []
    );
    const allConflicts = resultsPerWarehouse.flat();
    const uniqueConflicts: NeedsListDuplicateSummary[] = [];
    const seenNeedsListIds = new Set<string>();

    for (const conflict of allConflicts) {
      const needsListId = String(conflict?.needs_list_id || '').trim();
      if (
        !needsListId ||
        excludedNeedsListIds.has(needsListId) ||
        seenNeedsListIds.has(needsListId)
      ) {
        continue;
      }

      if (!this.conflictOverlapsRequestedItems(conflict, requestedItemIdsByWarehouse)) {
        continue;
      }

      seenNeedsListIds.add(needsListId);
      uniqueConflicts.push(conflict);
    }

    return uniqueConflicts;
  }

  private collectRequestedItemIdsByWarehouse(
    items: NeedsListItem[]
  ): Map<number, Set<number>> {
    const itemIdsByWarehouse = new Map<number, Set<number>>();
    for (const item of items) {
      const warehouseId = Number(item.warehouse_id || 0);
      const itemId = Number(item.item_id || 0);
      const requiredQty = Number(item.required_qty ?? item.gap_qty ?? 0);
      if (!Number.isInteger(warehouseId) || warehouseId <= 0) {
        continue;
      }
      if (!Number.isInteger(itemId) || itemId <= 0 || requiredQty <= 0) {
        continue;
      }
      if (!itemIdsByWarehouse.has(warehouseId)) {
        itemIdsByWarehouse.set(warehouseId, new Set<number>());
      }
      itemIdsByWarehouse.get(warehouseId)?.add(itemId);
    }
    return itemIdsByWarehouse;
  }

  private conflictOverlapsRequestedItems(
    conflict: NeedsListDuplicateSummary,
    requestedItemIdsByWarehouse: Map<number, Set<number>>
  ): boolean {
    const warehouseId = Number(conflict.warehouse_id || 0);
    const requestedItemIds = requestedItemIdsByWarehouse.get(warehouseId);
    if (!requestedItemIds || requestedItemIds.size === 0) {
      return true;
    }

    const conflictItemIds = new Set<number>();
    for (const itemIdRaw of conflict.item_ids || []) {
      const itemId = Number(itemIdRaw);
      if (Number.isInteger(itemId) && itemId > 0) {
        conflictItemIds.add(itemId);
      }
    }

    if (conflictItemIds.size === 0) {
      return true;
    }

    for (const itemId of requestedItemIds) {
      if (conflictItemIds.has(itemId)) {
        return true;
      }
    }
    return false;
  }

  private resolveNeedsListIdsToExclude(): Set<string> {
    const state = this.wizardService.getState();
    const editableStatuses = new Set(['DRAFT', 'MODIFIED', 'RETURNED']);
    const ids = new Set<string>();

    const editingDraftId = String(state.editing_draft_id || '').trim();
    if (editingDraftId.length > 0) {
      ids.add(editingDraftId);
    }

    const previewStatus = String(state.previewResponse?.status || '').trim().toUpperCase();
    const isEditableContext = ids.size > 0 || editableStatuses.has(previewStatus);
    if (!isEditableContext) {
      return ids;
    }

    for (const id of state.draft_ids || []) {
      const normalizedId = String(id || '').trim();
      if (normalizedId.length > 0) {
        ids.add(normalizedId);
      }
    }

    const fromPreview = String(state.previewResponse?.needs_list_id || '').trim();
    if (fromPreview.length > 0 && editableStatuses.has(previewStatus)) {
      ids.add(fromPreview);
    }

    return ids;
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
    }).afterClosed().pipe(
      takeUntilDestroyed(this.destroyRef),
      switchMap((confirmed: boolean) => {
        if (!confirmed) {
          return of(false);
        }
        return this.discardEditedDraftIfNeeded().pipe(map(() => true));
      })
    ).subscribe((shouldExit: boolean) => {
      if (shouldExit) {
        this.wizardService.reset();
        this.router.navigate(['/replenishment/dashboard']);
      }
    });
  }

  private discardEditedDraftIfNeeded(): Observable<void> {
    const state = this.wizardService.getState();
    const editingDraftId = String(state.editing_draft_id || '').trim();
    // Never delete a persisted draft opened for editing when user cancels.
    if (editingDraftId) {
      return of(void 0);
    }

    const previewNeedsListId = String(state.previewResponse?.needs_list_id || '').trim();
    if (!previewNeedsListId) {
      return of(void 0);
    }

    const normalizedStatus = String(state.previewResponse?.status || '').trim().toUpperCase();
    if (normalizedStatus && normalizedStatus !== 'DRAFT' && normalizedStatus !== 'MODIFIED') {
      return of(void 0);
    }

    return this.replenishmentService.bulkDeleteDrafts(
      [previewNeedsListId],
      'Cancelled while editing draft from wizard.'
    ).pipe(
      map(() => void 0),
      catchError(() => of(void 0))
    );
  }
}
