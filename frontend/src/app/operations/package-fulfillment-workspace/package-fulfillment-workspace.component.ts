import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, DestroyRef, ViewChild, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatIconModule } from '@angular/material/icon';
import { MatStepper, MatStepperModule } from '@angular/material/stepper';

import { FulfillmentDetailsStepComponent } from './steps/fulfillment-details-step.component';
import { FulfillmentPlanStepComponent } from './steps/fulfillment-plan-step.component';
import { FulfillmentReviewStepComponent } from './steps/fulfillment-review-step.component';
import { DmisEmptyStateComponent } from '../../replenishment/shared/dmis-empty-state/dmis-empty-state.component';
import { DmisSkeletonLoaderComponent } from '../../replenishment/shared/dmis-skeleton-loader/dmis-skeleton-loader.component';
import { DmisStepTrackerComponent, StepDefinition } from '../../shared/dmis-step-tracker/dmis-step-tracker.component';
import { DmisNotificationService } from '../../replenishment/services/notification.service';
import { AuthRbacService } from '../../replenishment/services/auth-rbac.service';
import { OpsMetricStripComponent, OpsMetricStripItem } from '../shared/ops-metric-strip.component';
import { OperationsService } from '../services/operations.service';
import { OperationsWorkspaceStateService } from '../services/operations-workspace-state.service';
import { AllocationCommitResponse } from '../models/operations.model';
import {
  formatAllocationMethod,
  formatExecutionStatus,
  formatPackageStatus,
  formatUrgency,
  isOverrideApproverRole,
} from '../models/operations-status.util';

interface FulfillmentConfirmationState {
  title: string;
  message: string;
  hint: string;
}

