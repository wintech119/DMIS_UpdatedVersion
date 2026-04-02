import { DatePipe, DecimalPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, DestroyRef, OnInit, computed, inject, input, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormGroup } from '@angular/forms';
import { MatIconModule } from '@angular/material/icon';
import { map, merge, startWith } from 'rxjs';

import {
  type AllocationLine,
  DispatchDetailResponse,
  TRANSPORT_MODE_OPTIONS,
  WaybillLineItem,
  WaybillResponse,
} from '../../models/operations.model';
import { formatSourceType } from '../../models/operations-status.util';

type ReviewLine = WaybillLineItem | AllocationLine;

interface DispatchTransportFormValue {
  transport_mode: string;
  driver_name: string;
  vehicle_id: string;
  departure_date: Date | null;
  departure_time: string;
  arrival_date: Date | null;
  arrival_time: string;
  transport_notes: string;
}

const EMPTY_TRANSPORT_FORM_VALUE: DispatchTransportFormValue = {
  transport_mode: '',
  driver_name: '',
  vehicle_id: '',
  departure_date: null,
  departure_time: '',
  arrival_date: null,
  arrival_time: '',
  transport_notes: '',
};

@Component({
  selector: 'app-ops-dispatch-review-step',
  standalone: true,
  imports: [
    DatePipe,
    DecimalPipe,
    MatIconModule,
  ],
  template: `
    <div class="ops-review">
      <div class="ops-review__intro">
        <h2>Review & Dispatch</h2>
        <p>
          Finalize the operational handoff. When dispatch is recorded, reserved stock is physically deducted and the
          waybill reference becomes part of the execution record.
        </p>
      </div>

      @if (!effectiveWaybillNo()) {
        <div class="ops-callout" role="status">
          <mat-icon aria-hidden="true">description</mat-icon>
          <span>The waybill number will be assigned at dispatch if it does not already exist.</span>
        </div>
      }

      @if (waybillReadback()) {
        <div class="ops-review__artifact" role="status">
          <mat-icon aria-hidden="true">info</mat-icon>
          <span>
            Artifact mode: <strong>{{ waybillReadback()!.artifact_mode || 'unknown' }}</strong>
            @if (!waybillReadback()!.persisted) {
              — Rebuilt from dispatch record, not independently persisted.
            }
          </span>
        </div>
      }

      <section class="ops-review__section" aria-label="Dispatch document summary">
        <div class="ops-review__section-header">
          <h3>Dispatch Document</h3>
          <p>The line summary below mirrors the minimal digital waybill or dispatch document reference.</p>
        </div>

        <div class="ops-review__meta-grid" aria-label="Transport details" role="group">
          <div>
            <span>Transport Mode</span>
            <strong>{{ effectiveTransportModeLabel() }}</strong>
          </div>
          <div>
            <span>Driver</span>
            <strong>{{ formDriverName() || 'Not specified' }}</strong>
          </div>
          <div>
            <span>Vehicle</span>
            <strong>{{ formVehicleId() || 'Not specified' }}</strong>
          </div>
          <div>
            <span>Source Warehouse</span>
            <strong>{{ sourceWarehouseLabel() }}</strong>
          </div>
          <div>
            <span>Destination</span>
            <strong>{{ destinationLabel() }}</strong>
          </div>
          <div>
            <span>Departure</span>
            <strong>{{ formDepartureTime() ? (formDepartureTime() | date:'medium') : 'Not set' }}</strong>
          </div>
          <div>
            <span>ETA</span>
            <strong>{{ formEstimatedArrival() ? (formEstimatedArrival() | date:'medium') : 'Not set' }}</strong>
          </div>
          @if (formTransportNotes()) {
            <div class="ops-review__meta-grid--full">
              <span>Transport Notes</span>
              <strong>{{ formTransportNotes() }}</strong>
            </div>
          }
        </div>

        @if (!reviewLines().length) {
          <div class="ops-empty">
            <mat-icon aria-hidden="true">description</mat-icon>
            <p class="ops-empty__title">No dispatch lines available</p>
            <p class="ops-empty__copy">Line items will appear here once stock is reserved and allocated.</p>
          </div>
        } @else {
          <div class="ops-review__table-wrap desktop-only">
            <table class="ops-table" aria-label="Dispatch line items">
              <thead>
                <tr>
                  <th>Item</th>
                  <th>Batch / Lot</th>
                  <th>Source</th>
                  <th>Qty</th>
                </tr>
              </thead>
              <tbody>
                @for (line of reviewLines(); track line.inventory_id + '-' + line.batch_id + '-' + line.item_id) {
                  <tr>
                    <td>{{ itemLabel(line) }}</td>
                    <td>{{ line.batch_no || ('Batch ' + line.batch_id) }}</td>
                    <td>{{ formatSource(line.source_type || 'ON_HAND') }}</td>
                    <td>{{ line.quantity | number:'1.0-4' }}</td>
                  </tr>
                }
              </tbody>
            </table>
          </div>

          <div class="mobile-only ops-review__mobile-list" role="list" aria-label="Dispatch line items">
            @for (line of reviewLines(); track line.inventory_id + '-' + line.batch_id + '-' + line.item_id) {
              <div class="ops-review__mobile-card" role="listitem">
                <strong>{{ itemLabel(line) }}</strong>
                <span>{{ line.batch_no || ('Batch ' + line.batch_id) }}</span>
                <span>{{ formatSource(line.source_type || 'ON_HAND') }}</span>
                <strong>{{ line.quantity | number:'1.0-4' }}</strong>
              </div>
            }
          </div>
        }
      </section>

      <section class="ops-review__section" aria-label="Scope guardrail">
        <div class="ops-review__section-header">
          <h3>Scope Guardrail</h3>
          <p>
            This workspace stops at dispatch recording and status visibility. Receiving-agency distribution confirmation
            remains out of scope.
          </p>
        </div>
      </section>
    </div>
  `,
  styles: [`
    :host {
      display: block;
    }

    .ops-review {
      display: flex;
      flex-direction: column;
      gap: 18px;
    }

    .ops-review__intro h2 {
      margin: 0 0 6px;
      font-size: var(--text-lg);
      font-weight: var(--weight-semibold);
    }

    .ops-review__intro p,
    .ops-review__section-header p {
      margin: 0;
      color: var(--color-text-secondary);
    }

    .ops-review__artifact {
      display: flex;
      align-items: flex-start;
      gap: 10px;
      padding: 12px 16px;
      border-radius: 12px;
      background: color-mix(in srgb, var(--color-accent) 8%, white);
      border-left: 4px solid var(--color-accent);
      color: var(--color-accent);
      font-size: var(--text-sm);
    }

    .ops-review__section {
      display: flex;
      flex-direction: column;
      gap: 14px;
      padding: 18px;
      border-radius: 14px;
      border: 1px solid var(--ops-outline, rgba(55, 53, 47, 0.08));
      background: var(--color-surface, #ffffff);
    }

    .ops-review__section-header h3 {
      margin: 0 0 4px;
      font-size: var(--text-md);
      font-weight: var(--weight-semibold);
    }

    .ops-review__meta-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
    }

    .ops-review__meta-grid > div {
      padding: 12px;
      border-radius: 10px;
      background: var(--color-surface-container-low, #f3f3f4);
    }

    .ops-review__meta-grid span {
      display: block;
      margin-bottom: 6px;
      color: var(--color-text-secondary);
      font-size: var(--text-sm);
    }

    .ops-review__meta-grid strong {
      display: block;
      font-size: var(--text-md);
      font-weight: var(--weight-semibold);
    }

    .ops-review__meta-grid--full {
      grid-column: 1 / -1;
    }

    .ops-review__table-wrap {
      overflow-x: auto;
      border: 1px solid var(--ops-outline, rgba(55, 53, 47, 0.08));
      border-radius: 10px;
    }

    .ops-review__mobile-list {
      display: none;
      gap: 10px;
    }

    .ops-review__mobile-card {
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
      .ops-review__meta-grid {
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
      .ops-review__meta-grid {
        grid-template-columns: 1fr;
      }

      .ops-review__meta-grid--full {
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
export class OpsDispatchReviewStepComponent implements OnInit {
  readonly detail = input<DispatchDetailResponse | null>(null);
  readonly waybillReadback = input<WaybillResponse | null>(null);
  readonly transportForm = input.required<FormGroup>();
  readonly itemNameMap = input<ReadonlyMap<number, string>>(new Map());

  private readonly destroyRef = inject(DestroyRef);
  private readonly transportModeMap = new Map(TRANSPORT_MODE_OPTIONS.map(o => [o.value, o.label]));
  private readonly transportFormValue = signal<DispatchTransportFormValue>(EMPTY_TRANSPORT_FORM_VALUE);

  readonly formDriverName = computed(() => this.transportFormValue().driver_name);
  readonly formVehicleId = computed(() => this.transportFormValue().vehicle_id);
  readonly formDepartureTime = computed(() => {
    const v = this.transportFormValue();
    return this.recombineDateTime(v.departure_date, v.departure_time);
  });
  readonly formEstimatedArrival = computed(() => {
    const v = this.transportFormValue();
    return this.recombineDateTime(v.arrival_date, v.arrival_time);
  });
  readonly formTransportNotes = computed(() => this.transportFormValue().transport_notes);

  private recombineDateTime(date: Date | null, time: string): Date | null {
    const normalizedTime = time.trim();
    if (!date || !normalizedTime) {
      return null;
    }
    const d = new Date(date);
    if (Number.isNaN(d.getTime())) {
      return null;
    }
    const [h, m] = normalizedTime.split(':').map(Number);
    if (!Number.isInteger(h) || !Number.isInteger(m)) {
      return null;
    }
    d.setHours(h, m, 0, 0);
    return d;
  }

  ngOnInit(): void {
    const form = this.transportForm();
    merge(form.valueChanges, form.statusChanges).pipe(
      startWith(null),
      map(() => form.getRawValue() as DispatchTransportFormValue),
      takeUntilDestroyed(this.destroyRef),
    ).subscribe((value) => {
      this.transportFormValue.set(value);
    });
  }

  readonly reviewLines = computed<ReviewLine[]>(() => {
    const waybillLines = this.waybillReadback()?.waybill_payload?.line_items
      ?? this.detail()?.waybill?.waybill_payload?.line_items
      ?? [];
    if (waybillLines.length) {
      return waybillLines;
    }
    return this.detail()?.allocation?.allocation_lines ?? [];
  });

  readonly effectiveWaybillNo = computed(() =>
    this.waybillReadback()?.waybill_no
    || this.detail()?.waybill?.waybill_no
    || this.detail()?.allocation?.waybill_no
    || ''
  );

  readonly effectiveTransportModeLabel = computed(() => {
    const raw = this.waybillReadback()?.waybill_payload?.transport_mode
      || this.transportFormValue().transport_mode
      || this.detail()?.transport_mode
      || '';
    return this.transportModeMap.get(raw) || raw || 'Not specified';
  });

  readonly sourceWarehouseLabel = computed(() => {
    const payload = this.waybillReadback()?.waybill_payload ?? this.detail()?.waybill?.waybill_payload;
    if (payload?.source_warehouse_names?.length) {
      return payload.source_warehouse_names.join(', ');
    }
    if (payload?.source_warehouse_ids?.length) {
      return payload.source_warehouse_ids.join(', ');
    }
    return 'From reserved stock';
  });

  readonly destinationLabel = computed(() => {
    const payload = this.waybillReadback()?.waybill_payload ?? this.detail()?.waybill?.waybill_payload;
    if (payload?.destination_warehouse_name) {
      return payload.destination_warehouse_name;
    }
    const detailName = this.detail()?.destination_warehouse_name;
    if (detailName && detailName !== 'null') {
      return detailName;
    }
    if (payload?.agency_id) {
      return `Agency ${payload.agency_id}`;
    }
    if (this.detail()?.agency_id) {
      return `Agency ${this.detail()!.agency_id}`;
    }
    return 'Receiving destination on request';
  });

  itemLabel(line: ReviewLine): string {
    return this.itemNameMap().get(line.item_id) || `Item ${line.item_id}`;
  }

  formatSource(sourceType: string): string {
    return formatSourceType(sourceType);
  }
}
