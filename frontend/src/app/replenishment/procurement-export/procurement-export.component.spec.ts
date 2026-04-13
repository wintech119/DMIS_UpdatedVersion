import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router, convertToParamMap } from '@angular/router';
import { of, throwError } from 'rxjs';

import { ProcurementExportComponent } from './procurement-export.component';
import { NeedsListResponse } from '../models/needs-list.model';
import { DmisNotificationService } from '../services/notification.service';
import { ReplenishmentService } from '../services/replenishment.service';

describe('ProcurementExportComponent', () => {
  let fixture: ComponentFixture<ProcurementExportComponent>;
  let component: ProcurementExportComponent;

  let replenishmentService: jasmine.SpyObj<ReplenishmentService>;
  let notifications: jasmine.SpyObj<DmisNotificationService>;
  let router: jasmine.SpyObj<Router>;

  beforeEach(async () => {
    replenishmentService = jasmine.createSpyObj<ReplenishmentService>(
      'ReplenishmentService',
      ['getNeedsList', 'exportProcurementNeeds']
    );
    notifications = jasmine.createSpyObj<DmisNotificationService>(
      'DmisNotificationService',
      ['showError', 'showSuccess']
    );
    router = jasmine.createSpyObj<Router>('Router', ['navigate']);

    replenishmentService.getNeedsList.and.returnValue(of({
      event_id: 1,
      phase: 'BASELINE',
      items: [
        {
          item_id: 300,
          item_name: 'Generator',
          uom_code: 'EA',
          available_qty: 0,
          inbound_strict_qty: 0,
          burn_rate_per_hour: 1,
          gap_qty: 3,
          horizon: {
            A: { recommended_qty: 0 },
            B: { recommended_qty: 0 },
            C: { recommended_qty: 3 },
          },
          procurement: {
            recommended_qty: 3,
            est_unit_cost: 100,
            est_total_cost: 300,
            lead_time_hours_default: 336,
          },
        },
      ],
      as_of_datetime: '2026-04-10T12:00:00Z',
    } satisfies NeedsListResponse));

    await TestBed.configureTestingModule({
      imports: [ProcurementExportComponent],
      providers: [
        { provide: ReplenishmentService, useValue: replenishmentService },
        { provide: DmisNotificationService, useValue: notifications },
        { provide: Router, useValue: router },
        {
          provide: ActivatedRoute,
          useValue: {
            paramMap: of(convertToParamMap({ id: 'NL-2' })),
          },
        },
      ],
    }).overrideComponent(ProcurementExportComponent, {
      set: { template: '' },
    }).compileComponents();

    fixture = TestBed.createComponent(ProcurementExportComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('shows the job-aware failure message when export polling fails', () => {
    replenishmentService.exportProcurementNeeds.and.returnValue(
      throwError(() => new Error('Export job job-77 failed: worker unavailable'))
    );

    component.exportAs('csv');

    expect(replenishmentService.exportProcurementNeeds).toHaveBeenCalledWith('NL-2', 'csv');
    expect(notifications.showError).toHaveBeenCalledWith(
      'Export job job-77 failed: worker unavailable'
    );
    expect(component.exporting()).toBeFalse();
  });
});
