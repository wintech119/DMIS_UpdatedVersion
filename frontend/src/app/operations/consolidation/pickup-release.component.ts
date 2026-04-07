import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import {
  FormBuilder,
  FormGroup,
  ReactiveFormsModule,
  Validators,
} from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';

import { DmisEmptyStateComponent } from '../../replenishment/shared/dmis-empty-state/dmis-empty-state.component';
import { DmisSkeletonLoaderComponent } from '../../replenishment/shared/dmis-skeleton-loader/dmis-skeleton-loader.component';
import { DmisNotificationService } from '../../replenishment/services/notification.service';
import {
  formatFulfillmentMode,
  formatPackageStatus,
} from '../models/operations-status.util';
import { PickupReleasePayload } from '../models/operations.model';
import { OperationsWorkspaceStateService } from '../services/operations-workspace-state.service';
import { OpsStatusChipComponent } from '../shared/ops-status-chip.component';

@Component({
  selector: 'app-pickup-release',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatButtonModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    DmisEmptyStateComponent,
    DmisSkeletonLoaderComponent,
    OpsStatusChipComponent,
  ],
  providers: [OperationsWorkspaceStateService],
  template: `
    <div class="ops-shell">
      <header class="ops-hero">
        <div class="ops-hero__lead">
          <button
            mat-icon-button
            aria-label="Back to package"
            (click)="goBack()">
            <mat-icon>arrow_back</mat-icon>
          </button>
          <div>
            <span class="ops-hero__eyebrow">Operations / Pickup Release</span>
            <h1 class="ops-hero__title">
              {{ trackingNumber() || 'Staging pickup' }}
            </h1>
            <p class="ops-hero__copy">
              {{ fulfillmentModeLabel() }}
            </p>
          </div>
        </div>
      </header>

      @if (state.loading()) {
        <dmis-skeleton-loader variant="table-row" />
      } @else if (!packageLoaded()) {
        <dmis-empty-state
          icon="help_outline"
          title="Package not found"
          message="Unable to locate the staged package for pickup."
          actionLabel="Back to queue"
          actionIcon="arrow_back"
          (action)="goBack()" />
      } @else if (!state.canReleaseForPickup()) {
        <section class="ops-card" aria-label="Pickup not available">
          <div class="ops-card__header">
            <h3 class="ops-card__title">Pickup release not available</h3>
            <p class="ops-card__copy">
              This package is not currently ready for beneficiary collection.
            </p>
          </div>
          <div class="ops-card__status">
            <app-ops-status-chip
              [label]="packageStatusLabel()"
              tone="neutral" />
          </div>
          <div class="ops-card__actions">
            <button type="button" matButton="outlined" (click)="goBack()">
              <mat-icon aria-hidden="true">arrow_back</mat-icon>
              Back to package
            </button>
          </div>
        </section>
      } @else {
        <section class="ops-card" aria-label="Beneficiary pickup release">
          <header class="ops-card__header">
            <h3 class="ops-card__title">Record pickup release</h3>
            <p class="ops-card__copy">
              Capture the beneficiary who collected the package at the staging hub.
            </p>
          </header>
          <form
            [formGroup]="form"
            (ngSubmit)="onSubmit()"
            class="ops-pickup-form"
            aria-label="Pickup release details">
            <div class="ops-pickup-form__row ops-pickup-form__row--2col">
              <mat-form-field appearance="outline" subscriptSizing="dynamic">
                <mat-label>Collected by (name)</mat-label>
                <input
                  matInput
                  formControlName="collected_by_name"
                  maxlength="120"
                  placeholder="Full name of the collector"
                  required />
                @if (form.controls['collected_by_name'].hasError('required') && form.controls['collected_by_name'].touched) {
                  <mat-error>Collector name is required.</mat-error>
                }
                @if (form.controls['collected_by_name'].hasError('maxlength')) {
                  <mat-error>Max 120 characters.</mat-error>
                }
              </mat-form-field>
              <mat-form-field appearance="outline" subscriptSizing="dynamic">
                <mat-label>Collector ID reference (optional)</mat-label>
                <input
                  matInput
                  formControlName="collected_by_id_ref"
                  maxlength="60"
                  placeholder="ID card, voucher no., etc." />
                @if (form.controls['collected_by_id_ref'].hasError('maxlength')) {
                  <mat-error>Max 60 characters.</mat-error>
                }
              </mat-form-field>
            </div>

            <mat-form-field appearance="outline" subscriptSizing="dynamic">
              <mat-label>Released by (optional)</mat-label>
              <input
                matInput
                formControlName="released_by_name"
                maxlength="120"
                placeholder="Name of staff releasing the package" />
              @if (form.controls['released_by_name'].hasError('maxlength')) {
                <mat-error>Max 120 characters.</mat-error>
              }
            </mat-form-field>

            <mat-form-field appearance="outline" subscriptSizing="dynamic">
              <mat-label>Release notes (optional)</mat-label>
              <textarea
                matInput
                formControlName="release_notes"
                rows="3"
                maxlength="500"
                placeholder="Condition, identification checks, etc."></textarea>
              @if (form.controls['release_notes'].hasError('maxlength')) {
                <mat-error>Max 500 characters.</mat-error>
              }
            </mat-form-field>

            <div class="ops-pickup-form__actions">
              <button
                type="button"
                matButton
                (click)="goBack()"
                [disabled]="submitting()">
                Cancel
              </button>
              <button
                type="submit"
                mat-flat-button
                color="primary"
                [disabled]="submitting() || form.invalid">
                <mat-icon aria-hidden="true">check_circle</mat-icon>
                Release to beneficiary
              </button>
            </div>
          </form>
        </section>
      }
    </div>
  `,
  styles: [`
    :host { display: block; }

    .ops-shell {
      padding: 24px;
      max-width: 1100px;
      margin: 0 auto;
      display: flex;
      flex-direction: column;
      gap: 18px;
    }

    .ops-hero {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 16px;
      padding-bottom: 12px;
      border-bottom: 1px solid var(--ops-outline, rgba(55, 53, 47, 0.08));
    }

    .ops-hero__lead {
      display: flex;
      align-items: flex-start;
      gap: 8px;
    }

    .ops-hero__eyebrow {
      font-size: 0.68rem;
      font-weight: 700;
      letter-spacing: 0.2em;
      text-transform: uppercase;
      color: var(--ops-ink-muted, #787774);
    }

    .ops-hero__title {
      margin: 4px 0 2px;
      font-size: clamp(1.6rem, 2.5vw, 2.2rem);
      font-weight: 800;
      letter-spacing: -0.04em;
      color: var(--ops-ink, #37352F);
    }

    .ops-hero__copy {
      margin: 0;
      color: var(--ops-ink-muted, #787774);
      font-size: 0.92rem;
    }

    .ops-card {
      background: var(--ops-card, #fbfaf7);
      border: 1px solid var(--ops-outline, rgba(55, 53, 47, 0.08));
      border-radius: var(--ops-radius-md, 10px);
      padding: 22px 24px;
      display: flex;
      flex-direction: column;
      gap: 16px;
    }

    .ops-card__header {
      display: flex;
      flex-direction: column;
      gap: 4px;
    }

    .ops-card__title {
      margin: 0;
      font-size: 1.15rem;
      font-weight: 700;
      letter-spacing: -0.02em;
      color: var(--ops-ink, #37352F);
    }

    .ops-card__copy {
      margin: 0;
      font-size: 0.88rem;
      color: var(--ops-ink-muted, #787774);
    }

    .ops-card__status {
      display: flex;
      gap: 10px;
      align-items: center;
    }

    .ops-card__actions {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      justify-content: flex-end;
    }

    .ops-pickup-form {
      display: flex;
      flex-direction: column;
      gap: 12px;
    }

    .ops-pickup-form__row {
      display: grid;
      gap: 12px;
    }

    .ops-pickup-form__row--2col {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    .ops-pickup-form__actions {
      display: flex;
      gap: 10px;
      justify-content: flex-end;
      padding-top: 6px;
      border-top: 1px solid var(--ops-outline, rgba(55, 53, 47, 0.08));
    }

    @media (max-width: 760px) {
      .ops-pickup-form__row--2col {
        grid-template-columns: 1fr;
      }
    }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PickupReleaseComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly fb = inject(FormBuilder);
  private readonly notifications = inject(DmisNotificationService);
  readonly state = inject(OperationsWorkspaceStateService);

  private reliefpkgId = 0;

  readonly submitting = signal(false);

  readonly packageLoaded = computed(() => !!this.state.packageDetail()?.package);

  readonly trackingNumber = computed(
    () => this.state.packageDetail()?.package?.tracking_no ?? null,
  );

  readonly fulfillmentModeLabel = computed(() =>
    formatFulfillmentMode(this.state.fulfillmentMode()),
  );

  readonly packageStatusLabel = computed(() =>
    formatPackageStatus(this.state.packageDetail()?.package?.status_code ?? ''),
  );

  readonly form: FormGroup = this.fb.nonNullable.group({
    collected_by_name: ['', [Validators.required, Validators.maxLength(120)]],
    collected_by_id_ref: ['', [Validators.maxLength(60)]],
    released_by_name: ['', [Validators.maxLength(120)]],
    release_notes: ['', [Validators.maxLength(500)]],
  });

  ngOnInit(): void {
    const raw = this.route.snapshot.paramMap.get('reliefpkgId');
    this.reliefpkgId = Number(raw);
    if (this.reliefpkgId > 0) {
      this.state.loadConsolidationLegs(this.reliefpkgId);
    }
  }

  goBack(): void {
    const reliefrqstId = this.state.reliefrqstId();
    if (reliefrqstId) {
      this.router.navigate(['/operations/package-fulfillment', reliefrqstId]);
      return;
    }
    this.router.navigate(['/operations/package-fulfillment']);
  }

  onSubmit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    const raw = this.form.getRawValue() as {
      collected_by_name: string;
      collected_by_id_ref: string;
      released_by_name: string;
      release_notes: string;
    };
    const payload: PickupReleasePayload = {
      collected_by_name: raw.collected_by_name.trim(),
      collected_by_id_ref: raw.collected_by_id_ref.trim() || undefined,
      released_by_name: raw.released_by_name.trim() || undefined,
      release_notes: raw.release_notes.trim() || undefined,
    };
    this.submitting.set(true);
    this.state.releaseForPickup(payload).subscribe({
      next: () => {
        this.submitting.set(false);
        this.notifications.showSuccess('Package released to beneficiary.');
        this.goBack();
      },
      error: () => {
        this.submitting.set(false);
        this.notifications.showError('Failed to record pickup release.');
      },
    });
  }
}
