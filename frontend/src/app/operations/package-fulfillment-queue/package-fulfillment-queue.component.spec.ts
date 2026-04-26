import { HttpErrorResponse } from '@angular/common/http';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { ActivatedRoute, Router } from '@angular/router';
import { of, throwError } from 'rxjs';

import { AuthRbacService } from '../../replenishment/services/auth-rbac.service';
import { PackageQueueItem, PackageSummary } from '../models/operations.model';
import { OperationsService } from '../services/operations.service';
import {
  getOperationsPackageTone,
  getOperationsRequestTone,
  getOperationsUrgencyTone,
} from '../operations-display.util';
import { PackageFulfillmentQueueComponent } from './package-fulfillment-queue.component';

describe('PackageFulfillmentQueueComponent', () => {
  const authStub = {
    ensureLoaded: jasmine.createSpy('ensureLoaded').and.returnValue(of(void 0)),
    currentUserRef: signal<string | null>('kemar.logistics'),
  };
  const operationsService = jasmine.createSpyObj<OperationsService>('OperationsService', ['getPackagesQueue']);
  const router = jasmine.createSpyObj<Router>('Router', ['navigate']);

  function buildQueueItem(overrides: Partial<PackageQueueItem> = {}): PackageQueueItem {
    return {
      reliefrqst_id: 95009,
      tracking_no: 'RQ-95009',
      agency_id: 1,
      agency_name: 'Parish Shelter',
      eligible_event_id: null,
      event_name: 'Flood Response',
      urgency_ind: 'H',
      status_code: 'APPROVED_FOR_FULFILLMENT',
      status_label: 'Approved for Fulfillment',
      request_date: '2026-04-10',
      create_dtime: '2026-04-10T09:00:00Z',
      review_dtime: null,
      action_dtime: null,
      rqst_notes_text: null,
      review_notes_text: null,
      status_reason_desc: null,
      version_nbr: 1,
      item_count: 1,
      total_requested_qty: '2',
      total_issued_qty: '0',
      reliefpkg_id: 77001,
      package_tracking_no: 'PKG-77001',
      package_status: null,
      execution_status: null,
      needs_list_id: null,
      compatibility_bridge: false,
      request_mode: null,
      authority_context: null,
      requesting_tenant_id: null,
      requesting_agency_id: null,
      beneficiary_tenant_id: null,
      beneficiary_agency_id: null,
      current_package: null,
      ...overrides,
    };
  }

  function buildPackageSummary(overrides: Partial<PackageSummary> = {}): PackageSummary {
    return {
      reliefpkg_id: 77001,
      tracking_no: 'PKG-77001',
      reliefrqst_id: 95009,
      agency_id: 1,
      eligible_event_id: null,
      source_warehouse_id: 9001,
      to_inventory_id: 9002,
      destination_warehouse_name: 'Destination WH',
      status_code: 'D',
      status_label: 'Dispatched',
      dispatch_dtime: null,
      received_dtime: null,
      transport_mode: null,
      comments_text: null,
      version_nbr: 1,
      execution_status: null,
      needs_list_id: null,
      compatibility_bridge: false,
      ...overrides,
    };
  }

  beforeEach(async () => {
    authStub.ensureLoaded.calls.reset();
    operationsService.getPackagesQueue.and.returnValue(of({ results: [] }));

    await TestBed.configureTestingModule({
      imports: [NoopAnimationsModule, PackageFulfillmentQueueComponent],
      providers: [
        { provide: AuthRbacService, useValue: authStub },
        { provide: OperationsService, useValue: operationsService },
        { provide: Router, useValue: router },
        // The redesigned template includes a `routerLink` to the Dispatch
        // Queue. The `RouterLink` directive injects `ActivatedRoute` even
        // for absolute URLs, so we stub the minimal shape it reads from
        // without pulling in the full router (which would clash with the
        // spy `Router` above).
        {
          provide: ActivatedRoute,
          useValue: { snapshot: { url: [] }, url: of([]) },
        },
      ],
    }).compileComponents();
  });

  it('treats legacy pending package rows as ready when no override approval is pending', () => {
    const fixture = TestBed.createComponent(PackageFulfillmentQueueComponent);
    const component = fixture.componentInstance;
    fixture.detectChanges();

    expect(
      component.isReady(
        buildQueueItem({
          package_status: 'P',
          current_package: null,
          execution_status: null,
        }),
      ),
    ).toBeTrue();
  });

  it('does not treat legacy pending package rows as ready while override approval is pending', () => {
    const fixture = TestBed.createComponent(PackageFulfillmentQueueComponent);
    const component = fixture.componentInstance;
    fixture.detectChanges();

    expect(
      component.isReady(
        buildQueueItem({
          package_status: 'P',
          current_package: null,
          execution_status: 'PENDING_OVERRIDE_APPROVAL',
        }),
      ),
    ).toBeFalse();
  });

  it('excludes dispatched, received, and legacy closed rows from the active-work queue', () => {
    spyOn(console, 'warn');
    operationsService.getPackagesQueue.and.returnValue(
      of({
        results: [
          buildQueueItem({ reliefrqst_id: 1, status_code: 'APPROVED_FOR_FULFILLMENT' }),
          // DISPATCHED / RECEIVED belong on PackageStatusCode, routed via current_package.
          buildQueueItem({
            reliefrqst_id: 2,
            status_code: 'APPROVED_FOR_FULFILLMENT',
            current_package: buildPackageSummary({ status_code: 'DISPATCHED' }),
          }),
          buildQueueItem({
            reliefrqst_id: 3,
            status_code: 'APPROVED_FOR_FULFILLMENT',
            current_package: buildPackageSummary({ status_code: 'RECEIVED' }),
          }),
          // Legacy D / C live on package_status (PackageStatusCode | null).
          buildQueueItem({ reliefrqst_id: 4, package_status: 'D' }),
          buildQueueItem({ reliefrqst_id: 5, package_status: 'C' }),
        ],
      }),
    );

    const fixture = TestBed.createComponent(PackageFulfillmentQueueComponent);
    const component = fixture.componentInstance;
    fixture.detectChanges();

    const ids = component.filteredItems().map((row) => row.reliefrqst_id);
    expect(ids).toContain(1);
    expect(ids).not.toContain(2);
    expect(ids).not.toContain(3);
    expect(ids).not.toContain(4);
    expect(ids).not.toContain(5);
    expect(console.warn).toHaveBeenCalledTimes(4);
  });

  it('excludes non-approved request rows from the active-work queue', () => {
    spyOn(console, 'warn');
    operationsService.getPackagesQueue.and.returnValue(
      of({
        results: [
          buildQueueItem({ reliefrqst_id: 10, status_code: 'APPROVED_FOR_FULFILLMENT' }),
          buildQueueItem({ reliefrqst_id: 11, status_code: 'PARTIALLY_FULFILLED' }),
          buildQueueItem({ reliefrqst_id: 12, status_code: 'DRAFT' }),
          buildQueueItem({ reliefrqst_id: 13, status_code: 'SUBMITTED' }),
          buildQueueItem({ reliefrqst_id: 14, status_code: 'UNDER_ELIGIBILITY_REVIEW' }),
          buildQueueItem({ reliefrqst_id: 15, status_code: 'INELIGIBLE' }),
          buildQueueItem({ reliefrqst_id: 16, status_code: 'CANCELLED' }),
          buildQueueItem({ reliefrqst_id: 17, status_code: 'FULFILLED' }),
        ],
      }),
    );

    const fixture = TestBed.createComponent(PackageFulfillmentQueueComponent);
    const component = fixture.componentInstance;
    fixture.detectChanges();

    expect(component.filteredItems().map((row) => row.reliefrqst_id)).toEqual([10, 11]);
    expect(console.warn).toHaveBeenCalledTimes(6);
  });

  it('does not navigate directly to fulfillment for an out-of-contract request row', () => {
    const fixture = TestBed.createComponent(PackageFulfillmentQueueComponent);
    const component = fixture.componentInstance;
    fixture.detectChanges();
    spyOn(console, 'warn');
    router.navigate.calls.reset();

    component.fulfillRequest(buildQueueItem({ status_code: 'UNDER_ELIGIBILITY_REVIEW' }));

    expect(router.navigate).not.toHaveBeenCalled();
    expect(console.warn).toHaveBeenCalled();
  });

  it('keeps override-rejected package attempts visible for a fresh fulfillment attempt', () => {
    operationsService.getPackagesQueue.and.returnValue(
      of({
        results: [
          buildQueueItem({
            reliefrqst_id: 7,
            status_code: 'APPROVED_FOR_FULFILLMENT',
            current_package: buildPackageSummary({ status_code: 'REJECTED' }),
          }),
        ],
      }),
    );

    const fixture = TestBed.createComponent(PackageFulfillmentQueueComponent);
    const component = fixture.componentInstance;
    fixture.detectChanges();

    const [row] = component.filteredItems();
    expect(row?.reliefrqst_id).toBe(7);
    expect(component.getFulfillmentStage(row!)).toBe('preparing');
  });

  it('does not expose a Dispatched option in filterOptions', () => {
    const fixture = TestBed.createComponent(PackageFulfillmentQueueComponent);
    const component = fixture.componentInstance;
    fixture.detectChanges();

    const values = component.filterOptions.map((option) => option.value);
    expect(values).not.toContain('dispatched' as never);
    expect(values).toEqual(jasmine.arrayContaining(['all', 'awaiting', 'drafts', 'preparing', 'ready']));
  });

  it('renders the error branch with a working Retry CTA when the queue fails to load', () => {
    operationsService.getPackagesQueue.and.returnValue(
      throwError(() => new HttpErrorResponse({ status: 503, statusText: 'Service Unavailable' })),
    );

    const fixture = TestBed.createComponent(PackageFulfillmentQueueComponent);
    const component = fixture.componentInstance;
    fixture.detectChanges();

    expect(component.errored()).toBeTrue();
    expect(component.loadError()).toBeTruthy();

    const errorEl = fixture.nativeElement.querySelector('dmis-empty-state[icon="error_outline"]');
    expect(errorEl).not.toBeNull();

    operationsService.getPackagesQueue.calls.reset();
    operationsService.getPackagesQueue.and.returnValue(
      of({ results: [buildQueueItem({ reliefrqst_id: 42 })] }),
    );

    component.refreshQueue();
    fixture.detectChanges();

    expect(operationsService.getPackagesQueue).toHaveBeenCalled();
    expect(component.errored()).toBeFalse();
    expect(component.loadError()).toBeNull();
    expect(component.filteredItems().length).toBe(1);
  });

  it('routes metric-strip clicks through setFilter with the mapped token', () => {
    operationsService.getPackagesQueue.and.returnValue(
      of({
        results: [
          buildQueueItem({ reliefrqst_id: 10, status_code: 'APPROVED_FOR_FULFILLMENT' }),
          buildQueueItem({
            reliefrqst_id: 11,
            current_package: buildPackageSummary({ status_code: 'DRAFT' }),
          }),
        ],
      }),
    );

    const fixture = TestBed.createComponent(PackageFulfillmentQueueComponent);
    const component = fixture.componentInstance;
    fixture.detectChanges();

    component.onMetricClick({ label: 'Drafts', value: '1', interactive: true, token: 'drafts' });
    expect(component.activeFilter()).toBe('drafts');

    component.onMetricClick({ label: 'All', value: '2', interactive: true, token: 'all' });
    expect(component.activeFilter()).toBe('all');
  });

  it('ignores metric-strip clicks with unexpected filter tokens', () => {
    const fixture = TestBed.createComponent(PackageFulfillmentQueueComponent);
    const component = fixture.componentInstance;
    fixture.detectChanges();

    component.setFilter('drafts');
    component.onMetricClick({ label: 'Invalid', value: '1', interactive: true, token: 'not-a-filter' });

    expect(component.activeFilter()).toBe('drafts');
  });

  it('derives activeQueueCount from queueStats', () => {
    spyOn(console, 'warn');
    operationsService.getPackagesQueue.and.returnValue(
      of({
        results: [
          buildQueueItem({ reliefrqst_id: 70, status_code: 'APPROVED_FOR_FULFILLMENT' }),
          buildQueueItem({
            reliefrqst_id: 71,
            current_package: buildPackageSummary({ status_code: 'DRAFT' }),
          }),
          buildQueueItem({
            reliefrqst_id: 72,
            current_package: buildPackageSummary({ status_code: 'DISPATCHED' }),
          }),
        ],
      }),
    );

    const fixture = TestBed.createComponent(PackageFulfillmentQueueComponent);
    const component = fixture.componentInstance;
    fixture.detectChanges();

    const statsTotal = component.queueStats().reduce((total, stat) => total + stat.value, 0);
    expect(component.activeQueueCount()).toBe(statsTotal);
    expect(component.activeQueueCount()).toBe(2);
  });

  it('applies priority, warehouse, and sort controls within filteredItems', () => {
    operationsService.getPackagesQueue.and.returnValue(
      of({
        results: [
          buildQueueItem({
            reliefrqst_id: 70,
            urgency_ind: 'H',
            create_dtime: '2026-04-11T09:00:00Z',
            current_package: buildPackageSummary({
              reliefpkg_id: 77070,
              tracking_no: 'PKG-77070',
              source_warehouse_id: 9002,
              status_code: 'DRAFT',
            }),
          }),
          buildQueueItem({
            reliefrqst_id: 71,
            urgency_ind: 'M',
            create_dtime: '2026-04-09T09:00:00Z',
            current_package: buildPackageSummary({
              reliefpkg_id: 77071,
              tracking_no: 'PKG-77071',
              source_warehouse_id: 9001,
              status_code: 'DRAFT',
            }),
          }),
          buildQueueItem({
            reliefrqst_id: 72,
            urgency_ind: 'L',
            create_dtime: '2026-04-10T09:00:00Z',
            current_package: buildPackageSummary({
              reliefpkg_id: 77072,
              tracking_no: 'PKG-77072',
              source_warehouse_id: 9002,
              status_code: 'DRAFT',
            }),
          }),
        ],
      }),
    );

    const fixture = TestBed.createComponent(PackageFulfillmentQueueComponent);
    const component = fixture.componentInstance;
    fixture.detectChanges();

    expect(component.warehouseOptions()).toEqual([
      { value: '9001', label: 'Warehouse 9001' },
      { value: '9002', label: 'Warehouse 9002' },
    ]);

    component.onPriorityChange('HIGH');
    expect(component.filteredItems().map((row) => row.reliefrqst_id)).toEqual([70]);

    component.onPriorityChange('all');
    component.onWarehouseChange('9001');
    expect(component.filteredItems().map((row) => row.reliefrqst_id)).toEqual([71]);

    component.onWarehouseChange('all');
    component.onSortChange('newest');
    expect(component.filteredItems().map((row) => row.reliefrqst_id)).toEqual([70, 72, 71]);
  });

  it('syncs queueMetrics.active with the lower filter chip selection (shared source of truth)', () => {
    operationsService.getPackagesQueue.and.returnValue(
      of({
        results: [
          buildQueueItem({ reliefrqst_id: 20, status_code: 'APPROVED_FOR_FULFILLMENT' }),
          buildQueueItem({
            reliefrqst_id: 21,
            current_package: buildPackageSummary({ status_code: 'DRAFT' }),
          }),
        ],
      }),
    );

    const fixture = TestBed.createComponent(PackageFulfillmentQueueComponent);
    const component = fixture.componentInstance;
    fixture.detectChanges();

    component.setFilter('preparing');
    const preparingActive = component.queueMetrics().find((m) => m.token === 'preparing')?.active;
    const othersActive = component.queueMetrics().filter((m) => m.token !== 'preparing').map((m) => m.active);
    expect(preparingActive).toBeTrue();
    expect(othersActive.every((a) => a === false)).toBeTrue();

    component.setFilter('ready');
    const readyActive = component.queueMetrics().find((m) => m.token === 'ready')?.active;
    const preparingAfter = component.queueMetrics().find((m) => m.token === 'preparing')?.active;
    expect(readyActive).toBeTrue();
    expect(preparingAfter).toBeFalse();
  });

  it('produces identical filteredItems whether filter is set from the top strip or the chip row', () => {
    operationsService.getPackagesQueue.and.returnValue(
      of({
        results: [
          buildQueueItem({ reliefrqst_id: 30, status_code: 'APPROVED_FOR_FULFILLMENT' }),
          buildQueueItem({
            reliefrqst_id: 31,
            current_package: buildPackageSummary({ status_code: 'DRAFT' }),
          }),
          buildQueueItem({
            reliefrqst_id: 32,
            current_package: buildPackageSummary({ status_code: 'COMMITTED' }),
          }),
        ],
      }),
    );

    const fixture = TestBed.createComponent(PackageFulfillmentQueueComponent);
    const component = fixture.componentInstance;
    fixture.detectChanges();

    component.onMetricClick({ label: 'Drafts', value: '1', interactive: true, token: 'drafts' });
    const viaMetric = component.filteredItems().map((r) => r.reliefrqst_id);

    component.setFilter('all');
    component.setFilter('drafts');
    const viaChip = component.filteredItems().map((r) => r.reliefrqst_id);

    expect(viaMetric).toEqual(viaChip);
    expect(viaChip).toEqual([31]);
  });

  it('resolves the redesigned queue tone palette for APPROVED / LOW / MEDIUM / DRAFT', () => {
    expect(getOperationsRequestTone('APPROVED_FOR_FULFILLMENT')).toBe('success');
    expect(getOperationsUrgencyTone('L')).toBe('review');
    expect(getOperationsUrgencyTone('M')).toBe('warning');
    expect(getOperationsPackageTone('DRAFT')).toBe('muted');
    expect(getOperationsPackageTone('A')).toBe('muted');
  });

  it('renders each row as a non-interactive listitem with a real <button> activator for a11y', () => {
    operationsService.getPackagesQueue.and.returnValue(
      of({
        results: [buildQueueItem({ reliefrqst_id: 51, tracking_no: 'RQ-51' })],
      }),
    );

    const fixture = TestBed.createComponent(PackageFulfillmentQueueComponent);
    fixture.detectChanges();

    const host: HTMLElement = fixture.nativeElement;
    const article = host.querySelector('article.pfq-row') as HTMLElement;
    expect(article).not.toBeNull();
    // The article is the listitem container — it must not be the focusable
    // activator (no tabindex, no button/link role, no click/keydown handlers).
    expect(article.getAttribute('role')).toBe('listitem');
    expect(article.hasAttribute('tabindex')).toBeFalse();

    const activator = article.querySelector(
      'button.pfq-row__activator',
    ) as HTMLButtonElement;
    expect(activator).not.toBeNull();
    expect(activator.type).toBe('button');
    expect(activator.getAttribute('aria-label') ?? '').toContain('Open request');
    expect(activator.getAttribute('aria-label') ?? '').toContain('RQ-51');
  });

  it('activates fulfillRequest when the full-row activator button is clicked', () => {
    operationsService.getPackagesQueue.and.returnValue(
      of({
        results: [buildQueueItem({ reliefrqst_id: 52, tracking_no: 'RQ-52' })],
      }),
    );

    const fixture = TestBed.createComponent(PackageFulfillmentQueueComponent);
    fixture.detectChanges();

    router.navigate.calls.reset();

    const host: HTMLElement = fixture.nativeElement;
    const activator = host.querySelector(
      'button.pfq-row__activator',
    ) as HTMLButtonElement;
    expect(activator).not.toBeNull();
    activator.click();

    expect(router.navigate).toHaveBeenCalledWith([
      '/operations/package-fulfillment',
      52,
    ]);
  });
});
