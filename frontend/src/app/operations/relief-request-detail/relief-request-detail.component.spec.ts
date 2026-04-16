import { ComponentFixture, TestBed } from '@angular/core/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { ActivatedRoute, Router, convertToParamMap } from '@angular/router';
import { MatDialog } from '@angular/material/dialog';
import { of } from 'rxjs';

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
      items: [],
      packages: [pkg],
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
      'submitRequest',
    ]);
    router = jasmine.createSpyObj<Router>('Router', ['navigate', 'navigateByUrl']);
    notifications = jasmine.createSpyObj<DmisNotificationService>('DmisNotificationService', [
      'showError',
      'showSuccess',
      'showWarning',
    ]);
    appAccess = jasmine.createSpyObj<AppAccessService>('AppAccessService', ['canAccessNavKey']);
    appAccess.canAccessNavKey.and.returnValue(true);
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
});
