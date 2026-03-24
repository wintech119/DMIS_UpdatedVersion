import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, DestroyRef, ViewChild, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatIconModule } from '@angular/material/icon';
import { MatStepper, MatStepperModule } from '@angular/material/stepper';

import { AllocationDetailsStepComponent } from './steps/allocation-details-step.component';
import { AllocationPlanStepComponent } from './steps/allocation-plan-step.component';
import { AllocationReviewStepComponent } from './steps/allocation-review-step.component';
import { DmisEmptyStateComponent } from '../shared/dmis-empty-state/dmis-empty-state.component';
import { DmisSkeletonLoaderComponent } from '../shared/dmis-skeleton-loader/dmis-skeleton-loader.component';
import { DmisApprovalStatusTrackerComponent } from '../shared/dmis-approval-status-tracker/dmis-approval-status-tracker.component';
import { NeedsListResponse } from '../models/needs-list.model';
import { ExecutionWorkspaceStateService } from '../execution/services/execution-workspace-state.service';
import { DmisNotificationService } from '../services/notification.service';
import { ReplenishmentService } from '../services/replenishment.service';
import { AuthRbacService } from '../services/auth-rbac.service';
import { formatExecutionMethod, formatExecutionStatus, isOverrideApproverRole } from '../execution/execution-status.util';

interface AllocationConfirmationState {
  title: string;
  message: string;
  hint: string;
}

const ALLOCATION_READY_STATUSES = new Set(['APPROVED', 'IN_PREPARATION', 'IN_PROGRESS']);

