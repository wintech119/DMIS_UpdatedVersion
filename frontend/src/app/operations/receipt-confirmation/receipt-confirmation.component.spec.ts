import { ComponentFixture, TestBed } from '@angular/core/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { ActivatedRoute, Router, convertToParamMap } from '@angular/router';
import { of } from 'rxjs';

import { ReceiptConfirmationComponent } from './receipt-confirmation.component';
import { OperationsService } from '../services/operations.service';

describe('ReceiptConfirmationComponent', () => {
  let fixture: ComponentFixture<ReceiptConfirmationComponent>;
  let component: ReceiptConfirmationComponent;
  let operationsService: jasmine.SpyObj<OperationsService>;

  beforeEach(async () => {
    operationsService = jasmine.createSpyObj<OperationsService>('OperationsService', [
      'getDispatchDetail',
      'confirmReceipt',
    ]);

    operationsService.getDispatchDetail.and.returnValue(of({
      reliefpkg_id: 90,
      tracking_no: 'PKG-00090',
      reliefrqst_id: 12,
      agency_id: 8,
      eligible_event_id: 4,
      to_inventory_id: 3,
      destination_warehouse_name: 'Kingston Warehouse',
      status_code: 'D',
      status_label: 'Dispatched',
      dispatch_dtime: '2026-03-26T10:00:00Z',
      received_dtime: null,
      transport_mode: 'TRUCK',
      comments_text: null,
      version_nbr: 1,
      execution_status: 'DISPATCHED',
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
        status_code: 'APPROVED_FOR_FULFILLMENT',
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
        package_status: 'D',
        execution_status: 'DISPATCHED',
        needs_list_id: null,
        compatibility_bridge: false,
        request_mode: null,
        authority_context: null,
      },
      waybill: {
        waybill_no: 'WB-00090',
        waybill_payload: {
          waybill_no: 'WB-00090',
        },
        persisted: true,
      },
    }));
    operationsService.confirmReceipt.and.returnValue(of({
      status: 'RECEIVED',
      reliefpkg_id: 90,
      package_tracking_no: 'PKG-00090',
      receipt: {
        receipt_status_code: 'RECEIVED',
        received_by_user_id: 'ops-user',
        received_by_name: 'Receiver One',
        received_at: '2026-03-26T14:00:00Z',
        receipt_notes: 'Received intact',
        beneficiary_delivery_ref: 'BEN-42',
      },
    }));

    await TestBed.configureTestingModule({
      imports: [NoopAnimationsModule, ReceiptConfirmationComponent],
      providers: [
        { provide: OperationsService, useValue: operationsService },
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: {
              paramMap: convertToParamMap({ reliefpkgId: '90' }),
            },
          },
        },
        {
          provide: Router,
          useValue: jasmine.createSpyObj('Router', ['navigate']),
        },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(ReceiptConfirmationComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('submits the backend-aligned receipt payload keys', () => {
    component.receivedBy.set('Receiver One');
    component.receiptNotes.set('Received intact');
    component.beneficiaryDeliveryRef.set('BEN-42');

    component.submitReceipt();

    expect(operationsService.confirmReceipt).toHaveBeenCalledWith(90, {
      received_by_name: 'Receiver One',
      receipt_notes: 'Received intact',
      beneficiary_delivery_ref: 'BEN-42',
    });
  });
});
