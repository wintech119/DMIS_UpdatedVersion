import { HttpErrorResponse } from '@angular/common/http';
import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, DestroyRef, ViewChild, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { AbstractControl, FormBuilder, ReactiveFormsModule, ValidationErrors, Validators } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatStepper, MatStepperModule } from '@angular/material/stepper';
import { map, merge, startWith } from 'rxjs';

import { OpsDispatchReadinessStepComponent } from './steps/dispatch-readiness-step.component';
import { OpsDispatchReviewStepComponent } from './steps/dispatch-review-step.component';
import { DmisEmptyStateComponent } from '../../replenishment/shared/dmis-empty-state/dmis-empty-state.component';
import { DmisSkeletonLoaderComponent } from '../../replenishment/shared/dmis-skeleton-loader/dmis-skeleton-loader.component';
import { DmisStepTrackerComponent, StepDefinition } from '../../shared/dmis-step-tracker/dmis-step-tracker.component';
import { DmisNotificationService } from '../../replenishment/services/notification.service';
import { OpsMetricStripComponent, OpsMetricStripItem } from '../shared/ops-metric-strip.component';
import { OperationsService } from '../services/operations.service';
import {
  DispatchDetailResponse,
  DispatchHandoffPayload,
  DispatchHandoffResponse,
  WaybillResponse,
} from '../models/operations.model';
import {
  formatExecutionStatus,
  formatPackageStatus,
} from '../models/operations-status.util';

function combineDateAndTime(date: Date | string | null, time: string | null): Date | null {
  const normalizedTime = time?.trim() ?? '';
  if (!date || !normalizedTime) {
    return null;
  }
  const d = date instanceof Date ? new Date(date.getTime()) : new Date(date);
  if (Number.isNaN(d.getTime())) {
    return null;
  }
  const [hours, minutes] = normalizedTime.split(':').map(Number);
  if (!Number.isInteger(hours) || !Number.isInteger(minutes)) {
    return null;
  }
  d.setHours(hours, minutes, 0, 0);
  return d;
}

function arrivalAfterDepartureValidator(group: AbstractControl): ValidationErrors | null {
  const depDate = group.get('departure_date')?.value;
  const depTime = group.get('departure_time')?.value;
  const arrDate = group.get('arrival_date')?.value;
  const arrTime = group.get('arrival_time')?.value;
  const departure = combineDateAndTime(depDate, depTime);
  const arrival = combineDateAndTime(arrDate, arrTime);
  if (departure && arrival && arrival < departure) {
    return { arrivalBeforeDeparture: true };
  }
  return null;
}

interface DispatchConfirmationState {
  title: string;
  message: string;
  hint: string;
}

interface DispatchStateSummary {
  label: string;
  icon: string;
  tone: 'success' | 'warning' | 'muted';
  checks: { label: string; met: boolean }[];
}

