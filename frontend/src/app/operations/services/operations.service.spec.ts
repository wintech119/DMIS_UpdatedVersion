import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { OperationsService } from './operations.service';

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
      }),
      allocation: jasmine.objectContaining({
        reserved_stock_summary: jasmine.objectContaining({
          total_qty: '4.0000',
        }),
      }),
      compatibility_only: false,
    }));
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
});
