import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, Router } from '@angular/router';
import { of } from 'rxjs';

import { MasterHomeComponent } from './master-home.component';
import { AuthRbacService } from '../../../replenishment/services/auth-rbac.service';
import { MASTER_DOMAIN_DEFINITIONS } from '../../models/master-domain-map';
import { MasterDataAccessService } from '../../services/master-data-access.service';

describe('MasterHomeComponent', () => {
  function setup(allowedDomains: string[] = ['catalogs', 'operational']) {
    const router = jasmine.createSpyObj<Router>('Router', ['navigate']);
    const authRbac = {
      load: jasmine.createSpy('load'),
      roles: signal<string[]>([]),
      loaded: signal(true),
      tenantContext: signal({
        requested_tenant_id: null,
        active_tenant_id: 12,
        active_tenant_code: 'ODPEM',
        active_tenant_type: 'GOV',
        is_neoc: false,
        can_read_all_tenants: true,
        can_act_cross_tenant: true,
        memberships: [],
      }),
    };
    const masterDataAccess = {
      isSystemAdmin: jasmine.createSpy('isSystemAdmin').and.returnValue(true),
      canAccessDomain: jasmine.createSpy('canAccessDomain').and.callFake((domain: string) => allowedDomains.includes(domain)),
      canAccessRoutePath: jasmine.createSpy('canAccessRoutePath').and.returnValue(true),
      canCreateRoutePath: jasmine.createSpy('canCreateRoutePath').and.returnValue(true),
      canEditRoutePath: jasmine.createSpy('canEditRoutePath').and.returnValue(true),
      getAccessibleDomains: jasmine.createSpy('getAccessibleDomains').and.returnValue(
        allowedDomains.flatMap((domain) => {
          if (domain === 'catalogs') {
            return [{
              id: 'catalogs',
              label: 'Catalogs',
              icon: 'menu_book',
              description: 'Foundational reference data and item catalogs.',
              implementedRoutePaths: ['item-categories', 'ifrc-families', 'ifrc-item-references', 'events'],
              plannedTables: [],
            }];
          }
          if (domain === 'operational') {
            return [{
              id: 'operational',
              label: 'Operational Masters',
              icon: 'domain',
              description: 'Operational entities used by replenishment workflows.',
              implementedRoutePaths: ['warehouses'],
              plannedTables: [],
            }];
          }
          return [];
        }),
      ),
      getDefaultAccessibleDomain: jasmine.createSpy('getDefaultAccessibleDomain').and.returnValue(allowedDomains[0] ?? null),
    };

    TestBed.configureTestingModule({
      imports: [MasterHomeComponent],
      providers: [
        { provide: ActivatedRoute, useValue: { queryParamMap: of(convertToParamMap({ domain: 'catalogs' })) } },
        { provide: Router, useValue: router },
        { provide: AuthRbacService, useValue: authRbac },
        { provide: MasterDataAccessService, useValue: masterDataAccess },
      ],
    });

    const fixture = TestBed.createComponent(MasterHomeComponent);
    fixture.detectChanges();

    return {
      fixture,
      component: fixture.componentInstance,
      router,
      authRbac,
      masterDataAccess,
    };
  }

  it('surfaces Level 1, Level 2, and Level 3 catalog maintenance cards under Catalogs', () => {
    const { component } = setup();

    const routePaths = component.activeCards()
      .map((card) => (card.kind === 'implemented' ? card.routePath : null))
      .filter((routePath): routePath is string => routePath != null);

    expect(routePaths).toContain('item-categories');
    expect(routePaths).toContain('ifrc-families');
    expect(routePaths).toContain('ifrc-item-references');
  });

  it('routes governed catalog create actions through page-mode /new flows', () => {
    const { component, router } = setup();

    component.create('item-categories');
    expect(router.navigate).toHaveBeenCalledWith(['/master-data', 'item-categories', 'new']);

    component.create('ifrc-families');
    expect(router.navigate).toHaveBeenCalledWith(['/master-data', 'ifrc-families', 'new']);

    component.create('ifrc-item-references');
    expect(router.navigate).toHaveBeenCalledWith(['/master-data', 'ifrc-item-references', 'new']);
  });

  it('keeps dialog-mode create actions on the list screen for simple masters', () => {
    const { component, router } = setup();

    component.create('uom');

    expect(router.navigate).toHaveBeenCalledWith(['/master-data', 'uom'], {
      queryParams: { open: 'new' },
    });
  });

  it('only renders master data domains allowed by the shared access policy', () => {
    const { component } = setup(['operational']);

    expect(component.domains().map((domain) => domain.id)).toEqual(['operational']);
    expect(component.activeCards().some((card) => card.kind === 'implemented' && card.routePath === 'warehouses')).toBeTrue();
    expect(component.activeCards().some((card) => card.kind === 'implemented' && card.routePath === 'custodians')).toBeFalse();
  });

  it('does not surface custodians as a normal operational master card', () => {
    const { component } = setup(['operational']);
    const operationalDomain = MASTER_DOMAIN_DEFINITIONS.find((domain) => domain.id === 'operational');

    expect(operationalDomain?.implementedRoutePaths).not.toContain('custodians');
    expect(component.activeCards().some((card) => card.kind === 'implemented' && card.routePath === 'custodians')).toBeFalse();
  });
});
