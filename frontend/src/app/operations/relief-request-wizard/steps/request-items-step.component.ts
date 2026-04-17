import {
  Component, ChangeDetectionStrategy, Input, OnChanges, SimpleChanges,
} from '@angular/core';
import {
  AbstractControl,
  FormArray,
  FormGroup,
  ReactiveFormsModule,
} from '@angular/forms';
import { MatAutocompleteModule, MatAutocompleteSelectedEvent } from '@angular/material/autocomplete';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatDatepickerModule } from '@angular/material/datepicker';
import { MatNativeDateModule } from '@angular/material/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { TextFieldModule } from '@angular/cdk/text-field';

import {
  RequestReferenceOption,
  URGENCY_OPTIONS,
  UrgencyCode,
} from '../../models/operations.model';

@Component({
  selector: 'app-request-items-step',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatAutocompleteModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatButtonModule,
    MatIconModule,
    MatDatepickerModule,
    MatNativeDateModule,
    MatTooltipModule,
    TextFieldModule,
  ],
  templateUrl: './request-items-step.component.html',
  styleUrl: './request-items-step.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RequestItemsStepComponent implements OnChanges {
  @Input({ required: true }) form!: FormGroup;
  @Input({ required: true }) itemsArray!: FormArray<FormGroup>;
  @Input({ required: true }) onAddItem!: () => void;
  @Input({ required: true }) onRemoveItem!: (index: number) => void;
  @Input({ required: true }) agencyOptions: RequestReferenceOption[] = [];
  @Input({ required: true }) eventOptions: RequestReferenceOption[] = [];
  @Input({ required: true }) itemOptions: RequestReferenceOption[] = [];
  @Input({ required: true }) submissionModeLabel = '';
  @Input({ required: true }) submissionModeHint = '';
  @Input({ required: true }) creationBlocked = false;

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['creationBlocked'] || changes['agencyOptions'] || changes['form'] || changes['itemsArray']) {
      this.syncFormDisabledState();
    }
  }

  readonly urgencyOptions = URGENCY_OPTIONS;
  readonly requestNotesMaxLength = 500;
  readonly requestReasonMaxLength = 255;
  readonly tooltips = {
    event: 'Link this request to the active event when the support is tied to a live incident. Leave it unlinked when the request is not event-specific.',
    requestUrgency: 'Sets the baseline priority for review, packaging, and dispatch unless an item line is given a different urgency.',
    notes: 'Use notes for operational context, delivery constraints, or handling instructions that reviewers and downstream teams should see.',
    addItem: 'Add another requested relief item line to this request.',
    itemName: 'Search and select the requested item by name. The form stores the matching Item Master ID automatically after selection.',
    quantity: 'Enter the total number of units being requested for this item line. Quantity must be at least 1.',
    itemUrgency: 'Leave this blank to follow the overall request urgency. Set it only when this item needs a different priority than the rest of the request.',
    reason: 'Explain the operational need for this item line. A reason is required when line urgency is Critical or High.',
    requiredBy: 'Optional target date for when the item is needed on the ground. This helps planning, packaging, and dispatch timing.',
  } as const;

  get requestingAgencyTooltip(): string {
    switch (this.submissionModeLabel) {
      case 'Your organisation or managed entity':
        return 'Choose whether this request is for your organisation or an agency you manage.';
      case 'Request on behalf of a managed entity':
        return 'Choose which agency under your authority needs supplies.';
      case 'ODPEM-assisted request':
        return 'Choose the agency you are entering this request for.';
      case 'Your organisation\'s request':
        return 'Choose your agency. In most cases there will be only one option.';
      default:
        return 'Choose the agency requesting relief supplies.';
    }
  }

  get isHighUrgency(): boolean {
    return this.form?.get('urgency_ind')?.value === 'H';
  }

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
        return 'Requesting entity is required.';
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

  filterItemOptions(itemGroup: AbstractControl): RequestReferenceOption[] {
    const query = String(itemGroup.get('item_name')?.value ?? '').trim().toLowerCase();
    if (!query) {
      return this.itemOptions.slice(0, 40);
    }
    return this.itemOptions
      .filter((option) => option.label.toLowerCase().includes(query))
      .slice(0, 40);
  }

  onItemSelected(itemGroup: AbstractControl, event: MatAutocompleteSelectedEvent): void {
    const selectedId = Number(event.option.value);
    const selectedLabel = this.itemOptions.find((option) => option.value === selectedId)?.label ?? '';
    itemGroup.get('item_id')?.setValue(selectedId);
    itemGroup.get('item_id')?.markAsTouched();
    itemGroup.get('item_id')?.markAsDirty();
    itemGroup.get('item_name')?.setValue(selectedLabel, { emitEvent: false });
  }

  onItemBlur(itemGroup: AbstractControl): void {
    const typed = String(itemGroup.get('item_name')?.value ?? '').trim();
    const currentId = itemGroup.get('item_id')?.value;

    if (!typed) {
      itemGroup.get('item_id')?.setValue(null);
      itemGroup.get('item_id')?.markAsTouched();
      return;
    }

    // If there's already a valid selection, check the name still matches
    if (typeof currentId === 'number' && currentId > 0) {
      const match = this.itemOptions.find((o) => o.value === currentId);
      if (match && match.label === typed) {
        return; // Selection is still valid
      }
    }

    // Try exact match by label
    const exact = this.itemOptions.find((o) => o.label.toLowerCase() === typed.toLowerCase());
    if (exact) {
      itemGroup.get('item_id')?.setValue(exact.value);
      itemGroup.get('item_name')?.setValue(exact.label, { emitEvent: false });
    } else {
      // No valid match — clear item_id so validation catches it
      itemGroup.get('item_id')?.setValue(null);
    }
    itemGroup.get('item_id')?.markAsTouched();
  }

  hasItemMatch(itemGroup: AbstractControl): boolean {
    const id = itemGroup.get('item_id')?.value;
    return typeof id === 'number' && Number.isFinite(id) && id > 0;
  }

  private syncFormDisabledState(): void {
    if (!this.form) return;
    const opts = { emitEvent: false };

    // Header-level form controls
    const agencyBlocked = this.creationBlocked || this.agencyOptions.length === 0;
    const agency = this.form.get('agency_id');
    if (agencyBlocked) {
      agency?.disable(opts);
    } else {
      agency?.enable(opts);
    }

    const event = this.form.get('eligible_event_id');
    if (this.creationBlocked) {
      event?.disable(opts);
    } else {
      event?.enable(opts);
    }

    // Item-level form controls
    if (!this.itemsArray) return;
    const itemFields = ['item_name', 'request_qty', 'urgency_ind', 'rqst_reason_desc', 'required_by_date'];
    for (const group of this.itemsArray.controls) {
      for (const field of itemFields) {
        const control = group.get(field);
        if (this.creationBlocked) {
          control?.disable(opts);
        } else {
          control?.enable(opts);
        }
      }
    }
  }
}
