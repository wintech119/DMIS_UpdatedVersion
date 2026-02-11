import { CommonModule } from '@angular/common';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Component, OnDestroy, OnInit, DestroyRef, inject } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators, FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatChipsModule } from '@angular/material/chips';
import { MatDividerModule } from '@angular/material/divider';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSelectModule } from '@angular/material/select';
import { MatTableModule } from '@angular/material/table';
import { MatTooltipModule } from '@angular/material/tooltip';
import { DmisApprovalStatusTrackerComponent } from '../shared/dmis-approval-status-tracker/dmis-approval-status-tracker.component';
import { HorizonType } from '../models/approval-workflows.model';
import { NeedsListResponse } from '../models/needs-list.model';

interface HorizonBlock {
  recommended_qty: number | null;
}

interface NeedsListItem {
  item_id: number;
  available_qty: number;
  inbound_strict_qty: number;
  burn_rate_per_hour: number;
  required_qty?: number;
  computed_required_qty?: number;
  override_reason?: string;
  override_updated_by?: string;
  override_updated_at?: string;
  review_comment?: string;
  review_updated_by?: string;
  review_updated_at?: string;
  gap_qty: number;
  time_to_stockout?: string | number;
  horizon?: { A: HorizonBlock; B: HorizonBlock; C: HorizonBlock };
  triggers?: { activate_B: boolean; activate_C: boolean; activate_all: boolean };
  confidence?: { level: string; reasons: string[] };
  warnings?: string[];
  freshness_state?: string;
  freshness?: { state: string; age_hours: number | null; inventory_as_of: string | null };
  procurement_status?: string | null;
  procurement?: {
    recommended_qty: number;
    est_unit_cost?: number | null;
    est_total_cost?: number | null;
    lead_time_hours_default: number;
    approval?: { tier: string; approver_role: string; methods_allowed: string[] };
    gojep_note?: { label: string; url: string };
  };
}

@Component({
  selector: 'app-needs-list-preview',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    ReactiveFormsModule,
    MatButtonModule,
    MatCardModule,
    MatChipsModule,
    MatDividerModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatProgressBarModule,
    MatSelectModule,
    MatTableModule,
    MatTooltipModule,
    DmisApprovalStatusTrackerComponent
  ],
  templateUrl: './needs-list-preview.component.html',
  styleUrl: './needs-list-preview.component.scss'
})
export class NeedsListPreviewComponent implements OnInit, OnDestroy {
  private readonly fb = inject(FormBuilder);
  private readonly http = inject(HttpClient);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  readonly phaseOptions = ['SURGE', 'STABILIZED', 'BASELINE'] as const;

  readonly form: FormGroup;
  private readonly destroyRef = inject(DestroyRef);
  private autoPreviewTimeoutId: ReturnType<typeof setTimeout> | null = null;
  private readonly warningLabels: Record<string, string> = {
    burn_data_missing: 'No recent burn data found in the demand window.',
    burn_fallback_unavailable: 'No category fallback rate is available for this item.',
    burn_rate_estimated: 'Burn rate is estimated from fallback data.',
    burn_no_rows_in_window: 'No validated fulfillments in the demand window.',
    db_unavailable_preview_stub: 'Database unavailable; showing preview stub values.',
    donation_in_transit_unmodeled: 'Donation in-transit data is not modeled yet.',
    procurement_unavailable_in_schema: 'Procurement data is not modeled yet.',
    procurement_cost_unavailable: 'Procurement cost estimates are unavailable.',
    procurement_category_unavailable: 'Procurement category is missing; using defaults.',
    procurement_cost_invalid: 'Procurement cost estimate is invalid.',
    procurement_phase_invalid: 'Procurement phase value is invalid; using baseline.',
    cost_missing_for_approval: 'Estimated costs are missing; approval tier is conservative.',
    approval_tier_conservative: 'Approval tier is escalated due to missing cost data.',
    transfer_cross_parish_over_500: 'Cross-parish transfer above 500 units requires escalation.',
    transfer_scope_unavailable: 'Transfer scope is unavailable for approval authority checks.',
    transfer_scope_unrecognized: 'Transfer scope is unrecognized.',
    donation_restriction_unavailable: 'Donation restriction is unavailable for approval authority checks.',
    donation_restriction_escalation_required: 'Restricted or earmarked donation requires escalation.',
    donation_restriction_unrecognized: 'Donation restriction is unrecognized.',
    strict_inbound_mapping_best_effort: 'Inbound status mapping uses best-effort rules.',
    critical_flag_unavailable: 'Critical item flag not configured.',
    inventory_timestamp_unavailable: 'Inventory timestamp is unavailable.',
    burn_fallback_unavailable_in_schema: 'Fallback burn rate data is missing in schema.'
  };

