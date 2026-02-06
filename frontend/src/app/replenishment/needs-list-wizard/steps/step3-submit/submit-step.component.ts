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

import { WizardStateService } from '../../services/wizard-state.service';
import { NeedsListItem } from '../../../models/needs-list.model';
import { distinctUntilChanged, map } from 'rxjs/operators';

interface WarehouseBreakdown {
  warehouse_id: number;
  warehouse_name: string;
  items: number;
  units: number;
  cost: number;
}

interface HorizonBreakdown {
  horizon: 'A' | 'B' | 'C';
  label: string;
  items: number;
  units: number;
  leadTime: string;
}

@Component({
  selector: 'app-submit-step',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    MatCardModule,
    MatButtonModule,
    MatIconModule,
    MatFormFieldModule,
    MatInputModule,
    MatChipsModule,
    MatDividerModule,
    MatProgressBarModule
  ],
  templateUrl: './submit-step.component.html',
  styleUrl: './submit-step.component.scss'
})
export class SubmitStepComponent implements OnInit {
  @Output() back = new EventEmitter<void>();
  @Output() complete = new EventEmitter<void>();

  items: NeedsListItem[] = [];
  selectedItems: NeedsListItem[] = [];  // Only selected items
  warehouseBreakdown: WarehouseBreakdown[] = [];
  horizonBreakdown: HorizonBreakdown[] = [];

  totalItems = 0;
  totalUnits = 0;
  totalCost = 0;
  totalReviewed = 0;  // Total items reviewed (not just selected)

  notesForm: FormGroup;
  loading = false;
  errors: string[] = [];
  showAllItems = false;  // For items preview expansion
  showTierInfo = false;  // For approval tier explanation

  private destroyRef = inject(DestroyRef);

  constructor(
    private fb: FormBuilder,
    private wizardService: WizardStateService
  ) {
    this.notesForm = this.fb.group({
      notes: ['']
    });
  }

