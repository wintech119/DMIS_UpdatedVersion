import { ComponentFixture, TestBed } from '@angular/core/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { By } from '@angular/platform-browser';
import { of } from 'rxjs';
import { ActivatedRoute, Router, convertToParamMap } from '@angular/router';

import { DmisNotificationService } from '../../replenishment/services/notification.service';
import { OperationsService } from '../services/operations.service';
import { OpsDispatchWorkspaceComponent } from './dispatch-workspace.component';
import { OpsDispatchReadinessStepComponent } from './steps/dispatch-readiness-step.component';

describe('OpsDispatchWorkspaceComponent', () => {
  let fixture: ComponentFixture<OpsDispatchWorkspaceComponent>;
  let component: OpsDispatchWorkspaceComponent;
  let operationsService: jasmine.SpyObj<OperationsService>;
  let notifications: jasmine.SpyObj<DmisNotificationService>;

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
      source_warehouse_id: 1,
      to_inventory_id: 3,
      destination_warehouse_name: 'Kingston Warehouse',
      status_code: 'P',
      status_label: 'Ready for Dispatch',
      dispatch_dtime: null,
      received_dtime: null,
      transport_mode: 'TRUCK',
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
        package_status: 'P',
        execution_status: 'READY_FOR_DISPATCH',
        needs_list_id: null,
        compatibility_bridge: false,
        request_mode: null,
        authority_context: null,
      },
      allocation: {
        allocation_lines: [
          {
            item_id: 101,
            inventory_id: 11,
            batch_id: 5,
            quantity: '1.2345',
            source_type: 'ON_HAND',
          },
        ],
        reserved_stock_summary: {
          line_count: 1,
          total_qty: '1.2345',
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
    notifications = jasmine.createSpyObj<DmisNotificationService>('DmisNotificationService', [
      'showError',
      'showWarning',
      'showSuccess',
    ]);

    await TestBed.configureTestingModule({
      imports: [NoopAnimationsModule, OpsDispatchWorkspaceComponent],
      providers: [
        { provide: OperationsService, useValue: operationsService },
        { provide: DmisNotificationService, useValue: notifications },
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

  it('preloads the transport mode captured during package fulfillment', () => {
    expect(component.transportForm.getRawValue().transport_mode).toBe('TRUCK');
  });

  it('keeps the desktop table gated and preserves four-decimal reservation quantities', () => {
    const host: HTMLElement = fixture.nativeElement;

    expect(host.querySelector('.ops-readiness__table-wrap.desktop-only')).not.toBeNull();
    expect(host.querySelector('.ops-stock-strip__value')?.textContent).toContain('1.2345');
    expect(host.querySelector('tbody .ops-readiness__table-num')?.textContent).toContain('1.2345');
  });

  it('submits the backend-aligned dispatch payload keys', async () => {
    const departureDate = new Date(2026, 2, 26);
    const arrivalDate = new Date(2026, 2, 26);
    component.transportForm.patchValue({
      transport_mode: 'TRUCK',
      driver_name: 'Jane Driver',
      vehicle_id: '1234AB',
      departure_date: departureDate,
      departure_time: '10:00',
      arrival_date: arrivalDate,
      arrival_time: '13:00',
      transport_notes: 'Route via Kingston.',
    });
    fixture.detectChanges();
    await fixture.whenStable();

    expect(component.primaryActionLabel()).toBe('Dispatch Now');

    component.completeDispatchAction();
    fixture.detectChanges();
    await fixture.whenStable();

    expect(operationsService.submitDispatchHandoff).toHaveBeenCalledWith(90, {
      transport_mode: 'TRUCK',
      driver_name: 'Jane Driver',
      vehicle_registration: '1234AB',
      departure_dtime: new Date(2026, 2, 26, 10, 0, 0, 0).toISOString(),
      estimated_arrival_dtime: new Date(2026, 2, 26, 13, 0, 0, 0).toISOString(),
      transport_notes: 'Route via Kingston.',
    });
  });

  it('surfaces maxlength validation errors without native truncation attributes', () => {
    const host: HTMLElement = fixture.nativeElement;

    expect(host.querySelector('input[placeholder="Full name of the driver"]')?.getAttribute('maxlength')).toBeNull();
    expect(host.querySelector('input[placeholder="Plate or fleet no."]')?.getAttribute('maxlength')).toBeNull();
    expect(
      host.querySelector('textarea[placeholder="Route details, special handling, etc."]')
        ?.getAttribute('maxlength'),
    ).toBeNull();

    component.transportForm.patchValue({
      driver_name: 'D'.repeat(101),
      vehicle_id: 'V'.repeat(51),
      transport_notes: 'N'.repeat(501),
    });
    component.transportForm.get('driver_name')?.markAsTouched();
    component.transportForm.get('vehicle_id')?.markAsTouched();
    component.transportForm.get('transport_notes')?.markAsTouched();
    fixture.detectChanges();

    expect(host.textContent).toContain('Max 100 characters.');
    expect(host.textContent).toContain('Max 50 characters.');
    expect(host.textContent).toContain('Max 500 characters.');
  });

  it('surfaces control-level required errors in the custom date/time matchers', () => {
    const departureDateControl = component.transportForm.get('departure_date');
    const arrivalTimeControl = component.transportForm.get('arrival_time');
    departureDateControl?.markAsTouched();
    arrivalTimeControl?.markAsTouched();
    fixture.detectChanges();

    const readinessStep = fixture.debugElement.query(By.directive(OpsDispatchReadinessStepComponent))
      .componentInstance as OpsDispatchReadinessStepComponent;

    expect(readinessStep.departureErrorMatcher.isErrorState(departureDateControl ?? null, null)).toBeTrue();
    expect(readinessStep.estimatedArrivalErrorMatcher.isErrorState(arrivalTimeControl ?? null, null)).toBeTrue();
  });

  it('keeps the readiness step active and shows required transport errors until mandatory fields are complete', () => {
    component.goToDispatchReview();
    fixture.detectChanges();

    const host = fixture.nativeElement as HTMLElement;
    expect(component.currentStepIndex()).toBe(0);
    expect(notifications.showError).toHaveBeenCalledWith('Complete the required transport details before continuing to review.');
    expect(host.textContent).toContain('Vehicle ID is required.');
    expect(host.textContent).toContain('Departure date is required.');
    expect(host.textContent).toContain('Departure time is required.');
    expect(host.textContent).toContain('Estimated arrival date is required.');
    expect(host.textContent).toContain('Estimated arrival time is required.');
  });

  it('marks estimated arrival in error state when it precedes departure', () => {
    component.transportForm.patchValue({
      vehicle_id: '1234AB',
      departure_date: new Date(2026, 2, 26),
      departure_time: '13:00',
      arrival_date: new Date(2026, 2, 26),
      arrival_time: '10:00',
    });
    const arrivalControl = component.transportForm.get('arrival_time');
    arrivalControl?.markAsTouched();
    fixture.detectChanges();

    const readinessStep = fixture.debugElement.query(By.directive(OpsDispatchReadinessStepComponent))
      .componentInstance as OpsDispatchReadinessStepComponent;

    expect(component.transportForm.hasError('arrivalBeforeDeparture')).toBeTrue();
    expect(readinessStep.showArrivalBeforeDepartureError()).toBeTrue();
    expect(readinessStep.estimatedArrivalErrorMatcher.isErrorState(arrivalControl ?? null, null)).toBeTrue();
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('Must be after departure.');
  });

  it('resets form interaction state when loading a new package', () => {
    component.transportForm.markAllAsTouched();
    component.transportForm.markAsDirty();
    component.transportForm.get('vehicle_id')?.markAsDirty();
    component.transportForm.get('vehicle_id')?.markAsTouched();

    component.refresh();
    fixture.detectChanges();

    expect(component.transportForm.pristine).toBeTrue();
    expect(component.transportForm.untouched).toBeTrue();
    expect(component.transportForm.get('vehicle_id')?.untouched).toBeTrue();
  });
});
