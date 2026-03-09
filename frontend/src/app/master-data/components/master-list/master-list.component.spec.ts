import { fakeAsync, TestBed, tick } from '@angular/core/testing';
import { of } from 'rxjs';
import { ActivatedRoute, Router } from '@angular/router';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { MatDialog } from '@angular/material/dialog';
import { BreakpointObserver } from '@angular/cdk/layout';

import { MasterListComponent } from './master-list.component';
import { MasterDataService } from '../../services/master-data.service';
import { DmisNotificationService } from '../../../replenishment/services/notification.service';

describe('MasterListComponent', () => {
  function setup() {
    const masterDataService = jasmine.createSpyObj<MasterDataService>('MasterDataService', [
      'list',
      'lookupItemCategories',
      'lookupIfrcFamilies',
      'lookupIfrcReferences',
      'inactivate',
      'activate',
      'clearLookupCache',
    ]);
    const router = jasmine.createSpyObj<Router>('Router', ['navigate']);
    const dialog = jasmine.createSpyObj<MatDialog>('MatDialog', ['open']);
    const notificationService = jasmine.createSpyObj<DmisNotificationService>('DmisNotificationService', [
      'showSuccess',
      'showError',
      'showWarning',
    ]);
    const breakpointObserver = jasmine.createSpyObj<BreakpointObserver>('BreakpointObserver', ['observe']);

    masterDataService.list.and.returnValue(of({
      results: [],
      count: 0,
      limit: 25,
      offset: 0,
      warnings: [],
    }));
    masterDataService.lookupItemCategories.and.returnValue(of([
      { value: 102, label: 'WASH', category_code: 'WASH' },
    ]));
    masterDataService.lookupIfrcFamilies.and.returnValue(of([
      { value: 301, label: 'Water Treatment', family_code: 'WTR', group_code: 'W', category_id: 102 },
    ]));
    masterDataService.lookupIfrcReferences.and.returnValue(of([
      { value: 401, label: 'Water purification tablet', ifrc_code: 'WWTRTABL01', ifrc_family_id: 301 },
    ]));
    breakpointObserver.observe.and.returnValue(of({
      matches: false,
      breakpoints: {},
    }));

    TestBed.configureTestingModule({
      imports: [MasterListComponent, NoopAnimationsModule],
      providers: [
        { provide: ActivatedRoute, useValue: { data: of({ routePath: 'items' }) } },
        { provide: Router, useValue: router },
        { provide: MatDialog, useValue: dialog },
        { provide: BreakpointObserver, useValue: breakpointObserver },
        { provide: MasterDataService, useValue: masterDataService },
        { provide: DmisNotificationService, useValue: notificationService },
      ],
    });

    const fixture = TestBed.createComponent(MasterListComponent);
    fixture.detectChanges();

    return {
      fixture,
      component: fixture.componentInstance,
      masterDataService,
    };
  }

  it('sends category, family, and reference filters through item list requests', () => {
    const { component, masterDataService } = setup();

    component.onItemCategoryFilterChange({ target: { value: '102' } } as unknown as Event);
    expect(masterDataService.list.calls.mostRecent().args[1]).toEqual(jasmine.objectContaining({
      categoryId: '102',
      ifrcFamilyId: undefined,
      ifrcItemRefId: undefined,
    }));

    component.onItemIfrcFamilyFilterChange({ target: { value: '301' } } as unknown as Event);
    expect(masterDataService.list.calls.mostRecent().args[1]).toEqual(jasmine.objectContaining({
      categoryId: '102',
      ifrcFamilyId: '301',
      ifrcItemRefId: undefined,
    }));

    component.onItemIfrcReferenceFilterChange({ target: { value: '401' } } as unknown as Event);
    expect(masterDataService.list.calls.mostRecent().args[1]).toEqual(jasmine.objectContaining({
      categoryId: '102',
      ifrcFamilyId: '301',
      ifrcItemRefId: '401',
    }));
  });

  it('keeps search wired to the item list backend search contract', fakeAsync(() => {
    const { component, masterDataService } = setup();

    component.onSearchInput({ target: { value: 'water tabs' } } as unknown as Event);
    tick(300);

    expect(masterDataService.list.calls.mostRecent().args[1]).toEqual(jasmine.objectContaining({
      search: 'water tabs',
    }));
  }));
});
