import { Component, OnInit, Output, EventEmitter, DestroyRef, inject } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, ReactiveFormsModule } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatChipsModule } from '@angular/material/chips';
import { MatDividerModule } from '@angular/material/divider';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatRadioModule } from '@angular/material/radio';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { FormsModule } from '@angular/forms';
import { Observable, forkJoin, from, of, throwError } from 'rxjs';
import { catchError, concatMap, finalize, map, switchMap, toArray } from 'rxjs/operators';

import { WizardStateService } from '../../services/wizard-state.service';
import { DmisNotificationService } from '../../../services/notification.service';
import {
  NeedsListLineOverridePayload,
  ReplenishmentService
} from '../../../services/replenishment.service';
import { DmisEmptyStateComponent } from '../../../shared/dmis-empty-state/dmis-empty-state.component';
import {
  ConfirmDialogData,
  DmisConfirmDialogComponent
} from '../../../shared/dmis-confirm-dialog/dmis-confirm-dialog.component';
import { NeedsListItem, NeedsListResponse } from '../../../models/needs-list.model';
import {
  APPROVAL_WORKFLOWS,
  ApprovalWorkflowData,
  HorizonType
} from '../../../models/approval-workflows.model';
import { ADJUSTMENT_REASON_LABELS } from '../../models/wizard-state.model';

interface WarehouseBreakdown {
  warehouse_id: number;
  warehouse_name: string;
  items: number;
  units: number;
  cost: number;
}

export interface SubmitStepCompleteEvent {
  action: 'draft_saved' | 'submitted_for_approval';
  totalItems: number;
  completedAt: string;
  approver?: string;
}


@Component({
  selector: 'app-submit-step',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    ReactiveFormsModule,
    MatCardModule,
    MatButtonModule,
    MatIconModule,
    MatFormFieldModule,
    MatInputModule,
    MatChipsModule,
    MatDividerModule,
    MatProgressBarModule,
    MatProgressSpinnerModule,
    MatDialogModule,
    MatRadioModule,
    DmisEmptyStateComponent
  ],
  templateUrl: './submit-step.component.html',
  styleUrl: './submit-step.component.scss'
})
export class SubmitStepComponent implements OnInit {
  private fb = inject(FormBuilder);
  private wizardService = inject(WizardStateService);
  private replenishmentService = inject(ReplenishmentService);

  @Output() back = new EventEmitter<void>();
  @Output() complete = new EventEmitter<SubmitStepCompleteEvent>();

  items: NeedsListItem[] = [];
  selectedItems: NeedsListItem[] = [];  // Only selected items
  warehouseBreakdown: WarehouseBreakdown[] = [];

  totalItems = 0;
  totalUnits = 0;
  totalCost = 0;
  totalReviewed = 0;  // Total items reviewed (not just selected)

  notesForm: FormGroup;
  loading = false;
  submitting = false;
  savingDraft = false;
  errors: string[] = [];
  showAllItems = false;  // For items preview expansion
  showApprovalDetails = true;  // For approval workflow details (expanded by default)

  // Horizon-based approval workflows
  approvalWorkflows: ApprovalWorkflowData[] = [];
  activeWorkflow: ApprovalWorkflowData | null = null;
  activeApprovalWorkflows: ApprovalWorkflowData[] = [];

  // Method override
  selectedMethod: HorizonType = 'A';
  recommendedMethod: HorizonType = 'A';
  itemsExpanded = false;

  // All horizons for template iteration (typed to avoid strict template errors)
  allHorizons: HorizonType[] = ['A', 'B', 'C'];

  // Method display metadata
  methodMeta: Record<HorizonType, { label: string; sublabel: string; timeframe: string; inDmis: boolean }> = {
    A: { label: 'TRANSFER', sublabel: 'Inter-Warehouse', timeframe: '6-24 hours', inDmis: true },
    B: { label: 'DONATION', sublabel: 'From Verified Donations', timeframe: '2-7 days', inDmis: true },
    C: { label: 'PROCUREMENT', sublabel: 'Purchase New Stock', timeframe: '14+ days', inDmis: false }
  };

