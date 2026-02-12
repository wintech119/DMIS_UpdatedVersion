import {
  Component, ChangeDetectionStrategy, inject, signal, computed, OnInit, DestroyRef
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { DatePipe, DecimalPipe, SlicePipe } from '@angular/common';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatChipsModule } from '@angular/material/chips';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatDividerModule } from '@angular/material/divider';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatTableModule } from '@angular/material/table';
import { MatTooltipModule } from '@angular/material/tooltip';
import { FormsModule } from '@angular/forms';
import { EMPTY, of } from 'rxjs';
import { catchError, map, switchMap } from 'rxjs/operators';

import { NeedsListResponse, NeedsListItem, HorizonAllocation } from '../models/needs-list.model';
import { HorizonType } from '../models/approval-workflows.model';
import { ReplenishmentService } from '../services/replenishment.service';
import { DmisNotificationService } from '../services/notification.service';
import { DmisApprovalStatusTrackerComponent } from '../shared/dmis-approval-status-tracker/dmis-approval-status-tracker.component';
import {
  RejectReasonDialogComponent,
  RejectReasonDialogResult
} from '../shared/reject-reason-dialog/reject-reason-dialog.component';
import {
  DmisReasonDialogComponent,
  DmisReasonDialogData,
  DmisReasonDialogResult
} from '../shared/dmis-reason-dialog/dmis-reason-dialog.component';
import { DmisSkeletonLoaderComponent } from '../shared/dmis-skeleton-loader/dmis-skeleton-loader.component';
import { DmisEmptyStateComponent } from '../shared/dmis-empty-state/dmis-empty-state.component';
import { formatStatusLabel } from './status-label.util';

