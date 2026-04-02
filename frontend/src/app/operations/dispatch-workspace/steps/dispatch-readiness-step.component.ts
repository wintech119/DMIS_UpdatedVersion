import { DecimalPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { AbstractControl, FormGroup, ReactiveFormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatOptionModule, MatNativeDateModule, ErrorStateMatcher } from '@angular/material/core';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatDatepickerModule } from '@angular/material/datepicker';

import { AllocationLine, DispatchDetailResponse, TRANSPORT_MODE_OPTIONS } from '../../models/operations.model';
import { formatSourceType } from '../../models/operations-status.util';

function hasGroupError(control: AbstractControl | null | undefined, errorKeys: string[]): boolean {
  const parent = control?.parent;
  return !!parent && errorKeys.some((errorKey) => parent.hasError(errorKey));
}

const DEPARTURE_ERROR_MATCHER: ErrorStateMatcher = {
  isErrorState(control): boolean {
    if (!control || !hasGroupError(control, ['departureIncomplete'])) {
      return false;
    }
    return !!(control.touched || control.dirty || control.parent?.touched || control.parent?.dirty);
  },
};

const ARRIVAL_ERROR_MATCHER: ErrorStateMatcher = {
  isErrorState(control): boolean {
    if (!control || !hasGroupError(control, ['arrivalIncomplete', 'arrivalBeforeDeparture'])) {
      return false;
    }
    return !!(control.touched || control.dirty || control.parent?.touched || control.parent?.dirty);
  },
};

