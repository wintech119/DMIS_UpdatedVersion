import { TestBed } from '@angular/core/testing';
import { Route, Router, UrlSegment } from '@angular/router';
import { firstValueFrom, isObservable, of } from 'rxjs';

import { AuthSessionService, AuthSessionState } from '../../core/auth-session.service';
import { MasterDataAccessService } from '../services/master-data-access.service';
import { masterDataAccessGuard } from './master-data-access.guard';

describe('masterDataAccessGuard', () => {
  function setup(options: {
    authState?: Partial<AuthSessionState>;
    canAccess?: boolean;
    canCreate?: boolean;
    canEdit?: boolean;
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
    const access = {
      canAccessRoutePath: jasmine.createSpy('canAccessRoutePath').and.returnValue(options.canAccess ?? true),
      canCreateRoutePath: jasmine.createSpy('canCreateRoutePath').and.returnValue(options.canCreate ?? false),
      canEditRoutePath: jasmine.createSpy('canEditRoutePath').and.returnValue(options.canEdit ?? false),
    };
    const router = {
      createUrlTree: jasmine.createSpy('createUrlTree').and.callFake((commands: unknown[], extras?: unknown) => ({
        commands,
        extras,
      })),
    };

    TestBed.configureTestingModule({
      providers: [
        { provide: AuthSessionService, useValue: authSession },
        { provide: MasterDataAccessService, useValue: access },
        { provide: Router, useValue: router },
      ],
    });

    return { access, router };
  }

  async function resolveGuard(route: Route) {
    const guardResult = TestBed.runInInjectionContext(() =>
      masterDataAccessGuard(route, [new UrlSegment(route.path ?? '', {})]),
    );
    return isObservable(guardResult) ? firstValueFrom(guardResult) : guardResult;
  }

  it('allows authenticated users to open accessible master-data routes', async () => {
    const { access } = setup({ canAccess: true });

    const result = await resolveGuard({ path: 'warehouses', data: { routePath: 'warehouses' } });

    expect(access.canAccessRoutePath).toHaveBeenCalledWith('warehouses');
    expect(result).toBeTrue();
  });

  it('redirects unauthenticated users to the login route before evaluating access using the normalized route path', async () => {
    const { access, router } = setup({
      authState: {
        status: 'unauthenticated',
      },
    });

    const result = await resolveGuard({
      path: 'items/new',
      data: { routePath: 'items', masterAction: 'create' },
    });

    expect(access.canCreateRoutePath).not.toHaveBeenCalled();
    expect(router.createUrlTree).toHaveBeenCalledWith(['/auth/login'], {
      queryParams: {
        reason: 'unauthenticated',
        returnUrl: '/items',
      },
    });
    expect(result).toEqual(jasmine.objectContaining({
      commands: ['/auth/login'],
    }));
  });

  it('redirects authenticated but unauthorized routes to access denied using the normalized route path', async () => {
    const { access, router } = setup({ canEdit: false });

    const result = await resolveGuard({
      path: 'events/:pk/edit',
      data: { routePath: 'events', masterAction: 'edit' },
    });

    expect(access.canEditRoutePath).toHaveBeenCalledWith('events');
    expect(router.createUrlTree).toHaveBeenCalledWith(['/access-denied'], {
      queryParams: {
        returnUrl: '/events',
      },
    });
    expect(result).toEqual(jasmine.objectContaining({
      commands: ['/access-denied'],
    }));
  });
});
