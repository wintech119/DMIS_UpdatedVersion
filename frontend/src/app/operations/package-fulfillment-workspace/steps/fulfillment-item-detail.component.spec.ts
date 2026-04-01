import { TestBed } from '@angular/core/testing';

import { FulfillmentItemDetailComponent } from './fulfillment-item-detail.component';
import { AllocationItemGroup } from '../../models/operations.model';

describe('FulfillmentItemDetailComponent', () => {
  const storeStub = {
    getItemAvailabilityIssue: jasmine.createSpy('getItemAvailabilityIssue'),
    getItemValidationMessage: jasmine.createSpy('getItemValidationMessage').and.returnValue(null),
    isRuleBypassedForItem: jasmine.createSpy('isRuleBypassedForItem').and.returnValue(false),
    getSelectedTotalForItem: jasmine.createSpy('getSelectedTotalForItem').and.returnValue(0),
    getUncoveredQtyForItem: jasmine.createSpy('getUncoveredQtyForItem').and.returnValue(42),
    clearItemSelection: jasmine.createSpy('clearItemSelection'),
    getSelectedQtyForCandidate: jasmine.createSpy('getSelectedQtyForCandidate').and.returnValue(0),
    setCandidateQuantity: jasmine.createSpy('setCandidateQuantity'),
    effectiveWarehouseForItem: jasmine.createSpy('effectiveWarehouseForItem').and.returnValue(''),
    updateItemWarehouse: jasmine.createSpy('updateItemWarehouse'),
  };

  const item: AllocationItemGroup = {
    item_id: 44,
    item_code: 'WATER-044',
    item_name: 'Portable Water Container',
    request_qty: '42',
    issue_qty: '0',
    remaining_qty: '42',
    urgency_ind: 'H',
    candidates: [],
    suggested_allocations: [],
    remaining_after_suggestion: '42',
    can_expire_flag: false,
    issuance_order: 'FIFO',
    compliance_markers: [],
    override_required: false,
  };

  it('renders the shared warehouse availability state when the selected item has no candidates', async () => {
    storeStub.getItemAvailabilityIssue.and.returnValue({ kind: 'no-candidates', scope: 'item' });

    await TestBed.configureTestingModule({
      imports: [FulfillmentItemDetailComponent],
    }).compileComponents();

    const fixture = TestBed.createComponent(FulfillmentItemDetailComponent);
    fixture.componentRef.setInput('item', item);
    fixture.componentRef.setInput('store', storeStub as never);
    fixture.detectChanges();

    const text = fixture.nativeElement.textContent.replace(/\s+/g, ' ').trim();
    expect(text).toContain('Portable Water Container is not stocked in an available warehouse');
    expect(text).not.toContain('Qty to reserve');
  });
});
