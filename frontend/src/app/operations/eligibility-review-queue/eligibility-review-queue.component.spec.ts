import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { Router } from '@angular/router';
import { of, Subject, throwError } from 'rxjs';

import { AuthRbacService } from '../../replenishment/services/auth-rbac.service';
import { DmisNotificationService } from '../../replenishment/services/notification.service';
import { RequestSummary } from '../models/operations.model';
import { OperationsService } from '../services/operations.service';
import { EligibilityReviewQueueComponent } from './eligibility-review-queue.component';

describe('EligibilityReviewQueueComponent', () => {
  const authStub = {
    ensureLoaded: jasmine.createSpy('ensureLoaded').and.returnValue(of(void 0)),
    currentUserRef: signal<string | null>('kemar.logistics'),
  };
  const operationsService = jasmine.createSpyObj<OperationsService>('OperationsService', ['getEligibilityQueue']);
  const notificationService = jasmine.createSpyObj<DmisNotificationService>('DmisNotificationService', ['showNetworkError']);
  const router = jasmine.createSpyObj<Router>('Router', ['navigate', 'navigateByUrl']);

  function buildSummary(overrides: Partial<RequestSummary> = {}): RequestSummary {
    return {
      reliefrqst_id: 9001,
      tracking_no: 'RQ-9001',
      agency_id: 1,
      agency_name: 'Parish Shelter',
      eligible_event_id: null,
      event_name: 'Flood Response',
      urgency_ind: 'H',
      status_code: 'UNDER_ELIGIBILITY_REVIEW',
      status_label: 'Under Eligibility Review',
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
      reliefpkg_id: null,
      package_tracking_no: null,
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
      ...overrides,
    };
  }

  beforeEach(async () => {
    authStub.ensureLoaded.calls.reset();
    operationsService.getEligibilityQueue.calls.reset();
    notificationService.showNetworkError.calls.reset();
    router.navigate.calls.reset();
    router.navigateByUrl.calls.reset();

    operationsService.getEligibilityQueue.and.returnValue(of({ results: [] }));

    await TestBed.configureTestingModule({
      imports: [NoopAnimationsModule, EligibilityReviewQueueComponent],
      providers: [
        { provide: AuthRbacService, useValue: authStub },
        { provide: DmisNotificationService, useValue: notificationService },
        { provide: OperationsService, useValue: operationsService },
        { provide: Router, useValue: router },
      ],
    }).compileComponents();
  });

  it('defensively filters out rows whose status is not UNDER_ELIGIBILITY_REVIEW', () => {
    operationsService.getEligibilityQueue.and.returnValue(of({
      results: [
        buildSummary({ reliefrqst_id: 1, status_code: 'UNDER_ELIGIBILITY_REVIEW' }),
        buildSummary({ reliefrqst_id: 2, status_code: 'APPROVED_FOR_FULFILLMENT' }),
        buildSummary({ reliefrqst_id: 3, status_code: 'REJECTED' }),
        buildSummary({ reliefrqst_id: 4, status_code: 'UNDER_ELIGIBILITY_REVIEW' }),
      ],
    }));

    const fixture = TestBed.createComponent(EligibilityReviewQueueComponent);
    fixture.detectChanges();

    const actionable = fixture.componentInstance.actionableRequests();
    expect(actionable.map((row) => row.reliefrqst_id).sort()).toEqual([1, 4]);
  });

  it('renders the retry empty state when the queue load fails, and retrying re-fetches', () => {
    operationsService.getEligibilityQueue.and.returnValue(throwError(() => new Error('network down')));

    const fixture = TestBed.createComponent(EligibilityReviewQueueComponent);
    fixture.detectChanges();

    expect(fixture.componentInstance.loadError()).toBe(
      'We could not load the eligibility queue. Check your connection and try again.',
    );
    expect(notificationService.showNetworkError).toHaveBeenCalledTimes(1);
    expect(notificationService.showNetworkError.calls.mostRecent().args[0]).toBe(
      'We could not load the eligibility queue. Check your connection and try again.',
    );
    expect(notificationService.showNetworkError.calls.mostRecent().args[1]).toEqual(jasmine.any(Function));

    const host: HTMLElement = fixture.nativeElement;
    const emptyState = host.querySelector('dmis-empty-state');
    expect(emptyState).not.toBeNull();
    expect(emptyState?.getAttribute('title')).toBe('Unable to load queue');
    expect(emptyState?.getAttribute('actionLabel')).toBe('Retry');

    operationsService.getEligibilityQueue.calls.reset();
    operationsService.getEligibilityQueue.and.returnValue(of({
      results: [buildSummary({ reliefrqst_id: 77, status_code: 'UNDER_ELIGIBILITY_REVIEW' })],
    }));

    const retryButton = host.querySelector('dmis-empty-state button');
    expect(retryButton).not.toBeNull();
    retryButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    fixture.detectChanges();

    expect(operationsService.getEligibilityQueue).toHaveBeenCalledTimes(1);
    expect(fixture.componentInstance.loadError()).toBeNull();
    expect(fixture.componentInstance.actionableRequests().length).toBe(1);
  });

  it('ignores retry clicks while the initial load is still in flight', () => {
    const response$ = new Subject<{ results: RequestSummary[] }>();
    operationsService.getEligibilityQueue.and.returnValue(response$.asObservable());

    const fixture = TestBed.createComponent(EligibilityReviewQueueComponent);
    fixture.detectChanges();

    expect(operationsService.getEligibilityQueue).toHaveBeenCalledTimes(1);
    expect(fixture.componentInstance.loading()).toBeTrue();

    fixture.componentInstance.retryLoad();
    expect(operationsService.getEligibilityQueue).toHaveBeenCalledTimes(1);

    response$.next({ results: [] });
    response$.complete();
    fixture.detectChanges();

    expect(fixture.componentInstance.loading()).toBeFalse();
  });

  it('narrows the standard filter to non-critical and non-high urgency rows', () => {
    operationsService.getEligibilityQueue.and.returnValue(of({
      results: [
        buildSummary({ reliefrqst_id: 10, urgency_ind: 'C' }),
        buildSummary({ reliefrqst_id: 11, urgency_ind: 'H' }),
        buildSummary({ reliefrqst_id: 12, urgency_ind: 'M' }),
        buildSummary({ reliefrqst_id: 13, urgency_ind: 'L' }),
        buildSummary({ reliefrqst_id: 14, urgency_ind: null }),
        buildSummary({ reliefrqst_id: 15, urgency_ind: ' h ' as unknown as RequestSummary['urgency_ind'] }),
      ],
    }));

    const fixture = TestBed.createComponent(EligibilityReviewQueueComponent);
    fixture.detectChanges();

    fixture.componentInstance.setFilter('standard');
    fixture.detectChanges();

    const ids = fixture.componentInstance.filteredRequests().map((row) => row.reliefrqst_id).sort();
    expect(ids).toEqual([12, 13, 14]);
  });

  it('falls back to request_date when create_dtime is invalid instead of treating the row as brand new', () => {
    spyOn(Date, 'now').and.returnValue(Date.parse('2026-04-12T12:00:00Z'));
    operationsService.getEligibilityQueue.and.returnValue(of({
      results: [
        buildSummary({ reliefrqst_id: 21, tracking_no: 'RQ-21', create_dtime: '', request_date: '2026-04-10T00:00:00Z' }),
        buildSummary({ reliefrqst_id: 22, tracking_no: 'RQ-22', create_dtime: '2026-04-11T09:00:00Z' }),
        buildSummary({ reliefrqst_id: 23, tracking_no: 'RQ-23', create_dtime: 'not-a-date', request_date: '2026-04-09T08:00:00Z' }),
      ],
    }));

    const fixture = TestBed.createComponent(EligibilityReviewQueueComponent);
    fixture.detectChanges();
    const host: HTMLElement = fixture.nativeElement;
    const fallbackRow = fixture.componentInstance.filteredRequests().find((row) => row.reliefrqst_id === 23);

    expect(fixture.componentInstance.filteredRequests().map((row) => row.reliefrqst_id)).toEqual([22, 21, 23]);
    expect(fixture.componentInstance.metrics().find((metric) => metric.label === 'Oldest waiting (h)')?.value).toBe(76);
    expect(fallbackRow).toBeDefined();
    expect(fixture.componentInstance.requestTimestamp(fallbackRow!)).toBe('2026-04-09T08:00:00Z');
    expect(host.textContent).toContain(
      `Created ${fixture.componentInstance.formatOperationsDateTime('2026-04-09T08:00:00Z')}`,
    );
  });
});
