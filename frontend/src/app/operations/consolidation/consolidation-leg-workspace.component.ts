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
import { formatConsolidationLegStatus } from '../models/operations-status.util';
import {
  ConsolidationLeg,
  ConsolidationLegReceivePayload,
  ConsolidationWaybillResponse,
} from '../models/operations.model';
import {
  getOperationsConsolidationLegTone,
  mapOperationsToneToChipTone,
} from '../operations-display.util';
import { OperationsService } from '../services/operations.service';
import { OperationsWorkspaceStateService } from '../services/operations-workspace-state.service';
import {
  OpsTransportFormComponent,
  OpsTransportFormValue,
} from '../shared/ops-transport-form.component';
import { OpsStatusChipComponent } from '../shared/ops-status-chip.component';

@Component({
  selector: 'app-consolidation-leg-workspace',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatButtonModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    DmisEmptyStateComponent,
    DmisSkeletonLoaderComponent,
    OpsTransportFormComponent,
    OpsStatusChipComponent,
  ],
  providers: [OperationsWorkspaceStateService],
  template: `
    <div class="ops-shell">
      <header class="ops-hero">
        <div class="ops-hero__lead">
          <button
            mat-icon-button
            aria-label="Back to consolidation"
            (click)="goBack()">
            <mat-icon>arrow_back</mat-icon>
          </button>
          <div>
            <span class="ops-hero__eyebrow">Operations / Consolidation Leg</span>
            <h1 class="ops-hero__title">
              @if (leg(); as current) {
                Leg #{{ current.leg_sequence }}
              } @else {
                Loading…
              }
            </h1>
            @if (leg(); as current) {
              <div class="ops-hero__meta">
                <app-ops-status-chip
                  [label]="legStatusLabel()"
                  [tone]="legStatusTone()" />
                <span>Source wh: {{ current.source_warehouse_id }}</span>
                <span>Staging wh: {{ current.staging_warehouse_id }}</span>
              </div>
            }
          </div>
        </div>
      </header>

      @if (state.legsLoading()) {
        <dmis-skeleton-loader variant="table-row" />
      } @else if (state.legsError()) {
        <dmis-empty-state
          icon="error_outline"
          title="Could not load leg"
          [message]="state.legsError() || ''"
          actionLabel="Retry"
          actionIcon="refresh"
          (action)="reload()" />
      } @else if (!leg()) {
        <dmis-empty-state
          icon="help_outline"
          title="Leg not found"
          message="This consolidation leg could not be located for the current package."
          actionLabel="Back to consolidation"
          actionIcon="arrow_back"
          (action)="goBack()" />
      } @else {
        @switch (leg()?.status_code) {
          @case ('PLANNED') {
            <section class="ops-card" aria-label="Dispatch leg">
              <header class="ops-card__header">
                <h3 class="ops-card__title">Record dispatch</h3>
                <p class="ops-card__copy">
                  Provide the driver and transport details before the leg leaves the source warehouse.
                </p>
              </header>
              <app-ops-transport-form
                submitLabel="Dispatch leg"
                [submitting]="dispatching()"
                (submitted)="onDispatch($event)"
                (cancelled)="goBack()" />
            </section>
          }
          @case ('IN_TRANSIT') {
            <section class="ops-card" aria-label="Dispatch summary">
              <header class="ops-card__header">
                <h3 class="ops-card__title">Dispatched to staging</h3>
                <p class="ops-card__copy">
                  This leg is in transit. Confirm receipt once it arrives at the staging warehouse.
                </p>
              </header>
              <dl class="ops-summary-grid">
                <div>
                  <dt>Driver</dt>
                  <dd>{{ leg()?.driver_name || '—' }}</dd>
                </div>
                <div>
                  <dt>Vehicle</dt>
                  <dd>{{ leg()?.vehicle_registration || leg()?.vehicle_id || '—' }}</dd>
                </div>
                <div>
                  <dt>Transport mode</dt>
                  <dd>{{ leg()?.transport_mode || '—' }}</dd>
                </div>
                <div>
                  <dt>Dispatched at</dt>
                  <dd>{{ leg()?.dispatched_at || '—' }}</dd>
                </div>
                <div>
                  <dt>Expected arrival</dt>
                  <dd>{{ leg()?.estimated_arrival_dtime || leg()?.expected_arrival_at || '—' }}</dd>
                </div>
              </dl>
            </section>

            <section class="ops-card" aria-label="Confirm receipt">
              <header class="ops-card__header">
                <h3 class="ops-card__title">Confirm arrival at staging</h3>
                <p class="ops-card__copy">
                  Capture who received the leg and any notes about the condition on arrival.
                </p>
              </header>
              <form
                [formGroup]="receiptForm"
                (ngSubmit)="onReceive()"
                class="ops-receipt-form"
                aria-label="Receipt details">
                <mat-form-field appearance="outline" subscriptSizing="dynamic">
                  <mat-label>Received by (optional)</mat-label>
                  <input
                    matInput
                    formControlName="received_by_name"
                    maxlength="120"
                    placeholder="Name of the receiving staff" />
                  @if (receiptForm.controls['received_by_name'].hasError('maxlength')) {
                    <mat-error>Max 120 characters.</mat-error>
                  }
                </mat-form-field>
                <mat-form-field appearance="outline" subscriptSizing="dynamic">
                  <mat-label>Receipt notes (optional)</mat-label>
                  <textarea
                    matInput
                    formControlName="receipt_notes"
                    rows="3"
                    maxlength="500"
                    placeholder="Condition, damage, discrepancies…"></textarea>
                  @if (receiptForm.controls['receipt_notes'].hasError('maxlength')) {
                    <mat-error>Max 500 characters.</mat-error>
                  }
                </mat-form-field>
                <div class="ops-receipt-form__actions">
                  <button
                    type="button"
                    matButton
                    (click)="goBack()"
                    [disabled]="receiving()">
                    Cancel
                  </button>
                  <button
                    type="submit"
                    mat-flat-button
                    color="primary"
                    [disabled]="receiving() || receiptForm.invalid">
                    <mat-icon aria-hidden="true">inventory_2</mat-icon>
                    Confirm receipt
                  </button>
                </div>
              </form>
            </section>
          }
          @case ('RECEIVED_AT_STAGING') {
            <section class="ops-card" aria-label="Received at staging">
              <header class="ops-card__header">
                <h3 class="ops-card__title">Received at staging</h3>
                <p class="ops-card__copy">
                  This leg has been fully received at the staging hub.
                </p>
              </header>
              <dl class="ops-summary-grid">
                <div>
                  <dt>Received at</dt>
                  <dd>{{ leg()?.received_at || '—' }}</dd>
                </div>
                <div>
                  <dt>Waybill no</dt>
                  <dd>{{ leg()?.waybill_no || 'Not generated' }}</dd>
                </div>
                <div>
                  <dt>Driver</dt>
                  <dd>{{ leg()?.driver_name || '—' }}</dd>
                </div>
                <div>
                  <dt>Vehicle</dt>
                  <dd>{{ leg()?.vehicle_registration || leg()?.vehicle_id || '—' }}</dd>
                </div>
              </dl>
              <div class="ops-card__actions">
                <button
                  type="button"
                  matButton="outlined"
                  (click)="onDownloadWaybill()"
                  [disabled]="waybillLoading()">
                  <mat-icon aria-hidden="true">download</mat-icon>
                  Download waybill
                </button>
              </div>
              @if (waybillError(); as errorMessage) {
                <p class="ops-card__error" role="alert">{{ errorMessage }}</p>
              }
            </section>
          }
          @case ('CANCELLED') {
            <dmis-empty-state
              icon="cancel"
              title="Leg cancelled"
              message="This leg was cancelled and cannot be dispatched or received."
              actionLabel="Back to consolidation"
              actionIcon="arrow_back"
              (action)="goBack()" />
          }
          @default {
            <dmis-empty-state
              icon="help_outline"
              title="Unknown leg status"
              [message]="'Status ' + (leg()?.status_code || 'unknown') + ' is not supported.'" />
          }
        }
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
      margin: 4px 0 6px;
      font-size: clamp(1.6rem, 2.5vw, 2.2rem);
      font-weight: 800;
      letter-spacing: -0.04em;
      color: var(--ops-ink, #37352F);
    }

    .ops-hero__meta {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
      font-size: 0.85rem;
      color: var(--ops-ink-muted, #787774);
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

    .ops-card__actions {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      justify-content: flex-end;
    }

    .ops-card__error {
      margin: 0;
      font-size: 0.85rem;
      color: var(--color-danger, #c0392b);
    }

    .ops-summary-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 14px 24px;
      margin: 0;
    }

    .ops-summary-grid div {
      display: flex;
      flex-direction: column;
      gap: 2px;
    }

    .ops-summary-grid dt {
      font-size: 0.72rem;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--ops-ink-muted, #787774);
    }

    .ops-summary-grid dd {
      margin: 0;
      font-size: 0.95rem;
      color: var(--ops-ink, #37352F);
    }

    .ops-receipt-form {
      display: flex;
      flex-direction: column;
      gap: 12px;
    }

    .ops-receipt-form__actions {
      display: flex;
      gap: 10px;
      justify-content: flex-end;
      padding-top: 6px;
      border-top: 1px solid var(--ops-outline, rgba(55, 53, 47, 0.08));
    }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ConsolidationLegWorkspaceComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly fb = inject(FormBuilder);
  private readonly operationsService = inject(OperationsService);
  private readonly notifications = inject(DmisNotificationService);
  readonly state = inject(OperationsWorkspaceStateService);

  private reliefpkgId = 0;
  private readonly legId = signal<number | null>(null);

  readonly dispatching = signal(false);
  readonly receiving = signal(false);
  readonly waybillLoading = signal(false);
  readonly waybillError = signal<string | null>(null);

  readonly leg = computed<ConsolidationLeg | null>(() => {
    const legId = this.legId();
    if (!legId) {
      return null;
    }
    const legs = this.state.consolidationLegs();
    return legs.find((entry) => entry.leg_id === legId) ?? null;
  });

  readonly legStatusLabel = computed(() =>
    formatConsolidationLegStatus(this.leg()?.status_code),
  );

  readonly legStatusTone = computed(() =>
    mapOperationsToneToChipTone(getOperationsConsolidationLegTone(this.leg()?.status_code)),
  );

  readonly receiptForm: FormGroup = this.fb.nonNullable.group({
    received_by_name: ['', [Validators.maxLength(120)]],
    receipt_notes: ['', [Validators.maxLength(500)]],
  });

  ngOnInit(): void {
    const pkgRaw = this.route.snapshot.paramMap.get('reliefpkgId');
    const legRaw = this.route.snapshot.paramMap.get('legId');
    this.reliefpkgId = Number(pkgRaw);
    const legId = Number(legRaw);
    this.legId.set(legId > 0 ? legId : null);
    if (this.reliefpkgId > 0) {
      this.state.loadConsolidationLegs(this.reliefpkgId);
    }
  }

  reload(): void {
    if (this.reliefpkgId > 0) {
      this.state.loadConsolidationLegs(this.reliefpkgId);
    }
  }

  goBack(): void {
    if (this.reliefpkgId > 0) {
      this.router.navigate(['/operations/consolidation', this.reliefpkgId]);
      return;
    }
    this.router.navigate(['/operations/package-fulfillment']);
  }

  onDispatch(value: OpsTransportFormValue): void {
    const legId = this.legId();
    if (!legId) {
      return;
    }
    this.dispatching.set(true);
    this.state.dispatchLeg(legId, value).subscribe({
      next: () => {
        this.dispatching.set(false);
        this.notifications.showSuccess('Leg dispatched to staging.');
      },
      error: () => {
        this.dispatching.set(false);
        this.notifications.showError('Failed to dispatch leg.');
      },
    });
  }

  onReceive(): void {
    const legId = this.legId();
    if (!legId || this.receiptForm.invalid) {
      this.receiptForm.markAllAsTouched();
      return;
    }
    const raw = this.receiptForm.getRawValue() as {
      received_by_name: string;
      receipt_notes: string;
    };
    const payload: ConsolidationLegReceivePayload = {
      received_by_name: raw.received_by_name.trim() || undefined,
      receipt_notes: raw.receipt_notes.trim() || undefined,
    };
    this.receiving.set(true);
    this.state.receiveLeg(legId, payload).subscribe({
      next: () => {
        this.receiving.set(false);
        this.notifications.showSuccess('Leg received at staging.');
      },
      error: () => {
        this.receiving.set(false);
        this.notifications.showError('Failed to confirm receipt.');
      },
    });
  }

  onDownloadWaybill(): void {
    const legId = this.legId();
    if (!this.reliefpkgId || !legId) {
      return;
    }
    this.waybillLoading.set(true);
    this.waybillError.set(null);
    this.operationsService.getConsolidationLegWaybill(this.reliefpkgId, legId).subscribe({
      next: (response) => {
        const artifact = buildWaybillDownloadArtifact(response);
        this.waybillLoading.set(false);
        if (!artifact) {
          this.waybillError.set('Waybill content is missing.');
          return;
        }
        const url = URL.createObjectURL(artifact.blob);
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = artifact.filename;
        anchor.style.display = 'none';
        document.body.appendChild(anchor);
        anchor.click();
        document.body.removeChild(anchor);
        URL.revokeObjectURL(url);
        this.notifications.showSuccess(`Waybill ${response.waybill_no} downloaded.`);
      },
      error: () => {
        this.waybillLoading.set(false);
        this.waybillError.set('Could not generate waybill.');
      },
    });
  }
}

function buildWaybillDownloadArtifact(
  response: ConsolidationWaybillResponse,
): { blob: Blob; filename: string } | null {
  const payload = response.waybill_payload as unknown;
  if (payload == null) {
    return null;
  }
  const safeWaybillNo = (response.waybill_no || 'consolidation-waybill').replace(/[^\w.-]+/g, '_');
  if (typeof payload === 'string') {
    const trimmed = payload.trim();
    if (!trimmed) {
      return null;
    }
    if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
      return {
        blob: new Blob([trimmed], { type: 'application/json' }),
        filename: `${safeWaybillNo}.json`,
      };
    }
    if (trimmed.startsWith('data:')) {
      const match = trimmed.match(/^data:([^;]+);base64,(.+)$/);
      if (!match) {
        return null;
      }
      try {
        return {
          blob: new Blob([decodeBase64(match[2])], { type: match[1] || 'application/pdf' }),
          filename: `${safeWaybillNo}.${extensionForMimeType(match[1])}`,
        };
      } catch {
        return null;
      }
    }
    try {
      return {
        blob: new Blob([decodeBase64(trimmed)], { type: 'application/pdf' }),
        filename: `${safeWaybillNo}.pdf`,
      };
    } catch {
      return null;
    }
  }
  if (payload instanceof ArrayBuffer) {
    return {
      blob: new Blob([payload], { type: 'application/pdf' }),
      filename: `${safeWaybillNo}.pdf`,
    };
  }
  if (ArrayBuffer.isView(payload)) {
    return {
      blob: new Blob([arrayBufferFromView(payload)], { type: 'application/pdf' }),
      filename: `${safeWaybillNo}.pdf`,
    };
  }
  return {
    blob: new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' }),
    filename: `${safeWaybillNo}.json`,
  };
}

function decodeBase64(encoded: string): ArrayBuffer {
  const binary = window.atob(encoded);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes.buffer;
}

function arrayBufferFromView(view: ArrayBufferView): ArrayBuffer {
  const bytes = new Uint8Array(view.byteLength);
  bytes.set(new Uint8Array(view.buffer, view.byteOffset, view.byteLength));
  return bytes.buffer;
}

function extensionForMimeType(mimeType: string | null | undefined): string {
  switch ((mimeType ?? '').toLowerCase()) {
    case 'application/pdf':
      return 'pdf';
    case 'application/json':
      return 'json';
    default:
      return 'bin';
  }
}
