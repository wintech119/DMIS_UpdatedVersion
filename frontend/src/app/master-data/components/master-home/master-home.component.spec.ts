import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, Router } from '@angular/router';
import { of } from 'rxjs';

import { MasterHomeComponent } from './master-home.component';
import { AuthRbacService } from '../../../replenishment/services/auth-rbac.service';

describe('MasterHomeComponent', () => {
  function setup() {
    const router = jasmine.createSpyObj<Router>('Router', ['navigate']);
    const authRbac = {
      load: jasmine.createSpy('load'),
      roles: signal<string[]>([]),
      loaded: signal(true),
    };

    TestBed.configureTestingModule({
      imports: [MasterHomeComponent],
      providers: [
        { provide: ActivatedRoute, useValue: { queryParamMap: of(convertToParamMap({ domain: 'catalogs' })) } },
        { provide: Router, useValue: router },
        { provide: AuthRbacService, useValue: authRbac },
      ],
    });

    const fixture = TestBed.createComponent(MasterHomeComponent);
    fixture.detectChanges();

    return {
      fixture,
      component: fixture.componentInstance,
      router,
      authRbac,
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

  it('routes IFRC family and item-reference create actions through page-mode /new flows', () => {
    const { component, router } = setup();

    component.create('ifrc-families');
    expect(router.navigate).toHaveBeenCalledWith(['/master-data', 'ifrc-families', 'new']);

    component.create('ifrc-item-references');
    expect(router.navigate).toHaveBeenCalledWith(['/master-data', 'ifrc-item-references', 'new']);
  });

  it('keeps dialog-mode create actions on the list screen for simple masters', () => {
    const { component, router } = setup();

    component.create('item-categories');

    expect(router.navigate).toHaveBeenCalledWith(['/master-data', 'item-categories'], {
      queryParams: { open: 'new' },
    });
  });
});
