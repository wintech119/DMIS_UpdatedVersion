import { ChangeDetectionStrategy, Component, Input, computed, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatRadioModule } from '@angular/material/radio';
import { MatSelectModule } from '@angular/material/select';

import { MasterDataService } from '../../../master-data/services/master-data.service';
import { AuthRbacService } from '../../../replenishment/services/auth-rbac.service';
import { DmisNotificationService } from '../../../replenishment/services/notification.service';
import {
  FULFILLMENT_MODE_OPTIONS,
  FulfillmentMode,
  OVERRIDE_REASON_OPTIONS,
  TRANSPORT_MODE_OPTIONS,
} from '../../models/operations.model';
import { OperationsWorkspaceStateService } from '../../services/operations-workspace-state.service';
import {
  OpsStagingCardApplyEvent,
  OpsStagingRecommendationCardComponent,
} from '../../shared/ops-staging-recommendation-card.component';

@Component({
  selector: 'app-fulfillment-details-step',
  standalone: true,
  imports: [
    FormsModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatRadioModule,
    MatSelectModule,
    OpsStagingRecommendationCardComponent,
  ],
  template: `
    <div class="ops-details">
      <div class="ops-details__header">
        <h2>Operational Details</h2>
        @if (lockOperationalFields) {
          <span class="ops-details__badge ops-details__badge--lock" role="status">
            <mat-icon aria-hidden="true">lock</mat-icon> Read-only
          </span>
        }
      </div>

      <section class="ops-details__mode" aria-label="Fulfillment mode">
        <header class="ops-details__mode-header">
          <strong>Fulfillment mode</strong>
          <span class="ops-details__mode-copy">
            Choose how this package moves from source warehouse to beneficiary.
          </span>
        </header>
        <mat-radio-group
          class="ops-details__mode-group"
          aria-label="Select fulfillment mode"
          [value]="draft().fulfillment_mode"
          (change)="onFulfillmentModeChange($event.value)"
          [disabled]="lockOperationalFields || !canSetFulfillmentMode()">
          @for (option of fulfillmentModeOptions; track option.value) {
            <mat-radio-button [value]="option.value" class="ops-details__mode-option">
              <span class="ops-details__mode-label">{{ option.label }}</span>
              <span class="ops-details__mode-hint">{{ option.hint }}</span>
            </mat-radio-button>
          }
        </mat-radio-group>
        @if (!canSetFulfillmentMode()) {
          <p class="ops-details__mode-locked" role="note">
            <mat-icon aria-hidden="true">lock</mat-icon>
            You do not have permission to change the fulfillment mode.
          </p>
        }
      </section>

      @if (store.isStagedFulfillment()) {
        <app-ops-staging-recommendation-card
          [recommendation]="store.stagingRecommendation()"
          [currentStagingWarehouseId]="store.stagingWarehouseId()"
          [basis]="store.stagingSelectionBasis()"
          [recommendationLoading]="store.recommendationLoading()"
          [recommendationError]="store.recommendationError()"
          [saving]="savingStagingMode()"
          [disabled]="lockOperationalFields || !canSetFulfillmentMode()"
          (applied)="onStagingApplied($event)" />
      }

      <div class="ops-details__form">
        <mat-form-field appearance="outline" subscriptSizing="dynamic">
          <mat-label>Destination Warehouse</mat-label>
          <mat-select
            [ngModel]="draft().to_inventory_id"
            (ngModelChange)="store.patchDraft({ to_inventory_id: normalizeText($event) })"
            [disabled]="lockOperationalFields"
            aria-label="Select destination warehouse">
            @for (wh of warehouseOptions(); track wh.value) {
              <mat-option [value]="wh.value">{{ wh.label }}</mat-option>
            }
          </mat-select>
        </mat-form-field>

        <mat-form-field appearance="outline" subscriptSizing="dynamic">
          <mat-label>Transport Mode</mat-label>
          <mat-select
            [ngModel]="draft().transport_mode"
            (ngModelChange)="store.patchDraft({ transport_mode: normalizeText($event) })"
            [disabled]="lockOperationalFields"
            aria-label="Select transport mode">
            @for (mode of transportModeOptions; track mode.value) {
              <mat-option [value]="mode.value">{{ mode.label }}</mat-option>
            }
          </mat-select>
        </mat-form-field>

        <mat-form-field appearance="outline" class="ops-details__field--span" subscriptSizing="dynamic">
          <mat-label>Further Instructions</mat-label>
          <textarea
            matInput
            rows="2"
            [ngModel]="draft().comments_text"
            (ngModelChange)="store.patchDraft({ comments_text: normalizeText($event) })"
            placeholder="For the inventory clerk (e.g., fragile, cold chain, priority)"
            [disabled]="lockOperationalFields"
          ></textarea>
        </mat-form-field>
      </div>

      @if (store.planRequiresOverride() || store.hasPendingOverride()) {
        <div class="ops-details__override">
          <div class="ops-details__override-header">
            <mat-icon aria-hidden="true">warning_amber</mat-icon>
            <div>
              <strong>Rule Bypass</strong>
              <span>Plan deviates from recommended stock order.</span>
            </div>
          </div>

          <div class="ops-details__override-fields">
            <mat-form-field appearance="outline" subscriptSizing="dynamic">
              <mat-label>Override Reason</mat-label>
              <mat-select
                [ngModel]="draft().override_reason_code"
                (ngModelChange)="store.patchDraft({ override_reason_code: normalizeText($event) })"
                [disabled]="lockOperationalFields"
                aria-label="Select override reason">
                @for (option of overrideOptions; track option.value) {
                  <mat-option [value]="option.value">{{ option.label }}</mat-option>
                }
              </mat-select>
            </mat-form-field>

            <mat-form-field appearance="outline" subscriptSizing="dynamic">
              <mat-label>Override Note</mat-label>
              <textarea
                matInput
                rows="2"
                [ngModel]="draft().override_note"
                (ngModelChange)="store.patchDraft({ override_note: normalizeText($event) })"
                placeholder="Operational reason for the bypass"
                [disabled]="lockOperationalFields"
              ></textarea>
            </mat-form-field>
          </div>
        </div>
      }
    </div>
  `,
  styles: [`
    :host {
      display: block;
      --mat-form-field-container-height: 40px;
    }

    .ops-details {
      display: flex;
      flex-direction: column;
      gap: 14px;
    }

    /* ── Mode selector ── */

    .ops-details__mode {
      display: flex;
      flex-direction: column;
      gap: 10px;
      padding: 14px 16px;
      border: 1px solid var(--ops-outline, rgba(55, 53, 47, 0.08));
      border-radius: var(--ops-radius-md, 10px);
      background: var(--ops-card, #fbfaf7);
    }

    .ops-details__mode-header {
      display: flex;
      flex-direction: column;
      gap: 2px;
    }

    .ops-details__mode-header strong {
      font-size: 0.92rem;
      color: var(--ops-ink, #37352F);
    }

    .ops-details__mode-copy {
      font-size: 0.82rem;
      color: var(--ops-ink-muted, #787774);
    }

    .ops-details__mode-group {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 10px;
    }

    .ops-details__mode-option {
      display: flex;
      flex-direction: column;
      padding: 8px 4px;
    }

    .ops-details__mode-label {
      font-weight: 600;
      color: var(--ops-ink, #37352F);
    }

    .ops-details__mode-hint {
      display: block;
      font-size: 0.78rem;
      color: var(--ops-ink-muted, #787774);
      margin-top: 2px;
    }

    .ops-details__mode-locked {
      margin: 0;
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 0.82rem;
      color: var(--ops-ink-muted, #787774);
    }

    .ops-details__mode-locked mat-icon {
      width: 16px;
      height: 16px;
      font-size: 16px;
    }

    /* ── Header row ── */

    .ops-details__header {
      display: flex;
      align-items: center;
      gap: 10px;
    }

    .ops-details__header h2 {
      margin: 0;
      font-size: var(--text-lg);
      font-weight: var(--weight-semibold);
    }

    .ops-details__badge {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 2px 10px;
      border-radius: 999px;
      font-size: 0.72rem;
      font-weight: 600;
      line-height: 1;
    }

    .ops-details__badge mat-icon {
      width: 14px;
      height: 14px;
      font-size: 14px;
    }

    .ops-details__badge--lock {
      background: var(--color-bg-warning, #fde8b1);
      color: var(--color-watch, #6e4200);
    }

    /* ── Form grid ── */

    .ops-details__form {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
    }

    .ops-details__field--span {
      grid-column: 1 / -1;
    }

    /* ── Override section ── */

    .ops-details__override {
      padding: 12px 14px;
      border-radius: 10px;
      border: 1px solid color-mix(in srgb, var(--color-warning) 30%, white);
      background: var(--color-bg-warning);
    }

    .ops-details__override-header {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 10px;
      color: var(--color-watch, #6e4200);
    }

    .ops-details__override-header mat-icon {
      width: 18px;
      height: 18px;
      font-size: 18px;
      flex-shrink: 0;
    }

    .ops-details__override-header strong {
      font-size: var(--text-sm);
      display: block;
    }

    .ops-details__override-header span {
      font-size: 0.78rem;
      opacity: 0.8;
    }

    .ops-details__override-fields {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
    }

    @media (max-width: 960px) {
      .ops-details__form,
      .ops-details__override-fields {
        grid-template-columns: 1fr;
      }

      .ops-details__field--span {
        grid-column: auto;
      }
    }

    @media (prefers-reduced-motion: reduce) {
      .ops-details__override {
        transition: none;
      }
    }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FulfillmentDetailsStepComponent {
  @Input() lockOperationalFields = false;

  private readonly masterData = inject(MasterDataService);
  private readonly auth = inject(AuthRbacService);
  private readonly notifications = inject(DmisNotificationService);
  readonly store = inject(OperationsWorkspaceStateService);
  readonly draft = this.store.draft;

  readonly warehouseOptions = toSignal(this.masterData.lookup('warehouses'), { initialValue: [] });
  readonly transportModeOptions = TRANSPORT_MODE_OPTIONS;
  readonly overrideOptions = OVERRIDE_REASON_OPTIONS;
  readonly fulfillmentModeOptions = FULFILLMENT_MODE_OPTIONS;

  readonly canSetFulfillmentMode = computed(() =>
    this.auth.hasPermission('operations.fulfillment_mode.set'),
  );

  readonly savingStagingMode = computed(() => this.store.loading());

  normalizeText(value: unknown): string {
    return String(value ?? '');
  }

  onFulfillmentModeChange(mode: FulfillmentMode): void {
    if (!mode || mode === this.draft().fulfillment_mode) {
      return;
    }
    const reliefrqstId = this.store.reliefrqstId();
    const stagingWarehouseId = this.draft().staging_warehouse_id
      ? Number(this.draft().staging_warehouse_id)
      : null;
    const overrideReason = this.draft().staging_override_reason || null;
    if (!reliefrqstId) {
      this.store.patchDraft({ fulfillment_mode: mode });
      return;
    }
    if (mode !== 'DIRECT' && this.store.reliefrqstId()) {
      this.store.loadStagingRecommendation(this.store.reliefrqstId());
    }
    this.store.saveFulfillmentModeDraft(mode, stagingWarehouseId, overrideReason).subscribe({
      next: () => this.notifications.showSuccess('Fulfillment mode updated.'),
      error: () => this.notifications.showError('Failed to update fulfillment mode.'),
    });
  }

  onStagingApplied(event: OpsStagingCardApplyEvent): void {
    const mode = this.draft().fulfillment_mode;
    this.store
      .saveFulfillmentModeDraft(
        mode,
        event.staging_warehouse_id,
        event.staging_override_reason,
      )
      .subscribe({
        next: () => this.notifications.showSuccess('Staging hub updated.'),
        error: () => this.notifications.showError('Failed to update staging hub.'),
      });
  }
}
