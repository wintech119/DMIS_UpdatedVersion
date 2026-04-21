import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of, Subject, throwError } from 'rxjs';
import { MAT_DIALOG_DATA, MatDialog, MatDialogRef } from '@angular/material/dialog';
import { HttpErrorResponse, HttpHeaders } from '@angular/common/http';
import { NO_ERRORS_SCHEMA } from '@angular/core';
import { ActivatedRoute, Router, convertToParamMap } from '@angular/router';

import { StockStatusDashboardComponent } from './stock-status-dashboard.component';
import { AppAccessService } from '../../core/app-access.service';
import { AuthRbacService } from '../services/auth-rbac.service';
import { DashboardData, DashboardDataService } from '../services/dashboard-data.service';
import { DataFreshnessService } from '../services/data-freshness.service';
import { DmisNotificationService } from '../services/notification.service';
import { ActiveEvent, ReplenishmentService, Warehouse, NeedsListDuplicateSummary } from '../services/replenishment.service';
import {
  PhaseWindowEntry,
  PhaseWindowsResponse,
  StockStatusItem,
  WarehouseStockGroup
} from '../models/stock-status.model';
import { NeedsListResponse } from '../models/needs-list.model';
import {
  getFreshnessThresholdsForPhase,
  phaseToIntervalMs,
  toDisplaySeverity,
  toDisplayStatus
} from './utils/display-mappers';
import { ScopePickerDialogComponent, ScopePickerDialogResult } from './dialogs/scope-picker-dialog.component';
import {
  DuplicateGuardDialogComponent,
  DuplicateGuardDialogResult
} from './dialogs/duplicate-guard-dialog.component';
import { LowConfidenceAckDialogComponent } from './dialogs/low-confidence-ack-dialog.component';
import { PhaseWindowsDialogComponent } from './dialogs/phase-windows-dialog.component';

