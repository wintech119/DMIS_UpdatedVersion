import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router, convertToParamMap } from '@angular/router';
import { of } from 'rxjs';

import {
  NeedsListFulfillmentSourcesResponse,
  NeedsListResponse,
  NeedsListSummaryVersionResponse
} from '../models/needs-list.model';
import { AuthRbacService } from '../services/auth-rbac.service';
import { DmisNotificationService } from '../services/notification.service';
import { ReplenishmentService } from '../services/replenishment.service';
import { NeedsListFulfillmentTrackerComponent } from './needs-list-fulfillment-tracker.component';

describe('NeedsListFulfillmentTrackerComponent', () => {
  let fixture: ComponentFixture<NeedsListFulfillmentTrackerComponent>;
  let component: NeedsListFulfillmentTrackerComponent;

  let replenishmentService: jasmine.SpyObj<ReplenishmentService>;
  let notifications: jasmine.SpyObj<DmisNotificationService>;
  let router: jasmine.SpyObj<Router>;
  let authRbac: jasmine.SpyObj<AuthRbacService>;

  beforeEach(async () => {
    replenishmentService = jasmine.createSpyObj<ReplenishmentService>(
      'ReplenishmentService',
      ['getNeedsList', 'getNeedsListFulfillmentSources', 'getNeedsListSummaryVersion']
    );
    notifications = jasmine.createSpyObj<DmisNotificationService>(
      'DmisNotificationService',
      ['showError']
    );
    router = jasmine.createSpyObj<Router>('Router', ['navigate']);
    authRbac = jasmine.createSpyObj<AuthRbacService>('AuthRbacService', ['load', 'hasPermission']);
    authRbac.hasPermission.and.returnValue(true);

    replenishmentService.getNeedsList.and.returnValue(of({
      event_id: 1,
      phase: 'SURGE',
      items: [],
      as_of_datetime: '2026-03-17T12:00:00Z',
      status: 'APPROVED'
    } satisfies NeedsListResponse));
    replenishmentService.getNeedsListFulfillmentSources.and.returnValue(of({
      needs_list_id: 'NL-1',
      lines: []
    } satisfies NeedsListFulfillmentSourcesResponse));
    replenishmentService.getNeedsListSummaryVersion.and.returnValue(of({
      needs_list_id: 'NL-1',
      status: 'APPROVED',
      last_updated_at: '2026-03-17T12:00:00Z',
      data_version: 'v1'
    } satisfies NeedsListSummaryVersionResponse));

    await TestBed.configureTestingModule({
      imports: [NeedsListFulfillmentTrackerComponent],
      providers: [
        { provide: ReplenishmentService, useValue: replenishmentService },
        { provide: DmisNotificationService, useValue: notifications },
        { provide: Router, useValue: router },
        { provide: AuthRbacService, useValue: authRbac },
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: {
              url: [],
              queryParamMap: convertToParamMap({})
            },
            paramMap: of(convertToParamMap({ id: 'NL-1' }))
          }
        }
      ]
    }).overrideComponent(NeedsListFulfillmentTrackerComponent, {
      set: { template: '' }
    }).compileComponents();
  });

  afterEach(() => {
    fixture?.destroy();
  });

  it('recomputes freshness summaries as time passes', () => {
    fixture = TestBed.createComponent(NeedsListFulfillmentTrackerComponent);
    component = fixture.componentInstance;

    const initialNow = new Date('2026-03-17T12:00:00Z').getTime();
    component.lastSyncedAt.set('2026-03-17T11:30:00Z');
    (component as unknown as { now: { set: (value: number) => void } }).now.set(initialNow);

    expect(component.dataFreshness()).toBe('high');
    expect(component.lastSyncedRelative()).toBe('30m ago');

    const laterNow = new Date('2026-03-17T19:00:00Z').getTime();
    (component as unknown as { now: { set: (value: number) => void } }).now.set(laterNow);

    expect(component.dataFreshness()).toBe('low');
    expect(component.lastSyncedRelative()).toBe('7h 30m ago');
  });

  it('keeps dormant tracker language scoped to replenishment sourcing', () => {
    fixture = TestBed.createComponent(NeedsListFulfillmentTrackerComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();

    const title = component.pageTitle();
    const subtitle = component.pageSubtitle();
    const allocationDescription = component.allocationActionDescription();
    const normalizedAllocationDescription = allocationDescription.toLowerCase();

    expect(title).toBe('Sourcing Tracker');
    expect(subtitle).toBe('Track replenishment sourcing progress');
    expect(normalizedAllocationDescription).toContain('replenishment');
    expect(normalizedAllocationDescription).not.toContain('relief request');
    expect(normalizedAllocationDescription).not.toContain('request and package');
  });
});
