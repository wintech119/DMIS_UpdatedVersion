import { ComponentFixture, TestBed } from '@angular/core/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { of } from 'rxjs';
import { ActivatedRoute, Router, convertToParamMap } from '@angular/router';

import { DmisNotificationService } from '../../replenishment/services/notification.service';
import { OperationsService } from '../services/operations.service';
import { OpsDispatchWorkspaceComponent } from './dispatch-workspace.component';

describe('OpsDispatchWorkspaceComponent', () => {
  let fixture: ComponentFixture<OpsDispatchWorkspaceComponent>;
  let component: OpsDispatchWorkspaceComponent;
  let operationsService: jasmine.SpyObj<OperationsService>;

  beforeEach(async () => {
    operationsService = jasmine.createSpyObj<OperationsService>('OperationsService', [
      'getDispatchDetail',
      'submitDispatchHandoff',
    ]);

    operationsService.getDispatchDetail.and.returnValue(of({
      reliefpkg_id: 90,
      tracking_no: 'PKG-00090',
      reliefrqst_id: 12,
      agency_id: 8,
      eligible_event_id: 4,
      to_inventory_id: 3,
      destination_warehouse_name: 'Kingston Warehouse',
      status_code: 'P',
      status_label: 'Ready for Dispatch',
      dispatch_dtime: null,
      received_dtime: null,
      transport_mode: null,
      comments_text: null,
      version_nbr: 1,
      execution_status: 'READY_FOR_DISPATCH',
      needs_list_id: null,
      compatibility_bridge: false,
      request: {
        reliefrqst_id: 12,
        tracking_no: 'RQ-00012',
        agency_id: 8,
        agency_name: 'Parish Shelter',
        eligible_event_id: 4,
        event_name: 'Flood Response',
        urgency_ind: 'H',
        status_code: 3,
        status_label: 'Approved',
        request_date: '2026-03-26',
        create_dtime: '2026-03-26T08:00:00Z',
        review_dtime: null,
        action_dtime: null,
        rqst_notes_text: null,
        review_notes_text: null,
        status_reason_desc: null,
        version_nbr: 1,
        item_count: 1,
        total_requested_qty: '4.0000',
        total_issued_qty: '0.0000',
        reliefpkg_id: 90,
        package_tracking_no: 'PKG-00090',
        package_status: 'P',
        execution_status: 'READY_FOR_DISPATCH',
        needs_list_id: null,
        compatibility_bridge: false,
      },
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
      waybill: null,
    }));
    operationsService.submitDispatchHandoff.and.returnValue(of({
      status: 'DISPATCHED',
      reliefrqst_id: 12,
      reliefpkg_id: 90,
      request_tracking_no: 'RQ-00012',
      package_tracking_no: 'PKG-00090',
      waybill_no: 'WB-00090',
      waybill_payload: {
        waybill_no: 'WB-00090',
      },
      dispatched_rows: [],
    }));

    await TestBed.configureTestingModule({
      imports: [NoopAnimationsModule, OpsDispatchWorkspaceComponent],
      providers: [
        { provide: OperationsService, useValue: operationsService },
        {
          provide: DmisNotificationService,
          useValue: jasmine.createSpyObj<DmisNotificationService>('DmisNotificationService', [
            'showError',
            'showWarning',
            'showSuccess',
          ]),
        },
        {
          provide: ActivatedRoute,
          useValue: {
            paramMap: of(convertToParamMap({ reliefpkgId: '90' })),
          },
        },
        {
          provide: Router,
          useValue: jasmine.createSpyObj('Router', ['navigate']),
        },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(OpsDispatchWorkspaceComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('submits the backend-aligned dispatch payload keys', () => {
    component.transportMode.set('TRUCK');
    component.driverName.set('Jane Driver');
    component.vehicleIdentifier.set('1234AB');
    component.departureTime.set('2026-03-26T10:00');
    component.estimatedArrival.set('2026-03-26T13:00');
    component.transportNotes.set('Route via Kingston.');

    component.completeDispatchAction();

    expect(operationsService.submitDispatchHandoff).toHaveBeenCalledWith(90, {
      transport_mode: 'TRUCK',
      driver_name: 'Jane Driver',
      vehicle_registration: '1234AB',
      departure_dtime: '2026-03-26T10:00',
      estimated_arrival_dtime: '2026-03-26T13:00',
      transport_notes: 'Route via Kingston.',
    });
  });
});