  loading = false;
  response: NeedsListResponse | null = null;
  items: NeedsListItem[] = [];
  topWarnings: string[] = [];
  perItemWarnings: { item_id: number; warnings: string[] }[] = [];
  errors: string[] = [];
  workflowErrors: string[] = [];
  permissions: string[] = [];
  overrideEdits: Record<number, { overridden_qty?: number; reason?: string }> = {};
  reviewEdits: Record<number, { comment?: string }> = {};
  draftIdInput = '';

  displayedColumns = [
    'item',
    'available',
    'inbound',
    'burn',
    'required',
    'gap',
    'stockout',
    'horizonA',
    'horizonB',
    'horizonC',
    'confidence',
    'freshness'
  ];

  constructor() {
    this.form = this.fb.group({
      event_id: [null, [Validators.required, Validators.min(1)]],
      warehouse_id: [null, [Validators.required, Validators.min(1)]],
      phase: ['BASELINE', Validators.required],
      as_of_datetime: ['']
    });
  }

  ngOnInit(): void {
    this.loadPermissions();
    this.loadQueryParams();
  }

  ngOnDestroy(): void {
    if (this.autoPreviewTimeoutId) {
      clearTimeout(this.autoPreviewTimeoutId);
    }
  }

  backToDashboard(): void {
    this.router.navigate(['/replenishment/dashboard']);
  }

  private loadQueryParams(): void {
    this.route.queryParams.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(params => {
      if (params['event_id']) {
        this.form.patchValue({
          event_id: Number(params['event_id']),
          warehouse_id: Number(params['warehouse_id']) || null,
          phase: params['phase'] || 'BASELINE'
        });
        // Auto-generate preview if params are present
        if (params['event_id'] && params['warehouse_id']) {
          if (this.autoPreviewTimeoutId) {
            clearTimeout(this.autoPreviewTimeoutId);
          }
          this.autoPreviewTimeoutId = setTimeout(() => this.generatePreview(), 100);
        }
      }
    });
  }

  generatePreview(): void {
    this.errors = [];
    this.workflowErrors = [];
    if (this.form.invalid) {
      this.errors = ['Please provide valid event_id, warehouse_id, and phase.'];
      return;
    }

    const payload = this.buildPayload();

    this.loading = true;
    this.http.post<NeedsListResponse>('/api/v1/replenishment/needs-list/preview', payload).subscribe({
      next: (data) => {
        this.resetWorkflowState();
        this.response = data;
        this.items = data.items ?? [];
        this.topWarnings = data.warnings ?? [];
        this.perItemWarnings = this.items
          .filter((item) => item.warnings && item.warnings.length)
          .map((item) => ({ item_id: item.item_id, warnings: item.warnings ?? [] }));
        this.loading = false;
      },
      error: (error: HttpErrorResponse) => {
        this.loading = false;
        this.errors = this.extractErrors(error, 'Preview request failed.');
      }
    });
  }

  createDraft(): void {
    this.workflowErrors = [];
    if (this.form.invalid) {
      this.workflowErrors = ['Please provide valid event_id, warehouse_id, and phase.'];
      return;
    }

    const payload = this.buildPayload();
    this.loading = true;
    this.http.post<NeedsListResponse>('/api/v1/replenishment/needs-list/draft', payload).subscribe({
      next: (data) => {
        this.loading = false;
        this.response = data;
        this.items = data.items ?? [];
        this.topWarnings = data.warnings ?? [];
        this.perItemWarnings = this.items
          .filter((item) => item.warnings && item.warnings.length)
          .map((item) => ({ item_id: item.item_id, warnings: item.warnings ?? [] }));
        this.overrideEdits = {};
        this.reviewEdits = {};
      },
      error: (error: HttpErrorResponse) => {
        this.loading = false;
        this.workflowErrors = this.extractErrors(error, 'Draft creation failed.');
      }
    });
  }

