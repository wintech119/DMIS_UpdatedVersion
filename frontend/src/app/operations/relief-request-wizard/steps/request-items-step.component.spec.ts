import { ComponentFixture, TestBed } from '@angular/core/testing';
import { FormArray, FormControl, FormGroup, Validators } from '@angular/forms';
import { By } from '@angular/platform-browser';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { MatTooltip } from '@angular/material/tooltip';

import { RequestItemsStepComponent } from './request-items-step.component';
import { trimmedRequiredValidator } from '../relief-request-wizard.component';

const REQUEST_REASON_MAX_LENGTH = 255;
const REQUEST_NOTES_MAX_LENGTH = 500;

function syncRequestNotesValidators(form: FormGroup): void {
  const notes = form.get('rqst_notes_text')!;
  notes.setValidators(
    form.get('urgency_ind')?.value === 'H'
      ? [trimmedRequiredValidator, Validators.maxLength(REQUEST_NOTES_MAX_LENGTH)]
      : [Validators.maxLength(REQUEST_NOTES_MAX_LENGTH)],
  );
  notes.updateValueAndValidity({ emitEvent: false });
}

function syncItemReasonValidators(itemGroup: FormGroup): void {
  const reason = itemGroup.get('rqst_reason_desc')!;
  const urgency = itemGroup.get('urgency_ind')?.value;
  reason.setValidators(
    urgency === 'C' || urgency === 'H'
      ? [trimmedRequiredValidator, Validators.maxLength(REQUEST_REASON_MAX_LENGTH)]
      : [Validators.maxLength(REQUEST_REASON_MAX_LENGTH)],
  );
  reason.updateValueAndValidity({ emitEvent: false });
}

function wireUrgencyValidation(form: FormGroup, itemsArray: FormArray): void {
  syncRequestNotesValidators(form);
  form.get('urgency_ind')?.valueChanges.subscribe(() => syncRequestNotesValidators(form));

  itemsArray.controls.forEach((group) => {
    const itemGroup = group as FormGroup;
    syncItemReasonValidators(itemGroup);
    itemGroup.get('urgency_ind')?.valueChanges.subscribe(() => syncItemReasonValidators(itemGroup));
  });
}

