import { Component, OnInit, Output, EventEmitter, DestroyRef, inject } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators, FormsModule } from '@angular/forms';
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
import { MatCheckboxModule } from '@angular/material/checkbox';

import { WizardStateService } from '../../services/wizard-state.service';
import { DmisEmptyStateComponent } from '../../../shared/dmis-empty-state/dmis-empty-state.component';
import { NeedsListItem } from '../../../models/needs-list.model';
import { ItemAdjustment, ADJUSTMENT_REASON_LABELS, AdjustmentReason } from '../../models/wizard-state.model';
import { distinctUntilChanged, map } from 'rxjs/operators';

// Extended interface to track selection and editing state
interface PreviewItem extends NeedsListItem {
  included: boolean;
  tempAdjustedQty?: number;
  tempReason?: AdjustmentReason;
}

@Component({
  selector: 'app-preview-step',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    FormsModule,
    MatTableModule,
    MatButtonModule,
    MatIconModule,
    MatCardModule,
    MatChipsModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatTooltipModule,
    MatProgressBarModule,
    MatCheckboxModule,
    DmisEmptyStateComponent
  ],
  templateUrl: './preview-step.component.html',
  styleUrl: './preview-step.component.scss'
})
export class PreviewStepComponent implements OnInit {
  @Output() back = new EventEmitter<void>();
  @Output() next = new EventEmitter<void>();

  items: PreviewItem[] = [];
  loading = false;
  errors: string[] = [];
  private destroyRef = inject(DestroyRef);

  displayedColumns = [
    'select',
    'severity',
    'item',
    'warehouse',
    'calculatedGap',
    'adjustedQty',
    'reason',
    'source',
    'leadTime',
    'cost'
  ];

  adjustmentReasonOptions = Object.entries(ADJUSTMENT_REASON_LABELS).map(([key, label]) => ({ key, label }));

  constructor(
    private fb: FormBuilder,
    private wizardService: WizardStateService
  ) {}

  ngOnInit(): void {
    this.wizardService.getState$().pipe(
      map(state => state.previewResponse?.items || []),
      distinctUntilChanged((prev, curr) => this.arePreviewItemsEqual(prev, curr)),
      takeUntilDestroyed(this.destroyRef)
    ).subscribe(items => {
      // Convert to PreviewItem and auto-select items with gap > 0
      this.items = items.map(item => ({
        ...item,
        included: item.gap_qty > 0,
        tempAdjustedQty: this.getAdjustedQty(item),
        tempReason: this.wizardService.getAdjustment(item.item_id, item.warehouse_id || 0)?.reason
      }));
    });
  }

  private arePreviewItemsEqual(prev: NeedsListItem[], curr: NeedsListItem[]): boolean {
    if (prev === curr) return true;
    if (prev.length !== curr.length) return false;

    for (let i = 0; i < prev.length; i += 1) {
      const a = prev[i];
      const b = curr[i];
      if (!b) return false;

      if (a.item_id !== b.item_id) return false;
      if ((a.warehouse_id ?? 0) !== (b.warehouse_id ?? 0)) return false;
      if (a.gap_qty !== b.gap_qty) return false;
      if (a.required_qty !== b.required_qty) return false;
      if (a.inbound_strict_qty !== b.inbound_strict_qty) return false;
      if (a.severity !== b.severity) return false;

      if (!this.areHorizonEqual(a.horizon, b.horizon)) return false;

      const aProc = a.procurement;
      const bProc = b.procurement;
      if ((aProc?.est_total_cost ?? null) !== (bProc?.est_total_cost ?? null)) return false;
      if ((aProc?.est_unit_cost ?? null) !== (bProc?.est_unit_cost ?? null)) return false;
    }

    return true;
  }

  private areHorizonEqual(a?: NeedsListItem['horizon'], b?: NeedsListItem['horizon']): boolean {
    if (a === b) return true;
    if (!a || !b) return false;

    return (
      (a.A?.recommended_qty ?? 0) === (b.A?.recommended_qty ?? 0) &&
      (a.B?.recommended_qty ?? 0) === (b.B?.recommended_qty ?? 0) &&
      (a.C?.recommended_qty ?? 0) === (b.C?.recommended_qty ?? 0)
    );
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
    const cost = item.procurement?.est_total_cost;
    if (cost !== null && cost !== undefined) {
      return `$${cost.toFixed(2)}`;
    }
    return 'N/A';
  }

  getTotalCost(): number {
    return this.items
      .filter(item => item.included)
      .reduce((sum, item) => {
        const cost = item.procurement?.est_total_cost || 0;
        return sum + cost;
      }, 0);
  }

  // Selection management
  get selectedCount(): number {
    return this.items.filter(item => item.included).length;
  }

  get allSelected(): boolean {
    return this.items.length > 0 && this.items.every(item => item.included);
  }

  get someSelected(): boolean {
    return this.items.some(item => item.included) && !this.allSelected;
  }