  loadDraftById(): void {
    this.workflowErrors = [];
    const trimmed = this.draftIdInput.trim();
    if (!trimmed) {
      this.workflowErrors = ['Please enter a draft ID.'];
      return;
    }
    this.loading = true;
    this.http.get<NeedsListResponse>(`/api/v1/replenishment/needs-list/${trimmed}`).subscribe({
      next: (data) => {
        this.loading = false;
        this.response = data;
        this.items = data.items ?? [];
        this.topWarnings = data.warnings ?? [];
        this.perItemWarnings = this.items
          .filter((item) => item.warnings && item.warnings.length)
          .map((item) => ({ item_id: item.item_id, warnings: item.warnings ?? [] }));
        this.reviewEdits = {};
      },
      error: (error: HttpErrorResponse) => {
        this.loading = false;
        this.workflowErrors = this.extractErrors(error, 'Load draft failed.');
      }
    });
  }

  applyOverride(item: NeedsListItem): void {
    if (!this.response?.needs_list_id) {
      return;
    }
    const draftId = this.response.needs_list_id;
    const edit = this.overrideEdits[item.item_id] || {};
    if (edit.overridden_qty === undefined || edit.overridden_qty === null) {
      this.workflowErrors = ['Override quantity is required.'];
      return;
    }
    if (!edit.reason) {
      this.workflowErrors = ['Reason is required for overrides.'];
      return;
    }
    this.loading = true;
    this.http
      .patch<NeedsListResponse>(`/api/v1/replenishment/needs-list/${draftId}/lines`, [
        {
          item_id: item.item_id,
          overridden_qty: edit.overridden_qty,
          reason: edit.reason
        }
      ])
      .subscribe({
        next: (data) => {
          this.loading = false;
          this.response = data;
          this.items = data.items ?? [];
          this.topWarnings = data.warnings ?? [];
          this.perItemWarnings = this.items
            .filter((entry) => entry.warnings && entry.warnings.length)
            .map((entry) => ({ item_id: entry.item_id, warnings: entry.warnings ?? [] }));
        },
        error: (error: HttpErrorResponse) => {
          this.loading = false;
          this.workflowErrors = this.extractErrors(error, 'Line update failed.');
        }
      });
  }

  submitDraft(): void {
    if (!this.response?.needs_list_id) {
      return;
    }
    const draftId = this.response.needs_list_id;
    this.loading = true;
    this.http.post<NeedsListResponse>(`/api/v1/replenishment/needs-list/${draftId}/submit`, {}).subscribe({
      next: (data) => {
        this.loading = false;
        this.response = data;
      },
      error: (error: HttpErrorResponse) => {
        this.loading = false;
        this.workflowErrors = this.extractErrors(error, 'Submit failed.');
      }
    });
  }

  startReview(): void {
    this.workflowErrors = [];
    if (!this.response?.needs_list_id) {
      return;
    }
    const draftId = this.response.needs_list_id;
    this.loading = true;
    this.http
      .post<NeedsListResponse>(`/api/v1/replenishment/needs-list/${draftId}/review/start`, {})
      .subscribe({
        next: (data) => {
          this.loading = false;
          this.response = data;
        },
        error: (error: HttpErrorResponse) => {
          this.loading = false;
          this.workflowErrors = this.extractErrors(error, 'Start review failed.');
        }
      });
  }

  returnDraft(): void {
    if (!this.response?.needs_list_id) {
      return;
    }
    const reason = window.prompt('Reason for return:');
    if (!reason) {
      return;
    }
    const draftId = this.response.needs_list_id;
    this.loading = true;
    this.http
      .post<NeedsListResponse>(`/api/v1/replenishment/needs-list/${draftId}/return`, { reason })
      .subscribe({
        next: (data) => {
          this.loading = false;
          this.response = data;
        },
        error: (error: HttpErrorResponse) => {
          this.loading = false;
          this.workflowErrors = this.extractErrors(error, 'Return failed.');
        }
      });
  }

