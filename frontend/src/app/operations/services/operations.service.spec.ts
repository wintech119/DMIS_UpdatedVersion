import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { OperationsService } from './operations.service';
import { EligibilityDetailResponse, RequestDetailResponse } from '../models/operations.model';
import { formatStagingSelectionBasis, formatPackageStatus } from '../models/operations-status.util';
import { formatOperationsPackageStatus, getOperationsDispatchStage } from '../operations-display.util';

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

  it('adds an idempotency key when confirming receipt', () => {
    service.confirmReceipt(44, { received_by_name: 'Receiver One' }).subscribe();

    const request = httpMock.expectOne('/api/v1/operations/receipt-confirmation/44');
    expect(request.request.method).toBe('POST');
    expect(request.request.headers.get('Idempotency-Key')).toMatch(/^receipt-44-/);
    request.flush({ reliefpkg_id: 44, status: 'RECEIVED' });
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
});
