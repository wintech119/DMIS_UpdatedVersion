import { TestBed } from '@angular/core/testing';
import { HttpErrorResponse } from '@angular/common/http';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { OperationsService } from './operations.service';
import { EligibilityDetailResponse, RequestDetailResponse } from '../models/operations.model';
import { formatStagingSelectionBasis, formatPackageStatus } from '../models/operations-status.util';
import {
  extractOperationsHttpErrorMessage,
  formatOperationsPackageStatus,
  getOperationsDispatchStage,
} from '../operations-display.util';

describe('OperationsService', () => {
  let service: OperationsService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        OperationsService,
        provideHttpClient(),
        provideHttpClientTesting(),
      ],
    });

    service = TestBed.inject(OperationsService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('normalizes package detail responses with nested allocation payloads', () => {
    let result: unknown;

    service.getPackage(12).subscribe((value) => {
      result = value;
    });

    const request = httpMock.expectOne('/api/v1/operations/packages/12');
    expect(request.request.method).toBe('GET');
    request.flush({
      request: {
        reliefrqst_id: 12,
        agency_id: 8,
        agency_name: 'Parish Shelter',
        urgency_ind: 'H',
        status_code: 'APPROVED_FOR_FULFILLMENT',
        item_count: 2,
        total_requested_qty: '12.0000',
        total_issued_qty: '0.0000',
      },
      package: {
        reliefpkg_id: 44,
        reliefrqst_id: 12,
        source_warehouse_id: 2,
        status_code: 'P',
        consolidation_status: 'not-a-real-status',
        allocation: {
          allocation_lines: [
            {
              item_id: 101,
              inventory_id: 11,
              batch_id: 5,
              quantity: '4.0000',
              source_type: 'ON_HAND',
            },
          ],
          reserved_stock_summary: {
            line_count: 1,
            total_qty: '4.0000',
          },
          waybill_no: null,
        },
      },
      items: [],
      compatibility_only: false,
    });

    expect(result).toEqual(jasmine.objectContaining({
      request: jasmine.objectContaining({
        reliefrqst_id: 12,
        status_label: 'Approved',
      }),
      package: jasmine.objectContaining({
        reliefpkg_id: 44,
        source_warehouse_id: 2,
        status_label: 'Ready for Dispatch',
        consolidation_status: null,
      }),
      allocation: jasmine.objectContaining({
        reserved_stock_summary: jasmine.objectContaining({
          total_qty: '4.0000',
        }),
      }),
      compatibility_only: false,
    }));
  });

  it('normalizes alphabetical fallback staging basis and legacy V package status', () => {
    let result: unknown;

    service.getPackage(12).subscribe((value) => {
      result = value;
    });

    const request = httpMock.expectOne('/api/v1/operations/packages/12');
    expect(request.request.method).toBe('GET');
    request.flush({
      request: {
        reliefrqst_id: 12,
        status_code: 'APPROVED_FOR_FULFILLMENT',
      },
      package: {
        reliefpkg_id: 44,
        reliefrqst_id: 12,
        status_code: 'V',
        staging_selection_basis: 'ALPHABETICAL_FALLBACK',
      },
      items: [],
      compatibility_only: false,
    });

    expect(result).toEqual(jasmine.objectContaining({
      package: jasmine.objectContaining({
        status_code: 'V',
        status_label: 'Ready for Dispatch',
        staging_selection_basis: 'ALPHABETICAL_FALLBACK',
      }),
    }));
    expect(formatPackageStatus('V')).toBe('Ready for Dispatch');
    expect(formatOperationsPackageStatus('V')).toBe('Ready for Dispatch');
    expect(formatPackageStatus('REJECTED')).toBe('Rejected');
    expect(formatOperationsPackageStatus('REJECTED')).toBe('Rejected');
    expect(getOperationsDispatchStage({ status_code: 'V' })).toBe('ready');
    expect(formatStagingSelectionBasis('ALPHABETICAL_FALLBACK')).toBe('Alphabetical fallback');
  });

  it('loads the dispatch worklist from the real dispatch queue endpoint', () => {
    let result: unknown;

    service.getDispatchQueue().subscribe((value) => {
      result = value;
    });

    const request = httpMock.expectOne('/api/v1/operations/dispatch/queue');
    expect(request.request.method).toBe('GET');
    request.flush({
      results: [
        {
          reliefpkg_id: 44,
          reliefrqst_id: 12,
          tracking_no: 'PKG-00044',
          status_code: 'P',
          request: {
            reliefrqst_id: 12,
            tracking_no: 'RQ-00012',
            agency_name: 'Parish Shelter',
            event_name: 'Flood Response',
            urgency_ind: 'H',
            request_date: '2026-03-24',
            status_code: 'APPROVED_FOR_FULFILLMENT',
          },
          dispatch: {
            dispatch_id: 101,
            dispatch_no: 'DSP-00001',
            status_code: 'READY',
            dispatch_at: null,
            transport: {
              transport_mode: 'TRUCK',
            },
          },
        },
      ],
    });

    expect(result).toEqual({
      results: [
        jasmine.objectContaining({
          reliefpkg_id: 44,
          tracking_no: 'PKG-00044',
          request_tracking_no: 'RQ-00012',
          agency_name: 'Parish Shelter',
          event_name: 'Flood Response',
          transport_mode: 'TRUCK',
          request: jasmine.objectContaining({
            reliefrqst_id: 12,
          }),
          dispatch: jasmine.objectContaining({
            dispatch_id: 101,
          }),
        }),
      ],
    });
  });

  it('falls back to the real dispatch queue when dispatch detail fails before waybill creation', () => {
    let result: unknown;

    service.getDispatchDetail(44).subscribe((value) => {
      result = value;
    });

    const dispatchRequest = httpMock.expectOne('/api/v1/operations/dispatch/44');
    expect(dispatchRequest.request.method).toBe('GET');
    dispatchRequest.flush({ waybill: 'Waybill not available.' }, { status: 400, statusText: 'Bad Request' });

    const queueRequest = httpMock.expectOne('/api/v1/operations/dispatch/queue');
    expect(queueRequest.request.method).toBe('GET');
    queueRequest.flush({
      results: [
        {
          reliefpkg_id: 44,
          reliefrqst_id: 12,
          tracking_no: 'PKG-00044',
          status_code: 'P',
          request: {
            reliefrqst_id: 12,
            tracking_no: 'RQ-00012',
            urgency_ind: 'C',
            request_date: '2026-03-24',
            status_code: 'APPROVED_FOR_FULFILLMENT',
          },
        },
      ],
    });

    const packageRequest = httpMock.expectOne('/api/v1/operations/packages/12');
    expect(packageRequest.request.method).toBe('GET');
    packageRequest.flush({
      request: {
        reliefrqst_id: 12,
        tracking_no: 'RQ-00012',
        urgency_ind: 'C',
        status_code: 'APPROVED_FOR_FULFILLMENT',
      },
      package: {
        reliefpkg_id: 44,
        reliefrqst_id: 12,
        tracking_no: 'PKG-00044',
        status_code: 'P',
        allocation: {
          allocation_lines: [
            {
              item_id: 101,
              inventory_id: 11,
              batch_id: 5,
              quantity: '4.0000',
              source_type: 'ON_HAND',
            },
          ],
          reserved_stock_summary: {
            line_count: 1,
            total_qty: '4.0000',
          },
          waybill_no: null,
        },
      },
      items: [],
      compatibility_only: false,
    });

    expect(result).toEqual(jasmine.objectContaining({
      reliefpkg_id: 44,
      tracking_no: 'PKG-00044',
      request: jasmine.objectContaining({
        reliefrqst_id: 12,
      }),
      waybill: null,
      allocation: jasmine.objectContaining({
        allocation_lines: jasmine.any(Array),
      }),
    }));
  });

  it('normalizes dispatch detail responses with nested package transport data', () => {
    let result: unknown;

    service.getDispatchDetail(44).subscribe((value) => {
      result = value;
    });

    const request = httpMock.expectOne('/api/v1/operations/dispatch/44');
    expect(request.request.method).toBe('GET');
    request.flush({
      request: {
        reliefrqst_id: 12,
        tracking_no: 'RQ-00012',
        agency_id: 8,
        agency_name: 'Parish Shelter',
        urgency_ind: 'H',
        status_code: 'APPROVED_FOR_FULFILLMENT',
      },
      package: {
        reliefpkg_id: 44,
        reliefrqst_id: 12,
        tracking_no: 'PKG-00044',
        source_warehouse_id: 2,
        to_inventory_id: 8,
        destination_warehouse_name: 'Kingston Warehouse',
        status_code: 'P',
        transport_mode: 'TRUCK',
        allocation: {
          allocation_lines: [
            {
              item_id: 101,
              inventory_id: 11,
              batch_id: 5,
              quantity: '4.0000',
              source_type: 'ON_HAND',
            },
          ],
          reserved_stock_summary: {
            line_count: 1,
            total_qty: '4.0000',
          },
          waybill_no: null,
        },
      },
      dispatch: {
        dispatch_id: 101,
        dispatch_no: 'DSP-00001',
        status_code: 'READY',
        dispatch_at: null,
        transport: null,
      },
      waybill: null,
    });

    expect(result).toEqual(jasmine.objectContaining({
      reliefpkg_id: 44,
      tracking_no: 'PKG-00044',
      source_warehouse_id: 2,
      to_inventory_id: 8,
      transport_mode: 'TRUCK',
      allocation: jasmine.objectContaining({
        allocation_lines: jasmine.any(Array),
      }),
      dispatch: jasmine.objectContaining({
        dispatch_id: 101,
      }),
    }));
  });

  it('posts source warehouse when saving a package draft', () => {
    let result: unknown;

    service.savePackageDraft(12, {
      source_warehouse_id: 3,
      to_inventory_id: 8,
      transport_mode: 'TRUCK',
      comments_text: 'Ready for loading.',
    }).subscribe((value) => {
      result = value;
    });

    const draftRequest = httpMock.expectOne('/api/v1/operations/packages/12/draft');
    expect(draftRequest.request.method).toBe('POST');
    expect(draftRequest.request.body).toEqual({
      source_warehouse_id: 3,
      to_inventory_id: 8,
      transport_mode: 'TRUCK',
      comments_text: 'Ready for loading.',
    });
    draftRequest.flush({ status: 'DRAFT', reliefrqst_id: 12, reliefpkg_id: 44 });

    const packageRequest = httpMock.expectOne('/api/v1/operations/packages/12');
    expect(packageRequest.request.method).toBe('GET');
    packageRequest.flush({
      request: {
        reliefrqst_id: 12,
        agency_id: 8,
        agency_name: 'Parish Shelter',
        urgency_ind: 'H',
        status_code: 'APPROVED_FOR_FULFILLMENT',
      },
      package: {
        reliefpkg_id: 44,
        reliefrqst_id: 12,
        source_warehouse_id: 3,
        to_inventory_id: 8,
        transport_mode: 'TRUCK',
        comments_text: 'Ready for loading.',
        status_code: 'D',
      },
      items: [],
      compatibility_only: false,
    });

    expect(result).toEqual(jasmine.objectContaining({
      package: jasmine.objectContaining({
        source_warehouse_id: 3,
        to_inventory_id: 8,
        transport_mode: 'TRUCK',
        comments_text: 'Ready for loading.',
      }),
    }));
  });

  it('normalizes queue assignments and notifications into a combined task feed', () => {
    let result: unknown;

    service.getTasks().subscribe((value) => {
      result = value;
    });

    const request = httpMock.expectOne('/api/v1/operations/tasks');
    expect(request.request.method).toBe('GET');
    request.flush({
      queue_assignments: [
        {
          queue_assignment_id: 7,
          queue_code: 'DISPATCH',
          entity_type: 'PACKAGE',
          entity_id: 44,
          assigned_role_code: 'LOGISTICS_MANAGER',
          assignment_status: 'OPEN',
          assigned_at: '2026-03-26T15:00:00Z',
          completed_at: null,
        },
      ],
      notifications: [
        {
          notification_id: 11,
          event_code: 'REQUEST_APPROVED',
          entity_type: 'RELIEF_REQUEST',
          entity_id: 12,
          message_text: 'Request RQ-00012 approved for fulfillment.',
          queue_code: 'PACKAGE_FULFILLMENT',
          read_at: null,
          created_at: '2026-03-26T16:00:00Z',
        },
      ],
    });

    expect(result).toEqual({
      queue_assignments: [
        jasmine.objectContaining({
          id: 7,
          source: 'QUEUE_ASSIGNMENT',
          task_type: 'DISPATCH',
          related_entity_type: 'PACKAGE',
          related_entity_id: 44,
          queue_code: 'DISPATCH',
          status: 'PENDING',
        }),
      ],
      notifications: [
        jasmine.objectContaining({
          id: 11,
          source: 'NOTIFICATION',
          task_type: 'REQUEST_APPROVED',
          related_entity_type: 'RELIEF_REQUEST',
          related_entity_id: 12,
          queue_code: 'PACKAGE_FULFILLMENT',
          status: 'PENDING',
        }),
      ],
      results: [
        jasmine.objectContaining({
          id: 11,
          source: 'NOTIFICATION',
        }),
        jasmine.objectContaining({
          id: 7,
          source: 'QUEUE_ASSIGNMENT',
        }),
      ],
    });
  });

  it('normalizes partial release approval responses from the current child-package keys', () => {
    let result: unknown;

    service.approvePartialRelease(44, { approval_reason: 'Approved for split.' }).subscribe((value) => {
      result = value;
    });

    const request = httpMock.expectOne('/api/v1/operations/packages/44/partial-release/approve');
    expect(request.request.method).toBe('POST');
    request.flush({
      parent: {
        reliefpkg_id: 44,
        reliefrqst_id: 12,
        status_code: 'SPLIT',
        consolidation_status: 'PARTIAL_RELEASE_REQUESTED',
      },
      released_child: {
        reliefpkg_id: 45,
        reliefrqst_id: 12,
        status_code: 'READY_FOR_PICKUP',
      },
      residual_child: {
        reliefpkg_id: 46,
        reliefrqst_id: 12,
        status_code: 'CONSOLIDATING',
        consolidation_status: 'LEGS_IN_TRANSIT',
      },
    });

    expect(result).toEqual({
      parent: jasmine.objectContaining({
        reliefpkg_id: 44,
        consolidation_status: 'PARTIAL_RELEASE_REQUESTED',
      }),
      released: jasmine.objectContaining({
        reliefpkg_id: 45,
        status_code: 'READY_FOR_PICKUP',
      }),
      residual: jasmine.objectContaining({
        reliefpkg_id: 46,
        consolidation_status: 'LEGS_IN_TRANSIT',
      }),
    });
  });

  it('adds an idempotency key when abandoning a package draft', () => {
    service.abandonDraft(44, 'Reset this fulfillment').subscribe();

    const request = httpMock.expectOne('/api/v1/operations/packages/44/abandon-draft');
    expect(request.request.method).toBe('POST');
    expect(request.request.headers.get('Idempotency-Key')).toMatch(/^package-abandon-44-/);
    request.flush({ status: 'ABANDONED', reliefpkg_id: 44, reliefrqst_id: 12 });
  });

  it('uses a caller-supplied idempotency key when abandoning a package draft', () => {
    service.abandonDraft(44, 'Reset this fulfillment', 'retry-key-44').subscribe();

    const request = httpMock.expectOne('/api/v1/operations/packages/44/abandon-draft');
    expect(request.request.method).toBe('POST');
    expect(request.request.headers.get('Idempotency-Key')).toBe('retry-key-44');
    request.flush({ status: 'ABANDONED', reliefpkg_id: 44, reliefrqst_id: 12 });
  });

  it('falls back to a generated idempotency key when the caller-supplied abandon key is blank', () => {
    service.abandonDraft(44, 'Reset this fulfillment', '   ').subscribe();

    const request = httpMock.expectOne('/api/v1/operations/packages/44/abandon-draft');
    expect(request.request.method).toBe('POST');
    expect(request.request.headers.get('Idempotency-Key')).toMatch(/^package-abandon-44-/);
    request.flush({ status: 'ABANDONED', reliefpkg_id: 44, reliefrqst_id: 12 });
  });

  it('normalizes consolidation leg status codes before deriving the fallback label', () => {
    let result: unknown;

    service.getConsolidationLegs(44).subscribe((value) => {
      result = value;
    });

    const request = httpMock.expectOne('/api/v1/operations/packages/44/consolidation-legs');
    expect(request.request.method).toBe('GET');
    request.flush({
      package: {
        reliefpkg_id: 44,
        reliefrqst_id: 12,
        status_code: 'CONSOLIDATING',
      },
      results: [
        {
          leg_id: 301,
          package_id: 44,
          leg_sequence: 1,
          source_warehouse_id: 2,
          staging_warehouse_id: 8,
          status_code: 'in_transit',
          status_label: null,
        },
      ],
    });

    expect(result).toEqual({
      package: jasmine.objectContaining({
        reliefpkg_id: 44,
      }),
      results: [
        jasmine.objectContaining({
          leg_id: 301,
          status_code: 'IN_TRANSIT',
          status_label: 'In transit',
        }),
      ],
    });
  });

  it('preserves raw consolidation waybill payload artifacts instead of coercing them into objects', () => {
    let result: unknown;

    service.getConsolidationLegWaybill(44, 301).subscribe((value) => {
      result = value;
    });

    const request = httpMock.expectOne('/api/v1/operations/packages/44/consolidation-legs/301/waybill');
    expect(request.request.method).toBe('GET');
    request.flush({
      waybill_no: 'PK00044-L01',
      waybill_payload: 'JVBERi0xLjQKJcTl8uXr...',
      persisted: true,
    });

    expect(result).toEqual({
      waybill_no: 'PK00044-L01',
      waybill_payload: 'JVBERi0xLjQKJcTl8uXr...',
      persisted: true,
    });
  });

  it('adds an idempotency key when submitting a dispatch handoff', () => {
    service.submitDispatchHandoff(44, { transport_mode: 'TRUCK' }).subscribe();

    const request = httpMock.expectOne('/api/v1/operations/dispatch/44/handoff');
    expect(request.request.method).toBe('POST');
    expect(request.request.headers.get('Idempotency-Key')).toMatch(/^dispatch-44-/);
    request.flush({ reliefpkg_id: 44, status: 'DISPATCHED' });
  });

  it('adds an idempotency key when dispatching a consolidation leg', () => {
    service.dispatchConsolidationLeg(44, 301, { driver_name: 'Driver One' }).subscribe();

    const request = httpMock.expectOne('/api/v1/operations/packages/44/consolidation-legs/301/dispatch');
    expect(request.request.method).toBe('POST');
    expect(request.request.headers.get('Idempotency-Key')).toMatch(/^consolidation-leg-dispatch-44-301-/);
    request.flush({
      status: 'IN_TRANSIT',
      package: { reliefpkg_id: 44, reliefrqst_id: 12, status_code: 'CONSOLIDATING' },
      leg: { leg_id: 301, package_id: 44, status_code: 'IN_TRANSIT' },
    });
  });

  it('uses the caller supplied idempotency key when dispatching a consolidation leg', () => {
    service.dispatchConsolidationLeg(44, 301, { driver_name: 'Driver One' }, 'dispatch-leg-44-301-fixed').subscribe();

    const request = httpMock.expectOne('/api/v1/operations/packages/44/consolidation-legs/301/dispatch');
    expect(request.request.headers.get('Idempotency-Key')).toBe('dispatch-leg-44-301-fixed');
    request.flush({
      status: 'IN_TRANSIT',
      package: { reliefpkg_id: 44, reliefrqst_id: 12, status_code: 'CONSOLIDATING' },
      leg: { leg_id: 301, package_id: 44, status_code: 'IN_TRANSIT' },
    });
  });

  it('adds an idempotency key when receiving a consolidation leg', () => {
    service.receiveConsolidationLeg(44, 301, { received_by_name: 'Officer One' }).subscribe();

    const request = httpMock.expectOne('/api/v1/operations/packages/44/consolidation-legs/301/receive');
    expect(request.request.method).toBe('POST');
    expect(request.request.headers.get('Idempotency-Key')).toMatch(/^consolidation-leg-receive-44-301-/);
    request.flush({
      status: 'RECEIVED_AT_STAGING',
      package: { reliefpkg_id: 44, reliefrqst_id: 12, status_code: 'CONSOLIDATING' },
      leg: { leg_id: 301, package_id: 44, status_code: 'RECEIVED_AT_STAGING' },
    });
  });

  it('uses the caller supplied idempotency key when receiving a consolidation leg', () => {
    service.receiveConsolidationLeg(44, 301, { received_by_name: 'Officer One' }, 'receive-leg-44-301-fixed').subscribe();

    const request = httpMock.expectOne('/api/v1/operations/packages/44/consolidation-legs/301/receive');
    expect(request.request.headers.get('Idempotency-Key')).toBe('receive-leg-44-301-fixed');
    request.flush({
      status: 'RECEIVED_AT_STAGING',
      package: { reliefpkg_id: 44, reliefrqst_id: 12, status_code: 'CONSOLIDATING' },
      leg: { leg_id: 301, package_id: 44, status_code: 'RECEIVED_AT_STAGING' },
    });
  });

  it('adds an idempotency key when confirming receipt', () => {
    service.confirmReceipt(44, { received_by_name: 'Receiver One' }).subscribe();

    const request = httpMock.expectOne('/api/v1/operations/receipt-confirmation/44');
    expect(request.request.method).toBe('POST');
    expect(request.request.headers.get('Idempotency-Key')).toMatch(/^receipt-44-/);
    request.flush({ reliefpkg_id: 44, status: 'RECEIVED' });
  });

  it('adds an idempotency key when committing allocations', () => {
    service.commitAllocations(12, { allocations: [] }).subscribe();

    const request = httpMock.expectOne('/api/v1/operations/packages/12/allocations/commit');
    expect(request.request.method).toBe('POST');
    expect(request.request.headers.get('Idempotency-Key')).toMatch(/^allocation-commit-12-/);
    request.flush({ status: 'COMMITTED', reliefrqst_id: 12, reliefpkg_id: 44 });
  });

  it('adds an idempotency key when requesting a partial release', () => {
    service.requestPartialRelease(44, { reason: 'Split urgent items.' }).subscribe();

    const request = httpMock.expectOne('/api/v1/operations/packages/44/partial-release/request');
    expect(request.request.method).toBe('POST');
    expect(request.request.headers.get('Idempotency-Key')).toMatch(/^partial-release-request-44-/);
    request.flush({
      status: 'PARTIAL_RELEASE_REQUESTED',
      package: { reliefpkg_id: 44, reliefrqst_id: 12, status_code: 'PARTIAL_RELEASE_REQUESTED' },
    });
  });

  it('uses the caller supplied idempotency key when requesting a partial release', () => {
    service.requestPartialRelease(44, { reason: 'Split urgent items.' }, 'partial-release-request-44-fixed').subscribe();

    const request = httpMock.expectOne('/api/v1/operations/packages/44/partial-release/request');
    expect(request.request.headers.get('Idempotency-Key')).toBe('partial-release-request-44-fixed');
    request.flush({
      status: 'PARTIAL_RELEASE_REQUESTED',
      package: { reliefpkg_id: 44, reliefrqst_id: 12, status_code: 'PARTIAL_RELEASE_REQUESTED' },
    });
  });

  it('adds an idempotency key when approving a partial release', () => {
    service.approvePartialRelease(44, { approval_reason: 'Approved for split.' }).subscribe();

    const request = httpMock.expectOne('/api/v1/operations/packages/44/partial-release/approve');
    expect(request.request.method).toBe('POST');
    expect(request.request.headers.get('Idempotency-Key')).toMatch(/^partial-release-approve-44-/);
    request.flush({
      parent: { reliefpkg_id: 44 },
      released_child: { reliefpkg_id: 45 },
      residual_child: { reliefpkg_id: 46 },
    });
  });

  it('uses the caller supplied idempotency key when approving a partial release', () => {
    service.approvePartialRelease(44, { approval_reason: 'Approved for split.' }, 'partial-release-approve-44-fixed').subscribe();

    const request = httpMock.expectOne('/api/v1/operations/packages/44/partial-release/approve');
    expect(request.request.headers.get('Idempotency-Key')).toBe('partial-release-approve-44-fixed');
    request.flush({
      parent: { reliefpkg_id: 44 },
      released_child: { reliefpkg_id: 45 },
      residual_child: { reliefpkg_id: 46 },
    });
  });

  it('adds an idempotency key when submitting pickup release', () => {
    service.submitPickupRelease(44, { collected_by_name: 'Driver One' }).subscribe();

    const request = httpMock.expectOne('/api/v1/operations/packages/44/pickup-release');
    expect(request.request.method).toBe('POST');
    expect(request.request.headers.get('Idempotency-Key')).toMatch(/^pickup-release-44-/);
    request.flush({
      status: 'RECEIVED',
      package: { reliefpkg_id: 44, reliefrqst_id: 12, status_code: 'RECEIVED' },
    });
  });

  it('uses the caller supplied idempotency key when submitting pickup release', () => {
    service.submitPickupRelease(44, { collected_by_name: 'Driver One' }, 'pickup-release-44-fixed').subscribe();

    const request = httpMock.expectOne('/api/v1/operations/packages/44/pickup-release');
    expect(request.request.headers.get('Idempotency-Key')).toBe('pickup-release-44-fixed');
    request.flush({
      status: 'RECEIVED',
      package: { reliefpkg_id: 44, reliefrqst_id: 12, status_code: 'RECEIVED' },
    });
  });

  it('adds an idempotency key when submitting a relief request', () => {
    service.submitRequest(12).subscribe();

    const request = httpMock.expectOne('/api/v1/operations/requests/12/submit');
    expect(request.request.method).toBe('POST');
    expect(request.request.headers.get('Idempotency-Key')).toMatch(/^request-submit-12-/);
    request.flush({ reliefrqst_id: 12, status_code: 'SUBMITTED' });
  });

  it('uses the caller-supplied idempotency key when replaying request submission', () => {
    service.submitRequest(12, 'request-submit-12-fixed').subscribe();

    const request = httpMock.expectOne('/api/v1/operations/requests/12/submit');
    expect(request.request.method).toBe('POST');
    expect(request.request.headers.get('Idempotency-Key')).toBe('request-submit-12-fixed');
    request.flush({ reliefrqst_id: 12, status_code: 'SUBMITTED' });
  });

  it('adds an idempotency key when submitting an eligibility decision', () => {
    service.submitEligibilityDecision(12, { decision: 'APPROVED' }).subscribe();

    const request = httpMock.expectOne('/api/v1/operations/eligibility/12/decision');
    expect(request.request.method).toBe('POST');
    expect(request.request.headers.get('Idempotency-Key')).toMatch(/^eligibility-decision-12-/);
    request.flush({ reliefrqst_id: 12, status_code: 'APPROVED_FOR_FULFILLMENT' });
  });

  it('uses the caller-supplied idempotency key when replaying an eligibility decision', () => {
    service.submitEligibilityDecision(12, { decision: 'APPROVED' }, 'eligibility-decision-12-fixed').subscribe();

    const request = httpMock.expectOne('/api/v1/operations/eligibility/12/decision');
    expect(request.request.method).toBe('POST');
    expect(request.request.headers.get('Idempotency-Key')).toBe('eligibility-decision-12-fixed');
    request.flush({ reliefrqst_id: 12, status_code: 'APPROVED_FOR_FULFILLMENT' });
  });

  describe('relief-request intake contract normalization', () => {
    function flushRequest(payload: Record<string, unknown>): RequestDetailResponse {
      let result: RequestDetailResponse | undefined;
      service.getRequest(12).subscribe((value) => {
        result = value;
      });
      const request = httpMock.expectOne('/api/v1/operations/requests/12');
      expect(request.request.method).toBe('GET');
      request.flush(payload);
      if (!result) {
        throw new Error('getRequest did not emit a value');
      }
      return result;
    }

    it('preserves canonical request_mode and all four tenant/agency IDs', () => {
      const result = flushRequest({
        reliefrqst_id: 12,
        status_code: 'APPROVED_FOR_FULFILLMENT',
        request_mode: 'FOR_SUBORDINATE',
        requesting_tenant_id: 3,
        requesting_agency_id: 17,
        beneficiary_tenant_id: 5,
        beneficiary_agency_id: 21,
      });

      expect(result.request_mode).toBe('FOR_SUBORDINATE');
      expect(result.requesting_tenant_id).toBe(3);
      expect(result.requesting_agency_id).toBe(17);
      expect(result.beneficiary_tenant_id).toBe(5);
      expect(result.beneficiary_agency_id).toBe(21);
    });

    it('falls back to origin_mode when request_mode is missing', () => {
      const result = flushRequest({
        reliefrqst_id: 12,
        status_code: 'SUBMITTED',
        origin_mode: 'FOR_SUBORDINATE',
      });

      expect(result.request_mode).toBe('FOR_SUBORDINATE');
    });

    it('remaps the legacy SUBORDINATE value to the canonical FOR_SUBORDINATE', () => {
      const result = flushRequest({
        reliefrqst_id: 12,
        status_code: 'SUBMITTED',
        request_mode: 'SUBORDINATE',
      });

      expect(result.request_mode).toBe('FOR_SUBORDINATE');
    });

    it('rejects unknown request_mode values via the canonical whitelist', () => {
      const result = flushRequest({
        reliefrqst_id: 12,
        status_code: 'SUBMITTED',
        request_mode: 'BOGUS',
      });

      expect(result.request_mode).toBeNull();
    });
  });

  describe('eligibility detail normalization', () => {
    function flushEligibility(payload: Record<string, unknown>): EligibilityDetailResponse {
      let result: EligibilityDetailResponse | undefined;
      service.getEligibilityDetail(70).subscribe((value) => {
        result = value;
      });
      const request = httpMock.expectOne('/api/v1/operations/eligibility/70');
      expect(request.request.method).toBe('GET');
      request.flush(payload);
      if (!result) {
        throw new Error('getEligibilityDetail did not emit a value');
      }
      return result;
    }

    it('round-trips all five eligibility_decision fields', () => {
      const result = flushEligibility({
        reliefrqst_id: 70,
        status_code: 'APPROVED_FOR_FULFILLMENT',
        decision_made: true,
        can_edit: false,
        eligibility_decision: {
          decision_code: 'APPROVED',
          decision_reason: 'Request aligns with SURGE allocation.',
          decided_by_user_id: 'user-9001',
          decided_by_role_code: 'ELIGIBILITY_APPROVER',
          decided_at: '2026-04-15T09:30:00Z',
        },
      });

      expect(result.decision_made).toBeTrue();
      expect(result.can_edit).toBeFalse();
      expect(result.eligibility_decision).toEqual({
        decision_code: 'APPROVED',
        decision_reason: 'Request aligns with SURGE allocation.',
        decided_by_user_id: 'user-9001',
        decided_by_role_code: 'ELIGIBILITY_APPROVER',
        decided_at: '2026-04-15T09:30:00Z',
      });
    });

    it('normalizes a null eligibility_decision block to null', () => {
      const result = flushEligibility({
        reliefrqst_id: 70,
        status_code: 'UNDER_ELIGIBILITY_REVIEW',
        decision_made: false,
        can_edit: true,
        eligibility_decision: null,
      });

      expect(result.eligibility_decision).toBeNull();
    });

    it('treats an empty eligibility_decision object as null', () => {
      const result = flushEligibility({
        reliefrqst_id: 70,
        status_code: 'UNDER_ELIGIBILITY_REVIEW',
        decision_made: false,
        can_edit: true,
        eligibility_decision: {},
      });

      expect(result.eligibility_decision).toBeNull();
    });

    it('drops the decision block when decision_code is malformed so audit data is never fabricated', () => {
      const result = flushEligibility({
        reliefrqst_id: 70,
        status_code: 'REJECTED',
        decision_made: true,
        can_edit: false,
        eligibility_decision: {
          decision_code: 'maybe',
          decision_reason: 'Unclear outcome in feed.',
          decided_by_user_id: null,
          decided_by_role_code: null,
          decided_at: null,
        },
      });

      expect(result.eligibility_decision).toBeNull();
    });
  });

  describe('FR05.08 override review', () => {
    const API = '/api/v1/operations';

    it('approveOverride posts to override-approve with the caller-supplied Idempotency-Key', () => {
      service.approveOverride(95009, {}, 'override:95009:test-uuid').subscribe();
      const req = httpMock.expectOne(`${API}/packages/95009/allocations/override-approve`);
      expect(req.request.method).toBe('POST');
      expect(req.request.headers.get('Idempotency-Key')).toBe('override:95009:test-uuid');
      req.flush({
        status: 'COMMITTED',
        reliefrqst_id: 95009,
        reliefpkg_id: 77001,
        override_required: false,
        override_status_code: 'APPROVED',
      });
    });

    it('returnOverride posts to override-return with reason body and Idempotency-Key', () => {
      let response: unknown;
      service
        .returnOverride(95009, { reason: 'Needs rework' }, 'override:95009:retkey')
        .subscribe((value) => (response = value));
      const req = httpMock.expectOne(`${API}/packages/95009/allocations/override-return`);
      expect(req.request.method).toBe('POST');
      expect(req.request.body).toEqual({ reason: 'Needs rework' });
      expect(req.request.headers.get('Idempotency-Key')).toBe('override:95009:retkey');
      req.flush({
        status: 'RETURNED_FOR_ADJUSTMENT',
        reliefrqst_id: 95009,
        reliefpkg_id: 77001,
        override_status_code: 'RETURNED_FOR_ADJUSTMENT',
        package_status_code: 'DRAFT',
      });
      expect((response as { status: string }).status).toBe('RETURNED_FOR_ADJUSTMENT');
    });

    it('rejectOverride posts to override-reject with reason body and Idempotency-Key', () => {
      let response: unknown;
      service
        .rejectOverride(95009, { reason: 'Invalid request' }, 'override:95009:rejkey')
        .subscribe((value) => (response = value));
      const req = httpMock.expectOne(`${API}/packages/95009/allocations/override-reject`);
      expect(req.request.method).toBe('POST');
      expect(req.request.body).toEqual({ reason: 'Invalid request' });
      expect(req.request.headers.get('Idempotency-Key')).toBe('override:95009:rejkey');
      req.flush({
        status: 'REJECTED',
        reliefrqst_id: 95009,
        reliefpkg_id: 77001,
        override_status_code: 'REJECTED',
        package_status_code: 'REJECTED',
      });
      expect((response as { status: string }).status).toBe('REJECTED');
    });

    it('createIdempotencyKey shapes override keys as override-<id>-<uuid>', () => {
      const key = service.createIdempotencyKey('override', 42);
      expect(key.startsWith('override-42-')).toBeTrue();
    });

    it('createIdempotencyKey shapes request-submit keys as request-submit-<id>-<uuid>', () => {
      const key = service.createIdempotencyKey('request-submit', 12);
      expect(key.startsWith('request-submit-12-')).toBeTrue();
    });

    it('createIdempotencyKey shapes eligibility-decision keys as eligibility-decision-<id>-<uuid>', () => {
      const key = service.createIdempotencyKey('eligibility-decision', 12);
      expect(key.startsWith('eligibility-decision-12-')).toBeTrue();
    });

    it('createIdempotencyKey shapes allocation-commit keys as allocation-commit-<id>-<uuid>', () => {
      const key = service.createIdempotencyKey('allocation-commit', 12);
      expect(key.startsWith('allocation-commit-12-')).toBeTrue();
    });

    it('same idempotency key propagates on replay (same key -> same header)', () => {
      const fixedKey = 'override:95009:fixed-uuid';
      service.returnOverride(95009, { reason: 'First try' }, fixedKey).subscribe();
      const first = httpMock.expectOne(`${API}/packages/95009/allocations/override-return`);
      expect(first.request.headers.get('Idempotency-Key')).toBe(fixedKey);
      first.flush({
        status: 'RETURNED_FOR_ADJUSTMENT',
        reliefrqst_id: 95009,
        reliefpkg_id: 77001,
        override_status_code: 'RETURNED_FOR_ADJUSTMENT',
        package_status_code: 'DRAFT',
      });

      service.returnOverride(95009, { reason: 'First try' }, fixedKey).subscribe();
      const second = httpMock.expectOne(`${API}/packages/95009/allocations/override-return`);
      expect(second.request.headers.get('Idempotency-Key')).toBe(fixedKey);
      second.flush({
        status: 'RETURNED_FOR_ADJUSTMENT',
        reliefrqst_id: 95009,
        reliefpkg_id: 77001,
        override_status_code: 'RETURNED_FOR_ADJUSTMENT',
        package_status_code: 'DRAFT',
      });
    });

    it('normalizes approve-path extended statuses (CONSOLIDATING / READY_FOR_PICKUP / READY_FOR_DISPATCH)', () => {
      const statuses = ['CONSOLIDATING', 'READY_FOR_PICKUP', 'READY_FOR_DISPATCH'];
      for (const status of statuses) {
        let response: unknown;
        service
          .approveOverride(95009, {}, `override:95009:${status}`)
          .subscribe((value) => (response = value));
        const req = httpMock.expectOne(`${API}/packages/95009/allocations/override-approve`);
        req.flush({
          status,
          reliefrqst_id: 95009,
          reliefpkg_id: 77001,
          override_required: false,
          override_status_code: 'APPROVED',
        });
        expect((response as { status: string }).status).toBe(status);
      }
    });
  });

  it('extracts nested structured error messages from an errors map', () => {
    const message = extractOperationsHttpErrorMessage(
      new HttpErrorResponse({
        status: 400,
        error: {
          errors: {
            package: [{ detail: 'Structured package error.' }],
          },
        },
      }),
      'Fallback error.',
    );

    expect(message).toBe('Structured package error.');
  });
});