  private destroyRef = inject(DestroyRef);
  private notificationService = inject(DmisNotificationService);
  private dialog = inject(MatDialog);

  constructor() {
    this.notesForm = this.fb.group({
      notes: ['']
    });
  }

  ngOnInit(): void {
    // Subscribe to wizard state changes
    // Note: mat-stepper renders all steps at once, so we need to react to ALL state changes
    this.wizardService.getState$().pipe(
      takeUntilDestroyed(this.destroyRef)
    ).subscribe(state => {
      const items = state.previewResponse?.items || [];
      const selectedItemKeys = state.selectedItemKeys || [];
      const selectedMethod = this.normalizeSelectedMethod(state.previewResponse?.selected_method);

      this.items = items;
      this.totalReviewed = items.length;
      if (selectedMethod) {
        this.selectedMethod = selectedMethod;
      }

      // Filter to only selected items
      const selectedKeys = new Set(selectedItemKeys);
      this.selectedItems = items.filter(item => {
        const key = `${item.item_id}_${item.warehouse_id || 0}`;
        return selectedKeys.has(key);
      });

      this.calculateSummary();
    });

    // Load existing notes from state
    const state = this.wizardService.getState();
    if (state.notes) {
      this.notesForm.patchValue({ notes: state.notes });
    }

    // Auto-save notes to state
    this.notesForm.valueChanges.pipe(
      takeUntilDestroyed(this.destroyRef)
    ).subscribe(values => {
      this.wizardService.updateState({ notes: values.notes });
    });
  }

  calculateSummary(): void {
    if (!this.selectedItems.length) {
      this.totalItems = 0;
      this.totalUnits = 0;
      this.totalCost = 0;
      this.warehouseBreakdown = [];
      this.approvalWorkflows = [];
      this.activeWorkflow = null;
      this.activeApprovalWorkflows = [];
      return;
    }

    // Apply adjustments to selected items only
    const adjustedItems = this.selectedItems.map(item => {
      const adjustment = this.wizardService.getAdjustment(item.item_id, item.warehouse_id || 0);
      const adjustedQty = adjustment ? adjustment.adjusted_qty : item.gap_qty;
      return {
        ...item,
        gap_qty: adjustedQty,
        // Ensure we have a positive quantity for workflow calculation
        effective_qty: Math.max(adjustedQty, 0)
      };
    });

    // Calculate totals from selected items
    this.totalItems = adjustedItems.length;
    this.totalUnits = adjustedItems.reduce((sum, item) => sum + (item.gap_qty || 0), 0);
    this.totalCost = adjustedItems.reduce((sum, item) => sum + this.getItemCost(item), 0);

    // Group by warehouse
    const byWarehouse = new Map<number, { name: string; items: number; units: number; cost: number }>();

    adjustedItems.forEach(item => {
      const warehouseId = item.warehouse_id || 0;

      if (!byWarehouse.has(warehouseId)) {
        byWarehouse.set(warehouseId, {
          name: item.warehouse_name || `Warehouse ${warehouseId}`,
          items: 0,
          units: 0,
          cost: 0
        });
      }

      const wh = byWarehouse.get(warehouseId)!;
      wh.items++;
      wh.units += item.gap_qty || 0;
      wh.cost += this.getItemCost(item);
    });

    this.warehouseBreakdown = Array.from(byWarehouse.entries())
      .map(([id, data]) => ({
        warehouse_id: id,
        warehouse_name: data.name,
        items: data.items,
        units: data.units,
        cost: data.cost
      }))
      .sort((a, b) => a.warehouse_name.localeCompare(b.warehouse_name));

    // Calculate approval workflows based on horizons (use adjusted items)
    this.calculateApprovalWorkflows(adjustedItems);
  }