@Component({
  selector: 'app-allocation-workspace',
  standalone: true,
  imports: [
    MatButtonModule,
    MatCardModule,
    MatIconModule,
    MatStepperModule,
    AllocationPlanStepComponent,
    AllocationDetailsStepComponent,
    AllocationReviewStepComponent,
    DmisApprovalStatusTrackerComponent,
    DmisEmptyStateComponent,
    DmisSkeletonLoaderComponent,
  ],
  providers: [ExecutionWorkspaceStateService],
  templateUrl: './allocation-workspace.component.html',
  styleUrl: './allocation-workspace.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AllocationWorkspaceComponent {
  @ViewChild('stepper') stepper?: MatStepper;

  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  private readonly service = inject(ReplenishmentService);
  private readonly notifications = inject(DmisNotificationService);
  readonly store = inject(ExecutionWorkspaceStateService);
  readonly auth = inject(AuthRbacService);

  readonly current = this.store.current;
  readonly needsListId = signal('');
  readonly submissionErrors = signal<string[]>([]);
  readonly confirmationState = signal<AllocationConfirmationState | null>(null);

  readonly approvalHorizon = computed(() => this.resolveApprovalHorizon(this.current()));
  readonly canExecute = computed(() => this.auth.hasPermission('replenishment.needs_list.execute'));

  readonly isAllocationOpen = computed(() =>
    ALLOCATION_READY_STATUSES.has(String(this.current()?.status ?? '').trim().toUpperCase())
  );

  readonly canApprovePendingOverride = computed(() => {
    if (!this.store.hasPendingOverride() || !this.canExecute()) {
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

  readonly dispatchRefLabel = computed(() => this.current()?.waybill_no || 'Assigned on dispatch');
  readonly requestTrackingLabel = computed(() => this.current()?.request_tracking_no || 'Created on commit');
  readonly packageTrackingLabel = computed(() => this.current()?.package_tracking_no || 'Created on commit');

  constructor() {
    this.auth.load();
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      const needsListId = String(params.get('id') ?? '').trim();
      this.needsListId.set(needsListId);
      this.confirmationState.set(null);
      this.submissionErrors.set([]);
      if (needsListId) {
        this.store.load(needsListId, true);
      }
    });
  }

  refresh(): void {
    const needsListId = this.needsListId();
    if (!needsListId) {
      return;
    }
    this.submissionErrors.set([]);
    this.store.load(needsListId, true);
  }

  backToTracker(): void {
    const needsListId = this.needsListId();
    if (!needsListId) {
      this.router.navigate(['/replenishment/my-submissions']);
      return;
    }
    this.router.navigate(['/replenishment/needs-list', needsListId, 'track']);
  }

  openDispatch(): void {
    const needsListId = this.needsListId();
    if (!needsListId) {
      return;
    }
    this.router.navigate(['/replenishment/needs-list', needsListId, 'dispatch']);
  }

  formatExecutionStatus(value: unknown): string {
    return formatExecutionStatus(String(value ?? ''));
  }

  formatExecutionMethod(value: unknown): string {
    return formatExecutionMethod(String(value ?? ''));
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
    }
  }

  submitReservation(): void {
    if (!this.needsListId()) {
      return;
    }
    if (!this.isAllocationOpen()) {
      this.notifications.showError('Allocation is available only after approval and during active preparation.');
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
        this.service.approveAllocationOverride(this.needsListId(), payload),
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
    this.runAllocationAction(this.service.commitAllocation(this.needsListId(), payload), 'commit');
  }

  private runAllocationAction(
    request$: ReturnType<ReplenishmentService['commitAllocation']>,
    mode: 'commit' | 'override_approved'
  ): void {
    this.store.setSubmitting(true);
    request$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (response) => {
        this.store.setSubmitting(false);
        this.submissionErrors.set([]);
        this.confirmationState.set(this.buildConfirmationState(response, mode));
        this.store.current.set(response);
        this.store.refreshCurrent();
        if (response.waybill_no) {
          this.store.loadWaybill();
        }
        if (mode === 'override_approved') {
          this.notifications.showSuccess('Override approved. Reservation can continue into dispatch.');
        } else if (
          String(response.execution_status ?? '').trim().toUpperCase() === 'PENDING_OVERRIDE_APPROVAL'
          || !!response.override_required
        ) {
          this.notifications.showWarning('Reservation plan submitted for override approval.');
        } else {
          this.notifications.showSuccess('Reservation committed. Stock is now frozen for dispatch.');
        }
        queueMicrotask(() => {
          if (this.stepper) {
            this.stepper.selectedIndex = 3;
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
    if (!this.isAllocationOpen()) {
      errors.push('Allocation is available only after approval and during active preparation.');
    }
    if (!(this.store.options()?.items ?? []).length) {
      errors.push('Allocation options are not available for this needs list.');
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
    if (this.store.requiresFirstCommitDetails()) {
      const agencyId = Number(draft.agency_id);
      if (!Number.isInteger(agencyId) || agencyId <= 0) {
        errors.push('Receiving agency ID is required for the first formal allocation.');
      }
      if (!draft.urgency_ind) {
        errors.push('Urgency is required for the first formal allocation.');
      }
    }
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
    response: NeedsListResponse,
    mode: 'commit' | 'override_approved'
  ): AllocationConfirmationState {
    if (mode === 'override_approved') {
      return {
        title: 'Override Approved',
        message: 'The pending bypass has been approved and the reservation can now move into dispatch preparation.',
        hint: 'Stock remains reserved. Physical deduction still happens only when dispatch is recorded.',
      };
    }
    if (
      String(response.execution_status ?? '').trim().toUpperCase() === 'PENDING_OVERRIDE_APPROVAL'
      || !!response.override_required
    ) {
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

    // `submitted_by` is the original needs-list submitter and `updated_by` is our best available
    // frontend proxy for the user who most recently routed the pending override.
    const blockedActors = [
      this.current()?.submitted_by,
      this.current()?.updated_by,
    ]
      .map((value) => String(value ?? '').trim().toLowerCase())
      .filter(Boolean);

    return blockedActors.includes(currentUser);
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

  private resolveApprovalHorizon(current: NeedsListResponse | null): 'A' | 'B' | 'C' {
    const selectedMethod = String(current?.selected_method ?? '').trim().toUpperCase();
    if (selectedMethod === 'A' || selectedMethod === 'B' || selectedMethod === 'C') {
      return selectedMethod;
    }
    const items = current?.items ?? [];
    if (items.some((item) => Number(item.horizon?.C?.recommended_qty ?? 0) > 0)) {
      return 'C';
    }
    if (items.some((item) => Number(item.horizon?.B?.recommended_qty ?? 0) > 0)) {
      return 'B';
    }
    return 'A';
  }
}
