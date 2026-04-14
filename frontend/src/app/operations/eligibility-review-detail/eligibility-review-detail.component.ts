import { ChangeDetectionStrategy, Component, DestroyRef, OnInit, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpErrorResponse } from '@angular/common/http';

import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatDialog } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';

import { AppAccessService } from '../../core/app-access.service';
import { DmisConfirmDialogComponent, ConfirmDialogData } from '../../replenishment/shared/dmis-confirm-dialog/dmis-confirm-dialog.component';
import { DmisEmptyStateComponent } from '../../replenishment/shared/dmis-empty-state/dmis-empty-state.component';
import { DmisNotificationService } from '../../replenishment/services/notification.service';
import { DmisReasonDialogComponent, DmisReasonDialogData, DmisReasonDialogResult } from '../../replenishment/shared/dmis-reason-dialog/dmis-reason-dialog.component';
import { DmisSkeletonLoaderComponent } from '../../replenishment/shared/dmis-skeleton-loader/dmis-skeleton-loader.component';
import { OpsStatusChipComponent } from '../shared/ops-status-chip.component';
import { OperationsService } from '../services/operations.service';
import { EligibilityDetailResponse, EligibilityDecisionPayload, RequestItem } from '../models/operations.model';
import {
  formatOperationsDateTime,
  formatOperationsLineCount,
  formatOperationsRequestStatus,
  formatOperationsUrgency,
  getRequestFulfillmentEntryAction,
  OperationsTone,
  extractOperationsErrorMessage,
  getOperationsRequestTone,
  getOperationsUrgencyTone,
  mapOperationsToneToChipTone,
} from '../operations-display.util';

interface WorkflowStep {
  label: string;
  detail: string;
  tone: 'draft' | 'review' | 'success' | 'warning' | 'danger' | 'muted';
}