  private calculateApprovalWorkflows(adjustedItems: (NeedsListItem & { effective_qty: number })[]): void {
    const horizonData: Record<HorizonType, { items: number; units: number }> = {
      A: { items: 0, units: 0 },
      B: { items: 0, units: 0 },
      C: { items: 0, units: 0 }
    };

    // Count items and units by horizon using adjusted quantities
    adjustedItems.forEach(item => {
      const horizons = item.horizon;
      let hasAnyHorizonQty = false;
      const effectiveQty = item.effective_qty || item.gap_qty || 0;

      if (horizons) {
        // Count for each horizon independently (not mutually exclusive)
        const aQty = horizons.A?.recommended_qty;
        const bQty = horizons.B?.recommended_qty;
        const cQty = horizons.C?.recommended_qty;

        if (aQty && aQty > 0) {
          horizonData.A.items++;
          horizonData.A.units += aQty;
          hasAnyHorizonQty = true;
        }
        if (bQty && bQty > 0) {
          horizonData.B.items++;
          horizonData.B.units += bQty;
          hasAnyHorizonQty = true;
        }
        if (cQty && cQty > 0) {
          horizonData.C.items++;
          horizonData.C.units += cQty;
          hasAnyHorizonQty = true;
        }
      }

      // Fallback: If no horizon data OR all horizon quantities are 0/null,
      // default to Transfer (A) with the effective quantity
      if (!hasAnyHorizonQty && effectiveQty > 0) {
        horizonData.A.items++;
        horizonData.A.units += effectiveQty;
      }
    });

    // Build approval workflows for horizons that have items
    this.approvalWorkflows = (['A', 'B', 'C'] as HorizonType[])
      .filter(horizon => horizonData[horizon].items > 0)
      .map(horizon => ({
        horizon,
        config: APPROVAL_WORKFLOWS[horizon],
        itemCount: horizonData[horizon].items,
        totalUnits: horizonData[horizon].units
      }));

    // Final fallback: If still no workflows but we have selected items, default to Transfer
    if (this.approvalWorkflows.length === 0 && adjustedItems.length > 0) {
      this.approvalWorkflows = [{
        horizon: 'A' as HorizonType,
        config: APPROVAL_WORKFLOWS.A,
        itemCount: adjustedItems.length,
        totalUnits: adjustedItems.reduce((sum, i) => sum + (i.effective_qty || i.gap_qty || 0), 0)
      }];
    }

    // Determine recommended method (the horizon with most items)
    if (this.approvalWorkflows.length > 0) {
      const primary = this.approvalWorkflows.reduce((max, wf) =>
        wf.itemCount > max.itemCount ? wf : max
      );
      this.recommendedMethod = primary.horizon;
      // Only set selectedMethod if it hasn't been initialized yet,
      // or if the current selection is no longer valid
      const validHorizons = this.approvalWorkflows.map(wf => wf.horizon);
      if (!validHorizons.includes(this.selectedMethod)) {
        this.selectedMethod = primary.horizon;
      }
    }

    this.updateActiveApprovalWorkflow();
  }

  // Get the primary replenishment method (the one with most items)
  getPrimaryHorizon(): ApprovalWorkflowData | null {
    if (this.approvalWorkflows.length === 0) return null;
    return this.approvalWorkflows.reduce((max, wf) =>
      wf.itemCount > max.itemCount ? wf : max
    );
  }

  // Get timeframe for a horizon
  getHorizonTimeframe(horizon: HorizonType): string {
    const timeframes: Record<HorizonType, string> = {
      A: '6-24 hours',
      B: '2-7 days',
      C: '14+ days'
    };
    return timeframes[horizon];
  }

  onMethodChange(method: HorizonType): void {
    this.selectedMethod = method;
    this.updateActiveApprovalWorkflow();
  }

  /** Recalculate which approval workflow to display based on selectedMethod */
  private updateActiveApprovalWorkflow(): void {
    if (this.approvalWorkflows.length === 0) {
      this.activeWorkflow = null;
      this.activeApprovalWorkflows = [];
      return;
    }

    const existing = this.approvalWorkflows.find(wf => wf.horizon === this.selectedMethod);
    if (existing) {
      this.activeWorkflow = existing;
      this.activeApprovalWorkflows = [existing];
      return;
    }

    // Build a single workflow entry for the currently selected method
    const config = APPROVAL_WORKFLOWS[this.selectedMethod];
    const horizonItems = this.getHorizonItems(this.selectedMethod);
    const horizonUnits = this.getHorizonUnits(this.selectedMethod);

    // If the selected method has no items of its own, show all items count
    this.activeWorkflow = {
      horizon: this.selectedMethod,
      config,
      itemCount: horizonItems > 0 ? horizonItems : this.totalItems,
      totalUnits: horizonUnits > 0 ? horizonUnits : this.totalUnits
    };
    this.activeApprovalWorkflows = [this.activeWorkflow];
  }

