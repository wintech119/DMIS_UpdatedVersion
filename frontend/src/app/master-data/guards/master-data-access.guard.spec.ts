import { TestBed } from '@angular/core/testing';
import { Router, Route, UrlSegment } from '@angular/router';
import { firstValueFrom, isObservable, of } from 'rxjs';

import { MasterDataAccessService } from '../services/master-data-access.service';
import { masterDataAccessGuard } from './master-data-access.guard';

describe('masterDataAccessGuard', () => {
  function setup(options: {
    canAccess?: boolean;
    canCreate?: boolean;
    canEdit?: boolean;
  } = {}) {
    TestBed.resetTestingModule();

    const access = {
      waitForAuthReady: jasmine.createSpy('waitForAuthReady').and.returnValue(of(void 0)),
      canAccessRoutePath: jasmine.createSpy('canAccessRoutePath').and.returnValue(options.canAccess ?? true),
      canCreateRoutePath: jasmine.createSpy('canCreateRoutePath').and.returnValue(options.canCreate ?? false),
      canEditRoutePath: jasmine.createSpy('canEditRoutePath').and.returnValue(options.canEdit ?? false),
    };
    const router = {
      parseUrl: jasmine.createSpy('parseUrl').and.callFake((url: string) => ({ redirectedTo: url })),
    };

    TestBed.configureTestingModule({
      providers: [
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

  it('allows accessible view routes', async () => {
    const { access } = setup({ canAccess: true });

    const result = await resolveGuard({ path: 'warehouses', data: { routePath: 'warehouses' } });

    expect(access.waitForAuthReady).toHaveBeenCalled();
    expect(access.canAccessRoutePath).toHaveBeenCalledWith('warehouses');
    expect(result).toBeTrue();
  });

  it('redirects inaccessible create routes to /master-data', async () => {
    const { access, router } = setup({ canCreate: false });

    const result = await resolveGuard({
      path: 'items/new',
      data: { routePath: 'items', masterAction: 'create' },
    });

    expect(access.canCreateRoutePath).toHaveBeenCalledWith('items');
    expect(router.parseUrl).toHaveBeenCalledWith('/master-data');
    expect(result).toEqual(jasmine.objectContaining({ redirectedTo: '/master-data' }));
  });

  it('allows edit routes when the shared policy approves them', async () => {
    const { access } = setup({ canEdit: true });

    const result = await resolveGuard({
      path: 'events/:pk/edit',
      data: { routePath: 'events', masterAction: 'edit' },
    });

    expect(access.canEditRoutePath).toHaveBeenCalledWith('events');
    expect(result).toBeTrue();
  });
});
