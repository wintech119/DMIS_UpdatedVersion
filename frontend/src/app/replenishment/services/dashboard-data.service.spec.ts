import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';

import { DashboardDataService } from './dashboard-data.service';
import { ReplenishmentService } from './replenishment.service';

describe('DashboardDataService', () => {
  let service: DashboardDataService;
  let replenishmentService: jasmine.SpyObj<ReplenishmentService>;

  beforeEach(() => {
    replenishmentService = jasmine.createSpyObj<ReplenishmentService>('ReplenishmentService', [
      'getStockStatusMulti',
    ]);

    TestBed.configureTestingModule({
      providers: [
        DashboardDataService,
        { provide: ReplenishmentService, useValue: replenishmentService },
      ],
    });

    service = TestBed.inject(DashboardDataService);
  });

  it('marks stock health as unavailable when the backend required quantity is missing', (done) => {
    replenishmentService.getStockStatusMulti.and.returnValue(of({
      event_id: 1,
      phase: 'SURGE',
      items: [
        {
          item_id: 11,
          item_name: 'Water Tabs',
          warehouse_id: 1,
          warehouse_name: 'North Hub',
          available_qty: 20,
          inbound_strict_qty: 5,
          burn_rate_per_hour: 0,
          required_qty: null,
          gap_qty: 0,
          warnings: [],
        } as never,
      ],
      as_of_datetime: '2026-03-19T10:00:00Z',
      warnings: [],
    }));

    service.getDashboardData(1, [1], 'SURGE').subscribe((result) => {
      expect(result.groups.length).toBe(1);
      const firstGroup = result.groups[0]!;
      const firstItem = firstGroup.items[0]!;
      expect(firstItem.stock_health!.level).toBe('UNAVAILABLE');
      done();
    });
  });
});
