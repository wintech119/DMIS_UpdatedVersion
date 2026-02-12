import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of, Subject, throwError } from 'rxjs';
import { MatDialog } from '@angular/material/dialog';
import { Router } from '@angular/router';

import { StockStatusDashboardComponent } from './stock-status-dashboard.component';
import { DashboardData, DashboardDataService } from '../services/dashboard-data.service';
import { DataFreshnessService } from '../services/data-freshness.service';
import { DmisNotificationService } from '../services/notification.service';
import { ActiveEvent, ReplenishmentService, Warehouse } from '../services/replenishment.service';
import { WarehouseStockGroup } from '../models/stock-status.model';

describe('StockStatusDashboardComponent', () => {
  let fixture: ComponentFixture<StockStatusDashboardComponent>;
  let component: StockStatusDashboardComponent;

  let dashboardDataService: jasmine.SpyObj<DashboardDataService>;
  let dataFreshnessService: jasmine.SpyObj<DataFreshnessService>;
  let notificationService: jasmine.SpyObj<DmisNotificationService>;

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
      ['showNetworkError', 'showWarning']
    );

    const replenishmentService = jasmine.createSpyObj<ReplenishmentService>(
      'ReplenishmentService',
      ['getActiveEvent', 'getAllWarehouses']
    );
    replenishmentService.getActiveEvent.and.returnValue(of(event));
    replenishmentService.getAllWarehouses.and.returnValue(of(warehouses));

    const router = jasmine.createSpyObj<Router>('Router', ['navigate']);
    const dialog = jasmine.createSpyObj<MatDialog>('MatDialog', ['open']);
    dataFreshnessService.onRefreshRequested$.and.returnValue(refreshRequested$.asObservable());

    await TestBed.configureTestingModule({
      imports: [StockStatusDashboardComponent],
      providers: [
        { provide: ReplenishmentService, useValue: replenishmentService },
        { provide: DashboardDataService, useValue: dashboardDataService },
        { provide: DataFreshnessService, useValue: dataFreshnessService },
        { provide: DmisNotificationService, useValue: notificationService },
        { provide: Router, useValue: router },
        { provide: MatDialog, useValue: dialog }
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
});
