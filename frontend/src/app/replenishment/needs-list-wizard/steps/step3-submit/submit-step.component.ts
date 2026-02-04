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
  warehouseBreakdown: WarehouseBreakdown[] = [];
  horizonBreakdown: HorizonBreakdown[] = [];

  totalItems = 0;
  totalUnits = 0;
  totalCost = 0;

  notesForm: FormGroup;
  loading = false;
  errors: string[] = [];

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
        adjustments: state.adjustments
      })),
    this.wizardService.getState$().pipe(
      map(state => state.previewResponse?.items || []),
      distinctUntilChanged((prev, curr) => 
        prev.length === curr.length && 
        prev.every((item, i) => item.item_id === curr[i]?.item_id)
      ),
      takeUntilDestroyed(this.destroyRef)
    ).subscribe(items => {
      this.items = items;
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
    if (!this.items.length) {
      this.totalItems = 0;
      this.totalUnits = 0;
      this.totalCost = 0;
      this.warehouseBreakdown = [];
      this.horizonBreakdown = [];
      return;
    }

    // Apply adjustments to items
    const adjustedItems = this.items.map(item => {
      const adjustment = this.wizardService.getAdjustment(item.item_id, item.warehouse_id || 0);
      return {
        ...item,
        gap_qty: adjustment ? adjustment.adjusted_qty : item.gap_qty
      };
    });

    // Calculate totals
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

      // Count items by their primary recommended source (A → B → C)
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

  private getItemCost(item: NeedsListItem): number {
    const unitCost = item.procurement?.est_unit_cost ?? 0;
    const quantity = item.gap_qty ?? 0;
    return quantity * unitCost;
  }

  getPhaseLabel(): string {
    const state = this.wizardService.getState();
    return state.phase || 'BASELINE';
  }

  getEventId(): number | undefined {
    return this.wizardService.getState().event_id;
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
