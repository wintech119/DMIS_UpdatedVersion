import { HttpErrorResponse } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { Subject, of, throwError } from 'rxjs';

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
  ConsolidationLeg,
  PackageDetailResponse,
  PackageDraftPayload,
  PackageLockReleaseResponse,
  PackageSummary,
  RequestSummary,
  StagingRecommendationResponse,
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
      warehouse_cards: [],
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

  it('refreshes fully-issued state from the latest preview response', () => {
    const staleItem = buildItemGroup({
      issue_qty: '0',
      remaining_qty: '42',
      fully_issued: false,
    });
    const refreshedPreview = buildItemGroup({
      issue_qty: '42',
      remaining_qty: '0',
      fully_issued: true,
    });
    const { service } = setUp({
      item: staleItem,
      loadedWarehouses: [PRIMARY_WAREHOUSE_ID],
    });
    const previewSpy = TestBed.inject(OperationsService)
      .previewItemAllocationOptions as jasmine.Spy;
    previewSpy.and.returnValue(of(refreshedPreview));

    service.setCandidateQuantity(ITEM_ID, staleItem.candidates[0], 5);

    const updatedItem = service.options()?.items[0];
    expect(updatedItem?.issue_qty).toBe('42');
    expect(updatedItem?.remaining_qty).toBe('0');
    expect(updatedItem?.fully_issued).toBeTrue();
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

  it('does not fabricate a package source warehouse from a single-warehouse selection when the draft source is blank', () => {
    // Per-item warehouse selection is first-class in the stock-aware redesign —
    // the backend no longer expects a collapsed package-level source when the
    // user never picked one. Even if every selected row happens to come from
    // the same inventory_id, the payload must send source_warehouse_id
    // undefined so the backend keeps the package row at NULL.
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
    expect(payload.source_warehouse_id).toBeUndefined();
    expect(payload.allocations?.[0]?.inventory_id).toBe(9123);
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
      warehouse_cards: [],
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

  function stagingRecommendationResponse(): StagingRecommendationResponse {
    return {
      reliefrqst_id: RELIEFRQST_ID,
      recommended_staging_warehouse_id: 9501,
      recommended_staging_warehouse_name: 'ODPEM Staging Hub',
      recommended_staging_parish_code: '01',
      staging_selection_basis: 'SAME_PARISH',
      staging_hubs: [
        { warehouse_id: 9501, warehouse_name: 'ODPEM Staging Hub', parish_code: '01' },
      ],
    };
  }

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
            getStagingRecommendation: jasmine
              .createSpy('getStagingRecommendation')
              .and.returnValue(of(stagingRecommendationResponse())),
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

  it('includes the current staged fulfillment draft values in the commit payload', () => {
    TestBed.configureTestingModule({
      providers: [
        OperationsWorkspaceStateService,
        { provide: OperationsService, useValue: {} },
      ],
    });

    const service = TestBed.inject(OperationsWorkspaceStateService);
    service.patchDraft({
      source_warehouse_id: '9001',
      to_inventory_id: '9002',
      fulfillment_mode: 'DELIVER_FROM_STAGING',
      staging_warehouse_id: '9501',
      staging_override_reason: 'Use the manually selected hub',
    });
    service.selectedRowsByItem.set({
      44: [
        {
          item_id: 44,
          inventory_id: 9001,
          batch_id: 1001,
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
        fulfillment_mode: 'DELIVER_FROM_STAGING',
        staging_warehouse_id: 9501,
        staging_override_reason: 'Use the manually selected hub',
      }),
    );
  });

  it('keeps the current draft in place until the save succeeds', () => {
    const response$ = new Subject<PackageDetailResponse>();
    const saveSpy = jasmine.createSpy('savePackageDraft').and.returnValue(response$.asObservable());

    TestBed.configureTestingModule({
      providers: [
        OperationsWorkspaceStateService,
        {
          provide: OperationsService,
          useValue: {
            savePackageDraft: saveSpy,
            getConsolidationLegs: jasmine.createSpy('getConsolidationLegs').and.returnValue(
              of({ results: [], package: null }),
            ),
            getStagingRecommendation: jasmine
              .createSpy('getStagingRecommendation')
              .and.returnValue(of(stagingRecommendationResponse())),
          } satisfies Partial<OperationsService>,
        },
      ],
    });

    const service = TestBed.inject(OperationsWorkspaceStateService);
    service.reliefrqstId.set(RELIEFRQST_ID);
    service.patchDraft({
      fulfillment_mode: 'DIRECT',
      staging_warehouse_id: '',
      staging_override_reason: '',
    });

    service.saveFulfillmentModeDraft('PICKUP_AT_STAGING', 9501, 'Closer to field site').subscribe();

    expect(service.draft().fulfillment_mode).toBe('DIRECT');
    expect(service.draft().staging_warehouse_id).toBe('');
    expect(service.draft().staging_override_reason).toBe('');

    response$.next({
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
    });
    response$.complete();

    expect(service.draft().fulfillment_mode).toBe('PICKUP_AT_STAGING');
    expect(service.draft().staging_warehouse_id).toBe('9501');
    expect(service.draft().staging_override_reason).toBe('Closer to field site');
  });

  it('ignores in-flight consolidation leg loads after switching back to direct fulfillment', () => {
    const legsResponse$ = new Subject<{
      results: ConsolidationLeg[];
      package: PackageSummary | null;
    }>();
    const directResponse = {
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
        fulfillment_mode: 'DIRECT',
        staging_warehouse_id: null,
        staging_override_reason: null,
      },
      items: [],
      compatibility_only: false,
    } as PackageDetailResponse;
    const saveSpy = jasmine.createSpy('savePackageDraft').and.returnValue(of(directResponse));

    TestBed.configureTestingModule({
      providers: [
        OperationsWorkspaceStateService,
        {
          provide: OperationsService,
          useValue: {
            savePackageDraft: saveSpy,
            getConsolidationLegs: jasmine
              .createSpy('getConsolidationLegs')
              .and.returnValue(legsResponse$.asObservable()),
          } satisfies Partial<OperationsService>,
        },
      ],
    });

    const service = TestBed.inject(OperationsWorkspaceStateService);
    service.reliefrqstId.set(RELIEFRQST_ID);
    service.consolidationLegs.set([{ leg_id: 1 } as ConsolidationLeg]);

    service.loadConsolidationLegs(77001);
    service.saveFulfillmentModeDraft('DIRECT', null, null).subscribe();

    legsResponse$.next({
      results: [{ leg_id: 2 } as ConsolidationLeg],
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
        fulfillment_mode: 'DELIVER_FROM_STAGING',
        staging_warehouse_id: 9501,
        staging_override_reason: null,
      },
    });
    legsResponse$.complete();

    expect(service.consolidationLegs()).toEqual([]);
    expect(service.legsLoading()).toBeFalse();
    expect(service.packageDetail()?.package?.fulfillment_mode).toBe('DIRECT');
  });

  it('ignores stale fulfillment-mode save responses after the request context changes', () => {
    const response$ = new Subject<PackageDetailResponse>();
    const saveSpy = jasmine.createSpy('savePackageDraft').and.returnValue(response$.asObservable());

    TestBed.configureTestingModule({
      providers: [
        OperationsWorkspaceStateService,
        {
          provide: OperationsService,
          useValue: {
            savePackageDraft: saveSpy,
            getConsolidationLegs: jasmine.createSpy('getConsolidationLegs').and.returnValue(
              of({ results: [], package: null }),
            ),
          } satisfies Partial<OperationsService>,
        },
      ],
    });

    const service = TestBed.inject(OperationsWorkspaceStateService);
    service.reliefrqstId.set(RELIEFRQST_ID);

    service.saveFulfillmentModeDraft('PICKUP_AT_STAGING', 9501, 'Closer to field site').subscribe();
    service.reliefrqstId.set(RELIEFRQST_ID + 1);

    response$.next({
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
    });
    response$.complete();

    expect(service.packageDetail()).toBeNull();
    expect(service.reliefpkgId()).toBe(0);
    expect(service.draft().fulfillment_mode).toBe('');
  });

  it('ignores stale fulfillment-mode responses when a newer save completes first', () => {
    const firstResponse$ = new Subject<PackageDetailResponse>();
    const secondResponse$ = new Subject<PackageDetailResponse>();
    const saveSpy = jasmine
      .createSpy('savePackageDraft')
      .and.returnValues(firstResponse$.asObservable(), secondResponse$.asObservable());
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
            getStagingRecommendation: jasmine
              .createSpy('getStagingRecommendation')
              .and.returnValue(of(stagingRecommendationResponse())),
          } satisfies Partial<OperationsService>,
        },
      ],
    });

    const service = TestBed.inject(OperationsWorkspaceStateService);
    service.reliefrqstId.set(RELIEFRQST_ID);

    service.saveFulfillmentModeDraft('PICKUP_AT_STAGING', 9501, 'First warehouse').subscribe();
    service.saveFulfillmentModeDraft('DELIVER_FROM_STAGING', 9502, 'Second warehouse').subscribe();

    secondResponse$.next({
      request: { reliefrqst_id: RELIEFRQST_ID } as unknown as RequestSummary,
      package: {
        reliefpkg_id: 77002,
        tracking_no: 'PKG-002',
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
        fulfillment_mode: 'DELIVER_FROM_STAGING',
        staging_warehouse_id: 9502,
        staging_override_reason: 'Second warehouse',
      },
      items: [],
      compatibility_only: false,
    });
    secondResponse$.complete();

    firstResponse$.next({
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
        staging_override_reason: 'First warehouse',
      },
      items: [],
      compatibility_only: false,
    });
    firstResponse$.complete();

    expect(service.packageDetail()?.package?.reliefpkg_id).toBe(77002);
    expect(service.draft().fulfillment_mode).toBe('DELIVER_FROM_STAGING');
    expect(service.draft().staging_warehouse_id).toBe('9502');
    expect(service.draft().staging_override_reason).toBe('Second warehouse');
  });

  it('ignores stale fulfillment-mode save errors after a newer save starts', () => {
    const firstResponse$ = new Subject<PackageDetailResponse>();
    const secondResponse$ = new Subject<PackageDetailResponse>();
    const saveSpy = jasmine
      .createSpy('savePackageDraft')
      .and.returnValues(firstResponse$.asObservable(), secondResponse$.asObservable());

    TestBed.configureTestingModule({
      providers: [
        OperationsWorkspaceStateService,
        {
          provide: OperationsService,
          useValue: {
            savePackageDraft: saveSpy,
            getConsolidationLegs: jasmine.createSpy('getConsolidationLegs').and.returnValue(
              of({ results: [], package: null }),
            ),
          } satisfies Partial<OperationsService>,
        },
      ],
    });

    const service = TestBed.inject(OperationsWorkspaceStateService);
    service.reliefrqstId.set(RELIEFRQST_ID);
    service.patchDraft({
      fulfillment_mode: 'DIRECT',
      staging_warehouse_id: '',
      staging_override_reason: '',
    });

    let staleError: unknown = null;
    service.saveFulfillmentModeDraft('PICKUP_AT_STAGING', 9501, 'First warehouse').subscribe({
      error: (error) => {
        staleError = error;
      },
    });
    service.saveFulfillmentModeDraft('DELIVER_FROM_STAGING', 9502, 'Second warehouse').subscribe();

    firstResponse$.error(new HttpErrorResponse({
      status: 409,
      error: { detail: 'Stale failure' },
    }));

    expect(staleError).toBeNull();
    expect(service.draft().fulfillment_mode).toBe('DIRECT');
    expect(service.lockConflict()).toBeNull();
  });
});

