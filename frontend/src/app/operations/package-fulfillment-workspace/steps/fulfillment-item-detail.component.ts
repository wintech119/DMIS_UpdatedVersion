import { BreakpointObserver } from '@angular/cdk/layout';
import { DecimalPipe } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  afterEveryRender,
  computed,
  effect,
  inject,
  input,
  output,
  viewChildren,
} from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import {
  MAT_BOTTOM_SHEET_DATA,
  MatBottomSheet,
  MatBottomSheetModule,
  MatBottomSheetRef,
} from '@angular/material/bottom-sheet';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatMenuModule } from '@angular/material/menu';
import { MatSelectModule } from '@angular/material/select';
import { MatTooltipModule } from '@angular/material/tooltip';

import {
  AllocationItemGroup,
  AlternateWarehouseOption,
  WarehouseAllocationCard,
} from '../../models/operations.model';
import { OperationsWorkspaceStateService } from '../../services/operations-workspace-state.service';
import { OpsStockAvailabilityStateComponent } from '../../shared/ops-stock-availability-state.component';
import { WarehouseAllocationCardComponent } from './warehouse-allocation-card.component';

interface WarehouseSelectOption {
  label: string;
  value: string;
}

interface AddWarehouseSheetData {
  alternates: AlternateWarehouseOption[];
  issuanceOrder: string;
  loadedCount: number;
}

/**
 * Mobile bottom-sheet for the "Add next warehouse" affordance. Co-located with
 * FulfillmentItemDetailComponent by design (no net-new top-level component
 * file). Emits the selected warehouse_id back via MatBottomSheetRef.
 */