  rejectDraft(): void {
    if (!this.response?.needs_list_id) {
      return;
    }
    const reason = window.prompt('Reason for rejection:');
    if (!reason) {
      return;
    }
    const draftId = this.response.needs_list_id;
    this.loading = true;
    this.http
      .post<NeedsListResponse>(`/api/v1/replenishment/needs-list/${draftId}/reject`, { reason })
      .subscribe({
        next: (data) => {
          this.loading = false;
          this.response = data;
        },
        error: (error: HttpErrorResponse) => {
          this.loading = false;
          this.workflowErrors = this.extractErrors(error, 'Reject failed.');
        }
      });
  }

  applyReviewComment(item: NeedsListItem): void {
    if (!this.response?.needs_list_id) {
      return;
    }
    const comment = this.reviewEdits[item.item_id]?.comment;
    if (!comment || !comment.trim()) {
      this.workflowErrors = ['Comment is required for review notes.'];
      return;
    }
    const draftId = this.response.needs_list_id;
    this.loading = true;
    this.http
      .patch<NeedsListResponse>(`/api/v1/replenishment/needs-list/${draftId}/review-comments`, [
        { item_id: item.item_id, comment }
      ])
      .subscribe({
        next: (data) => {
          this.loading = false;
          this.response = data;
          this.items = data.items ?? [];
        },
        error: (error: HttpErrorResponse) => {
          this.loading = false;
          this.workflowErrors = this.extractErrors(error, 'Review comment failed.');
        }
      });
  }

  approveDraft(): void {
    if (!this.response?.needs_list_id) {
      return;
    }
    const comment = window.prompt('Approval comment (optional):') ?? '';
    const draftId = this.response.needs_list_id;
    this.loading = true;
    this.http
      .post<NeedsListResponse>(`/api/v1/replenishment/needs-list/${draftId}/approve`, {
        comment: comment || undefined
      })
      .subscribe({
        next: (data) => {
          this.loading = false;
          this.response = data;
        },
        error: (error: HttpErrorResponse) => {
          this.loading = false;
          this.workflowErrors = this.extractErrors(error, 'Approve failed.');
        }
      });
  }

  escalateDraft(): void {
    if (!this.response?.needs_list_id) {
      return;
    }
    const reason = window.prompt('Reason for escalation:');
    if (!reason) {
      return;
    }
    const draftId = this.response.needs_list_id;
    this.loading = true;
    this.http
      .post<NeedsListResponse>(`/api/v1/replenishment/needs-list/${draftId}/escalate`, {
        reason
      })
      .subscribe({
        next: (data) => {
          this.loading = false;
          this.response = data;
        },
        error: (error: HttpErrorResponse) => {
          this.loading = false;
          this.workflowErrors = this.extractErrors(error, 'Escalation failed.');
        }
      });
  }

  startPreparation(): void {
    if (!this.response?.needs_list_id) {
      return;
    }
    const draftId = this.response.needs_list_id;
    this.loading = true;
    this.http
      .post<NeedsListResponse>(`/api/v1/replenishment/needs-list/${draftId}/start-preparation`, {})
      .subscribe({
        next: (data) => {
          this.loading = false;
          this.response = data;
        },
        error: (error: HttpErrorResponse) => {
          this.loading = false;
          this.workflowErrors = this.extractErrors(error, 'Start preparation failed.');
        }
      });
  }

  markDispatched(): void {
    if (!this.response?.needs_list_id) {
      return;
    }
    const draftId = this.response.needs_list_id;
    this.loading = true;
    this.http
      .post<NeedsListResponse>(`/api/v1/replenishment/needs-list/${draftId}/mark-dispatched`, {})
      .subscribe({
        next: (data) => {
          this.loading = false;
          this.response = data;
        },
        error: (error: HttpErrorResponse) => {
          this.loading = false;
          this.workflowErrors = this.extractErrors(error, 'Mark dispatched failed.');
        }
      });
  }

