import { DecimalPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, Input, computed, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { MatIconModule } from '@angular/material/icon';
import { catchError, of } from 'rxjs';

import { AllocationCandidate, AllocationSelectionPayload } from '../../models/operations.model';
import { OperationsWorkspaceStateService } from '../../services/operations-workspace-state.service';
import { formatAllocationMethod, formatExecutionStatus, formatSourceType } from '../../models/operations-status.util';
import { OpsStatusChipComponent } from '../../shared/ops-status-chip.component';
import { MasterDataService } from '../../../master-data/services/master-data.service';

interface ReviewWarehouseSubgroup {
  inventoryId: number;
  warehouseName: string;
  subtotal: number;
  rows: AllocationSelectionPayload[];
}

interface ReviewGroup {
  itemId: number;
  itemName: string;
  itemCode: string;
  selectedQty: number;
  rows: AllocationSelectionPayload[];
  warehouses: ReviewWarehouseSubgroup[];
}

@Component({
  selector: 'app-fulfillment-review-step',
  standalone: true,
  imports: [
    DecimalPipe,
    MatIconModule,
    OpsStatusChipComponent,
  ],
  styleUrls: ['../../operations-shell.scss'],
  template: `
    <div class="review-step">

      <!-- ── Tier 1: Hero Summary ──────────────────────────── -->
      <div class="ops-section">
        <div class="ops-section__header">
          <div>
            <p class="ops-section__eyebrow">Review &amp; commit</p>
            <h2 class="ops-section__title">Reservation Summary</h2>
          </div>
          <div class="review-state-cluster">
            <app-ops-status-chip
              [label]="reservationStateLabel()"
              [tone]="reservationStateTone()" />
            <span class="review-state-cluster__method">{{ formatAllocationMethod(store.selectedMethod()) }}</span>
          </div>
        </div>

        <div class="review-hero-grid">
          <div class="ops-summary-card">
            <span class="ops-summary-card__label">{{ quantityLabel() }}</span>
            <p class="ops-summary-card__value review-hero-value">
              {{ reservedQuantity() | number:'1.0-4' }}
            </p>
          </div>
          <div class="ops-summary-card">
            <span class="ops-summary-card__label">Stock Lines</span>
            <p class="ops-summary-card__value review-hero-value">
              {{ store.selectedLineCount() }}
            </p>
          </div>
        </div>
      </div>

      <!-- ── Tier 2: Alerts ────────────────────────────────── -->
      @if (submissionErrors.length) {
        <div class="ops-callout ops-callout--danger" role="alert">
          <mat-icon aria-hidden="true">error</mat-icon>
          <div>
            <strong>Resolve these items before continuing:</strong>
            <ul class="review-error-list">
              @for (error of submissionErrors; track $index) {
                <li>{{ error }}</li>
              }
            </ul>
          </div>
        </div>
      }

      @if (stockIntegrityWarning) {
        <div class="ops-callout ops-callout--warning" role="status">
          <mat-icon aria-hidden="true">warning_amber</mat-icon>
          <span>{{ stockIntegrityWarning }}</span>
        </div>
      }

      @if (store.planRequiresOverride() && !store.hasPendingOverride()) {
        <div class="ops-callout ops-callout--warning" role="status">
          <mat-icon aria-hidden="true">policy</mat-icon>
          <span>
            This selection bypasses the backend recommendation. Record the override reason before you commit the
            reservation.
          </span>
        </div>
      }

      @if (store.hasPendingOverride()) {
        <div class="ops-callout ops-callout--warning" role="status">
          <mat-icon aria-hidden="true">pending_actions</mat-icon>
          <span>
            Override approval is still pending. Dispatch stays blocked until an authorized approver completes that
            review.
          </span>
        </div>
      }

      @if (overrideApprovalHint) {
        <div class="ops-callout" role="status">
          <mat-icon aria-hidden="true">visibility</mat-icon>
          <span>{{ overrideApprovalHint }}</span>
        </div>
      }

      <!-- ── Tier 3: Stock Lines (Primary Content) ─────────── -->
      <div class="ops-section">
        <div class="ops-section__header">
          <div>
            <p class="ops-section__eyebrow">
              <mat-icon class="review-icon--inline" aria-hidden="true">inventory</mat-icon>
              Selected stock
            </p>
            <h2 class="ops-section__title">Reserved Lines</h2>
          </div>
        </div>

        @if (!reviewGroups().length) {
          <div class="ops-empty">
            <p class="ops-empty__title">No stock lines selected</p>
            <p class="ops-empty__copy">Go back to the selection step to choose stock lines.</p>
          </div>
        } @else {
          <!-- Desktop: single unified table, items grouped, warehouses sub-grouped -->
          <div class="review-table-wrap review-table-scroll desktop-only">
            <table class="review-table">
              <thead>
                <tr>
                  <th>Item</th>
                  <th>Batch / Lot</th>
                  <th>Source</th>
                  <th>Warehouse</th>
                  <th class="review-col--qty">Qty</th>
                </tr>
              </thead>
              <tbody>
                @for (group of reviewGroups(); track group.itemId) {
                  @for (wh of group.warehouses; track wh.inventoryId; let firstWh = $first) {
                    @if (group.warehouses.length > 1) {
                      <tr class="review-row--warehouse-header">
                        <td class="review-cell--item">
                          @if (firstWh) {
                            <span class="review-item-name">{{ group.itemName }}</span>
                            <span class="review-item-meta">{{ group.itemCode }} · {{ group.selectedQty | number:'1.0-4' }} total</span>
                          }
                        </td>
                        <td colspan="3" class="review-cell--warehouse-label">
                          <mat-icon class="review-icon--inline" aria-hidden="true">warehouse</mat-icon>
                          {{ wh.warehouseName }}
                        </td>
                        <td class="review-col--qty review-cell--warehouse-subtotal">
                          {{ wh.subtotal | number:'1.0-4' }}
                        </td>
                      </tr>
                    }
                    @for (row of wh.rows; track row.inventory_id + '-' + row.batch_id + '-' + row.source_type + '-' + (row.source_record_id ?? ''); let firstRow = $first) {
                      <tr
                        [class.review-row--group-start]="firstWh && firstRow && group.warehouses.length === 1"
                        [class.review-row--sub]="group.warehouses.length > 1">
                        <td class="review-cell--item">
                          @if (firstWh && firstRow && group.warehouses.length === 1) {
                            <span class="review-item-name">{{ group.itemName }}</span>
                            <span class="review-item-meta">{{ group.itemCode }} · {{ group.selectedQty | number:'1.0-4' }} total</span>
                          }
                        </td>
                        <td class="review-cell--truncate" [title]="batchLabel(row)">{{ batchLabel(row) }}</td>
                        <td><span class="ops-chip ops-chip--outline">{{ formatSource(row.source_type) }}</span></td>
                        <td class="review-cell--truncate" [title]="warehouseLabel(row)">{{ warehouseLabel(row) }}</td>
                        <td class="review-col--qty">{{ row.quantity | number:'1.0-4' }}</td>
                      </tr>
                    }
                  }
                }
              </tbody>
            </table>
          </div>

          <!-- Mobile: compact card list, items grouped, warehouses sub-grouped -->
          <div class="review-mobile-scroll mobile-only">
            @for (group of reviewGroups(); track group.itemId) {
              <div class="review-mobile-group">
                <div class="review-mobile-group__header">
                  <span class="review-item-name">{{ group.itemName }}</span>
                  <strong>{{ group.selectedQty | number:'1.0-4' }}</strong>
                </div>
                @for (wh of group.warehouses; track wh.inventoryId) {
                  @if (group.warehouses.length > 1) {
                    <div class="review-mobile-warehouse-header">
                      <mat-icon class="review-icon--inline" aria-hidden="true">warehouse</mat-icon>
                      <span>{{ wh.warehouseName }}</span>
                      <strong>{{ wh.subtotal | number:'1.0-4' }}</strong>
                    </div>
                  }
                  @for (row of wh.rows; track row.inventory_id + '-' + row.batch_id + '-' + row.source_type + '-' + (row.source_record_id ?? '')) {
                    <div class="review-mobile-row">
                      <div class="review-mobile-row__lead">
                        <span>{{ batchLabel(row) }}</span>
                        <span class="ops-chip ops-chip--outline">{{ formatSource(row.source_type) }}</span>
                        <span class="review-mobile-row__warehouse">{{ warehouseLabel(row) }}</span>
                      </div>
                      <strong>{{ row.quantity | number:'1.0-4' }}</strong>
                    </div>
                  }
                }
              </div>
            }
          </div>
        }
      </div>

      <!-- ── Tier 4: References ────────────────────────────── -->
      <div class="ops-section">
        <div class="ops-section__header">
          <div>
            <p class="ops-section__eyebrow">
              <mat-icon class="review-icon--inline" aria-hidden="true">tag</mat-icon>
              References
            </p>
            <h2 class="ops-section__title">Tracking &amp; Method</h2>
          </div>
        </div>

        <div class="review-ref-grid">
          <div class="ops-figure review-ref--highlight">
            <p class="ops-figure__label">
              <mat-icon class="review-icon--inline" aria-hidden="true">local_shipping</mat-icon>
              Destination Warehouse
            </p>
            <p class="ops-figure__value">{{ destinationWarehouseLabel() }}</p>
          </div>
          <div class="ops-figure">
            <p class="ops-figure__label">Request Tracking</p>
            <p class="ops-figure__value">{{ packageDetail()?.request?.tracking_no || 'Generated on commit' }}</p>
          </div>
          <div class="ops-figure">
            <p class="ops-figure__label">Package Tracking</p>
            <p class="ops-figure__value">{{ packageDetail()?.package?.tracking_no || 'Generated on commit' }}</p>
          </div>
          <div class="ops-figure">
            <p class="ops-figure__label">Dispatch Document</p>
            <p class="ops-figure__value">{{ packageDetail()?.allocation?.waybill_no || 'Assigned on dispatch' }}</p>
          </div>
          <div class="ops-figure">
            <p class="ops-figure__label">Selection Method</p>
            <p class="ops-figure__value">{{ formatAllocationMethod(store.selectedMethod()) }}</p>
          </div>
        </div>
      </div>

      <!-- ── Pre-flight Checklist ──────────────────────────── -->
      <div class="ops-callout review-preflight"
           [class.ops-callout--warning]="store.hasPendingOverride()"
           [class.ops-callout--success]="!store.hasPendingOverride() && store.hasCommittedAllocation()"
           role="status">
        <mat-icon aria-hidden="true">
          {{ store.hasPendingOverride() ? 'pending_actions' : 'task_alt' }}
        </mat-icon>
        <div>
          <strong class="review-preflight__title">
            {{ store.hasPendingOverride() ? 'Override Review' : 'Commit Outcome' }}
          </strong>
          <p class="review-preflight__copy">{{ commitOutcomeCopy() }}</p>
          <p class="review-preflight__detail">
            Committing will reserve <strong>{{ reservedQuantity() | number:'1.0-4' }}</strong> units
            across <strong>{{ store.selectedLineCount() }}</strong> stock lines.
            Inventory deducts only on dispatch.
          </p>
        </div>
      </div>

    </div>
  `,
  styles: [`
    :host {
      display: block;
    }

    /* ── Root layout ────────────────────────────────────── */

    .review-step {
      display: flex;
      flex-direction: column;
      gap: 1.25rem;
    }

    /* ── Tier 1: Hero summary ───────────────────────────── */

    .review-state-cluster {
      display: flex;
      flex-direction: column;
      align-items: flex-end;
      gap: 0.25rem;
    }

    .review-state-cluster__method {
      font-size: 0.78rem;
      color: var(--color-text-secondary);
      letter-spacing: 0.06em;
    }

    .review-hero-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 0.75rem;
    }

    .review-hero-value {
      font-size: clamp(1.75rem, 3vw, 2.6rem);
      line-height: 1;
      letter-spacing: -0.05em;
    }

    /* ── Tier 2: Alerts ─────────────────────────────────── */

    .review-error-list {
      margin: 0.5rem 0 0 1.125rem;
      padding: 0;
    }

    /* ── Tier 3: Stock lines (condensed) ───────────────── */

    .review-icon--inline {
      font-size: 14px;
      width: 14px;
      height: 14px;
      vertical-align: -2px;
    }

    .review-table-wrap {
      overflow-x: auto;
      border: 1px solid var(--color-border, #e5e5e2);
      border-radius: 0.75rem;
    }

    .review-table-scroll {
      max-height: 26rem;
      overflow-y: auto;
    }

    .review-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.84rem;
    }

    .review-table thead {
      position: sticky;
      top: 0;
      z-index: 1;
    }

    .review-table th {
      padding: 0.5rem 0.65rem;
      background: var(--color-surface-container-low, #f3f3f4);
      color: var(--color-text-secondary);
      font-size: 0.68rem;
      font-weight: 700;
      letter-spacing: 0.16em;
      text-transform: uppercase;
      text-align: left;
      border-bottom: 1px solid var(--color-border, #e5e5e2);
    }

    .review-table td {
      padding: 0.38rem 0.65rem;
      border-bottom: 1px solid color-mix(in srgb, var(--color-border, #e5e5e2) 50%, transparent);
      vertical-align: middle;
    }

    .review-table tbody tr:hover {
      background: color-mix(in srgb, var(--color-surface-container-high, #e8e8e8) 40%, transparent);
    }

    .review-row--group-start td {
      border-top: 1px solid var(--color-border, #e5e5e2);
    }

    .review-row--group-start:first-child td {
      border-top: none;
    }

    .review-row--warehouse-header td {
      background: color-mix(in srgb, var(--color-surface-container-low, #f3f3f4) 70%, transparent);
      border-top: 1px solid var(--color-border, #e5e5e2);
      font-size: 0.78rem;
      font-weight: 600;
      color: var(--color-text-secondary, #787774);
      padding-top: 0.4rem;
      padding-bottom: 0.4rem;
    }

    .review-row--warehouse-header:first-child td {
      border-top: none;
    }

    .review-cell--warehouse-label {
      letter-spacing: 0.02em;
      text-transform: uppercase;
    }

    .review-cell--warehouse-label .review-icon--inline {
      margin-right: 0.25rem;
      vertical-align: -2px;
    }

    .review-cell--warehouse-subtotal {
      color: var(--color-text-primary, #37352F);
      font-variant-numeric: tabular-nums;
    }

    .review-row--sub td {
      border-top: 1px dashed color-mix(in srgb, var(--color-border, #e5e5e2) 60%, transparent);
    }

    .review-cell--item {
      vertical-align: top;
      padding-top: 0.5rem;
      min-width: 10rem;
    }

    .review-item-name {
      display: block;
      font-weight: 600;
      font-size: 0.84rem;
      line-height: 1.25;
      color: var(--color-text-primary);
    }

    .review-item-meta {
      display: block;
      font-size: 0.72rem;
      color: var(--color-text-secondary);
      margin-top: 1px;
    }

    .review-cell--truncate {
      max-width: 12rem;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .review-col--qty {
      text-align: right;
      font-variant-numeric: tabular-nums;
      font-weight: 600;
    }

    /* ── Mobile stock lines ─────────────────────────────── */

    .review-mobile-scroll {
      display: grid;
      gap: 0.5rem;
      max-height: 26rem;
      overflow-y: auto;
    }

    .review-mobile-group {
      border: 1px solid var(--color-border, #e5e5e2);
      border-radius: 0.6rem;
      overflow: hidden;
    }

    .review-mobile-group__header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 0.5rem;
      padding: 0.45rem 0.65rem;
      background: var(--color-surface-container-low, #f3f3f4);
      font-size: 0.82rem;
    }

    .review-mobile-warehouse-header {
      display: flex;
      align-items: center;
      gap: 0.4rem;
      padding: 0.3rem 0.65rem;
      background: color-mix(in srgb, var(--color-surface-container-low, #f3f3f4) 50%, transparent);
      font-size: 0.74rem;
      font-weight: 600;
      color: var(--color-text-secondary, #787774);
      text-transform: uppercase;
      letter-spacing: 0.02em;
      border-top: 1px solid var(--color-border, #e5e5e2);
    }

    .review-mobile-warehouse-header strong {
      margin-left: auto;
      color: var(--color-text-primary, #37352F);
      font-variant-numeric: tabular-nums;
      text-transform: none;
    }

    .review-mobile-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 0.5rem;
      padding: 0.35rem 0.65rem;
      font-size: 0.8rem;
      border-top: 1px solid color-mix(in srgb, var(--color-border, #e5e5e2) 50%, transparent);
    }

    .review-mobile-row__lead {
      display: flex;
      align-items: center;
      gap: 0.4rem;
      min-width: 0;
      overflow: hidden;
    }

    .review-mobile-row__lead > span:first-child {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .review-mobile-row__warehouse {
      color: var(--color-text-secondary, #787774);
      font-size: 0.75rem;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      max-width: 120px;
    }

    .desktop-only {
      display: block;
    }

    .mobile-only {
      display: none;
    }

    /* ── Tier 4: References ─────────────────────────────── */

    .review-ref-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(10rem, 1fr));
      gap: 0.75rem;
    }

    .review-ref--highlight {
      padding: 0.6rem 0.75rem;
      border-radius: 0.6rem;
      background: var(--color-surface-container-low, #f3f3f4);
    }

    /* ── Pre-flight checklist ───────────────────────────── */

    .review-preflight {
      border-left: 4px solid var(--color-border, #e5e5e2);
    }

    :host .ops-callout--warning.review-preflight {
      border-left-color: #d97706;
    }

    :host .ops-callout--success.review-preflight {
      border-left-color: #16a34a;
    }

    .review-preflight__title {
      display: block;
      font-size: 0.92rem;
      margin-bottom: 0.25rem;
    }

    .review-preflight__copy {
      margin: 0;
      font-size: 0.88rem;
      line-height: 1.55;
    }

    .review-preflight__detail {
      margin: 0.5rem 0 0;
      font-size: 0.82rem;
      opacity: 0.85;
    }

    /* ── Responsive ─────────────────────────────────────── */

    @media (max-width: 960px) {
      .review-ref-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
    }

    @media (max-width: 768px) {
      .review-state-cluster {
        align-items: flex-start;
      }

      .desktop-only {
        display: none;
      }

      .mobile-only {
        display: grid;
      }
    }

    @media (max-width: 520px) {
      .review-hero-grid,
      .review-ref-grid {
        grid-template-columns: 1fr;
      }
    }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FulfillmentReviewStepComponent {
  @Input() submissionErrors: string[] = [];
  @Input() stockIntegrityWarning: string | null = null;
  @Input() overrideApprovalHint: string | null = null;
  @Input() canApproveOverride = false;

  readonly store = inject(OperationsWorkspaceStateService);
  readonly packageDetail = this.store.packageDetail;
  private readonly masterData = inject(MasterDataService);
  private readonly warehouseOptions = toSignal(
    this.masterData.lookup('warehouses').pipe(catchError(() => of([]))),
    { initialValue: [] },
  );

  readonly destinationWarehouseLabel = computed(() => {
    // Prefer the backend-resolved name (available after commit)
    const backendName = this.packageDetail()?.package?.destination_warehouse_name;
    if (backendName) {
      return backendName;
    }
    // Fall back to resolving from draft ID against master data lookup
    const draftId = this.store.draft().to_inventory_id;
    if (draftId) {
      const match = this.warehouseOptions().find((wh) => String(wh.value) === String(draftId));
      return match?.label || `Warehouse ${draftId}`;
    }
    return 'Not assigned';
  });

  readonly reviewGroups = computed<ReviewGroup[]>(() => {
    const options = this.store.options()?.items ?? [];
    return options
      .map((item) => {
        const rows = this.store.getSelectedRows(item.item_id).filter((row) => this.toNumber(row.quantity) > 0);
        const warehouses = this.buildWarehouseSubgroups(rows);
        return {
          itemId: item.item_id,
          itemName: item.item_name || `Item ${item.item_id}`,
          itemCode: item.item_code || `Item ID ${item.item_id}`,
          selectedQty: rows.reduce((sum, row) => sum + this.toNumber(row.quantity), 0),
          rows,
          warehouses,
        };
      })
      .filter((group) => group.rows.length > 0);
  });

  private buildWarehouseSubgroups(rows: AllocationSelectionPayload[]): ReviewWarehouseSubgroup[] {
    const map = new Map<number, ReviewWarehouseSubgroup>();
    for (const row of rows) {
      const key = row.inventory_id;
      if (!map.has(key)) {
        map.set(key, {
          inventoryId: key,
          warehouseName: this.warehouseLabel(row),
          subtotal: 0,
          rows: [],
        });
      }
      const entry = map.get(key)!;
      entry.rows.push(row);
      entry.subtotal += this.toNumber(row.quantity);
    }
    return [...map.values()].sort((a, b) => a.warehouseName.localeCompare(b.warehouseName));
  }

  reservationStateLabel(): string {
    if (this.store.hasPendingOverride()) {
      return 'Pending override approval';
    }
    if (this.store.hasCommittedAllocation()) {
      return 'Reserved';
    }
    return 'Not reserved yet';
  }

  reservationStateTone(): 'warning' | 'success' | 'neutral' {
    if (this.store.hasPendingOverride()) {
      return 'warning';
    }
    if (this.store.hasCommittedAllocation()) {
      return 'success';
    }
    return 'neutral';
  }

  quantityLabel(): string {
    return this.store.hasCommittedAllocation() ? 'Reserved Quantity' : 'Quantity To Reserve';
  }

  reservedQuantity(): number {
    const summaryQty = this.toNumber(this.packageDetail()?.allocation?.reserved_stock_summary?.total_qty);
    return summaryQty || this.store.totalSelectedQty();
  }

  batchLabel(row: AllocationSelectionPayload): string {
    const candidate = this.lookupCandidate(row);
    return candidate?.batch_no || `Batch ${row.batch_id}`;
  }

  warehouseLabel(row: AllocationSelectionPayload): string {
    const candidate = this.lookupCandidate(row);
    return candidate?.warehouse_name || `Inventory ${row.inventory_id}`;
  }

  formatSource(sourceType: string | undefined): string {
    return formatSourceType(sourceType);
  }

  formatAllocationMethod(value: unknown): string {
    return formatAllocationMethod(String(value ?? ''));
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
        && String(candidate.source_type).toUpperCase() === String(row.source_type ?? '').toUpperCase()
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
