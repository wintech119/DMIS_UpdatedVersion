import { TestBed } from '@angular/core/testing';

import { FulfillmentItemDetailComponent } from './fulfillment-item-detail.component';
import {
  AllocationCandidate,
  AllocationItemGroup,
  WarehouseAllocationCard,
} from '../../models/operations.model';

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
    warehouse_cards: [],
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

  /**
   * Regression tests for the multi-warehouse stacked layout added in the
   * Stock-Aware Selection redesign. Before this change, the step seeded one
   * warehouse per item and drove everything through a single dropdown; the
   * new layout groups candidates by warehouse and honours the FEFO/FIFO rank
   * supplied by the backend via `warehouse_cards`.
   */
  describe('stacked warehouse card layout', () => {
    function makeCandidate(
      warehouseId: number,
      batchId: number,
      warehouseName: string,
      availableQty: string,
    ): AllocationCandidate {
      return {
        batch_id: batchId,
        inventory_id: warehouseId,
        item_id: 44,
        usable_qty: availableQty,
        reserved_qty: '0',
        available_qty: availableQty,
        source_type: 'ON_HAND',
        can_expire_flag: false,
        issuance_order: 'FIFO',
        warehouse_name: warehouseName,
        batch_no: `BT-${batchId}`,
      };
    }

    function makeWarehouseCard(
      warehouseId: number,
      warehouseName: string,
      rank: number,
    ): WarehouseAllocationCard {
      return {
        warehouse_id: warehouseId,
        warehouse_name: warehouseName,
        rank,
        issuance_order: 'FIFO',
        total_available: '100',
        suggested_qty: '0',
        batches: [],
      };
    }

    it('renders one warehouse card per unique inventory_id grouped from candidates', async () => {
      const item: AllocationItemGroup = {
        ...baseItem,
        candidates: [
          makeCandidate(9001, 1001, 'ODPEM Kingston', '20'),
          makeCandidate(9001, 1002, 'ODPEM Kingston', '10'),
          makeCandidate(9002, 2001, 'ODPEM Montego Bay', '15'),
        ],
      };

      await TestBed.configureTestingModule({
        imports: [FulfillmentItemDetailComponent],
      }).compileComponents();

      const fixture = TestBed.createComponent(FulfillmentItemDetailComponent);
      fixture.componentRef.setInput('item', item);
      fixture.componentRef.setInput('store', storeStub as never);
      fixture.detectChanges();

      const cards = fixture.nativeElement.querySelectorAll(
        '.warehouse-card',
      ) as NodeListOf<HTMLElement>;
      expect(cards.length).toBe(2);
      // Both Kingston batches land inside the first group.
      expect(cards[0].querySelectorAll('tbody tr').length).toBe(2);
      expect(cards[0].textContent).toContain('ODPEM Kingston');
      expect(cards[0].textContent).toContain('2 batches');
      // Montego Bay has one batch and renders as the second group.
      expect(cards[1].querySelectorAll('tbody tr').length).toBe(1);
      expect(cards[1].textContent).toContain('ODPEM Montego Bay');
    });

    it('orders the warehouse cards by the backend-supplied FEFO/FIFO rank', async () => {
      // Insertion order of candidates puts 9002 first, but the card rank says
      // 9001 is the primary. The stacked layout must follow the rank.
      const item: AllocationItemGroup = {
        ...baseItem,
        candidates: [
          makeCandidate(9002, 2001, 'ODPEM Montego Bay', '15'),
          makeCandidate(9001, 1001, 'ODPEM Kingston', '20'),
        ],
        warehouse_cards: [
          makeWarehouseCard(9001, 'ODPEM Kingston', 0),
          makeWarehouseCard(9002, 'ODPEM Montego Bay', 1),
        ],
      };

      await TestBed.configureTestingModule({
        imports: [FulfillmentItemDetailComponent],
      }).compileComponents();

      const fixture = TestBed.createComponent(FulfillmentItemDetailComponent);
      fixture.componentRef.setInput('item', item);
      fixture.componentRef.setInput('store', storeStub as never);
      fixture.detectChanges();

      const cardNames = Array.from(
        fixture.nativeElement.querySelectorAll(
          '.warehouse-card__name',
        ) as NodeListOf<HTMLElement>,
      ).map((el) => (el.textContent ?? '').trim());
      expect(cardNames).toEqual(['ODPEM Kingston', 'ODPEM Montego Bay']);
    });

    it('sends unranked warehouses to the end while preserving their insertion order', async () => {
      const item: AllocationItemGroup = {
        ...baseItem,
        candidates: [
          // Ranked card is listed second in the candidates array.
          makeCandidate(9004, 4001, 'ODPEM Portland', '8'),
          makeCandidate(9001, 1001, 'ODPEM Kingston', '20'),
          makeCandidate(9003, 3001, 'ODPEM St. Ann', '5'),
        ],
        warehouse_cards: [makeWarehouseCard(9001, 'ODPEM Kingston', 0)],
      };

      await TestBed.configureTestingModule({
        imports: [FulfillmentItemDetailComponent],
      }).compileComponents();

      const fixture = TestBed.createComponent(FulfillmentItemDetailComponent);
      fixture.componentRef.setInput('item', item);
      fixture.componentRef.setInput('store', storeStub as never);
      fixture.detectChanges();

      const cardNames = Array.from(
        fixture.nativeElement.querySelectorAll(
          '.warehouse-card__name',
        ) as NodeListOf<HTMLElement>,
      ).map((el) => (el.textContent ?? '').trim());
      // Ranked warehouse first, then the two unranked ones in first-seen order.
      expect(cardNames[0]).toBe('ODPEM Kingston');
      expect(cardNames.slice(1)).toEqual(['ODPEM Portland', 'ODPEM St. Ann']);
    });
  });

  /**
   * Regression tests for the "fully issued" UX guardrail. When a prior package
   * dispatch has already satisfied `reliefrqst_item.issue_qty >= request_qty`,
   * the backend now returns `fully_issued: true` and the Stock-Aware Selection
   * step must surface that state clearly (chip + disabled inputs + info banner)
   * instead of letting the operator hit a misleading "Over-Allocated" toast on
   * any new reservation attempt. See plan `jolly-zooming-flame.md`.
   */
  describe('fully_issued UX guardrail', () => {
    function makeFullyIssuedCandidate(): AllocationCandidate {
      return {
        batch_id: 258,
        inventory_id: 9001,
        item_id: 44,
        usable_qty: '60',
        reserved_qty: '0',
        available_qty: '60',
        source_type: 'ON_HAND',
        can_expire_flag: false,
        issuance_order: 'FIFO',
        warehouse_name: 'ODPEM Marcus Garvey',
        batch_no: 'HADR-2-58',
      };
    }

    function buildFullyIssuedItem(): AllocationItemGroup {
      return {
        ...baseItem,
        request_qty: '40',
        issue_qty: '40',
        remaining_qty: '0',
        remaining_shortfall_qty: '0',
        fully_issued: true,
        candidates: [makeFullyIssuedCandidate()],
      };
    }

    it('renders "Already Issued" in the Status metric card when fully_issued is true', async () => {
      await TestBed.configureTestingModule({
        imports: [FulfillmentItemDetailComponent],
      }).compileComponents();

      const fixture = TestBed.createComponent(FulfillmentItemDetailComponent);
      fixture.componentRef.setInput('item', buildFullyIssuedItem());
      fixture.componentRef.setInput('store', storeStub as never);
      fixture.detectChanges();

      const statusValue = fixture.nativeElement.querySelector(
        '.metric-card__value--status',
      ) as HTMLElement;
      expect(statusValue).toBeTruthy();
      expect(statusValue.getAttribute('data-status')).toBe('fully_issued');
      expect((statusValue.textContent ?? '').trim()).toBe('Already Issued');
    });

    it('disables every qty-input when the item is fully_issued', async () => {
      await TestBed.configureTestingModule({
        imports: [FulfillmentItemDetailComponent],
      }).compileComponents();

      const fixture = TestBed.createComponent(FulfillmentItemDetailComponent);
      const item = buildFullyIssuedItem();
      fixture.componentRef.setInput('item', item);
      fixture.componentRef.setInput('store', storeStub as never);
      fixture.detectChanges();
      await fixture.whenStable();
      fixture.detectChanges();

      const qtyInputs = fixture.nativeElement.querySelectorAll(
        'input.qty-input',
      ) as NodeListOf<HTMLInputElement>;
      expect(qtyInputs.length).toBeGreaterThan(0);
      qtyInputs.forEach((input) => {
        expect(input.disabled).toBeTrue();
      });
    });

    it('renders the already-issued info banner with the request/issue quantities', async () => {
      await TestBed.configureTestingModule({
        imports: [FulfillmentItemDetailComponent],
      }).compileComponents();

      const fixture = TestBed.createComponent(FulfillmentItemDetailComponent);
      fixture.componentRef.setInput('item', buildFullyIssuedItem());
      fixture.componentRef.setInput('store', storeStub as never);
      fixture.detectChanges();

      const banner = fixture.nativeElement.querySelector(
        '.detail__notice--info',
      ) as HTMLElement;
      expect(banner).toBeTruthy();
      const text = (banner.textContent ?? '').replace(/\s+/g, ' ').trim();
      expect(text).toContain('This item is already fully issued');
      expect(text).toContain('40');
      expect(text).toContain('Cancel the previous package');
    });

    it('does not render the info banner or disable inputs when fully_issued is false', async () => {
      const item: AllocationItemGroup = {
        ...baseItem,
        candidates: [makeFullyIssuedCandidate()],
      };

      await TestBed.configureTestingModule({
        imports: [FulfillmentItemDetailComponent],
      }).compileComponents();

      const fixture = TestBed.createComponent(FulfillmentItemDetailComponent);
      fixture.componentRef.setInput('item', item);
      fixture.componentRef.setInput('store', storeStub as never);
      fixture.detectChanges();

      expect(fixture.nativeElement.querySelector('.detail__notice--info')).toBeNull();
      const qtyInputs = fixture.nativeElement.querySelectorAll(
        'input.qty-input',
      ) as NodeListOf<HTMLInputElement>;
      expect(qtyInputs.length).toBeGreaterThan(0);
      qtyInputs.forEach((input) => {
        expect(input.disabled).toBeFalse();
      });
      const statusValue = fixture.nativeElement.querySelector(
        '.metric-card__value--status',
      ) as HTMLElement;
      expect((statusValue.textContent ?? '').trim()).not.toBe('Already Issued');
    });
  });
});
