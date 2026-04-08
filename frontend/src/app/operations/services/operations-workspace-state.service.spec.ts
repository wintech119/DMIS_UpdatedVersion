import { HttpErrorResponse } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';

import {
  OperationsWorkspaceStateService,
  tryParsePackageLockConflict,
} from './operations-workspace-state.service';
import { OperationsService } from './operations.service';
import {
  AllocationCandidate,
  AllocationItemGroup,
  AllocationOptionsResponse,
  AllocationCommitPayload,
  PackageDetailResponse,
  PackageDraftPayload,
  PackageLockReleaseResponse,
  PackageSummary,
  RequestSummary,
} from '../models/operations.model';

describe('OperationsWorkspaceStateService.maybeRefreshContinuationPreview', () => {
  const ITEM_ID = 44;
  const PRIMARY_WAREHOUSE_ID = 9001;
  const SECONDARY_WAREHOUSE_ID = 9002;

  function buildCandidate(): AllocationCandidate {
    return {
      batch_id: 1,
      inventory_id: PRIMARY_WAREHOUSE_ID,
      item_id: ITEM_ID,
      usable_qty: '10',
      reserved_qty: '0',
      available_qty: '10',
      source_type: 'ON_HAND',
      can_expire_flag: false,
      issuance_order: 'FIFO',
    };
  }

  function buildItemGroup(overrides: Partial<AllocationItemGroup> = {}): AllocationItemGroup {
    return {
      item_id: ITEM_ID,
      item_code: 'WATER-044',
      item_name: 'Portable Water Container',
      request_qty: '42',
      issue_qty: '0',
      remaining_qty: '42',
      urgency_ind: 'H',
      candidates: [buildCandidate()],
      suggested_allocations: [],
      remaining_after_suggestion: '42',
      can_expire_flag: false,
      issuance_order: 'FIFO',
      compliance_markers: [],
      override_required: false,
      remaining_shortfall_qty: '32',
      continuation_recommended: true,
      alternate_warehouses: [],
      ...overrides,
    };
  }

  function buildOptionsResponse(item: AllocationItemGroup): AllocationOptionsResponse {
    return {
      request: { reliefrqst_id: 7001 } as unknown as RequestSummary,
      items: [item],
    };
  }

  function setUp(options: {
    item: AllocationItemGroup;
    loadedWarehouses: number[];
  }): { service: OperationsWorkspaceStateService; previewSpy: jasmine.Spy } {
    const previewSpy = jasmine
      .createSpy('previewItemAllocationOptions')
      .and.returnValue(of(options.item));

    const operationsServiceStub: Partial<OperationsService> = {
      previewItemAllocationOptions: previewSpy,
    };

    TestBed.configureTestingModule({
      providers: [
        OperationsWorkspaceStateService,
        { provide: OperationsService, useValue: operationsServiceStub },
      ],
    });

    const service = TestBed.inject(OperationsWorkspaceStateService);
    service.reliefrqstId.set(7001);
    service.options.set(buildOptionsResponse(options.item));
    service.loadedWarehousesByItem.set({ [options.item.item_id]: options.loadedWarehouses });

    return { service, previewSpy };
  }

  beforeEach(() => {
    TestBed.resetTestingModule();
  });

  it('fires the POST preview when continuation is recommended for a single-warehouse item', () => {
    const item = buildItemGroup({ continuation_recommended: true });
    const { service, previewSpy } = setUp({
      item,
      loadedWarehouses: [PRIMARY_WAREHOUSE_ID],
    });

    service.setCandidateQuantity(ITEM_ID, item.candidates[0], 5);

    expect(previewSpy).toHaveBeenCalledTimes(1);
    const [reliefrqstId, itemId, payload] = previewSpy.calls.mostRecent().args;
    expect(reliefrqstId).toBe(7001);
    expect(itemId).toBe(ITEM_ID);
    expect(payload.source_warehouse_id).toBe(PRIMARY_WAREHOUSE_ID);
    expect(payload.draft_allocations.length).toBe(1);
    expect(payload.draft_allocations[0].item_id).toBe(ITEM_ID);
    expect(payload.draft_allocations[0].inventory_id).toBe(PRIMARY_WAREHOUSE_ID);
  });

  it('does NOT fire the POST preview when continuation is not recommended and only one warehouse is loaded', () => {
    const item = buildItemGroup({ continuation_recommended: false });
    const { service, previewSpy } = setUp({
      item,
      loadedWarehouses: [PRIMARY_WAREHOUSE_ID],
    });

    service.setCandidateQuantity(ITEM_ID, item.candidates[0], 5);

    expect(previewSpy).not.toHaveBeenCalled();
  });

  it('fires the POST preview against the last loaded warehouse for multi-warehouse items even when continuation_recommended is false', () => {
    const item = buildItemGroup({ continuation_recommended: false });
    const { service, previewSpy } = setUp({
      item,
      loadedWarehouses: [PRIMARY_WAREHOUSE_ID, SECONDARY_WAREHOUSE_ID],
    });

    service.setCandidateQuantity(ITEM_ID, item.candidates[0], 5);

    expect(previewSpy).toHaveBeenCalledTimes(1);
    const [, , payload] = previewSpy.calls.mostRecent().args;
    expect(payload.source_warehouse_id).toBe(SECONDARY_WAREHOUSE_ID);
  });
});

