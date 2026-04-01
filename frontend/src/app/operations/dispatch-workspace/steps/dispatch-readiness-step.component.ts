import { DecimalPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { FormGroup, ReactiveFormsModule } from '@angular/forms';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatOptionModule } from '@angular/material/core';
import { MatSelectModule } from '@angular/material/select';

import { AllocationLine, DispatchDetailResponse, TRANSPORT_MODE_OPTIONS } from '../../models/operations.model';
import { formatSourceType } from '../../models/operations-status.util';

@Component({
  selector: 'app-ops-dispatch-readiness-step',
  standalone: true,
  imports: [
    DecimalPipe,
    ReactiveFormsModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatOptionModule,
    MatSelectModule,
  ],
  template: `
    <div class="ops-readiness">
      <div class="ops-readiness__intro">
        <h2>Dispatch Readiness</h2>
        <p>
          Confirm that reserved stock, tracking references, and handoff details are ready before dispatch. Reserved
          stock is still frozen, not deducted, until the dispatch action is recorded.
        </p>
      </div>

      @if (!hasAllocation()) {
        <div class="ops-callout ops-callout--danger" role="alert">
          <mat-icon aria-hidden="true">inventory_2</mat-icon>
          <span>Reserve stock in the fulfillment workspace before moving to dispatch.</span>
        </div>
      }

      @if (isPendingOverride()) {
        <div class="ops-callout ops-callout--warning" role="status">
          <mat-icon aria-hidden="true">pending_actions</mat-icon>
          <span>Dispatch stays blocked while override approval is pending.</span>
        </div>
      }

      @if (isAlreadyDispatched()) {
        <div class="ops-callout ops-callout--success" role="status">
          <mat-icon aria-hidden="true">check_circle</mat-icon>
          <span>This package has already been dispatched. Review the dispatch confirmation on the next step.</span>
        </div>
      }

      @if (!isAlreadyDispatched() && !detail()?.waybill) {
        <div class="ops-callout" role="status">
          <mat-icon aria-hidden="true">description</mat-icon>
          <span>Waybill will be generated on dispatch. No pre-dispatch waybill exists for this package.</span>
        </div>
      }

      <section class="ops-readiness__section" aria-label="Transport handoff details">
        <div class="ops-readiness__section-header">
          <h3>Operational Handoff</h3>
          <p>Provide transport and driver details for the dispatch document.</p>
        </div>

        @if (isAlreadyDispatched()) {
          <div class="ops-callout" role="status">
            <mat-icon aria-hidden="true">lock</mat-icon>
            <span>Transport details were captured at dispatch time and are now read-only.</span>
          </div>
        } @else if (hasAllocation() && !isPendingOverride()) {
          <div class="ops-callout ops-callout--warning" role="status">
            <mat-icon aria-hidden="true">edit_note</mat-icon>
            <span>Complete transport details before dispatching. Driver name is required.</span>
          </div>
        }

        <form [formGroup]="transportForm()" role="form" aria-label="Transport handoff details"
              class="ops-readiness__form-grid">
          <mat-form-field appearance="outline">
            <mat-label>Transport Mode</mat-label>
            <mat-select formControlName="transport_mode"
                        aria-label="Select transport mode for this dispatch">
              <mat-option value="">-- Select --</mat-option>
              @for (opt of transportModeOptions; track opt.value) {
                <mat-option [value]="opt.value">{{ opt.label }}</mat-option>
              }
            </mat-select>
            <mat-hint>How the goods will be transported.</mat-hint>
          </mat-form-field>

          <mat-form-field appearance="outline">
            <mat-label>Driver Name</mat-label>
            <input matInput formControlName="driver_name"
                   placeholder="Full name of the driver"
                   maxlength="100" />
            <mat-hint>The driver responsible for this delivery.</mat-hint>
            @if (transportForm().get('driver_name')?.hasError('required') && transportForm().get('driver_name')?.touched) {
              <mat-error>Driver name is required to record dispatch.</mat-error>
            }
            @if (transportForm().get('driver_name')?.hasError('maxlength')) {
              <mat-error>Driver name cannot exceed 100 characters.</mat-error>
            }
          </mat-form-field>

          <mat-form-field appearance="outline">
            <mat-label>Vehicle Identifier</mat-label>
            <input matInput formControlName="vehicle_id"
                   placeholder="License plate or fleet number"
                   maxlength="50" />
            <mat-hint>License plate or fleet number for the transport vehicle.</mat-hint>
            @if (transportForm().get('vehicle_id')?.hasError('maxlength')) {
              <mat-error>Vehicle identifier cannot exceed 50 characters.</mat-error>
            }
          </mat-form-field>

          <mat-form-field appearance="outline">
            <mat-label>Departure Time</mat-label>
            <input matInput type="datetime-local"
                   formControlName="departure_dtime" />
            <mat-hint>When the vehicle will leave the warehouse.</mat-hint>
          </mat-form-field>

          <mat-form-field appearance="outline">
            <mat-label>Estimated Arrival</mat-label>
            <input matInput type="datetime-local"
                   formControlName="estimated_arrival_dtime" />
            <mat-hint>Expected arrival at the receiving destination.</mat-hint>
            @if (transportForm().hasError('arrivalBeforeDeparture')) {
              <mat-error>Arrival time must be after departure time.</mat-error>
            }
          </mat-form-field>

          <mat-form-field appearance="outline" class="ops-readiness__form-grid--full">
            <mat-label>Transport Notes</mat-label>
            <textarea matInput formControlName="transport_notes"
                      placeholder="Route details, special handling instructions, etc."
                      maxlength="500"
                      rows="3"></textarea>
            <mat-hint>Route details, special handling instructions, or delivery constraints.</mat-hint>
            @if (transportForm().get('transport_notes')?.hasError('maxlength')) {
              <mat-error>Transport notes cannot exceed 500 characters.</mat-error>
            }
          </mat-form-field>
        </form>
      </section>

      <section class="ops-readiness__section" aria-label="Reserved stock snapshot">
        <div class="ops-readiness__section-header">
          <h3>Reserved Stock Snapshot</h3>
          <p>These reserved lines are what will be deducted when dispatch is recorded.</p>
        </div>

        @if (lines().length) {
          <div class="ops-summary-grid">
            <div class="ops-summary-card">
              <span class="ops-summary-card__label">Reserved Quantity</span>
              <p class="ops-summary-card__value">{{ reservedQuantity() | number:'1.0-4' }}</p>
            </div>
            <div class="ops-summary-card">
              <span class="ops-summary-card__label">Reserved Lines</span>
              <p class="ops-summary-card__value">{{ lines().length }}</p>
            </div>
            <div class="ops-summary-card">
              <span class="ops-summary-card__label">Dispatch Reference</span>
              <p class="ops-summary-card__value">{{ detail()?.waybill?.waybill_no || detail()?.allocation?.waybill_no || 'Assigned on dispatch' }}</p>
            </div>
            <div class="ops-summary-card">
              <span class="ops-summary-card__label">Deduction Rule</span>
              <p class="ops-summary-card__value">Deduct on dispatch</p>
            </div>
          </div>

          <div class="ops-readiness__table-wrap desktop-only" role="table" aria-label="Reserved stock lines">
            <table class="ops-table">
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

          <div class="mobile-only ops-readiness__mobile-list" role="list" aria-label="Reserved stock lines">
            @for (line of lines(); track line.inventory_id + '-' + line.batch_id + '-' + line.item_id) {
              <div class="ops-readiness__mobile-card" role="listitem">
                <strong>{{ itemLabel(line) }}</strong>
                <span>{{ line.batch_no || ('Batch ' + line.batch_id) }}</span>
                <span>{{ formatSource(line.source_type) }}</span>
                <strong>{{ line.quantity | number:'1.0-4' }}</strong>
              </div>
            }
          </div>
        } @else {
          <div class="ops-empty">
            <mat-icon aria-hidden="true">inventory_2</mat-icon>
            <p class="ops-empty__title">No reserved stock lines</p>
            <p class="ops-empty__copy">Reserve stock in the fulfillment workspace before moving to dispatch.</p>
          </div>
        }
      </section>
    </div>
  `,
  styles: [`
    :host {
      display: block;
    }

    .ops-readiness {
      display: flex;
      flex-direction: column;
      gap: 18px;
    }

    .ops-readiness__intro h2 {
      margin: 0 0 6px;
      font-size: var(--text-lg);
      font-weight: var(--weight-semibold);
    }

    .ops-readiness__intro p {
      margin: 0;
      color: var(--color-text-secondary);
    }

    .ops-readiness__section {
      display: flex;
      flex-direction: column;
      gap: 14px;
      padding: 18px;
      border-radius: 14px;
      border: 1px solid var(--ops-outline, rgba(55, 53, 47, 0.08));
      background: var(--color-surface, #ffffff);
    }

    .ops-readiness__section-header h3 {
      margin: 0 0 4px;
      font-size: var(--text-md);
      font-weight: var(--weight-semibold);
    }

    .ops-readiness__section-header p {
      margin: 0;
      color: var(--color-text-secondary);
    }

    .ops-readiness__form-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 1rem;
    }

    .ops-readiness__form-grid--full {
      grid-column: 1 / -1;
    }

    .ops-readiness__table-wrap {
      overflow-x: auto;
      border: 1px solid var(--ops-outline, rgba(55, 53, 47, 0.08));
      border-radius: 10px;
    }

    .ops-readiness__mobile-list {
      display: none;
      gap: 10px;
    }

    .ops-readiness__mobile-card {
      display: grid;
      gap: 4px;
      padding: 12px;
      border-radius: 10px;
      background: var(--color-surface, #ffffff);
      border: 1px solid var(--ops-outline, rgba(55, 53, 47, 0.08));
      box-shadow: 0 1px 3px rgba(55, 53, 47, 0.06);
    }

    .desktop-only {
      display: block;
    }

    .mobile-only {
      display: none;
    }

    @media (max-width: 960px) {
      .ops-summary-grid {
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
      .ops-summary-grid,
      .ops-readiness__form-grid {
        grid-template-columns: 1fr;
      }

      .ops-readiness__form-grid--full {
        grid-column: auto;
      }
    }

    @media (prefers-reduced-motion: reduce) {
      * {
        transition: none;
      }
    }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class OpsDispatchReadinessStepComponent {
  readonly detail = input<DispatchDetailResponse | null>(null);
  readonly transportForm = input.required<FormGroup>();
  readonly itemNameMap = input<ReadonlyMap<number, string>>(new Map());

  readonly transportModeOptions = TRANSPORT_MODE_OPTIONS;

  readonly lines = computed(() => this.detail()?.allocation?.allocation_lines ?? []);

  readonly hasAllocation = computed(() => (this.lines().length ?? 0) > 0);

  readonly isPendingOverride = computed(() => {
    const status = String(this.detail()?.execution_status ?? '').trim().toUpperCase();
    return status === 'PENDING_OVERRIDE_APPROVAL';
  });

  readonly isAlreadyDispatched = computed(() => {
    const d = this.detail();
    return d?.status_code === 'D' || !!d?.dispatch_dtime || !!d?.waybill;
  });

  readonly reservedQuantity = computed(() => {
    const summaryQty = this.toNumber(this.detail()?.allocation?.reserved_stock_summary?.total_qty);
    if (summaryQty > 0) {
      return summaryQty;
    }
    return this.lines().reduce((sum, line) => sum + this.toNumber(line.quantity), 0);
  });

  itemLabel(line: AllocationLine): string {
    return this.itemNameMap().get(line.item_id) || `Item ${line.item_id}`;
  }

  formatSource(sourceType: string): string {
    return formatSourceType(sourceType);
  }

  private toNumber(value: string | number | null | undefined): number {
    if (typeof value === 'number') {
      return Number.isFinite(value) ? value : 0;
    }
    const parsed = Number.parseFloat(String(value ?? '0'));
    return Number.isFinite(parsed) ? parsed : 0;
  }
}
