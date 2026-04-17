import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { Router } from '@angular/router';
import { of } from 'rxjs';

import { AuthRbacService } from '../../replenishment/services/auth-rbac.service';
import { PackageQueueItem } from '../models/operations.model';
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
});