  getMethodItemCount(horizon: HorizonType): string {
    const count = this.getHorizonItems(horizon);
    if (count > 0) return `${count} items`;
    if (horizon === 'C') return 'All items';
    return '0 items available';
  }

  toggleItemsExpanded(): void {
    this.itemsExpanded = !this.itemsExpanded;
  }

  getApprovalSummary(): string {
    if (this.approvalWorkflows.length === 0) {
      return 'No items requiring approval';
    }

    const workflowNames = this.approvalWorkflows.map(wf => wf.config.name);
    if (workflowNames.length === 1) {
      return `${workflowNames[0]} approval required`;
    }
    return `${workflowNames.slice(0, -1).join(', ')} and ${workflowNames[workflowNames.length - 1]} approvals required`;
  }

  getItemCost(item: NeedsListItem): number {
    const unitCost = item.procurement?.est_unit_cost ?? 0;
    const quantity = this.getAdjustedQty(item) ?? 0;
    return quantity * unitCost;
  }

  getHorizonItems(horizon: 'A' | 'B' | 'C'): number {
    if (!this.selectedItems.length) return 0;

    return this.selectedItems.reduce((count, item) => {
      const horizons = item.horizon;

      if (horizons) {
        // Check the specific horizon requested
        const qty = horizons[horizon]?.recommended_qty;
        if (qty && qty > 0) {
          return count + 1;
        }

        // Check if item has ANY horizon qty - if not, fallback to A
        const hasAnyHorizonQty =
          (horizons.A?.recommended_qty && horizons.A.recommended_qty > 0) ||
          (horizons.B?.recommended_qty && horizons.B.recommended_qty > 0) ||
          (horizons.C?.recommended_qty && horizons.C.recommended_qty > 0);

        if (!hasAnyHorizonQty && horizon === 'A' && item.gap_qty > 0) {
          return count + 1;
        }
      } else if (horizon === 'A' && item.gap_qty > 0) {
        // Fallback: items without horizon data default to Transfer (A)
        return count + 1;
      }

      return count;
    }, 0);
  }

  getHorizonUnits(horizon: 'A' | 'B' | 'C'): number {
    if (!this.selectedItems.length) return 0;

    return this.selectedItems.reduce((sum, item) => {
      const horizons = item.horizon;

      if (horizons) {
        // Get the quantity for the specific horizon requested
        const qty = horizons[horizon]?.recommended_qty;
        if (qty && qty > 0) {
          return sum + qty;
        }

        // Check if item has ANY horizon qty - if not, fallback to A
        const hasAnyHorizonQty =
          (horizons.A?.recommended_qty && horizons.A.recommended_qty > 0) ||
          (horizons.B?.recommended_qty && horizons.B.recommended_qty > 0) ||
          (horizons.C?.recommended_qty && horizons.C.recommended_qty > 0);

        if (!hasAnyHorizonQty && horizon === 'A' && item.gap_qty > 0) {
          return sum + item.gap_qty;
        }
      } else if (horizon === 'A' && item.gap_qty > 0) {
        // Fallback: items without horizon data default to Transfer (A)
        return sum + item.gap_qty;
      }

      return sum;
    }, 0);
  }

  getPhaseLabel(): string {
    const state = this.wizardService.getState();
    return state.phase || 'BASELINE';
  }

  getEventId(): number | undefined {
    return this.wizardService.getState().event_id;
  }

  getEventName(): string {
    const state = this.wizardService.getState();
    return state.event_name || `Event ${state.event_id || 'N/A'}`;
  }

  toggleItemsList(): void {
    this.showAllItems = !this.showAllItems;
  }

