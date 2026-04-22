import { DatePipe, DecimalPipe } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  computed,
  effect,
  input,
  output,
  signal,
  viewChild,
} from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatMenuModule } from '@angular/material/menu';

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
 * Visual language tracks the `Allocation Redesign.html` reference: primary
 * card gets hero treatment, header carries a dot-separated identity subtitle
 * plus a top-right status pill, reason is a full-width info banner, and the
 * qty input is a ±-stepper group with inline "of X available" context. The
 * redundant 5-KPI strip from the previous iteration is retired — that data
 * lives on the item-level metric strip above the stack.
 */
type AllocationFillStatus = 'FILLED' | 'PARTIAL' | 'EMPTY';

@Component({
  selector: 'app-warehouse-allocation-card',
  standalone: true,
  imports: [DatePipe, DecimalPipe, MatButtonModule, MatIconModule, MatMenuModule],
  template: `
    <article
      class="wh-card"
      role="group"
      [attr.aria-label]="ariaLabel()"
      [attr.aria-busy]="isPending() ? 'true' : null"
      [attr.data-fill-status]="fillStatus()"
      [attr.data-pending]="isPending() ? 'true' : null"
      [attr.data-primary]="isPrimary() ? 'true' : null">
      @if (isPending()) {
        <span
          class="wh-card__pending-badge"
          role="status"
          aria-live="polite">
          <mat-icon aria-hidden="true">schedule</mat-icon>
          Loading stock detail…
        </span>
      }

      <!-- ── Header: identity (left) + status pill + remove (right) ─ -->
      <header class="wh-card__header">
        <div class="wh-card__identity">
          <mat-icon class="wh-card__icon" aria-hidden="true">warehouse</mat-icon>
          <div class="wh-card__identity-body">
            <h3 class="wh-card__name">{{ warehouse().warehouse_name }}</h3>
            <div class="wh-card__sub">
              <span
                class="wh-card__rank"
                [attr.data-primary]="isPrimary() ? 'true' : null"
                [attr.data-rule]="warehouse().issuance_order">
                {{ rankLabel() }}
              </span>
              <span class="wh-card__sub-dot" aria-hidden="true"></span>
              <span class="wh-card__available-badge">
                <strong>{{ warehouse().total_available | number: '1.0-4' }}</strong>
                available
              </span>
              @if (subtitleDate(); as sub) {
                <span class="wh-card__sub-dot" aria-hidden="true"></span>
                <span class="wh-card__sub-meta">{{ sub }}</span>
              }
            </div>
          </div>
        </div>

        <div class="wh-card__trail">
          <span
            class="wh-card__status-pill"
            [attr.data-fill-status]="fillStatus()"
            [attr.data-non-compliant]="isOverrideRiskActive() ? 'true' : null">
            <mat-icon aria-hidden="true">{{ statusIcon() }}</mat-icon>
            {{ statusLabel() }}
          </span>
          @if (!readOnly()) {
            <button
              mat-icon-button
              type="button"
              class="wh-card__menu-trigger"
              [matMenuTriggerFor]="cardMenu"
              [attr.aria-label]="
                'More actions for ' + warehouse().warehouse_name
              ">
              <mat-icon aria-hidden="true">more_vert</mat-icon>
            </button>
            <mat-menu #cardMenu="matMenu" xPosition="before">
              <button
                mat-menu-item
                type="button"
                (click)="onUseMax()">
                <mat-icon aria-hidden="true">vertical_align_top</mat-icon>
                <span>Use max available here</span>
              </button>
              <button
                mat-menu-item
                type="button"
                (click)="onClear()">
                <mat-icon aria-hidden="true">clear</mat-icon>
                <span>Clear allocation</span>
              </button>
              <button
                mat-menu-item
                type="button"
                [disabled]="!canRemove()"
                [attr.aria-label]="removeMenuAriaLabel()"
                (click)="onRemoveClick()">
                <mat-icon aria-hidden="true">delete_outline</mat-icon>
                <span>Remove warehouse</span>
              </button>
            </mat-menu>
          }
        </div>
      </header>

      <!-- ── Reason banner (full-width info) ───────────────────── -->
      <div class="wh-card__reason" role="note">
        <mat-icon aria-hidden="true">info</mat-icon>
        <span class="wh-card__reason-text">{{ reasonLine() }}</span>
      </div>

      <!-- ── Quantity stepper + context + helpers ──────────────── -->
      <div class="wh-card__qty">
        <span class="wh-card__qty-label">Allocating from this warehouse</span>
        <div class="wh-card__qty-row">
          <div class="wh-card__stepper" role="group" aria-label="Quantity">
            <button
              type="button"
              class="wh-card__step"
              [disabled]="readOnly() || allocatedQty() <= 0"
              [attr.aria-label]="'Decrement ' + warehouse().warehouse_name + ' qty'"
              (click)="onStep(-1)">
              <mat-icon aria-hidden="true">remove</mat-icon>
            </button>
            <input
              #qtyInput
              type="number"
              class="wh-card__qty-input"
              inputmode="decimal"
              min="0"
              [attr.max]="maxQty()"
              step="0.0001"
              maxlength="12"
              [value]="allocatedQty()"
              [disabled]="readOnly()"
              [attr.aria-label]="'Allocation qty for ' + warehouse().warehouse_name"
              [attr.aria-invalid]="qtyInvalid() ? 'true' : 'false'"
              [attr.aria-describedby]="describedByIds()"
              (input)="onQtyInput($event)" />
            <button
              type="button"
              class="wh-card__step"
              [disabled]="readOnly() || allocatedQty() >= maxQty()"
              [attr.aria-label]="'Increment ' + warehouse().warehouse_name + ' qty'"
              (click)="onStep(1)">
              <mat-icon aria-hidden="true">add</mat-icon>
            </button>
          </div>
          <span class="wh-card__qty-ctx" [id]="qtyHintId()">
            of <strong>{{ maxQty() | number: '1.0-4' }}</strong> available
          </span>
          <button
            type="button"
            class="wh-card__qty-btn wh-card__qty-btn--link"
            [disabled]="readOnly()"
            [attr.aria-label]="'Use max for ' + warehouse().warehouse_name"
            (click)="onUseMax()">
            Use max
          </button>
          <button
            type="button"
            class="wh-card__qty-btn wh-card__qty-btn--link"
            [disabled]="readOnly()"
            [attr.aria-label]="'Clear allocation from ' + warehouse().warehouse_name"
            (click)="onClear()">
            Clear
          </button>
        </div>
        @if (qtyInvalid()) {
          <div
            class="wh-card__qty-error"
            [id]="qtyErrorId()"
            role="alert"
            aria-live="polite">
            <mat-icon aria-hidden="true">warning_amber</mat-icon>
            <span>{{ qtyErrorMessage() }}</span>
          </div>
        }
      </div>

      <!-- ── Batch detail (collapsible) ────────────────────────── -->
      @if (batchCount() > 0) {
        <div class="wh-card__batch-region">
          <button
            type="button"
            class="wh-card__toggle"
            [class.wh-card__toggle--open]="batchesExpanded()"
            [attr.aria-expanded]="batchesExpanded()"
            [attr.aria-controls]="batchTableId()"
            (click)="toggleBatches()">
            <mat-icon aria-hidden="true">chevron_right</mat-icon>
            {{ batchesExpanded() ? 'Hide' : 'View' }} {{ batchCount() }}
            {{ batchCount() === 1 ? 'batch' : 'batches' }}
          </button>

          @if (batchesExpanded()) {
            <div class="wh-card__batch-wrap" [id]="batchTableId()">
              <table class="wh-batch-table">
                <thead>
                  <tr>
                    <th scope="col">Lot no.</th>
                    <th scope="col">Received</th>
                    <th scope="col">Expires</th>
                    <th scope="col" class="wh-batch-table__num">
                      Available
                    </th>
                  </tr>
                </thead>
                <tbody>
                  @for (batch of warehouse().batches; track batch.batch_id) {
                    <tr
                      [class.wh-batch-row--expiring]="isExpiringSoon(batch.expiry_date)">
                      <td class="wh-batch-table__mono">
                        {{ batch.batch_no || ('Batch ' + batch.batch_id) }}
                      </td>
                      <td>
                        @if (batch.batch_date) {
                          {{ batch.batch_date | date: 'mediumDate' }}
                        } @else {
                          <span class="wh-batch-table__muted">—</span>
                        }
                      </td>
                      <td>
                        @if (batch.expiry_date) {
                          <span class="wh-batch-table__expiry">
                            @if (isExpiringSoon(batch.expiry_date)) {
                              <mat-icon aria-hidden="true">schedule</mat-icon>
                            }
                            {{ batch.expiry_date | date: 'mediumDate' }}
                          </span>
                        } @else {
                          <span class="wh-batch-table__muted">—</span>
                        }
                      </td>
                      <td class="wh-batch-table__num">
                        {{ batch.available_qty | number: '1.0-4' }}
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
        gap: 14px;
        padding: 18px 20px;
        border-radius: 12px;
        border: 1px solid #eae7dd;
        background: #ffffff;
        box-shadow: 0 1px 3px rgba(55, 53, 47, 0.04);
        transition: border-color 180ms ease, box-shadow 180ms ease;
      }

      /* Primary card hero treatment — stronger border + soft shadow. */
      .wh-card[data-primary='true'] {
        border-color: color-mix(
          in srgb,
          var(--color-text-primary, #37352f) 16%,
          #eae7dd
        );
        box-shadow: 0 4px 12px rgba(55, 53, 47, 0.06);
      }

      .wh-card[data-fill-status='FILLED'] {
        border-color: color-mix(
          in srgb,
          var(--color-success, #286a36) 40%,
          #eae7dd
        );
      }

      .wh-card[data-fill-status='PARTIAL'] {
        border-color: color-mix(
          in srgb,
          var(--color-warning, #d97706) 32%,
          #eae7dd
        );
      }

      .wh-card:focus-within {
        box-shadow: 0 2px 8px rgba(55, 53, 47, 0.1);
      }

      /* Synthetic placeholder (add-next preview) */
      .wh-card[data-pending='true'] {
        border-style: dashed;
        border-color: color-mix(
          in srgb,
          var(--color-text-secondary, #787774) 45%,
          #eae7dd
        );
        background: color-mix(
          in srgb,
          var(--color-surface-subtle, #f7f6f3) 70%,
          #ffffff
        );
      }

      .wh-card__pending-badge {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        align-self: flex-start;
        padding: 2px 8px;
        border-radius: 999px;
        font-size: 11px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        background: color-mix(
          in srgb,
          var(--color-text-secondary, #787774) 12%,
          transparent
        );
        color: var(--color-text-secondary, #787774);
      }

      .wh-card__pending-badge mat-icon {
        font-size: 14px;
        width: 14px;
        height: 14px;
      }

      @media (prefers-reduced-motion: reduce) {
        .wh-card {
          transition: none;
        }
      }

      /* ── Header: identity on left, trail cluster on right ──── */
      .wh-card__header {
        display: flex;
        align-items: flex-start;
        gap: 12px;
      }

      .wh-card__identity {
        display: flex;
        align-items: flex-start;
        gap: 12px;
        min-width: 0;
        flex: 1 1 auto;
      }

      .wh-card__icon {
        flex-shrink: 0;
        font-size: 22px;
        width: 22px;
        height: 22px;
        color: var(--color-text-secondary, #787774);
        margin-top: 2px;
      }

      .wh-card__identity-body {
        display: flex;
        flex-direction: column;
        gap: 4px;
        min-width: 0;
        flex: 1 1 auto;
      }

      .wh-card__name {
        font-size: 1.02rem;
        font-weight: 700;
        letter-spacing: -0.01em;
        margin: 0;
        color: var(--color-text-primary, #37352f);
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }

      .wh-card__sub {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 8px;
        font-size: 0.82rem;
        color: var(--color-text-secondary, #787774);
      }

      .wh-card__sub-dot {
        width: 3px;
        height: 3px;
        border-radius: 50%;
        background: #cfcdc6;
      }

      .wh-card__rank {
        display: inline-flex;
        align-items: center;
        padding: 2px 8px;
        border-radius: 999px;
        font-size: 0.68rem;
        font-weight: 600;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        background: #f0eee7;
        color: var(--color-text-secondary, #787774);
      }

      .wh-card__rank[data-primary='true'] {
        background: var(--color-bg-info, #eff6ff);
        color: var(--color-info, #17447f);
      }

      .wh-card__rank[data-rule='FIFO']:not([data-primary='true']) {
        background: #f0eee7;
        color: var(--color-text-secondary, #787774);
      }

      .wh-card__available-badge {
        font-variant-numeric: tabular-nums;
      }

      .wh-card__available-badge strong {
        color: var(--color-text-primary, #37352f);
        font-weight: 700;
      }

      .wh-card__sub-meta {
        font-variant-numeric: tabular-nums;
      }

      .wh-card__trail {
        display: flex;
        align-items: center;
        gap: 6px;
        flex-shrink: 0;
      }

      .wh-card__status-pill {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        padding: 4px 10px;
        border-radius: 999px;
        font-size: 0.76rem;
        font-weight: 600;
        letter-spacing: 0.02em;
        background: #eae7dd;
        color: var(--color-text-secondary, #787774);
      }

      .wh-card__status-pill mat-icon {
        font-size: 14px;
        width: 14px;
        height: 14px;
      }

      .wh-card__status-pill[data-fill-status='FILLED'] {
        background: color-mix(in srgb, var(--color-success, #286a36) 14%, white);
        color: var(--color-success, #286a36);
      }

      .wh-card__status-pill[data-fill-status='PARTIAL'] {
        background: color-mix(in srgb, var(--color-warning, #d97706) 14%, white);
        color: var(--color-warning-text, #6e4200);
      }

      .wh-card__status-pill[data-fill-status='EMPTY'] {
        background: #eae7dd;
        color: var(--color-text-secondary, #787774);
      }

      .wh-card__status-pill[data-non-compliant='true'] {
        background: color-mix(in srgb, var(--color-warning, #d97706) 22%, white);
        color: var(--color-warning-text, #6e4200);
      }

      .wh-card__menu-trigger {
        flex-shrink: 0;
        color: var(--color-text-secondary, #787774);
      }

      .wh-card__menu-trigger:hover:not([disabled]) {
        color: var(--color-text-primary, #37352f);
      }

      .wh-card__menu-trigger:focus-visible {
        outline: 2px solid var(--color-focus-ring, #1565c0);
        outline-offset: 2px;
        border-radius: 50%;
      }

      /* ── Reason banner (full-width, info-tinted) ───────────── */
      .wh-card__reason {
        display: flex;
        align-items: flex-start;
        gap: 10px;
        padding: 10px 14px;
        border-radius: 8px;
        background: var(--color-bg-info, #eff6ff);
        color: var(--color-info, #17447f);
        font-size: 0.86rem;
        line-height: 1.45;
      }

      .wh-card__reason mat-icon {
        flex-shrink: 0;
        font-size: 18px;
        width: 18px;
        height: 18px;
        margin-top: 1px;
      }

      .wh-card__reason-text {
        flex: 1 1 auto;
      }

      /* ── Qty row: stepper + ctx + helpers ──────────────────── */
      .wh-card__qty {
        display: flex;
        flex-direction: column;
        gap: 8px;
      }

      .wh-card__qty-label {
        font-size: 0.82rem;
        font-weight: 600;
        color: var(--color-text-primary, #37352f);
      }

      .wh-card__qty-row {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 12px;
      }

      .wh-card__stepper {
        display: inline-flex;
        align-items: stretch;
        border: 1px solid var(--color-border-default, rgba(55, 53, 47, 0.18));
        border-radius: 8px;
        overflow: hidden;
        background: #ffffff;
      }

      .wh-card__stepper:focus-within {
        outline: 2px solid var(--color-focus-ring, #1565c0);
        outline-offset: 2px;
      }

      .wh-card__step {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 40px;
        min-height: 40px;
        border: 0;
        background: transparent;
        color: var(--color-text-primary, #37352f);
        cursor: pointer;
        padding: 0;
      }

      .wh-card__step:hover:not(:disabled) {
        background: #f0eee7;
      }

      .wh-card__step:disabled {
        color: var(--color-text-secondary, #c2bfb7);
        cursor: not-allowed;
      }

      .wh-card__step mat-icon {
        font-size: 20px;
        width: 20px;
        height: 20px;
      }

      .wh-card__qty-input {
        width: 64px;
        min-height: 40px;
        padding: 0 8px;
        border: 0;
        border-left: 1px solid
          var(--color-border-default, rgba(55, 53, 47, 0.18));
        border-right: 1px solid
          var(--color-border-default, rgba(55, 53, 47, 0.18));
        font-size: 1rem;
        font-weight: 600;
        text-align: center;
        font-variant-numeric: tabular-nums;
        color: var(--color-text-primary, #37352f);
        background: transparent;
      }

      .wh-card__qty-input:focus {
        outline: none;
      }

      /* Hide native number-input spinners — our ± buttons replace them. */
      .wh-card__qty-input::-webkit-inner-spin-button,
      .wh-card__qty-input::-webkit-outer-spin-button {
        -webkit-appearance: none;
        margin: 0;
      }

      .wh-card__qty-input {
        -moz-appearance: textfield;
      }

      .wh-card__qty-ctx {
        font-size: 0.88rem;
        color: var(--color-text-secondary, #787774);
      }

      .wh-card__qty-ctx strong {
        color: var(--color-text-primary, #37352f);
        font-weight: 700;
      }

      .wh-card__qty-btn {
        padding: 6px 10px;
        font-size: 0.85rem;
        font-weight: 600;
        border: 0;
        background: transparent;
        color: var(--color-info, #17447f);
        cursor: pointer;
        border-radius: 4px;
      }

      .wh-card__qty-btn:hover:not(:disabled) {
        background: var(--color-bg-info, #eff6ff);
      }

      .wh-card__qty-btn:disabled {
        color: var(--color-text-secondary, #c2bfb7);
        cursor: not-allowed;
      }

      .wh-card__qty-btn--link {
        padding: 6px 4px;
      }

      .wh-card__qty-error {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 6px 10px;
        border-radius: 6px;
        background: #fde8b1;
        color: var(--color-warning-text, #6e4200);
        font-size: 0.82rem;
      }

      .wh-card__qty-error mat-icon {
        font-size: 16px;
        width: 16px;
        height: 16px;
      }

      /* ── Batch region ──────────────────────────────────────── */
      .wh-card__batch-region {
        display: flex;
        flex-direction: column;
        gap: 8px;
        padding-top: 8px;
        border-top: 1px dashed #eae7dd;
      }

      .wh-card__toggle {
        align-self: flex-start;
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 4px 0;
        border: 0;
        background: transparent;
        color: var(--color-info, #17447f);
        font-size: 0.85rem;
        font-weight: 600;
        cursor: pointer;
      }

      .wh-card__toggle:hover {
        color: var(--color-text-primary, #37352f);
      }

      .wh-card__toggle mat-icon {
        font-size: 18px;
        width: 18px;
        height: 18px;
        transition: transform 180ms ease;
      }

      .wh-card__toggle--open mat-icon {
        transform: rotate(90deg);
      }

      @media (prefers-reduced-motion: reduce) {
        .wh-card__toggle mat-icon {
          transition: none;
        }
      }

      .wh-card__batch-wrap {
        border-radius: 8px;
        border: 1px solid #eae7dd;
        background: #fbfaf7;
        overflow-x: auto;
      }

      .wh-batch-table {
        width: 100%;
        border-collapse: collapse;
      }

      .wh-batch-table th,
      .wh-batch-table td {
        padding: 8px 12px;
        text-align: left;
        font-size: 0.82rem;
        border-bottom: 1px solid #eae7dd;
        color: var(--color-text-primary, #37352f);
      }

      .wh-batch-table tbody tr:last-child td {
        border-bottom: 0;
      }

      .wh-batch-table th {
        font-size: 0.68rem;
        font-weight: 600;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: var(--color-text-secondary, #787774);
        background: #f0eee7;
      }

      .wh-batch-table__num {
        text-align: right;
        font-variant-numeric: tabular-nums;
      }

      .wh-batch-table__mono {
        font-family: ui-monospace, SFMono-Regular, 'Menlo', 'Consolas', monospace;
        font-size: 0.85rem;
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
        color: var(--color-warning-text, #6e4200);
      }

      .wh-batch-row--expiring {
        background: rgba(253, 232, 177, 0.3);
      }

      /* ── Responsive ─────────────────────────────────────── */
      @media (max-width: 760px) {
        .wh-card {
          padding: 16px;
          gap: 12px;
        }

        .wh-card__header {
          flex-direction: column;
          align-items: stretch;
          gap: 10px;
        }

        .wh-card__trail {
          justify-content: flex-start;
        }
      }

      @media (max-width: 520px) {
        .wh-card__qty-row {
          gap: 8px;
        }

        .wh-card__qty-input {
          width: 56px;
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
  /**
   * Numeric remaining qty the item still needs. Used to clamp the qty input so
   * the operator cannot reserve more than the item requires from any single
   * card. Parent passes `max(0, remaining_qty - reserving + allocatedForThisCard)`
   * so `Use max` works intuitively on the active card without reopening
   * quantities already issued on another package leg.
   */
  readonly remainingQtyForItem = input<number>(0);
  /**
   * Raised by the parent when this card is at risk of triggering an override
   * (e.g. skipping a higher-ranked card with remaining stock). Drives warning
   * tone on the status pill; color is never the sole signal.
   */
  readonly isOverrideRisk = input<boolean>(false);

  /** Emitted on every valid numeric change from the input. */
  readonly qtyChange = output<number>();
  /** Emitted with the warehouse_id when the remove affordance is clicked. */
  readonly removeCard = output<number>();

  /** Reference to the qty input element — exposed to parents via focusQtyInput(). */
  private readonly qtyInputRef = viewChild<ElementRef<HTMLInputElement>>('qtyInput');

  /** Local UI-only state: whether the batch table is expanded. */
  private readonly expanded = signal(false);
  readonly batchesExpanded = this.expanded.asReadonly();

  /** Local UI-only state: most recent qty validation error, if any. */
  private readonly lastError = signal<string | null>(null);
  readonly qtyInvalid = computed(() => this.lastError() !== null);
  readonly qtyErrorMessage = computed(() => this.lastError() ?? '');

  constructor() {
    // When the card's warehouse binding changes (e.g. the stack re-orders or a
    // parent swaps the card out), any prior validation error is no longer
    // meaningful. Clear it so the operator does not see a stale message on a
    // fresh card.
    const lastWarehouseId = signal<number | null>(null);
    effect(() => {
      const currentId = this.warehouse().warehouse_id;
      if (lastWarehouseId() !== null && lastWarehouseId() !== currentId) {
        this.lastError.set(null);
      }
      lastWarehouseId.set(currentId);
    });
  }

  /**
   * Public API: focus this card's qty input. Used by the parent after adding
   * a new warehouse so keyboard users land in the correct place. Prefers the
   * scoped viewChild reference over any global DOM query.
   */
  focusQtyInput(): void {
    this.qtyInputRef()?.nativeElement.focus();
  }

  /**
   * Maximum quantity the input will accept. Clamped to the lesser of the
   * card-level cap (`allocatable_available_qty` when present, else
   * `total_available`) and the item's remaining qty need.
   */
  readonly maxQty = computed(() => {
    const card = this.warehouse();
    const cap = this.parseDecimal(
      card.allocatable_available_qty ?? card.total_available,
    );
    const remaining = this.remainingQtyForItem();
    const safeRemaining = Number.isFinite(remaining) ? remaining : cap;
    return Math.max(0, Math.min(cap, safeRemaining));
  });

  readonly isPrimary = computed(() => this.warehouse().rank === 0);

  /**
   * True when this card is a client-only synthetic placeholder (user added an
   * alternate warehouse but the backend preview hasn't returned detail yet).
   * Used to render a dashed-border "Loading stock detail…" visual cue so
   * operators don't mistake an in-flight placeholder for a fully-loaded card.
   */
  readonly isPending = computed(() => this.warehouse().pending === true);

  readonly rankLabel = computed(() => {
    const card = this.warehouse();
    if (card.rank === 0) {
      return `Primary ${card.issuance_order}`;
    }
    return `+${card.rank} ${card.issuance_order}`;
  });

  readonly batchCount = computed(() => this.warehouse().batches?.length ?? 0);

  readonly shortfallNumeric = computed(() =>
    this.parseDecimal(this.itemShortfallQty()),
  );

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

  /** Active only when the card sits empty while override risk is present. */
  readonly isOverrideRiskActive = computed(
    () => this.isOverrideRisk() && (this.allocatedQty() ?? 0) === 0,
  );

  readonly statusLabel = computed<string>(() => {
    if (this.isOverrideRiskActive()) {
      return 'Override risk';
    }
    switch (this.fillStatus()) {
      case 'FILLED':
        return 'Filled from this warehouse';
      case 'PARTIAL':
        return 'Partial from this warehouse';
      default:
        return 'Not yet allocated';
    }
  });

  readonly statusIcon = computed<string>(() => {
    if (this.isOverrideRiskActive()) {
      return 'warning_amber';
    }
    switch (this.fillStatus()) {
      case 'FILLED':
        return 'check_circle';
      case 'PARTIAL':
        return 'pie_chart';
      default:
        return 'radio_button_unchecked';
    }
  });

  /**
   * Dot-separated subtitle metadata — the "Received 02 Mar 2025" or
   * "Earliest expiry 12 May 2026" line next to the available qty.
   * Returns an empty string when the backend omits ranking_context so the
   * template's `@if` guard can drop the dot separator cleanly.
   */
  readonly subtitleDate = computed<string>(() => {
    const card = this.warehouse();
    const issuance = String(card.issuance_order ?? '').toUpperCase();
    const ctx = card.ranking_context ?? null;
    if (!ctx) {
      return '';
    }
    if (issuance === 'FEFO' && ctx.top_expiry_date) {
      return `Earliest expiry ${this.formatDate(ctx.top_expiry_date)}`;
    }
    if (issuance === 'FIFO' && ctx.top_batch_date) {
      return `Received ${this.formatDate(ctx.top_batch_date)}`;
    }
    return '';
  });

  /**
   * Derived rationale for this card's rank. Never speculative and always a
   * non-empty string — falls back to the rank-only copy when the backend omits
   * `ranking_context`, and appends a source-type annotation when any batch is
   * non-ON_HAND. Typed as a guaranteed string so the template does not need a
   * truthiness guard.
   */
  readonly reasonLine = computed<string>(() => {
    const card = this.warehouse();
    const rank = card.rank ?? 0;
    const issuance = String(card.issuance_order ?? '').toUpperCase();
    const ctx = card.ranking_context ?? null;
    const shortfall = this.parseDecimal(this.itemShortfallQty());
    const suggested = this.parseDecimal(card.suggested_qty);
    let base: string;

    if (rank === 0) {
      if (issuance === 'FEFO' && ctx?.top_expiry_date) {
        const formatted = this.formatDate(ctx.top_expiry_date);
        base = `Ranked first — earliest expiring batch ${formatted} (FEFO)`;
      } else if (issuance === 'FIFO' && ctx?.top_batch_date) {
        const formatted = this.formatDate(ctx.top_batch_date);
        base = `Ranked first — oldest stock, received ${formatted} (FIFO)`;
      } else {
        base = `Primary source — ranked first (${issuance || 'FIFO'})`;
      }
    } else if (shortfall > 0) {
      base = `Ranked ${rank + 1} — holds ${this.formatNumber(suggested)} to cover the remaining ${this.formatNumber(shortfall)}`;
    } else {
      base = `Ranked ${rank + 1} — additional available stock (${issuance || 'FIFO'})`;
    }

    const sourceSuffix = this.nonOnHandSource(card);
    return sourceSuffix ? `${base} · includes ${sourceSuffix} source` : base;
  });

  readonly ariaLabel = computed(() => {
    const card = this.warehouse();
    const allocated = this.allocatedQty() ?? 0;
    const base = (
      `${card.warehouse_name} — allocating ${allocated} of ${card.total_available} ` +
      `(${card.issuance_order} rank ${card.rank + 1})`
    );
    // reasonLine is a non-empty string by contract; append unconditionally.
    return `${base}. ${this.reasonLine()}`;
  });

  /**
   * ARIA label for the "Remove warehouse" menu item. When disabled (primary,
   * rank-0 card), supplies a spoken reason so AT users hear *why* the action is
   * unavailable rather than just "disabled".
   */
  readonly removeMenuAriaLabel = computed(() =>
    this.canRemove()
      ? 'Remove warehouse'
      : 'Remove warehouse (unavailable — the primary warehouse cannot be removed)',
  );

  readonly qtyHintId = computed(() => `wh-qty-hint-${this.warehouse().warehouse_id}`);
  readonly qtyErrorId = computed(() => `wh-qty-error-${this.warehouse().warehouse_id}`);
  readonly describedByIds = computed(() =>
    [this.qtyHintId(), this.qtyInvalid() ? this.qtyErrorId() : null]
      .filter((v): v is string => !!v)
      .join(' '),
  );
  readonly batchTableId = computed(
    () => `wh-batch-table-${this.warehouse().warehouse_id}`,
  );

  /**
   * Validate and emit on every input event. Accepts non-negative plain
   * decimal values up to 4 decimal places (matching the backend allocation
   * contract). Rejects negative, NaN/Infinity, scientific notation, more than
   * 4 decimal places, or > cap values without emitting; the DOM reflects the
   * rejected value so the operator sees the error, but parent state stays
   * clean.
   */
  onQtyInput(event: Event): void {
    const target = event.target as HTMLInputElement | null;
    if (!target) {
      return;
    }
    const rawText = String(target.value ?? '');
    const trimmed = rawText.trim();
    if (trimmed === '') {
      this.lastError.set(null);
      this.qtyChange.emit(0);
      return;
    }
    // Plain decimal, non-negative, up to 4 decimal places — reject scientific
    // notation, signs, and anything with more precision than the backend
    // supports.
    if (!/^\d+(?:\.\d{1,4})?$/.test(trimmed)) {
      if (/^\d+\.\d{5,}$/.test(trimmed)) {
        this.lastError.set('Use up to 4 decimal places.');
      } else {
        this.lastError.set('Enter a valid quantity.');
      }
      return;
    }
    const raw = Number(trimmed);
    if (!Number.isFinite(raw)) {
      this.lastError.set('Enter a valid quantity.');
      return;
    }
    if (raw < 0) {
      this.lastError.set('Quantity cannot be negative.');
      return;
    }
    const cap = this.maxQty();
    if (raw > cap) {
      this.lastError.set(`Maximum is ${cap}.`);
      return;
    }
    this.lastError.set(null);
    this.qtyChange.emit(raw);
  }

  /**
   * Step the qty up or down by a single unit, clamped to [0, maxQty]. The
   * parent rehydrates the input via its signal so the DOM stays in sync.
   */
  onStep(delta: -1 | 1): void {
    const current = this.allocatedQty() ?? 0;
    const next = Math.max(0, Math.min(this.maxQty(), current + delta));
    if (next === current) {
      return;
    }
    this.lastError.set(null);
    this.qtyChange.emit(next);
  }

  /**
   * Emits min(maxQty, remainingQtyForItem) normalized to the backend-supported
   * 4-decimal precision (no floor — preserve fractional accuracy).
   */
  onUseMax(): void {
    const target = Math.min(this.maxQty(), this.remainingQtyForItem() || this.maxQty());
    const clamped = Math.max(0, target);
    const normalized = Math.round(clamped * 10_000) / 10_000;
    this.lastError.set(null);
    this.qtyChange.emit(normalized);
  }

  onClear(): void {
    this.lastError.set(null);
    this.qtyChange.emit(0);
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
    return parsed > now && parsed - now <= fourteenDaysMs;
  }

  private parseDecimal(value: string | number | null | undefined): number {
    if (value == null) {
      return 0;
    }
    const parsed = typeof value === 'number' ? value : Number(value);
    return Number.isFinite(parsed) ? parsed : 0;
  }

  private formatDate(value: string | null | undefined): string {
    if (!value) {
      return '';
    }
    const parsed = Date.parse(value);
    if (Number.isNaN(parsed)) {
      return value;
    }
    return new Date(parsed).toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  }

  private formatNumber(value: number): string {
    if (!Number.isFinite(value)) {
      return '0';
    }
    const rounded = Math.round(value * 10_000) / 10_000;
    return Number.isInteger(rounded) ? String(rounded) : rounded.toString();
  }

  private nonOnHandSource(card: WarehouseAllocationCard): string | null {
    const batches = card.batches ?? [];
    for (const batch of batches) {
      const source = String(batch.source_type ?? 'ON_HAND').toUpperCase();
      if (source !== 'ON_HAND') {
        return source;
      }
    }
    return null;
  }
}
