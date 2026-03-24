import { DecimalPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';

import { AllocationCommittedLine } from '../../models/allocation-dispatch.model';
import { ExecutionWorkspaceStateService } from '../../execution/services/execution-workspace-state.service';
import { formatExecutionStatus, formatPackageStatus, formatSourceType } from '../../execution/execution-status.util';

@Component({
  selector: 'app-dispatch-readiness-step',
  standalone: true,
  imports: [
    DecimalPipe,
    FormsModule,
    MatCardModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
  ],
  template: `
    <div class="dispatch-step">
      <div class="dispatch-step__intro">
        <h2>Dispatch Readiness</h2>
        <p>
          Confirm that reserved stock, tracking references, and handoff details are ready before dispatch. Reserved
          stock is still frozen, not deducted, until the dispatch action is recorded.
        </p>
      </div>

      @if (!store.hasCommittedAllocation()) {
        <div class="dispatch-alert dispatch-alert--error" role="alert">
          <mat-icon aria-hidden="true">inventory_2</mat-icon>
          <span>Reserve stock in the allocation workspace before moving to dispatch.</span>
        </div>
      }

      @if (store.hasPendingOverride()) {
        <div class="dispatch-alert dispatch-alert--warning" role="status">
          <mat-icon aria-hidden="true">pending_actions</mat-icon>
          <span>Dispatch stays blocked while override approval is pending.</span>
        </div>
      }

      @if (needsPreparation()) {
        <div class="dispatch-alert dispatch-alert--info" role="status">
          <mat-icon aria-hidden="true">playlist_add_check</mat-icon>
          <span>Start preparation first. Dispatch can only be recorded after the needs list enters preparation.</span>
        </div>
      }

      <div class="dispatch-metric-grid">
        <mat-card class="dispatch-metric-card">
          <span class="dispatch-metric-card__label">Request Tracking Number</span>
          <strong>{{ current()?.request_tracking_no || 'Pending first reservation' }}</strong>
        </mat-card>

        <mat-card class="dispatch-metric-card">
          <span class="dispatch-metric-card__label">Package Tracking Number</span>
          <strong>{{ current()?.package_tracking_no || 'Pending first reservation' }}</strong>
        </mat-card>

        <mat-card class="dispatch-metric-card">
          <span class="dispatch-metric-card__label">Execution Status</span>
          <strong>{{ formatExecutionStatus(current()?.execution_status) }}</strong>
        </mat-card>

        <mat-card class="dispatch-metric-card">
          <span class="dispatch-metric-card__label">Package Status</span>
          <strong>{{ formatPackageStatus(current()?.package_status) }}</strong>
        </mat-card>
      </div>

      <mat-card class="dispatch-section">
        <div class="dispatch-section__header">
          <div>
            <h3>Reserved Stock Snapshot</h3>
            <p>These reserved lines are what will be deducted when dispatch is recorded.</p>
          </div>
        </div>

        <div class="dispatch-metric-grid dispatch-metric-grid--compact">
          <div class="dispatch-summary">
            <span>Reserved Quantity</span>
            <strong>{{ reservedQuantity() | number:'1.0-4' }}</strong>
          </div>
          <div class="dispatch-summary">
            <span>Reserved Lines</span>
            <strong>{{ lines().length }}</strong>
          </div>
          <div class="dispatch-summary">
            <span>Dispatch Reference</span>
            <strong>{{ current()?.waybill_no || 'Assigned on dispatch' }}</strong>
          </div>
          <div class="dispatch-summary">
            <span>Deduction Rule</span>
            <strong>Deduct on dispatch</strong>
          </div>
        </div>

        @if (!lines().length) {
          <p class="dispatch-empty">No reserved stock lines are available yet.</p>
        } @else {
          <div class="dispatch-table-wrap desktop-only">
            <table>
              <thead>
                <tr>
                  <th>Item</th>
                  <th>Batch / Lot</th>
                  <th>Source</th>
                  <th>Qty</th>
                </tr>
              </thead>
              <tbody>
                @for (line of lines(); track line.inventory_id + '-' + line.batch_id + '-' + line.item_id) {
                  <tr>
                    <td>{{ itemLabel(line) }}</td>
                    <td>{{ batchLabel(line) }}</td>
                    <td>{{ formatSource(line.source_type) }}</td>
                    <td>{{ line.quantity | number:'1.0-4' }}</td>
                  </tr>
                }
              </tbody>
            </table>
          </div>

          <div class="mobile-only dispatch-mobile-list">
            @for (line of lines(); track line.inventory_id + '-' + line.batch_id + '-' + line.item_id) {
              <div class="dispatch-mobile-card">
                <strong>{{ itemLabel(line) }}</strong>
                <span>{{ batchLabel(line) }}</span>
                <span>{{ formatSource(line.source_type) }}</span>
                <strong>{{ line.quantity | number:'1.0-4' }}</strong>
              </div>
            }
          </div>
        }
      </mat-card>

      <mat-card class="dispatch-section">
        <div class="dispatch-section__header">
          <div>
            <h3>Operational Handoff</h3>
            <p>Transport mode is optional but helps make the dispatch document clearer for handoff teams.</p>
          </div>
        </div>

        <mat-form-field appearance="outline" class="dispatch-field">
          <mat-label>Transport Mode</mat-label>
          <input
            matInput
            [ngModel]="draft().transport_mode"
            (ngModelChange)="store.patchDraft({ transport_mode: normalizeText($event) })"
            placeholder="TRUCK, VAN, AIR, etc."
          />
        </mat-form-field>
      </mat-card>
    </div>
  `,
  styles: [`
    :host {
      display: block;
    }

    .dispatch-step {
      display: flex;
      flex-direction: column;
      gap: 18px;
    }

    .dispatch-step__intro h2 {
      margin: 0 0 6px;
      font-size: var(--text-lg);
      font-weight: var(--weight-semibold);
    }

    .dispatch-step__intro p,
    .dispatch-section__header p {
      margin: 0;
      color: var(--color-text-secondary);
    }

    .dispatch-alert {
      display: flex;
      align-items: flex-start;
      gap: 10px;
      padding: 14px 16px;
      border-radius: 12px;
      border-left: 4px solid var(--color-warning);
      background: var(--color-bg-warning);
      color: var(--color-watch);
    }

    .dispatch-alert--info {
      border-left-color: var(--color-focus-ring);
      background: var(--color-bg-info);
      color: var(--color-info);
    }

    .dispatch-alert--error {
      border-left-color: var(--color-critical);
      background: var(--color-bg-critical);
      color: var(--color-critical);
    }

    .dispatch-metric-grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
    }

    .dispatch-metric-grid--compact {
      margin-bottom: 16px;
    }

    .dispatch-metric-card,
    .dispatch-summary,
    .dispatch-section {
      border: 1px solid var(--color-border);
      box-shadow: none;
    }

    .dispatch-metric-card,
    .dispatch-summary {
      padding: 16px;
      border-radius: 12px;
      background: var(--color-surface);
    }

    .dispatch-metric-card__label,
    .dispatch-summary span {
      display: block;
      margin-bottom: 6px;
      color: var(--color-text-secondary);
      font-size: var(--text-sm);
    }

    .dispatch-metric-card strong,
    .dispatch-summary strong {
      display: block;
      font-size: var(--text-md);
      font-weight: var(--weight-semibold);
    }

    .dispatch-section {
      padding: 18px;
      border-radius: 14px;
    }

    .dispatch-section__header {
      margin-bottom: 16px;
    }

    .dispatch-section__header h3 {
      margin: 0 0 4px;
      font-size: var(--text-md);
      font-weight: var(--weight-semibold);
    }

    .dispatch-table-wrap {
      overflow-x: auto;
      border: 1px solid var(--color-border);
      border-radius: 10px;
    }

    .dispatch-table-wrap table {
      width: 100%;
      border-collapse: collapse;
    }

    .dispatch-table-wrap th,
    .dispatch-table-wrap td {
      padding: 10px 12px;
      border-bottom: 1px solid var(--color-border);
      text-align: left;
    }

    .dispatch-table-wrap th {
      background: var(--color-surface-muted);
      color: var(--color-text-secondary);
      font-size: var(--text-sm);
      font-weight: var(--weight-semibold);
    }

    .dispatch-mobile-list {
      display: none;
      gap: 10px;
    }

    .dispatch-mobile-card {
      display: grid;
      gap: 4px;
      padding: 12px;
      border-radius: 10px;
      background: var(--color-surface-muted);
      border: 1px solid var(--color-border);
    }

    .dispatch-empty {
      margin: 0;
      color: var(--color-text-secondary);
    }

    .dispatch-field {
      width: 100%;
    }

    .desktop-only {
      display: block;
    }

    .mobile-only {
      display: none;
    }

    @media (max-width: 960px) {
      .dispatch-metric-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
    }

    @media (max-width: 768px) {
      .desktop-only {
        display: none;
      }

      .mobile-only {
        display: grid;
      }
    }

    @media (max-width: 520px) {
      .dispatch-metric-grid {
        grid-template-columns: 1fr;
      }
    }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DispatchReadinessStepComponent {
  readonly store = inject(ExecutionWorkspaceStateService);
  readonly current = this.store.current;
  readonly draft = this.store.draft;

  readonly lines = computed(() => this.current()?.allocation_lines ?? []);

  needsPreparation(): boolean {
    return String(this.current()?.status ?? '').trim().toUpperCase() === 'APPROVED' && this.store.hasCommittedAllocation();
  }

  reservedQuantity(): number {
    return this.toNumber(this.current()?.reserved_stock_summary?.total_qty)
      || this.lines().reduce((sum, line) => sum + this.toNumber(line.quantity), 0);
  }

  itemLabel(line: AllocationCommittedLine): string {
    const item = this.current()?.items?.find((entry) => entry.item_id === line.item_id);
    return item?.item_name || `Item ${line.item_id}`;
  }

  batchLabel(line: AllocationCommittedLine): string {
    return line.batch_no || `Batch ${line.batch_id}`;
  }

  formatSource(sourceType: string): string {
    return formatSourceType(sourceType);
  }

  formatExecutionStatus(value: unknown): string {
    return formatExecutionStatus(String(value ?? ''));
  }

  formatPackageStatus(value: unknown): string {
    return formatPackageStatus(String(value ?? ''));
  }

  normalizeText(value: unknown): string {
    return String(value ?? '');
  }

  private toNumber(value: string | number | null | undefined): number {
    if (typeof value === 'number') {
      return Number.isFinite(value) ? value : 0;
    }
    const parsed = Number.parseFloat(String(value ?? '0'));
    return Number.isFinite(parsed) ? parsed : 0;
  }
}