@Component({
  selector: 'app-eligibility-review-detail',
  standalone: true,
  imports: [
    MatButtonModule,
    MatCardModule,
    MatIconModule,
    MatTooltipModule,
    DmisEmptyStateComponent,
    DmisSkeletonLoaderComponent,
    OpsStatusChipComponent,
  ],
  templateUrl: './eligibility-review-detail.component.html',
  styleUrls: ['./eligibility-review-detail.component.scss', '../operations-shell.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class EligibilityReviewDetailComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly operationsService = inject(OperationsService);
  private readonly dialog = inject(MatDialog);
  private readonly notify = inject(DmisNotificationService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly appAccess = inject(AppAccessService);

  readonly loading = signal(true);
  readonly error = signal<string | null>(null);
  readonly detail = signal<EligibilityDetailResponse | null>(null);
  readonly submitting = signal(false);

  readonly formatOperationsRequestStatus = formatOperationsRequestStatus;
  readonly formatOperationsUrgency = formatOperationsUrgency;
  readonly formatOperationsDateTime = formatOperationsDateTime;
  readonly formatOperationsLineCount = formatOperationsLineCount;
  readonly getOperationsRequestTone = getOperationsRequestTone;
  readonly getOperationsUrgencyTone = getOperationsUrgencyTone;

  readonly statusTone = computed(() => this.getOperationsRequestTone(this.detail()?.status_code));
  readonly canDecide = computed(() => {
    const detail = this.detail();
    return detail ? detail.can_edit && !detail.decision_made : false;
  });
  readonly fulfillmentEntryAction = computed(() => {
    const detail = this.detail();
    if (!detail) {
      return null;
    }
    return getRequestFulfillmentEntryAction(detail, this.appAccess.canAccessNavKey('operations.fulfillment'));
  });

  readonly decisionLabel = computed(() => {
    const detail = this.detail();
    if (!detail) {
      return 'Pending';
    }
    if (!detail.decision_made) {
      return 'Not decided';
    }
    if (detail.status_code === 'INELIGIBLE') {
      return 'Ineligible';
    }
    return detail.status_code === 'REJECTED' ? 'Rejected' : 'Approved';
  });

  readonly workflow = computed<WorkflowStep[]>(() => {
    const detail = this.detail();
    if (!detail) {
      return [];
    }

    return [
      {
        label: 'Submitted',
        detail: detail.create_dtime ? 'Request queued for review' : 'Pending submission',
        tone: detail.create_dtime ? 'review' : 'draft',
      },
      {
        label: 'Eligibility',
        detail: detail.decision_made ? 'Decision recorded' : 'Decision pending',
        tone: detail.decision_made ? 'success' : 'warning',
      },
      {
        label: 'Fulfillment',
        detail: detail.status_code === 'APPROVED_FOR_FULFILLMENT' || detail.status_code === 'FULFILLED' || detail.status_code === 'PARTIALLY_FULFILLED'
          ? 'Ready for packing'
          : 'Blocked until approval',
        tone: detail.status_code === 'APPROVED_FOR_FULFILLMENT' || detail.status_code === 'FULFILLED' || detail.status_code === 'PARTIALLY_FULFILLED'
          ? 'success'
          : 'muted',
      },
    ];
  });

  ngOnInit(): void {
    const reliefrqstId = Number(this.route.snapshot.paramMap.get('reliefrqstId'));
    if (!reliefrqstId) {
      this.error.set('Invalid request ID.');
      this.loading.set(false);
      return;
    }
    this.loadDetail(reliefrqstId);
  }

  loadDetail(reliefrqstId = Number(this.route.snapshot.paramMap.get('reliefrqstId'))): void {
    this.loading.set(true);
    this.error.set(null);

    this.operationsService.getEligibilityDetail(reliefrqstId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (data) => {
          this.detail.set(data);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.error.set(err.status === 404 ? 'Eligibility review not found.' : 'Failed to load eligibility review.');
        },
      });
  }

  goBack(): void {
    this.router.navigate(['/operations/eligibility-review']);
  }

  approve(): void {
    const detail = this.detail();
    if (!detail) {
      return;
    }

    const dialogRef = this.dialog.open(DmisConfirmDialogComponent, {
      width: '480px',
      data: {
        title: 'Approve Request',
        message: `Approve ${detail.tracking_no ?? 'request #' + detail.reliefrqst_id} and move it into fulfillment?`,
        confirmLabel: 'Approve',
        icon: 'check_circle',
        confirmColor: 'primary',
      } satisfies ConfirmDialogData,
    });

    dialogRef.afterClosed()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((confirmed) => {
        if (!confirmed) {
          return;
        }
        this.submitDecision({ decision: 'APPROVED' }, 'Request approved.');
      });
  }

  deny(): void {
    const detail = this.detail();
    if (!detail) {
      return;
    }

    const dialogRef = this.dialog.open(DmisReasonDialogComponent, {
      width: '480px',
      data: {
        title: 'Reject Request',
        actionLabel: 'Reject Request',
        actionColor: 'warn',
      } satisfies DmisReasonDialogData,
    });

    dialogRef.afterClosed()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((result: DmisReasonDialogResult | undefined) => {
        if (result?.reason) {
          this.submitDecision({ decision: 'REJECTED', reason: result.reason }, 'Request rejected.');
        }
      });
  }

  markIneligible(): void {
    const detail = this.detail();
    if (!detail) {
      return;
    }

    const dialogRef = this.dialog.open(DmisReasonDialogComponent, {
      width: '480px',
      data: {
        title: 'Mark Ineligible',
        actionLabel: 'Mark Ineligible',
        actionColor: 'warn',
      } satisfies DmisReasonDialogData,
    });

    dialogRef.afterClosed()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((result: DmisReasonDialogResult | undefined) => {
        if (result?.reason) {
          this.submitDecision({ decision: 'INELIGIBLE', reason: result.reason }, 'Request marked ineligible.');
        }
      });
  }

  openFulfillment(): void {
    const detail = this.detail();
    if (!detail || this.fulfillmentEntryAction()?.disabled) {
      return;
    }
    this.router.navigate(['/operations/package-fulfillment', detail.reliefrqst_id]);
  }

  chipTone(tone: OperationsTone): 'neutral' | 'soft' | 'critical' | 'warning' | 'success' | 'info' | 'outline' {
    return mapOperationsToneToChipTone(tone);
  }

  trackItem(_index: number, item: RequestItem): number {
    return item.item_id;
  }

  private submitDecision(payload: EligibilityDecisionPayload, successMessage: string): void {
    const detail = this.detail();
    if (!detail) {
      return;
    }

    this.submitting.set(true);
    this.operationsService.submitEligibilityDecision(detail.reliefrqst_id, payload)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.detail.set(updated);
          this.submitting.set(false);
          this.notify.showSuccess(successMessage);
        },
        error: (err: HttpErrorResponse) => {
          this.submitting.set(false);
          const fallback = typeof err.error?.detail === 'string' ? err.error.detail : 'Failed to submit decision.';
          this.notify.showError(extractOperationsErrorMessage(err.error) ?? fallback);
        },
      });
  }
}
