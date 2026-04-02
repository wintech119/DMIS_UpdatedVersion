import { ChangeDetectionStrategy, Component, Input, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';

import { MasterDataService } from '../../../master-data/services/master-data.service';
import { OVERRIDE_REASON_OPTIONS, TRANSPORT_MODE_OPTIONS } from '../../models/operations.model';
import { OperationsWorkspaceStateService } from '../../services/operations-workspace-state.service';

@Component({
  selector: 'app-fulfillment-details-step',
  standalone: true,
  imports: [
    FormsModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatSelectModule,
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
      gap: 10px;
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
  readonly store = inject(OperationsWorkspaceStateService);
  readonly draft = this.store.draft;

  readonly warehouseOptions = toSignal(this.masterData.lookup('warehouses'), { initialValue: [] });
  readonly transportModeOptions = TRANSPORT_MODE_OPTIONS;
  readonly overrideOptions = OVERRIDE_REASON_OPTIONS;

  normalizeText(value: unknown): string {
    return String(value ?? '');
  }
}