  toggleAllSelection(): void {
    const newValue = !this.allSelected;
    this.items.forEach(item => {
      item.included = newValue;
    });
  }

  selectAll(): void {
    this.items.forEach(item => {
      item.included = true;
    });
  }

  selectNone(): void {
    this.items.forEach(item => {
      item.included = false;
    });
  }

  selectItemsWithGap(): void {
    this.items.forEach(item => {
      item.included = item.gap_qty > 0;
    });
  }

  // Check if item is uncovered (gap > 0 after horizon allocation)
  isUncovered(item: PreviewItem): boolean {
    const horizonTotal =
      (item.horizon?.A?.recommended_qty || 0) +
      (item.horizon?.B?.recommended_qty || 0) +
      (item.horizon?.C?.recommended_qty || 0);

    return item.gap_qty > horizonTotal;
  }

  // Computed property for template - checks if any items are uncovered
  get hasUncoveredItems(): boolean {
    return this.items.some(item => this.isUncovered(item));
  }

  // Computed property for template - count of uncovered items
  get uncoveredItemCount(): number {
    return this.items.filter(item => this.isUncovered(item)).length;
  }

  getRowClass(item: PreviewItem): string {
    const classes: string[] = [];

    // Add selected class for visual feedback
    if (item.included) {
      classes.push('selected-item');
    }

    if (this.isUncovered(item)) {
      classes.push('uncovered-item');
    }

    if (item.gap_qty === 0) {
      classes.push('zero-gap-item');
    }

    return classes.join(' ');
  }

  getItemKey(item: PreviewItem): string {
    return `${item.item_id}_${item.warehouse_id || 0}`;
  }

  hasAdjustment(item: PreviewItem): boolean {
    return !!this.wizardService.getAdjustment(item.item_id, item.warehouse_id || 0);
  }

  getAdjustedQty(item: NeedsListItem): number {
    const adjustment = this.wizardService.getAdjustment(item.item_id, item.warehouse_id || 0);
    return adjustment ? adjustment.adjusted_qty : item.gap_qty;
  }

  // Inline editing methods
  onQuantityChange(item: PreviewItem): void {
    if (item.tempAdjustedQty === undefined || !Number.isFinite(item.tempAdjustedQty) || item.tempAdjustedQty < 0) {
      return;
    }

    // If quantity changed from original and reason is provided, save adjustment
    if (item.tempAdjustedQty !== item.gap_qty && item.tempReason) {
      const adjustment: ItemAdjustment = {
        item_id: item.item_id,
        warehouse_id: item.warehouse_id || 0,
        original_qty: item.gap_qty,
        adjusted_qty: item.tempAdjustedQty,
        reason: item.tempReason,
        notes: ''
      };
      this.wizardService.setAdjustment(item.item_id, item.warehouse_id || 0, adjustment);
    } else if (item.tempAdjustedQty === item.gap_qty) {
      // If quantity reverted to original, remove adjustment
      this.wizardService.removeAdjustment(item.item_id, item.warehouse_id || 0);
    }
  }

  onReasonChange(item: PreviewItem): void {
    // Save adjustment when reason changes (if quantity is also different)
    if (item.tempAdjustedQty !== undefined && item.tempAdjustedQty !== item.gap_qty && item.tempReason) {
      this.onQuantityChange(item);
    }
  }

  isQuantityAdjusted(item: PreviewItem): boolean {
    return item.tempAdjustedQty !== undefined && item.tempAdjustedQty !== item.gap_qty;
  }

  showReasonField(item: PreviewItem): boolean {
    return this.isQuantityAdjusted(item);
  }

  proceedToNext(): void {
    // Validate that at least one item is selected
    if (this.selectedCount === 0) {
      this.errors = ['Please select at least one item before continuing. Use the checkboxes to select items you want to include in the needs list.'];
      this.scrollToErrors();
      return;
    }

    const pendingReasonItems = this.items.filter(item =>
      item.included &&
      this.isQuantityAdjusted(item) &&
      !item.tempReason
    );

    if (pendingReasonItems.length > 0) {
      this.errors = [
        `Please select a reason for all adjusted quantities before continuing (${pendingReasonItems.length} pending).`
      ];
      this.scrollToErrors();
      return;
    }

    // Clear any errors
    this.errors = [];

    // Save selected item keys to wizard state
    const selectedItemKeys = this.items
      .filter(item => item.included)
      .map(item => this.getItemKey(item));

    this.wizardService.updateState({ selectedItemKeys });

    // Move to step 3
    this.next.emit();
  }

  goBack(): void {
    this.back.emit();
  }

  private scrollToErrors(): void {
    // Give Angular a tick to render the error container, then scroll to it
    setTimeout(() => {
      const errorEl = document.querySelector('.errors-container');
      if (errorEl) {
        errorEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
      } else {
        window.scrollTo({ top: 0, behavior: 'smooth' });
      }
    }, 50);
  }
}
