import { TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { asyncScheduler, firstValueFrom, isObservable, of, scheduled } from 'rxjs';

import { AppAccessService } from './app-access.service';
import { AuthSessionService, AuthSessionState } from './auth-session.service';
import { appAccessGuard, appAccessMatchGuard, normalizeRequestedUrlString } from './app-access.guard';

describe('appAccessGuard', () => {
  function setup(options: {
    authState?: Partial<AuthSessionState>;
    canAccessNavKey?: boolean;
    canCreateMasterRoutePath?: boolean;
  } = {}) {
    TestBed.resetTestingModule();

    const authSession = {
      ensureInitialized: jasmine.createSpy('ensureInitialized').and.returnValue(of(void 0)),
      state: jasmine.createSpy('state').and.returnValue({
        status: 'authenticated',
        message: null,
        configured: true,
        oidcEnabled: true,
        ...options.authState,
      }),
    };
    const router = {
      createUrlTree: jasmine.createSpy('createUrlTree').and.callFake((commands: unknown[], extras?: unknown) => ({
        commands,
        extras,
      })),
    };
    const access = jasmine.createSpyObj<AppAccessService>('AppAccessService', [
      'canAccessNavKey',
      'canCreateMasterRoutePath',
      'canEditMasterRoutePath',
      'canAccessMasterRoutePath',
    ]);
    access.canAccessNavKey.and.returnValue(options.canAccessNavKey ?? true);
    access.canCreateMasterRoutePath.and.returnValue(options.canCreateMasterRoutePath ?? true);
    access.canEditMasterRoutePath.and.returnValue(true);
    access.canAccessMasterRoutePath.and.returnValue(true);

    TestBed.configureTestingModule({
      providers: [
        { provide: AuthSessionService, useValue: authSession },
        { provide: Router, useValue: router },
        { provide: AppAccessService, useValue: access },
      ],
    });

    return { authSession, router, access };
  }

  it('allows a permitted nav key to match when the session is authenticated', async () => {
    const { access } = setup({ canAccessNavKey: true });

    const guardResult = TestBed.runInInjectionContext(() =>
      appAccessMatchGuard({ data: { accessKey: 'master.operational' } } as never, []),
    );
    const result = isObservable(guardResult) ? await firstValueFrom(guardResult) : guardResult;

    expect(access.canAccessNavKey).toHaveBeenCalledWith('master.operational');
    expect(result).toBeTrue();
  });

  it('redirects unauthenticated protected navigation to the login route with a returnUrl', async () => {
    const { router } = setup({
      authState: {
        status: 'unauthenticated',
        oidcEnabled: true,
      },
    });

    const guardResult = TestBed.runInInjectionContext(() =>
      appAccessGuard({ data: { accessKey: 'replenishment.dashboard' } } as never, { url: '/replenishment/dashboard' } as never),
    );
    const result = isObservable(guardResult) ? await firstValueFrom(guardResult) : guardResult;

    expect(router.createUrlTree).toHaveBeenCalledWith(['/auth/login'], {
      queryParams: {
        reason: 'unauthenticated',
        returnUrl: '/replenishment/dashboard',
      },
    });
    expect(result).toEqual(jasmine.objectContaining({
      commands: ['/auth/login'],
    }));
  });

  it('redirects authenticated but unauthorized navigation to access denied', async () => {
    const { router, access } = setup({ canAccessNavKey: false });

    const guardResult = TestBed.runInInjectionContext(() =>
      appAccessGuard({ data: { accessKey: 'operations.dispatch' } } as never, { url: '/operations/dispatch' } as never),
    );
    const result = isObservable(guardResult) ? await firstValueFrom(guardResult) : guardResult;

    expect(access.canAccessNavKey).toHaveBeenCalledWith('operations.dispatch');
    expect(router.createUrlTree).toHaveBeenCalledWith(['/access-denied'], {
      queryParams: {
        returnUrl: '/operations/dispatch',
      },
    });
    expect(result).toEqual(jasmine.objectContaining({
      commands: ['/access-denied'],
    }));
  });

  it('uses the same shared auth decision model for master-data create routes', async () => {
    const { access, router } = setup({
      authState: {
        status: 'backend_auth_failure',
        oidcEnabled: true,
      },
      canCreateMasterRoutePath: false,
    });

    const guardResult = TestBed.runInInjectionContext(() =>
      appAccessGuard(
        { data: { routePath: 'item-categories', masterAction: 'create' } } as never,
        { url: '/master-data/item-categories/new' } as never,
      ),
    );
    const result = isObservable(guardResult) ? await firstValueFrom(guardResult) : guardResult;

    expect(access.canCreateMasterRoutePath).not.toHaveBeenCalled();
    expect(router.createUrlTree).toHaveBeenCalledWith(['/auth/login'], {
      queryParams: {
        reason: 'backend_auth_failure',
        returnUrl: '/master-data/item-categories/new',
      },
    });
    expect(result).toEqual(jasmine.objectContaining({
      commands: ['/auth/login'],
    }));
  });

  it('keeps access checks working when auth initialization resolves asynchronously', async () => {
    const { access, authSession } = setup({ canAccessNavKey: true });
    authSession.ensureInitialized.and.returnValue(scheduled([void 0], asyncScheduler));

    const guardResult = TestBed.runInInjectionContext(() =>
      appAccessGuard(
        { data: { accessKey: 'operations.relief-requests' } } as never,
        { url: '/operations/relief-requests' } as never,
      ),
    );
    const result = isObservable(guardResult) ? await firstValueFrom(guardResult) : guardResult;

    expect(access.canAccessNavKey).toHaveBeenCalledWith('operations.relief-requests');
    expect(result).toBeTrue();
  });

  it('keeps lazy-route access checks working when auth initialization resolves asynchronously', async () => {
    const { access, authSession } = setup({ canAccessNavKey: true });
    authSession.ensureInitialized.and.returnValue(scheduled([void 0], asyncScheduler));

    const guardResult = TestBed.runInInjectionContext(() =>
      appAccessMatchGuard({ data: { accessKey: 'master.any' }, path: 'master-data' } as never, []),
    );
    const result = isObservable(guardResult) ? await firstValueFrom(guardResult) : guardResult;

    expect(access.canAccessNavKey).toHaveBeenCalledWith('master.any');
    expect(result).toBeTrue();
  });

  it('normalizes safe returnUrls and rejects scheme, credential, and encoded host attacks', () => {
    expect(normalizeRequestedUrlString('/replenishment/dashboard')).toBe('/replenishment/dashboard');
    expect(normalizeRequestedUrlString('/%2F%2Fevil.example')).toBe('/');
    expect(normalizeRequestedUrlString('/https:%2F%2Fevil.example')).toBe('/');
    expect(normalizeRequestedUrlString('/ops@evil.example')).toBe('/');
    expect(normalizeRequestedUrlString('/ops\\dispatch')).toBe('/');
    expect(normalizeRequestedUrlString('/auth/login')).toBe('/');
  });
});