  ngOnInit(): void {
    // Subscribe to wizard state changes
    this.wizardService.getState$().pipe(
      map(state => ({
        items: state.previewResponse?.items || [],
        selectedItemKeys: state.selectedItemKeys || [],
        adjustments: state.adjustments
      })),
      distinctUntilChanged((prev, curr) => (
        prev.items.length === curr.items.length &&
        prev.items.every((item, i) => (
          item.item_id === curr.items[i]?.item_id &&
          item.warehouse_id === curr.items[i]?.warehouse_id &&
          item.gap_qty === curr.items[i]?.gap_qty
        )) &&
        prev.selectedItemKeys.length === curr.selectedItemKeys.length &&
        prev.adjustments === curr.adjustments
      )),
      takeUntilDestroyed(this.destroyRef)
    ).subscribe(({ items, selectedItemKeys }) => {
      this.items = items;
      this.totalReviewed = items.length;

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
      this.horizonBreakdown = [];
      return;
    }

    // Apply adjustments to selected items only
    const adjustedItems = this.selectedItems.map(item => {
      const adjustment = this.wizardService.getAdjustment(item.item_id, item.warehouse_id || 0);
      return {
        ...item,
        gap_qty: adjustment ? adjustment.adjusted_qty : item.gap_qty
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

    // Group by recommended horizon
    const byHorizon = new Map<'A' | 'B' | 'C', { items: number; units: number }>();
    byHorizon.set('A', { items: 0, units: 0 });
    byHorizon.set('B', { items: 0, units: 0 });
    byHorizon.set('C', { items: 0, units: 0 });

    adjustedItems.forEach(item => {
      const horizon = item.horizon;
      if (!horizon) return;

      // Count items by their primary recommended source (A -> B -> C)
      if (horizon.A?.recommended_qty && horizon.A.recommended_qty > 0) {
        const h = byHorizon.get('A')!;
        h.items++;
        h.units += horizon.A.recommended_qty;
      } else if (horizon.B?.recommended_qty && horizon.B.recommended_qty > 0) {
        const h = byHorizon.get('B')!;
        h.items++;
        h.units += horizon.B.recommended_qty;
      } else if (horizon.C?.recommended_qty && horizon.C.recommended_qty > 0) {
        const h = byHorizon.get('C')!;
        h.items++;
        h.units += horizon.C.recommended_qty;
      }
    });

    this.horizonBreakdown = ([
      { horizon: 'A' as const, label: 'Transfer (Horizon A)', items: byHorizon.get('A')!.items, units: byHorizon.get('A')!.units, leadTime: '6-8 hours' },
      { horizon: 'B' as const, label: 'Donation (Horizon B)', items: byHorizon.get('B')!.items, units: byHorizon.get('B')!.units, leadTime: '2-7 days' },
      { horizon: 'C' as const, label: 'Procurement (Horizon C)', items: byHorizon.get('C')!.items, units: byHorizon.get('C')!.units, leadTime: '14+ days' }
    ] as HorizonBreakdown[]).filter(h => h.items > 0); // Only show horizons with items
  }

  getApprovalInfo(): string {
    const state = this.wizardService.getState();
    const response = state.previewResponse;

    if (response?.approval_summary?.approval) {
      const approval = response.approval_summary.approval;
      return `${approval.tier} - ${approval.approver_role}`;
    }

    // Default based on phase
    const phase = state.phase || 'BASELINE';
    switch (phase) {
      case 'SURGE':
        return 'Tier 1 - Emergency Coordinator';
      case 'STABILIZED':
        return 'Tier 2 - Logistics Manager';
      case 'BASELINE':
        return 'Tier 3 - Supply Chain Director';
      default:
        return 'To be determined';
    }
  }

  getItemCost(item: NeedsListItem): number {
    const unitCost = item.procurement?.est_unit_cost ?? 0;
    const quantity = item.gap_qty ?? 0;
    return quantity * unitCost;
  }

  getHorizonItems(horizon: 'A' | 'B' | 'C'): number {
    if (!this.selectedItems.length) return 0;

    return this.selectedItems.filter(item => {
      if (!item.horizon) return false;

      if (horizon === 'A') {
        return item.horizon.A?.recommended_qty && item.horizon.A.recommended_qty > 0;
      } else if (horizon === 'B') {
        return item.horizon.B?.recommended_qty && item.horizon.B.recommended_qty > 0;
      } else if (horizon === 'C') {
        return item.horizon.C?.recommended_qty && item.horizon.C.recommended_qty > 0;
      }
      return false;
    }).length;
  }

  getHorizonUnits(horizon: 'A' | 'B' | 'C'): number {
    if (!this.selectedItems.length) return 0;

    return this.selectedItems.reduce((sum, item) => {
      if (!item.horizon) return sum;

      if (horizon === 'A' && item.horizon.A?.recommended_qty) {
        return sum + (item.horizon.A.recommended_qty || 0);
      } else if (horizon === 'B' && item.horizon.B?.recommended_qty) {
        return sum + (item.horizon.B.recommended_qty || 0);
      } else if (horizon === 'C' && item.horizon.C?.recommended_qty) {
        return sum + (item.horizon.C.recommended_qty || 0);
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

  toggleTierInfo(): void {
    this.showTierInfo = !this.showTierInfo;
  }

  getAdjustedQty(item: NeedsListItem): number {
    const adjustment = this.wizardService.getAdjustment(item.item_id, item.warehouse_id || 0);
    return adjustment ? adjustment.adjusted_qty : item.gap_qty;
  }

  getApprovalTierLevel(): number {
    const approvalInfo = this.getApprovalInfo();
    if (approvalInfo.includes('Tier 1')) return 1;
    if (approvalInfo.includes('Tier 2')) return 2;
    if (approvalInfo.includes('Tier 3')) return 3;
    if (approvalInfo.includes('Tier 4')) return 4;
    return 0;
  }

  saveDraft(): void {
    // Phase 5 MVP: Just show message
    // In future phase, this will call backend API to create draft
    this.errors = [];

    if (this.totalItems === 0) {
      this.errors = ['No items to save. Please go back to Step 2.'];
      return;
    }

    alert('Save as Draft functionality will be implemented in the next phase. For now, your progress is automatically saved.');
  }

  submitForApproval(): void {
    // Phase 5 MVP: Just show message
    // In future phase, this will call backend API to submit for approval
    this.errors = [];

    if (this.totalItems === 0) {
      this.errors = ['No items to submit. Please go back to Step 2.'];
      return;
    }

    const confirmed = confirm(
      `You are about to submit a needs list with ${this.totalItems} items (${this.totalUnits} total units) ` +
      `for approval.\n\nApprover: ${this.getApprovalInfo()}\n\nProceed?`
    );

    if (confirmed) {
      alert('Submit for Approval functionality will be implemented in the next phase. This will create a needs list and send it for approval.');
      // In future: this.complete.emit() after successful submission
    }
  }

  goBack(): void {
    this.back.emit();
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