  toggleApprovalDetails(): void {
    this.showApprovalDetails = !this.showApprovalDetails;
  }

  getAdjustedQty(item: NeedsListItem): number {
    const adjustment = this.wizardService.getAdjustment(item.item_id, item.warehouse_id || 0);
    return adjustment ? adjustment.adjusted_qty : item.gap_qty;
  }

  hasExternalWorkflow(): boolean {
    return this.approvalWorkflows.some(wf => !wf.config.inDmis);
  }

  getApprovalWorkflowNames(): string {
    return this.approvalWorkflows.map(wf => wf.config.name).join(', ');
  }

  getApprovalInfo(): string {
    if (this.approvalWorkflows.length === 0) {
      return 'No approvers required';
    }

    // Build a summary of the primary approvers for each workflow
    const approvers = this.approvalWorkflows.map(wf => {
      const primaryStep = wf.config.steps.find(s => s.type === 'primary');
      return primaryStep ? primaryStep.role : wf.config.steps[0]?.role || 'Unknown';
    });

    // Remove duplicates
    const uniqueApprovers = [...new Set(approvers)];

    if (uniqueApprovers.length === 1) {
      return uniqueApprovers[0];
    }

    return uniqueApprovers.slice(0, -1).join(', ') + ' and ' + uniqueApprovers[uniqueApprovers.length - 1];
  }

  saveDraft(): void {
    this.errors = [];

    if (this.totalItems === 0) {
      this.errors = ['No items to save. Please go back to Step 2.'];
      return;
    }

    this.savingDraft = true;

    this.ensureDraftIds().pipe(
      takeUntilDestroyed(this.destroyRef),
      finalize(() => {
        this.savingDraft = false;
      })
    ).subscribe({
      next: (draftIds) => {
        const countText = draftIds.length === 1 ? 'Draft' : `${draftIds.length} drafts`;
        this.notificationService.showSuccess(`${countText} saved successfully. Your progress has been preserved.`);
        this.complete.emit({
          action: 'draft_saved',
          totalItems: this.totalItems,
          completedAt: new Date().toISOString()
        });
      },
      error: (error: unknown) => {
        const message = this.extractErrorMessage(error, 'Failed to save draft.');
        this.errors = [message];
        this.notificationService.showError(message);
      }
    });
  }

  private ensureDraftIds(): Observable<string[]> {
    return this.createDrafts();
  }

  private getExistingDraftIds(): string[] {
    return (this.wizardService.getState().draft_ids || []).filter(
      (id): id is string => typeof id === 'string' && id.trim().length > 0
    );
  }

  private createDrafts(): Observable<string[]> {
    const state = this.wizardService.getState();
    const eventId = state.event_id;
    if (!eventId) {
      return throwError(() => new Error('Event is required before saving or submitting.'));
    }

    const warehouseIds = this.getSubmissionWarehouseIds();
    if (warehouseIds.length === 0) {
      return throwError(() => new Error('At least one warehouse is required before saving or submitting.'));
    }

    const phase = state.phase || 'BASELINE';
    const asOfDatetime = state.as_of_datetime || state.previewResponse?.as_of_datetime;
    const expectedCountsByWarehouse = this.getSelectedCountsByWarehouse();
    const expectedRequiredQtyByWarehouse = this.getExpectedRequiredQtyByWarehouse();

    return this.collectReusableDraftIds(
      eventId,
      phase,
      warehouseIds,
      expectedCountsByWarehouse,
      expectedRequiredQtyByWarehouse
    ).pipe(
      switchMap((draftIdsByWarehouse) => {
        const reusableDraftIds = this.orderDraftIdsByWarehouse(warehouseIds, draftIdsByWarehouse);
        if (reusableDraftIds.length > 0) {
          this.wizardService.updateState({ draft_ids: reusableDraftIds });
        }

        const missingWarehouseIds = warehouseIds.filter(
          (warehouseId) => !draftIdsByWarehouse.has(warehouseId)
        );

        const finalizeDraftIds = (): Observable<string[]> =>
          this.persistLineOverridesForDrafts(warehouseIds, draftIdsByWarehouse).pipe(
            map(() => {
              const draftIds = this.orderDraftIdsByWarehouse(warehouseIds, draftIdsByWarehouse);
              if (draftIds.length !== warehouseIds.length) {
                throw new Error('Failed to create all required drafts for submission.');
              }
              this.wizardService.updateState({ draft_ids: draftIds });
              return draftIds;
            })
          );

        if (missingWarehouseIds.length === 0) {
          return finalizeDraftIds();
        }

        return from(missingWarehouseIds).pipe(
          concatMap((warehouseId) =>
            this.replenishmentService.createNeedsListDraft({
              event_id: eventId,
              warehouse_id: warehouseId,
              phase,
              as_of_datetime: asOfDatetime,
              selected_item_keys: this.getSelectedItemKeysForWarehouse(warehouseId),
              selected_method: this.selectedMethod
            }).pipe(
              map((response) => {
                const draftId = response.needs_list_id;
                if (typeof draftId !== 'string' || draftId.trim().length === 0) {
                  throw new Error(
                    `Draft creation succeeded, but no draft ID was returned for warehouse ${warehouseId}.`
                  );
                }

                draftIdsByWarehouse.set(warehouseId, draftId);
                const partialDraftIds = this.orderDraftIdsByWarehouse(warehouseIds, draftIdsByWarehouse);
                this.wizardService.updateState({ draft_ids: partialDraftIds });
                return draftId;
              })
            )
          ),
          toArray(),
          switchMap(() => finalizeDraftIds())
        );
      })
    );
  }

