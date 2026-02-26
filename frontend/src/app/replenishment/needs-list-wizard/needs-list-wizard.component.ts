import { Component, OnInit, ViewChild, DestroyRef, ChangeDetectorRef, inject } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { MatStepperModule, MatStepper } from '@angular/material/stepper';
import { StepperSelectionEvent } from '@angular/cdk/stepper';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatCardModule } from '@angular/material/card';
import { MatTooltipModule } from '@angular/material/tooltip';

import { WizardStateService } from './services/wizard-state.service';
import { ItemAdjustment, AdjustmentReason } from './models/wizard-state.model';
import { ScopeStepComponent } from './steps/step1-scope/scope-step.component';
import { PreviewStepComponent } from './steps/step2-preview/preview-step.component';
import { SubmitStepComponent } from './steps/step3-submit/submit-step.component';
import { NeedsListItem, NeedsListResponse } from '../models/needs-list.model';
import { ReplenishmentService } from '../services/replenishment.service';
import { EventPhase } from '../models/stock-status.model';
import { DmisNotificationService } from '../services/notification.service';
import { WizardState } from './models/wizard-state.model';

interface SubmitStepCompleteEvent {
  action: 'draft_saved' | 'submitted_for_approval';
  totalItems: number;
  completedAt: string;
  approver?: string;
}

interface WizardConfirmationState {
  action: 'draft_saved' | 'submitted_for_approval';
  totalItems: number;
  completedAt: string;
  approver?: string;
}

@Component({
  selector: 'app-needs-list-wizard',
  standalone: true,
  imports: [
    CommonModule,
    MatStepperModule,
    MatButtonModule,
    MatIconModule,
    MatCardModule,
    MatTooltipModule,
    ScopeStepComponent,
    PreviewStepComponent,
    SubmitStepComponent
  ],
  templateUrl: './needs-list-wizard.component.html',
  styleUrls: ['./needs-list-wizard.component.scss']
})
export class NeedsListWizardComponent implements OnInit {
  @ViewChild('stepper') stepper!: MatStepper;
  private destroyRef = inject(DestroyRef);
  private cdr = inject(ChangeDetectorRef);
  public wizardService = inject(WizardStateService);
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private replenishmentService = inject(ReplenishmentService);
  private notificationService = inject(DmisNotificationService);
  private hydratedNeedsListId: string | null = null;

  readonly isStep1Valid$ = this.wizardService.isStep1Valid$();
  readonly isStep2Valid$ = this.wizardService.isStep2Valid$();
  confirmationState: WizardConfirmationState | null = null;

  ngOnInit(): void {
    // Load query params from dashboard navigation
import { combineLatest } from 'rxjs';

    combineLatest([this.route.paramMap, this.route.queryParams]).pipe(
      takeUntilDestroyed(this.destroyRef)
    ).subscribe(([paramMap, params]) => {
      const routeNeedsListId = String(paramMap.get('id') ?? '').trim();
      const needsListId = String(params['needs_list_id'] ?? routeNeedsListId).trim();
      if (!needsListId) {
        this.hydratedNeedsListId = null;
        this.resetStaleStateForNewWizardSession();
      }

      if (params['event_id']) {
        // Convert single warehouse_id to array for multi-warehouse support
        const warehouseId = params['warehouse_id'];
        const warehouseIds = warehouseId ? [Number(warehouseId)] : [];

        this.wizardService.updateState({
          event_id: Number(params['event_id']),
          warehouse_ids: warehouseIds,
          phase: params['phase'] || 'BASELINE'
        });
      }

      if (!needsListId) {
        this.wizardService.updateState({ editing_draft_id: undefined });
        return;
      }
      if (needsListId && needsListId !== this.hydratedNeedsListId) {
        this.loadExistingNeedsList(needsListId);
      }
    });
  }

  private resetStaleStateForNewWizardSession(): void {
    const state = this.wizardService.getState();
    if (!this.shouldResetStateForNewWizardSession(state)) {
      return;
    }
    this.wizardService.reset();
  }

  private shouldResetStateForNewWizardSession(state: WizardState): boolean {
    const editingDraftId = String(state.editing_draft_id || '').trim();
    const hasDraftIds = (state.draft_ids || []).some(
      (id) => String(id || '').trim().length > 0
    );
    const previewNeedsListId = String(state.previewResponse?.needs_list_id || '').trim();
    const previewStatus = String(state.previewResponse?.status || '').trim();
    const hasPreviewItems = (state.previewResponse?.items || []).length > 0;
    const hasSelectedItemKeys = (state.selectedItemKeys || []).some(
      (value) => String(value || '').trim().length > 0
    );
    const hasAdjustments = Object.keys(state.adjustments || {}).length > 0;
    const hasNotes = String(state.notes || '').trim().length > 0;

    return (
      editingDraftId.length > 0 ||
      hasDraftIds ||
      previewNeedsListId.length > 0 ||
      previewStatus.length > 0 ||
      hasPreviewItems ||
      hasSelectedItemKeys ||
      hasAdjustments ||
      hasNotes
    );
  }

