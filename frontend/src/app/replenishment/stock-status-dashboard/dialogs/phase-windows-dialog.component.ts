// `manageable_by_active_tenant` is a UX hint only — the backend is the
// enforcement layer. A 403 on PUT must surface to the user via toast and
// close the dialog.
import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatDialogModule, MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { forkJoin, of, catchError, map } from 'rxjs';
import { HttpErrorResponse } from '@angular/common/http';
import { ReplenishmentService } from '../../services/replenishment.service';
import { DmisNotificationService } from '../../services/notification.service';
import {
  EventPhase,
  PhaseWindows
} from '../../models/stock-status.model';

export interface PhaseWindowsDialogData {
  eventId: number;
  windows: Record<EventPhase, PhaseWindows>;
}

const PHASES: EventPhase[] = ['SURGE', 'STABILIZED', 'BASELINE'];
const MIN_HOURS = 1;
const MAX_HOURS = 8760;
const JUSTIFICATION_MAX = 500;

@Component({
  selector: 'app-phase-windows-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ReactiveFormsModule,
    MatDialogModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    MatIconModule
  ],
  template: `
    <h2 mat-dialog-title>Edit phase windows</h2>
    <div mat-dialog-content>
      <p class="phase-windows-help">
        Configure demand and planning windows per phase. Values are in hours.
      </p>
      <form [formGroup]="form" class="phase-windows-form">
        @for (phase of phases; track phase) {
          <fieldset class="phase-fieldset" [formGroupName]="phase">
            <legend>{{ phase }}</legend>
            <div class="phase-row">
              <mat-form-field appearance="fill">
                <mat-label>Demand window (hrs)</mat-label>
                <input
                  matInput
                  type="number"
                  formControlName="demand_hours"
                  [min]="MIN"
                  [max]="MAX"
                  maxlength="6"
                  required>
                @if (form.get(phase + '.demand_hours')?.hasError('required')) {
                  <mat-error>Demand hours required.</mat-error>
                }
                @if (form.get(phase + '.demand_hours')?.hasError('min')) {
                  <mat-error>Minimum is {{ MIN }} hour.</mat-error>
                }
                @if (form.get(phase + '.demand_hours')?.hasError('max')) {
                  <mat-error>Maximum is {{ MAX }} hours.</mat-error>
                }
              </mat-form-field>
              <mat-form-field appearance="fill">
                <mat-label>Planning window (hrs)</mat-label>
                <input
                  matInput
                  type="number"
                  formControlName="planning_hours"
                  [min]="MIN"
                  [max]="MAX"
                  maxlength="6"
                  required>
                @if (form.get(phase + '.planning_hours')?.hasError('required')) {
                  <mat-error>Planning hours required.</mat-error>
                }
                @if (form.get(phase + '.planning_hours')?.hasError('min')) {
                  <mat-error>Minimum is {{ MIN }} hour.</mat-error>
                }
                @if (form.get(phase + '.planning_hours')?.hasError('max')) {
                  <mat-error>Maximum is {{ MAX }} hours.</mat-error>
                }
              </mat-form-field>
            </div>
          </fieldset>
        }
        <mat-form-field appearance="fill" class="justification-field">
          <mat-label>Justification</mat-label>
          <textarea
            matInput
            formControlName="justification"
            rows="3"
            required
            [maxlength]="JUSTIFICATION_MAX"
            aria-label="Justification for phase window change"
            placeholder="Explain why the global phase windows must change (shared across phases)."></textarea>
          <mat-hint align="end">
            {{ (form.get('justification')?.value ?? '').length }} / {{ JUSTIFICATION_MAX }}
          </mat-hint>
          @if (form.get('justification')?.hasError('required')) {
            <mat-error>Justification is required.</mat-error>
          }
          @if (form.get('justification')?.hasError('maxlength')) {
            <mat-error>Justification must be {{ JUSTIFICATION_MAX }} characters or fewer.</mat-error>
          }
        </mat-form-field>
      </form>
    </div>
    <div mat-dialog-actions align="end">
      <button mat-button type="button" (click)="cancel()" [disabled]="saving()">
        Cancel
      </button>
      <button
        matButton="filled"
        color="primary"
        type="button"
        (click)="save()"
        [disabled]="form.invalid || saving()">
        @if (saving()) {
          <mat-icon class="spin" aria-hidden="true">autorenew</mat-icon>
          Saving...
        } @else {
          Save
        }
      </button>
    </div>
  `,
  styles: [`
    .phase-windows-help {
      margin: 0 0 16px;
      color: var(--color-text-secondary, #555);
      font-size: var(--text-sm, 13px);
    }
    .phase-windows-form {
      display: flex;
      flex-direction: column;
      gap: 16px;
    }
    .phase-fieldset {
      border: 1px solid var(--color-border, #d6d3ce);
      border-radius: var(--radius-md, 8px);
      padding: 8px 16px 4px;
      margin: 0;
    }
    .phase-fieldset legend {
      padding: 0 6px;
      font-weight: var(--weight-semibold, 600);
      color: var(--color-text-primary, #37352f);
    }
    .phase-row {
      display: flex;
      gap: 16px;
      flex-wrap: wrap;
    }
    .phase-row mat-form-field {
      flex: 1 1 160px;
      min-width: 140px;
    }
    .justification-field {
      width: 100%;
    }
    .spin {
      animation: phasewin-spin 1s linear infinite;
      margin-right: 6px;
    }
    @keyframes phasewin-spin {
      from { transform: rotate(0deg); }
      to { transform: rotate(360deg); }
    }
  `]
})
export class PhaseWindowsDialogComponent {
  private readonly dialogRef = inject<MatDialogRef<PhaseWindowsDialogComponent, void>>(MatDialogRef);
  private readonly data = inject<PhaseWindowsDialogData>(MAT_DIALOG_DATA);
  private readonly fb = inject(FormBuilder);
  private readonly service = inject(ReplenishmentService);
  private readonly notifications = inject(DmisNotificationService);

