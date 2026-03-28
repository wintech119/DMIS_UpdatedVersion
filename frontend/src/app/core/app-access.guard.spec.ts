import { TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { of, firstValueFrom, isObservable } from 'rxjs';

import { AppAccessService } from './app-access.service';
import { AuthRbacService } from '../replenishment/services/auth-rbac.service';
import { appAccessGuard, appAccessMatchGuard } from './app-access.guard';

describe('appAccessGuard', () => {
  function setup(accessOverrides: Partial<AppAccessService> = {}) {
    TestBed.resetTestingModule();

    const auth = {
      ensureLoaded: jasmine.createSpy('ensureLoaded').and.returnValue(of(void 0)),
    };
    const router = {
      parseUrl: jasmine.createSpy('parseUrl').and.callFake((url: string) => ({ redirectedTo: url })),
    };
    const access = jasmine.createSpyObj<AppAccessService>('AppAccessService', [
      'canAccessNavKey',
      'canCreateMasterRoutePath',
      'canEditMasterRoutePath',
      'canAccessMasterRoutePath',
    ]);
    if (accessOverrides.canAccessNavKey) {
      access.canAccessNavKey.and.callFake(accessOverrides.canAccessNavKey.bind(access));
    }
    if (accessOverrides.canCreateMasterRoutePath) {
      access.canCreateMasterRoutePath.and.callFake(accessOverrides.canCreateMasterRoutePath.bind(access));
    }
    if (accessOverrides.canEditMasterRoutePath) {
      access.canEditMasterRoutePath.and.callFake(accessOverrides.canEditMasterRoutePath.bind(access));
    }
    if (accessOverrides.canAccessMasterRoutePath) {
      access.canAccessMasterRoutePath.and.callFake(accessOverrides.canAccessMasterRoutePath.bind(access));
    }

    TestBed.configureTestingModule({
      providers: [
        { provide: AuthRbacService, useValue: auth },
        { provide: Router, useValue: router },
        { provide: AppAccessService, useValue: access },
      ],
    });

    return { auth, router, access };
  }

  it('allows a permitted nav key to match', async () => {
    const { access } = setup({ canAccessNavKey: () => true });

    const guardResult = TestBed.runInInjectionContext(() =>
      appAccessMatchGuard({ data: { accessKey: 'master.operational' } } as never, []),
    );
    const result = isObservable(guardResult) ? await firstValueFrom(guardResult) : guardResult;

    expect(access.canAccessNavKey).toHaveBeenCalledWith('master.operational');
    expect(result).toBeTrue();
  });

  it('redirects denied master create routes to the dashboard', async () => {
    const { router, access } = setup({ canCreateMasterRoutePath: () => false });

    const guardResult = TestBed.runInInjectionContext(() =>
      appAccessGuard({ data: { routePath: 'item-categories', masterAction: 'create' } } as never, {} as never),
    );
    const result = isObservable(guardResult) ? await firstValueFrom(guardResult) : guardResult;

    expect(access.canCreateMasterRoutePath).toHaveBeenCalledWith('item-categories');
    expect(router.parseUrl).toHaveBeenCalledWith('/replenishment/dashboard');
    expect(result).toEqual(jasmine.objectContaining({ redirectedTo: '/replenishment/dashboard' }));
  });
});
