import { DecimalPipe } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  input,
  output,
} from '@angular/core';
import { MatIconModule } from '@angular/material/icon';

import { AllocationItemGroup } from '../../models/operations.model';
import { OperationsWorkspaceStateService } from '../../services/operations-workspace-state.service';

type ItemStatus = 'filled' | 'compliant_partial' | 'non_compliant' | 'no_stock' | 'draft';

interface ItemStatusView {
  status: ItemStatus;
  icon: string;
  iconLabel: string;
}

@Component({
  selector: 'app-fulfillment-item-list',
  standalone: true,
  imports: [DecimalPipe, MatIconModule],
  template: `
    <div class="item-list">
      <p class="item-list__eyebrow">Items to Fulfil</p>

      @for (item of items(); track item.item_id) {
        @let view = statusView(item);
        <button
          class="item-card"
          type="button"
          [class.item-card--selected]="selectedItemId() === item.item_id"
          [class.item-card--issued]="item.fully_issued"
          [attr.data-status]="view.status"
          [attr.aria-current]="selectedItemId() === item.item_id ? 'true' : null"
          (click)="itemSelected.emit(item.item_id)">
          <div class="item-card__row">
            <span
              class="item-card__status"
              [attr.data-status]="view.status"
              [attr.aria-label]="view.iconLabel">
              <mat-icon aria-hidden="true">{{ view.icon }}</mat-icon>
            </span>
            <div class="item-card__body">
              <div class="item-card__header">
                <strong class="item-card__name">
                  {{ item.item_name || ('Item ' + item.item_id) }}
                </strong>
                <span class="item-card__badge" [attr.data-rule]="item.issuance_order">
                  {{ item.issuance_order }}
                </span>
              </div>
              <span class="item-card__code">
                {{ item.item_code || ('ID ' + item.item_id) }}
              </span>
              <div class="item-card__meta">
                @if (item.fully_issued) {
                  <span class="item-card__meta-part item-card__meta-part--issued">
                    {{ item.issue_qty | number:'1.0-2' }} /
                    {{ item.request_qty | number:'1.0-2' }} issued
                  </span>
                } @else {
                  <span class="item-card__meta-part">
                    Req {{ item.request_qty | number:'1.0-2' }}
                  </span>
                  <span class="item-card__meta-sep" aria-hidden="true">&middot;</span>
                  @if (view.status === 'no_stock') {
                    <span class="item-card__meta-part item-card__meta-part--alert">
                      No stock
                    </span>
                  } @else if (view.status === 'draft' && reservingFor(item.item_id) === 0) {
                    <span class="item-card__meta-part">Not started</span>
                  } @else {
                    <span class="item-card__meta-part">
                      Reserving {{ reservingFor(item.item_id) | number:'1.0-2' }}
                    </span>
                  }
                }
              </div>
              @if (item.fully_issued) {
                <span class="item-card__chip item-card__chip--info">
                  <mat-icon aria-hidden="true">task_alt</mat-icon>
                  Already Issued
                </span>
              }
              @if (isItemOverridden(item.item_id)) {
                <span class="item-card__chip item-card__chip--info">
                  <mat-icon aria-hidden="true">swap_horiz</mat-icon>
                  Different warehouse
                </span>
              }
              @if (store().isRuleBypassedForItem(item.item_id)) {
                <span class="item-card__chip item-card__chip--warn">
                  <mat-icon aria-hidden="true">policy</mat-icon>
                  Rule Bypass
                </span>
              }
            </div>
          </div>
        </button>
      }

      @if (items().length > 0) {
        <footer class="item-list__progress">
          <div class="item-list__progress-copy">
            <strong
              id="item-list-progress-label"
              role="status"
              aria-live="polite"
              aria-atomic="true">
              {{ resolvedCount() }} of {{ items().length }} items resolved
            </strong>
          </div>
          <div
            class="item-list__progress-bar"
            role="progressbar"
            aria-labelledby="item-list-progress-label"
            [attr.aria-valuenow]="resolvedCount()"
            [attr.aria-valuemin]="0"
            [attr.aria-valuemax]="items().length"
            [attr.aria-valuetext]="resolvedCount() + ' of ' + items().length + ' items resolved'">
            <div
              class="item-list__progress-fill"
              [style.width.%]="progressPercent()">
            </div>
          </div>
        </footer>
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
      display: block;
      padding: 8px 10px;
      border-radius: 8px;
      border: 1px solid rgba(55, 53, 47, 0.14);
      background: #ffffff;
      box-shadow: 0 1px 3px rgba(55, 53, 47, 0.06);
      text-align: left;
      cursor: pointer;
      transition: border-color 180ms ease, box-shadow 180ms ease, background-color 180ms ease;
      font: inherit;
      color: inherit;
      width: 100%;
    }

    @media (prefers-reduced-motion: reduce) {
      .item-card {
        transition: none;
      }
    }

    .item-card:hover {
      border-color: rgba(55, 53, 47, 0.28);
      box-shadow: 0 2px 6px rgba(55, 53, 47, 0.1);
    }

    .item-card:focus-visible {
      outline: 2px solid var(--color-focus, #1d4ed8);
      outline-offset: 2px;
    }

    .item-card--selected {
      border-color: var(--color-text-primary, #37352F);
      background: #f2f1ee;
      box-shadow: 0 2px 8px rgba(55, 53, 47, 0.14);
    }

    .item-card--issued {
      background: #f6f8fc;
      border-color: rgba(37, 99, 235, 0.28);
    }

    .item-card--issued.item-card--selected {
      background: #eef4fc;
    }

    .item-card--issued .item-card__name {
      color: #17447f;
    }

    .item-card__row {
      display: flex;
      align-items: flex-start;
      gap: 10px;
    }

    .item-card__status {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;
      width: 18px;
      height: 18px;
      margin-top: 1px;
      border-radius: 50%;
      color: var(--color-text-secondary);
    }

    .item-card__status mat-icon {
      font-size: 18px;
      width: 18px;
      height: 18px;
      line-height: 18px;
    }

    .item-card__status[data-status='filled'] {
      color: var(--color-ok, #166534);
    }

    .item-card__status[data-status='compliant_partial'] {
      color: var(--color-info, #1e3a8a);
    }

    .item-card__status[data-status='non_compliant'],
    .item-card__status[data-status='no_stock'] {
      color: var(--color-danger, #b91c1c);
    }

    .item-card__body {
      display: flex;
      flex-direction: column;
      gap: 2px;
      flex: 1 1 auto;
      min-width: 0;
    }

    .item-card__header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 6px;
    }

    .item-card__name {
      font-size: 0.85rem;
      font-weight: var(--weight-semibold);
      color: var(--color-text-primary);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
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
      flex-shrink: 0;
    }

    .item-card__badge[data-rule='FEFO'] {
      background: var(--color-bg-info, #eff6ff);
      color: var(--color-info, #1e3a8a);
    }

    .item-card__badge[data-rule='FIFO'] {
      background: #eef0ff;
      color: var(--color-accent, #4f46e5);
    }

    .item-card__code {
      font-size: 0.76rem;
      color: var(--color-text-secondary);
      font-variant-numeric: tabular-nums;
    }

    .item-card__meta {
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 4px;
      margin-top: 2px;
      font-size: 0.76rem;
      color: var(--color-text-secondary);
      font-variant-numeric: tabular-nums;
    }

    .item-card__meta-part--issued {
      color: var(--color-info, #17447f);
    }

    .item-card__meta-part--alert {
      color: var(--color-danger, #b91c1c);
      font-weight: var(--weight-semibold);
    }

    .item-card__meta-sep {
      color: rgba(55, 53, 47, 0.35);
    }

    .item-card__chip {
      display: inline-flex;
      align-items: center;
      gap: 3px;
      margin-top: 3px;
      font-size: 0.65rem;
    }

    .item-card__chip mat-icon {
      font-size: 13px;
      width: 13px;
      height: 13px;
      line-height: 13px;
    }

    .item-card__chip--info {
      color: var(--color-info, #17447f);
    }

    .item-card__chip--warn {
      color: var(--color-warning-text, #6e4200);
    }

    .item-list__progress {
      margin-top: 6px;
      padding: 8px 10px;
      border-radius: 8px;
      background: #ffffff;
      border: 1px solid rgba(55, 53, 47, 0.12);
      display: flex;
      flex-direction: column;
      gap: 6px;
    }

    .item-list__progress-copy {
      font-size: 0.72rem;
      color: var(--color-text-secondary);
    }

    .item-list__progress-copy strong {
      color: var(--color-text-primary);
      font-weight: var(--weight-semibold);
    }

    .item-list__progress-bar {
      height: 4px;
      border-radius: var(--radius-pill, 999px);
      background: rgba(55, 53, 47, 0.08);
      overflow: hidden;
    }

    .item-list__progress-fill {
      height: 100%;
      background: var(--color-ok, #166534);
      transition: width 240ms ease;
    }

    @media (prefers-reduced-motion: reduce) {
      .item-list__progress-fill {
        transition: none;
      }
    }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FulfillmentItemListComponent {
  readonly items = input.required<AllocationItemGroup[]>();
  readonly selectedItemId = input<number | null>(null);
  readonly store = input.required<OperationsWorkspaceStateService>();
  readonly itemSelected = output<number>();

  readonly resolvedCount = computed(() => {
    const store = this.store();
    return this.items().reduce((count, item) => {
      if (item.fully_issued) {
        return count + 1;
      }
      const status = store.getItemFillStatus(item.item_id);
      // "Resolved" = the operator has made a compliant decision for this item.
      // `filled` and `compliant_partial` both count as resolved (explicit,
      // compliant plans). `non_compliant` requires an override reason and is
      // NOT counted as resolved here. `draft` is untouched.
      if (status === 'filled' || status === 'compliant_partial') {
        return count + 1;
      }
      return count;
    }, 0);
  });

  readonly progressPercent = computed(() => {
    const total = this.items().length;
    if (total === 0) {
      return 0;
    }
    return Math.round((this.resolvedCount() / total) * 100);
  });

  isItemOverridden(itemId: number): boolean {
    const defaultWarehouseId = this.items().find((item) => item.item_id === itemId)?.source_warehouse_id;
    if (defaultWarehouseId == null) {
      return false;
    }
    return this.store().effectiveWarehouseForItem(itemId) !== String(defaultWarehouseId);
  }

  reservingFor(itemId: number): number {
    return this.store().getSelectedTotalForItem(itemId);
  }

  statusView(item: AllocationItemGroup): ItemStatusView {
    const store = this.store();
    if (item.fully_issued) {
      return {
        status: 'filled',
        icon: 'check_circle',
        iconLabel: 'Already issued',
      };
    }

    const availabilityIssue = store.getItemAvailabilityIssue(item);
    if (availabilityIssue && availabilityIssue.kind === 'no-candidates') {
      return {
        status: 'no_stock',
        icon: 'error',
        iconLabel: 'No stock available',
      };
    }

    const fillStatus = store.getItemFillStatus(item.item_id);
    switch (fillStatus) {
      case 'filled':
        return {
          status: 'filled',
          icon: 'check_circle',
          iconLabel: 'Fully covered',
        };
      case 'compliant_partial':
        return {
          status: 'compliant_partial',
          icon: 'schedule',
          iconLabel: 'Compliant partial allocation',
        };
      case 'non_compliant':
        return {
          status: 'non_compliant',
          icon: 'error',
          iconLabel: 'Non-compliant — reason required',
        };
      case 'draft':
      default:
        return {
          status: 'draft',
          icon: 'radio_button_unchecked',
          iconLabel: 'Not yet allocated',
        };
    }
  }
}