describe('OperationsWorkspaceStateService.saveDraft', () => {
  const RELIEFRQST_ID = 95009;
  const RELIEFPKG_ID = 77001;

  function buildPackageDetail(overrides: Partial<PackageSummary> = {}): PackageDetailResponse {
    const pkg: PackageSummary = {
      reliefpkg_id: RELIEFPKG_ID,
      tracking_no: 'PKG-001',
      reliefrqst_id: RELIEFRQST_ID,
      agency_id: 1,
      eligible_event_id: null,
      source_warehouse_id: 9001,
      to_inventory_id: 9002,
      destination_warehouse_name: 'Destination WH',
      status_code: 'DRAFT',
      status_label: 'Draft',
      dispatch_dtime: null,
      received_dtime: null,
      transport_mode: 'TRUCK',
      comments_text: 'Saved from draft',
      version_nbr: 1,
      execution_status: null,
      needs_list_id: null,
      compatibility_bridge: false,
      fulfillment_mode: 'DIRECT',
      staging_warehouse_id: null,
      staging_override_reason: null,
      ...overrides,
    };
    return {
      request: { reliefrqst_id: RELIEFRQST_ID } as unknown as RequestSummary,
      package: pkg,
      items: [],
      compatibility_only: false,
    };
  }

  function setUp(): {
    service: OperationsWorkspaceStateService;
    saveSpy: jasmine.Spy;
    response: PackageDetailResponse;
  } {
    const response = buildPackageDetail();
    const saveSpy = jasmine.createSpy('savePackageDraft').and.returnValue(of(response));
    const operationsServiceStub: Partial<OperationsService> = {
      savePackageDraft: saveSpy,
    };

    TestBed.configureTestingModule({
      providers: [
        OperationsWorkspaceStateService,
        { provide: OperationsService, useValue: operationsServiceStub },
      ],
    });

    const service = TestBed.inject(OperationsWorkspaceStateService);
    service.reliefrqstId.set(RELIEFRQST_ID);
    return { service, saveSpy, response };
  }

  beforeEach(() => {
    TestBed.resetTestingModule();
  });

  it('builds a PackageDraftPayload from the draft signal and calls savePackageDraft', () => {
    const { service, saveSpy } = setUp();
    service.patchDraft({
      source_warehouse_id: '9001',
      to_inventory_id: '9002',
      transport_mode: '  TRUCK  ',
      comments_text: '  Hold for consolidation  ',
      fulfillment_mode: 'PICKUP_AT_STAGING',
      staging_warehouse_id: '9501',
      staging_override_reason: '  Closer to field site  ',
    });
    service.selectedRowsByItem.set({
      44: [
        {
          item_id: 44,
          inventory_id: 9001,
          batch_id: 1001,
          quantity: '3',
          source_type: 'ON_HAND',
          source_record_id: null,
          uom_code: 'EA',
        },
      ],
    });

    service.saveDraft().subscribe();

    expect(saveSpy).toHaveBeenCalledTimes(1);
    const [reliefrqstId, payload] = saveSpy.calls.mostRecent().args as [number, PackageDraftPayload];
    expect(reliefrqstId).toBe(RELIEFRQST_ID);
    expect(payload.source_warehouse_id).toBe(9001);
    expect(payload.to_inventory_id).toBe(9002);
    expect(payload.transport_mode).toBe('TRUCK');
    expect(payload.comments_text).toBe('Hold for consolidation');
    expect(payload.allocations).toEqual([
      {
        item_id: 44,
        inventory_id: 9001,
        batch_id: 1001,
        quantity: '3.0000',
        source_type: 'ON_HAND',
        source_record_id: null,
        uom_code: 'EA',
      },
    ]);
    expect(payload.fulfillment_mode).toBe('PICKUP_AT_STAGING');
    expect(payload.staging_warehouse_id).toBe(9501);
    expect(payload.staging_override_reason).toBe('Closer to field site');
  });

  it('sends undefined for empty header fields and null for an empty staging reason', () => {
    const { service, saveSpy } = setUp();
    service.patchDraft({
      source_warehouse_id: '',
      to_inventory_id: '',
      transport_mode: '   ',
      comments_text: '',
      fulfillment_mode: 'DIRECT',
      staging_warehouse_id: '',
      staging_override_reason: '   ',
    });

    service.saveDraft().subscribe();

    const [, payload] = saveSpy.calls.mostRecent().args as [number, PackageDraftPayload];
    expect(payload.source_warehouse_id).toBeUndefined();
    expect(payload.to_inventory_id).toBeUndefined();
    expect(payload.transport_mode).toBeUndefined();
    expect(payload.comments_text).toBeUndefined();
    expect(payload.staging_warehouse_id).toBeNull();
    expect(payload.staging_override_reason).toBeNull();
  });

  it('derives the package source warehouse from selected allocation rows when the draft source is blank', () => {
    const { service, saveSpy } = setUp();
    service.patchDraft({
      source_warehouse_id: '',
      fulfillment_mode: 'DIRECT',
    });
    service.selectedRowsByItem.set({
      44: [
        {
          item_id: 44,
          inventory_id: 9123,
          batch_id: 1001,
          quantity: '3.0000',
          source_type: 'ON_HAND',
          source_record_id: null,
          uom_code: 'EA',
        },
      ],
    });

    service.saveDraft().subscribe();

    const [, payload] = saveSpy.calls.mostRecent().args as [number, PackageDraftPayload];
    expect(payload.source_warehouse_id).toBe(9123);
  });

  it('does not collapse a mixed-warehouse draft to the first selected warehouse when no package source exists', () => {
    const { service, saveSpy } = setUp();
    service.packageDetail.set(buildPackageDetail({ source_warehouse_id: null }));
    service.patchDraft({
      source_warehouse_id: '',
      fulfillment_mode: 'DIRECT',
    });
    service.selectedRowsByItem.set({
      44: [
        {
          item_id: 44,
          inventory_id: 9123,
          batch_id: 1001,
          quantity: '3.0000',
          source_type: 'ON_HAND',
          source_record_id: null,
          uom_code: 'EA',
        },
      ],
      45: [
        {
          item_id: 45,
          inventory_id: 9456,
          batch_id: 2001,
          quantity: '1.0000',
          source_type: 'ON_HAND',
          source_record_id: null,
          uom_code: 'EA',
        },
      ],
    });

    service.saveDraft().subscribe();

    const [, payload] = saveSpy.calls.mostRecent().args as [number, PackageDraftPayload];
    expect(payload.source_warehouse_id).toBeUndefined();
    expect(payload.allocations?.map((row) => row.inventory_id)).toEqual([9123, 9456]);
  });

  it('hydrates packageDetail and reliefpkgId from the save response', () => {
    const { service, response } = setUp();

    service.saveDraft().subscribe();

    expect(service.packageDetail()).toBe(response);
    expect(service.reliefpkgId()).toBe(RELIEFPKG_ID);
    // hydrateDraft should also have reflected the response transport/comments into the draft signal.
    expect(service.draft().transport_mode).toBe('TRUCK');
    expect(service.draft().comments_text).toBe('Saved from draft');
  });
});

