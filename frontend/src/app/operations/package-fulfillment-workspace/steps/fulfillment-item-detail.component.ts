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
import { MatIconModule } from '@angular/material/icon';

import { AllocationCandidate, AllocationItemGroup } from '../../models/operations.model';
import { OperationsWorkspaceStateService } from '../../services/operations-workspace-state.service';
import { formatSourceType } from '../../models/operations-status.util';

interface WarehouseGroup {
  name: string;
  inventoryId: number;
  totalAvailable: number;
  batchCount: number;
  candidates: AllocationCandidate[];
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
  imports: [DatePipe, DecimalPipe, FormsModule, MatButtonModule, MatIconModule],
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

      <!-- 5 Metric cards — white, elevated off the warm background -->
      <div class="detail__metrics">
        <div class="metric-card">
          <span class="metric-card__label">Requested</span>
          <span class="metric-card__value">{{ item().request_qty | number:'1.0-4' }}</span>
        </div>
        <div class="metric-card">
          <span class="metric-card__label">Issued</span>
          <span class="metric-card__value">{{ item().issue_qty | number:'1.0-4' }}</span>
        </div>
        <div class="metric-card">
          <span class="metric-card__label">Need Now</span>
          <span class="metric-card__value">{{ item().remaining_qty | number:'1.0-4' }}</span>
        </div>
        <div class="metric-card">
          <span class="metric-card__label">Allocating Now</span>
          <span class="metric-card__value metric-card__value--accent">
            {{ store().getSelectedTotalForItem(item().item_id) | number:'1.0-4' }}
          </span>
        </div>
        <div class="metric-card">
          <span class="metric-card__label">Shortfall</span>
          <span class="metric-card__value"
            [class.metric-card__value--danger]="store().getUncoveredQtyForItem(item().item_id) > 0">
            {{ store().getUncoveredQtyForItem(item().item_id) | number:'1.0-4' }}
          </span>
        </div>
      </div>

      <!-- Inline validation — compact notice tucked under metrics -->
      @if (store().getItemValidationMessage(item()); as msg) {
        <p class="detail__notice detail__notice--error" role="alert">
          <mat-icon aria-hidden="true">info</mat-icon>
          {{ msg }}
        </p>
      }

      <!-- Available Warehouses -->
      <p class="detail__section-eyebrow">Available Warehouses</p>

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
                @for (c of wh.candidates; track c.batch_id + '-' + c.source_type) {
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
                        step="0.0001"
                        [disabled]="readOnly()"
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
        @for (c of item().candidates; track c.inventory_id + '-' + c.batch_id + '-' + c.source_type) {
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
                step="0.0001"
                [disabled]="readOnly()"
                [ngModel]="store().getSelectedQtyForCandidate(item().item_id, c)"
                (ngModelChange)="onQtyChange(c, $event)"
              />
            </label>
          </div>
        }
      </div>

      @if (store().isRuleBypassedForItem(item().item_id)) {
        <p class="detail__notice detail__notice--warning" role="status">
          <mat-icon aria-hidden="true">policy</mat-icon>
          This selection no longer matches the system's {{ item().issuance_order }} recommendation.
          Submit an override reason in the next step.
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

    .metric-card__value--accent {
      color: var(--color-accent, #6366f1);
    }

    .metric-card__value--danger {
      color: var(--color-critical, #991b1b);
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

    /* ── Responsive ── */
    @media (max-width: 1100px) {
      .detail__metrics {
        grid-template-columns: repeat(3, minmax(0, 1fr));
      }
    }

    @media (max-width: 768px) {
      .detail__header {
        flex-direction: column;
      }

      .detail__metrics {
        grid-template-columns: repeat(2, minmax(0, 1fr));
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

  readonly warehouseGroups = computed<WarehouseGroup[]>(() => {
    const candidates = this.item().candidates;
    const map = new Map<number, WarehouseGroup>();

    for (const c of candidates) {
      const key = c.inventory_id;
      if (!map.has(key)) {
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

    return [...map.values()];
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

  formatSource(sourceType: string): string {
    return formatSourceType(sourceType);
  }
}