  markReceived(): void {
    if (!this.response?.needs_list_id) {
      return;
    }
    const draftId = this.response.needs_list_id;
    this.loading = true;
    this.http
      .post<NeedsListResponse>(`/api/v1/replenishment/needs-list/${draftId}/mark-received`, {})
      .subscribe({
        next: (data) => {
          this.loading = false;
          this.response = data;
        },
        error: (error: HttpErrorResponse) => {
          this.loading = false;
          this.workflowErrors = this.extractErrors(error, 'Mark received failed.');
        }
      });
  }

  markCompleted(): void {
    if (!this.response?.needs_list_id) {
      return;
    }
    const draftId = this.response.needs_list_id;
    this.loading = true;
    this.http
      .post<NeedsListResponse>(`/api/v1/replenishment/needs-list/${draftId}/mark-completed`, {})
      .subscribe({
        next: (data) => {
          this.loading = false;
          this.response = data;
        },
        error: (error: HttpErrorResponse) => {
          this.loading = false;
          this.workflowErrors = this.extractErrors(error, 'Mark completed failed.');
        }
      });
  }

  cancelExecution(): void {
    if (!this.response?.needs_list_id) {
      return;
    }
    const reason = window.prompt('Reason for cancellation:');
    if (!reason) {
      return;
    }
    const draftId = this.response.needs_list_id;
    this.loading = true;
    this.http
      .post<NeedsListResponse>(`/api/v1/replenishment/needs-list/${draftId}/cancel`, { reason })
      .subscribe({
        next: (data) => {
          this.loading = false;
          this.response = data;
        },
        error: (error: HttpErrorResponse) => {
          this.loading = false;
          this.workflowErrors = this.extractErrors(error, 'Cancel failed.');
        }
      });
  }

  updateOverrideQty(item: NeedsListItem, value: string): void {
    const qty = value === '' ? undefined : Number(value);
    this.overrideEdits[item.item_id] = {
      ...this.overrideEdits[item.item_id],
      overridden_qty: Number.isFinite(qty) ? qty : undefined
    };
  }

  updateOverrideReason(item: NeedsListItem, value: string): void {
    this.overrideEdits[item.item_id] = {
      ...this.overrideEdits[item.item_id],
      reason: value
    };
  }

  updateReviewComment(item: NeedsListItem, value: string): void {
    this.reviewEdits[item.item_id] = {
      comment: value
    };
  }

  can(permission: string): boolean {
    return this.permissions.includes(permission);
  }

  canEditLines(): boolean {
    return this.can('replenishment.needs_list.edit_lines');
  }

  canReviewComments(): boolean {
    return this.can('replenishment.needs_list.review_comments');
  }

  canExecute(): boolean {
    return this.can('replenishment.needs_list.execute');
  }

  canCancel(): boolean {
    return this.can('replenishment.needs_list.cancel');
  }

  requiredQty(item: NeedsListItem): number {
    if (typeof item.required_qty === 'number') {
      return Number(item.required_qty.toFixed(2));
    }
    const available = item.available_qty ?? 0;
    const inbound = item.inbound_strict_qty ?? 0;
    const gap = item.gap_qty ?? 0;
    return Number((available + inbound + gap).toFixed(2));
  }

  recommendedQty(item: NeedsListItem): number {
    if (typeof item.computed_required_qty === 'number') {
      return Number(item.computed_required_qty.toFixed(2));
    }
    return this.requiredQty(item);
  }

  horizonValue(block?: HorizonBlock): string {
    if (!block || block.recommended_qty === null || block.recommended_qty === undefined) {
      return 'N/A';
    }
    return block.recommended_qty.toFixed(2);
  }

  confidenceLevel(item: NeedsListItem): string {
    return item.confidence?.level ?? 'unknown';
  }

  freshnessState(item: NeedsListItem): string {
    const state = item.freshness_state ?? item.freshness?.state ?? 'unknown';
    return String(state).toLowerCase();
  }

  freshnessLabel(item: NeedsListItem): string {
    const state = this.freshnessState(item);
    return state.charAt(0).toUpperCase() + state.slice(1);
  }

  timeToStockout(item: NeedsListItem): string {
    const value = item.time_to_stockout ?? '';
    if (typeof value === 'number') {
      return value.toFixed(2);
    }
    return value || 'N/A';
  }

  isEstimated(item: NeedsListItem): boolean {
    return (item.warnings ?? []).includes('burn_rate_estimated');
  }