describe('OperationsWorkspaceStateService.buildCommitPayload', () => {
  function buildCandidate(): AllocationCandidate {
    return {
      batch_id: 1001,
      inventory_id: 9001,
      item_id: 44,
      usable_qty: '10',
      reserved_qty: '0',
      available_qty: '10',
      source_type: 'ON_HAND',
      can_expire_flag: true,
      issuance_order: 'FEFO',
      batch_no: 'B-1001',
    };
  }

  function buildOverrideCandidate(): AllocationCandidate {
    return {
      batch_id: 1002,
      inventory_id: 9002,
      item_id: 44,
      usable_qty: '10',
      reserved_qty: '0',
      available_qty: '10',
      source_type: 'ON_HAND',
      can_expire_flag: true,
      issuance_order: 'FEFO',
      batch_no: 'B-1002',
    };
  }

  function buildItemGroup(): AllocationItemGroup {
    return {
      item_id: 44,
      item_code: 'WATER-044',
      item_name: 'Portable Water Container',
      request_qty: '2',
      issue_qty: '0',
      remaining_qty: '2',
      urgency_ind: 'H',
      candidates: [buildCandidate(), buildOverrideCandidate()],
      suggested_allocations: [],
      remaining_after_suggestion: '0',
      can_expire_flag: true,
      issuance_order: 'FEFO',
      compliance_markers: ['allocation_order_override'],
      override_required: false,
      remaining_shortfall_qty: '0',
      continuation_recommended: false,
      alternate_warehouses: [],
    };
  }

  beforeEach(() => {
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      providers: [
        OperationsWorkspaceStateService,
        { provide: OperationsService, useValue: {} },
      ],
    });
  });

  it('includes override metadata when the selected plan bypasses allocation rules', () => {
    const service = TestBed.inject(OperationsWorkspaceStateService);
    service.options.set({
      request: { reliefrqst_id: 95009 } as unknown as RequestSummary,
      items: [buildItemGroup()],
    });
    service.patchDraft({
      source_warehouse_id: '9001',
      override_reason_code: ' FEFO_BYPASS ',
      override_note: ' Needs manager approval ',
    });
    service.selectedRowsByItem.set({
      44: [
        {
          item_id: 44,
          inventory_id: 9002,
          batch_id: 1002,
          quantity: '2',
          source_type: 'ON_HAND',
          source_record_id: null,
          uom_code: 'EA',
        },
      ],
    });

    const result = service.buildCommitPayload();

    expect(result.errors).toEqual([]);
    expect(result.payload).toEqual(
      jasmine.objectContaining<AllocationCommitPayload>({
        source_warehouse_id: 9001,
        override_reason_code: 'FEFO_BYPASS',
        override_note: 'Needs manager approval',
      }),
    );
  });

  it('rejects stale draft selections that no longer exist in the current candidate list', () => {
    const service = TestBed.inject(OperationsWorkspaceStateService);
    service.options.set({
      request: { reliefrqst_id: 95009 } as unknown as RequestSummary,
      items: [buildItemGroup()],
    });
    service.selectedRowsByItem.set({
      44: [
        {
          item_id: 44,
          inventory_id: 9999,
          batch_id: 7777,
          quantity: '2',
          source_type: 'ON_HAND',
          source_record_id: null,
          uom_code: 'EA',
        },
      ],
    });

    const result = service.buildCommitPayload();

    expect(result.payload).toBeNull();
    expect(result.errors).toContain(
      'Portable Water Container: One or more selected stock lines are no longer available. Refresh the item selection before continuing.',
    );
  });
});