  backToDashboard(): void {
    // Confirm if user wants to abandon wizard
    const state = this.wizardService.getState();
    const hasData = state.event_id || (state.warehouse_ids && state.warehouse_ids.length > 0);

    if (hasData) {
      const confirmed = confirm('Are you sure you want to leave? Any unsaved changes will be lost.');
      if (!confirmed) {
        return;
      }
    }

    const queryParams = this.dashboardQueryParams();
    this.wizardService.reset();
    this.router.navigate(['/replenishment/dashboard'], { queryParams });
  }

  onStepChange(event: StepperSelectionEvent): void {
    // Track step changes for analytics
    console.log('Step changed:', event.selectedIndex);
  }

  onComplete(event: SubmitStepCompleteEvent): void {
    this.confirmationState = {
      action: event.action,
      totalItems: event.totalItems,
      completedAt: event.completedAt,
      approver: event.approver
    };

    // Force navigation to step 4 confirmation without requiring header click.
    this.cdr.detectChanges();
    queueMicrotask(() => {
      if (this.stepper) {
        this.stepper.selectedIndex = 3;
      }
    });
  }

  returnToDashboardFromConfirmation(): void {
    const queryParams = this.dashboardQueryParams();
    this.wizardService.reset();
    this.confirmationState = null;
    this.router.navigate(['/replenishment/dashboard'], { queryParams });
  }

  returnToSubmitStepFromConfirmation(): void {
    this.confirmationState = null;
    if (this.stepper) {
      this.stepper.selectedIndex = 2;
    }
  }

  startNewNeedsList(): void {
    this.wizardService.reset();
    this.confirmationState = null;
    if (this.stepper) {
      this.stepper.reset();
    }
  }

  private dashboardQueryParams(): { context: 'wizard'; event_id?: number; phase?: string } {
    const state = this.wizardService.getState();
    const params: { context: 'wizard'; event_id?: number; phase?: string } = {
      context: 'wizard'
    };
    if (state.event_id) {
      params.event_id = state.event_id;
    }
    if (state.phase) {
      params.phase = state.phase;
    }
    return params;
  }

  private loadExistingNeedsList(needsListId: string): void {
    this.replenishmentService.getNeedsList(needsListId).pipe(
      takeUntilDestroyed(this.destroyRef)
    ).subscribe({
      next: (record) => {
        if (record.status === 'SUPERSEDED' || record.superseded_by_needs_list_id) {
          this.hydratedNeedsListId = null;
          this.wizardService.updateState({ editing_draft_id: undefined });
          const replacementId = String(record.superseded_by_needs_list_id ?? '').trim();
          this.notificationService.showWarning('This draft has been superseded.');
          if (replacementId) {
            this.router.navigate(['/replenishment/needs-list', replacementId, 'review']);
          } else {
            this.router.navigate(['/replenishment/needs-list', needsListId, 'superseded']);
          }
          return;
        }
        this.hydratedNeedsListId = needsListId;
        this.hydrateWizardStateFromNeedsList(record, needsListId);
      },
      error: (error: unknown) => {
        this.hydratedNeedsListId = null;
        this.wizardService.updateState({ editing_draft_id: undefined });
        this.notificationService.showError(this.extractNeedsListLoadErrorMessage(error));
      }
    });
  }

  private extractNeedsListLoadErrorMessage(error: unknown): string {
    const fallback = 'Failed to load needs list.';
    const maybeHttpError = error as {
      error?: { errors?: Record<string, unknown>; detail?: unknown; message?: unknown };
      message?: unknown;
    };

    const errorMap = maybeHttpError?.error?.errors;
    if (errorMap && typeof errorMap === 'object') {
      const firstValue = Object.values(errorMap)[0];
      if (typeof firstValue === 'string' && firstValue.trim()) {
        return `${fallback} ${firstValue.trim()}`;
      }
      if (Array.isArray(firstValue) && firstValue.length > 0) {
        const firstItem = firstValue[0];
        if (typeof firstItem === 'string' && firstItem.trim()) {
          return `${fallback} ${firstItem.trim()}`;
        }
      }
    }

    const detail = maybeHttpError?.error?.detail;
    if (typeof detail === 'string' && detail.trim()) {
      return `${fallback} ${detail.trim()}`;
    }

    const apiMessage = maybeHttpError?.error?.message;
    if (typeof apiMessage === 'string' && apiMessage.trim()) {
      return `${fallback} ${apiMessage.trim()}`;
    }

    if (error instanceof Error && error.message) {
      return `${fallback} ${error.message}`;
    }
    if (typeof maybeHttpError?.message === 'string' && maybeHttpError.message.trim()) {
      return `${fallback} ${maybeHttpError.message.trim()}`;
    }
    return fallback;
  }

