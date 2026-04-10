import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap } from '@angular/router';
import { MatDialog } from '@angular/material/dialog';
import { Router } from '@angular/router';
import { signal } from '@angular/core';
import { of } from 'rxjs';

import { NeedsListReviewDetailComponent } from './needs-list-review-detail.component';
import { AuthRbacService } from '../services/auth-rbac.service';
import { ReplenishmentService } from '../services/replenishment.service';
import { DmisNotificationService } from '../services/notification.service';
import { DataFreshnessService } from '../services/data-freshness.service';
import { NeedsListResponse } from '../models/needs-list.model';

describe('NeedsListReviewDetailComponent', () => {
  let fixture: ComponentFixture<NeedsListReviewDetailComponent>;
  let component: NeedsListReviewDetailComponent;

  let replenishmentService: jasmine.SpyObj<ReplenishmentService>;
  let notificationService: jasmine.SpyObj<DmisNotificationService>;
  let dataFreshnessService: jasmine.SpyObj<DataFreshnessService>;
  let router: jasmine.SpyObj<Router>;

  const needsListResponse: NeedsListResponse = {
    event_id: 1,
    event_name: 'Storm',
    phase: 'SURGE',
    warehouse_ids: [10, 11],
    warehouses: [
      { warehouse_id: 10, warehouse_name: 'North Depot' },
      { warehouse_id: 11, warehouse_name: 'South Depot' }
    ],
    items: [
      {
        item_id: 1,
        item_name: 'Tarpaulin',
        warehouse_id: 10,
        warehouse_name: 'North Depot',
        available_qty: 10,
        inbound_strict_qty: 0,
        burn_rate_per_hour: 1,
        gap_qty: 5,
        severity: 'WARNING',
        freshness: {
          state: 'LOW',
          age_hours: 14,
          inventory_as_of: '2026-03-17T10:00:00Z'
        },
        horizon: {
          A: { recommended_qty: 0 },
          B: { recommended_qty: 0 },
          C: { recommended_qty: 5 }
        }
      },
      {
        item_id: 2,
        item_name: 'Blanket',
        warehouse_id: 11,
        warehouse_name: 'South Depot',
        available_qty: 50,
        inbound_strict_qty: 5,
        burn_rate_per_hour: 0.5,
        gap_qty: 3,
        severity: 'CRITICAL',
        freshness: {
          state: 'MEDIUM',
          age_hours: 5,
          inventory_as_of: '2026-03-17T12:00:00Z'
        },
        horizon: {
          A: { recommended_qty: 1 },
          B: { recommended_qty: 2 },
          C: { recommended_qty: 3 }
        }
      }
    ],
    as_of_datetime: '2026-03-17T12:30:00Z',
    needs_list_id: 'NL-1',
    needs_list_no: 'NL-0001',
    status: 'SUBMITTED'
  };

  beforeEach(async () => {
    replenishmentService = jasmine.createSpyObj<ReplenishmentService>(
      'ReplenishmentService',
      ['getNeedsList', 'approveNeedsList', 'rejectNeedsList', 'returnNeedsList', 'escalateNeedsList', 'sendReviewReminder']
    );
    replenishmentService.getNeedsList.and.returnValue(of(needsListResponse));

    notificationService = jasmine.createSpyObj<DmisNotificationService>(
      'DmisNotificationService',
      ['showError', 'showWarning', 'showSuccess']
    );

    dataFreshnessService = jasmine.createSpyObj<DataFreshnessService>(
      'DataFreshnessService',
      ['clear', 'updateFromWarehouseEntries']
    );

    router = jasmine.createSpyObj<Router>('Router', ['navigate']);
    const authRbac = {
      roles: signal(['EXECUTIVE']),
      permissions: signal([
        'replenishment.needs_list.approve',
        'replenishment.needs_list.reject',
        'replenishment.needs_list.return',
        'replenishment.needs_list.escalate',
      ]),
      actorRef: signal('EMP-123'),
    };

    await TestBed.configureTestingModule({
      imports: [NeedsListReviewDetailComponent],
      providers: [
        { provide: ReplenishmentService, useValue: replenishmentService },
        { provide: DmisNotificationService, useValue: notificationService },
        { provide: DataFreshnessService, useValue: dataFreshnessService },
        { provide: AuthRbacService, useValue: authRbac },
        { provide: Router, useValue: router },
        { provide: MatDialog, useValue: jasmine.createSpyObj<MatDialog>('MatDialog', ['open']) },
        {
          provide: ActivatedRoute,
          useValue: {
            paramMap: of(convertToParamMap({ id: 'NL-1' }))
          }
        }
      ]
    }).overrideComponent(NeedsListReviewDetailComponent, {
      set: { template: '' }
    }).compileComponents();

    fixture = TestBed.createComponent(NeedsListReviewDetailComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('updates the freshness banner from the loaded needs list items', () => {
    expect(dataFreshnessService.clear).toHaveBeenCalled();
    expect(dataFreshnessService.updateFromWarehouseEntries).toHaveBeenCalledWith([
      {
        warehouse_id: 10,
        warehouse_name: 'North Depot',
        freshness: 'LOW',
        last_sync: '2026-03-17T10:00:00Z',
        age_hours: 14
      },
      {
        warehouse_id: 11,
        warehouse_name: 'South Depot',
        freshness: 'MEDIUM',
        last_sync: '2026-03-17T12:00:00Z',
        age_hours: 5
      }
    ]);
    expect(component.hasFreshnessData()).toBeTrue();
  });

  it('uses the actual horizon allocation for review-screen stockout guidance', () => {
    const procurementGuidance = component.stockoutData(needsListResponse.items[0]);
    const mixedGuidance = component.stockoutData(needsListResponse.items[1]);

    expect(procurementGuidance.recommendedAction).toEqual({
      label: 'Procurement (Horizon C)',
      icon: 'shopping_cart',
      detail: 'Use the procurement allocation shown in the Horizon C column.'
    });
    expect(mixedGuidance.recommendedAction).toEqual({
      label: 'Mixed allocation (Horizons A/B/C)',
      icon: 'alt_route',
      detail: 'This line uses multiple replenishment paths based on the backend allocation shown in the Horizon A/B/C columns: A/B/C.'
    });
  });
});
