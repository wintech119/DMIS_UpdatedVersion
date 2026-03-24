import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, DestroyRef, ViewChild, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatIconModule } from '@angular/material/icon';
import { MatStepper, MatStepperModule } from '@angular/material/stepper';

import { DispatchReadinessStepComponent } from './steps/dispatch-readiness-step.component';
import { DispatchReviewStepComponent } from './steps/dispatch-review-step.component';
import { DmisEmptyStateComponent } from '../shared/dmis-empty-state/dmis-empty-state.component';
import { DmisSkeletonLoaderComponent } from '../shared/dmis-skeleton-loader/dmis-skeleton-loader.component';
import { DmisApprovalStatusTrackerComponent } from '../shared/dmis-approval-status-tracker/dmis-approval-status-tracker.component';
import { NeedsListResponse } from '../models/needs-list.model';
import { ExecutionWorkspaceStateService } from '../execution/services/execution-workspace-state.service';
import { DmisNotificationService } from '../services/notification.service';
import { ReplenishmentService } from '../services/replenishment.service';
import { formatExecutionStatus, formatPackageStatus } from '../execution/execution-status.util';

interface DispatchConfirmationState {
  title: string;
  message: string;
  hint: string;
}

@Component({
  selector: 'app-dispatch-workspace',
  standalone: true,
  imports: [
    MatButtonModule,
    MatCardModule,
    MatIconModule,
    MatStepperModule,
    DispatchReadinessStepComponent,
    DispatchReviewStepComponent,
    DmisApprovalStatusTrackerComponent,
    DmisEmptyStateComponent,
    DmisSkeletonLoaderComponent,
  ],
  providers: [ExecutionWorkspaceStateService],
  templateUrl: './dispatch-workspace.component.html',
  styleUrl: './dispatch-workspace.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DispatchWorkspaceComponent {
  @ViewChild('stepper') stepper?: MatStepper;

  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  private readonly service = inject(ReplenishmentService);
  private readonly notifications = inject(DmisNotificationService);
  readonly store = inject(ExecutionWorkspaceStateService);

  readonly current = this.store.current;
  readonly needsListId = signal('');
  readonly confirmationState = signal<DispatchConfirmationState | null>(null);

  readonly approvalHorizon = computed(() => this.resolveApprovalHorizon(this.current()));

  readonly hasDispatchableReservation = computed(() =>
    this.store.hasCommittedAllocation() && !this.store.hasPendingOverride()
  );

  readonly needsPreparation = computed(() =>
    String(this.current()?.status ?? '').trim().toUpperCase() === 'APPROVED' && this.hasDispatchableReservation()
  );

  readonly canDispatchNow = computed(() =>
    String(this.current()?.status ?? '').trim().toUpperCase() === 'IN_PREPARATION' && this.hasDispatchableReservation()
  );

  readonly alreadyDispatched = computed(() => {
    const executionStatus = String(this.current()?.execution_status ?? '').trim().toUpperCase();
    return executionStatus === 'DISPATCHED' || !!this.current()?.dispatch_dtime || !!this.current()?.waybill_no;
  });

  readonly primaryActionLabel = computed(() => {
    if (this.alreadyDispatched()) {
      return 'Open Dispatch Confirmation';
    }
    if (!this.store.hasCommittedAllocation()) {
      return 'Reserve Stock First';
    }
    if (this.store.hasPendingOverride()) {
      return 'Awaiting Override Approval';
    }
    if (this.needsPreparation()) {
      return 'Start Preparation';
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
        message: 'This needs list already has a recorded dispatch and waybill reference.',
        hint: 'Distribution confirmation remains out of scope for Sprint 08. Use the tracker for continued visibility.',
      };
    }
    return null;
  });

  constructor() {
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      const needsListId = String(params.get('id') ?? '').trim();
      this.needsListId.set(needsListId);
      this.confirmationState.set(null);
      if (needsListId) {
        this.store.load(needsListId, false);
      }
    });
  }

  refresh(): void {
    const needsListId = this.needsListId();
    if (!needsListId) {
      return;
    }
    this.store.load(needsListId, false);
  }

  backToTracker(): void {
    const needsListId = this.needsListId();
    if (!needsListId) {
      this.router.navigate(['/replenishment/my-submissions']);
      return;
    }
    this.router.navigate(['/replenishment/needs-list', needsListId, 'track']);
  }

  openAllocation(): void {
    const needsListId = this.needsListId();
    if (!needsListId) {
      return;
    }
    this.router.navigate(['/replenishment/needs-list', needsListId, 'allocation']);
  }

  goToDispatchReview(): void {
    if (!this.store.hasCommittedAllocation()) {
      this.notifications.showError('Reserve stock in the allocation workspace before moving to dispatch.');
      return;
    }
    if (this.store.hasPendingOverride()) {
      this.notifications.showWarning('Dispatch stays blocked while override approval is pending.');
      return;
    }
    this.stepper?.next();
  }

  completeDispatchAction(): void {
    if (!this.needsListId()) {
      return;
    }
    if (this.alreadyDispatched()) {
      this.stepper?.next();
      return;
    }
    if (!this.store.hasCommittedAllocation()) {
      this.notifications.showError('Reserve stock in the allocation workspace before moving to dispatch.');
      return;
    }
    if (this.store.hasPendingOverride()) {
      this.notifications.showWarning('Dispatch stays blocked while override approval is pending.');
      return;
    }
    if (this.needsPreparation()) {
      this.startPreparation();
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
    }
  }

  formatExecutionStatus(value: unknown): string {
    return formatExecutionStatus(String(value ?? ''));
  }

  formatPackageStatus(value: unknown): string {
    return formatPackageStatus(String(value ?? ''));
  }

  private startPreparation(): void {
    this.store.setStartPreparationLoading(true);
    this.service.startPreparation(this.needsListId()).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: () => {
        this.store.setStartPreparationLoading(false);
        this.store.load(this.needsListId(), false);
        this.notifications.showSuccess('Preparation started. You can now record dispatch when loading is complete.');
      },
      error: (error: HttpErrorResponse) => {
        this.store.setStartPreparationLoading(false);
        this.notifications.showError(this.extractError(error, 'Failed to start preparation.'));
      },
    });
  }

  private dispatchNow(): void {
    this.store.setSubmitting(true);
    const transportMode = this.store.draft().transport_mode.trim();
    this.service.markDispatched(
      this.needsListId(),
      transportMode ? { transport_mode: transportMode } : {}
    ).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (response) => {
        this.store.setSubmitting(false);
        this.confirmationState.set({
          title: 'Dispatch Recorded',
          message: 'Reserved stock has been dispatched and physically deducted from inventory.',
          hint: 'Distribution confirmation remains out of scope for Sprint 08. Use the tracker for ongoing status visibility.',
        });
        this.store.current.set(response);
        this.store.refreshCurrent();
        if (response.waybill_no) {
          this.store.loadWaybill();
        }
        this.notifications.showSuccess('Dispatch recorded and waybill reference updated.');
        queueMicrotask(() => {
          if (this.stepper) {
            this.stepper.selectedIndex = 2;
          }
        });
      },
      error: (error: HttpErrorResponse) => {
        this.store.setSubmitting(false);
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
