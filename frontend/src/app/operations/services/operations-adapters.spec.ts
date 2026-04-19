import { normalizeWarehouseAllocationCard } from './operations-adapters';

/**
 * Adapter-level guardrail for the FR05.06 Item Allocation Redesign contract.
 *
 * The backend's `build_item_warehouse_cards` response carries three frontend-relevant
 * ranking fields that were previously dropped by the adapter:
 *   - `recommended` (bool) — which warehouse is the FEFO/FIFO primary
 *   - `allocatable_available_qty` (string decimal) — residual qty after prior draft
 *     allocations are subtracted; used to cap the per-card qty input
 *   - `ranking_context` (object | null) — rationale fields (basis, top batch meta)
 *     used to render the card's "why this rank" reason line
 *
 * These tests lock the round-trip and its graceful degradation in case a
 * compat-downgraded payload omits any of the three.
 */
describe('normalizeWarehouseAllocationCard (FR05.06)', () => {
  it('preserves recommended, allocatable_available_qty, and ranking_context from a well-formed payload', () => {
    const raw = {
      warehouse_id: 9001,
      warehouse_name: 'ODPEM Kingston',
      rank: 0,
      recommended: true,
      issuance_order: 'FEFO',
      total_available: '300',
      allocatable_available_qty: '275',
      suggested_qty: '200',
      ranking_context: {
        basis: 'FEFO',
        top_batch_id: 7001,
        top_batch_no: 'BT-001',
        top_batch_date: '2026-01-02',
        top_expiry_date: '2026-12-31',
      },
      batches: [],
    };

    const card = normalizeWarehouseAllocationCard(raw);

    expect(card.warehouse_id).toBe(9001);
    expect(card.recommended).toBeTrue();
    expect(card.allocatable_available_qty).toBe('275');
    expect(card.ranking_context).toEqual({
      basis: 'FEFO',
      top_batch_id: 7001,
      top_batch_no: 'BT-001',
      top_batch_date: '2026-01-02',
      top_expiry_date: '2026-12-31',
    });
  });

  it('tolerates a missing allocatable_available_qty by leaving it undefined (not 0)', () => {
    const raw = {
      warehouse_id: 9002,
      warehouse_name: 'ODPEM Montego Bay',
      rank: 1,
      issuance_order: 'FIFO',
      total_available: '150',
      suggested_qty: '0',
      batches: [],
    };

    const card = normalizeWarehouseAllocationCard(raw);

    expect(card.allocatable_available_qty).toBeUndefined();
  });

  it('tolerates a missing ranking_context by returning null, not a synthesized object', () => {
    const raw = {
      warehouse_id: 9002,
      warehouse_name: 'ODPEM Montego Bay',
      rank: 1,
      issuance_order: 'FIFO',
      total_available: '150',
      suggested_qty: '0',
      batches: [],
    };

    const card = normalizeWarehouseAllocationCard(raw);

    expect(card.ranking_context).toBeNull();
  });

  it('tolerates an explicit ranking_context: null from the server', () => {
    const raw = {
      warehouse_id: 9002,
      warehouse_name: 'ODPEM Montego Bay',
      rank: 1,
      issuance_order: 'FIFO',
      total_available: '150',
      suggested_qty: '0',
      ranking_context: null,
      batches: [],
    };

    const card = normalizeWarehouseAllocationCard(raw);

    expect(card.ranking_context).toBeNull();
  });

  it('falls back recommended to rank === 0 when the backend omits the field', () => {
    const rankZero = normalizeWarehouseAllocationCard({
      warehouse_id: 9001,
      warehouse_name: 'ODPEM Kingston',
      rank: 0,
      issuance_order: 'FEFO',
      total_available: '100',
      suggested_qty: '0',
      batches: [],
    });
    expect(rankZero.recommended).toBeTrue();

    const rankOne = normalizeWarehouseAllocationCard({
      warehouse_id: 9002,
      warehouse_name: 'ODPEM Montego Bay',
      rank: 1,
      issuance_order: 'FEFO',
      total_available: '100',
      suggested_qty: '0',
      batches: [],
    });
    expect(rankOne.recommended).toBeFalse();
  });

  it('respects an explicit recommended=false on a rank-0 card (backend override wins)', () => {
    const card = normalizeWarehouseAllocationCard({
      warehouse_id: 9003,
      warehouse_name: 'ODPEM Portland',
      rank: 0,
      recommended: false,
      issuance_order: 'FEFO',
      total_available: '100',
      suggested_qty: '0',
      batches: [],
    });

    expect(card.recommended).toBeFalse();
  });

  it('uppercases the ranking_context basis for defensive normalization', () => {
    const card = normalizeWarehouseAllocationCard({
      warehouse_id: 9001,
      warehouse_name: 'ODPEM Kingston',
      rank: 0,
      recommended: true,
      issuance_order: 'fefo',
      total_available: '100',
      suggested_qty: '0',
      ranking_context: {
        basis: 'fefo',
        top_batch_id: 1,
        top_batch_no: 'BT-LC',
        top_batch_date: null,
        top_expiry_date: '2026-12-31',
      },
      batches: [],
    });

    expect(card.ranking_context?.basis).toBe('FEFO');
  });
});
