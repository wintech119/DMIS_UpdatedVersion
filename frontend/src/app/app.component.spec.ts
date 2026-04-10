import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { of } from 'rxjs';

import { AppComponent } from './app.component';
import { AuthSessionService } from './core/auth-session.service';
import { AuthRbacService } from './replenishment/services/auth-rbac.service';
import {
  isLocalAuthHarnessHost,
  localAuthHarnessBuildEnabled,
  localAuthHarnessClientEnabled
} from './core/dev-user.interceptor';

describe('AppComponent', () => {
  let httpMock: HttpTestingController;
  let authSession: {
    logoutAvailable: jasmine.Spy;
    logout: jasmine.Spy;
  };

  beforeEach(async () => {
    (globalThis as typeof globalThis & Record<string, unknown>)['__DMIS_LOCAL_AUTH_HARNESS_BUILD__'] = true;
    authSession = {
      logoutAvailable: jasmine.createSpy('logoutAvailable').and.returnValue(false),
      logout: jasmine.createSpy('logout').and.returnValue(Promise.resolve()),
    };
    const authRbac = {
      load: jasmine.createSpy('load'),
      ensureLoaded: jasmine.createSpy('ensureLoaded').and.returnValue(of(void 0)),
      currentUserRef: signal('local_system_admin_tst'),
      actorRef: signal('27'),
      roles: signal(['SYSTEM_ADMINISTRATOR']),
      permissions: signal([
        'masterdata.view',
        'operations.queue.view',
        'replenishment.needs_list.preview',
      ]),
      tenantContext: signal({
        requested_tenant_id: null,
        active_tenant_id: 2,
        active_tenant_code: 'ODPEM-NEOC',
        active_tenant_type: 'NATIONAL',
        is_neoc: true,
        can_read_all_tenants: true,
        can_act_cross_tenant: true,
        memberships: [
          {
            tenant_id: 2,
            tenant_code: 'ODPEM-NEOC',
            tenant_name: 'ODPEM NEOC',
            tenant_type: 'NATIONAL',
            is_primary: true,
            access_level: 'FULL',
          },
        ],
      }),
      operationsCapabilities: signal({
        can_create_relief_request: true,
        can_create_relief_request_on_behalf: true,
        relief_request_submission_mode: 'for_subordinate' as const,
        default_requesting_tenant_id: 2,
        allowed_origin_modes: ['for_subordinate' as const],
      }),
      hasPermission(permission: string) {
        return this.permissions().includes(permission.toLowerCase());
      },
    };

    await TestBed.configureTestingModule({
      imports: [AppComponent],
      providers: [
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: AuthSessionService, useValue: authSession },
        { provide: AuthRbacService, useValue: authRbac },
      ],
    }).compileComponents();

    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
    localStorage.clear();
    delete (globalThis as typeof globalThis & Record<string, unknown>)['__DMIS_LOCAL_AUTH_HARNESS_BUILD__'];
  });

  it('should create the app', () => {
    const fixture = TestBed.createComponent(AppComponent);
    fixture.detectChanges();
    flushInitialRequests(httpMock);
    const app = fixture.componentInstance;
    expect(app).toBeTruthy();
  });

  it('should render topbar root label', () => {
    const fixture = TestBed.createComponent(AppComponent);
    fixture.detectChanges();
    flushInitialRequests(httpMock);
    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.querySelector('.breadcrumb-root')?.textContent).toContain('DMIS');
  });

  it('shows local test mode options when the harness endpoint is enabled', () => {
    const fixture = TestBed.createComponent(AppComponent);
    fixture.detectChanges();
    httpMock.expectOne('/api/v1/auth/local-harness/').flush({
      enabled: true,
      default_user: 'local_system_admin_tst',
      users: [
        {
          user_id: '42',
          username: 'local_odpem_deputy_director_tst',
          email: 'natalie.williams+national.deputy-director@odpem.gov.jm',
          roles: ['ODPEM_DDG'],
          memberships: [
            {
              tenant_id: 2,
              tenant_code: 'ODPEM-NEOC',
              tenant_name: 'ODPEM NEOC',
              tenant_type: 'NEOC',
              is_primary: true,
              access_level: 'FULL',
            },
          ],
        },
        {
          user_id: '64',
          username: 'local_odpem_logistics_manager_tst',
          email: 'kemar.campbell+national.logistics-manager@odpem.gov.jm',
          roles: ['ODPEM_LOGISTICS_MANAGER'],
          memberships: [
            {
              tenant_id: 2,
              tenant_code: 'ODPEM-NEOC',
              tenant_name: 'ODPEM NEOC',
              tenant_type: 'NEOC',
              is_primary: true,
              access_level: 'FULL',
            },
          ],
        },
        {
          user_id: '91',
          username: 'relief_jrc_requester_tst',
          email: 'alicia.bennett+jrc.requester@agency.example.org',
          roles: ['AGENCY_DISTRIBUTOR'],
          memberships: [
            {
              tenant_id: 19,
              tenant_code: 'JRC',
              tenant_name: 'Jamaica Red Cross',
              tenant_type: 'NGO',
              is_primary: true,
              access_level: 'FULL',
            },
          ],
        },
      ],
    });
    fixture.detectChanges();

    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.querySelector('.dev-user-label')?.textContent).toContain('Local test mode');
    const select = compiled.querySelector('#dev-user-select') as HTMLSelectElement | null;
    expect(select).not.toBeNull();
    expect(select?.options[0].textContent).toContain('local_system_admin_tst');
    expect(select?.options[1].textContent).toContain('ODPEM_DDG');
    expect(select?.options[1].textContent).toContain('ODPEM-NEOC');
    expect(select?.options[2].textContent).toContain('ODPEM_LOGISTICS_MANAGER');
    expect(select?.options[2].textContent).toContain('ODPEM-NEOC');
    expect(select?.options[3].textContent).toContain('AGENCY_DISTRIBUTOR');
    expect(select?.options[3].textContent).toContain('JRC');
  });

  it('does not load the local harness UI when the build flag is disabled', () => {
    (globalThis as typeof globalThis & Record<string, unknown>)['__DMIS_LOCAL_AUTH_HARNESS_BUILD__'] = false;

    const fixture = TestBed.createComponent(AppComponent);
    fixture.detectChanges();
    httpMock.expectNone('/api/v1/auth/local-harness/');
    fixture.detectChanges();

    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.querySelector('.dev-user-label')).toBeNull();
  });

  it('limits the local harness client gate to local browser hosts', () => {
    delete (globalThis as typeof globalThis & Record<string, unknown>)['__DMIS_LOCAL_AUTH_HARNESS_BUILD__'];

    expect(localAuthHarnessBuildEnabled()).toBeFalse();
    expect(localAuthHarnessClientEnabled({ hostname: 'localhost' })).toBeFalse();

    (globalThis as typeof globalThis & Record<string, unknown>)['__DMIS_LOCAL_AUTH_HARNESS_BUILD__'] = true;
    expect(localAuthHarnessBuildEnabled()).toBeTrue();
    expect(localAuthHarnessClientEnabled({ hostname: 'localhost' })).toBeTrue();
    expect(isLocalAuthHarnessHost({ hostname: 'shared-dev.dmis.example.org' })).toBeFalse();
    expect(localAuthHarnessClientEnabled({ hostname: 'shared-dev.dmis.example.org' })).toBeFalse();
  });
});

function flushInitialRequests(httpMock: HttpTestingController): void {
  httpMock.expectOne('/api/v1/auth/local-harness/').flush({ enabled: false });
}
