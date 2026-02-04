import { Component, OnInit, Output, EventEmitter, DestroyRef, inject } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatTableModule } from '@angular/material/table';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatCardModule } from '@angular/material/card';
import { MatChipsModule } from '@angular/material/chips';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatProgressBarModule } from '@angular/material/progress-bar';

import { WizardStateService } from '../../services/wizard-state.service';
import { NeedsListItem } from '../../../models/needs-list.model';
import { ItemAdjustment, ADJUSTMENT_REASON_LABELS, AdjustmentReason } from '../../models/wizard-state.model';
import { distinctUntilChanged, map } from 'rxjs/operators';

@Component({
  selector: 'app-preview-step',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    MatTableModule,
    MatButtonModule,
    MatIconModule,
    MatCardModule,
    MatChipsModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatTooltipModule,
    MatProgressBarModule
  ],
  templateUrl: './preview-step.component.html',
  styleUrl: './preview-step.component.scss'
})
export class PreviewStepComponent implements OnInit {
  @Output() back = new EventEmitter<void>();
  @Output() next = new EventEmitter<void>();

  items: NeedsListItem[] = [];
  loading = false;
  errors: string[] = [];
  private destroyRef = inject(DestroyRef);

  displayedColumns = [
    'severity',
    'item',
    'warehouse',
    'gap',
    'source',
    'leadTime',
    'cost',
    'actions'
  ];

  adjustmentReasonOptions = Object.entries(ADJUSTMENT_REASON_LABELS);
  editingItemKey: string | null = null;
  adjustmentForm: FormGroup;

  constructor(
    private fb: FormBuilder,
    private wizardService: WizardStateService
  ) {
    this.adjustmentForm = this.fb.group({
      adjusted_qty: [null, [Validators.required, Validators.min(0)]],
      reason: ['', Validators.required],
      notes: ['']
    });
  }

  ngOnInit(): void {
    this.wizardService.getState$().pipe(
      map(state => state.previewResponse?.items || []),
      distinctUntilChanged(),
      takeUntilDestroyed(this.destroyRef)
    ).subscribe(items => {
      this.items = items;
    });
  }

  getSeverityIcon(item: NeedsListItem): string {
    const severity = item.severity;
    switch (severity) {
      case 'CRITICAL': return 'error';
      case 'WARNING': return 'warning';
      case 'WATCH': return 'visibility';
      default: return 'check_circle';
    }
  }

  getSeverityClass(item: NeedsListItem): string {
    return `severity-${item.severity?.toLowerCase() || 'ok'}`;
  }

  getRecommendedSource(item: NeedsListItem): string {
    const horizon = item.horizon;
    if (horizon?.A?.recommended_qty && horizon.A.recommended_qty > 0) return 'A';
    if (horizon?.B?.recommended_qty && horizon.B.recommended_qty > 0) return 'B';
    if (horizon?.C?.recommended_qty && horizon.C.recommended_qty > 0) return 'C';
    return 'N/A';
  }

  getSourceIcon(source: string): string {
    switch (source) {
      case 'A': return 'local_shipping';  // Transfer
      case 'B': return 'inventory';        // Donation
      case 'C': return 'shopping_cart';    // Procurement
      default: return 'help';
    }
  }

  getSourceLabel(source: string): string {
    switch (source) {
      case 'A': return 'Transfer';
      case 'B': return 'Donation';
      case 'C': return 'Procurement';
      default: return 'N/A';
    }
  }

  getLeadTime(item: NeedsListItem): string {
    const source = this.getRecommendedSource(item);
    // Lead times from CLAUDE.md
    switch (source) {
      case 'A': return '6-8 hours';
      case 'B': return '2-7 days';
      case 'C': return '14+ days';
      default: return 'N/A';
    }
  }

  getEstimatedCost(item: NeedsListItem): string {
    if (item.procurement?.est_total_cost) {
      return `$${item.procurement.est_total_cost.toFixed(2)}`;
    }
    return 'N/A';
  }

  getTotalCost(): number {
    return this.items.reduce((sum, item) => {
      const cost = item.procurement?.est_total_cost || 0;
      return sum + cost;
    }, 0);
  }

  // Check if item is uncovered (gap > 0 after horizon allocation)
  isUncovered(item: NeedsListItem): boolean {
    const horizonTotal =
      (item.horizon?.A?.recommended_qty || 0) +
      (item.horizon?.B?.recommended_qty || 0) +
      (item.horizon?.C?.recommended_qty || 0);

    return item.gap_qty > horizonTotal;
  }

  getRowClass(item: NeedsListItem): string {
    if (this.isUncovered(item)) {
      return 'uncovered-item';
    }
    return '';
  }

  getItemKey(item: NeedsListItem): string {
    return `${item.item_id}_${item.warehouse_id}`;
  }

  hasAdjustment(item: NeedsListItem): boolean {
    return !!this.wizardService.getAdjustment(item.item_id, item.warehouse_id || 0);
  }

  getAdjustedQty(item: NeedsListItem): number {
    const adjustment = this.wizardService.getAdjustment(item.item_id, item.warehouse_id || 0);
    return adjustment ? adjustment.adjusted_qty : item.gap_qty;
  }

  startEdit(item: NeedsListItem): void {
    const key = this.getItemKey(item);
    this.editingItemKey = key;

    const existing = this.wizardService.getAdjustment(item.item_id, item.warehouse_id || 0);
    this.adjustmentForm.patchValue({
      adjusted_qty: existing?.adjusted_qty || item.gap_qty,
      reason: existing?.reason || '',
      notes: existing?.notes || ''
    });
  }

  cancelEdit(): void {
    this.editingItemKey = null;
    this.adjustmentForm.reset();
  }

  isEditing(item: NeedsListItem): boolean {
    return this.editingItemKey === this.getItemKey(item);
  }

  saveAdjustment(item: NeedsListItem): void {
    if (this.adjustmentForm.invalid) {
      this.adjustmentForm.markAllAsTouched();
      return;
    }

    const adjustment: ItemAdjustment = {
      item_id: item.item_id,
      warehouse_id: item.warehouse_id || 0,
      original_qty: item.gap_qty,
      adjusted_qty: this.adjustmentForm.value.adjusted_qty,
      reason: this.adjustmentForm.value.reason,
      notes: this.adjustmentForm.value.notes
    };

    this.wizardService.setAdjustment(item.item_id, item.warehouse_id || 0, adjustment);
    this.editingItemKey = null;
    this.adjustmentForm.reset();
  }

  removeAdjustment(item: NeedsListItem): void {
    this.wizardService.removeAdjustment(item.item_id, item.warehouse_id || 0);
  }

  proceedToNext(): void {
    // Move to step 3
    this.next.emit();
  }

  goBack(): void {
    this.back.emit();
  }
}
