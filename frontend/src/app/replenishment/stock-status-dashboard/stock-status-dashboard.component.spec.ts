import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of, Subject, throwError } from 'rxjs';
import { MatDialog } from '@angular/material/dialog';
import { ActivatedRoute, Router, convertToParamMap } from '@angular/router';
import { HttpClient } from '@angular/common/http';

import { StockStatusDashboardComponent } from './stock-status-dashboard.component';
import { DashboardData, DashboardDataService } from '../services/dashboard-data.service';
import { DataFreshnessService } from '../services/data-freshness.service';
import { DmisNotificationService } from '../services/notification.service';
import { ActiveEvent, ReplenishmentService, Warehouse } from '../services/replenishment.service';
import { WarehouseStockGroup } from '../models/stock-status.model';
import { NeedsListResponse } from '../models/needs-list.model';

describe('StockStatusDashboardComponent', () => {
  let fixture: ComponentFixture<StockStatusDashboardComponent>;
  let component: StockStatusDashboardComponent;

  let dashboardDataService: jasmine.SpyObj<DashboardDataService>;
  let dataFreshnessService: jasmine.SpyObj<DataFreshnessService>;
  let notificationService: jasmine.SpyObj<DmisNotificationService>;
  let httpClient: jasmine.SpyObj<HttpClient>;
  let replenishmentService: jasmine.SpyObj<ReplenishmentService>;
  let router: jasmine.SpyObj<Router>;

  const refreshRequested$ = new Subject<void>();
  const event: ActiveEvent = {
    event_id: 99,
    event_name: 'Storm',
    status: 'ACTIVE',
    phase: 'SURGE',
    declaration_date: '2026-02-10T00:00:00Z'
  };
  const warehouses: Warehouse[] = [
    { warehouse_id: 1, warehouse_name: 'North Depot' },
    { warehouse_id: 2, warehouse_name: 'South Depot' }
  ];

  function createGroup(warehouseId: number, warehouseName: string): WarehouseStockGroup {
    return {
      warehouse_id: warehouseId,
      warehouse_name: warehouseName,
      items: [],
      critical_count: 0,
      warning_count: 0,
      watch_count: 0,
      ok_count: 0
    };
  }

  function createDashboardData(groups: WarehouseStockGroup[]): DashboardData {
    return {
      groups,
      as_of_datetime: '2026-02-11T00:00:00Z',
      warnings: [],
      totals: {
        items: 0,
        critical: 0,
        warning: 0,
        watch: 0,
        ok: 0
      },
      availableCategories: []
    };
  }

  beforeEach(async () => {
    localStorage.clear();

    dashboardDataService = jasmine.createSpyObj<DashboardDataService>(
      'DashboardDataService',
      ['getDashboardData', 'invalidateCache']
    );
    dataFreshnessService = jasmine.createSpyObj<DataFreshnessService>(
      'DataFreshnessService',
      ['onRefreshRequested$', 'updateFromWarehouseGroups', 'refreshComplete', 'clear']
    );
    notificationService = jasmine.createSpyObj<DmisNotificationService>(
      'DmisNotificationService',
      ['showNetworkError', 'showWarning', 'showSuccess']
    );

    replenishmentService = jasmine.createSpyObj<ReplenishmentService>(
      'ReplenishmentService',
      ['getActiveEvent', 'getAllWarehouses', 'listNeedsLists']
    );
    replenishmentService.getActiveEvent.and.returnValue(of(event));
    replenishmentService.getAllWarehouses.and.returnValue(of(warehouses));
    replenishmentService.listNeedsLists.and.returnValue(of({ needs_lists: [], count: 0 }));

    router = jasmine.createSpyObj<Router>('Router', ['navigate']);
    const dialog = jasmine.createSpyObj<MatDialog>('MatDialog', ['open']);
    httpClient = jasmine.createSpyObj<HttpClient>('HttpClient', ['get']);
    httpClient.get.and.returnValue(of({ roles: [], permissions: [] }));
    dataFreshnessService.onRefreshRequested$.and.returnValue(refreshRequested$.asObservable());

    await TestBed.configureTestingModule({
      imports: [StockStatusDashboardComponent],
      providers: [
        { provide: ReplenishmentService, useValue: replenishmentService },
        { provide: DashboardDataService, useValue: dashboardDataService },
        { provide: DataFreshnessService, useValue: dataFreshnessService },
        { provide: DmisNotificationService, useValue: notificationService },
        { provide: Router, useValue: router },
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: {
              queryParamMap: convertToParamMap({})
            }
          }
        },
        { provide: MatDialog, useValue: dialog },
        { provide: HttpClient, useValue: httpClient }
      ]
    }).overrideComponent(StockStatusDashboardComponent, {
      set: { template: '' }
    }).compileComponents();

    fixture = TestBed.createComponent(StockStatusDashboardComponent);
    component = fixture.componentInstance;
    component.activeEvent = event;
    component.allWarehouses = warehouses;
  });

  it('ignores stale single-view responses after returning to multi view', () => {
    const singleResponse$ = new Subject<DashboardData>();
    const multiData = createDashboardData([
      createGroup(1, 'North Depot'),
      createGroup(2, 'South Depot')
    ]);

    dashboardDataService.getDashboardData.and.returnValues(
      singleResponse$.asObservable(),
      of(multiData)
    );

    component.drillDownToWarehouse(1);
    component.returnToMultiView();

    expect(component.viewMode).toBe('multi');
    expect(component.warehouseGroups.map(g => g.warehouse_id)).toEqual([1, 2]);

    singleResponse$.next(createDashboardData([createGroup(1, 'North Depot')]));
    singleResponse$.complete();

    expect(component.viewMode).toBe('multi');
    expect(component.warehouseGroups.map(g => g.warehouse_id)).toEqual([1, 2]);
  });

  it('handles single-view fetch errors and surfaces retry callback', () => {
    dashboardDataService.getDashboardData.and.returnValue(
      throwError(() => new Error('single fetch failed'))
    );

    const retrySpy = spyOn(component, 'retryCurrentView').and.callThrough();
    component.drillDownToWarehouse(1);

    const firstCallArgs = dashboardDataService.getDashboardData.calls.argsFor(0);
    expect(firstCallArgs[1]).toEqual([1]);

    expect(component.dataLoadedSuccessfully).toBeFalse();
    expect(component.errors).toEqual(['single fetch failed']);
    expect(component.loading).toBeFalse();
    expect(component.refreshing).toBeFalse();
    expect(notificationService.showNetworkError).toHaveBeenCalled();
    expect(dataFreshnessService.refreshComplete).toHaveBeenCalled();

    const retryCallback = notificationService.showNetworkError.calls.mostRecent()
      .args[1] as () => void;
    retryCallback();

    expect(retrySpy).toHaveBeenCalled();
  });

  it('applies only the latest single-warehouse response when switching warehouses quickly', () => {
    const firstRequest$ = new Subject<DashboardData>();
    const secondRequest$ = new Subject<DashboardData>();
    const bothGroupsData = createDashboardData([
      createGroup(1, 'North Depot'),
      createGroup(2, 'South Depot')
    ]);

    dashboardDataService.getDashboardData.and.returnValues(
      firstRequest$.asObservable(),
      secondRequest$.asObservable()
    );

    component.drillDownToWarehouse(1);
    component.drillDownToWarehouse(2);

    secondRequest$.next(bothGroupsData);
    secondRequest$.complete();

    expect(component.selectedWarehouseId).toBe(2);
    expect(component.warehouseGroups.map(g => g.warehouse_id)).toEqual([2]);

    firstRequest$.next(bothGroupsData);
    firstRequest$.complete();

    expect(component.selectedWarehouseId).toBe(2);
    expect(component.warehouseGroups.map(g => g.warehouse_id)).toEqual([2]);
  });

  it('applies only the latest multi-warehouse response when filters change quickly', () => {
    const firstRequest$ = new Subject<DashboardData>();
    const secondRequest$ = new Subject<DashboardData>();
    const northData = createDashboardData([createGroup(1, 'North Depot')]);
    const southData = createDashboardData([createGroup(2, 'South Depot')]);

    dashboardDataService.getDashboardData.and.returnValues(
      firstRequest$.asObservable(),
      secondRequest$.asObservable()
    );

    component.loadMultiWarehouseStatus();
    component.changeSortBy('severity');

    secondRequest$.next(southData);
    secondRequest$.complete();

    expect(component.sortBy).toBe('severity');
    expect(component.warehouseGroups.map(g => g.warehouse_id)).toEqual([2]);

    firstRequest$.next(northData);
    firstRequest$.complete();

    expect(component.sortBy).toBe('severity');
    expect(component.warehouseGroups.map(g => g.warehouse_id)).toEqual([2]);
  });

  it('does not allow review queue with action permission but no preview permission', () => {
    httpClient.get.and.returnValue(of({
      roles: [],
      permissions: ['replenishment.needs_list.approve']
    }));

    component['loadReviewQueueAccess']();

    expect(component.canAccessReviewQueue).toBeFalse();
  });

  it('allows review queue when preview and review permissions are present', () => {
    httpClient.get.and.returnValue(of({
      roles: [],
      permissions: [
        'replenishment.needs_list.preview',
        'replenishment.needs_list.approve'
      ]
    }));

    component['loadReviewQueueAccess']();

    expect(component.canAccessReviewQueue).toBeTrue();
  });

  it('prefers user_id when matching submitter updates', () => {
    httpClient.get.and.returnValue(of({
      user_id: 'EMP-123',
      username: 'alice',
      roles: [],
      permissions: [
        'replenishment.needs_list.preview',
        'replenishment.needs_list.approve'
      ]
    }));
    replenishmentService.listNeedsLists.and.returnValue(of({
      needs_lists: [
        {
          needs_list_id: 'NL-1',
          event_id: 99,
          phase: 'SURGE',
          items: [],
          as_of_datetime: '2026-02-16T12:00:00Z',
          submitted_by: 'EMP-123',
          status: 'APPROVED',
          updated_at: '2026-02-16T12:00:00Z'
        },
        {
          needs_list_id: 'NL-2',
          event_id: 99,
          phase: 'SURGE',
          items: [],
          as_of_datetime: '2026-02-16T12:00:00Z',
          submitted_by: 'alice',
          status: 'APPROVED',
          updated_at: '2026-02-16T12:00:00Z'
        }
      ],
      count: 2
    }));

    component['loadReviewQueueAccess']();

    expect(component['currentUserRef']).toBe('EMP-123');
    expect(component.mySubmissionUpdates.map((row) => row.needs_list_id)).toEqual(['NL-1']);
  });

  it('loads my drafts and submissions with mine filter enabled', () => {
    httpClient.get.and.returnValue(of({
      user_id: 'EMP-123',
      username: 'alice',
      roles: [],
      permissions: ['replenishment.needs_list.preview']
    }));
    replenishmentService.listNeedsLists.and.returnValue(of({
      needs_lists: [
        {
          needs_list_id: 'NL-2',
          event_id: 99,
          phase: 'SURGE',
          items: [],
          as_of_datetime: '2026-02-16T12:00:00Z',
          created_by: 'EMP-123',
          status: 'SUBMITTED',
          updated_at: '2026-02-16T13:00:00Z'
        },
        {
          needs_list_id: 'NL-1',
          event_id: 99,
          phase: 'SURGE',
          items: [],
          as_of_datetime: '2026-02-16T12:00:00Z',
          created_by: 'EMP-123',
          status: 'DRAFT',
          updated_at: '2026-02-16T14:00:00Z'
        }
      ],
      count: 2
    }));

    component['loadReviewQueueAccess']();

    const mineCall = replenishmentService.listNeedsLists.calls.allArgs().find((args) =>
      args[1]?.mine === true && args[1]?.includeClosed === true
    );
    expect(mineCall).toBeDefined();
    expect(component.myNeedsLists.map((row) => row.needs_list_id)).toEqual(['NL-1', 'NL-2']);
  });

  it('opens revision in wizard with existing needs_list_id context', () => {
    component.reviseMyNeedsList({
      needs_list_id: 'NL-55',
      event_id: 99,
      phase: 'SURGE',
      warehouse_id: 2,
      items: [],
      as_of_datetime: '2026-02-16T12:00:00Z'
    });

    expect(router.navigate).toHaveBeenCalledWith(
      ['/replenishment/needs-list-wizard'],
      {
        queryParams: jasmine.objectContaining({
          needs_list_id: 'NL-55',
          event_id: 99,
          warehouse_id: 2,
          phase: 'SURGE'
        })
      }
    );
  });

  it('computes remaining and fulfilled item groups for my needs lists', () => {
    const row: NeedsListResponse = {
      needs_list_id: 'NL-70',
      event_id: 99,
      phase: 'SURGE',
      status: 'IN_PROGRESS',
      as_of_datetime: '2026-02-16T12:00:00Z',
      items: [
        { item_id: 1, item_name: 'Water', gap_qty: 100, fulfilled_qty: 25, fulfillment_status: 'PENDING', available_qty: 0, inbound_strict_qty: 0, burn_rate_per_hour: 0 },
        { item_id: 2, item_name: 'Rice', gap_qty: 40, fulfilled_qty: 40, fulfillment_status: 'FULFILLED', available_qty: 0, inbound_strict_qty: 0, burn_rate_per_hour: 0 }
      ]
    };

    expect(component.remainingNeedsListItems(row).map((item) => item.item_id)).toEqual([1]);
    expect(component.fulfilledNeedsListItems(row).map((item) => item.item_id)).toEqual([2]);
  });

  it('keeps fetched event context when requested event id does not match', () => {
    component['requestedEventId'] = 777;
    component['requestedPhase'] = 'BASELINE';

    const resolved = component['resolveRequestedEventContext'](event as ActiveEvent);

    expect(resolved.event_id).toBe(event.event_id);
    expect(resolved.phase).toBe(event.phase);
  });

  it('applies requested phase when requested event id matches fetched event', () => {
    component['requestedEventId'] = event.event_id;
    component['requestedPhase'] = 'BASELINE';

    const resolved = component['resolveRequestedEventContext'](event as ActiveEvent);

    expect(resolved.event_id).toBe(event.event_id);
    expect(resolved.phase).toBe('BASELINE');
  });

  it('uses a user-scoped key for submitter update seen-state storage', () => {
    component['setCurrentUserRef']('EMP-123');

    const storageKey = component['getSeenSubmitterUpdateStorageKey']();

    expect(storageKey).toBe('dmis_needs_list_submitter_updates_seen:emp-123');
  });

  it('preserves RETURNED status when creating my needs list summaries', () => {
    expect(component['toSummaryStatus']('RETURNED')).toBe('RETURNED');
  });

  it('loads my drafts panel collapsed preference from localStorage', () => {
    localStorage.setItem('dmis_stock_dashboard_my_needs_lists_collapsed', 'true');

    component['loadMyNeedsListsCollapsedState']();

    expect(component.myNeedsListsCollapsed).toBeTrue();
  });

  it('persists my drafts panel collapsed preference when toggled', () => {
    component.myNeedsListsCollapsed = false;

    component.toggleMyNeedsListsCollapsed();
    expect(component.myNeedsListsCollapsed).toBeTrue();
    expect(localStorage.getItem('dmis_stock_dashboard_my_needs_lists_collapsed')).toBe('true');

    component.toggleMyNeedsListsCollapsed();
    expect(component.myNeedsListsCollapsed).toBeFalse();
    expect(localStorage.getItem('dmis_stock_dashboard_my_needs_lists_collapsed')).toBe('false');
  });

  it('migrates legacy seen-state and reloads when current user changes', () => {
    localStorage.setItem('dmis_needs_list_submitter_updates_seen', JSON.stringify(['legacy-key']));

    component['setCurrentUserRef']('EMP-123');

    expect(component['seenSubmitterUpdateKeys'].has('legacy-key')).toBeTrue();
    expect(localStorage.getItem('dmis_needs_list_submitter_updates_seen:emp-123')).toBe(
      JSON.stringify(['legacy-key'])
    );
    expect(localStorage.getItem('dmis_needs_list_submitter_updates_seen')).toBeNull();

    component['setCurrentUserRef']('EMP-456');
    expect(component['seenSubmitterUpdateKeys'].size).toBe(0);
  });
});
