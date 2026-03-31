import { ComponentFixture, TestBed } from '@angular/core/testing';
import { FormArray, FormControl, FormGroup, Validators } from '@angular/forms';
import { By } from '@angular/platform-browser';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { MatTooltip } from '@angular/material/tooltip';

import { RequestItemsStepComponent } from './request-items-step.component';

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
      rqst_notes_text: new FormControl(''),
      items: new FormArray([
        new FormGroup({
          item_id: new FormControl<number | string | null>(null, Validators.required),
          item_name: new FormControl(''),
          request_qty: new FormControl<number | null>(1, [Validators.required, Validators.min(1)]),
          urgency_ind: new FormControl<string | null>(null),
          rqst_reason_desc: new FormControl(''),
          required_by_date: new FormControl<string | null>(null),
        }),
      ]),
    });
    component.itemsArray = component.form.get('items') as FormArray;
    component.onAddItem = jasmine.createSpy('onAddItem');
    component.onRemoveItem = jasmine.createSpy('onRemoveItem');
    component.agencyOptions = [{ value: 12, label: 'St. Mary Parish Council' }];
    component.eventOptions = [{ value: 44, label: 'Flood Response 2026' }];
    component.itemOptions = [{ value: 23, label: 'Blankets' }];
    component.submissionModeLabel = 'Request on behalf of a managed entity';
    component.submissionModeHint = 'Choose which agency under your authority needs supplies. You are submitting on their behalf.';
    component.creationBlocked = false;

    fixture.detectChanges();
  });

  it('replaces stale design-system copy and exposes field help tooltips', () => {
    const text = fixture.nativeElement.textContent as string;

    expect(text).toContain('Select the requesting agency and any linked event');
    expect(text).not.toContain('Stitch');

    const agencyHelpButton = fixture.debugElement.query(By.css('[aria-label="More information about Requesting entity"]'));
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
});
