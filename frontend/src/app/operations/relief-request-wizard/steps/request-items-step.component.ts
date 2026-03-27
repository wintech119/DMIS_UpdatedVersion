import {
  Component, ChangeDetectionStrategy, Input,
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
  ],
  templateUrl: './request-items-step.component.html',
  styleUrl: './request-items-step.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RequestItemsStepComponent {
  @Input({ required: true }) form!: FormGroup;
  @Input({ required: true }) itemsArray!: FormArray<FormGroup>;
  @Input({ required: true }) onAddItem!: () => void;
  @Input({ required: true }) onRemoveItem!: (index: number) => void;
  @Input({ required: true }) agencyOptions: RequestReferenceOption[] = [];
  @Input({ required: true }) eventOptions: RequestReferenceOption[] = [];
  @Input({ required: true }) itemOptions: RequestReferenceOption[] = [];
  @Input({ required: true }) requestDateText = '';
  @Input({ required: true }) requestDateHint = '';
  @Input({ required: true }) submissionModeLabel = '';
  @Input({ required: true }) submissionModeHint = '';
  @Input({ required: true }) creationBlocked = false;

  readonly urgencyOptions = URGENCY_OPTIONS;
  readonly tooltips = {
    event: 'Link this request to the active event when the support is tied to a live incident. Leave it unlinked when the request is not event-specific.',
    requestDate: 'This is the request intake date recorded for audit history and queue sequencing.',
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
      case 'For subordinate entity':
        return 'Choose the subordinate agency or entity that needs support. The request is still saved against that agency ID even though the form shows names.';
      case 'ODPEM bridge on behalf':
        return 'Choose the beneficiary agency by name. This bridge lane is for transitional ODPEM-assisted request entry and still saves the agency ID underneath.';
      case 'Self request':
        return 'Choose the entity that is requesting relief in this transaction. In self mode this should be the active operational tenant.';
      default:
        return 'Choose the entity that should appear as the requesting entity on this relief request.';
    }
  }

  get submissionModeTooltip(): string {
    return `${this.submissionModeHint} This lane is controlled by the backend permissions advertised for the active tenant.`;
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

  displayItemOption = (value: number | string | null): string => {
    if (typeof value === 'number' && Number.isFinite(value)) {
      return this.itemOptions.find((option) => option.value === value)?.label ?? `Item ${value}`;
    }
    return typeof value === 'string' ? value : '';
  };

  filterItemOptions(itemGroup: AbstractControl): RequestReferenceOption[] {
    const rawValue = itemGroup.get('item_id')?.value;
    const query = String(typeof rawValue === 'string' ? rawValue : '').trim().toLowerCase();
    if (!query) {
      return this.itemOptions.slice(0, 40);
    }
    return this.itemOptions
      .filter((option) => option.label.toLowerCase().includes(query))
      .slice(0, 40);
  }

  onItemInput(itemGroup: AbstractControl, value: string): void {
    const currentValue = itemGroup.get('item_id')?.value;
    if (typeof currentValue === 'number') {
      const selected = this.itemOptions.find((option) => option.value === currentValue);
      if (!selected || selected.label !== value) {
        itemGroup.get('item_id')?.setValue(value);
        this.setItemNameValue(itemGroup, value);
      }
      return;
    }

    if (!value.trim()) {
      itemGroup.get('item_id')?.setValue(null);
      this.setItemNameValue(itemGroup, '');
      return;
    }

    this.setItemNameValue(itemGroup, value);
  }

  onItemSelected(itemGroup: AbstractControl, event: MatAutocompleteSelectedEvent): void {
    const selectedId = Number(event.option.value);
    const selectedLabel = this.itemOptions.find((option) => option.value === selectedId)?.label ?? '';
    itemGroup.get('item_id')?.setValue(selectedId);
    itemGroup.get('item_id')?.markAsTouched();
    itemGroup.get('item_id')?.markAsDirty();
    this.setItemNameValue(itemGroup, selectedLabel);
  }

  markItemSelectionTouched(itemGroup: AbstractControl): void {
    itemGroup.get('item_id')?.markAsTouched();
  }

  private setItemNameValue(itemGroup: AbstractControl, value: string): void {
    const control = itemGroup.get('item_name');
    if (!control) {
      return;
    }
    control.setValue(value.trim(), { emitEvent: false });
  }
}