  private collectReusableDraftIds(
    expectedEventId: number,
    phase: string,
    warehouseIds: number[],
    expectedCountsByWarehouse: Map<number, number>,
    expectedRequiredQtyByWarehouse: Map<number, Map<number, number>>
  ): Observable<Map<number, string>> {
    const existingDraftIds = this.getExistingDraftIds();
    if (existingDraftIds.length === 0) {
      return of(new Map<number, string>());
    }

    const expectedPhase = String(phase || 'BASELINE').toUpperCase();
    const expectedWarehouseIds = new Set(warehouseIds);
    const expectedMethod = this.selectedMethod;

    return this.replenishmentService.listNeedsLists(['DRAFT'], { mine: true }).pipe(
      map(({ needs_lists }) => {
        const recordsById = new Map<string, NeedsListResponse>();
        for (const record of needs_lists) {
          const id = record.needs_list_id;
          if (typeof id === 'string' && id.trim().length > 0) {
            recordsById.set(id, record);
          }
        }

        const reusableDraftsByWarehouse = new Map<number, string>();
        for (const draftId of existingDraftIds) {
          const record = recordsById.get(draftId);
          if (!record) {
            continue;
          }

          const warehouseId = record.warehouse_id;
          if (
            warehouseId &&
            !reusableDraftsByWarehouse.has(warehouseId) &&
            this.isReusableDraftRecord(
              record,
              expectedEventId,
              expectedPhase,
              expectedMethod,
              expectedWarehouseIds,
              expectedCountsByWarehouse,
              expectedRequiredQtyByWarehouse
            )
          ) {
            reusableDraftsByWarehouse.set(warehouseId, draftId);
          }
        }
        return reusableDraftsByWarehouse;
      }),
      catchError(() => of(new Map<number, string>()))
    );
  }

