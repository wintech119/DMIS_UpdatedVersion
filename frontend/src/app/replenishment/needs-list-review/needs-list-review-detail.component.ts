import {
  Component, ChangeDetectionStrategy, inject, signal, computed, OnInit, DestroyRef
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { DatePipe, DecimalPipe } from '@angular/common';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatChipsModule } from '@angular/material/chips';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatDividerModule } from '@angular/material/divider';
import { MatIconModule } from '@angular/material/icon';
import { MatTableModule } from '@angular/material/table';
import { MatTooltipModule } from '@angular/material/tooltip';

import { NeedsListResponse, NeedsListItem, HorizonAllocation } from '../models/needs-list.model';
import { HorizonType } from '../models/approval-workflows.model';
import { FreshnessLevel, SeverityLevel, WarehouseFreshnessEntry } from '../models/stock-status.model';
import { ReplenishmentService } from '../services/replenishment.service';
import { DataFreshnessService } from '../services/data-freshness.service';
import { DmisNotificationService } from '../services/notification.service';
import { DmisDataFreshnessBannerComponent } from '../shared/dmis-data-freshness-banner/dmis-data-freshness-banner.component';
import { TimeToStockoutComponent, TimeToStockoutData } from '../time-to-stockout/time-to-stockout.component';
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

const SEVERITY_ORDER: Record<string, number> = {
  CRITICAL: 0,
  WARNING: 1,
  WATCH: 2,
  OK: 3
};

const PENDING_APPROVAL_STATUSES = new Set(['SUBMITTED', 'PENDING_APPROVAL', 'PENDING', 'UNDER_REVIEW']);
const PROCUREMENT_APPROVER_ROLE_CODES = new Set([
  'EXECUTIVE',
  'ODPEM_DIR_PEOD',
  'DIRECTOR_PEOD',
  'SYSTEM_ADMINISTRATOR',
  'TST_DIR_PEOD'
]);
const REQUEST_CHANGE_REASON_OPTIONS = [
  { value: 'QTY_ADJUSTMENT', label: 'Quantity Adjustment' },
  { value: 'DATA_QUALITY', label: 'Data Quality' },
  { value: 'MISSING_JUSTIFICATION', label: 'Missing Justification' },
  { value: 'SCOPE_MISMATCH', label: 'Scope Mismatch' },
  { value: 'POLICY_COMPLIANCE', label: 'Policy Compliance' },
  { value: 'OTHER', label: 'Other' }
] as const;

const APPROVAL_WARNING_LABELS: Record<string, string> = {
  cost_missing_for_approval:
    'Estimated cost data is missing for one or more items.',
  approval_tier_conservative:
    'Approval tier was set conservatively due to missing cost data.',
  transfer_scope_unavailable:
    'Transfer scope metadata is unavailable for one or more items.',
  transfer_cross_parish_over_500:
    'Cross-parish transfer exceeds 500 units and requires escalation.',
  transfer_scope_unrecognized:
    'Transfer scope value is unrecognized and requires review.',
  donation_restriction_unavailable:
    'Donation restriction metadata is unavailable for one or more items.',
  donation_restriction_escalation_required:
    'Donation restrictions require escalation before approval.',
  donation_restriction_unrecognized:
    'Donation restriction value is unrecognized and requires review.'
};

interface WorkflowStep {
  id: string;
  label: string;
  icon: string;
  state: 'completed' | 'active' | 'pending' | 'terminal';
}

const FRESHNESS_RANK: Record<FreshnessLevel, number> = {
  HIGH: 0,
  MEDIUM: 1,
  LOW: 2
};

const HORIZON_ACTIONS = {
  A: {
    label: 'Transfer (Horizon A)',
    icon: 'local_shipping',
    detail: 'Use the transfer allocation shown in the Horizon A column.'
  },
  B: {
    label: 'Donation (Horizon B)',
    icon: 'inventory_2',
    detail: 'Use the donation allocation shown in the Horizon B column.'
  },
  C: {
    label: 'Procurement (Horizon C)',
    icon: 'shopping_cart',
    detail: 'Use the procurement allocation shown in the Horizon C column.'
  }
} as const;

