import { ChangeDetectionStrategy, Component, DestroyRef, OnInit, computed, inject, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
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
import { DmisSkeletonLoaderComponent } from '../../replenishment/shared/dmis-skeleton-loader/dmis-skeleton-loader.component';
import { OpsSplitBannerComponent } from '../shared/ops-split-banner.component';
import { OpsStatusChipComponent } from '../shared/ops-status-chip.component';
import { OperationsService } from '../services/operations.service';
import { RequestDetailResponse, RequestItem, PackageSummary } from '../models/operations.model';
import {
  formatOperationsDateTime,
  formatOperationsLineCount,
  formatOperationsPackageStatus,
  formatOperationsRequestStatus,
  formatOperationsUrgency,
  formatRequestMode,
  getPackageDispatchAction,
  getRequestFulfillmentEntryAction,
  OperationsTone,
  PackageDispatchAction,
  extractOperationsErrorMessage,
  getOperationsPackageTone,
  getOperationsRequestTone,
  getOperationsUrgencyTone,
  mapOperationsToneToChipTone,
} from '../operations-display.util';

interface WorkflowStep {
  label: string;
  detail: string;
  tone: 'draft' | 'review' | 'success' | 'warning' | 'danger' | 'muted';
  timestamp?: string;
}

@Component({
  selector: 'app-relief-request-detail',
  standalone: true,
  imports: [
    DecimalPipe,
    MatButtonModule,
    MatCardModule,
    MatIconModule,
    MatTooltipModule,
    DmisEmptyStateComponent,
    DmisSkeletonLoaderComponent,
    OpsSplitBannerComponent,
    OpsStatusChipComponent,
  ],
  templateUrl: './relief-request-detail.component.html',
  styleUrls: ['./relief-request-detail.component.scss', '../operations-shell.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ReliefRequestDetailComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly operationsService = inject(OperationsService);
  private readonly dialog = inject(MatDialog);
  private readonly notify = inject(DmisNotificationService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly appAccess = inject(AppAccessService);

  readonly loading = signal(true);
  readonly error = signal<string | null>(null);
  readonly request = signal<RequestDetailResponse | null>(null);
  readonly submitting = signal(false);

  readonly formatOperationsRequestStatus = formatOperationsRequestStatus;
  readonly formatOperationsPackageStatus = formatOperationsPackageStatus;
  readonly formatOperationsUrgency = formatOperationsUrgency;
  readonly formatOperationsDateTime = formatOperationsDateTime;
  readonly formatOperationsLineCount = formatOperationsLineCount;
  readonly formatRequestMode = formatRequestMode;
  readonly getOperationsRequestTone = getOperationsRequestTone;
  readonly getOperationsUrgencyTone = getOperationsUrgencyTone;
  readonly getOperationsPackageTone = getOperationsPackageTone;

  readonly statusTone = computed(() => this.getOperationsRequestTone(this.request()?.status_code));
  readonly fulfillmentEntryAction = computed(() => {
    const request = this.request();
    if (!request) {
      return null;
    }
    return getRequestFulfillmentEntryAction(request, this.appAccess.canAccessNavKey('operations.fulfillment'));
  });

  readonly canEditDraft = computed(() => this.appAccess.canEditReliefRequestDraft());
  readonly canSubmitRequest = computed(() => this.appAccess.canSubmitReliefRequest());

  readonly workflow = computed<WorkflowStep[]>(() => {
    const request = this.request();
    if (!request) {
      return [];
    }

    // A request is only considered submitted once its workflow status advances
    // past DRAFT. `create_dtime` is set on first save and would misleadingly
    // mark drafts as already submitted. No truthful submit timestamp is present
    // in the current payload, so we leave the Submitted step timestamp blank.
    const submitted = request.status_code !== 'DRAFT';
    const reviewed = Boolean(request.review_dtime);
    const hasPackage = (request.packages?.length ?? 0) > 0;
    const firstPackage = request.packages?.[0];
    const dispatched = Boolean(firstPackage?.dispatch_dtime);

    return [
      {
        label: 'Draft',
        detail: request.status_code === 'DRAFT' ? 'Editable' : 'Captured',
        tone: request.status_code === 'DRAFT' ? 'draft' : 'success',
        timestamp: request.request_date ? formatOperationsDateTime(request.request_date) : undefined,
      },
      {
        label: 'Submitted',
        detail: submitted ? 'Sent to review' : 'Pending submit',
        tone: submitted ? 'review' : 'muted',
        timestamp: undefined,
      },
      {
        label: 'Eligibility Review',
        detail: reviewed ? 'Decision recorded' : 'Awaiting decision',
        tone: reviewed ? 'warning' : 'muted',
        timestamp: reviewed ? formatOperationsDateTime(request.review_dtime) : undefined,
      },
      {
        label: 'Fulfillment',
        detail: hasPackage ? 'Package created' : 'Not yet started',
        tone: hasPackage ? 'success' : 'muted',
        timestamp: request.action_dtime ? formatOperationsDateTime(request.action_dtime) : undefined,
      },
      {
        label: 'Dispatch',
        detail: dispatched ? 'Waybill available' : 'Pending handoff',
        tone: dispatched ? 'danger' : 'muted',
        timestamp: dispatched ? formatOperationsDateTime(firstPackage?.dispatch_dtime) : undefined,
      },
    ];
  });

  readonly primaryPackage = computed(() => this.request()?.packages?.[0] ?? null);

  readonly splitParentInfo = computed(() => {
    const split = this.primaryPackage()?.split;
    if (!split?.split_from_package_id) {
      return null;
    }
    return { id: split.split_from_package_id, no: split.split_from_package_no };
  });

  readonly splitChildren = computed(() =>
    this.primaryPackage()?.split?.split_children ?? [],
  );

  ngOnInit(): void {
    const reliefrqstId = Number(this.route.snapshot.paramMap.get('reliefrqstId'));
    if (!reliefrqstId) {
      this.error.set('Invalid request ID.');
      this.loading.set(false);
      return;
    }
    this.loadRequest(reliefrqstId);
  }

  loadRequest(reliefrqstId = Number(this.route.snapshot.paramMap.get('reliefrqstId'))): void {
    this.loading.set(true);
    this.error.set(null);

    this.operationsService.getRequest(reliefrqstId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (data) => {
          this.request.set(data);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.error.set(err.status === 404 ? 'Relief request not found.' : 'Failed to load relief request.');
        },
      });
  }

  goBack(): void {
    this.router.navigate(['/operations/relief-requests']);
  }

  openEdit(): void {
    const request = this.request();
    if (!request || request.status_code !== 'DRAFT') {
      return;
    }
    this.router.navigate(['/operations/relief-requests', request.reliefrqst_id, 'edit']);
  }

  /**
   * Returns the disabled/tooltip state for the "Open dispatch workspace" action
   * on a package row. Packages in DRAFT / PENDING_OVERRIDE_APPROVAL / CONSOLIDATING
   * have no dispatch record and must not open the dispatch workspace — doing so
   * previously led users to a shell page where no transport details could be
   * confirmed because stock had never been committed.
   */
  packageDispatchAction(pkg: PackageSummary): PackageDispatchAction {
    return getPackageDispatchAction(pkg);
  }

  openDispatch(pkg: PackageSummary): void {
    if (this.packageDispatchAction(pkg).disabled) {
      return;
    }
    this.router.navigate(['/operations/dispatch', pkg.reliefpkg_id]);
  }

  openFulfillment(): void {
    const request = this.request();
    if (!request || this.fulfillmentEntryAction()?.disabled) {
      return;
    }
    this.router.navigate(['/operations/package-fulfillment', request.reliefrqst_id]);
  }

  chipTone(tone: OperationsTone): 'neutral' | 'soft' | 'critical' | 'warning' | 'success' | 'info' | 'outline' {
    return mapOperationsToneToChipTone(tone);
  }

  submitForReview(): void {
    const request = this.request();
    if (!request) {
      return;
    }

    const dialogRef = this.dialog.open(DmisConfirmDialogComponent, {
      width: '480px',
      data: {
        title: 'Submit for Review',
        message: `Submit ${request.tracking_no ?? 'request #' + request.reliefrqst_id} to the eligibility queue?`,
        confirmLabel: 'Submit',
        icon: 'send',
        confirmColor: 'primary',
      } satisfies ConfirmDialogData,
    });

    dialogRef.afterClosed()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((confirmed) => {
        if (!confirmed) {
          return;
        }
        this.submitting.set(true);
        this.operationsService.submitRequest(request.reliefrqst_id)
          .pipe(takeUntilDestroyed(this.destroyRef))
          .subscribe({
            next: (updated) => {
              this.request.set(updated);
              this.submitting.set(false);
              this.notify.showSuccess('Request submitted for review.');
            },
            error: (err: HttpErrorResponse) => {
              this.submitting.set(false);
              const fallback = typeof err.error?.detail === 'string' ? err.error.detail : 'Failed to submit request.';
              this.notify.showError(extractOperationsErrorMessage(err.error) ?? fallback);
            },
          });
      });
  }

  trackItem(_index: number, item: RequestItem): number {
    return item.item_id;
  }

  trackPackage(_index: number, item: PackageSummary): number {
    return item.reliefpkg_id;
  }
}
