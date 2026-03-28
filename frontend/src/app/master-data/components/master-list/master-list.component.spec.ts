import { fakeAsync, TestBed, tick } from '@angular/core/testing';
import { of, Subject } from 'rxjs';
import { ActivatedRoute, Router, convertToParamMap } from '@angular/router';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { MatDialog } from '@angular/material/dialog';
import { BreakpointObserver } from '@angular/cdk/layout';

import { MasterListComponent } from './master-list.component';
import { MasterDataAccessService } from '../../services/master-data-access.service';
import { MasterDataService } from '../../services/master-data.service';
import { DmisNotificationService } from '../../../replenishment/services/notification.service';

describe('MasterListComponent', () => {
  function setup(
    routePath = 'items',
    queryParams: Record<string, string> = {},
    accessOverrides: {
      canCreate?: boolean;
      canEdit?: boolean;
      canToggleStatus?: boolean;
    } = {},
  ) {
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
    const access = jasmine.createSpyObj<MasterDataAccessService>('MasterDataAccessService', [
      'canCreateRoutePath',
      'canEditRoutePath',
      'canToggleStatusRoutePath',
    ]);
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
      { value: 401, label: 'Water purification tablet', ifrc_code: 'WWTRTABLTB01', ifrc_family_id: 301 },
    ]));
    breakpointObserver.observe.and.returnValue(of({
      matches: false,
      breakpoints: {},
    }));
    dialog.open.and.returnValue({ afterClosed: () => of(false) } as never);
    access.canCreateRoutePath.and.returnValue(accessOverrides.canCreate ?? true);
    access.canEditRoutePath.and.returnValue(accessOverrides.canEdit ?? true);
    access.canToggleStatusRoutePath.and.returnValue(accessOverrides.canToggleStatus ?? true);

    TestBed.configureTestingModule({
      imports: [MasterListComponent, NoopAnimationsModule],
      providers: [
        {
          provide: ActivatedRoute,
          useValue: {
            data: of({ routePath }),
            queryParamMap: of(convertToParamMap(queryParams)),
          },
        },
        { provide: Router, useValue: router },
        { provide: MatDialog, useValue: dialog },
        { provide: BreakpointObserver, useValue: breakpointObserver },
        { provide: MasterDataAccessService, useValue: access },
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
      dialog,
      router,
      access,
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

  it('routes page-mode catalog create actions to /new routes', () => {
    const { component, router, access } = setup('item-categories');

    component.onAdd();

    expect(component.config()).toEqual(jasmine.objectContaining({
      routePath: 'item-categories',
      tableKey: 'item_categories',
      formMode: 'page',
    }));
    expect(access.canCreateRoutePath).toHaveBeenCalledWith('item-categories', false);
    expect(router.navigate).toHaveBeenCalledWith(['/master-data', 'item-categories', 'new']);
  });

  it('still opens the create dialog when a dialog-mode catalog list handles a pending create request', () => {
    const { component, access, router } = setup('uom');
    const listHarness = component as never as {
      pendingDialogQueryAction: 'new' | null;
      handleDialogQueryAction: () => void;
      openFormDialog: (pk: string | number | null) => void;
    };
    const openFormDialogSpy = spyOn(listHarness, 'openFormDialog');

    expect(component.config()).toEqual(jasmine.objectContaining({
      routePath: 'uom',
      tableKey: 'uom',
      formMode: 'dialog',
    }));

    listHarness.pendingDialogQueryAction = 'new';
    listHarness.handleDialogQueryAction();

    expect(access.canCreateRoutePath).toHaveBeenCalledWith('uom', false);
    expect(openFormDialogSpy).toHaveBeenCalledWith(null);
    expect(router.navigate).toHaveBeenCalledWith([], {
      relativeTo: jasmine.anything(),
      queryParams: { open: null },
      queryParamsHandling: 'merge',
      replaceUrl: true,
    });
  });

  it('drops pending dialog-mode create requests when create access is denied', () => {
    const { component, access, dialog, router } = setup('uom', {}, { canCreate: false });
    const listHarness = component as never as {
      pendingDialogQueryAction: 'new' | null;
      handleDialogQueryAction: () => void;
    };
    listHarness.pendingDialogQueryAction = 'new';
    listHarness.handleDialogQueryAction();

    expect(access.canCreateRoutePath).toHaveBeenCalledWith('uom', false);
    expect(dialog.open).not.toHaveBeenCalled();
    expect(router.navigate).toHaveBeenCalledWith([], {
      relativeTo: jasmine.anything(),
      queryParams: { open: null },
      queryParamsHandling: 'merge',
      replaceUrl: true,
    });
  });

  it('ignores stale IFRC family lookup responses', () => {
    const { component, masterDataService } = setup();
    const staleResponse = new Subject<{
      value: number;
      label: string;
      family_code: string;
      group_code: string;
      category_id: number;
    }[]>();
    const latestItems = [
      { value: 302, label: 'Shelter Kit', family_code: 'SHELTER', group_code: 'S', category_id: 103 },
    ];

    masterDataService.lookupIfrcFamilies.and.returnValues(
      staleResponse.asObservable(),
      of(latestItems),
    );

    component.onItemCategoryFilterChange({ target: { value: '102' } } as unknown as Event);
    component.onItemCategoryFilterChange({ target: { value: '103' } } as unknown as Event);

    expect(component.itemIfrcFamilyOptions()).toEqual(latestItems);
    expect(component.itemLookupLoading().families).toBeFalse();

    staleResponse.next([
      { value: 301, label: 'Water Treatment', family_code: 'WTR', group_code: 'W', category_id: 102 },
    ]);
    staleResponse.complete();

    expect(component.itemIfrcFamilyOptions()).toEqual(latestItems);
    expect(component.itemLookupLoading().families).toBeFalse();
  });

  it('ignores stale IFRC reference lookup failures after a newer response succeeds', () => {
    const { component, masterDataService } = setup();
    const staleResponse = new Subject<{
      value: number;
      label: string;
      ifrc_code: string;
      ifrc_family_id: number;
    }[]>();
    const latestItems = [
      { value: 402, label: 'Emergency shelter kit', ifrc_code: 'SSHLTKIT01', ifrc_family_id: 302 },
    ];

    masterDataService.lookupIfrcReferences.and.returnValues(
      staleResponse.asObservable(),
      of(latestItems),
    );

    component.onItemIfrcFamilyFilterChange({ target: { value: '301' } } as unknown as Event);
    component.onItemIfrcFamilyFilterChange({ target: { value: '302' } } as unknown as Event);

    expect(component.itemIfrcReferenceOptions()).toEqual(latestItems);
    expect(component.itemLookupLoading().references).toBeFalse();

    staleResponse.error(new Error('stale failure'));

    expect(component.itemIfrcReferenceOptions()).toEqual(latestItems);
    expect(component.itemLookupLoading().references).toBeFalse();
  });
});