describe('OperationsWorkspaceStateService.loadStagingRecommendation', () => {
  const RELIEFRQST_ID = 95009;

  beforeEach(() => {
    TestBed.resetTestingModule();
  });

  it('clears stale recommendations while loading and after errors', () => {
    const response$ = new Subject<StagingRecommendationResponse>();
    const getStagingRecommendationSpy = jasmine
      .createSpy('getStagingRecommendation')
      .and.returnValue(response$.asObservable());

    TestBed.configureTestingModule({
      providers: [
        OperationsWorkspaceStateService,
        {
          provide: OperationsService,
          useValue: {
            getStagingRecommendation: getStagingRecommendationSpy,
          } satisfies Partial<OperationsService>,
        },
      ],
    });

    const service = TestBed.inject(OperationsWorkspaceStateService);
    service.stagingRecommendation.set({
      reliefrqst_id: RELIEFRQST_ID,
      recommended_staging_warehouse_id: 9101,
      recommended_staging_warehouse_name: 'Old recommendation',
      recommended_staging_parish_code: '01',
      staging_selection_basis: null,
      staging_hubs: [],
    });

    service.loadStagingRecommendation(RELIEFRQST_ID);

    expect(service.stagingRecommendation()).toBeNull();
    expect(service.recommendationLoading()).toBeTrue();

    response$.error(new HttpErrorResponse({
      status: 500,
      error: { detail: 'Backend failure' },
    }));

    expect(service.stagingRecommendation()).toBeNull();
    expect(service.recommendationLoading()).toBeFalse();
    expect(service.recommendationError()).toContain('Backend failure');
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

  it('loads staging recommendation details when the package is already staged', () => {
    const packageDetail = buildPackageDetail();
    packageDetail.package!.fulfillment_mode = 'DELIVER_FROM_STAGING';
    const getPackageSpy = jasmine.createSpy('getPackage').and.returnValue(of(packageDetail));
    const getAllocationOptionsSpy = jasmine
      .createSpy('getAllocationOptions')
      .and.returnValue(of({ request: packageDetail.request, items: [] } as AllocationOptionsResponse));
    const getConsolidationLegsSpy = jasmine
      .createSpy('getConsolidationLegs')
      .and.returnValue(of({ package: packageDetail.package, results: [] }));
    const getStagingRecommendationSpy = jasmine
      .createSpy('getStagingRecommendation')
      .and.returnValue(of({
        reliefrqst_id: RELIEFRQST_ID,
        recommended_staging_warehouse_id: 9501,
        recommended_staging_warehouse_name: 'ODPEM Staging Hub',
        recommended_staging_parish_code: '01',
        staging_selection_basis: 'SAME_PARISH',
        staging_hubs: [
          { warehouse_id: 9501, warehouse_name: 'ODPEM Staging Hub', parish_code: '01' },
        ],
      } satisfies StagingRecommendationResponse));

    TestBed.configureTestingModule({
      providers: [
        OperationsWorkspaceStateService,
        {
          provide: OperationsService,
          useValue: {
            getPackage: getPackageSpy,
            getAllocationOptions: getAllocationOptionsSpy,
            getConsolidationLegs: getConsolidationLegsSpy,
            getStagingRecommendation: getStagingRecommendationSpy,
          } satisfies Partial<OperationsService>,
        },
      ],
    });

    const service = TestBed.inject(OperationsWorkspaceStateService);

    service.load(RELIEFRQST_ID, true);

    expect(getConsolidationLegsSpy).toHaveBeenCalledWith(77001);
    expect(getStagingRecommendationSpy).toHaveBeenCalledWith(RELIEFRQST_ID);
    expect(service.stagingRecommendation()?.staging_hubs).toEqual([
      { warehouse_id: 9501, warehouse_name: 'ODPEM Staging Hub', parish_code: '01' },
    ]);
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
          warehouse_cards: [],
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
          warehouse_cards: [],
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

  it('keeps the seeded warehouse primary when a draft committed to multiple warehouses including the seed', () => {
    const ITEM_ID = 101;
    const SECONDARY_WAREHOUSE_ID = 9002;
    const packageDetail = buildPackageDetail();
    packageDetail.allocation = {
      allocation_lines: [
        {
          item_id: ITEM_ID,
          inventory_id: SOURCE_WAREHOUSE_ID,
          batch_id: 3001,
          quantity: '1.0000',
          source_type: 'ON_HAND',
          source_record_id: null,
          uom_code: 'EA',
        },
        {
          item_id: ITEM_ID,
          inventory_id: SECONDARY_WAREHOUSE_ID,
          batch_id: 5001,
          quantity: '3.0000',
          source_type: 'ON_HAND',
          source_record_id: null,
          uom_code: 'EA',
        },
      ],
      reserved_stock_summary: { line_count: 2, total_qty: '4.0000' },
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
              usable_qty: '1',
              reserved_qty: '0',
              available_qty: '1',
              source_type: 'ON_HAND',
              can_expire_flag: false,
              issuance_order: 'FIFO',
              warehouse_name: 'Seeded Warehouse',
            },
            {
              batch_id: 5001,
              inventory_id: SECONDARY_WAREHOUSE_ID,
              item_id: ITEM_ID,
              usable_qty: '3',
              reserved_qty: '0',
              available_qty: '3',
              source_type: 'ON_HAND',
              can_expire_flag: false,
              issuance_order: 'FIFO',
              warehouse_name: 'Secondary Warehouse',
            },
          ],
          suggested_allocations: [],
          remaining_after_suggestion: '1.0000',
          can_expire_flag: false,
          issuance_order: 'FIFO',
          compliance_markers: [],
          override_required: false,
          source_warehouse_id: SOURCE_WAREHOUSE_ID,
          remaining_shortfall_qty: '1.0000',
          continuation_recommended: false,
          alternate_warehouses: [],
          warehouse_cards: [],
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

    // The seeded warehouse is still primary — a multi-warehouse expansion must not
    // be mistaken for a per-item override (fixes false OVERRIDDEN chip on reload).
    expect(service.itemWarehouseOverrides()).toEqual({});
    expect(service.effectiveWarehouseForItem(ITEM_ID)).toBe(String(SOURCE_WAREHOUSE_ID));
    expect(service.seededWarehousesByItem()[ITEM_ID]).toBe(String(SOURCE_WAREHOUSE_ID));
    expect(service.loadedWarehousesByItem()[ITEM_ID]).toEqual([
      SOURCE_WAREHOUSE_ID,
      SECONDARY_WAREHOUSE_ID,
    ]);
    expect(service.selectedRowsByItem()[ITEM_ID]).toEqual([
      jasmine.objectContaining({
        inventory_id: SOURCE_WAREHOUSE_ID,
        batch_id: 3001,
        quantity: '1.0000',
      }),
      jasmine.objectContaining({
        inventory_id: SECONDARY_WAREHOUSE_ID,
        batch_id: 5001,
        quantity: '3.0000',
      }),
    ]);
  });

  it('preserves the per-item override when the seeded warehouse is only a secondary committed source', () => {
    const ITEM_ID = 101;
    const OVERRIDE_WAREHOUSE_ID = 9002;
    const packageDetail = buildPackageDetail();
    packageDetail.package!.source_warehouse_id = 9900;
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
        {
          item_id: ITEM_ID,
          inventory_id: SOURCE_WAREHOUSE_ID,
          batch_id: 3001,
          quantity: '1.0000',
          source_type: 'ON_HAND',
          source_record_id: null,
          uom_code: 'EA',
        },
      ],
      reserved_stock_summary: { line_count: 2, total_qty: '4.0000' },
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
              batch_id: 5001,
              inventory_id: OVERRIDE_WAREHOUSE_ID,
              item_id: ITEM_ID,
              usable_qty: '3',
              reserved_qty: '0',
              available_qty: '3',
              source_type: 'ON_HAND',
              can_expire_flag: false,
              issuance_order: 'FIFO',
              warehouse_name: 'Override Warehouse',
            },
            {
              batch_id: 3001,
              inventory_id: SOURCE_WAREHOUSE_ID,
              item_id: ITEM_ID,
              usable_qty: '1',
              reserved_qty: '0',
              available_qty: '1',
              source_type: 'ON_HAND',
              can_expire_flag: false,
              issuance_order: 'FIFO',
              warehouse_name: 'Seeded Warehouse',
            },
          ],
          suggested_allocations: [],
          remaining_after_suggestion: '1.0000',
          can_expire_flag: false,
          issuance_order: 'FIFO',
          compliance_markers: [],
          override_required: false,
          source_warehouse_id: SOURCE_WAREHOUSE_ID,
          remaining_shortfall_qty: '1.0000',
          continuation_recommended: false,
          alternate_warehouses: [],
          warehouse_cards: [],
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
    expect(service.seededWarehousesByItem()[ITEM_ID]).toBe(String(SOURCE_WAREHOUSE_ID));
    expect(service.draft().source_warehouse_id).toBe('9900');
    expect(service.loadedWarehousesByItem()[ITEM_ID]).toEqual([
      OVERRIDE_WAREHOUSE_ID,
      SOURCE_WAREHOUSE_ID,
    ]);
  });

  it('resets per-item warehouse overrides back to the selected default warehouse', () => {
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
          suggested_allocations: [
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
          remaining_after_suggestion: '3.0000',
          can_expire_flag: false,
          issuance_order: 'FIFO',
          compliance_markers: [],
          override_required: false,
          source_warehouse_id: SOURCE_WAREHOUSE_ID,
          remaining_shortfall_qty: '3.0000',
          continuation_recommended: false,
          alternate_warehouses: [],
          warehouse_cards: [],
        },
      ],
    };
    const getPackageSpy = jasmine.createSpy('getPackage').and.returnValue(of(packageDetail));
    const getAllocationOptionsSpy = jasmine
      .createSpy('getAllocationOptions')
      .and.returnValues(of(optionsResponse), of(optionsResponse));

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

    service.resetWarehouseOverrides();

    expect(getAllocationOptionsSpy).toHaveBeenCalledWith(RELIEFRQST_ID, SOURCE_WAREHOUSE_ID);
    expect(service.itemWarehouseOverrides()).toEqual({});
    expect(service.effectiveWarehouseForItem(ITEM_ID)).toBe(String(SOURCE_WAREHOUSE_ID));
    expect(service.loadedWarehousesByItem()[ITEM_ID]).toEqual([SOURCE_WAREHOUSE_ID]);
    expect(service.selectedRowsByItem()[ITEM_ID]).toEqual([
      jasmine.objectContaining({
        item_id: ITEM_ID,
        inventory_id: SOURCE_WAREHOUSE_ID,
        batch_id: 3001,
        quantity: '2.0000',
      }),
    ]);
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
      warehouse_cards: [],
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

describe('OperationsWorkspaceStateService.extractReservationIntegrityWarning', () => {
  function createService(): OperationsWorkspaceStateService {
    TestBed.configureTestingModule({
      providers: [
        OperationsWorkspaceStateService,
        {
          provide: OperationsService,
          useValue: jasmine.createSpyObj<OperationsService>('OperationsService', [
            'previewItemAllocationOptions',
          ]),
        },
      ],
    });
    return TestBed.inject(OperationsWorkspaceStateService);
  }

  beforeEach(() => {
    TestBed.resetTestingModule();
  });

  it('maps the warehouse stock shortage response to a workflow integrity warning', () => {
    const service = createService();
    const error = new HttpErrorResponse({
      status: 409,
      error: {
        errors: {
          allocations: 'Insufficient warehouse stock for item 195 at inventory 1.',
        },
      },
    });

    expect(service.extractReservationIntegrityWarning(error)).toBe(
      'Warehouse stock data for item 195 at inventory 1 appears to be out of sync with the batch availability shown here. Refresh the workspace before trying again.',
    );
  });

  it('returns null for unrelated backend write errors', () => {
    const service = createService();
    const error = new HttpErrorResponse({
      status: 400,
      error: { errors: { allocations: 'Select at least one stock line to reserve.' } },
    });

    expect(service.extractReservationIntegrityWarning(error)).toBeNull();
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
      warehouse_cards: [],
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

  it('refreshes fully-issued state when the additive warehouse preview is merged back', () => {
    const additivePreview = buildItemGroup({
      issue_qty: '6.0000',
      remaining_qty: '0.0000',
      fully_issued: true,
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
      draft_selected_qty: '6.0000',
      effective_remaining_qty: '0.0000',
      remaining_shortfall_qty: '0.0000',
      continuation_recommended: false,
      alternate_warehouses: [],
    });
    const refreshPreview = buildItemGroup({
      issue_qty: '6.0000',
      remaining_qty: '0.0000',
      fully_issued: true,
      draft_selected_qty: '6.0000',
      effective_remaining_qty: '0.0000',
      remaining_shortfall_qty: '0.0000',
      continuation_recommended: false,
      alternate_warehouses: [],
    });
    const previewSpy = jasmine
      .createSpy('previewItemAllocationOptions')
      .and.returnValues(of(additivePreview), of(refreshPreview));

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
      items: [
        buildItemGroup({
          issue_qty: '4.0000',
          remaining_qty: '2.0000',
          fully_issued: false,
        }),
      ],
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

    const updatedItem = service.options()?.items[0];
    expect(updatedItem?.issue_qty).toBe('6.0000');
    expect(updatedItem?.remaining_qty).toBe('0.0000');
    expect(updatedItem?.fully_issued).toBeTrue();
  });

  it('preserves stock_integrity_issue after the follow-up preview refresh runs for an added warehouse', () => {
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
      remaining_after_suggestion: '0.0000',
      remaining_shortfall_qty: '0.0000',
      continuation_recommended: false,
      alternate_warehouses: [],
      draft_selected_qty: '6.0000',
      effective_remaining_qty: '0.0000',
      stock_integrity_issue: null,
    });
    const refreshedPreview = buildItemGroup({
      source_warehouse_id: SECONDARY_WAREHOUSE_ID,
      remaining_after_suggestion: '0.0000',
      remaining_shortfall_qty: '0.0000',
      continuation_recommended: false,
      alternate_warehouses: [],
      draft_selected_qty: '6.0000',
      effective_remaining_qty: '0.0000',
      stock_integrity_issue:
        'Warehouse stock totals are out of sync for item 44 at inventory 9002. Reconcile warehouse inventory before committing this reservation.',
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

    const updatedItem = service.options()?.items[0];
    expect(updatedItem?.stock_integrity_issue).toContain('Warehouse stock totals are out of sync');
    expect(service.getItemValidationMessage(updatedItem!)).toContain('Reconcile warehouse inventory');
  });
});

describe('OperationsWorkspaceStateService lock conflict interception', () => {
  const RELIEFRQST_ID = 95009;
  const RELIEFPKG_ID = 77001;
  const SOURCE_WAREHOUSE_ID = 9001;
  const ITEM_ID = 44;

  function buildReloadPackageDetail(): PackageDetailResponse {
    return {
      request: {
        reliefrqst_id: RELIEFRQST_ID,
        tracking_no: 'REQ-95009',
        agency_id: 1,
        agency_name: 'ODPEM',
        eligible_event_id: null,
        event_name: null,
        urgency_ind: 'H',
        status_code: 'APPROVED_FOR_FULFILLMENT',
        status_label: 'Approved for Fulfillment',
        request_date: '2026-04-07T12:00:00+00:00',
        create_dtime: '2026-04-07T12:00:00+00:00',
        review_dtime: null,
        action_dtime: '2026-04-07T12:15:00+00:00',
        rqst_notes_text: null,
        review_notes_text: null,
        status_reason_desc: null,
        version_nbr: 1,
        item_count: 1,
        total_requested_qty: '10.0000',
        total_issued_qty: '0.0000',
        reliefpkg_id: RELIEFPKG_ID,
        package_tracking_no: 'PKG-001',
        package_status: 'DRAFT',
        execution_status: null,
        needs_list_id: null,
        compatibility_bridge: false,
        request_mode: 'SELF',
        authority_context: null,
        requesting_tenant_id: null,
        requesting_agency_id: null,
        beneficiary_tenant_id: null,
        beneficiary_agency_id: null,
      },
      package: {
        reliefpkg_id: RELIEFPKG_ID,
        tracking_no: 'PKG-001',
        reliefrqst_id: RELIEFRQST_ID,
        agency_id: 1,
        eligible_event_id: null,
        source_warehouse_id: SOURCE_WAREHOUSE_ID,
        to_inventory_id: 9002,
        destination_warehouse_name: 'Kingston Warehouse',
        status_code: 'DRAFT',
        status_label: 'Draft',
        dispatch_dtime: null,
        received_dtime: null,
        transport_mode: 'TRUCK',
        comments_text: 'Reload after releasing package lock.',
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

  function buildReloadAllocationOptions(): AllocationOptionsResponse {
    return {
      request: buildReloadPackageDetail().request,
      items: [
        {
          item_id: ITEM_ID,
          item_code: 'WATER-044',
          item_name: 'Portable Water Container',
          request_qty: '10.0000',
          issue_qty: '0.0000',
          remaining_qty: '10.0000',
          urgency_ind: 'H',
          candidates: [
            {
              batch_id: 1001,
              inventory_id: SOURCE_WAREHOUSE_ID,
              item_id: ITEM_ID,
              usable_qty: '10.0000',
              reserved_qty: '0.0000',
              available_qty: '10.0000',
              source_type: 'ON_HAND',
              warehouse_name: 'Kingston Warehouse',
              can_expire_flag: false,
              issuance_order: 'FIFO',
            },
          ],
          suggested_allocations: [],
          remaining_after_suggestion: '10.0000',
          can_expire_flag: false,
          issuance_order: 'FIFO',
          compliance_markers: [],
          override_required: false,
          source_warehouse_id: SOURCE_WAREHOUSE_ID,
          remaining_shortfall_qty: '0.0000',
          continuation_recommended: false,
          alternate_warehouses: [],
          warehouse_cards: [],
        },
      ],
    };
  }

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
    const getPackageSpy = jasmine.createSpy('getPackage').and.returnValue(of(buildReloadPackageDetail()));
    const getAllocationOptionsSpy = jasmine
      .createSpy('getAllocationOptions')
      .and.returnValue(of(buildReloadAllocationOptions()));

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

describe('OperationsWorkspaceStateService.getItemValidationMessage (fully_issued)', () => {
  const ITEM_ID = 101;
  const WAREHOUSE_ID = 9001;

  function buildCandidate(): AllocationCandidate {
    return {
      batch_id: 1,
      inventory_id: WAREHOUSE_ID,
      item_id: ITEM_ID,
      batch_no: 'HADR-2-58',
      usable_qty: '1000',
      reserved_qty: '0',
      available_qty: '1000',
      source_type: 'ON_HAND',
      can_expire_flag: false,
      issuance_order: 'FIFO',
    };
  }

  function buildItemGroup(overrides: Partial<AllocationItemGroup> = {}): AllocationItemGroup {
    return {
      item_id: ITEM_ID,
      item_code: 'HADR-0058',
      item_name: 'Battery AA',
      request_qty: '40',
      issue_qty: '40',
      remaining_qty: '0',
      fully_issued: true,
      urgency_ind: 'H',
      candidates: [buildCandidate()],
      suggested_allocations: [],
      remaining_after_suggestion: '0',
      can_expire_flag: false,
      issuance_order: 'FIFO',
      compliance_markers: [],
      override_required: false,
      source_warehouse_id: WAREHOUSE_ID,
      remaining_shortfall_qty: '0',
      continuation_recommended: false,
      alternate_warehouses: [],
      warehouse_cards: [],
      ...overrides,
    };
  }

  function makeService(): OperationsWorkspaceStateService {
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      providers: [
        OperationsWorkspaceStateService,
        { provide: OperationsService, useValue: {} as Partial<OperationsService> },
      ],
    });
    return TestBed.inject(OperationsWorkspaceStateService);
  }

  it('returns null when the item is fully_issued AND no selection was made', () => {
    const service = makeService();
    const item = buildItemGroup();

    expect(service.getItemValidationMessage(item)).toBeNull();
  });

  it('returns a dedicated "already fully issued" message when the operator tries to reserve against a fully_issued item', () => {
    const service = makeService();
    const item = buildItemGroup();
    service.options.set({
      request: { reliefrqst_id: 7001 } as unknown as RequestSummary,
      items: [item],
    });
    service.setCandidateQuantity(ITEM_ID, item.candidates[0], 10);

    const message = service.getItemValidationMessage(item);

    expect(message).not.toBeNull();
    expect(message).toContain('already fully issued');
    // Regression guard: the old misleading message must NOT fire for fully_issued items.
    expect(message).not.toContain('more than the item still needs');
  });

  it('still returns the over-allocated message for normal (non-fully_issued) items when reserving exceeds remaining', () => {
    const service = makeService();
    const item = buildItemGroup({
      issue_qty: '0',
      remaining_qty: '5',
      fully_issued: false,
    });
    service.options.set({
      request: { reliefrqst_id: 7001 } as unknown as RequestSummary,
      items: [item],
    });
    service.setCandidateQuantity(ITEM_ID, item.candidates[0], 10);

    const message = service.getItemValidationMessage(item);

    expect(message).toBe('You cannot allocate more than the item still needs.');
  });

  it('returns the stock integrity issue when the source warehouse aggregate is out of sync', () => {
    const service = makeService();
    const item = buildItemGroup({
      issue_qty: '0',
      remaining_qty: '5',
      fully_issued: false,
      stock_integrity_issue:
        'Warehouse stock totals are out of sync for item 101 at inventory 9001. Reconcile warehouse inventory before committing this reservation.',
    });

    const message = service.getItemValidationMessage(item);

    expect(message).toContain('Warehouse stock totals are out of sync');
    expect(message).toContain('Reconcile warehouse inventory');
  });
});

describe('OperationsWorkspaceStateService.setItemWarehouseQty (FR05.06 redesign)', () => {
  const ITEM_ID = 101;
  const WAREHOUSE_ID = 9001;

  function buildItem(overrides: Partial<AllocationItemGroup> = {}): AllocationItemGroup {
    return {
      item_id: ITEM_ID,
      item_code: 'WATER-101',
      item_name: 'Water Container',
      request_qty: '50',
      issue_qty: '0',
      remaining_qty: '50',
      urgency_ind: 'H',
      candidates: [
        {
          batch_id: 1,
          inventory_id: WAREHOUSE_ID,
          item_id: ITEM_ID,
          usable_qty: '30',
          reserved_qty: '0',
          available_qty: '30',
          source_type: 'ON_HAND',
          can_expire_flag: false,
          issuance_order: 'FIFO',
          batch_no: 'BT-1',
        },
        {
          batch_id: 2,
          inventory_id: WAREHOUSE_ID,
          item_id: ITEM_ID,
          usable_qty: '40',
          reserved_qty: '0',
          available_qty: '40',
          source_type: 'ON_HAND',
          can_expire_flag: false,
          issuance_order: 'FIFO',
          batch_no: 'BT-2',
        },
      ],
      suggested_allocations: [],
      remaining_after_suggestion: '50',
      can_expire_flag: false,
      issuance_order: 'FIFO',
      compliance_markers: [],
      override_required: false,
      remaining_shortfall_qty: '50',
      continuation_recommended: false,
      alternate_warehouses: [],
      warehouse_cards: [
        {
          warehouse_id: WAREHOUSE_ID,
          warehouse_name: 'Kingston',
          rank: 0,
          issuance_order: 'FIFO',
          total_available: '70',
          allocatable_available_qty: '70',
          suggested_qty: '50',
          batches: [
            {
              batch_id: 1,
              inventory_id: WAREHOUSE_ID,
              batch_no: 'BT-1',
              batch_date: null,
              expiry_date: null,
              available_qty: '30',
              usable_qty: '30',
              reserved_qty: '0',
              uom_code: 'EA',
              source_type: 'ON_HAND',
              source_record_id: null,
            },
            {
              batch_id: 2,
              inventory_id: WAREHOUSE_ID,
              batch_no: 'BT-2',
              batch_date: null,
              expiry_date: null,
              available_qty: '40',
              usable_qty: '40',
              reserved_qty: '0',
              uom_code: 'EA',
              source_type: 'ON_HAND',
              source_record_id: null,
            },
          ],
        },
      ],
      ...overrides,
    };
  }

  function makeService(): OperationsWorkspaceStateService {
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      providers: [
        OperationsWorkspaceStateService,
        {
          provide: OperationsService,
          useValue: {
            previewItemAllocationOptions: jasmine
              .createSpy('previewItemAllocationOptions')
              .and.returnValue(of(buildItem())),
          } as Partial<OperationsService>,
        },
      ],
    });
    const service = TestBed.inject(OperationsWorkspaceStateService);
    service.reliefrqstId.set(7001);
    service.options.set({
      request: { reliefrqst_id: 7001 } as unknown as RequestSummary,
      items: [buildItem()],
    });
    return service;
  }

  it('greedily distributes qty across ranked batches in FEFO/FIFO order', () => {
    const service = makeService();
    service.setItemWarehouseQty(ITEM_ID, WAREHOUSE_ID, 45);

    const rows = service.selectedRowsByItem()[ITEM_ID] ?? [];
    // First batch takes 30 (its full per-batch cap), second batch takes 15.
    expect(rows.length).toBe(2);
    const row1 = rows.find((r) => r.batch_id === 1);
    const row2 = rows.find((r) => r.batch_id === 2);
    expect(Number(row1?.quantity)).toBe(30);
    expect(Number(row2?.quantity)).toBe(15);
  });

  it('clamps qty to the card-level allocatable_available_qty cap', () => {
    const service = makeService();
    service.setItemWarehouseQty(ITEM_ID, WAREHOUSE_ID, 200);

    const total = service.getItemWarehouseAllocatedQty(ITEM_ID, WAREHOUSE_ID);
    // Cap is 70 (allocatable_available_qty); 200 clamps down.
    expect(total).toBe(70);
  });

  it('tail-releases prior batch allocations when qty shrinks', () => {
    const service = makeService();
    service.setItemWarehouseQty(ITEM_ID, WAREHOUSE_ID, 45);
    expect(service.getItemWarehouseAllocatedQty(ITEM_ID, WAREHOUSE_ID)).toBe(45);

    service.setItemWarehouseQty(ITEM_ID, WAREHOUSE_ID, 10);
    const rows = service.selectedRowsByItem()[ITEM_ID] ?? [];
    const row2 = rows.find((r) => r.batch_id === 2);
    expect(service.getItemWarehouseAllocatedQty(ITEM_ID, WAREHOUSE_ID)).toBe(10);
    // Tail batch must be zero now, not lingering.
    expect(row2 ? Number(row2.quantity) : 0).toBe(0);
  });

  it('rejects negative qty without mutating state', () => {
    const service = makeService();
    service.setItemWarehouseQty(ITEM_ID, WAREHOUSE_ID, 30);
    const before = service.getItemWarehouseAllocatedQty(ITEM_ID, WAREHOUSE_ID);

    const warnSpy = spyOn(console, 'warn');
    service.setItemWarehouseQty(ITEM_ID, WAREHOUSE_ID, -5);

    expect(service.getItemWarehouseAllocatedQty(ITEM_ID, WAREHOUSE_ID)).toBe(before);
    expect(warnSpy).toHaveBeenCalled();
  });

  it('accepts decimal qty up to 4 decimal places and normalizes precision', () => {
    const service = makeService();
    const warnSpy = spyOn(console, 'warn');
    service.setItemWarehouseQty(ITEM_ID, WAREHOUSE_ID, 12.5);

    expect(service.getItemWarehouseAllocatedQty(ITEM_ID, WAREHOUSE_ID)).toBe(12.5);
    expect(warnSpy).not.toHaveBeenCalled();

    service.setItemWarehouseQty(ITEM_ID, WAREHOUSE_ID, 1.2345);
    expect(service.getItemWarehouseAllocatedQty(ITEM_ID, WAREHOUSE_ID)).toBe(1.2345);
  });

  it('rejects qty with more than 4 decimal places without mutating state', () => {
    const service = makeService();
    service.setItemWarehouseQty(ITEM_ID, WAREHOUSE_ID, 10);
    const before = service.getItemWarehouseAllocatedQty(ITEM_ID, WAREHOUSE_ID);

    const warnSpy = spyOn(console, 'warn');
    service.setItemWarehouseQty(ITEM_ID, WAREHOUSE_ID, 1.23456);

    expect(service.getItemWarehouseAllocatedQty(ITEM_ID, WAREHOUSE_ID)).toBe(before);
    expect(warnSpy).toHaveBeenCalled();
  });

  it('rejects non-finite qty without mutating state', () => {
    const service = makeService();
    const warnSpy = spyOn(console, 'warn');
    service.setItemWarehouseQty(ITEM_ID, WAREHOUSE_ID, Number.NaN);

    expect(service.getItemWarehouseAllocatedQty(ITEM_ID, WAREHOUSE_ID)).toBe(0);
    expect(warnSpy).toHaveBeenCalled();

    service.setItemWarehouseQty(ITEM_ID, WAREHOUSE_ID, Number.POSITIVE_INFINITY);
    expect(service.getItemWarehouseAllocatedQty(ITEM_ID, WAREHOUSE_ID)).toBe(0);
  });

  it('zeroes all allocations for a warehouse when called with qty=0', () => {
    const service = makeService();
    service.setItemWarehouseQty(ITEM_ID, WAREHOUSE_ID, 45);
    expect(service.getItemWarehouseAllocatedQty(ITEM_ID, WAREHOUSE_ID)).toBe(45);

    service.setItemWarehouseQty(ITEM_ID, WAREHOUSE_ID, 0);
    expect(service.getItemWarehouseAllocatedQty(ITEM_ID, WAREHOUSE_ID)).toBe(0);
  });

  it('refreshes continuation preview once after batch distribution', () => {
    const previewSpy = jasmine
      .createSpy('previewItemAllocationOptions')
      .and.returnValue(of(buildItem({ continuation_recommended: true })));

    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      providers: [
        OperationsWorkspaceStateService,
        {
          provide: OperationsService,
          useValue: {
            previewItemAllocationOptions: previewSpy,
          } as Partial<OperationsService>,
        },
      ],
    });

    const service = TestBed.inject(OperationsWorkspaceStateService);
    service.reliefrqstId.set(7001);
    service.loadedWarehousesByItem.set({ [ITEM_ID]: [WAREHOUSE_ID] });
    service.options.set({
      request: { reliefrqst_id: 7001 } as unknown as RequestSummary,
      items: [buildItem({ continuation_recommended: true })],
    });

    service.setItemWarehouseQty(ITEM_ID, WAREHOUSE_ID, 45);

    expect(previewSpy).toHaveBeenCalledTimes(1);
  });

  it('preserves the full source identity when a batch key collides across sources', () => {
    const service = makeService();
    const item = buildItem({
      candidates: [
        {
          batch_id: 1,
          inventory_id: WAREHOUSE_ID,
          item_id: ITEM_ID,
          usable_qty: '30',
          reserved_qty: '0',
          available_qty: '30',
          source_type: 'TRANSFER',
          source_record_id: 77,
          can_expire_flag: false,
          issuance_order: 'FIFO',
          batch_no: 'BT-1-XFER',
        },
        {
          batch_id: 1,
          inventory_id: WAREHOUSE_ID,
          item_id: ITEM_ID,
          usable_qty: '30',
          reserved_qty: '0',
          available_qty: '30',
          source_type: 'ON_HAND',
          source_record_id: null,
          can_expire_flag: false,
          issuance_order: 'FIFO',
          batch_no: 'BT-1',
        },
      ],
    });
    service.options.set({
      request: { reliefrqst_id: 7001 } as unknown as RequestSummary,
      items: [item],
    });

    service.setItemWarehouseQty(ITEM_ID, WAREHOUSE_ID, 10);

    const rows = service.selectedRowsByItem()[ITEM_ID] ?? [];
    expect(rows.length).toBe(1);
    expect(rows[0].source_type).toBe('ON_HAND');
    expect(rows[0].source_record_id).toBeNull();
  });

  describe('removeItemWarehouse (FR05.06 kebab-menu redesign)', () => {
    it('removes draft selections, drops the loaded tracker entry, strips the rank card, and clears stale preview fields', () => {
      const service = makeService();
      service.loadedWarehousesByItem.set({ [ITEM_ID]: [WAREHOUSE_ID] });
      service.addingWarehouseByItem.set({ [ITEM_ID]: true });
      service.options.set({
        request: { reliefrqst_id: 7001 } as unknown as RequestSummary,
        items: [
          buildItem({
            continuation_recommended: true,
            remaining_shortfall_qty: '5',
            alternate_warehouses: [{
              warehouse_id: 9999,
              warehouse_name: 'Spanish Town',
              available_qty: '5',
              suggested_qty: '5',
              can_fully_cover: false,
            }],
            draft_selected_qty: '45.0000',
            effective_remaining_qty: '5.0000',
            stock_integrity_issue:
              'Warehouse stock totals are out of sync for item 101 at inventory 9001.',
          }),
        ],
      });
      service.setItemWarehouseQty(ITEM_ID, WAREHOUSE_ID, 45);
      expect(service.getItemWarehouseAllocatedQty(ITEM_ID, WAREHOUSE_ID)).toBe(45);

      service.removeItemWarehouse(ITEM_ID, WAREHOUSE_ID);

      // Draft selections cleared
      expect(service.selectedRowsByItem()[ITEM_ID]).toEqual([]);
      // Loaded tracker no longer lists the removed warehouse
      expect(service.loadedWarehousesByItem()[ITEM_ID] ?? []).toEqual([]);
      expect(service.addingWarehouseByItem()[ITEM_ID]).toBeFalse();
      // warehouse_cards + candidates filtered in the cached options
      const item = service
        .options()
        ?.items.find((entry) => entry.item_id === ITEM_ID);
      expect(item?.warehouse_cards ?? []).toEqual([]);
      expect(item?.candidates.filter((c) => c.inventory_id === WAREHOUSE_ID)).toEqual([]);
      expect(item?.continuation_recommended).toBeFalse();
      expect(item?.alternate_warehouses ?? []).toEqual([]);
      expect(item?.draft_selected_qty).toBe('0.0000');
      expect(item?.effective_remaining_qty).toBe('50');
      expect(item?.remaining_shortfall_qty).toBe('50');
      expect(item?.stock_integrity_issue).toBeNull();
    });

    it('is a no-op when warehouseId is 0 / negative / missing', () => {
      const service = makeService();
      service.setItemWarehouseQty(ITEM_ID, WAREHOUSE_ID, 20);
      const before = service.getItemWarehouseAllocatedQty(ITEM_ID, WAREHOUSE_ID);

      service.removeItemWarehouse(ITEM_ID, 0);
      service.removeItemWarehouse(ITEM_ID, -5);

      expect(service.getItemWarehouseAllocatedQty(ITEM_ID, WAREHOUSE_ID)).toBe(before);
      expect(service.selectedRowsByItem()[ITEM_ID]?.length).toBeGreaterThan(0);
    });

    it('clears the per-item override when the removed warehouse matches the override', () => {
      const service = makeService();
      service.itemWarehouseOverrides.set({ [ITEM_ID]: String(WAREHOUSE_ID) });

      service.removeItemWarehouse(ITEM_ID, WAREHOUSE_ID);

      expect(service.itemWarehouseOverrides()[ITEM_ID]).toBeUndefined();
    });

    it('preserves the per-item override when a different warehouse is removed', () => {
      const service = makeService();
      service.itemWarehouseOverrides.set({ [ITEM_ID]: '9999' });

      service.removeItemWarehouse(ITEM_ID, WAREHOUSE_ID);

      expect(service.itemWarehouseOverrides()[ITEM_ID]).toBe('9999');
    });

    it('invalidates an in-flight preview so stale warehouse cards do not merge back in', () => {
      const preview$ = new Subject<AllocationItemGroup>();

      TestBed.resetTestingModule();
      TestBed.configureTestingModule({
        providers: [
          OperationsWorkspaceStateService,
          {
            provide: OperationsService,
            useValue: {
              previewItemAllocationOptions: jasmine
                .createSpy('previewItemAllocationOptions')
                .and.returnValue(preview$.asObservable()),
            } as Partial<OperationsService>,
          },
        ],
      });

      const service = TestBed.inject(OperationsWorkspaceStateService);
      service.reliefrqstId.set(7001);
      service.loadedWarehousesByItem.set({ [ITEM_ID]: [WAREHOUSE_ID] });
      service.options.set({
        request: { reliefrqst_id: 7001 } as unknown as RequestSummary,
        items: [buildItem()],
      });

      service.previewItemAllocations(ITEM_ID, WAREHOUSE_ID);
      expect(service.previewLoadingByItem()[ITEM_ID]).toBeTrue();

      service.removeItemWarehouse(ITEM_ID, WAREHOUSE_ID);
      expect(service.previewLoadingByItem()[ITEM_ID]).toBeFalse();

      preview$.next(buildItem());

      const item = service.options()?.items.find((entry) => entry.item_id === ITEM_ID);
      expect(item?.warehouse_cards ?? []).toEqual([]);
      expect(item?.candidates.filter((candidate) => candidate.inventory_id === WAREHOUSE_ID)).toEqual([]);
    });

    it('requests a fresh preview against the remaining warehouse after removal', () => {
      const secondaryWarehouseId = 9002;
      const previewSpy = jasmine
        .createSpy('previewItemAllocationOptions')
        .and.returnValue(of(buildItem({
          source_warehouse_id: secondaryWarehouseId,
          candidates: [
            {
              batch_id: 3,
              inventory_id: secondaryWarehouseId,
              item_id: ITEM_ID,
              usable_qty: '20',
              reserved_qty: '0',
              available_qty: '20',
              source_type: 'ON_HAND',
              source_record_id: null,
              can_expire_flag: false,
              issuance_order: 'FIFO',
            },
          ],
          warehouse_cards: [
            {
              warehouse_id: secondaryWarehouseId,
              warehouse_name: 'Montego Bay',
              rank: 0,
              issuance_order: 'FIFO',
              total_available: '20',
              allocatable_available_qty: '20',
              suggested_qty: '20',
              batches: [
                {
                  batch_id: 3,
                  inventory_id: secondaryWarehouseId,
                  batch_no: 'BT-3',
                  batch_date: null,
                  expiry_date: null,
                  available_qty: '20',
                  usable_qty: '20',
                  reserved_qty: '0',
                  uom_code: 'EA',
                  source_type: 'ON_HAND',
                  source_record_id: null,
                },
              ],
            },
          ],
        })));

      TestBed.resetTestingModule();
      TestBed.configureTestingModule({
        providers: [
          OperationsWorkspaceStateService,
          {
            provide: OperationsService,
            useValue: {
              previewItemAllocationOptions: previewSpy,
            } as Partial<OperationsService>,
          },
        ],
      });

      const service = TestBed.inject(OperationsWorkspaceStateService);
      service.reliefrqstId.set(7001);
      service.loadedWarehousesByItem.set({ [ITEM_ID]: [WAREHOUSE_ID, secondaryWarehouseId] });
      service.options.set({
        request: { reliefrqst_id: 7001 } as unknown as RequestSummary,
        items: [
          buildItem({
            source_warehouse_id: WAREHOUSE_ID,
            selected_warehouse_ids: [WAREHOUSE_ID, secondaryWarehouseId],
            candidates: [
              ...buildItem().candidates,
              {
                batch_id: 3,
                inventory_id: secondaryWarehouseId,
                item_id: ITEM_ID,
                usable_qty: '20',
                reserved_qty: '0',
                available_qty: '20',
                source_type: 'ON_HAND',
                source_record_id: null,
                can_expire_flag: false,
                issuance_order: 'FIFO',
              },
            ],
            warehouse_cards: [
              ...buildItem().warehouse_cards,
              {
                warehouse_id: secondaryWarehouseId,
                warehouse_name: 'Montego Bay',
                rank: 1,
                issuance_order: 'FIFO',
                total_available: '20',
                allocatable_available_qty: '20',
                suggested_qty: '20',
                batches: [
                  {
                    batch_id: 3,
                    inventory_id: secondaryWarehouseId,
                    batch_no: 'BT-3',
                    batch_date: null,
                    expiry_date: null,
                    available_qty: '20',
                    usable_qty: '20',
                    reserved_qty: '0',
                    uom_code: 'EA',
                    source_type: 'ON_HAND',
                    source_record_id: null,
                  },
                ],
              },
            ],
          }),
        ],
      });

      service.removeItemWarehouse(ITEM_ID, WAREHOUSE_ID);

      expect(previewSpy).toHaveBeenCalledOnceWith(
        7001,
        ITEM_ID,
        jasmine.objectContaining({ source_warehouse_id: secondaryWarehouseId }),
      );
    });
  });
});

describe('OperationsWorkspaceStateService.getItemFillStatus (FR05.06 redesign)', () => {
  const ITEM_ID = 101;

  function buildItem(overrides: Partial<AllocationItemGroup> = {}): AllocationItemGroup {
    return {
      item_id: ITEM_ID,
      item_code: 'WATER-101',
      item_name: 'Water Container',
      request_qty: '50',
      issue_qty: '0',
      remaining_qty: '50',
      urgency_ind: 'H',
      candidates: [
        {
          batch_id: 1,
          inventory_id: 9001,
          item_id: ITEM_ID,
          usable_qty: '100',
          reserved_qty: '0',
          available_qty: '100',
          source_type: 'ON_HAND',
          can_expire_flag: false,
          issuance_order: 'FIFO',
        },
      ],
      suggested_allocations: [],
      remaining_after_suggestion: '50',
      can_expire_flag: false,
      issuance_order: 'FIFO',
      compliance_markers: [],
      override_required: false,
      remaining_shortfall_qty: '50',
      continuation_recommended: false,
      alternate_warehouses: [],
      warehouse_cards: [],
      ...overrides,
    };
  }

  function makeService(item: AllocationItemGroup): OperationsWorkspaceStateService {
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      providers: [
        OperationsWorkspaceStateService,
        { provide: OperationsService, useValue: {} as Partial<OperationsService> },
      ],
    });
    const service = TestBed.inject(OperationsWorkspaceStateService);
    service.reliefrqstId.set(7001);
    service.options.set({
      request: { reliefrqst_id: 7001 } as unknown as RequestSummary,
      items: [item],
    });
    return service;
  }

  it('returns draft when reserving qty is zero', () => {
    const service = makeService(buildItem());
    expect(service.getItemFillStatus(ITEM_ID)).toBe('draft');
  });

  it('returns filled when reserving >= remaining', () => {
    const item = buildItem();
    const service = makeService(item);
    service.setCandidateQuantity(ITEM_ID, item.candidates[0], 50);
    expect(service.getItemFillStatus(ITEM_ID)).toBe('filled');
  });

  it('returns non_compliant when reserving exists against a zero remaining quantity', () => {
    const item = buildItem({ remaining_qty: '0' });
    const service = makeService(item);
    service.setCandidateQuantity(ITEM_ID, item.candidates[0], 1);
    expect(service.getItemFillStatus(ITEM_ID)).toBe('non_compliant');
  });

  it('returns compliant_partial when reserving > 0 and < remaining with no override flags', () => {
    const item = buildItem();
    const service = makeService(item);
    service.setCandidateQuantity(ITEM_ID, item.candidates[0], 20);
    expect(service.getItemFillStatus(ITEM_ID)).toBe('compliant_partial');
  });

  it('returns non_compliant (precedence) when item.override_required is true, even with full allocation', () => {
    const item = buildItem({ override_required: true });
    const service = makeService(item);
    service.setCandidateQuantity(ITEM_ID, item.candidates[0], 50);
    expect(service.getItemFillStatus(ITEM_ID)).toBe('non_compliant');
  });

  it('returns non_compliant when rule is bypassed via skipping the greedy recommendation', () => {
    // Two candidates: greedy would fill from candidate[0] (50 available)
    // but the operator skips directly to candidate[1] — that counts as bypass.
    const item = buildItem({
      request_qty: '20',
      remaining_qty: '20',
      candidates: [
        {
          batch_id: 1,
          inventory_id: 9001,
          item_id: ITEM_ID,
          usable_qty: '100',
          reserved_qty: '0',
          available_qty: '100',
          source_type: 'ON_HAND',
          can_expire_flag: false,
          issuance_order: 'FIFO',
        },
        {
          batch_id: 2,
          inventory_id: 9001,
          item_id: ITEM_ID,
          usable_qty: '100',
          reserved_qty: '0',
          available_qty: '100',
          source_type: 'ON_HAND',
          can_expire_flag: false,
          issuance_order: 'FIFO',
        },
      ],
    });
    const service = makeService(item);
    // Allocate from the second candidate only — greedy would have picked the first.
    service.setCandidateQuantity(ITEM_ID, item.candidates[1], 20);
    expect(service.isRuleBypassedForItem(ITEM_ID)).toBeTrue();
    expect(service.getItemFillStatus(ITEM_ID)).toBe('non_compliant');
  });
});