describe('StockStatusDashboardComponent', () => {
  let fixture: ComponentFixture<StockStatusDashboardComponent>;
  let component: StockStatusDashboardComponent;

  let dashboardDataService: jasmine.SpyObj<DashboardDataService>;
  let dataFreshnessService: jasmine.SpyObj<DataFreshnessService>;
  let notificationService: jasmine.SpyObj<DmisNotificationService>;
  let appAccessService: jasmine.SpyObj<AppAccessService>;
  let authRbacService: jasmine.SpyObj<AuthRbacService>;
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

  // Backend-shaped phase-windows response. The service projects `phase_windows`
  // into the `windows` record at the boundary; specs seed both so callers that
  // read either surface see consistent data.
  function createPhaseWindowsResponse(
    options: { manageable?: boolean } = {}
  ): PhaseWindowsResponse {
    const phaseWindows: PhaseWindowEntry[] = [
      { event_id: 99, phase: 'SURGE', scope: 'global', applies_globally: true, demand_hours: 6, planning_hours: 24, source: 'backlog_default', config_id: null, authoritative_tenant: null, justification: null, audit: null },
      { event_id: 99, phase: 'STABILIZED', scope: 'global', applies_globally: true, demand_hours: 72, planning_hours: 72, source: 'backlog_default', config_id: null, authoritative_tenant: null, justification: null, audit: null },
      { event_id: 99, phase: 'BASELINE', scope: 'global', applies_globally: true, demand_hours: 720, planning_hours: 168, source: 'backlog_default', config_id: null, authoritative_tenant: null, justification: null, audit: null }
    ];
    return {
      event_id: 99,
      scope: 'global',
      applies_globally: true,
      phase_windows: phaseWindows,
      windows: {
        SURGE: { demand_hours: 6, planning_hours: 24, safety_factor: 1.5 },
        STABILIZED: { demand_hours: 72, planning_hours: 72, safety_factor: 1.25 },
        BASELINE: { demand_hours: 720, planning_hours: 168, safety_factor: 1.1 }
      },
      manageable_by_active_tenant: !!options.manageable
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
      ['showNetworkError', 'showWarning', 'showSuccess', 'showError']
    );

    replenishmentService = jasmine.createSpyObj<ReplenishmentService>(
      'ReplenishmentService',
      [
        'getActiveEvent',
        'getAllWarehouses',
        'listNeedsLists',
        'getPhaseWindows',
        'updatePhaseWindow',
        'checkActiveNeedsLists'
      ]
    );
    replenishmentService.getActiveEvent.and.returnValue(of(event));
    replenishmentService.getAllWarehouses.and.returnValue(of(warehouses));
    replenishmentService.listNeedsLists.and.returnValue(of({ needs_lists: [], count: 0 }));
    replenishmentService.getPhaseWindows.and.returnValue(
      of(createPhaseWindowsResponse({ manageable: false }))
    );
    replenishmentService.checkActiveNeedsLists.and.returnValue(of([]));

    router = jasmine.createSpyObj<Router>('Router', ['navigate']);
    const dialog = jasmine.createSpyObj<MatDialog>('MatDialog', ['open']);
    appAccessService = jasmine.createSpyObj<AppAccessService>('AppAccessService', ['canAccessNavKey']);
    appAccessService.canAccessNavKey.and.returnValue(false);
    authRbacService = jasmine.createSpyObj<AuthRbacService>('AuthRbacService', ['actorRef']);
    authRbacService.actorRef.and.returnValue(null);
    dataFreshnessService.onRefreshRequested$.and.returnValue(refreshRequested$.asObservable());

    await TestBed.configureTestingModule({
      imports: [StockStatusDashboardComponent],
      providers: [
        { provide: ReplenishmentService, useValue: replenishmentService },
        { provide: DashboardDataService, useValue: dashboardDataService },
        { provide: DataFreshnessService, useValue: dataFreshnessService },
        { provide: DmisNotificationService, useValue: notificationService },
        { provide: Router, useValue: router },
        { provide: AppAccessService, useValue: appAccessService },
        { provide: AuthRbacService, useValue: authRbacService },
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: {
              queryParamMap: convertToParamMap({})
            }
          }
        },
      ]
    })
      .overrideProvider(MatDialog, { useValue: dialog })
      .overrideComponent(StockStatusDashboardComponent, {
        set: { template: '' }
      })
      .compileComponents();

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
    appAccessService.canAccessNavKey.and.returnValue(false);
    authRbacService.actorRef.and.returnValue('EMP-123');

    component['syncAuthContext']();

    expect(component.canAccessReviewQueue).toBeFalse();
  });

  it('allows review queue when preview and review permissions are present', () => {
    appAccessService.canAccessNavKey.and.returnValue(true);
    authRbacService.actorRef.and.returnValue('EMP-123');

    component['syncAuthContext']();

    expect(component.canAccessReviewQueue).toBeTrue();
  });

  it('prefers user_id when matching submitter updates', () => {
    authRbacService.actorRef.and.returnValue('EMP-123');
    appAccessService.canAccessNavKey.and.returnValue(true);
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

    component['syncAuthContext']();

    expect(component['currentUserRef']).toBe('EMP-123');
    expect(component.mySubmissionUpdates.map((row) => row.needs_list_id)).toEqual(['NL-1']);
  });

  it('loads my drafts and submissions with mine filter enabled', () => {
    authRbacService.actorRef.and.returnValue('EMP-123');
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

    component['syncAuthContext']();

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

  it('computes Action Inbox counts from FR02.93 status buckets', () => {
    // 2 awaiting approval (SUBMITTED + PENDING_APPROVAL normalize to SUBMITTED).
    // 3 drafts.
    // 2 returned (RETURNED → MODIFIED, REJECTED → REJECTED, both fold into
    // the "returned" inbox bucket).
    // 1 APPROVED ignored.
    component.myNeedsLists = [
      {
        needs_list_id: 'A1',
        event_id: 99,
        phase: 'SURGE',
        items: [],
        as_of_datetime: '2026-02-16T12:00:00Z',
        status: 'SUBMITTED'
      },
      {
        needs_list_id: 'A2',
        event_id: 99,
        phase: 'SURGE',
        items: [],
        as_of_datetime: '2026-02-16T12:00:00Z',
        status: 'PENDING_APPROVAL'
      },
      {
        needs_list_id: 'D1',
        event_id: 99,
        phase: 'SURGE',
        items: [],
        as_of_datetime: '2026-02-16T12:00:00Z',
        status: 'DRAFT'
      },
      {
        needs_list_id: 'D2',
        event_id: 99,
        phase: 'SURGE',
        items: [],
        as_of_datetime: '2026-02-16T12:00:00Z',
        status: 'DRAFT'
      },
      {
        needs_list_id: 'D3',
        event_id: 99,
        phase: 'SURGE',
        items: [],
        as_of_datetime: '2026-02-16T12:00:00Z',
        status: 'DRAFT'
      },
      {
        needs_list_id: 'R1',
        event_id: 99,
        phase: 'SURGE',
        items: [],
        as_of_datetime: '2026-02-16T12:00:00Z',
        status: 'RETURNED'
      },
      {
        needs_list_id: 'R2',
        event_id: 99,
        phase: 'SURGE',
        items: [],
        as_of_datetime: '2026-02-16T12:00:00Z',
        status: 'REJECTED'
      },
      {
        needs_list_id: 'OK',
        event_id: 99,
        phase: 'SURGE',
        items: [],
        as_of_datetime: '2026-02-16T12:00:00Z',
        status: 'APPROVED'
      }
    ];

    expect(component.actionInbox).toEqual({
      awaitingApproval: 2,
      draftsInProgress: 3,
      returned: 2,
      reviewQueueTarget: '/replenishment/needs-list-review'
    });
    expect(component.actionInboxTotal).toBe(7);
  });

  it('produces a zero-aware category rollup without divide-by-zero artifacts', () => {
    // Items WITHOUT category fall into 'Uncategorized' (per pre-plan review
    // requirement). Mixed severities exercise each bucket; a Water-only/
    // all-good bucket asserts atRiskPct is 0 (not NaN / Infinity).
    component.warehouseGroups = [
      {
        warehouse_id: 1,
        warehouse_name: 'North Depot',
        items: [
          { item_id: 1, available_qty: 0, inbound_strict_qty: 0, burn_rate_per_hour: 0, gap_qty: 0, severity: 'CRITICAL', category: 'Food' },
          { item_id: 2, available_qty: 0, inbound_strict_qty: 0, burn_rate_per_hour: 0, gap_qty: 0, severity: 'WARNING', category: 'Food' },
          { item_id: 3, available_qty: 0, inbound_strict_qty: 0, burn_rate_per_hour: 0, gap_qty: 0, severity: 'OK', category: 'Water' },
          { item_id: 4, available_qty: 0, inbound_strict_qty: 0, burn_rate_per_hour: 0, gap_qty: 0, severity: 'CRITICAL' }
        ],
        critical_count: 2,
        warning_count: 1,
        watch_count: 0,
        ok_count: 1
      }
    ];

    const rollup = component.categoryRollup;
    const byName = (name: string) => rollup.find((r) => r.name === name);

    expect(byName('Food')).toEqual(
      jasmine.objectContaining({ critical: 1, warning: 1, good: 0, atRisk: 2, total: 2, atRiskPct: 100 })
    );
    expect(byName('Water')).toEqual(
      jasmine.objectContaining({ critical: 0, warning: 0, good: 1, atRisk: 0, total: 1, atRiskPct: 0 })
    );
    expect(byName('Uncategorized')).toEqual(
      jasmine.objectContaining({ critical: 1, warning: 0, good: 0, atRisk: 1, total: 1, atRiskPct: 100 })
    );

    for (const row of rollup) {
      expect(Number.isFinite(row.atRiskPct)).toBeTrue();
      expect(row.atRiskPct).toBeGreaterThanOrEqual(0);
      expect(row.atRiskPct).toBeLessThanOrEqual(100);
    }
  });

  it('returns an empty category rollup when no items exist', () => {
    component.warehouseGroups = [
      {
        warehouse_id: 1,
        warehouse_name: 'North Depot',
        items: [],
        critical_count: 0,
        warning_count: 0,
        watch_count: 0,
        ok_count: 0
      }
    ];
    expect(component.categoryRollup).toEqual([]);
  });

  it('returns the full stock item name for item tooltips', () => {
    expect(component.getStockItemTooltip({
      item_id: 42,
      item_name: 'Emergency Shelter Tarp Heavy Duty',
      available_qty: 0,
      inbound_strict_qty: 0,
      burn_rate_per_hour: 0,
      gap_qty: 0
    })).toBe('Emergency Shelter Tarp Heavy Duty');

    expect(component.getStockItemTooltip({
      item_id: 7,
      available_qty: 0,
      inbound_strict_qty: 0,
      burn_rate_per_hour: 0,
      gap_qty: 0
    })).toBe('Item 7');

    expect(component.getStockItemTooltip({
      item_id: 9,
      item_name: '   ',
      available_qty: 0,
      inbound_strict_qty: 0,
      burn_rate_per_hour: 0,
      gap_qty: 0
    })).toBe('Item 9');
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

  // -- CTA gate chain --------------------------------------------------

  function mockDialogRef<R>(result: R): jasmine.SpyObj<MatDialogRef<unknown, R>> {
    const ref = jasmine.createSpyObj<MatDialogRef<unknown, R>>(
      'MatDialogRef',
      ['close', 'afterClosed']
    );
    ref.afterClosed.and.returnValue(of(result));
    return ref;
  }

  it('routes hero, FAB, and warehouse-card triggers through a single CTA gate path', () => {
    const runGateSpy = spyOn<any>(component, 'runGateChain').and.callFake(() => {
      component.ctaInFlight.set(false);
    });

    component.generateNeedsListWithGates('hero', 1);
    component.generateNeedsListWithGates('fab', 2);
    component.generateNeedsListWithGates('warehouse-card', 3);

    expect(runGateSpy).toHaveBeenCalledTimes(3);
    expect(runGateSpy.calls.argsFor(0)[0]).toBe(1);
    expect(runGateSpy.calls.argsFor(1)[0]).toBe(2);
    expect(runGateSpy.calls.argsFor(2)[0]).toBe(3);
  });

  it('opens duplicate-guard dialog when checkActiveNeedsLists returns entries', () => {
    const dialog = TestBed.inject(MatDialog) as jasmine.SpyObj<MatDialog>;
    const dupRef = mockDialogRef<DuplicateGuardDialogResult>(undefined);
    dialog.open.and.returnValue(dupRef as unknown as MatDialogRef<unknown>);

    const duplicate: NeedsListDuplicateSummary = {
      needs_list_id: 'NL-9',
      needs_list_no: 'NL-000009',
      status: 'SUBMITTED',
      created_by: 'alice',
      created_at: '2026-03-01T00:00:00Z',
      warehouse_id: 1,
      items_count: 3,
      item_ids: [1, 2, 3]
    };
    replenishmentService.checkActiveNeedsLists.and.returnValue(of([duplicate]));

    component.generateNeedsListWithGates('hero', 1);

    expect(dialog.open).toHaveBeenCalled();
    expect(dialog.open.calls.mostRecent().args[0]).toBe(DuplicateGuardDialogComponent);
    const config = dialog.open.calls.mostRecent().args[1] as { data: { duplicates: NeedsListDuplicateSummary[]; phase: string } };
    expect(config.data.duplicates).toEqual([duplicate]);
    expect(config.data.phase).toBe('SURGE');
  });

  it('opens low-confidence dialog when the selected warehouse has LOW confidence', () => {
    const dialog = TestBed.inject(MatDialog) as jasmine.SpyObj<MatDialog>;
    const lowConfRef = mockDialogRef<boolean>(false);
    dialog.open.and.returnValue(lowConfRef as unknown as MatDialogRef<unknown>);

    component.warehouseGroups = [
      {
        warehouse_id: 1,
        warehouse_name: 'North Depot',
        items: [
          {
            item_id: 42,
            available_qty: 10,
            inbound_strict_qty: 0,
            burn_rate_per_hour: 0.5,
            gap_qty: 0,
            confidence: { level: 'LOW', reasons: ['Stale inventory'] }
          }
        ],
        critical_count: 0,
        warning_count: 0,
        watch_count: 0,
        ok_count: 0
      }
    ];
    replenishmentService.checkActiveNeedsLists.and.returnValue(of([]));

    component.generateNeedsListWithGates('warehouse-card', 1);

    expect(dialog.open).toHaveBeenCalled();
    expect(dialog.open.calls.mostRecent().args[0]).toBe(LowConfidenceAckDialogComponent);
    const config = dialog.open.calls.mostRecent().args[1] as { data: { warehouseName: string; reasons: string[] } };
    expect(config.data.warehouseName).toBe('North Depot');
    expect(config.data.reasons).toContain('Stale inventory');
  });

  it('opens scope-picker dialog when hero CTA fires without a selected warehouse', () => {
    const dialog = TestBed.inject(MatDialog) as jasmine.SpyObj<MatDialog>;
    const scopeRef = mockDialogRef<ScopePickerDialogResult | undefined>(undefined);
    dialog.open.and.returnValue(scopeRef as unknown as MatDialogRef<unknown>);

    component.selectedWarehouseId = null;
    component.selectedWarehouseIds = [];

    component.generateNeedsListWithGates('hero');

    expect(dialog.open).toHaveBeenCalled();
    expect(dialog.open.calls.mostRecent().args[0]).toBe(ScopePickerDialogComponent);
    expect(replenishmentService.checkActiveNeedsLists).not.toHaveBeenCalled();
  });

  // -- Safe poll loop --------------------------------------------------

  it('safe poll loop does not schedule a timer when document is hidden', () => {
    spyOnProperty(document, 'hidden', 'get').and.returnValue(true);
    const timeoutSpy = spyOn(window, 'setTimeout').and.callThrough();

    component['schedulePoll']();

    expect(timeoutSpy).not.toHaveBeenCalled();
    expect(component['pollTimer']).toBeNull();
  });

  it('safe poll loop honors 429 Retry-After before the next retry', () => {
    spyOnProperty(document, 'hidden', 'get').and.returnValue(false);
    const timeoutSpy = spyOn(window, 'setTimeout').and.callFake(() => 0 as unknown as ReturnType<typeof setTimeout>);
    const error = new HttpErrorResponse({
      status: 429,
      headers: new HttpHeaders({ 'Retry-After': '45' })
    });

    component['onRefreshComplete'](error);

    expect(timeoutSpy).toHaveBeenCalled();
    expect(timeoutSpy.calls.mostRecent().args[1]).toBe(45_000);
  });

  // -- Phase windows ---------------------------------------------------

  it('phase windows edit action is hidden when manageable_by_active_tenant is false', () => {
    component.phaseWindows.set(createPhaseWindowsResponse({ manageable: false }));
    expect(component.canManagePhaseWindows()).toBeFalse();

    component.phaseWindows.set(createPhaseWindowsResponse({ manageable: true }));
    expect(component.canManagePhaseWindows()).toBeTrue();
  });

  it('passes the active event id when fetching phase windows', () => {
    replenishmentService.getPhaseWindows.calls.reset();
    component.activeEvent = event;
    component.loadPhaseWindows();

    expect(replenishmentService.getPhaseWindows).toHaveBeenCalledWith(event.event_id);
  });

  it('does not call getPhaseWindows when no active event is resolved', () => {
    replenishmentService.getPhaseWindows.calls.reset();
    component.activeEvent = null;
    component.loadPhaseWindows();

    expect(replenishmentService.getPhaseWindows).not.toHaveBeenCalled();
  });
});

describe('display-mappers (EP-02 dashboard)', () => {
  it('returns backend-matching freshness thresholds for all phases', () => {
    expect(getFreshnessThresholdsForPhase('SURGE')).toEqual({ highMaxHours: 2, mediumMaxHours: 4 });
    expect(getFreshnessThresholdsForPhase('STABILIZED')).toEqual({ highMaxHours: 6, mediumMaxHours: 12 });
    expect(getFreshnessThresholdsForPhase('BASELINE')).toEqual({ highMaxHours: 24, mediumMaxHours: 48 });
  });

  it('maps each phase to its polling interval in ms', () => {
    expect(phaseToIntervalMs('SURGE')).toBe(300_000);
    expect(phaseToIntervalMs('STABILIZED')).toBe(1_800_000);
    expect(phaseToIntervalMs('BASELINE')).toBe(7_200_000);
  });

  it('warns via [ep02:display-mapper] when toDisplaySeverity gets an unknown value', () => {
    const warnSpy = spyOn(console, 'warn');
    const result = toDisplaySeverity('MYSTERY' as never);
    expect(result).toBe('GOOD');
    expect(warnSpy).toHaveBeenCalledWith(
      '[ep02:display-mapper]',
      jasmine.objectContaining({ source: 'severity', value: 'MYSTERY' })
    );
  });

  it('warns via [ep02:display-mapper] when toDisplayStatus gets an unknown value', () => {
    const warnSpy = spyOn(console, 'warn');
    const result = toDisplayStatus('MYSTERY_STATUS');
    expect(result).toBe('DRAFT');
    expect(warnSpy).toHaveBeenCalledWith(
      '[ep02:display-mapper]',
      jasmine.objectContaining({ source: 'status', value: 'MYSTERY_STATUS' })
    );
  });
});

describe('PhaseWindowsDialogComponent', () => {
  let replSpy: jasmine.SpyObj<ReplenishmentService>;
  let notifySpy: jasmine.SpyObj<DmisNotificationService>;
  let dialogRefSpy: jasmine.SpyObj<MatDialogRef<PhaseWindowsDialogComponent, void>>;

  const initialWindows = {
    SURGE: { demand_hours: 6, planning_hours: 24, safety_factor: 1.5 },
    STABILIZED: { demand_hours: 72, planning_hours: 72, safety_factor: 1.25 },
    BASELINE: { demand_hours: 720, planning_hours: 168, safety_factor: 1.1 }
  };
  const DIALOG_EVENT_ID = 99;

  beforeEach(async () => {
    replSpy = jasmine.createSpyObj<ReplenishmentService>(
      'ReplenishmentService',
      ['updatePhaseWindow']
    );
    notifySpy = jasmine.createSpyObj<DmisNotificationService>(
      'DmisNotificationService',
      ['showError', 'showWarning', 'showSuccess', 'showNetworkError']
    );
    dialogRefSpy = jasmine.createSpyObj<MatDialogRef<PhaseWindowsDialogComponent, void>>(
      'MatDialogRef',
      ['close']
    );

    await TestBed.configureTestingModule({
      imports: [PhaseWindowsDialogComponent],
      providers: [
        { provide: ReplenishmentService, useValue: replSpy },
        { provide: DmisNotificationService, useValue: notifySpy },
        { provide: MatDialogRef, useValue: dialogRefSpy },
        {
          provide: MAT_DIALOG_DATA,
          useValue: { eventId: DIALOG_EVENT_ID, windows: initialWindows }
        }
      ]
    }).compileComponents();
  });

  it('shows a permission warning and closes on 403 PUT response', () => {
    const err = new HttpErrorResponse({ status: 403, error: { error: 'forbidden' } });
    replSpy.updatePhaseWindow.and.returnValue(throwError(() => err));

    const fixture = TestBed.createComponent(PhaseWindowsDialogComponent);
    const dialogComponent = fixture.componentInstance;
    // Change one value so the diff detection issues a PUT and provide a
    // justification so the required validator passes.
    dialogComponent.form.get('SURGE.demand_hours')?.setValue(8);
    dialogComponent.form.get('justification')?.setValue('Storm intensified; shorter windows required.');

    dialogComponent.save();

    expect(replSpy.updatePhaseWindow).toHaveBeenCalledWith(
      DIALOG_EVENT_ID,
      'SURGE',
      8,
      24,
      'Storm intensified; shorter windows required.'
    );
    expect(notifySpy.showWarning).toHaveBeenCalled();
    const message = notifySpy.showWarning.calls.mostRecent().args[0];
    expect(message).toMatch(/permission/i);
    expect(dialogRefSpy.close).toHaveBeenCalledWith();
  });

  it('blocks save when the justification is missing or whitespace-only', () => {
    const fixture = TestBed.createComponent(PhaseWindowsDialogComponent);
    const dialogComponent = fixture.componentInstance;
    dialogComponent.form.get('SURGE.demand_hours')?.setValue(8);
    // Intentionally whitespace-only.
    dialogComponent.form.get('justification')?.setValue('   ');

    dialogComponent.save();

    expect(replSpy.updatePhaseWindow).not.toHaveBeenCalled();
    expect(dialogRefSpy.close).not.toHaveBeenCalled();
    expect(dialogComponent.form.get('justification')?.hasError('required')).toBeTrue();
  });

  it('trims the justification before sending', () => {
    replSpy.updatePhaseWindow.and.returnValue(of({}));

    const fixture = TestBed.createComponent(PhaseWindowsDialogComponent);
    const dialogComponent = fixture.componentInstance;
    dialogComponent.form.get('STABILIZED.planning_hours')?.setValue(96);
    dialogComponent.form.get('justification')?.setValue('  extended planning window  ');

    dialogComponent.save();

    expect(replSpy.updatePhaseWindow).toHaveBeenCalledWith(
      DIALOG_EVENT_ID,
      'STABILIZED',
      72,
      96,
      'extended planning window'
    );
  });
});

// -------------------------------------------------------------------------
// Display severity leakage regression test
//
// The full dashboard template renders status badges for every stock item.
// Internal severity is a 4-bucket value (CRITICAL / WARNING / WATCH / OK) but
// the display boundary must collapse WATCH → WARNING and OK → GOOD. This
// test renders the real template with items deliberately carrying WATCH and
// OK and asserts that no rendered badge contains those raw tokens.
// -------------------------------------------------------------------------
describe('StockStatusDashboardComponent display severity rendering', () => {
  let fixture: ComponentFixture<StockStatusDashboardComponent>;
  let component: StockStatusDashboardComponent;

  const event: ActiveEvent = {
    event_id: 99,
    event_name: 'Storm',
    status: 'ACTIVE',
    phase: 'SURGE',
    declaration_date: '2026-02-10T00:00:00Z'
  };

  beforeEach(async () => {
    localStorage.clear();

    const dashboardDataService = jasmine.createSpyObj<DashboardDataService>(
      'DashboardDataService',
      ['getDashboardData', 'invalidateCache']
    );
    dashboardDataService.getDashboardData.and.returnValue(
      of({
        groups: [],
        as_of_datetime: '2026-02-11T00:00:00Z',
        warnings: [],
        totals: { items: 0, critical: 0, warning: 0, watch: 0, ok: 0 },
        availableCategories: []
      } as DashboardData)
    );
    const dataFreshnessService = jasmine.createSpyObj<DataFreshnessService>(
      'DataFreshnessService',
      ['onRefreshRequested$', 'updateFromWarehouseGroups', 'refreshComplete', 'clear']
    );
    dataFreshnessService.onRefreshRequested$.and.returnValue(new Subject<void>().asObservable());
    const notificationService = jasmine.createSpyObj<DmisNotificationService>(
      'DmisNotificationService',
      ['showNetworkError', 'showWarning', 'showSuccess', 'showError']
    );
    const replenishmentService = jasmine.createSpyObj<ReplenishmentService>(
      'ReplenishmentService',
      ['getActiveEvent', 'getAllWarehouses', 'listNeedsLists', 'getPhaseWindows', 'updatePhaseWindow', 'checkActiveNeedsLists']
    );
    replenishmentService.getActiveEvent.and.returnValue(of(event));
    replenishmentService.getAllWarehouses.and.returnValue(of([
      { warehouse_id: 1, warehouse_name: 'North Depot' }
    ]));
    replenishmentService.listNeedsLists.and.returnValue(of({ needs_lists: [], count: 0 }));
    replenishmentService.getPhaseWindows.and.returnValue(of({
      event_id: 99,
      scope: 'global',
      applies_globally: true,
      phase_windows: [],
      windows: {
        SURGE: { demand_hours: 6, planning_hours: 24, safety_factor: 1.5 },
        STABILIZED: { demand_hours: 72, planning_hours: 72, safety_factor: 1.25 },
        BASELINE: { demand_hours: 720, planning_hours: 168, safety_factor: 1.1 }
      },
      manageable_by_active_tenant: false
    } as PhaseWindowsResponse));
    replenishmentService.checkActiveNeedsLists.and.returnValue(of([]));
    const router = jasmine.createSpyObj<Router>('Router', ['navigate']);
    const appAccessService = jasmine.createSpyObj<AppAccessService>('AppAccessService', ['canAccessNavKey']);
    appAccessService.canAccessNavKey.and.returnValue(false);
    const authRbacService = jasmine.createSpyObj<AuthRbacService>('AuthRbacService', ['actorRef']);
    authRbacService.actorRef.and.returnValue(null);
    const dialog = jasmine.createSpyObj<MatDialog>('MatDialog', ['open']);

    await TestBed.configureTestingModule({
      imports: [StockStatusDashboardComponent],
      providers: [
        { provide: ReplenishmentService, useValue: replenishmentService },
        { provide: DashboardDataService, useValue: dashboardDataService },
        { provide: DataFreshnessService, useValue: dataFreshnessService },
        { provide: DmisNotificationService, useValue: notificationService },
        { provide: Router, useValue: router },
        { provide: AppAccessService, useValue: appAccessService },
        { provide: AuthRbacService, useValue: authRbacService },
        {
          provide: ActivatedRoute,
          useValue: { snapshot: { queryParamMap: convertToParamMap({}) } }
        }
      ],
      // Ignore unknown elements emitted by nested standalone components; this
      // test only inspects the outer dashboard template output.
      schemas: [NO_ERRORS_SCHEMA]
    })
      .overrideProvider(MatDialog, { useValue: dialog })
      // Deliberately DO NOT override the template — we need the real DOM
      // to inspect rendered badge text.
      .compileComponents();

    fixture = TestBed.createComponent(StockStatusDashboardComponent);
    component = fixture.componentInstance;
  });

  function seedDashboardWithMixedSeverities(): void {
    component.activeEvent = event;
    component.allWarehouses = [{ warehouse_id: 1, warehouse_name: 'North Depot' }];
    component.loading = false;
    component.dataLoadedSuccessfully = true;
    // Force the filters panel expanded so the severity chip listbox is in
    // the DOM for querying.
    component.filtersExpanded = true;
    component.warehouseGroups = [
      {
        warehouse_id: 1,
        warehouse_name: 'North Depot',
        items: [
          makeItem(1, 'Critical Item', 'CRITICAL'),
          makeItem(2, 'Warning Item', 'WARNING'),
          makeItem(3, 'Watch Item', 'WATCH'),
          makeItem(4, 'OK Item', 'OK')
        ],
        critical_count: 1,
        warning_count: 1,
        watch_count: 1,
        ok_count: 1
      }
    ];
  }

  function makeItem(id: number, name: string, severity: 'CRITICAL' | 'WARNING' | 'WATCH' | 'OK'): StockStatusItem {
    return {
      item_id: id,
      item_name: name,
      available_qty: 10,
      inbound_strict_qty: 0,
      burn_rate_per_hour: 0.5,
      gap_qty: 0,
      severity
    };
  }

  it('never renders raw WATCH or OK tokens in severity status chips', () => {
    // First detectChanges runs ngOnInit → autoLoadDashboard → loadMultiWarehouseStatus
    // which resets warehouseGroups from the mock service response. Seed the
    // mixed-severity groups AFTER that lifecycle completes, then re-render.
    fixture.detectChanges();
    seedDashboardWithMixedSeverities();
    fixture.detectChanges();

    const host = fixture.nativeElement as HTMLElement;
    // Severity chip is the first app-ops-status-chip inside each desktop
    // row's Status column (first td) and the first chip inside each mobile
    // card header. Freshness chips sit in a later cell / position and are
    // excluded by the :first-of-type / :first-child selector.
    const severityChips = Array.from(
      host.querySelectorAll<HTMLElement>(
        'tr.stock-dashboard__item-row > td:first-of-type app-ops-status-chip span.ops-chip,'
          + ' .stock-dashboard__item-card-header > app-ops-status-chip:first-of-type span.ops-chip'
      )
    );

    expect(severityChips.length).toBeGreaterThan(0);

    for (const chip of severityChips) {
      const text = (chip.textContent ?? '').trim().toUpperCase();

      // Display-boundary vocabulary is CRITICAL / WARNING / GOOD only.
      expect(['CRITICAL', 'WARNING', 'GOOD']).toContain(text);
      // Tone class must be one of the 3-bucket aliases (GOOD maps to `success` tone).
      expect(chip.className).toMatch(/ops-chip--(critical|warning|success)/);
      expect(chip.className).not.toMatch(/ops-chip--watch\b/);
      expect(chip.className).not.toMatch(/ops-chip--ok\b/);
    }

    // The per-row bucket class must likewise be 3-bucket only.
    const itemRows = Array.from(
      host.querySelectorAll<HTMLElement>('tr.stock-dashboard__item-row')
    );
    expect(itemRows.length).toBeGreaterThan(0);
    for (const row of itemRows) {
      expect(row.className).toMatch(/stock-dashboard__item-row--(critical|warning|good)/);
      expect(row.className).not.toMatch(/stock-dashboard__item-row--watch\b/);
      expect(row.className).not.toMatch(/stock-dashboard__item-row--ok\b/);
    }
  });

  it('renders the severity filter chips with only CRITICAL / WARNING / GOOD labels', () => {
    fixture.detectChanges();
    // Filters panel is gated on `warehouseGroups.length > 0`; seed after
    // ngOnInit so the chip-listbox is in the DOM when we query it.
    seedDashboardWithMixedSeverities();
    fixture.detectChanges();

    const host = fixture.nativeElement as HTMLElement;
    const chipLabels = Array.from(
      host.querySelectorAll<HTMLElement>('mat-chip-option')
    )
      .map((el) => (el.textContent ?? '').trim().toUpperCase())
      // Drop category-filter chips by class — only severity-filter chips carry chip-critical/warning/good.
      .filter((label) => label === 'CRITICAL' || label === 'WARNING' || label === 'GOOD' || label === 'WATCH' || label === 'OK');

    expect(chipLabels).toContain('CRITICAL');
    expect(chipLabels).toContain('WARNING');
    expect(chipLabels).toContain('GOOD');
    expect(chipLabels).not.toContain('WATCH');
    expect(chipLabels).not.toContain('OK');
  });

  it('renders the mobile FAB when an event is active with warehouses', () => {
    fixture.detectChanges();
    seedDashboardWithMixedSeverities();
    fixture.detectChanges();

    const host = fixture.nativeElement as HTMLElement;
    // CSS toggles the FAB's display between desktop and narrow viewports,
    // but the DOM element itself must always be rendered when there is an
    // active event with warehouses — this is Kemar's one-tap field CTA.
    const fab = host.querySelector<HTMLButtonElement>('button.stock-dashboard__fab');
    expect(fab).not.toBeNull();
    expect(fab?.disabled).toBeFalse();
    expect((fab?.textContent ?? '').toLowerCase()).toContain('generate');
  });

  it('renders the Action Inbox chips with FR02.93 labels', () => {
    fixture.detectChanges();
    component.activeEvent = event;
    component.myNeedsLists = [
      {
        needs_list_id: 'A1',
        event_id: 99,
        phase: 'SURGE',
        items: [],
        as_of_datetime: '2026-02-16T12:00:00Z',
        status: 'SUBMITTED'
      },
      {
        needs_list_id: 'D1',
        event_id: 99,
        phase: 'SURGE',
        items: [],
        as_of_datetime: '2026-02-16T12:00:00Z',
        status: 'DRAFT'
      }
    ];
    fixture.detectChanges();

    const host = fixture.nativeElement as HTMLElement;
    const chipLabels = Array.from(
      host.querySelectorAll<HTMLElement>('.ops-action-inbox__chips .ops-chip')
    ).map((el) => (el.textContent ?? '').trim());

    expect(chipLabels.length).toBe(3);
    expect(chipLabels.some((l) => l.includes('awaiting approval'))).toBeTrue();
    expect(chipLabels.some((l) => l.includes('drafts in progress'))).toBeTrue();
    expect(chipLabels.some((l) => l.includes('returned'))).toBeTrue();
  });

  it('renders risk-by-category bars without divide-by-zero artifacts', () => {
    fixture.detectChanges();
    seedDashboardWithMixedSeverities();
    fixture.detectChanges();

    const host = fixture.nativeElement as HTMLElement;
    const categoryRows = Array.from(
      host.querySelectorAll<HTMLElement>('.stock-dashboard__category-row')
    );
    expect(categoryRows.length).toBeGreaterThan(0);

    for (const row of categoryRows) {
      const pctText = (row.querySelector('.stock-dashboard__category-row-pct')?.textContent ?? '').trim();
      // Percent label must NEVER read as NaN% / Infinity% even for all-good buckets.
      expect(pctText).not.toContain('NaN');
      expect(pctText).not.toContain('Infinity');
    }
  });
});
