import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  Input,
  ViewChild,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { catchError, of } from 'rxjs';

import { LookupItem } from '../../../master-data/models/master-data.models';
import { MasterDataService } from '../../../master-data/services/master-data.service';
import { OperationsWorkspaceStateService } from '../../services/operations-workspace-state.service';
import { FulfillmentItemListComponent } from './fulfillment-item-list.component';
import { FulfillmentItemDetailComponent } from './fulfillment-item-detail.component';
import { OpsSourceWarehousePickerComponent } from '../../shared/ops-source-warehouse-picker.component';
import { OpsStockAvailabilityStateComponent } from '../../shared/ops-stock-availability-state.component';

@Component({
  selector: 'app-fulfillment-plan-step',
  standalone: true,
  imports: [
    MatButtonModule,
    MatIconModule,
    FulfillmentItemListComponent,
    FulfillmentItemDetailComponent,
    OpsSourceWarehousePickerComponent,
    OpsStockAvailabilityStateComponent,
  ],
  template: `
    <div class="plan-step">
      <h2 class="plan-step__title">Stock-Aware Selection</h2>
      <div class="plan-step__intro">
        <p>
          Select an item on the left, then use the warehouse stock lines on the right to reserve
          inventory. The system orders batches by FEFO or FIFO when available.
        </p>
      </div>

      @if (readOnly) {
        <div class="plan-alert plan-alert--info" role="status">
          <mat-icon aria-hidden="true">lock</mat-icon>
          <span>
            This reservation plan is pending override approval. Stock line edits are locked so the
            submitted plan stays visible exactly as routed.
          </span>
        </div>
      }

      @if (store.optionsError() && !requestAvailabilityIssue()) {
        <div class="plan-alert plan-alert--warning" role="status">
          <mat-icon aria-hidden="true">warning</mat-icon>
          <span>{{ store.optionsError() }}</span>
        </div>
      }

      @if (showSourceWarehousePicker()) {
        <app-ops-source-warehouse-picker
          class="plan-step__warehouse"
          [warehouseOptions]="warehouseOptions()"
          [selectedId]="sourceWarehouseId()"
          [overrideCount]="warehouseOverrideCount()"
          [itemCount]="items().length"
          [disabled]="readOnly || store.loading() || store.submitting()"
          (warehouseChange)="onSourceWarehouseChange($event)"
          (clearOverrides)="resetWarehouseOverrides()"
        />
      }

      <div class="plan-split">
        @if (items().length) {
          <app-fulfillment-item-list
            [items]="items()"
            [selectedItemId]="selectedItemId()"
            [store]="store"
            (itemSelected)="onItemSelected($event)"
          />
        } @else {
          <div class="plan-list-empty" role="status">
            <mat-icon aria-hidden="true">inventory_2</mat-icon>
            <p>No item-level stock lines are available to review yet.</p>
          </div>
        }

        @if (selectedItem(); as item) {
          <div #detailPanel class="plan-split__detail" tabindex="-1"
            [class.plan-split__detail--switching]="store.switching()">
            @if (store.switching()) {
              <div class="plan-shimmer" aria-live="polite" aria-label="Refreshing item stock data"></div>
            }
            <app-fulfillment-item-detail
              [item]="item"
              [readOnly]="readOnly"
              [store]="store"
              (back)="clearSelection()"
            />
          </div>
        } @else if (requestAvailabilityIssue(); as issue) {
          <app-ops-stock-availability-state
            class="plan-split__detail"
            [kind]="issue.kind"
            [scope]="issue.scope"
            [detail]="issue.detail ?? null" />
        } @else {
          <div class="plan-empty">
            <mat-icon aria-hidden="true">touch_app</mat-icon>
            <p>Select an item from the list to view available warehouses and stock lines.</p>
          </div>
        }
      </div>
    </div>
  `,
  styles: [`
    :host {
      display: block;
    }

    .plan-step {
      display: flex;
      flex-direction: column;
      gap: 10px;
    }

    .plan-step__title {
      margin: 0;
      font-size: var(--text-lg);
      font-weight: var(--weight-semibold);
    }

    .plan-step__intro {
      padding: 8px 12px;
      border-radius: 8px;
      border: 1px solid rgba(55, 53, 47, 0.14);
      background: #ffffff;
      box-shadow: 0 1px 3px rgba(55, 53, 47, 0.06);
    }

    .plan-step__intro p {
      margin: 0;
      font-size: 0.82rem;
      color: var(--color-text-secondary);
    }

    .plan-alert {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 12px 14px;
      border-radius: 10px;
      border-left: 4px solid var(--color-warning);
      background: var(--color-bg-warning);
      color: var(--color-watch);
    }

    .plan-alert--info {
      border-left-color: var(--color-focus-ring);
      background: var(--color-bg-info);
      color: var(--color-info);
    }

    .plan-split {
      display: grid;
      grid-template-columns: minmax(220px, 0.7fr) minmax(0, 1.8fr);
      gap: 20px;
      align-items: start;
    }

    .plan-step__warehouse {
      margin-bottom: 2px;
    }

    .plan-split__detail:focus {
      outline: none;
    }

    .plan-split__detail {
      position: relative;
      transition: opacity 180ms ease;
    }

    .plan-split__detail--switching {
      opacity: 0.5;
      pointer-events: none;
    }

    .plan-shimmer {
      position: absolute;
      inset: 0;
      z-index: 1;
      border-radius: 8px;
      background: linear-gradient(
        90deg,
        rgba(255, 255, 255, 0) 0%,
        rgba(255, 255, 255, 0.5) 50%,
        rgba(255, 255, 255, 0) 100%
      );
      background-size: 200% 100%;
      animation: shimmer-slide 1.2s ease-in-out infinite;
    }

    @keyframes shimmer-slide {
      0% { background-position: 200% 0; }
      100% { background-position: -200% 0; }
    }

    @media (prefers-reduced-motion: reduce) {
      .plan-split__detail {
        transition: none;
      }
      .plan-shimmer {
        animation: none;
        background: rgba(255, 255, 255, 0.4);
      }
    }

    .plan-list-empty,
    .plan-empty {
      display: grid;
      place-items: center;
      gap: 8px;
      padding: 3rem 1.5rem;
      border-radius: 12px;
      border: 1px dashed #d5d5d2;
      background: var(--color-surface-muted, #fafaf9);
      text-align: center;
      color: var(--color-text-secondary);
    }

    .plan-list-empty {
      min-height: 16rem;
    }

    .plan-list-empty mat-icon,
    .plan-empty mat-icon {
      font-size: 32px;
      width: 32px;
      height: 32px;
      opacity: 0.5;
    }

    .plan-empty p {
      margin: 0;
      max-width: 28rem;
    }

    @media (max-width: 900px) {
      .plan-split {
        grid-template-columns: 1fr;
      }
    }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FulfillmentPlanStepComponent {
  @Input() readOnly = false;
  @ViewChild('detailPanel', { read: ElementRef }) detailPanel?: ElementRef<HTMLElement>;

  private readonly masterData = inject(MasterDataService);
  readonly store = inject(OperationsWorkspaceStateService);
  readonly warehouseOptions = toSignal(
    this.masterData.lookup('warehouses').pipe(catchError(() => of([] as LookupItem[]))),
    { initialValue: [] },
  );
  readonly items = computed(() => this.store.options()?.items ?? []);
  readonly requestAvailabilityIssue = this.store.requestAvailabilityIssue;
  readonly selectedItemId = signal<number | null>(null);
  readonly selectionCleared = signal(false);
  readonly sourceWarehouseId = this.store.sourceWarehouseId;
  readonly warehouseOverrideCount = computed(
    () => Object.keys(this.store.itemWarehouseOverrides()).length,
  );
  readonly showSourceWarehousePicker = computed(() =>
    this.requestAvailabilityIssue()?.kind === 'missing-warehouse'
    && (this.warehouseOptions() ?? []).length > 0,
  );

  readonly selectedItem = computed(() => {
    const id = this.selectedItemId();
    if (id == null) return null;
    return this.items().find((i) => i.item_id === id) ?? null;
  });

  constructor() {
    effect(() => {
      const list = this.items();
      const current = this.selectedItemId();
      const keepListVisible = this.selectionCleared();
      if (list.length && current == null && !keepListVisible) {
        this.selectedItemId.set(list[0].item_id);
      } else if (current != null && !list.some((i) => i.item_id === current)) {
        this.selectionCleared.set(false);
        this.selectedItemId.set(list.length ? list[0].item_id : null);
      }
    });
  }

  onItemSelected(itemId: number): void {
    this.selectionCleared.set(false);
    this.selectedItemId.set(itemId);
    queueMicrotask(() => this.detailPanel?.nativeElement?.focus());
  }

  clearSelection(): void {
    this.selectionCleared.set(true);
    this.selectedItemId.set(null);
  }

  onSourceWarehouseChange(sourceWarehouseId: string): void {
    this.store.updateSourceWarehouse(sourceWarehouseId);
  }

  resetWarehouseOverrides(): void {
    const sourceWarehouseId = this.sourceWarehouseId();
    if (!sourceWarehouseId) {
      return;
    }
    this.store.resetWarehouseOverrides();
  }
}
