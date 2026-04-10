import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';

import { AuthSessionService } from '../../core/auth-session.service';
import { AuthRbacService } from './auth-rbac.service';

describe('AuthRbacService', () => {
  function setup() {
    const principal = signal({
      user_id: 'ops-user-1',
      username: 'ops.user',
      roles: ['ODPEM_DIR_PEOD'],
      permissions: ['operations.request.write', 'national.act_cross_tenant'],
      tenant_context: {
        requested_tenant_id: null,
        active_tenant_id: 27,
        active_tenant_code: 'OFFICE-OF-DISASTER-P',
        active_tenant_type: 'NATIONAL',
        is_neoc: false,
        can_read_all_tenants: false,
        can_act_cross_tenant: true,
        memberships: [],
      },
      operations_capabilities: {
        can_create_relief_request: true,
        can_create_relief_request_on_behalf: true,
        relief_request_submission_mode: 'on_behalf_bridge' as const,
        default_requesting_tenant_id: null,
        allowed_origin_modes: ['on_behalf_bridge' as const],
      },
    });

    const authSession = {
      principal: jasmine.createSpy('principal').and.callFake(() => principal()),
      bootstrapping: jasmine.createSpy('bootstrapping').and.returnValue(false),
      principalLoaded: jasmine.createSpy('principalLoaded').and.returnValue(true),
      ensureInitialized: jasmine.createSpy('ensureInitialized').and.returnValue(of(void 0)),
      refreshPrincipal: jasmine.createSpy('refreshPrincipal').and.returnValue(of(void 0)),
    };

    TestBed.configureTestingModule({
      providers: [
        AuthRbacService,
        { provide: AuthSessionService, useValue: authSession },
      ],
    });

    return {
      service: TestBed.inject(AuthRbacService),
      authSession,
      principal,
    };
  }

  it('projects principal roles, permissions, tenant context, and operations capabilities', () => {
    const { service } = setup();

    expect(service.actorRef()).toBe('ops-user-1');
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
    expect(service.loading()).toBeFalse();
  });

  it('delegates bootstrap and refresh requests to the shared auth session service', () => {
    const { service, authSession } = setup();

    service.load();
    service.refresh();
    service.ensureLoaded(true).subscribe();

    expect(authSession.ensureInitialized).toHaveBeenCalled();
    expect(authSession.refreshPrincipal).toHaveBeenCalledTimes(2);
  });
});