@Component({
  selector: 'app-ops-dispatch-readiness-step',
  standalone: true,
  imports: [
    DecimalPipe,
    ReactiveFormsModule,
    MatButtonModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatOptionModule,
    MatNativeDateModule,
    MatSelectModule,
    MatDatepickerModule,
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
              class="ops-handoff">
          <div class="ops-handoff__row ops-handoff__row--3col">
            <mat-form-field appearance="outline" subscriptSizing="dynamic">
              <mat-label>Transport Mode</mat-label>
              <mat-select formControlName="transport_mode"
                          aria-label="Select transport mode for this dispatch">
                <mat-option value="">-- Select --</mat-option>
                @for (opt of transportModeOptions; track opt.value) {
                  <mat-option [value]="opt.value">{{ opt.label }}</mat-option>
                }
              </mat-select>
            </mat-form-field>

            <mat-form-field appearance="outline" subscriptSizing="dynamic">
              <mat-label>Driver Name</mat-label>
              <input matInput formControlName="driver_name"
                     placeholder="Full name of the driver" />
              @if (transportForm().get('driver_name')?.hasError('required') && transportForm().get('driver_name')?.touched) {
                <mat-error>Driver name is required.</mat-error>
              }
              @if (transportForm().get('driver_name')?.hasError('maxlength')) {
                <mat-error>Max 100 characters.</mat-error>
              }
            </mat-form-field>

            <mat-form-field appearance="outline" subscriptSizing="dynamic">
              <mat-label>Vehicle ID</mat-label>
              <input matInput formControlName="vehicle_id"
                     placeholder="Plate or fleet no." />
              @if (transportForm().get('vehicle_id')?.hasError('maxlength')) {
                <mat-error>Max 50 characters.</mat-error>
              }
            </mat-form-field>
          </div>

          <div class="ops-handoff__row ops-handoff__row--schedule">
            <fieldset class="ops-handoff__datetime-group">
              <legend class="ops-handoff__group-label">Departure</legend>
              <div class="ops-handoff__datetime-pair">
                <mat-form-field appearance="outline" subscriptSizing="dynamic">
                  <mat-label>Date</mat-label>
                  <input matInput [matDatepicker]="depPicker" formControlName="departure_date"
                         placeholder="Pick date"
                         [errorStateMatcher]="departureErrorMatcher" />
                  <mat-datepicker-toggle matIconSuffix [for]="depPicker" />
                  <mat-datepicker #depPicker />
                </mat-form-field>
                <mat-form-field appearance="outline" subscriptSizing="dynamic">
                  <mat-label>Time</mat-label>
                  <input #depTimeInput matInput type="time" step="60"
                         formControlName="departure_time"
                         aria-label="Departure time (24-hour)"
                         [errorStateMatcher]="departureErrorMatcher" />
                  <button mat-icon-button matSuffix type="button"
                          aria-label="Open departure time picker"
                          [disabled]="departureTimeControl()?.disabled"
                          [attr.tabindex]="departureTimeControl()?.disabled ? -1 : null"
                          (click)="openTimePicker(depTimeInput, departureTimeControl())">
                    <mat-icon>schedule</mat-icon>
                  </button>
                  @if (showDepartureIncompleteError()) {
                    <mat-error>Complete both departure date and time.</mat-error>
                  }
                </mat-form-field>
              </div>
            </fieldset>

            <fieldset class="ops-handoff__datetime-group">
              <legend class="ops-handoff__group-label">Estimated Arrival</legend>
              <div class="ops-handoff__datetime-pair">
                <mat-form-field appearance="outline" subscriptSizing="dynamic">
                  <mat-label>Date</mat-label>
                  <input matInput [matDatepicker]="arrPicker" formControlName="arrival_date"
                         placeholder="Pick date"
                         [errorStateMatcher]="estimatedArrivalErrorMatcher" />
                  <mat-datepicker-toggle matIconSuffix [for]="arrPicker" />
                  <mat-datepicker #arrPicker />
                  @if (showArrivalBeforeDepartureError()) {
                    <mat-error>Must be after departure.</mat-error>
                  }
                </mat-form-field>
                <mat-form-field appearance="outline" subscriptSizing="dynamic">
                  <mat-label>Time</mat-label>
                  <input #arrTimeInput matInput type="time" step="60"
                         formControlName="arrival_time"
                         aria-label="Estimated arrival time (24-hour)"
                         [errorStateMatcher]="estimatedArrivalErrorMatcher" />
                  <button mat-icon-button matSuffix type="button"
                          aria-label="Open estimated arrival time picker"
                          [disabled]="arrivalTimeControl()?.disabled"
                          [attr.tabindex]="arrivalTimeControl()?.disabled ? -1 : null"
                          (click)="openTimePicker(arrTimeInput, arrivalTimeControl())">
                    <mat-icon>schedule</mat-icon>
                  </button>
                  @if (showArrivalIncompleteError()) {
                    <mat-error>Complete both arrival date and time.</mat-error>
                  }
                  @if (showArrivalBeforeDepartureError()) {
                    <mat-error>Must be after departure.</mat-error>
                  }
                </mat-form-field>
              </div>
            </fieldset>
          </div>

          <mat-form-field appearance="outline" subscriptSizing="dynamic" class="ops-handoff__notes">
            <mat-label>Transport Notes</mat-label>
            <textarea matInput formControlName="transport_notes"
                      placeholder="Route details, special handling, etc."
                      rows="2"></textarea>
            @if (transportForm().get('transport_notes')?.hasError('maxlength')) {
              <mat-error>Max 500 characters.</mat-error>
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

    /* ── Condensed handoff form ────────────────────────────── */
    .ops-handoff {
      display: flex;
      flex-direction: column;
      gap: 0.75rem;
    }

    .ops-handoff__row {
      display: grid;
      gap: 0.75rem;
    }

    .ops-handoff__row--3col {
      grid-template-columns: minmax(0, 0.8fr) minmax(0, 1fr) minmax(0, 0.8fr);
    }

    .ops-handoff__row--schedule {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    .ops-handoff__datetime-group {
      border: 1px solid var(--ops-outline, rgba(55, 53, 47, 0.10));
      border-radius: 10px;
      padding: 0.65rem 0.75rem 0.5rem;
      margin: 0;
    }

    .ops-handoff__group-label {
      font-size: 0.7rem;
      font-weight: var(--weight-semibold, 600);
      text-transform: uppercase;
      letter-spacing: 0.14em;
      color: var(--color-text-secondary, #787774);
      padding: 0 4px;
    }

    .ops-handoff__datetime-pair {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 0.5rem;
      margin-top: 0.35rem;
    }

    .ops-handoff__notes {
      width: 100%;
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

    @media (max-width: 768px) {
      .ops-handoff__row--3col {
        grid-template-columns: 1fr 1fr;
      }

      .ops-handoff__row--schedule {
        grid-template-columns: 1fr;
      }
    }

    @media (max-width: 520px) {
      .ops-handoff__row--3col {
        grid-template-columns: 1fr;
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
  readonly departureErrorMatcher = DEPARTURE_ERROR_MATCHER;
  readonly estimatedArrivalErrorMatcher = ARRIVAL_ERROR_MATCHER;
  readonly departureTimeControl = computed(() => this.transportForm().get('departure_time'));
  readonly arrivalTimeControl = computed(() => this.transportForm().get('arrival_time'));

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

  showDepartureIncompleteError(): boolean {
    return this.showGroupError('departureIncomplete', ['departure_date', 'departure_time']);
  }

  showArrivalIncompleteError(): boolean {
    return this.showGroupError('arrivalIncomplete', ['arrival_date', 'arrival_time']);
  }

  showArrivalBeforeDepartureError(): boolean {
    return this.showGroupError('arrivalBeforeDeparture', ['arrival_date', 'arrival_time']);
  }

  openTimePicker(input: HTMLInputElement, control: AbstractControl | null): void {
    if (input.disabled || control?.disabled) {
      return;
    }
    input.focus();
    if (typeof input.showPicker === 'function') {
      input.showPicker();
      return;
    }
    input.click();
  }

  private showGroupError(errorKey: string, controlNames: string[]): boolean {
    const form = this.transportForm();
    if (!form.hasError(errorKey)) {
      return false;
    }
    return controlNames.some((controlName) => {
      const control = form.get(controlName);
      return !!(control?.touched || control?.dirty);
    }) || form.touched || form.dirty;
  }

  private toNumber(value: string | number | null | undefined): number {
    if (typeof value === 'number') {
      return Number.isFinite(value) ? value : 0;
    }
    const parsed = Number.parseFloat(String(value ?? '0'));
    return Number.isFinite(parsed) ? parsed : 0;
  }
}
