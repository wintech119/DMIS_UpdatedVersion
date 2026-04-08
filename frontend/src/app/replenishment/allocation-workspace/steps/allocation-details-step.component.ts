import { ChangeDetectionStrategy, Component, Input, computed, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';

import {
  EXECUTION_OVERRIDE_REASON_OPTIONS,
  EXECUTION_URGENCY_OPTIONS,
} from '../../models/allocation-dispatch.model';
import { ExecutionWorkspaceStateService } from '../../execution/services/execution-workspace-state.service';

@Component({
  selector: 'app-allocation-details-step',
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
          Capture the request context that becomes part of the formal reservation record. Stock is reserved only after
          the allocation is committed. Physical deduction happens later on dispatch.
        </p>
      </div>

      @if (store.requiresFirstCommitDetails()) {
        <div class="details-alert" role="status">
          <mat-icon aria-hidden="true">info</mat-icon>
          <span>
            This is the first formal allocation for this needs list. Receiving agency ID and urgency are required before
            stock can be reserved.
          </span>
        </div>
      } @else {
        <div class="details-alert details-alert--soft" role="status">
          <mat-icon aria-hidden="true">sync</mat-icon>
          <span>
            Request and package tracking already exist. Update transport mode or notes only if operations changed.
          </span>
        </div>
      }

      @if (lockOperationalFields) {
        <div class="details-alert details-alert--soft" role="status">
          <mat-icon aria-hidden="true">lock</mat-icon>
          <span>
            This routed reservation is read-only during override approval review so the submitted plan stays intact for
            approvers.
          </span>
        </div>
      }

      <div class="details-grid">
        <mat-form-field appearance="outline" class="details-field">
          <mat-label>Receiving Agency ID</mat-label>
          <input
            matInput
            type="number"
            min="1"
            [ngModel]="draft().agency_id"
            (ngModelChange)="store.patchDraft({ agency_id: sanitizeInteger($event) })"
            [disabled]="lockOperationalFields || !store.requiresFirstCommitDetails()"
          />
          <mat-hint>Use the numeric agency identifier required by the formal request record.</mat-hint>
        </mat-form-field>

        <mat-form-field appearance="outline" class="details-field">
          <mat-label>Urgency</mat-label>
          <mat-select
            [ngModel]="draft().urgency_ind"
            (ngModelChange)="store.patchDraft({ urgency_ind: $event })"
            [disabled]="lockOperationalFields || !store.requiresFirstCommitDetails()"
          >
            @for (option of urgencyOptions; track option.value) {
              <mat-option [value]="option.value">{{ option.label }}</mat-option>
            }
          </mat-select>
          <mat-hint>{{ selectedUrgencyHint() }}</mat-hint>
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
          <mat-label>Request Notes</mat-label>
          <textarea
            matInput
            rows="4"
            [ngModel]="draft().request_notes"
            (ngModelChange)="store.patchDraft({ request_notes: normalizeText($event) })"
            placeholder="Operational notes for the request tracking record"
            [disabled]="lockOperationalFields"
          ></textarea>
        </mat-form-field>

        <mat-form-field appearance="outline" class="details-field">
          <mat-label>Package Comments</mat-label>
          <textarea
            matInput
            rows="4"
            [ngModel]="draft().package_comments"
            (ngModelChange)="store.patchDraft({ package_comments: normalizeText($event) })"
            placeholder="Notes for packaging, loading, or handoff preparation"
            [disabled]="lockOperationalFields"
          ></textarea>
        </mat-form-field>
      </div>

      @if (store.planRequiresOverride() || store.hasPendingOverride()) {
        <div class="details-override">
          <div class="details-override__header">
            <h3>{{ store.hasPendingOverride() ? 'Override Approval' : 'Order Override' }}</h3>
            <p>
              {{
                store.hasPendingOverride()
                  ? 'This reservation is awaiting approval because a blocking allocation rule was bypassed.'
                  : 'The current plan bypasses the recommended stock order. Record the reason before committing.'
              }}
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
              <mat-hint>Recorded with the saved allocation when the recommended stock order is bypassed.</mat-hint>
            </mat-form-field>

            @if (store.hasPendingOverride()) {
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
            }
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
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 16px;
    }

    .details-grid--notes {
      grid-template-columns: repeat(2, minmax(0, 1fr));
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
      .details-grid,
      .details-grid--notes {
        grid-template-columns: 1fr;
      }
    }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AllocationDetailsStepComponent {
  @Input() lockOperationalFields = false;

  readonly store = inject(ExecutionWorkspaceStateService);
  readonly draft = this.store.draft;

  readonly urgencyOptions = EXECUTION_URGENCY_OPTIONS;
  readonly overrideOptions = EXECUTION_OVERRIDE_REASON_OPTIONS;

  readonly selectedUrgencyHint = computed(() => {
    const selected = this.urgencyOptions.find((option) => option.value === this.draft().urgency_ind);
    return selected?.hint ?? 'Choose the urgency that should carry into the formal request header.';
  });

  sanitizeInteger(value: unknown): string {
    return String(value ?? '').replace(/[^\d]/g, '');
  }

  normalizeText(value: unknown): string {
    return String(value ?? '');
  }
}