  private isReusableDraftRecord(
    record: NeedsListResponse,
    expectedEventId: number,
    expectedPhase: string,
    expectedMethod: HorizonType,
    expectedWarehouseIds: Set<number>,
    expectedCountsByWarehouse: Map<number, number>,
    expectedRequiredQtyByWarehouse: Map<number, Map<number, number>>
  ): boolean {
    if (record.status !== 'DRAFT') {
      return false;
    }

    if (record.event_id !== expectedEventId) {
      return false;
    }

    const recordPhase = String(record.phase || '').toUpperCase();
    if (recordPhase !== expectedPhase) {
      return false;
    }

    const warehouseId = record.warehouse_id;
    if (!warehouseId || !expectedWarehouseIds.has(warehouseId)) {
      return false;
    }

    if ((record.selected_method || '') !== expectedMethod) {
      return false;
    }

    const expectedCount = expectedCountsByWarehouse.get(warehouseId) || 0;
    const expectedRequiredQtyByItem = expectedRequiredQtyByWarehouse.get(warehouseId) || new Map<number, number>();
    const recordItems = record.items || [];
    if (recordItems.length !== expectedCount || expectedRequiredQtyByItem.size !== expectedCount) {
      return false;
    }

    for (const item of recordItems) {
      const expectedQty = expectedRequiredQtyByItem.get(item.item_id);
      if (expectedQty === undefined) {
        return false;
      }

      const currentQty = item.required_qty ?? item.gap_qty;
      if (!this.quantitiesEqual(currentQty, expectedQty)) {
        return false;
      }
    }

    return true;
  }

  private orderDraftIdsByWarehouse(
    warehouseIds: number[],
    draftIdsByWarehouse: Map<number, string>
  ): string[] {
    return warehouseIds
      .map((warehouseId) => draftIdsByWarehouse.get(warehouseId))
      .filter((draftId): draftId is string => typeof draftId === 'string' && draftId.trim().length > 0);
  }

  private getSubmissionWarehouseIds(): number[] {
    const selectedWarehouseIds = this.selectedItems
      .map((item) => item.warehouse_id)
      .filter((id): id is number => typeof id === 'number' && Number.isInteger(id) && id > 0);
    if (selectedWarehouseIds.length > 0) {
      return [...new Set(selectedWarehouseIds)];
    }

    const stateWarehouses = this.wizardService.getState().warehouse_ids || [];
    const stateWarehouseIds = stateWarehouses.filter(
      (id): id is number => Number.isInteger(id) && id > 0
    );
    return [...new Set(stateWarehouseIds)];
  }

  private getSelectedItemKeysForWarehouse(warehouseId: number): string[] {
    return this.selectedItems
      .filter((item) => (item.warehouse_id || 0) === warehouseId)
      .map((item) => `${item.item_id}_${item.warehouse_id || 0}`);
  }

  private getSelectedCountsByWarehouse(): Map<number, number> {
    const counts = new Map<number, number>();
    for (const item of this.selectedItems) {
      const warehouseId = item.warehouse_id || 0;
      counts.set(warehouseId, (counts.get(warehouseId) || 0) + 1);
    }
    return counts;
  }

  private getExpectedRequiredQtyByWarehouse(): Map<number, Map<number, number>> {
    const expectedByWarehouse = new Map<number, Map<number, number>>();

    for (const item of this.selectedItems) {
      const warehouseId = item.warehouse_id || 0;
      const itemId = item.item_id;
      const adjustedQty = this.getAdjustedQty(item);

      if (!expectedByWarehouse.has(warehouseId)) {
        expectedByWarehouse.set(warehouseId, new Map<number, number>());
      }

      expectedByWarehouse.get(warehouseId)!.set(itemId, adjustedQty);
    }

    return expectedByWarehouse;
  }

  private getLineOverridesForWarehouse(warehouseId: number): NeedsListLineOverridePayload[] {
    const state = this.wizardService.getState();
    const selectedItemKeys = new Set(this.getSelectedItemKeysForWarehouse(warehouseId));
    const adjustments = state.adjustments || {};

    const overrides: NeedsListLineOverridePayload[] = [];
    for (const [adjustmentKey, adjustment] of Object.entries(adjustments)) {
      if (!selectedItemKeys.has(adjustmentKey)) {
        continue;
      }

      if ((adjustment.warehouse_id || 0) !== warehouseId) {
        continue;
      }

      const reasonLabel = ADJUSTMENT_REASON_LABELS[adjustment.reason] || 'Manual adjustment';
      const notes = adjustment.notes?.trim();
      const reason = notes ? `${reasonLabel}: ${notes}` : reasonLabel;

      overrides.push({
        item_id: adjustment.item_id,
        overridden_qty: adjustment.adjusted_qty,
        reason
      });
    }

    return overrides;
  }

