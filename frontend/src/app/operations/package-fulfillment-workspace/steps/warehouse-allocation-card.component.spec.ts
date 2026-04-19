import { ComponentFixture, TestBed } from '@angular/core/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';

import { WarehouseAllocationCardComponent } from './warehouse-allocation-card.component';
import { WarehouseAllocationCard } from '../../models/operations.model';

/**
 * Focused spec for the WarehouseAllocationCardComponent presentational tile
 * under the FR05.06 Item Allocation Redesign contract.
 *
 * Covers:
 *   - Rank pill copy (Primary FEFO/FIFO vs +N FEFO/FIFO)
 *   - 6-rule reason line (rank 0 FEFO/FIFO/fallback, rank > 0 shortfall/additional,
 *     non-ON_HAND source suffix)
 *   - Qty validation: integer-only regex, non-negative, bounded by
 *     min(allocatable_available_qty || total_available, remainingQtyForItem)
 *   - Use max clamps to remainingQtyForItem; Clear emits 0
 *   - isOverrideRisk toggles the non-compliant data attribute on the status
 *     footer only when allocatedQty === 0
 *   - Remove emission carries warehouse_id
 *   - A11y: role="group", derived aria-label includes reason-line
 *   - Batch disclosure toggles aria-expanded and renders batches in server order
 *   - Expiring-soon heuristic (14-day window)
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
    remainingQtyForItem?: number;
    isOverrideRisk?: boolean;
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
    fixture.componentRef.setInput('remainingQtyForItem', inputs.remainingQtyForItem ?? 400);
    fixture.componentRef.setInput('isOverrideRisk', inputs.isOverrideRisk ?? false);
    fixture.detectChanges();
    return fixture;
  }

  it('renders the warehouse name and primary-rank pill for a rank-0 FEFO card', async () => {
    const fixture = await render({ warehouse: buildCard() });
    const host: HTMLElement = fixture.nativeElement;

    expect(host.querySelector('.wh-card__name')?.textContent).toContain('ODPEM Kingston');
    expect(host.querySelector('.wh-card__rank')?.textContent).toContain('Primary FEFO');
    expect(host.querySelector('.wh-card__available-badge')?.textContent).toContain('300');
  });

  it('labels non-primary cards with the +N FIFO offset', async () => {
    const fixture = await render({
      warehouse: buildCard({ warehouse_id: 9002, rank: 2, issuance_order: 'FIFO' }),
    });

    const rankText = fixture.nativeElement.querySelector('.wh-card__rank')?.textContent ?? '';
    expect(rankText).toContain('+2 FIFO');
  });

  describe('reason line (6 rules)', () => {
    it('rank 0 + FEFO + top_expiry_date renders earliest-expiring copy', async () => {
      const fixture = await render({
        warehouse: buildCard({
          ranking_context: {
            basis: 'FEFO',
            top_batch_id: 7001,
            top_batch_no: 'BT-001',
            top_batch_date: null,
            top_expiry_date: '2026-12-31',
          },
        }),
      });

      const reason = fixture.nativeElement.querySelector('.wh-card__reason-text')?.textContent ?? '';
      expect(reason).toContain('Ranked first');
      expect(reason).toContain('earliest expiring');
      expect(reason).toContain('FEFO');
    });

    it('rank 0 + FIFO + top_batch_date renders oldest-stock copy', async () => {
      const fixture = await render({
        warehouse: buildCard({
          issuance_order: 'FIFO',
          ranking_context: {
            basis: 'FIFO',
            top_batch_id: 7001,
            top_batch_no: 'BT-001',
            top_batch_date: '2026-01-02',
            top_expiry_date: null,
          },
        }),
      });

      const reason = fixture.nativeElement.querySelector('.wh-card__reason-text')?.textContent ?? '';
      expect(reason).toContain('Ranked first');
      expect(reason).toContain('oldest stock');
      expect(reason).toContain('FIFO');
    });

    it('rank 0 without ranking_context falls back to generic Primary copy', async () => {
      const fixture = await render({
        warehouse: buildCard({ issuance_order: 'FIFO', ranking_context: null }),
      });

      const reason = fixture.nativeElement.querySelector('.wh-card__reason-text')?.textContent ?? '';
      expect(reason).toContain('Primary source');
      expect(reason).toContain('FIFO');
    });

    it('rank > 0 with positive shortfall renders shortfall-cover copy', async () => {
      const fixture = await render({
        warehouse: buildCard({ rank: 1, suggested_qty: '25' }),
        itemShortfallQty: '50',
      });

      const reason = fixture.nativeElement.querySelector('.wh-card__reason-text')?.textContent ?? '';
      expect(reason).toContain('Ranked 2');
      expect(reason).toContain('25');
      expect(reason).toContain('50');
    });

    it('rank > 0 with zero shortfall renders additional-stock copy', async () => {
      const fixture = await render({
        warehouse: buildCard({ rank: 1, issuance_order: 'FIFO' }),
        itemShortfallQty: '0',
      });

      const reason = fixture.nativeElement.querySelector('.wh-card__reason-text')?.textContent ?? '';
      expect(reason).toContain('Ranked 2');
      expect(reason).toContain('additional available stock');
      expect(reason).toContain('FIFO');
    });

    it('non-ON_HAND source batches append a source-suffix to the reason line', async () => {
      const fixture = await render({
        warehouse: buildCard({
          batches: [
            {
              batch_id: 7101,
              inventory_id: 9001,
              batch_no: 'TR-1',
              batch_date: '2026-01-01',
              expiry_date: null,
              available_qty: '50',
              usable_qty: '50',
              reserved_qty: '0',
              uom_code: 'EA',
              source_type: 'INBOUND_TRANSFER',
              source_record_id: 12,
            },
          ],
        }),
      });

      const reason = fixture.nativeElement.querySelector('.wh-card__reason-text')?.textContent ?? '';
      expect(reason).toContain('includes INBOUND_TRANSFER source');
    });
  });

  describe('qty input validation', () => {
    it('caps at allocatable_available_qty when provided (below total_available)', async () => {
      const fixture = await render({
        warehouse: buildCard({
          total_available: '300',
          allocatable_available_qty: '75',
        }),
        remainingQtyForItem: 400,
      });
      const emitted: number[] = [];
      fixture.componentInstance.qtyChange.subscribe((v) => emitted.push(v));

      const input = fixture.nativeElement.querySelector('input.wh-card__qty-input') as HTMLInputElement;
      input.value = '100';
      input.dispatchEvent(new Event('input'));

      // No emission because 100 > 75 (allocatable cap) — the card surfaces an error.
      expect(emitted).toEqual([]);
      expect(fixture.componentInstance.qtyInvalid()).toBeTrue();
      expect(fixture.componentInstance.qtyErrorMessage()).toContain('75');
    });

    it('falls back to total_available when allocatable_available_qty is absent', async () => {
      const fixture = await render({
        warehouse: buildCard({ total_available: '300' }),
        remainingQtyForItem: 400,
      });
      const emitted: number[] = [];
      fixture.componentInstance.qtyChange.subscribe((v) => emitted.push(v));

      const input = fixture.nativeElement.querySelector('input.wh-card__qty-input') as HTMLInputElement;
      input.value = '250';
      input.dispatchEvent(new Event('input'));

      expect(emitted).toEqual([250]);
    });

    it('rejects negative values without emitting', async () => {
      const fixture = await render({ warehouse: buildCard() });
      const emitted: number[] = [];
      fixture.componentInstance.qtyChange.subscribe((v) => emitted.push(v));

      const input = fixture.nativeElement.querySelector('input.wh-card__qty-input') as HTMLInputElement;
      input.value = '-5';
      input.dispatchEvent(new Event('input'));

      expect(emitted).toEqual([]);
      expect(fixture.componentInstance.qtyInvalid()).toBeTrue();
    });

    it('rejects non-integer / decimal values without emitting', async () => {
      const fixture = await render({ warehouse: buildCard() });
      const emitted: number[] = [];
      fixture.componentInstance.qtyChange.subscribe((v) => emitted.push(v));

      const input = fixture.nativeElement.querySelector('input.wh-card__qty-input') as HTMLInputElement;
      input.value = '12.5';
      input.dispatchEvent(new Event('input'));

      expect(emitted).toEqual([]);
      expect(fixture.componentInstance.qtyInvalid()).toBeTrue();
      expect(fixture.componentInstance.qtyErrorMessage()).toContain('whole number');
    });

    it('rejects values over the cap without emitting', async () => {
      const fixture = await render({
        warehouse: buildCard({ total_available: '300' }),
        remainingQtyForItem: 300,
      });
      const emitted: number[] = [];
      fixture.componentInstance.qtyChange.subscribe((v) => emitted.push(v));

      const input = fixture.nativeElement.querySelector('input.wh-card__qty-input') as HTMLInputElement;
      input.value = '500';
      input.dispatchEvent(new Event('input'));

      expect(emitted).toEqual([]);
      expect(fixture.componentInstance.qtyInvalid()).toBeTrue();
    });

    it('uses integer step for numeric input', async () => {
      const fixture = await render({ warehouse: buildCard() });
      const input = fixture.nativeElement.querySelector('input.wh-card__qty-input') as HTMLInputElement;
      expect(input.getAttribute('step')).toBe('1');
      expect(input.getAttribute('inputmode')).toBe('numeric');
    });
  });

  describe('Use max and Clear buttons', () => {
    it('Use max emits min(allocatable cap, remainingQtyForItem) floored', async () => {
      const fixture = await render({
        warehouse: buildCard({ total_available: '300' }),
        remainingQtyForItem: 120,
      });
      const emitted: number[] = [];
      fixture.componentInstance.qtyChange.subscribe((v) => emitted.push(v));

      // Locate Use max by its stable aria-label.
      const useMaxBtn = Array.from(
        fixture.nativeElement.querySelectorAll('.wh-card__qty-btn') as NodeListOf<HTMLButtonElement>,
      ).find((b) => (b.textContent ?? '').trim().startsWith('Use max'));
      expect(useMaxBtn).toBeTruthy();
      useMaxBtn!.click();

      expect(emitted).toEqual([120]);
    });

    it('Clear emits 0 regardless of current allocation', async () => {
      const fixture = await render({
        warehouse: buildCard(),
        allocatedQty: 75,
      });
      const emitted: number[] = [];
      fixture.componentInstance.qtyChange.subscribe((v) => emitted.push(v));

      const clearBtn = Array.from(
        fixture.nativeElement.querySelectorAll('.wh-card__qty-btn') as NodeListOf<HTMLButtonElement>,
      ).find((b) => (b.textContent ?? '').trim().startsWith('Clear'));
      expect(clearBtn).toBeTruthy();
      clearBtn!.click();

      expect(emitted).toEqual([0]);
    });
  });

  describe('override-risk indicator', () => {
    it('sets data-non-compliant on the status pill when risk is active and qty is 0', async () => {
      const fixture = await render({
        warehouse: buildCard(),
        allocatedQty: 0,
        isOverrideRisk: true,
      });

      const statusPill = fixture.nativeElement.querySelector(
        '.wh-card__status-pill',
      ) as HTMLElement;
      expect(statusPill.getAttribute('data-non-compliant')).toBe('true');
      expect(fixture.nativeElement.textContent).toContain('Override risk');
    });

    it('does NOT flag non-compliant when allocatedQty > 0 even if isOverrideRisk is true', async () => {
      const fixture = await render({
        warehouse: buildCard(),
        allocatedQty: 10,
        isOverrideRisk: true,
      });

      const statusPill = fixture.nativeElement.querySelector(
        '.wh-card__status-pill',
      ) as HTMLElement;
      expect(statusPill.getAttribute('data-non-compliant')).toBeNull();
    });
  });

  it('exposes a kebab trigger wired to matMenuTriggerFor when not readOnly', async () => {
    const fixture = await render({
      warehouse: buildCard({ warehouse_id: 9007 }),
      canRemove: true,
    });
    const trigger = fixture.nativeElement.querySelector(
      '.wh-card__menu-trigger',
    ) as HTMLButtonElement | null;
    expect(trigger).not.toBeNull();
    // Angular Material sets aria-haspopup on the mat-menu trigger host element.
    expect(trigger!.getAttribute('aria-haspopup')).toBe('menu');
  });

  it('onRemoveClick() emits removeCard with the warehouse_id', async () => {
    const fixture = await render({
      warehouse: buildCard({ warehouse_id: 9007 }),
      canRemove: true,
    });
    const emitted: number[] = [];
    fixture.componentInstance.removeCard.subscribe((id) => emitted.push(id));

    // Invoke the menu-wired handler directly — the template bindings
    // ((click)="onRemoveClick()") are covered by Angular's compiler.
    fixture.componentInstance.onRemoveClick();
    expect(emitted).toEqual([9007]);
  });

  it('exposes canRemove() === false to the template so the Remove menu item can disable', async () => {
    const fixture = await render({ warehouse: buildCard(), canRemove: false });
    expect(fixture.componentInstance.canRemove()).toBeFalse();
    // The kebab trigger is still visible — only the Remove menu item disables.
    const trigger = fixture.nativeElement.querySelector(
      '.wh-card__menu-trigger',
    ) as HTMLButtonElement | null;
    expect(trigger).not.toBeNull();
  });

  it('exposes a plain "Remove warehouse" aria-label when canRemove is true', async () => {
    const fixture = await render({ warehouse: buildCard(), canRemove: true });
    expect(fixture.componentInstance.removeMenuAriaLabel()).toBe('Remove warehouse');
  });

  it('explains *why* Remove is disabled via aria-label on the primary (rank-0) card', async () => {
    const fixture = await render({ warehouse: buildCard(), canRemove: false });
    const label = fixture.componentInstance.removeMenuAriaLabel();
    expect(label).toContain('unavailable');
    expect(label).toContain('primary');
  });

  it('hides the kebab menu trigger and disables the qty input in read-only mode', async () => {
    const fixture = await render({
      warehouse: buildCard(),
      readOnly: true,
      canRemove: true,
    });

    expect(fixture.nativeElement.querySelector('.wh-card__menu-trigger')).toBeNull();
    const input = fixture.nativeElement.querySelector('input.wh-card__qty-input') as HTMLInputElement;
    expect(input.disabled).toBeTrue();
  });

  it('exposes role="group" with an aria-label that includes the reason line', async () => {
    const fixture = await render({
      warehouse: buildCard({
        ranking_context: {
          basis: 'FEFO',
          top_batch_id: 7001,
          top_batch_no: 'BT-001',
          top_batch_date: null,
          top_expiry_date: '2026-12-31',
        },
      }),
      allocatedQty: 100,
    });

    const group = fixture.nativeElement.querySelector('.wh-card') as HTMLElement;
    expect(group.getAttribute('role')).toBe('group');
    const ariaLabel = group.getAttribute('aria-label') ?? '';
    expect(ariaLabel).toContain('ODPEM Kingston');
    expect(ariaLabel).toContain('allocating 100');
    expect(ariaLabel).toContain('FEFO rank 1');
    expect(ariaLabel).toContain('Ranked first');
  });

  describe('batch disclosure', () => {
    it('renders the collapsed toggle with aria-expanded=false by default', async () => {
      const fixture = await render({ warehouse: buildCard() });
      const toggle = fixture.nativeElement.querySelector(
        '.wh-card__toggle',
      ) as HTMLButtonElement;
      expect(toggle.getAttribute('aria-expanded')).toBe('false');
      expect(toggle.textContent).toContain('View 2 batches');
      expect(fixture.nativeElement.querySelector('.wh-batch-table')).toBeNull();
    });

    it('expands into a grid of batches in server order and flips aria-expanded', async () => {
      const fixture = await render({ warehouse: buildCard() });
      const toggle = fixture.nativeElement.querySelector(
        '.wh-card__toggle',
      ) as HTMLButtonElement;
      toggle.click();
      fixture.detectChanges();

      expect(toggle.getAttribute('aria-expanded')).toBe('true');
      const rows = fixture.nativeElement.querySelectorAll('.wh-batch-table tbody tr');
      expect(rows.length).toBe(2);
      expect(rows[0].textContent).toContain('BT-001');
      expect(rows[1].textContent).toContain('BT-002');
    });

    it('hides the batch toggle when there are no batches to show', async () => {
      const fixture = await render({ warehouse: buildCard({ batches: [] }) });
      expect(fixture.nativeElement.querySelector('.wh-card__toggle')).toBeNull();
    });
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

  it('gives the qty input a stable hint id per warehouse for SR association', async () => {
    const fixture = await render({
      warehouse: buildCard({ warehouse_id: 9042 }),
    });
    const input = fixture.nativeElement.querySelector('input.wh-card__qty-input') as HTMLInputElement;
    const ctx = fixture.nativeElement.querySelector('.wh-card__qty-ctx') as HTMLElement;
    expect(input.getAttribute('aria-describedby')).toBe('wh-qty-hint-9042');
    expect(ctx.getAttribute('id')).toBe('wh-qty-hint-9042');
  });

  describe('pending placeholder cue', () => {
    it('renders a data-pending attribute, aria-busy, and loading badge for synthetic placeholders', async () => {
      const fixture = await render({
        warehouse: buildCard({ warehouse_id: 9099, pending: true, batches: [] }),
      });
      const host: HTMLElement = fixture.nativeElement;
      const article = host.querySelector('.wh-card') as HTMLElement;
      expect(article.getAttribute('data-pending')).toBe('true');
      expect(article.getAttribute('aria-busy')).toBe('true');
      const badge = host.querySelector('.wh-card__pending-badge') as HTMLElement;
      expect(badge).not.toBeNull();
      expect(badge.getAttribute('role')).toBe('status');
      expect(badge.textContent).toContain('Loading stock detail');
    });

    it('does not render pending affordances for a normal card', async () => {
      const fixture = await render({ warehouse: buildCard() });
      const host: HTMLElement = fixture.nativeElement;
      const article = host.querySelector('.wh-card') as HTMLElement;
      expect(article.getAttribute('data-pending')).toBeNull();
      expect(article.getAttribute('aria-busy')).toBeNull();
      expect(host.querySelector('.wh-card__pending-badge')).toBeNull();
    });
  });

  describe('qty error state', () => {
    it('renders the error hint with role="alert" and aria-live="polite" when validation fails', async () => {
      const fixture = await render({
        warehouse: buildCard(),
        remainingQtyForItem: 100,
      });
      const host: HTMLElement = fixture.nativeElement;
      const input = host.querySelector('input.wh-card__qty-input') as HTMLInputElement;
      input.value = '1.5';
      input.dispatchEvent(new Event('input'));
      fixture.detectChanges();

      const error = host.querySelector('.wh-card__qty-error') as HTMLElement;
      expect(error).not.toBeNull();
      expect(error.getAttribute('role')).toBe('alert');
      expect(error.getAttribute('aria-live')).toBe('polite');
    });

    it('clears the error when the warehouse input changes to a different card', async () => {
      const fixture = await render({
        warehouse: buildCard({ warehouse_id: 9100 }),
        remainingQtyForItem: 100,
      });
      const host: HTMLElement = fixture.nativeElement;
      const input = host.querySelector('input.wh-card__qty-input') as HTMLInputElement;
      input.value = '-5';
      input.dispatchEvent(new Event('input'));
      fixture.detectChanges();
      expect(host.querySelector('.wh-card__qty-error')).not.toBeNull();

      fixture.componentRef.setInput('warehouse', buildCard({ warehouse_id: 9101 }));
      fixture.detectChanges();
      expect(host.querySelector('.wh-card__qty-error')).toBeNull();
    });
  });
});