describe('OperationsWorkspaceStateService.saveFulfillmentModeDraft', () => {
  const RELIEFRQST_ID = 95009;

  beforeEach(() => {
    TestBed.resetTestingModule();
  });

  it('includes the current allocation rows when auto-saving fulfillment changes', () => {
    const response = {
      request: { reliefrqst_id: RELIEFRQST_ID } as unknown as RequestSummary,
      package: {
        reliefpkg_id: 77001,
        tracking_no: 'PKG-001',
        reliefrqst_id: RELIEFRQST_ID,
        agency_id: 1,
        eligible_event_id: null,
        source_warehouse_id: 9001,
        to_inventory_id: 9002,
        destination_warehouse_name: 'Destination WH',
        status_code: 'DRAFT',
        status_label: 'Draft',
        dispatch_dtime: null,
        received_dtime: null,
        transport_mode: null,
        comments_text: null,
        version_nbr: 1,
        execution_status: null,
        needs_list_id: null,
        compatibility_bridge: false,
        fulfillment_mode: 'PICKUP_AT_STAGING',
        staging_warehouse_id: 9501,
        staging_override_reason: 'Closer to field site',
      },
      items: [],
      compatibility_only: false,
    } as PackageDetailResponse;
    const saveSpy = jasmine.createSpy('savePackageDraft').and.returnValue(of(response));
    const getConsolidationLegsSpy = jasmine
      .createSpy('getConsolidationLegs')
      .and.returnValue(of({ results: [], package: null }));

    TestBed.configureTestingModule({
      providers: [
        OperationsWorkspaceStateService,
        {
          provide: OperationsService,
          useValue: {
            savePackageDraft: saveSpy,
            getConsolidationLegs: getConsolidationLegsSpy,
          } satisfies Partial<OperationsService>,
        },
      ],
    });

    const service = TestBed.inject(OperationsWorkspaceStateService);
    service.reliefrqstId.set(RELIEFRQST_ID);
    service.patchDraft({
      source_warehouse_id: '9001',
      fulfillment_mode: 'DIRECT',
    });
    service.options.set({
      request: { reliefrqst_id: RELIEFRQST_ID } as unknown as RequestSummary,
      items: [],
    });
    service.selectedRowsByItem.set({
      44: [
        {
          item_id: 44,
          inventory_id: 9001,
          batch_id: 1001,
          quantity: '3',
          source_type: 'ON_HAND',
          source_record_id: null,
          uom_code: 'EA',
        },
      ],
    });

    service.saveFulfillmentModeDraft('PICKUP_AT_STAGING', 9501, 'Closer to field site').subscribe();

    const [, payload] = saveSpy.calls.mostRecent().args as [number, PackageDraftPayload];
    expect(payload.allocations).toEqual([
      {
        item_id: 44,
        inventory_id: 9001,
        batch_id: 1001,
        quantity: '3.0000',
        source_type: 'ON_HAND',
        source_record_id: null,
        uom_code: 'EA',
      },
    ]);
    expect(payload.fulfillment_mode).toBe('PICKUP_AT_STAGING');
    expect(payload.staging_warehouse_id).toBe(9501);
    expect(payload.staging_override_reason).toBe('Closer to field site');
  });
});

