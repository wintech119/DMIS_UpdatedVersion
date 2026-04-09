import { DatePipe, DecimalPipe } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  input,
  output,
  signal,
} from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';

import { WarehouseAllocationCard } from '../../models/operations.model';

/**
 * Presentational tile for a single warehouse's contribution toward fulfilling
 * one item in the Stock-Aware step of the Package Fulfillment wizard. The
 * parent component is responsible for keeping FormControl state, adding or
 * removing cards, and aggregating shortfall across the item's card stack.
 *
 * Signal inputs drive every bit of state; this component never mutates its
 * inputs directly. The only outputs are a numeric `qtyChange` and a
 * `removeCard` request keyed by `warehouse_id`.
 *
 * Design reference: generation.tsx Section 4c (Multi-Warehouse Allocation
 * Pattern) and Section 4d, rendered with the warm Notion palette tokens used
 * by sibling step components.
 */
type AllocationFillStatus = 'FILLED' | 'PARTIAL' | 'EMPTY';

@Component({
  selector: 'app-warehouse-allocation-card',
  standalone: true,
  imports: [
    DatePipe,
    DecimalPipe,
    MatButtonModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
  ],
  template: `
    <article
      class="wh-card"
      role="group"
      [attr.aria-label]="ariaLabel()"
      [attr.data-fill-status]="fillStatus()">
      <!-- ── Header strip ───────────────────────────────────────── -->
      <header class="wh-card__header">
        <mat-icon class="wh-card__icon" aria-hidden="true">warehouse</mat-icon>
        <div class="wh-card__title-group">
          <span class="wh-card__name">{{ warehouse().warehouse_name }}</span>
          <span class="wh-card__rank-row">
            <span
              class="wh-card__rank"
              [attr.data-primary]="isPrimary() ? 'true' : null"
              [attr.data-rule]="warehouse().issuance_order">
              <mat-icon aria-hidden="true">
                {{ isPrimary() ? 'star' : 'stacked_line_chart' }}
              </mat-icon>
              {{ rankLabel() }}
            </span>
            <span class="wh-card__available-badge" aria-hidden="true">
              {{ warehouse().total_available | number: '1.0-4' }} avail
            </span>
          </span>
        </div>
        @if (canRemove() && !readOnly()) {
          <button
            mat-icon-button
            type="button"
            class="wh-card__remove"
            [attr.aria-label]="
              'Remove ' + warehouse().warehouse_name + ' from this item'
            "
            (click)="onRemoveClick()">
            <mat-icon aria-hidden="true">close</mat-icon>
          </button>
        }
      </header>

      <!-- ── Metric row (5 compact KPIs) ────────────────────────── -->
      <div class="wh-card__metrics" role="list">
        <div class="wh-metric" role="listitem">
          <span class="wh-metric__label">Requested</span>
          <span class="wh-metric__value">
            {{ itemRequestedQty() | number: '1.0-4' }}
          </span>
        </div>

        <div class="wh-metric" role="listitem">
          <span class="wh-metric__label">Available Here</span>
          <span class="wh-metric__value">
            {{ warehouse().total_available | number: '1.0-4' }}
          </span>
        </div>

        <div class="wh-metric" role="listitem">
          <span class="wh-metric__label">Allocating</span>
          <span
            class="wh-metric__value wh-metric__value--accent"
            [attr.data-fill-status]="fillStatus()">
            {{ allocatedQty() | number: '1.0-4' }}
          </span>
        </div>

        <div
          class="wh-metric"
          role="listitem"
          [class.wh-metric--critical]="shortfallNumeric() > 0"
          [class.wh-metric--success]="shortfallNumeric() === 0">
          <span class="wh-metric__label">Shortfall</span>
          <span
            class="wh-metric__value"
            [class.wh-metric__value--danger]="shortfallNumeric() > 0"
            [class.wh-metric__value--success]="shortfallNumeric() === 0">
            {{ itemShortfallQty() | number: '1.0-4' }}
          </span>
        </div>

        <div
          class="wh-metric wh-metric--status"
          role="listitem"
          [attr.data-fill-status]="fillStatus()">
          <span class="wh-metric__label">Status</span>
          <span class="wh-metric__status-pill" [attr.data-fill-status]="fillStatus()">
            <mat-icon aria-hidden="true">{{ statusIcon() }}</mat-icon>
            {{ statusLabel() }}
          </span>
        </div>
      </div>

      <!-- ── Quantity input ─────────────────────────────────────── -->
      <div class="wh-card__qty">
        <mat-form-field appearance="outline" class="wh-card__qty-field">
          <mat-label>Qty from {{ warehouse().warehouse_name }}</mat-label>
          <input
            matInput
            type="number"
            inputmode="decimal"
            min="0"
            [max]="maxQty()"
            step="1"
            maxlength="12"
            [value]="allocatedQty()"
            [disabled]="readOnly()"
            [attr.aria-describedby]="qtyHintId()"
            (input)="onQtyInput($event)" />
          <mat-hint [id]="qtyHintId()">
            up to {{ warehouse().total_available }}
          </mat-hint>
        </mat-form-field>
      </div>

      <!-- ── Batch detail (collapsible) ─────────────────────────── -->
      @if (batchCount() > 0) {
        <div class="wh-card__batch-region">
          <button
            mat-button
            type="button"
            class="wh-card__toggle"
            [attr.aria-expanded]="batchesExpanded()"
            [attr.aria-controls]="batchTableId()"
            (click)="toggleBatches()">
            <mat-icon aria-hidden="true">
              {{ batchesExpanded() ? 'expand_less' : 'expand_more' }}
            </mat-icon>
            {{ batchesExpanded() ? 'Hide' : 'View' }} {{ batchCount() }}
            {{ batchCount() === 1 ? 'batch' : 'batches' }}
          </button>

          @if (batchesExpanded()) {
            <div class="wh-card__batch-wrap" [id]="batchTableId()">
              <table class="wh-batch-table" role="grid">
                <thead>
                  <tr role="row">
                    <th scope="col" role="columnheader">Batch #</th>
                    <th scope="col" role="columnheader">Expiry</th>
                    <th scope="col" role="columnheader" class="wh-batch-table__num">
                      Available
                    </th>
                    <th scope="col" role="columnheader">UOM</th>
                  </tr>
                </thead>
                <tbody>
                  @for (batch of warehouse().batches; track batch.batch_id) {
                    <tr
                      role="row"
                      [class.wh-batch-row--expiring]="isExpiringSoon(batch.expiry_date)">
                      <td role="gridcell">
                        {{ batch.batch_no || ('Batch ' + batch.batch_id) }}
                      </td>
                      <td role="gridcell">
                        @if (batch.expiry_date) {
                          <span class="wh-batch-table__expiry">
                            @if (isExpiringSoon(batch.expiry_date)) {
                              <mat-icon aria-hidden="true">schedule</mat-icon>
                            }
                            {{ batch.expiry_date | date: 'mediumDate' }}
                          </span>
                        } @else {
                          <span class="wh-batch-table__muted">No expiry</span>
                        }
                      </td>
                      <td role="gridcell" class="wh-batch-table__num">
                        {{ batch.available_qty | number: '1.0-4' }}
                      </td>
                      <td role="gridcell">
                        {{ batch.uom_code || '—' }}
                      </td>
                    </tr>
                  }
                </tbody>
              </table>
            </div>
          }
        </div>
      }
    </article>
  `,
  styles: [
    `
      :host {
        display: block;
      }

      .wh-card {
        display: flex;
        flex-direction: column;
        gap: 12px;
        padding: 16px;
        border-radius: 12px;
        border: 1px solid #eae7dd;
        background: #ffffff;
        box-shadow: 0 1px 3px rgba(55, 53, 47, 0.06);
        transition: border-color 180ms ease, box-shadow 180ms ease;
      }

      .wh-card[data-fill-status='FILLED'] {
        border-color: color-mix(in srgb, #0f766e 40%, #eae7dd);
      }

      .wh-card[data-fill-status='PARTIAL'] {
        border-color: color-mix(in srgb, #d97706 32%, #eae7dd);
      }

      .wh-card:focus-within {
        border-color: color-mix(in srgb, var(--color-text-primary, #37352f) 35%, #eae7dd);
        box-shadow: 0 2px 8px rgba(55, 53, 47, 0.1);
      }

      @media (prefers-reduced-motion: reduce) {
        .wh-card {
          transition: none;
        }
      }

      /* ── Header strip ───────────────────────────────────── */
      .wh-card__header {
        display: flex;
        align-items: flex-start;
        gap: 10px;
      }

      .wh-card__icon {
        flex-shrink: 0;
        font-size: 20px;
        width: 20px;
        height: 20px;
        color: var(--color-text-secondary, #787774);
      }

      .wh-card__title-group {
        display: flex;
        flex-direction: column;
        gap: 4px;
        flex: 1 1 auto;
        min-width: 0;
      }

      .wh-card__name {
        font-size: 0.95rem;
        font-weight: var(--weight-semibold, 600);
        color: var(--color-text-primary, #37352f);
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }

      .wh-card__rank-row {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 6px;
      }

      .wh-card__rank {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        padding: 2px 8px;
        border-radius: var(--radius-pill, 999px);
        font-size: 0.65rem;
        font-weight: var(--weight-semibold, 600);
        letter-spacing: 0.1em;
        text-transform: uppercase;
        background: #f0eee7;
        color: var(--color-text-secondary, #787774);
      }

      .wh-card__rank mat-icon {
        font-size: 12px;
        width: 12px;
        height: 12px;
      }

      .wh-card__rank[data-primary='true'] {
        background: color-mix(in srgb, #0f766e 14%, white);
        color: #0f766e;
      }

      .wh-card__rank[data-rule='FIFO']:not([data-primary='true']) {
        background: var(--color-bg-info, #eff6ff);
        color: var(--color-info, #1e3a8a);
      }

      .wh-card__available-badge {
        display: inline-flex;
        align-items: center;
        padding: 2px 8px;
        border-radius: var(--radius-pill, 999px);
        background: #f7f6f3;
        color: var(--color-text-secondary, #787774);
        font-size: 0.65rem;
        font-weight: var(--weight-semibold, 600);
        letter-spacing: 0.05em;
        font-variant-numeric: tabular-nums;
      }

      .wh-card__remove {
        flex-shrink: 0;
        color: var(--color-text-secondary, #787774);
      }

      .wh-card__remove:focus-visible {
        outline: 2px solid var(--color-focus-ring, #1565c0);
        outline-offset: 2px;
        border-radius: 50%;
      }

      /* ── Metric row ─────────────────────────────────────── */
      .wh-card__metrics {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
      }

      .wh-metric {
        display: flex;
        flex-direction: column;
        gap: 2px;
        flex: 1 1 90px;
        min-width: 90px;
        padding: 8px 10px;
        border-radius: 8px;
        border: 1px solid #eae7dd;
        background: #f7f6f3;
      }

      .wh-metric__label {
        font-size: 0.6875rem;
        letter-spacing: 0.18em;
        text-transform: uppercase;
        color: var(--color-text-secondary, #787774);
      }

      .wh-metric__value {
        font-size: 1rem;
        font-weight: var(--weight-semibold, 600);
        font-variant-numeric: tabular-nums;
        color: var(--color-text-primary, #37352f);
      }

      .wh-metric__value--accent {
        color: #0f766e;
      }

      .wh-metric__value--accent[data-fill-status='EMPTY'] {
        color: var(--color-text-secondary, #787774);
      }

      .wh-metric__value--danger {
        color: #8c1d13;
      }

      .wh-metric__value--success {
        color: #286a36;
      }

      .wh-metric--critical {
        background: rgba(253, 221, 216, 0.25);
        border-color: color-mix(in srgb, #8c1d13 22%, #eae7dd);
      }

      .wh-metric--success {
        background: rgba(237, 247, 239, 0.5);
        border-color: color-mix(in srgb, #286a36 22%, #eae7dd);
      }

      .wh-metric--status[data-fill-status='FILLED'] {
        background: rgba(237, 247, 239, 0.5);
        border-color: color-mix(in srgb, #286a36 28%, #eae7dd);
      }

      .wh-metric--status[data-fill-status='PARTIAL'] {
        background: rgba(253, 232, 177, 0.3);
        border-color: color-mix(in srgb, #d97706 30%, #eae7dd);
      }

      .wh-metric--status[data-fill-status='EMPTY'] {
        background: #f7f6f3;
      }

      .wh-metric__status-pill {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        padding: 2px 8px;
        border-radius: var(--radius-pill, 999px);
        font-size: 0.7rem;
        font-weight: var(--weight-semibold, 600);
        letter-spacing: 0.08em;
        text-transform: uppercase;
        background: #eae7dd;
        color: var(--color-text-secondary, #787774);
      }

      .wh-metric__status-pill mat-icon {
        font-size: 13px;
        width: 13px;
        height: 13px;
      }

      .wh-metric__status-pill[data-fill-status='FILLED'] {
        background: color-mix(in srgb, #286a36 16%, white);
        color: #286a36;
      }

      .wh-metric__status-pill[data-fill-status='PARTIAL'] {
        background: color-mix(in srgb, #d97706 16%, white);
        color: #6e4200;
      }

      .wh-metric__status-pill[data-fill-status='EMPTY'] {
        background: #eae7dd;
        color: var(--color-text-secondary, #787774);
      }

      /* ── Qty input ──────────────────────────────────────── */
      .wh-card__qty {
        display: flex;
      }

      .wh-card__qty-field {
        width: 100%;
        max-width: 260px;
      }

      .wh-card__qty-field ::ng-deep .mat-mdc-form-field-subscript-wrapper {
        padding-top: 2px;
      }

      .wh-card__qty-field input:focus-visible {
        outline: 2px solid var(--color-focus-ring, #1565c0);
        outline-offset: 2px;
        border-radius: 4px;
      }

      /* ── Batch region ───────────────────────────────────── */
      .wh-card__batch-region {
        display: flex;
        flex-direction: column;
        gap: 8px;
      }

      .wh-card__toggle {
        align-self: flex-start;
        color: var(--color-info, #1e3a8a);
      }

      .wh-card__toggle mat-icon {
        font-size: 18px;
        width: 18px;
        height: 18px;
      }

      .wh-card__batch-wrap {
        border-radius: 8px;
        border: 1px solid #eae7dd;
        background: #f7f6f3;
        overflow-x: auto;
      }

      .wh-batch-table {
        width: 100%;
        border-collapse: collapse;
      }

      .wh-batch-table th,
      .wh-batch-table td {
        padding: 6px 10px;
        text-align: left;
        font-size: 0.78rem;
        border-bottom: 1px solid #eae7dd;
        color: var(--color-text-primary, #37352f);
      }

      .wh-batch-table tbody tr:last-child td {
        border-bottom: 0;
      }

      .wh-batch-table th {
        font-size: 0.6rem;
        font-weight: var(--weight-semibold, 600);
        letter-spacing: 0.14em;
        text-transform: uppercase;
        color: var(--color-text-secondary, #787774);
        background: #f0eee7;
      }

      .wh-batch-table__num {
        text-align: right;
        font-variant-numeric: tabular-nums;
      }

      .wh-batch-table__muted {
        color: var(--color-text-secondary, #787774);
      }

      .wh-batch-table__expiry {
        display: inline-flex;
        align-items: center;
        gap: 4px;
      }

      .wh-batch-table__expiry mat-icon {
        font-size: 14px;
        width: 14px;
        height: 14px;
        color: #6e4200;
      }

      .wh-batch-row--expiring {
        background: rgba(253, 232, 177, 0.3);
      }

      /* ── Responsive ─────────────────────────────────────── */
      @media (max-width: 760px) {
        .wh-card {
          padding: 14px;
          gap: 10px;
        }

        .wh-metric {
          flex-basis: calc(50% - 4px);
        }

        .wh-card__qty-field {
          max-width: 100%;
        }
      }

      @media (max-width: 520px) {
        .wh-metric {
          flex-basis: 100%;
        }
      }
    `,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class WarehouseAllocationCardComponent {
  /** The card data, including pre-ranked batches. */
  readonly warehouse = input.required<WarehouseAllocationCard>();
  /** Item total requested qty (decimal string) — shared across the card stack. */
  readonly itemRequestedQty = input.required<string>();
  /** Numeric qty the operator has typed for this card (parent owns form state). */
  readonly allocatedQty = input.required<number>();
  /** Whether the remove affordance is shown. */
  readonly canRemove = input<boolean>(true);
  /** Disable the input and hide remove when plan is in a locked state. */
  readonly readOnly = input<boolean>(false);
  /** Aggregate shortfall across the parent's cards (parent-computed). */
  readonly itemShortfallQty = input<string>('0');

  /** Emitted on every valid numeric change from the input. */
  readonly qtyChange = output<number>();
  /** Emitted with the warehouse_id when the remove affordance is clicked. */
  readonly removeCard = output<number>();

  /** Local UI-only state: whether the batch table is expanded. */
  private readonly expanded = signal(false);
  readonly batchesExpanded = this.expanded.asReadonly();

  /** Maximum quantity the input will accept (clamped to stock on hand here). */
  readonly maxQty = computed(() => this.parseDecimal(this.warehouse().total_available));

  readonly isPrimary = computed(() => this.warehouse().rank === 0);

  readonly rankLabel = computed(() => {
    const card = this.warehouse();
    if (card.rank === 0) {
      return `Primary ${card.issuance_order}`;
    }
    return `+${card.rank} ${card.issuance_order}`;
  });

  readonly batchCount = computed(() => this.warehouse().batches?.length ?? 0);

  readonly shortfallNumeric = computed(() => this.parseDecimal(this.itemShortfallQty()));

  readonly fillStatus = computed<AllocationFillStatus>(() => {
    const allocated = this.allocatedQty() ?? 0;
    if (allocated <= 0) {
      return 'EMPTY';
    }
    const requested = this.parseDecimal(this.itemRequestedQty());
    const cap = this.maxQty();
    // Filled when this card is either at/over the item's requested total
    // (rare if only one warehouse covers it) or at/over its own available cap.
    if (allocated >= requested && requested > 0) {
      return 'FILLED';
    }
    if (cap > 0 && allocated >= cap) {
      return 'FILLED';
    }
    return 'PARTIAL';
  });

  readonly statusLabel = computed<string>(() => {
    switch (this.fillStatus()) {
      case 'FILLED':
        return 'Filled';
      case 'PARTIAL':
        return 'Partial';
      default:
        return 'Empty';
    }
  });

  readonly statusIcon = computed<string>(() => {
    switch (this.fillStatus()) {
      case 'FILLED':
        return 'check_circle';
      case 'PARTIAL':
        return 'pending';
      default:
        return 'radio_button_unchecked';
    }
  });

  readonly ariaLabel = computed(() => {
    const card = this.warehouse();
    const allocated = this.allocatedQty() ?? 0;
    return (
      `${card.warehouse_name} — allocating ${allocated} of ${card.total_available} ` +
      `(${card.issuance_order} rank ${card.rank + 1})`
    );
  });

  readonly qtyHintId = computed(() => `wh-qty-hint-${this.warehouse().warehouse_id}`);
  readonly batchTableId = computed(
    () => `wh-batch-table-${this.warehouse().warehouse_id}`,
  );

  /** Clamps the user-entered value to [0, maxQty] and emits a numeric value. */
  onQtyInput(event: Event): void {
    const target = event.target as HTMLInputElement | null;
    if (!target) {
      return;
    }
    const raw = Number(target.value);
    if (!Number.isFinite(raw)) {
      // Reject NaN / Infinity without emitting — keep parent state stable.
      return;
    }
    const cap = this.maxQty();
    const clamped = Math.min(Math.max(raw, 0), cap > 0 ? cap : raw);
    if (clamped !== raw) {
      // Reflect the clamp back into the DOM so the displayed value matches.
      target.value = String(clamped);
    }
    this.qtyChange.emit(clamped);
  }

  onRemoveClick(): void {
    this.removeCard.emit(this.warehouse().warehouse_id);
  }

  toggleBatches(): void {
    this.expanded.update((prev) => !prev);
  }

  /** Expiring-soon heuristic: expiry_date within 14 days of today. */
  isExpiringSoon(expiryDate: string | null | undefined): boolean {
    if (!expiryDate) {
      return false;
    }
    const parsed = Date.parse(expiryDate);
    if (Number.isNaN(parsed)) {
      return false;
    }
    const now = Date.now();
    const fourteenDaysMs = 14 * 24 * 60 * 60 * 1000;
    return parsed - now <= fourteenDaysMs;
  }

  private parseDecimal(value: string | number | null | undefined): number {
    if (value == null) {
      return 0;
    }
    const parsed = typeof value === 'number' ? value : Number(value);
    return Number.isFinite(parsed) ? parsed : 0;
  }
}
