import { firstValueFrom, of } from 'rxjs';
import { TestBed } from '@angular/core/testing';

import { AppAccessService } from '../../core/app-access.service';
import { AuthRbacService } from '../../replenishment/services/auth-rbac.service';
import { MasterDataAccessService } from './master-data-access.service';

describe('MasterDataAccessService', () => {
  function setup() {
    TestBed.resetTestingModule();

    const auth = {
      load: jasmine.createSpy('load'),
      ensureLoaded: jasmine.createSpy('ensureLoaded').and.returnValue(of(void 0)),
    };
    const access = {
      isSystemAdministrator: jasmine.createSpy('isSystemAdministrator').and.returnValue(false),
      canAccessMasterDomain: jasmine.createSpy('canAccessMasterDomain').and.callFake((domain: string) => domain === 'operational'),
      canAccessMasterRoutePath: jasmine.createSpy('canAccessMasterRoutePath').and.returnValue(true),
      canCreateMasterRoutePath: jasmine.createSpy('canCreateMasterRoutePath').and.returnValue(false),
      canEditMasterRoutePath: jasmine.createSpy('canEditMasterRoutePath').and.returnValue(false),
      canToggleMasterStatus: jasmine.createSpy('canToggleMasterStatus').and.returnValue(false),
      isLegacyMasterRoutePath: jasmine.createSpy('isLegacyMasterRoutePath').and.callFake((routePath: string) => routePath === 'custodians'),
    };

    TestBed.configureTestingModule({
      providers: [
        MasterDataAccessService,
        { provide: AuthRbacService, useValue: auth },
        { provide: AppAccessService, useValue: access },
      ],
    });

    return {
      service: TestBed.inject(MasterDataAccessService),
      auth,
      access,
    };
  }

  it('waits on shared auth readiness before route guards evaluate', async () => {
    const { service, auth } = setup();

    await firstValueFrom(service.waitForAuthReady());

    expect(auth.ensureLoaded).toHaveBeenCalled();
    expect(auth.load).toHaveBeenCalled();
  });

  it('delegates domain and route checks to the shared access policy', () => {
    const { service, access } = setup();

    expect(service.canAccessDomain('operational')).toBeTrue();
    expect(service.canAccessRoutePath('warehouses/details')).toBeTrue();
    expect(service.canCreateRoutePath('warehouses', true)).toBeFalse();
    expect(service.canEditRoutePath('warehouses')).toBeFalse();
    expect(service.canToggleStatusRoutePath('warehouses', true)).toBeFalse();
    expect(service.isLegacyRoutePath('custodians')).toBeTrue();

    expect(access.canAccessMasterDomain).toHaveBeenCalledWith('operational');
    expect(access.canAccessMasterRoutePath).toHaveBeenCalledWith('warehouses');
    expect(access.canCreateMasterRoutePath).toHaveBeenCalledWith('warehouses', true);
    expect(access.canEditMasterRoutePath).toHaveBeenCalledWith('warehouses', false);
    expect(access.canToggleMasterStatus).toHaveBeenCalledWith('warehouses', true, false);
    expect(access.isLegacyMasterRoutePath).toHaveBeenCalledWith('custodians');
  });

  it('returns only the domains allowed by the shared policy', () => {
    const { service } = setup();

    expect(service.getAccessibleDomains().map((domain) => domain.id)).toEqual(['operational']);
    expect(service.getDefaultAccessibleDomain()).toBe('operational');
  });
});