describe('OperationsWorkspaceStateService.load', () => {
  const RELIEFRQST_ID = 95009;
  const SOURCE_WAREHOUSE_ID = 9001;

  function buildPackageDetail(): PackageDetailResponse {
    return {
      request: { reliefrqst_id: RELIEFRQST_ID } as unknown as RequestSummary,
      package: {
        reliefpkg_id: 77001,
        tracking_no: 'PKG-001',
        reliefrqst_id: RELIEFRQST_ID,
        agency_id: 1,
        eligible_event_id: null,
        source_warehouse_id: SOURCE_WAREHOUSE_ID,
        to_inventory_id: 9002,
        destination_warehouse_name: 'Destination WH',
        status_code: 'DRAFT',
        status_label: 'Draft',
        dispatch_dtime: null,
        received_dtime: null,
        transport_mode: null,
        comments_text: null,
        version_nbr: 1,
        execution_status: null,
        needs_list_id: null,
        compatibility_bridge: false,
        fulfillment_mode: 'DIRECT',
        staging_warehouse_id: null,
        staging_override_reason: null,
      },
      items: [],
      compatibility_only: false,
    };
  }

  beforeEach(() => {
    TestBed.resetTestingModule();
  });

  it('rehydrates allocation options from the saved source warehouse on initial load', () => {
    const packageDetail = buildPackageDetail();
    const getPackageSpy = jasmine.createSpy('getPackage').and.returnValue(of(packageDetail));
    const getAllocationOptionsSpy = jasmine
      .createSpy('getAllocationOptions')
      .and.returnValue(of({ request: packageDetail.request, items: [] } as AllocationOptionsResponse));

    TestBed.configureTestingModule({
      providers: [
        OperationsWorkspaceStateService,
        {
          provide: OperationsService,
          useValue: {
            getPackage: getPackageSpy,
            getAllocationOptions: getAllocationOptionsSpy,
          } satisfies Partial<OperationsService>,
        },
      ],
    });

    const service = TestBed.inject(OperationsWorkspaceStateService);

    service.load(RELIEFRQST_ID, true);

    expect(getPackageSpy).toHaveBeenCalledWith(RELIEFRQST_ID);
    expect(getAllocationOptionsSpy).toHaveBeenCalledWith(RELIEFRQST_ID, SOURCE_WAREHOUSE_ID);
    expect(service.draft().source_warehouse_id).toBe(String(SOURCE_WAREHOUSE_ID));
  });

  it('populates itemWarehouseOverrides when committed lines reference a different warehouse', () => {
    const ITEM_ID = 101;
    const OVERRIDE_WAREHOUSE_ID = 9002;
    const packageDetail = buildPackageDetail();
    packageDetail.allocation = {
      allocation_lines: [
        {
          item_id: ITEM_ID,
          inventory_id: OVERRIDE_WAREHOUSE_ID,
          batch_id: 5001,
          quantity: '3.0000',
          source_type: 'ON_HAND',
          source_record_id: null,
          uom_code: 'EA',
        },
      ],
      reserved_stock_summary: { line_count: 1, total_qty: '3.0000' },
      waybill_no: null,
    };

    const optionsResponse: AllocationOptionsResponse = {
      request: packageDetail.request,
      items: [
        {
          item_id: ITEM_ID,
          item_code: 'TARP001',
          item_name: 'Tarpaulin',
          request_qty: '5.0000',
          issue_qty: '0.0000',
          remaining_qty: '5.0000',
          urgency_ind: 'H',
          candidates: [
            {
              batch_id: 3001,
              inventory_id: SOURCE_WAREHOUSE_ID,
              item_id: ITEM_ID,
              usable_qty: '2',
              reserved_qty: '0',
              available_qty: '2',
              source_type: 'ON_HAND',
              can_expire_flag: false,
              issuance_order: 'FIFO',
              warehouse_name: 'Seeded Warehouse',
            },
            {
              batch_id: 5001,
              inventory_id: OVERRIDE_WAREHOUSE_ID,
              item_id: ITEM_ID,
              usable_qty: '4',
              reserved_qty: '0',
              available_qty: '4',
              source_type: 'ON_HAND',
              can_expire_flag: false,
              issuance_order: 'FIFO',
              warehouse_name: 'Override Warehouse',
            },
          ],
          suggested_allocations: [],
          remaining_after_suggestion: '5.0000',
          can_expire_flag: false,
          issuance_order: 'FIFO',
          compliance_markers: [],
          override_required: false,
          source_warehouse_id: SOURCE_WAREHOUSE_ID,
          remaining_shortfall_qty: '5.0000',
          continuation_recommended: false,
          alternate_warehouses: [],
        },
      ],
    };
    const getPackageSpy = jasmine.createSpy('getPackage').and.returnValue(of(packageDetail));
    const getAllocationOptionsSpy = jasmine
      .createSpy('getAllocationOptions')
      .and.returnValue(of(optionsResponse));

    TestBed.configureTestingModule({
      providers: [
        OperationsWorkspaceStateService,
        {
          provide: OperationsService,
          useValue: {
            getPackage: getPackageSpy,
            getAllocationOptions: getAllocationOptionsSpy,
          } satisfies Partial<OperationsService>,
        },
      ],
    });

    const service = TestBed.inject(OperationsWorkspaceStateService);

    service.load(RELIEFRQST_ID, true);

    expect(service.itemWarehouseOverrides()).toEqual({ [ITEM_ID]: String(OVERRIDE_WAREHOUSE_ID) });
    expect(service.effectiveWarehouseForItem(ITEM_ID)).toBe(String(OVERRIDE_WAREHOUSE_ID));
    expect(service.selectedRowsByItem()[ITEM_ID]).toEqual([
      jasmine.objectContaining({
        item_id: ITEM_ID,
        inventory_id: OVERRIDE_WAREHOUSE_ID,
        batch_id: 5001,
        quantity: '3.0000',
      }),
    ]);
    expect(service.seededWarehousesByItem()[ITEM_ID]).toBe(String(SOURCE_WAREHOUSE_ID));
  });

  it('leaves itemWarehouseOverrides empty when committed lines match the seeded warehouse', () => {
    const ITEM_ID = 101;
    const packageDetail = buildPackageDetail();
    packageDetail.allocation = {
      allocation_lines: [
        {
          item_id: ITEM_ID,
          inventory_id: SOURCE_WAREHOUSE_ID,
          batch_id: 3001,
          quantity: '2.0000',
          source_type: 'ON_HAND',
          source_record_id: null,
          uom_code: 'EA',
        },
      ],
      reserved_stock_summary: { line_count: 1, total_qty: '2.0000' },
      waybill_no: null,
    };

    const optionsResponse: AllocationOptionsResponse = {
      request: packageDetail.request,
      items: [
        {
          item_id: ITEM_ID,
          item_code: 'TARP001',
          item_name: 'Tarpaulin',
          request_qty: '5.0000',
          issue_qty: '0.0000',
          remaining_qty: '5.0000',
          urgency_ind: 'H',
          candidates: [
            {
              batch_id: 3001,
              inventory_id: SOURCE_WAREHOUSE_ID,
              item_id: ITEM_ID,
              usable_qty: '4',
              reserved_qty: '0',
              available_qty: '4',
              source_type: 'ON_HAND',
              can_expire_flag: false,
              issuance_order: 'FIFO',
              warehouse_name: 'Seeded Warehouse',
            },
          ],
          suggested_allocations: [],
          remaining_after_suggestion: '3.0000',
          can_expire_flag: false,
          issuance_order: 'FIFO',
          compliance_markers: [],
          override_required: false,
          source_warehouse_id: SOURCE_WAREHOUSE_ID,
          remaining_shortfall_qty: '3.0000',
          continuation_recommended: false,
          alternate_warehouses: [],
        },
      ],
    };
    const getPackageSpy = jasmine.createSpy('getPackage').and.returnValue(of(packageDetail));
    const getAllocationOptionsSpy = jasmine
      .createSpy('getAllocationOptions')
      .and.returnValue(of(optionsResponse));

    TestBed.configureTestingModule({
      providers: [
        OperationsWorkspaceStateService,
        {
          provide: OperationsService,
          useValue: {
            getPackage: getPackageSpy,
            getAllocationOptions: getAllocationOptionsSpy,
          } satisfies Partial<OperationsService>,
        },
      ],
    });

    const service = TestBed.inject(OperationsWorkspaceStateService);

    service.load(RELIEFRQST_ID, true);

    expect(service.itemWarehouseOverrides()).toEqual({});
    expect(service.effectiveWarehouseForItem(ITEM_ID)).toBe(String(SOURCE_WAREHOUSE_ID));
  });
});

