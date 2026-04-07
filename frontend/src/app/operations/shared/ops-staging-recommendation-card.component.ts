import { ChangeDetectionStrategy, Component, computed, inject, input, output, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';

import { MasterDataService } from '../../master-data/services/master-data.service';
import { formatStagingSelectionBasis } from '../models/operations-status.util';
import { StagingRecommendationResponse, StagingSelectionBasis } from '../models/operations.model';
import { OpsStatusChipComponent } from './ops-status-chip.component';

export interface OpsStagingCardApplyEvent {
  staging_warehouse_id: number;
  staging_override_reason: string | null;
}

@Component({
  selector: 'app-ops-staging-recommendation-card',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatButtonModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatSelectModule,
    OpsStatusChipComponent,
  ],
  template: `
    <section class="ops-staging-card" aria-label="Staging hub recommendation">
      <header class="ops-staging-card__header">
        <div>
          <span class="ops-staging-card__eyebrow">Staging hub</span>
          <h3 class="ops-staging-card__title">
            @if (recommendationLoading()) {
              Loading recommendation…
            } @else if (recommendedName()) {
              {{ recommendedName() }}
            } @else {
              No recommendation available
            }
          </h3>
          @if (recommendedParish(); as parish) {
            <p class="ops-staging-card__sub">Parish: {{ parish }}</p>
          }
        </div>
        @if (basisLabel()) {
          <app-ops-status-chip [label]="basisLabel()" tone="info" [showDot]="false" />
        }
      </header>

      @if (recommendationError()) {
        <p class="ops-staging-card__error" role="alert">
          <mat-icon aria-hidden="true">error_outline</mat-icon>
          {{ recommendationError() }}
        </p>
      }

      @if (disabled()) {
        <p class="ops-staging-card__locked" role="status">
          <mat-icon aria-hidden="true">lock</mat-icon>
          You don't have permission to change the staging hub.
        </p>
      } @else {
        <div class="ops-staging-card__actions">
          @if (!overrideActive()) {
            <button
              type="button"
              matButton="outlined"
              (click)="useRecommendation()"
              [disabled]="!recommendedWarehouseId() || saving()">
              <mat-icon aria-hidden="true">check_circle_outline</mat-icon>
              Use recommendation
            </button>
            <button
              type="button"
              matButton="outlined"
              (click)="beginOverride()"
              [disabled]="saving()">
              <mat-icon aria-hidden="true">swap_horiz</mat-icon>
              Override hub
            </button>
          }
        </div>

        @if (overrideActive()) {
          <form [formGroup]="form" (ngSubmit)="applyOverride()" class="ops-staging-card__form">
            <mat-form-field appearance="outline" subscriptSizing="dynamic">
              <mat-label>Staging warehouse</mat-label>
              <mat-select formControlName="warehouse_id" aria-label="Select staging warehouse">
                @for (wh of warehouseOptions(); track wh.value) {
                  <mat-option [value]="wh.value">{{ wh.label }}</mat-option>
                }
              </mat-select>
              @if (form.controls.warehouse_id.invalid && form.controls.warehouse_id.touched) {
                <mat-error>Select a staging warehouse.</mat-error>
              }
            </mat-form-field>

            <mat-form-field appearance="outline" subscriptSizing="dynamic">
              <mat-label>Reason for override</mat-label>
              <textarea
                matInput
                rows="2"
                maxlength="500"
                formControlName="reason"
                placeholder="Explain why the recommended hub isn't suitable"></textarea>
              @if (form.controls.reason.invalid && form.controls.reason.touched) {
                <mat-error>A reason is required (max 500 characters).</mat-error>
              }
            </mat-form-field>

            <div class="ops-staging-card__form-actions">
              <button type="button" matButton (click)="cancelOverride()" [disabled]="saving()">
                Cancel
              </button>
              <button type="submit" mat-flat-button color="primary" [disabled]="saving() || form.invalid">
                Apply override
              </button>
            </div>
          </form>
        }
      }
    </section>
  `,
  styles: [`
    :host { display: block; }

    .ops-staging-card {
      border: 1px solid var(--ops-outline, rgba(55, 53, 47, 0.08));
      border-radius: var(--ops-radius-md, 10px);
      background: var(--ops-card, #fbfaf7);
      padding: 18px 20px;
      display: flex;
      flex-direction: column;
      gap: 14px;
    }

    .ops-staging-card__header {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
    }

    .ops-staging-card__eyebrow {
      font-size: 0.7rem;
      font-weight: 700;
      letter-spacing: 0.18em;
      text-transform: uppercase;
      color: var(--ops-ink-muted, #787774);
    }

    .ops-staging-card__title {
      margin: 4px 0 0;
      font-size: 1.1rem;
      font-weight: 700;
      letter-spacing: -0.02em;
      color: var(--ops-ink, #37352F);
    }

    .ops-staging-card__sub {
      margin: 2px 0 0;
      font-size: 0.85rem;
      color: var(--ops-ink-muted, #787774);
    }

    .ops-staging-card__error {
      display: flex;
      align-items: center;
      gap: 8px;
      color: var(--color-critical, #8c1d13);
      margin: 0;
      font-size: 0.85rem;
    }

    .ops-staging-card__locked {
      display: flex;
      align-items: center;
      gap: 8px;
      margin: 0;
      font-size: 0.85rem;
      color: var(--ops-ink-muted, #787774);
    }

    .ops-staging-card__actions {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
    }

    .ops-staging-card__form {
      display: grid;
      gap: 12px;
    }

    .ops-staging-card__form-actions {
      display: flex;
      gap: 8px;
      justify-content: flex-end;
    }

    mat-icon {
      width: 18px;
      height: 18px;
      font-size: 18px;
    }

    @media (prefers-reduced-motion: reduce) {
      .ops-staging-card { transition: none; }
    }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class OpsStagingRecommendationCardComponent {
  readonly recommendation = input<StagingRecommendationResponse | null>(null);
  readonly currentStagingWarehouseId = input<number | null>(null);
  readonly basis = input<StagingSelectionBasis | null>(null);
  readonly recommendationLoading = input(false);
  readonly recommendationError = input<string | null>(null);
  readonly saving = input(false);
  readonly disabled = input(false);

  readonly applied = output<OpsStagingCardApplyEvent>();

  private readonly masterData = inject(MasterDataService);
  private readonly fb = inject(FormBuilder);

  readonly warehouseOptions = toSignal(this.masterData.lookup('warehouses'), { initialValue: [] });

  readonly form = this.fb.nonNullable.group({
    warehouse_id: [0, [Validators.required, Validators.min(1)]],
    reason: ['', [Validators.required, Validators.maxLength(500)]],
  });

  readonly overrideActive = signal(false);

  readonly recommendedWarehouseId = computed(
    () => this.recommendation()?.recommended_staging_warehouse_id ?? null,
  );
  readonly recommendedName = computed(
    () => this.recommendation()?.recommended_staging_warehouse_name ?? null,
  );
  readonly recommendedParish = computed(
    () => this.recommendation()?.recommended_staging_parish_code ?? null,
  );
  readonly basisLabel = computed(() => {
    const basisValue = this.recommendation()?.staging_selection_basis ?? this.basis();
    return basisValue ? formatStagingSelectionBasis(basisValue) : '';
  });

  useRecommendation(): void {
    const warehouseId = this.recommendedWarehouseId();
    if (!warehouseId) {
      return;
    }
    this.applied.emit({
      staging_warehouse_id: warehouseId,
      staging_override_reason: null,
    });
  }

  beginOverride(): void {
    this.overrideActive.set(true);
    this.form.reset({
      warehouse_id: this.currentStagingWarehouseId() ?? 0,
      reason: '',
    });
  }

  cancelOverride(): void {
    this.overrideActive.set(false);
    this.form.reset({ warehouse_id: 0, reason: '' });
  }

  applyOverride(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    const warehouseId = Number(this.form.controls.warehouse_id.value);
    const reason = this.form.controls.reason.value.trim();
    this.applied.emit({
      staging_warehouse_id: warehouseId,
      staging_override_reason: reason,
    });
    this.overrideActive.set(false);
  }
}