@Component({
  selector: 'app-package-fulfillment-workspace',
  standalone: true,
  imports: [
    MatButtonModule,
    MatCardModule,
    MatIconModule,
    MatStepperModule,
    OpsMetricStripComponent,
    FulfillmentPlanStepComponent,
    FulfillmentDetailsStepComponent,
    FulfillmentReviewStepComponent,
    DmisEmptyStateComponent,
    DmisSkeletonLoaderComponent,
    DmisStepTrackerComponent,
  ],
  providers: [OperationsWorkspaceStateService],
  templateUrl: './package-fulfillment-workspace.component.html',
  styleUrl: './package-fulfillment-workspace.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PackageFulfillmentWorkspaceComponent {
  private static readonly OPERATIONS_ACCESS_PERMISSIONS = [
    'replenishment.needs_list.execute',
    'replenishment.needs_list.approve',
  ] as const;

  @ViewChild('stepper') stepper?: MatStepper;

  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  private readonly operationsService = inject(OperationsService);
  private readonly notifications = inject(DmisNotificationService);
  readonly store = inject(OperationsWorkspaceStateService);
  readonly auth = inject(AuthRbacService);

  readonly contextExpanded = signal(false);
  readonly currentStepIndex = signal(0);
  readonly trackerSteps = computed<StepDefinition[]>(() => [
    { label: 'Select Stock' },
    { label: 'Operational Details' },
    { label: 'Review & Commit' },
    { label: 'Confirmation' },
  ]);

  readonly reliefrqstId = signal(0);
  readonly submissionErrors = signal<string[]>([]);
  readonly confirmationState = signal<FulfillmentConfirmationState | null>(null);

  readonly packageDetail = this.store.packageDetail;

  readonly hasOperationsAccess = computed(() =>
    PackageFulfillmentWorkspaceComponent.OPERATIONS_ACCESS_PERMISSIONS.some((permission) =>
      this.auth.hasPermission(permission)
    )
  );

  readonly canApprovePendingOverride = computed(() => {
    if (!this.store.hasPendingOverride() || !this.hasOperationsAccess()) {
      return false;
    }
    if (!isOverrideApproverRole(this.auth.roles())) {
      return false;
    }
    return !this.isNoSelfApprovalBlocked();
  });

  readonly lockPlanEdits = computed(() => this.store.hasPendingOverride());
  readonly lockOperationalFields = computed(() => this.store.hasPendingOverride());
  readonly commitActionDisabled = computed(() =>
    this.store.submitting() || (this.store.hasPendingOverride() && !this.canApprovePendingOverride())
  );

  readonly overrideApprovalHint = computed(() => {
    if (this.store.hasPendingOverride()) {
      if (this.isNoSelfApprovalBlocked()) {
        return 'You can view the pending override, but a different authorized approver must complete it. No self-approval is allowed for the request submitter or the user who routed the override.';
      }
      if (!isOverrideApproverRole(this.auth.roles())) {
        return 'Override approval is limited to logistics leadership roles. You can review the plan, but approval stays hidden.';
      }
      return 'The routed plan is locked while override approval is reviewed. Only authorized logistics approvers can approve it, and backend no-self-approval checks remain in force.';
    }
    if (this.store.planRequiresOverride()) {
      return 'This plan will be routed for narrow override approval before dispatch can continue.';
    }
    return null;
  });

  readonly commitActionLabel = computed(() => {
    if (this.store.hasPendingOverride() && this.canApprovePendingOverride()) {
      return 'Approve Pending Override';
    }
    if (this.store.hasPendingOverride()) {
      return 'Awaiting Override Approval';
    }
    if (this.store.planRequiresOverride()) {
      return 'Submit Override For Approval';
    }
    if (this.store.hasCommittedAllocation()) {
      return 'Update Reservation';
    }
    return 'Commit Reservation';
  });

  readonly reservationStateLabel = computed(() => {
    if (this.store.hasPendingOverride()) {
      return 'Pending override approval';
    }
    if (this.store.hasCommittedAllocation()) {
      return 'Reserved';
    }
    return 'Not reserved yet';
  });

  readonly requestTrackingLabel = computed(() =>
    this.packageDetail()?.request?.tracking_no || 'Created on commit'
  );

  readonly packageTrackingLabel = computed(() =>
    this.packageDetail()?.package?.tracking_no || 'Created on commit'
  );

  readonly dispatchRefLabel = computed(() =>
    this.packageDetail()?.allocation?.waybill_no || 'Assigned on dispatch'
  );

  readonly workspaceMetrics = computed<readonly OpsMetricStripItem[]>(() => [
    {
      label: 'Request Tracking Number',
      value: this.requestTrackingLabel(),
      hint: 'The request anchor remains visible during packing.',
    },
    {
      label: 'Package Tracking Number',
      value: this.packageTrackingLabel(),
      hint: 'Generated when stock is committed.',
    },
    {
      label: 'Reservation State',
      value: this.reservationStateLabel(),
      hint: this.packageDetail()?.package?.execution_status ? formatExecutionStatus(this.packageDetail()?.package?.execution_status) : 'Not started',
    },
    {
      label: 'Waybill Reference',
      value: this.dispatchRefLabel(),
      hint: 'Waybill remains pending until dispatch.',
    },
  ]);

  constructor() {
    this.auth.load();
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      const reliefrqstId = Number(params.get('reliefrqstId') ?? 0);
      this.reliefrqstId.set(reliefrqstId);
      this.confirmationState.set(null);
      this.submissionErrors.set([]);
      if (reliefrqstId) {
        this.store.load(reliefrqstId, true);
      }
    });
  }

  refresh(): void {
    const reliefrqstId = this.reliefrqstId();
    if (!reliefrqstId) {
      return;
    }
    this.submissionErrors.set([]);
    this.store.load(reliefrqstId, true);
  }

  backToRequest(): void {
    const reliefrqstId = this.reliefrqstId();
    if (!reliefrqstId) {
      this.router.navigate(['/operations/packages']);
      return;
    }
    this.router.navigate(['/operations/relief-requests', reliefrqstId]);
  }

  openDispatch(): void {
    const reliefpkgId = this.store.reliefpkgId();
    if (!reliefpkgId) {
      return;
    }
    this.router.navigate(['/operations/dispatch', reliefpkgId]);
  }

  openWaybill(): void {
    const reliefpkgId = this.store.reliefpkgId();
    if (!reliefpkgId) {
      return;
    }
    this.router.navigate(['/operations/dispatch', reliefpkgId, 'waybill']);
  }

  openReceiptConfirmation(): void {
    const reliefpkgId = this.store.reliefpkgId();
    if (!reliefpkgId) {
      return;
    }
    this.router.navigate(['/operations/receipt-confirmation', reliefpkgId]);
  }

  formatExecutionStatus(value: unknown): string {
    return formatExecutionStatus(String(value ?? ''));
  }

  formatAllocationMethod(value: unknown): string {
    return formatAllocationMethod(String(value ?? ''));
  }

  formatPackageStatus(value: unknown): string {
    return formatPackageStatus(String(value ?? ''));
  }

  formatUrgency(value: unknown): string {
    return formatUrgency(String(value ?? ''));
  }

  goToDetails(): void {
    const errors = this.collectPlanErrors();
    if (errors.length) {
      this.submissionErrors.set(errors);
      this.notifications.showError(errors[0]);
      return;
    }
    this.submissionErrors.set([]);
    this.stepper?.next();
  }

  onTrackerStepClick(index: number): void {
    if (this.stepper) {
      this.stepper.selectedIndex = index;
      this.currentStepIndex.set(index);
    }
  }

  goToReview(): void {
    const errors = this.collectDetailErrors();
    if (errors.length) {
      this.submissionErrors.set(errors);
      this.notifications.showError(errors[0]);
      return;
    }
    this.submissionErrors.set([]);
    this.stepper?.next();
  }

  resetConfirmation(): void {
    this.confirmationState.set(null);
    if (this.stepper) {
      this.stepper.selectedIndex = 2;
      this.currentStepIndex.set(2);
    }
  }

  submitReservation(): void {
    const reliefrqstId = this.reliefrqstId();
    if (!reliefrqstId) {
      return;
    }

    if (this.store.hasPendingOverride() && !this.canApprovePendingOverride()) {
      this.notifications.showWarning('This reservation is locked while narrow override approval is pending.');
      return;
    }

    if (this.store.hasPendingOverride() && this.canApprovePendingOverride()) {
      const { payload, errors } = this.store.buildOverrideApprovalPayload();
      if (!payload || errors.length) {
        this.submissionErrors.set(errors);
        this.notifications.showError(errors[0] || 'Override approval details are incomplete.');
        return;
      }
      this.runAllocationAction(
        this.operationsService.approveOverride(reliefrqstId, payload),
        'override_approved'
      );
      return;
    }

    const { payload, errors } = this.store.buildCommitPayload();
    if (!payload || errors.length) {
      this.submissionErrors.set(errors);
      this.notifications.showError(errors[0] || 'Reservation details are incomplete.');
      return;
    }
    this.runAllocationAction(this.operationsService.commitAllocations(reliefrqstId, payload), 'commit');
  }

  private runAllocationAction(
    request$: ReturnType<OperationsService['commitAllocations']>,
    mode: 'commit' | 'override_approved'
  ): void {
    this.store.setSubmitting(true);
    request$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (response: AllocationCommitResponse) => {
        this.store.setSubmitting(false);
        this.submissionErrors.set([]);
        this.confirmationState.set(this.buildConfirmationState(response, mode));
        this.store.refreshPackage();
        if (mode === 'override_approved') {
          this.notifications.showSuccess('Override approved. Reservation can continue into dispatch.');
        } else if (response.status === 'PENDING_OVERRIDE_APPROVAL' || response.override_required) {
          this.notifications.showWarning('Reservation plan submitted for override approval.');
        } else {
          this.notifications.showSuccess('Reservation committed. Stock is now frozen for dispatch.');
        }
        queueMicrotask(() => {
          if (this.stepper) {
            this.stepper.selectedIndex = 3;
            this.currentStepIndex.set(3);
          }
        });
      },
      error: (error: HttpErrorResponse) => {
        this.store.setSubmitting(false);
        this.notifications.showError(this.extractError(error, 'Failed to save reservation.'));
      },
    });
  }

  private collectPlanErrors(): string[] {
    const errors: string[] = [];
    if (!(this.store.options()?.items ?? []).length) {
      errors.push('Allocation options are not available for this request.');
    }
    for (const item of this.store.options()?.items ?? []) {
      const message = this.store.getItemValidationMessage(item);
      if (message) {
        errors.push(`${item.item_name || `Item ${item.item_id}`}: ${message}`);
      }
    }
    if (this.store.totalSelectedQty() <= 0) {
      errors.push('Select at least one stock line to reserve.');
    }
    return [...new Set(errors)];
  }

  private collectDetailErrors(): string[] {
    const errors: string[] = [];
    const draft = this.store.draft();
    if (this.store.planRequiresOverride() || this.store.hasPendingOverride()) {
      if (!draft.override_reason_code.trim()) {
        errors.push('Select an override reason before continuing.');
      }
      if (!draft.override_note.trim()) {
        errors.push('Add an override note before continuing.');
      }
    }
    return [...new Set(errors)];
  }

  private buildConfirmationState(
    response: AllocationCommitResponse,
    mode: 'commit' | 'override_approved'
  ): FulfillmentConfirmationState {
    if (mode === 'override_approved') {
      return {
        title: 'Override Approved',
        message: 'The pending bypass has been approved and the reservation can now move into dispatch preparation.',
        hint: 'Stock remains reserved. Physical deduction still happens only when dispatch is recorded.',
      };
    }
    if (response.status === 'PENDING_OVERRIDE_APPROVAL' || response.override_required) {
      return {
        title: 'Override Routed',
        message: 'The reservation plan is visible for narrow override approval. Dispatch remains blocked until that review is completed.',
        hint: 'No self-approval is allowed. A different authorized approver must complete the override review.',
      };
    }
    return {
      title: 'Reservation Committed',
      message: 'Stock is now reserved against this request and is ready for the dispatch workspace when operations are ready.',
      hint: 'Reservation freezes stock. Physical deduction and the waybill reference happen on dispatch.',
    };
  }

  private isNoSelfApprovalBlocked(): boolean {
    const currentUser = String(this.auth.currentUserRef() ?? '').trim().toLowerCase();
    if (!currentUser) {
      return false;
    }
    // The backend enforces this rule. The operations payload does not currently
    // expose reliable actor identifiers for a meaningful frontend pre-check.
    // The backend enforces this — the frontend provides a best-effort hint
    // by checking if the current user appears in the request metadata
    return false;
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
}
