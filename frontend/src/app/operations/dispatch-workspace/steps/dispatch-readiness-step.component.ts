import { DecimalPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output, computed } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';

import { AllocationLine, DispatchDetailResponse } from '../../models/operations.model';
import {
  formatExecutionStatus,
  formatPackageStatus,
  formatSourceType,
} from '../../models/operations-status.util';

@Component({
  selector: 'app-ops-dispatch-readiness-step',
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

      @if (!hasAllocation()) {
        <div class="dispatch-alert dispatch-alert--error" role="alert">
          <mat-icon aria-hidden="true">inventory_2</mat-icon>
          <span>Reserve stock in the fulfillment workspace before moving to dispatch.</span>
        </div>
      }

      @if (isPendingOverride()) {
        <div class="dispatch-alert dispatch-alert--warning" role="status">
          <mat-icon aria-hidden="true">pending_actions</mat-icon>
          <span>Dispatch stays blocked while override approval is pending.</span>
        </div>
      }

      @if (isAlreadyDispatched()) {
        <div class="dispatch-alert dispatch-alert--info" role="status">
          <mat-icon aria-hidden="true">check_circle</mat-icon>
          <span>This package has already been dispatched. Review the dispatch confirmation on the next step.</span>
        </div>
      }

      @if (!isAlreadyDispatched() && !detail?.waybill) {
        <div class="dispatch-alert dispatch-alert--info" role="status">
          <mat-icon aria-hidden="true">description</mat-icon>
          <span>Waybill will be generated on dispatch. No pre-dispatch waybill exists for this package.</span>
        </div>
      }

      <div class="dispatch-metric-grid">
        <mat-card class="dispatch-metric-card">
          <span class="dispatch-metric-card__label">Request Tracking Number</span>
          <strong>{{ detail?.request?.tracking_no || 'Pending' }}</strong>
        </mat-card>

        <mat-card class="dispatch-metric-card">
          <span class="dispatch-metric-card__label">Package Tracking Number</span>
          <strong>{{ detail?.tracking_no || 'Pending' }}</strong>
        </mat-card>

        <mat-card class="dispatch-metric-card">
          <span class="dispatch-metric-card__label">Execution Status</span>
          <strong>{{ formatExecutionStatus(detail?.execution_status) }}</strong>
        </mat-card>

        <mat-card class="dispatch-metric-card">
          <span class="dispatch-metric-card__label">Package Status</span>
          <strong>{{ formatPackageStatus(detail?.status_code) }}</strong>
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
            <strong>{{ detail?.waybill?.waybill_no || detail?.allocation?.waybill_no || 'Assigned on dispatch' }}</strong>
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
                    <td>{{ line.batch_no || ('Batch ' + line.batch_id) }}</td>
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
                <span>{{ line.batch_no || ('Batch ' + line.batch_id) }}</span>
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
            <p>Provide transport and driver details for the dispatch document. Driver name is required.</p>
          </div>
        </div>

        @if (isAlreadyDispatched()) {
          <div class="dispatch-alert dispatch-alert--info" role="status" style="margin-bottom: 14px">
            <mat-icon aria-hidden="true">lock</mat-icon>
            <span>Transport details were captured at dispatch time and are now read-only.</span>
          </div>
        } @else if (hasAllocation() && !isPendingOverride()) {
          <div class="dispatch-alert dispatch-alert--warning" role="status" style="margin-bottom: 14px">
            <mat-icon aria-hidden="true">edit_note</mat-icon>
            <span>Complete transport details before dispatching. Driver name is required.</span>
          </div>
        }

        <div class="dispatch-transport-grid">
          <mat-form-field appearance="outline" class="dispatch-field">
            <mat-label>Transport Mode</mat-label>
            <input
              matInput
              [ngModel]="transportMode"
              (ngModelChange)="transportModeChange.emit($event)"
              placeholder="TRUCK, VAN, AIR, etc."
              [disabled]="isAlreadyDispatched()"
            />
          </mat-form-field>

          <mat-form-field appearance="outline" class="dispatch-field">
            <mat-label>Driver Name</mat-label>
            <input
              matInput
              [ngModel]="driverName"
              (ngModelChange)="driverNameChange.emit($event)"
              placeholder="Full name of the driver"
              [disabled]="isAlreadyDispatched()"
              required
            />
            <mat-hint>Required for dispatch</mat-hint>
          </mat-form-field>

          <mat-form-field appearance="outline" class="dispatch-field">
            <mat-label>Vehicle Identifier</mat-label>
            <input
              matInput
              [ngModel]="vehicleIdentifier"
              (ngModelChange)="vehicleIdentifierChange.emit($event)"
              placeholder="License plate or fleet number"
              [disabled]="isAlreadyDispatched()"
            />
          </mat-form-field>

          <mat-form-field appearance="outline" class="dispatch-field">
            <mat-label>Departure Time</mat-label>
            <input
              matInput
              type="datetime-local"
              [ngModel]="departureTime"
              (ngModelChange)="departureTimeChange.emit($event)"
              [disabled]="isAlreadyDispatched()"
            />
          </mat-form-field>

          <mat-form-field appearance="outline" class="dispatch-field">
            <mat-label>Estimated Arrival</mat-label>
            <input
              matInput
              type="datetime-local"
              [ngModel]="estimatedArrival"
              (ngModelChange)="estimatedArrivalChange.emit($event)"
              [disabled]="isAlreadyDispatched()"
            />
          </mat-form-field>

          <mat-form-field appearance="outline" class="dispatch-field dispatch-transport-grid--full">
            <mat-label>Transport Notes</mat-label>
            <textarea
              matInput
              [ngModel]="transportNotes"
              (ngModelChange)="transportNotesChange.emit($event)"
              placeholder="Route details, special handling instructions, etc."
              [disabled]="isAlreadyDispatched()"
              rows="3"
            ></textarea>
          </mat-form-field>
        </div>
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
      border: 1px solid #e5e5e2;
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
      border: 1px solid #e5e5e2;
      border-radius: 10px;
    }

    .dispatch-table-wrap table {
      width: 100%;
      border-collapse: collapse;
    }

    .dispatch-table-wrap th,
    .dispatch-table-wrap td {
      padding: 10px 12px;
      border-bottom: 1px solid #e5e5e2;
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
      background: var(--ops-strip-bg, #ffffff);
      border: 1px solid var(--color-border, #e5e5e2);
      box-shadow: var(--ops-strip-shadow, 0 1px 3px rgba(55, 53, 47, 0.06));
    }

    .dispatch-empty {
      margin: 0;
      color: var(--color-text-secondary);
    }

    .dispatch-transport-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 1rem;
    }

    .dispatch-transport-grid--full {
      grid-column: 1 / -1;
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
      .dispatch-metric-grid,
      .dispatch-transport-grid {
        grid-template-columns: 1fr;
      }
    }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class OpsDispatchReadinessStepComponent {
  @Input() detail: DispatchDetailResponse | null = null;
  @Input() transportMode = '';
  @Output() transportModeChange = new EventEmitter<string>();
  @Input() driverName = '';
  @Output() driverNameChange = new EventEmitter<string>();
  @Input() vehicleIdentifier = '';
  @Output() vehicleIdentifierChange = new EventEmitter<string>();
  @Input() departureTime = '';
  @Output() departureTimeChange = new EventEmitter<string>();
  @Input() estimatedArrival = '';
  @Output() estimatedArrivalChange = new EventEmitter<string>();
  @Input() transportNotes = '';
  @Output() transportNotesChange = new EventEmitter<string>();

  readonly lines = computed(() => this.detail?.allocation?.allocation_lines ?? []);

  hasAllocation(): boolean {
    return (this.detail?.allocation?.allocation_lines?.length ?? 0) > 0;
  }

  isPendingOverride(): boolean {
    return String(this.detail?.execution_status ?? '').trim().toUpperCase() === 'PENDING_OVERRIDE_APPROVAL';
  }

  isAlreadyDispatched(): boolean {
    return this.detail?.status_code === 'D' || !!this.detail?.dispatch_dtime || !!this.detail?.waybill;
  }

  reservedQuantity(): number {
    const summaryQty = this.toNumber(this.detail?.allocation?.reserved_stock_summary?.total_qty);
    if (summaryQty > 0) {
      return summaryQty;
    }
    return this.lines().reduce((sum, line) => sum + this.toNumber(line.quantity), 0);
  }

  itemLabel(line: AllocationLine): string {
    return `Item ${line.item_id}`;
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

  private toNumber(value: string | number | null | undefined): number {
    if (typeof value === 'number') {
      return Number.isFinite(value) ? value : 0;
    }
    const parsed = Number.parseFloat(String(value ?? '0'));
    return Number.isFinite(parsed) ? parsed : 0;
  }
}
