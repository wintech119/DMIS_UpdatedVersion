import { DecimalPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, Input, computed, inject } from '@angular/core';
import { MatCardModule } from '@angular/material/card';
import { MatIconModule } from '@angular/material/icon';

import { AllocationCandidate, AllocationSelectionPayload } from '../../models/allocation-dispatch.model';
import { ExecutionWorkspaceStateService } from '../../execution/services/execution-workspace-state.service';
import { formatExecutionMethod, formatExecutionStatus, formatSourceType } from '../../execution/execution-status.util';

interface ReviewGroup {
  itemId: number;
  itemName: string;
  itemCode: string;
  uomCode: string;
  selectedQty: number;
  rows: AllocationSelectionPayload[];
}

@Component({
  selector: 'app-allocation-review-step',
  standalone: true,
  imports: [
    DecimalPipe,
    MatCardModule,
    MatIconModule,
  ],
  template: `
    <div class="review-step">
      <div class="review-step__intro">
        <h2>Review Reservation</h2>
        <p>
          Confirm the stock lines, tracking references, and rule-bypass visibility before the reservation is committed.
          Stock is deducted only when dispatch is recorded later.
        </p>
      </div>

      @if (submissionErrors.length) {
        <div class="review-alert review-alert--error" role="alert">
          <mat-icon aria-hidden="true">error</mat-icon>
          <div>
            <strong>Resolve these items before continuing:</strong>
            <ul>
              @for (error of submissionErrors; track error) {
                <li>{{ error }}</li>
              }
            </ul>
          </div>
        </div>
      }

      @if (store.planRequiresOverride() && !store.hasPendingOverride()) {
        <div class="review-alert review-alert--warning" role="status">
          <mat-icon aria-hidden="true">policy</mat-icon>
          <span>
            This selection bypasses the backend recommendation. The reservation will route for narrow override approval
            before dispatch can continue.
          </span>
        </div>
      }

      @if (store.hasPendingOverride()) {
        <div class="review-alert review-alert--warning" role="status">
          <mat-icon aria-hidden="true">pending_actions</mat-icon>
          <span>
            Override approval is still pending. Dispatch stays blocked until an authorized approver completes that
            review.
          </span>
        </div>
      }

      @if (overrideApprovalHint) {
        <div class="review-alert review-alert--info" role="status">
          <mat-icon aria-hidden="true">visibility</mat-icon>
          <span>{{ overrideApprovalHint }}</span>
        </div>
      }

      <div class="review-metric-grid">
        <mat-card class="review-metric-card">
          <span class="review-metric-card__label">Reservation State</span>
          <strong>{{ reservationStateLabel() }}</strong>
          <span class="review-metric-card__meta">{{ formatExecutionStatus(current()?.execution_status) }}</span>
        </mat-card>

        <mat-card class="review-metric-card">
          <span class="review-metric-card__label">Selection Method</span>
          <strong>{{ formatExecutionMethod(store.selectedMethod() || current()?.selected_method) }}</strong>
          <span class="review-metric-card__meta">
            {{ store.planRequiresOverride() || store.hasPendingOverride() ? 'Bypass visible' : 'Backend ordered plan' }}
          </span>
        </mat-card>

        <mat-card class="review-metric-card">
          <span class="review-metric-card__label">{{ quantityLabel() }}</span>
          <strong>{{ reservedQuantity() | number:'1.0-4' }}</strong>
          <span class="review-metric-card__meta">
            {{ store.selectedLineCount() }} stock line{{ store.selectedLineCount() === 1 ? '' : 's' }}
          </span>
        </mat-card>

        <mat-card class="review-metric-card">
          <span class="review-metric-card__label">Tracking References</span>
          <strong>{{ current()?.request_tracking_no || 'Created on commit' }}</strong>
          <span class="review-metric-card__meta">
            Package {{ current()?.package_tracking_no || 'Created on commit' }}
          </span>
        </mat-card>
      </div>

      <mat-card class="review-section">
        <div class="review-section__header">
          <div>
            <h3>Reference Summary</h3>
            <p>Request, package, and dispatch-document references stay visible as the workflow moves forward.</p>
          </div>
        </div>

        <div class="reference-grid">
          <div class="reference-card">
            <span>Request Tracking Number</span>
            <strong>{{ current()?.request_tracking_no || 'Will be generated on first commit' }}</strong>
          </div>
          <div class="reference-card">
            <span>Package Tracking Number</span>
            <strong>{{ current()?.package_tracking_no || 'Will be generated on first commit' }}</strong>
          </div>
          <div class="reference-card">
            <span>Dispatch Document Reference</span>
            <strong>{{ current()?.waybill_no || 'Assigned on dispatch' }}</strong>
          </div>
          <div class="reference-card">
            <span>Deduction Rule</span>
            <strong>Inventory deducts only on dispatch</strong>
          </div>
        </div>
      </mat-card>

      <mat-card class="review-section">
        <div class="review-section__header">
          <div>
            <h3>Selected Stock Lines</h3>
            <p>The lines below are the exact reservation candidates that will be saved for this needs list.</p>
          </div>
        </div>

        @if (!reviewGroups().length) {
          <p class="review-empty">No stock lines are selected yet.</p>
        } @else {
          @for (group of reviewGroups(); track group.itemId) {
            <div class="review-group">
              <div class="review-group__header">
                <div>
                  <h4>{{ group.itemName }}</h4>
                  <p>{{ group.itemCode }} - {{ group.uomCode }}</p>
                </div>
                <strong>{{ group.selectedQty | number:'1.0-4' }} reserved</strong>
              </div>

              <div class="review-table-wrap desktop-only">
                <table>
                  <thead>
                    <tr>
                      <th>Batch / Lot</th>
                      <th>Source</th>
                      <th>Warehouse</th>
                      <th>Qty</th>
                    </tr>
                  </thead>
                  <tbody>
                    @for (row of group.rows; track row.inventory_id + '-' + row.batch_id + '-' + row.source_type) {
                      <tr>
                        <td>{{ batchLabel(row) }}</td>
                        <td>{{ formatSource(row.source_type) }}</td>
                        <td>{{ warehouseLabel(row) }}</td>
                        <td>{{ row.quantity | number:'1.0-4' }}</td>
                      </tr>
                    }
                  </tbody>
                </table>
              </div>

              <div class="mobile-only review-mobile-list">
                @for (row of group.rows; track row.inventory_id + '-' + row.batch_id + '-' + row.source_type) {
                  <div class="review-mobile-card">
                    <strong>{{ batchLabel(row) }}</strong>
                    <span>{{ formatSource(row.source_type) }}</span>
                    <span>{{ warehouseLabel(row) }}</span>
                    <strong>{{ row.quantity | number:'1.0-4' }}</strong>
                  </div>
                }
              </div>
            </div>
          }
        }
      </mat-card>

      <mat-card class="review-section">
        <div class="review-section__header">
          <div>
            <h3>Commit Outcome</h3>
            <p>{{ commitOutcomeCopy() }}</p>
          </div>
        </div>
      </mat-card>
    </div>
  `,
  styles: [`
    :host {
      display: block;
    }

    .review-step {
      display: flex;
      flex-direction: column;
      gap: 18px;
    }

    .review-step__intro h2 {
      margin: 0 0 6px;
      font-size: var(--text-lg);
      font-weight: var(--weight-semibold);
    }

    .review-step__intro p,
    .review-section__header p,
    .review-group__header p {
      margin: 0;
      color: var(--color-text-secondary);
    }

    .review-alert {
      display: flex;
      align-items: flex-start;
      gap: 10px;
      padding: 14px 16px;
      border-radius: 12px;
      border-left: 4px solid var(--color-warning);
      background: var(--color-bg-warning);
      color: var(--color-watch);
    }

    .review-alert--info {
      border-left-color: var(--color-focus-ring);
      background: var(--color-bg-info);
      color: var(--color-info);
    }

    .review-alert--error {
      border-left-color: var(--color-critical);
      background: var(--color-bg-critical);
      color: var(--color-critical);
    }

    .review-alert ul {
      margin: 8px 0 0 18px;
      padding: 0;
    }

    .review-metric-grid,
    .reference-grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
    }

    .review-metric-card,
    .reference-card,
    .review-section {
      border: 1px solid var(--color-border);
      box-shadow: none;
    }

    .review-metric-card,
    .reference-card {
      padding: 16px;
      border-radius: 12px;
      background: var(--color-surface);
    }

    .review-metric-card__label,
    .reference-card span {
      display: block;
      margin-bottom: 6px;
      color: var(--color-text-secondary);
      font-size: var(--text-sm);
    }

    .review-metric-card strong,
    .reference-card strong {
      display: block;
      font-size: var(--text-md);
      font-weight: var(--weight-semibold);
    }

    .review-metric-card__meta {
      display: block;
      margin-top: 6px;
      color: var(--color-text-secondary);
      font-size: var(--text-sm);
    }

    .review-section {
      padding: 18px;
      border-radius: 14px;
    }

    .review-section__header {
      margin-bottom: 16px;
    }

    .review-section__header h3,
    .review-group__header h4 {
      margin: 0 0 4px;
      font-size: var(--text-md);
      font-weight: var(--weight-semibold);
    }

    .review-group {
      display: flex;
      flex-direction: column;
      gap: 12px;
    }

    .review-group + .review-group {
      margin-top: 16px;
      padding-top: 16px;
      border-top: 1px solid var(--color-border);
    }

    .review-group__header {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 16px;
    }

    .review-table-wrap {
      overflow-x: auto;
      border: 1px solid var(--color-border);
      border-radius: 10px;
    }

    .review-table-wrap table {
      width: 100%;
      border-collapse: collapse;
    }

    .review-table-wrap th,
    .review-table-wrap td {
      padding: 10px 12px;
      border-bottom: 1px solid var(--color-border);
      text-align: left;
    }

    .review-table-wrap th {
      background: var(--color-surface-muted);
      color: var(--color-text-secondary);
      font-size: var(--text-sm);
      font-weight: var(--weight-semibold);
    }

    .review-mobile-list {
      display: none;
      gap: 10px;
    }

    .review-mobile-card {
      display: grid;
      gap: 4px;
      padding: 12px;
      border-radius: 10px;
      background: var(--color-surface-muted);
      border: 1px solid var(--color-border);
    }

    .review-empty {
      margin: 0;
      color: var(--color-text-secondary);
    }

    .desktop-only {
      display: block;
    }

    .mobile-only {
      display: none;
    }

    @media (max-width: 960px) {
      .review-metric-grid,
      .reference-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
    }

    @media (max-width: 768px) {
      .review-group__header {
        flex-direction: column;
      }

      .desktop-only {
        display: none;
      }

      .mobile-only {
        display: grid;
      }
    }

    @media (max-width: 520px) {
      .review-metric-grid,
      .reference-grid {
        grid-template-columns: 1fr;
      }
    }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AllocationReviewStepComponent {
  @Input() submissionErrors: string[] = [];
  @Input() overrideApprovalHint: string | null = null;
  @Input() canApproveOverride = false;

  readonly store = inject(ExecutionWorkspaceStateService);
  readonly current = this.store.current;

  readonly reviewGroups = computed<ReviewGroup[]>(() => {
    const options = this.store.options()?.items ?? [];
    return options
      .map((item) => {
        const rows = this.store.getSelectedRows(item.item_id).filter((row) => this.toNumber(row.quantity) > 0);
        return {
          itemId: item.item_id,
          itemName: item.item_name || `Item ${item.item_id}`,
          itemCode: item.item_code || `Item ID ${item.item_id}`,
          uomCode: item.item_uom_code || 'Units',
          selectedQty: rows.reduce((sum, row) => sum + this.toNumber(row.quantity), 0),
          rows,
        };
      })
      .filter((group) => group.rows.length > 0);
  });

  reservationStateLabel(): string {
    if (this.store.hasPendingOverride()) {
      return 'Pending override approval';
    }
    if (this.store.hasCommittedAllocation()) {
      return 'Reserved';
    }
    return 'Not reserved yet';
  }

  quantityLabel(): string {
    return this.store.hasCommittedAllocation() ? 'Reserved Quantity' : 'Quantity To Reserve';
  }

  reservedQuantity(): number {
    return this.toNumber(this.current()?.reserved_stock_summary?.total_qty) || this.store.totalSelectedQty();
  }

  batchLabel(row: AllocationSelectionPayload): string {
    const candidate = this.lookupCandidate(row);
    return candidate?.batch_no || `Batch ${row.batch_id}`;
  }

  warehouseLabel(row: AllocationSelectionPayload): string {
    const candidate = this.lookupCandidate(row);
    return candidate?.warehouse_name || `Inventory ${row.inventory_id}`;
  }

  formatSource(sourceType: string): string {
    return formatSourceType(sourceType);
  }

  formatExecutionMethod(value: unknown): string {
    return formatExecutionMethod(String(value ?? ''));
  }

  formatExecutionStatus(value: unknown): string {
    return formatExecutionStatus(String(value ?? ''));
  }

  commitOutcomeCopy(): string {
    if (this.store.hasPendingOverride()) {
      return this.canApproveOverride
        ? 'Approving this override will keep the submitted reservation plan intact and unlock the next dispatch step.'
        : 'This routed reservation is locked while narrow supervisor approval is pending. Dispatch remains blocked until that review is complete.';
    }
    if (this.store.hasCommittedAllocation()) {
      return 'Updating this reservation keeps stock frozen against the request. Physical deduction still happens only on dispatch.';
    }
    return 'Committing this review will freeze stock against the request and create the formal request and package tracking references.';
  }

  private lookupCandidate(row: AllocationSelectionPayload): AllocationCandidate | undefined {
    return this.store
      .options()
      ?.items
      .find((item) => item.item_id === row.item_id)
      ?.candidates
      .find((candidate) =>
        candidate.inventory_id === row.inventory_id
        && candidate.batch_id === row.batch_id
        && String(candidate.source_type).toUpperCase() === String(row.source_type).toUpperCase()
        && (candidate.source_record_id ?? null) === (row.source_record_id ?? null)
      );
  }

  private toNumber(value: string | number | null | undefined): number {
    if (typeof value === 'number') {
      return Number.isFinite(value) ? value : 0;
    }
    const parsed = Number.parseFloat(String(value ?? '0'));
    return Number.isFinite(parsed) ? parsed : 0;
  }
}
