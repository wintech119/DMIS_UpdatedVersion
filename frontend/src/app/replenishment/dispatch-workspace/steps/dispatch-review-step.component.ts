import { DatePipe, DecimalPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { MatCardModule } from '@angular/material/card';
import { MatIconModule } from '@angular/material/icon';

import { AllocationCommittedLine, WaybillLineItem, WaybillPayload } from '../../models/allocation-dispatch.model';
import { ExecutionWorkspaceStateService } from '../../execution/services/execution-workspace-state.service';
import { formatSourceType } from '../../execution/execution-status.util';

type ReviewLine = WaybillLineItem | AllocationCommittedLine;

@Component({
  selector: 'app-dispatch-review-step',
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

      @if (!effectiveWaybill()?.waybill_no) {
        <div class="dispatch-review-alert" role="status">
          <mat-icon aria-hidden="true">description</mat-icon>
          <span>The waybill number will be assigned at dispatch if it does not already exist.</span>
        </div>
      }

      <div class="dispatch-review-grid">
        <mat-card class="dispatch-review-card">
          <span class="dispatch-review-card__label">Waybill Number</span>
          <strong>{{ effectiveWaybill()?.waybill_no || current()?.waybill_no || 'Assigned on dispatch' }}</strong>
        </mat-card>

        <mat-card class="dispatch-review-card">
          <span class="dispatch-review-card__label">Dispatch Time</span>
          <strong>{{ current()?.dispatch_dtime ? (current()?.dispatch_dtime | date:'medium') : 'Pending dispatch' }}</strong>
        </mat-card>

        <mat-card class="dispatch-review-card">
          <span class="dispatch-review-card__label">Request Tracking Number</span>
          <strong>{{ current()?.request_tracking_no || 'Pending first reservation' }}</strong>
        </mat-card>

        <mat-card class="dispatch-review-card">
          <span class="dispatch-review-card__label">Package Tracking Number</span>
          <strong>{{ current()?.package_tracking_no || 'Pending first reservation' }}</strong>
        </mat-card>
      </div>

      <mat-card class="dispatch-review-section">
        <div class="dispatch-review-section__header">
          <div>
            <h3>Minimal Dispatch Document</h3>
            <p>The line summary below mirrors the minimal digital waybill or dispatch document reference for Sprint 08.</p>
          </div>
        </div>

        <div class="dispatch-review-doc">
          <div class="dispatch-review-doc__meta">
            <div>
              <span>Transport Mode</span>
              <strong>{{ effectiveWaybill()?.transport_mode || draft().transport_mode || 'Not specified' }}</strong>
            </div>
            <div>
              <span>Source Warehouse</span>
              <strong>{{ sourceWarehouseLabel() }}</strong>
            </div>
            <div>
              <span>Destination</span>
              <strong>{{ destinationLabel() }}</strong>
            </div>
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
                      <td>{{ itemLabel(line) }}</td>
                      <td>{{ batchLabel(line) }}</td>
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
                  <strong>{{ itemLabel(line) }}</strong>
                  <span>{{ batchLabel(line) }}</span>
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
              remains out of scope for Sprint 08.
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

    .dispatch-review-grid,
    .dispatch-review-doc__meta {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
    }

    .dispatch-review-card,
    .dispatch-review-section {
      border: 1px solid var(--color-border);
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
      border: 1px solid var(--color-border);
      border-radius: 10px;
    }

    .dispatch-review-table table {
      width: 100%;
      border-collapse: collapse;
    }

    .dispatch-review-table th,
    .dispatch-review-table td {
      padding: 10px 12px;
      border-bottom: 1px solid var(--color-border);
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
      border: 1px solid var(--color-border);
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
      .dispatch-review-grid,
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
    }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DispatchReviewStepComponent {
  readonly store = inject(ExecutionWorkspaceStateService);
  readonly current = this.store.current;
  readonly draft = this.store.draft;

  readonly effectiveWaybill = computed<WaybillPayload | null>(() =>
    this.store.waybill()?.waybill_payload ?? this.current()?.waybill_payload ?? null
  );

  readonly reviewLines = computed<ReviewLine[]>(() => {
    const waybillLines = this.effectiveWaybill()?.line_items ?? [];
    if (waybillLines.length) {
      return waybillLines;
    }
    return this.current()?.allocation_lines ?? [];
  });

  itemLabel(line: ReviewLine): string {
    const item = this.current()?.items?.find((entry) => entry.item_id === line.item_id);
    return item?.item_name || `Item ${line.item_id}`;
  }

  batchLabel(line: ReviewLine): string {
    return line.batch_no || `Batch ${line.batch_id}`;
  }

  sourceWarehouseLabel(): string {
    const payload = this.effectiveWaybill();
    if (payload?.source_warehouse_names?.length) {
      return payload.source_warehouse_names.join(', ');
    }
    if (payload?.source_warehouse_ids?.length) {
      return payload.source_warehouse_ids.join(', ');
    }
    return 'From reserved stock';
  }

  destinationLabel(): string {
    const payload = this.effectiveWaybill();
    if (payload?.destination_warehouse_name) {
      return payload.destination_warehouse_name;
    }
    if (payload?.agency_id) {
      return `Agency ${payload.agency_id}`;
    }
    return 'Receiving destination on request';
  }

  formatSource(sourceType: string): string {
    return formatSourceType(sourceType);
  }
}
