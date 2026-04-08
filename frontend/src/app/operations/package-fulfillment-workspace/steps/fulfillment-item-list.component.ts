import { DecimalPipe } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  input,
  output,
} from '@angular/core';
import { MatIconModule } from '@angular/material/icon';

import { AllocationItemGroup } from '../../models/operations.model';
import { OperationsWorkspaceStateService } from '../../services/operations-workspace-state.service';

@Component({
  selector: 'app-fulfillment-item-list',
  standalone: true,
  imports: [DecimalPipe, MatIconModule],
  template: `
    <div class="item-list">
      <p class="item-list__eyebrow">Items to Fulfil</p>

      @for (item of items(); track item.item_id) {
        <button
          class="item-card"
          type="button"
          [class.item-card--selected]="selectedItemId() === item.item_id"
          (click)="itemSelected.emit(item.item_id)">
          <div class="item-card__header">
            <strong>{{ item.item_name || ('Item ' + item.item_id) }}</strong>
            <span class="item-card__badge" [attr.data-rule]="item.issuance_order">
              {{ item.issuance_order }}
            </span>
          </div>
          <span class="item-card__code">{{ item.item_code || ('ID ' + item.item_id) }}</span>
          <div class="item-card__meta">
            <span>Req: {{ item.request_qty | number:'1.0-2' }}</span>
            <span>Rem: {{ item.remaining_qty | number:'1.0-2' }}</span>
          </div>
          @if (isItemOverridden(item.item_id)) {
            <span class="item-card__warehouse-override">
              <mat-icon aria-hidden="true">swap_horiz</mat-icon>
              Different warehouse
            </span>
          }
          @if (store().isRuleBypassedForItem(item.item_id)) {
            <span class="item-card__bypass">
              <mat-icon aria-hidden="true">policy</mat-icon>
              Rule Bypass
            </span>
          }
        </button>
      }
    </div>
  `,
  styles: [`
    .item-list {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }

    .item-list__eyebrow {
      margin: 0 0 2px;
      font-size: 0.65rem;
      letter-spacing: 0.2em;
      text-transform: uppercase;
      color: var(--color-text-secondary);
    }

    .item-card {
      display: flex;
      flex-direction: column;
      gap: 1px;
      padding: 7px 10px;
      border-radius: 8px;
      border: 1px solid rgba(55, 53, 47, 0.14);
      background: #ffffff;
      box-shadow: 0 1px 3px rgba(55, 53, 47, 0.06);
      text-align: left;
      cursor: pointer;
      transition: border-color 180ms ease, box-shadow 180ms ease;
      font: inherit;
      color: inherit;
    }

    .item-card:hover {
      border-color: rgba(55, 53, 47, 0.28);
      box-shadow: 0 2px 6px rgba(55, 53, 47, 0.1);
    }

    .item-card--selected {
      border-color: var(--color-text-primary, #37352F);
      box-shadow: 0 2px 8px rgba(55, 53, 47, 0.14);
    }

    .item-card__header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 6px;
    }

    .item-card__header strong {
      font-size: 0.85rem;
      font-weight: var(--weight-semibold);
      color: var(--color-text-primary);
    }

    .item-card__badge {
      display: inline-flex;
      padding: 1px 7px;
      border-radius: var(--radius-pill, 999px);
      font-size: 0.6rem;
      font-weight: var(--weight-semibold);
      letter-spacing: 0.1em;
      text-transform: uppercase;
      background: #e8e8e8;
      color: var(--color-text-secondary);
    }

    .item-card__badge[data-rule='FEFO'] {
      background: var(--color-bg-info, #eff6ff);
      color: var(--color-info, #1e3a8a);
    }

    .item-card__badge[data-rule='FIFO'] {
      background: color-mix(in srgb, var(--color-accent, #6366f1) 12%, white);
      color: var(--color-accent, #6366f1);
    }

    .item-card__code {
      font-size: 0.76rem;
      color: var(--color-text-secondary);
    }

    .item-card__meta {
      display: flex;
      gap: 10px;
      font-size: 0.76rem;
      color: var(--color-text-secondary);
      font-variant-numeric: tabular-nums;
    }

    .item-card__bypass {
      display: inline-flex;
      align-items: center;
      gap: 3px;
      margin-top: 1px;
      font-size: 0.65rem;
      color: var(--color-watch, #92400e);
    }

    .item-card__bypass mat-icon {
      font-size: 13px;
      width: 13px;
      height: 13px;
    }

    .item-card__warehouse-override {
      display: inline-flex;
      align-items: center;
      gap: 3px;
      margin-top: 1px;
      font-size: 0.65rem;
      color: var(--color-info, #17447f);
    }

    .item-card__warehouse-override mat-icon {
      font-size: 13px;
      width: 13px;
      height: 13px;
    }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FulfillmentItemListComponent {
  readonly items = input.required<AllocationItemGroup[]>();
  readonly selectedItemId = input<number | null>(null);
  readonly store = input.required<OperationsWorkspaceStateService>();
  readonly itemSelected = output<number>();

  isItemOverridden(itemId: number): boolean {
    const defaultWarehouseId = this.items().find((item) => item.item_id === itemId)?.source_warehouse_id;
    if (defaultWarehouseId == null) {
      return false;
    }
    return this.store().effectiveWarehouseForItem(itemId) !== String(defaultWarehouseId);
  }
}