@Component({
  selector: 'app-ops-dispatch-workspace',
  standalone: true,
  imports: [
    DatePipe,
    ReactiveFormsModule,
    MatButtonModule,
    MatIconModule,
    MatStepperModule,
    OpsMetricStripComponent,
    OpsDispatchReadinessStepComponent,
    OpsDispatchReviewStepComponent,
    DmisEmptyStateComponent,
    DmisSkeletonLoaderComponent,
    DmisStepTrackerComponent,
  ],
  templateUrl: './dispatch-workspace.component.html',
  styleUrls: ['./dispatch-workspace.component.scss', '../operations-shell.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class OpsDispatchWorkspaceComponent {
  @ViewChild('stepper') stepper?: MatStepper;

  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  private readonly fb = inject(FormBuilder);
  private readonly operationsService = inject(OperationsService);
  private readonly notifications = inject(DmisNotificationService);

  readonly transportForm = this.fb.nonNullable.group({
    transport_mode: [''],
    driver_name: ['', [Validators.required, Validators.maxLength(100)]],
    vehicle_id: ['', [Validators.maxLength(50)]],
    departure_date: [null as Date | null],
    departure_time: [''],
    arrival_date: [null as Date | null],
    arrival_time: [''],
    transport_notes: ['', [Validators.maxLength(500)]],
  }, { validators: arrivalAfterDepartureValidator });
  readonly transportFormValue = toSignal(
    merge(this.transportForm.valueChanges, this.transportForm.statusChanges).pipe(
      startWith(null),
      map(() => this.transportForm.getRawValue()),
    ),
    { initialValue: this.transportForm.getRawValue() },
  );

  readonly contextExpanded = signal(false);
  readonly currentStepIndex = signal(0);
  readonly trackerSteps = computed<StepDefinition[]>(() => [
    {
      label: 'Readiness',
      completed: this.canAdvanceToDispatchReview(),
    },
    {
      label: 'Review & Dispatch',
      completed: this.hasDispatchConfirmation(),
    },
    {
      label: 'Confirmation',
      disabled: !this.hasDispatchConfirmation(),
    },
  ]);

  readonly reliefpkgId = signal(0);
  readonly loading = signal(false);
  readonly loadError = signal<string | null>(null);
  readonly submitting = signal(false);
  readonly dispatchDetail = signal<DispatchDetailResponse | null>(null);
  readonly waybillReadback = signal<WaybillResponse | null>(null);
  readonly confirmationState = signal<DispatchConfirmationState | null>(null);

  readonly itemNameMap = computed<ReadonlyMap<number, string>>(() => {
    const detail = this.dispatchDetail();
    const map = new Map<number, string>();
    // Primary source: top-level items array from dispatch detail response
    const items = detail?.items ?? [];
    for (const item of items) {
      if (item.item_name && !map.has(item.item_id)) {
        const label = item.item_code
          ? `${item.item_name} (${item.item_code})`
          : item.item_name;
        map.set(item.item_id, label);
      }
    }
    // Supplement from allocation lines (backend returns item_code/item_name)
    const lines = detail?.allocation?.allocation_lines ?? [];
    for (const line of lines) {
      if (line.item_name && !map.has(line.item_id)) {
        const label = line.item_code
          ? `${line.item_name} (${line.item_code})`
          : line.item_name;
        map.set(line.item_id, label);
      }
    }
    return map;
  });

  readonly hasCommittedAllocation = computed(() => {
    const alloc = this.dispatchDetail()?.allocation;
    return (alloc?.allocation_lines?.length ?? 0) > 0;
  });

  readonly hasPendingOverride = computed(() => {
    const execStatus = String(this.dispatchDetail()?.execution_status ?? '').trim().toUpperCase();
    return execStatus === 'PENDING_OVERRIDE_APPROVAL';
  });

  readonly alreadyDispatched = computed(() => {
    const detail = this.dispatchDetail();
    if (!detail) {
      return false;
    }
    return detail.status_code === 'D' || !!detail.dispatch_dtime || !!detail.waybill;
  });

  readonly canDispatchNow = computed(() =>
    this.dispatchDetail()?.status_code === 'P'
    && this.hasCommittedAllocation()
    && !this.hasPendingOverride()
    && !this.alreadyDispatched()
    && this.transportFormValue().driver_name.trim().length > 0
  );

  readonly dispatchStateSummary = computed<DispatchStateSummary>(() => {
    const detail = this.dispatchDetail();
    const dispatched = this.alreadyDispatched();
    const receiptConfirmed = !!detail?.received_dtime;
    const reservationReady = this.hasCommittedAllocation() && !this.hasPendingOverride();

    let label: string;
    let icon: string;
    let tone: 'success' | 'warning' | 'muted';

    if (receiptConfirmed) {
      label = 'Receipt Confirmed';
      icon = 'verified';
      tone = 'success';
    } else if (dispatched) {
      label = 'Dispatched';
      icon = 'local_shipping';
      tone = 'success';
    } else if (this.hasPendingOverride()) {
      label = 'Override Pending';
      icon = 'hourglass_top';
      tone = 'warning';
    } else if (reservationReady) {
      label = 'Ready to Dispatch';
      icon = 'check_circle';
      tone = 'success';
    } else {
      label = 'Awaiting Reservation';
      icon = 'pending';
      tone = 'warning';
    }

    return {
      label,
      icon,
      tone,
      checks: [
        { label: 'Reservation committed', met: this.hasCommittedAllocation() },
        { label: 'No pending override', met: !this.hasPendingOverride() },
        { label: 'Dispatch recorded', met: dispatched },
        { label: 'Receipt confirmed', met: receiptConfirmed },
      ],
    };
  });

  readonly primaryActionLabel = computed(() => {
    if (this.alreadyDispatched()) {
      return 'Open Dispatch Confirmation';
    }
    if (!this.hasCommittedAllocation()) {
      return 'Reserve Stock First';
    }
    if (this.hasPendingOverride()) {
      return 'Awaiting Override Approval';
    }
    if (this.canDispatchNow()) {
      return 'Dispatch Now';
    }
    return 'Dispatch Not Ready';
  });

  readonly displayConfirmation = computed<DispatchConfirmationState | null>(() => {
    const explicit = this.confirmationState();
    if (explicit) {
      return explicit;
    }
    if (this.alreadyDispatched()) {
      return {
        title: 'Dispatch Recorded',
        message: 'This package has already been dispatched and has a waybill on record.',
        hint: 'You can track this package from the request list.',
      };
    }
    return null;
  });

  readonly workspaceMetrics = computed<readonly OpsMetricStripItem[]>(() => {
    const detail = this.dispatchDetail();
    return [
      {
        label: 'Request Tracking Number',
        value: detail?.request?.tracking_no || 'Pending',
        hint: 'Visible from reservation through dispatch.',
      },
      {
        label: 'Package Tracking Number',
        value: detail?.tracking_no || 'Pending',
        hint: 'Package-level status reference.',
      },
      {
        label: 'Dispatch Reference',
        value: detail?.waybill?.waybill_no || detail?.allocation?.waybill_no || 'Assigned on dispatch',
        hint: 'Document-style waybill identifier.',
      },
      {
        label: 'Lifecycle Status',
        value: formatExecutionStatus(detail?.execution_status),
        hint: detail ? formatPackageStatus(detail.status_code) : 'Not started',
      },
    ];
  });

  constructor() {
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      const reliefpkgId = Number(params.get('reliefpkgId') ?? 0);
      this.reliefpkgId.set(reliefpkgId);
      this.confirmationState.set(null);
      this.waybillReadback.set(null);
      if (reliefpkgId) {
        this.loadDetail(reliefpkgId);
      }
    });
  }

  refresh(): void {
    const reliefpkgId = this.reliefpkgId();
    if (reliefpkgId) {
      this.loadDetail(reliefpkgId);
    }
  }

  backToQueue(): void {
    this.router.navigate(['/operations/dispatch']);
  }

  openFulfillment(): void {
    const reliefrqstId = this.dispatchDetail()?.request?.reliefrqst_id;
    if (reliefrqstId) {
      this.router.navigate(['/operations/package-fulfillment', reliefrqstId]);
    }
  }

  openWaybill(): void {
    const reliefpkgId = this.reliefpkgId();
    if (reliefpkgId) {
      this.router.navigate(['/operations/dispatch', reliefpkgId, 'waybill']);
    }
  }

  openReceiptConfirmation(): void {
    const reliefpkgId = this.reliefpkgId();
    if (reliefpkgId) {
      this.router.navigate(['/operations/receipt-confirmation', reliefpkgId]);
    }
  }

  onTrackerStepClick(index: number): void {
    this.navigateToStep(index, true);
  }

  goToDispatchReview(): void {
    this.transportForm.markAllAsTouched();
    this.navigateToStep(1, true);
  }

  completeDispatchAction(): void {
    if (!this.reliefpkgId()) {
      return;
    }
    if (this.alreadyDispatched()) {
      this.stepper?.next();
      return;
    }
    if (!this.hasCommittedAllocation()) {
      this.notifications.showError('Reserve stock in the fulfillment workspace before moving to dispatch.');
      return;
    }
    if (this.hasPendingOverride()) {
      this.notifications.showWarning('Dispatch stays blocked while override approval is pending.');
      return;
    }
    this.transportForm.markAllAsTouched();
    if (this.canDispatchNow() && this.transportForm.valid) {
      this.dispatchNow();
      return;
    }
    if (!this.transportForm.valid) {
      this.notifications.showWarning('Please complete all required transport fields before dispatching.');
      return;
    }
    this.notifications.showWarning('Dispatch is not ready yet.');
  }

  resetConfirmation(): void {
    this.confirmationState.set(null);
    if (this.stepper) {
      this.stepper.selectedIndex = 1;
      this.currentStepIndex.set(1);
    }
  }

  formatExecutionStatus(value: unknown): string {
    return formatExecutionStatus(String(value ?? ''));
  }

  formatPackageStatus(value: unknown): string {
    return formatPackageStatus(String(value ?? ''));
  }

  private loadDetail(reliefpkgId: number): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.dispatchDetail.set(null);
    this.waybillReadback.set(null);

    this.operationsService.getDispatchDetail(reliefpkgId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (detail: DispatchDetailResponse) => {
          this.dispatchDetail.set(detail);
          const transport = detail.dispatch?.transport;
          const depParts = this.splitDateTime(transport?.departure_dtime);
          const arrParts = this.splitDateTime(transport?.estimated_arrival_dtime);
          this.transportForm.patchValue({
            transport_mode: transport?.transport_mode || detail.transport_mode || '',
            driver_name: transport?.driver_name || '',
            vehicle_id: transport?.vehicle_registration || transport?.vehicle_id || '',
            departure_date: depParts.date,
            departure_time: depParts.time,
            arrival_date: arrParts.date,
            arrival_time: arrParts.time,
            transport_notes: transport?.transport_notes || '',
          });
          const isDispatched = detail.status_code === 'D' || !!detail.dispatch_dtime || !!detail.waybill;
          if (isDispatched) {
            this.transportForm.disable();
          } else {
            this.transportForm.enable();
          }
          if (detail.waybill) {
            this.waybillReadback.set(detail.waybill);
          }
          this.loading.set(false);
        },
        error: (error: HttpErrorResponse) => {
          this.loading.set(false);
          this.loadError.set(this.extractError(error, 'Failed to load dispatch workspace.'));
        },
      });
  }

  private dispatchNow(): void {
    this.submitting.set(true);
    const formValue = this.transportForm.getRawValue();
    const departure = combineDateAndTime(formValue.departure_date, formValue.departure_time);
    const arrival = combineDateAndTime(formValue.arrival_date, formValue.arrival_time);
    const payload: DispatchHandoffPayload = {
      transport_mode: formValue.transport_mode.trim() || undefined,
      driver_name: formValue.driver_name.trim() || undefined,
      vehicle_registration: formValue.vehicle_id.trim() || undefined,
      departure_dtime: departure?.toISOString() || undefined,
      estimated_arrival_dtime: arrival?.toISOString() || undefined,
      transport_notes: formValue.transport_notes.trim() || undefined,
    };
    this.operationsService.submitDispatchHandoff(
      this.reliefpkgId(),
      payload
    ).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (response: DispatchHandoffResponse) => {
        this.submitting.set(false);
        this.confirmationState.set({
          title: 'Dispatch Recorded',
          message: 'Reserved stock has been dispatched and physically deducted from inventory.',
          hint: 'Distribution confirmation remains out of scope. Use the request tracker for ongoing status visibility.',
        });
        // Reload the detail to pick up the updated status and waybill
        this.loadDetail(this.reliefpkgId());
        // Also build a WaybillResponse from the handoff response for immediate display
        this.waybillReadback.set({
          waybill_no: response.waybill_no,
          waybill_payload: response.waybill_payload,
          persisted: false,
          artifact_mode: response.waybill_artifact_mode || 'deterministic_rebuild',
        });
        this.notifications.showSuccess('Dispatch recorded and waybill reference updated.');
        queueMicrotask(() => {
          if (this.stepper) {
            this.stepper.selectedIndex = 2;
            this.currentStepIndex.set(2);
          }
        });
      },
      error: (error: HttpErrorResponse) => {
        this.submitting.set(false);
        this.notifications.showError(this.extractError(error, 'Failed to record dispatch.'));
      },
    });
  }

  private extractError(error: HttpErrorResponse, fallback: string): string {
    const errorMap = error.error?.errors;
    if (errorMap && typeof errorMap === 'object') {
      const messages = Object.values(errorMap)
        .flatMap((value) => Array.isArray(value) ? value : [value])
        .map((value) => String(value ?? '').trim())
        .filter(Boolean);
      if (messages.length) {
        return messages[0];
      }
    }
    const directMessage = typeof error.error?.message === 'string' ? error.error.message.trim() : '';
    const detail = typeof error.error?.detail === 'string' ? error.error.detail.trim() : '';
    return directMessage || detail || fallback;
  }

  private splitDateTime(value: string | null | undefined): { date: Date | null; time: string } {
    if (!value) {
      return { date: null, time: '' };
    }
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
      return { date: null, time: '' };
    }
    const hh = String(parsed.getHours()).padStart(2, '0');
    const mm = String(parsed.getMinutes()).padStart(2, '0');
    return { date: parsed, time: `${hh}:${mm}` };
  }

  private navigateToStep(index: number, showValidationMessages = false): void {
    const stepper = this.stepper;
    if (!stepper) {
      return;
    }

    const currentIndex = stepper.selectedIndex;
    const targetStep = stepper.steps.toArray()[index];
    if (!targetStep) {
      return;
    }

    if (index === currentIndex) {
      this.currentStepIndex.set(index);
      return;
    }

    if (targetStep.editable === false) {
      return;
    }

    if (index > currentIndex) {
      for (let stepIndex = currentIndex; stepIndex < index; stepIndex += 1) {
        if (!this.canLeaveStep(stepIndex, showValidationMessages)) {
          return;
        }
      }
    }

    stepper.selectedIndex = index;
    this.currentStepIndex.set(index);
  }

  private canLeaveStep(stepIndex: number, showValidationMessages: boolean): boolean {
    if (stepIndex === 0) {
      return this.validateDispatchReviewAccess(showValidationMessages);
    }
    return true;
  }

  private canAdvanceToDispatchReview(): boolean {
    return this.getDispatchReviewBlocker() === null;
  }

  private hasDispatchConfirmation(): boolean {
    return this.displayConfirmation() !== null;
  }

  private validateDispatchReviewAccess(showValidationMessages: boolean): boolean {
    const blocker = this.getDispatchReviewBlocker();
    if (!blocker) {
      return true;
    }

    if (showValidationMessages) {
      if (blocker.tone === 'warning') {
        this.notifications.showWarning(blocker.message);
      } else {
        this.notifications.showError(blocker.message);
      }
    }
    return false;
  }

  private getDispatchReviewBlocker(): { message: string; tone: 'error' | 'warning' } | null {
    if (!this.hasCommittedAllocation()) {
      return {
        message: 'Reserve stock in the fulfillment workspace before moving to dispatch.',
        tone: 'error',
      };
    }
    if (this.hasPendingOverride()) {
      return {
        message: 'Dispatch stays blocked while override approval is pending.',
        tone: 'warning',
      };
    }
    return null;
  }
}