  private persistLineOverridesForDrafts(
    warehouseIds: number[],
    draftIdsByWarehouse: Map<number, string>
  ): Observable<void> {
    return from(warehouseIds).pipe(
      concatMap((warehouseId) => {
        const draftId = draftIdsByWarehouse.get(warehouseId);
        if (!draftId) {
          return throwError(() => new Error(`Missing draft ID for warehouse ${warehouseId}.`));
        }

        const overrides = this.getLineOverridesForWarehouse(warehouseId);
        if (overrides.length === 0) {
          return of(void 0);
        }

        return this.replenishmentService.editNeedsListLines(draftId, overrides).pipe(
          map(() => void 0)
        );
      }),
      toArray(),
      map(() => void 0)
    );
  }

  private quantitiesEqual(valueA: unknown, valueB: unknown): boolean {
    const qtyA = Number(valueA);
    const qtyB = Number(valueB);
    if (!Number.isFinite(qtyA) || !Number.isFinite(qtyB)) {
      return false;
    }

    return Math.abs(qtyA - qtyB) < 0.0001;
  }

  private extractErrorMessage(error: unknown, fallbackMessage: string): string {
    const maybeHttpError = error as { error?: { errors?: Record<string, unknown> } };
    const errorMap = maybeHttpError?.error?.errors;
    if (errorMap && typeof errorMap === 'object') {
      const firstValue = Object.values(errorMap)[0];
      if (Array.isArray(firstValue) && firstValue.length > 0) {
        return String(firstValue[0]);
      }
      if (typeof firstValue === 'string' && firstValue.trim().length > 0) {
        return firstValue;
      }
    }

    if (error instanceof Error && error.message) {
      return error.message;
    }

    return fallbackMessage;
  }

  private performSubmitForApproval(): void {
    this.submitting = true;

    this.ensureDraftIds().pipe(
      takeUntilDestroyed(this.destroyRef),
      switchMap((draftIds) => {
        if (draftIds.length === 0) {
          return throwError(() => new Error('No draft was available for submission.'));
        }

        return forkJoin(
          draftIds.map((needsListId) => this.replenishmentService.submitNeedsListForApproval(needsListId))
        ).pipe(map(() => draftIds));
      }),
      finalize(() => {
        this.submitting = false;
      })
    ).subscribe({
      next: () => {
        const approver = this.getApprovalInfo();
        this.notificationService.showSuccess(`Needs list with ${this.totalItems} items submitted for approval.`);
        this.complete.emit({
          action: 'submitted_for_approval',
          totalItems: this.totalItems,
          completedAt: new Date().toISOString(),
          approver
        });
      },
      error: (error: unknown) => {
        const message = this.extractErrorMessage(error, 'Failed to submit needs list for approval.');
        this.errors = [message];
        this.notificationService.showError(message);
      }
    });
  }

  submitForApproval(): void {
    this.errors = [];

    if (this.totalItems === 0) {
      this.errors = ['No items to submit. Please go back to Step 2.'];
      return;
    }

    const confirmData: ConfirmDialogData = {
      title: 'Submit Needs List for Approval?',
      message:
        'Are you sure you want to submit this needs list for approval? You can still track it in the wizard confirmation screen.',
      confirmLabel: 'Submit',
      cancelLabel: 'Cancel'
    };

    this.dialog.open(DmisConfirmDialogComponent, {
      width: '460px',
      autoFocus: false,
      data: confirmData
    }).afterClosed().pipe(
      takeUntilDestroyed(this.destroyRef)
    ).subscribe((confirmed: boolean) => {
      if (!confirmed) {
        return;
      }

      this.performSubmitForApproval();
    });
  }

  goBack(): void {
    this.back.emit();
  }

  private normalizeSelectedMethod(method: string | undefined): HorizonType | null {
    if (method === 'A' || method === 'B' || method === 'C') {
      return method;
    }
    return null;
  }

  get hasAdjustments(): boolean {
    const state = this.wizardService.getState();
    return Object.keys(state.adjustments).length > 0;
  }

  get adjustmentCount(): number {
    const state = this.wizardService.getState();
    return Object.keys(state.adjustments).length;
  }
}
