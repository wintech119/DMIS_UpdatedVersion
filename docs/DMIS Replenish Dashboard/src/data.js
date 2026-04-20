// Seed data for the prototype — three illustrative items that exercise
// the three UI branches: FEFO multi-warehouse, FIFO partial, unstocked blocker.
window.ALLOCATION_DATA = {
  package: {
    code: 'PK-2026-0418-014',
    requestCode: 'RR-2026-0418-007',
    authority: 'ODPEM · Portland Parish',
    policy: 'FEFO first, FIFO on tie',
    deadline: 'Today · 16:00 JST',
  },
  items: [
    {
      itemId: 'itm-001',
      itemName: 'WATER, BOTTLED, 1L',
      itemCode: 'MMCONSWTR01',
      requestedQty: 320,
      rankingPolicy: 'FEFO',
      warehouseCards: [
        {
          warehouseId: 'wh-port-antonio',
          warehouseName: 'Port Antonio Central Warehouse',
          totalAvailable: 145,
          suggestedQty: 145,
          issuanceOrder: 1,
          rankReason: 'EARLIEST_EXPIRY',
          rankReasonDate: '12 May 2026',
          rankReasonPct: 45,
          batches: [
            { batchId: 'b-001', lotNo: 'WTR-25-091', receiptDate: '04 Sep 2025', expiryDate: '12 May 2026', available: 80, qtyToReserve: 80 },
            { batchId: 'b-002', lotNo: 'WTR-25-112', receiptDate: '14 Nov 2025', expiryDate: '20 Aug 2026', available: 65, qtyToReserve: 65 },
          ],
        },
        {
          warehouseId: 'wh-sav-la-mar',
          warehouseName: 'Savanna-la-Mar Depot',
          totalAvailable: 180,
          suggestedQty: 175,
          issuanceOrder: 2,
          rankReason: 'COVERS_REMAINDER',
          batches: [
            { batchId: 'b-003', lotNo: 'WTR-25-138', receiptDate: '02 Jan 2026', expiryDate: '03 Jun 2026', available: 180, qtyToReserve: 175 },
          ],
        },
      ],
      alternateWarehouses: [
        { warehouseId: 'wh-montego', warehouseName: 'Montego Bay Depot', available: 240, issuanceOrder: 3, nextExpiryDate: '18 Jul 2026' },
        { warehouseId: 'wh-kingston', warehouseName: 'Kingston Regional Hub', available: 510, issuanceOrder: 4, nextExpiryDate: '02 Sep 2026' },
      ],
    },
    {
      itemId: 'itm-002',
      itemName: 'FACE MASK, MEDIUM, 23 CM',
      itemCode: 'MMASSURGFA23',
      requestedQty: 20,
      rankingPolicy: 'FEFO',
      warehouseCards: [],
      alternateWarehouses: [],
      availabilityState: {
        code: 'NO_STOCK_ANYWHERE',
        title: 'No warehouse currently holds FACE MASK, MEDIUM, 23 CM',
        body: 'Inventory shows zero availability across all warehouses for this item.',
        impact: 'Item-level blocker',
        stillNeeded: 20,
        nextStep: 'Skip this item and accept partial, request inventory replenishment, or return once stock arrives.',
      },
    },
    {
      itemId: 'itm-003',
      itemName: 'TARPAULIN, 4x6 M, BLUE',
      itemCode: 'MMSHLTARP46B',
      requestedQty: 80,
      rankingPolicy: 'FIFO',
      warehouseCards: [
        {
          warehouseId: 'wh-kingston',
          warehouseName: 'Kingston Regional Hub',
          totalAvailable: 55,
          suggestedQty: 55,
          issuanceOrder: 1,
          rankReason: 'EARLIEST_RECEIPT',
          rankReasonDate: '11 Aug 2024',
          batches: [
            { batchId: 'b-010', lotNo: 'TRP-24-031', receiptDate: '11 Aug 2024', expiryDate: null, available: 55, qtyToReserve: 55 },
          ],
        },
      ],
      alternateWarehouses: [
        { warehouseId: 'wh-mandeville', warehouseName: 'Mandeville Substation', available: 25, issuanceOrder: 2, nextExpiryDate: null },
      ],
    },
    {
      itemId: 'itm-004',
      itemName: 'BLANKET, WOOL, ADULT',
      itemCode: 'MMSHLBLWLAD',
      requestedQty: 60,
      rankingPolicy: 'FIFO',
      warehouseCards: [
        {
          warehouseId: 'wh-kingston',
          warehouseName: 'Kingston Regional Hub',
          totalAvailable: 240,
          suggestedQty: 60,
          issuanceOrder: 1,
          rankReason: 'EARLIEST_RECEIPT',
          rankReasonDate: '02 Mar 2025',
          batches: [
            { batchId: 'b-020', lotNo: 'BLK-25-008', receiptDate: '02 Mar 2025', expiryDate: null, available: 240, qtyToReserve: 60 },
          ],
        },
      ],
      alternateWarehouses: [
        { warehouseId: 'wh-montego', warehouseName: 'Montego Bay Depot', available: 120, issuanceOrder: 2 },
      ],
    },
    {
      itemId: 'itm-005',
      itemName: 'HYGIENE KIT, FAMILY',
      itemCode: 'MMHYGFAM01',
      requestedQty: 40,
      rankingPolicy: 'FEFO',
      warehouseCards: [
        {
          warehouseId: 'wh-port-antonio',
          warehouseName: 'Port Antonio Central Warehouse',
          totalAvailable: 40,
          suggestedQty: 40,
          issuanceOrder: 1,
          rankReason: 'EARLIEST_EXPIRY',
          rankReasonDate: '22 Dec 2026',
          rankReasonPct: 100,
          batches: [
            { batchId: 'b-030', lotNo: 'HYG-26-003', receiptDate: '08 Jan 2026', expiryDate: '22 Dec 2026', available: 40, qtyToReserve: 40 },
          ],
        },
      ],
      alternateWarehouses: [],
    },
    {
      itemId: 'itm-006',
      itemName: 'COT, FOLDING, ADULT',
      itemCode: 'MMSHLCOTAD',
      requestedQty: 24,
      rankingPolicy: 'FIFO',
      warehouseCards: [
        {
          warehouseId: 'wh-kingston',
          warehouseName: 'Kingston Regional Hub',
          totalAvailable: 120,
          suggestedQty: 24,
          issuanceOrder: 1,
          rankReason: 'EARLIEST_RECEIPT',
          rankReasonDate: '18 Jun 2024',
          batches: [
            { batchId: 'b-040', lotNo: 'COT-24-012', receiptDate: '18 Jun 2024', expiryDate: null, available: 120, qtyToReserve: 24 },
          ],
        },
      ],
      alternateWarehouses: [],
    },
    {
      itemId: 'itm-007',
      itemName: 'JERRYCAN, 20L, COLLAPSIBLE',
      itemCode: 'MMCONSJERCAN',
      requestedQty: 50,
      rankingPolicy: 'FIFO',
      warehouseCards: [
        {
          warehouseId: 'wh-montego',
          warehouseName: 'Montego Bay Depot',
          totalAvailable: 30,
          suggestedQty: 30,
          issuanceOrder: 1,
          rankReason: 'EARLIEST_RECEIPT',
          rankReasonDate: '04 Apr 2025',
          batches: [
            { batchId: 'b-050', lotNo: 'JER-25-004', receiptDate: '04 Apr 2025', expiryDate: null, available: 30, qtyToReserve: 30 },
          ],
        },
      ],
      alternateWarehouses: [],
    },
  ],
};
