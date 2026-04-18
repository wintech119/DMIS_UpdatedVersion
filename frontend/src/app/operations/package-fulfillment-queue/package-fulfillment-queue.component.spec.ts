import { HttpErrorResponse } from '@angular/common/http';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { Router } from '@angular/router';
import { of, throwError } from 'rxjs';

import { AuthRbacService } from '../../replenishment/services/auth-rbac.service';
import { PackageQueueItem, PackageSummary } from '../models/operations.model';
import { OperationsService } from '../services/operations.service';
import { PackageFulfillmentQueueComponent } from './package-fulfillment-queue.component';

describe('PackageFulfillmentQueueComponent', () => {
  const authStub = {
    ensureLoaded: jasmine.createSpy('ensureLoaded').and.returnValue(of(void 0)),
    currentUserRef: signal<string | null>('kemar.logistics'),
  };
  const operationsService = jasmine.createSpyObj<OperationsService>('OperationsService', ['getPackagesQueue']);
  const router = jasmine.createSpyObj<Router>('Router', ['navigate']);

  function buildQueueItem(overrides: Partial<PackageQueueItem> = {}): PackageQueueItem {
    return {
      reliefrqst_id: 95009,
      tracking_no: 'RQ-95009',
      agency_id: 1,
      agency_name: 'Parish Shelter',
      eligible_event_id: null,
      event_name: 'Flood Response',
      urgency_ind: 'H',
      status_code: 'APPROVED_FOR_FULFILLMENT',
      status_label: 'Approved for Fulfillment',
      request_date: '2026-04-10',
      create_dtime: '2026-04-10T09:00:00Z',
      review_dtime: null,
      action_dtime: null,
      rqst_notes_text: null,
      review_notes_text: null,
      status_reason_desc: null,
      version_nbr: 1,
      item_count: 1,
      total_requested_qty: '2',
      total_issued_qty: '0',
      reliefpkg_id: 77001,
      package_tracking_no: 'PKG-77001',
      package_status: null,
      execution_status: null,
      needs_list_id: null,
      compatibility_bridge: false,
      request_mode: null,
      authority_context: null,
      requesting_tenant_id: null,
      requesting_agency_id: null,
      beneficiary_tenant_id: null,
      beneficiary_agency_id: null,
      current_package: null,
      ...overrides,
    };
  }

  function buildPackageSummary(overrides: Partial<PackageSummary> = {}): PackageSummary {
    return {
      reliefpkg_id: 77001,
      tracking_no: 'PKG-77001',
      reliefrqst_id: 95009,
      agency_id: 1,
      eligible_event_id: null,
      source_warehouse_id: 9001,
      to_inventory_id: 9002,
      destination_warehouse_name: 'Destination WH',
      status_code: 'D',
      status_label: 'Dispatched',
      dispatch_dtime: null,
      received_dtime: null,
      transport_mode: null,
      comments_text: null,
      version_nbr: 1,
      execution_status: null,
      needs_list_id: null,
      compatibility_bridge: false,
      ...overrides,
    };
  }

  beforeEach(async () => {
    authStub.ensureLoaded.calls.reset();
    operationsService.getPackagesQueue.and.returnValue(of({ results: [] }));

    await TestBed.configureTestingModule({
      imports: [NoopAnimationsModule, PackageFulfillmentQueueComponent],
      providers: [
        { provide: AuthRbacService, useValue: authStub },
        { provide: OperationsService, useValue: operationsService },
        { provide: Router, useValue: router },
      ],
    }).compileComponents();
  });

  it('treats legacy pending package rows as ready when no override approval is pending', () => {
    const fixture = TestBed.createComponent(PackageFulfillmentQueueComponent);
    const component = fixture.componentInstance;
    fixture.detectChanges();

    expect(
      component.isReady(
        buildQueueItem({
          package_status: 'P',
          current_package: null,
          execution_status: null,
        }),
      ),
    ).toBeTrue();
  });

  it('does not treat legacy pending package rows as ready while override approval is pending', () => {
    const fixture = TestBed.createComponent(PackageFulfillmentQueueComponent);
    const component = fixture.componentInstance;
    fixture.detectChanges();

    expect(
      component.isReady(
        buildQueueItem({
          package_status: 'P',
          current_package: null,
          execution_status: 'PENDING_OVERRIDE_APPROVAL',
        }),
      ),
    ).toBeFalse();
  });

  it('excludes DISPATCHED, RECEIVED, and REJECTED rows from the active-work queue', () => {
    operationsService.getPackagesQueue.and.returnValue(
      of({
        results: [
          buildQueueItem({ reliefrqst_id: 1, status_code: 'APPROVED_FOR_FULFILLMENT' }),
          // DISPATCHED / RECEIVED belong on PackageStatusCode — route via current_package.
          buildQueueItem({
            reliefrqst_id: 2,
            status_code: 'APPROVED_FOR_FULFILLMENT',
            current_package: buildPackageSummary({ status_code: 'DISPATCHED' }),
          }),
          buildQueueItem({
            reliefrqst_id: 3,
            status_code: 'APPROVED_FOR_FULFILLMENT',
            current_package: buildPackageSummary({ status_code: 'RECEIVED' }),
          }),
          // REJECTED is valid on RequestStatusCode — keep on the request.
          buildQueueItem({ reliefrqst_id: 4, status_code: 'REJECTED' }),
          // Legacy D / C live on package_status (PackageStatusCode | null).
          buildQueueItem({ reliefrqst_id: 5, package_status: 'D' }),
          buildQueueItem({ reliefrqst_id: 6, package_status: 'C' }),
        ],
      }),
    );

    const fixture = TestBed.createComponent(PackageFulfillmentQueueComponent);
    const component = fixture.componentInstance;
    fixture.detectChanges();

    const ids = component.filteredItems().map((row) => row.reliefrqst_id);
    expect(ids).toContain(1);
    expect(ids).not.toContain(2);
    expect(ids).not.toContain(3);
    expect(ids).not.toContain(4);
    expect(ids).not.toContain(5);
    expect(ids).not.toContain(6);
  });

  it('does not expose a Dispatched option in filterOptions', () => {
    const fixture = TestBed.createComponent(PackageFulfillmentQueueComponent);
    const component = fixture.componentInstance;
    fixture.detectChanges();

    const values = component.filterOptions.map((option) => option.value);
    expect(values).not.toContain('dispatched' as never);
    expect(values).toEqual(jasmine.arrayContaining(['all', 'awaiting', 'drafts', 'preparing', 'ready']));
  });

  it('renders the error branch with a working Retry CTA when the queue fails to load', () => {
    operationsService.getPackagesQueue.and.returnValue(
      throwError(() => new HttpErrorResponse({ status: 503, statusText: 'Service Unavailable' })),
    );

    const fixture = TestBed.createComponent(PackageFulfillmentQueueComponent);
    const component = fixture.componentInstance;
    fixture.detectChanges();

    expect(component.errored()).toBeTrue();
    expect(component.loadError()).toBeTruthy();

    const errorEl = fixture.nativeElement.querySelector('dmis-empty-state[icon="error_outline"]');
    expect(errorEl).not.toBeNull();

    operationsService.getPackagesQueue.calls.reset();
    operationsService.getPackagesQueue.and.returnValue(
      of({ results: [buildQueueItem({ reliefrqst_id: 42 })] }),
    );

    component.refreshQueue();
    fixture.detectChanges();

    expect(operationsService.getPackagesQueue).toHaveBeenCalled();
    expect(component.errored()).toBeFalse();
    expect(component.loadError()).toBeNull();
    expect(component.filteredItems().length).toBe(1);
  });
});
