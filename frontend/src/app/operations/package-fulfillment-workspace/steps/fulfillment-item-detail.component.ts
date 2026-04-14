import { DatePipe, DecimalPipe } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  input,
  output,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatSelectModule } from '@angular/material/select';

import { AllocationCandidate, AllocationItemGroup } from '../../models/operations.model';
import { OperationsWorkspaceStateService } from '../../services/operations-workspace-state.service';
import { formatSourceType } from '../../models/operations-status.util';
import { OpsStockAvailabilityStateComponent } from '../../shared/ops-stock-availability-state.component';

interface WarehouseGroup {
  name: string;
  inventoryId: number;
  totalAvailable: number;
  batchCount: number;
  candidates: AllocationCandidate[];
}

interface WarehouseSelectOption {
  label: string;
  value: string;
}

const COMPLIANCE_LABELS: Record<string, string> = {
  donation_source: 'Donation source',
  transfer_source: 'Transfer source',
  fifo: 'FIFO recommended',
  fefo: 'FEFO recommended',
  allocation_order_override: 'Order override',
  insufficient_on_hand_stock: 'Insufficient compliant stock',
};

@Component({
  selector: 'app-fulfillment-item-detail',
  standalone: true,
  imports: [DatePipe, DecimalPipe, FormsModule, MatButtonModule, MatFormFieldModule, MatIconModule, MatSelectModule, OpsStockAvailabilityStateComponent],
  template: `
    <div class="detail">
      <!-- Item header row: name + badges + actions grouped together -->
      <div class="detail__header">
        <div>
          <h3 class="detail__name">{{ item().item_name || ('Item ' + item().item_id) }}</h3>
          <p class="detail__code">{{ item().item_code || ('Item ID ' + item().item_id) }}</p>
        </div>
        <div class="detail__actions">
          <span class="detail__badge detail__badge--method" [attr.data-rule]="item().issuance_order">
            {{ item().issuance_order }}
          </span>
          @if (store().isRuleBypassedForItem(item().item_id)) {
            <span class="detail__badge detail__badge--warning">Bypass</span>
          }
          @if (isOverridden()) {
            <span class="detail__badge detail__badge--override">Overridden</span>
          }
          @if (warehouseSelectOptions().length > 1) {
            <mat-form-field appearance="outline" class="detail__warehouse-select">
              <mat-label>Source</mat-label>
              <mat-select
                [ngModel]="effectiveWarehouse()"
                (ngModelChange)="onWarehouseOverride($event)"
                [disabled]="readOnly()"
                panelClass="detail-warehouse-panel"
                [attr.aria-label]="'Source warehouse for ' + (item().item_name || 'this item')">
                @for (wh of warehouseSelectOptions(); track wh.value) {
                  <mat-option [value]="wh.value">
                    {{ wh.label }}
                  </mat-option>
                }
              </mat-select>
            </mat-form-field>
          }
          <button
            class="detail__text-btn"
            type="button"
            [disabled]="readOnly()"
            (click)="store().clearItemSelection(item().item_id)">
            Clear selection
          </button>
          <span class="detail__divider"></span>
          <button class="detail__text-btn" type="button" (click)="back.emit()">Manual override</button>
        </div>
      </div>

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
          <span class="metric-card__label">Available Here</span>
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

      <!-- Already-issued informational banner — precedes warehouse picker. -->
      @if (item().fully_issued) {
        <p class="detail__notice detail__notice--info" role="status">
          <mat-icon aria-hidden="true">info</mat-icon>
          This item is already fully issued ({{ item().issue_qty | number:'1.0-2' }} / {{ item().request_qty | number:'1.0-2' }}).
          Cancel the previous package to free this quantity before re-allocating from another batch.
        </p>
      }

      <!-- Multi-warehouse continuation callout — only when backend recommends it. -->
      @if (continuationVisible()) {
        <section
          class="detail__continuation"
          role="region"
          [attr.aria-label]="'Multi-warehouse continuation for ' + (item().item_name || 'this item')">
          <header class="detail__continuation-head">
            <mat-icon aria-hidden="true">call_split</mat-icon>
            <div>
              <h4 class="detail__continuation-title">
                @if (continuationHasShortfall()) {
                  {{ continuationShortfall() | number:'1.0-4' }} units still need coverage
                } @else {
                  Other eligible warehouses available
                }
              </h4>
              <p class="detail__continuation-copy">
                @if (continuationHasShortfall()) {
                  Add another warehouse below to keep building this item's allocation. Your current
                  selections will be preserved.
                } @else {
                  Add another eligible warehouse below to allocate from multiple sources while
                  keeping the current {{ item().issuance_order }} rule order.
                }
              </p>
            </div>
            @if (continuationLoading()) {
              <span class="detail__continuation-loading" aria-live="polite">
                <mat-icon aria-hidden="true">progress_activity</mat-icon>
                Recalculating&hellip;
              </span>
            }
          </header>

          <ul class="detail__alternate-list" role="list">
            @for (alt of visibleAlternateWarehouses(); track alt.warehouse_id) {
              <li class="detail__alternate-card" role="listitem">
                <div class="detail__alternate-head">
                  <span class="detail__alternate-name">{{ alt.warehouse_name }}</span>
                  @if (!continuationHasShortfall()) {
                    <span class="detail__alternate-badge detail__alternate-badge--ok">
                      <mat-icon aria-hidden="true">check_circle</mat-icon>
                      Eligible
                    </span>
                  } @else if (alt.can_fully_cover) {
                    <span class="detail__alternate-badge detail__alternate-badge--ok">
                      <mat-icon aria-hidden="true">check_circle</mat-icon>
                      Fully covers shortfall
                    </span>
                  } @else {
                    <span class="detail__alternate-badge detail__alternate-badge--partial">
                      <mat-icon aria-hidden="true">timelapse</mat-icon>
                      Partial cover
                    </span>
                  }
                </div>
                <dl class="detail__alternate-figures">
                  <div>
                    <dt>Available</dt>
                    <dd>{{ alt.available_qty | number:'1.0-4' }}</dd>
                  </div>
                  <div>
                    <dt>Suggested</dt>
                    <dd>{{ alt.suggested_qty | number:'1.0-4' }}</dd>
                  </div>
                </dl>
                <button
                  type="button"
                  matButton="outlined"
                  color="primary"
                  class="detail__alternate-action"
                  [disabled]="readOnly() || addingWarehouse()"
                  (click)="onAddWarehouse(alt.warehouse_id)">
                  <mat-icon aria-hidden="true">add</mat-icon>
                  Add this warehouse
                </button>
              </li>
            }
          </ul>
        </section>
      }

      <!-- Available Warehouses -->
      <p class="detail__section-eyebrow">Available Warehouses</p>

      @if (itemAvailabilityIssue(); as issue) {
        <app-ops-stock-availability-state
          [kind]="issue.kind"
          [scope]="issue.scope"
          [itemName]="item().item_name || null"
          [remainingQty]="item().remaining_qty" />
      } @else {
        @for (wh of warehouseGroups(); track wh.inventoryId) {
          <div class="warehouse-card">
            <div class="warehouse-card__header">
              <mat-icon class="warehouse-card__icon" aria-hidden="true">warehouse</mat-icon>
              <div>
                <strong class="warehouse-card__name">{{ wh.name }}</strong>
                <span class="warehouse-card__meta">
                  {{ wh.totalAvailable | number:'1.0-2' }} available &middot; {{ wh.batchCount }} batch{{ wh.batchCount === 1 ? '' : 'es' }}
                </span>
              </div>
            </div>

            <div class="warehouse-card__table-wrap">
              <table class="warehouse-table">
                <thead>
                  <tr>
                    <th>Batch / Lot</th>
                    <th>Source</th>
                    <th>Batch Date</th>
                    <th>Expiry</th>
                    <th class="col-num">Available</th>
                    <th class="col-num">Reserved</th>
                    <th>Qty to reserve</th>
                  </tr>
                </thead>
                <tbody>
                  @for (c of wh.candidates; track c.batch_id + '-' + c.source_type + '-' + (c.source_record_id ?? '')) {
                    <tr [class.row--selected]="store().getSelectedQtyForCandidate(item().item_id, c) > 0">
                      <td>
                        <strong>{{ c.batch_no || ('Batch ' + c.batch_id) }}</strong>
                        @if (c.compliance_markers?.length) {
                          <div class="marker-list">
                            @for (m of c.compliance_markers; track m) {
                              <span class="marker-chip">{{ formatMarker(m) }}</span>
                            }
                          </div>
                        }
                      </td>
                      <td>{{ formatSource(c.source_type) }}</td>
                      <td>{{ c.batch_date ? (c.batch_date | date:'MMM d, y') : 'N/A' }}</td>
                      <td>{{ c.expiry_date ? (c.expiry_date | date:'MMM d, y') : 'N/A' }}</td>
                      <td class="col-num">{{ c.available_qty | number:'1.0-4' }}</td>
                      <td class="col-num">{{ c.reserved_qty | number:'1.0-4' }}</td>
                      <td>
                        <input
                          class="qty-input"
                          type="number"
                          min="0"
                          step="any"
                          [disabled]="readOnly() || !!item().fully_issued"
                          [ngModel]="store().getSelectedQtyForCandidate(item().item_id, c)"
                          (ngModelChange)="onQtyChange(c, $event)"
                          [attr.aria-label]="'Quantity to reserve for batch ' + (c.batch_no || c.batch_id)"
                        />
                      </td>
                    </tr>
                  }
                </tbody>
              </table>
            </div>
          </div>
        }

        <!-- Mobile cards -->
        <div class="mobile-cards">
          @for (c of item().candidates; track c.inventory_id + '-' + c.batch_id + '-' + c.source_type + '-' + (c.source_record_id ?? '')) {
            <div class="mobile-card">
              <div class="mobile-card__header">
                <strong>{{ c.batch_no || ('Batch ' + c.batch_id) }}</strong>
                <span class="detail__badge">{{ formatSource(c.source_type) }}</span>
              </div>
              <div class="mobile-card__meta">
                <span>{{ c.warehouse_name || ('Inventory ' + c.inventory_id) }}</span>
              </div>
              <div class="mobile-card__fields">
                <div class="mobile-card__field">
                  <span>Available</span>
                  <strong>{{ c.available_qty | number:'1.0-4' }}</strong>
                </div>
                <div class="mobile-card__field">
                  <span>Reserved</span>
                  <strong>{{ c.reserved_qty | number:'1.0-4' }}</strong>
                </div>
              </div>
              <label class="mobile-card__input">
                <span>Qty To Reserve</span>
                <input
                  class="qty-input"
                  type="number"
                  min="0"
                  step="any"
                  [disabled]="readOnly() || !!item().fully_issued"
                  [ngModel]="store().getSelectedQtyForCandidate(item().item_id, c)"
                  (ngModelChange)="onQtyChange(c, $event)"
                />
              </label>
            </div>
          }
        </div>
      }

      @if (store().isRuleBypassedForItem(item().item_id)) {
        <p class="detail__notice detail__notice--warning" role="status">
          <mat-icon aria-hidden="true">policy</mat-icon>
          This selection no longer matches the system's {{ item().issuance_order }} recommendation.
          Capture an override reason in the next step.
        </p>
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
    }

    .detail__name {
      margin: 0;
      font-size: 1.1rem;
      font-weight: var(--weight-semibold);
      color: var(--color-text-primary);
    }

    .detail__code {
      margin: 2px 0 0;
      font-size: 0.78rem;
      color: var(--color-text-secondary);
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
      padding: 2px 8px;
      border-radius: var(--radius-pill, 999px);
      font-size: 0.65rem;
      font-weight: var(--weight-semibold);
      letter-spacing: 0.1em;
      text-transform: uppercase;
      background: #e8e8e8;
      color: var(--color-text-secondary);
    }

    .detail__badge--method[data-rule='FEFO'] {
      background: var(--color-bg-info, #eff6ff);
      color: var(--color-info, #1e3a8a);
    }

    .detail__badge--method[data-rule='FIFO'] {
      background: color-mix(in srgb, var(--color-accent, #6366f1) 12%, white);
      color: var(--color-accent, #6366f1);
    }

    .detail__badge--warning {
      background: #fde8b1;
      color: #6e4200;
    }

    .detail__badge--override {
      background: #e0f2fe;
      color: #0c4a6e;
    }

    .detail__warehouse-select {
      width: 140px;
      font-size: 0.68rem;
      --mat-form-field-container-height: 32px;
      --mat-form-field-container-vertical-padding: 4px;
      --mat-select-trigger-text-size: 0.68rem;
    }

    .detail__warehouse-select ::ng-deep .mat-mdc-form-field-subscript-wrapper {
      display: none;
    }

    .detail__warehouse-select ::ng-deep .mat-mdc-select-value-text {
      font-size: 0.68rem;
    }

    .detail__warehouse-select ::ng-deep .mat-mdc-floating-label {
      font-size: 0.68rem;
    }

    .detail__warehouse-select ::ng-deep .mat-mdc-form-field-infix {
      padding-top: 6px;
      padding-bottom: 4px;
      min-height: 32px;
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

    /* ── Metrics — white cards that pop off the warm page ── */
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
      color: #0f766e;
    }

    .metric-card__value--warning {
      color: #6e4200;
    }

    .metric-card__value--success {
      color: #286a36;
    }

    .metric-card__value--danger {
      color: #8c1d13;
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

    /* ── Active card (Reserving with value > 0) — intentionally no border accent ── */

    /* ── Status card ── */
    .metric-card__value--status[data-status='not_started'] {
      color: #787774;
    }

    .metric-card__value--status[data-status='partial'] {
      color: #6e4200;
    }

    .metric-card__value--status[data-status='filled'] {
      color: #286a36;
    }

    .metric-card__value--status[data-status='over_allocated'] {
      color: #8c1d13;
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
      background: #d97706;
    }

    .metric-card__bar-fill[data-status='filled'] {
      background: #059669;
    }

    .metric-card__bar-fill[data-status='over_allocated'] {
      background: #dc3545;
      animation: bar-pulse 1.5s ease-in-out infinite;
    }

    .metric-card__bar-fill[data-status='fully_issued'] {
      background: #2563eb;
    }

    @keyframes bar-pulse {
      0%, 100% { opacity: 1; }
      50% { opacity: 0.6; }
    }

    @media (prefers-reduced-motion: reduce) {
      .metric-card {
        transition: none;
      }
      .metric-card__bar-fill {
        transition: none;
      }
      .metric-card__bar-fill[data-status='over_allocated'] {
        animation: none;
      }
    }

    /* ── Inline notice — compact, no heavy left-border ── */
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

    /* ── Section eyebrow ── */
    .detail__section-eyebrow {
      margin: 4px 0 0;
      font-size: 0.68rem;
      letter-spacing: 0.22em;
      text-transform: uppercase;
      color: var(--color-text-secondary);
      font-weight: var(--weight-semibold);
    }

    /* ── Warehouse cards ── */
    .warehouse-card {
      border-radius: 8px;
      border: 1px solid rgba(55, 53, 47, 0.14);
      background: #ffffff;
      overflow: hidden;
      box-shadow: 0 1px 3px rgba(55, 53, 47, 0.06);
    }

    .warehouse-card__header {
      display: flex;
      align-items: center;
      gap: 6px;
      padding: 5px 10px;
      border-bottom: 1px solid #ebebeb;
    }

    .warehouse-card__icon {
      font-size: 16px;
      width: 16px;
      height: 16px;
      color: var(--color-text-secondary);
    }

    .warehouse-card__name {
      display: block;
      font-size: 0.78rem;
      color: var(--color-text-primary);
    }

    .warehouse-card__meta {
      display: block;
      font-size: 0.65rem;
      color: var(--color-text-secondary);
    }

    .warehouse-card__table-wrap {
      overflow-x: auto;
    }

    .warehouse-table {
      width: 100%;
      border-collapse: collapse;
    }

    .warehouse-table th,
    .warehouse-table td {
      padding: 5px 7px;
      border-bottom: 1px solid #f0f0ee;
      text-align: left;
      vertical-align: middle;
      font-size: 0.78rem;
    }

    .warehouse-table th {
      padding: 4px 7px;
      font-size: 0.58rem;
      font-weight: var(--weight-semibold);
      letter-spacing: 0.14em;
      text-transform: uppercase;
      color: var(--color-text-secondary);
      background: #fafaf9;
    }

    .warehouse-table .col-num {
      text-align: right;
      font-variant-numeric: tabular-nums;
    }

    .row--selected {
      background: color-mix(in srgb, var(--color-success, #10b981) 7%, white);
    }

    .marker-list {
      display: flex;
      flex-wrap: wrap;
      gap: 4px;
      margin-top: 3px;
    }

    .marker-chip {
      padding: 1px 6px;
      border-radius: var(--radius-pill, 999px);
      background: var(--color-bg-info, #eff6ff);
      color: var(--color-info, #1e3a8a);
      font-size: 0.6rem;
      font-weight: var(--weight-medium);
    }

    .qty-input {
      width: 100%;
      max-width: 76px;
      padding: 3px 6px;
      border: 1px solid #ddddd9;
      border-radius: 5px;
      font: inherit;
      font-size: 0.78rem;
      font-variant-numeric: tabular-nums;
      background: #ffffff;
    }

    .qty-input:focus {
      outline: 2px solid var(--color-focus-ring, #1565c0);
      outline-offset: 1px;
      border-color: transparent;
    }

    /* ── Mobile cards ── */
    .mobile-cards {
      display: none;
    }

    .mobile-card {
      padding: 10px;
      border-radius: 8px;
      border: 1px solid rgba(55, 53, 47, 0.14);
      background: #ffffff;
    }

    .mobile-card__header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
    }

    .mobile-card__meta {
      margin: 3px 0;
      font-size: 0.75rem;
      color: var(--color-text-secondary);
    }

    .mobile-card__fields {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 6px;
      margin: 8px 0;
    }

    .mobile-card__field {
      display: flex;
      justify-content: space-between;
      font-size: 0.82rem;
    }

    .mobile-card__field span {
      color: var(--color-text-secondary);
    }

    .mobile-card__input {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
    }

    .mobile-card__input span {
      color: var(--color-text-secondary);
      font-size: 0.78rem;
    }

    /* ── Continuation callout (multi-warehouse) ── */
    .detail__continuation {
      display: flex;
      flex-direction: column;
      gap: 12px;
      padding: 14px 16px;
      border-radius: 10px;
      border: 1px solid var(--color-border-warning, rgba(217, 119, 6, 0.32));
      background: var(--color-surface-warning, rgba(254, 243, 199, 0.5));
    }

    .detail__continuation-head {
      display: flex;
      align-items: flex-start;
      gap: 10px;
    }

    .detail__continuation-head mat-icon {
      color: var(--color-text-warning, #b45309);
      flex-shrink: 0;
    }

    .detail__continuation-title {
      margin: 0 0 2px;
      font-size: 0.95rem;
      font-weight: var(--weight-semibold, 600);
      color: var(--color-text-primary, #37352F);
    }

    .detail__continuation-copy {
      margin: 0;
      font-size: 0.82rem;
      color: var(--color-text-secondary, #787774);
    }

    .detail__continuation-loading {
      margin-left: auto;
      display: inline-flex;
      align-items: center;
      gap: 4px;
      font-size: 0.78rem;
      color: var(--color-text-secondary, #787774);
    }

    .detail__continuation-loading mat-icon {
      font-size: 16px;
      width: 16px;
      height: 16px;
      animation: detail-continuation-spin 1.2s linear infinite;
    }

    @keyframes detail-continuation-spin {
      from { transform: rotate(0deg); }
      to { transform: rotate(360deg); }
    }

    @media (prefers-reduced-motion: reduce) {
      .detail__continuation-loading mat-icon {
        animation: none;
        transform: none;
      }
    }

    .detail__alternate-list {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 10px;
      margin: 0;
      padding: 0;
      list-style: none;
    }

    .detail__alternate-card {
      display: flex;
      flex-direction: column;
      gap: 8px;
      padding: 12px;
      background: #ffffff;
      border-radius: 8px;
      border: 1px solid rgba(55, 53, 47, 0.1);
    }

    .detail__alternate-head {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 8px;
    }

    .detail__alternate-name {
      font-size: 0.88rem;
      font-weight: var(--weight-semibold, 600);
      color: var(--color-text-primary, #37352F);
    }

    .detail__alternate-badge {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 2px 8px;
      font-size: 0.7rem;
      font-weight: var(--weight-semibold, 600);
      border-radius: 999px;
      white-space: nowrap;
    }

    .detail__alternate-badge mat-icon {
      font-size: 13px;
      width: 13px;
      height: 13px;
    }

    .detail__alternate-badge--ok {
      background: var(--color-surface-success, rgba(34, 197, 94, 0.12));
      color: var(--color-text-success, #166534);
    }

    .detail__alternate-badge--partial {
      background: var(--color-surface-warning, rgba(217, 119, 6, 0.12));
      color: var(--color-text-warning, #b45309);
    }

    .detail__alternate-figures {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 6px;
      margin: 0;
    }

    .detail__alternate-figures div {
      display: flex;
      flex-direction: column;
    }

    .detail__alternate-figures dt {
      margin: 0;
      font-size: 0.7rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      color: var(--color-text-secondary, #787774);
    }

    .detail__alternate-figures dd {
      margin: 0;
      font-size: 0.92rem;
      font-weight: var(--weight-semibold, 600);
      color: var(--color-text-primary, #37352F);
    }

    .detail__alternate-action {
      align-self: flex-start;
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

      .detail__metrics {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }

      .metric-card--status {
        grid-column: 1 / -1;
      }

      .warehouse-card__table-wrap {
        display: none;
      }

      .mobile-cards {
        display: grid;
        gap: 8px;
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
  readonly itemAvailabilityIssue = computed(() => this.store().getItemAvailabilityIssue(this.item()));

  readonly effectiveWarehouse = computed(() =>
    this.store().effectiveWarehouseForItem(this.item().item_id),
  );

  readonly isOverridden = computed(() => {
    const defaultId = this.item().source_warehouse_id != null ? String(this.item().source_warehouse_id) : '';
    const effective = this.effectiveWarehouse();
    return !!defaultId && !!effective && effective !== defaultId;
  });

  readonly warehouseSelectOptions = computed<WarehouseSelectOption[]>(() => {
    const options = new Map<string, string>();
    for (const candidate of this.item().candidates) {
      options.set(String(candidate.inventory_id), candidate.warehouse_name || `Warehouse ${candidate.inventory_id}`);
    }
    for (const alternate of this.item().alternate_warehouses ?? []) {
      options.set(String(alternate.warehouse_id), alternate.warehouse_name || `Warehouse ${alternate.warehouse_id}`);
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

  readonly fillRatio = computed(() => {
    const remaining = this.remainingQty();
    if (remaining <= 0) return 1;
    return Math.min(this.reservingQty() / remaining, 1);
  });

  readonly fillStatus = computed<'not_started' | 'partial' | 'filled' | 'over_allocated' | 'fully_issued'>(() => {
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

  // ── Continuation (multi-warehouse) computed signals ──

  readonly visibleAlternateWarehouses = computed(() => {
    const item = this.item();
    const alternates = item.alternate_warehouses ?? [];
    if (alternates.length === 0) {
      return alternates;
    }
    const loaded = new Set(this.store().loadedWarehousesByItem()[item.item_id] ?? []);
    return alternates.filter((alt) => !loaded.has(alt.warehouse_id));
  });

  readonly continuationVisible = computed(() => {
    if (this.readOnly()) return false;
    return this.visibleAlternateWarehouses().length > 0;
  });

  readonly continuationHasShortfall = computed(() => this.continuationShortfall() > 0);

  readonly continuationShortfall = computed(() => {
    const item = this.item();
    const effective = item.effective_remaining_qty ?? item.remaining_shortfall_qty ?? '0';
    const parsed = Number.parseFloat(String(effective));
    return Number.isFinite(parsed) ? parsed : 0;
  });

  readonly continuationLoading = computed(
    () => this.store().previewLoadingByItem()[this.item().item_id] ?? false,
  );

  readonly addingWarehouse = computed(
    () => this.store().addingWarehouseByItem()[this.item().item_id] ?? false,
  );

  readonly warehouseGroups = computed<WarehouseGroup[]>(() => {
    const candidates = this.item().candidates;
    const map = new Map<number, WarehouseGroup>();
    const insertionIndexByInventoryId = new Map<number, number>();

    for (const c of candidates) {
      const key = c.inventory_id;
      if (!map.has(key)) {
        insertionIndexByInventoryId.set(key, insertionIndexByInventoryId.size);
        map.set(key, {
          name: c.warehouse_name || `Inventory ${c.inventory_id}`,
          inventoryId: c.inventory_id,
          totalAvailable: 0,
          batchCount: 0,
          candidates: [],
        });
      }
      const group = map.get(key)!;
      group.totalAvailable += Number(c.available_qty) || 0;
      group.batchCount += 1;
      group.candidates.push(c);
    }

    // Respect the backend's FEFO/FIFO warehouse ranking when the
    // `warehouse_cards` payload is present. Cards provide the canonical
    // rank for each inventory_id; any loaded warehouse not covered by
    // the ranking falls to the end but keeps its relative insertion order.
    const rankByInventoryId = new Map<number, number>();
    for (const card of this.item().warehouse_cards ?? []) {
      rankByInventoryId.set(card.warehouse_id, card.rank);
    }
    const unranked = Number.MAX_SAFE_INTEGER;
    return [...map.values()].sort((left, right) => {
      const leftRank = rankByInventoryId.get(left.inventoryId) ?? unranked;
      const rightRank = rankByInventoryId.get(right.inventoryId) ?? unranked;
      if (leftRank !== rightRank) {
        return leftRank - rightRank;
      }
      return (
        (insertionIndexByInventoryId.get(left.inventoryId) ?? unranked)
        - (insertionIndexByInventoryId.get(right.inventoryId) ?? unranked)
      );
    });
  });

  onQtyChange(candidate: AllocationCandidate, value: number | string): void {
    const parsed = Number.parseFloat(String(value ?? '0'));
    this.store().setCandidateQuantity(
      this.item().item_id,
      candidate,
      Number.isFinite(parsed) ? parsed : 0,
    );
  }

  formatMarker(marker: string): string {
    return COMPLIANCE_LABELS[marker] ?? marker.replace(/_/g, ' ');
  }

  onWarehouseOverride(warehouseId: string): void {
    this.store().updateItemWarehouse(this.item().item_id, warehouseId);
  }

  onAddWarehouse(warehouseId: number): void {
    this.store().addItemWarehouse(this.item().item_id, warehouseId);
  }

  formatSource(sourceType: string): string {
    return formatSourceType(sourceType);
  }
}