@Component({
  selector: 'app-add-warehouse-bottom-sheet',
  standalone: true,
  imports: [DecimalPipe, MatButtonModule, MatIconModule, MatBottomSheetModule],
  template: `
    <div class="bs" role="dialog" aria-labelledby="add-wh-title">
      <h3 id="add-wh-title" class="bs__title">Add another warehouse</h3>
      <ul class="bs__list" role="list">
        @for (alt of data.alternates; track alt.warehouse_id; let idx = $index) {
          <li>
            <button
              mat-stroked-button
              type="button"
              class="bs__row"
              (click)="onSelect(alt.warehouse_id)">
              <span class="bs__eyebrow">
                +{{ data.loadedCount + idx }} · {{ data.issuanceOrder }}
              </span>
              <span class="bs__name">{{ alt.warehouse_name }}</span>
              <span class="bs__meta">
                {{ alt.available_qty | number:'1.0-4' }} avail · suggests
                {{ alt.suggested_qty | number:'1.0-4' }}
              </span>
            </button>
          </li>
        }
      </ul>
    </div>
  `,
  styles: [
    `
      .bs {
        display: flex;
        flex-direction: column;
        gap: 12px;
        padding: 16px;
      }
      .bs__title {
        margin: 0;
        font-size: 1rem;
        font-weight: var(--weight-semibold, 600);
        color: var(--color-text-primary, #37352f);
      }
      .bs__list {
        list-style: none;
        margin: 0;
        padding: 0;
        display: flex;
        flex-direction: column;
        gap: 8px;
      }
      .bs__row {
        display: flex;
        flex-direction: column;
        align-items: flex-start;
        gap: 2px;
        width: 100%;
        padding: 10px 12px;
        min-height: 48px;
        text-align: left;
      }
      .bs__eyebrow {
        font-size: 0.62rem;
        letter-spacing: 0.14em;
        text-transform: uppercase;
        color: var(--color-text-secondary, #787774);
      }
      .bs__name {
        font-size: 0.92rem;
        font-weight: var(--weight-semibold, 600);
        color: var(--color-text-primary, #37352f);
      }
      .bs__meta {
        font-size: 0.78rem;
        color: var(--color-text-secondary, #787774);
      }
    `,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AddWarehouseBottomSheetComponent {
  private readonly sheetRef = inject(MatBottomSheetRef<AddWarehouseBottomSheetComponent, number>);
  readonly data = inject<AddWarehouseSheetData>(MAT_BOTTOM_SHEET_DATA);

  onSelect(warehouseId: number): void {
    this.sheetRef.dismiss(warehouseId);
  }
}

@Component({
  selector: 'app-fulfillment-item-detail',
  standalone: true,
  imports: [
    DecimalPipe,
    MatButtonModule,
    MatBottomSheetModule,
    MatFormFieldModule,
    MatIconModule,
    MatMenuModule,
    MatSelectModule,
    MatTooltipModule,
    ReactiveFormsModule,
    OpsStockAvailabilityStateComponent,
    WarehouseAllocationCardComponent,
  ],
  template: `
    <div class="detail">
      <!-- Item header row: name + badges + actions grouped together -->
      <div class="detail__header">
        <div class="detail__title">
          <h3 class="detail__name">{{ item().item_name || ('Item ' + item().item_id) }}</h3>
          <p class="detail__code">{{ item().item_code || ('Item ID ' + item().item_id) }}</p>
        </div>
        <div class="detail__actions">
          <span class="detail__badge detail__badge--method" [attr.data-rule]="item().issuance_order">
            <mat-icon aria-hidden="true">schedule</mat-icon>
            {{ item().issuance_order }}
          </span>
          <button
            type="button"
            class="detail__help-btn"
            [matTooltip]="methodTooltip()"
            matTooltipPosition="below"
            [attr.aria-label]="'About ' + item().issuance_order + ' allocation rule'">
            <mat-icon aria-hidden="true">help_outline</mat-icon>
          </button>
          @if (store().isRuleBypassedForItem(item().item_id)) {
            <span class="detail__badge detail__badge--warning">Bypass</span>
          }
          @if (isOverridden()) {
            <span class="detail__badge detail__badge--override">Overridden</span>
          }
          <div class="detail__text-actions">
            <button
              class="detail__text-btn"
              type="button"
              [disabled]="readOnly()"
              (click)="store().clearItemSelection(item().item_id)">
              Clear selection
            </button>
            <span class="detail__divider" aria-hidden="true"></span>
            <button class="detail__text-btn" type="button" (click)="back.emit()">Manual override</button>
          </div>
        </div>
      </div>

      <!-- Preferred source (per-item override) — compact row above the stack -->
      @if (warehouseSelectOptions().length > 1) {
        <div class="detail__preferred">
          <mat-form-field appearance="outline" class="detail__warehouse-select">
            <mat-label>Preferred source</mat-label>
            <mat-select
              [formControl]="preferredWarehouseControl"
              panelClass="detail-warehouse-panel"
              [attr.aria-label]="'Preferred source warehouse for ' + (item().item_name || 'this item')">
              @for (wh of warehouseSelectOptions(); track wh.value) {
                <mat-option [value]="wh.value">
                  {{ wh.label }}
                </mat-option>
              }
            </mat-select>
          </mat-form-field>
        </div>
      }

      <!-- 5 Metric cards — the operator's story -->
      <div class="detail__metrics">
        <!-- 1. Requested -->
        <div class="metric-card">
          <span class="metric-card__label">Requested</span>
          <span class="metric-card__value">{{ item().request_qty | number:'1.0-4' }}</span>
        </div>

        <!-- 2. Available Here -->
        <div class="metric-card"
          [class.metric-card--warning-tint]="totalAvailableHere() > 0 && totalAvailableHere() < remainingQty()"
          [class.metric-card--critical-tint]="totalAvailableHere() === 0 && remainingQty() > 0">
          <span class="metric-card__label">Available</span>
          <span class="metric-card__value"
            [class.metric-card__value--accent]="totalAvailableHere() >= remainingQty()"
            [class.metric-card__value--warning]="totalAvailableHere() > 0 && totalAvailableHere() < remainingQty()"
            [class.metric-card__value--danger]="totalAvailableHere() === 0 && remainingQty() > 0">
            {{ totalAvailableHere() | number:'1.0-4' }}
          </span>
          @if (availabilityHint(); as hint) {
            <span class="metric-card__hint">{{ hint }}</span>
          }
        </div>

        <!-- 3. Reserving -->
        <div class="metric-card">
          <span class="metric-card__label">Reserving</span>
          <span class="metric-card__value metric-card__value--accent">
            {{ reservingQty() | number:'1.0-4' }}
          </span>
        </div>

        <!-- 4. Shortfall -->
        <div class="metric-card"
          [class.metric-card--critical-tint]="shortfallQty() > 0"
          [class.metric-card--success-tint]="shortfallQty() === 0 && reservingQty() > 0">
          <span class="metric-card__label">Shortfall</span>
          <span class="metric-card__value"
            [class.metric-card__value--danger]="shortfallQty() > 0"
            [class.metric-card__value--success]="shortfallQty() === 0 && reservingQty() > 0">
            {{ shortfallQty() | number:'1.0-4' }}
          </span>
          @if (shortfallHint(); as hint) {
            <span class="metric-card__hint">{{ hint }}</span>
          }
        </div>

        <!-- 5. Status -->
        <div class="metric-card metric-card--status"
          [attr.data-status]="fillStatus()"
          role="status"
          [attr.aria-label]="statusLabel() + ', ' + (fillRatio() * 100 | number:'1.0-0') + '% of need covered'">
          <span class="metric-card__label">Status</span>
          <span class="metric-card__value metric-card__value--status"
            [attr.data-status]="fillStatus()">
            {{ statusLabel() }}
          </span>
          <div class="metric-card__bar" role="progressbar"
            [attr.aria-valuenow]="fillRatio() * 100 | number:'1.0-0'"
            aria-valuemin="0" aria-valuemax="100">
            <div class="metric-card__bar-fill"
              [attr.data-status]="fillStatus()"
              [style.width.%]="fillRatio() * 100">
            </div>
          </div>
        </div>
      </div>

      <!-- Inline validation — compact notice tucked under metrics -->
      @if (store().getItemValidationMessage(item()); as msg) {
        <p class="detail__notice detail__notice--error" role="alert">
          <mat-icon aria-hidden="true">info</mat-icon>
          {{ msg }}
        </p>
      }

      <!-- Already-issued informational banner — precedes the stack. -->
      @if (item().fully_issued) {
        <p class="detail__notice detail__notice--info" role="status">
          <mat-icon aria-hidden="true">info</mat-icon>
          This item is already fully issued ({{ item().issue_qty | number:'1.0-2' }} / {{ item().request_qty | number:'1.0-2' }}).
          Cancel the previous package to free this quantity before re-allocating from another batch.
        </p>
      }

      <!-- Ranked warehouse card stack -->
      @if (itemAvailabilityIssue(); as issue) {
        <app-ops-stock-availability-state
          [kind]="issue.kind"
          [scope]="issue.scope"
          [itemName]="item().item_name || null"
          [remainingQty]="item().remaining_qty" />
      } @else {
        <section class="detail__stack" [attr.aria-label]="'Ranked warehouses for ' + (item().item_name || 'this item')">
          @for (card of rankedStackCards(); track card.warehouse_id) {
            <app-warehouse-allocation-card
              [warehouse]="card"
              [itemRequestedQty]="item().request_qty"
              [allocatedQty]="allocatedQtyFor(card)"
              [remainingQtyForItem]="remainingForCard(card)"
              [itemShortfallQty]="shortfallString()"
              [readOnly]="readOnly() || !!item().fully_issued"
              [canRemove]="card.rank > 0"
              [isOverrideRisk]="isOverrideRiskFor(card)"
              (qtyChange)="onCardQty(card, $event)"
              (removeCard)="onRemoveCard($event)" />
          }
        </section>

        <!-- Add-next warehouse affordance -->
        <div class="detail__add-row">
          @if (isNarrow()) {
            <button
              type="button"
              class="detail__add-btn"
              [disabled]="readOnly() || visibleAlternateWarehouses().length === 0 || addingWarehouse()"
              (click)="openBottomSheet()">
              <mat-icon aria-hidden="true">add</mat-icon>
              <span class="detail__add-btn-label">
                Add another warehouse
                @if (visibleAlternateWarehouses().length > 0) {
                  <span class="detail__add-btn-count"
                    >({{ visibleAlternateWarehouses().length }} available)</span
                  >
                }
              </span>
            </button>
          } @else {
            <button
              type="button"
              class="detail__add-btn"
              [matMenuTriggerFor]="addMenu"
              [disabled]="readOnly() || visibleAlternateWarehouses().length === 0 || addingWarehouse()">
              <mat-icon aria-hidden="true">add</mat-icon>
              <span class="detail__add-btn-label">
                Add another warehouse
                @if (visibleAlternateWarehouses().length > 0) {
                  <span class="detail__add-btn-count"
                    >({{ visibleAlternateWarehouses().length }} available)</span
                  >
                }
              </span>
            </button>
            <mat-menu #addMenu="matMenu" class="detail__add-menu">
              @for (alt of visibleAlternateWarehouses(); track alt.warehouse_id; let idx = $index) {
                <button mat-menu-item type="button" (click)="onAddWarehouse(alt.warehouse_id)">
                  <span class="detail__add-row-eyebrow">
                    +{{ (store().loadedWarehousesByItem()[item().item_id]?.length ?? 0) + idx }} · {{ item().issuance_order }}
                  </span>
                  <span class="detail__add-row-name">{{ alt.warehouse_name }}</span>
                  <span class="detail__add-row-meta">
                    {{ alt.available_qty | number:'1.0-4' }} avail · suggests {{ alt.suggested_qty | number:'1.0-4' }}
                  </span>
                </button>
              }
            </mat-menu>
          }
        </div>

        <!-- Aggregate summary / shortfall bar (4 states) -->
        <footer
          class="detail__summary"
          [attr.data-state]="aggregateState()"
          role="status"
          aria-live="polite">
          <mat-icon aria-hidden="true">{{ summaryIcon() }}</mat-icon>
          <span class="detail__summary-text">{{ summaryCopy() }}</span>
        </footer>
      }
    </div>
  `,
  styles: [`
    .detail {
      display: flex;
      flex-direction: column;
      gap: 14px;
    }

    /* ── Header ── */
    .detail__header {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
    }

    .detail__title {
      display: flex;
      flex-direction: column;
      gap: 4px;
      min-width: 0;
      flex: 1 1 auto;
    }

    .detail__name {
      margin: 0;
      font-size: 1.35rem;
      font-weight: var(--weight-bold, 700);
      line-height: 1.2;
      letter-spacing: -0.005em;
      color: var(--color-text-primary);
      overflow-wrap: anywhere;
    }

    .detail__code {
      margin: 0;
      font-size: 0.78rem;
      font-family: var(--font-family-mono,
        ui-monospace, "SF Mono", "Roboto Mono", "Menlo", "Consolas", monospace);
      color: var(--color-text-secondary);
      letter-spacing: 0.02em;
    }

    .detail__actions {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px;
      flex-shrink: 0;
    }

    .detail__badge {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 3px 9px;
      border-radius: var(--radius-pill, 999px);
      font-size: 0.68rem;
      font-weight: var(--weight-semibold);
      letter-spacing: 0.1em;
      text-transform: uppercase;
      background: #e8e8e8;
      color: var(--color-text-secondary);
      line-height: 1.4;
    }

    .detail__badge mat-icon {
      font-size: 14px;
      width: 14px;
      height: 14px;
      line-height: 14px;
    }

    .detail__badge--method[data-rule='FEFO'] {
      background: var(--color-bg-info, #eff6ff);
      color: var(--color-info, #1e3a8a);
    }

    .detail__badge--method[data-rule='FIFO'] {
      background: #eef0ff;
      color: var(--color-accent, #4f46e5);
    }

    .detail__badge--warning {
      background: #fde8b1;
      color: var(--color-warning-text, #6e4200);
    }

    .detail__badge--override {
      background: #e0f2fe;
      color: #0c4a6e;
    }

    .detail__help-btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 26px;
      height: 26px;
      padding: 0;
      margin-left: -2px;
      border: 0;
      border-radius: 50%;
      background: transparent;
      color: var(--color-text-secondary);
      cursor: pointer;
      transition: background-color 150ms ease, color 150ms ease;
    }

    .detail__help-btn:hover,
    .detail__help-btn:focus-visible {
      background: rgba(55, 53, 47, 0.06);
      color: var(--color-text-primary);
    }

    .detail__help-btn:focus-visible {
      outline: 2px solid var(--color-focus, #1d4ed8);
      outline-offset: 1px;
    }

    .detail__help-btn mat-icon {
      font-size: 18px;
      width: 18px;
      height: 18px;
      line-height: 18px;
    }

    @media (prefers-reduced-motion: reduce) {
      .detail__help-btn {
        transition: none;
      }
    }

    .detail__text-actions {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      margin-left: 4px;
      padding-left: 10px;
      border-left: 1px solid rgba(55, 53, 47, 0.14);
    }

    .detail__preferred {
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .detail__warehouse-select {
      width: 220px;
      font-size: 0.78rem;
      --mat-form-field-container-height: 40px;
    }

    .detail__warehouse-select ::ng-deep .mat-mdc-form-field-subscript-wrapper {
      display: none;
    }

    .detail__text-btn {
      border: 0;
      background: 0;
      padding: 0;
      font: inherit;
      font-size: 0.78rem;
      color: var(--color-info, #1e3a8a);
      cursor: pointer;
      white-space: nowrap;
    }

    .detail__text-btn:hover {
      text-decoration: underline;
    }

    .detail__text-btn:focus-visible {
      outline: 2px solid var(--color-focus, #1d4ed8);
      outline-offset: 2px;
      border-radius: 2px;
    }

    .detail__text-btn:disabled {
      opacity: 0.4;
      cursor: default;
      text-decoration: none;
    }

    .detail__divider {
      width: 1px;
      height: 14px;
      background: #d5d5d2;
    }

    /* ── Metrics ── */
    .detail__metrics {
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 8px;
    }

    .metric-card {
      padding: 10px 12px;
      border-radius: 8px;
      border: 1px solid rgba(55, 53, 47, 0.14);
      background: #ffffff;
      box-shadow: 0 1px 3px rgba(55, 53, 47, 0.06);
      transition: background-color 300ms ease;
    }

    .metric-card__label {
      display: block;
      margin-bottom: 3px;
      font-size: 0.62rem;
      letter-spacing: 0.18em;
      text-transform: uppercase;
      color: var(--color-text-secondary);
    }

    .metric-card__value {
      display: block;
      font-size: 1.05rem;
      font-weight: var(--weight-semibold);
      font-variant-numeric: tabular-nums;
      color: var(--color-text-primary);
    }

    .metric-card__hint {
      display: block;
      margin-top: 2px;
      font-size: 0.62rem;
      color: var(--color-text-secondary);
    }

    .metric-card__value--accent {
      color: var(--color-success, #0f766e);
    }

    .metric-card__value--warning {
      color: var(--color-warning, #6e4200);
    }

    .metric-card__value--success {
      color: var(--color-success, #286a36);
    }

    .metric-card__value--danger {
      color: var(--color-danger, #8c1d13);
    }

    /* ── Conditional background tints ── */
    .metric-card--warning-tint {
      background: rgba(253, 232, 177, 0.3);
    }

    .metric-card--critical-tint {
      background: rgba(253, 221, 216, 0.25);
    }

    .metric-card--success-tint {
      background: rgba(237, 247, 239, 0.5);
    }

    /* ── Status card ── */
    .metric-card__value--status[data-status='not_started'] {
      color: var(--color-text-secondary, #787774);
    }

    .metric-card__value--status[data-status='partial'] {
      color: var(--color-warning, #6e4200);
    }

    .metric-card__value--status[data-status='filled'] {
      color: var(--color-success, #286a36);
    }

    .metric-card__value--status[data-status='over_allocated'] {
      color: var(--color-danger, #8c1d13);
    }

    .metric-card__value--status[data-status='fully_issued'] {
      color: #17447f;
    }

    .metric-card--status[data-status='partial'] {
      background: rgba(253, 232, 177, 0.25);
    }

    .metric-card--status[data-status='filled'] {
      background: rgba(237, 247, 239, 0.5);
    }

    .metric-card--status[data-status='over_allocated'] {
      background: rgba(253, 221, 216, 0.25);
    }

    .metric-card--status[data-status='fully_issued'] {
      background: rgba(219, 234, 254, 0.45);
    }

    /* ── Progress bar ── */
    .metric-card__bar {
      margin-top: 6px;
      height: 3px;
      border-radius: 2px;
      background: #E3E3E0;
      overflow: hidden;
    }

    .metric-card__bar-fill {
      height: 100%;
      border-radius: 2px;
      background: #E3E3E0;
      transition: width 300ms cubic-bezier(0.4, 0, 0.2, 1),
                  background-color 300ms ease;
    }

    .metric-card__bar-fill[data-status='partial'] {
      background: var(--color-warning, #d97706);
    }

    .metric-card__bar-fill[data-status='filled'] {
      background: var(--color-success, #059669);
    }

    .metric-card__bar-fill[data-status='over_allocated'] {
      background: var(--color-danger, #dc3545);
    }

    .metric-card__bar-fill[data-status='fully_issued'] {
      background: #2563eb;
    }

    @media (prefers-reduced-motion: reduce) {
      .metric-card,
      .metric-card__bar-fill {
        transition: none;
      }
    }

    /* ── Inline notice ── */
    .detail__notice {
      display: flex;
      align-items: center;
      gap: 6px;
      margin: 0;
      padding: 6px 10px;
      border-radius: 6px;
      font-size: 0.78rem;
    }

    .detail__notice mat-icon {
      font-size: 16px;
      width: 16px;
      height: 16px;
      flex-shrink: 0;
    }

    .detail__notice--error {
      background: #fef2f2;
      color: #991b1b;
    }

    .detail__notice--warning {
      background: #fffbeb;
      color: #92400e;
    }

    .detail__notice--info {
      background: #eff6ff;
      color: #17447f;
    }

    /* ── Ranked stack ── */
    .detail__stack {
      display: flex;
      flex-direction: column;
      gap: 12px;
    }

    /* ── Add-next row ── */
    .detail__add-row {
      display: flex;
      flex-direction: column;
      align-items: stretch;
      gap: 8px;
    }

    /*
     * Full-width dashed-border add-another-warehouse affordance.
     * Intentionally NOT a mat-stroked-button — the ghost/dashed look matches the
     * frozen mockup and does not use Material's pill-sized stroked-button token.
     */
    .detail__add-btn {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      width: 100%;
      padding: 14px 16px;
      border: 1.5px dashed
        color-mix(in srgb, var(--color-text-secondary, #787774) 40%, #d6d3cb);
      border-radius: 12px;
      background: transparent;
      color: var(--color-text-secondary, #787774);
      font-size: 0.9rem;
      font-weight: var(--weight-medium, 500);
      cursor: pointer;
      transition: border-color 160ms ease, background-color 160ms ease,
        color 160ms ease;
    }

    .detail__add-btn mat-icon {
      flex-shrink: 0;
      font-size: 18px;
      width: 18px;
      height: 18px;
    }

    .detail__add-btn-label {
      display: inline-flex;
      align-items: baseline;
      gap: 6px;
    }

    .detail__add-btn-count {
      color: var(--color-text-secondary, #787774);
      font-weight: var(--weight-regular, 400);
      font-size: 0.82rem;
    }

    .detail__add-btn:hover:not([disabled]),
    .detail__add-btn:focus-visible:not([disabled]) {
      border-color: var(--color-text-primary, #37352f);
      color: var(--color-text-primary, #37352f);
      background: color-mix(
        in srgb,
        var(--color-surface-subtle, #f7f6f3) 60%,
        transparent
      );
    }

    .detail__add-btn:focus-visible {
      outline: 2px solid var(--color-focus-ring, #1565c0);
      outline-offset: 2px;
    }

    .detail__add-btn[disabled] {
      cursor: not-allowed;
      opacity: 0.55;
    }

    @media (prefers-reduced-motion: reduce) {
      .detail__add-btn {
        transition: none;
      }
    }

    .detail__add-row-eyebrow {
      display: block;
      font-size: 0.6rem;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      color: var(--color-text-secondary, #787774);
    }

    .detail__add-row-name {
      display: block;
      font-size: 0.88rem;
      font-weight: var(--weight-semibold, 600);
      color: var(--color-text-primary, #37352f);
    }

    .detail__add-row-meta {
      display: block;
      font-size: 0.72rem;
      color: var(--color-text-secondary, #787774);
    }

    /* ── Aggregate summary ── */
    .detail__summary {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 10px 12px;
      border-radius: 8px;
      font-size: 0.85rem;
      border: 1px solid transparent;
    }

    .detail__summary mat-icon {
      flex-shrink: 0;
      font-size: 18px;
      width: 18px;
      height: 18px;
    }

    .detail__summary-text {
      flex: 1 1 auto;
    }

    .detail__summary[data-state='draft'] {
      background: #f7f6f3;
      color: var(--color-text-secondary, #787774);
      border-color: #eae7dd;
    }

    .detail__summary[data-state='filled'] {
      background: color-mix(in srgb, var(--color-success, #286a36) 8%, white);
      color: var(--color-success, #286a36);
      border-color: color-mix(in srgb, var(--color-success, #286a36) 28%, #eae7dd);
    }

    .detail__summary[data-state='compliant_partial'] {
      background: color-mix(in srgb, var(--color-success, #286a36) 6%, white);
      color: var(--color-success, #286a36);
      border-color: color-mix(in srgb, var(--color-success, #286a36) 20%, #eae7dd);
    }

    .detail__summary[data-state='non_compliant'] {
      background: color-mix(in srgb, var(--color-warning, #d97706) 10%, white);
      color: var(--color-warning, #6e4200);
      border-color: color-mix(in srgb, var(--color-warning, #d97706) 32%, #eae7dd);
    }

    /* ── Responsive ── */
    @media (max-width: 1100px) {
      .detail__metrics {
        grid-template-columns: repeat(3, minmax(0, 1fr));
      }

      .metric-card--status {
        grid-column: span 2;
      }
    }

    @media (max-width: 768px) {
      .detail__header {
        flex-direction: column;
      }

      .detail__name {
        font-size: 1.2rem;
      }

      .detail__text-actions {
        margin-left: 0;
        padding-left: 0;
        border-left: none;
      }

      /* When the text-actions lose their left rule, the inner vertical
         separator between the two buttons floats without context — drop it
         so the narrow-layout reads cleanly. */
      .detail__text-actions .detail__divider {
        display: none;
      }

      .detail__metrics {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }

      .metric-card--status {
        grid-column: 1 / -1;
      }
    }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FulfillmentItemDetailComponent {
  readonly item = input.required<AllocationItemGroup>();
  readonly readOnly = input(false);
  readonly store = input.required<OperationsWorkspaceStateService>();
  readonly back = output<void>();

  private readonly breakpointObserver = inject(BreakpointObserver);
  private readonly bottomSheet = inject(MatBottomSheet);
  private readonly destroyRef = inject(DestroyRef);
  private readonly cardComponents = viewChildren(WarehouseAllocationCardComponent);
  private previousCardCount = 0;

  /** True when viewport is narrower than 520px — bottom sheet replaces menu. */
  private readonly narrowState = toSignal(
    this.breakpointObserver.observe('(max-width: 519px)'),
    { initialValue: { matches: false, breakpoints: {} } },
  );
  readonly isNarrow = computed(() => this.narrowState().matches);

  readonly itemAvailabilityIssue = computed(() =>
    this.store().getItemAvailabilityIssue(this.item()),
  );

  readonly effectiveWarehouse = computed(() =>
    this.store().effectiveWarehouseForItem(this.item().item_id),
  );
  readonly preferredWarehouseControl = new FormControl<string>('', { nonNullable: true });

  readonly isOverridden = computed(() => {
    const defaultId = this.item().source_warehouse_id != null
      ? String(this.item().source_warehouse_id)
      : '';
    const effective = this.effectiveWarehouse();
    return !!defaultId && !!effective && effective !== defaultId;
  });

  readonly warehouseSelectOptions = computed<WarehouseSelectOption[]>(() => {
    const options = new Map<string, string>();
    for (const candidate of this.item().candidates) {
      options.set(
        String(candidate.inventory_id),
        candidate.warehouse_name || `Warehouse ${candidate.inventory_id}`,
      );
    }
    for (const alternate of this.item().alternate_warehouses ?? []) {
      options.set(
        String(alternate.warehouse_id),
        alternate.warehouse_name || `Warehouse ${alternate.warehouse_id}`,
      );
    }
    const effectiveWarehouseId = this.effectiveWarehouse();
    if (effectiveWarehouseId) {
      options.set(
        effectiveWarehouseId,
        options.get(effectiveWarehouseId) ?? `Warehouse ${effectiveWarehouseId}`,
      );
    }
    return [...options.entries()].map(([value, label]) => ({ value, label }));
  });

  // ── Metric card computed signals ──

  readonly remainingQty = computed(() => Number(this.item().remaining_qty) || 0);

  readonly totalAvailableHere = computed(() =>
    this.item().candidates.reduce((sum, c) => sum + (Number(c.available_qty) || 0), 0),
  );

  readonly reservingQty = computed(() =>
    this.store().getSelectedTotalForItem(this.item().item_id),
  );

  readonly shortfallQty = computed(() =>
    this.store().getUncoveredQtyForItem(this.item().item_id),
  );

  readonly shortfallString = computed(() => String(this.shortfallQty()));

  readonly fillRatio = computed(() => {
    const remaining = this.remainingQty();
    if (remaining <= 0) return 1;
    return Math.min(this.reservingQty() / remaining, 1);
  });

  readonly fillStatus = computed<
    'not_started' | 'partial' | 'filled' | 'over_allocated' | 'fully_issued'
  >(() => {
    if (this.item().fully_issued) return 'fully_issued';
    const remaining = this.remainingQty();
    const reserving = this.reservingQty();
    if (reserving <= 0) return 'not_started';
    if (reserving > remaining + 0.0001) return 'over_allocated';
    if (reserving >= remaining - 0.0001) return 'filled';
    return 'partial';
  });

  readonly statusLabel = computed(() => {
    switch (this.fillStatus()) {
      case 'not_started': return 'Not Started';
      case 'partial': return 'Partly Filled';
      case 'filled': return 'Filled';
      case 'over_allocated': return 'Over-Allocated';
      case 'fully_issued': return 'Already Issued';
    }
  });

  /**
   * Plain-language explanation of the item's issuance rule, surfaced via a
   * Material tooltip on the help-icon button next to the method badge. Works
   * on hover and keyboard focus (MatTooltip shows on focus for a11y). Falls
   * back to a neutral sentence when the backend reports an unrecognised rule
   * so the help affordance never renders an empty tooltip.
   */
  readonly methodTooltip = computed(() => {
    // Normalise casing/whitespace so legacy payloads like ' fefo ' still
    // render the correct help copy instead of falling through to the generic
    // fallback sentence.
    const rule = String(this.item().issuance_order ?? '').trim().toUpperCase();
    if (rule === 'FEFO') {
      return 'FEFO (First Expiring, First Out): batches with the earliest expiry date are issued first to minimise spoilage.';
    }
    if (rule === 'FIFO') {
      return 'FIFO (First In, First Out): the oldest received stock is issued first to rotate inventory.';
    }
    return 'Allocation rule for this item.';
  });

  readonly availabilityHint = computed<string | null>(() => {
    const available = this.totalAvailableHere();
    const remaining = this.remainingQty();
    if (remaining <= 0 || available >= remaining) return null;
    if (available === 0) return 'No stock at selected warehouse';
    const pct = Math.round((available / remaining) * 100);
    return `Covers ${pct}% of need`;
  });

  readonly shortfallHint = computed<string | null>(() => {
    const shortfall = this.shortfallQty();
    if (shortfall <= 0) return null;
    const available = this.totalAvailableHere();
    const remaining = this.remainingQty();
    return available < remaining
      ? 'Warehouse stock insufficient'
      : 'Increase reservation to cover';
  });

  // ── Stack and add-next computed signals ──

  readonly rankedStackCards = computed<WarehouseAllocationCard[]>(() => {
    const item = this.item();
    const cards = [...(item.warehouse_cards ?? [])];
    const presentIds = new Set(cards.map((c) => c.warehouse_id));

    // Merge any transient warehouses the user added that aren't yet represented
    // in the backend's rank-ordered cards. These typically come from
    // alternate_warehouses that were added before the next preview round-trip.
    // Marked `pending: true` so the card can render a loading affordance until
    // the backend's preview POST returns authoritative batch detail.
    const loaded = this.store().loadedWarehousesByItem()[item.item_id] ?? [];
    const alternates = item.alternate_warehouses ?? [];
    let trailingRank = cards.length;
    for (const warehouseId of loaded) {
      if (presentIds.has(warehouseId)) continue;
      const alt = alternates.find((a) => a.warehouse_id === warehouseId);
      cards.push({
        warehouse_id: warehouseId,
        warehouse_name: alt?.warehouse_name ?? `Warehouse ${warehouseId}`,
        rank: trailingRank,
        issuance_order: item.issuance_order,
        total_available: alt?.available_qty ?? '0',
        suggested_qty: alt?.suggested_qty ?? '0',
        batches: [],
        pending: true,
      });
      presentIds.add(warehouseId);
      trailingRank += 1;
    }
    return cards;
  });

  readonly visibleAlternateWarehouses = computed(() => {
    const item = this.item();
    const alternates = item.alternate_warehouses ?? [];
    if (alternates.length === 0) {
      return alternates;
    }
    const loaded = new Set(this.store().loadedWarehousesByItem()[item.item_id] ?? []);
    const stackIds = new Set(this.rankedStackCards().map((c) => c.warehouse_id));
    return alternates.filter((alt) => !loaded.has(alt.warehouse_id) && !stackIds.has(alt.warehouse_id));
  });

  readonly addingWarehouse = computed(
    () => this.store().addingWarehouseByItem()[this.item().item_id] ?? false,
  );

  readonly maxRankWithQty = computed(() => {
    let maxRank = -1;
    for (const card of this.rankedStackCards()) {
      if (this.allocatedQtyFor(card) > 0 && card.rank > maxRank) {
        maxRank = card.rank;
      }
    }
    return maxRank;
  });

  // ── Aggregate summary ──

  readonly aggregateState = computed<
    'draft' | 'filled' | 'compliant_partial' | 'non_compliant'
  >(() => {
    // Delegate to the store helper (single source of truth). The per-card
    // `isOverrideRiskFor` heuristic remains a presentational hint; the
    // canonical fill-state classification lives in
    // OperationsWorkspaceStateService.getItemFillStatus, which combines the
    // backend override_required flag with the workspace's own
    // isRuleBypassedForItem signature check.
    const item = this.item();
    const base = this.store().getItemFillStatus(item.item_id);
    if (base !== 'non_compliant') {
      // Preserve the pre-commit UX safety net: a higher-rank card zeroed while
      // a lower-rank card has qty should surface as non_compliant even during
      // transitional states where the store's canonical check has not yet
      // caught up.
      const hasLocalOverrideRisk = this.rankedStackCards().some((card) =>
        this.isOverrideRiskFor(card),
      );
      if (hasLocalOverrideRisk) {
        return 'non_compliant';
      }
    }
    return base;
  });

  readonly summaryIcon = computed(() => {
    switch (this.aggregateState()) {
      case 'filled': return 'check_circle';
      case 'compliant_partial': return 'check_circle_outline';
      case 'non_compliant': return 'warning';
      default: return 'info';
    }
  });

  readonly summaryCopy = computed(() => {
    const item = this.item();
    const reserving = this.reservingQty();
    const remaining = this.remainingQty();
    const shortfall = Math.max(0, remaining - reserving);
    const primary = this.rankedStackCards()[0]?.warehouse_name ?? 'the primary warehouse';
    const warehouseCount = this.rankedStackCards().filter(
      (c) => this.allocatedQtyFor(c) > 0,
    ).length;
    switch (this.aggregateState()) {
      case 'draft':
        return `Nothing allocated yet. Start by reserving from ${primary} or add another warehouse.`;
      case 'filled':
        return `Fully covered — ${this.formatNumber(reserving)} of ${this.formatNumber(remaining)} reserved across ${warehouseCount} warehouse${warehouseCount === 1 ? '' : 's'}.`;
      case 'compliant_partial':
        return `Compliant partial — ${this.formatNumber(shortfall)} short. No more compliant stock available; proceed to review or add stock later.`;
      case 'non_compliant':
      default:
        // Use the backend flag to produce a consistent message; avoid referencing
        // item name to keep copy short.
        return `Non-compliant allocation — reason required in the next step.${item.issuance_order ? ' (reason required for issuance order)' : ''}`;
    }
  });

  constructor() {
    this.preferredWarehouseControl.valueChanges
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((value) => this.onWarehouseOverride(value));

    effect(() => {
      const effectiveWarehouse = this.effectiveWarehouse();
      if (this.preferredWarehouseControl.value !== effectiveWarehouse) {
        this.preferredWarehouseControl.setValue(effectiveWarehouse, { emitEvent: false });
      }
      if (this.readOnly()) {
        if (this.preferredWarehouseControl.enabled) {
          this.preferredWarehouseControl.disable({ emitEvent: false });
        }
      } else if (this.preferredWarehouseControl.disabled) {
        this.preferredWarehouseControl.enable({ emitEvent: false });
      }
    });

    // After each render, if the card stack grew, focus the new card's qty input
    // so keyboard users land in the right place after adding a warehouse.
    // Uses viewChildren() for scoped, DOM-agnostic access rather than a global
    // querySelectorAll (which would escape this component's DOM boundary).
    afterEveryRender(() => {
      const count = this.rankedStackCards().length;
      if (count > this.previousCardCount && this.previousCardCount > 0) {
        const cards = this.cardComponents();
        const last = cards[cards.length - 1];
        last?.focusQtyInput();
      }
      this.previousCardCount = count;
    });
  }

  // ── Interaction handlers ──

  allocatedQtyFor(card: WarehouseAllocationCard): number {
    return this.store().getItemWarehouseAllocatedQty(this.item().item_id, card.warehouse_id);
  }

  remainingForCard(card: WarehouseAllocationCard): number {
    const remaining = this.remainingQty();
    const reserving = this.reservingQty();
    return Math.max(0, remaining - reserving + this.allocatedQtyFor(card));
  }

  isOverrideRiskFor(card: WarehouseAllocationCard): boolean {
    // A card is at risk when a higher-ranked card with qty sits above it and
    // this card itself is empty — a pre-commit heuristic mirroring the
    // backend's override gate.
    if (this.allocatedQtyFor(card) > 0) {
      return false;
    }
    const maxRank = this.maxRankWithQty();
    return maxRank > -1 && card.rank < maxRank;
  }

  onCardQty(card: WarehouseAllocationCard, qty: number): void {
    this.store().setItemWarehouseQty(this.item().item_id, card.warehouse_id, qty);
  }

  onRemoveCard(warehouseId: number): void {
    this.store().removeItemWarehouse(this.item().item_id, warehouseId);
  }

  onAddWarehouse(warehouseId: number): void {
    this.store().addItemWarehouse(this.item().item_id, warehouseId);
  }

  onWarehouseOverride(warehouseId: string): void {
    this.store().updateItemWarehouse(this.item().item_id, warehouseId);
  }

  openBottomSheet(): void {
    const alternates = this.visibleAlternateWarehouses();
    if (!alternates.length) {
      return;
    }
    const loadedCount = this.store().loadedWarehousesByItem()[this.item().item_id]?.length ?? 0;
    const ref = this.bottomSheet.open(AddWarehouseBottomSheetComponent, {
      data: {
        alternates,
        issuanceOrder: this.item().issuance_order,
        loadedCount,
      } as AddWarehouseSheetData,
    });
    ref
      .afterDismissed()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((warehouseId) => {
        if (typeof warehouseId === 'number' && warehouseId > 0) {
          this.onAddWarehouse(warehouseId);
        }
      });
  }

  private formatNumber(value: number): string {
    if (!Number.isFinite(value)) return '0';
    const rounded = Math.round(value * 10_000) / 10_000;
    return Number.isInteger(rounded) ? String(rounded) : rounded.toString();
  }
}
