import {
  Component, ChangeDetectionStrategy, Input,
} from '@angular/core';
import { ReactiveFormsModule, FormGroup, FormArray } from '@angular/forms';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatDatepickerModule } from '@angular/material/datepicker';
import { MatNativeDateModule } from '@angular/material/core';
import { MatTooltipModule } from '@angular/material/tooltip';

import { URGENCY_OPTIONS, UrgencyCode } from '../../models/operations.model';

export interface RequestReferenceOption {
  value: number;
  label: string;
}

@Component({
  selector: 'app-request-items-step',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatButtonModule,
    MatIconModule,
    MatDatepickerModule,
    MatNativeDateModule,
    MatTooltipModule,
  ],
  templateUrl: './request-items-step.component.html',
  styleUrl: './request-items-step.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RequestItemsStepComponent {
  @Input({ required: true }) form!: FormGroup;
  @Input({ required: true }) itemsArray!: FormArray;
  @Input({ required: true }) onAddItem!: () => void;
  @Input({ required: true }) onRemoveItem!: (index: number) => void;
  @Input({ required: true }) agencyOptions: RequestReferenceOption[] = [];
  @Input({ required: true }) eventOptions: RequestReferenceOption[] = [];
  @Input({ required: true }) requestDateText = '';
  @Input({ required: true }) requestDateHint = '';
  @Input({ required: true }) submissionModeLabel = '';
  @Input({ required: true }) submissionModeHint = '';
  @Input({ required: true }) creationBlocked = false;

  readonly urgencyOptions = URGENCY_OPTIONS;

  isReasonRequired(urgency: UrgencyCode | string | null): boolean {
    return urgency === 'C' || urgency === 'H';
  }

  selectRequestUrgency(urgency: UrgencyCode): void {
    if (this.creationBlocked) {
      return;
    }
    this.form.get('urgency_ind')?.setValue(urgency);
    this.form.get('urgency_ind')?.markAsTouched();
  }

  getControlError(controlName: 'agency_id' | 'urgency_ind' | 'eligible_event_id'): string | null {
    const control = this.form.get(controlName);
    if (!control || !(control.touched || control.dirty || control.errors?.['server'])) {
      return null;
    }

    if (control.hasError('required')) {
      if (controlName === 'agency_id') {
        return 'Requesting agency is required.';
      }
      if (controlName === 'urgency_ind') {
        return 'Request urgency is required.';
      }
    }

    const serverMessage = control.getError('server');
    return typeof serverMessage === 'string' ? serverMessage : null;
  }

  trackByIndex(index: number): number {
    return index;
  }
}