  private hydrateWizardStateFromNeedsList(record: NeedsListResponse, needsListId: string): void {
    const warehouseIds = this.resolveWarehouseIds(record);
    const normalizedItems = this.normalizeNeedsListItems(record.items || [], warehouseIds, record.warehouse_id);
    const selectedItemKeys = this.resolveSelectedItemKeys(record, normalizedItems, warehouseIds);
    const adjustments = this.extractAdjustments(record, normalizedItems);
    const phase = (record.phase || 'BASELINE') as EventPhase;

    this.wizardService.updateState({
      event_id: record.event_id,
      event_name: record.event_name,
      warehouse_ids: warehouseIds,
      phase,
      as_of_datetime: record.as_of_datetime,
      previewResponse: {
        ...record,
        phase,
        warehouse_ids: warehouseIds,
        items: normalizedItems
      },
      selectedItemKeys,
      draft_ids: [needsListId],
      editing_draft_id: needsListId,
      adjustments
    });

    this.confirmationState = null;
    this.cdr.detectChanges();
    queueMicrotask(() => {
      if (this.stepper && normalizedItems.length > 0) {
        this.stepper.selectedIndex = 1;
      }
    });
  }

  private resolveWarehouseIds(record: NeedsListResponse): number[] {
    if (Array.isArray(record.warehouse_ids) && record.warehouse_ids.length > 0) {
      return record.warehouse_ids.filter((warehouseId) => Number.isInteger(warehouseId) && warehouseId > 0);
    }
    if (Number.isInteger(record.warehouse_id) && (record.warehouse_id ?? 0) > 0) {
      return [record.warehouse_id as number];
    }
    return [];
  }

  private normalizeNeedsListItems(
    items: NeedsListItem[],
    warehouseIds: number[],
    fallbackWarehouseId?: number
  ): NeedsListItem[] {
    const defaultWarehouseId = warehouseIds[0] ?? fallbackWarehouseId ?? 0;
    return items.map((item) => ({
      ...item,
      warehouse_id: item.warehouse_id ?? defaultWarehouseId,
    }));
  }

  private resolveSelectedItemKeys(
    record: NeedsListResponse,
    items: NeedsListItem[],
    warehouseIds: number[]
  ): string[] {
    const explicit = (record.selected_item_keys || [])
      .map((value) => String(value || '').trim())
      .filter((value) => value.length > 0);
    if (explicit.length > 0) {
      return explicit;
    }

    const defaultWarehouseId = warehouseIds[0] ?? record.warehouse_id ?? 0;
    return items
      .filter((item) => Number(item.gap_qty || 0) > 0)
      .map((item) => `${item.item_id}_${item.warehouse_id ?? defaultWarehouseId}`);
  }

  private extractAdjustments(
    record: NeedsListResponse,
    items: NeedsListItem[]
  ): Record<string, ItemAdjustment> {
    const rawRecord = record as NeedsListResponse & {
      line_overrides?: Record<string, { overridden_qty?: number; reason?: string }>;
    };
    const lineOverrides = rawRecord.line_overrides;
    if (!lineOverrides || typeof lineOverrides !== 'object') {
      return {};
    }

    const itemsById = new Map<number, NeedsListItem>();
    for (const item of items) {
      if (!itemsById.has(item.item_id)) {
        itemsById.set(item.item_id, item);
      }
    }

    const adjustments: Record<string, ItemAdjustment> = {};
    for (const [itemIdKey, override] of Object.entries(lineOverrides)) {
      const itemId = Number(itemIdKey);
      if (!Number.isFinite(itemId) || itemId <= 0) {
        continue;
      }
      const item = itemsById.get(itemId);
      if (!item) {
        continue;
      }
      const warehouseId = item.warehouse_id || 0;
      const rawReason = String(override?.reason || '').trim();
      const reason = this.toAdjustmentReason(rawReason);
      const adjustedQty = Number(override?.overridden_qty ?? item.gap_qty ?? 0);
      adjustments[`${itemId}_${warehouseId}`] = {
        item_id: itemId,
        warehouse_id: warehouseId,
        original_qty: Number(item.gap_qty || 0),
        adjusted_qty: Number.isFinite(adjustedQty) ? adjustedQty : Number(item.gap_qty || 0),
        reason,
        notes: reason === 'OTHER' && rawReason && rawReason !== 'OTHER' ? rawReason : ''
      };
    }
    return adjustments;
  }

  private toAdjustmentReason(value: string): AdjustmentReason {
    const normalized = value.toUpperCase();
    if (
      normalized === 'PARTIAL_COVERAGE' ||
      normalized === 'DEMAND_ADJUSTED' ||
      normalized === 'PRIORITY_CHANGE' ||
      normalized === 'BUDGET_CONSTRAINT' ||
      normalized === 'OTHER'
    ) {
      return normalized;
    }
    return 'OTHER';
  }
}
