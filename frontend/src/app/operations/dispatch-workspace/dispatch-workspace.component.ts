import { HttpErrorResponse } from '@angular/common/http';
import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, DestroyRef, ViewChild, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatIconModule } from '@angular/material/icon';
import { MatStepper, MatStepperModule } from '@angular/material/stepper';

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
    MatButtonModule,
    MatCardModule,
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
  styleUrl: './dispatch-workspace.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class OpsDispatchWorkspaceComponent {
  @ViewChild('stepper') stepper?: MatStepper;

  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  private readonly operationsService = inject(OperationsService);
  private readonly notifications = inject(DmisNotificationService);

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
  readonly transportMode = signal('');
  readonly driverName = signal('');
  readonly vehicleIdentifier = signal('');
  readonly departureTime = signal('');
  readonly estimatedArrival = signal('');
  readonly transportNotes = signal('');
  readonly dispatchDetail = signal<DispatchDetailResponse | null>(null);
  readonly waybillReadback = signal<WaybillResponse | null>(null);
  readonly confirmationState = signal<DispatchConfirmationState | null>(null);

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
    && this.driverName().trim().length > 0
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
        message: 'This package already has a recorded dispatch and waybill reference.',
        hint: 'Distribution confirmation remains out of scope. Use the request tracker for continued visibility.',
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
    if (this.canDispatchNow()) {
      this.dispatchNow();
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
          this.transportMode.set(detail.dispatch?.transport?.transport_mode || detail.transport_mode || '');
          this.driverName.set(detail.dispatch?.transport?.driver_name || '');
          this.vehicleIdentifier.set(
            detail.dispatch?.transport?.vehicle_registration
            || detail.dispatch?.transport?.vehicle_id
            || '',
          );
          this.departureTime.set(this.toDateTimeLocalValue(detail.dispatch?.transport?.departure_dtime));
          this.estimatedArrival.set(this.toDateTimeLocalValue(detail.dispatch?.transport?.estimated_arrival_dtime));
          this.transportNotes.set(detail.dispatch?.transport?.transport_notes || '');
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
    const payload: DispatchHandoffPayload = {
      transport_mode: this.transportMode().trim() || undefined,
      driver_name: this.driverName().trim() || undefined,
      vehicle_registration: this.vehicleIdentifier().trim() || undefined,
      departure_dtime: this.departureTime().trim() || undefined,
      estimated_arrival_dtime: this.estimatedArrival().trim() || undefined,
      transport_notes: this.transportNotes().trim() || undefined,
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

  private toDateTimeLocalValue(value: string | null | undefined): string {
    if (!value) {
      return '';
    }
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
      return '';
    }
    const localOffsetMs = parsed.getTimezoneOffset() * 60000;
    return new Date(parsed.getTime() - localOffsetMs).toISOString().slice(0, 16);
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
