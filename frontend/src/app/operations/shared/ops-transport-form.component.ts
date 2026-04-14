import { ChangeDetectionStrategy, Component, inject, input, output } from '@angular/core';
import {
  AbstractControl,
  FormBuilder,
  FormGroup,
  ReactiveFormsModule,
  ValidationErrors,
  ValidatorFn,
  Validators,
} from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';

import { TRANSPORT_MODE_OPTIONS } from '../models/operations.model';

export interface OpsTransportFormValue {
  driver_name: string;
  driver_license_last4?: string;
  vehicle_id?: string;
  vehicle_registration?: string;
  vehicle_type?: string;
  transport_mode?: string;
  transport_notes?: string;
  departure_dtime?: string;
  estimated_arrival_dtime?: string;
}

@Component({
  selector: 'app-ops-transport-form',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatButtonModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatSelectModule,
  ],
  template: `
    <form
      [formGroup]="form"
      (ngSubmit)="onSubmit()"
      class="ops-transport-form"
      aria-label="Transport details">
      <div class="ops-transport-form__row ops-transport-form__row--3col">
        <mat-form-field appearance="outline" subscriptSizing="dynamic">
          <mat-label>Driver name</mat-label>
          <input
            matInput
            formControlName="driver_name"
            maxlength="120"
            placeholder="Full name of the driver"
            required />
          @if (form.controls['driver_name'].hasError('required') && form.controls['driver_name'].touched) {
            <mat-error>Driver name is required.</mat-error>
          }
          @if (form.controls['driver_name'].hasError('maxlength')) {
            <mat-error>Max 120 characters.</mat-error>
          }
        </mat-form-field>

        <mat-form-field appearance="outline" subscriptSizing="dynamic">
          <mat-label>Driver licence last 4 (optional)</mat-label>
          <input
            matInput
            formControlName="driver_license_last4"
            maxlength="4"
            placeholder="Last 4 characters only" />
        </mat-form-field>

        <mat-form-field appearance="outline" subscriptSizing="dynamic">
          <mat-label>Transport mode</mat-label>
          <mat-select formControlName="transport_mode" aria-label="Transport mode">
            <mat-option value="">-- Select --</mat-option>
            @for (opt of transportModeOptions; track opt.value) {
              <mat-option [value]="opt.value">{{ opt.label }}</mat-option>
            }
          </mat-select>
        </mat-form-field>
      </div>

      <div class="ops-transport-form__row ops-transport-form__row--3col">
        <mat-form-field appearance="outline" subscriptSizing="dynamic">
          <mat-label>Vehicle ID</mat-label>
          <input matInput formControlName="vehicle_id" maxlength="30" />
        </mat-form-field>

        <mat-form-field appearance="outline" subscriptSizing="dynamic">
          <mat-label>Vehicle registration</mat-label>
          <input matInput formControlName="vehicle_registration" maxlength="30" />
        </mat-form-field>

        <mat-form-field appearance="outline" subscriptSizing="dynamic">
          <mat-label>Vehicle type</mat-label>
          <input matInput formControlName="vehicle_type" maxlength="40"
            placeholder="Box truck, pickup, refrigerated..." />
        </mat-form-field>
      </div>

      <div class="ops-transport-form__row ops-transport-form__row--2col">
        <mat-form-field appearance="outline" subscriptSizing="dynamic">
          <mat-label>Departure (date & time)</mat-label>
          <input
            matInput
            type="datetime-local"
            formControlName="departure_dtime" />
        </mat-form-field>

        <mat-form-field appearance="outline" subscriptSizing="dynamic">
          <mat-label>Estimated arrival</mat-label>
          <input
            matInput
            type="datetime-local"
            formControlName="estimated_arrival_dtime" />
          @if (form.errors?.['arrivalBeforeDeparture'] && (form.touched || form.dirty)) {
            <mat-error>Arrival must be after departure.</mat-error>
          }
        </mat-form-field>
      </div>

      <mat-form-field appearance="outline" subscriptSizing="dynamic">
        <mat-label>Transport notes</mat-label>
        <textarea
          matInput
          formControlName="transport_notes"
          rows="2"
          maxlength="500"
          placeholder="Route details, special handling, etc."></textarea>
        @if (form.controls['transport_notes'].hasError('maxlength')) {
          <mat-error>Max 500 characters.</mat-error>
        }
      </mat-form-field>

      <div class="ops-transport-form__actions">
        @if (showCancel()) {
          <button
            type="button"
            matButton
            (click)="cancelled.emit()"
            [disabled]="submitting()">
            Cancel
          </button>
        }
        <button
          type="submit"
          mat-flat-button
          color="primary"
          [disabled]="submitting() || form.invalid">
          <mat-icon aria-hidden="true">local_shipping</mat-icon>
          {{ submitLabel() }}
        </button>
      </div>
    </form>
  `,
  styles: [`
    :host { display: block; }

    .ops-transport-form {
      display: flex;
      flex-direction: column;
      gap: 12px;
    }

    .ops-transport-form__row {
      display: grid;
      gap: 12px;
    }

    .ops-transport-form__row--2col {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    .ops-transport-form__row--3col {
      grid-template-columns: repeat(3, minmax(0, 1fr));
    }

    .ops-transport-form__actions {
      display: flex;
      gap: 10px;
      justify-content: flex-end;
      padding-top: 6px;
      border-top: 1px solid var(--ops-outline, rgba(55, 53, 47, 0.08));
    }

    @media (max-width: 760px) {
      .ops-transport-form__row--2col,
      .ops-transport-form__row--3col {
        grid-template-columns: 1fr;
      }
    }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class OpsTransportFormComponent {
  readonly submitLabel = input<string>('Record dispatch');
  readonly submitting = input<boolean>(false);
  readonly showCancel = input<boolean>(true);

  readonly submitted = output<OpsTransportFormValue>();
  readonly cancelled = output<void>();

  private readonly fb = inject(FormBuilder);
  readonly transportModeOptions = TRANSPORT_MODE_OPTIONS;

  readonly form: FormGroup = this.fb.nonNullable.group(
    {
      driver_name: ['', [trimRequiredAndMaxLength(120)]],
      driver_license_last4: ['', [Validators.maxLength(4)]],
      vehicle_id: ['', [Validators.maxLength(30)]],
      vehicle_registration: ['', [Validators.maxLength(30)]],
      vehicle_type: ['', [Validators.maxLength(40)]],
      transport_mode: [''],
      transport_notes: ['', [Validators.maxLength(500)]],
      departure_dtime: [''],
      estimated_arrival_dtime: [''],
    },
    { validators: [arrivalAfterDepartureValidator] },
  );

  onSubmit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    const raw = this.form.getRawValue() as OpsTransportFormValue;
    const value: OpsTransportFormValue = {
      driver_name: raw.driver_name.trim(),
      driver_license_last4: raw.driver_license_last4?.trim() || undefined,
      vehicle_id: raw.vehicle_id?.trim() || undefined,
      vehicle_registration: raw.vehicle_registration?.trim() || undefined,
      vehicle_type: raw.vehicle_type?.trim() || undefined,
      transport_mode: raw.transport_mode?.trim() || undefined,
      transport_notes: raw.transport_notes?.trim() || undefined,
      departure_dtime: raw.departure_dtime || undefined,
      estimated_arrival_dtime: raw.estimated_arrival_dtime || undefined,
    };
    this.submitted.emit(value);
  }
}

function arrivalAfterDepartureValidator(
  control: AbstractControl,
): ValidationErrors | null {
  const departure = control.get('departure_dtime')?.value;
  const arrival = control.get('estimated_arrival_dtime')?.value;
  if (!departure || !arrival) {
    return null;
  }
  const d = new Date(departure).getTime();
  const a = new Date(arrival).getTime();
  if (Number.isNaN(d) || Number.isNaN(a)) {
    return null;
  }
  return a > d ? null : { arrivalBeforeDeparture: true };
}

function trimRequiredAndMaxLength(maxLength: number): ValidatorFn {
  return (control: AbstractControl): ValidationErrors | null => {
    const value = String(control.value ?? '');
    const trimmed = value.trim();
    if (!trimmed) {
      return { required: true };
    }
    if (trimmed.length > maxLength) {
      return {
        maxlength: {
          requiredLength: maxLength,
          actualLength: trimmed.length,
        },
      };
    }
    return null;
  };
}
