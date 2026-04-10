import { ComponentFixture, TestBed } from '@angular/core/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';

import { WarehouseAllocationCardComponent } from './warehouse-allocation-card.component';
import { WarehouseAllocationCard } from '../../models/operations.model';

/**
 * Focused spec for the WarehouseAllocationCardComponent presentational tile.
 *
 * Covers the visual contract documented in generation.tsx Section 4c:
 *   - Qty input bounds (clamped to 0 ≤ qty ≤ warehouse.total_available)
 *   - Remove emission carries the warehouse_id
 *   - A11y landmark: role="group" with a warehouse-derived aria-label
 *   - Read-only mode hides the remove button and disables the input
 *   - Fill status transitions (EMPTY → PARTIAL → FILLED)
 *   - Batch table toggles and renders the server-ranked batches in order
 */
describe('WarehouseAllocationCardComponent', () => {
  function buildCard(overrides: Partial<WarehouseAllocationCard> = {}): WarehouseAllocationCard {
    return {
      warehouse_id: 9001,
      warehouse_name: 'ODPEM Kingston',
      rank: 0,
      issuance_order: 'FEFO',
      total_available: '300',
      suggested_qty: '300',
      batches: [
        {
          batch_id: 7001,
          inventory_id: 9001,
          batch_no: 'BT-001',
          batch_date: '2026-01-02',
          expiry_date: '2026-12-31',
          available_qty: '200',
          usable_qty: '200',
          reserved_qty: '0',
          uom_code: 'EA',
          source_type: 'ON_HAND',
          source_record_id: null,
        },
        {
          batch_id: 7002,
          inventory_id: 9001,
          batch_no: 'BT-002',
          batch_date: '2026-01-05',
          expiry_date: '2027-06-30',
          available_qty: '100',
          usable_qty: '100',
          reserved_qty: '0',
          uom_code: 'EA',
          source_type: 'ON_HAND',
          source_record_id: null,
        },
      ],
      ...overrides,
    };
  }

  async function render(inputs: {
    warehouse: WarehouseAllocationCard;
    itemRequestedQty?: string;
    allocatedQty?: number;
    canRemove?: boolean;
    readOnly?: boolean;
    itemShortfallQty?: string;
  }): Promise<ComponentFixture<WarehouseAllocationCardComponent>> {
    await TestBed.configureTestingModule({
      imports: [WarehouseAllocationCardComponent, NoopAnimationsModule],
    }).compileComponents();

    const fixture = TestBed.createComponent(WarehouseAllocationCardComponent);
    fixture.componentRef.setInput('warehouse', inputs.warehouse);
    fixture.componentRef.setInput('itemRequestedQty', inputs.itemRequestedQty ?? '400');
    fixture.componentRef.setInput('allocatedQty', inputs.allocatedQty ?? 0);
    fixture.componentRef.setInput('canRemove', inputs.canRemove ?? true);
    fixture.componentRef.setInput('readOnly', inputs.readOnly ?? false);
    fixture.componentRef.setInput('itemShortfallQty', inputs.itemShortfallQty ?? '400');
    fixture.detectChanges();
    return fixture;
  }

  it('renders the warehouse name, rank label, and available badge', async () => {
    const fixture = await render({ warehouse: buildCard() });
    const host: HTMLElement = fixture.nativeElement;

    expect(host.querySelector('.wh-card__name')?.textContent).toContain('ODPEM Kingston');
    expect(host.querySelector('.wh-card__rank')?.textContent).toContain('Primary FEFO');
    expect(host.querySelector('.wh-card__available-badge')?.textContent).toContain('300');
  });

  it('labels non-primary cards with the FIFO/FEFO rank offset', async () => {
    const fixture = await render({
      warehouse: buildCard({ warehouse_id: 9002, rank: 2, issuance_order: 'FIFO' }),
    });

    const rankText = fixture.nativeElement.querySelector('.wh-card__rank')?.textContent ?? '';
    expect(rankText).toContain('+2 FIFO');
  });

  it('exposes the a11y landmark as role="group" with a derived aria-label', async () => {
    const fixture = await render({
      warehouse: buildCard(),
      allocatedQty: 100,
    });

    const group = fixture.nativeElement.querySelector('.wh-card') as HTMLElement;
    expect(group.getAttribute('role')).toBe('group');
    const ariaLabel = group.getAttribute('aria-label') ?? '';
    expect(ariaLabel).toContain('ODPEM Kingston');
    expect(ariaLabel).toContain('allocating 100');
    expect(ariaLabel).toContain('300');
    expect(ariaLabel).toContain('FEFO rank 1');
  });

  it('clamps qty input at the warehouse available max and emits the clamped numeric value', async () => {
    const fixture = await render({ warehouse: buildCard() });
    const emitted: number[] = [];
    fixture.componentInstance.qtyChange.subscribe((value) => emitted.push(value));

    const input = fixture.nativeElement.querySelector('input[matInput]') as HTMLInputElement;
    input.value = '999';
    input.dispatchEvent(new Event('input'));

    expect(emitted).toEqual([300]);
    expect(input.value).toBe('300');
  });

  it('clamps qty input to zero when the warehouse has no stock available', async () => {
    const fixture = await render({
      warehouse: buildCard({ total_available: '0', suggested_qty: '0' }),
    });
    const emitted: number[] = [];
    fixture.componentInstance.qtyChange.subscribe((value) => emitted.push(value));

    const input = fixture.nativeElement.querySelector('input[matInput]') as HTMLInputElement;
    input.value = '7';
    input.dispatchEvent(new Event('input'));

    expect(emitted).toEqual([0]);
    expect(input.value).toBe('0');
  });

  it('clamps negative qty input to zero and emits 0', async () => {
    const fixture = await render({ warehouse: buildCard() });
    const emitted: number[] = [];
    fixture.componentInstance.qtyChange.subscribe((value) => emitted.push(value));

    const input = fixture.nativeElement.querySelector('input[matInput]') as HTMLInputElement;
    input.value = '-12';
    input.dispatchEvent(new Event('input'));

    expect(emitted).toEqual([0]);
    expect(input.value).toBe('0');
  });

  it('does not emit qtyChange when the input value is non-finite', async () => {
    const fixture = await render({ warehouse: buildCard() });
    const emitted: number[] = [];
    fixture.componentInstance.qtyChange.subscribe((value) => emitted.push(value));

    const input = fixture.nativeElement.querySelector('input[matInput]') as HTMLInputElement;
    // Simulate a non-numeric input by clearing .value then dispatching — Number('') === 0
    // which IS finite, so force a true non-finite path by calling onQtyInput manually.
    fixture.componentInstance.onQtyInput({ target: { value: 'abc' } } as unknown as Event);
    expect(emitted).toEqual([]);
  });

  it('emits removeCard with the warehouse_id when the remove button is clicked', async () => {
    const fixture = await render({
      warehouse: buildCard({ warehouse_id: 9007 }),
      canRemove: true,
    });
    const emitted: number[] = [];
    fixture.componentInstance.removeCard.subscribe((id) => emitted.push(id));

    const removeBtn = fixture.nativeElement.querySelector(
      '.wh-card__remove',
    ) as HTMLButtonElement;
    expect(removeBtn).toBeTruthy();
    removeBtn.click();

    expect(emitted).toEqual([9007]);
  });

  it('hides the remove button when canRemove is false', async () => {
    const fixture = await render({
      warehouse: buildCard(),
      canRemove: false,
    });

    expect(fixture.nativeElement.querySelector('.wh-card__remove')).toBeNull();
  });

  it('hides the remove button and disables the qty input in read-only mode', async () => {
    const fixture = await render({
      warehouse: buildCard(),
      readOnly: true,
      canRemove: true,
    });

    expect(fixture.nativeElement.querySelector('.wh-card__remove')).toBeNull();
    const input = fixture.nativeElement.querySelector('input[matInput]') as HTMLInputElement;
    expect(input.disabled).toBeTrue();
  });

  it('allows fractional allocations in the qty input', async () => {
    const fixture = await render({ warehouse: buildCard() });
    const input = fixture.nativeElement.querySelector('input[matInput]') as HTMLInputElement;

    expect(input.getAttribute('step')).toBe('0.0001');
  });

  it('reflects EMPTY status when nothing has been allocated', async () => {
    const fixture = await render({
      warehouse: buildCard(),
      allocatedQty: 0,
    });
    const wrapper = fixture.nativeElement.querySelector('.wh-card') as HTMLElement;
    expect(wrapper.getAttribute('data-fill-status')).toBe('EMPTY');
    expect(fixture.nativeElement.textContent).toContain('Empty');
  });

  it('reflects PARTIAL status when allocated < requested and < max', async () => {
    const fixture = await render({
      warehouse: buildCard(),
      itemRequestedQty: '400',
      allocatedQty: 100,
    });
    const wrapper = fixture.nativeElement.querySelector('.wh-card') as HTMLElement;
    expect(wrapper.getAttribute('data-fill-status')).toBe('PARTIAL');
    expect(fixture.nativeElement.textContent).toContain('Partial');
  });

  it('reflects FILLED status when allocated reaches the warehouse cap', async () => {
    const fixture = await render({
      warehouse: buildCard(),
      itemRequestedQty: '400',
      allocatedQty: 300,
    });
    const wrapper = fixture.nativeElement.querySelector('.wh-card') as HTMLElement;
    expect(wrapper.getAttribute('data-fill-status')).toBe('FILLED');
    expect(fixture.nativeElement.textContent).toContain('Filled');
  });

  it('renders the collapsed batch toggle and expands into a grid of batches in the server order', async () => {
    const fixture = await render({ warehouse: buildCard() });
    const host: HTMLElement = fixture.nativeElement;

    // Collapsed by default — the toggle is visible, the table is not rendered.
    expect(host.querySelector('.wh-batch-table')).toBeNull();
    const toggle = host.querySelector('.wh-card__toggle') as HTMLButtonElement;
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    expect(toggle.textContent).toContain('View 2 batches');

    toggle.click();
    fixture.detectChanges();

    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    const rows = host.querySelectorAll('.wh-batch-table tbody tr');
    expect(rows.length).toBe(2);
    expect(rows[0].textContent).toContain('BT-001');
    expect(rows[1].textContent).toContain('BT-002');
  });

  it('hides the batch toggle when there are no batches to show', async () => {
    const fixture = await render({
      warehouse: buildCard({ batches: [] }),
    });
    expect(fixture.nativeElement.querySelector('.wh-card__toggle')).toBeNull();
  });

  it('flags expiring-soon batches within the 14-day window', async () => {
    const today = new Date();
    const soon = new Date(today.getTime() + 5 * 24 * 60 * 60 * 1000);
    const far = new Date(today.getTime() + 365 * 24 * 60 * 60 * 1000);

    const fixture = await render({
      warehouse: buildCard({
        batches: [
          {
            batch_id: 8001,
            inventory_id: 9001,
            batch_no: 'EXP-SOON',
            batch_date: '2026-01-01',
            expiry_date: soon.toISOString().slice(0, 10),
            available_qty: '25',
            usable_qty: '25',
            reserved_qty: '0',
            uom_code: 'EA',
            source_type: 'ON_HAND',
            source_record_id: null,
          },
          {
            batch_id: 8002,
            inventory_id: 9001,
            batch_no: 'EXP-FAR',
            batch_date: '2026-01-01',
            expiry_date: far.toISOString().slice(0, 10),
            available_qty: '100',
            usable_qty: '100',
            reserved_qty: '0',
            uom_code: 'EA',
            source_type: 'ON_HAND',
            source_record_id: null,
          },
        ],
      }),
    });

    (fixture.nativeElement.querySelector('.wh-card__toggle') as HTMLButtonElement).click();
    fixture.detectChanges();

    const rows = fixture.nativeElement.querySelectorAll('.wh-batch-table tbody tr');
    expect((rows[0] as HTMLElement).classList).toContain('wh-batch-row--expiring');
    expect((rows[1] as HTMLElement).classList).not.toContain('wh-batch-row--expiring');
  });

  it('does not flag already-expired batches as expiring soon', async () => {
    const yesterday = new Date(Date.now() - 24 * 60 * 60 * 1000);

    const fixture = await render({
      warehouse: buildCard({
        batches: [
          {
            batch_id: 8003,
            inventory_id: 9001,
            batch_no: 'EXPIRED',
            batch_date: '2026-01-01',
            expiry_date: yesterday.toISOString().slice(0, 10),
            available_qty: '25',
            usable_qty: '25',
            reserved_qty: '0',
            uom_code: 'EA',
            source_type: 'ON_HAND',
            source_record_id: null,
          },
        ],
      }),
    });

    (fixture.nativeElement.querySelector('.wh-card__toggle') as HTMLButtonElement).click();
    fixture.detectChanges();

    const row = fixture.nativeElement.querySelector('.wh-batch-table tbody tr') as HTMLElement;
    expect(row.classList).not.toContain('wh-batch-row--expiring');
  });

  it('gives the qty input a stable hint id per warehouse for screen-reader association', async () => {
    const fixture = await render({
      warehouse: buildCard({ warehouse_id: 9042 }),
    });
    const input = fixture.nativeElement.querySelector('input[matInput]') as HTMLInputElement;
    const hint = fixture.nativeElement.querySelector('mat-hint') as HTMLElement;
    expect(input.getAttribute('aria-describedby')).toBe('wh-qty-hint-9042');
    expect(hint.getAttribute('id')).toBe('wh-qty-hint-9042');
  });
});