@Component({
  selector: 'app-needs-list-review-detail',
  imports: [
    DatePipe,
    DecimalPipe,
    SlicePipe,
    FormsModule,
    MatButtonModule,
    MatCardModule,
    MatChipsModule,
    MatDialogModule,
    MatDividerModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatTableModule,
    MatTooltipModule,
    DmisApprovalStatusTrackerComponent,
    DmisSkeletonLoaderComponent,
    DmisEmptyStateComponent
  ],
  templateUrl: './needs-list-review-detail.component.html',
  styleUrl: './needs-list-review-detail.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class NeedsListReviewDetailComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly http = inject(HttpClient);
  private readonly dialog = inject(MatDialog);
  private readonly destroyRef = inject(DestroyRef);
  private readonly replenishmentService = inject(ReplenishmentService);
  private readonly notifications = inject(DmisNotificationService);

  readonly loading = signal(true);
  readonly needsList = signal<NeedsListResponse | null>(null);
  readonly error = signal(false);
  readonly actionLoading = signal<string | null>(null);
  readonly roles = signal<string[]>([]);
  readonly permissions = signal<string[]>([]);
  readonly reviewComments = signal<Record<number, string>>({});

  readonly items = computed(() => this.needsList()?.items ?? []);
  readonly status = computed(() => this.needsList()?.status ?? 'DRAFT');

  readonly approvalHorizon = computed<HorizonType>(() => {
    const itemList = this.items();
    let hasB = false;
    let hasA = false;

    for (const item of itemList) {
      const horizons = item.horizon;
      if (!horizons) continue;
      if ((horizons.C?.recommended_qty ?? 0) > 0) return 'C';
      if ((horizons.B?.recommended_qty ?? 0) > 0) hasB = true;
      if ((horizons.A?.recommended_qty ?? 0) > 0) hasA = true;
    }

    if (hasB) return 'B';
    if (hasA) return 'A';
    return 'A';
  });

  readonly canStartReview = computed(() =>
    this.status() === 'SUBMITTED' && this.can('replenishment.needs_list.review_start')
  );

  readonly canApprove = computed(() =>
    this.status() === 'UNDER_REVIEW' && this.can('replenishment.needs_list.approve')
  );

  readonly canReject = computed(() =>
    this.status() === 'UNDER_REVIEW' && this.can('replenishment.needs_list.reject')
  );

  readonly canReturn = computed(() =>
    this.status() === 'UNDER_REVIEW' && this.can('replenishment.needs_list.return')
  );

  readonly canEscalate = computed(() =>
    this.status() === 'UNDER_REVIEW' && this.can('replenishment.needs_list.escalate')
  );

  readonly canAddComments = computed(() =>
    this.status() === 'UNDER_REVIEW' && this.can('replenishment.needs_list.review_comments')
  );

  readonly hasActions = computed(() =>
    this.canStartReview() || this.canApprove() || this.canReject() || this.canReturn() || this.canEscalate()
  );

  readonly displayedColumns = [
    'item_name', 'warehouse', 'available', 'inbound', 'burn_rate',
    'required', 'gap', 'stockout', 'horizon_a', 'horizon_b', 'horizon_c', 'severity'
  ];

  readonly mobileDisplayedColumns = [
    'item_name', 'gap', 'severity'
  ];

  private needsListId = '';

  ngOnInit(): void {
    this.loadPermissions();
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(params => {
      this.needsListId = params.get('id') ?? '';
      if (this.needsListId) {
        this.loadNeedsList();
      }
    });
  }

  loadNeedsList(): void {
    this.loading.set(true);
    this.error.set(false);
    this.replenishmentService.listNeedsLists().pipe(
      map(({ needs_lists }) =>
        needs_lists.some((row) => row.needs_list_id === this.needsListId)
      ),
      // If queue check fails, attempt direct fetch so transient list failures do not block detail view.
      catchError(() => of(true)),
      switchMap((existsInQueue) => {
        if (!existsInQueue) {
          this.loading.set(false);
          this.error.set(true);
          this.notifications.showWarning('Needs list not found. It may have expired or been removed.');
          this.router.navigate(['/replenishment/needs-list-review']);
          return EMPTY;
        }
        return this.replenishmentService.getNeedsList(this.needsListId);
      })
    ).subscribe({
      next: (data) => {
        this.needsList.set(data);
        this.loading.set(false);
      },
      error: () => {
        this.loading.set(false);
        this.error.set(true);
        this.notifications.showError('Failed to load needs list.');
      }
    });
  }

  backToQueue(): void {
    this.router.navigate(['/replenishment/needs-list-review']);
  }

  // ── Approval Actions ──

  startReview(): void {
    if (!this.canStartReview() || this.actionLoading()) return;
    this.actionLoading.set('start_review');
    this.replenishmentService.startReview(this.needsListId).subscribe({
      next: (data) => {
        this.needsList.set(data);
        this.actionLoading.set(null);
        this.notifications.showSuccess('Review started.');
      },
      error: (err: HttpErrorResponse) => {
        this.actionLoading.set(null);
        this.notifications.showError(this.extractError(err, 'Failed to start review.'));
      }
    });
  }

  approve(): void {
    if (!this.canApprove() || this.actionLoading()) return;
    this.actionLoading.set('approve');
    this.replenishmentService.approveNeedsList(this.needsListId).subscribe({
      next: (data) => {
        this.needsList.set(data);
        this.actionLoading.set(null);
        this.notifications.showSuccess('Needs list approved.');
      },
      error: (err: HttpErrorResponse) => {
        this.actionLoading.set(null);
        this.notifications.showError(this.extractError(err, 'Approval failed.'));
      }
    });
  }

  reject(): void {
    if (!this.canReject() || this.actionLoading()) return;
    this.dialog.open(RejectReasonDialogComponent, {
      width: '520px',
      autoFocus: false
    }).afterClosed()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((result?: RejectReasonDialogResult) => {
        if (!result) return;
        this.actionLoading.set('reject');
        this.replenishmentService.rejectNeedsList(this.needsListId, {
          reason: result.reason,
          notes: result.notes
        }).subscribe({
          next: (data) => {
            this.needsList.set(data);
            this.actionLoading.set(null);
            this.notifications.showWarning('Needs list rejected.');
          },
          error: (err: HttpErrorResponse) => {
            this.actionLoading.set(null);
            this.notifications.showError(this.extractError(err, 'Rejection failed.'));
          }
        });
      });
  }

  returnForRevision(): void {
    if (!this.canReturn() || this.actionLoading()) return;
    const data: DmisReasonDialogData = {
      title: 'Return for Revision',
      actionLabel: 'Return',
      actionColor: 'warn'
    };
    this.dialog.open(DmisReasonDialogComponent, {
      width: '520px',
      autoFocus: false,
      data
    }).afterClosed()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((result?: DmisReasonDialogResult) => {
        if (!result) return;
        this.actionLoading.set('return');
        this.replenishmentService.returnNeedsList(this.needsListId, result.reason).subscribe({
          next: (nlData) => {
            this.needsList.set(nlData);
            this.actionLoading.set(null);
            this.notifications.showWarning('Needs list returned for revision.');
          },
          error: (err: HttpErrorResponse) => {
            this.actionLoading.set(null);
            this.notifications.showError(this.extractError(err, 'Return failed.'));
          }
        });
      });
  }

  escalate(): void {
    if (!this.canEscalate() || this.actionLoading()) return;
    const data: DmisReasonDialogData = {
      title: 'Escalate for Higher Approval',
      actionLabel: 'Escalate',
      actionColor: 'accent'
    };
    this.dialog.open(DmisReasonDialogComponent, {
      width: '520px',
      autoFocus: false,
      data
    }).afterClosed()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((result?: DmisReasonDialogResult) => {
        if (!result) return;
        this.actionLoading.set('escalate');
        this.replenishmentService.escalateNeedsList(this.needsListId, result.reason).subscribe({
          next: (nlData) => {
            this.needsList.set(nlData);
            this.actionLoading.set(null);
            this.notifications.showSuccess('Needs list escalated.');
          },
          error: (err: HttpErrorResponse) => {
            this.actionLoading.set(null);
            this.notifications.showError(this.extractError(err, 'Escalation failed.'));
          }
        });
      });
  }

  saveComment(item: NeedsListItem): void {
    const comment = this.reviewComments()[item.item_id];
    if (!comment?.trim()) return;
    this.replenishmentService.addReviewComments(this.needsListId, [
      { item_id: item.item_id, comment: comment.trim() }
    ]).subscribe({
      next: (data) => {
        this.needsList.set(data);
        this.notifications.showSuccess('Comment saved.');
      },
      error: (err: HttpErrorResponse) => {
        this.notifications.showError(this.extractError(err, 'Failed to save comment.'));
      }
    });
  }

  updateComment(itemId: number, value: string): void {
    this.reviewComments.update(c => ({ ...c, [itemId]: value }));
  }

  onSendReminder(): void {
    this.notifications.showSuccess('Reminder sent (not yet implemented).');
  }

  // ── Display helpers ──

  horizonQty(horizon: HorizonAllocation | undefined, key: 'A' | 'B' | 'C'): string {
    const val = horizon?.[key]?.recommended_qty;
    if (val === null || val === undefined) return '—';
    return val.toFixed(1);
  }

  severityIcon(item: NeedsListItem): string {
    switch (item.severity) {
      case 'CRITICAL': return 'error';
      case 'WARNING': return 'warning';
      case 'WATCH': return 'visibility';
      case 'OK': return 'check_circle';
      default: return 'help_outline';
    }
  }

  timeToStockout(item: NeedsListItem): string {
    const val = item.time_to_stockout;
    if (val === undefined || val === null || val === 'N/A') return '—';
    if (typeof val === 'number') return `${val.toFixed(1)}h`;
    return val;
  }

  warehouseLabel(nl: NeedsListResponse): string {
    if (nl.warehouses?.length) {
      return nl.warehouses.map(w => w.warehouse_name).join(', ');
    }
    if (nl.warehouse_ids?.length) {
      return nl.warehouse_ids.join(', ');
    }
    if (nl.warehouse_id) {
      return `Warehouse ${nl.warehouse_id}`;
    }
    return 'N/A';
  }

  statusLabel(status: string): string {
    return formatStatusLabel(status);
  }

  // ── Private helpers ──

  private can(permission: string): boolean {
    return this.permissions().includes(permission);
  }

  private loadPermissions(): void {
    this.http.get<{ roles?: string[]; permissions?: string[] }>('/api/v1/auth/whoami/').subscribe({
      next: (data) => {
        this.roles.set(data.roles ?? []);
        this.permissions.set(data.permissions ?? []);
      },
      error: () => {
        this.roles.set([]);
        this.permissions.set([]);
      }
    });
  }

  private extractError(error: HttpErrorResponse, fallback: string): string {
    if (error.status === 403) return 'You do not have permission to perform this action.';
    if (error.error?.errors) {
      const errors = error.error.errors;
      if (Array.isArray(errors)) return errors[0] ?? fallback;
      const entries = Object.entries(errors);
      if (entries.length) {
        const [field, msg] = entries[0];
        return `${field}: ${Array.isArray(msg) ? msg[0] : msg}`;
      }
    }
    return error.message || fallback;
  }
}
