import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { AuthRbacService } from './auth-rbac.service';

describe('AuthRbacService', () => {
  let service: AuthRbacService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        AuthRbacService,
        provideHttpClient(),
        provideHttpClientTesting(),
      ],
    });

    service = TestBed.inject(AuthRbacService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('stores tenant context and operations capabilities from whoami', () => {
    service.load();

    const request = httpMock.expectOne('/api/v1/auth/whoami/');
    expect(request.request.method).toBe('GET');
    request.flush({
      user_id: 'ops-user-1',
      username: 'ops.user',
      roles: ['ODPEM_DIR_PEOD'],
      permissions: ['operations.request.write', 'national.act_cross_tenant'],
      tenant_context: {
        active_tenant_id: 27,
        active_tenant_code: 'OFFICE-OF-DISASTER-P',
        active_tenant_type: 'NATIONAL',
        can_act_cross_tenant: true,
        memberships: [
          {
            tenant_id: 27,
            tenant_code: 'OFFICE-OF-DISASTER-P',
            tenant_name: 'ODPEM',
            tenant_type: 'NATIONAL',
            is_primary: true,
            access_level: 'WRITE',
          },
        ],
      },
      operations_capabilities: {
        can_create_relief_request: true,
        can_create_relief_request_on_behalf: true,
        relief_request_submission_mode: 'on_behalf_bridge',
        default_requesting_tenant_id: null,
      },
    });

    expect(service.currentUserRef()).toBe('ops.user');
    expect(service.roles()).toEqual(['ODPEM_DIR_PEOD']);
    expect(service.permissions()).toEqual(['operations.request.write', 'national.act_cross_tenant']);
    expect(service.tenantContext()).toEqual(jasmine.objectContaining({
      active_tenant_id: 27,
      active_tenant_code: 'OFFICE-OF-DISASTER-P',
      can_act_cross_tenant: true,
    }));
    expect(service.operationsCapabilities()).toEqual({
      can_create_relief_request: true,
      can_create_relief_request_on_behalf: true,
      relief_request_submission_mode: 'on_behalf_bridge',
      default_requesting_tenant_id: null,
      allowed_origin_modes: ['on_behalf_bridge'],
    });
    expect(service.loaded()).toBeTrue();
  });

  it('normalizes subordinate request mode without treating it as unavailable', () => {
    service.load();

    const request = httpMock.expectOne('/api/v1/auth/whoami/');
    request.flush({
      operations_capabilities: {
        can_create_relief_request: true,
        can_create_relief_request_on_behalf: true,
        relief_request_submission_mode: 'for_subordinate',
        default_requesting_tenant_id: 42,
      },
    });

    expect(service.operationsCapabilities()).toEqual({
      can_create_relief_request: true,
      can_create_relief_request_on_behalf: true,
      relief_request_submission_mode: 'for_subordinate',
      default_requesting_tenant_id: 42,
      allowed_origin_modes: ['for_subordinate'],
    });
  });
});
