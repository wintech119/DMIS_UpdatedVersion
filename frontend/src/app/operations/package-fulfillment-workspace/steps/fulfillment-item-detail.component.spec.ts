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
    addItemWarehouse: jasmine.createSpy('addItemWarehouse'),
    previewLoadingByItem: jasmine.createSpy('previewLoadingByItem').and.returnValue({}),
    addingWarehouseByItem: jasmine.createSpy('addingWarehouseByItem').and.returnValue({}),
    loadedWarehousesByItem: jasmine.createSpy('loadedWarehousesByItem').and.returnValue({}),
  };

  const baseItem: AllocationItemGroup = {
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
    remaining_shortfall_qty: '42',
    continuation_recommended: false,
    alternate_warehouses: [],
  };

  function buildItemWithAlternates(overrides: Partial<AllocationItemGroup> = {}): AllocationItemGroup {
    return {
      ...baseItem,
      continuation_recommended: true,
      alternate_warehouses: [
        {
          warehouse_id: 101,
          warehouse_name: 'Kingston Central',
          available_qty: '20',
          suggested_qty: '10',
          can_fully_cover: false,
        },
        {
          warehouse_id: 102,
          warehouse_name: 'Spanish Town',
          available_qty: '50',
          suggested_qty: '42',
          can_fully_cover: true,
        },
        {
          warehouse_id: 103,
          warehouse_name: 'Montego Bay',
          available_qty: '15',
          suggested_qty: '15',
          can_fully_cover: false,
        },
      ],
      ...overrides,
    };
  }

  beforeEach(() => {
    storeStub.getItemAvailabilityIssue.calls.reset();
    storeStub.getItemAvailabilityIssue.and.returnValue(null);
    storeStub.addItemWarehouse.calls.reset();
    storeStub.loadedWarehousesByItem.and.returnValue({});
    storeStub.previewLoadingByItem.and.returnValue({});
    storeStub.addingWarehouseByItem.and.returnValue({});
  });

  it('renders the shared warehouse availability state when the selected item has no candidates', async () => {
    storeStub.getItemAvailabilityIssue.and.returnValue({ kind: 'no-candidates', scope: 'item' });

    await TestBed.configureTestingModule({
      imports: [FulfillmentItemDetailComponent],
    }).compileComponents();

    const fixture = TestBed.createComponent(FulfillmentItemDetailComponent);
    fixture.componentRef.setInput('item', baseItem);
    fixture.componentRef.setInput('store', storeStub as never);
    fixture.detectChanges();

    const text = fixture.nativeElement.textContent.replace(/\s+/g, ' ').trim();
    expect(text).toContain('Portable Water Container is not stocked in an available warehouse');
    expect(text).not.toContain('Qty to reserve');
  });

  it('excludes already-loaded warehouses from the alternate cards', async () => {
    storeStub.loadedWarehousesByItem.and.returnValue({ 44: [101] });
    const item = buildItemWithAlternates();

    await TestBed.configureTestingModule({
      imports: [FulfillmentItemDetailComponent],
    }).compileComponents();

    const fixture = TestBed.createComponent(FulfillmentItemDetailComponent);
    fixture.componentRef.setInput('item', item);
    fixture.componentRef.setInput('store', storeStub as never);
    fixture.detectChanges();

    const cards = fixture.nativeElement.querySelectorAll('.detail__alternate-card') as NodeListOf<HTMLElement>;
    expect(cards.length).toBe(2);
    const cardText = Array.from(cards).map((c) => c.textContent ?? '').join(' ');
    expect(cardText).not.toContain('Kingston Central');
    expect(cardText).toContain('Spanish Town');
    expect(cardText).toContain('Montego Bay');
  });

  it('calls addItemWarehouse with the correct id when the visible Add this warehouse button is clicked', async () => {
    storeStub.loadedWarehousesByItem.and.returnValue({ 44: [101] });
    const item = buildItemWithAlternates();

    await TestBed.configureTestingModule({
      imports: [FulfillmentItemDetailComponent],
    }).compileComponents();

    const fixture = TestBed.createComponent(FulfillmentItemDetailComponent);
    fixture.componentRef.setInput('item', item);
    fixture.componentRef.setInput('store', storeStub as never);
    fixture.detectChanges();

    const cards = fixture.nativeElement.querySelectorAll('.detail__alternate-card') as NodeListOf<HTMLElement>;
    expect(cards.length).toBe(2);
    const firstVisibleCard = cards[0];
    expect((firstVisibleCard.textContent ?? '')).toContain('Spanish Town');
    const button = firstVisibleCard.querySelector('button') as HTMLButtonElement;
    button.click();

    expect(storeStub.addItemWarehouse).toHaveBeenCalledTimes(1);
    expect(storeStub.addItemWarehouse).toHaveBeenCalledWith(44, 102);
  });

  it('renders continuation title with effective_remaining_qty and updated copy', async () => {
    const item = buildItemWithAlternates({
      remaining_shortfall_qty: '42',
      effective_remaining_qty: '17',
      alternate_warehouses: [
        {
          warehouse_id: 102,
          warehouse_name: 'Spanish Town',
          available_qty: '50',
          suggested_qty: '17',
          can_fully_cover: true,
        },
      ],
    });

    await TestBed.configureTestingModule({
      imports: [FulfillmentItemDetailComponent],
    }).compileComponents();

    const fixture = TestBed.createComponent(FulfillmentItemDetailComponent);
    fixture.componentRef.setInput('item', item);
    fixture.componentRef.setInput('store', storeStub as never);
    fixture.detectChanges();

    const title = fixture.nativeElement.querySelector('.detail__continuation-title') as HTMLElement;
    expect(title).toBeTruthy();
    const titleText = (title.textContent ?? '').trim();
    expect(titleText).toContain('17');
    expect(titleText).toContain('still need coverage');
    expect(titleText).not.toContain('after this warehouse');
  });

  it('shows eligible warehouse continuation cards even when shortfall is already covered', async () => {
    const item = buildItemWithAlternates({
      continuation_recommended: false,
      remaining_shortfall_qty: '0',
      effective_remaining_qty: '0',
      alternate_warehouses: [
        {
          warehouse_id: 102,
          warehouse_name: 'Spanish Town',
          available_qty: '50',
          suggested_qty: '0',
          can_fully_cover: true,
        },
      ],
    });

    await TestBed.configureTestingModule({
      imports: [FulfillmentItemDetailComponent],
    }).compileComponents();

    const fixture = TestBed.createComponent(FulfillmentItemDetailComponent);
    fixture.componentRef.setInput('item', item);
    fixture.componentRef.setInput('store', storeStub as never);
    fixture.detectChanges();

    const title = fixture.nativeElement.querySelector('.detail__continuation-title') as HTMLElement;
    const badge = fixture.nativeElement.querySelector('.detail__alternate-badge') as HTMLElement;
    expect(title.textContent ?? '').toContain('Other eligible warehouses available');
    expect(badge.textContent ?? '').toContain('Eligible');
  });
});