  readonly phases = PHASES;
  readonly MIN = MIN_HOURS;
  readonly MAX = MAX_HOURS;
  readonly JUSTIFICATION_MAX = JUSTIFICATION_MAX;

  readonly saving = signal(false);

  readonly form: FormGroup = this.buildForm();

  private buildForm(): FormGroup {
    const group: Record<string, FormGroup | unknown> = {};
    for (const phase of PHASES) {
      const win = this.data.windows?.[phase] ?? { demand_hours: 0, planning_hours: 0, safety_factor: 1 };
      group[phase] = this.fb.group({
        demand_hours: [
          win.demand_hours ?? 0,
          [Validators.required, Validators.min(MIN_HOURS), Validators.max(MAX_HOURS)]
        ],
        planning_hours: [
          win.planning_hours ?? 0,
          [Validators.required, Validators.min(MIN_HOURS), Validators.max(MAX_HOURS)]
        ]
      });
    }
    group['justification'] = [
      '',
      [Validators.required, Validators.maxLength(JUSTIFICATION_MAX)]
    ];
    return this.fb.group(group);
  }

  save(): void {
    if (this.form.invalid || this.saving()) {
      this.form.markAllAsTouched();
      return;
    }

    const rawJustification = String(this.form.get('justification')?.value ?? '');
    const justification = rawJustification.trim();
    // Defensive guard: Validators.required allows whitespace-only strings through
    // on some browsers; re-check the trimmed value before sending.
    if (!justification) {
      this.form.get('justification')?.setErrors({ required: true });
      this.form.markAllAsTouched();
      return;
    }

    const changed: { phase: EventPhase; demand: number; planning: number }[] = [];
    for (const phase of PHASES) {
      const original = this.data.windows?.[phase];
      const current = this.form.get(phase)!.value as { demand_hours: number; planning_hours: number };
      const demand = Number(current.demand_hours);
      const planning = Number(current.planning_hours);
      if (
        !original ||
        original.demand_hours !== demand ||
        original.planning_hours !== planning
      ) {
        changed.push({ phase, demand, planning });
      }
    }

    if (changed.length === 0) {
      this.dialogRef.close();
      return;
    }

    this.saving.set(true);

    const updates = changed.map(({ phase, demand, planning }) =>
      this.service
        .updatePhaseWindow(this.data.eventId, phase, demand, planning, justification)
        .pipe(
          map((res) => ({ ok: true as const, res })),
          catchError((err: HttpErrorResponse) => of({ ok: false as const, err }))
        )
    );

    forkJoin(updates).subscribe({
      next: (results) => {
        this.saving.set(false);

        const forbidden = results.find((r) => !r.ok && r.err.status === 403);
        if (forbidden) {
          this.notifications.showWarning('You do not have permission to update phase windows.');
          this.dialogRef.close();
          return;
        }

        const failure = results.find((r) => !r.ok);
        if (failure && !failure.ok) {
          const msg = failure.err.error?.error || failure.err.message || 'Failed to update phase windows.';
          this.notifications.showError(msg);
          return;
        }

        this.notifications.showSuccess('Phase windows updated.');
        // Close without a payload; caller refetches from the service to pick
        // up the projected `windows` record with any partial saves applied.
        this.dialogRef.close();
      }
    });
  }

  cancel(): void {
    if (this.saving()) {
      return;
    }
    this.dialogRef.close();
  }
}
