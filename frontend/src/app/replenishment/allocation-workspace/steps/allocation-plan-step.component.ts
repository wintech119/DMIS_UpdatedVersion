import { DatePipe, DecimalPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, Input, computed, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatIconModule } from '@angular/material/icon';

import { AllocationCandidate } from '../../models/allocation-dispatch.model';
import { ExecutionWorkspaceStateService } from '../../execution/services/execution-workspace-state.service';
import { formatSourceType } from '../../execution/execution-status.util';

const COMPLIANCE_LABELS: Record<string, string> = {
  donation_source: 'Donation source',
  transfer_source: 'Transfer source',
  fifo: 'FIFO recommended',
  fefo: 'FEFO recommended',
  allocation_order_override: 'Order override',
  insufficient_on_hand_stock: 'Insufficient compliant stock',
};

@Component({
  selector: 'app-allocation-plan-step',
  standalone: true,
  imports: [
    DatePipe,
    DecimalPipe,
    FormsModule,
    MatButtonModule,
    MatCardModule,
    MatIconModule,
  ],
  template: `
    <div class="execution-step">
      <div class="execution-step__intro">
        <h2>Stock-Aware Selection</h2>
        <p>
          Use the sorted stock lines below to reserve inventory. The system orders batches by FEFO or FIFO when
          available. Any bypass stays visible and will require an override note before submission.
        </p>
      </div>

      @if (readOnly) {
        <div class="execution-alert execution-alert--info" role="status">
          <mat-icon aria-hidden="true">lock</mat-icon>
          <span>
            This reservation plan is pending override approval. Stock line edits are locked so the
            submitted plan stays visible exactly as routed.
          </span>
        </div>
      }

      @if (store.optionsError(); as optionsError) {
        <div class="execution-alert execution-alert--warning" role="status">
          <mat-icon aria-hidden="true">warning</mat-icon>
          <span>{{ optionsError }}</span>
        </div>
      }

      @for (item of items(); track item.item_id) {
        <mat-card class="execution-item-card">
          <div class="execution-item-card__header">
            <div class="execution-item-card__identity">
              <span class="execution-item-card__eyebrow">Line {{ item.needs_list_item_id }}</span>
              <h3>{{ item.item_name || ('Item ' + item.item_id) }}</h3>
              <p>
                {{ item.item_code || ('Item ID ' + item.item_id) }}
                <span class="execution-separator">-</span>
                {{ item.item_uom_code || 'Units' }}
              </p>
            </div>
            <div class="execution-item-card__badges">
              <span class="execution-badge execution-badge--criticality">
                {{ item.criticality_level || 'NORMAL' }}
              </span>
              <span class="execution-badge execution-badge--method" [attr.data-rule]="item.issuance_order">
                {{ item.issuance_order }}
              </span>
              @if (store.isRuleBypassedForItem(item.item_id)) {
                <span class="execution-badge execution-badge--warning">Rule Bypass Visible</span>
              }
            </div>
          </div>

          <div class="execution-metric-grid">
            <div class="execution-metric">
              <span class="execution-metric__label">Required</span>
              <span class="execution-metric__value">{{ item.required_qty | number:'1.0-4' }}</span>
            </div>
            <div class="execution-metric">
              <span class="execution-metric__label">Fulfilled</span>
              <span class="execution-metric__value">{{ item.fulfilled_qty | number:'1.0-4' }}</span>
            </div>
            <div class="execution-metric">
              <span class="execution-metric__label">Already Reserved</span>
              <span class="execution-metric__value">{{ item.reserved_qty | number:'1.0-4' }}</span>
            </div>
            <div class="execution-metric">
              <span class="execution-metric__label">Still To Cover</span>
              <span class="execution-metric__value">{{ item.remaining_qty | number:'1.0-4' }}</span>
            </div>
            <div class="execution-metric">
              <span class="execution-metric__label">Selected Now</span>
              <span class="execution-metric__value">{{ store.getSelectedTotalForItem(item.item_id) | number:'1.0-4' }}</span>
            </div>
            <div class="execution-metric">
              <span class="execution-metric__value" [class.execution-metric__value--warning]="store.getUncoveredQtyForItem(item.item_id) > 0">
                {{ store.getUncoveredQtyForItem(item.item_id) | number:'1.0-4' }}
              </span>
              <span class="execution-metric__label">Uncovered After This Step</span>
            </div>
          </div>

          <div class="execution-guidance">
            <div>
              <strong>Suggested reservation plan</strong>
              <p>
                The backend recommends
                {{ item.suggested_allocations.length || 0 }}
                stock line{{ item.suggested_allocations.length === 1 ? '' : 's' }}
                for this item.
              </p>
            </div>
            <button
              mat-stroked-button
              type="button"
              [disabled]="readOnly"
              (click)="store.useSuggestedPlan(item.item_id)">
              <mat-icon aria-hidden="true">restart_alt</mat-icon>
              Use Suggested Plan
            </button>
          </div>

          <div class="execution-candidate-table desktop-only">
            <table>
              <thead>
                <tr>
                  <th>Batch / Lot</th>
                  <th>Source</th>
                  <th>Batch Date</th>
                  <th>Expiry</th>
                  <th>Available</th>
                  <th>Reserved</th>
                  <th>Qty To Reserve</th>
                </tr>
              </thead>
              <tbody>
                @for (candidate of item.candidates; track candidate.inventory_id + '-' + candidate.batch_id + '-' + candidate.source_type) {
                  <tr [class.execution-row--selected]="store.getSelectedQtyForCandidate(item.item_id, candidate) > 0">
                    <td>
                      <div class="execution-batch-cell">
                        <strong>{{ candidate.batch_no || ('Batch ' + candidate.batch_id) }}</strong>
                        <span>{{ candidate.warehouse_name || ('Inventory ' + candidate.inventory_id) }}</span>
                        @if (candidate.compliance_markers?.length) {
                          <div class="execution-marker-list">
                            @for (marker of candidate.compliance_markers; track marker) {
                              <span class="execution-marker-chip">{{ formatMarker(marker) }}</span>
                            }
                          </div>
                        }
                      </div>
                    </td>
                    <td>{{ formatSource(candidate.source_type) }}</td>
                    <td>{{ candidate.batch_date ? (candidate.batch_date | date:'mediumDate') : 'N/A' }}</td>
                    <td>{{ candidate.expiry_date ? (candidate.expiry_date | date:'mediumDate') : 'N/A' }}</td>
                    <td>{{ candidate.available_qty | number:'1.0-4' }}</td>
                    <td>{{ candidate.reserved_qty | number:'1.0-4' }}</td>
                    <td>
                      <input
                        class="execution-qty-input"
                        type="number"
                        min="0"
                        step="0.0001"
                        [disabled]="readOnly"
                        [ngModel]="store.getSelectedQtyForCandidate(item.item_id, candidate)"
                        (ngModelChange)="onQuantityChange(item.item_id, candidate, $event)"
                      />
                    </td>
                  </tr>
                }
              </tbody>
            </table>
          </div>

          <div class="mobile-only execution-candidate-cards">
            @for (candidate of item.candidates; track candidate.inventory_id + '-' + candidate.batch_id + '-' + candidate.source_type) {
              <div class="execution-candidate-card">
                <div class="execution-candidate-card__header">
                  <strong>{{ candidate.batch_no || ('Batch ' + candidate.batch_id) }}</strong>
                  <span class="execution-badge execution-badge--source">{{ formatSource(candidate.source_type) }}</span>
                </div>
                <div class="execution-candidate-card__body">
                  <div class="execution-candidate-card__field">
                    <span>Available</span>
                    <strong>{{ candidate.available_qty | number:'1.0-4' }}</strong>
                  </div>
                  <div class="execution-candidate-card__field">
                    <span>Reserved</span>
                    <strong>{{ candidate.reserved_qty | number:'1.0-4' }}</strong>
                  </div>
                  <div class="execution-candidate-card__field">
                    <span>Batch Date</span>
                    <strong>{{ candidate.batch_date ? (candidate.batch_date | date:'mediumDate') : 'N/A' }}</strong>
                  </div>
                  <div class="execution-candidate-card__field">
                    <span>Expiry</span>
                    <strong>{{ candidate.expiry_date ? (candidate.expiry_date | date:'mediumDate') : 'N/A' }}</strong>
                  </div>
                </div>
                <label class="execution-candidate-card__input">
                  <span>Qty To Reserve</span>
                  <input
                    class="execution-qty-input"
                    type="number"
                    min="0"
                    step="0.0001"
                    [disabled]="readOnly"
                    [ngModel]="store.getSelectedQtyForCandidate(item.item_id, candidate)"
                    (ngModelChange)="onQuantityChange(item.item_id, candidate, $event)"
                  />
                </label>
              </div>
            }
          </div>

          @if (store.getItemValidationMessage(item); as validationMessage) {
            <p class="execution-validation" role="alert">
              <mat-icon aria-hidden="true">error</mat-icon>
              {{ validationMessage }}
            </p>
          }

          @if (store.isRuleBypassedForItem(item.item_id)) {
            <p class="execution-override-note" role="status">
              <mat-icon aria-hidden="true">policy</mat-icon>
              This line no longer matches the backend's {{ item.issuance_order }} recommendation. Submit an override
              reason in the next step so the bypass remains visible for supervisor review.
            </p>
          }
        </mat-card>
      }
    </div>
  `,
  styles: [`
    :host {
      display: block;
    }

    .execution-step {
      display: flex;
      flex-direction: column;
      gap: 18px;
    }

    .execution-step__intro h2 {
      margin: 0 0 6px;
      font-size: var(--text-lg);
      font-weight: var(--weight-semibold);
    }

    .execution-step__intro p {
      margin: 0;
      color: var(--color-text-secondary);
    }

    .execution-alert {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 12px 14px;
      border-radius: 10px;
      border-left: 4px solid var(--color-warning);
      background: var(--color-bg-warning);
      color: var(--color-watch);
    }

    .execution-alert--info {
      border-left-color: var(--color-focus-ring);
      background: var(--color-bg-info);
      color: var(--color-info);
    }

    .execution-item-card {
      border: 1px solid var(--color-border);
      box-shadow: none;
    }

    .execution-item-card__header,
    .execution-guidance {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 16px;
    }

    .execution-item-card__identity h3 {
      margin: 0;
      font-size: var(--text-md);
      font-weight: var(--weight-semibold);
    }

    .execution-item-card__identity p,
    .execution-item-card__identity .execution-item-card__eyebrow {
      margin: 0;
      color: var(--color-text-secondary);
      font-size: var(--text-sm);
    }

    .execution-item-card__eyebrow {
      display: inline-block;
      margin-bottom: 6px;
      text-transform: uppercase;
      letter-spacing: var(--tracking-wide);
    }

    .execution-item-card__badges {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      justify-content: flex-end;
    }

    .execution-badge {
      display: inline-flex;
      align-items: center;
      padding: 4px 10px;
      border-radius: var(--radius-pill);
      font-size: var(--text-sm);
      font-weight: var(--weight-semibold);
      background: var(--color-surface-muted);
      color: var(--color-text-primary);
    }

    .execution-badge--warning {
      background: var(--color-bg-warning);
      color: var(--color-watch);
    }

    .execution-badge--method[data-rule='FEFO'] {
      background: var(--color-bg-info);
      color: var(--color-info);
    }

    .execution-badge--method[data-rule='FIFO'] {
      background: color-mix(in srgb, var(--color-accent) 12%, white);
      color: var(--color-accent);
    }

    .execution-metric-grid {
      display: grid;
      grid-template-columns: repeat(6, minmax(0, 1fr));
      gap: 12px;
      margin: 16px 0;
    }

    .execution-metric {
      padding: 12px;
      border-radius: 10px;
      background: var(--color-surface-muted);
      border: 1px solid var(--color-border);
    }

    .execution-metric__label {
      display: block;
      margin-top: 6px;
      color: var(--color-text-secondary);
      font-size: var(--text-sm);
    }

    .execution-metric__value {
      display: block;
      font-size: var(--text-md);
      font-weight: var(--weight-semibold);
      font-variant-numeric: tabular-nums;
    }

    .execution-metric__value--warning {
      color: var(--color-warning);
    }

    .execution-guidance {
      margin-bottom: 16px;
      padding: 14px;
      border-radius: 12px;
      background: color-mix(in srgb, var(--color-accent) 8%, white);
      border: 1px solid color-mix(in srgb, var(--color-accent) 20%, white);
    }

    .execution-guidance p {
      margin: 4px 0 0;
      color: var(--color-text-secondary);
    }

    .execution-candidate-table {
      overflow-x: auto;
      border-radius: 10px;
      border: 1px solid var(--color-border);
      margin-bottom: 12px;
    }

    .execution-candidate-table table {
      width: 100%;
      border-collapse: collapse;
    }

    .execution-candidate-table th,
    .execution-candidate-table td {
      padding: 10px 12px;
      border-bottom: 1px solid var(--color-border);
      text-align: left;
      vertical-align: top;
    }

    .execution-candidate-table th {
      background: var(--color-surface-muted);
      color: var(--color-text-secondary);
      font-size: var(--text-sm);
      font-weight: var(--weight-semibold);
    }

    .execution-row--selected {
      background: color-mix(in srgb, var(--color-success) 8%, white);
    }

    .execution-batch-cell {
      display: flex;
      flex-direction: column;
      gap: 4px;
    }

    .execution-batch-cell span {
      color: var(--color-text-secondary);
      font-size: var(--text-sm);
    }

    .execution-marker-list {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }

    .execution-marker-chip {
      padding: 2px 8px;
      border-radius: var(--radius-pill);
      background: var(--color-bg-info);
      color: var(--color-info);
      font-size: var(--text-xs);
      font-weight: var(--weight-medium);
    }

    .execution-qty-input {
      width: 100%;
      max-width: 120px;
      padding: 8px 10px;
      border: 1px solid var(--color-border);
      border-radius: 8px;
      font: inherit;
      font-variant-numeric: tabular-nums;
    }

    .execution-candidate-cards {
      display: none;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 12px;
      margin-bottom: 12px;
    }

    .execution-candidate-card {
      padding: 12px;
      border-radius: 10px;
      border: 1px solid var(--color-border);
      background: var(--color-surface-muted);
    }

    .execution-candidate-card__header,
    .execution-candidate-card__field,
    .execution-candidate-card__input {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }

    .execution-candidate-card__body {
      display: grid;
      gap: 8px;
      margin: 12px 0;
    }

    .execution-candidate-card__field span,
    .execution-candidate-card__input span {
      color: var(--color-text-secondary);
      font-size: var(--text-sm);
    }

    .execution-validation,
    .execution-override-note {
      display: flex;
      align-items: flex-start;
      gap: 10px;
      margin: 12px 0 0;
      padding: 12px 14px;
      border-radius: 10px;
      font-size: var(--text-sm);
    }

    .execution-validation {
      background: var(--color-bg-critical);
      color: var(--color-critical);
      border-left: 4px solid var(--color-critical);
    }

    .execution-override-note {
      background: var(--color-bg-warning);
      color: var(--color-watch);
      border-left: 4px solid var(--color-warning);
    }

    .desktop-only {
      display: block;
    }

    .mobile-only {
      display: none;
    }

    .execution-separator {
      padding: 0 6px;
      color: var(--color-text-tertiary);
    }

    @media (max-width: 1100px) {
      .execution-metric-grid {
        grid-template-columns: repeat(3, minmax(0, 1fr));
      }
    }

    @media (max-width: 768px) {
      .execution-item-card__header,
      .execution-guidance {
        flex-direction: column;
      }

      .execution-item-card__badges {
        justify-content: flex-start;
      }

      .execution-metric-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }

      .desktop-only {
        display: none;
      }

      .mobile-only {
        display: grid;
      }
    }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AllocationPlanStepComponent {
  @Input() readOnly = false;

  readonly store = inject(ExecutionWorkspaceStateService);
  readonly items = computed(() => this.store.options()?.items ?? []);

  onQuantityChange(itemId: number, candidate: AllocationCandidate, value: number | string): void {
    const parsed = Number.parseFloat(String(value ?? '0'));
    this.store.setCandidateQuantity(itemId, candidate, Number.isFinite(parsed) ? parsed : 0);
  }

  formatMarker(marker: string): string {
    return COMPLIANCE_LABELS[marker] ?? marker.replace(/_/g, ' ');
  }

  formatSource(sourceType: string): string {
    return formatSourceType(sourceType);
  }
}
