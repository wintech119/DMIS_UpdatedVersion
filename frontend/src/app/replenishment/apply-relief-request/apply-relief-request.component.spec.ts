import { ComponentFixture, TestBed } from '@angular/core/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { ActivatedRoute, Router, convertToParamMap } from '@angular/router';
import { of, throwError } from 'rxjs';

import { OperationsService } from '../../operations/services/operations.service';
import { ApplyReliefRequestComponent } from './apply-relief-request.component';

describe('ApplyReliefRequestComponent', () => {
  let fixture: ComponentFixture<ApplyReliefRequestComponent>;
  let operationsService: jasmine.SpyObj<OperationsService>;
  let router: jasmine.SpyObj<Router>;

  async function createComponent(routeId = '40'): Promise<void> {
    await TestBed.configureTestingModule({
      imports: [NoopAnimationsModule, ApplyReliefRequestComponent],
      providers: [
        { provide: OperationsService, useValue: operationsService },
        { provide: Router, useValue: router },
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: { paramMap: convertToParamMap({ id: routeId }) },
          },
        },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(ApplyReliefRequestComponent);
    fixture.detectChanges();
  }

  beforeEach(() => {
    operationsService = jasmine.createSpyObj<OperationsService>('OperationsService', [
      'getRequestAuthorityPreview',
    ]);
    router = jasmine.createSpyObj<Router>('Router', ['navigate']);
  });

  it('navigates to the relief request wizard with bridge state when creation is allowed', async () => {
    operationsService.getRequestAuthorityPreview.and.returnValue(of({
      can_create: true,
      allowed_origin_modes: ['SELF'],
      required_authority_tenant_id: null,
      required_authority_tenant_name: null,
      beneficiary_tenant_id: 12,
      beneficiary_agency_id: 501,
      suggested_event_id: 44,
      blocked_reason_code: null,
    }));

    await createComponent();

    expect(operationsService.getRequestAuthorityPreview).toHaveBeenCalledWith(40);
    expect(router.navigate).toHaveBeenCalledWith(['/operations/relief-requests/new'], {
      state: {
        source_needs_list_id: 40,
        beneficiary_tenant_id: 12,
        beneficiary_agency_id: 501,
        suggested_event_id: 44,
        allowed_origin_modes: ['SELF'],
      },
    });
  });

  it('renders a non-blocking blocked state when authority preview denies creation', async () => {
    operationsService.getRequestAuthorityPreview.and.returnValue(of({
      can_create: false,
      allowed_origin_modes: [],
      required_authority_tenant_id: 7,
      required_authority_tenant_name: 'Parish Authority',
      beneficiary_tenant_id: 12,
      beneficiary_agency_id: 501,
      suggested_event_id: null,
      blocked_reason_code: 'escalation_required',
    }));

    await createComponent();

    const host = fixture.nativeElement as HTMLElement;
    expect(router.navigate).not.toHaveBeenCalled();
    expect(host.textContent).toContain('Relief request cannot be created');
    expect(host.textContent).toContain('A higher-level tenant must create this relief request.');
    expect(host.textContent).toContain('Parish Authority');
  });

  it('renders an error state when the route id is invalid', async () => {
    await createComponent('bogus');

    const host = fixture.nativeElement as HTMLElement;
    expect(operationsService.getRequestAuthorityPreview).not.toHaveBeenCalled();
    expect(router.navigate).not.toHaveBeenCalled();
    expect(host.textContent).toContain('Invalid needs list ID.');
  });

  it('renders an error state when the authority preview call fails', async () => {
    operationsService.getRequestAuthorityPreview.and.returnValue(throwError(() => new Error('offline')));

    await createComponent();

    const host = fixture.nativeElement as HTMLElement;
    expect(router.navigate).not.toHaveBeenCalled();
    expect(host.textContent).toContain('authority pre-check could not be completed');
  });
});
