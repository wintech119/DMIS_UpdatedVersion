import { BreakpointObserver } from '@angular/cdk/layout';
import { TestBed } from '@angular/core/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { of } from 'rxjs';

import { FulfillmentItemDetailComponent } from './fulfillment-item-detail.component';
import {
  AllocationCandidate,
  AllocationItemGroup,
  WarehouseAllocationCard,
} from '../../models/operations.model';

/**
 * Spec for FulfillmentItemDetailComponent under the FR05.06 redesign.
 *
 * Covers:
 *   - Ranked stack renders in backend rank order
 *   - Stack is de-duped with transient loaded warehouses appended
 *   - Add-next menu disabled when no alternates remain
 *   - Aggregate summary transitions across 4 states (draft / filled /
 *     compliant_partial / non_compliant)
 *   - Fully-issued guardrail still renders Already-Issued banner and disables
 *     inputs (regression from prior spec)
 *   - Stock-availability issue path renders the shared empty state
 */
describe('FulfillmentItemDetailComponent', () => {
  // Allocation state helpers — per-warehouse qty keyed by itemId|warehouseId.
  const qtyByItemWarehouse = new Map<string, number>();
  const makeKey = (itemId: number, warehouseId: number) => `${itemId}|${warehouseId}`;
  // Shared ref updated by render() so getItemFillStatus can mirror the real
  // service's logic (requires request_qty / remaining_qty / override_required
  // off the current item).
  let currentItemForFake: AllocationItemGroup | null = null;

  const storeStub = {
    getItemAvailabilityIssue: jasmine.createSpy('getItemAvailabilityIssue').and.returnValue(null),
    getItemValidationMessage: jasmine.createSpy('getItemValidationMessage').and.returnValue(null),
    isRuleBypassedForItem: jasmine.createSpy('isRuleBypassedForItem').and.returnValue(false),
    getSelectedTotalForItem: jasmine.createSpy('getSelectedTotalForItem').and.callFake((itemId: number) => {
      let total = 0;
      for (const [k, v] of qtyByItemWarehouse) {
        if (k.startsWith(`${itemId}|`)) total += v;
      }
      return total;
    }),
    getItemFillStatus: jasmine
      .createSpy('getItemFillStatus')
      .and.callFake(
        (
          itemId: number,
        ): 'draft' | 'filled' | 'compliant_partial' | 'non_compliant' => {
          const item = currentItemForFake;
          if (!item || item.item_id !== itemId) {
            return 'draft';
          }
          // Precedence matches operations-workspace-state.service.ts:
          // non_compliant > filled > compliant_partial > draft.
          if (
            item.override_required ||
            storeStub.isRuleBypassedForItem(itemId)
          ) {
            return 'non_compliant';
          }
          let total = 0;
          for (const [k, v] of qtyByItemWarehouse) {
            if (k.startsWith(`${itemId}|`)) total += v;
          }
          if (total <= 0) {
            return 'draft';
          }
          const requested =
            parseFloat(item.remaining_qty ?? item.request_qty ?? '0') || 0;
          if (total + 0.0001 >= requested) {
            return 'filled';
          }
          return 'compliant_partial';
        },
      ),
    getUncoveredQtyForItem: jasmine.createSpy('getUncoveredQtyForItem').and.returnValue(0),
    clearItemSelection: jasmine.createSpy('clearItemSelection'),
    getSelectedQtyForCandidate: jasmine.createSpy('getSelectedQtyForCandidate').and.returnValue(0),
    setCandidateQuantity: jasmine.createSpy('setCandidateQuantity'),
    setItemWarehouseQty: jasmine
      .createSpy('setItemWarehouseQty')
      .and.callFake((itemId: number, warehouseId: number, qty: number) => {
        qtyByItemWarehouse.set(makeKey(itemId, warehouseId), qty);
      }),
    getItemWarehouseAllocatedQty: jasmine
      .createSpy('getItemWarehouseAllocatedQty')
      .and.callFake((itemId: number, warehouseId: number) =>
        qtyByItemWarehouse.get(makeKey(itemId, warehouseId)) ?? 0,
      ),
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

  function makeWarehouseCard(
    warehouseId: number,
    warehouseName: string,
    rank: number,
    overrides: Partial<WarehouseAllocationCard> = {},
  ): WarehouseAllocationCard {
    return {
      warehouse_id: warehouseId,
      warehouse_name: warehouseName,
      rank,
      issuance_order: 'FIFO',
      total_available: '100',
      suggested_qty: '0',
      batches: [],
      ...overrides,
    };
  }

  function makeCandidate(warehouseId: number, batchId: number, warehouseName: string): AllocationCandidate {
    return {
      batch_id: batchId,
      inventory_id: warehouseId,
      item_id: 44,
      usable_qty: '50',
      reserved_qty: '0',
      available_qty: '50',
      source_type: 'ON_HAND',
      can_expire_flag: false,
      issuance_order: 'FIFO',
      warehouse_name: warehouseName,
      batch_no: `BT-${batchId}`,
    };
  }

  /**
   * Build a BreakpointObserver stub so the component's isNarrow signal stays
   * in desktop mode (matches === false) unless a test overrides it.
   */
  function breakpointStub(matches = false) {
    return {
      observe: () => of({ matches, breakpoints: { '(max-width: 519px)': matches } }),
      isMatched: () => matches,
    };
  }

  async function render(
    item: AllocationItemGroup,
    {
      loadedWarehousesByItem = {},
      uncoveredQty = 0,
      addingByItem = {},
      previewByItem = {},
      isNarrow = false,
    }: {
      loadedWarehousesByItem?: Record<number, number[]>;
      uncoveredQty?: number;
      addingByItem?: Record<number, boolean>;
      previewByItem?: Record<number, boolean>;
      isNarrow?: boolean;
    } = {},
  ) {
    currentItemForFake = item;
    storeStub.getUncoveredQtyForItem.and.returnValue(uncoveredQty);
    storeStub.loadedWarehousesByItem.and.returnValue(loadedWarehousesByItem);
    storeStub.addingWarehouseByItem.and.returnValue(addingByItem);
    storeStub.previewLoadingByItem.and.returnValue(previewByItem);

    await TestBed.configureTestingModule({
      imports: [FulfillmentItemDetailComponent, NoopAnimationsModule],
      providers: [{ provide: BreakpointObserver, useValue: breakpointStub(isNarrow) }],
    }).compileComponents();

    const fixture = TestBed.createComponent(FulfillmentItemDetailComponent);
    fixture.componentRef.setInput('item', item);
    fixture.componentRef.setInput('store', storeStub as never);
    fixture.detectChanges();
    return fixture;
  }

  beforeEach(() => {
    qtyByItemWarehouse.clear();
    currentItemForFake = null;
    storeStub.getItemAvailabilityIssue.calls.reset();
    storeStub.getItemAvailabilityIssue.and.returnValue(null);
    storeStub.isRuleBypassedForItem.calls.reset();
    storeStub.isRuleBypassedForItem.and.returnValue(false);
    storeStub.getItemFillStatus.calls.reset();
    storeStub.addItemWarehouse.calls.reset();
    storeStub.setItemWarehouseQty.calls.reset();
    storeStub.getItemWarehouseAllocatedQty.calls.reset();
    storeStub.loadedWarehousesByItem.and.returnValue({});
    storeStub.previewLoadingByItem.and.returnValue({});
    storeStub.addingWarehouseByItem.and.returnValue({});
    storeStub.getUncoveredQtyForItem.and.returnValue(0);
    storeStub.getSelectedTotalForItem.and.callFake((itemId: number) => {
      let total = 0;
      for (const [k, v] of qtyByItemWarehouse) {
        if (k.startsWith(`${itemId}|`)) total += v;
      }
      return total;
    });
  });

  describe('ranked stack', () => {
    it('renders cards in backend rank order from warehouse_cards', async () => {
      const item: AllocationItemGroup = {
        ...baseItem,
        warehouse_cards: [
          makeWarehouseCard(9001, 'ODPEM Kingston', 0),
          makeWarehouseCard(9002, 'ODPEM Montego Bay', 1),
          makeWarehouseCard(9003, 'ODPEM Portland', 2),
        ],
      };

      const fixture = await render(item);
      const names = Array.from(
        fixture.nativeElement.querySelectorAll(
          '.wh-card__name',
        ) as NodeListOf<HTMLElement>,
      ).map((el) => (el.textContent ?? '').trim());
      expect(names).toEqual(['ODPEM Kingston', 'ODPEM Montego Bay', 'ODPEM Portland']);
    });

    it('appends transient loaded warehouses that are not yet in warehouse_cards (de-duped)', async () => {
      const item: AllocationItemGroup = {
        ...baseItem,
        warehouse_cards: [makeWarehouseCard(9001, 'ODPEM Kingston', 0)],
        alternate_warehouses: [
          {
            warehouse_id: 9002,
            warehouse_name: 'ODPEM Montego Bay',
            available_qty: '25',
            suggested_qty: '10',
            can_fully_cover: false,
          },
          {
            warehouse_id: 9003,
            warehouse_name: 'ODPEM Portland',
            available_qty: '15',
            suggested_qty: '5',
            can_fully_cover: false,
          },
        ],
      };

      const fixture = await render(item, { loadedWarehousesByItem: { 44: [9002] } });
      const cards = fixture.nativeElement.querySelectorAll(
        'app-warehouse-allocation-card',
      );
      // Kingston (backend) + Montego Bay (transient, loaded) = 2 cards; Portland stays in the add menu.
      expect(cards.length).toBe(2);
      const names = Array.from(
        fixture.nativeElement.querySelectorAll(
          '.wh-card__name',
        ) as NodeListOf<HTMLElement>,
      ).map((el) => (el.textContent ?? '').trim());
      expect(names).toEqual(['ODPEM Kingston', 'ODPEM Montego Bay']);
    });
  });

  describe('add-next affordance', () => {
    it('disables the Add-next button when no alternate warehouses remain', async () => {
      const item: AllocationItemGroup = {
        ...baseItem,
        warehouse_cards: [makeWarehouseCard(9001, 'ODPEM Kingston', 0)],
        alternate_warehouses: [],
      };

      const fixture = await render(item);
      const button = fixture.nativeElement.querySelector(
        '.detail__add-row button',
      ) as HTMLButtonElement;
      expect(button).toBeTruthy();
      expect(button.disabled).toBeTrue();
    });

    it('shows the mat-menu trigger on desktop viewports', async () => {
      const item: AllocationItemGroup = {
        ...baseItem,
        warehouse_cards: [makeWarehouseCard(9001, 'ODPEM Kingston', 0)],
        alternate_warehouses: [
          {
            warehouse_id: 9002,
            warehouse_name: 'ODPEM Montego Bay',
            available_qty: '20',
            suggested_qty: '10',
            can_fully_cover: false,
          },
        ],
      };

      const fixture = await render(item, { isNarrow: false });
      const trigger = fixture.nativeElement.querySelector(
        '.detail__add-row button',
      ) as HTMLButtonElement;
      expect(trigger).toBeTruthy();
      expect(trigger.disabled).toBeFalse();
      // In desktop mode the mat-menu trigger is wired; on narrow it's a plain
      // click-handler. We verify the label is consistent across both modes.
      expect(trigger.textContent).toContain('Add next warehouse');
      expect(trigger.textContent).toContain('1 available');
    });

    it('uses the bottom-sheet path on narrow viewports (<520px)', async () => {
      const item: AllocationItemGroup = {
        ...baseItem,
        warehouse_cards: [makeWarehouseCard(9001, 'ODPEM Kingston', 0)],
        alternate_warehouses: [
          {
            warehouse_id: 9002,
            warehouse_name: 'ODPEM Montego Bay',
            available_qty: '20',
            suggested_qty: '10',
            can_fully_cover: false,
          },
        ],
      };

      const fixture = await render(item, { isNarrow: true });
      // In narrow mode the Add-next button is a plain button (no matMenuTriggerFor).
      const trigger = fixture.nativeElement.querySelector(
        '.detail__add-row button',
      ) as HTMLButtonElement;
      expect(trigger).toBeTruthy();
      expect(trigger.getAttribute('aria-haspopup')).not.toBe('menu');
    });
  });

  describe('aggregate summary (4 states)', () => {
    function withCards(): AllocationItemGroup {
      return {
        ...baseItem,
        request_qty: '42',
        remaining_qty: '42',
        warehouse_cards: [
          makeWarehouseCard(9001, 'ODPEM Kingston', 0, { total_available: '50', suggested_qty: '42' }),
          makeWarehouseCard(9002, 'ODPEM Montego Bay', 1, { total_available: '30', suggested_qty: '0' }),
        ],
      };
    }

    it('draft — nothing reserved', async () => {
      const fixture = await render(withCards());
      const summary = fixture.nativeElement.querySelector('.detail__summary') as HTMLElement;
      expect(summary.getAttribute('data-state')).toBe('draft');
      expect((summary.textContent ?? '').toLowerCase()).toContain('nothing allocated');
    });

    it('filled — reservingQty >= remainingQty across ranked stack', async () => {
      qtyByItemWarehouse.set(makeKey(44, 9001), 42);
      const fixture = await render(withCards());
      const summary = fixture.nativeElement.querySelector('.detail__summary') as HTMLElement;
      expect(summary.getAttribute('data-state')).toBe('filled');
      expect((summary.textContent ?? '').toLowerCase()).toContain('fully covered');
    });

    it('compliant_partial — partial qty, no override flags', async () => {
      qtyByItemWarehouse.set(makeKey(44, 9001), 20);
      qtyByItemWarehouse.set(makeKey(44, 9002), 5);
      const fixture = await render(withCards());
      const summary = fixture.nativeElement.querySelector('.detail__summary') as HTMLElement;
      expect(summary.getAttribute('data-state')).toBe('compliant_partial');
      expect((summary.textContent ?? '').toLowerCase()).toContain('compliant partial');
    });

    it('non_compliant — override flagged via item.override_required', async () => {
      const fixture = await render({ ...withCards(), override_required: true });
      const summary = fixture.nativeElement.querySelector('.detail__summary') as HTMLElement;
      expect(summary.getAttribute('data-state')).toBe('non_compliant');
      expect(summary.getAttribute('aria-live')).toBe('polite');
    });

    it('non_compliant — local override-risk heuristic when higher-rank qty exists and a rank-0 empty', async () => {
      // Allocate to rank 1 only, leaving rank 0 empty — a classic override risk.
      qtyByItemWarehouse.set(makeKey(44, 9002), 10);
      const fixture = await render(withCards());
      const summary = fixture.nativeElement.querySelector('.detail__summary') as HTMLElement;
      expect(summary.getAttribute('data-state')).toBe('non_compliant');
    });
  });

  describe('regressions', () => {
    it('renders the shared warehouse availability state when the selected item has no candidates', async () => {
      storeStub.getItemAvailabilityIssue.and.returnValue({ kind: 'no-candidates', scope: 'item' });

      const fixture = await render(baseItem);
      const text = fixture.nativeElement.textContent.replace(/\s+/g, ' ').trim();
      expect(text).toContain('Portable Water Container is not stocked in an available warehouse');
      expect(fixture.nativeElement.querySelector('.detail__stack')).toBeNull();
    });

    it('renders the already-issued info banner and read-only cards when fully_issued=true', async () => {
      const item: AllocationItemGroup = {
        ...baseItem,
        request_qty: '40',
        issue_qty: '40',
        remaining_qty: '0',
        remaining_shortfall_qty: '0',
        fully_issued: true,
        candidates: [makeCandidate(9001, 258, 'ODPEM Marcus Garvey')],
        warehouse_cards: [makeWarehouseCard(9001, 'ODPEM Marcus Garvey', 0)],
      };

      const fixture = await render(item);

      const banner = fixture.nativeElement.querySelector('.detail__notice--info') as HTMLElement;
      expect(banner).toBeTruthy();
      const text = (banner.textContent ?? '').replace(/\s+/g, ' ').trim();
      expect(text).toContain('This item is already fully issued');
      expect(text).toContain('40');

      const qtyInputs = fixture.nativeElement.querySelectorAll(
        'app-warehouse-allocation-card input[matInput]',
      ) as NodeListOf<HTMLInputElement>;
      expect(qtyInputs.length).toBeGreaterThan(0);
      qtyInputs.forEach((input) => expect(input.disabled).toBeTrue());

      const statusValue = fixture.nativeElement.querySelector(
        '.metric-card__value--status',
      ) as HTMLElement;
      expect(statusValue.getAttribute('data-status')).toBe('fully_issued');
      expect((statusValue.textContent ?? '').trim()).toBe('Already Issued');
    });
  });
});