describe('RequestItemsStepComponent', () => {
  let fixture: ComponentFixture<RequestItemsStepComponent>;
  let component: RequestItemsStepComponent;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [NoopAnimationsModule, RequestItemsStepComponent],
    }).compileComponents();

    fixture = TestBed.createComponent(RequestItemsStepComponent);
    component = fixture.componentInstance;

    component.form = new FormGroup({
      agency_id: new FormControl<number | null>(null, Validators.required),
      eligible_event_id: new FormControl<number | null>(null),
      urgency_ind: new FormControl<string | null>(null, Validators.required),
      rqst_notes_text: new FormControl('', [Validators.maxLength(REQUEST_NOTES_MAX_LENGTH)]),
      items: new FormArray([
        new FormGroup({
          item_id: new FormControl<number | string | null>(null, Validators.required),
          item_name: new FormControl(''),
          request_qty: new FormControl<number | null>(1, [Validators.required, Validators.min(1)]),
          urgency_ind: new FormControl<string | null>(null),
          rqst_reason_desc: new FormControl('', [Validators.maxLength(REQUEST_REASON_MAX_LENGTH)]),
          required_by_date: new FormControl<string | null>(null),
        }),
      ]),
    });
    component.itemsArray = component.form.get('items') as FormArray;
    wireUrgencyValidation(component.form, component.itemsArray);
    component.onAddItem = jasmine.createSpy('onAddItem');
    component.onRemoveItem = jasmine.createSpy('onRemoveItem');
    component.agencyOptions = [{ value: 12, label: 'St. Mary Parish Council' }];
    component.eventOptions = [{ value: 44, label: 'Flood Response 2026' }];
    component.itemOptions = [{ value: 23, label: 'Blankets' }];
    component.submissionModeLabel = 'Request on behalf of a managed entity';
    component.submissionModeHint = 'Choose which agency under your authority needs supplies. You are submitting on their behalf.';
    component.requestingEntityLabel = 'Requesting entity';
    component.creationBlocked = false;

    fixture.detectChanges();
  });

  it('replaces stale design-system copy and exposes field help tooltips', () => {
    const text = fixture.nativeElement.textContent as string;

    expect(text).toContain('Select the requesting agency and any linked event');
    expect(text).not.toContain('Stitch');

    const agencyHelpButton = fixture.debugElement.query(By.css(`[aria-label="${component.requestingAgencyHelpLabel}"]`));
    const agencyTooltip = agencyHelpButton.injector.get(MatTooltip);
    expect(agencyTooltip.message).toContain('agency under your authority');

    expect(fixture.debugElement.queryAll(By.css('.field-help-button')).length).toBeGreaterThanOrEqual(4);
  });

  it('filters item-name autocomplete options and writes the selected item id', () => {
    const itemGroup = component.itemsArray.at(0) as FormGroup;
    component.itemOptions = [
      { value: 21, label: 'Tarpaulins' },
      { value: 22, label: 'Water Purification Tablets' },
      { value: 23, label: 'Blankets' },
    ];

    itemGroup.get('item_name')?.setValue('water');

    expect(component.filterItemOptions(itemGroup)).toEqual([
      { value: 22, label: 'Water Purification Tablets' },
    ]);

    itemGroup.get('item_name')?.setValue('Water Purification Tablets');
    component.onItemBlur(itemGroup);
    expect(itemGroup.get('item_id')?.value).toBe(22);
    expect(component.hasItemMatch(itemGroup)).toBeTrue();

    itemGroup.get('item_name')?.setValue('');
    component.onItemBlur(itemGroup);
    expect(itemGroup.get('item_id')?.value).toBeNull();

    component.onItemSelected(itemGroup, { option: { value: '23' } } as never);
    expect(itemGroup.get('item_id')?.value).toBe(23);
    expect(itemGroup.get('item_name')?.value).toBe('Blankets');
    expect(itemGroup.get('item_id')?.touched).toBeTrue();
    expect(itemGroup.get('item_id')?.dirty).toBeTrue();
  });

  it('shows dual-mode agency guidance when self and managed-entity submission are both allowed', () => {
    component.submissionModeLabel = 'Your organisation or managed entity';
    fixture.detectChanges();

    expect(component.requestingAgencyTooltip).toBe(
      'Choose whether this request is for your organisation or an agency you manage.',
    );
  });

  it('uses the dynamic requesting entity label in the required agency error', () => {
    const agency = component.form.get('agency_id')!;
    component.requestingEntityLabel = 'Represented requester';

    agency.markAsTouched();
    fixture.detectChanges();

    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('Represented requester is required.');
    expect(text).not.toContain('Requesting entity is required.');
  });

  it('normalizes blank requesting entity labels for help text and errors', () => {
    const agency = component.form.get('agency_id')!;
    component.requestingEntityLabel = '   ';

    agency.markAsTouched();
    fixture.detectChanges();

    expect(component.requestingAgencyHelpLabel).toBe('More information about Requesting entity');
    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('Requesting entity is required.');
  });

  it('flags item reason entries longer than 255 characters and renders the bound error', () => {
    const itemGroup = component.itemsArray.at(0) as FormGroup;
    const reason = itemGroup.get('rqst_reason_desc')!;

    reason.setValue('x'.repeat(256));
    reason.markAsTouched();
    fixture.detectChanges();

    expect(reason.hasError('maxlength')).toBeTrue();
    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('Reason must be 255 characters or fewer.');
  });

  it('requires the item reason when the line urgency is C or H', () => {
    const itemGroup = component.itemsArray.at(0) as FormGroup;
    const reason = itemGroup.get('rqst_reason_desc')!;
    itemGroup.get('urgency_ind')!.setValue('C');
    reason.markAsTouched();
    fixture.detectChanges();

    expect(reason.hasError('required')).toBeTrue();
    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('Required for C/H');
  });

  it('rejects whitespace-only item reasons as a C/H justification', () => {
    const itemGroup = component.itemsArray.at(0) as FormGroup;
    const reason = itemGroup.get('rqst_reason_desc')!;
    itemGroup.get('urgency_ind')!.setValue('C');

    reason.setValue('    ');
    reason.markAsTouched();
    fixture.detectChanges();
    expect(reason.hasError('required')).toBeTrue();

    reason.setValue('Surge shortfall at staging point.');
    fixture.detectChanges();
    expect(reason.hasError('required')).toBeFalse();
    expect(reason.valid).toBeTrue();
  });

  it('surfaces the high-urgency justification error on the request notes field', () => {
    const notes = component.form.get('rqst_notes_text')!;
    component.form.get('urgency_ind')!.setValue('H');
    notes.markAsTouched();
    fixture.detectChanges();

    expect(notes.hasError('required')).toBeTrue();
    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('Justification is required for high-urgency requests.');
  });

  it('renders four size="lg" urgency chips inside a radiogroup with aria-label', () => {
    const host = fixture.nativeElement as HTMLElement;
    const group = host.querySelector<HTMLElement>('.urgency-chip-group');
    expect(group).not.toBeNull();
    expect(group?.getAttribute('role')).toBe('radiogroup');
    expect(group?.getAttribute('aria-label')).toBe('Select request urgency');

    const chips = host.querySelectorAll<HTMLElement>('app-ops-status-chip');
    expect(chips.length).toBe(4);
    chips.forEach((chip) => {
      expect(chip.getAttribute('size')).toBe('lg');
    });

    const hosts = host.querySelectorAll<HTMLElement>('.urgency-chip-host');
    expect(hosts.length).toBe(4);
    expect(hosts[0].getAttribute('tabindex')).toBe('0');
    expect(hosts[1].getAttribute('tabindex')).toBe('-1');
    expect(hosts[2].getAttribute('tabindex')).toBe('-1');
    expect(hosts[3].getAttribute('tabindex')).toBe('-1');
  });

  it('marks exactly one chip aria-checked="true" when an urgency is selected', () => {
    component.form.get('urgency_ind')!.setValue('H');
    fixture.detectChanges();

    const host = fixture.nativeElement as HTMLElement;
    const checkedHosts = host.querySelectorAll<HTMLElement>('[role="radio"][aria-checked="true"]');
    expect(checkedHosts.length).toBe(1);
    // 'H' is the second URGENCY_OPTIONS entry → index 1.
    const allHosts = host.querySelectorAll<HTMLElement>('[role="radio"]');
    expect(allHosts[1].getAttribute('aria-checked')).toBe('true');
    expect(allHosts[1].textContent).toContain('High');
  });

  it('marks the urgency chip-group aria-invalid when control is invalid and touched', () => {
    component.form.get('urgency_ind')!.markAsTouched();
    fixture.detectChanges();

    const host = fixture.nativeElement as HTMLElement;
    const group = host.querySelector<HTMLElement>('.urgency-chip-group');
    expect(group?.getAttribute('aria-invalid')).toBe('true');
  });

  it('renders a visible char counter and verbatim helper text under the notes field', () => {
    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('Reviewers see this verbatim.');
    expect(text).toContain('0 / 500');
  });

  it('updates the notes char counter live when the user types', () => {
    component.form.get('rqst_notes_text')!.setValue('Hello, Kemar.');
    fixture.detectChanges();

    expect(component.notesCharCount()).toBe(13);
    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('13 / 500');
  });

  it('renders a dashed full-width Add Item CTA wired to onAddItem', () => {
    const host = fixture.nativeElement as HTMLElement;
    const cta = host.querySelector<HTMLButtonElement>('.step-items-add-cta');
    expect(cta).not.toBeNull();
    expect(cta?.textContent ?? '').toContain('Add another item');

    cta!.click();
    expect(component.onAddItem as jasmine.Spy).toHaveBeenCalled();
  });
});
