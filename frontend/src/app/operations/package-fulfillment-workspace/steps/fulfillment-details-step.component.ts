import { ChangeDetectionStrategy, Component, Input, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';

import { OVERRIDE_REASON_OPTIONS } from '../../models/operations.model';
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
    <div class="details-step">
      <div class="details-step__intro">
        <h2>Operational Details</h2>
        <p>
          Capture the package context that becomes part of the formal reservation record. Stock is reserved only after
          the allocation is committed. Physical deduction happens later on dispatch.
        </p>
      </div>

      @if (lockOperationalFields) {
        <div class="details-alert details-alert--soft" role="status">
          <mat-icon aria-hidden="true">lock</mat-icon>
          <span>
            This routed reservation is read-only during override approval review so the submitted plan stays intact for
            approvers.
          </span>
        </div>
      } @else {
        <div class="details-alert details-alert--soft" role="status">
          <mat-icon aria-hidden="true">info</mat-icon>
          <span>
            Set the destination warehouse and transport mode for this package. These values carry into the dispatch
            workspace and waybill.
          </span>
        </div>
      }

      <div class="details-grid">
        <mat-form-field appearance="outline" class="details-field">
          <mat-label>Destination Warehouse ID</mat-label>
          <input
            matInput
            type="number"
            min="1"
            [ngModel]="draft().to_inventory_id"
            (ngModelChange)="store.patchDraft({ to_inventory_id: sanitizeInteger($event) })"
            [disabled]="lockOperationalFields"
          />
          <mat-hint>Numeric warehouse / inventory identifier for the receiving site.</mat-hint>
        </mat-form-field>

        <mat-form-field appearance="outline" class="details-field">
          <mat-label>Transport Mode</mat-label>
          <input
            matInput
            [ngModel]="draft().transport_mode"
            (ngModelChange)="store.patchDraft({ transport_mode: normalizeText($event) })"
            placeholder="TRUCK, VAN, AIR, etc."
            [disabled]="lockOperationalFields"
          />
          <mat-hint>Optional now, but shown again before dispatch.</mat-hint>
        </mat-form-field>
      </div>

      <div class="details-grid details-grid--notes">
        <mat-form-field appearance="outline" class="details-field">
          <mat-label>Package Comments</mat-label>
          <textarea
            matInput
            rows="4"
            [ngModel]="draft().comments_text"
            (ngModelChange)="store.patchDraft({ comments_text: normalizeText($event) })"
            placeholder="Notes for packaging, loading, or handoff preparation"
            [disabled]="lockOperationalFields"
          ></textarea>
        </mat-form-field>
      </div>

      @if (store.planRequiresOverride() || store.hasPendingOverride()) {
        <div class="details-override">
          <div class="details-override__header">
            <h3>Rule Bypass Visibility</h3>
            <p>
              The current plan bypasses the recommended stock order. A supervisor must be able to see why this happened.
            </p>
          </div>

          <div class="details-grid">
            <mat-form-field appearance="outline" class="details-field">
              <mat-label>Override Reason</mat-label>
              <mat-select
                [ngModel]="draft().override_reason_code"
                (ngModelChange)="store.patchDraft({ override_reason_code: normalizeText($event) })"
                [disabled]="lockOperationalFields"
              >
                @for (option of overrideOptions; track option.value) {
                  <mat-option [value]="option.value">{{ option.label }}</mat-option>
                }
              </mat-select>
              <mat-hint>Visible to supervisors when a FEFO/FIFO or source order bypass is submitted.</mat-hint>
            </mat-form-field>

            <mat-form-field appearance="outline" class="details-field details-field--full">
              <mat-label>Override Note</mat-label>
              <textarea
                matInput
                rows="4"
                [ngModel]="draft().override_note"
                (ngModelChange)="store.patchDraft({ override_note: normalizeText($event) })"
                placeholder="Explain the operational reason for the rule bypass"
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
    }

    .details-step {
      display: flex;
      flex-direction: column;
      gap: 18px;
    }

    .details-step__intro h2 {
      margin: 0 0 6px;
      font-size: var(--text-lg);
      font-weight: var(--weight-semibold);
    }

    .details-step__intro p,
    .details-override__header p {
      margin: 0;
      color: var(--color-text-secondary);
    }

    .details-alert {
      display: flex;
      align-items: flex-start;
      gap: 10px;
      padding: 14px 16px;
      border-radius: 12px;
      background: var(--color-bg-info);
      border-left: 4px solid var(--color-focus-ring);
      color: var(--color-info);
    }

    .details-alert--soft {
      background: color-mix(in srgb, var(--color-accent) 8%, white);
      border-left-color: var(--color-accent);
      color: var(--color-accent);
    }

    .details-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 16px;
    }

    .details-grid--notes {
      grid-template-columns: 1fr;
    }

    .details-field {
      width: 100%;
    }

    .details-field--full {
      grid-column: 1 / -1;
    }

    .details-override {
      padding: 18px;
      border-radius: 14px;
      border: 1px solid color-mix(in srgb, var(--color-warning) 30%, white);
      background: var(--color-bg-warning);
    }

    .details-override__header {
      margin-bottom: 14px;
    }

    .details-override__header h3 {
      margin: 0 0 4px;
      font-size: var(--text-md);
      font-weight: var(--weight-semibold);
      color: var(--color-watch);
    }

    @media (max-width: 960px) {
      .details-grid {
        grid-template-columns: 1fr;
      }
    }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FulfillmentDetailsStepComponent {
  @Input() lockOperationalFields = false;

  readonly store = inject(OperationsWorkspaceStateService);
  readonly draft = this.store.draft;

  readonly overrideOptions = OVERRIDE_REASON_OPTIONS;

  sanitizeInteger(value: unknown): string {
    return String(value ?? '').replace(/[^\d]/g, '');
  }

  normalizeText(value: unknown): string {
    return String(value ?? '');
  }
}