describe('OperationsWorkspaceStateService.updateItemWarehouse', () => {
  const RELIEFRQST_ID = 7001;
  const ITEM_ID = 44;
  const PRIMARY_WAREHOUSE_ID = 9001;
  const SECONDARY_WAREHOUSE_ID = 9002;

  function buildCandidate(inventoryId: number, batchId: number): AllocationCandidate {
    return {
      batch_id: batchId,
      inventory_id: inventoryId,
      item_id: ITEM_ID,
      usable_qty: '10',
      reserved_qty: '0',
      available_qty: '10',
      source_type: 'ON_HAND',
      can_expire_flag: false,
      issuance_order: 'FIFO',
      warehouse_name: `Warehouse ${inventoryId}`,
    };
  }

  function buildItemGroup(sourceWarehouseId: number): AllocationItemGroup {
    return {
      item_id: ITEM_ID,
      item_code: 'WATER-044',
      item_name: 'Portable Water Container',
      request_qty: '6.0000',
      issue_qty: '0.0000',
      remaining_qty: '6.0000',
      urgency_ind: 'H',
      candidates: [buildCandidate(sourceWarehouseId, sourceWarehouseId === PRIMARY_WAREHOUSE_ID ? 1001 : 2001)],
      suggested_allocations: [
        {
          item_id: ITEM_ID,
          inventory_id: sourceWarehouseId,
          batch_id: sourceWarehouseId === PRIMARY_WAREHOUSE_ID ? 1001 : 2001,
          quantity: '6.0000',
          source_type: 'ON_HAND',
          source_record_id: null,
          uom_code: 'EA',
        },
      ],
      remaining_after_suggestion: '0.0000',
      can_expire_flag: false,
      issuance_order: 'FIFO',
      compliance_markers: [],
      override_required: false,
      source_warehouse_id: sourceWarehouseId,
      remaining_shortfall_qty: '0.0000',
      continuation_recommended: false,
      alternate_warehouses: [],
    };
  }

  beforeEach(() => {
    TestBed.resetTestingModule();
  });

  it('clears the override when the operator switches back to the original seeded warehouse', () => {
    const getItemAllocationOptionsSpy = jasmine
      .createSpy('getItemAllocationOptions')
      .and.returnValues(
        of(buildItemGroup(SECONDARY_WAREHOUSE_ID)),
        of(buildItemGroup(PRIMARY_WAREHOUSE_ID)),
      );

    TestBed.configureTestingModule({
      providers: [
        OperationsWorkspaceStateService,
        {
          provide: OperationsService,
          useValue: {
            getItemAllocationOptions: getItemAllocationOptionsSpy,
          } satisfies Partial<OperationsService>,
        },
      ],
    });

    const service = TestBed.inject(OperationsWorkspaceStateService);
    service.reliefrqstId.set(RELIEFRQST_ID);
    service.patchDraft({ source_warehouse_id: '' });
    service.options.set({
      request: { reliefrqst_id: RELIEFRQST_ID } as unknown as RequestSummary,
      items: [buildItemGroup(PRIMARY_WAREHOUSE_ID)],
    });
    service.seededWarehousesByItem.set({ [ITEM_ID]: String(PRIMARY_WAREHOUSE_ID) });

    service.updateItemWarehouse(ITEM_ID, String(SECONDARY_WAREHOUSE_ID));
    expect(service.itemWarehouseOverrides()).toEqual({ [ITEM_ID]: String(SECONDARY_WAREHOUSE_ID) });

    service.updateItemWarehouse(ITEM_ID, String(PRIMARY_WAREHOUSE_ID));

    expect(service.itemWarehouseOverrides()).toEqual({});
    expect(service.effectiveWarehouseForItem(ITEM_ID)).toBe(String(PRIMARY_WAREHOUSE_ID));
  });
});

describe('tryParsePackageLockConflict', () => {
  it('returns a structured conflict from a canned HttpErrorResponse with the backend shape', () => {
    const error = new HttpErrorResponse({
      status: 400,
      error: {
        errors: {
          lock: 'Package is locked by another fulfillment actor.',
          lock_owner_user_id: 'kemar.logistics',
          lock_owner_role_code: 'LOGISTICS_MANAGER',
          lock_expires_at: '2026-04-07T15:30:00+00:00',
        },
      },
    });

    const conflict = tryParsePackageLockConflict(error);

    expect(conflict).not.toBeNull();
    expect(conflict?.lock).toBe('Package is locked by another fulfillment actor.');
    expect(conflict?.lock_owner_user_id).toBe('kemar.logistics');
    expect(conflict?.lock_owner_role_code).toBe('LOGISTICS_MANAGER');
    expect(conflict?.lock_expires_at).toBe('2026-04-07T15:30:00+00:00');
  });

  it('returns null when the 400 payload does not include a lock key', () => {
    const error = new HttpErrorResponse({
      status: 400,
      error: { errors: { source_warehouse_id: 'Must be a positive integer.' } },
    });

    expect(tryParsePackageLockConflict(error)).toBeNull();
  });

  it('returns null for non-400 statuses', () => {
    const error = new HttpErrorResponse({
      status: 500,
      error: { errors: { lock: 'Package is locked by another fulfillment actor.' } },
    });

    expect(tryParsePackageLockConflict(error)).toBeNull();
  });

  it('returns null for non-HttpErrorResponse inputs', () => {
    expect(tryParsePackageLockConflict(new Error('boom'))).toBeNull();
    expect(tryParsePackageLockConflict(null)).toBeNull();
    expect(tryParsePackageLockConflict(undefined)).toBeNull();
  });

  it('handles missing optional owner fields by returning null entries', () => {
    const error = new HttpErrorResponse({
      status: 400,
      error: {
        errors: {
          lock: 'Package is locked by another fulfillment actor.',
        },
      },
    });

    const conflict = tryParsePackageLockConflict(error);

    expect(conflict?.lock_owner_user_id).toBeNull();
    expect(conflict?.lock_owner_role_code).toBeNull();
    expect(conflict?.lock_expires_at).toBeNull();
  });
});

