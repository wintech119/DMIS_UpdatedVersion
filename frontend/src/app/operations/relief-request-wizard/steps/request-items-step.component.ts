import {
  Component, ChangeDetectionStrategy, DestroyRef, Input, OnChanges, OnInit, SimpleChanges, inject, signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
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
import { Subscription } from 'rxjs';

import {
  RequestReferenceOption,
  URGENCY_OPTIONS,
  UrgencyCode,
} from '../../models/operations.model';
import { OpsStatusChipComponent } from '../../shared/ops-status-chip.component';
import { DmisEmptyStateComponent } from '../../../replenishment/shared/dmis-empty-state/dmis-empty-state.component';
import {
  formatOperationsUrgency,
  getOperationsUrgencyTone,
  mapOperationsToneToChipTone,
  type OperationsTone,
} from '../../operations-display.util';

type ChipTone = ReturnType<typeof mapOperationsToneToChipTone>;

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
    OpsStatusChipComponent,
    DmisEmptyStateComponent,
  ],
  templateUrl: './request-items-step.component.html',
  styleUrl: './request-items-step.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RequestItemsStepComponent implements OnChanges, OnInit {
  private readonly destroyRef = inject(DestroyRef);

  @Input({ required: true }) form!: FormGroup;
  @Input({ required: true }) itemsArray!: FormArray<FormGroup>;
  @Input({ required: true }) onAddItem!: () => void;
  @Input({ required: true }) onRemoveItem!: (index: number) => void;
  @Input({ required: true }) agencyOptions: RequestReferenceOption[] = [];
  @Input({ required: true }) eventOptions: RequestReferenceOption[] = [];
  @Input({ required: true }) itemOptions: RequestReferenceOption[] = [];
  @Input({ required: true }) submissionModeLabel = '';
  @Input({ required: true }) submissionModeHint = '';
  @Input({ required: true }) requestingEntityLabel!: string;
  @Input({ required: true }) creationBlocked = false;

  ngOnInit(): void {
    // Defensive bind for cases where the parent assigns inputs directly
    // (e.g. unit tests using `component.form = new FormGroup(...)`) and
    // ngOnChanges does not fire. Subscribing here ensures the notes char
    // counter signal is wired before the first detectChanges paints.
    this.bindNotesCharCount();
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['creationBlocked'] || changes['agencyOptions'] || changes['form'] || changes['itemsArray']) {
      this.syncFormDisabledState();
    }
    if (changes['form']) {
      this.bindNotesCharCount();
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

  /**
   * Char counter for the notes textarea. Backed by a signal so OnPush
   * still re-renders on every keystroke (closes architecture-review
   * Required Change #2 — a getter would freeze under OnPush).
   */
  private readonly notesCharCountSig = signal(0);
  readonly notesCharCount = this.notesCharCountSig.asReadonly();

  /**
   * Roving-tabindex anchor for the urgency chip-group radiogroup. Only
   * one chip is in the tab order at a time; arrow keys cycle focus and
   * Enter/Space commits the selection.
   */
  readonly urgencyFocusIndex = signal(0);

  private notesSubscription: Subscription | null = null;

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

  get requestingAgencyHelpLabel(): string {
    return `More information about ${this.getNormalizedRequestingEntityLabel()}`;
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

  /**
   * Tone resolver for the urgency chips. Routes through the operations
   * display utility so the chip palette stays consistent with the
   * eligibility / dispatch / list surfaces.
   */
  urgencyChipTone(urgency: UrgencyCode): ChipTone {
    const tone: OperationsTone = getOperationsUrgencyTone(urgency);
    return mapOperationsToneToChipTone(tone);
  }

  /**
   * Long label for the chip's screen-reader announcement.
   * Combines `formatOperationsUrgency` with the option hint so the
   * chip reads as "Critical: Immediate action required." rather than
   * just "Critical".
   */
  urgencyAriaLabel(urgency: UrgencyCode, hint: string): string {
    return `${formatOperationsUrgency(urgency)}: ${hint}`;
  }

  onUrgencyKeydown(event: KeyboardEvent, index: number, urgency: UrgencyCode): void {
    const options = this.urgencyOptions;
    if (options.length === 0) {
      return;
    }

    let targetIndex: number | null = null;
    switch (event.key) {
      case 'ArrowRight':
      case 'ArrowDown':
        event.preventDefault();
        targetIndex = (index + 1) % options.length;
        break;
      case 'ArrowLeft':
      case 'ArrowUp':
        event.preventDefault();
        targetIndex = (index - 1 + options.length) % options.length;
        break;
      case 'Home':
        event.preventDefault();
        targetIndex = 0;
        break;
      case 'End':
        event.preventDefault();
        targetIndex = options.length - 1;
        break;
      case 'Enter':
      case ' ':
        event.preventDefault();
        this.selectRequestUrgency(urgency);
        return;
      default:
        return;
    }

    if (targetIndex == null) {
      return;
    }
    this.urgencyFocusIndex.set(targetIndex);
    const hosts = (event.currentTarget as HTMLElement)
      .parentElement
      ?.querySelectorAll<HTMLElement>('[role="radio"]');
    queueMicrotask(() => hosts?.[targetIndex!]?.focus());
  }

  getControlError(controlName: 'agency_id' | 'urgency_ind' | 'eligible_event_id'): string | null {
    const control = this.form.get(controlName);
    if (!control || !(control.touched || control.dirty || control.errors?.['server'])) {
      return null;
    }

    if (control.hasError('required')) {
      if (controlName === 'agency_id') {
        return `${this.getNormalizedRequestingEntityLabel()} is required.`;
      }
      if (controlName === 'urgency_ind') {
        return 'Request urgency is required.';
      }
    }

    const serverMessage = control.getError('server');
    return typeof serverMessage === 'string' ? serverMessage : null;
  }

  /**
   * Bound to `[attr.aria-invalid]` on the urgency chip-group container.
   * Closes architecture-review Required Change #6 (a11y wiring).
   */
  isUrgencyInvalid(): boolean {
    return !!this.getControlError('urgency_ind');
  }

  trackByIndex(index: number): number {
    return index;
  }

  private getNormalizedRequestingEntityLabel(): string {
    return String(this.requestingEntityLabel ?? '').trim() || 'Requesting entity';
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

  private bindNotesCharCount(): void {
    this.notesSubscription?.unsubscribe();
    this.notesSubscription = null;
    const ctrl = this.form?.get('rqst_notes_text');
    if (!ctrl) {
      this.notesCharCountSig.set(0);
      return;
    }
    this.notesCharCountSig.set(String(ctrl.value ?? '').length);
    this.notesSubscription = ctrl.valueChanges
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((value) => this.notesCharCountSig.set(String(value ?? '').length));
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
