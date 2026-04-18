import { HttpErrorResponse } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { ActivatedRoute, Router, convertToParamMap } from '@angular/router';
import { MatDialog } from '@angular/material/dialog';
import { throwError, of } from 'rxjs';

import { AppAccessService } from '../../core/app-access.service';
import { DmisNotificationService } from '../../replenishment/services/notification.service';
import { EligibilityReviewDetailComponent } from './eligibility-review-detail.component';
import { OperationsService } from '../services/operations.service';

describe('EligibilityReviewDetailComponent', () => {
  let fixture: ComponentFixture<EligibilityReviewDetailComponent>;
  let component: EligibilityReviewDetailComponent;
  let operationsService: jasmine.SpyObj<OperationsService>;
  let dialog: jasmine.SpyObj<MatDialog>;
  let notifications: jasmine.SpyObj<DmisNotificationService>;
  let appAccess: jasmine.SpyObj<AppAccessService>;

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
    requesting_tenant_id: null,
    requesting_agency_id: null,
    beneficiary_tenant_id: null,
    beneficiary_agency_id: null,
    items: [],
    packages: [],
    decision_made: false,
    can_edit: true,
    eligibility_decision: null,
  };

  beforeEach(async () => {
    operationsService = jasmine.createSpyObj<OperationsService>('OperationsService', [
      'createIdempotencyKey',
      'getEligibilityDetail',
      'submitEligibilityDecision',
    ]);
    dialog = jasmine.createSpyObj<MatDialog>('MatDialog', ['open']);
    notifications = jasmine.createSpyObj<DmisNotificationService>('DmisNotificationService', [
      'showError',
      'showWarning',
      'showSuccess',
    ]);
    appAccess = jasmine.createSpyObj<AppAccessService>('AppAccessService', ['canAccessNavKey']);
    appAccess.canAccessNavKey.and.returnValue(true);

    operationsService.getEligibilityDetail.and.returnValue(of(detailResponse));
    operationsService.createIdempotencyKey.and.returnValue('eligibility-decision-70-fixed');
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
        { provide: AppAccessService, useValue: appAccess },
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
    }, 'eligibility-decision-70-fixed');
  });

  it('submits the reject decision with the rejected contract code', () => {
    dialog.open.and.returnValue({
      afterClosed: () => of({ reason: 'Missing documentation' }),
    } as ReturnType<MatDialog['open']>);

    component.deny();

    expect(operationsService.submitEligibilityDecision).toHaveBeenCalledWith(70, {
      decision: 'REJECTED',
      reason: 'Missing documentation',
    }, 'eligibility-decision-70-fixed');
  });

  it('submits the ineligible decision with the ineligible contract code', () => {
    dialog.open.and.returnValue({
      afterClosed: () => of({ reason: 'Outside the event scope' }),
    } as ReturnType<MatDialog['open']>);

    component.markIneligible();

    expect(operationsService.submitEligibilityDecision).toHaveBeenCalledWith(70, {
      decision: 'INELIGIBLE',
      reason: 'Outside the event scope',
    }, 'eligibility-decision-70-fixed');
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

  it('shows a disabled open-fulfillment action for users without fulfillment access', () => {
    appAccess.canAccessNavKey.and.returnValue(false);
    component.detail.set({
      ...detailResponse,
      decision_made: true,
      can_edit: false,
      status_code: 'APPROVED_FOR_FULFILLMENT',
      status_label: 'Approved',
    });

    expect(component.fulfillmentEntryAction()).toEqual(
      jasmine.objectContaining({
        label: 'Open Fulfillment',
        disabled: true,
      }),
    );
  });

  it('switches the fulfillment CTA to continue when package work already exists', () => {
    component.detail.set({
      ...detailResponse,
      decision_made: true,
      can_edit: false,
      status_code: 'APPROVED_FOR_FULFILLMENT',
      status_label: 'Approved',
      reliefpkg_id: 301,
      packages: [
        {
          reliefpkg_id: 301,
          tracking_no: 'PKG-00301',
          reliefrqst_id: 70,
          agency_id: 501,
          eligible_event_id: 12,
          source_warehouse_id: 11,
          to_inventory_id: 12,
          destination_warehouse_name: 'Kingston Warehouse',
          status_code: 'DRAFT',
          status_label: 'Draft',
          dispatch_dtime: null,
          received_dtime: null,
          transport_mode: null,
          comments_text: null,
          version_nbr: 1,
          execution_status: null,
          needs_list_id: null,
          compatibility_bridge: false,
        },
      ],
    });

    expect(component.fulfillmentEntryAction()).toEqual(
      jasmine.objectContaining({
        label: 'Continue from Stock-Aware Selection',
        disabled: false,
      }),
    );
  });

  it('exposes the decision metadata block when the detail includes a recorded decision', () => {
    component.detail.set({
      ...detailResponse,
      decision_made: true,
      can_edit: false,
      status_code: 'APPROVED_FOR_FULFILLMENT',
      status_label: 'Approved',
      eligibility_decision: {
        decision_code: 'APPROVED',
        decision_reason: 'Aligned with SURGE allocation.',
        decided_by_user_id: 'user-9001',
        decided_by_role_code: 'ELIGIBILITY_APPROVER',
        decided_at: '2026-04-15T09:30:00Z',
      },
    });
    fixture.detectChanges();

    expect(component.decisionMetadata()).toEqual({
      decision_code: 'APPROVED',
      decision_reason: 'Aligned with SURGE allocation.',
      decided_by_user_id: 'user-9001',
      decided_by_role_code: 'ELIGIBILITY_APPROVER',
      decided_at: '2026-04-15T09:30:00Z',
    });

    const text = fixture.nativeElement.textContent as string;
    expect(text).toContain('Aligned with SURGE allocation.');
    expect(text).toContain('ELIGIBILITY_APPROVER');
    expect(text).toContain('user-9001');
    expect(text).toContain(component.formatOperationsDateTime('2026-04-15T09:30:00Z'));
  });

  it('hides the decision metadata list when no decision block is attached', () => {
    component.detail.set({
      ...detailResponse,
      decision_made: true,
      can_edit: false,
      status_code: 'REJECTED',
      status_label: 'Rejected',
      eligibility_decision: null,
    });
    fixture.detectChanges();

    expect(component.decisionMetadata()).toBeNull();
    const metaBlock = fixture.nativeElement.querySelector('.ops-detail-meta--inline');
    expect(metaBlock).toBeNull();
  });

  it('hides the decision metadata list when the decision exists without visible audit fields', () => {
    component.detail.set({
      ...detailResponse,
      decision_made: true,
      can_edit: false,
      status_code: 'APPROVED_FOR_FULFILLMENT',
      status_label: 'Approved',
      eligibility_decision: {
        decision_code: 'APPROVED',
        decision_reason: null,
        decided_by_user_id: null,
        decided_by_role_code: null,
        decided_at: null,
      },
    });
    fixture.detectChanges();

    expect(component.decisionMetadata()).toEqual({
      decision_code: 'APPROVED',
      decision_reason: null,
      decided_by_user_id: null,
      decided_by_role_code: null,
      decided_at: null,
    });
    expect(component.decisionAuditMetadata()).toBeNull();
    const metaBlock = fixture.nativeElement.querySelector('.ops-detail-meta--inline');
    expect(metaBlock).toBeNull();
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

  it('reuses the same idempotency key when the same eligibility decision is retried after an ambiguous failure', () => {
    dialog.open.and.returnValue({
      afterClosed: () => of(true),
    } as ReturnType<MatDialog['open']>);
    operationsService.submitEligibilityDecision.and.returnValues(
      throwError(() => new HttpErrorResponse({ status: 504, error: { detail: 'Timed out' } })),
      throwError(() => new HttpErrorResponse({ status: 504, error: { detail: 'Timed out' } })),
    );

    component.approve();
    component.approve();

    expect(operationsService.createIdempotencyKey).toHaveBeenCalledTimes(1);
    expect(operationsService.submitEligibilityDecision.calls.argsFor(0)).toEqual([
      70,
      { decision: 'APPROVED' },
      'eligibility-decision-70-fixed',
    ]);
    expect(operationsService.submitEligibilityDecision.calls.argsFor(1)).toEqual([
      70,
      { decision: 'APPROVED' },
      'eligibility-decision-70-fixed',
    ]);
  });

  it('mints a new idempotency key when the decision payload changes after a failed attempt', () => {
    dialog.open.and.returnValues(
      {
        afterClosed: () => of(true),
      } as ReturnType<MatDialog['open']>,
      {
        afterClosed: () => of({ reason: 'Missing documentation' }),
      } as ReturnType<MatDialog['open']>,
    );
    operationsService.createIdempotencyKey.and.returnValues(
      'eligibility-decision-70-approve',
      'eligibility-decision-70-reject',
    );
    operationsService.submitEligibilityDecision.and.returnValues(
      throwError(() => new HttpErrorResponse({ status: 504, error: { detail: 'Timed out' } })),
      throwError(() => new HttpErrorResponse({ status: 504, error: { detail: 'Timed out' } })),
    );

    component.approve();
    component.deny();

    expect(operationsService.createIdempotencyKey).toHaveBeenCalledTimes(2);
    expect(operationsService.submitEligibilityDecision.calls.argsFor(0)).toEqual([
      70,
      { decision: 'APPROVED' },
      'eligibility-decision-70-approve',
    ]);
    expect(operationsService.submitEligibilityDecision.calls.argsFor(1)).toEqual([
      70,
      { decision: 'REJECTED', reason: 'Missing documentation' },
      'eligibility-decision-70-reject',
    ]);
  });
});
