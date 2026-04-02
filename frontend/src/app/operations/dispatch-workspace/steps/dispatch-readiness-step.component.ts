import { DecimalPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { FormGroup, ReactiveFormsModule } from '@angular/forms';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatOptionModule, ErrorStateMatcher } from '@angular/material/core';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';

import { AllocationLine, DispatchDetailResponse, TRANSPORT_MODE_OPTIONS } from '../../models/operations.model';
import { formatSourceType } from '../../models/operations-status.util';

const ARRIVAL_ERROR_MATCHER: ErrorStateMatcher = {
  isErrorState(control): boolean {
    const parent = control?.parent;
    if (!control || !parent?.hasError('arrivalBeforeDeparture')) {
      return false;
    }
    return !!(control.touched || control.dirty || parent.touched || parent.dirty);
  },
};

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
                   placeholder="Full name of the driver" />
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
                   placeholder="License plate or fleet number" />
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
                   formControlName="estimated_arrival_dtime"
                   [errorStateMatcher]="estimatedArrivalErrorMatcher" />
            <mat-hint>Expected arrival at the receiving destination.</mat-hint>
            @if (showArrivalBeforeDepartureError()) {
              <mat-error>Arrival time must be after departure time.</mat-error>
            }
          </mat-form-field>

          <mat-form-field appearance="outline" class="ops-readiness__form-grid--full">
            <mat-label>Transport Notes</mat-label>
            <textarea matInput formControlName="transport_notes"
                      placeholder="Route details, special handling instructions, etc."
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
          <div class="ops-stock-strip" role="status" aria-label="Stock reservation summary">
            <div class="ops-stock-strip__stat">
              <span class="ops-stock-strip__value">{{ reservedQuantity() | number:'1.0-4' }}</span>
              <span class="ops-stock-strip__label">qty reserved</span>
            </div>
            <span class="ops-stock-strip__sep" aria-hidden="true"></span>
            <div class="ops-stock-strip__stat">
              <span class="ops-stock-strip__value">{{ lines().length }}</span>
              <span class="ops-stock-strip__label">{{ lines().length === 1 ? 'line' : 'lines' }}</span>
            </div>
            <span class="ops-stock-strip__sep" aria-hidden="true"></span>
            <div class="ops-stock-strip__stat">
              <mat-icon class="ops-stock-strip__icon" aria-hidden="true">description</mat-icon>
              <span class="ops-stock-strip__label">{{ detail()?.waybill?.waybill_no || detail()?.allocation?.waybill_no || 'Ref assigned on dispatch' }}</span>
            </div>
            <span class="ops-stock-strip__sep" aria-hidden="true"></span>
            <div class="ops-stock-strip__stat">
              <mat-icon class="ops-stock-strip__icon" aria-hidden="true">swap_vert</mat-icon>
              <span class="ops-stock-strip__label">Deduct on dispatch</span>
            </div>
          </div>

          <div class="ops-readiness__table-wrap desktop-only" aria-label="Reserved stock lines">
            <table class="ops-readiness__table">
              <thead>
                <tr>
                  <th>Item</th>
                  <th>Batch / Lot</th>
                  <th>Source</th>
                  <th class="ops-readiness__table-num">Qty</th>
                </tr>
              </thead>
              <tbody>
                @for (line of lines(); track line.inventory_id + '-' + line.batch_id + '-' + line.item_id) {
                  <tr>
                    <td>{{ itemLabel(line) }}</td>
                    <td>{{ line.batch_no || ('Batch ' + line.batch_id) }}</td>
                    <td>{{ formatSource(line.source_type) }}</td>
                    <td class="ops-readiness__table-num">{{ line.quantity | number:'1.0-4' }}</td>
                  </tr>
                }
              </tbody>
            </table>
          </div>

          <div class="mobile-only ops-readiness__mobile-list" role="list" aria-label="Reserved stock lines">
            @for (line of lines(); track line.inventory_id + '-' + line.batch_id + '-' + line.item_id) {
              <div class="ops-readiness__mobile-card" role="listitem">
                <div class="ops-readiness__mobile-card-header">
                  <strong>{{ itemLabel(line) }}</strong>
                  <strong>{{ line.quantity | number:'1.0-4' }}</strong>
                </div>
                <div class="ops-readiness__mobile-card-meta">
                  <span>{{ line.batch_no || ('Batch ' + line.batch_id) }}</span>
                  <span>{{ formatSource(line.source_type) }}</span>
                </div>
              </div>
            }
          </div>
        } @else {
          <div class="ops-readiness__empty" role="status">
            <mat-icon aria-hidden="true">inventory_2</mat-icon>
            <div>
              <p class="ops-readiness__empty-title">No reserved stock lines</p>
              <p class="ops-readiness__empty-copy">Reserve stock in the fulfillment workspace before moving to dispatch.</p>
            </div>
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

    /* ── Stock summary strip ─────────────────────────────────── */
    .ops-stock-strip {
      display: flex;
      align-items: center;
      gap: 0.75rem;
      padding: 0.65rem 0.85rem;
      border-radius: 0.65rem;
      background: var(--color-surface-container-low, #f3f3f4);
      flex-wrap: wrap;
    }

    .ops-stock-strip__stat {
      display: inline-flex;
      align-items: center;
      gap: 0.35rem;
    }

    .ops-stock-strip__value {
      font-size: 1.1rem;
      font-weight: var(--weight-semibold, 600);
      color: var(--color-text-primary, #37352F);
      letter-spacing: -0.02em;
    }

    .ops-stock-strip__label {
      font-size: 0.78rem;
      color: var(--color-text-secondary, #787774);
    }

    .ops-stock-strip__icon {
      font-size: 0.95rem;
      width: 0.95rem;
      height: 0.95rem;
      color: var(--color-text-tertiary, #908d87);
    }

    .ops-stock-strip__sep {
      width: 1px;
      height: 1.1rem;
      background: var(--ops-outline, rgba(55, 53, 47, 0.12));
      flex-shrink: 0;
    }

    /* ── Table ────────────────────────────────────────────────── */
    .ops-readiness__table-wrap {
      overflow-x: auto;
      border: 1px solid var(--ops-outline, rgba(55, 53, 47, 0.08));
      border-radius: 0.6rem;
    }

    .ops-readiness__table {
      width: 100%;
      border-collapse: collapse;
    }

    .ops-readiness__table th,
    .ops-readiness__table td {
      padding: 0.55rem 0.7rem;
      text-align: left;
      border-bottom: 1px solid var(--ops-outline, rgba(55, 53, 47, 0.06));
      vertical-align: middle;
    }

    .ops-readiness__table th {
      font-size: 0.68rem;
      letter-spacing: 0.16em;
      text-transform: uppercase;
      color: var(--color-text-secondary, #787774);
      background: var(--color-surface-container-low, #f3f3f4);
      font-weight: var(--weight-semibold, 600);
    }

    .ops-readiness__table td {
      font-size: 0.86rem;
      color: var(--color-text-primary, #37352F);
    }

    .ops-readiness__table tbody tr:last-child td {
      border-bottom: none;
    }

    .ops-readiness__table-num {
      text-align: right;
      font-variant-numeric: tabular-nums;
    }

    /* ── Mobile cards ─────────────────────────────────────────── */
    .ops-readiness__mobile-list {
      display: none;
      gap: 6px;
    }

    .ops-readiness__mobile-card {
      display: flex;
      flex-direction: column;
      gap: 2px;
      padding: 0.65rem 0.75rem;
      border-radius: 0.5rem;
      background: var(--color-surface, #ffffff);
      border: 1px solid var(--ops-outline, rgba(55, 53, 47, 0.08));
    }

    .ops-readiness__mobile-card-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 0.88rem;
      font-weight: var(--weight-semibold, 600);
    }

    .ops-readiness__mobile-card-meta {
      display: flex;
      gap: 0.5rem;
      font-size: 0.78rem;
      color: var(--color-text-secondary, #787774);
    }

    /* ── Empty state ──────────────────────────────────────────── */
    .ops-readiness__empty {
      display: flex;
      align-items: flex-start;
      gap: 0.65rem;
      padding: 1rem;
      border-radius: 0.65rem;
      background: var(--color-surface-container-low, #f3f3f4);
      color: var(--color-text-secondary, #787774);
    }

    .ops-readiness__empty mat-icon {
      font-size: 1.25rem;
      width: 1.25rem;
      height: 1.25rem;
      margin-top: 0.1rem;
      color: var(--color-text-tertiary, #908d87);
    }

    .ops-readiness__empty-title {
      margin: 0;
      font-size: 0.88rem;
      font-weight: var(--weight-semibold, 600);
      color: var(--color-text-primary, #37352F);
    }

    .ops-readiness__empty-copy {
      margin: 0.15rem 0 0;
      font-size: 0.82rem;
    }

    .desktop-only {
      display: block;
    }

    .mobile-only {
      display: none;
    }

    @media (max-width: 768px) {
      .desktop-only {
        display: none;
      }

      .mobile-only {
        display: flex;
        flex-direction: column;
      }
    }

    @media (max-width: 520px) {
      .ops-readiness__form-grid {
        grid-template-columns: 1fr;
      }

      .ops-readiness__form-grid--full {
        grid-column: auto;
      }

      .ops-stock-strip {
        gap: 0.5rem 0.6rem;
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
  readonly estimatedArrivalErrorMatcher = ARRIVAL_ERROR_MATCHER;

  readonly lines = computed(() => this.detail()?.allocation?.allocation_lines ?? []);

  readonly hasAllocation = computed(() => this.lines().length > 0);

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

  showArrivalBeforeDepartureError(): boolean {
    const form = this.transportForm();
    const arrivalControl = form.get('estimated_arrival_dtime');
    return form.hasError('arrivalBeforeDeparture')
      && !!(arrivalControl?.touched || arrivalControl?.dirty || form.touched || form.dirty);
  }

  private toNumber(value: string | number | null | undefined): number {
    if (typeof value === 'number') {
      return Number.isFinite(value) ? value : 0;
    }
    const parsed = Number.parseFloat(String(value ?? '0'));
    return Number.isFinite(parsed) ? parsed : 0;
  }
}
