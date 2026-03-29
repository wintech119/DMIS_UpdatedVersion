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
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';

import { OperationsWorkspaceStateService } from '../../services/operations-workspace-state.service';
import { FulfillmentItemListComponent } from './fulfillment-item-list.component';
import { FulfillmentItemDetailComponent } from './fulfillment-item-detail.component';

@Component({
  selector: 'app-fulfillment-plan-step',
  standalone: true,
  imports: [
    MatButtonModule,
    MatIconModule,
    FulfillmentItemListComponent,
    FulfillmentItemDetailComponent,
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

      @if (store.optionsError(); as optionsError) {
        <div class="plan-alert plan-alert--warning" role="status">
          <mat-icon aria-hidden="true">warning</mat-icon>
          <span>{{ optionsError }}</span>
        </div>
      }

      <div class="plan-split">
        <app-fulfillment-item-list
          [items]="items()"
          [selectedItemId]="selectedItemId()"
          [store]="store"
          (itemSelected)="onItemSelected($event)"
        />

        @if (selectedItem(); as item) {
          <div #detailPanel class="plan-split__detail" tabindex="-1">
            <app-fulfillment-item-detail
              [item]="item"
              [readOnly]="readOnly"
              [store]="store"
              (back)="clearSelection()"
            />
          </div>
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

    .plan-split__detail:focus {
      outline: none;
    }

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

  readonly store = inject(OperationsWorkspaceStateService);
  readonly items = computed(() => this.store.options()?.items ?? []);
  readonly selectedItemId = signal<number | null>(null);
  readonly selectionCleared = signal(false);

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
}
