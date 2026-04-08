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

    service.saveDraft().subscribe();

    expect(saveSpy).toHaveBeenCalledTimes(1);
    const [reliefrqstId, payload] = saveSpy.calls.mostRecent().args as [number, PackageDraftPayload];
    expect(reliefrqstId).toBe(RELIEFRQST_ID);
    expect(payload.source_warehouse_id).toBe(9001);
    expect(payload.to_inventory_id).toBe(9002);
    expect(payload.transport_mode).toBe('TRUCK');
    expect(payload.comments_text).toBe('Hold for consolidation');
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