  warningList(source: string[]): string {
    return source.join(', ');
  }

  warningLabel(code: string): string {
    return this.warningLabels[code] ?? this.humanizeWarning(code);
  }

  private humanizeWarning(code: string): string {
    return code
      .replace(/_/g, ' ')
      .replace(/\b\w/g, (char) => char.toUpperCase());
  }

  dataNotes(): string[] {
    if (!this.response) {
      return [];
    }
    const warnings = new Set<string>([
      ...(this.topWarnings ?? []),
      ...this.perItemWarnings.flatMap((entry) => entry.warnings ?? [])
    ]);
    const hasMissingDataWarning =
      warnings.has('burn_data_missing') ||
      warnings.has('donation_in_transit_unmodeled') ||
      warnings.has('db_unavailable_preview_stub');

    if (!hasMissingDataWarning) {
      return [];
    }

    return [
      'Burn rate and/or inbound may be zero because relief package, transfer, or donation in-transit data is missing or not modeled yet.'
    ];
  }

  isDraft(): boolean {
    return Boolean(this.response?.needs_list_id);
  }

  isDraftEditable(): boolean {
    return this.response?.status === 'DRAFT';
  }

  statusValue(): string {
    return this.response?.status ?? 'DRAFT';
  }

  isStatus(status: string): boolean {
    return this.response?.status === status;
  }

  warehouseSummary(response: NeedsListResponse): string {
    if (response.warehouse_ids?.length) {
      return response.warehouse_ids.join(', ');
    }
    if (response.warehouses?.length) {
      return response.warehouses.map(w => w.warehouse_id).join(', ');
    }
    return 'N/A';
  }

  approvalWarnings(): string[] {
    return this.response?.approval_summary?.warnings ?? [];
  }

  get approvalHorizon(): HorizonType {
    let hasB = false;
    let hasA = false;

    for (const item of this.items) {
      const horizons = item.horizon;
      if (!horizons) {
        continue;
      }
      if ((horizons.C?.recommended_qty ?? 0) > 0) {
        return 'C';
      }
      if ((horizons.B?.recommended_qty ?? 0) > 0) {
        hasB = true;
      }
      if ((horizons.A?.recommended_qty ?? 0) > 0) {
        hasA = true;
      }
    }

    if (hasB) return 'B';
    if (hasA) return 'A';
    return 'A';
  }

  onSendReminder(): void {
    console.log('Send reminder requested for needs list:', this.response?.needs_list_id);
  }

  overrideQty(item: NeedsListItem): number | null {
    const entry = this.overrideEdits[item.item_id];
    if (!entry || entry.overridden_qty === undefined || entry.overridden_qty === null) {
      return null;
    }
    return entry.overridden_qty;
  }

  overrideReason(item: NeedsListItem): string {
    const entry = this.overrideEdits[item.item_id];
    return entry?.reason ?? '';
  }

  private buildPayload(): Record<string, unknown> {
    const payload: Record<string, unknown> = {
      event_id: Number(this.form.value.event_id),
      warehouse_id: Number(this.form.value.warehouse_id),
      phase: this.form.value.phase
    };

    if (this.form.value.as_of_datetime) {
      payload['as_of_datetime'] = this.form.value.as_of_datetime;
    }

    return payload;
  }

  private resetWorkflowState(): void {
    this.overrideEdits = {};
  }

  private loadPermissions(): void {
    this.http.get<{ permissions: string[] }>('/api/v1/auth/whoami/').subscribe({
      next: (data) => {
        this.permissions = data.permissions ?? [];
      },
      error: () => {
        this.permissions = [];
      }
    });
  }

  private extractErrors(error: HttpErrorResponse, fallback: string): string[] {
    if (error.status === 403) {
      return ['You do not have permission to perform this action.'];
    }
    if (error.error?.errors) {
      const errors = error.error.errors;
      if (Array.isArray(errors)) {
        return errors;
      }
      return Object.entries(errors).flatMap(([field, message]) => {
        if (Array.isArray(message)) {
          return message.map((entry) => `${field}: ${entry}`);
        }
        return [`${field}: ${message}`];
      });
    }
    return [error.message || fallback];
  }
}
