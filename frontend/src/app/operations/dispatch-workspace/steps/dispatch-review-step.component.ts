import { DatePipe, DecimalPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, Input, computed } from '@angular/core';
import { MatCardModule } from '@angular/material/card';
import { MatIconModule } from '@angular/material/icon';

import {
  AllocationLine,
  DispatchDetailResponse,
  WaybillLineItem,
  WaybillResponse,
} from '../../models/operations.model';
import { formatSourceType } from '../../models/operations-status.util';

type ReviewLine = WaybillLineItem | AllocationLine;

@Component({
  selector: 'app-ops-dispatch-review-step',
  standalone: true,
  imports: [
    DatePipe,
    DecimalPipe,
    MatCardModule,
    MatIconModule,
  ],
  template: `
    <div class="dispatch-review-step">
      <div class="dispatch-review-step__intro">
        <h2>Review & Dispatch</h2>
        <p>
          Finalize the operational handoff. When dispatch is recorded, reserved stock is physically deducted and the
          waybill reference becomes part of the execution record.
        </p>
      </div>

      @if (!effectiveWaybillNo()) {
        <div class="dispatch-review-alert" role="status">
          <mat-icon aria-hidden="true">description</mat-icon>
          <span>The waybill number will be assigned at dispatch if it does not already exist.</span>
        </div>
      }

      <div class="dispatch-review-grid">
        <mat-card class="dispatch-review-card">
          <span class="dispatch-review-card__label">Waybill Number</span>
          <strong>{{ effectiveWaybillNo() || 'Assigned on dispatch' }}</strong>
        </mat-card>

        <mat-card class="dispatch-review-card">
          <span class="dispatch-review-card__label">Dispatch Time</span>
          <strong>{{ detail?.dispatch_dtime ? (detail?.dispatch_dtime | date:'medium') : 'Pending dispatch' }}</strong>
        </mat-card>

        <mat-card class="dispatch-review-card">
          <span class="dispatch-review-card__label">Request Tracking Number</span>
          <strong>{{ detail?.request?.tracking_no || 'Pending' }}</strong>
        </mat-card>

        <mat-card class="dispatch-review-card">
          <span class="dispatch-review-card__label">Package Tracking Number</span>
          <strong>{{ detail?.tracking_no || 'Pending' }}</strong>
        </mat-card>
      </div>

      @if (waybillReadback) {
        <div class="artifact-badge" role="status">
          <mat-icon aria-hidden="true">info</mat-icon>
          <span>
            Artifact mode: <strong>{{ waybillReadback.artifact_mode || 'unknown' }}</strong>
            @if (!waybillReadback.persisted) {
              — Rebuilt from dispatch record, not independently persisted.
            }
          </span>
        </div>
      }

      <mat-card class="dispatch-review-section">
        <div class="dispatch-review-section__header">
          <div>
            <h3>Dispatch Document</h3>
            <p>The line summary below mirrors the minimal digital waybill or dispatch document reference.</p>
          </div>
        </div>

        <div class="dispatch-review-doc">
          <div class="dispatch-review-doc__meta">
            <div>
              <span>Transport Mode</span>
              <strong>{{ effectiveTransportMode() }}</strong>
            </div>
            <div>
              <span>Driver</span>
              <strong>{{ driverName || 'Not specified' }}</strong>
            </div>
            <div>
              <span>Vehicle</span>
              <strong>{{ vehicleIdentifier || 'Not specified' }}</strong>
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
              <strong>{{ departureTime ? (departureTime | date:'medium') : 'Not set' }}</strong>
            </div>
            <div>
              <span>ETA</span>
              <strong>{{ estimatedArrival ? (estimatedArrival | date:'medium') : 'Not set' }}</strong>
            </div>
            @if (transportNotes) {
              <div class="dispatch-review-doc__meta--full">
                <span>Transport Notes</span>
                <strong>{{ transportNotes }}</strong>
              </div>
            }
          </div>

          @if (!reviewLines().length) {
            <p class="dispatch-review-empty">No dispatch lines are available yet.</p>
          } @else {
            <div class="dispatch-review-table desktop-only">
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
                  @for (line of reviewLines(); track line.inventory_id + '-' + line.batch_id + '-' + line.item_id) {
                    <tr>
                      <td>Item {{ line.item_id }}</td>
                      <td>{{ line.batch_no || ('Batch ' + line.batch_id) }}</td>
                      <td>{{ formatSource(line.source_type || 'ON_HAND') }}</td>
                      <td>{{ line.quantity | number:'1.0-4' }}</td>
                    </tr>
                  }
                </tbody>
              </table>
            </div>

            <div class="mobile-only dispatch-review-mobile">
              @for (line of reviewLines(); track line.inventory_id + '-' + line.batch_id + '-' + line.item_id) {
                <div class="dispatch-review-mobile__card">
                  <strong>Item {{ line.item_id }}</strong>
                  <span>{{ line.batch_no || ('Batch ' + line.batch_id) }}</span>
                  <span>{{ formatSource(line.source_type || 'ON_HAND') }}</span>
                  <strong>{{ line.quantity | number:'1.0-4' }}</strong>
                </div>
              }
            </div>
          }
        </div>
      </mat-card>

      <mat-card class="dispatch-review-section">
        <div class="dispatch-review-section__header">
          <div>
            <h3>Scope Guardrail</h3>
            <p>
              This workspace stops at dispatch recording and status visibility. Receiving-agency distribution confirmation
              remains out of scope.
            </p>
          </div>
        </div>
      </mat-card>
    </div>
  `,
  styles: [`
    :host {
      display: block;
    }

    .dispatch-review-step {
      display: flex;
      flex-direction: column;
      gap: 18px;
    }

    .dispatch-review-step__intro h2 {
      margin: 0 0 6px;
      font-size: var(--text-lg);
      font-weight: var(--weight-semibold);
    }

    .dispatch-review-step__intro p,
    .dispatch-review-section__header p {
      margin: 0;
      color: var(--color-text-secondary);
    }

    .dispatch-review-alert {
      display: flex;
      align-items: flex-start;
      gap: 10px;
      padding: 14px 16px;
      border-radius: 12px;
      background: var(--color-bg-info);
      border-left: 4px solid var(--color-focus-ring);
      color: var(--color-info);
    }

    .artifact-badge {
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

    .dispatch-review-grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
    }

    .dispatch-review-doc__meta {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
    }

    .dispatch-review-doc__meta--full {
      grid-column: 1 / -1;
    }

    .dispatch-review-card,
    .dispatch-review-section {
      border: 1px solid #e5e5e2;
      box-shadow: none;
    }

    .dispatch-review-card {
      padding: 16px;
      border-radius: 12px;
      background: var(--color-surface);
    }

    .dispatch-review-card__label,
    .dispatch-review-doc__meta span {
      display: block;
      margin-bottom: 6px;
      color: var(--color-text-secondary);
      font-size: var(--text-sm);
    }

    .dispatch-review-card strong,
    .dispatch-review-doc__meta strong {
      display: block;
      font-size: var(--text-md);
      font-weight: var(--weight-semibold);
    }

    .dispatch-review-section {
      padding: 18px;
      border-radius: 14px;
    }

    .dispatch-review-section__header {
      margin-bottom: 16px;
    }

    .dispatch-review-section__header h3 {
      margin: 0 0 4px;
      font-size: var(--text-md);
      font-weight: var(--weight-semibold);
    }

    .dispatch-review-doc {
      display: flex;
      flex-direction: column;
      gap: 16px;
    }

    .dispatch-review-table {
      overflow-x: auto;
      border: 1px solid #e5e5e2;
      border-radius: 10px;
    }

    .dispatch-review-table table {
      width: 100%;
      border-collapse: collapse;
    }

    .dispatch-review-table th,
    .dispatch-review-table td {
      padding: 10px 12px;
      border-bottom: 1px solid #e5e5e2;
      text-align: left;
    }

    .dispatch-review-table th {
      background: var(--color-surface-muted);
      color: var(--color-text-secondary);
      font-size: var(--text-sm);
      font-weight: var(--weight-semibold);
    }

    .dispatch-review-mobile {
      display: none;
      gap: 10px;
    }

    .dispatch-review-mobile__card {
      display: grid;
      gap: 4px;
      padding: 12px;
      border-radius: 10px;
      background: var(--color-surface-muted);
      border: 1px solid #e5e5e2;
    }

    .dispatch-review-empty {
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
      .dispatch-review-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }

      .dispatch-review-doc__meta {
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
      .dispatch-review-grid,
      .dispatch-review-doc__meta {
        grid-template-columns: 1fr;
      }

      .dispatch-review-doc__meta--full {
        grid-column: auto;
      }
    }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class OpsDispatchReviewStepComponent {
  @Input() detail: DispatchDetailResponse | null = null;
  @Input() waybillReadback: WaybillResponse | null = null;
  @Input() transportMode = '';
  @Input() driverName = '';
  @Input() vehicleIdentifier = '';
  @Input() departureTime = '';
  @Input() estimatedArrival = '';
  @Input() transportNotes = '';

  readonly reviewLines = computed<ReviewLine[]>(() => {
    const waybillLines = this.waybillReadback?.waybill_payload?.line_items
      ?? this.detail?.waybill?.waybill_payload?.line_items
      ?? [];
    if (waybillLines.length) {
      return waybillLines;
    }
    return this.detail?.allocation?.allocation_lines ?? [];
  });

  effectiveWaybillNo(): string {
    return this.waybillReadback?.waybill_no
      || this.detail?.waybill?.waybill_no
      || this.detail?.allocation?.waybill_no
      || '';
  }

  effectiveTransportMode(): string {
    return this.waybillReadback?.waybill_payload?.transport_mode
      || this.transportMode
      || this.detail?.transport_mode
      || 'Not specified';
  }

  sourceWarehouseLabel(): string {
    const payload = this.waybillReadback?.waybill_payload ?? this.detail?.waybill?.waybill_payload;
    if (payload?.source_warehouse_names?.length) {
      return payload.source_warehouse_names.join(', ');
    }
    if (payload?.source_warehouse_ids?.length) {
      return payload.source_warehouse_ids.join(', ');
    }
    return 'From reserved stock';
  }

  destinationLabel(): string {
    const payload = this.waybillReadback?.waybill_payload ?? this.detail?.waybill?.waybill_payload;
    if (payload?.destination_warehouse_name) {
      return payload.destination_warehouse_name;
    }
    if (this.detail?.destination_warehouse_name) {
      return this.detail.destination_warehouse_name;
    }
    if (payload?.agency_id) {
      return `Agency ${payload.agency_id}`;
    }
    if (this.detail?.agency_id) {
      return `Agency ${this.detail.agency_id}`;
    }
    return 'Receiving destination on request';
  }

  formatSource(sourceType: string): string {
    return formatSourceType(sourceType);
  }
}