@Component({
  selector: 'app-needs-list-review-detail',
  imports: [
    DatePipe,
    DecimalPipe,
    MatButtonModule,
    MatCardModule,
    MatChipsModule,
    MatDialogModule,
    MatDividerModule,
    MatIconModule,
    MatTableModule,
    MatTooltipModule,
    DmisDataFreshnessBannerComponent,
    TimeToStockoutComponent,
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
  private readonly dataFreshnessService = inject(DataFreshnessService);
  private readonly notifications = inject(DmisNotificationService);

  readonly loading = signal(true);
  readonly needsList = signal<NeedsListResponse | null>(null);
  readonly error = signal(false);
  readonly actionLoading = signal<string | null>(null);
  readonly roles = signal<string[]>([]);
  readonly permissions = signal<string[]>([]);
  readonly currentUser = signal<string | null>(null);
  readonly hasFreshnessData = signal(false);

  readonly items = computed(() => this.needsList()?.items ?? []);
  readonly status = computed(() => this.needsList()?.status ?? 'DRAFT');

  readonly sortedItems = computed(() => {
    const list = [...this.items()];
    list.sort((a, b) => {
      const sa = SEVERITY_ORDER[a.severity ?? ''] ?? 99;
      const sb = SEVERITY_ORDER[b.severity ?? ''] ?? 99;
      if (sa !== sb) return sa - sb;
      const ta = this.parseStockoutHours(a);
      const tb = this.parseStockoutHours(b);
      return ta - tb;
    });
    return list;
  });

  readonly severityCounts = computed(() => {
    const counts: Record<string, number> = { CRITICAL: 0, WARNING: 0, WATCH: 0, OK: 0 };
    for (const item of this.items()) {
      const sev = item.severity ?? 'UNKNOWN';
      if (sev in counts) counts[sev]++;
    }
    return counts;
  });

  readonly criticalCount = computed(() => this.severityCounts()['CRITICAL']);

  readonly approvalHorizon = computed<HorizonType>(() => {
    const selectedMethod = this.normalizeHorizon(this.needsList()?.selected_method);
    if (selectedMethod) {
      return selectedMethod;
    }

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

  readonly isPendingApproval = computed(() =>
    PENDING_APPROVAL_STATUSES.has(this.status())
  );

  readonly canApprove = computed(() =>
    this.isPendingApproval()
    && this.can('replenishment.needs_list.approve')
    && this.isApprovalRoleAuthorized()
  );

  readonly canReject = computed(() =>
    this.isPendingApproval()
    && this.can('replenishment.needs_list.reject')
    && this.isApprovalRoleAuthorized()
  );

  readonly canReturn = computed(() =>
    this.isPendingApproval() && this.can('replenishment.needs_list.return')
  );

  readonly canEscalate = computed(() =>
    this.isPendingApproval() && this.can('replenishment.needs_list.escalate')
  );

  readonly hasActions = computed(() =>
    this.canApprove() || this.canReject() || this.canReturn() || this.canEscalate()
  );
  readonly approvalActionHint = computed(() => {
    const nl = this.needsList();
    if (!nl || !this.isPendingApproval() || this.hasActions()) {
      return null;
    }

    const submittedBy = String(nl.submitted_by ?? '').trim().toLowerCase();
    const currentUser = String(this.currentUser() ?? '').trim().toLowerCase();
    if (submittedBy && currentUser && submittedBy === currentUser) {
      return 'This needs list was submitted by your account. A different approver must approve, reject, or request changes.';
    }
    return 'No approval actions are available for your current permissions.';
  });

  readonly workflowSteps = computed<WorkflowStep[]>(() => {
    const status = this.status();
    const steps: { id: string; label: string; icon: string }[] = [
      { id: 'SUBMITTED', label: 'Submitted', icon: 'send' },
      { id: 'UNDER_REVIEW', label: 'Under Review', icon: 'rate_review' },
      { id: 'APPROVED', label: 'Approved', icon: 'verified' },
      { id: 'FULFILLED', label: 'Fulfilled', icon: 'task_alt' },
    ];

    let activeIndex: number;
    let isTerminal = false;
    switch (status) {
      case 'DRAFT': case 'MODIFIED': case 'RETURNED':
        activeIndex = -1; break;
      case 'SUBMITTED': case 'PENDING': case 'PENDING_APPROVAL':
        activeIndex = 0; break;
      case 'UNDER_REVIEW': case 'ESCALATED':
        activeIndex = 1; break;
      case 'APPROVED':
        activeIndex = 2; break;
      case 'IN_PREPARATION': case 'DISPATCHED': case 'RECEIVED': case 'IN_PROGRESS':
        activeIndex = 2; break;
      case 'COMPLETED': case 'FULFILLED':
        activeIndex = 3; break;
      case 'REJECTED': case 'CANCELLED':
        activeIndex = 1; isTerminal = true; break;
      default:
        activeIndex = 0; break;
    }

    return steps.map((s, i) => ({
      ...s,
      state: i < activeIndex ? 'completed' as const
           : i === activeIndex ? (isTerminal ? 'terminal' as const : 'active' as const)
           : 'pending' as const
    }));
  });

  readonly itemTotals = computed(() => {
    const list = this.items();
    let available = 0, inbound = 0, required = 0, gap = 0;
    let horizonA = 0, horizonB = 0, horizonC = 0;
    for (const item of list) {
      available += item.available_qty ?? 0;
      inbound += item.inbound_strict_qty ?? 0;
      required += item.required_qty ?? 0;
      gap += item.gap_qty ?? 0;
      horizonA += item.horizon?.A?.recommended_qty ?? 0;
      horizonB += item.horizon?.B?.recommended_qty ?? 0;
      horizonC += item.horizon?.C?.recommended_qty ?? 0;
    }
    return { available, inbound, required, gap, horizonA, horizonB, horizonC };
  });

  readonly displayedColumns = [
    'item_name', 'warehouse', 'available', 'inbound', 'burn_rate',
    'required', 'gap', 'stockout', 'horizon_a', 'horizon_b', 'horizon_c', 'severity'
  ];

  readonly mobileDisplayedColumns = [
    'item_name', 'gap', 'severity'
  ];

  private needsListId = '';

  private normalizeHorizon(value: unknown): HorizonType | null {
    const normalized = String(value ?? '').trim().toUpperCase().replace(/[-\s]+/g, '_');
    if (
      normalized === 'A' ||
      normalized === 'TRANSFER' ||
      normalized === 'INTER_WAREHOUSE' ||
      normalized === 'HORIZON_A'
    ) {
      return 'A';
    }
    if (
      normalized === 'B' ||
      normalized === 'DONATION' ||
      normalized === 'DONATIONS' ||
      normalized === 'HORIZON_B'
    ) {
      return 'B';
    }
    if (
      normalized === 'C' ||
      normalized === 'PROCUREMENT' ||
      normalized === 'PURCHASE' ||
      normalized === 'HORIZON_C'
    ) {
      return 'C';
    }
    return null;
  }

  private isApprovalRoleAuthorized(): boolean {
    const selectedMethod = this.normalizeHorizon(this.needsList()?.selected_method);
    const method = selectedMethod ?? this.approvalHorizon();
    if (method !== 'C') {
      return true;
    }

    const roleSet = new Set(
      this.roles()
        .map((role) => String(role ?? '').trim().toUpperCase().replace(/[-\s]+/g, '_'))
        .filter(Boolean)
    );
    for (const role of roleSet) {
      if (PROCUREMENT_APPROVER_ROLE_CODES.has(role)) {
        return true;
      }
    }
    return false;
  }

  ngOnInit(): void {
    this.dataFreshnessService.clear();
    this.destroyRef.onDestroy(() => this.dataFreshnessService.clear());
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
    this.replenishmentService.getNeedsList(this.needsListId).subscribe({
      next: (data) => {
        this.needsList.set(data);
        this.syncFreshnessBanner(data);
        this.loading.set(false);
      },
      error: () => {
        this.dataFreshnessService.clear();
        this.hasFreshnessData.set(false);
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

  approve(): void {
    if (!this.canApprove() || this.actionLoading()) return;
    this.actionLoading.set('approve');
    this.replenishmentService.approveNeedsList(this.needsListId).subscribe({
      next: () => {
        this.actionLoading.set(null);
        this.router.navigate(
          ['/replenishment/needs-list', this.needsListId, 'review'],
          { queryParams: { approved: 'true' } }
        );
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
      title: 'Request Changes',
      actionLabel: 'Request Changes',
      actionColor: 'warn',
      reasonCodeLabel: 'Reason Code',
      reasonCodeOptions: REQUEST_CHANGE_REASON_OPTIONS
    };
    this.dialog.open(DmisReasonDialogComponent, {
      width: '520px',
      autoFocus: false,
      data
    }).afterClosed()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((result?: DmisReasonDialogResult) => {
        if (!result) return;
        const reasonCode = result.reason_code?.trim().toUpperCase();
        if (!reasonCode) {
          this.notifications.showError('A reason code is required to request changes.');
          return;
        }
        this.actionLoading.set('return');
        this.replenishmentService.returnNeedsList(this.needsListId, {
          reason_code: reasonCode,
          reason: result.reason
        }).subscribe({
          next: (nlData) => {
            this.needsList.set(nlData);
            this.actionLoading.set(null);
            this.notifications.showWarning('Changes requested. Needs list moved to Modified.');
          },
          error: (err: HttpErrorResponse) => {
            this.actionLoading.set(null);
            this.notifications.showError(this.extractError(err, 'Request changes failed.'));
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

  onSendReminder(): void {
    if (this.actionLoading()) {
      return;
    }

    const currentStatus = this.status();
    if (!PENDING_APPROVAL_STATUSES.has(currentStatus)) {
      this.notifications.showWarning('Reminder is only available while approval is pending.');
      return;
    }

    const canSendReminder =
      this.can('replenishment.needs_list.approve') ||
      this.can('replenishment.needs_list.reject') ||
      this.can('replenishment.needs_list.return') ||
      this.can('replenishment.needs_list.escalate');
    if (!canSendReminder) {
      this.notifications.showError('You do not have permission to send a reminder.');
      return;
    }

    this.actionLoading.set('reminder');
    this.replenishmentService.sendReviewReminder(this.needsListId).subscribe({
      next: (data) => {
        this.needsList.set(data);
        this.actionLoading.set(null);
        const reminder = data.review_reminder;
        if (reminder?.escalation_recommended) {
          this.notifications.showWarning(
            'Reminder sent. This needs list has been pending more than 8 hours; consider escalating.'
          );
          return;
        }
        this.notifications.showSuccess('Reminder sent to approver.');
      },
      error: (err: HttpErrorResponse) => {
        this.actionLoading.set(null);
        this.notifications.showError(this.extractError(err, 'Failed to send reminder.'));
      }
    });
  }

  // ── Display helpers ──

  stockoutData(item: NeedsListItem): TimeToStockoutData {
    const hours = this.parseStockoutHours(item);
    const hasBurnRate = (item.burn_rate_per_hour ?? 0) > 0;
    return {
      hours: hasBurnRate ? hours : null,
      severity: (item.severity as SeverityLevel) ?? 'OK',
      hasBurnRate,
      recommendedAction: this.getRecommendedStockoutAction(item.horizon)
    };
  }

  private parseStockoutHours(item: NeedsListItem): number {
    if (item.time_to_stockout_hours !== undefined && item.time_to_stockout_hours !== null) {
      return item.time_to_stockout_hours;
    }
    const val = item.time_to_stockout;
    if (val === undefined || val === null || val === 'N/A') return Infinity;
    if (typeof val === 'number') return val;
    const parsed = parseFloat(val);
    return isNaN(parsed) ? Infinity : parsed;
  }

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

  warningLabel(code: string): string {
    const trimmed = String(code ?? '').trim();
    if (!trimmed) return '';
    const mapped = APPROVAL_WARNING_LABELS[trimmed];
    if (mapped) return mapped;
    const display = trimmed.replace(/_/g, ' ');
    return display.charAt(0).toUpperCase() + display.slice(1);
  }

  statusLabel(status: string): string {
    return formatStatusLabel(status);
  }

  // ── Private helpers ──

  private can(permission: string): boolean {
    return this.permissions().includes(permission.toLowerCase());
  }

  private loadPermissions(): void {
    this.http.get<{ user_id?: string; username?: string; roles?: string[]; permissions?: string[] }>('/api/v1/auth/whoami/').subscribe({
      next: (data) => {
        const roles = [...new Set((data.roles ?? []).map((role) => String(role).trim()).filter(Boolean))];
        const permissions = [
          ...new Set(
            (data.permissions ?? [])
              .map((permission) => String(permission).trim().toLowerCase())
              .filter(Boolean)
          )
        ];
        const userRef = String(data.username ?? data.user_id ?? '').trim();
        this.roles.set(roles);
        this.permissions.set(permissions);
        this.currentUser.set(userRef || null);
      },
      error: () => {
        this.roles.set([]);
        this.permissions.set([]);
        this.currentUser.set(null);
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
    const apiMessage =
      typeof error.error?.message === 'string' ? error.error.message.trim() : '';
    const statusText = typeof error.statusText === 'string' ? error.statusText.trim() : '';
    return apiMessage || statusText || fallback || 'An unexpected error occurred';
  }

  private syncFreshnessBanner(needsList: NeedsListResponse): void {
    const entries = this.buildFreshnessEntries(needsList);
    this.hasFreshnessData.set(entries.length > 0);
    if (entries.length === 0) {
      this.dataFreshnessService.clear();
      return;
    }
    this.dataFreshnessService.updateFromWarehouseEntries(entries);
  }

  private buildFreshnessEntries(needsList: NeedsListResponse): WarehouseFreshnessEntry[] {
    const entries = new Map<string, WarehouseFreshnessEntry>();

    for (const item of needsList.items ?? []) {
      const freshnessLevel = this.normalizeFreshnessLevel(item.freshness?.state ?? item.freshness_state);
      const ageHours = item.freshness?.age_hours ?? null;
      const inventoryAsOf = item.freshness?.inventory_as_of ?? null;
      if (!freshnessLevel && ageHours === null && !inventoryAsOf) {
        continue;
      }

      const warehouseId = item.warehouse_id ?? needsList.warehouse_id ?? null;
      const warehouseName =
        item.warehouse_name?.trim() ||
        needsList.warehouses?.find((warehouse) => warehouse.warehouse_id === warehouseId)?.warehouse_name ||
        this.warehouseLabel(needsList);
      const entryKey = warehouseId !== null ? `id:${warehouseId}` : `name:${warehouseName}`;
      const nextLevel = freshnessLevel ?? 'HIGH';
      const existingEntry = entries.get(entryKey);

      if (!existingEntry) {
        entries.set(entryKey, {
          warehouse_id: warehouseId ?? 0,
          warehouse_name: warehouseName,
          freshness: nextLevel,
          last_sync: inventoryAsOf,
          age_hours: ageHours
        });
        continue;
      }

      if (FRESHNESS_RANK[nextLevel] > FRESHNESS_RANK[existingEntry.freshness]) {
        existingEntry.freshness = nextLevel;
      }
      if (ageHours !== null && (existingEntry.age_hours === null || ageHours > existingEntry.age_hours)) {
        existingEntry.age_hours = ageHours;
      }
      if (inventoryAsOf && (!existingEntry.last_sync || inventoryAsOf > existingEntry.last_sync)) {
        existingEntry.last_sync = inventoryAsOf;
      }
    }

    return [...entries.values()];
  }

  private normalizeFreshnessLevel(value: unknown): FreshnessLevel | null {
    const normalized = String(value ?? '').trim().toUpperCase();
    if (normalized === 'HIGH' || normalized === 'MEDIUM' || normalized === 'LOW') {
      return normalized;
    }
    return null;
  }

  private getRecommendedStockoutAction(horizon: HorizonAllocation | undefined): TimeToStockoutData['recommendedAction'] {
    if (!horizon) {
      return null;
    }

    const activeHorizons = (['A', 'B', 'C'] as const).filter((key) => {
      const quantity = horizon[key]?.recommended_qty;
      return quantity !== null && quantity !== undefined && quantity > 0;
    });

    if (activeHorizons.length === 0) {
      return null;
    }

    if (activeHorizons.length === 1) {
      return HORIZON_ACTIONS[activeHorizons[0]];
    }

    const horizonList = activeHorizons.join('/');
    return {
      label: `Mixed allocation (Horizons ${horizonList})`,
      icon: 'alt_route',
      detail: `This line uses multiple replenishment paths based on the backend allocation shown in the Horizon A/B/C columns: ${horizonList}.`
    };
  }
}
