import { ComponentFixture, TestBed } from '@angular/core/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { HttpErrorResponse, HttpHeaders } from '@angular/common/http';
import { ActivatedRoute, Router, convertToParamMap } from '@angular/router';
import { MatDialog } from '@angular/material/dialog';
import { of, throwError } from 'rxjs';

import { AppAccessService } from '../../core/app-access.service';
import { DmisNotificationService } from '../../replenishment/services/notification.service';
import { OperationsService } from '../services/operations.service';
import { PackageSummary, RequestDetailResponse } from '../models/operations.model';
import { ReliefRequestDetailComponent } from './relief-request-detail.component';

describe('ReliefRequestDetailComponent', () => {
  let fixture: ComponentFixture<ReliefRequestDetailComponent>;
  let component: ReliefRequestDetailComponent;
  let operationsService: jasmine.SpyObj<OperationsService>;
  let router: jasmine.SpyObj<Router>;
  let notifications: jasmine.SpyObj<DmisNotificationService>;
  let appAccess: jasmine.SpyObj<AppAccessService>;
  let dialog: jasmine.SpyObj<MatDialog>;

  const basePackage: PackageSummary = {
    reliefpkg_id: 95027,
    tracking_no: 'PK95027',
    reliefrqst_id: 95009,
    agency_id: 8,
    eligible_event_id: 4,
    source_warehouse_id: 1,
    to_inventory_id: 3,
    destination_warehouse_name: 'Kingston Warehouse',
    status_code: 'DRAFT',
    status_label: 'Draft',
    dispatch_dtime: null,
    received_dtime: null,
    transport_mode: null,
    comments_text: null,
    version_nbr: 1,
    execution_status: 'DRAFT',
    needs_list_id: null,
    compatibility_bridge: false,
  };

  function buildDetail(
    packageOverrides: Partial<PackageSummary>,
    detailOverrides: Partial<RequestDetailResponse> = {},
  ): RequestDetailResponse {
    const pkg: PackageSummary = { ...basePackage, ...packageOverrides };
    return {
      reliefrqst_id: 95009,
      tracking_no: 'RQ95009',
      agency_id: 8,
      agency_name: 'Parish Shelter',
      eligible_event_id: 4,
      event_name: 'Flood Response',
      urgency_ind: 'H',
      status_code: 'APPROVED_FOR_FULFILLMENT',
      status_label: 'Approved',
      request_date: '2026-03-26',
      create_dtime: '2026-03-26T08:00:00Z',
      review_dtime: '2026-03-26T09:00:00Z',
      action_dtime: null,
      rqst_notes_text: null,
      review_notes_text: null,
      status_reason_desc: null,
      version_nbr: 1,
      item_count: 1,
      total_requested_qty: '650.0000',
      total_issued_qty: '0.0000',
      reliefpkg_id: pkg.reliefpkg_id,
      package_tracking_no: pkg.tracking_no,
      package_status: pkg.status_code,
      execution_status: pkg.execution_status,
      needs_list_id: null,
      compatibility_bridge: false,
      request_mode: null,
      authority_context: null,
      requesting_tenant_id: 3,
      requesting_agency_id: 17,
      beneficiary_tenant_id: 5,
      beneficiary_agency_id: 21,
      source_needs_list_id: null,
      items: [],
      packages: [pkg],
      audit_timeline: [],
      ...detailOverrides,
    };
  }

  async function createComponent(detail: RequestDetailResponse): Promise<void> {
    operationsService.getRequest.and.returnValue(of(detail));

    await TestBed.configureTestingModule({
      imports: [NoopAnimationsModule, ReliefRequestDetailComponent],
      providers: [
        { provide: OperationsService, useValue: operationsService },
        { provide: DmisNotificationService, useValue: notifications },
        { provide: AppAccessService, useValue: appAccess },
        { provide: MatDialog, useValue: dialog },
        { provide: Router, useValue: router },
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: { paramMap: convertToParamMap({ reliefrqstId: '95009' }) },
          },
        },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(ReliefRequestDetailComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  }

  beforeEach(() => {
    operationsService = jasmine.createSpyObj<OperationsService>('OperationsService', [
      'getRequest',
      'createIdempotencyKey',
      'submitRequest',
      'cancelRequest',
    ]);
    operationsService.createIdempotencyKey.and.returnValue('request-submit-95009-fixed');
    router = jasmine.createSpyObj<Router>('Router', ['navigate', 'navigateByUrl']);
    notifications = jasmine.createSpyObj<DmisNotificationService>('DmisNotificationService', [
      'showError',
      'showSuccess',
      'showWarning',
    ]);
    appAccess = jasmine.createSpyObj<AppAccessService>('AppAccessService', [
      'canAccessNavKey',
      'canEditReliefRequestDraft',
      'canSubmitReliefRequest',
      'canCancelReliefRequest',
    ]);
    appAccess.canAccessNavKey.and.returnValue(true);
    appAccess.canEditReliefRequestDraft.and.returnValue(true);
    appAccess.canSubmitReliefRequest.and.returnValue(true);
    appAccess.canCancelReliefRequest.and.returnValue(true);
    dialog = jasmine.createSpyObj<MatDialog>('MatDialog', ['open']);
  });

  it('disables the Open dispatch workspace button for a DRAFT package', async () => {
    await createComponent(buildDetail({ status_code: 'DRAFT', execution_status: 'DRAFT' }));

    const pkg = component.request()!.packages[0];
    const action = component.packageDispatchAction(pkg);

    expect(action.disabled).toBeTrue();
    expect(action.disabledReason).toBe(
      'Dispatch preparation unlocks after the package is committed in fulfillment.',
    );

    const host = fixture.nativeElement as HTMLElement;
    const dispatchButton = host.querySelector<HTMLButtonElement>(
      'button[aria-label="Open dispatch workspace"]',
    );
    expect(dispatchButton).not.toBeNull();
    expect(dispatchButton?.disabled).toBeTrue();
  });

  it('does not navigate when openDispatch is invoked for a DRAFT package', async () => {
    await createComponent(buildDetail({ status_code: 'DRAFT', execution_status: 'DRAFT' }));

    component.openDispatch(component.request()!.packages[0]);

    expect(router.navigate).not.toHaveBeenCalled();
  });

  it('disables the dispatch button while the execution status is PENDING_OVERRIDE_APPROVAL', async () => {
    await createComponent(
      buildDetail({ status_code: 'DRAFT', execution_status: 'PENDING_OVERRIDE_APPROVAL' }),
    );

    const pkg = component.request()!.packages[0];
    expect(component.packageDispatchAction(pkg).disabled).toBeTrue();
  });

  it('enables the dispatch button and navigates once the package is COMMITTED', async () => {
    await createComponent(
      buildDetail({ status_code: 'COMMITTED', execution_status: 'COMMITTED' }),
    );

    const pkg = component.request()!.packages[0];
    expect(component.packageDispatchAction(pkg).disabled).toBeFalse();

    const host = fixture.nativeElement as HTMLElement;
    const dispatchButton = host.querySelector<HTMLButtonElement>(
      'button[aria-label="Open dispatch workspace"]',
    );
    expect(dispatchButton?.disabled).toBeFalse();

    component.openDispatch(pkg);
    expect(router.navigate).toHaveBeenCalledWith(['/operations/dispatch', pkg.reliefpkg_id]);
  });

  it('enables the dispatch button once the package is READY_FOR_DISPATCH', async () => {
    await createComponent(
      buildDetail({ status_code: 'READY_FOR_DISPATCH', execution_status: 'READY_FOR_DISPATCH' }),
    );

    expect(
      component.packageDispatchAction(component.request()!.packages[0]).disabled,
    ).toBeFalse();
  });

  it('renders request mode on the detail page', async () => {
    await createComponent(buildDetail({}, { request_mode: 'FOR_SUBORDINATE' }));

    const host = fixture.nativeElement as HTMLElement;
    const strip = host.querySelector('.ops-context-strip');
    expect(strip).not.toBeNull();
    expect(strip?.getAttribute('aria-label')).toBe('Request intake context');
    expect(strip?.textContent).toContain('Request mode');
    expect(strip?.textContent).toContain('For subordinate');
  });

  it('hides package fulfillment entry when a terminal request has no package relationship', async () => {
    await createComponent(
      buildDetail(
        {},
        {
          status_code: 'FULFILLED',
          reliefpkg_id: null,
          package_tracking_no: null,
          package_status: null,
          execution_status: null,
          packages: [],
        },
      ),
    );

    expect(component.fulfillmentEntryAction()).toBeNull();

    const host = fixture.nativeElement as HTMLElement;
    const actionButtons = Array.from(host.querySelectorAll('.ops-hero__actions button'))
      .map((button) => (button.textContent ?? '').trim());
    expect(actionButtons.some((label) => label.includes('Fulfillment'))).toBeFalse();
  });

  it('continues package fulfillment for a terminal request when an existing package is present', async () => {
    await createComponent(buildDetail({}, { status_code: 'FULFILLED' }));

    expect(component.fulfillmentEntryAction()).toEqual(
      jasmine.objectContaining({
        label: 'Continue from Stock-Aware Selection',
        disabled: false,
      }),
    );
  });

  it('keeps the Submitted lifecycle step pending while the request is still a draft', async () => {
    await createComponent(
      buildDetail(
        { status_code: 'DRAFT', execution_status: 'DRAFT' },
        { status_code: 'DRAFT', review_dtime: null, create_dtime: '2026-03-26T08:00:00Z' },
      ),
    );

    const submittedStep = component.workflow().find((step) => step.label === 'Submitted')!;
    expect(submittedStep.tone).toBe('muted');
    expect(submittedStep.detail).toBe('Pending submit');
    expect(submittedStep.timestamp).toBeUndefined();
  });

  it('marks the Submitted lifecycle step complete once the request advances past DRAFT', async () => {
    await createComponent(
      buildDetail(
        {},
        { status_code: 'UNDER_ELIGIBILITY_REVIEW', review_dtime: null },
      ),
    );

    const submittedStep = component.workflow().find((step) => step.label === 'Submitted')!;
    expect(submittedStep.tone).toBe('review');
    expect(submittedStep.detail).toBe('Sent to review');
  });

  it('renders draft write actions only when the matching request-side permissions are granted', async () => {
    await createComponent(
      buildDetail({ status_code: 'DRAFT', execution_status: 'DRAFT' }, { status_code: 'DRAFT' }),
    );

    const host = fixture.nativeElement as HTMLElement;
    const actionButtons = () => Array.from(host.querySelectorAll('.ops-hero__actions button'))
      .map((button) => (button.textContent ?? '').trim());

    expect(actionButtons().some((label) => label.includes('Edit Draft'))).toBeTrue();
    expect(actionButtons().some((label) => label.includes('Submit for Review'))).toBeTrue();
  });

  it('cancels a cancellable relief request and refreshes the detail state', async () => {
    const updated = buildDetail(
      { status_code: 'DRAFT', execution_status: 'DRAFT' },
      {
        status_code: 'CANCELLED',
        packages: [],
        audit_timeline: [
          {
            event_kind: 'ACTION_AUDIT',
            from_status_code: null,
            to_status_code: null,
            action_code: 'REQUEST_CANCELLED',
            action_reason: 'Duplicate intake',
            occurred_at: '2026-03-26T10:00:00Z',
            actor_role_code: 'AGENCY_DISTRIBUTOR',
            actor_user_label: 'User ...er-a',
          },
        ],
      },
    );
    await createComponent(
      buildDetail({ status_code: 'DRAFT', execution_status: 'DRAFT' }, { status_code: 'DRAFT' }),
    );
    operationsService.createIdempotencyKey.and.returnValue('request-cancel-95009-fixed');
    dialog.open.and.returnValue({
      afterClosed: () => of({ reason: '  Duplicate intake  ' }),
    } as ReturnType<MatDialog['open']>);
    operationsService.cancelRequest.and.returnValue(of(updated));

    component.cancelRequest();

    expect(operationsService.createIdempotencyKey).toHaveBeenCalledWith('request-cancel', 95009);
    expect(operationsService.cancelRequest).toHaveBeenCalledWith(
      95009,
      'Duplicate intake',
      'request-cancel-95009-fixed',
    );
    expect(component.request()?.status_code).toBe('CANCELLED');
    expect(component.auditTimeline()[0].action_code).toBe('REQUEST_CANCELLED');
    expect(notifications.showSuccess).toHaveBeenCalledWith('Request cancelled.');
  });

  it('renders no Cancel Request action when the actor lacks operations.request.cancel', async () => {
    appAccess.canCancelReliefRequest.and.returnValue(false);
    await createComponent(
      buildDetail({ status_code: 'DRAFT', execution_status: 'DRAFT' }, { status_code: 'DRAFT' }),
    );

    const host = fixture.nativeElement as HTMLElement;
    const actionLabels = Array.from(host.querySelectorAll('.ops-hero__actions button'))
      .map((button) => (button.textContent ?? '').trim());

    expect(actionLabels.some((label) => label.includes('Cancel Request'))).toBeFalse();
  });

  it('shows an inline not-cancellable error when cancel returns request_not_cancellable', async () => {
    await createComponent(
      buildDetail({ status_code: 'DRAFT', execution_status: 'DRAFT' }, { status_code: 'DRAFT' }),
    );
    dialog.open.and.returnValue({
      afterClosed: () => of({ reason: 'Duplicate intake' }),
    } as ReturnType<MatDialog['open']>);
    operationsService.cancelRequest.and.returnValue(throwError(() => new HttpErrorResponse({
      status: 409,
      error: { errors: { status: { code: 'request_not_cancellable' } } },
    })));

    component.cancelRequest();
    fixture.detectChanges();

    expect(component.cancelError()).toBe('This request is no longer cancellable.');
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('This request is no longer cancellable.');
  });

  it('shows an inline unavailable error when cancel returns 404', async () => {
    await createComponent(
      buildDetail({ status_code: 'DRAFT', execution_status: 'DRAFT' }, { status_code: 'DRAFT' }),
    );
    dialog.open.and.returnValue({
      afterClosed: () => of({ reason: 'Duplicate intake' }),
    } as ReturnType<MatDialog['open']>);
    operationsService.cancelRequest.and.returnValue(throwError(() => new HttpErrorResponse({ status: 404 })));

    component.cancelRequest();
    fixture.detectChanges();

    expect(component.cancelError()).toBe('Request no longer available.');
  });

  it('surfaces Retry-After when cancel is rate limited', async () => {
    await createComponent(
      buildDetail({ status_code: 'DRAFT', execution_status: 'DRAFT' }, { status_code: 'DRAFT' }),
    );
    dialog.open.and.returnValue({
      afterClosed: () => of({ reason: 'Duplicate intake' }),
    } as ReturnType<MatDialog['open']>);
    operationsService.cancelRequest.and.returnValue(throwError(() => new HttpErrorResponse({
      status: 429,
      headers: new HttpHeaders({ 'Retry-After': '12' }),
    })));

    component.cancelRequest();
    fixture.detectChanges();

    expect(component.cancelError()).toBe('Too many cancel attempts. Retry in 12 seconds.');
  });

  it('hides Edit Draft when the user lacks operations.request.edit.draft', async () => {
    appAccess.canEditReliefRequestDraft.and.returnValue(false);
    await createComponent(
      buildDetail({ status_code: 'DRAFT', execution_status: 'DRAFT' }, { status_code: 'DRAFT' }),
    );

    const host = fixture.nativeElement as HTMLElement;
    const actionButtons = Array.from(host.querySelectorAll('.ops-hero__actions button'))
      .map((button) => (button.textContent ?? '').trim());

    expect(actionButtons.some((label) => label.includes('Edit Draft'))).toBeFalse();
    expect(actionButtons.some((label) => label.includes('Submit for Review'))).toBeTrue();
  });

  it('hides Submit for Review when the user lacks operations.request.submit', async () => {
    appAccess.canSubmitReliefRequest.and.returnValue(false);
    await createComponent(
      buildDetail({ status_code: 'DRAFT', execution_status: 'DRAFT' }, { status_code: 'DRAFT' }),
    );

    const host = fixture.nativeElement as HTMLElement;
    const actionButtons = Array.from(host.querySelectorAll('.ops-hero__actions button'))
      .map((button) => (button.textContent ?? '').trim());

    expect(actionButtons.some((label) => label.includes('Edit Draft'))).toBeTrue();
    expect(actionButtons.some((label) => label.includes('Submit for Review'))).toBeFalse();
  });

  it('renders no draft write actions when the user holds neither request-side permission', async () => {
    appAccess.canEditReliefRequestDraft.and.returnValue(false);
    appAccess.canSubmitReliefRequest.and.returnValue(false);
    await createComponent(
      buildDetail({ status_code: 'DRAFT', execution_status: 'DRAFT' }, { status_code: 'DRAFT' }),
    );

    const host = fixture.nativeElement as HTMLElement;
    const actionLabels = Array.from(host.querySelectorAll('.ops-hero__actions button'))
      .map((button) => (button.textContent ?? '').trim());

    expect(actionLabels.some((label) => label.includes('Edit Draft'))).toBeFalse();
    expect(actionLabels.some((label) => label.includes('Submit for Review'))).toBeFalse();
  });

  it('renders tenant and agency context on the detail page', async () => {
    await createComponent(
      buildDetail(
        {},
        {
          request_mode: 'FOR_SUBORDINATE',
          requesting_tenant_id: 3,
          requesting_agency_id: 17,
          beneficiary_tenant_id: 5,
          beneficiary_agency_id: 21,
        },
      ),
    );

    const host = fixture.nativeElement as HTMLElement;
    const strip = host.querySelector('.ops-context-strip');
    const text = strip?.textContent ?? '';
    expect(text).toContain('Requesting tenant 3');
    expect(text).toContain('agency 17');
    expect(text).toContain('Beneficiary tenant 5');
    expect(text).toContain('agency 21');
  });

  it('renders the chronological audit timeline with redacted actor fallback', async () => {
    await createComponent(
      buildDetail(
        {},
        {
          audit_timeline: [
            {
              event_kind: 'STATUS_TRANSITION',
              from_status_code: 'DRAFT',
              to_status_code: 'SUBMITTED',
              action_code: null,
              action_reason: null,
              occurred_at: '2026-03-26T08:30:00Z',
              actor_role_code: 'REQUESTER',
              actor_user_label: 'Kemar Blake',
            },
            {
              event_kind: 'ACTION_AUDIT',
              from_status_code: null,
              to_status_code: null,
              action_code: 'REQUEST_CANCELLED',
              action_reason: 'Duplicate entry.',
              occurred_at: '2026-03-26T09:00:00Z',
              actor_role_code: null,
              actor_user_label: null,
            },
          ],
        },
      ),
    );

    const host = fixture.nativeElement as HTMLElement;
    expect(host.textContent).toContain('Audit timeline');
    expect(host.textContent).toContain('Draft to Submitted');
    expect(host.textContent).toContain('REQUESTER | Kemar Blake');
    expect(host.textContent).toContain('Request Cancelled');
    expect(host.textContent).toContain('External actor');
    expect(host.textContent).toContain('Duplicate entry.');
  });

  it('reuses the same idempotency key when submit-for-review is retried after an ambiguous failure', async () => {
    await createComponent(
      buildDetail(
        { status_code: 'DRAFT', execution_status: 'DRAFT' },
        { status_code: 'DRAFT', status_label: 'Draft', review_dtime: null },
      ),
    );
    dialog.open.and.returnValue({
      afterClosed: () => of(true),
    } as ReturnType<MatDialog['open']>);
    operationsService.submitRequest.and.returnValues(
      throwError(() => new HttpErrorResponse({ status: 504, error: { detail: 'Timed out' } })),
      throwError(() => new HttpErrorResponse({ status: 504, error: { detail: 'Timed out' } })),
    );

    component.submitForReview();
    component.submitForReview();

    expect(operationsService.createIdempotencyKey).toHaveBeenCalledTimes(1);
    expect(operationsService.submitRequest.calls.argsFor(0)).toEqual([95009, 'request-submit-95009-fixed']);
    expect(operationsService.submitRequest.calls.argsFor(1)).toEqual([95009, 'request-submit-95009-fixed']);
  });
});
