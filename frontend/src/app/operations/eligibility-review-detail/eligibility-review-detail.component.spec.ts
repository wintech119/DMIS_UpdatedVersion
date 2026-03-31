import { ComponentFixture, TestBed } from '@angular/core/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { ActivatedRoute, Router, convertToParamMap } from '@angular/router';
import { MatDialog } from '@angular/material/dialog';
import { throwError, of } from 'rxjs';

import { DmisNotificationService } from '../../replenishment/services/notification.service';
import { EligibilityReviewDetailComponent } from './eligibility-review-detail.component';
import { OperationsService } from '../services/operations.service';

describe('EligibilityReviewDetailComponent', () => {
  let fixture: ComponentFixture<EligibilityReviewDetailComponent>;
  let component: EligibilityReviewDetailComponent;
  let operationsService: jasmine.SpyObj<OperationsService>;
  let dialog: jasmine.SpyObj<MatDialog>;
  let notifications: jasmine.SpyObj<DmisNotificationService>;

  const detailResponse = {
    reliefrqst_id: 70,
    tracking_no: 'RQ00070',
    agency_id: 501,
    agency_name: 'FFP Shelter',
    eligible_event_id: 12,
    event_name: 'Flood Response',
    urgency_ind: 'H' as const,
    status_code: 'UNDER_ELIGIBILITY_REVIEW' as const,
    status_label: 'Under Eligibility Review',
    request_date: '2026-03-26',
    create_dtime: '2026-03-26T09:00:00Z',
    review_dtime: null,
    action_dtime: null,
    rqst_notes_text: 'Need shelter kits',
    review_notes_text: null,
    status_reason_desc: null,
    version_nbr: 1,
    item_count: 1,
    total_requested_qty: '4.0000',
    total_issued_qty: '0.0000',
    reliefpkg_id: null,
    package_tracking_no: null,
    package_status: null,
    execution_status: null,
    needs_list_id: null,
    compatibility_bridge: false,
    request_mode: null,
    authority_context: null,
    items: [],
    packages: [],
    decision_made: false,
    can_edit: true,
  };

  beforeEach(async () => {
    operationsService = jasmine.createSpyObj<OperationsService>('OperationsService', [
      'getEligibilityDetail',
      'submitEligibilityDecision',
    ]);
    dialog = jasmine.createSpyObj<MatDialog>('MatDialog', ['open']);
    notifications = jasmine.createSpyObj<DmisNotificationService>('DmisNotificationService', [
      'showError',
      'showWarning',
      'showSuccess',
    ]);

    operationsService.getEligibilityDetail.and.returnValue(of(detailResponse));
    operationsService.submitEligibilityDecision.and.returnValue(of({
      ...detailResponse,
      decision_made: true,
      can_edit: false,
      status_code: 'APPROVED_FOR_FULFILLMENT' as const,
      status_label: 'Approved',
    }));

    await TestBed.configureTestingModule({
      imports: [NoopAnimationsModule, EligibilityReviewDetailComponent],
      providers: [
        { provide: OperationsService, useValue: operationsService },
        { provide: MatDialog, useValue: dialog },
        { provide: DmisNotificationService, useValue: notifications },
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: {
              paramMap: convertToParamMap({ reliefrqstId: '70' }),
            },
          },
        },
        {
          provide: Router,
          useValue: jasmine.createSpyObj('Router', ['navigate']),
        },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(EligibilityReviewDetailComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('submits the approve decision with the backend contract code', () => {
    dialog.open.and.returnValue({
      afterClosed: () => of(true),
    } as ReturnType<MatDialog['open']>);

    component.approve();

    expect(operationsService.submitEligibilityDecision).toHaveBeenCalledWith(70, {
      decision: 'APPROVED',
    });
  });

  it('submits the reject decision with the rejected contract code', () => {
    dialog.open.and.returnValue({
      afterClosed: () => of({ reason: 'Missing documentation' }),
    } as ReturnType<MatDialog['open']>);

    component.deny();

    expect(operationsService.submitEligibilityDecision).toHaveBeenCalledWith(70, {
      decision: 'REJECTED',
      reason: 'Missing documentation',
    });
  });

  it('submits the ineligible decision with the ineligible contract code', () => {
    dialog.open.and.returnValue({
      afterClosed: () => of({ reason: 'Outside the event scope' }),
    } as ReturnType<MatDialog['open']>);

    component.markIneligible();

    expect(operationsService.submitEligibilityDecision).toHaveBeenCalledWith(70, {
      decision: 'INELIGIBLE',
      reason: 'Outside the event scope',
    });
  });

  it('treats approved-for-fulfillment requests as fulfillment-ready in the workflow', () => {
    component.detail.set({
      ...detailResponse,
      decision_made: true,
      can_edit: false,
      status_code: 'APPROVED_FOR_FULFILLMENT',
      status_label: 'Approved',
    });

    const fulfillmentStep = component.workflow().find((step) => step.label === 'Fulfillment');

    expect(fulfillmentStep).toEqual(
      jasmine.objectContaining({
        detail: 'Ready for packing',
        tone: 'success',
      }),
    );
  });

  it('surfaces nested validation errors from the decision submit response', () => {
    dialog.open.and.returnValue({
      afterClosed: () => of(true),
    } as ReturnType<MatDialog['open']>);
    operationsService.submitEligibilityDecision.and.returnValue(
      throwError(() => ({
        error: {
          errors: {
            decision: [{ message: 'Decision reason is required.' }],
          },
        },
      })),
    );

    component.approve();

    expect(notifications.showError).toHaveBeenCalledWith('Decision reason is required.');
  });
});
