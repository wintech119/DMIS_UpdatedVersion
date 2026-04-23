import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ActivatedRoute, convertToParamMap, provideRouter, Router } from '@angular/router';
import { provideNoopAnimations } from '@angular/platform-browser/animations';
import { of, throwError } from 'rxjs';

import { AuthSessionService } from '../core/auth-session.service';
import { AuthRbacService } from '../replenishment/services/auth-rbac.service';
import {
  DmisAccessDeniedPageComponent,
  DmisAuthCallbackPageComponent,
  DmisAuthLoginPageComponent,
} from './auth-pages.component';

describe('Auth pages', () => {
  afterEach(() => {
    localStorage.removeItem('dmis_local_harness_user');
    delete (globalThis as typeof globalThis & Record<string, unknown>)['__DMIS_LOCAL_AUTH_HARNESS_BUILD__'];
  });

  function activatedRouteWith(queryParams: Record<string, string> = {}) {
    return {
      snapshot: {
        queryParamMap: convertToParamMap(queryParams),
      },
      queryParamMap: of(convertToParamMap(queryParams)),
    };
  }

  it('shows the non-local OIDC configuration warning on the login page when login is unavailable', async () => {
    const authSession = {
      loginAvailable: signal(false),
      authenticated: signal(false),
      state: signal({
        status: 'unauthenticated' as const,
        message: 'Sign in to continue.',
        configured: false,
        oidcEnabled: false,
      }),
      startLogin: jasmine.createSpy('startLogin'),
    };

    await TestBed.configureTestingModule({
      imports: [DmisAuthLoginPageComponent],
      providers: [
        provideRouter([]),
        provideNoopAnimations(),
        { provide: AuthSessionService, useValue: authSession },
        {
          provide: ActivatedRoute,
          useValue: activatedRouteWith({ reason: 'unauthenticated' }),
        },
      ],
    }).compileComponents();

    const fixture = TestBed.createComponent(DmisAuthLoginPageComponent);
    fixture.detectChanges();

    const element = fixture.nativeElement as HTMLElement;
    expect(element.textContent).toContain('OIDC login is not configured for this deployment');
  });

  it('shows the local harness selector on the login page when local harness mode is available', async () => {
    (globalThis as typeof globalThis & Record<string, unknown>)['__DMIS_LOCAL_AUTH_HARNESS_BUILD__'] = true;
    const authenticated = signal(false);
    const authSession = {
      loginAvailable: signal(false),
      authenticated,
      state: signal({
        status: 'unauthenticated' as const,
        message: 'OIDC login is not configured for this deployment.',
        configured: true,
        oidcEnabled: false,
      }),
      startLogin: jasmine.createSpy('startLogin'),
      refreshPrincipal: jasmine.createSpy('refreshPrincipal').and.callFake(() => {
        authenticated.set(true);
        return of(void 0);
      }),
    };

    await TestBed.configureTestingModule({
      imports: [DmisAuthLoginPageComponent],
      providers: [
        provideRouter([]),
        provideNoopAnimations(),
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: AuthSessionService, useValue: authSession },
        {
          provide: ActivatedRoute,
          useValue: activatedRouteWith({ reason: 'unauthenticated' }),
        },
      ],
    }).compileComponents();

    const router = TestBed.inject(Router);
    const navigateByUrl = spyOn(router, 'navigateByUrl').and.returnValue(Promise.resolve(true));
    const httpMock = TestBed.inject(HttpTestingController);
    const fixture = TestBed.createComponent(DmisAuthLoginPageComponent);
    fixture.detectChanges();
    httpMock.expectOne('/api/v1/auth/local-harness/').flush({
      enabled: true,
      default_user: 'local_system_admin_tst',
      users: [
        {
          user_id: '42',
          username: 'local_odpem_logistics_manager_tst',
          email: 'local.odpem.logistics.manager@example.test',
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
      ],
    });
    fixture.detectChanges();

    const element = fixture.nativeElement as HTMLElement;
    expect(element.textContent).toContain('Use the local harness session to continue.');
    expect(element.textContent).toContain('Local harness mode is active');
    const continueButton = element.querySelector('.auth-primary') as HTMLButtonElement | null;
    expect(continueButton?.textContent).toContain('Continue in local mode');
    expect(element.querySelector('.dev-user-label')?.textContent).toContain('Local test mode');
    expect(element.querySelector('#dev-user-select')?.textContent).toContain('ODPEM_LOGISTICS_MANAGER');

    continueButton?.click();
    await fixture.whenStable();

    expect(authSession.refreshPrincipal).toHaveBeenCalled();
    expect(navigateByUrl).toHaveBeenCalledWith('/replenishment/dashboard', { replaceUrl: true });
    httpMock.verify();
  });

  it('surfaces local harness refresh failures and clears the working state', async () => {
    (globalThis as typeof globalThis & Record<string, unknown>)['__DMIS_LOCAL_AUTH_HARNESS_BUILD__'] = true;
    // Intentional defensive-path coverage: simulate a rejected refresh call so
    // the component's catch branch clears the working state and surfaces the error.
    const authSession = {
      loginAvailable: signal(false),
      authenticated: signal(false),
      state: signal({
        status: 'unauthenticated' as const,
        message: 'Local harness session unavailable.',
        configured: true,
        oidcEnabled: false,
      }),
      startLogin: jasmine.createSpy('startLogin'),
      refreshPrincipal: jasmine.createSpy('refreshPrincipal').and.returnValue(
        throwError(() => new Error('Backend unavailable')),
      ),
    };

    await TestBed.configureTestingModule({
      imports: [DmisAuthLoginPageComponent],
      providers: [
        provideRouter([]),
        provideNoopAnimations(),
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: AuthSessionService, useValue: authSession },
        {
          provide: ActivatedRoute,
          useValue: activatedRouteWith({ reason: 'unauthenticated' }),
        },
      ],
    }).compileComponents();

    const fixture = TestBed.createComponent(DmisAuthLoginPageComponent);
    fixture.detectChanges();
    const httpMock = TestBed.inject(HttpTestingController);
    httpMock.expectOne('/api/v1/auth/local-harness/').flush({
      enabled: true,
      default_user: 'local_system_admin_tst',
      users: [],
    });
    fixture.detectChanges();

    const continueButton = fixture.nativeElement.querySelector('.auth-primary') as HTMLButtonElement;
    continueButton.click();
    await fixture.whenStable();
    fixture.detectChanges();

    expect(authSession.refreshPrincipal).toHaveBeenCalled();
    expect(fixture.componentInstance.localHarnessWorking()).toBeFalse();
    expect(fixture.componentInstance.localHarnessError()).toBe('Backend unavailable');
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('Backend unavailable');
    httpMock.verify();
  });

  it('surfaces the harness state message when refresh completes without authenticating', async () => {
    (globalThis as typeof globalThis & Record<string, unknown>)['__DMIS_LOCAL_AUTH_HARNESS_BUILD__'] = true;
    const state = signal({
      status: 'unauthenticated' as const,
      message: 'Local harness session unavailable.',
      configured: true,
      oidcEnabled: false,
    });
    const authSession = {
      loginAvailable: signal(false),
      authenticated: signal(false),
      state,
      startLogin: jasmine.createSpy('startLogin'),
      refreshPrincipal: jasmine.createSpy('refreshPrincipal').and.callFake(() => {
        state.set({
          ...state(),
          message: 'Backend unavailable',
        });
        return of(void 0);
      }),
    };

    await TestBed.configureTestingModule({
      imports: [DmisAuthLoginPageComponent],
      providers: [
        provideRouter([]),
        provideNoopAnimations(),
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: AuthSessionService, useValue: authSession },
        {
          provide: ActivatedRoute,
          useValue: activatedRouteWith({ reason: 'unauthenticated' }),
        },
      ],
    }).compileComponents();

    const fixture = TestBed.createComponent(DmisAuthLoginPageComponent);
    fixture.detectChanges();
    const httpMock = TestBed.inject(HttpTestingController);
    httpMock.expectOne('/api/v1/auth/local-harness/').flush({
      enabled: true,
      default_user: 'local_system_admin_tst',
      users: [],
    });
    fixture.detectChanges();

    const continueButton = fixture.nativeElement.querySelector('.auth-primary') as HTMLButtonElement;
    continueButton.click();
    await fixture.whenStable();
    fixture.detectChanges();

    expect(authSession.refreshPrincipal).toHaveBeenCalled();
    expect(fixture.componentInstance.localHarnessWorking()).toBeFalse();
    expect(fixture.componentInstance.localHarnessError()).toBe('Backend unavailable');
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('Backend unavailable');
    httpMock.verify();
  });

  it('renders the sign-in button and forwards the sanitized returnUrl when login is available', async () => {
    const authSession = {
      loginAvailable: signal(true),
      authenticated: signal(false),
      state: signal({
        status: 'unauthenticated' as const,
        message: 'Sign in to continue.',
        configured: true,
        oidcEnabled: true,
      }),
      startLogin: jasmine.createSpy('startLogin').and.returnValue(Promise.resolve()),
    };

    await TestBed.configureTestingModule({
      imports: [DmisAuthLoginPageComponent],
      providers: [
        provideRouter([]),
        provideNoopAnimations(),
        { provide: AuthSessionService, useValue: authSession },
        {
          provide: ActivatedRoute,
          useValue: activatedRouteWith({ reason: 'unauthenticated', returnUrl: '/operations/dispatch' }),
        },
      ],
    }).compileComponents();

    const fixture = TestBed.createComponent(DmisAuthLoginPageComponent);
    fixture.detectChanges();

    const button = fixture.nativeElement.querySelector('.auth-primary') as HTMLButtonElement | null;
    expect(button).not.toBeNull();

    button?.click();
    await fixture.whenStable();

    expect(authSession.startLogin).toHaveBeenCalledWith('/operations/dispatch');
  });

  it('redirects authenticated users to a safe returnUrl without rendering the sign-in button', async () => {
    const authSession = {
      loginAvailable: signal(true),
      authenticated: signal(true),
      state: signal({
        status: 'authenticated' as const,
        message: null,
        configured: true,
        oidcEnabled: true,
      }),
      startLogin: jasmine.createSpy('startLogin'),
    };

    await TestBed.configureTestingModule({
      imports: [DmisAuthLoginPageComponent],
      providers: [
        provideRouter([]),
        provideNoopAnimations(),
        { provide: AuthSessionService, useValue: authSession },
        {
          provide: ActivatedRoute,
          useValue: activatedRouteWith({ returnUrl: '/https:%2F%2Fevil.example' }),
        },
      ],
    }).compileComponents();

    const router = TestBed.inject(Router);
    const navigateByUrl = spyOn(router, 'navigateByUrl').and.returnValue(Promise.resolve(true));

    const fixture = TestBed.createComponent(DmisAuthLoginPageComponent);
    fixture.detectChanges();
    await fixture.whenStable();

    expect(navigateByUrl).toHaveBeenCalledWith('/replenishment/dashboard', { replaceUrl: true });
    expect((fixture.nativeElement as HTMLElement).querySelector('.auth-primary')).toBeNull();
  });

  it('shows bootstrapping UI on the callback page without a retry link', async () => {
    const authSession = {
      state: signal({
        status: 'bootstrapping' as const,
        message: null,
        configured: true,
        oidcEnabled: true,
      }),
    };

    await TestBed.configureTestingModule({
      imports: [DmisAuthCallbackPageComponent],
      providers: [
        provideRouter([]),
        provideNoopAnimations(),
        { provide: AuthSessionService, useValue: authSession },
      ],
    }).compileComponents();

    const fixture = TestBed.createComponent(DmisAuthCallbackPageComponent);
    fixture.detectChanges();

    const element = fixture.nativeElement as HTMLElement;
    expect(element.textContent).toContain('validating the authorization response');
    expect(element.querySelector('.auth-link')).toBeNull();
  });

  it('shows redirecting UI on the callback page without a retry link after authentication', async () => {
    const authSession = {
      state: signal({
        status: 'authenticated' as const,
        message: null,
        configured: true,
        oidcEnabled: true,
      }),
    };

    await TestBed.configureTestingModule({
      imports: [DmisAuthCallbackPageComponent],
      providers: [
        provideRouter([]),
        provideNoopAnimations(),
        { provide: AuthSessionService, useValue: authSession },
      ],
    }).compileComponents();

    const fixture = TestBed.createComponent(DmisAuthCallbackPageComponent);
    fixture.detectChanges();

    const element = fixture.nativeElement as HTMLElement;
    expect(element.textContent).toContain('Redirecting you back into DMIS');
    expect(element.querySelector('.auth-link')).toBeNull();
  });

  it('shows the signed-in user on the access denied page', async () => {
    await TestBed.configureTestingModule({
      imports: [DmisAccessDeniedPageComponent],
      providers: [
        provideRouter([]),
        provideNoopAnimations(),
        {
          provide: AuthRbacService,
          useValue: {
            currentUserRef: signal('ops.user'),
          },
        },
      ],
    }).compileComponents();

    const fixture = TestBed.createComponent(DmisAccessDeniedPageComponent);
    fixture.detectChanges();

    const element = fixture.nativeElement as HTMLElement;
    expect(element.textContent).toContain('ops.user');
    expect(element.textContent).toContain('route is not available');
  });
});