describe('OperationsWorkspaceStateService.addItemWarehouse', () => {
  const RELIEFRQST_ID = 7001;
  const ITEM_ID = 44;
  const PRIMARY_WAREHOUSE_ID = 9001;
  const SECONDARY_WAREHOUSE_ID = 9002;

  function buildCandidate(overrides: Partial<AllocationCandidate> = {}): AllocationCandidate {
    return {
      batch_id: 1,
      inventory_id: PRIMARY_WAREHOUSE_ID,
      item_id: ITEM_ID,
      usable_qty: '10',
      reserved_qty: '0',
      available_qty: '10',
      source_type: 'ON_HAND',
      can_expire_flag: false,
      issuance_order: 'FIFO',
      ...overrides,
    };
  }

  function buildItemGroup(overrides: Partial<AllocationItemGroup> = {}): AllocationItemGroup {
    return {
      item_id: ITEM_ID,
      item_code: 'WATER-044',
      item_name: 'Portable Water Container',
      request_qty: '6.0000',
      issue_qty: '0.0000',
      remaining_qty: '6.0000',
      urgency_ind: 'H',
      candidates: [buildCandidate()],
      suggested_allocations: [],
      remaining_after_suggestion: '2.0000',
      can_expire_flag: false,
      issuance_order: 'FIFO',
      compliance_markers: [],
      override_required: false,
      source_warehouse_id: PRIMARY_WAREHOUSE_ID,
      remaining_shortfall_qty: '2.0000',
      continuation_recommended: true,
      alternate_warehouses: [
        {
          warehouse_id: SECONDARY_WAREHOUSE_ID,
          warehouse_name: 'Warehouse 9002',
          available_qty: '2.0000',
          suggested_qty: '2.0000',
          can_fully_cover: true,
        },
      ],
      draft_selected_qty: '4.0000',
      effective_remaining_qty: '2.0000',
      ...overrides,
    };
  }

  beforeEach(() => {
    TestBed.resetTestingModule();
  });

  it('recomputes draft-aware metrics after auto-adding another warehouse', () => {
    const additivePreview = buildItemGroup({
      candidates: [
        buildCandidate({
          batch_id: 2,
          inventory_id: SECONDARY_WAREHOUSE_ID,
          available_qty: '2.0000',
          usable_qty: '2.0000',
        }),
      ],
      suggested_allocations: [
        {
          item_id: ITEM_ID,
          inventory_id: SECONDARY_WAREHOUSE_ID,
          batch_id: 2,
          quantity: '2.0000',
          source_type: 'ON_HAND',
          source_record_id: null,
          uom_code: 'EA',
        },
      ],
      source_warehouse_id: SECONDARY_WAREHOUSE_ID,
      remaining_shortfall_qty: '2.0000',
      continuation_recommended: true,
      alternate_warehouses: [],
      draft_selected_qty: '4.0000',
      effective_remaining_qty: '2.0000',
    });
    const refreshedPreview = buildItemGroup({
      candidates: additivePreview.candidates,
      suggested_allocations: additivePreview.suggested_allocations,
      source_warehouse_id: SECONDARY_WAREHOUSE_ID,
      remaining_after_suggestion: '0.0000',
      remaining_shortfall_qty: '0.0000',
      continuation_recommended: false,
      alternate_warehouses: [],
      draft_selected_qty: '6.0000',
      effective_remaining_qty: '0.0000',
    });
    const previewSpy = jasmine
      .createSpy('previewItemAllocationOptions')
      .and.returnValues(of(additivePreview), of(refreshedPreview));

    TestBed.configureTestingModule({
      providers: [
        OperationsWorkspaceStateService,
        {
          provide: OperationsService,
          useValue: {
            previewItemAllocationOptions: previewSpy,
          } satisfies Partial<OperationsService>,
        },
      ],
    });

    const service = TestBed.inject(OperationsWorkspaceStateService);
    service.reliefrqstId.set(RELIEFRQST_ID);
    service.options.set({
      request: { reliefrqst_id: RELIEFRQST_ID } as unknown as RequestSummary,
      items: [buildItemGroup()],
    });
    service.selectedRowsByItem.set({
      [ITEM_ID]: [
        {
          item_id: ITEM_ID,
          inventory_id: PRIMARY_WAREHOUSE_ID,
          batch_id: 1,
          quantity: '4.0000',
          source_type: 'ON_HAND',
          source_record_id: null,
          uom_code: 'EA',
        },
      ],
    });
    service.loadedWarehousesByItem.set({ [ITEM_ID]: [PRIMARY_WAREHOUSE_ID] });

    service.addItemWarehouse(ITEM_ID, SECONDARY_WAREHOUSE_ID);

    expect(previewSpy).toHaveBeenCalledTimes(2);
    const secondCall = previewSpy.calls.argsFor(1);
    expect(secondCall[0]).toBe(RELIEFRQST_ID);
    expect(secondCall[1]).toBe(ITEM_ID);
    expect(secondCall[2].source_warehouse_id).toBe(SECONDARY_WAREHOUSE_ID);
    expect(secondCall[2].draft_allocations).toEqual([
      {
        item_id: ITEM_ID,
        inventory_id: PRIMARY_WAREHOUSE_ID,
        batch_id: 1,
        quantity: '4.0000',
        source_type: 'ON_HAND',
        source_record_id: null,
        uom_code: 'EA',
      },
      {
        item_id: ITEM_ID,
        inventory_id: SECONDARY_WAREHOUSE_ID,
        batch_id: 2,
        quantity: '2.0000',
        source_type: 'ON_HAND',
        source_record_id: null,
        uom_code: 'EA',
      },
    ]);

    const updatedItem = service.options()?.items[0];
    expect(updatedItem?.draft_selected_qty).toBe('6.0000');
    expect(updatedItem?.effective_remaining_qty).toBe('0.0000');
    expect(updatedItem?.remaining_shortfall_qty).toBe('0.0000');
    expect(updatedItem?.continuation_recommended).toBeFalse();
    expect(service.getSelectedTotalForItem(ITEM_ID)).toBe(6);
  });
});

describe('OperationsWorkspaceStateService lock conflict interception', () => {
  const RELIEFRQST_ID = 95009;

  function setUp(): {
    service: OperationsWorkspaceStateService;
    saveSpy: jasmine.Spy;
    releaseSpy: jasmine.Spy;
    getPackageSpy: jasmine.Spy;
    getAllocationOptionsSpy: jasmine.Spy;
  } {
    const saveSpy = jasmine.createSpy('savePackageDraft').and.returnValue(
      throwError(() => new HttpErrorResponse({
        status: 400,
        error: {
          errors: {
            lock: 'Package is locked by another fulfillment actor.',
            lock_owner_user_id: 'other.user',
            lock_owner_role_code: 'LOGISTICS_MANAGER',
            lock_expires_at: '2026-04-07T16:00:00+00:00',
          },
        },
      })),
    );
    const releaseSpy = jasmine.createSpy('releasePackageLock').and.returnValue(
      of<PackageLockReleaseResponse>({
        released: true,
        message: 'Package lock released.',
        package_id: 77001,
        package_no: 'PKG-001',
        previous_lock_owner_user_id: 'other.user',
        previous_lock_owner_role_code: 'LOGISTICS_MANAGER',
        released_by_user_id: 'kemar.logistics',
        released_at: '2026-04-07T15:45:00+00:00',
        lock_status: 'RELEASED',
        lock_expires_at: '2026-04-07T15:45:00+00:00',
      }),
    );
    const getPackageSpy = jasmine.createSpy('getPackage').and.returnValue(of(null));
    const getAllocationOptionsSpy = jasmine.createSpy('getAllocationOptions').and.returnValue(
      of({ request: null, items: [] } as unknown as AllocationOptionsResponse),
    );

    const operationsServiceStub: Partial<OperationsService> = {
      savePackageDraft: saveSpy,
      releasePackageLock: releaseSpy,
      getPackage: getPackageSpy,
      getAllocationOptions: getAllocationOptionsSpy,
    };

    TestBed.configureTestingModule({
      providers: [
        OperationsWorkspaceStateService,
        { provide: OperationsService, useValue: operationsServiceStub },
      ],
    });

    const service = TestBed.inject(OperationsWorkspaceStateService);
    service.reliefrqstId.set(RELIEFRQST_ID);
    return { service, saveSpy, releaseSpy, getPackageSpy, getAllocationOptionsSpy };
  }

  beforeEach(() => {
    TestBed.resetTestingModule();
  });

  it('saveDraft captures the lock conflict and re-throws the error', () => {
    const { service } = setUp();
    const caught: HttpErrorResponse[] = [];

    service.saveDraft().subscribe({
      next: () => fail('expected saveDraft to error on a lock conflict'),
      error: (error: HttpErrorResponse) => {
        caught.push(error);
      },
    });

    expect(caught.length).toBe(1);
    expect(caught[0].status).toBe(400);
    const conflict = service.lockConflict();
    expect(conflict).not.toBeNull();
    expect(conflict?.lock_owner_user_id).toBe('other.user');
    expect(conflict?.lock_owner_role_code).toBe('LOGISTICS_MANAGER');
  });

  it('captureLockConflict returns true and populates the signal for lock errors', () => {
    const { service } = setUp();

    const error = new HttpErrorResponse({
      status: 400,
      error: {
        errors: {
          lock: 'Package is locked by another fulfillment actor.',
          lock_owner_user_id: 'x',
        },
      },
    });

    expect(service.captureLockConflict(error)).toBeTrue();
    expect(service.lockConflict()?.lock_owner_user_id).toBe('x');
  });

  it('captureLockConflict returns false for non-lock errors and leaves the signal alone', () => {
    const { service } = setUp();

    const error = new HttpErrorResponse({
      status: 500,
      error: { message: 'boom' },
    });

    expect(service.captureLockConflict(error)).toBeFalse();
    expect(service.lockConflict()).toBeNull();
  });

  it('releasePackageLock(false) calls the service with force=false, clears lockConflict, and reloads on released=true', () => {
    const { service, releaseSpy, getPackageSpy } = setUp();
    // Pre-populate conflict so we can observe it being cleared.
    service.captureLockConflict(new HttpErrorResponse({
      status: 400,
      error: { errors: { lock: 'Locked.' } },
    }));
    expect(service.lockConflict()).not.toBeNull();

    service.releasePackageLock(false).subscribe();

    expect(releaseSpy).toHaveBeenCalledTimes(1);
    const [reliefrqstId, force] = releaseSpy.calls.mostRecent().args;
    expect(reliefrqstId).toBe(RELIEFRQST_ID);
    expect(force).toBe(false);
    expect(service.lockConflict()).toBeNull();
    expect(service.unlocking()).toBeFalse();
    // load() was triggered as a side-effect of released=true, which calls getPackage.
    expect(getPackageSpy).toHaveBeenCalled();
  });

  it('releasePackageLock(true) clears conflict on a no-op response without reloading', () => {
    const { service, releaseSpy, getPackageSpy } = setUp();
    releaseSpy.and.returnValue(of<PackageLockReleaseResponse>({
      released: false,
      message: 'No active package lock found for this package.',
      package_id: null,
      package_no: null,
      previous_lock_owner_user_id: null,
      previous_lock_owner_role_code: null,
      released_by_user_id: null,
      released_at: null,
      lock_status: null,
      lock_expires_at: null,
    }));
    service.captureLockConflict(new HttpErrorResponse({
      status: 400,
      error: { errors: { lock: 'Locked.' } },
    }));

    service.releasePackageLock(true).subscribe();

    expect(service.lockConflict()).toBeNull();
    // No-op response should NOT trigger a package reload.
    expect(getPackageSpy).not.toHaveBeenCalled();
  });
});
